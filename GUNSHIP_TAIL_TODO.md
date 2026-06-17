# Open issue: crashedgunship tail collision (resume notes)

## Symptom
crashedgunship (custom dynamic prop, 2 solids: Gunship.Body + Gunship.Tail_cnl,
1 ragdoll constraint). On **PC** the tail collides as a bare `prop_dynamic`. After
conversion, on **Xbox only solid 0 collides** — the prop falls back to a single static
physics object instead of creating bone followers for both solids.

Confirmed via swap test: whatever geometry is placed in **solid slot 0** collides at its
named bone; slot 1 is never instantiated. So exactly one physics object is being created,
from solid 0, via the static fallback path (not bone followers).

## Ruled OUT (all verified against Valve ground truth)
- **phx format** — byte-format-identical to GT `scrapyarddumpster.phx` (which works):
  names block, solids block, constraint block all encoded the same.
- **phx geometry** — TAILTEST (body geometry copied into the tail slot) still didn't
  collide → not the tail's collision data.
- **vertex-cache / solid index byte** (`dummy[0]` at collide-data +64) — set correctly
  to 0/1 (matches GT strider); changing it does nothing for the tail.
- **MDL** — bones, flags, `bone_followers` kv (byte-identical to PC, correct pointer),
  `bonetablebyname` table, checksum all correct and match working props.
- **case** — Valve lowercases phx solid names too; not the issue. (Keep original case.)
- **tail bone usage** — 652 verts are weighted to Gunship.Tail_cnl; it's a real used bone.
- **stale build** — fresh reconvert is byte-identical to the in-use file.
- **checksum** — phx checksum == MDL checksum (consistent triplet).

## Why it's stuck
crashedgunship is a **custom model with no Valve Xbox version** anywhere in the model
dumps, so there's no ground-truth `.phx`/`.mdl` to diff against — which is the oracle that
cracked every other bug. Its exact profile (2 bones, BOTH followers, parent→child, 1
constraint) also has no GT equivalent. The closest working analog is scrapyarddumpster
(6 bones, root + 5 child followers, 5 constraints) — same pattern at larger scale, which
says the pattern *should* work but not why this instance doesn't.

## Leads to try when resuming
1. Find/author ANY Xbox prop with the exact 2-bone-both-follower + single-constraint
   profile that works, convert it, and diff — the missing ground truth.
2. Get the Xbox game DLL's bone-follower creation path (CBoneFollowerManager /
   CreateBoneFollowers) to see what gates follower count.
3. Test whether the **constraint** is the trigger: candidate "no constraint" failed, but
   re-verify with a clean build that also has no constraint reference anywhere.

## Practical workaround (recommended for now)
It's a static crashed wreck — the tail doesn't need independent physics. Rebuild the
collision as a **single solid** covering body+tail in the modeling source, then reconvert.
The static fallback already collides solid 0 perfectly, so a one-solid collision model
makes the entire gunship collide with no bone followers involved.
