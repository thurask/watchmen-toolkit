"""Pass 1, package D (formats): fields the engine reads that the parsers now name.

Synthetic fixtures only.  What each section pins and where it was read:

  1. .sequence         loop mode (0x53cfce / 0x49d705 / 0x49d7fe), hosts_up
                       (0x5411dc), target kind (0x53ccab), linear rules per
                       data type (vtable +0x68)
  2. model node tail   MeshParticleData surfaces (0x561d1c), mesh nodes
                       (0x545927 / 0x542541), model sidecar
  3. block             header @32 / @327 / @328 / @388, font type, inflate by
                       asset type (0x5480fe), trailing blob (0x4e1a59)
  4. .naz              the engine's index key (0x4428fb), compression warning
  5. languages         engine codes, --language names, selection tables
  6. subtitles         key edge cases (0x4da4db), rules, movies (0x4da273)
  7. tables            CHARACTER_BONE_TYPES, reg_dump dispatch kinds (0x47c752)
"""

import argparse
import json
import struct
import zlib

import numpy as np
import pytest

import decode_sequence as ds
import engine_enums as ee
import gen_data
import kapow_props
import parse_model_nodes as pmn
import skeleton_records as sr
import text_assets as ta
import watchmen_extract as we

import test_audio_v2 as au
import test_formats_v2 as tf
import test_phys_v2 as tp

# ---------------------------------------------------------------------------
# 1. .sequence
# ---------------------------------------------------------------------------


def _seq(flags, objects=None):
    objects = objects or [tf._object("Model", [tf._track("visible", 1, [tf._key(0, [1.0])])])]
    return tf._sequence(objects, duration=2.0, flags=flags)


@pytest.mark.parametrize(
    "flags,name",
    [(0, "loop"), (1, "oneshot"), (2, "oneshot_reverse"), (3, "loop_reverse"), (4, "pingpong")],
)
def test_sequence_header_word_is_the_loop_mode(flags, name):
    d = ds.parse_exact(_seq(flags))
    assert (d["loop_mode"], d["loop_mode_name"]) == (flags, name)
    assert d["h1"] == flags  # the older key stays
    assert d["format"] == "kapow-sequence/2"  # additive keys: no format change


def test_sequence_loop_mode_out_of_range_has_no_name():
    d = ds.parse_exact(_seq(7))
    assert d["loop_mode"] == 7 and d["loop_mode_name"] is None


def test_sequence_object_word_is_hosts_up_and_the_target_kind_is_derived():
    one = [tf._track("opacity", 1, [tf._key(0, [1.0], [((-0.1, 1.0), (0.1, 1.0))])])]
    b = _seq(
        4,
        [
            tf._object("Sprite", one, ids=(0x5A787F10, 0x42CAA4A1, 0xA81361BB), flag=1),
            tf._object("TextureSheet", one, path="/art/x/Face.BMP#1", ids=()),
            tf._object("TextureSheet", one, path="/art/x/Face.bmp", ids=()),
            tf._object("Model", one, path="_this_", ids=()),
            tf._object("Model", one, path="Door_Left", ids=()),
            tf._object("Texture", one, path="/art/x/Face.bmp", ids=()),
        ],
    )
    o = ds.parse_exact(b)["objects"]
    assert (o[0]["hosts_up"], o[0]["flag"], o[0]["target_kind"]) == (1, 1, "entity_path")
    assert o[0]["ids"] == ["5a787f10", "42caa4a1", "a81361bb"]
    assert (o[1]["target_kind"], o[1]["texture"], o[1]["sheet_index"]) == (
        "texture_sheet",
        "/art/x/Face.BMP",
        1,
    )
    assert (o[2]["target_kind"], o[2]["sheet_index"]) == ("texture_sheet", -1)
    assert o[3]["target_kind"] == "self" and o[4]["target_kind"] == "name"
    assert o[5]["target_kind"] == "asset" and "sheet_index" not in o[5]
    assert all(x["hosts_up"] == 0 for x in o[1:])


def test_sequence_sheet_index_is_c_atol():
    f = ds.target_fields
    assert f("TextureSheet", "/a.bmp# 12x", [])["sheet_index"] == 12
    assert f("TextureSheet", "/a.bmp#x", [])["sheet_index"] == 0
    assert f("TextureSheet", "/a.bmp#", [])["sheet_index"] == 0
    # the class decides before the ids do (0x53ccab tests TextureSheet first)
    assert f("TextureSheet", "/a.bmp#2", ["00000001"])["target_kind"] == "texture_sheet"


def test_linear_keys_blend_only_number_vector_quaternion():
    """vtable +0x68: number 0x4fa5bb, vector 0x4fbf8d, integer 0x4fac1c
    (a + trunc), every other type the base 0x47fc01 = key A."""
    b = _seq(
        0,
        [
            tf._object(
                "TextBox",
                [
                    tf._track("visible", 2, [tf._key(0, [0.0]), tf._key(1, [1.0])]),
                    tf._track("currentIndex", 2, [tf._key(0, [0.0]), tf._key(1, [-10.0])]),
                    tf._track(
                        "opacity",
                        2,
                        [
                            tf._key(0, [0.0], [((-0.1, 0.0), (0.1, 0.0))]),
                            tf._key(1, [1.0], [((0.9, 1.0), (1.1, 1.0))]),
                        ],
                    ),
                ],
            )
        ],
    )
    truth, integer, number = ds.parse_exact(b)["objects"][0]["tracks"]
    assert (truth["value_type"], integer["value_type"]) == ("truth", "integer")
    assert ds.evaluate(truth, 0.75) == [0.0]  # held; a lerp gave 0.75
    assert ds.evaluate(integer, 0.55) == [-5.0]  # trunc(-5.5), not floor (-6) nor -5.5
    assert ds.evaluate(integer, 0.05) == [0.0]
    assert ds.evaluate(number, 0.25) == pytest.approx([0.25])
    # step and the scanning parser's untyped tracks are untouched
    keys = [{"t": 0.0, "mode": 0, "value": 0.0}, {"t": 1.0, "mode": 0, "value": 2.0}]
    assert ds.evaluate({"type": 2, "keys": keys}, 0.5) == [1.0]
    assert ds.evaluate({"type": 2, "value_type": None, "keys": keys}, 0.5) == [0.0]
    assert ds.evaluate({"type": 2, "value_type": "color", "keys": keys}, 0.5) == [0.0]
    assert ds.evaluate({"type": 1, "value_type": "number", "keys": keys}, 0.5) == [0.0]


def test_play_position_five_modes():
    seq = {"duration": 2.0, "loop_mode": 0}
    pp = ds.play_position
    assert pp(seq, 0.5) == 0.5 and pp(seq, 2.5) == pytest.approx(0.5)  # loop
    assert pp(seq, 2.5, 1) == 2.0 and pp(seq, 0.5, 1) == 0.5  # oneshot stops at the end
    assert pp(seq, 0.5, 2) == 1.5 and pp(seq, 9.0, 2) == 0.0  # starts at the end
    assert pp(seq, 0.5, 3) == 1.5 and pp(seq, 2.5, 3) == pytest.approx(1.5)
    assert pp(seq, 2.5, 4) == pytest.approx(1.5) and pp(seq, 4.5, 4) == pytest.approx(0.5)
    assert pp(seq, 2.5, "pingpong") == pp(seq, 2.5, 4)
    assert pp({"duration": 2.0, "loop_mode": 4}, 2.5) == pytest.approx(1.5)  # the file's mode
    with pytest.raises(ValueError):
        pp(seq, 1.0, 5)


def test_play_position_steps_frames_as_the_engine_does():
    """0x49d7fe: a loop RESETS to 0.0 (the overshoot is dropped), pingpong
    clamps to the end and turns round, loop_reverse jumps back to duration."""
    seq = {"duration": 1.0}
    step = lambda mode, n: ds.play_position(seq, n * 0.3, mode, dt=0.3)
    assert [round(step(0, n), 6) for n in range(1, 6)] == [0.3, 0.6, 0.9, 0.0, 0.3]
    assert [round(step(1, n), 6) for n in range(1, 6)] == [0.3, 0.6, 0.9, 1.0, 1.0]
    assert [round(step(4, n), 6) for n in range(1, 9)] == [0.3, 0.6, 0.9, 1.0, 0.7, 0.4, 0.1, 0.0]
    assert [round(step(3, n), 6) for n in range(1, 6)] == [0.7, 0.4, 0.1, 1.0, 0.7]
    assert [round(step(2, n), 6) for n in range(1, 6)] == [0.7, 0.4, 0.1, 0.0, 0.0]


# ---------------------------------------------------------------------------
# 2. model node tail: particle emission surfaces, mesh nodes
# ---------------------------------------------------------------------------

QUAD = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 0.0, 1.0), (0.0, 0.0, 1.0)]
QUAD_IDX = [0, 1, 2, 2, 3, 0]  # two triangles of area 1.0


def _surface(weights, ids=(-1, -1)):
    tris = [((0.0, -1.0, 0.0), w, i) for w, i in zip(weights, ids)]
    return (tris, QUAD, QUAD_IDX)


@pytest.mark.parametrize("order", ["<", ">"])
def test_surface_keys_class_and_area_weight(order):
    region = tp._tail(order, 0, surfaces=[_surface((1.0, 1.0), (2, 0)), _surface((1.0, 0.5))])
    r = sr.parse_node_tail(region, 0, len(region), order)
    area, other = r["surfaces"]
    assert area["class"] == "MeshParticleData" and other["class"] == "MeshParticleData"
    t = area["tris"][0]
    assert (t["normal"], t["area_weight"], t["material_id"]) == ((0.0, -1.0, 0.0), 1.0, 2)
    assert (t["vec"], t["value"], t["id"]) == (t["normal"], 1.0, 2)  # old keys, one release
    assert area["weight_is_area"] is True and area["weight_sum"] == 2.0
    assert other["weight_is_area"] is False and other["weight_sum"] == 1.5


def test_weight_is_area_tolerance_and_unpaired_meshes():
    tris = lambda *w: [dict(area_weight=x) for x in w]
    v, i = np.array(QUAD, np.float32), np.array(QUAD_IDX, np.uint32)
    assert sr._weight_is_area(tris(1.0005, 0.9995), v, i) is True  # rtol 1e-3
    assert sr._weight_is_area(tris(1.01, 1.0), v, i) is False
    assert sr._weight_is_area(tris(1.0), v, i) is None  # one record, two triangles
    assert sr._weight_is_area([], v, i) is None


def _mesh_region(surfaces=(), submesh=True, groups=1, hulls=0, occluder=False):
    """[f1][parent][mesh section][lists] of a node, engine layout 0x545927."""
    b = struct.pack("<Ii", 0, 3)
    b += struct.pack("<I", 1) + struct.pack("<I", 1 if submesh else 0)
    if submesh:
        b += tf._str("Body") + struct.pack("<II", 1, 0) + bytes([0, 0])
        b += struct.pack("<I", 1) + bytes([0, 0]) + tf._meshbuffer(5, 4, 12)
        b += struct.pack("<I", 3) + b"NXS"  # cooked blob
    b += struct.pack("<I", groups)
    for _ in range(groups):
        b += struct.pack("<I", hulls)
        for _ in range(hulls):
            b += b"\x00" + struct.pack("<I", 0xFFFFFFFF) + tf._meshbuffer(9, 4, 12)
    b += (b"\x01" + tf._meshbuffer(5, 4, 12, flags=0)) if occluder else b"\x00"
    return b + tp._lists_bytes("<", l0=tp.VOLS0[:1], surfaces=list(surfaces))


def test_mesh_node_tail_is_read_on_request():
    region = _mesh_region([_surface((1.0, 1.0))], hulls=2, occluder=True)
    assert sr.parse_node_tail(region, 0, len(region)) is None  # the default is unchanged
    r = sr.parse_node_tail(region, 0, len(region), meshes=True)
    assert r is not None and r["has_mesh"] is True and r["parent"] == 3
    assert r["end"] == len(region) and len(r["volumes"][0]) == 1
    assert len(r["surfaces"]) == 1 and r["surfaces"][0]["weight_is_area"] is True
    aux = pmn.parse_node_aux(region, 0, len(region), meshes=True)
    assert aux["has_mesh"] is True and len(aux["surfaces"]) == 1 and len(aux["joints"]) == 1
    assert pmn.parse_node_aux(region, 0, len(region)) is None
    # it still has to tile the region exactly
    assert sr.parse_node_tail(region, 0, len(region) - 1, meshes=True) is None
    assert sr.parse_node_tail(region + b"\0", 0, len(region) + 1, meshes=True) is None


def test_bone_with_an_empty_shadow_group_is_not_a_mesh_node():
    """Mesh-free bones often carry ONE EMPTY shadow group.  The default reader
    keeps refusing them (its callers rely on that); meshes=True reads them."""
    region = _mesh_region(submesh=False, groups=1, hulls=0)
    assert sr.parse_node_tail(region, 0, len(region)) is None
    r = sr.parse_node_tail(region, 0, len(region), meshes=True)
    assert r["has_mesh"] is False and len(r["volumes"][0]) == 1 and r["surfaces"] == []


def _model_with_surface(weights=(1.0, 1.0), ids=(2, 0)):
    h, s = tf._model([{"name": "Barrel", "lods": [[("Body", 0, 5, 0.0, 1)]]}], ["/art/t/a.bmp"])
    lists = tp._lists_bytes("<", surfaces=[_surface(weights, ids)])
    assert h[-36:] == b"\0" * 36  # three empty lists + the 24-byte tail
    return h[:-36] + lists + b"\0" * 24, s


def test_model_surfaces_reach_the_sidecar():
    h, _s = _model_with_surface()
    M = we.parse_model_header(h)
    assert M["parts"][0]["surface_count"] == 1
    (surf,) = we.model_surfaces(h)
    assert (surf["node"], surf["part"], surf["surface"]) == ("Barrel", 0, 0)
    assert [t["material_id"] for t in surf["tris"]] == [2, 0]
    meta = we.model_meta(h)
    assert meta["format"] == "watchmen-model-meta/1"
    assert meta["particle_surfaces"] == [
        {
            "node": "Barrel",
            "part": 0,
            "class": "MeshParticleData",
            "triangles": 2,
            "vertices": 4,
            "material_ids": {"0": 1, "2": 1},
            "weight_sum": 2.0,
            "weight_is_area": True,
            "weight_is_unit": True,  # two unit-area triangles with weight 1.0
        }
    ]
    assert "SurfaceSpawner" in meta["particle_surface_note"]
    json.dumps(meta)  # plain JSON
    phys = pmn.model_physics(h)
    assert len(phys["nodes"][0]["surfaces"]) == 1


def test_model_without_surfaces_has_no_new_sidecar_key():
    h, _s = tf._model([{"name": "Wall", "lods": [[("Body", 0, 5, 0.0, 1)]]}], ["/art/t/a.bmp"])
    assert we.model_surfaces(h) == []
    meta = we.model_meta(h)
    assert "particle_surfaces" not in meta and "particle_surface_note" not in meta
    assert pmn.model_physics(h)["nodes"][0]["surfaces"] == []
    assert we.model_surfaces(b"not a model") is None


# ---------------------------------------------------------------------------
# 3. block header, asset types, compression, trailing blob
# ---------------------------------------------------------------------------

RAW328 = bytes.fromhex("0a883f59")


def _real_header(h, signature=0x79D3E0DA, low_violence=0):
    b = bytearray(h)
    struct.pack_into("<I", b, 32, signature)
    b[328:332] = RAW328
    b[388] = low_violence
    return bytes(b)


def test_block_header_signature_is_at_32_and_328_is_raw_bytes():
    h, _s = tf._block([("/a.bmp", tf._TEX, b"HDR-A", None)])
    hd = we.parse_block_header(_real_header(h))
    assert hd["version_signature"] == 0x79D3E0DA  # was the u32 at 328
    assert hd["unknown_328"] == RAW328 and hd["unknown_327"] == 2
    assert hd["low_violence"] is False
    assert we.parse_block_header(_real_header(h, low_violence=1))["low_violence"] is True
    # the fields around it are untouched
    assert hd["num_entries"] == 1 and hd["fragment_size"] == 8


def test_block_header_328_does_not_follow_the_byte_order():
    """@32 is a platform-order u32; the four bytes at 328 are the same on the
    big-endian consoles."""
    h, _s = tf._block([("/a.bmp", tf._TEX, b"HDR-A", None)])
    b = bytearray(_real_header(h))
    struct.pack_into(">I", b, 32, 0x79D3E0DA)
    hd = we.parse_block_header(bytes(b), order=">")
    assert hd["version_signature"] == 0x79D3E0DA and hd["unknown_328"] == RAW328


def test_font_and_terrain_coloring_asset_types_are_named():
    assert we.asset_type_name(0x62F2722A) == "font"
    assert we.asset_type_name(0xF1FDBE49) == "terrainColoringAsset"
    assert kapow_props.name_hash("font") == 0x62F2722A
    assert kapow_props.name_hash("terrainColoringAsset") == 0xF1FDBE49
    h, _s = tf._block([("/art/Fonts/DaveGibbons40.font", 0x62F2722A, zlib.compress(b"F"), None)])
    (e,) = we.parse_block_toc(h)[0]
    assert e.type_name == "font" and e.compressed is True


def test_blobs_inflate_by_asset_type_not_by_their_first_byte():
    packed = zlib.compress(b"PAYLOAD" * 9)
    assert packed[0] == 0x78
    # mediastream is the one raw type (0x554a2e): its bytes are never inflated
    assert we._maybe_inflate(packed, "mediastream") == packed
    assert we.asset_compressed("mediastream") is False
    # every other type is zlib whatever the first byte is
    co = zlib.compressobj(6, zlib.DEFLATED, 12)
    small_window = co.compress(b"PAYLOAD" * 9) + co.flush()
    assert small_window[0] != 0x78
    assert we._maybe_inflate(small_window, "sound") == b"PAYLOAD" * 9
    assert we._maybe_inflate(small_window, "ModelEffects(ModelRes)") == b"PAYLOAD" * 9
    assert we.asset_compressed("TextureEffects(Texture)") is True
    # unknown type: sniffed, as before
    assert we._maybe_inflate(packed) == b"PAYLOAD" * 9
    assert we._maybe_inflate(small_window) == small_window
    assert we._maybe_inflate(b"RAW") == b"RAW" and we.asset_compressed("") is None


def test_a_blob_that_should_inflate_and_does_not_is_reported():
    got = []
    assert we._maybe_inflate(b"\x78\x9cgarbage", "Texture", got.append) == b"\x78\x9cgarbage"
    assert len(got) == 1
    h, s = tf._block(
        [
            ("/a.bmp", tf._TEX, b"NOT-ZLIB", zlib.compress(b"stream")),
            ("/m.wav", we._name_hash("mediastream"), b"RAWHDR", None),
        ]
    )
    msgs = []
    out = list(we.extract_block(h, s, report=msgs.append))
    (a, ah, ast), (m, mh, _mst) = out
    assert ah == b"NOT-ZLIB" and ast == b"stream" and a.inflate_failed == ["header"]
    assert len(msgs) == 1 and "/a.bmp" in msgs[0] and "header" in msgs[0]
    assert mh == b"RAWHDR" and m.inflate_failed == [] and m.compressed is False
    assert [e.name for e, _h, _s in we.extract_block(h, s)] == ["/a.bmp", "/m.wav"]


def _stream_set(name, entries):
    b = struct.pack("<8f", -1, -2, -3, 0, 1, 2, 3, 0) + tf._str(name) + struct.pack("<I", 7)
    b += struct.pack("<I", len(entries))
    for th, nm, pairs in entries:
        b += struct.pack("<I", th) + tf._str(nm)
        b += b"".join(struct.pack("<II", *p) for p in pairs)
    return b


def test_block_trailer_two_empty_tables():
    h, _s = tf._block([("/a.bmp", tf._TEX, b"HDR-A", None)])
    t = we.parse_block_trailer(h)
    assert t == {"auto_stream_sets": [], "manual_stream_sets": [], "size": 8, "end": len(h)}


def test_block_trailer_stream_sets():
    h, _s = tf._block([("/a.bmp", tf._TEX, b"HDR-A", None)])
    pairs = [(16 * k, 100 + k) for k in range(6)]
    blob = struct.pack("<I", 1) + _stream_set("/lv/a.block_s_z", [(tf._TEX, "/x.bmp", pairs)])
    blob += struct.pack("<I", 1) + struct.pack("<I2I", 2, 0xAABBCCDD, 0x11223344)
    blob += _stream_set("/lv/b.block_s_z", [])
    b = bytearray(h[:-8] + blob)
    struct.pack_into("<I", b, 348, len(blob))
    t = we.parse_block_trailer(bytes(b))
    (auto,), (manual,) = t["auto_stream_sets"], t["manual_stream_sets"]
    assert auto["stream_file"] == "/lv/a.block_s_z" and auto["min"] == (-1.0, -2.0, -3.0, 0.0)
    assert auto["entries"] == [
        {"type_hash": tf._TEX, "type": "Texture", "name": "/x.bmp", "streams": pairs}
    ]
    assert manual["node_path"] == ["aabbccdd", "11223344"] and manual["entries"] == []
    assert t["end"] == len(b) and t["size"] == len(blob)
    with pytest.raises(ValueError):
        we.parse_block_trailer(bytes(b[:-3]))


# ---------------------------------------------------------------------------
# 4. .naz
# ---------------------------------------------------------------------------


def _rotr2(b):
    return bytes(((c >> 2) | (c << 6)) & 0xFF for c in b)


def _naz(tmp_path, entries):
    """entries: [(name, data, method)] -> path of a .naz in the layout
    naz_entries reads (EOCD magic 0x16ED5B50, rotated names)."""
    body, cd = b"", b""
    for name, data, method in entries:
        nm = _rotr2(name.encode())
        hoffs = len(body)
        body += b"\0" * we._LFH + nm + data
        cd += struct.pack(
            we._CD_FMT,
            we.NAZ_LIST,
            0,
            0,
            0,
            len(data),
            len(data),
            len(nm),
            0,
            0,
            0,
            0,
            0,
            hoffs,
            0,
            0,
            0,
            method,
        )
        cd += nm
    eocd = struct.pack(we._EOCD_FMT, we.NAZ_HEAD, 0, 0, 0, len(entries), len(cd), len(body), 0)
    p = tmp_path / "game.naz"
    p.write_bytes(body + cd + eocd)
    return p


def test_naz_key_is_the_crc_of_the_lower_cased_slash_name():
    assert we.naz_key("Data\\Levels/A.BLOCK_h_z") == kapow_props.kapow_hash(
        "data/levels/a.block_h_z"
    )
    assert we.naz_key("a") != kapow_props.name_hash("a")  # raw CRC, no 0xDF fold


def test_naz_entries_carry_the_key_and_warn_about_compressed_entries(tmp_path):
    p = _naz(tmp_path, [("Data/A.block_h_z", b"AAAA", 0), ("Data/B.bin", b"BB", 8)])
    warned = []
    a, b = list(we.naz_entries(p, warn=warned.append))
    assert (a.name, a.compr, a.key) == ("Data/A.block_h_z", 0, we.naz_key("data/a.block_h_z"))
    assert we.naz_read(p, a) == b"AAAA"
    assert len(warned) == 1 and "Data/B.bin" in warned[0] and "stored" in warned[0]
    assert [e.name for e in we.naz_entries(p)] == ["Data/A.block_h_z", "Data/B.bin"]  # no warn
    loose = tmp_path / "files" / "derived_pc"
    loose.mkdir(parents=True)
    (loose / "x.block_h_z").write_bytes(b"x")
    assert [e.key for e in we.naz_entries(tmp_path / "files")] == [None]


# ---------------------------------------------------------------------------
# 5. languages
# ---------------------------------------------------------------------------


def test_engine_language_codes():
    assert ta.ENGINE_CODES == ("uk", "fr", "it", "de", "es", "dk")
    assert ta.LANGUAGE_CODES == ("en", "fr", "it", "de", "es", "da")
    assert [n for _i, n, _c in ta.LANGUAGES] == [n for n, _e, _c in we.BLOCK_LANGUAGE_NAMES]
    assert tuple(e for _n, e, _c in we.BLOCK_LANGUAGE_NAMES) == ta.ENGINE_CODES
    assert tuple(c for _n, _e, c in we.BLOCK_LANGUAGE_NAMES) == ta.LANGUAGE_CODES
    j = ta.rows_json("/Localize/Menu_uk_pc.txt", [("k", "v")], 3)
    assert j["language"] == {"slot": 3, "name": "German", "code": "de", "engine_code": "de"}
    assert ta.rows_json("/x.txt", [], 0)["language"]["engine_code"] == "uk"


def test_language_option_takes_names_and_codes():
    arg = we._language_arg
    assert arg("german") == arg("3") == arg("de") == arg("GERMAN") == 3
    assert arg("english") == arg("uk") == arg("en") == arg("0") == 0
    assert arg("danish") == arg("dk") == arg("da") == 5
    assert [arg(x) for x in ("french", "italian", "spanish")] == [1, 2, 4]
    for bad in ("6", "-1", "xx", "", "deutsch"):
        with pytest.raises(argparse.ArgumentTypeError):
            arg(bad)
    assert we.language_slot("es") == 4 and we.language_slot("klingon") is None


def test_selection_tables():
    sel = ta.SELECTION
    assert sel["fallback_slot"] == 0
    pc = sel["pc"]["language_ids"]
    assert pc["1"] == ["0x040c", "0x080c", "0x0c0c", "0x100c", "0x140c", "0x180c"]
    assert pc["2"] == ["0x0410", "0x0810"] and len(pc["3"]) == 5
    assert len(pc["4"]) == 20 and (pc["4"][0], pc["4"][-1]) == ("0x040a", "0x500a")
    assert "5" not in pc and sel["pc"]["unreachable_slots"] == [5]
    assert "0x0406" not in sum(pc.values(), [])  # Danish falls through to English on PC
    assert sel["x360"]["language_ids"] == {"0": [1], "1": [4], "2": [6], "3": [3], "4": [5]}
    assert sel["ps3"]["language_ids"] == {"1": [2], "2": [5], "3": [4], "4": [3], "5": [14]}


# ---------------------------------------------------------------------------
# 6. subtitles
# ---------------------------------------------------------------------------


def test_subtitle_key_cuts_are_case_sensitive_and_anywhere():
    k = ta.subtitle_key
    assert k("/a/_uk.wav") == "" and k("/a/b.c/Line") == "Line"
    assert k("/s/Foo_UK.wav") == "Foo_UK" and k("/s/A_uk_B_pc_C.wav") == "A"
    assert ta.key_hash("Foo_UK") == ta.key_hash("foo_uk")  # the lookup folds A-Z
    assert "case-sensitive" in ta._EV["subtitle_key"] and "streamingSound" in ta._EV["subtitle_key"]


def test_subtitle_key_grammar_edge_cases():
    p = ta.parse_subtitle_key
    # 0 <= end < start: the engine drops the end (0x4da710); end == 0 counts
    assert p("L#00:05:000->00:01:000") == ("L", 5.0, None)
    assert p("L#00:05:000->00:00:000") == ("L", 5.0, None)
    assert p("L#00:05:000->00:05:000") == ("L", 5.0, 5.0)
    assert p("#00:01:000->00:02:000") == ("", 1.0, 2.0)
    assert p("00:01:000->00:02:500") == ("", 1.0, 2.5)
    long_name = "N" * 200  # nothing is truncated (the engine keeps copying)
    assert p(long_name + "#00:01:000->00:02:000") == (long_name, 1.0, 2.0)
    assert p("L#00:01:000 ->00:02:000") == ("L", None, 2.0)  # 10 characters: not a time
    assert p("") is None and p("Name") == ("Name", None, None)


def test_shown_from_is_the_latest_end_of_all_earlier_rows():
    lines = [(1.0, 10.0, 0), (2.0, 3.0, 1), (9.0, 12.0, 2), (20.0, 26.528, 3), (25.53, 30.435, 4)]
    got = ta.shown_from(lines)
    assert got == [(1.0, True), (10.0, False), (10.0, True), (20.0, True), (26.528, True)]
    # the same answer from the engine's walk, sampled every millisecond
    for (start, end, i), (frm, shown) in zip(lines, got):
        seen = [t / 1000.0 for t in range(0, 31000) if ta.subtitle_index(lines, t / 1000.0) == i]
        assert bool(seen) == shown
        if seen:
            assert seen[0] == pytest.approx(frm, abs=0.0011)


CUT_KEYS = [
    "00:01:000->00:10:000",
    "00:02:000->00:03:000",
    "00:09:000->00:12:000",
    "00:20:000->00:26:528",
    "00:25:530->00:30:435",
]
LANGS = ["English", "Français", "Italiano", "Deutsch", "Español"]


@pytest.fixture
def movie_extract(tmp_path):
    """A cutscene table, its SubtitleSlot and three MoviePlayerCtrl nodes: one
    with the slot (and a link to the next), one logo without, one whose slot
    spells the property `textRes`."""
    cut = [ta.build_textres([(k, "%s %d" % (s, i)) for i, k in enumerate(CUT_KEYS)]) for s in LANGS]
    cut.append(cut[0])
    other = [ta.build_textres([("00:00:000->00:01:000", s)]) for s in LANGS]
    other.append(other[0])
    text_hash = we._name_hash("textRes")
    h, s_ = tf._block(
        [("/main.bmp", tf._TEX, b"MAIN", None)],
        [
            ("/Localize/Cutscene08b_uk.txt", text_hash, cut, None),
            ("/Localize/Cutscene1_uk.txt", text_hash, other, None),
        ],
    )
    files = tmp_path / "files"
    files.mkdir()
    (files / "g.block_h_z").write_bytes(h)
    (files / "g.block_s_z").write_bytes(s_)
    out = tmp_path / "out"
    ta.extract_text(str(files), str(out), log=lambda *a: None)
    db = au.Frag("TNT/Fragments/GameEssentials/MovieDb.fragment")
    box = db.add("TextBox", "MovieSubtitles")
    slot = db.add(
        "SubtitleSlot", "Cut08B", textres="/localize/cutscene08b_UK.txt", defaultDuration=5.0
    )
    slot2 = db.add(
        "SubtitleSlot", "Cut01", textRes="/Localize/Cutscene1_uk.txt", defaultDuration=5.0
    )
    logo = db.add(
        "MoviePlayerCtrl",
        "DeveloperMovie",
        movie="/Art/cutscenes/Logo.bik",
        volume=1.0,
        isLocalized=False,
        subtitleTextBox={"ref": box},
        subtitleSlot={"etag": 1},
        m_econtinuelink={"etag": 1},
        m_tskiplink=False,
    )
    db.add(
        "MoviePlayerCtrl",
        "Cutscene08B",
        movie="/Art/cutscenes/Cutscene08B.bik",
        volume=0.7,
        isLocalized=False,
        subtitleTextBox={"ref": box},
        subtitleSlot={"ref": slot},
        m_econtinuelink={"ref": logo},
        m_tskiplink=True,
    )
    db.add(
        "MoviePlayerCtrl",
        "Cutscene01",
        movie="/Art/cutscenes/Cutscene01.bik",
        subtitleSlot={"ref": slot2},
    )
    db.write(out)
    return out


def test_textmeta_movies_section(movie_extract):
    m = ta.build(str(movie_extract))
    assert m["format"] == "watchmen-text-meta/1"
    logo, cut, one = m["movies"]
    rel = "TNT/Fragments/GameEssentials/MovieDb.fragment"
    assert logo["name"] == "DeveloperMovie" and logo["ref"][0] == rel
    assert (logo["table"], logo["lines"], logo["subtitle_slot"]) == (None, [], None)
    assert logo["subtitle_text_box"]["name"] == "MovieSubtitles"
    assert (logo["continue_link"], logo["skip_skips_link"]) == (None, False)
    assert cut["movie"] == "/Art/cutscenes/Cutscene08B.bik" and cut["volume"] == 0.7
    assert cut["localized_audio"] is False and cut["skip_skips_link"] is True
    assert cut["continue_link"] == {
        "ref": logo["ref"],
        "name": "DeveloperMovie",
        "movie": "/Art/cutscenes/Logo.bik",
    }
    # the table is the slot's textres, matched to the asset whatever its letter case
    assert cut["table"] == "/Localize/Cutscene08b_uk.txt" and cut["default_duration_s"] == 5.0
    assert cut["subtitle_slot"]["name"] == "Cut08B"
    assert [ln["index"] for ln in cut["lines"]] == [0, 1, 2, 3, 4]
    assert [(ln["from_s"], ln["to_s"]) for ln in cut["lines"]] == [
        (1.0, 10.0),
        (2.0, 3.0),
        (9.0, 12.0),
        (20.0, 26.528),
        (25.53, 30.435),
    ]
    # row 2: an EARLIER row (0, ends 10.0), not the previous one (1, ends 3.0), delays it
    assert [ln["shown_from_s"] for ln in cut["lines"]] == [1.0, 10.0, 10.0, 20.0, 26.528]
    assert [ln["shown"] for ln in cut["lines"]] == [True, False, True, True, True]
    assert cut["lines"][4]["text"] == {
        c: "%s 4" % s for c, s in zip(("en", "fr", "it", "de", "es"), LANGS)
    }
    # a slot whose property is spelled as the engine registers it (textRes)
    assert one["table"] == "/Localize/Cutscene1_uk.txt" and len(one["lines"]) == 1
    assert one["volume"] is None and one["localized_audio"] is None
    assert one["default_duration_s"] == 5.0
    assert m["assets"]["/Localize/Cutscene08b_uk.txt"]["movies"] == [
        {"ref": cut["ref"], "name": "Cutscene08B"}
    ]
    assert m["assets"]["/Localize/Cutscene1_uk.txt"]["kind"] == "timed_subtitles"
    assert "movie_subtitles" in m["evidence"] and "movies" in m["conventions"]
    assert "2 with subtitles" in ta.summary(m)


def test_textmeta_rules_selection_and_open_points(movie_extract):
    m = ta.build(str(movie_extract))
    rules = m["subtitles"]["rules"]
    assert set(rules) == {"entry_routes", "other_starts", "request", "priority", "option", "clock"}
    assert len(rules["entry_routes"]) == 2 and "0x831bb8" in rules["entry_routes"][0]
    assert "off by default" in rules["option"] and "0.1 s" in rules["clock"]
    assert m["selection"] == ta.SELECTION
    assert [x["engine_code"] for x in m["languages"]] == list(ta.ENGINE_CODES)
    open_points = " | ".join(m["not_established"])
    assert "which sound wins" not in open_points and "pairing" not in open_points
    # the first-frame point is read on both Part 1 consoles; PC Part 1 has no executable
    assert "SoundDef.Active on PC Part 1 (no executable)" in open_points
    assert "0x82b21808" in open_points
    assert "subtitle option hides cutscene subtitles" in open_points
    assert "case-insensitive" not in m["conventions"]["subtitle"]
    json.dumps(m)


def test_text_index_lists_engine_codes(movie_extract):
    idx = json.loads((movie_extract / "text" / "index.json").read_text(encoding="utf-8"))
    assert [x["engine_code"] for x in idx["languages"]] == list(ta.ENGINE_CODES)
    assert [x["code"] for x in idx["languages"]] == list(ta.LANGUAGE_CODES)


# ---------------------------------------------------------------------------
# 7. tables
# ---------------------------------------------------------------------------


def test_character_bone_types_family():
    fam = ee.family("CHARACTER_BONE_TYPES")
    assert sorted(fam) == list(range(23))
    assert (fam[0], fam[11], fam[17], fam[18], fam[22]) == (
        "Head",
        "L Foot",
        "R Foot",
        "GamePivot",
        "RUpArmTwist",
    )
    raw = ee.data()["families"]["CHARACTER_BONE_TYPES"]
    assert raw["out_of_range"] == 18 and raw["prefix"] is None
    # 34 registered families (ACHIEVEMENTS, PLAYABLE_CHARACTERS, GAME_MODES, AIAGENTFACTION
    # among them) + this one
    assert len(ee.families()) == 35
    assert ee.name("CHARACTER_TYPES", 0) is not None  # the neighbours are intact


def test_add_dispatch_kinds():
    """0x47c752: one version owned by _root -> 0, by a state -> 1; several
    versions without a root one -> 2 (index -1), with one -> 3 (its index)."""

    def cmd(name, slot, owner, hsh=None, kind=3):
        return {"name": name, "slot": slot, "arg3": owner, "hash": hsh, "kind": kind}

    c = {
        "name": "X",
        "props": [],
        "commands": [
            cmd("StateA", "state", -1, kind=1),
            cmd("_root", "state", -1),
            cmd("command_root_only", "command", 1, "0x1"),
            cmd("command_state_only", "command", 0, "0x2"),
            cmd("StateB", "state", -1, kind=1),
            cmd("command_two_states", "command", 0, "0x3"),
            cmd("command_two_states", "command", 4, "0x3"),
            cmd("command_override", "command", 0, "0x4"),
            cmd("command_override", "command", 1, "0x4"),
            cmd("Helper", "method", -1, kind=1),
        ],
    }
    (out,) = gen_data.add_dispatch([c])
    assert out["root_index"] == 1 and list(out)[-2:] == ["props", "commands"]
    got = [(x["dispatch_kind"], x["dispatch_index"]) for x in out["commands"]]
    assert got == [
        (None, None),
        (None, None),
        (0, 2),
        (1, 3),
        (None, None),
        (2, -1),
        (2, -1),
        (3, 8),
        (3, 8),
        (None, None),
    ]
    assert [x["visibility"] for x in out["commands"]] == [x["kind"] for x in out["commands"]]


def test_shipped_reg_dump_dispatch_totals():
    import engine_schema as es

    reg = es.reg()
    entries, rows = {0: 0, 1: 0, 2: 0, 3: 0}, 0
    for c in reg:
        roots = [i for i, x in enumerate(c["commands"]) if x["name"] == "_root"]
        assert roots == [c["root_index"]]  # exactly one _root per class
        seen = set()
        for x in c["commands"]:
            rows += 1
            assert x["visibility"] == x["kind"]
            assert (x["dispatch_kind"] is None) == (x["hash"] is None)
            if x["hash"] is not None and x["hash"] not in seen:
                seen.add(x["hash"])
                entries[x["dispatch_kind"]] += 1
            if x["dispatch_kind"] == 3:
                assert c["commands"][x["dispatch_index"]]["arg3"] == c["root_index"]
    assert rows == 6630
    assert entries == {0: 3166, 1: 295, 2: 61, 3: 134}
