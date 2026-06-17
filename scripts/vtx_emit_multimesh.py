#!/usr/bin/env python3
"""
vtx_emit_multimesh.py - emit an Xbox v47 VTX for a Type-B model
(1 bodypart / 1 model / 1 LOD / N meshes / K stripgroups per mesh / 1 strip per sg).

Chain navigation (verified byte-exact on 51/51 single-LOD 2-mesh models):
  count = u8, following offset = u24, offsets relative to the containing header,
  except bodyPartOffset which is relative to file start.

Layout:
  [FileHeader 32B][bodypart 4B][model 4B][lod 8B]
  [N x mesh 9B][ALL stripgroups 19B, grouped by mesh][ALL strips 18B]
  [verts grouped][indices grouped][bsc grouped][matRepl numLODs*4]

Multi-stripgroup support: skinned meshes split into K stripgroups by hardware bone
palette; each stripgroup carries its own strip + bone-state-changes.
"""
import struct

def _u24(buf, off, val):
    buf[off]=val&0xFF; buf[off+1]=(val>>8)&0xFF; buf[off+2]=(val>>16)&0xFF

_FH = bytes([0x07,0,0,0, 0x18,0,0,0, 0x2f,0,0x09,0, 0x03,0,0,0])  # FileHeader @0..15

def emit(meshes, checksum, numLODs=1, switchPoint=0.0):
    """meshes: list of meshes; each mesh is a dict with:
         mesh_flags, stripgroups=[ sg, ... ]  (>=1)
       each sg dict: numVerts, verts_bytes (nv*9), numIndices, indices_bytes (ni*2),
                     numBones, strip_flags, sg_flags, bsc=[(hwID,newBoneID),...]
       Returns the full Xbox .xbox.vtx bytes.

       Backward-compatible: a mesh may instead BE a single-sg dict (old interface);
       it is auto-wrapped as one stripgroup."""
    # normalize: every mesh -> {mesh_flags, stripgroups:[...]}
    norm=[]
    for m in meshes:
        if "stripgroups" in m:
            norm.append(m)
        else:
            norm.append(dict(mesh_flags=m.get("mesh_flags",0), stripgroups=[m]))
    meshes=norm
    N=len(meshes)
    total_sg=sum(len(m["stripgroups"]) for m in meshes)

    HDR=32+4+4+8                       # 48
    mesh_base   = HDR                  # 48
    sg_base     = mesh_base + 9*N
    strip_base  = sg_base   + 19*total_sg
    data_base   = strip_base+ 18*total_sg

    # flat list of (mesh_index, sg) in emission order (grouped by mesh)
    flat=[]
    for mi,m in enumerate(meshes):
        for sg in m["stripgroups"]:
            flat.append((mi,sg))

    # absolute positions of each sg header, strip header
    sg_abs   =[sg_base   + i*19 for i in range(total_sg)]
    strip_abs=[strip_base+ i*18 for i in range(total_sg)]
    # group data: all verts, then all indices, then all bsc (in flat order)
    verts_abs=[]; idx_abs=[]; bsc_abs=[]
    cur=data_base
    for (_,sg) in flat: verts_abs.append(cur); cur+=sg["numVerts"]*9
    for (_,sg) in flat: idx_abs.append(cur);   cur+=sg["numIndices"]*2
    for (_,sg) in flat: bsc_abs.append(cur);   cur+=len(sg["bsc"])*4
    matrepl_abs=cur
    filesize=matrepl_abs+numLODs*4

    buf=bytearray(filesize)
    # FileHeader
    buf[0:16]=_FH
    struct.pack_into("<i",buf,16,checksum)
    buf[20]=numLODs&0xFF
    _u24(buf,21,matrepl_abs)
    buf[24]=1; _u24(buf,25,32)
    struct.pack_into("<I",buf,28,filesize)
    # bodypart/model/lod
    buf[32]=1; _u24(buf,33,4)
    buf[36]=1; _u24(buf,37,4)
    buf[40]=N; _u24(buf,41,8); struct.pack_into("<f",buf,44,switchPoint)
    # meshes (point each to its FIRST stripgroup; SGs grouped by mesh)
    sg_cursor=0
    for mi,m in enumerate(meshes):
        me=mesh_base+mi*9
        k=len(m["stripgroups"])
        buf[me]=k; buf[me+1]=0; buf[me+2]=2; buf[me+3]=0
        # offset to this mesh's first stripgroup; computed arithmetically so a mesh with
        # k==0 (material decimated away at this LOD) still gets a valid in-bounds pointer.
        _u24(buf,me+4, (sg_base + sg_cursor*19) - me)
        buf[me+7]=0; buf[me+8]=m.get("mesh_flags",0)&0xFF
        sg_cursor+=k
    # stripgroups + strips
    for i,(mi,sg) in enumerate(flat):
        s=sg_abs[i]; st=strip_abs[i]
        struct.pack_into("<H",buf,s+0,  sg["numVerts"])
        struct.pack_into("<I",buf,s+2,  verts_abs[i]-s)
        struct.pack_into("<H",buf,s+6,  sg["numIndices"])
        struct.pack_into("<I",buf,s+8,  idx_abs[i]-s)
        struct.pack_into("<H",buf,s+12, 1)            # numStrips
        struct.pack_into("<I",buf,s+14, st-s)
        buf[s+18]=sg.get("sg_flags",0)&0xFF
        struct.pack_into("<H",buf,st+0,  sg["numIndices"])
        struct.pack_into("<I",buf,st+2,  0)
        struct.pack_into("<H",buf,st+6,  sg["numVerts"])
        struct.pack_into("<I",buf,st+8,  0)
        buf[st+12]=sg["numBones"]&0xFF
        buf[st+13]=sg["strip_flags"]&0xFF
        buf[st+14]=len(sg["bsc"])&0xFF
        _u24(buf,st+15, bsc_abs[i]-st)
    # data
    for i,(mi,sg) in enumerate(flat):
        buf[verts_abs[i]:verts_abs[i]+sg["numVerts"]*9]=sg["verts_bytes"]
    for i,(mi,sg) in enumerate(flat):
        buf[idx_abs[i]:idx_abs[i]+sg["numIndices"]*2]=sg["indices_bytes"]
    for i,(mi,sg) in enumerate(flat):
        b=b"".join(struct.pack("<HH",hw,nb) for (hw,nb) in sg["bsc"])
        buf[bsc_abs[i]:bsc_abs[i]+len(b)]=b
    return bytes(buf)


def emit_tree(bodyparts, checksum, numLODs=1, switchPoint=0.0):
    """General N-bodypart / M-model emitter (bodygroups). Each model has 1 LOD (rootLOD).
       bodyparts: [ [ model, ... ], ... ]   where model = [ mesh, ... ]
                  and mesh = {mesh_flags, stripgroups:[sg,...]}  (sg as in emit()).
       Breadth-first layout verified against GT ammocrate_ar2.xbox.vtx (nbp=2, bodygroup).
       Backward note: emit() above covers the common 1-bodypart/1-model case."""
    # normalize meshes' stripgroups
    def norm_mesh(m):
        if "stripgroups" in m: return m
        return dict(mesh_flags=m.get("mesh_flags",0), stripgroups=[m])
    bodyparts=[[ [norm_mesh(me) for me in model] for model in bp] for bp in bodyparts]

    Nbp=len(bodyparts)
    models=[(bi,mi,model) for bi,bp in enumerate(bodyparts) for mi,model in enumerate(bp)]
    Nmodel=len(models)
    # one LOD per model
    lods=[(idx,model) for idx,(bi,mi,model) in enumerate(models)]
    Nlod=len(lods)
    meshes=[(li,me) for li,(_,model) in enumerate(lods) for me in model]
    Nmesh=len(meshes)
    sgs=[(mei,sg) for mei,(_,me) in enumerate(meshes) for sg in me["stripgroups"]]
    Nsg=len(sgs)

    bp_base   = 32
    model_base= bp_base    + 4*Nbp
    lod_base  = model_base + 4*Nmodel
    mesh_base = lod_base   + 8*Nlod
    sg_base   = mesh_base  + 9*Nmesh
    strip_base= sg_base    + 19*Nsg
    data_base = strip_base + 18*Nsg

    # absolute header positions
    bp_pos    =[bp_base    + i*4  for i in range(Nbp)]
    model_pos =[model_base + i*4  for i in range(Nmodel)]
    lod_pos   =[lod_base   + i*8  for i in range(Nlod)]
    mesh_pos  =[mesh_base  + i*9  for i in range(Nmesh)]
    sg_pos    =[sg_base    + i*19 for i in range(Nsg)]
    strip_pos =[strip_base + i*18 for i in range(Nsg)]

    # data regions (grouped over sgs in order)
    verts_abs=[]; idx_abs=[]; bsc_abs=[]; cur=data_base
    for (_,sg) in sgs: verts_abs.append(cur); cur+=sg["numVerts"]*9
    for (_,sg) in sgs: idx_abs.append(cur);   cur+=sg["numIndices"]*2
    for (_,sg) in sgs: bsc_abs.append(cur);   cur+=len(sg["bsc"])*4
    matrepl_abs=cur; filesize=matrepl_abs+numLODs*4

    buf=bytearray(filesize)
    buf[0:16]=_FH
    struct.pack_into("<i",buf,16,checksum)
    buf[20]=numLODs&0xFF; _u24(buf,21,matrepl_abs)
    buf[24]=Nbp; _u24(buf,25,bp_base); struct.pack_into("<I",buf,28,filesize)

    # index maps for first-child lookup
    first_model_of_bp={}
    mi_run=0
    for bi,bp in enumerate(bodyparts):
        first_model_of_bp[bi]=mi_run; mi_run+=len(bp)
    # bodyparts
    for bi in range(Nbp):
        p=bp_pos[bi]; buf[p]=len(bodyparts[bi]); _u24(buf,p+1, model_pos[first_model_of_bp[bi]]-p)
    # models (one lod each; lod index == model index)
    for mi in range(Nmodel):
        p=model_pos[mi]; buf[p]=1; _u24(buf,p+1, lod_pos[mi]-p)
    # lods
    first_mesh_of_lod={}
    run=0
    for li,(_,model) in enumerate(lods):
        first_mesh_of_lod[li]=run; run+=len(model)
    for li in range(Nlod):
        p=lod_pos[li]; nme=len(lods[li][1])
        buf[p]=nme; _u24(buf,p+1, (mesh_base + first_mesh_of_lod[li]*9) - p)
        struct.pack_into("<f",buf,p+4,switchPoint)
    # meshes
    first_sg_of_mesh={}; run=0
    for mei,(_,me) in enumerate(meshes):
        first_sg_of_mesh[mei]=run; run+=len(me["stripgroups"])
    for mei in range(Nmesh):
        p=mesh_pos[mei]; k=len(meshes[mei][1]["stripgroups"])
        buf[p]=k; buf[p+1]=0; buf[p+2]=2; buf[p+3]=0
        _u24(buf,p+4, (sg_base+first_sg_of_mesh[mei]*19)-p)
        buf[p+7]=0; buf[p+8]=meshes[mei][1].get("mesh_flags",0)&0xFF
    # stripgroups + strips + data
    for i,(_,sg) in enumerate(sgs):
        s=sg_pos[i]; st=strip_pos[i]
        struct.pack_into("<H",buf,s+0,  sg["numVerts"]); struct.pack_into("<I",buf,s+2, verts_abs[i]-s)
        struct.pack_into("<H",buf,s+6,  sg["numIndices"]); struct.pack_into("<I",buf,s+8, idx_abs[i]-s)
        struct.pack_into("<H",buf,s+12, 1); struct.pack_into("<I",buf,s+14, st-s)
        buf[s+18]=sg.get("sg_flags",0)&0xFF
        struct.pack_into("<H",buf,st+0, sg["numIndices"]); struct.pack_into("<I",buf,st+2,0)
        struct.pack_into("<H",buf,st+6, sg["numVerts"]);  struct.pack_into("<I",buf,st+8,0)
        buf[st+12]=sg["numBones"]&0xFF; buf[st+13]=sg["strip_flags"]&0xFF
        buf[st+14]=len(sg["bsc"])&0xFF; _u24(buf,st+15, bsc_abs[i]-st)
        buf[verts_abs[i]:verts_abs[i]+sg["numVerts"]*9]=sg["verts_bytes"]
        buf[idx_abs[i]:idx_abs[i]+sg["numIndices"]*2]=sg["indices_bytes"]
        b=b"".join(struct.pack("<HH",hw,nb) for (hw,nb) in sg["bsc"])
        buf[bsc_abs[i]:bsc_abs[i]+len(b)]=b
    return bytes(buf)


def emit_tree_ml(bodyparts, checksum, numLODs, switchPoints=None):
    """Multi-LOD N-bodypart / M-model emitter -- keeps ALL LODs (Valve Xbox structure).
       bodyparts: [ [ model, ... ], ... ]   model = [ lod, ... ]   lod = [ mesh, ... ]
                  mesh = {mesh_flags, stripgroups:[sg,...]} (sg as in emit()).
       Each model carries numLODs LODs. origMeshVertID stays mesh-relative, so per-LOD
       stripgroups are copied verbatim from the PC dx90 chain; they resolve into the
       full fixup-applied (numFixups=0) LOD-sorted VVD. Breadth-first packed layout,
       same nav rules as emit_tree but with N lods per model."""
    if switchPoints is None: switchPoints=[0.0]*numLODs
    def norm_mesh(m):
        if "stripgroups" in m: return m
        return dict(mesh_flags=m.get("mesh_flags",0), stripgroups=[m])
    bodyparts=[[ [ [norm_mesh(me) for me in lod] for lod in model] for model in bp] for bp in bodyparts]

    Nbp=len(bodyparts)
    models=[(bi,mi,model) for bi,bp in enumerate(bodyparts) for mi,model in enumerate(bp)]
    Nmodel=len(models)
    # all lods flattened in model order; remember each lod's index within its model (for switchPoint)
    lods=[(midx,li,lod) for midx,(bi,mi,model) in enumerate(models) for li,lod in enumerate(model)]
    Nlod=len(lods)
    meshes=[(lodi,me) for lodi,(_,_,lod) in enumerate(lods) for me in lod]
    Nmesh=len(meshes)
    sgs=[(mei,sg) for mei,(_,me) in enumerate(meshes) for sg in me["stripgroups"]]
    Nsg=len(sgs)

    bp_base   = 32
    model_base= bp_base    + 4*Nbp
    lod_base  = model_base + 4*Nmodel
    mesh_base = lod_base   + 8*Nlod
    sg_base    = mesh_base  + 9*Nmesh
    strip_base = sg_base    + 19*Nsg
    data_base  = strip_base + 18*Nsg

    bp_pos    =[bp_base    + i*4  for i in range(Nbp)]
    model_pos =[model_base + i*4  for i in range(Nmodel)]
    lod_pos   =[lod_base   + i*8  for i in range(Nlod)]
    mesh_pos  =[mesh_base  + i*9  for i in range(Nmesh)]
    sg_pos    =[sg_base    + i*19 for i in range(Nsg)]
    strip_pos =[strip_base + i*18 for i in range(Nsg)]

    # Valve's exact Xbox VTX layout (verified byte-for-byte against shipped props): sections are
    # GLOBALLY GROUPED by type in the order  headers | strips | verts | indices | bsc | matRepl.
    # The strip block comes BEFORE the verts block. Offsets in each stripgroup header are relative
    # to that header.
    verts_abs=[]; idx_abs=[]; bsc_abs=[]; cur=data_base
    for (_,sg) in sgs: verts_abs.append(cur); cur+=sg["numVerts"]*9
    for (_,sg) in sgs: idx_abs.append(cur);   cur+=sg["numIndices"]*2
    for (_,sg) in sgs: bsc_abs.append(cur);   cur+=len(sg["bsc"])*4
    matrepl_abs=cur; filesize=matrepl_abs+numLODs*4

    buf=bytearray(filesize)
    buf[0:16]=_FH
    struct.pack_into("<i",buf,16,checksum)
    buf[20]=numLODs&0xFF; _u24(buf,21,matrepl_abs)
    buf[24]=Nbp; _u24(buf,25,bp_base); struct.pack_into("<I",buf,28,filesize)

    # bodyparts -> first model
    first_model_of_bp={}; run=0
    for bi,bp in enumerate(bodyparts): first_model_of_bp[bi]=run; run+=len(bp)
    for bi in range(Nbp):
        p=bp_pos[bi]; buf[p]=len(bodyparts[bi]); _u24(buf,p+1, model_pos[first_model_of_bp[bi]]-p)
    # models -> first lod (numLODs each)
    first_lod_of_model={}; run=0
    for midx,(bi,mi,model) in enumerate(models): first_lod_of_model[midx]=run; run+=len(model)
    for midx,(bi,mi,model) in enumerate(models):
        p=model_pos[midx]; buf[p]=len(model); _u24(buf,p+1, lod_pos[first_lod_of_model[midx]]-p)
    # lods -> first mesh
    first_mesh_of_lod={}; run=0
    for li,(_,_,lod) in enumerate(lods): first_mesh_of_lod[li]=run; run+=len(lod)
    for li,(midx,lod_li,lod) in enumerate(lods):
        p=lod_pos[li]; nme=len(lod)
        buf[p]=nme; _u24(buf,p+1, (mesh_base + first_mesh_of_lod[li]*9) - p)
        sp=switchPoints[lod_li] if lod_li < len(switchPoints) else 0.0
        struct.pack_into("<f",buf,p+4,sp)
    # meshes -> first sg (k==0 meshes still get an in-bounds pointer)
    first_sg_of_mesh={}; run=0
    for mei,(_,me) in enumerate(meshes): first_sg_of_mesh[mei]=run; run+=len(me["stripgroups"])
    for mei in range(Nmesh):
        p=mesh_pos[mei]; k=len(meshes[mei][1]["stripgroups"])
        buf[p]=k; buf[p+1]=0; buf[p+2]=2; buf[p+3]=0
        _u24(buf,p+4, (sg_base+first_sg_of_mesh[mei]*19)-p)
        buf[p+7]=0; buf[p+8]=meshes[mei][1].get("mesh_flags",0)&0xFF
    # stripgroups + per-block strip + data
    for i,(_,sg) in enumerate(sgs):
        s=sg_pos[i]; st=strip_pos[i]
        struct.pack_into("<H",buf,s+0,  sg["numVerts"]);   struct.pack_into("<I",buf,s+2, verts_abs[i]-s)
        struct.pack_into("<H",buf,s+6,  sg["numIndices"]); struct.pack_into("<I",buf,s+8, idx_abs[i]-s)
        struct.pack_into("<H",buf,s+12, 1);                struct.pack_into("<I",buf,s+14, st-s)
        buf[s+18]=sg.get("sg_flags",0)&0xFF
        struct.pack_into("<H",buf,st+0, sg["numIndices"]); struct.pack_into("<I",buf,st+2,0)
        struct.pack_into("<H",buf,st+6, sg["numVerts"]);   struct.pack_into("<I",buf,st+8,0)
        buf[st+12]=sg["numBones"]&0xFF; buf[st+13]=sg["strip_flags"]&0xFF
        buf[st+14]=len(sg["bsc"])&0xFF; _u24(buf,st+15, bsc_abs[i]-st)
        buf[verts_abs[i]:verts_abs[i]+sg["numVerts"]*9]=sg["verts_bytes"]
        buf[idx_abs[i]:idx_abs[i]+sg["numIndices"]*2]=sg["indices_bytes"]
        b=b"".join(struct.pack("<HH",hw,nb) for (hw,nb) in sg["bsc"])
        buf[bsc_abs[i]:bsc_abs[i]+len(b)]=b
    return bytes(buf)
