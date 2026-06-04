#!/usr/bin/env python3
"""
convert_xbox.py - one-command PC -> Original Xbox (v47) model converter.

Usage:
    python convert_xbox.py <pc_model_basepath> <out_dir> [--full]

  <pc_model_basepath>  path WITHOUT extension, e.g. models/props/turret_01
                       (expects <base>.mdl, <base>.vvd, and a dx90 VTX named
                        either <base>.dx90.vtx or <base>_dx90.vtx)
  <out_dir>            where the Xbox triplet is written
  --full               emit ALL anims/seqs in the MDL (EXPERIMENTAL: animation
                       track pointers are not yet cracked, so anims won't play
                       and the model may not load. Default is the proven
                       single-idle build that renders correctly.)

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
    r = lod.convert_model(base, out_dir)
    print("VVD+VTX:", {k: r[k] for k in ("numvertices", "out_numLODs", "checksum",
                                         "indices") if k in r})

    # 2) MDL
    mdl = _load("mdl_v44_to_v47")
    mdl.convert(pc_mdl, os.path.join(out_dir, name + ".mdl"), reduce=not full)

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
    print("\nDone ->", out_dir)
    print("  ", name + ".mdl,", name + ".vvd,", name + ".xbox.vtx")
    print("Pack the output dir into zip1 with build_xzp.py, keeping the")
    print("models/<path>/ folder structure intact.")
    if full:
        print("\n[--full] WARNING: multi-anim track pointers are not yet solved;")
        print("this build is experimental and may not load on hardware.")

if __name__ == "__main__":
    main()
