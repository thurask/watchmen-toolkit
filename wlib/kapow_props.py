#!/usr/bin/env python3
# Universal Kapow "property bag" asset parser (.particle/.grass/.terrain/.detailmesh/
# .pb/.sequence/...). Format (integers in platform byte order: LE on PC, BE on
# X360/PS3 -- auto-detected, or pass parse(order='<'|'>')):
#   block: [u32 pre?]* [u32 namelen][ClassName\0][u32 schemaCount]
#   records (same ownerId dword anchors a block's records):
#     [u32 ownerId][u32 keyHash][u32 typeHash][u32 k][k dwords payload]
#     string payload: [u32 wordcount][wordcount*4 chars]  (k = 1+wordcount)
#   OLDER layout (standalone Part 1 on PC and Xbox 360; read from the data, not from
#   an executable): the same objects, records WITHOUT the type hash:
#     [u32 ownerId][u32 keyHash][u32 k][k dwords payload]
#   the value type is then the property's registered one (UNTYPED_TYPES).  A block's
#   third dword is the DWORD COUNT of its records, so both layouts are told apart
#   by which one walks to that end exactly (read_records).
#   keyHash/typeHash = name_hash(name): kapow bit-CRC32(poly 0x04C11DB7) over the name's
#   bytes each ANDed with 0xDF (engine FUN_00423ce8) -- NOT str.upper(): digits and
#   punctuation are folded too ('0'..'9' -> 0x10..0x19, '(' -> 0x08, ',' -> 0x0C).
import struct, json, pickle


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def kapow_hash(s):
    """Raw bit-CRC (poly 0x04C11DB7, init 0, bits fed LSB-first, no final xor) over
    the latin-1 bytes of ``s`` exactly as given -- NO folding.  This is the engine's
    length-counted hasher (FUN_00423ca1 / FUN_00423d7c).  To hash a NAME (property
    key, type name, command signature, asset name) use :func:`name_hash`."""
    crc = 0
    for byte in s.encode("latin1"):
        for bit in range(8):
            neg = crc & 0x80000000
            crc = ((crc << 1) & 0xFFFFFFFF) | ((byte >> bit) & 1)
            if neg:
                crc ^= 0x04C11DB7
    return crc


def name_fold(s):
    """The engine's name fold: every byte ANDed with 0xDF (``and cl,0xdf`` at
    0x423cf7 in FUN_00423ce8).  Equal to upper-casing for letters and '_' only."""
    return bytes(b & 0xDF for b in s.encode("latin1")).decode("latin1")


def name_hash(s):
    """Engine name hash (FUN_00423ce8): :func:`kapow_hash` of the 0xDF-folded name.
    FUN_00423d30 is the same hash stopped at the first ':' (``name:type`` strings);
    callers hashing such a string must cut it at the ':' themselves."""
    return kapow_hash(name_fold(s))


TYPES = {
    name_hash(t): t
    for t in (
        "number",
        "integer",
        "truth",
        "string",
        "vector",
        "color",
        "quaternion",
        "enum",
        "vectorlist",
        "list",
        # one 4-byte slot, default 0xFFFFFFFF (type object 0x500343, vtable 0xa24d4c);
        # registered for `localParticipant` only, and in no shipped file
        "netparticipant",
    )
}
_D = None


def native_message_signature(sig):
    """A native message's registration string as the engine normalises it before
    hashing (0x4f9504): argument NAMES are erased, types stay.

    1. p = the first '('; none -> unchanged.
    2. end = the ')' just before the last ':' when that colon directly follows a ')',
       else the last ')'; none -> unchanged.
    3. c = the first ':' at or after p.  While c < end: erase p+1 .. c inclusive, move
       p to the next ',' after p (stop without one), c = the next ':' at or after p.
    4. `end` is NOT adjusted after an erase.

    All-named and all-unnamed lists come out as expected; in a mixed list an unnamed
    argument in front of a named one is erased with it (one shipped case:
    GetNearbyAIAgents(number,agents:list(AIAgentInfo)) -> GetNearbyAIAgents(list(AIAgentInfo)))."""
    p = sig.find("(")
    if p < 0:
        return sig
    last = sig.rfind(":")
    if last > 0 and sig[last - 1] == ")":
        end = last - 1
    else:
        end = sig.rfind(")")
    if end < 0:
        return sig
    c = sig.find(":", p)
    while 0 <= c < end:
        sig = sig[: p + 1] + sig[c + 1 :]
        p = sig.find(",", p + 1)
        if p < 0:
            break
        c = sig.find(":", p)
    return sig


def native_message_hash(sig):
    """Hash a native message is registered under: the name hash of the normalised
    signature up to its first ':' (0x423d30; the first byte is hashed untested).  Not
    validated against a sender."""
    s = native_message_signature(sig)
    return name_hash(s[:1] + s[1:].split(":", 1)[0])


def namedict():
    global _D
    if _D is None:
        import os

        import sys

        cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prop_hash_dict.pkl")
        try:
            with open(cand, "rb") as _fh:
                _D = pickle.load(_fh)
            # names the dictionary lacks, from the executable's registrations
            # (VarianceInitializer.life, UVArray*.numX / numY, DampeningAffector.damp,
            # Entity.open); never overrides an existing entry
            for _nm in ("life", "numX", "numY", "damp", "open"):
                _D.setdefault(name_hash(_nm), _nm)
        except (OSError, pickle.UnpicklingError, EOFError, ValueError) as _ex:
            # NEVER fall back to a world-writable path: pickle.load executes code.
            print(
                "warning: %s unreadable (%s) -- property keys will render as hex hashes"
                % (cand, _ex),
                file=sys.stderr,
            )
            _D = {}
    return _D


_CLASS_NAMES = None


def class_prop_name(cls, key):
    """The spelling class `cls` registers for key hash `key` where it differs
    from the dictionary's (registered_names.json `class_overrides`: Sprite
    registers `is3D`, the sound assets `is3d`), else None."""
    global _CLASS_NAMES
    if _CLASS_NAMES is None:
        import json
        import os

        _CLASS_NAMES = {}
        try:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "registered_names.json"), encoding="utf-8") as fh:
                raw = json.load(fh).get("class_overrides", {})
            for c, tab in raw.items():
                for k, s in tab.items():
                    if name_hash(s) == int(k, 16):
                        _CLASS_NAMES[(c, int(k, 16))] = s
        except (OSError, ValueError):
            pass
    return _CLASS_NAMES.get((cls, key))


#: type hash of the 64-bit `uniqueID` record (not one of the TYPES names)
T_UNIQUE_ID = 0xEDEF427C

# Value type of every property the UNTYPED record layout stores without one.
# Source: the typed files of the same assets (PS3 Part 1 and PC Part 2: 3,771 / 2,916
# objects of these classes, every (class, property) pair with ONE stored type and no
# name with two types across classes).  "id" is the 64-bit uniqueID record.
_UNTYPED_SRC = {
    "id": "uniqueID",
    "string": "ambOccMapOverride animation depthFadeGradient depthFadeGradientAlpha "
    "diffuseMapOverride fallOffMapOverride glowMapOverride heightMapOverride model name "
    "normalMapOverride specSizeMapOverride specularMapOverride templateName texture",
    "truth": "castShadow compress constantAmbient enableAnimation enableNormalMapping "
    "enablePOM inheritDeferredLight isLit open receiveShadow recordInSavepoints "
    "resetUVOffset runScript storeLowestLODInHeader twoSided useConstantAmbient "
    "useRealtime useWaterDepthFade writeDepthBuffer",
    "integer": "alphaThreshold ambOccMapChannel animationDelayInMs blendOp blendType "
    "collisionMask density diffuseMapChannel dstBlend fallOffMapChannel glowMapChannel "
    "heightMapChannel lightModel m_iSpecificEffectPackage normalMapChannel "
    "numHeightSamples numLightSamples numUCells numVCells numVariations randSeed "
    "reflectionType renderOrder renderType shadowMeshType specSizeMapChannel "
    "specularMapChannel srcBlend texAmbOccScale texDiffuseScale texFalloffScale "
    "texGlowScale texHeightScale texNormalScale texSpecScale texSpecSizeScale "
    "waterNormalType",
    "number": "ambientHeight bloomPower characterSpeedFactor characterSwayFactor "
    "collisionPower cosMod depthFadeScale depthFogPower fadeFactor fallOffPower "
    "fresnelPower friction glassThickness height heightBias heightScale heightVariance "
    "highlightBumpScale lodDistance01 lodDistance12 lodDistance23 lodDistance34 "
    "lodDistance45 lodFactor lodFadeIn01 lodFadeIn12 lodFadeIn23 lodFadeIn34 lodFadeIn45 "
    "lodFadeOut01 lodFadeOut12 lodFadeOut23 lodFadeOut34 lodFadeOut45 "
    "lodNormalMapDistance lodNormalMapFadeOut lodPOMDistance lodPOMFadeOut lodRange "
    "materialColorAlpha maxReflection movePower normalMapPower opacity range "
    "reflectionBumpPower reflectionLightFactor refractionBumpPower restitution "
    "secondaryHighlightShift selfIlluminance shadowPower sinMod specularPower "
    "specularSize sphereInsertionDelay u2ScrollSpeed uScrollSpeed v2ScrollSpeed "
    "vScrollSpeed waterEffectFadeRange width widthVariance",
    "vector": "fallOffColor materialColor selfIlluminanceColor",
}
#: two keys the name dictionary lacks (MaterialSheet / TextureEffects script members)
_UNTYPED_HASHES = {0x6F275C5E: "integer", 0x2A1529E3: "integer"}
_UNTYPED = {}


def untyped_types():
    """{keyHash: type name} for records of the untyped layout ("id" = uniqueID)."""
    if not _UNTYPED:
        for typ, names in _UNTYPED_SRC.items():
            for nm in names.split():
                _UNTYPED[name_hash(nm)] = typ
        _UNTYPED.update(_UNTYPED_HASHES)
    return _UNTYPED


def type_hash(type_name):
    """Stored type hash of a type name ("id" -> T_UNIQUE_ID)."""
    return T_UNIQUE_ID if type_name == "id" else name_hash(type_name)


def read_records(b, p, end, bo="<", layout=None):
    """The property records in b[p:end] -> (layout, records) or None.

    layout  "typed"   [u32 owner][u32 key][u32 typeHash][u32 k][k dwords]
            "untyped" [u32 owner][u32 key][u32 k][k dwords]   (older Part 1 build)
    records [(owner, key, typeHash or None, payload offset, k)]

    Nothing is guessed: a layout is accepted only when its records all carry the
    first record's owner id and end exactly at `end` (and, typed, every type hash
    is above 0xFFFF); "typed" is tried first.
    None when `end` is out of range, the span is empty or neither layout fits
    (`layout` restricts the test to one)."""
    if not 0 <= p < end <= len(b):
        return None
    for lay in (layout,) if layout else ("typed", "untyped"):
        head = 16 if lay == "typed" else 12
        q, recs, owner = p, [], None
        while q + head <= end:
            if lay == "typed":
                o, key, th, k = struct.unpack_from(bo + "4I", b, q)
            else:
                o, key, k = struct.unpack_from(bo + "3I", b, q)
                th = None
            if owner is None:
                owner = o
            # a type hash is never a small number: an untyped record whose value is 0
            # (or a string) would otherwise also read as a typed one of "type" k
            if o != owner or 4 * k > end - q - head or (th is not None and th <= 0xFFFF):
                break
            recs.append((o, key, th, q + head, k))
            q += head + 4 * k
        if q == end and recs:
            return lay, recs
    return None


def find_objects(b, bo="<", classes=None):
    """Every `[u32 nameLen][ClassName\\0][u32 dwordCount][records]` object of a
    header whose records read exactly in one of the two layouts ->
    [{"class", "offset", "end", "layout", "records"}] in file order.  `classes`:
    an iterable of class names to keep (a script class "X(Base)" also matches
    "Base").  Used where the objects sit between other data (Texture headers)."""
    want = None if classes is None else set(classes)
    out, n, p = [], len(b), 0
    while p + 12 <= n:
        r = _rdname(b, p, bo)
        if r is None:
            p += 1
            continue
        cls, q = r
        base = cls[cls.index("(") + 1 : -1] if cls.endswith(")") and "(" in cls else cls
        if q + 4 > n or (want is not None and cls not in want and base not in want):
            p += 1
            continue
        ndw = struct.unpack_from(bo + "I", b, q)[0]
        got = read_records(b, q + 4, q + 4 + 4 * ndw, bo) if 0 < ndw <= (n - q - 4) // 4 else None
        if got is None:
            p += 1
            continue
        out.append(
            {"class": cls, "offset": p, "end": q + 4 + 4 * ndw, "layout": got[0], "records": got[1]}
        )
        p = q + 4 + 4 * ndw
    return out


def record_value(type_name, b, q, k, bo="<"):
    """Plain value of one record payload (k dwords at q) by type name: float,
    int, bool, str, [float] (vector / color / quaternion), int (64-bit "id");
    None when the type is unknown or the size does not fit it."""
    if type_name == "string":
        return None if k < 1 else b[q + 4 : q + 4 * k].split(b"\0", 1)[0].decode("latin1")
    if type_name == "number" and k == 1:
        return struct.unpack_from(bo + "f", b, q)[0]
    if type_name == "integer" and k == 1:
        return struct.unpack_from(bo + "i", b, q)[0]
    if type_name == "enum" and k == 1:
        return struct.unpack_from(bo + "i", b, q)[0]
    if type_name == "truth" and k == 1:
        return bool(struct.unpack_from(bo + "I", b, q)[0])
    if type_name == "id" and k == 2:
        hi, lo = struct.unpack_from(bo + "II", b, q)
        return (hi << 32) | lo
    if type_name in ("vector", "color", "quaternion") and k >= 1:
        return list(struct.unpack_from(bo + "%df" % k, b, q))
    return None


def pivot_book(b, order=None):
    """Sheets of a `.pb` pivot book in either record layout ->
    {"record_layout": "typed" | "untyped" | None, "sheets": [{name, uniqueID,
    friction, restitution, collisionMask, open, ...}]} (values by record_value;
    a record whose type is not known is kept as {"hex": ...} under its key).
    `uniqueID` is the 64-bit value with the FIRST stored dword low, the reading
    of skeleton_records.parse_pivot_book and the ragdoll sidecar's `unique_id`
    (0x43b830d445af888d for the Ragdoll sheet on every platform and in both
    layouts); texture sheets print theirs first dword high.  `book_id` (the u64 of the
    12-byte header in the file's byte order; Book +0x20, reader 0x528326) is given when
    the first object header is at byte 12."""
    bo = order or detect_order(b)
    names = namedict()
    sheets, layouts = [], set()
    for ob in find_objects(b, bo, ("PivotSheet",)):
        layouts.add(ob["layout"])
        sh = {}
        for _o, key, th, q, k in ob["records"]:
            if th is None:
                tn = untyped_types().get(key)
            else:
                tn = "id" if th == T_UNIQUE_ID else TYPES.get(th)
            v = record_value(tn, b, q, k, bo)
            if v is None:
                v = {"hex": b[q : q + 4 * k].hex()}
            elif tn == "id":
                # as skeleton_records / the ragdoll sidecar give it: first dword low
                v = ((v & 0xFFFFFFFF) << 32) | (v >> 32)
            sh.setdefault(names.get(key) or "%08x" % key, v)
        sheets.append(sh)
    lay = layouts.pop() if len(layouts) == 1 else ("mixed" if layouts else None)
    out = {"record_layout": lay, "sheets": sheets}
    if len(b) >= 12 and _rdname(b, 12, bo) is not None:
        out["book_id"] = "0x%016x" % struct.unpack_from(bo + "Q", b, 0)[0]
    return out


def _rdname(b, p, bo="<"):
    n = len(b)
    if p + 4 > n:
        return None
    nl = struct.unpack_from(bo + "I", b, p)[0]
    if 2 <= nl <= 64 and p + 4 + nl <= n:
        nm = b[p + 4 : p + 4 + nl]
        if nm.endswith(b"\0") and all(32 <= c < 127 for c in nm[:-1]):
            return nm[:-1].decode(), p + 4 + nl
    return None


def detect_order(b):
    """Pick byte order by finding the leading [u32 namelen][ClassName\\0] record
    (allowing up to 4 pre-dwords). Small namelen only parses in the right order."""
    for bo in ("<", ">"):
        for nskip in range(5):
            if _rdname(b, 4 * nskip, bo):
                return bo
    return "<"


def _value(tn, typ, b, q, k, bo):
    """JSON value of one record payload as parse() writes it (tn = type name or
    None, typ = the type hash shown for a raw value)."""
    if tn == "string":
        wc = struct.unpack_from(bo + "I", b, q)[0]
        return b[q + 4 : q + 4 + wc * 4].rstrip(b"\0").decode("latin1")
    if tn == "number":
        fs = [struct.unpack_from(bo + "f", b, q + 4 * j)[0] for j in range(k)]
        return fs[0] if k == 1 else fs
    if tn in ("integer", "truth", "enum"):
        iv = [struct.unpack_from(bo + "i", b, q + 4 * j)[0] for j in range(k)]
        return iv[0] if k == 1 else iv
    fs = [struct.unpack_from(bo + "f", b, q + 4 * j)[0] for j in range(k)]
    return {
        "raw_type": "%08x" % typ,
        "floats": [round(x, 6) if abs(x) < 1e9 else None for x in fs],
        "hex": b[q : q + 4 * k].hex(),
    }


def parse(b, keynames=None, order=None):
    by_class = keynames is None  # the shipped dictionary: per-class spellings apply
    if keynames is None:
        keynames = namedict()
    bo = order or detect_order(b)
    p = 0
    n = len(b)
    blocks = []
    pre = []
    trunc = 0  # records/blocks whose payload ran past the buffer (2026-08-17)
    wcmm = 0  # string records whose wordcount disagrees with the dword count k
    untyped_blocks = untyped_unknown = 0  # older record layout (no type hash)
    while p + 8 <= n:
        r = _rdname(b, p, bo)
        nskip = 0
        while r is None and nskip < 4 and p + 4 * (nskip + 1) + 8 <= n:
            nskip += 1
            r = _rdname(b, p + 4 * nskip, bo)
        if r is None:
            break
        if nskip:
            pre = list(struct.unpack_from(bo + "%dI" % nskip, b, p))
        cls, p = r
        if p + 4 > n:  # 2026-08-17: truncated before schemaCount -- stop cleanly
            trunc += 1
            break
        schema = struct.unpack_from(bo + "I", b, p)[0]
        p += 4
        recs = []
        owner = None
        # older Part 1 build: records without a type hash.  Taken only when the
        # typed layout does NOT end at the block's dword count and this one does.
        old = read_records(b, p, p + 4 * schema, bo) if 0 < schema <= (n - p) // 4 else None
        if old is not None and old[0] == "untyped":
            ut = untyped_types()
            for o, key, _th, q, k in old[1]:
                owner = o
                tn = ut.get(key)
                if tn is None:
                    untyped_unknown += 1
                    val = {"raw_type": None, "hex": b[q : q + 4 * k].hex()}
                else:
                    val = _value(tn, type_hash(tn), b, q, k, bo)
                    if tn == "string" and struct.unpack_from(bo + "I", b, q)[0] + 1 != k:
                        wcmm += 1
                recs.append(
                    {
                        "key": (by_class and class_prop_name(cls, key))
                        or keynames.get(key)
                        or "%08x" % key,
                        "type": ("%08x" % T_UNIQUE_ID if tn == "id" else tn) if tn else "unknown",
                        "value": val,
                    }
                )
            p += 4 * schema
            untyped_blocks += 1
            blocks.append(
                {
                    "class": cls,
                    "pre": pre,
                    "owner": "%08x" % (owner or 0),
                    "schema": schema,
                    "props": recs,
                    "record_layout": "untyped",
                }
            )
            pre = []
            continue
        while p + 16 <= n:
            o, key, typ, k = struct.unpack_from(bo + "4I", b, p)
            if owner is None:
                owner = o
            if o != owner:
                break
            tn = TYPES.get(typ)
            if tn is None and k > 1024:
                break
            q = p + 16
            # 2026-08-17: every payload is k dwords ([u32 k][k dwords]); these
            # buffers are carved heuristically, so a record running past the
            # end is routine -- stop the walk instead of letting struct.error
            # escape into the caller's whole extraction pass.
            if q + 4 * k > n or (tn == "string" and k < 1):
                trunc += 1
                break
            if tn == "string" and struct.unpack_from(bo + "I", b, q)[0] + 1 != k:
                wcmm += 1  # counted + reported via out['warn'] (was a no-op)
            val = _value(tn, typ, b, q, k, bo)
            p = q + 4 * k
            recs.append(
                {
                    "key": (by_class and class_prop_name(cls, key))
                    or keynames.get(key)
                    or "%08x" % key,
                    "type": tn or "%08x" % typ,
                    "value": val,
                }
            )
        blocks.append(
            {
                "class": cls,
                "pre": pre,
                "owner": "%08x" % (owner or 0),
                "schema": schema,
                "props": recs,
            }
        )
        pre = []
    out = {"blocks": blocks, "trailing_bytes": n - p}
    # one summary warning per parse, on the same channel decode_sequence uses
    # (surfaces in the emitted JSON; per-record stderr would spam bulk runs)
    warn = []
    if untyped_blocks:
        out["record_layout"] = "untyped"
        out["record_layout_note"] = (
            "records without a type hash ([owner][key][k][k dwords], the older standalone "
            "Part 1 build; layout read from the data): value types are the ones the typed "
            "files of the same assets store"
        )
    if untyped_unknown:
        warn.append(
            "untyped layout: %d record(s) of a property with no known value type, kept as "
            "raw hex (type 'unknown')" % untyped_unknown
        )
    if trunc:
        warn.append("truncated: %d record(s) ran past the buffer" % trunc)
    if wcmm:
        warn.append("string wordcount != k-1 on %d record(s)" % wcmm)
    if warn:
        out["warn"] = warn
    return out


if __name__ == "__main__":
    import sys

    b = _read_bytes(sys.argv[1])
    out = parse(b)
    j = json.dumps(out, indent=1)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as _f:
            _f.write(j)
    else:
        print(j[:5000])
