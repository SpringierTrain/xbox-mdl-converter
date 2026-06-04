# PC -> Original Xbox model conversion

This is an AI-Generated tool. I do not take any credit for the output presented here.
Made using Opus 4.8

Converts a PC Half-Life 2 model (studiohdr **v44**) to the Original Xbox
format (studiohdr **v47**) so it loads on a real Xbox / xemu via a zip1 override.

## Files (keep all in one folder)

| File | Role |
|------|------|
| `convert_xbox.py` | one-command driver (run this) |
| `mdl_v44_to_v47.py` | MDL converter (v44 -> v47) |
| `lod_convert.py` | VVD + VTX converter (drives the four below) |
| `vvd_multilod.py`, `vtx_lod_extract.py`, `vtx_emit_skinned.py`, `cache_opt.py` | VVD/VTX internals |
| `v47_reader.py` | validator (`--check`) |
| `phy2phx.py` | optional: `.phy` -> `.phx` for prop_physics |

## One command

```
python convert_xbox.py <pc_model_basepath> <out_dir>
```

`<pc_model_basepath>` is the path with **no extension**, e.g.
`models/props/turret_01`. It needs, sitting next to it:

- `<base>.mdl`
- `<base>.vvd`
- a dx90 VTX named `<base>.dx90.vtx` **or** `<base>_dx90.vtx`
  (dx80 / sw are accepted as fallbacks)

It writes three files to `<out_dir>`:

- `<name>.mdl`
- `<name>.vvd`
- `<name>.xbox.vtx`   <- note the dotted `.xbox.vtx` extension the Xbox uses

All three share one checksum (the engine refuses the model otherwise) and the
MDL is validated automatically.

## Then package

Drop the three files into your zip1 staging tree, mirroring the on-disc path
(`models/props/turret_01.*`), add the material under `materials/...`, and pack:

```
start /wait python build_xzp.py --root ..\zip1_xbox --scan
```

then convert/rename the result to `zip1.xz_` as usual.

## Doing it manually (what the driver runs)

```
python lod_convert.py        models/props/turret_01  out_dir   # -> .vvd + .xbox.vtx
python mdl_v44_to_v47.py      models/props/turret_01.mdl  out_dir/turret_01.mdl
python v47_reader.py          out_dir/turret_01.mdl --check
```

`mdl_v44_to_v47.convert(pc, out, reduce=True, mat_override=None)`:
- `reduce=True` (default via the driver) = emit one idle anim + one seq. This is
  the **proven** build that renders. Multi-anim (`--full`) is experimental and
  not yet reliable (see Limitations).
- `mat_override=("texname","cdpath")` repoints the model at a different material
  (used for the stock-material A/B test).

## Spawn it

`prop_dynamic`, model `models/<path>/<name>.mdl`. Use `prop_physics` only if you
also built a `.phx` (via `phy2phx.py`) and injected prop_data.

## Limitations / gotchas

- **Material must already be in Xbox form.** A custom material that's a PC `.vtf`
  won't render. metalPot worked because its material was stock and on the disc.
- **Animations don't play yet.** The model renders in its reference pose; the
  v47 animation-descriptor track pointer isn't cracked, so multi-anim builds are
  experimental. Skeleton, skinning, and geometry are fully working.
- **Bone count:** the v44->v47 bone struct fix (i16 parent, bone flags @140,
  surfaceprop@152/contents@156) applies to every multi-bone model.
- **Attachments / flexes / pose params** are dropped (not needed to render).
