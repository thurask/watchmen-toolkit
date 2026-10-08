"""Texture layers are named by their FILE SLOT; animation block; cube face order.

The loader stores file slot i at frame +4*i and the sheet asks by engine layer
(0x5382aa, 0x49be2d): slot 3 is the glow map and slot 4 the height map.  Until
this change a slot-3 map without a slot-2 map was written `_specMap_` and a
slot-4 map `_specSize_`.  Synthetic headers only."""

import json
import struct

import pytest

import watchmen_extract as we

import test_formats_v2 as tf
import test_vcolor as tv

pytest.importorskip("PIL")


def _names(d):
    return sorted(p.name for p in d.glob("*.png"))


def _dxt1(w=4, h=4, mips=1):
    return tf._tex_desc(w, h, 5, mips)


def _l8(w=4, h=4, mips=1):
    return tf._tex_desc(w, h, 3, mips)


# ---------------------------------------------------------------------------
# labels
# ---------------------------------------------------------------------------
def test_slot_tables_are_the_engines():
    assert we.TEXTURE_SLOT_LABELS == {
        0: "diffuse",
        1: "normal",
        2: "specMap",
        3: "glow",
        4: "height",
        5: "fallOff",
        6: "ambOcc",
        7: "specSize",
    }
    # engine layer -> file slot (accessors 0x49bcbe ... 0x49bdff)
    assert we.TEXTURE_LAYER_SLOTS == {0: 0, 1: 0, 2: 1, 3: 4, 4: 2, 5: 3, 6: 5, 7: 6, 8: 7}
    assert sorted(set(we.TEXTURE_LAYER_SLOTS.values())) == list(range(8))


@pytest.mark.parametrize("slot, label", sorted(we.TEXTURE_SLOT_LABELS.items()))
def test_a_layer_that_knows_its_slot_is_labelled_by_it(slot, label):
    # the format says something else on purpose: slot wins
    layers = [{"slot": 0, "enum": 5}, {"slot": slot, "enum": 3 if slot in (2, 3) else 5}]
    assert we.texture_layer_label(layers, 1) == label


def test_glow_without_a_specular_map_and_height_beside_specsize():
    hdr = tf._tex_header([({0: _dxt1(), 3: _dxt1()}, "/data/art/Neon.bmp")])
    plan = we.plan_texture_layers(hdr, 16)
    assert plan.get("exact")
    assert [we.texture_layer_label(plan["layers"], j) for j in range(2)] == ["diffuse", "glow"]
    hdr = tf._tex_header(
        [({0: _dxt1(), 2: _dxt1(), 4: _l8(), 7: _l8()}, "/data/art/Ground_Asphalt.bmp")]
    )
    plan = we.plan_texture_layers(hdr, 8 + 8 + 16 + 16)
    labels = [we.texture_layer_label(plan["layers"], j) for j in range(4)]
    assert labels == ["diffuse", "specMap", "height", "specSize"]


def test_layers_without_a_slot_keep_the_format_rule():
    """The stride walk and the drift rescue see formats only."""
    L = [{"enum": 5}, {"enum": 9}, {"enum": 5}, {"enum": 5}, {"enum": 3}]
    assert [we.texture_layer_label(L, j) for j in range(5)] == [
        "diffuse",
        "normal",
        "specMap",
        "glow",
        "specSize",
    ]


def test_pc_carve_writes_the_slot_names(tmp_path):
    hdr = tf._tex_header([({0: _dxt1(), 3: _dxt1()}, "/data/art/Neon.bmp")])
    assert we.carve_texture(bytes(16), hdr, tmp_path / "neon", lambda *a: None)
    assert _names(tmp_path / "neon") == ["0_diffuse_4x4_DXT1.png", "1_glow_4x4_DXT1.png"]
    hdr = tf._tex_header([({0: _dxt1(), 4: _l8()}, "/data/art/Floor.bmp")])
    assert we.carve_texture(bytes(8 + 16), hdr, tmp_path / "floor", lambda *a: None)
    assert _names(tmp_path / "floor") == ["0_diffuse_4x4_DXT1.png", "1_height_4x4_L8.png"]
    # a height map is not a specular-power map: the lookups by label do not find it
    assert we._find_layer(tmp_path / "floor", "specSize") is None
    assert we._find_layer(tmp_path / "floor", "height") is not None
    assert we._find_layer(tmp_path / "neon", "specMap") is None
    assert we._find_layer(tmp_path / "neon", "glow") is not None


# ---------------------------------------------------------------------------
# animation block
# ---------------------------------------------------------------------------
def _cycle(items, steps=None, subs=()):
    b = struct.pack("<3I", 0, 1, 2)
    steps = [(0, k) for k in range(len(items))] if steps is None else steps
    b += struct.pack("<I", len(steps)) + b"".join(struct.pack("<2I", *s) for s in steps)
    b += struct.pack("<I", len(items)) + b"".join(struct.pack("<5I", *i) for i in items)
    return b + struct.pack("<I", len(subs)) + b"".join(subs)


def _animated(tail, frames=3, sheet=True):
    fr = {0: tf._tex_desc(4, 4, 1, 1, alpha=1)}
    hdr = tf._tex_header([(fr, "/data/f%d.bmp" % k) for k in range(frames)], anim=1)
    hdr = hdr[:-40] + tail
    if sheet:
        hdr += b"".join(
            tv._prop(0x1DA7D3DD, n, t, v)
            for n, t, v in (("renderType", "integer", 0), ("twoSided", "truth", 1))
        )
    return hdr + b"\0" * 24


def test_animation_block_is_read_and_the_end_moves_past_it():
    items = [(0, 0, 65, 65, 7), (1, 1, 65, 65, 8), (2, 2, 40, 90, 9)]
    sub = _cycle([(0, 2, 10, 10, 1)])
    tail = struct.pack("<I", 0xBEEF) + _cycle(items, steps=[(0, 0), (0, 1), (1, 0)], subs=[sub])
    hdr = _animated(tail, sheet=False)
    ex = we.parse_texture_frames(hdr)
    assert ex["anim"] is True and ex["end"] == len(hdr) - 24
    t = ex["anim_tail"]
    assert t["serial"] == 0xBEEF and t["cycle"]["head"] == [0, 1, 2]
    assert t["cycle"]["steps"] == [
        {"sub_cycle": False, "index": 0},
        {"sub_cycle": False, "index": 1},
        {"sub_cycle": True, "index": 0},
    ]
    assert t["cycle"]["items"][2] == {
        "frame_min": 2,
        "frame_max": 2,
        "time_min_ms": 40,
        "time_max_ms": 90,
        "id": 9,
    }
    assert len(t["cycle"]["sub_cycles"]) == 1
    # a fixed frame for a fixed time gets a time; a random time or a frame range does not
    assert we.texture_frame_ms(t, 3) == [65, 65, None]
    assert we.texture_frame_ms({"cycle": {"items": []}}, 2) == [None, None]
    assert we.texture_frame_ms(None, 2) == [None, None]
    # the layer plan is the one the frames give, as before
    assert we.plan_texture_layers(hdr, 3 * 64)["kind"] == "anim"


def test_a_block_that_does_not_read_leaves_the_frames_standing():
    tail = struct.pack("<I", 1) + struct.pack("<3I", 0, 0, 0) + struct.pack("<I", 0x7FFFFFFF)
    ex = we.parse_texture_frames(_animated(tail, sheet=False))
    assert ex["anim"] is True and ex["anim_tail"] is None and len(ex["frames"]) == 3
    # no block at all (a still texture)
    still = tf._tex_header([({0: _dxt1()}, "/data/a.bmp")])
    assert we.parse_texture_frames(still)["anim_tail"] is None


def test_sheet_json_carries_the_animation_and_the_frame_times(tmp_path):
    tail = struct.pack("<I", 3) + _cycle([(k, k, 65, 65, k) for k in range(3)])
    we._write_sheet_json(_animated(tail), tmp_path)
    d = json.loads((tmp_path / "sheet.json").read_text())
    assert d["frame_ms"] == [65, 65, 65] and d["animation"]["serial"] == 3
    assert d["twoSided"] is True and "cubeFaceOrder" not in d
    # random times: the block is written, no per-frame time is claimed
    out = tmp_path / "r"
    out.mkdir()
    tail = struct.pack("<I", 3) + _cycle([(0, 2, 30, 90, 0)])
    we._write_sheet_json(_animated(tail), out)
    d = json.loads((out / "sheet.json").read_text())
    assert "frame_ms" not in d and d["animation"]["cycle"]["items"][0]["frame_max"] == 2


# ---------------------------------------------------------------------------
# cube maps
# ---------------------------------------------------------------------------
def test_cube_sheet_json_states_the_face_order(tmp_path):
    assert we.CUBE_FACE_ORDER == ("+X", "-X", "+Y", "-Y", "+Z", "-Z")
    hdr = tf._tex_header([({0: tf._tex_desc(4, 4, 5, 1, typ=2)}, "/data/c_cubemap.bmp")])
    hdr += tv._prop(0x1DA7D3DD, "renderType", "integer", 0) + b"\0" * 24
    we._write_sheet_json(hdr, tmp_path)
    d = json.loads((tmp_path / "sheet.json").read_text())
    assert d["cubeFaceOrder"] == ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
    flat = tf._tex_header([({0: _dxt1()}, "/data/a.bmp")])
    flat += tv._prop(0x1DA7D3DD, "renderType", "integer", 0) + b"\0" * 24
    out = tmp_path / "flat"
    out.mkdir()
    we._write_sheet_json(flat, out)
    assert "cubeFaceOrder" not in json.loads((out / "sheet.json").read_text())
