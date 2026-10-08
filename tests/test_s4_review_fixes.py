"""Fixes that came out of the coverage check of the export.

    name scan     the track-name scan of a clip starts behind the five header words: a
                  big-endian clip with 882 keys read as one track named "r" from byte 11
    stale bakes   a cached bake without `scan` of such a clip is baked again, and a GLB
                  older than a bake of its skeleton is rewritten
    char          `watchmen char` looks for the clip families of the skeleton
    levelmeta     models[].local / parent_chain_without_transform / host_offset_copy,
                  three counts, the evidence of the world rule and of the hero models
    savemeta      button_map.code_names from the engine's three input enums
    textmeta      movie strings spelled as the exported file; the markup evidence
    tables        the Underboss re-check default, event 60, the nav override evidence

Synthetic fixtures only."""

import json
import os
import re
import struct
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import bake_v4
import canonical_names as cn
import characters_export as ce
import fx_meta
import level_meta as lm
import nav_data as nd
import text_assets as ta
import variant_glb as vg

import test_p1_formats as tf
import test_p1_level as tl
import test_p6_anim as tp

bind = tp.bind  # the fixtures of those modules, used below
movie_extract = tf.movie_extract
HERE = os.path.dirname(os.path.abspath(__file__))
I4 = (0.0, 0.0, 0.0, 1.0)


@pytest.fixture(autouse=True)
def names_mode(monkeypatch):
    monkeypatch.delenv("WATCHMEN_NAMES", raising=False)
    cn.end()
    yield
    cn.end()


# ------------------------------------------------------------------ the name scan
def _const_clip(order, keys, names):
    """A clip of constant tracks (type 3) in byte order `order` with `keys` in its header."""
    b = bytearray(struct.pack(order + "ffIII", (keys - 1) / 88.0, 88.0, 0, keys, 1))
    b += struct.pack(order + "I", len(names))
    for nm in names:
        raw = nm.encode() + b"\0"
        b += struct.pack(order + "I", len(raw)) + raw
    for k, _nm in enumerate(names):
        b += bytes([3]) + struct.pack(order + "3f", 0.0, 0.5 if k == 0 else 0.0, 0.0)
        b += b"\0\0\0\0" + struct.pack(order + "4f", *I4)
    return bytes(b)


def test_the_name_scan_starts_behind_the_header():
    be = _const_clip(">", 0x372, ["Bip", "Hand"])
    # 00 00 03 72 at byte 12: read from byte 11 it is the length 3 and the name "r"
    assert bake_v4._name_scan(be, ">", 0) == 11 and bake_v4.NAME_SCAN_START == 20
    assert bake_v4._name_scan(be, ">") == 24 and bake_v4._name_scan(be, "<") is None
    assert bake_v4._detect_clip_order(be) == ">"
    assert sorted(bake_v4.walk(be)) == ["Bip", "Hand"]
    assert bake_v4.scan_start_matters(be) and bake_v4.scan_start_matters(be[:400])
    le = _const_clip("<", 0x372, ["Bip", "Hand"])
    assert bake_v4._detect_clip_order(le) == "<" and sorted(bake_v4.walk(le)) == ["Bip", "Hand"]
    assert not bake_v4.scan_start_matters(le)
    assert not bake_v4.scan_start_matters(_const_clip(">", 13, ["Bip", "Hand"]))
    assert bake_v4.walk(b"\0" * 64) == {} and bake_v4._detect_clip_order(b"") == "<"


def test_a_bake_of_a_clip_the_old_scan_misread_is_baked_again(tmp_path, bind, monkeypatch):
    path, _tb = bind
    ex, out = tmp_path / "ex", tmp_path / "out"
    d = ex / "extracted" / "Animation" / "T"
    d.mkdir(parents=True)
    (d / "T_cage.animation").write_bytes(_const_clip(">", 0x372, ["Bip", "Hand"]))
    (d / "T_idle.animation").write_bytes(_const_clip(">", 13, ["Bip", "Hand"]))
    monkeypatch.setitem(ce.CLIP_PREFIX, "t", ("T",))
    cdir = out / "_bake" / "t"
    cdir.mkdir(parents=True)
    old = dict(pal=np.full((2, 4, 3, 4), 7, np.float32), dur=np.float32(1), fps=np.float32(1))
    for nm in ("T_cage", "T_idle"):  # caches of the same pose rule, written without `scan`
        np.savez(cdir / (nm + ".npz"), rule=np.int32(bake_v4.POSE_RULE), **old)
    assert ce.bake_is_current(str(cdir / "T_cage.npz"))  # without the clip: the rule only
    assert not ce.bake_is_current(str(cdir / "T_cage.npz"), str(d / "T_cage.animation"))
    # named with its clip, a bake must record the clip's bytes (clip_sha): these do not
    assert not ce.bake_is_current(str(cdir / "T_idle.npz"), str(d / "T_idle.animation"))
    assert not ce.bake_is_current(str(cdir / "T_idle.npz"), str(d / "missing.animation"))
    assert ce.bake_cache("t", path, str(ex), str(out)) == (2, 0)
    cage, idle = np.load(cdir / "T_cage.npz"), np.load(cdir / "T_idle.npz")
    assert int(cage["scan"]) == bake_v4.NAME_SCAN_START and not (cage["pal"] == 7).any()
    assert int(idle["scan"]) == bake_v4.NAME_SCAN_START and not (idle["pal"] == 7).any()
    # a bake that stores the scan is current whatever its clip looks like
    assert ce.bake_is_current(str(cdir / "T_cage.npz"), str(d / "T_cage.animation"))
    np.savez(cdir / "other.npz", rule=np.int32(bake_v4.POSE_RULE), scan=np.int32(0), **old)
    assert not ce.bake_is_current(str(cdir / "other.npz"))


def test_a_glb_older_than_a_bake_of_its_skeleton_is_rewritten(tmp_path, capsys):
    cdir = tmp_path / "_bake" / "t"
    cdir.mkdir(parents=True)
    assert ce.newest_bake_time(str(cdir)) is None
    for i, nm in enumerate(("a.npz", "b.npz", "c.tmp.npz")):
        (cdir / nm).write_bytes(b"x")
        os.utime(cdir / nm, (1000 + 100 * i, 1000 + 100 * i))
    assert ce.newest_bake_time(str(cdir)) == 1100  # a torn write does not count
    glb = tmp_path / "A.glb"
    glb.write_bytes(b"not a glb")  # no frame mark: the frame test lets it pass
    os.utime(glb, (1100, 1100))
    assert ce.glb_is_current(str(glb)) and ce.glb_is_current(str(glb), 1100)
    assert not ce.glb_is_current(str(glb), 1100.5)
    assert "older than a bake of its skeleton" in capsys.readouterr().out
    assert not ce.glb_is_current(str(tmp_path / "missing.glb"), 1)
    import inspect

    src = inspect.getsource(ce.export)
    assert "baked = newest_bake_time(cdir)" in src
    assert "glb_is_current(out, baked, opts, outdir)" in src


# ------------------------------------------------------------------ watchmen char
def test_char_takes_the_clip_families_of_the_skeleton(tmp_path):
    assert vg.clip_families("Female_Skeleton") == ("EN4", "BS2")
    assert vg.clip_families("Large_Gimp_Skeleton") == ("EN2",)
    # 1.3.0: EN4 for these three, so their GLBs had no clip
    assert vg.clip_families("Medium_Skeleton") == ("EN1",)
    assert vg.clip_families("Rorschach") == ("RSH",) and vg.clip_families("NiteOwl") == ("NTO",)
    assert vg.clip_families("Unknown_Skeleton") == ("EN4",)
    p2 = tmp_path / "p2" / "extracted" / "TNT" / "Production" / "Fragments" / "Enemy"
    p1 = tmp_path / "p1" / "extracted" / "TNT" / "Production" / "Fragments" / "Enemy"
    for d in (p1, p2):
        d.mkdir(parents=True)
        (d / "ThugFast.fragment.json").write_text("{}")
    (p1 / "Biker.fragment").write_bytes(b"")  # what marks a Part 1 extract
    assert vg.clip_families("Small_Skeleton", str(p2 / "ThugFast.fragment.json")) == ("EN1",)
    assert vg.clip_families("Small_Skeleton", str(p1 / "ThugFast.fragment.json")) == ("EN1", "EN3")
    assert vg.clip_families("Large_Skeleton", str(p1 / "ThugFast.fragment.json")) == ("EN1", "EN2")
    assert vg.clip_families("Female_Skeleton", str(p1 / "x.json")) == ("EN4", "BS2")
    assert vg.clip_families("Small_Skeleton", str(tmp_path / "loose.json")) == ("EN1",)
    note = vg.no_bake_note("bake", ("EN1", "EN3"))
    assert "no bake in bake for the clip families EN1/EN3 (EN1*.npy)" in note
    import inspect

    src = inspect.getsource(vg.build)
    assert "clip_families(skel, fragjson)" in src and "no_bake_note(bakedir, prefix)" in src


# ------------------------------------------------------------------ levelmeta
ID = tl.ID
SCENE, LVL = 0x10, 0x12
FOLD, PVS, DEEP, LINKED = 0x30, 0x31, 0x32, 0x33
M_UP, M_ALONE, M_PLACED, M_HOST, M_DEEP, M_LINK = range(0x40, 0x46)
M_UP2, M_PLACED2, M_UP3, M_PLACED3 = range(0x46, 0x4A)
HOST_POS = [100.0, 50.0, -105.0]
# StreetsOfRiot block C: one folder copy and its placed twin differ in one component
Q_COPY, Q_PLACED = [0.0, 0.894935, 0.0, 0.446197], [0.0, 0.894934, 0.0, 0.446197]
Q_OTHER = [0.0, 0.893935, 0.0, 0.446197]  # 1e-3 away: another orientation


@pytest.fixture(scope="module")
def level(tmp_path_factory):
    """A fragment whose host is moved: a crowd under a root that cancels the host, the
    folder copy of one of them beside it, and models at other depths."""
    base = tmp_path_factory.mktemp("s4level") / "extracted"
    n = tl._node
    scene = n(SCENE, "SceneNode", "", None)
    scene += n(
        LVL, "SceneScope(LoadBlock)", "Lvl", SCENE, 1, assetName="/L/Lvl.fragment",
        localPos=HOST_POS, localOrient=ID,
    )  # fmt: skip
    tl._write(base / "L" / "Lvl.scene", tl._fragment(scene))
    model = lambda nid, name, parent, order, pos, quat=ID, **kw: n(
        nid, "Model", name, parent, order, localPos=pos, localOrient=quat,
        modelNames=["/art/props/%s.model" % name], **kw,
    )  # fmt: skip
    f = n(FOLD, "Folder", "NoCombat", "host", 0)
    f += n(PVS, "PVSRootNode", "PVS", "host", 1, localPos=[-100.0, -50.0, 105.0], localOrient=ID)
    f += model(M_UP, "copy", FOLD, 0, [98.5, 3.0, -144.75])
    f += model(M_ALONE, "alone", FOLD, 1, [90.0, 3.0, -140.0])
    f += model(M_PLACED, "placed", PVS, 0, [98.5, 3.0, -144.75])
    f += model(M_HOST, "hostrel", "host", 2, [1.0, -50.0, 2.0])
    f += n(DEEP, "DynamicObjectCollection(Folder)", "deep", FOLD, 2)
    f += model(M_DEEP, "deepone", DEEP, 0, [5.0, -50.0, 5.0])
    f += n(LINKED, "PivotNode", "linked", "host", 3, localPos=[7.0, 8.0, 9.0], localOrient=ID)
    f += model(M_LINK, "kept", LINKED, 0, [1.0, 2.0, 3.0], parentLink=1)
    f += model(M_UP2, "copy2", FOLD, 3, [80.0, 3.0, -130.0], Q_COPY)
    f += model(M_PLACED2, "placed2", PVS, 1, [80.0, 3.0, -130.0], Q_PLACED)
    f += model(M_UP3, "copy3", FOLD, 4, [70.0, 3.0, -120.0], Q_COPY)
    f += model(M_PLACED3, "placed3", PVS, 2, [70.0, 3.0, -120.0], Q_OTHER)
    tl._write(base / "L" / "Lvl.fragment", tl._fragment(f, name="Lvl_Main", singleton=True))
    return lm.build_level(str(base / "L" / "Lvl.scene"), "Lvl", "%08x" % LVL, None)


def _m(level, name):
    return next(r for r in level["models"] if r["name"] == name)


def test_models_carry_the_stored_transform_and_the_chain_passed_over(level):
    copy, placed = _m(level, "copy"), _m(level, "placed")
    assert copy["local"] == placed["local"] == {"pos": [98.5, 3.0, -144.75], "quat": ID}
    assert copy["world"]["pos"] == [198.5, 53.0, -249.75]  # the host is applied once
    assert placed["world"]["pos"] == [98.5, 3.0, -144.75]
    assert copy["parent_chain_without_transform"] == ["Folder"]
    assert placed["parent_chain_without_transform"] == []
    assert _m(level, "hostrel")["parent_chain_without_transform"] == []
    deep = _m(level, "deepone")["parent_chain_without_transform"]
    assert len(deep) == 2 and deep[1] == "Folder"  # nearest first
    kept = _m(level, "kept")
    # parentLink = 1 composes like any node (0x48d789): host + linked + local
    assert kept["world"]["pos"] == [108.0, 60.0, -93.0] and kept["local"]["pos"] == [1.0, 2.0, 3.0]


def test_a_copy_left_in_host_coordinates_is_marked(level):
    copy, placed = _m(level, "copy"), _m(level, "placed")
    assert copy["host_offset_copy"] == {"twin": placed["uid"]}
    assert _m(level, "alone")["host_offset_copy"] == {"twin": None}  # same folder, no twin
    # the same stored position and a quaternion 1e-6 away in one component: a twin
    copy2, placed2 = _m(level, "copy2"), _m(level, "placed2")
    assert copy2["local"]["pos"] == placed2["local"]["pos"]
    dq = [abs(a - b) for a, b in zip(copy2["local"]["quat"], placed2["local"]["quat"])]
    assert 0 < max(dq) < 2e-6 and max(dq) < lm.HOST_OFFSET_QUAT_TOLERANCE == 1e-5
    assert copy2["host_offset_copy"] == {"twin": placed2["uid"]}
    # 1e-3 away is another orientation: no twin, marked as a model of the same folder
    assert _m(level, "copy3")["host_offset_copy"] == {"twin": None}
    for name in ("placed", "placed2", "placed3", "hostrel", "deepone", "kept"):
        assert "host_offset_copy" not in _m(level, name), name
    c = level["counts"]
    assert c["host_offset_copies"] == 4 and c["parent_link_1"] == 1
    assert c["placements_below_transformless_ancestor"] == 5
    rule = level["conventions"]["host_offset_copy"]
    assert rule == lm.HOST_OFFSET_RULE and "not established: whether the game draws" in rule
    assert "inferred: an editor leftover" in rule and "within 1e-5" in rule
    assert "each of the seven placed ones is the twin of one of them" in rule


def test_a_host_at_the_origin_marks_nothing(tmp_path):
    base = tmp_path / "extracted"
    n = tl._node
    scene = n(SCENE, "SceneNode", "", None)
    scene += n(LVL, "SceneScope(LoadBlock)", "Lvl", SCENE, 1, assetName="/L/Lvl.fragment")
    tl._write(base / "L" / "Lvl.scene", tl._fragment(scene))
    f = n(FOLD, "Folder", "a", "host", 0)
    f += n(PVS, "Folder", "b", "host", 1)
    for nid, par in ((M_UP, FOLD), (M_PLACED, PVS)):
        f += n(
            nid, "Model", "twin%d" % nid, par, 0, localPos=[1.0, 2.0, 3.0], localOrient=ID,
            modelNames=["/art/props/x.model"],
        )  # fmt: skip
    tl._write(base / "L" / "Lvl.fragment", tl._fragment(f, name="Lvl_Main", singleton=True))
    lv = lm.build_level(str(base / "L" / "Lvl.scene"), "Lvl", "%08x" % LVL, None)
    assert len(lv["models"]) == 2 and lv["counts"]["host_offset_copies"] == 0
    assert all("host_offset_copy" not in m for m in lv["models"])
    assert lv["counts"]["parent_link_1"] == 0


def test_the_world_rule_and_the_hero_models_say_where_they_come_from():
    ev = lm.EVIDENCE["world"]
    assert "confirmed against the terrain on StreetsOfRiot" in ev and "inferred" not in ev
    assert "0x4932d4" in ev and "0x48d789" in ev and "keeps its local transform" not in ev
    assert "composes the same way" in lm.CONVENTIONS["world"]
    assert "0x49325d" in lm.CONVENTIONS["world"]
    hero = lm.EVIDENCE["hero_models"]
    assert "CharacterDef.command_get_override_model 0x666d03" in hero
    assert "LevelSceneCtrl.command_get_override_model 0x76ef49" in hero


# ------------------------------------------------------------------ savemeta
def test_button_codes_are_named_from_the_engines_enums():
    assert lm.input_code_name("X360_PS3", 0) == "GAMEPAD_DPAD_UP"
    assert lm.input_code_name("GENERIC_PC_GAMEPAD", 9) == "GAMEPAD_RIGHT_SHOULDER"
    assert lm.input_code_name("X360_PS3", 16) is None
    assert lm.input_code_name("KEYBOARD_MOUSE", 200) == "KEY_UP"
    assert lm.input_code_name("KEYBOARD_MOUSE", 1) == "KEY_ESCAPE"
    assert lm.input_code_name("KEYBOARD_MOUSE", 257) == "MOUSE_BUTTON_LEFT"
    assert lm.input_code_name("KEYBOARD_MOUSE", 260) == "MOUSE_BUTTON_RIGHT"
    assert lm.input_code_name("KEYBOARD_MOUSE", 259) is None  # 3 is no MouseButtons value
    with open(os.path.join(HERE, "..", "wlib", "input_code_enums.json"), encoding="utf-8") as fh:
        t = json.load(fh)
    assert len(t["KeyboardKeys"]) == 118 and len(t["GamepadButton"]) == 16
    assert t["MouseButtons"] == {
        "1": "MOUSE_BUTTON_LEFT",
        "2": "MOUSE_BUTTON_MIDDLE",
        "4": "MOUSE_BUTTON_RIGHT",
    }
    assert "inferred" in t["evidence"] and "0x4cc842" in t["evidence"]

    none = [-1, -1, -1]
    pad = [[0, -1, -1]] + [none] * 8 + [[9, 99, -1]]
    keys = [[200, -1, -1], [33, 257, -1]]
    bm = lm.button_map([[pad, []], [keys, []]])
    assert bm["devices"]["X360_PS3"][0]["buttons"]["MENU_UP"] == [0]
    assert bm["code_names"] == {
        "X360_PS3": {"0": "GAMEPAD_DPAD_UP", "9": "GAMEPAD_RIGHT_SHOULDER"},  # 99: no name
        "KEYBOARD_MOUSE": {"33": "KEY_F", "200": "KEY_UP", "257": "MOUSE_BUTTON_LEFT"},
    }
    assert "0x4d3514" in bm["evidence"] and "256 offset were not read" in bm["evidence"]
    assert "not established: the numbering" not in bm["evidence"]
    assert lm.button_map([[[], []]])["code_names"] == {}


# ------------------------------------------------------------------ textmeta
def test_text_meta_spells_a_movie_as_its_exported_file(movie_extract):
    d = movie_extract / "files" / "data" / "art" / "cutscenes"
    os.makedirs(str(d), exist_ok=True)
    (d / "logo.bik").write_bytes(b"x")
    m = ta.build(str(movie_extract))
    logo = [x for x in m["movies"] if (x.get("stored") or {}).get("movie")]
    assert logo and all(x["movie"] == "/art/cutscenes/logo.bik" for x in logo)
    assert all(x["stored"]["movie"] == "/Art/cutscenes/Logo.bik" for x in logo)
    assert m["asset_names"]["spelling"] == "export" and m["asset_names"]["respelled"] >= len(logo)
    # a movie whose file is not in the export keeps its string
    assert any("stored" not in x and x["movie"] for x in m["movies"])


def test_text_meta_names_stored_keeps_the_strings(movie_extract, monkeypatch):
    d = movie_extract / "files" / "data" / "art" / "cutscenes"
    os.makedirs(str(d), exist_ok=True)
    (d / "logo.bik").write_bytes(b"x")
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    m = ta.build(str(movie_extract))
    assert "asset_names" not in m and all("stored" not in x for x in m["movies"])
    assert any(x["movie"] == "/Art/cutscenes/Logo.bik" for x in m["movies"])


def test_the_markup_rules_are_given_as_read(movie_extract):
    m = ta.build(str(movie_extract))
    mk = m["evidence"]["markup"]
    assert mk.startswith("read (substitution 0x4b6fb7") and "0-based" in mk and "%1..%9" not in mk
    assert "code was not read" not in mk and "data only: Greek capitals" in mk
    read = mk.split("data only:")[0]
    assert "backslash + n are replaced by U+000A (0x4b7007-0x4b700e)" in read
    first = m["not_established"][0]
    assert first.startswith("TextBox layout on the Xbox 360 and PS3 builds")
    assert "read on PC Part 2 only" in first and "0x440c1e" in m["evidence"]["layout"]
    assert "U+000A" not in first and "re-checked" not in first and "researcher" not in first
    assert "code not read" not in first
    assert m["layout_rules"] == ta.LAYOUT_RULES and m["parameters"] == ta.PARAMETERS
    assert m["senders"] == ta.SENDERS


# ------------------------------------------------------------------ other tables
def test_event_60_says_which_effect_is_fired_and_which_started():
    ev = fx_meta.EVENT_EFFECTS[60]
    assert ev["effect_ids"] == [12, 13] and "0xcaf719fe" in ev["note"]
    assert "12 is fired" in ev["note"] and "checker" not in ev["note"]
    assert not any("checker" in str(v) for v in fx_meta.EVENT_EFFECTS.values())


def test_the_nav_override_evidence_names_the_follow_agent():
    ev = nd.EVIDENCE["config_runtime_overrides"]
    assert "0x489c1b: first path finder only" in ev and "0x934650: the follow agent" in ev


def test_no_text_speaks_of_the_time_until_this_version():
    root = os.path.join(HERE, "..")
    files = [os.path.join("docs", f) for f in sorted(os.listdir(os.path.join(root, "docs")))]
    files += [os.path.join("wlib", f) for f in sorted(os.listdir(os.path.join(root, "wlib")))]
    seen = 0
    for rel in files + ["README.md", "watchmen.py"]:
        if not rel.endswith((".md", ".py")):
            continue
        with open(os.path.join(root, rel), encoding="utf-8") as fh:
            text = " ".join(fh.read().split()).lower()
        seen += 1
        assert not re.search(r"until (toolkit )?1\.4\.0", text), rel
    assert seen > 60
