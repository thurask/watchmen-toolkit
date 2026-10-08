"""Pass 2, small defects found by the six-set export audit.

    repeated names    a name stored in several blocks is written once (OutputNames):
                      identical copies are skipped, a second spelling that differs
                      only in letter case goes under the first, a copy with other
                      bytes gets `<stem>~<block>.<ext>` and a log line
    model summary     a model that gives no output is named with the reason; the
                      summary counts written models, not block entries
    materials         a scanned model whose header lists more textures than the scan
                      found buffers says that no material was assigned
    skeleton scan     non-finite probe positions are skipped explicitly and reported
                      in one line (no numpy RuntimeWarning)
    jiggle cache      the solver's cache key is versioned and the loop flag is part
                      of the file name
    navigation        a loose-folder source keeps the .hpd beside the folder that is
                      extracted: found, copied to files/, exported; a level finds its
                      path data through its .aipathdata asset when the names differ;
                      a level without path data says so
    level uids        stable_uid / stable_id do not depend on the load order
    usage             `gendata` lists respell

Synthetic fixtures only (those of the feature tests are reused)."""

import json
import os
import struct
import sys
import warnings

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import jiggle_d6
import level_meta as lm
import nav_data as nd
import skeleton_records as sr
import text_assets as ta
import watchmen_extract as wx

import test_feature_seams as fs
import test_formats_v2 as tf
import test_level_meta as tl
import test_nav_data as tn
import test_text_assets as tt

nav_level = fs.nav_level  # the fixture: a level `Demo` with a door template instanced twice
extract = tl.extract  # the fixture: a scene with two load blocks and a nested fragment


# ------------------------------------------------------------ repeated names
def test_output_names_first_copy_keeps_its_name_and_a_repeat_is_not_written_again():
    n = wx.OutputNames()
    assert n.place("/a/Wall.bmp", "/l/one.block", b"H", b"S") == ("/a/Wall.bmp", "new")
    assert n.place("/a/Wall.bmp", "/l/two.block", b"H", b"S") == ("/a/Wall.bmp", "repeat")
    assert n.repeats == 1 and n.case_twins == [] and n.variants == []


def test_output_names_a_case_twin_goes_under_the_first_spelling():
    """Rubble_Rooftop_02 / Rubble_RoofTop_02 (Part 2, five blocks, same bytes): one
    file, named and labelled with the first spelling."""
    n = wx.OutputNames()
    n.place("/art/Rubble_Rooftop_02.model", "/l/bordello.block", b"H", b"S")
    got = n.place("/art/Rubble_RoofTop_02.model", "/l/nightclub.block", b"H", b"S")
    assert got == ("/art/Rubble_Rooftop_02.model", "repeat")
    n.place("/art/Rubble_RoofTop_02.model", "/l/tutorial.block", b"H", b"S")
    assert n.case_twins == [("/art/Rubble_RoofTop_02.model", "/art/Rubble_Rooftop_02.model")]
    assert n.repeats == 2


def test_output_names_a_later_stream_completes_a_copy_that_had_none():
    """Part 1: the Prison block lists 22 names without the stream other blocks have."""
    n = wx.OutputNames()
    assert n.place("/a/Fire.bmp", "/l/Prison.block", b"H", None)[1] == "new"
    assert n.place("/a/fire.bmp", "/l/docks.block", b"H", b"S") == ("/a/Fire.bmp", "fill")
    assert n.place("/a/Fire.bmp", "/l/streets.block", b"H", b"S")[1] == "repeat"
    assert n.place("/a/Fire.bmp", "/l/Prison2.block", b"H", None)[1] == "repeat"
    assert n.variants == []


def test_output_names_different_bytes_get_their_own_documented_name():
    logged = []
    n = wx.OutputNames(logged.append)
    n.place("/a/Rock.model", "/l/bordello.block", b"H", b"S")
    assert n.place("/a/Rock.model", "/l/nightclub.block", b"H2", b"S") == (
        "/a/Rock~nightclub.model",
        "variant",
    )
    # a third content from a block of the same name must not land on the second
    assert n.place("/a/rock.model", "/x/nightclub.block", b"H", b"S3") == (
        "/a/rock~nightclub~2.model",
        "variant",
    )
    assert n.place("/a/Rock.model", "/l/tutorial.block", b"H2", b"S")[1] == "repeat"
    assert [v[1] for v in n.variants] == ["/a/Rock~nightclub.model", "/a/rock~nightclub~2.model"]
    assert len(logged) == 2 and "different content in /l/nightclub.block" in logged[0]
    assert "/l/bordello.block" in logged[0] and "/a/Rock~nightclub.model" in logged[0]
    assert wx.OutputNames.variant_name("Wall.bmp", "/l/a b.block") == "Wall~a_b.bmp"
    assert wx.OutputNames.variant_name("/d/X.model", "blk", 3) == "/d/X~blk~3.model"


def _cls(name, payload=b""):
    raw = name.encode("ascii") + b"\0"
    return struct.pack("<I", len(raw)) + raw + payload


def _two_block_tree(root):
    """derived_pc/levels/{a,b}.block: `b` repeats a texture and a model of `a` under
    another letter case, holds one model with other bytes, and one without a mesh."""
    tex, mdl = _cls("Texture", b"tex-hdr"), _cls("ModelRes", b"mdl-hdr")
    a = [
        ("/art/T/Wall.bmp", tf._TEX, tex, b"wall-stream-0123456789"),
        ("/art/M/Rubble_Rooftop_02.model", 1, mdl, b"rubble-stream"),
        ("/art/M/Rock.model", 1, mdl, b"rock-stream-a"),
        ("/art/M/Medium_Skeleton.model", 1, _cls("ModelRes", b"skel"), b""),
    ]
    b = [
        ("/art/T/wall.bmp", tf._TEX, tex, b"wall-stream-0123456789"),
        ("/art/M/Rubble_RoofTop_02.model", 1, mdl, b"rubble-stream"),
        ("/art/M/Rock.model", 1, mdl, b"rock-stream-b"),
        ("/art/M/Medium_Skeleton.model", 1, _cls("ModelRes", b"skel"), b""),
    ]
    d = root / "files" / "derived_pc" / "levels"
    d.mkdir(parents=True)
    for nm, rows in (("a", a), ("b", b)):
        h, s = tf._block(rows)
        (d / (nm + ".block_h_z")).write_bytes(h)
        (d / (nm + ".block_s_z")).write_bytes(s)
    return root / "files"


@pytest.fixture
def recorded(monkeypatch):
    """main() with the two writers replaced: they record their calls and write one
    file holding the name they were given (the real decode_model handles a model
    without a stream, so its message is the real one)."""
    calls = {"tex": [], "mdl": []}
    real = wx.decode_model

    def carve(stream, header, out_dir, log=None):
        calls["tex"].append(out_dir.name)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0.png").write_bytes(stream)
        return True

    def decode(header, stream, out_path, tex_index=None, log=None, order=None, lod=0):
        calls["mdl"].append(out_path.name)
        if not stream:
            return real(header, stream, out_path, tex_index, log, order=order, lod=lod)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(out_path.stem.encode() + b"|" + stream)
        return True

    monkeypatch.setattr(wx, "carve_texture", carve)
    monkeypatch.setattr(wx, "decode_model", decode)
    monkeypatch.setattr(wx, "HAVE_IMG", True)
    return calls


def test_extract_writes_a_repeated_name_once_and_keeps_both_contents(tmp_path, recorded, capsys):
    files = _two_block_tree(tmp_path)
    out = tmp_path / "out"
    assert wx.main([str(files), "-o", str(out), "--no-files", "--no-text", "--no-audio"]) == 0
    log = capsys.readouterr().out
    # the texture twin and the model twin are written once, under the first spelling
    assert recorded["tex"] == ["Wall.bmp"]
    assert sorted(recorded["mdl"]) == [
        "Medium_Skeleton.model.obj",
        "Rock.model.obj",
        "Rock~b.model.obj",
        "Rubble_Rooftop_02.model.obj",
    ]
    m = out / "models" / "art" / "M"
    assert sorted(p.name for p in m.iterdir()) == [
        "Rock.model.obj",
        "Rock~b.model.obj",
        "Rubble_Rooftop_02.model.obj",
    ]
    # the name inside the file is the file's name (1.3.0: the last block's spelling)
    assert (m / "Rubble_Rooftop_02.model.obj").read_bytes().startswith(b"Rubble_Rooftop_02.model|")
    # both contents of the name that differs survive; the first keeps the plain name
    assert (m / "Rock.model.obj").read_bytes().endswith(b"rock-stream-a")
    assert (m / "Rock~b.model.obj").read_bytes().endswith(b"rock-stream-b")
    assert "/art/M/Rock.model is stored with different content in " in log
    assert "written as /art/M/Rock~b.model" in log
    # the raw dump follows the same names
    ex = out / "extracted" / "art" / "M"
    assert (ex / "Rock~b.model.stream").read_bytes() == b"rock-stream-b"
    assert not (ex / "Rubble_RoofTop_02.model").exists() or os.path.normcase("A") == "a"
    # log: what was skipped and why, by name
    assert "\nMODELS: 4  (textures indexed: " in log
    assert ")  [6 entries: 2 identical copies in other blocks not decoded again]" in log
    assert "note: model Medium_Skeleton.model.obj: not decoded: empty stream" in log
    assert "  textures    : 1  (+ 1 identical copies in other blocks, not written again)" in log
    assert (
        "  models      : 3  of 4  (1 without output, reason logged above: Medium_Skeleton.model)"
        in log
    )
    assert "names       : 2 stored under a second spelling" in log
    assert "/art/M/Rubble_RoofTop_02.model (= /art/M/Rubble_Rooftop_02.model)" in log
    assert "names       : 1 stored with different content in different blocks" in log


def test_extract_summary_stays_plain_without_repeats(tmp_path, recorded, capsys):
    files = tt.loose_tree(tmp_path)  # one block, one texture, no model
    assert wx.main([str(files), "-o", str(tmp_path / "o"), "--no-files", "--no-text"]) == 0
    log = capsys.readouterr().out
    assert "\nMODELS: 0  (textures indexed: " in log and "[" not in log.split("MODELS:")[1][:60]
    assert "  models      : 0\n" in log and "names       :" not in log
    assert "identical copies" not in log


# ------------------------------------------------- model without output / material
def test_decode_model_says_why_nothing_was_written(tmp_path):
    lines = []
    out = tmp_path / "X.model.obj"
    assert wx.decode_model(_cls("ModelRes"), b"", out, {}, lines.append) is False
    assert lines == [
        "      note: model X.model.obj: not decoded: empty stream: the model has no mesh data"
    ]
    lines.clear()
    assert wx.decode_model(_cls("ModelRes"), b"\0" * 64, out, {}, lines.append, order=">") is False
    assert len(lines) == 1 and "not decoded: no vertex buffer found (0 descriptor(s)" in lines[0]
    assert not out.exists()


def test_scanned_model_with_more_textures_than_buffers_logs_the_missing_material(
    tmp_path, monkeypatch
):
    """Console Palm_Banana_01: the header lists three textures, the single-buffer scan
    finds one buffer and there are no submesh records to pair them."""
    hdr = _cls("ModelRes") + b"".join(
        struct.pack(">I", len(p) + 1) + p + b"\0"
        for p in (b"/art/t/bananatree.bmp", b"/art/t/banana_leaf_02.bmp", b"/art/t/leaf_03.bmp")
    )
    verts = [(float(i), 0.0, float(i % 3)) for i in range(9)]
    monkeypatch.setattr(wx, "_pick_vb", lambda s: (0, 32, True, 9, [0, 1, 2, 3, 4, 5]))
    monkeypatch.setattr(wx, "_decode_sub", lambda s, off, nv, stride, be: (verts, None, None))
    written = {}
    monkeypatch.setattr(wx, "_write_obj_mtl", lambda *a: written.update(mats=a[7]))
    monkeypatch.setitem(wx._RIG, "on", False)
    lines = []
    out = tmp_path / "Palm_Banana_01.model.obj"
    assert wx.decode_model(hdr, b"\1" * 400, out, {}, lines.append, order=">")
    assert written["mats"] == ["submesh_0"]
    note = [x for x in lines if "no material assigned" in x]
    assert len(note) == 1 and "Palm_Banana_01.model.obj" in note[0]
    assert "the header lists 3 textures (bananatree, banana_leaf_02, leaf_03)" in note[0]
    assert "the single-buffer scan gave 1 submesh(es)" in note[0]
    assert "+mtl" not in [x for x in lines if " submeshes" in x][0]


# --------------------------------------------------------------- skeleton scan
def _header_with_garbage():
    """Two node names; the first node's body holds a NaN / inf run between two real
    [pos][unit quat] entries, as mesh and string bytes do in shipped models."""

    def name(s):
        raw = s.encode() + b"\0"
        return struct.pack("<I", len(raw)) + raw

    ent = struct.pack("<7f", 0.5, 1.0, -0.25, 0.0, 0.0, 0.0, 1.0)
    bad = struct.pack("<7f", 0.0, 0.0, 0.0, float("nan"), float("inf"), 0.0, 1.0)
    body = struct.pack("<Ii", 0, 1) + ent + bad + ent
    return name("Bip01 Pelvis") + body + name("Bip01 Spine") + struct.pack("<Ii", 0, 2)


def test_skeleton_scan_skips_non_finite_windows_without_a_numpy_warning():
    sr.scan_note()  # start from a clean count
    h = _header_with_garbage()
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # 1.3.0: RuntimeWarning in matmul on Windows numpy
        recs = sr.parse(h, order="<")
    assert [r["name"] for r in recs] == ["Bip01 Pelvis", "Bip01 Spine"]
    ents = recs[0]["entries"]
    assert [j for j, _p, _q in ents] == [8, 64]  # the two real entries, around the bad run
    assert np.allclose(ents[0][1], [0.5, 1.0, -0.25]) and np.allclose(ents[1][2], [0, 0, 0, 1])
    note = sr.scan_note()
    assert note.startswith("skeleton scan: ") and "in 1 model header(s)" in note
    assert "first: node Bip01 Pelvis, header offset" in note and "not transforms" in note
    assert int(note.split()[2]) >= 1  # probe positions that read the NaN / inf floats
    assert sr.scan_note() is None  # reported once
    sr.parse(struct.pack("<I", 4) + b"Abc\0" + struct.pack("<Ii", 0, 0) + b"\0" * 40)
    assert sr.scan_note() is None  # nothing non-finite: nothing to say


def test_finite7():
    assert sr._finite7((0.0, 1.0, -2.5, 3.0e38, 0.0, 0.0, 1.0))
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert not sr._finite7((0.0, 0.0, 0.0, 0.0, bad, 0.0, 1.0))


# ---------------------------------------------------------------- jiggle cache
def test_jiggle_cache_key_carries_the_loop_flag_and_a_version(monkeypatch):
    assert jiggle_d6.CACHE_KEY_VERSION == 2
    assert jiggle_d6.cache_file("run_cycle", "solver", loop=True) == "run_cycle.loop.npz"
    assert jiggle_d6.cache_file("run_cycle", "solver", loop=False) == "run_cycle.npz"
    assert jiggle_d6.cache_file("run_cycle", None, True) == "run_cycle.loop.npz"  # default model
    # the older models do not use the flag: one entry, the 1.3.0 name
    assert jiggle_d6.cache_file("run_cycle", "pinned", loop=True) == "run_cycle.npz"
    assert jiggle_d6.cache_file("run_cycle", "pivot", loop=True) == "run_cycle.npz"
    with pytest.raises(ValueError):
        jiggle_d6.cache_file("x", "wobbly")
    now = jiggle_d6.cache_signature("solver")
    monkeypatch.setattr(jiggle_d6, "CACHE_KEY_VERSION", 1)
    assert jiggle_d6.cache_signature("solver") != now  # key 1 directories are not read again
    assert jiggle_d6.cache_signature("pinned") == "pinned-engine-b1de22ed"  # 1.3.0 tags stay
    assert jiggle_d6.cache_signature("pivot") == "pivot-capture-b1de22ed"


# ------------------------------------------------------------------ navigation
def _loose_game(root, sub="derived_pc"):
    """<root>/game/<sub>/levels/game.block_* beside data/ and data_baked/, the layout
    of Part 1 on PC and Xbox Live."""
    src = tt.loose_tree(root / "tmp") / "derived_pc" / "levels"
    dst = root / "game" / sub / "levels"
    dst.mkdir(parents=True)
    for f in src.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    g = root / "game" / "data" / "Levels" / "Game_Levels_Part2" / "Demo" / "Gameplay"
    g.mkdir(parents=True)
    (g / "DemoAIPath.hpd").write_bytes(tn.demo_hpd())
    (g / "notes.txt").write_bytes(b"x")
    c = root / "game" / "data" / "Art" / "cutscenes"
    c.mkdir(parents=True)
    (c / "Cutscene01.bik").write_bytes(BIK)
    b = root / "game" / "data_baked" / "tnt" / "production"
    b.mkdir(parents=True)
    (b / "database.bin").write_bytes(b"DB")
    return root / "game" / sub


HPD_NAME = "data/Levels/Game_Levels_Part2/Demo/Gameplay/DemoAIPath.hpd"
BIK_NAME = "data/Art/cutscenes/Cutscene01.bik"
#: a Bink header: 300 frames, 1280 x 720, 30000 / 1001 frames per second
BIK = b"BIKi" + struct.pack("<8I", 0, 300, 0, 0, 1280, 720, 30000, 1001) + b"\0" * 8


@pytest.mark.parametrize("sub", ["derived_pc", "derived_x360"])
def test_loose_source_files_are_found_beside_the_source(tmp_path, sub):
    src = _loose_game(tmp_path, sub)
    got = nd.loose_source_files(str(src))
    assert [n for n, _p in got] == [
        BIK_NAME,
        HPD_NAME,
        "data_baked/tnt/production/database.bin",
    ]
    assert all(os.path.isfile(p) for _n, p in got)
    # an archive, a missing path and a folder without such siblings have none
    naz = tmp_path / "game.naz"
    naz.write_bytes(b"x")
    assert nd.loose_source_files(str(naz)) == []
    assert nd.loose_source_files(str(tmp_path / "nope")) == []
    assert nd.loose_source_files(str(src / "levels")) == []
    # the folder above (which holds data/ itself) works too, and lists each file once
    assert [n for n, _p in nd.loose_source_files(str(src.parent))][:2] == [BIK_NAME, HPD_NAME]


def test_nav_inputs_accept_single_files_among_the_trees(tmp_path):
    src = _loose_game(tmp_path)
    ex = tmp_path / "ex"
    (ex / "Gameplay").mkdir(parents=True)
    (ex / "Gameplay" / "DemoAIPath.aipathdata").write_bytes(tn.make_aipathdata())
    found = dict(nd.loose_source_files(str(src)))
    hpd = found[HPD_NAME]
    (e,) = nd.find_inputs([str(ex), hpd, found["data_baked/tnt/production/database.bin"]])
    assert e["level"] == "Demo" and e["hpd"] == hpd and e["aipathdata"].endswith(".aipathdata")


def _seed_definition(out):
    a = out / "extracted" / "Levels" / "Game_Levels_Part2" / "Demo" / "Gameplay"
    a.mkdir(parents=True)
    (a / "DemoAIPath.aipathdata").write_bytes(tn.make_aipathdata())


def test_extract_of_a_loose_folder_brings_the_path_data_along(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("WATCHMEN_NAMES", raising=False)  # the default naming
    src = _loose_game(tmp_path)
    out = tmp_path / "out"
    _seed_definition(out)  # what the block pass leaves behind
    args = ["--no-textures", "--no-models", "--no-text", "--no-audio"]
    assert wx.main([str(src), "-o", str(out)] + args) == 0
    log = capsys.readouterr().out
    # where the archive sets have them, and spelled as an archive spells its entries
    # (--names canonical, the default: lower case)
    gameplay = out / "files" / "data" / "levels" / "game_levels_part2" / "demo" / "gameplay"
    assert gameplay.is_dir() and "levels" in os.listdir(out / "files" / "data")
    assert (out / "files" / "data_baked" / "tnt" / "production" / "database.bin").is_file()
    assert sorted(p.name for p in (out / "nav").iterdir()) == ["Demo.nav.glb", "Demo.nav.json"]
    doc = json.loads((out / "nav" / "Demo.nav.json").read_text(encoding="utf-8"))
    assert doc["source"] == {"hpd": "demoaipath.hpd", "aipathdata": "DemoAIPath.aipathdata"}
    assert "LOOSE SOURCE: 3 file(s) from beside " in log
    assert "(1 .hpd path data, 1 .bik movie(s), 1 other)" in log
    assert "  files       : 5\n" in log  # the two block halves + the three copies
    # the movie is where an archive set has it, and textmeta reads its length there
    staged = out / "files" / "data" / "art" / "cutscenes" / "cutscene01.bik"
    assert staged.read_bytes() == BIK and "art" in os.listdir(out / "files" / "data")
    facts = ta.movie_file_facts("/Art/cutscenes/Cutscene01.bik", ta._bik_index(str(out)))
    assert facts["frames"] == 300 and facts["fps"] == 29.97 and facts["duration_s"] == 10.01
    assert "no path data" not in log


def test_extract_no_files_reads_the_loose_path_data_in_place(tmp_path, capsys):
    src = _loose_game(tmp_path)
    out = tmp_path / "out"
    _seed_definition(out)
    args = ["--no-files", "--no-textures", "--no-models", "--no-text", "--no-audio"]
    assert wx.main([str(src), "-o", str(out)] + args) == 0
    assert not (out / "files").exists() and (out / "nav" / "Demo.nav.glb").is_file()
    assert "LOOSE SOURCE" not in capsys.readouterr().out
    assert ta._bik_index(str(out)) == {}  # --no-files: the movies are not fetched


def test_extract_names_the_levels_left_without_path_data(tmp_path, capsys):
    """Without the sibling data/ folder there is only the definition: 1.3.0 wrote the
    32 KB .nav.json and no .nav.glb, silently."""
    src = _loose_game(tmp_path)
    (src.parent / "data" / "Levels" / "Game_Levels_Part2" / "Demo" / "Gameplay").rename(
        src.parent / "elsewhere"
    )
    out = tmp_path / "out"
    _seed_definition(out)
    args = ["--no-files", "--no-textures", "--no-models", "--no-text", "--no-audio"]
    assert wx.main([str(src), "-o", str(out)] + args) == 0
    assert [p.name for p in (out / "nav").iterdir()] == ["Demo.nav.json"]
    assert (
        "  WARNING: nav: no path data (.hpd) found for Demo: definition only"
        in capsys.readouterr().out
    )


def test_level_finds_its_path_data_by_the_definition_it_names(nav_level):
    """Part 1 `Streets2` lives in the folder `Street2` and `Undergound` in
    `Underground`: the level's name is not the name of the navigation entry."""
    asset = "/Levels/Game_Levels_Part2/Demo/Gameplay/DemoAIPath.aipathdata"
    assert lm.find_nav(str(nav_level), "Demo")[1] == "demoaipath.hpd"  # by name, as before
    assert lm.find_nav(str(nav_level), "Dem0") == (None, None)
    table, src = lm.find_nav(str(nav_level), "Dem0", ["/x/Terrain.terrain", asset.upper()])
    assert src == "demoaipath.hpd" and len(table) == 1
    assert lm.find_nav(str(nav_level), "Dem0", ["/Other/Gameplay/DemoAIPath.aipathdata"]) == (
        None,
        None,
    )


def test_level_without_path_data_says_so(nav_level, tmp_path):
    import shutil

    ((scene, name, sid, _asset),) = lm.levels(str(nav_level))
    j = lm.build_level(scene, name, sid, str(nav_level))
    assert j["nav"]["linked"] == 1 and "nav_note" not in j
    shutil.rmtree(str(nav_level / "files"))
    j = lm.build_level(scene, name, sid, str(nav_level))
    assert j["nav"] is None and j["nav_note"] == lm.NAV_MISSING_NOTE
    assert "files/data/" in j["nav_note"] and "navmeta" in j["nav_note"]
    lines = []
    lm.write(str(nav_level), str(tmp_path / "lv"), log=lines.append)
    assert len(lines) == 2 and lines[1].startswith(
        "    WARNING: Demo: 3 path objects but no path data (.hpd) in "
    )


# ------------------------------------------------------------------ level uids
def _door_level(root, extra_first):
    """The level of test_feature_seams (a door template instanced twice); with
    `extra_first` another fragment is loaded BEFORE the doors, as on a platform
    that has one fragment more."""
    base = root / "extracted"
    scene = tl._node(fs.SCENE, "SceneNode", "", None)
    scene += tl._node(fs.SCENES, "Folder", "Scenes", fs.SCENE)
    scene += tl._node(
        fs.LVL, "SceneScope(LoadBlock)", "Demo", fs.SCENES, 1, localPos=[0.0, 0.0, 0.0],
        localOrient=tl.ID, assetName="/Levels/Game_Levels_Part2/Demo/Demo.fragment", m_isceneid=9,
    )  # fmt: skip
    tl._write(base / "Levels" / "Game_Levels_Part2" / "Demo.scene", tl._fragment(scene))
    door, crate = "/LevelDesign/Door.fragment", "/LevelDesign/Crate.fragment"
    lvl = b""
    if extra_first:
        lvl += tl._node(
            0x1F, "FragmentNode", "crate", "host", 0, localPos=[1.0, 0.0, 1.0],
            localOrient=tl.ID, assetName=crate,
        )  # fmt: skip
    for nid, nm, order, x in ((fs.HOST_A, "door near", 1, -5.0), (fs.HOST_B, "door far", 2, 40.0)):
        lvl += tl._node(
            nid, "FragmentNode", nm, "host", order, localPos=[x, 0.0, 2.0],
            localOrient=tl.ID, assetName=door,
        )  # fmt: skip
    tl._write(base / "Levels" / "Game_Levels_Part2" / "Demo" / "Demo.fragment", tl._fragment(lvl))
    d = tl._node(
        fs.PO, "KynapseDoor(AIStaticPathObjectNode)", "", "host", 0, localPos=[0.0, 0.0, 0.0],
        localOrient=tl.ID,
    )  # fmt: skip
    tl._write(base / "LevelDesign" / "Door.fragment", tl._fragment(d))
    c = tl._node(0x70, "ModelNode", "crate", "host", 0, localPos=[0.0, 0.0, 0.0], localOrient=tl.ID)
    tl._write(base / "LevelDesign" / "Crate.fragment", tl._fragment(c))
    ((scene_path, name, sid, _asset),) = lm.levels(str(root))
    return lm.build_level(scene_path, name, sid, str(root))


def test_stable_uid_does_not_depend_on_the_load_order(tmp_path):
    a = _door_level(tmp_path / "a", extra_first=False)
    b = _door_level(tmp_path / "b", extra_first=True)

    def doors(j):
        return {p["world"]["pos"][0]: p["uid"] for p in j["path_objects"]}

    def stable(j, uid):
        k, nid = uid.split(":")
        return "%s@%s" % (nid, j["stable_ids"][int(k)])

    # the extra fragment renumbers every instance behind it: the uids differ ...
    assert all(doors(a)[x] != doors(b)[x] for x in doors(a)) and len(doors(a)) == 2
    # ... the stable uids are the same, and still tell the two doors apart
    sa = {x: stable(a, u) for x, u in doors(a).items()}
    sb = {x: stable(b, u) for x, u in doors(b).items()}
    assert sa == sb and len(set(sa.values())) == 2
    for j in (a, b):
        assert len(j["stable_ids"]) == len(set(j["stable_ids"]))
        assert all(len(s) == 8 and int(s, 16) >= 0 for s in j["stable_ids"])
        for f in j["fragments"]:
            assert f["stable_id"] == j["stable_ids"][f["index"]]
        assert "load order" in j["conventions"]["stable_uid"]
        assert j["conventions"]["uid"].startswith("<fragment instance index>:<node id>")
    fa = {f["stable_id"]: f["asset"] for f in a["fragments"]}
    fb = {f["stable_id"]: f["asset"] for f in b["fragments"]}
    assert set(fa.items()) < set(fb.items())  # b = a plus the crate
    assert sorted(set(fb.values()) - set(fa.values())) == ["/LevelDesign/Crate.fragment"]


def test_graph_nodes_carry_the_stable_uid_beside_the_uid(extract):
    (found,) = [x for x in lm.levels(str(extract)) if x[1] == "Lvl"]
    j = lm.build_level(found[0], found[1], found[2], str(extract))
    nodes = j["graph"]["nodes"]
    assert len(nodes) > 5 and len(set(n["stable_uid"] for n in nodes)) == len(nodes)
    for n in nodes:
        k, nid = n["uid"].split(":")
        assert n["stable_uid"] == "%s@%s" % (nid, j["stable_ids"][int(k)]) and n["id"] == nid
    # nodes of the nested fragment hang from another instance than the level's own
    assert len(set(n["stable_uid"].split("@")[1] for n in nodes)) >= 2
    assert list(j).index("stable_ids") == list(j).index("fragments") + 1


def test_instance_stable_id_is_the_hash_of_the_host_chain():
    import hashlib

    class _N:
        def __init__(self, nid, inst):
            self.id, self.inst = nid, inst

    class _I:
        def __init__(self, host):
            self.host = host

    top = _I(None)
    mid = _I(_N("0000002a", top))
    leaf = _I(_N("deadbeef", mid))
    assert lm.instance_chain(top) == "scene" and lm.instance_chain(None) == "scene"
    assert lm.instance_chain(leaf) == "scene/0000002a/deadbeef"
    assert lm.instance_stable_id(leaf) == hashlib.sha1(b"scene/0000002a/deadbeef").hexdigest()[:8]
    assert len({lm.instance_stable_id(x) for x in (top, mid, leaf)}) == 3


# ----------------------------------------------------------------------- usage
def test_gendata_usage_lists_respell(capsys):
    import watchmen

    assert watchmen.main(["watchmen", "gendata"]) == 2
    text = capsys.readouterr()
    assert "strings|respell|regdump|propnames|keys-export|keys-import|check" in text.out + text.err
