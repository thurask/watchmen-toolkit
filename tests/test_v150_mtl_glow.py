"""1.5.0: the MTL's constant roughness, the light-layer opacity, one first-sheet reader.

* A material without a specSize layer has one roughness for the whole surface;
  the MTL writes it as a plain ``Ns = 1000 (1 - r)^2``, the value Blender's OBJ
  importer turns back into roughness r (roughness = 1 - sqrt(Ns / 1000)), where
  1.4.0 linked a 4x4 ``roughnessEngine.png`` of that one value.  A specSize
  layer keeps its baked map, a material without a highlight keeps ``Ns 0``,
  ``--materials legacy`` keeps ``roughnessGen.png``.
* A glow (SRCALPHA / ONE) carries its sheet's opacity as ``emissiveFactor`` only
  when the sky pass draws it (SkyBoxPS multiplies the opacity into the alpha,
  read from code); in the standard pass that was inferred, and the factor is 1.
* ``watchmen_extract.first_sheet`` is the one reader of a texture's first
  sheet for the MTL writer, ``_mtl_no_highlight`` and ``rig_glb``.
* ``characters_export.GLB_REVISION`` is 3, so a resumed export writes a
  character GLB of the earlier revision again.

Synthetic fixtures only."""

import inspect
import json
import math

import numpy as np
import pytest

import characters_export as ce
import materials as mt
import rig_glb
import watchmen_extract as we
import test_materials_no_highlight as tnh
import test_texture_sheets as ts
from conftest import parse_glb

Image = pytest.importorskip("PIL.Image")

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _blender_roughness(ns):
    """Blender's OBJ importer: roughness = 1 - sqrt(Ns / 1000) (io_import_obj)."""
    return 1.0 - math.sqrt(ns / 1000.0)


# ------------------------------------------------------------ MTL roughness
@pytest.mark.parametrize("r", [0.045, 0.2869, 0.343, 0.5, 0.9, 1.0])
def test_ns_reads_back_as_the_roughness(r):
    assert _blender_roughness(we._mtl_ns_of_roughness(r)) == pytest.approx(r, abs=1e-12)


def test_ns_ends_and_clamps():
    assert we._mtl_ns_of_roughness(1.0) == 0.0  # roughness 1 = Ns 0, the no-highlight value
    assert we._mtl_ns_of_roughness(0.0) == 1000.0
    assert we._mtl_ns_of_roughness(-0.5) == 1000.0 and we._mtl_ns_of_roughness(2.0) == 0.0


def test_constant_roughness_is_the_engine_lobe():
    """(2 / (n + 2))^0.25 of the sheet's exponent; no exponent = 15."""
    assert we._mtl_const_roughness(43.0) == pytest.approx((2.0 / 45.0) ** 0.25)
    assert we._mtl_const_roughness(None) == pytest.approx(float(mt.roughness(15.0)))


def _plain_tree(root, power=0.4, spec_txt="43.0 0.4"):
    """A texture with a highlight and no specSize layer."""
    path = "/art/m/props/Bottle_02.bmp"
    hdr = ts._header(
        ts._sheet(0x5151, "default", ts.WHITE, renderType=0, specularSize=43.0, specularPower=power)
    )
    d = ts._texture(root, path, (120, 90, 60), header=hdr)
    if spec_txt is not None:
        (d / "spec.txt").write_text(spec_txt)
    return path, d


def _rough_lines(lines):
    return [x for x in lines if x.startswith(("Ns ", "map_Ns"))]


def test_mtl_without_spec_size_writes_a_plain_ns(tmp_path):
    path, d = _plain_tree(tmp_path)
    lines = tnh._mtl(tmp_path, path)
    r = float(mt.roughness(43.0))
    assert _rough_lines(lines) == ["Ns %.6f" % (1000.0 * (1.0 - r) ** 2)]
    assert not (d / "roughnessEngine.png").exists()
    (ns,) = [float(x.split()[1]) for x in lines if x.startswith("Ns ")]
    assert _blender_roughness(ns) == pytest.approx(r, abs=1e-6)
    # Ks and the specular map are written as before
    assert "Ks 0.4000 0.4000 0.4000" in lines


def test_mtl_without_spec_txt_takes_the_default_exponent(tmp_path):
    path, d = _plain_tree(tmp_path, spec_txt=None)
    lines = tnh._mtl(tmp_path, path)
    r = float(mt.roughness(15.0))
    assert _rough_lines(lines) == ["Ns %.6f" % (1000.0 * (1.0 - r) ** 2)]
    assert not (d / "roughnessEngine.png").exists()


def test_mtl_with_spec_size_keeps_the_map_and_no_highlight_keeps_ns_0(tmp_path):
    (tmp_path / "lit").mkdir()
    (tmp_path / "zero").mkdir()
    p1, d1 = tnh._spec_size_tree(tmp_path / "lit", 0.4)
    lit = _rough_lines(tnh._mtl(tmp_path / "lit", p1))
    assert len(lit) == 1 and lit[0].startswith("map_Ns ") and lit[0].endswith("roughnessEngine.png")
    assert (d1 / "roughnessEngine.png").exists()
    p0, _d0 = tnh._spec_size_tree(tmp_path / "zero", 0.0)
    assert _rough_lines(tnh._mtl(tmp_path / "zero", p0)) == ["Ns 0.000000"]
    (tmp_path / "plain0").mkdir()
    p2, d2 = _plain_tree(tmp_path / "plain0", power=0.0, spec_txt="43.0 0.0")
    assert _rough_lines(tnh._mtl(tmp_path / "plain0", p2)) == ["Ns 0.000000"]
    assert not (d2 / "roughnessEngine.png").exists()


def test_legacy_mtl_keeps_the_old_bake(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    path, d = _plain_tree(tmp_path)
    rough = _rough_lines(tnh._mtl(tmp_path, path))
    assert len(rough) == 1 and rough[0].endswith("roughnessGen.png")
    assert (d / "roughnessGen.png").exists() and not (d / "roughnessEngine.png").exists()


# ------------------------------------------------------- light-layer opacity
SKY_MANUAL = {"renderType": 7, "blendType": 3, "srcBlend": 5, "dstBlend": 2, "blendOp": 1}
STD_MANUAL = {"renderType": 1, "blendType": 3, "srcBlend": 5, "dstBlend": 2, "blendOp": 1}


@pytest.mark.parametrize(
    "sheet, opacity, factor, pass_",
    [
        (SKY_MANUAL, 0.6, 0.6, "sky"),  # Sky_SunRay_01: SRCALPHA / ONE in the sky pass
        ({"renderType": 7, "blendType": 1}, 0.6, 1.0, "sky"),  # ONE / ONE
        ({"renderType": 1, "blendType": 1}, 0.25, 1.0, "standard"),  # add, SRCALPHA / ONE
        (STD_MANUAL, 0.63, 1.0, "standard"),  # manual SRCALPHA / ONE
        ({"renderType": 9, "blendType": 1}, 0.08, 1.0, "standard"),  # sprite
        ({"renderType": 0, "blendType": 1}, 0.5, 1.0, "standard"),  # blended for its opacity
        ({"renderType": 10, "blendType": 1}, 0.5, 1.0, "standard"),
    ],
)
def test_only_the_sky_pass_scales_a_glow(sheet, opacity, factor, pass_):
    blend = we.sheet_blend(dict(sheet, opacity=opacity))
    assert blend["gltf"] == "glow" and blend["pass"] == pass_
    mat = we.blend_material({"name": "m"}, blend, 0, opacity)
    assert mat["emissiveFactor"] == [factor] * 3
    assert mat["extras"]["watchmen"].get("opacity") == (factor if factor < 1.0 else None)


def test_every_blend_names_its_pass():
    for rt in (0, 1, 7, 9, 10):
        for bt in (0, 1, 2, 3):
            b = we.sheet_blend({"renderType": rt, "blendType": bt, "opacity": 0.5})
            assert b is not None and b["pass"] == ("sky" if rt == 7 else "standard")


def _model_glb(tmp_path, asset, sheet):
    d = tmp_path / "textures" / asset.strip("/")
    d.mkdir(parents=True)
    Image.new("RGBA", (4, 4), (255, 200, 100, 255)).save(d / "0_diffuse_4x4_DXT5.png")
    (d / "sheet.json").write_text(json.dumps(dict(sheet, sheets=[dict(sheet, name="default")])))
    V = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], float)
    out = tmp_path / "m.glb"
    rig_glb.build_rigged_glb(
        out,
        V,
        None,
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        None,
        None,
        [(0, 1, 2), (0, 2, 3)],
        [(0, 4, 0, 2, 44)],
        [we.texture_ref(asset)],
        we.TextureIndex(tmp_path / "textures"),
        {"bone_count": 0, "bones": []},
        None,
        None,
        static=True,
        normals=np.tile(np.array([[0.0, 0.0, 1.0]], np.float32), (4, 1)),
        colors=None,
        tangents=None,
        has_color=[False],
        has_alpha=[False],
        engine_materials=True,
    )
    (mat,) = parse_glb(out).j["materials"]
    return mat


@pytest.mark.parametrize(
    "asset, sheet",
    [
        # 1.4.0 wrote these factors for Disco_Ball_01 (0.08), the burning cars (0.63)
        ("/art/props/Disco_Ball_01.bmp", {"renderType": 1, "blendType": 1, "opacity": 0.08}),
        ("/art/cars/Fire.bmp", dict(STD_MANUAL, opacity=0.63)),
    ],
)
def test_extract_glb_standard_pass_glow_keeps_factor_one(tmp_path, asset, sheet):
    mat = _model_glb(tmp_path, asset, sheet)
    assert mat["extras"]["watchmen"]["blend"] in ("add", "manual")
    assert mat["emissiveFactor"] == [1.0, 1.0, 1.0] and mat["alphaMode"] == "BLEND"
    assert "opacity" not in mat["extras"]["watchmen"]


def test_extract_glb_sky_glow_keeps_its_opacity(tmp_path):
    mat = _model_glb(tmp_path, "/art/sky/Sky_SunRay_01.bmp", dict(SKY_MANUAL, opacity=0.6))
    assert mat["emissiveFactor"] == [0.6, 0.6, 0.6] and mat["extras"]["watchmen"]["opacity"] == 0.6


# ----------------------------------------------------- one first-sheet reader
def test_first_sheet_overlays_the_top_level_keys(tmp_path):
    assert we.first_sheet(tmp_path) == {}  # no sheet.json
    (tmp_path / "sheet.json").write_text("[1, 2]")
    assert we.first_sheet(tmp_path) == {}  # not an object
    (tmp_path / "sheet.json").write_text("{broken")
    assert we.first_sheet(tmp_path) == {}
    doc = {
        "renderType": 1,
        "opacity": 0.5,
        "sheets": [{"renderType": 9, "srcBlend": 5, "name": "a"}, {"name": "b"}],
    }
    (tmp_path / "sheet.json").write_text(json.dumps(doc))
    assert we.first_sheet(str(tmp_path)) == {
        "renderType": 1,
        "opacity": 0.5,
        "srcBlend": 5,
        "name": "a",
    }
    (tmp_path / "sheet.json").write_text(json.dumps({"renderType": 1, "sheets": []}))
    assert we.first_sheet(tmp_path) == {"renderType": 1, "sheets": []}  # nothing to overlay


def test_the_writers_read_the_first_sheet_through_one_function(tmp_path, monkeypatch):
    calls = []
    real = we.first_sheet

    def spy(texdir):
        calls.append(inspect.stack()[1].function)
        return real(texdir)

    monkeypatch.setattr(we, "first_sheet", spy)
    path, _d = _plain_tree(tmp_path / "mtl")
    tnh._mtl(tmp_path / "mtl", path)
    assert {"_write_obj_mtl", "_mtl_no_highlight"} <= set(calls)
    calls.clear()
    _model_glb(tmp_path / "glb", "/art/props/Lamp.bmp", {"renderType": 1, "blendType": 1})
    assert "_sheet" in calls
    # no other copy of the overlay is left in the two modules
    src = inspect.getsource(we) + inspect.getsource(rig_glb)
    assert src.count("full[0] | {") == 1
    assert "sheet.json" not in inspect.getsource(rig_glb.build_rigged_glb).split('"""', 2)[2]


# --------------------------------------------------------- writer revision
def test_a_glb_of_the_earlier_revision_is_written_again(tmp_path):
    assert ce.GLB_REVISION == 3 and ce.writer_options()["glb_revision"] == 3
    out = tmp_path / "Dominatrix_1.stub"  # not a GLB (glb_frame: None): the record decides
    out.write_bytes(b"stub")
    old = ce.writer_options() | {"glb_revision": 2}
    ce.record_glb_options(str(out), str(tmp_path), old)
    assert not ce.glb_is_current(str(out), options=ce.writer_options(), root=str(tmp_path))
    ce.record_glb_options(str(out), str(tmp_path), ce.writer_options())
    assert ce.glb_is_current(str(out), options=ce.writer_options(), root=str(tmp_path))


# ------------------------------------------------------------------- docs
def test_naz_format_doc_names_the_font_and_colouring_decoders():
    text = (ROOT / "docs" / "KAPOW_NAZ_FORMAT.md").read_text(encoding="utf-8")
    assert "Neither type has a decoder" not in text
    for name in ("wlib/font_asset.py", "wlib/terrain_asset.py", ".terrainColoringAsset.json"):
        assert name in text, name
