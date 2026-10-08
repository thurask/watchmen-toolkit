"""Final sweep, combat: the rules read since (electrify range, sweep check point, bull
rush, faction filter, partner AI, Underboss, achievements), the data they add to the
combat block, and the enum families.

Synthetic fixtures only (the combat feature's extract, extended)."""

import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import combat_meta as cm
import engine_enums as ee

import test_combat_meta as tc
from test_anim_meta import Frag

extract = tc.extract


class _Node:
    def __init__(self, cls, **props):
        self.cls, self.props = cls, props

    def p(self, k, default=None):
        return self.props.get(k, default)


# ---------------------------------------------------------------- fixed rules
def test_electrify_range_is_the_code_constant():
    r = cm.rules()
    text = r["pair_damage"]["ELECTRIFY_ARMOR"]
    assert "t = max(0, (10.0 - d) / 10.0)" in text and "m_nelectrifyrange is not read here" in text
    assert "0x6a71b6" in text
    assert "one further factor" not in text and "not established" not in text
    assert "front 17 / 14, behind 28 / 27" in text and "push 13.0 * t" in text
    assert r["pair_damage"]["ELECTRIFY_ARMOR_range_m"] == cm.ELECTRIFY_RANGE_M == 10.0
    (c,) = [x for x in r["constants"] if x["address"] == "0x9eb1d8"]
    assert c["value"] == 10.0 and c["type"] == "f32"


def test_sweep_has_the_check_point_and_the_direction_rule():
    s = cm.rules()["sweep"]
    assert "not_established" not in s
    assert s["check_point"].startswith("P = visual world position") and "pct" in s["check_point"]
    assert "DetermindTravDir 0x69b2be" in s["direction"]
    assert "m_tcounterclockwise is not read" in s["direction"]


def test_bull_rush_and_the_faction_filter_are_rules():
    r = cm.rules()
    b = r["bull_rush"]
    assert b["evidence"].startswith("read from code (PC)")
    assert "0x696d2d" in b["contact"] and "Freight Train" in b["contact"]
    assert set(b["secondary"]) == {
        "who",
        "radius",
        "in_front",
        "gate",
        "damage",
        "stun",
        "pose",
        "push",
        "low_violence",
    }
    assert "diagonal to sideways" in b["secondary"]["push"]
    assert "1.1 m" in b["blocked_by_player"]
    f = r["attack_permission"]["faction_filter"]
    assert "GetVisibleAIEnemies 0x484235" in f and "NEUTRALFACTION (2)" in f
    assert "the unique attack id" in r["attack_id"] and "1.5 s" in r["attack_id"]
    assert "three callers" in r["damage"]["override"]
    assert r["special_handling"]["BULL_MOVE"].startswith("BULL_MOVE: after event 15 CHARGE")
    assert "GAME_MODES" in r["damage"]["death"]["game_modes"]


def test_partner_ai_rule_block():
    p = cm.rules()["partner_ai"]
    assert p["mega_kill"] == {
        "attack_interval_max_s": 0.5,
        "attack_interval_min_s": 0.0,
        "damage_modifier": 10.0,
    }
    assert p["react_multipliers"]["stun_lock_unblockable"] == 0.7
    assert p["follow"]["speed_match"]["rorschach"] == [3.32, 4.83]
    assert p["find_closest_radius"] == "sqrt(visual_range)"
    assert len(p["known_defects"]) == 2 and "0x6f2428" in p["known_defects"][0]
    json.dumps(p)


def test_underboss_rule_only_with_a_definition():
    assert "underboss" not in cm.rules()
    u = cm.rules(None, [{"name": "UB"}])["underboss"]
    assert u["success_test"]["handlers"] == {"true": "0x7f09ac", "false": "0x87b96e"}
    assert u["react"]["hits_before_block"] == 3 and u["react"]["blocks_before_counter"] == 2
    assert u["react"]["counter"]["phase_1_2"]["unfire"] == ["PUNCH"]
    assert u["react"]["counter"]["phase_3_4"]["override_attack_combo"] == "KNOCKDOWN"
    assert "Underboss in the enemy's local +z" in u["interrupts"]["rules"][1]
    assert u["shockwave"]["spread_speed_used"] is False and u["shockwave"]["damage_radius"] == 2.5
    assert u["attack"]["switch_to"] == "first other known enemy"
    # the re-check time is a registered default (0x8a1b34), not a code constant
    assert u["attack"]["target_recheck"] == 6.0
    assert "registered default" in u["attack"]["target_recheck_is"]
    assert "target re-check time are registered defaults" in u["evidence"]
    assert u["game_events"]["700"] == "UNDERBOSS_GOTO_PHASE1"
    assert u["game_events"]["715"] == "UNDERBOSS_PLATFORM_HIT4" and len(u["game_events"]) == 16
    assert u["defs"] == [{"name": "UB"}]


def test_underboss_phases_of_the_shipped_fractions():
    ph = cm.underboss_phases(0.8, 0.7, 0.5, 4)
    assert [(p["start"], p["end"]) for p in ph["phases"]] == [
        (1.0, 0.8),
        (0.8, 0.7),
        (0.7, 0.5),
        (0.5, 0.375),
        (0.375, 0.25),
        (0.25, 0.125),
        (0.125, 0.0),
    ]
    assert [p.get("stage") for p in ph["phases"]] == [None, None, None, 1, 2, 3, 4]
    assert ph["stage_count"] == 4 and ph["phase4_reaches_zero"] is True
    # the stage count is hard-coded: six steps make smaller stages that stop above zero
    six = cm.underboss_phases(0.8, 0.7, 0.5, 6)
    assert len(six["phases"]) == 7 and six["phase4_reaches_zero"] is False
    assert six["phases"][-1]["end"] == pytest.approx(0.5 - 4 * 0.5 / 6, abs=1e-6)
    # two steps: the floor is 0 from stage 2 on
    two = cm.underboss_phases(0.8, 0.7, 0.5, 2)
    assert [p["end"] for p in two["phases"][3:]] == [0.25, 0.0, 0.0, 0.0]
    assert cm.underboss_phases(0.8, None, 0.5, 4) is None


def test_not_established_names_what_is_left():
    text = " | ".join(cm.NOT_ESTABLISHED)
    for settled in (
        "sweep check point",
        "bull rush contact",
        "ElectricArmor.AreaDamage",
        "filters by faction",
        "names of game modes",
        "Underboss attack-success",
    ):
        assert settled not in text, settled
    assert "partner AI)" not in text and "BehaviorWaypointMove" not in text
    assert "0x47dfed" in text and "m_nelectrifyrange" not in text
    assert "flee geometry" not in text and "Underboss: whether the registered defaults" in text
    assert "1,207 / 1,174 files" in text and "0x4fa365" in text


# ---------------------------------------------------------------- achievements
def test_achievement_names_are_the_exe_family():
    assert cm.ACHIEVEMENTS == {int(k): v for k, v in ee.family("ACHIEVEMENTS").items()}
    assert cm.ACHIEVEMENTS[6] == "RRARARARGHGH" and len(cm.ACHIEVEMENTS) == 24


def test_achievements_take_thresholds_from_the_fragment_else_the_registered_default():
    p2 = _Node("AchievementPart2Ctrl", _itagem_requiredstomps=12)
    p1 = _Node(
        "AchievementCtrl",
        _nturbo_requiredtimetocompletegame=4800.0,
        _ishield_requiredblocksordodges=25,
    )
    a = cm.achievements([("Enemy/Achievements.fragment", p2), ("x", _Node("Other")), ("P1", p1)])
    c2 = a["controllers"]["AchievementPart2Ctrl"]
    assert c2["fragment"] == "Enemy/Achievements.fragment"
    assert c2["thresholds"]["_itagem_requiredstomps"] == 12
    assert c2["threshold_source"]["_itagem_requiredstomps"] == "fragment"
    assert c2["thresholds"]["_itagem_timelimit"] == 10.0  # not stored: the registered default
    assert c2["threshold_source"]["_itagem_timelimit"] == "registered default"
    assert sorted(int(k) for k in c2["conditions"]) == list(range(12))
    assert c2["conditions"]["3"]["name"] == "TAGEM"
    assert "the other hero threw" in c2["conditions"]["3"]["condition"]
    c1 = a["controllers"]["AchievementCtrl"]
    assert sorted(int(k) for k in c1["conditions"]) == list(range(12, 24))
    assert c1["thresholds"]["_nturbo_requiredtimetocompletegame"] == 4800.0
    assert c1["thresholds"]["_ivigilante_inseconds"] is None  # no default is registered
    assert "no default" in c1["threshold_source"]["_ivigilante_inseconds"]
    assert len(a["defects"]) == 2 and "0x59925d" in a["defects"][0]
    assert "9999.0" in a["turbo_clock"]
    assert cm.achievements([("x", _Node("Other"))])["controllers"] == {}


# ------------------------------------------------------------- the data block
def _extend(root):
    """Achievements, an Underboss and a partner definition, an event that deals damage
    and a BULL_MOVE state on top of the combat feature's extract."""
    a = Frag()
    a.add("AchievementPart2Ctrl", "Achievements", _ifocusfire_enemies=7)
    tc._write(a, root, "TNT/GameEssentials/Enemy/Achievements")

    u = Frag()
    cd = u.add("CharacterDef", "{UNDERBOSS}", m_icharactertype=25, m_nmaxhealth=1000.0)
    u.add(
        "UnderbossDef",
        "{UnderbossDef}",
        cd,
        m_nmaxhealth=1500.0,
        m_nhealthfractiongotonextphase=0.8,
        m_nhealthfraction1gotonextphase=0.7,
        m_nhealthfraction2gotonextphase=0.5,
        m_istepsinphase4=4,
        m_nenemyengagementdist=5.0,
        m_iflamerdamage=3.0,
        m_nvisualrange=30.0,
    )
    pd = u.add("CharacterDef", "{NITE_OWL_AI}", m_icharactertype=1)
    cdb = u.add("CharacterComboDatabase", "Partner Combos")
    s1 = u.add("CharacterComboString", "{[F] [F]}", cdb)
    u.add(
        "PartnerDef",
        "{PartnerDef}",
        pd,
        m_nvisualrange=50.0,
        m_nkillvscrowdcontrol=0.5,
        m_nfollowpartnermovedistancebetweentargetandpartner=2.0,
        m_ncrowdcontrolprobofreactatt=0.6,
        m_tdisallowhelppartnerstate=False,
        m_ecrowdctrlcomboattack1={"ref": s1},
        m_ifreqofcrowdctrlcomboattack1=3,
    )
    tc._write(u, root, "TNT/GameEssentials/Enemy/Boss")

    h = Frag()
    g = h.add("AnimationStateGroupWM", "Specials")
    s = h.state("Shock", g, "EN4_COM_ATT_light_A", m_tisattackstate=True, m_ispecialhandling=6)
    ev = h.add("Folder", "Events", s)
    for pos, truth, value in ((0.25, True, 35.0), (0.5, True, 0.0), (0.75, False, 9.0)):
        h.add(
            "AnimationEventWM",
            "",
            ev,
            m_nplaypos=pos,
            m_ieventtype=0,
            m_ianimationevent=56,
            m_nvalue=value,
            m_ttruth1=truth,
        )
    h.write(root, "Special")
    return root


@pytest.fixture
def meta(extract):
    return am.build(str(_extend(extract)))


def test_combat_block_carries_the_achievements_of_the_extract(meta):
    a = meta["combat"]["achievements"]
    assert list(a["controllers"]) == ["AchievementPart2Ctrl"]
    c = a["controllers"]["AchievementPart2Ctrl"]
    assert c["fragment"].endswith("Enemy/Achievements.fragment")
    assert c["thresholds"]["_ifocusfire_enemies"] == 7
    assert c["thresholds"]["_ielectric_requiredenemies"] == 14
    assert a["names"]["23"] == "EXTERMINATOR"


def test_an_extract_without_the_controllers_has_no_achievements_key(extract):
    m = am.build(str(extract))
    assert "achievements" not in m["combat"] and "underboss" not in m["combat"]["rules"]
    assert m["combat"]["rules"]["damage"]["override_events"] == []


def test_underboss_definition_gives_its_phases_and_the_character_defs_health(meta):
    (d,) = meta["combat"]["rules"]["underboss"]["defs"]
    assert d["name"] == "UnderbossDef" and d["character_def"] == "UNDERBOSS"
    assert d["max_health"] == 1000.0 and d["own_max_health_unread"] == 1500.0
    assert d["enemy_engagement_dist"] == 5.0 and d["flamer_damage"] == 3.0
    assert [p["end"] for p in d["phases"]] == [0.8, 0.7, 0.5, 0.375, 0.25, 0.125, 0.0]
    assert (
        d["phase4_reaches_zero"] is True and "CharacterDef.m_nmaxhealth" in d["max_health_source"]
    )


def test_partner_definition_carries_its_ai_numbers_and_combo_weights(meta):
    defs = {d["name"]: d for d in meta["combat"]["ai_defs"]}
    p = defs["PartnerDef"]
    assert p["visual_range"] == 50.0 and p["kill_vs_crowd_control"] == 0.5
    assert p["follow_side_distance"] == 2.0 and p["prob_react_to_attack"] == 0.6
    assert p["disallow_help_partner"] is False
    assert "follow_stop_distance" not in p  # an absent property is left out
    assert p["crowd_control_combos"] == [
        {"database": "Partner Combos", "combo": "[F] [F]", "weight": 3}
    ]
    assert defs["UnderbossDef"]["visual_range"] == 30.0  # the member exists on that class too
    assert "kill_vs_crowd_control" not in defs["UnderbossDef"]


def test_impact_effects_events_that_deal_damage_are_listed(meta):
    rows = meta["combat"]["rules"]["damage"]["override_events"]
    assert [(r["class"], r["state"], r["override_damage"]) for r in rows] == [
        ("Special", "Specials/Shock", 35.0),
        ("Special", "Specials/Shock", 0.0),
    ]
    assert rows[0]["time_s"] == pytest.approx(0.5) and rows[1]["time_s"] == pytest.approx(1.0)
    assert cm.override_damage_events({}) == []


def test_a_bull_move_state_points_to_its_rule(meta):
    shock = tc._state(meta, "Special", "Shock")
    assert shock["special_handling"]["name"] == "BULL_MOVE"
    assert shock["combat"]["special_handling_rule"] == "BULL_MOVE"
    assert "BULL_MOVE" in meta["combat"]["rules"]["special_handling"]
    other = tc._state(meta, "Rorschach", "Chain_A")
    assert "special_handling_rule" not in other["combat"]


def test_partner_enum_families_are_exported(meta):
    en = meta["combat"]["enums"]
    for name in (
        "PARTNER_AI_STATE",
        "PARTNER_MODIFIED_STATE",
        "PLAYER_AI_STATES",
        "REPEAT_DEFENCE",
        "STOP_CRITERIA",
        "TACTICAL_INFO",
    ):
        assert set(en[name]) == {"evidence", "items"}, name
    assert en["PARTNER_AI_STATE"]["items"]["3"] == "FOLLOW_PARTNER"
    assert en["PARTNER_MODIFIED_STATE"]["items"] == {
        "0": "NONE",
        "1": "LOW_HEALTH",
        "2": "MEGA_KILL",
    }
    assert en["TACTICAL_INFO"]["items"]["1024"] == "PLACEMENT_REAR"
    assert en["TACTICAL_INFO"]["items"]["65536"] == "IS_PRIMARY_TARGET"
    assert "bit mask" in en["STOP_CRITERIA"]["evidence"]
    assert en["AI_DEF_TYPE"]["items"]["2"] == "PHASE_1"  # the older tables are still there


# ----------------------------------------------------------------- enum tables
def test_engine_enums_has_the_four_added_families():
    fam = ee.data()["families"]
    assert fam["ACHIEVEMENTS"]["registered_in"] == "0x80c150"
    assert (
        fam["ACHIEVEMENTS"]["prefix"] == "ACHIEVEMENTS" and len(fam["ACHIEVEMENTS"]["items"]) == 24
    )
    assert fam["PLAYABLE_CHARACTERS"]["prefix"] == "PLAYABLE_CHARACTER"
    assert ee.family("PLAYABLE_CHARACTERS") == {
        -1: "NONE",
        0: "RORSCHACH",
        1: "NITE_OWL",
        2: "BOTH",
    }
    assert ee.family("GAME_MODES") == {
        0: "NONE",
        1: "RORSCHACH",
        2: "NITEOWL",
        3: "COOP",
        4: "MAINMENU",
    }
    assert fam["AIAGENTFACTION"]["registered_in"] == "0x4865b9"
    assert ee.name("AIAGENTFACTION", 2) == "NEUTRALFACTION"


def test_event_semantics_of_the_heading_and_underboss_events():
    es = ee.event_semantics()
    assert "+MathLib.pidiv2 (registered default 1.570796)" in es["54"]["effect"]
    assert "-MathLib.pidiv2" in es["55"]["effect"]
    assert [es[k]["heading_offset_rad"] for k in ("54", "55", "41", "49")] == [
        1.570796,
        -1.570796,
        3.14159274,
        0.0,
    ]
    assert (
        "special handling BLOCK (8)" in es["38"]["effect"]
        and "special state 8" not in es["38"]["effect"]
    )
    assert "starts the landing shockwave" in es["67"]["effect"]
    assert "stores the jump end point" in es["66"]["effect"]
    assert "_ndelaypunishtimer" in es["86"]["effect"] and "disables the pipe" in es["81"]["effect"]
    # the shipped copy of the table says the same
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "..", "docs", "re", "events_table.json"), encoding="utf-8") as fh:
        table = {str(e["id"]): e for e in json.load(fh)}
    for k in ("38", "54", "55", "66", "67", "68", "71", "81", "86"):
        assert table[k]["effect"] == es[k]["effect"], k
