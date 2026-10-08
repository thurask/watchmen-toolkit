#!/usr/bin/env python3
"""combat_meta -- the combat rules of the game as data, joined to anim_meta.

Adds, to the table anim_meta.build() writes (all additive, `combat_format`):

  classes.*.states[*].group_criteria   the criteria the state inherits from its
                                       state groups, outermost first, with the
                                       group's random-pick flag; texts are
                                       rendered from the STORED values (several
                                       node captions are stale)
  classes.*.states[*].criteria_rendered  the state's own criteria, same rendering
  classes.*.states[*].combat           per attack state: attack class, weapon
                                       class, entry kind, required combo
                                       override, damage with its formula inputs,
                                       timings, reach, flags, sweep, damage pose,
                                       what the defender can do.  Other combat
                                       states (counter / finisher / throw
                                       masters, dodges, blocks, hit reactions)
                                       get a short block.
  pairs[*].trigger                     the game condition that starts the pair,
                                       where its damage comes from (a throw's
                                       comes from ragdoll contacts, not from an
                                       event), the breakout window, the finisher
                                       prompt numbers
  combat                               rules (constants with their exe address;
                                       hit damage and its receiving side,
                                       ragdoll contact damage, the area attacks,
                                       sweep stepping, who may attack when),
                                       combo databases, CharacterDefs, AI
                                       definitions with their reaction rows and
                                       effective damage modifier, weapons,
                                       per-class links and totals

Evidence (docs/re/wp3_combat.md and the later damage / AI reads): every rule
cites the script handler it was read from; numbers under `rules.constants`
were read from the executable's bytes; everything else is read from the
shipped fragments.  Fields that are derived by this module carry "derived";
what is inferred says so; what is not established is left out and listed under
`combat.not_established`.

CLI:  python3 combat_meta.py ANIM_META.json      (summary of an existing table)
"""

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

import anim_state_machine as asm  # noqa: E402
import engine_enums as ee  # noqa: E402

# (the marker does not count content changes: a cached table that lacks newer
# content is told apart by anim_meta.REVISION)
COMBAT_FORMAT = "watchmen-combat-meta/1"

# --------------------------------------------------------------- ids and names
# CONTROL_ACTION_TYPES ids the attack groups test (exe enum family)
ACT_PUNCH, ACT_NORMAL_ATTACK, ACT_FINISH, ACT_THROW = 0, 1, 3, 4
ACT_BULLMOVE, ACT_HEAVY_PUNCH, ACT_COUNTER = 6, 7, 12
ACT_INITIAL, ACT_AFTER_DASH, ACT_KILL_PRONE = 21, 25, 29
# ANIMATION_ENUM variables
VAR_WEAPON, VAR_TARGET_MODE, VAR_OVERRIDE = 5, 7, 8
VAR_DAMAGE_POSE, VAR_OPPONENT_MODEL, VAR_SPECIFIC_MODEL = 4, 11, 14
# ANIMATION_VALUE variables
VAL_ATTACK_MOVE_DIST = 4
# ANIMATION_EVENT ids
EV_IMPACT, EV_BRANCH, EV_CAN_MOVE, EV_PRE_IMPACT = 4, 5, 13, 16
EV_KILL_PARTNER, EV_CLEAR_DEADZONE, EV_ALLOW_ATTACKS = 20, 23, 24
EV_BULLMOVE_IMPACT, EV_DIE, EV_BREAKOUT, EV_BREAKOUT_END = 33, 85, 87, 88
# ANIMATION_TYPE ids
AT_LIGHT, AT_HEAVY, AT_BLOCK, AT_DODGE, AT_COUNTER, AT_FINISH = 4, 5, 6, 7, 8, 9
AT_THROW, AT_DAMAGE, AT_STUNNED, AT_BULLMOVE, AT_ANY = 10, 11, 12, 13, 17
# ANIMATION_SPECIAL_CASE ids
SP_RESEND_PUNCH, SP_BULL_MOVE, SP_IMMUNE_TO_BREAK = 4, 6, 13
EV_IMPACT_EFFECTS = 56

# Enum 7 TARGET_MODE has no registered value family.  The values are the ones
# CharacterVisual.command_update_animation 0x69b988 writes every frame from the
# character's next attack target (script code, not an exe enum table).
TARGET_MODE = {
    -1: "NO_TARGET",
    0: "TARGET_NOT_IN_COMBAT",
    1: "TARGET_IN_COMBAT",
    2: "TARGET_DEAD",
    3: "TARGET_STUNNED_OR_ON_KNEE",
    4: "TARGET_PRONE",
}
# Exe enum families that engine_enums.json does not carry (ids from the
# registration calls, findings/enums.md): kept local so the shared table and the
# `enums` block of anim_meta stay as they are.
CHARACTER_COMBO_ITEMS = {  # registered in 0x6726d6
    0: "NONE",
    1: "FAST_ATTACK_UNARMED",
    2: "FAST_ATTACK_1H_WEAPON",
    3: "FAST_ATTACK_2H_WEAPON",
    4: "HEAVY_ATTACK_UNARMED",
    5: "HEAVY_ATTACK_1H_WEAPON",
    6: "HEAVY_ATTACK_2H_WEAPON",
    7: "BULL_RUSH",
    8: "STEP_AROUND",
    9: "GRENADE",
    10: "ELECTRIFY",
    11: "DODGE",
    12: "BLOCK",
    13: "COUNTER_ATTACK",
    14: "THROW",
    15: "FINISHING_MOVE",
    16: "KICK",
}
CHARACTER_COMBO_ENEMY_STATUS = {  # registered in 0x6726d6; a bit mask, -1 = any
    -1: "ANY",
    0: "NONE",
    1: "STUNNED",
    2: "PRONE",
    4: "ATTACKING",
    8: "KNEE",
    16: "DEFAULT",
}
AI_DEF_TYPE = {  # registered in 0x5a38a6
    0: "BASE_DEF",
    1: "LEADER_DEF",
    2: "PHASE_1",
    3: "PHASE_2",
    4: "PHASE_3",
    5: "PHASE_4",
    6: "PHASE_5",
    7: "PHASE_6",
}
# partner AI families (values and registration sites: docs/re/enums.md)
PARTNER_AI_STATE = {  # registered in 0x5a38a6
    0: "INVALID",
    1: "IDELING",
    2: "FOLLOW_PIVOT",
    3: "FOLLOW_PARTNER",
    4: "COMBAT",
    5: "USE",
    6: "UBER_RAGE",
    7: "FOLLOW_WAYPOINT",
    8: "STEP_BACK",
}
PARTNER_MODIFIED_STATE = {0: "NONE", 1: "LOW_HEALTH", 2: "MEGA_KILL"}  # registered in 0x7e873b
PLAYER_AI_STATES = {  # registered in 0x5a38a6
    0: "INVALID",
    1: "INACTIVE",
    2: "FOLLOW_PIVOT",
    3: "USE",
    4: "DO_COMBAT",
    5: "WAYPOINT_FOLLOW",
    6: "IDELING",
    7: "STEP_BACK",
}
REPEAT_DEFENCE = {  # registered in 0x6fffd7
    0: "INVALID",
    1: "BLOCK",
    2: "DODGE",
    3: "COUNTER_ATTACK",
    4: "FAST_ATTACK",
    5: "SLOW_ATTACK",
}
STOP_CRITERIA = {  # registered in 0x5a38a6; a bit mask
    0: "NONE",
    1: "LEADER_PRESENT",
    2: "TIMER",
    4: "ENEMY_IN_MELEE_RANGE",
    8: "STATE_NOT_RUNNING",
}
TACTICAL_INFO = {  # registered in 0x5a38a6; a bit mask
    0: "INVALID",
    1: "IS_ATTACKING_ME",
    2: "WITHIN_MELEE_RANGE",
    4: "OUTSIDE_MELEE_RANGE",
    8: "WITHIN_ATTACK_RANGE",
    16: "IS_STUNNED",
    32: "IS_NOT_STUNNED",
    64: "IS_PRONE",
    128: "IS_NOT_PRONE",
    256: "IS_NOT_STUNNED_OR_PRONE",
    512: "PLACEMENT_FRONT",
    1024: "PLACEMENT_REAR",
    2048: "PLACEMENT_LEFT",
    4096: "PLACEMENT_RIGHT",
    8192: "CURRENT_TARGET",
    16384: "NOT_CURRENT_TARGET",
    32768: "LOW_HEALTH",
    65536: "IS_PRIMARY_TARGET",
}
_PARTNER_ENUMS = (
    ("PARTNER_AI_STATE", PARTNER_AI_STATE, "exe enum family, registered in 0x5a38a6"),
    ("PARTNER_MODIFIED_STATE", PARTNER_MODIFIED_STATE, "exe enum family, registered in 0x7e873b"),
    ("PLAYER_AI_STATES", PLAYER_AI_STATES, "exe enum family, registered in 0x5a38a6"),
    ("REPEAT_DEFENCE", REPEAT_DEFENCE, "exe enum family, registered in 0x6fffd7"),
    ("STOP_CRITERIA", STOP_CRITERIA, "exe enum family, registered in 0x5a38a6 (bit mask)"),
    ("TACTICAL_INFO", TACTICAL_INFO, "exe enum family, registered in 0x5a38a6 (bit mask)"),
)
LOGICAL_INPUT_BUTTONS = {  # the combat buttons of the exe family
    21: "PLAYER_ATTACK_0",
    22: "PLAYER_ATTACK_1",
    23: "PLAYER_ATTACK_2",
    24: "PLAYER_USE",
    25: "PLAYER_SPECIAL_ATTACK_1",
    26: "PLAYER_COUNTER_ATTACK",
    27: "PLAYER_SPECIAL_ATTACK_2",
    28: "PLAYER_DEFEND",
}
# combo item -> (button, weapon class); CharacterRootLogic.AddAttackToCombo 0x68bca8
_ITEM_ATTACK = {
    1: ("light", "UNARMED"),
    2: ("light", "BASH_1H"),
    3: ("light", "BASH_2H"),
    4: ("heavy", "UNARMED"),
    5: ("heavy", "BASH_1H"),
    6: ("heavy", "BASH_2H"),
}
# combo database property holding the base damage of (button, weapon class);
# "heavvunarmed" is the shipped spelling
BASE_DAMAGE_PROP = {
    ("light", "UNARMED"): "m_ndefaultdamagefastunarmed",
    ("light", "BASH_1H"): "m_ndefaultdamagefast1hweapon",
    ("light", "BASH_2H"): "m_ndefaultdamagefast2hweapon",
    ("heavy", "UNARMED"): "m_ndefaultdamageheavvunarmed",
    ("heavy", "BASH_1H"): "m_ndefaultdamageheavy1hweapon",
    ("heavy", "BASH_2H"): "m_ndefaultdamageheavy2hweapon",
}
_WEAPON_CLASSES = ("UNARMED", "BASH_1H", "BASH_2H")

# AnimationStateWM truth properties that the combat script reads
STATE_FLAGS = (
    ("disallow_attack", "m_tdisallowattack"),
    ("immune_to_attacks", "m_timmunetoattacks"),
    ("keep_combo_alive", "m_tkeepcomboalive"),
    ("stun_lock", "m_tstunlockstate"),
    ("sweep", "m_tallowsweepatt"),
    ("ignore_weapon_sound", "m_tignoreweaponsound"),
    ("get_away_from_me", "m_tgetawayfromme"),
    ("immune_to_combo_speedup", "m_timmunetocombospeedup"),
    ("ignore_target_lock", "m_tignoretargetlock"),
)
SWEEP_PROPS = (
    "m_nwithinspeed",
    "m_nbeginsweepangle",
    "m_nbeginsweeplength",
    "m_nbeginsweepplaypos",
    "m_nimpactsweepangle",
    "m_nimpactsweeplength",
    "m_nimpactsweepplaypos",
    "m_nendsweepangle",
    "m_nendsweeplength",
    "m_nendsweepplaypos",
)

# ------------------------------------------------------------------ constants
# value, exe address the bytes were read from, width, meaning
ELECTRIFY_RANGE_M = 10.0  # ElectricArmor.AreaDamage 0x72769f: range and sphere radius
COUNTER_MARGIN_S = 0.13
WHIFF_M, WHIFF_BIG_M = 1.8, 2.2
SPEEDUP_LIGHT_S, SPEEDUP_HEAVY_S = 0.15, 0.2
PAIR_BASE_DAMAGE, PAIR_PLAYABLE_FACTOR, KILL_DAMAGE = 20.0, 0.75, 100000.0
BULL_PLAYABLE_FACTOR = 0.4
# ragdoll contact damage (CharacterVisual.ModelCollisionContactAdded 0x69d00a)
RAGDOLL_FORCE_CAP, RAGDOLL_DAMAGE_PER_FORCE, RAGDOLL_HORIZONTAL_FACTOR = 4000.0, 0.00007, 0.2
RAGDOLL_CAP_FACTOR = round(RAGDOLL_FORCE_CAP * RAGDOLL_DAMAGE_PER_FORCE, 6)  # 0.28 per kg
RAGDOLL_MIN_SPEED, RAGDOLL_FALL_KILL_M, RAGDOLL_PLAYER_FACTOR = 2.0, 3.0, 0.3
THROW_SPEED, THROW_SPEED_BIG = 9.0, 5.0
BYSTANDER_DAMAGE_FACTOR, BYSTANDER_STUN_S = 0.0, 3.0
BYSTANDER_POSES = (5, 2, 11, 8)  # rand_number quartiles, DetermineDamageReaction 0x6a18d1
ELECTRIC_ARMOUR_FACTOR, UNDERBOSS_FROM_AI_FACTOR, UBER_VS_PLAYABLE_MIN = 0.2, 0.2, 0.7
SWEEP_STEP_PLAYPOS, SWEEP_HIT_M = 0.05, 0.8
# CharacterVisualDef members ModelCollisionContactAdded reads / stores without a reader
VISUAL_DEF_READ = (
    "m_nragdollimpactforcethresholdforsound",
    "m_nragdollimpactheightmask",
    "m_nragdollimpactdecreasepersecond",
    "m_nragdollimpactragdolltrigger",
    "m_nragdollimpactanimationtrigger",
)
VISUAL_DEF_UNREAD = ("m_nragdollimpactignoretrigger", "m_nragdollimpactforcefromcollider")

CONSTANTS = [
    (COUNTER_MARGIN_S, "0xa5ecc8", "f32", "counter: least time left before the IMPACT event"),
    (0.26, "0xa5ecc4", "f32", "counter margin for argument 0; both callers pass 1 (unused)"),
    (0.03, "0x9e60e0", "f32", "counter: least time since the previous IMPACT, player"),
    (-0.03, "0xa5eccc", "f32", "counter: least time since the previous IMPACT, AI"),
    (WHIFF_M, "0x9e5fa0", "f32", "AI attacker loses its target beyond this at PRE_IMPACT"),
    (WHIFF_BIG_M, "0xa46b90", "f32", "the same for a big attacker (model type 4 or 5)"),
    (SPEEDUP_LIGHT_S, "0x9eb188", "f64", "combo speed-up lead, LIGHTATTACK; least combo validity"),
    (
        SPEEDUP_HEAVY_S,
        "0x9e97e8",
        "f64",
        "combo speed-up lead, HEAVYATTACK; factor on the base term of a hit on electric armour;"
        " clear-attack delay after BRANCH; factor on the x and z of a ragdoll contact force",
    ),
    (0.3, "0xa00178", "f64", "interrupt attack: at most this long after the last attack"),
    (
        ELECTRIFY_RANGE_M,
        "0x9eb1d8",
        "f32",
        "ElectricArmor.AreaDamage: range of the interpolation and radius of the sphere query",
    ),
    (
        1.0,
        "0xc3cc48",
        "f64",
        "attack dead zone after an issued attack; player stun cap; combo validity after a paired"
        " IMPACT",
    ),
    (2.0, "0xc3cc78", "f64", "an attack is buffered when the dead zone is older than this"),
    (
        0.7,
        "0xa3aff8",
        "f64",
        "combo validity after a landed hit; step-around cooldown; finisher prompt grace;"
        " threshold of the uber-rage clamp on a playable victim",
    ),
    (
        UBER_VS_PLAYABLE_MIN,
        "0x9e60d4",
        "f32",
        "least factor (1 / uber, clamped) on uber-rage damage to a playable victim",
    ),
    (
        0.4,
        "0x9eb790",
        "f64",
        "slow motion length (real time); rush re-issue delay; bull rush factor on a playable"
        " victim; DISCHARGE_ARMOR share of a playable victim's maximum health",
    ),
    (PAIR_BASE_DAMAGE, "0x9e66ac", "f32", "paired-move damage without a combo database"),
    (PAIR_PLAYABLE_FACTOR, "0x9e70e8", "f64", "paired-move damage factor on a playable victim"),
    (
        KILL_DAMAGE,
        "0x9eba80",
        "f32",
        "damage of KILL_ANIMATION_PARTNER / DIE; of a ragdoll contact more than 3 m below the"
        " thrower",
    ),
    (
        THROW_SPEED_BIG,
        "0x9e97fc",
        "f32",
        "attack damage without a combo database; release speed of a thrown big victim (m/s)",
    ),
    (-0.2, "0xa40310", "f64", "attacker's local z below which the hit counts as from behind"),
    (0.15, "0xa11984", "f32", "delay of the AI counter after a COUNTERATTACK reaction"),
    (1.5, "0x9e8320", "f64", "lifetime of an entry of the dodge list"),
    (-0.35, "0xa5ec78", "f32", "a throw fails when the target's RELATIVE_HEAD_HEIGHT is below"),
    (-0.18, "0xa5e7b0", "f32", "head bone height below which a finisher becomes a stomp"),
    (2.5, "0x9e72b8", "f32", "stun cap on a player in versus / on an AI partner"),
    (1.4, "0xa5ed34", "f32", "base maximum of rage / electricity (+0.1 per upgrade)"),
    (2.1, "0xa5ed38", "f32", "camera recoil of a knock-down pose"),
    # ragdoll contact damage and the throw (0x69d00a, 0x6914f2, 0x6a18d1, 0x5b16ed)
    (
        RAGDOLL_FORCE_CAP,
        "0xa5ee58",
        "f32",
        "ragdoll contact: cap of the scaled contact force (compared as f64 0xa5ee60)",
    ),
    (RAGDOLL_DAMAGE_PER_FORCE, "0xa5ee50", "f64", "ragdoll contact: damage per mass x force"),
    (RAGDOLL_MIN_SPEED, "0x9e663c", "f32", "ragdoll contact: least mean ragdoll speed (m/s)"),
    (
        RAGDOLL_FALL_KILL_M,
        "0x9e8670",
        "f64",
        "ragdoll contact: a body this far below its animation partner's visual takes 100000",
    ),
    (
        RAGDOLL_PLAYER_FACTOR,
        "0x9e650c",
        "f32",
        "ragdoll damage factor on a player-controlled victim",
    ),
    (
        BYSTANDER_DAMAGE_FACTOR,
        "0xc3cc18",
        "f64",
        "damage factor of the hit a standing character takes from a ragdoll (always 0)",
    ),
    (
        BYSTANDER_STUN_S,
        "0x9e6910",
        "f32",
        "stun of a standing character hit by a ragdoll; FLASH_GRENADE radius (m) and stun (s)",
    ),
    (
        THROW_SPEED,
        "0xa45bec",
        "f32",
        "release speed of a thrown victim (m/s); 5.0 when the victim is big",
    ),
    (20.0, "0x9e5c68", "f64", "decay per second of CharacterVisual._naddeddamage (never read)"),
    # area attacks (event cases 29 / 31 of 0x6a525e)
    (11.0, "0xa5e9b0", "f64", "FLASH_GRENADE: damage base minus distance, playable target"),
    (10.0, "0x9e5c60", "f64", "DISCHARGE_ARMOR: added to the attacker's health as damage base"),
    # sweep (CharacterVisual.command_begin_sweep_attack 0x698a43, 0x69a57d)
    (SWEEP_STEP_PLAYPOS, "0x9ebc04", "f32", "sweep: play position between two checks"),
    (
        SWEEP_HIT_M,
        "0x9ea130",
        "f64",
        "sweep: hit when the target is nearer than this to the travelled segment; end of the"
        " reverse-direction window of give_damage",
    ),
    # Twilight Lady's reaction routine (Enemy.command_react_to_attack_twilight_lady 0x7220c7)
    (0.22, "0xa69770", "f64", "Twilight Lady: dodge probability on an early attack"),
    (5.0, "0x9e70a0", "f64", "Twilight Lady: an attacker record is dropped after this (s)"),
    (
        0.25,
        "0x9e6914",
        "f32",
        "Twilight Lady: probability of reacting to a human's unblockable attack",
    ),
    (1.5, "0x9e5ff0", "f32", "Twilight Lady: ATTACK_MOVE_DIST of her forced attacks"),
]


def _pose_map(*spans):
    out = {}
    for ids, to in spans:
        for i in ids:
            out[i] = to
    return out


# ProjectAnimationLib pose conversions (all read): pose id -> pose id
POSE_LIGHT_TO_HEAVY = _pose_map(((1, 2, 3), 8), ((4, 5, 6), 11), ((23,), 25), ((24,), 26))
POSE_TO_STUN = _pose_map(
    ((1, 2, 3, 7, 8, 9), 19), ((4, 5, 6, 10, 11, 12), 20), ((23, 25), 21), ((24, 26), 22)
)
POSE_HIGH_TO_LOW = _pose_map(
    ((1, 2, 3), 5),
    ((23,), 24),
    ((7, 8, 9), 11),
    ((25,), 26),
    ((13, 14, 15), 17),
    ((27,), 28),
    ((19,), 20),
)
POSE_LOW_TO_HIGH = {5: 2, 24: 23, 11: 8, 26: 25, 22: 25, 17: 14, 27: 28, 20: 19}
POSE_TO_BACK = _pose_map(
    ((1, 2, 3), 23),
    ((4, 5, 6), 24),
    ((7, 8, 9), 25),
    ((10, 11, 12), 26),
    ((13, 14, 15), 27),
    ((16, 17, 18), 28),
    ((19,), 21),
    ((20,), 22),
)
POSE_UPPER = (1, 2, 3, 7, 8, 9, 13, 14, 15, 19, 20, 21, 23, 25, 27)  # IsUpperDamagePose
_POSE_CLASS = (
    ("light", (1, 2, 3, 4, 5, 6, 23, 24)),
    ("heavy", (7, 8, 9, 10, 11, 12, 25, 26)),
    ("knockdown", (13, 14, 15, 16, 17, 18, 27, 28)),
    ("stun", (19, 20, 21, 22)),
)


def pose_name(i):
    return ee.name("DAMAGE_POSE", i, "DAMAGE_POSE_%s" % i)


def pose_class(i):
    """light / heavy / knockdown / stun: the classes CharacterRoot.do_recoil
    0x6902c0 and give_damage 0x691b10 test."""
    for nm, ids in _POSE_CLASS:
        if i in ids:
            return nm
    return None


def convert_pose(
    pose, override=None, from_behind=False, big_target=False, upper=True, dy=0.0, hit_y=0.0
):
    """The pose a hit delivers (CharacterRootLogic.SetCloseCombatDamageToTarget
    0x6ae57f): combo, direction, size, height -- in that order.

    override     OVERRIDE_ATTACK_COMBO name of the completed combo string
    from_behind  attacker's z in the target's frame < -0.2 m
    big_target   target is big (model type 4 / 5); upper: CharacterRootLogic
                 .m_tisupper of the attack
    dy           target height - attacker height; hit_y: state m_vimpactpos.y"""
    if override == "HEAVY_DAM":
        pose = POSE_LIGHT_TO_HEAVY.get(pose, pose)
    elif override == "STUN":
        pose = POSE_TO_STUN.get(pose, pose)
    if from_behind:
        pose = POSE_TO_BACK.get(pose, pose)
    if big_target and not upper:
        pose = POSE_HIGH_TO_LOW.get(pose, pose)
    if dy > 0.1 and hit_y - dy < 0.4:
        pose = POSE_HIGH_TO_LOW.get(pose, pose)
    elif dy < -0.1 and hit_y - dy > 0.4:
        pose = POSE_LOW_TO_HIGH.get(pose, pose)
    return pose


def _named_map(m):
    return {pose_name(k): pose_name(v) for k, v in sorted(m.items())}


def contact_damage_cap(mass_kg):
    """The most one ragdoll contact of a body of this mass can add to the
    damage accumulator: mass * min(|F'|, 4000) * 0.00007 at the force cap
    (CharacterVisual.ModelCollisionContactAdded 0x69d00a).  The run-time mass is
    the ragdoll file's mass (no game-time SetMass touches a ragdoll body), so
    the `mass` of a ragdoll sidecar body can be passed as is.  The 3 m fall rule
    (100000) is outside this cap."""
    return round(float(mass_kg) * RAGDOLL_CAP_FACTOR, 6)


def _ragdoll_damage(visual_def):
    vd = visual_def or {}
    return {
        "evidence": "read from code (PC disassembly 0x69d37c-0x69d4e8; the PS3 twin 0x796ca0"
        " shows the same arithmetic); visual_def: data",
        "handler": "CharacterVisual.ModelCollisionContactAdded 0x69d00a ->"
        " CharacterVisual.StateRagdollDriven 0x69ed7c ->"
        " CharacterRoot.command_give_ragdoll_damage_increment 0x6914f2",
        "applies_to": "every ragdoll in the world (thrown bodies and knock-downs alike); a"
        " throw removes health only this way",
        "per_contact": "mass(body) * min(|(0.2Fx, Fy, 0.2Fz)|, 4000) * 0.00007",
        "per_contact_cap_factor": RAGDOLL_CAP_FACTOR,
        "per_contact_cap": "mass(body) * 0.28 (derived: the force cap 4000 * 0.00007); the"
        " run-time mass is the ragdoll file's mass (no game-time SetMass touches a ragdoll"
        " body), so per body it is the `mass` of the ragdoll sidecar * 0.28"
        " (combat_meta.contact_damage_cap)",
        "gates": [
            "|contact force| > CharacterVisualDef.m_nragdollimpactforcethresholdforsound",
            "mean ragdoll speed > 2.0 m/s",
            "the other body's owner is not the ragdoll itself",
            "the other body does not belong to a placeholder character"
            " (CharacterRoot.m_tisplaceholder, 0x69d18c)",
        ],
        "fall_kill": {
            "when": "the body is more than 3.0 m below the visual of its animation partner"
            " (the thrower)",
            "body_below_thrower_visual_m": RAGDOLL_FALL_KILL_M,
            "damage": KILL_DAMAGE,
        },
        "delivered": "once per frame when the accumulator exceeds 1.0 (then reset to 0)",
        "player_victim_factor": RAGDOLL_PLAYER_FACTOR,
        "inflictor": "the ragdoll's animation partner, may be none",
        "receive": "CharacterRoot.DecreaseHealth as for a hit (rules.damage.receive from"
        " `incoming` on); nothing for a placeholder victim",
        "bystanders": {
            "handler": "the same contact handler, branch of a character that is not a ragdoll;"
            " CharacterVisual.DetermineDamageReaction 0x6a18d1",
            "gates": [
                "the standing character is not playable",
                "it is not in a state with special handling BLOCK",
                "the collider is a character in physics state RAGDOLL",
                "the collider's ragdoll pelvis is above m_nragdollimpactheightmask",
            ],
            "force": "m_nragdollimpactforce decays by m_nragdollimpactdecreasepersecond * dt"
            " and gains |contact force|",
            "above m_nragdollimpactanimationtrigger": "when not stunned: a hit of"
            " modifier * 0.0 * global damage (always 0), stun 3.0 s, pose drawn at random",
            "above m_nragdollimpactragdolltrigger": "the bystander is ragdolled itself and"
            " then takes contact damage under this rule",
            "direct_damage": BYSTANDER_DAMAGE_FACTOR,
            "stun_s": BYSTANDER_STUN_S,
            "poses": [pose_name(i) for i in BYSTANDER_POSES],
            "poses_note": "one of the four by a random quartile, then the from-behind"
            " conversion (rules.damage_pose.direction)",
        },
        "visual_def": dict(
            {k: vd.get(k) for k in VISUAL_DEF_READ},
            evidence="data (CharacterVisualDef); null when the extract has no such node",
            fragment=vd.get("fragment"),
            unread_in_script=list(VISUAL_DEF_UNREAD),
        ),
        "unused": "CharacterVisual._naddeddamage is written with the same amount and decays by"
        " 20 per second but is never read (PC script code)",
    }


def _area_damage():
    """The three area / armour event cases (pair_damage entries)."""
    flash = (
        "event 29, case 0x6a62d8: pays special_def.m_ngrenadecost, then a sphere query of"
        " radius 3.0 m; per character found that is not of the attacker's faction and passes"
        " is_attack_successful: hit_soon + give_damage with damage (11.0 - distance) * modifier"
        " * global * uber for a playable target and 0 for any other, stun 3.0 s (an enemy"
        " takes no health loss, only the stun)"
    )
    discharge = (
        "event 31, case 0x6a8865: needs the attacker's electrified charge power > 0, an"
        " animation partner and is_attack_successful; damage = (attacker health + 10.0, or"
        " 0.4 * the victim's m_nmaxhealth when the victim is playable) * modifier * global"
        " * uber, stun special_def.m_nstunperchargeattack, pose %s; then a record of 0 damage"
        " with pose %s goes to the attacker itself; the charge power is set to 0"
        % (pose_name(14), pose_name(5))
    )
    electrify = (
        "event 30 itself deals no damage: it charges the armour, pays special_def.m_narmorcost"
        " and sends ElectricArmor.command_electric_armor_charge; on entering StateActive"
        " ElectricArmor.AreaDamage 0x72769f gives every character found, with"
        " t = max(0, (10.0 - d) / 10.0), d between the two m_echaractervisual positions, 10.0 a"
        " code constant (f32 0x9eb1d8; m_nelectrifyrange is not read here; its only reader,"
        " 0x6a71b6 in CharacterRootLogic.command_animation_event_received (event ELECTRIFY_ARMOR),"
        " stores it in a local that is not read afterwards, so the property — 4.0 in all six sets —"
        " has no effect): damage = uber"
        " * global * modifier * (t * m_nelectrifydamclose + (1 - t) * m_nelectrifydamfar),"
        " stun = t * m_nelectrifystunclose + (1 - t) * m_nelectrifystunfar, hit_soon then"
        " give_damage with a pose by distance and side: d > m_nelectryfypushbackrange -> LIGHT"
        " (front 5 / 2, behind 24 / 23); d > m_nelectryfyfallrange -> HEAVY (front 8 / 11,"
        " behind 26 / 25); else KNOCKDOWN (front 17 / 14, behind 28 / 27); the first id is drawn"
        " when rand < 0.5; behind = the attacker's position has z < 0 in the victim root's"
        " frame; victims: other faction only, a playable victim not while its state is DODGE,"
        " a non-playable one only within +/- 2.2 m of height; push 13.0 * t along the direction"
        " for 0.3 s"
    )
    return flash, discharge, electrify


def _receive():
    """What happens to a hit's damage on the victim, in code order."""
    return [
        {
            "step": "reverse_direction_window",
            "handler": "CharacterRoot.command_give_damage 0x691b10",
            "rule": "the pose becomes NO_POSE while the victim's reversed state is between play"
            " positions 0.5 and 0.8",
        },
        {
            "step": "underboss_victim_from_ai_factor",
            "handler": "CharacterRoot.command_give_damage 0x691b10",
            "rule": "damage * 0.2 when the victim is the Underboss and the inflictor is a"
            " character without a player controller (rage uses the reduced value)",
            "value": UNDERBOSS_FROM_AI_FACTOR,
        },
        {
            "step": "slave_filter",
            "handler": "CharacterRoot.command_give_damage 0x691b10",
            "rule": "a victim inside a paired move loses health only to its animation partner"
            " or to itself",
        },
        {
            "step": "incoming",
            "handler": "CharacterRoot.DecreaseHealth 0x695632",
            "rule": "damage * victim.m_nincomingdamagefactor",
        },
        {
            "step": "uber_vs_playable_factor",
            "handler": "CharacterRoot.DecreaseHealth 0x695632",
            "rule": "damage * max(1/uber, 0.7) when the inflictor's uber factor is > 1 and the"
            " victim is in the playable list",
            "value": "max(1/uber, 0.7)",
        },
        {
            "step": "invulnerable",
            "handler": "CharacterRoot.DecreaseHealth 0x695632",
            "rule": "no health loss when the victim is invulnerable or in damage state 1",
        },
        {
            "step": "floors",
            "handler": "CharacterRoot.DecreaseHealth 0x695632",
            "rule": "health is floored after the subtraction",
            "floors": {
                "underboss": "max(1, m_nhealthlowerbound * max health)",
                "ai_partner": 1.0,
                "min_health": "CharacterRoot.m_nminhealth when > 0",
            },
        },
    ]


def _death():
    return {
        "evidence": "read from code (CharacterRoot.DecreaseHealth 0x695632, branch"
        " 0x695e83-0x696132)",
        "ordinary": "health 0 and game event 201 CHARACTER_DEAD: the path of every character",
        "versus_only": "a playable victim, when both playable characters exist and one has"
        " AIBrainNode.agentFaction 1 (a hero-versus-hero fight)",
        "versus_outcomes": [
            "scene 40 PLAYER_VS_PLAYER, health before the hit > 0.5 and the inflictor in an"
            " attack state: health is set to 0.5 and the inflictor is forced into a finishing"
            " move on the victim (not dead)",
            "game mode 3, or mode 2 with the victim at playable index 0, or mode 1 with the"
            " victim at index 1: health is set to 1.0 and game event 104 / 105 is sent; alive"
            " unless the scene is 40",
        ],
        "game_modes": "exe enum family GAME_MODES: 1 RORSCHACH, 2 NITEOWL, 3 COOP (that"
        " ProjectLib.GetGameMode returns these values is inferred)",
        "not_established": "the name of forced animation 9",
    }


def _attack_permission():
    return {
        "evidence": "read from code",
        "orchestrator_grant": {
            "handler": "CombatOrchestrator.StateActive 0x6e8231 (grant block 0x6e900d)",
            "per": "hero (faction 0 character), every frame",
            "rule": "a waiting attacker is granted (behaviour.command_may_attack) when the hero"
            " has fewer than _imaxnumberofattacks current attacks, the newest current attack"
            " started at least _nattackfrequency ago and no grant is younger than"
            " _nattackfrequency; the first waiting entry whose attacker is alive and an active"
            " attacker in this combat gets it",
            "regrant": "a granted request that has not started is granted again when"
            " (now - granted) + _nattackwaittime < now (registered default 0.5)",
            "immune_target": "no grant while the hero's animation is immune to attacks; every"
            " current attack then gets command_break_off_attack",
            "cleanup": "waiting entries with no or a dead attacker are erased",
            "parameters": "max attacks, frequency, cooldown and idle time are level data"
            " (CombatOrchestratorParameters presets, set by triggers); they are the game's"
            " difficulty ramp and are not part of this block",
        },
        "faction_filter": "target lists come from AIBrainNode.GetVisibleAIEnemies 0x484235"
        " (sweeps: Perception's known-enemy list, fed by GetSeenAIEnemies 0x48460d): another"
        " active agent whose faction is not NEUTRALFACTION (2) and differs from the caller's,"
        " and that passes the sight test; a character set as"
        " Perception.m_forceperceptedcharacter is added without a faction test; that member is"
        " written only by Enemy.StateActive 0x724071 (store at 0x725078): on acquiring a target,"
        " each other living member of the enemy's group whose known-enemy list is empty receives"
        " the enemy's own target if the enemy can see it; Perception.AddNewKnownEnemies 0x7dcc88"
        " uses it once and clears it",
        "enemy_evaluate": {
            "handler": "Enemy.Evaluate 0x72587d",
            "interval": "each enemy evaluates every 0.0625 + rand * 0.1 s",
            "order": [
                "health <= 0: INACTIVE",
                "breadcrumb mode (AGGRESSIVE only)",
                "forced state (AILib.CheckForcedState 0x59ca06)",
                "target and step-back timer or step-back behaviour running: STEP_BACK",
                "PASSIVE: RETURN_TO_COMBAT_ZONE outside its turf, else IDLING; nothing below"
                " is evaluated (0x726214 / 0x7264a2 / 0x726fc3)",
                "AGGRESSIVE: return to the combat zone, idle without a live reachable target,"
                " hang back, ATTACKING within the engagement distance with a clear line, else"
                " CHASING",
                "any other state of mind: IDLING",
            ],
            "passive_becomes_aggressive": [
                "Enemy.command_react_to_attack (a hero enters an attack state on it)",
                "CharacterRoot.command_give_damage 0x691b10 with an inflictor",
                "CharacterRoot.command_give_ragdoll_damage_increment 0x6914f2",
                "being the attack target in CharacterRootLogic.FireAttackBasedOnAttackID"
                " 0x68d870",
                "the trigger action SET_AI_STATE",
            ],
            "note": "a PASSIVE enemy neither chases nor attacks; the whole group turns"
            " aggressive together (CharacterRoot.SetAggressive 0x677f3f)",
        },
    }


def _twilight_reaction():
    return {
        "evidence": "read from code; the four constants, the from-behind rule and the clamp"
        " were re-read independently, the branch order was read once",
        "handler": "Enemy.command_react_to_attack_twilight_lady 0x7220c7 (replaces the"
        " reaction table for character type TWILIGHT_LADY)",
        "order": [
            "back-flip behaviour running: it handles the attack",
            "she is the master of a paired move: no reaction",
            "attacker records older than 5.0 s are dropped",
            "a human attacker's unblockable attack: no reaction with probability 0.75",
            "first attack of an attacker: dodge with probability 0.22",
            "attack n of a known attacker, n < hits_before_dodge - 1: dodge with probability"
            " 0.22",
            "later, below hits_before_dodge + dodges_before_counter - 1: a forced fast attack"
            " with probability _spamprobability_fastquick, else dodge",
            "from hits_before_dodge + dodges_before_counter - 1 on (not in an"
            " IMMUNE_TO_BREAK_ATTACK state): a slow attack with override STUN when rand >"
            " _spamprobability_counterattack, else a counter attack",
        ],
        "from_behind": "attacks from behind are not exempt for her (the behind flag is forced"
        " to 0)",
        "defaults": {
            "hits_before_dodge": 3,
            "dodges_before_counter": 1,
            "_spamprobability_fastquick": 0.2,
            "_spamprobability_counterattack": 0.6,
        },
        "defaults_note": "registered defaults; a level trigger sets them"
        " (command_set_twilight_combat_params, dodges_before_counter clamped to at most 1)",
        "forced_attack_move_dist_m": 1.5,
        "random": "engine random numbers (MT19937, seeded once with 5489, never reseeded by"
        " script): unlike the reaction table the routine depends on the draw",
        "not_exported": "her punish and back-flip routines",
    }


def _sweep():
    return {
        "evidence": "read from code (PC; the scalar skeleton and both constants also in the"
        " X360 build)",
        "handlers": "CharacterVisual.command_begin_sweep_attack 0x698a43, StateActivePlayPos"
        " 0x698fe1, DoEnemyCheckAgainstTravelLine 0x69a57d,"
        " CharacterRootLogic.command_sweep_target_detected 0x6879ed",
        "step_playpos": SWEEP_STEP_PLAYPOS,
        "stepping": "one check per 0.05 of play position passed (several in one frame when"
        " more has passed); the state property m_nchecksprsec is not read",
        "slices": "the three stored (angle, length, playpos) entries are begin, impact and"
        " end; the slice advances when the counter passes an entry's play position and the"
        " sweep ends at the last; length and angle are interpolated linearly inside a slice",
        "hit_distance_m": SWEEP_HIT_M,
        "hit_test": "per potential target except the main attack target: closest point on the"
        " segment from the last to the current check point, both ends at the target's height;"
        " a hit when nearer than 0.8 m; the target is then removed from the list (at most one"
        " hit per sweep)",
        "effect": "command_sweep_target_detected -> SetCloseCombatDamageToTarget (rules.damage)"
        " unless the detected character's state has special handling BLOCK: a blocking sweep"
        " victim takes no block damage",
        "parameters": "states[*].combat.sweep",
        "check_point": "P = visual world position + (visual position - last recorded model"
        " position, refreshed after the check when it moved > 0.01 m) + conj(Q)*(sin r, 0, cos"
        " r)*Q * dist; Q = the visual's world orientation; r = angle[i-1] + pct * right slice"
        " (clockwise) or angle[i-1] - pct * (2pi - right slice) (counter-clockwise); right"
        " slice(a, b) = a - b, plus 2pi if negative, taken as (angle[i], angle[i-1]); dist ="
        " (1 - pct) * len[i-1] + pct * len[i]; pct = (counter - playpos[i-1]) / (playpos[i]"
        " - playpos[i-1])",
        "direction": "counter-clockwise when rightSlice(impact, begin) > rightSlice(end, begin)"
        " (DetermindTravDir 0x69b2be); the property m_tcounterclockwise is not read",
    }


def rules(visual_def=None, underboss_defs=None):
    """The fixed rules, as data.  `handler` = script handler and its address.
    visual_def: the CharacterVisualDef numbers of the extract (CombatData), for
    rules.ragdoll_damage.visual_def.  underboss_defs: the UnderbossDef records of the
    extract (CombatData.underboss_defs); `rules.underboss` exists only when there is one."""
    out = _rules(visual_def)
    if underboss_defs:
        out["underboss"] = _underboss(underboss_defs)
    return out


def _rules(visual_def=None):
    flash, discharge, electrify = _area_damage()
    return {
        "constants": [
            {"value": v, "address": a, "type": t, "meaning": m} for v, a, t, m in CONSTANTS
        ],
        "damage": {
            "evidence": "read from code",
            "handler": "CharacterRootLogic.SetCloseCombatDamageToTarget 0x6ae57f",
            "formula": (
                "damage = (base * modifier * global * uber)"
                " * [0.2 if the target's electric armour fired and the attacker is not the"
                " Underboss]"
                " + [string completed] combo.bonus_damage * modifier * global * uber"
                " + [attacker charged] special_def.m_ndamageperchargeattack * global * uber;"
                " applied = damage * victim.m_nincomingdamagefactor"
                " * [max(1/uber, 0.7) if uber > 1 and the victim is playable]"
                " * [0.2 if the victim is the Underboss and the attacker is not a player],"
                " subject to `receive`"
            ),
            "inputs": {
                "base": "combo database default for button x held weapon class, set when the"
                " attack is initialised (CharacterRootLogic.InitializeNextAttack 0x68bf6f ->"
                " AddAttackToCombo 0x68bca8), from the weapon class held at that moment",
                "modifier": "EnemyDef._ndamagemodifier when not 0, else the CharacterDef's"
                " _ndamagemodifier (EnemyDef.command_get_damage_modifier 0x71f0cf);"
                " PartnerDef uses m_ndamagemodifier (0x597273); 1.0 without a behaviour"
                " handler (CharacterRoot.command_get_damage_modifier 0x6931a4)",
                "global": 'PublicLib.g_nglobaldamagefactor, default "1.000000" registered at'
                " 0x7f1ce6; no script writer; not present in the extracted fragments",
                "uber": "CharacterRoot.m_ninrageuberdamagefactor: 1.0, or"
                " special_def.m_nrageuberdamagefactor in uber rage",
                "incoming": "CharacterRoot.m_nincomingdamagefactor, default 1.0, set only by"
                " level triggers (command_set_incoming_damage_factor 0x691a62)",
                "electric_armour": "the target's armour fires"
                " (ElectricArmor.command_electric_armor_hit 0x71ea63) only in its StateActive"
                " with charge power > 0; each firing takes 1 / m_nelectrifycharges off the"
                " charge.  The attacker is then shocked: global"
                " * special_def.m_ndamageperchargedefence * the ATTACKER's uber, stun"
                " m_nstunperchargedefence, pose LIGHT_UPPER_STRAIGHT (NO_POSE and no 0.2 for"
                " an Underboss attacker)",
                "charge": "the attacker's own armour firing in the same way adds the third"
                " term (no modifier) and special_def.m_nstunperchargeattack of stun",
            },
            "receive": _receive(),
            "death": _death(),
            "weapon_durability": "a hit takes durability off the attacker's weapon also when"
            " it is blocked, and once more per sweep victim that is not blocking; not for"
            " states flagged ignore_weapon_sound or a placeholder target",
            "difficulty": "no difficulty input in script code",
            "override": "SetCloseCombatDamageToTarget has three callers.  Two pass -1.0 (no"
            " override).  The IMPACT_EFFECTS event with m_ttruth1 passes its m_nvalue: > 0"
            " replaces the state's default damage (27 events in Part 2 PC: Enemy04 x 22,"
            " Rorschach x 5); `override_events` lists them for this extract",
            "per_state_damage": "states[*].combat.damage lists base * modifier per owning"
            " CharacterDef and weapon class (global = uber = incoming = 1, no bonus)",
        },
        "unblockable": {
            "evidence": "read from code",
            "handler": "CharacterRootLogic.command_start_animation_state 0x688961",
            "any_of": [
                "attacker in uber rage (m_ninrageuberdamagefactor > 1)",
                "attacker's combo list holds more than one item",
                "attacker has electrified charges",
                "attacker holds a weapon and the state's animation type is not THROW",
            ],
            "effect": "the defender's reaction table is skipped and the attack is not"
            " remembered (Enemy.command_react_to_attack 0x721958)",
        },
        "defender": {
            "evidence": "read from code",
            "reaction_table": {
                "handler": "Enemy.command_react_to_attack 0x721958",
                "evaluated": "when the attacker ENTERS an attack state"
                " (CombatOrchestrator.command_attack_animation_stated 0x6e6495); not for"
                " states with special handling RESEND_PUNCH_WHEN_IN_RANGE",
                "gates": [
                    "the defender can lock onto the attacker",
                    "the attack is not unblockable",
                    "the attacker is not behind the defender (TACTICAL_INFO 0x400"
                    " PLACEMENT_REAR)",
                    "the defender is neither stunned nor prone (its history is cleared)",
                    "the attack state's animation type is not NOTSET",
                ],
                "matching": "the attack's animation type goes into a ring of 9; rows are"
                " tried in order; a row lists types newest first, AI_SYSTEM_ONLY__ANY_ATTACK"
                " matches any, a row of n entries needs n remembered attacks; no random"
                " number",
                "results": {
                    "BLOCK": "CharacterRoot.command_block",
                    "DODGE": "AILib.SetGoodDodgeDir + CharacterRoot.command_dodge",
                    "COUNTERATTACK": "command_block + command_delayed_counter_attack(0.15 s)",
                },
                "history_cleared": [
                    "by a row with clear_history",
                    "m_nreactiontoattackdecaytime seconds after the last attack",
                    "when the defender is stunned or prone",
                    "when hit after a block / dodge reaction (m_tclearifblockdodgeisbroken;"
                    " Enemy.command_hit_by 0x722bbb)",
                ],
            },
            "counter": {
                "handler": "CharacterRootLogic.TestForCounterAttack 0x68d36a",
                "rule": "with p the attacker state's play position, p0 / p1 the previous /"
                " next IMPACT event and D the clip duration: (p1 - p) * D > 0.13 and"
                " (p - p0) * D > 0.03 (player) or -0.03 (AI); the attacker must be"
                " attacking the defender or have just been dodged by it; no test while the"
                " attacker is in its rush state",
                "margin_s": COUNTER_MARGIN_S,
                "note": "D is the clip's own duration: a state with speed s leaves"
                " margin / s seconds of real time",
            },
            "whiff": {
                "handler": "CharacterRootLogic.command_animation_event_received 0x6a525e,"
                " PRE_IMPACT",
                "rule": "an AI attacker farther than this from its target at PRE_IMPACT"
                " drops the target and the hit; players have no such test",
                "whiff_basis": {
                    "ai": "class played by AI enemies: distance_m",
                    "ai_big": "class of a big AI enemy: distance_big_attacker_m",
                    "player": "hero class: no test for a player (whiff_distance_m null); an"
                    " AI partner playing the class is tested at distance_m",
                },
                "distance_m": WHIFF_M,
                "distance_big_attacker_m": WHIFF_BIG_M,
                "big": "CharacterRoot.command_is_big 0x68f192: animation class model type"
                " ENEMY_02_BIG_GUY (4) or UNDERBOSS (5)",
            },
            "block": {
                "handler": "CharacterRootLogic.SetCloseCombatDamageToTarget 0x6ae57f",
                "rule": "the hit is blocked when the target's state has special handling"
                " BLOCK or IMMUNE_TO_BREAK_ATTACK (or the target is the Underboss hit from"
                " behind) and the attacker's RELATIVE_HEAD_HEIGHT value is > 0; damage still"
                " lands if the attacker has electrified charges",
                "relative_head_height": "the attacker's own head bone (bone type 0) model"
                " height in character mode 0, else a constant",
            },
            "dodge": {
                "handler": "CharacterRoot.command_i_will_dodge_you 0x693fa1",
                "rule": "the attacker loses its attack target and its combo; the dodger is"
                " remembered as m_ehasjustdodgedme (a counter on it needs no timing)",
            },
            "hit_soon": "PRE_IMPACT starts the victim's hit / block animation"
            " (CharacterRoot.command_hit_soon 0x6903ea); health is removed at IMPACT",
        },
        "impact": {
            "evidence": "read from code",
            "rule": "at IMPACT the attack target takes the hit without a range or cone test;"
            " states flagged sweep also hit every character their sweep volume detects"
            " (CharacterRootLogic.command_sweep_target_detected 0x6879ed; rules.sweep)",
        },
        "sweep": _sweep(),
        "ragdoll_damage": _ragdoll_damage(visual_def),
        "attack_permission": _attack_permission(),
        "twilight_lady_reaction": _twilight_reaction(),
        "combo": {
            "evidence": "read from code",
            "handlers": "CharacterComboDatabase.get_longest_valid_combo 0x66cd98,"
            " CharacterRootLogic.InitializeNextAttack 0x68bf6f, AddAttackToCombo 0x68bca8,"
            " ExecuteAttack 0x68b351",
            "rule": "each press appends an item (button x held weapon class; any attack on a"
            " prone target is KICK); the longest enabled string equal to the TAIL of the"
            " pressed list is the current combo; its override is written to animation enum"
            " 8 OVERRIDE_ATTACK_COMBO for that attack, and at the hit its bonus damage, stun"
            " and push-back apply",
            "initial_attack": "ACTION INITIAL_ATTACK is fired with the first attack of a"
            " string when the current state is not an attack state (ExecuteAttack)",
            "speedup": {
                "handler": "CharacterRootLogic.command_start_animation_state 0x688961",
                "rule": "an attack entered with more than one item in the combo list (a"
                " player; an AI only while it performs a combo) starts at the play position"
                " of its CLEAR_DEADZONE event minus lead / D (D = clip duration): lead 0.15 s"
                " for animation type LIGHTATTACK, 0.2 s for HEAVYATTACK; no speed-up for"
                " other types, for states flagged immune_to_combo_speedup, or when the"
                " result is not > 0",
            },
        },
        "finisher_prompt": {
            "evidence": "read from code",
            "handlers": "CharacterRoot.DecreaseHealth 0x695632, UpdateHealth 0x678288,"
            " PlayerCtrl.CheckFinishMove 0x7eff13, CharacterRootLogic.FinishOrStompEnemy"
            " 0x677c93",
            "trigger": "the first hit by a player that takes health below"
            " CharacterDef.m_ncriticalhealth without killing",
            "prompt_time": "CharacterDef.m_nfinishicontime seconds",
            "button_count": {"EDITOR": 3, "PC": 3, "X360": 4, "PS3": 4},
            "buttons": ["PLAYER_DEFEND", "PLAYER_ATTACK_0", "PLAYER_ATTACK_1", "PLAYER_ATTACK_2"],
            "reroll": "up to 10 times while the roll equals the last button pressed",
            "wrong_button": "cancels the prompt once it is older than 0.7 s",
            "result": "FINISHING_MOVE, or KILL_PRONE_TARGET when the target is ragdolled or"
            " its head bone is below -0.18 m",
            "per_character": "combat.character_defs[*].critical_health / finish_icon_time_s",
        },
        "damage_pose": {
            "evidence": "read from code (ProjectAnimationLib, all handlers)",
            "order": ["combo", "direction", "size", "height"],
            "combo": {
                "handler": "CharacterRootLogic.ComboManipulateDamage 0x675ce6",
                "override HEAVY_DAM": _named_map(POSE_LIGHT_TO_HEAVY),
                "override STUN": _named_map(POSE_TO_STUN),
            },
            "direction": {
                "handler": "ProjectAnimationLib.DirectionManipulateDamage 0x802ae8",
                "when": "attacker's z in the target's visual frame < -0.2 m",
                "map": _named_map(POSE_TO_BACK),
            },
            "size": {
                "handler": "ProjectAnimationLib.SizeManipulateDamagePose 0x7fca72",
                "when": "the attacker's main attack target is big and the attack is not"
                " upper (for sweep victims this is not the entity hit)",
                "map": _named_map(POSE_HIGH_TO_LOW),
            },
            "height": {
                "handler": "ProjectAnimationLib.HeightManipulateDamagePose 0x7fcaee",
                "dy": "target height - attacker height; hit_y = state impact position y",
                "dy > 0.1 and hit_y - dy < 0.4": _named_map(POSE_HIGH_TO_LOW),
                "dy < -0.1 and hit_y - dy > 0.4": _named_map(POSE_LOW_TO_HIGH),
            },
            "upper_poses": [pose_name(i) for i in POSE_UPPER],
            "classes": {nm: [pose_name(i) for i in ids] for nm, ids in _POSE_CLASS},
            "reaction": "no damage threshold: the victim's hit reaction is the state whose"
            " DAMAGE_POSE criterion matches the delivered pose",
        },
        "pair_triggers": {
            "evidence": "read from code; the rule of a pair is read from its master state's"
            " criteria (the control action its groups ask for)",
            "rules": dict(sorted(RULE_TEXT.items())),
            "breakout": "between the partner's FORCE_ALLOW_BREAKOUT and"
            " FORCE_ALLOW_BREAKOUT_NO_MORE events a dodge / block / forced counter by the"
            " partner ends the pair (CharacterRootLogic.command_dodge 0x686a17,"
            " command_block 0x686e56)",
            "counter_damage": "(counter_damage * (0.75 when the partner is playable)"
            " + completed-string bonus) * modifier * global * uber; pairs[*].trigger.damage"
            ".amounts lists counter_damage * factor * modifier",
        },
        "pair_damage": {
            "evidence": "read from code",
            "handler": "CharacterRootLogic.command_animation_event_received 0x6a525e",
            "IMPACT in a non-attack state": "((counter damage, else 20) * 0.75 when the"
            " partner is playable + completed-string bonus) * modifier * global * uber; pose"
            " NO_POSE; rage flag cleared in uber rage; combo validity now + 1.0",
            "KILL_ANIMATION_PARTNER": "100000 damage to the partner",
            "DIE": "100000 damage to the character itself",
            "BULLMOVE_IMPACT": "special_def.m_nbullrushdamage * global * uber, * 0.4 when"
            " the victim is playable; stun special_def.m_nbullrushstun",
            "FLASH_GRENADE": flash,
            "DISCHARGE_ARMOR": discharge,
            "ELECTRIFY_ARMOR": electrify,
            # the range of ELECTRIFY_ARMOR (the entry above is prose): a code constant
            "ELECTRIFY_ARMOR_range_m": ELECTRIFY_RANGE_M,
            "IMPACT_EFFECTS with m_ttruth1": "the event itself calls"
            " SetCloseCombatDamageToTarget(victim, m_ecuranimstate, m_nvalue): m_nvalue > 0 is"
            " the damage, else the state's default (_nnextdefaultdamage); rules.damage"
            ".override",
        },
        "bull_rush": _bull_rush(),
        "partner_ai": _partner_ai(),
        "special_handling": dict(SPECIAL_HANDLING_NOTES),
        "attack_id": "the unique attack id (damage struct +0x38) is passed by give_damage to"
        " DecreaseHealth and from there only into game events 0xcb and 0xc9; no handler"
        " compares it.  i_will_hit_you is sent by CharacterRootLogic"
        ".command_start_animation_state 0x688961 when a state with m_tisattackstate or special"
        " handling 4 starts and an attack target exists; the receiver keeps the entry 1.5 s",
    }


# ------------------------------------------------- rules read in the final sweep
SPECIAL_HANDLING_NOTES = {
    "BULL_MOVE": "BULL_MOVE: after event 15 CHARGE it keeps CharacterPhysics in charge mode"
    " (leaving it -> free fall); for a player the StateActive local nrotatefactor (name from"
    " declaration order) is 1.5 for the first 0.25 s of the state, then 0; on state end the"
    " heading override is cleared, a non-player loses its lock target and a player gets"
    " release_dodge_lock; like any non-NORMAL value it stops the character being pushed."
    " Also set on counter-attack and finishing-move states.",
}


def _bull_rush():
    return {
        "evidence": "read from code (PC); animation and state data measured on PC Part 2",
        "start": "animation event 15 CHARGE sends CharacterPhysics.command_state_charge; the"
        " state ends in free fall as soon as the current state's special handling is not"
        " BULL_MOVE",
        "contact": "animation value 9 DISTANCE_TO_END_POS = 3D distance root to lock target, 0"
        " without a target, 10.0 while the target blocks or is electrified"
        " (SendBullRushDataToAnimationCtrl 0x696d2d); Rorschach starts the impact pair on"
        " [0.05, 1.0); EnemyBig 'Freight Train' leaves to CombatGroup below 2.0 or at"
        " animation end",
        "secondary": {
            "who": "every target-list entry that is not a placeholder, the lock target or the"
            " animation partner",
            "radius": "capsule radius + 1.0 (3D)",
            "in_front": "dot(face heading, horizontal direction) > 0",
            "gate": "victim state m_tstunlockstate == 0 (set on the hit-reaction, Ragdoll-Hit,"
            " AttackBlocked and ThrownInAir states: 100 states on PC Part 2)",
            "damage": "special_def.m_nbullrushsecondarydamage, no global / uber / modifier"
            " factor",
            "stun": "special_def.m_nbullrushsecondarystun",
            "pose": "11 or 8 (rand < 0.5 first) when |local x| >= 0.2 or the victim is big,"
            " else 17 or 14; then DirectionManipulateDamage",
            "push": "when animation speed > 2.0: 0.3 s at 4.0 m/s along normalise(sign(local"
            " x), local y, local z) in the attacker's frame (diagonal to sideways, on the"
            " victim's side)",
            "low_violence": "a prone victim is skipped",
        },
        "blocked_by_player": "a blocking or electrified playable lock target nearer than 1.1 m"
        " gets hit_soon(pose 2) and give_block_damage; the attacker is forced to animation 9"
        " and fires actions 14 and 30",
    }


def _partner_ai():
    return {
        "evidence": "read from code; constants read from the executable's bytes",
        "handlers": "Partner.Evaluate 0x7dba9f, Partner.StateActive 0x7daa2e,"
        " CombatPartner 0x6ec895 / 0x6ed5d1 / 0x6ebac7 / 0x6eb7c7,"
        " AttackKillTargetPartner 0x6014e2, CrowdControlPartner 0x6ef510 / 0x6f1195 / 0x6f214f,"
        " CombatHelpPartner 0x6e17da, FollowPartner 0x73e357",
        "evaluate": "forced state; step back; AGGRESSIVE only: in combat and preconditions ->"
        " COMBAT, else human alive -> FOLLOW_PARTNER; otherwise IDELING",
        "mega_kill": {
            "attack_interval_max_s": 0.5,
            "attack_interval_min_s": 0.0,
            "damage_modifier": 10.0,
        },
        "low_health": {"react_probability": 1.0, "help_check_interval_s": 0.5},
        "repeat_action_s": 0.3,
        "react_multipliers": {
            "paired_attack": 1.2,
            "twilight_lady": 0.4,
            "stun_lock": 1.3,
            "stun_lock_unblockable": 0.7,
        },
        "react_draw_floor": 0.01,
        "block_paired_attack_probability": 0.5,
        "behavior_switch_step": 0.1,
        "human_low_health_threshold": 50,
        "partners_target_exclusion_m": 2.5,
        "special_moves": {
            "rorschach_step_around_window_s": 5.0,
            "niteowl_electrify_range_kill_m": 3.0,
            "niteowl_special_range_crowd_m": 4.0,
            "niteowl_throw_min_charge": 0.05,
            "niteowl_throw_min_target_health": 80,
        },
        "combo_timeout_s": {"crowd_control": "items * 5.0", "help_partner": "items * 0.5"},
        "follow": {
            "ahead_min_m": 1.5,
            "speed_match": {
                "rorschach": [3.32, 4.83],
                "nite_owl": [2.67, 4.77],
                "floor": 0.6,
                "walk": 0.4,
            },
            "forced_stop": {
                "human_speed_below": 0.1,
                "within_m": 4.0,
                "not_behind_more_than_m": 1.0,
            },
            "corridor_check_s": 3.0,
            "stuck_replan_s": 5.0,
            "waypoint_fallback": {
                "only_while": "goal unreachable or no AI velocity",
                "distance_m": 20.0,
                "delay_s": 5.0,
                "recheck_s": 2.0,
            },
        },
        "find_closest_radius": "sqrt(visual_range)",
        "waypoint_move": {
            "handlers": "BehaviorWaypointMove.StateActive 0x6289b4, StateUseTrigger 0x629b68,"
            " StateForceMove 0x62aef5",
            "requery_while_breadcrumb_younger_s": 2.0,
            "pause_order_clear_m": 0.5,
            "absolute_animation_wait_s": 1.0,
            "flying_waypoint_range_m": 50.0,
            "stuck_move_m": 0.1,
            "stuck_s": 5.0,
            "first_replan_s": 0.5,
            "replan_s": 5.0,
            "arrive_m": 1.0,
            "stand_before_use_s": 1.0,
            "walk_within_m": 3.0,
            "force_move_s": 2.0,
            "use_trigger": "StateUseTrigger stops the move and returns false for a root without"
            " a PlayerCtrl (0x629c52); an AI partner has none, so it never uses a trigger from"
            " here (inferred from two read facts)",
        },
        "known_defects": [
            "CrowdControlPartner.TakeCareOfOwnCrowd throws with a null target (0x6f2428)",
            "AttackKillTargetPartner registers its attack with the target's CharacterRoot as"
            " the behaviour (0x603129 -> 0x6eb1c2 -> 0x6252e3 -> 0x6e620c)."
            " CombatOrchestrator.command_attack_animation_stated 0x6e6495 sends"
            " command_attack_animation_stated to that root, which has no such command, so the"
            " behaviour's handler 0x601088 does not run; command_release_attackers 0x6e388e"
            " sends command_break_off_attack to the target's own root (0x691013) instead of the"
            " partner's behaviour",
        ],
    }


# Underboss (Part 1): the three health-fraction properties and the phase-4 step count
UNDERBOSS_PHASE4_STAGES = 4  # hard-coded: stage 4 is final (cmp stage, 4 in JumpOnCharacter)


def underboss_phases(f0, f1, f2, steps):
    """The health-fraction intervals of the Underboss's phases, as the engine walks them.

    f0, f1, f2: UnderbossDef.m_nhealthfractiongotonextphase, m_nhealthfraction1gotonextphase,
    m_nhealthfraction2gotonextphase; steps: m_istepsinphase4.  Phase 4 always has four
    stages of (1 - f2) / steps each, floored at 0.  None when a value is missing."""
    if None in (f0, f1, f2) or not steps:
        return None
    f0, f1, f2 = float(f0), float(f1), float(f2)
    step = (1.0 - f2) / float(steps)
    r = lambda x: round(x, 6)
    out = [
        {"phase": 1, "start": 1.0, "end": r(f0)},
        {"phase": 2, "start": r(f0), "end": r(f1)},
        {"phase": 3, "start": r(f1), "end": r(f2)},
    ]
    for k in range(1, UNDERBOSS_PHASE4_STAGES + 1):
        out.append(
            {
                "phase": 4,
                "stage": k,
                "start": r(f2 - (k - 1) * step),
                "end": r(max(0.0, f2 - k * step)),
            }
        )
    return {
        "phases": out,
        "stage_count": UNDERBOSS_PHASE4_STAGES,
        "phase4_step": r(step),
        "phase4_reaches_zero": bool(f2 - UNDERBOSS_PHASE4_STAGES * step <= 1e-9),
        "floor": "health cannot go below the current threshold (command_set_lower_bound,"
        " 0x8932d1); death at health <= 1",
        "max_health_source": "CharacterDef.m_nmaxhealth of the character type"
        " (UnderbossDef.m_nmaxhealth is not read)",
    }


def _underboss(defs):
    """rules.underboss: the fixed rules plus, per UnderbossDef of the data, its phases."""
    return {
        "evidence": "read from code (PC executable; Part 1 data); the hit / block counts, the"
        " shockwave numbers and the target re-check time are registered defaults",
        "success_test": {
            "default": True,
            "false_in_state": "UnderbossPhase1.StateFleeToJumpPoint",
            "handlers": {"true": "0x7f09ac", "false": "0x87b96e"},
            "effect": "PRE_IMPACT sends block_timed(1.0); m_idamagestate 1",
        },
        "react": {
            "handler": "0x88aa08",
            "hits_before_block": 3,
            "blocks_before_counter": 2,
            "values_are": "registered defaults",
            "block_time": 1.0,
            "series_keep_first": 3.0,
            "series_keep": 1.0,
            "not_counted": ["attacker behind", "player unblockable attack"],
            "retaliate_after_first": 1.5,
            "retaliate_after_not_counted": 3.0,
            "counter_skipped_when": "IMMUNE_TO_BREAK_ATTACK",
            "counter": {
                "phase_1_2": {
                    "command": "attack_slow",
                    "fire": ["ONE_FRAME_ACTION", "NORMAL_ATTACK", "HEAVY_PUNCH"],
                    "unfire": ["PUNCH"],
                    "override_attack_combo": "NORMAL",
                },
                "phase_3_4": {
                    "command": "attack_fast",
                    "attack_pose": "POSE_AFTER_DASH unless the attacker's animation type is"
                    " COUNTERATTACK or FINISHINGMOVE",
                    "fire": ["NORMAL_ATTACK", "PUNCH", "ONE_FRAME_ACTION"],
                    "override_attack_combo": "KNOCKDOWN",
                },
            },
            "attack_move_dist": 1.5,
            "live_in_states": ["StateActive", "JustAttacked", "StateStopAttacker"],
        },
        "interrupts": {
            "range": 4.0,
            "rules": [
                "FINISHINGMOVE whose m_eattacktarget or animation partner is the Underboss",
                "BULLMOVE / THROW / FAILED_THROW by an enemy that faces the Underboss"
                " (Underboss in the enemy's local +z)",
            ],
            "attack": "attack_fast, OVERRIDE_ATTACK_COMBO KNOCKDOWN",
        },
        "punish": {
            "on": "attacker completed combo",
            "unless_delay_opponent_within": 2.0,
            "stun_min": 0.8,
            "stun_on_rehit": 0.7,
            "ignores_prone_gate": True,
        },
        "attack": {
            "range": 4.5,
            "ai_target_window": 2.1,
            "prone_reattack": 4.0,
            "target_recheck": 6.0,
            "target_recheck_is": "registered default of UnderbossLib.ntargetlocktime (0x8a1b34);"
            " no writer found",
            "switch_when_other_enemy_within": "UnderbossDef.m_nenemyengagementdist",
            "switch_to": "first other known enemy",
        },
        "shockwave": {
            "trigger_event": "TRIGGER_END_INTERPOLATING (67) in JumpOnCharacter",
            "damage": 10.0,
            "damage_radius": 2.5,
            "knockdown_radius": 2.5,
            "distance": "horizontal",
            "pose_inside": "KNOCKDOWN_UPPER_STRAIGHT",
            "pose_outside": "HEAVY_UPPER_STRAIGHT",
            "skips_playables_at_stage": 4,
            "values_are": "registered defaults",
            "spread_speed_used": False,
        },
        "flamer": {
            "damage_per_contact": "UnderbossDef.m_iflamerdamage",
            "pose_base": "HEAVY_UPPER_STRAIGHT",
            "bursts_before_reequip": "5 - stage",
        },
        "movement": {
            "evidence": "read from code (UnderbossMovement.command_defaut_movement 0x887a07,"
            " lifted listing; constants from the executable's bytes)",
            "beyond_max_melee": "run after the target: full speed at 5.0 m or more, walk speed"
            " below; pathfinder goal = target + (0, 1, 0)",
            "full_speed_from_m": 5.0,
            "inside_max_melee_beyond_attack_distance": "walk speed x 0.5",
            "inside_attack_distance_beyond_minimum": "stop (idle speed)",
            "inside_minimum_distance": "step back facing the target at walk speed x 0.5; turn"
            " first when the facing error is outside +-1.5 rad; stop after 0.5 s of stepping"
            " back with move speed below 0.6",
            "approach_speed_factor": 0.5,
            "step_back_turn_first_rad": 1.5,
            "step_back_stop_after_s": 0.5,
            "step_back_stop_below_speed": 0.6,
            "target_lock_cleared_above_speed": 0.5,
            "turn_in_place": "not attacking and (facing error outside +-0.3 rad or speed below"
            " 0.2): speed 0 and turn, by the error x 0.2 while moving faster than 0.3",
            "turn_in_place_error_rad": 0.3,
            "turn_in_place_below_speed": 0.2,
            "turn_error_factor": 0.2,
            "turn_error_factor_above_speed": 0.3,
            "distances_are": "UnderbossDef.m_nattackdistance, m_nminimumdistance and the max"
            " melee distance",
        },
        "flee": {
            "evidence": "read from code (lifted listing of UnderbossFlee: init 0x886106,"
            " StateActive 0x884a6f, 0x8867e2, 0x886913, 0x88643d; 0.9 and 2.0 from the"
            " executable's bytes)",
            "points": "scene nodes: every sibling named fleepointlinear, and"
            " fleepointcircular1... until a number is missing",
            "trigger": "the closest player is nearer than the current flee distance and the"
            " vertical gap is under m_nminverticaldistwhenfleeing; the flee distance is redrawn"
            " uniformly between m_nmindistwhenfleeing and m_nmaxdistwhenfleeing (0x87a5d0)",
            "linear": "the next list point; when the list ends, circular flee from then on",
            "circular": "candidates: not the nearest point of either hero on his level, index"
            " differing by 1 or 3 from his own nearest point (0x87a6c3), direction from him"
            " with a dot of at most 0.9 with the direction to each hero (0x886eed); one is"
            " picked at random",
            "same_level_height_m": 2.0,
            "candidate_index_steps": [1, 3],
            "candidate_max_dot": 0.9,
            "surrounded": "no candidate, or more than m_inumberofpointsincircular picks: he"
            " leaves the state when a hero comes within the surrounded distance",
            "arrive_m": 2.0,
        },
        "flamer_volumes": {
            "evidence": "read from code (lifted listing of FlameThrower: Init 0x7385f9, state"
            " active 0x7414e7; defaults registered at 0x74449e, 0x7444b3, 0x7444c8); inferred:"
            " that the local vpos is the aim vector",
            "length_m": 12.0,
            "speed_m_per_s": 10.0,
            "capsules": 5,
            "capsule_width_m": 2.0,
            "start_ages_s": [0.0, 0.3, 0.6, 0.9, 1.2],
            "values_are": "registered defaults",
            "tick": "age += dt; position = flamethrower position + direction x speed x age,"
            " y from ResidualLimiterNode; above length / speed the capsule restarts at age 0"
            " with the current aim direction while firing, else with a zero direction",
        },
        "unreachable": [
            "UnderbossPhase1.command_hit_by 0x888c4b (UnderbossCombat does not forward hit_by)"
        ],
        "game_events": {str(k): v for k, v in sorted(UNDERBOSS_GAME_EVENTS.items())},
        "defs": defs,
        "not_established": "whether the registered defaults 3 / 2 are live (a registered"
        " default is parsed into the slot at instance creation; the shipped fragment stores"
        " neither property);"
        " the shipped values of the UnderbossDef flee properties, FaceTarget, the residual"
        " fire areas",
    }


UNDERBOSS_GAME_EVENTS = {  # exe enum family GAME_EVENTS (registered in 0x80c150)
    700: "UNDERBOSS_GOTO_PHASE1",
    701: "UNDERBOSS_GOTO_PHASE2",
    702: "UNDERBOSS_GOTO_PHASE3",
    703: "UNDERBOSS_GOTO_PHASE4",
    704: "UNDERBOSS_DEFEATED",
    705: "UNDERBOSS_JUMPS",
    706: "UNDERBOSS_JUMPS_FINAL_TIME",
    707: "UNDERBOSS_JUMPS_2ND_TIME",
    708: "UNDERBOSS_JUMPS_3RD_TIME",
    709: "UNDERBOSS_ESCAPE_PHASE1",
    710: "UNDERBOSS_ESCAPE_PHASE2",
    711: "UNDERBOSS_ESCAPE_PHASE3",
    712: "UNDERBOSS_PLATFORM_HIT",
    713: "UNDERBOSS_PLATFORM_HIT2",
    714: "UNDERBOSS_PLATFORM_HIT3",
    715: "UNDERBOSS_PLATFORM_HIT4",
}


# ----------------------------------------------------------------- achievements
ACHIEVEMENTS = {  # exe enum family ACHIEVEMENTS, registered in 0x80c150
    0: "STREETJUSTICE",
    1: "MORALLYSUPERIOR",
    2: "FRIENDSFOREVER",
    3: "TAGEM",
    4: "FOCUSFIRE",
    5: "ELECTRICEXPLOSION",
    6: "RRARARARGHGH",
    7: "MARTIALARTIST",
    8: "FERALFIGHTER",
    9: "PINGPONG",
    10: "UNENDINGCOMBO",
    11: "GENTLEMAN",
    12: "PSYCHO",
    13: "HERO",
    14: "TEAMWORK",
    15: "THIEF",
    16: "DETECTIVE",
    17: "UNTOUCHABLE",
    18: "TURBO",
    19: "VIGILANTE",
    20: "SHIELD",
    21: "STRONGARM",
    22: "RETALIATOR",
    23: "EXTERMINATOR",
}
# threshold property -> registered default (None: the class registers none)
ACHIEVEMENT_THRESHOLDS = {
    "AchievementPart2Ctrl": {
        "_itagem_requiredstomps": 10,
        "_itagem_timelimit": 10.0,
        "_ifocusfire_enemies": 10,
        "_ielectric_requiredenemies": 14,
        "_nrargh_seconds": 60.0,
        "_nmartial_timelimit": 60.0,
        "_ipingpong_requiredtargets": 4,
        "_iunending_requiredhits": 10,
        "_ngentleman_secondsbetweencombat": 20.0,
    },
    "AchievementCtrl": {
        "_nturbo_requiredtimetocompletegame": None,
        "_ivigilante_numenemieseliminated": None,
        "_ivigilante_inseconds": None,
        "_istrongarm_requiredknockeddownbythrow": None,
        "_iretaliator_requiredcounterattacks": None,
        "_iexterminator_requiredfinishingmoves": None,
        "_ishield_requiredblocksordodges": None,
    },
}
_ACHIEVEMENT_RULES = {
    "AchievementPart2Ctrl": {
        0: "game completed in mode 1 (Rorschach)",
        1: "game completed in mode 2 (Nite Owl)",
        2: "game completed in mode 3 (co-op)",
        3: "kills by the signed-in player of an enemy the other hero threw less than"
        " _itagem_timelimit (+5.0 s low violence) before",
        4: "_ifocusfire_enemies kills in a row; reset when the player damages a different"
        " enemy while a current one is set",
        5: "more than _ielectric_requiredenemies entries of the raw overlap list whose owner"
        " has the CharacterPhysics script",
        6: "rage lasted more than _nrargh_seconds of playing time when it ends",
        7: "8 distinct proper combos, the first 8 each done within _nmartial_timelimit;"
        " signed-in player is playable 1 (Nite Owl)",
        8: "the same, signed-in player is not playable 1 (Rorschach)",
        9: "a proper combo completes with >= _ipingpong_requiredtargets distinct enemies hit"
        " in the string",
        10: "a proper combo completes with hits + 1 >= _iunending_requiredhits",
        11: "at game completion the flag is still set and hits by character type 33 > 10"
        " (literal)",
    },
    "AchievementCtrl": {
        12: "game completed in mode 1 (Rorschach)",
        13: "game completed in mode 2 (Nite Owl)",
        14: "game completed in mode 3 (co-op)",
        15: "abilities 1-25 all unlocked, signed-in Rorschach",
        16: "abilities 1-25 all unlocked, signed-in Nite Owl",
        17: "level completed with no damage taken",
        18: "playing time below _nturbo_requiredtimetocompletegame at game completion",
        19: "_ivigilante_numenemieseliminated kills inside a sliding window of"
        " _ivigilante_inseconds",
        20: "_ishield_requiredblocksordodges dodges or blocks",
        21: "_istrongarm_requiredknockeddownbythrow enemies knocked over by a throw",
        22: "defect: a counter attack once _iretaliator_requiredcounterattacks dodges or blocks"
        " are saved",
        23: "defect: a finishing move once _iexterminator_requiredfinishingmoves dodges or"
        " blocks are saved",
    },
}


def achievements(nodes):
    """combat.achievements from the achievement controllers of the data.

    nodes: iterable of (fragment key, node).  One record per controller class found
    (Part 2: AchievementPart2Ctrl, Part 1: AchievementCtrl), with the thresholds its
    fragment stores (registered default where it stores none)."""
    out = {
        "evidence": "conditions read from code (PC executable); names are the exe enum family"
        " ACHIEVEMENTS (registered in 0x80c150), not UI captions; thresholds measured: the"
        " fragment's stored value, else the registered default",
        "names": {str(k): v for k, v in sorted(ACHIEVEMENTS.items())},
        "controllers": {},
        "defects": [
            "Part 1 RETALIATOR (22) and EXTERMINATOR (23) increment saved counters +0x10 /"
            " +0x14 but compare the dodge-or-block counter +0x18 with their threshold"
            " (0x59925d, 0x599222)",
            "ELECTRICEXPLOSION (5) tests the raw overlap entry against the playable list, so"
            " playable capsules are counted (inferred)",
        ],
        "turbo_clock": "playing time is set to 9999.0 on game event 5 and when a level is"
        " entered out of order; to 0 when level 1 is entered",
        "gate": "command_set_achievement_earned 0x599c3a: not in the tutorial, a user is"
        " signed in, achievements are initialised and the loaded progress belongs to that"
        " user; each award adds 8.0 s to the display timer",
    }
    for rel, n in nodes:
        props = ACHIEVEMENT_THRESHOLDS.get(n.cls)
        if props is None or n.cls in out["controllers"]:
            continue
        th, src = {}, {}
        for prop, default in props.items():
            v = n.p(prop)
            if v is not None:
                th[prop], src[prop] = v, "fragment"
            elif default is not None:
                th[prop], src[prop] = default, "registered default"
            else:
                th[prop], src[prop] = None, "not stored; the class registers no default"
        out["controllers"][n.cls] = {
            "fragment": rel,
            "thresholds": th,
            "threshold_source": src,
            "conditions": {
                str(i): {"name": ACHIEVEMENTS[i], "condition": text}
                for i, text in sorted(_ACHIEVEMENT_RULES[n.cls].items())
            },
        }
    return out


def override_damage_events(states):
    """The IMPACT_EFFECTS events that deal close-combat damage themselves: with m_ttruth1
    the event calls SetCloseCombatDamageToTarget(victim, state, m_nvalue) (0x6ae57f);
    m_nvalue > 0 overrides the state's default damage.  states: {class: [(node, record)]}."""
    out = []
    for cn, recs in sorted(states.items()):
        for _node, rec in recs:
            for e in rec.get("events") or []:
                if e.get("event_id") == EV_IMPACT_EFFECTS and e.get("m_ttruth1"):
                    out.append(
                        {
                            "class": cn,
                            "state": rec["path"],
                            "time_s": e.get("play_time_s"),
                            "override_damage": e.get("value"),
                        }
                    )
    return out


# ------------------------------------------------------------------- criteria
def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _g(x):
    return "%g" % round(x, 6) if isinstance(x, float) else str(x)


def render_criterion(k):
    """Text of one criterion from its STORED values (AnimationCriteriaMet
    0x5c5781 says which properties each kind reads).  The node caption is used
    only for kinds without values of their own."""
    kind = k.p("m_ianimationcriteria") or 0
    if kind == asm.CRIT_VALUE:
        v = k.p("m_ianimationvalue") or 0
        var = ee.name("ANIMATION_VALUE", v, "VALUE_%s" % v)
        t = k.p("m_iintervaltype") or 0
        lo, hi = k.p("m_nintervalmin"), k.p("m_nintervalmax")
        if t == 0:
            s = "%s in [%s;%s[" % (var, _g(lo), _g(hi))
        elif t == 1:
            s = "%s < %s" % (var, _g(hi))
        elif t == 2:
            s = "%s >= %s" % (var, _g(lo))
        else:
            s = "%s interval type %s" % (var, t)
    elif kind == asm.CRIT_ACTION:
        a = k.p("m_ianimationaction") or 0
        s = "ACTION " + ee.name("CONTROL_ACTION_TYPES", a, "ACTION_%s" % a)
    elif kind == asm.CRIT_ENUM:
        var = k.p("m_ianimationenum") or 0
        val = ee.signed(k.p("m_ianimationenumvalue") or 0)
        fam = ee.enum_variable_family(var)
        if var == VAR_TARGET_MODE:
            nm = TARGET_MODE.get(val, "VALUE_%s" % val)
        else:
            nm = ee.name(fam, val, "VALUE_%s" % val) if fam else "VALUE_%s" % val
        s = "%s = %s" % (ee.name("ANIMATION_ENUM", var, "ENUM_%s" % var), nm)
    elif kind in (asm.CRIT_ANY_OF, asm.CRIT_ALL_OF):
        kids = [render_criterion(x) for x in k.children if x.cls == asm.CLS_CRIT]
        s = ("ANY OF(" if kind == asm.CRIT_ANY_OF else "ALL OF(") + " | ".join(kids) + ")"
    else:
        s = (k.name or "").strip("{}").strip()
        s = s[len("criteria: ") :] if s.startswith("criteria: ") else s
        if s.startswith("NOT ") and k.p("m_tnot"):
            s = s[4:]
    if k.p("m_tnot"):
        s = "NOT " + s
    return s


def _crit_rows(nodes):
    out = []
    for k in nodes:
        if k.p("enabled", True) is False:
            continue
        row = {"text": render_criterion(k)}
        if k.p("m_tentryonly"):
            row["entry_only"] = True
        out.append(row)
    return out


def _path(n):
    p = []
    while n is not None:
        if n.cls in (asm.CLS_GROUP, asm.CLS_STATE, asm.CLS_CLASS) or n.name == "SlaveStates":
            p.append(n.name)
        n = n.parent
    return "/".join(reversed(p))


def groups_of(node):
    """The state groups enclosing a state, OUTERMOST first."""
    out, n = [], node.parent
    while n is not None:
        if n.cls == asm.CLS_GROUP:
            out.append(n)
        n = n.parent
    return out[::-1]


def group_criteria(node):
    """[{group, random_pick, criteria: [{text, entry_only?}]}] outermost first.
    random_pick: the group picks at random among its members whose criteria
    hold (`_trandomizetransitiontostate`, GetValidState).  Groups that neither
    test anything nor pick at random are left out (the state's path names them)."""
    out = []
    for g in groups_of(node):
        rows, rnd = _crit_rows(asm.criteria_of(g)), bool(g.p(asm.RANDOM_STATE))
        if rows or rnd:
            out.append({"group": _path(g), "random_pick": rnd, "criteria": rows})
    return out


def _chain(node):
    """Every enabled criterion that gates a state: its groups', then its own."""
    out = []
    for g in groups_of(node):
        out += asm.criteria_of(g)
    out += asm.criteria_of(node)
    return [k for k in out if k.p("enabled", True) is not False]


def _leaves(k, neg=False, alt=False):
    """(leaf, negated, inside an ANY_OF) for criterion k and its children."""
    kind = k.p("m_ianimationcriteria") or 0
    neg = neg != bool(k.p("m_tnot"))
    if kind in (asm.CRIT_ANY_OF, asm.CRIT_ALL_OF):
        # NOT ALL OF(...) is an alternative too (De Morgan)
        inner = alt or (kind == asm.CRIT_ANY_OF) != neg
        for x in k.children:
            if x.cls == asm.CLS_CRIT and x.p("enabled", True) is not False:
                for row in _leaves(x, neg, inner):
                    yield row
    else:
        yield k, neg, alt


def chain_actions(node):
    """Control action ids the state's criteria chain asks for (not negated)."""
    out = []
    for k in _chain(node):
        for leaf, neg, _alt in _leaves(k):
            if (leaf.p("m_ianimationcriteria") or 0) == asm.CRIT_ACTION and not neg:
                a = leaf.p("m_ianimationaction") or 0
                if a not in out:
                    out.append(a)
    return out


def chain_interval(node, value_id):
    """[lo, hi] the chain's unconditional VALUE criteria leave for an animation
    value (None = unbounded); criteria inside an ANY OF are not counted."""
    lo = hi = None
    for k in _chain(node):
        for leaf, neg, alt in _leaves(k):
            if (leaf.p("m_ianimationcriteria") or 0) != asm.CRIT_VALUE or neg or alt:
                continue
            if (leaf.p("m_ianimationvalue") or 0) != value_id:
                continue
            t = leaf.p("m_iintervaltype") or 0
            a, b = _num(leaf.p("m_nintervalmin")), _num(leaf.p("m_nintervalmax"))
            if t in (0, 2) and a is not None:
                lo = a if lo is None else max(lo, a)
            if t in (0, 1) and b is not None:
                hi = b if hi is None else min(hi, b)
    return [lo, hi]


def chain_enum(node, var):
    """(required values, excluded values) of an enum variable over the chain's
    unconditional ENUM criteria."""
    req, exc = [], []
    for k in _chain(node):
        for leaf, neg, alt in _leaves(k):
            if (leaf.p("m_ianimationcriteria") or 0) != asm.CRIT_ENUM or alt:
                continue
            if (leaf.p("m_ianimationenum") or 0) != var:
                continue
            v = ee.signed(leaf.p("m_ianimationenumvalue") or 0)
            (exc if neg else req).append(v)
    return sorted(set(req)), sorted(set(exc))


def allowed_enum(node, var, am):
    """Names of the values of `var` the chain leaves possible, or None when no
    criterion tests it (anim_meta.allowed_enum_names: full criteria logic)."""
    return am.allowed_enum_names(node, var)


# ------------------------------------------------------------------ fragments
_TOKENS = (
    b"CharacterDef",
    b"CharacterComboDatabase",
    b"CharacterSpecialDef",
    b"WeaponBase",
    b"EnemyDef",
    b"PartnerDef",
    b"UnderbossDef",
    b"CharacterVisualDef",
    b"AchievementCtrl",
    b"AchievementPart2Ctrl",
)
_AI_DEF_CLASSES = ("EnemyDef", "PartnerDef", "UnderbossDef", "AiDef")


class CombatData:
    """The combat definitions of one EXTRACT_OUT: combo databases, the special
    definition, CharacterDefs, AI definitions and weapons, with the references
    between them resolved (sound_meta.SoundDB.resolve: [stem hash, node id])."""

    def __init__(self, extract_out, log=None):
        import sound_meta

        self.db = sound_meta.SoundDB(extract_out, log)
        self.extract_out = extract_out
        self.combo_databases = {}
        self.special_def = None
        self.character_defs = []
        self.ai_defs = []
        self.weapons = []
        self.visual_def = None  # the ragdoll-impact numbers of the CharacterVisualDef
        self.underboss_defs = []  # per UnderbossDef: thresholds and phases (rules.underboss)
        self.achievements = None  # combat.achievements (the achievement controllers)
        self._string_names = {}  # id(node) -> (database, label)
        self._load()

    def _fragments(self):
        out = []
        for path, rel in sorted(self.db.files().values(), key=lambda x: x[1]):
            try:
                with open(path if os.path.exists(path) else path + ".json", "rb") as fh:
                    b = fh.read()
            except OSError:
                continue
            if any(t in b for t in _TOKENS):
                out.append(rel)
        return out

    def _load(self):
        frags = self._fragments()
        nodes = [(rel, n) for rel in frags for n in self.db.nodes(rel).values()]
        nodes.sort(key=lambda x: (x[0], x[1].p("siblingOrder", 0) or 0, str(x[1].id)))
        for rel, n in nodes:
            if n.cls == "CharacterComboDatabase":
                self.combo_databases.setdefault(_strip(n.name), self._combo_db(rel, n))
            elif n.cls == "CharacterSpecialDef" and self.special_def is None:
                self.special_def = dict(
                    {
                        k: v
                        for k, v in sorted(n.props.items())
                        if k.startswith("m_") and isinstance(v, (int, float))
                    },
                    fragment=rel,
                )
            elif n.cls == "CharacterVisualDef" and self.visual_def is None:
                self.visual_def = dict(
                    {k: n.p(k) for k in VISUAL_DEF_READ + VISUAL_DEF_UNREAD}, fragment=rel
                )
        for rel, n in nodes:
            if n.cls == "CharacterDef":
                self.character_defs.append(self._character_def(rel, n))
            elif n.cls == "WeaponBase":
                self.weapons.append(self._weapon(rel, n))
        for rel, n in nodes:
            if n.cls in _AI_DEF_CLASSES:
                self.ai_defs.append(self._ai_def(rel, n))
        ach = achievements(nodes)
        if ach["controllers"]:
            self.achievements = ach

    # ------------------------------------------------------------ combos
    def _combo_db(self, rel, n):
        strings = []
        for s in n.children:
            if s.cls != "CharacterComboString":
                continue
            items = []
            for i in s.children:
                if i.cls != "CharacterComboItem":
                    continue
                item = i.p("m_icomboitem") or 0
                st = ee.signed(i.p("m_itargetstatus") or 0)
                row = {
                    "item": CHARACTER_COMBO_ITEMS.get(item, "ITEM_%s" % item),
                    "item_id": item,
                    "target_status": _status_names(st),
                    "target_status_mask": st,
                }
                if item in _ITEM_ATTACK:
                    row["button"], row["weapon_class"] = _ITEM_ATTACK[item]
                items.append(row)
            ov = s.p("m_iforcespecialanimation") or 0
            ability = ee.signed(s.p("_iability") or 0)
            rec = {
                "label": _strip(s.name),
                "enabled": bool(s.p("enabled", True)),
                "items": items,
                "bonus_damage": s.p("m_ndamage") or 0.0,
                "stun_s": s.p("m_nstunduration") or 0.0,
                "pushback_velocity": s.p("m_npushbackvel") or 0.0,
                "pushback_time_s": s.p("m_npushbacktime") or 0.0,
                "override": (
                    ee.name("OVERRIDE_ATTACK_COMBO", ov, "OVERRIDE_%s" % ov) if ov else None
                ),
                "override_id": ov,
                "terminate": bool(s.p("m_tterminatecombo")),
                "uninterruptable": bool(s.p("m_tuninterruptable")),
                "proper_combo": bool(s.p("m_tpropercombo")),
                "ability_id": ability,
                "available_from_start": bool(s.p("_tavailablefromstart")),
            }
            strings.append(rec)
            self._string_names[id(s)] = (_strip(n.name), rec["label"])
        base = {}
        for (button, wpn), prop in BASE_DAMAGE_PROP.items():
            base.setdefault(button, {})[wpn] = n.p(prop)
        db = {
            "fragment": rel,
            "base_damage": base,
            "base_damage_props": {
                "%s %s" % k: v for k, v in sorted(BASE_DAMAGE_PROP.items(), key=lambda kv: kv[1])
            },
            "counter_damage": n.p("m_ndefaultdamagecounterattack"),
            "throw_damage": n.p("m_ndefaultdamagethrow"),
            # no reader of the property in the game (rules.ragdoll_damage)
            "throw_damage_used": False,
            "strings": strings,
        }
        for rec in strings:
            _step_overrides(rec, strings)
        return db

    # ------------------------------------------------------- definitions
    def _named(self, ref, rel):
        hit = self.db.resolve(ref, rel)
        return (hit[0], hit[1]) if hit else (None, None)

    def _character_def(self, rel, n):
        P = n.p
        ct = ee.signed(P("m_icharactertype") or 0)
        _f, combo = self._named(P("m_ecombosetup"), rel)
        _f, model = self._named(P("m_emodelfragment"), rel)
        visual = model.p("assetName") if model is not None else None
        colls = {}
        for key, prop in (("BASH_1H", "m_emodelcollbash1h"), ("BASH_2H", "m_emodelcollbash2h")):
            _f, c = self._named(P(prop), rel)
            colls[key] = _strip(c.name) if c is not None else None
        return {
            "fragment": rel,
            "name": _strip(n.name),
            "character_type": ee.name("CHARACTER_TYPES", ct, "CHARACTER_TYPE_%s" % ct),
            "character_type_id": ct,
            "playable": ee.signed(P("m_iplayablecharacter") or 0) >= 0
            and P("m_iplayablecharacter") is not None,
            "max_health": P("m_nmaxhealth"),
            "critical_health": P("m_ncriticalhealth"),
            "finish_icon_time_s": P("m_nfinishicontime"),
            "health_regen_per_s": P("m_nhealthregen"),
            "low_health_point": P("m_nlowintervalpos"),
            "low_health_regen_per_s": P("m_nhealthregenlow"),
            "regen_hit_delay_s": P("m_nregenhitdelay"),
            "damage_modifier": P("_ndamagemodifier"),
            "combo_database": _strip(combo.name) if combo is not None else None,
            "weapon_collections": colls,
            "visual_fragment": visual.lstrip("/") if isinstance(visual, str) else None,
            "animation_class": None,  # filled by link_classes()
            "head_attack_distance": P("m_nheadattackdistance"),
            "body_attack_distance": P("m_nbodyattackdistance"),
            "dodge_angle_rad": P("m_ndodgeangle"),
            "weapon_pickup_range": P("m_nweaponpickuprange"),
        }

    def _ai_def(self, rel, n):
        P = n.p
        parent = n.parent
        while parent is not None and parent.cls != "CharacterDef":
            parent = parent.parent
        dt = P("m_ideftype") or 0
        at = ee.signed(P("m_iaitype") or 0)
        rec = {
            "fragment": rel,
            "class": n.cls,
            "name": _strip(n.name),
            "character_def": _strip(parent.name) if parent is not None else None,
            "def_type": AI_DEF_TYPE.get(dt, "DEF_TYPE_%s" % dt),
            "ai_type": ee.name("CHARACTER_TYPES", at, "CHARACTER_TYPE_%s" % at),
        }
        # EnemyDef reads _ndamagemodifier (0x71f0cf; its m_ndamagemodifier is
        # overwritten at run time), the other classes m_ndamagemodifier (0x597273)
        own = P("_ndamagemodifier") if n.cls == "EnemyDef" else P("m_ndamagemodifier")
        rec["damage_modifier_own"] = own
        rec["damage_modifier_prop"] = (
            "_ndamagemodifier" if n.cls == "EnemyDef" else "m_ndamagemodifier"
        )
        # every getter (0x71f0cf, 0x597273, 0x8841f3) returns its own member when it
        # is not 0, else the CharacterDef's (command_get_default_damage_modifier)
        base = parent.p("_ndamagemodifier") if parent is not None else None
        if own:
            eff, src = own, "own (%s)" % rec["damage_modifier_prop"]
        elif base is not None:
            eff, src = base, "CharacterDef._ndamagemodifier (own value is %s)" % (
                "0" if own is not None else "absent"
            )
        else:
            eff, src = None, "not established: own value is 0 or absent and no CharacterDef"
        rec["damage_modifier_effective"] = eff
        rec["damage_modifier_source"] = src
        for key, prop in _AI_PROPS:
            if P(prop) is not None:
                rec[key] = P(prop)
        _f, odb = self._named(P("m_eoverridecombodatabase"), rel)
        rec["override_combo_database"] = _strip(odb.name) if odb is not None else None
        rec["reaction_rows"] = reaction_rows(n)
        combos = []
        for prefix, freq in (("m_ecomboattack", "m_ifreqofcomboattack"),):
            for i in range(1, 10):
                _f, s = self._named(P("%s%d" % (prefix, i)), rel)
                if s is not None and id(s) in self._string_names:
                    dbn, label = self._string_names[id(s)]
                    combos.append(
                        {"database": dbn, "combo": label, "weight": P("%s%d" % (freq, i))}
                    )
        crowd = []
        for i in range(1, 10):
            _f, s = self._named(P("m_ecrowdctrlcomboattack%d" % i), rel)
            if s is not None and id(s) in self._string_names:
                dbn, label = self._string_names[id(s)]
                crowd.append(
                    {
                        "database": dbn,
                        "combo": label,
                        "weight": P("m_ifreqofcrowdctrlcomboattack%d" % i),
                    }
                )
        rec["combos"] = combos
        if crowd:
            rec["crowd_control_combos"] = crowd
        if n.cls == "UnderbossDef":
            ph = underboss_phases(
                P("m_nhealthfractiongotonextphase"),
                P("m_nhealthfraction1gotonextphase"),
                P("m_nhealthfraction2gotonextphase"),
                P("m_istepsinphase4"),
            )
            ub = {
                "name": rec["name"],
                "fragment": rel,
                "character_def": rec["character_def"],
                "max_health": parent.p("m_nmaxhealth") if parent is not None else None,
                "own_max_health_unread": P("m_nmaxhealth"),
                "enemy_engagement_dist": P("m_nenemyengagementdist"),
                "flamer_damage": P("m_iflamerdamage"),
                "steps_in_phase_4": P("m_istepsinphase4"),
                "damage_modifier_own": P("_ndamagemodifier"),
            }
            if ph:
                ub.update(ph)
            self.underboss_defs.append(ub)
        return rec

    def _weapon(self, rel, n):
        loss = n.p("m_ndurebilitylossperhit")
        t = ee.signed(n.p("m_iweapontype") or 0)
        rec = {
            "fragment": rel,
            "collection": _strip(n.parent.name) if n.parent is not None else None,
            "weapon_class": ee.name("WEAPON_TYPES", t, "WEAPON_TYPE_%s" % t),
            "player_one_handed": bool(n.p("m_tplayeronehanded")),
            "durability_loss_per_hit": loss,
            "disable_at_break": bool(n.p("m_tdisableatbreak")),
            "priority": n.p("m_iprioritymodel"),
        }
        if loss:
            # durability starts at 1.0 (registry default) and a landed hit takes
            # loss off (WeaponBase.command_take_durability_damage 0x8b33e0)
            hits, left = 0, 1.0
            while left > 0.0 and hits < 1000:
                left -= float(loss)
                hits += 1
            rec["hits_to_break"] = hits
        return rec

    # -------------------------------------------------------------- joins
    def modifier(self, ai, cdef):
        own = ai.get("damage_modifier_own") if ai else None
        return own if own else (cdef or {}).get("damage_modifier")

    def owners(self, class_name):
        """CharacterDefs that use an animation class, one per name (the head
        fragments each repeat the same BIKER_HEAD definition)."""
        out, seen = [], set()
        for d in self.character_defs:
            if d["animation_class"] == class_name and d["name"] not in seen:
                seen.add(d["name"])
                out.append(d)
        return out

    def ai_defs_of(self, cdef):
        return [
            a
            for a in self.ai_defs
            if a["character_def"] == cdef["name"] and a["fragment"] == cdef["fragment"]
        ]

    def database_of(self, cdef, ai=None):
        name = (ai or {}).get("override_combo_database") or cdef.get("combo_database")
        return name, self.combo_databases.get(name)


_AI_PROPS = (
    ("attack_distance", "m_nattackdistance"),
    ("minimum_distance", "m_nminimumdistance"),
    ("time_between_attacks_min_s", "m_ntimebetweenattacks_min"),
    ("time_between_attacks_max_s", "m_ntimebetweenattacks_max"),
    ("prob_fast_attack", "m_nproboffastatt"),
    ("prob_slow_attack", "m_nprobofslowatt"),
    ("prob_combo_attack", "m_nprobofcomboatt"),
    ("prob_block_throw", "m_nprobblockthrow"),
    ("prob_dodge_throw", "m_nprobdodgethrow"),
    ("reaction_decay_time_s", "m_nreactiontoattackdecaytime"),
    ("clear_if_block_dodge_is_broken", "m_tclearifblockdodgeisbroken"),
    ("never_do_random_combos", "m_tneverdorandomcombos"),
    ("speed_up_combos", "m_tspeedupcombos"),
    ("disable_health_regen", "m_tdisablehealthregen"),
    # PartnerDef (visual_range and allowed_speed_change_per_s also on EnemyDef / UnderbossDef);
    # how the partner behaviours use them: rules.partner_ai
    ("visual_range", "m_nvisualrange"),
    ("time_between_attacks_low_health_min_s", "m_ntimebetweenattackslowhealth_min"),
    ("time_between_attacks_low_health_max_s", "m_ntimebetweenattackslowhealth_max"),
    ("help_speak_time_s", "m_nhelpspeaktime"),
    ("allowed_speed_change_per_s", "m_nallowedspeedchange"),
    ("follow_stop_distance", "m_nfollowpartnerstopdistance"),
    ("follow_min_distance_to_partner", "m_nfollowpartnerminimumdistancetopartner"),
    ("follow_match_speed_distance", "m_nfollowpartnermatchspeeddistance"),
    ("follow_closest_distance", "m_nfollowpartnerstopdistancebetweentargetandpartner"),
    ("follow_side_distance", "m_nfollowpartnermovedistancebetweentargetandpartner"),
    ("kill_vs_crowd_control", "m_nkillvscrowdcontrol"),
    ("behavior_change_time_s", "m_ncombatanalyzerbehaviorchangetime"),
    ("crowd_special_cooldown_min_s", "m_ncrowdcontrolspecialattackcooldown_min"),
    ("crowd_special_cooldown_max_s", "m_ncrowdcontrolspecialattackcooldown_max"),
    ("crowd_num_enemy_modifier", "m_ncrowdcontrolnumofenemymodifier"),
    ("prob_react_to_attack", "m_ncrowdcontrolprobofreactatt"),
    ("prob_counter_attack", "m_ncrowdcontrolprobofcounteratt"),
    ("prob_dodge", "m_ncrowdcontrolprobofdodge"),
    ("prob_block", "m_ncrowdcontrolprobofblock"),
    ("prob_rorschach_charge", "m_nprobablityrorschachcharge"),
    ("prob_niteowl_electrify", "m_nprobabilityniteowlelectrify"),
    ("prob_niteowl_stun", "m_nprobabilityniteowlstun"),
    ("prob_crowd_combo_attack", "m_nprobofcrowdcomboatt"),
    ("kill_special_cooldown_min_s", "m_nattackkillspecialattackcooldown_min"),
    ("kill_special_cooldown_max_s", "m_nattackkillspecialattackcooldown_max"),
    ("disallow_help_partner", "m_tdisallowhelppartnerstate"),
)


def _strip(s):
    s = s or ""
    return s[1:-1].strip() if s.startswith("{") and s.endswith("}") else s.strip()


def _status_names(mask):
    if mask == -1:
        return ["ANY"]
    out = [nm for bit, nm in sorted(CHARACTER_COMBO_ENEMY_STATUS.items()) if bit > 0 and mask & bit]
    return out or ["NONE"]


def _step_overrides(rec, strings):
    """Per item of a string: the override in effect when that item is pressed,
    i.e. the override of the longest enabled string that equals the tail of the
    presses so far (get_longest_valid_combo 0x66cd98).  Another string counts
    only when a target in DEFAULT status satisfies it (CompareComboItems
    0x664d43: item equal and status mask & target flags); the string itself is
    taken as satisfied."""
    ids = [i["item_id"] for i in rec["items"]]
    for n, item in enumerate(rec["items"]):
        seq, best = ids[: n + 1], None
        for s in strings:
            other = [i["item_id"] for i in s["items"]]
            if not s["enabled"] or not other or len(other) > len(seq):
                continue
            if s is not rec and not all(
                i["target_status_mask"] == -1 or i["target_status_mask"] & 16 for i in s["items"]
            ):
                continue
            if s is rec:
                continue
            if seq[len(seq) - len(other) :] == other and (
                best is None or len(other) > len(best["items"])
            ):
                best = s
        if n == len(ids) - 1:
            best = rec  # the string itself completes here
        item["override_in_effect"] = best["override"] if best else None
        item["completes"] = best["label"] if best else None


# ---------------------------------------------------------- reaction table
def reaction_rows(n):
    """The defensive reaction rows of an AI definition, as the engine builds
    them (EnemyDef.command_initialize_DRS 0x71f146: a slot counts only when its
    first attack and its result are set; a row ends at the first empty entry)."""
    rows = []
    for i in range(1, 9):
        if n.p("m_idrs%02dresult" % i) is None and n.p("m_idrs%02dattack01" % i) is None:
            continue
        att = [n.p("m_idrs%02dattack%02d" % (i, j)) or 0 for j in range(1, 9)]
        res = n.p("m_idrs%02dresult" % i) or 0
        if not att[0] or not res:
            continue
        seq = []
        for a in att:
            if not a:
                break
            seq.append(a)
        rows.append(
            {
                "row": i,
                "newest_first": [ee.name("ANIMATION_TYPE", a, "TYPE_%s" % a) for a in seq],
                "newest_first_ids": seq,
                "result": ee.name("ANIMATION_TYPE", res, "TYPE_%s" % res),
                "result_id": res,
                "clear_history": bool(n.p("m_tdrs%02dshouldclear" % i)),
            }
        )
    return rows


def react(rows, history):
    """The reaction to the newest attack (Enemy.command_react_to_attack
    0x721958).  history: animation type ids, NEWEST first, of the attacks
    remembered (at most 9).  Returns the matching row or None; deterministic."""
    hist = [h for h in list(history)[:9]]
    for row in rows:
        seq = row["newest_first_ids"]
        if len(seq) > len(hist) or any(not h for h in hist[: len(seq)]):
            continue
        if all(s == AT_ANY or s == h for s, h in zip(seq, hist)):
            return row
    return None


# ------------------------------------------------------------------ linking
def class_ids(classes):
    """{class name: AnimationClass id} (the id a CharVisual's AnimationCtrlWM
    names; face_rule uses the same link)."""
    import face_rule

    out = {}
    for cn, c in classes.items():
        root = asm.find_class_root([n for n in c["nodes"] if n.parent is None])
        cid = root.p("m_iclassid") if root is not None else None
        if cid is None:
            cid = face_rule._class_id_by_name(cn)
        out[cn] = cid
    return out


def link_classes(data, classes, extract_out):
    """Sets CharacterDef.animation_class: CharacterDef.m_emodelfragment -> the
    FragmentNode of CharacterVisual.fragment -> the *CharVisual fragment -> its
    body AnimationCtrlWM.m_ianimationclassid -> the AnimationClass of that id."""
    import face_rule

    ids = class_ids(classes)
    by_id = {}
    for cn, cid in sorted(ids.items()):
        if cid is not None:
            by_id.setdefault(cid, cn)
    visual = {}
    for row in face_rule.charvisual_table(extract_out):
        key = row["fragment"].replace(os.sep, "/").lower()
        key = key[len("extracted/") :] if key.startswith("extracted/") else key
        visual[key] = by_id.get(row["body_class_id"])
    for d in data.character_defs:
        v = (d.get("visual_fragment") or "").lower()
        d["animation_class"] = visual.get(v)
    return ids


# -------------------------------------------------------------- state blocks
def _event(rec, eid):
    """The first firing record of an event of a state record (anim_meta._events
    did the timing: start position, slot speed, looping)."""
    best = None
    for e in rec.get("events") or []:
        if e.get("event_id") != eid:
            continue
        if best is None or (e.get("playpos") or 0.0) < (best.get("playpos") or 0.0):
            best = e
    return best


def _timing(e):
    if e is None:
        return None
    return {
        "playpos": e.get("playpos"),
        "clip_time_s": e.get("time_s"),
        "from_entry_s": e.get("play_time_s"),
    }


def _from_entry(playpos, rec):
    """Seconds after state entry at which the state reaches `playpos`
    (asm.event_timing, PLAY_POS rule) -- None when unknown or not reached."""
    dur = rec.get("duration_s")
    if playpos is None or not dur:
        return None
    start = float(rec.get("start_playpos") or 0.0)
    _pp, _ts, pt = asm.event_timing(
        asm.EV_PLAY_POS, playpos, dur, rec.get("speed") or 1.0, start, bool(rec.get("loop"))
    )
    return None if pt is None else round(pt, 4)


def state_flags(node):
    """The set truth flags of a state.  upper_attack and heavy_attack are computed as
    AnimationStateWM.initialize_external 0x5f0e63 writes them (the stored
    m_tupperattack / m_theavyattack are false in all shipped data)."""
    out = {key: True for key, prop in STATE_FLAGS if node.p(prop)}
    if ee.signed(node.p("m_idamagepose") or 0) in asm.UPPER_DAMAGE_POSES:
        out["upper_attack"] = True  # m_tupperattack, written at 0x5f0e63
    if ACT_HEAVY_PUNCH in asm.own_and_group_actions(node):
        out["heavy_attack"] = True  # m_theavyattack, written at 0x5f0e63
    return out


_KIND_BY_TYPE = {
    AT_COUNTER: "counter",
    AT_FINISH: "finisher",
    AT_THROW: "throw",
    AT_BULLMOVE: "bull_rush",
    AT_DODGE: "dodge",
    AT_BLOCK: "block",
    AT_DAMAGE: "hit_reaction",
    AT_STUNNED: "stunned",
    15: "special",
    16: "special",
    19: "special",
}


def state_kind(node):
    if node.p("m_tisattackstate"):
        return "attack"
    if (node.p("m_ispecialhandling") or 0) == SP_RESEND_PUNCH:
        return "rush"
    return _KIND_BY_TYPE.get(asm.determine_animation_type(node))


def attack_class(node):
    """(light / heavy / None, source): the control action the state's groups
    ask for (PUNCH = fast attack, HEAVY_PUNCH = heavy attack)."""
    acts = chain_actions(node)
    if ACT_PUNCH in acts and ACT_HEAVY_PUNCH not in acts:
        return "light", "criterion ACTION PUNCH"
    if ACT_HEAVY_PUNCH in acts and ACT_PUNCH not in acts:
        return "heavy", "criterion ACTION HEAVY_PUNCH"
    names = [ee.name("CONTROL_ACTION_TYPES", a, "ACTION_%s" % a) for a in acts]
    return None, "no PUNCH / HEAVY_PUNCH criterion (actions: %s)" % (", ".join(names) or "none")


def entry_kind(node):
    acts = chain_actions(node)
    ini, dash = ACT_INITIAL in acts, ACT_AFTER_DASH in acts
    return (
        "initial_or_dash" if ini and dash else "initial" if ini else "dash" if dash else "general"
    )


def combo_speedup(node, rec):
    """Where a combo continuation enters the state (rules.combo.speedup)."""
    at = asm.determine_animation_type(node)
    lead = {AT_LIGHT: SPEEDUP_LIGHT_S, AT_HEAVY: SPEEDUP_HEAVY_S}.get(at)
    if node.p("m_timmunetocombospeedup"):
        return {"applies": False, "reason": "state is immune_to_combo_speedup"}
    if lead is None:
        return {
            "applies": False,
            "reason": "animation type %s is neither LIGHTATTACK nor HEAVYATTACK"
            % ee.name("ANIMATION_TYPE", at, at),
        }
    cdz, dur = _event(rec, EV_CLEAR_DEADZONE), rec.get("duration_s")
    if cdz is None or not cdz.get("playpos") or not dur:
        return {"applies": False, "reason": "no CLEAR_DEADZONE event or clip duration"}
    pp = cdz["playpos"] - lead / dur
    if pp <= 0.0:
        return {"applies": False, "reason": "CLEAR_DEADZONE is within the lead of the clip start"}
    out = {"applies": True, "lead_s": lead, "entry_playpos": round(pp, 4)}
    speed = rec.get("speed") or 1.0
    for key, eid in (("impact_from_entry_s", EV_IMPACT), ("branch_from_entry_s", EV_BRANCH)):
        e = _event(rec, eid)
        if e is not None and e.get("playpos") is not None and e["playpos"] > pp:
            out[key] = round((e["playpos"] - pp) * dur / speed, 4)
    return out


def _damage_rows(data, class_name, button, weapons):
    """Base damage x modifier per owning CharacterDef and weapon class."""
    rows = []
    for d in data.owners(class_name):
        ais = data.ai_defs_of(d)
        dbs = sorted({data.database_of(d, a)[0] for a in ais} | {d["combo_database"]} - {None})
        for dbn in dbs:
            db = data.combo_databases.get(dbn)
            if db is None:
                continue
            users = [a for a in ais if data.database_of(d, a)[0] == dbn]
            if not users and dbn != d["combo_database"]:
                continue
            for w in weapons:
                if w != "UNARMED" and not d["weapon_collections"].get(w) and not d["playable"]:
                    continue  # the character has no weapon models of that class
                base = db["base_damage"].get(button, {}).get(w)
                if base is None:
                    continue
                mods = {}
                for a in users:
                    m = data.modifier(a, d)
                    mods.setdefault(m, []).append(a["name"])
                if not users:
                    mods[d["damage_modifier"]] = []
                row = {
                    "character_def": d["name"],
                    "combo_database": dbn,
                    "weapon_class": w,
                    "base": base,
                    "base_source": BASE_DAMAGE_PROP[(button, w)],
                    "variants": [
                        {
                            "modifier": m,
                            "damage": None if m is None else round(base * m, 4),
                            "ai_defs": names,
                        }
                        for m, names in sorted(mods.items(), key=lambda kv: (kv[0] or 0.0))
                    ],
                }
                rows.append(row)
    return rows


def state_combat(node, rec, ctx, am):
    """The `combat` block of one state, or None when it has no combat role."""
    kind = state_kind(node)
    flags = state_flags(node)
    if kind is None and not flags:
        return None
    out = {"kind": kind or "other"}
    if flags:
        out["flags"] = flags
    if (node.p("m_ispecialhandling") or 0) == SP_BULL_MOVE:
        # what the value does: combat.rules.special_handling.BULL_MOVE
        out["special_handling_rule"] = "BULL_MOVE"
    if kind == "attack":
        out.update(_attack_block(node, rec, ctx, am))
    elif kind in ("hit_reaction", "stunned"):
        poses = am.allowed_enum_names(node, VAR_DAMAGE_POSE, with_groups=False)
        if poses is not None:
            out["damage_poses"] = poses
        for key, eid in (
            ("clear_deadzone", EV_CLEAR_DEADZONE),
            ("allow_attacks", EV_ALLOW_ATTACKS),
        ):
            t = _timing(_event(rec, eid))
            if t:
                out[key] = t
    elif kind in ("counter", "finisher", "throw", "bull_rush"):
        for key, eid in (
            ("impact", EV_IMPACT),
            ("kill_partner", EV_KILL_PARTNER),
            ("bullmove_impact", EV_BULLMOVE_IMPACT),
            ("allow_attacks", EV_ALLOW_ATTACKS),
        ):
            t = _timing(_event(rec, eid))
            if t:
                out[key] = t
    return out


def _attack_block(node, rec, ctx, am):
    P = node.p
    button, source = attack_class(node)
    out = {"attack_class": button, "attack_class_source": source}
    at = asm.determine_animation_type(node)
    out["animation_type"] = ee.name("ANIMATION_TYPE", at, "TYPE_%s" % at)
    weapons = allowed_enum(node, VAR_WEAPON, am)
    out["weapon_classes"] = weapons if weapons is not None else list(_WEAPON_CLASSES)
    if weapons is None:
        out["weapon_classes_basis"] = "no weapon criterion"
    out["entry"] = entry_kind(node)
    ov = allowed_enum(node, VAR_OVERRIDE, am)
    normal = ee.name("OVERRIDE_ATTACK_COMBO", 0, "NORMAL")
    out["combo_override"] = {
        "required": ov[0] if ov is not None and len(ov) == 1 and ov[0] != normal else None,
        "allowed": ov,
    }
    req, exc = chain_enum(node, VAR_TARGET_MODE)
    if req or exc:
        out["target_mode"] = {
            "requires": [TARGET_MODE.get(v, "VALUE_%s" % v) for v in req],
            "excludes": [TARGET_MODE.get(v, "VALUE_%s" % v) for v in exc],
        }
        if 4 in req:
            # AddAttackToCombo 0x68bca8: the base damage is set from the button,
            # then the combo item becomes KICK when the target is prone
            out["combo_item"] = "KICK"
    dist = chain_interval(node, VAL_ATTACK_MOVE_DIST)
    if dist != [None, None]:
        out["attack_move_dist_m"] = dist

    # timings: anim_meta's own event records (start position, slot speed)
    timing = {
        "start_playpos": rec.get("start_playpos") or 0.0,
        "duration_s": rec.get("duration_s"),
        "speed": rec.get("speed"),
    }
    for key, eid in (
        ("clear_deadzone", EV_CLEAR_DEADZONE),
        ("pre_impact", EV_PRE_IMPACT),
        ("impact", EV_IMPACT),
        ("branch", EV_BRANCH),
        ("can_go_to_movement", EV_CAN_MOVE),
    ):
        timing[key] = _timing(_event(rec, eid))
    out["timing"] = timing
    out["combo_speedup"] = combo_speedup(node, rec)

    d, mod = P("m_nimpactdistance") or 0.0, P("m_nimpactdistancemodification") or 0.0
    out["reach"] = {"impact_distance_m": d, "modification_m": mod, "total_m": round(d + mod, 6)}
    pose = P("m_idamagepose") or 0
    out["damage_pose"] = {
        "id": pose,
        "name": pose_name(pose),
        "class": pose_class(pose),
        "upper": pose in POSE_UPPER,
        "from_behind": pose_name(POSE_TO_BACK.get(pose, pose)),
    }
    if P("m_tallowsweepatt"):
        out["sweep"] = {p[3:]: P(p) for p in SWEEP_PROPS}

    # damage
    if button is None:
        out["damage"] = None
        out["damage_reason"] = "attack class not established: " + source
    else:
        rows = _damage_rows(ctx["data"], ctx["class"], button, out["weapon_classes"])
        out["damage"] = rows
        if not rows:
            out["damage_reason"] = (
                "no CharacterDef with a combo database is linked to this animation class"
            )

    # what the defender can do
    imp = _event(rec, EV_IMPACT)
    dur = rec.get("duration_s")
    counter = None
    if imp is not None and imp.get("playpos") is not None and dur:
        latest = imp["playpos"] - COUNTER_MARGIN_S / dur
        start = float(rec.get("start_playpos") or 0.0)
        counter = {
            "margin_s": COUNTER_MARGIN_S,
            "latest_playpos": round(latest, 4),
            "latest_from_entry_s": _from_entry(latest, rec) if latest > start else 0.0,
        }
    pre = _event(rec, EV_PRE_IMPACT)
    out["defender"] = {
        "counter": counter,
        "reaction_table_sees": (None if at == 0 else ee.name("ANIMATION_TYPE", at, "TYPE_%s" % at)),
        "hit_reaction_starts_from_entry_s": pre.get("play_time_s") if pre else None,
        "whiff_distance_m": ctx["whiff_m"],
        "whiff_basis": ctx["whiff_basis"],
        "cannot_be_broken_off": (P("m_ispecialhandling") or 0) == SP_IMMUNE_TO_BREAK,
    }
    return out


# -------------------------------------------------------------- pair trigger
RULE_ACTION = {
    "counter": ACT_COUNTER,
    "enemy_counter": ACT_COUNTER,
    "finisher": ACT_FINISH,
    "throw": ACT_THROW,
    "bull_rush": ACT_BULLMOVE,
}
RULE_TEXT = {
    "counter": "a hero fires COUNTER_ATTACK: combo [DODGE or BLOCK] + fast attack (override"
    " COUNTER_ATTACK, InitializeNextAttack 0x68bf6f), the counter button passing"
    " TestForCounterAttack 0x68d36a, or a forced counter; a player counter that would kill"
    " (target health <= counter damage) becomes a finisher",
    "enemy_counter": "the enemy's reaction table returns COUNTERATTACK when the hero enters"
    " an attack state (Enemy.command_react_to_attack 0x721958): delayed counter 0.15 s"
    " later (command_force_counter_attack 0x6867b7)",
    "finisher": "FINISHING_MOVE from the finisher prompt (PlayerCtrl.CheckFinishMove"
    " 0x7eff13 -> command_force_finishing_move 0x6866f9), from a counter that would kill,"
    " or from the forced finisher in versus",
    "throw": "the throw button when the grab succeeds (FireAttackBasedOnAttackID 0x68d870:"
    " the target may block with m_nprobblockthrow or dodge with m_nprobdodgethrow)",
    "bull_rush": "Rorschach's bull rush reaching its target",
}


def pair_rule(mnode, mrec, hero):
    """(rule, basis) of a pair from its master state: the control actions its
    criteria chain asks for, else the events it carries."""
    acts = chain_actions(mnode)
    if ACT_COUNTER in acts:
        return ("counter" if hero else "enemy_counter"), "criterion ACTION COUNTER_ATTACK"
    if ACT_FINISH in acts:
        return "finisher", "criterion ACTION FINISHING_MOVE"
    if ACT_THROW in acts:
        return "throw", "criterion ACTION THROW"
    if _event(mrec, EV_BULLMOVE_IMPACT) is not None:
        return "bull_rush", "event BULLMOVE_IMPACT"
    if _event(mrec, EV_KILL_PARTNER) is not None:
        return "finisher", "event KILL_ANIMATION_PARTNER"
    return None, "no action criterion and no damage event on the master"


def _amounts(data, class_name, key, factor=1.0):
    """Paired-move damage per owning CharacterDef of the master class."""
    rows = []
    for d in data.owners(class_name):
        ais = data.ai_defs_of(d)
        seen = {}
        for a in ais or [None]:
            dbn, db = data.database_of(d, a)
            base = (db or {}).get(key)
            if base is None:
                base = PAIR_BASE_DAMAGE
            m = data.modifier(a, d)
            if m is None:
                continue
            seen.setdefault((dbn, base, m), []).append(a["name"] if a else None)
        for (dbn, base, m), names in sorted(seen.items(), key=lambda kv: str(kv[0])):
            rows.append(
                {
                    "character_def": d["name"],
                    "combo_database": dbn,
                    "base": base,
                    "modifier": m,
                    "factor": factor,
                    "damage": round(base * m * factor, 4),
                    "ai_defs": [n for n in names if n],
                }
            )
    return rows


def pair_trigger(p, mnode, mrec, prec, ctx, am):
    data = ctx["data"]
    hero = ctx["playable"].get(p["master_class"], False)
    victim_playable = ctx["playable"].get(p["partner_class"], False)
    rule, basis = pair_rule(mnode, mrec, hero)
    out = {"rule": rule, "rule_basis": basis}
    if rule is None:
        return out
    a = RULE_ACTION[rule]
    out["action"] = {"id": a, "name": ee.name("CONTROL_ACTION_TYPES", a, "ACTION_%s" % a)}
    out["opponent_models"] = p.get("master_opponent_models")
    out["master_weapon_classes"] = allowed_enum(mnode, VAR_WEAPON, am)
    out["opponent_weapon_classes"] = allowed_enum(mnode, am.VAR_OPPONENT_WEAPON, am)
    req, exc = chain_enum(mnode, VAR_SPECIFIC_MODEL)
    if req or exc:
        out["specific_model"] = {
            "requires": [ee.name("SPECIFIC_MODEL", v, "VALUE_%s" % v) for v in req],
            "excludes": [ee.name("SPECIFIC_MODEL", v, "VALUE_%s" % v) for v in exc],
        }
    out["distance_m"] = chain_interval(mnode, VAL_ATTACK_MOVE_DIST)

    if rule in ("counter", "enemy_counter"):
        e = _event(mrec, EV_IMPACT)
        factor = PAIR_PLAYABLE_FACTOR if victim_playable else 1.0
        out["damage"] = {
            "source": "counter_base",
            "event": "IMPACT",
            "at": _timing(e),
            "amounts": _amounts(data, p["master_class"], "counter_damage", factor),
        }
        if e is None:
            out["damage"]["note"] = "the master carries no IMPACT event: no damage"
    elif rule == "finisher":
        e = _event(mrec, EV_KILL_PARTNER)
        out["damage"] = {
            "source": "kill",
            "event": "KILL_ANIMATION_PARTNER",
            "at": _timing(e),
            "amount": KILL_DAMAGE,
        }
        die = _event(prec, EV_DIE)
        if die is not None:
            out["damage"]["partner_die_event"] = _timing(die)
        out["finisher_prompt"] = [
            {
                "character_def": d["name"],
                "critical_health": d["critical_health"],
                "max_health": d["max_health"],
                "prompt_time_s": d["finish_icon_time_s"],
            }
            for d in data.owners(p["partner_class"])
            if d.get("critical_health")
        ]
    elif rule == "bull_rush":
        e = _event(mrec, EV_BULLMOVE_IMPACT)
        sd = data.special_def or {}
        base = sd.get("m_nbullrushdamage")
        factor = BULL_PLAYABLE_FACTOR if victim_playable else 1.0
        out["damage"] = {
            "source": "bull_rush",
            "rule": "combat.rules.bull_rush",
            "event": "BULLMOVE_IMPACT",
            "at": _timing(e),
            "base": base,
            "factor": factor,
            "amount": None if base is None else round(base * factor, 4),
            "stun_s": sd.get("m_nbullrushstun"),
        }
    elif rule == "throw":
        # no event of a throw deals damage and m_ndefaultdamagethrow has no reader:
        # the thrown body loses health by ragdoll contacts only
        big = bool((ctx.get("big") or {}).get(p["partner_class"]))
        out["damage"] = {
            "source": "ragdoll_contact",
            "event": None,
            "amount": None,
            "rule": "combat.rules.ragdoll_damage",
            "throw_damage_property_used": False,
            "release_speed_m_s": THROW_SPEED_BIG if big else THROW_SPEED,
            "release_speed_basis": "partner class is %s (AnimationCtrlWM"
            ".CharacterTransferToRagdollControl 0x5b16ed)" % ("big" if big else "not big"),
            "fall_kill": {
                "body_below_thrower_visual_m": RAGDOLL_FALL_KILL_M,
                "damage": KILL_DAMAGE,
            },
            "bystanders": {
                "direct_damage": BYSTANDER_DAMAGE_FACTOR,
                "stun_s": BYSTANDER_STUN_S,
                "poses": [pose_name(i) for i in BYSTANDER_POSES],
                "note": "above m_nragdollimpactragdolltrigger the bystander is ragdolled and"
                " then takes contact damage itself",
            },
        }
    b0, b1 = _event(prec, EV_BREAKOUT), _event(prec, EV_BREAKOUT_END)
    if b0 is not None:
        out["breakout"] = {
            "from_s": b0.get("play_time_s"),
            "to_s": b1.get("play_time_s") if b1 is not None else None,
            "from_playpos": b0.get("playpos"),
            "to_playpos": b1.get("playpos") if b1 is not None else None,
        }
    return out


# ---------------------------------------------------------------- combo steps
def _ordered_groups(cands):
    out = []
    for path, _b in cands:
        g = path.rsplit("/", 1)[0]
        if g not in out:
            out.append(g)
    return out


def _draws_from(step, first, blocks):
    """Group paths of the class's attack states a combo step can play, in TREE
    ORDER: same button, a weapon class the group allows, the override in effect
    allowed, target not prone, and no INITIAL_ATTACK group after the first
    press.  A non-random parent group takes its first acceptable member
    (GetValidState 0x5f0792), so the first listed group whose remaining criteria
    (distance, angle, height) hold is the one played."""
    button, wpn = step.get("button"), step.get("weapon_class")
    if step.get("item_id") == 16:  # KICK: any attack on a prone target
        return _ordered_groups(
            (path, b)
            for path, b in blocks
            if "TARGET_PRONE" in (b.get("target_mode") or {}).get("requires", [])
        )
    if button is None:
        return []
    ov = step.get("override_in_effect") or ee.name("OVERRIDE_ATTACK_COMBO", 0, "NORMAL")
    cands = []
    for path, b in blocks:
        if b.get("attack_class") != button or wpn not in b.get("weapon_classes", ()):
            continue
        allowed = b["combo_override"]["allowed"]
        if allowed is not None and ov not in allowed:
            continue
        if "TARGET_PRONE" in (b.get("target_mode") or {}).get("requires", []):
            continue
        if not first and b["entry"] == "initial":
            continue
        cands.append((path, b))
    return _ordered_groups(cands)


def annotate_combo_steps(data, class_blocks):
    """Adds `draws_from` ({animation class: [group paths]}) to every item of the
    databases an animation class's owners use.  Derived (rules.combo)."""
    for cn, blocks in sorted(class_blocks.items()):
        names = set()
        for d in data.owners(cn):
            names.add(d["combo_database"])
            for a in data.ai_defs_of(d):
                names.add(a.get("override_combo_database"))
        for dbn in sorted(n for n in names if n):
            db = data.combo_databases.get(dbn)
            if db is None:
                continue
            for s in db["strings"]:
                for i, item in enumerate(s["items"]):
                    groups = _draws_from(item, i == 0, blocks)
                    if groups:
                        item.setdefault("draws_from", {})[cn] = groups


# ----------------------------------------------------------------------- build
NOT_ESTABLISHED = [
    "ragdoll contact force magnitudes and contact counts (run-time physics): they decide how"
    " much health a ragdolled body loses",
    "the AI behaviours behind rules.attack_permission (chase, hang back, circle, return to the"
    " combat zone) and the orchestrator's level presets: not exported here",
    "Twilight Lady's punish and back-flip routines",
    "Underboss: whether the registered defaults 3 / 2 are live (the shipped fragment stores"
    " neither property)",
    "a native or data writer of PublicLib.g_nglobaldamagefactor outside the files scanned"
    " (no difficulty input in script code; default 1.0)",
    "property defaults: a registered default is parsed into the slot at instance creation"
    " (0x47dfed); nine combat defaults absent from every decoded JSON of the six sets (1,207 /"
    " 1,174 files); a property without a registered default starts as 0, null, a zero vector"
    " or an empty list (type virtual +0xc: 0x4fa365, 0x4fa89c, 0x4fb82b, 0x50030f)",
]


def build(extract_out, classes, states, pairs, am, log=None):
    """Adds the combat records to the anim_meta tables and returns the
    top-level `combat` block.

    classes: anim_meta.load_classes(); states: {class: [(node, record)]};
    pairs: the pair list (mutated: `trigger`); am: the anim_meta module."""
    log = log or (lambda *a: None)
    data = CombatData(extract_out, log)
    ids = link_classes(data, classes, extract_out)
    playable = {}
    for cn, c in classes.items():
        owners = data.owners(cn)
        playable[cn] = (
            any(d["playable"] for d in owners)
            if owners
            else c.get("chartype_label") in ("RORSCHACH", "NITE_OWL")
        )
    node_of, rec_of = {}, {}
    class_blocks, out_classes = {}, {}
    for cn, recs in sorted(states.items()):
        big = classes[cn].get("chartype") in (4, 5)
        ai = not playable[cn]
        ctx = {
            "data": data,
            "class": cn,
            "whiff_m": (WHIFF_BIG_M if big else WHIFF_M) if ai else None,
            "whiff_basis": ("ai_big" if big else "ai") if ai else "player",
        }
        counts, blocks, no_damage = {}, [], []
        for node, rec in recs:
            node_of[(cn, rec["path"])] = node
            rec_of[(cn, rec["path"])] = rec
            rec["group_criteria"] = group_criteria(node)
            rec["criteria_rendered"] = _crit_rows(asm.criteria_of(node))
            block = state_combat(node, rec, ctx, am)
            if block is None:
                continue
            rec["combat"] = block
            counts[block["kind"]] = counts.get(block["kind"], 0) + 1
            if block["kind"] == "attack":
                blocks.append((rec["path"], block))
                if not block.get("damage"):
                    no_damage.append({"state": rec["path"], "reason": block.get("damage_reason")})
        class_blocks[cn] = blocks
        owners = data.owners(cn)
        out_classes[cn] = {
            "class_id": ids.get(cn),
            "model_type": classes[cn].get("chartype_label"),
            "playable": playable[cn],
            "big": big,
            "character_defs": [d["name"] for d in owners],
            "combo_databases": sorted(
                {d["combo_database"] for d in owners if d["combo_database"]}
                | {
                    a["override_combo_database"]
                    for d in owners
                    for a in data.ai_defs_of(d)
                    if a.get("override_combo_database")
                }
            ),
            "state_counts": dict(sorted(counts.items())),
            "attack_states": len(blocks),
            "attack_states_without_damage": no_damage,
            "attack_groups": _attack_groups(blocks),
        }
        log(
            "combat %-12s %3d attack states (%d without damage), owners %s"
            % (cn, len(blocks), len(no_damage), ", ".join(d["name"] for d in owners) or "-")
        )
    annotate_combo_steps(data, class_blocks)

    rules_count = {}
    for p in pairs:
        mnode = node_of.get((p["master_class"], p["master_path"]))
        mrec = rec_of.get((p["master_class"], p["master_path"]))
        prec = rec_of.get((p["partner_class"], p["partner_path"])) or {}
        if mnode is None or mrec is None:
            p["trigger"] = {"rule": None, "rule_basis": "master state not found"}
        else:
            big = {cn: c.get("chartype") in (4, 5) for cn, c in classes.items()}
            ctx = {"data": data, "playable": playable, "big": big}
            p["trigger"] = pair_trigger(p, mnode, mrec, prec, ctx, am)
        r = p["trigger"]["rule"] or "none"
        rules_count[r] = rules_count.get(r, 0) + 1

    return {
        "format": COMBAT_FORMAT,
        "evidence": (
            "rules: read from the game's script (handler and address given) and constants"
            " read from the executable's bytes; tables: read from the shipped fragments;"
            " 'derived' fields are computed by the toolkit from those rules"
        ),
        "rules": _with_override_events(
            rules(data.visual_def, data.underboss_defs), override_damage_events(states)
        ),
        "enums": {
            "TARGET_MODE": {
                "evidence": "values written by CharacterVisual.command_update_animation"
                " 0x69b988 (script code; the exe registers no value family for enum 7)",
                "items": {str(k): v for k, v in sorted(TARGET_MODE.items())},
            },
            "CHARACTER_COMBO_ITEMS": {
                "evidence": "exe enum family, registered in 0x6726d6",
                "items": {str(k): v for k, v in sorted(CHARACTER_COMBO_ITEMS.items())},
            },
            "CHARACTER_COMBO_ENEMY_STATUS": {
                "evidence": "exe enum family, registered in 0x6726d6 (bit mask, -1 = any)",
                "items": {str(k): v for k, v in sorted(CHARACTER_COMBO_ENEMY_STATUS.items())},
            },
            "AI_DEF_TYPE": {
                "evidence": "exe enum family, registered in 0x5a38a6",
                "items": {str(k): v for k, v in sorted(AI_DEF_TYPE.items())},
            },
            "LOGICAL_INPUT_BUTTONS": {
                "evidence": "exe enum family (combat buttons only)",
                "items": {str(k): v for k, v in sorted(LOGICAL_INPUT_BUTTONS.items())},
            },
            **{
                name: {"evidence": ev, "items": {str(k): v for k, v in sorted(items.items())}}
                for name, items, ev in _PARTNER_ENUMS
            },
        },
        **({"achievements": data.achievements} if data.achievements else {}),
        "special_def": data.special_def,
        "combo_databases": data.combo_databases,
        "character_defs": data.character_defs,
        "ai_defs": data.ai_defs,
        "weapons": {
            "evidence": "data; a weapon has no damage of its own: damage comes from the"
            " combo database's base for its class",
            "items": data.weapons,
        },
        "classes": out_classes,
        "totals": {
            "attack_states": sum(c["attack_states"] for c in out_classes.values()),
            "attack_states_without_damage": sum(
                len(c["attack_states_without_damage"]) for c in out_classes.values()
            ),
            "pair_rules": dict(sorted(rules_count.items())),
        },
        "not_established": NOT_ESTABLISHED,
    }


def _with_override_events(r, events):
    """rules with rules.damage.override_events filled for this extract."""
    r["damage"]["override_events"] = events
    return r


def _attack_groups(blocks):
    """{group path: what its attack states have in common} -- the index a combo
    step's `draws_from` points into."""
    out = {}
    for path, b in blocks:
        g = out.setdefault(
            path.rsplit("/", 1)[0],
            {
                "attack_class": b.get("attack_class"),
                "weapon_classes": b.get("weapon_classes"),
                "entry": b.get("entry"),
                "combo_override": b["combo_override"]["required"],
                "states": [],
            },
        )
        g["states"].append(path.rsplit("/", 1)[-1])
    return dict(sorted(out.items()))


def build_or_none(extract_out, classes, states, pairs, am, log=None):
    """build(), or None when the extract's combat data cannot be read: the
    combat block is decoration and must not take the animation table down."""
    try:
        return build(extract_out, classes, states, pairs, am, log)
    except Exception as ex:  # a fragment this module does not understand
        (log or (lambda *a: None))("  combat: skipped (%s: %s)" % (type(ex).__name__, ex))
        return None


# --------------------------------------------------------------------- summary
def summary(meta):
    """One line per class and one for the pairs, from a written table."""
    c = meta.get("combat")
    if not c:
        return "no combat block (format %s)" % meta.get("format")
    lines = ["%s" % c["format"]]
    for cn, k in sorted(c["classes"].items()):
        lines.append(
            "%-12s %3d attack states (%d without damage)  owners: %s"
            % (
                cn,
                k["attack_states"],
                len(k["attack_states_without_damage"]),
                ", ".join(k["character_defs"]) or "-",
            )
        )
    lines.append("pairs by rule: %s" % json.dumps(c["totals"]["pair_rules"], sort_keys=True))
    lines.append(
        "%d combo databases, %d character defs, %d AI defs, %d weapons"
        % (
            len(c["combo_databases"]),
            len(c["character_defs"]),
            len(c["ai_defs"]),
            len(c["weapons"]["items"]),
        )
    )
    return "\n".join(lines)


_USAGE = re.sub(r"\s+", " ", "usage: combat_meta.py ANIM_META.json")


def main(argv):
    if len(argv) != 2:
        print(_USAGE)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        print(summary(json.load(fh)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
