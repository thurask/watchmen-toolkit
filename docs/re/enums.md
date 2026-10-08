# Enum tables (id -> name) from KapowMultiDEDRM.exe

Tables: `findings/enums.json` (`enums` = {family: {id: name}}, `by_name` = {family: {name: id}}, `meta` = per-family provenance).
Per-registration evidence (call address, address of the instruction that pushes the value): `findings/enums_entries.json`.
Extraction scripts: `work/enums/extract.py`, `extract3.py`, `build.py`.

## How enums are registered — read from code

- **Everything is registered by code in the exe; nothing is loaded from game files.** The only writer of the enum table is
  `FUN_005052c9(const char *family, const char *fullName, int value)` (cdecl, 0x5052c9). It first looks the full name up
  (0x4f915b, by hash); if absent it appends a record {family, fullName, value} to the global table at 0xc8bd78
  (`call 0x503667` at 0x50534f — the only call to that append in the exe) and pushes `hash(family)` to 0xc8bd90 and
  `hash(fullName)` to 0xc8bd84 (hash = `FUN_00423ce8`, see the note at the end).
  `FUN_0050574a` (thiscall, `ret 0xc`) is a thin wrapper that calls it with the same three arguments and remembers the index in `[this+0x44]`.
- There are 1,814 call sites to the two functions (1,813 real registrations + the wrapper's own inner call), in 65 class/library
  registration functions. Every one was resolved: 1,807 by simulating the pushes, plus the 6 `LANGUAGE` entries whose name is built
  at run time (`sprintf("LANGUAGE___%s", upper(name))`, 0x47ffdd-0x48017d; upper-casing loop 0x410312).
- **The family is the first argument, not the text before `___`.** `GAME_EVENT___X` is registered into family `GAME_EVENTS`,
  `CHARACTER_TYPE___X` into `CHARACTER_TYPES`, `CHARACTER_ANIMATION___X` into `CHARACTER_ANIMATIONS`, and so on. The family string is
  what `control=autodropdown|items=FAMILY` refers to. `enums.json` is keyed by family; `meta[family].prefixes` gives the name prefix.
  The prefix `WEAPON_TYPE___` feeds two different families (`WEAPON_TYPES` and `WEAPON_TYPE`).
- Values: 1,623 are immediate pushes, 6 are the LANGUAGE entries, and 184 are register pushes (`push ebx` and the like) whose register was set earlier in the
  function (`xor ebx,ebx`, `push N / pop reg`, `inc`, `or reg,-1`). They were resolved by a single-path simulation from the function
  start and checked: every non-zero register value fills a gap in its family and collides with nothing.
  One trap, now handled: in 0x809e94 `inc ebx` appears on both arms of an allocation check (0x809ec8 / 0x809ee4), so a naive
  linear sweep reads 2 where the value is 1 (this affects 18 names, e.g. `ANIMATION_EVENT___PUNCH`, `OPPONENT_MODEL_TYPE___RORSCHACH`).
- Result: **186 families, 1,801 distinct names** (1,813 registrations; 12 repeat an existing name with the same value).
  No name is registered with two different values.
- The exe holds 1,561 strings of the form `X___Y`; all but `LANGUAGE___%s` are pushed at a registration site. Other strings
  such as `KEY_A`, `GAMEPAD_DPAD_UP` are registered without a prefix (families `KeyboardKeys`, `GamepadButton`, ..., whose
  family pointer is read from a global, e.g. `[0xc8b004]` -> "KeyboardKeys").

## Animation criteria — read from code

`AnimationCriteriaMet` 0x5c5781, criteria record offsets from the property registration order (0x5d3062):

| kind | name | what is tested |
|---|---|---|
| 0 | VALUE | `GetAnimationValue(m_ianimationvalue)` (AnimationLib method +0x1c, 0x5ae18f) against min/max with `m_iintervaltype` (`MathLib.InsideInterval`) |
| 1 | ACTION | `IsAnimationActionPending(m_ianimationaction)` (method +0x38, 0x5aa7f7) |
| 2 | ENUM | `GetAnimationEnum(m_ianimationenum)` (method +0x30, 0x5ae25d) `== m_ianimationenumvalue` |
| 3 | EVENT | event `m_ianimationevent` fired |
| 4 | PLAY_TIME | seconds played |
| 5 / 6 | PLAY_POS / REVERSE_PLAY_POS | play position / 1 - play position |
| 7 / 8 | OVERLAY_PLAY_POS / REVERSE_OVERLAY_PLAY_POS | same on the overlay page |
| 9 | ANIM_PLAY_DONE | page flag +0x18 |
| 10 | FORCE_ANIM | |
| 11 / 12 | ANY_OF / ALL_OF | OR / AND over child criteria |

Interval type (inline dropdown on the property): INTERVAL 0, LESS_THAN 1, GREATER_THAN_OR_EQUAL 2.

**For kind ENUM the engine reads only `m_ianimationenum` (rec+0x28) and `m_ianimationenumvalue` (rec+0x2c)** (decompiled branch
`iVar9 == 2`). `m_ianimationvalue` (rec+0x14) is read only in the VALUE branch.

## Disagreements with the toolkit

1. **"Enum var 11 = character type" is `ANIMATION_ENUM___OPPONENT_MODEL_TYPE`** — the *opponent's* model type, and its values are the
   `OPPONENT_MODEL_TYPE` family: NONE 0, RORSCHACH 1, NITE_OWL 2, ENEMY_01 3, ENEMY_02_BIG_GUY 4, UNDERBOSS 5, ENEMY_03 6, ENEMY_04 7.
   The seven ids the toolkit uses agree with the exe exactly. They are *not* `CHARACTER_TYPES` (there RORSCHACH 0, NITE_OWL 1, BIKER 2, ...).
2. **The "value slot" 0 / 4 / 14 / 23 is not a selector of whose type is tested.** It is `m_ianimationvalue`, an `ANIMATION_VALUE`
   id (0 NONE, 4 ATTACK_MOVE_DIST, 14 RELATIVE_HEAD_HEIGHT, 23 VERTICAL_HEIGHT_TO_TARGET) that the ENUM branch never reads; it is
   whatever was left in the editor's Value box. `anim_meta.py` (`_VAR_PARTNER = (0, 4)`, `_is_partner_type_leaf`) therefore drops
   real opponent-type tests. In the Part 2 data there are 7 such criteria: `NiteOwlAttackFragment` 4x `ENEMY_02_BIG_GUY` (slot 23),
   `RorshackAttackFragment` 1x `ENEMY_02_BIG_GUY` (slot 23), `AnimationClassRorschach` `NOT NITE_OWL` (slot 14),
   `AnimationClassNiteOwl` `NOT RORSCHACH` (slot 14). Their captions name an opponent type, as the code predicts.
3. **`anim_meta.json` `event_names`**: 74 of 75 entries agree with the exe. Id 14 is `WALK_CYCLE_POINT` in the data captions and
   `UNUSED` in the exe (`ANIMATION_EVENT___UNUSED` = 14). 18 registered events never occur in `event_names`:
   1 PUNCH, 3 STOP_R, 22 ALLOW_AUTOAIM, 42 NO_LONGER_IMMUNE_TO_ATTACK, 43 RIGHT_FOOT_UP, 44 LEFT_FOOT_UP, 50 RIGHT_ROTATED_HEADING,
   51 LEFT_ROTATED_HEADING, 63-65 UNDERBOSS_*_FLAMER*, 66/67 TRIGGER_*_INTERPOLATING, 68 UNDERBOSS_JUMP_OFF_LAND_DONE,
   71 UNDERBOSS_WOBBLE_DONE, 81 UNDERBOSS_SUPPORT_EVENT, 89/90 *_DEPTH_OF_FIELD.
4. `ENGINE_CONSTANTS.md` "CHARACTER_TYPE enum (full)" omits `COP_FAST` = 24 and `INVALID` = -1; the rest agrees.
5. `ENGINE_CONSTANTS.md` "WEAPON_TYPE enum: BASH_1H/MELEE_ONE_HAND=0, BASH_2H/MELEE_TWO_HAND=1" merges two families:
   `WEAPON_TYPES` {NONE -1, BASH_1H 0, BASH_2H 1} and `WEAPON_TYPE` {MELEE_ONE_HAND 0, MELEE_TWO_HAND 1}. The weapon the criteria
   test is neither: enum variable 5 is `WEAPON_ANIMATION_TYPE` {UNARMED 0, BASH_1H 1, BASH_2H 2}, and variable 12 is
   `OPPONENT_WEAPON_TYPE` {NONE -1, BASH_1H 0, BASH_2H 1} (stored as 4294967295 in the fragments for NONE).

## Checked against the game data (Part 2 PC, all 906 `.fragment.json`, read-only)

Criteria captions are the editor's own rendering of the ids, so they test the tables independently:
kind ACTION — all 35 action ids match `CONTROL_ACTION_TYPES`; kind ENUM — variables 1, 4, 10, 11, 12, 13, 14, 15 match
`CHARACTER_MODE`, `DAMAGE_POSE` (all 29), `TARGET_LOCK`, `OPPONENT_MODEL_TYPE` (1-7), `OPPONENT_WEAPON_TYPE`, `KNEE`,
`SPECIFIC_MODEL`, `SCENE_ID` (40 = PLAYER_VS_PLAYER); kind VALUE — 16 variables match `ANIMATION_VALUE`; kind EVENT — 8, 13, 80 match.
State names agree with `ANIMATION_STATE` ids (1 ThrownByRorschach, 9 Idle, 10 Countered_by_*, 13 Ragdoll-Idle, 84 GrapplingHookStraightDown, ...).
Not checked on data: families the animation fragments do not use.

## Animation-related families

### `ANIMATION_CRITERIA` (13 names, prefix `ANIMATION_CRITERIA___`, registered in 0x5e50f7)
`AnimationCriteria.m_ianimationcriteria` (rec+0x10). Dispatch on these ids is in `AnimationCriteriaMet` 0x5c5781.

| id | name |
|---|---|
| 0 | VALUE |
| 1 | ACTION |
| 2 | ENUM |
| 3 | EVENT |
| 4 | PLAY_TIME |
| 5 | PLAY_POS |
| 6 | REVERSE_PLAY_POS |
| 7 | OVERLAY_PLAY_POS |
| 8 | REVERSE_OVERLAY_PLAY_POS |
| 9 | ANIM_PLAY_DONE |
| 10 | FORCE_ANIM |
| 11 | ANY_OF |
| 12 | ALL_OF |

### `ANIMATION_ENUM` (16 names, prefix `ANIMATION_ENUM___`, registered in 0x809e94)
The criteria ENUM *variables*: `m_ianimationenum` (rec+0x28) indexes `AnimationData.m_ienumlist`; each slot holds a value of the family with the same name (below).

| id | name |
|---|---|
| 0 | ATTACK_DIR |
| 1 | CHARACTER_MODE |
| 2 | ATTACK_TYPE |
| 3 | ATTACK_POSE |
| 4 | DAMAGE_POSE |
| 5 | WEAPON_ANIMATION_TYPE |
| 6 | MODEL_ANIMATION_TYPE |
| 7 | TARGET_MODE |
| 8 | OVERRIDE_ATTACK_COMBO |
| 9 | STATE_CHANGE_OVERRIDE |
| 10 | TARGET_LOCK |
| 11 | OPPONENT_MODEL_TYPE |
| 12 | OPPONENT_WEAPON_TYPE |
| 13 | KNEE |
| 14 | SPECIFIC_MODEL |
| 15 | SCENE_ID |

### `ANIMATION_VALUE` (25 names, prefix `ANIMATION_VALUE___`, registered in 0x809e94)
The criteria VALUE *variables*: `m_ianimationvalue` (rec+0x14) indexes `AnimationData.m_nparameterlist`. Also used by blend nodes (`m_iblendctrlparam`, `m_ilayerweightctrlparam`).

| id | name |
|---|---|
| 0 | NONE |
| 1 | SPEED |
| 2 | DIRECTION |
| 3 | FREEFALL |
| 4 | ATTACK_MOVE_DIST |
| 5 | HEALTH |
| 6 | CHARACTER_PELVIS_ROTATION |
| 7 | CHARACTER_PELVIS_STATIONARY |
| 8 | CHARACTER_PELVIS_RAGDOLL_FREE |
| 9 | DISTANCE_TO_END_POS |
| 10 | CHARACTER_PELVIS_VELOCITY |
| 11 | CHARACTER_PELVIS_GROUND_HEIGHT |
| 12 | ANGLE_TO_TARGET |
| 13 | VERTICAL_ANGLE_TO_TARGET |
| 14 | RELATIVE_HEAD_HEIGHT |
| 15 | SPEED_TIME |
| 16 | TARGET_ANGLE_TO_YOU |
| 17 | HEAD_ANGLE_TO_TARGET |
| 18 | HEAD_VERTICAL_ANGLE_TO_TARGET |
| 19 | HAS_WEAPON |
| 20 | BLOCK_TIME |
| 21 | HAS_1H_WEAPON |
| 22 | HAS_2H_WEAPON |
| 23 | VERTICAL_HEIGHT_TO_TARGET |
| 24 | TARGET_DIST |

### `ANIMATION_STATE` (84 names, prefix `ANIMATION_STATE___`, registered in 0x809e94)
`AnimationState.m_istateid` / `m_imasterof`. No id 14 is registered.

| id | name |
|---|---|
| 0 | NONE |
| 1 | THROWN_BY_RORSCHACH |
| 2 | CLIMB_DRAIN |
| 3 | JUMP_DOWN_AUTO_HEIGHT |
| 4 | CLIMB_DRAIN_DOWN |
| 5 | GRAPPLING_HOOK |
| 6 | GRAPPLING_HOOK_DOWN |
| 7 | JUMP_DOWN_1M |
| 8 | FINISH_MOVE_VICTIM_01 |
| 9 | COMBAT_IDLE |
| 10 | COUNTER_ATTACK_VICTIM_01 |
| 11 | BULLRUSH_VICTIM |
| 12 | GRAB_1H_WEAPON |
| 13 | RAGDOLL_IDLE |
| 15 | PULL_LEVER |
| 16 | TURN_VALVE |
| 17 | PULL_SWITCH |
| 18 | JUMP_DOWN_2M |
| 19 | CLIMB_UP_1M |
| 20 | JUMP_ACROSS_3M |
| 21 | LOCKPICK_START |
| 22 | LOCKPICK_END |
| 23 | LIFT_START |
| 24 | LIFT_END |
| 25 | LIFT |
| 26 | SQUEEZE_UNDER |
| 27 | COUNTER_ATTACK_VICTIM_02 |
| 28 | COUNTER_ATTACK_VICTIM_03 |
| 29 | COUNTER_ATTACK_VICTIM_04 |
| 30 | COUNTER_ATTACK_VICTIM_05 |
| 31 | COUNTER_ATTACK_VICTIM_06 |
| 32 | COUNTER_ATTACK_VICTIM_07 |
| 33 | FINISH_MOVE_VICTIM_02 |
| 34 | FINISH_MOVE_VICTIM_03 |
| 35 | FINISH_MOVE_VICTIM_04 |
| 36 | FINISH_MOVE_VICTIM_05 |
| 37 | FINISH_MOVE_VICTIM_06 |
| 38 | FINISH_MOVE_VICTIM_07 |
| 39 | CLIMB_LADDER |
| 40 | CLIMB_LADDER_DOWN |
| 41 | RESIST |
| 42 | JUMP_UP_6M |
| 43 | UNDERBOSS_USE_FLAMER |
| 44 | UNDERBOSS_JUMP_OFF_PLATFORM |
| 45 | UNDERBOSS_JUMP_OFF_MIDAIR |
| 46 | UNDERBOSS_JUMP_OFF_LAND |
| 47 | UNDERBOSS_JUMP_ON_PLATFORM |
| 48 | RORSCHACH_MENU_ANIMATION |
| 49 | NITE_OWL_MENU_ANIMATION |
| 50 | UNDERBOSS_WOBBLE |
| 51 | UNDERBOSS_DEFEAT |
| 52 | UNDERBOSS_EQUIP_FLAMER |
| 53 | UNDERBOSS_UNEQUIP_FLAMER |
| 54 | UNDERBOSS_PICKUP_WEAPON |
| 55 | COUNTER_ATTACK_VICTIM_08 |
| 56 | FINISH_MOVE_VICTIM_08 |
| 57 | COUNTER_ATTACK_VICTIM_09 |
| 58 | UNDERBOSS_WOBBLE_LEFT |
| 59 | UNDERBOSS_IDLE_TAUNT_A |
| 60 | UNDERBOSS_IDLE_TAUNT_B |
| 61 | UNDERBOSS_IDLE_TAUNT_C |
| 62 | UNDERBOSS_IDLE_TAUNT_D |
| 63 | UNDERBOSS_IDLE_TAUNT_E |
| 64 | UNDERBOSS_IDLE_TAUNT_F |
| 65 | UNDERBOSS_IDLE_TAUNT_G |
| 66 | UNDERBOSS_IDLE_TAUNT_H |
| 67 | UNDERBOSS_IDLE_TAUNT_I |
| 68 | UNDERBOSS_IDLE_TAUNT_J |
| 69 | UNDERBOSS_RECHARGE |
| 70 | UNUSED |
| 71 | COUNTER_ATTACK_VICTIM_10 |
| 72 | COUNTER_ATTACK_VICTIM_11 |
| 73 | UNDERBOSS_DEFEAT_PER_LEVEL |
| 74 | KNOCKDOWN_ANIM |
| 75 | JUMP_DOWN_4M_WITH_RAILING |
| 76 | KICK_OPEN_DOOR |
| 77 | SLIDE_DOOR_LEFT |
| 78 | SLIDE_DOOR_RIGHT |
| 79 | FINISH_MOVE_VICTIM_09 |
| 80 | FINISH_MOVE_VICTIM_10 |
| 81 | COUNTER_ATTACK_VICTIM_12 |
| 82 | FINISH_MOVE_VICTIM_11 |
| 83 | FINISH_MOVE_VICTIM_12 |
| 84 | GRAPPLE_STRAIGHT_DOWN |

### `ANIMATION_EVENT` (93 names, prefix `ANIMATION_EVENT___`, registered in 0x809e94)
`AnimationEvent.m_ianimationevent`, and criteria kind EVENT. No id 10 is registered.

| id | name |
|---|---|
| 0 | NONE |
| 1 | PUNCH |
| 2 | STOP_L |
| 3 | STOP_R |
| 4 | IMPACT |
| 5 | BRANCH |
| 6 | LEFT_FOOT_DOWN |
| 7 | ANIMATION_DRIVEN |
| 8 | TRIGGER_01 |
| 9 | SOUND |
| 11 | DISABLE_ROTATION_INPUT |
| 12 | ENABLE_ROTATION_INPUT |
| 13 | CAN_GO_TO_MOVEMENT |
| 14 | UNUSED |
| 15 | CHARGE |
| 16 | PRE_IMPACT |
| 17 | GRAPPLING_HOOK |
| 18 | CAMERA |
| 19 | LEAVE_ABSOLUTE_MODE |
| 20 | KILL_ANIMATION_PARTNER |
| 21 | DISALLOW_AUTOAIM |
| 22 | ALLOW_AUTOAIM |
| 23 | CLEAR_DEADZONE |
| 24 | ALLOW_ATTACKS |
| 25 | DISABLE_CHARACTER_COLLISION |
| 26 | DROP_TARGET_LOCK |
| 27 | FORCE_ALLOW_COUNTER_ATTACK |
| 28 | ABSOLUTE_GOTO_TARGET_POS |
| 29 | FLASH_GRENADE |
| 30 | ELECTRIFY_ARMOR |
| 31 | DISCHARGE_ARMOR |
| 32 | COUNTER_ATTACK_WEAPON_STEAL |
| 33 | BULLMOVE_IMPACT |
| 34 | STEP_AROUND |
| 35 | EXTEND_COMBO_TIME |
| 36 | PICK_UP_WEAPON |
| 37 | SPEAK |
| 38 | THROW_BRANCH_POINT |
| 39 | GOT_UP |
| 40 | RIGHT_FOOT_DOWN |
| 41 | REVERSE_HEADING |
| 42 | NO_LONGER_IMMUNE_TO_ATTACK |
| 43 | RIGHT_FOOT_UP |
| 44 | LEFT_FOOT_UP |
| 45 | LOOK_AT_TARGET |
| 46 | GRAPGUN_ENABLE |
| 47 | GRAPGUN_DISABLE |
| 48 | SET_MOVE_AS_FACEHEADING |
| 49 | NORMAL_HEADING |
| 50 | RIGHT_ROTATED_HEADING |
| 51 | LEFT_ROTATED_HEADING |
| 52 | FACE_HEADING_FORCE_IGNORE |
| 53 | FACE_HEADING_REMOVE_FORCE_IGNORE |
| 54 | ROTATE_HEADING_90_LEFT |
| 55 | ROTATE_HEADING_90_RIGHT |
| 56 | IMPACT_EFFECTS |
| 57 | SAFE_RAGDOLL_COLLISION |
| 58 | DROP_WEAPON |
| 59 | CAMERA_CUT |
| 60 | STARTING_UBER_RAGE |
| 61 | CAMERA_CUT_TO_CHARACTER_CAM |
| 62 | SET_HEADINGS_FROM_ALIGNEMENT |
| 63 | UNDERBOSS_START_FLAMER |
| 64 | UNDERBOSS_STOP_FLAMER |
| 65 | UNDERBOSS_FLAMER_DONE |
| 66 | TRIGGER_START_INTERPOLATING |
| 67 | TRIGGER_END_INTERPOLATING |
| 68 | UNDERBOSS_JUMP_OFF_LAND_DONE |
| 69 | MAKE_LIGHTNING_FLASH |
| 70 | THROW_MODE_STORE_TARGET |
| 71 | UNDERBOSS_WOBBLE_DONE |
| 72 | KNEE |
| 73 | RAGDOLL_MODIFIER |
| 74 | REMOVE_INVERSE_DIRECTION |
| 75 | DROP_WEAPON_WITH_ANIM |
| 76 | FOOT_DOWN_JUMP |
| 77 | FOOT_DOWN_STOP |
| 78 | LOOP_START |
| 79 | LOOP_END |
| 80 | DO_AUTO_ALIGN |
| 81 | UNDERBOSS_SUPPORT_EVENT |
| 82 | RUMBLE |
| 83 | STARTING_HURT_ANIMATION |
| 84 | DO_BLOCK_FLASH |
| 85 | DIE |
| 86 | DELAY_OPPONENT |
| 87 | FORCE_ALLOW_BREAKOUT |
| 88 | FORCE_ALLOW_BREAKOUT_NO_MORE |
| 89 | ACTIVATE_DEPTH_OF_FIELD |
| 90 | DEACTIVATE_DEPTH_OF_FIELD |
| 91 | NEVER_USE_THIS_ANIM_AGAIN |
| 92 | STOP_TWILIGHT_CAM_LOCK |
| 93 | DO_CHOKE_EFFECT |

### `ANIMATION_EVENT_TYPES` (4 names, prefix `ANIMATION_EVENT_TYPE___`, registered in 0x5e50f7)


| id | name |
|---|---|
| 0 | PLAY_POS |
| 1 | ENTER_STATE |
| 2 | LEAVE_STATE |
| 3 | TOTAL_PLAY_TIME |

### `CONTROL_ACTION_TYPES` (35 names, prefix `CONTROL_ACTION_TYPE___`, registered in 0x809e94)
Criteria kind ACTION: `m_ianimationaction` (rec+0x24). The property UI is a plain string box, so the link to this family is **inferred**, then confirmed on data: all 35 ids in shipped criteria carry the matching caption.

| id | name |
|---|---|
| 0 | PUNCH |
| 1 | NORMAL_ATTACK |
| 2 | HITTAKEN |
| 3 | FINISHING_MOVE |
| 4 | THROW |
| 5 | THROW_GRAB_FAILED |
| 6 | BULLMOVE |
| 7 | HEAVY_PUNCH |
| 8 | RAGDOLL |
| 9 | GRAPPLING_RELEASE |
| 10 | GRAPPLING_LAND |
| 11 | DODGE |
| 12 | COUNTER_ATTACK |
| 13 | STICK_FLICK |
| 14 | ONE_FRAME_ACTION |
| 15 | NEVER_FIRED |
| 16 | IDLE_ALLOWED |
| 17 | THROW_GRENADE |
| 18 | ELECTRIFY_ARMOR |
| 19 | STEP_AROUND_ATTACK |
| 20 | BLOCK |
| 21 | INITIAL_ATTACK |
| 22 | INITIALIZE_BLOCK |
| 23 | BREAK_LOOP |
| 24 | STICK_REVERSE |
| 25 | AFTER_DASH_ATTACK |
| 26 | STEP |
| 27 | DROP_WEAPON |
| 28 | START_UBER_RAGE |
| 29 | KILL_PRONE_TARGET |
| 30 | ATTACK_BLOCKED |
| 31 | START_SPEAK |
| 32 | STOP_SPEAK |
| 33 | BECKON |
| 34 | FLIP_MOVE |

### `OPPONENT_MODEL_TYPE` (8 names, prefix `OPPONENT_MODEL_TYPE___`, registered in 0x809e94)
Values of enum variable 11. **These are the ids the toolkit calls "character type".**

| id | name |
|---|---|
| 0 | NONE |
| 1 | RORSCHACH |
| 2 | NITE_OWL |
| 3 | ENEMY_01 |
| 4 | ENEMY_02_BIG_GUY |
| 5 | UNDERBOSS |
| 6 | ENEMY_03 |
| 7 | ENEMY_04 |

### `OPPONENT_WEAPON_TYPE` (3 names, prefix `OPPONENT_WEAPON_TYPE___`, registered in 0x809e94)


| id | name |
|---|---|
| -1 | NONE |
| 0 | BASH_1H |
| 1 | BASH_2H |

### `WEAPON_ANIMATION_TYPE` (3 names, prefix `WEAPON_ANIMATION_TYPE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | UNARMED |
| 1 | BASH_1H |
| 2 | BASH_2H |

### `MODEL_ANIMATION_TYPE` (3 names, prefix `MODEL_ANIMATION_TYPE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | RORSHACK |
| 1 | NITE_OWL |
| 2 | ENEMY_1 |

### `CHARACTER_MODE` (5 names, prefix `CHARACTER_MODE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NONCOMBAT |
| 1 | COMBAT |
| 2 | DEAD |
| 3 | STUNNED |
| 4 | PRONE |

### `ATTACK_DIR` (2 names, prefix `ATTACK_DIR___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | LEFT |
| 1 | RIGHT |

### `ATTACK_TYPES` (3 names, prefix `ATTACK_TYPE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | HEAVY |
| 1 | LIGHT |
| 2 | THROW |

### `ATTACK_POSE` (2 names, prefix `ATTACK_POSE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | POSE_DEFAULT |
| 1 | POSE_AFTER_DASH |

### `DAMAGE_POSE` (29 names, prefix `DAMAGE_POSE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NO_POSE |
| 1 | LIGHT_UPPER_LEFT |
| 2 | LIGHT_UPPER_STRAIGHT |
| 3 | LIGHT_UPPER_RIGHT |
| 4 | LIGHT_MIDDLE_LEFT |
| 5 | LIGHT_MIDDLE_STRAIGHT |
| 6 | LIGHT_MIDDLE_RIGHT |
| 7 | HEAVY_UPPER_LEFT |
| 8 | HEAVY_UPPER_STRAIGHT |
| 9 | HEAVY_UPPER_RIGHT |
| 10 | HEAVY_MIDDLE_LEFT |
| 11 | HEAVY_MIDDLE_STRAIGHT |
| 12 | HEAVY_MIDDLE_RIGHT |
| 13 | KNOCKDOWN_UPPER_LEFT |
| 14 | KNOCKDOWN_UPPER_STRAIGHT |
| 15 | KNOCKDOWN_UPPER_RIGHT |
| 16 | KNOCKDOWN_MIDDLE_LEFT |
| 17 | KNOCKDOWN_MIDDLE_STRAIGHT |
| 18 | KNOCKDOWN_MIDDLE_RIGHT |
| 19 | STUN_UPPER |
| 20 | STUN_MIDDLE |
| 21 | STUN_UPPER_BACK |
| 22 | STUN_MIDDLE_BACK |
| 23 | LIGHT_UPPER_BACK |
| 24 | LIGHT_MIDDLE_BACK |
| 25 | HEAVY_UPPER_BACK |
| 26 | HEAVY_MIDDLE_BACK |
| 27 | KNOCKDOWN_UPPER_BACK |
| 28 | KNOCKDOWN_MIDDLE_BACK |

### `OVERRIDE_ATTACK_COMBO` (9 names, prefix `OVERRIDE_ATTACK_COMBO___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NORMAL |
| 1 | KNOCKDOWN |
| 2 | STUN |
| 3 | HEAVY_DAM |
| 4 | FINISHING_MOVE |
| 5 | AREA_DAMAGE |
| 6 | COUNTER_ATTACK |
| 7 | KILL_PRONE_TARGET |
| 8 | SUPER_DAMAGE |

### `STATE_CHANGE_OVERRIDE` (2 names, prefix `STATE_CHANGE_OVERRIDE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NO_OVERRIDE |
| 1 | ALLOW_LEAVE_STATE |

### `TARGET_LOCK` (2 names, prefix `TARGET_LOCK___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NO_TARGET |
| 1 | TARGET_LOCK |

### `KNEE` (4 names, prefix `KNEE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NONE |
| 1 | LEFT |
| 2 | RIGHT |
| 3 | BOTH |

### `SPECIFIC_MODEL` (2 names, prefix `SPECIFIC_MODEL___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | DEFAULT |
| 1 | TWILIGHT_LADY |

### `SCENE_ID` (15 names, prefix `SCENE_ID___`, registered in 0x80c150)


| id | name |
|---|---|
| -1 | NONE |
| 0 | MAIN_MENU |
| 1 | PRISON |
| 2 | STREETS |
| 3 | DOCKS |
| 4 | UNDERGROUND |
| 5 | CONSTRUCT_SITE |
| 6 | STREETS_2 |
| 7 | NIGHTCLUB |
| 8 | STREETS_OF_RIOTS |
| 9 | BORDELLO |
| 20 | GAME_ESSENTIALS |
| 30 | TUTORIAL |
| 40 | PLAYER_VS_PLAYER |
| 50 | DEBUG_TOOL_CHECKER |

### `ANIMATION_SPECIAL_CASE` (15 names, prefix `ANIMATION_SPECIAL_CASE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NORMAL |
| 1 | INVERSE_CONTROL_DIRECTION |
| 2 | FLY_TO_SPECIAL_TARGET |
| 3 | ABSOLUTE_START_AT_CURRENT_POS |
| 4 | RESEND_PUNCH_WHEN_IN_RANGE |
| 5 | DODGE |
| 6 | BULL_MOVE |
| 7 | SET_IDLE_TIME |
| 8 | BLOCK |
| 9 | BYPASS_BLOCKER |
| 10 | SPAM_SEND_SPECIAL_ACTION |
| 11 | STEP_AROUND |
| 12 | FIT_TO_END_POS_Y |
| 13 | IMMUNE_TO_BREAK_ATTACK |
| 14 | FAILED_THROW |

### `ANIMATION_TYPE` (16 names, prefix `ANIMATION_TYPE`/`ANIMATOIN_TYPE___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | NOTSET |
| 4 | LIGHTATTACK |
| 5 | HEAVYATTACK |
| 6 | BLOCK |
| 7 | DODGE |
| 8 | COUNTERATTACK |
| 9 | FINISHINGMOVE |
| 10 | THROW |
| 11 | DAMAGE |
| 12 | STUNNED |
| 13 | BULLMOVE |
| 14 | NOTUSED |
| 15 | FLASHGRENADE |
| 16 | ELECTRIFYARMOR |
| 17 | AI_SYSTEM_ONLY__ANY_ATTACK |
| 19 | STEP |

### `ANIMATION_LAYER` (12 names, prefix `ANIMATION_LAYER___`, registered in 0x5e50f7)


| id | name |
|---|---|
| 0 | MOTION_LAYER_1 |
| 1 | MOTION_LAYER_2 |
| 2 | MOTION_LAYER_3 |
| 3 | MOTION_LAYER_4 |
| 4 | MOTION_LAYER_5 |
| 5 | MOTION_LAYER_6 |
| 10 | ACTION_LAYER_1 |
| 11 | ACTION_LAYER_2 |
| 12 | ACTION_LAYER_3 |
| 13 | ACTION_LAYER_4 |
| 14 | ACTION_LAYER_5 |
| 15 | ACTION_LAYER_6 |

### `ACTION_LAYER_FLAG` (6 names, prefix `ACTION_LAYER_FLAG___`, registered in 0x5e50f7)


| id | name |
|---|---|
| 1 | ACTION_LAYER_1 |
| 2 | ACTION_LAYER_2 |
| 4 | ACTION_LAYER_3 |
| 8 | ACTION_LAYER_4 |
| 16 | ACTION_LAYER_5 |
| 32 | ACTION_LAYER_6 |

### `CHARACTER_ANIMATIONS` (12 names, prefix `CHARACTER_ANIMATION___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | RSH |
| 1 | NTO |
| 2 | BS1 |
| 3 | EN1 |
| 4 | EN1_FAST |
| 5 | EN2 |
| 6 | EN3 |
| 7 | EN1_FACE |
| 8 | NTO_FACE |
| 9 | UB_FACE |
| 10 | EN4 |
| 11 | EN4_FACE |

### `CHARACTER_TYPES` (32 names, prefix `CHARACTER_TYPE___`, registered in 0x80c150)
`items=CHARACTER_TYPES`; a different family from OPPONENT_MODEL_TYPE. Ids 5, 7, 13, 17, 20, 21 are not registered.

| id | name |
|---|---|
| -1 | INVALID |
| 0 | RORSCHACH |
| 1 | NITE_OWL |
| 2 | BIKER |
| 3 | BIKER_BIG |
| 4 | PRISONER |
| 6 | PRISONER_FAST |
| 8 | THUG |
| 9 | THUG_BIG |
| 10 | THUG_FAST |
| 11 | THUG_LEADER |
| 12 | MERCENARY |
| 14 | MERCENARY_FAST |
| 15 | MERCENARY_LEADER |
| 16 | MINION |
| 18 | MINION_FAST |
| 19 | MINION_LEADER |
| 22 | COP |
| 23 | COP_LEADER |
| 24 | COP_FAST |
| 25 | UNDERBOSS |
| 26 | BIKER_HEAD |
| 27 | PRISONER_ELITE |
| 28 | GO_GO_DANCER |
| 29 | HEAVIES |
| 30 | KNOT_TOP_NORMAL |
| 31 | KNOT_TOP_FAST |
| 32 | KNOT_TOP_BIG |
| 33 | DOMINATRICE |
| 34 | GIMP |
| 35 | TWILIGHT_LADY |
| 36 | GIMP_WITH_GAGBALL |

### `WEAPON_TYPES` (3 names, prefix `WEAPON_TYPE___`, registered in 0x6726d6)
registered at 0x6726d6 (prefix `WEAPON_TYPE___`).

| id | name |
|---|---|
| -1 | NONE |
| 0 | BASH_1H |
| 1 | BASH_2H |

### `WEAPON_TYPE` (2 names, prefix `WEAPON_TYPE___`, registered in 0x8bb4aa)
a second, separate family with the same prefix, registered at 0x8bb4aa.

| id | name |
|---|---|
| 0 | MELEE_ONE_HAND |
| 1 | MELEE_TWO_HAND |

### `ANIMATION_HEAD_MODEL` (27 names, prefix `ANIMATION_HEAD_MODEL___`, registered in 0x809e94)


| id | name |
|---|---|
| 0 | LARGE_HEAD_1 |
| 1 | LARGE_HEAD_2 |
| 2 | LARGE_HEAD_3 |
| 3 | MEDIUM_HEAD_1 |
| 4 | MEDIUM_HEAD_2 |
| 5 | MEDIUM_HEAD_3 |
| 6 | LARGE_HEAD_3KT |
| 7 | SMALL_HEAD_1 |
| 8 | SMALL_HEAD_1KT |
| 9 | MEDIUM_HEAD_MERC_1 |
| 10 | MEDIUM_HEAD_MERC_2 |
| 11 | SMALL_HEAD_MERC_1 |
| 12 | SMALL_HEAD_MERC_2 |
| 13 | LARGE_HEAD_GOATEE |
| 14 | MEDIUM_HEAD_GOATEE |
| 15 | HEAD_UNDERBOSS |
| 16 | HEAD_NITE_OWL |
| 17 | HEAD_TWILIGHT_LADY |
| 18 | HEAD_DOMINATRIX_1 |
| 19 | HEAD_GIMP_1 |
| 20 | HEAD_GIMP_2 |
| 21 | HEAD_DOMINATRIX_2 |
| 22 | HEAVY_1 |
| 23 | HEAD_DOMINATRIX_3 |
| 24 | HEAD_DOMINATRIX_4 |
| 25 | HEAD_DOMINATRIX_5 |
| 26 | HEAD_GIMP_3 |

### `ANIMATION_SYSTEM_NODE_TYPE` (9 names, prefix `ANIMATION_SYSTEM_NODE_TYPE___`, registered in 0x5e50f7)


| id | name |
|---|---|
| 0 | ANIMATION_BLEND |
| 1 | ANIMATION_CRITERIA |
| 2 | ANIMATION_SLOT |
| 3 | ANIMATION_STATE |
| 4 | ANIMATION_TRANSITION |
| 5 | ANIMATION_CLASS |
| 6 | ANIMATION_EVENT |
| 7 | ANIMATION_STATE_GROUP |
| 8 | ANIMATION_PLAY_POS |

## All families

| family | names | name prefix | registered in | id range |
|---|---|---|---|---|
| `ABILITIES_NTO` | 27 | `ABILITY_NTO` | 0x80c150 | 0..26 |
| `ABILITIES_RSH` | 26 | `ABILITY_RSH` | 0x80c150 | 0..25 |
| `ABS_EaseState` | 3 | (none) | 0x595c38 | 0..2 |
| `ACHIEVEMENTS` | 24 | `ACHIEVEMENTS` | 0x80c150 | 0..23 |
| `ACHIEVEMENT_FAILCODE` | 3 | `ACHIEVEMENT_FAILCODE` | 0x4dce04 | 0..2 |
| `ACTION_LAYER_FLAG` | 6 | `ACTION_LAYER_FLAG` | 0x5e50f7 | 1..32 |
| `ACTOR_SOUND_TYPE` | 3 | `ACTOR_SOUND_TYPE` | 0x844c72 | 0..2 |
| `AGENT_BASE_TYPE` | 7 | `AGENT_BASE_TYPE` | 0x5a38a6 | 0..6 |
| `AIAGENTFACTION` | 3 | (none) | 0x4865b9 | 0..2 |
| `AIAGENTTYPE` | 6 | (none) | 0x4865b9 | 0..5 |
| `AIPATHFINDINGCONSTRAINTS` | 2 | (none) | 0x4865b9 | 0..1 |
| `AI_AGENT_TYPES` | 4 | `AI_AGENT_TYPES` | 0x5a38a6 | 0..3 |
| `AI_DEF_TYPE` | 8 | `AI_DEF_TYPE` | 0x5a38a6 | 0..7 |
| `AL_EaseState` | 3 | (none) | 0x5945e5 | 0..2 |
| `ANIMATIION_BONE_TYPES` | 24 | `ANIMATIION_BONE_TYPE` | 0x5e50f7 | 1..8388608 |
| `ANIMATIION_JOINT_TYPES` | 17 | `ANIMATIION_JOINT_TYPE` | 0x5e50f7 | 1..65536 |
| `ANIMATION_CRITERIA` | 13 | `ANIMATION_CRITERIA` | 0x5e50f7 | 0..12 |
| `ANIMATION_DEBUGGER_ITEM_STATUS_TYPES` | 7 | `ANIMATION_DEBUGGER_ITEM_STATUS` | 0x5e50f7 | 0..6 |
| `ANIMATION_DEBUGGER_MOUSE_CLICK_ACTIONS` | 8 | `ANIMATION_DEBUGGER_MOUSE_CLICK_ACTIONS` | 0x5e50f7 | 0..7 |
| `ANIMATION_DEBUG_VISUALIZATIONS` | 3 | `ANIMATION_DEBUG_VISUALIZATIONS` | 0x5e50f7 | 0..2 |
| `ANIMATION_ENUM` | 16 | `ANIMATION_ENUM` | 0x809e94 | 0..15 |
| `ANIMATION_EVENT` | 93 | `ANIMATION_EVENT` | 0x809e94 | 0..93 |
| `ANIMATION_EVENT_TYPES` | 4 | `ANIMATION_EVENT_TYPE` | 0x5e50f7 | 0..3 |
| `ANIMATION_HEAD_MODEL` | 27 | `ANIMATION_HEAD_MODEL` | 0x809e94 | 0..26 |
| `ANIMATION_LAYER` | 12 | `ANIMATION_LAYER` | 0x5e50f7 | 0..15 |
| `ANIMATION_PANEL_PREVIEW_MODE` | 5 | `ANIMATION_PANEL_PREVIEW_MODE` | 0x5e74c1 | 0..4 |
| `ANIMATION_SPECIAL_CASE` | 15 | `ANIMATION_SPECIAL_CASE` | 0x809e94 | 0..14 |
| `ANIMATION_STATE` | 84 | `ANIMATION_STATE` | 0x809e94 | 0..84 |
| `ANIMATION_SYSTEM_NODE_TYPE` | 9 | `ANIMATION_SYSTEM_NODE_TYPE` | 0x5e50f7 | 0..8 |
| `ANIMATION_TYPE` | 16 | `ANIMATION_TYPE`, `ANIMATOIN_TYPE` | 0x809e94 | 0..19 |
| `ANIMATION_VALUE` | 25 | `ANIMATION_VALUE` | 0x809e94 | 0..24 |
| `ARCHIVE_FAILCODE` | 11 | `ARCHIVE_FAILCODE` | 0x4dce04 | 0..10 |
| `ARCHIVE_OPERATION` | 5 | `ARCHIVE_OPERATION` | 0x4dce04 | 0..4 |
| `ARCHIVE_STATUS` | 4 | `ARCHIVE_STATUS` | 0x4dce04 | 0..3 |
| `ATTACK_DIR` | 2 | `ATTACK_DIR` | 0x809e94 | 0..1 |
| `ATTACK_POSE` | 2 | `ATTACK_POSE` | 0x809e94 | 0..1 |
| `ATTACK_TYPES` | 3 | `ATTACK_TYPE` | 0x809e94 | 0..2 |
| `BLACK_SCREEN_TRANSITIONS` | 3 | `BLACK_SCREEN_TRANSITIONS` | 0x850da9, 0x86970e | 0..2 |
| `BUILD_TYPES` | 3 | `BUILD_TYPE` | 0x80c150 | 1..4 |
| `BUTTON_INPUT` | 2 | `BUTTON_INPUT` | 0x775983 | 0..1 |
| `BUTTON_STATES` | 3 | (none) | 0x769c11 | 0..2 |
| `CAMERATYPE` | 7 | `CAMERATYPE` | 0x6424cd | 0..6 |
| `CAMERA_ANIMATION_CONTROLLED_EFFECTS` | 2 | `CAMERA_ANIMATION_CONTROLLED_EFFECT` | 0x6726d6 | 0..1 |
| `CAMERA_ANIMATION_EVENTS` | 13 | `CAMERA_ANIMATION_EVENT` | 0x6726d6 | 0..12 |
| `CAMERA_CAM_DIR_TARGETS` | 4 | `CAMERA_CAM_DIR_TARGET` | 0x850da9 | 0..3 |
| `CAMERA_CHARACTER_DB` | 27 | `CAMERA_CHARACTER_DB` | 0x6424cd | 0..26 |
| `CAMERA_CHARACTER_STATE_PRIORITY` | 2 | `CAMERA_CHARACTER_STATE_PRIORITY` | 0x6424cd | 0..1 |
| `CAMERA_MODE` | 2 | `CAMERA_MODE` | 0x6424cd | 0..1 |
| `CAMERA_MODIFIER_TYPE` | 3 | `CAMERA_MODIFIER_TYPE` | 0x6424cd | 0..2 |
| `CAMERA_MOVEMENTS` | 2 | `CAMERA_MOVEMENTS` | 0x757cc4 | 0..1 |
| `CHARACTER_ANIMATIONS` | 12 | `CHARACTER_ANIMATION` | 0x809e94 | 0..11 |
| `CHARACTER_ANIMATION_ADDON` | 4 | `CHARACTER_ANIMATION_ADDON` | 0x80c150 | 0..3 |
| `CHARACTER_AREAS` | 2 | `CHARACTER_AREA` | 0x6726d6 | 0..1 |
| `CHARACTER_BONE_TYPE` | 23 | `CHARACTER_BONE_TYPE` | 0x6726d6 | 0..22 |
| `CHARACTER_COMBO_ENEMY_STATUS` | 7 | `CHARACTER_COMBO_ENEMY_STATUS` | 0x6726d6 | -1..16 |
| `CHARACTER_COMBO_ITEMS` | 17 | `CHARACTER_COMBO_ITEM` | 0x6726d6 | 0..16 |
| `CHARACTER_HEAD_BONE_TYPES` | 7 | `CHARACTER_HEAD_BONE_TYPE` | 0x6726d6 | 0..6 |
| `CHARACTER_LOD_LEVES` | 3 | `CHARACTER_LOD_LEVE` | 0x6726d6 | 0..2 |
| `CHARACTER_MODE` | 5 | `CHARACTER_MODE` | 0x809e94 | 0..4 |
| `CHARACTER_MOVEMENT_TYPE` | 4 | `CHARACTER_MOVEMENT_TYPE` | 0x6726d6 | 0..3 |
| `CHARACTER_PHYSIC_STATES` | 5 | `CHARACTER_PHYSIC_STATE` | 0x80c150 | 0..4 |
| `CHARACTER_TYPES` | 32 | `CHARACTER_TYPE` | 0x80c150 | -1..36 |
| `COLLISION_EFFECT_TYPES` | 95 | `COLLISION_EFFECT_TYPE` | 0x7f1c71 | 0..94 |
| `COLLISION_GROUP_TYPES` | 20 | `COLLISION_GROUP_TYPE` | 0x8bbc25 | 0..19 |
| `COLLISION_TYPES` | 16 | `COLLISION_TYPE` | 0x8bbc25 | 1..32768 |
| `COLORS` | 16 | (none), `COLOR` | 0x496c76, 0x5e50f7 | 1..8 |
| `COMBAT_EFFECT_TYPES` | 4 | `COMBAT_EFFECT_TYPE` | 0x7f1c71 | 0..3 |
| `CONTROL_ACTION_TYPES` | 35 | `CONTROL_ACTION_TYPE` | 0x809e94 | 0..34 |
| `CONTROL_SETUP_TYPES` | 3 | `CONTROL_SETUP_TYPES` | 0x757cc4 | 0..2 |
| `DAMAGE_POSE` | 29 | `DAMAGE_POSE` | 0x809e94 | 0..28 |
| `DIRECTION` | 3 | `DIRECTION` | 0x744c98 | 0..2 |
| `EFFECTS` | 20 | `EFFECT` | 0x80c150 | -1..18 |
| `EFFECT_CLIENT_TYPE` | 1 | (none) | 0x74a340 | 0..0 |
| `EFFECT_TYPES` | 3 | (none) | 0x72de90 | 0..2 |
| `ENEMY` | 11 | `ENEMY` | 0x5a38a6 | 0..10 |
| `ENGINE_PLAYMODE` | 4 | `ENGINE_PLAYMODE` | 0x5e50f7 | 0..3 |
| `FORCE_MOVE_ACTION` | 3 | `FORCE_MOVE_ACTION` | 0x864d1f | 0..2 |
| `GAMER_PICTURES` | 2 | `GAMER_PICTURES` | 0x80c150 | 1..2 |
| `GAME_EVENTS` | 57 | `GAME_EVENT` | 0x80c150 | 0..715 |
| `GAME_MODES` | 5 | `GAME_MODE` | 0x80c150 | 0..4 |
| `GAME_MODE_DATA` | 3 | `GAME_MODE_DATA` | 0x753859, 0x868799, 0x86d80e | 1..4 |
| `GENERIC_PARTICLE_SYSTEMS` | 1 | `GENERIC_PARTICLE_SYSTEM` | 0x72de90 | 0..0 |
| `GamepadButton` | 16 | (none) | 0x4d3514 | 0..15 |
| `GamepadStick` | 3 | (none) | 0x4d3514 | 0..2 |
| `GamepadVibrationMotor` | 3 | (none) | 0x4d3514 | 0..2 |
| `HANGBACK_MODE` | 3 | `HANGBACK_MODE` | 0x7687d8 | 0..2 |
| `HIGHLIGHT` | 3 | `HIGHLIGHT` | 0x72de90 | 0..2 |
| `HIT_POSITIONS` | 2 | `HIT_POSITION` | 0x66f617 | 0..1 |
| `INIT_TYPE` | 2 | `INIT_TYPE` | 0x775fde | 0..1 |
| `JOINT_TYPES` | 3 | `JOINT` | 0x51ff66 | 0..2 |
| `KEYBOARD_PARAMETERS` | 2 | `KEYBOARD_PARAMETERS` | 0x757cc4 | 0..1 |
| `KNEE` | 4 | `KNEE` | 0x809e94 | 0..3 |
| `KeyboardKeys` | 118 | (none) | 0x4cc842 | 1..221 |
| `LANGUAGE` | 6 | `LANGUAGE` | 0x47ff8c | 0..5 |
| `LIGHTING_EVENT_EFFECT_TYPE` | 5 | `LIGHTING_EVENT_EFFECT_TYPE` | 0x74a340 | 0..4 |
| `LIGHTNING_PULSE_TYPE` | 1 | `LIGHTNING_PULSE_TYPE` | 0x749101 | 0..0 |
| `LOBBYBUTTONS` | 4 | (none) | 0x8342b2 | 0..3 |
| `LOGICAL_INPUT_BUTTONS` | 34 | `LOGICAL_INPUT_BUTTON` | 0x80c150 | -1..40 |
| `LOGICAL_INPUT_STICKS` | 4 | `LOGICAL_INPUT_STICK` | 0x80c150 | -1..10 |
| `MATERIAL_SHEETS` | 4 | `MATERIAL_SHEET` | 0x80c150 | 1..4 |
| `MENUSTATE` | 3 | (none) | 0x8342b2 | 0..2 |
| `MENU_MOUSE_CLICK_ACTIONS` | 8 | `MM_CLICK_ACTIONS` | 0x7c4f82 | -1..6 |
| `MENU_SOUNDS` | 3 | `MENU_SOUNDS` | 0x7c4f82 | 0..7 |
| `META_INPUT_DEVICES` | 4 | (none) | 0x775983 | -1..2 |
| `MODEL_ANIMATION_TYPE` | 3 | `MODEL_ANIMATION_TYPE` | 0x809e94 | 0..2 |
| `MODEL_PRIORITY` | 6 | `MODEL_PRIORITY` | 0x80c150 | 0..5 |
| `MOTION_TYPES` | 3 | `MOTION` | 0x51ff66 | 0..2 |
| `MOTOR_TYPES` | 2 | `MOTOR` | 0x51ff66 | 0..1 |
| `MOUSE_STICKS` | 1 | (none) | 0x77631a | 0..0 |
| `MOVEMENT_TYPES` | 3 | `MOVEMENT_TYPE` | 0x518a9a | 0..2 |
| `MouseButtons` | 3 | (none) | 0x4db801 | 1..4 |
| `OPERATION` | 4 | (none) | 0x7ed26a | 0..3 |
| `OPPONENT_MODEL_TYPE` | 8 | `OPPONENT_MODEL_TYPE` | 0x809e94 | 0..7 |
| `OPPONENT_WEAPON_TYPE` | 3 | `OPPONENT_WEAPON_TYPE` | 0x809e94 | -1..1 |
| `ORIENTATION_CONTROL_TYPE` | 3 | `ORIENTATION_CONTROL_TYPE` | 0x7ecf11 | 0..2 |
| `OVERRIDE_ATTACK_COMBO` | 9 | `OVERRIDE_ATTACK_COMBO` | 0x809e94 | 0..8 |
| `OVERRIDE_DAMAGE_STATE` | 2 | `OVERRIDE_DAMAGE_STATE` | 0x80c150 | 0..1 |
| `PARTICLESYSTEMEVENT` | 9 | (none) | 0x555456 | 0..8 |
| `PARTNER_AI_STATE` | 9 | `PARTNER_AI_STATE` | 0x5a38a6 | 0..8 |
| `PARTNER_MODIFIED_STATE` | 3 | `PARTNER_MODIFIED_STATE` | 0x7e873b | 0..2 |
| `PHYSICS_TYPES` | 5 | `PHYSICS_TYPE` | 0x518a9a | 0..4 |
| `PIN_TYPES` | 2 | (none) | 0x79aa41 | 0..1 |
| `PLACEMENT` | 2 | `PLACEMENT` | 0x72d075, 0x72ef5d | 0..1 |
| `PLATFORM` | 4 | `PLATFORM` | 0x47ff8c | 0..3 |
| `PLAYABLE_CHARACTERS` | 4 | `PLAYABLE_CHARACTER` | 0x80c150 | -1..2 |
| `PLAYER` | 2 | `PLAYER` | 0x775983 | 0..1 |
| `PLAYER_AI_STATES` | 8 | `PLAYER_AI_STATES` | 0x5a38a6 | 0..7 |
| `PLAYER_SELECTION_MODE` | 3 | `PLAYER_SELECTION_MODE` | 0x79cf06 | 0..2 |
| `POSITION_CONTROL_TYPE` | 2 | `POSITION_CONTROL_TYPE` | 0x7ecf11 | 0..1 |
| `PREFERENCES_AUTO_AIM` | 3 | (none), `PREFERENCES_AUTO_AIM` | 0x4dce04 | 0..2 |
| `PREFERENCES_AUTO_CENTER` | 3 | `PREFERENCES_AUTO_CENTER` | 0x4dce04 | 0..2 |
| `PREFERENCES_CONTROLSENSITIVITY` | 4 | `PREFERENCES_CONTROLSENSITIVITY` | 0x4dce04 | 0..3 |
| `PREFERENCES_GAMEDIFFICULTY` | 4 | `PREFERENCES_GAMEDIFFICULTY` | 0x4dce04 | 0..3 |
| `PREFERENCES_MOVEMENT_CONTROL` | 3 | `PREFERENCES_MOVEMENT_CONTROL` | 0x4dce04 | 0..2 |
| `PROCESS_STEPS` | 6 | `PROCESS_STEPS` | 0x776ba2 | 0..5 |
| `REPEAT_DEFENCE` | 6 | `REPEAT_DEFENCE` | 0x6fffd7 | 0..5 |
| `ROOT_BEHAVIOR` | 3 | `ROOT_BEHAVIOR` | 0x5a38a6 | -1..1 |
| `SAVETYPE` | 2 | `SAVETYPE` | 0x757cc4 | 0..1 |
| `SAVE_DEVICES` | 7 | `SAVE_DEVICES` | 0x775983 | -1..5 |
| `SAVE_GAME_TYPE` | 4 | `SAVE_GAME_TYPE` | 0x80c150 | 0..3 |
| `SCENE_ID` | 15 | `SCENE_ID` | 0x80c150 | -1..50 |
| `SCRIPT_UPDATE_BUCKETS` | 9 | `SCRIPT_UPDATE_BUCKET` | 0x80c150 | 0..11 |
| `SELECTION_METHODS` | 5 | `SELECTION_METHOD` | 0x837887 | 0..4 |
| `SETTINGS_SPEAKER_TYPES` | 3 | `SETTINGS_SPEAKER_TYPES` | 0x757cc4 | 0..2 |
| `SLIDER_VALUES` | 11 | `SLIDER_VALUES` | 0x757cc4 | 0..10 |
| `SPATIAL_TREE_STRATEGY` | 3 | `SPATIAL` | 0x495047 | 0..2 |
| `SPEAKER_TYPE` | 12 | `SPEAKER_TYPE` | 0x844c72 | 0..12 |
| `SPEAK_GROUP_TYPE` | 2 | `SPEAK_GROUP_TYPE` | 0x844c72 | 0..1 |
| `SPEAK_ID` | 50 | `SPEAK_ID` | 0x844c72 | 0..49 |
| `SPEAK_PRIORITY` | 5 | `SPEAK_PRIORITY` | 0x844c72 | 0..4 |
| `SPEAK_SELECTOR_TYPE` | 2 | `SPEAK_SELECTOR_TYPE` | 0x844c72 | 0..1 |
| `SPECIFIC_MODEL` | 2 | `SPECIFIC_MODEL` | 0x809e94 | 0..1 |
| `STATE_CHANGE_OVERRIDE` | 2 | `STATE_CHANGE_OVERRIDE` | 0x809e94 | 0..1 |
| `STATE_OF_MIND` | 2 | `STATE_OF_MIND` | 0x5a38a6 | 0..1 |
| `STOP_CRITERIA` | 5 | `STOP_CRITERIA` | 0x5a38a6 | 0..8 |
| `SplitScreenType` | 4 | (none) | 0x79e8e7 | 0..3 |
| `TACTICAL_INFO` | 18 | `TACTICAL_INFO` | 0x5a38a6 | 0..65536 |
| `TARGET_LOCK` | 2 | `TARGET_LOCK` | 0x809e94 | 0..1 |
| `TESTMOVE` | 4 | (none) | 0x621c06 | 0..3 |
| `TOOLBAR_TYPES` | 5 | `TOOLBAR_TYPES` | 0x7c4f82 | 0..4 |
| `TRANSITION_TYPE` | 3 | (none) | 0x63ea3f | 1..3 |
| `TRIGGER_ACTION_CAMERA_ACTIONS` | 4 | `TRIGGER_ACTION_CAMERA_ACTION` | 0x850da9 | 0..3 |
| `TRIGGER_ACTION_CATEGORY_CHARACTER` | 35 | `TRIGGER_ACTION_CATEGORY_CHARACTER` | 0x865760 | 0..34 |
| `TRIGGER_ACTION_CATEGORY_PARTICLE` | 3 | `TRIGGER_ACTION_CATEGORY_PARTICLE` | 0x86a099 | 0..2 |
| `TRIGGER_ACTION_CATEGORY_SOUND` | 14 | `TRIGGER_ACTION_CATEGORY_SOUND` | 0x86a9fc | 0..13 |
| `TRIGGER_ACTION_CHAR_TARGETS` | 3 | `TRIGGER_ACTION_CHAR_TARGET` | 0x865760 | 1..3 |
| `TRIGGER_ACTION_DELAY` | 1 | `TRIGGER_ACTION_GENERAL` | 0x8676bd | 0..0 |
| `TRIGGER_ACTION_GENERAL` | 25 | `TRIGGER_ACTION_GENERAL` | 0x868c2e | 0..24 |
| `TRIGGER_ACTIVATOR` | 7 | `TRIGGER_ACTIVATOR` | 0x80c150 | 0..6 |
| `TRIGGER_ACTIVATOR_TYPE` | 6 | `TRIGGER_ACTIVATOR_TYPE` | 0x80c150 | 0..5 |
| `TRIGGER_CONDITION` | 3 | `TRIGGER_CONDITION` | 0x80c150 | 0..2 |
| `TRIGGER_CONDITION_CHARACTER_TYPE` | 2 | `TRIGGER_CONDITION_CHARACTER_TYPE` | 0x86c116 | 1..2 |
| `TRIGGER_CONDITION_TYPE` | 3 | `TRIGGER_CONDITION_TYPE` | 0x80c150 | 1..3 |
| `TUTORIAL_EVENT` | 11 | `TUTORIAL_EVENT` | 0x7c4f82 | 1..11 |
| `UNDERBOSS_PHASES` | 5 | (none) | 0x5a38a6 | 0..4 |
| `UNDERBOSS_STATES` | 3 | `UNDERBOSS_STATES` | 0x8a7b03 | 0..2 |
| `USER_PRIVILEGES` | 13 | `USER_PRIVILEGES` | 0x4dce04 | 0..12 |
| `USE_TYPES` | 17 | `USE_TYPE` | 0x80c150 | -1..15 |
| `VIEWPORT_TARGET` | 4 | `VIEWPORT_TARGET` | 0x850da9 | 0..3 |
| `VolumeCurve` | 4 | (none) | 0x4d9436 | 0..3 |
| `WARNINGS` | 13 | `WARNING` | 0x7c4f82 | 0..12 |
| `WEAPON_ANIMATION_TYPE` | 3 | `WEAPON_ANIMATION_TYPE` | 0x809e94 | 0..2 |
| `WEAPON_EFFECT_TYPES` | 4 | `WEAPON_EFFECT_TYPES` | 0x72de90 | 0..3 |
| `WEAPON_TYPE` | 2 | `WEAPON_TYPE` | 0x8bb4aa | 0..1 |
| `WEAPON_TYPES` | 3 | `WEAPON_TYPE` | 0x6726d6 | -1..1 |
| `WiiButton` | 11 | (none) | 0x4d3f5c | 0..10 |

`GAME_EVENTS` (57 names, ids 0-715) is the family behind `control=autodropdown|items=GAME_EVENTS`; id 614 carries two names
(`ACTIONLIST_SETTINGS_MENU_UPDATED`, `MENU_CLOSED`). `COLORS` registers each id under two names (`RED` and `COLOR_RED`, ...).
Where an id has several names `enums.json` joins them with ` | `; `meta[family].aliases` lists them.

## Class constants that are not in a family: `AIBrainNode`

Registered by 0x50574a in `AIBrainNode::RegisterMembers` 0x4865b9 (0x48660a..0x4866e2). They have no common
prefix, so they are not families of `engine_enums.json`; the toolkit keeps them as
`level_meta.AI_BRAIN_ENUMS`, keyed by the property each one is the value set of.

| property | values |
|---|---|
| `agentType` | 0 `IDLEAGENT`, 1 `GOTOAGENT`, 2 `FOLLOWAGENT`, 3 `WANDERAGENT`, 4 `FLEEAGENT`, 5 `HIDEAGENT` |
| `agentFaction` | 0 `ALLYFACTION`, 1 `ENEMYFACTION`, 2 `NEUTRALFACTION` |
| `pathFindingConstraint` | 0 `SHORTESTPATH`, 1 `STEALTH` |

Three more value sets the level export names (read from the pushes beside each name string):
`ENEMY` (0x5a3b12..0x5a3b9c: 0 `NO_STATE`, 1 `INACTIVE`, 2 `CHASING`, 3 `IDLING`, 4 `ATTACKING`,
5 `FOLLOW_PIVOT`, 6 `BRAINLESS_AUTOTARGET`, 7 `HANG_BACK`, 8 `RETURN_TO_COMBAT_ZONE`,
9 `TWILIGHT_LADY_BACK_FLIP`, 10 `STEP_BACK`), `STOP_CRITERIA` (0x5a3c99..0x5a3cd5: 0 `NONE`,
1 `LEADER_PRESENT`, 2 `TIMER`, 4 `ENEMY_IN_MELEE_RANGE`, 8 `STATE_NOT_RUNNING`), and for the save
file `SAVE_DEVICES` (0x775ad0..0x775b25: −1 `INVALID`, 0 `X360_PS3`, 1 `KEYBOARD_MOUSE`,
2 `GENERIC_PC_GAMEPAD`, 3 `LOGITECH_RUMBLEPAD_2`, 4 `SMARTJOY_PLUS_ADAPTOR`,
5 `TIGERGAME_PS_PS2_GAME_CONTROLLER_ADAPTER`) and `LOGICAL_INPUT_BUTTON` (`ProjectLib` registration
0x80d17a..0x80d3b8: −1 `NONE`, 0 `MENU_UP` … 39 `CAMERA_STICK_RIGHT`, 40 `SIZE`; 9, 10, 14–17, 19 and
29 are not registered).

## Side finding: the engine hash is not Python `upper()`

`FUN_00423ce8` (0x423ce8, the hash used for enum names and property keys) masks **every** byte with `& 0xDF` before shifting it
in — it does not upper-case letters only. Digits therefore hash as 0x11-0x19 (and `/`, `.`, `-` change too; `_` is unaffected).
`kh.py` / `kapow_props.kapow_hash` use `str.upper()`, which is wrong for any name containing a digit: of the key-table names
with a digit, 387 match a registered property hash under `& 0xDF` and 0 under `upper()`. This is why the sync markers showed up as
`key_ee2a40a0`: `m_nsupersynclocal1` hashes to 0xee2a40a0 with the engine's rule and 0xee2a40a4 with ours. Whether asset-path
hashes use the same function was not examined.
