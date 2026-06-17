# PC -> Original Xbox model conversion

This is an AI-Generated tool. I do not take any credit for the output presented here.
Made using Opus 4.8

Converts a PC Half-Life 2 model (studiohdr **v44**) to the Original Xbox format
(studiohdr **v47**) so it loads and collides on a real Xbox / xemu via a zip1
override. It transforms the shipped binary directly rather than decompiling and
recompiling, so nothing is regenerated or approximated.

## Why this exists

The Original Xbox build of HL2 used an internal Valve toolchain that never shipped
in working form. The public Source SDK studiomdl still carries a `-xbox` flag, but
it does **not** emit correct v47 models, and the community "Source SDK 2005" fork
(which restored the Xbox **map** tools) currently **crashes** on model compile. So
until a native Xbox studiomdl is restored, going straight from the compiled PC
binary to v47 is the working path for getting models onto the console. For a
faithful 1:1 port of a shipped asset this is also *more* accurate than a
decompile -> recompile round-trip, which loses vertex order, flex/delta data, and
some QC options.

## Files (keep all in one folder)

| File | Role |
|------|------|
| `convert_xbox.py` | one-command driver (run this) |
| `mdl_v44_to_v47.py` | MDL converter (v44 -> v47) |
| `lod_convert.py` | VVD + VTX converter (drives the four below) |
| `vvd_multilod.py`, `vtx_lod_extract.py`, `vtx_emit_skinned.py`, `cache_opt.py` | VVD/VTX internals |
| `vtx_emit_multimesh.py` | multi-mesh VTX emit |
| `v47_reader.py` | validator (`--check`) |
| `phy2phx.py` | collision: `.phy` -> `.phx` (run automatically by the driver) |

## One command

```
python convert_xbox.py <pc_model_basepath> <out_dir> [--full] [--lod N]
```

`<pc_model_basepath>` is the path with **no extension**, e.g.
`models/props/turret_01`. Sitting next to it it needs:

- `<base>.mdl`
- `<base>.vvd`
- a dx90 VTX named `<base>.dx90.vtx` **or** `<base>_dx90.vtx`
  (dx80 / sw accepted as fallbacks)
- `<base>.phy` (optional) — if present, a `.phx` is produced automatically

It writes to `<out_dir>`:

- `<name>.mdl`
- `<name>.vvd`
- `<name>.xbox.vtx`   <- note the dotted `.xbox.vtx` extension the Xbox uses
- `<name>.phx`        <- only if a `.phy` was found

The MDL/VVD/VTX share one checksum (the engine refuses the model otherwise), the
`.phx` checksum is matched to it, and the MDL is validated automatically.

## What's solved

- **The line-of-sight / first-draw GPU hang** — root-caused to the per-mesh
  `meshid` (stored at Xbox mesh `+28`, vs PC `+32`). The converter wrote 0 for
  every mesh, so any 2+ mesh model collided draw state and stalled the GPU
  pushbuffer. Now carried/sequenced correctly. Confirmed on real hardware.
- **Multi-mesh / multi-LOD models** — contiguous VTX layout + LOD collapse fixes,
  passing a 2134-model regression suite.
- **The v44 -> v47 bone struct** — i16 parent, bone flags @140, surfaceprop @152,
  contents @156, plus the compacted field layout. Applies to every multi-bone model.
- **The `.phx` collision format** — the Xbox replaces the PHY's text keyvalues with
  a binary block (lead = block count; `0x02` names / `0x04` solids / `0x05`
  constraints; truncated float16 mass/volume; surfaceprop table rebuilt from the full
  2033-pair suite). The *keyvalue block* is byte-exact on ~75% of pairs; the residual
  is a build-time names-block choice on single-solid props that isn't in any input file
  and has no functional effect (a single solid binds to the root regardless). The *full*
  `.phx` file is never byte-exact because the solid geometry is verbatim-copied while
  Valve recompiles it (see Limitations). Bone-follower collision is confirmed working on
  hardware.
- **phy2phx never crashes.** Across all 1874 `.phy` files in the suite it converts 100%
  (was crashing on ~8% — every NPC ragdoll, because the surfaceprop table was missing
  `flesh`). Unknown surfaceprops fall back to `default` and non-zero ragdoll joint limits
  are flattened to zero-limit, each emitted with a warning rather than an exception.
- **Collision geometry simplification (opt-in, `--simplify-collision`).** Ports Valve's
  vphysics `SimplifyCollide` in pure Python: parse the IVP compact-surface, reduce each
  convex hull via plane-clipping to a tolerance, and re-emit valid IVP — using scipy's
  Qhull, the same hull library IVP used. The writer is byte-identical to Valve except a
  deliberately-conservative bounding box. Cuts the mean solid-size error vs Valve from
  ~488 B (verbatim) to ~162 B, with big wins on character ragdolls (Kleiner/Combine_Soldier
  collision ~67% smaller, matching Valve's scale). Per-solid verbatim fallback when it
  wouldn't shrink (matches Valve). See `COLLISION_SIMPLIFY_PLAN.md`.
  NOT yet on by default: re-parses cleanly and is conservatively bounded, but the IVP
  `pierce_index` (raycast acceleration) is heuristic and this hasn't been hardware-verified
  for collision behaviour — enable, test on hardware, then trust. Multi-convex single solids
  (ledge trees, e.g. some props) currently fall back to verbatim until tree-emit lands.

## Spawn it

`prop_dynamic`, model `models/<path>/<name>.mdl`. Use `prop_physics` only if you
also built a `.phx` and injected the prop_data keyvalues.

## Then package

Drop the output files into your zip1 staging tree, mirroring the on-disc path
(`models/props/turret_01.*`), add the material under `materials/...`, and pack:

```
start /wait python build_xzp.py --root ..\zip1_xbox --scan
```

then convert/rename the result to `zip1.xz_` as usual.

## Doing it manually (what the driver runs)

```
python lod_convert.py     models/props/turret_01      out_dir   # -> .vvd + .xbox.vtx
python mdl_v44_to_v47.py  models/props/turret_01.mdl  out_dir/turret_01.mdl
python phy2phx.py         models/props/turret_01.phy  out_dir/turret_01.phx   # if a .phy exists
python v47_reader.py      out_dir/turret_01.mdl --check
```

`mdl_v44_to_v47.convert(pc, out, reduce=True, mat_override=None)`:
- `reduce=True` (driver default) emits one idle anim + one seq — the proven build.
  `--full` emits all anims/seqs and is experimental (see Limitations).
- `mat_override=("texname","cdpath")` repoints the model at a different material.

## Limitations / gotchas

- **Material must already be in Xbox form.** A custom material left as a PC `.vtf`
  won't render; it has to be on-disc or converted to the Xbox texture format.
- **Collision geometry: simplification now exists (`--simplify-collision`, opt-in).**
  Verbatim copy is still the default and is functionally correct but larger than Valve's.
  The simplifier (above) closes most of that gap for single-convex solids; multi-convex
  ledge-tree solids still copy verbatim. Byte-identical to Valve isn't the target (Qhull
  vertex ordering differs); Valve-like sizes + valid IVP is. Needs hardware validation
  before becoming default.
- **Non-zero ragdoll joint limits are flattened to zero-limit** (emitted with a
  warning). Affects animated-NPC ragdolls — joints are looser than Valve's until the
  non-zero limit encoding is cracked. The model still converts and collides.
- **Bone-follower edge case (open).** A custom prop with exactly two bones, *both*
  bone followers, parent->child with a single constraint (the "crashedgunship tail"
  case) only instantiates solid 0 on Xbox; the second follower isn't created.
  Every structural field matches working props and there's no Valve Xbox build of
  it to diff against, so it's unsolved. Workaround: author the collision as a single
  merged solid. See `GUNSHIP_TAIL_TODO.md`.
- **`--full` multi-anim is experimental.** Animation-holder models with hundreds of
  sequences can overflow a u16 pack; not yet guarded. A separate autoplay DELTA-aim
  angle bug is known. Single-sequence (`reduce`) builds are the reliable path.
- **Attachments / flexes / pose params** are dropped (not needed to render).

## Ground truth

Real Xbox hardware is the oracle; xemu is a secondary validator. Every fix here was
confirmed by byte-diffing against Valve's shipped Xbox files — that comparison, not
reasoning in the abstract, is what cracked each format.
