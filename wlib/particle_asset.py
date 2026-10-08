#!/usr/bin/env python3
"""particle_asset -- the engine's `.particle` grammar (kapow-particle/2).

A `.particle` asset is one ParticleSystemAsset followed by its ParticleTypes;
every type carries three module lists.  Loader: ParticleSystemAsset::vfunc_24
0x55d3ed (writer: vfunc_23 0x558a29); object reader FUN_00511f96 / FUN_00511eb5;
record application FUN_00510e5f; record writer FUN_005015d7.

    file    = object(ParticleSystemAsset)
              u32 nTypes
              nTypes x { object(ParticleType)
                         u32 nAffectors     nAffectors    x object   (type+0x60)
                         u32 nSpawners      nSpawners     x object   (type+0x48)
                         u32 nInitializers  nInitializers x object   (type+0x54) }
    object  = u32 nameLen, nameLen bytes "ClassName\\0"     (FUN_00437469)
              u32 payloadDwords, payloadDwords x 4 bytes of records
    record  = u32 objectId, u32 nameHash, u32 typeHash, u32 k, k dwords of value
    value   = number 1 float | integer 1 int32 | truth 1 dword (0/1) |
              vector 3 floats | quaternion 4 floats (x y z w) | color 1 dword |
              string: u32 words, words x 4 chars, NUL padded (k = 1 + words);
                      a null string is the single dword 0 (JSON null)

All integers and floats are in the platform byte order (little-endian on PC,
big-endian on X360/PS3: the writer byte-swaps every dword of a record but not
the characters of a string, FUN_005015d7 / StringType::vfunc_07 0x4ebaa2).
`objectId` is the saved entity's session id (entity+0x28); the engine applies
records only while it stays the same (FUN_00510e5f).  `nameHash` / `typeHash`
are kapow_props.name_hash of the property and data type names.  A record is
applied when the class registers a property with that hash AND the stored type
hash is that property's type; anything else is skipped by its length `k`.

Two record layouts exist.  "typed" above is what the Part 2 executable reads and writes
(Part 2 on PC / X360 / PS3 and Part 1 on PS3).  The Part 1 PC and X360 archives come from
an older build whose records carry no type hash:

    record  = u32 objectId, u32 nameHash, u32 k, k dwords of value        ("untyped")

That layout is read from the data (260 files parse to the last byte with the Part 2
class tables and no unknown property), not from the executable; the value type is then
the registered type of the property.

The class and property tables below are the executable's own registrations
(RegisterMembers functions, addresses in CLASSES[...]["register"]); defaults are
the constructors' values.  Dropdown items come from the registration strings.

    parse(data, order=None) -> dict      typed tree (see docs/PARTICLE_FORMAT.md)
    build(tree, order=None) -> bytes     the inverse (byte-exact on parse output)
    to_json(data, order=None) -> dict    parse(), for kapow_json / the extractor
"""

import json
import math
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

import kapow_props  # noqa: E402

FORMAT = "kapow-particle/2"

EVIDENCE = (
    "read: grammar from the loader 0x55d3ed / 0x511f96 / 0x510e5f and the writer 0x558a29 / "
    "0x5015d7; class, property, type and enum names from the executable's registrations "
    "(every name reproduces its stored hash); defaults from the class constructors"
)


EVIDENCE_UNTYPED = (
    "tree grammar, class / property / enum names and defaults as read from the Part 2 "
    "executable; the untyped record layout [id][nameHash][k][k dwords] of this older build "
    "is read from the data (value types are the registered ones), not from an executable"
)


class ParticleError(ValueError):
    """The bytes are not a complete `.particle` asset (truncated or malformed)."""


# --- data types (DataType ctors 0x4fa348.. in FUN_00501f6a: id, name, dwords) -------------
TYPE_DWORDS = {
    "number": 1,
    "integer": 1,
    "truth": 1,
    "vector": 3,
    "quaternion": 4,
    "color": 1,
    "string": None,  # 1 + word count
}
TYPE_BY_HASH = {kapow_props.name_hash(t): t for t in TYPE_DWORDS}
TYPE_HASH = {t: h for h, t in TYPE_BY_HASH.items()}

# --- enums: dropdown items of the registration strings ------------------------------------
D3DBLEND = {
    1: "zero",
    2: "one",
    3: "srcColor",
    4: "invSrcColor",
    5: "srcAlpha",
    6: "invSrcAlpha",
    7: "dstAlpha",
    8: "invDestAlpha",
    9: "dstColor",
    10: "invDstColor",
    11: "srcAlphaSat",
}
ENUMS = {
    "simulationMode": {0: "World space", 1: "Local space", 2: "Local Instanced"},
    "blendMode": {0: "Normal", 1: "Additive", 2: "Subtract", 3: "Multiply", 4: "Custom"},
    "srcBlend": D3DBLEND,
    "dstBlend": D3DBLEND,
    "blendOp": {1: "add", 2: "subtract", 3: "revSubtract", 4: "max", 5: "min"},
    "renderStyle": {0: "Billboard", 1: "Model", 2: "Refraction"},
    "alignment": {
        0: "None",
        1: "Camera",
        2: "Velocity",
        3: "Camera (Stretch last)",
        4: "Camera (Stretch first)",
    },
    "animationMode": {0: "Forward", 1: "reverse"},
    # EventSpawner lists all four, EventGeneratorAffector only the CUSTOM pair
    "eventChannel": {4: "COLLISION", 5: "DIE", 9: "CUSTOM_1", 10: "CUSTOM_2"},
}
# Enum_RegisterValue("COLLISION_TYPES", "COLLISION_TYPE___<name>", bit) in 0x8bbc25
COLLISION_TYPES = {
    0x1: "RAGDOLL",
    0x2: "CHARACTER_PHYSICS",
    0x4: "CAMERA",
    0x8: "CLOTH",
    0x10: "TRIGGER",
    0x20: "SOLID",
    0x40: "BLOCKER_RORSCHACH",
    0x80: "BLOCKER_NITEOWL",
    0x100: "BLOCKER_ENEMY",
    0x200: "MOVEMENT_STOPPER",
    0x400: "RAGDOLL_ALLY",
    0x800: "BLOCKER_UNDERBOSS",
    0x1000: "WATER",
    0x2000: "KYNAPSE",
    0x4000: "WAYPOINT",
    0x8000: "PARTICLES",
}
FLAGS = {"collisionMask": COLLISION_TYPES}
# properties whose string is a gradient "t,r,g,b,a|..." (FUN_00413360)
GRADIENTS = ("colorSequence", "sizeOverTime", "selfIllumination", "bloomSequence")
# properties whose string names another asset
REFERENCES = {"texture": "texture", "model": "model"}

_NOT_SET = "not-set-by-constructor"


def _p(name, typ, default, stored=True):
    return (name, typ, default, stored)


# Entity::RegisterMembers 0x511603 (ctor FUN_0050da83).  Only these five reach a file; the
# others (fragmentID, id, typeName, script, refCount, autoName) are never stored in the
# 656 files of the seven extracts.
_ENTITY = [
    _p("name", "string", ""),
    _p("useRealtime", "truth", False),
    _p("recordInSavepoints", "truth", True),
    _p("runScript", "truth", True),
    _p("open", "truth", False),
]

_V0 = [0.0, 0.0, 0.0]
_Q1 = [0.0, 0.0, 0.0, 1.0]

#: class name -> {"role", "base", "register" (RegisterMembers VA), "ctor", "props"}.
#: props: (name, data type, constructor default, stored in files).  `role` is the list a
#: class belongs to by its registered base class (ParticleAffector / ParticleSpawner /
#: ParticleInitializer, FUN_00565242 / 0x5652d4 / 0x56528b; all three derive from
#: ParticleModule 0x5605b8, which derives from Entity).
CLASSES = {
    "ParticleSystemAsset": {
        "role": "system",
        "base": "Asset",
        "register": "0x55da60",
        "ctor": "0x559fed",
        "entity": False,
        "props": [
            _p("duration", "number", 1.0),
            _p("loop", "truth", True),
            _p("enableUpdateEvents", "truth", False),
            _p("enableDieEvents", "truth", False),
            _p("enableSpawnEvents", "truth", False),
            _p("alwaysUpdate", "truth", False),
            _p("evolveFramesOnStart", "integer", 0),
            _p("cullingRadius", "number", 1.0),
            _p("cullingDistance", "number", 60.0),
            _p("renderInstanced", "truth", False),
            _p("numVariations", "integer", 1),
        ],
    },
    "ParticleType": {
        "role": "type",
        "base": "Entity",
        "register": "0x55c1d2",
        "ctor": "0x55b2bb",
        "props": [
            _p("simulationMode", "integer", 0),
            _p("maxParticles", "integer", 50),
            _p("particleSpeed", "number", 0.0),
            _p("particleLife", "number", 1.0),
            _p("particleSize", "number", 1.0),
            _p("blendMode", "integer", 0),
            _p("srcBlend", "integer", 2),
            _p("dstBlend", "integer", 2),
            _p("blendOp", "integer", 1),
            _p("particleDepth", "number", 0.0),
            _p("texture", "string", None),  # null string: no resource (getter 0x556985)
            _p("model", "string", None),
            _p("renderStyle", "integer", 0),
            _p("alignment", "integer", 1),
            _p("stretchFactor", "number", 0.0),
            _p("startTime", "number", 0.0),
            _p("endTime", "number", 1.0),
            _p("localPosition", "vector", _V0),
            _p("localOrientation", "quaternion", _Q1),
            _p("particleOrientation", "quaternion", _Q1),
            _p("immortalParticles", "truth", False),
            _p("localMode", "truth", False, False),  # deprecated alias: true -> simulationMode 1
            _p("uScale", "number", 1.0),
            _p("vScale", "number", 1.0),
            _p("alphaFalloffEnabled", "truth", False),
            _p("alphaFalloffStart", "number", 0.0),
            _p("alphaFalloffEnd", "number", 20.0),
            _p("useOcclusion", "truth", False),
            _p("occlusionAttenuationLow", "number", 0.9),
            _p("occlusionAttenuationHigh", "number", 1.0),
            _p("occlusionId", "integer", 1),
        ],
    },
    # ---- spawners (base ParticleSpawner) ----
    "RegularSpawner": {
        "role": "spawner",
        "register": "0x564b2d",
        "ctor": "0x564319",
        "props": [_p("particlesPerSec", "number", 10.0)],
    },
    "IrregularSpawner": {
        "role": "spawner",
        "register": "0x55b6ea",
        "ctor": "0x55a945",
        "props": [_p("particlesPerSec", "number", 10.0), _p("variance", "number", 0.0)],
    },
    "BurstSpawner": {
        "role": "spawner",
        "register": "0x554166",
        "ctor": "0x552ca5",
        "props": [
            _p("minBurstAmount", "integer", 10),
            _p("maxBurstAmount", "integer", 10),
            _p("minBurstInterval", "number", 1.0),
            _p("maxBurstInterval", "number", 1.0),
        ],
    },
    "EmitterTrailSpawner": {
        "role": "spawner",
        "register": "0x54fd2e",
        "ctor": "0x54901a",
        "props": [_p("stretchAdjust", "number", 1.0)],
    },
    "EventSpawner": {
        "role": "spawner",
        "register": "0x557b50",
        "ctor": "0x555d62",
        "props": [
            _p("eventChannel", "integer", 4),
            _p("particleTypeNr", "integer", 0),
            _p("minBurstAmount", "integer", 10),
            _p("maxBurstAmount", "integer", 10),
            _p("inheritedVelocity", "number", 0.0),
        ],
    },
    "SurfaceSpawner": {
        "role": "spawner",
        "register": "0x55384e",
        "ctor": "0x552a85",
        "props": [
            _p("particleAmount", "number", 0.1),
            _p("radius", "number", 100.0),
            _p("speed", "number", 0.0),
            _p("lifeVariance", "number", 0.0),
            _p("faceCullLimit", "number", 0.0),
            _p("spawnOnCharacters", "truth", False),
            _p("spawnOnGeometry", "truth", True),
            _p("materialId", "integer", -1),
        ],
    },
    "TerrainSurfaceSpawner": {
        "role": "spawner",
        "register": "0x553e77",
        "ctor": "0x552b43",
        "props": [
            _p("particleAmount", "number", 10.0),
            _p("radius", "number", 10.0),
            _p("speed", "number", 0.0),
            _p("lifeVariance", "number", 0.0),
            _p("spawnOffset", "number", 0.0),
        ],
    },
    # ---- initializers (base ParticleInitializer) ----
    "VarianceInitializer": {
        "role": "initializer",
        "register": "0x5501a8",
        "ctor": "0x5495ce",
        "props": [
            _p("position", "vector", _V0),
            _p("orientation", "vector", _V0),
            _p("rotation", "vector", _V0),
            _p("sizeVariance", "number", 0.0),
            _p("alpha", "number", 0.0),
            _p("life", "number", 0.0),
            _p("speed", "number", 0.0),
            _p("spread", "number", 0.0),
            _p("useLocalOrientation", "truth", False),
        ],
    },
    "ColorRangeInitializer": {
        "role": "initializer",
        "register": "0x5519f0",
        "ctor": "0x54d28e",
        "props": [_p("colorSequence", "string", "")],
    },
    "UVArrayInitializer": {
        "role": "initializer",
        "register": "0x5576aa",
        "ctor": "0x5559a9",
        "props": [_p("numX", "integer", 1), _p("numY", "integer", 1)],
    },
    "PositionInitializer": {
        "role": "initializer",
        "register": "0x5571d5",  # no properties; body vfunc_15 0x5553d0
        "ctor": None,
        "props": [],
    },
    # ---- affectors (base ParticleAffector) ----
    "LinearForceAffector": {
        "role": "affector",
        "register": "0x55793f",
        "ctor": "0x555b32",
        "props": [_p("force", "vector", _V0)],
    },
    "DampeningAffector": {
        "role": "affector",
        "register": "0x557a99",
        "ctor": "0x555c2f",
        "props": [_p("damp", "number", 0.0)],
    },
    "GrowthAffector": {
        "role": "affector",
        "register": "0x564c7a",
        "ctor": "0x56433e",
        "props": [_p("growth", "number", 0.0)],
    },
    "RotateAffector": {
        "role": "affector",
        "register": "0x5577c4",
        "ctor": "0x555a8d",
        "props": [
            _p("rotationx", "number", 0.0),
            _p("rotationy", "number", 0.0),
            _p("rotationz", "number", 0.0),
        ],
    },
    "TraceAffector": {
        "role": "affector",
        "register": "0x564dc7",
        "ctor": "0x56435b",
        "props": [_p("stretchRatio", "number", 1.0)],
    },
    "SizeSequenceAffector": {
        "role": "affector",
        "register": "0x564f30",
        "ctor": "0x564378",
        "props": [_p("sizeOverTime", "string", ""), _p("factor", "number", 1.0)],
    },
    "OpacitySequenceAffector": {
        "role": "affector",
        "register": "0x5585ae",
        "ctor": "0x5579f6",
        "props": [_p("colorSequence", "string", "")],
    },
    "ColorSequenceAffector": {
        "role": "affector",
        "register": "0x551939",
        "ctor": "0x54ffc1",
        "props": [_p("colorSequence", "string", "")],
    },
    "IlluminationAffector": {
        "role": "affector",
        "register": "0x56504a",
        "ctor": "0x5643e0",
        "props": [
            _p("ambient", "truth", True),
            _p("selfIllumination", "string", ""),
            _p("bloomFactor", "number", 1.0),
            _p("bloomSequence", "string", ""),
        ],
    },
    "UVArrayAffector": {
        "role": "affector",
        "register": "0x565445",
        "ctor": "0x5644bc",
        "props": [
            _p("frameRate", "number", 10.0),
            _p("numX", "integer", 1),
            _p("numY", "integer", 1),
            _p("animationMode", "integer", 0),
            _p("randomize", "truth", _NOT_SET),
        ],
    },
    "GeometryCollisionAffector": {
        "role": "affector",
        "register": "0x54f8a8",
        "ctor": "0x548c7d",
        "props": [
            _p("radius", "number", 0.1),
            _p("elasticity", "number", 0.8),
            _p("friction", "number", 0.0),
            _p("collisionMask", "integer", 0),
            _p("alignToCollisionNormal", "truth", False),
            _p("safetyRadius", "number", 0.5),
            _p("dieOnImpact", "truth", False),
        ],
    },
    "PlaneCollisionAffector": {
        "role": "affector",
        "register": "0x55aa4f",
        "ctor": "0x55943b",
        "props": [
            _p("radius", "number", 0.5),
            _p("elasticity", "number", 0.8),
            _p("nodeRef", "string", ""),
        ],
    },
    "TerrainCollisionAffector": {
        "role": "affector",
        "register": "0x55b96a",
        "ctor": "0x55abca",
        "props": [
            _p("radius", "number", 0.5),
            _p("elasticity", "number", 0.8),
            _p("nodeRef", "string", ""),
        ],
    },
    "EventGeneratorAffector": {
        "role": "affector",
        "register": "0x54fde5",
        "ctor": "0x54948f",
        "props": [
            _p("eventChannel", "integer", 9),
            _p("interval", "number", _NOT_SET),
            _p("startTime", "number", 0.0),
            _p("endTime", "number", 1.0),
        ],
    },
    # registered under the name "ProximityNoise" with base ParticleAffector (0x5544d8)
    "ProximityNoise": {
        "role": "affector",
        "register": "0x5544d8",
        "ctor": "0x552d20",
        "props": [
            _p("spawnDistance", "number", 10.0),
            _p("fadeDistance", "number", 5.0),
            _p("particleDensity", "number", 500.0),  # stored /1000 at +0x54 (0x54d5f4)
            _p("jitter", "number", 0.0),
            _p("scroll", "vector", _V0),
            _p("followCamera", "truth", False),
            _p("useTerrainLayer", "truth", True),
            _p("spawnHeight", "number", 2.0),
            _p("terrainOffset", "number", 0.0),
        ],
    },
}

_BASE_OF_ROLE = {
    "affector": "ParticleAffector",
    "spawner": "ParticleSpawner",
    "initializer": "ParticleInitializer",
}
#: the three lists of a ParticleType in file order (loader 0x55d3ed, writer 0x558a29)
LISTS = (("affectors", "affector"), ("spawners", "spawner"), ("initializers", "initializer"))

_SCHEMA = {}


def class_props(cls):
    """{name hash: (name, type, default, stored)} of class `cls` incl. the Entity
    properties, or None for a class the executable does not register."""
    if cls not in CLASSES:
        return None
    if cls not in _SCHEMA:
        c = CLASSES[cls]
        props = ([] if c.get("entity") is False else list(_ENTITY)) + list(c["props"])
        _SCHEMA[cls] = {kapow_props.name_hash(p[0]): p for p in props}
    return _SCHEMA[cls]


def class_base(cls):
    """Registered base class name of `cls` (None when unknown)."""
    c = CLASSES.get(cls)
    if c is None:
        return None
    return c.get("base") or _BASE_OF_ROLE.get(c["role"])


# --- values -------------------------------------------------------------------------------
def _f32(raw, bo):
    """One stored float as the shortest decimal that packs back to the same 4 bytes."""
    x = struct.unpack(bo + "f", raw)[0]
    if not math.isfinite(x):
        return None
    for digits in (6, 7, 8, 9):
        y = float("%.*g" % (digits, x))
        if struct.pack(bo + "f", y) == raw:
            return y
    return x


def _pack_f32(x, bo):
    try:
        return struct.pack(bo + "f", x)
    except (struct.error, OverflowError, TypeError):
        return None


def parse_gradient(text):
    """A gradient string -> [[t, r, g, b, a], ...] exactly as FUN_00413360 reads it: keys
    split at '|', fields at ',' (atof); t is kept in milliseconds as an integer (t * 1000
    truncated), so it is returned as ms / 1000.  A key needs five fields; shorter pieces
    (the trailing '' after the last '|') are not keys."""
    keys = []
    for piece in text.split("|"):
        f = piece.split(",")
        if len(f) < 5:
            continue
        try:
            v = [float(x) for x in f[:5]]
        except ValueError:
            continue
        keys.append([int(v[0] * 1000.0) / 1000.0] + v[1:])
    return keys


def gradient_at(keys, t, default=(1.0, 1.0, 1.0, 1.0)):
    """[r, g, b, a] of a parsed gradient at normalised time t: linear between the two
    neighbouring keys (FUN_00411783); no keys -> the engine's white (0x9e814c)."""
    if not keys:
        return list(default)
    ks = sorted(keys, key=lambda k: k[0])
    if t <= ks[0][0]:
        return list(ks[0][1:])
    for a, b in zip(ks, ks[1:]):
        if t <= b[0]:
            u = 0.0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
            return [a[i] + u * (b[i] - a[i]) for i in range(1, 5)]
    return list(ks[-1][1:])


def _encode_string(text, bo):
    """StringType::vfunc_13 0x4ebac7: words = (len + 4) >> 2, NUL padded ("" is one zero
    word; a null string pointer is the single word 0 and is None here)."""
    if text is None:
        return struct.pack(bo + "I", 0)
    raw = text.encode("latin1")
    words = (len(raw) + 4) >> 2
    return struct.pack(bo + "I", words) + raw.ljust(4 * words, b"\0")


def _decode_value(typ, payload, bo):
    """(value, canonical) of one record payload; canonical is False when re-encoding the
    value would not give the same bytes (the record then keeps its raw payload)."""
    k = len(payload) // 4
    if typ == "string":
        if k < 1:
            return None, False
        words = struct.unpack_from(bo + "I", payload, 0)[0]
        if k == 1 and words == 0:
            return None, True
        body = payload[4:]
        text = body.split(b"\0")[0].decode("latin1")
        return text, _encode_string(text, bo) == payload and words == k - 1
    n = TYPE_DWORDS.get(typ)
    if n is None or k != n:
        return None, False
    if typ == "number":
        v = _f32(payload, bo)
        return v, v is not None
    if typ in ("vector", "quaternion"):
        v = [_f32(payload[4 * i : 4 * i + 4], bo) for i in range(n)]
        return v, None not in v
    if typ == "integer":
        return struct.unpack(bo + "i", payload)[0], True
    if typ == "truth":
        u = struct.unpack(bo + "I", payload)[0]
        return (bool(u), True) if u in (0, 1) else (u, False)
    if typ == "color":
        return "%08x" % struct.unpack(bo + "I", payload)[0], True
    return None, False


def _encode_value(typ, value, bo):
    if typ == "string":
        return _encode_string(value, bo)
    if typ == "number":
        return _pack_f32(value, bo)
    if typ in ("vector", "quaternion"):
        if not isinstance(value, (list, tuple)) or len(value) != TYPE_DWORDS[typ]:
            return None
        parts = [_pack_f32(x, bo) for x in value]
        return None if None in parts else b"".join(parts)
    if typ == "integer":
        return struct.pack(bo + "i", value)
    if typ == "truth":
        return struct.pack(bo + "I", int(value))
    if typ == "color":
        return struct.pack(bo + "I", int(value, 16))
    return None


def _same(a, b):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, float) or isinstance(b, float):
        try:
            return struct.pack("<f", a) == struct.pack("<f", b)
        except (struct.error, OverflowError, TypeError):
            return False
    return a == b


# --- reader -------------------------------------------------------------------------------
class _Reader(object):
    def __init__(self, data, bo):
        self.b = data
        self.bo = bo
        self.p = 0

    def need(self, n, what):
        if n < 0 or self.p + n > len(self.b):
            raise ParticleError(
                "truncated .particle: %s needs %d byte(s) at offset %d, file has %d"
                % (what, n, self.p, len(self.b))
            )

    def u32(self, what):
        self.need(4, what)
        v = struct.unpack_from(self.bo + "I", self.b, self.p)[0]
        self.p += 4
        return v

    def take(self, n, what):
        self.need(n, what)
        v = self.b[self.p : self.p + n]
        self.p += n
        return v


def _read_object(r, role, stats, typed=True):
    at = r.p
    nlen = r.u32("class name length")
    if not 2 <= nlen <= 256:
        raise ParticleError("bad class name length %d at offset %d" % (nlen, at))
    raw = r.take(nlen, "class name")
    if raw[-1:] != b"\0" or not all(32 <= c < 127 for c in raw[:-1]):
        raise ParticleError("class name at offset %d is not a C string" % (at + 4))
    cls = raw[:-1].decode("latin1")
    ndw = r.u32("payload length of %s" % cls)
    end = r.p + 4 * ndw
    r.need(4 * ndw, "payload of %s" % cls)
    schema = class_props(cls)
    obj = {"class": cls}
    if schema is None:
        obj["unknown_class"] = True
        stats["unknown_classes"].append({"class": cls, "offset": at})
    else:
        base = class_base(cls)
        obj["base"] = base
        want = CLASSES[cls]["role"]
        if role != want:
            obj["warn"] = "a %s (%s) stored in the %s list" % (want, base, role)
    names = kapow_props.namedict() if schema is None else None
    props = []
    seen = set()
    oid = None
    while r.p < end:
        rec_at = r.p
        head = 16 if typed else 12
        if end - r.p < head:
            raise ParticleError("record header of %s cut at offset %d" % (cls, rec_at))
        if typed:
            rid, key, th, k = struct.unpack_from(r.bo + "4I", r.b, r.p)
        else:
            rid, key, k = struct.unpack_from(r.bo + "3I", r.b, r.p)
            th = None
        r.p += head
        if 4 * k > end - r.p:
            raise ParticleError(
                "record %08x of %s at offset %d runs past the object payload" % (key, cls, rec_at)
            )
        payload = r.take(4 * k, "record value")
        if oid is None:
            oid = rid
        known = schema.get(key) if schema is not None else None
        if typed:
            typ = TYPE_BY_HASH.get(th)
        else:  # no stored type: the registered one
            typ = known[1] if known is not None else None
        rec = {}
        if known is not None:
            rec["name"] = known[0]
        else:
            rec["name"] = None
            rec["hash"] = "%08x" % key
            if names is not None and names.get(key):
                rec["name_guess"] = names[key]
        rec["type"] = typ or (None if th is None else "%08x" % th)
        value, canonical = _decode_value(typ, payload, r.bo) if typ else (None, False)
        rec["value"] = value
        if not canonical:
            rec["raw"] = payload.hex()
        if rid != oid:
            # FUN_00510e5f stops applying at the first record with another id
            rec["id"] = "%08x" % rid
            rec["ignored"] = "id-change"
            stats["ignored"] += 1
        elif known is None:
            if schema is not None:
                rec["unknown"] = True
                stats["unknown_properties"].append(
                    {"class": cls, "hash": "%08x" % key, "type": rec["type"], "offset": rec_at}
                )
        elif typ != known[1]:
            rec["ignored"] = "type-mismatch (registered %s)" % known[1]
            stats["ignored"] += 1
        elif k != (TYPE_DWORDS[typ] or k) or (typ == "string" and k < 1):
            # 0x510e5f advances by the type's own size: such a record would desynchronise
            rec["ignored"] = "size-mismatch (%d dwords for a %s)" % (k, typ)
            stats["ignored"] += 1
        else:
            seen.add(key)
            name = known[0]
            if isinstance(value, int) and not isinstance(value, bool):
                if name in ENUMS:
                    rec["enum"] = ENUMS[name].get(value)
                elif name in FLAGS:
                    rec["flags"] = [n for bit, n in sorted(FLAGS[name].items()) if value & bit]
            if typ == "string" and name in GRADIENTS and isinstance(value, str):
                rec["keys"] = parse_gradient(value)
            if known[2] != _NOT_SET and _same(value, known[2]):
                rec["default"] = True
        props.append(rec)
    obj["id"] = "%08x" % (oid or 0)
    obj["props"] = props
    if schema is not None:
        absent = {}
        for h, (name, _typ, default, stored) in schema.items():
            if stored and h not in seen:
                absent[name] = None if default == _NOT_SET else default
        if absent:
            obj["absent"] = absent  # the constructor's values stay in force
    stats["objects"] += 1
    stats["classes"][cls] = stats["classes"].get(cls, 0) + 1
    return obj


def _count(r, what):
    n = r.u32(what)
    # every object is at least 4 + 2 + 4 bytes
    if n > (len(r.b) - r.p) // 10:
        raise ParticleError("%s %d at offset %d exceeds the file" % (what, n, r.p - 4))
    return n


def detect_order(data):
    """'<' or '>': the order in which the first dword is a plausible class-name length
    followed by that many bytes ending in NUL (the kapow_props convention)."""
    for bo in ("<", ">"):
        if len(data) >= 4:
            n = struct.unpack_from(bo + "I", data, 0)[0]
            if 2 <= n <= 256 and len(data) >= 4 + n and data[3 + n : 4 + n] == b"\0":
                return bo
    return "<"


def parse(data, order=None):
    """Parse a `.particle` asset.  Raises ParticleError when the bytes do not hold the
    complete tree.  Result (all of it JSON-serialisable):

      format, byte_order ('little' | 'big'), evidence
      record_layout 'typed' (the executable's) | 'untyped' (Part 1 PC / X360 build)
      system        object(ParticleSystemAsset)
      types         [object(ParticleType) + 'affectors' / 'spawners' / 'initializers']
      summary       object / class counts, unknown_classes, unknown_properties,
                    ignored_records, trailing_bytes
      trailing      hex of bytes after the tree (only when present; the loader ignores them)

    object = {class, base, id, props, [absent], [unknown_class], [warn]}
    props  = records in file order: {name, type, value} plus
               enum / flags     item name(s) of a dropdown / flag integer
               keys             [[t, r, g, b, a], ...] of a gradient string
               default: true    the value equals the constructor default
               hash, unknown    a record the class does not register (kept, never dropped)
               ignored          why the engine skips the record ('type-mismatch', 'id-change')
               raw              payload hex when the value does not re-encode to it
    absent = {name: default} of registered, normally stored properties without a record.
    """
    data = bytes(data)
    bo = order or detect_order(data)
    try:
        out = _parse(data, bo, True)
    except ParticleError as ex:
        try:
            out = _parse(data, bo, False)
        except ParticleError:
            raise ex
    else:
        s = out["summary"]
        if s["unknown_classes"] or s["unknown_properties"] or s["ignored_records"]:
            # a clean reading in the other layout wins (never seen in the game data)
            try:
                alt = _parse(data, bo, False)
            except ParticleError:
                alt = None
            if alt is not None:
                a = alt["summary"]
                if not (a["unknown_classes"] or a["unknown_properties"] or a["ignored_records"]):
                    out = alt
    return out


def _parse(data, bo, typed):
    r = _Reader(data, bo)
    stats = {
        "objects": 0,
        "classes": {},
        "unknown_classes": [],
        "unknown_properties": [],
        "ignored": 0,
    }
    system = _read_object(r, "system", stats, typed)
    types = []
    for _i in range(_count(r, "particle type count")):
        t = _read_object(r, "type", stats, typed)
        for key, role in LISTS:
            n = _count(r, key[:-1] + " count")
            t[key] = [_read_object(r, role, stats, typed) for _j in range(n)]
        types.append(t)
    out = {
        "format": FORMAT,
        "byte_order": "little" if bo == "<" else "big",
        "record_layout": "typed" if typed else "untyped",
        "evidence": EVIDENCE if typed else EVIDENCE_UNTYPED,
        "system": system,
        "types": types,
        "summary": {
            "types": len(types),
            "objects": stats["objects"],
            "classes": dict(sorted(stats["classes"].items())),
            "unknown_classes": stats["unknown_classes"],
            "unknown_properties": stats["unknown_properties"],
            "ignored_records": stats["ignored"],
            "trailing_bytes": len(data) - r.p,
        },
    }
    if r.p < len(data):
        out["trailing"] = data[r.p :].hex()
    return out


def to_json(data, order=None):
    """parse() under the name the other asset modules use."""
    return parse(data, order=order)


# --- writer -------------------------------------------------------------------------------
def _build_object(obj, bo, typed=True):
    cls = obj["class"]
    schema = class_props(cls) or {}
    by_name = {p[0]: (h, p) for h, p in schema.items()}
    oid = int(obj.get("id", "0"), 16)
    recs = []
    for rec in obj.get("props", []):
        name = rec.get("name")
        key = by_name[name][0] if name in by_name and "hash" not in rec else int(rec["hash"], 16)
        typ = rec["type"]
        th = TYPE_HASH.get(typ)
        if th is None and typed:
            th = int(typ, 16)
        if "raw" in rec:
            payload = bytes.fromhex(rec["raw"])
        else:
            payload = _encode_value(typ, rec["value"], bo)
            if payload is None:
                raise ParticleError("cannot encode %s.%s (%s)" % (cls, name, typ))
        rid = int(rec["id"], 16) if "id" in rec else oid
        if typed:
            head = struct.pack(bo + "4I", rid, key, th, len(payload) // 4)
        else:
            head = struct.pack(bo + "3I", rid, key, len(payload) // 4)
        recs.append(head + payload)
    body = b"".join(recs)
    name = cls.encode("latin1") + b"\0"
    return struct.pack(bo + "I", len(name)) + name + struct.pack(bo + "I", len(body) // 4) + body


def build(tree, order=None):
    """Serialise a parse() tree back to bytes (byte-exact for parse() output in the same
    byte order).  `raw` payloads are written verbatim, so a tree re-ordered to the other
    byte order is only correct when no record carries `raw`."""
    bo = order or ("<" if tree.get("byte_order", "little") == "little" else ">")
    typed = tree.get("record_layout", "typed") == "typed"
    out = [_build_object(tree["system"], bo, typed), struct.pack(bo + "I", len(tree["types"]))]
    for t in tree["types"]:
        out.append(_build_object(t, bo, typed))
        for key, _role in LISTS:
            out.append(struct.pack(bo + "I", len(t.get(key, []))))
            out.extend(_build_object(o, bo, typed) for o in t.get(key, []))
    if tree.get("trailing"):
        out.append(bytes.fromhex(tree["trailing"]))
    return b"".join(out)


# --- convenience ---------------------------------------------------------------------------
def values(obj, with_defaults=True):
    """{property name: value} of one object as the engine ends up with it: the applied
    records in file order over the constructor defaults of absent properties.  Two
    ParticleType setters are not plain stores: simulationMode keeps its value unless the
    new one is 0 or 1 (0x55733e), and the deprecated localMode = true sets simulationMode
    to 1 and stores nothing itself (0x557481; its getter 0x555da0 returns false)."""
    out = dict(obj.get("absent", {})) if with_defaults else {}
    is_type = obj.get("class") == "ParticleType"
    for rec in obj.get("props", []):
        name = rec.get("name")
        if not name or "ignored" in rec or "unknown" in rec:
            continue
        if is_type and name == "localMode":
            if rec["value"] is True:
                out["simulationMode"] = 1
            continue
        if is_type and name == "simulationMode" and rec["value"] not in (0, 1):
            continue
        out[name] = rec["value"]
    return out


def references(tree):
    """[(type index, type name, kind, path)] of the texture / model strings of a tree."""
    out = []
    for i, t in enumerate(tree["types"]):
        v = values(t)
        for prop, kind in sorted(REFERENCES.items()):
            if v.get(prop):
                out.append((i, v.get("name", ""), kind, v[prop]))
    return out


def schema_table():
    """The class / property tables as plain data (for documentation and tests)."""
    out = {}
    for cls in CLASSES:
        c = CLASSES[cls]
        out[cls] = {
            "role": c["role"],
            "base": class_base(cls),
            "register": c["register"],
            "ctor": c["ctor"],
            "props": [
                {
                    "name": n,
                    "hash": "%08x" % h,
                    "type": t,
                    "default": None if d == _NOT_SET else d,
                    "stored": s,
                }
                for h, (n, t, d, s) in class_props(cls).items()
            ],
        }
    return out


if __name__ == "__main__":
    with open(sys.argv[1], "rb") as _fh:
        _d = parse(_fh.read())
    _j = json.dumps(_d, indent=1)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_j)
    else:
        print(_j)
