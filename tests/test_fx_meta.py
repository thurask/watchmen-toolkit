"""fx_meta: event payloads, the per-state `fx` section, pair camera cuts and
the effect / weapon / attachment / camera tables.

Offline: every fixture is synthetic (fragment JSON in the shape
tree_from_json() reads, clips through test_anim_meta.write_clip).
"""

import copy
import json
import math

import pytest

import anim_meta as am
import engine_enums as ee
import kapow_props

try:  # the module is new: every test fails (not errors at import) on the base tree
    import fx_meta as fx
except ImportError:  # pragma: no cover
    fx = None

EFFECTDB = "TNT/Fragments/GameEssentials/EffectDb.fragment"
PARTICLEDB = "TNT/Fragments/GameEssentials/ParticleDb.fragment"
SOUNDDB = "TNT/Fragments/GameEssentials/SoundDb/SoundDb.fragment"
ANIM = "TNT/Fragments/GameEssentials/CharacterAnimation/"
RORSCHACH, ENEMY_04 = 1, 7  # OPPONENT_MODEL_TYPE


def need():
    assert fx is not None, "wlib/fx_meta.py is missing"
    return fx


class Frag:
    """A fragment JSON in the shape tree_from_json() reads; ids count from 1 in
    every fragment (so they collide across fragments on purpose)."""

    def __init__(self, rel):
        self.rel, self.cls, self.nodes, self.n = rel, {}, [], 0

    def add(self, cls, name, parent=None, **props):
        self.n += 1
        nid = "%08x" % self.n
        self.cls["str_" + nid] = [cls + "(Node)"]
        p = [["name", "string", name], ["siblingOrder", "int", self.n]]
        if parent:
            p.append(["logicalParent", "ref", {"ref": parent}])
        p += [[k, "x", v] for k, v in props.items()]
        self.nodes.append({"id": nid, "type": cls, "props": p})
        return nid

    def state(self, name, parent, clip, events=(), speed=1.0, **props):
        s = self.add("AnimationStateWM", name, parent, **props)
        layers = self.add("Folder", "Layers", s)
        b = self.add("AnimationBlendWM", "{MOTION_LAYER_1}", layers, m_nweight=1.0)
        self.add("AnimationSlotWM", "{%s.animation}" % clip, b, m_nweight=1.0, speedFactor=speed)
        evf = self.add("Folder", "Events", s)
        for ev in events:
            base = dict(m_ieventtype=0, m_nvalue=0.0, m_nplaypos=0.0)
            base.update(ev)
            self.add("AnimationEventWM", "{event}", evf, **base)
        return s

    def enum_criteria(self, owner, value):
        f = self.add("Folder", "Criterias", owner)
        self.add(
            "AnimationCriteriaWM",
            "{criteria}",
            f,
            m_ianimationcriteria=2,
            m_ianimationenum=11,
            m_ianimationenumvalue=value,
            m_ianimationvalue=0,
            m_tnot=False,
        )

    def write(self, root):
        f = root / "extracted" / (self.rel + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"instances": [self.cls], "nodes_full": self.nodes}))


def stem_ref(stem, nid):
    return {"xref": ["%08x" % kapow_props.name_hash(stem), nid]}


def cut(pos, **kw):
    """A CAMERA_CUT event: the argument slots as case 59 reads them."""
    names = dict(
        transition="m_nvalue",
        to_target="m_ttruth1",
        bone="m_ivalue00",
        distance="m_nvalue02",
        fov="m_nvalue03",
        mult="m_nvalue04",
        height="m_nvalue05",
        angle="m_nvalue10",
        keep="m_ttruth2",
        shake_t="m_nvalue06",
        shake_f="m_nvalue07",
        shake_s="m_nvalue08",
    )
    ev = dict(m_ianimationevent=59, m_nplaypos=pos, m_nvalue03=50.0, m_nvalue04=1.0)
    ev.update({names[k]: v for k, v in kw.items()})
    return ev


@pytest.fixture
def fx_extract(tmp_path):
    """An effect database (three damage effects, one effect with an id, two
    character definitions), a particle and a sound database, weapons, a GFX
    package, two characters with their visuals (an emitter on a bone, a light
    flash), a camera rig, and a hero finisher (master of 8) with camera cuts,
    impacts, rumble, a look-at and a weapon steal against an enemy slave."""
    snd = Frag(SOUNDDB)
    thud = snd.add("SoundDef", "thud", sound="/sounds/fx/thud.wav", _iselectionmethod=3)
    snd.write(tmp_path)

    pdb = Frag(PARTICLEDB)
    pdb.add("Folder", "General")
    slot = pdb.add("ParticleSystemSlot", "", definition="/Art/fx/hit.particle")
    pdb.write(tmp_path)

    ed = Frag(EFFECTDB)

    def effect(name, eid=4294967295, particle=True, speak=None):
        e = ed.add("EffectBase", name, _ieffectid=eid)
        if particle:
            ed.add(
                "EffectParticle",
                "",
                e,
                _ieffectid=4294967295,
                _iplacement=1,
                _eparticle=stem_ref("ParticleDb", slot),
                _tlocaltransform=False,
                _vlocalposition=[0.0, 0.1, 0.0],
                _qlocalorient=[0.0, 0.0, 0.0, 1.0],
            )
        ed.add("EffectSound", "", e, _iplacement=1, _esounddef=stem_ref("SoundDb", thud))
        if speak is not None:
            ed.add("EffectSpeak", "", e, _ispeakid=speak)
        return e

    eff = {n: effect(n, speak=30) for n in ("body_light", "head_heavy", "head_steel", "knock")}
    eff["discharge"] = effect("Discharge", eid=1)
    eff["hero_head"] = effect("RSH_head", particle=False)
    slots = dict(
        _ebodyfast={"ref": eff["body_light"]},
        _eheadheavy={"ref": eff["head_heavy"]},
        _eheadweaponsteel={"ref": eff["head_steel"]},
        _eknockdown={"ref": eff["knock"]},
        _eheadfast={"etag": 1},
    )
    enemy_def = ed.add("CharacterEffectDef", "EnemyDamageEffectDef", **slots)
    hero_def = ed.add(
        "CharacterEffectDef", "RSH_DamageEffectDef", _eheadfast={"ref": eff["hero_head"]}
    )
    ed.write(tmp_path)

    wdb = Frag("TNT/Fragments/GameEssentials/WeaponDB/WeaponDB.fragment")
    coll = wdb.add("CharacterModelCollection", "DominitrixWeapons_1H")
    baton = wdb.add(
        "WeaponBase",
        "",
        coll,
        modelNames=["/Art/weapons/PoliceBaton.model"],
        m_iweapontype=0,
        m_ieffecttype=1,
        m_ndurebilitylossperhit=0.16,
        m_tdisableatbreak=False,
        _ebreakeffect=stem_ref("EffectDb", eff["knock"]),
    )
    wdb.add("EmitterNode", "", baton, particleSystemAsset="/Art/fx/torch.particle", autoStart=True)
    wdb.write(tmp_path)

    gfx = Frag("TNT/Fragments/GameEssentials/CollisionEffectDB/CollisionGFXDB.fragment")
    gfx.add("GFXPackageCtrl", "NONE", m_ieffecttypes=0)
    pkg = gfx.add("GFXPackageCtrl", "TRASHCAN", m_ieffecttypes=9)
    row = gfx.add("GFXEffectType", "WOOD_BOARD", pkg, m_ieffecttypes=7)
    gfx.add("GFXParticleEffectType", "", row, definition="/particles/dust.particle")
    gfx.write(tmp_path)

    cv = Frag("TNT/Fragments/GameEssentials/CharacterVisual.fragment")
    fn_en = cv.add(
        "FragmentNode",
        "",
        assetName="/TNT/Fragments/GameEssentials/CharacterVisual/En4CharVisual.fragment",
    )
    fn_rsh = cv.add(
        "FragmentNode",
        "",
        assetName="/TNT/Fragments/GameEssentials/CharacterVisual/RorschachCharVisual.fragment",
    )
    cv.write(tmp_path)
    vis = Frag("TNT/Fragments/GameEssentials/CharacterVisual/En4CharVisual.fragment")
    v = vis.add("CharacterVisual", "EN4", localPos=[0.0, 0.97, 0.0])
    vis.add("AnimationCtrlWM", "AnimCtrl", v, m_ianimationclassid=10)
    att = vis.add("BoneAttacher", "HandAttach", v, attachedBone=2, localPos=[0.0, 0.0, 0.0])
    model = vis.add("Model", "", att, modelNames=["/Art/tw/TW_weapon.model"], localPos=[0.1, 0, 0])
    vis.add(
        "EmitterNode",
        "",
        model,
        particleSystemAsset="/Art/fx/sparks.particle",
        autoStart=True,
        localPos=[-0.1, 0.48, 0.0],
        localOrient=[0.0, 0.0, 0.0, 1.0],
    )
    vis.write(tmp_path)
    rvis = Frag("TNT/Fragments/GameEssentials/CharacterVisual/RorschachCharVisual.fragment")
    rv = rvis.add("CharacterVisual", "RSH")
    rsh_id = [k for k, n in ee.family("CHARACTER_ANIMATIONS").items() if n == "RSH"][0]
    rvis.add("AnimationCtrlWM", "AnimCtrl", rv, m_ianimationclassid=rsh_id)
    rvis.add(
        "LightFlash",
        "ImpactLight",
        rv,
        lightColorRGB=[0.86, 0.86, 1.0],
        Brightness=2.82,
        range=0.7,
        lightType=1,
    )
    rvis.write(tmp_path)

    for stem, ctype, fn, d in (
        ("Dominatrices", 33, fn_en, enemy_def),
        ("Rorchach", 0, fn_rsh, hero_def),
    ):
        ch = Frag("TNT/Fragments/Enemy/%s.fragment" % stem)
        ch.add(
            "CharacterDef",
            "{%s}" % stem.upper(),
            m_icharactertype=ctype,
            m_emodelfragment=stem_ref("CharacterVisual", fn),
            m_echaractereffectdef=stem_ref("EffectDb", d),
        )
        ch.write(tmp_path)

    rig = Frag("TNT/Fragments/GameEssentials/PlayerCtrl/RorschachSingle.fragment")
    ctrl = rig.add("CameraCtrl", "Camera")
    rig.add("CharacterCamera", "CharacterCamera", ctrl, _ndefaultfov=55.0, _tdebugdraw=True)
    man = rig.add("CharacterCameraStateManager", "States", ctrl)
    item = rig.add("CharacterCameraDBItem", "Combat", man, m_icharactercamid=2, m_nverticalfov=60.0)
    rig.add("CameraCharacterTransition", "", item, m_icharactercamid=0, m_ntransitionduration=0.5)
    rig.add("CameraCombatSpecialCuts", "Cuts", ctrl, ncoopfov=70.0)
    rig.write(tmp_path)

    hero = Frag(ANIM + "AnimationClassRorschach.fragment")
    g = hero.add("AnimationStateGroupWM", "FinishingMovesGroup")
    hero.state(
        "Finish_move_A",
        g,
        "RSH_COM_ATT_finish_EN4_A",
        speed=2.0,
        m_imasterof=8,
        m_tislooping=False,
        m_nstartplaypos=0.1,
        events=[
            # a hard cut on the victim; the two vectors are left over from an older id
            dict(
                cut(0.2, to_target=True, bone=5, distance=1.5, height=2.1, angle=180.0, fov=65.0),
                m_vvalue1=[0.0, 0.35, 0.0],
                m_vvalue2=[0.7, 0.0, 0.4],
            ),
            # slow motion on the actor, with a shake
            dict(
                cut(0.5, transition=0.1, bone=14, distance=2.6, height=1.2, angle=-35.0, mult=0.1),
                m_nvalue06=0.6,
                m_nvalue07=50.0,
                m_nvalue08=0.1,
            ),
            cut(0.6, transition=0.1, to_target=True, bone=18, keep=True, fov=60.0),
            dict(m_ianimationevent=61, m_nplaypos=0.8, m_nvalue=0.3, m_ttruth1=True),
            dict(
                m_ianimationevent=56,
                m_nplaypos=0.3,
                m_ivalue00=5,
                m_vvalue1=[0.5, 0.35, 0.3],
                m_vvalue2=[0.0, 0.0, 1.0],
            ),
            dict(
                m_ianimationevent=56,
                m_nplaypos=0.65,
                m_ivalue00=27,
                m_ttruth2=True,
                m_ttruth3=True,
                _etarget01=stem_ref("EffectDb", eff["discharge"]),
            ),
            dict(m_ianimationevent=82, m_nplaypos=0.3, m_nvalue=0.13, m_nvalue02=1.0, m_ivalue00=8),
            dict(
                m_ianimationevent=45, m_ieventtype=1, m_nvalue=0.7, m_nvalue02=0.61, m_ttruth1=True
            ),
            dict(m_ianimationevent=32, m_nplaypos=0.45),
            dict(m_ianimationevent=20, m_nplaypos=0.7),
        ],
    )
    hero.state("Run", g, "RSH_COM_MOV_run_cycle", m_imasterof=0, m_tislooping=True)
    hero.write(tmp_path)

    en = Frag(ANIM + "AnimationClassEnemy04.fragment")
    root = en.add(
        "AnimationClassWM", "Enemy04AnimationClass", m_ianimationmodeltype=ENEMY_04, m_iclassid=10
    )
    sl = en.add("Folder", "SlaveStates", root)
    grp = en.add("AnimationStateGroupWM", "FinishingGroup_Victim", sl, m_istategroupid=8)
    victim = en.state(
        "Finished_by_Rorshack_A",
        grp,
        "EN4_COM_DMG_finish_RSH_A",
        m_nstartplaypos=0.25,
        events=[
            # at the partner's own start: created already fired, never fires in the pair
            dict(m_ianimationevent=56, m_nplaypos=0.2, m_ivalue00=2),
            dict(m_ianimationevent=56, m_nplaypos=0.9, m_ivalue00=2),
            dict(
                m_ianimationevent=82, m_nplaypos=0.5, m_nvalue=0.2, m_nvalue02=0.5, m_ttruth1=True
            ),
        ],
    )
    en.enum_criteria(victim, RORSCHACH)
    en.write(tmp_path)

    import test_anim_meta as tam

    tam.write_clip(
        tmp_path,
        "RSH_COM_ATT_finish_EN4_A",
        ((0, 1, 0), (0, 1, 0)),
        ((0, 0, 1), (0, 0, 1)),
        duration=4.0,
    )
    tam.write_clip(tmp_path, "EN4_COM_DMG_finish_RSH_A", ((0, 1, -1), (0, 1, -1)), duration=4.0)
    tam.write_clip(tmp_path, "RSH_COM_MOV_run_cycle", ((0, 1, 0), (0, 1, 6)))
    return tmp_path


@pytest.fixture
def meta(fx_extract):
    return am.build(str(fx_extract))


def _state(meta, cls, name):
    return next(s for s in meta["classes"][cls]["states"] if s["name"] == name)


# ---------------------------------------------------------- the dispatch rule
def test_hit_position_follows_is_upper_damage_pose():
    f = need()
    assert f.hit_position(0) is None
    assert [p for p in range(1, 29) if f.hit_position(p) == 0] == sorted(f.UPPER_POSES)
    # 20 and 21 (stun middle / upper back) count as upper, 22 does not: as coded
    assert (f.hit_position(20), f.hit_position(21), f.hit_position(22)) == (0, 0, 1)


def test_damage_slots_order_and_special_cases():
    f = need()
    assert f.damage_slots(0) == []
    assert f.damage_slots(1) == ["headfast"] and f.damage_slots(5) == ["bodyfast"]
    # 3 and 4 are "light" poses that take the heavy effect
    assert f.damage_slots(3) == ["headheavy"] and f.damage_slots(4) == ["bodyheavy"]
    assert f.damage_slots(8, "wood") == ["headweaponwood"]
    assert f.damage_slots(11, "steel") == ["bodyweaponsteel"]
    # SHARP has one slot for head and body and fires nothing else
    assert f.damage_slots(8, "sharp") == ["sharpweapon"] == f.damage_slots(11, "sharp")
    # TASER: effect id 1 first, then the STEEL slot
    assert f.damage_slots(8, "taser") == ["effect_id:1", "headweaponsteel"]
    assert f.damage_slots(8, "uber") == ["headuber"] and f.damage_slots(8, "kill") == ["headkill"]
    # knock-down / stun come on top, whatever the main effect
    assert f.damage_slots(27) == ["headheavy", "knockdown"]
    assert f.damage_slots(17, "steel") == ["bodyweaponsteel", "knockdown"]
    assert f.damage_slots(22, "uber") == ["bodyuber", "stun"]


def test_impact_rumble_and_recoil_by_pose():
    f = need()
    assert f.impact_rumble(2) == {"duration_s": 0.2, "power": 0.15, "fade": False}
    assert f.impact_rumble(20) == {"duration_s": 0.35, "power": 0.2, "fade": True}
    assert f.impact_rumble(27) == {"duration_s": 0.55, "power": 0.2, "fade": True}
    assert f.impact_rumble(0) is None
    assert [f.recoil_intensity(p) for p in (2, 8, 17, 20, 0)] == [0.5, 1.0, 2.1, 1.4, 0.2]


def test_damage_rule_table_covers_every_pose():
    rule = need().damage_rule()
    assert sorted(int(k) for k in rule["by_pose"]) == list(range(1, 29))
    row = rule["by_pose"]["3"]
    assert row["hit_position"] == "HEAD" and row["slots"]["unarmed"] == ["headheavy"]
    assert row["slots"]["taser"] == ["effect_id:1", "headweaponsteel"]
    assert "0x6673d0" in rule["evidence"]


# ------------------------------------------------------------- cut placement
def test_cut_camera_angle_is_measured_from_the_pair_line():
    f = need()
    actor, target = [0.0, 0.0, 0.0], [0.0, 0.0, 2.0]
    c = dict(distance_m=3.0, height_m=1.5, angle_deg=90.0, look_at_bone=18, look_at_height_m=1.2)
    r = f.cut_camera(dict(c, look_at="actor"), actor, target)
    # d = +Z, heading 0; +90 degrees turns from +Z towards +X; base = the actor
    assert r["position"] == pytest.approx([3.0, 1.5, 0.0], abs=1e-5)
    assert r["look_at"] == [0.0, 1.2, 0.0]
    # looking at the attack target: the line is reversed and the base is the target
    r = f.cut_camera(dict(c, look_at="attack_target"), actor, target)
    assert r["position"] == pytest.approx([-3.0, 1.5, 2.0], abs=1e-5)
    assert r["look_at"] == [0.0, 1.2, 2.0]
    # 180 on the attack target: beyond the target, on the pair's line
    r = f.cut_camera(dict(c, look_at="attack_target", angle_deg=180.0), actor, target)
    assert r["position"] == pytest.approx([0.0, 1.5, 5.0], abs=1e-5)


def test_cut_camera_side_shot_and_kept_position():
    f = need()
    actor, target = [0.0, 0.0, 0.0], [0.0, 0.0, 2.0]
    c = dict(distance_m=2.0, height_m=1.0, angle_deg=0.0, look_at="actor", look_at_bone=4)
    r = f.cut_camera(c, actor, target, look_at_point=[0.1, 1.1, 0.2])
    # perpendicular (-l.z, 0, l.x) at the midpoint of the pair
    assert r["position"] == pytest.approx([-2.0, 1.0, 1.0], abs=1e-5) and r["side"] == 1
    assert r["look_at"] == [0.1, 1.1, 0.2]
    # the camera is on the other side: that side is taken
    r = f.cut_camera(c, actor, target, look_at_point=[0, 1, 0], camera=[5.0, 2.0, -1.0])
    assert r["position"] == pytest.approx([2.0, 1.0, 1.0], abs=1e-5) and r["side"] == -1
    kept = f.cut_camera(dict(c, placement="previous_position"), actor, target, previous=[9, 9, 9])
    assert kept["position"] == [9, 9, 9]


def test_cut_camera_matches_the_engine_constants():
    # ((A + 180) / 360) * 2 pi - pi, as SetValidStartPos computes it, is A in radians
    f = need()
    r = f.cut_camera(dict(distance_m=1.0, height_m=0.0, angle_deg=-35.0), [0, 0, 0], [0, 0, 1])
    assert r["position"][0] == pytest.approx(math.sin(math.radians(-35.0)), abs=1e-5)
    for a in (-35.0, 0.1, 140.0):
        assert ((a + 180.0) / 360.0) * 2 * math.pi - math.pi == pytest.approx(math.radians(a))


# ------------------------------------------------------------ event payloads
def test_events_carry_their_payload_and_name_the_stale_slots(meta):
    st = _state(meta, "Rorschach", "Finish_move_A")
    cuts = [e for e in st["events"] if e["name"] == "CAMERA_CUT"]
    first = cuts[0]
    assert first["payload"]["m_nvalue02"] == 1.5 and first["payload"]["m_nvalue10"] == 180.0
    assert first["payload"]["m_ttruth1"] is True and first["payload"]["m_ivalue00"] == 5
    # the two vectors are not read by the CAMERA_CUT case: named, not dumped
    assert first["payload_stale"] == ["m_vvalue1", "m_vvalue2"]
    assert "m_vvalue1" not in first["payload"]
    rumble = next(e for e in st["events"] if e["name"] == "RUMBLE")
    assert rumble["payload"] == {"m_nvalue02": 1.0} and rumble["payload_stale"] == ["m_ivalue00"]
    # an id without a decoded handler keeps every set slot
    assert "payload_stale" not in next(
        e for e in st["events"] if e["name"] == "KILL_ANIMATION_PARTNER"
    )
    # the clip table shares the records
    clip = meta["clips"]["RSH_COM_ATT_finish_EN4_A"]
    assert any("payload" in e for e in clip["events"])
    f = need()
    assert set(f.EVENT_FIELDS[59][1]) >= {"m_nvalue02", "m_nvalue05", "m_nvalue10", "m_ttruth2"}
    assert meta["fx"]["event_fields"]["59"]["fields"]["m_nvalue04"]["arg"] == "time_multiplier"


def test_existing_content_is_unchanged_apart_from_added_keys(fx_extract, monkeypatch):
    need()
    with_fx = am.build(str(fx_extract))
    monkeypatch.setattr(fx, "attach", lambda meta, *a, **k: meta)
    without = am.build(str(fx_extract))
    assert "fx" not in without and with_fx["fx_format"] == fx.FORMAT

    def strip(m):
        m = copy.deepcopy(m)
        m.pop("fx", None)
        m.pop("fx_format", None)
        for c in m["classes"].values():
            for s in c["states"]:
                s.pop("fx", None)
                for e in s["events"]:
                    e.pop("payload", None)
                    e.pop("payload_stale", None)
                    e.pop("payload_editor_hidden", None)
        for c in m["clips"].values():
            for e in c["events"]:
                e.pop("payload", None)
                e.pop("payload_stale", None)
                e.pop("payload_editor_hidden", None)
        for p in m["pairs"]:
            for k in ("camera_cuts", "camera_return", "fx"):
                p.pop(k, None)
        return m

    assert json.dumps(strip(with_fx), sort_keys=True) == json.dumps(without, sort_keys=True)
    json.dumps(with_fx)  # JSON clean


# ------------------------------------------------------------------ state fx
def test_state_fx_uses_the_times_of_the_event_records(meta):
    st = _state(meta, "Rorschach", "Finish_move_A")
    sfx = st["fx"]
    assert [c["playpos"] for c in sfx["camera_cuts"]] == [0.2, 0.5, 0.6]
    c0, c1, c2 = sfx["camera_cuts"]
    # clip time = playpos * 4 s; play time = (playpos - start 0.1) * 4 s / speed 2
    assert (c0["time_s"], c0["play_time_s"]) == (0.8, 0.2)
    assert (c1["time_s"], c1["play_time_s"]) == (2.0, 0.8)
    assert c0["look_at"] == "attack_target" and c0["look_at_joint"] == "Pelvis"
    assert (c0["distance_m"], c0["height_m"], c0["angle_deg"], c0["fov_deg"]) == (
        1.5,
        2.1,
        180.0,
        65.0,
    )
    assert c0["placement"] == "angle" and c0["transition_s"] == 0.0 and "shake" not in c0
    assert c1["look_at"] == "actor" and c1["time_multiplier"] == 0.1
    assert c1["shake"] == {"time_s": 0.6, "time_factor": 50.0, "size": 0.1}
    # bone 18 is the looked-at root + height, not a joint (GetLookAtPosition 0x634125)
    assert c2["placement"] == "previous_position" and c2["look_at_joint"] is None
    assert c2["look_at_point"] == "root" and c0["look_at_point"] == "joint"
    assert sfx["camera_return"] == [
        {
            "playpos": 0.8,
            "time_s": 3.2,
            "play_time_s": 1.4,
            "transition_s": 0.3,
            "set_in_vector": True,
        }
    ]
    assert sfx["rumble"][0] == {
        "playpos": 0.3,
        "time_s": 1.2,
        "play_time_s": 0.4,
        "duration_s": 0.13,
        "power": 1.0,
        "fade": False,
    }
    look = sfx["look_at"][0]
    assert look["trigger"] == "ENTER_STATE" and look["play_time_s"] == 0.0
    assert (look["duration_s"], look["fov_factor"], look["target"]) == (0.7, 0.61, "self")
    assert sfx["weapon_events"][0]["action"] == "steal_from_partner"
    # the slow shot lasts from its cut to the next one, on the state's play time
    assert sfx["slow_motion"] == [
        {
            "from_s": 0.8,
            "to_s": 1.0,
            "time_multiplier": 0.1,
            "real_s": 2.0,
            "real_s_basis": "no_blend",
            "blend_s": 0.1,
            "blend_from_multiplier": 1.0,
        }
    ]
    assert "fx" not in _state(meta, "Rorschach", "Run")


def test_impact_effects_entries_and_the_extra_effect(meta):
    sfx = _state(meta, "Rorschach", "Finish_move_A")["fx"]
    a, b = sfx["impact_effects"]
    assert (a["damage_pose"], a["damage_pose_name"], a["hit_position"]) == (
        5,
        "LIGHT_MIDDLE_STRAIGHT",
        "BODY",
    )
    assert a["local_position"] == [0.5, 0.35, 0.3] and a["local_direction"] == [0.0, 0.0, 1.0]
    assert a["ignore_weapon"] is False and "extra_effect" not in a
    assert b["damage_pose"] == 27 and b["hit_position"] == "HEAD" and b["ignore_weapon"] is True
    key = b["extra_effect"]
    assert key.startswith(EFFECTDB + "#") and meta["fx"]["effects"][key]["name"] == "Discharge"


def test_slow_motion_intervals():
    f = need()
    cuts = [
        {"time_s": 1.0, "time_multiplier": 1.0},
        {"time_s": 2.0, "time_multiplier": 0.5},
        {"time_s": 2.5, "time_multiplier": 0.25},
    ]
    got = f.slow_motion(cuts, [{"time_s": 3.0}])
    keys = ("from_s", "to_s", "time_multiplier", "real_s")
    assert [{k: r[k] for k in keys} for r in got] == [
        {"from_s": 2.0, "to_s": 2.5, "time_multiplier": 0.5, "real_s": 1.0},
        {"from_s": 2.5, "to_s": 3.0, "time_multiplier": 0.25, "real_s": 2.0},
    ]
    # real_s takes each cut as hard; the multiplier a blend would start from is given
    assert [(r["real_s_basis"], r["blend_from_multiplier"]) for r in got] == [
        ("no_blend", 1.0),
        ("no_blend", 0.5),
    ]
    # no return: open until the end of the move
    assert f.slow_motion(cuts[:2], [], end=4.0)[0]["to_s"] == 4.0
    assert f.slow_motion(cuts[:2], [])[0]["real_s"] is None


# ---------------------------------------------------------------------- pairs
def test_pair_carries_the_shot_list_on_the_shared_clock(meta):
    (p,) = [x for x in meta["pairs"] if x["master_state"] == "Finish_move_A"]
    assert p["partner_class"] == "Enemy04"
    tl = p["timeline"]
    assert tl["start_playpos"] == 0.1 and tl["playpos_per_second"] == 0.5
    cuts = p["camera_cuts"]
    assert [(c["time_s"], c["playpos"], c["clip_time_s"]) for c in cuts] == [
        (0.2, 0.2, 0.8),
        (0.8, 0.5, 2.0),
        (1.0, 0.6, 2.4),
    ]
    assert cuts[1]["look_at_bone"] == 14 and cuts[1]["angle_deg"] == -35.0
    assert "play_time_s" not in cuts[0]
    assert p["camera_return"] == {
        "time_s": 1.4,
        "playpos": 0.8,
        "clip_time_s": 3.2,
        "transition_s": 0.3,
        "set_in_vector": True,
    }
    assert p["fx"]["end_s"] == 1.8
    assert [(s["from_s"], s["to_s"], s["ends_with"]) for s in p["fx"]["shots"]] == [
        (0.2, 0.8, "cut"),
        (0.8, 1.0, "cut"),
        (1.0, 1.4, "return"),
    ]
    assert p["fx"]["shots"][1]["real_s"] == 2.0
    assert p["fx"]["slow_motion"] == [
        {
            "from_s": 0.8,
            "to_s": 1.0,
            "time_multiplier": 0.1,
            "real_s": 2.0,
            "real_s_basis": "no_blend",
            "blend_s": 0.1,
            "blend_from_multiplier": 1.0,
        }
    ]


def test_pair_events_of_the_partner_follow_the_master_clock(meta):
    (p,) = [x for x in meta["pairs"] if x["master_state"] == "Finish_move_A"]
    imp = p["fx"]["impact_effects"]
    # the partner's impact at 0.2 is at or before its own start (0.25): never fires;
    # the one at 0.9 fires when the MASTER's play position gets there
    assert [(i["actor"], i["playpos"], i["time_s"], i["damage_pose"]) for i in imp] == [
        ("master", 0.3, 0.4, 5),
        ("master", 0.65, 1.1, 27),
        ("partner", 0.9, 1.6, 2),
    ]
    assert imp[1]["ignore_weapon"] is True and imp[1]["extra_effect"].startswith(EFFECTDB)
    assert p["fx"]["weapon_cases"]["master"][-1] == "uber"
    assert [(r["actor"], r["time_s"]) for r in p["fx"]["rumble"]] == [
        ("master", 0.4),
        ("partner", 0.8),
    ]
    assert p["fx"]["weapon_events"][0]["action"] == "steal_from_partner"
    # a pair is resolved to effects through the victim's class
    f, top = need(), meta["fx"]
    d = top["class_effect_defs"]["Enemy04"]
    assert top["effect_defs"][d]["name"] == "EnemyDamageEffectDef"
    names = [top["effects"][k]["name"] for k in f.resolve_slots(top, d, 5)]
    assert names == ["body_light"]
    keys = f.resolve_slots(top, d, 27, "taser")
    assert [top["effects"][k]["name"] for k in keys] == ["Discharge", "head_steel", "knock"]
    assert f.resolve_slots(top, d, 1) == [None]  # the slot is empty in the data


# --------------------------------------------------------------------- tables
def test_effect_table_and_sound_meta_keys(meta, fx_extract):
    import sound_meta

    top = meta["fx"]
    assert top["format"] == need().FORMAT == meta["fx_format"]
    by_name = {e["name"]: (k, e) for k, e in top["effects"].items()}
    k, e = by_name["body_light"]
    assert k == EFFECTDB + "#" + e["ref"][1] and e["effect_id"] == -1
    (part,) = e["particles"]
    assert part["particle"] == "/Art/fx/hit.particle" and part["placement"] == "POS_AND_ORIENT"
    assert part["slot"][0] == PARTICLEDB and part["local_position"] == [0.0, 0.1, 0.0]
    assert e["speaks"] == [{"speak_id": 30, "speak": sound_meta.SPEAK_ID[30]}]
    # the sound is a key into sound_meta's definitions, not a copy of it
    sm = sound_meta.build(str(fx_extract))
    assert e["sounds"][0]["definition"] in sm["definitions"]
    assert set(e["sounds"][0]) == {"definition", "definition_name", "placement"}
    assert top["effects_by_id"] == {"1": by_name["Discharge"][0]}
    assert by_name["Discharge"][1]["effect_id_name"] == "ELECTRIC_ARMOR_DISCHARGE"
    assert by_name["RSH_head"][1]["particles"] == []
    defs = {d["name"]: d for d in top["effect_defs"].values()}
    en = defs["EnemyDamageEffectDef"]
    assert en["characters"] == ["Dominatrices"] and defs["RSH_DamageEffectDef"]["characters"] == [
        "Rorchach"
    ]
    assert en["slots"]["bodyfast"] == by_name["body_light"][0] and en["slots"]["headfast"] is None
    assert sorted(en["slots"]) == sorted(need().DAMAGE_SLOTS)
    assert top["class_effect_defs"]["Rorschach"] == next(
        k for k, d in top["effect_defs"].items() if d["name"] == "RSH_DamageEffectDef"
    )
    # particles are listed once, with what is known about them (the file is not there)
    assert top["particles"]["/Art/fx/hit.particle"] == {"file_found": False}


def test_particle_facts_from_the_property_bag(tmp_path, monkeypatch):
    f = need()
    doc = {
        "blocks": [
            {
                "class": "ParticleSystemAsset",
                "props": [{"key": "duration", "value": 1.0}, {"key": "loop", "value": 0}],
            },
            {"class": "ParticleType", "props": [{"key": "particleLife", "value": 0.2}]},
            {"class": "ParticleType", "props": [{"key": "particlelife", "value": 0.45}]},
            {"class": "BurstSpawner", "props": [{"key": "particleLife", "value": 9.0}]},
        ]
    }
    monkeypatch.setattr(kapow_props, "parse", lambda b: doc)
    p = tmp_path / "x.particle"
    p.write_bytes(b"x")
    assert f.particle_facts(str(p)) == {
        "emit_duration_s": 1.0,
        "loop": False,
        "types": 2,
        "particle_life_s_max": 0.45,
    }
    assert f.particle_facts(str(tmp_path / "missing.particle")) is None


def test_weapons_gfx_matrix_and_camera_rig(meta):
    top = meta["fx"]
    (w,) = top["weapons"]
    assert (
        w["collection"] == "DominitrixWeapons_1H" and w["model"] == "/Art/weapons/PoliceBaton.model"
    )
    assert (w["effect_type"], w["effect_type_name"], w["weapon_type_name"]) == (
        1,
        "STEEL",
        "BASH_1H",
    )
    assert top["effects"][w["break_effect"]]["name"] == "knock"
    assert w["emitters"][0]["particle"] == "/Art/fx/torch.particle"
    g = top["gfx_matrix"]
    assert g["packages"] == 2 and list(g["rows"]) == ["9"]  # the empty package is left out
    assert g["rows"]["9"]["rows"] == [
        {
            "surface": "WOOD_BOARD",
            "surface_id": 7,
            "particle": "/particles/dust.particle",
            "decal": None,
        }
    ]
    rig = top["camera"]["rig"]["RorschachSingle"]
    assert rig["nodes"]["CharacterCamera"] == {"_ndefaultfov": 55.0}  # debug switches left out
    assert rig["nodes"]["CameraCombatSpecialCuts"] == {"ncoopfov": 70.0}
    (st,) = rig["states"]
    assert st["camera"] == "COMBAT" and st["m_nverticalfov"] == 60.0
    assert st["transitions"][0]["to"] == "DEFAULT"
    assert top["camera"]["cut_placement"]["evidence"] == "read"
    assert "0x6341f7" in top["evidence"]["camera.cut_placement"]
    assert top["counts"]["camera_cut_events"] == 3 and top["counts"]["pair_cuts"] == 3
    # CharacterVisual.SetupBoneMap: bone type -> joint name
    assert (
        top["camera"]["bone_joints"]["14"] == "R Hand" and len(top["camera"]["bone_joints"]) == 23
    )


def test_character_attachments_for_the_glb_extras(meta, fx_extract):
    f = need()
    chars = meta["fx"]["characters"]
    dom = chars["Dominatrices"]
    assert dom["body_class"] == "Enemy04" and dom["character_type"] == 33
    (em,) = dom["attachments"]
    assert em["kind"] == "emitter" and em["particle"] == "/Art/fx/sparks.particle"
    assert em["bone_index"] == 2 and em["auto_start"] is True
    assert [x["class"] for x in em["parents"]] == ["Model", "BoneAttacher"]
    assert em["parents"][0]["model"] == "/Art/tw/TW_weapon.model"
    (lf,) = chars["Rorchach"]["attachments"]
    assert lf["kind"] == "light_flash" and lf["bone_index"] is None
    assert lf["light"] == {
        "color_rgb": [0.86, 0.86, 1.0],
        "brightness": 2.82,
        "range_m": 0.7,
        "light_type": 1,
    }
    f._ATT_CACHE.clear()
    ex = f.character_attachments(str(fx_extract), "Dominatrices", ["Root", "Spine", "R Hand"])
    row = ex["fx_attachments"]["attachments"][0]
    assert row["bone"] == "R Hand" and "ref" not in row
    # the export's character name for the hero differs from its fragment stem
    assert f.character_attachments(str(fx_extract), "Rorschach")["fx_attachments"]["attachments"]
    assert f.character_attachments(str(fx_extract), "Nobody") == {}
    base = {"reconstruction": {"shipped": False}}
    merged = f.with_attachments(base, str(fx_extract), "Dominatrices")
    assert set(merged) == {"reconstruction", "fx_attachments"} and "fx_attachments" not in base
    assert f.with_attachments(None, str(fx_extract), "Nobody") is None
    # with the anim_meta table at hand its `fx` block is used: no fragment is read again
    f._ATT_CACHE.clear()
    again = f.with_attachments(None, "/nonexistent/extract", "Dominatrices", ["a", "b", "c"], meta)
    assert again["fx_attachments"]["attachments"][0]["bone"] == "c"
    f._ATT_CACHE.clear()


def test_fxmeta_sidecar_and_command(meta, fx_extract, tmp_path, capsys):
    f = need()
    side = f.build(str(fx_extract), meta)
    assert side["format"] == f.FORMAT and "effects" in side
    (st,) = side["states"]["Rorschach"]
    assert st["name"] == "Finish_move_A" and st["fx"]["camera_cuts"]
    (p,) = side["pairs"]
    assert p["pair"] == 0 and len(p["camera_cuts"]) == 3 and p["camera_return"]["time_s"] == 1.4
    # without an anim_meta: the tables only
    assert "states" not in f.build(str(fx_extract))
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    try:
        import watchmen
    finally:
        sys.path.remove(str(root))
    out = tmp_path / "fx.json"
    watchmen.main(["watchmen.py", "fxmeta", str(fx_extract), str(out)])
    assert "fx.json" in capsys.readouterr().out
    assert json.loads(out.read_text())["format"] == f.FORMAT
