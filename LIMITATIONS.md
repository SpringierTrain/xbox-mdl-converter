## Limitations

- **Material must be in Xbox form.** A material left in your XZip staging area as a PC `.vtf`
  won't render (instead will show the iconic purple and black checkers) on the custom model;
  it *has* to be converted to the Xbox texture format via [MareTF](https://github.com/craftablescience/MareTF);
  see guide for that [here](https://docs.google.com/document/d/1Zw3uZYdpCWaGxMtJ3-IRgayM9HIWiHyTJN0N16T3j30/edit?usp=sharing).
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
