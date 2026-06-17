"""IVP compact-surface (.phy/.phx solid) parser + writer, for collision simplification.

A .phy solid's collide payload is an IVP "compact surface": a header, a binary ledge
tree, and one or more convex "ledges" (each = points + triangles with half-edge
connectivity). Format reverse-engineered from the Source SDK vphysics sources and
verified byte-for-byte against shipped models (see COLLISION_SIMPLIFY_PLAN.md).

parse_surface(collide) -> Surface  (list of Convex, each with .verts and .tris)
write_surface(convexes, meta)      -> collide bytes (valid IVP of those convexes)
"""
import struct
from dataclasses import dataclass, field

IVPS = 0x53505649  # 'IVPS'

SURF_HDR = 28      # compactsurfaceheader_t
SURF = 28          # ivpcompactsurface_t starts here
LEDGE_HDR = 16
TRI = 16
EDGE = 4
PT = 16
NODE = 28


@dataclass
class Convex:
    verts: list           # [(x,y,z), ...]
    tris: list            # [(a,b,c), ...] point indices (winding preserved)
    pierce: list = field(default_factory=list)   # per-tri pierce_index (opaque)


@dataclass
class Surface:
    convexes: list
    mass_center: tuple = (0.0, 0.0, 0.0)
    rotation_inertia: tuple = (1.0, 1.0, 1.0)
    upper_limit_radius: float = 0.0
    drag_axis_areas: tuple = (1.0, 1.0, 1.0)
    surf_bf1: int = 0
    dummy: tuple = (0, 0, IVPS)
    vphysics_id: int = 0x59485056   # 'VPHY'
    version: int = 256
    model_type: int = 0
    axis_map_size: int = 0


def _f3(b, o):
    return struct.unpack_from("<3f", b, o)


def _parse_ledge(c, ledge):
    c_point_offset, lt_node_off, lbf1 = struct.unpack_from("<iii", c, ledge)
    n_tri = struct.unpack_from("<h", c, ledge + 12)[0]
    pbase = ledge + c_point_offset
    tris, pierce = [], []
    maxidx = -1
    for t in range(n_tri):
        to = ledge + LEDGE_HDR + t * TRI
        thdr = struct.unpack_from("<I", c, to)[0]
        pierce.append((thdr >> 12) & 0xfff)
        idxs = []
        for k in range(3):
            ei = struct.unpack_from("<I", c, to + 4 + k * EDGE)[0]
            spi = ei & 0xffff
            idxs.append(spi)
            maxidx = max(maxidx, spi)
        tris.append(tuple(idxs))
    npts = maxidx + 1
    verts = [_f3(c, pbase + i * PT) for i in range(npts)]
    return Convex(verts=verts, tris=tris, pierce=pierce)


def _walk_tree(c, node, out):
    """Collect every leaf ledge under a ledge-tree node (binary tree)."""
    off_right, off_ledge = struct.unpack_from("<ii", c, node)
    if off_right == 0:                      # terminal node -> one ledge
        out.append(node + off_ledge)
    else:
        _walk_tree(c, node + NODE, out)     # left child immediately follows
        _walk_tree(c, node + off_right, out)


def parse_surface(c):
    """c = a solid's collide payload (the `size` bytes after the .phy per-solid prefix)."""
    surf_bf1 = struct.unpack_from("<i", c, SURF + 28)[0]
    off_ltroot = struct.unpack_from("<i", c, SURF + 32)[0]
    mc = _f3(c, SURF)
    ri = _f3(c, SURF + 12)
    ulr = struct.unpack_from("<f", c, SURF + 24)[0]
    drag = _f3(c, 12)
    dummy = struct.unpack_from("<3i", c, SURF + 36)
    vphysics_id, = struct.unpack_from("<i", c, 0)
    version, model_type = struct.unpack_from("<hh", c, 4)
    axis_map_size, = struct.unpack_from("<i", c, 24)
    ledge_offs = []
    _walk_tree(c, SURF + off_ltroot, ledge_offs)
    convexes = [_parse_ledge(c, lo) for lo in ledge_offs]
    return Surface(convexes=convexes, mass_center=mc, rotation_inertia=ri,
                   upper_limit_radius=ulr, drag_axis_areas=drag,
                   surf_bf1=surf_bf1, dummy=dummy, vphysics_id=vphysics_id,
                   version=version, model_type=model_type, axis_map_size=axis_map_size)


def _write_ledge(verts, tris, pierce):
    """Serialize one convex as: ledge header + triangles + points. Returns bytes.
    Regenerates the half-edge opposite_index from triangle adjacency."""
    n_tri = len(tris)
    # directed-edge -> int-index within the triangle stream (tri hdr=1 int, edges follow)
    pos = {}
    for t, (a, b, c) in enumerate(tris):
        verts_cyc = (a, b, c)
        for k in range(3):
            u, v = verts_cyc[k], verts_cyc[(k + 1) % 3]
            pos[(u, v)] = t * 4 + 1 + k
    out = bytearray()
    c_point_offset = LEDGE_HDR + n_tri * TRI
    ledge_size = c_point_offset + len(verts) * PT
    # ledge header: c_point_offset, ledgetree_node_offset(=1 sentinel), bf1, n_tri, future
    bf1 = ((ledge_size // 16) << 8) | 0x04   # 24-bit size/16; low byte is a constant 0x04
    out += struct.pack("<iiihh", c_point_offset, 1, bf1, n_tri, 0)
    for t, (a, b, c) in enumerate(tris):
        thdr = (t & 0xfff) | ((pierce[t] if t < len(pierce) else 0) & 0xfff) << 12
        out += struct.pack("<I", thdr)
        verts_cyc = (a, b, c)
        for k in range(3):
            u, v = verts_cyc[k], verts_cyc[(k + 1) % 3]
            this_pos = t * 4 + 1 + k
            opp = pos.get((v, u))
            off = 0 if opp is None else (opp - this_pos)
            out += struct.pack("<I", (u & 0xffff) | ((off & 0x7fff) << 16))
    for (x, y, z) in verts:
        out += struct.pack("<4f", x, y, z, 0.0)
    return bytes(out)


def write_surface(surf):
    """Serialize a Surface back to a solid collide payload. Single-convex only for now
    (multi-convex ledge-tree emission is a follow-up). Returns the `size`-prefixed-free
    collide bytes (caller prepends the per-solid size)."""
    if len(surf.convexes) != 1:
        raise NotImplementedError(f"{len(surf.convexes)}-convex surface (tree build TBD)")
    cx = surf.convexes[0]
    ledge = _write_ledge(cx.verts, cx.tris, cx.pierce)
    ledge_pos = SURF_HDR + 48                      # after surface header + ivpcompactsurface
    node_pos = ledge_pos + len(ledge)
    # terminal ledge-tree node (28B): off_right=0, off_compact_ledge -> back to ledge
    import math
    xs = [v[0] for v in cx.verts]; ys = [v[1] for v in cx.verts]; zs = [v[2] for v in cx.verts]
    ctr = ((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2)
    rad = max(math.dist(v, ctr) for v in cx.verts)
    he = (max(max(xs)-ctr[0], ctr[0]-min(xs)),
          max(max(ys)-ctr[1], ctr[1]-min(ys)),
          max(max(zs)-ctr[2], ctr[2]-min(zs)))
    # box_sizes: per-axis half-extent quantized by radius/255; ceil = conservative bound
    box = bytes(min(255, math.ceil(he[i] / rad * 255)) if rad > 0 else 0 for i in range(3))
    node = struct.pack("<ii3ff", 0, ledge_pos - node_pos, *ctr, rad) + box + b"\x00"
    # ivpcompactsurface (48B)
    off_ltroot = node_pos - SURF_HDR               # relative to surface base (+28)
    surface = struct.pack("<3f3ffii3i", *surf.mass_center, *surf.rotation_inertia,
                          surf.upper_limit_radius, surf.surf_bf1, off_ltroot, *surf.dummy)
    body = surface + ledge + node
    surface_size = len(body) + 0                   # payload after the 28B header... see below
    # compactsurfaceheader (28B): vphysicsID, version(h), modelType(h), surfaceSize,
    # dragAxisAreas(3f), axisMapSize. surfaceSize counts from ivpcompactsurface to end.
    hdr = struct.pack("<ihhi3fi", surf.vphysics_id, surf.version, surf.model_type,
                      len(body), *surf.drag_axis_areas, surf.axis_map_size)
    return hdr + body


# ---------------------------------------------------------------------------
# Simplification — port of the SDK's SimplifyConvexFromVerts (simplify.cpp):
# seed with the 6 AABB planes, then greedily add the face plane that most reduces
# the hull's overshoot past the true surface, until within tolerance. IVP used
# QHull; scipy.spatial is QHull, so this stays faithful to Valve's pipeline.
# ---------------------------------------------------------------------------
def simplify_convex(verts, tolerance=0.25):
    import numpy as np
    from scipy.spatial import ConvexHull, HalfspaceIntersection
    V = np.asarray(verts, float)
    if len(V) <= 8:                      # simplify.cpp: can't simplify <= 8 verts
        return verts
    try:
        hull = ConvexHull(V)
    except Exception:
        return verts
    mins, maxs = V.min(0), V.max(0)
    interior = (mins + maxs) / 2.0
    # candidate planes as (normal, dist) with outward normals, dist = max support
    planes = []
    for ax in range(3):
        n = np.zeros(3); n[ax] = 1.0;  planes.append((n.copy(), maxs[ax], True))
        n = np.zeros(3); n[ax] = -1.0; planes.append((n.copy(), -mins[ax], True))
    seen = {tuple(np.round(p[0], 4)) for p in planes}
    for eq in hull.equations:            # face planes: normal . x + d <= 0  ->  n=eq[:3], dist=-eq[3]
        n = eq[:3]; key = tuple(np.round(n, 4))
        if key in seen:
            continue
        seen.add(key)
        planes.append((n.copy(), -eq[3], False))

    def build(active):
        hs = np.array([[*p[0], -p[1]] for p in active])    # n.x - dist <= 0
        try:
            hi = HalfspaceIntersection(hs, interior)
            return hi.intersections
        except Exception:
            return None

    def support(pts, d):
        return float(np.max(pts @ d))

    active = [p for p in planes if p[2]]
    cand = [i for i, p in enumerate(planes) if not p[2]]
    for _ in range(len(V)):
        pts = build(active)
        if pts is None:
            break
        best_i, best_gain = -1, tolerance
        for i in cand:
            n, dist, _ = planes[i]
            gain = support(pts, n) - dist          # how far the current hull overshoots this face
            if gain > best_gain:
                best_gain, best_i = gain, i
        if best_i < 0:
            break
        active.append((planes[best_i][0], planes[best_i][1], True))
        cand.remove(best_i)

    pts = build(active)
    if pts is None or len(pts) < 4 or len(pts) >= len(V):
        return verts                                # no win -> caller keeps original
    return [tuple(p) for p in pts]


def _hull_tris(points):
    """Convex-hull a point set into (verts, tris) with consistent OUTWARD winding so
    every directed edge (u,v) has its reverse (v,u) — required for valid half-edges."""
    import numpy as np
    from scipy.spatial import ConvexHull
    P = np.asarray(points, float)
    h = ConvexHull(P)
    verts = [tuple(P[i]) for i in h.vertices]
    remap = {old: i for i, old in enumerate(h.vertices)}
    hv = np.array([P[i] for i in h.vertices])
    tris = []
    for si, simplex in enumerate(h.simplices):
        a, b, c = (remap[v] for v in simplex)
        nrm = np.cross(hv[b] - hv[a], hv[c] - hv[a])
        if np.dot(nrm, h.equations[si][:3]) < 0:   # flip to match outward face normal
            b, c = c, b
        tris.append((a, b, c))
    return verts, tris


def simplify_surface(surf, tolerance=0.25):
    """Return a new Surface with each convex simplified + re-hulled, or the original
    convex where simplification didn't reduce it. Single-convex only for now."""
    new = []
    for cx in surf.convexes:
        sv = simplify_convex(cx.verts, tolerance)
        if len(sv) >= len(cx.verts):
            new.append(cx)                          # verbatim fallback (matches simplify.cpp)
            continue
        verts, tris = _hull_tris(sv)
        new.append(Convex(verts=verts, tris=tris, pierce=[0] * len(tris)))
    import copy
    out = copy.copy(surf); out.convexes = new
    return out
