#!/usr/bin/env python3
"""
convert_xbox.py - one-command PC -> Original Xbox (v47) model converter.

Usage:
    python convert_xbox.py <pc_model_basepath> <out_dir> [--full]

  <pc_model_basepath>  path WITHOUT extension, e.g. models/props/turret_01
                       (expects <base>.mdl, <base>.vvd, and a dx90 VTX named
                        either <base>.dx90.vtx or <base>_dx90.vtx)
  <out_dir>            where the Xbox triplet is written
  --lod N              keep LOD N (0=full, 1=medium) instead of the Xbox default
                       min(2,numLODs-1). Default reproduces Valve's geometry for
                       ~95% of multi-LOD models; use this for the ~4.5% Valve
                       shipped at higher detail (e.g. handrail04_long needs --lod 1).
  --full               emit ALL anims/seqs in the MDL. The anim emit (contiguous
                       descriptors + pooled tracks, animindex@24 and regiondist@20
                       both <<8-encoded) is verified valid for normal multi-seq
                       models (e.g. advisor 7/7, combine_scanner 20/12). Huge
                       animation-holder models (hundreds of anims, e.g.
                       alyx_gestures) still overflow a u16 pack -- not yet guarded.

Produces in <out_dir>:  <name>.mdl  <name>.vvd  <name>.xbox.vtx
All three share one checksum (engine requires this). Then pack <out_dir> into
your zip1 override with build_xzp.py.
"""
import os, sys, shutil, struct, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))

def _load(name):
    p = os.path.join(HERE, name + ".py")
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m

def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    base = sys.argv[1].rsplit(".mdl", 1)[0]      # tolerate a .mdl being passed
    out_dir = sys.argv[2]
    full = "--full" in sys.argv[3:]
    # --lod N : override the kept detail level. Default (omitted) = Xbox rule
    # min(2,numLODs-1), which reproduces Valve's choice for ~95% of multi-LOD
    # models. ~4.5% were shipped at a higher detail (Valve's per-model decision,
    # not recoverable from the PC files); pass --lod 0 or --lod 1 to match those.
    root_lod = None
    if "--lod" in sys.argv[3:]:
        root_lod = int(sys.argv[sys.argv.index("--lod") + 1])
    os.makedirs(out_dir, exist_ok=True)
    name = os.path.basename(base)

    pc_mdl, pc_vvd = base + ".mdl", base + ".vvd"
    for f in (pc_mdl, pc_vvd):
        if not os.path.exists(f):
            print("ERROR: missing", f); sys.exit(2)

    # lod_convert expects a dotted "<base>.dx90.vtx". Accept underscore naming too.
    dotted = base + ".dx90.vtx"
    if not os.path.exists(dotted):
        for alt in (base + "_dx90.vtx", base + ".dx80.vtx", base + "_dx80.vtx",
                    base + ".sw.vtx", base + "_sw.vtx"):
            if os.path.exists(alt):
                shutil.copy(alt, dotted)      # stage a dotted copy lod_convert can find
                print("note: using", os.path.basename(alt), "as the dx90 VTX")
                break
        else:
            print("ERROR: no VTX found next to", base); sys.exit(2)

    # 1) VVD + VTX
    lod = _load("lod_convert")
    r = lod.convert_model(base, out_dir, root_lod=root_lod)
    print("VVD+VTX:", {k: r[k] for k in ("numvertices", "out_numLODs", "checksum",
                                         "indices") if k in r})

    # 2) MDL. If the VVD/VTX kept all LODs (multi-LOD skinned/ragdoll, Valve structure),
    # the MDL must keep every per-LOD vertex count too -> root_lod=0 (no flatten).
    mdl = _load("mdl_v44_to_v47")
    mdl_rl = 0 if r.get("all_lods") else r.get("rootLOD")
    mdl.convert(pc_mdl, os.path.join(out_dir, name + ".mdl"), reduce=not full,
                root_lod=mdl_rl)

    # 3) validate + checksum consistency
    rd = _load("v47_reader")
    chk = rd.V47Reader(os.path.join(out_dir, name + ".mdl"))
    def cks(p, off):
        return struct.unpack_from("<i", open(p, "rb").read(), off)[0]
    cm = cks(os.path.join(out_dir, name + ".mdl"), 8)
    cv = cks(os.path.join(out_dir, name + ".vvd"), 8)
    cx = cks(os.path.join(out_dir, name + ".xbox.vtx"), 16)
    print("MDL check:", len(chk.errors), "errors,", len(chk.warnings), "warnings")
    print("checksums match:", cm == cv == cx, "(", cm, ")")

    # ---- collision: .phy -> .phx (only if a .phy sits next to the model) ----
    pc_phy = base + ".phy"
    phx_made = False
    if os.path.exists(pc_phy):
        phy2phx = _load("phy2phx")
        out_phx = os.path.join(out_dir, name + ".phx")
        simp = "--simplify-collision" in sys.argv[3:]
        try:
            pinfo = phy2phx.convert(pc_phy, out_phx, simplify=simp)
            phx_made = True
            cp = cks(out_phx, 12)            # phx checksum lives at +12, must equal model
            print("PHX:", pinfo["solidCount"], "solid(s),",
                  pinfo["numConstraints"], "constraint(s); checksum matches MDL:",
                  cp == cm)
            if pinfo.get("simplified"):
                print("     simplified", pinfo["simplified"], "solid(s) via vphysics-style hull reduction")
            for w in pinfo.get("warnings", []):
                print("     warning:", w)
            if pinfo["solidCount"] > 1 or pinfo["numConstraints"]:
                print("     (multi-solid/ragdoll: collision geometry is copied verbatim,")
                print("      which is functional but not byte-identical to Valve's recompiled hulls)")
        except Exception as e:
            print("PHX: skipped (phy2phx error:", e, ")")

    print("\nDone ->", out_dir)
    trip = name + ".mdl, " + name + ".vvd, " + name + ".xbox.vtx"
    print("   ", trip + (", " + name + ".phx" if phx_made else ""))
    print("Pack the output dir into zip1 with build_xzp.py, keeping the")
    print("models/<path>/ folder structure intact.")
    if full:
        print("\n[--full] NOTE: multi-anim emit is verified for normal multi-seq")
        print("models; animation-holder models with hundreds of anims may overflow")
        print("a u16 pack (not yet guarded). Test on hardware before relying on it.")

if __name__ == "__main__":
    main()
