# Animation events at run time

Target: `KapowMultiDEDRM.exe`. Read 2026-10-02. Machine-readable table:
`findings/events_table.json` (93 ids). Scratch: `work/events/` (annotated
disassembly `handler.asm`, case map `casemap.json`, enum dump `enum_raw.txt`).

Evidence tags: **[R]** read from code, **[I]** inferred, **[N]** not established.

## 0. What matters for the pair-placement tool

1. **`ABSOLUTE_GOTO_TARGET_POS` (28) only sets one flag** on the character's own
   collision capsule (`capsule.data+0xb8 = 1`, 0x6a9dca–0x6a9ddf) [R]. It computes
   no position itself. The flag changes what the capsule's per-frame absolute
   update does (section 3).
2. **In the shipped data it is a victim-side event, timed in seconds.** All 161
   states carrying it are absolute, non-master states with
   `m_ispecialhandling = 3` (`ABSOLUTE_START_AT_CURRENT_POS`); 159 of the 161
   events have trigger type 3 (`TOTAL_PLAY_TIME`), so their `m_nplaypos` 0.2 /
   0.21 is **0.2 s of play time, not 20 % of the clip** (measured on the Part 2
   PC fragments; sender logic in section 1) [R].
   `anim_meta.json` currently exports only `on_enter` (type == 1) and presents
   `playpos` as 0..1 for every event; that is wrong for type-3 events and it
   hides type 2 (`LEAVE_STATE`).
3. **Victim timeline that follows from the code** [R for each step, the
   combination I]: the victim enters absolute mode at its *current* pose
   (special handling 3 → flag 0); `CharacterRoot.StateActive` writes the
   partner-defined start (`m_vWorldStartPos`/`m_qWorldStartOrient`, the rule in
   `ANIMATION_META.md`) every frame, but the capsule ignores it while the flag
   is 0; at 0.2 s the event sets the flag, the capsule picks the new start up
   and eases from the pose it entered the state in to the placed track over the
   state's blend time. The tool's placement rule is therefore the *settled*
   pose, reached one blend time after 0.2 s.
4. **`LOOK_AT_TARGET` (45) is a camera event.** It does not turn the character
   (section 4).
5. **`LEAVE_ABSOLUTE_MODE` (19)** ends track-driven placement for the character
   that carries it and unlinks the pair (section 5). 58 of its 219 uses are
   `LEAVE_STATE`-type.
6. **`KILL_ANIMATION_PARTNER` (20)** is a 100000-damage hit on the victim plus
   clearing the partner link; no transform is written (section 5).
7. No event in this handler writes a partner's position or orientation.
   Events that move or re-seat the *own* character: 28, 15 (`CHARGE`),
   17 (`GRAPPLING_HOOK`), 80 (`DO_AUTO_ALIGN`). Heading events (41, 48, 49, 54,
   55, 62) change logical heading fields only.

## 1. Sender

`AnimationCtrl/AnimationCtrlWM.CheckPlayPosEvents` 0x5b51f3 [R]. Arguments:
`[0]` → event slot `{event node, fired flag, force flag}`, `[1]` → page
(page data `+0x10` current play position, `+0x38` previous, `+0x34` total play
time).

- Trigger type = `m_ieventtype` (event data +0x00). Enum
  `ANIMATION_EVENT_TYPES`, registered at 0x5e54ed–0x5e5516:
  `PLAY_POS = 0`, `ENTER_STATE = 1`, `LEAVE_STATE = 2`, `TOTAL_PLAY_TIME = 3` [R].
- Type 3: fires once when `m_nplaypos < page total play time (+0x34)`; here
  `m_nplaypos` is a time (captions read "DIE at time 8.04") [R compare, I unit].
- Type 0, non-looping state: fires once when `m_nplaypos <= current playpos`.
- Type 0, looping state (`Is looping`, state data +0x34): fires when
  `min(cur, prev) < m_nplaypos <= max(cur, prev)`.
- Type 1: sent from `SetupNewPage` 0x5b7788 (second argument 0). Type 2: sent
  from `UpdatePagePlayPos` 0x5b56a9 and `SetupNewPage` (second argument 1.0) [R].
- After each send the sender stores a fresh random number in event data +0x10
  (property 0x387ca064).

Delivery: `SendAnimationEvent` 0x5ac4ef [R]. If the event's
`m_tforceupdateblends` (+0x0c) is set it sets controller data +0xac = 1; it
appends `{event id, ctrl+0x80}` to a controller list (purpose [I]: lets
`AnimationCriteria` with an `Event` test it); then sends hash 0xf7c3b75f
`command_animation_event_received` with `{event node, arg1}` to every listener.

Registered receivers [R]:

| Class | Handler | Handles |
|---|---|---|
| CharacterRootLogic | 0x6a525e | everything in section 2 |
| CharacterCameraStateManager | 0x64b304 | id 18 `CAMERA` only |
| TriggerCharacter | 0x87d421, 0x87e574 | ids 78, 79 (store play position), 8 |
| AnimationCtrl / AnimationCtrlWM | 0x48d561 | empty stub |

CollisionCapsuleNode and the weapon classes register no such handler.

## 2. Dispatch of 0x6a525e

The function runs to 0x6ae57e (the dump's size of 34714 stops short; real length
37665 bytes) [R].

- `args[0]` = event node. Event id: if the node is class id 0x126
  (`AnimationCriteria`, global 0xe16d7c) → data +0x30; else if class id 0x123
  (`AnimationEvent`, 0xe16f58) → data +0x08 (0x6a5297–0x6a52e6). `args[1]` is
  never read.
- Id is kept at `[ebp+0x68]` and in the handler frame +0xb8; dispatch is four
  compare chains, not a jump table: 0x6a52f5, 0x6a625e, 0x6a7226, 0x6a749d.
  Unmatched ids fall out at 0x6a750c → return.
- Trigger type and `m_nvalue` do not arrive as arguments; cases read them from
  the node.

Event node layout (properties are laid out in registration order, 0x5e44e8…;
rule checked against the known capsule offsets and the +0x08 id) [R order, I sizes]:

| Offset | Hash | Name / use |
|---|---|---|
| +0x00 | 0x19ce5b00 | `m_ieventtype` |
| +0x04 | 0x02865508 | `m_nplaypos` |
| +0x08 | 0x3fa944a3 | `m_ianimationevent` |
| +0x0c | 0x42dd8a72 | `m_tforceupdateblends` |
| +0x10 | 0x387ca064 | random number written by the sender |
| +0x14, +0x18, +0x1c | 0x9db59b14 / …94 / …54 | entity refs |
| +0x20 | 0xed4c0d80 | enum dropdown (name not in the exe); "enum" below |
| +0x24 | 0x66cc9ce5 | `m_nvalue` |
| +0x28 … +0x48 | 0x7050e679 … 0x70506639 | nine more floats ("value2" = +0x28) |
| +0x4c, +0x50, +0x54 | 0xbd9f4248 / …88 / …08 | three bools ("bool1" = 0xbd9f4248) |
| +0x58, +0x64 | 0x69f0c2e5, 0x69f0c225 | two vectors |

Objects used below: `logic` = CharacterRootLogic data (`ebx`); `root` =
`logic+0x3c` (CharacterRoot); `root+0x04` animation controller (also
`logic+0x44`); **partner = controller data +0x04**; `root+0x24` visual;
`root+0x28` capsule; `root+0x70` current attack target; `root+0x7c` locked
target; `root+0x88` PlayerCtrl (null for AI); `logic+0x1c` current
AnimationStateWM; `logic+0x18` stored victim.

### Case map (every id, all [R] unless marked)

| Id | Name | Case at | What the code does |
|---|---|---|---|
| 4 | IMPACT | 0x6ac9dd | Non-attack state (`state+0xa0 == 0`): partner behaviour `is_attack_successful`; if yes builds a damage record and sends partner `CharacterRoot.command_give_damage` (0x6ad284); rage / electrify power. Attack state: `SetCloseCombatDamageToTarget(root+0x70, state, -1)` (0x6ad566), `TestImpactOnDynamicObjects`, `DebugHit` |
| 5 | BRANCH | 0x6ae34f | Next queued attack → `FireAttackBasedOnAttackID`, `InitializeNextAttack`; none → `root+0x70 = 0`, `root+0x104 = 0`, partner link = 0, `command_send_attack_dist_to_animation_ctrl`, `command_update_animdata_partner_model` |
| 6, 40, 76, 77 | LEFT/RIGHT_FOOT_DOWN, FOOT_DOWN_JUMP/STOP | 0x6a533a | `CharacterVisual.command_get_boneID` (0x11 for id 40, else 0xb), ground lookup, footstep sound/effect |
| 7 | ANIMATION_DRIVEN | 0x6ac992 | `command_reset_physics_state` to self |
| 9 | SOUND | 0x6aba76 | bool1 → stop entity sound, `command_play_event_speak`, `CharacterVisual.command_start_speak`; else `command_play_event_sound` / `_sound_entity` |
| 11 / 12 | DISABLE / ENABLE_ROTATION_INPUT | 0x6a9f19 / 0x6a9f03 | `root+0xa8 = 1 / 0` |
| 13 | CAN_GO_TO_MOVEMENT | 0x6ac08c | player: `command_doing_block_breaker(0)`; `SetAnimationEnum(ctrl, 9, 1)` |
| 15 | CHARGE | 0x6ac010 | `add_rage(-k)`; player: `root+0x8c = 0`; `CollisionCapsuleNode.command_state_charge` |
| 16 | PRE_IMPACT | 0x6ad5ec | no target → `logic+0x50 = 0`. AI target that will not be hit → `command_block_timed(1.0)`. AI attacker further than 1.8 m (2.2 m if `is_big`) → drops target and partner link (0x6ad84e–0x6ad88a). Otherwise computes the damage pose and sends target `command_hit_soon` (0x6addfc) |
| 17 | GRAPPLING_HOOK | 0x6a9ebe | `CollisionCapsuleNode.command_goto_grappling_hook` |
| 19 | LEAVE_ABSOLUTE_MODE | 0x6ac8de | section 5 |
| 20 | KILL_ANIMATION_PARTNER | 0x6ac5f6 | section 5 |
| 21 / 22 | DISALLOW / ALLOW_AUTOAIM | 0x6a9eec / 0x6a9ed6 | `root+0xb0 = 1 / 0` |
| 23 | CLEAR_DEADZONE | 0x6ae002 | `logic+0x54` dead-zone time, `CharacterComboDatabase.command_trim_combo_list`, `command_get_longest_valid_combo`, combo log |
| 24 | ALLOW_ATTACKS | 0x6ac9a3 | `logic+0x60 = 0`, `logic+0x54 = -2.0`, `logic+0x84 = 1` |
| 25 | DISABLE_CHARACTER_COLLISION | 0x6ac10a | capsule property `enabled` (0x2708acba) = 0 |
| 26 | DROP_TARGET_LOCK | 0x6a9df6 | `root+0x7c = 0`, `root+0x8c = 0`, `root+0x90 = (-10000)³`; tutorial event |
| 27 | FORCE_ALLOW_COUNTER_ATTACK | 0x6a9dea | `logic+0x74 = 1` |
| 28 | ABSOLUTE_GOTO_TARGET_POS | 0x6a9dca | `capsule.data+0xb8 = 1`; section 3 |
| 29, 30 | FLASH_GRENADE, ELECTRIFY_ARMOR | 0x6a62d8 | radius-3 physics query, `hit_soon` + `give_damage` per character; id 30 also charges the armor |
| 31 | DISCHARGE_ARMOR | 0x6a8865 | partner: rumble, `hit_soon`, `force_anim_always`, `give_damage`, lightning |
| 32 | COUNTER_ATTACK_WEAPON_STEAL | 0x6a84cf | partner `command_force_drop_weapon`; own weapon dropped; `WeaponBase.command_do_actual_pickup{root, 0.1}`; `root+0xd4 = weapon` |
| 33 | BULLMOVE_IMPACT | 0x6abcb1 | `give_damage` to `logic+0x18`, camera recoil |
| 34 | STEP_AROUND | 0x6abbe9 | `command_set_stun_time` to `root+0x7c` |
| 35 | EXTEND_COMBO_TIME | 0x6ac9bf | `logic+0x0c = now + m_nvalue` |
| 36 | PICK_UP_WEAPON | 0x6a817a | `WeaponBase.command_detach` on the old weapon; `root+0xd4 = root+0x15c`; `command_do_actual_pickup{root, 0.1}` (or `force_drop_weapon` for "UnderbossBluntWeapon") |
| 37 | SPEAK | 0x6a9f30 | `SpeakCtrl.command_add_speak_event_based_on_enum` (enum = +0x20) |
| 38 | THROW_BRANCH_POINT | 0x6a91c0 | partner in special state 8: `FireAnimationAction(ctrl, 0x1e)`, `hit_soon` both ways; `ClearAttackData` |
| 39 | GOT_UP | 0x6a812a | behaviour `command_got_up` |
| 41 / 49 / 54 / 55 | REVERSE / NORMAL_HEADING, ROTATE_HEADING_90_LEFT / RIGHT | 0x6a8108 / 0x6a80dc / 0x6a80ef / 0x6a80e0 | `root+0x158` = π (0xa5d2a0) / 0 / +c / −c, c = MathLib data +0x40 (run-time value [N]); then `command_set_move_and_face_heading_to_actual_heading` |
| 42 | NO_LONGER_IMMUNE_TO_ATTACK | 0x6ac9b0 | `logic+0x84 = 1` |
| 45 | LOOK_AT_TARGET | 0x6a86ae | section 4 |
| 46 / 47 | GRAPGUN_ENABLE / DISABLE | 0x6a9eaf / 0x6a9ea6 | `command_enable` / `command_disable` to `logic+0x24` |
| 48 | SET_MOVE_AS_FACEHEADING | 0x6a80ce | `command_hack_set_moveheading_to_faceHeading` |
| 52 / 53 | FACE_HEADING_FORCE_IGNORE / REMOVE | 0x6a80b7 / 0x6a80a1 | `root+0xb4 = 1 / 0` |
| 56 | IMPACT_EFFECTS | 0x6aae6f | rumble by damage pose (enum), `play_damage_effect`, `command_do_recoil`, partner `command_when_attacked`, effect |
| 57 | SAFE_RAGDOLL_COLLISION | 0x6a8031 | `PhysicsSimulation.command_set_safe_ragdoll_collision_groups{own visual, partner visual, m_nvalue}` |
| 58 | DROP_WEAPON | 0x6a845c | `CharacterRoot.command_force_drop_weapon` |
| 59 | CAMERA_CUT | 0x6aa7e4 | `CameraCtrl.command_set_combat_cut_data`, HUD/lock, `command_force_step_back` to others |
| 60 | STARTING_UBER_RAGE | 0x6a7de3 | effects 0xc / 0xd, `root+0x13c` |
| 61 | CAMERA_CUT_TO_CHARACTER_CAM | 0x6aa036 | `command_return_to_character_camera{m_nvalue}` |
| 62 | SET_HEADINGS_FROM_ALIGNEMENT | 0x6a7dd5 | `command_set_move_and_face_heading_to_actual_heading` |
| 63 / 64 / 65 | UNDERBOSS_START / STOP_FLAMER, FLAMER_DONE | 0x6a7ce7 / 0x6a7bf9 / 0x6a7b0b | Underboss phase `command_flamer_start / _stop / _done` |
| 66, 67, 68, 71 | TRIGGER_START/END_INTERPOLATING, UNDERBOSS_JUMP_OFF_LAND_DONE, UNDERBOSS_WOBBLE_DONE | 0x6a739d | Underboss phase `command_jump_anim_part_done{id}` |
| 69 | MAKE_LIGHTNING_FLASH | 0x6ac1bf | two `command_fire_effect_by_id` |
| 70 | THROW_MODE_STORE_TARGET | 0x6a9349 | picks throw target → `root+0x8c`, `root+0x90` |
| 72 | KNEE | 0x6a7ad9 | `SetAnimationEnum(ctrl, 13, enum)` |
| 73 | RAGDOLL_MODIFIER | 0x6a7996 | `visual.data+0x28 = normalise(logic+0xb8) × m_nvalue` |
| 74 | REMOVE_INVERSE_DIRECTION | 0x6a798d | `logic+0x34 = 0` |
| 75 | DROP_WEAPON_WITH_ANIM | 0x6a8480 | `FireAnimationAction(ctrl, 0x1b)` if a weapon is held |
| 80 | DO_AUTO_ALIGN | 0x6aae3c | `CharacterRoot.command_force_auto_align{m_nvalue, value2}` (0x694ed7): `root+0x26c = now + value2`, `root+0x270 = m_nvalue` |
| 81 | UNDERBOSS_SUPPORT_EVENT | 0x6a78ea | `command_recieve_anim_support_event` |
| 82 | RUMBLE | 0x6a7879 | `command_do_rumble_effect{m_nvalue, value2, bool1}` |
| 83 | STARTING_HURT_ANIMATION | 0x6ac12f | `command_dont_move_while_animation_runs{clip length}` |
| 84 | DO_BLOCK_FLASH | 0x6a779e | `logic+0xd8 = 1`, `add_electrify_power(-k)`, `SetTextureSheetData` |
| 85 | DIE | 0x6ac4e1 | `give_damage{attacker = self, 100000}` to self |
| 86 | DELAY_OPPONENT | 0x6a7772 | `command_delay` to `root+0x70` |
| 87 / 88 | FORCE_ALLOW_BREAKOUT / _NO_MORE | 0x6a7763 / 0x6a7757 | `logic+0xe0 = 1 / 0` |
| 89 | ACTIVATE_DEPTH_OF_FIELD | 0x6a7619 | `FXGfxEffectCtrl.command_fade_in{entity ref +0x14, m_nvalue}` |
| 91 | NEVER_USE_THIS_ANIM_AGAIN | 0x6a760d | state property `enabled` = 0 |
| 92 | STOP_TWILIGHT_CAM_LOCK | 0x6a75ed | `StopTwilightLadyCamLock` |
| 93 | DO_CHOKE_EFFECT | 0x6a7512 | head controller: `FireAnimationAction(·, 2)`, `SetAnimationEnum(·, 4, 0x10)` |

No case in this handler: 0, 1, 2, 3, 8, 14, 18, 43, 44, 50, 51, 78, 79, 90.
Of these 8, 18, 78, 79 are handled by the other classes in section 1; the
rest have no receiver in the exe.

## 3. ABSOLUTE_GOTO_TARGET_POS — what the flag does

The handler: `root.data+0x28` → capsule, `capsule.data+0xb8 = 1`, return [R].
There is no target lookup, blend time or vector math in the event case.

`capsule.data+0xb8` is the fifth argument of
`CollisionCapsuleNode.command_goto_animation_mode` (0x67bd36 / 0x6a32ce) [R].
`CharacterRootLogic.command_goto_phys_absolute_mode` 0x68a79f passes
`flag = (current state's "Special handling" (state data +0x9c) == 0)` and
`blend time = its second argument` [R]. `ANIMATION_SPECIAL_CASE` value 3 is
`ABSOLUTE_START_AT_CURRENT_POS`.

At entry (0x67bd36) [R]:

- flag 0: `m_vWorldStartPos (+0x10)` = current visual position,
  `m_qWorldStartOrient (+0x28)` = current orientation; `m_vWorldEndPos (+0x1c)`
  and `m_qWorldEndOrient (+0x38)` derived from the GamePivot track.
- flag 1 and `capsule.data+0x48 != 0`: start is solved so the clip's `interact`
  track (clip data +0x4c) lands on `m_vAbsInteractPos (+0x4c)` /
  `m_qAbsInteractOrient (+0x58)`; start orient = `m_qAbsInteractOrient`.
- flag 1 and `+0x48 == 0`: the stored start is kept. (This answers the "flag-1
  branch" item left open in `ENGINE_CONSTANTS.md`.)

Per frame, `command_absolute_update` 0x67f7b0 [R]:

1. If the flag is set it first sends itself `command_update_world_data`
   0x6b201d. That compares the property values with the copies cached in the
   state frame: start changed → the "worldstartnode" pivot is re-seated and End
   recomputed (`End = Start + R·(GP(len) − GP(0))`, `End orient = GP orient ·
   Start orient`); only End changed → Start is back-solved from End. **Without
   the flag the pivots stay where they were at state entry, so later writes to
   `m_vWorldStartPos` have no effect.**
2. `pos = Start + R(Start orient)·(GP(t) + loop offset − GP(0))`,
   `orient = q_GP(t) · Start orient` (unchanged from the existing doc).
3. If the flag is set: `timer −= clamp(dt, 0, 0.1)`; while `timer > 0`,
   `w = timer / blend time`, `pos = lerp(pos, entry pos, w)`,
   `orient = slerp(orient, entry orient, w)`. Timer and entry pose are set once
   in `StateAbsoluteAnimation` 0x6a1e1d (frame +0x48 = blend time, +0x4c =
   1/blend time, +0x50.. entry position, +0x5c.. entry orientation). The timer
   only counts while the flag is set, so for an event-set flag the ease starts
   at the event, from the pose the character had when the state began.

Other writers of the flag: `UnderbossPhase1` code (0x88c226, 0x88df1c,
0x88e3bd, 0x88ec20, 0x88f31d), which writes End pos/orient as a goal and then
sets the flag — the "target" the event name refers to [R writes, I naming].
`StateAbsoluteAnimation` clears the flag on exit when the state has `Master of`
set (0x6a1e1d case 5).

Not established: the blend time value actually passed for victim states (the
caller of `SendGotoPhysAbsoluteMode` 0x5ac79b was not traced; `Ease in
duration` 0.21 s on these states is the likely source); whether
`capsule.data+0x48` is ever non-zero in combat.

## 4. LOOK_AT_TARGET

0x6a86ae–0x6a8860 [R]. Returns at once unless the character has a PlayerCtrl.

- `time = m_nvalue (+0x24)`, `value2 = +0x28`.
- Target: bool1 set → the character's own root; else `root+0x70`, else
  `root+0x7c`, else the animation partner; none → return.
- If enum (+0x20) == 1: `camera.command_force_rotate{π, time}`.
- `camera.command_lookat_target_timed{target, time, value2}` —
  `CharacterCamera` 0x650d42 stores the three values in its own state.

No capsule field, heading or orientation of any character is written. Shipped
values (140 events): time 0.7 s on 122, value2 0.61 on 111, bool1 set on 132.

## 5. Partner, weapons, ragdoll

**LEAVE_ABSOLUTE_MODE** (0x6ac8de) [R]:

1. `CharacterRootLogic.command_goto_phys_normal_mode` → capsule 0x67f56b: own
   animation controller `command_leave_slave_mode` (controller data +0x60 = 0),
   capsule state → `StateOnGround`. Position is not changed.
2. If a partner is linked: own root `command_leave_slave_mode{partner's
   controller}` (0x693a09) → `command_dual_end` on both capsules, own slave
   flag cleared.
3. Partner capsule `command_break_joint` (0x67b342 → `CleanUp_eDccJoint`).

**KILL_ANIMATION_PARTNER** (0x6ac5f6) [R]: character type 1 gets electrify
power, others rage; `logic+0xd4 = 0`; victim = `logic+0x18`, falling back to
`root+0x70`; victim's logic `command_set_ragdoll_modifier_direction{0,0,0}`;
`victim.root+0x1cc = bool1` (read in `CharacterRoot.StateDead` 0x6bb12a: 0 →
death speak line, 1 → silent); `give_damage{attacker, damage 100000, zero
position and direction, new attack id}`; `add_rage(0.2)`; own partner link = 0;
`command_update_animdata_partner_model`.

**Ragdoll hand-over**: no event case sends a ragdoll command. 20 and 85 only
deliver lethal damage; 73 scales the ragdoll modifier vector; 57 sets collision
groups between the two visuals. The path from `give_damage` to the ragdoll
state was not traced [N].

**Weapons**: 32, 36, 58, 75 as in the table. Detach direction for 36 is
`MathLib.ToDirection(root+0x5c)`; pick-up always passes 0.1 as the second
argument.

**Other events that touch the partner or target**: 4, 5, 16, 31, 33, 34, 38,
56, 86 (damage, hit notification, stun, delay, or clearing the link). 5 and 16
can clear the partner link mid-move.

## 6. Enum

Registered by calls to 0x5052c9 `(enum name, item name, value)` in the function
at 0x809e9e, items 0x80a51b–0x80a9f2; register-pushed values resolved
(`ebp` = 0 → NONE, `ebx` = 1 → PUNCH) [R]. 93 items, ids 0–93 with **10
unassigned**. Full list in `events_table.json` / `work/events/enum_raw.txt`.

Against `anim_meta.json` `event_names`:

- One disagreement: id 14 is `UNUSED` in the exe, `WALK_CYCLE_POINT` in the
  captions (4 uses).
- Id 6 also appears captioned `FOOTSTEP` (5 uses); exe name `LEFT_FOOT_DOWN`.
- 18 exe ids have no caption-learned name: 1 PUNCH, 3 STOP_R, 22 ALLOW_AUTOAIM,
  42 NO_LONGER_IMMUNE_TO_ATTACK, 43 RIGHT_FOOT_UP, 44 LEFT_FOOT_UP,
  50 RIGHT_ROTATED_HEADING, 51 LEFT_ROTATED_HEADING, 63–68 and 71, 81
  (Underboss / trigger), 89, 90 (depth of field). Id 42 is used 20 times in the
  shipped data.

## 7. m_ieventtype and m_nvalue

`m_ieventtype` is the trigger kind for every event (section 1); no handler case
branches on it except TriggerCharacter for 78/79 (requires type 0).

`m_nvalue` is read by: 35 (seconds), 45 (seconds), 57 (third argument of the
collision-group call), 61 (argument of return-to-camera), 73 (scale), 80 (value
stored at `root+0x270`; shipped 1.22–1.72, used by StateActive in place of
`root+0xe8` in its auto-align distance term [I for "metres"]), 82, 89, 56 (only
with bool1), 59 (copied to cut data). Events whose shipped `m_nvalue` is
non-zero but whose case never reads it: 24, 37, 48, 75.

## 8. Side observation for the extractor

On the device, event nodes decode with keys such as `key_3eb33333`,
`key_3f000000`, `key_00000000/1/2` — float bit patterns used as key names. The
property-bag reader is losing alignment on some AnimationEventWM properties
(most visibly on ids 9, 37, 56). The fields `m_ieventtype`, `m_nplaypos`,
`m_ianimationevent`, `m_nvalue` come out consistent, but the extra floats,
bools and vectors of those events should not be trusted until that is fixed.

## Not established

- Blend time passed to the capsule for victim states (section 3).
- Run-time value of the MathLib constant used by 54/55.
- Names of properties 0xed4c0d80, 0xbd9f42x8, 0x7050e6xx (not in the exe's
  strings; hashes of `m_nvalue02`… do not match).
- Path from lethal damage to ragdoll.
- Cases 23, 29/30, 31, 59, 70 and the footstep block were skimmed for commands
  and field writes, not read instruction by instruction.
