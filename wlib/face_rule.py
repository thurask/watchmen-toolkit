#!/usr/bin/env python3
"""face_rule.py -- which face pose the game shows during which body animation.

The head of a character is a second Character entity with its own
AnimationCtrlWM (CharacterHeadCtrl 0x671099).  Its animation class (the
`AnimationClass*Face` fragments) is NOT driven by body states: the body side
feeds it four inputs (CharacterVisual.command_update_animation 0x69b988 and the
hit / speak commands), and the face class turns them into one-frame poses with
timed exits.  This module

* reads the face classes and the CharVisual fragments (which face class a body
  class's head runs),
* derives, for every body state, the inputs the game generates while it plays
  (attack flag, hits, death, speech) and the face track that follows, by running
  the face class in anim_state_machine.Interpreter,
* does the same for both sides of a pair on the pair's shared clock,
* turns a track into pose keys for the GLB writer (variant_glb).

Engine sources (KapowMultiDEDRM.exe):
  update_animation 0x69c728 CHARACTER_MODE, 0x69c764 NORMAL_ATTACK, 0x69c7d7 STOP_SPEAK
  command_hit_soon 0x6903ea / command_give_damage 0x691b10  HITTAKEN + DAMAGE_POSE
  IMPACT_EFFECTS 0x6ab6a6 (pose = event enum), DO_CHOKE_EFFECT 0x6a7512 (pose 16)
  IMPACT in a non-attack state 0x6ac9dd: damage record pose 0; DIE 0x6ac4e1 and
  KILL_ANIMATION_PARTNER 0x6ac5f6: pose 0, damage 100000
  start_speak 0x69b7a1 / stop_speak 0x69b806
  CharacterHeadCtrl.command_activate 0x669496 (attachment), HeadCharacterUpdate 0x66a2a5
"""

import math
import os
import random
import sys
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

import anim_state_machine as asm
import kapow_json as _kj
import engine_enums as ee

FACE_FORMAT = "watchmen-face/2"  # 2: speech categories, fixed-wave talk segments, talk_clips

# CONTROL_ACTION_TYPES / ANIMATION_ENUM ids the head controller receives
A_NORMAL_ATTACK, A_HITTAKEN, A_START_SPEAK, A_STOP_SPEAK = 1, 2, 31, 32
E_CHARACTER_MODE, E_DAMAGE_POSE = 1, 4
MODE_NONCOMBAT, MODE_COMBAT, MODE_DEAD = 0, 1, 2
# ANIMATION_EVENT ids that reach a face controller
EV_IMPACT, EV_SOUND, EV_PRE_IMPACT, EV_KILL_PARTNER = 4, 9, 16, 20
EV_DISCHARGE, EV_BULLMOVE, EV_SPEAK, EV_THROW_BRANCH = 31, 33, 37, 38
EV_IMPACT_EFFECTS, EV_DIE, EV_CHOKE = 56, 85, 93
CHOKE_POSE = 16  # KNOCKDOWN_MIDDLE_LEFT, the constant at 0x6a7512

DT = 1.0 / 30.0  # simulation step; the engine reacts in the frame an input arrives
IDLE, TALK, HIT_BY_POSE = "IDLE", "TALK", "HIT_BY_POSE"

DRIVERS = {
    "CHARACTER_MODE": {
        "kind": "enum",
        "id": E_CHARACTER_MODE,
        "sent": "to the head in every frame in which the body controller updated, the "
        "character moves or it is being pushed (_nbeingpushedtime > 0)",
        "values": "NONCOMBAT, COMBAT, STUNNED, PRONE while alive; DEAD from CharacterRoot.StateDead",
        "rule": "COMBAT (1) when (in combat, or a weapon is held, or m_tforcecombat) and "
        "(playable, or player-controlled, or m_istateofmind != 0); 'in combat' is "
        "CombatOrchestrator.command_is_in_combat when the body controller updated or the "
        "character moves, otherwise 'the mode is already non-zero'; COMBAT also for "
        "non-playable types 8-11 without a player controller; STUNNED (3) while the stun "
        "timer runs; DEAD (2) in StateDead",
        "evidence": "read: update_animation 0x69c728-0x69c74f; CharacterRoot.StateActive "
        "0x6b367a (lifted CharacterRoot.c 7495-7506, 8191-8228, 9287); StateDead 0x6bb12a "
        "passes 2",
    },
    "NORMAL_ATTACK": {
        "kind": "action",
        "id": A_NORMAL_ATTACK,
        "sent": 'every frame while the body\'s current state has "Attack state" set '
        "(or CharacterRoot.is_attacking 0x693249)",
        "lifetime": "one controller update",
        "evidence": "read: update_animation 0x69c764-0x69c7c3",
    },
    "HITTAKEN": {
        "kind": "action + enum DAMAGE_POSE",
        "id": A_HITTAKEN,
        "enum_id": E_DAMAGE_POSE,
        "sent": "once per hit: command_hit_soon (attacker PRE_IMPACT), command_give_damage "
        "(IMPACT, DIE, KILL_ANIMATION_PARTNER), the attacker's IMPACT_EFFECTS, own "
        "DO_CHOKE_EFFECT",
        "lifetime": "one controller update; the enum keeps its value: DAMAGE_POSE on the "
        "head is never cleared (initial value 0; it is written only by hits, never with 0), "
        "so a criterion on it stays met until the next hit",
        "evidence": "read: 0x6906be, 0x6929e9, 0x6ab6a6-0x6ab7d9, 0x6a7512; all 39 "
        "SetAnimationEnum call sites of the lifted scripts",
    },
    "START_SPEAK": {
        "kind": "action",
        "id": A_START_SPEAK,
        "sent": "when a voice line starts: own SOUND event with its speak flag (0x6aba76), "
        "SpeakCtrl when a category-1 line starts (0x83d936; category 0 lines and category "
        "2 grunts and shouts send nothing), trigger sounds on the character (0x853e88)",
        "evidence": "read: CharacterVisual.command_start_speak 0x69b7a1",
    },
    "STOP_SPEAK": {
        "kind": "action",
        "id": A_STOP_SPEAK,
        "sent": "every frame in which no voice has the character root as pivot (speech, "
        "trigger sounds, footsteps on a surface that has a footstep sound); by SpeakCtrl the "
        "first frame its line no longer plays (0x83dbe4)",
        "evidence": "read: update_animation 0x69c7d7-0x69c843; command_stop_speak 0x69b806",
    },
}

ATTACHMENT = {
    "head_entity": 'a second Character (node "HeadModel") with its own AnimationCtrlWM; '
    "CharacterHeadCtrl owns both",
    "attach_bone": "Spine2",
    "head_model_yaw_deg": 90.0,
    "driven_bones": [
        {"head_bone": "Head", "body_bone": "Head"},
        {"head_bone": "Neck", "body_bone": "Neck"},
    ],
    "nite_owl_extra": [
        {"head_bone": "L Clavicle", "body_bone": "L Clavicle"},
        {"head_bone": "R Clavicle", "body_bone": "R Clavicle"},
        {"head_bone": "LUpArmTwist", "body_bone": "LUpArmTwist"},
        {"head_bone": "RUpArmTwist", "body_bone": "RUpArmTwist"},
    ],
    "rule": "the head model is placed at the body's world transform turned 90 degrees about "
    "+Y and attached at the body's Spine2; every frame its Head and Neck bones are "
    "overwritten with the body's Head and Neck bone transforms, the bones below Head "
    "keep the face controller's pose",
    "glb": "f_anchor follows the body Head joint; f_<bone> children carry the face pose",
    "copy_space": "bone-local: UpdateHeadBone reads the body bone's controlled LOCAL position "
    "and orientation (Character::GetBoneControlledLocalOrient 0x4b05de and its position twin "
    "0x4b05b3) and writes them with Character::SetBoneLocalPosAndOrient 0x4ba7ad",
    "evidence": "read: command_activate 0x669496 (Spine2 0x669713, yaw constant 0xa0f240 = "
    "pi/4 half-angle), HeadCharacterUpdate 0x66a2a5 / UpdateHeadBone 0x663ea5",
}

NOT_ESTABLISHED = [
    "which voice line plays: the voice is drawn per character and the wave per play, and a "
    "line can be suppressed (quarantine), so only a SOUND event with the speak flag and ONE "
    "fixed wave gives a talk segment with an end (`talk_s`).  The length of a talk is that "
    "of the wave played (pitch 1.0 and no random pitch on any speak wave), plus the line's "
    "start_delay_s; lines requested by the AI are listed in `talk_clips` with their length "
    "per voice.  A Nite Owl hit pose (NTO_FACE has no timed exit) ends when no voice has "
    "the character root as pivot any more -- the grunt, whose wave is likewise drawn at "
    "random: such segments stay sound-dependent",
    "CHARACTER_MODE of a body state whose criteria do not fix it: the mode is game state "
    "(drivers.CHARACTER_MODE.rule, read: COMBAT when (in combat, or a weapon is held, or "
    "m_tforcecombat) and (playable, or player-controlled, or m_istateofmind != 0)), not a "
    "property of the state, so `character_mode.basis` says 'assumed' there; it matters to "
    "the face of attack states only",
    "the runtime modifiers of an attack state's damage pose in SetCloseCombatDamageToTarget "
    "0x6ae57f: ComboManipulateDamage 0x675ce6 (the running combo entry's type 2 -> stun, 3 -> "
    "light-to-heavy), SizeManipulateDamagePose 0x7fca72 and HeightManipulateDamagePose "
    "0x7fcaee (the two characters' height difference) -- game state; `inflicts` gives the "
    "state's own Damage Pose",
    "whether the attacker is behind the victim when IMPACT_EFFECTS fires (victim-local z below "
    "-0.2 m, 0x802ae8): each such hit carries `damage_pose_if_behind` / `face_state_if_behind`, "
    "and `behind_changes_face` says whether it would matter; the track uses the pose as "
    "authored",
]


# ----------------------------------------------------------------- fragments
def _fragroot(extract_out):
    return os.path.join(extract_out, "extracted")


def find_face_fragments(extract_out):
    """{face class name: path} for every AnimationClass*Face fragment."""
    hits = set()
    for ext in (".fragment", ".fragment.json"):
        for f in _kj.glob_tree(
            _fragroot(extract_out), "CharacterAnimation", "AnimationClass*" + ext
        ):
            hits.add(f[: -len(".json")] if f.endswith(".json") else f)
    out = {}
    for f in sorted(hits):
        nm = os.path.basename(f)[len("AnimationClass") : -len(".fragment")]
        if nm.lower().endswith("face"):
            out[nm] = f
    return out


def charvisual_table(extract_out):
    """[{fragment, visual, body_class_id, face_class_id}] from the *CharVisual
    fragments: the body controller is the AnimationCtrlWM under the
    CharacterVisual node, the face controller the one under the "HeadModel"
    character (CharacterHeadCtrl.Init 0x664a11 finds both by name)."""
    hits = set()
    for ext in (".fragment", ".fragment.json"):
        for f in _kj.glob_tree(_fragroot(extract_out), "CharacterVisual", "*CharVisual*" + ext):
            hits.add(f[: -len(".json")] if f.endswith(".json") else f)
    rows = []
    for f in sorted(hits):
        try:
            roots = asm.load_tree(f, False)
        except (OSError, ValueError, KeyError):
            continue
        body = face = visual = None
        for n in asm.walk(roots):
            if n.cls != "AnimationCtrlWM" or n.parent is None:
                continue
            cid = asm.s32(n.p("m_ianimationclassid", 0) or 0)
            if n.parent.cls == "CharacterVisual":
                body, visual = cid, n.parent.name
            elif (n.parent.name or "").lower() == "headmodel":
                face = cid
        if body is not None:
            rows.append(
                {
                    "fragment": os.path.relpath(f, extract_out).replace(os.sep, "/"),
                    "visual": visual,
                    "body_class_id": body,
                    "face_class_id": face,
                }
            )
    return rows


def load_face_class(path):
    roots = asm.load_tree(path, True)
    return asm.find_class_root(roots), list(asm.walk(roots))


def _clip_name(slot):
    t = slot.p("targetAnimation") or slot.name or ""
    return os.path.splitext(t.replace("\\", "/").rsplit("/", 1)[-1])[0].strip()


def _clip_dir(slot):
    t = (slot.p("targetAnimation") or "").replace("\\", "/").strip("/")
    parts = t.split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else ""


def state_clips(state):
    return [_clip_name(s) for b in state.descend(asm.CLS_BLEND) for s in b.kids(asm.CLS_SLOT)]


CLIP_MIX_EVIDENCE = (
    "read: command_evaluate_blends 0x59e905 (a blend without a control parameter hands its "
    "weight to its first child only), SetAllSlotBlends 0x5b4ef7 (every other slot gets "
    "weight 0), mixer 0x596532 (a source below 1e-5 is skipped), Node insert 0x48f556 (the "
    "child list is in siblingOrder), AnimBlendSource 0x594b36 (a new source starts at 0)"
)


def clip_mix(state):
    """How the slots of a state with several clips are mixed, or None for a
    single clip / a blend driven by a control parameter.  The clips are in
    sibling order (asm.load_tree sorts the children), so the first one is the
    engine's first child."""
    blends = [b for b in state.descend(asm.CLS_BLEND) if b.kids(asm.CLS_SLOT)]
    slots = [x for b in blends for x in b.kids(asm.CLS_SLOT)]
    if len(slots) < 2 or len(blends) != 1 or blends[0].p("m_iblendctrlparam"):
        return None
    w = asm.Interpreter._slot_pos_weights(None, blends[0], slots)
    return {
        "rule": "first_child_only",
        "shown": next(_clip_name(x) for i, x in enumerate(slots) if w[i] > 0.0),
        "weights": [w[i] for i in range(len(slots))],
        "evidence": CLIP_MIX_EVIDENCE,
    }


def _group_path(node):
    out, n = [], node
    while n is not None:
        if n.cls in (asm.CLS_GROUP, asm.CLS_STATE, asm.CLS_CLASS):
            out.append(n.name)
        n = n.parent
    return "/".join(reversed(out))


def _kind(state):
    """IDLE / TALK for the states of the idle and talk groups (the groups that
    are left by PLAY_TIME transitions back into themselves and re-rolled at
    random), else the state's own name."""
    g = asm._parent_group(state)
    if g is None or not g.p(asm.RANDOM_STATE, False):
        return state.name
    nm = (g.name or "").lower()
    if nm.startswith("idle"):
        return IDLE
    if nm.startswith("talk"):
        return TALK
    return state.name


# ---------------------------------------------------------------- simulation
def simulate(root, play_time, attack=False, mode=MODE_NONCOMBAT, inputs=(), seed=7, dt=DT):
    """Face states of the class `root` over `play_time` seconds.

    inputs: [(t, "HIT", pose id) | (t, "START_SPEAK", 0) | (t, "STOP_SPEAK", 0) |
    (t, "DEAD", 0)].  STOP_SPEAK = the line's sound has ended.
    attack: NORMAL_ATTACK is fired every frame.  A silent character gets
    STOP_SPEAK every frame (0x69c7d7), a talking one none.
    -> [{from_s, to_s, face_state, clips?, ease_in_s?}], idle / talk states merged
    into IDLE / TALK; to_s of the last segment is None."""
    it = asm.Interpreter(root, seed=seed)
    it.env.enums[E_CHARACTER_MODE] = mode
    it.env.enums[E_DAMAGE_POSE] = 0
    d = it._ref(root, "m_edefaultanimstate")
    if d is not None and d.cls == asm.CLS_STATE:
        it.transit(d, None)
    else:
        it.start(d)
    if it.page is None:
        return []
    ins = sorted(inputs, key=lambda x: x[0])
    k, talking, segs, cur = 0, False, [], None
    n = max(1, int(math.ceil(play_time / dt - 1e-6)))
    for f in range(n + 1):
        t = f * dt
        it.env.actions = set()
        while k < len(ins) and ins[k][0] <= t + 1e-6:
            _t, kind, pose = ins[k]
            k += 1
            if kind == "HIT":
                it.env.actions.add(A_HITTAKEN)
                it.env.enums[E_DAMAGE_POSE] = pose or 0
            elif kind == "START_SPEAK":
                it.env.actions.add(A_START_SPEAK)
                talking = True
            elif kind == "STOP_SPEAK":
                talking = False
            elif kind == "DEAD":
                it.env.enums[E_CHARACTER_MODE] = MODE_DEAD
        if attack and it.env.enums[E_CHARACTER_MODE] != MODE_DEAD:
            it.env.actions.add(A_NORMAL_ATTACK)
        if not talking:
            it.env.actions.add(A_STOP_SPEAK)
        it.env.force_update = True  # FireAnimationAction sets ctrl +0x2c (0x5aa83f)
        it.tick(dt)
        st = it.page.state
        lb = _kind(st)
        if cur is None or cur["face_state"] != lb:
            if cur is not None:
                cur["to_s"] = round(t, 3)
            cur = {"from_s": round(t, 3), "to_s": None, "face_state": lb}
            if lb not in (IDLE, TALK):
                cur["clips"] = state_clips(st)
                cur["ease_in_s"] = round(float(st.p("m_neaseinduration", 0.0) or 0.0), 3)
            segs.append(cur)
    return segs


# ------------------------------------------------------------- class records
def face_class_record(name, path, extract_out, am):
    """JSON-able description of one face class.  am: the anim_meta module
    (record builders; passed in to avoid a circular import)."""
    root, nodes = load_face_class(path)
    byid = asm.node_index(None, nodes)
    states, groups, dirs, mixes = [], [], set(), {}
    for n in nodes:
        if n.cls == asm.CLS_GROUP:
            groups.append(
                {
                    "path": _group_path(n),
                    "criteria": [am._crit_text(k) for k in am._crit_nodes(n)],
                    "choose_random_state": bool(n.p(asm.RANDOM_STATE, False)),
                }
            )
        elif n.cls == asm.CLS_STATE:
            slots = [s for b in n.descend(asm.CLS_BLEND) for s in b.kids(asm.CLS_SLOT)]
            dirs.update(_clip_dir(s) for s in slots)
            crit = am._crit_nodes(n)
            mixes[len(states)] = clip_mix(n)
            states.append(
                {
                    "name": n.name,
                    "path": _group_path(n),
                    "kind": _kind(n),
                    "clips": [_clip_name(s) for s in slots],
                    "ease_in_s": float(n.p("m_neaseinduration", 0.0) or 0.0),
                    "allow_more_than_once": bool(n.p("m_tallowmultipleinstances", False)),
                    "criteria": [am._crit_text(k) for k in crit],
                    "criteria_tree": [am.criteria_record(k) for k in crit],
                }
            )
    dirs.discard("")
    clip_dir = sorted(dirs)[0] if dirs else ""
    fam = clip_dir.split("/")[1] if clip_dir.count("/") >= 2 else ""
    for k, s in enumerate(states):
        # the animation names variant_glb gives the pose clips of this directory
        s["glb_animation_names"] = ["FACE %s/%s" % (fam, c) for c in s["clips"]]
        if mixes.get(k):
            s["clip_mix"] = mixes[k]
    d = asm.resolve_ref(root, root.p("m_edefaultanimstate"), byid)
    hit, then = {}, {}
    for pid, pn in sorted(ee.family("DAMAGE_POSE").items()):
        segs = simulate(root, 0.5, inputs=((0.1, "HIT", pid),))
        hs = [x for x in segs if x["face_state"] not in (IDLE, TALK)]
        hit[pn] = hs[0]["face_state"] if hs else None
        if len(hs) > 1:  # the hit state is left for another state before its hold ends
            then[pn] = {
                "face_state": hs[1]["face_state"],
                "clips": hs[1].get("clips"),
                "after_s": round(hs[1]["from_s"] - hs[0]["from_s"], 3),
                "basis": HIT_THEN_BASIS,
            }
    rec = {
        "class_id": asm.s32(root.p("m_iclassid", 0) or 0),
        "engine_name": ee.name("CHARACTER_ANIMATIONS", asm.s32(root.p("m_iclassid", 0) or 0)),
        "fragment": os.path.relpath(path, extract_out).replace(os.sep, "/"),
        "clip_dir": clip_dir,
        "pose_family": fam,
        "default_state": _group_path(d) if d is not None else None,
        "groups": groups,
        "states": states,
        "transitions": am._transitions(nodes),
        "hit_pose_to_state": hit,
        "hit_pose_then": then,
        "idle_cycle": _cycle(nodes, IDLE),
        "talk_cycle": _cycle(nodes, TALK),
        "hit_hold_s": _hit_hold(nodes),
    }
    rec["idle_cycle"]["rule"] = (
        "free-running, not tied to the body clip: the idle group is ENTERED at a uniformly "
        "random member (every entry goes through command_get_valid_state with a random "
        "start); after min_s in a state the group is re-rolled every frame from a uniformly "
        "random member (a pick of the current state does nothing), so with two members the "
        "state is left with probability 1/2 per frame; each change eases in"
    )
    rec["idle_cycle"]["evidence"] = (
        "data: member transitions PLAY_TIME >= min_s, group flag Choose Random State, the "
        "class's default state; read: command_get_valid_state 0x5f076f (0x5f07bb-0x5f07d7), "
        "0x5f7873, EvaluateTransitions 0x5cbbc2 (a self-pick is rejected), the controller "
        "start (AnimationCtrlWM sends get_valid_state to a default state that is a group), "
        "rand_integer 0x47b025"
    )
    idle_names = [x["name"] for x in rec["idle_cycle"]["states"]]
    rec["idle_cycle"]["entry"] = {
        # the first segment of a track: the class's default state.  A group is entered at
        # a random member; a state (NiteOwlFace: IdleB) is that state
        "first_segment": (
            idle_names.index(d.name)
            if d is not None and d.cls == asm.CLS_STATE and d.name in idle_names
            else "random"
        ),
        "after_transition": "random",
        "default_state_is": (None if d is None else "group" if d.cls == asm.CLS_GROUP else "state"),
    }
    rec["talk_cycle"]["rule"] = (
        "from START_SPEAK until STOP_SPEAK (the first frame no voice is attached to the "
        "character): "
        "after min_s in a member the talk group is re-rolled every frame at random; with the "
        "ease-in the mouth never settles. No visemes, no audio amplitude"
    )
    rec["talk_cycle"]["evidence"] = "data: transitions; read: 0x69b7a1, 0x69b806, 0x69c7d7"
    return root, rec


HIT_THEN_BASIS = (
    "simulated for a silent character that is not attacking: the hit state lasts one "
    "controller update, because STOP_SPEAK fires in every frame no voice has the root as "
    "pivot and the class then leaves the hit group for a state whose criteria the damage "
    "pose still meets (DAMAGE_POSE is never cleared, so that state stays until the next "
    "hit with another pose).  With a voice on the root (a pain sound) the hit state lasts "
    "min(sound length, hit_hold_s): sound-dependent"
)


def _min_time(state):
    """Smallest PLAY_TIME >= x of the state's own transitions (seconds)."""
    best = None
    for t in asm._trans_nodes(state):
        for c in asm.walk(asm.criteria_of(t)):
            if c.cls == asm.CLS_CRIT and c.p("m_ianimationcriteria", 0) == asm.CRIT_PLAY_TIME:
                v = float(c.p("m_nintervalmin", 0.0) or 0.0)
                best = v if best is None else min(best, v)
    return best


def _cycle(nodes, kind):
    out = []
    for n in nodes:
        if n.cls == asm.CLS_STATE and _kind(n) == kind:
            m = _min_time(n)
            if m is None:
                g = asm._parent_group(n)
                ms = [x for x in (_min_time_group(g),) if x is not None] if g else []
                m = ms[0] if ms else None
            out.append(
                {
                    "name": n.name,
                    "clips": state_clips(n),
                    "min_s": m,
                    "ease_in_s": float(n.p("m_neaseinduration", 0.0) or 0.0),
                }
            )
    return {"states": out}


def _min_time_group(group):
    best = None
    for t in asm._trans_nodes(group):
        for c in asm.walk(asm.criteria_of(t)):
            if c.cls == asm.CLS_CRIT and c.p("m_ianimationcriteria", 0) == asm.CRIT_PLAY_TIME:
                v = float(c.p("m_nintervalmin", 0.0) or 0.0)
                best = v if best is None else min(best, v)
    return best


def _hit_hold(nodes):
    """Seconds after which the hit group (criteria: ACTION HITTAKEN) is left for
    another GROUP by a PLAY_TIME transition; None when it has no such exit."""
    byid = asm.node_index(None, nodes)
    for n in nodes:
        if n.cls != asm.CLS_GROUP:
            continue
        acts = [
            c.p("m_ianimationaction", 0)
            for c in asm.criteria_of(n)
            if c.p("m_ianimationcriteria", 0) == asm.CRIT_ACTION
        ]
        if A_HITTAKEN not in acts:
            continue
        for t in asm._trans_nodes(n):
            target = asm.resolve_ref(t, t.p("m_etostate"), byid)
            crit = [
                c
                for c in asm.criteria_of(t)
                if c.p("m_ianimationcriteria", 0) == asm.CRIT_PLAY_TIME
            ]
            if crit and target is not None and target.cls == asm.CLS_GROUP and target is not n:
                return float(crit[0].p("m_nintervalmin", 0.0) or 0.0)
        return None
    return None


# ------------------------------------------------------------ body-side inputs
def _chain_actions(node, am):
    """Action ids the criteria of `node` and its groups require (not negated)."""
    acts = set()

    def walk(k):
        if (k.p("m_ianimationcriteria") or 0) == asm.CRIT_ACTION and not k.p("m_tnot"):
            acts.add(k.p("m_ianimationaction"))
        for x in k.children:
            if x.cls == asm.CLS_CRIT:
                walk(x)

    for x in [node] + am._groups_of(node):
        for k in am._crit_nodes(x):
            walk(k)
    return acts


def _ev_time(ev, rec, dur):
    """(trigger name, raw, play position, seconds of play time) of an event node
    on its state's default entry (asm.event_timing)."""
    trig = asm.event_trigger(ev)
    raw = round(asm.event_at(ev), 4)
    pp, _ts, pt = asm.event_timing(
        trig,
        raw,
        dur,
        rec.get("speed") or 1.0,
        float(rec.get("start_playpos") or 0.0),
        bool(rec.get("loop")),
    )
    return ee.name("ANIMATION_EVENT_TYPES", trig, "TRIGGER_%s" % trig), raw, pp, pt


_HIT_OTHER = {
    EV_IMPACT_EFFECTS: "IMPACT_EFFECTS",
    EV_PRE_IMPACT: "PRE_IMPACT",
    EV_IMPACT: "IMPACT",
    EV_KILL_PARTNER: "KILL_ANIMATION_PARTNER",
    EV_DISCHARGE: "DISCHARGE_ARMOR",
    EV_BULLMOVE: "BULLMOVE_IMPACT",
    EV_THROW_BRANCH: "THROW_BRANCH_POINT",
}
_EVID = {
    EV_IMPACT_EFFECTS: "read: 0x6ab6a6-0x6ab7d9, pose = the event's enum through "
    "DirectionManipulateDamage 0x802ae8",
    EV_PRE_IMPACT: "read: 0x6ad5ec -> command_hit_soon 0x6903ea; pose = the state's Damage "
    "Pose (0x6ad9b0) before the runtime modifiers",
    EV_IMPACT: "read: 0x6ac9dd -> command_give_damage 0x691b10",
    EV_KILL_PARTNER: "read: 0x6ac5f6, damage record pose 0, damage 100000; StateDead 0x6bb12a "
    "then passes CHARACTER_MODE DEAD",
    EV_DISCHARGE: "read: 0x6a8865 hit_soon + give_damage to the partner",
    EV_BULLMOVE: "read: 0x6abcb1 give_damage",
    EV_THROW_BRANCH: "read: 0x6a91c0 hit_soon",
    EV_CHOKE: "read: 0x6a7512, own head HITTAKEN with DAMAGE_POSE 16",
    EV_SOUND: "read: 0x6aba76, speak flag set -> command_start_speak 0x69b7a1",
    EV_DIE: "read: 0x6ac4e1 give_damage to self, damage record pose 0, damage 100000; "
    "StateDead 0x6bb12a then passes CHARACTER_MODE DEAD",
}


def _pose_name(pid):
    return ee.name("DAMAGE_POSE", pid) if pid is not None else None


def state_inputs(node, rec, am, sounds=None):
    """(inputs, inflicts, notes) of one body state.

    inputs: face-controller inputs on the character that plays the state.
    inflicts: hits its events deliver to the other character (attack target or
    animation partner) -- HITTAKEN inputs on THAT character's face.
    sounds: optional (event node -> sound record, speak id -> {character:
    category}) pair from the sound data; with it a speak-flag SOUND event that
    plays one fixed wave carries `talk_s` (its STOP_SPEAK time is then known)
    and SPEAK notes say which characters' line opens the mouth."""
    inputs, inflicts, notes = [], [], []
    dur = rec.get("duration_s")
    attack = bool(rec.get("attack_state"))
    state_pose = asm.s32(node.p("m_idamagepose", 0) or 0)
    modes = am.allowed_enum_names(node, E_CHARACTER_MODE)
    poses = am.allowed_enum_names(node, E_DAMAGE_POSE)
    if modes == ["DEAD"]:
        inputs.append(
            {
                "t_s": 0.0,
                "input": "DEAD",
                "source": "the state's criteria require CHARACTER_MODE DEAD",
                "evidence": "data: criteria; read: StateDead 0x6bb12a",
                "established": True,
            }
        )
    if attack:
        inputs.append(
            {
                "t_s": 0.0,
                "input": "NORMAL_ATTACK",
                "every_frame": True,
                "source": 'state has "Attack state" set',
                "evidence": DRIVERS["NORMAL_ATTACK"]["evidence"],
                "established": True,
            }
        )
    if poses is not None and modes != ["DEAD"] and A_HITTAKEN in _chain_actions(node, am):
        ids = {v: k for k, v in ee.family("DAMAGE_POSE").items()}
        inputs.append(
            {
                "t_s": 0.0,
                "input": "HITTAKEN",
                "damage_pose_any_of": poses,
                "damage_pose_id": ids[poses[0]] if poses else 0,
                "source": "the hit that selects this state: its criteria require ACTION "
                "HITTAKEN and test DAMAGE_POSE",
                "evidence": "data: criteria; read: give_damage 0x6929e9 sends HITTAKEN and the "
                "same DAMAGE_POSE to the body and the head controller",
                "established": True,
            }
        )
    for ev in asm.state_events(node):
        eid = ev.p("m_ianimationevent")
        trig, raw, pp, pt = _ev_time(ev, rec, dur)
        t = None if pt is None else round(pt, 4)
        base = {"t_s": t, "trigger": trig, "raw": raw}
        if pp is not None:
            base["playpos"] = round(pp, 4)
        if eid == EV_CHOKE:
            inputs.append(
                dict(
                    base,
                    input="HITTAKEN",
                    damage_pose=_pose_name(CHOKE_POSE),
                    damage_pose_id=CHOKE_POSE,
                    source="own event DO_CHOKE_EFFECT",
                    evidence=_EVID[EV_CHOKE],
                    established=True,
                )
            )
        elif eid == EV_SOUND and ev.p("m_ttruth1"):
            i = dict(
                base,
                input="START_SPEAK",
                source="own event SOUND with its speak flag",
                evidence=_EVID[EV_SOUND],
                until="STOP_SPEAK: the first frame no voice has the character root as "
                "pivot (speech, trigger sounds, footsteps on a surface that has a footstep "
                "sound); the length is that of the wave played (pitch 1.0, no random pitch "
                "on any speak wave) -- which wave and voice is drawn at play time, and the "
                "line can be suppressed",
                established=True,
            )
            snd = sounds[0](ev) if sounds else None
            if snd:
                i["sound"] = snd
                if snd.get("talk_s") and t is not None:
                    i["talk_s"] = snd["talk_s"]
                    i["until"] = (
                        "STOP_SPEAK when the wave ends, talk_s after the event: the "
                        "definition plays one fixed wave (data: sound header)"
                    )
                else:
                    i["until"] = (
                        "STOP_SPEAK when the sound ends; the definition draws one of several "
                        "waves (see `sound`), so the end is not fixed"
                    )
            inputs.append(i)
        elif eid == EV_DIE:
            inputs.append(
                dict(
                    base,
                    input="HITTAKEN",
                    damage_pose=_pose_name(0),
                    damage_pose_id=0,
                    source="own event DIE",
                    evidence=_EVID[EV_DIE],
                    established=True,
                )
            )
            inputs.append(
                dict(
                    base,
                    input="DEAD",
                    source="own event DIE",
                    evidence=_EVID[EV_DIE],
                    established=True,
                )
            )
        elif eid == EV_SPEAK:
            n = dict(
                base,
                note="SPEAK event: queues a line in SpeakCtrl (0x84171e); when it plays, "
                "SpeakCtrl.Active 0x83d414 sends START_SPEAK only for a category-1 line "
                "(0x83d936) -- a grunt or shout (category 2) never opens the mouth. Voice "
                "and wave are drawn at random, so no talk segment is placed",
                speak_id=ev.p("m_ivalue00"),
            )
            if sounds:
                n["category_by_character"] = sounds[1](ev.p("m_ivalue00"))
                n["opens_mouth_for"] = sorted(
                    k for k, v in n["category_by_character"].items() if v == 1
                )
            notes.append(n)
        if eid in _HIT_OTHER:
            if eid == EV_IMPACT_EFFECTS:
                pid = asm.s32(ev.p("m_ivalue00", 0) or 0)
                basis, ok = "event enum (m_ivalue00)", True
            elif eid == EV_KILL_PARTNER or (eid == EV_IMPACT and not attack):
                pid, basis, ok = 0, "damage record pose 0", True
            else:
                pid = state_pose
                basis = "state Damage Pose, before the runtime modifiers"
                ok = False
            inflicts.append(
                dict(
                    base,
                    event=_HIT_OTHER[eid],
                    event_id=eid,
                    damage_pose=_pose_name(pid),
                    damage_pose_id=pid,
                    pose_basis=basis,
                    pose_established=ok,
                    kills=eid == EV_KILL_PARTNER,
                    evidence=_EVID[eid],
                )
            )
    inputs.sort(key=lambda i: (i["t_s"] is None, i["t_s"] or 0.0))
    inflicts.sort(key=lambda i: (i["t_s"] is None, i["t_s"] or 0.0))
    return inputs, inflicts, notes


def play_time(rec):
    """Seconds one pass of a body state lasts from its default entry."""
    d, sp = rec.get("duration_s"), rec.get("speed") or 1.0
    if not d:
        return 3.0
    if rec.get("loop"):
        return d / sp
    return max(DT, d * (1.0 - float(rec.get("start_playpos") or 0.0)) / sp)


def _script(inputs):
    out = []
    for i in inputs:
        if i.get("t_s") is None:
            i["in_track"] = False
            i["not_in_track_because"] = "no defined time"
            continue
        if i["input"] == "HITTAKEN":
            if not i.get("pose_established", True):
                i["in_track"] = False
                i["not_in_track_because"] = "the DAMAGE_POSE sent with this hit is not established"
                continue
            out.append((round(i["t_s"], 4), "HIT", i.get("damage_pose_id") or 0))
        elif i["input"] == "START_SPEAK":
            out.append((round(i["t_s"], 4), "START_SPEAK", 0))
            if i.get("talk_s"):  # one fixed wave: the sound, and the talk, end here
                out.append((round(i["t_s"] + i["talk_s"], 4), "STOP_SPEAK", 0))
        elif i["input"] == "DEAD":
            out.append((round(i["t_s"], 4), "DEAD", 0))
    return tuple(out)


class _Tracks:
    """Face tracks of one face class, memoised."""

    def __init__(self, name, root, rec):
        self.name, self.root, self.rec = name, root, rec
        self.hit = rec["hit_pose_to_state"]
        self.hit_states = {v for v in self.hit.values() if v}
        self.timed_hit = rec.get("hit_hold_s") is not None
        self.mix = {x["name"]: x["clip_mix"] for x in rec["states"] if x.get("clip_mix")}
        self._memo = {}

    def track(self, T, attack, mode, inputs, playpos=None):
        """Segments for `inputs` (state_inputs records; flags are written into
        them).  playpos: t -> play position of the body clip, or None."""
        script = _script(inputs)
        key = (round(T, 3), attack, mode, script)
        if key not in self._memo:
            self._memo[key] = simulate(self.root, T, attack, mode, script)
        segs = [dict(s) for s in self._memo[key]]
        alts = None
        for i in inputs:
            if i.get("damage_pose_any_of"):
                by = {}
                for p in i["damage_pose_any_of"]:
                    by.setdefault(str(self.hit.get(p)), []).append(p)
                i["face_state_by_pose"] = by
                if len(by) > 1:
                    alts = by
        for s in segs:
            if alts and s["from_s"] <= 0.05 and s["face_state"] in self.hit_states:
                s["face_state"] = HIT_BY_POSE
                s["one_of"] = alts
                s.pop("clips", None)
            if not self.timed_hit and s["face_state"] in self.hit_states:
                s["sound_dependent"] = (
                    "this class has no timed exit from a hit pose: it is left on the first "
                    "frame no voice has the character root as pivot (speech, trigger sounds, "
                    "footsteps on a surface that has a footstep sound); shown for a silent "
                    "character"
                )
            if s["face_state"] == TALK:
                fx = [
                    i
                    for i in inputs
                    if i["input"] == "START_SPEAK"
                    and i.get("talk_s")
                    and i.get("t_s") is not None
                    and i["t_s"] - 1e-6 <= s["from_s"] <= i["t_s"] + 2 * DT
                ]
                if fx:
                    s["talk"] = {
                        "wave": fx[0]["sound"].get("wave"),
                        "talk_s": fx[0]["talk_s"],
                        "ends_s": round(fx[0]["t_s"] + fx[0]["talk_s"], 3),
                        "basis": "one fixed wave: its length is the talk time",
                    }
                else:
                    s["sound_dependent"] = "ends at STOP_SPEAK; shown without an end"
            if len(s.get("clips", ())) > 1 and s["face_state"] in self.mix:
                s["clip_mix"] = self.mix[s["face_state"]]
            if playpos is not None:
                s["from_playpos"] = playpos(s["from_s"])
                s["to_playpos"] = None if s["to_s"] is None else playpos(s["to_s"])
        return segs


def _category(track, inputs):
    if track is None:
        return "no_face"
    specific = [s for s in track if s["face_state"] != IDLE]
    if not specific:
        return "idle_only"
    first = [s for s in track if s["from_s"] <= 0.05]
    if any(s["face_state"] == "Attack" for s in first):
        return "attack"
    if any(i["input"] == "DEAD" and i["t_s"] == 0.0 for i in inputs):
        return "dead"
    if any(i["input"] == "HITTAKEN" and i["t_s"] == 0.0 for i in inputs):
        return "hit_at_entry"
    return "event_driven"


def _confidence(track, inputs, extra=()):
    basis, level = list(extra), "high"
    for s in track or ():
        if s.get("sound_dependent"):
            level = "low"
            basis.append("a segment ends with the character's sound (%s)" % s["face_state"])
        if s["face_state"] == HIT_BY_POSE and level == "high":
            level = "medium"
            basis.append("the hit pose depends on which of the allowed damage poses was dealt")
    for i in inputs:
        if i.get("in_track") is False and level == "high":
            level = "medium"
            basis.append("an input is left out: " + i["not_in_track_because"])
    if any(i["input"] == "NORMAL_ATTACK" for i in inputs):
        basis.append(
            "attack states are taken to run in CHARACTER_MODE COMBAT (assumed: the mode is "
            "game state)"
        )
    return level, "; ".join(dict.fromkeys(basis)) or "data and read code only"


# ----------------------------------------------------------------- the block
def build(extract_out, classes, states, pairs, am, log=None):
    """Adds the face records to the anim_meta tables and returns the top-level
    `face` block (None when the extract has no face class).

    classes: anim_meta.load_classes(); states: {class: [(node, record)]};
    pairs: the pair list (mutated: `face`); am: the anim_meta module."""
    log = log or (lambda *a: None)
    frags = find_face_fragments(extract_out)
    if not frags:
        return None
    tracks, recs = {}, {}
    for name, path in frags.items():
        root, rec = face_class_record(name, path, extract_out, am)
        recs[name] = rec
        tracks[name] = _Tracks(name, root, rec)
    by_id = {r["class_id"]: n for n, r in recs.items()}
    table = charvisual_table(extract_out)
    body_face, body_ids = {}, {}
    for cn, c in classes.items():
        root = asm.find_class_root([n for n in c["nodes"] if n.parent is None])
        cid = root.p("m_iclassid") if root is not None else None
        if cid is None:
            cid = _class_id_by_name(cn)
        body_ids[cn] = cid
        rows = [r for r in table if r["body_class_id"] == cid]
        fids = sorted({r["face_class_id"] for r in rows if r["face_class_id"] is not None})
        body_face[cn] = {
            "body_class_id": cid,
            "face_class": by_id.get(fids[0]) if fids else None,
            "face_class_id": fids[0] if fids else None,
            "charvisual_fragments": [r["fragment"] for r in rows],
            "basis": (
                "data: m_ianimationclassid of the body and the HeadModel controllers in the "
                "CharVisual fragments"
                if rows
                else "no CharVisual fragment uses this body class id"
            ),
        }
        if rows and not fids:
            body_face[cn]["note"] = "the CharVisual fragment has no HeadModel: no face controller"
    speech, snd_of = _speech(extract_out, log), {}
    if speech is not None:
        for cn, c in classes.items():
            snd_of[cn] = (
                lambda ev, f=c["fragment"]: speech.event_sound(ev, f),
                lambda sid, cn=cn: speech.categories(cn, sid),
            )
    own, index = {}, {}
    for cn, lst in states.items():
        fc = body_face.get(cn, {}).get("face_class")
        for node, rec in lst:
            ins, infl, notes = state_inputs(node, rec, am, snd_of.get(cn))
            modes = am.allowed_enum_names(node, E_CHARACTER_MODE)
            own[id(rec)] = (ins, infl, notes, modes)
            index[(cn, rec["path"], rec["name"])] = rec
            if infl:
                rec["inflicts"] = infl
            if fc is None:
                rec["face"] = None
                continue
            T = play_time(rec)
            dead = any(i["input"] == "DEAD" and i["t_s"] == 0.0 for i in ins)
            attack = bool(rec.get("attack_state"))
            mode, mode_basis = character_mode(modes, attack, dead)
            d, sp = rec.get("duration_s"), rec.get("speed") or 1.0
            start = float(rec.get("start_playpos") or 0.0)

            def pp(t, d=d, sp=sp, start=start):
                if not d:
                    return None
                v = start + t * sp / d
                return round(v, 4) if v <= 1.0 + 1e-6 else None

            tr = tracks[fc].track(T, attack, mode, ins, pp)
            level, basis = _confidence(tr, ins)
            face = {
                "class": fc,
                "play_time_s": round(T, 3),
                "category": _category(tr, ins),
                "character_mode": {
                    "name": ee.name("CHARACTER_MODE", mode),
                    "basis": mode_basis,
                },
                "inputs": ins,
                "track": tr,
                "confidence": level,
                "confidence_basis": basis,
            }
            if notes:
                face["notes"] = notes
            rec["face"] = face
    npair = 0
    for p in pairs:
        if not p.get("primary"):
            continue
        m = _find(index, p["master_class"], p["master_path"], p["master_state"])
        v = _find(index, p["partner_class"], p["partner_path"], p["partner_state"])
        tl = p.get("timeline") or {}
        pps, sp0 = tl.get("playpos_per_second"), tl.get("start_playpos") or 0.0
        if m is None or v is None or not pps:
            continue
        T = (1.0 - sp0) / pps
        out = {
            "clock": "seconds since both states started; play position = "
            "timeline.start_playpos + t * timeline.playpos_per_second on both clips",
            "play_time_s": round(T, 3),
        }
        for role, rec, other, cls in (
            ("master", m, v, p["master_class"]),
            ("partner", v, m, p["partner_class"]),
        ):
            fc = body_face.get(cls, {}).get("face_class")
            if fc is None:
                out[role] = None
                continue
            ins = [dict(i) for i in own[id(rec)][0]]
            if role == "partner":  # its play position is the master's (0x5b5756)
                for i in ins:
                    i["t_s"] = _shared(i, sp0, pps, True)
            for x in own[id(other)][1]:
                t = _shared(x, sp0, pps, role == "master")
                who = "master" if role == "partner" else "partner"
                src = "%s event %s" % (who, x["event"])
                hit = {
                    "t_s": t,
                    "input": "HITTAKEN",
                    "damage_pose": x["damage_pose"],
                    "damage_pose_id": x["damage_pose_id"],
                    "pose_basis": x["pose_basis"],
                    "pose_established": x["pose_established"],
                    "source": src,
                    "evidence": x["evidence"],
                    "established": True,
                }
                if x["event_id"] == EV_IMPACT_EFFECTS:
                    # DirectionManipulateDamage 0x802ae8: from behind the pose
                    # becomes its *_BACK variant; say what that would show
                    back = back_pose(x["damage_pose_id"])
                    h2s = recs[fc]["hit_pose_to_state"]
                    fs, fb = h2s.get(x["damage_pose"]), h2s.get(_pose_name(back))
                    hit["damage_pose_if_behind"] = _pose_name(back)
                    hit["face_state"] = fs
                    hit["face_state_if_behind"] = fb
                    hit["behind_changes_face"] = fs != fb
                ins.append(hit)
                if x["kills"]:
                    ins.append(
                        {
                            "t_s": t,
                            "input": "DEAD",
                            "source": src,
                            "evidence": x["evidence"],
                            "established": True,
                        }
                    )
            ins.sort(key=lambda i: (i["t_s"] is None, i["t_s"] or 0.0))
            dead = any(i["input"] == "DEAD" and i["t_s"] == 0.0 for i in ins)
            attack = bool(rec.get("attack_state"))
            mode, mode_basis = character_mode(own[id(rec)][3], attack, dead)

            def pp(t, sp0=sp0, pps=pps):
                v2 = sp0 + t * pps
                return round(v2, 4) if v2 <= 1.0 + 1e-6 else None

            tr = tracks[fc].track(T, attack, mode, ins, pp)
            level, basis = _confidence(
                tr,
                ins,
                ("hits are delivered while the victim is alive and not blocking",),
            )
            out[role] = {
                "class": fc,
                "category": _category(tr, ins),
                "character_mode": {
                    "name": ee.name("CHARACTER_MODE", mode),
                    "basis": mode_basis,
                },
                "inputs": ins,
                "track": tr,
                "confidence": level,
                "confidence_basis": basis,
            }
        p["face"] = out
        npair += 1
    log("  face: %d classes, %d pairs with a face record" % (len(recs), npair))
    return {
        "conventions": {
            "time": "t_s / from_s / to_s are seconds of play time since the body state (or "
            "the pair) started; *_playpos is the body clip's play position then (null past "
            "the end of one pass); clip time = playpos * duration_s",
            "track": "the face states that follow from `inputs`, simulated with the face "
            "class at 30 Hz for a silent character; a segment eases in over ease_in_s from "
            "whatever was shown before; to_s null = to the end",
            "IDLE": "the class's idle_cycle (random, not part of the track)",
            "TALK": "the class's talk_cycle (random).  With `talk` the segment belongs to a "
            "SOUND event that plays one fixed wave and ends with it; otherwise its end is "
            "sound_dependent: the length is that of the wave played (pitch 1.0, no random "
            "pitch on any speak wave), but which wave and voice is drawn at play time and "
            "the line can be suppressed.  Talk ends on the first frame NO voice has the "
            "character root as pivot (speech, trigger sounds, footsteps on a surface that "
            "has a footstep sound)",
            "evaluation": "the face class is evaluated every frame while the head is in a "
            "camera frustum within 9 m (either camera; AnimationCtrlWM.StateMain / "
            "IsShownOrClose, 9.0 at 0xa45bec, read); the tracks are what such a head shows",
            "hit_hold": "a hit state eases in over its ease_in_s and is held for the class's "
            "hit_hold_s UNLESS the face class leaves earlier: an attacking character goes "
            "to Attack on the next update, and a hit whose damage pose meets another "
            "state's criteria on a silent character (STUN_MIDDLE -> Retreat) is left after "
            "one update -- classes[*].hit_pose_then; hit_pose_to_state is the FIRST state",
            "HIT_BY_POSE": "a hit pose that depends on the damage pose dealt: one_of",
            "inflicts": "on a body state: hits its events deliver to the OTHER character",
            "evidence": "read = traced in the executable (address given), data = measured on "
            "the game files",
        },
        "drivers": DRIVERS,
        "timing": {
            "ease_in_s": "per state (0.21 on all but one: 0.37 on Enemy04Face "
            "KnockDownMiddleLeft(ClosedEyes), the Twilight Lady / Dominatrix knock-down face)",
            "hit_hold_note": "an upper bound, see conventions.hit_hold",
            "hit_hold_s": {n: r["hit_hold_s"] for n, r in recs.items()},
            "simulation_hz": 30,
        },
        "attachment": ATTACHMENT,
        "charvisual": table,
        "body_class": body_face,
        "classes": recs,
        "talk_clips": _talk_clips(speech, by_id),
        "not_established": NOT_ESTABLISHED,
    }


def _speech(extract_out, log=None):
    """sound_meta.Speech of the extract, or None when it has no sound data."""
    try:
        import sound_meta

        sp = sound_meta.Speech(extract_out, log)
        return sp if sp.groups or sp.db.sound_fragments() else None
    except Exception as ex:  # the face rule works without sounds (talk stays open-ended)
        (log or (lambda *a: None))("  face: no sound data (%s: %s)" % (type(ex).__name__, ex))
        return None


TALK_CLIPS_RULE = (
    "a line of category 1 opens the mouth from the frame its sound starts until the sound "
    "ends (talk_s = the wave's length; the voice is drawn once per character, the wave per "
    "play, never the one played last); most lines are requested by the AI, not by an "
    "animation event, so they are not baked into a body clip: build a talk clip of talk_s "
    "from the class's talk_cycle, starting start_delay_s after the request, keyed by "
    "(character, voice, wave).  Speak ids in closed_mouth_speak_ids are category 2 "
    "(grunts, shouts, hit and death sounds), category 0 (which sends no START_SPEAK "
    "either) or never play: the mouth stays in its idle / attack / hit state"
)


def _talk_clips(speech, face_by_id):
    if speech is None:
        return None
    chars = speech.talk_clips()
    for c in chars.values():
        c["face_class"] = face_by_id.get(c.get("face_class_id"))
    return {
        "rule": TALK_CLIPS_RULE,
        "evidence": "read: SpeakLib.DetermineSoundCategoryStruct 0x83baa1, SpeakCtrl.Active "
        "0x83d936 (START_SPEAK), 0x83dbe4 (STOP_SPEAK), voice choice 0x83afd6, wave choice "
        "0x831365; data: SpeakDefinition flags, sound headers",
        "characters": chars,
    }


# CHARACTER_MODE as CharacterRoot.StateActive 0x6b367a sets it (root +0xac, passed
# to command_update_animation): 0; 1 (COMBAT) when (in combat, or a weapon is held,
# or m_tforcecombat) and (playable, or player-controlled, or m_istateofmind != 0),
# and for non-playable types 8-11 without a player controller; 3 while its stun
# timer runs; 4 prone; StateDead passes 2 (DRIVERS["CHARACTER_MODE"]["rule"]).  A
# body state that only exists in one mode says so in its criteria (the CombatGroup
# of every body class tests CHARACTER_MODE).
def character_mode(modes, attack, dead):
    """(mode id, basis) of a body state.  modes: the CHARACTER_MODE values its
    criteria leave possible (anim_meta.allowed_enum_names), or None."""
    ids = {v: k for k, v in ee.family("CHARACTER_MODE").items()}
    if dead:
        return MODE_DEAD, "data: the state's criteria require CHARACTER_MODE DEAD"
    if modes is not None and len(modes) == 1 and modes[0] in ids:
        return ids[modes[0]], "data: the state's criteria require CHARACTER_MODE " + modes[0]
    if modes is not None and "COMBAT" not in modes:
        return MODE_NONCOMBAT, "data: the state's criteria exclude CHARACTER_MODE COMBAT"
    if attack:
        return (
            MODE_COMBAT,
            "assumed: an attack state is taken to run in combat (the mode is game state: "
            "StateActive 0x6b367a sets COMBAT while the character has a target)",
        )
    return (
        MODE_NONCOMBAT,
        "assumed: the criteria do not fix the mode; it only matters to the face of "
        "attack states",
    )


# ProjectAnimationLib.DirectionManipulateDamage 0x802ae8: the attacker's position
# is brought into the victim's local space; when its z is below -0.2 m (double at
# 0xa40310; +Z is forward) the damage pose becomes its *_BACK variant.
BEHIND_Z = -0.2
_BACK = {19: 21, 20: 22}
for _i in range(18):
    _BACK[_i + 1] = 23 + _i // 3


def back_pose(pose):
    """The pose DirectionManipulateDamage substitutes when the attacker is behind."""
    return _BACK.get(pose, pose)


def direction_manipulate(pose, attacker_local_z):
    """DAMAGE_POSE after DirectionManipulateDamage 0x802ae8."""
    return back_pose(pose) if attacker_local_z < BEHIND_Z else pose


def _class_id_by_name(cn):
    """Class id of a body class whose fragment has no class node (the heroes)."""
    fam = ee.family("CHARACTER_ANIMATIONS")
    want = {"rorschach": "RSH", "niteowl": "NTO"}.get(cn.lower())
    for k, v in fam.items():
        if v == want:
            return k
    return None


def _find(index, cls, path, name):
    for (c, p, n), rec in index.items():
        if c == cls and n == name and (p == path or path.endswith("/" + p) or p.endswith(path)):
            return rec
    return None


def _shared(x, sp0, pps, slaved):
    """Time on the pair's clock of an event given on its state's own timeline.
    slaved: the state's play position is the pair's (a partner's own PLAY_POS
    events, or events of the partner state seen from the master)."""
    trig = x.get("trigger")
    if trig == "TOTAL_PLAY_TIME":
        return x.get("raw")
    if trig == "ENTER_STATE":
        return 0.0
    if trig == "LEAVE_STATE":
        return None
    if trig == "PLAY_POS" and slaved:
        return round(max(0.0, (x["raw"] - sp0) / pps), 4) if pps else None
    return x.get("t_s")


# ------------------------------------------------------------- GLB baking
TRACK_CHOICE = (
    "per body clip: the face track of the primary pair the clip plays in, else of the "
    "states whose main clip it is, else of the states that blend it with their main clip; "
    "among several: the track most of them share, then one that is not idle throughout, "
    "then the higher confidence, then the first by (class, path).  Baked: hit, attack and "
    "dead segments at their times with each state's ease-in; a TALK segment of a fixed "
    "wave (`talk`) as a seeded instance of the class's random talk cycle for the wave's "
    "length; other TALK, sound-dependent and pose-dependent (HIT_BY_POSE) segments stay on "
    "the idle pose and are listed in not_baked; IDLE shows the first idle state plus, "
    "unless switched off, a seeded instance of the class's random idle cycle"
)


def choose_track(meta, clip, family):
    """The face track to bake into body clip `clip` for a head of pose family
    `family` ("EN1" / "BS2" / "NTO").

    A clip can be the main clip of several states.  Candidates are their face
    records -- the pair record when the state is in a primary pair (the clip
    then only plays in that pair) -- restricted to face classes of this pose
    family.  A clip that is nowhere a main clip takes the states it is blended
    into beside the main clip (same layer; not the "blend on NONE" clip lists).  Chosen: the track most candidates share; ties go to a track
    that is not idle throughout, then to the higher confidence, then to the
    first in (class, path) order.
    -> None, or {track, source {...}, candidates, distinct_tracks, duration_s}."""
    face = (meta or {}).get("face") or {}
    fam_of = {n: r.get("pose_family") for n, r in (face.get("classes") or {}).items()}
    clips = (meta or {}).get("clips") or {}
    clip_key = clip
    if clip_key not in clips:
        clip_key = {k.lower(): k for k in clips}.get(str(clip).lower())
    c = clips.get(clip_key)
    if c is None:
        return None
    cands, partners = [], []
    for u in sorted(c.get("used_by", []), key=lambda x: (x["class"], x["path"])):
        st = _state_rec(meta, u["class"], u["path"], u["state"])
        if st is None:
            continue
        f = st.get("face")
        if not f or fam_of.get(f["class"]) != family:
            continue
        src = {
            "class": u["class"],
            "state": u["state"],
            "path": u["path"],
            "pair": None,
            "class_face": f["class"],
        }
        start = st.get("start_playpos") or 0.0
        if u.get("main"):
            rate = (st.get("speed") or 1.0) / st["duration_s"] if st.get("duration_s") else None
            cands.append((src, f["track"], f["confidence"], start, rate))
            continue
        # a clip blended with the main clip in the same layer (1H / 2H weapon,
        # direction, speed) plays through the same state
        layer = {x["clip"]: x.get("layer") for x in st.get("clips", [])}
        la = layer.get(st.get("main_clip"))
        if la is None or layer.get(clip_key) != la or "blend on NONE" in la:
            continue
        src["slot"] = "blended with the state's main clip %s (%s)" % (st["main_clip"], la)
        rate = (u.get("speed") or 1.0) / c["duration_s"] if c.get("duration_s") else None
        partners.append((src, f["track"], f["confidence"], start, rate))
    paired = []
    for ref in c.get("pairs", []):
        p = meta["pairs"][ref["pair"]]
        f = (p.get("face") or {}).get(ref["role"])
        if not p.get("primary") or not f or fam_of.get(f["class"]) != family:
            continue
        tl = p["timeline"]
        paired.append(
            (
                {
                    "class": p[ref["role"] + "_class"],
                    "state": p[ref["role"] + "_state"],
                    "path": p[ref["role"] + "_path"],
                    "pair": ref["pair"],
                    "role": ref["role"],
                    "other_clip": ref["other_clip"],
                    "class_face": f["class"],
                },
                f["track"],
                f["confidence"],
                tl["start_playpos"],
                tl["playpos_per_second"],
            )
        )
    if not cands and not paired:
        cands = partners
    if paired:
        states_in_pairs = {(x[0]["class"], x[0]["state"]) for x in paired}
        cands = [x for x in cands if (x[0]["class"], x[0]["state"]) not in states_in_pairs]
        cands = paired + cands
    if not cands:
        return None
    rank = {"high": 0, "medium": 1, "low": 2}

    def sig(tr):
        return tuple((s["from_s"], s["to_s"], s["face_state"]) for s in tr)

    groups = {}
    for i, x in enumerate(cands):
        groups.setdefault(sig(x[1]), []).append(i)

    def idle_only(i):
        return all(x["face_state"] == IDLE for x in cands[i][1])

    best = min(
        groups.values(),
        key=lambda ix: (-len(ix), idle_only(ix[0]), rank.get(cands[ix[0]][2], 3), ix[0]),
    )
    src, tr, conf, start, rate = cands[best[0]]
    return {
        "track": tr,
        "source": src,
        "confidence": conf,
        "candidates": len(cands),
        "distinct_tracks": len(groups),
        "start_playpos": start,
        "playpos_per_second": rate,
    }


_STATE_INDEX = [None, None]  # (the meta dict, its index): one table at a time


def _state_rec(meta, cls, path, name):
    if _STATE_INDEX[0] is not meta:
        idx = {}
        for cn, c in (meta.get("classes") or {}).items():
            for s in c.get("states", []):
                idx[(cn, s["path"], s["name"])] = s
        _STATE_INDEX[:] = [meta, idx]
    return _STATE_INDEX[1].get((cls, path, name))


def idle_plan(clip, t0, t1, cycle, hz=30.0, entry=0):
    """Deterministic instance of the game's idle rule on [t0, t1): the entry
    state for at least its min_s, then every frame a 1/2 chance (seeded by the
    clip name) to change to the next, and so on.  -> [(t, state index)],
    starting with (t0, entry state).  Empty when the class has a single idle
    state.

    entry: index of the idle state the segment starts in, or "random": the
    engine enters the idle group at a uniformly random member (every transition
    into it, and the controller's start when the class's default state is the
    group: command_get_valid_state 0x5f076f draws the start with
    rand_integer(count)).  The draw is seeded by the clip name and t0 on a
    stream of its own, so a plan that draws state 0 is the plan of entry=0."""
    sts = [s for s in cycle.get("states", []) if s.get("min_s") is not None]
    if len(sts) < 2 or len(sts) != len(cycle.get("states", [])):
        return []
    if entry == "random":
        draw = random.Random(
            zlib.crc32(("idle-entry:" + str(clip)).encode("utf-8")) ^ int(round(t0 * 1000))
        )
        i = draw.randrange(len(sts))
    else:
        i = int(entry or 0) % len(sts)
    rng = random.Random(zlib.crc32(str(clip).encode("utf-8")) ^ int(round(t0 * 1000)))
    out, t = [(t0, i)], t0
    while True:
        t += sts[i]["min_s"]
        while rng.random() < 0.5:  # the re-roll picked the current state: no change
            t += 1.0 / hz
        if t >= t1:
            return out
        i = (i + 1) % len(sts)
        out.append((round(t, 4), i))


def idle_entry(cycle, first_segment):
    """The `entry` argument of idle_plan() for an IDLE segment of a class whose
    record is `cycle` (classes[*].idle_cycle): its `entry` block says how the
    first segment of a track and a segment entered by a transition start.  A
    table written before the block existed gives 0, the first idle state."""
    ent = cycle.get("entry") or {}
    e = ent.get("first_segment" if first_segment else "after_transition")
    return 0 if e is None else e


def talk_plan(clip, t0, t1, cycle, hz=30.0):
    """Deterministic instance of the game's talk rule on [t0, t1): the talk group
    is entered at a random member; after the member's min_s the group is
    re-rolled every frame from a uniformly random member (a pick of the current
    one does nothing).  Seeded by the clip name.  -> [(t, state index)]."""
    sts = cycle.get("states", [])
    if not sts or any(s.get("min_s") is None or not s.get("clips") for s in sts):
        return []
    rng = random.Random(zlib.crc32(("talk:" + str(clip)).encode("utf-8")) ^ int(round(t0 * 1000)))
    i = rng.randrange(len(sts))
    out, t = [(round(t0, 4), i)], t0
    while len(sts) > 1:
        t += sts[i]["min_s"]
        j = rng.randrange(len(sts))
        while j == i:
            t += 1.0 / hz
            j = rng.randrange(len(sts))
        if t >= t1:
            break
        i = j
        out.append((round(t, 4), i))
    return out


def pose_schedule(chosen, fclass, clip, clip_time, idle=True, duration=None):
    """[(time in the written animation, pose clip name, ease seconds)] for a
    chosen track.  clip_time: play position -> seconds in the written animation
    (None = outside it).  The first entry is the pose shown from time 0.
    Only deterministic segments are scheduled: sound-dependent segments (a
    TALK without a fixed wave among them) and HIT_BY_POSE stay on the idle
    pose; a TALK segment with `talk` (one fixed wave) is a seeded talk cycle
    (talk_plan); a state with two slots and no blend parameter shows its first
    slot (clip_mix: first_child_only).  idle: also schedule the seeded idle
    cycle; each IDLE segment then starts in the state idle_entry() gives (a
    seeded random member when the class's record says so, as the engine enters
    the idle group; the first idle state for an older table).
    duration: length of the written animation; an idle-cycle change that could
    not come back before the end is left out (the clip would end, and loop, on
    a half-finished blink): a track that opens with an IDLE segment has to end
    in the idle state it starts in, any other in the first idle state; an entry
    draw that could not come back at all is replaced by the first idle state."""
    idle_states = fclass["idle_cycle"]["states"]
    neutral = idle_states[0]["clips"][0] if idle_states and idle_states[0]["clips"] else None
    if neutral is None:
        return [], []
    ease0 = idle_states[0].get("ease_in_s", 0.21)
    start, rate = chosen["start_playpos"], chosen["playpos_per_second"]
    track = chosen["track"]
    end = track[-1]["from_s"] + 1e9

    def wt(t):
        if rate is None:
            return t
        return clip_time(start + t * rate)

    sched, skipped = [(0.0, neutral, 0.0)], []
    for s in track:
        t0, t1 = s["from_s"], s["to_s"] if s["to_s"] is not None else end
        w0 = wt(t0)
        if w0 is None:
            continue
        fs = s["face_state"]
        if fs == TALK and s.get("talk") and not s.get("sound_dependent"):
            tsts = fclass.get("talk_cycle", {}).get("states", [])
            plan = talk_plan(clip, t0, min(t1, t0 + 3600.0), fclass.get("talk_cycle", {}))
            for k, (t, i) in enumerate(plan):
                w = wt(t)
                if w is None or (duration is not None and w > duration):
                    break
                sched.append((w, tsts[i]["clips"][0], tsts[i].get("ease_in_s", 0.21)))
            if plan:
                continue
        if fs == IDLE or fs in (TALK, HIT_BY_POSE) or s.get("sound_dependent"):
            if fs != IDLE:
                skipped.append({"face_state": fs, "from_s": t0, "reason": "not deterministic"})
            if t0 > 0.0:
                sched.append((w0, neutral, ease0))
            if idle and fs == IDLE:
                horizon = min(t1, t0 + 3600.0)
                first = t0 <= 0.0 and len(sched) == 1
                last = duration is not None and t1 >= end

                def planned(entry):
                    full = idle_plan(clip, t0, horizon, fclass["idle_cycle"], entry=entry)
                    if not full:
                        return 0, 0, []
                    k0, plan = full[0][1], []
                    for t, i in full[1:]:
                        w = wt(t)
                        if w is None or (duration is not None and w > duration):
                            break
                        plan.append((w, i))
                    # the idle state the clip has to end in: the one it starts in when
                    # the track opens with this segment (a loop), else the first
                    home = k0 if first else 0
                    while plan and last:
                        # no time left to return to that state, or to finish easing
                        # back into it
                        back = idle_states[home].get("ease_in_s", 0.21)
                        if plan[-1][1] != home or plan[-1][0] + back > duration:
                            plan.pop()
                        else:
                            break
                    return k0, home, plan

                k0, home, plan = planned(idle_entry(fclass["idle_cycle"], first))
                if last and (
                    (plan[-1][1] if plan else k0) != home or (first and not plan and k0 != 0)
                ):
                    # the drawn entry cannot come back before the clip ends: start in
                    # the first idle state, as an older table does
                    k0, home, plan = planned(0)
                if k0 != 0 and idle_states[k0].get("clips"):
                    st = idle_states[k0]
                    if first:
                        sched[0] = (0.0, st["clips"][0], 0.0)
                    elif t0 > 0.0:
                        sched[-1] = (w0, st["clips"][0], st.get("ease_in_s", 0.21))
                for w, i in plan:
                    st = idle_states[i]
                    sched.append((w, st["clips"][0], st.get("ease_in_s", 0.21)))
            continue
        sched.append((w0, s["clips"][0], s.get("ease_in_s", 0.21) if t0 > 0.0 else 0.0))
    sched.sort(key=lambda x: x[0])
    return sched, skipped


def pose_weights(sched, t):
    """{pose: weight} at time t for a pose schedule: each entry cross-fades in
    linearly over its ease from whatever was shown (the page stack of
    SetupNewPage 0x5b7788 with a linear blend)."""
    w = {}
    for t0, pose, ease in sched:
        if t0 > t + 1e-9:
            break
        a = 1.0 if ease <= 0.0 else min(1.0, (t - t0) / ease)
        if a > 1.0 - 1e-9:
            a = 1.0
        w = {k: v * (1.0 - a) for k, v in w.items()}
        w[pose] = w.get(pose, 0.0) + a
    return {k: v for k, v in w.items() if v > 1e-6}


def key_times(sched, duration, hz=30.0):
    """Times at which a pose schedule has to be keyed: both ends of every
    cross-fade, sampled at `hz` inside overlapping ones."""
    ts = {0.0, round(max(duration, 1e-3), 5)}
    for i, (t0, _p, ease) in enumerate(sched):
        if t0 > duration:
            break
        ts.add(round(t0, 5))
        e = min(t0 + ease, duration)
        ts.add(round(e, 5))
        nxt = sched[i + 1][0] if i + 1 < len(sched) else None
        prev_end = sched[i - 1][0] + sched[i - 1][2] if i > 0 else None
        if (nxt is not None and nxt < e) or (prev_end is not None and prev_end > t0):
            k = t0
            while k < e:
                ts.add(round(k, 5))
                k += 1.0 / hz
    return sorted(x for x in ts if 0.0 <= x <= max(duration, 1e-3) + 1e-9)


def pose_extras(meta, animname):
    """extras of a `FACE ...` animation of a character GLB: which face states
    of which face class show this pose, or that the toolkit made it up."""
    if animname.startswith("FACE SYNTH"):
        return {
            "synthetic": True,
            "note": "toolkit-made loop of shipped poses; the game has no such clip",
        }
    used = []
    classes = ((meta or {}).get("face") or {}).get("classes") or {}
    for cn in sorted(classes):
        for st in classes[cn].get("states", []):
            if animname in st.get("glb_animation_names", []):
                used.append({"class": cn, "state": st["name"], "kind": st.get("kind")})
    return {"synthetic": False, "pose": animname.split("/")[-1], "face_states": used}


# ------------------------------------------------------------- head models
# ANIMATION_HEAD_MODEL, registered at 0x80b33e-0x80b4a0
HEAD_MODEL_TYPES = {
    0: "LARGE_HEAD_1",
    1: "LARGE_HEAD_2",
    2: "LARGE_HEAD_3",
    3: "MEDIUM_HEAD_1",
    4: "MEDIUM_HEAD_2",
    5: "MEDIUM_HEAD_3",
    6: "LARGE_HEAD_3KT",
    7: "SMALL_HEAD_1",
    8: "SMALL_HEAD_1KT",
    9: "MEDIUM_HEAD_MERC_1",
    10: "MEDIUM_HEAD_MERC_2",
    11: "SMALL_HEAD_MERC_1",
    12: "SMALL_HEAD_MERC_2",
    13: "LARGE_HEAD_GOATEE",
    14: "MEDIUM_HEAD_GOATEE",
    15: "HEAD_UNDERBOSS",
    16: "HEAD_NITE_OWL",
    17: "HEAD_TWILIGHT_LADY",
    18: "HEAD_DOMINATRIX_1",
    19: "HEAD_GIMP_1",
    20: "HEAD_GIMP_2",
    21: "HEAD_DOMINATRIX_2",
    22: "HEAVY_1",
    23: "HEAD_DOMINATRIX_3",
    24: "HEAD_DOMINATRIX_4",
    25: "HEAD_DOMINATRIX_5",
    26: "HEAD_GIMP_3",
}
_HEADS = {}


def head_tables(extract_out):
    """(body, heads, sheets) from the CharacterModelCollection fragments.

    body:  {variant name: [(head model type, [model basenames])]} -- the
           CharacterHeadModel nodes of a collection that references a head
           collection (`_eheadmodelcollection`);
    heads: {head model type: model basename} -- the nodes of the head
           collections (ThugFace, BordelloFace, ...);
    sheets: {head model type: [{slot, pivot, lod, path, sheet_id}]} -- those
           nodes' textureSheetsDescription: which sheet of which of the head's
           textures the game uses (sheet_overrides).
    The type is ANIMATION_HEAD_MODEL (m_iheadmodeltype); CharacterHeadCtrl.
    command_activate 0x669496 asks the head collection for the model of the
    character's type (command_get_model_by_id 0x8ffd39d)."""
    if extract_out in _HEADS:
        return _HEADS[extract_out]
    body, heads, sheets = {}, {}, {}
    hits = set()
    for ext in (".fragment", ".fragment.json"):
        for f in _kj.glob_tree(_fragroot(extract_out), "Fragments", "Enemy", "*" + ext):
            hits.add(f[: -len(".json")] if f.endswith(".json") else f)
    for f in sorted(hits):
        try:
            if os.path.getsize(f if os.path.exists(f) else f + ".json") > 200000:
                continue  # the All*Types level fragments: no collections of their own
            roots = asm.load_tree(f, False)
        except (OSError, ValueError, KeyError, IndexError):
            continue
        for n in asm.walk(roots):
            if n.cls != "CharacterHeadModel" or n.parent is None:
                continue
            ref = n.parent.p("_eheadmodelcollection")
            typ = asm.s32(n.p("m_iheadmodeltype", 0) or 0)
            models = [
                os.path.splitext(m.replace("\\", "/").rsplit("/", 1)[-1])[0]
                for m in (n.p("modelNames") or [])
                if m
            ]
            if isinstance(ref, dict) and ("xref" in ref or "ref" in ref):
                name = n.name or os.path.basename(f)[: -len(".fragment")]
                body.setdefault(name, []).append((typ, models))
            elif models and typ not in heads:
                heads[typ] = models[0]
                sheets[typ] = sheet_records(n.p("textureSheetsDescription"))
    _HEADS[extract_out] = (body, heads, sheets)
    return body, heads, sheets


def game_head(extract_out, variant, models):
    """The face-rigged head model the game gives variant `variant`, whose body
    is built from `models` (basenames, exactly one static head among them).

    1. A head named in the variant's own model list next to its static copy
       (`X` beside `X_NoSKL`) is that head.
    2. Otherwise the head collection's model for the variant's head model type;
       with several nodes of one name (KnotTop_Large), the node whose model
       list contains the static head.
    -> None, or {head, static, head_model_type, head_by_type, basis,
    texture_sheets (the head collection node's textures, when the head is that
    node's model)}."""
    body, heads, sheets = head_tables(extract_out)
    statics = [m for m in models if "head" in m.lower()]
    if len(statics) != 1:
        return None
    static = statics[0]
    nodes = body.get(variant) or []
    with_static = [x for x in nodes if static in x[1]] or nodes
    typ = with_static[0][0] if with_static else None
    by_type = heads.get(typ) if typ is not None else None
    twin = static[: -len("_NoSKL")] if static.endswith("_NoSKL") else None
    listed = {m for _t, ms in nodes for m in ms}
    if twin and twin in listed:
        head, basis = twin, "named in the variant's own model list beside its static copy"
    elif by_type:
        head, basis = by_type, "head collection model of the variant's head model type"
    else:
        return None
    return {
        "head": head,
        "static": static,
        "head_model_type": typ,
        "head_model_type_name": HEAD_MODEL_TYPES.get(typ),
        "head_by_type": by_type,
        "basis": basis,
        "texture_sheets": sheets.get(typ, []) if head == by_type else [],
    }


# ------------------------------------------------------------ texture sheets
# A Texture asset holds one or more TextureSheets.  Each has a `name`, a 64-bit
# `uniqueID` and eight "<layer>MapOverride" strings; a sheet with an override
# draws that OTHER texture's layer in place of its own.  A collection node picks
# the sheet by id in its textureSheetsDescription (BaseModel 0x49f95e / 0x4a544a).
# Measured: bikers/textures/head.bmp has the sheets "default" and "Goatee";
# Goatee's diffuseMapOverride is bikers/textures/head02.bmp, and its uniqueID is
# the one ThugFace's LARGE_HEAD_GOATEE node names for Large_Head_1.
SHEET_OVERRIDES = {
    "diffuseMapOverride": "diffuse",
    "normalMapOverride": "normal",
    "specularMapOverride": "spec",
    "specSizeMapOverride": "specSize",
    "glowMapOverride": "glow",
    "heightMapOverride": "height",
    "fallOffMapOverride": "fallOff",
    "ambOccMapOverride": "ambOcc",
}
_T_STRING = 0x144B7B5D  # property type hashes as they stand in a Texture header
_T_ID = 0xEDEF427C


def texture_sheets(header, order="<"):
    """[{name, unique_id, overrides {layer: asset path}}] of a Texture header, in
    file order.  Property records are [salt u32][key hash u32][type hash u32]
    [payload dwords u32][payload]; the salt is the same for all records of one
    sheet.  A string payload is [dwords u32][bytes, NUL padded]; a uniqueID
    payload is the id's high dword, then its low dword."""
    import struct

    import kapow_props

    keys = {kapow_props.name_hash(k): v for k, v in SHEET_OVERRIDES.items()}
    k_name, k_id = kapow_props.name_hash("name"), kapow_props.name_hash("uniqueID")
    sheets, n = {}, len(header)
    for o in range(4, n - 16):
        key, typ, cnt = struct.unpack_from(order + "III", header, o)
        if typ == _T_ID and key == k_id and cnt == 2 and o + 20 <= n:
            salt = struct.unpack_from(order + "I", header, o - 4)[0]
            hi, lo = struct.unpack_from(order + "II", header, o + 12)
            sheets.setdefault(salt, {"overrides": {}})["unique_id"] = (hi << 32) | lo
        elif typ == _T_STRING and (key == k_name or key in keys) and 2 <= cnt < 256:
            if o + 12 + 4 * cnt > n:
                continue
            salt = struct.unpack_from(order + "I", header, o - 4)[0]
            raw = header[o + 16 : o + 12 + 4 * cnt].split(b"\0", 1)[0]
            text = raw.decode("latin-1")
            sh = sheets.setdefault(salt, {"overrides": {}})
            if key == k_name:
                sh["name"] = text
            elif text:
                sh["overrides"][keys[key]] = text
    return [
        dict(name=v.get("name"), unique_id=v.get("unique_id"), overrides=v["overrides"])
        for v in sheets.values()
        if "unique_id" in v
    ]


def sheet_records(description):
    """textureSheetsDescription -> [{slot, pivot, lod, path, sheet_id}]: the records of
    characters_export.sheet_records (versions "2," and "1,"; lod 0 in version 1)."""
    import characters_export

    return [
        {"slot": s, "pivot": p, "lod": lod, "path": path, "sheet_id": i}
        for s, p, lod, path, i in characters_export.sheet_records(description)
    ]


def sheet_overrides(extract_out, records):
    """{texture asset path (lower case): {sheet, unique_id, overrides}} for the
    records whose sheet replaces a layer.  Reads the Texture headers under
    <extract_out>/extracted; a texture whose header is missing, or whose sheets
    do not include the id, is left alone."""
    out = {}
    import characters_export

    for r in records or []:
        rel = [x for x in r["path"].replace("\\", "/").split("/") if x]
        f = characters_export._asset_file(extract_out, rel)  # letter case as the engine
        try:
            with open(f, "rb") as fh:
                sheets = texture_sheets(fh.read())
        except OSError:
            continue
        for sh in sheets:
            if sh["unique_id"] == r["sheet_id"] and sh["overrides"]:
                out["/".join(rel).lower()] = {
                    "sheet": sh["name"],
                    "unique_id": sh["unique_id"],
                    "overrides": sh["overrides"],
                }
    return out


# ------------------------------------------------------------------ switches
RULES = ("engine", "legacy")


def rule(value=None):
    """The face rule in force: `value`, else $WATCHMEN_FACE_RULE, else "engine".
    "legacy" = toolkit 1.3.0 (pose picked from the clip name, synthetic blinks,
    no face rig on the Gimp / KnotTop characters)."""
    v = value or os.environ.get("WATCHMEN_FACE_RULE") or "engine"
    if v not in RULES:
        raise ValueError("face rule must be one of %s, not %r" % (", ".join(RULES), v))
    return v


def idle_enabled(value=None):
    """Bake the seeded idle cycle into IDLE segments?  `value`, else
    $WATCHMEN_FACE_IDLE ("0" = off), else on."""
    if value is not None:
        return bool(value)
    return os.environ.get("WATCHMEN_FACE_IDLE", "1") not in ("0", "off", "false", "no")
