"""anim_meta format 2: exe enum names, criteria semantics, event trigger kinds,
transition sync markers and the pair timeline.

Offline: synthetic fragments and clips only (builders shared with
test_anim_meta.py).  Every test here fails on the format-1 module.
"""

import json
import os

import pytest

import anim_meta as am
import anim_state_machine as asm
import engine_enums as ee
from test_anim_meta import Frag, crit, with_criteria, write_clip

RORSCHACH, NITE_OWL, ENEMY_01, BIG_GUY, ENEMY_03 = 1, 2, 3, 4, 6


def state(name="s", **props):
    n = asm.Node(name, asm.CLS_STATE, name)
    n.props = dict(props)
    return n


def event(eid, trigger, pos, caption=""):
    n = asm.Node("e%s_%s_%s" % (eid, trigger, pos), asm.CLS_EVENT, caption)
    n.props = {"m_ianimationevent": eid, "m_ieventtype": trigger, "m_nplaypos": pos}
    return n


def adopt(parent, *kids):
    for k in kids:
        k.parent = parent
        parent.children.append(k)
    return parent


# ------------------------------------------------------------------ enums
def test_enum_tables_carry_the_exe_ids():
    """Ids are read from the registration calls, not guessed from order: PUNCH
    is 1 (a register push), 10 is unassigned, UNUSED is 14."""
    ev = ee.family("ANIMATION_EVENT")
    assert ev[1] == "PUNCH" and ev[14] == "UNUSED" and 10 not in ev and len(ev) == 93
    assert ev[19] == "LEAVE_ABSOLUTE_MODE" and ev[28] == "ABSOLUTE_GOTO_TARGET_POS"
    assert ee.family("OPPONENT_MODEL_TYPE") == {
        0: "NONE",
        1: "RORSCHACH",
        2: "NITE_OWL",
        3: "ENEMY_01",
        4: "ENEMY_02_BIG_GUY",
        5: "UNDERBOSS",
        6: "ENEMY_03",
        7: "ENEMY_04",
    }
    assert ee.family("CHARACTER_TYPES")[24] == "COP_FAST" and ee.family("CHARACTER_TYPES")[0] == (
        "RORSCHACH"
    )
    assert ee.family("ANIMATION_CRITERIA")[2] == "ENUM" and ee.family("ANIMATION_CRITERIA")[12] == (
        "ALL_OF"
    )
    assert ee.family("ANIMATION_EVENT_TYPES") == {
        0: "PLAY_POS",
        1: "ENTER_STATE",
        2: "LEAVE_STATE",
        3: "TOTAL_PLAY_TIME",
    }
    assert ee.family("ANIMATION_SPECIAL_CASE")[3] == "ABSOLUTE_START_AT_CURRENT_POS"
    assert ee.enum_variable_family(11) == "OPPONENT_MODEL_TYPE"
    assert ee.enum_variable_family(5) == "WEAPON_ANIMATION_TYPE"
    assert ee.name("OPPONENT_WEAPON_TYPE", 4294967295) == "NONE", "-1 is stored unsigned"
    assert ee.ident("ANIMATION_VALUE", "TARGET_DIST") == 24
    assert set(ee.event_semantics()) == {str(k) for k in ev}
    assert os.path.getsize(ee._PATH) < 64 * 1024, "shipped table stays small"


# --------------------------------------------------------------- criteria
def test_enum_11_filters_whatever_the_stale_value_slot_says():
    """AnimationCriteriaMet 0x5c5781 reads only the enum variable and its value
    for an ENUM criterion.  Format 1 skipped enum-11 criteria whose
    m_ianimationvalue was 14 or 23 (7 shipped ones) and so kept pairs the game
    rules out."""
    for slot in (0, 4, 14, 23):
        st = with_criteria(state(), crit("ENEMY_02_BIG_GUY", value=BIG_GUY, var=slot))
        assert am.accepts_partner(st, BIG_GUY) and not am.accepts_partner(st, RORSCHACH), slot
    neg = with_criteria(state(), crit("NOT NITE_OWL", value=NITE_OWL, var=14, neg=True))
    assert am.accepts_partner(neg, RORSCHACH) and not am.accepts_partner(neg, NITE_OWL)


def test_any_of_with_a_branch_about_something_else_does_not_rule_out():
    """`ANY OF(BASH_1H | ALL OF(BASH_2H, ENEMY_03))` on the heroes' 1H disarm:
    the weapon branch may hold for any opponent, so the state is not limited to
    ENEMY_03.  Format 1 dropped the branch it had no opinion on and lost the
    disarm pairs."""
    tree = crit(
        "ANY OF",
        kind=11,
        kids=[
            crit("BASH_1H", enum=12, value=0),
            crit("ALL OF", kind=12, kids=[crit("BASH_2H", enum=12, value=1), crit("EN3", value=6)]),
        ],
    )
    st = with_criteria(state(), tree)
    assert am.accepts_partner(st, ENEMY_01) and am.accepts_partner(st, ENEMY_03)
    # ...and with the opponent known, the weapon the branch leaves is exact
    assert am.allowed_enum_names(st, am.VAR_OPPONENT_WEAPON, env={11: ENEMY_01}) == ["BASH_1H"]
    assert am.allowed_enum_names(st, am.VAR_OPPONENT_WEAPON, env={11: ENEMY_03}) == [
        "BASH_1H",
        "BASH_2H",
    ]
    # an ALL_OF is still ruled out by one failing branch, an ANY_OF by all
    allof = with_criteria(
        state(), crit("ALL OF", kind=12, kids=[crit("w", enum=12, value=0), crit("E", value=6)])
    )
    assert not am.accepts_partner(allof, ENEMY_01)
    anyof = with_criteria(
        state(), crit("ANY OF", kind=11, kids=[crit("a", value=3), crit("b", value=6)])
    )
    assert not am.accepts_partner(anyof, RORSCHACH)


def test_criteria_filed_directly_under_a_state_are_read():
    """73 shipped states carry their criteria as direct children, with no
    `Criterias` folder; format 1 reported them as having none."""
    st = adopt(state(), crit("RORSCHACH", value=RORSCHACH))
    assert am.accepts_partner(st, RORSCHACH) and not am.accepts_partner(st, NITE_OWL)
    assert am.state_record(st)["criteria"] == ["RORSCHACH"]


def test_criteria_records_are_named_from_the_exe():
    c = crit("NONE", enum=12, value=4294967295)
    assert am.criteria_record(c) == {
        "text": "NONE",
        "kind": "ENUM",
        "kind_id": 2,
        "variable": "OPPONENT_WEAPON_TYPE",
        "variable_id": 12,
        "value": "NONE",
        "value_id": -1,
    }
    v = crit("SPEED less than 0.01", kind=0, var=1)
    v.props.update(m_iintervaltype=1, m_nintervalmin="0.01", m_nintervalmax="0")
    r = am.criteria_record(v)
    assert (r["kind"], r["variable"], r["variable_id"]) == ("VALUE", "SPEED", 1)
    assert r["interval"] == {"type": "LESS_THAN", "min": 0.01, "max": 0.0}
    a = crit("NOT ACTION INITIAL_ATTACK", kind=1, neg=True)
    a.props["m_ianimationaction"] = 21
    r = am.criteria_record(a)
    assert r["action"] == "INITIAL_ATTACK" and r["not"] is True
    tree = am.criteria_record(crit("ANY OF", kind=11, kids=[crit("ENEMY_01", value=3)]))
    assert tree["kind"] == "ANY_OF" and tree["children"][0]["value"] == "ENEMY_01"
    assert tree["children"][0]["variable"] == "OPPONENT_MODEL_TYPE"


def test_pair_weapons_reads_own_and_opponent_weapon_criteria():
    m = with_criteria(
        state("Counter_1H"),
        crit("BASH_1H", enum=5, value=1),
        crit("NONE", enum=12, value=2**32 - 1),
    )
    p = with_criteria(state("Countered"), crit("RORSCHACH", value=1))
    w = am.pair_weapons(m, p, RORSCHACH, ENEMY_01)
    assert w["master_weapon"] == ["BASH_1H"] and w["partner_weapon"] == ["UNARMED"]
    assert w["master_requires_partner"] == ["NONE"] and w["partner_own"] is None
    # a group above the state counts too
    g = asm.Node("g", asm.CLS_GROUP, "Armed")
    with_criteria(g, crit("NOT UNARMED", enum=5, value=0, neg=True))
    q = state("q")
    adopt(g, q)
    assert am.allowed_enum_names(q, am.VAR_WEAPON) == ["BASH_1H", "BASH_2H"]
    assert am.allowed_enum_names(q, am.VAR_WEAPON, with_groups=False) is None
    assert am.pair_weapons(state(), state())["master_weapon"] is None


# ------------------------------------------------------------------ events
def test_event_records_carry_trigger_kind_and_time_unit():
    """m_ieventtype: 0 PLAY_POS, 1 ENTER_STATE, 2 LEAVE_STATE, 3 TOTAL_PLAY_TIME
    (CheckPlayPosEvents 0x5b51f3).  A TOTAL_PLAY_TIME event's m_nplaypos is
    seconds; format 1 presented all of them as a 0..1 play position."""
    st = adopt(
        state(),
        event(28, 3, 0.2),  # the victim's ABSOLUTE_GOTO_TARGET_POS: 0.2 SECONDS
        event(56, 0, 0.25),
        event(39, 1, 0.7),  # ENTER_STATE events ship with a stale m_nplaypos
        event(19, 2, 0.0),
        event(85, 3, 8.04),  # later than one pass of the clip
    )
    ev = {e["name"]: e for e in am._events(st, duration=4.0, basis="clip duration")}
    g = ev["ABSOLUTE_GOTO_TARGET_POS"]
    assert (g["trigger"], g["time_unit"], g["time_s"], g["raw"]) == (
        "TOTAL_PLAY_TIME",
        "seconds",
        0.2,
        0.2,
    )
    assert g["playpos"] == pytest.approx(0.05), "0.2 s of a 4 s clip, not 20 % of it"
    i = ev["IMPACT_EFFECTS"]
    assert (i["trigger"], i["time_unit"], i["playpos"], i["time_s"]) == (
        "PLAY_POS",
        "playpos",
        0.25,
        1.0,
    )
    e = ev["GOT_UP"]
    assert e["on_enter"] is True and (e["playpos"], e["time_s"], e["raw"]) == (0.0, 0.0, 0.7)
    lv = ev["LEAVE_ABSOLUTE_MODE"]
    assert lv["trigger"] == "LEAVE_STATE" and lv["on_leave"] is True
    assert lv["playpos"] is None and lv["time_s"] is None and lv["on_enter"] is False
    d = ev["DIE"]
    # review B1: past the end of the clip there is no position on it, only a time
    assert d["play_time_s"] == 8.04 and d["playpos"] is None and d["time_s"] is None
    # order: on enter, then by time, state-leave last
    assert [x["trigger_id"] for x in am._events(st, duration=4.0)] == [1, 3, 0, 3, 2]
    # without a duration the stored unit is still told apart
    n = {e["name"]: e for e in am._events(st)}
    assert n["ABSOLUTE_GOTO_TARGET_POS"]["playpos"] is None
    assert n["ABSOLUTE_GOTO_TARGET_POS"]["time_s"] == 0.2
    assert n["IMPACT_EFFECTS"]["time_s"] is None and n["IMPACT_EFFECTS"]["playpos"] == 0.25


def test_event_names_are_the_exes_and_caption_conflicts_are_kept():
    a = event(14, 0, 0.5, "{event WALK_CYCLE_POINT at pos 0.5}")
    b = event(6, 0, 0.1, "{event FOOTSTEP at pos 0.1}")
    c = event(6, 0, 0.6, "{event LEFT_FOOT_DOWN at pos 0.6}")
    d = event(42, 0, 0.3)
    st = adopt(state(), a, b, c, d)
    ev = am._events(st)
    assert [e["name"] for e in ev] == [
        "LEFT_FOOT_DOWN",
        "NO_LONGER_IMMUNE_TO_ATTACK",
        "UNUSED",
        "LEFT_FOOT_DOWN",
    ]
    assert ev[0]["caption_name"] == "FOOTSTEP" and ev[2]["caption_name"] == "WALK_CYCLE_POINT"
    assert "caption_name" not in ev[3] and "caption_name" not in ev[1]
    chk = am.event_name_check([a, b, c, d])
    assert chk["agree"] == 0
    assert {(x["event_id"], x["exe"], x["caption"], x["uses"]) for x in chk["conflicts"]} == {
        (14, "UNUSED", "WALK_CYCLE_POINT", 1),
        (6, "LEFT_FOOT_DOWN", "FOOTSTEP", 1),
    }
    assert 42 in chk["exe_only"] and 6 not in chk["exe_only"]


# ------------------------------------------------------------- transitions
def trans(name="{trans to Run}", **props):
    n = asm.Node("t" + name, asm.CLS_TRANS, name)
    n.props = dict(props)
    return n


def test_sync_markers_are_sorted_and_stop_at_the_first_unset_local():
    """UpdateSuperSync 0x5fa582: pairs in order until the first local < 0 (the
    remote value is not looked at), then sorted by local."""
    t = trans(
        m_tsupersyncpos=True,
        m_nsupersynclocal1=0.33,
        m_nsupersyncremote1=0.57,
        m_nsupersynclocal2=0.17,
        m_nsupersyncremote2=-1.0,
        m_nsupersynclocal3=-1.0,
        m_nsupersyncremote3=0.9,
        m_nsupersynclocal4=0.8,
        m_nsupersyncremote4=0.9,
    )
    assert am.sync_markers(t) == [(0.17, -1.0), (0.33, 0.57)]
    # keys written by an extractor older than the name-hash fix still work
    old = trans(key_ee2a40a0=0.6, key_4cadfb2b=0.15, key_ee2a4060=[1.0, 9.1e7, -1.0])
    old.props["key_4cadfbeb"] = 0.41
    assert am.sync_markers(old) == [(0.6, 0.15), (1.0, 0.41)]


def test_transition_record_gives_gate_and_start_rule():
    run = state("Run")
    run.id = "run"
    owner = state("Run Start")
    t = trans(
        m_etostate={"ref": "run"},
        m_tsupersyncpos=True,
        m_nsupersynclocal1=1.0,
        m_nsupersyncremote1=0.35,
        m_nsupersynclocal2=0.83,
        m_nsupersyncremote2=0.23,
        m_toverrideeasein=True,
        m_neaseinduration=0.15,
    )
    r = am.transition_record(t, owner, {"run": run})
    assert r["to"] == "Run" and r["to_kind"] == "state" and r["owner_kind"] == "state"
    assert r["ease_in_override_s"] == 0.15 and "fallback" not in r
    assert r["start"] == {
        "rule": "sync_markers",
        "markers": [[0.83, 0.23], [1.0, 0.35]],
        "gate": [0.83, 1.0],
    }
    # engine map (TransitionPlayPos 0x5ac1aa): linear inside, CLAMPED outside --
    # no implicit (0,0) / (1,1) end points
    assert am.transition_start(r, 0.915) == pytest.approx(0.29)
    assert am.transition_start(r, 0.5) == pytest.approx(0.23)
    assert am.transition_start(r, 1.0) == pytest.approx(0.35)
    # Override Start PlayPos wins over the markers
    t.props.update(m_toverrideplaypos=True, m_nplaypos=0.4)
    r = am.transition_record(t, owner, {"run": run})
    assert r["start"] == {"rule": "override_playpos", "playpos": 0.4}
    assert am.transition_start(r, 0.9) == 0.4
    # neither: the transition has no opinion
    plain = am.transition_record(trans(m_tfallback=True), owner, {})
    assert "start" not in plain and plain["fallback"] is True and plain["to"] is None
    assert am.transition_start(plain, 0.9) is None
    assert [x["rule"] for x in am.TRANSITION_START_PRIORITY] == [
        "override_playpos",
        "sync_markers",
        "walk_cycle_carry_over",
        "target_default",
        "reentry",
    ]


# ---------------------------------------------------------------- timeline
def _rec(absolute, special, ease=0.21, events=(), **kw):
    st = adopt(
        state(
            m_tisabsoluteanimation=absolute,
            m_ispecialhandling=special,
            m_neaseinduration=ease,
            **kw,
        ),
        *events,
    )
    return am.state_record(st)


def test_timeline_victim_holds_its_pose_until_the_goto_event_then_blends():
    """Special handling 3: the victim enters at its own pose; the anchor is
    applied from ABSOLUTE_GOTO_TARGET_POS (0.2 SECONDS), eased in over the
    state's ease-in, and dropped at the first LEAVE_ABSOLUTE_MODE."""
    counter = asm.Node("c", asm.CLS_CRIT, "c")  # ACTION 12: the type is computed (0x5f277a)
    counter.props = {"m_ianimationcriteria": 1, "m_ianimationaction": 12}
    master = _rec(False, 6, events=[counter], m_imasterof=10, m_ianimationtype=0)
    victim = _rec(True, 3, events=[event(28, 3, 0.2), event(19, 0, 0.5), event(19, 2, 0.0)])
    t = am.pair_timeline(master, victim, vf={"duration_s": 4.0})
    assert t["master"] == {
        "absolute": False,
        "snapped": False,
        "special_handling": {"id": 6, "name": "BULL_MOVE"},
        "animation_type": {"id": 8, "name": "COUNTERATTACK"},
        "speed": 1.0,
        "duration_s": None,
        "start_playpos": 0.0,
        "start_basis": "state_default",
        "entry_alternatives": [],
    }
    p = t["partner"]
    assert p["follows_master_playpos"] is True and t["playpos_per_second"] == 0.25
    assert p["special_handling"] == {"id": 3, "name": "ABSOLUTE_START_AT_CURRENT_POS"}
    assert p["anchored_from_start"] is False
    # follow-up: the pair runs on the master's clock (here: no master clip known,
    # so 1 / the partner's 4 s), which gives the 0.2 s event a play position
    assert p["goto_target"] == {"time_s": 0.2, "playpos": 0.05, "trigger": "TOTAL_PLAY_TIME"}
    assert p["blend_s"] == 0.21 and p["anchored_from_s"] == pytest.approx(0.41)
    assert p["release"] == {"time_s": 2.0, "playpos": 0.5, "trigger": "PLAY_POS"}
    victim = _rec(True, 3, events=[event(28, 3, 0.2), event(19, 3, 2.0)])
    p = am.pair_timeline(master, victim)["partner"]
    assert [(x["mode"], x["from_s"], x["to_s"]) for x in p["phases"]] == [
        ("own_entry_pose", 0.0, 0.2),
        ("blend_to_anchor", 0.2, 0.41),
        ("anchored", 0.41, 2.0),
        ("released", 2.0, None),
    ]


def test_timeline_special_handling_zero_is_anchored_from_the_start():
    """goto_phys_absolute_mode 0x68a79f passes flag = (Special handling == 0)."""
    master = _rec(False, 6, m_imasterof=11)
    p = am.pair_timeline(master, _rec(True, 0, ease=0.1))["partner"]
    assert p["anchored_from_start"] is True and p["goto_target"]["time_s"] == 0.0
    assert p["goto_target"]["trigger"] == "STATE_ENTRY_FLAG" and p["release"] is None
    assert [(x["mode"], x["from_s"], x["to_s"]) for x in p["phases"]] == [
        ("blend_to_anchor", 0.0, 0.1),
        ("anchored", 0.1, None),
    ]
    # special handling 3 with no goto event: never anchored
    p = am.pair_timeline(master, _rec(True, 3))
    assert p["partner"]["goto_target"] is None and p["partner"]["anchored_from_s"] is None
    assert [x["mode"] for x in p["partner"]["phases"]] == ["own_entry_pose"]
    assert p["anchor_rotation_unverified"] is False
    # a slave state that is not an absolute animation is not placed at all
    p = am.pair_timeline(master, _rec(False, 2))["partner"]
    assert [x["mode"] for x in p["phases"]] == ["not_absolute"] and p["blend_s"] is None


def test_timeline_flags_a_master_that_turns_inside_the_anchored_window():
    """The anchor is rotated by the master's live node; whether that node turns
    with the GamePivot is not established, so such pairs are flagged."""
    master = _rec(False, 1, m_imasterof=1)
    victim = _rec(True, 3, ease=0.2, events=[event(28, 3, 0.2), event(19, 3, 1.0)])
    pl = {"partner_offset_xz": [0.0, 1.0]}
    still = {"duration_s": 2.0, "_gp_yaw_deg": [0.0] * 5, "_gp_pos": [[0, 1, 0]] * 5}
    t = am.pair_timeline(master, victim, still, {"duration_s": 2.0}, pl)
    assert t["anchor_rotation_unverified"] is False and t["master_yaw_change_deg"] == 0.0
    assert t["master_yaw_window_s"] == [0.2, 1.0] and t["anchor_drift_if_master_turns_m"] == 0.0
    # turns 180 degrees over the clip: 90 by the release at 1.0 s
    turn = dict(still, _gp_yaw_deg=[0.0, 45.0, 90.0, 135.0, 180.0])
    t = am.pair_timeline(master, victim, turn, {"duration_s": 2.0}, pl)
    assert t["anchor_rotation_unverified"] is True
    assert t["master_yaw_change_deg"] == pytest.approx(90.0)
    assert t["anchor_drift_if_master_turns_m"] == pytest.approx(2**0.5, abs=1e-3)
    # the turn happens only AFTER the victim is released: not flagged
    late = dict(still, _gp_yaw_deg=[0.0, 0.0, 0.0, 90.0, 180.0])
    t = am.pair_timeline(master, victim, late, {"duration_s": 2.0}, pl)
    assert t["anchor_rotation_unverified"] is False and t["master_yaw_change_deg"] == 0.0
    # no clip data for the master: unknown, not "verified"
    t = am.pair_timeline(master, victim, None, {"duration_s": 2.0}, pl)
    assert t["anchor_rotation_unverified"] is None


# ------------------------------------------------------------------- build
@pytest.fixture
def extract2(tmp_path):
    """Hero master `Counter` (master of 10) with a transition that syncs; the
    enemy files an absolute slave with the shipped event pattern."""
    h = Frag()
    g = h.add("AnimationStateGroupWM", "Counters")
    s = h.state("Counter_A", g, "RSH_COM_ATT_counter_EN1_A", m_imasterof=10, m_ispecialhandling=6)
    f = h.add("Folder", "Criterias", s)
    h.add(
        "AnimationCriteriaWM",
        "{criteria: ENEMY_01}",
        f,
        m_ianimationcriteria=2,
        m_ianimationenum=11,
        m_ianimationenumvalue=ENEMY_01,
        m_ianimationvalue=23,
    )
    h.add(
        "AnimationCriteriaWM",
        "{criteria: BASH_1H}",
        f,
        m_ianimationcriteria=2,
        m_ianimationenum=5,
        m_ianimationenumvalue=1,
    )
    idle = h.state("Idle", g, "RSH_COM_MOV_idle", m_tiswalkcycle=True)
    tf = h.add("Folder", "Transitions", s)
    h.add(
        "AnimationTransitionWM",
        "{trans to Idle}",
        tf,
        m_etostate={"ref": idle},
        m_tsupersyncpos=True,
        m_nsupersynclocal1=1.0,
        m_nsupersyncremote1=0.5,
        m_nsupersynclocal2=0.5,
        m_nsupersyncremote2=0.0,
        m_nsupersynclocal3=-1.0,
    )
    h.write(tmp_path, "Rorschach")

    for cname, ctype in (("Enemy01", ENEMY_01), ("EnemyBig", BIG_GUY)):
        e = Frag()
        root = e.add("AnimationClassWM", cname + "AnimationClass", m_ianimationmodeltype=ctype)
        sl = e.add("Folder", "SlaveStates", root)
        v = e.state(
            "Countered_by_RSH_A",
            sl,
            "EN1_COM_DMG_counter_RSH_A",
            m_istateid=10,
            m_tisabsoluteanimation=True,
            m_ispecialhandling=3,
            m_neaseinduration=0.21,
        )
        ev = e.add("Folder", "Events", v)
        for eid, trig, pos in ((28, 3, 0.2), (19, 0, 0.5), (4, 0, 0.3)):
            e.add(
                "AnimationEventWM", "", ev, m_ianimationevent=eid, m_ieventtype=trig, m_nplaypos=pos
            )
        e.write(tmp_path, cname)

    write_clip(tmp_path, "RSH_COM_ATT_counter_EN1_A", ((0, 1, 0), (0, 1, 0.5)), ((0, 0, 1.2),) * 2)
    write_clip(tmp_path, "EN1_COM_DMG_counter_RSH_A", ((0, 1, -1.2), (0, 1, -1.5)))
    return tmp_path


def test_build_format_2_keeps_v1_fields_and_adds_the_new_tables(extract2):
    m = am.build(str(extract2))
    assert m["format"] == "watchmen-anim-meta/2"
    # the enemy the master's (stale-slot) criterion rules out gets no pair
    assert [(p["partner_class"], p["primary"]) for p in m["pairs"]] == [("Enemy01", True)]
    p = m["pairs"][0]
    for k in (
        "master_class master_state master_path master_clip master_of master_criteria "
        "partner_class partner_state partner_path partner_clip partner_criteria "
        "master_duration_s partner_duration_s same_duration placement confidence primary"
    ).split():
        assert k in p, k
    assert p["placement"]["partner_start_xz"] == [0.0, 1.2]
    assert p["weapons"]["master_weapon"] == ["BASH_1H"] and p["weapons"]["partner_weapon"] is None
    t = p["timeline"]
    assert t["partner"]["goto_target"] == {
        "time_s": 0.2,
        "playpos": 0.1,
        "trigger": "TOTAL_PLAY_TIME",
    }
    assert t["partner"]["release"]["time_s"] == pytest.approx(1.0)
    assert t["anchor_rotation_unverified"] is False and t["master_yaw_change_deg"] == 0.0
    # classes: model type named from the exe, states carry the structured criteria
    c = m["classes"]
    assert (c["Enemy01"]["character_type"], c["Enemy01"]["character_type_id"]) == ("ENEMY_01", 3)
    assert (c["Rorschach"]["character_type"], c["Rorschach"]["character_type_id"]) == (
        "RORSCHACH",
        1,
    )
    st = c["Rorschach"]["states"][0]
    assert st["criteria"] == ["ENEMY_01", "BASH_1H"] and st["weapon"] == ["BASH_1H"]
    assert st["criteria_tree"][0]["variable"] == "OPPONENT_MODEL_TYPE"
    assert st["special_handling"] == {"id": 6, "name": "BULL_MOVE"} and st["duration_s"] == 2.0
    (tr,) = c["Rorschach"]["transitions"]
    assert tr["owner"].endswith("Counters/Counter_A") and tr["to"].endswith("Counters/Idle")
    assert tr["start"]["markers"] == [[0.5, 0.0], [1.0, 0.5]] and tr["start"]["gate"] == [0.5, 1.0]
    # the victim's events, per state and per clip, in both units
    ve = {e["name"]: e for e in c["Enemy01"]["states"][0]["events"]}
    assert ve["ABSOLUTE_GOTO_TARGET_POS"]["time_unit"] == "seconds"
    assert ve["IMPACT"]["time_s"] == pytest.approx(0.6)
    ce = m["clips"]["EN1_COM_DMG_counter_RSH_A"]["events"]
    assert [e["name"] for e in ce] == ["ABSOLUTE_GOTO_TARGET_POS", "IMPACT", "LEAVE_ABSOLUTE_MODE"]
    # top-level reference tables
    assert m["enums"]["ANIMATION_EVENT"]["28"] == "ABSOLUTE_GOTO_TARGET_POS"
    assert m["enum_variables"]["11"] == {
        "name": "OPPONENT_MODEL_TYPE",
        "values": "OPPONENT_MODEL_TYPE",
    }
    sem = m["event_semantics"]["28"]
    assert sem["name"] == "ABSOLUTE_GOTO_TARGET_POS" and sem["evidence"].startswith("read from")
    assert m["transition_start_priority"][0]["rule"] == "override_playpos"
    for k in ("pair_timeline", "transition_start", "evidence", "criteria", "names"):
        assert k in m["conventions"], k
    assert "seconds" in m["conventions"]["playpos"]
    json.dumps(m)  # private per-key series must not leak into the table
    assert not [k for e in m["clips"].values() for k in e if k.startswith("_")]


def test_clip_extras_carry_trigger_times_and_the_pair_timeline(extract2):
    m = am.build(str(extract2))
    x = am.clip_extras(m, "EN1_COM_DMG_counter_RSH_A", fps=10.0, frames=11)  # written at 1 s
    ev = {e["name"]: e for e in x["events"]}
    g = ev["ABSOLUTE_GOTO_TARGET_POS"]
    assert g["trigger"] == "TOTAL_PLAY_TIME" and g["time_s"] == 0.2 and g["playpos"] == 0.1
    assert g["written_time_s"] == pytest.approx(0.1)
    assert ev["LEAVE_ABSOLUTE_MODE"]["time_s"] == pytest.approx(1.0)
    assert ev["LEAVE_ABSOLUTE_MODE"]["written_time_s"] == pytest.approx(0.5)
    (pr,) = x["pairs"]
    assert pr["role"] == "partner" and pr["timeline"]["partner"]["blend_s"] == 0.21
    assert pr["weapons"]["master_weapon"] == ["BASH_1H"]
    # a format-1 table (no time_unit) is still served the format-1 way
    old = {
        "clips": {"c": {"duration_s": 2.0, "events": [{"name": "HIT", "playpos": 0.5}]}},
        "pairs": [],
    }
    assert am.clip_extras(old, "c")["events"][0]["time_s"] == pytest.approx(1.0)


def test_clip_facts_keeps_private_root_motion_series(extract2):
    f = am.clip_facts(am.find_clips(str(extract2))["rsh_com_att_counter_en1_a"])
    assert f["_gp_yaw_deg"] == [0.0] and len(f["_gp_pos"]) == f["key_count"]
    assert am._unwrap([170.0, -170.0, -150.0]) == [170.0, 190.0, 210.0]
    assert am._sample([0.0, 10.0, 20.0], 0.25) == pytest.approx(5.0)


# ------------------------------------------------------- nested fragments
def _write_frag(root, name, frag):
    d = root / "extracted" / "TNT" / "CharacterAnimation"
    d.mkdir(parents=True, exist_ok=True)
    j = {"instances": [frag.cls], "nodes_full": frag.nodes}
    (d / (name + ".fragment.json")).write_text(json.dumps(j))


@pytest.fixture
def nested(tmp_path):
    """A class whose `Movement` group instances a nested fragment twice-removed
    from the root.  The nested fragment's TOP-LEVEL nodes -- a state, a group
    and a `Group Transitions` folder -- are the host group's children."""
    sub = Frag()
    strafe = sub.state("Strafe", None, "EN1_COM_MOV_strafe_left_long")
    sub.nodes[0]["props"].append(["logicalParent", "ref", {"etag": 2}])
    g = sub.add("AnimationStateGroupWM", "Run Start")
    run = sub.state("Run Start Left Foot", g, "EN1_COM_MOV_run_start_left_foot")
    # a blend tree: slots are captioned with their blend position
    lay = [n for n in sub.nodes if n["props"][0][2] == "{MOTION_LAYER_1}"][-1]["id"]
    sub.add("AnimationSlotWM", "{pos 1, EN1_COM_ATT_dash_cycle.animation}", lay, m_nweight=1.0)
    gt = sub.add("Folder", "Group Transitions")
    sub.add("AnimationTransitionWM", "{trans to Strafe}", gt, m_etostate={"ref": strafe})
    tf = sub.add("Folder", "Transitions", run)
    sub.add("AnimationTransitionWM", "{trans to Strafe}", tf, m_etostate={"ref": strafe})
    _write_frag(tmp_path, "Enemy01Movement", sub)

    h = Frag()
    root = h.add("AnimationClassWM", "Enemy1AnimationClass", m_ianimationmodeltype=ENEMY_01)
    # same node id as `Strafe` has inside the nested fragment (ids are per fragment)
    assert root == strafe
    host = h.add(
        "AnimationStateGroupWM",
        "EnemyMovement",
        root,
        assetName="/TNT/CharacterAnimation/Enemy01Movement.fragment",
    )
    h.state("Dead", root, "EN1_COM_DMG_dead")
    ct = h.add("Folder", "Group Transitions", root)
    h.add(
        "AnimationTransitionWM",
        "{trans to Strafe}",
        ct,
        m_etostate={"xref": ["ffff", host, strafe]},
    )
    _write_frag(tmp_path, "AnimationClassEnemy01", h)
    return tmp_path


def test_nested_fragment_top_level_nodes_are_kept(nested):
    """asm.load_tree splices only the CHILDREN of a nested fragment's roots, so
    the roots themselves -- states such as Strafe, Run, Walk, 126 of them in the
    shipped classes -- vanished from format 1 and their transitions and events
    hung off the host group."""
    m = am.build(str(nested))
    st = {s["name"]: s for s in m["classes"]["Enemy01"]["states"]}
    assert set(st) == {"Dead", "Strafe", "Run Start Left Foot"}
    assert st["Strafe"]["path"] == "Enemy1AnimationClass/EnemyMovement/Strafe"
    assert st["Run Start Left Foot"]["path"].endswith("EnemyMovement/Run Start/Run Start Left Foot")
    assert st["Strafe"]["main_clip"] == "EN1_COM_MOV_strafe_left_long"
    # "pos N, " is the slot's blend position, not part of the clip name
    assert [c["clip"] for c in st["Run Start Left Foot"]["clips"]] == [
        "EN1_COM_MOV_run_start_left_foot",
        "EN1_COM_ATT_dash_cycle",
    ]
    assert "EN1_COM_ATT_dash_cycle" in m["clips"] and not [c for c in m["clips"] if "pos" in c]


def test_transition_targets_resolve_through_fragment_instances(nested):
    """Node ids are unique only inside one fragment: a reference is looked up
    next to the node that makes it, an xref path walked instance by instance."""
    tr = am.build(str(nested))["classes"]["Enemy01"]["transitions"]
    strafe = "Enemy1AnimationClass/EnemyMovement/Strafe"
    # follow-up: the transition filed under the CLASS is not listed -- a transition
    # registers only with a state or a state group (AddToClosestState); xref paths
    # are covered in test_followup.py
    assert sorted((t["owner"], t["owner_kind"]) for t in tr) == [
        ("Enemy1AnimationClass/EnemyMovement", "group"),  # the nested Group Transitions
        ("Enemy1AnimationClass/EnemyMovement/Run Start/Run Start Left Foot", "state"),
    ]
    assert all(t["to"] == strafe and t["to_kind"] == "state" for t in tr), [t["to"] for t in tr]
