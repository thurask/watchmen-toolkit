"""Pass 3, work package H: the formats that were raw-only or partly decoded.

    .font                   font_asset: descriptor, inline atlas, FontBuffer fields, glyphs
    .scene                  a Fragment; `scene` summary; written by extract
    .terrain                terrain_asset: whole header (was 74-95% `tail_bytes`), stream
                            walk, height / layer maps, surface GLB
    .terraincoloringasset   terrain_asset: header + image
    .detailmesh             the 25 (24) bytes after the property bag

Synthetic fixtures only, built here (the property-bag, block and fragment builders of
the pass 2 tests are reused)."""

import json
import os
import struct
import sys
import zlib

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import font_asset as fa
import kapow_json as kj
import kapow_props as kp
import terrain_asset as ta
import watchmen_extract as we

import test_p2_fragment as tf
import test_p2_part1 as p1

from conftest import parse_glb


# ---------------------------------------------------------------------------
# .font
# ---------------------------------------------------------------------------
def _font_doc(bo="<", size=0, glyphs=3):
    return {
        "format": fa.FORMAT,
        "order": bo,
        "has_data": True,
        "texture": {
            "width": 4,
            "height": 2,
            "enum": 1,
            "x": 0,
            "type": 1,
            "alpha": True,
            "mips": 1,
            "size": size,
        },
        "glyph_height": 2,
        "b04": 0,
        "b38": 0,
        "b3c": 0,
        "v28": [0.0, 0.0],
        "v30": [1.0, 1.0],
        "glyph_height_v": 0.5,
        "f24": 0.0,
        "glyphs": [
            {
                "code": 65 + i,
                "offset": [0.0, 12.0],
                "width": 1.0,
                "uv": [i * 0.25, 0.0],
                "u_width": 0.25,
                "flag": i & 1,
            }
            for i in range(glyphs)
        ],
    }


#: 4 x 2 A8R8G8B8 pixels as the PC stores them (B, G, R, A): texel k = (k, 10k, 100, 255)
_PIX = b"".join(bytes([100, 10 * k, k, 255]) for k in range(8))


def test_font_parses_every_field_and_rebuilds_byte_exact():
    data = fa.build(_font_doc(), _PIX)
    assert len(data) == 1 + 29 + 32 + 44 + 3 * 27
    doc = fa.to_json(data)
    assert doc["format"] == "kapow-font/1" and doc["order"] == "<" and doc["leftover_bytes"] == 0
    t = doc["texture"]
    assert (t["width"], t["height"], t["fmt"], t["mips"]) == (4, 2, "A8R8G8B8", 1)
    assert (t["data_offset"], t["data_bytes"]) == (30, 32)
    assert doc["glyph_height"] == 2 and doc["glyph_height_v"] == 0.5 and doc["glyph_count"] == 3
    g = doc["glyphs"][1]
    assert (g["code"], g["char"], g["width"], g["flag"]) == (66, "B", 1.0, 1)
    assert g["rect_px"] == [1.0, 0.0, 1.0, 2]
    assert doc["checks"] == {
        "glyphs": 3,
        "u_width_matches": 3,
        "whole_pixel_u": 3,
        "inside_atlas": 3,
    }
    # what is a guess says so; a JSON round trip gives the file back
    assert "glyphs[].uv" in doc["inferred"] and doc["not_established"] == []
    # the flag is the icon mark (0x43efbb); a code without a glyph is drawn as '@'
    assert [g["icon"] for g in doc["glyphs"]] == [bool(g["flag"]) for g in doc["glyphs"]]
    assert doc["fallback_code"] == 64 and "glyphs[].offset" not in doc["inferred"]
    assert fa.build(json.loads(json.dumps(doc)), fa.pixels(data, doc)) == data


def test_font_atlas_is_decoded_to_rgba():
    data = fa.build(_font_doc(), _PIX)
    img = fa.atlas_image(data, fa.parse(data))
    assert img.shape == (2, 4, 4)
    assert img[1, 2].tolist() == [6, 60, 100, 255]  # texel 6 as R, G, B, A


@pytest.mark.parametrize("platform", ["x360", "ps3"])
def test_font_console_layouts_are_big_endian_with_their_own_pixel_block(platform):
    if platform == "x360":  # the descriptor carries the stored size
        blk = bytes(range(40))
        doc0 = _font_doc(">", size=40)
    else:  # 36-byte RSX descriptor, byte count at +8
        blk = struct.pack(">3I", 0, 0x80, 32) + bytes(24) + bytes(range(32))
        doc0 = _font_doc(">")
    data = fa.build(doc0, blk)
    assert data[1:5] == b"\0\0\0\4"
    doc = fa.parse(data)
    assert doc["order"] == ">" and doc["texture"]["data_bytes"] == len(blk)
    assert [g["code"] for g in doc["glyphs"]] == [65, 66, 67] and doc["glyphs"][2]["uv"] == [
        0.5,
        0.0,
    ]
    assert fa.build(doc, fa.pixels(data, doc)) == data


def test_font_without_buffer_and_font_that_does_not_fit_are_marked():
    assert fa.to_json(b"\0")["has_data"] is False
    data = fa.build(_font_doc(), _PIX)
    bad = fa.to_json(data + b"\0")  # one byte too many: the glyph table does not end the file
    assert (
        bad["not_decoded"].startswith("font: 3 glyph records")
        and bad["leftover_bytes"] == len(data) + 1
    )
    assert fa.notes("a.font", bad, False)[0].startswith("WARNING: font a.font not decoded")
    with pytest.raises(fa.FontError):
        fa.parse(b"\2")


# ---------------------------------------------------------------------------
# .terrain
# ---------------------------------------------------------------------------
Q = 1.0  # quad size
SQ = 32  # sector edge in quads -> one cell per sector
#: heights of the 3 x 3 vertices of the one cell (row = z)
_H = [[0.0, 0.5, 1.0], [0.25, 0.75, 1.25], [0.5, 1.0, 2.0]]
#: texture layer per vertex (the alpha of the vertex colour)
_L = [[0, 0, 1], [0, 1, 1], [0, 1, 1]]
_ORIGIN = [-16.0, 0.0, 0.0]  # sector 1 of a 1 x 2 grid centred on the asset origin


def _positions():
    return [(_ORIGIN[0] + i * Q, _H[k][i], _ORIGIN[2] + k * Q) for k in range(3) for i in range(3)]


def _triangles():
    """The 8 triangles of the 2 x 2 quads in FILE winding: clockwise against the
    normal in engine coordinates (counter-clockwise once x is negated)."""
    out = []
    for k in range(2):
        for i in range(2):
            a, b, c, d = k * 3 + i, k * 3 + i + 1, (k + 1) * 3 + i, (k + 1) * 3 + i + 1
            out += [(a, b, c), (b, d, c)]
    return out


def _terrain_doc(bo="<"):
    pos = _positions()
    xs, ys, zs = zip(*pos)
    box = [[min(xs), min(ys) - 0.1, min(zs)], [max(xs), max(ys) + 0.1, max(zs)]]
    drawn = [[min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]]
    cell = {
        "drawn_bounds": drawn,
        "bounds": box,
        "quads_x": 2,
        "quads_z": 2,
        "origin": list(_ORIGIN),
        "quad_size": Q,
        "vertex_buffer": {"flags": 0, "count": 9, "format": 8},
        "index_buffer": {"flags": 0, "bytes": 60, "x": 1},
        "grass_mask": 0b11,
        "detail_mask": 0b101,
    }
    return {
        "format": ta.FORMAT,
        "order": bo,
        "quad_size": Q,
        "sector_quads": SQ,
        "sectors_x": 1,
        "sectors_z": 2,
        "texture_layers": [
            {"path": "/art/Terrain/Ground_Grass_01.bmp", "id": "0102030405060708"},
            {"path": "/art/Terrain/Ground_Gravel_10.BMP", "id": "1112131415161718"},
        ],
        "grass": ["/art/Grass/Grass_short_01.grass"],
        "detailmeshes": ["/art/d/Detail_A.detailmesh", "/art/d/Detail_B.detailmesh"],
        "decal_textures": [{"path": "/art/Decals/Storm_Drain.bmp", "id": "2122232425262728"}],
        "decals": [
            {
                "quad_rect": [1, 33, 2, 34],  # quad (1, 1) of sector 1
                "b10": 0,
                "f14": -90.0,
                "b18": 0,
                "b19": 1,
                "b1a": 1,
                "f1c": [1.0, 0.86, 0.0, 0.0],
                "place": {"sector": 1, "cell": 0, "sector_vertex": 34, "cell_vertex": 34},
                "bounds": [[-15.0, 0.0, 1.0], [-14.0, 0.0, 2.0]],
                "sphere": [-14.5, 0.0, 1.5, 0.7071],
                "vertex_buffer": {"flags": 0, "count": 6, "format": 8},
            }
        ],
        "sectors": [
            {
                "index": 1,
                "x": 0,
                "z": 1,
                "flag": 1,
                "drawn_bounds": drawn,
                "bounds": box,
                "origin": list(_ORIGIN),
                "cells": [cell],
            }
        ],
    }


def _half(v):
    return np.array(v, "<f2").tobytes()


def _vertex(p, layer, bo, ps3=False):
    """One terrain vertex: PC 48 bytes (vertex format 8), consoles 36 bytes."""
    tint = (200, 150, 100)  # R, G, B
    if bo == "<":
        out = struct.pack("<3f", *p) + _half([0.0, 1.0, 0.0, 0.0])
        out += bytes([tint[2], tint[1], tint[0], layer])  # D3DCOLOR: B, G, R, A
        out += _half([p[0] * 0.5, p[2] * 0.5, 0.0, 0.0]) + _half([1, 0, 0, 0]) + _half([0, 0, 1, 0])
        return out
    packed = 1023 << 11  # x:11 y:11 z:10 -> (0, 1, 0)
    out = struct.pack(">3f", *p) + struct.pack(">I", packed)
    out += bytes(tint) + bytes([layer]) if ps3 else bytes([layer]) + bytes(tint)
    out += np.array([p[0] * 0.5, p[2] * 0.5, 0.0, 0.0], ">f2").tobytes()
    return out + struct.pack(">II", 1023, 511 << 22)


def _terrain_stream(bo="<", ps3=False, extra=b""):
    u = lambda *v: struct.pack(bo + "%dI" % len(v), *v)
    out = b"".join(_vertex((-15.0 + (i % 2), 0.0, 1.0 + i // 2), 0, bo, ps3) for i in range(6))
    layers = [l for row in _L for l in row]
    out += b"".join(_vertex(p, l, bo, ps3) for p, l in zip(_positions(), layers))
    tris = _triangles()
    idx = [v for t in tris for v in t] + [v for t in tris[:2] for v in t]  # pass 2 repeats two
    out += struct.pack(bo + "30H", *idx)
    out += u(0, 24)  # the whole cell
    out += u(2, 0, 12, 12, 24) + u(2, 0, 1)  # pass 1: layer 0 = [0, 12), layer 1 = [12, 24)
    out += u(1, 24, 30) + u(1, 1)  # pass 2: layer 1 = [24, 30)
    out += bytes([0, 0, 0, 0, 1, 0, 0, 0, 0])  # grass id + 1 per vertex
    out += bytes([0, 0, 0, 0, 0, 0, 0, 0, 2])  # detail mesh id + 1 per vertex
    return out + extra


@pytest.mark.parametrize("bo", ["<", ">"])
def test_terrain_header_is_decoded_to_the_last_byte_and_rebuilds(bo):
    data = ta.build(_terrain_doc(bo))
    doc = ta.strip(ta.to_json(data))
    assert doc["format"] == "kapow-terrain/2" and doc["order"] == bo and doc["tail_bytes"] == 0
    assert (doc["quad_size"], doc["sector_quads"], doc["sectors_x"], doc["sectors_z"]) == (
        1.0,
        32,
        1,
        2,
    )
    # the three lists the 1.3.0 reader had keep their keys and shapes
    assert doc["texture_layers"][1]["path"].endswith("Ground_Gravel_10.BMP")
    assert doc["texture_layers"][0]["id"] == "0102030405060708"
    assert doc["grass"] == ["/art/Grass/Grass_short_01.grass"] and len(doc["detailmeshes"]) == 2
    # the id is two u32, low word first: the same value in both byte orders needs the
    # words read in the file's order
    want = 0x0807060504030201 if bo == "<" else 0x0506070801020304
    assert doc["texture_layers"][0]["unique_id"] == "0x%016x" % want
    assert doc["decal_textures"][0]["path"] == "/art/Decals/Storm_Drain.bmp"
    assert doc["decals"][0]["quad_rect"] == [1, 33, 2, 34] and doc["decals"][0]["f14"] == -90.0
    assert doc["sectors_present"] == 1 and doc["cells_per_sector"] == 1
    s = doc["sectors"][0]
    assert (s["index"], s["x"], s["z"]) == (1, 0, 1) and s["origin"] == _ORIGIN
    c = s["cells"][0]
    assert (c["quads_x"], c["quads_z"], c["vertex_buffer"]["format"]) == (2, 2, 8)
    assert c["index_buffer"] == {"flags": 0, "bytes": 60, "x": 1, "primitive_type": 1}
    assert (c["grass_mask"], c["detail_mask"]) == (3, 5)
    assert doc["checks"] == {
        "decals": 1,
        "sectors": 1,
        "decal_place_agree": 1,
        "sector_origin_agree": 1,
    }
    assert "decals[].place" in doc["inferred"] and "decals[].b18" in doc["not_established"]
    assert ta.build(json.loads(json.dumps(doc))) == data


def test_terrain_json_of_kapow_json_is_the_full_decode():
    data = ta.build(_terrain_doc())
    old_style = kj.terrain_json(data)
    assert old_style["tail_bytes"] == 0 and "sectors" in old_style and "_lay" not in old_style
    assert kj.to_json("a.terrain", data)["sectors_present"] == 1
    json.dumps(old_style)


def test_terrain_non_finite_floats_survive_the_json_round_trip():
    d = _terrain_doc()
    cell = d["sectors"][0]["cells"][0]
    cell["index_buffer"] = None  # a cell without triangles has an empty drawn box
    big = struct.unpack("<f", struct.pack("<f", 3.4028234663852886e38))[0]
    cell["drawn_bounds"] = [[big] * 3, [-big] * 3]
    cell["bounds"][0][1] = {"f32": "7fc00000"}  # NaN
    data = ta.build(d)
    doc = ta.strip(ta.to_json(data))
    c = doc["sectors"][0]["cells"][0]
    assert c["index_buffer"] is None and c["drawn_bounds"][0][0] == big
    assert c["bounds"][0][1] == {"f32": "7fc00000"}
    assert ta.build(json.loads(json.dumps(doc))) == data


def test_terrain_that_does_not_fit_the_grammar_is_a_marked_stub():
    data = ta.build(_terrain_doc())
    for bad in (data[:-3], data + b"\0", b"\0" * 16):
        doc = ta.to_json(bad)
        assert doc["not_decoded"].startswith("terrain header:") and doc["tail_bytes"] == len(bad)
        assert ta.notes("t.terrain", doc)[0].startswith("WARNING: terrain t.terrain not decoded")
    with pytest.raises(ta.TerrainError):
        ta.parse(data[:40])


@pytest.mark.parametrize("bo,ps3", [("<", False), (">", False), (">", True)])
def test_terrain_stream_is_walked_as_the_loader_reads_it(bo, ps3):
    data = ta.build(_terrain_doc(bo))
    stream = _terrain_stream(bo, ps3)
    doc = ta.to_json(data, stream=stream)
    lay = doc["_lay"]
    st = doc["stream"]
    stride = 48 if bo == "<" else 36
    assert (st["vertex_stride"], st["bytes"], st["decoded_bytes"], st["leftover_bytes"]) == (
        stride,
        len(stream),
        len(stream),
        0,
    )
    assert st["decal_vertex_buffers"] == [{"offset": 0, "count": 6}]
    c = st["cells"][0]
    assert (c["sector"], c["cell"], c["vertex_offset"], c["vertex_count"]) == (1, 0, 6 * stride, 9)
    assert c["index_offset"] == 15 * stride and c["index_count"] == 30 and c["range"] == [0, 24]
    assert c["pass1"] == [
        {"layer": 0, "first": 0, "end": 12},
        {"layer": 1, "first": 12, "end": 24},
    ]
    assert c["pass2"] == [{"layer": 1, "first": 24, "end": 30}] and c["map_bytes"] == 9
    v = lay["cells"][0]["vertices"]
    assert np.allclose(v["position"], _positions())
    assert np.allclose(v["normal"], [0.0, 1.0, 0.0], atol=2e-3)
    assert v["color"][2].tolist() == [200, 150, 100, 1]  # R, G, B, layer
    assert np.allclose(v["uv"][4], [-7.5, 0.5])
    if bo == ">":
        assert st["console_color_order"] == ("RGBA" if ps3 else "ARGB")
    assert lay["cells"][0]["grass"].tolist() == [[0, 0, 0], [0, 1, 0], [0, 0, 0]]
    assert lay["cells"][0]["detail"][2, 2] == 2
    assert doc["checks"] == {
        "decals": 1,
        "sectors": 1,
        "decal_place_agree": 1,
        "sector_origin_agree": 1,
        "cells": 1,
        "cells_with_indices": 1,
        "cell_bounds_agree": 1,
        "drawn_bounds_agree": 1,
        "range_end_is_index_count": 1,
        "pass_ranges_tile": 1,
        "masks_cover_ids": 1,
        "pass1_triangles_unique": 1,
        "pass2_in_pass1": 1,
    }
    json.dumps(ta.strip(doc))


def test_terrain_checks_count_what_disagrees():
    d = _terrain_doc()
    d["decals"][0]["place"]["cell_vertex"] = 35
    d["sectors"][0]["cells"][0]["grass_mask"] = 1  # the byte map uses id 0 (bit 1)
    doc = ta.to_json(ta.build(d), stream=_terrain_stream())
    assert doc["checks"]["decal_place_agree"] == 0 and doc["checks"]["masks_cover_ids"] == 0
    assert doc["checks"]["cell_bounds_agree"] == 1


def test_terrain_stream_bytes_left_over_or_missing_are_reported():
    data = ta.build(_terrain_doc())
    left = ta.strip(ta.to_json(data, stream=_terrain_stream(extra=b"\0\0\0")))
    assert left["stream"]["leftover_bytes"] == 3
    assert ta.notes("t.terrain", left) == ["WARNING: terrain t.terrain: 3 stream bytes not decoded"]
    short = ta.strip(ta.to_json(data, stream=_terrain_stream()[:-5]))
    assert "pass the end" in short["stream"]["not_decoded"]
    assert short["stream"]["leftover_bytes"] == len(_terrain_stream()) - 5
    assert ta.notes("t.terrain", short)[0].startswith("WARNING: terrain t.terrain stream not")
    none = ta.strip(ta.to_json(data))
    assert "stream" not in none
    assert ta.notes("t.terrain", none) == ["note: terrain t.terrain: no stream, header only"]


def test_terrain_height_field_and_maps(tmp_path):
    from PIL import Image

    doc = ta.to_json(ta.build(_terrain_doc()), stream=_terrain_stream())
    hf = ta.height_field(doc, doc["_lay"])
    assert (hf["width"], hf["depth"], hf["mismatched"]) == (33, 65, 0)
    # sector 1 starts at row 32 (z = 0); column = x index
    assert np.allclose(hf["height"][32:35, 0:3], _H)
    assert np.isnan(hf["height"][0, 0]) and np.isnan(hf["height"][40, 10])
    assert hf["layer"][34, 2] == 1 and hf["layer"][0, 0] == 255
    assert hf["grass"][33, 1] == 1 and hf["detail"][34, 2] == 2
    assert hf["drawn"][32:34, 0:2].all() and hf["drawn"].sum() == 4
    base = str(tmp_path / "T.terrain")
    wrote = ta.write_outputs(doc, base)
    assert sorted(os.path.basename(f) for f in wrote) == [
        "T.terrain.glb",
        "T.terrain.height.png",
        "T.terrain.layers.png",
    ]
    assert "_lay" not in doc
    h = doc["height_field"]
    assert (h["width"], h["depth"], h["min_height"], h["max_height"]) == (33, 65, 0.0, 2.0)
    assert (
        h["vertices_with_data"] == 9
        and h["quads_drawn"] == 4
        and h["origin_xz"]
        == [
            -16.0,
            -32.0,
        ]
    )
    assert "no height map" in h["source"] and "not reflected" in h["axes"]
    px = np.array(Image.open(base + ".height.png"))
    # Pillow before 10.3 reads a 16-bit grey PNG as int32 (mode I); the file is the same
    assert px.dtype in (np.uint16, np.int32) and px.shape == (65, 33)
    assert px[0, 0] == 0 and px[32, 0] == 1 and px[34, 2] == 65535  # no data, min, max
    assert abs(h["min_height"] + (int(px[33, 1]) - 1) / 65534 * 2.0 - 0.75) < 1e-4
    ly = np.array(Image.open(base + ".layers.png"))
    assert ly[34, 2] == 1 and ly[32, 0] == 0 and ly[0, 0] == 255
    json.dumps(doc)


def _glb_tris(g):
    """[(node name, positions, triangles)] of a parsed terrain GLB."""
    out = []
    for n in g.j["nodes"]:
        if "mesh" not in n:
            continue
        p = g.j["meshes"][n["mesh"]]["primitives"][0]
        out.append(
            (
                n["name"],
                g.accessor(p["attributes"]["POSITION"]),
                g.accessor(p["indices"]).reshape(-1, 3),
            )
        )
    return out


def _write_glb(tmp_path, name="T.terrain"):
    doc = ta.to_json(ta.build(_terrain_doc()), stream=_terrain_stream())
    base = str(tmp_path / name)
    ta.write_outputs(doc, base)
    return doc, parse_glb(base + ".glb")


def test_terrain_glb_is_true_handed_with_one_node_per_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    doc, g = _write_glb(tmp_path)
    assert doc["glb"] == "T.terrain.glb"
    meta = g.j["asset"]["extras"]["watchmen"]
    assert meta["coordinate_frame"] == "right-handed-true"
    parts = _glb_tris(g)
    assert [p[0] for p in parts] == ["layer_0_Ground_Grass_01", "layer_1_Ground_Gravel_10"]
    assert sum(len(t) for _, _, t in parts) == 8  # pass 1 only: every triangle once
    mats = g.j["materials"]
    assert mats[1]["extras"] == {"terrain_layer": 1, "texture": "/art/Terrain/Ground_Gravel_10.BMP"}
    for _, pos, tri in parts:
        assert pos[:, 0].min() >= 14.0 - 1e-6 and pos[:, 0].max() <= 16.0 + 1e-6  # x negated
        n = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
        assert (n[:, 1] > 0).all()  # counter-clockwise from above = front faces up
    prim = g.j["meshes"][0]["primitives"][0]
    assert set(prim["attributes"]) == {"POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"}
    col = g.accessor(prim["attributes"]["COLOR_0"])
    assert col.shape[1] == 4 and (col[:, 3] == 255).all() and col[0, :3].tolist() == [200, 150, 100]


def test_terrain_glb_in_the_mirrored_frame_keeps_engine_x(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    _, g = _write_glb(tmp_path)
    assert "extras" not in g.j["asset"]
    for _, pos, tri in _glb_tris(g):
        assert pos[:, 0].max() <= -14.0 + 1e-6 and pos[:, 0].min() >= -16.0 - 1e-6
        n = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])
        assert (n[:, 1] > 0).all()


# ---------------------------------------------------------------------------
# .terraincoloringasset
# ---------------------------------------------------------------------------
def _coloring(bo="<", w=3, h=2, en=4, size=0):
    return struct.pack(bo + "4I2fIf3B", w, h, 2, 2, 0.1, -0.5, 128, 3.5, 0, 1, 1) + struct.pack(
        bo + "5IBII", w, h, en, 1, 1, 0, 1, size
    )


@pytest.mark.parametrize("bo", ["<", ">"])
def test_coloring_header_is_decoded_and_rebuilds(bo):
    data = _coloring(bo, en=4 if bo == "<" else 3)
    assert len(data) == 64
    doc = ta.coloring_to_json(data)
    assert doc["format"] == "kapow-terraincoloring/1" and doc["order"] == bo
    assert (doc["ua0"], doc["ua4"], doc["u98"], doc["ub0"], doc["fb8"]) == (3, 2, 2, 128, 3.5)
    assert (doc["bbd"], doc["bbc"], doc["bbe"]) == (0, 1, 1) and doc["leftover_bytes"] == 0
    assert doc["texture"]["width"] == 3 and doc["texture"]["mips"] == 1
    assert doc["not_established"] == [] and doc["numberOfRays"] == 128
    assert ta.coloring_build(json.loads(json.dumps(doc))) == data


def test_coloring_image_takes_the_padded_rows_apart(tmp_path):
    from PIL import Image

    doc = ta.coloring_to_json(_coloring())
    stream = bytes([1, 2, 3, 99, 4, 5, 6, 99])  # 3 texels + 1 pad byte per row
    wrote = ta.coloring_write(doc, stream, str(tmp_path / "C.terrainColoringAsset"))
    assert [os.path.basename(f) for f in wrote] == ["C.terrainColoringAsset.png"]
    assert doc["stream"] == {"bytes": 8, "expected_bytes": 8, "leftover_bytes": 0}
    assert doc["png"] == "C.terrainColoringAsset.png" and doc["texture"]["fmt"] == "L8"
    assert np.array(Image.open(wrote[0])).tolist() == [[1, 2, 3], [4, 5, 6]]
    assert ta.coloring_notes("C", doc) == []


def test_coloring_that_is_not_decoded_says_so(tmp_path):
    bad = ta.coloring_to_json(_coloring()[:-1])
    assert (
        bad["not_decoded"].startswith("terrain colouring header:") and bad["leftover_bytes"] == 63
    )
    assert ta.coloring_notes("C", bad)[0].startswith("WARNING: terrain colouring C not decoded")
    doc = ta.coloring_to_json(_coloring())
    assert ta.coloring_write(doc, b"", str(tmp_path / "C")) == []
    assert ta.coloring_notes("C", doc) == [
        "WARNING: terrain colouring C: image not written: no stream"
    ]
    doc = ta.coloring_to_json(_coloring())
    assert ta.coloring_write(doc, bytes(5), str(tmp_path / "C")) == []  # shorter than 2 rows
    assert "image not written" in ta.coloring_notes("C", doc)[0]
    odd = ta.coloring_to_json(_coloring(en=77))
    assert ta.coloring_write(odd, bytes(8), str(tmp_path / "C")) == []
    assert odd["stream"]["not_decoded"] == "texture format id 77 / type 1"


def test_coloring_xbox_map_smaller_than_a_block_is_marked_unverified(tmp_path):
    doc = ta.coloring_to_json(_coloring(">", w=1, h=1, en=8, size=8192))
    wrote = ta.coloring_write(doc, bytes(8192), str(tmp_path / "C"))
    assert len(wrote) == 1 and doc["stream"]["leftover_bytes"] == 0
    assert "not established" in doc["stream"]["unverified"]
    assert ta.coloring_notes("C", doc)[0].startswith("note: terrain colouring C: Xbox 360 map")
    big = ta.coloring_to_json(_coloring(">", w=64, h=64, en=8, size=2048))
    assert (
        ta.coloring_write(big, bytes(2048), str(tmp_path / "D"))
        and "unverified" not in big["stream"]
    )


# ---------------------------------------------------------------------------
# .detailmesh
# ---------------------------------------------------------------------------
_DM_PROPS = [
    ("templateName", "string", "Ashes_01"),
    ("model", "string", "/art/Environments/Common/terraindetail/Detail_Ashes_01.model"),
    ("range", "number", 25.0),
]


def _detail(bo="<", typed=True, flag=True):
    body = p1._object("detailmeshasset", _DM_PROPS, bo, typed)
    tail = struct.pack(bo + "6I", 0, 2, 7, 0, 6, 1)
    return body + (b"\1" if flag else b"") + tail


def _detail_stream(bo="<"):
    lists = b"".join(struct.pack(bo + "2I", 1, k) for k in (0, 3, 1))
    return lists + bytes(2 * 60) + bytes(6)


@pytest.mark.parametrize("bo", ["<", ">"])
def test_detailmesh_tail_is_the_mesh_flag_and_two_buffer_descriptors(bo):
    data = _detail(bo)
    assert kp.parse(data, order=bo)["trailing_bytes"] == 25  # the generic walk stops there
    doc = kj.to_json("a.detailmesh", data, order=bo, stream=_detail_stream(bo))
    assert doc["trailing_bytes"] == 0 and len(doc["blocks"][0]["props"]) == 3
    m = doc["mesh"]
    assert m == {
        "has_mesh": True,
        "has_mesh_byte": True,
        "vertex_buffer": {"flags": 0, "count": 2, "format": 7},
        "index_buffer": {"flags": 0, "bytes": 6, "x": 1, "primitive_type": 1},
    }
    assert doc["stream"] == {
        "lists": [1, 1, 1],
        "list_names": ["first_index_a", "first_index_b", "triangle_count"],
        "vertex_offset": 24,
        "vertex_stride": 60,
        "vertex_stride_source": "stream size",
        "format_stride": 60,
        "stride_matches_format": True,
        "index_offset": 144,
        "decoded_bytes": 150,
        "leftover_bytes": 0,
    }
    assert ta.detail_tail_build(m, bo) == data[-25:]
    # the stride is derived from the stream size and the JSON says so
    assert "derived from the stream size" in doc["inferred"]["stream.vertex_stride"]
    assert doc["not_established"] == ta.DETAIL_NOT_ESTABLISHED == []
    assert kj.undecoded(doc) is None
    # a stream whose size does not fit the format's stride is visible as such
    odd = ta.detail_stream_layout(m, _detail_stream(bo) + bytes(8), bo)
    assert odd["vertex_stride"] == 64 and odd["stride_matches_format"] is False
    assert odd["leftover_bytes"] == 0
    _doc, lines = kj.export("a.detailmesh", data, order=bo, stream=_detail_stream(bo) + bytes(8))
    assert lines == [
        "WARNING: detailmesh a.detailmesh: vertex stride 64 from the stream size, the "
        "format's is 60"
    ]
    assert kj.export("a.detailmesh", data, order=bo, stream=_detail_stream(bo))[1] == []
    # without the stream nothing is derived: no `inferred`, the open fields stay listed
    bare = kj.to_json("a.detailmesh", data, order=bo)
    assert "stream" not in bare and "inferred" not in bare
    assert bare["not_established"] == ta.DETAIL_NOT_ESTABLISHED


def test_detailmesh_of_the_standalone_part_1_has_no_flag_byte():
    data = _detail("<", typed=False, flag=False)
    doc = kj.to_json("a.detailmesh", data)
    assert doc["record_layout"] == "untyped" and doc["trailing_bytes"] == 0
    m = doc["mesh"]
    assert m["has_mesh"] and m["has_mesh_byte"] is False and "0x828dae50" in m["layout_note"]
    assert m["vertex_buffer"] == {"flags": 0, "count": 2, "format": 7}
    assert ta.detail_tail_build(m) == data[-24:]
    assert doc["not_established"] == ta.DETAIL_NOT_ESTABLISHED and "inferred" not in doc


def test_detailmesh_without_mesh_and_with_an_unknown_tail():
    none = kj.to_json("a.detailmesh", p1._object("detailmeshasset", _DM_PROPS) + b"\0")
    assert (
        none["mesh"] == {"has_mesh": False, "has_mesh_byte": True} and none["trailing_bytes"] == 0
    )
    assert "not_established" not in none and "inferred" not in none
    odd = p1._object("detailmeshasset", _DM_PROPS) + bytes(7)
    doc, lines = kj.export("a.detailmesh", odd)
    assert "mesh" not in doc and doc["trailing_bytes"] == 7
    assert any("not a detail mesh tail" in w for w in doc["warn"])
    assert lines == ["WARNING: detailmesh a.detailmesh: 7 trailing bytes not decoded"]


# ---------------------------------------------------------------------------
# .scene
# ---------------------------------------------------------------------------
def _scene(order="<"):
    b = tf.B(order)
    p = b.type_record(0x10, "SceneNode") + b.type_record(0x11, "SceneScope(LoadBlock)")
    p += b.instance(0x10, [("name", ""), ("siblingOrder", 0)])
    p += b.instance(
        0x11,
        [
            ("name", "NightClub"),
            ("logicalParent", None),
            ("siblingOrder", 1),
            ("assetName", "/Levels/Game_Levels_Part2/NightClub/NightClub.fragment"),
        ],
    )
    return b.fragment(p)


@pytest.mark.parametrize("order", ["<", ">"])
def test_scene_is_a_fragment_with_a_scene_summary(order):
    doc = kj.to_json("levels/x.scene", _scene(order), order=order)
    assert doc["lossless"] is True and doc["instances_source"] == "exact"
    sc = doc["scene"]
    assert sc["root"] == {"memory_setups": {}} and sc["other_nodes"] == {}
    assert sc["scopes"] == [
        {
            "id": "00000011",
            "type": "SceneScope(LoadBlock)",
            "name": "NightClub",
            "asset": "/Levels/Game_Levels_Part2/NightClub/NightClub.fragment",
            "parent": sc["scopes"][0]["parent"],
            "props": {},
            "memory_setups": {},
        }
    ]
    assert "scene" not in kj.to_json("levels/x.fragment", _scene(order), order=order)


def test_scene_summary_resolves_the_memory_setups():
    common = [["UseRealTime", "truth", False], ["Open", "truth", False]]
    nodes = [
        {"id": "aa", "type": "SceneNode", "created": True, "props": []},  # the type record
        {
            "id": "aa",
            "type": "SceneNode",
            "created": False,
            "props": [["name", "string", ""], ["isCommonBlock", "truth", True]] + common,
        },
        {
            "id": "m1",
            "type": "LoadBlockMemorySetup",
            "created": False,
            "props": [["name", "string", ""], ["maxBaseLayerSizeMB", "number", 96.0]] + common,
        },
        {"id": "f1", "type": "Folder", "created": False, "props": [["name", "string", "Scenes"]]},
        {
            "id": "s1",
            "type": "SceneScope(LoadBlock)",
            "created": False,
            "props": [
                ["name", "string", "Bordello"],
                ["logicalParent", "Entity", {"ref": "f1"}],
                ["assetName", "string", "/Levels/Bordello/Bordello.fragment"],
                ["memorySetupPC", "Entity", {"ref": "m1"}],
                ["m_isceneid", "integer", 7],
            ]
            + common,
        },
    ]
    sc = kj.scene_summary({"nodes_full": nodes})
    assert sc["root"] == {"isCommonBlock": True, "memory_setups": {}}
    assert sc["other_nodes"] == {"Folder": 1}
    (s,) = sc["scopes"]
    assert (s["name"], s["asset"], s["parent"]) == (
        "Bordello",
        "/Levels/Bordello/Bordello.fragment",
        {"ref": "f1"},
    )
    assert s["props"] == {"memorySetupPC": {"ref": "m1"}, "m_isceneid": 7}
    assert s["memory_setups"] == {"memorySetupPC": {"maxBaseLayerSizeMB": 96.0}}


# ---------------------------------------------------------------------------
# kapow_json.export and the extractor
# ---------------------------------------------------------------------------
def test_export_writes_json_safe_documents_and_the_images(tmp_path):
    font = fa.build(_font_doc(), _PIX)
    doc, lines = kj.export("F.font", font, None, str(tmp_path / "F.font"))
    assert doc["atlas_png"] == "F.font.png" and (tmp_path / "F.font.png").exists()
    assert lines == ["font F.font: 3 glyphs, atlas 4x2 A8R8G8B8"]
    json.dumps(doc)
    doc, lines = kj.export(
        "T.terrain", ta.build(_terrain_doc()), _terrain_stream(), str(tmp_path / "T.terrain")
    )
    assert lines == [] and doc["glb"] == "T.terrain.glb" and "_lay" not in doc
    assert (tmp_path / "T.terrain.height.png").exists()
    json.dumps(doc)
    doc, lines = kj.export(
        "U.terrain",
        ta.build(_terrain_doc()),
        _terrain_stream(),
        str(tmp_path / "U.terrain"),
        glb=False,
    )
    assert "glb" not in doc and not (tmp_path / "U.terrain.glb").exists()
    doc, lines = kj.export("S.scene", _scene(), None, str(tmp_path / "S.scene"))
    assert lines == [] and doc["scene"]["scopes"][0]["name"] == "NightClub"
    assert kj.EXPORT_EXTS == (".font", ".scene", ".terrain", ".terraincoloringasset", ".detailmesh")


def test_export_of_a_font_whose_atlas_format_is_unknown_says_so(tmp_path):
    d = _font_doc(">", size=8)  # an Xbox 360 block of a format the decoders do not have
    d["texture"]["enum"] = 77
    data = fa.build(d, bytes(8))
    doc, lines = kj.export("F.font", data, None, str(tmp_path / "F.font"), ">")
    assert doc["glyph_count"] == 3 and "atlas_png" not in doc and doc["atlas_not_written"]
    assert lines == ["font F.font: 3 glyphs, atlas 4x2 format 77 (atlas PNG NOT written)"]


def _run_extract(tmp_path, entries, stream, extra=()):
    src = tmp_path / "derived_pc" / "Levels" / "L"
    src.mkdir(parents=True)
    (src / "L.block_h_z").write_bytes(p1._block(entries))
    (src / "L.block_s_z").write_bytes(stream)
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
            + list(extra)
        )
    finally:
        builtins.print = real
    assert rc == 0
    return out / "extracted", "\n".join(lines)


def _block_parts():
    """Entries of one block (font, scene, terrain, colouring, detail mesh, a broken
    font) and its stream file."""
    z = zlib.compress
    streams = [z(_terrain_stream()), z(bytes([1, 2, 3, 0, 4, 5, 6, 0])), z(_detail_stream())]
    offs = [0, len(streams[0]), len(streams[0]) + len(streams[1])]
    pair = lambda i: (offs[i], len(streams[i]))
    h = we._name_hash
    entries = [
        ("/art/Fonts/Small.font", h("font"), z(fa.build(_font_doc(), _PIX)), None),
        ("/Levels/Game.scene", h("fragment"), z(_scene()), None),
        ("/Levels/L/T.terrain", h("terrain"), z(ta.build(_terrain_doc())), pair(0)),
        (
            "/Levels/L/T.terrainColoringAsset",
            h("terrainColoringAsset"),
            z(_coloring()),
            pair(1),
        ),
        ("/art/d/Detail_A.detailmesh", h("DetailMeshAsset"), z(_detail()), pair(2)),
        ("/art/Fonts/Broken.font", h("font"), z(fa.build(_font_doc(), _PIX) + b"\7"), None),
    ]
    return entries, b"".join(streams)


def test_extract_writes_json_and_images_for_the_five_kinds(tmp_path):
    entries, stream = _block_parts()
    ex, log = _run_extract(tmp_path, entries, stream)
    font = json.loads((ex / "art" / "Fonts" / "Small.font.json").read_text())
    assert font["glyph_count"] == 3 and font["atlas_png"] == "Small.font.png"
    assert (ex / "art" / "Fonts" / "Small.font.png").exists()
    scene = json.loads((ex / "Levels" / "Game.scene.json").read_text())
    assert scene["lossless"] and scene["scene"]["scopes"][0]["name"] == "NightClub"
    terrain = json.loads((ex / "Levels" / "L" / "T.terrain.json").read_text())
    assert terrain["tail_bytes"] == 0 and terrain["stream"]["leftover_bytes"] == 0
    assert terrain["height_field"]["png"] == "T.terrain.height.png"
    assert (ex / "Levels" / "L" / "T.terrain.height.png").exists()
    assert (ex / "Levels" / "L" / "T.terrain.layers.png").exists()
    assert not (ex / "Levels" / "L" / "T.terrain.glb").exists()  # only with --glb
    col = json.loads((ex / "Levels" / "L" / "T.terrainColoringAsset.json").read_text())
    assert col["png"] == "T.terrainColoringAsset.png" and col["stream"]["leftover_bytes"] == 0
    assert (ex / "Levels" / "L" / "T.terrainColoringAsset.png").exists()
    dm = json.loads((ex / "art" / "d" / "Detail_A.detailmesh.json").read_text())
    assert dm["trailing_bytes"] == 0 and dm["mesh"]["vertex_buffer"]["count"] == 2
    assert dm["stream"]["leftover_bytes"] == 0
    # what is not decoded: a marker in the JSON and a line in the log
    broken = json.loads((ex / "art" / "Fonts" / "Broken.font.json").read_text())
    assert broken["not_decoded"].startswith("font:") and broken["leftover_bytes"] > 0
    assert "WARNING: font /art/Fonts/Broken.font not decoded: font: 3 glyph records" in log
    assert not (ex / "art" / "Fonts" / "Broken.font.png").exists()
    assert "font /art/Fonts/Small.font: 3 glyphs, atlas 4x2 A8R8G8B8" in log
    assert "WARNING: terrain" not in log and "! json" not in log


def test_extract_with_glb_writes_the_terrain_surface(tmp_path):
    entries, stream = _block_parts()
    ex, log = _run_extract(tmp_path, entries, stream, ["--glb"])
    terrain = json.loads((ex / "Levels" / "L" / "T.terrain.json").read_text())
    assert terrain["glb"] == "T.terrain.glb"
    g = parse_glb(str(ex / "Levels" / "L" / "T.terrain.glb"))
    assert len(g.j["meshes"]) == 2 and "! json" not in log
