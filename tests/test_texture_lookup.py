"""Texture lookup by the model's own texture path.

A model header lists full texture asset paths and the engine loads exactly those
(ModelRes::Read 0x547006 -> 0x49b2b2 -> AssetManager 0x55243f).  Bare names are
not unique in the game data ('head' exists in three folders), so every lookup
goes by path; only a material without a usable path falls back to the bare name,
deterministically and with a warning.  Nothing may depend on the order the file
system lists directories in.  Each test fails on the 1.3.0 code.
"""

import io
import json
import os
import pickle
from pathlib import Path

import numpy as np
import pytest

import char_lib
import characters_export as ce
import rig_glb
import variant_glb as vg
import watchmen_extract as we
from conftest import parse_glb

Image = pytest.importorskip("PIL.Image")

BIKERS = "art/characters/bikers/textures/head.bmp"
COMMON = "art/characters/common/textures/head/head.bmp"
KNOT = "art/characters/knottops/textures/head.bmp"
COLOUR = {BIKERS: (200, 10, 10), COMMON: (10, 200, 10), KNOT: (10, 10, 200)}


def _texture(root, rel, rgb, normal=False):
    d = Path(root) / rel
    d.mkdir(parents=True)
    Image.fromarray(np.full((2, 2, 3), rgb, np.uint8)).save(d / "0_diffuse_2x2_DXT1.png")
    if normal:
        Image.fromarray(np.full((2, 2, 3), (128, 128, 255), np.uint8)).save(
            d / "1_normal_2x2_ATI2.png"
        )
    return d


def _tree(root, order):
    """The same texture tree, its directories created in the given order (on a
    creation-ordered file system that is the order os.walk lists them in)."""
    for rel in order:
        _texture(root, rel, COLOUR[rel])
    return Path(root)


ORDERS = [(BIKERS, COMMON, KNOT), (KNOT, COMMON, BIKERS), (COMMON, KNOT, BIKERS)]


def _rgb(png_bytes):
    return tuple(int(x) for x in np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"))[0, 0])


@pytest.fixture(autouse=True)
def _fresh_caches():
    char_lib._TEXIDX.clear()
    char_lib._LAYERCACHE.clear()
    yield
    char_lib._TEXIDX.clear()
    char_lib._LAYERCACHE.clear()


def _reversed_walk(monkeypatch):
    """Make os.walk list every directory in reverse order."""
    real = os.walk

    def walk(top, *a, **k):
        for dp, dns, fns in real(top, *a, **k):
            dns.sort(reverse=True)
            yield dp, dns, list(reversed(sorted(fns)))

    monkeypatch.setattr(os, "walk", walk)


# ---------------------------------------------------------------------------
# 1. TexRef and the model's texture list
# ---------------------------------------------------------------------------


def test_texref_is_the_bare_name_and_keeps_the_path():
    a = we.texture_ref("/art/characters/bikers/textures/head.bmp")
    b = we.texture_ref("/art/characters/knottops/textures/head.bmp")
    assert a == "head" and str(a) == "head" and a.path.endswith("bikers/textures/head.bmp")
    assert a != b and hash(a) == hash(b) == hash("head")
    assert a == we.TexRef("head", "\\ART\\Characters\\Bikers\\textures\\HEAD.bmp")  # same asset
    d = {a: 1, b: 2}
    assert len(d) == 2 and d[a] == 1 and d[b] == 2
    assert "head" in d  # a plain name still finds a material of that name
    c = pickle.loads(pickle.dumps(b))
    assert c == b and c.path == b.path and isinstance(c, we.TexRef)
    assert json.dumps([a]) == '["head"]'


def test_extract_materials_carry_the_header_paths():
    hdr = (
        b"\x00\x01"
        + b"\x2b\x00\x00\x00/art/characters/bikers/textures/EnemyEye.bmp\x00"
        + b"\x30\x00\x00\x00/art/characters/common/textures/head/EnemyEye.bmp\x00"
    )
    mats = we.extract_materials(hdr)
    assert mats == ["EnemyEye", "EnemyEye"]  # still the names every caller compares
    assert [m.path for m in mats] == [
        "/art/characters/bikers/textures/EnemyEye.bmp",
        "/art/characters/common/textures/head/EnemyEye.bmp",
    ]
    assert mats[0] != mats[1]
    assert we.unique_material_names(mats) == ["EnemyEye", "EnemyEye__2"]
    assert we.unique_material_names(mats + mats[:1]) == ["EnemyEye", "EnemyEye__2", "EnemyEye"]
    assert we.unique_material_names(["a", "b", "a"]) == ["a", "b", "a"]


# ---------------------------------------------------------------------------
# 2. TextureIndex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("order", ORDERS)
def test_index_resolves_by_path_whatever_the_creation_order(tmp_path, order):
    root = _tree(tmp_path / "textures", order)
    idx = we.build_texture_index(root)
    for rel in order:
        got = idx.resolve(we.texture_ref("/" + rel), warn=pytest.fail)
        assert got == root / rel
    # case and separators of the stored path do not matter
    assert idx.resolve(we.TexRef("head", "\\ART\\CHARACTERS\\KNOTTOPS\\Textures\\Head.BMP")) == (
        root / KNOT
    )
    assert idx.resolve("/art/characters/common/textures/head/head.bmp") == root / COMMON


@pytest.mark.parametrize("order", ORDERS)
def test_bare_name_fallback_is_sorted_and_warns_with_the_candidates(tmp_path, order):
    root = _tree(tmp_path / "textures", order)
    idx = we.build_texture_index(root)
    said = []
    assert idx.resolve("head", warn=said.append) == root / BIKERS  # asset paths sorted, first
    assert idx["head"] == root / BIKERS and idx.get("head") == root / BIKERS  # the dict view
    assert len(said) == 1 and "ambiguous" in said[0]
    for rel in order:
        assert rel in said[0]
    idx.resolve("head", warn=said.append)
    assert len(said) == 1  # once per name
    assert sorted(idx.ambiguous()) == ["head"]
    assert [d.relative_to(root).as_posix() for d in idx.candidates["head"]] == [
        BIKERS,
        COMMON,
        KNOT,
    ]


def test_a_path_that_is_not_in_the_tree_falls_back_to_the_name(tmp_path):
    root = tmp_path / "textures"
    only = _texture(root, "Textures/grids/gray.BMP", (9, 9, 9))
    _tree(root, ORDERS[1])
    idx = we.build_texture_index(root)
    said = []
    # one texture of that name: taken silently, wherever the model says it lives
    assert idx.resolve(we.texture_ref("/textures/gray.bmp"), warn=said.append) == only
    assert said == []
    # several: the documented tie-break, and the warning names the missing path
    gone = we.texture_ref("/art/characters/prisoners/textures/head.bmp")
    assert idx.resolve(gone, warn=said.append) == root / BIKERS
    assert "prisoners/textures/head.bmp is not in the texture tree" in said[0]
    assert idx.resolve(we.texture_ref("/x/nothing.bmp"), warn=said.append) is None


def test_index_does_not_depend_on_the_walk_order(tmp_path, monkeypatch):
    root = _tree(tmp_path / "textures", ORDERS[0])
    a = we.build_texture_index(root)
    _reversed_walk(monkeypatch)
    b = we.build_texture_index(root)
    assert dict(a) == dict(b) and a.by_path == b.by_path and a.candidates == b.candidates
    assert b["head"] == root / BIKERS


def test_plain_dict_indexes_still_work():
    assert we.resolve_texture({"a": "X"}, we.TexRef("A", "/p/A.bmp")) == "X"
    assert we.resolve_texture({}, "a") is None and we.resolve_texture(None, "a") is None


# ---------------------------------------------------------------------------
# 3. characters: char_lib
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("order", ORDERS)
def test_character_layers_come_from_the_models_own_folder(tmp_path, order, capsys):
    root = str(_tree(tmp_path / "textures", order))
    for rel in order:
        lay = char_lib._find_layers(we.texture_ref("/" + rel), [root])
        assert _rgb(lay["diffuse"]) == COLOUR[rel]
    assert capsys.readouterr().err == ""  # nothing ambiguous was looked up
    # a material without a path: deterministic, and it says so
    assert _rgb(char_lib._find_layers("head", [root])["diffuse"]) == COLOUR[BIKERS]
    assert "ambiguous" in capsys.readouterr().err


def test_character_lookup_ignores_the_walk_order(tmp_path, monkeypatch):
    root = str(_tree(tmp_path / "textures", ORDERS[0]))
    first = char_lib._texdir("head", root)
    char_lib._TEXIDX.clear()
    _reversed_walk(monkeypatch)
    assert char_lib._texdir("head", root) == first == str(Path(root) / BIKERS)


def test_two_models_with_the_same_material_name_keep_their_own_textures(tmp_path):
    root = str(_tree(tmp_path / "textures", ORDERS[2]))
    z = np.zeros
    part = lambda ref: (
        z((3, 3)),
        z((3, 4), np.uint16),
        z((3, 4), np.float32),
        z((1, 3)),
        None,
        ref,
    )
    a, b = we.texture_ref("/" + KNOT), we.texture_ref("/" + BIKERS)
    tex = char_lib.find_textures([part(a), part(b), part(a)], [root])
    assert len(tex) == 2
    assert _rgb(tex[a]["diffuse"]) == COLOUR[KNOT] and _rgb(tex[b]["diffuse"]) == COLOUR[BIKERS]


def test_upper_case_and_padded_texture_folders_are_found(tmp_path):
    root = tmp_path / "textures"
    _texture(root, "art/characters/rorschach/textures/RorschachFaceClean.BMP", (1, 2, 3))
    _texture(root, "art/characters/rorschach/textures/rorschachspots01 .bmp", (4, 5, 6))
    face = we.texture_ref("/art/characters/rorschach/textures/RorschachFaceClean.BMP")
    spots = we.texture_ref("/art/characters/rorschach/textures/rorschachspots01 .bmp")
    assert spots == "rorschachspots01 "  # the name the game uses, trailing blank included
    assert _rgb(char_lib._find_layers(face, [str(root)])["diffuse"]) == (1, 2, 3)
    assert _rgb(char_lib._find_layers(spots, [str(root)])["diffuse"]) == (4, 5, 6)
    assert _rgb(char_lib._find_layers("RorschachFaceClean", [str(root)])["diffuse"]) == (1, 2, 3)
    assert _rgb(char_lib._find_layers("rorschachspots01", [str(root)])["diffuse"]) == (4, 5, 6)


def test_character_glb_embeds_one_image_per_path(rig, tmp_path):
    root = str(_tree(tmp_path / "textures", ORDERS[1]))
    a, b = we.texture_ref("/" + KNOT), we.texture_ref("/" + COMMON)
    base = rig.parts[0]
    parts = [tuple(base[:5]) + (a,), tuple(base[:5]) + (b,), tuple(base[:5]) + (a,)]
    tex = char_lib.find_textures(parts, [root])
    vg.write_glb(parts, rig.manifest, tmp_path / "c.glb", str(rig.bind_npz), textures=tex)
    g = parse_glb(tmp_path / "c.glb")
    prims = g.j["meshes"][0]["primitives"]
    assert [p["material"] for p in prims] == [0, 1, 0]
    assert [m["name"] for m in g.j["materials"]] == ["head", "head"]

    def colour(mi):
        t = g.j["materials"][mi]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        bv = g.j["bufferViews"][g.j["images"][g.j["textures"][t]["source"]]["bufferView"]]
        o = bv.get("byteOffset", 0)
        return _rgb(bytes(g.bin_chunk[o : o + bv["byteLength"]]))

    assert colour(0) == COLOUR[KNOT] and colour(1) == COLOUR[COMMON]


# ---------------------------------------------------------------------------
# 4. extract: OBJ/MTL and the model .glb
# ---------------------------------------------------------------------------


def _write_two(tmp_path, mats, idx):
    v = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)] * 2
    subs = [(0, 3, 0, 1, 44), (3, 3, 1, 1, 44)]
    out = tmp_path / "models" / "m.obj"
    we._write_obj_mtl(out, "m", v, None, None, [(0, 1, 2), (3, 4, 5)], subs, mats, idx, None)
    return out.read_text(), out.with_suffix(".mtl").read_text()


@pytest.mark.parametrize("order", ORDERS)
def test_mtl_links_each_submesh_to_its_own_texture(tmp_path, order):
    root = _tree(tmp_path / "textures", order)
    idx = we.build_texture_index(root)
    mats = [we.texture_ref("/" + KNOT), we.texture_ref("/" + COMMON)]
    obj, mtl = _write_two(tmp_path, mats, idx)
    assert "usemtl head\n" in obj and "usemtl head__2\n" in obj
    blocks = dict(b.split("\n", 1) for b in mtl.split("newmtl ")[1:])
    assert sorted(blocks) == ["head", "head__2"]
    assert "knottops/textures/head.bmp/0_diffuse" in blocks["head"]
    assert "common/textures/head/head.bmp/0_diffuse" in blocks["head__2"]


def test_mtl_is_unchanged_for_unique_names(tmp_path):
    root = tmp_path / "textures"
    _texture(root, "art/a/skin.bmp", (1, 1, 1))
    _texture(root, "art/a/cloth.bmp", (2, 2, 2))
    refs = [we.texture_ref("/art/a/skin.bmp"), we.texture_ref("/art/a/cloth.bmp")]
    with_paths = _write_two(tmp_path / "p", refs, we.build_texture_index(root))
    plain = _write_two(tmp_path / "q", ["skin", "cloth"], we.build_texture_index(root))
    assert with_paths == plain and "__2" not in with_paths[1]


def test_model_glb_materials_follow_the_path(tmp_path):
    root = tmp_path / "textures"
    for rel in (KNOT, BIKERS, COMMON):
        _texture(root, rel, COLOUR[rel])
    idx = we.build_texture_index(root)
    V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)] * 2
    U = [(0, 0), (1, 0), (1, 1), (0, 1)] * 2
    T = [(0, 2, 1), (0, 3, 2), (4, 6, 5), (4, 7, 6)]
    subs = [(0, 4, 0, 2, 44), (4, 4, 2, 2, 44)]
    mats = [we.texture_ref("/" + KNOT), we.texture_ref("/" + COMMON)]
    out = tmp_path / "m.glb"
    pal = {"bone_count": 1, "bones": [{"name": "root"}]}
    said = []
    rig_glb.build_rigged_glb(
        out, np.asarray(V, float), None, U, None, None, T, subs, mats, idx, pal, None, said.append,
        static=True,
    )  # fmt: skip
    g = parse_glb(out)
    prims = g.j["meshes"][0]["primitives"]
    assert prims[0]["material"] != prims[1]["material"]
    got = []
    for p in prims:
        t = g.j["materials"][p["material"]]["pbrMetallicRoughness"]["baseColorTexture"]["index"]
        bv = g.j["bufferViews"][g.j["images"][g.j["textures"][t]["source"]]["bufferView"]]
        o = bv.get("byteOffset", 0)
        got.append(_rgb(bytes(g.bin_chunk[o : o + bv["byteLength"]])))
    assert got == [COLOUR[KNOT], COLOUR[COMMON]]
    assert not [s for s in said if "ambiguous" in str(s)]


# ---------------------------------------------------------------------------
# 5. characters_export: models are resolved by the fragment's path too
# ---------------------------------------------------------------------------


def test_model_reference_goes_by_path_and_the_name_index_is_sorted(tmp_path, monkeypatch):
    ex = tmp_path / "out"
    for rel in ("art/props/b/models/AirVent_01", "art/props/b/AirVent_01", "art/zz/Other"):
        p = ex / "extracted" / (rel + ".model")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")
    first = str(ex / "extracted" / "art" / "props" / "b" / "AirVent_01")
    deep = str(ex / "extracted" / "art" / "props" / "b" / "models" / "AirVent_01")
    midx = ce._model_index(str(ex))
    assert midx["AirVent_01"] == first
    real = ce.glob.glob
    monkeypatch.setattr(ce.glob, "glob", lambda *a, **k: list(reversed(sorted(real(*a, **k)))))
    assert ce._model_index(str(ex)) == midx  # not the listing order
    ref = "/art/props/b/models/AirVent_01.model"
    assert ce._model_ref_base(str(ex), ref, midx) == deep  # the referenced file itself
    assert ce._model_ref_base(str(ex), "/art/moved/Other.model", midx) == midx["Other"]
    assert ce._model_ref_base(str(ex), "/art/none/Missing.model", midx) is None
