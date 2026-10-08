# Effects, camera cuts and rumble (`fx`, format `watchmen-fx-meta/1`)

What a move shows besides the animation: which effects a hit fires, where the finisher camera
stands, when the pad rumbles. `wlib/fx_meta.py` adds it to `anim_meta.json` (`watchmen animmeta`,
`watchmen characters`); `watchmen fxmeta EXTRACT_OUT OUT.json [ANIM_META.json]` writes the same
data as one stand-alone table.

Part 2 PC: 81 effects, 3 effect definitions, 21 weapons, 38 particle assets, 14 characters;
279 states with an `fx` section (259 camera cuts, 41 returns, 317 impact effects, 231 rumbles,
141 look-ats, 144 weapon events, 69 slow-motion intervals); 118 of the 413 pairs carry camera
cuts (61 of the 240 primary pairs, 773 / 383 cuts).

Evidence marks, as everywhere: **read** = traced in the executable (address given), **data** =
read from the game files, **inferred**, **not established**. The top-level `fx.evidence` dict
has one line per table.

## Where it is in `anim_meta.json`

A string that names a file of the export (a `.fragment`, `.model`, `.particle`, `.bmp`, `.wav`,
`.mediastream_s` ... path) is spelled as that file is written, and the string the game stores is
kept in the same record under `stored`, `{field: value as stored}`, where it differs (for a map
whose keys are respelled, `{key written: key stored}` beside the map). `asset_names` at the top
level says so (`spelling: "export"`, `respelled`: how many strings). `--names stored` writes the
stored strings and neither key. See "Asset strings in the JSON files" in the README.
The keys of `fx.particles` and the `particle` / `model` values are such strings (PC Part 2: 183
`.particle` and 19 `.model` strings are stored in another letter case than their file has).

```
fx_format            "watchmen-fx-meta/1"
classes.*.states[*].events[*].payload        { property: value }   argument slots that are set
classes.*.states[*].events[*].payload_stale  [ property ]          set slots the handler ignores
classes.*.states[*].fx     { impact_effects, camera_cuts, camera_return, rumble, look_at,
                             weapon_events, effect_events, depth_of_field, slow_motion }
pairs[*].camera_cuts       [ cut ]          the master's cuts on the pair's clock
pairs[*].camera_return     { time_s, playpos, clip_time_s, transition_s, set_in_vector } | null
pairs[*].fx                { end_s, shots, slow_motion, impact_effects, weapon_cases, rumble,
                             weapon_events }
fx                   { format, evidence, conventions, event_fields, effects, effects_by_id,
                       effect_ids, effect_defs, class_effect_defs, damage_rule, weapons,
                       particles, gfx_matrix, characters, camera, rumble, event_effects,
                       fake_twilight_lady_weapon, counts, not_established }
```

Only keys are added: with them removed the table is byte-identical to the one written without
the module (checked on Part 2 PC against the 12,380,171-byte table of the r4 export). The
additions are 2.04 MB (16.5 %). `clips.*.events` share the state records, so they carry
`payload` too, and through `clip_extras` so do the animations of the character GLBs.

## Event payload

An `AnimationEventWM` node has generic argument slots besides the four core fields: three entity
references `_etarget00..02`, one integer `m_ivalue00`, nine more floats `m_nvalue02..10`, three
booleans `m_ttruth1..3`, two vectors `m_vvalue1/2` (and `m_tforceupdateblends`). `payload` lists
the slots that are set, under those property names.

Event nodes are copied in the editor and keep the values of the event they were copied from: a
`CAMERA_CUT` usually still carries the two vectors of an `IMPACT_EFFECTS` event. For the event
ids whose handler is decoded, `fx.event_fields[id]` names the slots that handler **reads**
(with the argument name and its meaning); a set slot the handler does not read is left out of
`payload` and named in `payload_stale`. For any other id every set slot is in `payload`.
Part 2 PC: 1,377 of 5,099 events have a payload, 650 name stale slots.

`fx.event_editor_params` is the editor's view of the same slots: for each of 16 event ids the
caption, group, dropdown family and range of every argument `AnimationEventWM.FilterExposedProperties`
(0x5c1767) exposes (read from code; editor data, not game behaviour; id 90
DEACTIVATE_DEPTH_OF_FIELD has an editor entry and no handler case). For an id it does not list
the editor hides every generic slot. `payload_editor_hidden` on an event names its set slots
the editor does not show for that id (measured on Part 2: 53 events outside the 16 ids have
set slots; `m_nvalue09` of CAMERA_CUT, which the handler reads and the editor hides, is set on
0 of 259 events).

Decoded ids (case addresses in `CharacterRootLogic.command_animation_event_received` 0x6a525e):
SOUND 9, CAMERA 18, KILL_ANIMATION_PARTNER 20, EXTEND_COMBO_TIME 35, SPEAK 37, LOOK_AT_TARGET 45,
IMPACT_EFFECTS 56, SAFE_RAGDOLL_COLLISION 57, CAMERA_CUT 59, CAMERA_CUT_TO_CHARACTER_CAM 61,
KNEE 72, RAGDOLL_MODIFIER 73, DO_AUTO_ALIGN 80, RUMBLE 82, ACTIVATE_DEPTH_OF_FIELD 89.

## The `fx` section of a state

Every entry carries the times of its event record — `playpos`, `time_s` (position on the clip),
`play_time_s` (seconds since the state was entered at its start position, at the slot's speed;
see *Events* in ANIMATION_META.md) — plus `trigger` when it is not `PLAY_POS` and
`fires_first_pass: false` when the event is created already fired. A state without such events
has no `fx` key.

| List | Event | Fields |
|---|---|---|
| `impact_effects` | IMPACT_EFFECTS (56) | `damage_pose`, `damage_pose_name`, `hit_position` (HEAD / BODY), `local_position`, `local_direction` (the acting character's visual space), `ignore_weapon`; `extra_effect` = an effect key when the event also fires an effect of its own (`m_ttruth3` + `_etarget01`: 26 events, mostly the cattle-prod discharge); with `m_ttruth1` set the event deals close-combat damage itself (`CharacterRootLogic.SetCloseCombatDamageToTarget(victim, m_ecuranimstate, m_nvalue)` 0x6ae57f): `deals_damage: true` and `override_damage` (the damage when > 0, else the state's default); `truth1` / `value` carry the same two values under their earlier names |
| `camera_cuts` | CAMERA_CUT (59) | see below |
| `camera_return` | CAMERA_CUT_TO_CHARACTER_CAM (61) | `transition_s`, `set_in_vector` (the character camera is first aimed looking from the actor toward the partner, 16.7° down, heading turned by −45.84° (atan2(x, z) decreases by 0.8 rad)) |
| `rumble` | RUMBLE (82) | `duration_s`, `power` (0..1), `fade` |
| `look_at` | LOOK_AT_TARGET (45) | `duration_s`, `fov_factor`, `target` (`self` / `attack_target`), `orbit_180` — a timed look-at of the *character* camera, players only |
| `weapon_events` | 32 / 36 / 58 / 75 | `action`: `steal_from_partner`, `pick_up`, `drop`, `drop_with_animation` |
| `effect_events` | STARTING_UBER_RAGE (60) | `effect_ids` [12, 13] |
| `depth_of_field` | ACTIVATE_DEPTH_OF_FIELD (89) | `fade_s` |
| `slow_motion` | derived from the cuts | `from_s`, `to_s`, `time_multiplier`, `real_s`, `real_s_basis`, `blend_s`, `blend_from_multiplier` — every interval whose world time multiplier is not 1 (57 slow, 12 faster than 1): a cut's multiplier holds until the next cut or the return; times are play time; `real_s` = (to − from) / multiplier takes the cut as hard (`real_s_basis: "no_blend"`); `blend_s` is the cut's `transition_s` and `blend_from_multiplier` the multiplier the blend would start from (the previous cut's; 1.0 for the first cut and after a return) — see *Slow motion and blends* |

What an impact's damage pose selects — the definition slots per weapon case, the rumble and the
camera recoil — is `fx.damage_rule.by_pose[pose]`, not repeated per event.

## Which effect a hit fires

`CharacterEffectDef.command_play_damage_effect` 0x6673d0 (read), on the **victim's**
definition (`fx.effect_defs`; three ship: enemies, Rorschach, Nite Owl):

1. Pose 0: nothing. Upper poses (1, 2, 3, 7, 8, 9, 13, 14, 15, 19, 20, 21, 23, 25, 27;
   `IsUpperDamagePose` 0x7f077c) take the `head*` slots, the others `body*`.
2. The inflictor is in uber rage → `*uber`; else a killing hit → `*kill`; else a weapon →
   its effect type (`fx.weapons[*].effect_type`): WOOD → `*weaponwood`, STEEL → `*weaponsteel`,
   SHARP → the one `sharpweapon` slot, **TASER → effect id 1 `ELECTRIC_ARMOR_DISCHARGE` first,
   then the STEEL slot**; else poses 1, 2, 5, 6, 23, 24 → `*fast`, any other → `*heavy`
   (so the "light" poses 3 and 4 take the heavy effect).
3. On top: poses 17, 18, 27, 28 → `knockdown`; poses 19–22 → `stun`.

`fx_meta.damage_slots(pose, case)` returns the slot list (`case`: `unarmed`, `wood`, `steel`,
`sharp`, `taser`, `uber`, `kill`), `fx_meta.resolve_slots(fx, effect_def, pose, case)` the effect
keys. An IMPACT_EFFECTS event passes kill = false and the acting character's weapon (none with
`ignore_weapon`).

`fx.effects[key]`: `name`, `effect_id` (+ name; −1 = none), `particles` (particle asset →
`fx.particles`, `placement` ENTITY / POS_AND_ORIENT, local transform), `sounds` (`definition` =
a key of **sound_meta.json `definitions`**, `placement`), `speaks`, `children`. Keys are
sound_meta's (`<fragment>#<node id>`); an `effect_defs` key equals sound_meta's
`effects.damage_effect_sets` / `characters[*].damage_effects` key. Sound content is not
repeated here.

`fx.particles[asset]`: `emit_duration_s` and `loop` of the system, the longest `particleLife`
of its types (`particle_life_s_max`), `types`, `file_found`. An emitter stops emitting at
`duration` unless it loops; a fired effect is visible for about duration + particle life.

`fx.gfx_matrix`: the GFX half of the effect type × surface matrix (55 packages, 2 with rows; only
TRASHCAN has particles). The sound half is sound_meta.json `footsteps.rows`, same effect type id.
Package order = `COLLISION_EFFECT_TYPES` id (0x75bb96); these are not the `EFFECTS` ids of the
hit effects.

`fx.class_effect_defs`: body class → effect definition (through the characters that use it).

## Camera cuts

A finisher or counter has no animated camera. Its shots are `CAMERA_CUT` events on the master's
state (on the partner's state in four pairs, see *On a pair*), each of which parameterises a
procedural camera (`CameraCombatSpecialCuts`).

A cut: `transition_s` (0 = hard cut), `look_at` (`actor` / `attack_target`), `look_at_bone`
(`CHARACTER_BONE_TYPE`), `look_at_point` (`joint` or `root`), `look_at_joint` (the skeleton
joint, `CharacterVisual.SetupBoneMap` 0x67a31e; `null` for bone 18, which is not a joint but the
looked-at character's root node + `look_at_height_m` — 4 of the 259 cuts), `look_at_height_m`,
`distance_m`, `height_m`, `angle_deg`, `fov_deg` (vertical), `time_multiplier`, `placement`,
optional `shake` {`time_s`, `time_factor`, `size`}. "Attack target" is the acting character's
*animation partner*, read once at the first cut of a cut session and kept for the following cuts
(`command_set_cut_data` 0x6325c5); the key value `attack_target` is kept.

Placement (read: `SetValidStartPos` 0x6341f7). The formulas are in **engine coordinates**
(left-handed). GLBs of the default true frame have x = −engine x: negate x of the actor,
target and camera positions before using the formulas and x of the result after, or call
`fx_meta.cut_camera(..., frame="true")`, which does both; in true-frame numbers the two rules
read h = atan2(d.x, d.z) − radians(`angle_deg`) and v = normalize((l.z, 0, −l.x)). With
`--frame mirrored` GLBs the formulas apply as written:

- `angle` (`angle_deg` ≠ 0): d = normalize_xz(target − actor), base = actor; when the cut looks
  at the attack target d = −d and base = target. Position = base + `distance_m` ·
  (sin h, 0, cos h) + (0, `height_m`, 0), h = atan2(d.x, d.z) + radians(`angle_deg`). When
  the sweep to that position is blocked the cut falls to the side rule below
  (`cut_camera()` returns those two positions as `fallback`).
- `side_of_pair` (`angle_deg` = 0): v = normalize((−l.z, 0, l.x)), l = target − actor (3-D); v is
  flipped when it points away from the camera node's position; position = actor + l / 2 +
  `distance_m` · v + (0, `height_m`, 0), so its y is the midpoint of the two roots' heights +
  `height_m` (the same as before in pair space, where both roots are at one height); if the
  sweep to it is blocked, the second try is the other side.
- `previous_position`: the previous cut's target position is kept; when there is no previous cut
  it is the character camera's position. It is valid without a partner and without a sweep.

**The position is fixed in the world for the whole shot.** Each frame only the aim is recomputed
from the look-at point — the joint's world position, or for bone GAME_PIVOT the looked-at root +
`look_at_height_m` — with up +Y, no roll (hold update 0x633011). `UpdateWorldPos` 0x633f28, which
would move the camera with the looked-at root, is registered but has no caller on PC, X360 or
PS3; toolkit tables written before 2026-10-05 described that follow as if it ran.
The effects' `local_position` / `local_direction` / `local_orientation` and the attachment
offsets below are engine values too, in both frames.
`actor` / `target` are the root positions of the character carrying the event and of its
animation partner. A teleport puts the root at P, the capsule at P + 0.5 · height (2.0) and the
visual node on the capsule (0x6b2af5), so the root is on the floor, 1.0 m under the visual
frame; that it is still there at the moment of a cut is inferred (how the root follows the
capsule each frame is not established).
`fx_meta.cut_camera(cut, actor, target, look_at_point, previous, camera)` does the arithmetic
and returns `position`, `look_at`, `side` and `fallback`; a kept position needs `previous` or
`camera` (`ValueError` otherwise). It does no collision test: the engine accepts a position when
a sweep of width = height = 0.2 from the look-at point to it hits nothing (both characters'
capsules ignored; no partner means invalid): a sphere of radius 0.1 (capsule with zero segment,
0x50a8d3); a sweep longer than 25 m horizontally is scaled down to 25 m; result = t of the first
hit not on an ignored node, −1 when none. On rejection while the cut camera is active it
returns to the character camera with 0 s and ignores the remaining cuts of that animation; when
it is not yet active, the next cut of the move is tried again.

**Transitions.** `transition_s` > 0 blends from the previous shot: n += frame time /
`transition_s`, s = 0.5 · (1 − cos πn) · sin(πn / 2) (`HalfBell` 0x779d40,
`fx_meta.halfbell`); position lerp, orientation slerp, fov and time multiplier lerp with s. A
cut-to-cut blend starts from the previous cut's stored position, orientation and multiplier,
not from the values blended so far. The blend is dropped — the cut becomes a hard cut, it is
not rejected — when the horizontal view directions of start and target differ by more than 90°
(`HasValidTransition` 0x634f62). During a blend a 0.3-wide sweep from the look-at point pulls
the camera in. The clock is the script `timepassed` global 0xe14304. During the script update it
holds the step chosen for the last natively updated node (0x495fec does not restore it). No node
of a second-list class has UseRealTime set in the Part 2 PC data (906 fragments + scene, 137
true), so it is the game step. The camera entity's own flag only decides whether its script runs
while the game step is 0.

**Hard cuts** (`fx.camera.cut_placement.hard_cut_push_in`). The 0.3 sweep pull-in is written by
StateTransition's hard block (T <= 0). Cut-to-cut with a live previous target: shown for one
frame, then the hold update restores the un-pushed position. First cut of a sequence (previous
target null, so DoContinue(3) 0x6269bc is false): the hold state is left every frame and the hard
block runs every frame, so the pull-in stays applied; with T > 0 nothing writes the camera data
after the blend and the output freezes at the last blended frame. Read from code, not confirmed
in game.

**Return.** `camera_return` blends back to the character camera over its `transition_s`; when
the actor leaves the animation state without one the camera returns over 0.9 s
(`fx.camera.cut_placement.return`). With `set_in_vector` the character camera is aimed first
(`return_in_vector`): basis actor → partner (the lender, and negated, for a borrowed camera),
flattened, y set to −0.3, turned about Y by −0.8 rad.

**Shake.** A cut's `shake` activates the shared sinus shake, but the cut camera applies no
modifiers; only the character camera reads it, so it shows only in a return blend that starts
while it is running (`fx.camera.modifiers.cut_shake`: `rule`, `applied_by_cut_camera: false`,
`note`, `source`). The rule: rotation (rad) = sum over active shakes of dir × size × sin(time_factor
× t) × (T − t)/T, t in real seconds (0xe14300); output quaternion (qz⊗qx)⊗qy, each built with
angle −r/2 (0x6466fd); dir = normalize((rand − 0.5) × 2 per axis).

**Co-op.** The player's viewport is kept (the split screen stays), fov = `ncoopfov` (75) and
time multipliers other than 1 are ignored. Locking all players, the full screen and HUD off
happen only for cuts on a state with no `master_of` in game mode 3: the 16 cuts of the four
`Countered_by_BS2_cattleprod_A|B` slave states (`coop_full_screen: true` on the pair).

### Slow motion and blends

`real_s` of a `slow_motion` interval or a pair shot is (to − from) / multiplier: the shot as a
hard cut. A valid blend into the shot runs in game time while the multiplier itself is blended,
so it takes `fx_meta.blend_real_s(blend_s, blend_from_multiplier, time_multiplier)` real seconds
= T · ∫₀¹ dn / lerp(m0, m1, s(n)) instead of T / m1. Whether a blend is valid needs the two
view directions, i.e. the joint positions, so the table does not decide it (`real_s_basis:
"no_blend"`). Example, `Rorschach` × `Enemy04` `Finish_move_WPN_1H`: cut 1 (×0.07, 0.1 s blend)
turns the view by 154°, so it is a hard cut and its shot lasts 0.049 game s = 0.70 s real, as
tabled; cut 2 blends 0.07 → 1 over 0.1 game s (19° turn, valid), which takes
`blend_real_s(0.1, 0.07, 1.0)` = 0.496 s real, 0.396 s more than its `real_s` of 0.72 s. Stepped
per frame the multiplier lags one frame and the figure depends on the frame rate (0.53 s at
60 fps).

Part 2 PC: 175 side shots, 55 kept positions, 29 angled; time multipliers 0.07 … 1.6 (69 cuts
≠ 1). `fx.camera.modifiers` lists the shake / recoil / kill constants, `fx.camera.rig` the camera
nodes of the four player-control fragments as stored (the character camera's parameters per
mode and its state table).

### On a pair

`pairs[*].camera_cuts` are the master's cuts on the pair's shared clock: `time_s` = seconds since
both states were entered (the master's play time, `pair.timeline`), `playpos` = the shared play
position, `clip_time_s` = the position on the master's clip. `camera_return` likewise.
Four pairs — `Enemy04` `Counter_A|B` × the players' `Countered_by_BS2_cattleprod_A|B` — have
their cuts on the PARTNER's state (the master's has none): their 16 cuts and their return carry
`actor: "partner"`, the cuts also `coop_full_screen: true`, `clip_time_s` is the position on the
partner's clip, and in `cut_camera` the actor is the partner and the target the master. A cut
without `actor` is the master's. Part 2 PC: 122 pairs with cuts (65 primary), 789 pair cuts.
`fx.shots` gives each cut's interval (`from_s`, `to_s`, `ends_with` cut / return / state_end,
`time_multiplier`, `real_s`, `real_s_basis`, `blend_s`, `blend_from_multiplier`), `fx.end_s`
the end of the lock. `fx.impact_effects`
(`actor` master / partner, `damage_pose`; the victim is the other actor, its definition
`fx.class_effect_defs[its class]`; `weapon_cases[actor]` = the dispatch cases the pair's weapon
criteria allow), `fx.rumble`, `fx.weapon_events` are on the same clock; partner events follow
the slave-locked rule of `anim_meta._pair_event`.

To reproduce a shot list: place the pair (`pair.placement`), run both clips at the shared play
position, and for each cut compute the camera from the two roots at `time_s` and hold that
position until the next cut, re-aiming at the look-at point every frame
(a reference render of `Rorschach` x `Enemy04` `Finish_move_WPN_1H` was made this way from the
character GLBs; `fx_meta.cut_camera` is the placement).

### In a character GLB

`anim_meta.clip_extras` (the `extras.watchmen` of every animation) copies three pair keys into
the clip's `pairs[*]` entries when the pair has them: `camera_cuts`, `camera_return` (this
document) and `trigger` (COMBAT_META.md). They sit beside `placement` and `timeline`, which is
what their times are measured on; the master's and the partner's clip both carry them. The
clip's `events[*]` carry `payload` / `payload_stale` (the event records are shared with the
table). The pair's `fx` lists and the per-state `fx` block are NOT in the GLB: a clip is shared
by several states, so they stay in `anim_meta.json`, keyed by state.

## Gameplay cameras

Read from code; not checked in the running game. `fx.camera.gameplay` holds the
rules of the three gameplay camera updates as data (`combat`, `exploration`,
`pvp`), each with its constants and, for combat, the per-frame steps as
`formulas`. The constants with their addresses are in ENGINE_CONSTANTS.md
("Gameplay cameras"). Helpers: `fx_meta.power_smooth`, `symmetric_halfbell`,
`pvp_camera`, `exploration_camera` (the last two take `frame=` like
`cut_camera`).

**Shared.** `BaseState` 0x64c1b4 runs the exploration update when
`m_irequestedcameramode` is 0 and the combat update when it is 1;
`command_combat_begin` 0x64376d sets 1 only when the input is not a mouse.
`InitializeCameraProperties` 0x655e27 builds two property sets (exploration,
combat) that differ only in the initial blend-in time.
`PowerSmooth(v, power, initPower)` 0x77ab7b: `v = clamp(v, 0, 1); m =
v^initPower; m > 0.5 ? 1 − 0.5·(2 − 2m)^power : 0.5·(2m)^power`. The cast
helpers skip hits on a `RagdollBone` and return the first other hit of the
sorted list; "no hit" is t = −1. Capsule casts are sphere sweeps of diameter
0.3. Both updates run once and then skip while the frame time is 0 (pause).

**Combat** (`StateActiveCombat` 0x64c330, update 0x64cee1): a chase camera with
yaw prediction and a 0.2 s output low-pass. It runs on the physics clock
(`physicsTimePassed + physicsRemainingTime − remainingLastFrame`); the
avoid-character lift and the output low-pass use the global `timepassed`.

- State entry: with a reset, `ninitialblendpos = 1` and `nfovtimer = 0` (the FOV
  factor then stays at `camera.fov / defaultFov` until a timed look-at ends —
  inferred consequence); without, 0 and 1.
- Stick (step 2): the left quarantine clears when the move intensity is above
  0.01 or x ≤ 0.1, the right one on x ≥ −0.1; a collision on one side
  quarantines the stick toward it and pulls the camera to the other side for
  0.1 s.
- Look-at and distance: `x = lerp(x, target, min(k·dt·extra, 1))`; extra =
  nveryclosefactor² for the look-at, nveryclosefactor for get-away; catch-up is
  `offset·dt·k`, not clamped. The look-at point is the visual's world position
  1.0 m lower plus the wanted look-at height.
- Yaw: path prediction (the ray toward where the character will be in 0.8 s),
  the target bias and the decay move a turn rate; with a target in front (step
  7b) the factor 2 applies when the rate already has the sign of the push,
  elsewhere when the rate opposes it. The yaw applied per frame is `d = (rate +
  stick) · dt · rotateSpeed + forced`, `x' = x cos d + z sin d`, `z' = −x sin d
  + z cos d`.
- The user tilt uses the raw stick (`nactualtiltpos` is written and never
  read).
- Collision: a hit nearer than the current minimum distance on a wall (normal.y
  < 0.7) shortens the minimum distance (`nforcediminishtime` is set to 0.1 and
  then `min(t − dt, 0)`, so it is active for one frame) and, below the
  collision minimum, pushes the character away. `ProjectVector(v, n)` 0x780fb1:
  zero if n = 0 or v̂·n < −0.999; `n × (v × n)` if v̂·n < 0; else v unchanged.
  `_ncollisionclipinfactor` has no effect: the value is overwritten with 1.0.
- Output: `out += (new − out) · avgDt / 0.2`, position and orientation alike,
  not clamped (above 0.2 s average frame time it overshoots); `avgDt = lerp(
  avgDt, timepassed, m_ntimepassedhistory)` — `m_ntimepassedhistory` 0.05 is
  the weight of the frame-time average, not a smoothing time. A final sweep
  moves only the output position.

**Exploration** (`StateActiveExploration` 0x651632, update 0x651b3d): an orbit
described by the state manager's current state (look-at offsets, FOV,
distance, pitch, yaw, pitch limits) plus the actual distance. It runs on the
global `timepassed` and has no output low-pass.

- Pose: `lookdir = normalize(sin yaw, −tan pitch, cos yaw)` (positive pitch
  puts the camera above the look-at); `offX = actual distance · clamp(
  lookAtOffsetX / distance, −1, 1)`; `lookat = root + up · yOffset − rightFlat ·
  offX`; `position = lookat − lookdir · actual distance`
  (`fx_meta.exploration_camera`, without collision and without the
  avoid-character height).
- State by stick (`PickStateStickBased` 0x64bb35, `rig.states[*].use`):

  | Move stick | State |
  |---|---|
  | ≥ 0.6 | RUN (1) |
  | > 0.1 and < 0.6 | WALK (9) |
  | exactly 0.1 | no change |
  | < 0.1 | IDLE (3) |
  | < 0.1 while in OVER_SHOULDER (6) | stays, unless pitch > `m_novershoulderoutpitch`, then IDLE |

  Buttons (`ReceiveButtonInputs` 0x654c5f): 0x22 → FORCE_BEHIND (16), 0x23 →
  LOOK_AT_PARTNER (17), 0x12 → HELPER (26, look at the next waypoint).
- Transition: `v −= signed(v, to) · halfbell(p)`, applied to the current value
  each frame; pitch, yaw, FOV and the pitch limits stop at p = 1, offsets and
  distance keep updating. The whole control step is skipped while a transition
  that disallows user input is running.
- Manual control: `SymmetricHalfBell(n) = 0.5·(1 − cos(π n))` 0x597620 ramps the
  speed (accelerating: `pref · shb`; decelerating: `start · (1 − shb)`); after
  the ramp the speed stays until the stick re-enters the dead zone.
  `ClampHeadingSpeedWithinCone` 0x645658: with a transition that has
  `m_tyawinsideobjectconehold`, `a = wrap(m_nyawto − yaw)`; if a and the speed
  have opposite signs, `speed *= clamp(1 − |a| / |m_nyawinsideobjectconehold|,
  0, 1)`.
- Fall-in (`SimulateFallIn` 0x64444f, only with `m_tenablefallincamera`): when
  the character's 3-D speed is above 1.0 m/s and dot(flat camera forward, flat
  velocity) > `m_nfallinstart`, per 0.01 s step `c = c · conv + m · (1 − conv)`
  and `yaw = heading(c)`.
- Distance catch-up: `f = t² / m_ndistanceoutcatchuppower`; lerp to the state
  distance, snap when f > 1; not allowed within 0.2 m and 0.5 rad of the last
  collision pose.
- Collision (read from code; `fx.camera.gameplay.exploration.collision`). Order
  in the update 0x651b3d: `LineChecks`, `CapsuleCheck`, `OffsetXCheck`. Each
  result other than −1 gives actual = min(actual, result) and the test position
  is recomputed (`OffsetXCheck` returns a value already capped at actual); then
  an actual distance at or below 0.1 becomes 0.1 (0x9e9628, 0x9e664c); any hit
  resets the distance catch-up.
  - `TestCollision` 0x644cc6: sphere sweep (width = height = diameter, sheet
    mask 4), sorted; the first hit whose node class is not `RagdollBone` gives
    from + (to − from) × t and is stored in `_vlasthitnormal`; no hit is the
    zero vector.
  - `LineChecks` 0x65436e: ray look-at → camera. If it hits nearer than the
    actual distance, cast back camera → hit point; if that also hits and a ray
    head bone → camera is clear, return −1 (a thin obstacle is ignored while the
    head sees the camera). Otherwise `LineCheckDistanceCalc`.
  - `LineCheckDistanceCalc` 0x654196: d = |hit − camera|; α from look direction
    · hit normal; α = 0 → −1. clear = (`m_ncollisionspherediameter` × 0.5) /
    sin α + d; result = (look-at-to-camera length − clear) × cos β, β from
    offsetX / actual. `LineCheckDistanceCalc` returns −1 also when the actual
    distance is 0. The angle functions are asin (0x9936f0, argument clamped to
    [−1, 1] by 0x423b91) and atan (0x993840).
  - `CapsuleCheck` 0x653883: sweep from camera + 0.5 m toward the look-at back
    to the camera, diameter `m_ncollisionspherediameter`; hit → actual − |camera
    − hit|, else −1.
  - `OffsetXCheck` 0x653b26: ray camera → camera + offsetX × side. If blocked,
    cast from the look-at (character x/z at look-at height) to that point;
    result = min(1.1 × actual × |hit − look-at| / |look-at − point|, actual);
    1.1 at 0xa3f068.

**PvP** (`CameraPlayerVsPlayer.UpdateCamera` 0x64748c, read from disassembly in
full). With R and N the two heroes, the pivot the level's
`PlayerVsPlayerFocusPoint` node (LEVEL_META `cameras.pvp_focus`) and cam the
camera's current position:

```
center  = R + 0.5 (N − R)
closest = N if |cam − N|² < |cam − R|² else R
n       = normalize(pivot − center)
lookat  = center + up · _nlookatheight
ponline = center + n · dot(closest − center, n)
hfov    = radians(_nfov) · width / height
D       = clamp((|closest − ponline| + 2) / tan(hfov / 2) + |ponline − center|, 2, 999)
pos     = lookat − n D + up D tan(_nlookatpitch)
```

The distance uses the character closest to the camera and its distance to the
centre → pivot line + 2 m, not the separation. There is no smoothing:
`_nsmoothing` has no reader (`rig.property_use`). `fx_meta.pvp_camera(r, n,
pivot, cam, fov_deg, lookat_h, pitch, aspect)` does the arithmetic.

Not established: on-screen left / right of a positive yaw step; the PvP view at
its shipped pitch 1.2 (inferred steep, about 2.6·D above the look-at); co-op
behaviour; `CameraDataCollector`.

## Level cameras

Camera node (read from code: 0x4a796c, 0x4a1eeb, 0x49e49c, 0x49e500): `fovVertical` in degrees,
default 70, clamped 1..179; `nearClip` default and floor 0.05; `farClip` default 1000, at least
near + 1. The engine registers only `fovVertical`; the fragments hold both `fov` and
`fovVertical`, equal on all 265 PC Part 2 camera instances, so the exported `fov` is right.
PC Part 2: 265 instances, near 0.1 on all, far 1000 on 263 and 350 on 2 (measured). Scripted
cuts: LEVEL_META `cameras.tours`.

Inferred: `CameraCinematic` / `CameraCinematicToCharacter` are driven only by
`CameraCtrl.command_start_lookat` / `command_stop_lookat` (0x636005, 0x63643f); no lifted
script sends them and `PlayerLookatTrigger` has no instance; native senders were not searched.

`fx.camera.rig.<player>.transition_editor_visibility` pairs four `CameraCharacterTransition`
properties with the truth property the editor's property grid shows them with (`m_npitchto`
with `m_tpitch`, and three yaw pairs; read from code: `FilterExposedProperties` 0x62f298).
Whether the run time reads a value only with its truth property is not established.

## Decals

No `DecalManager` or `GFXDecalEffectType` node is in any PC Part 2 or Part 1 level
(measured), so no export depends on decals. Read from code: the `DecalManager` constructor
0x4be917 sets 5 at +0x60 and 2 at +0x64. Read from code: rotation = rand × π; offset along the
normal 0.01 + rand × 0.001; corner rays at ± scale × 0.8, each ± 0.05 m along the normal
(0x75ada5, 0x75b7e5); a ring of `bufferSize` + `perFrameFillSize` quads, the slot advancing by 4
vertices modulo the pool (0x4c5777). Both `SetDecal` entries refuse when the byte at +0x65 is
not below `perFrameFillSize` (0x4c56f7, 0x4c566a); that byte is incremented per flushed decal
(0x4c5fa6) and zeroed only in the constructor (0x4be9a1; measured: no other write in
0x401000–0x590000).

## Lens flare

Reference, read from code (the manager 0x4bd679 and the per-flare draw
0x4b4816); the occlusion-query timing is not re-checked.

Manager (called from pass 0x56dc9e for managers in the frustum), with P the
flare position:

- dir = normalize(P − (camPos + 0.1 × camForward)).
- If the parent has byte +0x131 set, the flare is placed at distance +0x158
  along the manager's axis and its fade distance becomes 10000.0.
- Occlusion is a hardware query on a quad of `occlusionSize`, read two frames
  late from a ring of three (not re-checked).
- Visibility `S[5]` moves ± 1 / `numberOfFadeInFrames` per frame, clamped to
  0..1, and is zeroed when P is outside the frustum.
- Intensity `S[4]` = `S[5]` × (1 − dist / `fadeDistance`).
- Size factor = 1 − `sizeReduction` × dist / `fadeDistance`.
- No line check is made, despite the property name.

Per flare (the setters store the cosines of the degree angles):

- Flare angle A (when `fadeFlareAngle` < 170.0): g = dot(dir, manager axis); x
  = 1 − max(g, 0), or |g| with `inverseFlareAngle`; A = max(0, 1 − x / (1 − cos
  FF)).
- Camera angle B, with c = dot(dir, camForward): inside angle 1 (c > cos1, and
  cos1 ≤ 0.99): B = blind + (1 − c) × (1 − blind) / (1 − cos1); otherwise B =
  clamp01((max(c, 0) − cos2) / (cos1 − cos2)).
- Alpha = `opacityModifier` × `S[4]` × A × B × `opacity` × (1 − clamp01(camDist
  / `maxDistance`)).
- Screen position = centre − (source − centre) × `offset`.
- Height px = size factor × `size` × k, with k = clamp01(1 /
  (`distanceSizeScaleFactor` × camDist)) when that factor is > 0; width =
  height × W / (H × pixel aspect).
- Colour is premultiplied by alpha; blend mode 0 normal, 1 additive.

## Character attachments

`fx.characters[stem]`: `character_type`, `body_class`, `effect_def`, `visual_fragment`,
`attachments` — the `EmitterNode` / `LightFlash` nodes of the character's CharVisual fragment:
`kind`, `particle`, `auto_start` or `light` {colour, brightness, range}, `bone_index` (the
`attachedBone` of the `BoneAttacher` above it = joint index of the body skeleton), the stored
local offsets and the parent chain. Rorschach 22 (rain splashes, breath, the hand motion trail,
the impact light), Nite Owl 12 (armour electricity), Twilight Lady 1 (the cattle-prod sparks,
on the weapon model); the other enemies none.

A character GLB carries the same list in `asset.extras.watchmen.fx_attachments`, each entry
with the joint name (`bone`).

In a true-frame GLB an engine local (p, q) is translation (−p.x, p.y, p.z), rotation (−q.x, q.y,
q.z, q.w). A BoneAttacher's stored transform is a rest snapshot of its bone (rotation equal to
the GLB joint within 0.2° on 14 / 14; position equal on Rorschach, 0.0596 m lower in y on Nite
Owl, unrelated on the Twilight Lady weapon chain) and is replaced by the bone at run time
(inferred). Measured on PC Part 2, 3 characters; not tested on a `--frame mirrored` GLB (there
the rule would be t = p, r = (−x, −y, −z, w): inferred).

## Effects the event cases fire, and rumble senders

`fx.event_effects.by_event`: the effect ids (`fx.effect_ids`) the animation event cases fire
themselves: FLASH_GRENADE (29) id 8; ELECTRIFY_ARMOR (30) none in the case
(`ElectricArmor.command_electric_armor_charge` fires id 0); DISCHARGE_ARMOR (31) none;
STARTING_UBER_RAGE (60) id 12 fired and id 13 started (command_start_effect_by_id); MAKE_LIGHTNING_FLASH (69)
ids 1 and 10, both at root position + visual-space (0, 0.4, 0.4), needing an attack target and
the ElectricArmor entity.

`fx.rumble.senders`: the senders of `command_do_rumble_effect(duration, power, fade)` besides the
RUMBLE event and the impact rumble: forced counter attack 1.0 s / 0.4 / fade, dodge and block
0.5 s / 0.15 (to the partner's controller), the bull-rush charge 0.5 s / 0.15 (to the charged
target), DISCHARGE_ARMOR 0.5 s / 0.4 / fade, the fire volume 0.2 s / 0.4 per player in the fire,
`UnderbossPhase1` 0x890013 0.75 s at min(1, (10 − clamp(d, 3, 10)) × 0.15) with fade (to the player), and the
trigger action RUMBLE_CHARACTERS_CONTROLLER (25) with its own numbers.

`fx.fake_twilight_lady_weapon` (the same text is in `fx.damage_rule.twilight_lady_fake_weapon`,
beside the rule it qualifies): `g_efaketwilightladyweapon` is null in shipped data:
`command_set_weapon` 0x6943b8 sets it only when the type-0x23 definition has
`m_emodelcollbash1h`, which is null on PC, PS3 and X360 (read from code; measured on all six
sets); no weapon node has effect type TASER. Inferred: the TASER branch is therefore never taken
for her (0x6673d0 was not re-read for a null weapon).

`fx.particles[asset]` (emit duration, loop, longest particle life) is read with
`particle_asset.parse` (PARTICLE_FORMAT.md), so it also reads big-endian files and the Part 1
PC / X360 record layout; the full parameters of an effect are in the asset's own
`.particle.json`.

## Not established

`fx.not_established` in the table. In short: how the root node follows the capsule
each frame (the cut's vertical reference); whether the first cut of a session blends (the test
uses the cut camera's previous orientation); which weapon model a character holds in a
given pair; the
damage pose a given IMPACT ends with (the conversions and their order — combo, direction, size,
height — are read and exported as `combat.rules.damage_pose`, see COMBAT_META.md; their inputs
exist only at run time, so the effect tables give the authored pose); the 0.0596 m by which Nite
Owl's stored attacher positions lie below the GLB joints, and why the Twilight Lady weapon-chain
attacher's position is not a rest snapshot; everything about the gameplay cameras on screen.
