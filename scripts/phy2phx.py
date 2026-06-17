#!/usr/bin/env python3
"""phy2phx.py - PC .phy -> Original Xbox .phx, without vphysics.dll.

Cracked from Valve's makephx + the regression suite:
 - .phx header = .phy header verbatim (checksum already = model checksum).
 - solid collide blocks copied VERBATIM from the .phy. (Valve's tool re-runs the
   solid through vphysics SimplifyCollide+CollideWrite, but for already-simple
   props that is a no-op on topology; the only byte differences vs the PC solid
   are last-bit float noise from independent compilation, functionally identical.
   The VPHY/IVPS compiled format is identical on PC and Xbox.)
 - text keyvalues -> packed binary (the only real transform; loader requires it):
     u16 keyCount
     per key: 0x04 0x01 <f16 volume/2^24> <f16 mass> 0x00 0xff <sprop_idx> ff*5
   (Names/surfaceprop-text/editparams are dropped, as Valve's tool does for props.)
"""
import struct, re, sys

VOL_SCALE = 1 << 24
# surfaceprop name -> index in the Xbox surfaceprops table.
# Decoded by aligning 1268 PC .phy / GT .phx pairs (the sprop byte at solid+6 in the
# 0x04 block vs the PC "surfaceprop" text). 'conrete' is Valve's own typo'd prop.
SPROP = {
    "default": 0x00, "solidmetal": 0x01, "metal": 0x03, "metalgrate": 0x06,
    "metalvent": 0x07, "metalpanel": 0x08, "dirt": 0x09, "tile": 0x0d, "wood": 0x0e,
    "wood_crate": 0x11, "wood_plank": 0x12, "wood_solid": 0x13, "wood_furniture": 0x14,
    "wood_panel": 0x15, "glass": 0x1b, "computer": 0x1c, "concrete": 0x1d,
    "porcelain": 0x1f, "boulder": 0x20, "brick": 0x22, "chainlink": 0x24,
    "watermelon": 0x2a, "plaster": 0x2e, "cardboard": 0x2f, "plastic_barrel": 0x30,
    "plastic_box": 0x31, "plastic": 0x32, "item": 0x33, "rubber": 0x36, "rubbertire": 0x37,
    "glassbottle": 0x3d, "pottery": 0x3e, "canister": 0x40, "metal_barrel": 0x41,
    "floating_metal_barrel": 0x42, "plastic_barrel_buoyant": 0x43, "popcan": 0x45,
    "paintcan": 0x46, "paper": 0x47, "weapon": 0x4a, "metalvehicle": 0x51,
    "combine_metal": 0x58, "combine_glass": 0x59, "conrete": 0x7f,
    # recovered from GT by aligning the full 2033-pair suite (the originals above
    # missed these — 'flesh' alone made every NPC/character ragdoll crash):
    "flesh": 0x26, "rock": 0x1e, "carpet": 0x2d, "grenade": 0x3f, "strider": 0x56,
}

def _f16(x):
    """float32 -> float16 with mantissa TRUNCATION (round toward zero), not round-to-
    nearest. Valve's tool truncates; struct.pack('<e') rounds, which is off by 1 ULP on
    ~half of all mass/volume values. Verified against the regression suite."""
    b = struct.unpack("<I", struct.pack("<f", float(x)))[0]
    s = (b >> 16) & 0x8000
    e = ((b >> 23) & 0xff) - 112        # rebias 127 -> 15
    m = b & 0x7fffff
    if x == 0:           return struct.pack("<H", s)
    if e <= 0:                           # subnormal / underflow
        if e < -10:      return struct.pack("<H", s)
        m = (m | 0x800000) >> (1 - e)
        return struct.pack("<H", s | (m >> 13))
    if e >= 31:          return struct.pack("<H", s | 0x7c00)
    return struct.pack("<H", s | (e << 10) | (m >> 13))

def pack_kv(solids, constraints):
    """Emit the Xbox binary-keyvalues collision block. Grammar cracked by aligning the
    full PC .phy / GT .phx suite. The *keyvalue block* is byte-exact on ~75% of pairs;
    the full .phx file is never byte-exact because the solid geometry ahead of this block
    is copied verbatim while Valve recompiles it through vphysics (see README).

      u16 lead   = NUMBER OF BLOCKS that follow (not a solid/constraint count)
      [0x02] numSolids u8, nameLen u16, <lowercased name\\0 ...>      names block (see rule)
      [0x04] numSolids u8,  per solid: vol_f16, mass_f16, idx u8, link u8, sprop u8, ff*5
                 link = 0xe0|idx when a names block is present, else 0xff
      [0x05] numConstraints u8, per constraint: parent u8, child u8, [00 00 ff]x3 (zero lim)

    names-keep rule: Valve keeps the names block for multi-solid objects and ragdolls
    (constraints), drops it for plain single-solid props. The residual ~25% is a build-time
    choice on single-solid props not recoverable from any input file, with no functional
    effect (a single solid binds to the root regardless of whether its name is present).

    Approximations (emitted with a warning, never a crash): unknown surfaceprops fall back
    to 'default'; non-zero ragdoll joint limits are flattened to zero-limit; animated-NPC
    ragdolls with the extra 0x00 float32 params block aren't fully encoded yet."""
    keep_names = (len(solids) > 1 or bool(constraints)) and any(s.get("name") for s in solids)
    warnings = []
    blocks = []
    if keep_names:
        names = b"".join((s.get("name") or "").lower().encode("latin-1") + b"\x00" for s in solids)
        blocks.append(bytes([0x02, len(solids)]) + struct.pack("<H", len(names)) + names)
    sb = bytearray([0x04, len(solids)])
    for s in solids:
        idx = s["index"]
        sp = SPROP.get((s["sprop"] or "default").lower())
        if sp is None:
            # Unknown surfaceprop (custom prop, or one not in any GT manifest).
            # Fall back to 'default' rather than crashing — the prop still collides;
            # only its impact sound/material response is approximate.
            warnings.append(f"surfaceprop {s['sprop']!r} unknown -> default (0x00)")
            sp = 0x00
        link = (0xe0 | (idx & 0x1f)) if keep_names else 0xff
        sb += (_f16(s["volume"] / VOL_SCALE) + _f16(s["mass"])
               + bytes([idx & 0xff, link, sp]) + b"\xff"*5)
    blocks.append(bytes(sb))
    if constraints:
        cb = bytearray([0x05, len(constraints)])
        for c in constraints:
            if not all(abs(c["lim"][k]) < 1e-6 for k in range(6)):
                # Non-zero joint limits aren't encoded yet; emit zero-limit (free) joints
                # so the model still converts and collides. Ragdoll joint range may be
                # looser than Valve's until this is properly encoded.
                warnings.append("non-zero ragdoll joint limits emitted as zero-limit")
            cb += bytes([c["parent"] & 0xff, c["child"] & 0xff]) + b"\x00\x00\xff"*3
        blocks.append(bytes(cb))
    return struct.pack("<H", len(blocks)) + b"".join(blocks), warnings   # lead = block count

def convert(phy_path, phx_path, simplify=False):
    d = open(phy_path, "rb").read()
    hdrsize, vid, solidCount, checksum = struct.unpack_from("<iiii", d, 0)
    o = 16; solids = []
    for s in range(solidCount):
        cs = struct.unpack_from("<i", d, o)[0]
        solids.append(d[o:o+4+cs]); o += 4 + cs
    text = d[o:].decode("latin-1", "replace")
    blocks = re.findall(r'solid\s*\{(.*?)\}', text, re.S)
    solids_kv = []
    for b in blocks:
        g = lambda k: (re.search(rf'"{k}"\s+"([^"]+)"', b) or [None, None])[1]
        solids_kv.append(dict(index=int(g("index") or len(solids_kv)),
                              name=g("name"), mass=float(g("mass") or 1.0),
                              volume=float(g("volume") or 0.0), sprop=g("surfaceprop")))
    solids_kv.sort(key=lambda s: s["index"])
    constraints = []
    for cb in re.findall(r'ragdollconstraint\s*\{(.*?)\}', text, re.S):
        gc = lambda k: (re.search(rf'"{k}"\s+"([^"]+)"', cb) or [None, "0"])[1]
        constraints.append(dict(parent=int(gc("parent")), child=int(gc("child")),
                                lim=[float(gc(a)) for a in
                                     ("xmin","xmax","ymin","ymax","zmin","zmax")]))
    out = bytearray(d[:16])                 # header verbatim (checksum = model)
    n_simplified = 0
    for i, sd in enumerate(solids):         # solid collide blocks, per-solid index byte set
        cs = struct.unpack_from("<i", sd, 0)[0]
        collide = sd[4:4 + cs]
        if simplify:
            # Single-convex solids only: parse -> simplify hull -> re-emit IVP. Keep
            # verbatim if it isn't smaller (matches Valve's CollideSize check) or on any
            # failure (multi-convex ledge trees fall through here until tree-emit lands).
            try:
                import ivp_collide
                surf = ivp_collide.parse_surface(collide)
                if len(surf.convexes) == 1:
                    nc = ivp_collide.write_surface(ivp_collide.simplify_surface(surf))
                    if len(nc) < len(collide):
                        collide = nc; n_simplified += 1
            except Exception:
                pass
        sb = bytearray(struct.pack("<i", len(collide)) + collide)
        if len(sb) > 68:
            sb[68] = i & 0xff               # offset 68 = solid's internal index (Valve sets it)
        out += sb
    kv, kv_warnings = pack_kv(solids_kv, constraints)  # binary keyvalues incl. ragdoll constraints
    out += kv
    open(phx_path, "wb").write(out)
    return dict(solidCount=solidCount, checksum=checksum, numKeys=len(solids_kv),
                numConstraints=len(constraints), warnings=kv_warnings, simplified=n_simplified,
                surfaceprops=sorted({s["sprop"] for s in solids_kv}), size=len(out))

if __name__ == "__main__":
    print(convert(sys.argv[1], sys.argv[2]))
