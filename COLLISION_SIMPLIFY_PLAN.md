# Collision simplification — IVP compact-surface format + plan

The biggest remaining accuracy gap is that solid collision geometry is copied
verbatim instead of being simplified the way Valve's vphysics did at build time
(`SimplifyCollide` in the SDK's `simplify.cpp`). This is the spec + plan for closing it.

## Key realization

`simplify.cpp` line ~443: **"IVP internally used QHull to generate the convexes."**
`scipy.spatial.ConvexHull` *is* Qhull — the same hull library. So the earlier claim
that this needs the proprietary IVP engine and is "impossible in pure Python" was wrong
on both counts: the simplification is portable geometry, and the hull library ships with
scipy. A native exe (porting `Physics_Collision.cpp`'s Bullet-based `CollideWrite`) is the
alternative Valve-style path, but Bullet's hull ordering differs from Qhull, so the
Python+scipy route is actually *closer* to Valve's exact output.

## IVP compact-surface binary layout (verified against powerbox.phy solid 0)

Per-solid collide data (the `cs` bytes after each solid's int size prefix in a .phy):

```
compactsurfaceheader_t (28 bytes)
  +0   int   vphysicsID    'VPHY'
  +4   int   version       256 (0x100)
  +8   int   surfaceSize    size of the surface payload
  +12  float dragAxisAreas[3]
  +24  int   axisMapSize

ivpcompactsurface_t (starts +28)
  +28  float mass_center[3]
  +40  float rotation_inertia[3]
  +52  float upper_limit_radius      (bounding radius)
  +56  int   bf1  (byte_size:8 | dummy/size:24)
  +60  int   offset_ledgetree_root   (relative to +28)
  +64  int   dummy[3]                 dummy[2] @+72 = 'IVPS' magic

ivpcompactledge_t (16 bytes; one per convex)
  +0   int   c_point_offset           (relative to the ledge; -> points array)
  +4   int   ledgetree_node_offset
  +8   int   bf1  (is_compact:2 | dummy:2 | size_div16:4 | n_points-ish:24)
  +12  short n_triangles
  +14  short for_future_use

ivpcompacttriangle_t (16 bytes; n_triangles of them, right after the ledge header)
  +0   int   bf1 (tri_index:12 | pierce_index:12 | material:7 | is_virtual:1)
  then 3x ivpcompactedge_t (4 bytes each):
       int   bf1 (start_point_index:16 | opposite_index:15 | is_virtual:1)

points: at ledge + c_point_offset, each = 4 floats (16 bytes, w is padding).
        n_points = max(start_point_index over all edges) + 1.
```

## Plan

1. **Parse** (foundation, started): walk surface -> ledgetree root -> compact ledge(s) ->
   triangles -> points; recover each convex as a vertex list + face list.
2. **Round-trip test**: re-serialize the parsed structure and confirm byte-identical to the
   input. This MUST pass before simplifying (proves the writer is correct; the Xbox rejects
   malformed ledges).
3. **Simplify**: port `simplify.cpp`'s `SimplifyConvexFromVerts` — seed with the 6 AABB
   planes, iteratively add the candidate plane that most reduces the extent error until
   within `tolerance` (default 0.25 in/SDK), rebuild the hull via scipy Qhull.
4. **Re-emit** the simplified convex as a compact ledge (new points + triangles + tree node).
5. **Verbatim fallback** (matches Valve exactly — `simplify.cpp` line 441): if the simplified
   collide isn't smaller than the input, copy the input verbatim.
6. **Validate** against the GT suite: compare simplified solid sizes to Valve's. Target is
   size/shape parity (byte-exact is unlikely due to Qhull vertex ordering, but functional
   parity + Valve-like sizes is the win).

## Decision pending

Python+scipy (same Qhull IVP used, stays in the toolchain) vs a native exe (port the
Bullet `CollideWrite` from `Physics_Collision.cpp`; heavier Source-SDK build, hull ordering
differs from Valve's). Leaning Python for the reasons above.

## DECODED: full single-convex serialization spec (verified on powerbox.phy)

Parser is working (verts + triangles + connectivity recovered; scipy/Qhull reproduces
IVP's 8-vert/12-tri box exactly). Everything needed to WRITE a solid is now pinned:

- **Half-edge `opposite_index`** (15-bit signed): offset, in 4-byte int units, from the
  current edge's position to its opposite half-edge, within the triangle stream (tri header
  = 1 int, each edge = 1 int; edge k of tri t is at int-index t*4+1+k). Verified mutual
  (tri0 e0 ->+6-> tri1 e2 ->-6-> back). Regenerate from triangle adjacency on the (b->a)
  reverse directed edge.
- **Points**: 4 floats each, w = 0.
- **Triangle header bf1**: tri_index (sequential), pierce_index:12, material:7, is_virtual:1.
  `pierce_index` is IVP's raycast acceleration index — NOT cleanly regenerable; start with a
  heuristic (0 or self-index) and hardware-test whether ray/pierce collision still behaves.
- **Ledge `bf1`**: 24-bit field = total ledge byte size / 16 (header16 + tris + points).
- **Tree node** (terminal, 28 bytes): off_right=0, off_compact_ledge = -(node_pos - ledge_pos),
  center = hull center, radius = max vertex distance to center.
- **`ivpcompactsurface`**: mass_center, rotation_inertia, upper_limit_radius, dragAxisAreas
  are IVP-computed; recompute via standard convex mass-property formulas (functional, not
  byte-identical to Valve — acceptable since the simplified hull differs anyway).

Byte-identical to Valve is NOT the target (Qhull vertex/triangle ordering differs from
Valve's stored order); a VALID IVP solid of the simplified hull is. Validation path:
re-parse our output (self-consistency) + Valve-like solid sizes vs GT + hardware accept.

Remaining build: (1) writer from (verts,tris) using the spec above; (2) port
`SimplifyConvexFromVerts`; (3) wire into phy2phx as an opt-in pass with the verbatim
fallback; (4) GT size-parity + hardware validation.
