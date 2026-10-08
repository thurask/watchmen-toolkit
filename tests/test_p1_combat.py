"""combat_meta, damage pass: the throw's real damage source (ragdoll contacts),
the receiving side of a hit, the area attacks, the effective damage modifier
and the rules that were listed as not established (sweep stepping, who may
attack when, Twilight Lady's reaction).

Offline: the synthetic extract of test_combat_meta plus a throw master with a
normal and a big partner class and a CharacterVisualDef.
"""

import json

import pytest

import anim_meta as am
import combat_meta as cm
import engine_enums as ee
import test_combat_meta
from test_anim_meta import Frag, write_clip
from test_combat_meta import _action, _write

combat_extract = test_combat_meta.extract

THROW, BIG_GUY, THROW_TYPE = 4, 4, 10
VISUAL_DEF = dict(
    m_nragdollimpactforcethresholdforsound=300.0,
    m_nragdollimpactheightmask=0.6,
    m_nragdollimpactdecreasepersecond=2500.0,
    m_nragdollimpactragdolltrigger=6000.0,
    m_nragdollimpactanimationtrigger=2000.0,
    m_nragdollimpactignoretrigger=500.0,
    m_nragdollimpactforcefromcollider=1.2,
)


def _reopen(path):
    """A Frag over a fragment JSON that is already written."""
    j = json.loads(path.read_text())
    f = Frag()
    f.cls, f.nodes = j["instances"][0], j["nodes_full"]
    f.n = max(int(n["id"], 16) for n in f.nodes)
    return f


def _node_named(f, name):
    return next(n["id"] for n in f.nodes if ["name", "string", name] in n["props"])


@pytest.fixture
def throw_extract(combat_extract):
    root = combat_extract
    cdir = root / "extracted" / "TNT" / "CharacterAnimation"
    # hero: a throw master (ACTION THROW, master of group 12), no damaging event
    h = _reopen(cdir / "AnimationClassRorschach.fragment.json")
    tg = h.add("AnimationStateGroupWM", "ThrowGroup")
    _action(h, tg, THROW, "ACTION THROW")
    h.state(
        "Throw",
        tg,
        "RSH_COM_ATT_throw_A",
        events=[("ALLOW_ATTACKS", 0.9)],
        m_imasterof=12,
        m_ianimationtype=THROW_TYPE,
    )
    h.write(root, "Rorschach")
    # the normal-sized partner
    e = _reopen(cdir / "AnimationClassEnemy04.fragment.json")
    tv = e.add(
        "AnimationStateGroupWM",
        "ThrowGroup_Victim",
        _node_named(e, "SlaveStates"),
        m_istategroupid=12,
    )
    e.state("ThrownByRorschach", tv, "EN4_COM_DMG_throw_RSH_A")
    e.write(root, "Enemy04")
    # a big partner class (model type 4: CharacterRoot.command_is_big)
    b = Frag()
    broot = b.add("AnimationClassWM", "EnemyBigAnimationClass", m_ianimationmodeltype=BIG_GUY)
    sl = b.add("Folder", "SlaveStates", broot)
    bv = b.add("AnimationStateGroupWM", "ThrowGroup_Victim", sl, m_istategroupid=12)
    b.state("ThrownByRorschach", bv, "EN2_COM_DMG_throw_RSH_A")
    b.state("Idle", broot, "EN2_idle")
    b.write(root, "EnemyBig")
    for name in ("RSH_COM_ATT_throw_A", "EN4_COM_DMG_throw_RSH_A", "EN2_COM_DMG_throw_RSH_A"):
        write_clip(root, name, ((0, 1, 0), (0, 1, 1)), duration=2.0)
    # the ragdoll-impact numbers live on the CharacterVisualDef
    v = _reopen(root / "extracted" / "TNT" / "GameEssentials" / "CharacterVisual.fragment.json")
    v.add("CharacterVisualDef", "", **VISUAL_DEF)
    _write(v, root, "TNT/GameEssentials/CharacterVisual")
    return root


@pytest.fixture
def meta(throw_extract):
    return am.build(str(throw_extract))


@pytest.fixture
def plain(combat_extract):
    return am.build(str(combat_extract))


def _throws(meta):
    return {
        p["partner_class"]: p["trigger"] for p in meta["pairs"] if p["trigger"]["rule"] == "throw"
    }


# -------------------------------------------------------------------- throws
def test_a_throw_pair_names_ragdoll_contact_as_its_damage_source(meta):
    """T1: no event of a throw deals damage and m_ndefaultdamagethrow has no
    reader; the old block said "not established"."""
    t = _throws(meta)
    assert set(t) == {"Enemy04", "EnemyBig"}
    for trig in t.values():
        d = trig["damage"]
        assert d["source"] == "ragdoll_contact" and d["throw_damage_property_used"] is False
        assert d["event"] is None and d["amount"] is None and "note" not in d
        assert d["rule"] == "combat.rules.ragdoll_damage"
        assert d["fall_kill"] == {"body_below_thrower_visual_m": 3.0, "damage": 100000.0}
        assert d["bystanders"]["direct_damage"] == 0.0 and d["bystanders"]["stun_s"] == 3.0
        assert d["bystanders"]["poses"] == [
            "LIGHT_MIDDLE_STRAIGHT",
            "LIGHT_UPPER_STRAIGHT",
            "HEAVY_MIDDLE_STRAIGHT",
            "HEAVY_UPPER_STRAIGHT",
        ]
    assert meta["combat"]["totals"]["pair_rules"]["throw"] == 2


def test_release_speed_follows_the_size_of_the_partner_class(meta):
    t = _throws(meta)
    assert t["Enemy04"]["damage"]["release_speed_m_s"] == 9.0
    assert t["EnemyBig"]["damage"]["release_speed_m_s"] == 5.0
    assert "not big" in t["Enemy04"]["damage"]["release_speed_basis"]
    assert meta["combat"]["classes"]["EnemyBig"]["big"] is True


def test_the_other_pair_rules_keep_their_damage_block(meta, plain):
    def others(m):
        return [p["trigger"] for p in m["pairs"] if p["trigger"]["rule"] != "throw"]

    assert others(meta) == others(plain) and len(others(meta)) == 2


def test_the_trigger_copy_in_a_clip_carries_the_new_block(meta):
    x = am.clip_extras(meta, "RSH_COM_ATT_throw_A", fps=30.0, frames=61)
    sources = {p["trigger"]["damage"]["source"] for p in x["pairs"]}
    assert sources == {"ragdoll_contact"}


def test_throw_damage_stays_as_data_and_is_marked_unused(meta):
    db = meta["combat"]["combo_databases"]["Enemy Combos"]
    assert db["throw_damage"] == 10.0 and db["throw_damage_used"] is False
    assert db["counter_damage"] == 10.0  # untouched neighbour


# ------------------------------------------------------------ ragdoll damage
def test_ragdoll_damage_rule_and_the_visual_def_numbers(meta):
    r = meta["combat"]["rules"]["ragdoll_damage"]
    assert "0x69d00a" in r["handler"] and "0x6914f2" in r["handler"]
    assert r["per_contact"] == "mass(body) * min(|(0.2Fx, Fy, 0.2Fz)|, 4000) * 0.00007"
    assert r["per_contact_cap_factor"] == 0.28 and r["player_victim_factor"] == 0.3
    assert len(r["gates"]) == 4 and "placeholder" in r["gates"][3]
    vd = r["visual_def"]
    assert vd["m_nragdollimpactforcethresholdforsound"] == 300.0
    assert [vd[k] for k in cm.VISUAL_DEF_READ] == [300.0, 0.6, 2500.0, 6000.0, 2000.0]
    assert vd["unread_in_script"] == [
        "m_nragdollimpactignoretrigger",
        "m_nragdollimpactforcefromcollider",
    ]
    assert vd["fragment"].endswith("CharacterVisual.fragment")
    assert r["bystanders"]["direct_damage"] == 0.0 and r["fall_kill"]["damage"] == 100000.0


def test_an_extract_without_a_visual_def_has_null_numbers(plain):
    vd = plain["combat"]["rules"]["ragdoll_damage"]["visual_def"]
    assert all(vd[k] is None for k in cm.VISUAL_DEF_READ) and vd["fragment"] is None
    assert cm.rules()["ragdoll_damage"]["visual_def"]["fragment"] is None


def test_contact_damage_cap_is_mass_times_the_force_cap():
    assert cm.RAGDOLL_CAP_FACTOR == pytest.approx(4000.0 * 0.00007) == pytest.approx(0.28)
    # a 9.961 kg thigh, a 100 kg untuned body
    assert cm.contact_damage_cap(9.961) == pytest.approx(2.789, abs=5e-4)
    assert cm.contact_damage_cap(100.0) == 28.0


# ------------------------------------------------------------------ the hit
def test_damage_formula_and_the_receiving_side():
    d = cm.rules()["damage"]
    assert "[0.2 if the target's electric armour fired" in d["formula"]
    assert "max(1/uber, 0.7)" in d["formula"]
    assert "InitializeNextAttack 0x68bf6f" in d["inputs"]["base"]
    assert "per press" not in d["inputs"]["base"]
    assert "not present in the extracted fragments" in d["inputs"]["global"]
    assert "0x71ea63" in d["inputs"]["electric_armour"]
    steps = [s["step"] for s in d["receive"]]
    assert steps == [
        "reverse_direction_window",
        "underboss_victim_from_ai_factor",
        "slave_filter",
        "incoming",
        "uber_vs_playable_factor",
        "invulnerable",
        "floors",
    ]
    by = {s["step"]: s for s in d["receive"]}
    assert by["underboss_victim_from_ai_factor"]["value"] == 0.2
    assert by["uber_vs_playable_factor"]["value"] == "max(1/uber, 0.7)"
    assert by["floors"]["floors"]["ai_partner"] == 1.0
    assert set(by["floors"]["floors"]) == {"underboss", "ai_partner", "min_health"}
    assert all("0x691b10" in s["handler"] or "0x695632" in s["handler"] for s in d["receive"])
    assert "201" in d["death"]["ordinary"] and len(d["death"]["versus_outcomes"]) == 2


def test_size_rule_names_the_main_target_and_the_height_maps_are_unchanged():
    p = cm.rules()["damage_pose"]
    assert p["size"]["when"].startswith("the attacker's main attack target is big")
    # ConvertLowToHighDam 0x7f08e7, with its two odd rows (27 -> 28, 22 -> 25)
    assert cm.POSE_LOW_TO_HIGH == {5: 2, 24: 23, 11: 8, 26: 25, 17: 14, 27: 28, 20: 19, 22: 25}
    low = p["height"]["dy < -0.1 and hit_y - dy > 0.4"]
    assert low["KNOCKDOWN_UPPER_BACK"] == "KNOCKDOWN_MIDDLE_BACK"
    assert low["STUN_MIDDLE_BACK"] == "HEAVY_UPPER_BACK" and len(low) == 8


def test_pair_damage_gains_exactly_the_three_area_attacks():
    pd = cm.rules()["pair_damage"]
    assert set(pd) == {
        "evidence",
        "handler",
        "IMPACT in a non-attack state",
        "KILL_ANIMATION_PARTNER",
        "DIE",
        "BULLMOVE_IMPACT",
        "FLASH_GRENADE",
        "DISCHARGE_ARMOR",
        "ELECTRIFY_ARMOR",
        "ELECTRIFY_ARMOR_range_m",
        "IMPACT_EFFECTS with m_ttruth1",
    }
    assert "radius 3.0" in pd["FLASH_GRENADE"] and "(11.0 - distance)" in pd["FLASH_GRENADE"]
    assert "attacker health + 10.0" in pd["DISCHARGE_ARMOR"]
    assert "KNOCKDOWN_UPPER_STRAIGHT" in pd["DISCHARGE_ARMOR"]
    assert "0x72769f" in pd["ELECTRIFY_ARMOR"] and "not established" not in pd["ELECTRIFY_ARMOR"]
    assert "(10.0 - d) / 10.0" in pd["ELECTRIFY_ARMOR"] and pd["ELECTRIFY_ARMOR_range_m"] == 10.0
    impact = pd["IMPACT in a non-attack state"]
    assert "now + 1.0" in impact and "rage flag cleared in uber rage" in impact
    assert pd["KILL_ANIMATION_PARTNER"] == "100000 damage to the partner"


def test_new_constants_carry_their_addresses():
    cs = cm.rules()["constants"]
    by = {c["address"]: c for c in cs}
    assert len(by) == len(cs)  # one row per address
    for addr, value, typ in (
        ("0xa5ee58", 4000.0, "f32"),
        ("0xa5ee50", 0.00007, "f64"),
        ("0x9e663c", 2.0, "f32"),
        ("0x9e8670", 3.0, "f64"),
        ("0x9e650c", 0.3, "f32"),
        ("0xc3cc18", 0.0, "f64"),
        ("0x9e6910", 3.0, "f32"),
        ("0xa45bec", 9.0, "f32"),
        ("0x9e60d4", 0.7, "f32"),
        ("0xa5e9b0", 11.0, "f64"),
        ("0x9e5c60", 10.0, "f64"),
        ("0x9ebc04", 0.05, "f32"),
        ("0x9ea130", 0.8, "f64"),
        ("0xa69770", 0.22, "f64"),
    ):
        assert (by[addr]["value"], by[addr]["type"]) == (value, typ), addr
    assert "0xa5ee60" in by["0xa5ee58"]["meaning"]
    assert "ragdoll contact force" in by["0x9e97e8"]["meaning"]
    assert by["0x9e97fc"]["value"] == 5.0 and "thrown big victim" in by["0x9e97fc"]["meaning"]


# -------------------------------------------------------- the settled rules
def test_sweep_attack_permission_and_twilight_rules():
    r = cm.rules()
    assert r["sweep"]["step_playpos"] == 0.05 and r["sweep"]["hit_distance_m"] == 0.8
    assert "m_nchecksprsec is not read" in r["sweep"]["stepping"]
    g = r["attack_permission"]["orchestrator_grant"]
    assert "0x6e8231" in g["handler"] and "command_break_off_attack" in g["immune_target"]
    ev = r["attack_permission"]["enemy_evaluate"]
    assert any(row.startswith("PASSIVE") and "IDLING" in row for row in ev["order"])
    assert len(ev["passive_becomes_aggressive"]) == 5
    t = r["twilight_lady_reaction"]
    assert "0x7220c7" in t["handler"] and t["defaults"]["hits_before_dodge"] == 3
    assert t["defaults"]["dodges_before_counter"] == 1 and t["forced_attack_move_dist_m"] == 1.5


def test_not_established_drops_what_is_settled(meta):
    text = " | ".join(meta["combat"]["not_established"])
    assert meta["combat"]["not_established"] == cm.NOT_ESTABLISHED
    for stale in (
        "throw",
        "stepping loop",
        "who may attack when",
        "own reaction routine",
        "none found in the damage path",
    ):
        assert stale not in text.replace("flamethrower", ""), stale
    assert text.startswith("ragdoll contact force magnitudes and contact counts")
    assert "ElectricArmor.AreaDamage" not in text and "g_nglobaldamagefactor" in text
    assert "m_nelectrifyrange" not in text and "sweep check point" not in text


# ------------------------------------------------------- effective modifier
def test_ai_defs_carry_the_effective_damage_modifier_with_its_source(meta):
    """C5: a stored 0 means "use the CharacterDef's" (0x71f0cf), never a zero
    multiplier."""
    by = {a["name"]: a for a in meta["combat"]["ai_defs"]}
    base, phase = by["base_def"], by["phase_1"]
    assert base["damage_modifier_own"] == 0.0 and base["damage_modifier_effective"] == 1.5
    assert base["damage_modifier_source"] == "CharacterDef._ndamagemodifier (own value is 0)"
    assert phase["damage_modifier_effective"] == 2.0
    assert phase["damage_modifier_source"] == "own (_ndamagemodifier)"
    assert all(a["damage_modifier_effective"] for a in meta["combat"]["ai_defs"])


def test_per_state_damage_numbers_do_not_change(meta, plain):
    s = test_combat_meta._state(meta, "Enemy04", "Light_A")["combat"]
    assert s == test_combat_meta._state(plain, "Enemy04", "Light_A")["combat"]
    assert [(v["modifier"], v["damage"]) for v in s["damage"][0]["variants"]] == [
        (1.5, 7.5),
        (2.0, 10.0),
    ]


# ------------------------------------------------------------------- marker
def test_format_markers_stay_and_the_table_carries_its_revision(meta):
    assert cm.COMBAT_FORMAT == "watchmen-combat-meta/1" == meta["combat_format"]
    assert meta["combat"]["format"] == cm.COMBAT_FORMAT and meta["format"] == am.FORMAT
    assert meta["revision"] == am.REVISION


# ------------------------------------------------------------- events table
def test_event_rows_29_to_31_state_the_damage_as_read():
    sem = ee.event_semantics()
    assert len(sem) == 93
    flash, electrify, discharge = sem["29"], sem["30"], sem["31"]
    for row in (flash, electrify, discharge):
        assert row["evidence"] == "read from code"
    assert "Same block as FLASH_GRENADE" not in electrify["effect"]
    assert "ElectricArmor.AreaDamage 0x72769f" in electrify["effect"]
    assert "m_narmorcost" in electrify["effect"] and electrify["handler"] == "0x6a62d8"
    assert "(11.0 - distance)" in flash["effect"] and "radius 3.0" in flash["effect"]
    assert "attacker health + 10.0" in discharge["effect"] and discharge["affects_partner"] is True
    assert (flash["name"], electrify["name"], discharge["name"]) == (
        "FLASH_GRENADE",
        "ELECTRIFY_ARMOR",
        "DISCHARGE_ARMOR",
    )
