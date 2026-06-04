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
# surfaceprop name -> index in the Xbox surfaceprops table (decoded from suite .phx)
SPROP = {"metal":0x03, "item":0x33, "metalvehicle":0x51, "default":0x00}

def _f16(x): return struct.pack("<e", x)

def pack_kv(mass, volume, surfaceprop):
    idx = SPROP.get(surfaceprop.lower())
    if idx is None:
        raise KeyError(f"surfaceprop {surfaceprop!r} not in decoded table {list(SPROP)}; "
                       "need its index from the Xbox surfaceprops manifest")
    return (struct.pack("<H", 1) + b"\x04\x01"
            + _f16(volume / VOL_SCALE) + _f16(mass)
            + bytes([0x00, 0xff, idx]) + b"\xff"*5)

def convert(phy_path, phx_path):
    d = open(phy_path, "rb").read()
    hdrsize, vid, solidCount, checksum = struct.unpack_from("<iiii", d, 0)
    o = 16; solids = []
    for s in range(solidCount):
        cs = struct.unpack_from("<i", d, o)[0]
        solids.append(d[o:o+4+cs]); o += 4 + cs
    text = d[o:].decode("latin-1", "replace")
    g = lambda k: (re.search(rf'"{k}"\s+"([^"]+)"', text) or [None, None])[1]
    mass = float(g("mass")); volume = float(g("volume")); sprop = g("surfaceprop")
    out = bytearray(d[:16])                 # header verbatim (checksum = model)
    for sd in solids: out += sd             # solids verbatim
    out += pack_kv(mass, volume, sprop)     # packed kv
    open(phx_path, "wb").write(out)
    return dict(solidCount=solidCount, checksum=checksum, mass=mass, volume=volume,
                surfaceprop=sprop, size=len(out))

if __name__ == "__main__":
    print(convert(sys.argv[1], sys.argv[2]))
