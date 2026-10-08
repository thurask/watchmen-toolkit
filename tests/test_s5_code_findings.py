"""Rules read from the executable after the six-set export, as the toolkit applies them.

animation   the game's animation type rule (0x5f277a) and the two computed flags (0x5f0e63);
            the editor's event argument table; the twist-bone pass (0x5958f5)
level       waypoint links (0x8b1062), culling groups, stream blocks, swinging props,
            lights, the action track of a sequence node (0x49d529), camera tours, the
            property filter tables, PVSRootNode visibility (0x48e028), parentLink,
            SubPivot overrides, LOD override, a stored sheet id 0 (0x4a4c44), terrain
models      triangle strips (0x431206), console format 10 joints, cloth world fixes
fragments   the typed stream framing
sound       one-track streams, local default packages, music one-shots
Synthetic fixtures only."""

import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import anim_state_machine as asm
import bake_v4
import characters_export as ce
import combat_meta as cm
import decode_sequence as ds
import fx_meta
import kapow_fragment as kf
import kapow_props as kp
import level_meta as lm
import ragdoll_rig as rr
import sound_meta as sm
import test_level_meta as tl
import test_p4_level_terrain as tt
import watchmen_extract as we

ID = [0.0, 0.0, 0.0, 1.0]


# ------------------------------------------------------------------ animation type
def _state(name="s", **props):
    n = asm.Node(name, asm.CLS_STATE, name)
    n.props = dict(props)
    return n


def _group(name="g"):
    return asm.Node(name, asm.CLS_GROUP, name)


def _crit(**props):
    n = asm.Node("c", asm.CLS_CRIT, "c")
    n.props = dict(props)
    return n


def _adopt(parent, *kids):
    for k in kids:
        k.parent = parent
        parent.children.append(k)
    return parent


def test_animation_type_is_the_first_mapped_criterion_of_the_state_then_its_groups():
    outer = _adopt(_group("outer"), _crit(m_ianimationcriteria=1, m_ianimationaction=7))
    inner = _adopt(_group("inner"), _crit(m_ianimationcriteria=1, m_ianimationaction=21))
    _adopt(outer, inner)
    s = _adopt(_state(m_ianimationtype=18), _crit(m_ianimationcriteria=2, m_ianimationenum=4))
    _adopt(inner, s)
    # own criteria give nothing, action 21 is not mapped, the outer group's HEAVY_PUNCH is 5
    assert asm.determine_animation_type(s) == 5 == am.determine_animation_type(s)
    rec = am.state_record(s)
    assert rec["animation_type"] == {"id": 5, "name": "HEAVYATTACK"}
    assert rec["animation_type_stored"]["id"] == 18
    assert "0x5f0e63" in rec["animation_type_basis"] and "inferred" in rec["animation_type_basis"]
    # a state's own criterion wins over a group's
    own = _adopt(_state(), _crit(m_ianimationcriteria=1, m_ianimationaction=0))
    _adopt(inner, own)
    assert asm.determine_animation_type(own) == 4
    assert asm.determine_animation_type(_state(m_ianimationtype=9)) == 0  # stored only
    assert asm.TYPE_BY_ACTION[12] == 8 and len(asm.TYPE_BY_ACTION) == 12


def test_character_mode_stunned_and_the_any_of_rule():
    stun = _crit(m_ianimationcriteria=2, m_ianimationenum=1, m_ianimationenumvalue=3)
    assert asm.criterion_animation_type(stun) == 12
    other_var = _crit(m_ianimationcriteria=2, m_ianimationenum=4, m_ianimationenumvalue=3)
    assert asm.criterion_animation_type(other_var) == 0  # only variable 1 counts (0x5ebe9b)
    # ANY_OF: the kind of the first child, the values of the ANY_OF node itself
    any_of = _crit(m_ianimationcriteria=11, m_ianimationaction=3)
    _adopt(any_of, _crit(m_ianimationcriteria=1, m_ianimationaction=0))
    assert asm.criterion_animation_type(any_of) == 9
    assert asm.criterion_animation_type(_crit(m_ianimationcriteria=11)) == 0  # no child


def test_upper_and_heavy_flags_are_computed_not_read():
    g = _adopt(_group(), _crit(m_ianimationcriteria=1, m_ianimationaction=7))
    s = _adopt(g, _state(m_idamagepose=8, m_tupperattack=False))
    s = g.children[-1]
    assert cm.state_flags(s) == {"upper_attack": True, "heavy_attack": True}
    low = _state(m_idamagepose=11, m_tupperattack=True, m_theavyattack=True, m_tallowsweepatt=1)
    assert cm.state_flags(low) == {"sweep": True}  # the stored flags are not used
    assert 8 in asm.UPPER_DAMAGE_POSES and 11 not in asm.UPPER_DAMAGE_POSES
    assert "upper_attack" not in dict(cm.STATE_FLAGS)
    # a negated or nested HEAVY_PUNCH still counts only at the top level
    nested = _crit(m_ianimationcriteria=11)
    _adopt(nested, _crit(m_ianimationcriteria=1, m_ianimationaction=7))
    assert "heavy_attack" not in cm.state_flags(_adopt(_state(), nested))


# ------------------------------------------------------------------ editor parameters
def test_event_editor_params_table_and_hidden_slots():
    t = fx_meta.EVENT_EDITOR_PARAMS
    assert len(t["events"]) == 16 and t["events"]["90"]["handler"] is None
    assert "0x5c1767" in t["_source"] and 90 not in fx_meta.EVENT_FIELDS
    assert t["events"]["59"]["params"]["m_nvalue"]["caption"] == "Transition time"
    assert "m_nvalue09" not in t["events"]["59"]["params"]  # read by the game, hidden there
    ev = asm.Node("e", asm.CLS_EVENT, "e")
    ev.props = {"m_ianimationevent": 59, "m_nvalue09": 1.5, "m_nvalue02": 2.0, "m_ttruth1": True}
    assert fx_meta.editor_hidden(ev) == ["m_nvalue09"]
    ev.props = {"m_ianimationevent": 58, "m_ivalue00": 3, "m_tforceupdateblends": True}
    assert fx_meta.editor_hidden(ev) == ["m_ivalue00"]  # an id the table does not list
    name, why = fx_meta.EVENT_FIELDS[fx_meta.EV_SAFE_RAGDOLL][1]["m_nvalue"]
    assert name == "safe_time_s" and "Ragdoll Safe Time" in why
    assert "FEET" in fx_meta.EVENT_FIELDS[fx_meta.EV_SOUND][1]["m_ivalue00"][1]
    assert "0x62f298" in fx_meta.TRANSITION_EDITOR_VISIBILITY_EVIDENCE
    assert fx_meta.TRANSITION_EDITOR_VISIBILITY["m_npitchto"] == "m_tpitch"
    assert "criteria_units" in am.CONVENTIONS and "radians" in am.CONVENTIONS["criteria_units"]


# ------------------------------------------------------------------ twist pass
def test_twist_pairs_take_the_lower_sibling():
    names = ["Root", "UpperArm", "Forearm", "ForeTwist", "ForeTwist1", "Hand", "LoneTwist"]
    par = [-1, 0, 1, 1, 3, 2, 5]
    # ForeTwist1's parent is a twist bone; LoneTwist has no lower sibling
    assert bake_v4.twist_pairs(names, par) == [(3, 2)]
    assert bake_v4.twist_pairs(["ATwist", "B"], [-1, -1]) == []  # a root is never a twist


def test_twist_align_puts_the_x_axis_on_the_partners_and_carries_the_child():
    names = ["Root", "Forearm", "ForeTwist", "ForeTwist1"]
    par = [-1, 0, 0, 2]
    rz = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])  # X -> +Y
    Wr = np.tile(np.eye(3), (2, 4, 1, 1))
    Wr[0, 1] = rz
    Wt = np.zeros((2, 4, 3))
    Wt[:, 2] = [1.0, 0.0, 0.0]
    Wt[:, 3] = [2.0, 0.0, 0.0]
    assert bake_v4.apply_twist_align(Wr, Wt, names, par) == [(2, 1)]
    assert Wr[0, 2][:, 0] == pytest.approx([0.0, 1.0, 0.0], abs=1e-12)
    assert Wr[0, 3] == pytest.approx(Wr[0, 2], abs=1e-12)
    assert Wt[0, 2] == pytest.approx([1.0, 0.0, 0.0])  # the twist bone keeps its position
    assert Wt[0, 3] == pytest.approx([1.0, 1.0, 0.0], abs=1e-12)  # the child swings round it
    # frame 1: the two X axes agree already, nothing moves (|a x b| <= 1e-5)
    assert Wr[1, 2] == pytest.approx(np.eye(3)) and Wt[1, 3] == pytest.approx([2.0, 0.0, 0.0])


def test_twist_align_is_on_by_default_and_an_untwisted_cache_is_not_current(tmp_path):
    import inspect

    sig = inspect.signature(bake_v4.bake)
    assert sig.parameters["twist_align"].default is None
    assert sig.parameters["track_names"].default == "exact"
    for flag, ok in ((0, False), (1, True)):
        p = tmp_path / ("c%d.npz" % flag)
        np.savez(
            str(p),
            pal=np.zeros((1, 1, 3, 4), np.float32),
            rule=np.int32(bake_v4.POSE_RULE),
            scan=np.int32(bake_v4.NAME_SCAN_START),
            twist_align=np.int32(flag),
        )
        assert ce.bake_is_current(str(p)) is ok


def _twist_bind(tmp_path):
    """root, Arm and its sibling `Bip02 ArmTwist`, Hand under the twist bone."""
    p = tmp_path / "bind_tw_file_v1.npz"
    np.savez(
        p,
        Rb=np.tile(np.eye(3), (4, 1, 1)),
        tb=np.array([[0, 0, 0], [1, 0, 0], [1, 0, 0], [2, 0, 0]], float),
        tloc=np.array([[0, 0, 0], [1, 0, 0], [1, 0, 0], [1, 0, 0]], float),
        par=np.array([-1, 0, 0, 2]),
        names=np.array(["root", "Arm", "Bip02 ArmTwist", "Hand"]),
    )
    return str(p)


def _angle_deg(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def test_a_track_binds_to_the_bone_of_the_same_name_only(tmp_path):
    import test_p6_anim as tpa

    bind = _twist_bind(tmp_path)
    h = np.radians(40.0) / 2
    qy = (0.0, float(np.sin(h)), 0.0, float(np.cos(h)))
    clip = tpa._clip([("root", 3, ((0, 0, 0), ID)), ("ArmTwist", 3, ((0, 0, 0), qy))])
    kw = dict(bind=bind, bank={"c": clip}, twist_align=False)
    exact, _ = bake_v4.bake("c", 1, track_names="exact", **kw)
    assert bake_v4.bake("c", 1, **kw)[0] == pytest.approx(exact)  # the default
    # binds are identity, so a palette rotation is the bone's world (= local) rotation
    assert _angle_deg(exact[0, 2, :, :3]) == pytest.approx(0.0, abs=1e-3)
    prefix, _ = bake_v4.bake("c", 1, track_names="prefix", **kw)
    assert _angle_deg(prefix[0, 2, :, :3]) == pytest.approx(40.0, abs=0.01)
    with pytest.raises(ValueError, match="track_names"):
        bake_v4.bake("c", 1, track_names="index", **kw)


def test_the_twist_pass_runs_by_default_in_the_engine_gauge_only(tmp_path):
    import test_p6_anim as tpa

    bind = _twist_bind(tmp_path)
    h = np.radians(30.0) / 2
    qz = (0.0, 0.0, float(np.sin(h)), float(np.cos(h)))
    clip = tpa._clip([("root", 3, ((0, 0, 0), ID)), ("Arm", 3, ((0, 0, 0), qz))])
    kw = dict(bind=bind, bank={"c": clip})
    on, _ = bake_v4.bake("c", 1, **kw)
    off, _ = bake_v4.bake("c", 1, twist_align=False, **kw)
    # Arm's X axis is turned 30 degrees; the twist bone follows it only with the pass
    assert _angle_deg(off[0, 2, :, :3]) == pytest.approx(0.0, abs=1e-3)
    assert _angle_deg(on[0, 2, :, :3]) == pytest.approx(30.0, abs=0.01)
    assert on[0, 2, :, 0] == pytest.approx(on[0, 1, :, 0], abs=1e-4)
    assert on[0, 3, :, :3] == pytest.approx(on[0, 2, :, :3], abs=1e-6)  # the child follows
    try:
        # conj=False: the default leaves the pass out; asking for it is an error
        plain, _ = bake_v4.bake("c", 1, conj=False, **kw)
        assert _angle_deg(plain[0, 2, :, :3]) == pytest.approx(0.0, abs=1e-3)
        with pytest.raises(ValueError, match="twist_align"):
            bake_v4.bake("c", 1, conj=False, twist_align=True, **kw)
    finally:
        bake_v4.CONJ = True


def test_the_character_export_picks_the_track_lookup_by_part(tmp_path):
    import inspect

    assert ce.track_names_for(str(tmp_path)) == "exact"
    d = tmp_path / "extracted" / "TNT" / "Production" / "Fragments" / "Enemy"
    d.mkdir(parents=True)
    (d / "Biker.fragment").write_bytes(b"")
    assert ce.track_names_for(str(tmp_path)) == "prefix"  # Part 1
    src = inspect.getsource(ce.bake_cache)
    assert src.count("track_names=_tn") == 2 and "twist_align=np.int32(1)" in src
    assert "bake_is_current(dst, clips[nm], _tn, _bsha)" in src
    import char_lib, face_export

    assert "track_names_for(extract_out)" in inspect.getsource(char_lib.build_all)
    for fn in (face_export.export, ce._face_attach):
        s = inspect.getsource(fn)
        assert "twist_align=False" in s and 'track_names="prefix"' in s


def test_a_cached_bake_of_the_other_track_lookup_is_not_current(tmp_path):
    for stored in ("exact", "prefix", None):
        p = tmp_path / ("c_%s.npz" % stored)
        kw = dict(
            pal=np.zeros((1, 1, 3, 4), np.float32),
            rule=np.int32(bake_v4.POSE_RULE),
            scan=np.int32(bake_v4.NAME_SCAN_START),
            twist_align=np.int32(1),
        )
        if stored:
            kw["track_names"] = np.str_(stored)
        np.savez(str(p), **kw)
        assert ce.bake_is_current(str(p))  # no lookup named: not tested
        for want in ("exact", "prefix"):
            # a bake without the key (written before it was stored) is not tested either
            assert ce.bake_is_current(str(p), None, want) is (stored in (want, None))


class _Entry:
    def __init__(self, name):
        self.name = name


def _fake_archive(monkeypatch, tmp_path, blocks):
    """An archive file whose blocks are `blocks`: [[(entry name, bytes)]]."""
    import export_female_anims as efa

    naz = tmp_path / "game.naz"
    naz.write_bytes(b"")
    read = []
    monkeypatch.setattr(
        efa, "grab_blocks", lambda _naz: {"b%d" % i: {"h": i} for i in range(len(blocks))}
    )

    def extract_block(h, s=None):
        read.append(h)
        return [(_Entry(n), d, None) for n, d in blocks[h]]

    monkeypatch.setattr(we, "extract_block", extract_block)
    return str(naz), read


def test_a_bake_outside_the_export_uses_the_track_lookup_of_the_clips_set(tmp_path, monkeypatch):
    import test_p6_anim as tpa
    import watchmenlib as wl

    bind = _twist_bind(tmp_path)
    h = np.radians(40.0) / 2
    qy = (0.0, float(np.sin(h)), 0.0, float(np.cos(h)))
    clip = tpa._clip([("root", 3, ((0, 0, 0), ID)), ("ArmTwist", 3, ((0, 0, 0), qy))])
    part2 = [[("Animation/EN1/c.animation", clip)], [("TNT/Fragments/Enemy/Thug.fragment", b"")]]
    part1 = part2 + [[("TNT\\Production\\Fragments\\Enemy\\Biker.fragment", b"")]]
    for blocks, rule, angle in ((part2, "exact", 0.0), (part1, "prefix", 40.0)):
        naz, read = _fake_archive(monkeypatch, tmp_path, blocks)
        assert wl.bake_track_names("c", naz=naz) == (rule, clip)
        assert read == list(range(len(blocks)))  # every block: the mark may follow the clip
        del read[:]
        assert bake_v4.archive_clip("c", naz) == clip and read == [0]  # stops at the clip
        assert bake_v4.archive_clip("nope", naz) is None
        pal, _ = wl.bake("c", bind, 1, naz=naz)
        # binds are identity and the twist pass turns the twist bone onto Arm (0°): only
        # the bone's child shows which lookup ran, so read the lookup through bake_v4
        got = {}
        real = bake_v4.bake

        def spy(*a, **k):
            got.update(k)
            return real(*a, **k)

        monkeypatch.setattr(bake_v4, "bake", spy)
        wl.bake("c", bind, 1, naz=naz)
        monkeypatch.setattr(bake_v4, "bake", real)
        assert got["track_names"] == rule and got["bank"] == {"c": clip}
        off, _ = real("c", 1, bind=bind, bank={"c": clip}, twist_align=False, track_names=rule)
        assert _angle_deg(off[0, 2, :, :3]) == pytest.approx(angle, abs=0.01)
    # a clip from a bank names no set; an explicit rule is passed on
    assert wl.bake_track_names("c", bank={"c": clip}, naz=naz) == ("exact", None)
    assert wl.bake_track_names("c", naz=str(tmp_path / "missing.naz")) == ("exact", None)
    monkeypatch.setattr(bake_v4, "bake", lambda *a, **k: k["track_names"])
    assert wl.bake("c", bind, 1, bank={"c": clip}, track_names="prefix") == "prefix"
    assert wl.PART1_MARK == "/fragments/enemy/biker.fragment"


def test_the_contact_check_bakes_with_the_track_lookup_of_the_set(tmp_path, monkeypatch):
    import inspect

    assert am._ContactCheck(str(tmp_path)).track_names == "exact"
    np.savez(
        str(tmp_path / "bind_rsh_file_v1.npz"),
        names=np.array(["GamePivot"]),
        Rb=np.eye(3)[None],
        tb=np.zeros((1, 3)),
    )
    seen = []

    def bake(nm, ups, **kw):
        seen.append(kw["track_names"])
        return np.tile(np.eye(3, 4), (2, 1, 1, 1)), 1.0

    monkeypatch.setattr(bake_v4, "bake", bake)
    for rule in ("exact", "prefix"):
        am._ContactCheck(str(tmp_path), rule)._load(str(tmp_path / "RSH_a.animation"))
    assert seen == ["exact", "prefix"]
    assert "_ContactCheck(binds, characters_export.track_names_for(extract_out))" in (
        inspect.getsource(am._build)
    )


# ------------------------------------------------------------------ level fixture
SCENE, LVL = 0x10, 0x12
WPC, W0, W1, W2, W3, W4 = range(0x20, 0x26)
CG, CB, VG, SB, SB2, ST, ST2 = range(0x30, 0x37)
OB, L5, LF, TOUR, SEQ, CUT, SND, DIRECT, CAM, DEA = range(0x40, 0x4A)
TRUE, STOP, GEN9, GEN10, UF, TU, VIS, SOME, PLAY, HELD = range(0x50, 0x5A)
HIDF, M1, HIDP, M2, M3, SP, SP2, SP3, VOL0, VOLN, LINKP, LINKED = range(0x60, 0x6C)
CKP = 0x7A


def _n(nid, typ, name, parent, order=0, ents=None, lists=None, **props):
    """tl._node with entity (`ents`) and entity-list (`lists`) properties."""
    b = tl._node(nid, typ, name, parent, order, **props)
    for k, v in (ents or {}).items():
        b += tl._u(kp.name_hash(k)) + tl._ent(v)
    for k, v in (lists or {}).items():
        b += tl._u(kp.name_hash(k)) + tl._u(len(v)) + b"".join(tl._ent(x) for x in v)
    return b


@pytest.fixture(scope="module")
def level(tmp_path_factory):
    base = tmp_path_factory.mktemp("s5level") / "extracted"
    scene = tl._node(SCENE, "SceneNode", "", None)
    scene += tl._node(LVL, "SceneScope(LoadBlock)", "Lvl", SCENE, 1, assetName="/L/Lvl.fragment")
    tl._write(base / "L" / "Lvl.scene", tl._fragment(scene))
    f = _n(WPC, "WaypointController(Node)", "wpc", "host", 0, ents={"m_estart": W0, "m_eend": W4},
           m_nmaxdistance=30.0)  # fmt: skip
    way = lambda nid, order, for_all, excl, **kw: _n(
        nid, "waypoint(CollisionBoxNode)", "wp%d" % order, WPC, order,
        localPos=[float(order), 0.0, 0.0], localOrient=ID, m_tforall=for_all,
        m_iexclusivetocharacter=excl, **kw,
    )  # fmt: skip
    f += way(W0, 0, True, 0xFFFFFFFF)
    f += way(W1, 1, False, 0)
    f += way(W2, 2, False, 0, m_tflyingwaypoint=True, m_tenforceminimumheightdifference=True,
             m_nnumberminheight=1.0, m_nnumbermaxheight=3.0)  # fmt: skip
    f += way(W3, 3, True, 0xFFFFFFFF, ents={"m_eforcenext": W1})  # on a for-all node: no effect
    f += way(W4, 4, False, 1)
    f += _n(CG, "CullingGroup(Node)", "cg", "host", 1, lists={"m_evisibilitygrouplist": [VG]})
    f += _n(CB, "CullingBox(CollisionBoxNode)", "cb", CG, 0, localPos=[5.0, 1.0, 0.0],
            localOrient=ID, width=12.5, height=4.0, depth=5.0)  # fmt: skip
    f += _n(VG, "CullingVisibilityGroup(PivotNode)", "vg", "host", 2, localPos=[0.0] * 3,
            localOrient=ID)  # fmt: skip
    f += _n(SB, "StreamBlock(StreamBlockNode)", "Yard", "host", 3, assetName="/L/Yard",
            m_tisscenestartstreamblock=True)  # fmt: skip
    f += _n(SB2, "StreamBlock(StreamBlockNode)", "Cells", "host", 4, assetName="/L/Cells")
    f += _n(ST, "StreamBlockTriggerOneShot(CollisionBoxNode)", "once", "host", 5,
            ents={"m_eloadstreamblock": SB2, "m_eunloadstreamblock": SB})  # fmt: skip
    f += _n(ST2, "StreamBlockTrigger(CollisionBoxNode)", "door", "host", 6,
            ents={"m_estreamblock": SB2})  # fmt: skip
    f += _n(CKP, "TriggerActionCheckpoint(Node)", "cp", "host", 40, _icheckpointid=2,
            ents={"_estreamblock": SB2})  # fmt: skip
    f += _n(OB, "TriggerOscillateBox(Model)", "lamp", "host", 7, localPos=[0.0, 3.0, 0.0],
            localOrient=ID, modelNames=["/art/props/lamp.model"], m_namplitude=0.12,
            m_nfrequency=2.0, m_nfalloff=1.5, m_namplitudez=0.05, m_nfrequencyz=2.0,
            m_nfalloffz=1.5, m_neffectquarentinetime=0.5)  # fmt: skip
    f += _n(L5, "Light", "proj", "host", 8, localPos=[1.0, 2.0, 3.0], localOrient=ID,
            lightType=5, brightness=2.0, range=10.0, attnStart=0.75,
            lightColorRGB=[1.0, 0.5, 0.25])  # fmt: skip
    f += _n(LF, "LightFlicker(Light)", "bulb", "host", 9, localPos=[0.0] * 3, localOrient=ID,
            lightType=2, innerConeAngle=30.0, outerConeAngle=40.0, ignoreGlobalLightFading=True,
            _nbrightnessmin=0.5, _nbrightnessmax=1.0, _nbrighnessrandomizetime=0.1,
            _nrangemin=4.0, _nrangemax=6.0)  # fmt: skip
    f += _n(CAM, "Camera", "cam", "host", 10, localPos=[0.0] * 3, localOrient=ID, fov=60.0)
    f += _n(TOUR, "TriggerActionCamera(Node)", "tour", "host", 11, _iaction=0)
    f += _n(SEQ, "PropertySequenceNode", "seq", TOUR, 0, sequence="/a/t.sequence",
            speedFactor=0.7, autoStart=True, updateCullingDistance=35.0)  # fmt: skip
    f += _n(SND, "TriggerActionSound(Node)", "late", SEQ, 0, _ndelay=3.0, m_iactiontype=0)
    f += _n(CUT, "TriggerActionCamera(Node)", "cut", SEQ, 1, ents={"_ecamera": CAM}, _iaction=1,
            _ndelay=2.0)  # fmt: skip
    f += _n(DEA, "DelayedEmitterActivator(Node)", "smoke", SEQ, 2)  # no stored _ndelay: 0.0
    f += _n(DIRECT, "TriggerActionCamera(Node)", "direct", TOUR, 1, _iaction=1, _ndelay=9.0)
    f += _n(TRUE, "TriggerConditionTrue(Node)", "always", "host", 12, m_treactivatable=True,
            m_treactivationdelay=20.0)  # fmt: skip
    f += _n(STOP, "TriggerActionSound(Node)", "stop", TRUE, 0, m_iactiontype=1,
            _tchildrenafter=True, m_nnumber4=0.5, m_nnumber5=9.0)  # fmt: skip
    f += _n(GEN9, "TriggerActionGeneral(Node)", "move", STOP, 0, m_iactiontype=9, m_iinteger1=2)
    f += _n(GEN10, "TriggerActionGeneral(Node)", "gfx", TRUE, 1, m_iactiontype=10)
    f += _n(PLAY, "TriggerActionSound(Node)", "play", TRUE, 2, m_iactiontype=0,
            _tchildrenafter=True)  # fmt: skip
    f += _n(HELD, "TriggerActionGeneral(Node)", "after", PLAY, 0, m_iactiontype=0)
    f += _n(UF, "TriggerUseFragment(PivotNode)", "lock", "host", 13, m_ilocksegmentcount=2,
            localPos=[0.0] * 3, localOrient=ID)  # fmt: skip
    f += _n(TU, "TriggerUse(Node)", "TriggerUse", UF, 0, m_iusetype=0, _iactivatortype=0)
    f += _n(VIS, "TriggerConditionVisibility(PivotNode)", "look", "host", 14, _icharacter=1,
            _nmaxdist=4.0, localPos=[0.0] * 3, localOrient=ID)  # fmt: skip
    f += _n(SOME, "TriggerConditionLogical(Node)", "some", "host", 15, m_iconditiontype=3,
            m_icount=2)  # fmt: skip
    model = lambda nid, name, parent, order, **kw: _n(
        nid, "Model", name, parent, order, localPos=[1.0, 0.0, 0.0], localOrient=ID,
        modelNames=["/art/props/%s.model" % name], **kw,
    )  # fmt: skip
    f += _n(HIDF, "Folder", "hidden folder", "host", 16, Visible=False)
    f += model(M1, "shown", HIDF, 0)
    f += _n(HIDP, "PVSRootNode", "hidden pvs", "host", 17, Visible=False)
    f += model(M2, "culled", HIDP, 0)
    f += model(M3, "switch", "host", 18, geometryLodOverride=1, geometryLodFactor=0.5,
               includeInReflections=True, includeInAO=False)  # fmt: skip
    f += _n(SP, "SubPivot", "interact", M3, 0, pivotID=1, locked=True,
            localPos=[0.0766, 0.0093, -1.549], localOrient=[-0.5, -0.5, -0.5, 0.5])  # fmt: skip
    f += _n(SP2, "SubPivot", "plain", M3, 1, pivotID=2, localPos=[0.0] * 3, localOrient=ID)
    f += _n(SP3, "SubPivot", "off", SP2, 0, pivotID=3, enabled=False, localPos=[0.0] * 3,
            localOrient=ID)  # fmt: skip
    f += _n(VOL0, "CollisionBoxNode", "nosheet", "host", 19, localPos=[0.0] * 3, localOrient=ID,
            width=1.0, height=1.0, depth=1.0, physicsType=1)  # fmt: skip
    f += tl._u(kp.name_hash("pivotSheet_Id")) + tl._u(0, 0)  # a stored id 0 (biginteger)
    f += _n(LINKP, "PivotNode", "group", "host", 20, localPos=[0.0, 36.0, 0.0], localOrient=ID)
    f += _n(LINKED, "PivotNode", "flee", LINKP, 0, localPos=[1.0, -33.0, 2.0], localOrient=ID,
            parentLink=1)  # fmt: skip
    f += model(0x70, "fleeprop", LINKED, 0)
    tl._write(base / "L" / "Lvl.fragment", tl._fragment(f, name="Lvl_Main", singleton=True))
    return lm.build_level(str(base / "L" / "Lvl.scene"), "Lvl", "%08x" % LVL, None)


def _uid(level, nid):
    (u,) = {
        r["uid"]
        for sec in ("graph",)
        for r in level[sec]["nodes"]
        if r["uid"].endswith(":%08x" % nid)
    } or {"1:%08x" % nid}
    return u


def _node(level, nid):
    return next(r for r in level["graph"]["nodes"] if r["uid"].endswith(":%08x" % nid))


def _edges(level, kind):
    return [e for e in level["graph"]["edges"] if e["kind"] == kind]


def _m(level, name):
    return next(r for r in level["models"] if r["name"] == name)


# ------------------------------------------------------------------ waypoints
def test_waypoint_links_follow_the_engine_walk():
    A, R, N = (True, -1), (False, 0), (False, 1)
    nall, nex = lm.waypoint_links([A, R, R, A, N])
    assert nall == [3, None, None, None, None]
    assert nex == [[1, None], [2, None], [None, None], [None, 4], [None, None]]
    # m_eforcenext on a for-all node changes nothing
    assert lm.waypoint_links([A, R, R, A, N], {3: 1}) == (nall, nex)
    # on an exclusive node it fills that node's own slot ...
    assert lm.waypoint_links([A, R, A, N], {1: 3})[1][1] == [3, None]
    # ... and is replaced when the next sibling is exclusive to the same type
    assert lm.waypoint_links([A, R, R, A], {1: 3})[1][1] == [2, None]
    assert lm.waypoint_links([A]) == ([None], [[None, None]])


def test_waypoints_section(level):
    w = level["waypoints"]
    u = lambda nid: "1:%08x" % nid
    assert w["controller"] == u(WPC) and w["start"] == u(W0) and w["end"] == u(W4)
    assert w["max_distance"] == 30.0 and w["activated_by"] == []
    assert [x["uid"] for x in w["nodes"]] == [u(W0), u(W1), u(W2), u(W3), u(W4)]
    assert [x["id"] for x in w["nodes"]] == [0, 1, 2, 3, 4]
    assert [x["next_all"] for x in w["nodes"]] == [u(W3), None, None, None, None]
    assert [x["next_exclusive"] for x in w["nodes"]] == [
        [u(W1), None],
        [u(W2), None],
        [None, None],
        [None, u(W4)],
        [None, None],
    ]
    assert [x["exclusive_to_name"] for x in w["nodes"]] == [
        "INVALID",
        "RORSCHACH",
        "RORSCHACH",
        "INVALID",
        "NITE_OWL",
    ]
    assert w["nodes"][3]["force_next"] == u(W1) and w["nodes"][3]["for_all"] is True
    assert w["nodes"][2]["flying"] is True and w["nodes"][2]["height_limits"] == [1.0, 3.0]
    assert w["nodes"][1]["height_limits"] is None
    assert w["nodes"][4]["world"]["pos"] == [4.0, 0.0, 0.0] and "gltf" in w["nodes"][4]
    assert "0x8b1062" in level["evidence"]["waypoints"] and level["counts"]["waypoints"] == 5
    assert lm.EDGE_KINDS["m_eforcenext"] == "force_next"


# ------------------------------------------------------------------ culling, stream blocks
def test_culling_groups_and_the_visibility_rule(level):
    c = level["culling"]
    u = lambda nid: "1:%08x" % nid
    (box,) = c["boxes"]
    assert box["group"] == u(CG)
    assert c["groups"] == [
        {"uid": u(CG), "name": "cg", "boxes": [u(CB)], "shows": [u(VG)], "cube_maps": []}
    ]
    assert c["cube_maps_no_box"] == []
    assert c["visibility_groups"] == [u(VG)]
    assert c["visibility_rule"] == lm.CULLING_VISIBILITY_RULE and "0x70e0a4" in c["visibility_rule"]
    assert "not exported" not in level["evidence"]["culling"]
    assert level["counts"]["culling_groups"] == 1


def test_a_cube_node_names_the_visibility_groups_that_switch_it(tmp_path):
    """A cube node below a CullingVisibilityGroup that is a PVSRootNode is a candidate only
    for a culling group that shows it (0x7054b8 -> 0x48f69a, read by 0x48e028); one below
    no group is a candidate for every culling group; a plain PVSRootNode keeps its flag."""
    base = tmp_path / "extracted"
    scene = tl._node(SCENE, "SceneNode", "", None)
    scene += tl._node(LVL, "SceneScope(LoadBlock)", "Lvl", SCENE, 1, assetName="/L/Lvl.fragment")
    tl._write(base / "L" / "Lvl.scene", tl._fragment(scene))
    room, other, c_room, c_other, c_free, g1, g2, box = range(0x80, 0x88)
    plain, c_plain, m_room, m_free, m_other = range(0x88, 0x8D)
    f = _n(room, "CullingVisibilityGroup(PVSRootNode)", "room", "host", 0)
    f += _n(other, "CullingVisibilityGroup(PVSRootNode)", "other", "host", 1)
    cube = lambda nid, name, parent, order, x: _n(
        nid, "CubeMapNode", name, parent, order, localPos=[x, 0.0, 0.0],
        localOrient=ID, texture="/L/%s_cubemap.bmp" % name,
    )  # fmt: skip
    model = lambda nid, name, parent, order, x: _n(
        nid, "Model", name, parent, order, localPos=[x, 0.0, 0.0], localOrient=ID,
        modelNames=["/art/props/%s.model" % name],
    )  # fmt: skip
    f += cube(c_room, "in_room", room, 0, 0.0)
    f += model(m_room, "chair", room, 1, 4.0)
    f += cube(c_other, "in_other", other, 0, 5.0)
    f += model(m_other, "lamp", other, 1, 5.0)
    f += cube(c_free, "free", "host", 2, 10.0)
    f += _n(g1, "CullingGroup(Node)", "g1", "host", 3, lists={"m_evisibilitygrouplist": [room]})
    f += _n(box, "CullingBox(CollisionBoxNode)", "b", g1, 0, localPos=[0.0] * 3,
            localOrient=ID, width=2.0, height=2.0, depth=2.0)  # fmt: skip
    f += _n(g2, "CullingGroup(Node)", "g2", "host", 4)
    f += _n(plain, "PVSRootNode", "plain", "host", 5, Visible=False)
    f += cube(c_plain, "under_plain", plain, 0, 4.0)
    f += model(m_free, "crate", "host", 6, 4.0)
    tl._write(base / "L" / "Lvl.fragment", tl._fragment(f, name="Lvl_Main", singleton=True))
    j = lm.build_level(str(base / "L" / "Lvl.scene"), "Lvl", "%08x" % LVL, None)
    u = lambda nid: "1:%08x" % nid
    by = {c["name"]: c for c in j["cube_maps"]}
    assert by["in_room"]["visibility_groups"] == [u(room)] == by["in_room"]["pvs_roots"]
    assert by["in_other"]["visibility_groups"] == [u(other)]
    assert by["free"]["visibility_groups"] == [] == by["free"]["pvs_roots"]
    assert by["under_plain"]["visibility_groups"] == []
    assert by["under_plain"]["pvs_roots"] == [u(plain)]
    assert {c["name"] for c in j["cube_maps"] if c["candidate_at_load"]} == {
        "in_room",
        "in_other",
        "free",
    }
    groups = {g["name"]: g for g in j["culling"]["groups"]}
    assert groups["g1"]["cube_maps"] == [u(c_room), u(c_free)]
    assert groups["g2"]["cube_maps"] == [u(c_free)]  # a group that shows nothing
    assert j["culling"]["cube_maps_no_box"] == [u(c_free)]
    assert "0x7054b8" in j["cube_map_rule"] and "cube_map_by_area" in j["cube_map_rule"]
    m = {r["name"]: r for r in j["models"]}
    # the file rule: every candidate_at_load node counts, so the chair at x = 4 gets the
    # cube of the other room (x = 5); cube_map keeps that value
    assert m["chair"]["cube_map"]["uid"] == u(c_other)
    # under a group: only the culling group that shows it is asked, and it has no in_other
    assert m["chair"]["cube_map_by_area"] == [
        {
            "cube": {"uid": u(c_room), "texture": "/L/in_room_cubemap.bmp", "distance": 4.0},
            "groups": [u(g1)],
        }
    ]
    # under no group: every culling group is asked, one row per distinct answer
    assert m["crate"]["cube_map"]["uid"] == u(c_other)
    rows = m["crate"]["cube_map_by_area"]
    assert [(r["cube"]["uid"], r["groups"]) for r in rows] == [
        (u(c_room), [u(g1)]),
        (u(c_free), [u(g2)]),
    ]
    assert rows[1]["cube"]["distance"] == 6.0
    assert m["lamp"]["cube_map_by_area"] == []  # no culling group shows its room
    c = j["counts"]
    assert c["models_cube_by_area_single"] == 1 and c["models_cube_by_area_multiple"] == 1
    assert c["models_cube_by_area_single_differs_from_file_rule"] == 1


def test_stream_blocks_name_their_triggers(level):
    u = lambda nid: "1:%08x" % nid
    sb = {b["name"]: b for b in level["files"]["stream_blocks"]}
    assert sb["Yard"] == {
        "uid": u(SB),
        "name": "Yard",
        "asset": "/L/Yard",
        "scene_start": True,
        "loaded_by": [],
        "unloaded_by": [u(ST)],
        "referenced_by": [],
    }
    assert sb["Cells"]["loaded_by"] == [u(ST), u(ST2)] and sb["Cells"]["unloaded_by"] == [u(ST2)]
    assert sb["Cells"]["scene_start"] is False and level["counts"]["stream_blocks"] == 2
    assert "0x847c78" in level["evidence"]["stream_blocks"]
    assert lm.EDGE_KINDS["m_eloadstreamblock"] == "stream_load"


def test_a_checkpoint_naming_a_stream_block_is_listed_on_the_block(level):
    u = lambda nid: "1:%08x" % nid
    sb = {b["name"]: b for b in level["files"]["stream_blocks"]}
    # the trigger volumes stay in loaded_by / unloaded_by; the checkpoint is not one of them
    assert sb["Cells"]["referenced_by"] == [u(CKP)]
    assert u(CKP) not in sb["Cells"]["loaded_by"] + sb["Cells"]["unloaded_by"]
    edge = [e for e in level["graph"]["edges"] if e["from"] == u(CKP) and e["to"] == u(SB2)]
    assert [e["kind"] for e in edge] == ["stream_block"]
    assert "not established" in level["evidence"]["stream_blocks"]


# ------------------------------------------------------------------ models
def test_swinging_prop_carries_its_motion(level):
    mo = _m(level, "lamp")["motion"]
    assert mo["kind"] == "hit_swing" and mo["rest"] == "stored placement"
    assert (mo["amplitude"], mo["frequency_hz"], mo["falloff"]) == (pytest.approx(0.12), 2.0, 1.5)
    assert mo["amplitude_z"] == pytest.approx(0.05) and mo["quarantine_s"] == 0.5
    assert "2^(-falloff_k*t)" in mo["formula"] and "0x874b7a" in mo["evidence"]
    assert "motion" not in _m(level, "switch")


def test_visibility_follows_pvs_roots_only(level):
    shown, culled = _m(level, "shown"), _m(level, "culled")
    # an invisible Folder does not hide its children; an invisible PVSRootNode does (0x48e028)
    assert shown["visible"] and shown["visible_effective"] is True and shown["pvs_root"] is None
    assert culled["visible"] is True and culled["visible_effective"] is False
    assert culled["pvs_root"] == "1:%08x" % HIDP
    assert level["counts"]["models_hidden_by_pvs_root"] == 1
    assert "0x48e028" in level["evidence"]["models"]


def test_lod_override_and_part_overrides(level):
    sw = _m(level, "switch")
    assert sw["lod_override"] == 1 and sw["lod_factor"] == 0.5
    assert sw["include_in_reflections"] is True and sw["include_in_ao"] is False
    plain = _m(level, "shown")
    assert plain["lod_override"] == -1 and plain["lod_factor"] == 1.0
    assert plain["include_in_reflections"] is False and plain["include_in_ao"] is True
    assert plain["part_overrides"] == []
    # the locked SubPivot keeps its stored transform; the disabled one hides its part; the
    # unlocked, enabled, visible one is not listed
    assert sw["part_overrides"] == [
        {
            "part": 1,
            "name": "interact",
            "local": {"pos": [0.0766, 0.0093, -1.549], "quat": [-0.5, -0.5, -0.5, 0.5]},
            "locked": True,
            "enabled": True,
            "visible": True,
        },
        {
            "part": 3,
            "name": "off",
            "local": {"pos": [0.0, 0.0, 0.0], "quat": ID},
            "locked": False,
            "enabled": False,
            "visible": True,
        },
    ]
    assert level["counts"]["models_with_part_overrides"] == 1


def test_parent_link_1_composes_with_its_parent(level):
    prop = _m(level, "fleeprop")
    assert prop["world"]["pos"] == [2.0, 3.0, 2.0]  # group y 36 + flee point y -33
    assert level["counts"]["parent_link_1"] == 1


# ------------------------------------------------------------------ lights
def test_lights_section(level):
    proj, bulb = level["lights"]
    assert proj["name"] == "proj" and proj["type"] == 2 and proj["stored_type"] == 5
    assert proj["type_name"] == "spot" and proj["textured"] is True
    assert proj["color"] == [1.0, 0.5, 0.25] and proj["brightness"] == 2.0
    assert proj["range_m"] == 10.0 and proj["attn_start"] == 0.75 and proj["never_fade"] is False
    assert proj["inner_cone_deg"] is None and "flicker" not in proj  # not stored: null
    assert proj["world"]["pos"] == [1.0, 2.0, 3.0] and "forward" in proj and "gltf" in proj
    assert bulb["class"] == "LightFlicker" and bulb["type_name"] == "spot"
    assert "stored_type" not in bulb and bulb["never_fade"] is True
    assert (bulb["inner_cone_deg"], bulb["outer_cone_deg"]) == (30.0, 40.0)
    assert bulb["flicker"] == {
        "brightness_min": 0.5,
        "brightness_max": 1.0,
        "period_s": pytest.approx(0.1),
        "range_m": 5.0,
        "active_within_m": 40,
    }
    c = level["counts"]
    assert c["lights"] == 2 and c["lights_with_flicker"] == 1
    assert "0x579fdf" in level["conventions"]["light"] and "0x4a3d8e" in level["evidence"]["lights"]


# ------------------------------------------------------------------ sequences and tours
def test_tour_cuts_come_from_the_sequence_node(level):
    (tour,) = level["cameras"]["tours"]
    u = lambda nid: "1:%08x" % nid
    assert tour["sequences"] == [
        {
            "uid": u(SEQ),
            "name": "seq",
            "sequence": "/a/t.sequence",
            "speed_factor": pytest.approx(0.7),
        }
    ]
    (cut,) = tour["cuts"]
    assert cut["uid"] == u(CUT) and cut["at"] == 2.0 and cut["action"] == "SET_CAMERA"
    assert cut["camera"]["uid"] == u(CAM) and cut["class"] == "TriggerActionCamera"
    # the other actions of the sequence, by position; a child without _ndelay is at 0.0
    assert [(t["uid"], t["at"], t["class"]) for t in tour["timed_actions"]] == [
        (u(DEA), 0.0, "DelayedEmitterActivator"),
        (u(SND), 3.0, "TriggerActionSound"),
    ]
    # an action placed directly under the tour is in neither list
    assert u(DIRECT) not in [x["uid"] for x in tour["cuts"] + tour["timed_actions"]]
    assert level["counts"]["tour_cuts"] == 1


def test_sequence_action_edges_and_the_tour_refire_child(level):
    u = lambda nid: "1:%08x" % nid
    seq = sorted((e["to"], e["at"]) for e in _edges(level, "sequence_action"))
    assert seq == [(u(CUT), 2.0), (u(SND), 3.0), (u(DEA), 0.0)]
    assert all(e["from"] == u(SEQ) for e in _edges(level, "sequence_action"))
    assert _edges(level, "tour_sequence") == [
        {"from": u(TOUR), "to": u(SEQ), "kind": "tour_sequence"}
    ]
    assert _node(level, SEQ)["kind"] == "object"
    child = [e for e in _edges(level, "child") if e["from"] == u(TOUR)]
    assert [(e["to"], e["when"]) for e in child] == [(u(DIRECT), "tour_refire")]
    assert "delay" not in child[0]
    assert level["counts"]["sequence_actions"] == 3
    (auto,) = level["auto_sequences"]
    assert auto["speed_factor"] == pytest.approx(0.7) and auto["actions"] == 3
    assert auto["update_culling_distance"] == 35.0


def test_actions_fired_and_the_speed_factor():
    assert ds.actions_fired([0, 1, 2], 0, 1) == [0]
    assert ds.actions_fired([2], 2, 2) == []  # nothing fires without a rising position
    assert ds.actions_fired([0.5, 2.0], 0.0, 2.0) == [0.5]  # a delay at the new position waits
    seq = {"duration": 4.0, "loop_mode": 1}
    assert ds.play_position(seq, 2.0) == 2.0
    assert ds.play_position(seq, 2.0, speed=0.5) == 1.0
    assert ds.play_position(seq, 2.0, dt=0.5, speed=0.5) == pytest.approx(1.0)
    assert ds.play_position(seq, 100.0, speed=0.5) == 4.0
    with pytest.raises(ValueError):
        ds.play_position(seq, 1.0, speed=-1.0)


# ------------------------------------------------------------------ property filters, labels
def test_applies_names_the_properties_of_the_action_type(level):
    assert _node(level, GEN9)["applies"] == ["m_etarget1", "m_iinteger1"]
    assert _node(level, GEN10)["applies"] == ["m_sstring1"]
    # the use fragment: the use type of its TriggerUse (PICK_LOCK), two lock pins
    ap = _node(level, UF)["applies"]
    assert "_ipinheight1" in ap and "_ipinheight2" in ap and "_ipinheight3" not in ap
    assert "m_estartaction" in ap and "m_iactivatortype" not in ap
    assert "applies" not in _node(level, STOP) and "applies" not in _node(level, TU)
    t = lm.filter_exposed()
    assert sorted(t["classes"]) == [
        "TriggerActionGeneral",
        "TriggerActionParticle",
        "TriggerUseFragment",
    ]
    assert "0x873568" in t["classes"]["TriggerUseFragment"]["default_rule"]
    assert "0x85e3e8" in level["evidence"]["graph"]


def test_labels_of_use_triggers_and_conditions(level):
    assert _node(level, TU)["label"] == "USE PICK_LOCK by RORSCHACH"
    assert _node(level, UF)["label"] == "USE PICK_LOCK by RORSCHACH"
    assert _node(level, VIS)["label"] == "LOOK+USE NITE_OWL within 4.0 m"
    assert _node(level, TRUE)["label"] == "ON LOAD, every 20.0 s"
    assert _node(level, SOME)["label"] == "SOME 2"  # unchanged
    assert _node(level, GEN10)["label"].endswith(" (no effect)")
    assert not _node(level, GEN9)["label"].endswith(" (no effect)")
    assert _node(level, TU)["names"]["m_iusetype"] == "PICK_LOCK"
    assert lm.enum_name("MOVEMENT_TYPES", 2) == "DYNAMIC"
    assert lm.enum_name("CHARACTER_TYPES", 0xFFFFFFFF) == "INVALID"


def test_sound_action_params_and_held_children(level):
    u = lambda nid: "1:%08x" % nid
    # SOUND_STOP uses the sound slot and the fade time only (0x861606)
    assert _node(level, STOP)["sound_params"] == {"Sound slot": None, "Fade time": 0.5}
    assert list(_node(level, PLAY)["sound_params"])[:2] == ["Sound slot", "Attach to"]
    assert "sound_params" not in _node(level, GEN9)
    assert lm.TRIGGER_ACTION_SOUND_PARAMS[7]["m_nnumber4"] == "Volume"
    assert lm.TRIGGER_ACTION_SOUND_PARAMS[13]["m_nnumber1"] == "Volume"
    held = {e["from"]: e for e in _edges(level, "child") if e["when"] == "after_sound"}
    # a SOUND_STOP action starts no sound, so nothing sends command_sound_done (0x86150a)
    assert held[u(STOP)]["sound_done"] is False and held[u(STOP)]["to"] == u(GEN9)
    assert "sound_done" not in held[u(PLAY)]


# ------------------------------------------------------------------ ai sight, terrain
class _N:
    def __init__(self, **p):
        self.props = p

    def p(self, k, d=None):
        return self.props.get(k, d)


def test_a_stored_sheet_id_0_is_no_sheet(level):
    sheets = {7: {"name": "default", "book": "default.pb", "collision_mask": 8192}}
    zero = lm.ai_sight(_N(pivotSheet_Id=0, physicsType=1), 8192, sheets)
    assert zero == {
        "sheet": None,
        "sheet_book": None,
        "sheet_collision_mask": 0,
        "sheet_has_ai_bit": False,
        "physics_type": 1,
        "blocks": False,
        "sheet_source": "none (stored id 0, 0x4a4c44)",
    }
    absent = lm.ai_sight(_N(physicsType=1), 8192, sheets)
    assert absent["blocks"] is None and absent["sheet_source"] == "not stored"
    assert absent["sheet_collision_mask"] is None
    hit = lm.ai_sight(_N(pivotSheet_Id=7, physicsType=1), 8192, sheets)
    assert hit["blocks"] is True and hit["sheet_source"] == "stored id"
    unknown = lm.ai_sight(_N(pivotSheet_Id=99, physicsType=1), 8192, sheets)
    assert unknown["blocks"] is None and unknown["sheet_source"] == "id in no pivot book read"
    # without an AI mask nothing is decided, and a trigger never blocks
    assert lm.ai_sight(_N(pivotSheet_Id=0, physicsType=1), None, sheets)["blocks"] is None
    assert lm.ai_sight(_N(pivotSheet_Id=0, physicsType=2), 8192, sheets)["blocks"] is False
    # through the file: the fixture's volume stores the id as a biginteger 0
    (vol,) = [v for v in level["volumes"] if v["name"] == "nosheet"]
    assert vol["ai_sight"]["sheet_source"] == lm.SHEET_SOURCE_NONE
    assert vol["ai_sight"]["sheet_collision_mask"] == 0
    assert "0x4a4c44" in level["evidence"]["ai_sight"]


def test_terrain_says_how_it_is_drawn(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    (t,) = tt._level(tmp_path / "a", [0.0, 0.0, 0.0], tl.ID, "true")["files"]["terrain"]
    assert t["drawn_with"] == "identity" and t["world_is_identity"] is True
    j = tt._level(tmp_path / "b", [10.0, 0.0, 3.0], tl.Q90, "true")
    (moved,) = j["files"]["terrain"]
    assert moved["drawn_with"] == "identity" and moved["world_is_identity"] is False
    assert "0x49c3be" in j["files"]["terrain_rule"] and "0x49c3be" in j["evidence"]["files"]
    assert lm._is_identity({"pos": [0, 0, 0], "quat": [0, 0, 0, -1]}) is True
    assert lm._is_identity(None) is None


# ------------------------------------------------------------------ models: strips, cloth
def test_index_triangles_reads_lists_and_strips():
    idx = (0, 1, 2, 3, 3, 4, 5)
    assert we.index_triangles(idx, 1) == [(0, 1, 2), (3, 3, 4)]
    # strip: (i, i+1, i+2) for even i, (i+2, i+1, i) for odd i; repeats are dropped
    assert we.index_triangles(idx, 0) == [(0, 1, 2), (3, 2, 1), (3, 4, 5)]
    assert we.index_triangles((0, 1), 0) == [] and we.index_triangles((), 1) == []
    with pytest.raises(ValueError):
        we.index_triangles(idx, 2)
    assert we.PRIMITIVE_NAMES == {0: "triangle_strip", 1: "triangle_list"}


def test_model_header_and_sidecar_name_the_primitive():
    import test_formats_v2 as tf

    h, s = tf._lod_model()
    M = we.parse_model_header(h)
    assert [b["primitive_type"] for b in M["buffers"][:3]] == [1, 0, 1]
    assert all(b["primitive_type"] == b["ix"] for b in M["buffers"])
    assert M["buffers"][0]["has_cloth_mesh"] == M["buffers"][0]["no_defer"]
    subs = we.decode_model_mesh(h, s)["submeshes"]
    assert [x["primitive"] for x in subs] == ["triangle_list", "triangle_strip"]
    assert subs[1]["triangles"] == [(0, 1, 2), (0, 2, 1), (3, 2, 0)]
    meta = we.model_meta(h)
    prims = [sm_["primitive"] for sm_ in meta["parts"][0]["submeshes"]]
    assert prims == ["triangle_list", "triangle_strip", "triangle_list"]
    assert "triangle_strip" in meta["parts_note"]


def test_cloth_world_fixes_depend_on_the_buffer_format():
    model = {"parts": [{"lods": [[{"format": 5}, {"format": 6}]]}, {"lods": []}]}
    assert rr.cloth_mesh_format(model, 0, 0) == 5 and rr.cloth_mesh_format(model, 0, 1) == 6
    assert rr.cloth_mesh_format(model, 1, 0) is None and rr.cloth_mesh_format(None, 0, 0) is None
    assert rr.cloth_mesh_format(model, 0, 9) is None
    assert rr.world_fixes_applied(5, {"characterClothMode": True}) is True  # the curtain
    assert rr.world_fixes_applied(6, {"characterClothMode": True}) is False  # a coat
    assert rr.world_fixes_applied(6, {"characterClothMode": False}) is True
    assert rr.world_fixes_applied(6, {}) is False  # the constructor default is true
    assert rr.world_fixes_applied(None, {}) is None
    c = {"node": 0, "mesh": 0, "attachments": [(3, 0xFFFFFFFF), (4, 2)]}
    rec = rr._cloth_record(c, {"props": {"characterClothMode": True, "key_1": 0}}, model)
    assert rec["mesh_format"] == 5 and rec["world_fixes_applied"] is True
    assert rec["world_fixes_rule"] == rr.WORLD_FIXES_RULE and "0x507dd0" in rec["world_fixes_rule"]
    assert [a["world_fixed"] for a in rec["attachments"]] == [True, False]
    assert rec["properties"] == {"characterClothMode": True}
    assert rr._cloth_record(c, {"props": {}}, None)["world_fixes_applied"] is None


# ------------------------------------------------------------------ typed fragment stream
def test_a_typed_stream_is_read_with_its_type_and_length_words():
    def prop(name, value, words=None, typehash=0x1234):
        words = len(value) // 4 if words is None else words
        return tl._u(kp.name_hash(name), typehash, words) + value

    nid = 0x77
    body = tl._u(0xFFFFFFFF, nid) + tl._str("Folder") + tl._u(0xFFFFFFFE, nid)
    body += prop("name", tl._str("room"))
    body += prop("siblingOrder", tl._u(3))
    body += tl._u(0xDEADBEEF, 0x99, 2) + tl._u(7, 8)  # an unknown key: two words by the frame
    body += prop("localPos", tl._f(1.0, 2.0, 3.0))
    nm = b"\0"
    head = tl._u(4) + bytes([0, 0]) + tl._u(len(nm)) + nm + bytes([0, 1]) + tl._u(1)
    data = head + tl._u(len(body)) + body
    assert kf.parse_header(data)["typed"] is True
    r = kf.parse(data)
    assert r["ok"] and r["end"] == r["size"]
    (inst,) = [x for x in r["inst"] if not x["created"]]
    got = {k: v for k, _t, v in inst["props"]}
    assert got["name"] == "room" and got["siblingOrder"] == 3
    assert got["localPos"] == [1.0, 2.0, 3.0] and got["key_deadbeef"] == [7, 8]
    assert [t for k, t, _v in inst["props"] if k == "key_deadbeef"] == ["words?"]
    # the same bytes without the header flag do not read as an untyped stream
    plain = head[:-5] + bytes([0]) + head[-4:] + tl._u(len(body)) + body
    assert kf.parse_header(plain)["typed"] is False
    untyped = [x for x in kf.parse(plain)["inst"] if not x["created"]]
    assert {k: v for k, _t, v in untyped[0]["props"]}.get("siblingOrder") != 3


# ------------------------------------------------------------------ sound
class _Db:
    """The two SoundDB calls _package_rows makes."""

    def __init__(self, nodes):
        self.by_id = nodes

    def definition_of(self, ref, rel):
        n = self.by_id.get(ref)
        return (
            {
                "ref": [rel, ref],
                "name": n,
                "n_waves": 1,
                "duration_s": 1.0,
                "play": {"mode": "one"},
            }
            if n
            else None
        )

    def resolve(self, ref, rel):
        return None


def _package(effect_type, kids):
    p = asm.Node("p%d" % effect_type, "SoundPackageCtrl", "pkg%d" % effect_type)
    p.props = {"m_ieffecttypes": effect_type}
    for sid, snd in kids:
        e = asm.Node("e%d_%d" % (effect_type, sid), "SoundEffectType", "surf%d" % sid)
        e.props = {"m_ieffecttypes": sid, "m_eeffectsoundreference": snd}
        e.parent = p
        p.children.append(e)
    return p


def test_a_package_owns_every_surface_it_has_a_child_for():
    db = _Db({"a": "stepA", "b": "stepB"})
    own = _package(53, [(0, "a"), (1, None), (2, "a")])
    rows, owned = sm._package_rows(db, "x.fragment", own)
    assert owned == [0, 1, 2]  # the child without a sound still owns surface 1
    assert [(r["name"], r["surface_ids"]) for r in rows] == [("stepA", [0, 2])]
    default = _package(33, [(1, "b"), (3, "b"), (0, "b")])
    extra, _ = sm._package_rows(db, "x.fragment", default, skip_ids=set(owned))
    # only the surface the first package does not own is taken from the default
    assert [(r["name"], r["surface_ids"]) for r in extra] == [("stepB", [3])]


def _music_tree():
    def node(nid, cls, typ, name="", parent=None, **props):
        n = asm.Node(nid, cls, name)
        n.type, n.props = typ, dict(props)
        if parent is not None:
            n.parent = parent
            parent.children.append(n)
        return n

    setup = node("s", "MusicSetup", "MusicSetup(Node)", "Menu")
    slot = node("m", "MusicStreamSlot", "MusicStreamSlot(StreamingSoundSlot)", parent=setup,
                streamingSound="/a/Menu_track0.mediastream", track0="drums")  # fmt: skip
    trig = node("t", "MusicTrigger", "MusicTrigger(Node)", "calm", parent=setup)
    node("c", "MusicTrackCtrl", "MusicTrackCtrl(Node)", parent=trig, track_index=0, volume=1.0,
         fade_time=2.0, change_on_cue=0)  # fmt: skip
    node("o1", "MusicStaticSlot", "MusicStaticSlot(SoundSlot)", parent=trig, sound="/a/hit.wav",
         volume=0.5, change_on_cue=1)  # fmt: skip
    node("o2", "SoundDef", "SoundDef(SoundSlot)", parent=trig, sound="/a/sting.wav",
         volume=1.0, change_on_cue=77)  # fmt: skip
    node("o3", "MusicStaticSlot", "MusicStaticSlot(SoundSlot)", parent=trig, volume=1.0)
    node("g", "MusicGroupCtrl", "MusicGroupCtrl(Node)", parent=trig, group={"ref": "00000009"},
         volume=0.25, fade_time=1.0, change_on_cue=sm.cue_hash("end"))  # fmt: skip
    return {n.id: n for n in (setup, slot, trig)}


def test_music_one_shots_are_every_sound_slot_child_with_a_sound():
    (rec,) = sm.music_setups(_music_tree(), "m.fragment")
    (st,) = rec["states"]
    # the slot without a sound is left out; a class other than the two music slot classes
    # plays at once whatever it stores
    assert st["one_shots"] == [
        {"class": "MusicStaticSlot", "wave": "/a/hit.wav", "volume": 0.5, "change_on_cue": 1},
        {"class": "SoundDef", "wave": "/a/sting.wav", "volume": 1.0, "change_on_cue": 0},
    ]
    assert st["groups"][0]["volume"] == 0.25 and st["groups"][0]["fade_s"] == 1.0
    sm.name_cue_changes(rec, ["start", "end"])
    assert [o["change_on_cue_mode"] for o in st["one_shots"]] == ["next_cue", "at_once"]
    assert st["groups"][0]["change_on_cue_name"] == "end"
    assert st["tracks"][0]["change_on_cue_mode"] == "at_once"
