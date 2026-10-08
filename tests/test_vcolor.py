"""Vertex colour, tangent frame and normal-map channels in the GLB exports
(findings/vcolor.md, findings/impl_vcolor.md).  Offline: every fixture is built
from the layouts the engine reads; each test fails on the 1.3.0 code.

Sections
--------
  1. ATI2 block order of PC normal maps
  2. TextureSheet properties -> sheet.json
  3. COLOR_0 / TANGENT conventions
  4. rig_glb: per-submesh colour, alpha modes, sheet-driven materials, normal map
  5. decode_model: attributes on, rigid GLB, --no-vertex-attrs
  6. character GLBs (variant_glb): attributes carried by the parts
"""

import io
import json
import struct

import numpy as np
import pytest

import rig_glb
import test_formats_v2 as tf
import variant_glb as vg
import watchmen_extract as we
from conftest import parse_glb

Image = pytest.importorskip("PIL.Image")

_PAL = {"bone_count": 0, "bones": []}

# ---------------------------------------------------------------------------
# 1. ATI2 block order
# ---------------------------------------------------------------------------


def _bc4_flat(value):
    """8-byte BC4 block whose 16 texels all decode to `value`."""
    return bytes([value, value]) + b"\x00" * 6


def test_pc_ati2_keeps_the_y_block_first():
    # Direct3D 9 ATI2: first block = Y (green), second = X (red).  1.3.0 wrote the
    # first block to the PNG's red channel.
    layer = _bc4_flat(200) + _bc4_flat(60)  # first block 200, second block 60
    img = we._decode_one_layer(layer, 9, 4, 4)
    assert img[..., 0].tolist() == [[60] * 4] * 4  # X = second block
    assert img[..., 1].tolist() == [[200] * 4] * 4  # Y = first block
    # the X360 format (enum 10) is X-first already and stays as it was
    x360 = we._decode_one_layer(layer, 10, 4, 4)
    assert x360[0, 0, 0] == 200 and x360[0, 0, 1] == 60
    assert we.ati2_xy(("first", "second")) == ("second", "first")


def test_normal_z_is_rebuilt_from_the_swapped_pair():
    img = we._decode_one_layer(_bc4_flat(255) + _bc4_flat(128), 9, 4, 4)
    x, y = img[0, 0, 0] / 255 * 2 - 1, img[0, 0, 1] / 255 * 2 - 1
    assert abs(y - 1.0) < 1e-6 and abs(x) < 0.01
    assert img[0, 0, 2] <= 129  # z = sqrt(1 - x^2 - y^2) ~ 0 -> 0.5 encoded


# ---------------------------------------------------------------------------
# 2. TextureSheet properties
# ---------------------------------------------------------------------------


def _prop(salt, name, typ, value, order="<"):
    raw = struct.pack(order + "f", value) if typ == "number" else struct.pack(order + "I", value)
    head = struct.pack(order + "IIII", salt, we._name_hash(name), we._name_hash(typ), 1)
    return head + raw


def _sheet_header(order="<"):
    first = [
        ("renderType", "integer", 1),
        ("isLit", "truth", 1),
        ("normalMapPower", "number", 1.5),
        ("opacity", "number", 0.75),
        ("alphaThreshold", "integer", 95),
        ("writeDepthBuffer", "truth", 0),
        ("twoSided", "truth", 1),
        ("blendType", "integer", 0),
    ]
    second = [
        ("renderType", "integer", 0),
        ("twoSided", "truth", 0),
        ("alphaThreshold", "integer", 60),
    ]
    b = b"\x08\x00\x00\x00Texture\x00" + b"\xaa" * 37
    b += b"".join(_prop(0x1DA7D3DD, n, t, v, order) for n, t, v in first) + b"\x00" * 9
    b += b"".join(_prop(0x1DADD41F, n, t, v, order) for n, t, v in second)
    return b + b"\x00" * 24


def test_texture_sheet_reads_the_first_sheet_only():
    sh = we.texture_sheet(_sheet_header())
    assert sh["renderType"] == 1 and sh["twoSided"] is True and sh["alphaThreshold"] == 95
    assert sh["writeDepthBuffer"] is False and sh["isLit"] is True
    assert abs(sh["normalMapPower"] - 1.5) < 1e-6 and abs(sh["opacity"] - 0.75) < 1e-6
    assert we.SHEET_RENDER_TYPES[sh["renderType"]] == "blend"
    assert we.texture_sheet(b"\x00" * 64) == {}
    be = we.texture_sheet(_sheet_header(">"), ">")
    assert be["twoSided"] is True and be["alphaThreshold"] == 95


def test_sheet_json_round_trip(tmp_path):
    we._write_sheet_json(_sheet_header(), tmp_path)
    d = we.read_sheet_json(tmp_path)
    assert d["twoSided"] is True and d["renderType"] == 1
    assert we.read_sheet_json(tmp_path / "missing") == {}
    we._write_sheet_json(b"\x00" * 64, tmp_path / "x")  # no sheet: nothing written, no error
    assert not (tmp_path / "x").exists()


# ---------------------------------------------------------------------------
# 3. conventions
# ---------------------------------------------------------------------------


def test_vertex_colour_is_linearised_but_alpha_is_not():
    c = rig_glb.linear_vertex_colors(np.array([[255, 0, 128, 128], [188, 188, 188, 0]], np.uint8))
    assert c.dtype == np.float32
    assert c[0].tolist()[:2] == [1.0, 0.0]
    assert abs(c[0, 2] - 0.21586) < 1e-4  # sRGB 128 -> linear
    assert abs(c[0, 3] - 128 / 255) < 1e-6  # alpha as stored
    assert abs(c[1, 0] - 0.50289) < 1e-4 and c[1, 3] == 0.0


def test_tangent_handedness_follows_the_normal_texture_orientation():
    n = np.array([[0, 0, 1.0]] * 2)
    t = np.array([[1.0, 0, 0]] * 2)
    b = np.array([[0, 1.0, 0], [0, -1.0, 0]])  # s = +1, -1
    assert we.gltf_tangents(n, t, b)[:, 3].tolist() == [-1.0, 1.0]  # glTF texture: w = -s
    assert we.gltf_tangents(n, t, b, green_up=False)[:, 3].tolist() == [1.0, -1.0]


def test_gltf_normal_png_inverts_green_only():
    buf = io.BytesIO()
    Image.fromarray(np.array([[[10, 20, 200]]], np.uint8)).save(buf, "PNG")
    out = np.asarray(Image.open(io.BytesIO(rig_glb.gltf_normal_png(buf.getvalue()))))
    assert out[0, 0].tolist() == [10, 235, 200]
    assert rig_glb.gltf_normal_png(b"not a png") is None


def test_material_alpha_rules():
    f = rig_glb.material_alpha
    assert f({"renderType": 0, "alphaThreshold": 95}, True, False) == ("MASK", 0.372549)
    assert f({"renderType": 0, "alphaThreshold": 0}, True, False) == (None, None)
    assert f({"renderType": 1, "alphaThreshold": 0}, True, False) == ("BLEND", None)
    assert f({"renderType": 1}, False, False) == (None, None)  # nothing to blend with
    # vertex alpha does not choose the render list (0x5739d0): MASK / opaque stay
    assert f({"renderType": 0, "alphaThreshold": 95}, True, True) == ("MASK", 0.372549)
    assert f({"renderType": 0}, False, True) == (None, None)
    assert f(None, False, True) == ("BLEND", None)  # no sheet known: as before
    # the legacy materials mode keeps its rule
    assert f({"renderType": 0, "alphaThreshold": 95}, True, True, legacy=True) == ("BLEND", None)
    assert f({"renderType": 0}, False, True, legacy=True) == ("BLEND", None)
    assert f(None, True, False) == ("MASK", 0.5)  # no sheet.json: the 1.3.0 character rule


# ---------------------------------------------------------------------------
# 4. rig_glb
# ---------------------------------------------------------------------------


def _two_quads(tmp_path, name="m.glb", tex_index=None, materials=("a", "b"), **kw):
    V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)] * 2
    U = [(0, 0), (1, 0), (1, 1), (0, 1)] * 2
    T = [(0, 2, 1), (0, 3, 2), (4, 6, 5), (4, 7, 6)]  # the engine's order: against +Z
    subs = [(0, 4, 0, 2, 44), (4, 4, 2, 2, 44)]
    nrm = np.tile(np.array([0, 0, 1], np.float32), (8, 1))
    col = np.tile(np.array([128, 128, 128, 255], np.uint8), (8, 1))
    col[4:, 3] = [0, 255, 255, 0]
    tan = np.tile(np.array([1, 0, 0, 1], np.float32), (8, 1))
    out = tmp_path / name
    rig_glb.build_rigged_glb(
        out,
        np.asarray(V, float),
        None,
        U,
        None,
        None,
        T,
        subs,
        list(materials),
        tex_index or {},
        _PAL,
        None,
        None,
        static=True,
        normals=nrm,
        colors=col,
        tangents=tan,
        **kw,
    )
    return parse_glb(out)


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_colour_only_on_flagged_submeshes_and_blend_on_vertex_alpha(tmp_path):
    g = _two_quads(
        tmp_path, has_color=[False, True], has_alpha=[False, True], engine_materials=True
    )
    p0, p1 = g.j["meshes"][0]["primitives"]
    assert "COLOR_0" not in p0["attributes"] and "COLOR_0" in p1["attributes"]
    acc = g.j["accessors"][p1["attributes"]["COLOR_0"]]
    assert (acc["type"], acc["componentType"]) == ("VEC4", 5126) and "normalized" not in acc
    C = np.asarray(g.accessor(p1["attributes"]["COLOR_0"]))
    assert np.allclose(C[:, 0], 0.21586, atol=1e-4) and C[:, 3].tolist() == [0.0, 1.0, 1.0, 0.0]
    m0, m1 = g.j["materials"][p0["material"]], g.j["materials"][p1["material"]]
    assert "alphaMode" not in m0 and m1["alphaMode"] == "BLEND"
    # winding turned to counter-clockwise against the normal
    idx = np.asarray(g.accessor(p0["indices"])).reshape(-1, 3)
    assert idx.tolist() == [[0, 1, 2], [0, 2, 3]]


def test_one_texture_used_with_and_without_vertex_alpha_gets_two_materials(tmp_path):
    g = _two_quads(
        tmp_path,
        materials=("same", "same"),
        has_color=[True, True],
        has_alpha=[False, True],
        engine_materials=True,
    )
    p0, p1 = g.j["meshes"][0]["primitives"]
    assert p0["material"] != p1["material"]
    assert [m.get("alphaMode") for m in g.j["materials"]] == [None, "BLEND"]
    # without engine_materials the 1.3.0 material is kept: one, opaque, double-sided
    g = _two_quads(tmp_path, "old.glb", materials=("same", "same"), has_alpha=[False, True])
    assert len(g.j["materials"]) == 1 and g.j["materials"][0]["doubleSided"] is True
    assert "alphaMode" not in g.j["materials"][0]


def _texture_dir(tmp_path, name, sheet, alpha=True):
    d = tmp_path / (name + ".bmp")
    d.mkdir()
    rgba = np.zeros((4, 4, 4), np.uint8)
    rgba[..., :3] = 200
    rgba[..., 3] = 255
    if alpha:
        rgba[0, 0, 3] = 0
    Image.fromarray(rgba).save(d / "0_diffuse_4x4_DXT5.png")
    Image.fromarray(np.full((4, 4, 3), (140, 30, 250), np.uint8)).save(d / "1_normal_4x4_ATI2.png")
    if sheet is not None:
        (d / "sheet.json").write_text(json.dumps(sheet), encoding="utf-8")
    return d


def test_engine_materials_follow_the_texture_sheet(tmp_path):
    idx = {
        "a": _texture_dir(
            tmp_path,
            "a",
            {"twoSided": False, "renderType": 0, "alphaThreshold": 95, "normalMapPower": 1.5},
        ),
        "b": _texture_dir(tmp_path, "b", {"twoSided": True, "renderType": 1, "alphaThreshold": 0}),
    }
    g = _two_quads(tmp_path, tex_index=idx, has_color=[False, False], engine_materials=True)
    ma, mb = [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]
    assert ma["doubleSided"] is False and mb["doubleSided"] is True
    assert (ma["alphaMode"], ma["alphaCutoff"]) == ("MASK", 0.372549)
    assert mb["alphaMode"] == "BLEND" and "alphaCutoff" not in mb
    assert ma["normalTexture"]["scale"] == 1.5 and "scale" not in mb["normalTexture"]
    # the embedded normal map is the PNG with green inverted; the diffuse keeps its alpha
    tex = g.j["textures"][ma["normalTexture"]["index"]]
    bv = g.j["bufferViews"][g.j["images"][tex["source"]]["bufferView"]]
    png = g.bin_chunk[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]]
    assert np.asarray(Image.open(io.BytesIO(png)))[0, 0].tolist() == [140, 225, 250]
    base = g.j["textures"][ma["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    bv = g.j["bufferViews"][g.j["images"][base["source"]]["bufferView"]]
    assert (
        Image.open(
            io.BytesIO(g.bin_chunk[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]])
        ).mode
        == "RGBA"
    )


def test_without_sheet_json_materials_stay_double_sided(tmp_path):
    idx = {
        "a": _texture_dir(tmp_path, "a", None),
        "b": _texture_dir(tmp_path, "b", None, alpha=False),
    }
    g = _two_quads(tmp_path, tex_index=idx, has_color=[False, False], engine_materials=True)
    ma, mb = [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]
    assert ma["doubleSided"] is True and mb["doubleSided"] is True
    assert (ma["alphaMode"], ma["alphaCutoff"]) == ("MASK", 0.5) and "alphaMode" not in mb


# ---------------------------------------------------------------------------
# 5. decode_model
# ---------------------------------------------------------------------------


@pytest.fixture
def rig_on(monkeypatch):
    monkeypatch.setitem(we._RIG, "on", True)
    monkeypatch.setitem(we._RIG, "loaded", False)
    monkeypatch.setitem(we._RIG, "attrs", True)
    return we._RIG


def _rigid_model():
    return tf._model([{"lods": [[("Crate", 0, 5, 0.0, 1)]]}], tf._TEXTURES)


def _skinned_model():
    return tf._model([{"lods": [[("Body", 1, 6, 0.0, 1)]]}], tf._TEXTURES)


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_rigid_model_gets_a_static_glb_with_its_vertex_data(tmp_path, rig_on):
    h, s = _rigid_model()
    # no normal map for the material: NORMAL and COLOR_0, but no (unused) TANGENT
    assert we.decode_model(h, s, tmp_path / "plain.obj", {}, None)
    A = parse_glb(tmp_path / "plain.glb").j["meshes"][0]["primitives"][0]["attributes"]
    assert set(A) == {"POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"}
    idx = {"wall_01": _texture_dir(tmp_path, "Wall_01", {"twoSided": False}, alpha=False)}
    assert we.decode_model(h, s, tmp_path / "crate.obj", idx, None)
    g = parse_glb(tmp_path / "crate.glb")
    assert "skins" not in g.j
    A = g.j["meshes"][0]["primitives"][0]["attributes"]
    assert set(A) == {"POSITION", "NORMAL", "TANGENT", "TEXCOORD_0", "COLOR_0"}
    assert "normalTexture" in g.j["materials"][0] and g.j["materials"][0]["doubleSided"] is False
    C = np.asarray(g.accessor(A["COLOR_0"]))
    assert np.allclose(
        C[0], rig_glb.linear_vertex_colors(np.array([[10, 20, 30, 40]], np.uint8))[0]
    )
    # stored tangent +X, bitangent -Y, normal +Z: s = -1, so w = +1
    assert np.asarray(g.accessor(A["TANGENT"])).tolist() == [[1.0, 0.0, 0.0, 1.0]] * 4


def test_no_vertex_attrs_restores_the_130_output(tmp_path, rig_on):
    rig_on["attrs"] = False
    h, s = _rigid_model()
    assert we.decode_model(h, s, tmp_path / "crate.obj", {}, None)
    assert not (tmp_path / "crate.glb").exists()  # 1.3.0: no .glb for a rigid model
    h, s = _skinned_model()
    assert we.decode_model(h, s, tmp_path / "body.obj", {}, None)
    g = parse_glb(tmp_path / "body.glb")
    p = g.j["meshes"][0]["primitives"][0]
    assert set(p["attributes"]) == {"POSITION", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"}
    assert g.j["materials"][p["material"]]["doubleSided"] is True
    off = (tmp_path / "body.glb").read_bytes()
    rig_on["attrs"] = True
    idx = {"trim_02": _texture_dir(tmp_path, "Trim_02", None, alpha=False)}
    assert we.decode_model(h, s, tmp_path / "body.obj", idx, None)
    on = parse_glb(tmp_path / "body.glb")
    assert {"NORMAL", "TANGENT", "COLOR_0"} <= set(on.j["meshes"][0]["primitives"][0]["attributes"])
    assert (tmp_path / "body.glb").read_bytes() != off


def test_cli_switch_is_parsed(monkeypatch, capsys):
    import watchmen

    assert watchmen.main(["watchmen.py", "hash", "--no-vertex-attrs", "x"]) == 2
    assert "--no-vertex-attrs applies to" in capsys.readouterr().out
    monkeypatch.delenv("WATCHMEN_VERTEX_ATTRS", raising=False)
    assert vg.vertex_attrs_enabled()
    monkeypatch.setenv("WATCHMEN_VERTEX_ATTRS", "0")
    assert not vg.vertex_attrs_enabled()


# ---------------------------------------------------------------------------
# 6. character GLBs
# ---------------------------------------------------------------------------


def test_buffer_vertex_attrs_come_from_the_header_located_buffer():
    h, s = _skinned_model()
    at = vg.buffer_vertex_attrs(h, s, "<", 0, 4, 56)
    assert at["has_color"] is True and at["has_alpha"] is False
    assert at["normal"].tolist() == [[0.0, 0.0, 1.0]] * 4
    assert at["tangent"].tolist() == [[1.0, 0.0, 0.0]] * 4
    assert at["bitangent"].tolist() == [[0.0, -1.0, 0.0]] * 4
    assert at["color"].tolist() == [[10, 20, 30, 40]] * 4
    # anything the header does not account for is refused, never guessed
    assert vg.buffer_vertex_attrs(h, s, "<", 4, 4, 56) is None  # not a buffer start
    assert vg.buffer_vertex_attrs(h, s, "<", 0, 3, 56) is None  # other vertex count
    assert vg.buffer_vertex_attrs(h, s, "<", 0, 4, 44) is None  # other stride
    assert vg.buffer_vertex_attrs(h, s, ">", 0, 4, 56) is None  # console files: scan path only
    assert vg.buffer_vertex_attrs(h[:40], s, "<", 0, 4, 56) is None


def test_parts_carry_attributes_through_rebuilds():
    base = (np.zeros((2, 3)), None, None, np.zeros((0, 3), int), np.zeros((2, 2)), "m")
    at = {
        "normal": np.array([[0, 0, 1], [0, 0, 1]], np.float32),
        "tangent": np.array([[1, 0, 0], [1, 0, 0]], np.float32),
        "bitangent": np.array([[0, 1, 0], [0, 1, 0]], np.float32),
        "color": np.zeros((2, 4), np.uint8),
        "has_color": True,
        "has_alpha": False,
    }
    p = vg.with_attrs(base, at)
    assert isinstance(p, tuple) and len(p) == 6 and p[5] == "m" and p.attrs is at
    V, SI, SW, T, UV, nm = p  # unpacks like the plain tuple
    assert vg.with_attrs(base, None) is base
    rot = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])  # +X -> +Y
    r = vg.with_attrs(base, at, rot=rot)
    assert r.attrs["tangent"].tolist() == [[0.0, 1.0, 0.0]] * 2
    assert r.attrs["normal"].tolist() == [[0.0, 0.0, 1.0]] * 2 and at["tangent"][0, 0] == 1
    k = vg.keep_attrs(p, base[:5] + ("other",))
    assert k[5] == "other" and k.attrs is at
    shorter = (np.zeros((1, 3)),) + base[1:]
    assert (
        not hasattr(vg.keep_attrs(p, shorter), "attrs") or vg.keep_attrs(p, shorter).attrs is None
    )


def _png(rgb):
    buf = io.BytesIO()
    Image.fromarray(np.full((2, 2, 3), rgb, np.uint8)).save(buf, "PNG")
    return buf.getvalue()


def _attr_parts(rig, has_alpha=False):
    n = np.tile(np.array([0, 0, 1], np.float32), (rig.NV, 1))
    col = np.tile(np.array([128, 64, 255, 255], np.uint8), (rig.NV, 1))
    if has_alpha:
        col[0, 3] = 0
    at = {
        "normal": n,
        "tangent": np.tile(np.array([1, 0, 0], np.float32), (rig.NV, 1)),
        "bitangent": np.tile(np.array([0, 1, 0], np.float32), (rig.NV, 1)),
        "color": col,
        "has_color": True,
        "has_alpha": has_alpha,
    }
    return [vg.with_attrs(rig.parts[0], at)]


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_character_glb_gets_the_attributes_and_keeps_the_130_buffers(rig, tmp_path, monkeypatch):
    monkeypatch.delenv("WATCHMEN_VERTEX_ATTRS", raising=False)
    vg.write_glb(_attr_parts(rig), rig.manifest, tmp_path / "nomap.glb", str(rig.bind_npz))
    nomap = parse_glb(tmp_path / "nomap.glb").j["meshes"][0]["primitives"][0]["attributes"]
    assert "NORMAL" in nomap and "COLOR_0" in nomap and "TANGENT" not in nomap  # no normal map
    tex = {"mat_body": {"diffuse": _png((90, 90, 90)), "normal": _png((128, 128, 255))}}
    bind = str(rig.bind_npz)
    vg.write_glb(rig.parts, rig.manifest, tmp_path / "plain.glb", bind, textures=tex)
    vg.write_glb(_attr_parts(rig), rig.manifest, tmp_path / "attrs.glb", bind, textures=tex)
    old, new = parse_glb(tmp_path / "plain.glb"), parse_glb(tmp_path / "attrs.glb")
    po, pn = old.j["meshes"][0]["primitives"][0], new.j["meshes"][0]["primitives"][0]
    assert set(pn["attributes"]) - set(po["attributes"]) == {"NORMAL", "TANGENT", "COLOR_0"}
    for k in po["attributes"]:  # positions, skin and UVs are the same bytes
        assert np.array_equal(old.accessor(po["attributes"][k]), new.accessor(pn["attributes"][k]))
    T = np.asarray(new.accessor(pn["attributes"]["TANGENT"]))
    assert T[:, 3].tolist() == [-1.0] * rig.NV  # s = +1 -> w = -1
    C = np.asarray(new.accessor(pn["attributes"]["COLOR_0"]))
    assert np.allclose(
        C[0], rig_glb.linear_vertex_colors(np.array([[128, 64, 255, 255]], np.uint8))[0]
    )
    # same triangles; each is wound counter-clockwise against the written normal
    io_, in_ = (
        np.asarray(old.accessor(po["indices"])).reshape(-1, 3),
        np.asarray(new.accessor(pn["indices"])).reshape(-1, 3),
    )
    assert [sorted(t) for t in io_.tolist()] == [sorted(t) for t in in_.tolist()]
    flipped = rig_glb.winding_reversed(rig.V, np.tile([0, 0, 1.0], (rig.NV, 1)), io_)
    assert (
        (in_.tolist() == io_[:, [0, 2, 1]].tolist()) if flipped else (in_.tolist() == io_.tolist())
    )
    # animation and inverse binds: byte-identical accessors
    for a_old, a_new in zip(old.j["animations"], new.j["animations"]):
        for s_old, s_new in zip(a_old["samplers"], a_new["samplers"]):
            assert np.array_equal(old.accessor(s_old["output"]), new.accessor(s_new["output"]))
    assert "alphaMode" not in new.j["materials"][pn["material"]]


def test_character_vertex_alpha_blends_and_the_switch_restores_130(rig, tmp_path, monkeypatch):
    monkeypatch.delenv("WATCHMEN_VERTEX_ATTRS", raising=False)
    parts = _attr_parts(rig, has_alpha=True)
    vg.write_glb(parts, rig.manifest, tmp_path / "a.glb", str(rig.bind_npz))
    g = parse_glb(tmp_path / "a.glb")
    p = g.j["meshes"][0]["primitives"][0]
    assert g.j["materials"][p["material"]]["alphaMode"] == "BLEND"
    vg.write_glb(rig.parts, rig.manifest, tmp_path / "plain.glb", str(rig.bind_npz))
    monkeypatch.setenv("WATCHMEN_VERTEX_ATTRS", "0")
    vg.write_glb(parts, rig.manifest, tmp_path / "off.glb", str(rig.bind_npz))
    assert (tmp_path / "off.glb").read_bytes() == (tmp_path / "plain.glb").read_bytes()


def test_uv_sanitiser_copies_the_attributes_of_the_vertices_it_duplicates(rig):
    part = _attr_parts(rig)[0]
    uv = np.asarray(part[4]).copy()
    uv[:3] = uv[0]  # collapse the first triangle's UVs
    part = vg.with_attrs(part[:4] + (uv, part[5]), part.attrs)
    part.attrs["color"][1] = [1, 2, 3, 4]
    out = vg._sanitize_uv_tangents(part)
    assert len(out[0]) > rig.NV and len(out.attrs["normal"]) == len(out[0])
    new = np.asarray(out[3])[0]
    assert new.min() >= rig.NV  # the collapsed face now uses appended vertices
    src = np.asarray(part[3])[0]
    assert out.attrs["color"][new].tolist() == part.attrs["color"][src].tolist()
    assert np.array_equal(out[0][new], np.asarray(part[0])[src])
