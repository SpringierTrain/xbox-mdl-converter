#!/usr/bin/env python3
"""
vtx_emit_skinned.py - emit an Xbox v47 VTX for a 1/1/1/1/1 prop, supporting
hardware-skinned strips (bone state changes). Generalizes vtx_emit.py.

Xbox layout (decoded byte-exact from wood_splinters01a + wood_fence01c):
  [chain+strip : 0..94][verts nv*9][indices ni*2][bsc nbsc*4][matRepl numLODs*4]

FileHeader packed fields used:
  @16 checksum i32, @21 matReplListOffset u24 (= filesize-4),
  @28 fileLength u32 (= filesize)
StripGroupHeader @57: numVerts u16@57, vertOffset u32@59(=37 -> verts@94),
  numIndices u16@63, indexOffset u32@65(=37+nv*9), numStrips u16@69,
  stripOffset u32@71(=19 -> strip@76)
StripHeader @76: numIndices u16@76, indexOffset u32@78(=0), numVerts u16@82,
  vertOffset u32@84(=0), numBones u8@88, flags u8@89, numBoneStateChanges u8@90,
  boneStateChangeOffset u24@91 (relative to strip@76)
Bone state change (Xbox): u16 hardwareID, u16 newBoneID  (PC stores int32 pairs).
Vertices & indices are PC dx90 records verbatim (optionally cache-permuted by
the caller, which keeps the pair self-consistent).
"""
import struct

# Canonical 94-byte VTX chain header for a 1/1/1/1/1 single-LOD model.
# All render-critical fields (checksum, offsets, counts, strip) are overwritten
# below; the bytes kept are the constant chain navigation (bodypart/model/lod/
# mesh sub-headers) + FileHeader hints, identical for any 1/1/1/1/1 numLODs=1 VTX.
CHAIN94 = (b'\x07\x00\x00\x00\x18\x00\x00\x00/\x00\t\x00\x03\x00\x00\x00'
           b'\x00\x00\x00\x00\x01\xe6\x00\x00\x01 \x00\x00\xea\x00\x00\x00'
           b'\x01\x04\x00\x00\x01\x04\x00\x00\x01\x08\x00\x00\x00\x00\x00\x00'
           b'\x01\x00\x02\x00\t\x00\x00\x00\x00\x0c\x00%\x00\x00\x00\x0c\x00'
           b'\x91\x00\x00\x00\x01\x00\x13\x00\x00\x00\x02\x0c\x00\x00\x00\x00'
           b'\x00\x0c\x00\x00\x00\x00\x00\x00\x01\x00\x96\x00\x00')

def _u24(buf, off, val):
    buf[off] = val & 0xFF; buf[off+1] = (val>>8)&0xFF; buf[off+2] = (val>>16)&0xFF

def emit(geom, template_path=None, checksum=None):
    """geom: numVerts, numIndices, numStrips(=1), numBones, strip_flags,
             verts_bytes (nv*9, verbatim PC records, possibly permuted),
             indices_bytes (ni*2), bsc=[(hardwareID,newBoneID),...],
             numLODs, checksum.
       template_path: optional path to copy chain[0:94] from; if None, uses the
             embedded CHAIN94 (correct for any 1/1/1/1/1 single-LOD model)."""
    head = bytearray(open(template_path, "rb").read()[:94] if template_path else CHAIN94)
    nv = geom["numVerts"]; ni = geom["numIndices"]; nbsc = len(geom["bsc"])
    cks = geom["checksum"] if checksum is None else checksum
    numLODs = geom.get("numLODs", 1)

    verts = geom["verts_bytes"]; indices = geom["indices_bytes"]
    bsc = b"".join(struct.pack("<HH", hw, nb) for (hw, nb) in geom["bsc"])
    matrepl = b"\x00\x00\x00\x00" * numLODs

    vert_abs   = 94
    index_abs  = vert_abs + nv*9
    bsc_abs    = index_abs + ni*2
    matrepl_abs= bsc_abs + nbsc*4
    filesize   = matrepl_abs + len(matrepl)

    # FileHeader
    struct.pack_into("<i", head, 16, cks)
    _u24(head, 21, filesize - len(matrepl))           # matReplListOffset
    struct.pack_into("<I", head, 28, filesize)        # fileLength
    # StripGroup @57
    struct.pack_into("<H", head, 57, nv)
    struct.pack_into("<I", head, 59, vert_abs - 57)   # 37
    struct.pack_into("<H", head, 63, ni)
    struct.pack_into("<I", head, 65, index_abs - 57)
    struct.pack_into("<H", head, 69, geom["numStrips"])
    struct.pack_into("<I", head, 71, 76 - 57)         # 19
    # Strip @76
    struct.pack_into("<H", head, 76, ni)
    struct.pack_into("<I", head, 78, 0)
    struct.pack_into("<H", head, 82, nv)
    struct.pack_into("<I", head, 84, 0)
    head[88] = geom["numBones"] & 0xFF
    head[89] = geom["strip_flags"] & 0xFF
    head[90] = nbsc & 0xFF
    _u24(head, 91, bsc_abs - 76)                       # boneStateChangeOffset (rel strip)

    return bytes(head) + verts + indices + bsc + matrepl
