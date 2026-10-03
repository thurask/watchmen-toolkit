# Animation metadata — states, events, transitions, pairs, skeletons

What a consumer of the character GLBs needs beyond the keyframes, read from the
game's own data. Written by `watchmen animmeta EXTRACT_OUT OUT.json [BINDS_DIR]`,
and by `watchmen characters`, which saves the same table as
`OUT_DIR/anim_meta.json` and embeds the relevant part in every GLB's `extras`.

This document describes **format 2** (`"format": "watchmen-anim-meta/2"`,
toolkit 1.3.0). Format 1 was written only by a development build of 1.3.0 that
was never tagged; the differences are listed in the next section.

Source: `wlib/anim_meta.py` builds the records; the engine rules it applies
(fragment splicing, reference resolution, criteria, event timing, sync markers,
start position, slot speed) are implemented once, in
`wlib/anim_state_machine.py`. Names and ids come from the executable's enum
registrations (`wlib/engine_enums.json`). Nothing is inferred from clip names.

Evidence labels used below:

- **read** — traced in the executable; the address is given.
- **data** — measured on the Part 2 PC files.
- **inferred** — follows from what was read or measured, with the reason given.
- **not established** — open.

The same labels are in the file itself, as text, under `conventions`
(`pair_timeline`, `pair_weapons`, `evidence`) and per event in
`event_semantics[*].evidence`.

## What changed since format 1

A consumer written against format 1 has to deal with the following. No
format 1 key was removed; values changed as listed.

1. **Check `format == "watchmen-anim-meta/2"`.** A cached `anim_meta.json` of
   format 1 next to your GLBs is rebuilt by `watchmen characters` because the
   string differs.
2. **Events have a trigger kind, and `playpos` can be `null`.** Format 1
   exported every event's stored number as a play position. That is right only
   for `PLAY_POS` events. Use `trigger`; for timing use `time_s` (seconds on
   the clip's own timeline) or `play_time_s` (seconds since the state was
   entered). `playpos` is `null` for `LEAVE_STATE` events and for a
   `TOTAL_PLAY_TIME` event that falls beyond one pass of the clip. On the
   states both tables contain, 801 events had a wrong `playpos` in format 1
   (enter-state 419, leave-state 82, total-play-time 300).
3. **Event names are the executable's.** Ids 6 and 14 are renamed: `FOOTSTEP`
   → `LEFT_FOOT_DOWN`, `WALK_CYCLE_POINT` → `UNUSED`. The editor's label is
   kept in `caption_name` when it differs. What an event does is in
   `event_semantics[event_id]`.
4. **Some `PLAY_POS` events do not fire on the first pass.** An event at or
   before the state's start position carries `fires_first_pass: false`
   (34 events; on the 29 that sit on non-looping states `play_time_s` is
   `null`: they never fire).
5. **States have a `speed` and a `start_playpos`.** A state is entered at
   `start_playpos` (563 of 1,290 states start past 0) and its play position
   then advances by `speed / duration` per second (707 states run at a speed
   other than 1), so `time_s = start_playpos × duration + play_time_s × speed`.
   Every event repeats the `start_playpos` its times were computed for and a
   `start_basis` (`state_default`: the state's own start, the engine's default
   entry).
6. **Pairs have a `timeline`.** `placement` is unchanged on every pair that
   was in the format 1 table; `timeline` says when to apply it. Do not snap
   the master. Hold the partner at its own entry pose during `own_entry_pose`,
   blend during `blend_to_anchor`, use `placement` during `anchored`, stop
   constraining at `released`. The pair runs on the master's clock, from
   the master's start position (`timeline.start_playpos`; past 0 on 205 of
   240 primary pairs).
7. **`timeline.anchor_rotation_unverified`** is true on 39 primary pairs: the
   master turns while the partner is anchored and the constant anchor may be
   off by up to `anchor_drift_if_master_turns_m`. Treat contact there as
   approximate.
8. **More states, fewer clip entries, more pairs.** 1,290 states (format 1:
   1,162) because the root nodes of nested fragments are no longer lost;
   1,159 clip entries (1,375) because blend-slot captions such as
   `pos 2, CLIP` are no longer exported as clip names; 413 pair candidates,
   240 primary (395, 234). State `path` and pair `master_path` include the
   restored groups. The order of `classes.*.states` can differ.
9. **`character_type`** is an `OPPONENT_MODEL_TYPE` name. The ids are the same
   as before.
10. **New data:** `criteria_tree` per state, `classes.*.transitions` with
    `start` (sync markers or an override), `transition_start_priority`,
    `enums`, `enum_variables`, `special_handling` and `animation_type` per
    state, `weapons`, group criteria and `master_opponent_models` per pair,
    `speeds` per clip.
11. **Python:** the private `_VAR_PARTNER` is gone (`VAR_OPPONENT_MODEL`).
    Public functions and the CLI are unchanged; `state_record` and
    `allowed_enum_names` gained optional arguments.

## Where each fact comes from

| Fact | Game data |
|---|---|
| Which clip pairs with which | `AnimationStateWM.m_imasterof` ("Master of") on the attacker's state ↔ the partner class's `SlaveStates` entry with the same id (`m_istategroupid` on a group, `m_istateid` on a state); the child is chosen by its criteria on the opponent's model type |
| Where the partner stands | the `GamePivot` and `interact` root tracks of the two `.animation` clips |
| When the partner is anchored and released | the partner state's `m_ispecialhandling`, its `ABSOLUTE_GOTO_TARGET_POS` and `LEAVE_ABSOLUTE_MODE` events and its ease-in; the master state's slot speed |
| Events (hit, kill partner, camera cut, drop weapon …) | `AnimationEventWM` children of the state: event id, trigger kind `m_ieventtype`, and `m_nplaypos` — a play position for `PLAY_POS`, **seconds of play time** for `TOTAL_PLAY_TIME`, unused for `ENTER_STATE` / `LEAVE_STATE` |
| What an event does | `event_semantics`: read from the event handlers in the executable |
| Criteria, weapon stance per side | `AnimationCriteria` nodes of the state and its groups; enum variable 5 = own weapon, 11 = the other character's model type, 12 = the other's weapon |
| Transitions, sync markers | `AnimationTransition` nodes: `m_nsupersynclocal1..8` / `m_nsupersyncremote1..8`, `m_toverrideplaypos` / `m_nplaypos`, `m_neaseinduration` |
| Speed | the `speedFactor` of the state's animation slots |
| Loop, start play position, impact settings | properties of the state |
| Every id → name | the executable's enum registrations (`wlib/engine_enums.json`) |
| Bone names and parents | the skeleton `.model` header (via the bind) |
| Frame rate, duration, rate scale | the clip header |

## Coordinate conventions

- Metres, seconds, degrees. **+Y up**; no axis conversion is applied.
- **The export is a mirror image.** Engine coordinates are written verbatim into
  right-handed glTF: with a character facing +Z its *left* hand is at −X. Mirror
  X and swap L/R for the real-world pose. This affects single characters and
  pairs identically, so relative placement is unaffected.
- **Body joints are keyed relative to `GamePivot`.** `GamePivot` is 1.0 m above
  the ground in every skeleton (lowest body joint + GamePivot.y = 0.00 across
  213 clips, data), and carries the actor's motion through the scene:
  `world = GamePivot track + joint position`.
- `interact` is keyed local to `GamePivot` and cancels its motion, so it is a
  world-fixed marker (data). In a paired clip the engine starts the partner on
  the master's `interact`. The women's skeletons (`female`, `bs2`) have no
  `interact`.
- In the skeleton file `Bip`, `GamePivot` and `interact` are siblings under one
  unnamed root; none is the parent of another.
- A play position is a fraction 0..1 of the clip.

## Events

An event record has a trigger kind (`ANIMATION_EVENT_TYPES`, read from the
registration at 0x5e54e0):

| `trigger` | the game stores (`raw`) | `time_unit` | `playpos` | `time_s` | `play_time_s` |
|---|---|---|---|---|---|
| `PLAY_POS` (4,132) | a play position 0..1 | `playpos` | raw | raw × duration | (raw − start) × duration / speed; when raw ≤ start see below |
| `ENTER_STATE` (582) | ignored | `state_enter` | start | start × duration | 0.0 |
| `LEAVE_STATE` (83) | ignored | `state_leave` | `null` | `null` | `null` |
| `TOTAL_PLAY_TIME` (302) | seconds of play time | `seconds` | start + raw × speed / duration; `null` past the end of a non-looping clip or without a duration | `playpos` × duration | raw |

`time_s` is the position on the clip's own timeline (always `playpos` ×
duration); `play_time_s` is the time since the state was entered. `start` is
the play position the state is entered at: the engine starts a page at the
state's `m_nstartplaypos` unless the transition says otherwise
(`TransitToState` 0x5b4a31), and the play-time counter starts with the page.
Each event carries `start_playpos` and `start_basis` (`state_default`) so the
assumption is explicit; a transition with an override or sync-marker start,
or a walk-cycle carry-over (see *Transitions*), enters the state elsewhere and
shifts the times — `anim_meta._events(state, …, start=…)` computes them for
another entry. Class, character and controller speed factors are taken as 1.

Read from `CheckPlayPosEvents` 0x5b51f3 and `SetupNewPage` 0x5b7788:

- A `PLAY_POS` event fires once per pass, when the play position reaches it
  (`m_nplaypos <= play position` and not yet fired, 0x5b55c4). It is a latch,
  not a (previous, current] window; the window is used only under the
  editor's debug play-position override.
- An event at or before the position the state starts at is created already
  fired (0x5b8f16) and carries `fires_first_pass: false`. On a looping state
  it fires after the wrap — `play_time_s` is then
  (1 − start + raw) × duration / speed; on a non-looping state it never fires
  and `play_time_s` is `null`. 34 events: 29 on non-looping states, 5 on
  looping ones.
- A `TOTAL_PLAY_TIME` event fires once, when that many seconds have been
  played on the page (0x5b52c1).
- `ENTER_STATE` events are sent when the page is set up, `LEAVE_STATE` events
  when the state is left, whenever that is.

`event_semantics` (93 ids) says for each event what the handler does (`effect`),
what its `value` means, whether it moves the character that carries it
(`moves_character`) or touches the partner (`affects_partner`), and the case
address (`handler`). `evidence` is "read from code" for 83 ids; for ten (6, 23,
29, 30, 31, 40, 59, 70, 76, 77) the case was skimmed for commands and field
writes, not read instruction by instruction, and the string says so. No event
writes a partner's position or orientation.

`event_name_check` compares the executable's names with the editor captions in
the fragments: 73 ids agree, 2 conflict (id 6: `LEFT_FOOT_DOWN` against the
caption `FOOTSTEP`, 13 uses; id 14: `UNUSED` against `WALK_CYCLE_POINT`,
4 uses), 18 ids exist only in the executable. `event_names` is the
caption-learned table of format 1, kept unchanged.

## Criteria

`criteria` is the text form; `criteria_tree` gives each criterion as data.

Read from `AnimationCriteriaMet` 0x5c5781 and `MathLib.InsideInterval`
0x77aa25:

- An `ENUM` criterion tests only its variable (`m_ianimationenum`) and value
  (`m_ianimationenumvalue`). Enum variable 11 is `OPPONENT_MODEL_TYPE`, the
  *other* character's model type. Format 1 read a stale editor slot as a
  second selector and dropped real tests.
- Intervals: `INTERVAL` is min ≤ x < max; `LESS_THAN` is x < **max** (min is
  not read); `GREATER_THAN_OR_EQUAL` is x ≥ min. A shipped criterion captioned
  "SPEED less than 0.01" stores min 0.51, max 0.01.
- A criterion belongs to the nearest state, state group or transition above
  it, whatever folder it is filed in (`FindClosestRelevantParent` 0x5aaf49).
- `entry_only`: the criterion is not tested while the current state is the
  state that owns it or lies inside the group that owns it.

`ANY_OF` / `ALL_OF` are evaluated three-valued when the table asks whether a
state accepts a partner or a weapon: a child that does not mention the tested
variable has no opinion.

## Transitions

`classes.*.transitions` lists every transition with its owner (a state or a
state group), its resolved target, its criteria and how the target's start
position is chosen. Part 2 PC: 2,593 transitions (owner a state 2,330, a group
263); 146 with sync markers, 44 with an override start position, 39 fallback,
575 overriding the ease-in.

Read from `UpdateSuperSync` 0x5fa582, `TransitionMet` 0x5c5ea4,
`TransitionPlayPos` 0x5ac1aa, `MapIntervalToInterval` 0x77a579,
`TransitToState` 0x5b4a31:

- Sync markers are (local, remote) play positions: local in the state being
  left, remote in the target. The engine keeps them up to the first unset
  local marker and sorts them by local.
- A transition with markers can fire only while the outgoing play position is
  inside `gate` = [smallest local, largest local].
- The target then starts at the piecewise-linear map of the outgoing position,
  clamped to the first / last remote marker. There are no implicit (0, 0) or
  (1, 1) end points.
- It sets the start position once. It does not warp time.
- A transition to a **state** is also gated by that state's own `criteria`
  (`AnimationTransition.initialize_external` 0x5f9b13 appends them to the
  transition's list) and by the criteria of the groups around the target; a
  transition to a **group** by the group's criteria and those around it.

`transition_start_priority` gives the order as data: transition override →
sync markers → walk-cycle carry-over (both states have `walk_cycle`: the
outgoing play position is kept) → the target's `start_playpos`; afterwards, if
the target is already on the page stack and is a walk cycle, that page's
current position replaces the value. `anim_meta.transition_start(rec,
outgoing_playpos)` evaluates the transition's part of it.

## Speed

Read from `SetAllSlotBlends` 0x5b4ef7 (0x5b5175–0x5b51d0): the page rate is
`controller speed × slot speed × slot weight / clip duration`, summed over the
slots of the page's first layer. The slot speed is the slot's `speedFactor`
property (getter 0x4b30b1).

`state.speed` is that factor; `clips[*].speed` gives it per slot. When the
first layer's slots differ in speed the state has no single rate, and
`speed_basis` says which slot the value was taken from (13 states). 20 states
have no slot and `speed: null`.

Not established: that the objects in a page's slot list are the fragment's
`AnimSlot` nodes themselves rather than sources created from them with another
speed. The rate code reads the factor at +0x64 on an `AnimSlot` and +0x84 on
an `AnimBlendSource`; both are that class's `speedFactor` property.

## Pair placement

This is the engine's rule, read from the executable (addresses below).

Every actor in an absolute animation has a start frame and moves by its own
`GamePivot` track relative to that track's first key:

```
pos(t)    = start_pos + R(start_orient) · (GamePivot(t) − GamePivot(0))
orient(t) = GamePivot_orient(t) · start_orient
```

The partner's start frame is set from the master:

```
partner start_pos    = master node · interact_m(0)        (the `interact` marker)
partner start_orient = yaw(180°) · master node orientation
```

"Master node" is the master's CharacterVisual node, its live world transform.
So the partner's anchor is the master's `interact` marker, turned 180° about
+Y, and the partner plays its own clip from there. In the master's clip space:

```
master_world(t)  = GamePivot_m(t) + joint_m(t)
partner_world(t) = partner_start + R180 · (GamePivot_p(t) − GamePivot_p(0) + joint_p(t))
```

`placement.partner_start_xz` is the start, `partner_offset_xz` the same relative
to the master's own start, and `partner_yaw_deg` the turn to apply to the
partner clip (180 unless the master's GamePivot is itself turned at t = 0).
`partner_origin_shift_xz` is the constant to add after turning the partner
clip's *absolute* coordinates, for consumers that don't subtract
`GamePivot_p(0)` themselves. `placement.space` names the frame ("master clip
space").

If the master's `interact` track is exactly (0, 0, 0) at t = 0, or the clip
has no `interact` track, the engine substitutes the offset
**(0.11, 0.04, 1.12)**; `placement.source` says which applied. Four primary
pairs use it: `RSH_COM_ATT_finish_EN1_A` (against three partner classes) and
`EN1_COM_ATT_counter_NTO_B`.

The engine never reads the partner clip's absolute `GamePivot` start. It is
reported as `check.partner_game_pivot_start_xz`, with `check.agreement_m` its
distance from the engine's start, because the two halves were authored in one
scene and on most pairs it lands on the marker to the centimetre — an
independent check of the pairing and the placement.

### Pair timeline

`placement` says where the partner is while it is anchored; `timeline` says when.

Read from the executable:

- The **master** is not an absolute animation and is never snapped
  (`timeline.master.absolute` and `.snapped` are false). No shipped master
  state is absolute (data); `SetupNewPage` sends such a state to normal physics
  mode. The master plays its root motion from wherever it stands and the
  partner is brought to it.
- The pair is **locked in play position**. The master hands the partner its
  first animation source (`goto_slave_mode` 0x5b32a2) and the partner's play
  position is copied from it every frame until the master's reaches 1
  (`UpdatePagePlayPos` 0x5b5756, `partner.follows_master_playpos`). Both
  therefore run at the master's rate,
  `playpos_per_second = master.speed / master.duration_s`, whatever the
  partner's own slot speed is (they differ on 145 of 240 primary pairs).
- The pair starts at the **master's start position**:
  `playpos(t) = start_playpos + t × playpos_per_second`. The master's page is
  set up at the master state's own `m_nstartplaypos`
  (`master.start_playpos`, `start_basis: "state_default"`; 0.06 on 100 primary
  pairs, 0 on 35, up to 0.29). How the states are entered (data + code): every
  one of the 124 master states is reached only through transitions to a state
  group above it, none of which carries an override or sync-marker start, and
  none is a walk cycle — so the default entry is the only one
  (`master.entry_alternatives` is empty on every pair; it would list such
  transitions). No transition leads to any of the 164 partner states: they
  are entered by `goto_slave_mode` alone, which forces the state with play
  position −1, i.e. the partner's page is set up at the partner state's own
  start (`partner.start_playpos`, 0 on all of them) and the master's position
  is copied into it from then on. The partner's own start only decides which
  of its `PLAY_POS` events are created already fired; an event between the two
  starts fires at once.
- `time_s`, `from_s`, `to_s` are seconds of play time from the start of both
  states; `playpos`, `from_playpos`, `to_playpos` the shared play position.
  Multiply a play position by a clip's duration to get the position on that
  clip's own timeline.
- The **partner** enters at its own pose and plays its `GamePivot` motion from
  there (`own_entry_pose`). The placement block already runs every tick, but
  the capsule ignores its output until its go-to-target flag (+0xb8) is set.
- At its `ABSOLUTE_GOTO_TARGET_POS` event (`goto_target`; the handler at
  0x6a9dca sets that flag) the engine starts easing it from the entry pose
  onto the anchored trajectory over `blend_s` seconds, the partner state's own
  ease-in (`blend_to_anchor`): `w = 1 − (t − t_goto) / blend_s`,
  `pos = w · entry + (1 − w) · anchored`. The blend starts from the pose the
  partner had when the state began, not from where it is at the event.
- It then follows the anchor (`anchored`, from `anchored_from_s`) until its
  first `LEAVE_ABSOLUTE_MODE` event (`release`), after which it is under
  normal physics from where it is (`released`); the position is kept.
- A partner state with special handling `NORMAL` (0) has the flag set at
  entry and is anchored from the start (`anchored_from_start`, 3 primary
  pairs; `goto_target.trigger` is then `STATE_ENTRY_FLAG`). The usual value is
  `ABSOLUTE_START_AT_CURRENT_POS` (3).
- A partner state that is not absolute has the single phase `not_absolute`
  (none among the Part 2 PC pairs).

Part 2 PC, 240 primary pairs (data): master speed 1.1 on 214 (0.93–1.23 on
the rest, 1.0 on 3); go-to by `TOTAL_PLAY_TIME` at 0.20–0.21 s on 234, by
`PLAY_POS` on 3, entry flag on 3; blend 0.21 s on 237 and 0.13 s on 3; release
between play position 0.26 and 0.91 on 230, none on 10.

Inferred: that the anchored trajectory is the constant anchor of `placement`
(the engine re-anchors every tick to the master's live node, which cancels the
master's own translation but not a turn of its node); that both states start
on the same frame.

Not established: whether a non-absolute master's node turns with its
`GamePivot` during the clip. Where it would matter — the master's `GamePivot`
turns more than 2° from its heading at the start position while the partner is anchored — the
pair carries `anchor_rotation_unverified: true`, with `master_yaw_change_deg`,
`master_yaw_window_s`, `master_yaw_window_playpos` and
`anchor_drift_if_master_turns_m` (39 primary pairs, 14 master clips,
0.06–3.6 m).

### Where this is in the executable

Read 2026-10-02 from `KapowMultiDEDRM.exe`.

| What | Where |
|---|---|
| Master's new state has `Master of` set → sends `request_me_as_dual_animation_partner` and `goto_slave_mode` to the partner | `AnimationCtrlWM.SetupNewPage`, 0x5b9afb–0x5b9b54 |
| Partner placement block, run every tick while the partner's capsule is in absolute mode, it is in slave mode and has a partner | `CharacterRoot.StateActive`, 0x6b9035–0x6b94e9 |
| … asks the master for `get_slave_pos_offset` and `get_interact_initial_pos` | 0x6b90c1, 0x6b913d |
| … builds the 180° quaternion from the constant −π/2 at 0x9e8440 (sin → y, cos → w) | 0x6b9195–0x6b91ec |
| … substitutes (0.11, 0.04, 1.12) when interact(0) is zero | 0x6b9202–0x6b9263 |
| … writes the capsule's `m_vWorldStartPos` (+0x10) and `m_qWorldStartOrient` (+0x28) | 0x6b9320, 0x6b9478 |
| The capsule re-reads those properties only while its flag +0xb8 is set | `command_update_world_data` 0x6b201d, called from `command_absolute_update` |
| Per-frame absolute motion and the blend from the entry pose | `CollisionCapsuleNode.command_absolute_update`, 0x67f7b0 |
| `ABSOLUTE_GOTO_TARGET_POS` sets the capsule flag +0xb8 | 0x6a9dca |
| `LEAVE_ABSOLUTE_MODE` returns the capsule to normal physics and unlinks the pair | 0x6ac8de |
| `goto_slave_mode` forces the partner into its slave state with the state's own ease-in, and stores the master's animation source | 0x5b32a2 → `ForceToState` 0x5b4933 → `SetupNewPage` 0x5b7788 |
| Partner play position copied from the master's source | `UpdatePagePlayPos`, 0x5b5756–0x5b57d0 |
| Start-frame carry-over for looping absolute clips | `CollisionCapsuleNode.command_set_world_start_pos_from_next_pos_and_orient`, 0x6a24e1 |
| `command_get_slave_alignment` is a stub returning the identity quaternion | 0x5b0ddf |
| Enum criterion tests `m_ianimationenum` / `m_ianimationenumvalue` only | `AnimationCriteriaMet` 0x5c5781 |
| Event triggers: `TOTAL_PLAY_TIME` in seconds, `PLAY_POS` latch | `CheckPlayPosEvents` 0x5b51f3 (0x5b52c1, 0x5b55c4) |
| Sync markers sorted, gate, start position | `UpdateSuperSync` 0x5fa582, `TransitionMet` 0x5c5ea4, `TransitionPlayPos` 0x5ac1aa |

The full position expression is `master node · (interact_m(0) − (GamePivot_m(t) −
GamePivot_m(0)))`: the subtraction cancels the master's own progress, so the
anchor does not follow the master's root motion.

Not established: whether a non-absolute master's node turns with its
`GamePivot` (see *Pair timeline*); the parameters of the joint the engine
creates between the two capsules once the partner is anchored; how combat code
decides that a pair may start. The rule for a master whose GamePivot is turned
at t = 0 is implemented from the algebra but no shipped primary pair exercises
it (`yaw_start_deg` is 0 on all of them). The research reports are
[`re/placement.md`](re/placement.md) and [`re/events.md`](re/events.md).

### Evidence from the data (Part 2 PC)

- 141 unique equal-duration clip pairs. In 123 of them the partner clip's own
  `GamePivot` start is on the marker to under 5 cm.
- Turning the partner 180° brings the two skeletons into contact: mean closest
  approach 0.19 m, against 0.49–0.69 m for 0°, 90°, 270°. (Measured for format
  1 on the 139 pairs it had; not re-run.)
- `EN1_COM_DMG_counter_RSH_A/X/Y` are each exactly 3.925 m from the marker by
  their own `GamePivot` reading, yet meet the master when started on it
  (closest 0.207 / 0.248 / 0.233 m) — which is what the engine does.
- `RSH_COM_ATT_finish_EN1_B` + `EN1_COM_DMG_finish_RSH_B`: partner start
  (0.0, 0.856); the table's joint-to-joint check gives a closest approach of
  0.093 m at play position 0.424, next to the `IMPACT_EFFECTS` event at 0.41.
  Placed from the embedded `extras` of two exported GLBs, the closest
  limb-to-body distance was 2.7 cm at play position 0.43 (measured for format
  1; the inputs it depends on are unchanged).

### `confidence`

How well the *data* backs the engine's placement for that pair.

| Value | Meaning |
|---|---|
| `verified` | the partner clip's own GamePivot start lands on the engine's start (< 5 cm) and the two clips are the same length |
| `plausible` | it does not, but the placed skeletons do meet (< 0.25 m) |
| `unverified` | neither. Mostly two-handed-weapon moves, where contact is through the weapon |
| `none` | a clip has no `GamePivot` position track |

Part 2 PC: 240 primary pairs — 198 verified, 32 plausible, 10 unverified.

### `primary`

A master state rarely says which enemy it is for (the game's script picks the
state), so the table links it to *every* class that files a slave under that
id: 413 candidates. Where one candidate's clip is exactly as long as the
master's, that is the authored pair and the rest are marked `primary: false`.
A candidate of different length stays primary only when neither its master
state nor its partner state has an equal-length candidate; 8 primary pairs are
of that kind, with `same_duration: false` (e.g. `Throw Big Guy`: 3.17 s
against 2.90 s).

`master_opponent_models` lists the opponent model types the master state's and
its groups' criteria leave possible (`null` = not tested), and
`group_criteria_accept` compares them with the partner class's own model type
(165 true, 248 false). `ENEMY_03` and `UNDERBOSS` have no class file of their
own, so `false` does not rule a pair out (89 primary pairs are false). Group
criteria are reported, not used to filter pairs, and the `primary` rule does
not use them.

Things the table shows that clip names do not: Nite Owl's `Throw` plays
`RSH_COM_ATT_throw_EN1`; Rorschach's counters against Enemy04 reuse the
`…_EN1_*` attacker clips with `EN4_…` victim clips; Nite Owl's `Finish_move_G`
plays `NTO_COM_ATT_finish_EN1_B` against `EN4_COM_DMG_finish_NTO_G`.

## File layout (`anim_meta.json`)

```
format       "watchmen-anim-meta/2"
conventions  { key: sentence }   units, up_axis, handedness, playpos, names,
                                 criteria, pair_weapons, pair_timeline,
                                 transition_start, evidence, body_space,
                                 motion_root, interact, pair_space,
                                 absolute_motion, frame_rate_scale
event_names  { event id: name learned from editor captions (format 1 table) }
event_name_check  { agree, conflicts: [ {event_id, exe, caption, uses} ], exe_only: [ids] }
event_semantics   { event id: { name, effect, value, moves_character,
                                affects_partner, handler, evidence } }
enums        { family: { id: name } }                    30 families
enum_variables    { variable id: { name, values: family or null } }   16 variables
transition_start_priority  [ { rule, when, start } ]
skeletons    { bind key: { joint_names, joint_parents, motion_root,
                           motion_root_joint, interact_joint, body_root_joint,
                           roots, joint_space, attach_joints, joint_count } }
classes      { class: { fragment, character_type, character_type_id,
                        states: [ state ], transitions: [ transition ] } }
clips        { clip name: { file, duration_s, key_count, key_rate_hz,
                            frame_rate_scale, loop, game_pivot, interact,
                            events, weapon, speeds, used_by, pairs } }
pairs        [ pair ]
```

Part 2 PC: 5 classes, 1,290 states, 2,593 transitions, 5,099 events on states,
1,159 clips, 413 pairs.

**state** — `name`, `path`, `state_id`, `master_of`, `clips` (`clip`, `weight`,
`layer`, `speed`), `main_clip`, `loop`, `walk_cycle`, `start_playpos`,
`ease_in_s`, `absolute`, `defines_movement`, `defines_rotation`,
`attack_state`, `special_handling` and `animation_type` (each `id`, `name`),
`duration_s`, `speed` (and `speed_basis` when the first layer's slots differ),
`start_basis` (`state_default`),
`criteria`, `criteria_tree`, `weapon` (`UNARMED` / `BASH_1H` / `BASH_2H` when
the state requires one), `events`, and `impact` (`count`, `time_s`,
`distance_m`, `position`, `direction`, `damage_pose`, `damage_pose_name`,
`bone_id`) when set.

**criterion** (`criteria_tree`) — `text`, `kind`, `kind_id`, and when set `not`
and `entry_only`. By kind: `VALUE` carries `variable`, `variable_id` and
`interval` (`type`, `min`, `max`; min / max may name an `ANIMATION_VALUE`
instead of a number); the play-time and play-position kinds carry `interval`
only; `ENUM` carries `variable`,
`variable_id`, `value` (the name) and `value_id`; `ACTION` carries `action`,
`action_id`; `EVENT` carries `event`, `event_id`; `ANY_OF` / `ALL_OF` carry
`children`.

**event** — `name` (the executable's), `caption_name` (only when the editor
caption differs), `event_id`, `value`, `trigger`, `trigger_id`, `raw` (the
stored number), `time_unit`, `playpos`, `time_s`, `play_time_s`, `on_enter`,
and `on_leave` (only on leave-state events). `time_basis` on a `PLAY_POS`
event and `playpos_basis` on a `TOTAL_PLAY_TIME` event say how the derived
value was computed, including when the state's clips differ in length and the
main clip's duration was used. `start_playpos` and `start_basis` name the
entry the times were computed for; `fires_first_pass: false` as described
under *Events*. In a GLB's extras also `written_time_s` (the animation as
written, which may be retimed).

**transition** — `owner`, `owner_kind` (`state` or `group`), `name`, `to`,
`to_kind`, and when set `criteria`, `ease_in_override_s`, `fallback`, `start`:
`{rule: "override_playpos", playpos}` or `{rule: "sync_markers", markers:
[[local, remote], …], gate: [min, max]}`. `to` is the resolved target; a
reference to the fragment's own slot resolves to the state group that
instances the fragment.

**game_pivot / interact** — `pos_start`, `pos_end`, `yaw_start_deg`,
`yaw_end_deg`, `position_keyed`, `rotation_keyed`.

**clip** — the header facts, `loop`, `events` and `weapon` of the states that
use it as their main clip, `speeds` (the slot speeds the game plays it at as a
main clip), `used_by` (`class`, `state`, `path`, `main`, `speed`), and `pairs`
(`pair` = index into the top-level `pairs`, `role`, `other_clip`,
`other_class`).

**pair** — `master_class`, `master_state`, `master_path`, `master_clip`,
`master_of`, `master_criteria`, `master_group_criteria`,
`master_opponent_models`, `partner_class`, `partner_state`, `partner_path`,
`partner_clip`, `partner_criteria`, `partner_group_criteria`,
`group_criteria_accept`, `master_duration_s`, `partner_duration_s`,
`same_duration`, `primary`, `confidence`, `placement`, `weapons`, `timeline`.

**placement** — `space`, `source`, `master_start_xz`, `partner_start_xz`,
`partner_offset_xz`, `partner_distance_m`, `partner_yaw_deg`,
`partner_origin_shift_xz`, `check` (`partner_game_pivot_start_xz`,
`agreement_m`, `contact.closest_m`, `contact.closest_playpos`).

**weapons** — `master_weapon`, `partner_weapon`: the allowed
`WEAPON_ANIMATION_TYPE` names per side, `null` = not tested. The parts they
are built from are given too: `master_own`, `partner_own`,
`master_requires_partner`, `partner_requires_master`. Inferred, and labelled
so in `conventions.pair_weapons`: that `OPPONENT_WEAPON_TYPE` `NONE` / `BASH_1H`
/ `BASH_2H` correspond to `WEAPON_ANIMATION_TYPE` `UNARMED` / `BASH_1H` /
`BASH_2H`.

**timeline** —

```
master   { absolute, snapped, special_handling {id, name}, animation_type {id, name},
           speed, duration_s, start_playpos, start_basis, entry_alternatives [ ] }
partner  { absolute, special_handling {id, name}, follows_master_playpos,
           entered_by, start_playpos,
           anchored_from_start, goto_target {time_s, playpos, trigger} | null,
           blend_s, anchored_from_s, release {time_s, playpos, trigger} | null,
           duration_s,
           phases [ {mode, from_s, to_s, from_playpos, to_playpos} ] }
start_playpos, playpos_per_second
anchor_rotation_unverified, master_yaw_change_deg, anchor_drift_if_master_turns_m,
master_yaw_window_s, master_yaw_window_playpos
```

`mode` is `own_entry_pose`, `blend_to_anchor`, `anchored`, `released` or
`not_absolute`. `to_s` / `to_playpos` of the last phase are `null`.

`skeletons` and `check.contact` are present only when a binds directory was
given. A `clips` entry with no `file` is a clip a state names that does not
ship (4 on Part 2 PC, Part 1 leftovers).

## In the GLB

| Where | What |
|---|---|
| `asset.extras.watchmen` | `format`, `conventions` |
| `skins[0].extras.watchmen` | the skeleton record above |
| each joint node's `extras` | `bone` (real name), `parent` (joint index, −1 for a root) |
| `animations[i].extras.watchmen` | the clip record (`clip`, header facts, `loop`, `game_pivot`, `interact`, `weapon`, `speeds`), with `events` timed (`time_s`, `written_time_s`; `null` for leave-state events), `written_fps`, `written_duration_s`, `states`, and `pairs` (primary only) each carrying `role`, `other_clip`, `other_class`, the two state names, `same_duration`, `primary`, `confidence`, `placement`, `weapons` and `timeline` |

Joint nodes keep their `b0…bN` names and stay flat under `root`, so existing
importers are unaffected; the order is the palette order, which is
`joint_names`. Synthetic animations (`GRIP 1H`, face poses) have no clip record.

The `extras` path was exercised by the synthetic tests only in this release;
`watchmen characters` was not re-run on real data for it.

## Weapons

Weapon models are rigid-skinned to the `Attach RHand` joint (index in
`attach_joints`), grip authored at the model origin; Twilight Lady's is placed
from her fragment's `HandAttach` node. A state's `weapon` list says which
stance it needs, a pair's `weapons` which stance each side has. The attach
transform is that joint's own track in each clip.
