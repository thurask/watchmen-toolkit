#!/usr/bin/env python3
"""level_meta -- one `<level>.level.json` per level ("watchmen-level-meta/1") and a
reader for the game's `.kpw` save files.

A level is a `SceneScope(LoadBlock)` node of the scene file (`*.scene`, itself a
fragment).  Its top fragment is instanced with every nested fragment, as the
engine does when it applies a load block (FragmentNode::SetFragmentAssetByName
0x498db7 -> Fragment::Apply 0x5473ee), references are resolved the engine's way
(anim_state_machine.resolve_ref) and world transforms are composed down the tree.

Sections: level (with ai_world), files, fragments, characters (with variant, weapon,
ai_start), groups, character_defs, models, volumes, path_objects, nav, combat_presets,
cube_maps, graph (condition / action nodes + typed edges), checkpoints, cameras,
movies, game_events, spawn_recipe, unresolved, counts.  docs/LEVEL_META.md describes
each.

Evidence: engine reading in findings/wp5_runtime.md, waveA_spawn_check.md (model
picker, path-object ids), waveC_ai_check.md (state of mind, orchestrator presets,
groups) and waveC_renderer_check.md (cube maps); `evidence` in the JSON says per
section what is read from code, what is data and what is inferred.
"""

import glob
import json
import math
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0): flat module names must not shadow the stdlib

import frame as _frame  # noqa: E402

FORMAT = "watchmen-level-meta/1"
SAVE_FORMAT = "watchmen-save-meta/1"

# Enum families of the trigger system and level flow, as the executable registers
# them (FUN_005052c9(family, "PREFIX___NAME", value); findings/enums.json).
ENUMS = {
    "BLACK_SCREEN_TRANSITIONS": {0: "CUT", 1: "FADE", 2: "CUT_TO_BLACK"},
    "CAMERA_CAM_DIR_TARGETS": {0: "ACTIVATOR", 1: "RORSHCACH", 2: "NITE_OWL", 3: "BOTH"},
    "FORCE_MOVE_ACTION": {0: "INVALID", 1: "FORCE_MOVE", 2: "SKIP_FORCE_MOVE"},
    "GAME_EVENTS": {
        0: "NONE",
        1: "SCENE_ACTIVATED",
        2: "SCENE_DEACTIVATING",
        3: "SCENE_DEACTIVATED",
        4: "SCENE_RESTARTED",
        5: "SCENE_RESTORED_FROM_CP",
        6: "SCENE_STARTING",
        7: "GAME_CRITICAL_STOP",
        100: "LEVEL_START",
        101: "LEVEL_END",
        102: "GAMEOVER",
        103: "TRIAL_MODE_END",
        104: "GAME_COMPLETE_RORSCHACH_WON",
        105: "GAME_COMPLETE_NITE_OWL_WON",
        106: "PLAYER_VS_PLAYER_BEGIN",
        107: "PLAYER_VS_PLAYER_END",
        108: "PLAYER_VS_PLAYER_BULL_RUSH_PERFORMED",
        109: "PLAYER_VS_PLAYER_RAGE_MODE_ENDED",
        110: "PLAYER_VS_PLAYER_STUN_GRENADE_FIRED",
        111: "PLAYER_VS_PLAYER_ELECTRIFY_ARMOR_ENDED",
        112: "PLAYER_VS_PLAYER_ELECTRIFY_ARMOR_START",
        201: "CHARACTER_DEAD",
        203: "CHARACTER_DAMAGE_RECEIVED",
        204: "CHARACTER_PLACEHOLDED_IN",
        205: "CHARACTER_PLACEHOLDED_OUT",
        206: "CHARACTER_SUBSYSTEMS_CREATED",
        207: "CHARACTER_SUBSYSTEMS_DELETING",
        300: "PLAYER_CTRL_ACTIVATED",
        301: "PLAYER_CTRL_DEACTIVATED",
        400: "CHARACTER_CAMERA_ACTIVATED",
        500: "TRIGGER_THRESHOLD_GREATER_THAN_COUNTER",
        501: "TRIGGER_THRESHOLD_LESS_THAN_COUNTER",
        502: "TRIGGER_THRESHOLD_EQUAL_TO_COUNTER",
        600: "CUTSCENE_DONE",
        610: "GAME_SETTINGS_MENU_UPDATED",
        611: "AUDIO_SETTINGS_MENU_UPDATED",
        612: "VIDEO_SETTINGS_MENU_UPDATED",
        613: "BRIGHTNESS_CONTRAST_SETTINGS_MENU_UPDATED",
        614: "ACTIONLIST_SETTINGS_MENU_UPDATED | MENU_CLOSED",
        615: "MENU_STARTED",
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
    },
    "GAME_MODES": {0: "NONE", 1: "RORSCHACH", 2: "NITEOWL", 3: "COOP", 4: "MAINMENU"},
    "GAME_MODE_DATA": {1: "RORSCHACH", 2: "NITEOWL", 4: "COOP"},
    "PLAYABLE_CHARACTERS": {-1: "NONE", 0: "RORSCHACH", 1: "NITE_OWL", 2: "BOTH"},
    "SAVETYPE": {0: "SETTINGS", 1: "LEVELPROGRESS"},
    "SAVE_GAME_TYPE": {
        0: "RORSCHACH",
        1: "NITEOWL",
        2: "COOP_PLAYER1_IS_RORSCHACH",
        3: "COOP_PLAYER1_IS_NITEOWL",
    },
    "SCENE_ID": {
        -1: "NONE",
        0: "MAIN_MENU",
        1: "PRISON",
        2: "STREETS",
        3: "DOCKS",
        4: "UNDERGROUND",
        5: "CONSTRUCT_SITE",
        6: "STREETS_2",
        7: "NIGHTCLUB",
        8: "STREETS_OF_RIOTS",
        9: "BORDELLO",
        20: "GAME_ESSENTIALS",
        30: "TUTORIAL",
        40: "PLAYER_VS_PLAYER",
        50: "DEBUG_TOOL_CHECKER",
    },
    "STATE_OF_MIND": {0: "PASSIVE", 1: "AGGRESSIVE"},
    "TRIGGER_ACTION_CAMERA_ACTIONS": {
        0: "CAMERA_TOUR",
        1: "SET_CAMERA",
        2: "END_TOUR",
        3: "SET_CHARACTER_CAM_DIR",
    },
    "TRIGGER_ACTION_CATEGORY_CHARACTER": {
        0: "TELEPORT",
        1: "SET_AI_STATE",
        2: "PLAY_SPECIFIC_ANIMATION",
        3: "FOLLOW_PIVOT",
        4: "KILL",
        5: "ACTIVATE",
        6: "SET_PRIORITY_LOOKAT_TARGET",
        7: "REMOVE_PRIORITY_LOOKAT_TARGET",
        8: "DEACTIVATE",
        9: "LOOK_AT_PIVOT",
        10: "CANCEL_LOOKAT",
        11: "LEAVING_COMBAT_ZONE",
        12: "ENTERING_COMBAT_ZONE",
        13: "USE",
        14: "FORCE_MOVEMENT_TYPE",
        15: "STOP_FORCED_STATE",
        16: "GIVE_HEALTH",
        17: "GIVE_POWER",
        18: "SET_AI_DEF",
        19: "SET_AI_DEF_PHASE",
        20: "TUTORIAL_AI_PASSIVE",
        21: "TUTORIAL_AI_AGGRESSIVE",
        22: "SET_INCOMING_DAMAGE_FACTOR",
        23: "SET_MIN_HEALTH",
        24: "INVULNERABLE",
        25: "RUMBLE_CHARACTERS_CONTROLLER",
        26: "SHOW_BOSS_HUD",
        27: "HIDE_BOSS_HUD",
        28: "REQUEST_FORCED_STATE",
        29: "SET_TWI_LADY_COMBAT_PARAMS",
        30: "RESET_SPECIAL_MODE",
        31: "DROP_WEAPON",
        32: "DAMAGE_MODE",
        33: "CAMERA_SHAKE",
        34: "FREEZE_ACTIVE_RAGDOLLS",
    },
    "TRIGGER_ACTION_CATEGORY_PARTICLE": {
        0: "DO_PARTICLE_EFFECT",
        1: "START_PARTICLE",
        2: "STOP_PARTICLE",
    },
    "TRIGGER_ACTION_CATEGORY_SOUND": {
        0: "SOUND_PLAY",
        1: "SOUND_STOP",
        2: "GROUP_STOP",
        3: "ALL_STOP",
        4: "CROSS_FADE",
        5: "GROUP_PAUSE",
        6: "GROUP_UNPAUSE",
        7: "GROUP_SET_VOLUME",
        8: "ACTIVATE_MUSIC_SETUP",
        9: "ACTIVATE_MUSIC_STATE",
        10: "DEACTIVATE_MUSIC",
        11: "ACTIVATE_MUSIC_INTENSITY",
        12: "NEXT_DEFAULT_MUSIC_STATE",
        13: "ADJUST_SOUND",
    },
    "TRIGGER_ACTION_CHAR_TARGETS": {1: "ENTITYREF", 2: "RORSCHACH", 3: "NITE_OWL"},
    "TRIGGER_ACTION_DELAY": {0: "DELAY"},
    "TRIGGER_ACTION_GENERAL": {
        0: "ENABLE",
        1: "DISABLE",
        2: "FLIP_ENABLED",
        3: "SET_VISIBLE",
        4: "SET_INVISIBLE",
        5: "FLIP_VISIBLE",
        6: "RESET_CONDITION",
        7: "STOP_SEQUENCER",
        8: "TRIG",
        9: "CHANGE_MOVEMENT_TYPE",
        10: "SET_GFX_NODE_DEFAULT",
        11: "SET_GFX_NODE_SPECIFIC",
        12: "PLAY_MOVIE",
        13: "START_SEQUENCER",
        14: "AMOUNT_RESET",
        15: "AMOUNT_INCREMENT",
        16: "AMOUNT_DECREMENT",
        17: "USE_TRIGGER_FREEZE",
        18: "USE_TRIGGER_UNFREEZE",
        19: "SET_IMPASSABLE",
        20: "ACTIVATE_WAYPOINTS",
        21: "SET_TIME_MULTIPLIER",
        22: "ACTIVATE_DEPTH_OF_FIELD",
        23: "DEACTIVATE_DEPTH_OF_FIELD",
        24: "SET_SEARCHLIGHT_TARGET",
    },
    "TRIGGER_ACTIVATOR": {
        0: "RORSCHACH",
        1: "NITE_OWL",
        2: "ALLY_FACTION",
        3: "ENEMY_FACTION",
        4: "PLAYER_CONTROLLED",
        5: "ANY_CHARACTER",
        6: "UNDERBOSS",
    },
    "TRIGGER_ACTIVATOR_TYPE": {
        0: "ANY_CHARACTER",
        1: "PLAYER",
        2: "RORSCHACH",
        3: "NITE_OWL",
        4: "SPECIFIC",
        5: "ENEMY",
    },
    "TRIGGER_CONDITION": {0: "ENTER", 1: "LEAVE", 2: "INSIDE"},
    "TRIGGER_CONDITION_CHARACTER_TYPE": {1: "HEALTH_PERCENT_BELOW", 2: "HEALTH_PERCENT_ABOVE"},
    "TRIGGER_CONDITION_TYPE": {1: "ANY", 2: "ALL", 3: "SOME"},
    "TUTORIAL_EVENT": {
        1: "THROW",
        2: "DODGE",
        3: "COUNTERATTACK",
        4: "BULL_RUSH",
        5: "ELECTRIFY",
        6: "GRENADE",
        7: "RAGE_MODE",
        8: "HEAVY_ATTACK",
        9: "FAST_ATTACK",
        10: "COMBO",
        11: "BLOCK",
    },
    "VIEWPORT_TARGET": {0: "RORSCHACH", 1: "NITE_OWL", 2: "BOTH", 3: "ACTIVATOR"},
    "USE_TYPES": {
        -1: "NONE",
        0: "PICK_LOCK",
        1: "SQUEEZE_UNDER",
        2: "JUMP_DOWN",
        3: "CLIMB",
        4: "PULL",
        5: "TURN_VALVE",
        6: "GRAPPLING",
        7: "PICK_UP",
        8: "LIFT",
        9: "PULL_LEVER",
        10: "PULL_SWITCH",
        11: "JUMP",
        12: "GRAPPLING_DOWN",
        13: "SLIDE_DOOR_LEFT",
        14: "SLIDE_DOOR_RIGHT",
        15: "FORCE_OPEN_DOOR",
    },
    "MOVEMENT_TYPES": {0: "STATIC", 1: "KINEMATIC", 2: "DYNAMIC"},
    "ORIENTATION_CONTROL_TYPE": {0: "NONE", 1: "LOOK_AT_TARGET", 2: "COPY_TARGET"},
    "POSITION_CONTROL_TYPE": {0: "NONE", 1: "COPY_TARGET"},
}

# (script class, property) -> enum family.  The class/property pairs marked "name"
# in EVIDENCE["enums"] are matched by the family's name only.
PROP_ENUMS = {
    ("TriggerConditionCollision", "m_itrueon"): "TRIGGER_CONDITION",
    ("TriggerConditionCollision", "m_iactivator"): "TRIGGER_ACTIVATOR_TYPE",
    ("TriggerConditionGameEvent", "m_itrueon"): "GAME_EVENTS",
    ("TriggerConditionGameEvent", "m_iactivator"): "TRIGGER_ACTIVATOR_TYPE",
    ("TriggerConditionLogical", "m_iconditiontype"): "TRIGGER_CONDITION_TYPE",
    ("TriggerConditionCharacter", "_iconditiontype"): "TRIGGER_CONDITION_CHARACTER_TYPE",
    ("TriggerConditionTutorial", "_icondition"): "TUTORIAL_EVENT",
    ("TriggerActionCharacter", "m_iactiontype"): "TRIGGER_ACTION_CATEGORY_CHARACTER",
    ("TriggerActionCharacter", "m_itargettype"): "TRIGGER_ACTION_CHAR_TARGETS",
    ("TriggerActionCharacterForceMove", "m_iactiontype"): "FORCE_MOVE_ACTION",
    ("TriggerActionGeneral", "m_iactiontype"): "TRIGGER_ACTION_GENERAL",
    ("TriggerActionDelay", "m_iactiontype"): "TRIGGER_ACTION_DELAY",
    ("TriggerActionGameEvent", "m_iactioneventtype"): "GAME_EVENTS",
    ("TriggerActionCamera", "_iaction"): "TRIGGER_ACTION_CAMERA_ACTIONS",
    ("TriggerActionCamera", "m_iviewport"): "VIEWPORT_TARGET",
    ("TriggerActionCamera", "_itarget"): "CAMERA_CAM_DIR_TARGETS",
    ("TriggerActionCamera", "m_istarttransitionin"): "BLACK_SCREEN_TRANSITIONS",
    ("TriggerActionCamera", "m_istarttransitionout"): "BLACK_SCREEN_TRANSITIONS",
    ("TriggerActionCamera", "m_iendtransition"): "BLACK_SCREEN_TRANSITIONS",
    ("TriggerActionMovie", "m_istarttransition"): "BLACK_SCREEN_TRANSITIONS",
    ("TriggerActionMovie", "m_iendtransition"): "BLACK_SCREEN_TRANSITIONS",
    ("TriggerActionSound", "m_iactiontype"): "TRIGGER_ACTION_CATEGORY_SOUND",
    ("TriggerActionParticle", "m_iactiontype"): "TRIGGER_ACTION_CATEGORY_PARTICLE",
    ("TriggerUse", "_iactivatortype"): "TRIGGER_ACTIVATOR",
    ("TriggerUseFragment", "m_iactivatortype"): "TRIGGER_ACTIVATOR",
    ("TriggerCharacter", "_iactivatortype"): "TRIGGER_ACTIVATOR",
    ("CharacterRoot", "m_istateofmind"): "STATE_OF_MIND",
    ("CharacterDef", "m_iplayablecharacter"): "PLAYABLE_CHARACTERS",
    ("SceneScope", "m_isceneid"): "SCENE_ID",
    ("OverrideGameMode", "_igamemode"): "GAME_MODES",
    ("TriggerUse", "m_iusetype"): "USE_TYPES",
    ("TriggerConditionVisibility", "m_iusetype"): "USE_TYPES",
    ("PivotController", "_iorientationcontroltype"): "ORIENTATION_CONTROL_TYPE",
    ("PivotController", "_ipositioncontroltype"): "POSITION_CONTROL_TYPE",
    ("TriggerConditionVisibility", "_icharacter"): "PLAYABLE_CHARACTERS",
    ("waypoint", "m_iexclusivetocharacter"): "CHARACTER_TYPES",  # family in engine_enums
}
#: Enemy root-behaviour states (enum ENEMY, registered 0x5a3b12..0x5a3b9c; values read
#: from the pushes beside each name string)
ENEMY_STATES = {
    0: "NO_STATE",
    1: "INACTIVE",
    2: "CHASING",
    3: "IDLING",
    4: "ATTACKING",
    5: "FOLLOW_PIVOT",
    6: "BRAINLESS_AUTOTARGET",
    7: "HANG_BACK",
    8: "RETURN_TO_COMBAT_ZONE",
    9: "TWILIGHT_LADY_BACK_FLIP",
    10: "STEP_BACK",
}
#: stop-criteria bits of a forced state (enum STOP_CRITERIA, registered 0x5a3c99..0x5a3cd5)
STOP_CRITERIA = {
    1: "LEADER_PRESENT",
    2: "TIMER",
    4: "ENEMY_IN_MELEE_RANGE",
    8: "STATE_NOT_RUNNING",
}
#: what AILib.CharacterRootToAiType (0x5974a3) returns for a character in PLAY mode
AI_TYPES = {1: "enemy", 2: "partner", 3: "player_controlled"}
#: AIBrainNode class constants (registered in AIBrainNode::RegisterMembers 0x4865b9,
#: 0x48660a..0x4866e2; they have no common prefix, the family names are the properties')
AI_BRAIN_ENUMS = {
    "agentType": {
        0: "IDLEAGENT",
        1: "GOTOAGENT",
        2: "FOLLOWAGENT",
        3: "WANDERAGENT",
        4: "FLEEAGENT",
        5: "HIDEAGENT",
    },
    "agentFaction": {0: "ALLYFACTION", 1: "ENEMYFACTION", 2: "NEUTRALFACTION"},
    "pathFindingConstraint": {0: "SHORTESTPATH", 1: "STEALTH"},
}
# flag words: every set bit is named
PROP_FLAGS = {
    ("TriggerConditionGameMode", "_igamemodetype"): "GAME_MODE_DATA",
    ("TriggerActionGameMode", "_igamemodetype"): "GAME_MODE_DATA",
    ("GameModeSelector", "_igamemodetype"): "GAME_MODE_DATA",
}

# entity-reference property -> edge kind ("ref" for every other property)
EDGE_KINDS = {
    "m_etriggerentity": "volume",
    "m_etarget1": "target",
    "m_etarget2": "target",
    "m_etarget3": "target",
    "_echaracter": "target",
    "m_eactivatorgroup": "target",
    "_eauxaction": "aux",
    "_ealldeadaction": "all_dead",
    "m_ezonetrigger": "zone",
    "_ereturntohometurfpoint": "return_point",
    "_eontourend": "tour_end",
    "_eontourskipped": "tour_skipped",
    "m_eactivatedaction": "activated",
    "_eactivatedaction": "activated",
    "m_ereleasedaction": "released",
    "_ereleasedaction": "released",
    "m_estartaction": "start",
    "_ecamera": "camera",
    "m_emovie": "movie",
    "m_eactivatorentity": "activator",
    "m_emovetotargetgroup1": "move_to",
    "_estreamblock": "stream_block",
    "_elookatnode": "look_at",
    "m_estreamblock": "stream_block",
    "m_eloadstreamblock": "stream_load",
    "m_eunloadstreamblock": "stream_unload",
    "m_egrappleendpivot": "grapple_end",
    "m_eforcenext": "force_next",
    "m_eforceusetrigger": "force_use",
}

# properties every node carries (editor state, tree links, transform): not `params`
_STD = frozenset(
    "name UseRealTime recordInSavepoints runScript Open enabled Visible runFrameUpdate "
    "smartSelectable logicalParent siblingOrder parentLink spatialTreeStrategy localPos "
    "localOrient Locked UserType includeInAO includeInReflections castShadow "
    # the same five as the executable registers them (key table from 1.4.0 on)
    "useRealtime open visible locked userType".split()
)

# characters_export names the two heroes' folders differently from their fragments
_EXPORT_NAMES = {"Rorchach": "Rorschach", "NightOwl": "NiteOwl"}

# Two stored quaternions are the same orientation for HOST_OFFSET_RULE when every
# component is within this (StreetsOfRiot block C: one pair differs by 1e-6 in one
# component, 0.894935 against 0.894934).
HOST_OFFSET_QUAT_TOLERANCE = 1e-5

HOST_OFFSET_RULE = (
    "data: a model node whose stored local position is the one of another node of the same "
    "class and fragment that sits under a parent cancelling the fragment host's translation, "
    "with every component of the stored quaternion within 1e-5 of the other's, so that the "
    "two world positions differ by exactly that translation (`twin`), and the other model "
    "nodes of its folder (`twin` null).  Its local position is in level coordinates under a "
    "host that is not at the origin: StreetsOfRiot block C keeps ten such CharacterSimple "
    "nodes 50 m above the street; each of the seven placed ones is the twin of one of them.  "
    "inferred: an editor leftover; not established: whether the game draws them"
)

CONVENTIONS = {
    "units": "metres; +Y is up",
    "quaternion": "(x, y, z, w) as stored in localOrient",
    "engine_rotation": "the engine rotates a vector with v' = conj(q) * v * q",
    "world": (
        "world.quat = local (x) parent (Hamilton product, local on the left); "
        "world.pos = parent.pos + rotate(parent.quat, local.pos); the parent is the "
        "nearest ancestor with a transform; parentLink = 1 (NEVER_MOVE_WITH_PARENT) "
        "composes the same way; in play mode it only stops a later move of the parent from "
        "reaching the node (0x49325d)"
    ),
    "light": (
        "axis = local +Z (0x9e808c); distance term = sat((range - d) / (range * (1 - "
        "min(attn_start, 0.99)))); spot term = sat((cos t - cos outer) / (cos inner - cos "
        "outer)), cones are half-angles in degrees, cos outer / cos inner capped at 0.99; "
        "colour * brightness * camera-distance fade (read from code: 0x579fdf, 0x56a4c0; the "
        "saturate form is inferred from the constants).  A value the node does not store is "
        "null; the constructor defaults are type 1, range 25, attn_start 0.75, brightness 1, "
        "shadow power 1, cones 45 / 55 (0x4a3d8e)"
    ),
    "gltf": (
        "a placement's `gltf` is the node transform of a toolkit GLB placed in a "
        "glTF scene: translation = world.pos unchanged, rotation = conj(world.quat) "
        "= (-x, -y, -z, w), no scale.  Positions and toolkit meshes share one "
        "coordinate frame, so a level assembled this way is self-consistent."
    ),
    "handedness": (
        "the toolkit keeps the engine's coordinates in its GLBs, which a glTF viewer "
        "shows mirrored; put scale (-1, 1, 1) on ONE scene root above everything for "
        "the picture the game shows (never per placement)"
    ),
    "forward": "`forward` is the world direction of the node's local +Z; yaw_deg = atan2(x, z)",
    "uid": "<fragment instance index>:<node id>; node ids repeat across fragment instances",
    "stable_uid": (
        "<node id>@<instance id>: the same node under a name that does not depend on how many "
        "fragment instances were loaded before it.  `uid` carries the instance's ordinal in "
        "load order, which shifts by one for everything behind a fragment a platform lacks, "
        "so uids of the same node differ between platforms; the instance id is the first 8 "
        "hex digits of the SHA-1 of the chain of host node ids from the scene file down "
        "(text 'scene/<host id>/<host id>...', the scene file itself is 'scene').  Written on "
        "every graph node (`stable_uid`) and on every fragment (`stable_id`); `stable_ids` "
        "lists the instance id of every instance index, so any `uid` 'N:<id>' in this file "
        "maps to '<id>@' + stable_ids[N].  A toolkit naming rule, not an engine value; `uid` "
        "stays the key every reference in this file uses"
    ),
    "order": (
        "`order` on an edge is the child index the engine fires in (siblingOrder).  read: the "
        "engine's sibling insert (0x48f556) puts a node behind every sibling whose order is "
        "<= its own, so children with EQUAL siblingOrder keep the order they were inserted "
        "in; inferred: that this insertion order is the order in the file, which is the "
        "order kept here -- counts.action_order_ties says how many action lists have a tie"
    ),
    "model_flags": (
        "models[].cast_shadow is the node flag the stencil shadow pass tests (0x4995c6, "
        "0x5748e2); the mesh also needs a shadow hull in its model (not_exported.shadow_hull "
        "of the model's .model.json).  models[].opacity (BaseModel, clamped 0..1 by the "
        "engine) multiplies the sheet opacity; below 0.99 a type 0 or 10 part is drawn "
        "blended (0x5739d0)"
    ),
    "host_offset_copy": HOST_OFFSET_RULE,
}

# The frame-dependent sentences for a file written in the true frame (the default).
CONVENTIONS_TRUE = dict(CONVENTIONS)
CONVENTIONS_TRUE["gltf"] = (
    "a placement's `gltf` is the node transform of a toolkit GLB placed in a glTF "
    "scene, in the GLBs' frame (coordinate_frame 'right-handed-true': right-handed, "
    "x = -engine x): translation = (-world.pos.x, world.pos.y, world.pos.z), rotation "
    "= (-x, y, z, w) of world.quat (its conjugate, reflected), no scale.  Place every "
    "GLB with its `gltf` and the level is assembled as the game shows it."
)
CONVENTIONS_TRUE["handedness"] = (
    "`gltf`, `forward` and `yaw_deg` are in the true-handed frame of the toolkit's "
    "GLBs; nothing has to be mirrored and no root scale is needed.  `world` and every "
    "other position or quaternion in this file are "
    + _frame.ENGINE_NOTE
    + ".  A level file without a coordinate_frame key (--frame mirrored) has `gltf` in "
    "the engine's numbers, which a glTF viewer shows as a mirror image"
)
CONVENTIONS_TRUE["forward"] = (
    "`forward` is the direction of the node's local +Z in the frame of `gltf` "
    "(the engine direction with x negated); yaw_deg = atan2(x, z) of it"
)


def conventions(frame=None):
    """The `conventions` block of a level file in `frame` (default frame.mode())."""
    return CONVENTIONS_TRUE if _frame.is_true(frame) else CONVENTIONS


EVIDENCE = {
    "fragments": "read: FragmentNode::SetFragmentAssetByName 0x498db7, Fragment::Apply 0x5473ee",
    "references": "read: EntityType reader 0x500b81 / 0x505d84, scope search 0x53a5ff",
    "world": (
        "read: PivotNode world transform composition; data: the scene assembled from it "
        "puts every character on a floor and inside its room (findings/level_assembly.png). "
        "data: 'nearest ancestor with a transform' for nodes below a Folder, confirmed "
        "against the terrain on StreetsOfRiot (PC Part 2; one level).  read: parentLink is "
        "tested only where a parent passes its change to its children (0x4932d4), not in the "
        "world composition (0x48d789); measured: every node's and every fragment host's "
        "transform is stored after its parent reference and before assetName, and every "
        "parent record precedes its children (PC Part 1 and Part 2, all fragments), so the "
        "gate cannot act during a load; the 21 parentLink = 1 nodes of ConstructionSite (PC "
        "Part 1) lie in the frame of their Group at y = 36 (counts.parent_link_1 says how "
        "many nodes of a level have the flag)"
    ),
    "graph": (
        "read: TriggerConditionBase 0x8632fa, TriggerActionBase 0x84afa9 (child order, "
        "aux action), TriggerActionDelay 0x852ecd (delay of child i = m_ndelaynumber<i>), "
        "TriggerActionCheckpoint 0x85d2de (children run on restore), CharacterGroup 0x66267e. "
        "A condition's actions are taken to be its children of a TriggerAction* class "
        "(the engine tests the class property _tIsAction, which the level data does not store).  "
        "applies: read 0x85e3e8, 0x86038f, 0x873568 (editor property filter; General types 10, "
        "11, 12 do nothing at run time, 0x85f77b).  sound_params: captions read: "
        "TriggerActionSound.FilterExposedProperties 0x861606; calls read: 0x862b6c, 0x853e88, "
        "0x85238a-0x852584; children read: 0x86150a, 0x861583.  sequence_action / "
        "tour_sequence / tour_refire: read 0x4ab230, 0x49d529, 0x4999e7, 0x849e59, 0x84bed0, "
        "0x84b299, 0x84aea3, 0x84bde2.  labels of use triggers: read 0x862e84, 0x87d044; "
        "SOME is an exact count, a reactivatable TriggerConditionTrue repeats (0x86de58, "
        "0x86f83e)"
    ),
    "waypoints": (
        "read: WaypointController.WayPointInit 0x8b1062, SetNextExclusiveCharacter 0x8aa4e5 "
        "(slot 0 = character type 0, slot 1 = type 1; m_eforcenext is ignored on a node not "
        "exclusive to type 0 or 1, and is replaced when the next sibling is exclusive to the "
        "same type), waypoint.command_get_follow 0x8b2f6c (the type's slot, else next_all; "
        "null for a node of the other type), command_activate_recursive 0x8b3091, selection "
        "0x8b012b, CanSee 0x8b0988. data: m_eforcenext is non-null on 28 PC waypoints. not "
        "established: whether WaypointController.StateInitAutoStart 0x8aa1fb runs"
    ),
    "stream_blocks": (
        "read: 0x847c78 (one-shot: gated by _tisused, unload then load, waits for the loaded "
        "callback or 20.0 s), 0x841c78, 0x841d9d (enter with local z > 0 or leave with z <= 0 "
        "loads, otherwise unloads). data: referenced_by = the nodes whose _estreamblock "
        "names the block. not established: what a TriggerActionCheckpoint does with it"
    ),
    "lights": (
        "data: the Light nodes' stored properties; read: Light constructor 0x4a3d8e, type 5 "
        "is kept as type 2 with `textured` (0x4a1c4a), attenuation constants 0x579fdf, "
        "LightFlicker 0x774baf / 0x7703c9 / 0x774c92 (active within 40 m: squared distance "
        "1600.0 at 0xa743b8; _nrangerandomizetime has no reader)"
    ),
    "models": (
        "visible_effective: read 0x48e028 (the node's flag and its PVSRootNode ancestors', "
        "handle set by 0x492b67).  lod_override / lod_factor: read 0x49d00f, 0x53a317, "
        "constructor 0x4a8f99.  part_overrides: read 0x4a5907 (a SubPivot is one part of the "
        "ModelRes; its transform is overwritten with the rest pose unless locked), 0x49faaf "
        "(a part is drawn only when its SubPivot is enabled and visible).  motion: read "
        "0x874b7a, 0x871b96, 0x8718e6 (OscillateBox); 0x874795, 0x87113c (FireBarrel)"
    ),
    "enums": (
        "read: registered by the executable (FUN_005052c9).  read: the families of "
        "TriggerActionCamera m_iviewport / _itarget / transitions and TriggerActionMovie "
        "transitions are named by each property's own registration string "
        "(items=VIEWPORT_TARGET 0xa961a8, items=CAMERA_CAM_DIR_TARGETS 0xa95f18, "
        "items=BLACK_SCREEN_TRANSITIONS)"
    ),
    "forced_state": (
        "read: TriggerActionCharacter.ActionExecute 0x85b858 case 28 sends "
        "command_set_forced_state(state = m_iinteger2, criteria, time): criteria 10 "
        "(TIMER | STATE_NOT_RUNNING) with time m_nnumber1 when the target's AI type equals "
        "m_iinteger1 and the time is above 0, otherwise criteria 8 with time 0.  AI type "
        "from AILib.CharacterRootToAiType 0x5974a3; state and criteria names from the "
        "ENEMY and STOP_CRITERIA enums the executable registers (0x5a3b12, 0x5a3c99)"
    ),
    "ai_sight": (
        "read: the AI sight ray cast 0x48b44e reports every shape whose pivot-sheet "
        "collisionMask shares a bit with AIWorldNode.collisionMask (filter 0x48b4c8, shape "
        "mask 0x51384d) and is blocked when the FIRST reported hit belongs to a "
        "CollisionNode with physicsType 1 (0x48b506).  data: `sheet_has_ai_bit` = the "
        "node's pivot sheet (pivotSheet_Id) has a bit of the level's AIWorldNode "
        "collisionMask; `blocks` = that and physicsType 1.  a stored pivotSheet_Id 0 is no "
        "sheet (read: 0x4a4c44; mask 0 through 0x48e154, inferred to be the shape's mask "
        "word), so `blocks` is false.  null where the node does not store the property "
        "(constructor defaults read: physicsType 1 and the first sheet of "
        "/pivotbooks/default.pb, 0x4a8944; not applied here) or a non-zero id is in no pivot "
        "book read.  `sheet_source` says which case holds.  level.ai_world.generation: path-data generation inputs; this "
        "executable cannot regenerate (CreatePathData, CreateLocalPathData and "
        "UpdateAIDefinition are the stub 0x48d55e)"
    ),
    "hero_models": (
        "data: the LevelSceneCtrl node's references _emodelrsh, _emodelnto, _emodelntohead, "
        "_emodelrshrage, _emodelntoflashing and the modelNames of the node each one names "
        "(read: CharacterDef.command_get_override_model 0x666d03 takes the model of types "
        "0 and 1 from LevelSceneCtrl.command_get_override_model 0x76ef49)"
    ),
    "characters": (
        "data: CharacterRoot nodes; export.character is the stem of the fragment that holds "
        "the CharacterDef of the placement's type (the folder `watchmen characters` writes). "
        "`variant` and `weapon`: see evidence.variants"
    ),
    "variants": (
        "read: CharacterModelCollection.command_get_model 0x66ca15 (PS3 0x71a980) picks the "
        "member: with a non-zero request the LAST member whose m_iprioritymodel equals it, "
        "otherwise the member with the lowest live instance count, the first in child "
        "order on a tie (strict <); the count rises when a character is built and falls "
        "when its visual is deleted (0x67909b).  The member list is the collection's "
        "children in sibling order (initialize_local 0x66cd2a).  Body: "
        "CharacterDef.command_get_override_model 0x666d03 with the placement's "
        "m_iprioritymodel; without a collection the level's LevelSceneCtrl names the model "
        "(types 0 and 1 only, 0x76ef49).  Weapon: CharacterRoot.command_set_weapon 0x694378 "
        "with m_ipriorityweaponmodel, collection by _iweapontype (0 = bash_1h, 1 = bash_2h; "
        "-1 or a null collection = no weapon); weapon collections are shared between "
        "definitions (collection_uid), so their counts are too.  A `candidates` result "
        "depends on the build / delete history of the play session, not on the level "
        "file alone: the status is what the file fixes.  not established: whether a "
        "checkpoint restart resets the counts of the enemy collections, which are in the "
        "level block; the weapon collections are outside it and are neither reset nor "
        "decreased; the order in which start-activated "
        "characters are built.  The nodes the LevelSceneCtrl names for the two heroes are "
        "in level.hero_models.  `weapon.no_collection`: the placement asks for a 1H or 2H "
        "weapon and the definition's collection for it is null, so the engine gives no "
        "weapon (0x694440)"
    ),
    "ai_start": (
        "data: CharacterRoot.m_istateofmind (`unset` when the placement has no value; what "
        "such a character starts as is not established).  read: Enemy.Evaluate 0x72587d -- "
        "a PASSIVE enemy (0x726214 -> 0x7264a2) only returns to its combat zone or idles "
        "(0x726fc3); it does not chase or attack until it is AGGRESSIVE.  It becomes "
        "AGGRESSIVE when it reacts to an attack, takes damage, is the target of an attack, "
        "or by a SET_AI_STATE action (TriggerActionCharacter.SetAIState 0x852a28 writes "
        "m_iinteger1 to every character the action lists).  `set_ai_state` = those actions: "
        "the action's list is built at initialize_local 0x855ecb from m_etarget1 -- the node "
        "itself when it is a CharacterRoot, else every CharacterRoot below it, not looking "
        "below a CharacterRoot (AILib 0x59d5db)"
    ),
    "groups": (
        "read: CharacterGroup.initialize_local 0x668a0e (zone trigger = m_ezonetrigger, else "
        "the first child whose physicsType is 2) and initialize_external 0x668a99 "
        "(return position = position of _ereturntohometurfpoint, else of the first member, "
        "+0.5 in y; only when the group has members -- the stored m_vreturnposition is "
        "overwritten).  Members = every CharacterRoot below the group, depth first "
        "(0x66932f).  inferred: that the position the engine reads there is the node's "
        "world position, which is what `return_position` is computed from"
    ),
    "combat_presets": (
        "data: the CombatOrchestrator node (`start` = its instance values, the state at "
        "level start) and the TriggerActionGeneral TRIG actions whose m_etarget1 is a "
        "CombatOrchestratorParameters node.  read: TriggerTrig 0x851fba sends command_trig "
        "to m_etarget1; CombatOrchestratorParameters.command_trig 0x6d9128 hands the node "
        "to CombatOrchestrator.command_set_parameters; a preset with on_initialize sends "
        "itself command_trig at initialize_external 0x6d910d"
    ),
    "cube_maps": (
        "data: CubeMapNode nodes of the level.  read: a reflective surface samples the "
        "cube of the NEAREST registered CubeMapNode (squared distance between the node "
        "and the drawn object's matrix translation, 0x4d1299 / 0x56bd5f), no cube when "
        "none is registered.  read: the candidates are rebuilt every frame (0x4d5ca9, from "
        "MasterRA 0x561521) from all cube nodes: a node is one when its `enabled` byte "
        "(+0x54) and bit 0 of +0x40 are set -- together the node property globalEnabled "
        "(Node::IsEnabled 0x481762) -- and `visible` (+0x55) is set on the node and on every "
        "PVSRootNode above it (0x48e028; handle set by 0x492b67); its position is "
        "node+0x88.  read: the switch is CullingCtrl (culling.visibility_rule): it sets "
        "`visible` on every registered CullingVisibilityGroup, a PVSRootNode, from the "
        "camera position (0x70e0a4, 0x7054b8 -> 0x48f69a), so a cube node below one is a "
        "candidate only while its group is shown (cube_maps[].visibility_groups, "
        "culling.groups[].cube_maps).  measured on three D3D9 captures, counting the draws "
        "whose pixel shader samples a cube: the nearest candidate under that rule is the "
        "bound cube in 4,041 of 4,041 draws of 87 frames (file state alone: 3,254 of "
        "4,041) and in 659 of 659 draws of 18 other frames (nearest of ALL nodes of the "
        "level file: 586 of 659 -- Bordello 328 of 328, NightClub 258 of 331); in the "
        "seven frames with the camera in two groups only the union of their lists fits "
        "(312 of 312; intersection 250).  `candidate_at_load` = enabled_effective and "
        "visible_effective, the state of the FILE; inferred: that bit 0 of +0x40 is the "
        "enabled state of the parents; not established: any other switch of the flags at "
        "run time.  models[].cube_map applies the rule to the FILE state: the nearest node "
        "with candidate_at_load to the placement's world position (null without one), with "
        "its distance and whether it is of the placement's own fragment; "
        "models[].cube_map_by_area applies it per culling group; a moving object changes "
        "the answer at run time"
    ),
    "culling": (
        "data: nodes whose script class is CullingBox, with the size property of their "
        "native class.  read: CullingCtrl.InsideTest 0x7111b9 -- a point is inside iff "
        "|local| * 2 <= (width, height, depth); the depth comes from MockupBox+0x1a0, "
        "CollisionBoxNode *(+0x198)+0x2c or Light+0x174 and any other class is unbounded on "
        "z; CullingCtrl.Culling 0x70e0a4 collects the boxes with a physics overlap sphere of "
        "radius 1.0 and mask 0x10 at the test position.  read: every registered "
        "CullingVisibilityGroup is hidden except those listed by a CullingGroup that has a "
        "box containing the camera of the viewport being drawn; a camera in no box hides all "
        "of them (0x70e0a4, 0x7052b9, 0x7054b8); a box's group is the nearest ancestor with "
        "script CullingGroup, written into m_ecullinggroup at initialisation (0x70d525, "
        "0x704f9b)"
    ),
    "movies": (
        "data: MoviePlayerCtrl nodes; subtitle_table = textres of the SubtitleSlot the "
        "movie's subtitleSlot names (the cutscene's timed text table), continue_link = "
        "m_econtinuelink, the movie played next (read: command_link 0x7c3a04)"
    ),
    "files": (
        "data: block file names = the base name of the top fragment's path, lower-cased as "
        "the archives store them, with the block extensions (checked against the archive "
        "directory and the loose Part 1 trees on all 39 levels of the six sets; the loose "
        "trees spell the names with the fragment's letter case); data: loose files and "
        "movies.  `terrain`: data: the TerrainNode's properties, `world` composed like every "
        "placement (conventions.world); read: the terrain is drawn with the identity matrix, "
        "not the node's transform (0x49c3be; world-matrix slot 0x5691b7 / 0x5682aa / 0x576d17; "
        "Xbox 360 0x829d8750, 0x829a31d0); data: all 24 TerrainNodes of the six sets compose "
        "to the origin; `scale` is null because the node has no scale "
        "property"
    ),
    "checkpoints": "read: GameStateCtrl 0x74f382 (reach) / 0x74f5f1 (restore); data: the children",
    "spawn_recipe": "data: fragment headers with reapplyable = 1 (read: header 0x54306d)",
    "path_objects": (
        "data: AIStaticPathObjectNode nodes and their AIStaticPathObjectVertexNode children "
        "(world positions).  `nav` (the entry of the level's .hpd path-object table) is "
        "matched BY ID first.  read: a path-object id is the 1-based index into the "
        "serialised list property aiStaticPathObjectNodes of the level's AIWorldNode "
        "(lookup 0x4837d5, X360 0x829f8260; property registered in 0x484ffb, setter "
        "0x483844), written when the path data was generated; nothing adds to the list at "
        "run time.  `ai_world_index` is that index.  A table entry whose list entry is null "
        "or does not resolve (the engine leaves such a path object unbound) falls back to "
        "the POSITION rule: the end points of the graph edges that carry the path object "
        "against the vertex nodes.  The position distance is computed for every id-joined "
        "pair as a cross-check (nav.id_position_disagree).  Part 2 PC, Bordello / NightClub / "
        "StreetsOfRiot: 127 of 128 entries join by id, each within 0.16 m of its node; "
        "Bordello id 45 is a null list entry and joins by position (0.1196 m).  "
        "`bound_at_run_time`: read: the path data's path object looks its node up by id "
        "(KynapseStaticPathObject 0x48c249 -> 0x4837d5), stores itself in the node "
        "(+0x138) and takes over the node's impassable flag; "
        "AIStaticPathObjectNode::SetIsImpassable 0x48a559 reaches the path data only "
        "through +0x138.  A node that is not in the list (ai_world_index null) is never "
        "found, so it stays unbound and its flags do not reach the path finder; "
        "counts.path_objects_unbound.  data, the six-set export: every path-object table "
        "has as many entries as its level's list; unbound nodes are the 4 of Part 1 "
        "ConstructionSite (all disabled, list and table empty), 1 of Part 1 Streets (an "
        "enabled copy of the StreetsRollerDoor template's nodes placed in "
        "MissionStructure.fragment; list and table 14, nodes 15) and the Bordello node of "
        "the null entry 45"
    ),
}


def enum_name(family, value):
    """Name of `value` in an enum family, None when the family has no such value.  A
    family this module does not list is looked up in engine_enums (CHARACTER_TYPES)."""
    if family in ENUMS:
        return ENUMS[family].get(_signed(value))
    import engine_enums

    try:
        return engine_enums.name(family, value)
    except Exception:
        return None


def _signed(v):
    return v - (1 << 32) if isinstance(v, int) and v >= 0x80000000 else v


# ---------------------------------------------------------------- transforms


def q_mul(a, b):
    """Hamilton product a (x) b of two (x, y, z, w) quaternions."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def q_rot(q, v):
    """`v` rotated the engine's way: conj(q) * v * q."""
    c = [-q[0], -q[1], -q[2], q[3]]
    r = q_mul(q_mul(c, [v[0], v[1], v[2], 0.0]), q)
    return r[:3]


def compose(parent, pos, quat):
    """World (pos, quat) of a node with local (pos, quat) under `parent` (pos, quat)."""
    if parent is None:
        return list(pos), list(quat)
    pp, pq = parent
    r = q_rot(pq, pos)
    return [pp[0] + r[0], pp[1] + r[1], pp[2] + r[2]], q_mul(quat, pq)


def gltf_trs(pos, quat, frame=None):
    """glTF node {translation, rotation} that places a toolkit GLB at an engine world
    transform, for GLBs written in `frame` (default frame.mode()).

    mirrored: the position unchanged, the rotation conjugated (glTF rotates with
    q * v * conj(q)).  true: that transform reflected with the GLBs (x -> -x):
    translation (-x, y, z), rotation (-qx, qy, qz, qw)."""
    if _frame.is_true(frame):
        return {
            "translation": [_r(-pos[0]), _r(pos[1]), _r(pos[2])],
            "rotation": [_r(-quat[0]), _r(quat[1]), _r(quat[2]), _r(quat[3])],
        }
    return {
        "translation": [_r(x) for x in pos],
        "rotation": [_r(-quat[0]), _r(-quat[1]), _r(-quat[2]), _r(quat[3])],
    }


def forward(quat):
    """World direction of the local +Z axis."""
    return q_rot(quat, [0.0, 0.0, 1.0])


def yaw_deg(quat):
    f = forward(quat)
    return math.degrees(math.atan2(f[0], f[2]))


def _r(x, n=6):
    x = round(float(x), n)
    return 0.0 if x == 0 else x


# ---------------------------------------------------------------- loading


def find_scenes(extract_out):
    """Every `*.scene` under EXTRACT_OUT/extracted (EXTRACT_OUT may also be the
    `extracted` folder itself)."""
    base = extract_out
    if os.path.isdir(os.path.join(extract_out, "extracted")):
        base = os.path.join(extract_out, "extracted")
    hits = set()
    for ext in ("*.scene", "*.scene.json"):
        for f in glob.glob(os.path.join(base, "**", ext), recursive=True):
            hits.add(f[:-5] if f.endswith(".json") else f)
    return sorted(hits)


def _is_level_scope(n):
    return (n.type or "").endswith("(LoadBlock)") and bool(n.p("assetName"))


def scene_levels(scene_path):
    """[(name, node id, asset)] of the load-block scopes of a scene file, in tree order."""
    import anim_state_machine as asm

    roots = asm.load_tree(scene_path, resolve_fragments=False)
    return [(n.name or n.id, n.id, n.p("assetName")) for n in asm.walk(roots) if _is_level_scope(n)]


def load_level_tree(scene_path, scope_id):
    """The scene with ONE level instanced: every fragment host is spliced (the game
    essentials too, which the level's references point into) except the other
    levels' load blocks.  -> (roots, scope node)."""
    import anim_state_machine as asm

    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))

    def hosts(n, asset):
        return not _is_level_scope(n) or n.id == scope_id

    roots = asm.load_tree(scene_path, hosts=hosts)
    scope = next((n for n in asm.walk(roots) if n.id == scope_id and _is_level_scope(n)), None)
    if scope is None:
        raise ValueError("no load block %s in %s" % (scope_id, scene_path))
    return roots, scope


def _native(n):
    ty = n.type or ""
    return ty[ty.index("(") + 1 : -1] if ty.endswith(")") and "(" in ty else ty


def instance_chain(inst):
    """'scene/<host id>/...': the host node ids from the scene file down to `inst`."""
    ids = []
    seen = set()
    while inst is not None and inst.host is not None and id(inst) not in seen:
        seen.add(id(inst))
        ids.append(str(inst.host.id))
        inst = inst.host.inst
    return "/".join(["scene"] + ids[::-1])


def instance_stable_id(inst):
    """Platform-stable id of a fragment instance: 8 hex digits of the SHA-1 of its
    host chain (instance_chain).  It names WHERE the instance hangs, not when it was
    loaded, so a fragment missing on one platform does not renumber the rest."""
    import hashlib

    return hashlib.sha1(instance_chain(inst).encode("utf-8")).hexdigest()[:8]


def _own_visible(n):
    """The node's own `visible` property (default true), whatever letter case the
    key table spells it in."""
    v = n.p("Visible")
    if v is None:
        v = n.p("visible")
    return v is not False


class _Level:
    """The loaded tree of one level with what every section needs: uids, world
    transforms, effective enabled state, reference resolution."""

    def __init__(self, roots, scope):
        import anim_state_machine as asm

        self.asm = asm
        self.roots, self.scope = roots, scope
        self.nodes = asm.walk(roots)
        self.index = asm.node_index(roots, self.nodes)
        self.insts, num = [], {}
        for n in self.nodes:
            if n.inst is not None and id(n.inst) not in num:
                num[id(n.inst)] = len(self.insts)
                self.insts.append(n.inst)
        self._num = num
        self.uid = {id(n): "%d:%s" % (num.get(id(n.inst), 0), n.id) for n in self.nodes}
        self.stable_ids = [instance_stable_id(i) for i in self.insts]
        self.world, self.enabled = {}, {}
        # visible on the node and on its PVSRootNode ancestors (engine 0x48e028; handle set
        # by 0x492b67)
        self.visible = {}
        self.pvs = {}  # id(node) -> nearest PVSRootNode ancestor or None
        for n in self.nodes:  # parents first
            par = n.parent
            pw = self.world.get(id(par)) if par is not None else None
            pos, quat = n.p("localPos"), n.p("localOrient")
            if isinstance(pos, list) and isinstance(quat, list) and len(quat) == 4:
                # parentLink = 1 composes like any node (0x48d789; the flag only gates later
                # parent moves in play mode, 0x4932d4)
                self.world[id(n)] = compose(pw, pos, quat)
            elif pw is not None:
                self.world[id(n)] = pw  # no transform of its own: its children hang from above
            pe = self.enabled.get(id(par), True) if par is not None else True
            self.enabled[id(n)] = pe and n.p("enabled", True) is not False
            pvs = None
            if par is not None:
                pvs = par if _native(par) == "PVSRootNode" else self.pvs.get(id(par))
            self.pvs[id(n)] = pvs
            self.visible[id(n)] = _own_visible(n) and (
                self.visible[id(pvs)] if pvs is not None else True
            )
        self.level = asm.walk(scope)
        self.in_level = set(id(n) for n in self.level)
        self.unresolved = []
        self.resolved = 0
        self._cache = {}

    def has_transform(self, n):
        return isinstance(n.p("localPos"), list) and isinstance(n.p("localOrient"), list)

    def inst_index(self, n):
        return self._num.get(id(n.inst), 0)

    def stable_uid(self, n):
        """`uid` of the node without the load-order ordinal (conventions "stable_uid")."""
        k = self._num.get(id(n.inst))
        return "%s@%s" % (n.id, self.stable_ids[k] if k is not None else instance_stable_id(None))

    def resolve(self, n, prop):
        """Target node of reference property `prop` of `n` (None for a null or
        unresolved reference; unresolved ones are recorded once)."""
        key = (id(n), prop)
        if key in self._cache:
            return self._cache[key]
        ref = n.p(prop)
        t = None
        if isinstance(ref, dict) and ref.get("etag") not in (0, 1):
            t = self.asm.resolve_ref(n, ref, self.index)
            if t is None:
                self.unresolved.append(
                    {
                        "node": self.uid[id(n)],
                        "class": n.cls,
                        "name": n.name,
                        "property": prop,
                        "reference": ref,
                        "fragment": n.inst.asset if n.inst is not None else None,
                    }
                )
            else:
                self.resolved += 1
        self._cache[key] = t
        return t

    def xform(self, n):
        w = self.world.get(id(n))
        if w is None:
            return None
        pos, quat = w
        return {"pos": [_r(x) for x in pos], "quat": [_r(x) for x in quat]}

    def placement(self, n):
        w = self.world.get(id(n))
        if w is None:
            return {}
        fwd = [_r(x, 4) for x in forward(w[1])]
        yaw = _r(yaw_deg(w[1]), 2)
        if _frame.is_true():  # forward / yaw_deg go with `gltf`
            fwd = [_r(v) for v in _frame.vec(fwd)]
            yaw = _r(_frame.yaw_deg(yaw, half_open_low=False))
        return {
            "world": self.xform(n),
            "gltf": gltf_trs(w[0], w[1]),
            "forward": fwd,
            "yaw_deg": yaw,
        }

    def chain_without_transform(self, n):
        """Script classes of the ancestors between `n` and its nearest ancestor with a
        transform, nearest first ([] when the direct parent has one or `n` is a root)."""
        out, par = [], n.parent
        while par is not None and not self.has_transform(par):
            out.append(par.cls)
            par = par.parent
        return out

    def brief(self, n):
        return {"uid": self.uid[id(n)], "class": n.cls, "name": n.name}

    def path(self, n):
        return "/".join((x.name or x.cls or "?") for x in reversed(self.asm._chain(n)))


def _refs(n):
    return [k for k, v in n.props.items() if isinstance(v, dict) and k != "logicalParent"]


def _params(lv, n):
    """(params, names): the node's own properties, references as target uids, and
    the enum names of the integer properties that have a family."""
    out, names = {}, {}
    for k, v in n.props.items():
        if k in _STD:
            continue
        if isinstance(v, dict):
            t = lv.resolve(n, k)
            if t is not None:
                out[k] = {"to": lv.uid[id(t)], "class": t.cls, "name": t.name}
            elif v.get("etag") in (0, 1):
                out[k] = None
            else:
                out[k] = {"to": None, "reference": v}
            continue
        if isinstance(v, int) and not isinstance(v, bool):
            v = _signed(v)
            fam = PROP_ENUMS.get((n.cls, k))
            if fam is not None and enum_name(fam, v) is not None:
                names[k] = enum_name(fam, v)
            fam = PROP_FLAGS.get((n.cls, k))
            if fam is not None:
                names[k] = [nm for bit, nm in sorted(ENUMS[fam].items()) if v & bit]
        out[k] = v
    return out, names


def _kind(n):
    c = n.cls or ""
    if c.startswith("TriggerCondition"):
        return "condition"
    if c.startswith("TriggerAction"):
        return "action"
    if c in ("TriggerUse", "TriggerUseFragment"):
        return "use"
    if c in ("TriggerCounterScript", "TriggerThreshold"):
        return "counter"
    if c == "CharacterGroup":
        return "group"
    if c.startswith("Trigger") and "(" in (n.type or ""):
        return "trigger"
    return None


def _ref_list(lv, n, prop):
    """The nodes a list-of-references property names (null and unresolved entries are
    left out)."""
    out = []
    refs = n.p(prop)
    for ref in refs if isinstance(refs, list) else ():
        if not isinstance(ref, dict) or ref.get("etag") in (0, 1):
            continue
        t = lv.asm.resolve_ref(n, ref, lv.index)
        if t is not None:
            out.append(t)
    return out


def _is_sequence_action(n):
    """A child a PropertySequenceNode fires: script class with command_fire_action(entity)
    and _ndelay (class-level tests 0x4f9376 / 0x4f934b in 0x4ab230)."""
    return (n.cls or "").startswith("TriggerAction") or n.cls == "DelayedEmitterActivator"


_FILTER_EXPOSED = None


def filter_exposed():
    """wlib/filter_exposed.json: which properties the editor's property filter shows per
    action / use type (TriggerActionGeneral 0x85e3e8, TriggerActionParticle 0x86038f,
    TriggerUseFragment 0x873568)."""
    global _FILTER_EXPOSED
    if _FILTER_EXPOSED is None:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "filter_exposed.json"), encoding="utf-8") as fh:
            _FILTER_EXPOSED = json.load(fh)
    return _FILTER_EXPOSED


def _use_trigger_of(lv, n):
    """The first descendant of a TriggerUseFragment that is named "TriggerUse"."""
    return next((d for d in lv.asm.walk(n)[1:] if d.name == "TriggerUse"), None)


def applies(lv, n):
    """Sorted names of the properties that apply to `n` for its action type (general and
    particle actions) or for the use type of its use trigger (TriggerUseFragment; -1
    without one), as the class's property filter shows them; None for any other class
    or a value the table has no row for."""
    spec = filter_exposed()["classes"].get(n.cls)
    if spec is None:
        return None
    if n.cls == "TriggerUseFragment":
        t = _use_trigger_of(lv, n)
        value = t.p("m_iusetype") if t is not None else -1
    else:
        value = n.p("m_iactiontype", 0)
    value = _signed(value) if isinstance(value, int) and not isinstance(value, bool) else -1
    row = spec["by_value"].get(str(value)) or spec.get("other_value")
    if row is None:
        return None
    out = []
    for k in row["applies"]:
        if "<k>" in k:
            cnt = n.p("m_ilocksegmentcount", 0)
            cnt = cnt if isinstance(cnt, int) and not isinstance(cnt, bool) else 0
            out += [k.replace("<k>", str(i)) for i in range(1, min(cnt, 10) + 1)]
        else:
            out.append(k)
    return sorted(out)


#: TriggerActionSound: action type -> {property: caption} of the properties its filter
#: shows (FilterExposedProperties 0x861606)
TRIGGER_ACTION_SOUND_PARAMS = {
    0: {
        "m_etarget1": "Sound slot",
        "m_etarget2": "Attach to",
        "m_iinteger1": "Track no.",
        "m_nnumber4": "Fade time",
        "m_ttruth1": "Attach to activator",
        "m_ttruth2": "Stop sounds on attach?",
        "m_ttruth3": "Pause Speak System while playing",
    },
    1: {"m_etarget1": "Sound slot", "m_nnumber4": "Fade time"},
    2: {"m_etarget1": "Group node", "m_nnumber4": "Fade time"},
    3: {"m_nnumber4": "Fade time"},
    4: {
        "m_etarget1": "Fade from sound",
        "m_etarget2": "Fade to sound",
        "m_etarget3": "Attach to",
        "m_iinteger1": "Track no.",
        "m_nnumber4": "Fade time",
        "m_ttruth1": "Attach to activator",
    },
    5: {"m_etarget1": "Group node"},
    6: {"m_etarget1": "Group node"},
    7: {"m_etarget1": "Group node", "m_nnumber4": "Volume", "m_nnumber5": "Fade time"},
    8: {"m_etarget1": "Set music setup"},
    9: {
        "m_etarget1": "Music state",
        "m_nnumber1": "Play time",
        "m_ttruth1": "Set As Default",
        "m_ttruth2": "Play Static",
    },
    10: {},
    11: {"m_etarget1": "Music intensity definition"},
    12: {"m_etarget1": "Next default music state"},
    13: {"m_etarget1": "SoundDef", "m_nnumber1": "Volume", "m_nnumber2": "Fade time"},
}
#: the TriggerActionSound types whose sound sends command_sound_done to the action
#: (SOUND_PLAY and CROSS_FADE pass the callback, 0x862b6c; sender 0x82aecf)
SOUND_DONE_TYPES = (0, 4)


def sound_params(lv, n):
    """{caption: value} of the properties a TriggerActionSound node uses for its action
    type (TRIGGER_ACTION_SOUND_PARAMS); a reference is the target's name.  None for
    another class or an action type outside the table."""
    if n.cls != "TriggerActionSound":
        return None
    t = n.p("m_iactiontype", 0)
    row = TRIGGER_ACTION_SOUND_PARAMS.get(_signed(t) if isinstance(t, int) else None)
    if row is None:
        return None
    return {
        cap: (_tname(lv, n, prop) if prop.startswith("m_etarget") else n.p(prop))
        for prop, cap in row.items()
    }


def _is_action(n):
    return (n.cls or "").startswith("TriggerAction")


def _is_condition(n):
    return (n.cls or "").startswith("TriggerCondition")


def _tname(lv, n, prop):
    t = lv.resolve(n, prop)
    return (t.name or t.cls) if t is not None else None


def _label(lv, n, names):
    """A one-line reading of a condition or action node."""
    c = n.cls or ""
    act = names.get("m_iactiontype") or names.get("_iaction")
    if c == "TriggerActionCharacter":
        who = names.get("m_itargettype")
        if who in (None, "ENTITYREF"):
            who = _tname(lv, n, "m_etarget1")
        return "%s %s" % (act or "action %s" % n.p("m_iactiontype"), who or "-")
    if c in ("TriggerActionGeneral", "TriggerActionSound", "TriggerActionParticle"):
        s = "%s %s" % (act or "action %s" % n.p("m_iactiontype"), _tname(lv, n, "m_etarget1"))
        if c == "TriggerActionGeneral" and _signed(n.p("m_iactiontype", 0)) in (10, 11, 12):
            s += " (no effect)"  # 0x85f77b: empty handlers / no branch
        return s
    if c == "TriggerActionCharacterForceMove":
        who = _tname(lv, n, "m_eactivatorgroup")
        return "%s %s -> %s" % (act, who, _tname(lv, n, "m_emovetotargetgroup1"))
    if c == "TriggerActionDelay":
        return "DELAY"
    if c == "TriggerActionCheckpoint":
        return "CHECKPOINT %s" % n.p("_icheckpointid")
    if c == "TriggerActionCamera":
        return "%s %s" % (act, _tname(lv, n, "_ecamera") or n.name)
    if c == "TriggerActionMovie":
        t = lv.resolve(n, "m_emovie")
        return "MOVIE %s" % ((t.p("movie") or t.name) if t is not None else None)
    if c == "TriggerActionGameEvent":
        return "GAME_EVENT %s" % (names.get("m_iactioneventtype") or n.p("m_iactioneventtype"))
    if c == "TriggerActionGameMode":
        return "IF MODE %s" % "|".join(names.get("_igamemodetype") or [])
    if c == "TriggerActionBase":
        return "GROUP"
    if c == "TriggerConditionCollision":
        vol = lv.resolve(n, "m_etriggerentity") or n.parent
        return "%s by %s in %s" % (
            names.get("m_itrueon"),
            names.get("m_iactivator"),
            (vol.name or vol.cls) if vol is not None else None,
        )
    if c == "TriggerConditionGameEvent":
        return "ON EVENT %s" % (names.get("m_itrueon") or n.p("m_itrueon"))
    if c == "TriggerConditionLogical":
        k = names.get("m_iconditiontype")
        return "%s %s" % (k, n.p("m_icount")) if k == "SOME" else str(k)
    if c == "TriggerConditionToggle":
        return "TOGGLE (fires on %s)" % ("true" if n.p("_tfireon") else "false")
    if c == "TriggerConditionGameMode":
        return "MODE %s" % "|".join(names.get("_igamemodetype") or [])
    if c == "TriggerConditionCharacter":
        return "%s %s%% %s" % (
            names.get("_iconditiontype"),
            n.p("_nvalue1"),
            _tname(lv, n, "_echaracter"),
        )
    if c == "TriggerConditionTrue":
        if n.p("m_treactivatable") is True:
            return "ON LOAD, every %s s" % n.p("m_treactivationdelay")
        return "ON LOAD"
    if c == "TriggerUse":
        return "USE %s by %s" % (names.get("m_iusetype"), names.get("_iactivatortype"))
    if c == "TriggerUseFragment":
        t = _use_trigger_of(lv, n)
        if t is None:
            return c
        tn = _params(lv, t)[1]
        return "USE %s by %s" % (tn.get("m_iusetype"), tn.get("_iactivatortype"))
    if c == "TriggerConditionVisibility":
        return "LOOK+USE %s within %s m" % (names.get("_icharacter"), n.p("_nmaxdist"))
    return c


def forced_state(n):
    """`forced_state` of a TriggerActionCharacter node of action type 28
    (REQUEST_FORCED_STATE), what ActionExecute 0x85b858 sends; None for other nodes."""
    if n.cls != "TriggerActionCharacter" or _signed(n.p("m_iactiontype", -1)) != 28:
        return None
    state = _signed(n.p("m_iinteger2", 0))
    out = {"state": state, "state_name": ENEMY_STATES.get(state)}
    t = n.p("m_nnumber1", 0.0)
    if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0:
        ai = _signed(n.p("m_iinteger1", 0))
        out.update(
            {
                "for_ai_type": ai,
                "for_ai_type_name": AI_TYPES.get(ai),
                "criteria_if_match": 10,
                "criteria_names_if_match": ["TIMER", "STATE_NOT_RUNNING"],
                "time_s_if_match": t,
            }
        )
    out.update(
        {
            "criteria_otherwise": 8,
            "criteria_names_otherwise": ["STATE_NOT_RUNNING"],
            "time_s_otherwise": 0.0,
            "evidence": "code 0x85b858 case 28; AI type from 0x5974a3",
        }
    )
    return out


_SHEETS = {}


def pivot_sheets(extract_out=None):
    """({sheet id: record}, source): the pivot sheets by the integer a node stores in
    pivotSheet_Id.  From the extract's own pivotbooks/*.pb.json when there are any
    (the Part 1 books differ), else the bundled PC Part 2 table (pivot_sheets.json)."""
    key = os.path.abspath(extract_out) if extract_out else None
    if key in _SHEETS:
        return _SHEETS[key]
    rows, source = [], "bundled PC Part 2 table (wlib/pivot_sheets.json)"
    if extract_out:
        for d in (extract_out, os.path.join(extract_out, "extracted")):
            for f in sorted(glob.glob(os.path.join(d, "pivotbooks", "*.pb.json"))):
                try:
                    with open(f, encoding="utf-8") as fh:
                        blocks = json.load(fh).get("blocks") or []
                except (OSError, ValueError):
                    continue
                for b in blocks:
                    pr = {x.get("key"): x.get("value") for x in b.get("props") or []}
                    uid = pr.get("uniqueID")
                    if not (isinstance(uid, dict) and isinstance(uid.get("hex"), str)):
                        continue
                    rows.append(
                        {
                            "book": "/pivotbooks/" + os.path.basename(f)[: -len(".json")],
                            "name": pr.get("name"),
                            "unique_id": uid["hex"],
                            "collision_mask": pr.get("collisionMask"),
                            "friction": pr.get("friction"),
                            "restitution": pr.get("restitution"),
                        }
                    )
            if rows:
                source = "pivot books of the extract"
                break
    if not rows:
        with open(os.path.join(_HERE, "pivot_sheets.json"), encoding="utf-8") as fh:
            rows = json.load(fh)["sheets"]
    table = {}
    for r in rows:
        try:
            raw = bytes.fromhex(r["unique_id"])
        except ValueError:
            continue
        if len(raw) != 8:
            continue
        # the hex is the 8 stored bytes: two u32 words, low word first, each in the
        # platform's byte order (PC 63f07e44 2f0f1807, consoles 447ef063 07180f2f)
        table.setdefault(int.from_bytes(raw, "little"), r)
        lo, hi = int.from_bytes(raw[:4], "big"), int.from_bytes(raw[4:], "big")
        table.setdefault(lo | (hi << 32), r)
    _SHEETS[key] = (table, source)
    return _SHEETS[key]


#: `sheet_source` of a collision node that stores pivotSheet_Id 0
SHEET_SOURCE_NONE = "none (stored id 0, 0x4a4c44)"


def ai_sight(n, ai_mask, sheets):
    """`ai_sight` of a collision node: does the AI sight ray (0x48b44e) report it and
    does it block.  `ai_mask` = the level's AIWorldNode.collisionMask (None without
    one), `sheets` = the first result of pivot_sheets().  A stored sheet id 0 is no sheet
    (0x4a4c44): mask 0, never reported.  A property the node does not store gives null
    (the constructor defaults are physicsType 1 and the first sheet of
    /pivotbooks/default.pb, 0x4a8944; no exported volume lacks either)."""
    pt = n.p("physicsType")
    pt = _signed(pt) if isinstance(pt, int) and not isinstance(pt, bool) else None
    sid = n.p("pivotSheet_Id")
    stored = isinstance(sid, int) and not isinstance(sid, bool)
    sheet = sheets.get(sid) if stored and sid != 0 else None
    if stored and sid == 0:
        mask, source = 0, SHEET_SOURCE_NONE
    elif sheet:
        mask, source = sheet.get("collision_mask"), "stored id"
    else:
        mask, source = None, ("id in no pivot book read" if stored else "not stored")
    bit = None
    if isinstance(mask, int) and isinstance(ai_mask, int) and not isinstance(ai_mask, bool):
        bit = bool(mask & ai_mask)
    return {
        "sheet": sheet["name"] if sheet else None,
        "sheet_book": sheet["book"] if sheet else None,
        "sheet_collision_mask": mask,
        "sheet_has_ai_bit": bit,
        "physics_type": pt,
        "blocks": None if bit is None or pt is None else bool(pt == 1 and bit),
        "sheet_source": source,
    }


def _volume(lv, n):
    """Shape of a collision node: box (width x, height y, depth z), sphere, capsule."""
    nat = _native(n)
    out = lv.brief(n)
    out["native"] = nat
    if nat == "CollisionBoxNode":
        out["shape"] = "box"
        out["size"] = [n.p("width"), n.p("height"), n.p("depth")]
    elif nat == "CollisionSphereNode":
        out["shape"] = "sphere"
        out["radius"] = n.p("radius")
    elif nat == "CollisionCapsuleNode":
        out["shape"] = "capsule"
        out["radius_or_width"] = n.p("width")
        out["height"] = n.p("height")
    out["enabled"] = lv.enabled[id(n)]
    out.update(lv.placement(n))
    return out


_VOLUME_NATIVES = ("CollisionBoxNode", "CollisionSphereNode", "CollisionCapsuleNode")


def _child_when(parent, i):
    """How a child action of `parent` is fired: (when, delay seconds or None)."""
    c = parent.cls
    if c == "TriggerActionDelay":
        d = parent.p("m_ndelaynumber%d" % i, 0.0) if i < 20 else 0.0
        return "delay", d
    if c == "TriggerActionCheckpoint":
        return "restore", None
    if c == "TriggerActionMovie":
        return "after_movie", None
    if c == "TriggerActionGameMode":
        return "mode", None
    if c == "TriggerActionSound" and parent.p("_tchildrenafter"):
        return "after_sound", None
    if c == "TriggerActionCamera" and parent.p("_iaction") == 0:
        # a direct action child of a tour is fired only by the base handler (0x84b299,
        # 0x84aea3, 0x84bde2): the timed cuts are children of the tour's sequence node
        return "tour_refire", None
    return "immediate", None


# ---------------------------------------------------------------- sections


def _section_graph(lv):
    nodes, edges, by_uid = [], [], {}

    def add(n, kind):
        u = lv.uid[id(n)]
        if u in by_uid:
            return by_uid[u]
        params, names = _params(lv, n) if kind != "object" else ({}, {})
        rec = {
            "uid": u,
            "stable_uid": lv.stable_uid(n),
            "id": n.id,
            "kind": kind,
            "class": n.cls,
            "native": _native(n),
            "name": n.name,
            "enabled": n.p("enabled", True) is not False,
            "enabled_effective": lv.enabled[id(n)],
            "parent": lv.uid[id(n.parent)] if n.parent is not None else None,
            "fragment": n.inst.asset if n.inst is not None else None,
        }
        if id(n) not in lv.in_level:
            rec["external"] = True  # game essentials or scene, outside the load block
        if kind != "object":
            rec["label"] = _label(lv, n, names)
            rec["params"] = params
            if names:
                rec["names"] = names
            fs = forced_state(n)
            if fs is not None:
                rec["forced_state"] = fs
            ap = applies(lv, n)
            if ap is not None:
                rec["applies"] = ap
            sp = sound_params(lv, n)
            if sp is not None:
                rec["sound_params"] = sp
        if lv.has_transform(n):
            rec["world"] = lv.xform(n)
        by_uid[u] = rec
        nodes.append(rec)
        return rec

    graph_nodes = [(n, _kind(n)) for n in lv.level]
    graph_nodes = [(n, k) for n, k in graph_nodes if k]
    for n, k in graph_nodes:
        add(n, k)
    for n, k in graph_nodes:
        u = lv.uid[id(n)]
        acts = [c for c in n.children if _is_action(c)]
        if k == "condition":
            for i, c in enumerate(acts):
                edges.append({"from": u, "to": lv.uid[id(c)], "kind": "action", "order": i})
            if n.parent is not None and _is_condition(n.parent):
                edges.append({"from": u, "to": lv.uid[id(n.parent)], "kind": "input"})
            if n.cls == "TriggerConditionCollision" and lv.resolve(n, "m_etriggerentity") is None:
                if n.parent is not None:
                    add(n.parent, _kind(n.parent) or "object")
                    edges.append(
                        {"from": u, "to": lv.uid[id(n.parent)], "kind": "volume", "default": True}
                    )
        elif k == "action":
            for i, c in enumerate(acts):
                when, delay = _child_when(n, i)
                e = {"from": u, "to": lv.uid[id(c)], "kind": "child", "order": i, "when": when}
                if delay is not None:
                    e["delay"] = delay
                if when == "after_sound":
                    t = n.p("m_iactiontype", 0)
                    if (_signed(t) if isinstance(t, int) else None) not in SOUND_DONE_TYPES:
                        e["sound_done"] = False  # held for a command nothing sends (0x86150a)
                edges.append(e)
        elif k == "group":
            for c in lv.asm.walk(n)[1:]:
                if c.cls == "CharacterRoot":
                    edges.append({"from": u, "to": lv.uid[id(c)], "kind": "member"})
                    add(c, "object")
        for prop in _refs(n):
            t = lv.resolve(n, prop)
            if t is None:
                continue
            add(t, _kind(t) or "object")
            edges.append(
                {
                    "from": u,
                    "to": lv.uid[id(t)],
                    "kind": EDGE_KINDS.get(prop, "ref"),
                    "property": prop,
                }
            )
    # the action track of a sequence node (0x4ab230, 0x49d529): its direct action children
    for n in lv.level:
        if _native(n) != "PropertySequenceNode":
            continue
        acts = [c for c in n.children if _is_sequence_action(c)]
        if not acts:
            continue
        add(n, "object")
        u = lv.uid[id(n)]
        for c in acts:
            add(c, _kind(c) or "object")
            edges.append(
                {
                    "from": u,
                    "to": lv.uid[id(c)],
                    "kind": "sequence_action",
                    "at": c.p("_ndelay", 0.0),
                }
            )
        par = n.parent
        if par is not None and par.cls == "TriggerActionCamera" and par.p("_iaction") == 0:
            first = next((c for c in par.children if _native(c) == "PropertySequenceNode"), None)
            if first is n:
                edges.append({"from": lv.uid[id(par)], "to": u, "kind": "tour_sequence"})
    return {"nodes": nodes, "edges": edges}


#: _iweapontype -> the definition's weapon collection (command_set_weapon 0x694378)
WEAPON_COLLECTIONS = {0: "bash_1h", 1: "bash_2h"}
#: character types whose definition has no model collection and takes its model from
#: the level's LevelSceneCtrl (command_get_override_model 0x76ef49): the two heroes
SCENE_MODEL_TYPES = (0, 1)


def pick_model(members, requested):
    """What CharacterModelCollection.command_get_model (0x66ca15) does with a request,
    as far as the data fixes it.

    members     [{"index", "priority_model", ...}] in the collection's child order
    requested   the placement's m_iprioritymodel / m_ipriorityweaponmodel

    -> {status, members, requested_priority, priority_matched, rule}:
    `fixed` with the one member index -- the LAST member whose priority equals a
    non-zero request (rule `priority_last_match`), or the only member
    (`single_member`); `candidates` with every member index and rule
    `least_used_first` (lowest live instance count, first in child order on a tie:
    the result depends on which characters were built and deleted before);
    `none` for an empty collection."""
    requested = _signed(requested) if isinstance(requested, int) else 0
    hits = [m["index"] for m in members if requested != 0 and m["priority_model"] == requested]
    out = {
        "status": "candidates",
        "members": [m["index"] for m in members],
        "requested_priority": requested,
        "priority_matched": bool(hits),
        "rule": "least_used_first",
    }
    if not members:
        out.update(status="none", rule=None)
    elif hits:
        out.update(status="fixed", members=[hits[-1]], rule="priority_last_match")
    elif len(members) == 1:
        out.update(status="fixed", rule="single_member")
    return out


def _variant(d, ct, requested):
    """`variant` of a placement of character type `ct` with definition record `d`."""
    requested = _signed(requested) if isinstance(requested, int) else 0
    if d is None:
        return {
            "status": "unknown",
            "members": [],
            "requested_priority": requested,
            "priority_matched": False,
            "rule": None,
        }
    ex = d["export"]
    if ex["collection_uid"] is None:
        scene = ct in SCENE_MODEL_TYPES
        return {
            "status": "fixed_scene_model" if scene else "none",
            "members": [],
            "requested_priority": requested,
            "priority_matched": False,
            "rule": "scene_model" if scene else None,
        }
    return pick_model(ex["members"], requested)


def _weapon(d, wt, requested):
    """`weapon` of a placement with weapon type `wt` and definition record `d`."""
    requested = _signed(requested) if isinstance(requested, int) else 0
    key = WEAPON_COLLECTIONS.get(wt)
    coll = d["export"]["weapons"].get(key) if d is not None and key else None
    if coll is None:
        out = {
            "status": "none",
            "collection": key if d is not None else None,
            "collection_uid": None,
            "members": [],
            "requested_priority": requested,
            "priority_matched": False,
            "rule": None,
        }
        if d is not None and key:  # asked for a weapon the definition cannot give
            out["no_collection"] = True
        return out
    out = pick_model(coll["members"], requested)
    out = dict(out, collection=key, collection_uid=coll["collection_uid"])
    return out


def _script_roots(lv, n, cls="CharacterRoot"):
    """AILib.RecursivePushBackWithScript (0x59d5db) with early out: `n` when it has the
    script class, else the nodes of that class below it, not looking below a hit."""
    if n is None:
        return []
    if n.cls == cls:
        return [n]
    out = []
    for c in n.children:
        out.extend(_script_roots(lv, c, cls))
    return out


def _set_ai_state_actions(lv):
    """{id(CharacterRoot): [record]} of the level's SET_AI_STATE actions, per character
    the action lists (TriggerActionCharacter.initialize_local 0x855ecb, SetAIState
    0x852a28)."""
    out = {}
    for n in lv.level:
        if n.cls != "TriggerActionCharacter" or _signed(n.p("m_iactiontype", -1)) != 1:
            continue
        v = _signed(n.p("m_iinteger1", 0))
        rec = {
            "uid": lv.uid[id(n)],
            "name": n.name,
            "to": {"value": v, "name": enum_name("STATE_OF_MIND", v)},
            "enabled": lv.enabled[id(n)],
        }
        for c in _script_roots(lv, lv.resolve(n, "m_etarget1")):
            out.setdefault(id(c), []).append(rec)
    return out


def _section_characters(lv, defs):
    out = []
    switches = _set_ai_state_actions(lv)
    for n in lv.level:
        if n.cls != "CharacterRoot":
            continue
        grp = next((a for a in lv.asm._chain(n)[1:] if a.cls == "CharacterGroup"), None)
        ct = _signed(n.p("_icharactertype", -1))
        wt = _signed(n.p("_iweapontype", -1))
        som = n.p("m_istateofmind")
        d = defs.get(str(ct))
        rec = lv.brief(n)
        rec.update(
            {
                "id": n.id,
                "fragment": n.inst.asset if n.inst is not None else None,
                "path": lv.path(n),
                "group": lv.brief(grp) if grp is not None else None,
                "character_type": {"value": ct, "name": _engine_name("CHARACTER_TYPES", ct)},
                "state_of_mind": {"value": som, "name": enum_name("STATE_OF_MIND", som)},
                "weapon_type": {"value": wt, "name": _engine_name("WEAPON_TYPES", wt)},
                "priority_model": _signed(n.p("m_iprioritymodel", 0)),
                "priority_weapon_model": _signed(n.p("m_ipriorityweaponmodel", 0)),
                "start_activated": bool(n.p("_tstartactivated")),
                "enabled": lv.enabled[id(n)],
                "export": (
                    {k: d["export"][k] for k in ("character", "variants", "rule")} if d else None
                ),
                "playable": d["playable"] if d else None,
                "variant": _variant(d, ct, n.p("m_iprioritymodel", 0)),
                "weapon": _weapon(d, wt, n.p("m_ipriorityweaponmodel", 0)),
                "ai_start": {
                    "state_of_mind": (
                        "unset"
                        if som is None
                        else enum_name("STATE_OF_MIND", som) or "value %s" % _signed(som)
                    ),
                    "set_ai_state": switches.get(id(n), []),
                },
            }
        )
        rec.update(lv.placement(n))
        out.append(rec)
    return out


def _engine_name(fam, value):
    import engine_enums

    return engine_enums.name(fam, value)


VARIANT_RULE = (
    "folder of `watchmen characters` = stem of the definition's fragment; variants = the "
    "named model nodes of its model collection, in child order.  Which one a placement shows "
    "(CharacterModelCollection.command_get_model 0x66ca15, member list 0x66cd2a): with a "
    "non-zero m_iprioritymodel the LAST member whose own m_iprioritymodel equals it; otherwise "
    "the member with the lowest live instance count, the first in child order on a tie -- "
    "counts rise when a character is built and fall when its visual is deleted, so the choice "
    "depends on the history of the play session.  `members` lists every member (unnamed ones "
    "too); characters[].variant says what the level file fixes"
)


def _collection_members(lv, coll, weapon=False):
    """The members of a CharacterModelCollection as the picker sees them: its children
    in sibling order (equal orders keep file order), index = position in that list."""
    out = []
    for i, m in enumerate(coll.children):
        rec = {
            "index": i,
            "uid": lv.uid[id(m)],
            "name": m.name,
            "sibling_order": m.p("siblingOrder", 0),
            "priority_model": _signed(m.p("m_iprioritymodel", 0)),
        }
        if weapon:
            names = m.p("modelNames")
            rec["models"] = [s for s in (names if isinstance(names, list) else [names]) if s]
        else:
            rec["head_model_type"] = _signed(m.p("m_iheadmodeltype"))
        out.append(rec)
    return out


def _section_defs(lv):
    """CharacterDef nodes by character type; the level's own definitions win over
    the game essentials' (the two heroes live there)."""
    out = {}
    order = [n for n in lv.level if n.cls == "CharacterDef"]
    order += [n for n in lv.nodes if n.cls == "CharacterDef" and id(n) not in lv.in_level]
    for n in order:
        ct = _signed(n.p("m_icharactertype", -1))
        if str(ct) in out:
            continue
        asset = (n.inst.asset if n.inst is not None else None) or ""
        stem = os.path.splitext(os.path.basename(asset))[0]
        coll = lv.resolve(n, "m_eoverridemodelcollection")
        pool = lv.asm.walk(coll)[1:] if coll is not None else []
        if not any(m.p("modelNames") for m in pool) and n.parent is not None:
            pool = lv.asm.walk(n.parent)[1:]  # no collection of its own: the definition's folder
        variants = [m.name for m in pool if m.name and m.p("modelNames")]
        head = lv.resolve(coll, "_eheadmodelcollection") if coll is not None else None
        weapons = {}
        for key, prop in (("bash_1h", "m_emodelcollbash1h"), ("bash_2h", "m_emodelcollbash2h")):
            wc = lv.resolve(n, prop)
            weapons[key] = (
                {
                    "collection_uid": lv.uid[id(wc)],
                    "name": wc.name,
                    "members": _collection_members(lv, wc, weapon=True),
                }
                if wc is not None
                else None
            )
        tmpl = lv.resolve(n, "m_echaracterfragment")
        vis = lv.resolve(n, "m_emodelfragment")
        play = _signed(n.p("m_iplayablecharacter", -1))
        out[str(ct)] = {
            "uid": lv.uid[id(n)],
            "name": n.name,
            "character_type": {"value": ct, "name": _engine_name("CHARACTER_TYPES", ct)},
            "fragment": asset or None,
            "root_template": tmpl.p("assetName") if tmpl is not None else None,
            "visual": vis.p("assetName") if vis is not None else None,
            "max_health": n.p("m_nmaxhealth"),
            "faction": n.p("m_ifaction"),
            "playable": {"value": play, "name": enum_name("PLAYABLE_CHARACTERS", play)},
            "export": {
                "character": _EXPORT_NAMES.get(stem, stem) or None,
                "variants": variants,
                "collection_uid": lv.uid[id(coll)] if coll is not None else None,
                "head_collection_uid": lv.uid[id(head)] if head is not None else None,
                "members": _collection_members(lv, coll) if coll is not None else [],
                "weapons": weapons,
                "rule": VARIANT_RULE,
            },
        }
    return out


#: metres added to the y of a group's return position (double at 0x9e5dc8)
GROUP_RETURN_LIFT = 0.5


def _section_groups(lv):
    out = []
    for n in lv.level:
        if n.cls != "CharacterGroup":
            continue
        rec = lv.brief(n)
        rec["path"] = lv.path(n)
        rec["members"] = [lv.uid[id(c)] for c in lv.asm.walk(n)[1:] if c.cls == "CharacterRoot"]
        for key, prop in (
            ("all_dead", "_ealldeadaction"),
            ("zone", "m_ezonetrigger"),
            ("return_point", "_ereturntohometurfpoint"),
        ):
            t = lv.resolve(n, prop)
            rec[key] = lv.brief(t) if t is not None else None
        # initialize_local 0x668a0e: no zone trigger set -> the first child with physics type 2
        zt, zsrc = lv.resolve(n, "m_ezonetrigger"), "m_ezonetrigger"
        if zt is None:
            zt = next((c for c in n.children if c.p("physicsType") == 2), None)
            zsrc = "first_child_physics_type_2"
        rec["zone_trigger"] = dict(lv.brief(zt), source=zsrc) if zt is not None else None
        # initialize_external 0x668a99: return point, else the first member, +0.5 in y;
        # a group without members keeps the stored vector
        stored = n.p("m_vreturnposition")
        members = [c for c in lv.asm.walk(n)[1:] if c.cls == "CharacterRoot"]
        src, src_name = None, None
        if members:
            src = lv.resolve(n, "_ereturntohometurfpoint")
            src_name = "return_point"
            if src is None:
                src, src_name = members[0], "first_member"
        if src is None:
            rec["return_position"] = stored
            rec["return_position_source"] = "stored" if stored is not None else None
        else:
            w = lv.world.get(id(src))
            rec["return_position"] = (
                [_r(w[0][0]), _r(w[0][1] + GROUP_RETURN_LIFT), _r(w[0][2])] if w else None
            )
            rec["return_position_source"] = src_name
        rec["return_position_stored"] = stored
        out.append(rec)
    return out


def _preset(n):
    return {
        "engagement_dist": n.p("m_nengagementdist"),
        "attack_cooldown": n.p("m_nattackcooldown"),
        "max_attacks": n.p("m_imaxnumberofattacks"),
        "attack_frequency": n.p("m_nattackfrequency"),
        "idle_time": n.p("m_nidletime"),
    }


def _section_combat(lv):
    """The combat orchestrator's values at level start and the level's switches to a
    CombatOrchestratorParameters preset (TriggerActionGeneral TRIG on one)."""
    orch = next((n for n in lv.nodes if n.cls == "CombatOrchestrator"), None)
    start = None
    if orch is not None:
        start = lv.brief(orch)
        start.update(
            {
                "engagement_dist": orch.p("m_nengagementdist"),
                "running_characters_clamp": orch.p("m_irunningcharactersclamp"),
                "attack_cooldown": orch.p("_nattackcooldown"),
                "max_attacks": orch.p("_imaxnumberofattacks"),
                "attack_frequency": orch.p("_nattackfrequency"),
                "idle_time": orch.p("_nidletime"),
            }
        )
    presets, order, switches = {}, [], []
    for n in lv.nodes:
        if n.cls == "CombatOrchestratorParameters":
            rec = lv.brief(n)
            rec.update(_preset(n))
            rec["on_initialize"] = bool(n.p("m_toninitialize"))
            rec["switches"] = 0
            presets[id(n)] = rec
            order.append(rec)
    for n in lv.level:
        if n.cls != "TriggerActionGeneral" or _signed(n.p("m_iactiontype", -1)) != 8:
            continue
        t = lv.resolve(n, "m_etarget1")
        if t is None or id(t) not in presets:
            continue
        presets[id(t)]["switches"] += 1
        rec = {"trigger": lv.brief(n), "enabled": lv.enabled[id(n)]}
        rec["preset"] = {"uid": lv.uid[id(t)], "name": t.name}
        rec.update(_preset(t))
        switches.append(rec)
    return {"start": start, "presets": order, "switches": switches}


def _section_cube_maps(lv):
    out = []
    for n in lv.level:
        if _native(n) != "CubeMapNode":
            continue
        rec = lv.brief(n)
        rec["fragment"] = n.inst.asset if n.inst is not None else None
        rec["texture"] = n.p("texture")
        rec["texture_size"] = n.p("textureSize")
        rec["enabled"] = n.p("enabled", True) is not False
        rec["enabled_effective"] = lv.enabled[id(n)]
        rec["visible"] = _own_visible(n)
        rec["visible_effective"] = lv.visible[id(n)]
        rec["candidate_at_load"] = lv.enabled[id(n)] and lv.visible[id(n)]
        # the PVSRootNodes above the node, nearest first, and those of them CullingCtrl
        # shows and hides with the camera (CULLING_VISIBILITY_RULE)
        chain = _pvs_chain(lv, n)
        rec["visibility_groups"] = [lv.uid[id(g)] for g in chain if g.cls == VISIBILITY_GROUP]
        rec["pvs_roots"] = [lv.uid[id(g)] for g in chain]
        rec.update(lv.placement(n))
        out.append(rec)
    return out


VISIBILITY_GROUP = "CullingVisibilityGroup"


def _pvs_chain(lv, n):
    """The PVSRootNode ancestors of `n`, nearest first (the chain 0x48e028 walks)."""
    out, g = [], lv.pvs.get(id(n))
    while g is not None:
        out.append(g)
        g = lv.pvs.get(id(g))
    return out


def _area_cubes(lv):
    """[(uid, uids of the CullingVisibilityGroups above)] of the cube nodes that are
    candidates whenever those groups are shown: enabled up the tree, visible on the node
    and on every plain PVSRootNode above it (a plain root keeps its stored flag)."""
    out = []
    for n in lv.level:
        if _native(n) != "CubeMapNode" or not lv.enabled[id(n)] or not _own_visible(n):
            continue
        chain = _pvs_chain(lv, n)
        if all(_own_visible(g) for g in chain if g.cls != VISIBILITY_GROUP):
            out.append((lv.uid[id(n)], {lv.uid[id(g)] for g in chain if g.cls == VISIBILITY_GROUP}))
    return out


CUBE_MAP_RULE = (
    "a reflective surface samples the nearest CANDIDATE cube node, by squared distance to "
    "the drawn object's world translation (0x4d1299); the candidates are rebuilt every "
    "frame (0x4d5ca9): the node's own enabled flag (+0x54), bit 0 of +0x40, and visible "
    "(+0x55) on the node and every PVSRootNode above it.  read: the visible flag of a "
    "CullingVisibilityGroup (native PVSRootNode) is set every frame by CullingCtrl "
    "(0x70e0a4 -> 0x7054b8 -> Node::SetVisible 0x48f69a): shown when a CullingGroup with a "
    "box containing the camera lists it, hidden otherwise; with the camera in boxes of "
    "several groups the lists are united.  enabled_effective, visible_effective and "
    "candidate_at_load are the state of the file only.  models[].cube_map is the nearest "
    "candidate of the FILE state; models[].cube_map_by_area gives the nearest candidate "
    "per culling group for a camera in the boxes of that group alone"
)
CULLING_RULE = (
    "inside iff abs(local) * 2 <= (width, height, depth); a class without a depth "
    "property is unbounded on z (0x7111b9)"
)
CULLING_VISIBILITY_RULE = (
    "every registered CullingVisibilityGroup is hidden except those listed by a "
    "CullingGroup that has a box containing the camera of the viewport being drawn; a "
    "camera in no box hides all of them (0x70e0a4, 0x7052b9, 0x7054b8); a box's group is "
    "the nearest ancestor with script CullingGroup, written into m_ecullinggroup at "
    "initialisation (0x70d525, 0x704f9b)"
)


def _section_culling(lv):
    """Every node whose script class is CullingBox, with its box.  Every group carries
    `cube_maps`, the cube nodes that are candidates while the camera is in boxes of that
    group alone (CUBE_MAP_RULE); `cube_maps_no_box` is the list for a camera in no box."""
    out = []
    for n in lv.level:
        if n.cls != "CullingBox":
            continue
        rec = lv.brief(n)
        rec["native"] = _native(n)
        rec["enabled"] = lv.enabled[id(n)]
        for key in ("width", "height", "depth"):
            v = n.p(key)
            rec[key] = v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
        g = n.parent
        while g is not None and g.cls != "CullingGroup":
            g = g.parent
        rec["group"] = lv.uid[id(g)] if g is not None else None
        rec.update(lv.placement(n))
        out.append(rec)
    groups = [
        {
            "uid": lv.uid[id(g)],
            "name": g.name,
            "boxes": [b["uid"] for b in out if b["group"] == lv.uid[id(g)]],
            "shows": [lv.uid[id(t)] for t in _ref_list(lv, g, "m_evisibilitygrouplist")],
        }
        for g in lv.level
        if g.cls == "CullingGroup"
    ]
    area = _area_cubes(lv)
    for g in groups:
        shows = set(g["shows"])
        g["cube_maps"] = [u for u, vg in area if vg <= shows]
    return {
        "inside_rule": CULLING_RULE,
        "visibility_rule": CULLING_VISIBILITY_RULE,
        "boxes": out,
        "groups": groups,
        "cube_maps_no_box": [u for u, vg in area if not vg],
        "visibility_groups": [lv.uid[id(n)] for n in lv.level if n.cls == "CullingVisibilityGroup"],
    }


TERRAIN_RULE = (
    "read: the terrain surface is drawn in world space with the identity matrix "
    "(0x49c3be); the node's world translation moves only the height query grid (0x49f3e4, "
    "0x52a22f).  `world` is the node's transform composed with its parents "
    "(conventions.world) and is the origin on every shipped level.  `gltf` "
    "places <asset>.glb (the file `watchmen extract --glb` writes beside the .terrain) in "
    "the frame of this file like every other placement.  The node has no scale property; "
    "the quad size is in the .terrain header and already in the GLB's vertices"
)


def _visible(n):
    """The node's `visible` flag (true when not stored), whatever letter case the key
    table that read the node spells it in (`Visible` up to 1.3.0)."""
    v = n.p("visible")
    if v is None:
        v = n.p("Visible", True)
    return v is not False


def _is_identity(world, eps=1e-6):
    """Whether a `world` record ({pos, quat}) is the identity within `eps` (the
    quaternion or its negative); None without a record."""
    if not world:
        return None
    pos, q = world.get("pos"), world.get("quat")
    if not pos or not q:
        return None
    if any(abs(x) > eps for x in pos):
        return False
    return any(all(abs(a - s * b) <= eps for a, b in zip(q, (0.0, 0.0, 0.0, 1.0))) for s in (1, -1))


def _section_terrain(lv):
    """Every node that names a `.terrain`: the file, the GLB the extractor writes for it
    and where the node puts it (local as stored, world composed, `gltf` in the file's
    frame)."""
    out = []
    for n in lv.level:
        asset = n.p("terrainAsset")
        if not (isinstance(asset, str) and asset):
            continue
        rec = lv.brief(n)
        rec["stable_uid"] = lv.stable_uid(n)
        rec["fragment"] = n.inst.asset if n.inst is not None else None
        rec["asset"] = asset
        rec["glb"] = asset + ".glb"
        rec["coloring_asset"] = n.p("terrainColoringAsset") or None
        rec["enabled"] = n.p("enabled", True) is not False
        rec["enabled_effective"] = lv.enabled[id(n)]
        rec["visible"] = _visible(n)
        pos, quat = n.p("localPos"), n.p("localOrient")
        rec["local"] = (
            {"pos": [_r(x) for x in pos], "quat": [_r(x) for x in quat]}
            if lv.has_transform(n)
            else None
        )
        rec["parent_link"] = n.p("parentLink")
        rec.update(lv.placement(n))
        rec["drawn_with"] = "identity"  # engine 0x49c3be: never the node's transform
        rec["world_is_identity"] = _is_identity(rec.get("world"))
        rec["scale"] = None
        rec["node"] = {
            k: n.p(k)
            for k in (
                "metersPerQuad",
                "quadsPerUserSector",
                "widthInUserSectors",
                "heightInUserSectors",
                "textureTiling",
            )
            if n.p(k) is not None
        }
        out.append(rec)
    return out


def _host_offset_copies(lv):
    """{id(node): twin node or None} of the model nodes HOST_OFFSET_RULE describes."""
    by = {}
    for n in lv.level:
        if n.p("modelNames") and id(n) in lv.world and lv.has_transform(n):
            by.setdefault((id(n.inst), n.cls, tuple(n.p("localPos"))), []).append(n)
    out = {}
    for group in by.values():
        for a in group:
            host = a.inst.host if a.inst is not None else None
            hw = lv.world.get(id(host)) if host is not None else None
            if hw is None or max(abs(x) for x in hw[0]) < 1e-6:
                continue
            qa = a.p("localOrient")
            for b in group:
                qb = b.p("localOrient")
                if b is a or len(qa) != len(qb):
                    continue
                if max(abs(x - y) for x, y in zip(qa, qb)) > HOST_OFFSET_QUAT_TOLERANCE:
                    continue
                d = [lv.world[id(a)][0][i] - lv.world[id(b)][0][i] - hw[0][i] for i in range(3)]
                if max(abs(x) for x in d) < 1e-3:
                    out[id(a)] = b
    folders = set(id(n.parent) for n in lv.level if id(n) in out and n.parent is not None)
    for n in lv.level:
        if id(n) not in out and id(n.parent) in folders and n.p("modelNames") and id(n) in lv.world:
            out[id(n)] = None
    return out


def _flag(n, *keys):
    """A truth property under the first spelling the node stores (None when none)."""
    for k in keys:
        v = n.p(k)
        if v is not None:
            return v
    return None


def _part_overrides(lv, n):
    """The SubPivot nodes below a model node (reached through SubPivot nodes only) that
    change how a part is drawn: `locked` keeps the stored transform instead of the part's
    rest pose (0x4a5907); a disabled or invisible one hides its part (0x49faaf)."""
    out, todo = [], [c for c in n.children if _native(c) == "SubPivot"]
    while todo:
        c = todo.pop(0)
        todo[0:0] = [k for k in c.children if _native(k) == "SubPivot"]
        locked = _flag(c, "locked", "Locked") is True
        enabled = c.p("enabled", True) is not False
        visible = _own_visible(c)
        if not (locked or not enabled or not visible):
            continue
        pid = c.p("pivotID")
        out.append(
            {
                "part": _signed(pid) if isinstance(pid, int) and pid is not True else None,
                "name": c.name,
                "local": (
                    {
                        "pos": [_r(x) for x in c.p("localPos")],
                        "quat": [_r(x) for x in c.p("localOrient")],
                    }
                    if lv.has_transform(c)
                    else None
                ),
                "locked": locked,
                "enabled": enabled,
                "visible": visible,
            }
        )
    return out


MOTION_FORMULA = (
    "angle_k = -impact_k * amplitude_k * 2^(-falloff_k*t) * sin(2*pi*frequency_k*t); s = "
    "min(1, |contact force|/10000); d = unit horizontal direction from the hitting character "
    "to the node; OscillateBox: impact_x = -s*dot(d, node X axis) turns about local Z, "
    "impact_z = -s*dot(d, node Z axis) turns about local X, orientation = start * Rz * Rx "
    "while either 2^(...) term >= 0.001"
)
MOTION_EVIDENCE = (
    "read: 0x874b7a, 0x871b96, 0x8718e6 (OscillateBox); 0x874795, 0x87113c (FireBarrel: one "
    "parameter set, about X then about Z scaled by the direction's z and -x)"
)


def _motion(n):
    """`motion` of a prop that swings when a character runs into it (script classes
    TriggerOscillateBox and TriggerFireBarrelEffect); None for any other node."""
    if n.cls not in ("TriggerOscillateBox", "TriggerFireBarrelEffect"):
        return None
    box = n.cls == "TriggerOscillateBox"
    return {
        "kind": "hit_swing",
        "rest": "stored placement",
        "amplitude": n.p("m_namplitude"),
        "frequency_hz": n.p("m_nfrequency"),
        "falloff": n.p("m_nfalloff"),
        "amplitude_z": n.p("m_namplitudez") if box else None,
        "frequency_z_hz": n.p("m_nfrequencyz") if box else None,
        "falloff_z": n.p("m_nfalloffz") if box else None,
        "quarantine_s": n.p("m_neffectquarentinetime"),
        "formula": MOTION_FORMULA,
        "evidence": MOTION_EVIDENCE,
    }


def _section_models(lv, cubes=None, culling=None):
    """`cubes` = the level's cube_maps section, for models[].cube_map; `culling` = its
    culling section, for models[].cube_map_by_area."""
    out = []
    copies = _host_offset_copies(lv)
    by_uid = {c["uid"]: c for c in cubes or ()}
    groups = (culling or {}).get("groups") or []
    shows = [set(g["shows"]) for g in groups]
    for n in lv.level:
        names = n.p("modelNames")
        if not names or id(n) not in lv.world:
            continue
        rec = lv.brief(n)
        rec["native"] = _native(n)
        # node flags of the renderer (conventions.model_flags)
        op = n.p("opacity", 1.0)
        rec["opacity"] = _r(op) if isinstance(op, (int, float)) and op is not True else 1.0
        rec["cast_shadow"] = n.p("castShadow", True) is not False
        # a Character node is a character-definition variant or a player model kept in
        # the level's data, not a placed prop -- except CharacterSimple, the background
        # characters, which are placements (the role value is the same for both)
        rec["role"] = "character_model" if "Character" in (n.type or "") else "prop"
        rec["models"] = [s for s in (names if isinstance(names, list) else [names]) if s]
        if isinstance(names, str):
            rec["models"] = [s for s in names.replace(";", ",").split(",") if s]
        rec["fragment"] = n.inst.asset if n.inst is not None else None
        rec["enabled"] = lv.enabled[id(n)]
        rec["visible"] = _visible(n)
        # the node's flag and its PVSRootNode ancestors' (0x48e028)
        rec["visible_effective"] = lv.visible[id(n)]
        pvs = lv.pvs.get(id(n))
        rec["pvs_root"] = lv.uid[id(pvs)] if pvs is not None else None
        lo = n.p("geometryLodOverride")
        rec["lod_override"] = _signed(lo) if isinstance(lo, int) and lo is not True else -1
        lf = n.p("geometryLodFactor", 1.0)
        rec["lod_factor"] = _r(lf) if isinstance(lf, (int, float)) and lf is not True else 1.0
        rec["include_in_reflections"] = n.p("includeInReflections") is True
        rec["include_in_ao"] = n.p("includeInAO", True) is not False
        rec["part_overrides"] = _part_overrides(lv, n)
        mo = _motion(n)
        if mo is not None:
            rec["motion"] = mo
        rec.update(lv.placement(n))
        # the transform as stored and what lies between the node and the node it hangs from
        rec["local"] = (
            {"pos": [_r(x) for x in n.p("localPos")], "quat": [_r(x) for x in n.p("localOrient")]}
            if lv.has_transform(n)
            else None
        )
        rec["parent_chain_without_transform"] = lv.chain_without_transform(n)
        if id(n) in copies:
            twin = copies[id(n)]
            rec["host_offset_copy"] = {"twin": lv.uid[id(twin)] if twin is not None else None}
        rec["cube_map"] = _nearest_cube(rec, cubes)
        above = {lv.uid[id(g)] for g in _pvs_chain(lv, n) if g.cls == VISIBILITY_GROUP}
        rec["cube_map_by_area"] = _cube_by_area(
            rec, by_uid, [g for g, s in zip(groups, shows) if above <= s]
        )
        out.append(rec)
    return out


def _cube_by_area(rec, by_uid, groups):
    """[{"cube": {uid, texture, distance} or None, "groups": [culling group uids]}], one
    row per distinct answer: for each of `groups` (the culling groups that show the
    placement) the nearest of that group's `cube_maps` to the placement, i.e. the cube
    for a camera in the boxes of that group alone.  [] when no group shows it."""
    rows, memo = [], {}
    for g in groups:
        key = tuple(g["cube_maps"])
        if key not in memo:
            c = _nearest_cube(rec, [by_uid[u] for u in key if u in by_uid], file_state=False)
            memo[key] = None if c is None else {k: c[k] for k in ("uid", "texture", "distance")}
        cube = memo[key]
        for row in rows:
            if (row["cube"] or {}).get("uid") == (cube or {}).get("uid"):
                row["groups"].append(g["uid"])
                break
        else:
            rows.append({"cube": cube, "groups": [g["uid"]]})
    return rows


def _nearest_cube(rec, cubes, file_state=True):
    """CUBE_MAP_RULE on the file state: the candidate_at_load cube node nearest to
    the placement's world position (squared distance, the first of equals as the
    engine's strict `<` keeps it, 0x4d1299) -> {"uid", "texture", "distance",
    "same_fragment"} or None.  file_state=False: every node of `cubes` is a candidate."""
    pos = (rec.get("world") or {}).get("pos")
    best, bd = None, None
    for c in cubes or ():
        cp = (c.get("world") or {}).get("pos")
        if (file_state and not c.get("candidate_at_load")) or pos is None or cp is None:
            continue
        d = sum((float(a) - float(b)) ** 2 for a, b in zip(pos, cp))
        if bd is None or d < bd:
            best, bd = c, d
    if best is None:
        return None
    return {
        "uid": best["uid"],
        "texture": best.get("texture"),
        "distance": _r(bd**0.5, 3),
        "same_fragment": best.get("fragment") == rec.get("fragment"),
    }


PATH_OBJECT_NATIVE = "AIStaticPathObjectNode"
PATH_VERTEX_NATIVE = "AIStaticPathObjectVertexNode"
#: a nav path object and a level node are the same thing when every edge end point
#: lies this close (metres, 3D) to one of the node's vertex nodes
PATH_OBJECT_TOLERANCE = 0.5


AI_WORLD_NATIVE = "AIWorldNode"
AI_WORLD_LIST = "aiStaticPathObjectNodes"
#: AIWorldNode path-data generation inputs (not read at run time by this executable)
AI_WORLD_GENERATION = (
    "groundSlopeMax",
    "groundSlopeMin",
    "holeMax",
    "entityHeight",
    "entityRadius",
    "pitch",
    "stepMax",
    "stepLength",
    "graphAccuracy",
    "nbSectors",
    "distEdgeMax",
)


def _ai_world(lv):
    """(summary, {id(node): 1-based index}) of the level's AI world: the serialised
    list a path-object id indexes (lookup 0x4837d5).  (None, {}) without one."""
    worlds = [n for n in lv.level if _native(n) == AI_WORLD_NATIVE]
    world = next((n for n in worlds if isinstance(n.p(AI_WORLD_LIST), list)), None)
    if world is None:
        return None, {}
    index, nulls, unres, other, dup = {}, [], [], [], []
    refs = world.p(AI_WORLD_LIST)
    for i, ref in enumerate(refs, 1):
        if not isinstance(ref, dict) or ref.get("etag") in (0, 1):
            nulls.append(i)
            continue
        t = lv.asm.resolve_ref(world, ref, lv.index)
        if t is None:
            unres.append(i)
        elif _native(t) != PATH_OBJECT_NATIVE or id(t) not in lv.in_level:
            other.append(i)
        elif id(t) in index:
            dup.append(i)
        else:
            index[id(t)] = i
    summ = {
        "uid": lv.uid[id(world)],
        "asset": world.p("aiWorldAsset") or None,
        "collision_mask": world.p("collisionMask"),
        "node_collision_mask": world.p("nodeCollisionMask"),
        "use_collision_masks_for_map_builder": world.p("useCollisionMasksForMapBuilder"),
        "generation": {k: world.p(k) for k in AI_WORLD_GENERATION},
        "nodes": len(worlds),
        "list_length": len(refs),
        "null_entries": nulls,
        "unresolved": unres,
        "not_path_objects": other,
        "repeated": dup,
    }
    return summ, index


def _section_path_objects(lv, ai_index=None):
    """The level's static path objects (doors, gates, climb-ups): the nodes the
    path data's path-object table refers to, each with its link end points.
    `ai_index` = the second result of _ai_world()."""
    out = []
    ai_index = ai_index or {}
    for n in lv.level:
        if _native(n) != PATH_OBJECT_NATIVE:
            continue
        rec = lv.brief(n)
        rec["native"] = _native(n)
        rec["fragment"] = n.inst.asset if n.inst is not None else None
        rec["enabled"] = lv.enabled[id(n)]
        for key, prop in (
            ("impassable", "impassable"),
            ("can_leave", "canLeave"),
            ("can_bypass", "canBypass"),
        ):
            rec[key] = n.p(prop)
        t = lv.resolve(n, "pathObject")
        rec["path_object"] = lv.brief(t) if t is not None else None
        rec["vertices"] = [
            {"uid": lv.uid[id(c)], "pos": [_r(x) for x in lv.world[id(c)][0]]}
            for c in lv.asm.walk(n)
            if _native(c) == PATH_VERTEX_NATIVE and id(c) in lv.world
        ]
        rec.update(lv.placement(n))
        rec["ai_world_index"] = ai_index.get(id(n))
        # only a node in the AI world's list is ever bound to the path data (0x48c249)
        rec["bound_at_run_time"] = rec["ai_world_index"] is not None
        rec["nav"] = None
        out.append(rec)
    return out


NAV_LINK_RULE = (
    "id first: a table entry goes to the node whose ai_world_index equals the entry's id "
    "(the id is the 1-based index into the AI world's aiStaticPathObjectNodes list, lookup "
    "0x4837d5); an entry without such a node -- a null or unresolved list entry -- goes by "
    "position: edge end points of the nav path object against the node's vertex nodes, "
    "within tolerance_m, one entry per node (see evidence.path_objects)"
)


def _po_points(po):
    pts = set()
    for e in po.get("edges") or []:
        pts.add(tuple(e["from"]))
        pts.add(tuple(e["to"]))
    return pts


def _po_distance(pts, rec):
    """Largest distance of an end point to the nearest vertex node of `rec`, or None."""
    vs = [v["pos"] for v in rec.get("vertices") or []]
    if not pts or not vs:
        return None
    return max(min(math.dist(p, v) for v in vs) for p in pts)


def link_nav(level, nav_path_objects, source=None, tolerance=PATH_OBJECT_TOLERANCE):
    """Join the path-object table of a level's navigation data to the level's
    path-object nodes: by id, then by position.

    level              a level-meta dict (mutated: `path_objects[*].nav`, `nav`,
                       `counts.path_objects_linked`)
    nav_path_objects   `path_objects` of a watchmen-nav/1 document (engine space):
                       [{"index", "id", "edges": [{"from", "to"}]}]

    By id: a table entry goes to the node whose `ai_world_index` equals its `id`
    (what the engine does, 0x4837d5).  The position distance of the pair is kept as
    a cross-check and never undoes the join; pairs farther apart than `tolerance`
    are listed in `id_position_disagree`.

    By position, for the entries the id leaves over (their list entry is null or
    unresolved, or the level dict has no `ai_world_index`): an entry goes to the
    still unjoined node whose vertex nodes are nearest to ALL end points of the
    entry's edges (the largest of the per-point distances counts), when that
    distance is within `tolerance` and no other entry is nearer to the same node.
    -> the `nav` summary dict."""
    nodes = level.get("path_objects") or []
    for rec in nodes:
        rec["nav"] = None
    table = list(nav_path_objects or [])
    points = {po["index"]: _po_points(po) for po in table}
    by_id = {}
    for k, rec in enumerate(nodes):
        if rec.get("ai_world_index") is not None:
            by_id.setdefault(rec["ai_world_index"], k)
    done_po, done_node, dists, disagree = set(), set(), [], []

    def join(po, k, d, method):
        done_po.add(po["index"])
        done_node.add(k)
        if d is not None:
            dists.append(d)
        nodes[k]["nav"] = {
            "index": po["index"],
            "id": po.get("id"),
            "method": method,
            "distance_m": _r(d, 4) if d is not None else None,
            "edges": [[e.get("cell"), e.get("edge")] for e in po.get("edges") or []],
        }

    for po in table:
        k = by_id.get(po.get("id")) if po.get("id") is not None else None
        if k is None or k in done_node:
            continue
        d = _po_distance(points[po["index"]], nodes[k])
        join(po, k, d, "id")
        if d is not None and d > tolerance:
            disagree.append(
                {
                    "index": po["index"],
                    "id": po.get("id"),
                    "node": nodes[k].get("uid"),
                    "distance_m": _r(d, 4),
                }
            )
    n_id = len(done_po)
    cand = []
    for po in table:
        if po["index"] in done_po or not points[po["index"]]:
            continue
        for k, rec in enumerate(nodes):
            if k in done_node:
                continue
            d = _po_distance(points[po["index"]], rec)
            if d is not None and d <= tolerance:
                cand.append((d, po["index"], k, po))
    cand.sort(key=lambda c: (c[0], c[1], c[2]))
    for d, index, k, po in cand:
        if index in done_po or k in done_node:
            continue
        join(po, k, d, "position")
    summ = {
        "source": source,
        "path_objects": len(table),
        "linked": len(done_po),
        "linked_by_id": n_id,
        "linked_by_position_only": len(done_po) - n_id,
        "id_position_disagree": disagree,
        "unlinked": sorted(po["index"] for po in table if po["index"] not in done_po),
        "max_distance_m": _r(max(dists), 4) if dists else None,
        "tolerance_m": tolerance,
        "rule": NAV_LINK_RULE,
        "vertical_offset": NAV_HEIGHT_NOTE,
    }
    level["nav"] = summ
    level.setdefault("counts", {})["path_objects_linked"] = len(done_po)
    return summ


NAV_HEIGHT_NOTE = (
    "path-object end points are the vertex nodes' own positions (no offset).  The rest of "
    "the navigation data -- mesh outlines and the other graph vertices -- lies about 1 m "
    "above the walking surface (median 1.025 m above character pivots, 1.05 m above floor "
    "models): compare placements with the mesh in x / z and an altitude window, not by "
    "height (nav_data.locate does that)"
)


def _path_key(p):
    return [x.lower() for x in str(p or "").replace("\\", "/").split("/") if x]


def find_nav(extract_out, name, assets=()):
    """`path_objects` of the navigation data of level `name` in an extract output and
    the .hpd's file name, or (None, None) when the extract has no path data for it.

    The entry is looked up by the level's name first (nav_data names an entry after
    the folder above `Gameplay/`), then by the level's own path-data definition:
    `assets` = the `.aipathdata` asset paths its nodes name (aiWorldAsset).  The
    second lookup is what links Part 1's `Streets2` (folder `Street2`) and
    `Undergound` (folder `Underground`), whose load blocks are not named like their
    folders."""
    import nav_data

    found = nav_data.find_inputs(nav_data.extract_trees(extract_out))
    hit = next((e for e in found if e["level"].lower() == (name or "").lower() and e["hpd"]), None)
    if hit is None:
        want = [_path_key(a) for a in assets if str(a).lower().endswith(".aipathdata")]
        for e in found:
            k = _path_key(e["aipathdata"])
            if e["hpd"] and any(w and k[-len(w) :] == w for w in want):
                hit = e
                break
    if hit is None:
        return None, None
    with open(hit["hpd"], "rb") as fh:
        hpd = nav_data.parse_hpd(fh.read())
    doc = nav_data.build_document(hpd, None, hit["level"], {"hpd": None, "aipathdata": None})
    return doc["path_objects"], os.path.basename(hit["hpd"])


#: `nav_note` of a level that has path objects but no path data to join them to
NAV_MISSING_NOTE = (
    "no path data (.hpd) for this level in the extract output, so `nav` is null and no "
    "path object carries a `nav` entry.  The archives hold it under data/; a loose-folder "
    "source (Part 1 PC / Xbox Live: derived_pc, derived_x360) keeps it in the sibling "
    "data/ folder, which `extract` copies to files/data/ -- run `extract` again, or "
    "`navmeta` on that data/ folder"
)


HERO_MODEL_REFS = (
    ("rsh", "_emodelrsh"),
    ("nto", "_emodelnto"),
    ("nto_head", "_emodelntohead"),
    ("rsh_rage", "_emodelrshrage"),
    ("nto_flashing", "_emodelntoflashing"),
)


def _section_hero_models(lv):
    """What the level's LevelSceneCtrl names for the two heroes: {key: {uid, name,
    enabled, model} or None}; None without a LevelSceneCtrl."""
    ctrl = next((n for n in lv.level if n.cls == "LevelSceneCtrl"), None)
    if ctrl is None:
        return None
    out = {"ctrl": lv.uid[id(ctrl)]}
    for key, prop in HERO_MODEL_REFS:
        t = lv.resolve(ctrl, prop)
        if t is None:
            out[key] = None
            continue
        names = t.p("modelNames")
        if isinstance(names, str):
            names = [s for s in names.replace(";", ",").split(",") if s]
        names = [s for s in (names or []) if s]
        out[key] = {
            "uid": lv.uid[id(t)],
            "name": t.name,
            "enabled": lv.enabled[id(t)],
            "model": names[0] if names else None,
        }
    return out


def _section_volumes(lv, graph, ai_mask=None, sheets=None):
    used = {}
    for e in graph["edges"]:
        if e["kind"] in ("volume", "zone"):
            used.setdefault(e["to"], []).append(e["from"])
    out = []
    for n in lv.level:
        if _native(n) not in _VOLUME_NATIVES:
            continue
        rec = _volume(lv, n)
        rec["ai_sight"] = ai_sight(n, ai_mask, sheets or {})
        rec["used_by"] = used.get(rec["uid"], [])
        rec["conditions"] = [lv.uid[id(c)] for c in n.children if _is_condition(c)]
        out.append(rec)
    return out


def _walk_actions(lv, n, depth, out, seen, how=None):
    """Depth-first list of what firing `n`'s children does (aux actions followed)."""
    acts = [c for c in n.children if _is_action(c)]
    for i, c in enumerate(acts):
        when, delay = _child_when(n, i)
        _, names = _params(lv, c)
        rec = {"depth": depth, "uid": lv.uid[id(c)], "label": _label(lv, c, names), "when": when}
        if delay is not None:
            rec["delay"] = delay
        if not lv.enabled[id(c)]:
            rec["enabled"] = False
        out.append(rec)
        if id(c) not in seen:
            seen.add(id(c))
            _walk_actions(lv, c, depth + 1, out, seen)
            aux = lv.resolve(c, "_eauxaction")
            if aux is not None:
                _, an = _params(lv, aux)
                out.append(
                    {
                        "depth": depth + 1,
                        "uid": lv.uid[id(aux)],
                        "label": _label(lv, aux, an),
                        "when": "aux",
                    }
                )
                if id(aux) not in seen:
                    seen.add(id(aux))
                    _walk_actions(lv, aux, depth + 2, out, seen)
    return out


def _section_checkpoints(lv, graph):
    incoming = {}
    for e in graph["edges"]:
        if e["kind"] in ("action", "child", "aux", "activated", "released", "start", "tour_end"):
            incoming.setdefault(e["to"], []).append({"from": e["from"], "kind": e["kind"]})
    out = []
    for n in lv.level:
        if n.cls != "TriggerActionCheckpoint":
            continue
        rec = lv.brief(n)
        rec["checkpoint_id"] = n.p("_icheckpointid")
        rec["fragment"] = n.inst.asset if n.inst is not None else None
        rec["fired_by"] = incoming.get(rec["uid"], [])
        par = n.parent
        if par is not None and par.cls == "TriggerConditionCollision":
            vol = lv.resolve(par, "m_etriggerentity") or par.parent
            _, names = _params(lv, par)
            rec["condition"] = {"uid": lv.uid[id(par)], "label": _label(lv, par, names)}
            if vol is not None and _native(vol) in _VOLUME_NATIVES:
                rec["trigger_volume"] = _volume(lv, vol)
        tele = []
        for c in lv.asm.walk(n)[1:]:
            if c.cls == "TriggerActionCharacter" and c.p("m_iactiontype") == 0:
                who = enum_name("TRIGGER_ACTION_CHAR_TARGETS", c.p("m_itargettype"))
                if who in (None, "ENTITYREF"):
                    who = _tname(lv, c, "m_etarget1")
                t = {"uid": lv.uid[id(c)], "who": who}
                t.update(lv.placement(c))
                tele.append(t)
        rec["teleports"] = tele
        rec["replay"] = _walk_actions(lv, n, 0, [], set())
        out.append(rec)
    out.sort(key=lambda r: (r["checkpoint_id"] is None, r["checkpoint_id"]))
    return out


def _section_cameras(lv):
    tours, cams, focus = [], [], []
    for n in lv.level:
        if n.cls == "PlayerVsPlayerFocusPoint":
            # the PvP camera sits on the line from the players' midpoint away from this node
            rec = lv.brief(n)
            rec["path"] = lv.path(n)
            rec.update(lv.placement(n))
            focus.append(rec)
        if _native(n) == "Camera" or n.cls == "Camera":
            rec = lv.brief(n)
            rec["fov"] = n.p("fov")
            rec["path"] = lv.path(n)
            rec.update(lv.placement(n))
            cams.append(rec)
        if n.cls != "TriggerActionCamera" or n.p("_iaction") != 0:
            continue
        rec = lv.brief(n)
        rec["path"] = lv.path(n)
        rec["enabled"] = lv.enabled[id(n)]
        for key, prop in (
            ("skipable", "_tskipable"),
            ("unskippable_time", "_tunskippabletime"),
            ("disable_player_ctrl", "_tdisableplayerctrl"),
            ("pause_enemy_attack", "_tpauseenemyattack"),
        ):
            rec[key] = n.p(prop)
        cam = lv.resolve(n, "_ecamera")
        rec["camera"] = lv.brief(cam) if cam is not None else None
        seqs = [c for c in n.children if _native(c) == "PropertySequenceNode"]
        rec["sequences"] = [
            {
                "uid": lv.uid[id(c)],
                "name": c.name,
                "sequence": c.p("sequence"),
                "speed_factor": c.p("speedFactor", 1.0),
            }
            for c in seqs
        ]
        cuts, timed = [], []
        for c in seqs[0].children if seqs else ():  # the engine uses the first one, 0x849e59
            if not _is_sequence_action(c):
                continue
            r = {
                "uid": lv.uid[id(c)],
                "at": c.p("_ndelay", 0.0),
                "class": c.cls,
                "enabled": c.p("enabled", True) is not False,
            }
            if c.cls == "TriggerActionCamera":
                cc = lv.resolve(c, "_ecamera")
                r["action"] = enum_name("TRIGGER_ACTION_CAMERA_ACTIONS", c.p("_iaction"))
                r["camera"] = lv.brief(cc) if cc is not None else None
                cuts.append(r)
            else:
                timed.append(r)
        rec["cuts"] = sorted(cuts, key=lambda r: r["at"])
        rec["timed_actions"] = sorted(timed, key=lambda r: r["at"])
        for key, prop in (("on_end", "_eontourend"), ("on_skipped", "_eontourskipped")):
            t = lv.resolve(n, prop)
            rec[key] = lv.brief(t) if t is not None else None
        tours.append(rec)
    return {"tours": tours, "camera_nodes": cams, "pvp_focus": focus}


def _num(v):
    return _r(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def waypoint_links(nodes, forced=None):
    """The links WaypointController.WayPointInit (0x8b1062) builds over the start node
    and its next siblings, by index.

    nodes   [(for_all, exclusive_to)] in sibling order, the start node first
    forced  {index: target index}: m_eforcenext

    -> (next_all, next_exclusive): per node the next for-all node (or None) and the two
    exclusive slots [type 0, type 1] (SetNextExclusiveCharacter 0x8aa4e5 writes a slot
    only for type 0 or 1)."""
    forced = forced or {}
    next_all = [None] * len(nodes)
    next_ex = [[None, None] for _ in nodes]
    last = prev = 0
    for i in range(1, len(nodes)):
        for_all, t = nodes[i]
        before = last
        if for_all:
            next_all[last] = i
            last = i
        if t in (0, 1):
            owner = prev if nodes[prev][1] == t else before
            next_ex[owner][t] = i
            if forced.get(i) is not None:
                next_ex[i][t] = forced[i]
        prev = i
    return next_all, next_ex


def _section_waypoints(lv):
    """The level's waypoint chain with the links the engine builds at load (None without
    a WaypointController)."""
    ctrls = [n for n in lv.level if n.cls == "WaypointController"]
    if not ctrls:
        return None
    ctrl = ctrls[0]
    start, end = lv.resolve(ctrl, "m_estart"), lv.resolve(ctrl, "m_eend")
    chain = []
    if start is not None and start.parent is not None:
        sib = start.parent.children
        k = next((i for i, c in enumerate(sib) if c is start), None)
        chain = list(sib[k:]) if k is not None else [start]
    elif start is not None:
        chain = [start]
    pos = {id(c): i for i, c in enumerate(chain)}

    def excl(c):
        v = c.p("m_iexclusivetocharacter", -1)
        return _signed(v) if isinstance(v, int) and not isinstance(v, bool) else -1

    forced = {}
    for i, c in enumerate(chain):
        t = lv.resolve(c, "m_eforcenext")
        if t is not None and id(t) in pos:
            forced[i] = pos[id(t)]
    nall, nex = waypoint_links([(c.p("m_tforall") is True, excl(c)) for c in chain], forced)

    def u(i):
        return lv.uid[id(chain[i])] if i is not None else None

    nodes = []
    for i, c in enumerate(chain):
        fn, fu = lv.resolve(c, "m_eforcenext"), lv.resolve(c, "m_eforceusetrigger")
        rec = {
            "uid": lv.uid[id(c)],
            "id": i,
            "class": c.cls,
            "for_all": c.p("m_tforall") is True,
            "exclusive_to": excl(c),
            "exclusive_to_name": enum_name("CHARACTER_TYPES", excl(c)),
            "active": c.p("m_tactive"),
            "activator_stopper": c.p("m_tlastinactive"),
            "flying": c.p("m_tflyingwaypoint"),
            "height_limits": (
                [c.p("m_nnumberminheight"), c.p("m_nnumbermaxheight")]
                if c.p("m_tenforceminimumheightdifference") is True
                else None
            ),
            "force_next": lv.uid[id(fn)] if fn is not None else None,
            "force_use_trigger": lv.uid[id(fu)] if fu is not None else None,
            "next_all": u(nall[i]),
            "next_exclusive": [u(nex[i][0]), u(nex[i][1])],
        }
        pl = lv.placement(c)
        rec["world"], rec["gltf"] = pl.get("world"), pl.get("gltf")
        nodes.append(rec)
    out = {
        "controller": lv.uid[id(ctrl)],
        "max_distance": ctrl.p("m_nmaxdistance"),
        "start": lv.uid[id(start)] if start is not None else None,
        "end": lv.uid[id(end)] if end is not None else None,
        "nodes": nodes,
        "activated_by": [
            lv.uid[id(n)]
            for n in lv.level
            if n.cls == "TriggerActionGeneral" and _signed(n.p("m_iactiontype", 0)) == 20
        ],
    }
    if len(ctrls) > 1:
        out["other_controllers"] = [lv.uid[id(c)] for c in ctrls[1:]]
    return out


def _section_stream_blocks(lv):
    """`files.stream_blocks`: every StreamBlock node with the triggers that load and
    unload it and the nodes that name it through `_estreamblock`."""
    loaded, unloaded, referenced = {}, {}, {}
    for n in lv.level:
        t = lv.resolve(n, "_estreamblock")
        if t is not None:
            referenced.setdefault(id(t), []).append(lv.uid[id(n)])
        if n.cls == "StreamBlockTriggerOneShot":
            for prop, into in (("m_eloadstreamblock", loaded), ("m_eunloadstreamblock", unloaded)):
                t = lv.resolve(n, prop)
                if t is not None:
                    into.setdefault(id(t), []).append(lv.uid[id(n)])
        elif n.cls == "StreamBlockTrigger":
            t = lv.resolve(n, "m_estreamblock")
            if t is not None:
                loaded.setdefault(id(t), []).append(lv.uid[id(n)])
                unloaded.setdefault(id(t), []).append(lv.uid[id(n)])
    return [
        {
            "uid": lv.uid[id(n)],
            "name": n.name,
            "asset": n.p("assetName") or None,
            "scene_start": n.p("m_tisscenestartstreamblock") is True,
            "loaded_by": loaded.get(id(n), []),
            "unloaded_by": unloaded.get(id(n), []),
            "referenced_by": referenced.get(id(n), []),
        }
        for n in lv.level
        if n.cls == "StreamBlock"
    ]


LIGHT_TYPES = {1: "point", 2: "spot", 3: "directional", 4: "ambient", 6: "box", 7: "frustum"}
#: LightFlicker changes brightness only while a camera is within this distance (squared
#: distance 1600.0 at 0xa743b8)
FLICKER_ACTIVE_WITHIN_M = 40


def _section_lights(lv):
    """Every native Light node with its stored properties (conventions.light).  A stored
    type 5 is what the engine keeps as type 2 with `textured` set (0x4a1c4a)."""
    out = []
    for n in lv.level:
        if _native(n) != "Light":
            continue
        rec = lv.brief(n)
        rec["path"] = lv.path(n)
        rec["enabled"] = lv.enabled[id(n)]
        rec.update(lv.placement(n))
        t = n.p("lightType")
        t = _signed(t) if isinstance(t, int) and not isinstance(t, bool) else None
        textured = n.p("textured")
        if t == 5:
            rec["type"], rec["stored_type"], textured = 2, 5, True
        else:
            rec["type"] = t
        rec["type_name"] = LIGHT_TYPES.get(rec["type"])
        col = n.p("lightColorRGB")
        rec["color"] = [_r(x) for x in col] if isinstance(col, list) else col
        rec["brightness"] = _num(n.p("brightness"))
        rec["range_m"] = _num(n.p("range"))
        rec["attn_start"] = _num(n.p("attnStart"))
        rec["inner_cone_deg"] = _num(n.p("innerConeAngle"))
        rec["outer_cone_deg"] = _num(n.p("outerConeAngle"))
        rec["dist_fade_start_m"] = _num(n.p("distFadeStart"))
        rec["dist_fade_end_m"] = _num(n.p("distFadeEnd"))
        rec["never_fade"] = n.p("ignoreGlobalLightFading") is True
        rec["cause_shadows"] = n.p("causeShadows")
        rec["shadow_power"] = _num(n.p("shadowPower"))
        rec["textured"] = textured
        rec["texture"] = n.p("texture") or None
        rec["box"] = {k: _num(n.p(k)) for k in ("width", "height", "depth")}
        rec["aspect_ratio"] = _num(n.p("aspectRatio"))
        if n.cls == "LightFlicker":
            lo, hi = _num(n.p("_nrangemin")), _num(n.p("_nrangemax"))
            rec["flicker"] = {
                "brightness_min": _num(n.p("_nbrightnessmin")),
                "brightness_max": _num(n.p("_nbrightnessmax")),
                "period_s": _num(n.p("_nbrighnessrandomizetime")),
                "range_m": _r((lo + hi) / 2) if lo is not None and hi is not None else None,
                "active_within_m": FLICKER_ACTIVE_WITHIN_M,
            }
        out.append(rec)
    return out


def _section_auto_sequences(lv):
    """The PropertySequenceNodes that start by themselves when the level loads
    (`autoStart`): sheet pulses, lights, doors -- everything that runs without a trigger."""
    return [
        {
            "uid": lv.uid[id(n)],
            "name": n.name,
            "path": lv.path(n),
            "sequence": n.p("sequence"),
            "enabled": lv.enabled[id(n)],
            "speed_factor": n.p("speedFactor", 1.0),
            "update_culling_distance": n.p("updateCullingDistance", 0.0),
            "actions": sum(1 for c in getattr(n, "children", ()) if _is_sequence_action(c)),
        }
        for n in lv.level
        if _native(n) == "PropertySequenceNode" and n.p("autoStart")
    ]


#: LevelSceneCtrl reference -> key of scene_ctrl.override_models.  The level's scene
#: controller names the hero models of the level (CharacterDef.command_get_override_model
#: 0x666d03 -> LevelSceneCtrl 0x76ef49); `_emodelntoflashing` is the model whose texture
#: sheets the block flash (animation event 84) copies.
SCENE_CTRL_MODELS = (
    ("nto", "_emodelnto"),
    ("nto_flashing", "_emodelntoflashing"),
    ("rsh", "_emodelrsh"),
    ("rsh_rage", "_emodelrshrage"),
    ("nto_head", "_emodelntohead"),
)
RSH_RAGE_NOTE = "not read by any script (hash and member scan); inferred unused"


def _section_scene_ctrl(lv):
    """The level's LevelSceneCtrl nodes with the Character nodes their model references
    name: `override_models` = {key: {uid, name, model (the node's first model name),
    enabled, textureSheetsDescription}}
    (null for a null reference; a key the node does not store is left out)."""
    out = []
    for n in lv.level:
        if n.cls != "LevelSceneCtrl":
            continue
        models = {}
        for key, prop in SCENE_CTRL_MODELS:
            if _prop_any_case(n, prop) is None and prop not in n.props:
                continue
            t = lv.resolve(n, prop)
            if t is None:
                models[key] = None
                continue
            rec = {
                "uid": lv.uid[id(t)],
                "name": t.name,
                "model": next((x for x in (t.p("modelNames") or []) if x), None),
                "enabled": lv.enabled[id(t)],
                "textureSheetsDescription": _prop_any_case(t, "textureSheetsDescription"),
            }
            if key == "rsh_rage":
                rec["note"] = RSH_RAGE_NOTE
            models[key] = rec
        rec = lv.brief(n)
        rec["override_models"] = models
        out.append(rec)
    return out


def _prop_any_case(n, key):
    """Property `key` of a node whatever letter case the key table spells it in
    (`textRes` as SubtitleSlot registers it; `textres` in key tables before 1.4.0)."""
    v = n.p(key)
    if v is not None:
        return v
    low = key.lower()
    for k, v in n.props.items():
        if k.lower() == low:
            return v
    return None


def _movie(lv, t):
    rec = lv.brief(t)
    rec["movie"] = t.p("movie")
    rec["localized"] = t.p("isLocalized")
    slot = lv.resolve(t, "subtitleSlot")
    rec["subtitle_table"] = (_prop_any_case(slot, "textRes") or None) if slot is not None else None
    nxt = lv.resolve(t, "m_econtinuelink")
    rec["continue_link"] = dict(lv.brief(nxt), movie=nxt.p("movie")) if nxt is not None else None
    return rec


def _section_movies(lv):
    out = {"scope": {}, "actions": []}
    for prop in _refs(lv.scope):
        if "movie" in prop:
            t = lv.resolve(lv.scope, prop)
            out["scope"][prop] = _movie(lv, t) if t is not None else None
    for n in lv.level:
        if n.cls == "TriggerActionMovie":
            t = lv.resolve(n, "m_emovie")
            rec = lv.brief(n)
            rec["movie"] = _movie(lv, t) if t is not None else None
            out["actions"].append(rec)
    return out


def _section_events(lv):
    listened, sent = {}, {}
    for n in lv.level:
        if n.cls == "TriggerConditionGameEvent":
            listened.setdefault(_signed(n.p("m_itrueon")), []).append(lv.uid[id(n)])
        elif n.cls == "TriggerActionGameEvent":
            sent.setdefault(_signed(n.p("m_iactioneventtype")), []).append(lv.uid[id(n)])

    def rows(d):
        return [
            {"id": k, "name": enum_name("GAME_EVENTS", k), "nodes": v} for k, v in sorted(d.items())
        ]

    return {"listened": rows(listened), "sent": rows(sent)}


def _section_fragments(lv):
    counts = {}
    for n in lv.level:
        counts[id(n.inst)] = counts.get(id(n.inst), 0) + 1
    out = []
    for i, inst in enumerate(lv.insts):
        if id(inst) not in counts:
            continue
        host = inst.host
        rec = {
            "index": i,
            "stable_id": lv.stable_ids[i],
            "asset": inst.asset,
            "header": inst.header,
            "nodes": counts[id(inst)],
            "host": lv.brief(host) if host is not None else None,
            "parent": lv.inst_index(host) if host is not None else None,
        }
        if host is not None and id(host) in lv.world:
            rec["world"] = lv.xform(host)
            rec["gltf"] = gltf_trs(*lv.world[id(host)])
        out.append(rec)
    return out


_REAPPLY = {}


def reapplyable_fragments(extract_out):
    """Fragments whose header has reapplyable = 1: the ones the game applies to a
    node again at run time (character root templates, visuals, HUDs)."""
    import kapow_fragment

    base = extract_out
    if os.path.isdir(os.path.join(extract_out, "extracted")):
        base = os.path.join(extract_out, "extracted")
    if base in _REAPPLY:
        return _REAPPLY[base]
    out = []
    for f in sorted(glob.glob(os.path.join(base, "**", "*.fragment"), recursive=True)):
        try:
            with open(f, "rb") as fh:
                head = fh.read(600)
        except OSError:
            continue
        h = kapow_fragment.parse_header(head, kapow_fragment.detect_order(head))
        if h and h["reapplyable"]:
            out.append(
                {
                    "asset": "/" + os.path.relpath(f, base).replace(os.sep, "/"),
                    "name": h["name"],
                    "singleton": h["singleton"],
                }
            )
    _REAPPLY[base] = out
    return out


def _bounds(scope):
    keys = ("quadTreeBoundMinX", "quadTreeBoundMinZ", "quadTreeBoundMaxX", "quadTreeBoundMaxZ")
    return {k[13:].lower(): scope.p(k) for k in keys} if scope.p(keys[0]) is not None else None


def build_level(scene_path, name, scope_id, extract_out=None):
    """The level-meta dict of one load block of a scene."""
    roots, scope = load_level_tree(scene_path, scope_id)
    lv = _Level(roots, scope)
    asset = scope.p("assetName") or ""
    sid = _signed(scope.p("m_isceneid", -1))
    defs = _section_defs(lv)
    graph = _section_graph(lv)
    cubes = _section_cube_maps(lv)
    culling = _section_culling(lv)
    ai_world, ai_index = _ai_world(lv)
    # the block is named after the top fragment, not after the load block's name
    # (Part 1: level `Streets2` is Street2.block_*, `Undergound` is underground.block_*)
    stem = (os.path.splitext(os.path.basename(asset.replace("\\", "/")))[0] or name or "").lower()
    sheets, sheet_source = pivot_sheets(extract_out)
    # the mask the sight ray uses: any AIWorldNode of the level that stores one
    ai_mask = next(
        (
            n.p("collisionMask")
            for n in lv.level
            if _native(n) == AI_WORLD_NATIVE and isinstance(n.p("collisionMask"), int)
        ),
        None,
    )
    if ai_world is not None:
        ai_world["pivot_sheet_source"] = sheet_source
    loose = sorted(
        set(
            n.p(k)
            for n in lv.level
            for k in ("aiWorldAsset", "terrainAsset")
            if isinstance(n.p(k), str) and n.p(k)
        )
    )
    out = {
        "format": FORMAT,
        "level": {
            "name": name,
            "scene": os.path.basename(scene_path),
            "scope": lv.uid[id(scope)],
            "scope_id": scope.id,
            "scene_id": {"value": sid, "name": enum_name("SCENE_ID", sid)},
            "asset": asset,
            "bounds": _bounds(scope),
            "nodes": len(lv.level),
            "ai_world": ai_world,
            "hero_models": _section_hero_models(lv),
        },
        "conventions": conventions(),
        "evidence": EVIDENCE,
        "files": {
            "blocks": [stem + ".block_h_z", stem + ".block_s_z"],
            "common_block": bool(scope.p("isCommonBlock")),
            "loose": loose,
            "terrain": _section_terrain(lv),
            "terrain_rule": TERRAIN_RULE,
            "stream_blocks": _section_stream_blocks(lv),
            "top_fragment": asset,
        },
        "fragments": _section_fragments(lv),
        "stable_ids": list(lv.stable_ids),  # by instance index (conventions "stable_uid")
        "characters": _section_characters(lv, defs),
        "groups": _section_groups(lv),
        "character_defs": defs,
        "models": _section_models(lv, cubes, culling),
        "volumes": _section_volumes(lv, graph, ai_mask, sheets),
        "path_objects": _section_path_objects(lv, ai_index),
        "nav": None,
        "combat_presets": _section_combat(lv),
        "cube_maps": cubes,
        "cube_map_rule": CUBE_MAP_RULE,
        "culling": culling,
        "graph": graph,
        "checkpoints": _section_checkpoints(lv, graph),
        "cameras": _section_cameras(lv),
        "movies": _section_movies(lv),
        "game_events": _section_events(lv),
        "spawn_recipe": {
            "reapplyable_fragments": reapplyable_fragments(extract_out) if extract_out else [],
            "spawners": [lv.brief(n) for n in lv.level if n.cls == "CharacterSpawner"],
            "rule": (
                "a placed CharacterRoot is built when it is activated and near: the engine "
                "applies the definition's root_template and visual fragments (reapplyable) "
                "to it; see character_defs"
            ),
        },
    }
    out["auto_sequences"] = _section_auto_sequences(lv)
    out["waypoints"] = _section_waypoints(lv)
    out["lights"] = _section_lights(lv)
    out["scene_ctrl"] = _section_scene_ctrl(lv)
    for n in lv.level:  # every reference of the level, so nothing unresolved goes unseen
        for prop in _refs(n):
            lv.resolve(n, prop)
    out["unresolved"] = lv.unresolved
    nav = None
    if extract_out and out["path_objects"]:
        try:
            nav = find_nav(extract_out, name, loose)
            if nav[0] is None:  # say so: a null `nav` alone reads like "nothing to link"
                out["nav_note"] = NAV_MISSING_NOTE
        except Exception as ex:  # unreadable path data must not stop the level export
            nav = None
            out["nav"] = {"error": "%s: %s" % (type(ex).__name__, ex)}
    kinds = {}
    for r in graph["nodes"]:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    chars = out["characters"]

    def tally(key, sub, *values):
        return sum(1 for c in chars if c[key][sub] in values)

    out["counts"] = {
        "nodes": len(lv.level),
        "fragments": len(out["fragments"]),
        "characters": len(chars),
        "characters_variant_fixed": tally("variant", "status", "fixed", "fixed_scene_model"),
        "characters_variant_candidates": tally("variant", "status", "candidates"),
        "weapons_fixed": tally("weapon", "status", "fixed"),
        "weapons_candidates": tally("weapon", "status", "candidates"),
        "weapons_none": tally("weapon", "status", "none"),
        "characters_passive": tally("ai_start", "state_of_mind", "PASSIVE"),
        "characters_aggressive": tally("ai_start", "state_of_mind", "AGGRESSIVE"),
        "set_ai_state_actions": sum(
            1
            for n in lv.level
            if n.cls == "TriggerActionCharacter" and _signed(n.p("m_iactiontype", -1)) == 1
        ),
        "forced_state_actions": sum(1 for r in graph["nodes"] if "forced_state" in r),
        "weapons_no_collection": sum(1 for c in chars if c["weapon"].get("no_collection")),
        "parent_link_1": sum(1 for n in lv.level if _signed(n.p("parentLink", 0)) == 1),
        "placements_below_transformless_ancestor": sum(
            1 for m in out["models"] if m.get("parent_chain_without_transform")
        ),
        "host_offset_copies": sum(1 for m in out["models"] if "host_offset_copy" in m),
        "volumes_block_ai_sight": sum(1 for v in out["volumes"] if v["ai_sight"]["blocks"] is True),
        "groups": len(out["groups"]),
        "groups_with_zone_trigger": sum(1 for g in out["groups"] if g["zone_trigger"]),
        "combat_preset_switches": len(out["combat_presets"]["switches"]),
        "cube_maps": len(out["cube_maps"]),
        "cube_maps_candidate_at_load": sum(1 for c in out["cube_maps"] if c["candidate_at_load"]),
        "models_cube_by_area_single": sum(
            1 for m in out["models"] if len(m["cube_map_by_area"]) == 1
        ),
        "models_cube_by_area_multiple": sum(
            1 for m in out["models"] if len(m["cube_map_by_area"]) > 1
        ),
        "models_cube_by_area_single_differs_from_file_rule": sum(
            1
            for m in out["models"]
            if len(m["cube_map_by_area"]) == 1
            and (m["cube_map_by_area"][0]["cube"] or {}).get("uid")
            != (m["cube_map"] or {}).get("uid")
        ),
        "culling_boxes": len(out["culling"]["boxes"]),
        "culling_groups": len(out["culling"]["groups"]),
        "lights": len(out["lights"]),
        "lights_with_flicker": sum(1 for x in out["lights"] if "flicker" in x),
        "waypoints": len(out["waypoints"]["nodes"]) if out["waypoints"] else 0,
        "stream_blocks": len(out["files"]["stream_blocks"]),
        "sequence_actions": sum(1 for e in graph["edges"] if e["kind"] == "sequence_action"),
        "tour_cuts": sum(len(t["cuts"]) for t in out["cameras"]["tours"]),
        "models_hidden_by_pvs_root": sum(
            1 for m in out["models"] if m["visible"] and not m["visible_effective"]
        ),
        "models_with_part_overrides": sum(1 for m in out["models"] if m["part_overrides"]),
        "models": len(out["models"]),
        "volumes": len(out["volumes"]),
        "path_objects": len(out["path_objects"]),
        "path_objects_linked": 0,
        "path_objects_unbound": sum(1 for p in out["path_objects"] if not p["bound_at_run_time"]),
        "conditions": kinds.get("condition", 0),
        "actions": kinds.get("action", 0),
        "use_triggers": kinds.get("use", 0),
        "triggers": kinds.get("trigger", 0),
        "edges": len(graph["edges"]),
        "checkpoints": len(out["checkpoints"]),
        "camera_tours": len(out["cameras"]["tours"]),
        "movies": len(out["movies"]["actions"]),
        "action_order_ties": sum(
            1
            for n in lv.level
            if _kind(n) in ("condition", "action")
            and len(set(c.p("siblingOrder", 0) for c in n.children if _is_action(c)))
            < len([c for c in n.children if _is_action(c)])
        ),
        "references_resolved": lv.resolved,
        "references_unresolved": len(lv.unresolved),
    }
    if nav and nav[0] is not None:
        link_nav(out, nav[0], source=nav[1])
    return _frame.stamp_json(out)  # marker after `format` (true frame only)


def levels(extract_out):
    """[(scene path, level name, scope node id, asset)] of every level of an extract."""
    out = []
    for sc in find_scenes(extract_out):
        for name, nid, asset in scene_levels(sc):
            out.append((sc, name, nid, asset))
    return out


def write(extract_out, out_dir, only=None, log=print):
    """Write `<level>.level.json` for every level (or the names in `only`).
    -> [(path, counts)]"""
    found = levels(extract_out)
    if not found:
        raise FileNotFoundError("no *.scene with load-block levels under %s" % extract_out)
    os.makedirs(out_dir, exist_ok=True)
    want = set(x.lower() for x in only) if only else None
    done = []
    import canonical_names

    # --names canonical: one listing of the export's files serves every level
    names = None
    if canonical_names.export_mode(extract_out) == "canonical":
        names = canonical_names.ExportIndex(extract_out)
    for sc, name, nid, asset in found:
        if want is not None and name.lower() not in want:
            continue
        j = build_level(sc, name, nid, extract_out)
        if names is not None:
            # every string that names an exported file: spelled as the file is
            # written, the stored string beside it under "stored"
            canonical_names.respell_export(j, extract_out, names)
            # the movie path inside a graph label ("MOVIE /Art/cutscenes/X.bik")
            j[canonical_names.NAMES_KEY]["respelled"] += canonical_names.respell_after(
                j, names, "label", "MOVIE "
            )
        path = os.path.join(out_dir, "%s.level.json" % name)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(j, fh, indent=1)
        c = j["counts"]
        if log:
            log(
                "  %-16s %5d nodes  %3d characters  %4d models  %3d conditions  %4d actions  "
                "%2d checkpoints  %d unresolved -> %s"
                % (
                    name,
                    c["nodes"],
                    c["characters"],
                    c["models"],
                    c["conditions"],
                    c["actions"],
                    c["checkpoints"],
                    c["references_unresolved"],
                    path,
                )
            )
            if j.get("nav_note"):
                log(
                    "    WARNING: %s: %d path objects but no path data (.hpd) in %s: nav not linked"
                    " (see nav_note)" % (name, c["path_objects"], extract_out)
                )
        done.append((path, c))
    return done


# ---------------------------------------------------------------- .kpw saves

_SAVE_TYPES = (
    "truth number integer string vector color quaternion Entity "
    "list(truth) list(number) list(integer) list(string) list(vector) list(Entity) "
    "list(list(truth)) list(list(number)) list(list(integer)) list(list(string))"
).split()


#: enum SAVE_DEVICES (registered 0x775ad0..0x775b25; INVALID = -1)
SAVE_DEVICES = {
    0: "X360_PS3",
    1: "KEYBOARD_MOUSE",
    2: "GENERIC_PC_GAMEPAD",
    3: "LOGITECH_RUMBLEPAD_2",
    4: "SMARTJOY_PLUS_ADAPTOR",
    5: "TIGERGAME_PS_PS2_GAME_CONTROLLER_ADAPTER",
}
#: enum LOGICAL_INPUT_BUTTON (registered in ProjectLib 0x80d17a..0x80d3b8; NONE = -1,
#: 40 = SIZE; the values missing here are not registered)
LOGICAL_INPUT_BUTTONS = {
    0: "MENU_UP",
    1: "MENU_DOWN",
    2: "MENU_SELECT",
    3: "MENU_BACK",
    4: "MENU_START",
    5: "MENU_LEFT",
    6: "MENU_RIGHT",
    7: "MENU_ABILITIES",
    8: "MENU_JOIN_COOP__PC_EDITOR_ONLY",
    11: "DEBUG_MOVE_UP",
    12: "DEBUG_MOVE_DOWN",
    13: "DEBUG_MOVE_SPRINT",
    18: "CAMERA_LOOK_AT_WAYPOINT",
    20: "PLAYER_TARGET",
    21: "PLAYER_ATTACK_0",
    22: "PLAYER_ATTACK_1",
    23: "PLAYER_ATTACK_2",
    24: "PLAYER_USE",
    25: "PLAYER_SPECIAL_ATTACK_1",
    26: "PLAYER_COUNTER_ATTACK",
    27: "PLAYER_SPECIAL_ATTACK_2",
    28: "PLAYER_DEFEND",
    30: "MOVEMENT_STICK_UP",
    31: "MOVEMENT_STICK_DOWN",
    32: "MOVEMENT_STICK_LEFT",
    33: "MOVEMENT_STICK_RIGHT",
    34: "CAMERA_CENTER",
    35: "CAMERA_LOOK_AT_PARTNER",
    36: "CAMERA_STICK_UP",
    37: "CAMERA_STICK_DOWN",
    38: "CAMERA_STICK_LEFT",
    39: "CAMERA_STICK_RIGHT",
}


_INPUT_CODES = []


def input_code_name(device, code):
    """Name of button code `code` of save device `device` (a SAVE_DEVICES name), or None:
    GamepadButton on the pad devices; on KEYBOARD_MOUSE KeyboardKeys below 256 and
    "MOUSE_BUTTON_*" for 256 + a MouseButtons value (wlib/input_code_enums.json; the
    tables are read from code, their use for these codes is inferred)."""
    if not _INPUT_CODES:
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "input_code_enums.json"), encoding="utf-8") as fh:
            _INPUT_CODES.append(json.load(fh))
    t = _INPUT_CODES[0]
    if device != "KEYBOARD_MOUSE":
        return t["GamepadButton"].get(str(code))
    if code >= 256:
        return t["MouseButtons"].get(str(code - 256))
    return t["KeyboardKeys"].get(str(code))


def button_map(value):
    """`decoded.button_map` of a SettingsState.m_emetadevicebuttonmap value
    (list(list(list(list(integer)))), 675 words in a shipped profile): [save device]
    [player][logical button][code], -1 = no code; a player without a map has an empty
    button list (`shape` = the largest count at each level).  None when the value is
    not four lists deep.  Only devices / players / buttons that hold a code are
    listed."""

    def ints(x):
        return isinstance(x, list) and all(isinstance(c, int) for c in x)

    if not (
        isinstance(value, list)
        and value
        and all(
            isinstance(pl, list)
            and all(isinstance(bt, list) and all(ints(c) for c in bt) for bt in pl)
            for pl in value
        )
    ):
        return None
    buttons = [bt for pl in value for bt in pl]
    shape = [
        len(value),
        max([len(pl) for pl in value] or [0]),
        max([len(bt) for bt in buttons] or [0]),
        max([len(c) for bt in buttons for c in bt] or [0]),
    ]
    devices = {}
    for di, players in enumerate(value):
        out = []
        for pi, buttons in enumerate(players):
            used = {
                LOGICAL_INPUT_BUTTONS.get(bi, str(bi)): [c for c in codes if c != -1]
                for bi, codes in enumerate(buttons)
                if any(c != -1 for c in codes)
            }
            if used:
                out.append({"player": pi, "buttons": used})
        if out:
            devices[SAVE_DEVICES.get(di, str(di))] = out
    names = {}
    for dev, players in devices.items():
        codes = sorted(set(c for pl in players for cs in pl["buttons"].values() for c in cs))
        named = {str(c): input_code_name(dev, c) for c in codes}
        names[dev] = {k: v for k, v in named.items() if v}
    return {
        "shape": shape,
        "index_order": ["save_device", "player", "logical_button", "code"],
        "devices": devices,
        "code_names": names,
        "evidence": (
            "read: the type hash 0x2bf20fb4 is list(list(list(list(integer)))); index 1 = "
            "SAVE_DEVICES (resized to InputLib.g_isave_device_list_max_number in "
            "SettingsState.initialize_local 0x82bc77), index 2 = the player "
            "(GameStateCtrl.command_has_any_input_map 0x74d04e).  inferred from the content: "
            "index 3 = LOGICAL_INPUT_BUTTON 0..40 and three alternative codes per button.  "
            "code_names: the engine registers GamepadButton 0-15 (0x4d3514), KeyboardKeys "
            "with 118 names (0x4cc842) and MouseButtons 1 / 2 / 4 (0x4db801), read from code; "
            "that a pad device's codes are GamepadButton values, a KEYBOARD_MOUSE code "
            "below 256 a KeyboardKeys value and 256 + n the mouse button n is inferred from "
            "the fit with one shipped profile (every code of it has a name); the code that "
            "fills the map and the 256 offset were not read"
        ),
    }


def _type_ids():
    import kapow_props

    return {kapow_props.name_hash(t): t for t in _SAVE_TYPES}


def _save_value(ty, w, p):
    """(value, next index) of a `ty` value at word p of the record's words."""
    if ty.startswith("list(") and ty.endswith(")"):
        n = w[p]
        p += 1
        if n > len(w):
            raise ValueError("list count")
        out = []
        for _ in range(n):
            v, p = _save_value(ty[5:-1], w, p)
            out.append(v)
        return out, p
    if ty == "truth":
        return bool(w[p]), p + 1
    if ty == "integer":
        return _signed(w[p]), p + 1
    if ty == "number":
        return struct.unpack("<f", struct.pack("<I", w[p]))[0], p + 1
    if ty in ("vector", "color", "quaternion"):
        n = 4 if ty == "quaternion" else 3
        return list(struct.unpack("<%df" % n, struct.pack("<%dI" % n, *w[p : p + n]))), p + n
    if ty == "string":
        n = w[p]
        raw = struct.pack("<%dI" % n, *w[p + 1 : p + 1 + n])
        return raw.split(b"\x00")[0].decode("latin1"), p + 1 + n
    if ty == "Entity":
        return "%08x" % w[p], p + 1
    raise ValueError(ty)


def parse_save(data):
    """A `.kpw` save file -> dict ("watchmen-save-meta/1").

    u32 5, "KPWF", u8, u32, u32 titleChars, UTF-16LE title, u32 payloadBytes, then
    records [u32 entity id][u32 property name hash][u32 type id][u32 nWords][words]:
    the fragment reader's typed mode with the entity in front (type id = name hash of
    the type name).  A record whose type is not known keeps `raw_words`."""
    import kapow_fragment
    import kapow_props

    if len(data) < 21 or data[4:8] != b"KPWF":
        raise ValueError("not a .kpw save file (no KPWF magic)")
    version, flag, kind, nchars = struct.unpack_from("<I4xBII", data, 0)
    p = 17
    title = data[p : p + 2 * nchars].decode("utf-16-le", "replace").rstrip("\x00")
    p += 2 * nchars
    (size,) = struct.unpack_from("<I", data, p)
    p += 4
    end = min(len(data), p + size)
    types = _type_ids()
    names = kapow_props.namedict()
    recs = []
    while p + 16 <= end:
        ent, key, tid, nw = struct.unpack_from("<4I", data, p)
        p += 16
        if p + 4 * nw > end:
            raise ValueError("record at %d runs past the payload" % (p - 16))
        words = list(struct.unpack_from("<%dI" % nw, data, p))
        p += 4 * nw
        known = kapow_fragment.NAMES.get(key)  # (name, declared type) of the key table
        name = (known[0] if known else None) or names.get(key) or "key_%08x" % key
        ty = types.get(tid)
        if ty is None and known and kapow_props.name_hash(known[1]) == tid:
            ty = known[1]  # a type the table declares, e.g. a deeper list nesting
        rec = {"entity": "%08x" % ent, "property": name, "type": ty or "type_%08x" % tid}
        try:
            if ty is None:
                raise ValueError("type")
            v, used = _save_value(ty, words, 0)
            if used != nw:
                raise ValueError("length")
            rec["value"] = v
        except (ValueError, IndexError, struct.error):
            rec["raw_words"] = words
        recs.append(rec)
    out = {
        "format": SAVE_FORMAT,
        "evidence": (
            "data: both files of a real profile decode to the last byte with this layout; "
            "read: the record is the fragment reader's typed mode (0x545e1b)"
        ),
        "version": version,
        "flag": flag,
        "kind": kind,
        "title": title,
        "payload_bytes": size,
        "trailing_bytes": len(data) - end,
        "entities": sorted(set(r["entity"] for r in recs)),
        "records": recs,
    }
    vals = {r["property"]: r.get("value") for r in recs}
    dec = {}
    if isinstance(vals.get("m_ilastcheckpoint"), list):
        dec["last_checkpoint"] = {
            enum_name("SAVE_GAME_TYPE", i) or str(i): v
            for i, v in enumerate(vals["m_ilastcheckpoint"])
        }
    if isinstance(vals.get("m_blevelcompletelist"), list):
        dec["completed_scenes"] = {
            enum_name("SAVE_GAME_TYPE", i)
            or str(i): [{"id": s, "name": enum_name("SCENE_ID", s)} for s in v]
            for i, v in enumerate(vals["m_blevelcompletelist"])
            if isinstance(v, list)
        }
    bm = button_map(vals.get("m_emetadevicebuttonmap"))
    if bm:
        dec["button_map"] = bm
    if dec:
        out["decoded"] = dec
    return out


def read_save(path):
    with open(path, "rb") as fh:
        return parse_save(fh.read())


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: level_meta.py EXTRACT_OUT OUT_DIR [LEVEL ...]")
        raise SystemExit(2)
    write(sys.argv[1], sys.argv[2], sys.argv[3:] or None)
