#!/usr/bin/env python3
"""
vvd_multilod.py - PC v44 VVD -> Xbox v47 VVD, multi-LOD aware.

Ports Valve's Clamp_RootLOD / Studio_LoadVertexes (studio.h) for the Original
Xbox (g_minLod = 2). Authoritative behavior, confirmed against the regression
suite:

  rootLOD = min(2, numLODs-1)
  keep    = numLODVertexes[rootLOD]          (verts are lod-sorted, low-detail first)
  numLODVertexes[0..rootLOD-1] = keep        (flattened; >= rootLOD unchanged)
  vertex/tangent blocks: first `keep` records

For SINGLE-MESH models (numFixups == 0) the kept block is contiguous: a straight
truncation of the PC vertex pool to the first `keep` records. We keep PC vertex
ORDER (rather than Valve's per-model strip permutation); the matching VTX rootLOD
chain indexes [0,keep) so the pair is self-consistent and renders. Byte layout
of each 48B mstudiovertex_t / 16B tangent is unchanged PC<->Xbox.

MULTI-MESH (numFixups > 0) models need the fixup re-gather + (for skinned LODs)
bone-index remap; that path raises NotImplementedError here (Alyx milestone).
"""
import struct

HDR = 64; VERT = 48; TAN = 16; MINLOD = 2; MAX_LODS = 8

def I(d, o): return struct.unpack_from("<i", d, o)[0]

def analyze(d):
    assert d[0:4] == b"IDSV", "not a VVD"
    return dict(version=I(d,4), checksum=I(d,8), numLODs=I(d,12),
                lodv=[I(d,16+4*k) for k in range(MAX_LODS)],
                numFixups=I(d,48), fixupStart=I(d,52),
                vstart=I(d,56), tstart=I(d,60), size=len(d))

def convert(pc_path, out_path, force_checksum=None, collapse=False, vert_perm=None, root_lod=None):
    """collapse=False: preserve numLODs (Valve structure, +64B pad, flatten <root).
       collapse=True : emit a clean single-LOD VVD carrying the rootLOD vertex set
                       (numLODs=1, no pad) for full MDL/VVD/VTX consistency with a
                       single-LOD VTX template.
       vert_perm     : optional list of length `keep`, perm[new]=old, reordering the
                       kept verts/tangents for vertex-fetch locality (Valve's
                       ComputeVertexPermutation). Caller must remap VTX origMeshVertIDs
                       with the matching inverse so the pair stays self-consistent."""
    d = open(pc_path, "rb").read()
    h = analyze(d)
    if h["numFixups"] != 0:
        raise NotImplementedError(
            f"{pc_path}: numFixups={h['numFixups']} (multi-mesh) needs the "
            "fixup re-gather + bone remap path (skinned/Alyx milestone)")

    rootLOD = min(MINLOD if root_lod is None else root_lod, h["numLODs"] - 1)
    keep    = h["lodv"][rootLOD]
    checksum = h["checksum"] if force_checksum is None else force_checksum

    vsrc = d[h["vstart"]: h["vstart"] + keep * VERT]
    tsrc = d[h["tstart"]: h["tstart"] + keep * TAN]
    assert len(vsrc) == keep * VERT, "vertex block short read"
    assert len(tsrc) == keep * TAN, "tangent block short read"
    if vert_perm is not None:
        assert len(vert_perm) == keep, "vert_perm length must equal keep"
        vblock = b"".join(vsrc[old*VERT:(old+1)*VERT] for old in vert_perm)
        tblock = b"".join(tsrc[old*TAN:(old+1)*TAN] for old in vert_perm)
    else:
        vblock, tblock = vsrc, tsrc

    out_numLODs = 1 if collapse else h["numLODs"]
    new_vstart = 80                               # 16-aligned (matches Xbox)
    new_tstart = new_vstart + len(vblock)
    # Prefetch reserve: Studio_VertexDataSize reserves +1 vertex (48B) + 1 tangent
    # (16B) = 64B so the loader can read-ahead without faulting. Empirically the
    # on-disk file carries exactly 64 trailing zero bytes whenever a clamp ran
    # (numLODs > 1); single-LOD files carry none (879/879 in the suite).
    pad = 64 if out_numLODs > 1 else 0
    out = bytearray(new_tstart + len(tblock) + pad)

    struct.pack_into("<i", out, 0, 0x56534449)    # "IDSV"
    struct.pack_into("<i", out, 4, h["version"])
    struct.pack_into("<i", out, 8, checksum)
    struct.pack_into("<i", out, 12, out_numLODs)
    # numLODVertexes: flatten [0..rootLOD-1] to keep; keep real values >= rootLOD.
    # In collapse mode all entries become keep (single-LOD form).
    flat = list(h["lodv"])
    for k in range(rootLOD):
        flat[k] = keep
    if collapse:
        flat = [keep]*MAX_LODS
    for k in range(MAX_LODS):
        struct.pack_into("<i", out, 16 + 4*k, flat[k])
    struct.pack_into("<i", out, 48, 0)            # numFixups
    struct.pack_into("<i", out, 52, 68)           # fixupTableStart
    struct.pack_into("<i", out, 56, new_vstart)
    struct.pack_into("<i", out, 60, new_tstart)
    out[new_vstart:new_vstart+len(vblock)] = vblock
    out[new_tstart:new_tstart+len(tblock)] = tblock
    open(out_path, "wb").write(out)
    return bytes(out), dict(rootLOD=rootLOD, keep=keep, numLODs=h["numLODs"])

if __name__ == "__main__":
    import sys
    out, info = convert(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else "/tmp/out.vvd")
    print(f"rootLOD={info['rootLOD']} keep={info['keep']} numLODs={info['numLODs']} -> {len(out)}B")
