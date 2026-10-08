"""Materials after the renderer re-read (findings/waveC_renderer_check.md, section 6,
proposals 1-4): the alpha mode follows the render list (vertex alpha alone never
blends), "texture has alpha" is the Texture header's flag, sheet_blend covers a
Standard / FallOff sheet drawn blended for its opacity, and the grade meta carries
the corrected formula, the platform adjustment and the missing node keys.

Offline: synthetic sheets, headers, textures and fragments only."""

import io
import json

import numpy as np
import pytest

import materials as mt
import rig_glb
import test_formats_v2 as tf
import test_vcolor as tv
import variant_glb as vg
import watchmen_extract as we
from conftest import parse_glb

Image = pytest.importorskip("PIL.Image")

HAIR = {"renderType": 10, "alphaThreshold": 95, "twoSided": True, "opacity": 1.0}
STD = {"renderType": 0, "alphaThreshold": 95, "opacity": 1.0}


@pytest.fixture(autouse=True)
def _engine_mode(monkeypatch):
    monkeypatch.delenv("WATCHMEN_MATERIALS", raising=False)
    monkeypatch.delenv("WATCHMEN_MATERIAL_OPTS", raising=False)
    monkeypatch.delenv("WATCHMEN_VERTEX_ATTRS", raising=False)


# ---------------------------------------------------------------------------
# 1. alpha mode: the render list, never vertex alpha alone
# ---------------------------------------------------------------------------


def test_vertex_alpha_alone_never_blends():
    # a type-0 mesh with varying vertex alpha exports as opaque or MASK
    assert mt.alpha(STD, False, vertex_alpha=True) == (None, None, None)
    assert mt.alpha(STD, True, vertex_alpha=True) == ("MASK", round(95 / 255.0, 6), None)
    assert mt.alpha(HAIR, True, vertex_alpha=True)[0] == "MASK"
    assert mt.alpha(dict(STD, renderType=11), False, vertex_alpha=True)[0] is None
    # no sheet known (a texture without sheet.json): the earlier rule stays
    assert mt.alpha({}, False, vertex_alpha=True) == ("BLEND", None, None)
    assert mt.alpha(None, True, vertex_alpha=True) == ("BLEND", None, None)
    assert mt.alpha(None, True) == ("MASK", 0.5, None)


def test_blend_iff_render_type_1_or_opacity():
    assert mt.alpha({"renderType": 1}, True) == ("BLEND", None, None)
    assert mt.alpha({"renderType": 1}, False, vertex_alpha=True) == ("BLEND", None, None)
    assert mt.alpha({"renderType": 1}, False) == (None, None, None)  # nothing below 1
    assert mt.alpha(dict(STD, opacity=0.5), False) == ("BLEND", None, 0.5)
    assert mt.alpha(dict(HAIR, opacity=0.98), True, True) == ("BLEND", None, 0.98)
    assert mt.alpha(dict(STD, opacity=0.99), True)[0] == "MASK"  # the threshold is < 0.99


def test_skybox_and_sprite_sheets_keep_their_rule():
    # passes of their own, which blend (sheet_blend): vertex alpha still gives BLEND
    for rt in mt.OWN_PASS_BLENDED:
        assert mt.alpha({"renderType": rt}, False, vertex_alpha=True)[0] == "BLEND"
        assert rig_glb.material_alpha({"renderType": rt}, False, True) == ("BLEND", None)
        assert mt.alpha({"renderType": rt, "alphaThreshold": 95}, True)[0] == "MASK"
    assert mt.OWN_PASS_BLENDED == (7, 9)


def test_rig_material_alpha_has_the_same_rule_and_a_legacy_switch():
    f = rig_glb.material_alpha
    assert f(STD, False, True) == (None, None)
    assert f(STD, True, True) == ("MASK", 0.372549)
    assert f({"renderType": 1}, False, True) == ("BLEND", None)
    assert f(dict(STD, opacity=0.5), False, False) == ("BLEND", None)  # was opaque
    assert f(None, False, True) == ("BLEND", None)  # no sheet known: as before
    assert f({}, True, True) == ("BLEND", None)
    # legacy materials mode: the old rule, unchanged
    assert f(STD, False, True, legacy=True) == ("BLEND", None)
    assert f(dict(STD, opacity=0.5), False, False, legacy=True) == (None, None)
    assert f({"renderType": 1}, True, False, legacy=True) == ("BLEND", None)


# ---------------------------------------------------------------------------
# 2. "texture has alpha" = the header flag
# ---------------------------------------------------------------------------


def _header(alpha, fmt=7, bag=b""):
    """A PC Texture header with one 4x4 layer whose alpha byte is `alpha`."""
    return tf._tex_header([({0: tf._tex_desc(4, 4, fmt, 1, alpha=alpha)}, "/data/art/x/T.bmp")])


def test_texture_alpha_flag_reads_the_header_byte():
    assert we.texture_alpha_flag(_header(1)) is True
    assert we.texture_alpha_flag(_header(0)) is False
    assert we.texture_alpha_flag(_header(0, fmt=5)) is False
    assert we.texture_alpha_flag(b"\x00" * 64) is None  # not a texture


def test_flag_and_pixels_together():
    # flag set, pixels with alpha: tested
    assert mt.alpha(STD, True, False, True)[0] == "MASK"
    # flag clear, pixels with alpha (a DXT1 punch-through the game does not test): opaque
    assert mt.alpha(STD, False, False, True) == (None, None, None)
    # flag set, alpha 255 everywhere: the test passes everywhere -> opaque ...
    assert mt.alpha(STD, True, False, False) == (None, None, None)
    # ... unless vertex alpha multiplies in: then the test can reject
    assert mt.alpha(STD, True, True, False)[0] == "MASK"
    # blended sheets use the pixels, whatever the flag says
    assert mt.alpha({"renderType": 1}, False, False, True)[0] == "BLEND"
    # one argument for both: as before
    assert mt.alpha(STD, True) == mt.alpha(STD, True, False, True)


def test_texture_has_alpha_prefers_the_recorded_flag():
    assert mt.texture_has_alpha({"textureHasAlpha": False}, True) == (False, True)
    assert mt.texture_has_alpha({"textureHasAlpha": True}, False) == (True, True)
    assert mt.texture_has_alpha({}, True) == (True, False)  # an older extract: the pixels
    assert mt.texture_has_alpha(None, False) == (False, False)
    assert mt.texture_has_alpha({"textureHasAlpha": 1}, False) == (False, False)  # not a flag


def _sheet_header_with_image(alpha):
    """A header that has both a sheet (texture_sheet finds renderType) and one image."""
    props = b"".join(
        tv._prop(0x1DA7D3DD, n, t, v)
        for n, t, v in (("renderType", "integer", 0), ("alphaThreshold", "integer", 95))
    )
    bag = props + b"\x00" * (-len(props) % 4)
    nd = len(bag) // 4
    b = tf._str("Texture") + bytes([nd & 255, nd >> 8, 0, 0]) + bag
    b += b"\x01\x00\x00\x00\x00" + tf._tex_desc(4, 4, 7, 1, alpha=alpha)
    b += b"\x00" * 7 + tf._str("/data/art/x/T.bmp")
    return b + b"\0" * 40


def test_sheet_json_records_the_flag(tmp_path):
    for alpha in (0, 1):
        h = _sheet_header_with_image(alpha)
        assert we.texture_sheet(h)["renderType"] == 0
        assert we.texture_alpha_flag(h) is bool(alpha)
        d = tmp_path / str(alpha)
        d.mkdir()
        we._write_sheet_json(h, d)
        js = we.read_sheet_json(d)
        assert js["textureHasAlpha"] is bool(alpha) and js["alphaThreshold"] == 95
    # a header without an image record: no key (readers fall back to the pixels)
    we._write_sheet_json(tv._sheet_header(), tmp_path)
    assert "textureHasAlpha" not in we.read_sheet_json(tmp_path)


def _png_mode(g, mat):
    tex = g.j["textures"][mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]]
    bv = g.j["bufferViews"][g.j["images"][tex["source"]]["bufferView"]]
    raw = g.bin_chunk[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]]
    return Image.open(io.BytesIO(raw)).mode


def test_model_glb_alpha_test_follows_the_recorded_flag(tmp_path):
    idx = {
        # pixels have alpha, the header says no: the game does not test -> opaque, RGB
        "a": tv._texture_dir(tmp_path, "a", dict(STD, textureHasAlpha=False)),
        # no flag recorded (an older extract): the pixels decide, as before
        "b": tv._texture_dir(tmp_path, "b", dict(STD)),
    }
    g = tv._two_quads(tmp_path, tex_index=idx, has_color=[False, False], engine_materials=True)
    ma, mb = [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]
    assert "alphaMode" not in ma and _png_mode(g, ma) == "RGB"
    assert (mb["alphaMode"], mb["alphaCutoff"]) == ("MASK", 0.372549) and _png_mode(g, mb) == "RGBA"


def test_model_glb_flag_is_ignored_in_legacy_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    idx = {"a": tv._texture_dir(tmp_path, "a", dict(STD, textureHasAlpha=False))}
    g = tv._two_quads(
        tmp_path, tex_index=idx, materials=("a", "a"), has_color=[False] * 2, engine_materials=True
    )
    (m,) = g.j["materials"]
    assert (m["alphaMode"], m["alphaCutoff"]) == ("MASK", 0.372549) and _png_mode(g, m) == "RGBA"


# ---------------------------------------------------------------------------
# 1b. the writers
# ---------------------------------------------------------------------------


def test_model_glb_vertex_alpha_on_a_standard_sheet_is_not_blend(tmp_path):
    idx = {
        "a": tv._texture_dir(tmp_path, "a", dict(STD), alpha=False),
        "b": tv._texture_dir(tmp_path, "b", dict(STD)),
    }
    g = tv._two_quads(
        tmp_path,
        tex_index=idx,
        has_color=[True, True],
        has_alpha=[True, True],
        engine_materials=True,
    )
    ma, mb = [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]
    assert "alphaMode" not in ma and mb["alphaMode"] == "MASK"
    assert ma["extras"]["watchmen"]["vertex_alpha"] is True
    assert mb["extras"]["watchmen"]["vertex_alpha"] is True
    assert ma["extras"]["watchmen"]["materials"] == "engine"  # still an engine material


def test_model_glb_vertex_alpha_on_a_blending_sheet_stays_blend(tmp_path):
    idx = {
        "a": tv._texture_dir(tmp_path, "a", {"renderType": 1, "alphaThreshold": 0}, alpha=False),
        "b": tv._texture_dir(tmp_path, "b", {"renderType": 7}, alpha=False),
    }
    g = tv._two_quads(
        tmp_path,
        tex_index=idx,
        has_color=[True, True],
        has_alpha=[True, True],
        engine_materials=True,
    )
    ma, mb = [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]
    assert ma["alphaMode"] == "BLEND" and mb["alphaMode"] == "BLEND"


def test_model_glb_shares_the_material_when_vertex_alpha_changes_nothing(tmp_path):
    idx = {"same": tv._texture_dir(tmp_path, "same", dict(STD))}
    for order in ([False, True], [True, False]):
        g = tv._two_quads(
            tmp_path,
            tex_index=idx,
            materials=("same", "same"),
            has_color=[True, True],
            has_alpha=order,
            engine_materials=True,
        )
        p0, p1 = g.j["meshes"][0]["primitives"]
        assert p0["material"] == p1["material"] and len(g.j["materials"]) == 1
        (m,) = g.j["materials"]
        assert m["alphaMode"] == "MASK" and m["extras"]["watchmen"]["vertex_alpha"] is True
        assert len(g.j["images"]) == 2  # diffuse + normal, once
    # a type 1 sheet without texture alpha: opaque without, BLEND with vertex alpha
    idx = {"same": tv._texture_dir(tmp_path, "t1", {"renderType": 1}, alpha=False)}
    g = tv._two_quads(
        tmp_path,
        tex_index=idx,
        materials=("same", "same"),
        has_color=[True, True],
        has_alpha=[False, True],
        engine_materials=True,
    )
    assert [m.get("alphaMode") for m in g.j["materials"]] == [None, "BLEND"]


def test_model_glb_faded_standard_sheet_keeps_its_engine_material(tmp_path):
    sheet = dict(STD, opacity=0.5, blendType=0, specularPower=0.5, specularSize=20.0)
    idx = {"a": tv._texture_dir(tmp_path, "a", sheet, alpha=False)}
    g = tv._two_quads(
        tmp_path, tex_index=idx, materials=("a", "a"), has_color=[False] * 2, engine_materials=True
    )
    (m,) = g.j["materials"]
    assert m["alphaMode"] == "BLEND"
    assert m["pbrMetallicRoughness"]["baseColorFactor"] == [1.0, 1.0, 1.0, 0.5]
    assert m["extras"]["watchmen"]["materials"] == "engine"
    assert "blend" not in m["extras"]["watchmen"]  # a plain alpha blend
    # an additive one is written like an additive type-1 layer
    idx = {"a": tv._texture_dir(tmp_path, "g", dict(sheet, blendType=1), alpha=False)}
    g = tv._two_quads(
        tmp_path, tex_index=idx, materials=("a", "a"), has_color=[False] * 2, engine_materials=True
    )
    (m,) = g.j["materials"]
    assert m["alphaMode"] == "BLEND" and m["extras"]["watchmen"]["blend"] == "add"
    assert "emissiveTexture" in m


def _char_layers(sheet, alpha_px=True, flag=None):
    rgba = np.full((2, 2, 4), 200, np.uint8)
    rgba[..., 3] = 255
    if alpha_px:
        rgba[0, 0, 3] = 0
    buf = io.BytesIO()
    Image.fromarray(rgba).save(buf, "PNG")
    lay = {"diffuse": buf.getvalue(), "materials": "engine", "sheet": sheet}
    if alpha_px:
        lay["texAlpha"] = lay["alphaMask"] = True
    if flag is not None:
        lay["texAlphaFlag"] = flag
    return {"mat_body": lay}


def _char(rig, tmp_path, name, layers, has_alpha=True, both=False):
    parts = tv._attr_parts(rig, has_alpha=has_alpha)
    if both:
        parts = [rig.parts[0]] + parts
    out = tmp_path / name
    vg.write_glb(parts, rig.manifest, out, str(rig.bind_npz), textures=layers)
    return parse_glb(out)


def test_character_vertex_alpha_gets_no_blend_twin_on_an_opaque_list(rig, tmp_path):
    g = _char(rig, tmp_path, "a.glb", _char_layers(dict(STD)), both=True)
    (m,) = g.j["materials"]  # one material for the part with and the part without
    assert (m["alphaMode"], m["alphaCutoff"]) == ("MASK", 0.372549)
    assert m["extras"]["watchmen"]["vertex_alpha"] is True
    g = _char(rig, tmp_path, "b.glb", _char_layers(dict(HAIR), alpha_px=False))
    (m,) = g.j["materials"]
    assert "alphaMode" not in m and m["extras"]["watchmen"]["vertex_alpha"] is True


def test_character_vertex_alpha_still_blends_a_blending_sheet(rig, tmp_path):
    g = _char(rig, tmp_path, "a.glb", _char_layers({"renderType": 1}, alpha_px=False), both=True)
    assert [m.get("alphaMode") for m in g.j["materials"]] == [None, "BLEND"]
    prims = g.j["meshes"][0]["primitives"]
    assert sorted(p["material"] for p in prims) == [0, 1]
    g = _char(rig, tmp_path, "b.glb", _char_layers(dict(STD, opacity=0.5)))
    (m,) = g.j["materials"]
    assert m["alphaMode"] == "BLEND"
    assert m["pbrMetallicRoughness"]["baseColorFactor"] == [1.0, 1.0, 1.0, 0.5]


def test_character_alpha_test_follows_the_header_flag(rig, tmp_path):
    # pixels with alpha, flag clear: opaque
    g = _char(rig, tmp_path, "a.glb", _char_layers(dict(STD), flag=False), has_alpha=False)
    assert "alphaMode" not in g.j["materials"][0]
    # flag absent: the pixels, as before
    g = _char(rig, tmp_path, "b.glb", _char_layers(dict(STD)), has_alpha=False)
    assert g.j["materials"][0]["alphaMode"] == "MASK"
    # flag set, opaque pixels: only a part with vertex alpha is alpha-tested
    lay = _char_layers(dict(STD), alpha_px=False, flag=True)
    g = _char(rig, tmp_path, "c.glb", lay, both=True)
    assert [m.get("alphaMode") for m in g.j["materials"]] == [None, "MASK"]
    assert g.j["materials"][1]["alphaCutoff"] == 0.372549


def test_character_legacy_mode_keeps_the_blend_twin(rig, tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    lay = _char_layers(dict(STD))
    del lay["mat_body"]["materials"]  # what char_lib hands over in legacy mode
    g = _char(rig, tmp_path, "a.glb", lay, both=True)
    assert [m.get("alphaMode") for m in g.j["materials"]] == ["MASK", "BLEND"]
    assert all("vertex_alpha" not in json.dumps(m) for m in g.j["materials"])


# ---------------------------------------------------------------------------
# 3. sheet_blend
# ---------------------------------------------------------------------------


def test_sheet_blend_covers_a_sheet_blended_for_its_opacity():
    b = we.sheet_blend({"renderType": 10, "opacity": 0.5, "blendType": 0})
    assert (b["src"], b["dst"], b["op"]) == ("srcAlpha", "invSrcAlpha", "add")  # (5, 6, 1)
    assert b["type"] == "standard" and b["gltf"] == "exact" and b["cause"] == "opacity"
    assert we.sheet_blend({"renderType": 0, "opacity": 0.98, "blendType": 1})["gltf"] == "glow"
    man = we.sheet_blend(
        {"renderType": 0, "opacity": 0.1, "blendType": 3, "srcBlend": 9, "dstBlend": 6}
    )
    assert (man["type"], man["src"], man["cause"]) == ("manual", "dstColor", "opacity")
    # not below 0.99, no opacity, or a type the engine does not move to the blended list
    assert we.sheet_blend({"renderType": 0, "opacity": 0.99, "blendType": 1}) is None
    assert we.sheet_blend({"renderType": 10, "opacity": 1.0}) is None
    assert we.sheet_blend({"renderType": 0, "blendType": 1}) is None
    assert we.sheet_blend({"renderType": 11, "opacity": 0.5}) is None
    assert we.sheet_blend({"renderType": 3, "opacity": 0.5}) is None
    # the blending types say why
    assert we.sheet_blend({"renderType": 1, "opacity": 0.5})["cause"] == "renderType"
    assert we.sheet_blend({"renderType": 9})["cause"] == "renderType"


def test_mtl_no_highlight_still_covers_a_faded_standard_sheet(tmp_path):
    d = tmp_path / "t"
    d.mkdir()
    sheet = dict(STD, opacity=0.5, specularPower=0.0)
    (d / "sheet.json").write_text(json.dumps(sheet), encoding="utf-8")
    assert we._mtl_no_highlight(d, 0.0, None) is True  # as before the opacity rule
    (d / "sheet.json").write_text(json.dumps(dict(sheet, blendType=1)), encoding="utf-8")
    assert we._mtl_no_highlight(d, 0.0, None) is False  # rewritten layer: no engine material
    (d / "sheet.json").write_text(json.dumps(dict(sheet, renderType=1)), encoding="utf-8")
    assert we._mtl_no_highlight(d, 0.0, None) is False


# ---------------------------------------------------------------------------
# 4. grade meta
# ---------------------------------------------------------------------------


def test_platform_adjustment_centres_and_formulas():
    pa = mt.PLATFORM_ADJUSTMENT
    assert pa["pc"] == {"gamma": 0.6, "brightness": 0.6, "contrast": 0.6, "saturation": 0.5}
    assert pa["x360"] == {"gamma": 0.5, "brightness": 0.7, "contrast": 0.6, "saturation": 0.5}
    assert pa["ps3"] == {"gamma": 0.4, "brightness": 0.4, "contrast": 0.2, "saturation": 0.5}
    assert set(pa["formulas"]) == {"contrast", "brightness", "gamma", "saturation"}
    assert pa["multipliers"] == {
        "contrast": 1.1,
        "brightness": 0.5,
        "gamma": 1.2,
        "saturation": 1.5,
    }
    assert "-1" in pa["formulas"]["saturation"] and "start at 0.5" in pa["note"]
    json.dumps(pa)


def test_grade_adjustment_at_the_middle_option_value():
    # PC, option 0.5: m = 2 * 0.6 * 0.5 = 0.6 -> +0.12 gamma, +0.05 brightness, +0.11 contrast
    assert mt.grade_adjustment("pc", 0.5) == {
        "gamma": 0.12,
        "brightness": 0.05,
        "contrast": 0.11,
        "saturation": 0.0,
    }
    # the centre maps to 0.5 on every platform only for the 0.5 centres
    assert mt.grade_adjustment("other", 0.5) == dict.fromkeys(
        ("gamma", "brightness", "contrast", "saturation"), 0.0
    )
    # both ends: m(0) = 0 and m(1) = 1 whatever the centre
    for plat in ("pc", "x360", "ps3"):
        assert mt.grade_adjustment(plat, 0.0)["gamma"] == -0.6
        assert mt.grade_adjustment(plat, 1.0)["saturation"] == 0.75
    assert mt.grade_adjustment("ps3", 0.5)["contrast"] == round((0.2 - 0.5) * 1.1, 6)


def test_grade_formula_says_what_enable_filters_gates():
    f = mt.GRADE_FORMULA
    assert "NOT under enableFilters" in f and "enableDOF" in f and "enableAA" in f
    assert "noiseTexture" in f and "noiseIntensity > 0" in f
    assert "first enabled GFXEffect" in f and "platform_adjustment" in f
    assert "applied only when enableFilters" not in f  # the old closing clause


def _gfx(props):
    base = [["name", "string", "RS GFX"], ["gamma", "number", 1.2]]
    return {"nodes_full": [{"type": "FXGfxEffectCtrl(GFXEffect)", "props": base + props}]}


def test_fragment_grades_reads_the_new_node_keys():
    (g,) = mt.fragment_grades(
        _gfx(
            [
                ["skyBoxBlur", "number", 0.25],
                ["edgeDetectGradient", "number", 8.0],
                ["edgeDetectCutoff", "integer", 2],
                ["noiseTexture", "string", "/Art/Effects/Noise.bmp"],
                ["shadowBlurPower", "number", 1.0],
            ]
        )
    )
    assert g["skyboxblur"] == 0.25 and g["edgedetectgradient"] == 8.0
    assert g["edgedetectcutoff"] == 2 and isinstance(g["edgedetectcutoff"], int)
    assert g["noisetexture"] == "/Art/Effects/Noise.bmp" and g["shadowblurpower"] == 1.0
    # an empty texture name is kept: it is what switches the noise off
    (g,) = mt.fragment_grades(_gfx([["noiseTexture", "string", ""]]))
    assert g["noisetexture"] == ""


def test_noise_intensity_alias_of_the_data_is_not_a_second_key():
    # the nodes store "noiseIntensity" and a misspelt twin registered on the same
    # setter ("noiseIntensisty", 0x4c0af2); only the first is exported
    (g,) = mt.fragment_grades(
        _gfx([["NoiseIntensity", "number", 0.35], ["noiseIntensisty", "number", 0.35]])
    )
    assert g["noiseintensity"] == 0.35 and "noiseintensisty" not in g


def test_level_grades_format_and_platform_adjustment(tmp_path):
    lv = tmp_path / "extracted" / "Levels" / "L"
    lv.mkdir(parents=True)
    (lv / "Art.fragment").write_bytes(b"....GFXEffect....")
    (lv / "Other.fragment").write_bytes(b"nothing here")
    frag = _gfx([["noiseIntensity", "number", 0.1]])
    out = mt.level_grades(tmp_path, lambda p: frag)
    assert out["format"] == "watchmen-grade-meta/1"
    assert out["platform_adjustment"]["pc"]["gamma"] == 0.6 and out["formula"] == mt.GRADE_FORMULA
    assert list(out["fragments"]) == ["Levels/L/Art.fragment"]
    assert out["fragments"]["Levels/L/Art.fragment"][0]["noiseintensity"] == 0.1
    json.dumps(out)
