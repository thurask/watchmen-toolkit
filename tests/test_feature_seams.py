"""Seams between the six features added on top of the animation table: the combat
block, the effects block, the level export, text / subtitles, the particle parser
and the navigation data.

    cached table      a resumed character export reuses anim_meta.json only when it
                      carries every block this toolkit writes (face, combat, fx)
    two hooks         combat_meta and fx_meta both decorate one table: no key of one
                      is a key of the other, the table stays watchmen-anim-meta/2
    GLB extras        a clip's pair entries carry the finisher camera cuts and the
                      pair trigger
    particles         fx_meta reads .particle through the engine grammar
    grade             the two FXGfxEffectCtrl script properties that say whose node
                      a grade is (initialize_external 0x73ccb6)
    navigation        `extract` writes nav/; a level's path-object nodes are joined
                      to the path data's path-object table by position

Synthetic fixtures only (those of the feature tests are reused)."""

import copy
import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import characters_export as ce
import combat_meta as cm
import face_rule
import fx_meta as fx
import level_meta as lm
import materials
import nav_data as nd
import sound_meta
import text_assets
import watchmen_extract as wx

import test_level_meta as tl
import test_nav_data as tn
import test_particle_asset as tp
import test_text_assets as tt
import test_combat_meta
import test_fx_meta

# the fixtures of the two feature tests, under names of this module
combat_extract = test_combat_meta.extract
fx_extract = test_fx_meta.fx_extract


# ----------------------------------------------------------- the cached table
def _current():
    return {
        "format": am.FORMAT,
        "revision": am.REVISION,
        "face_format": face_rule.FACE_FORMAT,
        "combat_format": cm.COMBAT_FORMAT,
        "fx_format": fx.FORMAT,
    }


def _resume(tmp_path, monkeypatch, table):
    out = tmp_path / "CHARS"
    out.mkdir()
    (out / "anim_meta.json").write_text(json.dumps(dict(table, marker="cached")))
    built = []

    def build(extract_out, binds=None):
        built.append(extract_out)
        return dict(_current(), marker="new")

    monkeypatch.setattr(am, "build", build)
    monkeypatch.setattr(am, "find_class_fragments", lambda ex: {"Enemy01": "x"})
    monkeypatch.setattr(am, "summary", lambda m: "summary")
    monkeypatch.setattr(face_rule, "find_face_fragments", lambda ex: {"Enemy01Face": "x"})
    got = ce.animation_meta(str(tmp_path), str(out))
    return got["marker"], len(built), json.loads((out / "anim_meta.json").read_text())


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_a_current_table_is_reused(tmp_path, monkeypatch):
    assert _resume(tmp_path, monkeypatch, _current())[:2] == ("cached", 0)


@pytest.mark.parametrize("missing", ["combat_format", "fx_format"])
def test_a_table_from_before_the_combat_or_fx_block_is_rebuilt(tmp_path, monkeypatch, missing):
    """An output folder written before the block existed has a table with the right
    `format` and `face_format`: reusing it would keep the old tables for good."""
    old = _current()
    del old[missing]
    marker, builds, on_disk = _resume(tmp_path, monkeypatch, old)
    assert (marker, builds) == ("new", 1)
    assert on_disk[missing] == _current()[missing]


@pytest.mark.parametrize(
    "key,value", [("combat_format", "watchmen-combat-meta/0"), ("fx_format", "watchmen-fx-meta/0")]
)
def test_a_table_with_another_block_format_is_rebuilt(tmp_path, monkeypatch, key, value):
    assert _resume(tmp_path, monkeypatch, dict(_current(), **{key: value}))[:2] == ("new", 1)


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_anim_meta_is_current_reads_the_markers(monkeypatch):
    monkeypatch.setattr(face_rule, "find_face_fragments", lambda ex: {})
    m = _current()
    del m["face_format"]  # an extract without face fragments has no face block
    assert ce.anim_meta_is_current(m, "x") is True
    assert ce.anim_meta_is_current(dict(m, format="watchmen-anim-meta/1"), "x") is False
    assert ce.anim_meta_is_current(None, "x") is False


# ------------------------------------------------- two hooks on the one table
STATE_KEYS = {
    "combat": {"group_criteria", "criteria_rendered", "combat"},
    "fx": {"fx"},
}
PAIR_KEYS = {"combat": {"trigger"}, "fx": {"camera_cuts", "camera_return", "fx"}}
TOP_KEYS = {"combat": {"combat_format", "combat"}, "fx": {"fx_format", "fx"}}
EVENT_KEYS = {"payload", "payload_stale", "payload_editor_hidden"}


def _plain(extract_out, monkeypatch):
    """The table as anim_meta alone writes it (both hooks switched off)."""
    with monkeypatch.context() as mp:
        mp.setattr(cm, "build_or_none", lambda *a, **k: None)
        mp.setattr(fx, "attach", lambda meta, *a, **k: meta)
        return am.build(str(extract_out))


def _added(full, plain):
    top = set(full) - set(plain)
    st, pr, ev = set(), set(), set()
    for cn, c in full["classes"].items():
        for s, s0 in zip(c["states"], plain["classes"][cn]["states"]):
            st |= set(s) - set(s0)
            for e, e0 in zip(s["events"], s0["events"]):
                ev |= set(e) - set(e0)
    for p, p0 in zip(full["pairs"], plain["pairs"]):
        pr |= set(p) - set(p0)
    return top, st, pr, ev


def _strip(m):
    m = copy.deepcopy(m)
    for k in TOP_KEYS["combat"] | TOP_KEYS["fx"]:
        m.pop(k, None)
    for c in m["classes"].values():
        for s in c["states"]:
            for k in STATE_KEYS["combat"] | STATE_KEYS["fx"]:
                s.pop(k, None)
            for e in s["events"]:
                for k in EVENT_KEYS:
                    e.pop(k, None)
    for c in m["clips"].values():
        for e in c["events"]:
            for k in EVENT_KEYS:
                e.pop(k, None)
    for p in m["pairs"]:
        for k in PAIR_KEYS["combat"] | PAIR_KEYS["fx"]:
            p.pop(k, None)
    return m


@pytest.mark.parametrize("which", ["combat", "fx"])
def test_both_blocks_share_the_table_without_touching_each_other(
    which, combat_extract, fx_extract, monkeypatch
):
    """Built on the combat fixture and on the effects fixture: both markers are
    there, the table is still format 2, every added key belongs to exactly one of
    the two blocks, and with those keys removed the table is the plain one."""
    root = combat_extract if which == "combat" else fx_extract
    full = am.build(str(root))
    plain = _plain(root, monkeypatch)
    assert full["format"] == plain["format"] == "watchmen-anim-meta/2"
    assert full["combat_format"] == cm.COMBAT_FORMAT and full["fx_format"] == fx.FORMAT
    assert "combat_format" not in plain and "fx_format" not in plain
    top, st, pr, ev = _added(full, plain)
    assert top == TOP_KEYS["combat"] | TOP_KEYS["fx"]
    assert st <= STATE_KEYS["combat"] | STATE_KEYS["fx"]
    assert pr <= PAIR_KEYS["combat"] | PAIR_KEYS["fx"]
    assert ev <= EVENT_KEYS
    for group in (STATE_KEYS, PAIR_KEYS, TOP_KEYS):
        assert not group["combat"] & group["fx"]
    assert json.dumps(_strip(full), sort_keys=True) == json.dumps(plain, sort_keys=True)
    # the two blocks describe themselves and do not nest into each other
    assert full["combat"]["format"] == cm.COMBAT_FORMAT and full["fx"]["format"] == fx.FORMAT
    assert "fx" not in full["combat"] and "combat" not in full["fx"]
    # what reads a format-2 table still does
    assert am.summary(full) == am.summary(plain)
    for name in list(full["clips"])[:5]:
        a, b = am.clip_extras(full, name), am.clip_extras(plain, name)
        for k in ("clip", "duration_s", "loop", "states", "speeds"):
            assert a[k] == b[k]
    assert ce.anim_meta_is_current(full, str(root)) is True
    assert ce.anim_meta_is_current(plain, str(root)) is False


# ------------------------------------------------------- GLB animation extras
def test_clip_extras_carry_the_pair_camera_and_trigger(fx_extract):
    m = am.build(str(fx_extract))
    (p,) = [x for x in m["pairs"] if x["master_state"] == "Finish_move_A"]
    assert len(p["camera_cuts"]) == 3 and p["camera_return"]["time_s"] == 1.4
    for clip, role in ((p["master_clip"], "master"), (p["partner_clip"], "partner")):
        x = am.clip_extras(m, clip, fps=30.0, frames=31)
        pr = [e for e in x["pairs"] if e["role"] == role and e["master_state"] == "Finish_move_A"]
        assert len(pr) == 1
        assert pr[0]["camera_cuts"] == p["camera_cuts"]  # on the pair clock, as in the table
        assert pr[0]["camera_return"] == p["camera_return"]
        assert pr[0]["timeline"] == p["timeline"]  # what the cut times are measured on
        assert ("trigger" in pr[0]) == bool(p.get("trigger"))
        if p.get("trigger"):
            assert pr[0]["trigger"] == p["trigger"]
        assert "fx" not in pr[0]  # the pair's effect lists stay in anim_meta.json
    json.dumps(am.clip_extras(m, p["master_clip"]))


def test_clip_extras_of_a_table_without_the_blocks_are_as_before(fx_extract, monkeypatch):
    plain = _plain(fx_extract, monkeypatch)
    (p,) = [x for x in plain["pairs"] if x["master_state"] == "Finish_move_A"]
    x = am.clip_extras(plain, p["master_clip"])
    assert x["pairs"] and not [k for e in x["pairs"] for k in am.CLIP_PAIR_EXTRA_KEYS if k in e]
    # a pair without cuts (an empty list) adds nothing either
    full = am.build(str(fx_extract))
    for q in full["pairs"]:
        if not q.get("camera_cuts"):
            for e in am.clip_extras(full, q["master_clip"])["pairs"]:
                if e["master_state"] == q["master_state"]:
                    assert "camera_cuts" not in e


# ------------------------------------------------------------------ particles
@pytest.mark.parametrize("bo", ["<", ">"])
def test_fx_particle_facts_use_the_engine_grammar(tmp_path, bo):
    """The generic property-bag walk reads little-endian typed files only; the
    grammar reads the console byte order too.  duration 2.5 s, not looping, two
    types, the longer life 0.35 s (the second type keeps the constructor's 1.0)."""
    p = tmp_path / "hit.particle"
    p.write_bytes(tp.sample(bo))
    got = fx.particle_facts(str(p))
    assert got["emit_duration_s"] == 2.5 and got["loop"] is False and got["types"] == 2
    assert got["particle_life_s_max"] == 1.0  # ParticleType constructor 0x55b2bb: life 1.0
    assert fx.particle_facts(str(tmp_path / "missing.particle")) is None


# ---------------------------------------------------------------------- grade
def test_grade_nodes_say_whose_they_are():
    frag = {
        "nodes_full": [
            {
                "type": "FXGfxEffectCtrl(GFXEffect)",
                "props": [
                    ["name", "string", "NO GFX"],
                    ["gamma", "number", 1.2],
                    ["m_tinitialgfxnode", "truth", False],
                    ["_iplayerctrl", "integer", 1],
                ],
            }
        ]
    }
    (g,) = materials.fragment_grades(frag)
    assert g["node"] == "NO GFX" and g["gamma"] == 1.2
    assert g["_iplayerctrl"] == 1 and g["m_tinitialgfxnode"] is False
    assert materials.GRADE_PROPS["_iplayerctrl"] == "integer"


# -------------------------------------------------------------- sound wording
def test_damage_rule_names_the_taser_not_a_sharp_extra_effect(fx_extract):
    """CharacterEffectDef.command_play_damage_effect 0x6673d0: SHARP selects the one
    sharpweapon slot; the extra effect (id 1) belongs to TASER."""
    import inspect

    src = inspect.getsource(sound_meta)
    assert "sharp adds sharpweapon" not in src
    assert "sharp = the one sharpweapon slot; taser = effect id 1" in src
    rule = fx.damage_rule()
    assert rule is not None and fx.damage_slots(2, "taser") != fx.damage_slots(2, "sharp")


# ------------------------------------------------------ text / subtitle keys
def test_sound_meta_and_textmeta_use_one_subtitle_key():
    for wave in (
        "/sounds/Speaks/TWILIGHT/BS2_TWL_Attack_RSH_05_uk.wav",
        "sounds\\x\\Line_A_uk_pc.wav",
        "/a/NoSuffix.wav",
    ):
        assert sound_meta._subtitle_key(wave) == text_assets.subtitle_key(wave)
    assert sound_meta._subtitle_key("/s/BS2_TWL_Attack_RSH_05_uk.wav") == "BS2_TWL_Attack_RSH_05"
    # the table is looked up case-insensitively: both sides fold the same way
    table = text_assets.subtitle_table([("line_a", "x")], 7.0)
    assert text_assets._fold(sound_meta._subtitle_key("/x/Line_A_uk_pc.wav")) in table


# ----------------------------------------------------------------- navigation
ARGS = ["--no-files", "--no-textures", "--no-models", "--no-text", "--quiet"]


def _nav_files(out):
    a = out / "extracted" / "Levels" / "Game_Levels_Part2" / "Demo" / "Gameplay"
    f = out / "files" / "data" / "levels" / "game_levels_part2" / "demo" / "gameplay"
    for d in (a, f):
        d.mkdir(parents=True)
    (a / "DemoAIPath.aipathdata").write_bytes(tn.make_aipathdata())
    (f / "demoaipath.hpd").write_bytes(tn.demo_hpd())


def test_extract_writes_the_navigation_data(tmp_path):
    files = tt.loose_tree(tmp_path)
    out = tmp_path / "out"
    _nav_files(out)  # what the files pass and the block pass leave behind
    assert wx.main([str(files), "-o", str(out)] + ARGS) == 0
    assert sorted(p.name for p in (out / "nav").iterdir()) == ["Demo.nav.glb", "Demo.nav.json"]
    doc = json.loads((out / "nav" / "Demo.nav.json").read_text(encoding="utf-8"))
    assert doc["format"] == "watchmen-nav/1" and doc["source"]["hpd"] == "demoaipath.hpd"
    assert doc["coverage"]["undecoded_bytes"] == 0


def test_extract_no_nav_and_nothing_to_write(tmp_path):
    files = tt.loose_tree(tmp_path)
    off = tmp_path / "off"
    _nav_files(off)
    assert wx.main([str(files), "-o", str(off), "--no-nav"] + ARGS) == 0
    assert not (off / "nav").exists()
    none = tmp_path / "none"  # an extract without path data gets no empty folder
    assert wx.main([str(files), "-o", str(none)] + ARGS) == 0
    assert not (none / "nav").exists()


def test_nav_inputs_are_searched_in_the_two_extract_folders_only(tmp_path):
    out = tmp_path / "out"
    _nav_files(out)
    stray = out / "characters" / "x" / "gameplay"  # an export folder beside them
    stray.mkdir(parents=True)
    (stray / "stray.hpd").write_bytes(tn.demo_hpd())
    trees = nd.extract_trees(str(out))
    assert sorted(os.path.basename(t) for t in trees) == ["extracted", "files"]
    assert [e["level"] for e in nd.find_inputs(trees)] == ["Demo"]
    assert sorted(e["level"] for e in nd.find_inputs(str(out))) == ["Demo", "x"]
    bare = tmp_path / "bare"
    bare.mkdir()
    assert nd.extract_trees(str(bare)) == [str(bare)]  # a plain folder is walked itself
    assert nd.export(str(bare), str(tmp_path / "o")) == [] and not (tmp_path / "o").exists()


# node ids of the level fixture
SCENE, SCENES, LVL, HOST_A, HOST_B, PO, V1, V2, LONE = (
    0x10,
    0x11,
    0x12,
    0x20,
    0x21,
    0x30,
    0x31,
    0x32,
    0x40,
)


@pytest.fixture
def nav_level(tmp_path):
    """A level `Demo` with one door template instanced twice and a path-object node
    without vertex nodes, next to the navigation files of test_nav_data: path
    object 1 of the .hpd is carried by the edges between the file-space vertices
    (5, 1, 0.5) and (5, 1, 3.5) = engine (-5, 1, 0.5) and (-5, 1, 3.5)."""
    base = tmp_path / "extracted"
    scene = tl._node(SCENE, "SceneNode", "", None)
    scene += tl._node(SCENES, "Folder", "Scenes", SCENE)
    scene += tl._node(
        LVL,
        "SceneScope(LoadBlock)",
        "Demo",
        SCENES,
        1,
        localPos=[0.0, 0.0, 0.0],
        localOrient=tl.ID,
        assetName="/Levels/Game_Levels_Part2/Demo/Demo.fragment",
        m_isceneid=9,
    )
    tl._write(base / "Levels" / "Game_Levels_Part2" / "Demo.scene", tl._fragment(scene))
    door = "/LevelDesign/Door.fragment"
    lvl = tl._node(
        HOST_A, "FragmentNode", "door near", "host", 0, localPos=[-5.0, 0.0, 2.0],
        localOrient=tl.ID, assetName=door,
    )  # fmt: skip
    lvl += tl._node(
        HOST_B, "FragmentNode", "door far", "host", 1, localPos=[40.0, 0.0, 40.0],
        localOrient=tl.ID, assetName=door,
    )  # fmt: skip
    lvl += tl._node(
        LONE, "AIStaticPathObjectNode", "no vertices", "host", 2, localPos=[-5.0, 1.0, 2.0],
        localOrient=tl.ID,
    )  # fmt: skip
    tl._write(base / "Levels" / "Game_Levels_Part2" / "Demo" / "Demo.fragment", tl._fragment(lvl))
    d = tl._node(
        PO, "KynapseDoor(AIStaticPathObjectNode)", "", "host", 0, localPos=[0.0, 0.0, 0.0],
        localOrient=tl.ID, impassable=True, canLeave=True, canBypass=False,
    )  # fmt: skip
    for nid, z in ((V1, -1.5), (V2, 1.5)):
        d += tl._node(
            nid, "AIStaticPathObjectVertexNode", "", PO, nid, localPos=[0.0, 1.0, z],
            localOrient=tl.ID,
        )  # fmt: skip
    tl._write(base / "LevelDesign" / "Door.fragment", tl._fragment(d))
    _nav_files(tmp_path)
    return tmp_path


def test_level_lists_its_path_objects_and_links_the_path_data(nav_level):
    ((scene, name, sid, _asset),) = lm.levels(str(nav_level))
    j = lm.build_level(scene, name, sid, str(nav_level))
    pos = j["path_objects"]
    assert [p["name"] for p in pos] == ["", "", "no vertices"] and len(set(p["uid"] for p in pos))
    near, far, lone = pos
    assert near["class"] == "KynapseDoor" and near["native"] == "AIStaticPathObjectNode"
    assert near["fragment"] == "/LevelDesign/Door.fragment" and near["enabled"] is True
    assert (near["impassable"], near["can_leave"], near["can_bypass"]) == (True, True, False)
    assert [v["pos"] for v in near["vertices"]] == [[-5.0, 1.0, 0.5], [-5.0, 1.0, 3.5]]
    assert [v["pos"] for v in far["vertices"]] == [[40.0, 1.0, 38.5], [40.0, 1.0, 41.5]]
    assert near["world"]["pos"] == [-5.0, 0.0, 2.0] and lone["vertices"] == []
    # the join: by position, onto the near door only
    assert near["nav"] == {
        "index": 1,
        "id": 1,
        "method": "position",
        "distance_m": 0.0,
        "edges": [[1000, 2], [1000, 3]],
    }
    assert far["nav"] is None and lone["nav"] is None
    nav = j["nav"]
    assert nav["source"] == "demoaipath.hpd" and nav["path_objects"] == 1 and nav["linked"] == 1
    assert nav["unlinked"] == [] and nav["max_distance_m"] == 0.0
    assert "1 m" in nav["vertical_offset"]
    assert j["counts"]["path_objects"] == 3 and j["counts"]["path_objects_linked"] == 1
    assert "path_objects" in j["evidence"]
    json.dumps(j)


def test_level_without_path_data_keeps_its_path_objects_unlinked(nav_level):
    import shutil

    shutil.rmtree(str(nav_level / "files"))
    ((scene, name, sid, _asset),) = lm.levels(str(nav_level))
    j = lm.build_level(scene, name, sid, str(nav_level))
    assert len(j["path_objects"]) == 3 and j["nav"] is None
    assert [p["nav"] for p in j["path_objects"]] == [None] * 3
    assert j["counts"]["path_objects_linked"] == 0


def test_link_nav_is_one_to_one_and_bounded():
    def node(uid, *pts):
        return {"uid": uid, "vertices": [{"uid": uid + "v", "pos": list(p)} for p in pts]}

    def po(index, a, b):
        return {
            "index": index,
            "id": index + 10,
            "edges": [{"cell": 7, "edge": index, "from": a, "to": b}],
        }

    level = {
        "path_objects": [
            node("a", (0, 1, 0), (0, 1, 2)),
            node("b", (10, 1, 0), (10, 1, 2)),
            node("c"),
        ]
    }
    nav = [
        po(1, [10.0, 1.0, 0.1], [10.0, 1.0, 2.0]),  # 0.1 m from b
        po(2, [0.0, 1.0, 0.0], [0.0, 1.0, 2.0]),  # exactly a
        po(3, [0.2, 1.0, 0.0], [0.0, 1.0, 2.0]),  # a again, 0.2 m: a is taken by the nearer one
        po(4, [50.0, 1.0, 0.0], [50.0, 1.0, 2.0]),  # nothing within the tolerance
        {"index": 5, "id": 15, "edges": []},  # carried by no edge
        po(6, [0.0, 1.0, 0.0], [10.0, 1.0, 2.0]),  # one end at a, one at b: no single node
    ]
    s = lm.link_nav(level, nav, source="x.hpd")
    a, b, c = level["path_objects"]
    assert a["nav"]["index"] == 2 and a["nav"]["id"] == 12 and a["nav"]["distance_m"] == 0.0
    assert b["nav"]["index"] == 1 and b["nav"]["distance_m"] == 0.1 and c["nav"] is None
    assert s["linked"] == 2 and s["unlinked"] == [3, 4, 5, 6] and s["max_distance_m"] == 0.1
    assert level["counts"]["path_objects_linked"] == 2
    # a second run starts from scratch
    lm.link_nav(level, nav[3:], source="x.hpd")
    assert [p["nav"] for p in level["path_objects"]] == [None, None, None]
