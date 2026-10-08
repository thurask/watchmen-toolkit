"""combat_meta: the combat block of the animation metadata.

Offline: a synthetic extract (one hero class, one enemy class, a combo
database, a CharacterDef with an EnemyDef, a CharVisual link).  Every test
here fails on the tree without wlib/combat_meta.py.
"""

import json

import pytest

import anim_meta as am
import anim_state_machine as asm
import combat_meta as cm
import engine_enums as ee
import face_rule
import kapow_props
from test_anim_meta import Frag, write_clip

RORSCHACH, ENEMY_04 = 1, 7
PUNCH, HEAVY_PUNCH, COUNTER, FINISH, INITIAL = 0, 7, 12, 3, 21
LIGHT, HEAVY, ANY = 4, 5, 17


def _h(stem):
    return "%08x" % kapow_props.name_hash(stem)


def _write(frag, root, rel):
    p = root / "extracted" / (rel + ".fragment.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"instances": [frag.cls], "nodes_full": frag.nodes}))


def _crit(f, owner, name, **props):
    props.setdefault("m_ianimationcriteria", 2)
    return f.add("AnimationCriteriaWM", "{criteria: %s}" % name, owner, **props)


def _action(f, owner, action, name=None, **kw):
    return _crit(
        f, owner, name or "ACTION", m_ianimationcriteria=1, m_ianimationaction=action, **kw
    )


def _events(f, state, rows):
    ev = f.add("Folder", "Events", state)
    for label, pos in rows:
        f.add(
            "AnimationEventWM",
            "",
            ev,
            m_nplaypos=pos,
            m_ieventtype=0,
            m_ianimationevent=ee.ident("ANIMATION_EVENT", label),
            m_nvalue=0.0,
        )


ATTACK_EVENTS = [
    ("CLEAR_DEADZONE", 0.5),
    ("PRE_IMPACT", 0.55),
    ("IMPACT", 0.6),
    ("BRANCH", 0.65),
    ("CAN_GO_TO_MOVEMENT", 0.8),
]


@pytest.fixture
def extract(tmp_path):
    # ---- combo database + special def (CharacterDef.fragment)
    c = Frag()
    db = c.add(
        "CharacterComboDatabase",
        "Enemy Combos",
        m_ndefaultdamagefastunarmed=5.0,
        m_ndefaultdamagefast1hweapon=12.0,
        m_ndefaultdamagefast2hweapon=15.0,
        m_ndefaultdamageheavvunarmed=10.0,
        m_ndefaultdamageheavy1hweapon=20.0,
        m_ndefaultdamageheavy2hweapon=25.0,
        m_ndefaultdamagecounterattack=10.0,
        m_ndefaultdamagethrow=10.0,
    )

    def string(name, items, **props):
        s = c.add("CharacterComboString", name, db, **props)
        for item, status in items:
            c.add("CharacterComboItem", "{i}", s, m_icomboitem=item, m_itargetstatus=status)
        return s

    ffh = string("{[F] [F] [H]}", [(1, 0xFFFFFFFF), (1, 0xFFFFFFFF), (4, 0xFFFFFFFF)])
    string(
        "{[F] [H] => stun}",
        [(1, 0xFFFFFFFF), (4, 0xFFFFFFFF)],
        m_iforcespecialanimation=2,
        m_nstunduration=6.0,
    )
    string("{[H] vs knee}", [(4, 8)], m_iforcespecialanimation=1)
    c.add("CharacterSpecialDef", "special", m_nbullrushdamage=40.0, m_nbullrushstun=3.0)
    _write(c, tmp_path, "TNT/GameEssentials/CharacterDef")

    # ---- CharVisual link: CharacterVisual.fragment -> En4CharVisual.fragment
    v = Frag()
    vis = v.add("CharacterVisual", "En4Visual")
    v.add("AnimationCtrlWM", "ctrl", vis, m_ianimationclassid=77)
    _write(v, tmp_path, "TNT/GameEssentials/CharacterVisual/En4CharVisual")
    cv = Frag()
    fn = cv.add(
        "FragmentNode", "", assetName="/TNT/GameEssentials/CharacterVisual/En4CharVisual.fragment"
    )
    _write(cv, tmp_path, "TNT/GameEssentials/CharacterVisual")

    # ---- the enemy: CharacterDef + two EnemyDefs with a reaction table
    e = Frag()
    cd = e.add(
        "CharacterDef",
        "{DOMINATRICE}",
        m_icharactertype=33,
        m_iplayablecharacter=0xFFFFFFFF,
        m_nmaxhealth=100.0,
        m_ncriticalhealth=44.0,
        m_nfinishicontime=3.0,
        _ndamagemodifier=1.5,
        m_ecombosetup={"xref": [_h("CharacterDef"), db]},
        m_emodelfragment={"xref": [_h("CharacterVisual"), fn]},
    )
    rows = dict(
        m_idrs01attack01=LIGHT,
        m_idrs01attack02=LIGHT,
        m_idrs01attack03=LIGHT,
        m_idrs01attack04=ANY,
        m_idrs01result=8,
        m_tdrs01shouldclear=True,
        m_idrs02attack01=LIGHT,
        m_idrs02attack02=LIGHT,
        m_idrs02attack03=LIGHT,
        m_idrs02result=7,
        m_idrs03attack01=0,  # an unused slot: no first attack
        m_idrs03result=6,
    )
    e.add(
        "EnemyDef",
        "{base_def}",
        cd,
        _ndamagemodifier=0.0,
        m_ndamagemodifier=9.0,  # a run-time field: never an input (0x71f0cf)
        m_ideftype=0,
        m_iaitype=33,
        m_nproboffastatt=0.8,
        m_ecomboattack1={"xref": [_h("CharacterDef"), ffh]},
        m_ifreqofcomboattack1=3,
        **rows,
    )
    e.add("EnemyDef", "{phase_1}", cd, _ndamagemodifier=2.0, m_ideftype=2, m_iaitype=33)
    _write(e, tmp_path, "TNT/Enemy/Dominatrices")

    # ---- enemy animation class
    a = Frag()
    root = a.add(
        "AnimationClassWM", "Enemy04AnimationClass", m_ianimationmodeltype=ENEMY_04, m_iclassid=77
    )
    att = a.add("AnimationStateGroupWM", "AttackGroup", root)
    light = a.add("AnimationStateGroupWM", "LightAttacks", att)
    _action(a, light, PUNCH, "ACTION PUNCH", m_tentryonly=True)
    # a stale caption: the stored maximum is 2.0
    _crit(
        a,
        light,
        "ATTACK_MOVE_DIST less than 2.2",
        m_ianimationcriteria=0,
        m_ianimationvalue=4,
        m_iintervaltype=1,
        m_nintervalmin=2.0,
        m_nintervalmax=2.0,
    )
    unarmed = a.add("AnimationStateGroupWM", "Unarmed", light)
    _crit(a, unarmed, "UNARMED", m_ianimationenum=5, m_ianimationenumvalue=0)
    plain = a.add("AnimationStateGroupWM", "Plain", unarmed)  # tests nothing
    general = a.add(
        "AnimationStateGroupWM", "GeneralAttacks", plain, _trandomizetransitiontostate=True
    )
    la = a.state(
        "Light_A",
        general,
        "EN4_COM_ATT_light_A",
        m_tisattackstate=True,
        m_ianimationtype=LIGHT,
        m_nstartplaypos=0.2,
        m_nimpactdistance=1.0,
        m_nimpactdistancemodification=0.07,
        m_idamagepose=6,
        m_tkeepcomboalive=True,
    )
    _events(a, la, ATTACK_EVENTS)
    heavy = a.add("AnimationStateGroupWM", "HeavyAttack", att)
    _action(a, heavy, HEAVY_PUNCH, "ACTION HEAVY_PUNCH")
    stuns = a.add("AnimationStateGroupWM", "Stuns", heavy)
    _crit(a, stuns, "STUN", m_ianimationenum=8, m_ianimationenumvalue=2)
    hs = a.state(
        "Sidekick",
        stuns,
        "EN4_COM_ATT_heavy_A",
        m_tisattackstate=True,
        m_ianimationtype=HEAVY,
        m_tallowsweepatt=True,
        m_nbeginsweepangle=30.0,
        m_idamagepose=11,
    )
    _events(a, hs, ATTACK_EVENTS)
    hgen = a.add("AnimationStateGroupWM", "HeavyGeneral", heavy)
    _crit(a, hgen, "NOT STUN", m_ianimationenum=8, m_ianimationenumvalue=2, m_tnot=True)
    hg = a.state("Heavy_A", hgen, "EN4_COM_ATT_heavy_A", m_tisattackstate=True)
    _events(a, hg, ATTACK_EVENTS)
    cg = a.add("AnimationStateGroupWM", "CounterGroup", root)
    _action(a, cg, COUNTER, "ACTION COUNTER_ATTACK")
    cs = a.state(
        "Counter_A RSH", cg, "EN4_COM_ATT_counter_RSH_A", m_imasterof=10, m_ianimationtype=8
    )
    _events(a, cs, [("IMPACT", 0.5)])
    sl = a.add("Folder", "SlaveStates", root)
    fv = a.add("AnimationStateGroupWM", "FinishingGroup_Victim_01", sl, m_istategroupid=8)
    a.state("Finished_by_Rorshack_A", fv, "EN4_COM_DMG_finish_RSH_A")
    hit = a.add("AnimationStateGroupWM", "HitTakenGroup", root)
    _action(a, hit, 2, "ACTION 2")  # the criterion the game derives type 11 from (0x5ebeb0)
    hr = a.state("LightMiddleRight", hit, "EN4_COM_DMG_light", m_ianimationtype=11)
    _crit(a, hr, "LIGHT_MIDDLE_RIGHT", m_ianimationenum=4, m_ianimationenumvalue=6)
    a.state("Idle", root, "EN4_idle")
    a.write(tmp_path, "Enemy04")

    # ---- hero animation class (no class node, like the shipped hero classes)
    h = Frag()
    fg = h.add("AnimationStateGroupWM", "FinishingMovesGroup")
    _action(h, fg, FINISH, "ACTION FINISHING_MOVE")
    _crit(
        h,
        fg,
        "ATTACK_MOVE_DIST in [0.1;1.6[",
        m_ianimationcriteria=0,
        m_ianimationvalue=4,
        m_iintervaltype=0,
        m_nintervalmin=0.1,
        m_nintervalmax=1.6,
    )
    fs = h.state("Finish_move_A", fg, "RSH_COM_ATT_finish_EN4_A", m_imasterof=8, m_ianimationtype=9)
    _events(h, fs, [("KILL_ANIMATION_PARTNER", 0.7)])
    sl = h.add("Folder", "SlaveStates")
    cv_ = h.add("AnimationStateGroupWM", "Countergroup Victim 01", sl, m_istategroupid=10)
    victim = h.state("Countered_by_EN4_A", cv_, "RSH_COM_DMG_counter_EN4_A")
    _events(h, victim, [("FORCE_ALLOW_BREAKOUT", 0.1), ("FORCE_ALLOW_BREAKOUT_NO_MORE", 0.4)])
    hl = h.add("AnimationStateGroupWM", "LightAttacks")
    _action(h, hl, PUNCH, "ACTION PUNCH")
    ini = h.add("AnimationStateGroupWM", "InitialAttacks", hl)
    _action(h, ini, INITIAL, "ACTION INITIAL_ATTACK")
    s1 = h.state("Initial_A", ini, "RSH_COM_ATT_light_A", m_tisattackstate=True)
    _events(h, s1, ATTACK_EVENTS)
    kicks = h.add("AnimationStateGroupWM", "Kicks", hl)
    _crit(h, kicks, "PRONE", m_ianimationenum=7, m_ianimationenumvalue=4)
    s0 = h.state("Kick", kicks, "RSH_COM_ATT_light_A", m_tisattackstate=True)
    _events(h, s0, ATTACK_EVENTS)
    gen = h.add("AnimationStateGroupWM", "GeneralAttacks", hl)
    s2 = h.state("Chain_A", gen, "RSH_COM_ATT_light_A", m_tisattackstate=True)
    _events(h, s2, ATTACK_EVENTS)
    h.write(tmp_path, "Rorschach")

    for name, dur in (
        ("EN4_COM_ATT_light_A", 2.0),
        ("EN4_COM_ATT_heavy_A", 4.0),
        ("EN4_COM_ATT_counter_RSH_A", 2.0),
        ("RSH_COM_DMG_counter_EN4_A", 2.0),
        ("RSH_COM_ATT_finish_EN4_A", 2.0),
        ("EN4_COM_DMG_finish_RSH_A", 2.0),
        ("RSH_COM_ATT_light_A", 1.0),
    ):
        write_clip(tmp_path, name, ((0, 1, 0), (0, 1, 1)), duration=dur)
    return tmp_path


@pytest.fixture
def meta(extract):
    return am.build(str(extract))


def hero_basis(meta):
    return _state(meta, "Rorschach", "Chain_A")["combat"]["defender"]["whiff_basis"]


def _state(meta, cls, name):
    return next(s for s in meta["classes"][cls]["states"] if s["name"] == name)


# ------------------------------------------------------------------- marker
def test_table_stays_format_2_with_a_combat_marker(meta):
    assert meta["format"] == "watchmen-anim-meta/2"
    assert meta["combat_format"] == cm.COMBAT_FORMAT == meta["combat"]["format"]
    assert "evidence" in meta["combat"] and meta["combat"]["not_established"]


def test_existing_state_fields_are_untouched(extract, meta):
    """The hook only ADDS keys: every key anim_meta.state_record writes keeps
    its value."""
    added = {"group_criteria", "criteria_rendered", "combat", "face"}
    classes = am.load_classes(str(extract))
    for cn, c in classes.items():
        plain = {n.name: am.state_record(n) for n in c["nodes"] if n.cls == asm.CLS_STATE}
        for s in meta["classes"][cn]["states"]:
            ref = plain[s["name"]]
            for k in ref:
                if k not in ("events", "duration_s"):  # these need the clip facts
                    assert s[k] == ref[k], (cn, s["name"], k)
            assert set(s) - set(ref) <= added


# ----------------------------------------------------------------- criteria
def test_intervals_are_rendered_from_the_stored_values(meta):
    """The caption says 2.2, the stored maximum is 2.0 (seen in the shipped
    Enemy04 dash group): the rendered text follows the value."""
    s = _state(meta, "Enemy04", "Light_A")
    g = {x["group"].split("/")[-1]: x for x in s["group_criteria"]}
    assert {"text": "ATTACK_MOVE_DIST < 2"} in g["LightAttacks"]["criteria"]
    assert {"text": "ACTION PUNCH", "entry_only": True} in g["LightAttacks"]["criteria"]
    assert g["Unarmed"]["criteria"] == [{"text": "WEAPON_ANIMATION_TYPE = UNARMED"}]


def test_group_chain_is_outermost_first_with_the_random_flag(meta):
    s = _state(meta, "Enemy04", "Light_A")
    names = [x["group"].split("/")[-1] for x in s["group_criteria"]]
    # AttackGroup and Plain test nothing and do not pick at random: left out
    assert names == ["LightAttacks", "Unarmed", "GeneralAttacks"]
    assert [x["random_pick"] for x in s["group_criteria"]] == [False, False, True]


def test_negated_and_target_mode_criteria_render():
    k = asm.Node("k", asm.CLS_CRIT, "{criteria: NOT PRONE}")
    k.props = {
        "m_ianimationcriteria": 2,
        "m_ianimationenum": 7,
        "m_ianimationenumvalue": 4,
        "m_tnot": True,
    }
    assert cm.render_criterion(k) == "NOT TARGET_MODE = TARGET_PRONE"
    assert cm.TARGET_MODE[3] == "TARGET_STUNNED_OR_ON_KNEE"


# ------------------------------------------------------------- attack block
def test_every_attack_state_gets_a_block(meta):
    for cn, c in meta["classes"].items():
        for s in c["states"]:
            if s["attack_state"]:
                assert s["combat"]["kind"] == "attack", (cn, s["name"])
    k = meta["combat"]["classes"]
    assert k["Enemy04"]["attack_states"] == 3 and k["Rorschach"]["attack_states"] == 3
    assert meta["combat"]["totals"]["attack_states"] == 6


def test_attack_class_weapon_entry_and_override(meta):
    b = _state(meta, "Enemy04", "Light_A")["combat"]
    assert b["attack_class"] == "light" and b["weapon_classes"] == ["UNARMED"]
    assert b["entry"] == "general" and b["combo_override"]["required"] is None
    assert b["attack_move_dist_m"] == [None, 2.0]
    assert b["flags"] == {"keep_combo_alive": True}
    b = _state(meta, "Enemy04", "Sidekick")["combat"]
    assert b["attack_class"] == "heavy" and b["combo_override"]["required"] == "STUN"
    assert b["sweep"]["beginsweepangle"] == 30.0
    # heavy_attack: an ACTION HEAVY_PUNCH criterion on a group (computed, 0x5f0e63)
    assert b["flags"] == {"sweep": True, "heavy_attack": True}
    assert "STUN" not in _state(meta, "Enemy04", "Heavy_A")["combat"]["combo_override"]["allowed"]
    assert _state(meta, "Rorschach", "Initial_A")["combat"]["entry"] == "initial"
    assert _state(meta, "Rorschach", "Chain_A")["combat"]["entry"] == "general"


def test_damage_is_base_times_modifier_with_its_sources(meta):
    """5 (fast, unarmed, Enemy Combos) x 1.5: the base EnemyDef has no modifier
    of its own (0 -> the CharacterDef's), phase 1 has 2.0.  The EnemyDef's
    m_ndamagemodifier is a run-time field and is never an input."""
    rows = _state(meta, "Enemy04", "Light_A")["combat"]["damage"]
    assert len(rows) == 1
    r = rows[0]
    assert r["character_def"] == "DOMINATRICE" and r["combo_database"] == "Enemy Combos"
    assert r["base"] == 5.0 and r["base_source"] == "m_ndefaultdamagefastunarmed"
    assert r["variants"] == [
        {"modifier": 1.5, "damage": 7.5, "ai_defs": ["base_def"]},
        {"modifier": 2.0, "damage": 10.0, "ai_defs": ["phase_1"]},
    ]
    heavy = _state(meta, "Enemy04", "Sidekick")["combat"]["damage"][0]
    assert heavy["base"] == 10.0 and heavy["variants"][0]["damage"] == 15.0


def test_a_class_without_an_owner_says_why_there_is_no_damage(meta):
    b = _state(meta, "Rorschach", "Chain_A")["combat"]
    assert b["damage"] == [] and "no CharacterDef" in b["damage_reason"]
    assert meta["combat"]["classes"]["Rorschach"]["attack_states_without_damage"]


def test_timings_are_anim_metas_own_event_times(meta):
    """Seconds from entry and play positions are copied from the state's event
    records (start position 0.2, 2 s clip): nothing is re-derived."""
    s = _state(meta, "Enemy04", "Light_A")
    t = s["combat"]["timing"]
    ev = {e["name"]: e for e in s["events"]}
    for key, name in (("pre_impact", "PRE_IMPACT"), ("impact", "IMPACT"), ("branch", "BRANCH")):
        assert t[key]["from_entry_s"] == ev[name]["play_time_s"]
        assert t[key]["playpos"] == ev[name]["playpos"]
    assert t["impact"] == {"playpos": 0.6, "clip_time_s": 1.2, "from_entry_s": 0.8}
    assert t["start_playpos"] == 0.2 and s["combat"]["reach"]["total_m"] == 1.07


def test_counter_window_and_whiff_distance(meta):
    """Counter: 0.13 s of CLIP time must remain before IMPACT (0x68d36a) ->
    play position 0.6 - 0.13 / 2.0.  Whiff: 1.8 m for an AI attacker, none for
    a player class."""
    d = _state(meta, "Enemy04", "Light_A")["combat"]["defender"]
    assert d["counter"]["latest_playpos"] == pytest.approx(0.535)
    assert d["counter"]["latest_from_entry_s"] == pytest.approx(0.67)
    assert d["whiff_distance_m"] == 1.8 and d["reaction_table_sees"] == "LIGHTATTACK"
    assert d["whiff_basis"] == "ai" and hero_basis(meta) == "player"
    assert d["hit_reaction_starts_from_entry_s"] == pytest.approx(0.7)
    hero = _state(meta, "Rorschach", "Chain_A")["combat"]["defender"]
    # the type is computed from the group's ACTION PUNCH criterion (0x5f277a), not stored
    assert hero["whiff_distance_m"] is None and hero["reaction_table_sees"] == "LIGHTATTACK"


def test_combo_speedup_entry_play_position(meta):
    """CLEAR_DEADZONE minus 0.15 s / duration for LIGHTATTACK, 0.2 s for
    HEAVYATTACK; a NOTSET state never speeds up (0x688961)."""
    sp = _state(meta, "Enemy04", "Light_A")["combat"]["combo_speedup"]
    assert sp["applies"] and sp["entry_playpos"] == pytest.approx(0.5 - 0.15 / 2.0)
    assert sp["impact_from_entry_s"] == pytest.approx((0.6 - 0.425) * 2.0)
    sp = _state(meta, "Enemy04", "Sidekick")["combat"]["combo_speedup"]
    assert sp["entry_playpos"] == pytest.approx(0.5 - 0.2 / 4.0)
    # Heavy_A stores no type; its group's ACTION HEAVY_PUNCH makes it HEAVYATTACK (0x5f277a)
    sp = _state(meta, "Enemy04", "Heavy_A")["combat"]["combo_speedup"]
    assert sp["applies"] and sp["entry_playpos"] == pytest.approx(0.5 - 0.2 / 4.0)
    bare = asm.Node("x", asm.CLS_STATE, "x")
    bare.props = {"m_ianimationtype": 4}  # a stored type without a criterion is not used
    off = cm.combo_speedup(bare, {})
    assert not off["applies"] and "NOTSET" in off["reason"]


def test_damage_pose_and_conversions():
    assert cm.pose_name(6) == "LIGHT_MIDDLE_RIGHT" and cm.pose_class(6) == "light"
    assert cm.convert_pose(6, from_behind=True) == 24  # LIGHT_MIDDLE_BACK
    assert cm.convert_pose(2, override="STUN") == 19  # STUN_UPPER
    assert cm.convert_pose(2, override="STUN", from_behind=True) == 21
    assert cm.convert_pose(8, big_target=True, upper=False) == 11
    assert cm.convert_pose(8, big_target=True, upper=True) == 8
    assert cm.convert_pose(8, dy=0.3, hit_y=0.5) == 11 and cm.convert_pose(11, dy=-0.3) == 11
    assert cm.convert_pose(11, dy=-0.3, hit_y=0.5) == 8
    r = cm.rules()["damage_pose"]
    assert r["direction"]["map"]["HEAVY_UPPER_LEFT"] == "HEAVY_UPPER_BACK"
    assert r["order"] == ["combo", "direction", "size", "height"]


def test_other_combat_states_get_a_short_block(meta):
    hr = _state(meta, "Enemy04", "LightMiddleRight")["combat"]
    assert hr == {"kind": "hit_reaction", "damage_poses": ["LIGHT_MIDDLE_RIGHT"]}
    assert _state(meta, "Enemy04", "Counter_A RSH")["combat"]["impact"]["from_entry_s"] == 1.0
    assert "combat" not in _state(meta, "Enemy04", "Idle")


# ---------------------------------------------------------- reaction table
def test_reaction_rows_and_the_deterministic_match(meta):
    ai = next(a for a in meta["combat"]["ai_defs"] if a["name"] == "base_def")
    rows = ai["reaction_rows"]
    assert [r["row"] for r in rows] == [1, 2]  # slot 3 has no first attack
    assert rows[0]["newest_first"][-1] == "AI_SYSTEM_ONLY__ANY_ATTACK" and rows[0]["clear_history"]
    assert cm.react(rows, [LIGHT, LIGHT]) is None
    assert cm.react(rows, [LIGHT, LIGHT, LIGHT])["result"] == "DODGE"
    assert cm.react(rows, [LIGHT, LIGHT, LIGHT, HEAVY])["result"] == "COUNTERATTACK"
    assert cm.react(rows, [LIGHT, HEAVY, LIGHT, LIGHT]) is None
    assert ai["prob_fast_attack"] == 0.8 and ai["damage_modifier_own"] == 0.0
    assert ai["combos"] == [{"database": "Enemy Combos", "combo": "[F] [F] [H]", "weight": 3}]


# ------------------------------------------------------------------- links
def test_character_def_is_linked_to_its_animation_class(meta):
    d = meta["combat"]["character_defs"][0]
    assert d["name"] == "DOMINATRICE" and d["animation_class"] == "Enemy04"
    assert d["max_health"] == 100.0 and d["critical_health"] == 44.0 and not d["playable"]
    k = meta["combat"]["classes"]["Enemy04"]
    assert k["character_defs"] == ["DOMINATRICE"] and k["combo_databases"] == ["Enemy Combos"]
    assert k["class_id"] == 77 and not k["big"] and not k["playable"]
    assert meta["combat"]["classes"]["Rorschach"]["class_id"] == face_rule._class_id_by_name(
        "Rorschach"
    )


# ------------------------------------------------------------------ combos
def test_combo_steps_carry_the_override_in_effect_and_their_groups(meta):
    """[F][H] => STUN: pressing H after F completes it, so the H of [F][F][H]
    is played with the STUN override too (longest string equal to the tail of
    the presses).  [H] vs a kneeling target does not count for a standing one."""
    db = meta["combat"]["combo_databases"]["Enemy Combos"]
    assert db["base_damage"]["light"] == {"UNARMED": 5.0, "BASH_1H": 12.0, "BASH_2H": 15.0}
    assert db["counter_damage"] == 10.0
    ffh, fh, knee = db["strings"]
    assert [i["override_in_effect"] for i in ffh["items"]] == [None, None, None]
    assert [i["override_in_effect"] for i in fh["items"]] == [None, "STUN"]
    assert knee["items"][0]["target_status"] == ["KNEE"]
    assert knee["items"][0]["override_in_effect"] == "KNOCKDOWN"
    assert fh["items"][0]["button"] == "light" and fh["items"][1]["weapon_class"] == "UNARMED"
    last = fh["items"][1]["draws_from"]["Enemy04"]
    assert [g.split("/")[-1] for g in last] == ["Stuns"]
    plain = ffh["items"][2]["draws_from"]["Enemy04"]
    assert [g.split("/")[-1] for g in plain] == ["HeavyGeneral"]
    groups = meta["combat"]["classes"]["Enemy04"]["attack_groups"]
    assert groups[last[0]]["combo_override"] == "STUN" and groups[last[0]]["states"] == ["Sidekick"]


# ------------------------------------------------------------ pair trigger
def test_pair_triggers(meta):
    by = {(p["master_class"], p["master_state"]): p for p in meta["pairs"]}
    c = by[("Enemy04", "Counter_A RSH")]["trigger"]
    assert c["rule"] == "enemy_counter" and c["action"] == {"id": 12, "name": "COUNTER_ATTACK"}
    assert c["damage"]["event"] == "IMPACT" and c["damage"]["at"]["from_entry_s"] == 1.0
    # 10 (counter base) x 0.75 (playable victim) x modifier
    assert [(a["modifier"], a["damage"]) for a in c["damage"]["amounts"]] == [
        (1.5, 11.25),
        (2.0, 15.0),
    ]
    assert c["breakout"]["from_s"] == pytest.approx(0.2) and c["breakout"]["to_s"] == pytest.approx(
        0.8
    )
    f = by[("Rorschach", "Finish_move_A")]["trigger"]
    assert f["rule"] == "finisher" and f["distance_m"] == [0.1, 1.6]
    assert f["damage"] == {
        "source": "kill",
        "event": "KILL_ANIMATION_PARTNER",
        "at": {"playpos": 0.7, "clip_time_s": 1.4, "from_entry_s": 1.4},
        "amount": 100000.0,
    }
    assert f["finisher_prompt"] == [
        {
            "character_def": "DOMINATRICE",
            "critical_health": 44.0,
            "max_health": 100.0,
            "prompt_time_s": 3.0,
        }
    ]
    assert meta["combat"]["totals"]["pair_rules"] == {"enemy_counter": 1, "finisher": 1}
    assert meta["combat"]["rules"]["finisher_prompt"]["button_count"]["PC"] == 3


def test_rules_carry_their_constants_with_addresses():
    r = cm.rules()
    by = {c["address"]: c for c in r["constants"]}
    assert by["0xa5ecc8"]["value"] == 0.13 and by["0x9e5fa0"]["value"] == 1.8
    assert by["0xa46b90"]["value"] == 2.2 and by["0x9eb188"]["type"] == "f64"
    assert r["defender"]["whiff"]["distance_big_attacker_m"] == 2.2
    assert "0x721958" in r["defender"]["reaction_table"]["handler"]


def test_summary_lists_the_classes(meta):
    text = cm.summary(meta)
    assert "Enemy04" in text and "3 attack states" in text
    assert cm.summary({"format": "x"}).startswith("no combat block")


def test_an_attack_on_a_prone_target_is_a_kick(meta):
    """Groups that require TARGET_MODE 4 (prone): the combo item is KICK while
    the base damage stays the button's (AddAttackToCombo 0x68bca8)."""
    b = _state(meta, "Rorschach", "Kick")["combat"]
    assert b["target_mode"] == {"requires": ["TARGET_PRONE"], "excludes": []}
    assert b["combo_item"] == "KICK" and b["attack_class"] == "light"
    assert "combo_item" not in _state(meta, "Rorschach", "Chain_A")["combat"]


def test_a_failing_combat_build_does_not_take_the_table_down(extract, monkeypatch):
    def boom(*a, **k):
        raise KeyError("unreadable")

    monkeypatch.setattr(cm, "CombatData", boom)
    logged = []
    m = am.build(str(extract), log=lambda *a: logged.append(" ".join(str(x) for x in a)))
    assert "combat" not in m and "combat_format" not in m and m["format"] == am.FORMAT
    assert any("combat: skipped" in x for x in logged)
