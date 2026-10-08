#!/usr/bin/env python3
"""fx_meta -- what a move shows besides the animation: effects, camera, rumble.

Additive to anim_meta.json (hook: anim_meta.build calls attach()):

  events[*].payload   the argument slots of the event node that are set, under
                      their property names (_etarget00..02, m_ivalue00,
                      m_nvalue02..10, m_ttruth1..3, m_vvalue1/2)
  events[*].payload_stale  names of set slots the handler of that event id does
                      not read (event nodes are copied in the editor and keep
                      the values of their former id); fx.event_fields[id] names
                      the slots an id's handler READS.  For an id without an
                      entry there, every set slot is in `payload`; `payload_editor_hidden`
                      names the set slots the editor does not show for that id
  state.fx            the decoded lists of one state: impact_effects,
                      camera_cuts, camera_return, rumble, look_at, slow_motion,
                      weapon_events, effect_events, depth_of_field -- each entry
                      with the firing time anim_meta computed for its event
                      (playpos, time_s on the clip, play_time_s since entry)
  pair.camera_cuts    the master's cuts on the pair's shared clock, with
  pair.camera_return  the return to the character camera, the shot list and the
  pair.fx             impact effects of both actors resolved to effects
  fx (top level)      the tables: effects, effect definitions per character
                      family, the dispatch rule, weapons, particle facts, the
                      effect type x surface GFX matrix, character attachments
                      (emitters / light flashes on bones), camera constants and
                      the per-player camera rig
  fx_format           FORMAT

Evidence marks in every table: "read" = traced in the executable (address
given), "data" = read from the game files, "inferred", "not established".
Sounds are NOT repeated here: an effect's sound is a key into sound_meta.json
`definitions`; effect and effect-definition keys are sound_meta's
('<fragment>#<node id>').

Engine rules used (KapowMultiDEDRM.exe, Part 2 PC):
  * effect dispatch   CharacterEffectDef.command_play_damage_effect 0x6673d0
  * IMPACT_EFFECTS    CharacterRootLogic event case 56 @ 0x6aae6f
  * CAMERA_CUT        case 59 @ 0x6aa7e4 -> CameraCombatSpecialCuts
                      .command_set_cut_data 0x6325c5, SetValidStartPos 0x6341f7,
                      GetLookAtPosition 0x634125, UpdateWorldOrient 0x626a15;
                      hold update 0x633011 (position fixed, the aim tracks),
                      blend 0x63312e / 0x6337aa, HasValidTransition 0x634f62
  * CAMERA_CUT_TO_CHARACTER_CAM  case 61 @ 0x6aa036
  * LOOK_AT_TARGET    case 45 @ 0x6a86ae;  RUMBLE case 82 @ 0x6a7879

CLI:  python3 fx_meta.py EXTRACT_OUT OUT.json [ANIM_META.json]
"""

import json
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

import anim_state_machine as asm  # noqa: E402
import engine_enums as ee  # noqa: E402

FORMAT = "watchmen-fx-meta/1"

# ------------------------------------------------------------------- enums
# registered by the script classes (enum registration 0x5052c9); ids as stored
EFFECTS = {
    -1: "NONE",
    0: "ELECTRIC_ARMOR_CHARGE",
    1: "ELECTRIC_ARMOR_DISCHARGE",
    2: "ELECTRIC_ARMOR_STOP",
    3: "ELECTRIC_ARMOR_FIZZLE",
    4: "GRAP_GUN_FIRE",
    5: "GRAP_GUN_RELOAD",
    6: "GRAP_GUN_HIT",
    7: "GRAP_GUN_WIND_IN",
    8: "STUN_GRENADE",
    9: "GRAP_GUN_ROPE",
    10: "UBER_RAGE_DAMAGE_HIGH",
    11: "UBER_RAGE_DAMAGE_LOW",
    12: "UBER_RAGE_INITIALIZE",
    13: "UBER_RAGE_ACTIVE",
    14: "UNDERBOSS_FLAMETHROWER",
    15: "UNDERBOSS_LAND_EFFECT",
    16: "UNDERBOSS_PILOT_LIGHT",
    17: "UNDERBOSS_FIRE_RESIDUE",
    18: "FIRE_BURST",
}
PLACEMENT = {0: "ENTITY", 1: "POS_AND_ORIENT"}
WEAPON_EFFECT_TYPES = {0: "WOOD", 1: "STEEL", 2: "SHARP", 3: "TASER"}
WEAPON_TYPES = {-1: "NONE", 0: "BASH_1H", 1: "BASH_2H"}
HIT_POSITIONS = {0: "HEAD", 1: "BODY"}
CHARACTER_BONE_TYPE = {
    0: "HEAD",
    1: "NECK",
    2: "SPINE2",
    3: "SPINE1",
    4: "SPINE",
    5: "PELVIS",
    6: "LEFT_UPPER_ARM",
    7: "LEFT_FORE_ARM",
    8: "LEFT_HAND",
    9: "LEFT_THIGH",
    10: "LEFT_CALF",
    11: "LEFT_FOOT",
    12: "RIGHT_UPPER_ARM",
    13: "RIGHT_FORE_ARM",
    14: "RIGHT_HAND",
    15: "RIGHT_THIGH",
    16: "RIGHT_CALF",
    17: "RIGHT_FOOT",
    18: "GAME_PIVOT",
    19: "LEFT_CLAVICLE",
    20: "LEFT_TWIST",
    21: "RIGHT_CLAVICLE",
    22: "RIGHT_TWIST",
}
BONE_GAME_PIVOT = 18  # GetLookAtPosition 0x634125: the root position + look-at height
# CharacterVisual.SetupBoneMap 0x67a31e: bone type -> the joint found by this name
# (Character.FindBoneIndex); a type out of range reads entry 18
BONE_JOINTS = {
    0: "Head",
    1: "Neck",
    2: "Spine2",
    3: "Spine1",
    4: "Spine",
    5: "Pelvis",
    6: "L UpperArm",
    7: "L Forearm",
    8: "L Hand",
    9: "L Thigh",
    10: "L Calf",
    11: "L Foot",
    12: "R UpperArm",
    13: "R Forearm",
    14: "R Hand",
    15: "R Thigh",
    16: "R Calf",
    17: "R Foot",
    18: "GamePivot",
    19: "L Clavicle",
    20: "LUpArmTwist",
    21: "R Clavicle",
    22: "RUpArmTwist",
}
CAMERA_CHARACTER_DB = {
    0: "DEFAULT",
    1: "RUN",
    2: "COMBAT",
    3: "IDLE",
    4: "UP_DRAIN_PIPE_GET_ON",
    5: "UP_DRAIN_PIPE_GET_OFF",
    6: "OVER_SHOULDER",
    7: "NOT_USED_01",
    8: "GRAPPLING_HOOK",
    9: "WALK",
    10: "UP_DRAIN_PIPE_CLIMB",
    11: "DOWN_DRAIN_PIPE_GET_ON",
    12: "DOWN_DRAIN_PIPE_CLIMB",
    13: "DOWN_DRAIN_PIPE_GET_OFF",
    14: "JUMP_DOWN",
    15: "JUMP_DOWN_LAND",
    16: "FORCE_BEHIND",
    17: "LOOK_AT_PARTNER",
    18: "GRAPLING_HOOK_UP_TAKE_OFF",
    19: "GRAPLING_HOOK_UP_LAND",
    20: "GRAPLING_HOOK_DOWN_TAKE_OFF",
    21: "GRAPLING_HOOK_DOWN_LAND",
    22: "COMBAT_AVOID_ILLEGAL_POS",
    23: "COMBAT_ON_ATTACK_MANIPULATOR",
    24: "COMBAT_AVOID_CORNER",
    25: "COMBAT_AVOID_WALL",
    26: "HELPER",
}
CAMERA_ANIMATION_EVENTS = {
    0: "DEFAULT",
    1: "UP_DRAIN_PIPE_GET_ON",
    2: "UP_DRAIN_PIPE_CLIMB",
    3: "UP_DRAIN_PIPE_GET_OFF",
    4: "DOWN_DRAIN_PIPE_GET_ON",
    5: "DOWN_DRAIN_PIPE_CLIMB",
    6: "DOWN_DRAIN_PIPE_GET_OFF",
    7: "JUMP_DOWN",
    8: "JUMP_DOWN_LAND",
    9: "GRAPLING_HOOK_UP_TAKE_OFF",
    10: "GRAPLING_HOOK_UP_LAND",
    11: "GRAPLING_HOOK_DOWN_TAKE_OFF",
    12: "GRAPLING_HOOK_DOWN_LAND",
}

# ANIMATION_EVENT ids decoded here
EV_SOUND, EV_CAMERA, EV_KILL_PARTNER, EV_WEAPON_STEAL, EV_EXTEND_COMBO = 9, 18, 20, 32, 35
EV_PICK_UP_WEAPON, EV_SPEAK, EV_LOOK_AT, EV_IMPACT_EFFECTS, EV_SAFE_RAGDOLL = 36, 37, 45, 56, 57
EV_DROP_WEAPON, EV_CAMERA_CUT, EV_UBER_RAGE, EV_CAMERA_RETURN = 58, 59, 60, 61
EV_KNEE, EV_RAGDOLL_MODIFIER, EV_DROP_WEAPON_ANIM, EV_AUTO_ALIGN, EV_RUMBLE = 72, 73, 75, 80, 82
EV_DEPTH_OF_FIELD = 89

# ------------------------------------------------------------ dispatch rule
# ProjectAnimationLib.IsUpperDamagePose 0x7f077c (20 and 21 count as upper, 22 not)
UPPER_POSES = frozenset((1, 2, 3, 7, 8, 9, 13, 14, 15, 19, 20, 21, 23, 25, 27))
FAST_POSES = frozenset((1, 2, 5, 6, 23, 24))  # 3 and 4 take the heavy effect, as coded
KNOCKDOWN_POSES = frozenset((17, 18, 27, 28))
STUN_POSES = frozenset((19, 20, 21, 22))
TASER_EFFECT_ID = 1  # ELECTRIC_ARMOR_DISCHARGE, fired before the STEEL entry
DAMAGE_SLOTS = (
    "headfast headheavy headuber headweaponwood headweaponsteel headkill bodyfast bodyheavy "
    "bodyuber bodyweaponwood bodyweaponsteel bodykill sharpweapon stun knockdown block"
).split()
WEAPON_CASES = ("unarmed", "wood", "steel", "sharp", "taser", "uber", "kill")


def hit_position(pose):
    """0 HEAD / 1 BODY of a DAMAGE_POSE (None for pose 0: nothing is played)."""
    if not pose:
        return None
    return 0 if pose in UPPER_POSES else 1


def damage_slots(pose, case="unarmed"):
    """The CharacterEffectDef slots command_play_damage_effect 0x6673d0 fires
    for a damage pose, in firing order.  case: 'unarmed', a weapon effect type
    ('wood' / 'steel' / 'sharp' / 'taser'), 'uber' (the inflictor is in uber
    rage) or 'kill' (a killing hit).  An entry is a slot name, or
    'effect_id:<n>' for an effect fired by id (the TASER discharge)."""
    hp = hit_position(pose)
    if hp is None:
        return []
    part = "head" if hp == 0 else "body"
    out = []
    if case == "uber":
        out.append(part + "uber")
    elif case == "kill":
        out.append(part + "kill")
    elif case == "taser":
        out += ["effect_id:%d" % TASER_EFFECT_ID, part + "weaponsteel"]
    elif case == "wood":
        out.append(part + "weaponwood")
    elif case == "steel":
        out.append(part + "weaponsteel")
    elif case == "sharp":
        out.append("sharpweapon")
    else:
        out.append(part + ("fast" if pose in FAST_POSES else "heavy"))
    if pose in KNOCKDOWN_POSES:
        out.append("knockdown")
    elif pose in STUN_POSES:
        out.append("stun")
    return out


def impact_rumble(pose):
    """The rumble the IMPACT_EFFECTS case sends for a pose (0x6aae6f; only when
    the acting character has a PlayerCtrl and the hit is confirmed):
    {duration_s, power, fade} or None."""
    if pose in (1, 2, 3, 4, 5, 6, 23, 24):
        return {"duration_s": 0.2, "power": 0.15, "fade": False}
    if pose in (7, 8, 9, 10, 11, 12, 19, 20, 21, 22, 25, 26):
        return {"duration_s": 0.35, "power": 0.2, "fade": True}
    if pose in (13, 14, 15, 16, 17, 18, 27, 28):
        return {"duration_s": 0.55, "power": 0.2, "fade": True}
    return None


def recoil_intensity(pose):
    """CharacterRoot.command_do_recoil 0x6902c0: the camera recoil intensity of
    a pose (tilt = 0.025 rad * intensity, fov factor = 1 - 0.06 * intensity,
    both over 0.3 s)."""
    if pose in (1, 2, 3, 4, 5, 6, 23, 24):
        return 0.5
    if pose in (7, 8, 9, 10, 11, 12, 25, 26):
        return 1.0
    if pose in (13, 14, 15, 16, 17, 18, 27, 28):
        return 2.1
    if pose in (19, 20, 21, 22):
        return 1.4
    return 0.2


# ----------------------------------------------------------- event payload
# AnimationEventWM's generic argument slots (registration order 0x5e44e8)
EXTRA_FIELDS = (
    ("m_tforceupdateblends",)
    + tuple("_etarget%02d" % i for i in range(3))
    + ("m_ivalue00",)
    + tuple("m_nvalue%02d" % i for i in range(2, 11))
    + ("m_ttruth1", "m_ttruth2", "m_ttruth3", "m_vvalue1", "m_vvalue2")
)

# event id -> (handler address, {property: (argument name, meaning)}).  Only the
# properties the case READS are listed (lifted CharacterRootLogic
# .command_animation_event_received 0x6a525e); everything else on the node is
# stale for that id.
EVENT_FIELDS = {
    EV_SOUND: (
        "0x6aba76",
        {
            "_etarget00": ("sound_definition", "the SoundDef (resolved in sound_meta.json)"),
            "m_ivalue00": (
                "position_mode",
                "0 = at the node's world position (editor name FEET), 1 = on the character entity"
                " (editor name CENTER); CHARACTER_AREAS, 0x6728c5 / 0x6728d7",
            ),
            "m_ttruth1": ("as_speak", "played as a speak line (START_SPEAK to the face)"),
        },
    ),
    EV_CAMERA: (
        "0x64b304",
        {
            "m_ivalue00": (
                "camera_event",
                "CAMERA_ANIMATION_EVENTS id: forces a character-camera state (drain pipe, "
                "jump down, grappling hook); handled by CharacterCamera, not by the root logic",
            )
        },
    ),
    EV_KILL_PARTNER: ("0x6ac5f6", {"m_ttruth1": ("silent", "no death speak line")}),
    EV_EXTEND_COMBO: ("0x6ac9bf", {"m_nvalue": ("seconds", "combo window = now + seconds")}),
    EV_SPEAK: (
        "0x6a9f30",
        {
            "m_ivalue00": ("speak_id", "SPEAK_ID"),
            "m_ttruth1": ("stop_first", "stop and quarantine the current line first"),
        },
    ),
    EV_LOOK_AT: (
        "0x6a86ae",
        {
            "m_nvalue": ("time_s", "seconds the character camera looks at the target"),
            "m_nvalue02": ("fov_factor", "FOV factor during the look-at"),
            "m_ttruth1": ("look_at_self", "target = the character itself, else its attack target"),
            "m_ivalue00": ("effect", "1 = also orbit 180 degrees (command_force_rotate(pi, time))"),
        },
    ),
    EV_IMPACT_EFFECTS: (
        "0x6aae6f",
        {
            "m_ivalue00": ("damage_pose", "DAMAGE_POSE"),
            "m_vvalue1": ("local_position", "impact point in the acting character's visual space"),
            "m_vvalue2": ("local_direction", "impact direction, same space"),
            "m_ttruth1": (
                "truth1",
                "target choice (false: the animation partner when there is one); when set, "
                "CharacterRootLogic.SetCloseCombatDamageToTarget(victim, m_ecuranimstate, "
                "m_nvalue) 0x6ae57f is called",
            ),
            "m_nvalue": (
                "override_damage",
                "damage of that call when > 0, else the state's default damage "
                "(_nnextdefaultdamage)",
            ),
            "m_ttruth2": ("ignore_weapon", "the effect is chosen as if unarmed"),
            "m_ttruth3": ("fire_extra_effect", "also fire the effect _etarget01 at the point"),
            "_etarget01": ("extra_effect", "an EffectBase fired with Z along the direction"),
        },
    ),
    EV_SAFE_RAGDOLL: (
        "0x6a8031",
        {
            "m_nvalue": (
                "safe_time_s",
                "third argument of the group call; editor caption 'Ragdoll Safe Time:'",
            )
        },
    ),
    EV_CAMERA_CUT: (
        "0x6aa7e4",
        {
            "m_nvalue": ("transition_s", "blend time to this shot; 0 = a hard cut"),
            "m_ttruth1": ("look_at_attack_target", "look at the victim, else at the actor"),
            "m_ivalue00": ("look_at_bone", "CHARACTER_BONE_TYPE of the looked-at character"),
            "m_nvalue09": (
                "look_at_height_m",
                "added to the root when the bone is GAME_PIVOT (not exposed by the editor,"
                " 0x5c1767; set on 0 of 259 Part 2 and 0 of 149 Part 1 events)",
            ),
            "m_nvalue02": ("distance_m", "horizontal distance of the camera from its base"),
            "m_nvalue05": ("height_m", "camera height above the base character's root"),
            "m_nvalue10": ("angle_deg", "see fx.camera.cut_placement; 0 = side shot"),
            "m_nvalue03": ("fov_deg", "vertical FOV (co-op uses the camera's ncoopfov)"),
            "m_nvalue04": ("time_multiplier", "world time multiplier during the shot"),
            "m_ttruth2": ("keep_previous_position", "keep the camera position of the last cut"),
            "m_nvalue06": ("shake_time_s", "sinus shake started with the cut"),
            "m_nvalue07": ("shake_time_factor", ""),
            "m_nvalue08": ("shake_size", ""),
        },
    ),
    EV_CAMERA_RETURN: (
        "0x6aa036",
        {
            "m_nvalue": ("transition_s", "blend time back to the character camera"),
            "m_ttruth1": (
                "set_in_vector",
                "first aim the character camera: looking from the actor toward the partner, "
                "16.7 degrees down, heading turned by -45.84 degrees (atan2(x, z) decreases "
                "by 0.8 rad; command_character_cam_set_in_vector)",
            ),
        },
    ),
    EV_KNEE: ("0x6a7ad9", {"m_ivalue00": ("knee", "KNEE: SetAnimationEnum(ctrl, 13, value)")}),
    EV_RAGDOLL_MODIFIER: ("0x6a7996", {"m_nvalue": ("scale", "ragdoll modifier vector length")}),
    EV_AUTO_ALIGN: (
        "0x6aae3c",
        {
            "m_nvalue": ("distance", "auto-align distance term (unit inferred: metres)"),
            "m_nvalue02": ("seconds", "auto-align is forced for this long"),
        },
    ),
    EV_RUMBLE: (
        "0x6a7879",
        {
            "m_nvalue": ("duration_s", "seconds"),
            "m_nvalue02": ("power", "0..1"),
            "m_ttruth1": ("fade", "fade out linearly"),
        },
    ),
    EV_DEPTH_OF_FIELD: (
        "0x6a7619",
        {
            "_etarget00": ("target", "the FXGfxEffectCtrl that fades in"),
            "m_nvalue": ("fade_s", "fade-in time"),
        },
    ),
}
_ENUM_ARGS = {
    (EV_IMPACT_EFFECTS, "damage_pose"): lambda v: ee.name("DAMAGE_POSE", v or 0),
    (EV_CAMERA_CUT, "look_at_bone"): lambda v: CHARACTER_BONE_TYPE.get(v),
    (EV_CAMERA, "camera_event"): lambda v: CAMERA_ANIMATION_EVENTS.get(v),
}


def _unset(v):
    """True for an argument slot at its default (nothing authored)."""
    if v is None or v is False or v == 0:
        return True
    if isinstance(v, (list, tuple)):
        return all(not x for x in v)
    if isinstance(v, dict):
        return v.get("ref") is None and not v.get("xref")
    return False


def _r(v, n=4):
    if isinstance(v, float):
        return round(v, n)
    if isinstance(v, (list, tuple)):
        return [_r(x, n) for x in v]
    return v


def _load_event_editor_params():
    with open(os.path.join(_HERE, "event_editor_params.json"), encoding="utf-8") as fh:
        return json.load(fh)


#: caption, group and range of every event argument the editor exposes, by event id
#: (AnimationEventWM.FilterExposedProperties 0x5c1767; editor data, not game behaviour)
EVENT_EDITOR_PARAMS = _load_event_editor_params()
#: the generic argument slots that filter shows or hides (every one is hidden for an id
#: the table does not list)
EDITOR_SLOTS = tuple(k for k in EXTRA_FIELDS if k != "m_tforceupdateblends")


def editor_hidden(ev):
    """Sorted names of the set generic slots of an event node that the editor does not
    show for its event id (EVENT_EDITOR_PARAMS)."""
    spec = EVENT_EDITOR_PARAMS["events"].get(str(ev.p("m_ianimationevent")))
    shown = spec["params"] if spec else {}
    return sorted(k for k in EDITOR_SLOTS if k not in shown and not _unset(ev.p(k)))


def event_payload(ev, with_stale=False):
    """({property: value}, [stale property names]) of an event node's argument
    slots that are set.  For an event id whose handler is decoded
    (EVENT_FIELDS) the slots that handler does not read are STALE -- left over
    from the node the event was copied from -- and only named, unless
    with_stale.  The four core fields (id, trigger, position, m_nvalue) are
    not repeated; m_nvalue is `value` on the record."""
    spec = EVENT_FIELDS.get(ev.p("m_ianimationevent"))
    out, stale = {}, []
    for k in EXTRA_FIELDS:
        v = ev.p(k)
        if _unset(v):
            continue
        if spec is not None and k not in spec[1]:
            stale.append(k)
            if not with_stale:
                continue
        out[k] = _r(v)
    return out, stale


def event_args(ev):
    """The arguments the handler of this event id reads, by name; {} for an id
    with no decoded arguments."""
    eid = ev.p("m_ianimationevent")
    spec = EVENT_FIELDS.get(eid)
    if not spec:
        return {}
    out = {}
    for prop, (name, _why) in spec[1].items():
        v = ev.p(prop)
        if prop.startswith("_etarget"):
            v = v if isinstance(v, dict) and not _unset(v) else None
        elif prop.startswith("m_ttruth"):
            v = bool(v)
        elif prop.startswith("m_vvalue"):
            v = _r(list(v)) if isinstance(v, (list, tuple)) else None
        elif prop.startswith("m_ivalue"):
            v = asm.s32(v or 0)
        else:
            v = _r(float(v or 0.0))
        out[name] = v
        fn = _ENUM_ARGS.get((eid, name))
        if fn is not None:
            out[name + "_name"] = fn(v)
    return out


def _ev_key(eid, trig, raw):
    return (eid, int(trig or 0), round(float(raw or 0.0), 4))


def decorate_events(state, rec, args=None):
    """Add `payload` / `payload_stale` to the event records of one state record and collect the
    decoded arguments in `args` ({id(event record): event_args()}).  The
    records are matched to the event nodes by (id, trigger, stored position);
    records with one key keep the nodes' order (the record sort is stable)."""
    queues = {}
    for e in asm.state_events(state):
        k = _ev_key(e.p("m_ianimationevent"), asm.event_trigger(e), asm.event_at(e))
        queues.setdefault(k, []).append(e)
    n = 0
    for r in rec.get("events", []):
        q = queues.get(_ev_key(r.get("event_id"), r.get("trigger_id"), r.get("raw")))
        if not q:
            continue
        e = q.pop(0)
        a, (p, stale) = event_args(e), event_payload(e)
        if a and args is not None:
            args[id(r)] = a
        if p:
            r["payload"] = p
        if stale:
            r["payload_stale"] = stale
        hidden = editor_hidden(e)
        if hidden:
            r["payload_editor_hidden"] = hidden
        n += 1
    return n


# ----------------------------------------------------------------- state fx
def _when(e):
    out = {
        "playpos": e.get("playpos"),
        "time_s": e.get("time_s"),
        "play_time_s": e.get("play_time_s"),
    }
    if e.get("trigger_id"):  # not PLAY_POS
        out["trigger"] = e.get("trigger")
    if e.get("fires_first_pass") is False:
        out["fires_first_pass"] = False
    return out


def _impact(e, a, resolve=None):
    """One impact_effects entry.  What the pose selects (slots per weapon case,
    rumble, recoil) is fx.damage_rule.by_pose[pose]."""
    pose = a.get("damage_pose") or 0
    out = _when(e)
    out.update(
        damage_pose=pose,
        damage_pose_name=a.get("damage_pose_name"),
        hit_position=HIT_POSITIONS.get(hit_position(pose)),
        local_position=a.get("local_position"),
        local_direction=a.get("local_direction"),
        ignore_weapon=bool(a.get("ignore_weapon")),
    )
    if a.get("truth1"):
        # the event deals close-combat damage itself (SetCloseCombatDamageToTarget 0x6ae57f)
        out["deals_damage"] = True
        out["override_damage"] = a.get("override_damage")
        out["truth1"] = True  # the two names of 1.4.0's first tables, kept
        out["value"] = a.get("override_damage")
    if a.get("fire_extra_effect") and a.get("extra_effect"):
        ref = a["extra_effect"]
        out["extra_effect"] = (resolve(ref) if resolve else None) or {"unresolved": ref}
    return out


def _cut(e, a):
    out = _when(e)
    out["transition_s"] = a.get("transition_s")
    out["look_at"] = "attack_target" if a.get("look_at_attack_target") else "actor"
    out["look_at_bone"] = a.get("look_at_bone")
    # GetLookAtPosition 0x634125: bone 18 is the looked-at character's ROOT node +
    # look_at_height_m, not a joint; every other bone type is a joint of the bone map
    root = a.get("look_at_bone") == BONE_GAME_PIVOT
    out["look_at_joint"] = (
        None if root else BONE_JOINTS.get(a.get("look_at_bone"), BONE_JOINTS[BONE_GAME_PIVOT])
    )
    out["look_at_point"] = "root" if root else "joint"
    for k in (
        "look_at_height_m",
        "distance_m",
        "height_m",
        "angle_deg",
        "fov_deg",
        "time_multiplier",
    ):
        out[k] = a.get(k)
    out["placement"] = (
        "previous_position"
        if a.get("keep_previous_position")
        else "side_of_pair" if not a.get("angle_deg") else "angle"
    )
    if a.get("shake_time_s"):
        out["shake"] = {
            "time_s": a.get("shake_time_s"),
            "time_factor": a.get("shake_time_factor"),
            "size": a.get("shake_size"),
        }
    return out


_WEAPON_EVENTS = {
    EV_WEAPON_STEAL: "steal_from_partner",
    EV_PICK_UP_WEAPON: "pick_up",
    EV_DROP_WEAPON: "drop",
    EV_DROP_WEAPON_ANIM: "drop_with_animation",
}


def state_fx(rec, args, resolve=None):
    """The decoded `fx` section of one state record, or None when the state
    has no such event.  args: the map decorate_events() filled; resolve: Entity
    value -> effect key (for the extra effect of an IMPACT_EFFECTS event)."""
    fx = {}

    def add(key, item):
        fx.setdefault(key, []).append(item)

    for e in rec.get("events", []):
        eid, a = e.get("event_id"), args.get(id(e)) or {}
        if eid == EV_IMPACT_EFFECTS:
            add("impact_effects", _impact(e, a, resolve))
        elif eid == EV_CAMERA_CUT:
            add("camera_cuts", _cut(e, a))
        elif eid == EV_CAMERA_RETURN:
            add(
                "camera_return",
                dict(
                    _when(e),
                    transition_s=a.get("transition_s"),
                    set_in_vector=bool(a.get("set_in_vector")),
                ),
            )
        elif eid == EV_RUMBLE:
            add(
                "rumble",
                dict(
                    _when(e),
                    duration_s=a.get("duration_s"),
                    power=a.get("power"),
                    fade=bool(a.get("fade")),
                ),
            )
        elif eid == EV_LOOK_AT:
            add(
                "look_at",
                dict(
                    _when(e),
                    duration_s=a.get("time_s"),
                    fov_factor=a.get("fov_factor"),
                    target="self" if a.get("look_at_self") else "attack_target",
                    orbit_180=a.get("effect") == 1,
                ),
            )
        elif eid in _WEAPON_EVENTS:
            add("weapon_events", dict(_when(e), action=_WEAPON_EVENTS[eid], event=e.get("name")))
        elif eid == EV_UBER_RAGE:
            add(
                "effect_events",
                dict(
                    _when(e),
                    event=e.get("name"),
                    effect_ids=[12, 13],
                    effect_names=[EFFECTS[12], EFFECTS[13]],
                ),
            )
        elif eid == EV_DEPTH_OF_FIELD:
            add("depth_of_field", dict(_when(e), fade_s=a.get("fade_s")))
    if not fx:
        return None
    slow = slow_motion(fx.get("camera_cuts", []), fx.get("camera_return", []), "play_time_s")
    if slow:
        fx["slow_motion"] = slow
    return fx


def halfbell(n):
    """Blend weight of a camera transition at progress n = 0..1 (MathLib HalfBell
    0x779d40): 0.5 * (1 - cos(pi n)) * sin(pi n / 2)."""
    n = min(max(float(n), 0.0), 1.0)
    return 0.5 * (1.0 - math.cos(math.pi * n)) * math.sin(0.5 * math.pi * n)


def blend_real_s(transition_s, m0, m1, steps=2000):
    """Real seconds a VALID cut blend of `transition_s` game seconds takes while
    the world time multiplier goes from m0 (the previous shot's) to m1 (this
    cut's): T * integral over n = 0..1 of dn / lerp(m0, m1, halfbell(n)).

    The blend clock is game time (n += frame time / T, StateTransition 0x63312e,
    update 0x6337aa; the multiplier is lerped with the same weight), so this is
    the continuous limit; stepped per frame the multiplier lags one frame and the
    figure depends on the frame rate.  It applies ONLY when the blend is valid: a
    blend whose two horizontal view directions differ by more than 90 degrees is
    dropped (HasValidTransition 0x634f62) and the cut is hard, the multiplier
    m1 at once.  Validity needs the joint positions, so `real_s` of the table
    never includes it (real_s_basis "no_blend")."""
    T = float(transition_s or 0.0)
    if T <= 0.0:
        return 0.0
    m0, m1 = float(m0), float(m1)
    acc = 0.0
    for k in range(int(steps)):
        m = m0 + (m1 - m0) * halfbell((k + 0.5) / steps)
        if m <= 0.0:
            return None  # the world stands still: the blend never ends
        acc += 1.0 / m
    return T * acc / steps


def slow_motion(cuts, returns, key="time_s", end=None):
    """Intervals of the move's own clock during which a cut's world time
    multiplier is not 1: [{from_s, to_s, time_multiplier, real_s, real_s_basis,
    blend_s, blend_from_multiplier}].  A cut's multiplier holds until the next
    cut or the return to the character camera (Reset 0x62695d restores 1).
    real_s = (to - from) / multiplier counts the shot as a hard cut
    (real_s_basis "no_blend"): a cut with transition_s > 0 blends the
    multiplier from the previous shot's (blend_from_multiplier; 1.0 for the
    first cut and after a return) over blend_s game seconds when the blend is
    valid -- see blend_real_s().  end: the clock value at which the move ends
    (to_s of an open interval)."""
    marks = sorted(
        [
            (c.get(key), c.get("time_multiplier"), c.get("transition_s"))
            for c in cuts
            if c.get(key) is not None
        ]
        + [(r.get(key), None, None) for r in returns if r.get(key) is not None],
        key=lambda x: x[0],
    )
    out = []
    for i, (t, m, tr) in enumerate(marks):
        if m is None or m == 1.0 or not m:
            continue
        to = marks[i + 1][0] if i + 1 < len(marks) else end
        rec = {"from_s": t, "to_s": to, "time_multiplier": m}
        rec["real_s"] = None if to is None else round((to - t) / m, 4)
        rec["real_s_basis"] = "no_blend"
        rec["blend_s"] = tr
        rec["blend_from_multiplier"] = (marks[i - 1][1] if i else None) or 1.0
        out.append(rec)
    return out


# -------------------------------------------------------- cut camera placement
def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _norm_xz(v):
    n = math.hypot(v[0], v[2])
    return [v[0] / n, 0.0, v[2] / n] if n else [0.0, 0.0, 0.0]


def _side_position(actor, target, dist, height, side):
    """A side shot's position on side +1 / -1 of the pair's line (0x6341f7): the
    3-D midpoint of the two roots + distance * v + height, v = normalize((-l.z,
    0, l.x)).  The y term is actor.y + 0.5 * (target.y - actor.y) + height."""
    line = _sub(target, actor)
    v = _norm_xz([-line[2], 0.0, line[0]])
    return [
        actor[0] + 0.5 * line[0] + side * dist * v[0],
        actor[1] + 0.5 * line[1] + height,
        actor[2] + 0.5 * line[2] + side * dist * v[2],
    ]


def _first_side(actor, target, camera):
    """+1, or -1 when the perpendicular points away from the camera node."""
    if camera is None:
        return 1
    line = _sub(target, actor)
    v = _norm_xz([-line[2], 0.0, line[0]])
    c = _norm_xz(_sub(camera, actor))
    return -1 if v[0] * c[0] + v[2] * c[2] <= 0.0 else 1


def cut_camera(
    cut, actor, target, look_at_point=None, previous=None, camera=None, frame="mirrored"
):
    """Camera position and look-at point of one CAMERA_CUT at the moment of the
    cut.  The position then stays fixed in the world for the whole shot; only
    the aim is recomputed each frame from the look-at point (hold update
    0x633011).  `frame` says what the positions passed in and returned are in:
    "mirrored" (default) = engine coordinates, Y up, as in a GLB without a
    coordinate_frame key; "true" = the true-handed frame of the default export
    (x = -engine x).

    cut            a camera_cuts entry (state.fx or pair), or event_args()
    actor, target  root positions [x, y, z] of the acting character and of its
                   animation partner ("attack target") at the moment of the cut
    look_at_point  world position of the looked-at joint; needed unless the bone
                   is GAME_PIVOT (then: looked-at root + look_at_height_m)
    previous       the previous cut's position (a kept position reuses it)
    camera         current camera position (the character camera before the
                   first cut): decides the first side tried by a side shot
                   (None = the +perpendicular side) and is what a kept position
                   falls back to when there is no previous cut

    Read from SetValidStartPos 0x6341f7 (angle constants 180 / 360 / pi at
    0x9eaaf8 / 0xa00180 / 0x9e5dd0; MathLib.ToHeading 0x7800c0 = atan2(x, z),
    ToDirection 0x780210 = (sin h, 0, cos h)):
      kept         the previous cut's position; without one the camera's
                   current position.  No sweep, valid without a partner
      angle != 0   d = normalize_xz(target - actor); base = actor
                   looking at the attack target: d = -d; base = target
                   position = base + distance * dir(atan2(d.x, d.z) + angle)
                              + (0, height, 0)
                   if the sweep to it is blocked: the side rule (`fallback`)
      angle == 0   v = normalize((-l.z, 0, l.x)), l = target - actor (3-D);
                   v is flipped when it points away from the camera node;
                   position = actor + l / 2 + distance * v + (0, height, 0);
                   if the sweep to it is blocked, the other side
    A position is accepted when a sweep of width = height = 0.2 from the
    look-at point to it hits nothing: this function does no collision test.
    Returns {"position", "look_at", "side", "fallback"}: `side` is +1 / -1 for a
    side shot, else None; `fallback` is None except for an angled cut, where it
    is the two side positions [first tried, other side] the engine falls to
    when the angled position is blocked.  Raises ValueError for a kept position
    with neither `previous` nor `camera`."""
    if frame == "true":
        fl = lambda p: None if p is None else [-p[0] + 0.0, p[1], p[2]]
        r = cut_camera(
            cut, fl(actor), fl(target), fl(look_at_point), fl(previous), fl(camera), "mirrored"
        )
        return {
            "position": fl(r["position"]),
            "look_at": fl(r["look_at"]),
            "side": r["side"],
            "fallback": None if r["fallback"] is None else [fl(x) for x in r["fallback"]],
        }
    if frame != "mirrored":
        raise ValueError("frame must be 'true' or 'mirrored', not %r" % (frame,))
    a = cut
    dist = float(a.get("distance_m") or 0.0)
    height = float(a.get("height_m") or 0.0)
    angle = float(a.get("angle_deg") or 0.0)
    to_target = bool(a.get("look_at_attack_target")) or a.get("look_at") == "attack_target"
    keep = bool(a.get("keep_previous_position")) or a.get("placement") == "previous_position"
    looked = target if to_target else actor
    side, fallback = None, None
    if keep:
        # the previous cut's target position; the character camera's when there is none
        if previous is None and camera is None:
            raise ValueError("a kept position needs `previous` or `camera`")
        pos = list(previous if previous is not None else camera)
    elif angle != 0.0:
        d = _norm_xz(_sub(target, actor))
        base = actor
        if to_target:
            d, base = [-d[0], 0.0, -d[2]], target
        h = math.atan2(d[0], d[2]) + math.radians(angle)
        pos = [
            base[0] + dist * math.sin(h),
            base[1] + height,
            base[2] + dist * math.cos(h),
        ]
        first = _first_side(actor, target, camera)
        fallback = [
            [round(x, 5) for x in _side_position(actor, target, dist, height, sd)]
            for sd in (first, -first)
        ]
    else:
        side = _first_side(actor, target, camera)
        pos = _side_position(actor, target, dist, height, side)
    if a.get("look_at_bone") == BONE_GAME_PIVOT or look_at_point is None:
        look = [looked[0], looked[1] + float(a.get("look_at_height_m") or 0.0), looked[2]]
    else:
        look = list(look_at_point)
    return {
        "position": [round(x, 5) for x in pos],
        "look_at": look,
        "side": side,
        "fallback": fallback,
    }


_CUT_COORDINATES_TRUE = (
    "engine coordinates (left-handed), Y up: the formulas below are the engine's. "
    "Toolkit GLBs in the true frame (coordinate_frame 'right-handed-true', the default) "
    "have x = -engine x: negate x of the actor / target / camera positions before "
    "using the formulas and x of the resulting position after (fx_meta.cut_camera("
    "..., frame='true') does both); equivalently, in true-frame numbers h = "
    "atan2(d.x, d.z) - radians(angle_deg) and v = normalize((l.z, 0, -l.x)). Files "
    "without a coordinate_frame key hold engine numbers and use the formulas as written"
)


def cut_placement(frame=None, base=None):
    """The fx.camera.cut_placement block for files in `frame` (default
    frame.mode()): only the `coordinates` sentence depends on it."""
    import frame as _frame

    out = dict(base if base is not None else _CUT_PLACEMENT)
    out["coordinates"] = (
        _CUT_COORDINATES_TRUE if _frame.is_true(frame) else _CUT_PLACEMENT["coordinates"]
    )
    return out


# ------------------------------------------------------------------ tables
def _key(rel, nid):
    return "%s#%s" % (rel, nid)


def _f(v, n=4):
    return None if v is None else round(float(v), n)


def _vec(v, n=6):
    return [round(float(x), n) for x in v] if isinstance(v, (list, tuple)) else None


def _eid(v):
    return None if v is None else asm.s32(v)


def particle_facts(path):
    """What a .particle file says about how long it shows: the system's
    `duration` (emit window, seconds) and `loop`, and the longest
    `particleLife` of its types.  Property names as registered by
    ParticleSystemAsset 0x55da60 / ParticleType 0x55c1d2.  None when the file
    cannot be read."""
    try:
        import kapow_props

        with open(path, "rb") as fh:
            data = fh.read()
    except Exception:  # an unreadable asset must not take the table down
        return None
    out = {"emit_duration_s": None, "loop": None, "types": 0, "particle_life_s_max": None}
    lives = []
    try:  # the engine's grammar: both byte orders and the Part 1 PC / X360 record layout
        import particle_asset

        tree = particle_asset.parse(data)
    except Exception:
        tree = None
    if tree is not None:
        v = particle_asset.values(tree["system"])
        if isinstance(v.get("duration"), (int, float)):
            out["emit_duration_s"] = _f(v["duration"])
        if isinstance(v.get("loop"), bool):
            out["loop"] = v["loop"]
        for t in tree["types"]:
            out["types"] += 1
            life = particle_asset.values(t).get("particleLife")
            if isinstance(life, (int, float)):
                lives.append(float(life))
        if lives:
            out["particle_life_s_max"] = _f(max(lives))
        return out
    try:  # not a complete tree: the generic property-bag walk, as before
        doc = kapow_props.parse(data)
    except Exception:
        return None
    for b in doc.get("blocks", []):
        props = {}
        for r in b.get("props", []):
            if isinstance(r, dict) and "key" in r:
                props[str(r["key"]).lower()] = r.get("value")  # key case varies by reader
        cls = str(b.get("class") or "")
        if cls == "ParticleSystemAsset":
            if isinstance(props.get("duration"), (int, float)):
                out["emit_duration_s"] = _f(props["duration"])
            if isinstance(props.get("loop"), (bool, int)):
                out["loop"] = bool(props["loop"])
        elif cls == "ParticleType":
            out["types"] += 1
            if isinstance(props.get("particlelife"), (int, float)):
                lives.append(float(props["particlelife"]))
    if lives:
        out["particle_life_s_max"] = _f(max(lives))
    return out


class FxDB:
    """The effect side of one EXTRACT_OUT, on sound_meta's fragment database
    (same reference resolution, same keys)."""

    EFFECT_CLASSES = ("EffectBase", "EffectParticle", "EffectSound", "EffectSpeak")

    def __init__(self, extract_out, log=None, db=None):
        import sound_meta

        self.sm = sound_meta
        self.db = db or sound_meta.SoundDB(extract_out, log)
        self.out = extract_out
        self.log = log or (lambda *a: None)
        self._frags = None
        self._particles = {}
        self._effects = {}

    # -------------------------------------------------------------- files
    _TOKENS = (
        "EffectBase",
        "CharacterEffectDef",
        "WeaponBase",
        "GFXPackageCtrl",
        "CharacterDef",
        "CharacterCamera",
    )

    def fragments(self, tokens):
        """Fragments whose bytes name one of `tokens` (class names of _TOKENS);
        every fragment is read once."""
        if self._frags is None:
            self._frags = {t: [] for t in self._TOKENS}
            toks = [(t, t.encode()) for t in self._TOKENS]
            for path, rel in sorted(self.db.files().values(), key=lambda x: x[1]):
                try:
                    with open(path if os.path.exists(path) else path + ".json", "rb") as fh:
                        b = fh.read()
                except OSError:
                    continue
                for t, tb in toks:
                    if tb in b:
                        self._frags[t].append(rel)
        out = []
        for t in tokens:
            for rel in self._frags[t]:
                if rel not in out:
                    out.append(rel)
        return sorted(out)

    def asset_path(self, asset):
        """File of an asset path ('/Art/x.particle') under extracted/, any case."""
        if not isinstance(asset, str) or not asset:
            return None
        rel = asset.replace("\\", "/").lstrip("/")
        p = os.path.join(self.db.root, *rel.split("/"))
        if os.path.exists(p):
            return p
        cur = self.db.root
        for part in rel.split("/"):
            try:
                names = {n.lower(): n for n in os.listdir(cur)}
            except OSError:
                return None
            if part.lower() not in names:
                return None
            cur = os.path.join(cur, names[part.lower()])
        return cur

    def particle(self, asset):
        """Key of a particle asset in the `particles` table (its facts are
        read once), or None."""
        if not isinstance(asset, str) or not asset:
            return None
        k = asset.replace("\\", "/")
        if k not in self._particles:
            p = self.asset_path(k)
            facts = particle_facts(p) if p else None
            self._particles[k] = dict(facts or {}, file_found=bool(p))
        return k

    # ------------------------------------------------------------ effects
    def effect(self, rel, n):
        """Record of one EffectBase node (children fired by FireChildEffect
        0x715d73), keyed '<fragment>#<id>'."""
        k = _key(rel, n.id)
        if k in self._effects:
            return k
        rec = {
            "ref": [rel, n.id],
            "name": n.name or None,
            "effect_id": _eid(n.p("_ieffectid")),
            "particles": [],
            "sounds": [],
            "speaks": [],
            "children": [],
        }
        rec["effect_id_name"] = EFFECTS.get(rec["effect_id"])
        self._effects[k] = rec
        for c in n.children:
            pl = c.p("_iplacement")
            if c.cls == "EffectParticle":
                slot = self.db.resolve(c.p("_eparticle"), rel)
                asset = slot[1].p("definition") if slot else None
                rec["particles"].append(
                    {
                        "particle": self.particle(asset),
                        "slot": [slot[0], slot[1].id] if slot else None,
                        "placement": PLACEMENT.get(pl, pl),
                        "local_transform": bool(c.p("_tlocaltransform")),
                        "local_position": _vec(c.p("_vlocalposition")),
                        "local_orientation": _vec(c.p("_qlocalorient")),
                    }
                )
            elif c.cls == "EffectSound":
                d = self.db.resolve(c.p("_esounddef"), rel)
                rec["sounds"].append(
                    {
                        "definition": _key(d[0], d[1].id) if d else None,
                        "definition_name": (d[1].name or None) if d else None,
                        "placement": PLACEMENT.get(pl, pl),
                    }
                )
            elif c.cls == "EffectSpeak":
                sid = c.p("_ispeakid")
                rec["speaks"].append({"speak_id": sid, "speak": self.sm.SPEAK_ID.get(sid)})
            elif c.cls == "EffectBase":
                rec["children"].append(self.effect(rel, c))
        return k

    def effect_of(self, ref, home):
        """Effect key an Entity value points at, or None."""
        r = self.db.resolve(ref, home)
        if r and r[1].cls == "EffectBase":
            return self.effect(r[0], r[1])
        return None

    def effects(self):
        """({key: effect}, {effect id: key}, {key: effect definition})."""
        defs = {}
        for rel in self.fragments(["EffectBase", "CharacterEffectDef"]):
            for n in self.db.nodes(rel).values():
                if n.cls == "EffectBase" and (n.parent is None or n.parent.cls != "EffectBase"):
                    self.effect(rel, n)
                elif n.cls == "CharacterEffectDef":
                    defs[_key(rel, n.id)] = {
                        "ref": [rel, n.id],
                        "name": n.name or None,
                        "slots": {s: self.effect_of(n.p("_e" + s), rel) for s in DAMAGE_SLOTS},
                        "characters": [],
                    }
        by_id = {}
        for k, e in sorted(self._effects.items()):
            if e["effect_id"] is not None and e["effect_id"] >= 0:
                by_id.setdefault(e["effect_id"], k)
        by_id = {str(i): by_id[i] for i in sorted(by_id)}
        return self._effects, by_id, defs

    # ------------------------------------------------------------ weapons
    def weapons(self):
        out = []
        for rel in self.fragments(["WeaponBase"]):
            for n in self.db.nodes(rel).values():
                if n.cls != "WeaponBase":
                    continue
                models = n.p("modelNames") or []
                et, wt = _eid(n.p("m_ieffecttype")), _eid(n.p("m_iweapontype"))
                out.append(
                    {
                        "ref": [rel, n.id],
                        "collection": n.parent.name if n.parent is not None else None,
                        "model": models[0] if models else None,
                        "weapon_type": wt,
                        "weapon_type_name": WEAPON_TYPES.get(wt),
                        "effect_type": et,
                        "effect_type_name": WEAPON_EFFECT_TYPES.get(et),
                        "durability_loss_per_hit": _f(n.p("m_ndurebilitylossperhit")),
                        "disable_at_break": bool(n.p("m_tdisableatbreak")),
                        "break_effect": self.effect_of(n.p("_ebreakeffect"), rel),
                        "emitters": [
                            {
                                "particle": self.particle(c.p("particleSystemAsset")),
                                "auto_start": bool(c.p("autoStart")),
                                "local_position": _vec(c.p("localPos")),
                                "local_orientation": _vec(c.p("localOrient")),
                            }
                            for c in n.descend("EmitterNode")
                        ],
                    }
                )
        out.sort(key=lambda w: (w["collection"] or "", w["model"] or "", w["ref"][1]))
        return out

    # --------------------------------------------------------- GFX matrix
    def gfx_matrix(self):
        """The GFX half of the effect type x surface matrix (CollisionEffectCtrl
        0x6f9c74): {effect type id: {name, rows: [{surface, surface_id,
        particle, decal}]}}; only packages with at least one entry."""
        out, packages = {}, 0
        for rel in self.fragments(["GFXPackageCtrl"]):
            for n in self.db.nodes(rel).values():
                if n.cls != "GFXPackageCtrl":
                    continue
                packages += 1
                rows = []
                for e in n.kids("GFXEffectType"):
                    row = {
                        "surface": e.name or None,
                        "surface_id": _eid(e.p("m_ieffecttypes")),
                        "particle": None,
                        "decal": None,
                    }
                    for c in e.children:
                        if c.cls == "GFXParticleEffectType":
                            row["particle"] = self.particle(c.p("definition"))
                        elif c.cls == "GFXDecalEffectType":
                            row["decal"] = c.name or True
                    for key, prop in (
                        ("particle", "m_eeffectparticlereference"),
                        ("decal", "m_eeffectdecalreference"),
                    ):
                        r = self.db.resolve(e.p(prop), rel)
                        if r and row[key] is None:
                            row[key] = (
                                self.particle(r[1].p("definition"))
                                if key == "particle"
                                else (r[1].name or True)
                            )
                    rows.append(row)
                if rows:
                    out[str(_eid(n.p("m_ieffecttypes")))] = {
                        "ref": [rel, n.id],
                        "effect_type": _eid(n.p("m_ieffecttypes")),
                        "name": n.name or None,
                        "rows": rows,
                    }
        return out, packages

    # ---------------------------------------------------------- characters
    def _attachments(self, vis):
        """EmitterNode / LightFlash nodes of a CharVisual fragment, each with
        the BoneAttacher chain above it."""
        out = []
        for n in self.db.nodes(vis).values():
            if n.cls not in ("EmitterNode", "LightFlash"):
                continue
            chain, bone, q = [], None, n.parent
            while q is not None:
                link = {"class": q.cls, "name": q.name or None}
                if q.cls == "BoneAttacher":
                    link["attached_bone"] = q.p("attachedBone")
                    if bone is None:
                        bone = q.p("attachedBone")
                if q.cls != "Folder":
                    link["local_position"] = _vec(q.p("localPos"))
                    link["local_orientation"] = _vec(q.p("localOrient"))
                    models = q.p("modelNames")
                    if models:
                        link["model"] = models[0]
                chain.append(link)
                if q.cls == "BoneAttacher":
                    break
                q = q.parent
            rec = {
                "kind": "emitter" if n.cls == "EmitterNode" else "light_flash",
                "name": n.name or None,
                "ref": [vis, n.id],
                "bone_index": bone,
                "local_position": _vec(n.p("localPos")),
                "local_orientation": _vec(n.p("localOrient")),
                "parents": chain,
            }
            if n.cls == "EmitterNode":
                rec["particle"] = self.particle(n.p("particleSystemAsset"))
                rec["auto_start"] = bool(n.p("autoStart"))
            else:
                rec["light"] = {
                    "color_rgb": _vec(n.p("lightColorRGB")),
                    "brightness": _f(n.p("brightness", n.p("Brightness"))),
                    "range_m": _f(n.p("range")),
                    "light_type": n.p("lightType"),
                }
            out.append(rec)
        out.sort(key=lambda r: (r["kind"], r["bone_index"] if r["bone_index"] is not None else -1))
        return out

    def characters(self, defs):
        """{character fragment stem: {character type, effect definition,
        CharVisual fragment, attachments}}; fills defs[*]['characters']."""
        fam = ee.family("CHARACTER_TYPES")
        try:
            class_ids, visuals = self.sm._body_classes(self.db)
        except Exception as ex:  # no class fragments in this extract
            self.log("  fx_meta: body classes: %s" % ex)
            class_ids, visuals = {}, {}
        out = {}
        for rel in self.fragments(["CharacterDef"]):
            for n in self.db.nodes(rel).values():
                if n.cls != "CharacterDef" or n.p("m_icharactertype") is None:
                    continue
                ct = asm.s32(n.p("m_icharactertype"))
                mf = self.db.resolve(n.p("m_emodelfragment"), rel)
                vis = self.db.rel(mf[1].p("assetName")) if mf else None
                row = visuals.get((vis or "").lower()) or {}
                ed = self.db.resolve(n.p("m_echaractereffectdef"), rel)
                dk = _key(ed[0], ed[1].id) if ed and ed[1].cls == "CharacterEffectDef" else None
                name = os.path.basename(rel)[: -len(".fragment")]
                out[name] = {
                    "ref": [rel, n.id],
                    "name": n.name or None,
                    "character_type": ct,
                    "character_type_name": fam.get(ct),
                    "body_class": class_ids.get(row.get("body_class_id")),
                    "effect_def": dk,
                    "visual_fragment": vis,
                    "attachments": self._attachments(vis) if vis else [],
                }
                if dk in defs and name not in defs[dk]["characters"]:
                    defs[dk]["characters"].append(name)
        return dict(sorted(out.items()))

    # -------------------------------------------------------------- camera
    _RIG_CLASSES = (
        "CameraCtrl",
        "CharacterCamera",
        "CharacterCameraDef",
        "CharacterCameraStateManager",
        "CameraCombatSpecialCuts",
        "CameraPlayerVsPlayer",
        "CameraCinematic",
        "CameraModifierSinusShake",
        "CameraModifierHealthEffect",
        "CameraModifierRecoil",
        "VibrationMotorCtrl",
    )
    _RIG_SKIP = frozenset(
        "name logicalParent siblingOrder uniqueID UseRealTime recordInSavepoints runScript Open "
        "enabled Visible runFrameUpdate smartSelectable parentLink spatialTreeStrategy Locked "
        "UserType includeInAO includeInReflections castShadow localPos localOrient "
        # the same five as the executable registers them (key table from 1.4.0 on)
        "useRealtime open visible locked userType".split()
    )

    def _plain(self, n):
        out = {}
        for k, v in n.props.items():
            if k in self._RIG_SKIP or isinstance(v, dict) or "debug" in k.lower():
                continue
            if isinstance(v, float):
                v = round(v, 6)
            elif isinstance(v, (list, tuple)):
                v = _vec(v)
            out[k] = v
        return out

    def camera_rig(self):
        """Per player-control fragment: the camera nodes' own properties as
        stored (CharacterCamera.InitializeCameraProperties 0x655e27 reads
        them), and the character-camera state table."""
        out = {}
        for rel in self.fragments(["CharacterCamera"]):
            nodes = self.db.nodes(rel)
            if not any(n.cls == "CharacterCamera" for n in nodes.values()):
                continue
            rig = {
                "fragment": rel,
                "nodes": {},
                "states": [],
                "property_use": dict(_RIG_PROPERTY_USE),
                "transition_editor_visibility": dict(TRANSITION_EDITOR_VISIBILITY),
                "transition_editor_visibility_evidence": TRANSITION_EDITOR_VISIBILITY_EVIDENCE,
            }
            for n in nodes.values():
                if n.cls in self._RIG_CLASSES and n.cls not in rig["nodes"]:
                    rig["nodes"][n.cls] = self._plain(n)
                elif n.cls == "CharacterCameraDBItem":
                    it = self._plain(n)
                    cid = _eid(n.p("m_icharactercamid"))
                    it.update(name=n.name or None, camera=CAMERA_CHARACTER_DB.get(cid))
                    if cid in CAMERA_CHARACTER_DB_USE:
                        it["use"] = CAMERA_CHARACTER_DB_USE[cid]
                    it["transitions"] = []
                    for c in n.children:
                        if c.cls != "CameraCharacterTransition":
                            continue
                        tr = self._plain(c)
                        tid = _eid(c.p("m_icharactercamid"))
                        tr.update(name=c.name or None, to=CAMERA_CHARACTER_DB.get(tid))
                        it["transitions"].append(tr)
                    rig["states"].append(it)
            out[os.path.basename(rel)[: -len(".fragment")]] = rig
        return dict(sorted(out.items()))


#: CameraCharacterTransition: property -> the truth property the editor's property grid
#: shows it with
TRANSITION_EDITOR_VISIBILITY = {
    "m_npitchto": "m_tpitch",
    "m_nyawcharacterrelativebase": "m_tyawcharacterrelative",
    "m_nyawtwocharacterrelativebase": "m_tyawtwocharacterrelative",
    "m_nyawinsideobjectconehold": "m_tyawinsideobjectconehold",
}
TRANSITION_EDITOR_VISIBILITY_EVIDENCE = (
    "read from code: CameraCharacterTransition.FilterExposedProperties 0x62f298 (editor "
    "property grid; runtime gating not established)"
)


# evidence lines of the tables
_EV = {
    "event_editor_params": "read from AnimationEventWM.FilterExposedProperties 0x5c1767 "
    "(captions, groups, ranges the editor shows per event id; editor data, not game behaviour)",
    "effects": "data: EffectBase nodes and their EffectParticle / EffectSound / EffectSpeak "
    "children; fired by EffectBase.command_fire_effect 0x71bfb8 -> FireChildEffect 0x715d73 "
    "(read)",
    "effect_defs": "data: CharacterEffectDef nodes; which character uses which: "
    "CharacterDef.m_echaractereffectdef",
    "damage_rule": "read: CharacterEffectDef.command_play_damage_effect 0x6673d0, "
    "IsUpperDamagePose 0x7f077c",
    "weapons": "data: WeaponBase nodes (m_ieffecttype = WEAPON_EFFECT_TYPES)",
    "particles": "data: ParticleSystemAsset.duration / loop and ParticleType.particleLife as "
    "the toolkit's property-bag reader finds them; an emitter stops emitting at `duration` "
    "unless it loops (0x55b104, read)",
    "gfx_matrix": "data: GFXPackageCtrl / GFXEffectType nodes; lookup by "
    "command_get_particle_in_package_based_on_enum 0x6e10c9 (read)",
    "characters": "data: CharacterDef -> m_emodelfragment -> CharVisual fragment; EmitterNode "
    "/ LightFlash nodes under BoneAttacher nodes (attachedBone = joint index of the body "
    "skeleton, as the weapon attach of Bs2CharVisual uses it)",
    "camera.cut_placement": "read: command_set_cut_data 0x6325c5, SetValidStartPos 0x6341f7, "
    "GetLookAtPosition 0x634125, the hold update 0x633011, UpdateWorldOrient 0x626a15, "
    "StateTransition 0x63312e / 0x6337aa, HasValidTransition 0x634f62, MathLib.ToHeading "
    "0x7800c0 / ToDirection 0x780210 / HalfBell 0x779d40, CharacterVisual.SetupBoneMap "
    "0x67a31e, event cases 59 and 61 of 0x6a525e",
    "camera.rig": "data: node properties of the PlayerCtrl camera fragments",
    "camera.gameplay": "read: combat 0x64c330 / 0x64cee1, exploration 0x651632 / 0x651b3d, "
    "PvP 0x64748c; constants from exe bytes; not checked in game",
    "event_effects": "read: the event cases 29, 30, 31, 60, 69 of 0x6a525e "
    "(command_fire_effect_by_id)",
    "camera.modifiers": "read: constants at the call sites (addresses in the table)",
    "rumble": "read: VibrationMotorCtrl 0x8ab701 / 0x8a9645, event cases 56 and 82",
    "event_fields": "read: the event cases of CharacterRootLogic"
    ".command_animation_event_received 0x6a525e (lifted script); a field not listed for an "
    "id is not read by that id's case",
    "state.fx / pair.camera_cuts": "data (the event nodes) + the times anim_meta computes",
}

_CUT_PLACEMENT = {
    "evidence": "read",
    "coordinates": "engine coordinates, Y up; the export writes them verbatim (see "
    "conventions.handedness), so the same numbers place the camera in GLB space",
    "roots": 'actor = the character whose state carries the event; target ("attack '
    "target\") = the actor's ANIMATION PARTNER (the pair partner in a paired move), read "
    "once at the first cut of a cut session (command_set_cut_data 0x6325c5) and kept for "
    "the following cuts.  Positions are their root node world positions; heights are added "
    "to the root's Y.  The cut data calls them heights above ground (nHeightAboveGround, "
    "nLookAtHeightAboveGround).  A teleport puts the root at P, the capsule at P + 0.5 * "
    "height (2.0) and the visual node on the capsule (command_set_world_position_and_orient "
    "0x6b2af5), so the root is on the floor, 1.0 m under the visual frame -- in clip space "
    "the GamePivot track's x and z, on the floor.  That it is still there at the moment of "
    "a cut is inferred: how the root follows the capsule each frame is not established",
    "angle": "placement 'angle' (angle_deg != 0): d = normalize_xz(target - actor), base = "
    "actor; when the cut looks at the attack target d = -d and base = target; position = "
    "base + distance_m * (sin h, 0, cos h) + (0, height_m, 0) with h = atan2(d.x, d.z) + "
    "radians(angle_deg).  So angle 180 puts the camera behind the base character on the "
    "pair's line, a positive angle turns it from +Z towards +X.  When the sweep to that "
    "position is blocked the cut falls to the side_of_pair rule (cut_camera()'s `fallback`)",
    "side_of_pair": "placement 'side_of_pair' (angle_deg == 0): v = normalize((-l.z, 0, l.x)), "
    "l = target - actor, 3-D; v is flipped when it points away from the camera node's "
    "position (the camera test); position = actor + l / 2 + distance_m * v + (0, height_m, 0), "
    "so its y is the midpoint of the two roots' y + height_m; if the sweep fails the second "
    "try is the other side",
    "previous_position": "placement 'previous_position': the previous cut's target position "
    "is kept, only look-at / fov / time multiplier change; when there is no previous cut "
    "it is the character camera's position.  Valid without a partner and without a sweep",
    "look_at": "bone GAME_PIVOT (18): the looked-at character's ROOT node + (0, "
    "look_at_height_m, 0) (look_at_point 'root', look_at_joint null); any other "
    "bone: the world position of joint `look_at_joint` after the bone controllers "
    "(CharacterVisual.command_get_bone_worldpos_controlled; bone type -> joint name: "
    "bone_joints, CharacterVisual.SetupBoneMap 0x67a31e).  Orientation = look from position "
    "to that point with up +Y, no roll; fov_deg is the vertical field of view",
    "follow": "none: the position is fixed in the world for the whole shot; each frame only "
    "the aim is recomputed from the look-at point (hold update 0x633011; UpdateWorldPos "
    "0x633f28 is registered but has no caller on PC, X360 or PS3)",
    "validity": "the start position is tested with a sweep of width = height = 0.2 from the "
    "look-at point to the position, both characters' capsules ignored: a sphere of radius "
    "0.1 (capsule with zero segment, 0x50a8d3); a sweep longer than 25 m horizontally is "
    "scaled down to 25 m; result = t of the first hit not on an ignored node, -1 when "
    "none.  No partner means invalid (except a kept position).  An invalid TRANSITION does not reject the cut: it "
    "only makes it a hard cut.  On rejection while the cut camera is active it returns to "
    "the character camera with 0 s and ignores the following cuts of that animation; when "
    "it is not yet active the next cut of the move is tried again",
    "transition": "transition_s > 0 blends from the previous shot (StateTransition "
    "0x63312e, update 0x6337aa): n += frame time / transition_s, s = 0.5 * (1 - cos(pi n)) "
    "* sin(pi n / 2) (HalfBell 0x779d40); position lerp, orientation slerp, fov and time "
    "multiplier lerp with s.  The clock is the script `timepassed` global 0xe14304.  During "
    "the script update it holds the step chosen for the last natively updated node (0x495fec "
    "does not restore it).  No node of a second-list class has UseRealTime set in the Part 2 "
    "PC data (906 fragments + scene, 137 true), so it is the game step (scaled by the "
    "multiplier being blended).  The camera entity's own flag only decides whether its "
    "script runs while the game step is 0.  A cut-to-cut blend starts from the previous cut's stored position, orientation and "
    "multiplier, not from the values blended so far.  A blend is dropped (transition time "
    "set to 0 = hard cut) when the horizontal view directions of start and target differ by "
    "more than 90 degrees (HasValidTransition 0x634f62).  During a blend a 0.3-wide sweep "
    "from the look-at point pulls the camera in.  0 is a hard cut.  fx_meta.halfbell(n), "
    "fx_meta.blend_real_s(T, m0, m1)",
    "time_multiplier": "WorldLib.SetTimeMultiplier(value) while the shot is active; reset to "
    "1 when the cut camera closes (Reset 0x62695d)",
    "coop": "in co-op the player's viewport is kept (the split screen stays), fov = the "
    "camera's ncoopfov (75) and time multipliers other than 1 are ignored "
    "(WorldLib.SetTimeMultiplier 0x8a9d27).  Locking all players, the full screen and HUD "
    "off happen only for cuts on a state with no master_of in game mode 3: the 16 cuts of "
    "the four Countered_by_BS2_cattleprod slave states, which pair.camera_cuts carries with "
    "actor 'partner' and coop_full_screen true.  In single player those cuts play on the "
    "victim's own camera",
    "hard_cut_push_in": "the 0.3 sweep pull-in is written by StateTransition's hard block "
    "(T <= 0).  Cut-to-cut with a live previous target: shown for one frame, then the hold "
    "update restores the un-pushed position.  First cut of a sequence (previous target null, "
    "so DoContinue(3) 0x6269bc is false): the hold state is left every frame and the hard "
    "block runs every frame, so the pull-in stays applied; with T > 0 nothing writes the "
    "camera data after the blend and the output freezes at the last blended frame.  Read "
    "from code, not confirmed in game",
    "return": "CAMERA_CUT_TO_CHARACTER_CAM (camera_return) blends back to the character "
    "camera over its transition_s (m_nvalue); when the actor leaves the animation state "
    "without one the camera returns over 0.9 s (StateCombatCut 0x625aec, StateActive "
    "0x632c3d; 0.9 at 0x9e5ecc), and a running blend is aborted",
    "return_in_vector": {
        "basis": "actor -> partner (the lender, and negated, for a borrowed camera)",
        "pitch_y": -0.3,
        "yaw_rad": -0.8,
        "rule": "with set_in_vector the character camera's view direction is d = partner - "
        "actor flattened and normalised, y set to -0.3 and normalised again, then turned "
        "about Y so that atan2(x, z) decreases by 0.8 rad; the camera is placed at look-at - "
        "length * d",
    },
    "helper": "fx_meta.cut_camera(cut, actor, target, look_at_point, previous, camera)",
}

_MODIFIERS = {
    "damage_shake": {
        "time_s": 0.25,
        "size_rad": 0.02,
        "time_factor": 40.0,
        "source": "CameraCtrl.command_start_damage_modifiers 0x636059",
    },
    "kill": {
        "fov_factor": 0.85,
        "fov_time_s": 0.4,
        "shake": {"time_s": 0.5, "size_rad": 0.04, "time_factor": 30.0},
        "slow_motion_real_s": 0.4,
        "source": "CharacterRoot.command_give_damage 0x691b10",
    },
    "recoil": {
        "intensity": "fx_meta.recoil_intensity(pose): 0.5 light, 1.0 heavy, 2.1 knock-down, "
        "1.4 stun, 0.2 otherwise",
        "tilt_rad": "0.025 * intensity over 0.3 s",
        "fov_factor": "1 - 0.06 * intensity over 0.3 s",
        "min_interval_s": 0.1,
        "source": "CharacterRoot.command_do_recoil 0x6902c0, "
        "CameraCtrl.command_start_recoil_modifiers 0x63618d",
    },
    "cut_shake": {
        "rule": "rotation (rad) = sum over active shakes of dir * size * sin(time_factor * t) "
        "* (T - t) / T, t in real seconds (0xe14300); output quaternion (qz (x) qx) (x) qy, "
        "each built with angle -r / 2 (0x6466fd); dir = normalize((rand - 0.5) * 2 per axis) "
        "(CameraModifierSinusShake 0x643d95; T = shake.time_s)",
        "applied_by_cut_camera": False,
        "note": "set_cut_data 0x6325c5 activates the shared sinus shake; only the character "
        "camera reads it (CharacterCamera.ApplyModifiers 0x6457f3), so it shows only in a "
        "return blend that starts while it is running",
        "source": "CameraCombatSpecialCuts.command_set_cut_data 0x6325c5, "
        "CameraCtrl.StateActive 0x637f66 (applies no modifiers)",
    },
}

_RUMBLE = {
    "impact_effects": "fx_meta.impact_rumble(pose): poses 1-6, 23, 24 -> 0.2 s at 0.15; "
    "7-12, 19-22, 25, 26 -> 0.35 s at 0.2 fading; 13-18, 27, 28 -> 0.55 s at 0.2 fading; "
    "only when the acting character is a player and the partner confirms the hit",
    "rumble_event": "duration_s, power, fade as authored (event 82)",
    "damage_received": {"duration_s": 0.23, "power": "0.3 + 0.7 * (1 - health)"},
    "motors": "power <= 0.5: motor 0 off, motor 1 = 1.5 * power; above: both = power",
    "senders": [
        {
            "source": "command_force_counter_attack 0x6867b7",
            "to": "partner's PlayerCtrl",
            "duration_s": 1.0,
            "power": 0.4,
            "fade": True,
        },
        {
            "source": "command_dodge 0x686a17",
            "to": "partner's PlayerCtrl",
            "duration_s": 0.5,
            "power": 0.15,
            "fade": False,
        },
        {
            "source": "command_block 0x686e56",
            "to": "partner's PlayerCtrl",
            "duration_s": 0.5,
            "power": 0.15,
            "fade": False,
        },
        {
            "source": "CharacterPhysics.StateCharge 0x67d89e",
            "to": "charged target's PlayerCtrl",
            "duration_s": 0.5,
            "power": 0.15,
            "fade": False,
        },
        {
            "source": "event 31 DISCHARGE_ARMOR",
            "to": "own PlayerCtrl",
            "duration_s": 0.5,
            "power": 0.4,
            "fade": True,
        },
        {
            "source": "FireVolumeGeneral.active 0x737257",
            "to": "each player in the fire",
            "duration_s": 0.2,
            "power": 0.4,
            "fade": False,
        },
        {
            "source": "UnderbossPhase1 0x890013",
            "to": "player",
            "duration_s": 0.75,
            "power": "min(1, (10 - clamp(d, 3, 10)) * 0.15)",
            "fade": True,
        },
        {
            "source": "TriggerActionCharacter action 25 RUMBLE_CHARACTERS_CONTROLLER 0x85bb91",
            "to": "the character's PlayerCtrl",
            "duration_s": "m_nnumber1",
            "power": "m_nnumber2",
            "fade": "m_ttruth1",
        },
    ],
}

_NOT_ESTABLISHED = [
    "how the root node follows the capsule each frame (the cut's vertical reference)",
    "whether the first cut of a session blends (the test uses the cut camera's previous "
    "orientation)",
    "which weapon model a character holds in a given pair (pair.fx gives every weapon "
    "effect type its criteria allow)",
    "the damage pose a given IMPACT ends with: the conversions and their order (combo, "
    "direction, size, height) are read and exported as combat.rules.damage_pose; their inputs "
    "(where the attacker stands, the two body sizes and heights) exist only at run time, so "
    "the effect tables give the authored pose",
    "character attachments: the 0.0596 m by which Nite Owl's stored attacher positions lie "
    "below the GLB joints, and why the Twilight Lady weapon-chain attacher's position is not "
    "a rest snapshot of its bone",
    "gameplay cameras: nothing was checked in the running game",
]

# settled in the final sweep, kept as a statement (was a not-established item); exported
# as fx.fake_twilight_lady_weapon and, beside the rule it qualifies, as
# fx.damage_rule.twilight_lady_fake_weapon
_FAKE_WEAPON = (
    "g_efaketwilightladyweapon is null in shipped data: "
    "CharacterRoot.command_set_weapon 0x6943b8 sets it only when the type-0x23 definition "
    "has m_emodelcollbash1h, which is null on PC, PS3 and X360 (read from code; measured "
    "on all six sets); no weapon node has effect type TASER.  inferred: the TASER branch "
    "is therefore never taken for her (0x6673d0 was not re-read for a null weapon)"
)


def damage_rule():
    fam = ee.family("DAMAGE_POSE")
    by_pose = {}
    for pose in sorted(k for k in fam if k):
        by_pose[str(pose)] = {
            "name": fam[pose],
            "hit_position": HIT_POSITIONS[hit_position(pose)],
            "slots": {c: damage_slots(pose, c) for c in WEAPON_CASES},
            "impact_event_rumble": impact_rumble(pose),
            "recoil_intensity": recoil_intensity(pose),
        }
    return {
        "evidence": _EV["damage_rule"],
        "order": "pose 0: nothing.  inflictor in uber rage (m_ninrageuberdamagefactor > 1) -> "
        "uber; else killing hit -> kill; else a weapon -> its effect type (WOOD, STEEL, "
        "SHARP -> the one sharpweapon slot; TASER first fires effect id 1 "
        "ELECTRIC_ARMOR_DISCHARGE, then the STEEL slot); else fast / heavy by pose.  Then "
        "knockdown (poses 17, 18, 27, 28) or stun (19-22) is fired as well",
        "twilight_lady_fake_weapon": _FAKE_WEAPON,
        "impact_effects_event": "the IMPACT_EFFECTS case passes kill = false and the acting "
        "character's weapon (none when ignore_weapon); the definition is the TARGET's",
        "upper_poses": sorted(UPPER_POSES),
        "fast_poses": sorted(FAST_POSES),
        "knockdown_poses": sorted(KNOCKDOWN_POSES),
        "stun_poses": sorted(STUN_POSES),
        "weapon_effect_types": {str(k): v for k, v in WEAPON_EFFECT_TYPES.items()},
        "slot_entry": "a slot name of effect_defs[*].slots, or 'effect_id:<n>' = "
        "effects_by_id[n]",
        "by_pose": by_pose,
    }


def event_fields():
    out = {}
    for eid, (addr, fields) in sorted(EVENT_FIELDS.items()):
        out[str(eid)] = {
            "name": ee.name("ANIMATION_EVENT", eid),
            "handler": addr,
            "fields": {p: {"arg": a, "meaning": why} for p, (a, why) in fields.items()},
        }
    return out


def tables(extract_out, log=None, db=None):
    """The top-level `fx` block (no per-state data)."""
    fdb = db if isinstance(db, FxDB) else FxDB(extract_out, log, db)
    effects, by_id, defs = fdb.effects()
    chars = fdb.characters(defs)
    weapons = fdb.weapons()
    gfx, packages = fdb.gfx_matrix()
    rig = fdb.camera_rig()
    for d in defs.values():
        d["characters"].sort()
    return {
        "format": FORMAT,
        "evidence": _EV,
        "conventions": {
            "keys": "'<fragment path under extracted/>#<node id>', as in sound_meta.json: an "
            "effect's sounds[*].definition is a key of sound_meta `definitions`, an "
            "effect_defs key equals sound_meta `effects.damage_effect_sets` / "
            "`characters[*].damage_effects`",
            "times": "playpos / time_s / play_time_s are copied from the event record "
            "(conventions.playpos); pair entries are on the pair's shared clock, the master's",
            "placement": "ENTITY: the emitter or sound is attached to the node the effect is "
            "fired on, at local_position / local_orientation; POS_AND_ORIENT: created in the "
            "world at fire position + local_position, fire orientation * local_orientation "
            "(EffectParticle.Fire 0x7162f0)",
            "payload": "an event's `payload` holds its argument slots that are set, by "
            "property name; for an id listed in event_fields only the slots its handler reads "
            "(the other set slots are named in `payload_stale`: values left over from the "
            "node the event was copied from), for any other id every set slot",
        },
        "event_fields": event_fields(),
        "event_editor_params": EVENT_EDITOR_PARAMS,
        "effects": dict(sorted(effects.items())),
        "effects_by_id": by_id,
        "effect_ids": {str(k): v for k, v in sorted(EFFECTS.items())},
        "effect_defs": dict(sorted(defs.items())),
        "damage_rule": damage_rule(),
        "weapons": weapons,
        "particles": dict(sorted(fdb._particles.items())),
        "gfx_matrix": {
            "sound_meta": "the sound half of the same matrix (effect type x surface -> "
            "definition) is sound_meta.json `footsteps.rows`, keyed by the same effect type id",
            "packages": packages,
            "rows": gfx,
        },
        "characters": chars,
        "camera": {
            "cut_placement": _CUT_PLACEMENT,
            "bone_types": {str(k): v for k, v in CHARACTER_BONE_TYPE.items()},
            "bone_joints": {str(k): v for k, v in BONE_JOINTS.items()},
            "modifiers": dict(_MODIFIERS, evidence=_EV["camera.modifiers"]),
            "rig": rig,
            "gameplay": dict(_GAMEPLAY_CAMERAS, evidence=_EV["camera.gameplay"]),
        },
        "event_effects": {
            "evidence": _EV["event_effects"],
            "by_event": {
                str(k): dict(v, name=ee.name("ANIMATION_EVENT", k))
                for k, v in sorted(EVENT_EFFECTS.items())
            },
        },
        "fake_twilight_lady_weapon": _FAKE_WEAPON,
        "rumble": dict(_RUMBLE, evidence=_EV["rumble"]),
        "not_established": _NOT_ESTABLISHED,
    }


# ------------------------------------------------------------- gameplay cameras
# The three gameplay camera updates (character camera in combat and in exploration, and
# the shared PvP camera).  Read from code; constants from the executable's bytes; nothing
# of it was checked in the running game.
_GAMEPLAY_CAMERAS = {
    "combat": {
        "update": "0x64cee1",
        "clock": "physicsTimePassed + physicsRemainingTime - remainingLastFrame (avoid lift"
        " and output low-pass use global timepassed)",
        "lookat_drop_m": 1.0,
        "very_close_raise": 0.3,
        "pull_factor_max_add": 1.2,
        "pull_time_s": 0.1,
        "quarantine_stick": 0.1,
        "quarantine_note": "left clears on x <= 0.1 or move intensity > 0.01; right on"
        " x >= -0.1",
        "move_intensity_gate": 0.01,
        "collision_b_actual_gate": 0.01,
        "collision_b_move_gate": 0.1,
        "predict_lookahead_s": 0.8,
        "predict_side_gate": 0.3,
        "target_speed_gate": 0.2,
        "target_front_gate": 0.2,
        "target_front_rate_scale": 2.0,
        "target_front_max_scale": 0.25,
        "target_behind_rate_scale": 0.2,
        "predict_decay_scale": 1.5,
        "rate_factor": {
            "value": 2.0,
            "path_and_target_behind": "when the rate opposes the push",
            "target_front": "when the rate already has the sign of the push",
        },
        "force_rotate_power": 1.9,
        "override_yaw_rate": 8.0,
        "sweep_diameter_m": 0.3,
        "wall_normal_y_max": 0.7,
        "diminish_margin_m": 0.02,
        "force_diminish_time": "set 0.1, then min(t - dt, 0): active for one frame",
        "push_gain": 7.0,
        "push_time_s": 0.02,
        "squeeze_rate": 3.0,
        "fov_power": 1.5,
        "initial_blend_power": 1.5,
        "output_lowpass_s": 0.2,
        "output_lowpass": "out += (new - out) * avgDt / 0.2, not clamped; avgDt = lerp(avgDt,"
        " timepassed, m_ntimepassedhistory)",
        "initial_avg_dt": 0.033333,
        "reset_entry": "tReset: ninitialblendpos = 1, nfovtimer = 0; else 0 and 1",
        "apply_yaw": "x' = x cos d + z sin d; z' = -x sin d + z cos d; d = (rate + stick) * dt"
        " * rotateSpeed + forced",
        "dead": [
            "_ncollisionclipinfactor (overwritten with 1.0)",
            "nactualtiltpos (written, never read)",
        ],
        "formulas": [
            "entry: lookat = root + up * wantedLookatHeight; pos.y = lookat.y + wantedHeight -"
            " wantedLookatHeight; with tReset pos = root + up * (wantedHeight -"
            " wantedLookatHeight) - fwd * 0.5 * (maxDist + minDist), ninitialblendpos = 1,"
            " nfovtimer = 0; else ninitialblendpos = 0, nfovtimer = 1; curMinDist = minDist;"
            " fovFactor = camera.fov / defaultFov",
            "1 clock: dt = physicsTimePassed + physicsRemainingTime - remainingLastFrame",
            "2 stick: x = stick.x * invertedH, y = stick.y * invertedV; left quarantine clears"
            " when move intensity > 0.01 or x <= 0.1, right when move intensity > 0.01 or"
            " x >= -0.1; a right quarantine zeroes negative x, a left one positive x; while a"
            " pull timer runs x = +1 (right) / -1 (left); pullFactor = 1 + min(2 * pullTime,"
            " 1.2)",
            "3 minimum distance: forceDiminishTime <= 0: curMinDist = min(curMinDist +"
            " blendFromMinDist * dt, minDist); else curMinDist = lerp(curMinDist,"
            " wantedDiminish, min(blendToMinDist * dt, 1)); then forceDiminishTime ="
            " min(forceDiminishTime - dt, 0)",
            "4 close-in: veryClose = 1 + (minDist - curMinDist) / (minDist - collisionMinDist);"
            " raise = (veryClose - 1) * 0.3",
            "5 timed look-at and FOV: fovTimer falls by dt / T (T = fovBlendOutTime without an"
            " override, 0.5 * fovBlendInTime when the override is the player's own root, else"
            " fovBlendInTime); s = PowerSmooth(fovTimer, 1.5, 1); fovFactor = last * s + wanted"
            " * (1 - s)",
            "6 look-at: C = visual world position with y - 1.0; lookat = lerp(lookat, C + up *"
            " (wantedLookatHeight + raise), min(lookatSluggish * dt * veryClose^2, 1)); vin ="
            " lookat - pos",
            "7a path prediction: vsoon = C + up * (lookatH + raise) + 0.8 * velocity; when the"
            " ray pos -> vsoon hits, with l = velocity in camera space, normalised: l.x > 0.3:"
            " rate = min(rate + mod * f * dt, maxRate); l.x < -0.3: rate = max(rate - mod * f"
            " * dt, -maxRate); f = 2 when the rate opposes the push; predicting = 1 on any hit",
            "7b target bias (|velocity| > 0.2 and a target; d = target - root in camera space):"
            " d.z >= 0 and normalised d.z > 0.2: d.x < 0: rate = min(rate + 2 * mod * f * dt,"
            " 0.25 * maxRate), f = 2 when rate > 0; d.x >= 0: rate = max(rate - 2 * mod * f *"
            " dt, -0.25 * maxRate), f = 2 when rate < 0; d.z < 0: predicting = 1; d.x > 0: rate"
            " = min(rate + 0.2 * mod * f * dt, maxRate); d.x < 0: rate = max(rate - 0.2 * mod"
            " * f * dt, -maxRate), f = 2 when the rate opposes the push",
            "7c decay: without predicting the rate moves toward 0 by 1.5 * mod * dt",
            "7d forced rotation: timer = max(timer - dt / time, 0); a = PowerSmooth(1 - timer,"
            " 1.9, 1); forced = angle * (a - a_prev)",
            "7e avoid-character lift: per overlapping body lift += timepassed * floorLiftScale"
            " / perpendicular distance to the view line; then lift = max(lift - 0.5 *"
            " floorLiftScale * timepassed, 0); while latched vin.y = startHeight - lift",
            "7f stick smoothing: actualRotate = lerp(actualRotate, x, min(c * dt * pullFactor,"
            " 1)), c = rotateAccel when the input pushes the value further from 0, else"
            " rotateDecel",
            "7g apply: vin turns about Y by d = (rate + actualRotate) * dt * rotateSpeed +"
            " forced; with another override entity vin slerps to the flat direction to it by"
            " min(8 * dt * pullFactor, 1)",
            "8 height: vin.y += dt * y * tiltSpeed (raw stick); vin.y = clamp(vin.y,"
            " -maxHeight, wantedLookatHeight + raise - max(lift, minimumFloorLift)); pos ="
            " lookat - vin",
            "9 distance band (n = horizontal |vin|, m = flat direction pos -> C + up *"
            " wantedHeight): n > maxDist: pos += m * (n - maxDist) * dt * catchUpSluggish;"
            " n < curMinDist: pos -= m * (curMinDist - n) * min(getAwaySluggish * dt *"
            " veryClose, 1)",
            "10 collision A: sphere sweep (diameter 0.3) lookat -> pos; on a hit hitpos ="
            " lookat - t * (lookat - pos); nearer than curMinDist: hitpos +="
            " ProjectVector(-(curMinDist - t * len) * dir, normal) and, when normal.y < 0.7,"
            " wantedDiminish = t * len + 0.02 (below collisionMinDist: push the character back"
            " by flat normal * min((collisionMinDist - wanted) * 7, 1) for 0.02 s and use"
            " collisionMinDist), forceDiminishTime = 0.1",
            "11 collision B (inside an A hit): sweep pos -> lookat; on a hit facing the camera"
            " the direction shrinks by (1 - 3 * dt) (not below curMinDist) and, by the side of"
            " the normal, the stick is quarantined and the camera pulled 0.1 s to the other"
            " side; after an A hit pos = hitpos outright",
            "12 orientation: in = normalize(lookat - pos), right = normalize(up x in), up' ="
            " in x right",
            "13 initial blend: ninitialblendpos += dt / initialBlendInTime (to 1); pose blends"
            " from the entry pose by PowerSmooth(., 1.5, 1)",
            "14 output low-pass: avg = lerp(avg, timepassed, m_ntimepassedhistory); out +="
            " (new - out) * avg / 0.2 (position; the orientation slerps by the same factor)",
            "15 FOV and final clamp: fov = defaultFov * fovFactor; a last sweep (diameter 0.3)"
            " lookat -> output pulls the output position to the hit point; then the modifiers",
        ],
    },
    "exploration": {
        "update": "0x651b3d",
        "clock": "global timepassed",
        "look_dir": "normalize(sin yaw, -tan pitch, cos yaw)",
        "offset_x": "actual_distance * clamp(lookAtOffsetX / distance, -1, 1)",
        "min_distance_m": 0.1,
        "stick_gate": 0.01,
        "state_stick_gate": 0.1,
        "stick_states": {
            "IDLE": "move < 0.1",
            "WALK": "0.1 < move < 0.6 (exactly 0.1: no change)",
            "RUN": "move >= 0.6",
            "OVER_SHOULDER": "held while move < 0.1 and pitch <= m_novershoulderoutpitch",
        },
        "speed_ramp": "symmetric_halfbell(n) = 0.5 * (1 - cos(pi n)); accel: speed = pref *"
        " shb; decel: speed = start * (1 - shb); speed is frozen after the accel ramp until"
        " |pref| <= 0.01",
        "cone_hold": "transition with m_tyawinsideobjectconehold: a = wrap(m_nyawto - yaw); if"
        " a and speed have opposite signs, speed *= clamp(1 - |a| /"
        " |m_nyawinsideobjectconehold|, 0, 1)",
        "fall_in": {
            "step_s": 0.01,
            "speed_gate_mps": 1.0,
            "rule": "if |v| > 1 and dot(camFwdFlat, vFlat) > m_nfallinstart: per step c = c *"
            " conv + m * (1 - conv); yaw = heading(c)",
        },
        "catch_up": "f = t^2 / m_ndistanceoutcatchuppower; lerp to state distance, snap when"
        " f > 1",
        "catch_up_gate": {"dist_m": 0.2, "heading_rad": 0.5},
        "convolution_snap": 0.001,
        "offset_x_check_factor": 1.1,
        "transition": "v -= signed(v, to) * halfbell(p), applied to the current value each"
        " frame; pitch / yaw / fov / pitch limits stop at p = 1, offsets and distance keep"
        " updating; control input is skipped while a transition that disallows user input is"
        " running",
        "buttons": {"0x22": 16, "0x23": 17, "0x12": 26},
        "collision": {
            "order": ["LineChecks", "CapsuleCheck", "OffsetXCheck"],
            "min_distance_m": 0.1,
            "capsule_lead_m": 0.5,
            "offset_x_factor": 1.1,
            "handlers": "0x65436e, 0x654196, 0x653883, 0x653b26, 0x644cc6",
        },
    },
    "pvp": {
        "update": "0x64748c",
        "margin_m": 2.0,
        "min_distance_m": 2.0,
        "max_distance_m": 999.0,
        "hfov": "radians(fov) * width / height",
        "smoothing": "none; _nsmoothing has no reader",
        "focus_class": "PlayerVsPlayerFocusPoint",
        "formula": [
            "center = R + 0.5 (N - R)",
            "closest = N if |cam - N|^2 < |cam - R|^2 else R",
            "n = normalize(pivot - center)",
            "lookat = center + up * _nlookatheight",
            "ponline = center + n * dot(closest - center, n)",
            "D = clamp((|closest - ponline| + 2) / tan(hfov / 2) + |ponline - center|, 2, 999)",
            "pos = lookat - n D + up D tan(_nlookatpitch)",
        ],
    },
    "helpers": "fx_meta.power_smooth, symmetric_halfbell, pvp_camera, exploration_camera",
}

# what the character camera's state manager picks a state for (ReceiveButtonInputs
# 0x654c5f, PickStateStickBased 0x64bb35)
CAMERA_CHARACTER_DB_USE = {
    16: "button 0x22: centre behind",
    17: "button 0x23: look at partner",
    26: "button 0x12: look at next waypoint",
    1: "move stick >= 0.6",
    9: "move stick 0.1..0.6",
    3: "move stick < 0.1",
}

_RIG_PROPERTY_USE = {
    "CameraPlayerVsPlayer._nsmoothing": "not read by the update",
    "CameraPlayerVsPlayer._tdummy01": "editor button only",
    "CharacterCamera._ncollisionclipinfactor": "copied to the mode struct, overwritten with"
    " 1.0 in combat, not read in exploration",
}

# effect ids the animation event cases fire themselves (command_fire_effect_by_id)
EVENT_EFFECTS = {
    29: {"effect_ids": [8]},
    30: {"effect_ids": [], "note": "ElectricArmor.command_electric_armor_charge fires id 0"},
    31: {"effect_ids": []},
    60: {
        "effect_ids": [12, 13],
        "note": "12 is fired (command_fire_effect_by_id), 13 is started"
        " (EffectCtrl.command_start_effect_by_id 0xcaf719fe)",
    },
    69: {
        "effect_ids": [1, 10],
        "note": "both at root position + visual-space (0, 0.4, 0.4); needs an attack target"
        " and the ElectricArmor entity",
    },
}


def power_smooth(v, power, init_power=1.0):
    """MathLib.PowerSmooth(v, power, initPower) 0x77ab7b: an S-curve on 0..1."""
    v = min(max(float(v), 0.0), 1.0)
    m = v**init_power
    if m > 0.5:
        return 1.0 - 0.5 * (2.0 - 2.0 * m) ** power
    return 0.5 * (2.0 * m) ** power


def symmetric_halfbell(n):
    """MathLib.SymmetricHalfBell 0x597620: 0.5 * (1 - cos(pi n)), n clamped to 0..1."""
    n = min(max(float(n), 0.0), 1.0)
    return 0.5 * (1.0 - math.cos(math.pi * n))


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0.0 else [0.0, 0.0, 0.0]


def _flip_x(p):
    return None if p is None else [-p[0] + 0.0, p[1], p[2]]


def pvp_camera(r, n, pivot, cam, fov_deg, lookat_h, pitch, aspect, frame="mirrored"):
    """The shared player-vs-player camera (CameraPlayerVsPlayer.UpdateCamera 0x64748c).

    r, n: world positions of Rorschach and Nite Owl; pivot: the level's
    PlayerVsPlayerFocusPoint node; cam: the camera's current position (decides which
    hero is "closest"); fov_deg, lookat_h, pitch: the camera node's _nfov,
    _nlookatheight and _nlookatpitch (radians); aspect: screen width / height.
    `frame` as in cut_camera(): "mirrored" = engine coordinates, "true" = x negated.
    Returns {"position", "look_at", "distance"}.  No smoothing exists in the game."""
    if frame == "true":
        out = pvp_camera(
            _flip_x(r), _flip_x(n), _flip_x(pivot), _flip_x(cam), fov_deg, lookat_h, pitch, aspect
        )
        out["position"], out["look_at"] = _flip_x(out["position"]), _flip_x(out["look_at"])
        return out
    if frame != "mirrored":
        raise ValueError("frame must be 'true' or 'mirrored', not %r" % (frame,))
    d2 = lambda a, b: sum((a[i] - b[i]) ** 2 for i in range(3))
    closest = n if d2(cam, n) < d2(cam, r) else r
    center = [r[i] + 0.5 * (n[i] - r[i]) for i in range(3)]
    nv = _unit(_sub(pivot, center))
    look = [center[0], center[1] + lookat_h, center[2]]
    k = sum((closest[i] - center[i]) * nv[i] for i in range(3))
    ponline = [center[i] + nv[i] * k for i in range(3)]
    hfov = math.radians(fov_deg) * aspect
    dist = (math.sqrt(d2(closest, ponline)) + 2.0) / math.tan(0.5 * hfov) + math.sqrt(
        d2(ponline, center)
    )
    dist = min(max(dist, 2.0), 999.0)
    up = dist * math.tan(pitch)
    pos = [look[0] - nv[0] * dist, look[1] - nv[1] * dist + up, look[2] - nv[2] * dist]
    return {"position": pos, "look_at": look, "distance": dist}


def exploration_camera(root, yaw, pitch, actual_dist, off_x, off_y, state_dist, frame="mirrored"):
    """Pose of the exploration (orbit) camera from its state, without collision and
    without the avoid-character height (GetLookDir 0x645c80, GetActualOffSetX 0x645e00,
    GetLookatWorldpos 0x6556d7).

    root: the character root position; yaw, pitch: the state's angles (radians; positive
    pitch puts the camera above the look-at); actual_dist: _nactualdistance; off_x,
    off_y: the state's nLookAtOffsetX / nLookAtOffsetY; state_dist: the state's nDistance.
    `frame` as in cut_camera().  Returns {"position", "look_at", "look_dir"}."""
    if frame == "true":
        out = exploration_camera(
            _flip_x(root), yaw, pitch, actual_dist, off_x, off_y, state_dist, "mirrored"
        )
        return {k: _flip_x(v) for k, v in out.items()}
    if frame != "mirrored":
        raise ValueError("frame must be 'true' or 'mirrored', not %r" % (frame,))
    look_dir = _unit([math.sin(yaw), -math.tan(pitch), math.cos(yaw)])
    # right = normalize(up x lookdir), flattened and renormalised
    right = _unit([look_dir[2], 0.0, -look_dir[0]])
    ratio = min(max(off_x / state_dist, -1.0), 1.0) if state_dist else 0.0
    ox = actual_dist * ratio
    look = [root[0] - right[0] * ox, root[1] + off_y, root[2] - right[2] * ox]
    pos = [look[i] - look_dir[i] * actual_dist for i in range(3)]
    return {"position": pos, "look_at": look, "look_dir": look_dir}


# ------------------------------------------------------------------- pairs
_ARMED_CASES = ("wood", "steel", "sharp")


def _weapon_cases(own, ignore_weapon):
    """Dispatch cases (keys of damage_rule.by_pose[pose].slots) a pair's weapon
    criteria allow for the acting side.  own: the WEAPON_ANIMATION_TYPE names
    the state accepts (pair.weapons *_own), None = no weapon criterion."""
    if ignore_weapon:
        return ["unarmed", "uber"]
    cases = []
    names = list(own) if own else ["UNARMED", "BASH_1H", "BASH_2H"]
    if "UNARMED" in names:
        cases.append("unarmed")
    if any(n != "UNARMED" for n in names):
        cases += list(_ARMED_CASES)
    return cases + ["uber"]


def resolve_slots(fx, effect_def, pose, case="unarmed"):
    """Effect keys (fx.effects) a damage pose fires on a victim that uses
    `effect_def` (a key of fx.effect_defs), in firing order."""
    d = (fx.get("effect_defs") or {}).get(effect_def) or {}
    out = []
    for s in damage_slots(pose, case):
        if s.startswith("effect_id:"):
            out.append((fx.get("effects_by_id") or {}).get(s.split(":", 1)[1]))
        else:
            out.append((d.get("slots") or {}).get(s))
    return out


def _on_clock(am, e, rate, start, own):
    """An event record on a pair's clock through anim_meta._pair_event (the
    slave-locked partner rule); None = it never fires in the pair."""
    return am._pair_event([e], e.get("event_id"), rate, start, own)


def pair_fx(am, pair, mrec, prec, args):
    """Add camera_cuts / camera_return / shots / fx to one pair record.

    Clock: seconds since both states were entered = the master's play time
    (pair.timeline); playpos = the shared play position.  Master events fire as
    on the master's own state; partner events as on a slave-locked partner
    (anim_meta._pair_event).  args: the decorate_events() map of both records.
    camera_cuts are the master's; a pair whose master state has none and whose
    partner state has (actor "partner", coop_full_screen true) carries the
    partner's, timed as partner events.
    An impact's victim is the other actor: its effect definition is
    fx.class_effect_defs[that actor's class], the effects
    resolve_slots(fx, definition, damage_pose, case) for each case of
    weapon_cases[actor] (only 'unarmed' / 'uber' when ignore_weapon)."""
    tl = pair.get("timeline") or {}
    rate, s0 = tl.get("playpos_per_second"), float(tl.get("start_playpos") or 0.0)
    own = float((tl.get("partner") or {}).get("start_playpos") or 0.0)
    end = None if not rate else round((1.0 - s0) / rate, 4)

    def clock(e, master):
        ref = _on_clock(am, e, rate, s0, s0 if master else own)
        return None if ref is None else {"time_s": ref["time_s"], "playpos": ref["playpos"]}

    def items(rec, key, master):
        out = []
        evs = [e for e in rec.get("events", []) if e.get("event_id") in key]
        for e in evs:
            c = clock(e, master)
            if c is not None and c["time_s"] is not None:
                out.append((e, c))
        out.sort(key=lambda x: x[1]["time_s"])
        return out

    # the cuts are the master's; when the master's state has none and the partner's
    # has (a move whose camera belongs to the victim: m_imasterof == 0, the only case
    # where co-op gets the lock / full screen / HUD off, 0x6a525e case 59), the partner's
    src, by_master = mrec, True
    if not items(mrec, (EV_CAMERA_CUT,), True) and items(prec, (EV_CAMERA_CUT,), False):
        src, by_master = prec, False
    cuts = []
    for e, c in items(src, (EV_CAMERA_CUT,), by_master):
        cut = _cut(e, args.get(id(e)) or {})
        for k in ("playpos", "time_s", "play_time_s", "fires_first_pass"):
            cut.pop(k, None)
        cuts.append(dict(c, clip_time_s=e.get("time_s"), **cut))
        if not by_master:
            cuts[-1].update(actor="partner", coop_full_screen=True)
    rets = [
        dict(
            c,
            clip_time_s=e.get("time_s"),
            transition_s=(args.get(id(e)) or {}).get("transition_s"),
            set_in_vector=bool((args.get(id(e)) or {}).get("set_in_vector")),
        )
        for e, c in items(src, (EV_CAMERA_RETURN,), by_master)
    ]
    if not by_master:
        for r in rets:
            r["actor"] = "partner"
    pair["camera_cuts"] = cuts
    pair["camera_return"] = rets[0] if rets else None
    # shot list: each cut holds until the next cut / the return / the end
    marks = [c["time_s"] for c in cuts[1:]]
    shots = []
    for i, c in enumerate(cuts):
        to = marks[i] if i < len(marks) else (rets[0]["time_s"] if rets else end)
        if rets and to is not None and rets[0]["time_s"] < to and rets[0]["time_s"] >= c["time_s"]:
            to = rets[0]["time_s"]
        m = c.get("time_multiplier") or 1.0
        shots.append(
            {
                "cut": i,
                "from_s": c["time_s"],
                "to_s": to,
                "time_multiplier": c.get("time_multiplier"),
                "real_s": None if to is None else round((to - c["time_s"]) / m, 4),
                # real_s takes the cut as hard.  With a valid blend of T s the shot lasts
                # blend_real_s(T, m0, m1) + (duration - T) / m1 instead (slow_motion)
                "real_s_basis": "no_blend",
                "blend_s": c.get("transition_s"),
                "blend_from_multiplier": (cuts[i - 1].get("time_multiplier") if i else None) or 1.0,
                "ends_with": (
                    "cut"
                    if i < len(marks) and to == marks[i]
                    else "return" if rets and to == rets[0]["time_s"] else "state_end"
                ),
            }
        )
    out = {"end_s": end, "shots": shots}
    slow = slow_motion(cuts, rets, "time_s", end)
    if slow:
        out["slow_motion"] = slow
    weapons = pair.get("weapons") or {}
    impacts, cases = [], {}
    for role, rec, own_w in (
        ("master", mrec, weapons.get("master_own")),
        ("partner", prec, weapons.get("partner_own")),
    ):
        for e, c in items(rec, (EV_IMPACT_EFFECTS,), role == "master"):
            a = args.get(id(e)) or {}
            imp = dict(c, actor=role, damage_pose=a.get("damage_pose") or 0)
            if a.get("ignore_weapon"):
                imp["ignore_weapon"] = True
            cases[role] = _weapon_cases(own_w, False)
            for x in (rec.get("fx") or {}).get("impact_effects", []):
                if x.get("playpos") == e.get("playpos") and x.get("extra_effect"):
                    imp["extra_effect"] = x["extra_effect"]
            impacts.append(imp)
    impacts.sort(key=lambda x: x["time_s"])
    if impacts:
        out["impact_effects"] = impacts
        out["weapon_cases"] = cases
    for key, ids in (("rumble", (EV_RUMBLE,)), ("weapon_events", tuple(_WEAPON_EVENTS))):
        rows = []
        for role, rec in (("master", mrec), ("partner", prec)):
            for e, c in items(rec, ids, role == "master"):
                a = args.get(id(e)) or {}
                row = dict(c, actor=role)
                if key == "rumble":
                    row.update(
                        duration_s=a.get("duration_s"),
                        power=a.get("power"),
                        fade=bool(a.get("fade")),
                    )
                else:
                    row.update(action=_WEAPON_EVENTS[e["event_id"]], event=e.get("name"))
                rows.append(row)
        if rows:
            rows.sort(key=lambda x: x["time_s"])
            out[key] = rows
    pair["fx"] = out
    return pair


# ------------------------------------------------------------ anim_meta hook
def counts(meta):
    """Event / state / pair counts of the fx data in an anim_meta dict."""
    import collections

    ev, fxs, states = collections.Counter(), collections.Counter(), 0
    for c in meta.get("classes", {}).values():
        for s in c.get("states", []):
            for e in s.get("events", []):
                ev[e.get("name")] += 1
            if s.get("fx"):
                states += 1
                for k, v in s["fx"].items():
                    fxs[k] += len(v)
    pairs = meta.get("pairs", [])
    return {
        "states_with_fx": states,
        "fx_entries": dict(sorted(fxs.items())),
        "events_decoded": sum(fxs[k] for k in fxs if k != "slow_motion"),
        "camera_cut_events": ev.get("CAMERA_CUT", 0),
        "camera_return_events": ev.get("CAMERA_CUT_TO_CHARACTER_CAM", 0),
        "impact_effects_events": ev.get("IMPACT_EFFECTS", 0),
        "rumble_events": ev.get("RUMBLE", 0),
        "look_at_events": ev.get("LOOK_AT_TARGET", 0),
        "pairs": len(pairs),
        "pairs_with_cuts": sum(1 for p in pairs if p.get("camera_cuts")),
        "primary_pairs_with_cuts": sum(
            1 for p in pairs if p.get("camera_cuts") and p.get("primary")
        ),
        "pair_cuts": sum(len(p.get("camera_cuts") or []) for p in pairs),
    }


def attach(meta, extract_out, classes, states, pairs, am, log=None):
    """The anim_meta hook: decorate every state's events, add state `fx`,
    pair camera cuts and the top-level `fx` block.  Only ADDS keys.

    meta     the anim_meta dict being built
    classes  anim_meta.load_classes(); states: {class: [(state node, record)]}
    am       the anim_meta module (for its pair-event timing)"""
    log = log or (lambda *a: None)
    try:
        return _attach(meta, extract_out, classes, states, pairs, am, log)
    except Exception as ex:  # optional decoration: never take the animation table down
        log("  fx_meta: skipped (%s: %s)" % (type(ex).__name__, ex))
        return meta


def _attach(meta, extract_out, classes, states, pairs, am, log):
    try:
        fdb = FxDB(extract_out, log)
        fx = tables(extract_out, log, fdb)
    except Exception as ex:  # no effect fragments: per-state data still goes in
        log("  fx_meta: tables: %s" % ex)
        fdb, fx = None, {"format": FORMAT, "error": str(ex)}
    root = fdb.db.root if fdb else None
    index, args = {}, {}
    for cn, lst in states.items():
        home = None
        if root:
            try:
                home = os.path.relpath(classes[cn]["fragment"], root).replace(os.sep, "/")
            except (KeyError, ValueError):
                home = None

        def resolve(ref, home=home):
            return fdb.effect_of(ref, home) if fdb else None

        for node, rec in lst:
            decorate_events(node, rec, args)
            sfx = state_fx(rec, args, resolve)
            if sfx:
                rec["fx"] = sfx
            index.setdefault((cn, rec["path"], rec["name"]), []).append(rec)
    if fdb:  # effects first reached through an event's extra effect
        fx["effects"] = dict(sorted(fdb._effects.items()))
        fx["particles"] = dict(sorted(fdb._particles.items()))
    class_defs = {}
    for _name, c in sorted((fx.get("characters") or {}).items()):
        bc = c.get("body_class")
        if bc and c.get("effect_def"):
            class_defs.setdefault(bc, c["effect_def"])
    fx["class_effect_defs"] = dict(sorted(class_defs.items()))

    def pick(cls, path, name, clip, master_of=None):
        # a path can name several states (a fragment spliced twice): take the one
        # with the pair's clip (and master id)
        cands = index.get((cls, path, name)) or []
        best = [r for r in cands if r.get("main_clip") == clip] or cands
        if master_of is not None:
            best = [r for r in best if r.get("master_of") == master_of] or best
        return best[0] if best else None

    for p in pairs:
        mrec = pick(
            p["master_class"], p["master_path"], p["master_state"], p["master_clip"], p["master_of"]
        )
        prec = pick(p["partner_class"], p["partner_path"], p["partner_state"], p["partner_clip"])
        if mrec is None or prec is None:
            continue
        pair_fx(am, p, mrec, prec, args)
    meta["fx_format"] = FORMAT
    meta["fx"] = fx
    fx["counts"] = counts(meta)
    log(
        "  fx_meta: %d effects, %d states with fx, %d camera cuts on %d pairs"
        % (
            len(fx.get("effects", {})),
            fx["counts"]["states_with_fx"],
            fx["counts"]["pair_cuts"],
            fx["counts"]["pairs_with_cuts"],
        )
    )
    return meta


# ------------------------------------------------------- character export
_CHAR_ALIASES = {"Rorschach": "Rorchach", "NiteOwl": "NightOwl", "NiteOwl_Dry": "NightOwl"}
_ATT_CACHE = {}


def character_attachments(extract_out, cname, bone_names=None, meta=None):
    """The emitters and light flashes the game hangs on a character's bones,
    for asset.extras.watchmen of its GLBs: {"fx_attachments": {...}} or {}.

    cname: the character's fragment stem (export folder name).  bone_names:
    the body skeleton's joint names in bind order -- adds `bone` to each entry
    (attachedBone is an index into that order).  meta: an anim_meta dict that
    carries the `fx` block (its tables are used instead of reading the
    fragments again)."""
    key = os.path.abspath(extract_out)
    top = (meta or {}).get("fx") or {}
    if top.get("characters") is not None:
        _ATT_CACHE[key] = (top["characters"], top.get("particles") or {})
    if key not in _ATT_CACHE:
        try:
            fdb = FxDB(extract_out)
            chars = fdb.characters({})
            parts = dict(fdb._particles)
        except Exception:
            chars, parts = {}, {}
        _ATT_CACHE[key] = (chars, parts)
    chars, parts = _ATT_CACHE[key]
    c = chars.get(cname) or chars.get(_CHAR_ALIASES.get(cname, ""))
    if not c or not c.get("attachments"):
        return {}
    rows = []
    for a in c["attachments"]:
        row = {k: v for k, v in a.items() if k != "ref"}
        i = a.get("bone_index")
        if bone_names is not None and isinstance(i, int) and 0 <= i < len(bone_names):
            row["bone"] = str(bone_names[i])
        if a.get("particle"):
            row["particle_facts"] = parts.get(a["particle"])
        rows.append(row)
    return {
        "fx_attachments": {
            "format": FORMAT,
            "visual_fragment": c.get("visual_fragment"),
            "evidence": _EV["characters"],
            "space": _attachment_space(),
            "attachments": rows,
        }
    }


_ATTACHMENT_SPACE = (
    "local_position / local_orientation (xyzw) as stored: relative to the "
    "parent listed first in `parents`, up to the BoneAttacher, which sits on joint "
    "`bone_index` of the body skeleton with its own local offset.  In a true-frame GLB an "
    "engine local (p, q) is translation (-p.x, p.y, p.z), rotation (-q.x, q.y, q.z, q.w) "
    "(measured).  A BoneAttacher's stored transform is a rest snapshot of its bone (rotation "
    "equal to the GLB joint within 0.2 degrees on 14 / 14; position equal on Rorschach, "
    "0.0596 m lower in y on Nite Owl, unrelated on the Twilight Lady weapon chain) and is "
    "replaced by the bone at run time (inferred)"
)


def _attachment_space():
    import frame as _frame

    if not _frame.is_true():
        return _ATTACHMENT_SPACE
    return _ATTACHMENT_SPACE + ". These are " + _frame.ENGINE_NOTE


def with_attachments(extras, extract_out, cname, bone_names=None, meta=None):
    """`extras` (a dict or None) plus character_attachments(); None when both
    are empty.  For characters_export's asset_extras argument."""
    try:
        att = character_attachments(extract_out, cname, bone_names, meta)
    except Exception:  # the attachment table is optional: never fail an export
        att = {}
    if not att:
        return extras
    out = dict(extras or {})
    out.update(att)
    return out


# ---------------------------------------------------------------------- CLI
def build(extract_out, anim=None, log=None):
    """A stand-alone fx table: the top-level block plus, when an anim_meta dict
    (or its path) is given, its per-state and per-pair fx data by reference."""
    if isinstance(anim, str):
        with open(anim, encoding="utf-8") as fh:
            anim = json.load(fh)
    if anim and anim.get("fx"):
        out = dict(anim["fx"])
    else:
        out = tables(extract_out, log)
    if anim:
        out["states"] = {
            cn: [
                {
                    "name": s["name"],
                    "path": s["path"],
                    "main_clip": s.get("main_clip"),
                    "fx": s["fx"],
                }
                for s in c.get("states", [])
                if s.get("fx")
            ]
            for cn, c in anim.get("classes", {}).items()
        }
        out["pairs"] = [
            {
                "pair": i,
                "master_class": p["master_class"],
                "master_state": p["master_state"],
                "master_clip": p["master_clip"],
                "partner_class": p["partner_class"],
                "partner_state": p["partner_state"],
                "partner_clip": p["partner_clip"],
                "primary": p.get("primary"),
                "camera_cuts": p.get("camera_cuts"),
                "camera_return": p.get("camera_return"),
                "fx": p.get("fx"),
            }
            for i, p in enumerate(anim.get("pairs", []))
            if p.get("camera_cuts") or (p.get("fx") or {}).get("impact_effects")
        ]
    cam = out.get("camera")
    if isinstance(cam, dict) and isinstance(cam.get("cut_placement"), dict):
        cam = out["camera"] = dict(cam)
        cam["cut_placement"] = cut_placement(None, cam["cut_placement"])
    import canonical_names

    # strings that name a file of the export: spelled as that file is written
    return canonical_names.respell_export(out, extract_out)


def write(extract_out, out_json, anim=None, log=print):
    import extract_out as _xo

    _xo.require(extract_out)  # a mistyped folder is an error, not an empty table
    meta = build(extract_out, anim, log)
    with open(out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1)
    return meta


def summary(meta):
    return "%d effects, %d effect definitions, %d weapons, %d particles, %d characters" % (
        len(meta.get("effects", {})),
        len(meta.get("effect_defs", {})),
        len(meta.get("weapons", [])),
        len(meta.get("particles", {})),
        len(meta.get("characters", {})),
    )


def main(argv):
    if len(argv) < 3 or argv[1] in ("-h", "--help"):
        print("usage: fx_meta.py EXTRACT_OUT OUT.json [ANIM_META.json]")
        return 0 if len(argv) > 1 else 2
    meta = write(argv[1], argv[2], argv[3] if len(argv) > 3 else None)
    print("wrote %s: %s" % (argv[2], summary(meta)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
