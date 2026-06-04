#!/usr/bin/env python3
"""
lod_convert.py - Multi-LOD PC->Xbox converter (LOD vertex stripping).

Adds MULTI-LOD support to the Original Xbox (v47) prop pipeline. The Xbox
compiler runs with g_minLod = 2 (studiomdl.cpp: -xbox sets g_bXbox/g_minLod=2),
which clamps every model to rootLOD = min(2, numLODs-1) via Clamp_RootLOD ->
Studio_LoadVertexes (studio.h). That is the "vertex stripping": the high-detail
LOD0/LOD1 vertices are dropped and the model renders at LOD2's smaller vertex
set -- the memory win the Xbox build exists for.

This tool takes a multi-LOD PC prop (.vvd + .dx90.vtx + .mdl) and emits a clean,
self-consistent SINGLE-LOD Xbox triplet carrying the rootLOD geometry, so it flows
through the proven single-LOD pipeline (MDL/VVD/VTX all agree numLODs=1).

Scope (validated 872/872 in the regression suite): single bodypart/model, single
mesh, single stripgroup at rootLOD, single-bone (static) props with numFixups==0.

Out of scope (later milestones, detected and rejected cleanly):
  - numFixups>0 (multi-mesh): needs the Studio_LoadVertexes fixup re-gather.
  - skinned models with LOD bone reduction: Clamp_MDL_LODS remaps vertex bone
    indices (e.g. stalker vert0 bone[3] 0b0c09 -> 090a08); geometry identical,
    bone indices change. -> Alyx/skinned milestone.

Key cracked facts (all verified against the suite):
  * PC shipping .vvd is already LOD-sorted (low-detail first) + fixup table.
  * Xbox keeps numLODVertexes[rootLOD] verts; numFixups always collapses to 0.
  * Xbox VTX vertex & index records are BYTE-IDENTICAL copies of the PC dx90
    records (no repack) -- the chain header is the only console-packed part.
  * Valve's Xbox files were compiled independently from source, so their exact
    LOD vertex order/count is NOT reproducible from the PC files in general; the
    correct oracle is self-consistency (VTX indices resolve into the VVD set),
    which is what renders -- the same basis as the proven single-LOD successes.
"""
import struct, os, sys, importlib.util

def _load(n, p):
    s = importlib.util.spec_from_file_location(n, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

_here = os.path.dirname(os.path.abspath(__file__))
vvd  = _load("vvd_multilod",   os.path.join(_here, "vvd_multilod.py"))
ext  = _load("vtx_lod_extract",os.path.join(_here, "vtx_lod_extract.py"))
emit = _load("vtx_emit_skinned", os.path.join(_here, "vtx_emit_skinned.py"))
_DEFAULT_VTX_TEMPLATE = None   # emitter uses its embedded CHAIN94 header
copt = _load("cache_opt",      os.path.join(_here, "cache_opt.py"))

def _i(d, o): return struct.unpack_from("<i", d, o)[0]

def convert_model(pc_basepath, out_dir, vtx_template=None, cache_optimize=True, root_lod=None):
    """pc_basepath: path without extension (expects .vvd/.dx90.vtx/.mdl).
       root_lod: detail to keep. None = Xbox default min(2,numLODs-1) (lowest
       detail, smallest files); 0 = full detail; 1 = medium.
       cache_optimize: apply Valve's ComputeVertexPermutation so the rootLOD verts
       are stored in strip first-use order (vertex-fetch locality; ~97% lower fetch
       stride). The VVD pool is reordered and VTX origMeshVertIDs remapped together,
       so the pair stays self-consistent.
       Emits <name>.vvd and <name>.xbox.vtx into out_dir; returns the MDL params
       (numvertices, numLODs, checksum) to drive mdl_template_convert."""
    name = os.path.basename(pc_basepath)
    pcv, pcvtx, pcmdl = pc_basepath+".vvd", pc_basepath+".dx90.vtx", pc_basepath+".mdl"
    os.makedirs(out_dir, exist_ok=True)
    checksum = _i(open(pcmdl, "rb").read(), 8)   # one consistent checksum for all 3

    g = ext.root_lod_geometry(pcvtx, root_lod=root_lod)
    hkeep = vvd.analyze(open(pcv, "rb").read())
    root = g["root"]
    keep = hkeep["lodv"][root]

    # vertex-fetch locality optimization (Valve ComputeVertexPermutation)
    vert_perm = None
    omv_of = [v["origMeshVertID"] for v in g["verts"]]
    if cache_optimize and g["indices"]:
        omv_stream = [omv_of[ix] for ix in g["indices"]]
        vert_perm, inv = copt.compute_permutation(keep, omv_stream)
        omv_of = [inv[o] for o in omv_of]        # remap VTX origMeshVertIDs to match

    vout, info = vvd.convert(pcv, os.path.join(out_dir, name+".vvd"),
                             force_checksum=checksum, collapse=True, vert_perm=vert_perm,
                             root_lod=root_lod)
    keep = info["keep"]

    # rebuild VTX vertex records with (possibly) remapped origMeshVertIDs
    vb = bytearray()
    for v, new_omv in zip(g["verts"], omv_of):
        rec = bytearray(v["raw"])
        struct.pack_into("<H", rec, 4, new_omv)  # origMeshVertID @4 (u16)
        vb += rec
    ib = struct.pack(f"<{len(g['indices'])}H", *g["indices"])
    geom = dict(numVerts=g["numVerts"], numIndices=g["numIndices"],
                numStrips=g["numStrips"], verts_bytes=bytes(vb), indices_bytes=ib,
                numBones=g["strip_numBones"], strip_flags=g["strip_flags"],
                bsc=g["bsc"], numLODs=1, checksum=checksum)
    tpl = vtx_template or _DEFAULT_VTX_TEMPLATE
    xvtx = emit.emit(geom, tpl, checksum=checksum)
    open(os.path.join(out_dir, name+".xbox.vtx"), "wb").write(xvtx)

    # self-consistency gate
    assert _i(vout,16) == keep, "VVD keep mismatch"
    assert (not omv_of) or max(omv_of) < keep, "origMeshVertID out of VVD range"
    assert (not g["indices"]) or max(g["indices"]) < g["numVerts"], "index out of stripgroup range"
    assert _i(vout,8) == _i(xvtx,16) == checksum, "checksum inconsistent"

    return dict(name=name, rootLOD=info["rootLOD"], src_numLODs=info["numLODs"],
                numvertices=keep, out_numLODs=1, checksum=checksum,
                vvd_bytes=len(vout), vtx_bytes=len(xvtx),
                strip_verts=g["numVerts"], indices=g["numIndices"],
                cache_optimized=bool(vert_perm))

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: lod_convert.py <pc_basepath_no_ext> <out_dir> [vtx_template]")
        sys.exit(1)
    tpl = sys.argv[3] if len(sys.argv) > 3 else None
    r = convert_model(sys.argv[1], sys.argv[2], tpl)
    print(f"{r['name']}: numLODs {r['src_numLODs']}->1  rootLOD={r['rootLOD']}  "
          f"keep={r['numvertices']} verts (strip {r['strip_verts']}v/{r['indices']}i)")
    print(f"  VVD {r['vvd_bytes']}B  VTX {r['vtx_bytes']}B  checksum={r['checksum']}")
    print(f"  -> feed mdl_template_convert: numvertices={r['numvertices']}, numLODs=1")
