"""Pass 1, package C (anim): face rule, pair placement with a turned master,
finisher camera cuts.

Synthetic nodes, records and clips only.  What is pinned here was read from
the executable in the review round of 2026-10-05 (addresses in the modules):

* an uncontrolled blend plays its first child alone (0x59e905), m_nweight has
  no reader;
* the idle group is entered at a random member (0x5f076f), a STUN_MIDDLE hit
  on a silent enemy leaves its hit state after one update;
* the master's node is its GamePivot frame (0x6b015d, 0x5b56a9): the body
  turns with GamePivot, the anchored partner swings with the master;
* a cut camera's position is fixed for the shot (0x633011), a kept position
  falls back to the character camera, a side shot's height is the midpoint of
  the two roots, blends run on game time with the HalfBell weight (0x779d40).
"""

import math
import os
import sys
import types

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_meta as am
import anim_state_machine as asm
import face_rule as fr
import fx_meta as fx

_n = [0]


def node(cls, name, parent=None, **props):
    _n[0] += 1
    n = asm.Node("p1c%d" % _n[0], cls, name)
    n.props = dict(props)
    if parent is not None:
        n.parent = parent
        parent.children.append(n)
    return n


def slot(blend, clip, order=None, **props):
    if order is not None:
        props["siblingOrder"] = order
    return node(
        asm.CLS_SLOT,
        clip,
        blend,
        m_sduration="1.0 s",
        targetAnimation="Animation/EN1/FACE/%s.animation" % clip,
        **props,
    )


def bare_interpreter():
    it = object.__new__(asm.Interpreter)
    it.env = types.SimpleNamespace(values={})
    return it


# ------------------------------------------------- blends without a parameter
def test_uncontrolled_blend_plays_its_first_child_alone():
    blend = node(asm.CLS_BLEND, "{MOTION_LAYER_1}")
    # listed out of order: the engine's first child is the lowest siblingOrder
    slots = [slot(blend, "Shout", 2), slot(blend, "Attack1", 1), slot(blend, "Third", 3)]
    w = asm.Interpreter._slot_pos_weights(None, blend, slots)
    assert w == {0: 0.0, 1: 1.0, 2: 0.0}
    # equal orders (or none stored): the first in the list, i.e. file order
    same = [slot(blend, "A"), slot(blend, "B")]
    assert asm.Interpreter._slot_pos_weights(None, blend, same) == {0: 1.0, 1: 0.0}
    # a single slot is not a mix
    assert asm.Interpreter._slot_pos_weights(None, blend, same[:1]) == {0: 1.0}


def test_controlled_blend_still_interpolates_between_its_slots():
    blend = node(
        asm.CLS_BLEND, "b", m_iblendctrlparam=3, m_nblendintervalstart=0.0, m_nblendintervalend=1.0
    )
    slots = [
        slot(blend, "Lo", 1, m_nparentblendposition=0.0),
        slot(blend, "Hi", 2, m_nparentblendposition=1.0),
    ]
    it = bare_interpreter()
    it.env.values[3] = 0.25
    assert it._slot_pos_weights(blend, slots) == pytest.approx({0: 0.75, 1: 0.25})


def test_slot_and_blend_m_nweight_are_not_weight_factors():
    blend = node(asm.CLS_BLEND, "b", m_nweight=0.5)
    first = slot(blend, "First", 1, m_nweight=0.25)
    slot(blend, "Second", 2, m_nweight=1.0)
    page = types.SimpleNamespace(blend=1.0, slots=lambda: [(blend, s) for s in blend.children])
    out = bare_interpreter()._stack_weights([page], {})
    # the first child at full weight, whatever m_nweight says; the second not at all
    assert out == {first.p("targetAnimation"): 1.0}


# ------------------------------------------------------------------- the face
def face_state(parent, name, clips, **props):
    s = node(asm.CLS_STATE, name, parent, **props)
    b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
    for i, c in enumerate(clips):
        slot(b, c, i + 1)
    return s


def test_clip_mix_of_a_two_slot_state_is_first_child_only():
    root = node(asm.CLS_CLASS, "c")
    att = face_state(root, "Attack", ["Attack1", "MouthShout_EyesAnger"])
    mix = fr.clip_mix(att)
    assert mix["rule"] == "first_child_only" and mix["shown"] == "Attack1"
    assert mix["weights"] == [1.0, 0.0]
    assert "0x59e905" in mix["evidence"] and "0x5b4ef7" in mix["evidence"]
    assert fr.clip_mix(face_state(root, "One", ["Attack1"])) is None
    # a blend driven by a control parameter is not this rule
    ctl = face_state(root, "Ctl", ["A", "B"])
    ctl.children[0].props["m_iblendctrlparam"] = 2
    assert fr.clip_mix(ctl) is None


def test_face_texts_carry_the_confirmed_rules():
    text = " ".join(fr.NOT_ESTABLISHED)
    assert "mix of the two slots" not in text and len(fr.NOT_ESTABLISHED) == 4
    assert "m_tforcecombat" in text and "m_istateofmind" in text
    d = fr.DRIVERS
    assert "never cleared" in d["HITTAKEN"]["lifetime"] and "initial value 0" in (
        d["HITTAKEN"]["lifetime"]
    )
    assert "no voice has the character root as pivot" in d["STOP_SPEAK"]["sent"]
    assert "footsteps on a surface that has a footstep sound" in d["STOP_SPEAK"]["sent"]
    assert "category 0" in d["START_SPEAK"]["sent"]
    assert "being pushed" in d["CHARACTER_MODE"]["sent"]
    assert "m_tforcecombat" in d["CHARACTER_MODE"]["rule"]
    assert "category 0" in fr.TALK_CLIPS_RULE and "start_delay_s" in fr.TALK_CLIPS_RULE
    assert "one controller update" in fr.HIT_THEN_BASIS and "never cleared" in fr.HIT_THEN_BASIS


CYCLE = {
    "states": [
        {"name": "IdleA", "clips": ["Open"], "min_s": 3.0, "ease_in_s": 0.21},
        {"name": "IdleB", "clips": ["Closed"], "min_s": 0.5, "ease_in_s": 0.21},
    ]
}
RANDOM_ENTRY = {"first_segment": "random", "after_transition": "random"}


def fclass(entry=None):
    cyc = dict(CYCLE)
    if entry is not None:
        cyc["entry"] = entry
    return {"pose_family": "EN1", "idle_cycle": cyc, "states": []}


def clip_named(first):
    """A clip name whose seeded entry draw (at t0 = 0) is idle state `first`."""
    for k in range(200):
        name = "clip_%d" % k
        if fr.idle_plan(name, 0.0, 60.0, CYCLE, entry="random")[0][1] == first:
            return name
    raise AssertionError("no clip name draws idle state %d" % first)


def test_idle_plan_entry_is_the_first_state_unless_asked_to_draw():
    a = fr.idle_plan("clip_a", 0.0, 60.0, CYCLE)
    assert a[0] == (0.0, 0) and a == fr.idle_plan("clip_a", 0.0, 60.0, CYCLE, entry=0)
    b = fr.idle_plan("clip_a", 0.0, 60.0, CYCLE, entry=1)
    assert b[0] == (0.0, 1) and [i for _t, i in b] == [(k + 1) % 2 for k in range(len(b))]
    # the entry state is held for ITS minimum time
    assert b[1][0] >= 0.5 - 1e-6 and a[1][0] >= 3.0 - 1e-6 and b[1][0] < 3.0


def test_idle_plan_random_entry_is_seeded_and_draws_both_members():
    draws = [
        fr.idle_plan("clip_%d" % k, 0.0, 60.0, CYCLE, entry="random")[0][1] for k in range(200)
    ]
    assert 60 < sum(draws) < 140  # a fair draw between two members
    name = clip_named(1)
    assert fr.idle_plan(name, 0.0, 60.0, CYCLE, entry="random") == fr.idle_plan(
        name, 0.0, 60.0, CYCLE, entry="random"
    )
    # the draw has a stream of its own: a clip that draws state 0 keeps the entry-0 plan
    zero = clip_named(0)
    assert fr.idle_plan(zero, 0.0, 60.0, CYCLE, entry="random") == fr.idle_plan(
        zero, 0.0, 60.0, CYCLE
    )
    # a class with one idle state has no cycle either way
    assert fr.idle_plan(name, 0.0, 60.0, {"states": CYCLE["states"][:1]}, entry="random") == []


def test_idle_entry_reads_the_class_record_and_defaults_to_the_first_state():
    assert fr.idle_entry(CYCLE, True) == 0 and fr.idle_entry(CYCLE, False) == 0
    cyc = dict(CYCLE, entry={"first_segment": 1, "after_transition": "random"})
    assert fr.idle_entry(cyc, True) == 1 and fr.idle_entry(cyc, False) == "random"


def chosen(track, rate=None):
    return {"track": track, "start_playpos": 0.0, "playpos_per_second": rate}


def seg(a, b, name, clips=None):
    d = {"from_s": a, "to_s": b, "face_state": name}
    if clips:
        d.update(clips=clips, ease_in_s=0.21)
    return d


def test_schedule_starts_an_idle_clip_in_the_drawn_member_and_loops_on_it():
    name = clip_named(1)
    ident = lambda pp: pp
    idle = [seg(0.0, None, "IDLE")]
    on, _ = fr.pose_schedule(chosen(idle), fclass(RANDOM_ENTRY), name, ident, True, 60.0)
    # starts on IdleB (eyes closed) without an ease, opens after >= 0.5 s ...
    assert on[0] == (0.0, "Closed", 0.0)
    assert on[1][1] == "Open" and 0.5 - 1e-6 <= on[1][0] < 3.0
    # ... and ends, with time to ease, in the state it starts in
    assert on[-1][1] == "Closed" and on[-1][0] + 0.21 <= 60.0
    # a table without the entry block, or a clip that draws IdleA, starts as before
    old, _ = fr.pose_schedule(chosen(idle), fclass(), name, ident, True, 60.0)
    assert old[0] == (0.0, "Open", 0.0) and old[-1][1] == "Open"
    zero = clip_named(0)
    assert (
        fr.pose_schedule(chosen(idle), fclass(RANDOM_ENTRY), zero, ident, True, 60.0)[0]
        == fr.pose_schedule(chosen(idle), fclass(), zero, ident, True, 60.0)[0]
    )
    # the idle cycle switched off: the neutral pose alone
    off, _ = fr.pose_schedule(chosen(idle), fclass(RANDOM_ENTRY), name, ident, False, 60.0)
    assert off == [(0.0, "Open", 0.0)]


def test_schedule_drops_an_entry_draw_that_cannot_come_back_before_the_end():
    name = clip_named(1)
    idle = [seg(0.0, None, "IDLE")]
    # 2.5 s: IdleB could be left but not re-entered (IdleA lasts >= 3 s)
    short, _ = fr.pose_schedule(chosen(idle), fclass(RANDOM_ENTRY), name, lambda pp: pp, True, 2.5)
    assert short == [(0.0, "Open", 0.0)]


def test_schedule_enters_a_later_idle_segment_at_a_drawn_member_with_its_ease():
    track = [seg(0.0, 0.75, "HitLeft", ["DamageL"]), seg(0.75, None, "IDLE")]
    fc = fclass(RANDOM_ENTRY)
    name = None
    for k in range(200):  # the draw is seeded by clip name and segment start
        if fr.idle_plan("hit_%d" % k, 0.75, 60.0, CYCLE, entry="random")[0][1] == 1:
            name = "hit_%d" % k
            break
    assert name
    sched, _ = fr.pose_schedule(chosen(track), fc, name, lambda pp: pp, True, 60.0)
    assert sched[0] == (0.0, "Open", 0.0) and sched[1] == (0.0, "DamageL", 0.0)
    assert sched[2] == (0.75, "Closed", 0.21)
    # a track that does not open with an idle segment ends in the first idle state
    assert sched[-1][1] == "Open"


def shipped_like_face_class():
    """Alive > Active > [Idles (random), HitResponse, Combat]; Combat's member
    Retreat tests DAMAGE_POSE == STUN_MIDDLE, as in Enemy01Face / Enemy04Face."""
    root = node(asm.CLS_CLASS, "FaceClass")
    alive = node(asm.CLS_GROUP, "Alive", root)
    active = node(asm.CLS_GROUP, "Active", alive)
    idles = node(asm.CLS_GROUP, "Idles", active, **{asm.RANDOM_STATE: True})
    idle_a = face_state(idles, "IdleA", ["MouthClosed_EyesOpen"], m_neaseinduration=0.21)
    idle_b = face_state(idles, "IdleB", ["MouthClosed_EyesClosed"], m_neaseinduration=0.21)

    def trans(owner, target):
        return node(asm.CLS_TRANS, "{trans}", owner, m_etostate={"ref": target.id})

    def crit(owner, kind, **props):
        return node(asm.CLS_CRIT, "{crit}", owner, m_ianimationcriteria=kind, **props)

    crit(trans(idle_a, idles), asm.CRIT_PLAY_TIME, m_iintervaltype=2, m_nintervalmin=3.0)
    crit(trans(idle_b, idles), asm.CRIT_PLAY_TIME, m_iintervaltype=2, m_nintervalmin=0.5)
    hit = node(asm.CLS_GROUP, "HitResponse", active)
    crit(hit, asm.CRIT_ACTION, m_ianimationaction=fr.A_HITTAKEN).props["m_tentryonly"] = True
    face_state(hit, "HitCenter", ["DamageStomach"], m_neaseinduration=0.21)
    crit(trans(hit, idles), asm.CRIT_PLAY_TIME, m_iintervaltype=2, m_nintervalmin=0.75)
    trans(idles, hit)
    trans(hit, hit)
    combat = node(asm.CLS_GROUP, "Combat", active)
    retreat = face_state(combat, "Retreat", ["MouthClosed_EyesOpen"], m_neaseinduration=0.21)
    crit(
        retreat,
        asm.CRIT_ENUM,
        m_ianimationenum=fr.E_DAMAGE_POSE,
        m_ianimationenumvalue=20,
    )
    trans(retreat, combat)
    crit(trans(alive, active), asm.CRIT_ACTION, m_ianimationaction=fr.A_STOP_SPEAK)
    root.props["m_edefaultanimstate"] = {"ref": idles.id}
    return root


def test_class_record_has_the_idle_entry_and_what_follows_a_stun_hit(monkeypatch):
    root = shipped_like_face_class()
    monkeypatch.setattr(fr, "load_face_class", lambda path: (root, list(asm.walk([root]))))
    _root, rec = fr.face_class_record("Face", "/x/Face.fragment", "/x", am)
    # default state = the idle group: the first segment is a random member too
    assert rec["idle_cycle"]["entry"] == {
        "first_segment": "random",
        "after_transition": "random",
        "default_state_is": "group",
    }
    assert "ENTERED at a uniformly random member" in rec["idle_cycle"]["rule"]
    # pose 20 on a silent character: HitCenter for one update, then Retreat
    assert rec["hit_pose_to_state"]["STUN_MIDDLE"] == "HitCenter"
    then = rec["hit_pose_then"]
    assert set(then) == {"STUN_MIDDLE"} and then["STUN_MIDDLE"]["face_state"] == "Retreat"
    assert then["STUN_MIDDLE"]["after_s"] <= 2 * fr.DT + 1e-6
    assert rec["hit_pose_to_state"]["LIGHT_MIDDLE_LEFT"] == "HitCenter"
    # a class whose default state is one idle state enters there
    idle_b = [n for n in asm.walk([root]) if n.name == "IdleB"][0]
    root.props["m_edefaultanimstate"] = {"ref": idle_b.id}
    _root, rec = fr.face_class_record("Face", "/x/Face.fragment", "/x", am)
    assert rec["idle_cycle"]["entry"]["first_segment"] == 1
    assert rec["idle_cycle"]["entry"]["default_state_is"] == "state"


# ------------------------------------------------------ pairs: a turned master
def facts(pos, yaw=0.0, interact=None, gp_pos=None, gp_yaw=None, dur=2.0):
    f = {"game_pivot": {"pos_start": list(pos), "yaw_start_deg": yaw}, "duration_s": dur}
    if interact is not None:
        f["interact"] = {"pos_start": list(interact)}
    if gp_pos is not None:
        f["_gp_pos"], f["_gp_yaw_deg"] = gp_pos, gp_yaw
    return f


def test_placement_of_a_master_turned_at_the_start_turns_the_partner_clip_too():
    m = facts((1.0, 1.0, 2.0), 30.0, (0.2, 0.0, 1.0))
    ox, oz = am._yaw_rot(-30.0, 0.2, 1.0)
    marker = (1.0 + ox, 2.0 + oz)
    # a partner whose own GamePivot start, turned by partner_yaw = 210, is on the marker
    vx, vz = am._yaw_rot(210.0, marker[0], marker[1])
    pl = am.placement(m, facts((vx, 1.0, vz)))
    assert pl["partner_yaw_deg"] == -150.0
    assert pl["partner_start_xz"] == pytest.approx(marker, abs=1e-4)
    assert pl["check"]["agreement_m"] == 0.0
    assert pl["check"]["partner_game_pivot_start_xz"] == pytest.approx(marker, abs=1e-4)
    assert pl["partner_origin_shift_xz"] == pytest.approx([0.0, 0.0], abs=1e-4)


def test_placement_of_an_unturned_master_is_unchanged():
    m = facts((0.5, 1.0, -0.25), 0.0, (0.1, 0.0, 0.9))
    pl = am.placement(m, facts((0.3, 1.0, 0.7)))
    assert pl["partner_yaw_deg"] == -180.0
    assert pl["check"]["partner_game_pivot_start_xz"] == [-0.3, -0.7]
    assert pl["partner_start_xz"] == [0.6, 0.65]
    assert pl["partner_origin_shift_xz"] == [0.9, 1.35]


def test_master_turn_drift_is_the_departure_from_the_fixed_marker():
    # yaw(0) = 30 degrees, the master walks 1 m along +Z without turning: the anchor
    # I0 - delta is in the NODE frame, so the fixed marker is left by |delta - R(30) delta|
    mf = facts(
        (0.0, 1.0, 0.0),
        30.0,
        (0.0, 0.0, 1.0),
        gp_pos=[[0.0, 1.0, 0.0], [0.0, 1.0, 1.0]],
        gp_yaw=[30.0, 30.0],
    )
    pl = am.placement(mf, facts((0.0, 1.0, 0.0)))
    turn, drift = am._master_turn(mf, pl, 0.0, 2.0)
    assert turn == 0.0
    assert drift == pytest.approx(2.0 * math.sin(math.radians(15.0)), abs=2e-3)


def test_master_turn_drift_of_a_master_that_turns_on_the_spot():
    mf = facts(
        (0.0, 1.0, 0.0),
        0.0,
        (0.0, 0.0, 1.0),
        gp_pos=[[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        gp_yaw=[0.0, 90.0],
    )
    pl = am.placement(mf, facts((0.0, 1.0, 0.0)))
    turn, drift = am._master_turn(mf, pl, 0.0, 2.0)
    # the partner, 1 m in front, is carried a quarter circle: chord sqrt(2)
    assert turn == 90.0 and drift == pytest.approx(math.sqrt(2.0), abs=2e-3)
    # only the window counts
    assert am._master_turn(mf, pl, 0.0, 1.0) == (45.0, pytest.approx(0.765, abs=2e-3))


def state_rec(**kw):
    rec = {
        "events": [],
        "special_handling": {"id": 0, "name": "NORMAL"},
        "animation_type": {"id": 0, "name": "NOTSET"},
        "speed": 1.0,
        "duration_s": 2.0,
        "start_playpos": 0.0,
        "ease_in_s": 0.2,
        "absolute": False,
    }
    rec.update(kw)
    return rec


def test_timeline_names_the_anchor_frame_and_flags_a_turning_master():
    mf = facts(
        (0.0, 1.0, 0.0),
        0.0,
        (0.0, 0.0, 1.0),
        gp_pos=[[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]],
        gp_yaw=[0.0, 90.0],
    )
    vf = facts((0.0, 1.0, 0.0))
    pl = am.placement(mf, vf)
    tl = am.pair_timeline(state_rec(), state_rec(absolute=True), mf, vf, pl)
    assert tl["anchor_frame"] == "master node"
    assert tl["anchor_rotation_unverified"] is True and tl["master_yaw_change_deg"] == 90.0
    assert tl["anchor_drift_if_master_turns_m"] == pytest.approx(math.sqrt(2.0), abs=2e-3)


@pytest.mark.parametrize("conv", [am.CONVENTIONS, am.CONVENTIONS_TRUE])
def test_conventions_say_the_body_turns_with_game_pivot_and_the_anchor_swings(conv):
    assert "R(q_GamePivot(t)) * joint" in conv["body_space"]
    assert "GamePivot track + joint position" not in conv["body_space"]
    assert "R(q_p(t)) * joint_p(t)" in conv["pair_space"]
    assert "three partner clips start at -5 deg" in conv["pair_space"]
    tl = conv["pair_timeline"]
    assert "plays its GamePivot motion from there" not in tl
    assert "HOLDS that entry pose" in tl and "0x6b015d" in tl
    assert "RIGID IN THE MASTER NODE'S FRAME" in tl
    assert "whether a non-absolute master's node turns" not in tl
    assert "most, not all" in tl and "authored for the fixed marker" not in tl


def test_anchor_frame_reaches_the_clip_extras_through_the_timeline():
    assert "camera_cuts" in am.CLIP_PAIR_EXTRA_KEYS and "camera_return" in am.CLIP_PAIR_EXTRA_KEYS
    pair = {
        "master_state": "M",
        "partner_state": "P",
        "same_duration": True,
        "primary": True,
        "confidence": "verified",
        "placement": None,
        "timeline": {"anchor_frame": "master node"},
        "camera_cuts": [{"time_s": 0.1, "actor": "partner", "coop_full_screen": True}],
    }
    meta = {
        "clips": {
            "c": {
                "events": [],
                "pairs": [{"pair": 0, "role": "partner", "other_clip": "m", "other_class": "X"}],
            }
        },
        "pairs": [pair],
    }
    (p,) = am.clip_extras(meta, "c")["pairs"]
    assert p["timeline"]["anchor_frame"] == "master node"
    assert p["camera_cuts"][0]["actor"] == "partner"


def test_contact_check_turns_each_body_with_its_game_pivot(tmp_path, monkeypatch):
    import bake_v4

    names = ["GamePivot", "interact", "Bip", "L Hand"]
    for key in ("rsh", "medium"):
        np.savez(
            str(tmp_path / ("bind_%s_file_v1.npz" % key)),
            names=np.array(names, dtype=object),
            Rb=np.tile(np.eye(3), (4, 1, 1)),
            tb=np.zeros((4, 3)),
        )
    quarter = np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]])  # +Z -> +X

    def bake(nm, _step, bind=None, bank=None, track_names=None):
        pal = np.zeros((2, 4, 3, 4))
        pal[:, :, :, :3] = np.eye(3)
        pal[:, 3, :, 3] = [0.0, 0.0, 1.0]  # the hand, 1 m in front, GamePivot-local
        if nm.startswith("RSH"):
            pal[:, 0, :, :3] = quarter
            pal[:, 0, :, 3] = [5.0, 1.0, 0.0]
        return pal, 1.0

    monkeypatch.setattr(bake_v4, "bake", bake)
    cc = am._ContactCheck(str(tmp_path))
    W, _eff = cc._load(str(tmp_path / "RSH_turned.animation"))
    # body joints = Bip and the hand: GamePivot + R(GamePivot) * joint
    assert W[0, 0] == pytest.approx([5.0, 1.0, 0.0])
    assert W[0, 1] == pytest.approx([6.0, 1.0, 0.0])  # not (5, 1, 1)
    # the partner clip is turned by partner_yaw: 180 by default, any yaw on request
    r = cc(
        str(tmp_path / "RSH_turned.animation"), str(tmp_path / "EN1_plain.animation"), (6.0, 1.0)
    )
    # partner hand (0, 0, 1) -> (0, 0, -1) + (6, 0, 1) = (6, 0, 0); master hand (6, 1, 0)
    assert r["closest_m"] == pytest.approx(1.0, abs=1e-3)
    r90 = cc(
        str(tmp_path / "RSH_turned.animation"),
        str(tmp_path / "EN1_plain.animation"),
        (5.0, 0.0),
        yaw_deg=-90.0,
    )
    # R(partner_yaw) = _yaw_rot(90): the partner hand goes to (1, 0, 0) + (5, 0, 0)
    assert r90["closest_m"] == pytest.approx(1.0, abs=1e-3)


# -------------------------------------------------------------- camera cuts
def test_cut_position_is_fixed_and_the_follow_text_is_gone():
    for frame in ("true", "mirrored"):
        cp = fx.cut_placement(frame)
        assert "moved by" not in cp["follow"] and "fixed in the world" in cp["follow"]
        assert "0x633f28" in cp["follow"] and "no caller" in cp["follow"]
        assert "ANIMATION PARTNER" in cp["roots"] and "first cut" in cp["roots"]
        assert "3-D" in cp["side_of_pair"] and "camera node" in cp["side_of_pair"]
        assert "character camera's position" in cp["previous_position"]
        assert "width = height = 0.2" in cp["validity"] and "hard cut" in cp["validity"]
        assert "tried again" in cp["validity"]
        assert "sin(pi n / 2)" in cp["transition"] and "90 degrees" in cp["transition"]
        assert "0.3-wide sweep" in cp["transition"]
        assert "split screen stays" in cp["coop"] and "no master_of" in cp["coop"]
        assert "0.9 s" in cp["return"]
        assert "ROOT node" in cp["look_at"]


def test_cut_shake_is_not_applied_by_the_cut_camera():
    sh = fx._MODIFIERS["cut_shake"]
    assert sh["applied_by_cut_camera"] is False
    assert "return blend" in sh["note"] and "0x643d95" in sh["rule"]


def test_not_established_lists_the_open_camera_points():
    text = fx._NOT_ESTABLISHED
    assert not any("runs in real or in game time" in t for t in text)
    # settled: the transition clock is the script timepassed global (cut_placement.transition)
    assert not any("useRealtime" in t for t in text)
    assert "0xe14304" in fx._CUT_PLACEMENT["transition"]
    assert any("root node follows the capsule" in t for t in text)
    assert any("first cut of a session blends" in t for t in text)


def cut_event(playpos):
    return {
        "event_id": fx.EV_CAMERA_CUT,
        "name": "CAMERA_CUT",
        "trigger_id": am.TRIG_PLAY_POS,
        "trigger": "PLAY_POS",
        "raw": playpos,
        "playpos": playpos,
        "time_s": playpos * 4.0,
        "play_time_s": playpos * 4.0,
    }


def test_bone_18_looks_at_the_root_not_at_a_joint():
    e = cut_event(0.2)
    root = fx._cut(e, {"look_at_bone": 18, "look_at_height_m": 1.2})
    assert root["look_at_joint"] is None and root["look_at_point"] == "root"
    joint = fx._cut(e, {"look_at_bone": 5})
    assert joint["look_at_joint"] == "Pelvis" and joint["look_at_point"] == "joint"


def test_side_shot_height_is_the_midpoint_of_the_two_roots():
    c = dict(distance_m=2.0, height_m=1.0, angle_deg=0.0, look_at_bone=18)
    r = fx.cut_camera(c, [0.0, 0.0, 0.0], [0.0, 1.0, 2.0])
    assert r["position"] == pytest.approx([-2.0, 1.5, 1.0], abs=1e-5)
    assert r["side"] == 1 and r["fallback"] is None
    # roots at one height: as before
    flat = fx.cut_camera(c, [0.0, 0.0, 0.0], [0.0, 0.0, 2.0])
    assert flat["position"] == pytest.approx([-2.0, 1.0, 1.0], abs=1e-5)


def test_kept_position_falls_back_to_the_character_camera():
    c = dict(distance_m=2.0, height_m=1.0, angle_deg=90.0, placement="previous_position")
    a, t = [0.0, 0.0, 0.0], [0.0, 0.0, 2.0]
    assert fx.cut_camera(c, a, t, previous=[9.0, 9.0, 9.0], camera=[1.0, 2.0, 3.0])["position"] == [
        9.0,
        9.0,
        9.0,
    ]
    # no previous cut: the character camera's position, not the angle formula
    kept = fx.cut_camera(c, a, t, camera=[1.0, 2.0, 3.0])
    assert kept["position"] == [1.0, 2.0, 3.0] and kept["fallback"] is None
    with pytest.raises(ValueError):
        fx.cut_camera(c, a, t)
    # in the true frame the camera passed in and the position returned are both true
    assert fx.cut_camera(c, a, t, camera=[1.0, 2.0, 3.0], frame="true")["position"] == [
        1.0,
        2.0,
        3.0,
    ]


def test_angled_cut_reports_the_side_positions_it_falls_back_to():
    c = dict(distance_m=2.0, height_m=1.0, angle_deg=90.0, look_at_bone=18)
    a, t = [0.0, 0.0, 0.0], [0.0, 0.0, 2.0]
    r = fx.cut_camera(c, a, t)
    assert r["position"] == pytest.approx([2.0, 1.0, 0.0], abs=1e-5) and r["side"] is None
    assert r["fallback"] == [[-2.0, 1.0, 1.0], [2.0, 1.0, 1.0]]
    # the first side is the one the camera is on
    cam = fx.cut_camera(c, a, t, camera=[5.0, 2.0, -1.0])
    assert cam["fallback"] == [[2.0, 1.0, 1.0], [-2.0, 1.0, 1.0]]
    # true frame: x of every position negated, in and out
    tr = fx.cut_camera(c, a, t, camera=[-5.0, 2.0, -1.0], frame="true")
    assert tr["position"] == pytest.approx([-2.0, 1.0, 0.0], abs=1e-5)
    assert tr["fallback"] == [[-2.0, 1.0, 1.0], [2.0, 1.0, 1.0]]


def test_halfbell_and_the_real_time_of_a_slow_motion_blend():
    assert fx.halfbell(0.0) == 0.0 and fx.halfbell(1.0) == pytest.approx(1.0)
    assert fx.halfbell(0.5) == pytest.approx(0.5 * math.sin(math.pi / 4.0))
    assert fx.halfbell(-1.0) == 0.0 and fx.halfbell(2.0) == pytest.approx(1.0)
    # Rorschach x Enemy04 Finish_move_WPN_1H, cut 2: 0.07 -> 1 over 0.1 game seconds
    assert fx.blend_real_s(0.1, 0.07, 1.0) == pytest.approx(0.496, abs=1e-3)
    assert fx.blend_real_s(0.1, 1.0, 1.0) == pytest.approx(0.1)
    assert fx.blend_real_s(0.2, 0.5, 0.5) == pytest.approx(0.4)
    assert fx.blend_real_s(0.0, 0.07, 1.0) == 0.0
    assert fx.blend_real_s(0.1, 0.0, 0.0) is None


def test_slow_motion_names_its_basis_and_the_blend_it_leaves_out():
    cuts = [
        {"time_s": 1.0, "time_multiplier": 0.07, "transition_s": 0.1},
        {"time_s": 1.5, "time_multiplier": 0.5, "transition_s": 0.2},
        {"time_s": 4.0, "time_multiplier": 0.25, "transition_s": 0.0},
    ]
    a, b, c = fx.slow_motion(cuts, [{"time_s": 3.0}], end=6.0)
    assert (a["real_s"], a["real_s_basis"], a["blend_s"], a["blend_from_multiplier"]) == (
        round(0.5 / 0.07, 4),
        "no_blend",
        0.1,
        1.0,
    )
    assert (b["blend_s"], b["blend_from_multiplier"]) == (0.2, 0.07)
    # after a return to the character camera the world runs at 1 again
    assert (c["blend_s"], c["blend_from_multiplier"]) == (0.0, 1.0)


def pair_records(master_cuts, partner_cuts, partner_return=None):
    def rec(playposs, ret):
        evs = [cut_event(p) for p in playposs]
        if ret is not None:
            e = cut_event(ret)
            e.update(event_id=fx.EV_CAMERA_RETURN, name="CAMERA_CUT_TO_CHARACTER_CAM")
            evs.append(e)
        return {"events": evs}

    mrec, prec = rec(master_cuts, None), rec(partner_cuts, partner_return)
    args = {}
    for k, e in enumerate(mrec["events"] + prec["events"]):
        if e["event_id"] == fx.EV_CAMERA_CUT:
            args[id(e)] = {
                "transition_s": 0.1 * k,
                "look_at_bone": 18,
                "time_multiplier": 0.5 if k else 1.0,
            }
        else:
            args[id(e)] = {"transition_s": 0.3}
    pair = {
        "timeline": {
            "playpos_per_second": 0.25,
            "start_playpos": 0.0,
            "partner": {"start_playpos": 0.0},
        }
    }
    return pair, mrec, prec, args


def test_pair_takes_the_partners_cuts_when_the_master_has_none():
    pair, mrec, prec, args = pair_records([], [0.25, 0.5], partner_return=0.75)
    fx.pair_fx(am, pair, mrec, prec, args)
    cuts = pair["camera_cuts"]
    assert [(c["time_s"], c["playpos"], c["clip_time_s"]) for c in cuts] == [
        (1.0, 0.25, 1.0),
        (2.0, 0.5, 2.0),
    ]
    assert all(c["actor"] == "partner" and c["coop_full_screen"] is True for c in cuts)
    assert "punish_cam" not in cuts[0]
    assert pair["camera_return"]["actor"] == "partner" and pair["camera_return"]["time_s"] == 3.0
    shots = pair["fx"]["shots"]
    assert [(s["from_s"], s["to_s"], s["ends_with"]) for s in shots] == [
        (1.0, 2.0, "cut"),
        (2.0, 3.0, "return"),
    ]
    # each shot names the blend its real_s leaves out
    assert [(s["real_s_basis"], s["blend_s"], s["blend_from_multiplier"]) for s in shots] == [
        ("no_blend", 0.0, 1.0),
        ("no_blend", 0.1, 1.0),
    ]
    assert fx.counts({"pairs": [pair]})["pair_cuts"] == 2
    assert fx.counts({"pairs": [pair]})["pairs_with_cuts"] == 1


def test_pair_keeps_the_masters_cuts_when_it_has_some():
    pair, mrec, prec, args = pair_records([0.25, 0.5], [0.3, 0.6, 0.9])
    fx.pair_fx(am, pair, mrec, prec, args)
    cuts = pair["camera_cuts"]
    assert [c["playpos"] for c in cuts] == [0.25, 0.5]
    assert all("actor" not in c and "coop_full_screen" not in c for c in cuts)
    assert pair["fx"]["shots"][1]["blend_from_multiplier"] == 1.0
    assert pair["fx"]["shots"][1]["blend_s"] == pytest.approx(0.1)
