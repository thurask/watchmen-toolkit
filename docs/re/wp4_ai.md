# WP4 - Enemy AI and navigation (Kynapse bridge)

Target `KapowMultiDEDRM.exe`. Evidence marks: **read** = traced in the lifted script / decompilation /
disassembly (handler and address given), **data** = value read from the binary fragments on the PC
(parsed with `tk160/wlib/kapow_fragment.py`), **inferred** = stated with the reason, **not established**.
Units: metres, seconds, radians for headings, speeds as a fraction 0..1 of full move speed.
Tables: `findings/wp4_ai_tables.json`. Scratch and tools: `work/wp4/` (section 11).

## 0. Result in one page

- **How an enemy thinks.** One script object per character, `Enemy` (root behaviour), runs
  `StateActive` 0x724071 every frame and re-evaluates every 0.0625-0.1625 s (interval drawn once per
  enemy). `Enemy.Evaluate` 0x72587d is a fixed priority list that returns one of ten `ENEMY` states;
  each state is a separate behaviour object that gets "focus". Inside the 8 m engagement zone the state
  is `ATTACKING`, whose behaviour `AttackEnemy` asks the global `CombatOrchestrator` for permission to
  attack and meanwhile runs one of two positioning sub-behaviours.
- **Who may attack.** The orchestrator keeps, per attacked character, a list of *current* attacks and a
  list of *waiting* requests. A request is granted when fewer than `_imaxnumberofattacks` (3) attacks
  are current, the newest current attack started at least `_nattackfrequency` (0.2 s) ago, and the
  requester is an "active attacker" (one of the first max+1 known enemies of the target that have it in
  front and within 4.5 m). An attack stays current for `_nattackcooldown` (2.0 s) after its animation
  started; each attacker also has its own cooldown `m_ntimebetweenattacks` (Dominatrix 1.8-3.0 s).
  There are **no ring slots**: positions come from pairwise ally repulsion in the two positioning
  behaviours.
- **How AI output reaches the character.** Exactly like player input: movement through
  `CharacterRoot.command_set_movement(moveHeading, faceHeading, speed)` 0x68e858 (the player controller
  calls the same command), actions through `command_attack_fast / attack_slow / perform_combo / dodge /
  block / step`.
- **Kynapse** (`Kaim`, statically linked) is used as: path finder + path follower + dynamic avoidance
  that outputs **one velocity vector per agent per frame** (`AIBrainNode.aiVelocity`), a sight service
  (who sees whom), an asynchronous reachability query, and AI-mesh queries (`TraceLine`,
  `IsInsideMesh`). It never moves a character. The script picks destinations (`SetGotoPos`), converts
  the velocity into a heading, chooses the speed itself and decides the facing.
- **Navigation data** is not in the block archives: `.aipathdata` (12 kB) is only the Kynapse world
  configuration ("KS BIG FILE"); the graph and AI mesh are in loose `data/levels/.../*.hpd` files
  (Bordello 204 kB) which the extractor does not touch.
- **Difficulty**: settled - nothing reads it (section 5.6).
- Corrections to `dominatrix_audit.md` are collected in section 9.

## 1. Architecture

### 1.1 Objects and ownership (read; data for the templates)

| object | class (register) | owner / where it comes from | holds |
|---|---|---|---|
| character | `CharacterRoot` (0x6c99ec) | level fragment (`Enemies.fragment`), template `CharacterRootTemplate_Enemy.fragment` | health, state of mind, `_npref*` movement request, target lock entity, breadcrumb, group id, orchestrator index |
| brain node | `CharacterAIBrain` on native `AIBrainNode` (0x659cc7 / 0x4865b9) | template | all Kynapse agent parameters and outputs (section 6) |
| perception | `Perception` (0x7e9d83) | template, child of the behaviour handler | known-enemy list (`EnemyStruct`), current target, tactical bits, reachability flag |
| behaviour handler | `BehaviorHandler` (0x61fbe6) | template | root behaviour list, active root behaviour, current AI definition `m_eaidef`, run speed |
| root behaviour | `Enemy` (0x732b65) | created by `CharacterRoot.InstantiateSubSystems` 0x67884e through `AILib.CreateRootBehavior` 0x5974f0 from `AiDef.m_smainbehavior` ("Enemy") | `_istate`, forced state, timers, hit history, nine sub-behaviours |
| definition | `EnemyDef` (parent `AiDef`; 0x7315dc / 0x5a3223) | `TNT/Production/Fragments/Enemy/<type>.fragment`, children of the `CharacterDef` | all tuning numbers; base / leader / phase variants |
| orchestrator | `CombatOrchestrator` (0x6fbb05) | one, `GameEssentials.fragment`; global `WorldLib.g_ecombatorchestrator` | per faction, per character `AiInfo`; attack budget |
| group | `CharacterGroup` (folder in the level), `GroupManager` | level | members, home turf / return point, all-dead action |
| LOD | `CharacterLodCtrl` (0x674767) | one, `GameEssentials.fragment` | which enemies are enabled: the 16 nearest (`_imaxenemycount` 16, enable distance 40 m; data) |
| AI world | `AIWorld` on native `AIWorldNode` | level `gameplay.fragment` | Kynapse world, AI mesh queries |

`Enemy.command_init` 0x7231b4 (read) creates `BehaviorIdle`, `BehaviorChase`, `AttackEnemy`, `hangback`,
`LeaderEnemy`, `ReturnToCombatZone`, `TwilightLadyBackflipBehavior` (type 35 only), `BehaviorStepBack`,
`FollowPivotBehavior`. `AttackEnemy.command_init` 0x5ff00b creates `CircleTargetEnemy02`,
`SecondaryAttackerEnemy`, `BehaviorEnforceSameHeight`. `BehaviorHandler.command_init` 0x6182b3 creates
`BehaviorBrainlessAutotarget`. `ChaseEnemy`, `BehaviorAttack`, `KynapseCharacter`, `kynapsetest01`,
`BehaviorMovementTest`, `AiSheetChanger`, `DoorPathObject`, `TriggerStaticPathObj` are registered but
never created by script and have no instance in the PC fragments (data + grep of the creation strings).

Classes covered in this pass (lifted lines): Enemy 4127, CombatOrchestrator 4600, AttackEnemy 2163,
CircleTargetEnemy02 2603, SecondaryAttackerEnemy 2397, Perception 2745, BehaviorHandler 1651,
BehaviorChase 1068, hangback 1437, AILib 2323 (12 of 35 methods), AiDef 504, EnemyDef 2257 (getters and
`initialize_local`), CharacterAIBrain 1028, AIWorld 683, BehaviorBrainlessAutotarget 844,
KynapseStaticPathObjSceneClimbUp 1062 (two handlers), KynapseArtificialDoor 110, PathBlocker 165,
visionblocker 128, KynapseCharacter 410, AiSheetChanger 154, CombatOrchestratorParameters 84 - read.
BehaviorStepBack 946, BehaviorEnforceSameHeight 830, LeaderEnemy 1019, ReturnToCombatZone 2159,
FollowPivotBehavior 1834, BehaviorIdle 672, Partner 2390 (Evaluate, init), CharacterLodCtrl 1168 -
summarised from call lists and constants (marked where used). Not read: CombatPartner 2278,
FollowPartner 4244, CombatHelpPartner, AttackKillTargetPartner, CrowdControlPartner,
twilightladybackflipbehavior 1801, Underboss* (no Underboss definition exists in the Part 2 data).
Engine: 22 functions of `ai.glue` (addresses in section 6).

### 1.2 Definitions and their switching (read + data)

- `EnemyDef.initialize_local` 0x72175a: the `BASE_DEF` registers itself in
  `AILib.g_echaractertypesdeflist[type]` (`AILib.RegisterAiDef` 0x5988c5) and remembers the sibling with
  `m_ideftype` 1 as `_eleaderdef`.
- Leader switch: `Enemy.StateActive` asks `CombatOrchestrator.command_leader_present(faction)` 0x6e5ac5 at
  every evaluation and calls `BehaviorHandler.command_switch_to_leader_def` 0x6187ae /
  `command_switch_to_base_def` 0x618801. A leader is an enemy whose definition has `m_tisleader`; its
  `LeaderEnemy` behaviour registers it (`BroadCast_LeaderPresent` 0x76edf1). In the PC data
  `m_tisleader` is false in all 18 definitions, so the leader definitions of the three Thug types are
  never selected by this path (data).
- Phase switch: trigger action `SET_AI_DEF_PHASE` (19) in `TriggerActionCharacter.ActionExecute` 0x85b858
  finds the definition with the requested `m_ideftype` and calls
  `BehaviorHandler.command_set_ai_parameter_sheet` 0x618084, which carries the forced state over,
  de/re-activates the root behaviour and sends `command_ai_def_changed`. Used 16 times in the three
  `Enemies.fragment` files (data).
- `AiSheetChanger` (with `m_nreactiontime`) is the only place a "reaction time" exists; it has no
  instance in the data. There is no perception or decision delay other than the evaluation interval.
- Speeds: `AiDef.command_get_idle/walk/full_speed` return `GlobalAiParameters` 0.0 / 0.5 / 1.0;
  `BehaviorHandler.command_get_run_speed` 0x618fef: for brains with `agentFaction == 1` a per-enemy
  constant drawn once, `min + (max-min)*rand` of `m_nminrunspeed..m_nmaxrunspeed` (Dominatrix 0.8-1.0),
  otherwise full speed.

### 1.3 Update cadence (read)

| what | cadence | where |
|---|---|---|
| `Enemy.StateActive` loop | every frame (`WAIT_FRAME`), first after a 1.0 s wait | 0x724071 |
| `Enemy.Evaluate` | every `_nevaluationinterval` = 0.0625 + rand*0.1 s (doubles 0xa1ac30, 0x9e9628), or next frame after `command_force_update` | `ShouldUpdate` 0x715233, `command_init` 0x7231b4 |
| sub-behaviour states | every frame | each `StateActive` |
| `Perception.StateActive` | every frame while `AnimationCtrl.m_tupdated`; first run after rand*`_ntimebetweenposreachablequeries` + 0.1 s | 0x7dc1f5 |
| tactical bits | every `m_ntacticalinformationupdatetime` (enemy 0.5 s, heroes 0.01 s; data) and on demand | 0x7d730a, 0x7dd352 |
| orchestrator | every frame | 0x6e8231 |
| Kynapse world | every frame, `Update(dt)` with the frame time | 0x529433 -> 0x9258c0 |
| only the 16 nearest enemies run at all | `CharacterLodCtrl` | audit c2 |

Random numbers all come from the script builtin `rand_number` / `rand_integer` (0x47b03e family); no
seed handling was looked at (**not established**: seed and generator).

## 2. `Enemy.StateActive` and `Enemy.Evaluate`

### 2.1 Per-frame body of `StateActive` 0x724071 (read)

1. Twilight Lady punish block (`_tdotwilightpunish`), not relevant for other types.
2. If `ShouldUpdate()`:
   - alive: leader definition switch (1.2).
   - Target: the current target is kept unless `AILib.ShouldAcquireNewTarget(target)` 0x598886 (no target,
     placeholder, dead, disabled or invisible) or `CombatOrchestrator.command_change_target` 0x6e430e
     says so **and** `_ntargetlockendtime` has passed. Then `command_acquire_target` 0x6e3e83 and
     `_ntargetlockendtime = now + def.m_ntargetlocktime` (4.0 s).
   - Alert propagation and speech (section 5).
   - dead: `command_remove_is_attacking`.
3. Twilight-Lady attacker lists are cleared when not blocking.
4. `Evaluate` is called as a state (it can wait); if the wanted state differs from `_istate`, or the
   current behaviour reports `command_is_behavior_running == false`, `SetState` 0x715285 sends
   `command_lost_focus` to the old behaviour and `command_got_focus` to the new one. Entering `ATTACKING`
   for the first time fires speak `ENGAGEMENT` (5) if the target is seen.
5. Leaving `StateActive` (root behaviour loses focus: death, deactivation, pause): `SetState(INACTIVE)`,
   forced state stopped.

### 2.2 `Evaluate` 0x72587d - rules in priority order (read)

| # | condition | result |
|---|---|---|
| 1 | `m_nhealth <= 0` | `INACTIVE` |
| 2 | off the AI mesh for more than 2.0 s (`m_nbreadcrumbtimer`), `AGGRESSIVE` | breadcrumb loop: state `IDLING`, each frame `set_movement(heading to m_vbreadcrumbposition, facing the target if within engagement distance, 1.0)`; after 10.0 s `command_uberkill` + 100000 damage. Constants 0xc3cc78, 0x9e5c60, 0x9eba80 |
| 3 | `AILib.CheckForcedState` 0x59ca06 | the forced state (set by `command_set_forced_state(state, stopCriteria, time)` 0x722bfa; criteria bits `STOP_CRITERIA`: 1 leader gone, 2 timer, 4 target within `m_nattackdistance`, 8 forced behaviour not running). Check order: first call after the request always true; then 1 `LEADER_PRESENT` (ends when `CombatOrchestrator.command_leader_present` is false), 2 `TIMER` (ends when stop time < now), 4 `ENEMY_IN_MELEE_RANGE`, 8 `STATE_NOT_RUNNING` (ends when not prone and the forced behaviour reports not running). `command_set_forced_state` also sends `command_force_update`, so the first evaluation is on the next frame. |
| 4 | target and (`_nstepbacktimer > now` or step-back behaviour running) | `STEP_BACK` |
| 5 | `PASSIVE` and outside home turf | `RETURN_TO_COMBAT_ZONE` |
| 6 | `AGGRESSIVE`, outside home turf (or already returning): return behaviour running with preconditions, or `m_nforcereturntohometurftimer` (now + 10 s at `command_leaving_combat_zone` 0x722f9f) expired | `RETURN_TO_COMBAT_ZONE` |
| 7 | no target / target dead | `IDLING` |
| 8 | outside home turf and target farther than 4.5 m (`m_nmeleemaxdistance`) | `RETURN_TO_COMBAT_ZONE` |
| 9 | `Perception.m_tiskynapsetargetreachable == 0` | wait a frame; still unreachable: `command_force_is_pos_reachable(target breadcrumb)`, wait 2.0 s for the answer; for a player target also `AIWorld.TraceLine` from the breadcrumb to the target (reachable if the trace ends within entityRadius + 10 m of it); unreachable -> `IDLING` |
| 10 | target is a placeholder | `IDLING` |
| 11 | hang back: `def.m_thashangback` and ((behaviour running and `_nhangbacktime` not expired) or (`health < m_nmaxhealth * m_nhangbackhealthprocent / 100` and the target's own target is not me)) and (attackers of the target >= 2 or `m_nhangbackifalone`) | `_nhangbacktime = now + rand[min,max]` when expired; `HANG_BACK` |
| 12 | `dist < orchestrator.m_nengagementdist` (8 m) and no AI-mesh border between the two breadcrumb positions (`AIWorld` 0x59db68: `TraceLine(a, b, 0.01)` stops farther than `m_nentityradiussqr` from b) | `ATTACKING` |
| 13 | `dist <= 2 x` engagement distance, already `ATTACKING`, and not allowed to start moving (`m_imovingcharacterslastframe >= m_irunningcharactersclamp` (5) and own speed 0) | stay `ATTACKING` |
| 14 | otherwise | `CHASING` |

Rule 12 uses the orchestrator's engagement distance, not the definition's attack distance (the audit said
attack distance; `Entity_GetScriptPropertyByIndex(orchestrator, 2)` = `m_nengagementdist`, lines 3743-3757
of `Enemy.c`).

### 2.3 Being attacked (read)

- **At attack start**: `CombatOrchestrator.command_attack_animation_stated` 0x6e6495 (called from
  `CharacterRootLogic` x3 and `CharacterPhysics`) sends `BehaviorHandler.command_react_to_attack(attacker)`
  to the *target*. For players this goes to `PlayerCtrl.command_you_are_attacked`; for enemies to
  `Enemy.command_react_to_attack` 0x721958: the Deterministic Reaction System described in the audit
  (c3), confirmed. Gate details settled here: she force-locks the target onto the attacker, ignores
  unblockable attacks, and does nothing when `Perception.command_tactical_query(attacker, 0x400)` is
  true - 0x400 is `TACTICAL_INFO.PLACEMENT_REAR`, i.e. **attacks from behind (more than 90 degrees off
  her facing) are never blocked, dodged or countered**. The first reaction also sets a `PASSIVE` enemy
  `AGGRESSIVE`. No random number is involved; `m_nprobofreactatt`, `m_nprobofdodge`, `m_nprobofblock`,
  `m_nprobofcounteratt` have no reader outside `EnemyDef`'s own editor-time `Justify*` handlers
  (measured: a displacement scan of the whole code section finds no reader outside `Justify*` /
  `FilterExposedProperties`; `enemydef_consumers` in `wp4_ai_tables.json` is superseded by it).
  `m_nprobblockthrow` / `m_nprobdodgethrow` are read in `CharacterRootLogic.FireAttackBasedOnAttackID`
  0x68d870 (throw defence; combat-resolution territory).
- **Just before impact**: `CharacterRoot.command_hit_soon` 0x6903ea -> `BehaviorHandler.command_when_attacked`
  0x618aac -> state `StateBrainLessAutoTarget` 0x615279: all behaviour entities are disabled
  (`command_set_pause(true)`), `BehaviorBrainlessAutotarget` turns the character to face the attacker for
  at least 0.2 s and, for ordinary enemies, until the main animation state's play position reaches 0.9
  (0x616a74); then behaviours resume.
- `command_hit_by` 0x722bbb clears the hit history when a block/dodge was broken
  (`m_tclearifblockdodgeisbroken`).
- `SetAggressive` 0x693236 (after damage) sets the whole `CharacterGroup` `AGGRESSIVE`.
- `command_force_step_back` 0x724033 (from `CombatOrchestrator.command_character_in_repel_attacters_animation`
  and an animation event): 1.0 s of `STEP_BACK`.

## 3. The behaviours

### 3.1 `BehaviorChase` 0x617146 (read) - state `CHASING`

Brain `GOTO` to the target's breadcrumb (`m_vbreadcrumbposition`, plus the correction vector while the
target is off-mesh), i.e. the last position where the target stood on the AI mesh. With a path
(`CharacterAIBrain.command_has_path` 0x6490bb: `HasPath` and |aiVelocity| > 0.01): heading and facing =
direction of `aiVelocity`; speed = run speed while farther than the engagement distance and the attack
distance, walk speed (0.5) with target lock inside the engagement distance. Without a path: stand facing
the target and every 5 s (first after 10 s) set agent type 3 for one frame ("wander agent hack",
`_nwanderagenthacktimer`) to force a re-plan. `m_nchasedist` is not used here (only by the unused
`ChaseEnemy` and by `ReturnToCombatZone`).

### 3.2 `AttackEnemy` 0x5ff3d6 (read) - state `ATTACKING`

Per frame, with d = distance to the target:

1. No target -> leave. `BehaviorEnforceSameHeight` pre-empts when she stands between `stepMax` (0.3 m) and
   1.5 m above the target (0x617b.. `command_check_preconditions`): she walks to the target's position.
2. While `_nstepbacktimer` runs: `CharacterRoot.command_step(target)` and nothing else.
3. **Request**: if `d < m_nattackdistance + 0.1`, no request pending, her orchestrator cooldown stamp has
   passed and `AILib.AttackPathClear` 0x59ce06 (a physics capsule cast of her own capsule towards the
   target hits nothing but the target or dynamic bodies): `CombatOrchestrator.command_request_attack`
   0x6e5ca7, and the combo decision is rolled now: `_tdocombo = rand < m_nprobofcomboatt` (0.5).
4. First time within 4.5 m: speak `MELEE` (6).
5. **Sub-behaviour**: `Perception.readonly_tisactiveattackerinthiscombat` (set by the orchestrator) selects
   `CircleTargetEnemy02` (active) or `SecondaryAttackerEnemy` (not active). While an attack animation
   plays the sub-behaviour is stopped and she just faces the target.
6. A pending request is re-validated every `_ncheckforclearlineofattackfrequency`; if the line is blocked
   or the orchestrator dropped it, `command_remove_attack_request` (which also restarts her cooldown).
7. **Punish zone**: while the target is closer than `m_npunishzone` (1.0 m; 1.5 in phase 1) and she is
   neither stunned nor prone, a 0.5 s timer runs down; at zero, if the orchestrator is not paused and
   `target.command_may_be_attacked`, she attacks **without a grant** (`command_may_attack` on herself),
   the timer becomes 1.5 s and a 1.0 s step-back follows.

`command_may_attack` 0x600246 (the grant): needs `AILib.MayAttack` 0x59c402 (target valid and within
`m_nattackdistance`), the step-back timer over and a successful `command_lock_target`. Then

- combo if `_tdocombo` and not already attacking: `FindUsableCombo` 0x600730 builds a list in which each
  of the nine `m_ecomboattackN` appears `m_ifreqofcomboattackN` times, but only if every item of the combo
  fits the weapon she holds now (animation enum `WEAPON_ANIMATION_TYPE`; item ids 1/4 unarmed only, 2/5
  one-handed only, 3/6 two-handed only; `TryAddComboToList` 0x5eee3a) and picks uniformly
  (`rand_integer`). `command_prep_combo` + `CharacterRoot.command_perform_combo(combo, 5 s x items)`.
- otherwise one roll: `rand < m_nproboffastatt` -> `command_attack_fast`, else `command_attack_slow`
  (`m_nprobofslowatt` is not read by this path).
- `PrepAttack` 0x6252e3 sets `m_enextattacktarget` and calls `CombatOrchestrator.command_register_attack`.
- speak `MELEE_ON_TARGET_A` (24) / `_B` (25) for Rorschach / Nite Owl; `_npunishtimer = 0.5`.

`command_taunt` 0x60066c (sent by the orchestrator) speaks `TAUNT` (1).

### 3.3 `CircleTargetEnemy02` 0x6dd04e (read; `IWhantToMove` checked in disassembly 0x6df3e2-0x6df654)

Runs only while the target is within 4.5 m (`command_check_preconditions` 0x6dcdb4). Target lock is on.

- `IWhantToMove` 0x6df2a0: yes if `d < m_nminimumdistance` (2.0); no if the orchestrator's moving count
  has reached the clamp (5); yes if `d > m_nattackdistance`; inside the band [2.0, 4.0]: yes while the
  brain is not in `GOTO` mode, otherwise only if another attacker of the same target stands inside its
  `m_ncombatinfluencesphere` (3.0 m) of her, and then once per random wait of
  `m_nwaittomovetime_min..max` (1-5 s).
- `SetMovementPosition` 0x6ddbc2: too far and the target may be attacked -> a point `attackdist - 0.1`
  from the target on the line to it; in the band -> a point `attackdist - 0.2` m to her **left or right**
  (local X of the visual), the side re-decided every 2 s: allies in the front half-plane vote with weight
  `1 - dist/influenceSphere` for their side and she goes to the lighter side (no ally: 50/50); too close
  -> a point `attackdist - 0.2` m straight away from the target.
- Movement: `SetAgentType(GOTO)`, `SetGotoPos`; next frame the brain's `aiVelocity` is turned into a
  heading by `ClampDirection` 0x6deb7e: less than 10 degrees off the facing -> straight forward; up to
  150 degrees -> pure left or right; more -> straight away from the target. Facing is always the target.
  Speed ramps to the run speed with `m_nallowedspeedchange` (0.5 per second) and is sent with
  `command_set_movement(heading, facing, speed)`.
- No path for 1 s (velocity below 0.01 after having moved, or target unreachable): agent type 3 for a
  frame, then `GOTO` again.
- Consequence (read, arithmetic mine): in the band `IWhantToMove` is true for only two consecutive frames
  per wait period, and with a 0.5/s ramp the speed stays far below the 0.1 threshold, so the "circle"
  step inside the band is practically a stand-still with a re-aim; real movement happens when she is
  outside the band (approach, back off).

### 3.4 `SecondaryAttackerEnemy` 0x815362 (read; `DetermineForwardHeading` read, 0x8169e9)

For enemies that are in the engagement zone but not active attackers. Brain `GOTO` to an own pivot.

| distance to target | behaviour |
|---|---|
| >= 8 m | stand facing the target |
| 4.5 - 8 m | if the moving clamp is reached and she stands: stand. Else `DetermineForwardHeading` 0x8169e9 (read, 0x8169e9). Allies within 90° of the target direction get weight 1 − distance / `m_ncombatinfluencesphere` and are sorted by the sign of `a.x·v.z − v.x·a.z` (≥ 0: side R, the +X side when facing +Z; < 0: side L). If neither side weight is positive she heads straight for the target. Otherwise the side is R when R ≤ L, else L. The aim point is the widest-angle ally on that side plus (side weight) × her local +X, or, when that side has no ally, the target plus 3.0 m × local +X for R and × local −X for L. With an ally the offset is along +X for both sides, so on L it points back towards the middle. She refuses when `m_nmaxturndeg` ≤ 2 × the angle between that heading and the target direction. Then: pivot 1 m ahead on that heading, heading from `aiVelocity`, run speed. Target lock only inside (8+4.5)/2 = 6.25 m |
| attack distance - 4.5 m | stand, target lock, speak `TAUNT` (1) |
| < attack distance | back away at walk speed towards a pivot `engagement distance` away from the target |

`SetMovement` 0x812cda limits both headings to 200 degrees/s, and forces idle speed when the target is
unreachable or the parent `AttackEnemy.command_may_move` is false (`command_dont_move_while_animation_runs`).

### 3.5 The rest

- `hangback` 0x75e618 (read): `CharacterRoot.command_is_in_hang_back_mode(true)`, brain `FOLLOW` the target
  with follow distance `m_nhangbackdistance_min`, speak `HELP_COMMUNICATE_TO_GROUP` (17). Closer than min
  (6 m): walk backwards facing the target; between min and max (6-10 m): stand, and **health rises by
  10 per second** while below `m_nhangbackhealthprocent x m_nmaxhealth` (the product without the /100
  that `Evaluate` uses - 3000 for her, so the cap never bites; read at lines 807 and 1311); beyond max:
  approach along `aiVelocity` at run speed.
- `BehaviorStepBack` 0x61abb3 (summarised): `command_step(target)` repeatedly for `m_nstepbacktime`
  (0.5 s default, 1.0 forced, 2.0 as a forced state), then `command_force_stop_now` and an optional
  wait; aborted by `command_react_to_attack`.
- `BehaviorIdle` 0x614f01: agent type `IDLE`, `AILib.StopMove`.
- `BehaviorEnforceSameHeight` 0x617c70 (summarised): walk (0.5) by `GOTO` to the target until level.
- `ReturnToCombatZone` (summarised): `StopAndTaunt` 0x7ff5f5 near the zone border when the target is
  within `m_ntauntdistance`, `RunBackToZone` 0x8006c9 by `GOTO` to the group's return point;
  `m_nchasedist` (3.0) is its distance threshold. Driven by trigger actions `LEAVING_/ENTERING_COMBAT_ZONE`
  (22 + 22 in the data) through `CharacterGroup.command_leaving_zone`.
- `FollowPivotBehavior` 0x73a1af (summarised): forced state 5 from trigger action `FOLLOW_PIVOT` (174 in
  the data) and from `CharacterRoot.EnableSubSystems`; `GOTO` to the pivot, run or walk, uses
  `GetCurrentPath`; stop criteria 8, or 12 when not "always go to" (so a target inside the attack
  distance ends it).
- `LeaderEnemy` 0x773029 (summarised): reinforcement call / beckoning timers; unused with the PC data.
- `twilightladybackflipbehavior.StateActive` 0x88130b. Requested by trigger action 28 with (state 9,
  criteria 10, 0.05 s): the forced state lasts until the first evaluation later than 0.05 s after the
  request, at most 0.05 + the enemy's evaluation interval (0.0625–0.1625 s, drawn once in
  `Enemy.command_init`) = 0.2125 s; `command_is_behavior_running` is true in `StateActive` (0x7f09ac), so `STATE_NOT_RUNNING` does not end it. Target within 4.0 m: an
  area attack. Otherwise she flips towards a retreat point (clamped to 7.0 m), firing action 34
  `FLIP_MOVE` each frame while the squared distance is above 4.0, i.e. until 2 m, or for 3.0 s; the
  3.0 s limit cannot be reached under this trigger. The `BackFlip` state (Enemy04; loop, 0.689 s per cycle, entered at 0.57)
  has two transitions of its own (measured): to `MovementGroup (Combat)` on `SPEED < 0.1` and
  `PLAY_POS` in [0.35; 0.75[ (ease 0.23 s), and to `OneFrameActionGroup` on `ACTION
  ONE_FRAME_ACTION` and `PLAY_POS` in [0.35; 0.55[. Its group holds `TARGET_LOCK` as a kept
  criterion. At the natural end the behaviour sends speed 0; when the forced state ends first
  (0x8166ca) it sends nothing. (The level export gives the request per action node:
  `graph.nodes[].forced_state`.)
- Flee sets its speed on the hide agent (0x48bc8c); vehicle entities are never created (0x483a55);
  the stealth constraint exists (0x48b317) but a loaded `pathFindingConstraint` is discarded.

### 3.6 Script and engine defects that change behaviour (read)

- (a) `AILib.IsAFacingB` 0x5a0998 passes a direction to the point conversion `ConvertFromWorldSpace`
  (call at 0x5a0b17), so the result is forward·(direction − A's world position) > 0; it is a facing
  test only near the world origin. Used by `AttackKillTargetPartner` and `CrowdControlPartner`.
- (b) `ReturnToCombatZone.StopAndTaunt` 0x7ff5f5: the side-step heading converts a local constant
  with `ConvertDirectionFromWorldSpace` and then subtracts the character's world position
  (0x7fff0e–0x7fffe3); far from the origin it is the heading towards the origin. It is used only
  after the taunt time, when the brain's velocity is non-zero.
- (c) The AI sight ray cast 0x48b44e loads the node of hit record 0 once and repeats the same test
  for every hit (0x48b4ee–0x48b512), so only the first reported hit decides.
- (d) `SecondaryAttackerEnemy.DetermineForwardHeading`: the with-ally offset has the same sign on
  both sides (0x8173cc).

Agent base type (`AILib.DeriveBaseAgentBaseType` 0x597696, read from code; a name fragment counts
only when found at an index of 1 or more). `command_set_type` 0x598105 stores it in
`m_iagentbasetype`; `BehaviorHandler.command_set_ai_parameter_sheet` 0x6180e6 ignores a definition
of another base type:

| Character type | Base type |
|---|---|
| 0 or 1 | 1 |
| 25 | 6 |
| name with `_BIG` | 4 |
| name with `_FAST` | 3 |
| name with `_LEADER` | 5 |
| any other | 2 |

## 4. The combat orchestrator (read: 0x6e8231 and the commands named)

Data model: `_combatentdb[faction][index]` = `AiInfo` (fields in the JSON). Faction is the brain's
`agentFaction` (0 ally = the two heroes, 1 enemy, 2 neutral); `CharacterRoot.m_icombatorchestratorindex`
is the index. `register_self` 0x6e2f58 at `EnableSubSystems`, `unregister_self` 0x6e3181 at disable/death.

**Per frame, for every faction-0 character T (a hero, human or AI):**

1. prune `currentAttacks`: normal attack older than `_nattackcooldown` since its animation start; combo
   older than 30 s; placeholder attackers.
2. mark active attackers: walk T's known-enemy list (sorted nearest first by `Perception`); for the
   first `_imaxnumberofattacks + 1` entries whose target is T, the enemy is active if its tactical bits
   about T contain 0x202 (`PLACEMENT_FRONT | WITHIN_MELEE_RANGE`) and the height difference is below
   0.8 m; all later ones are not active.
3. idle player: if T neither attacks nor is stunned/prone nor has a recent current attack for longer than
   `_nidletime` (0.1 s), the first ready active attacker gets its cooldown stamp cleared (-1): it may
   request at once.
4. T stunned or prone: the behaviour of the first current (else first waiting) attack gets
   `command_taunt`.
5. T's animation is immune to attacks: every current attacker gets `command_break_off_attack`, lists
   cleared.
6. **Grant**: if `count(currentAttacks) < _imaxnumberofattacks` (and max != 0 - `command_pause_attack`
   0x6e2f1b sets it to 0 during camera tours) and (no current attack or the first one started at least
   `_nattackfrequency` ago) and no waiting entry was granted within the last `_nattackfrequency`: the
   first waiting entry whose attacker is alive and active gets `nGrantedRequestStartTime = now` and its
   behaviour `command_may_attack`; the waiting list is bubble-sorted by grant time (`Sort` 0x6e9e92).
   `_nattackwaittime` is never written (0), so a granted entry that did not start is simply granted again.
7. T dead: both lists cleared.

Then, for enemy-faction characters as targets (attacked by the heroes), only the cooldown pruning runs.

When the attack animation really starts (`command_attack_animation_stated` 0x6e6495): the attacker's
personal stamp `nAttackCoolDownTimeStamp = now + def.command_get_time_between_attacks()`
(`min + (max-min)*rand`, 0x5971e4), the waiting entry moves to `currentAttacks` with
`nAnimationStartTime = now` (or `AddCurrentAttack` 0x6ea091), and the target's reaction is triggered
(2.3). Animation states with special handling `RESEND_PUNCH_WHEN_IN_RANGE` are ignored.

**Constants** (data; `CombatOrchestrator` instance in `GameEssentials.fragment`): engagement 8.0 m, running
clamp 5, cooldown 2.0 s, max attacks 3, frequency 0.2 s, idle 0.1 s. Presets
`combatorchestratordefaults.fragment` "Level 001".."Level 006" (engagement 8/8/12/12/8/8, cooldown
4/4/3/2/2/2, max 2/2/3/3/3/4, frequency 0.5/0.5/0.2/0.2/0.2/0.2, idle 1.5/1.0/0.75/0.5/0.1/0.1) are
applied by `CombatOrchestratorParameters.command_trig` 0x6d9128 -> `command_set_parameters` 0x6e2e73 (a
trigger action or "trig from start"); which levels fire which preset was not traced.

**Targets** (read):

- `command_choose_target` 0x6e3f26: first valid known enemy, replaced by a later one that has fewer than
  (attackers of the current best - 2) attackers (`ShouldSwitchTarget` 0x6da85a).
- `LockTarget` 0x6e9541: the target must be in the attacker's known-enemy list and of another faction; a
  change of target is refused for 1.0 s after the last lock (0.5 s for forced locks); it moves combo
  bookkeeping (`TransferCombo`) and the `isAttackedBy` entry and writes
  `Perception.readonly_ecurrenttarget`.
- `command_change_target` 0x6e430e says "re-acquire" when: no/placeholder target; target farther than the
  engagement distance; not an active attacker and farther than `m_nminimumdistance`; active, target in
  front, and another known enemy in front is nearer; or `ShouldSwitchTarget_entity` 0x6e9c0b - which
  passes its two arguments swapped (0x6e9cad-0x6e9cb9), so it fires when the *current* target has fewer
  than (other - 2) attackers; `choose_target` then picks by the correct rule, so the effect is only an
  extra re-acquire.
- In co-op this spreads enemies over the two heroes with a hysteresis of two; in single player the AI
  partner is the second faction-0 character and is treated exactly like a hero.
- Movement budget: `CharacterRoot.StateActive` (line 10617) counts moving characters per frame; the clamp
  5 is consulted by `Evaluate`, `CircleTargetEnemy02`, `SecondaryAttackerEnemy`, `ReturnToCombatZone`.
- `command_is_in_combat` 0x6e5682 (used by HUD/music/camera/path objects): an `AGGRESSIVE` enemy is always
  in combat; a hero when it knows an aggressive enemy within 1.5 m of height, is in a damage animation or
  has a target lock.

## 5. Perception and awareness

### 5.1 Sight (read)

- `Perception.init` 0x7dc14f sets the brain's visibility half angle to **180 degrees** (the template's 90
  is overwritten), `Enemy.command_init` sets the visibility distance to `m_nvisualrange` (34 m for all 18
  definitions); eye position (0,1,0) (data). So enemies see all around, 34 m, subject to Kynapse's line
  of sight.
- Each frame `AddNewKnownEnemies` 0x7dcc88 asks `AIBrainNode.GetSeenAIEnemies` (engine 0x48460d: all Kynapse
  entities of another, non-neutral faction for which the Kaim sight info says "seen"), validates them
  (`ValidTarget` 0x7d7e25: seen and alive and enabled, or remembered for `_nremembertargettime`) and keeps
  an `EnemyStruct` (last seen time, position, "sees me", tactical bits) per enemy, sorted nearest first.
- There is no hearing. The only other inputs are: `m_forceperceptedcharacter` (set by a group mate, 5.2),
  being hit (target force-lock in `command_hit_soon` and `react_to_attack`), and scripted activation.
- Sight = range and cone (0x955970), then visibility. Visibility is a per-pair result held in a
  time-stamped cache (0x48b785 → 0x489135, 0x48a2c1, 0x48a1b7); a stale entry is recomputed,
  time-sliced, by `Kaim::CVisibilityEntityInfo` 0x943be0, which calls the engine ray cast 0x48b44e
  between the two eye points (refresh periods not read). The ray reports every shape whose pivot-sheet
  `collisionMask` shares a bit with `AIWorldNode.collisionMask` (8192 `KYNAPSE` in three and 8193 in
  two of the five PC Part 2 `AIWorld` nodes that store one; `nodeCollisionMask` 0). Sight is blocked
  when the first reported hit belongs to a `CollisionNode` with `physicsType` 1 (RIGIDBODY). Sheets that share no bit with the level's mask are transparent to AI: `Character_Enemy` (258) and `Trigger` (16) everywhere, and `SolidCollisionAiCanSeeThrough*` (4095 / 4079 / 4075) where the mask is 8192. Where the mask is 8193 (NightClub, PlayerVsPlayer) those three sheets share bit 0 and are reported: 5 NightClub volumes on `SolidCollisionAiCanSeeThrough` with `physicsType` 1 export `blocks: true` (measured); Bordello's 8 export `false`. The 28 `visionblocker` boxes of PC Part 2 all store `physicsType` 1 and the
  `collisionprimitives` `default` sheet (mask 9771) and so block at run time (measured: the "47 in
  the data" counted earlier are 28 property records plus 19 creation records of the same nodes). `includeInAIVisibilityCache` (`CollisionNode`+0x189) only feeds the `Get*AIObjects`
  natives, which no script calls: in 0x49ca65 the entity type is always `DynamicObstacle` and only
  kinematic or dynamic nodes get one; its reader is 0x4a2b9f. There is no hearing:
  `Kaim::CEntityHearingAcuteness` is never instantiated (class object 0xe4c698 has no reference
  outside its own registration).
- Tactical bits (`UpdateTacticalInfoForEnemy` 0x7dd352): attacking me; within/outside melee range (4.5 m);
  within attack range (`m_nattackdistance`); stunned / prone; placement front/rear (90 degrees to my
  facing) and left/right; current target; low health (< 40); primary target.

### 5.2 Alert propagation and speech (read, `StateActive` lines 2639-2936)

- On acquiring a target, every living member of her `CharacterGroup` whose known-enemy list is empty gets
  `m_forceperceptedcharacter = target` if she can see the target: the whole group wakes up.
- Damage makes the whole group `AGGRESSIVE` (`SetAggressive`).
- `Perception` reports the first aggressive enemy to `BehaviorHandler.command_new_enemy_group_spotted`
  (used by the partner).
- Speech (ids of `SPEAK_ID`, through `SpeakCtrl.command_add_speak_event_based_on_enum`; only when
  `AGGRESSIVE`): group call `TARGET_SPOTTED_COMMUNICATE_TO_GROUP` (4), with probability 0.6 the
  hero-specific 18 / 19, once, when no group member is within the engagement distance of the target and
  the group has more than one member; first-sight line `TAUNT_TARGET_A/B_SPOTTED` (20 / 21) or
  `TARGET_SPOTTED` (3), once, when she spotted the target herself and faces it within 25 degrees
  (`command_is_facing_speak_target` 0x618854); `ENGAGEMENT` (5) on first `ATTACKING`; `MELEE` (6);
  `MELEE_ON_TARGET_A/B` (24 / 25) per attack; `TAUNT` (1); `HELP_COMMUNICATE_TO_GROUP` (17) on hang back;
  `TAUNT_GET_UP_TO_TARGET_A/B` (22 / 23) in `command_got_up` 0x722e07.

### 5.3 Activation (read + data)

Enemies are placed with `_tstartactivated` false (461 of 476 records). Trigger volumes fire
`TriggerActionCharacter` actions: `ACTIVATE` (121) -> `CharacterRoot.command_character_activate` 0x68f1e1 ->
`CharacterLodCtrl.command_register_enemy`; the LOD controller enables the nearest 16 ->
`EnableSubSystems` 0x696fac -> orchestrator registration and `BehaviorHandler.command_set_root_behavior(0)`
-> `Enemy.command_got_focus` -> `StateActive`. `SET_AI_STATE` (63), `FOLLOW_PIVOT` (174), `DEACTIVATE`
(140), `PLAY_SPECIFIC_ANIMATION` (54), `SET_AI_DEF_PHASE` (16), `REQUEST_FORCED_STATE` (4) do the staging.
(Counts are action records in the three `Enemies.fragment` files and include the parser's duplicate
rows; ratios are meaningful, absolute numbers are not.)

### 5.6 Global difficulty - settled (read)

`PREFERENCES_GAMEDIFFICULTY` (NORMAL 0, EASY 1, HARD 2, ERROR 3) is only the return type of the native
`PlatformNode.getdiffucultysettings` 0x4cd780 (reads the platform gamer profile, 0x4dfd58). That native
has **no caller**: no direct call in the exe (0 `E8` references), its name hash 0x7d522926 occurs nowhere
as an immediate, and no lifted script mentions it. Enemy strength is therefore set only by data and
triggers: definition phases, orchestrator presets, `SET_INCOMING_DAMAGE_FACTOR`, `SET_MIN_HEALTH`,
`DAMAGE_MODE`.

## 6. Movement and the Kynapse boundary

### 6.1 What the game asks of Kynapse (read)

Per agent the game writes the `AIBrainNode` properties and reads back the outputs; the Kaim objects are
created from the world definition in the `.aipathdata` asset.

| service | game -> Kynapse | Kynapse -> game | used by |
|---|---|---|---|
| world | `.aipathdata` config through `KynapseSkel::CBigFileDataReader`; `Update(dt)` per frame 0x529433 | - | `AIAsset` 0x52c8ae |
| entity input (each think) | position of the `physicsVolume` (the character capsule), speed from position delta, orientation, x and z extent of the physics volume's bounds (`CEntityWidth` / `CEntityLength`; no height); `maxSpeed`, eye position, head direction, visibility angle and distance, path-finding constraint, sub-goal / end-goal distances, `pathSearchRadius`, dynamic avoidance type and its five parameters | - | 0x48a6a4, 0x48ae80 |
| agent selection | `agentType`: 0 idle, 1 goto (`gotoPos`), 2 follow (`followTarget`, `followDist`, `followAngle`), 3 wander, 4 flee, 5 hide | goto: `gotoDistanceLeft`; follow: `followCurrentDist`, `followHasArrived` | 0x48b951, 0x489d19 |
| steering output | - | action = heading + speed -> `aiVelocity` vector (zero when the agent has nothing to do) | 0x488bcd |
| path state | - | `HasPath`, `GetCurrentPath(list(vector))`, `IsAvoidingObstacle`, `GetObstacleAvoidanceDirection` | 0x4811b1.. |
| reachability | `IsPosReachable(pos)` (one pending request per brain, computed by a second goto path finder) | callback `IsPosReachableResult(truth)` | 0x481954, 0x48b951 lines 139-161 |
| sight | visibility parameters, factions | `IsTargetSeen(target, fakeTarget)`, `GetSeenAIEnemies`, `GetVisibleAIEnemies` ... (`AIAgentInfo` records), `IsTargetHostile` | 0x4829bd, 0x48460d |
| AI mesh | - | `AIWorldNode.TraceLine(from,to,radius):vector` 0x481f77, `IsInsideMesh(pos)` 0x48204d, `CanGo` 0x481ed0 | breadcrumbs, mesh-border tests |
| path objects | static/dynamic path object nodes with a collision volume | script callbacks `GetEdgeCost(entity,from,to)` and `TraversePathObject(entity,target,AIPathObjectInfo)` | 6.3 |
| reference points | `isReferencePoint` brains (the two heroes; table 0xe138c0..0xe13900): each NPC brain passes one of 16 channels: its own if it is a reference brain, else the last reference brain closer than the first one found (0x48ba9b never updates its best distance); radius `referenceRadius` 40 m; to its two path-finder services each think | - | 0x48b951 lines 60-138 |

Coordinates: Kynapse x = -engine x at every crossing (0x48110f).

What the scripts actually use (call sites in the lifted corpus): agent types 0 (48 sites), 1 (25), 2 (8:
`hangback`, partner behaviours, `AILib`), 3 (20, always as a one-frame re-plan kick); never 4 or 5 and
never `AddDangerousEntity`. Natives: `SetGotoPos` 26, `SetFollowTarget` 10, `IsPosReachable` 10,
`IsTargetSeen` 7, `GetVisibleAIEnemies` 6 (player target selection), `GetSeenAIEnemies` 2, `HasPath` 2,
`GetCurrentPath` 2, `GetGotoDistLeft` 2, `TraceLine` 10, `IsInsideMesh` 13, `SetIsImpassable` 3.

Configured in the world definition (data, identical in all five levels): path finder
`CHierarchicalPathFinder` on database "Characters" (flat data mode, search radius 100 (overwritten per agent, see NAV_DATA)), goto modifier
`CGoto_GapDynamicAvoidance_v2` ("biped"), goal test `CDetectGoalReached_Distance2D5` (max height delta 2),
path-node test `CDetectPathNodeReached_Distance2D5` (1.0 m), target point `CComputeTargetPoint_ShortCut`
(sampling 1.5 m, period 0.5 s), services `PointLockManager`, `GapManager`,
`HierarchicalPathObjectManager` (30 dynamic + 50 static path objects), `HierarchicalGraphManager`,
`EntityInfoManager` with Visibility / Sight / Distance / Hostility / Nearest* infos; profile
`AICharacterProfile` max 34 entities; follow agent defaults 3.0 m / 180 degrees (overwritten per agent, see NAV_DATA). Brain template (data):
`maxSpeed` 5, `pathSearchRadius` 50, sub-goal 0.5, end-goal 0.5-2.5, biped avoidance look-ahead 8 x 4 m,
passing distance 0.1, 360 degrees/s, update 0.1 s.

**A replacement must provide**: (1) for a goto / follow request, a per-frame desired velocity direction
on the navigation data, including local avoidance of other agents; (2) "has path" and remaining
distance; (3) an asynchronous "is position reachable from here"; (4) who-sees-whom between factions with
range, cone and occlusion; (5) segment trace and point-inside tests on the walkable mesh; (6) edge-cost /
traverse callbacks for special links. Nothing else of the 534 kB library is consumed by game logic.

### 6.2 What the game does itself (read)

- Destination choice, speed choice (idle 0 / walk 0.5 / run 0.8-1.0 / full 1.0), acceleration ramps,
  facing, strafing (`ClampDirection`), turn-rate limits, ally spreading.
- The velocity is only a direction source. `command_set_movement` 0x68e858 stores `_nprefmoveheading`,
  `_npreffaceheading`, `_nprefmovespeed`; `CharacterRoot.StateActive` 0x6b367a turns them into
  `m_nmoveheading` / `m_nfaceheading` / `m_nmovespeed` with the `CharacterDef` heading speeds
  (Dominatrix 10 and 8 rad/s; data) and the speed clamps (`_nspeedclampwalk` 0.4, `_nspeedclampjog` 0.6;
  data) and feeds the animation values `SPEED` (1) and `DIRECTION` (2). From there on it is the
  locomotion state machine (WP3); not traced here beyond locating the writes.
- No path / off mesh: `CharacterRoot.StateActive` keeps a **breadcrumb**, the last position for which
  `AIWorldNode.IsInsideMesh` was true (lines 7462-7745); pursuers aim at the target's breadcrumb; an
  enemy off the mesh for 2 s walks straight back to its own breadcrumb and is killed after 10 more
  seconds (2.2 rule 2). Stuck with a path request: the one-frame agent-type-3 kick (3.1, 3.3).
- Obstacle and character avoidance while path-following is Kynapse's; the script adds the moving-count
  clamp and the line-of-attack capsule cast (`AILib.AttackPathClear`).

### 6.3 Path objects and helper volumes (read + data)

- `AIStaticPathObjectNode` (properties `pathObject`, `impassable`, `canLeave`, `canBypass`): 38 plain ones
  in the door templates (opened/closed by `SetIsImpassable` from triggers); 10
  `KynapseStaticPathObjSceneClimbUp` in the NightClub: `GetEdgeCost` 0x77173e = length, but going up while
  the agent is in combat costs (10 x users + length) x 100; `TraversePathObject` 0x771392 takes the agent
  off the path finder and plays the climb through its own `StateActive`.
- `KynapseArtificialDoor` (42), `PathBlocker` (49): collision boxes that exist only for path-data
  generation (disabled at run time, 0x76ed53, 0x7dbbe3). `visionblocker` (47): the reverse (5.1).
- `AIPathDataSeedPointNode` (118), `AIPathDataExplorationAreaNode` (2), `AIStaticPathObjectVertexNode` (96):
  generation inputs / link endpoints.
- `aipathobjectinfo` = `AIPathObjectInfo(usepathfinder, doneusingpathobject, newdestination)`.
- Kynapse capacities set by the bridge 0x48ee9f: 500 entities (0x48eea5 → 0x9239c0), 8 worlds
  (0x48eeac → 0x923b70), 10 allocators (0x48eedd → 0x947380 → 0x946eb0); library defaults 1000 and
  1 (0x92548a, 0x925491).

## 7. Dominatrix walkthrough

Data: `Dominatrices.fragment` (`CharacterDef` {DOMINATRICE}, type 33, faction 1, health 100, damage
modifier 1.5; base definition and phase 1). Bordello placements: 92 records, 77 `AGGRESSIVE` / 15
`PASSIVE`, 24 with a one-handed weapon (`BASH_1H`), none start activated.

1. **Spawn**: disabled until an `ACTIVATE` trigger; enabled if among the 16 nearest. `Enemy.command_init`
   draws her evaluation interval (62-162 ms) and later her run speed (0.8-1.0, once).
2. **Staging**: usually a `FOLLOW_PIVOT` forced state walks her to a pivot; it ends when the pivot is
   reached or, for the normal variant, when a target comes within 4.0 m.
3. **Noticing**: any hero within 34 m with line of sight, in any direction, becomes a known enemy on the
   next frame; the nearest valid one is chosen unless it already has more than two attackers more than
   the other hero. The target is kept at least 4.0 s (`m_ntargetlocktime`), her group mates are told, and
   she speaks the spotted lines.
4. **Chase**: beyond 8 m she runs along the Kynapse path to the hero's last on-mesh position; she
   switches to `ATTACKING` as soon as she is inside 8 m with no mesh border in between.
5. **In the zone, not an active attacker** (the hero already has four nearer enemies in front within
   4.5 m, or she is not within 4.5 m in front): she closes in at run speed around her allies if fewer
   than five characters are moving, stops and taunts at 4.0-4.5 m, backs off at walk speed if closer than
   4.0 m.
6. **Active attacker**: stands facing the hero at 2.0-4.0 m (approaches to 3.9 m if farther, backs off to
   3.8 m if closer than 2.0 m). When her personal cooldown (1.8-3.0 s after her last attack start) is
   over and the capsule cast to the hero is clear she queues a request and rolls combo (p 0.5). The
   orchestrator grants it when fewer than 3 attacks on that hero are current and the last one started at
   least 0.2 s ago.
7. **The attack**: unarmed with the combo roll won: `[F][F][H]` with probability 3/4, `[F][dodge][H]` 1/4
   (frequencies 3 and 1). Otherwise, or **when she holds a weapon** (both of her combos consist of
   unarmed-only items, so the list is empty): a single attack, fast with p 0.8, heavy 0.2. That is the
   whole armed/unarmed difference in the AI; damage and animation differences are combat resolution.
8. **Hero too close** (inside 1.0 m for 0.5 s): an immediate attack without a grant, then a 1 s step
   back; repeat after 1.5 s.
9. **Defence** (attacks from her front only): the third identical attack in a row is dodged (sideways if
   she is the attacker's target, 50/50 left/right, else straight back); a fourth attack after three
   identical ones is blocked and countered 0.15 s later, and the count restarts; 4.0 s without an attack
   on her clears the history. Thrown: `m_nprobdodgethrow` 0.4 (0.8 in phase 1).
10. **Hit**: all behaviours pause, she turns to the attacker until the hit animation is 90 % through.
11. **Low health** (below 30, base definition only; phase 1 has no hang back): if the hero is attacked by
    at least two enemies and is not targeting her, she hangs back for 2-10 s: calls for help, keeps
    6-10 m, and regains 10 health per second while standing there.
12. **Hero down**: she taunts when the hero is stunned or prone and she holds the first attack slot.
13. **Death**: `Evaluate` returns `INACTIVE`, the root behaviour is switched off in `StateDead`, the
    orchestrator entry and LOD registration are removed.

Phase 1 (`SET_AI_DEF_PHASE`) differs only in: attack distance 4.5, punish zone 1.5, dodge-throw 0.8, no
hang back (data).

## 8. Partner AI (single player second hero) - outline only

Root behaviour `Partner` (0x7e873b), definitions `PartnerDef` (Rorschach 6, Nite Owl 7; the non-base ones
are the six "End-Duel" phases of the final fight; data). `Partner.Evaluate` 0x7dba9f (read): forced state;
step back; if `AGGRESSIVE`: `COMBAT` when `CombatOrchestrator.command_is_in_combat` and `CombatPartner`'s
preconditions hold, else `FOLLOW_PARTNER` while the human hero lives, else idle. Sub-behaviours:
`BehaviorIdle`, `FollowPartner`, `FollowPivotBehavior`, `CombatPartner` (with `AttackKillTargetPartner`,
`CrowdControlPartner`, `CombatHelpPartner`), `UseBehavior`, `UberRageBehavior`, `BehaviorWaypointMove`,
`BehaviorStepBack`. It registers in the orchestrator as faction 0, so enemies treat it as a hero, and it
drives the character through the same `command_set_movement` / attack commands. The 75 kB of partner
combat behaviours were not read.

## 9. Corrections to earlier documents

| document | statement | what the code says |
|---|---|---|
| audit c2 | `ATTACKING` when within the attack distance | within the orchestrator's engagement distance (8 m); `m_nattackdistance` is the stand-off / request range inside `AttackEnemy` |
| audit c9 | `KynapseCharacter.StateActive` turns the brain velocity into the movement request | it is a test class that integrates `worldPos += aiVelocity*dt` on a pivot; no instance in the data. The behaviours read `aiVelocity` themselves |
| audit c3 | meaning of tactical flag 0x400 not established | `PLACEMENT_REAR` |
| audit c3 | reaction comes from `PRE_IMPACT -> hit_soon -> when_attacked` | the reaction table is triggered at attack *start* by `CombatOrchestrator.command_attack_animation_stated`; `hit_soon -> when_attacked` is the separate face-the-attacker pause |
| audit c4 | where `_tdocombo` is rolled, how frequencies weight | `AttackEnemy.StateActive` at request time; multiplicity in a uniform pick; weapon filter |
| audit c12 | enum order EASY/NORMAL/HARD | NORMAL 0, EASY 1, HARD 2; no consumer exists |
| brief | AI sheets / `AiSheetChanger` | registered, no instance; definitions are switched by the behaviour handler |

## 10. Asset / format consequences

- `.aipathdata` (asset type 0x48d86c33) is extracted raw and that is all it needs: u32 payload size,
  "KS BIG FILE", then a tree of length-prefixed strings - the Kynapse world definition. The five files
  differ only in the database path, `ConcreteSlotSize` and `MaxAIMeshSize`. A JSON dump of the tree is
  trivial (token list in the tables file).
- **The navigation data itself is outside the archives**: `data/levels/game_levels_part2/<level>/gameplay/*.hpd`
  (Bordello 204,076 B, NightClub 204,404, StreetsOfRiot 200,620, PlayerVsPlayer 3,996, Tutorial 5,888),
  opened by Kynapse through `ksio.cpp` from the path in the definition. The extractor does not list or
  convert them. Layout verified on all five files (the computed offset of every cell's mesh tag
  matches): f32 1.3; u32 cell count; cell table at 0x84, 0x30 bytes each {id 1000+i, bounding box
  xmin,xmax,ymin,ymax,zmin,zmax in Kynapse space, 0, size, offset, date stamp, time stamp}; f32 1.0, u32 n,
  n x {u32 id, u16 8, u16 1}; then per cell u32 vertex count, u32 edge count, 36-byte vertices
  {id, x, y, z, 2 floats, 4 ints}, 12-byte edges, and an AI-mesh blob tagged "Kynogon Mesh" version 5
  (header carries the generation parameters 0.3 / cos 45 / 0.4). Vertex fields beyond the position, the
  edge encoding and the mesh blob are **not decoded**. Bordello: 3 cells, 781 vertices, 1957 edges.
- Level fragments carry the generation inputs (seed points, exploration areas, path blockers, artificial
  doors, static path objects with vertex nodes); already parsed by the fragment reader, no label.
- AI definition fragments parse completely with `kapow_fragment.py` (179 staged files, all `ok`); the
  `*.fragment.json` next to them on the PC were not used.

## 11. Not established

| item | what it would take |
|---|---|
| Dynamic avoidance internals (`CGoto_GapDynamicAvoidance_v2`), path smoothing | library internals; only needed for a faithful replacement |
| `.hpd` vertex extra fields, edge records, AI-mesh blob | read `CHierarchicalGraphManager` loading (0x90d2e0 region) |
| What `PASSIVE` changes for an enemy beyond speech, turf rules and "in combat" status | no gate on targeting was found in `Enemy`, `Perception` or the orchestrator; read `TriggerActionCharacter` action 1 and `CharacterGroup` to see how passive groups are held (probably by forced states) |
| Which orchestrator preset each encounter uses | list `CombatOrchestratorParameters` references in the level `MissionStructure.fragment`s |
| Values of `Perception._nremembertargettime`, `_ntimebetweenposreachablequeries`, `AttackEnemy._ncheckforclearlineofattackfrequency`, `ReturnToCombatZone.m_ntauntdistance` | not in the template fragments (script-side defaults); find the initialising writes |
| `ReturnToCombatZone`, `FollowPivotBehavior`, `BehaviorStepBack` in full | line-by-line read (about 8,000 lifted lines) |
| Partner combat behaviours, Twilight Lady punish logic, Underboss (Part 1 only) | 75 kB + 20 kB of script |
| Random generator and seeding of `rand_number` | read 0x47b03e |
| `CharacterRoot.StateActive` movement integration and the SPEED/DIRECTION animation values | WP3 |

## 12. Files

- `findings/wp4_ai.md` (this), `findings/wp4_ai_tables.json` (enemy / character / partner definitions with
  decoded reaction rows and combos, orchestrator constants and presets, state machine, enums, spawn
  statistics, Kynapse API surface, `.aipathdata` tokens, `.hpd` cell tables, consumer scan).
- `work/wp4/`: `v.py` (compressed lifted-handler viewer with constant, member-offset and position-idiom
  resolution), `vv.sh`, `vo.sh`, `sm.py` (call/constant summary), `consumers.py`, `xref.py`, `defs.py` /
  `q.py` (fragment tables), `build_tables.py`, `build2.py`, `notes.md`.
- Game files used (staged read-only from the PC): `TNT/Production/Fragments/Enemy/*.fragment`,
  `GameEssentials*.fragment`, level `gameplay.fragment` / `Gameplay/Enemies.fragment` / `Collision.fragment`,
  five `.aipathdata`, five `.hpd`.
