"""Integration follow-up: one implementation of each engine rule, shared by the
interpreter (anim_state_machine) and the metadata export (anim_meta).

Loader          nested fragment roots, instances, references (data: 25 / 25
                {'etag': 2} references name the instancing group)
owners          FindClosestRelevantParent 0x5aaf49, AddToClosestState,
                AddToClass 0x5ed37a: the nearest ancestor with a system type
criteria        MathLib.InsideInterval 0x77aa25, AnimationCriteriaMet 0x5c5781,
                AnimationTransition.initialize_external 0x5f9b13
events          CheckPlayPosEvents 0x5b55c4 / 0x5b52c1, SetupNewPage 0x5b8f16
Synthetic trees only."""

import json, os, sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_meta as am
import anim_state_machine as asm
import engine_enums as ee

_n = [0]


def node(cls, name, parent=None, **props):
    _n[0] += 1
    n = asm.Node("f%d" % _n[0], cls, name)
    n.props = dict(props)
    if parent is not None:
        n.parent = parent
        parent.children.append(n)
    return n


def state(parent, name, dur=1.0, **props):
    s = node(asm.CLS_STATE, name, parent, **props)
    b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
    node(asm.CLS_SLOT, name + ".animation", b, m_sduration="%f s" % dur)
    return s


def trans(owner, target, **props):
    return node(asm.CLS_TRANS, "{trans}", owner, m_etostate={"ref": target.id}, **props)


def crit(owner, kind, **props):
    return node(asm.CLS_CRIT, "{crit}", owner, m_ianimationcriteria=kind, **props)


def crit_enum(owner, var, value, **props):
    return crit(owner, asm.CRIT_ENUM, m_ianimationenum=var, m_ianimationenumvalue=value, **props)


def event(owner, eid, kind, at):
    return node(
        asm.CLS_EVENT, "{ev}", owner, m_ianimationevent=eid, m_ieventtype=kind, m_nplaypos=at
    )


# ------------------------------------------------------------------ loader


def _frag(path, nodes, preamble_types=True):
    """nodes: [(id, type, name, parent ref dict | None, extra props)]"""
    pre = {"name": "(preamble)"}
    full = []
    for nid, typ, name, parent, extra in nodes:
        if preamble_types:
            pre["str_" + nid] = [typ]
        props = [["name", "string", name]]
        if parent is not None:
            props.append(["logicalParent", "Entity", parent])
        props += [[k, "x", v] for k, v in extra.items()]
        full.append({"id": nid, "type": typ, "props": props})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"instances": [pre], "nodes_full": full}, fh)


@pytest.fixture
def corpus(tmp_path):
    """Class -> groups A and B, both instancing Sub.fragment.  Sub's top-level
    nodes: state `Idle`, group `Inner`, folder `Group Transitions` with a
    transition back to the instancing group ({'etag': 2}) and one to Idle."""
    base = tmp_path / "extracted" / "TNT"
    asset = "/TNT/Sub.fragment"
    _frag(
        str(base / "Sub.fragment.json"),
        [
            ("s1", "AnimationStateWM(Node)", "Idle", {"etag": 2}, {}),
            ("g1", "AnimationStateGroupWM(Folder)", "Inner", {"etag": 2}, {}),
            ("s2", "AnimationStateWM(Node)", "Run", {"ref": "g1"}, {}),
            ("f1", "Folder", "Group Transitions", {"etag": 2}, {}),
            (
                "t1",
                "AnimationTransitionWM(Node)",
                "{to host}",
                {"ref": "f1"},
                {"m_etostate": {"etag": 2}},
            ),
            (
                "t2",
                "AnimationTransitionWM(Node)",
                "{to Idle}",
                {"ref": "s2"},
                {"m_etostate": {"ref": "s1"}},
            ),
        ],
    )
    top = str(base / "AnimationClassX.fragment.json")
    _frag(
        top,
        [
            ("c0", "AnimationClassWM(Folder)", "Class", {"etag": 2}, {}),
            ("ga", "AnimationStateGroupWM(FragmentNode)", "A", {"ref": "c0"}, {"assetName": asset}),
            ("gb", "AnimationStateGroupWM(FragmentNode)", "B", {"ref": "c0"}, {"assetName": asset}),
            # a path reference: into instance B, then the node inside it
            ("s9", "AnimationStateWM(Node)", "Far", {"ref": "c0"}, {}),
            (
                "t9",
                "AnimationTransitionWM(Node)",
                "{to B/Run}",
                {"ref": "s9"},
                {"m_etostate": {"xref": ["zz", "gb", "s2"]}},
            ),
        ],
    )
    return top


def _by(roots, cls, name):
    return [n for n in asm.walk(roots) if n.cls == cls and n.name == name]


def test_load_tree_keeps_the_top_level_nodes_of_nested_fragments(corpus):
    roots = asm.load_tree(corpus)
    root = asm.find_class_root(roots)
    a, b = _by(roots, asm.CLS_GROUP, "A")[0], _by(roots, asm.CLS_GROUP, "B")[0]
    # old loader: `Idle` and `Inner` were dropped, their children re-parented to A,
    # and B (second instance of the same fragment) stayed empty
    for host in (a, b):
        assert [k.name for k in host.children] == ["Idle", "Inner", "Group Transitions"]
        assert [k.name for k in asm.members(host)] == ["Idle", "Inner"]
        assert all(k.frag == "/TNT/Sub.fragment" for k in host.children)
    assert len(_by(roots, asm.CLS_STATE, "Idle")) == 2
    assert asm.fragment_host(_by(roots, asm.CLS_STATE, "Run")[0]) is a
    assert asm.fragment_host(root) is None


def test_references_resolve_inside_the_right_fragment_instance(corpus):
    roots = asm.load_tree(corpus)
    index = asm.node_index(roots)
    assert len(index["s1"]) == 2  # ids repeat across instances
    a, b = _by(roots, asm.CLS_GROUP, "A")[0], _by(roots, asm.CLS_GROUP, "B")[0]
    for host in (a, b):
        ts = {t.name: t for t in asm.walk(host) if t.cls == asm.CLS_TRANS}
        to_host, to_idle = ts["{to host}"], ts["{to Idle}"]
        assert asm.transitions_of(host) == [to_host]  # through the folder
        # {'etag': 2}: the group that instances the fragment
        assert asm.resolve_ref(to_host, to_host.p("m_etostate"), index) is host
        # a plain ref stays inside its own instance
        idle = asm.resolve_ref(to_idle, to_idle.p("m_etostate"), index)
        assert idle.name == "Idle" and idle.parent is host
    t9 = _by(roots, asm.CLS_TRANS, "{to B/Run}")[0]
    run = asm.resolve_ref(t9, t9.p("m_etostate"), index)
    assert run.name == "Run" and asm.fragment_host(run) is b
    it = asm.Interpreter(asm.find_class_root(roots))
    assert it._resolve_target(t9) is run
    assert asm.resolve_ref(t9, {"etag": 1}, index) is None


def test_node_class_comes_from_the_node_record(tmp_path):
    p = str(tmp_path / "extracted" / "A.fragment.json")
    _frag(p, [("s1", "AnimationStateWM(Node)", "Idle", None, {})], preamble_types=False)
    (n,) = asm.load_tree(p)
    assert n.cls == asm.CLS_STATE  # old: "?" (one node per shipped fragment)


def test_hero_fragments_get_a_synthetic_class_root():
    a, b = node(asm.CLS_GROUP, "CombatGroup"), node(asm.CLS_GROUP, "NonCombatGroup")
    root = asm.find_class_root([a, b])
    assert root.cls == asm.CLS_CLASS and root.children == [a, b]
    assert a.parent is None  # paths and owner chains are untouched
    s = state(b, "Idle")
    crit(a, asm.CRIT_ACTION, m_ianimationaction=3)
    assert asm.Interpreter(root).start() is s  # old: roots[0] only


# ------------------------------------------------------------------ owners


def test_criteria_and_transitions_register_through_folders_of_any_name():
    root = node(asm.CLS_CLASS, "class")
    g = node(asm.CLS_GROUP, "G", root)
    s = state(g, "S")
    c1 = crit(node("Folder", "Group Criteria", g), asm.CRIT_ACTION, m_ianimationaction=1)
    c2 = crit(node("Folder", "Criteria", s), asm.CRIT_ACTION, m_ianimationaction=2)
    c3 = crit(s, asm.CRIT_ACTION, m_ianimationaction=3)
    t = trans(node("Folder", "GroupTransistions", g), s)
    assert asm.criteria_of(g) == [c1]  # old: [] -- only a folder named "Criterias"
    assert asm.criteria_of(s) == [c2, c3]
    assert asm.transitions_of(g) == [t]
    assert asm.criterion_owner(c1) == (None, g, None)
    assert asm.criterion_owner(c2) == (s, None, None)
    assert asm.criterion_owner(crit(t, asm.CRIT_ACTION)) == (None, None, t)
    # anim_meta uses the same lists
    assert am._crit_nodes(g) == [c1] and am._crit_nodes(s) == [c2, c3]


def test_group_members_are_found_through_folders():
    root = node(asm.CLS_CLASS, "class")
    g = node(asm.CLS_GROUP, "G", root)
    a = state(g, "A")
    b = state(node("Folder", "TransitionStates", g), "B")
    inner = node(asm.CLS_GROUP, "Inner", g)
    c = state(inner, "C")
    assert asm.members(g) == [a, b, inner]  # AddToClass 0x5ed37a walks past folders
    assert asm._parent_group(b) is g and asm._parent_group(c) is inner
    assert asm._parent_group(g) is None  # the class is not a state group


def test_overlay_candidates_are_the_override_states_not_a_folder_name():
    root = node(asm.CLS_CLASS, "class")
    state(root, "Idle")
    g = node(asm.CLS_GROUP, "Looks", node("Folder", "Extras", root))
    state(g, "LookLeft", m_toverridestate=True)
    state(g, "LookRight", m_toverridestate=True)
    lone = state(node("Folder", "Misc", root), "Flinch", m_toverridestate=True)
    assert asm.Interpreter(root)._overlay_candidates() == [g, lone]  # command_add_state 0x5a03a8


# ------------------------------------------------------------------ criteria


def test_interval_types_follow_inside_interval():
    # INTERVAL: [min, max[
    assert asm.interval_met(0.5, 0, 0.5, 1.0) and not asm.interval_met(1.0, 0, 0.5, 1.0)
    # LESS_THAN: x < MAX, min is not read ("SPEED less than 0.01" ships as min 0.51, max 0.01)
    assert asm.interval_met(0.0, 1, 0.51, 0.01)
    assert not asm.interval_met(0.3, 1, 0.51, 0.01)  # old: x <= min -> True
    assert not asm.interval_met(0.01, 1, 0.51, 0.01)
    # GREATER_THAN_OR_EQUAL: x >= min
    assert asm.interval_met(0.01, 2, 0.01, 0.91) and not asm.interval_met(0.0, 2, 0.01, 0.91)
    assert not asm.interval_met(0.5, 3, 0.0, 1.0)


def test_enum_values_compare_as_int32():
    c = crit_enum(None, 12, 4294967295)  # OPPONENT_WEAPON_TYPE NONE = -1
    env = asm.Env()
    env.enums[12] = -1
    assert asm.criteria_met(c, env, None, True)  # old: 4294967295 != -1
    assert asm.criteria_partial(c, {12: -1}) is True
    assert asm.criteria_partial(c, {12: 0}) is False
    assert asm.criteria_partial(c, {5: 0}) is None


def test_partial_evaluation_is_three_valued_and_shared_with_anim_meta():
    any_of = crit(None, asm.CRIT_ANY_OF)
    crit_enum(any_of, 11, 3)
    crit(any_of, asm.CRIT_ACTION, m_ianimationaction=7)
    assert asm.criteria_partial(any_of, {11: 3}) is True
    assert asm.criteria_partial(any_of, {11: 4}) is None  # the action may still hold
    all_of = crit(None, asm.CRIT_ALL_OF)
    crit_enum(all_of, 11, 3)
    crit(all_of, asm.CRIT_ACTION, m_ianimationaction=7)
    assert asm.criteria_partial(all_of, {11: 4}) is False
    assert asm.criteria_partial(all_of, {11: 3}) is None
    assert am._accepts_env(all_of, {11: 4}) is False and am._accepts(any_of, 3) is True
    assert asm.criteria_partial(crit(None, asm.CRIT_ANY_OF), {}) is False  # no children: never met


def _dead_machine():
    root = node(asm.CLS_CLASS, "class")
    g = node(asm.CLS_GROUP, "Move", root)
    idle = state(g, "Idle", m_tislooping=True)
    dead = state(node("Folder", "Dead", root), "Dead")
    crit_enum(node("Folder", "Criterias", dead), 1, 2, m_tentryonly=True)  # {criteria: DEAD}
    t = trans(node("Folder", "Group Transitions", g), dead)  # no criteria of its own
    return root, idle, dead, t


def test_a_transition_to_a_state_carries_that_states_criteria():
    root, idle, dead, t = _dead_machine()
    assert len(asm.transition_criteria(t, dead)) == 1 and asm.transition_criteria(t) == []
    it = asm.Interpreter(root)
    it.transit(idle)
    for _ in range(5):
        it.tick(0.1)
    assert it.page.state is idle  # old: "trans to Dead" fired at once
    it.env.enums[1] = 2
    it.tick(0.1)
    assert it.page.state is dead


def test_entry_only_criteria_are_skipped_only_inside_their_owner():
    root, idle, dead, t = _dead_machine()
    (c,) = asm.criteria_of(dead)
    env = asm.Env()
    on_idle, on_dead = asm.Page(idle, 0.0, 0.0), asm.Page(dead, 0.0, 0.0)
    assert not asm.criteria_met(c, env, on_idle, False)  # old: entry-only -> always met
    assert asm.criteria_met(c, env, on_dead, False)  # the state stays once entered
    assert not asm.criteria_met(c, env, on_dead, True)
    assert not asm.criteria_met(c, env, None, False)
    # a group's entry-only criterion: skipped for every state inside the group
    gc = crit(idle.parent, asm.CRIT_ACTION, m_ianimationaction=9, m_tentryonly=True)
    assert asm.criteria_met(gc, env, on_idle, False) and not asm.criteria_met(
        gc, env, on_dead, False
    )
    # a transition's own entry-only criterion is always tested
    tc = crit(t, asm.CRIT_ACTION, m_ianimationaction=9, m_tentryonly=True)
    assert not asm.criteria_met(tc, env, on_idle, False)


# ------------------------------------------------------------------ events


def test_play_pos_events_fire_at_their_position_not_after_it():
    root = node(asm.CLS_CLASS, "class")
    s = state(root, "S", dur=1.0)
    end = event(s, 7, asm.EV_PLAY_POS, 1.0)  # on a clamped page playpos never exceeds 1.0
    at0 = event(s, 8, asm.EV_PLAY_POS, 0.0)
    sec = event(s, 9, asm.EV_TOTAL_PLAY_TIME, 0.5)
    it = asm.Interpreter(root)
    it.transit(s)
    for _ in range(12):
        it.tick(0.1)
    fired = [e for e, _v in it.fired]
    assert end in fired  # old (`<`): never
    assert at0 not in fired  # at <= start position: created already fired (0x5b8f16)
    assert sec in fired
    assert asm.event_prelatched(at0, 0.0) and not asm.event_prelatched(end, 0.0)
    assert not asm.event_prelatched(sec, 5.0)
    assert asm.event_due(end, 1.0, 0.0) and not asm.event_due(end, 0.999, 9.0)
    assert asm.event_due(sec, 0.0, 0.5)


def test_event_timing_is_one_rule_for_both_modules():
    # (play position, seconds on the clip, seconds of play time)
    assert asm.event_timing(asm.EV_PLAY_POS, 0.25, 4.0) == (0.25, 1.0, 1.0)
    assert asm.event_timing(asm.EV_TOTAL_PLAY_TIME, 0.2, 4.0) == (0.05, 0.2, 0.2)
    assert asm.event_timing(asm.EV_TOTAL_PLAY_TIME, 9.0, 4.0) == (None, None, 9.0)
    assert asm.event_timing(asm.EV_ENTER_STATE, 0.7, 4.0) == (0.0, 0.0, 0.0)
    assert asm.event_timing(asm.EV_LEAVE_STATE, 0.7, 4.0) == (None, None, None)
    # a state whose slot has speedFactor 2 runs through its clip twice as fast
    assert asm.event_timing(asm.EV_PLAY_POS, 0.25, 4.0, 2.0) == (0.25, 1.0, 0.5)
    assert asm.event_timing(asm.EV_TOTAL_PLAY_TIME, 0.2, 4.0, 2.0) == (0.1, 0.4, 0.2)
    assert (am.TRIG_PLAY_POS, am.TRIG_TOTAL_PLAY_TIME) == (asm.EV_PLAY_POS, asm.EV_TOTAL_PLAY_TIME)
    s = state(None, "S")
    event(s, ee.ident("ANIMATION_EVENT", "IMPACT"), asm.EV_PLAY_POS, 0.0)
    event(s, ee.ident("ANIMATION_EVENT", "IMPACT"), asm.EV_PLAY_POS, 0.5)
    second, first = am._events(s, duration=2.0, basis="clip duration")  # firing order
    assert first["fires_first_pass"] is False and "fires_first_pass" not in second
    assert first["play_time_s"] is None  # non-looping: never
    assert second["time_s"] == 1.0


# ------------------------------------------------------------------ transitions


def test_sync_markers_and_start_rule_are_shared():
    t = node(asm.CLS_TRANS, "{t}", m_tsupersyncpos=True)
    t.props.update(m_nsupersynclocal1=0.8, m_nsupersyncremote1=0.4)
    t.props.update(m_nsupersynclocal2=0.5, m_nsupersyncremote2=0.1)
    assert asm.marker_pairs(t) == [(0.5, 0.1), (0.8, 0.4)] == am.sync_markers(t)
    assert asm.markers_window(asm.marker_pairs(t)) == (0.5, 0.8)
    rec = {"start": {"rule": "sync_markers", "markers": [[0.5, 0.1], [0.8, 0.4]]}}
    for pp in (0.2, 0.65, 0.9):
        assert am.transition_start(rec, pp) == asm.map_markers([(0.5, 0.1), (0.8, 0.4)], pp)
        assert am.transition_start(rec, pp) == asm.sync_remap(pp, t)
    assert am.TRANSITION_START_PRIORITY is asm.TRANSITION_START_PRIORITY
    # keys written by an extractor older than the name-hash fix
    old = node(asm.CLS_TRANS, "{t}", m_tsupersyncpos=True)
    old.props.update(key_ee2a40a0=0.25, key_4cadfb2b=[0.75, 9.1e7, -1])
    assert asm.sync_markers(old) == [(0.25, 0.75)]  # old interpreter: []
    walk = state(None, "Walk", m_tiswalkcycle=True, m_nstartplaypos=0.3)
    run = state(None, "Run", m_tiswalkcycle=True, m_nstartplaypos=0.3)
    assert asm.start_playpos(run) == (0.3, False, "target_default")
    assert asm.start_playpos(run, None, walk, 0.6) == (0.6, True, "walk_cycle_carry_over")
    assert asm.start_playpos(run, t, walk, 0.65)[2] == "sync_markers"
    t.props.update(m_toverrideplaypos=True, m_nplaypos=0.9)
    assert asm.start_playpos(run, t, walk, 0.65) == (0.9, True, "override_playpos")
    assert [r["rule"] for r in asm.TRANSITION_START_PRIORITY][:4] == [
        "override_playpos",
        "sync_markers",
        "walk_cycle_carry_over",
        "target_default",
    ]


def test_transition_records_use_the_shared_reference_rule(corpus):
    nodes = asm.walk(asm.load_tree(corpus))
    recs = am._transitions(nodes)
    to_host = sorted(r["to"] for r in recs if r["name"] == "{to host}")
    assert to_host == ["Class/A", "Class/B"]  # format 2 guessed these from the caption
    assert all("to_source" not in r for r in recs)
    assert [r["to"] for r in recs if r["name"] == "{to B/Run}"] == ["Class/B/Inner/Run"]
    assert sorted(r["owner"] for r in recs if r["name"] == "{to Idle}") == [
        "Class/A/Inner/Run",
        "Class/B/Inner/Run",
    ]


# ------------------------------------------------------------------ GLB attributes
import numpy as np

import rig_glb
import test_formats_v2 as tf
import watchmen_extract as we
from conftest import parse_glb

_PAL = {"bone_count": 5, "bones": [{"name": "b%d" % i} for i in range(5)]}


def _skinned_model():
    """One format-6 quad at z = 0: normal +Z, tangent +X, bitangent -Y (so the
    handedness is -1), colour (10, 20, 30, 40), triangles wound WITH the normal."""
    return tf._model([{"lods": [[("Body", 1, 6, 0.0, 1)]]}], tf._TEXTURES)


def _write(path, attrs, tris=((0, 1, 2), (0, 2, 3)), **kw):
    V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    U = [(0, 0), (1, 0), (1, 1), (0, 1)]
    SI = np.zeros((4, 4), np.uint8)
    SW = np.tile(np.array([1, 0, 0, 0], np.float32), (4, 1))
    subs = [(0, 4, 0, 2, 56)]
    extra = {}
    if attrs:
        extra = dict(normals=attrs["normals"], colors=attrs["colors"], tangents=attrs["tangents"])
    extra.update(kw)
    # the positional `N` is ignored, as in 1.2.0 (review m4): pass normals there on
    # purpose to prove it changes nothing
    N = [(0.0, 0.0, 1.0)] * 4
    rig_glb.build_rigged_glb(
        path, V, N, U, SI, SW, list(tris), subs, ["m"], {}, _PAL, None, None, static=True, **extra
    )
    return path.read_bytes()


def test_mesh_vertex_attributes_follow_the_model_buffers(monkeypatch):
    h, s = _skinned_model()
    subs = [(0, 4, 0, 2, 56)]
    at = rig_glb.mesh_vertex_attributes(h, s, subs)
    assert at["has_color"] == [True]
    assert np.array_equal(at["normals"], np.tile([0, 0, 1], (4, 1)))
    assert at["colors"].dtype == np.uint8 and at["colors"].tolist() == [[10, 20, 30, 40]] * 4
    assert at["tangents"].tolist() == [[1.0, 0.0, 0.0, -1.0]] * 4
    assert rig_glb.mesh_vertex_attributes(h, s, [(0, 3, 0, 1, 56)]) is None  # does not line up
    assert rig_glb.mesh_vertex_attributes(h[:40], s, subs) is None  # not a header-driven model
    # no authored colours -> the buffer only holds the writer's default
    real = we.select_model_buffers
    monkeypatch.setattr(
        we, "select_model_buffers", lambda *a, **k: [dict(b, has_color=0) for b in real(*a, **k)]
    )
    assert rig_glb.mesh_vertex_attributes(h, s, subs)["colors"] is None


def test_glb_gets_normal_tangent_and_colour_as_valid_accessors(tmp_path):
    h, s = _skinned_model()
    at = rig_glb.mesh_vertex_attributes(h, s, [(0, 4, 0, 2, 56)])
    _write(tmp_path / "on.glb", at)
    g = parse_glb(tmp_path / "on.glb")
    A = g.j["meshes"][0]["primitives"][0]["attributes"]
    assert set(A) == {"POSITION", "NORMAL", "TANGENT", "TEXCOORD_0", "COLOR_0"}
    n, t, c = g.j["accessors"][A["NORMAL"]], g.j["accessors"][A["TANGENT"]], g.j["accessors"]
    c = c[A["COLOR_0"]]
    assert (n["type"], n["componentType"], n["count"]) == ("VEC3", 5126, 4)
    assert (t["type"], t["componentType"], t["count"]) == ("VEC4", 5126, 4)
    assert (c["type"], c["componentType"], c.get("normalized")) == ("VEC4", 5121, True)
    assert "normalized" not in n and "normalized" not in t
    T = np.asarray(g.accessor(A["TANGENT"]), float)
    assert np.allclose(np.linalg.norm(T[:, :3], axis=1), 1.0) and set(T[:, 3]) == {-1.0}
    assert np.asarray(g.accessor(A["COLOR_0"])).tolist() == [[10, 20, 30, 40]] * 4
    for v in g.j["bufferViews"]:
        assert v["byteOffset"] % 4 == 0


def test_attributes_switched_off_leave_the_file_byte_identical(tmp_path):
    h, s = _skinned_model()
    at = rig_glb.mesh_vertex_attributes(h, s, [(0, 4, 0, 2, 56)])
    plain = _write(tmp_path / "a.glb", None)
    off = _write(
        tmp_path / "a.glb", at, write_normals=False, write_colors=False, write_tangents=False
    )
    assert off == plain
    assert _write(tmp_path / "a.glb", at) != plain
    # tangents are not written without normals (glTF would ignore them)
    _write(tmp_path / "b.glb", at, write_normals=False)
    A = parse_glb(tmp_path / "b.glb").j["meshes"][0]["primitives"][0]["attributes"]
    assert set(A) == {"POSITION", "TEXCOORD_0", "COLOR_0"}


def test_malformed_attribute_data_is_left_out_not_repaired(tmp_path):
    h, s = _skinned_model()
    at = rig_glb.mesh_vertex_attributes(h, s, [(0, 4, 0, 2, 56)])

    def attrs(**kw):
        _write(tmp_path / "x.glb", dict(at, **kw))
        return set(parse_glb(tmp_path / "x.glb").j["meshes"][0]["primitives"][0]["attributes"])

    zero_n = at["normals"].copy()
    zero_n[2] = 0
    assert attrs(normals=zero_n) == {"POSITION", "TEXCOORD_0", "COLOR_0"}  # and no TANGENT
    long_t = at["tangents"].copy()
    long_t[1, :3] *= 2
    assert attrs(tangents=long_t) == {"POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"}
    bad_w = at["tangents"].copy()
    bad_w[0, 3] = 0.5
    assert "TANGENT" not in attrs(tangents=bad_w)
    assert "COLOR_0" not in attrs(colors=at["colors"].astype(np.float32))
    assert rig_glb.unit_normals(np.array([[0, 0, 2.0]])).tolist() == [[0, 0, 1]]
    assert rig_glb.unit_normals(np.array([[np.nan, 0, 1.0]])) is None


def test_winding_follows_the_normals_only_when_normals_are_written(tmp_path):
    h, s = _skinned_model()
    at = rig_glb.mesh_vertex_attributes(h, s, [(0, 4, 0, 2, 56)])
    clockwise = ((0, 2, 1), (0, 3, 2))  # the engine's order: against the normal

    def indices(name, a, **kw):
        _write(tmp_path / name, a, tris=clockwise, **kw)
        g = parse_glb(tmp_path / name)
        return np.asarray(g.accessor(g.j["meshes"][0]["primitives"][0]["indices"])).reshape(-1, 3)

    assert indices("f.glb", at).tolist() == [[0, 1, 2], [0, 2, 3]]  # flipped: CCW = front
    assert indices("k.glb", at, fix_winding=False).tolist() == [list(t) for t in clockwise]
    assert indices("n.glb", None).tolist() == [list(t) for t in clockwise]  # no NORMAL: untouched
    P = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], float)
    assert rig_glb.winding_reversed(P, at["normals"], clockwise)
    assert not rig_glb.winding_reversed(P, at["normals"], [(0, 1, 2)])


def test_tangents_are_written_as_stored_unless_orthogonalised(tmp_path):
    n = np.tile(np.array([0, 0, 1.0], np.float32), (4, 1))
    skew = np.tile(np.array([0.8, 0.0, 0.6, 1.0], np.float32), (4, 1))  # |n.t| = 0.6, as shipped
    at = {"normals": n, "colors": None, "tangents": skew}

    def tangent(**kw):
        _write(tmp_path / "t.glb", at, **kw)
        g = parse_glb(tmp_path / "t.glb")
        return np.asarray(g.accessor(g.j["meshes"][0]["primitives"][0]["attributes"]["TANGENT"]))

    assert np.allclose(tangent(), skew)
    assert np.allclose(tangent(orthogonalize_tangents=True), [[1, 0, 0, 1]] * 4)
    assert rig_glb.orthogonal_tangents(n, np.tile([0, 0, 1.0, 1.0], (4, 1))) is None


# ------------------------------------------------------------------ slot speed, slave lock


def _speed_state(parent, name, dur, speed, **props):
    s = node(asm.CLS_STATE, name, parent, **props)
    b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
    node(asm.CLS_SLOT, "{%s.animation}" % name, b, m_sduration="%f s" % dur, speedFactor=speed)
    return s


def test_page_rate_includes_the_slot_speed_factor():
    """rate = speed * slot speedFactor * weight / duration (0x5b5175-0x5b51c7;
    AnimSlot::GetSpeedFactor 0x4b30b1 reads the same +0x64)."""
    root = node(asm.CLS_CLASS, "class")
    s = _speed_state(root, "Counter", 4.0, 1.1, m_tislooping=True)
    it = asm.Interpreter(root)
    it.transit(s)
    it.tick(1.0)
    assert it.page.playpos == pytest.approx(1.1 / 4.0)  # old: 0.25
    assert asm.state_speed(s) == (1.1, "slot speedFactor")
    rec = am.state_record(s)
    assert rec["speed"] == 1.1 and rec["clips"][0]["speed"] == 1.1 and "speed_basis" not in rec
    two = _speed_state(root, "Blend", 2.0, 1.0)
    node(asm.CLS_SLOT, "{Other.animation}", two.children[0], m_sduration="2 s", speedFactor=1.5)
    assert asm.state_speed(two)[0] == 1.0 and "differ" in asm.state_speed(two)[1]
    assert asm.state_speed(node(asm.CLS_STATE, "Empty", root)) == (None, None)


def test_event_times_follow_the_state_speed():
    s = _speed_state(None, "Victim", 4.0, 1.1)
    event(s, 28, asm.EV_TOTAL_PLAY_TIME, 0.2)
    event(s, 19, asm.EV_PLAY_POS, 0.5)
    goto, leave = am._events(s, duration=4.0, basis="clip duration", speed=1.1)
    # 0.2 s of play at 1.1x = 0.22 s into the clip
    assert (goto["play_time_s"], goto["time_s"], goto["playpos"]) == (0.2, 0.22, 0.055)
    assert goto["playpos_basis"] == "seconds * speed / clip duration"
    # play position 0.5 of a 4 s clip: 2 s into the clip, reached after 2 / 1.1 s
    assert (leave["playpos"], leave["time_s"], leave["play_time_s"]) == (0.5, 2.0, 1.8182)


def test_pair_timeline_runs_on_the_masters_clock():
    """The partner's play position is copied from the master (UpdatePagePlayPos
    0x5b5756): its own slot speed does not matter, the master's does."""

    def rec(absolute, special, speed, events=()):
        s = _speed_state(
            None,
            "S",
            4.0,
            speed,
            m_tisabsoluteanimation=absolute,
            m_ispecialhandling=special,
            m_neaseinduration=0.21,
        )
        for e in events:
            event(s, *e)
        return am.state_record(s, fact=lambda c: {"duration_s": 4.0})

    master = rec(False, 6, 1.1)
    victim = rec(True, 3, 1.0, [(28, asm.EV_TOTAL_PLAY_TIME, 0.2), (19, asm.EV_PLAY_POS, 0.59)])
    assert victim["speed"] == 1.0 and master["speed"] == 1.1
    t = am.pair_timeline(master, victim, {"duration_s": 4.0}, {"duration_s": 4.0})
    assert t["playpos_per_second"] == pytest.approx(1.1 / 4.0)
    assert t["master"]["speed"] == 1.1 and t["partner"]["follows_master_playpos"] is True
    p = t["partner"]
    assert p["goto_target"] == {"time_s": 0.2, "playpos": 0.055, "trigger": "TOTAL_PLAY_TIME"}
    # released at play position 0.59 of BOTH clips = 0.59 * 4 / 1.1 seconds of play
    assert p["release"] == {"time_s": 2.1455, "playpos": 0.59, "trigger": "PLAY_POS"}
    assert [(x["mode"], x["from_playpos"], x["to_playpos"]) for x in p["phases"]] == [
        ("own_entry_pose", 0.0, 0.055),
        ("blend_to_anchor", 0.055, 0.1128),
        ("anchored", 0.1128, 0.59),
        ("released", 0.59, None),
    ]
    assert [x["from_s"] for x in p["phases"]] == [0.0, 0.2, 0.41, 2.1455]


def test_force_update_lets_a_looping_no_transition_tests_state_be_left():
    """EvaluateTransitions 0x5cbbc2 skips a "No Transition Tests" state unless its
    play position reached 1 or the controller's m_tforceupdate (+0x2c) is set; a
    looping idle (every enemy class) therefore needs the flag."""
    root = node(asm.CLS_CLASS, "class")
    idle = state(root, "Idle", m_tislooping=True, m_tnotransitiontests=True)
    walk = state(root, "Walk", m_tislooping=True)
    t = trans(idle, walk)
    crit(t, asm.CRIT_VALUE, m_ianimationvalue=1, m_iintervaltype=2, m_nintervalmin=0.01)
    it = asm.Interpreter(root)
    it.transit(idle)
    it.env.values[1] = 0.5
    for _ in range(10):
        it.tick(0.1)
    assert it.page.state is idle
    it.env.force_update = True
    it.tick(0.1)
    assert it.page.state is walk


# ------------------------------------------------------------------ review B1: start position
#
# TransitToState 0x5b4a31 starts a page at the state's m_nstartplaypos (or where
# the transition says); play time (page +0x34) counts from there.  The exported
# times are checked against an Interpreter run of the same state.


def _fire_times(state, dt=0.005, seconds=8.0, start=None):
    """{event node name: (seconds since entry, play position)} of first firings."""
    root = state.parent
    it = asm.Interpreter(root)
    if start is None:
        it.transit(state)
    else:
        it._setup_page(state, start, False, -1.0, False)
    t, seen = 0.0, {}
    for _ in range(int(seconds / dt)):
        it.tick(dt)
        t += dt
        for ev, _v in it.fired:
            seen.setdefault(ev.name, (t, it.page.playpos))
        it.fired.clear()
    return seen


def _started_state(start, loop, dur=4.0, speed=1.0):
    root = node(asm.CLS_CLASS, "class")
    s = node(asm.CLS_STATE, "S", root, m_nstartplaypos=start, m_tislooping=loop)
    b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
    node(asm.CLS_SLOT, "{S.animation}", b, m_sduration="%f s" % dur, speedFactor=speed)
    for name, eid, kind, at in (
        ("late", 20, asm.EV_PLAY_POS, 0.75),
        ("early", 21, asm.EV_PLAY_POS, 0.3),
        ("at_start", 22, asm.EV_PLAY_POS, start),
        ("secs", 28, asm.EV_TOTAL_PLAY_TIME, 0.2),
        ("enter", 23, asm.EV_ENTER_STATE, 0.9),
    ):
        node(asm.CLS_EVENT, name, s, m_ianimationevent=eid, m_ieventtype=kind, m_nplaypos=at)
    return s


@pytest.mark.parametrize("loop", [False, True])
@pytest.mark.parametrize("start,speed", [(0.5, 1.0), (0.06, 1.1), (0.0, 1.0)])
def test_exported_event_times_agree_with_the_interpreter(start, speed, loop):
    s = _started_state(start, loop, 4.0, speed)
    seen = _fire_times(s)
    recs = am.state_record(s, fact=lambda c: {"duration_s": 4.0})
    assert recs["start_playpos"] == start and recs["start_basis"] == "state_default"
    by_id = {e["event_id"]: e for e in recs["events"]}
    for name, eid in (("late", 20), ("early", 21), ("at_start", 22), ("secs", 28), ("enter", 23)):
        e = by_id[eid]
        assert e["start_playpos"] == start and e["start_basis"] == "state_default"
        if e["play_time_s"] is None:
            assert name not in seen, (name, seen.get(name))  # the engine never fires it
            assert e["fires_first_pass"] is False and not loop
            continue
        t, pp = seen[name]
        assert t == pytest.approx(e["play_time_s"], abs=0.011), name
        if e["trigger"] != "PLAY_POS":  # play position reached when it fires
            assert pp == pytest.approx(e["playpos"], abs=0.011 * speed / 4.0 + 1e-6), name
        assert e["time_s"] == pytest.approx(e["playpos"] * 4.0, abs=1e-3)
    # an event at or before the start position does not fire on the first pass
    pre = [n for n, eid in (("early", 21), ("at_start", 22)) if by_id[eid]["raw"] <= start]
    for n in pre:
        e = by_id[{"early": 21, "at_start": 22}[n]]
        assert e["fires_first_pass"] is False
        lap = (1.0 - start) * 4.0 / speed
        assert (n in seen and seen[n][0] > lap - 0.011) if loop else n not in seen
    if start == 0.5:  # the review's numbers: 4 s clip, start 0.5
        assert by_id[28]["playpos"] == 0.55 and by_id[20]["play_time_s"] == 1.0


def test_events_for_another_entry_position_are_marked_as_given():
    s = _started_state(0.5, False)
    seen = _fire_times(s, start=0.1)  # e.g. an "Override Start PlayPos" transition
    ev = {e["event_id"]: e for e in am._events(s, duration=4.0, speed=1.0, start=0.1)}
    assert ev[20]["start_basis"] == "given" and ev[20]["start_playpos"] == 0.1
    assert ev[20]["play_time_s"] == pytest.approx(2.6) == pytest.approx(seen["late"][0], abs=0.011)
    assert ev[21]["play_time_s"] == pytest.approx(0.8) == pytest.approx(seen["early"][0], abs=0.011)
    assert "fires_first_pass" not in ev[21]  # 0.3 is ahead of 0.1


def _pair_recs(m_start, p_events, m_speed=1.1, p_start=0.0):
    def rec(start, speed, absolute, special, events=()):
        root = node(asm.CLS_CLASS, "class")
        s = node(
            asm.CLS_STATE,
            "S",
            root,
            m_nstartplaypos=start,
            m_tisabsoluteanimation=absolute,
            m_ispecialhandling=special,
            m_neaseinduration=0.21,
        )
        b = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
        node(asm.CLS_SLOT, "{S.animation}", b, m_sduration="4 s", speedFactor=speed)
        for e in events:
            event(s, *e)
        return s, am.state_record(s, fact=lambda c: {"duration_s": 4.0})

    return rec(m_start, m_speed, False, 6), rec(p_start, 1.0, True, 3, p_events)


def test_pair_timeline_starts_at_the_masters_start_position():
    """The partner's play position is the master's, and the master's page starts
    at its m_nstartplaypos: playpos(t) = start + t * speed / duration."""
    (mnode, master), (_p, victim) = _pair_recs(
        0.09, [(28, asm.EV_TOTAL_PLAY_TIME, 0.2), (19, asm.EV_PLAY_POS, 0.69)]
    )
    t = am.pair_timeline(master, victim, {"duration_s": 4.0}, {"duration_s": 4.0})
    rate = 1.1 / 4.0
    assert t["start_playpos"] == 0.09 and t["master"]["start_basis"] == "state_default"
    assert t["master"]["entry_alternatives"] == [] and t["partner"]["start_playpos"] == 0.0
    p = t["partner"]
    assert p["entered_by"] == "goto_slave_mode"
    assert p["goto_target"]["playpos"] == pytest.approx(0.09 + 0.2 * rate, abs=1e-4)  # was 0.055
    assert p["release"]["time_s"] == pytest.approx(
        (0.69 - 0.09) / rate, abs=1e-4
    )  # was 0.69 / rate
    assert p["phases"][0]["from_playpos"] == 0.09
    # the master's page, run by the interpreter, is at the exported play position
    # at the exported times
    it = asm.Interpreter(mnode.parent)
    it.transit(mnode)
    clock = 0.0
    for want_t, want_pp in (
        (p["goto_target"]["time_s"], p["goto_target"]["playpos"]),
        (p["release"]["time_s"], p["release"]["playpos"]),
    ):
        while clock < want_t - 1e-9:
            step = min(0.01, want_t - clock)
            it.tick(step)
            clock += step
        assert it.page.playpos == pytest.approx(want_pp, abs=2e-4)
    # an explicit other entry: flagged, and the numbers move with it
    t2 = am.pair_timeline(master, victim, {"duration_s": 4.0}, {"duration_s": 4.0}, start=0.0)
    assert (
        t2["master"]["start_basis"] == "given" and t2["partner"]["goto_target"]["playpos"] == 0.055
    )


def test_partner_events_before_a_start_position():
    # a partner PLAY_POS event behind the master's start fires at once (the copied
    # position is already past it); one at the partner's own start never fires
    (_m, master), (_p, victim) = _pair_recs(
        0.2, [(28, asm.EV_PLAY_POS, 0.1), (19, asm.EV_PLAY_POS, 0.0), (19, asm.EV_PLAY_POS, 0.6)]
    )
    p = am.pair_timeline(master, victim, {"duration_s": 4.0}, {"duration_s": 4.0})["partner"]
    assert p["goto_target"] == {"time_s": 0.0, "playpos": 0.2, "trigger": "PLAY_POS"}
    assert p["release"]["playpos"] == 0.6  # not the pre-latched one at 0.0


def test_entry_alternatives_list_transitions_that_set_the_start():
    rec = {"path": "C/Group/Counter", "walk_cycle": False}
    trans_ = [
        {"owner": "C/Idle", "name": "{a}", "to": "C/Group"},
        {
            "owner": "C/Idle",
            "name": "{b}",
            "to": "C/Group",
            "start": {"rule": "override_playpos", "playpos": 0.3},
        },
        {
            "owner": "C/Idle",
            "name": "{c}",
            "to": "C/Other",
            "start": {"rule": "override_playpos", "playpos": 0.9},
        },
    ]
    assert am.entry_alternatives(rec, trans_) == [
        {"rule": "override_playpos", "playpos": 0.3, "owner": "C/Idle", "transition": "{b}"}
    ]
    assert (
        am.entry_alternatives(dict(rec, walk_cycle=True), [])[0]["rule"] == "walk_cycle_carry_over"
    )


# ------------------------------------------------------------------ review M1 / M2: jiggle
import jiggle_d6


def test_jiggle_cache_directory_names_the_model_and_its_constants(monkeypatch):
    import characters_export as ce

    default = ce.jiggle_cache_dir("/out/_bake/female")
    pinned = ce.jiggle_cache_dir("/out/_bake/female", "pinned")
    pivot = ce.jiggle_cache_dir("/out/_bake/female", "pivot")
    assert default == pinned != pivot
    assert pinned.startswith("/out/_bake/female_j_pinned-engine-")
    assert pivot.startswith("/out/_bake/female_j_pivot-capture-")
    assert "/out/_bake/female_j" not in (pinned, pivot)  # the 1.2.0 directory is never read
    # other constants -> another directory
    monkeypatch.setitem(jiggle_d6._CAPTURE_FIT, "breast", dict(K=600.0, D=37.5))
    assert ce.jiggle_cache_dir("/out/_bake/female", "pivot") != pivot
    with pytest.raises(ValueError):
        ce.jiggle_cache_dir("/out/_bake/female", "nope")


def test_cli_jiggle_model_option(monkeypatch, capsys):
    import watchmen

    calls = {}

    class FakeExport:
        @staticmethod
        def export(exout, outdir, naz, jiggle_model=None):
            calls["characters"] = (exout, outdir, naz, jiggle_model)
            return 0

    monkeypatch.setitem(sys.modules, "characters_export", FakeExport)
    monkeypatch.setattr(watchmen, "_wl", lambda: object())
    assert watchmen.main(["w", "characters", "EX", "OUT", "--jiggle-model", "pivot"]) == 0
    assert calls["characters"] == ("EX", "OUT", "game.naz", "pivot")
    assert watchmen.main(["w", "characters", "EX", "--jiggle-model", "pinned", "OUT", "N.naz"]) == 0
    assert calls["characters"] == ("EX", "OUT", "N.naz", "pinned")
    assert watchmen.main(["w", "characters", "EX", "OUT"]) == 0
    assert calls["characters"][3] is None  # the default model
    assert watchmen.main(["w", "characters", "EX", "OUT", "--jiggle-model", "wobbly"]) == 2
    assert watchmen.main(["w", "characters", "EX", "OUT", "--jiggle-model"]) == 2
    assert watchmen.main(["w", "fragment", "X", "--jiggle-model", "pivot"]) == 2
    assert "--jiggle-model" in capsys.readouterr().out


def test_positional_normals_are_ignored_as_in_1_3_0(tmp_path):
    plain = _write(tmp_path / "a.glb", None)  # passes N positionally, no `normals=`
    A = parse_glb(tmp_path / "a.glb").j["meshes"][0]["primitives"][0]["attributes"]
    assert set(A) == {"POSITION", "TEXCOORD_0"}
    V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    U = [(0, 0), (1, 0), (1, 1), (0, 1)]
    SI = np.zeros((4, 4), np.uint8)
    SW = np.tile(np.array([1, 0, 0, 0], np.float32), (4, 1))
    args = (U, SI, SW, [(0, 1, 2), (0, 2, 3)], [(0, 4, 0, 2, 56)], ["m"], {}, _PAL, None, None)
    (tmp_path / "d").mkdir()
    rig_glb.build_rigged_glb(tmp_path / "d" / "a.glb", V, None, *args, static=True)
    assert (tmp_path / "d" / "a.glb").read_bytes() == plain


def test_sync_flag_without_markers_has_no_opinion():
    """Review m5: the engine's result is not defined there; no shipped transition."""
    t = node(asm.CLS_TRANS, "{t}", m_tsupersyncpos=True)
    assert asm.sync_markers(t) == [] and asm.sync_window(t) is None
    assert asm.transition_playpos(t, 0.4) == -1.0  # was: the outgoing position
    run = state(None, "Run", m_nstartplaypos=0.3)
    assert asm.start_playpos(run, t, None, 0.4) == (0.3, False, "target_default")


# ------------------------------------------------------------------ review m6 - m8, m10
import decode_sequence as ds


def test_toc_old_attribute_names_can_be_written_too():
    t = we.Toc()
    assert t.data_size == 0 and t.best_stream is None  # a fresh Toc no longer raises
    t.flag, t.pairs, t.variants, t.unknown = 1, [(8, 16)], [5, 0, 0, 0, 0, 0], 0x1234
    assert (t.has_stream, t.streams, t.sizes, t.type_hash) == (
        True,
        [(8, 16)],
        [5, 0, 0, 0, 0, 0],
        0x1234,
    )
    assert (t.flag, t.pairs, t.variants, t.unknown, t.data_size) == (
        1,
        [(8, 16)],
        [5, 0, 0, 0, 0, 0],
        0x1234,
        5,
    )


def test_option_values_are_range_checked():
    import argparse

    assert we._model_lod_arg("all") == "all" and we._model_lod_arg("2") == 2
    for bad in ("-1", "x", "1.5"):
        with pytest.raises(argparse.ArgumentTypeError):
            we._model_lod_arg(bad)
    assert we._language_arg("5") == 5
    for bad in ("6", "-1", "uk"):
        with pytest.raises(argparse.ArgumentTypeError):
            we._language_arg(bad)
    h, s = _skinned_model()
    M = we.parse_model_header(h)
    with pytest.raises(ValueError, match="LOD"):
        we.select_model_buffers(M, -1)  # used to select nothing -> silent legacy scan
    with pytest.raises(ValueError, match="language"):
        we.parse_block_toc(b"\0" * 400, language=7)
    with pytest.raises(ValueError, match="not a block header"):
        we.parse_block_header(b"\0" * 100)  # was a bare struct.error


def test_sequence_parse_budget_is_per_call_and_per_thread():
    assert isinstance(ds._BUDGET, __import__("threading").local)
    ds._BUDGET.left = 7  # as if an outer parse were in progress
    ds.parse_exact(b"\0" * 12)
    assert ds._BUDGET.left == 7
