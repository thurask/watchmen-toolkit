"""anim_meta: the game's pairing table, events and partner placement.

Everything is built from synthetic fragments and clips -- no game files.  The
fixtures mirror the shapes measured in the shipped data (2026-10-02): a master
state names its slave through `m_imasterof`, the partner class files the slave
under `SlaveStates` by `m_istategroupid`, and both halves of a paired clip key
an absolute GamePivot track in one shared scene.
"""

import json
import struct

import numpy as np
import pytest

import anim_meta as am
import anim_state_machine as asm
import engine_enums as ee

RORSCHACH, ENEMY_01, ENEMY_04 = 1, 3, 7


# ------------------------------------------------------------------ builders
def crit(label, kind=2, enum=11, value=0, var=0, neg=False, kids=()):
    n = asm.Node(label, asm.CLS_CRIT, "{criteria: %s}" % label)
    n.props = {
        "m_ianimationcriteria": kind,
        "m_ianimationenum": enum,
        "m_ianimationenumvalue": value,
        "m_ianimationvalue": var,
        "m_tnot": neg,
    }
    for k in kids:
        k.parent = n
        n.children.append(k)
    return n


def with_criteria(node, *crits):
    f = asm.Node(node.id + "/c", "Folder", "Criterias")
    f.parent = node
    node.children.append(f)
    for c in crits:
        c.parent = f
        f.children.append(c)
    return node


def clip_bytes(tracks, keys, duration, order="<", scale=1):
    """A minimal .animation: header, track-name table, then one record per track.

    tracks: [(name, [xyz,...] or None, quat_xyzw)] -- type 0 (const quat +
    int16/1000 position keys) when positions are given, else type 3.
    """
    rate = (keys - 1) / duration
    b = struct.pack(order + "2f3I", rate, duration, 0, keys, scale)
    b += struct.pack(order + "I", len(tracks))
    for name, _p, _q in tracks:
        s = name.encode() + b"\x00"
        b += struct.pack(order + "I", len(s)) + s
    for _name, pos, q in tracks:
        if pos is None:
            b += bytes([3]) + struct.pack(order + "3f", 0, 0, 0) + b"\x00" * 4
            b += struct.pack(order + "4f", *q)
        else:
            b += bytes([0]) + struct.pack(order + "H", len(pos)) + struct.pack(order + "4f", *q)
            for p in pos:
                b += struct.pack(order + "3h", *[int(round(v * 1000)) for v in p])
    return b


IDENT = (0.0, 0.0, 0.0, 1.0)


def write_clip(root, name, gp, interact=None, keys=11, duration=2.0):
    """gp / interact: (start_xyz, end_xyz); positions are lerped over `keys`."""

    def lerp(a, b):
        return [
            tuple(np.array(a) + (np.array(b) - np.array(a)) * i / (keys - 1)) for i in range(keys)
        ]

    tracks = [("GamePivot", lerp(*gp), IDENT), ("Bip", None, IDENT)]
    if interact is not None:
        tracks.append(("interact", lerp(*interact), IDENT))
    d = root / "extracted" / "Animation" / name.split("_")[0]
    d.mkdir(parents=True, exist_ok=True)
    (d / (name + ".animation")).write_bytes(clip_bytes(tracks, keys, duration))


class Frag:
    """Builds a fragment JSON in the shape tree_from_json() reads."""

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

    def criteria(self, owner, *specs):
        f = self.add("Folder", "Criterias", owner)
        for label, value, neg in specs:
            self.add(
                "AnimationCriteriaWM",
                "{criteria: %s}" % label,
                f,
                m_ianimationcriteria=2,
                m_ianimationenum=11,
                m_ianimationenumvalue=value,
                m_ianimationvalue=0,
                m_tnot=neg,
            )

    def state(self, name, parent, clip, events=(), **props):
        s = self.add("AnimationStateWM", name, parent, **props)
        layers = self.add("Folder", "Layers", s)
        b = self.add("AnimationBlendWM", "{MOTION_LAYER_1}", layers, m_nweight=1.0)
        self.add("AnimationSlotWM", "{%s.animation}" % clip, b, m_nweight=1.0)
        if events:
            ev = self.add("Folder", "Events", s)
            for label, pos in events:
                self.add(
                    "AnimationEventWM",
                    "{event %s at pos %s}" % (label, pos),
                    ev,
                    m_nplaypos=pos,
                    m_ieventtype=0,
                    m_ianimationevent=ee.ident("ANIMATION_EVENT", label),
                    m_nvalue=0.0,
                )
        return s

    def write(self, root, classname):
        d = root / "extracted" / "TNT" / "CharacterAnimation"
        d.mkdir(parents=True, exist_ok=True)
        j = {"instances": [self.cls], "nodes_full": self.nodes}
        (d / ("AnimationClass%s.fragment.json" % classname)).write_text(json.dumps(j))


@pytest.fixture
def extract(tmp_path):
    """Hero `Rorschach` with one finisher (master of 8) and a looping run; enemy
    classes `Enemy01` and `Enemy04` each file a slave group 8 with a child per
    attacker.  Enemy04's victim clip is a different length."""
    h = Frag()
    g = h.add("AnimationStateGroupWM", "FinishingMovesGroup")
    h.state(
        "Finish_move_A",
        g,
        "RSH_COM_ATT_finish_EN1_A",
        events=[("KILL_ANIMATION_PARTNER", 0.7), ("IMPACT_EFFECTS", 0.25)],
        m_imasterof=8,
        m_tislooping=False,
    )
    h.state("Run", g, "RSH_COM_MOV_run_cycle", m_imasterof=0, m_tislooping=True)
    # the hero is the only class that mentions ENEMY_01, so the label is learnable
    h.criteria(
        h.state("OnlyVsEn1", g, "RSH_COM_ATT_kick", m_imasterof=0), ("ENEMY_01", ENEMY_01, False)
    )
    h.write(tmp_path, "Rorschach")

    for cname, ctype, clip in (
        ("Enemy01", ENEMY_01, "EN1_COM_DMG_finish_RSH_A"),
        ("Enemy04", ENEMY_04, "EN4_COM_DMG_finish_RSH_A"),
    ):
        e = Frag()
        root = e.add("AnimationClassWM", cname + "AnimationClass", m_ianimationmodeltype=ctype)
        sl = e.add("Folder", "SlaveStates", root)
        grp = e.add("AnimationStateGroupWM", "FinishingGroup_Victim_01", sl, m_istategroupid=8)
        e.criteria(e.state("Finished_by_Rorshack_A", grp, clip), ("RORSCHACH", RORSCHACH, False))
        e.criteria(
            e.state("Finished_by_NiteOwl_A", grp, clip.replace("RSH", "NTO")),
            ("NITE_OWL", 2, False),
        )
        e.write(tmp_path, cname)

    # master starts 0.5 m behind the origin; its interact marker is 1.5 m ahead
    write_clip(
        tmp_path,
        "RSH_COM_ATT_finish_EN1_A",
        ((0, 1, -0.5), (0, 1, 0)),
        ((0.1, 0, 1.5), (0.1, 0, 1.0)),
    )
    # the partner's own start is the marker mirrored through the origin
    write_clip(tmp_path, "EN1_COM_DMG_finish_RSH_A", ((-0.1, 1, -1.0), (-0.1, 1, -2.0)))
    write_clip(
        tmp_path, "EN4_COM_DMG_finish_RSH_A", ((-0.1, 1, -1.0), (-0.1, 1, -2.0)), duration=1.2
    )
    write_clip(tmp_path, "RSH_COM_MOV_run_cycle", ((0, 1, 0), (0, 1, 6)))
    write_clip(tmp_path, "RSH_COM_MOV_unused", ((0, 1, 0), (0, 1, 1)))
    return tmp_path


# ------------------------------------------------------------------ criteria
def test_partner_type_criteria_accept_and_reject():
    """A slave child is chosen by the MASTER's character type.  Getting this
    wrong hands the pose packer the other attacker's victim clip."""
    s = with_criteria(
        asm.Node("s", asm.CLS_STATE, "Finished_by_Rorshack"), crit("RORSCHACH", value=1)
    )
    assert am.accepts_partner(s, RORSCHACH)
    assert not am.accepts_partner(s, 2)


def test_negated_and_any_of_criteria():
    """`NOT ENEMY_02_BIG_GUY` and `ANY OF(ENEMY_01|ENEMY_03)` both occur on real
    master and slave states; ANY_OF is a criteria node whose children decide."""
    neg = with_criteria(asm.Node("a", asm.CLS_STATE, "Throw"), crit("NOT BIG", value=4, neg=True))
    assert am.accepts_partner(neg, ENEMY_01) and not am.accepts_partner(neg, 4)
    anyof = crit(
        "ANY OF", kind=11, value=3, kids=[crit("ENEMY_01", value=3), crit("ENEMY_03", value=6)]
    )
    st = with_criteria(asm.Node("b", asm.CLS_STATE, "Countered_by_EN1"), anyof)
    assert am.accepts_partner(st, 3) and am.accepts_partner(st, 6) and not am.accepts_partner(st, 7)


def test_criteria_about_other_variables_do_not_filter():
    """Weapon criteria (enum 5/12) are not about the partner's model type.
    Treating them as a partner-type test would silently drop valid pairs.

    (Format 1 also pinned here that enum 11 with "value slot" 14 or 23 is a
    different variable.  The engine never reads m_ianimationvalue for an ENUM
    criterion -- AnimationCriteriaMet 0x5c5781 -- so that half moved to
    test_anim_meta_v2.py with the opposite expectation.)"""
    weapon = crit("BASH_2H", enum=12, value=1)
    st = with_criteria(asm.Node("c", asm.CLS_STATE, "x"), weapon)
    assert am.accepts_partner(st, RORSCHACH)


# ---------------------------------------------------------------- placement
def _facts(gp_start, interact_start=None, yaw=0.0):
    f = {"game_pivot": {"pos_start": list(gp_start), "yaw_start_deg": yaw}, "interact": None}
    if interact_start is not None:
        f["interact"] = {"pos_start": list(interact_start)}
    return f


def test_placement_marker_and_game_pivot_agree():
    """The engine starts the partner on the master's interact marker, turned
    180 degrees.  On most pairs the partner clip's own GamePivot start, turned
    the same way, lands on that marker -- the per-pair data check."""
    pl = am.placement(_facts((0, 1, -0.5), (0.1, 0, 1.5)), _facts((-0.1, 1, -1.0)))
    assert pl["source"] == "interact marker"
    assert pl["partner_start_xz"] == [0.1, 1.0]
    assert pl["partner_offset_xz"] == [0.1, 1.5]
    assert abs(pl["partner_yaw_deg"]) == pytest.approx(180.0)
    assert pl["check"]["agreement_m"] == pytest.approx(0.0, abs=1e-6)
    assert pl["partner_origin_shift_xz"] == [0.0, 0.0]


def test_placement_uses_the_marker_when_the_partner_clip_is_offset():
    """Three shipped EN1 victim clips sit a constant 3.925 m from the marker.
    The engine never reads the partner clip's absolute start (it moves the
    partner by GamePivot(t) - GamePivot(0)), so the marker stands and the shift
    says how far the partner's whole track must move."""
    pl = am.placement(_facts((0, 1, 0), (0.0, 0, 1.5)), _facts((0, 1, 2.425)))
    assert pl["partner_start_xz"] == [0.0, 1.5]
    assert pl["check"]["agreement_m"] == pytest.approx(3.925)
    assert pl["partner_origin_shift_xz"] == [0.0, pytest.approx(3.925)]


def test_placement_uses_the_engine_default_when_interact_is_not_authored():
    """CharacterRoot.StateActive 0x6b9202: an interact track that is exactly zero
    at t=0 is replaced by (0.11, 0.04, 1.12) -- not by the partner clip's own
    start, and not by 'partner at the master's feet'."""
    pl = am.placement(_facts((0, 1, 0), (0, 0, 0)), _facts((-0.12, 1, -1.29)))
    assert pl["source"].startswith("engine default")
    assert pl["partner_offset_xz"] == [0.11, 1.12]
    assert pl["check"]["partner_game_pivot_start_xz"] == [0.12, 1.29]
    assert pl["check"]["agreement_m"] == pytest.approx(0.1703, abs=1e-3)
    no_track = am.placement(_facts((0, 1, 0)), _facts((0, 1, -1)))
    assert no_track["partner_offset_xz"] == [0.11, 1.12], "a clip with no interact track at all"


def test_placement_offset_is_in_the_master_nodes_frame():
    """The engine transforms the marker by the master NODE's matrix, so a master
    whose GamePivot is turned at t=0 turns the offset and the partner with it."""
    pl = am.placement(_facts((0, 1, 0), (0, 0, 2.0), yaw=90.0), _facts((0, 1, -2.0)))
    assert pl["partner_offset_xz"] == [pytest.approx(2.0), pytest.approx(0.0, abs=1e-6)]
    assert pl["partner_yaw_deg"] == pytest.approx(-90.0)


def test_placement_needs_position_tracks():
    assert am.placement({"game_pivot": {}}, _facts((0, 1, 0))) is None


# -------------------------------------------------------------------- clips
def test_clip_facts_reads_header_and_root_tracks(extract):
    f = am.clip_facts(am.find_clips(str(extract))["rsh_com_att_finish_en1_a"])
    assert (f["key_count"], f["duration_s"], f["frame_rate_scale"]) == (11, 2.0, 1)
    assert f["key_rate_hz"] == pytest.approx(5.0)
    assert f["game_pivot"]["pos_start"] == [0.0, 1.0, -0.5]
    assert f["game_pivot"]["pos_end"] == [0.0, 1.0, 0.0]
    assert f["interact"]["pos_start"] == [0.1, 0.0, 1.5]
    assert f["game_pivot"]["yaw_start_deg"] == 0.0


# -------------------------------------------------------------------- build
def test_build_pairs_from_the_game_table(extract):
    """master_of -> SlaveStates id -> child chosen by the master's type."""
    m = am.build(str(extract))
    assert m["format"] == am.FORMAT
    assert m["classes"]["Rorschach"]["character_type"] == "RORSCHACH"  # learned from the labels
    assert m["classes"]["Enemy04"]["character_type_id"] == ENEMY_04
    got = {(p["partner_class"], p["partner_clip"]) for p in m["pairs"]}
    assert got == {
        ("Enemy01", "EN1_COM_DMG_finish_RSH_A"),
        ("Enemy04", "EN4_COM_DMG_finish_RSH_A"),
    }, "the NiteOwl children must be rejected by their criteria"
    for p in m["pairs"]:
        assert p["master_clip"] == "RSH_COM_ATT_finish_EN1_A" and p["master_of"] == 8


def test_build_marks_the_same_duration_partner_primary(extract):
    """The table links a master to every class with that slave id; the authored
    partner is the one whose clip is exactly as long."""
    by = {p["partner_class"]: p for p in am.build(str(extract))["pairs"]}
    assert by["Enemy01"]["same_duration"] and by["Enemy01"]["primary"]
    assert by["Enemy01"]["confidence"] == "verified"
    assert not by["Enemy04"]["same_duration"] and not by["Enemy04"]["primary"]


def test_build_clip_view_carries_events_loop_and_unused_clips(extract):
    c = am.build(str(extract))["clips"]
    fin = c["RSH_COM_ATT_finish_EN1_A"]
    assert [e["name"] for e in fin["events"]] == ["IMPACT_EFFECTS", "KILL_ANIMATION_PARTNER"]
    assert [e["playpos"] for e in fin["events"]] == [0.25, 0.7]
    assert fin["loop"] is False and c["RSH_COM_MOV_run_cycle"]["loop"] is True
    assert fin["pairs"] and fin["pairs"][0]["role"] == "master"
    assert c["EN1_COM_DMG_finish_RSH_A"]["pairs"][0]["role"] == "partner"
    # a clip no state references still gets its header facts
    assert c["RSH_COM_MOV_unused"]["used_by"] == [] and c["RSH_COM_MOV_unused"]["duration_s"] == 2.0
    # a state may name a clip that has no file (Part 1 leftovers do)
    assert "duration_s" not in c["RSH_COM_ATT_kick"]


def test_build_is_deterministic_and_json_clean(extract):
    a, b = am.build(str(extract)), am.build(str(extract))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_clip_extras_scales_event_times_to_the_written_animation(extract):
    """The writer may retime a clip (locomotion speed sync); events must be
    usable against the animation as written, not only the authored one."""
    m = am.build(str(extract))
    x = am.clip_extras(m, "rsh_com_att_finish_en1_a.animation", fps=10.0, frames=11)
    assert x["clip"] == "RSH_COM_ATT_finish_EN1_A"
    kill = [e for e in x["events"] if e["name"] == "KILL_ANIMATION_PARTNER"][0]
    assert kill["time_s"] == pytest.approx(1.4) and kill["written_time_s"] == pytest.approx(0.7)
    assert [p["other_class"] for p in x["pairs"]] == [
        "Enemy01"
    ], "non-primary candidates are dropped"
    assert am.clip_extras(m, "GRIP 1H") is None


def test_clip_extras_does_not_mutate_the_table(extract):
    m = am.build(str(extract))
    before = json.dumps(m, sort_keys=True)
    am.clip_extras(m, "RSH_COM_MOV_run_cycle", fps=30.0, frames=5)
    assert json.dumps(m, sort_keys=True) == before


def test_event_names_cover_both_caption_styles_and_uncaptioned_events():
    """Captions come as "{event X at pos p}" or "{PLAY_POS [p]: X}", and a third
    of the shipped events have no caption at all -- those take the name other
    events with the same id carry."""

    def ev(caption, eid):
        n = asm.Node(caption, asm.CLS_EVENT, caption)
        n.props = {"m_ianimationevent": eid, "m_nplaypos": 0.5, "m_ieventtype": 0}
        return n

    a, b, c = ev("{event IMPACT at pos 0.3}", 4), ev("{PLAY_POS [0.33]: IMPACT}", 4), ev("", 4)
    d, e = ev("", 99), ev("{event_speedup", 9)
    assert am._event_label(a) == am._event_label(b) == "IMPACT"
    assert am._event_label(c) is None and am._event_label(e) is None
    st = asm.Node("s", asm.CLS_STATE, "s")
    st.children = [a, b, c, d, e]
    names = am.learn_event_names([a, b, c, d, e])
    assert names == {4: "IMPACT"}
    # format 2: the record's name is the exe's for a registered id (9 = SOUND);
    # an id the exe does not register falls back to the caption, then EVENT_n
    assert sorted(x["name"] for x in am._events(st, names)) == [
        "EVENT_99",
        "IMPACT",
        "IMPACT",
        "IMPACT",
        "SOUND",
    ]


# ---------------------------------------------------------------- skeleton
def test_skeleton_extras_names_roots_and_attach_points():
    names = ["interact", "Bip", "Pelvis", "R Hand", "Attach RHand", "GamePivot"]
    x = am.skeleton_extras(names, [-1, -1, 1, 2, 3, -1])
    assert x["joint_names"] == names and x["joint_parents"] == [-1, -1, 1, 2, 3, -1]
    assert (x["motion_root_joint"], x["interact_joint"], x["body_root_joint"]) == (5, 0, 1)
    assert x["roots"] == [0, 1, 5] and x["attach_joints"] == {"Attach RHand": 4}
    # the women's skeleton has GamePivot first and no interact at all
    y = am.skeleton_extras(["GamePivot", "Bip"], [-1, -1])
    assert y["motion_root_joint"] == 0 and y["interact_joint"] is None


# ------------------------------------------------------------------- tree
def test_empty_fragment_does_not_take_the_class_tree_down():
    """Several SoundEvents sub-fragments parse to no instances; one of them used
    to raise IndexError out of load_tree and lose the whole AnimationClass."""
    assert asm.tree_from_json({"instances": [], "nodes_full": []}) == ([], {})


# -------------------------------------------------------------------- glb
def test_write_glb_embeds_names_parents_and_conventions(rig, tmp_path):
    """Importers key on these: without them every skeleton needs a hand-made
    joint layout."""
    import variant_glb
    from conftest import parse_glb

    out = tmp_path / "x.glb"
    variant_glb.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz))
    J = parse_glb(out).j
    assert J["asset"]["extras"]["watchmen"]["format"] == am.FORMAT
    assert "MIRROR" in J["asset"]["extras"]["watchmen"]["conventions"]["handedness"]
    sk = J["skins"][0]
    ex = sk["extras"]["watchmen"]
    assert ex["joint_names"] == [str(n) for n in rig.names]
    assert ex["joint_parents"] == [int(p) for p in rig.par]
    for k, jn in enumerate(sk["joints"]):
        assert J["nodes"][jn]["name"] == "b%d" % k, "node names are unchanged"
        assert J["nodes"][jn]["extras"] == {"bone": str(rig.names[k]), "parent": int(rig.par[k])}
    assert "extras" not in J["animations"][0], "no table given -> no per-clip extras"


def test_write_glb_embeds_clip_metadata_when_given_the_table(rig, tmp_path):
    import variant_glb
    from conftest import parse_glb

    meta = {
        "clips": {
            "clip_test": {
                "duration_s": 2.0,
                "loop": True,
                "events": [
                    {"name": "HIT", "playpos": 0.5, "on_enter": False, "event_id": 1, "value": 0.0}
                ],
                "used_by": [],
                "pairs": [],
            }
        },
        "pairs": [],
    }
    out = tmp_path / "y.glb"
    variant_glb.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz), meta=meta)
    x = parse_glb(out).j["animations"][0]["extras"]["watchmen"]
    assert x["loop"] is True and x["written_fps"] == pytest.approx(rig.fps)
    assert x["events"][0]["time_s"] == pytest.approx(1.0)
    assert x["events"][0]["written_time_s"] == pytest.approx(0.5 * (rig.F - 1) / rig.fps)
