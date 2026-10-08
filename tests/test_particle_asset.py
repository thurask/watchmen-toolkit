"""particle_asset: the engine's `.particle` grammar (kapow-particle/2).

Synthetic files only, built here from the grammar (loader 0x55d3ed, object reader
0x511f96, record application 0x510e5f) independently of particle_asset.build.
"""

import json
import struct

import pytest

import kapow_json as kj
import kapow_props as kp
import particle_asset as pa

T = {t: kp.name_hash(t) for t in ("number", "integer", "truth", "string", "vector", "quaternion")}


def s_payload(text, bo):
    """string value: u32 words, words x 4 chars (chars are never byte-swapped)."""
    if text is None:
        return struct.pack(bo + "I", 0)
    raw = text.encode("latin1")
    words = len(raw) // 4 + 1
    return struct.pack(bo + "I", words) + raw.ljust(4 * words, b"\0")


def rec(oid, name, typ, payload, bo, key=None):
    key = kp.name_hash(name) if key is None else key
    return struct.pack(bo + "4I", oid, key, T.get(typ, 0x12345678), len(payload) // 4) + payload


def num(oid, name, x, bo):
    return rec(oid, name, "number", struct.pack(bo + "f", x), bo)


def integer(oid, name, x, bo):
    return rec(oid, name, "integer", struct.pack(bo + "i", x), bo)


def truth(oid, name, x, bo):
    return rec(oid, name, "truth", struct.pack(bo + "I", int(x)), bo)


def string(oid, name, text, bo):
    return rec(oid, name, "string", s_payload(text, bo), bo)


def obj(cls, records, bo):
    body = b"".join(records)
    name = cls.encode() + b"\0"
    return struct.pack(bo + "I", len(name)) + name + struct.pack(bo + "I", len(body) // 4) + body


def u32(n, bo):
    return struct.pack(bo + "I", n)


def entity(oid, name, bo):
    return [
        string(oid, "name", name, bo),
        truth(oid, "useRealtime", 0, bo),
        truth(oid, "recordInSavepoints", 1, bo),
        truth(oid, "runScript", 1, bo),
        truth(oid, "open", 0, bo),
    ]


GRADIENT = (
    "0.000000,1.000000,1.000000,1.000000,1.000000|1.000000,0.000000,0.000000,0.000000,1.000000|"
)


def sample(bo, extra_type_records=(), extra_tail=b""):
    """system + one type (1 affector, 2 spawners, 1 initializer) + one empty type."""
    system = obj(
        "ParticleSystemAsset",
        [num(1, "duration", 2.5, bo), truth(1, "loop", 0, bo), integer(1, "numVariations", 1, bo)],
        bo,
    )
    t0 = obj(
        "ParticleType",
        entity(2, "Sparks", bo)
        + [
            integer(2, "simulationMode", 1, bo),
            integer(2, "maxParticles", 64, bo),
            num(2, "particleLife", 0.35, bo),
            integer(2, "blendMode", 1, bo),
            integer(2, "alignment", 4, bo),
            string(2, "texture", "/Art/Effects/Spark01.bmp", bo),
            string(2, "model", None, bo),
            rec(2, "localPosition", "vector", struct.pack(bo + "3f", 0.0, 0.25, -1.5), bo),
            rec(2, "localOrientation", "quaternion", struct.pack(bo + "4f", 0, 0, 0, 1), bo),
        ]
        + list(extra_type_records),
        bo,
    )
    aff = obj(
        "OpacitySequenceAffector",
        entity(3, "", bo) + [string(3, "colorSequence", GRADIENT, bo)],
        bo,
    )
    sp0 = obj("RegularSpawner", entity(4, "", bo) + [num(4, "particlesPerSec", 30.0, bo)], bo)
    sp1 = obj(
        "BurstSpawner",
        entity(5, "", bo)
        + [integer(5, "minBurstAmount", 3, bo), integer(5, "maxBurstAmount", 7, bo)],
        bo,
    )
    ini = obj(
        "GeometryCollisionAffector",
        entity(6, "", bo) + [integer(6, "collisionMask", 0x8020, bo)],
        bo,
    )
    t1 = obj("ParticleType", entity(7, "Empty", bo), bo)
    return b"".join(
        [
            system,
            u32(2, bo),
            t0,
            u32(1, bo),
            aff,
            u32(2, bo),
            sp0,
            sp1,
            u32(1, bo),
            ini,
            t1,
            u32(0, bo),
            u32(0, bo),
            u32(0, bo),
            extra_tail,
        ]
    )


def by_name(o):
    return {r["name"]: r for r in o["props"] if r["name"]}


@pytest.mark.parametrize("bo", ["<", ">"])
def test_tree_both_byte_orders(bo):
    data = sample(bo)
    t = pa.parse(data)
    assert t["format"] == "kapow-particle/2"
    assert t["byte_order"] == ("little" if bo == "<" else "big")
    assert t["system"]["class"] == "ParticleSystemAsset" and t["system"]["id"] == "00000001"
    assert pa.values(t["system"])["duration"] == 2.5
    assert [x["class"] for x in t["types"]] == ["ParticleType", "ParticleType"]
    t0, t1 = t["types"]
    assert [o["class"] for o in t0["affectors"]] == ["OpacitySequenceAffector"]
    assert [o["class"] for o in t0["spawners"]] == ["RegularSpawner", "BurstSpawner"]
    assert [o["class"] for o in t0["initializers"]] == ["GeometryCollisionAffector"]
    assert t1["affectors"] == [] and t1["spawners"] == [] and t1["initializers"] == []
    p = by_name(t0)
    assert p["name"]["value"] == "Sparks"
    assert p["particleLife"]["value"] == 0.35  # shortest decimal of the stored float32
    assert p["texture"]["value"] == "/Art/Effects/Spark01.bmp"
    assert p["model"]["value"] is None and p["model"]["default"] is True  # null string
    assert p["localPosition"]["value"] == [0.0, 0.25, -1.5]
    assert p["localOrientation"]["value"] == [0.0, 0.0, 0.0, 1.0]
    s = t["summary"]
    assert s["types"] == 2 and s["objects"] == 7 and s["trailing_bytes"] == 0
    assert s["unknown_classes"] == [] and s["unknown_properties"] == []
    assert pa.build(t) == data  # byte-exact
    assert pa.build(json.loads(json.dumps(t))) == data  # ... through JSON too


def test_enums_flags_gradients_defaults():
    t = pa.parse(sample("<"))
    p = by_name(t["types"][0])
    assert p["simulationMode"]["enum"] == "Local space"
    assert p["blendMode"]["enum"] == "Additive"
    assert p["alignment"]["enum"] == "Camera (Stretch first)"
    assert "default" not in p["maxParticles"]  # 64, constructor says 50
    assert p["recordInSavepoints"]["default"] is True
    col = by_name(t["types"][0]["initializers"][0])["collisionMask"]
    assert col["flags"] == ["SOLID", "PARTICLES"]
    seq = by_name(t["types"][0]["affectors"][0])["colorSequence"]
    assert seq["keys"] == [[0.0, 1.0, 1.0, 1.0, 1.0], [1.0, 0.0, 0.0, 0.0, 1.0]]
    assert pa.gradient_at(seq["keys"], 0.25) == [0.75, 0.75, 0.75, 1.0]
    # the affector sits in the initializer list: reported, not rejected
    assert "warn" in t["types"][0]["initializers"][0]
    # properties without a record keep the constructor value
    absent = t["types"][1]["absent"]
    assert absent["maxParticles"] == 50 and absent["alphaFalloffEnd"] == 20.0
    assert "localMode" not in absent  # registered but never stored
    v = pa.values(t["types"][1])
    assert v["name"] == "Empty" and v["alignment"] == 1 and v["occlusionAttenuationLow"] == 0.9


@pytest.mark.parametrize("bo", ["<", ">"])
def test_unknown_and_ignored_records_are_kept(bo):
    extra = [
        rec(2, "?", "number", struct.pack(bo + "f", 4.5), bo, key=0xDEADBEEF),  # unknown name
        rec(2, "?", "?", b"\x01\x02\x03\x04\x05\x06\x07\x08", bo, key=0xCAFEF00D),  # unknown type
        integer(2, "particleSize", 3, bo),  # registered as number: the engine skips it
        num(9, "particleSpeed", 8.0, bo),  # another object id: the engine stops here
    ]
    data = sample(bo, extra_type_records=extra, extra_tail=b"\xaa\xbb")
    t = pa.parse(data)
    recs = t["types"][0]["props"][-4:]
    assert recs[0]["name"] is None and recs[0]["hash"] == "deadbeef"
    assert recs[0]["unknown"] is True and recs[0]["value"] == 4.5
    assert recs[1]["type"] == "12345678" and recs[1]["raw"] == "0102030405060708"
    assert recs[2]["name"] == "particleSize" and recs[2]["ignored"].startswith("type-mismatch")
    assert recs[3]["ignored"] == "id-change" and recs[3]["id"] == "00000009"
    s = t["summary"]
    assert [u["hash"] for u in s["unknown_properties"]] == ["deadbeef", "cafef00d"]
    assert s["ignored_records"] == 2 and s["trailing_bytes"] == 2 and t["trailing"] == "aabb"
    # skipped records do not reach the effective values
    v = pa.values(t["types"][0])
    assert v["particleSize"] == 1.0 and v["particleSpeed"] == 0.0
    assert pa.build(json.loads(json.dumps(t))) == data


def test_unknown_class_is_parsed_generically():
    bo = "<"
    data = obj("ParticleSystemAsset", [], bo) + u32(1, bo) + obj("ParticleType", [], bo)
    data += u32(1, bo) + obj("FutureAffector", [num(5, "duration", 1.5, bo)], bo) + u32(0, bo) * 2
    t = pa.parse(data)
    o = t["types"][0]["affectors"][0]
    assert o["unknown_class"] is True and o["props"][0]["value"] == 1.5
    assert o["props"][0]["hash"] == "%08x" % kp.name_hash("duration")
    assert t["summary"]["unknown_classes"][0]["class"] == "FutureAffector"
    assert pa.build(t) == data


@pytest.mark.parametrize("bo", ["<", ">"])
def test_truncated_input_fails_cleanly(bo):
    data = sample(bo)
    assert pa.parse(data)
    for cut in list(range(0, 40)) + list(range(40, len(data), 7)):
        with pytest.raises(pa.ParticleError):
            pa.parse(data[:cut], order=bo)
    with pytest.raises(pa.ParticleError):
        pa.parse(b"")
    with pytest.raises(pa.ParticleError):
        pa.parse(b"\xff" * 64)
    # a count larger than the file is refused before any allocation
    with pytest.raises(pa.ParticleError):
        pa.parse(obj("ParticleSystemAsset", [], bo) + u32(0x7FFFFFFF, bo))


def test_schema_names_reproduce_their_hashes():
    table = pa.schema_table()
    assert len(table) == 28
    for cls, c in table.items():
        hashes = [p["hash"] for p in c["props"]]
        assert len(set(hashes)) == len(hashes), cls
        for p in c["props"]:
            assert p["hash"] == "%08x" % kp.name_hash(p["name"])
            assert p["type"] in pa.TYPE_DWORDS
    # the five names the hash dictionary lacked resolve in the legacy reader too
    names = kp.namedict()
    for n in ("life", "numX", "numY", "damp", "open"):
        assert names[kp.name_hash(n)] == n
    assert pa.class_base("ProximityNoise") == "ParticleAffector"
    assert pa.class_base("ParticleSystemAsset") == "Asset"
    # the asset is not saved with the Entity properties, a type is
    assert "name" not in [p["name"] for p in table["ParticleSystemAsset"]["props"]]
    assert "open" in [p["name"] for p in table["ParticleType"]["props"]]


def test_extractor_json_uses_the_grammar_and_falls_back():
    data = sample(">")
    d = kj.to_json("art/effects/x.particle", data, order=">")
    assert d["format"] == "kapow-particle/2" and "blocks" not in d
    json.dumps(d)
    # other property bags keep the block walk
    assert "blocks" in kj.to_json("x.grass", data, order=">")
    # a broken file still yields the legacy block list, with the reason
    cut = kj.to_json("x.particle", data[:200], order=">")
    assert "blocks" in cut and any("not a complete .particle tree" in w for w in cut["warn"])
    # the legacy reader itself is unchanged
    old = kp.parse(sample("<"))
    assert [b["class"] for b in old["blocks"]][:2] == ["ParticleSystemAsset", "ParticleType"]


def test_gradient_and_references():
    assert pa.parse_gradient("") == []
    assert pa.parse_gradient("0.5,1,2,3|") == []  # a key needs five fields
    assert pa.parse_gradient("0.2506,1,0,0,1|") == [[0.25, 1.0, 0.0, 0.0, 1.0]]  # t in whole ms
    assert pa.gradient_at([], 0.5) == [1.0, 1.0, 1.0, 1.0]
    t = pa.parse(sample("<"))
    assert pa.references(t) == [(0, "Sparks", "texture", "/Art/Effects/Spark01.bmp")]


def untyped(data_typed_records):
    """Drop the type hash of every record: the Part 1 PC / X360 layout."""
    out = b""
    p = 0
    b = data_typed_records
    while p < len(b):
        bo = "<"
        rid, key, _th, k = struct.unpack_from(bo + "4I", b, p)
        out += struct.pack(bo + "3I", rid, key, k) + b[p + 16 : p + 16 + 4 * k]
        p += 16 + 4 * k
    return out


def test_untyped_part1_layout_and_local_mode():
    bo = "<"
    sys_recs = num(1, "duration", 3.0, bo) + truth(1, "loop", 1, bo)
    type_recs = b"".join(entity(2, "Old", bo)) + truth(2, "localMode", 1, bo)
    type_recs += string(2, "texture", "/Art/x.bmp", bo) + num(2, "particleLife", 2.0, bo)
    sp_recs = b"".join(entity(3, "", bo)) + num(3, "particlesPerSec", 12.5, bo)
    data = obj("ParticleSystemAsset", [untyped(sys_recs)], bo) + u32(1, bo)
    data += obj("ParticleType", [untyped(type_recs)], bo) + u32(0, bo) + u32(1, bo)
    data += obj("RegularSpawner", [untyped(sp_recs)], bo) + u32(0, bo)
    t = pa.parse(data)
    assert t["record_layout"] == "untyped" and "read from the data" in t["evidence"]
    assert t["summary"]["unknown_properties"] == [] and t["summary"]["trailing_bytes"] == 0
    ty = t["types"][0]
    assert by_name(ty)["texture"]["value"] == "/Art/x.bmp"
    assert by_name(ty["spawners"][0])["particlesPerSec"]["value"] == 12.5
    # the deprecated localMode = true is the setter of simulationMode = 1 (0x557481)
    assert ty["absent"]["simulationMode"] == 0
    assert pa.values(ty)["simulationMode"] == 1 and "localMode" not in pa.values(ty)
    assert pa.build(json.loads(json.dumps(t))) == data
    # the typed sample is never taken for the untyped layout
    assert pa.parse(sample("<"))["record_layout"] == "typed"


def test_simulation_mode_setter_rejects_other_values():
    bo = "<"
    data = obj("ParticleSystemAsset", [], bo) + u32(1, bo)
    data += obj("ParticleType", [integer(2, "simulationMode", 2, bo)], bo) + u32(0, bo) * 3
    t = pa.parse(data)
    rec = t["types"][0]["props"][0]
    assert rec["enum"] == "Local Instanced" and rec["value"] == 2
    assert "simulationMode" not in pa.values(t["types"][0], with_defaults=False)
    # a typed record whose size is not the type's is flagged and not applied
    bad = struct.pack("<4I", 2, kp.name_hash("particleLife"), T["number"], 2) + b"\0" * 8
    data = obj("ParticleSystemAsset", [], bo) + u32(1, bo) + obj("ParticleType", [bad], bo)
    data += u32(0, bo) * 3
    t = pa.parse(data)
    assert t["types"][0]["props"][0]["ignored"].startswith("size-mismatch")
    assert pa.values(t["types"][0])["particleLife"] == 1.0
    assert pa.build(t) == data
