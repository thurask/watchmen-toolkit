"""The ModelRes header of the stand-alone Part 1 build (PC, Xbox 360).

Its layout is the Part 2 one minus two things: the fifth flag byte of a submesh
record, and the type word of every property record.  All fixtures are built
here, in both layouts and both byte orders.
"""

import json
import struct

import numpy as np
import pytest

import kapow_props as kp
import parse_model_nodes as pmn
import ragdoll_rig as rr
import skeleton_records as sr
import variant_glb as vg
import watchmen_extract as we

TEXTURES = ["/art/t/Wall_01.bmp", "/art/t/Trim_02.bmp"]
_BODY_KEYS = (
    "name movementType numSolverIterations mass angularDamping linearDamping "
    "maxLinearVelocity maxAngularVelocity"
).split()
_DEFAULT = {
    "truth": 0,
    "integer": 0,
    "number": 0.5,
    "vector": (0.0, 0.0, 0.0),
    "quaternion": (0.0, 0.0, 0.0, 1.0),
}


def _types():
    out = {}
    for typ, names in sr._UNTYPED_SRC.items():
        for nm in names.split():
            out[nm] = typ
    return out


def _str(s, bo):
    b = s.encode("latin1") + b"\0"
    return struct.pack(bo + "I", len(b)) + b


def _payload(typ, value, bo):
    if typ == "string":
        raw = value.encode("latin1")
        words = (len(raw) + 4) >> 2
        return struct.pack(bo + "I", words) + raw.ljust(4 * words, b"\0")
    if typ == "number":
        return struct.pack(bo + "f", value)
    if typ in ("integer", "truth"):
        return struct.pack(bo + "i", int(value))
    return struct.pack(bo + "%df" % len(value), *value)


def _records(props, bo, typed, owner):
    """[(name, type, value)] -> property records, typed or untyped."""
    out = b""
    for name, typ, value in props:
        pl = _payload(typ, value, bo)
        out += struct.pack(bo + "II", owner, kp.name_hash(name))
        if typed:
            out += struct.pack(bo + "I", kp.type_hash(typ))
        out += struct.pack(bo + "I", len(pl) // 4) + pl
    return out


def _bag(bo, typed):
    props = [("storeLowestLODInHeader", "truth", 0), ("shadowMeshType", "integer", 2)]
    for pair, dist in (("01", 30.0), ("12", 60.0), ("23", 90.0), ("34", 120.0), ("45", 150.0)):
        props += [
            ("lodDistance" + pair, "number", dist),
            ("lodFadeIn" + pair, "number", 2.0),
            ("lodFadeOut" + pair, "number", 3.0),
        ]
    recs = _records(props, bo, typed, 0x20D4966D)
    return struct.pack(bo + "I", len(recs) // 4) + recs


def _vertex(x, y, z, u, v):
    """PC vertex format 5 (44 bytes): position, half3 normal (+pad), colour,
    half2 uv, half3 tangent (+pad), half3 bitangent (+pad)."""
    half = lambda *a: np.array(a, "<f2").tobytes()
    b = struct.pack("<3f", x, y, z) + half(0, 0, 1, 0) + bytes([30, 20, 10, 255])
    return b + half(u, v) + half(1, 0, 0, 0) + half(0, 1, 0, 0)


def _packed(x, y, z):
    """The console's packed vector: x 11 bits, y 11 bits, z 10 bits, LSB first."""
    q = lambda v, n, s: int(round(v * s)) & ((1 << n) - 1)
    return struct.pack(">I", q(x, 11, 1023) | q(y, 11, 1023) << 11 | q(z, 10, 511) << 22)


def _console_vertex(x, y, z, u, v, console):
    """Console vertex format 5 (32 bytes, big-endian): position, packed normal,
    colour (A,R,G,B on Xbox 360; R,G,B,A on PS3), half2 uv, packed tangent,
    packed bitangent."""
    colour = bytes([255, 10, 20, 30]) if console == "x360" else bytes([10, 20, 30, 255])
    b = struct.pack(">3f", x, y, z) + _packed(0, 0, 1) + colour
    return b + np.array((u, v), ">f2").tobytes() + _packed(1, 0, 0) + _packed(0, 1, 0)


def _quad(z, console=None):
    corners = ((0, 0), (1, 0), (1, 1), (0, 1))
    if console:
        vb = b"".join(_console_vertex(x, y, z, x, y, console) for x, y in corners)
        return vb, struct.pack(">6H", 0, 1, 2, 0, 2, 3)
    vb = b"".join(_vertex(x, y, z, x, y) for x, y in corners)
    return vb, struct.pack("<6H", 0, 1, 2, 0, 2, 3)


def _meshbuffer(bo, fmt, nv, index_bytes):
    b = struct.pack(bo + "6f", 0.5, 0.5, 0, 0.5, 0.5, 0) + bytes([1, 0, 0])
    return b + struct.pack(bo + "6I", 8, nv, fmt, 8, index_bytes, 1)


def _bulk(vb, ib, console=None):
    """Stream bytes of one buffer: vertices, indices, ONE cluster record (40
    bytes on PC, 48 on console), an empty list, no per-vertex array."""
    if console:
        return vb + ib + struct.pack(">I", 1) + bytes(48) + struct.pack(">I", 0) + b"\0"
    return vb + ib + struct.pack("<I", 1) + bytes(40) + struct.pack("<I", 0) + b"\0"


def _submesh(bo, layout, name, tex, z, dynamic=0, console=None):
    vb, ib = _quad(z, console)
    h = _str(name, bo) + struct.pack(bo + "II", 1, tex) + bytes([0, 0])
    h += struct.pack(bo + "I", 1) + bytes([dynamic])
    if layout == "part2":
        h += b"\0"  # the flag the stand-alone Part 1 build does not have
    h += _meshbuffer(bo, 5, 4, len(ib)) + struct.pack(bo + "I", 0)
    return h, _bulk(vb, ib, console)


def _capsule(bo, d, h):
    return (
        struct.pack(bo + "II", 7, 0)
        + struct.pack(bo + "2f", d, h)
        + struct.pack(bo + "7f", 0, 0, 0, 0, 0, 0, 1)
        + bytes(4)
    )


def _node(bo, layout, name, parent, pos, lods=(), shadow=False, vols=(), console=None):
    """-> (header bytes, stream bytes).  lods: [[(name, tex, z, dynamic)]]."""
    h = struct.pack(bo + "3f", *pos) + struct.pack(bo + "4f", 0, 0, 0, 1) + _str(name, bo)
    h += struct.pack(bo + "Ii", 0, parent) + struct.pack(bo + "I", len(lods))
    s = b""
    for lod in lods:
        h += struct.pack(bo + "I", len(lod))
        for sm in lod:
            a, b = _submesh(bo, layout, *sm, console=console)
            h += a
            s += b
    h += struct.pack(bo + "I", 1 if shadow else 0)
    if shadow:
        # shadow hull, format 9: 20 bytes a vertex on PC, 16 on console
        vb = b"".join(
            struct.pack(bo + "3f", x, 0, 5) + bytes(4 if console else 8) for x in range(4)
        )
        ib = struct.pack(bo + "6H", 0, 1, 2, 0, 2, 3)
        h += struct.pack(bo + "I", 1) + b"\0" + struct.pack(bo + "I", 0xFFFFFFFF)
        h += _meshbuffer(bo, 9, 4, len(ib))
        s += _bulk(vb, ib, console)
    h += b"\0"  # no occluder
    h += struct.pack(bo + "I", len(vols)) + b"".join(vols)
    h += struct.pack(bo + "II", 0, 0)  # scene-1 volumes, particle surfaces
    return h, s


def _object(bo, typed, owner, name, keys, extra=()):
    types = _types()
    props = [("name", "string", name)]
    props += [(k, types[k], _DEFAULT[types[k]]) for k in keys if k != "name"]
    return _records(props + list(extra), bo, typed, owner)


def _articulated(bo, typed, extra=()):
    types = _types()
    joint_keys = [k for k in rr._PROP_NAMES if k in types and k not in _BODY_KEYS]
    blob = _object(bo, typed, 0x1000, "Pelvis", _BODY_KEYS)
    blob += _object(bo, typed, 0x1001, "Spine", _BODY_KEYS)
    blob += _object(bo, typed, 0x2000, "Spine->Pelvis", joint_keys, extra)
    ab = struct.pack(bo + "I", len(blob) // 4) + blob
    ab += struct.pack(bo + "I2H", 2, 1, 2) + struct.pack(bo + "II", 0, 0)
    return ab + struct.pack(bo + "I2i", 1, 0, 1)


def build(bo="<", layout="part1", meshes=True, typed_bag=None, extra=(), console=None):
    """A ModelRes header + stream: root, Pelvis (two LODs, a shadow hull, one
    collision capsule), Spine (one submesh with the dynamic-copy flag, one
    capsule); two bodies and one joint.  layout "part1": no fifth submesh flag
    and untyped property records.  console "x360" / "ps3" (with bo ">"): the
    stream holds console vertices and console-sized cluster records; without
    it the stream is the PC one whatever `bo` is (header-only tests)."""
    typed = layout == "part2"
    h = _str("ModelRes", bo) + _bag(bo, typed if typed_bag is None else typed_bag)
    h += struct.pack(bo + "IBIB", 0, 1, 0xFFFFFFFF, 0) + struct.pack(bo + "II", 0, 0)
    h += struct.pack(bo + "6f", 0, 0, 0, 1, 1, 1)
    h += struct.pack(bo + "I", len(TEXTURES)) + b"".join(b"\x01" + _str(t, bo) for t in TEXTURES)
    h += struct.pack(bo + "I", 1) + _str("/pivotbooks/default.pb", bo)
    lods = [[("Body", 0, 0.0, 0)], [("BodyLow", 1, 2.0, 0)]] if meshes else []
    spine = [[("Spine", 1, 1.0, 1)]] if meshes else []
    nodes = [
        _node(bo, layout, "", -1, (0, 0, 0)),
        _node(
            bo, layout, "Pelvis", 0, (0, 1, 0), lods, meshes, [_capsule(bo, 0.26, 0.38)], console
        ),
        _node(bo, layout, "Spine", 1, (0.1, 0, 0), spine, False, [_capsule(bo, 0.2, 0.3)], console),
    ]
    h += struct.pack(bo + "I", len(nodes)) + b"".join(n[0] for n in nodes)
    return h + _articulated(bo, typed, extra) + bytes(4), b"".join(n[1] for n in nodes)


# ---------------------------------------------------------------------------
# 1. the header reads in both layouts, and says which
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bo", ["<", ">"])
@pytest.mark.parametrize("layout", ["part1", "part2"])
def test_header_is_read_in_its_own_layout_only(bo, layout):
    h, _s = build(bo, layout)
    other = "part2" if layout == "part1" else "part1"
    M = we.parse_model_header(h, bo)
    assert M is not None and M["layout"] == layout
    assert we.model_header_layout_hint(h, bo) == layout
    assert we.parse_model_header(h, bo, layout=other) is None
    assert [P["name"] for P in M["parts"]] == ["", "Pelvis", "Spine"]
    kinds = [(b["kind"], b["lod"], b["name"]) for b in M["buffers"]]
    assert kinds == [
        ("render", 0, "Body"),
        ("render", 1, "BodyLow"),
        ("shadow", None, ""),
        ("render", 0, "Spine"),
    ]
    assert [b["dynamic_copy"] for b in M["buffers"] if b["kind"] == "render"] == [0, 0, 1]
    no_defer = {b["no_defer"] for b in M["buffers"] if b["kind"] == "render"}
    assert no_defer == ({None} if layout == "part1" else {0})  # absent, not zero
    assert M["textures"] == TEXTURES and M["has_skeleton"] == 1


def test_both_layouts_give_the_same_model():
    a = we.parse_model_header(build("<", "part1")[0], "<")
    b = we.parse_model_header(build("<", "part2")[0], "<")
    strip = lambda buf: {k: v for k, v in buf.items() if k not in ("no_defer", "has_cloth_mesh")}
    assert [strip(x) for x in a["buffers"]] == [strip(x) for x in b["buffers"]]
    assert [P["pos"] for P in a["parts"]] == [P["pos"] for P in b["parts"]]


@pytest.mark.parametrize("typed", [True, False])
def test_a_header_without_submeshes_takes_the_layout_of_its_bag(typed):
    """Nothing but the property bag tells the builds apart then (5 such models
    per Part 1 set: the three skeletons and two empty props)."""
    layout = "part2" if typed else "part1"
    h, s = build("<", layout, meshes=False)
    assert s == b""
    assert we.parse_model_header(h, "<", layout="part1") is not None
    assert we.parse_model_header(h, "<", layout="part2") is not None
    assert we.parse_model_header(h, "<")["layout"] == layout


def test_layout_comes_from_the_records_when_the_bag_points_the_other_way():
    """The hint is tried first, not trusted: the submesh records decide."""
    h, _s = build("<", "part1", typed_bag=True)
    assert we.model_header_layout_hint(h, "<") == "part2"
    assert we.parse_model_header(h, "<")["layout"] == "part1"


def test_stream_of_a_part1_pc_model_tiles_exactly():
    h, s = build("<", "part1")
    M = we.parse_model_header(h, "<")
    bufs = we.model_stream_layout(M, s, "<")
    assert [(b["format"], b["stride"], b["vb"]) for b in bufs] == [
        (5, 44, 0),
        (5, 44, 237),
        (9, 20, 474),
        (5, 44, 615),
    ]
    assert bufs[0]["clusters"] == (192, 1)
    assert we.model_stream_layout(M, s + b"\0", "<") is None


# ---------------------------------------------------------------------------
# 2. sidecar
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bo", ["<", ">"])
def test_sidecar_of_a_part1_header_is_complete_and_says_its_layout(bo):
    h1, _ = build(bo, "part1")
    h2, _ = build(bo, "part2")
    m1, m2 = we.model_meta(h1, order=bo), we.model_meta(h2, order=bo)
    assert m1["header_layout"] == "part1" and "header_layout" not in m2
    assert m1["lod_count"] == 2 and [l["max_distance"] for l in m1["lods"]] == [30.0, 60.0]
    assert m1["not_exported"] == {"shadow_hull": 1, "occluder": 0}
    assert "not_decoded" not in m1
    assert {k: v for k, v in m1.items() if k != "header_layout"} == m2
    assert list(m2)[:2] == ["format", "lod_count"]  # the Part 2 sidecar is unchanged
    json.dumps(m1)


def test_scan_decoded_console_part1_model_gets_the_full_sidecar():
    """Xbox 360 Part 1: the mesh still comes from the descriptor scan, the header
    is read (it was the reduced sidecar with lod_count null and five LOD slots)."""
    h, _s = build(">", "part1")
    meta = we.model_meta_scanned(h, ">")
    assert meta["header_decoded"] is True and meta["mesh_source"] == "descriptor scan"
    assert meta["header_layout"] == "part1" and meta["lod_count"] == 2 and len(meta["lods"]) == 2
    assert "not_decoded" not in meta


def test_header_of_neither_layout_keeps_the_reduced_sidecar_with_its_marker():
    h = _str("ModelRes", "<") + _bag("<", False) + bytes(40)
    assert we.parse_model_header(h, "<") is None
    meta = we.model_meta_scanned(h, "<")
    assert meta["header_decoded"] is False and meta["lod_count"] is None
    assert "lod_count" in meta["not_decoded"] and "neither" in meta["not_decoded_note"]


# ---------------------------------------------------------------------------
# 3. header-driven mesh decode of a PC Part 1 model
# ---------------------------------------------------------------------------
def test_pc_part1_model_is_decoded_header_driven(tmp_path, monkeypatch):
    cap = {}

    def fake(path, name, v, n, uv, tris, subs, mats, tex_index, log):
        cap.update(v=list(v), tris=list(tris), subs=list(subs), mats=list(mats))

    monkeypatch.setattr(we, "_write_obj_mtl", fake)
    h, s = build("<", "part1")
    assert we.decode_model(h, s, tmp_path / "m.obj") is True
    # LOD 0 only, no shadow hull, materials from the submesh records
    assert sorted({v[2] for v in cap["v"]}) == [0.0, 1.0]
    assert cap["mats"] == ["Wall_01", "Trim_02"] and len(cap["tris"]) == 4
    meta = json.loads((tmp_path / "m.model.json").read_text())
    assert meta["header_layout"] == "part1" and meta["lod_count"] == 2
    assert "mesh_source" not in meta and "not_decoded" not in meta
    mesh = we.decode_model_mesh(h, s, lod="all")
    assert [m["name"] for m in mesh["submeshes"]] == ["Body", "BodyLow", "Spine"]
    assert mesh["submeshes"][0]["color"][0].tolist() == [10, 20, 30, 255]
    assert np.allclose(mesh["submeshes"][0]["tangent"][0], [1, 0, 0])


def test_character_piece_of_a_pc_part1_model_gets_its_vertex_attributes():
    h, s = build("<", "part1")
    b = we.model_stream_layout(we.parse_model_header(h, "<"), s, "<")[0]
    at = vg.buffer_vertex_attrs(h, s, "<", b["vb"], b["vertex_count"], b["stride"])
    assert at is not None and at["has_color"] is True
    assert np.allclose(at["normal"][0], [0, 0, 1]) and np.allclose(at["tangent"][0], [1, 0, 0])
    # a big-endian header over a stream that is not the console layout: nothing
    hb, sb = build(">", "part1")
    assert vg.buffer_vertex_attrs(hb, sb, ">", b["vb"], b["vertex_count"], b["stride"]) is None


def test_node_table_of_a_pc_part1_model_is_header_driven():
    names, pos, _quat, parent = pmn.parse(build("<", "part1")[0])
    assert names == ["(root)", "Pelvis", "Spine"] and parent.tolist() == [-1, 0, 1]
    assert pos[1].tolist() == [0.0, 1.0, 0.0]
    assert pmn.parse_header_driven(build(">", "part1")[0]) is None  # little-endian only


# ---------------------------------------------------------------------------
# 4. property records without a type word
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bo", ["<", ">"])
def test_untyped_articulated_records_get_their_type_from_the_key(bo):
    typed = _object(bo, True, 7, "Pelvis", _BODY_KEYS)
    untyped = _object(bo, False, 7, "Pelvis", _BODY_KEYS)
    assert len(typed) - len(untyped) == 4 * len(_BODY_KEYS)
    assert sr.property_record_layout(typed, 0, len(typed) // 4, bo) == "typed"
    assert sr.property_record_layout(untyped, 0, len(untyped) // 4, bo) == "untyped"
    a = sr.read_property_records(typed, 0, len(typed) // 4, bo)
    b = sr.read_property_records(untyped, 0, len(untyped) // 4, bo)
    assert a == b and all(r[2] in sr.RECORD_TYPES for r in b)
    props = sr.record_objects(b, rr.property_names(), bo)[0]["props"]
    assert props["name"] == "Pelvis" and props["mass"] == 0.5 and props["movementType"] == 0


def test_untyped_table_covers_every_typed_ragdoll_property_once():
    types = sr.untyped_record_types()
    assert len(types) == 86 == sum(len(v.split()) for v in sr._UNTYPED_SRC.values())
    assert set(types.values()) <= set(sr.RECORD_TYPES)
    assert types[kp.name_hash("childSpaceOrient")] == 0xD007189C


def test_untyped_record_with_an_unknown_key_is_marked_not_guessed():
    blob = struct.pack("<3If", 7, 0x12345678, 1, 2.5)
    blob += struct.pack("<3I3f", 7, kp.name_hash("mass"), 3, 1, 2, 3)  # wrong size for a number
    recs = sr.read_property_records(blob, 0, len(blob) // 4)
    assert [r[2] for r in recs] == [0, 0]
    obj = sr.record_objects(recs, rr.property_names())[0]["props"]
    assert obj["key_12345678"] == {"type_id": "0x00000000", "hex": blob[12:16].hex()}
    assert isinstance(obj["mass"], dict)  # raw bytes, not a made-up number


def test_property_blob_of_neither_layout_still_raises():
    with pytest.raises(ValueError):
        sr.read_property_records(struct.pack("<4I", 1, 2, 3, 99), 0, 4)
    assert sr.property_record_layout(struct.pack("<4I", 1, 2, 3, 99), 0, 4) is None


def test_pivot_book_reader_stays_typed_so_the_part1_fallback_still_runs():
    """ragdoll_rig.pivot_sheets relies on parse_pivot_book RAISING on an untyped
    book to hand it to kapow_props.pivot_book, which knows those keys."""
    recs = struct.pack("<3If", 9, kp.name_hash("friction"), 1, 0.4)
    book = struct.pack("<3I", 1, 2, 1) + struct.pack("<I", 11) + b"PivotSheet\0"
    book += struct.pack("<I", len(recs) // 4) + recs
    with pytest.raises((ValueError, struct.error)):
        sr.parse_pivot_book(book, rr.property_names())


# ---------------------------------------------------------------------------
# 5. physics and the ragdoll rig
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bo", ["<", ">"])
@pytest.mark.parametrize("meshes", [True, False])
def test_ragdoll_rig_of_a_part1_model_equals_the_part2_one(bo, meshes):
    extra = [("swing1MotionLimitValue", "number", 35.0)]
    h1 = build(bo, "part1", meshes, extra=extra)[0]
    h2 = build(bo, "part2", meshes, extra=extra)[0]
    r1, why = rr._build(h1, bo)
    assert why is None and rr.explain(h1, bo) is None
    assert [b["bone"] for b in r1["bodies"]] == ["Pelvis", "Spine"]
    assert len(r1["joints"]) == 1 and r1["joints"][0]["name"] == "Spine->Pelvis"
    assert r1["joints"][0]["swing1"]["limit_deg"] == 35.0  # the later record wins, as typed
    assert r1["bodies"][0]["shapes"][0]["file"] == {"diameter": 0.26, "height_total": 0.38}
    assert json.dumps(r1, sort_keys=True) == json.dumps(rr.build(h2, bo), sort_keys=True)
    assert rr.build(h1) == r1  # byte order from the header


@pytest.mark.parametrize("layout", ["part1", "part2"])
def test_model_physics_reports_the_layout_and_ends_at_the_tail(layout):
    h, _s = build("<", layout)
    m = pmn.model_physics(h, "<")
    assert m["layout"] == layout and m["end"] == len(h) - 4
    assert [len(n["volumes"][0]) for n in m["nodes"]] == [0, 1, 1]
    ab = m["articulated_body"]
    assert ab["bodies"] == [1, 2] and ab["joints"] == [(0, 1)] and len(ab["records"]) > 60


def test_rig_reason_when_the_header_follows_neither_layout():
    junk = _str("ModelRes", "<") + _bag("<", False) + bytes(40)
    assert rr.build(junk) is None and rr.explain(junk) == rr.NO_LAYOUT
    assert "neither" in rr.NO_LAYOUT and "older record format" in rr.NO_LAYOUT


@pytest.mark.parametrize("bo", ["<", ">"])
def test_node_tail_walks_the_mesh_section_of_either_layout(bo):
    for layout in ("part1", "part2"):
        node, _s = _node(
            bo, layout, "Pelvis", 0, (0, 1, 0), [[("Body", 0, 0.0, 0)]], True, [_capsule(bo, 1, 2)]
        )
        start = 28 + 4 + len("Pelvis") + 1  # behind the name
        tail = sr.parse_node_tail(node, start, len(node), bo, meshes=True)
        assert tail is not None and tail["has_mesh"] and tail["end"] == len(node)
        assert tail["volumes"][0][0]["type"] == 7
        other = "part2" if layout == "part1" else "part1"
        with pytest.raises((ValueError, struct.error)):
            sr._skip_node_meshes(node, start + 8, bo, len(node), other)


# ---------------------------------------------------------------------------
# 6. console files: the header locates the buffers there too
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("layout", ["part1", "part2"])
@pytest.mark.parametrize("console", ["x360", "ps3"])
def test_console_stream_tiles_with_the_console_strides_and_cluster_size(layout, console):
    h, s = build(">", layout, console=console)
    M = we.parse_model_header(h, ">")
    bufs = we.model_stream_layout(M, s, ">")
    assert [(b["format"], b["stride"], b["vb"]) for b in bufs] == [
        (5, 32, 0),
        (5, 32, 197),
        (9, 16, 394),
        (5, 32, 527),
    ]
    assert bufs[0]["clusters"] == (144, 1)  # one 48-byte record
    assert we.model_stream_layout(M, s + b"\0", ">") is None
    assert we.model_stream_layout(M, s, "<") is None
    assert we.vertex_strides(">")[5] == 32 and we.vertex_strides("<")[5] == 44
    # the PC stream of the same model does not tile as a console one
    assert we.model_stream_layout(we.parse_model_header(h, ">"), build(">", layout)[1], ">") is None


@pytest.mark.parametrize("console", ["x360", "ps3"])
def test_console_mesh_equals_the_pc_mesh_vertex_for_vertex(console):
    pc = we.decode_model_mesh(*build("<", "part2"), lod="all")
    co = we.decode_model_mesh(*build(">", "part2", console=console), lod="all")
    assert co["order"] == ">" and pc["order"] == "<" and "not_decoded" not in co
    assert we.console_color_order(
        build(">", "part2", console=console)[1], co["model"]["buffers"]
    ) == ("argb" if console == "x360" else "rgba")
    for a, b in zip(pc["submeshes"], co["submeshes"]):
        assert (a["name"], a["material"], a["triangles"]) == (
            b["name"],
            b["material"],
            b["triangles"],
        )
        assert a["positions"] == b["positions"] and a["uvs"] == b["uvs"]
        assert np.allclose(a["normals"], b["normals"], atol=2e-3)
        assert np.allclose(a["tangent"], b["tangent"], atol=2e-3)
        assert np.allclose(a["bitangent"], b["bitangent"], atol=2e-3)
        assert a["color"].tolist() == b["color"].tolist() == [[10, 20, 30, 255]] * 4


def test_console_model_is_decoded_header_driven(tmp_path, monkeypatch):
    cap = {}

    def fake(path, name, v, n, uv, tris, subs, mats, tex_index, log):
        cap.update(v=list(v), tris=list(tris), mats=list(mats))

    monkeypatch.setattr(we, "_write_obj_mtl", fake)
    h, s = build(">", "part1", console="x360")
    logs = []
    assert we.decode_model(h, s, tmp_path / "m.obj", log=lambda *a: logs.append(a[0])) is True
    assert sorted({v[2] for v in cap["v"]}) == [0.0, 1.0]  # LOD 0, no LOD 1, no shadow hull
    assert cap["mats"] == ["Wall_01", "Trim_02"] and len(cap["tris"]) == 4
    meta = json.loads((tmp_path / "m.model.json").read_text())
    assert meta["lod_count"] == 2 and meta["header_layout"] == "part1"
    assert "mesh_source" not in meta and "not_decoded" not in meta
    assert not any("note:" in l for l in logs)


def test_console_colour_is_not_guessed_when_the_model_does_not_show_the_order(
    tmp_path, monkeypatch
):
    """Colour (255, g, 255, 255): the first and the last byte are 255 on both
    consoles, so the alpha byte cannot be told -- no colour, a marker, a log line."""
    h, s = build(">", "part2", console="x360")
    s = s.replace(bytes([255, 10, 20, 30]), bytes([255, 255, 20, 255]))
    M = we.parse_model_header(h, ">")
    we.model_stream_layout(M, s, ">")
    assert we.console_color_order(s, M["buffers"]) is None
    assert len(we.console_color_undecoded(s, M["buffers"])) == 3
    mesh = we.decode_model_mesh(h, s, lod="all")
    assert mesh["not_decoded"] == ["COLOR_0"] and "color" not in mesh["submeshes"][0]
    assert [b["has_color"] for b in mesh["model"]["buffers"]] == [0, 0, 0, 0]
    assert mesh["model"]["buffers"][0]["has_color_file"] == 1
    b = M["buffers"][0]
    at = vg.buffer_vertex_attrs(h, s, ">", b["vb"], b["vertex_count"], b["stride"])
    assert at["color_not_decoded"] is True and at["has_color"] is False  # frame kept
    monkeypatch.setattr(we, "_write_obj_mtl", lambda *a: None)
    logs = []
    assert we.decode_model(h, s, tmp_path / "m.obj", log=lambda *a: logs.append(a[0])) is True
    meta = json.loads((tmp_path / "m.model.json").read_text())
    assert meta["not_decoded"] == ["COLOR_0"] and "order" in meta["not_decoded_note"]
    assert sum("vertex colours not decoded" in l for l in logs) == 1
    # plain white is the same in either order: decoded, no marker
    white = build(">", "part2", console="ps3")[1].replace(bytes([10, 20, 30, 255]), b"\xff" * 4)
    assert we.console_color_order(white, M["buffers"]) is None
    assert we.console_color_undecoded(white, M["buffers"]) == []
    mesh = we.decode_model_mesh(h, white, lod=0)
    assert "not_decoded" not in mesh and mesh["submeshes"][0]["color"].tolist() == [[255] * 4] * 4


@pytest.mark.parametrize("console", ["x360", "ps3"])
def test_console_character_piece_gets_its_vertex_attributes(console):
    h, s = build(">", "part1", console=console)
    b = we.model_stream_layout(we.parse_model_header(h, ">"), s, ">")[3]
    at = vg.buffer_vertex_attrs(h, s, ">", b["vb"], b["vertex_count"], b["stride"])
    assert at["color"].tolist() == [[10, 20, 30, 255]] * 4 and at["has_color"] is True
    assert np.allclose(at["normal"][0], [0, 0, 1], atol=2e-3)
    assert np.allclose(at["tangent"][0], [1, 0, 0], atol=2e-3)
    assert np.allclose(at["bitangent"][0], [0, 1, 0], atol=2e-3)
    assert vg.buffer_vertex_attrs(h, s, ">", b["vb"] + 4, b["vertex_count"], b["stride"]) is None


def test_console_stream_that_does_not_tile_falls_back_to_the_scan_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(we, "_write_obj_mtl", lambda *a: None)
    h, s = build(">", "part2", console="ps3")
    assert we._header_model_plan(h, s + b"\0", 0, ">") is None
    assert we.decode_model_mesh(h, s + b"\0") is None


def test_console_models_can_be_sent_back_to_the_scan(monkeypatch):
    h, s = build(">", "part2", console="x360")
    b = we.model_stream_layout(we.parse_model_header(h, ">"), s, ">")[0]
    assert we.console_header_decode() is True
    monkeypatch.setenv("WATCHMEN_CONSOLE_MODELS", "scan")
    assert we.console_header_decode() is False
    assert we._header_model_plan(h, s, 0, ">") is None and we.decode_model_mesh(h, s) is None
    assert vg.buffer_vertex_attrs(h, s, ">", b["vb"], b["vertex_count"], b["stride"]) is None
    # PC models are not affected by the switch
    assert we.decode_model_mesh(*build("<", "part1")) is not None
