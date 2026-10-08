"""Sheet opacity, glow / emission and the extra sheet values in the material
writers; the grade options' start value.

* a sheet's opacity below 0.99 makes a part blended for render types 0 and 10
  (0x5739d0) and fades a SkyBox (7) sheet, whose pass blends with the opacity as
  the shader's alpha factor (0x589dd9); the MTL writes it as `d`;
* a glow layer is an emission map where the first sheet's selfIlluminance is
  above 0 (the engine adds selfIlluminanceColor * selfIlluminance * glow): the
  GLB gets an emissive texture, the MTL `Ke` + `map_Ke`; with selfIlluminance 0
  the layer is only named;
* sheet_values of a GLB material carry the blend triple, the normal-map switch,
  the wet-surface pair and the layer overrides.

Synthetic fixtures only."""

import json

import numpy as np
import pytest
from PIL import Image

import materials as mt
import rig_glb
import watchmen_extract as we
from conftest import parse_glb

import test_texture_sheets as ts
import test_vcolor as tv


# ---------------------------------------------------------------------------
# alpha
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rt", [0, 10, None])
def test_low_opacity_blends_a_type_0_or_10_sheet(rt):
    sheet = {"opacity": 0.5, "alphaThreshold": 95}
    if rt is not None:
        sheet["renderType"] = rt
    assert mt.alpha(sheet, True, False) == ("BLEND", None, 0.5)
    assert mt.alpha(sheet, False, False) == ("BLEND", None, 0.5)


@pytest.mark.parametrize("rt", [2, 3, 4, 5, 6, 8, 9, 11])
def test_low_opacity_does_not_move_another_type_to_the_blended_list(rt):
    sheet = {"opacity": 0.5, "alphaThreshold": 95, "renderType": rt}
    # alpha-tested when the diffuse has alpha, opaque otherwise -- as with opacity 1
    full = dict(sheet, opacity=1.0)
    assert mt.alpha(sheet, True, False) == mt.alpha(full, True, False)
    assert mt.alpha(sheet, False, False) == (None, None, None)
    assert mt.alpha(sheet, True, False)[0] == "MASK"


@pytest.mark.parametrize("op", [0.0, 0.25])
def test_a_skybox_sheet_is_faded_by_its_opacity(op):
    """Sky pass: alpha = texture alpha * vertex alpha * sheet opacity, blended
    (0x589dd9, SkyBoxPS) -- opacity 0 is an invisible layer, with or without
    vertex alpha or texture alpha (Part 1: skyflash, moon_01)."""
    sheet = {"renderType": 7, "opacity": op, "alphaThreshold": 95, "blendType": 0}
    assert mt.alpha(sheet, False, False) == ("BLEND", None, op)
    assert mt.alpha(sheet, False, True) == ("BLEND", None, op)
    assert mt.alpha(sheet, True, False) == ("BLEND", None, op)
    assert mt.alpha(sheet, True, False, pixel_alpha=False) == ("BLEND", None, op)
    assert rig_glb.material_alpha(sheet, False, False) == ("BLEND", None)


def test_a_skybox_sheet_at_full_opacity_keeps_its_rule():
    sheet = {"renderType": 7, "opacity": 1.0, "alphaThreshold": 95}
    assert mt.alpha(sheet, False, False) == (None, None, None)
    assert mt.alpha(sheet, False, True) == ("BLEND", None, None)
    assert mt.alpha(sheet, True, False)[0] == "MASK"
    assert mt.alpha(dict(sheet, opacity=0.99), False, False) == (None, None, None)
    assert mt.FADED_BY_OPACITY == (None, 0, 7, 10)


def test_a_sprite_sheet_is_not_faded_without_vertex_alpha():
    # list 9 is not drawn on a model part; only varying vertex alpha gives BLEND
    sheet = {"renderType": 9, "opacity": 0.0}
    assert mt.alpha(sheet, False, False) == (None, None, None)
    assert mt.alpha(sheet, False, True) == ("BLEND", None, 0.0)


def test_a_blend_sheet_keeps_its_opacity_factor():
    assert mt.alpha({"renderType": 1, "opacity": 0.5}, False, False) == ("BLEND", None, 0.5)
    assert mt.alpha({"renderType": 1, "opacity": 0.995}, True, False) == ("BLEND", None, None)
    assert mt.alpha({"renderType": 0, "opacity": 0.99}, False, False) == (None, None, None)


# ---------------------------------------------------------------------------
# sheet values in the material
# ---------------------------------------------------------------------------
def test_extras_carry_the_new_sheet_values_and_the_overrides():
    for k in (
        "blendType",
        "srcBlend",
        "dstBlend",
        "blendOp",
        "writeDepthBuffer",
        "normalMapPower",
        "enableNormalMapping",
        "fresnelPower",
        "maxReflection",
    ):
        assert k in mt.EXTRA_KEYS
    sheet = {
        "renderType": 0,
        "specularSize": 20.0,
        "specularPower": 1.0,
        "blendType": 3,
        "srcBlend": 5,
        "dstBlend": 2,
        "blendOp": 1,
        "fresnelPower": 2.5,
        "enableNormalMapping": False,
        "overrides": {"diffuse": "/art/t/Heavy_ButtonBlue.bmp"},
    }
    P = mt.engine_material(sheet)
    ex = P["extras"]
    assert ex["blendType"] == 3 and ex["dstBlend"] == 2 and ex["fresnelPower"] == 2.5
    assert ex["enableNormalMapping"] is False
    assert ex["overrides"] == {"diffuse": "/art/t/Heavy_ButtonBlue.bmp"}
    assert ex["overrides"] is not sheet["overrides"]
    assert "overrides" not in mt.engine_material({"renderType": 0})["extras"]
    json.dumps(ex)


def test_grade_options_start_at_one_half():
    pa = mt.PLATFORM_ADJUSTMENT
    assert pa["option_default"] == 0.5
    for platform in ("pc", "x360", "ps3"):
        assert mt.grade_adjustment(platform, pa["option_default"]) == pytest.approx(
            pa["default_offsets"][platform]
        )
    assert pa["default_offsets"]["pc"] == {
        "gamma": 0.12,
        "brightness": 0.05,
        "contrast": 0.11,
        "saturation": 0.0,
    }
    assert "0x82be66" in pa["note"] and "console executables were not read" in pa["note"]


# ---------------------------------------------------------------------------
# MTL
# ---------------------------------------------------------------------------
def test_mtl_opacity_rule():
    f = we._mtl_opacity
    assert f({"opacity": 0.69, "renderType": 0}) == pytest.approx(0.69)
    assert f({"opacity": 0.69, "renderType": 10}) == pytest.approx(0.69)
    assert f({"opacity": 0.69, "renderType": 7}) == pytest.approx(0.69)  # sky pass
    assert f({"opacity": 0.0, "renderType": 7}) == 0.0
    assert f({"opacity": 0.69, "renderType": 9}) is None
    assert f({"opacity": 0.69, "renderType": 5}) is None  # not moved to the blended list
    assert f({"opacity": 0.69}) is None  # no sheet values: nothing claimed
    assert f({"opacity": 0.995, "renderType": 0}) is None and f({}) is None
    assert f({"opacity": "x", "renderType": 0}) is None


def test_mtl_emission_rule():
    f = we._mtl_emission
    assert f({}) == (True, None)  # no sheet values: the layer is linked as before
    assert f({"selfIlluminance": 0.0}) == (False, None)
    lit, ke = f({"selfIlluminance": 0.5, "selfIlluminanceColor": [1.0, 0.5, 0.25]})
    assert lit is True and ke == pytest.approx([0.5, 0.25, 0.125])
    lit, ke = f({"selfIlluminance": 3.0})
    assert lit is True and ke == [1.0, 1.0, 1.0]  # clamped: MTL has no strength


def _tex(tmp_path, name, sheet):
    d = tv._texture_dir(tmp_path, name, sheet, alpha=False)
    Image.fromarray(np.full((4, 4, 3), (250, 200, 40), np.uint8)).save(d / "2_glow_4x4_DXT1.png")
    return d


def _mtl(tmp_path, sheet, monkeypatch):
    monkeypatch.setitem(we._RIG, "on", False)
    h, s = tv._rigid_model()
    idx = {"wall_01": _tex(tmp_path, "Wall_01", sheet)}
    assert we.decode_model(h, s, tmp_path / "m.obj", idx, None)
    return (tmp_path / "m.mtl").read_text().splitlines()


def test_mtl_links_a_glow_map_the_sheet_lights(tmp_path, monkeypatch):
    lines = _mtl(
        tmp_path,
        {
            "renderType": 0,
            "opacity": 0.69,
            "selfIlluminance": 0.5,
            "selfIlluminanceColor": [1.0, 1.0, 0.5],
        },
        monkeypatch,
    )
    assert "Ke 0.5000 0.5000 0.2500" in lines
    assert any(x.startswith("map_Ke ") and x.endswith("2_glow_4x4_DXT1.png") for x in lines)
    assert "d 0.6900" in lines  # after map_d: drawn blended for the sheet's opacity
    assert lines.index("d 0.6900") == [i for i, x in enumerate(lines) if x[:6] == "map_d "][0] + 1
    assert not any("_specMap_" in x for x in lines)


def test_mtl_names_a_glow_map_the_first_sheet_does_not_light(tmp_path, monkeypatch):
    sheet = {
        "renderType": 0,
        "selfIlluminance": 0.0,
        "sheets": [
            {"name": "off", "renderType": 0, "selfIlluminance": 0.0},
            {"name": "Lit", "renderType": 0, "selfIlluminance": 1.0},
        ],
    }
    lines = _mtl(tmp_path, sheet, monkeypatch)
    assert not any(x.startswith(("map_Ke", "Ke ")) for x in lines)
    (note,) = [x for x in lines if x.startswith("# glow layer not linked")]
    assert "1 other sheet(s)" in note and note.endswith("2_glow_4x4_DXT1.png")
    assert not any(x.startswith("d ") for x in lines)


# ---------------------------------------------------------------------------
# GLB
# ---------------------------------------------------------------------------
def _glb_material(tmp_path, sheet, monkeypatch):
    monkeypatch.setitem(we._RIG, "on", True)
    monkeypatch.setitem(we._RIG, "loaded", False)
    monkeypatch.setitem(we._RIG, "attrs", True)
    h, s = tv._rigid_model()
    idx = {"wall_01": _tex(tmp_path, "Wall_01", sheet)}
    assert we.decode_model(h, s, tmp_path / "m.obj", idx, None)
    return parse_glb(tmp_path / "m.glb").j["materials"][0]


def test_glb_glow_map_is_emissive_where_the_sheet_says_so(tmp_path, monkeypatch):
    m = _glb_material(
        tmp_path, {"renderType": 0, "selfIlluminance": 1.0, "specularPower": 1.0}, monkeypatch
    )
    assert "emissiveTexture" in m and m["emissiveFactor"] == [1.0, 1.0, 1.0]
    assert m["extras"]["watchmen"]["sheet_values"]["selfIlluminance"] == 1.0


def test_glb_glow_map_is_not_emissive_with_self_illuminance_zero(tmp_path, monkeypatch):
    m = _glb_material(
        tmp_path, {"renderType": 0, "selfIlluminance": 0.0, "specularPower": 1.0}, monkeypatch
    )
    assert "emissiveTexture" not in m and "emissiveFactor" not in m
    # a glow map is not a specular-colour map either
    assert "specularColorTexture" not in (m.get("extensions") or {}).get(
        "KHR_materials_specular", {}
    )


def test_glb_low_opacity_fades_a_type_0_sheet_only(tmp_path, monkeypatch):
    m = _glb_material(tmp_path, {"renderType": 0, "opacity": 0.5}, monkeypatch)
    assert m["alphaMode"] == "BLEND" and m["pbrMetallicRoughness"]["baseColorFactor"][3] == 0.5
    sub = tmp_path / "glass"
    sub.mkdir()
    m = _glb_material(sub, {"renderType": 5, "opacity": 0.5}, monkeypatch)
    assert m.get("alphaMode") in (None, "OPAQUE")
    assert (m["pbrMetallicRoughness"].get("baseColorFactor") or [1, 1, 1, 1])[3] == 1


def test_glb_and_mtl_fade_a_skybox_sheet_with_opacity_0(tmp_path, monkeypatch):
    m = _glb_material(tmp_path, {"renderType": 7, "opacity": 0.0}, monkeypatch)
    assert m["alphaMode"] == "BLEND" and m["pbrMetallicRoughness"]["baseColorFactor"][3] == 0.0
    mtl = next(tmp_path.rglob("*.mtl")).read_text()
    assert "\nd 0.0000\n" in mtl


# ---------------------------------------------------------------------------
# sheet values against the gameplay captures
# ---------------------------------------------------------------------------
#: what the game sent to the pixel shader for these sheets in the D3D9 gameplay
#: captures (c2.xy = specularSize, specularPower; c12.x = reflectionLightFactor;
#: c14 = fallOffColor, fallOffPower), float32 as captured.  The exported
#: sheet.json of the ten textures holds the same numbers (measured, PC Part 2).
CAPTURED = {
    "FimaleGimpSuits1": (43.0000076, 1.169999, 0.1, (1, 1, 1, 0.25)),
    "FemaleSkinBody_White": (15.0, 0.05, None, (1, 1, 1, 0.25)),
    "Heavy_Outfit1": (41.249989, 3.880001, None, (0, 0, 0, 0.3)),
    "Heavy_Hands": (5.600001, 0.899996, None, (0, 0, 0, 0.27)),
    "Heavy_Hair_LongSideParting_Brown": (4.449995, 4.710001, None, (0, 0, 0, 0.12)),
    "sunglass": (28.05, 3.38, 0.6, None),
    "Heavy_Button": (62.65, 1.29, None, None),
}


@pytest.mark.parametrize("name", sorted(CAPTURED))
def test_sheet_reader_returns_the_captured_constants(name):
    """A sheet stored with the captured float32 values reads back as those values
    and reaches the material's sheet_values unchanged."""
    size, power, refl, fall = CAPTURED[name]
    props = {"specularSize": float(size), "specularPower": float(power)}
    if refl is not None:
        props["reflectionLightFactor"] = float(refl)
    if fall is not None:
        props["fallOffPower"] = float(fall[3])
    (sh,) = we.texture_sheets(ts._header(ts._sheet(0x1DA7D3DD, "default", 5, **props)))
    f32 = lambda v: float(np.float32(v))
    assert sh["specularSize"] == pytest.approx(f32(size), abs=0, rel=1e-7)
    assert sh["specularPower"] == pytest.approx(f32(power), abs=0, rel=1e-7)
    if refl is not None:
        assert sh["reflectionLightFactor"] == pytest.approx(f32(refl), rel=1e-7)
    if fall is not None:
        assert sh["fallOffPower"] == pytest.approx(f32(fall[3]), rel=1e-7)
    ex = mt.engine_material(sh)["extras"]
    assert ex["specularSize"] == sh["specularSize"] and ex["specularPower"] == sh["specularPower"]
