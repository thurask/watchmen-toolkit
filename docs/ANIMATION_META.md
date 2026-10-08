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

Since 1.4.0 the table also has a face block (`face_format:
"watchmen-face/2"`): additive, the format string stays `watchmen-anim-meta/2`,
and no key of a 1.3.0 table changes name or type. One value does change: the
`joint_space` sentence of every skeleton record, which in 1.3.0 said that
`GamePivot` and `interact` both carry absolute scene tracks. Only `GamePivot`
does; `interact` is written relative to it like every other joint (see
"Coordinate conventions"). See "The face block".

Two more blocks were added the same way, each with its own marker and its own
document, and neither changes an existing key:

- `combat_format: "watchmen-combat-meta/1"` — top-level `combat`, per state
  `group_criteria` / `criteria_rendered` / `combat`, per pair `trigger`: the
  combat rules. See [COMBAT_META.md](COMBAT_META.md).
- `fx_format: "watchmen-fx-meta/1"` — top-level `fx`, per event `payload` /
  `payload_stale`, per state `fx`, per pair `camera_cuts` / `camera_return` /
  `fx`: effects, the procedural finisher camera, rumble. See
  [FX_META.md](FX_META.md).

The two blocks share no key. A consumer checks the marker before reading a
block: a table built from an extract without the fragments a block needs, or
whose build step failed (`face: skipped (...)` / `combat: skipped (...)` /
`fx_meta: skipped (...)` in the log), has no marker and no block; the failure
is recorded under `build_failed`. `watchmen characters` reuses a table it
finds in its output folder only when all the markers are current or recorded
as failed in the current format (`characters_export.anim_meta_is_current`), so
a table whose face, combat or fx step fails is not rebuilt on every run. Part 2 PC: the table is 12.4 MB
without the two blocks; with the combat block alone 15.7 MB, with the fx block
alone 14.4 MB (with both blocks and the face block, in the six-set export:
21.5 MB on PC Part 2, 17.2 MB on PC Part 1; measured).

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
   master turns while the partner is anchored. The engine keeps the partner
   rigid in the master node's frame (`timeline.anchor_frame`, read from code),
   so it swings with the master and leaves the fixed marker of `placement` by
   up to `anchor_drift_if_master_turns_m`. Treat contact there as approximate
   (the key keeps its name from earlier tables).
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

- Metres, seconds, degrees. **+Y up**; no axis is swapped. Criteria bounds are in
  the unit of the animation value: radians for DIRECTION and ANGLE_TO_TARGET
  (measured −2.7..2.7 and −2..2), HEAD_ANGLE_TO_TARGET and
  HEAD_VERTICAL_ANGLE_TO_TARGET (internal range ∓π/2), and by the code range also
  VERTICAL_ANGLE_TO_TARGET and TARGET_ANGLE_TO_YOU (∓π; no shipped criterion) —
  `AnimationData.GetAnimationValueInternalMin/Max` 0x5aa588 / 0x5aa5c2; degrees
  for CHARACTER_PELVIS_ROTATION (measured −180..180).
- **The export is true-handed** (`coordinate_frame: "right-handed-true"`, the
  default since 1.4.0). The engine is left-handed; the GLBs and the numbers of
  this table that are in their frame have x = −engine x. With a character facing
  +Z its *left* hand is at +X, the bone names `L` / `R` are truthful, and nothing
  has to be mirrored. Single characters and pairs are treated alike, so relative
  placement is what the game shows.
- **A file without the `coordinate_frame` key is a mirror image.** That is every
  file written by 1.3.0 (this format string, `watchmen-anim-meta/2`, existed
  then) and everything written with `--frame mirrored`: the engine's numbers
  verbatim in right-handed glTF, a character facing +Z has its left hand at −X.
  For the real-world pose of such a file mirror X and swap L / R.
- **In the GLBs' frame** (they change sign of x, and of yaw, between the two
  frames): `clips[*].game_pivot` and `interact` (`pos_start`, `pos_end`,
  `yaw_start_deg`, `yaw_end_deg`) and `pairs[*].placement` (the `*_xz` pairs,
  `partner_yaw_deg`, `check.partner_game_pivot_start_xz`).
- **Sense of a yaw.** `yaw_start_deg`, `yaw_end_deg` and `partner_yaw_deg` are
  the engine's heading angle, 2·atan2(y, w) of its root quaternion. The engine
  rotates a vector as conj(q)·v·q and the GLB stores the conjugate, so a value
  *a* is a right-handed rotation of **−a** about +Y in the file: every clip yaw
  equals minus the right-handed yaw of the GLB's own `GamePivot` / `interact`
  rotation, in both frames (measured on Rorschach, 48 + 111 values, none with
  the same sign). In the true frame a positive value turns the facing direction
  from +Z towards −X, the character's right, clockwise seen from above
  (`RSH_COM_ATT_turn_left_EN1_B` ends at −90 with the GLB node at +90° about
  +Y). In a mirrored file the numbers have the other sign and a positive value
  again turns +Z towards −X, which there is the character's left. ±180 is the
  same turn in either sense.
- **In engine coordinates in both frames** (copied from the game files, see
  `conventions.engine_values`): a state's `impact.position` / `direction`, event
  payload vectors, the effects' `local_position` / `local_direction` /
  `local_orientation`, camera-cut parameters and the `fx.camera.cut_placement`
  formulas, the camera rig, sweep angles, `face.attachment.head_model_yaw_deg`.
  For a true-frame GLB negate x of such a position or direction, turn a
  quaternion (x, y, z, w) into (x, −y, −z, w) and change the sign of a yaw.
- **Body joints are keyed relative to `GamePivot`.** `GamePivot` is 1.0 m above
  the ground in every skeleton (lowest body joint + GamePivot.y = 0.00 across
  213 clips, data), and carries the actor's motion AND heading through the
  scene: `world = GamePivot(t) + R(q_GamePivot(t)) · joint` (read:
  `UpdatePagePlayPos` 0x5b56a9; the engine turns a vector as conj(q)·v·q). In
  the GLB the joint nodes are written beside the `GamePivot` node, not under
  it, so a consumer applies the `GamePivot` node's translation and rotation to
  them. A clip whose `GamePivot` turns turns the body with it (data: with this
  rotation the `interact` marker is world-fixed to 1 cm on 67 of the 72 staged
  clips that turn more than 2°, without it on none).
- `interact` is keyed local to `GamePivot` and cancels its motion, so it is a
  world-fixed marker (data). A marker parked at the clip origin has raw local
  y = −1 (756 of 1,159 Part 2 clips). `EN2_COM_DMG_wpn_1H_disarm_NTO` is parked
  except for one stray key at t = 1.30 s; treat it as unauthored. Measured on
  every character GLB of the six sets: each `game_pivot` / `interact` yaw of
  the table that is not 0 or ±180 equals minus the right-handed yaw of the GLB
  node (0 off), and on clips that start turned `GP + R(−yaw)·interact`
  reproduces the GLB node to 0.1 mm. In a paired clip the engine starts the partner on
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
address (`handler`). `evidence` is "read from code" for all 93 ids. Ten cases
(6, 23, 29, 30, 31, 40, 59, 70, 76, 77) were only skimmed when the table was
first written; each has since been read for a later table, and its string says
which one (footsteps 6 / 40 / 76 / 77: the sound table; 23: the combat rules;
29, 30, 31 and 70: the damage pass; 59: the effects table). No event writes a
partner's position or orientation.

An event's argument slots are in `payload` (see FX_META.md): the handler of an
event id reads only the slots listed in `fx.event_fields[id]`; other set slots
are stale editor leftovers and only named (`payload_stale`). For the feature
round cases 56 (IMPACT_EFFECTS), 59 (CAMERA_CUT) and 61
(CAMERA_CUT_TO_CHARACTER_CAM) were read instruction by instruction;
`fx.event_fields` holds that reading.

`event_name_check` compares the executable's names with the editor captions in
the fragments: 73 ids agree, 2 conflict (id 6: `LEFT_FOOT_DOWN` against the
caption `FOOTSTEP`, 13 uses; id 14: `UNUSED` against `WALK_CYCLE_POINT`,
4 uses), 18 ids exist only in the executable. `event_names` is the
caption-learned table of format 1, kept unchanged.

Editor rules (`AnimationEvent.FilterExposedProperties` 0x5c4522, read from code):
an event under a transition has trigger type and play position disabled and is
named '… on transition'; `m_nplaypos` is 'Play Position' (max 1) for PLAY_POS and
'Play Time' (max 20 s) for TOTAL_PLAY_TIME.

'Analyze impact' (`button_impact_analyze` 0x5f19da, editor only, read from code)
places, from the IMPACT position P, slot speed s and clip duration D: PRE_IMPACT
at P − 0.08·s/D, CLEAR_DEADZONE at max(P − 0.15·s/D, 0.02), BRANCH at
min(1, P + 0.1·s/D), CAN_GO_TO_MOVEMENT at min(1, P + 0.4·s/D); the game does
not recompute them.

## Criteria

`criteria` is the text form; `criteria_tree` gives each criterion as data.

Four animation values come from the ragdoll (read from
`CharacterVisual.command_update_ragdoll` 0x6bc3e2; definitions are exported as
`conventions.ragdoll_values`):

| id | value | meaning |
|---|---|---|
| 6 | `CHARACTER_PELVIS_ROTATION` (deg, −180..180) | atan2(E·up, E·(B × up)); E = world direction of −pelvis bone Y, B = horizontal unit of −pelvis bone X; 0 = body +Z up, +90 = right side up, −90 = left side up, ±180 = +Z down; exactly vertical body gives −90 (`anim_meta.pelvis_rotation`) |
| 8 | `CHARACTER_PELVIS_RAGDOLL_FREE` (truth) | expand volume fully grown for more than 0.15 s; for non-playable characters also no playable character within 1.5 m horizontal |
| 10 | `CHARACTER_PELVIS_VELOCITY` (m/s) | length of the pelvis ragdoll body's linear velocity |
| 11 | `CHARACTER_PELVIS_GROUND_HEIGHT` (m) | pelvis to first non-Character hit of a downward capsule cast (cast details not rechecked) |

The rotation bins the get-up states test are [−45, 45), [45, 135), [−135, −45) and
[−180, −135) ∪ [135, 180) (measured, pc_p2 `anim_meta.json`); which pose name goes with
which bin was not rechecked.

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
  state that owns it or lies inside the group that owns it. The editor clears
  `entry_only` on a criterion owned by a transition
  (`AnimationCriteria.FilterExposedProperties` 0x5aead6); 0 of 2,101 such
  criteria carry it in Part 2. Its captions are `FormatInterval` 0x5aa13e:
  '<name> in [min;max[', '<name> less than <max>', '<name> greater than or equal
  to <min>'.

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

A layer has two parallel lists (`SetAllSlotBlends` 0x5b4ef7). The speed is read
from `eAnimSlotList[i]` (`AnimSlot` +0x64, `AnimBlendSource` +0x84,
`PropertySequenceNode` +0x134); weight (+0x80) and duration come from
`eBlendSourceList[i]`. A source's own `speedFactor` (+0x84) is 1.0 from its
constructor (0x594ba7) and is not copied from the slot (`SetAnimSlot` 0x593ac3
copies only the clip name); the source's own update forms `slot × source` at
0x596346. Not read: who fills `eAnimSlotList`.

## Layers

Read from code (`SetupNewPage` 0x5b7788, `UpdatePagePlayPos` 0x5b61b9, mix
0x596636; the engine side is in ENGINE_CONSTANTS.md, "Layer mix"). A state's
blends are sorted into layers by `m_ilayerindex`; one blend of each layer is
picked at random when the page is set up. A state clip row carries the layer of
the blend directly under the state: `layer_index`, `additive`
(`m_tlayeradditive`), `force_playpos_1` (`m_tforcedpos`: an additive blend with
it always samples the last key) and, when the blend has a weight control,
`layer_weight` (`value` = the `ANIMATION_VALUE` name, `start`, `end`).

`clips[*].layer_use` is the sorted subset of `additive`, `base`, `upper` over
the states that use the clip: `additive` = in an additive blend; `base` = in a
non-additive blend of the state's lowest layer index; `upper` = any other. A
clip no state uses has no `layer_use`. A clip whose `layer_use` lacks `base` is
never played alone: `upper` clips replace only the bones they have tracks for,
by the layer weight (0x592c8d, 0x594cac); `additive` clips are applied as
pose(t) composed with the inverse of pose(0), scaled by the bone weight
(0x594cac, 0x592a2f). Character GLBs bake every clip as an absolute pose, and
bake a layered state's main clip without its arm layer.

Measured on the raw class nodes of the two PC sets (the console sets were not
counted here):

| | PC Part 2 | PC Part 1 |
|---|---|---|
| States | 1,290 | 1,279 |
| States with two or more layer indices | 256 | 250 |
| … with a non-additive `ACTION_LAYER_1` arm layer | 252 | 245 |
| … `HeadTurn` states, all three layers additive | 4 | 5 |
| Top-level blends / additive / "Force Playpos=1.0" | 1,575 / 12 / 12 | 1,560 / 15 / 15 |
| Blends with a layer weight control | 260 | 255 |
| States with a random pick among blends of one layer | 9 | 9 |
| Clips referenced by slots | 1,115 | 1,101 |
| Clips never in a base layer | 9 | 9 |

- Arm layers: Enemy01 84, Enemy04 90, EnemyBig 42, Rorschach 36 (Part 2);
  Enemy01 84, Enemy03 83, EnemyBig 42, Rorschach 36 (Part 1). The weight control
  is `HAS_1H_WEAPON` or `HAS_WEAPON` over 0..1; one Part 1 state uses
  `ANGLE_TO_TARGET`.
- The 9 clips: five additive `EN1_look_straight / up / Down / left / right`
  (used by `HeadTurn`; weights on `HEAD_ANGLE_TO_TARGET` over 0..−1.575 and
  0..+1.575) and four partial-body `*_COM_WPN_1H_right_arm_layer` clips (`EN1`,
  `EN2`, `RSH` and `EN4` in Part 2, `EN3` in Part 1).

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
master_world(t)  = GamePivot_m(t) + R(q_m(t)) · joint_m(t)
partner_world(t) = partner_start + R180 · (GamePivot_p(t) − GamePivot_p(0) + R(q_p(t)) · joint_p(t))
```

`q_m`, `q_p` are the clips' own `GamePivot` rotations (see *Coordinate
conventions*); the partner's comes on top of the 180° turn (three partner
clips start at −5°: `EN1_COM_DMG_counter_RSH_A`, `_X`, `EN1_COM_DMG_finish_NTO_B`).
The engine's start offset is 3-D (`interact_m(0).y` is −0.042 on
`RSH_COM_ATT_finish_EN2_B`); the table gives x and z.

Height: `partner_start` is that horizontal pair, so subtract only x and z of
`GamePivot_p(0)`. Each character then keeps the height of its own `GamePivot`
track, about 1.0 m above the ground. (The engine puts the partner's first key
at the master node's height + `interact_m(0).y`, which is the same thing where
both clips start at the same height; a clip's first key is at 1.0 m on nearly
all clips — 189 of the 190 of `Dominatrix_2.glb`, the other at 0.981.)
Subtracting the whole first key would drop the partner by a metre.

`placement.partner_start_xz` is the start, `partner_offset_xz` the same relative
to the master's own start, and `partner_yaw_deg` the turn to apply to the
partner clip (180 unless the master's GamePivot is itself turned at t = 0), in
the sense of *Sense of a yaw* above: `R(partner_yaw)` is a right-handed rotation
of −`partner_yaw_deg` about +Y. It is ±180 on every shipped pair.
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
- The **partner** enters at its own pose and its visible node holds that
  entry pose (`own_entry_pose`): it does not play its `GamePivot` motion in
  this phase. The placement block already runs every tick, but the capsule
  ignores its output until its go-to-target flag (+0xb8) is set, and the
  drawn node is the absolute target, which nothing updates for a slave before
  that (`UpdateAnimPoseAndCloth` 0x6b015d; `absolute_update` is sent only by
  the non-slave `attempt_move` 0x67f727 and by the master's `DccJoint`, which
  `DccUpdate` 0x680654 gates on the flag).
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

**The anchor swings with a turning master** (read from code, 2026-10-05).
While anchored the partner is rigid in the master *node's* frame
(`timeline.anchor_frame: "master node"`), and the master's node is its
`GamePivot` frame: the node orientation is the heading quaternion of
`m_nfaceheading`, set each frame (`CharacterVisual.UpdateAnimPoseAndCloth`
0x6b015d), the heading integrates minus the `GamePivot` twist rate, and the
velocity is `GamePivot`-local (`UpdatePagePlayPos` 0x5b56a9,
`CharacterRoot.StateActive` resume 0x56–0x58). In the master node's frame:

```
partner node pos    = I0 − (GP_m(t) − GP_m(0)) + R180 · (GP_p(t) − GP_p(0))
partner node orient = q_p(t) · r                      r = half-turn about +Y
I0 = interact_m(0), or (0.11, 0.04, 1.12) if exactly zero
```

So the anchor cancels the master's own translation and turns with the
master. `placement` is the fixed marker at t = 0 — what this rule gives while
the master has not turned. Where the master's `GamePivot` turns more than 2°
from its heading at t = 0 while the partner is anchored, the pair carries
`anchor_rotation_unverified: true` (the key name is kept from earlier tables;
the swing itself is no longer open), with `master_yaw_change_deg`,
`master_yaw_window_s`, `master_yaw_window_playpos` and
`anchor_drift_if_master_turns_m` = the engine's largest departure from the
fixed marker, `|GP(u) + R(yaw(u)) · (I0 − (GP(u) − GP(0))) − (GP(0) +
R(yaw(0)) · I0)|` (39 primary pairs, 14 master clips, 0.06–3.6 m; 60 of all
413 candidates, 22 master clips).

The clip data favour the fixed marker on most, not all, of those pairs: over
the 30 flagged pair rows with at least 3 frames turned more than 20° inside
the window, the two bodies are closer with the fixed marker on 24, with the
swing on 4 (`NTO_COM_ATT_finish_EN4_F`, the 3.6 m pair, among them), tie on 2
(median closest distance, 2 cm margin; ten of the rows are throws at about
4 m, which say nothing about contact). Whether the game shows the swing has
not been checked in a capture. Treat contact on these pairs as approximate
either way.

Inferred: that both states start on the same frame.

`UpdateAnimPoseAndCloth` (hash 0xf2bbea1b) is sent from one place,
`CharacterRoot.StateActive` (0x6bab75), once per tick. `DccJoint` 0x6a3d71
rewrites the partner's absolute target on a wall hit: capsule sweep (mask 0x20)
→ `target = master + (target − master) × fraction`; else sorted ray over
`distance + width/2` → `master + dir × (hit distance − width/2)`; the
correction, with its into-wall part removed, is added in x and z to the
master's `_vdccmove`. Master heading per tick: damp of the face heading towards
`_npreffaceheading` by `m_nmaxfaceheadingspeed × dt × factor × ramp` (skipped
while the ignore flag is set: state `m_tignorefaceheading` and |move − saved
face| ≥ state +0xa8, or `m_tforceignorefaceheading`), then `+ angular velocity
of the clip × dt`. After `DISABLE_ROTATION_INPUT` the input setters stop
writing the preferred heading; `StateActive` still writes it from an override
entity or position (event 70) and from the NPC smoothing. The target lock
becomes the override entity only in DODGE states.
`LinearDampSignedAngle` (0x791500): d = pref − cur wrapped to ±π (0x77a414);
`cur` when pref equals cur, `pref` when |d| < step, else cur ± step by the sign
of d. NPC (`m_eplayerctrl` null): the preferred heading is smoothed as
heading(lerp(dir(last), dir(pref), min(1, 10·dt))), 20·dt while attacking
(0x9e5c60, 0x9e5c68). If |pref − face| > 0.5 the ramp rises by 5·dt to 1 and the
face heading takes the linear damp with step max speed × dt × factor × ramp;
otherwise the ramp falls by 5·dt to 0.2 and face = heading(lerp(dir(face),
dir(pref), min(1, 5·dt))), 15·dt while attacking (0x9e70a0, 0x9e5bb0). A player
has ramp 1 and always takes the linear damp. Not read: the rotation-window
block. The master's heading does not enter the relative rule above.

On the consoles (read from the executables' bytes): PS3 Part 2 (`StateActive`
0x7c84e0): same three hashes (0x7d0188, 0x7d0218, 0x7cdb6c), −π/2 (0x185aafc),
default (0.11, 0.04, 1.12) (0x14fc960), `interact − offset` (0x7cdd3c), capsule
+0x10 / +0x28. Xbox 360 Part 2 (0x82e62d30): same hashes (0x82e69064,
0x82e690d8, 0x82e6917c) and constants (0x8223eb88; 0x82241384 / 0x82245380 /
0x8224537c); `vsubfp128` interact − offset at 0x82e693d8 (decoded by hand); the
quaternion product 0x82e69564–0x82e69604 and the PS3 block 0x7cdf24–0x7cdfcc
are reported equal to the PC formula.

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
| The visual node of a character in absolute mode is drawn at the absolute target; a non-absolute character's node orientation is the heading quaternion (0, sin(−h/2), 0, cos(−h/2)), h = `m_nfaceheading` | `CharacterVisual.UpdateAnimPoseAndCloth`, 0x6b015d |
| Velocity is `GamePivot`-local; angular velocity = minus the `GamePivot` twist rate; the character integrates both | `UpdatePagePlayPos` 0x5b56a9; `CharacterRoot.StateActive` resume 0x56–0x58 |
| `absolute_update` senders: the non-slave `attempt_move`, and the master's `DccJoint` gated on the partner's +0xb8 | 0x67f727; `DccUpdate` 0x680654 |
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

Not established: the parameters of the joint the engine creates between the
two capsules once the partner is anchored. (How combat code decides that a
pair may start is read and exported per pair as `trigger`: COMBAT_META.md.) The rule for a master whose GamePivot is turned at t = 0 is
the engine's value at t = 0 — the master's node is its `GamePivot` frame
(read on PC, see *Pair timeline*) — but no shipped pair exercises it
(`yaw_start_deg` is 0 on all of them). It turns the `interact` offset the
way the GLB hierarchy does (`GamePivot(0) · interact(0)`, checked on 32 turned
solo clips to 0.1 mm), and turns the partner clip by `partner_yaw_deg` =
180 + that yaw, which `partner_origin_shift_xz` and `check` now follow (they
assumed exactly 180 before 2026-10-05). The research reports are
[`re/placement.md`](re/placement.md) and [`re/events.md`](re/events.md).

### Evidence from the data (Part 2 PC)

- 141 unique equal-duration clip pairs. In 123 of them the partner clip's own
  `GamePivot` start is on the marker to under 5 cm.
- Turning the partner 180° brings the two skeletons into contact: mean closest
  approach 0.19 m, against 0.49–0.69 m for 0°, 90°, 270°. (Measured for format
  1 on the 139 pairs it had; not re-run.)
- `EN1_COM_DMG_counter_RSH_A/X/Y` are each exactly 3.925 m from the marker by
  their own `GamePivot` reading, yet meet the master when started on it
  (closest 0.187 / 0.270 / 0.233 m with the bodies turned by their
  `GamePivot`, see below) — which is what the engine does.
- `check.contact` measures both halves as `GamePivot(t) + R(q_GamePivot(t)) ·
  joint` (since 2026-10-05; before, the `GamePivot` rotation was left out).
  On the 238 primary pairs with a contact value this moved 11 rows by more
  than 2 cm (largest: `NTO_COM_ATT_counter_EN4_E` 0.094 → 0.051,
  `RSH_COM_ATT_counter_EN1_X` 0.248 → 0.270) and the four `_X` rows from
  `plausible` to `unverified`.
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

Part 2 PC: 240 primary pairs — 198 verified, 28 plausible, 14 unverified.

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

A string that names a file of the export (a `.fragment`, `.model`, `.particle`, `.bmp`, `.wav`,
`.mediastream_s` ... path) is spelled as that file is written, and the string the game stores is
kept in the same record under `stored`, `{field: value as stored}`, where it differs (for a map
whose keys are respelled, `{key written: key stored}` beside the map). `asset_names` at the top
level says so (`spelling: "export"`, `respelled`: how many strings). `--names stored` writes the
stored strings and neither key. See "Asset strings in the JSON files" in the README.

```
format       "watchmen-anim-meta/2"
coordinate_frame       "right-handed-true"   absent in a mirrored-frame file
coordinate_frame_note  one sentence          (--frame mirrored, toolkit 1.3.0)
conventions  { key: sentence }   units, up_axis, handedness, playpos, names,
                                 criteria, pair_weapons, pair_timeline,
                                 transition_start, evidence, body_space,
                                 motion_root, interact, pair_space,
                                 absolute_motion, frame_rate_scale,
                                 engine_values (true frame only)
event_names  { event id: name learned from editor captions (format 1 table) }
event_name_check  { agree, conflicts: [ {event_id, exe, caption, uses} ], exe_only: [ids] }
event_semantics   { event id: { name, effect, value, moves_character,
                                affects_partner, handler, evidence } }
enums        { family: { id: name } }                    34 families
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
face_format  "watchmen-face/2"          face { ... }       see "The face block"
combat_format "watchmen-combat-meta/1"  combat { rules, combo_databases, character_defs,
                                                 ai_defs, weapons, classes, ... }
                                                           see COMBAT_META.md
fx_format    "watchmen-fx-meta/1"       fx { effects, effect_defs, damage_rule, weapons,
                                             particles, characters, camera, event_fields, ... }
                                                           see FX_META.md
```

Part 2 PC: 5 classes, 1,290 states, 2,593 transitions, 5,099 events on states,
1,159 clips, 413 pairs.

**state** — `name`, `path`, `state_id`, `master_of`, `clips` (`clip`, `weight`,
`layer`, `speed`, `blend_position`, `layer_index`, `additive`,
`force_playpos_1`, and `layer_weight` when the blend has a weight control; see
"Layers"), `main_clip`, `loop`, `walk_cycle`, `start_playpos`,
`ease_in_s`, `absolute`, `defines_movement`, `defines_rotation`,
`attack_state`, `special_handling` and `animation_type` (each `id`, `name`),
`animation_type_stored`, `animation_type_basis`,
`duration_s`, `speed` (and `speed_basis` when the first layer's slots differ),
`start_basis` (`state_default`),
`criteria`, `criteria_tree`, `weapon` (`UNARMED` / `BASH_1H` / `BASH_2H` when
the state requires one), `events` (the state's own and those of the
`SoundEvents/SE_<clip>.fragment` lists it includes, the latter marked `source:
"SE_<clip>.fragment"`: sounds, speech and footsteps mostly), and `impact`
(`count`, `time_s`,
`distance_m`, `position`, `direction`, `damage_pose`, `damage_pose_name`,
`bone_id`) when set. Added by the blocks: `face` / `inflicts` (face),
`group_criteria`, `criteria_rendered`, `combat` (combat), `fx` (effects).

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
written, which may be retimed). Added by the fx block: `payload`,
`payload_stale`.

**transition** — `owner`, `owner_kind` (`state` or `group`), `name`, `to`,
`to_kind`, and when set `criteria`, `ease_in_override_s`, `fallback`, `start`:
`{rule: "override_playpos", playpos}` or `{rule: "sync_markers", markers:
[[local, remote], …], gate: [min, max]}`. `to` is the resolved target; a
reference to the fragment's own slot resolves to the state group that
instances the fragment.

**game_pivot / interact** — `pos_start`, `pos_end`, `yaw_start_deg`,
`yaw_end_deg`, `position_keyed`, `rotation_keyed`.

**clip** — the header facts, `loop` (true when a looping state plays the clip,
as its main clip or as a member of its blend; an arm-layer overlay does not
count), `events` and `weapon` of the states that
use it as their main clip, `speeds` (the slot speeds the game plays it at as a
main clip), `used_by` (`class`, `state`, `path`, `main`, `speed`), `layer_use`
(on a clip a state uses; see "Layers"), and `pairs`
(`pair` = index into the top-level `pairs`, `role`, `other_clip`,
`other_class`).

**pair** — `master_class`, `master_state`, `master_path`, `master_clip`,
`master_of`, `master_criteria`, `master_group_criteria`,
`master_opponent_models`, `partner_class`, `partner_state`, `partner_path`,
`partner_clip`, `partner_criteria`, `partner_group_criteria`,
`group_criteria_accept`, `master_duration_s`, `partner_duration_s`,
`same_duration`, `primary`, `confidence`, `placement`, `weapons`, `timeline`.
Added by the blocks: `face` (face), `trigger` (combat), `camera_cuts`,
`camera_return`, `fx` (effects).

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

`animation_type` is computed as the game does when the state is initialised
(`initialize_external` 0x5f0e63 → `DetermineAnimationType` 0x5f277a): the first
ACTION criterion with a mapped action (0x5ebeb0), or ENUM CHARACTER_MODE =
STUNNED (0x5ebe9b), among the state's criteria and then its groups', innermost
first; an ANY_OF takes the kind of its first child and the values of the ANY_OF
node itself. The stored property is overwritten in the game and kept here as
`animation_type_stored` (read from code; that the handler runs for every state
is inferred, `animation_type_basis`). Measured: the two differ on 150 of 1,290
states in each Part 2 set and 196 of 1,279 on PC Part 1 (the rule was read from
the Part 2 PC executable only).

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
start_playpos, playpos_per_second, anchor_frame
anchor_rotation_unverified, master_yaw_change_deg, anchor_drift_if_master_turns_m,
master_yaw_window_s, master_yaw_window_playpos
```

`mode` is `own_entry_pose`, `blend_to_anchor`, `anchored`, `released` or
`not_absolute`. `to_s` / `to_playpos` of the last phase are `null`.

`skeletons` and `check.contact` are present only when a binds directory was
given; a pair whose clips have no bind there (or no skeleton key) has a
placement without `check.contact`, and `watchmen characters` says how many.
A class whose state names an event-list fragment the data does not contain
lists it in `classes.<Class>.missing_event_lists` (1 on Part 2, 5 on Part 1). A `clips` entry with no `file` is a clip a state names that does not
ship (4 on Part 2 PC, Part 1 leftovers).

## The face block (`face_format: "watchmen-face/2"`)

*Format 2 (2026-10-04) adds speech: `face.talk_clips`, talk segments with a
known length, and the speech categories. A table with `watchmen-face/1`
found in an output folder is rebuilt by `characters`.*

A character's head is a second character with its own animation class (the
`AnimationClass*Face` fragments).  It is not keyframed and not driven by body
states: the body feeds it four inputs and the face class turns them into
one-frame poses.  `anim_meta.json` records that rule and what follows from it for
every body state and pair.  The block is additive: tables without face fragments
have neither `face` nor `face_format`, and no other key changes.

### `face` (top level)

| key | content |
|---|---|
| `conventions` | the units and words used below |
| `drivers` | the four inputs with their engine addresses: `CHARACTER_MODE` (enum; sent to the head when the body controller updated, the character moves or it is being pushed; `rule` = when the mode is COMBAT), `NORMAL_ATTACK` (action, every frame of an attack state), `HITTAKEN` + `DAMAGE_POSE` (a hit; `DAMAGE_POSE` on the head is never cleared, initial value 0), `START_SPEAK` / `STOP_SPEAK` (stop: every frame no voice has the character root as pivot — speech, trigger sounds, footsteps on a surface that has a footstep sound) |
| `timing` | `ease_in_s` (0.21 on all states but one: 0.37 on Enemy04Face `KnockDownMiddleLeft(ClosedEyes)`, the Twilight Lady / Dominatrix knock-down face), `hit_hold_s` per class (0.75 for Enemy01Face and Enemy04Face, null for NiteOwlFace: it leaves a hit when its grunt ends), `hit_hold_note`, `simulation_hz` |
| `attachment` | how the head rides the body: attach bone, the 90° yaw, the bones copied from the body every frame |
| `charvisual` | per CharVisual fragment: `visual`, `body_class_id`, `face_class_id` |
| `body_class` | per body class: `face_class` (null = no face controller), ids, the fragments it was read from |
| `classes` | per face class, see below |
| `not_established` | what the executable did not yield; none of it is baked |

### `face.classes.<name>`

`class_id`, `engine_name`, `fragment`, `clip_dir`, `pose_family` (`EN1` / `BS2` /
`NTO` — the `FACE <family>/<pose>` animations of a character GLB), `default_state`,
`groups` (path, criteria, `choose_random_state`), `transitions`, and

- `states[]`: `name`, `path`, `kind` (`IDLE`, `TALK` or the state's own name),
  `clips` (pose clip names), `glb_animation_names` (`"FACE EN1/DamageL"`),
  `ease_in_s`, `criteria`, `criteria_tree`; `clip_mix` when a state has two
  slots in one blend without a control parameter: `rule: "first_child_only"`,
  `shown` (the clip that plays), `weights` (`[1.0, 0.0]`), `evidence`. Such a
  blend plays its first child alone — the slot with the lowest `siblingOrder`
  (`command_evaluate_blends` 0x59e905, `SetAllSlotBlends` 0x5b4ef7, mixer
  0x596532). The Attack state of Enemy01Face and Enemy04Face is `Attack1`
  alone; `MouthShout_EyesAnger` never shows. The slots' `m_nweight` and
  `m_npriority` have no reader in the executable.
- `hit_pose_to_state`: DAMAGE_POSE name → the FIRST face state a hit with that
  pose selects.
- `hit_pose_then`: DAMAGE_POSE name → `{face_state, clips, after_s, basis}` where
  the hit state is left for another state before its hold ends. Enemy01Face and
  Enemy04Face: `STUN_MIDDLE` → `HitCenter` for one controller update, then
  `Retreat` (`MouthClosed_EyesOpen`), which stays until the next hit with
  another pose. This is the silent-character case and sound-dependent: with a
  pain sound on the root `HitCenter` lasts min(sound length, 0.75 s).
- `idle_cycle`: `states[]` (`name`, `clips`, `min_s`, `ease_in_s`), `rule`,
  `evidence`, `entry`.  The cycle is random and free-running: the idle group is
  entered at a uniformly random member, and after `min_s` in a state it is
  re-rolled every frame from a random member.  Enemy01Face: IdleA
  (neutral, >= 3 s) / IdleB (`Provocatively`, >= 0.5 s).  Enemy04Face: IdleA / IdleB
  = eyes closed — this is the game's blink.  NiteOwlFace has one idle state.
  `entry`: `first_segment` (`"random"` when the class's default state is the
  idle group — Enemy01Face, Enemy04Face — else the index of the default idle
  state: NiteOwlFace `IdleB`), `after_transition` (`"random"`: every entry by a
  transition goes through `command_get_valid_state` 0x5f076f with a random
  start), `default_state_is`.
- `talk_cycle`: the same for speech (members re-rolled every 0.2 / 0.15 s; no
  visemes, no audio amplitude).
- `hit_hold_s`: seconds a hit pose is held before the class returns to idle —
  unless the face class leaves earlier: a `STUN_MIDDLE` hit on a silent enemy
  changes to `Retreat` on the next update, and an attacking character changes
  to `Attack` (`face.conventions.hit_hold`).

The face class is evaluated every frame while the head is in a camera frustum
within 9 m (`face.conventions.evaluation`) (X360 Part 2: same 9.0 and the same
type 0x23 exception, `0x82fd9430`).

### On a body state: `face` and `inflicts`

`face` is null when the class has no face controller, else

| key | content |
|---|---|
| `class` | the face class |
| `play_time_s` | length of one pass of the state |
| `category` | `idle_only`, `attack`, `hit_at_entry`, `event_driven`, `dead` |
| `inputs[]` | what the game sends while the state plays: `t_s`, `input` (`NORMAL_ATTACK`, `HITTAKEN`, `START_SPEAK`, `DEAD`), `source`, `evidence`, `established`; for events also `trigger`, `raw`, `playpos`; for hits `damage_pose` + `damage_pose_id`, or `damage_pose_any_of` + `face_state_by_pose` when several poses select the state; `every_frame` on `NORMAL_ATTACK`; `until` on `START_SPEAK` |
| `track[]` | the face states that follow: `from_s`, `to_s` (null = to the end), `face_state`, `clips`, `ease_in_s`, `from_playpos`, `to_playpos`; `one_of` on a `HIT_BY_POSE` segment; `clip_mix` on a two-slot state; `sound_dependent` when the segment's end depends on a sound's length |
| `confidence`, `confidence_basis` | `high` = every input and time is read or data; `medium` / `low` name what is assumed |
| `notes[]` | e.g. SPEAK events, whose timing is not in the animation data |

`track` holds only the deterministic part.  `IDLE` means "the class's idle
cycle", `TALK` "the class's talk cycle": apply those rules at run time.

`inflicts[]` lists the hits the state's events deliver to the *other* character
(`event`, `event_id`, `t_s`, `trigger`, `raw`, `playpos`, `damage_pose`,
`damage_pose_id`, `pose_basis`, `pose_established`, `kills`, `evidence`).

### On a primary pair: `face`

`clock` (seconds since both states started; play position =
`timeline.start_playpos + t * timeline.playpos_per_second` on both clips),
`play_time_s`, and `master` / `partner`, each null or `{class, category, inputs,
track, confidence, confidence_basis}`.  The partner's record contains the
master's `inflicts` as `HITTAKEN` (and `DEAD`) inputs on the shared clock — this
is the victim's hit-driven track.

### In the character GLBs

`animations[i].extras.watchmen.face` on every body clip of a character with a
face rig: `rule` (`engine`), `pose_family`, `face_class`, `baked_from` (`class`,
`state`, `path`, `pair`, `role`, `other_clip`, `slot`), `candidates`,
`distinct_tracks`, `confidence`, `track` (as above), `poses[]`
(`written_time_s`, `pose`, `ease_in_s` — what is keyed), `not_baked[]`,
`idle_cycle_baked`; or `note` when the metadata has no track for the clip.
`skins[1].extras.watchmen.face`: `head_model`, `pose_family`, `face_classes`,
`anchor_node`, `track_choice` (the rule in words), `idle_cycle_baked`, and
`game_head` when the head was taken from a head collection: `head`, `static`
(the head it replaces), `head_model_type` (+ `_name`), `head_by_type`, `basis`,
`texture_sheets` (the collection node's records: `slot`, `pivot`, `lod`,
`path`, `sheet_id`), `sheet_overrides` (sheets that replace a layer: `sheet`,
`unique_id`, `texture`, `overrides`), `dropped_body_models`.  `FACE …` animations carry
`extras.watchmen.face_pose`: `pose`, `face_states[]`, or `synthetic: true` on the
two toolkit-made loops (`FACE SYNTH Blink` / `Talk`).

### How a clip gets its track

A clip can belong to several states. Per body clip the writer takes the face
track of the primary pair the clip plays in; else of the states whose main
clip it is; else of the states that blend it with their main clip in the same
layer (the 1H / 2H weapon, direction and speed blends; the "blend on NONE"
clip lists such as `AnimsToAdd` do not count). Among several candidates: the
track most of them share, then one that is not idle throughout, then the
higher confidence, then the first by (class, path). `candidates` and
`distinct_tracks` say how contested the choice was. This choice is the
toolkit's — in the game the state decides — and it is recorded per clip.

Baked: hit, attack and dead segments at their times, each easing in over the
state's own ease-in (0.21 s; 0.37 s for the Twilight Lady / Dominatrix
knock-down face) from whatever was shown before; `IDLE` as a seeded instance
of the class's idle cycle (seed = CRC-32 of the clip name; off with
`--no-face-idle`). Each idle segment starts in a seeded random member of the
idle group, as the engine enters it (`idle_cycle.entry`; about half the
Enemy01 / Enemy04 segments start in IdleB — the sneer, or closed eyes for at
least 0.5 s); a table without `idle_cycle.entry` gives the first idle state,
as before 2026-10-05. A change that could not return before the clip ends is
left out: a clip whose track opens with an idle segment ends in the idle
state it starts in, any other in the first idle state, and an entry draw that
could not come back is replaced by the first idle state. Not baked, and listed in `not_baked`:
`TALK`, sound-dependent segments, `HIT_BY_POSE`. `--face-rule legacy` writes
none of this (one pose per clip, chosen from the clip name, as in 1.3.0).

**Talk (format 2).** A TALK segment is baked when an animation event of the
state starts ONE fixed voice line: a SOUND event with the speak flag whose
definition plays a single wave. The segment then has an end (`talk`: `wave`,
`talk_s`, `ends_s`), the simulation gets `STOP_SPEAK` at that time, and the
track holds a seeded instance of the class's talk cycle from the event to
one frame before the end. In the shipped data these are four clips:
`BS2_COM_ATT_cattleprod_counter_NTO_A`, `…_NTO_B`, `…_RSH_A`, `…_RSH_B`
(2.45 / 5.23 / 2.81 / 2.02 s), on the Twilight Lady and — the clips are
shared — the ten Dominatrix GLBs. Lines the AI requests (random voice, random
wave) are not baked; `face.talk_clips` lists them per character with
`talk_s` (min / max / mean / n) per voice, the length a talk clip for that
line needs. Speech category 2 (grunts, shouts) never opens the mouth, and
neither does category 0. The length of a talk is that of the wave played
(pitch 1.0, no random pitch on any speak wave); which wave and voice is drawn
at play time, and the line can be suppressed. Talk ends on the first frame no
voice at all has the character root as pivot. A talk bake for an AI line would
have to add the line's `start_delay_s` and be keyed by (character, voice,
wave); speech stays unbaked by default.
`sound_meta.json` (`docs/SOUND_META.md`) has the sound side of the same
events.

### What is not established

Which voice line and wave plays, hence how long a voice line or grunt lasts;
the character mode of a body state whose criteria do not fix it (the rule is
read — `face.drivers.CHARACTER_MODE.rule` — but it is game state); the runtime modifiers of an attack's damage pose (combo, direction,
size, height: `inflicts` gives the state's own pose and marks it
`pose_established: false`); whether the attacker stands behind the victim (the
pose then becomes its `*_BACK` variant; X360 Part 2 `0x82be6858`: same −0.2
threshold and the same pose map). `face.not_established` carries the
same list.

## In the GLB

| Where | What |
|---|---|
| `asset.extras.watchmen` | `format`, `conventions`, `coordinate_frame` + `coordinate_frame_note` (true frame; absent = mirrored) |
| `skins[0].extras.watchmen` | the skeleton record above |
| each joint node's `extras` | `bone` (real name), `parent` (joint index, −1 for a root) |
| `animations[i].extras.watchmen` (not imported by Blender's stock importer; see README) | the clip record (`clip`, header facts, `loop`, `game_pivot`, `interact`, `weapon`, `speeds`), with `events` timed (`time_s`, `written_time_s`; `null` for leave-state events), `written_fps`, `written_duration_s`, `states`, and `pairs` (primary only) each carrying `role`, `other_clip`, `other_class`, the two state names, `same_duration`, `primary`, `confidence`, `placement`, `weapons` and `timeline`, and — when the pair has them — `camera_cuts`, `camera_return` (FX_META.md: the procedural camera of a finisher or counter, on the pair clock of `timeline`) and `trigger` (COMBAT_META.md: what starts the pair). The events carry `payload` / `payload_stale` |
| `asset.extras.watchmen.fx_attachments` | the emitters and light flashes the game hangs on the character's joints (Rorschach, Nite Owl, Twilight Lady; FX_META.md) |

Joint nodes keep their `b0…bN` names and stay flat under `root`, so existing
importers are unaffected; the order is the palette order, which is
`joint_names`. Synthetic animations (`GRIP 1H`, face poses) have no clip record
[2026-10-04: the `FACE …` animations carry `extras.watchmen.face_pose`, and
body clips of a character with a face rig carry `face`; see "The face block"].

In 1.3.0 the `extras` path was exercised by the synthetic tests only;
`watchmen characters` was not re-run on real data for it. [2026-10-04: for
1.4.0 all 26 character GLBs were exported in full from the real game data and
passed glTF-validator with 0 errors; the clip, pair and face extras were read
back from them.]

## Outfits and weapons in the GLB

*Added 2026-10-04.* A character GLB built with the default `--parts game`
shows one outfit and no weapon (see the README). The scene is named `game`.
`asset.extras.watchmen.parts`:

| key | what |
|---|---|
| `mode` | `"game"` |
| `member_shown` | number of the outfit in the scene (1), `null` for a character without a collection node (the players, the reconstructed `Dominatrix_3`) |
| `members[]` | every outfit of the variant in the engine's order: `index` (1-based), `head_model_type`, `head_model_type_name`, `models`, `shown`, `not_exported` (models the export does not build), and — for a variant with several outfits — `nodes` (its `OUTFIT <index> <model>` nodes) and `sheets` (`{model: {texture: sheet name}}`, sheets other than the first) |
| `common_models` | models in the main mesh: worn by every outfit with the same sheets |
| `shown_nodes` | the outfit nodes that are in the scene |
| `alternatives[]` | the hidden outfit nodes: `node`, `model`, `members` |
| `weapons` | `shown` (node names in the scene; only Twilight Lady's whip), `nodes[]` with `node`, `model`, `collections`, `weapon_types` (`BASH_1H` / `BASH_2H`), `shown`; `attach_bone`; `player` (true: picks up any weapon); `rule` |
| `hidden_nodes`, `hidden_under` | every node outside the scene, and where: children of the node `alternatives`, which is in no scene; all use skin 0 |
| `rule`, `order_basis`, `outfit_rule` | the engine rules in words, with addresses |

To show outfit `k`, hide the nodes in `members[shown].nodes` and show those
in `members[k].nodes`. To arm the character show one `weapons.nodes[].node`.
Outfit nodes of the same model share their accessors and differ in material.
A file built with `--parts all` has no `parts` record and no `alternatives`
node. `asset.extras.watchmen.reconstruction` (`shipped: false`, `base`,
`note`) marks a variant that is not in the game data.

`clips[name].weapon_use` in `anim_meta.json`, and the same object in each
animation's `extras.watchmen`: `{classes, basis}`. `classes` is a subset of
`UNARMED`, `BASH_1H`, `BASH_2H`: the weapon class the clip is played with.
`basis` says how it is known: `criteria WEAPON_ANIMATION_TYPE` (the state
tests the class) or `blend on HAS_2H_WEAPON` / `HAS_WEAPON` (the clip is the
high or low end of such a blend layer; each state clip row now carries its
`blend_position`). 177 of the 1,159 Part 2 PC clips have it (BASH_2H 60,
UNARMED + BASH_1H 52, UNARMED 39, BASH_1H 11, armed either way 11, all three
4); a clip without it is not tied to a weapon by the data.

## Weapons

Weapon models are rigid-skinned to the `Attach RHand` joint (index in
`attach_joints`), grip authored at the model origin; Twilight Lady's is placed
from her fragment's `HandAttach` node. A state's `weapon` list says which
stance it needs, a pair's `weapons` which stance each side has. The attach
transform is that joint's own track in each clip.
