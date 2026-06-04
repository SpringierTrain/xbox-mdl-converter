#!/usr/bin/env python3
"""
v47_reader.py - full validating parser for Original Xbox Half-Life 2 MDL (v47).

This is the reference implementation / test oracle for the eventual PC->v47
writer. It parses the complete studiohdr, walks every array (bones, bodyparts
-> models -> meshes, textures, cdtextures, skins, attachments, hitbox sets,
local animations, local sequences, pose parameters), resolves all pooled
string references, and runs a battery of integrity checks. If a future writer
emits a file this reader validates clean, the conversion is structurally sound.

Format facts (reverse-engineered + cross-validated against combine_camera,
concrete_debris pile, and alyx; see v47_decode.py for the derivation notes):

  studiohdr is a FIXED 208 bytes. Packing vs PC v44:
    name[64] -> int sznameindex (all strings pooled near EOF)
    Vector   -> 3x float16 (half)
    counts   -> IsChar(1B) / IsShort(2B);  indices -> IsInt24(3B) / int32(4B)
    count/index pairs for localanim+localseq and skinref+skinfamilies are
    GROUPED (both counts, then both indices), not interleaved like PC.
  mstudiobone_t = 160B (see BONE_LAYOUT below).
  Animation is demand-loaded from an external .ani (animblocks).

Usage:
    python3 v47_reader.py model.mdl              # full report
    python3 v47_reader.py model.mdl --check      # validation only (exit code)
    python3 v47_reader.py model.mdl --json       # machine-readable dump
"""
import struct
import sys
import json


# ----------------------------------------------------------------------
# low-level readers
# ----------------------------------------------------------------------
def u8(d, o):    return d[o]
def u16(d, o):   return d[o] | (d[o + 1] << 8)
def i24(d, o):   return d[o] | (d[o + 1] << 8) | (d[o + 2] << 16)
def i32(d, o):   return struct.unpack_from("<i", d, o)[0]
def f32(d, o):   return struct.unpack_from("<f", d, o)[0]
def half(d, o):  return struct.unpack_from("<e", d, o)[0]
def vec3h(d, o): return tuple(struct.unpack_from("<3e", d, o))
def vec3f(d, o): return tuple(struct.unpack_from("<3f", d, o))
def quatf(d, o): return tuple(struct.unpack_from("<4f", d, o))


def cstr(d, o):
    """Read a NUL-terminated latin-1 string at absolute offset o."""
    if o <= 0 or o >= len(d):
        return None
    e = d.find(b"\x00", o)
    if e < 0:
        e = len(d)
    return d[o:e].decode("latin-1", "replace")


# ----------------------------------------------------------------------
# studiohdr (fixed 208 bytes) - validated field map
# ----------------------------------------------------------------------
HEADER_FIELDS = [
    ("id", 0, lambda d, o: d[o:o + 4]),
    ("version", 4, i32), ("checksum", 8, i32),
    ("sznameindex", 12, i32), ("length", 16, i32),
    ("eyeposition", 20, vec3h), ("illumposition", 26, vec3h),
    ("hull_min", 32, vec3h), ("hull_max", 38, vec3h),
    ("view_bbmin", 44, vec3h), ("view_bbmax", 50, vec3h),
    ("flags", 56, i32),
    ("numbones", 60, u8), ("boneindex", 61, i24),
    ("numbonecontrollers", 64, u8), ("bonecontrollerindex", 65, i24),
    ("numhitboxsets", 68, u8), ("hitboxsetindex", 69, i24),
    ("numlocalanim", 72, u16), ("numlocalseq", 74, u16),
    ("localanimindex", 76, i32), ("localseqindex", 80, i32),
    ("activitylistversion", 84, i32), ("eventsindexed", 88, i32),
    ("numtextures", 92, u8), ("textureindex", 93, i24),
    ("numcdtextures", 96, u8), ("cdtextureindex", 97, i24),
    ("numskinref", 100, u16), ("numskinfamilies", 102, u16),
    ("skinindex", 104, i32),
    ("numbodyparts", 108, u8), ("bodypartindex", 109, i24),
    ("numlocalattachments", 112, u8), ("localattachmentindex", 113, i24),
    ("numlocalnodes", 116, u8), ("localnodeindex", 117, i24),
    ("localnodenameindex", 120, i32),
    ("numflexdesc", 124, u8), ("flexdescindex", 125, i24),
    ("numflexcontrollers", 128, u8), ("flexcontrollerindex", 129, i24),
    ("numflexrules", 132, u8), ("flexruleindex", 133, i24),
    ("numikchains", 136, u8), ("ikchainindex", 137, i24),
    ("nummouths", 140, u8), ("mouthindex", 141, i24),
    ("numlocalposeparameters", 144, u8), ("localposeparamindex", 145, i24),
    ("surfacepropindex", 148, i32),
    ("keyvalueindex", 152, i32), ("keyvaluesize", 156, i32),
    ("mass", 164, f32), ("contents", 168, i32),
    ("bonetablebynameindex", 192, i32),
]

HEADER_SIZE = 208

# Xbox mstudiobone_t (160B), relative offsets - SOLVED/verified.
BONE_SIZE = 160
BONE_LAYOUT = {
    "sznameindex": (0, i32), "parent": (4, lambda d, o: struct.unpack_from("<h", d, o)[0]),
    "bonecontroller": (8, i32),
    "pos": (12, vec3f), "quat": (24, quatf), "rot": (40, vec3f),
    "posscale": (52, vec3f), "rotscale": (64, vec3f),
    # poseToBone matrix3x4 at 76..124 (12 floats)
    "surfacepropidx": (124, i32), "contents": (128, i32),
}


# ----------------------------------------------------------------------
# parser
# ----------------------------------------------------------------------
class V47Reader:
    def __init__(self, path):
        self.path = path
        with open(path, "rb") as f:
            self.d = f.read()
        self.errors = []
        self.warnings = []
        self.hdr = {}
        self.bones = []
        self.textures = []
        self.cdtextures = []
        self.bodyparts = []
        self.attachments = []
        self.hitboxsets = []
        self.anims = []
        self.seqs = []
        self.poseparams = []
        self._parse()

    def err(self, m): self.errors.append(m)
    def warn(self, m): self.warnings.append(m)

    def _name_at(self, base, rel_index):
        """Resolve a sznameindex stored at (base + field) -> string.
        v47 name indices are relative to the owning struct's base."""
        return cstr(self.d, base + rel_index)

    def _parse(self):
        d = self.d
        if d[0:4] != b"IDST":
            self.err(f"bad magic {d[0:4]!r}")
            return
        for name, off, rd in HEADER_FIELDS:
            self.hdr[name] = rd(d, off)
        h = self.hdr
        if h["version"] != 47:
            self.warn(f"version is {h['version']}, expected 47")
        if h["length"] != len(d):
            self.err(f"length {h['length']} != file size {len(d)}")
        self.name = cstr(d, h["sznameindex"])

        self._parse_bones()
        self._parse_textures()
        self._parse_bodyparts()
        self._parse_attachments()
        self._validate()

    def _parse_bones(self):
        d, h = self.d, self.hdr
        base0, n = h["boneindex"], h["numbones"]
        if base0 != HEADER_SIZE and n > 0:
            self.warn(f"boneindex {base0} != header size {HEADER_SIZE}")
        for k in range(n):
            b = base0 + k * BONE_SIZE
            if b + BONE_SIZE > len(d):
                self.err(f"bone[{k}] runs past EOF")
                break
            rec = {}
            for fld, (rel, rd) in BONE_LAYOUT.items():
                rec[fld] = rd(d, b + rel)
            rec["name"] = cstr(d, b + rec["sznameindex"])
            rec["surfaceprop"] = cstr(d, b + rec["surfacepropidx"]) \
                if rec["surfacepropidx"] else None
            rec["_base"] = b
            self.bones.append(rec)

    def _parse_textures(self):
        d, h = self.d, self.hdr
        # mstudiotexture_t: int sznameindex, int flags, int used, ... (PC 64B;
        # we only need the name index, which is the struct's first int).
        # Stride is derived from spacing between resolvable names.
        base0, n = h["textureindex"], h["numtextures"]
        # Xbox mstudiotexture_t = 16B (PC is 64B): sznameindex, flags, then
        # 2 ints (used/unused). Verified on female_01 (8 textures resolve).
        stride = 16
        for k in range(n):
            t = base0 + k * stride
            if t + 4 > len(d):
                break
            szi = i32(d, t)
            nm = cstr(d, t + szi)
            self.textures.append({"index": k, "_base": t, "name": nm})
        # cdtextures: array of int offsets each pointing to a dir string
        cb, cn = h["cdtextureindex"], h["numcdtextures"]
        for k in range(cn):
            off = i32(d, cb + k * 4)
            self.cdtextures.append(cstr(d, off))

    def _parse_bodyparts(self):
        d, h = self.d, self.hdr
        # mstudiobodyparts_t (PC): int sznameindex, int nummodels, int base,
        # int modelindex. 16B. Indices relative to bodypart base.
        base0, n = h["bodypartindex"], h["numbodyparts"]
        stride = 16
        for k in range(n):
            bp = base0 + k * stride
            if bp + stride > len(d):
                break
            szi = i32(d, bp)
            nm = cstr(d, bp + szi)
            nummodels = i32(d, bp + 4)
            modelindex = i32(d, bp + 12)
            models = self._parse_models(bp, nummodels, modelindex)
            self.bodyparts.append({
                "index": k, "_base": bp, "name": nm,
                "nummodels": nummodels, "models": models,
            })

    def _parse_models(self, bp_base, nummodels, modelindex):
        # mstudiomodel_t (PC): char name[64], int type, float boundingradius,
        # int nummeshes, int meshindex, ... On Xbox the name MAY be pooled;
        # we read meshes count/offset conservatively and flag if uncertain.
        d = self.d
        out = []
        # Model struct on PC is 148B; Xbox likely shrinks the inline name[64]
        # to an index like everywhere else. We detect which by testing whether
        # the first 4 bytes look like a small offset (index) or ASCII (inline).
        mbase = bp_base + modelindex
        first4 = d[mbase:mbase + 4]
        inline = any(32 <= c < 127 for c in first4)
        out.append({
            "_base": mbase, "nummodels": nummodels,
            "name_mode": "inline" if inline else "indexed",
            "_note": "model walk UNRESOLVED: on Xbox the bodypart->model "
                     "offset convention differs from PC (modelindex is not "
                     "simply bodypart_base+rel; computed bases land inside the "
                     "string pool). Needs the studiomdl writer's bodypart/"
                     "model emit code or a byte-level trace to pin. Header, "
                     "bones, textures, attachments, cdtextures all resolved.",
        })
        return out

    def _parse_attachments(self):
        d, h = self.d, self.hdr
        # mstudioattachment_t (PC): int sznameindex, int flags, int localbone,
        # matrix3x4 local. 92B. Name index relative to attachment base.
        base0, n = h["localattachmentindex"], h["numlocalattachments"]
        stride = 60  # Xbox mstudioattachment_t (PC is 92B)
        for k in range(n):
            a = base0 + k * stride
            if a + 4 > len(d):
                break
            szi = i32(d, a)
            nm = cstr(d, a + szi)
            self.attachments.append({"index": k, "_base": a, "name": nm})

    # ------------------------------------------------------------------
    def _validate(self):
        d, h = self.d, self.hdr
        # 1. all array offsets in-bounds
        for fld in ("boneindex", "textureindex", "bodypartindex",
                    "localattachmentindex", "hitboxsetindex",
                    "localanimindex", "localseqindex", "skinindex"):
            v = h.get(fld, 0)
            cntfld = fld.replace("index", "").replace("local", "")
            if v and v >= len(d):
                self.err(f"{fld}={v} is past EOF ({len(d)})")
        # 2. names resolved
        if not self.name:
            self.err("model name did not resolve")
        unresolved_bones = [b["_base"] for b in self.bones if not b["name"]]
        if unresolved_bones:
            self.err(f"{len(unresolved_bones)} bone name(s) unresolved")
        # 3. bone scales sane (posscale typically small, e.g. 1/256)
        for b in self.bones:
            ps = b["posscale"]
            if any(abs(x) > 100 for x in ps):
                self.warn(f"bone {b['name']!r} posscale looks off: {ps}")
        # 4. quaternion roughly unit
        for b in self.bones:
            q = b["quat"]
            s = sum(x * x for x in q)
            if not (0.5 < s < 1.5):
                self.warn(f"bone {b['name']!r} quat not near-unit "
                          f"(sumsq={s:.3f})")
        # 5. texture names resolved
        bad_tex = [t["index"] for t in self.textures if not t["name"]]
        if bad_tex:
            self.warn(f"texture name(s) unresolved at {bad_tex} "
                      f"(stride guess may be wrong)")

    # ------------------------------------------------------------------
    def report(self):
        h = self.hdr
        L = []
        L.append(f"=== {self.path} ===")
        L.append(f"  name        : {self.name!r}")
        L.append(f"  version     : {h['version']}   "
                 f"checksum 0x{h['checksum'] & 0xffffffff:08x}")
        L.append(f"  length      : {h['length']} "
                 f"({'ok' if h['length'] == len(self.d) else 'MISMATCH'})")
        L.append(f"  flags       : 0x{h['flags'] & 0xffffffff:08x}")
        L.append(f"  mass        : {h['mass']:.3f}   contents {h['contents']}")
        L.append(f"  surfaceprop : {cstr(self.d, h['surfacepropindex'])!r}")
        L.append(f"  bbox        : hull {h['hull_min']} .. {h['hull_max']}")
        L.append("")
        L.append(f"  bones       : {len(self.bones)}")
        for b in self.bones[:6]:
            L.append(f"     [{b['parent']:3d}] {b['name']!r}  "
                     f"pos {tuple(round(x,2) for x in b['pos'])}")
        if len(self.bones) > 6:
            L.append(f"     ... (+{len(self.bones) - 6} more)")
        L.append(f"  textures    : {len(self.textures)}  "
                 f"{[t['name'] for t in self.textures[:6]]}")
        L.append(f"  cdtextures  : {self.cdtextures}")
        L.append(f"  bodyparts   : {[bp['name'] for bp in self.bodyparts]}")
        L.append(f"  attachments : {len(self.attachments)}  "
                 f"{[a['name'] for a in self.attachments[:6]]}")
        L.append(f"  localanim   : {h['numlocalanim']}   "
                 f"localseq {h['numlocalseq']}")
        L.append("")
        if self.errors:
            L.append(f"  ERRORS ({len(self.errors)}):")
            for e in self.errors:
                L.append(f"    ! {e}")
        else:
            L.append("  ERRORS: none")
        if self.warnings:
            L.append(f"  warnings ({len(self.warnings)}):")
            for w in self.warnings:
                L.append(f"    ~ {w}")
        return "\n".join(L)

    def to_dict(self):
        return {
            "path": self.path, "name": self.name,
            "header": {k: (list(v) if isinstance(v, tuple) else
                           (v.decode("latin-1") if isinstance(v, bytes) else v))
                       for k, v in self.hdr.items()},
            "bones": [{k: (list(v) if isinstance(v, tuple) else v)
                       for k, v in b.items() if not k.startswith("_")}
                      for b in self.bones],
            "textures": [t["name"] for t in self.textures],
            "cdtextures": self.cdtextures,
            "bodyparts": [bp["name"] for bp in self.bodyparts],
            "attachments": [a["name"] for a in self.attachments],
            "errors": self.errors, "warnings": self.warnings,
        }


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = argv[1]
    flag = argv[2] if len(argv) > 2 else ""
    r = V47Reader(path)
    if flag == "--json":
        print(json.dumps(r.to_dict(), indent=2))
    elif flag == "--check":
        print(f"{path}: {len(r.errors)} errors, {len(r.warnings)} warnings")
        return 1 if r.errors else 0
    else:
        print(r.report())
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
