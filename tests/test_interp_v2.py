"""Interpreter v2: behaviour read from SetupNewPage 0x5b7788 / UpdatePagePlayPos
0x5b56a9 / TransitionPlayPos 0x5ac1aa and friends.  Synthetic trees only."""

import os, sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_state_machine as asm

_n = [0]


def node(cls, name, parent=None, **props):
    _n[0] += 1
    n = asm.Node("n%d" % _n[0], cls, name)
    n.props = dict(props)
    if parent is not None:
        n.parent = parent
        parent.children.append(n)
    return n


def state(parent, name, dur=1.0, clips=None, **props):
    s = node(asm.CLS_STATE, name, parent, **props)
    b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
    for i, (clip, d) in enumerate(clips or [(name + ".animation", dur)]):
        node(asm.CLS_SLOT, clip, b, m_sduration="%f s" % d, targetAnimation=clip)
    return s


def trans(owner, target, **props):
    return node(asm.CLS_TRANS, "{trans}", owner, m_etostate={"ref": target.id}, **props)


def crit_value(owner, idx, lo, hi):
    return node(
        asm.CLS_CRIT,
        "{crit}",
        owner,
        m_ianimationcriteria=asm.CRIT_VALUE,
        m_ianimationvalue=idx,
        m_iintervaltype=0,
        m_nintervalmin=lo,
        m_nintervalmax=hi,
    )


def machine():
    root = node(asm.CLS_CLASS, "class")
    return root


def sync_trans(markers, flag=True):
    t = asm.Node("t", asm.CLS_TRANS, "t")
    t.props["m_tsupersyncpos"] = flag
    for i, (l, r) in enumerate(markers, 1):
        t.props["m_nsupersynclocal%d" % i] = l
        t.props["m_nsupersyncremote%d" % i] = r
    return t


# ------------------------------------------------------------------ sync markers


def test_sync_marker_key_names():
    assert asm.SYNC_LOCAL[0] == "m_nsupersynclocal1" and asm.SYNC_REMOTE[7] == "m_nsupersyncremote8"
    assert len(asm.SYNC_LOCAL) == len(asm.SYNC_REMOTE) == 8


def test_sync_remap_clamps_outside_the_markers():
    t = sync_trans([(0.75, 0.24), (1.0, 0.48)])
    assert asm.sync_remap(0.5, t) == 0.24  # old code: 0.16 through an implicit (0,0)
    assert abs(asm.sync_remap(0.875, t) - 0.36) < 1e-9
    assert asm.sync_remap(1.0, t) == 0.48
    assert asm.sync_window(t) == (0.75, 1.0)


def test_sync_markers_sorted_and_stop_at_first_negative_local():
    t = sync_trans([(0.33, 0.57), (0.17, 0.42), (-1.0, 0.9), (0.9, 0.1)])
    assert asm.sync_markers(t) == [(0.17, 0.42), (0.33, 0.57)]
    # remote is not tested
    assert asm.sync_markers(sync_trans([(0.2, -1.0)])) == [(0.2, -1.0)]
    assert asm.sync_markers(sync_trans([(0.2, 0.3)], flag=False)) == []


def test_transition_playpos_priority():
    t = sync_trans([(0.0, 1.0), (1.0, 0.0)])
    assert abs(asm.transition_playpos(t, 0.25) - 0.75) < 1e-9
    t.props["m_toverrideplaypos"], t.props["m_nplaypos"] = True, 0.4
    assert asm.transition_playpos(t, 0.25) == 0.4
    assert asm.transition_playpos(sync_trans([], flag=False), 0.25) == -1.0


def test_sync_transition_only_fires_inside_the_marker_window():
    root = machine()
    a = state(root, "A", dur=1.0, m_tislooping=True)
    b = state(root, "B", dur=1.0)
    t = trans(a, b, m_tsupersyncpos=True)
    t.props.update(m_nsupersynclocal1=0.5, m_nsupersyncremote1=0.1)
    t.props.update(m_nsupersynclocal2=0.8, m_nsupersyncremote2=0.4)
    it = asm.Interpreter(root)
    it.transit(a)
    for _ in range(4):  # playpos 0.1 .. 0.4: outside the window
        it.tick(0.1)
        assert it.page.state is a
    it.tick(0.1)  # evaluated at 0.4 -> still A, now 0.5
    assert it.page.state is a
    it.tick(0.1)  # evaluated at 0.5: inside
    assert it.page.state is b
    assert ("transit", "B", 0.0, 0.1) in it.log


# ------------------------------------------------------------------ page setup


def test_ease_override_ignored_when_target_ease_is_zero():
    root = machine()
    a = state(root, "A")
    b = state(root, "B", m_neaseinduration=0.0)
    c = state(root, "C", m_neaseinduration=0.5)
    it = asm.Interpreter(root)
    it.transit(a)
    pg = it.transit(b, trans(a, b, m_toverrideeasein=True, m_neaseinduration=0.3))
    assert pg.ease_in == 0.0 and pg.raw == 1.0
    pg = it.transit(c, trans(b, c, m_toverrideeasein=True, m_neaseinduration=0.3))
    assert pg.ease_in == 0.3 and pg.raw == 0.0
    pg = it.transit(a, trans(c, a, m_toverrideeasein=True, m_neaseinduration=0.0))
    assert pg.ease_in == 0.0


def test_first_body_page_is_instant():
    root = machine()
    a = state(root, "A", m_neaseinduration=0.5)
    it = asm.Interpreter(root)
    assert it.transit(a).blend == 1.0


def test_same_state_on_top_creates_no_page_unless_allowed():
    root = machine()
    a = state(root, "A")
    m = state(root, "M", m_tallowmultipleinstances=True)
    it = asm.Interpreter(root)
    it.transit(a)
    assert it.transit(a) is None and len(it.pages) == 1
    it.transit(m)
    assert it.transit(m) is not None and len(it.pages) == 3


def test_reentry_removes_the_old_page_and_inherits_its_share():
    root = machine()
    a = state(root, "A", m_neaseinduration=1.0)
    b = state(root, "B", m_neaseinduration=1.0)
    it = asm.Interpreter(root)
    it.transit(a)
    it.transit(b)
    it.tick(0.25)
    it.tick(0.25)  # B shown 0.25 -> A's share is 0.75
    assert abs(it.pages[-1].blend - 0.25) < 1e-9
    pg = it.transit(a)
    assert [p.state.name for p in it.pages] == ["B", "A"]
    assert abs(pg.raw - 0.75) < 1e-9 and it.pages[0].raw == 1.0
    w = it.slot_weights()
    assert abs(w["A.animation"] - 0.75) < 1e-6 and abs(w["B.animation"] - 0.25) < 1e-6


def test_walk_cycle_carries_the_phase_and_synchronises_rates():
    root = machine()
    a = state(root, "Walk", dur=1.0, m_tiswalkcycle=True, m_tislooping=True)
    b = state(root, "Run", dur=0.5, m_tiswalkcycle=True, m_tislooping=True, m_neaseinduration=1.0)
    it = asm.Interpreter(root)
    it.transit(a)
    it.tick(0.3)
    pg = it.transit(b)
    assert abs(pg.playpos - 0.3) < 1e-9 and pg.sync
    it.tick(0.1)  # Run blend 0 -> common rate = Walk's 1.0
    assert abs(it.pages[0].rate - 1.0) < 1e-9 and abs(it.pages[1].rate - 1.0) < 1e-9
    it.tick(0.1)  # Run blend 0.1: period = 0.1/2 + 0.9/1
    assert abs(it.pages[1].rate - 1.0 / 0.95) < 1e-9
    assert abs(it.pages[0].playpos - it.pages[1].playpos) < 1e-9


# ------------------------------------------------------------------ evaluation


def test_no_deferral_during_the_ease_window_without_force_stay():
    root = machine()
    a = state(root, "A", m_tislooping=True)
    b = state(root, "B", m_neaseinduration=1.0, m_tislooping=True)
    c = state(root, "C", m_tislooping=True)
    trans(b, c)
    it = asm.Interpreter(root)
    it.transit(a)
    it.transit(b)
    it.tick(0.1)
    assert it.page.state is c  # old code waited for B's 1 s ease-in


def test_force_stay_time_defers_a_wanted_transition():
    root = machine()
    a = state(root, "A", m_tislooping=True)
    b = state(root, "B", m_nforcestaytime=0.25, m_tislooping=True)
    c = state(root, "C", m_tislooping=True)
    trans(b, c)
    it = asm.Interpreter(root)
    it.transit(a)
    it.transit(b)
    seen = []
    for _ in range(5):
        it.tick(0.1)
        seen.append(it.page.state.name)
    assert seen == ["B", "B", "B", "C", "C"]


def test_fallback_transitions_are_excluded_from_the_normal_pass():
    root = machine()
    a = state(root, "A", m_tislooping=True)
    b = state(root, "B")
    c = state(root, "C")
    trans(a, b, m_tfallback=True)
    t = trans(a, c)
    it = asm.Interpreter(root)
    it.transit(a)
    assert it.get_valid_transition(a)[0] is t
    assert it.get_valid_transition(a, fallback=True)[1] is b


def test_fallback_pass_runs_when_the_state_criteria_fail():
    root = machine()
    a = state(root, "A", m_tislooping=True)
    b = state(root, "B")
    crit_value(a, 1, 0.5, 1.0)
    trans(a, b, m_tfallback=True)
    it = asm.Interpreter(root)
    it.env.values[1] = 0.7
    it.transit(a)
    it.tick(0.1)
    assert it.page.state is a  # criteria hold: stays, the fallback transition is not used
    it.env.values[1] = 0.0
    it.tick(0.1)
    assert it.page.state is b


def test_no_transition_tests_state_is_evaluated_once_finished():
    root = machine()
    a = state(root, "A", dur=0.2, m_tnotransitiontests=True)
    b = state(root, "B")
    trans(a, b)
    it = asm.Interpreter(root)
    it.transit(a)
    it.tick(0.1)
    it.tick(0.1)
    assert it.page.state is a and it.page.playpos == 1.0
    it.tick(0.1)
    assert it.page.state is b  # old code never evaluated such a state


def test_state_target_checks_owning_group_criteria_and_its_own():
    # follow-up: AnimationTransition.initialize_external 0x5f9b13 appends the
    # target STATE's own criteria to the transition's list, so they are tested
    # too (this test used to pin "not its own")
    root = machine()
    a = state(root, "A", m_tislooping=True)
    g = node(asm.CLS_GROUP, "G", root)
    b = state(g, "B")
    crit_value(b, 2, 0.5, 1.0)
    gc = crit_value(g, 3, 0.5, 1.0)
    trans(a, b)
    it = asm.Interpreter(root)
    it.transit(a)
    assert it.get_valid_transition(a) is None  # group criteria fail
    it.env.values[3] = 0.7
    assert it.get_valid_transition(a) is None  # B's own criteria fail
    it.env.values[2] = 0.7
    assert it.get_valid_transition(a)[1] is b
    assert gc.parent is g


# ------------------------------------------------------------------ rate / playpos


def test_rate_is_the_weighted_sum_of_inverse_durations():
    root = machine()
    s = state(root, "S", clips=[("walk", 1.0), ("run", 0.5)], m_tislooping=True)
    blend = s.children[0]
    blend.props.update(m_iblendctrlparam=5, m_nblendintervalstart=0.0, m_nblendintervalend=1.0)
    blend.children[0].props["m_nparentblendposition"] = 0.0
    blend.children[1].props["m_nparentblendposition"] = 1.0
    it = asm.Interpreter(root)
    it.env.values[5] = 0.5
    it.transit(s)
    it.tick(0.1)
    assert abs(it.page.rate - 1.5) < 1e-9  # 0.5/1.0 + 0.5/0.5; old code: 1/first = 1.0
    assert abs(it.page.playpos - 0.15) < 1e-9
    it.env.speed = 2.0
    it.tick(0.1)
    assert abs(it.page.rate - 3.0) < 1e-9


def test_rate_is_clamped_to_6_6_per_second():
    root = machine()
    s = state(root, "S", dur=0.05, m_tislooping=True)
    it = asm.Interpreter(root)
    it.transit(s)
    it.tick(0.1)
    assert abs(it.page.rate - 20.0) < 1e-9
    assert abs(it.page.playpos - 0.66) < 1e-6
    assert abs(asm.MAX_RATE - 6.6) < 1e-6


def test_loop_wrap_is_strict_and_subtractive():
    root = machine()
    s = state(root, "S", dur=1.0, m_tislooping=True)
    it = asm.Interpreter(root)
    pg = it.transit(s)
    pg.playpos = 0.5
    it.tick(0.5)
    assert pg.playpos == 1.0  # exactly 1.0 is not wrapped (old code: 0.0)
    it.tick(0.25)
    assert abs(pg.playpos - 0.25) < 1e-9


def test_slot_playpos_offset_wraps():
    root = machine()
    s = state(root, "S")
    blend = s.children[0]
    slot = blend.children[0]
    slot.props["m_noffset"] = -0.11
    it = asm.Interpreter(root)
    pg = it.transit(s)
    pg.playpos = 0.05
    assert abs(pg.slot_playpos(blend, slot) - 0.94) < 1e-9
    blend.props.update(m_tlayeradditive=True, m_tforcedpos=True)
    assert pg.slot_playpos(blend, slot) == 1.0


# ------------------------------------------------------------------ blending


def test_curve_needs_soft_blend_and_weights_lag_one_frame():
    root = machine()
    a = state(root, "A", m_tislooping=True)
    hard = dict(m_neaseinduration=1.0, m_nblendpower=2.0, m_tislooping=True)
    b = state(root, "B", **hard)
    c = state(root, "C", m_tusesoftblend=True, **hard)
    it = asm.Interpreter(root)
    it.transit(a)
    it.transit(b)
    it.tick(0.25)
    assert it.page.blend == 0.0  # weights were built before the blend advanced
    it.tick(0.25)
    assert abs(it.page.blend - 0.25) < 1e-9  # linear: no "Soft Blend To"
    it2 = asm.Interpreter(root)
    it2.transit(a)
    it2.transit(c)
    it2.tick(0.25)
    it2.tick(0.25)
    assert abs(it2.page.blend - 0.125) < 1e-6  # (2*0.25)^2 / 2


def test_one_random_blend_node_per_layer_list_seeded():
    root = machine()
    s = node(asm.CLS_STATE, "Dead", root)
    for i in range(5):
        b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
        node(asm.CLS_SLOT, "dead%d" % i, b, m_sduration="1 s", targetAnimation="dead%d" % i)
    b = node(asm.CLS_BLEND, "{ACTION_LAYER_1}", s, m_ilayerindex=10)
    node(asm.CLS_SLOT, "arm", b, m_sduration="1 s", targetAnimation="arm")
    assert sorted(asm.layer_lists(s)) == [0, 10] and len(asm.layer_lists(s)[0]) == 5
    picks = set()
    for seed in range(20):
        it = asm.Interpreter(root, seed=seed)
        it.transit(s)
        w = it.slot_weights()
        assert len(w) == 2 and w["arm"] == 1.0  # old code summed all five variants
        picks.add([k for k in w if k != "arm"][0])
        it_b = asm.Interpreter(root, seed=seed)
        it_b.transit(s)
        assert it_b.slot_weights() == w
    assert len(picks) > 1


# ------------------------------------------------------------------ events


def event(owner, kind, at=0.0, eid=1, name="ev"):
    return node(asm.CLS_EVENT, name, owner, m_ieventtype=kind, m_nplaypos=at, m_ianimationevent=eid)


def fired(it):
    out = [ev.name for ev, _ in it.fired]
    del it.fired[:]
    return out


def test_event_trigger_kinds():
    root = machine()
    a = state(root, "A", dur=1.0, m_tislooping=True)
    b = state(root, "B", dur=1.0, m_tislooping=True)
    event(a, asm.EV_ENTER_STATE, name="enter")
    event(a, asm.EV_LEAVE_STATE, name="leave")
    event(a, asm.EV_PLAY_POS, at=0.35, name="pos")
    event(a, asm.EV_TOTAL_PLAY_TIME, at=1.25, name="time")
    it = asm.Interpreter(root)
    it.transit(a)
    assert fired(it) == ["enter"]
    out = []
    for _ in range(15):
        it.tick(0.1)
        out.append(fired(it))
    # PLAY_POS latch: once per lap, when the position has been passed
    assert [i for i, f in enumerate(out) if "pos" in f] == [3, 13]
    # TOTAL_PLAY_TIME is in seconds and fires once
    assert [i for i, f in enumerate(out) if "time" in f] == [12]
    it.transit(b)
    assert fired(it) == ["leave"]


def test_play_pos_event_before_the_start_position_is_latched():
    root = machine()
    a = state(root, "A", dur=1.0, m_nstartplaypos=0.5)
    event(a, asm.EV_PLAY_POS, at=0.2, name="early")
    event(a, asm.EV_PLAY_POS, at=0.7, name="late")
    it = asm.Interpreter(root)
    it.transit(a)
    names = []
    for _ in range(6):
        it.tick(0.1)
        names += fired(it)
    assert names == ["late"]


def test_skipped_event_fires_after_the_loop_wrap():
    root = machine()
    a = state(root, "A", dur=1.0, m_tislooping=True)
    event(a, asm.EV_PLAY_POS, at=0.95, name="tail")
    it = asm.Interpreter(root)
    pg = it.transit(a)
    pg.playpos = 0.9
    it.tick(0.2)  # 0.9 -> 1.1 -> wraps to 0.1: never observed above 0.95
    assert fired(it) == ["tail"]
