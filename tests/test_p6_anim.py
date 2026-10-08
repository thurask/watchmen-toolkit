"""Final sweep, animation and characters: the baker's pose rule, the clip table's loop
flag, the SoundEvents lists in the state events, the contact check, the face step
failing, and the two cache rules.

    A17   a type-1 / 3 constant position is added to the rest local position of a
          non-root bone; a root's rest position is 0 (0x594d38, 0x593685)
    A18   clips[].loop is set by any looping state that plays the clip
    A33   the events of a state's SE_<clip>.fragment list are the state's events
    A23   the EN3 skeleton key, and every bind before the animation table
    V11   a failed face step leaves a marker and no half-written records
    A41   a jiggle memo older than its raw bake is baked again

Synthetic fixtures only."""

import inspect
import json
import os
import struct
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import bake_v4
import characters_export as ce
import face_rule

import test_anim_meta as ta
import test_combat_meta
from conftest import build_clip_header

combat_extract = test_combat_meta.extract
extract = ta.extract


# ------------------------------------------------------------------ the baker
def _clip(tracks, keys=1):
    """tracks: [(name, type, payload)] -- type 3: (pos, quat); type 1: (pos, [quat keys]);
    type 2: [(pos, quat) keys]; type 0: (quat, [pos keys])."""
    b = bytearray(build_clip_header(keys, 1.0))
    b += struct.pack("<I", len(tracks))
    for nm, _t, _p in tracks:
        raw = nm.encode() + b"\0"
        b += struct.pack("<I", len(raw)) + raw
    for _nm, t, p in tracks:
        b += bytes([t])
        if t == 3:
            b += struct.pack("<3f", *p[0]) + b"\0\0\0\0" + struct.pack("<4f", *p[1])
        elif t == 1:
            b += struct.pack("<H", len(p[1])) + struct.pack("<3f", *p[0])
            for q in p[1]:
                b += struct.pack("<4h", *[int(round(v * 10000)) for v in q])
        elif t == 2:
            b += struct.pack("<H", len(p))
            for pos, q in p:
                b += struct.pack("<3h", *[int(round(v * 1000)) for v in pos])
                b += struct.pack("<4h", *[int(round(v * 10000)) for v in q])
        else:
            b += struct.pack("<H", len(p[1])) + struct.pack("<4f", *p[0])
            for pos in p[1]:
                b += struct.pack("<3h", *[int(round(v * 1000)) for v in pos])
    return bytes(b)


I4 = (0.0, 0.0, 0.0, 1.0)


@pytest.fixture
def bind(tmp_path):
    """Bip (a root, bind position 0.5 up), a hand under it and an attach point under
    the hand; GamePivot, a second root at the origin."""
    p = tmp_path / "bind_t_file_v1.npz"
    tb = np.array([[0, 0.5, 0], [1, 0.5, 0], [1.25, 0.5, 0], [0, 0, 0]], float)
    np.savez(
        p,
        Rb=np.tile(np.eye(3), (4, 1, 1)),
        tb=tb,
        tloc=np.array([[0, 0.5, 0], [1, 0, 0], [0.25, 0, 0], [0, 0, 0]], float),
        par=np.array([-1, 0, 1, -1]),
        names=np.array(["Bip", "Hand", "Attach RHand", "GamePivot"]),
    )
    return str(p), tb


def _world(pal, tb):
    return np.einsum("fkab,kb->fka", pal[..., :3], tb) + pal[..., 3]


def test_walk_reports_the_track_types():
    clip = _clip(
        [("Bip", 3, ((0, 0, 0), I4)), ("Hand", 1, ((0, 0, 0), [I4])), ("X", 2, [((1, 0, 0), I4)])]
    )
    types = {}
    tr = bake_v4.walk(clip, types=types)
    assert types == {"Bip": 3, "Hand": 1, "X": 2}
    assert tr["Bip"][1] is None and tr["X"][1].shape == (1, 3)  # a one-key track looks constant
    assert bake_v4.walk(clip).keys() == tr.keys()  # the argument is optional


def test_a_constant_on_a_non_root_bone_is_added_to_its_rest_local_position(bind):
    path, tb = bind
    clip = _clip(
        [
            ("Bip", 2, [((0, 0.5, 0), I4)]),
            ("Hand", 3, ((0, 0, 0), I4)),  # zero constant: the rest local position
            ("Attach RHand", 3, ((0.1, 0.2, 0.0), I4)),
            ("GamePivot", 3, ((0, 1, 0), I4)),
        ]
    )
    pal, _ = bake_v4.bake("c", 1, bind=path, bank={"c": clip})
    w = _world(pal, tb)[0]
    assert w[1] == pytest.approx([1.0, 0.5, 0.0])
    # engine: rest local (0.25, 0, 0) + constant (0.1, 0.2, 0), not the constant alone
    assert w[2] == pytest.approx([1.35, 0.7, 0.0])
    assert w[3] == pytest.approx([0.0, 1.0, 0.0])  # a root's constant is absolute


def test_a_one_key_keyed_track_stays_absolute(bind):
    path, tb = bind
    clip = _clip(
        [
            ("Bip", 2, [((0, 0.5, 0), I4)]),
            ("Hand", 3, ((0, 0, 0), I4)),
            ("Attach RHand", 2, [((0.1, 0.2, 0.0), I4)]),  # type 2: no rest pose added
        ]
    )
    pal, _ = bake_v4.bake("c", 1, bind=path, bank={"c": clip})
    assert _world(pal, tb)[0][2] == pytest.approx([1.1, 0.7, 0.0])


@pytest.mark.parametrize("tracked", [True, False])
def test_a_root_without_position_keys_sits_at_zero_not_at_its_bind_position(bind, tracked):
    path, tb = bind
    tracks = [("Hand", 3, ((0, 0, 0), I4))]
    if tracked:
        tracks.insert(0, ("Bip", 3, ((0, 0, 0), I4)))  # zero constant
    clip = _clip(tracks)
    pal, _ = bake_v4.bake("c", 1, bind=path, bank={"c": clip})
    w = _world(pal, tb)[0]
    assert w[0] == pytest.approx([0.0, 0.0, 0.0])  # the bind has Bip at (0, 0.5, 0)
    assert w[1] == pytest.approx([1.0, 0.0, 0.0])  # and the body follows
    # a head model's own node list: its roots are not the character's
    pal, _ = bake_v4.bake("c", 1, bind=path, bank={"c": clip}, root_rest="bind")
    assert _world(pal, tb)[0][0] == pytest.approx([0.0, 0.5, 0.0])
    with pytest.raises(ValueError, match="root_rest"):
        bake_v4.bake("c", 1, bind=path, bank={"c": clip}, root_rest="nope")


def test_the_face_bakes_keep_their_roots_at_the_bind_position():
    import face_export

    assert 'root_rest="bind"' in inspect.getsource(face_export.export)
    assert 'root_rest="bind"' in inspect.getsource(ce._face_attach)
    assert "root_rest" not in inspect.getsource(ce.bake_cache)  # body clips: the engine rule


def test_a_cached_bake_of_another_pose_rule_is_baked_again(tmp_path, bind, monkeypatch):
    path, _tb = bind
    old = tmp_path / "old.npz"
    np.savez(old, pal=np.zeros((1, 4, 3, 4), np.float32), dur=np.float32(1), fps=np.float32(30))
    assert not ce.bake_is_current(str(old))  # written before the rule was stored
    new = tmp_path / "new.npz"
    np.savez(new, pal=np.zeros((1, 4, 3, 4), np.float32), rule=np.int32(bake_v4.POSE_RULE))
    assert ce.bake_is_current(str(new))
    other = tmp_path / "other.npz"
    np.savez(other, pal=np.zeros((1, 4, 3, 4), np.float32), rule=np.int32(bake_v4.POSE_RULE + 1))
    assert not ce.bake_is_current(str(other))
    (tmp_path / "torn.npz").write_bytes(b"not a zip")
    assert not ce.bake_is_current(str(tmp_path / "torn.npz"))

    # bake_cache: the stale file is replaced, the current one is kept
    ex, out = tmp_path / "ex", tmp_path / "out"
    d = ex / "extracted" / "Animation" / "T"
    d.mkdir(parents=True)
    clip = _clip([("Bip", 2, [((0, 0.5, 0), I4), ((0, 0.6, 0), I4)])], keys=2)
    (d / "T_a.animation").write_bytes(clip)
    (d / "T_b.animation").write_bytes(clip)
    monkeypatch.setitem(ce.CLIP_PREFIX, "t", ("T",))
    cdir = out / "_bake" / "t"
    cdir.mkdir(parents=True)
    np.savez(cdir / "T_a.npz", pal=np.full((2, 4, 3, 4), 7, np.float32), dur=np.float32(1))
    done, todo = ce.bake_cache("t", path, str(ex), str(out))
    assert (done, todo) == (2, 0)
    za = np.load(cdir / "T_a.npz")
    assert int(za["rule"]) == bake_v4.POSE_RULE and not (za["pal"] == 7).any()
    stamp = os.path.getmtime(cdir / "T_b.npz")
    os.utime(cdir / "T_b.npz", (stamp - 100, stamp - 100))
    assert ce.bake_cache("t", path, str(ex), str(out)) == (2, 0)
    assert os.path.getmtime(cdir / "T_b.npz") == pytest.approx(stamp - 100)  # not rewritten


def test_a_jiggle_memo_older_than_its_raw_bake_is_not_read(tmp_path):
    raw, memo = tmp_path / "c.npz", tmp_path / "m.npz"
    np.savez(raw, pal=np.zeros((2, 1, 3, 4), np.float32))
    np.savez(memo, pal=np.zeros((2, 1, 3, 4), np.float32), fps=np.float32(30))
    t = os.path.getmtime(raw)
    os.utime(memo, (t - 10, t - 10))
    assert not ce.jiggle_memo_is_current(str(memo), str(raw), "c", 30.0)
    os.utime(memo, (t + 10, t + 10))
    assert ce.jiggle_memo_is_current(str(memo), str(raw), "c", 30.0)
    assert "jiggle_memo_is_current(jf, f, nm, fps)" in inspect.getsource(ce.export)


# ------------------------------------------------------------ the clip table
def test_a_blend_member_of_a_looping_state_loops(tmp_path):
    h = ta.Frag()
    g = h.add("AnimationStateGroupWM", "Move")
    s = h.add("AnimationStateWM", "Run", g, m_tislooping=True)
    layers = h.add("Folder", "Layers", s)
    b = h.add("AnimationBlendWM", "{MOTION_LAYER_1}", layers, m_nweight=1.0)
    for clip in (
        "RSH_COM_MOV_run_cycle",
        "RSH_COM_WPN_1H_right_arm_layer",
        "RSH_COM_ATT_dash_cycle",
    ):
        h.add("AnimationSlotWM", "{%s.animation}" % clip, b, m_nweight=1.0)
    h.state("Kick", g, "RSH_COM_ATT_kick", m_tislooping=False)
    h.write(tmp_path, "Rorschach")
    for clip in ("RSH_COM_MOV_run_cycle", "RSH_COM_ATT_dash_cycle", "RSH_COM_ATT_kick"):
        ta.write_clip(tmp_path, clip, ((0, 1, 0), (0, 1, 1)))
    m = am.build(str(tmp_path))
    (run,) = [x for x in m["classes"]["Rorschach"]["states"] if x["name"] == "Run"]
    assert run["main_clip"] == "RSH_COM_ATT_dash_cycle" and run["loop"] is True
    assert m["clips"]["RSH_COM_ATT_dash_cycle"]["loop"] is True
    assert m["clips"]["RSH_COM_MOV_run_cycle"]["loop"] is True  # a blend member, not the main clip
    assert m["clips"]["RSH_COM_WPN_1H_right_arm_layer"]["loop"] is False  # a partial-body overlay
    assert m["clips"]["RSH_COM_ATT_kick"]["loop"] is False
    assert m["revision"] == am.REVISION == 5


SE = "TNT/CharacterAnimation/SoundEvents/SE_RSH_COM_ATT_kick.fragment"


def _class_with_event_list(tmp_path, write_list=True):
    h = ta.Frag()
    g = h.add("AnimationStateGroupWM", "Attacks")
    s = h.state("Kick", g, "RSH_COM_ATT_kick", events=[("IMPACT", 0.5)], m_tislooping=False)
    ev = next(n["id"] for n in h.nodes if ["name", "string", "Events"] in n["props"])
    h.add("FragmentNode", "", ev, assetName="/" + SE)
    h.add("FragmentNode", "", s, assetName="/TNT/CharacterAnimation/SoundEvents/SE_gone.fragment")
    h.write(tmp_path, "Rorschach")
    ta.write_clip(tmp_path, "RSH_COM_ATT_kick", ((0, 1, 0), (0, 1, 1)))
    if write_list:
        e = ta.Frag()
        for eid, pos in ((40, 0.25), (9, 0.75)):  # RIGHT_FOOT_DOWN, SOUND
            e.add(
                "AnimationEventWM",
                "",
                m_nplaypos=pos,
                m_ieventtype=0,
                m_ianimationevent=eid,
                m_nvalue=0.0,
            )
        f = tmp_path / "extracted" / (SE + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"instances": [e.cls], "nodes_full": e.nodes}))


def test_the_events_of_a_sound_event_list_are_the_states_events(tmp_path):
    _class_with_event_list(tmp_path)
    said = []
    m = am.build(str(tmp_path), log=said.append)
    cls = m["classes"]["Rorschach"]
    (kick,) = cls["states"]
    ev = [(e["name"], e["playpos"], e.get("source")) for e in kick["events"]]
    assert ev == [
        ("RIGHT_FOOT_DOWN", 0.25, "SE_RSH_COM_ATT_kick.fragment"),
        ("IMPACT", 0.5, None),
        ("SOUND", 0.75, "SE_RSH_COM_ATT_kick.fragment"),
    ]
    assert "source" not in kick["events"][1]  # an event of the class tree has no such key
    assert kick["events"][0]["time_s"] == pytest.approx(0.5)  # timed like every other event
    # the clip table and the clip extras carry them too
    assert [e["name"] for e in m["clips"]["RSH_COM_ATT_kick"]["events"]] == [x[0] for x in ev]
    # the list the data does not contain is named, not silently dropped
    assert cls["missing_event_lists"] == ["/TNT/CharacterAnimation/SoundEvents/SE_gone.fragment"]
    assert any("event-list fragments not found" in x and "SE_gone" in x for x in said)


def test_an_event_list_that_exists_but_is_empty_is_not_missing(tmp_path):
    _class_with_event_list(tmp_path)
    f = tmp_path / "extracted" / "TNT/CharacterAnimation/SoundEvents/SE_gone.fragment.json"
    f.write_text(json.dumps({"instances": [], "nodes_full": []}))  # as the 17-byte lists
    m = am.build(str(tmp_path))
    assert "missing_event_lists" not in m["classes"]["Rorschach"]
    assert len(m["classes"]["Rorschach"]["states"][0]["events"]) == 3


def test_a_class_without_missing_lists_has_no_such_key(extract):
    m = am.build(str(extract))
    assert all("missing_event_lists" not in c for c in m["classes"].values())
    assert all(
        "source" not in e for c in m["classes"].values() for s in c["states"] for e in s["events"]
    )


def test_sound_meta_counts_a_spliced_list_once(tmp_path):
    import anim_state_machine as asm
    import sound_meta

    _class_with_event_list(tmp_path)
    classes = am.load_classes(str(tmp_path))
    (state,) = [n for n in classes["Rorschach"]["nodes"] if n.cls == asm.CLS_STATE]
    db = sound_meta.SoundDB(str(tmp_path))
    rows = sound_meta._fragment_events(db, state)
    assert sorted((e.p("m_ianimationevent"), src) for e, _rel, src in rows) == [
        (4, "state"),
        (9, "SE_RSH_COM_ATT_kick.fragment"),
        (40, "SE_RSH_COM_ATT_kick.fragment"),
    ]
    assert {rel for _e, rel, src in rows if src != "state"} == {SE}


# ---------------------------------------------------------- the contact check
def test_contact_check_knows_the_part_1_en3_skeleton_and_says_what_is_missing(tmp_path):
    assert am._ContactCheck._KEY["EN3"] == "small" and ce.CLIP_PREFIX_P1["small"] == ("EN1", "EN3")
    cc = am._ContactCheck(str(tmp_path))
    with pytest.raises(OSError, match="bind_small_file_v1.npz is not in"):
        cc._load(str(tmp_path / "EN3_COM_ATT_x.animation"))
    with pytest.raises(KeyError, match="no skeleton is known for clip prefix XX9"):
        cc._load(str(tmp_path / "XX9_clip.animation"))


def test_every_bind_is_built_before_the_animation_table(monkeypatch):
    src = inspect.getsource(ce.export)
    assert src.index("ensure_all_binds(") < src.index("meta = animation_meta(extract_out, outdir)")
    built = []

    def ensure(key, extract_out, naz):
        if key == "bad":
            raise RuntimeError("no skeleton")
        built.append((key, extract_out, naz))

    monkeypatch.setattr(ce, "ensure_bind", ensure)
    failed = ce.ensure_all_binds({"rsh", "bs2", "bad"}, "EX", "g.naz")
    assert built == [("bs2", "EX", "g.naz"), ("rsh", "EX", "g.naz")]
    assert failed == {"bad": "RuntimeError: no skeleton"}


def test_pairs_without_a_contact_check_are_counted():
    m = {
        "pairs": [
            {"placement": {"check": {"contact": {"closest_m": 0.1}}}},
            {"placement": {"check": {"agreement_m": 0.0}}},
            {"placement": None},
            {"placement": {}},
        ]
    }
    assert ce.pairs_without_contact_check(m) == [1]
    assert ce.pairs_without_contact_check(None) == []


# ------------------------------------------------------- the face step fails
def test_a_failed_face_step_leaves_a_marker_and_no_partial_records(
    combat_extract, monkeypatch, tmp_path
):
    def boom(extract_out, classes, states, pairs, am_mod, log):
        for recs in states.values():  # what the real step writes before it can raise
            for _node, rec in recs:
                rec["face"] = {"half": True}
                rec["inflicts"] = [1]
        for p in pairs:
            p["face"] = {"half": True}
        raise KeyError("m_broken")

    monkeypatch.setattr(face_rule, "build", boom)
    monkeypatch.setattr(face_rule, "find_face_fragments", lambda ex: {"Face": "x"})
    said = []
    m = am.build(str(combat_extract), log=said.append)
    assert "face_format" not in m and "face" not in m
    assert m[am.BUILD_FAILED_KEY]["face"] == {
        "format": face_rule.FACE_FORMAT,
        "status": "attempted, failed",
        "reason": "KeyError: 'm_broken'",
    }
    states = [s for c in m["classes"].values() for s in c["states"]]
    assert states and not any("face" in s or "inflicts" in s for s in states)
    assert not any("face" in p for p in m["pairs"])
    assert m["combat_format"] and m["fx_format"]  # the other blocks are built
    assert any("face: skipped (KeyError: 'm_broken')" in x for x in said)
    json.dumps(m)

    # a resumed export reuses the table instead of building it on every run
    assert ce.anim_meta_is_current(m, str(combat_extract))
    out = tmp_path / "chars"
    out.mkdir()
    (out / "anim_meta.json").write_text(json.dumps(m))
    monkeypatch.setattr(am, "build", lambda *a, **k: pytest.fail("rebuilt"))
    assert ce.animation_meta(str(combat_extract), str(out))[am.BUILD_FAILED_KEY]["face"]
    # ... but not one whose failure was recorded for another face format
    m[am.BUILD_FAILED_KEY]["face"]["format"] = "watchmen-face/0"
    assert not ce.anim_meta_is_current(m, str(combat_extract))
