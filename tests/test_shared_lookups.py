"""One copy each of two helpers that several modules carried.

`wutil.find_ci` is the asset lookup without regard to letter case behind
`anim_state_machine._find_ci`, `particle_meta._lookup`, `FxDB.asset_path` and
`characters_export._asset_file`. `variant_glb.write_glb` makes a material in one place
for the body, attachment and face primitives.
"""

import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_state_machine as asm
import characters_export as ce
import fx_meta
import particle_meta as pm
import variant_glb as vg
import wutil
from conftest import parse_glb
from test_face_rule import face_rig


def _touch(root, rel):
    p = os.path.join(str(root), *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(rel)
    return p


def _case_sensitive(tmp_path):
    probe = tmp_path / "cs_probe"
    probe.write_text("")
    return not (tmp_path / "CS_PROBE").exists()


def test_find_ci_takes_the_written_name_else_the_first_sorted_twin(tmp_path):
    f = _touch(tmp_path, "Art/Textures/Head.bmp")
    assert wutil.find_ci(str(tmp_path), "/art/textures/HEAD.bmp") == f
    assert wutil.find_ci(str(tmp_path), "\\Art\\Textures\\Head.bmp") == f
    assert wutil.find_ci(str(tmp_path), "/art/./textures//../Head.bmp") == f
    assert wutil.find_ci(str(tmp_path), "/art/textures/Hat.bmp") is None
    assert wutil.find_ci(str(tmp_path), "") is None
    assert wutil.find_ci(str(tmp_path), None) is None
    assert wutil.find_ci(None, "/a.bmp") is None
    if not _case_sensitive(tmp_path):
        pytest.skip("case twins need a case-sensitive file system")
    g = _touch(tmp_path, "art/textures/head.bmp")
    # the name as written wins over a twin; otherwise the first sorted twin ("Art" < "art")
    assert wutil.find_ci(str(tmp_path), "art/textures/head.bmp") == g
    assert wutil.find_ci(str(tmp_path), "ART/TEXTURES/HEAD.BMP") == f


def test_find_ci_json_twin_and_cache(tmp_path):
    _touch(tmp_path, "TNT/Production/x.fragment.json")
    want = os.path.join(str(tmp_path), "TNT", "Production", "x.fragment")
    assert wutil.find_ci(str(tmp_path), "/tnt/production/x.fragment") is None
    assert wutil.find_ci(str(tmp_path), "/tnt/production/x.fragment", json_twin=True) == want
    cache = {}
    assert wutil.find_ci(str(tmp_path), "/tnt/production/x.fragment.json", cache) == want + ".json"
    assert cache[str(tmp_path)] == ["TNT"]
    os.remove(want + ".json")  # a cached listing is not read again
    assert wutil.find_ci(str(tmp_path), "/tnt/production/x.fragment.json", cache) == want + ".json"


def test_the_module_lookups_are_find_ci(tmp_path):
    _touch(tmp_path, "extracted/Art/Effects/Blood02.bmp")
    _touch(tmp_path, "extracted/TNT/a.fragment.json")
    ex = str(tmp_path / "extracted")

    class _F:
        class db:
            root = ex

    for asset in ("/art/effects/blood02.BMP", "/tnt/a.fragment", "/nothing/here.bmp"):
        assert asm._find_ci(ex, asset) == wutil.find_ci(ex, asset, json_twin=True)
        assert pm._lookup(ex, asset) == wutil.find_ci(ex, asset)
        assert fx_meta.FxDB.asset_path(_F(), asset) == wutil.find_ci(ex, asset)
    got = ce._asset_file(str(tmp_path), ["art", "EFFECTS", "blood02.bmp"])
    want = os.path.join(ex, "Art", "Effects", "Blood02.bmp")
    # on a case-insensitive file system the path as asked exists and is returned as is
    assert os.path.samefile(got, want)
    if _case_sensitive(tmp_path):
        assert got == want


class _Layers(dict):
    """Textures for every material name except those ending `_untextured`."""

    def __init__(self):
        super().__init__(_=None)  # truthy: write_glb reads `textures or {}`

    def get(self, k, d=None):
        if k.endswith("_untextured"):
            return None
        return {"diffuse": b"D" + k.encode(), "mr": b"M", "normal": b"N", "spec": b"S"}


def test_one_material_per_name_for_body_attachment_and_face(tmp_path, rig):
    V, SI, SW, T, UV, _ = rig.parts[0]
    parts = [(V, SI, SW, T, UV, n) for n in ("body0", "body1", "body0", "x_untextured")]
    att = [("Gun", [(V, SI, SW, T, UV, "gun1"), (V, SI, SW, T, UV, "body0")])]
    out = tmp_path / "m.glb"
    vg.write_glb(
        parts,
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        textures=_Layers(),
        face=face_rig(tmp_path, rig),
        attachments=att,
        face_rule="legacy",
    )
    j = parse_glb(out).j
    names = [m["name"] for m in j["materials"]]
    assert names[:4] == ["body0", "body1", "x_untextured", "gun1"] and len(names) == 5
    face_mat = names[4]
    # four images per textured material (diffuse, mr, normal, spec), none for the grey one
    assert len(j["images"]) == 4 * 4
    assert [i["name"] for i in j["images"][:4]] == [
        "body0_diffuse",
        "body0_mr",
        "body0_normal",
        "body0_spec",
    ]
    assert j["images"][-1]["name"] == face_mat + "_spec"
    grey = j["materials"][2]
    assert grey["pbrMetallicRoughness"]["baseColorFactor"] == [0.8, 0.8, 0.82, 1]
    body = j["materials"][0]
    assert body["pbrMetallicRoughness"]["roughnessFactor"] == 1.0 and "normalTexture" in body
    assert "KHR_materials_specular" in j["extensionsUsed"]
    by_mesh = {m["name"]: [p["material"] for p in m["primitives"]] for m in j["meshes"]}
    assert by_mesh["variant"] == [0, 1, 0, 2]
    assert [v for k, v in by_mesh.items() if k == "Gun"] == [[3, 0]]
