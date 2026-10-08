"""Engine materials (wlib/materials.py), buffer kinds, LOD metadata, level grade.

The game's colour pass (DeferredMain2PS; REDeferredMain2::SetMaterial 0x571d5d)
gives every material a specular lobe of exponent specularSize (times
specSize.g^2*256+1 with a specSize layer) and strength specularPower, adds
selfIlluminance * glow to both light sums, and routes the material by renderType
(0x5739d0).  `--materials engine` (default) writes that into the glTF material;
`--materials legacy` keeps the old writers byte for byte.  Each test fails on
the tree before this change.
"""

import io
import json
import struct

import numpy as np
import pytest

import char_lib
import characters_export as ce
import materials as mt
import rig_glb
import variant_glb as vg
import watchmen_extract as we
import test_formats_v2 as tf
import test_texture_sheets as ts
from conftest import parse_glb

Image = pytest.importorskip("PIL.Image")


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("WATCHMEN_MATERIALS", raising=False)
    monkeypatch.delenv("WATCHMEN_MATERIAL_OPTS", raising=False)
    for c in (char_lib._TEXIDX, char_lib._LAYERCACHE, ce._FRAG_NODES, ce._TEX_SHEETS):
        c.clear()
    yield
    for c in (char_lib._TEXIDX, char_lib._LAYERCACHE, ce._FRAG_NODES, ce._TEX_SHEETS):
        c.clear()


def _img(data):
    return Image.open(io.BytesIO(data))


# ---------------------------------------------------------------------------
# 1. the formulas
# ---------------------------------------------------------------------------


def test_mode_default_and_switch(monkeypatch):
    assert mt.mode() == "engine" and mt.MODES == ("engine", "legacy")
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    assert mt.mode() == "legacy" and mt.mode("engine") == "engine"
    with pytest.raises(ValueError):
        mt.mode("shiny")


def test_exponent_roughness_and_reflectance():
    # exponent: the sheet's specularSize, times (g^2 * 256 + 1) with a specSize texel g
    assert mt.exponent(43.0) == 43.0
    assert mt.exponent(43.0, 0.5) == pytest.approx((0.25 * 256 + 1) * 43.0)
    assert mt.exponent(None) == 15.0  # the engine default of the property
    # glTF roughness is perceptual: alpha = roughness^2 and alpha^2 = 2 / (n + 2)
    assert float(mt.roughness(43.0)) == pytest.approx((2.0 / 45.0) ** 0.25)
    assert float(mt.roughness(2.0)) < 1.0 and float(mt.roughness(0.0)) == 1.0
    assert float(mt.roughness(1e9)) == 0.045  # never a perfect mirror
    # a tighter lobe is glossier (the old bake had it the other way round)
    assert float(mt.roughness(400.0)) < float(mt.roughness(15.0))
    # peak match: F0 = 4 alpha^2 I = 8 I / (n + 2)
    assert float(mt.f0(43.0, 1.17)) == pytest.approx(8 * 1.17 / 45.0)
    assert float(mt.f0(15.0, 0.0)) == 0.0 and float(mt.f0(1.0, 50.0)) == 1.0


def test_gradient_is_the_engines_keyed_lookup():
    # FUN_00413360 / FUN_00411783: keys at int(pos * 1000), clamped ends, linear between
    g = mt.gradient("0.293000,0.3,0.3,0.3,1.0|0.546000,0.0,0.0,0.0,1.0|0.991,0.1,0.2,0.3,1|")
    assert g(0.0) == [0.3, 0.3, 0.3] and g(0.2929) == [0.3, 0.3, 0.3]
    assert g(1.0) == [0.1, 0.2, 0.3]
    mid = g((0.293 + 0.546) / 2)
    assert mid[0] == pytest.approx(0.15, abs=2e-3)
    assert mt.gradient("")(0.5) == [1.0, 1.0, 1.0]  # no key: white
    assert mt.gradient("0.5,0.2,0.4,0.6,1|")(0.9) == [0.2, 0.4, 0.6]


def test_alpha_mode_follows_the_render_list():
    hair = {"renderType": 10, "alphaThreshold": 95, "twoSided": True, "opacity": 1.0}
    # falloff / standard / wet: opaque, alpha-TESTED when the diffuse has alpha (hair too)
    assert mt.alpha(hair, True) == ("MASK", round(95 / 255.0, 6), None)
    assert mt.alpha(hair, False) == (None, None, None)
    assert mt.alpha(dict(hair, renderType=11), True)[0] == "MASK"
    assert mt.alpha(dict(hair, alphaThreshold=0), True) == (None, None, None)
    # "Standard with blending" and opacity < 0.99 go to the blended list (0x5739d0)
    assert mt.alpha({"renderType": 1}, True) == ("BLEND", None, None)
    assert mt.alpha({"renderType": 0, "opacity": 0.7}, False) == ("BLEND", None, 0.7)
    assert mt.alpha({"renderType": 0, "opacity": 0.995}, False) == (None, None, None)
    # vertex alpha multiplies the texture alpha but does not choose the list
    assert mt.alpha(hair, True, vertex_alpha=True)[0] == "MASK"
    assert mt.alpha(None, True) == ("MASK", 0.5, None)


# ---------------------------------------------------------------------------
# 2. sheet + layers -> material values
# ---------------------------------------------------------------------------

SUIT = dict(renderType=10, specularSize=43.0, specularPower=1.17, twoSided=True)


def test_no_specular_power_means_no_specular():
    P = mt.engine_material(dict(SUIT, specularPower=0.0), Image.new("RGB", (4, 4), (128,) * 3))
    assert P["specular"] == {"specularFactor": 0.0} and P["spec"] is None and P["ior"] is None
    # ... unless a cube reflection keeps a floor at reflectionLightFactor
    P = mt.engine_material(
        dict(SUIT, specularPower=0.0, reflectionType=2, reflectionLightFactor=0.1),
        Image.new("RGB", (4, 4), (128,) * 3),
    )
    f0 = ((P["ior"] - 1) / (P["ior"] + 1)) ** 2
    assert f0 == pytest.approx(0.1, abs=2e-3) and P["specular"] == {"specularFactor": 1.0}
    # the planar type and the bare factor do not
    P = mt.engine_material(dict(SUIT, specularPower=0.0, reflectionLightFactor=0.1), None)
    assert P["specular"] == {"specularFactor": 0.0}


def test_flat_material_plain_formulas():
    P = mt.engine_material(SUIT, None, opts={"display": 0})
    assert P["roughnessFactor"] == pytest.approx((2 / 45.0) ** 0.25, abs=1e-4)
    assert P["mr"] is None and P["spec"] is None
    f0 = ((P["ior"] - 1) / (P["ior"] + 1)) ** 2  # above 0.04: carried by the ior
    assert f0 == pytest.approx(8 * 1.17 / 45.0, abs=2e-3)
    weak = mt.engine_material(
        dict(SUIT, specularPower=0.05, specularSize=15.0), None, opts={"display": 0}
    )
    assert weak["ior"] is None  # below 0.04: KHR_materials_specular strength at ior 1.5
    assert weak["specular"]["specularFactor"] == pytest.approx(8 * 0.05 / 17 / 0.04, abs=1e-3)


def test_display_space_lobe_is_default():
    # the engine adds the highlight to DISPLAY values; a linear-light viewer needs a
    # narrower lobe and a base-dependent strength to show the same thing on screen
    img = Image.new("RGB", (4, 4), (10, 10, 10))
    dark = mt.engine_material(SUIT, img)
    plain = mt.engine_material(SUIT, img, opts={"display": 0})
    light = mt.engine_material(SUIT, Image.new("RGB", (4, 4), (240, 240, 240)))
    assert dark["roughnessFactor"] < plain["roughnessFactor"]
    assert light["roughnessFactor"] < plain["roughnessFactor"]
    assert dark["ior"] != plain["ior"] and dark["ior"] != light["ior"]


def test_spec_size_layer_gives_a_roughness_texture():
    ss = Image.fromarray(np.array([[0, 255], [128, 64]], np.uint8), "L")
    P = mt.engine_material(
        SUIT, Image.new("RGB", (2, 2), (128,) * 3), None, ss, opts={"display": 0}
    )
    assert P["roughnessFactor"] == 1.0
    orm = np.asarray(_img(P["mr"]))
    assert orm.shape == (2, 2, 3) and (orm[..., 0] == 255).all() and (orm[..., 2] == 0).all()
    want = np.round(
        mt.roughness(mt.exponent(43.0, np.array([[0, 1], [128 / 255, 64 / 255]]))) * 255
    )
    assert (orm[..., 1] == want).all()
    assert orm[0, 0, 1] > orm[1, 1, 1] > orm[0, 1, 1]  # higher specSize = tighter = smoother
    # the strength follows the texel exponent too: specularColorTexture (sRGB), max = 1
    sp = np.asarray(_img(P["spec"]))
    assert sp[0, 0, 0] == 255 and sp[0, 1, 0] < sp[1, 1, 0] < 255


def test_missing_layers_use_the_engine_defaults():
    # specular white, specSize black (n = specularSize), glow white
    P = mt.engine_material(dict(SUIT, selfIlluminance=0.5), Image.new("RGB", (2, 2), (51,) * 3))
    assert P["mr"] is None and P["spec"] is None
    assert P["emissiveFactor"] == [1.0, 1.0, 1.0] and P["emissive"] is not None


def test_emission_is_glow_times_albedo_plus_specular():
    alb = Image.new("RGB", (2, 2), (51, 51, 51))  # 0.2
    spec = Image.new("RGB", (2, 2), (102, 102, 102))  # 0.4
    glow = Image.fromarray(np.array([[[255] * 3, [0] * 3], [[255] * 3, [0] * 3]], np.uint8), "RGB")
    sheet = dict(SUIT, selfIlluminance=0.5, selfIlluminanceColor=[1.0, 0.5, 0.0])
    P = mt.engine_material(sheet, alb, spec, None, glow, opts={"display": 0})
    e = np.asarray(_img(P["emissive"])).astype(float) / 255.0
    # display values G * (albedo + specTex) = 0.5 * (0.2 + 0.4) * colour, as linear radiance
    want = mt.srgb_to_linear(np.array([0.3, 0.15, 0.0]))
    assert mt.srgb_to_linear(e[0, 0]) == pytest.approx(want, abs=4e-3)
    assert (e[0, 1] == 0).all() and P["emissiveStrength"] is None
    # above 1: KHR_materials_emissive_strength carries the scale
    P = mt.engine_material(
        dict(sheet, selfIlluminance=2.0, selfIlluminanceColor=[1, 1, 1]),
        alb,
        spec,
        None,
        glow,
        opts={"display": 0},
    )
    assert P["emissiveStrength"] == pytest.approx(float(mt.srgb_to_linear(1.2)), abs=1e-3)
    assert np.asarray(_img(P["emissive"]))[0, 0, 0] == 255
    # negative self-illumination (it darkens in the game) and zero: no emission
    for si in (0.0, -0.27):
        assert mt.engine_material(dict(sheet, selfIlluminance=si), alb)["emissiveFactor"] is None


def test_falloff_parameters_stay_in_extras_and_sheen_is_optional():
    sheet = dict(
        SUIT, fallOffPower=0.25, fallOffColor=[1.0, 1.0, 1.0], depthFadeGradient="0.0,1,0.5,0.25,1|"
    )
    P = mt.engine_material(sheet, None)
    assert P["sheen"] is None
    assert P["extras"]["depthFadeGradient"] == sheet["depthFadeGradient"]
    assert P["extras"]["fallOffPower"] == 0.25 and P["extras"]["renderType"] == 10
    P = mt.engine_material(sheet, None, opts={"sheen": 1})
    c = P["sheen"]["sheenColorFactor"]
    assert c[0] > c[1] > c[2] > 0 and P["sheen"]["sheenRoughnessFactor"] == 0.5
    assert mt.engine_material(dict(sheet, renderType=0), None, opts={"sheen": 1})["sheen"] is None


def test_apply_writes_extensions_and_never_metal():
    j = {"images": [], "textures": []}
    mat = {"name": "m", "pbrMetallicRoughness": {"metallicFactor": 0.4, "roughnessFactor": 0.85}}
    added = []

    def add(data, label):
        added.append(label)
        return len(added) - 1

    ss = Image.fromarray(np.array([[0, 255], [128, 64]], np.uint8), "L")
    sheet = dict(SUIT, selfIlluminance=3.0, fallOffPower=0.25)
    mt.apply(j, mat, mt.engine_material(sheet, Image.new("RGB", (2, 2), (200,) * 3), None, ss), add)
    assert mat["pbrMetallicRoughness"]["metallicFactor"] == 0
    assert mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] == {"index": 0}
    assert added == ["mr", "spec", "emissive"]
    assert set(j["extensionsUsed"]) == {
        "KHR_materials_specular",
        "KHR_materials_ior",
        "KHR_materials_emissive_strength",
    }
    assert mat["extensions"]["KHR_materials_specular"]["specularColorTexture"] == {"index": 1}
    assert mat["emissiveTexture"] == {"index": 2}
    w = mat["extras"]["watchmen"]
    assert w["materials"] == "engine" and w["sheet_values"]["specularSize"] == 43.0


# ---------------------------------------------------------------------------
# 3. the writers
# ---------------------------------------------------------------------------

HAIR = "/art/c/dom/textures/Hair.bmp"
HAIR_HDR = ts._header(
    ts._sheet(
        0x4444,
        "default",
        ts.WHITE,
        renderType=10,
        alphaThreshold=95,
        twoSided=True,
        specularSize=1.0,
        specularPower=0.13,
    )
)
SKIN_HDR = ts._header(
    ts._sheet(0x5555, "default", ts.RED_ID, renderType=10, specularSize=15.0, specularPower=0.0)
)


def _tree(root):
    d = ts._texture(root, HAIR, (200, 120, 60), header=HAIR_HDR, normal=(128, 128, 255), alpha=200)
    Image.new("RGB", (4, 4), (128, 128, 128)).save(d / "2_specMap_4x4_DXT1.png")
    Image.new("L", (4, 4), 200).save(d / "roughnessGen.png")
    ts._texture(root, ts.SKIN, (240, 200, 180), header=SKIN_HDR)
    return [str(root / "textures")]


def _char_glb(tmp_path, rig):
    roots = _tree(tmp_path)
    base = rig.parts[0]
    parts = [
        tuple(base[:5]) + (we.texture_ref(HAIR),),
        tuple(base[:5]) + (we.texture_ref(ts.SKIN),),
    ]
    tex = char_lib.find_textures(parts, roots)
    vg.write_glb(parts, rig.manifest, tmp_path / "c.glb", str(rig.bind_npz), textures=tex)
    g = parse_glb(tmp_path / "c.glb")
    return g, [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]


def test_character_glb_engine_materials(tmp_path, rig):
    g, (hair, skin) = _char_glb(tmp_path, rig)
    # hair: alpha-tested at 95/255 (the texture's alpha is 200: never below 128), two-sided
    assert hair["alphaMode"] == "MASK" and hair["alphaCutoff"] == round(95 / 255.0, 6)
    assert hair["doubleSided"] is True and skin["doubleSided"] is False
    assert "alphaMode" not in skin
    # roughness from the sheet, not roughnessGen.png and not 0.85
    assert "metallicRoughnessTexture" not in hair["pbrMetallicRoughness"]
    assert 0.5 < hair["pbrMetallicRoughness"]["roughnessFactor"] <= 1.0
    assert hair["pbrMetallicRoughness"]["roughnessFactor"] != 0.85
    sp = hair["extensions"]["KHR_materials_specular"]
    assert (
        sp["specularFactor"] > 0 and "specularColorTexture" not in sp
    )  # a flat specMap is a factor
    assert skin["extensions"]["KHR_materials_specular"] == {"specularFactor": 0.0}
    assert "KHR_materials_specular" in g.j["extensionsUsed"]
    assert hair["extras"]["watchmen"]["sheet_values"]["renderType"] == 10
    assert skin["extras"]["watchmen"]["materials"] == "engine"


def test_character_glb_legacy_materials_are_the_old_ones(tmp_path, rig, monkeypatch):
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    g, (hair, skin) = _char_glb(tmp_path, rig)
    assert hair["doubleSided"] is True and skin["doubleSided"] is True
    assert "alphaMode" not in hair  # the old rule: only below alpha 128
    assert hair["pbrMetallicRoughness"]["roughnessFactor"] == 1.0  # roughnessGen.png
    assert "metallicRoughnessTexture" in hair["pbrMetallicRoughness"]
    assert list(hair["extensions"]["KHR_materials_specular"]) == ["specularColorTexture"]
    assert skin["pbrMetallicRoughness"]["roughnessFactor"] == 0.85 and "extensions" not in skin
    assert "extras" not in hair and "extras" not in skin


def _static_glb(tmp_path, monkeypatch=None):
    _tree(tmp_path)
    idx = we.build_texture_index(tmp_path / "textures")
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
    N = np.array([[0, 0, 1]] * 3, np.float32)
    rig_glb.build_rigged_glb(
        tmp_path / "s.glb",
        V,
        None,
        [(0, 0), (1, 0), (0, 1)],
        None,
        None,
        [(0, 1, 2)],
        [(0, 3, 0, 1, 44)],
        [we.texture_ref(HAIR)],
        idx,
        {"bone_count": 0, "bones": []},
        None,
        None,
        static=True,
        normals=N,
        engine_materials=True,
    )
    return parse_glb(tmp_path / "s.glb")


def test_extract_glb_engine_materials(tmp_path):
    g = _static_glb(tmp_path)
    m = g.j["materials"][0]
    assert m["alphaMode"] == "MASK" and m["doubleSided"] is True
    assert m["pbrMetallicRoughness"]["roughnessFactor"] != 0.85
    assert m["extensions"]["KHR_materials_specular"]["specularFactor"] > 0
    assert m["extras"]["watchmen"]["sheet_values"]["specularPower"] == pytest.approx(0.13)


def test_extract_glb_legacy_materials(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    m = _static_glb(tmp_path).j["materials"][0]
    assert m["pbrMetallicRoughness"]["roughnessFactor"] == 0.85
    assert "extensions" not in m and "extras" not in m


def test_mtl_roughness_bake(tmp_path, monkeypatch):
    d = tmp_path / "t.bmp"
    d.mkdir()
    ss = d / "2_specSize_2x2_L8.png"
    Image.fromarray(np.array([[0, 255], [128, 64]], np.uint8), "L").save(ss)
    out = we._make_roughness_engine(d, ss, 43.0)
    assert out.name == "roughnessEngine.png"
    got = np.asarray(Image.open(out))
    assert got[0, 0] == round(float(mt.roughness(43.0)) * 255) and got[0, 1] < got[1, 1] < got[0, 0]
    d2 = tmp_path / "u.bmp"
    d2.mkdir()
    flat = np.asarray(Image.open(we._make_roughness_engine(d2, None, 15.0)))
    assert flat.shape == (4, 4) and flat[0, 0] == round((2 / 17.0) ** 0.25 * 255)
    # the legacy bake is untouched (inverted curve, sheet exponent ignored with a layer)
    old = np.asarray(Image.open(we._make_roughness(d, ss, 43.0)))
    assert old[0, 0] == int((1 - (2 / 3.0) ** 0.5) * 255) and old[0, 1] > old[0, 0]


# ---------------------------------------------------------------------------
# 4. buffer kinds, LOD metadata
# ---------------------------------------------------------------------------


def test_occluder_kind_and_roles():
    h, s = tf._lod_model()
    M = we.parse_model_header(h)
    assert M["parts"][0]["occluder"] is M["parts"][0]["proxy"] is not None
    assert we.BUFFER_KINDS == ("render", "shadow", "occluder")
    for kinds in (("occluder",), ("proxy",)):  # the old name still selects it
        subs = we.decode_model_mesh(h, s, kinds=kinds)["submeshes"]
        assert [(x["kind"], x["role"]) for x in subs] == [("occluder", "occluder")]
    subs = we.decode_model_mesh(h, s, kinds=("shadow",))["submeshes"]
    assert [(x["kind"], x["role"], x["format"]) for x in subs] == [("shadow", "shadow_hull", 9)]
    # the default never returns either
    assert {x["kind"] for x in we.decode_model_mesh(h, s)["submeshes"]} == {"render"}


def _lod_header(values):
    """tf._lod_model() with a real property bag: lodDistance / lodFadeIn / lodFadeOut."""
    h, s = tf._lod_model()
    bag = b""
    for name, v in values:
        bag += struct.pack("<IIII", 0xCD64AC11, we._name_hash(name), we._name_hash("number"), 1)
        bag += struct.pack("<f", v)
    start = h.index(b"\xcd" * 8)
    n = 4 * 91
    assert len(bag) <= n
    return h[:start] + bag + b"\0" * (n - len(bag)) + h[start + n :], s


def test_lod_distances_from_the_property_bag(tmp_path, monkeypatch):
    vals = [("lodDistance01", 30.0), ("lodFadeIn01", 2.0), ("lodFadeOut01", 5.0)]
    vals += [("lodDistance12", 60.0), ("lodFadeIn12", 2.0), ("lodFadeOut12", 2.0)]
    vals += [("lodDistance23", 90.0), ("lodFadeIn23", 0.0), ("lodFadeOut23", 2.0)]
    h, s = _lod_header(vals)
    info = we.model_lod_info(h)
    assert info["lods"][0] == {"lod": 0, "max_distance": 30.0, "fade_in": 2.0, "fade_out": 5.0}
    assert [x["max_distance"] for x in info["lods"]] == [30.0, 60.0, 90.0]
    meta = we.model_meta(h)
    assert meta["format"] == "watchmen-model-meta/1" and meta["lod_count"] == 2
    assert [x["lod"] for x in meta["lods"]] == [0, 1]  # only the LODs the model has
    assert meta["not_exported"] == {"shadow_hull": 1, "occluder": 1}
    assert we.model_lod_info(tf._lod_model()[0]) is None  # no such properties
    # decode_model writes it next to the OBJ; --materials legacy writes no new file
    we.decode_model(h, s, tmp_path / "m.obj")
    side = json.loads((tmp_path / "m.model.json").read_text())
    assert side["lods"][1]["max_distance"] == 60.0
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    we.decode_model(h, s, tmp_path / "n.obj")
    assert (tmp_path / "n.obj").exists() and not (tmp_path / "n.model.json").exists()


# ---------------------------------------------------------------------------
# 5. level grade, CLI
# ---------------------------------------------------------------------------


def test_fragment_grades_reads_the_gfx_nodes():
    one = struct.unpack("<I", struct.pack("<f", 80.0))[0]
    frag = {
        "nodes_full": [
            {"type": "Model", "props": [["name", "string", "x"], ["gamma", "raw4?", 9.0]]},
            {
                "type": "FXGfxEffectCtrl(GFXEffect)",
                "props": [
                    ["name", "string", "RS GFX"],
                    ["enabled", "truth", True],
                    ["Fog", "raw4?", 1],
                    ["fogBegin", "raw4?", 0],
                    ["fogEnd", "raw4?", one],
                    ["fogColor", "vector?", [0.0266, 0.042513, 0.07]],
                    ["contrast", "raw4?", 0.22],
                    ["Saturation", "number", 0.0],
                    ["tintPower", "raw4?", 0.3],
                    ["tintColor", "vector?", [0.54, 0.693333, 1.0]],
                    ["gamma", "raw4?", 1.2],
                    ["geometryLodMode", "raw4?", 0],
                ],
            },
        ]
    }
    (g,) = mt.fragment_grades(frag)
    assert g["node"] == "RS GFX" and g["type"].endswith("(GFXEffect)") and g["enabled"] is True
    assert g["fog"] is True and g["fogbegin"] == 0.0 and g["fogend"] == 80.0
    assert g["gamma"] == 1.2 and g["tintcolor"] == [0.54, 0.693333, 1.0] and g["saturation"] == 0.0
    assert g["geometrylodmode"] == 0 and isinstance(g["geometrylodmode"], int)
    assert mt.fragment_grades({}) == [] and "gamma" in mt.GRADE_FORMULA


def test_cli_materials_option(tmp_path, monkeypatch, capsys):
    import os
    import watchmen

    monkeypatch.delenv("WATCHMEN_MATERIALS", raising=False)
    assert watchmen.main(["w", "binds", "a", "b", "--materials", "legacy"]) == 2
    assert "--materials applies to" in capsys.readouterr().out
    assert watchmen.main(["w", "characters", "a", "b", "--materials", "shiny"]) == 2
    assert "--materials takes one of: engine, legacy" in capsys.readouterr().out
    assert "WATCHMEN_MATERIALS" not in os.environ
    for cmd in watchmen.MATERIALS_COMMANDS:
        assert "--materials engine|legacy" in watchmen.USAGE[cmd][1]
    assert "grademeta" in watchmen.USAGE
