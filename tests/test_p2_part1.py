"""Pass 2, package C (Part 1 layout): stream sets and the older record layout.

Synthetic fixtures only (little- and big-endian, both record layouts are built
here).  What each section pins, and the data it was read from:

  1. stream sets      the trailing blob of Part 1's Prison block: four manual
                      sets, bounds = two 3-float vectors, streams in separate
                      `.block_s_z` files (PC, X360, PS3: 96 entries each)
  2. record layouts   typed [owner][key][type][k][payload] against the older
                      untyped [owner][key][k][payload] of standalone Part 1 on
                      PC / X360 (kapow_props.read_records)
  3. property bags    .grass / .detailmesh / .pb in the older layout decode to
                      what the typed file of the same asset gives
  4. texture sheets   texture_sheet / texture_sheets / extract_specular
  5. model sidecar    property bag, LOD distances behind a long string, the
                      sidecar of a scan-decoded model
"""

import json
import struct
import zlib

import pytest

import kapow_json
import kapow_props as kp
import watchmen_extract as we

_TEX = we._name_hash("Texture")
_MDL = we._name_hash("modelRes")


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------
def _str(s, bo="<"):
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
    if typ == "id":
        return struct.pack(bo + "II", value >> 32, value & 0xFFFFFFFF)
    return struct.pack(bo + "%df" % len(value), *value)  # vector


def _records(props, bo="<", typed=True, owner=0x20D4966D):
    """props: [(name, type, value)] -> record bytes in one of the two layouts."""
    out = b""
    for name, typ, value in props:
        pl = _payload(typ, value, bo)
        out += struct.pack(bo + "II", owner, kp.name_hash(name))
        if typed:
            out += struct.pack(bo + "I", kp.type_hash(typ))
        out += struct.pack(bo + "I", len(pl) // 4) + pl
    return out


def _object(cls, props, bo="<", typed=True, owner=0x20D4966D):
    recs = _records(props, bo, typed, owner)
    return _str(cls, bo) + struct.pack(bo + "I", len(recs) // 4) + recs


def _block(entries, sets=(), bo="<", bounds=6, own_stream=b""):
    """entries: [(name, type hash, header blob, (offset, size) | None)];
    sets: [(stream file, [(type hash, name, (offset, size))], node path ids)].
    -> block_h_z bytes with the stream sets as MANUAL sets in the trailer."""
    toc = blobs = b""
    for name, th, blob, pair in entries:
        nm = name.encode("latin1") + b"\0"
        toc += struct.pack(bo + "6I", *([len(blob)] * 6)) + struct.pack(bo + "II", th, len(nm))
        toc += nm
        if pair is None:
            toc += b"\0"
        else:
            toc += b"\x01" + struct.pack(bo + "II", *pair) * 6
        blobs += blob
    trailer = struct.pack(bo + "II", 0, len(sets))
    for sfile, items, ids in sets:
        trailer += struct.pack(bo + "I%dI" % len(ids), len(ids), *ids)
        trailer += struct.pack(bo + "%df" % bounds, *([0.0] * bounds)) + _str(sfile, bo)
        trailer += struct.pack(bo + "II", len(items), len(items))
        for th, nm, pair in items:
            trailer += struct.pack(bo + "I", th) + _str(nm, bo) + struct.pack(bo + "II", *pair) * 6
    hdr = bytearray(400)
    hdr[0x147] = 2
    struct.pack_into(
        bo + "9I",
        hdr,
        328,
        0,
        len(toc),
        len(entries[0][2]),
        max(len(toc), max(len(e[2]) for e in entries)),
        400 + len(toc) + len(blobs),
        len(trailer),
        len(entries),
        0,
        sum(1 for e in entries if e[3] is not None),
    )
    struct.pack_into("<4s", hdr, 328, bytes.fromhex("0a883f59"))
    return bytes(hdr) + toc + blobs + trailer


def _prison(bo="<", bounds=6):
    """A block with one own stream and two entries whose streams sit in a room file."""
    a, b, c = zlib.compress(b"own-stream"), zlib.compress(b"fence-mesh"), zlib.compress(b"floor")
    room = b + c
    h = _block(
        [
            ("/art/Wall.bmp", _TEX, zlib.compress(b"HDR-WALL"), (0, len(a))),
            ("/art/Fence_01.model", _MDL, zlib.compress(b"HDR-FENCE"), None),
            ("/art/Shower_Floor_01.bmp", _TEX, zlib.compress(b"HDR-FLOOR"), None),
            ("/art/Skeleton.model", _MDL, zlib.compress(_str("ModelRes") + bytes(8)), None),
        ],
        [
            (
                "/derived_pc/Levels/Prison/Art/PrisonYard.block_s_z",
                [
                    (_MDL, "/art/fence_01.model", (0, len(b))),
                    (_TEX, "/art/Shower_Floor_01.bmp", (len(b), len(c))),
                ],
                (0xB06AAE30, 0x4016EFFE),
            )
        ],
        bo,
        bounds,
    )
    return h, a, room


# ---------------------------------------------------------------------------
# 1. stream sets
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bo", ["<", ">"])
def test_trailer_reads_manual_sets_with_three_float_bounds(bo):
    h, _a, _room = _prison(bo)
    t = we.parse_block_trailer(h)
    assert t["auto_stream_sets"] == [] and t["end"] == len(h)
    (st,) = t["manual_stream_sets"]
    assert st["bounds_floats"] == 6 and st["min"] == (0.0, 0.0, 0.0)
    assert st["stream_file"] == "/derived_pc/Levels/Prison/Art/PrisonYard.block_s_z"
    assert st["node_path"] == ["b06aae30", "4016effe"] and st["value"] == 2
    assert [e["name"] for e in st["entries"]] == ["/art/fence_01.model", "/art/Shower_Floor_01.bmp"]
    assert st["entries"][0]["type"] == "modelRes"
    sets, err = we.block_stream_sets(h)
    assert err is None and len(sets) == 1


def test_trailer_still_reads_the_four_float_bounds_of_the_code_reading():
    h, _a, _room = _prison("<", bounds=8)
    (st,) = we.parse_block_trailer(h)["manual_stream_sets"]
    assert st["bounds_floats"] == 8 and len(st["min"]) == 4 and len(st["entries"]) == 2


def test_stream_file_lookup_drops_the_derived_root_and_ignores_case():
    find = we.stream_file_lookup(
        {
            "/Levels/Prison/Art/PrisonYard.block_s_z": b"YARD",
            "levels/prison/art/hall.block_s_z": b"H",
        }
    )
    assert find("/derived_pc/Levels/Prison/Art/PrisonYard.block_s_z") == b"YARD"
    assert find("/derived_ps3/levels/prison/art/prisonyard.block_s_z") == b"YARD"
    assert find("/derived_x360/Levels/Prison/Art/Hall.block_s_z") == b"H"
    assert find("/derived_pc/Levels/Prison/Art/Missing.block_s_z") is None


@pytest.mark.parametrize("bo", ["<", ">"])
def test_extract_block_takes_streams_from_the_stream_sets(bo):
    h, a, room = _prison(bo)
    find = we.stream_file_lookup({"/Levels/Prison/Art/PrisonYard.block_s_z": room})
    msgs = []
    got = {e.name: (e, hd, st) for e, hd, st in we.extract_block(h, a, 0, msgs.append, find)}
    assert got["/art/Wall.bmp"][2] == b"own-stream" and got["/art/Wall.bmp"][0].stream_file is None
    e, hd, st = got["/art/Fence_01.model"]  # name match is case-insensitive
    assert (hd, st) == (b"HDR-FENCE", b"fence-mesh")
    assert e.stream_file == "/derived_pc/Levels/Prison/Art/PrisonYard.block_s_z"
    assert got["/art/Shower_Floor_01.bmp"][2] == b"floor"
    # in no set: stays without a stream, and without a note
    e, _hd, st = got["/art/Skeleton.model"]
    assert st is None and e.stream_file is None and e.stream_note is None
    assert msgs == []


def test_extract_block_without_a_resolver_is_unchanged():
    h, a, _room = _prison()
    got = [(e.name, st) for e, _hd, st in we.extract_block(h, a)]
    assert got == [
        ("/art/Wall.bmp", b"own-stream"),
        ("/art/Fence_01.model", None),
        ("/art/Shower_Floor_01.bmp", None),
        ("/art/Skeleton.model", None),
    ]


def test_a_missing_or_short_stream_file_is_reported_by_asset_name():
    h, a, room = _prison()
    msgs = []
    out = list(we.extract_block(h, a, 0, msgs.append, we.stream_file_lookup({})))
    assert [st for _e, _h, st in out] == [b"own-stream", None, None, None]
    assert len(msgs) == 2 and "/art/Fence_01.model" in msgs[0] and "not found" in msgs[0]
    assert out[1][0].stream_note.startswith("stream file /derived_pc/")
    msgs = []
    find = we.stream_file_lookup({"/Levels/Prison/Art/PrisonYard.block_s_z": room[:5]})
    out = list(we.extract_block(h, a, 0, msgs.append, find))
    assert out[1][2] is None and "runs past" in msgs[0] and "/art/Fence_01.model" in msgs[0]


def test_extract_reads_stream_only_blocks_and_names_what_has_no_stream(tmp_path):
    """main(): the room file is a stream-only `.block_s_z`; the two assets it
    feeds are extracted, the one left without a stream is logged by name, and a
    stream-only file no set names is reported."""
    h, a, room = _prison()
    src = tmp_path / "derived_pc" / "Levels" / "Prison"
    (src / "Art").mkdir(parents=True)
    (src / "Prison.block_h_z").write_bytes(h)
    (src / "Prison.block_s_z").write_bytes(a)
    (src / "Art" / "PrisonYard.block_s_z").write_bytes(room)
    (src / "Art" / "Orphan.block_s_z").write_bytes(b"xx")
    out = tmp_path / "out"
    lines = []
    import builtins

    real = builtins.print
    builtins.print = lambda *x, **k: lines.append(" ".join(str(v) for v in x))
    try:
        rc = we.main(
            [
                str(tmp_path / "derived_pc"),
                "-o",
                str(out),
                "--no-textures",
                "--no-models",
                "--no-audio",
                "--no-text",
                "--no-nav",
            ]
        )
    finally:
        builtins.print = real
    assert rc == 0
    ex = out / "extracted" / "art"
    assert (ex / "Fence_01.model.stream").read_bytes() == b"fence-mesh"
    assert (ex / "Shower_Floor_01.bmp.stream").read_bytes() == b"floor"
    assert not (ex / "Skeleton.model.stream").exists()
    log = "\n".join(lines)
    assert "no stream: /art/Skeleton.model (ModelRes): header only, not in any stream set" in log
    assert "/derived_pc/Levels/Prison/Art/PrisonYard.block_s_z: 2 asset stream(s) read" in log
    assert "Orphan.block_s_z: no stream set of any block names this file" in log
    assert "no stream: /art/Fence_01.model" not in log


# ---------------------------------------------------------------------------
# 2. record layouts
# ---------------------------------------------------------------------------
_GRASS = [
    ("templateName", "string", "Grass_Lawn"),
    ("randSeed", "integer", 1),
    ("texture", "string", "/art/Environments/Common/Grass/Textures/Grass_Rough_01.bmp"),
    ("numVariations", "integer", 5),
    ("density", "integer", 35),
    ("constantAmbient", "truth", 0),
    ("width", "number", 0.4),
    ("ambientHeight", "number", 0.0),
    ("lodRange", "number", 30.0),
]


@pytest.mark.parametrize("bo", ["<", ">"])
@pytest.mark.parametrize("typed", [True, False])
def test_read_records_tells_the_two_layouts_apart(bo, typed):
    recs = _records(_GRASS, bo, typed)
    lay, got = kp.read_records(recs, 0, len(recs), bo)
    assert lay == ("typed" if typed else "untyped") and len(got) == len(_GRASS)
    assert [g[1] for g in got] == [kp.name_hash(n) for n, _t, _v in _GRASS]
    assert (got[0][2] is None) == (not typed)
    # the other layout never fits the same bytes
    assert kp.read_records(recs, 0, len(recs), bo, "untyped" if typed else "typed") is None
    # wrong byte order, a cut span, an empty span: nothing is guessed
    assert kp.read_records(recs, 0, len(recs), ">" if bo == "<" else "<") is None
    assert kp.read_records(recs, 0, len(recs) - 4, bo) is None
    assert kp.read_records(recs, 0, 0, bo) is None


def test_untyped_zero_values_and_strings_are_not_read_as_typed_records():
    """[owner][key][1][0] is also a well-formed typed record of "type" 1 with no
    payload, and an untyped string one of "type" k: a type hash is never that small."""
    props = [("name", "string", "ab"), ("randSeed", "integer", 0), ("constantAmbient", "truth", 0)]
    recs = _records(props, "<", typed=False)
    assert kp.read_records(recs, 0, len(recs), "<")[0] == "untyped"
    assert kp.read_records(recs, 0, len(recs), "<", "typed") is None


def test_a_record_of_another_owner_ends_neither_layout_exactly():
    recs = _records(_GRASS[:2], "<", False) + _records(_GRASS[2:3], "<", False, owner=7)
    assert kp.read_records(recs, 0, len(recs), "<") is None


def test_untyped_type_table_covers_the_stored_sheet_properties():
    ut = kp.untyped_types()
    stored = set(we.SHEET_PROPERTIES)
    assert all(kp.name_hash(n) in ut for n in stored)
    for name, typ in we.TEXTURE_SHEET_PROPS.items():
        assert ut[kp.name_hash(name)] == typ
    assert ut[kp.name_hash("uniqueID")] == "id" and kp.type_hash("id") == 0xEDEF427C
    assert ut[kp.name_hash("density")] == "integer"  # a `number` in script classes


# ---------------------------------------------------------------------------
# 3. property bags (.grass / .detailmesh / .pb)
# ---------------------------------------------------------------------------
def _norm(doc):
    out = []
    for bl in doc["blocks"]:
        props = []
        for r in bl["props"]:
            v = r["value"]
            if isinstance(v, dict):
                v = ("raw", v.get("raw_type"), tuple(v.get("floats") or ()))
            props.append((r["key"], r["type"], v))
        out.append((bl["class"], props))
    return out


@pytest.mark.parametrize("bo", ["<", ">"])
def test_grass_in_the_older_layout_decodes_like_the_typed_file(bo):
    new = kp.parse(_object("grass", _GRASS, bo, True), order=bo)
    old = kp.parse(_object("grass", _GRASS, bo, False), order=bo)
    assert old["trailing_bytes"] == 0 and len(old["blocks"][0]["props"]) == len(_GRASS)
    assert _norm(old) == _norm(new)
    assert old["record_layout"] == "untyped" and old["blocks"][0]["record_layout"] == "untyped"
    assert "record_layout" not in new and "record_layout" not in new["blocks"][0]
    assert "warn" not in old
    vals = {r["key"]: r["value"] for r in old["blocks"][0]["props"]}
    assert vals["templateName"] == "Grass_Lawn" and vals["density"] == 35
    assert vals["width"] == pytest.approx(0.4) and vals["constantAmbient"] == 0


def test_detailmesh_keeps_its_trailing_bytes_marker_in_both_layouts():
    props = [
        ("templateName", "string", "Ashes_01"),
        ("model", "string", "/art/Environments/Common/terraindetail/Detail_Ashes_01.model"),
        ("lightModel", "integer", 2),
        ("movePower", "number", 0.0),
        ("useConstantAmbient", "truth", 0),
        ("range", "number", 25.0),
    ]
    tail = bytes(24)
    old = kp.parse(_object("detailmeshasset", props, "<", False) + tail)
    new = kp.parse(_object("detailmeshasset", props, "<", True) + tail + b"\x01")
    assert old["trailing_bytes"] == 24 and new["trailing_bytes"] == 25
    assert _norm(old) == _norm(new) and len(old["blocks"][0]["props"]) == 6


def _pivot_book(bo, typed):
    def sheet(name, uid, friction, mask, owner):
        return _object(
            "PivotSheet",
            [
                ("name", "string", name),
                ("open", "truth", 0),
                ("runScript", "truth", 1),
                ("uniqueID", "id", uid),
                ("friction", "number", friction),
                ("restitution", "number", 0.0),
                ("collisionMask", "integer", mask),
            ],
            bo,
            typed,
            owner,
        )

    # the book id is one u64 in the file's byte order: fa 9e 26 16 64 29 00 00 on PC,
    # 00 00 29 64 16 26 9e fa on Xbox 360 and PS3 (default.pb of all six sets)
    out = struct.pack(bo + "QI", 0x296416269EFA, 2)
    out += sheet("Default", 0x447EF063_071836EC, 0.9, 0x262F, 0x60C350E7)
    out += struct.pack(bo + "I", 0x262F)
    out += sheet("Ragdoll", 0x45AF888D_43B830D4, 0.6, 1, 0x60C4488B)
    out += struct.pack(bo + "I", 1)
    return out + _str("PivotBook", bo) + struct.pack(bo + "I", 0) + b"\0"


@pytest.mark.parametrize("bo", ["<", ">"])
def test_pivot_book_in_the_older_layout(bo):
    old_raw, new_raw = _pivot_book(bo, False), _pivot_book(bo, True)
    old, new = kp.parse(old_raw, order=bo), kp.parse(new_raw, order=bo)
    assert [b["class"] for b in old["blocks"]] == ["PivotSheet", "PivotSheet", "PivotBook"]
    assert _norm(old) == _norm(new)
    uid = old["blocks"][0]["props"][3]
    assert uid["key"] == "uniqueID" and uid["type"] == "edef427c"  # as the typed file shows it
    # the plain reader other modules can use for the ragdoll material
    for raw, lay in ((old_raw, "untyped"), (new_raw, "typed")):
        pb = kp.pivot_book(raw, bo)
        assert pb["record_layout"] == lay and [s["name"] for s in pb["sheets"]] == [
            "Default",
            "Ragdoll",
        ]
        rag = pb["sheets"][1]
        assert rag["uniqueID"] == 0x43B830D4_45AF888D and rag["collisionMask"] == 1  # 1st dword low
        assert rag["friction"] == pytest.approx(0.6) and rag["runScript"] is True
    assert kp.pivot_book(old_raw, ">" if bo == "<" else "<")["sheets"] == []


def test_an_untyped_record_without_a_known_type_is_kept_raw_and_warned():
    recs = _records([("templateName", "string", "x")], "<", False)
    recs += struct.pack("<4I", 0x20D4966D, 0x12345678, 1, 0xDEADBEEF)
    raw = _str("grass") + struct.pack("<I", len(recs) // 4) + recs
    doc = kp.parse(raw)
    assert doc["trailing_bytes"] == 0 and doc["record_layout"] == "untyped"
    rec = doc["blocks"][0]["props"][1]
    assert rec == {
        "key": "12345678",
        "type": "unknown",
        "value": {"raw_type": None, "hex": "efbeadde"},
    }
    assert any("no known value type" in w for w in doc["warn"])


def test_kapow_json_marks_the_older_layout_and_leaves_typed_output_alone():
    old = kapow_json.to_json("a.grass", _object("grass", _GRASS, ">", False))
    new = kapow_json.to_json("a.grass", _object("grass", _GRASS, ">", True))
    assert old["record_layout"] == "untyped" and "Part 1" in old["record_layout_note"]
    assert sorted(new) == ["blocks", "trailing_bytes"]
    json.dumps(old)


# ---------------------------------------------------------------------------
# 4. texture sheets
# ---------------------------------------------------------------------------
_SHEET = [
    ("name", "string", "default"),
    ("open", "truth", 0),
    ("uniqueID", "id", 0x483D06F5_ECE9AC1D),
    ("renderType", "integer", 1),
    ("isLit", "truth", 1),
    ("selfIlluminanceColor", "vector", (1.0, 0.5, 0.25)),
    ("normalMapPower", "number", 1.5),
    ("specularPower", "number", 0.58),
    ("specularSize", "number", 20.0),
    ("opacity", "number", 1.0),
    ("alphaThreshold", "integer", 95),
    ("writeDepthBuffer", "truth", 1),
    ("twoSided", "truth", 1),
    ("enableNormalMapping", "truth", 1),
    ("blendType", "integer", 2),
    ("diffuseMapOverride", "string", ""),
    ("normalMapOverride", "string", "/art/textures/Other_Normal.bmp"),
]


def _texture_header(bo, typed, sheets=(_SHEET,)):
    tex = [("compress", "truth", 1)] + [
        ("tex%sScale" % n, "integer", 1) for n in ("Diffuse", "Normal", "Spec", "Glow")
    ]
    out = _object("Texture", tex, bo, typed, owner=0xF435EE22)
    out += bytes(97)  # image descriptors (not read here)
    out += _str("/data/art/textures/Wall.bmp", bo) + struct.pack(bo + "II", 1, 2)
    out += struct.pack(bo + "I", len(sheets))
    for i, sh in enumerate(sheets):
        out += _object("TextureSheet", sh, bo, typed, owner=0xF554EBFB + i)
    return out


@pytest.mark.parametrize("bo", ["<", ">"])
def test_texture_sheets_of_the_older_layout_equal_the_typed_ones(bo):
    second = [("name", "string", "wet")] + [p for p in _SHEET[1:] if p[0] != "twoSided"]
    second[2] = ("uniqueID", "id", 0x1122334455667788)
    old = _texture_header(bo, False, (_SHEET, second))
    new = _texture_header(bo, True, (_SHEET, second))
    want = we.texture_sheets(new, bo)
    assert len(want) == 2 and want[0]["overrides"] == {"normal": "/art/textures/Other_Normal.bmp"}
    got = we.texture_sheets(old, bo)
    assert got == want
    assert got[0]["uniqueID"] == 0x483D06F5_ECE9AC1D and got[1]["name"] == "wet"
    assert got[0]["selfIlluminanceColor"] == [1.0, 0.5, 0.25]
    assert we.texture_sheet(old, bo) == we.texture_sheet(new, bo)
    assert we.texture_sheet(old, bo)["twoSided"] is True
    assert we.texture_sheet(old, bo)["renderType"] == 1
    assert we.extract_specular(old, bo) == we.extract_specular(new, bo)
    assert we.extract_specular(old, bo) == (20.0, pytest.approx(0.58))
    # read in the wrong byte order: nothing (callers try "<" then ">")
    other = ">" if bo == "<" else "<"
    assert we.texture_sheets(old, other) == [] and we.texture_sheet(old, other) == {}
    assert we.extract_specular(old, other) == (None, None)


def test_sheet_json_is_written_for_the_older_layout(tmp_path):
    for sub, typed in (("old", False), ("new", True)):
        (tmp_path / sub).mkdir()
        we._write_sheet_json(_texture_header("<", typed), tmp_path / sub, "<")
    old = json.loads((tmp_path / "old" / "sheet.json").read_text())
    assert old == json.loads((tmp_path / "new" / "sheet.json").read_text())
    assert old["twoSided"] is True and old["sheets"][0]["name"] == "default"
    we._write_spec_txt(_texture_header(">", False), tmp_path)  # the console carve
    assert (tmp_path / "spec.txt").read_text().split()[0] == "20.0"
    assert json.loads((tmp_path / "sheet.json").read_text())["blendType"] == 2


# ---------------------------------------------------------------------------
# 5. model property bag and sidecar
# ---------------------------------------------------------------------------
def _model_bag(bo, typed, animation=""):
    props = [("animation", "string", animation), ("storeLowestLODInHeader", "truth", 0)]
    props.append(("shadowMeshType", "integer", 2))
    for pair, dist in (("01", 30.0), ("12", 60.0), ("23", 90.0), ("34", 120.0), ("45", 150.0)):
        props += [
            ("lodDistance" + pair, "number", dist),
            ("lodFadeIn" + pair, "number", 2.0),
            ("lodFadeOut" + pair, "number", 5.0 if pair == "01" else 2.0),
        ]
    return _object("ModelRes", props, bo, typed) + bytes(40)


@pytest.mark.parametrize("bo", ["<", ">"])
@pytest.mark.parametrize("typed", [True, False])
def test_model_property_bag_and_lods_in_both_layouts(bo, typed):
    h = _model_bag(bo, typed)
    bag = we.model_property_bag(h, bo)
    assert bag["record_layout"] == ("typed" if typed else "untyped")
    assert bag["properties"]["shadowMeshType"] == 2 and bag["properties"]["animation"] == ""
    assert bag["properties"]["lodDistance23"] == 90.0
    info = we.model_lod_info(h, bo)
    assert [l["max_distance"] for l in info["lods"]] == [30.0, 60.0, 90.0, 120.0, 150.0]
    assert info["lods"][0]["fade_out"] == 5.0 and info["store_lowest_lod_in_header"] is False


@pytest.mark.parametrize("typed", [True, False])
def test_lods_survive_an_animation_path_in_the_bag(typed):
    """The fixed 20-byte stride lost its place behind a string longer than one
    dword: every model with an `animation` path had no LODs (22 in PC Part 2)."""
    h = _model_bag("<", typed, "/art/props/common/curtains/TWM_Curtain_5M_01.animation")
    info = we.model_lod_info(h, "<")
    assert info is not None and len(info["lods"]) == 5 and info["lods"][1]["max_distance"] == 60.0


def test_sidecar_of_a_scan_decoded_model_names_what_is_not_decoded():
    h = _model_bag(">", False)
    assert we.parse_model_header(h, ">") is None  # not the Part 2 header layout
    meta = we.model_meta_scanned(h, ">")
    assert meta["format"] == "watchmen-model-meta/1" and meta["header_decoded"] is False
    assert meta["mesh_source"] == "descriptor scan" and meta["record_layout"] == "untyped"
    assert meta["lod_count"] is None and len(meta["lods"]) == 5
    assert "lod_count" in meta["not_decoded"] and "particle_surfaces" in meta["not_decoded"]
    assert meta["properties"]["lodFadeOut01"] == 5.0
    json.dumps(meta)
    # a header whose bag does not read: no sidecar rather than a guessed one
    assert we.model_meta_scanned(h[:60], ">") is None
    assert we.model_property_bag(b"\x08\0\0\0ModelRes", "<") is None
