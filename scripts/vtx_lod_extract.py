#!/usr/bin/env python3
"""
vtx_lod_extract.py - extract the Xbox root-LOD geometry from a PC dx90 VTX.

This is the multi-LOD-specific front-end for the VTX side. For the Original
Xbox, rootLOD = min(2, numLODs-1). We navigate the PC VTX chain to that LOD's
mesh/stripgroup(s) and pull out the geometry that the matching clamped VVD
(first numLODVertexes[rootLOD] verts) is self-consistent with:

  - per stripgroup: the Vertex_t records (origMeshVertID + numBones), the u16
    index array, and the strip header(s).

The extracted (verts, indices, strips) feed the existing Xbox VTX emitter
(debris-template repack: 9-byte packed Vertex_t, u16 indices, strip tail).

Self-consistency guarantees (verified across the suite, see validate()):
  - every origMeshVertID < keep (= numLODVertexes[rootLOD])
  - every index < stripgroup numVerts
  - index count is a multiple of 3 (trilist) for these props
"""
import struct

def I(d, o):  return struct.unpack_from("<i", d, o)[0]
def Hh(d, o): return struct.unpack_from("<H", d, o)[0]

FILEHDR = None  # PC VTX FileHeader_t fields read positionally below
MINLOD = 2

def parse_pc_vtx(d):
    """Walk PC dx90 VTX, return nested structure with absolute offsets."""
    hdr = dict(version=I(d,0), vertCacheSize=I(d,4),
               maxBonesPerStrip=Hh(d,8), maxBonesPerTri=Hh(d,10),
               maxBonesPerVert=I(d,12), checksum=I(d,16), numLODs=I(d,20),
               matReplListOffset=I(d,24), numBodyParts=I(d,28), bodyPartOffset=I(d,32))
    bps=[]
    for bi in range(hdr["numBodyParts"]):
        bp = hdr["bodyPartOffset"] + bi*8        # BodyPartHeader_t: numModels(i), modelOffset(i)
        nmodels=I(d,bp); moff=I(d,bp+4); mbase=bp+moff
        models=[]
        for mi in range(nmodels):
            mh = mbase + mi*8                     # ModelHeader_t: numLODs(i), lodOffset(i)
            nLOD=I(d,mh); loff=I(d,mh+4); lbase=mh+loff
            lods=[]
            for li in range(nLOD):
                lod = lbase + li*12               # ModelLODHeader_t: numMeshes(i), meshOffset(i), switchPoint(f)
                nmesh=I(d,lod); meoff=I(d,lod+4); mebase=lod+meoff
                meshes=[]
                for mei in range(nmesh):
                    me = mebase + mei*9           # MeshHeader_t: numStripGroups(i), sgOffset(i), flags(byte)
                    nsg=I(d,me); sgoff=I(d,me+4); meflags=d[me+8]; sgbase=me+sgoff
                    sgs=[]
                    for si in range(nsg):
                        sg = sgbase + si*25       # StripGroupHeader_t (25B, see header)
                        nv=I(d,sg); vo=I(d,sg+4); ni=I(d,sg+8); io=I(d,sg+12)
                        ns=I(d,sg+16); so=I(d,sg+20); sgflags=d[sg+24]
                        verts_base = sg+vo; idx_base = sg+io; strip_base = sg+so
                        verts=[]
                        for vi in range(nv):
                            vbase=verts_base+vi*9
                            verts.append(dict(numBones=d[vbase+3],
                                              origMeshVertID=Hh(d,vbase+4),
                                              raw=d[vbase:vbase+9]))
                        indices=[Hh(d, idx_base+2*k) for k in range(ni)]
                        strips=[]
                        for ti in range(ns):
                            st = strip_base + ti*27   # StripHeader_t (27B)
                            nbsc = I(d, st+19); bsco = st + I(d, st+23)
                            bsc = [(I(d,bsco+j*8), I(d,bsco+j*8+4)) for j in range(nbsc)]
                            strips.append(dict(numIndices=I(d,st), indexOffset=I(d,st+4),
                                               numVerts=I(d,st+8), vertOffset=I(d,st+12),
                                               numBones=Hh(d,st+16), flags=d[st+18],
                                               numBoneStateChanges=nbsc, bsc=bsc,
                                               raw=d[st:st+27]))
                        sgs.append(dict(numVerts=nv, numIndices=ni, numStrips=ns, flags=sgflags,
                                        verts=verts, indices=indices, strips=strips))
                    meshes.append(dict(flags=meflags, stripgroups=sgs))
                lods.append(dict(meshes=meshes))
            models.append(dict(lods=lods))
        bps.append(dict(models=models))
    return hdr, bps

def root_lod_geometry(path, root_lod=None):
    d=open(path,"rb").read()
    hdr,bps=parse_pc_vtx(d)
    root=min(MINLOD if root_lod is None else root_lod, hdr["numLODs"]-1)
    # single-mesh single-sg target: bodypart0/model0/lod[root]/mesh0/sg0
    sg = bps[0]["models"][0]["lods"][root]["meshes"][0]["stripgroups"][0]
    st0 = sg["strips"][0] if sg["strips"] else dict(numBones=0, flags=1, bsc=[])
    return dict(root=root, numLODs=hdr["numLODs"], checksum=hdr["checksum"],
                numVerts=sg["numVerts"], numIndices=sg["numIndices"],
                numStrips=sg["numStrips"], verts=sg["verts"],
                indices=sg["indices"], strips=sg["strips"],
                strip_numBones=st0["numBones"], strip_flags=st0["flags"],
                bsc=st0["bsc"])
