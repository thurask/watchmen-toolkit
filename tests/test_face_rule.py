"""The face rule: which face pose the game shows during which body animation.

Synthetic trees and tables only.  The fixtures mirror the shipped face classes
(AnimationClassEnemy01Face and friends, read 2026-10-03): an Alive group whose
"Active" child is re-entered every silent frame (ACTION STOP_SPEAK), a random
Idles group left by PLAY_TIME transitions back into itself, and a HitResponse
group gated by ACTION HITTAKEN whose members test the DAMAGE_POSE enum.
"""

import json
import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_state_machine as asm
import face_rule as fr
import face_synth as fs
import variant_glb as vg

from conftest import parse_glb

_n = [0]


# ------------------------------------------------------------------ builders
def node(cls, name, parent=None, **props):
    _n[0] += 1
    n = asm.Node("f%d" % _n[0], cls, name)
    n.props = dict(props)
    if parent is not None:
        n.parent = parent
        parent.children.append(n)
    return n


def state(parent, name, clip=None, **props):
    s = node(asm.CLS_STATE, name, parent, **props)
    b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
    clip = clip or name
    node(
        asm.CLS_SLOT,
        clip,
        b,
        m_sduration="0.033333 s",
        targetAnimation="Animation/EN1/FACE/%s.animation" % clip,
    )
    return s


def group(parent, name, random=False):
    return node(asm.CLS_GROUP, name, parent, **{asm.RANDOM_STATE: random})


def trans(owner, target, **props):
    return node(asm.CLS_TRANS, "{trans}", owner, m_etostate={"ref": target.id}, **props)


def crit(owner, kind, **props):
    return node(asm.CLS_CRIT, "{crit}", owner, m_ianimationcriteria=kind, **props)


def play_time_at_least(owner, seconds):
    return crit(owner, asm.CRIT_PLAY_TIME, m_iintervaltype=2, m_nintervalmin=seconds)


def action(owner, ident):
    return crit(owner, asm.CRIT_ACTION, m_ianimationaction=ident)


def pose_is(owner, pose):
    return crit(owner, asm.CRIT_ENUM, m_ianimationenum=fr.E_DAMAGE_POSE, m_ianimationenumvalue=pose)


class StubRng:
    """random.Random stand-in that hands out a scripted sequence."""

    def __init__(self, picks):
        self.picks = list(picks)

    def randrange(self, n):
        return self.picks.pop(0) % n

    def random(self):
        return 0.0


def face_class():
    """The shape of a shipped face class, cut down to what the rule needs."""
    root = node(asm.CLS_CLASS, "FaceClass")
    alive = group(root, "Alive")
    active = group(alive, "Active", random=True)
    idles = group(active, "Idles", random=True)
    idle_a = state(idles, "IdleA", "MouthClosed_EyesOpen", m_neaseinduration=0.21)
    idle_b = state(idles, "IdleB", "MouthClosed_EyesClosed", m_neaseinduration=0.21)
    play_time_at_least(trans(idle_a, idles), 3.0)
    play_time_at_least(trans(idle_b, idles), 0.5)
    hit = group(active, "HitResponse")
    action(hit, fr.A_HITTAKEN).props["m_tentryonly"] = True
    left = state(hit, "HitLeft", "DamageL", m_neaseinduration=0.21)
    pose_is(left, 1).props["m_tentryonly"] = True
    low = state(hit, "HitLow", "DamageBalls", m_neaseinduration=0.21)
    play_time_at_least(trans(hit, idles), 0.75)
    trans(idles, hit)
    trans(hit, hit)
    action(trans(alive, active), fr.A_STOP_SPEAK)
    root.props["m_edefaultanimstate"] = {"ref": idles.id}
    return root, dict(idle_a=idle_a, idle_b=idle_b, left=left, low=low, idles=idles, hit=hit)


# ------------------------------------------------- interpreter: state choice
def test_group_scan_starts_at_the_first_member_every_time():
    """command_get_valid_state 0x5f076f scans from index 0 (0x5f0792); up to
    1.3.0 the interpreter resumed after the member it returned last (a round
    robin the engine does not have)."""
    root = node(asm.CLS_CLASS, "c")
    g = group(root, "G")
    a = state(g, "A")
    state(g, "B")
    it = asm.Interpreter(root)
    assert it.get_valid_state(g) is a
    assert it.get_valid_state(g) is a
    assert it.get_valid_state(g) is a


def test_random_group_starts_at_a_drawn_member():
    """ "Choose Random State" groups start the scan at a random index
    (0x5f07bb-0x5f07d7); the draw comes from the interpreter's rng."""
    root = node(asm.CLS_CLASS, "c")
    g = group(root, "G", random=True)
    kids = [state(g, n) for n in "ABC"]
    it = asm.Interpreter(root, rng=StubRng([2, 0, 1, 1]))
    assert [it.get_valid_state(g) for _ in range(4)] == [kids[2], kids[0], kids[1], kids[1]]


def test_random_start_still_scans_cyclically_past_failing_members():
    root = node(asm.CLS_CLASS, "c")
    g = group(root, "G", random=True)
    a = state(g, "A")
    b = state(g, "B")
    action(b, 99)  # never fired
    it = asm.Interpreter(root, rng=StubRng([1]))
    assert it.get_valid_state(g) is a


def test_random_choice_is_reproducible_from_the_seed():
    root = node(asm.CLS_CLASS, "c")
    g = group(root, "G", random=True)
    for n in "ABCDE":
        state(g, n)

    def picks(seed):
        it = asm.Interpreter(root, seed=seed)
        return [it.get_valid_state(g).name for _ in range(40)]

    assert picks(5) == picks(5)
    assert picks(5) != picks(6)
    assert set(picks(5)) == set("ABCDE")  # every member is reachable


def test_members_tested_in_one_evaluation_are_not_tried_again():
    """The idle state's own transition names the Idles group, so the group is in
    the evaluation's tested list (_etestedstates) when the Alive group's
    every-frame transition re-enters Active: Idles is skipped there and the idle
    state is NOT re-rolled each frame.  The interpreter of 1.3.0 re-rolled it
    (a face class run through it flickered between open and closed eyes)."""
    root, n = face_class()
    it = asm.Interpreter(root, rng=StubRng([0] * 50))
    it.transit(n["idle_a"])
    it.env.actions = {fr.A_STOP_SPEAK}
    assert it.get_valid_transition(n["idle_a"]) is None
    for _ in range(30):  # one second of silent frames: still the same idle state
        it.env.actions = {fr.A_STOP_SPEAK}
        it.env.force_update = True
        it.tick(fr.DT)
    assert it.page.state is n["idle_a"]


def test_tested_list_does_not_outlive_the_evaluation():
    root, n = face_class()
    it = asm.Interpreter(root, rng=StubRng([0] * 9))
    it.transit(n["idle_a"])
    it.get_valid_transition(n["idle_a"])
    assert it._tested is None
    assert it.get_valid_state(n["idles"]) is n["idle_a"]  # a plain call sees every member


# ------------------------------------------------------------ face simulation
def test_idle_face_stays_idle_and_is_one_segment():
    root, _ = face_class()
    segs = fr.simulate(root, 10.0, seed=3)
    assert [s["face_state"] for s in segs] == [fr.IDLE]
    assert segs[0]["from_s"] == 0.0 and segs[0]["to_s"] is None


def test_hit_selects_the_state_of_its_damage_pose_and_leaves_after_the_hold():
    root, _ = face_class()
    segs = fr.simulate(root, 4.0, inputs=[(1.0, "HIT", 1)], seed=3)
    assert [s["face_state"] for s in segs] == [fr.IDLE, "HitLeft", fr.IDLE]
    hit = segs[1]
    assert hit["clips"] == ["DamageL"] and hit["ease_in_s"] == 0.21
    assert abs(hit["from_s"] - 1.0) <= 2 * fr.DT
    # PLAY_TIME >= 0.75 on the HitResponse group, tested once per frame
    assert 0.75 <= hit["to_s"] - hit["from_s"] <= 0.75 + 3 * fr.DT


def test_hit_with_an_unlisted_pose_falls_to_the_member_without_criteria():
    root, _ = face_class()
    segs = fr.simulate(root, 2.0, inputs=[(0.5, "HIT", 7)], seed=3)
    assert segs[1]["face_state"] == "HitLow" and segs[1]["clips"] == ["DamageBalls"]


def test_second_hit_restarts_the_hit_response():
    root, _ = face_class()
    segs = fr.simulate(root, 4.0, inputs=[(1.0, "HIT", 1), (1.4, "HIT", 0)], seed=3)
    names = [s["face_state"] for s in segs]
    assert names == [fr.IDLE, "HitLeft", "HitLow", fr.IDLE]
    assert segs[2]["to_s"] - segs[2]["from_s"] >= 0.75


def test_hit_hold_is_read_from_the_group_exit():
    root, _ = face_class()
    assert fr._hit_hold(list(asm.walk([root]))) == 0.75


# ----------------------------------------------------------- baking: tracks
def seg(a, b, name, clips=None, **kw):
    d = {"from_s": a, "to_s": b, "face_state": name}
    if clips:
        d.update(clips=clips, ease_in_s=0.21)
    d.update(kw)
    return d


FCLASS = {
    "pose_family": "EN1",
    "idle_cycle": {
        "states": [
            {"name": "IdleA", "clips": ["Open"], "min_s": 3.0, "ease_in_s": 0.21},
            {"name": "IdleB", "clips": ["Closed"], "min_s": 0.5, "ease_in_s": 0.21},
        ]
    },
    "states": [
        {"name": "IdleA", "kind": "IDLE", "glb_animation_names": ["FACE EN1/Open"]},
        {"name": "HitLeft", "kind": "HitLeft", "glb_animation_names": ["FACE EN1/DamageL"]},
    ],
}


def meta_with(states, clips, pairs=()):
    return {
        "classes": {"Body": {"states": states}},
        "clips": clips,
        "pairs": list(pairs),
        "face": {"classes": {"FaceEN1": FCLASS, "FaceNTO": dict(FCLASS, pose_family="NTO")}},
    }


def body_state(name, clip, track, conf="high", fclass="FaceEN1", **kw):
    d = {
        "name": name,
        "path": "Body/" + name,
        "main_clip": clip,
        "clips": [{"clip": clip, "layer": "MOTION_LAYER_1"}],
        "duration_s": 2.0,
        "speed": 1.0,
        "start_playpos": 0.0,
        "face": {"class": fclass, "track": track, "confidence": conf},
    }
    d.update(kw)
    return d


def used(name, main=True, speed=1.0):
    return {"class": "Body", "state": name, "path": "Body/" + name, "main": main, "speed": speed}


IDLE_TRACK = [seg(0.0, None, "IDLE")]
HIT_TRACK = [seg(0.0, 0.5, "IDLE"), seg(0.5, 1.25, "HitLeft", ["DamageL"]), seg(1.25, None, "IDLE")]


def test_choose_track_takes_the_track_most_states_share():
    other = [seg(0.0, None, "Attack", ["Attack1"])]
    meta = meta_with(
        [
            body_state("A", "clip", other),
            body_state("B", "clip", HIT_TRACK),
            body_state("C", "clip", HIT_TRACK),
        ],
        {"clip": {"used_by": [used("A"), used("B"), used("C")], "pairs": [], "duration_s": 2.0}},
    )
    c = fr.choose_track(meta, "clip", "EN1")
    assert c["track"] == HIT_TRACK
    assert c["candidates"] == 3 and c["distinct_tracks"] == 2
    assert c["source"]["state"] == "B" and c["source"]["class_face"] == "FaceEN1"
    assert c["playpos_per_second"] == 0.5


def test_choose_track_ties_prefer_a_track_with_an_event_then_confidence():
    meta = meta_with(
        [body_state("A", "clip", IDLE_TRACK), body_state("B", "clip", HIT_TRACK, conf="medium")],
        {"clip": {"used_by": [used("A"), used("B")], "pairs": [], "duration_s": 2.0}},
    )
    assert fr.choose_track(meta, "clip", "EN1")["source"]["state"] == "B"
    a2 = [seg(0.0, None, "Attack", ["Attack1"])]
    meta = meta_with(
        [body_state("A", "clip", a2, conf="low"), body_state("B", "clip", HIT_TRACK, conf="high")],
        {"clip": {"used_by": [used("A"), used("B")], "pairs": [], "duration_s": 2.0}},
    )
    assert fr.choose_track(meta, "clip", "EN1")["source"]["state"] == "B"


def test_choose_track_only_sees_face_classes_of_the_heads_pose_family():
    meta = meta_with(
        [body_state("A", "clip", HIT_TRACK, fclass="FaceNTO")],
        {"clip": {"used_by": [used("A")], "pairs": [], "duration_s": 2.0}},
    )
    assert fr.choose_track(meta, "clip", "EN1") is None
    assert fr.choose_track(meta, "clip", "NTO")["source"]["state"] == "A"
    assert fr.choose_track(meta, "CLIP", "NTO") is not None  # clip names: case-insensitive
    assert fr.choose_track(meta, "missing", "NTO") is None
    assert fr.choose_track({}, "clip", "NTO") is None


def test_choose_track_a_primary_pair_replaces_its_states_own_record():
    st = body_state("Victim", "dmg", IDLE_TRACK)
    pair = {
        "primary": True,
        "partner_class": "Body",
        "partner_state": "Victim",
        "partner_path": "Body/Victim",
        "timeline": {"start_playpos": 0.1, "playpos_per_second": 0.25},
        "face": {"partner": {"class": "FaceEN1", "track": HIT_TRACK, "confidence": "high"}},
    }
    meta = meta_with(
        [st],
        {
            "dmg": {
                "used_by": [used("Victim")],
                "pairs": [{"pair": 0, "role": "partner", "other_clip": "att"}],
                "duration_s": 4.0,
            }
        },
        [pair],
    )
    c = fr.choose_track(meta, "dmg", "EN1")
    assert c["track"] == HIT_TRACK and c["candidates"] == 1
    assert c["source"]["pair"] == 0 and c["source"]["role"] == "partner"
    assert c["start_playpos"] == 0.1 and c["playpos_per_second"] == 0.25


def test_choose_track_blend_partner_of_the_main_clip_uses_the_states_track():
    layer = "MOTION_LAYER_1, blend on HAS_2H_WEAPON 0-1"
    st = body_state("Hit", "two_handed", HIT_TRACK)
    st["clips"] = [{"clip": "one_handed", "layer": layer}, {"clip": "two_handed", "layer": layer}]
    lst = body_state("List", "x", HIT_TRACK)
    lst["clips"] = [
        {"clip": "x", "layer": "MOTION_LAYER_1, blend on NONE 0-1"},
        {"clip": "listed", "layer": "MOTION_LAYER_1, blend on NONE 0-1"},
    ]
    meta = meta_with(
        [st, lst],
        {
            "one_handed": {
                "used_by": [used("Hit", main=False, speed=1.5)],
                "pairs": [],
                "duration_s": 3.0,
            },
            "listed": {"used_by": [used("List", main=False)], "pairs": [], "duration_s": 1.0},
        },
    )
    c = fr.choose_track(meta, "one_handed", "EN1")
    assert c["track"] == HIT_TRACK and "two_handed" in c["source"]["slot"]
    assert c["playpos_per_second"] == 0.5  # its own speed / its own length
    assert fr.choose_track(meta, "listed", "EN1") is None  # a clip list, not a blend


# -------------------------------------------------------- baking: schedule
def chosen(track, start=0.0, rate=0.5):
    return {"track": track, "start_playpos": start, "playpos_per_second": rate}


def clip_time(dur):
    return lambda pp: None if pp is None else pp * dur


def test_schedule_keys_the_hit_and_its_exit_with_the_states_ease():
    sched, skipped = fr.pose_schedule(chosen(HIT_TRACK), FCLASS, "c", clip_time(2.0), idle=False)
    assert sched == [(0.0, "Open", 0.0), (0.5, "DamageL", 0.21), (1.25, "Open", 0.21)]
    assert skipped == []


def test_schedule_maps_state_seconds_to_written_time_through_the_play_position():
    # the state enters the clip at 0.25 and plays it at 0.25 / s; the clip is 4 s long
    sched, _ = fr.pose_schedule(
        chosen(HIT_TRACK, start=0.25, rate=0.25), FCLASS, "c", clip_time(4.0), idle=False
    )
    assert [round(t, 4) for t, _p, _e in sched] == [0.0, 1.5, 2.25]


def test_schedule_leaves_non_deterministic_segments_on_the_idle_pose():
    track = [
        seg(0.0, 0.5, "IDLE"),
        seg(0.5, 1.0, "TALK"),
        seg(1.0, 1.5, "HIT_BY_POSE"),
        seg(1.5, None, "HitLeft", ["DamageL"], sound_dependent=True),
    ]
    sched, skipped = fr.pose_schedule(chosen(track), FCLASS, "c", clip_time(2.0), idle=False)
    assert {p for _t, p, _e in sched} == {"Open"}
    assert [s["face_state"] for s in skipped] == ["TALK", "HIT_BY_POSE", "HitLeft"]


def test_schedule_without_idle_states_is_empty():
    assert fr.pose_schedule(
        chosen(HIT_TRACK), {"idle_cycle": {"states": []}}, "c", clip_time(2.0)
    ) == (
        [],
        [],
    )


def test_idle_plan_is_seeded_by_the_clip_name_and_respects_the_minimum_times():
    cyc = FCLASS["idle_cycle"]
    a = fr.idle_plan("clip_a", 0.0, 60.0, cyc)
    assert a == fr.idle_plan("clip_a", 0.0, 60.0, cyc)
    assert a != fr.idle_plan("clip_b", 0.0, 60.0, cyc)
    assert a[0] == (0.0, 0)
    assert [i for _t, i in a] == [k % 2 for k in range(len(a))]
    for (t0, i0), (t1, _i1) in zip(a, a[1:]):
        assert t1 - t0 >= cyc["states"][i0]["min_s"] - 1e-6
    assert all(t < 60.0 for t, _i in a)
    # nothing happens before the first idle state's minimum time
    assert fr.idle_plan("clip_a", 0.0, 2.9, cyc) == [(0.0, 0)]
    # a class with a single idle state (Nite Owl) has no cycle
    assert fr.idle_plan("clip_a", 0.0, 60.0, {"states": cyc["states"][:1]}) == []


def test_idle_cycle_is_switchable_and_never_ends_on_a_half_blink():
    ch = chosen(IDLE_TRACK, rate=None)
    off, _ = fr.pose_schedule(ch, FCLASS, "clip_a", clip_time(1.0), idle=False, duration=60.0)
    assert off == [(0.0, "Open", 0.0)]
    on, _ = fr.pose_schedule(ch, FCLASS, "clip_a", clip_time(1.0), idle=True, duration=60.0)
    assert len(on) > 1 and {p for _t, p, _e in on} == {"Open", "Closed"}
    assert on[-1][1] == "Open" and on[-1][0] + 0.21 <= 60.0
    # a clip shorter than the first idle state's minimum time gets no blink at all
    short, _ = fr.pose_schedule(ch, FCLASS, "clip_a", clip_time(1.0), idle=True, duration=2.5)
    assert short == [(0.0, "Open", 0.0)]
    # cut so that the first closing fits but the re-opening does not: both dropped
    t_close = on[1][0]
    cut, _ = fr.pose_schedule(
        ch, FCLASS, "clip_a", clip_time(1.0), idle=True, duration=t_close + 0.3
    )
    assert cut == [(0.0, "Open", 0.0)]


def test_pose_weights_cross_fade_linearly_over_the_ease():
    sched = [(0.0, "Open", 0.0), (1.0, "Hit", 0.2), (2.0, "Open", 0.2)]
    assert fr.pose_weights(sched, 0.5) == {"Open": 1.0}
    w = fr.pose_weights(sched, 1.1)
    assert abs(w["Open"] - 0.5) < 1e-9 and abs(w["Hit"] - 0.5) < 1e-9
    assert fr.pose_weights(sched, 1.2) == {"Hit": 1.0}
    assert fr.pose_weights(sched, 5.0) == {"Open": 1.0}
    # a hit that arrives while the previous ease is still running stacks on it
    w = fr.pose_weights([(0.0, "A", 0.0), (1.0, "B", 0.2), (1.1, "C", 0.2)], 1.2)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w["C"] - 0.5) < 1e-9 and abs(w["B"] - 0.5) < 1e-9 and "A" not in w
    w = fr.pose_weights([(0.0, "A", 0.0), (1.0, "B", 0.2), (1.1, "C", 0.2)], 1.15)
    assert [round(w[k], 6) for k in "ABC"] == [0.1875, 0.5625, 0.25]


def test_key_times_cover_both_ends_of_every_ease():
    sched = [(0.0, "Open", 0.0), (1.0, "Hit", 0.2), (2.0, "Open", 0.2)]
    assert fr.key_times(sched, 3.0) == [0.0, 1.0, 1.2, 2.0, 2.2, 3.0]
    assert fr.key_times(sched, 2.1)[-1] == 2.1  # clipped to the animation


def test_blend_locals_holds_a_pose_exactly_and_nlerps_two():
    q0 = np.array([[0.0, 0.0, 0.0, 1.0]])
    q1 = -np.array([[0.0, 0.0, np.sin(0.5), np.cos(0.5)]])  # same rotation, other sign
    poses = {"a": (q0, np.zeros((1, 3))), "b": (q1, np.ones((1, 3)))}
    q, t = fs.blend_locals(poses, {"b": 1.0})
    assert np.array_equal(q, q1) and np.array_equal(t, np.ones((1, 3)))
    q, t = fs.blend_locals(poses, {"a": 0.5, "b": 0.5})
    assert abs(np.linalg.norm(q) - 1.0) < 1e-12
    assert np.allclose(np.abs(q[0]), [0.0, 0.0, np.sin(0.25), np.cos(0.25)])
    assert np.allclose(t, 0.5)


def test_pose_extras_name_the_face_states_and_flag_the_toolkit_loops():
    meta = {"face": {"classes": {"FaceEN1": FCLASS}}}
    x = fr.pose_extras(meta, "FACE EN1/DamageL")
    assert x == {
        "synthetic": False,
        "pose": "DamageL",
        "face_states": [{"class": "FaceEN1", "state": "HitLeft", "kind": "HitLeft"}],
    }
    assert fr.pose_extras(meta, "FACE SYNTH Blink")["synthetic"] is True
    assert fr.pose_extras(None, "FACE EN1/Other")["face_states"] == []


# ------------------------------------------------------------- the switches
def test_rule_switch_defaults_to_engine_and_reads_the_environment(monkeypatch):
    monkeypatch.delenv("WATCHMEN_FACE_RULE", raising=False)
    monkeypatch.delenv("WATCHMEN_FACE_IDLE", raising=False)
    assert fr.rule() == "engine" and fr.idle_enabled() is True
    monkeypatch.setenv("WATCHMEN_FACE_RULE", "legacy")
    monkeypatch.setenv("WATCHMEN_FACE_IDLE", "0")
    assert fr.rule() == "legacy" and fr.idle_enabled() is False
    assert fr.rule("engine") == "engine" and fr.idle_enabled(True) is True  # argument wins
    with pytest.raises(ValueError):
        fr.rule("guess")


def test_cli_face_rule_flags(monkeypatch, capsys):
    import watchmen

    monkeypatch.delenv("WATCHMEN_FACE_RULE", raising=False)
    monkeypatch.delenv("WATCHMEN_FACE_IDLE", raising=False)
    assert watchmen.main(["watchmen", "characters", "x", "y", "--face-rule", "guess"]) == 2
    assert "--face-rule takes one of: engine, legacy" in capsys.readouterr().out
    assert watchmen.main(["watchmen", "faces", "x", "y", "--face-rule", "legacy"]) == 2
    assert "apply to: all, characters" in capsys.readouterr().out
    assert "WATCHMEN_FACE_RULE" not in os.environ
    # accepted: the flags are consumed and the command then fails on its arguments
    assert watchmen.main(["watchmen", "characters", "--face-rule", "legacy", "--no-face-idle"]) == 2
    assert os.environ["WATCHMEN_FACE_RULE"] == "legacy" and os.environ["WATCHMEN_FACE_IDLE"] == "0"
    # the command set it: monkeypatch did not record it (it was absent), so drop it here
    os.environ.pop("WATCHMEN_FACE_RULE")
    os.environ.pop("WATCHMEN_FACE_IDLE")


# -------------------------------------------------------------- head models
class Frag:
    """A fragment JSON in the shape anim_state_machine.tree_from_json reads."""

    def __init__(self):
        self.cls, self.nodes, self.n = {}, [], 0

    def add(self, cls, name, parent=None, **props):
        self.n += 1
        nid = "%08x" % self.n
        self.cls["str_" + nid] = [cls + "(Node)"]
        p = [["name", "string", name], ["siblingOrder", "int", self.n]]
        if parent:
            p.append(["logicalParent", "ref", {"ref": parent}])
        p += [[k, "x", v] for k, v in props.items()]
        self.nodes.append({"id": nid, "props": p})
        return nid

    def write(self, root, name):
        d = root / "extracted" / "TNT" / "Production" / "Fragments" / "Enemy"
        d.mkdir(parents=True, exist_ok=True)
        j = {"instances": [self.cls], "nodes_full": self.nodes}
        (d / (name + ".fragment.json")).write_text(json.dumps(j))


def model(name):
    return "/Art/characters/x/models/%s.model" % name


@pytest.fixture
def heads(tmp_path):
    faces = Frag()
    coll = faces.add("CharacterModelCollection", "ThugFace")
    for typ, mdl, tex in (
        (3, "Medium_Head_1", "head"),
        (19, "GimpHead1", "g1"),
        (20, "GimpHead2", "g2"),
    ):
        faces.add(
            "CharacterHeadModel",
            "",
            coll,
            m_iheadmodeltype=typ,
            modelNames=[model(mdl)],
            textureSheetsDescription="2,0,0,0,/art/t/%s.bmp,123,0,0,0,/art/t/Teeth.bmp,456," % tex,
        )
    faces.write(tmp_path, "ThugFace")
    body = Frag()
    coll = body.add("CharacterModelCollection", "Thug", _eheadmodelcollection={"xref": "ThugFace"})
    body.add(
        "CharacterHeadModel",
        "KnotTop_Medium",
        coll,
        m_iheadmodeltype=3,
        modelNames=[
            model(m) for m in ("Medium_Skeleton", "KnotTop_Medium_Head1", "KnotTop_Medium_Hair")
        ],
    )
    # the gag-ball gimps: the type points at the OTHER head, the model list names the twin
    body.add(
        "CharacterHeadModel",
        "Gimp7",
        coll,
        m_iheadmodeltype=20,
        modelNames=[model(m) for m in ("Skel", "GimpHead1", "GimpBody", "GimpHead1_NoSKL")],
    )
    body.add(
        "CharacterHeadModel",
        "NoType",
        coll,
        m_iheadmodeltype=25,
        modelNames=[model(m) for m in ("Skel", "Some_Head")],
    )
    body.write(tmp_path, "Thug")
    fr._HEADS.clear()
    yield str(tmp_path)
    fr._HEADS.clear()


def test_game_head_is_the_head_collections_model_of_the_variants_type(heads):
    gh = fr.game_head(heads, "KnotTop_Medium", ["KnotTop_Medium_Head1", "KnotTop_Medium_Hair"])
    assert gh["head"] == "Medium_Head_1" and gh["static"] == "KnotTop_Medium_Head1"
    assert gh["head_model_type"] == 3 and gh["head_model_type_name"] == "MEDIUM_HEAD_1"
    assert [(r["path"], r["sheet_id"]) for r in gh["texture_sheets"]] == [
        ("/art/t/head.bmp", 123),
        ("/art/t/Teeth.bmp", 456),
    ]
    assert gh["texture_sheets"][0]["slot"] == 0 and gh["texture_sheets"][0]["lod"] == 0
    assert "head model type" in gh["basis"]


def test_game_head_prefers_the_rigged_twin_named_beside_the_static_copy(heads):
    gh = fr.game_head(heads, "Gimp7", ["GimpBody", "GimpHead1_NoSKL"])
    assert gh["head"] == "GimpHead1" and gh["head_by_type"] == "GimpHead2"
    assert gh["texture_sheets"] == []  # the sheets belong to the other head's node
    assert "own model list" in gh["basis"]


def test_game_head_needs_exactly_one_static_head_and_a_known_type(heads):
    assert fr.game_head(heads, "KnotTop_Medium", ["KnotTop_Medium_Hair"]) is None
    assert fr.game_head(heads, "KnotTop_Medium", ["A_Head", "B_Head"]) is None
    assert fr.game_head(heads, "NoType", ["Some_Head"]) is None
    assert fr.game_head(heads, "Unknown", ["Some_Head"]) is None


# ------------------------------------------------------------ the GLB writer
def face_rig(tmp_path, rig):
    """A four-bone head (Bip01 > Neck > Head > Jaw) with two poses, attached to
    the last body bone."""
    names = np.array(["Bip01", "Neck", "Head", "Jaw"])
    par = np.array([-1, 0, 1, 2])
    Rb = np.tile(np.eye(3), (4, 1, 1))
    tb = np.array([[0.0, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.2, 0.0], [0.0, 0.2, 0.05]])
    bind = tmp_path / "bind_face.npz"
    np.savez(bind, Rb=Rb, tb=tb, names=names, par=par)

    def pal(jaw_drop):
        p = np.tile(np.eye(4)[:3], (1, 4, 1, 1)).astype(np.float32)
        p[0, 3, 1, 3] = -jaw_drop  # the jaw translated down
        return np.repeat(p, 2, axis=0)

    anims = [("FACE EN1/Open", pal(0.0), 2.0), ("FACE EN1/DamageL", pal(0.03), 2.0)]
    V = np.array([[0, 0.2, 0], [0.02, 0.2, 0.05], [-0.02, 0.2, 0.05]], np.float32)
    SI = np.array([[2, 0, 0, 0], [3, 0, 0, 0], [3, 0, 0, 0]], np.uint16)
    SW = np.array([[1, 0, 0, 0]] * 3, np.float32)
    part = (V, SI, SW, np.array([[0, 1, 2]], np.uint32), np.zeros((3, 2), np.float32), "head")
    return dict(
        bind=str(bind),
        parts=[part],
        anims=anims,
        attach_idx=rig.NB - 1,
        M=np.eye(3),
        t=np.zeros(3),
        proxy_slots=[],
        proxy_align=None,
        auto_poses={nm.split("/")[-1]: p[0] for nm, p, _f in anims},
        blink_closed=None,
        family="EN1",
        head="Test_Head",
    )


def face_channels(glb, anim_name):
    """{(face bone, path): (times, values)} of one animation."""
    j = glb.j
    a = [x for x in j["animations"] if x["name"] == anim_name][0]
    out = {}
    for c in a["channels"]:
        nm = j["nodes"][c["target"]["node"]]["name"]
        if nm.startswith("f_") and nm != "f_anchor":
            s = a["samplers"][c["sampler"]]
            out[(nm, c["target"]["path"])] = (glb.accessor(s["input"]), glb.accessor(s["output"]))
    return a, out


@pytest.fixture
def face_meta(rig):
    dur = (rig.F - 1) / rig.fps
    track = [
        seg(0.0, 0.05, "IDLE"),
        seg(0.05, 0.15, "HitLeft", ["DamageL"]),
        seg(0.15, None, "IDLE"),
    ]
    st = body_state("Hit", "clip_test", track, duration_s=dur)
    return meta_with(
        [st], {"clip_test": {"used_by": [used("Hit")], "pairs": [], "duration_s": dur}}
    )


def test_engine_rule_bakes_the_states_face_track_into_the_body_clip(tmp_path, rig, face_meta):
    out = tmp_path / "e.glb"
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        face=face_rig(tmp_path, rig),
        meta=face_meta,
        face_rule="engine",
        face_idle=False,
    )
    glb = parse_glb(out)
    a, ch = face_channels(glb, "clip_test")
    times, tr = ch[("f_Jaw", "translation")]
    t, y = np.ravel(times), tr[:, 1]
    assert list(t) == sorted(set(t)) and t[0] == 0.0
    # neutral first (the jaw at its bind height), then the hit pose eases in
    assert abs(y[0] - 0.2) < 1e-6 and y.min() < 0.2 - 0.005
    # ... from the hit's own time, not before
    moved = t[np.abs(y - y[0]) > 1e-6]
    assert moved.min() > 0.05
    assert np.any(np.isclose(t, 0.05, atol=1e-5))
    face = a["extras"]["watchmen"]["face"]
    assert face["rule"] == "engine" and face["face_class"] == "FaceEN1"
    assert face["baked_from"]["state"] == "Hit" and face["idle_cycle_baked"] is False
    assert [p["pose"] for p in face["poses"]] == ["Open", "DamageL", "Open"]
    assert face["poses"][1]["written_time_s"] == 0.05
    # only bones below the head carry face keys
    assert {k[0] for k in ch} == {"f_Jaw"}
    sx = glb.j["skins"][1]["extras"]["watchmen"]["face"]
    assert sx["head_model"] == "Test_Head" and sx["face_classes"] == ["FaceEN1"]
    pose = [x for x in glb.j["animations"] if x["name"] == "FACE EN1/DamageL"][0]
    assert pose["extras"]["watchmen"]["face_pose"]["face_states"][0]["state"] == "HitLeft"


def test_engine_rule_without_a_track_holds_the_neutral_pose(tmp_path, rig):
    out = tmp_path / "n.glb"
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        face=face_rig(tmp_path, rig),
        meta=None,
        face_rule="engine",
    )
    a, ch = face_channels(parse_glb(out), "clip_test")
    _t, tr = ch[("f_Jaw", "translation")]
    assert np.allclose(tr, tr[0])
    assert "no face track" in a["extras"]["watchmen"]["face"]["note"]


def test_legacy_rule_ignores_the_face_block(tmp_path, rig, face_meta, monkeypatch):
    """legacy: no face extras, and the same bytes whether or not the metadata has
    a face block (the name-based rule of 1.3.0 never read one)."""
    monkeypatch.setenv("WATCHMEN_FACE_RULE", "legacy")
    a, b = tmp_path / "a.glb", tmp_path / "b.glb"
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(a),
        str(rig.bind_npz),
        face=face_rig(tmp_path, rig),
        meta=face_meta,
    )
    plain = dict(face_meta)
    plain.pop("face")
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(b),
        str(rig.bind_npz),
        face=face_rig(tmp_path, rig),
        meta=plain,
        face_rule="legacy",
    )
    assert a.read_bytes() == b.read_bytes()
    glb = parse_glb(a)
    anim, ch = face_channels(glb, "clip_test")
    assert "face" not in (anim.get("extras") or {}).get("watchmen", {})
    assert "extras" not in glb.j["skins"][1]
    _t, tr = ch[("f_Jaw", "translation")]
    assert len(tr) == 2 and np.allclose(tr[0], tr[1])  # one held pose for the whole clip


# ------------------------------------------------- the metadata block (build)
def _face_fragment(tmp_path):
    """AnimationClassEnemy01Face.fragment.json: the face_class() tree on disk."""
    import test_anim_meta as tam

    f = tam.Frag()
    root = f.add("AnimationClassWM", "Enemy01FaceAnimationClass", m_iclassid=7)
    alive = f.add("AnimationStateGroupWM", "Alive", root)
    active = f.add("AnimationStateGroupWM", "Active", alive, **{asm.RANDOM_STATE: True})
    idles = f.add("AnimationStateGroupWM", "Idles", active, **{asm.RANDOM_STATE: True})

    def st(name, parent, clip):
        s = f.add("AnimationStateWM", name, parent, m_neaseinduration=0.21)
        b = f.add("AnimationBlendWM", "{MOTION_LAYER_1}", s, m_nweight=1.0)
        f.add(
            "AnimationSlotWM",
            "{%s.animation}" % clip,
            b,
            m_nweight=1.0,
            targetAnimation="Animation/EN1/FACE/%s.animation" % clip,
        )
        return s

    def tr(owner, target, **crit_props):
        t = f.add("AnimationTransitionWM", "{trans}", owner, m_etostate={"ref": target})
        if crit_props:
            f.add("AnimationCriteriaWM", "{crit}", t, **crit_props)

    pt = dict(m_ianimationcriteria=asm.CRIT_PLAY_TIME, m_iintervaltype=2)
    tr(st("IdleA", idles, "MouthClosed_EyesOpen"), idles, m_nintervalmin=3.0, **pt)
    tr(st("IdleB", idles, "Provocatively"), idles, m_nintervalmin=0.5, **pt)
    hit = f.add("AnimationStateGroupWM", "HitResponse", active)
    f.add(
        "AnimationCriteriaWM",
        "{crit}",
        hit,
        m_ianimationcriteria=asm.CRIT_ACTION,
        m_ianimationaction=fr.A_HITTAKEN,
        m_tentryonly=True,
    )
    st("HitLow", hit, "DamageBalls")
    tr(hit, idles, m_nintervalmin=0.75, **pt)
    tr(idles, hit)
    tr(hit, hit)
    tr(alive, active, m_ianimationcriteria=asm.CRIT_ACTION, m_ianimationaction=fr.A_STOP_SPEAK)
    f.nodes[0]["props"].append(["m_edefaultanimstate", "ref", {"ref": idles}])
    f.write(tmp_path, "Enemy01Face")


def _charvisual(tmp_path, body_id, face_id):
    import test_anim_meta as tam

    f = tam.Frag()
    cv = f.add("CharacterVisual", "EN1_goon")
    f.add("AnimationCtrlWM", "AnimCtrl", cv, m_ianimationclassid=body_id)
    head = f.add("Character", "HeadModel", cv)
    f.add("AnimationCtrlWM", "AnimCtrl", head, m_ianimationclassid=face_id)
    d = tmp_path / "extracted" / "TNT" / "CharacterVisual"
    d.mkdir(parents=True, exist_ok=True)
    j = {"instances": [f.cls], "nodes_full": f.nodes}
    (d / "GoonCharVisual.fragment.json").write_text(json.dumps(j))


@pytest.fixture
def face_extract(tmp_path):
    """A hero finisher that hits its victim at play position 0.25 and kills it at
    0.7; the victim class (id 3) has a face (class id 7)."""
    import test_anim_meta as tam

    h = tam.Frag()
    g = h.add("AnimationStateGroupWM", "FinishingMovesGroup")
    h.state(
        "Finish_move_A",
        g,
        "RSH_COM_ATT_finish_EN1_A",
        events=[("KILL_ANIMATION_PARTNER", 0.7), ("IMPACT_EFFECTS", 0.25)],
        m_imasterof=8,
        m_tislooping=False,
    )
    h.write(tmp_path, "Rorschach")
    e = tam.Frag()
    root = e.add(
        "AnimationClassWM",
        "Enemy01AnimationClass",
        m_ianimationmodeltype=tam.ENEMY_01,
        m_iclassid=3,
    )
    sl = e.add("Folder", "SlaveStates", root)
    grp = e.add("AnimationStateGroupWM", "FinishingGroup_Victim_01", sl, m_istategroupid=8)
    e.criteria(
        e.state("Finished_by_Rorshack_A", grp, "EN1_COM_DMG_finish_RSH_A"),
        ("RORSCHACH", tam.RORSCHACH, False),
    )
    e.state("Idle", root, "EN1_COM_MOV_idle_stand", m_tislooping=True)
    e.write(tmp_path, "Enemy01")
    tam.write_clip(
        tmp_path,
        "RSH_COM_ATT_finish_EN1_A",
        ((0, 1, -0.5), (0, 1, 0)),
        ((0.1, 0, 1.5), (0.1, 0, 1.0)),
    )
    tam.write_clip(tmp_path, "EN1_COM_DMG_finish_RSH_A", ((-0.1, 1, -1.0), (-0.1, 1, -2.0)))
    tam.write_clip(tmp_path, "EN1_COM_MOV_idle_stand", ((0, 1, 0), (0, 1, 0)))
    return tmp_path


def test_metadata_without_face_fragments_has_no_face_block(face_extract):
    import anim_meta as am

    m = am.build(str(face_extract))
    assert m["format"] == "watchmen-anim-meta/2"
    assert "face" not in m and "face_format" not in m
    assert all("face" not in s for c in m["classes"].values() for s in c["states"])


def test_metadata_face_block_is_additive_and_tracks_the_pair_hits(face_extract):
    import anim_meta as am

    plain = am.build(str(face_extract))
    _face_fragment(face_extract)
    _charvisual(face_extract, 3, 7)
    m = am.build(str(face_extract))
    # additive under the same format: every key and value of a table without
    # face fragments is unchanged
    assert m["format"] == plain["format"] and m["face_format"] == fr.FACE_FORMAT
    assert set(m) - set(plain) == {"face", "face_format"}
    assert list(m["classes"]) == list(plain["classes"])  # the face class is not a body class

    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k not in ("face", "inflicts")}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x

    for k in plain:
        assert strip(m[k]) == plain[k], k
    face = m["face"]
    assert face["body_class"]["Enemy01"]["face_class"] == "Enemy01Face"
    assert face["body_class"]["Rorschach"]["face_class"] is None
    fc = face["classes"]["Enemy01Face"]
    assert fc["class_id"] == 7 and fc["pose_family"] == "EN1" and fc["hit_hold_s"] == 0.75
    assert [s["name"] for s in fc["idle_cycle"]["states"]] == ["IdleA", "IdleB"]
    assert [s["min_s"] for s in fc["idle_cycle"]["states"]] == [3.0, 0.5]
    hit_state = [s for s in fc["states"] if s["name"] == "HitLow"][0]
    assert hit_state["glb_animation_names"] == ["FACE EN1/DamageBalls"]
    states = {s["name"]: s for s in m["classes"]["Enemy01"]["states"]}
    assert states["Idle"]["face"]["category"] == "idle_only"
    assert [x["face_state"] for x in states["Idle"]["face"]["track"]] == ["IDLE"]
    hero = [s for s in m["classes"]["Rorschach"]["states"] if s["name"] == "Finish_move_A"][0]
    assert hero["face"] is None  # no HeadModel in its CharVisual: no face controller
    assert [x["event"] for x in hero["inflicts"]] == ["IMPACT_EFFECTS", "KILL_ANIMATION_PARTNER"]
    (pair,) = [p for p in m["pairs"] if p.get("primary")]
    assert pair["face"]["master"] is None
    victim = pair["face"]["partner"]
    kinds = [(i["input"], i["t_s"]) for i in victim["inputs"]]
    # the clip is 2 s long: play positions 0.25 and 0.7 on the pair's clock
    assert kinds == [("HITTAKEN", 0.5), ("HITTAKEN", 1.4), ("DEAD", 1.4)]
    names = [x["face_state"] for x in victim["track"]]
    assert names[:3] == ["IDLE", "HitLow", "IDLE"]
    first_hit = victim["track"][1]
    assert abs(first_hit["from_s"] - 0.5) <= 2 * fr.DT
    assert 0.75 <= first_hit["to_s"] - first_hit["from_s"] <= 0.75 + 3 * fr.DT
    # and the baker picks that pair track for the victim's clip
    c = fr.choose_track(m, "EN1_COM_DMG_finish_RSH_A", "EN1")
    assert c["source"]["pair"] is not None and c["source"]["role"] == "partner"
    assert c["track"] == victim["track"]


# ------------------------------------------------------------ texture sheets
def _prop(salt, key, typ, payload):
    import struct

    import kapow_props

    assert len(payload) % 4 == 0
    return struct.pack("<IIII", salt, kapow_props.name_hash(key), typ, len(payload) // 4) + payload


def _str_payload(text):
    import struct

    raw = text.encode() + b"\0"
    raw += b"\0" * (-len(raw) % 4)
    return struct.pack("<I", len(raw) // 4) + raw


def _sheet(salt, name, uid, **overrides):
    import struct

    b = _prop(salt, "name", fr._T_STRING, _str_payload(name))
    b += _prop(salt, "uniqueID", fr._T_ID, struct.pack("<II", uid >> 32, uid & 0xFFFFFFFF))
    for k in fr.SHEET_OVERRIDES:
        b += _prop(salt, k, fr._T_STRING, _str_payload(overrides.get(k, "")))
    return b


GOATEE = 5169807255234288178  # the id ThugFace's LARGE_HEAD_GOATEE node names


def texture_header():
    """Two sheets, as in bikers/textures/head.bmp; one stray byte in front, as the
    records are not aligned in the real file."""
    return (
        b"\x08Texture\0"
        + _sheet(0x7E383AC9, "default", 5166396499723655277)
        + b"\x0d\0\0\0TextureSheet\0"
        + _sheet(
            0x7E443205, "Goatee", GOATEE, diffuseMapOverride="/art/c/bikers/textures/head02.bmp"
        )
    )


def test_texture_sheets_reads_names_ids_and_layer_overrides():
    assert fr.texture_sheets(texture_header()) == [
        {"name": "default", "unique_id": 5166396499723655277, "overrides": {}},
        {
            "name": "Goatee",
            "unique_id": GOATEE,
            "overrides": {"diffuse": "/art/c/bikers/textures/head02.bmp"},
        },
    ]
    assert fr.texture_sheets(b"") == [] and fr.texture_sheets(b"no sheets in here at all") == []


def test_sheet_records_split_the_description_string():
    recs = fr.sheet_records("2,0,0,0,/art/a.bmp,11,1,2,3,/art/b.bmp,5169807255234288178,")
    assert recs == [
        {"slot": 0, "pivot": 0, "lod": 0, "path": "/art/a.bmp", "sheet_id": 11},
        {"slot": 1, "pivot": 2, "lod": 3, "path": "/art/b.bmp", "sheet_id": GOATEE},
    ]
    assert fr.sheet_records(None) == [] and fr.sheet_records("2,") == []
    assert fr.sheet_records("2,0,0,0,/art/a.bmp,not-a-number,") == []


def test_sheet_overrides_follow_the_sheet_the_collection_node_names(tmp_path):
    d = tmp_path / "extracted" / "art" / "c" / "bikers" / "textures"
    d.mkdir(parents=True)
    (d / "head.bmp").write_bytes(texture_header())
    rec = {"slot": 0, "pivot": 0, "lod": 0, "path": "/art/c/bikers/textures/head.bmp"}
    got = fr.sheet_overrides(str(tmp_path), [dict(rec, sheet_id=GOATEE)])
    assert got == {
        "art/c/bikers/textures/head.bmp": {
            "sheet": "Goatee",
            "unique_id": GOATEE,
            "overrides": {"diffuse": "/art/c/bikers/textures/head02.bmp"},
        }
    }
    # the default sheet, an unknown id and a texture without a header: nothing to do
    assert fr.sheet_overrides(str(tmp_path), [dict(rec, sheet_id=5166396499723655277)]) == {}
    assert fr.sheet_overrides(str(tmp_path), [dict(rec, sheet_id=1)]) == {}
    assert (
        fr.sheet_overrides(str(tmp_path), [dict(rec, path="/art/none.bmp", sheet_id=GOATEE)]) == {}
    )
    assert fr.sheet_overrides(str(tmp_path), None) == {}


def _texture_dir(root, rel, rgb, sheet=None):
    from PIL import Image

    d = root / "textures"
    for part in rel.strip("/").split("/"):
        d = d / part
    d.mkdir(parents=True)
    Image.new("RGB", (4, 4), rgb).save(d / "0_diffuse_4x4_DXT1.png")
    Image.new("RGB", (4, 4), (128, 128, 255)).save(d / "1_normal_4x4_ATI2.png")
    if sheet is not None:
        (d / "sheet.json").write_text(json.dumps(sheet))
    return d


def test_face_part_takes_the_overriding_sheets_diffuse_and_keeps_its_other_layers(tmp_path):
    import io

    from PIL import Image

    import char_lib
    import characters_export as ce
    import watchmen_extract as we

    _texture_dir(tmp_path, "/art/c/bikers/textures/head.bmp", (10, 200, 10))
    _texture_dir(tmp_path, "/art/c/bikers/textures/head02.bmp", (200, 10, 10))
    d = tmp_path / "extracted" / "art" / "c" / "bikers" / "textures"
    d.mkdir(parents=True)
    (d / "head.bmp").write_bytes(texture_header())
    char_lib._LAYERCACHE.clear()
    head = we.texture_ref("/art/c/bikers/textures/head.bmp")
    part = (None, None, None, None, None, head)
    rec = {"slot": 0, "pivot": 0, "lod": 0, "path": head.path, "sheet_id": GOATEE}
    roots = [str(tmp_path / "textures")]

    def colour(layers):
        return Image.open(io.BytesIO(layers["diffuse"])).convert("RGB").getpixel((0, 0))

    face = {"parts": [part], "game_head": {"texture_sheets": [rec]}}
    tex = ce._face_textures(face, roots, str(tmp_path))
    (key,) = tex
    assert key == "head" and key.path.endswith("#sheet=Goatee") and key != head
    assert colour(tex[key]) == (200, 10, 10)  # head02's diffuse ...
    plain = char_lib._find_layers(head, roots)
    assert colour(plain) == (10, 200, 10)
    assert tex[key]["normal"] == plain["normal"]  # ... on head's own normal map
    assert face["parts"][0][5] is key
    assert face["game_head"]["sheet_overrides"][0]["sheet"] == "Goatee"
    # without a sheet record the part keeps its own texture
    face = {"parts": [part], "game_head": {"texture_sheets": []}}
    tex = ce._face_textures(face, roots, str(tmp_path))
    assert colour(tex[head]) == (10, 200, 10) and "sheet_overrides" not in face["game_head"]


def test_subtract_blend_layer_becomes_black_ink_with_the_brightness_as_alpha(tmp_path):
    """Blend type 2 = subtract ("items=standard:0,add:1,subtract:2,manual:3" in the
    executable): Rorschach's inkblot layers are white blots on black.  Drawn as
    they are they black out the face they lie on."""
    import io

    from PIL import Image

    import char_lib
    import watchmen_extract as we

    d = _texture_dir(
        tmp_path, "/art/r/spots.bmp", (0, 0, 0), sheet={"blendType": 2, "renderType": 1}
    )
    im = Image.new("RGB", (4, 4), (0, 0, 0))
    im.putpixel((1, 1), (255, 255, 255))
    im.putpixel((2, 2), (128, 128, 128))
    im.save(d / "0_diffuse_4x4_DXT1.png")
    _texture_dir(tmp_path, "/art/r/coat.bmp", (90, 60, 30), sheet={"blendType": 0, "renderType": 0})
    char_lib._LAYERCACHE.clear()
    roots = [str(tmp_path / "textures")]
    ink = char_lib._find_layers(we.texture_ref("/art/r/spots.bmp"), roots)
    assert ink["blend"] == "subtract"
    px = Image.open(io.BytesIO(ink["diffuse"]))
    assert px.mode == "RGBA"
    assert px.getpixel((1, 1)) == (0, 0, 0, 255)  # full ink
    assert px.getpixel((2, 2)) == (0, 0, 0, 128)
    assert px.getpixel((0, 0)) == (0, 0, 0, 0)  # nothing: the face shows through
    coat = char_lib._find_layers(we.texture_ref("/art/r/coat.bmp"), roots)
    assert "blend" not in coat
    assert Image.open(io.BytesIO(coat["diffuse"])).convert("RGB").getpixel((0, 0)) == (90, 60, 30)


def test_subtract_layer_is_written_as_a_blend_material(tmp_path, rig):
    import char_lib
    import watchmen_extract as we

    _texture_dir(tmp_path, "/art/r/spots.bmp", (255, 255, 255), sheet={"blendType": 2})
    char_lib._LAYERCACHE.clear()
    nm = we.texture_ref("/art/r/spots.bmp")
    V, SI, SW, T, UV, _ = rig.parts[0]
    tex = char_lib.find_textures([(V, SI, SW, T, UV, nm)], [str(tmp_path / "textures")])
    out = tmp_path / "ink.glb"
    vg.write_glb([(V, SI, SW, T, UV, nm)], rig.manifest, str(out), str(rig.bind_npz), textures=tex)
    (mat,) = parse_glb(out).j["materials"]
    assert mat["alphaMode"] == "BLEND" and "alphaCutoff" not in mat
    assert mat["extras"]["watchmen"]["blend"] == "subtract"


# ----------------------------------------------------------- `char` metadata
def test_extract_out_is_found_from_a_fragment_path(tmp_path):
    import watchmen

    f = tmp_path / "OUT" / "extracted" / "TNT" / "Fragments" / "Enemy" / "Gimp.fragment.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    assert watchmen.extract_out_of(str(f)) == str(tmp_path / "OUT")
    assert watchmen.extract_out_of(str(tmp_path / "elsewhere" / "Gimp.fragment.json")) is None
    # no animation classes in that tree: no table, and no error
    assert watchmen.char_meta(str(f)) is None
    assert watchmen.char_meta(str(tmp_path / "elsewhere" / "Gimp.fragment.json")) is None


def test_char_meta_builds_the_table_of_the_fragments_extract(face_extract):
    import watchmen

    f = face_extract / "extracted" / "TNT" / "Fragments" / "Enemy" / "Thug.fragment.json"
    f.parent.mkdir(parents=True)
    f.write_text("{}")
    m = watchmen.char_meta(str(f))
    assert m["format"] == "watchmen-anim-meta/2" and "EN1_COM_MOV_idle_stand" in m["clips"]
    assert vg.clip_loops(m, "EN1_COM_MOV_idle_stand") is True
    assert vg.clip_loops(m, "en1_com_mov_idle_stand") is True  # as the extras resolve names
    assert vg.clip_loops(m, "EN1_COM_DMG_finish_RSH_A") is False
    assert vg.clip_loops(m, "unknown") is False and vg.clip_loops(None, "x") is False


def test_cli_no_meta_is_a_char_option(capsys):
    import watchmen

    assert watchmen.main(["watchmen", "characters", "x", "y", "--no-meta"]) == 2
    assert "--no-meta applies to: char" in capsys.readouterr().out
    assert "[--no-meta]" in watchmen.USAGE["char"][1]


def test_skeleton_model_pick_does_not_depend_on_listing_order(tmp_path, monkeypatch):
    """ensure_binds indexes *.model by base name; with two files of one name the
    pick was whichever the file system listed first."""
    import glob as _glob

    import build_bind_file
    import watchmenlib as wl

    name = os.path.basename(wl._SKEL_ASSETS["female"])
    for sub in ("zz", "aa"):
        d = tmp_path / "extracted" / sub
        d.mkdir(parents=True)
        (d / name).write_bytes(b"x")
    picked = []
    monkeypatch.setattr(build_bind_file, "build", lambda src, tpl, out: picked.append(src))
    real = _glob.glob
    for flip in (False, True):
        monkeypatch.setattr(
            _glob, "glob", lambda *a, _f=flip, **k: sorted(real(*a, **k), reverse=_f)
        )
        try:
            wl.ensure_binds(
                "none.naz", str(tmp_path / ("binds%d" % flip)), extract_dir=str(tmp_path)
            )
        except Exception:
            pass  # the other skeletons are not in this tree
    mine = [p for p in picked if os.path.basename(p) == name]
    assert len(mine) == 2 and mine[0] == mine[1]
    assert os.sep + "aa" + os.sep in mine[0]
