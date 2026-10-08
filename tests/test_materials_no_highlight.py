"""A material the game draws no highlight on is fully rough (1.4.0).

The engine-material conversion (wlib/materials.py) writes the highlight's width
as roughness and its strength through KHR_materials_specular.  Where the game
draws NO highlight (specularPower <= 0 without a cube reflection, or a
reflectance of nothing) the strength is specularFactor 0 -- but a viewer that
ignores the extension (F3D for one) then showed the default dielectric
highlight at the sheet's narrow lobe: wet-looking hair, brows and eyes.  Such a
material now has roughnessFactor 1.0 and no metallicRoughnessTexture; in the
MTL of `extract` it gets `Ns 0` and no roughnessEngine.png.  Every other
material, however weak its highlight, and `--materials legacy` are unchanged.
"""

import io

import numpy as np
import pytest

import char_lib
import characters_export as ce
import materials as mt
import rig_glb
import variant_glb as vg
import watchmen_extract as we
import test_materials_v2 as tm
import test_texture_sheets as ts
from conftest import parse_glb

Image = pytest.importorskip("PIL.Image")

SUIT = dict(renderType=10, specularSize=43.0, specularPower=1.17, twoSided=True)
NONE = dict(SUIT, specularPower=0.0)
GREY = lambda: Image.new("RGB", (2, 2), (128,) * 3)
SPEC_SIZE = lambda: Image.fromarray(np.array([[0, 255], [128, 64]], np.uint8), "L")


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv("WATCHMEN_MATERIALS", raising=False)
    monkeypatch.delenv("WATCHMEN_MATERIAL_OPTS", raising=False)
    for c in (char_lib._TEXIDX, char_lib._LAYERCACHE, ce._FRAG_NODES, ce._TEX_SHEETS):
        c.clear()
    yield
    for c in (char_lib._TEXIDX, char_lib._LAYERCACHE, ce._FRAG_NODES, ce._TEX_SHEETS):
        c.clear()


# ---------------------------------------------------------------- the function
def test_no_highlight_without_a_spec_size_layer_is_fully_rough():
    P = mt.engine_material(NONE, GREY())
    assert P["specular"] == {"specularFactor": 0.0} == mt.NO_HIGHLIGHT
    assert P["roughnessFactor"] == 1.0 and P["mr"] is None
    assert P["spec"] is None and P["ior"] is None
    # the sheet's own lobe (what was written before) is far from matte
    assert float(mt.roughness(43.0)) < 0.5


def test_no_highlight_with_a_spec_size_layer_writes_no_roughness_texture():
    P = mt.engine_material(NONE, GREY(), None, SPEC_SIZE())
    assert P["specular"] == {"specularFactor": 0.0}
    assert P["roughnessFactor"] == 1.0 and P["mr"] is None
    # the same layers with a highlight still give the per-texel roughness
    assert mt.engine_material(SUIT, GREY(), None, SPEC_SIZE())["mr"] is not None


def test_a_black_specular_layer_is_no_highlight_too():
    black = Image.new("RGB", (2, 2), (0, 0, 0))
    P = mt.engine_material(SUIT, GREY(), black, SPEC_SIZE())
    assert P["specular"] == {"specularFactor": 0.0}  # the reflectance is nothing
    assert P["roughnessFactor"] == 1.0 and P["mr"] is None


def test_a_cube_reflection_keeps_the_roughness_of_the_sheet():
    refl = dict(NONE, reflectionType=2, reflectionLightFactor=0.1)
    P = mt.engine_material(refl, GREY(), None, None, opts={"display": 0})
    assert P["specular"] == {"specularFactor": 1.0} and P["ior"] is not None
    assert P["roughnessFactor"] == pytest.approx((2 / 45.0) ** 0.25, abs=1e-4)
    P = mt.engine_material(refl, GREY(), None, SPEC_SIZE())
    assert P["mr"] is not None and P["roughnessFactor"] == 1.0


@pytest.mark.parametrize("power", [1e-4, 0.002, 0.05])
def test_a_weak_highlight_is_not_touched(power):
    """Only a strength of exactly zero is changed: any highlight the game does
    draw keeps its width.  The numbers are the formulas of the conversion (and
    equal the function before this rule; compared on the real data as well)."""
    weak = dict(SUIT, specularPower=power, specularSize=15.0)
    P = mt.engine_material(weak, None, opts={"display": 0})
    assert P["roughnessFactor"] == pytest.approx((2 / 17.0) ** 0.25, abs=1e-4)
    assert P["specular"]["specularFactor"] == pytest.approx(8 * power / 17 / 0.04, abs=1e-4)
    assert P["specular"]["specularFactor"] > 0 and P["mr"] is None
    P = mt.engine_material(weak, GREY(), None, SPEC_SIZE(), opts={"display": 0})
    assert P["specular"]["specularFactor"] > 0 and P["roughnessFactor"] == 1.0
    orm = np.asarray(Image.open(io.BytesIO(P["mr"])))
    want = np.round(
        mt.roughness(mt.exponent(15.0, np.array([[0, 1], [128 / 255, 64 / 255]]))) * 255
    )
    assert (orm[..., 1] == want).all() and (orm[..., 0] == 255).all() and (orm[..., 2] == 0).all()
    # default (display-space) options: pinned from the function before the rule
    P = mt.engine_material(weak, GREY(), None, SPEC_SIZE())
    assert np.asarray(Image.open(io.BytesIO(P["mr"])))[..., 1].tolist() == WEAK_MR_DISPLAY[power]
    assert P["specular"]["specularFactor"] == WEAK_SF_DISPLAY[power]


#: engine_material(dict(SUIT, specularPower=p, specularSize=15), grey, None, SPEC_SIZE)
#: of the tree before the rule: green channel of the roughness texture, specularFactor
WEAK_MR_DISPLAY = {
    1e-4: [[127, 32], [45, 63]],
    0.002: [[127, 32], [45, 63]],
    0.05: [[127, 32], [45, 63]],
}
WEAK_SF_DISPLAY = {1e-4: 0.0003, 0.002: 0.0061, 0.05: 0.1669}


def test_only_roughness_changes_for_a_material_without_a_highlight():
    """Emission, extras and the sheet values are what they were."""
    glow = dict(NONE, selfIlluminance=0.5)
    P = mt.engine_material(glow, Image.new("RGB", (2, 2), (51,) * 3), None, SPEC_SIZE())
    assert P["roughnessFactor"] == 1.0 and P["mr"] is None
    assert P["emissive"] is not None and P["emissiveFactor"] == [1.0, 1.0, 1.0]
    assert P["extras"]["specularSize"] == 43.0 and P["extras"]["specularPower"] == 0.0
    j, mat, added = {}, {"name": "m"}, []
    mt.apply(j, mat, P, lambda data, label: added.append(label) or len(added) - 1)
    assert mat["pbrMetallicRoughness"] == {"metallicFactor": 0, "roughnessFactor": 1.0}
    assert mat["extensions"]["KHR_materials_specular"] == {"specularFactor": 0.0}
    assert added == ["emissive"]  # no "mr" image is embedded
    assert mat["extras"]["watchmen"]["sheet_values"]["specularSize"] == 43.0


def test_sheet_rule_for_writers_that_do_not_build_the_material():
    assert mt.no_highlight(NONE) and mt.no_highlight({}) and mt.no_highlight(None)
    assert not mt.no_highlight(SUIT)
    assert not mt.no_highlight(dict(SUIT, specularPower=1e-4))
    assert not mt.no_highlight(dict(NONE, reflectionType=2, reflectionLightFactor=0.1))
    assert mt.no_highlight(dict(NONE, reflectionType=1, reflectionLightFactor=0.1))  # planar
    assert mt.no_highlight(SUIT, intensity=0.0) and not mt.no_highlight(NONE, intensity=0.5)
    assert mt.no_highlight(SUIT, spec_black=True)
    # it agrees with the material that is built
    for sheet in (NONE, SUIT, dict(NONE, reflectionType=2, reflectionLightFactor=0.1)):
        built = mt.engine_material(sheet, GREY())["specular"] == mt.NO_HIGHLIGHT
        assert built == mt.no_highlight(sheet)


# ---------------------------------------------------------------- the writers
def test_character_glb_material_without_a_highlight(tmp_path, rig):
    g, (hair, skin) = tm._char_glb(tmp_path, rig)
    assert skin["extensions"]["KHR_materials_specular"] == {"specularFactor": 0.0}
    assert skin["pbrMetallicRoughness"]["roughnessFactor"] == 1.0
    assert "metallicRoughnessTexture" not in skin["pbrMetallicRoughness"]
    # the hair has a (weak) highlight: its roughness is the sheet's
    assert hair["extensions"]["KHR_materials_specular"]["specularFactor"] > 0
    assert 0.5 < hair["pbrMetallicRoughness"]["roughnessFactor"] < 1.0
    assert not [im for im in g.j["images"] if im["name"].endswith("_mr")]


def _spec_size_tree(root, power):
    """One texture with a specSize layer and a sheet of the given specularPower."""
    path = "/art/c/dom/textures/Brow.bmp"
    hdr = ts._header(
        ts._sheet(
            0x6666, "default", ts.WHITE, renderType=10, specularSize=43.0, specularPower=power
        )
    )
    d = ts._texture(root, path, (90, 60, 40), header=hdr)
    SPEC_SIZE().resize((4, 4)).save(d / "3_specSize_4x4_L8.png")
    (d / "spec.txt").write_text("43.0 %r" % power)
    return path, d


def test_character_glb_drops_the_roughness_texture_of_a_spec_size_layer(tmp_path, rig):
    def write(sub, power):
        root = tmp_path / sub
        path, _d = _spec_size_tree(root, power)
        parts = [tuple(rig.parts[0][:5]) + (we.texture_ref(path),)]
        tex = char_lib.find_textures(parts, [str(root / "textures")])
        vg.write_glb(parts, rig.manifest, root / "c.glb", str(rig.bind_npz), textures=tex)
        for c in (char_lib._TEXIDX, char_lib._LAYERCACHE):
            c.clear()
        g = parse_glb(root / "c.glb")
        return g, g.j["materials"][g.j["meshes"][0]["primitives"][0]["material"]]

    g0, m0 = write("zero", 0.0)
    g1, m1 = write("lit", 0.4)
    assert "metallicRoughnessTexture" in m1["pbrMetallicRoughness"]
    assert [im["name"] for im in g1.j["images"] if im["name"].endswith("_mr")]
    assert m0["pbrMetallicRoughness"]["roughnessFactor"] == 1.0
    assert "metallicRoughnessTexture" not in m0["pbrMetallicRoughness"]
    assert not [im["name"] for im in g0.j["images"] if im["name"].endswith("_mr")]
    assert m0["extensions"]["KHR_materials_specular"] == {"specularFactor": 0.0}
    # geometry and animation do not depend on the material
    for a0, a1 in zip(g0.j["accessors"], g1.j["accessors"]):
        assert (a0["type"], a0["count"]) == (a1["type"], a1["count"])


def _static(root, path):
    idx = we.build_texture_index(root / "textures")
    V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
    rig_glb.build_rigged_glb(
        root / "s.glb",
        V,
        None,
        [(0, 0), (1, 0), (0, 1)],
        None,
        None,
        [(0, 1, 2)],
        [(0, 3, 0, 1, 44)],
        [we.texture_ref(path)],
        idx,
        {"bone_count": 0, "bones": []},
        None,
        None,
        static=True,
        normals=np.array([[0, 0, 1]] * 3, np.float32),
        engine_materials=True,
    )
    return parse_glb(root / "s.glb")


def test_extract_glb_material_without_a_highlight(tmp_path, monkeypatch):
    (tmp_path / "zero").mkdir()
    (tmp_path / "lit").mkdir()
    p0, _ = _spec_size_tree(tmp_path / "zero", 0.0)
    p1, _ = _spec_size_tree(tmp_path / "lit", 0.4)
    g0, g1 = _static(tmp_path / "zero", p0), _static(tmp_path / "lit", p1)
    m0, m1 = g0.j["materials"][0], g1.j["materials"][0]
    assert m0["pbrMetallicRoughness"]["roughnessFactor"] == 1.0
    assert "metallicRoughnessTexture" not in m0["pbrMetallicRoughness"]
    assert m0["extensions"]["KHR_materials_specular"] == {"specularFactor": 0.0}
    assert "metallicRoughnessTexture" in m1["pbrMetallicRoughness"]
    assert len(g0.j["images"]) == len(g1.j["images"]) - 2  # no mr, no specular strength map
    # legacy: neither is an engine material
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    m = _static(tmp_path / "zero", p0).j["materials"][0]
    assert m["pbrMetallicRoughness"]["roughnessFactor"] == 0.85 and "extensions" not in m


def test_legacy_character_materials_are_untouched(tmp_path, rig, monkeypatch):
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    _g, (hair, skin) = tm._char_glb(tmp_path, rig)
    assert skin["pbrMetallicRoughness"]["roughnessFactor"] == 0.85 and "extensions" not in skin
    assert "metallicRoughnessTexture" in hair["pbrMetallicRoughness"]


def _mtl(root, path, name="m"):
    idx = we.build_texture_index(root / "textures")
    out = root / "obj" / (name + ".obj")
    v = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    we._write_obj_mtl(
        out,
        name,
        v,
        [(0.0, 0.0, 1.0)] * 3,
        [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        [(0, 1, 2)],
        [(0, 3, 0, 1, 44)],
        [we.texture_ref(path)],
        idx,
        lambda *a: None,
    )
    return out.with_suffix(".mtl").read_text().splitlines()


def test_mtl_of_a_material_without_a_highlight_has_no_roughness_bake(tmp_path, monkeypatch):
    for sub in ("zero", "lit", "refl", "black"):
        (tmp_path / sub).mkdir()
    p0, d0 = _spec_size_tree(tmp_path / "zero", 0.0)
    lines = _mtl(tmp_path / "zero", p0)
    assert "Ns 0.000000" in lines and "Ks 0 0 0" in lines
    assert not [x for x in lines if x.startswith("map_Ns")]
    assert not (d0 / "roughnessEngine.png").exists()
    # a highlight: the bake and its line, as before
    p1, d1 = _spec_size_tree(tmp_path / "lit", 0.4)
    lines = _mtl(tmp_path / "lit", p1)
    assert [x for x in lines if x.startswith("map_Ns")][0].endswith("roughnessEngine.png")
    assert not [x for x in lines if x.startswith("Ns ")] and (d1 / "roughnessEngine.png").exists()
    # no specular power but a cube reflection: the game shows the environment, bake kept
    path = "/art/c/dom/textures/Chrome.bmp"
    hdr = ts._header(
        ts._sheet(
            0x7777,
            "default",
            ts.WHITE,
            renderType=10,
            specularSize=43.0,
            specularPower=0.0,
            reflectionType=2,
            reflectionLightFactor=0.1,
        )
    )
    d2 = ts._texture(tmp_path / "refl", path, (90, 90, 90), header=hdr)
    (d2 / "spec.txt").write_text("43.0 0.0")
    assert we.read_sheet_json(d2)["sheets"][0]["reflectionType"] == 2  # only in the full sheet
    lines = _mtl(tmp_path / "refl", path)
    assert [x for x in lines if x.startswith("map_Ns")] and "Ns 0.000000" not in lines
    # a specular layer that is black everywhere: no highlight either
    p3, d3 = _spec_size_tree(tmp_path / "black", 0.4)
    Image.new("RGB", (4, 4), (0, 0, 0)).save(d3 / "2_specMap_4x4_DXT1.png")
    lines = _mtl(tmp_path / "black", p3)
    assert "Ns 0.000000" in lines and not [x for x in lines if x.startswith("map_Ns")]
    # legacy mode: the old bake for every material, the rule is not applied
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    lines = _mtl(tmp_path / "zero", p0, "legacy")
    assert [x for x in lines if x.startswith("map_Ns")][0].endswith("roughnessGen.png")
    assert "Ns 0.000000" not in lines and not (d0 / "roughnessEngine.png").exists()
