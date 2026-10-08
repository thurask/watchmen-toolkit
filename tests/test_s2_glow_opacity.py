"""A light layer carries its sheet's opacity (watchmen_extract.blend_material).

A sheet drawn SRCALPHA / ONE (blend type add outside the sky pass, or a manual
blend) adds src.rgb * src.a, and the alpha the shader writes holds the opacity:
the emissiveFactor of the glTF material is that opacity.  ONE / ONE (blend type
add in the sky pass) does not read the alpha.

Synthetic fixtures only."""

import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import watchmen_extract as we

from conftest import parse_glb

#: Sky_SunRay_01: SkyBox sheet, manual blend SRCALPHA / ONE, opacity 0.6
SUNRAY = {"renderType": 7, "blendType": 3, "srcBlend": 5, "dstBlend": 2, "blendOp": 1}


def _mat():
    return {"name": "m", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}


def test_a_manual_srcalpha_one_glow_takes_the_opacity():
    blend = we.sheet_blend(dict(SUNRAY, opacity=0.6000000238418579))
    assert (blend["type"], blend["src"], blend["dst"], blend["gltf"]) == (
        "manual",
        "srcAlpha",
        "one",
        "glow",
    )
    mat = we.blend_material(_mat(), blend, 0, 0.6000000238418579)
    assert mat["emissiveFactor"] == [0.6, 0.6, 0.6] and mat["emissiveTexture"] == {"index": 0}
    assert mat["alphaMode"] == "BLEND"
    assert mat["pbrMetallicRoughness"]["baseColorFactor"] == [0.0, 0.0, 0.0, 1.0]
    w = mat["extras"]["watchmen"]
    assert w["opacity"] == 0.6 and (w["blend"], w["src"], w["dst"]) == ("manual", "srcAlpha", "one")


@pytest.mark.parametrize("opacity", [None, 1.0, 1.5])
def test_full_or_unknown_opacity_keeps_factor_one(opacity):
    mat = we.blend_material(_mat(), we.sheet_blend(dict(SUNRAY, opacity=1.0)), 0, opacity)
    assert mat["emissiveFactor"] == [1.0, 1.0, 1.0]
    assert "opacity" not in mat["extras"]["watchmen"]


def test_the_old_call_without_opacity_is_unchanged():
    blend = we.sheet_blend(dict(SUNRAY, opacity=0.6))
    assert we.blend_material(_mat(), blend, 0)["emissiveFactor"] == [1.0, 1.0, 1.0]


def test_add_outside_the_sky_pass_reads_the_alpha_too():
    """Blend type add on a "Standard with blending" sheet is SRCALPHA / ONE."""
    blend = we.sheet_blend({"renderType": 1, "blendType": 1, "opacity": 0.25})
    assert (blend["src"], blend["dst"], blend["gltf"]) == ("srcAlpha", "one", "glow")
    mat = we.blend_material(_mat(), blend, 0, 0.25)
    assert mat["emissiveFactor"] == [0.25, 0.25, 0.25]
    assert we.blend_material(_mat(), blend, 0, 0.0)["emissiveFactor"] == [0.0, 0.0, 0.0]


def test_add_in_the_sky_pass_does_not_read_the_alpha():
    """ONE / ONE: the opacity does not enter."""
    blend = we.sheet_blend({"renderType": 7, "blendType": 1, "opacity": 0.6})
    assert (blend["src"], blend["dst"], blend["gltf"]) == ("one", "one", "glow")
    mat = we.blend_material(_mat(), blend, 0, 0.6)
    assert mat["emissiveFactor"] == [1.0, 1.0, 1.0] and "opacity" not in mat["extras"]["watchmen"]


def test_ink_and_plain_blends_get_no_emission():
    ink = we.sheet_blend({"renderType": 1, "blendType": 2, "opacity": 0.5})
    assert ink["gltf"] == "ink"
    assert "emissiveFactor" not in we.blend_material(_mat(), ink, 0, 0.5)
    plain = we.sheet_blend({"renderType": 1, "blendType": 0, "opacity": 0.5})
    assert "emissiveFactor" not in we.blend_material(_mat(), plain, 0, 0.5)


def _texture_dir(root, asset, sheet):
    Image = pytest.importorskip("PIL.Image")
    d = root / "textures" / asset.strip("/")
    d.mkdir(parents=True)
    Image.new("RGBA", (4, 4), (255, 200, 100, 255)).save(d / "0_diffuse_4x4_DXT5.png")
    (d / "sheet.json").write_text(json.dumps(dict(sheet, sheets=[dict(sheet, name="default")])))
    return d


def test_extract_glb_writes_the_opacity_into_the_material(tmp_path):
    """rig_glb, the writer of `extract --glb`."""
    import numpy as np
    import rig_glb

    _texture_dir(tmp_path, "/art/sky/Sky_SunRay_01.bmp", dict(SUNRAY, opacity=0.6))
    idx = we.TextureIndex(tmp_path / "textures")
    V = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], float)
    out = tmp_path / "sky.glb"
    rig_glb.build_rigged_glb(
        out,
        V,
        None,
        [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        None,
        None,
        [(0, 1, 2), (0, 2, 3)],
        [(0, 4, 0, 2, 44)],
        [we.texture_ref("/art/sky/Sky_SunRay_01.bmp")],
        idx,
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
    assert mat["emissiveFactor"] == [0.6, 0.6, 0.6] and mat["alphaMode"] == "BLEND"
    assert mat["extras"]["watchmen"]["opacity"] == 0.6


def test_a_character_material_takes_it_from_its_sheet(tmp_path, rig):
    """variant_glb, the writer of the character GLBs."""
    import char_lib
    import variant_glb as vg

    _texture_dir(tmp_path, "/art/r/streak.bmp", {"renderType": 1, "blendType": 1, "opacity": 0.25})
    char_lib._LAYERCACHE.clear()
    nm = we.texture_ref("/art/r/streak.bmp")
    V, SI, SW, T, UV, _ = rig.parts[0]
    tex = char_lib.find_textures([(V, SI, SW, T, UV, nm)], [str(tmp_path / "textures")])
    out = tmp_path / "c.glb"
    vg.write_glb([(V, SI, SW, T, UV, nm)], rig.manifest, str(out), str(rig.bind_npz), textures=tex)
    (mat,) = parse_glb(out).j["materials"]
    assert mat["extras"]["watchmen"]["blend"] == "add"
    assert mat["emissiveFactor"] == [0.25, 0.25, 0.25]
