#!/usr/bin/env python3
"""anim_meta -- the game's own animation metadata, joined per clip and per pair.

Everything here is read from shipped game data (AnimationClass fragments and
the .animation clip headers/root tracks); nothing is inferred from clip names.

What it recovers
----------------
* states   every AnimationStateWM of every AnimationClass: its clips, loop
           flag, start play position, impact settings and its play-position
           EVENTS (hit / grab / kill-partner / camera-cut ... with the play
           position each fires at).
* pairs    which clip plays against which.  A "master" state names the slave
           state it drives through its `Master of` property (m_imasterof); the
           partner class files that slave under its `SlaveStates` folder with
           the same id (m_istategroupid on a group, m_istateid on a state), and
           picks the child whose criteria accept the master's character type.
* placement where the two actors of a pair stand.  It IS in the clips: every
           clip keys an absolute `GamePivot` root track, and a paired clip's
           two halves are authored in one shared scene.  See PLACEMENT below.

PLACEMENT (engine rule read from the executable 2026-10-02, and measured)
------------------------------------------------------------------------
  * The body joints are keyed RELATIVE to GamePivot (GamePivot sits 1.0 m above
    the ground in every skeleton; lowest body joint + GamePivot.y == 0.00).
  * In absolute mode every actor moves as
        pos(t) = start_pos + R(start_orient) * (GamePivot(t) - GamePivot(0))
    (CollisionCapsuleNode.command_absolute_update 0x67f7b0).
  * The partner's start is set from the master (CharacterRoot.StateActive
    0x6b9035-0x6b94e9): position = the master's `interact` track at t=0, in the
    master's frame; orientation = the master's turned 180 degrees about +Y (a
    literal -pi/2 half-angle constant at 0x9e8440).  If interact(0) is exactly
    zero the engine uses the offset (0.11, 0.04, 1.12).
  * Data cross-check over 141 equal-duration clip pairs: placed this way the
    skeletons touch (mean closest approach 0.19 m vs 0.49-0.69 m for 0/90/270
    degrees), and in 123 the partner clip's own GamePivot start is on the
    marker to under 5 cm.  Each pair carries its `check` and a `confidence`.

FORMAT 2 (2026-10-02, findings/sync.md, enums.md, events.md, placement.md)
--------------------------------------------------------------------------
  * names come from the executable's own enum tables (engine_enums.json):
    events, criteria kinds and variables, model/weapon types, special handling.
  * criteria: enum variable 11 is OPPONENT_MODEL_TYPE; an ENUM criterion reads
    only m_ianimationenum / m_ianimationenumvalue (AnimationCriteriaMet
    0x5c5781), never m_ianimationvalue.
  * events carry their trigger kind (PLAY_POS / ENTER_STATE / LEAVE_STATE /
    TOTAL_PLAY_TIME); a TOTAL_PLAY_TIME event's m_nplaypos is SECONDS.
  * every pair has a `timeline` (when the partner is anchored and released)
    and its `weapons`; every class lists its `transitions` with sync markers.
"""

import glob
import json
import math
import os
import re
import struct
import sys

import anim_state_machine as asm
import engine_enums as ee
import frame as _frame
import kapow_json as _kj

FORMAT = "watchmen-anim-meta/2"
# Content revision of the table (top-level "revision").  The format strings name
# the layout; this number names what the build puts into it.  A resumed character
# export rebuilds a cached anim_meta.json whose revision is missing or different
# (characters_export.anim_meta_is_current), so a table from before a rule was
# added or corrected is never reused.  Raise it with every change of content.
REVISION = 5

# Engine rules (criteria evaluation, event triggers, sync markers, start
# position, fragment splicing, reference resolution) live in anim_state_machine;
# this module only turns them into records.
_CRIT_VALUE, _CRIT_ACTION = asm.CRIT_VALUE, asm.CRIT_ACTION
_CRIT_ENUM, _CRIT_EVENT = asm.CRIT_ENUM, asm.CRIT_EVENT
_CRIT_ANY, _CRIT_ALL = asm.CRIT_ANY_OF, asm.CRIT_ALL_OF
_CRIT_INTERVAL = (  # kinds that test min/max (MathLib.InsideInterval 0x77aa25)
    asm.CRIT_VALUE,
    asm.CRIT_PLAY_TIME,
    asm.CRIT_PLAY_POS,
    asm.CRIT_REV_PP,
    asm.CRIT_OVERLAY_PP,
    asm.CRIT_REV_OVERLAY_PP,
)
# ANIMATION_ENUM variables (criteria m_ianimationenum).  11 is the OPPONENT's
# model type -- what format 1 called "character type".  An ENUM criterion
# compares GetAnimationEnum(m_ianimationenum) with m_ianimationenumvalue and
# reads nothing else (0x5c5781, branch kind == 2): m_ianimationvalue is a
# leftover of the editor's Value box and does NOT select whose type is tested.
VAR_WEAPON, VAR_OPPONENT_MODEL, VAR_OPPONENT_WEAPON = 5, 11, 12
_ENUM_CHARTYPE = VAR_OPPONENT_MODEL  # format-1 name, kept for callers
# hero classes carry no AnimationClassWM node, so their model type comes from
# the class name (ids from the exe's OPPONENT_MODEL_TYPE family).
_HERO_TYPE_LABEL = {"rorschach": "RORSCHACH", "niteowl": "NITE_OWL"}
_WEAPON_LABELS = ("UNARMED", "BASH_1H", "BASH_2H")
# ANIMATION_EVENT ids used by the pair timeline, ANIMATION_EVENT_TYPES triggers
EV_LEAVE_ABSOLUTE_MODE, EV_ABSOLUTE_GOTO_TARGET_POS = 19, 28
TRIG_PLAY_POS, TRIG_ENTER_STATE = asm.EV_PLAY_POS, asm.EV_ENTER_STATE
TRIG_LEAVE_STATE, TRIG_TOTAL_PLAY_TIME = asm.EV_LEAVE_STATE, asm.EV_TOTAL_PLAY_TIME


# ------------------------------------------------------------------ helpers
def _label(node):
    s = (node.name or "").strip("{}").strip()
    return s[len("criteria: ") :] if s.startswith("criteria: ") else s


def _walk(n, out):
    out.append(n)
    for c in n.children:
        _walk(c, out)
    return out


def _crit_nodes(n):
    """The criteria of a state / group / transition (asm.criteria_of: filed
    directly under the node or in a folder of it, whatever the folder is called)."""
    return asm.criteria_of(n)


def _crit_text(k):
    kids = [_crit_text(x) for x in k.children if x.cls == asm.CLS_CRIT]
    return _label(k) + ("(" + "|".join(kids) + ")" if kids else "")


def _is_enum_leaf(k, var):
    return (k.p("m_ianimationcriteria") or 0) == _CRIT_ENUM and (
        k.p("m_ianimationenum") or 0
    ) == var


def _accepts_env(k, env):
    """Does criteria node k hold when the enum variables are as in `env`
    ({variable id: value})?  None = no opinion (the criterion is about
    something else: another variable, a distance, an input, ...)."""
    return asm.criteria_partial(k, env)


def _accepts_enum(k, var, value):
    """Does criteria node k hold when enum variable `var` is `value`?"""
    return _accepts_env(k, {var: value})


def _accepts(k, chartype):
    """Does criteria node k accept a partner of model type `chartype`?"""
    return _accepts_enum(k, VAR_OPPONENT_MODEL, chartype)


def accepts_partner(node, chartype):
    """True unless one of node's criteria rules the partner's model type out."""
    return all(_accepts(k, chartype) is not False for k in _crit_nodes(node))


def _mentions_enum(k, var):
    if _is_enum_leaf(k, var):
        return True
    return any(_mentions_enum(x, var) for x in k.children if x.cls == asm.CLS_CRIT)


def _groups_of(node):
    """The state groups enclosing a state, innermost first."""
    out, n = [], node.parent
    while n is not None:
        if n.cls == asm.CLS_GROUP:
            out.append(n)
        n = n.parent
    return out


# ANIMATION_TYPE the game derives when a state is initialised
# (AnimationStateWM.initialize_external 0x5f0e63 -> DetermineAnimationType 0x5f277a);
# the rule itself lives in anim_state_machine, which combat_meta shares
_TYPE_BY_ACTION = asm.TYPE_BY_ACTION  # 0x5ebeb0
_criterion_type = asm.criterion_animation_type
determine_animation_type = asm.determine_animation_type
UPPER_DAMAGE_POSES = asm.UPPER_DAMAGE_POSES  # 0x5f0e63
ANIMATION_TYPE_BASIS = (
    "computed as initialize_external 0x5f0e63 does; that it runs for every state in the game"
    " is inferred"
)


def allowed_enum_names(node, var, with_groups=True, env=None):
    """Names of the values of enum variable `var` that node's criteria (and,
    with_groups, those of its enclosing state groups) leave possible; None when
    no criterion tests the variable.  env: other enum variables that are known
    ({id: value}, e.g. the opponent's model type)."""
    crits = list(_crit_nodes(node))
    if with_groups:
        for g in _groups_of(node):
            crits += _crit_nodes(g)
    crits = [k for k in crits if _mentions_enum(k, var)]
    fam = ee.family(ee.enum_variable_family(var) or "")
    if not crits or not fam:
        return None
    out = []
    for v in sorted(fam):
        e = dict(env or {})
        e[var] = v
        if all(_accepts_env(k, e) is not False for k in crits):
            out.append(fam[v])
    return out


def _interval(k):
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return v  # min/max may name an ANIMATION_VALUE instead of a number

    t = k.p("m_iintervaltype") or 0
    return {
        "type": ee.interval_type(t, "TYPE_%s" % t),
        "min": num(k.p("m_nintervalmin")),
        "max": num(k.p("m_nintervalmax")),
    }


def criteria_record(k):
    """One criterion as data, named from the exe enums (AnimationCriteriaMet
    0x5c5781 says which properties each kind reads)."""
    kind = k.p("m_ianimationcriteria") or 0
    rec = {
        "text": _crit_text(k),
        "kind": ee.name("ANIMATION_CRITERIA", kind, "KIND_%s" % kind),
        "kind_id": kind,
    }
    if k.p("m_tnot"):
        rec["not"] = True
    if k.p("m_tentryonly"):
        rec["entry_only"] = True
    if kind == _CRIT_VALUE:
        v = k.p("m_ianimationvalue") or 0
        rec["variable"] = ee.name("ANIMATION_VALUE", v, "VALUE_%s" % v)
        rec["variable_id"] = v
    elif kind == _CRIT_ACTION:
        a = k.p("m_ianimationaction") or 0
        rec["action"] = ee.name("CONTROL_ACTION_TYPES", a, "ACTION_%s" % a)
        rec["action_id"] = a
    elif kind == _CRIT_ENUM:
        var = k.p("m_ianimationenum") or 0
        val = ee.signed(k.p("m_ianimationenumvalue") or 0)
        fam = ee.enum_variable_family(var)
        rec["variable"] = ee.name("ANIMATION_ENUM", var, "ENUM_%s" % var)
        rec["variable_id"] = var
        rec["value"] = ee.name(fam, val, "VALUE_%s" % val) if fam else "VALUE_%s" % val
        rec["value_id"] = val
    elif kind == _CRIT_EVENT:
        e = k.p("m_ianimationevent") or 0
        rec["event"] = ee.name("ANIMATION_EVENT", e, "EVENT_%s" % e)
        rec["event_id"] = e
    if kind in _CRIT_INTERVAL:
        rec["interval"] = _interval(k)
    kids = [criteria_record(x) for x in k.children if x.cls == asm.CLS_CRIT]
    if kids:
        rec["children"] = kids
    return rec


def _clip_key(name):
    n = (name or "").strip()
    if n.lower().endswith(".animation"):
        n = n[: -len(".animation")]
    return n.strip()


_BLEND_POS = re.compile(r"^pos\s+[-+0-9.eE]+\s*,\s*")  # "{pos 0.5, CLIP.animation}"


def _slot_clip(s):
    """Clip name of a slot; slots of a blend tree are captioned with their
    position in the parent blend first."""
    return _clip_key(_BLEND_POS.sub("", _label(s)))


def _slots(state):
    """[(clip, weight, layer)] of a state, engine order."""
    return [x[:3] for x in _slot_rows(state)]


def _slot_rows(state):
    """[(clip, weight, layer, speedFactor, slot node, top blend)] of a state, engine
    order.  The top blend is the blend directly under the state that holds the slot (the
    node the state's layer list names, asm.layer_lists); for a slot of a nested blend it
    is the outermost blend above it."""
    top = {id(b) for b in asm._top_blends(state)}
    out = []
    for b in state.descend(asm.CLS_BLEND):
        t = b
        while t is not None and id(t) not in top and t is not state:
            t = t.parent
        if t is None or t is state:
            t = b
        for s in b.kids(asm.CLS_SLOT):
            out.append((_slot_clip(s), s.p("m_nweight", 1.0), _label(b), asm.slot_speed(s), s, t))
    return out


def _layer_fields(b):
    """Layer facts of a top blend `b` for a state clip row (SetupNewPage 0x5b7788,
    UpdatePagePlayPos 0x5b61b9): its list index, the additive flag, the forced play
    position and the layer weight control (left out when the control is 0 = NONE)."""
    out = {
        "layer_index": int(b.p("m_ilayerindex", 0) or 0),
        "additive": bool(b.p("m_tlayeradditive", False)),
        "force_playpos_1": bool(b.p("m_tforcedpos", False)),
    }
    v = b.p("m_ilayerweightctrlparam") or 0
    if v:
        out["layer_weight"] = {
            "value": ee.name("ANIMATION_VALUE", v, "VALUE_%s" % v),
            "start": b.p("m_nlayerweightintervalstart", 0.0),
            "end": b.p("m_nlayerweightintervalend", 0.0),
        }
    return out


def layer_use(rows):
    """{clip: sorted subset of ["additive", "base", "upper"]} from the clip rows of one
    state: "additive" = in an additive blend; "base" = in a non-additive blend of the
    state's lowest layer index; "upper" = any other."""
    low = min((r["layer_index"] for r in rows), default=0)
    out = {}
    for r in rows:
        if not r.get("clip"):
            continue
        use = "additive" if r["additive"] else "base" if r["layer_index"] == low else "upper"
        out.setdefault(r["clip"], set()).add(use)
    return {c: sorted(u) for c, u in out.items()}


def state_speed(state):
    """(rate factor, basis) of a state: asm.state_speed with the main clip's slot
    as the representative when the first layer's slots differ in speed."""
    main = _main_clip(state)
    slot = next((r[4] for r in _slot_rows(state) if r[0] == main), None)
    return asm.state_speed(state, slot)


def _main_clip(state):
    """The full-body clip of a state: the last slot that is not an arm-layer
    overlay (weapon-hold layers are listed first and are partial-body)."""
    sl = [c for c, _w, _l in _slots(state) if c and "arm_layer" not in c.lower()]
    return sl[-1] if sl else None


def _event_label(e):
    """The ANIMATION_EVENT name written in an event node's caption, or None.

    Two caption styles ship: "{event KILL_ANIMATION_PARTNER at pos 0.7}" and
    "{PLAY_POS [0.33]: IMPACT}".  Many events have no caption at all.
    """
    lab = _label(e)
    if lab.startswith("event ") and len(lab.split()) > 1:
        nm = lab.split()[1]
    elif "]: " in lab:
        nm = lab.split("]: ", 1)[1].split()[0] if lab.split("]: ", 1)[1].split() else ""
    else:
        return None
    return nm if nm and nm.isupper() else None


def learn_event_names(nodes):
    """{event id: name} from every captioned event (majority vote per id), so
    uncaptioned events of the same id get their name too."""
    votes = {}
    for n in nodes:
        if n.cls == asm.CLS_EVENT:
            nm = _event_label(n)
            if nm is not None:
                d = votes.setdefault(n.p("m_ianimationevent"), {})
                d[nm] = d.get(nm, 0) + 1
    return {k: sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for k, v in votes.items()}


def event_name_check(nodes):
    """Caption-learned event names against the exe's ANIMATION_EVENT family:
    {'agree': n ids, 'conflicts': [...], 'exe_only': [ids no caption names]}."""
    votes = {}
    for n in nodes:
        if n.cls == asm.CLS_EVENT:
            nm = _event_label(n)
            if nm is not None:
                d = votes.setdefault(n.p("m_ianimationevent"), {})
                d[nm] = d.get(nm, 0) + 1
    exe = ee.family("ANIMATION_EVENT")
    conflicts, agree = [], 0
    for eid in sorted(votes, key=lambda x: x or 0):
        if all(nm == exe.get(eid) for nm in votes[eid]):
            agree += 1
        for nm, uses in sorted(votes[eid].items()):
            if nm != exe.get(eid):
                conflicts.append(
                    {"event_id": eid, "exe": exe.get(eid), "caption": nm, "uses": uses}
                )
    return {
        "agree": agree,
        "conflicts": conflicts,
        "exe_only": [k for k in sorted(exe) if k not in votes],
    }


def _event_sort_key(x):
    # ENTER_STATE first, LEAVE_STATE last, the rest in firing order: seconds since
    # entry, else (no duration known) the stored position; events that never fire
    # on this entry go last, by their position on the clip
    order = {"ENTER_STATE": 0, "LEAVE_STATE": 3}.get(x.get("trigger"), 1)
    t = x.get("play_time_s")
    if t is None and order == 1:
        if x.get("fires_first_pass") is False:
            order = 2
        t = x.get("time_s")
        if t is None:
            t = x.get("playpos")
    return (order, 0.0 if t is None else t, x["name"])


def _events(state, names=None, duration=None, basis=None, speed=None, start=None):
    """Event records of a state.  duration: seconds of the state's clip (None =
    unknown); basis: how that duration was obtained; speed: the state's rate
    factor (state_speed; None = 1); start: the play position the state is
    entered at (None = its own m_nstartplaypos, the engine's default; pass
    another value for an entry through an override / sync-marker transition).

    CheckPlayPosEvents 0x5b51f3: PLAY_POS compares m_nplaypos with the page's
    normalised play position, TOTAL_PLAY_TIME with the page's seconds played;
    ENTER_STATE / LEAVE_STATE events are sent by SetupNewPage 0x5b7788 /
    UpdatePagePlayPos 0x5b56a9 when the state is entered / left."""
    out = []
    default = float(state.p("m_nstartplaypos", 0.0) or 0.0)
    start_basis = "state_default" if start is None or start == default else "given"
    start = default if start is None else float(start)
    loop = bool(state.p("m_tislooping"))
    for e in asm.state_events(state):
        eid = e.p("m_ianimationevent")
        cap = _event_label(e)
        nm = ee.name("ANIMATION_EVENT", eid) or cap or (names or {}).get(eid) or "EVENT_%s" % eid
        trig = asm.event_trigger(e)
        raw = round(asm.event_at(e), 4)
        pp, ts, pt = asm.event_timing(trig, raw, duration, speed or 1.0, start, loop)
        rec = {
            "name": nm,
            "playpos": None if pp is None else round(pp, 4),
            "on_enter": trig == TRIG_ENTER_STATE,
            "event_id": eid,
            "value": e.p("m_nvalue"),
            "trigger": ee.name("ANIMATION_EVENT_TYPES", trig, "TRIGGER_%s" % trig),
            "trigger_id": trig,
            "raw": raw,
            "time_s": None if ts is None else round(ts, 4),
            "play_time_s": None if pt is None else round(pt, 4),
        }
        if trig != TRIG_LEAVE_STATE:
            # times are for an entry at this play position (TransitToState 0x5b4a31)
            rec["start_playpos"] = round(start, 4)
            rec["start_basis"] = start_basis
        if trig == TRIG_ENTER_STATE:
            rec["time_unit"] = "state_enter"
        elif trig == TRIG_LEAVE_STATE:
            rec.update(time_unit="state_leave", on_leave=True)
        elif trig == TRIG_TOTAL_PLAY_TIME:
            rec["time_unit"] = "seconds"
            if pp is not None:
                rec["playpos_basis"] = (
                    ("start_playpos + " if start else "")
                    + ("seconds / " if not speed or speed == 1.0 else "seconds * speed / ")
                    + (basis or "duration")
                )
        else:
            rec["time_unit"] = "playpos"
            if ts is not None:
                rec["time_basis"] = "playpos * " + (basis or "duration")
            if asm.event_prelatched(e, start):
                # at or before the start position: created already fired
                # (SetupNewPage 0x5b8f16); it fires after a loop wrap (play_time_s
                # is then that moment), never on a non-looping state
                rec["fires_first_pass"] = False
        if cap and cap != nm:
            rec["caption_name"] = cap
        src = event_source(e)
        if src:  # an event of a spliced SoundEvents/SE_<clip>.fragment list
            rec["source"] = src
        rec.update(_event_args(e, eid))
        out.append(rec)
    out.sort(key=_event_sort_key)
    return out


# ANIMATION_EVENT ids whose arguments name a sound (CharacterRootLogic
# .command_animation_event_received: SOUND 0x6aba76, SPEAK 0x6a9f30)
EV_SOUND, EV_SPEAK = 9, 37


def _event_args(e, eid):
    """The event's own arguments, under their property names.  `_etarget00`:
    the Entity it targets (SOUND: the SoundDef) as stored -- {'ref': id} names
    a node of the same fragment, {'xref': [instance, ..., id]} one of another
    (sound_meta resolves both).  `m_ivalue00`: SOUND 0 = at the world position,
    1 = follows the character; SPEAK = the speak id.  `m_ttruth1`: SOUND = the
    speak flag (START_SPEAK to the face), SPEAK = stop the current line first.
    Always present on SOUND / SPEAK events, elsewhere only when set."""
    out = {}
    tgt = e.p("_etarget00")
    if isinstance(tgt, dict) and (tgt.get("ref") is not None or tgt.get("xref")):
        out["_etarget00"] = tgt
    elif eid == EV_SOUND:
        out["_etarget00"] = None
    v, t = e.p("m_ivalue00"), e.p("m_ttruth1")
    if eid in (EV_SOUND, EV_SPEAK) or v:
        out["m_ivalue00"] = v
    if eid in (EV_SOUND, EV_SPEAK) or t:
        out["m_ttruth1"] = bool(t)
    return out


def _path(n):
    p = []
    while n is not None:
        if n.cls in (asm.CLS_GROUP, asm.CLS_STATE, asm.CLS_CLASS) or n.name == "SlaveStates":
            p.append(n.name)
        n = n.parent
    return "/".join(reversed(p))


# ------------------------------------------------------------------ classes
def find_class_fragments(extract_out):
    """{class name: path} for every body AnimationClass fragment.  The face
    classes (`*Face`) are read by face_rule.find_face_fragments: they go into
    the table's `face` block, not into `classes`."""
    root = os.path.join(extract_out, "extracted")
    hits = set()
    for ext in (".fragment", ".fragment.json"):  # the JSON alone is enough
        for f in _kj.glob_tree(root, "CharacterAnimation", "AnimationClass*" + ext):
            hits.add(f[: -len(".json")] if f.endswith(".json") else f)
    out = {}
    for f in sorted(hits):
        nm = os.path.basename(f)[len("AnimationClass") : -len(".fragment")]
        if nm.lower().endswith("face"):
            continue
        out[nm] = f
    return out


CLS_FRAGMENT_NODE = "FragmentNode"


def _class_hosts(n, _asset):
    """Which nodes of an animation class instance a fragment: the state groups, and
    the plain FragmentNodes a state holds (in shipped data all of them are
    `SoundEvents/SE_<clip>.fragment` lists under a state or its `Events` folder;
    FragmentNode::SetFragmentAssetByName 0x498db7 applies the fragment when the
    property is set, so its events are the state's own)."""
    return n.cls in (asm.CLS_GROUP, CLS_FRAGMENT_NODE)


def load_class_tree(path, _open=()):
    """Roots of one AnimationClass fragment with every nested fragment spliced
    in whole (asm.load_tree; kept as a name for format-2 callers): the state-group
    fragments and the event-list fragments of the states."""
    return asm.load_tree(path, True, _open, hosts=_class_hosts)


def event_source(e):
    """Base name of the spliced event-list fragment an event node was read from
    ("SE_<clip>.fragment"), or None for an event stored in the class tree itself."""
    n = e
    while n is not None and n.cls not in (asm.CLS_STATE, asm.CLS_GROUP, asm.CLS_CLASS):
        if n.frag is not None and n.parent is not None and n.parent.cls == CLS_FRAGMENT_NODE:
            return n.frag.replace("\\", "/").rsplit("/", 1)[-1]
        n = n.parent
    return None


def missing_event_lists(nodes):
    """Asset names of the FragmentNodes of a class tree whose fragment file was not
    found, sorted, with repeats.  A fragment that exists but holds no node (the 17-byte
    `SE_CounterAttackGroup.fragment`) is not missing."""
    return sorted(
        n.p("assetName")
        for n in nodes
        if n.cls == CLS_FRAGMENT_NODE
        and isinstance(n.p("assetName"), str)
        and not getattr(n, "spliced", False)
    )


def load_classes(extract_out):
    """{class: {'fragment', 'nodes', 'chartype', 'chartype_label'}}."""
    classes = {}
    # model type id -> name: AnimationClassWM.m_ianimationmodeltype is an
    # OPPONENT_MODEL_TYPE dropdown (property registration, items=...)
    labels = {k: v for k, v in ee.family("OPPONENT_MODEL_TYPE").items() if k}
    for nm, f in find_class_fragments(extract_out).items():
        nodes = []
        for r in load_class_tree(f):
            _walk(r, nodes)
        ct = None
        for k in nodes:
            if k.cls == asm.CLS_CLASS and k.p("m_ianimationmodeltype") is not None:
                ct = k.p("m_ianimationmodeltype")
                break
        classes[nm] = {"fragment": f, "nodes": nodes, "chartype": ct}
    inv = {v: k for k, v in labels.items()}
    for nm, c in classes.items():
        if c["chartype"] is None:
            c["chartype"] = inv.get(_HERO_TYPE_LABEL.get(nm.lower()))
        c["chartype_label"] = labels.get(c["chartype"])
    return classes


def _named(fam, value):
    v = ee.signed(value or 0)
    return {"id": v, "name": ee.name(fam, v, "%s_%s" % (fam, v))}


def state_duration(s, fact=None):
    """(seconds, basis) one pass of the state takes at speed factor 1, from its
    clips' headers.  fact: clip name -> clip_facts() or None.  The engine's
    rate is the weight-blended sum of 1/duration over the slots of the state's
    first layer (SetAllSlotBlends 0x5b4ef7), so the number is exact only when
    all of the state's clips have one length."""
    if fact is None:
        return None, None
    durs, main = [], None
    for c, _w, _l in _slots(s):
        f = fact(c) if c else None
        if f and f.get("duration_s"):
            durs.append(f["duration_s"])
            if c == _main_clip(s):
                main = f["duration_s"]
    if not durs:
        return None, None
    if max(durs) - min(durs) < 1e-4:
        return durs[0], "clip duration"
    return (main or durs[-1]), "main clip duration (the state's clips differ in length)"


def state_record(s, event_names=None, fact=None):
    """JSON-able facts of one AnimationStateWM.  fact: optional clip name ->
    clip_facts() lookup, used to give event times in both units."""
    P = s.p
    cn = _crit_nodes(s)
    crit = [_crit_text(k) for k in cn]
    dur, basis = state_duration(s, fact)
    speed, speed_basis = state_speed(s)
    rec = {
        "name": s.name,
        "path": _path(s),
        "state_id": P("m_istateid"),
        "master_of": P("m_imasterof") or None,
        "clips": [
            dict(
                {
                    "clip": c,
                    "weight": w,
                    "layer": l,
                    "speed": sp,
                    "blend_position": n.p("m_nparentblendposition"),
                },
                **_layer_fields(b),
            )
            for c, w, l, sp, n, b in _slot_rows(s)
        ],
        "main_clip": _main_clip(s),
        "loop": bool(P("m_tislooping")),
        "walk_cycle": bool(P("m_tiswalkcycle")),
        "start_playpos": P("m_nstartplaypos"),
        "ease_in_s": P("m_neaseinduration"),
        "absolute": bool(P("m_tisabsoluteanimation")),
        "defines_movement": bool(P("m_tanimationdefinesmovement")),
        "defines_rotation": bool(P("m_tanimationdefinesrotation")),
        "attack_state": bool(P("m_tisattackstate")),
        "special_handling": _named("ANIMATION_SPECIAL_CASE", P("m_ispecialhandling")),
        "animation_type": _named("ANIMATION_TYPE", determine_animation_type(s)),
        "animation_type_stored": _named("ANIMATION_TYPE", P("m_ianimationtype")),
        "animation_type_basis": ANIMATION_TYPE_BASIS,
        "duration_s": dur,
        "speed": speed,
        "criteria": crit,
        "criteria_tree": [criteria_record(k) for k in cn],
        "weapon": sorted(
            {w for c in crit for w in _WEAPON_LABELS if w in c and "NOT " + w not in c}
        ),
        "start_basis": "state_default",
        "events": _events(s, event_names, dur, basis, speed),
    }
    if speed_basis and speed_basis != "slot speedFactor":
        rec["speed_basis"] = speed_basis
    if P("m_inumberofimpacts") or P("m_nimpacttime"):
        rec["impact"] = {
            "count": P("m_inumberofimpacts"),
            "time_s": P("m_nimpacttime"),
            "distance_m": P("m_nimpactdistance"),
            "position": P("m_vimpactpos"),
            "direction": P("m_vimpactdirection"),
            "damage_pose": P("m_idamagepose"),
            "damage_pose_name": ee.name("DAMAGE_POSE", P("m_idamagepose") or 0),
            "bone_id": P("m_iboneid"),
        }
    return rec


# -------------------------------------------------------------- transitions
def sync_markers(t):
    """Sorted [(local, remote)] of a transition (asm.marker_pairs: the engine's
    UpdateSuperSync 0x5fa582 list), rounded for the record."""
    return [(round(lo, 4), round(re_, 4)) for lo, re_ in asm.marker_pairs(t)]


def transition_start(rec, outgoing_playpos):
    """Start play position a transition record gives the target, or None when
    the transition has no opinion (the target then starts at the outgoing play
    position if both states are walk cycles, else at its own start_playpos).
    TransitionPlayPos 0x5ac1aa; clamps to the first / last remote marker."""
    st = rec.get("start") or {}
    if st.get("rule") == "override_playpos":
        return st["playpos"]
    if st.get("rule") != "sync_markers" or not st.get("markers"):
        return None
    return asm.map_markers(st["markers"], outgoing_playpos)


def transition_record(t, owner, byid, byname=None):
    """One AnimationTransitionWM as data (properties in docs/ANIMATION_META.md).
    byid: asm.node_index() of the class; byname is unused (format-2 signature)."""
    target = asm.resolve_ref(t, t.p("m_etostate"), byid)
    rec = {
        "owner": _path(owner),
        "owner_kind": _OWNERS.get(owner.cls, "state"),
        "name": t.name,
        "to": _path(target) if target is not None else None,
        "to_kind": (
            None if target is None else "group" if target.cls == asm.CLS_GROUP else "state"
        ),
    }
    if t.p("m_tfallback"):
        rec["fallback"] = True  # tried only in the fallback pass (0x5c6140)
    if not t.p("enabled", True):
        rec["enabled"] = False
    if t.p("m_toverrideeasein"):
        rec["ease_in_override_s"] = t.p("m_neaseinduration", 0.0)
    crit = [_crit_text(k) for k in _crit_nodes(t)]
    if crit:
        rec["criteria"] = crit
    if t.p("m_toverrideplaypos"):
        rec["start"] = {"rule": "override_playpos", "playpos": t.p("m_nplaypos", 0.0)}
    elif t.p("m_tsupersyncpos"):
        m = sync_markers(t)
        win = asm.markers_window(m)  # TransitionMet 0x5c5ea4
        rec["start"] = {
            "rule": "sync_markers",
            "markers": [list(x) for x in m],
            "gate": list(win) if win else None,
        }
    return rec


# a transition registers with the nearest typed ancestor, and only when that is
# a state or a state group (AnimationTransition.AddToClosestState)
_OWNERS = {asm.CLS_STATE: "state", asm.CLS_GROUP: "group"}


def _transitions(nodes):
    byid = asm.node_index(None, nodes)
    out = []
    for n in nodes:
        if n.cls in _OWNERS:
            for t in asm.transitions_of(n):
                out.append(transition_record(t, n, byid))
    out.sort(key=lambda r: (r["owner"], r["name"], r["to"] or ""))
    return out


# TransitToState 0x5b4a31 + SetupNewPage 0x5b7788, first match wins
TRANSITION_START_PRIORITY = asm.TRANSITION_START_PRIORITY


# -------------------------------------------------------------------- clips
def find_clips(extract_out):
    """{clip name: path}; names are stripped (some files end in ' .animation')."""
    root = os.path.join(extract_out, "extracted", "Animation")
    out = {}
    for f in sorted(glob.glob(os.path.join(root, "**", "*.animation"), recursive=True)):
        out.setdefault(_clip_key(os.path.basename(f)).lower(), f)
    return out


def _yaw_deg(q):
    """Heading of an XYZW quaternion that is (nearly) a pure yaw, else None.

    This is 2 * atan2(y, w) of the ENGINE quaternion.  The engine rotates a
    vector as conj(q) v q and the GLB stores the conjugate, so the value is
    MINUS the right-handed yaw of the GLB node's rotation (in either frame)."""
    x, y, z, w = (float(v) for v in q)
    if abs(x) + abs(z) > 0.05:
        return None
    a = math.degrees(2.0 * math.atan2(y, w))
    return round((a + 180.0) % 360.0 - 180.0, 2)


def clip_facts(path):
    """Header + root-track facts of one .animation file."""
    import bake_v4

    with open(path, "rb") as fh:
        h = fh.read()
    order = bake_v4._detect_clip_order(h)
    rate, dur, _z, keys, scale = struct.unpack_from(order + "2f3I", h, 0)
    tr = bake_v4.walk(h, order)
    out = {
        "file": path,
        "duration_s": round(float(dur), 5),
        "key_count": int(keys),
        "key_rate_hz": round(float(rate), 5),
        "frame_rate_scale": int(scale),  # 1/2/3 = FULL/HALF/THIRD of 30 fps
        "tracks": list(tr),
    }

    def root(name):
        t = tr.get(name)
        if t is None:
            return None
        q, p = t
        r = {
            "yaw_start_deg": _yaw_deg(q[0]),
            "yaw_end_deg": _yaw_deg(q[-1]),
            "rotation_keyed": len(q) > 1,
        }
        if p is not None:
            r["pos_start"] = [round(float(v), 4) for v in p[0]]
            r["pos_end"] = [round(float(v), 4) for v in p[-1]]
            r["position_keyed"] = len(p) > 1
        return r

    out["game_pivot"] = root("GamePivot")
    out["interact"] = root("interact")  # keyed LOCAL to GamePivot
    gp = tr.get("GamePivot")
    if gp is not None:  # private: per-key root motion for the pair timeline
        out["_gp_yaw_deg"] = _unwrap([_twist_deg(q) for q in gp[0]])
        if gp[1] is not None:
            out["_gp_pos"] = [[float(v) for v in p] for p in gp[1]]
    return out


def _twist_deg(q):
    """Rotation about +Y of an XYZW quaternion (its yaw twist), degrees."""
    return math.degrees(2.0 * math.atan2(float(q[1]), float(q[3])))


def _unwrap(deg):
    out = []
    for a in deg:
        if out:
            a = out[-1] + ((a - out[-1] + 180.0) % 360.0 - 180.0)
        out.append(a)
    return out


def _sample(series, u):
    """Linear sample of a per-key series at normalised time u (the engine's key
    index is (keys - 1) * t / duration, FUN_00591975)."""
    if len(series) == 1:
        return series[0]
    f = min(max(u, 0.0), 1.0) * (len(series) - 1)
    i = min(int(f), len(series) - 2)
    a, b, w = series[i], series[i + 1], f - i
    if isinstance(a, (list, tuple)):
        return [x + (y - x) * w for x, y in zip(a, b)]
    return a + (b - a) * w


# -------------------------------------------------------------------- pairs
# CharacterRoot.StateActive (0x6b9202): when the master clip's interact track is
# exactly (0,0,0) at t=0 the engine substitutes this offset (x, y, z).
ENGINE_DEFAULT_PARTNER_OFFSET = (0.11, 0.04, 1.12)


def _yaw_rot(deg, x, z):
    """(x, z) turned by `deg` about +Y in the right-handed sense (+Z towards +X).
    A yaw of this table (_yaw_deg) is the opposite turn: pass its negative."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return c * x + s * z, -s * x + c * z


def placement(m, v):
    """Where the partner starts and how its clip is turned, in the master's
    clip space.  m, v: clip_facts() of the master and the partner clip.
    Returns None when either clip has no positional GamePivot track.

    This is the engine's rule (CharacterRoot.StateActive 0x6b9035-0x6b94e9,
    read 2026-10-02; see docs/ANIMATION_META.md):

        partner start pos    = master node * (interact(0) - (GP_m(t) - GP_m(0)))
        partner start orient = yaw(180 deg) * master node orientation
        any actor, per frame : pos = start + R(start orient) * (GP(t) - GP(0))

    so the partner starts on the master's `interact` marker, turned 180 degrees,
    and plays its own GamePivot motion RELATIVE to its first key.  The values
    returned are those of t = 0 (the fixed marker); with a master that turns
    while the partner is anchored the engine's anchor leaves it (pair_timeline:
    anchor_drift_if_master_turns_m).  The partner
    clip's absolute GamePivot start is never read by the engine; it is reported
    under `check` because on most pairs it lands on the marker to the centimetre
    (the two halves were authored in one scene), which is an independent check.
    """
    mg, vg = m.get("game_pivot") or {}, v.get("game_pivot") or {}
    if "pos_start" not in mg or "pos_start" not in vg:
        return None
    mx, _my, mz = mg["pos_start"]
    vx, _vy, vz = vg["pos_start"]
    myaw = mg.get("yaw_start_deg") or 0.0
    it = (m.get("interact") or {}).get("pos_start")
    authored = bool(it) and (abs(it[0]) + abs(it[1]) + abs(it[2])) > 1e-6
    ox, oz = (
        (it[0], it[2])
        if authored
        else (ENGINE_DEFAULT_PARTNER_OFFSET[0], ENGINE_DEFAULT_PARTNER_OFFSET[2])
    )
    if myaw:
        # The offset is in the master node's frame.  A root quaternion whose
        # _yaw_deg is a turns a vector by -a in the right-handed sense (engine
        # vectors rotate as conj(q) v q), so the turn is _yaw_rot(-a): this is
        # GamePivot(0) * interact(0) of the GLB hierarchy (data, 2026-10-05: 32
        # turned solo clips agree to 0.1 mm, the other sign is off by up to
        # 1.66 m).  That the master's node is the GamePivot frame is READ on PC
        # (2026-10-05): the node orientation is the heading quaternion of
        # m_nfaceheading, set inline each frame (CharacterVisual
        # .UpdateAnimPoseAndCloth 0x6b015d); the heading integrates minus the
        # GamePivot twist rate and the velocity is GamePivot-local
        # (UpdatePagePlayPos 0x5b56a9, CharacterRoot.StateActive resume
        # 0x56-0x58).  No shipped pair has a master turned at t = 0, so this
        # branch never runs on the game's data.
        ox, oz = _yaw_rot(-myaw, ox, oz)
    px, pz = mx + ox, mz + oz
    # the partner clip's own start in the partner's start frame: turned by
    # partner_yaw = 180 + myaw about +Y (exactly 180 on every shipped pair)
    gx, gz = _yaw_rot(-(180.0 + myaw), vx, vz) if myaw else (-vx, -vz)
    out = {
        "space": "master clip space",
        "source": (
            "interact marker" if authored else "engine default offset (interact not authored)"
        ),
        "master_start_xz": [round(mx, 4), round(mz, 4)],
        "partner_start_xz": [round(px, 4), round(pz, 4)],
        "partner_offset_xz": [round(px - mx, 4), round(pz - mz, 4)],
        "partner_distance_m": round(math.hypot(px - mx, pz - mz), 4),
        # yaw of the partner's start frame: turn the partner clip by this
        "partner_yaw_deg": round(((180.0 + myaw) + 180.0) % 360.0 - 180.0, 2),
        # = partner_start - R(partner_yaw) * GamePivot_p(0): add to the turned partner clip
        "partner_origin_shift_xz": [round(px - gx, 4), round(pz - gz, 4)],
    }
    out["check"] = {
        "partner_game_pivot_start_xz": [round(gx, 4), round(gz, 4)],
        "agreement_m": round(math.hypot(gx - px, gz - pz), 4),
    }
    return out


def _confidence(pl, same_duration, contact):
    """How well the DATA backs the engine's placement for this pair:
    verified   the partner clip's own GamePivot start lands on the engine's
               start (< 5 cm) and the halves are the same length
    plausible  it does not, but the placed skeletons do meet (< 0.25 m)
    unverified neither
    none       a clip has no GamePivot position track"""
    if pl is None:
        return "none"
    a = pl["check"].get("agreement_m")
    c = None if contact is None else contact.get("closest_m")
    if a is not None and a < 0.05 and same_duration:
        return "verified"
    if c is not None and c < 0.25:
        return "plausible"
    return "unverified"


# A master GamePivot turn above this inside the partner's anchored window
# makes the anchor rule unverified (see pair_timeline).
ANCHOR_YAW_TOLERANCE_DEG = 2.0
# OPPONENT_WEAPON_TYPE item -> the WEAPON_ANIMATION_TYPE item it corresponds to
_OPPONENT_WEAPON_AS_OWN = {"NONE": "UNARMED", "BASH_1H": "BASH_1H", "BASH_2H": "BASH_2H"}


def _pair_event(events, eid, rate, start=0.0, own_start=0.0):
    """The earliest event of id `eid` that fires on a slave-locked partner, as
    {"time_s": seconds of play time, "playpos", "trigger"}.

    rate       play position per second of the MASTER (speed / clip duration)
    start      play position the master (hence the pair) starts at
    own_start  the partner state's own start position: its page is set up there
               (goto_slave_mode -> ForceToState with play position -1), which
               decides what is pre-latched, before the master's position is
               copied into it
    The partner's play position is the master's, start + t * rate.  A PLAY_POS
    event at r fires at (r - start) / rate seconds (at once when r <= start),
    never when r <= own_start (pre-latched on a non-looping state); a
    TOTAL_PLAY_TIME event after its seconds, at play position start + t * rate.
    Without a rate the event's own numbers are used."""
    best = None
    for e in events:
        if e.get("event_id") != eid:
            continue
        trig, raw = e.get("trigger_id"), e.get("raw")
        t, pp = e.get("play_time_s", e.get("time_s")), e.get("playpos")
        if rate and raw is not None:
            if trig == TRIG_PLAY_POS:
                if raw <= own_start:
                    continue  # created already fired: never fires
                t, pp = max(0.0, (raw - start) / rate), max(raw, start)
            elif trig == TRIG_TOTAL_PLAY_TIME:
                pp = start + raw * rate
                t, pp = raw, (pp if pp <= 1.0 + 1e-6 else None)
        elif trig == TRIG_PLAY_POS and e.get("fires_first_pass") is False:
            continue
        ref = {
            "time_s": None if t is None else round(t, 4),
            "playpos": None if pp is None else round(pp, 4),
            "trigger": e["trigger"],
        }
        if best is None or (
            ref["time_s"] is not None and (best["time_s"] is None or t < best["_t"])
        ):
            best = dict(ref, _t=t)
    if best is not None:
        best.pop("_t", None)
    return best


def _master_turn(mf, pl, t0, t1, t_ref=0.0):
    """(max |yaw(t) - yaw(0)| in degrees, anchor drift in metres) of the master's
    GamePivot for t in [t0, t1], seconds on the master's clip.

    The drift is the engine's departure from the fixed marker of placement():
    the anchored partner is rigid in the master NODE's frame, the node is the
    GamePivot frame (see placement), so in clip space

        anchor(u) = GP(u) + R(yaw(u)) * (I0 - (GP(u) - GP(0)))
        marker    = GP(0) + R(yaw(0)) * I0
        drift     = max |anchor(u) - marker|

    with I0 the UNTURNED interact offset and R(a) = _yaw_rot(-a).  Both the
    turn and the drift are measured from t = 0, where the offset is defined;
    t_ref (where the master's state starts) is accepted for older callers and
    not used."""
    yaw, pos, dur = mf.get("_gp_yaw_deg"), mf.get("_gp_pos"), mf.get("duration_s")
    if not yaw or not dur or t1 < t0:
        return None, None
    n = len(yaw)
    us = [t0 / dur, t1 / dur] + [i / (n - 1) for i in range(n) if n > 1]
    us = [u for u in us if t0 / dur - 1e-9 <= u <= t1 / dur + 1e-9]
    off = (pl or {}).get("partner_offset_xz")
    # the yaw placement() turned the offset by (0 for a start that is not a pure yaw)
    yaw0 = float((mf.get("game_pivot") or {}).get("yaw_start_deg") or 0.0)
    turn, drift = 0.0, 0.0 if (pos and off) else None
    if drift is not None:
        ix, iz = _yaw_rot(yaw0, off[0], off[1])  # I0: partner_offset = R(yaw0) * I0
    for u in us:
        a = _sample(yaw, u) - yaw[0]
        turn = max(turn, abs(a))
        if drift is not None:
            g = _sample(pos, u)
            dx, dz = g[0] - pos[0][0], g[2] - pos[0][2]
            rx, rz = _yaw_rot(-(yaw0 + a), ix - dx, iz - dz)
            drift = max(drift, math.hypot(dx + rx - off[0], dz + rz - off[1]))
    return round(turn, 2), (None if drift is None else round(drift, 3))


def pair_timeline(mrec, prec, mf=None, vf=None, pl=None, start=None, alternatives=None):
    """When the partner of a pair is anchored to the master and when it is let
    go, from the two state records (state_record) and clip facts.

    Read from code: a master is not an absolute animation and is never moved to
    the partner (SetupNewPage 0x5b7788).  The master's page starts at the
    master state's start position (TransitToState 0x5b4a31; `start` overrides
    it for an entry through an override / sync-marker transition, and
    `alternatives` lists such entries -- no shipped master state has one).  The
    master hands the partner its first animation source (goto_slave_mode
    0x5b32a2 stores it in the controller's _eslaveof) and forces it into the
    slave state with play position -1, i.e. the partner's page is set up at the
    partner state's OWN start position; from then on the partner's play
    position is COPIED from the master's every frame until that reaches 1
    (UpdatePagePlayPos 0x5b5756-0x5b57d0).  So the pair is locked in play
    position: playpos(t) = master start + t * speed / clip duration.
    The partner enters absolute mode at its OWN pose and its visible node HOLDS
    that entry pose: it gets no absolute update until its capsule flag +0xb8 is
    set (UpdateAnimPoseAndCloth 0x6b015d draws the absolute target, which only
    the non-slave attempt_move 0x67f727 and the master's DccJoint, gated on the
    flag by DccUpdate 0x680654, write).  The flag is set from the start when
    Special handling is NORMAL (0), otherwise by its ABSOLUTE_GOTO_TARGET_POS
    event (0x6a9dca); the anchor is then eased in from the entry pose over the
    blend time, which is the page's ease-in = the state's ease_in_s
    (goto_slave_mode -> ForceToState with ease -1).  While anchored the partner
    is rigid in the master NODE's frame (anchor_frame), so it swings with a
    master that turns: `placement` is the fixed marker of t = 0 and
    anchor_drift_if_master_turns_m the engine's departure from it.
    LEAVE_ABSOLUTE_MODE (0x6ac8de) returns it to normal physics, position kept.
    Inferred: both states start in the same frame.

    Times are seconds of play time since both states were entered (controller
    speed factors 1); `playpos` is the shared play position -- multiply by a
    clip's duration for the position on that clip's own timeline."""
    pev = prec.get("events", [])
    special = prec["special_handling"]["id"]
    blend = float(prec.get("ease_in_s") or 0.0)
    pdur = (vf or {}).get("duration_s") or prec.get("duration_s")
    mdur = (mf or {}).get("duration_s") or mrec.get("duration_s")
    speed = float(mrec.get("speed") or 1.0)
    rate = speed / mdur if mdur else (1.0 / pdur if pdur else None)
    default = float(mrec.get("start_playpos") or 0.0)
    s0 = default if start is None else float(start)
    own = float(prec.get("start_playpos") or 0.0)

    def pos(t):
        return None if (rate is None or t is None) else round(min(s0 + t * rate, 1.0), 4)

    goto = None
    if prec.get("absolute"):
        if special == 0:
            goto = {"time_s": 0.0, "playpos": round(s0, 4), "trigger": "STATE_ENTRY_FLAG"}
        else:
            goto = _pair_event(pev, EV_ABSOLUTE_GOTO_TARGET_POS, rate, s0, own)
    release = _pair_event(pev, EV_LEAVE_ABSOLUTE_MODE, rate, s0, own)
    t_rel = release["time_s"] if release else None
    phases = []

    def phase(mode, a, b):
        if t_rel is not None:
            if a >= t_rel:
                return
            b = t_rel if b is None else min(b, t_rel)
        if b is None or b > a:
            ph = {"mode": mode, "from_s": round(a, 4), "to_s": b and round(b, 4)}
            if rate is not None:
                ph.update(from_playpos=pos(a), to_playpos=pos(b))
            phases.append(ph)

    if not prec.get("absolute"):
        phases.append({"mode": "not_absolute", "from_s": 0.0, "to_s": None})
    elif goto is None or goto["time_s"] is None:
        phase("own_entry_pose", 0.0, None)
    else:
        t0 = goto["time_s"]
        phase("own_entry_pose", 0.0, t0)
        phase("blend_to_anchor", t0, t0 + blend)
        phase("anchored", t0 + blend, None)
    if prec.get("absolute") and release is not None:
        ph = {"mode": "released", "from_s": t_rel, "to_s": None}
        if rate is not None:
            ph.update(from_playpos=pos(t_rel), to_playpos=None)
        phases.append(ph)
    anchored = bool(goto and goto["time_s"] is not None and prec.get("absolute"))
    out = {
        "master": {
            "absolute": bool(mrec.get("absolute")),
            "snapped": False,
            "special_handling": mrec["special_handling"],
            "animation_type": mrec["animation_type"],
            "speed": speed,
            "duration_s": mdur,
            "start_playpos": round(s0, 4),
            "start_basis": "state_default" if s0 == default else "given",
            "entry_alternatives": list(alternatives or []),
        },
        "partner": {
            "absolute": bool(prec.get("absolute")),
            "special_handling": prec["special_handling"],
            "follows_master_playpos": True,
            "entered_by": "goto_slave_mode",
            "start_playpos": round(own, 4),
            "anchored_from_start": anchored and special == 0,
            "goto_target": goto,
            "blend_s": blend if anchored else None,
            "anchored_from_s": round(goto["time_s"] + blend, 4) if anchored else None,
            "release": release,
            "duration_s": pdur,
            "phases": phases,
        },
        "start_playpos": round(s0, 4),
        "playpos_per_second": None if rate is None else round(rate, 6),
        # the anchored partner is rigid in this frame (0x6b9035, 0x6b015d): read
        "anchor_frame": "master node",
        "anchor_rotation_unverified": False if not anchored else None,
        "master_yaw_change_deg": None,
        "anchor_drift_if_master_turns_m": None,
    }
    if anchored and mf and rate:
        end = (1.0 - s0) / rate  # the lock (and the master's clip) ends at play position 1
        t0 = goto["time_s"]
        t1 = max(t0, end if t_rel is None else min(t_rel, end))
        # play time -> seconds on the master's clip: (start + t * rate) * duration
        turn, drift = _master_turn(
            mf, pl, (s0 + t0 * rate) * mdur, (s0 + t1 * rate) * mdur, s0 * mdur
        )
        if turn is not None:
            out["master_yaw_window_s"] = [round(t0, 4), round(t1, 4)]
            out["master_yaw_window_playpos"] = [pos(t0), pos(t1)]
            out["master_yaw_change_deg"] = turn
            out["anchor_drift_if_master_turns_m"] = drift
            out["anchor_rotation_unverified"] = turn > ANCHOR_YAW_TOLERANCE_DEG
    return out


def entry_alternatives(rec, transitions):
    """Other play positions a state can be entered at than its own
    start_playpos: transitions that lead to it (directly or through a state
    group above it) and carry an override / sync-marker start, plus the
    walk-cycle carry-over.  [] = only the default entry is possible."""
    path, out = rec.get("path") or "", []
    for t in transitions or []:
        to = t.get("to")
        if t.get("start") and to and (to == path or path.startswith(to + "/")):
            out.append(dict(t["start"], owner=t["owner"], transition=t["name"]))
    if rec.get("walk_cycle"):
        out.append({"rule": "walk_cycle_carry_over"})
    return out


def pair_weapons(mnode, pnode, mtype=None, ptype=None):
    """Which weapon setup a pair needs, from the two states' criteria and those
    of their enclosing state groups: own weapon = enum variable 5
    (WEAPON_ANIMATION_TYPE), the other side's = variable 12
    (OPPONENT_WEAPON_TYPE).  A list of allowed names, or None = not tested.
    mtype / ptype: the two model types, so criteria such as
    ANY OF(BASH_1H | ALL OF(BASH_2H, ENEMY_03)) resolve for this pair."""

    def both(own, other):
        if other is not None:
            other = [_OPPONENT_WEAPON_AS_OWN.get(x, x) for x in other]
        if own is None or other is None:
            return own if other is None else other
        return [x for x in own if x in other]

    me = {} if ptype is None else {VAR_OPPONENT_MODEL: ptype}
    pe = {} if mtype is None else {VAR_OPPONENT_MODEL: mtype}
    mw = allowed_enum_names(mnode, VAR_WEAPON, env=me)
    pw = allowed_enum_names(pnode, VAR_WEAPON, env=pe)
    mo = allowed_enum_names(mnode, VAR_OPPONENT_WEAPON, env=me)
    po = allowed_enum_names(pnode, VAR_OPPONENT_WEAPON, env=pe)
    return {
        "master_weapon": both(mw, po),
        "partner_weapon": both(pw, mo),
        "master_own": mw,
        "partner_own": pw,
        "master_requires_partner": mo,
        "partner_requires_master": po,
    }


def _group_criteria(node):
    return [_crit_text(k) for g in _groups_of(node) for k in _crit_nodes(g)]


def _groups_accept(node, chartype):
    return all(accepts_partner(g, chartype) for g in _groups_of(node))


#: top-level key of a table whose combat / fx step failed:
#: {"combat" | "fx": {"format": the block format that was attempted, "status":
#: "attempted, failed", "reason": "<exception type>: <message>"}}.  The block and
#: its `<block>_format` marker are absent; this entry says the build was tried with
#: THIS toolkit's block format, so a resumed character export reuses the table
#: (characters_export.anim_meta_is_current) instead of rebuilding it on every run.
BUILD_FAILED_KEY = "build_failed"


def _block_failed(failed, block, fmt, said, prefix):
    """Record in `failed` why `block` is missing: the reason is what the step logged
    ("  combat: skipped (KeyError: 'x')").  A step that returned nothing WITHOUT
    reporting a failure (a hook switched off) leaves no entry."""
    line = next((x for x in reversed(said) if x.startswith(prefix)), None)
    if line is not None:
        reason = line[len(prefix) :]
        reason = reason[:-1] if reason.endswith(")") else reason
        failed[block] = {"format": fmt, "status": "attempted, failed", "reason": reason}


def build(extract_out, binds=None, log=None, frame=None):
    """The whole table as one JSON-able dict (see module docstring), in the
    output frame (`frame`, else frame.mode(): "true" unless --frame mirrored)."""
    with _kj.tree_cache(os.path.join(extract_out, "extracted")):  # the extract is only read
        return _build(extract_out, binds, log, frame)


def _build(extract_out, binds, log, frame):
    log = log or (lambda *a: None)
    classes = load_classes(extract_out)
    clipfiles = find_clips(extract_out)
    facts = {}

    def fact(name):
        k = _clip_key(name).lower()
        if k not in facts:
            f = clipfiles.get(k)
            try:
                facts[k] = clip_facts(f) if f else None
            except (struct.error, ValueError, IndexError, KeyError) as ex:
                log("  clip %s: %s" % (name, ex))
                facts[k] = None
        return facts[k]

    all_nodes = [n for c in classes.values() for n in c["nodes"]]
    event_names = learn_event_names(all_nodes)
    out_classes = {}
    states = {}  # class -> [(node, record)]
    rec_of = {}  # id(state node) -> record
    for cn, c in sorted(classes.items()):
        recs = []
        for n in c["nodes"]:
            if n.cls == asm.CLS_STATE:
                recs.append((n, state_record(n, event_names, fact)))
                rec_of[id(n)] = recs[-1][1]
        states[cn] = recs
        out_classes[cn] = {
            "fragment": os.path.relpath(c["fragment"], extract_out).replace(os.sep, "/"),
            "character_type": c["chartype_label"],
            "character_type_id": c["chartype"],
            "states": [r for _n, r in recs],
            "transitions": _transitions(c["nodes"]),
        }
        gone = missing_event_lists(c["nodes"])
        if gone:  # a state names an event-list fragment the data does not contain
            out_classes[cn]["missing_event_lists"] = gone
            log("  %s: %d event-list fragments not found: %s" % (cn, len(gone), ", ".join(gone)))
        log(
            "%-12s %4d states, %3d masters"
            % (cn, len(recs), sum(1 for _n, r in recs if r["master_of"]))
        )

    # slave index: class -> id -> [(container, candidate state nodes)]
    slaves = {}
    for cn, c in classes.items():
        idx = {}
        for n in c["nodes"]:
            if n.parent is None or n.parent.name != "SlaveStates":
                continue
            if n.cls == asm.CLS_GROUP:
                sid, kids = n.p("m_istategroupid"), [
                    k for k in n.children if k.cls == asm.CLS_STATE
                ]
            elif n.cls == asm.CLS_STATE:
                sid, kids = n.p("m_istateid"), [n]
            else:
                continue
            if sid:
                idx.setdefault(sid, []).append((n, kids))
        slaves[cn] = idx

    contact = None
    if binds:
        import characters_export

        contact = _ContactCheck(binds, characters_export.track_names_for(extract_out))
    pairs = []
    for cn, recs in sorted(states.items()):
        mtype = classes[cn]["chartype"]
        for node, rec in recs:
            X = rec["master_of"]
            if not X or not rec["main_clip"]:
                continue
            mf = fact(rec["main_clip"])
            for vn in sorted(classes):
                vtype = classes[vn]["chartype"]
                if not accepts_partner(node, vtype):
                    continue
                for cont, kids in slaves[vn].get(X, []):
                    for k in kids:
                        if not accepts_partner(k, mtype):
                            continue
                        vclip = _main_clip(k)
                        if not vclip:
                            continue
                        vf = fact(vclip)
                        same = bool(mf and vf and abs(mf["duration_s"] - vf["duration_s"]) < 0.035)
                        pl = placement(mf, vf) if (mf and vf) else None
                        ct = None
                        if contact and pl and mf and vf:
                            try:
                                ct = contact(
                                    mf["file"],
                                    vf["file"],
                                    pl["partner_origin_shift_xz"],
                                    pl["partner_yaw_deg"],
                                )
                            except Exception as ex:  # a bind this clip does not fit
                                log("  contact %s: %s" % (rec["main_clip"], ex))
                        if pl is not None and ct is not None:
                            pl["check"]["contact"] = ct
                        prec = rec_of.get(id(k)) or state_record(k, event_names, fact)
                        pairs.append(
                            {
                                "master_class": cn,
                                "master_state": rec["name"],
                                "master_path": rec["path"],
                                "master_clip": rec["main_clip"],
                                "master_of": X,
                                "master_criteria": rec["criteria"],
                                "partner_class": vn,
                                "partner_state": k.name,
                                "partner_path": _path(k),
                                "partner_clip": vclip,
                                "partner_criteria": [_crit_text(x) for x in _crit_nodes(k)],
                                "master_duration_s": mf and mf["duration_s"],
                                "partner_duration_s": vf and vf["duration_s"],
                                "same_duration": same,
                                "placement": pl,
                                "confidence": _confidence(pl, same, ct),
                                "master_group_criteria": _group_criteria(node),
                                "partner_group_criteria": _group_criteria(k),
                                "group_criteria_accept": bool(
                                    _groups_accept(node, vtype) and _groups_accept(k, mtype)
                                ),
                                "master_opponent_models": allowed_enum_names(
                                    node, VAR_OPPONENT_MODEL
                                ),
                                "weapons": pair_weapons(node, k, mtype, vtype),
                                "timeline": pair_timeline(
                                    rec,
                                    prec,
                                    mf,
                                    vf,
                                    pl,
                                    alternatives=entry_alternatives(
                                        rec, out_classes[cn]["transitions"]
                                    ),
                                ),
                            }
                        )
    pairs.sort(
        key=lambda p: (
            p["master_class"],
            p["master_path"],
            p["master_clip"],
            p["partner_class"],
            p["partner_clip"],
        )
    )
    # The table links a master state to EVERY class that files a slave under the
    # same id; the master state itself rarely says which enemy it is for (the
    # game's script picks the state).  Where one of the candidates has exactly
    # the master's duration, that is the authored pair and the others are not.
    by_m, by_p = {}, {}
    for p in pairs:
        by_m.setdefault((p["master_class"], p["master_path"], p["master_clip"]), []).append(p)
        by_p.setdefault((p["partner_class"], p["partner_path"], p["master_class"]), []).append(p)
    for p in pairs:
        sib = by_m[(p["master_class"], p["master_path"], p["master_clip"])]
        sib2 = by_p[(p["partner_class"], p["partner_path"], p["master_class"])]
        p["primary"] = p["same_duration"] or not (
            any(x["same_duration"] for x in sib) or any(x["same_duration"] for x in sib2)
        )

    # per-clip view: everything a clip needs, keyed by clip name
    clips = {}
    for cn, recs in states.items():
        for _n, r in recs:
            use = layer_use(r["clips"])
            for sl in r["clips"]:
                c = sl["clip"]
                if not c:
                    continue
                f = fact(c)
                e = clips.setdefault(c, {"used_by": [], "loop": False, "events": [], "pairs": []})
                e["layer_use"] = sorted(set(e.get("layer_use", [])) | set(use.get(c, [])))
                if f and "duration_s" not in e:
                    e.update(
                        {
                            k: f[k]
                            for k in (
                                "duration_s",
                                "key_count",
                                "key_rate_hz",
                                "frame_rate_scale",
                                "game_pivot",
                                "interact",
                            )
                        }
                    )
                    e["file"] = os.path.relpath(f["file"], extract_out).replace(os.sep, "/")
                e["used_by"].append(
                    {
                        "class": cn,
                        "state": r["name"],
                        "path": r["path"],
                        "main": c == r["main_clip"],
                        "speed": sl.get("speed"),
                    }
                )
                # the game loops a clip when a looping state plays it, as the state's main
                # clip or as a member of its blend (an arm-layer overlay is partial-body)
                if r["loop"] and "arm_layer" not in c.lower():
                    e["loop"] = True
                if c == r["main_clip"]:
                    if sl.get("speed") is not None and sl["speed"] not in e.setdefault(
                        "speeds", []
                    ):
                        e["speeds"] = sorted(e["speeds"] + [sl["speed"]])
                    for ev in r["events"]:
                        if ev not in e["events"]:
                            e["events"].append(ev)
                    for w in r["weapon"]:
                        e.setdefault("weapon", [])
                        if w not in e["weapon"]:
                            e["weapon"].append(w)
    # every clip file gets its header/root facts, used by a state or not
    used_lower = {c.lower() for c in clips}
    for lk, f in sorted(clipfiles.items()):
        if lk in used_lower:
            continue
        name = _clip_key(os.path.basename(f))
        ft = fact(name)
        if ft:
            e = clips.setdefault(name, {"used_by": [], "loop": False, "events": [], "pairs": []})
            e.update(
                {
                    k: ft[k]
                    for k in (
                        "duration_s",
                        "key_count",
                        "key_rate_hz",
                        "frame_rate_scale",
                        "game_pivot",
                        "interact",
                    )
                }
            )
            e["file"] = os.path.relpath(f, extract_out).replace(os.sep, "/")
    for i, p in enumerate(pairs):
        for role, mine, other, ocls in (
            ("master", "master_clip", "partner_clip", "partner_class"),
            ("partner", "partner_clip", "master_clip", "master_class"),
        ):
            e = clips.get(p[mine])
            if e is not None:
                e["pairs"].append(
                    {"pair": i, "role": role, "other_clip": p[other], "other_class": p[ocls]}
                )
    for e in clips.values():
        e["events"].sort(key=_event_sort_key)
        e["used_by"].sort(key=lambda x: (x["class"], x["path"]))

    # face controllers: per state / pair records + the top-level block (additive)
    import face_rule

    said = []  # what the optional steps logged: the reason of a failure is in there

    def _log(*a):
        said.append(str(a[0]) if a else "")
        if log:
            log(*a)

    failed = {}  # block -> why its build failed (BUILD_FAILED_KEY)
    try:
        face = face_rule.build(extract_out, classes, states, pairs, sys.modules[__name__], _log)
    except Exception as ex:  # decoration: must not take the animation table down
        face = None
        for _lst in states.values():  # drop what the step wrote before it failed
            for _node, _rec in _lst:
                _rec.pop("face", None)
                _rec.pop("inflicts", None)
        for _p in pairs:
            _p.pop("face", None)
        _log("  face: skipped (%s: %s)" % (type(ex).__name__, ex))
        _block_failed(failed, "face", face_rule.FACE_FORMAT, said, "  face: skipped (")
    out = {
        "format": FORMAT,
        "revision": REVISION,
        "conventions": CONVENTIONS,
        # caption-learned names (format 1); the records use the exe's names
        "event_names": {
            str(k): v for k, v in sorted(event_names.items(), key=lambda kv: kv[0] or 0)
        },
        "event_name_check": event_name_check(all_nodes),
        "event_semantics": ee.event_semantics(),
        "enums": {f: ee.data()["families"][f]["items"] for f in ee.families()},
        "enum_variables": {
            k: {"name": ee.name("ANIMATION_ENUM", int(k)), "values": v}
            for k, v in sorted(ee.data()["enum_variable_family"].items(), key=lambda kv: int(kv[0]))
        },
        "transition_start_priority": TRANSITION_START_PRIORITY,
        "skeletons": skeletons(binds) if binds else {},
        "classes": out_classes,
        "clips": dict(sorted(clips.items())),
        "pairs": pairs,
    }
    if face is not None:
        out["face_format"] = face_rule.FACE_FORMAT
        out["face"] = face
    # combat rules: per-state `combat`, per-pair `trigger`, top-level block (additive)
    import combat_meta

    combat = combat_meta.build_or_none(
        extract_out, classes, states, pairs, sys.modules[__name__], _log
    )
    if combat is not None:
        out["combat_format"] = combat_meta.COMBAT_FORMAT
        out["combat"] = combat
    else:
        _block_failed(failed, "combat", combat_meta.COMBAT_FORMAT, said, "  combat: skipped (")
    # the weapon class each clip is played with (criteria and weapon blends)
    import parts_rule

    for name, use in parts_rule.clip_weapon_use(out).items():
        if name in out["clips"]:
            out["clips"][name]["weapon_use"] = use
    # effects / camera cuts / rumble: event payload, state `fx`, pair camera cuts (additive)
    import fx_meta

    fx_meta.attach(out, extract_out, classes, states, pairs, sys.modules[__name__], _log)
    if out.get("fx_format") != fx_meta.FORMAT:
        _block_failed(failed, "fx", fx_meta.FORMAT, said, "  fx_meta: skipped (")
    if failed:
        out[BUILD_FAILED_KEY] = failed
    return _asset_names(apply_frame(out, frame), extract_out)


def _asset_names(meta, extract_out):
    """Strings that name a file of the export in the spelling of that file, the
    stored one beside them under "stored" (canonical_names.respell_export; with
    --names stored the table is left as it is)."""
    import canonical_names

    return canonical_names.respell_export(meta, extract_out)


# ------------------------------------------------------------- coordinate frame
# Keys that hold numbers in the GLB's frame (read from the clips' root tracks);
# everything else spatial in the table is a raw engine value (CONVENTIONS_TRUE
# "engine_values").
_ROOT_POS_KEYS = ("pos_start", "pos_end")
_ROOT_YAW_KEYS = ("yaw_start_deg", "yaw_end_deg")
_PLACEMENT_XZ_KEYS = (
    "master_start_xz",
    "partner_start_xz",
    "partner_offset_xz",
    "partner_origin_shift_xz",
)


def reflect_root(r):
    """A clip's game_pivot / interact record -> the other frame (in place)."""
    for k in _ROOT_POS_KEYS:
        if r.get(k) is not None:
            r[k] = _frame.vec(r[k])
    for k in _ROOT_YAW_KEYS:
        if r.get(k) is not None:
            r[k] = _frame.yaw_deg(r[k])
    return r


def reflect_placement(pl):
    """A pair's placement record -> the other frame (in place): x of every xz
    pair negated, the partner's yaw negated; distances do not change."""
    for k in _PLACEMENT_XZ_KEYS:
        if pl.get(k) is not None:
            pl[k] = _frame.xz(pl[k])
    if pl.get("partner_yaw_deg") is not None:
        pl["partner_yaw_deg"] = _frame.yaw_deg(pl["partner_yaw_deg"])
    chk = pl.get("check")
    if isinstance(chk, dict) and chk.get("partner_game_pivot_start_xz") is not None:
        chk["partner_game_pivot_start_xz"] = _frame.xz(chk["partner_game_pivot_start_xz"])
    return pl


def reflect_meta(meta):
    """Reflect (x -> -x) every GLB-frame number of a table in place: the clips'
    game_pivot / interact records and the pairs' placement.  Raw engine values
    (impact vectors, event payloads, fx offsets, camera parameters) are not
    touched.  Applying it twice gives the table back."""
    seen = set()

    def once(d):
        if not isinstance(d, dict) or id(d) in seen:
            return False
        seen.add(id(d))
        return True

    for c in (meta.get("clips") or {}).values():
        for k in ("game_pivot", "interact"):
            if once(c.get(k)):
                reflect_root(c[k])
    for p in meta.get("pairs") or []:
        if once(p.get("placement")):
            reflect_placement(p["placement"])
    return meta


def _set_frame_text(meta, mode):
    meta["conventions"] = conventions(mode)
    cam = (meta.get("fx") or {}).get("camera")
    if isinstance(cam, dict) and isinstance(cam.get("cut_placement"), dict):
        import fx_meta

        cam["cut_placement"] = fx_meta.cut_placement(mode, cam["cut_placement"])


def apply_frame(meta, frame=None):
    """A table as build() computes it (engine numbers = the mirrored frame) ->
    the output frame, in place.  "mirrored": unchanged, no marker.  "true": the
    GLB-frame numbers reflected, the conventions of that frame, and the marker
    coordinate_frame = "right-handed-true" after `format`."""
    if not _frame.is_true(frame):
        return meta
    reflect_meta(meta)
    _set_frame_text(meta, "true")
    return _frame.stamp_json(meta, "true")


def to_frame(meta, frame=None):
    """`meta` in the frame `frame` (default frame.mode()): the table itself when
    it already is, else a converted deep copy.  A table without the marker is
    in the mirrored frame (1.3.0 tables, --frame mirrored)."""
    if not isinstance(meta, dict):
        return meta
    mode = _frame.mode(frame)
    if _frame.frame_of(meta) == mode:
        return meta
    import copy

    out = reflect_meta(copy.deepcopy(meta))
    out.pop(_frame.MARKER_KEY, None)
    out.pop(_frame.NOTE_KEY, None)
    if "conventions" in out:
        _set_frame_text(out, mode)
    return _frame.stamp_json(out, mode)


def skeletons(binddir):
    """{bind key: skeleton_extras()} for every bind in `binddir`.  The joint
    order is the palette order, i.e. the order of the b0..bN nodes of every GLB
    written with that bind -- so this table also describes GLBs written before
    the names were embedded."""
    import numpy as np

    out = {}
    for f in sorted(glob.glob(os.path.join(binddir, "bind_*_file_v1.npz"))):
        key = os.path.basename(f)[len("bind_") : -len("_file_v1.npz")]
        b = np.load(f, allow_pickle=True)
        if "names" in b and "par" in b:
            out[key] = skeleton_extras(b["names"], b["par"])
            out[key]["joint_count"] = len(b["names"])
    return out


#: What the four ragdoll animation values hold (CharacterVisual.command_update_ragdoll
#: 0x6bc3e2); state criteria compare them (ANIMATION_VALUE ids).  Engine values: they
#: are the same in both export frames.
RAGDOLL_VALUES = [
    {
        "id": 6,
        "name": "CHARACTER_PELVIS_ROTATION",
        "unit": "deg",
        "range": [-180, 180],
        "rule": "atan2(E.up, E.(B x up)); E = world direction of -pelvis bone Y, B = "
        "horizontal unit of -pelvis bone X; 0 = body +Z up, +90 = right side up, -90 = left "
        "side up, +-180 = +Z down; exactly vertical body gives -90",
        "source": "0x6bc3e2, ATan2 0x5aa394",
    },
    {
        "id": 8,
        "name": "CHARACTER_PELVIS_RAGDOLL_FREE",
        "unit": "truth",
        "range": [0, 1],
        "rule": "expand volume fully grown for more than 0.15 s; for non-playable "
        "characters also no playable character within 1.5 m horizontal",
        "source": "0x6bc3e2",
    },
    {
        "id": 10,
        "name": "CHARACTER_PELVIS_VELOCITY",
        "unit": "m/s",
        "range": [0, None],
        "rule": "length of the pelvis ragdoll body's linear velocity",
        "source": "0x6bc3e2",
    },
    {
        "id": 11,
        "name": "CHARACTER_PELVIS_GROUND_HEIGHT",
        "unit": "m",
        "range": [0, None],
        "rule": "pelvis to first non-Character hit of a downward capsule cast",
        "source": "0x6bc3e2 (cast details not rechecked)",
    },
]


def pelvis_rotation(q_pelvis_world):
    """Animation value 6 (CHARACTER_PELVIS_ROTATION, degrees) for the pelvis bone's
    world orientation (x, y, z, w), engine numbers -- what 0x6bc3e2 computes: with
    A = the world direction of -bone X and E = that of -bone Y (vectors rotate as
    conj(q) v q), B = A made horizontal and unit (zero for a vertical body),
    D = B x up: 57.29578 * ATan2(E.up, E.D), where the engine's ATan2 (0x5aa394)
    takes sign -1 for a first argument <= 0."""
    x, y, z, w = (float(c) for c in q_pelvis_world)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    # rows of the matrix of conj(q) v q: the world directions of the bone axes
    bx = (1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y))
    by = (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x))
    a = (-bx[0], -bx[1], -bx[2])
    e = (-by[0], -by[1], -by[2])
    h = math.hypot(a[0], a[2])
    # rounding noise is not a direction: an exactly vertical body has B = 0
    b = (a[0] / h, 0.0, a[2] / h) if h > 1e-9 else (0.0, 0.0, 0.0)
    d = (-b[2], 0.0, b[0])  # B x up
    ny, nx = e[1], e[0] * d[0] + e[2] * d[2]
    ny = 0.0 if abs(ny) < 1e-9 else ny
    nx = 0.0 if abs(nx) < 1e-9 else nx
    sign = 1.0 if ny > 0 else -1.0
    if nx > 0:
        ang = sign * math.atan(abs(ny / nx))
    elif nx == 0:
        ang = sign * math.pi / 2
    else:
        ang = sign * (math.pi - math.atan(abs(ny / nx)))
    return 57.29578 * ang


CONVENTIONS = {
    "units": "metres, seconds, degrees",
    "up_axis": "+Y (the engine is Y-up; no axis conversion is applied)",
    "handedness": (
        "engine coordinates are written verbatim into right-handed glTF, so the "
        "export is a MIRROR IMAGE: with the character facing +Z its LEFT hand is "
        "at -X. Mirror X (and swap L/R) to get the real-world pose."
    ),
    "layers": (
        "classes.*.states[].clips[] carry layer_index, additive, force_playpos_1 and "
        "layer_weight of the blend directly under the state (read from code: "
        "SetupNewPage 0x5b7788, UpdatePagePlayPos 0x5b61b9). clips[*].layer_use is the "
        "sorted subset of ['additive', 'base', 'upper'] over the states that use the "
        "clip; a clip no state uses has no layer_use. A clip whose layer_use lacks "
        "'base' is never played alone: 'upper' clips replace only the bones they have "
        "tracks for, by the layer weight (0x592c8d, 0x594cac); 'additive' clips are "
        "applied as pose(t) composed with the inverse of pose(0), scaled by the bone "
        "weight (0x594cac, 0x592a2f). Character GLBs bake every clip as an absolute pose."
    ),
    "playpos": (
        "0..1 fraction of the clip. An event's `time_unit` says what the game stores "
        "(`raw`): 'playpos' (trigger PLAY_POS: playpos = raw), 'seconds' "
        "(TOTAL_PLAY_TIME: raw = seconds of play time), 'state_enter' (ENTER_STATE: "
        "fired when the state starts) or 'state_leave' (LEAVE_STATE: fired when the "
        "state is left, whenever that is; playpos and both times are null). `time_s` "
        "is the position on the clip's OWN timeline (playpos * duration), "
        "`play_time_s` the seconds after the state was entered. A state is entered at "
        "`start_playpos` (its own m_nstartplaypos, TransitToState 0x5b4a31; "
        "start_basis = 'state_default') and its play position then advances by speed / "
        "duration per second (`speed` = the slot's speedFactor, SetAllSlotBlends "
        "0x5b5193), so a PLAY_POS event at r fires (r - start_playpos) * duration / "
        "speed seconds after entry, and a TOTAL_PLAY_TIME event after t seconds sits "
        "at playpos = start_playpos + t * speed / duration (null past the end of a "
        "non-looping clip). Every event repeats the start_playpos / start_basis its "
        "times were computed for; a transition with an override or sync-marker start, "
        "or a walk-cycle carry-over, enters the state elsewhere and shifts them. "
        "Class / character / controller speed factors are taken as 1. A state whose "
        "first layer's slots differ in speed (speed_basis) has no single rate. A "
        "PLAY_POS event fires once per pass when the play position reaches it "
        "(position <= playpos, CheckPlayPosEvents 0x5b55c4); one at or before the "
        "start position is created already fired (SetupNewPage 0x5b8f16) and carries "
        "fires_first_pass = false: on a looping state it fires after the wrap "
        "(play_time_s is that moment), on a non-looping state never (play_time_s "
        "null)."
    ),
    "names": (
        "event, criteria, variable, model-type, weapon, special-handling and "
        "animation-type names and ids are the executable's own (top-level `enums`); "
        "`caption_name` on an event is the name its editor caption carries when that "
        "differs, `event_names` the caption-learned table of format 1."
    ),
    "criteria_units": (
        "criteria bounds are in the unit of the animation value: radians for DIRECTION and "
        "ANGLE_TO_TARGET (measured -2.7..2.7 and -2..2), HEAD_ANGLE_TO_TARGET and "
        "HEAD_VERTICAL_ANGLE_TO_TARGET (internal range -+pi/2), and by the code range also "
        "VERTICAL_ANGLE_TO_TARGET and TARGET_ANGLE_TO_YOU (-+pi; no shipped criterion) -- "
        "AnimationData.GetAnimationValueInternalMin/Max 0x5aa588 / 0x5aa5c2; degrees for "
        "CHARACTER_PELVIS_ROTATION (measured -180..180)"
    ),
    "criteria": (
        "`criteria_tree` gives each criterion as data. Enum variable 11 is "
        "OPPONENT_MODEL_TYPE (the other character's model type); an ENUM criterion "
        "tests only its variable and value. `character_type_id` of a class is its "
        "OPPONENT_MODEL_TYPE id. Intervals (MathLib.InsideInterval 0x77aa25): INTERVAL "
        "is min <= x < max, LESS_THAN is x < MAX (min is not read), "
        "GREATER_THAN_OR_EQUAL is x >= min. A criterion belongs to the nearest state, "
        "state group or transition above it, whatever folder it is filed in. "
        "`entry_only`: not tested while the current state is the state that owns it or "
        "lies inside the group that owns it. pair.master_opponent_models: the "
        "OPPONENT_MODEL_TYPE values the master state's and its groups' criteria leave "
        "possible (null = not tested); group_criteria_accept compares them with the "
        "partner CLASS's own model type, and ENEMY_03 and UNDERBOSS have no class "
        "file of their own, so false does not rule a pair out."
    ),
    "pair_weapons": (
        "pair.weapons: allowed WEAPON_ANIMATION_TYPE names per side, null = not "
        "tested. Read from the states' criteria and their enclosing groups' "
        "(variable 5 = own weapon, variable 12 = the other's, OPPONENT_WEAPON_TYPE "
        "NONE taken as UNARMED -- that correspondence is inferred from the names)."
    ),
    "pair_timeline": (
        "pair.timeline. READ FROM CODE: the master is not an absolute animation and is "
        "never snapped. The pair is locked in PLAY POSITION: the partner's play "
        "position is copied from the master every frame until the master's reaches 1 "
        "(partner.follows_master_playpos; goto_slave_mode 0x5b32a2, UpdatePagePlayPos "
        "0x5b5756), so both run at the master's rate, playpos_per_second = "
        "master.speed / master.duration_s, whatever the partner's own slot speed is, "
        "from the master's start position: playpos(t) = start_playpos + t * "
        "playpos_per_second (master.start_playpos, start_basis 'state_default'; "
        "master.entry_alternatives lists transitions that would enter the master "
        "elsewhere -- none ships). The partner is entered by goto_slave_mode at its "
        "own start position (partner.start_playpos), which only decides which of its "
        "PLAY_POS events are created already fired. "
        "`time_s` / `from_s` / `to_s` are seconds of play time from the start of both "
        "states; `playpos` / `from_playpos` / `to_playpos` the shared play position -- "
        "multiply by a clip's duration for the position on that clip's timeline. The "
        "partner enters at its own pose and its visible node HOLDS that entry pose "
        "('own_entry_pose'): it gets no absolute update until its capsule flag +0xb8 is "
        "set (UpdateAnimPoseAndCloth 0x6b015d, attempt_move 0x67f727, DccUpdate "
        "0x680654) -- it does not play its GamePivot motion in that phase. The flag is "
        "set by its ABSOLUTE_GOTO_TARGET_POS event (goto_target); the partner is "
        "then eased from that entry pose onto the anchored trajectory over blend_s "
        "seconds = its state's ease-in ('blend_to_anchor': w = 1 - (t - t_goto) / "
        "blend_s, pos = w * entry + (1 - w) * anchored), stays 'anchored', and is "
        "'released' to normal physics at its first LEAVE_ABSOLUTE_MODE (position "
        "kept). Special handling NORMAL (0) means anchored from the start. While "
        "anchored the partner is RIGID IN THE MASTER NODE'S FRAME (anchor_frame "
        "'master node'; the node is the master's GamePivot frame): in that frame "
        "partner node pos = I0 - (GP_m(t) - GP_m(0)) + R180 * (GP_p(t) - GP_p(0)), "
        "orient = q_p(t) * half-turn about +Y, I0 = interact_m(0) or the default "
        "offset. So the anchor cancels the master's own GamePivot translation and "
        "SWINGS with a turn of the master. `placement` is the fixed marker at t = 0; "
        "on a pair whose master turns more than 2 degrees while the partner is "
        "anchored, anchor_rotation_unverified is true (the key name is kept from "
        "earlier tables: the swing itself is read from code) with "
        "master_yaw_change_deg (largest GamePivot turn from t = 0 inside the anchored "
        "window) and anchor_drift_if_master_turns_m = the engine's largest departure "
        "from that fixed marker. The clip data favour the fixed marker on most, not "
        "all, of those pairs (measured: closer contact with the marker on 24 of 30 "
        "turning pair rows, with the swing on 4), so treat contact there as "
        "approximate either way. INFERRED: that both states start in the same frame. "
        "The master's face heading follows CharacterRoot.StateActive's damping "
        "(0x6b367a, MathLib.LinearDampSignedAngle 0x791500); it does not enter the "
        "relative rule. NOT ESTABLISHED: LOOK_AT_TARGET during a pair; whether the "
        "game shows the swing has not been checked in a capture."
    ),
    "transition_start": (
        "classes.*.transitions: `start.rule` and top-level transition_start_priority "
        "say where the target state starts. Sync markers are (local, remote) play "
        "positions 0..1, local in the state being left, remote in the target, sorted "
        "by local; the transition can fire only while gate[0] <= outgoing playpos <= "
        "gate[1] and the target starts at the piecewise-linear map of the outgoing "
        "playpos, clamped to the first / last remote marker (read from code: "
        "UpdateSuperSync 0x5fa582, TransitionMet 0x5c5ea4, TransitionPlayPos "
        "0x5ac1aa). It is a one-shot start position, not a time warp. A transition "
        "to a STATE is also gated by that state's own `criteria` (the engine appends "
        "them to the transition's list, AnimationTransition.initialize_external "
        "0x5f9b13) and by the criteria of the groups around the target; a transition "
        "to a group by the group's criteria and those around it. `to` is the "
        "resolved target; a reference to the fragment's own slot is the state group "
        "that instances the fragment."
    ),
    "evidence": (
        "read from the executable: enum tables, criteria semantics, event trigger "
        "kinds, per-event effects (event_semantics[*].evidence), sync markers, the "
        "partner's entry / goto / blend / release sequence, master not snapped. "
        "Inferred or measured on the data: see pair_timeline and pair_weapons."
    ),
    "body_space": (
        "body joints are keyed relative to GamePivot, which is 1.0 m above the "
        "ground and carries the actor's position AND heading: world = GamePivot(t) + "
        "R(q_GamePivot(t)) * joint (the engine turns a vector as conj(q) v q; in the "
        "GLB that is the GamePivot node's own rotation applied to the joint nodes, "
        "which are written beside it, not under it). A clip whose GamePivot turns "
        "turns the body with it"
    ),
    "motion_root": "GamePivot (absolute track, shared scene for paired clips)",
    "interact": (
        "child of GamePivot, keyed local to it; world-fixed marker. In a paired "
        "clip the master's interact marks where the partner starts."
    ),
    "pair_space": (
        "engine rule: the partner starts on the master's interact marker, its "
        "frame turned 180 deg about +Y, and moves by its own GamePivot track "
        "relative to that track's first key: partner_world(t) = partner_start + "
        "R(partner_yaw) * (GamePivot_p(t) - GamePivot_p(0) + R(q_p(t)) * joint_p(t)), "
        "q_p = the partner clip's own GamePivot rotation (it comes on top of "
        "partner_yaw; three partner clips start at -5 deg); master_world(t) = "
        "GamePivot_m(t) + R(q_m(t)) * joint_m(t). The engine's start offset is 3-D "
        "(interact_m(0).y is -0.042 on one primary pair); the table gives x and z. "
        "Height: partner_start is that horizontal pair, so subtract only x and z of "
        "GamePivot_p(0) -- each character keeps the height of its own GamePivot "
        "track (about 1.0 m; the engine puts the partner's first key at the master "
        "node's height + interact_m(0).y, which is the same where both clips start "
        "at the same height)"
    ),
    "absolute_motion": (
        "any actor: pos(t) = start_pos + R(start_orient) * (GamePivot(t) - "
        "GamePivot(0)); orient(t) = GamePivot_orient(t) * start_orient"
    ),
    "frame_rate_scale": "1/2/3 = FULL/HALF/THIRD of the 30 fps engine rate",
    "ragdoll_values": RAGDOLL_VALUES,
}


# The same block for files written in the true frame (the default).
CONVENTIONS_TRUE = dict(CONVENTIONS)
CONVENTIONS_TRUE["handedness"] = (
    "right-handed, x = -engine x (coordinate_frame 'right-handed-true'): the export "
    "shows the game as it is, not mirrored. With the character facing +Z its LEFT "
    "hand is at +X, and the bone names L / R are truthful. Nothing has to be mirrored. "
    "A file without a coordinate_frame key (toolkit 1.3.0, or --frame mirrored) holds "
    "the engine's left-handed numbers verbatim and is a mirror image."
)
CONVENTIONS_TRUE["engine_values"] = (
    "values copied from the game files are NOT converted and stay in "
    + _frame.ENGINE_NOTE
    + ". They are: a state's impact.position / impact.direction, event payload "
    "vectors (m_vvalue*), fx local_position / local_direction / local_orientation, "
    "the camera-cut parameters and the formulas of fx.camera.cut_placement, the "
    "camera rig, sweep angles and face.attachment.head_model_yaw_deg. In the GLB's "
    "frame are: clips[*].game_pivot / interact (pos_*, yaw_*) and pairs[*].placement."
)


CONVENTIONS_TRUE["yaw"] = (
    "yaw_start_deg / yaw_end_deg and partner_yaw_deg are the engine's heading angle "
    "(2 * atan2(y, w) of its root quaternion), sign changed for this frame. A value a "
    "is a right-handed rotation of MINUS a degrees about +Y in the GLB: every clip yaw "
    "equals minus the yaw of the GLB's own GamePivot / interact rotation (measured). "
    "In this frame a positive value turns the facing direction from +Z towards -X, the "
    "character's right, clockwise seen from above. R(partner_yaw) in pair_space is "
    "that rotation; +-180 is the same turn in either sense."
)


def conventions(frame=None):
    """The `conventions` block for files in `frame` (default frame.mode())."""
    return CONVENTIONS_TRUE if _frame.is_true(frame) else CONVENTIONS


def skeleton_extras(names, parents):
    """glTF `extras` for a skin: the real bone names and hierarchy.

    The joints are written flat (every joint a child of one identity root,
    transforms in GamePivot-relative world space), so this is what lets an
    importer rebuild the hierarchy without a hand-made table per skeleton.
    """
    names = [str(n) for n in names]
    par = [int(p) for p in parents]
    idx = {n: i for i, n in enumerate(names)}
    attach = {n: i for i, n in enumerate(names) if "attach" in n.lower()}
    return {
        "joint_names": names,
        "joint_parents": par,
        "motion_root": "GamePivot" if "GamePivot" in idx else None,
        "motion_root_joint": idx.get("GamePivot"),
        "interact_joint": idx.get("interact"),
        "body_root_joint": idx.get("Bip"),
        "roots": [i for i, p in enumerate(par) if p < 0],
        "joint_space": (
            "flat: every joint node is a child of `root`; its transform is the "
            "joint's world transform RELATIVE TO GamePivot (interact included). "
            "GamePivot alone carries the absolute scene track."
        ),
        "attach_joints": attach,
    }


_LOWER = {}  # id(meta["clips"]) -> {lowercased clip name: clip name}


def _find_clip(meta, name):
    clips = meta.get("clips") or {}
    k = _clip_key(name)
    if k in clips:
        return k, clips[k]
    lk = _LOWER.get(id(clips))
    if lk is None:
        lk = _LOWER[id(clips)] = {c.lower(): c for c in clips}
    c = lk.get(k.lower())
    return (c, clips[c]) if c else (None, None)


# pair keys of the fx / combat blocks that go into a clip's glTF extras (the pair's
# `fx` lists and the per-state `fx` / `combat` blocks stay in anim_meta.json: they are
# keyed by state, and a clip is shared by several states)
CLIP_PAIR_EXTRA_KEYS = ("camera_cuts", "camera_return", "trigger")


def clip_extras(meta, name, fps=None, frames=None):
    """glTF `extras` for one animation, or None when the game data does not
    know the clip (synthetic GRIP / face poses).

    fps/frames describe the animation AS WRITTEN (the writer may resample it);
    events are given both as the
    game's play position and as a time in the written animation.
    """
    key, c = _find_clip(meta, name)
    if c is None:
        return None
    written = (frames - 1) / fps if (fps and frames and frames > 1) else None
    ev = []
    dur = c.get("duration_s")
    for e in c.get("events", []):
        d = dict(e)
        unit = e.get("time_unit", "playpos")  # format-1 tables have playpos only
        if unit == "playpos" and dur is not None and e.get("playpos") is not None:
            d["time_s"] = round(e["playpos"] * dur, 4)  # on THIS clip's length
        elif unit == "seconds" and dur:
            # time_s is the position on the clip (it includes the state's start
            # position); None when the event falls past the end of the clip
            ts = e.get("time_s")
            d["playpos"] = round(ts / dur, 4) if (ts is not None and ts <= dur + 1e-6) else None
        if written is not None and d.get("playpos") is not None:
            d["written_time_s"] = round(d["playpos"] * written, 4)
        ev.append(d)
    out = {
        "clip": key,
        "duration_s": c.get("duration_s"),
        "key_count": c.get("key_count"),
        "key_rate_hz": c.get("key_rate_hz"),
        "frame_rate_scale": c.get("frame_rate_scale"),
        "loop": c.get("loop", False),
        "written_fps": None if fps is None else round(float(fps), 5),
        "written_duration_s": None if written is None else round(written, 5),
        "game_pivot": c.get("game_pivot"),
        "interact": c.get("interact"),
        "events": ev,
        "weapon": c.get("weapon", []),
        "states": [u["class"] + ":" + u["path"] for u in c.get("used_by", []) if u.get("main")],
        # slot speed factors the game plays this clip at (as a state's main clip)
        "speeds": c.get("speeds", []),
    }
    if c.get("weapon_use"):
        out["weapon_use"] = c["weapon_use"]
    prs = []
    for ref in c.get("pairs", []):
        p = meta["pairs"][ref["pair"]]
        prs.append(
            {
                "role": ref["role"],
                "other_clip": ref["other_clip"],
                "other_class": ref["other_class"],
                "master_state": p["master_state"],
                "partner_state": p["partner_state"],
                "same_duration": p["same_duration"],
                "primary": p["primary"],
                "confidence": p["confidence"],
                "placement": p["placement"],
                "weapons": p.get("weapons"),
                "timeline": p.get("timeline"),
            }
        )
        # blocks other modules add to a pair (fx_meta: the procedural camera of a
        # finisher / counter, on the pair clock; combat_meta: what starts the pair).
        # Copied only when the table has them: older tables give the same extras.
        for k in CLIP_PAIR_EXTRA_KEYS:
            if p.get(k):
                prs[-1][k] = p[k]
    prs = [x for x in prs if x["primary"]] or prs
    # one entry per distinct (role, other clip, other class); states differ only
    seen, uniq = set(), []
    for x in prs:
        k = (x["role"], x["other_clip"], x["other_class"])
        if k not in seen:
            seen.add(k)
            uniq.append(x)
    out["pairs"] = uniq
    return out


class _ContactCheck:
    """Optional geometric cross-check of a pair's placement: bake both halves,
    put them in the shared scene, and measure how close they actually get.
    `track_names` is bake_v4.bake's track lookup; build() passes the rule of the
    character export for the set (characters_export.track_names_for)."""

    _KEY = {
        "RSH": "rsh",
        "NTO": "nto",
        "EN1": "medium",
        "EN2": "large",
        "EN3": "small",  # Part 1 only (characters_export.CLIP_PREFIX_P1)
        "EN4": "female",
        "BS2": "bs2",
    }

    def __init__(self, binddir, track_names="exact"):
        self.binddir, self._bind, self._clip = binddir, {}, {}
        self.track_names = track_names

    def _load(self, f):
        import numpy as np
        import bake_v4

        if f in self._clip:
            return self._clip[f]
        nm = _clip_key(os.path.basename(f))
        key = self._KEY.get(nm[:3].upper())
        if key is None:
            raise KeyError("no skeleton is known for clip prefix %s" % nm[:3].upper())
        bp = os.path.join(self.binddir, "bind_%s_file_v1.npz" % key)
        if not os.path.exists(bp):
            raise OSError("bind_%s_file_v1.npz is not in %s" % (key, self.binddir))
        if key not in self._bind:
            b = np.load(bp, allow_pickle=True)
            names = [str(x) for x in b["names"]]
            B4 = np.tile(np.eye(4), (len(names), 1, 1))
            B4[:, :3, :3], B4[:, :3, 3] = b["Rb"], b["tb"]
            self._bind[key] = (names, B4)
        names, B4 = self._bind[key]
        pal, _dur = bake_v4.bake(nm, 1, bind=bp, bank={nm: f}, track_names=self.track_names)
        P4 = np.concatenate(
            [pal.astype(float), np.tile([0, 0, 0, 1.0], (pal.shape[0], pal.shape[1], 1, 1))], 2
        )
        T = np.einsum("fkab,kbc->fkac", P4, B4)[:, :, :3, 3]
        body = [
            i
            for i, n in enumerate(names)
            if n not in ("GamePivot", "interact") and "Attach" not in n
        ]
        eff = [
            body.index(i)
            for i in body
            if names[i].endswith(("Hand", "Foot", "Head", "Calf", "Forearm"))
        ]
        # world = GamePivot(t) + R(q_GamePivot(t)) * joint: the bake is GamePivot-local
        # and unrotated (GamePivot, interact and Bip are roots of the bind), and the
        # engine turns the body with GamePivot (UpdatePagePlayPos 0x5b56a9; data: the
        # interact marker is world-fixed only with this rotation)
        gp = names.index("GamePivot")
        M = np.einsum("fab,bc->fac", P4[:, gp], B4[gp])
        W = np.einsum("fab,fkb->fka", M[:, :3, :3], T[:, body]) + M[:, None, :3, 3]
        self._clip[f] = (W, eff)
        return self._clip[f]

    def __call__(self, mfile, vfile, shift=(0.0, 0.0), yaw_deg=180.0):
        """shift, yaw_deg: placement()'s partner_origin_shift_xz and
        partner_yaw_deg (the turn of the partner clip; +-180 on shipped pairs)."""
        import numpy as np

        (A, ae), (V, ve) = self._load(mfile), self._load(vfile)
        F = min(len(A), len(V), 60)

        def rs(X):
            idx = np.linspace(0, len(X) - 1, F)
            i0 = np.floor(idx).astype(int)
            i1 = np.minimum(i0 + 1, len(X) - 1)
            a = (idx - i0)[:, None, None]
            return X[i0] * (1 - a) + X[i1] * a

        A = rs(A)
        V = rs(V)
        if abs(abs(float(yaw_deg)) - 180.0) < 1e-9:
            V = V * np.array([-1.0, 1.0, -1.0])
        else:  # R(partner_yaw) = _yaw_rot(-yaw)
            c, sn = math.cos(math.radians(-yaw_deg)), math.sin(math.radians(-yaw_deg))
            V = np.stack(
                [c * V[..., 0] + sn * V[..., 2], V[..., 1], c * V[..., 2] - sn * V[..., 0]], -1
            )
        V = V + np.array([shift[0], 0.0, shift[1]])
        d1 = np.linalg.norm(A[:, ae][:, :, None] - V[:, None], axis=-1).reshape(F, -1).min(1)
        d2 = np.linalg.norm(V[:, ve][:, :, None] - A[:, None], axis=-1).reshape(F, -1).min(1)
        d = np.minimum(d1, d2)
        k = int(np.argmin(d))
        return {
            "closest_m": round(float(np.percentile(d, 10)), 3),
            "closest_playpos": round(k / max(F - 1, 1), 3),
        }


# ---------------------------------------------------------------------- CLI
def write(extract_out, out_json, binds=None, log=print, frame=None):
    import extract_out as _xo

    _xo.require(extract_out)  # a mistyped folder is an error, not an empty table
    meta = build(extract_out, binds=binds, log=log, frame=frame)
    with open(out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1)
    return meta


def summary(meta):
    import collections

    P = [p for p in meta["pairs"] if p["primary"]]
    conf = collections.Counter(p["confidence"] for p in P)
    return "%d classes, %d states, %d clips, %d primary pairs of %d candidates (%s)" % (
        len(meta["classes"]),
        sum(len(c["states"]) for c in meta["classes"].values()),
        len(meta["clips"]),
        len(P),
        len(meta["pairs"]),
        ", ".join("%s %d" % kv for kv in sorted(conf.items())),
    )


def main(argv):
    if len(argv) < 3 or argv[1] in ("-h", "--help"):
        print("usage: anim_meta.py EXTRACT_OUT OUT.json [BINDS_DIR]")
        return 0 if len(argv) > 1 else 2
    meta = write(argv[1], argv[2], binds=argv[3] if len(argv) > 3 else None)
    print("wrote %s: %s" % (argv[2], summary(meta)))
    return 0


if __name__ == "__main__":

    sys.exit(main(sys.argv))
