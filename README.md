# Half Life 2 XBox PC -> XBox model conversion

Please note this is NOT for "The Orange Box" it is for the 2005 release of Half-Life 2 for the Original XBox.

This is an AI-Generated tool. I do not take any credit for the output presented here.
Made using Opus 4.8 on Medium-High effort mode.

This README expects you to know the fundamentals of HL2 XBox modding.

Converts a PC Half-Life 2 model (ideally, studiohdr v44) to the Original XBox format
(studiohdr v47) so it loads nicely on real hardware (or xemu) via a XZP
override. It transforms the shipped binary directly rather than decompiling and
recompiling, so nothing is regenerated or approximated.

## Why does this exist?

The Original XBox build of HL2 used an internal Valve toolchain that never shipped. 
Some versions of studiomdl that were based on the 2006 SDK still carry a `-xbox` flag, 
but they do **not** produce correct v47 models (only the .xbox.vtx, which is still incorrect). 
Until a native XBox studiomdl is restored (or obtained via other means), going straight from 
the compiled PC binary to v47 is likely the best path for getting custom models onto the console. For a
faithful 1:1 port of a shipped asset this is also *more* accurate than a
decompile -> recompile round-trip, which loses vertex order, flex/delta data, and
some QC options.

`scripts/` (keep these together):

| File | Role |
|------|------|
| `convert_xbox.py` | one-command driver (run this) |
| `mdl_v44_to_v47.py` | MDL converter (v44 -> v47); meshid + fidelity guards |
| `lod_convert.py` | VVD + VTX converter (drives the four below) |
| `vvd_multilod.py`, `vtx_lod_extract.py`, `vtx_emit_skinned.py`, `cache_opt.py` | VVD/VTX internals |
| `vtx_emit_multimesh.py` | multi-mesh VTX emit |
| `phy2phx.py` | collision: `.phy` -> `.phx` (auto-run by the driver; `--simplify-collision` opt-in) |
| `ivp_collide.py` | IVP compact-surface parse/write + vphysics-style hull simplification |
| `v47_reader.py` | validator (`--check`, `--phx <file>` checksum cross-check, `--json`) |

`tools/`:

| File | Role |
|------|------|
| `gt_diff_harness.py` | ground-truth byte-diff harness / regression guard (needs the PC+Xbox suite; you can source the PC suite from the Half-Life 2 2004 Collectors' Edition.) |

## Automatic conversion of model

Ideally, use `--lod 2` to match the other XBox models, unless your model is already low poly enough.

```
python convert_xbox.py <pc_model_path> <out_dir> [--full] [--lod N]
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
- `<name>.phx`*        <- only if a `.phy` was found

The MDL/VVD/VTX share one checksum, the
`.phx` checksum is matched to it, and the MDL is validated automatically.

For any dynamic prop that needs its animations, use the `--full` parameter.

## Then package

Drop the output files into your zip1 staging tree, mirroring the path your prop uses in Hammer
(`models/props/turret_01.mdl`) for example, add the material under `materials/models/...` (you can see where models pull their materials from using [VPKEdit](https://github.com/craftablescience/VPKEdit)!, 
and then convert using [MakeXZIP](https://github.com/FelipeDeveloper07/XZP-Tool-Fix-V6-HL2x/releases/tag/HL2x), 
however do note you may need to modify the batch file for your own usage.

Using [xzptool](https://github.com/craftablescience/xzptool), convert your xzp to xz_ and drop it into `<game_installation>\GameMedia` and if using a fully custom zip (not included in the base game, for example zip1_xbox.xz_), mount it in \LoaderMedia\install.txt with an extra line.
You may also need to drop the **xzp** (NOT xz_) into: `<cache letter>\HL2\HL2x\` if it does not unpack correctly (i.e, hangs on the loading screen) which is the case for xemu a lot of times.

## Test the model

For this converter, most models work***, for prop_dynamic, prop_static and prop_physics you need to mount the model (see below), which should be downgraded to v44 studiohdr. 
You can spawn it with console commands or have a custom map with it already loaded.

## Doing it manually (what the driver runs)

```
python lod_convert.py     <path/to/model>      <out_dir> # -> .vvd + .xbox.vtx
python mdl_v44_to_v47.py  <path/to/model>      <out_dir>
python phy2phx.py         <path/to/model>      <out_dir> # if a .phy exists
python v47_reader.py      <out_dir> --check
```

`mdl_v44_to_v47.convert(pc, out, reduce=True, mat_override=None)`:
- `reduce=True` (driver default) emits one idle anim + one seq. Use if it doesn't work otherwise.
  `--full` emits all anims/seqs. Very experimental (see Limitations).
- `mat_override=("texname","cdpath")` repoints the model at a different material.

## Limitations

- **Material must be in Xbox form.** A material left in your XZip staging area as a PC `.vtf`
  won't render (instead will show the iconic purple and black checkers) on the custom model;
  it *has* to be converted to the Xbox texture format via [MareTF](https://github.com/craftablescience/MareTF)
- **Collision geometry: simplification now exists (`--simplify-collision`, opt-in).**
  Verbatim copy is still the default and is functionally correct but larger than Valve's.
  The simplifier (above) closes most of that gap for single-convex solids; multi-convex
  ledge-tree solids still copy verbatim. Byte-identical to Valve isn't the target (Qhull
  vertex ordering differs); Valve-like sizes + valid IVP is.
- **Non-zero ragdoll joint limits are flattened to zero-limit** (emitted with a
  warning). Affects animated-NPC ragdolls — joints are looser than Valve's until the
  non-zero limit encoding is cracked. The model still converts and collides.
- **Bone-follower edge case (open).** A custom prop with exactly two bones, *both*
  bone followers, parent->child with a single constraint (see `GUNSHIP_TAIL_TODO.md`)
  only instantiates solid 0 on Xbox; the second follower isn't created...
  Every structural field matches working props and there's no Valve Xbox build of
  it to diff against, so it's unsolved. For now, merge the collision into a single solid.
- **`--full` multi-anim is experimental.** Animation-holder models with hundreds of
  sequences can overflow a u16 pack; not yet guarded. A separate autoplay DELTA-aim
  angle bug is known. Single-sequence (`reduce`) builds are the reliable path.
- **Attachments / flexes / pose params** are dropped (not needed to render).

## The lesson

Real Xbox hardware is the oracle; xemu is a secondary validator. Every fix here was
confirmed by byte-diffing against Valve's shipped Xbox files. That comparison, not
reasoning in the abstract, is what cracked each format!
