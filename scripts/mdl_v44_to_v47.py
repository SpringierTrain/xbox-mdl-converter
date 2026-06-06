#!/usr/bin/env python3
"""mdl_v44_to_v47.py - PC v44 skinned .mdl -> Original Xbox v47 (functional repack).
First target: wood_fence01c-class (skinned, 1 bodypart/model/mesh). Validates vs
v47_reader --check and structural compare to the real Xbox file."""
import struct

def I(d,o): return struct.unpack_from("<i",d,o)[0]
def U16(d,o): return struct.unpack_from("<H",d,o)[0]
def f3(d,o): return struct.unpack_from("<3f",d,o)
def f4(d,o): return struct.unpack_from("<4f",d,o)
def cstr(d,o):
    e=d.find(b"\x00",o); return d[o:e]
def h3(v): return struct.pack("<3e",*v)

V44=dict(length=76,eye=80,illum=92,hmin=104,hmax=116,vmin=128,vmax=140,flags=152,
 numbones=156,boneindex=160,numhitbox=172,hitboxindex=176,numanim=180,animindex=184,
 numseq=188,seqindex=192,numtex=204,texindex=208,numcd=212,cdindex=216,
 numskinref=220,numskinfam=224,skinindex=228,numbp=232,bpindex=236,numatt=240,attindex=244,
 surfaceprop=308,kvindex=312,kvsize=316,mass=328,contents=332)

class Pool:
    def __init__(s): s.buf=bytearray(b"\x00"); s.m={b"":0}
    def add(s,x):
        if isinstance(x,str): x=x.encode("latin-1")
        if x in s.m: return s.m[x]
        o=len(s.buf); s.buf+=x+b"\x00"; s.m[x]=o; return o

def convert(pc_path,out_path,reduce=False,mat_override=None,pick_seq=None,root_lod=None):
    d=open(pc_path,"rb").read(); g=lambda k: I(d,V44[k])
    nb=g("numbones"); bi=g("boneindex"); nhs=g("numhitbox"); hsi=g("hitboxindex")
    na=g("numanim"); ai=g("animindex"); ns=g("numseq"); si=g("seqindex")
    ntex=g("numtex"); ti=g("texindex"); ncd=g("numcd"); cdi=g("cdindex")
    nsr=g("numskinref"); nsf=g("numskinfam"); ski=g("skinindex")
    nbp=g("numbp"); bpi=g("bpindex"); checksum=I(d,8)
    pool=Pool(); P=pool.add
    mdlname=cstr(d,12); P(mdlname)    # v44 studiohdr name is inline char[64]@12

    # ---- parse v44 ----
    bones=[]
    for k in range(nb):
        b=bi+k*216
        bones.append(dict(name=cstr(d,b+I(d,b)),parent=I(d,b+4),ctl=I(d,b+8),
            pos=f3(d,b+32),quat=f4(d,b+44),rot=f3(d,b+60),posscale=f3(d,b+72),
            rotscale=f3(d,b+84),p2b=struct.unpack_from("<12f",d,b+96),
            flags=I(d,b+160),
            surfaceprop=cstr(d,b+176+I(d,b+176)),contents=I(d,b+180)))
    hsets=[]
    for k in range(nhs):
        h=hsi+k*12; nhb=I(d,h+4); hbi=h+I(d,h+8); boxes=[]
        for j in range(nhb):
            bb=hbi+j*68
            boxes.append(dict(bone=I(d,bb),bbmin=f3(d,bb+8),bbmax=f3(d,bb+20),
                name=cstr(d,bb+32+I(d,bb+32)) if I(d,bb+32) else b""))
        hsets.append(dict(name=cstr(d,h+I(d,h)),boxes=boxes))
    # anim track data is a contiguous region after the descriptor array; each
    # anim's track runs from its (descbase+animindex) to the next anim's track.
    trk_offs=[ai+k*100+I(d,ai+k*100+56) for k in range(na)]
    anims=[]
    for k in range(na):
        a=ai+k*100; end=trk_offs[k+1] if k+1<na else si
        anims.append(dict(name=cstr(d,a+I(d,a+4)),fps=struct.unpack_from("<f",d,a+8)[0],
            flags=I(d,a+12),numframes=I(d,a+16),track=d[trk_offs[k]:end]))
    # seqs (parse label/activity/bbox/weightlist/flags)
    seqs=[]
    for k in range(ns):
        sq=si+k*212
        gs=(I(d,sq+68),I(d,sq+72)); ncells=max(1,gs[0]*gs[1]); aii=I(d,sq+60)
        blends=[struct.unpack_from("<h",d,sq+aii+2*j)[0] for j in range(ncells)]
        seqs.append(dict(label=cstr(d,sq+I(d,sq+4)),act=cstr(d,sq+I(d,sq+8)) if I(d,sq+8) else b"",
            flags=I(d,sq+12),bbmin=f3(d,sq+32),bbmax=f3(d,sq+44),numblends=I(d,sq+56),
            groupsize=gs,blends=blends,
            weights=[struct.unpack_from("<f",d,sq+I(d,sq+156)+4*j)[0] for j in range(nb)]))
    # bodypart/model/mesh (single bodypart; N meshes supported)
    bp=bpi; bpname=cstr(d,bp+I(d,bp)); model=bp+I(d,bp+12)
    mname=cstr(d,model)            # v44 model name is inline char[64]
    nummeshes=I(d,model+72); meshindex=I(d,model+76); model_numverts=I(d,model+80)
    MESH_STRIDE=116                # v44 mstudiomesh_t
    pcmeshes=[]                    # per-mesh: material + numLODVertexes[8]
    for mi in range(nummeshes):
        me=model+meshindex+mi*MESH_STRIDE
        pcmeshes.append(dict(material=I(d,me+0),
                             numLODVertexes=[I(d,me+52+4*k) for k in range(8)]))
    # textures
    texs=[]
    for k in range(ntex):
        t=ti+k*64  # v44 mstudiotexture_t=64B
        texs.append(cstr(d,t+I(d,t)))
    cds=[cstr(d,I(d,cdi+4*k)) for k in range(ncd)]
    if mat_override:
        texs[0]=mat_override[0].encode("latin-1"); cds[0]=mat_override[1].encode("latin-1")
    skin=[U16(d,ski+2*i) for i in range(nsr*nsf)]
    surfaceprop=cstr(d,I(d,V44["surfaceprop"])); P(surfaceprop)
    flags=g("flags"); mass=struct.unpack_from("<f",d,V44["mass"])[0]; contents=g("contents")
    hull=(f3(d,V44["hmin"]),f3(d,V44["hmax"])); view=(f3(d,V44["vmin"]),f3(d,V44["vmax"]))
    eye=f3(d,V44["eye"]); illum=f3(d,V44["illum"])

    # ---- (mesh fields parsed above into pcmeshes; rootLOD numverts computed at emit) ----

    # ================= EMIT v47 =================
    out=bytearray(208)
    def pad(n=4):
        while len(out)%n: out.append(0)
    def name_rel(base,s):  # rel index from struct base to pooled string (pool placed later)
        return ("NAME",base,P(s))   # placeholder resolved in 2nd pass
    fixups=[]  # (file_offset, struct_base, pool_str_off)
    def putname(field_off,base,s):
        fixups.append((field_off,base,P(s)))

    # ---- bones @208 ----
    pad(16); assert len(out)==208, len(out)
    bone_base=len(out)
    for k,bo in enumerate(bones):
        b=len(out); rec=bytearray(160)
        putname(b+0,b,bo["name"])
        struct.pack_into("<h",rec,4,bo["parent"]); struct.pack_into("<h",rec,6,-1)
        struct.pack_into("<i",rec,8,bo["ctl"])
        struct.pack_into("<3f",rec,12,*bo["pos"]); struct.pack_into("<4f",rec,24,*bo["quat"])
        struct.pack_into("<3f",rec,40,*bo["rot"]); struct.pack_into("<3f",rec,52,*bo["posscale"])
        struct.pack_into("<3f",rec,64,*bo["rotscale"]); struct.pack_into("<12f",rec,76,*bo["p2b"])
        struct.pack_into("<i",rec,140,bo["flags"])         # BONE_USED_BY_VERTEX flags (skinning setup)
        out+=rec
        # surfacepropidx@152, contents@156
        putname(b+152,b,bo["surfaceprop"]); struct.pack_into("<i",out,b+156,bo["contents"])
    # ---- hitboxsets ----
    hbset_base=len(out)
    for hs in hsets:
        h=len(out); out+=bytearray(12)
        putname(h+0,h,hs["name"]); struct.pack_into("<i",out,h+4,len(hs["boxes"]))
        struct.pack_into("<i",out,h+8,12)  # hitboxindex rel
        for bx in hs["boxes"]:
            bb=len(out); rec=bytearray(32)
            struct.pack_into("<i",rec,0,bx["bone"]); struct.pack_into("<3f",rec,4,*bx["bbmin"])
            struct.pack_into("<3f",rec,16,*bx["bbmax"]); out+=rec
            putname(bb+28,bb,bx["name"])
    # ---- bonetablebyname ----
    pad(1); btbn=len(out); out+=bytes(sorted(range(nb)))  # identity sort (names already ordered)
    # ---- anims ----
    if reduce and pick_seq is not None:
        # keep ONE chosen sequence and the animation it references, so the model
        # rests in that pose instead of seq0/anim0 (idle). Remap the kept seq's
        # blend indices to 0 (the single emitted anim becomes index 0).
        sq = dict(seqs[pick_seq])
        anim_idx = sq["blends"][0] if sq["blends"] else 0
        emit_anims = [anims[anim_idx]]
        sq["blends"] = [0] * len(sq["blends"])
        emit_seqs = [sq]
    else:
        emit_anims = anims[:1] if reduce else anims
        emit_seqs  = seqs[:1]  if reduce else seqs
    na_out=len(emit_anims); ns_out=len(emit_seqs)
    pad(4); anim_base=len(out)
    anim_descs=[]
    for an in emit_anims:                      # phase 1: contiguous 32B descriptors
        a=len(out); rec=bytearray(32)
        struct.pack_into("<i",rec,0,-a)         # baseptr
        out+=rec
        putname(a+4,a,an["name"])
        struct.pack_into("<f",out,a+8,an["fps"]); struct.pack_into("<i",out,a+12,an["flags"])
        struct.pack_into("<i",out,a+16,an["numframes"])
        anim_descs.append((a,an))
    for (a,an) in anim_descs:                   # phase 2: pooled track data + animindex@24
        tpos=len(out); out+=an["track"]
        struct.pack_into("<i",out,a+24,(tpos-a)<<8)   # animindex (track offset rel desc), <<8 encoding
    # ---- seqs ---- (fixed 100B headers + pooled weightlist/blend tables)
    WF=bytes.fromhex("9cfcffffb901000050010000000000000064000009d235c047d40952384047547000000000000000ffffffffffffffff0100010100000000000000000000663266320000ffffffff00000000006400006400000000000000007000007400000000000000")
    pad(4); seq_base=len(out)
    for (a,an) in anim_descs:                   # now seqindex known: regiondist@20 = (seqindex-desc)<<8
        struct.pack_into("<i",out,a+20,(seq_base-a)<<8)
    seq_hdrs=[]
    for sq in emit_seqs:                       # phase 1: contiguous 100B headers (fixed stride)
        s=len(out); hdr=bytearray(WF)
        struct.pack_into("<i",hdr,0,-s)         # baseptr
        struct.pack_into("<i",hdr,12,sq["flags"])
        struct.pack_into("<3e",hdr,20,*sq["bbmin"]); struct.pack_into("<3e",hdr,26,*sq["bbmax"])
        hdr[48]=min(sq["numblends"],255); hdr[50]=min(sq["groupsize"][0],255); hdr[51]=min(sq["groupsize"][1],255)
        out+=hdr
        putname(s+4,s,sq["label"]); putname(s+8,s,b"")
        seq_hdrs.append((s,sq))
    for (s,sq) in seq_hdrs:                     # phase 2: pooled weightlist + blend table per seq
        wl_pos=len(out)
        for _ in range(nb): out+=struct.pack("<f",1.0)
        bl_pos=len(out)
        for a in sq["blends"]: out+=struct.pack("<h",a)
        pad(4)
        struct.pack_into("<i",out,s+80,wl_pos-s)   # weightlistindex (rel to seq base)
        struct.pack_into("<i",out,s+32,bl_pos-s)   # animindexindex   (rel to seq base)
        bi=bl_pos-s
        # these index fields were inherited stale from the template and pointed into the
        # adjacent seqdesc (100B stride) -> engine read neighbouring bytes as pose data ->
        # corrupt angles. point them at the in-seq anim-index region, matching stock multi-frame.
        struct.pack_into("<i",out,s+16,bi<<8)
        struct.pack_into("<i",out,s+76,bi<<8)
        struct.pack_into("<i",out,s+88,bi<<8)
        struct.pack_into("<i",out,s+92,bi+4)
    # ---- bodypart/model/mesh ----
    pad(4); bp_off=len(out)
    out+=bytearray(12)
    putname(bp_off+0,bp_off,bpname)
    struct.pack_into("<i",out,bp_off+4,1)         # nummodels
    out[bp_off+8]=1                               # base (u8) - matches real Xbox
    out[bp_off+9]=12; out[bp_off+10]=0; out[bp_off+11]=0   # modelindex i24 = 12 (model follows)
    model_off=len(out); out+=bytearray(44)
    putname(model_off+0,model_off,mname)
    struct.pack_into("<i",out,model_off+12,44)    # meshindex (meshes right after model)
    # rootLOD for the MDL meshes: mirror the VVD/VTX rule. numLODs isn't stored in the MDL,
    # so derive the count of distinct LOD slots from the per-mesh numLODVertexes when not given.
    if root_lod is None:
        # number of LODs = length of the longest strictly/loosely-decreasing prefix is unreliable;
        # default to the Xbox rule min(2, numLODs-1) using the model's own numLOD slots.
        # numLODVertexes[k]==numLODVertexes[k+1] tail marks padding; count real LODs:
        nlods=8
        for k in range(7,0,-1):
            if any(m["numLODVertexes"][k]!=m["numLODVertexes"][k-1] for m in pcmeshes):
                nlods=k+1; break
        else:
            nlods=1
        rl=min(2, nlods-1)
    else:
        rl=root_lod
    # per-mesh rootLOD vertex count + cumulative vertexoffset within the (gathered) model pool
    voff=0; emit_meshes=[]
    for pm in pcmeshes:
        nv_root=pm["numLODVertexes"][rl]
        emit_meshes.append(dict(material=pm["material"], numverts=nv_root, vertexoffset=voff,
                                numLODVertexes=pm["numLODVertexes"]))
        voff+=nv_root
    model_numverts_root=voff
    struct.pack_into("<H",out,model_off+16,nummeshes)
    struct.pack_into("<H",out,model_off+18,model_numverts_root)
    for em in emit_meshes:
        mesh_off=len(out); out+=bytearray(64)
        struct.pack_into("<i",out,mesh_off+0,em["material"])
        struct.pack_into("<i",out,mesh_off+4,model_off-mesh_off)   # modelindex (rel)
        struct.pack_into("<i",out,mesh_off+8,em["numverts"])
        struct.pack_into("<i",out,mesh_off+12,em["vertexoffset"])
        # numLODVertexes[8]: flatten [0..rl-1] to the rootLOD count (matches the clamped VVD)
        flat=list(em["numLODVertexes"])
        for k in range(rl): flat[k]=em["numverts"]
        for j in range(8): struct.pack_into("<H",out,mesh_off+48+2*j,flat[j]&0xFFFF)
    # ---- textures ----
    pad(4); tex_off=len(out)
    for tname in texs:
        t=len(out); out+=bytearray(16); putname(t+0,t,tname)
    # ---- cdtextures (offset table -> abs string offsets) ----
    pad(4); cd_off=len(out)
    cd_fix=[]
    for cn in cds:
        cf=len(out); out+=bytearray(4); cd_fix.append((cf,P(cn)))
    # ---- skin ----
    pad(2); skin_off=len(out)
    for v in skin: out+=struct.pack("<H",v)
    # ---- strings ----
    pad(4); pool_off=len(out); out+=pool.buf
    # ---- keyvalues (prop_data etc.) appended after pool ----
    kvsz=I(d,V44["kvsize"]); kvidx=I(d,V44["kvindex"])
    kv_off=0
    if kvsz>0:
        pad(4); kv_off=len(out); out+=d[kvidx:kvidx+kvsz]

    # resolve name fixups (rel to struct base) and cdtexture abs offsets
    for foff,base,soff in fixups:
        struct.pack_into("<i",out,foff,(pool_off+soff)-base)
    for cf,soff in cd_fix:
        struct.pack_into("<i",out,cf,pool_off+soff)

    # ---- header ----
    def u8(o,v): out[o]=v&0xff
    def i24(o,v): out[o]=v&0xff; out[o+1]=(v>>8)&0xff; out[o+2]=(v>>16)&0xff
    def i32(o,v): struct.pack_into("<i",out,o,v)
    def u16(o,v): struct.pack_into("<H",out,o,v)
    out[0:4]=b"IDST"; i32(4,47); i32(8,checksum); i32(12,pool_off+P(mdlname)); i32(16,len(out))
    out[20:26]=h3(eye); out[26:32]=h3(illum); out[32:38]=h3(hull[0]); out[38:44]=h3(hull[1])
    out[44:50]=h3(view[0]); out[50:56]=h3(view[1]); i32(56,flags)
    u8(60,nb); i24(61,bone_base); u8(68,nhs); i24(69,hbset_base)
    u16(72,na_out); u16(74,ns_out); i32(76,anim_base); i32(80,seq_base)
    u8(92,ntex); i24(93,tex_off); u8(96,ncd); i24(97,cd_off)
    u16(100,nsr); u16(102,nsf); i32(104,skin_off)
    u8(108,nbp); i24(109,bp_off); u8(112,0); i24(113,hbset_base)
    i32(148,pool_off+P(surfaceprop)); struct.pack_into("<f",out,164,mass); i32(168,contents)
    if kvsz>0: i32(152,kv_off); i32(156,kvsz)
    i32(192,btbn)
    open(out_path,"wb").write(out)
    return dict(size=len(out),bones=nb,anims=na,seqs=ns,textures=ntex)

if __name__=="__main__":
    import sys; print(convert(sys.argv[1],sys.argv[2]))
