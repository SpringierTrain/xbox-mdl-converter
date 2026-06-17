#!/usr/bin/env python3
"""Ground-truth diff harness / regression guard.

Converts every PC model that has a Valve Xbox counterpart and byte-diffs the output
(MDL / VVD / VTX / PHX) against Valve's shipped file, bucketing each into:

  exact  - byte-identical (the goal)
  bytes  - same length, some bytes differ  (field-level diff -> usually a real bug)
  len    - different length                (structural: LOD/anim choice, or verbatim
                                            collision geometry vs Valve's recompiled)

The 'bytes' bucket on simple props is where genuine converter bugs hide; the 'len'
bucket is dominated by reduce-mode (anim stripping) and per-model LOD selection.

Usage:
    python tools/gt_diff_harness.py <pc_root> <xbox_root> [--sample N] [--phx-only]

<pc_root>/<xbox_root> mirror each other (pc/models/... and xbox/models/...). Needs the
converter scripts on the path (run from the repo root).
"""
import os, sys, struct, subprocess, tempfile, shutil, glob
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, "..", "scripts", "convert_xbox.py")


def pairs(pc_root, xbox_root):
    gt = {os.path.relpath(p, xbox_root).lower(): p
          for p in glob.glob(os.path.join(xbox_root, "**", "*.mdl"), recursive=True)}
    for p in glob.glob(os.path.join(pc_root, "**", "*.mdl"), recursive=True):
        rel = os.path.relpath(p, pc_root).lower()
        if rel not in gt:
            continue
        base = p[:-4]
        vtx = next((base + c for c in (".dx90.vtx", "_dx90.vtx", ".dx80.vtx", ".sw.vtx")
                    if os.path.exists(base + c)), None)
        if os.path.exists(base + ".vvd") and vtx:
            yield base, gt[rel][:-4]


def diff(mine, gt):
    if not os.path.exists(mine):
        return "missing"
    if not os.path.exists(gt):
        return "no_gt"
    a, b = open(mine, "rb").read(), open(gt, "rb").read()
    if a == b:
        return "exact"
    return "len" if len(a) != len(b) else "bytes"


def main(argv):
    if len(argv) < 3:
        print(__doc__); return 1
    pc_root, xbox_root = argv[1], argv[2]
    sample = int(argv[argv.index("--sample") + 1]) if "--sample" in argv else 1
    phx_only = "--phx-only" in argv

    allpairs = list(pairs(pc_root, xbox_root))[::sample]
    print(f"testing {len(allpairs)} pairs")
    buckets = {k: Counter() for k in ("mdl", "vvd", "vtx", "phx")}
    suspects = []
    for pb, gb in allpairs:
        name = os.path.basename(pb)
        od = tempfile.mkdtemp()
        try:
            subprocess.run([sys.executable, DRIVER, pb, od],
                           capture_output=True, timeout=120)
            o = os.path.join(od, name)
            checks = {"phx": (o + ".phx", gb + ".phx")} if phx_only else {
                "mdl": (o + ".mdl", gb + ".mdl"),
                "vvd": (o + ".vvd", gb + ".vvd"),
                "vtx": (o + ".xbox.vtx", gb + ".xbox.vtx"),
                "phx": (o + ".phx", gb + ".phx")}
            for k, (m, g) in checks.items():
                if k == "phx" and not os.path.exists(pb + ".phy"):
                    continue
                s = diff(m, g)
                buckets[k][s] += 1
                if s == "bytes" and k in ("mdl", "vtx"):
                    suspects.append((name, k))
        finally:
            shutil.rmtree(od, True)

    for k, c in buckets.items():
        if sum(c.values()):
            print(f"  {k:4s}: {dict(c)}")
    if suspects:
        print(f"\nsame-length byte diffs to investigate (potential bugs): {len(suspects)}")
        for n, k in suspects[:20]:
            print(f"   {n} [{k}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
