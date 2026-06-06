#!/usr/bin/env python3
"""
vtx_emit_multimesh.py - emit an Xbox v47 VTX for a Type-B multi-material model
(1 bodypart / 1 model / 1 LOD / N meshes / 1 stripgroup each / 1 strip each).

Chain navigation decoded byte-exact (verified 51/51 single-LOD 2-mesh models):
  count = u8, following offset = u24, offsets relative to the containing header,
  except bodyPartOffset which is relative to file start.

Layout:
  [FileHeader 32B][bodypart 4B][model 4B][lod 8B]
  [N x mesh 9B][N x stripgroup 19B][N x strip 18B]
  [verts grouped][indices grouped][bsc grouped][matRepl numLODs*4]
"""
import struct

def _u24(buf, off, val):
    buf[off]=val&0xFF; buf[off+1]=(val>>8)&0xFF; buf[off+2]=(val>>16)&0xFF

# Xbox FileHeader constants (identical across wood / ammocrate / gibs)
_FH = bytes([0x07,0,0,0, 0x18,0,0,0, 0x2f,0,0x09,0, 0x03,0,0,0])  # @0..15

def emit(meshes, checksum, numLODs=1, switchPoint=0.0):
    """meshes: list of dicts, each:
         verts_bytes (nv*9 verbatim PC Vertex_t), numVerts,
         indices_bytes (ni*2), numIndices,
         numBones, strip_flags, sg_flags, mesh_flags,
         bsc=[(hwID,newBoneID),...]
       Returns the full Xbox .xbox.vtx bytes."""
    N = len(meshes)
    HDR = 32 + 4 + 4 + 8          # FileHeader+bodypart+model+lod = 48
    mesh_base   = HDR             # 48
    sg_base     = mesh_base + 9*N
    strip_base  = sg_base   + 19*N
    data_base   = strip_base+ 18*N

    # group data regions
    verts_abs=[]; idx_abs=[]; bsc_abs=[]
    cur = data_base
    for m in meshes:
        verts_abs.append(cur); cur += m["numVerts"]*9
    for m in meshes:
        idx_abs.append(cur);   cur += m["numIndices"]*2
    for m in meshes:
        bsc_abs.append(cur);   cur += len(m["bsc"])*4
    matrepl_abs = cur
    filesize = matrepl_abs + numLODs*4

    buf = bytearray(filesize)
    # ---- FileHeader ----
    buf[0:16] = _FH
    struct.pack_into("<i", buf, 16, checksum)
    buf[20] = numLODs & 0xFF
    _u24(buf, 21, matrepl_abs)              # matReplListOffset
    buf[24] = 1                             # numBodyParts
    _u24(buf, 25, 32)                       # bodyPartOffset (rel file start)
    struct.pack_into("<I", buf, 28, filesize)
    # ---- bodypart @32 ----
    buf[32]=1; _u24(buf,33,4)               # numModels=1, modelOffset=4
    # ---- model @36 ----
    buf[36]=1; _u24(buf,37,4)               # numLODs=1, lodOffset=4
    # ---- lod @40 ----
    buf[40]=N; _u24(buf,41,8)               # numMeshes=N, meshOffset=8
    struct.pack_into("<f", buf, 44, switchPoint)
    # ---- meshes ----
    for i,m in enumerate(meshes):
        me = mesh_base + i*9
        buf[me]   = 1                       # numStripGroups
        buf[me+1] = 0
        buf[me+2] = 2                        # const observed in GT
        buf[me+3] = 0
        sg_i = sg_base + i*19
        _u24(buf, me+4, sg_i - me)          # stripGroupHeaderOffset (rel mesh)
        buf[me+7] = 0
        buf[me+8] = m.get("mesh_flags",0) & 0xFF
    # ---- stripgroups ----
    for i,m in enumerate(meshes):
        sg = sg_base + i*19
        st = strip_base + i*18
        struct.pack_into("<H", buf, sg+0,  m["numVerts"])
        struct.pack_into("<I", buf, sg+2,  verts_abs[i]-sg)
        struct.pack_into("<H", buf, sg+6,  m["numIndices"])
        struct.pack_into("<I", buf, sg+8,  idx_abs[i]-sg)
        struct.pack_into("<H", buf, sg+12, 1)              # numStrips
        struct.pack_into("<I", buf, sg+14, st-sg)
        buf[sg+18] = m.get("sg_flags",0) & 0xFF
    # ---- strips ----
    for i,m in enumerate(meshes):
        st = strip_base + i*18
        struct.pack_into("<H", buf, st+0,  m["numIndices"])
        struct.pack_into("<I", buf, st+2,  0)              # indexOffset
        struct.pack_into("<H", buf, st+6,  m["numVerts"])
        struct.pack_into("<I", buf, st+8,  0)              # vertOffset
        buf[st+12] = m["numBones"] & 0xFF
        buf[st+13] = m["strip_flags"] & 0xFF
        buf[st+14] = len(m["bsc"]) & 0xFF
        _u24(buf, st+15, bsc_abs[i]-st)                    # boneStateChangeOffset (rel strip)
    # ---- data ----
    for i,m in enumerate(meshes):
        buf[verts_abs[i]:verts_abs[i]+m["numVerts"]*9] = m["verts_bytes"]
    for i,m in enumerate(meshes):
        buf[idx_abs[i]:idx_abs[i]+m["numIndices"]*2] = m["indices_bytes"]
    for i,m in enumerate(meshes):
        b = b"".join(struct.pack("<HH",hw,nb) for (hw,nb) in m["bsc"])
        buf[bsc_abs[i]:bsc_abs[i]+len(b)] = b
    # matRepl left as zeros
    return bytes(buf)
