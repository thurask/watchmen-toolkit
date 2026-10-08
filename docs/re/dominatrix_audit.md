# The Dominatrix as a probe: what she touches in the engine, and how much of it is understood

Audit of `KapowMultiDEDRM.exe` (Watchmen: The End Is Nigh, Part 2, PC) against one enemy type.
Date 2026-10-04. Machine-readable twin: `dominatrix_audit.json` (same steps, same ids).

## 0. Answer to the question

Yes. Most of what a Dominatrix touches is not understood yet. What is understood is the part the
asset export needed: file formats, the animation state machine with its events and pairs, the face,
the jiggle joint, and the pixel and vertex shader math. Everything that makes her *behave* (the AI,
the combat rules, the ragdoll), everything that puts her on screen above the shader level (the render
pipe on the CPU), and everything she sounds like below the sound-definition level, is known only by
name, by data, or by a first skim done in this pass.

Of the 100 steps in her life traced below: 13 understood from the documents, 18 understood in this pass, 44 partly understood, 25 not understood.
By code volume, leaving the Kynapse library out: 2246 kB, about 19 % understood. Baked game script: 928 kB, about 30 %.
Engine C++: 1313 kB, about 12 %. These percentages are estimates (section 3 says how they are made).

Three things in the brief turned out different in the data, and one check of mine corrected itself:

- There are **nine** Dominatrix variants, not ten: `Dominatrix_1, 2, 4, 5, 6, 7, 8, 9, 10`. No
  `Dominatrix_3` node exists in `Dominatrices.fragment` (14 nodes, parsed lossless). The export
  folder has a `Dominatrix_3.glb`; where it comes from was not followed up.
- She has **no whip and no cattle prod**. Her weapon collection is `DominitrixWeapons_1H`: a police
  baton and a paddle, carried by 24 of the 92 placed Dominatrices; the other 68 are unarmed. The
  cattle prod belongs to the Twilight Lady (`BS2_COM_ATT_cattleprod_*`).
- She owns no `CharacterSweepAttack` and no `FXLightning*` node, and no `CharacterSpawner` stands in
  her level. Those classes touch her only as a victim (area attacks, Nite Owl's electrified armour).
- The `*.fragment.json` files that lie beside the fragments in the extract are stale: they were
  written by an older parser and show the Dominatrix `EnemyDef` with unnamed keys and a desync after
  `m_idrs03attack03`. The installed toolkit (1.4.0) parses the same file correctly. I first took
  this for a parser defect; it is not one. The stale files should be regenerated or deleted.

## 1. Gap list, ranked

Ranked by what the gap blocks for the two goals (a faithful asset export; understanding the engine).
Sizes are exe bytes of the code that has to be read; "open" is my estimate of the unread share.

| # | gap | steps | size | what it unlocks | package |
|---|---|---|---|---|---|
| 1 | **Render pipe on the CPU.** Pass order, which render effect a material goes to, model and material LOD, how lights are sorted into the four light-index layers, shadow-volume construction, hair, transparency order, who fills the skinning palette and when. No function in `kernel/rendering` has a semantic name. | g1, g3, g5, g8, g10, g15, b6 | 386 kB engine + about 60 relevant shaders | Export: the right material per part (hair, two-sided, glow), LOD choice, shadow hulls. Engine: a frame can be described from scene node to draw call. The shader side is already readable. | WP1 |
| 2 | **Ragdoll.** The joint limits, masses and body shapes are built in code (`CharacterRagdollSetup`, 14.7 kB, unread); the hand-over between animation and physics and the powered-ragdoll "muscle" blend are read only at the top level. | d10, d11, d8, e3 | 61 kB script | Export: a ragdoll rig for each skeleton, and the hit reactions that are part physics. Engine: knockdown, prone, get-up. | WP2 |
| 3 | **Character controller and PhysX wrapper.** How a move request becomes capsule motion, wall and slope handling, collision groups, the "Dcc" joint mode, contact reports. | e1, e2 | 41 kB script + 163 kB engine | Engine: movement, pushing, why characters slide or stop. Needed before any re-implementation of combat feel. | WP2 |
| 4 | **Combat rules in `CharacterRootLogic`.** Attack start, the attack queue, combo timing, block, dodge, counter windows, the damage formula. Only the event handler (37.7 kB) is documented; the 40 kB around it is not. | d1, d3, d6, d7, d14, b5 | 70 kB script | Engine: the fight itself. Export: per-attack damage, reach and timing values that are computed, not stored. | WP3 |
| 5 | **Enemy AI.** State choice is skimmed, the reaction table and the fast/slow choice are read; the nine sub-behaviours (where she stands, when she circles, steps back, hangs back), perception and the orchestrator's attack grants are not. | c1, c2, c4, c5, c6, c7, c8 | 136 kB script | Engine: why she does what she does. Nothing for the export. | WP4 |
| 6 | **Kynapse bridge.** Which Kynapse services run and what the script gets back per frame. The library itself (534 kB) does not need reading; the 43 kB bridge does. | c9, c10 (c11) | 9.5 kB script + 43 kB engine | Engine: path finding and avoidance; decides whether Kynapse can be replaced. Export: the `.aipathdata` nav data. | WP4 |
| 7 | **Runtime core.** How a fragment becomes an entity tree, how cross-fragment references resolve, the task scheduler's internals, asset streaming at run time. (The native node-update phases and worker jobs, b6, are listed under gap 1 and matter to both.) | a10, a8, b1, b2 | 379 kB engine | Engine: everything else stands on it; it also fixes the order "script, physics, skinning, draw" that today is inferred. | WP5 |
| 8 | **Audio below the sound definition.** 3D panning and attenuation (the engine's own: `X3DAudioCalculate` is not imported), voice pool, the four custom effects, obstruction, streaming. Script side: speak queue priorities, mixing and ducking, music intensity. | h2, h5, h6, h8, h9, h10 | 46 kB script + 132 kB engine | Export: per-sound ranges and mix values are data already; this adds how they are applied. Engine: the whole audio path. | WP6 |
| 9 | **Effects, HUD, camera feedback.** Effect objects, particle runtime, electricity, weapon trails, camera shake and special cuts, rumble, combo HUD. | i2 - i9 | 92 kB script + 140 kB engine | Engine: feedback layer. Export: effect definitions are data and already decoded. | WP7 |
| 10 | **Encounter scripting and game flow.** Trigger conditions and actions, group logic, level activation, checkpoints, the partner AI, the global difficulty setting (no consumer found). | a2, a3, a9, j2, j3, j5, c12 | 156 kB script | Engine: how a level runs. Export: nothing. | WP5 / WP4 |

One gap sits under all the script items and is listed separately because it is tooling, not reading:

- **Names inside the baked scripts.** The 441 registration functions end in 840 kB of declaration
  records that Ghidra still cuts off (`findings/submap.md` 0.1). This pass found what they are: the
  names of each handler's **local variables and parameters** (`etemplist`, `ecorpse`, `<return>` ...),
  pushed per handler; and it found that a script object's **member block is its property list in
  registration order** (4 bytes each, vectors 12, quaternions 16; a child class's list already
  contains the parent's). With both, `local_8[0x19]` reads as `m_nhealth` and `piVar6[2]` as
  `ecreateparent`. I used the member half of this by hand in this pass; it made handlers of 1 - 5 kB
  readable in minutes. Extracting both halves for all 441 classes is mechanical and should be done
  first (WP0).

## 2. Work packages

Each can go to one researcher. WP0 should start first; WP1, WP2 (engine half), WP5 and WP6 (engine
half) do not depend on it. WP3 and WP4 share `CharacterRoot` and should agree on who documents which
handlers (suggested split: WP3 owns `CharacterRoot` / `CharacterRootLogic`, WP4 owns everything under
`BehaviorHandler`).

**WP0. Names for the baked scripts.** Extract the declaration records of all 441 registration
functions from the exe bytes (pattern: `0x598d0e(tmp, "name", typeGlobal)` then `Vec20_PushBack`
0x5a0dfd; the `lea` before the push-back selects the handler's vector), compute member offsets from
the property lists, and write an annotated copy of the dump. Entry points: `ScriptClass_FinalizeLayout`
0x47ed4b, any `*__register`. Deliverable: `members.json` (class, offset, name), `locals.json`
(handler, slot, name), annotated dump. Small, mechanical, unlocks WP2 (script half), WP3, WP4, WP6
(script half), WP7. Scratch tools of this pass that show the idea: `work/domaudit/rdx.py`, `calls.py`.

**WP1. Renderer frame.** 2208 functions, 438 kB (script 10 kB, engine 424 kB); about 420 kB of it open. Read in this order: `RenderEffectManager` 0x572a7b and the
`RenderEffect` base 0x57d030 (which effects exist, their pass ids); `RenderPipe` 0x56f057 and
`DeferredRA` 0x574f74 (pass order, render targets, where `$LIB/$LAB/$LPT/$LCT` are filled);
`0x56bc16` / `0x56bcb8` outward (the per-draw-item path vcolor.md already entered) to find the
routing rule and the LOD choice; `LightConfigurationManager` 0x588ade (light sorting, four layers);
`REShadowVolume`; then the `Character` / `Model` draw submission in `kernel/scenegraph` and the skin
job. Read the remaining shaders alongside (ShadowVolumeVS, ShadowMapVS, HairPS/VS, the other
DeferredMain2PS variants): the disassembly exists in `work/vcolor/dis`. Deliverable: a frame
description (passes, targets, shaders, state) checked against the existing apitrace capture, and the
routing and LOD rules for the exporter. Independent of all other packages.

**WP2. Ragdoll and character physics.** 1298 functions, 265 kB (script 102 kB, engine 163 kB); about 247 kB of it open. Script first: `CharacterRagdollSetup.CreateBoneInfo`
0x682c60, `BoneMasses` 0x683545, `JointLimits` 0x683d12, `CreateJointInfo` 0x6846e8 (gives the rig);
then `CharacterVisual.command_update_ragdoll` 0x6bc3e2, `StateRagdollDriven` 0x69ed7c,
`AnimationCtrlWM.CharacterTransferToRagdollControl` 0x5b16ed and the two `MuscleOrientation*`
handlers (the blend); then `dynamic_getup_logic`; then `CharacterPhysics.command_attempt_move`
0x67d52c, `DccUpdate` 0x680654, `DccJoint` 0x6a3d71, `command_detect_wall` 0x67b508. Engine half:
`physx_charactercontroller.cpp`, `articulatedbody.cpp`, the contact and trigger reports; map the
PhysX vtable offsets with the 2.8.1 headers (submap section 6 says how many are open). Deliverable:
ragdoll rig tables per skeleton for the exporter; a description of the controller. Can be split in
two (ragdoll / controller) if two people are available.

**WP3. Combat rules.** 231 functions, 120 kB (script 120 kB, engine -); about 91 kB of it open. Read `CharacterRootLogic.command_start_animation_state` 0x688961,
`InitializeNextAttack` 0x68bf6f, `FireAttackBasedOnAttackID` 0x68d870, `ExecuteAttack` 0x68b351,
`command_update_combo_timing` 0x68810a; then `command_block` 0x686e56, `command_dodge` 0x686a17,
`TestForCounterAttack` 0x68d36a and `CharacterRoot.command_give_block_damage` 0x692c3f; then finish
`SetCloseCombatDamageToTarget` 0x6ae57f and the three pose manipulators in `ProjectAnimationLib`;
then the unread two thirds of `CharacterRoot.StateActive` (heading, rotation, speed clamps) and
`UpdateHealth` 0x678288; last `WeaponBase` and `command_set_weapon`. Deliverable: a rules document
(attack life cycle, windows, damage formula with every constant from exe bytes) and, for the
exporter, per-state combat values.

**WP4. Enemy AI and navigation.** 960 functions, 264 kB (script 221 kB, engine 43 kB); about 235 kB of it open. Read `Enemy.Evaluate` 0x72587d and `StateActive`
0x724071 line by line (this pass skimmed them); `BehaviorChase`, `AttackEnemy.StateActive` 0x5ff3d6
and `FindUsableCombo` 0x600730, `hangback`, `BehaviorStepBack`, `CircleTargetEnemy02`,
`SecondaryAttackerEnemy`, `ReturnToCombatZone`; `Perception`; `CombatOrchestrator.StateActive`
0x6e8231 with `command_request_attack` / `command_register_attack` / `LockTarget`;
`CharacterAIBrain.command_get_target` 0x64956f. Engine half: `aibrainnode.cpp` and the
`KynapseNPCBrain` / `KynapseNPCAction` classes, enough to list the Kynapse services used and the
data that crosses the bridge. Optional second half: the partner behaviours (75 kB) and the Twilight
Lady's extras. Deliverable: state diagrams with the real numbers; the list of Kynapse calls.

**WP5. Runtime core and level flow.** 3308 functions, 469 kB (script 90 kB, engine 379 kB); about 348 kB of it open. Engine: `Fragment` 0x542c1a and `FragmentNode`
(instancing, reference resolution), `Entity_SendCommand` 0x596d91 down to 0x47c9fd, the task
scheduler (0x47a66f, 0x47d23e), `SceneNode` update 0x495fec (which node classes are in which list),
the job scheduler 0x444813, `AssetStreamManager` 0x4e0e5d. Script: the trigger classes
(`TriggerActionCharacter.ActionExecute` 0x85b858 first), `CharacterGroup`, `MasterSceneCtrl`,
`GameStateCtrl` checkpoints. Deliverable: the frame-order document and a description of level
start-up from block file to first frame; answers the difficulty question as a by-product (who reads
`PREFERENCES_GAMEDIFFICULTY`).

**WP6. Audio.** 1243 functions, 189 kB (script 57 kB, engine 132 kB); about 177 kB of it open. Script: `SpeakCtrl.Active` 0x83d414 (queue, priorities, quarantine),
`SoundCtrl.StateActive` 0x829f70 and `command_damp` 0x83104a, `MusicIntensityCtrl.StateActive`
0x7ce905. Engine: `SoundSlot::PlayGroup*`, `SoundSystemNode`, then the XAudio2 layer (source voice
handling at member +0x124, output matrix computation, the four XAPO effects, the obstruction job).
Deliverable: the path from a sound event to a voice with volume, pitch and channel matrix.
Independent of the others.

**WP7. Effects, HUD and camera feedback.** 1174 functions, 232 kB (script 92 kB, engine 140 kB); about 213 kB of it open. `EffectCtrl`, `EffectParticle.Fire` 0x7162f0,
`EffectsLib`; the particle runtime (large but regular, one class per file); `ElectricArmor` and
`FXLighting`; `CameraModifierSinusShake`, `CameraCombatSpecialCuts`; `VibrationMotorCtrl`;
`ComboBuildupHud`, `PlayerHUD`, `SpriteWobbler`; `Sprite` / `TextBox` engine nodes. Deliverable: how
an effect id becomes particles, sound and camera motion; lowest priority for the export.

## 3. Coverage figures

| area | understood | understood now | partly | not | code (without the Kynapse library) | understood, estimate |
|---|---|---|---|---|---|---|
| a. Level load and spawn | 1 | 5 | 7 | 0 | 436 kB | 28 % |
| b. Per-frame update | 1 | 1 | 3 | 2 | 109 kB | 28 % |
| c. Decision making | 0 | 1 | 7 | 4 | 191 kB | 16 % |
| d. Combat mechanics | 2 | 3 | 5 | 4 | 192 kB | 34 % |
| e. Movement and physics | 3 | 0 | 2 | 2 | 219 kB | 11 % |
| f. Animation | 3 | 1 | 2 | 0 | 168 kB | 66 % |
| g. Rendering | 2 | 3 | 6 | 5 | 408 kB | 4 % |
| h. Sound | 1 | 0 | 6 | 3 | 189 kB | 7 % |
| i. FX and feedback | 0 | 2 | 4 | 4 | 234 kB | 9 % |
| j. Game flow | 0 | 2 | 2 | 1 | 101 kB | 5 % |

Totals: 13 understood from the documents, 18 understood in this pass, 44 partly understood, 25 not understood. All code she touches including the Kynapse library: 2780 kB, about 16 % understood.
Without it: 2246 kB, about 19 % understood.

How the byte figures are made, and their limits:

- A step's size is the sum of the exe bytes of the functions named for it, from
  `findings/submap.json`. For script classes I counted handlers and left out editor and debug
  handlers by name (`FilterExposedProperties`, `*debug*`, `Annotate*`, `fill_debug_view`, `_root`).
  For engine subsystems I took the whole subsystem from the map. Handlers shared between a class
  and its base are counted once by hand; expect errors of 10 - 20 % per step.
- "Understood" bytes are size times a fraction I assigned per step: 1.0 only where the code was read
  and checked, 0.7 - 0.9 where it was read, 0.3 - 0.6 where it was skimmed and the mechanism is
  clear, 0.1 - 0.25 where only call lists and data are known, 0 - 0.05 for names only. The
  fractions are judgement, not measurement.
- The engine figures count whole subsystems although one character does not exercise all of each
  (for example all 104 kB of the particle runtime). That makes the engine percentage look worse
  than a strictly reachable set would; I did not attempt a reachability cut inside engine
  subsystems.
- Shader bytecode has no exe bytes and is not in the percentages; shader steps count as steps only.

## 4. Method, evidence, limits

- Data first: `Dominatrices.fragment`, `En4CharVisual.fragment`, the nine `Enemy04*` animation
  fragments (local copies, parsed with the 1.4.0 toolkit), and on the PC (read-only) the level and
  game-essential fragments: `Enemies.fragment`, `MissionStructure.fragment`, `Bordello.fragment`,
  `Art.fragment`, `gameplay.fragment`, `GameEssentials.fragment`, `CharacterRootTemplate_Enemy`,
  `CharacterDef`, `CharacterVisual`, `combatorchestratordefaults`, `EffectDb`, `WeaponDB`,
  `AllBodelloTypes`, one `SoundEvents/SE_EN4_*`. The PC shell was unreachable for the first part of
  the session and came back later; nothing was written under `mnt/`.
- Code: the repaired dump through `fn.py`, the registry `reg_dump.json`, sizes from `submap.json`,
  constants from exe bytes. Scratch tools in `work/domaudit/`: `rdx.py` (prints a handler with
  hashes resolved to command and property names, coroutine boilerplate folded, members named),
  `calls.py` (the ordered list of commands a handler sends), `cls.py` / `sz.py` (handlers and sizes
  per class), `steps.py` / `gen.py` (the step table).
- Evidence words in the tables: **read from code** (traced in the decompilation, constants from
  bytes where quoted), **skimmed** (control flow and calls followed, not every branch), **call
  list** (only the ordered commands a handler sends were extracted), **data** (read from the game
  files), **inferred**, **not established**.
- A verdict of "understood" cites the document. "Understood now" means the explanation is in this
  report. "Partly" says what is and is not known. A handler that is merely named counts as not
  understood.
- Not done: no Ghidra run, no dynamic trace. Reachability of debug code is by name.

## 5. Who she is, and what one Dominatrix consists of

Identity (data + enum registry): `CharacterDef "{DOMINATRICE}"`, `m_icharactertype` 33 =
`CHARACTER_TYPES.DOMINATRICE`, faction 1 (enemy), AI base type 2 (`NORMAL_ENEMY`), main behaviour
`"Enemy"`. Body animation class id 10 (`EN4`, Enemy04), head animation class id 11 (`EN4_FACE`).
As an opponent in the players' animation criteria she is `OPPONENT_MODEL_TYPE` 7 (`ENEMY_04`).
Skeleton `Female_Skeleton.model`. The Twilight Lady is type 35, shares the Enemy04 class with
`SPECIFIC_MODEL` = `TWILIGHT_LADY` set at spawn (0x67884e, type 0x23), and has her own skeleton,
CharVisual and four AI phases.

Numbers from her definition: health 100; critical health 44 (the finisher threshold); finisher icon
3.0 s; no health regeneration; damage modifier 1.5; turn speeds 10 and 8 rad/s; visual range 34 m;
attack distance 4.0 m (4.5 in phase 1); minimum distance 2.0 m; 1.8 - 3.0 s between attacks;
P(fast) 0.8, P(slow) 0.2, P(combo) 0.5; hang back below 30 % health for 2 - 10 s at 6 - 10 m (base
definition only); target lock 4.0 s. Speech voices Dom1, Dom2, Dom3 (26 speak events each).

### Script objects instantiated for one Dominatrix

From the level (`Enemies.fragment`):

| class (native base) | role |
|---|---|
| `CharacterRoot` (PivotNode) | the character: health, headings, target, state coroutines `StateActive` / `StateDead`; child of a `CharacterGroup` (Folder) that counts alive and dead members |

From `CharacterRootTemplate_Enemy.fragment` (created by `InstantiateSubSystems`):

| class (native base) | role |
|---|---|
| `CharacterPhysics` (CollisionCapsuleNode) "MovementPhysics" | 0.8 x 2.0 m capsule, the character controller; with `RigidBody` (mass 100), `EmbeddedJointNode` "WorldJoint", `D6Joint` |
| `Sprite` x4 + `SpriteWobbler` (TextBox) x4 | the finisher button prompts (Fast, Heavy, Throw, DodgeBlock) floating at 1.2 m |
| `CollisionCapsuleNode` "ExpandVolume" + joints + `CollisionBoxNode` "FollowPivot" | soft volume on a spring joint (pushing); driven by `CharacterExpandVolume` code in `CharacterVisual` |
| `CharacterAIBrain` (AIBrainNode) "AIBrain" | the Kynapse agent: faction, visibility cone, path-finding and avoidance parameters |
| `BehaviorHandler` (Node) | owns the root behaviours and the AI definition in force |
| `Perception` (Node) | known-enemy list and tactical information, refreshed every 0.5 s |
| `CharacterRootLogic` (Node) | attack, combo, block, dodge logic; receives the animation events |

From `En4CharVisual.fragment`:

| class (native base) | role |
|---|---|
| `CharacterVisual` (Character) "EN4_Dominatrix" | the skinned body; ragdoll control; per-frame animation inputs |
| `AnimationCtrlWM` (Node), class id 10, + `AnimationDataWM` | body state machine and its blackboard |
| `CollisionBase` (CollisionSphereNode) "TriggerSphere" + `RigidBody` | 5 cm trigger sphere for level triggers |
| `CharacterHeadCtrl` (Node) | head character, face class, look-at |
| `BoneAttacher` "HeadAttach" | where the head character hangs (Spine2) |
| `Character` "HeadModel" + `AnimationCtrlWM`, class id 11, + `AnimationDataWM` | the rigged head and its face state machine |
| `Node` "AddOnCtrl" / `CharacterAddonCtrl` (PivotNode) | jiggle bones |

Created in code:

| class | role | where |
|---|---|---|
| `BoneAttacher` on bone "Attach RHand" | weapon mount | 0x67884e |
| `WeaponBase` (Model) | baton or paddle when `_iweapontype` = 0 | `command_set_weapon` 0x694378 |
| root behaviour `Enemy` | state choice | `AILib.CreateRootBehavior` 0x5974f0 |
| `BehaviorIdle`, `BehaviorChase`, `AttackEnemy`, `hangback`, `LeaderEnemy`, `ReturnToCombatZone`, `TwilightLadyBackflipBehavior`, `BehaviorStepBack`, `FollowPivotBehavior` | sub-behaviours, all nine always created | `Enemy.command_init` 0x7231b4 (strings read from exe bytes) |
| `CircleTargetEnemy02`, `SecondaryAttackerEnemy`, `BehaviorEnforceSameHeight` | children of `AttackEnemy` | `AttackEnemy.command_init` 0x5ff00b |
| ragdoll (native ArticulatedBody) | built by `CharacterRagdollSetup` | `CharacterVisual.command_activate_ragdoll` 0x69eac6 |

Shared objects she reads or calls (one instance per game, in `GameEssentials.fragment` and its
includes): definitions `CharacterDef`, `EnemyDef` x2, `CharacterModelCollection`, `CharacterHeadModel`
x9, `CharacterSoundDef`, `GlobalAiParameters`, `CharacterVisualDef`, `CharacterRagdollSetup`,
`CharacterComboDatabase` / `String` / `Item`, `CharacterEffectDef`, `SpeakDefinition` /
`SpeakVoiceDefinition`, `SoundDef`, the `AnimationClassWM` trees; controllers `characterlib`,
`CharacterLodCtrl`, `CombatOrchestrator`, `GroupManager`, `GameEventCtrl`, `SpeakCtrl`, `SoundCtrl`,
`EffectCtrl`, `CollisionEffectCtrl`, `DynamicObjectsEffectCtrl`, `FxHighlightCtrl`,
`MusicIntensityCtrl`, `AchievementPart2Ctrl`, `ScriptUpdateCtrl`, `PhysicsSimulation` (PhysicsWorld),
`AIWorld`, `CullingCtrl`; libraries `AILib`, `AnimationLib`, `ProjectAnimationLib`, `MathLib`,
`WorldLib`, `ProjectLib`, `EffectsLib`, `SpeakLib`.

Debug or editor-only in her tree (by name; the game can still reach them): the
`FilterExposedProperties` handler of every class (editor property panel), `command_fill_debug_view`
on every behaviour, `Debug*` handlers and `m_bdebug*` properties on `CharacterRoot`,
`AnimationDataWM`'s debug overrides, `AIDebug_orchestrator` under the orchestrator, `SessionLogCtrl`
(finisher logging), `PerformanceMeasurement`.

## 6. The pipeline

### a. Level load and spawn

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| a1 | Identity of the type *Nine variants, not ten: Dominatrix_1,2,4,5,6,7,8,9,10 (no _3). Dominatrices occur only in the Bordello level (92 CharacterRoot nodes).* | - | TNT/Production/Fragments/Enemy/Dominatrices.fragment: CharacterDef {DOMINATRICE} m_icharactertype=33, m_ifaction=1<br>enums CHARACTER_TYPES 33=DOMINATRICE, CHARACTER_ANIMATIONS 10=EN4 / 11=EN4_FACE, OPPONENT_MODEL_TYPE 7=ENEMY_04, ANIMATION_HEAD_MODEL 18/21/23/24/25 | **understood now** | data + enum registry; enums.md | - |
| a2 | Placement in the level: CharacterRoot nodes under CharacterGroup folders *Known: the data layout and that a group counts alive/dead and fires an all-dead action. Not read: StateActive, command_create_zones (0x6683ba), SetHeightAboveGround.* | CharacterGroup (reg 0x67054a): initialize_external 0x668a99, StateActive 0x668ded, command_add_character_to_group 0x668845, command_remove_character_from_group 0x6688d4, FireDeadActions 0x66267e<br>GroupManager.command_add 0x75df66 | Levels/Game_Levels_Part2/Bordello/Gameplay/Enemies.fragment: 165 CharacterRoot(PivotNode) in 56 CharacterGroup(Folder); per node _icharactertype, m_iprioritymodel, _iweapontype, m_istateofmind, _tstartactivated, localPos/localOrient<br>CharacterGroup._ealldeadaction, _ereturntohometurfpoint | **partly understood** | data read; handler list only; FRAGMENT_FORMAT.md (spawn map) | 23 fn, 5 kB |
| a3 | Encounter scripting: trigger conditions and actions that activate, steer and re-phase her *Known: the action vocabulary and which command each action sends. Not read: condition evaluation, delay chains, zone enter/leave, force-move.* | TriggerActionCharacter.ActionExecute 0x85b858 (5.1 kB), RecursiveSetCharActivationState 0x85cd2d<br>TriggerActionCharacterForceMove, TriggerActionDelay, TriggerActionGeneral, TriggerActionBase, TriggerConditionCollision/Character/Logical/Toggle, TriggerCharacter | Enemies.fragment: 208+43 TriggerActionCharacter, 128 TriggerConditionCollision, 72 TriggerActionDelay; m_iactiontype histogram DEACTIVATE 68, FOLLOW_PIVOT 57, ACTIVATE 45, SET_AI_STATE 20, PLAY_SPECIFIC_ANIMATION 15, DAMAGE_MODE 11, SET_AI_DEF_PHASE 8, FREEZE_ACTIVE_RAGDOLLS 7<br>enum TRIGGER_ACTION_CATEGORY_CHARACTER (35 actions) | **partly understood** | data read; ActionExecute call list read; FRAGMENT_FORMAT.md (encounter content) | 142 fn, 32 kB |
| a4 | Character definition lookup (type -> CharacterDef -> EnemyDef) and stats *Understood now: the def table is indexed by _icharactertype; health comes from the def. Not read: EnemyDef handlers that build the DRS tables and copy properties.* | CharacterRoot.initialize_external 0x6b3164<br>CharacterRoot.FindCharacterDef 0x6977dd<br>CharacterDef (reg 0x66ee9b), AiDef, EnemyDef (reg 0x731622; 27 handlers), GlobalAiParameters<br>AILib.RegisterAiDef 0x5988c5 | Dominatrices.fragment: CharacterDef (health 100, critical 44, finish icon 3.0 s, heading speeds 10/8 rad/s, damage modifier 1.5), two EnemyDef (BASE_DEF and PHASE_1)<br>GameEssentials.fragment: GlobalAiParameters (g_nfullspeed 1.0, g_nwalkspeed 0.5, m_nmeleemaxdistance 4.5) | **partly understood** | read from code (lookup) + data | 38 fn, 10 kB |
| a5 | Variant choice (which of the nine bodies) *Least-used balancing, no randomness.* | CharacterDef.command_get_override_model 0x666d03<br>CharacterModelCollection.command_get_model 0x66ca15, command_decrease_model_ref 0x66ccad | CharacterRoot.m_iprioritymodel (0 on all 92 placements)<br>CharacterHeadModel.m_iprioritymodel (0 on all nine) | **understood now** | read from code | 5 fn, 917 B |
| a6 | Head choice and attachment | CharacterHeadCtrl.command_activate 0x669496<br>CharacterModelCollection.command_get_model_by_id 0x66cbdd | m_iheadmodeltype per variant: 21,18,24,23,25,23,24,21,23<br>BordelloFace.fragment (head collection) | **understood** | read from code (earlier round); ENGINE_CONSTANTS.md 2026-10-04; findings/face.md | 2 fn, 2 kB |
| a7 | Weapon given at spawn *Known from data what she can carry and from InstantiateSubSystems that the weapon hangs on "Attach RHand". Not read: set_weapon, durability, break, pick-up/drop.* | CharacterRoot.command_set_weapon 0x694378<br>WeaponBase (reg 0x8ba89a), WeaponLib, WeaponSpawner | CharacterDef.m_emodelcollbash1h -> WeaponDB DominitrixWeapons_1H: PoliceBaton (durability loss 0.16/hit, priority 1), Paddle (0.2/hit, priority 2)<br>CharacterRoot._iweapontype: -1 on 68 placements, 0 (BASH_1H) on 24 | **partly understood** | data read; code not read; ENGINE_CONSTANTS.md (weapon attachment) | 20 fn, 10 kB |
| a8 | Block file -> assets (model, texture, animation, sound), streaming *Understood: container, directory, asset headers, model and texture payloads. Not read: AssetStreamManager (what is resident vs streamed, the .stream mip policy), block memory setup, asset reference counting.* | LoadBlock state machine 0x4a36d8, start 0x4ae0fd, header 0x49dd0e<br>AssetManager 0x550eb5, AssetStreamManager 0x4e0e5d, AsyncFileBuffer 0x43fb3f | *.block_h_z / *.block_s_z, "loadblock fragment" trailer<br>*.model + .model.stream, *.bmp + .stream | **partly understood** | file side read and validated; runtime side not read; KAPOW_NAZ_FORMAT.md, re/formats.md | 1300 fn, 188 kB |
| a9 | Level activation script *Bordello has no StreamBlock nodes: one load block per level.* | MasterSceneCtrl.StateActivateScene 0x7a63b2, StateWaitForLoad 0x78f8dc<br>LevelSceneCtrl (reg 0x7784b9)<br>StreamBlockManager.command_get_streamblock_for_loading 0x841166 | Bordello.fragment: SceneSettings, LevelSceneCtrl, FragmentNodes Art / gameplay / Sound, CharacterDB folder (AllBodelloTypes, AnimationClassEnemy04, AnimationClassEnemy04Face) | **partly understood** | call order skimmed | 66 fn, 23 kB |
| a10 | Fragment instantiation: bytes -> entity tree with typed properties *The file format is fully parsed. How FragmentNode expands an assetName, resolves cross-fragment references ("xref") and constructs script objects is not read. New in this pass: a script object's member block is its property list in registration order, 4 bytes per member, 12 for vectors, 16 for quaternions (checked on five classes).* | Fragment asset 0x542c1a<br>Entity / property / message system (script.database)<br>scene.core (Node, PivotNode, Folder, FragmentNode)<br>ScriptClass_FinalizeLayout 0x47ed4b | *.fragment | **partly understood** | file format read; instancing code not read; FRAGMENT_FORMAT.md; findings/submap.md 3.4 | 1234 fn, 149 kB |
| a11 | Building one Dominatrix: CharacterRoot.InstantiateSubSystems | CharacterRoot.InstantiateSubSystems 0x67884e<br>ProjectLib.InitializeHierarchy<br>AILib.CreateRootBehavior 0x5974f0<br>BehaviorHandler.command_add_root_behavior 0x6184f1<br>CharacterVisual.command_set_override_model 0x69c8e3, command_activate_model 0x69e354<br>characterlib.AddToUpdateList 0x66afc4 | CharacterRootTemplate_Enemy.fragment (via CharacterDef.m_echaracterfragment)<br>En4CharVisual.fragment (via CharacterDef.m_emodelfragment) | **understood now** | read from code | 8 fn, 6 kB |
| a12 | Activation and the 16-enemy budget *Level 2 builds the sub-systems, levels 0 and 1 delete them: only the 16 nearest activated enemies exist as full characters.* | CharacterRoot.command_character_activate 0x68f1e1<br>CharacterLodCtrl.command_register_enemy 0x66b6b8, StateActive 0x66bb68<br>CharacterRoot.command_set_lod_level 0x694e04, SetLODLevel 0x69715b, EnableSubSystems 0x696fac, DisableSubSystems 0x6763e7 | GameEssentials.fragment: CharacterLodCtrl _imaxenemycount 16, m_ncharacterenabledist 40 | **understood now** | read from code (StateActive skimmed) | 19 fn, 6 kB |
| a13 | CharacterSpawner (respawning folder) *Not part of her life in the shipped level; read because the brief names it.* | CharacterSpawner.StateActive 0x697ddc, EraseBody 0x679694 | not present in Bordello | **understood now** | read from code | 14 fn, 4 kB |

Read in this pass:

**Variant choice (a5, read from code).** `CharacterDef.command_get_override_model(priority)`
0x666d03 forwards to the override collection's `command_get_model` 0x66ca15. If `priority` is not 0
it looks for the member whose `m_iprioritymodel` equals it. Otherwise, or when none matches, it takes
the member with the lowest instance count (the collection keeps `_imodelinstancecount` per member;
the first minimum in list order wins), increments that count, and returns the member.
`command_decrease_model_ref` 0x66ccad gives the count back when a character is deleted. All 92
placed Dominatrices and all nine variants have priority 0, so the nine bodies are dealt out evenly in
activation order. There is no random number in this path.

**Building her (a11, read from code).** `CharacterRoot.initialize_external` 0x6b3164 looks the
definition up in `characterlib`'s table by `_icharactertype`, registers with `GroupManager`
(`command_add` returns the group id), copies health from the definition, stores start position and
heading, registers for game events, and, for a non-playable type, calls `command_character_activate`
only if `_tstartactivated` is set (it is false on all 92). `InstantiateSubSystems` 0x67884e then, in
this order: creates the template fragment node from `m_echaracterfragment` and runs
`ProjectLib.InitializeHierarchy`; finds child "MovementPhysics" and sends
`command_activate_collision`; finds "AIBrain", enables it, sets its faction from the definition,
sends `command_activate`; finds "BehaviorHandler", sends `command_init`, and adds one root behaviour
per behaviour name of the AI definition (`m_smainbehavior`, `m_ssecondarybehavior`) through
`AILib.CreateRootBehavior`; adds a "BehaviorTutorial" root behaviour when a global tutorial flag is
set; finds "CharacterRootLogic"; creates the model fragment node from `m_emodelfragment`, takes its
first child as the `CharacterVisual`, finds "ImpactLight"; asks the definition for the variant
(above) and sends `CharacterVisual.command_set_override_model`; sends the visual `init`, runs
`InitializeHierarchy` on it, sends `command_activate_model`; creates a `BoneAttacher` on
"Attach RHand" and sends `command_set_weapon(_iweapontype)`; sets animation enum 6 (playable or
not); for type 35 sets enum 14 to 1 (`SPECIFIC_MODEL` = `TWILIGHT_LADY`); sends
`command_finalize_initialization`; registers a playable character for manual resume at order 5, any
other with `characterlib.AddToUpdateList`; sets animation enum 15 from the loaded load block; and
broadcasts game event 0xce.

**Activation and the enemy budget (a12, read; the tail of the loop skimmed).** A trigger action
`ACTIVATE` on her group ends in `CharacterRoot.command_character_activate` 0x68f1e1, which registers
her with `CharacterLodCtrl` (0x66b6b8, into an "incoming" list). `CharacterLodCtrl.StateActive`
0x66bb68 each frame deletes queued characters, admits one incoming character per frame, computes for
every enemy the squared distance to the nearest player, sorts by it, and sends
`command_set_lod_level(2)` to the nearest `_imaxenemycount` (16) and level 1 to the rest.
`CharacterRoot.SetLODLevel` 0x69715b: level 2 calls `InstantiateSubSystems` and then
`EnableSubSystems`; levels 0 and 1 call `DeleteSubSystems` (self-method slots 0x27c, 0x294, 0x290 =
command indices 159, 165, 164). So at most 16 enemies exist as full characters; an activated
Dominatrix beyond the 16 nearest has no physics, brain, logic or model at all, and is built when she
moves into the set. Consequence (inferred): the body variant is chosen at each build, so the same
placed Dominatrix can come back with a different body. The level change is refused while
`CharacterRootLogic.command_is_lod_allowed` says no (0x694e04). Not read: the extra distance test in
the level-1 branch (`m_ncharacterenabledist` 40 m).

**CharacterSpawner (a13, read from code).** A folder that remembers the start transforms of its
`CharacterRoot` children. `StateActive` 0x697ddc: while active and below `_imaxnumofspawnedcharacters`,
every child whose health is 0 is replaced by a newly created `CharacterRoot(Pivotnode)` with the same
type at the stored position (initialize, activate, add to the group), and the dead one moves to a
dead list. Corpses beyond `_imaxnumofdeadvisible` (30) are erased when neither player camera has them
in the frustum, and unconditionally beyond that count plus five. Bordello contains no spawner.

### b. Per-frame update

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| b1 | Frame loop and time step | SceneNode::Update (vtable slot 39) 0x496294<br>main / KapowEngine 0x8bef92, 0x8bfdd9 | clamp 0.1 s at 0x9e664c; time multiplier SceneNode+0x2dc | **partly understood** | SceneNode::Update read; main loop not read | 47 fn, 12 kB |
| b2 | Script scheduler | SceneNode script update 0x495e41<br>Entity task resume 0x4f9baa<br>Task_* (script.runtime 0x479823-0x4810d9) | - | **partly understood** | run loop read; task internals from submap; findings/submap.md 3.4 | 324 fn, 30 kB |
| b3 | Ordered script update (pre / post) | ScriptUpdateCtrl.preScriptUpdate 0x815030, Update 0x812ab5, postScriptUpdate 0x8150d9, command_register_manual_resume 0x8148cb | ScriptUpdateCtrl.m_idefaultscriptordering 5 | **understood now** | read from code | 10 fn, 2 kB |
| b4 | CharacterRoot.StateActive: order of work inside one character | CharacterRoot.StateActive 0x6b367a (31.4 kB) | - | **partly understood** | call order read; placement block read earlier; heading math not read; re/placement.md | 1 fn, 31 kB |
| b5 | CharacterRootLogic per-frame state handling | CharacterRootLogic.StateCharacterRootLogic 0x68abab, command_do_special_state_handling 0x687bc5 | - | **not understood** | names only | 2 fn, 2 kB |
| b6 | Native node update phases and worker jobs (skin, physics, particles, occlusion, sound obstruction) *Which node classes sit in the first and second list, and when the skin job runs relative to script, decide the frame of lag between logic and picture.* | SceneNode node update 0x495fec (two node lists, vtable +0x44)<br>core.threading scheduler 0x444813 | - | **not understood** | structure seen; membership and ordering not established | 217 fn, 31 kB |
| b7 | Physics step (accumulator, substeps) | 0x4f4ddc | - | **understood** | read from code (earlier round); ENGINE_CONSTANTS.md 2026-10-03; re/physx_d6.md | 1 fn, 600 B |

Read in this pass (b1 - b4):

- `SceneNode::Update` 0x496294: frame time from the millisecond clock, clamped to 0.1 s; game time
  step = that times the scene's time multiplier (`SceneNode+0x2dc`, the value
  `WorldLib.SetTimeMultiplier` changes for slow motion) times a second factor (+0x2e0). Then, in this
  order: input (0x4b5644, 0x4c87c3); the native node update 0x495fec; the script update 0x495e41;
  particle and emitter updates; clean-up. In pause mode only the script update runs.
- Native node update 0x495fec: sends a "before" message to the render handler, updates a first list
  of nodes (vtable +0x44), runs 0x5427a6, 0x529f71 and the cloth update, updates a second list,
  sends an "after" message. Which node classes are in which list is not established (b6).
- Script update 0x495e41: sends `preScriptUpdate` to the registered handler (`ScriptUpdateCtrl`),
  resumes the scene's own task, then resumes every scripted entity in a flat list (0xe14438) once,
  skipping entities without the real-time flag when the game time step is 0, then sends
  `postScriptUpdate`.
- `ScriptUpdateCtrl`: `preScriptUpdate` 0x815030 resets `characterlib`'s update list and runs
  `Update(order)` for orders 0 to `m_idefaultscriptordering` (5); `postScriptUpdate` 0x8150d9 runs
  the orders above 5. `Update` 0x812ab5 resumes the tasks registered for that order
  (`command_register_manual_resume`) and sends `command_update` to that order's listeners. Player
  characters register at order 5; a Dominatrix does not: she runs in the flat list, after the players.
- Inside `CharacterRoot.StateActive` 0x6b367a (one pass per frame, from the ordered call list):
  teleport requests; AI-mesh check and breadcrumb; combo timing (`Logic.command_update_combo_timing`);
  electrify power; `CharacterVisual.command_update_animation` (animation inputs, face, head
  controller, add-ons); slow-motion restore; stun timer; wall detection; preferred / face / move
  heading with angle damping; rotation and movement deltas from the animation; ragdoll update
  (`command_update_ragdoll`) when prone; pair placement and slave handling (placement.md);
  `command_update_animation` again; velocities; `Logic.command_do_special_state_handling`; attack
  break-off; `CharacterPhysics.command_attempt_move`; teleport and collision reset; rage; cloth
  acceleration; enabling and disabling of actor, joint and articulated body; `UpdateAnimPoseAndCloth`;
  `characterlib.CharacterIsUpdated`, and when `AllCharactersUpdated`,
  `PhysicsWorld.BeginClothSimulation`; then wait for the next frame.

### c. Decision making

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| c1 | Behaviour framework: BehaviorHandler, Behavior base, root behaviours, forced states, AI definition sheets | BehaviorHandler (reg 0x61fc2d): command_init 0x6182b3, command_add_root_behavior 0x6184f1, command_set_ai_parameter_sheet 0x618084, command_switch_to_leader_def / _base_def<br>Behavior (reg 0x639ea2)<br>AILib.CheckForcedState 0x59ca06 | EnemyDef.m_smainbehavior "Enemy", m_ideftype BASE_DEF / PHASE_1<br>trigger actions SET_AI_STATE, SET_AI_DEF_PHASE, REQUEST_FORCED_STATE | **partly understood** | handler list + call lists | 58 fn, 6 kB |
| c2 | Enemy root behaviour: state choice | Enemy.Evaluate 0x72587d (6.0 kB)<br>Enemy.StateActive 0x724071 (6.0 kB)<br>Enemy.SetState 0x715285, command_init 0x7231b4, command_got_up 0x722e07 | enum ENEMY: INACTIVE, CHASING, IDLING, ATTACKING, FOLLOW_PIVOT, BRAINLESS_AUTOTARGET, HANG_BACK, RETURN_TO_COMBAT_ZONE, TWILIGHT_LADY_BACK_FLIP, STEP_BACK<br>EnemyDef: m_nattackdistance 4.0, m_thashangback, m_nhangbackhealthprocent 30, m_nhangbackifalone | **partly understood** | Evaluate skimmed (rules below are partly inferred); StateActive call list | 44 fn, 20 kB |
| c3 | Deterministic Reaction System: block / dodge / counter in answer to the player's attack pattern | Enemy.command_react_to_attack 0x721958<br>Enemy.ClearReactHistory 0x717376<br>AILib.SetGoodDodgeDir 0x59c080 | EnemyDef m_idrsNNattackMM / m_idrsNNresult / m_tdrsNNshouldclear, m_nreactiontoattackdecaytime 4.0 | **understood now** | read from code; data decoded | 2 fn, 2 kB |
| c4 | Attack choice: fast / slow / combo | AttackEnemy.command_may_attack 0x600246, FindUsableCombo 0x600730, TryAddComboToList 0x5eee3a<br>CharacterAIComboManager.StatePerformCombo 0x64a400<br>AILib.MayAttack 0x59c402, AttackPathClear 0x59ce06 | EnemyDef m_nproboffastatt 0.8, m_nprobofslowatt 0.2, m_nprobofcomboatt 0.5, m_ecomboattack1 "[F][dodge][H]" freq 1, m_ecomboattack2 "[F][F][H]" freq 3, m_ntimebetweenattacks 1.8-3.0 s | **partly understood** | may_attack read; FindUsableCombo and the combo manager not read | 8 fn, 7 kB |
| c5 | Sub-behaviours: chase, attack loop, idle, hang back, step back, return to combat zone, follow pivot, leader, circle target, secondary attacker *Known: which commands each behaviour issues (movement requests, attack requests, speak events). Not read: the geometry (where she stands, side-step, circling), speed selection, timers.* | Enemy.command_init 0x7231b4 (creates BehaviorIdle, BehaviorChase, AttackEnemy, hangback, LeaderEnemy, ReturnToCombatZone, TwilightLadyBackflipBehavior, BehaviorStepBack, FollowPivotBehavior)<br>AttackEnemy.command_init 0x5ff00b (creates CircleTargetEnemy02, SecondaryAttackerEnemy, BehaviorEnforceSameHeight)<br>BehaviorChase.StateActive 0x617146<br>AttackEnemy.StateActive 0x5ff3d6<br>hangback.StateActive 0x75e618<br>BehaviorStepBack.StateActive 0x61abb3<br>ReturnToCombatZone.StopAndTaunt 0x7ff5f5, RunBackToZone 0x8006c9<br>FollowPivotBehavior.StateActive 0x73a1af<br>BehaviorEnforceSameHeight.StateActive 0x617c70<br>CircleTargetEnemy02, SecondaryAttackerEnemy, LeaderEnemy, BehaviorIdle | EnemyDef m_nchasedist 3.0, m_nwaittomovetime 1-5 s, m_nsidesteptime 2.0, m_nhangbacktime 2-10 s, m_nhangbackdistance 6-10 m | **partly understood** | call lists only | 215 fn, 52 kB |
| c6 | Perception: known enemies, visibility, tactical info | Perception (reg 0x7e9dcd): UpdateKnownEnemies 0x7dc536, AddNewKnownEnemies 0x7dcc88, UpdateTacticalInfoForEnemy 0x7dd352, command_tactical_query 0x7dbd52<br>CharacterAIBrain.command_get_target 0x64956f (3.6 kB) | Perception.m_ntacticalinformationupdatetime 0.5 s<br>AIBrain: eyePos (0,1,0), maxVisibilityHalfAngleDeg 90, maxVisibilityDistance 30; EnemyDef m_nvisualrange 34 | **partly understood** | call lists only | 38 fn, 14 kB |
| c7 | Combat orchestrator: who may attack, attack slots, target choice between the two players | CombatOrchestrator (reg 0x6fbb4f): StateActive 0x6e8231, command_request_attack 0x6e5ca7, command_register_attack 0x6e620c, command_choose_target 0x6e3f26, ShouldSwitchTarget 0x6da85a, command_change_target 0x6e430e, LockTarget 0x6e9541, command_release_attackers 0x6e388e<br>CombatOrchestratorParameters.command_trig 0x6d9128 | GameEssentials.fragment CombatOrchestrator: engagement 8 m, runners clamp 5, cooldown 2.0, max attacks 3, frequency 0.2, idle 0.1<br>combatorchestratordefaults.fragment: Level 001..006 | **partly understood** | choose_target and ShouldSwitchTarget read; grant loop located, not read | 59 fn, 31 kB |
| c8 | AILib helpers (reachability, facing, bell curves, breadcrumbs) | AILib (reg 0x5a38ee): IsReachablePosition 0x5984a9, FindClosestTargetWithTacticalOptions 0x59d1ad, IsPosBehind, IsAFacingB, DoBreadCrumbNavigation, BellFactor | - | **not understood** | names only | 28 fn, 7 kB |
| c9 | Script side of navigation: brain node, velocity hand-over, AI world | CharacterAIBrain (native base AIBrainNode)<br>KynapseCharacter.StateActive 0x770d27<br>AIWorld (AIWorldNode): TraceLine, IsInsideMesh | AIBrain template props: maxSpeed 5, pathSearchRadius 50, biped dynamic avoidance (look-ahead 8 m x 4 m, 360 deg/s, 0.1 s)<br>BordelloAIPath.aipathdata; 19 AIPathDataSeedPointNode | **partly understood** | data read; call lists | 21 fn, 10 kB |
| c10 | Kynapse bridge (engine side) *Needed to say which Kynapse services run (path finding with which constraint, biped dynamic avoidance, visibility) and what the script receives each frame.* | ai.glue 0x482deb-0x48d2a8: AIBrainNode, AIWorldNode, KynapseNPCBrain / Action / Entity, path objects, KynapseSkel IO | .aipathdata | **not understood** | not read; findings/submap.md | 306 fn, 43 kB |
| c11 | Kynapse middleware *Only the used interface needs reading, not the library.* | Kaim:: 0x908fe0-0x97d429, 0x9a91e0-0x9bbc58 | - | **not understood** | not read; third-party; findings/submap.md | 2475 fn, 534 kB |
| c12 | Global difficulty setting *Not established whether the preference changes anything for enemies. Size unknown until a consumer is found.* | enum PREFERENCES_GAMEDIFFICULTY (EASY / NORMAL / HARD) registered in builtin.cpp 0x47ff8c | per-encounter knobs in data: SET_AI_DEF_PHASE, CombatOrchestratorParameters levels, SET_INCOMING_DAMAGE_FACTOR | **not understood** | no consumer found by name search | - |

Architecture (read from code and data): the `BehaviorHandler` holds root behaviours; hers is `Enemy`.
`Enemy` owns nine sub-behaviours and a state (`ENEMY` enum). `Enemy.StateActive` runs every frame,
calls `Evaluate`, keeps the target (`Perception` and `CombatOrchestrator`), fires engagement and taunt
speak events, and gives focus to the sub-behaviour of the current state. Sub-behaviours ask for
movement with `CharacterRoot.command_set_movement` / `command_set_move_speed` and for attacks through
the `CombatOrchestrator`, which decides who may attack. Path following comes from Kynapse through the
`AIBrain` node; `KynapseCharacter.StateActive` 0x770d27 turns the brain's velocity into the same
movement request.

**State choice, `Enemy.Evaluate` 0x72587d (skimmed; the conditions marked * are inferred from the
shape of the code, the member names are exact).** Dead: nothing. A forced state from a trigger wins
(`AILib.CheckForcedState`); in `FOLLOW_PIVOT` the pivot must be reachable. Otherwise the default is
`IDLING`. No target or a dead target: `IDLING`. `STATE_OF_MIND` `AGGRESSIVE` and outside the home
turf: after `m_nforcereturntohometurftimer` the `ReturnToCombatZone` behaviour is forced*; while
outside the turf a target further than `m_nmeleemaxdistance` (4.5 m) is not chased*. Hang back: if
the definition has `m_thashangback`, and her health is below `m_nhangbackhealthprocent` percent of
maximum (30), and the target is not herself, and the target has at least two attackers or
`m_nhangbackifalone` is set, then `_nhangbacktime` = now + `BehaviorHandler.command_get_hang_back_time`
and the state is `HANG_BACK`*. Otherwise with d = distance to the target: if d is within twice the
attack distance, and d is below the attack distance, and no AI-mesh edge lies between the two
characters (`command_is_trace_line_between_characters_crossing_ai_mesh_using_breadcrumb`), the state
is `ATTACKING`; if she is already `ATTACKING` and may not start running (the orchestrator's count of
moving characters has reached `m_irunningcharactersclamp`, 5, and her own speed is 0) she stays
`ATTACKING`; else `CHASING`. A change goes through `SetState` 0x715285. One more rule at the top: an
`AGGRESSIVE` character whose breadcrumb timer has been running for more than 2.0 s and whose position
stays unreachable for another 10 s is killed (`command_uberkill`, then `command_give_damage` with
100000)*; constants 2.0 at 0xc3cc78, 10.0 at 0x9e5c60, 100000 at 0x9eba80.

**Deterministic Reaction System (c3, read from code; data decoded).** `Enemy.command_react_to_attack`
0x721958 is called when an attack is about to land on her (attacker's `PRE_IMPACT` ->
`command_hit_soon` -> `BehaviorHandler.command_when_attacked`). The Twilight Lady branches to her own
routine. For everyone else: if more than `m_nreactiontoattackdecaytime` (4.0 s) passed since the last
entry, the history is cleared. If she is not stunned or prone, the `ANIMATION_TYPE` of the attacker's
current state (4 `LIGHTATTACK`, 5 `HEAVYATTACK` ...) is written into a 9-entry ring (`_ihithistory`).
Then each of the five reaction rows of her `EnemyDef` is compared with the ring, newest entry first;
17 (`AI_SYSTEM_ONLY__ANY_ATTACK`) matches anything, and a row needs as many past attacks as it has
entries. The first matching row fires its result: 6 `BLOCK` -> `command_block`; 7 `DODGE` ->
`AILib.SetGoodDodgeDir` then `command_dodge` and a forced re-evaluation; 8 `COUNTERATTACK` ->
`command_block` then `command_delayed_counter_attack(0.15 s, attacker)` (0.15 at 0xa11984). A row
with "clear when fire" empties the ring. Her rows, identical in both definitions:

| row | newest ... oldest | result | clear |
|---|---|---|---|
| 1 | light, light, light, any | counter-attack | yes |
| 2 | heavy, heavy, heavy, any | counter-attack | yes |
| 3 | heavy, heavy, heavy | dodge | no |
| 4 | light, light, light | dodge | no |

So the third identical attack in a row is dodged, and if a fourth attack follows three identical
ones she blocks it and counters, and the count starts again. The gate in front of the table (read): she force-locks her
target onto the attacker (`command_force_lock_target`, self slot 0x58) and reacts only if that
succeeded, the attacker is not doing an unblockable attack (`m_tdoingunblockableattack`), and
`Perception.command_tactical_query(attacker, 0x400)` returns 0 (meaning of flag 0x400 not
established). No random number is drawn in this handler; where `m_nprobofreactatt` (0.62) and
`m_nprobofdodge` (1.0) are used was not found.

**Attack choice (c4, `AttackEnemy.command_may_attack` 0x600246, read).** When `AILib.MayAttack`
allows and the line-of-attack timer has passed: if a combo was decided (`_tdocombo`) and she is not
already attacking, `FindUsableCombo` picks a combo string and `command_perform_combo(combo,
5.0 x length)` starts it. Otherwise one random number r in [0,1): r < `m_nproboffastatt` (0.8) ->
`command_attack_fast`, else `command_attack_slow`. Afterwards she speaks `MELEE_ON_TARGET_A` when the
target is Rorschach (type 0) and `MELEE_ON_TARGET_B` when it is Nite Owl (type 1). Her combo list
(data): "[F] [dodge] [H]" with frequency 1 and "[F] [F] [H]" with frequency 3 out of the "Enemy
Combos" database. Not read: where `_tdocombo` is rolled (`m_nprobofcomboatt` 0.5), how the
frequencies weight the choice, and the combo manager's timing.

**Target choice between two players (c7, read).** `CombatOrchestrator.command_choose_target`
0x6e3f26 walks the perceived enemies, skips those `AILib.ShouldAcquireNewTarget` rejects, takes the
first as candidate and replaces the current choice when `ShouldSwitchTarget` 0x6da85a holds: the
candidate has fewer attackers than the current target's attacker count minus 2. So attackers spread
over Rorschach and Nite Owl with a hysteresis of two. The orchestrator's grant loop (who of the
waiting attackers gets a slot) uses `_imaxnumberofattacks`, `_nattackcooldown`, `_nattackfrequency`,
`_nidletime` and `_nattackwaittime` (sites 0x6e8231+), fed by `CombatOrchestratorParameters`
(`command_trig` 0x6d9128) with six presets "Level 001" (cooldown 4.0, 2 attacks, frequency 0.5, idle
1.5) to "Level 006" (2.0, 4, 0.2, 0.1); the loop itself is not read.

Difficulty: the only difficulty knobs found are per encounter and in data (AI definition phases, the
orchestrator presets, `SET_INCOMING_DAMAGE_FACTOR`, `SET_MIN_HEALTH`). An enum
`PREFERENCES_GAMEDIFFICULTY` (EASY, NORMAL, HARD) is registered, but no reader was found by name.

### d. Combat mechanics

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| d1 | Attack start, attack queue, combo timing | CharacterRootLogic.command_start_animation_state 0x688961 (6.7 kB), InitializeNextAttack 0x68bf6f, FireAttackBasedOnAttackID 0x68d870, ExecuteAttack 0x68b351, AddAttackToCombo 0x68bca8, command_update_combo_timing 0x68810a, StartUpSpecialAction 0x68cec1<br>CharacterRoot.command_attack_fast / _slow / command_perform_combo, SendAttackDistToAnimationCtrl 0x69640d | CharacterDef m_nheadattackdistance 0.04, m_nbodyattackdistance 0.1 | **not understood** | names only | 16 fn, 24 kB |
| d2 | Animation events that make a hit (PRE_IMPACT, IMPACT, IMPACT_EFFECTS, BRANCH ...) | CharacterRootLogic.command_animation_event_received 0x6a525e (37.7 kB)<br>sender CheckPlayPosEvents 0x5b51f3 | AnimationEventWM nodes in Enemy04AttackFragment (277 events) | **understood** | read from code (ten cases skimmed); re/events.md | 1 fn, 38 kB |
| d3 | Building the damage record at impact *Known: inputs and order (pose from the state, turned by direction, size and height; electrified armour; block branch; counter branch; weapon durability). Not read: the exact damage formula and the three pose manipulators.* | CharacterRootLogic.SetCloseCombatDamageToTarget 0x6ae57f (5.1 kB)<br>ProjectAnimationLib.DirectionManipulateDamage 0x802ae8, SizeManipulateDamagePose, HeightManipulateDamagePose<br>CharacterRoot.command_get_damage_modifier 0x6931a4 | AnimationStateWM.m_idamagepose; CharacterComboDatabase default damages (fast 5 / heavy 10 unarmed, 12 / 20 with 1H weapon); damage modifier 1.5 | **partly understood** | skimmed; ENGINE_CONSTANTS.md 2026-10-04 (inputs of the face) | 4 fn, 6 kB |
| d4 | Applying a hit to her | CharacterRoot.command_give_damage 0x691b10 (4.4 kB)<br>CharacterRoot.command_hit_soon 0x6903ea<br>CharacterRoot.command_set_stun_time 0x691389, command_set_push_back_data 0x691325, command_do_recoil 0x6902c0 | - | **understood now** | read from code | 5 fn, 7 kB |
| d5 | Health, critical state and the finisher prompt | CharacterRoot.DecreaseHealth 0x695632 (3.0 kB)<br>CharacterRoot.IsAIPartner 0x678254<br>CharacterRoot.UpdateHealth 0x678288 (1.5 kB, not read: regeneration, end of the finisher window) | CharacterDef m_ncriticalhealth 44, m_nfinishicontime 3.0, m_nmaxhealth 100, regen 0<br>template sprites FastSprite / HeavySprite / ThrowSprite / DodgeBlockSprite + SpriteWobbler | **understood now** | DecreaseHealth read; UpdateHealth not read | 3 fn, 5 kB |
| d6 | Her block, dodge and counter moves; the player's counter window against her *When she decides to block or dodge is understood (c3); what the move then does (windows, block breaker, counter eligibility) is not.* | CharacterRootLogic.command_block 0x686e56, command_dodge 0x686a17, TestForCounterAttack 0x68d36a, command_force_counter_attack 0x6867b7<br>CharacterRoot.command_give_block_damage 0x692c3f, command_block_timed 0x690c0e, command_delayed_counter_attack 0x68fe34 | EnemyDef m_nprobdodgethrow 0.4 / 0.8 | **not understood** | call lists only | 8 fn, 9 kB |
| d7 | Combo database | CharacterComboDatabase, CharacterComboString, CharacterComboItem, CharacterComboDef | CharacterDef.fragment "Enemy Combos": 4 strings; default damages 5/12/15 fast, 10/20/25 heavy, counter 10, throw 10 | **partly understood** | data read; code not read | 19 fn, 4 kB |
| d8 | Stun, knockdown, prone, getting up | dynamic_getup_logic (reg 0x72abb8): command_start_getup 0x728e00, solveStaticObject 0x71b44c, VerifyCharacterLocation 0x7156e4<br>CharacterVisual.VerifyCharacterLocation 0x6a01d4, solveStaticObject 0x6a10cb, staticDynamicOverlap 0x6a0a60<br>Enemy.command_got_up 0x722e07 | Enemy04RagdollGroup.fragment (prone states, get-up clips) | **not understood** | names only | 14 fn, 12 kB |
| d9 | Death, corpse, clean-up | CharacterRoot.StateDead 0x6bb12a (4.6 kB)<br>CharacterRoot.deinitialize 0x69476d, command_delete 0x69498f, DeleteSubSystems 0x696e73<br>CullingCtrl.command_get_culling_visibility_group 0x70d69a | - | **understood now** | skimmed | 5 fn, 6 kB |
| d10 | Ragdoll hand-over and recovery (animation <-> physics, powered ragdoll) *Known: what a state asks for (muscle power per joint, blend-in time, which bones are physics-driven). Not read: how the ragdoll update and the muscle-orientation handlers apply it, the transfer in both directions, impact thresholds.* | CharacterVisual.command_update_ragdoll 0x6bc3e2 (10.1 kB), StateRagdollDriven 0x69ed7c, command_activate_ragdoll 0x69eac6, ModelCollisionContactAdded 0x69d00a, command_start_transfer_to_animation_control 0x6b09d9<br>AnimationCtrlWM.CharacterTransferToRagdollControl 0x5b16ed (3.9 kB), MuscleOrientationRagdoll 0x5ba03b, MuscleOrientationAnim 0x5acd3c, CharacterRagdollAnimTransferControl 0x5b9c8f<br>BehaviorAnimation.StateActive 0x615ed3, LookupMusclePowerScale 0x614dd4<br>CharacterRoot.command_give_ragdoll_damage_increment 0x6914f2<br>characterlib ragdoll helpers 0x6650bf, 0x66b43d, 0x664e1a | CharacterVisualDef: ragdoll impact triggers 6000 / 2000 / 500, decrease 2500/s<br>BehaviorAnimation(WM) nodes on states: m_ndefaultmusclepower, m_nextramusclepower, m_nmuscleblendintime, m_iselectedbones, 16 joint scales | **partly understood** | BehaviorAnimation read; the rest call lists | 22 fn, 32 kB |
| d11 | Ragdoll construction (bodies, joints, limits, masses) *The per-joint limits and masses are in code, not data: a ragdoll export needs this function read.* | CharacterRagdollSetup: CreateJointInfo 0x6846e8 (7.6 kB), JointLimits 0x683d12, CreateBoneInfo 0x682c60, BoneMasses 0x683545<br>native ArticulatedBody (articulatedbody.cpp) | CharacterVisual.fragment: CharacterRagdollSetup m_ntotalmass 85, linear damping 0.5, angular 2.5<br>Female_Skeleton.model collision volumes (32) | **not understood** | names only; re/skeleton_blobs.md (the volumes) | 7 fn, 15 kB |
| d12 | Paired moves on her: counters, finishers, throws, disarm *FinishOrStompEnemy 0x677c93 (who is allowed to start a finisher) not read.* | AnimationCtrlWM goto_slave_mode 0x5b32a2, UpdatePagePlayPos 0x5b56a9<br>CharacterRoot.command_goto_slave_mode 0x693b2e, command_leave_slave_mode 0x693a09, command_request_me_as_dual_animation_partner 0x693d5f | Master-of table; NTO_/RSH_ ..._EN4_* clips | **understood** | read from code (earlier rounds); re/placement.md; ANIMATION_META.md | 6 fn, 2 kB |
| d13 | Sweep (area) attacks that can hit her *She does not own one; she is a potential target of the players' and the boss's area attacks.* | CharacterSweepAttack.StateActivePlayPos 0x698fe1 (5.5 kB), DoEnemyCheckAgainstTravelLine 0x69a57d, command_begin_sweep_attack 0x698a43<br>CharacterRootLogic.command_sweep_target_detected 0x6879ed | no CharacterSweepAttack node in the Enemy04 fragments | **partly understood** | hit test read; the stepping loop not read | 11 fn, 9 kB |
| d14 | Remaining small CharacterRoot commands (queries, rage / electrify bookkeeping, movement setters, teleport, slave helpers) | CharacterRoot: ~150 handlers under 700 bytes | - | **partly understood** | about a third read in passing | 150 fn, 24 kB |

**Applying a hit, `CharacterRoot.command_give_damage` 0x691b10 (read).** Argument: a damage record
{attacker, damage pose, amount, stun time, push-back vector and time, direction, impact position,
flags}. Ignored when health is 0, the root is a placeholder, or damage state is 1. Steps: tell the
attacker (`command_you_hit_me`); stop her own combo (`command_kill_combo`); unless she is in slave
mode with someone other than the attacker, call `DecreaseHealth` (below), which returns "dead";
credit the signed-in player (`AchievementPart2Ctrl.command_damage_by_signed_in_player`, combo-string
bookkeeping); add rage to the attacker (amount times a global factor, a different one while in rage)
and to the victim; stop her speech with a quarantine (`SpeakCtrl.command_stop_speak_and_quarantine`);
play the damage effect (`CharacterEffectDef.command_play_damage_effect`, section i); set the ragdoll
impulse direction. Not dead: camera recoil when the attacker is a player; for knockdown poses (13 -
18, 27, 28) slow motion (`WorldLib.SetTimeMultiplier(_nslomotimemultiplier)`); stun time if the
record's is longer than what is left; push-back. Dead: slow motion is reset, and when a player
killed her with a heavy, knockdown or stun pose, an FOV kick, a camera shake (0.04) and slow motion;
`command_enemy_killed_by_signed_in_player`; `command_you_killed_me` to the attacker; ragdoll impulse
and push-back from the hit direction. Always: fire `HITTAKEN` (action 2) and set `DAMAGE_POSE` (enum
4) on the head controller and on the body controller (the body also gets action 14); notify the AI
(`BehaviorHandler.command_hit_by`); lock her target on the attacker (`command_force_lock_target`)
and set her aggressive. One special case at the top: when `CharacterRootLogic.m_treversedirection`
is set and her animation play position is between 0.5 and 0.8, the damage pose is cleared to 0
(what sets that flag was not followed).

**Health and the finisher prompt, `CharacterRoot.DecreaseHealth` 0x695632 (read).** Damage =
`m_nincomingdamagefactor` x amount. No damage when `m_tinvulnerable` or damage state 1. Health is
reduced and stamped (`m_nlasthittime`). If `IsAIPartner` (0x678254, self slot 0x264) holds and
health fell to 0 it is set back to 1: the AI partner cannot die; this does not apply to her.
Critical state: when health drops below `m_ncriticalhealth`
(44) for the first time (`m_nstartcriticaltime` < 0), she was above it before the hit, and the
attacker is a player, the time is stamped, the four button sprites are disabled, and one button is
drawn at random (up to ten tries so that it differs from `PlayerCtrl.m_ilastbuttonpressed` of the
attacker): ids 0x1c, 0x15, 0x16, 0x17 select the dodge, fast, heavy and throw icon
(`CharacterPhysics.m_estoreddodgeicon` ...), which is enabled with the player's button text; the choice is logged
(`command_log_finishing_move_allowed`). The window lasts `m_nfinishicontime` (3.0 s); its expiry, and health regeneration, are in
`UpdateHealth` 0x678288, which was not read. Health is
clamped to `m_nminhealth` when that is set. Alive: game event with attacker and amount; dead: health
0 and the death game event. (The same function has an Underboss branch and a player-versus-player
branch not relevant here.)

**Death, `CharacterRoot.StateDead` 0x6bb12a (skimmed).** Speaks `DEATH` unless `m_tnodeathscream`;
deletes the template fragment (`DeleteCharacterRootFragment` 0x67625b: capsule, brain, behaviours,
logic); unregisters from `CharacterLodCtrl` and the `CombatOrchestrator`; drops the weapon; resets
collision groups; restores the time multiplier. While the ragdoll's mean velocity is above 0.01
(0x9e5fac) the body and head pose are refreshed each frame only if she is in a camera frustum
(`IsInFrustrum` 0x6781a3 -> `UpdateBodyAndHead` 0x678156); there is a height test at -100 for bodies
that fell out of the world. Once at rest: the remaining child scripts are terminated or disabled, the corpse is re-parented to the culling
visibility group of the room it lies in (`CullingCtrl.command_get_culling_visibility_group`, a ray
cast), the animation controllers are stopped, `Character::SetFreeze(1)` freezes the pose, the
articulated body is cleared and physics deleted. The corpse stays as a frozen skinned mesh for the
rest of the level; nothing fades. `FREEZE_ACTIVE_RAGDOLLS` trigger actions (7 in the level) force the
same early.

**Powered ragdoll (d10, `BehaviorAnimation.StateActive` 0x615ed3 read; the consumers not).** States
in the animation class can carry a `BehaviorAnimation` node (6 + 6 in her class, most in the ragdoll
group). While its state is active it writes, for each ragdoll joint, a muscle power =
`m_ndefaultmusclepower` x the joint's scale, an extra power and a blend-in time into the animation
controller's joint list, and marks the bone types selected in `m_iselectedbones` as physics-driven.
The values range from 0.9 to 180 in her data. How `CharacterVisual.command_update_ragdoll` and
`AnimationCtrlWM.MuscleOrientationRagdoll` turn these into joint motors is not read.

**Sweep attacks (d13, hit test read).** `CharacterSweepAttack` describes an arc by three vectors and
samples it `m_nchecksprsec` (10) times per second of the attack animation. For each step,
`DoEnemyCheckAgainstTravelLine` 0x69a57d takes the segment travelled, finds for every potential
target the closest point on it (`MathLib.ClosestPointToLineSegment`), and when the target is within
0.8 m (0x9ea130) reports it to `CharacterRootLogic.command_sweep_target_detected` with the travel
direction. All other melee hits are not geometric: `PRE_IMPACT` checks the locked target and a range
(1.8 m, 2.2 m for big attackers; events.md) and `IMPACT` builds the damage record.

### e. Movement and physics

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| e1 | Character controller: script side *StateCharge and StateGrapplingHook (11.8 kB) are player-only and left out of the size.* | CharacterPhysics (reg 0x6beb83): command_attempt_move 0x67d52c -> native CharacterController::Move; DccUpdate 0x680654, DccJoint 0x6a3d71, command_detect_wall 0x67b508, command_goto_animation_mode 0x6a32ce / 0x67bd36, command_absolute_update 0x67f7b0, StateOnGround 0x67d2a5, StateRagdoll 0x68012e, FeedBack 0x681e7b, CollisionContactAdded 0x67c845, command_activate_collision 0x67cc00 | template: capsule width 0.8, height 2.0, m_ninitsteplimit 0.3, RigidBody mass 100, WorldJoint D6 (orient motor 5000) | **partly understood** | call lists; goto_animation_mode read earlier for pairs; re/placement.md (absolute mode flag) | 55 fn, 41 kB |
| e2 | PhysX wrapper: controller, actors, joints, articulated body, queries, contact reports *The figure includes database code linked into the same block (submap section 2).* | kernel/collision 0x4f4ddc-0x524f47 (physx_charactercontroller.cpp, articulatedbody.cpp, physx_trigger.cpp ...)<br>NxCharacter.dll, PhysXCore.dll | - | **not understood** | not read (except the jiggle joint path and the step); re/jiggle.md; re/physx_d6.md | 1192 fn, 163 kB |
| e3 | Expand volume and follow pivot (soft body pushing others away) | CharacterExpandVolume.updateJoint 0x66d0ec, Main 0x6680f4<br>CharacterVisual.command_init_expand_volume 0x69f924 | template: ExpandVolume capsule 0.08 x 0.2, FollowJoint (linear limit spring 200, damping 25), FollowPivot box | **not understood** | names only | 6 fn, 2 kB |
| e4 | Auto-align and absolute mode in pairs *Bytes counted under b4.* | CharacterRoot.StateActive placement block | - | **understood** | read from code (earlier round); re/placement.md | - |
| e5 | Collision volumes on the skeleton | Node::Deserialize 0x545927 | Female_Skeleton.model: 32 volumes | **understood** | read from code, validated; re/skeleton_blobs.md | 2 fn, 3 kB |
| e6 | Jiggle (breast, belly bones) *Hair is open in the docs (no capture).* | CharacterAddonCtrl 0x6574cd, 0x648858, 0x6563a0<br>PhysXCore.dll D6 soft limit | En4CharVisual.fragment AddOnCtrl | **understood** | read from code, validated on captures; re/jiggle.md; re/physx_d6.md | 6 fn, 9 kB |
| e7 | Cloth *Inferred from the fragment that the cloth path is idle for her.* | CharacterRoot.initializeCloth 0x678021, setClothPhysicsBlendFactor 0x6780e3<br>physx_cloth.cpp, clothupdatejob.cpp | En4CharVisual.fragment has no cloth node | **partly understood** | data: she has none; code not read | 2 fn, 310 B |

### f. Animation

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| f1 | State machine, pages, transitions, sync, criteria, overlay pages *Not covered by the docs: PostUpdate 0x5cab6b (4.2 kB), command_model_changed 0x5b33d4, the ragdoll transfer handlers (counted in d10).* | AnimationCtrl / AnimationCtrlWM, AnimationState(WM), AnimationStateGroup(WM), AnimationTransition(WM), AnimationCriteria(WM), AnimationBlend(WM), AnimationSlot(WM), AnimationLib | AnimationClassEnemy04.fragment and the eight Enemy04* fragments: 270 states, 411 transitions, 668 events | **understood** | read from code, interpreter validated on captures; ENGINE_CONSTANTS.md; re/pages.md; re/sync.md; ANIMATION_META.md | 330 fn, 120 kB |
| f2 | Native animation runtime: clip decode, layers, slots, blend sources, pose, bone controllers *Open in the docs: the pose term on type 1 / 3 tracks, AnimLayer / AnimBlendSource internals.* | kernel/animation 0x591225-0x596d7b | Animation/EN4/**.animation, FACE clips | **partly understood** | behaviour reproduced by the baker and checked against captures; internals not read; ENGINE_CONSTANTS.md; findings/submap.md 3.4 | 237 fn, 28 kB |
| f3 | Face class and its inputs | CharacterHeadCtrl (reg 0x671099)<br>CharacterVisual.command_update_animation 0x69b988 | AnimationClassEnemy04Face.fragment | **understood** | read from code; findings/face.md; ENGINE_CONSTANTS.md 2026-10-04 | 25 fn, 11 kB |
| f4 | Head look-at *Bytes counted under f3.* | CharacterHeadCtrl.UpdateHeading 0x66a5ae, UpdatePitch 0x66ab44, ApplySteeringForce 0x6646c3 | HeadCtrl: _nmaxheading 1.3, pitch disabled, mass 0.05, max force 400, max speed 12 | **understood** | read from code; findings/face.md 1.5 | - |
| f5 | Per-frame animation inputs from the character (values, enums, attack flag, LOD of the update) | CharacterVisual.command_update_animation 0x69b988 (3.9 kB), command_update_animation_fast 0x69b87d, UpdateAnimPoseAndCloth 0x6b015d<br>AnimationCtrlWM.IsShownOrClose 0x5ab2ac<br>CharacterRoot.UpdateAnimationValues 0x69620b | - | **partly understood** | face inputs read earlier; the rest call list; findings/face.md | 5 fn, 8 kB |
| f6 | IK / foot placement / additive layers *Feet are not corrected; footsteps are events only.* | - | strings and class list searched: no IK class, no foot-plant string; BoneController only attaches | **understood now** | inferred from absence | - |

Checked against her data: nothing she uses in the state machine falls outside the documents (states,
blends, slots, transitions, criteria, events, sound-event fragments, face). The two things her
animation class contains that no document describes are the `BehaviorAnimation` muscle nodes (d10)
and the handlers that pass control between animation and ragdoll. There is no IK and no foot
correction in the executable.

### g. Rendering

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| g1 | Scene nodes that draw her: Character, Model, render instances, bounds | kernel/scenegraph visual nodes (model.cpp, character.cpp ...) | CharacterVisual(Character) props: castShadow, includeInReflections, boundsFixedSize 2.5, geometryLodFactor 1.0, opacity | **not understood** | not read | 545 fn, 77 kB |
| g2 | Room culling (script) and occlusion *Known: corpses are re-parented to the room's visibility group (d9). Not read: the inside test and the per-viewport cull.* | CullingCtrl.Culling 0x70e0a4, InsideTest 0x7111b9, command_viewport_render_begin 0x70dba6, CullUncullSplit 0x7052b9<br>ViewportNodeManager, ViewportRenderHandler | Art.fragment: CullingGroup, CullingVisibilityGroup(PVSRootNode), CullingBox; PVS/*.fragment per room | **partly understood** | call lists; data | 33 fn, 6 kB |
| g3 | Model LOD, material LOD *Bytes inside g1 / g5.* | not located | GFX node: globalGeometryLodFactor 1.0, geometryLodMode 0, min/max material LOD 2/0<br>model header LODs | **not understood** | not located in code; WATCHMEN_EXTRACTION_MASTER.md (LOD in the file) | - |
| g4 | Skinning *GPU skinning, 70 bones of 3x4. Who fills the palette and when (the "skin" job) is not read.* | DepthVS[SKIN], DeferredMain2VS[SKIN], ShadowVolumeVS[SKIN], ShadowMapVS[SKIN] | vertex format 6: 4 indices in COLOR1, 4 weights in TEXCOORD3; $skinning = c40, 210 registers | **understood now** | read from shader bytecode; findings/vcolor.md | 4 shaders |
| g5 | Render pipe on the CPU: pass order, render effects, material -> effect routing, light assignment, shadow volume construction, transparency sorting *No function in this block has a semantic name.* | kernel/rendering 0x565e7e-0x590897: MasterRA 0x565e7e, DeferredRA 0x574f74, RenderPipe 0x56f057, RenderEffectManager 0x572a7b, REDeferredMain2 0x570d06, LightConfigurationManager 0x588ade | - | **not understood** | variant selection read (vcolor.md); the rest not; findings/vcolor.md 4 | 673 fn, 185 kB |
| g6 | Colour pass (REDeferredMain2): lighting, specular, fog, vertex colour | DeferredMain2VS (12 variants), DeferredMain2PS (16 variants) | texture sheet switches (sheet.json) | **understood now** | read from shader bytecode; findings/vcolor.md | 28 shaders |
| g7 | Light buffers $LIB / $LAB / $LPT / $LCT *How lights are sorted into the four layers and indexed on the CPU is in g5.* | DeferredLightLayerVS, DeferredLightLayerPS (16 variants) | - | **understood now** | read from shader bytecode (pixel side) | 17 shaders |
| g8 | Shadows: stencil volumes and shadow maps | ShadowVolumeVS (6), ShadowMapVS (4), ShadowMapPS (2), ShadowFilterPS (3)<br>REShadowVolume | shadow hull vertex formats 9 / 10; GFX node shadowMaxRange 25, shadow biases | **partly understood** | formats read; shaders present, not read; CPU not read; re/formats.md | 15 shaders |
| g9 | Material terms: glow, reflection, falloff / rim, wet surface, normal-map power | DeferredMain2PS variants ALL_ADDITIONAL_FEATURES, CUBEMAP_REFLECTION, PLANAR_REFLECTION, FALLOFF, WET_SURFACE | sheet.json: normalMapPower, renderType, opacity | **partly understood** | described in vcolor.md; variants other than SPECULAR;TANGENTSPACE not read line by line here; findings/vcolor.md 2 | - |
| g10 | Hair and alpha: which effect draws her hair, sorting *The capture showed only REDeferredMain2 for models; whether any Dominatrix hair sheet routes to REHair is open.* | HairVS (2), HairPS (2); REHair | hair models GoGoWhite_HairLayered1/2, Fimale_Gimp_Hair | **not understood** | not established; findings/vcolor.md 7 | 4 shaders |
| g11 | Two-sided materials, culling mode, winding, alpha test | 0x56bcb8 (pixel variant choice) | sheet+0xA4 two-sided; alphaThreshold | **understood** | read from code and bytecode; findings/vcolor.md 5 | 2 fn, 800 B |
| g12 | Post-processing: depth-edge AA, bloom, brightness / saturation / contrast, tint, gamma, DOF, noise *No motion-blur shader exists in the archive.* | PostProcessPS (9 variants), BloomRenderPS, BloomControlFilterPS, AddBloomPS, DownScale2x2PS, GaussianBlurPS<br>RenderEffect base 0x57d030<br>FXGfxEffectCtrl (script, per player) | Art.fragment "RS GFX" / "NO GFX": bloomWeight 0.2, contrast 0.22, Saturation 0.0, tint (0.54,0.69,1.0) power 0.3, gamma 1.2, enableAA, DOF off, fog 0-80 m | **partly understood** | PostProcessPS[AA] and BloomRenderPS read from bytecode; CPU chain and FXGfxEffectCtrl blending not read | 15 fn, 4 kB |
| g13 | Target highlight *A cloned texture sheet per render instance, not an outline pass.* | FxHighlightCtrl: command_highlight_def 0x73d682, AssignOverrideSheets 0x73da49, BlendOverrideSheets 0x73613c, StateMain 0x73d0e5 | GameEssentials.fragment: two FxHighlightDef "Highlight_CharacterTarget" (ids 1, 2), blend in 0.001 s, out 0.2 s, self-illumination 0, bloom 0 | **partly understood** | AssignOverrideSheets read; blend not read | 10 fn, 4 kB |
| g14 | Decals and blood on characters; fade on spawn / death *Nothing found that paints on a skinned mesh; not proven absent.* | DecalManager (decalmanager.cpp), GFXDecalEffectType | opacity 1.0 on the character nodes | **partly understood** | inferred from the API (world-space SetDecal) and from StateDead (no fade) | 176 fn, 38 kB |
| g15 | Graphics device layer | Gfx / GfxDX9 0x42dd56-0x43509b, 0x456c6a-0x45c3d1; shader archive reader 0x43398e | derived_pc/precompiled_shaders/shader.archive | **not understood** | archive format read; device layer not; findings/vcolor.md 1 | 520 fn, 93 kB |
| g16 | Textures and texture sheets on her parts *Bytes counted under a8.* | 0x5382aa, sheet lookup | textureSheetsDescription, *.bmp | **understood** | read from code, validated; ENGINE_CONSTANTS.md 2026-10-04; KAPOW_NAZ_FORMAT.md | - |

Read in this pass from the shader bytecode (`work/vcolor/dis`, the 243 shaders of the archive):

- **Skinning (g4).** `DepthVS[SKIN]`: bone indices = `COLOR1 x 256`, truncated, x 3; position =
  sum of four `$skinning` rows (c40 + index) weighted by `TEXCOORD3`. `$skinning` spans 210
  registers: a palette of 70 bones as 3x4 matrices, on the GPU, four influences per vertex. The same
  block opens `DeferredMain2VS[SKIN]`, `ShadowVolumeVS[SKIN]` and `ShadowMapVS[SKIN]`.
- **Depth pre-pass.** `DepthVS` writes view-space depth to a texture coordinate; the colour pass and
  the light pass read `$depthMap`.
- **Light pass (g7).** `DeferredLightLayerPS` (16 variants: POINT, SPOT, BOX, FRUSTUM, with
  TEXTURED, SHADOWMAP or STENCIL_SHADOWS) draws each light's volume with two render targets:
  target 0 receives the light's index colour (`$lightIndexColor`), target 1 the attenuation, which
  is distance falloff (`$lightAttnData`) x light power x shadow term (stencil shadow buffer through
  `$shadowLayerSelector`, or a shadow map); pixels outside the range are discarded. These two
  targets are `$LIB` (light index buffer) and `$LAB` (light attenuation buffer).
- **Colour pass (g6), `DeferredMain2PS[SPECULAR;TANGENTSPACE]`.** Normal = normalize(x T + y B + z N)
  with xy = (2 x texel - 0.996) x `$effectFactors.x` and z rebuilt, then to world space. Screen
  position -> `$LIB` gives up to four light indices per pixel and `$LAB` four attenuations. Each
  index addresses a row of two small textures: `$LPT` (light position, w = power) and `$LCT` (light
  colour). Per light: L = normalize(pos - P), diffuse = sat(N.L), H = normalize(L + V), s =
  sat(N.H), specular = s / (n - n s + s) x intensity with (n, intensity) = `$specularData.xy`.
  Result = (ambient + directional + sum of colour x attenuation x diffuse) x diffuse map + (sum of
  colour x attenuation x diffuse x specular) x specular map; alpha = diffuse alpha x vertex alpha;
  multiplied by the vertex colour; then fog. So the renderer is light-indexed deferred with at most
  four positional lights per pixel plus one directional light and ambient.
- **Post-process (g12), `PostProcessPS[AA]`.** Eight depth taps around the pixel in four opposite
  pairs; a pair is an edge when the depth differences disagree by more than `$aaSettings.x`; the
  edge count, above `$aaSettings.y`, blends the sharp image with a blurred one. Then: + material
  bloom map + blurred bloom x weight; + brightness; saturation (lerp from the channel mean);
  contrast around 0.5; tint (lerp to colour x tint); gamma by `exp(log(c) x g)`. `BloomRenderPS`
  writes glow map x diffuse x vertex colour x `$bloomPower` into the material bloom map. DOF and
  NOISE are variants of the same shader; the level has DOF off. Her level's values are in the table.
- **Target highlight (g13).** `FxHighlightCtrl.AssignOverrideSheets` 0x73da49 clones the texture
  sheet of every render instance of the character and installs the clones; `BlendOverrideSheets`
  blends bloom power and self-illumination on them over the definition's blend times. The two
  shipped definitions have self-illumination 0 and bloom 0, so the visible effect of the target
  highlight in the shipped data is not established.

### h. Sound

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| h1 | Animation events -> sound / speak / footsteps *Bytes counted under d2.* | CharacterRootLogic.command_animation_event_received cases 9 (SOUND), 37 (SPEAK), 6 / 40 / 76 / 77 (feet) | SoundEvents/SE_EN4_*.fragment and SE_BS2_*: lists of AnimationEventWM included by the states | **understood** | read from code (foot block skimmed); re/events.md | - |
| h2 | Voice: speak events, voices, quarantine, face start / stop | SpeakCtrl (reg 0x8420d4): Active 0x83d414, command_add_speak_event_based_on_enum 0x84171e, searchCharacterSpeakDef 0x83b223, ShouldIgnoreThisSpeaker 0x83ae84<br>SpeakDefinition.command_fill_speak_def_struct 0x83e32f, SpeakVoiceDefinition.findAllSpeaks 0x83e812, SpeakLib | AllBodelloTypes.fragment: 26 SpeakDefinition per voice Dom1 / Dom2 / Dom3 (TAUNT_*, MELEE_*, DAMAGED_*, DEATH, SPECIAL_GROUP_*), m_nquarantinetimemin/max, m_nrandom<br>sounds/Speaks/Dominatrix_01..03: 123 + 122 + 55 files<br>CharacterSoundDef.m_espeakref | **partly understood** | call lists; data; findings/face.md (START_SPEAK / STOP_SPEAK) | 60 fn, 12 kB |
| h3 | Sound definition: variation, random pitch / volume, 3D ranges | SoundDef (reg 0x8378d1): ChooseChild 0x82b53d, Play 0x82b44b, Active 0x82aecf, command_sounddef_play_all 0x831365, Quarantined 0x828d3b<br>native SoundSlot::PlayGroupPos / PlayGroupPivot | SoundDef props: minrange / maxrange, reverb ranges, dopplerfactor, enableobstructionandocclusion, randomPitchLength, randomVolumeLength, Priority, _iselectionmethod, _nmindelay / _nmaxdelay | **partly understood** | ChooseChild read; the rest call lists | 36 fn, 8 kB |
| h4 | Attack whoosh and hit impact sounds | CharacterSoundDef.command_play_attack_start_pos 0x679525<br>EffectSound.command_fire_effect 0x71dd1c | CharacterSoundDef: Attack_start_light / heavy / weapon (EffectDb)<br>EnemyDamageEffectDef children EffectSound | **partly understood** | data read; code small, not read | 6 fn, 900 B |
| h5 | Footstep and body-fall surface lookup | CollisionEffectCtrl.command_get_sound_package_based_on_model 0x6e0d9f, command_get_sound_in_package_based_on_enum 0x6e0f13<br>SoundPackageCtrl, EffectsLib.GetEffectPackageBasedOnTexture 0x71d254<br>DynamicObjectsEffectCtrl.command_add_dynamic_object_for_sound 0x71a63d | CollisionEffectDB / CollisionSoundDB fragments; sounds/Character/Footstep (173 files), sounds/Collision/Ragdoll (45) | **partly understood** | call lists | 30 fn, 9 kB |
| h6 | Mixing: volume groups, ducking, voice pool | SoundCtrl (reg 0x835a62): StateActive 0x829f70, command_damp 0x83104a, command_stop_entity 0x830f03 | Sound.fragment: 20 SoundController, SoundEffectNode "EnvironmentEffect", MusicStreamPlayer; SoundGrp groups | **partly understood** | call lists | 45 fn, 10 kB |
| h7 | Subtitles | SoundDef.Active -> command_show_subtitle; SubtitleHUD, SubtitleSlotRegister | Localize/, TextSlots.fragment | **partly understood** | hook seen only | 20 fn, 2 kB |
| h8 | Music reaction to combat | MusicIntensityCtrl.StateActive 0x7ce905 (2.0 kB)<br>MasterMusicCtrl, MusicTrackCtrl, MusicPlayer, MusicSetup, MusicStreamSlot, MusicIntensityContainer | MusicIntensityCtrl.m_iwatchedfaction 0 | **not understood** | names only | 70 fn, 15 kB |
| h9 | Sound scene nodes (slots, groups, system node, stream player) *3D positioning lives here: X3DAudioCalculate is not imported, so panning and distance attenuation are the engine's own.* | kernel/scenegraph sound nodes 0x4d6524-0x4db801 | - | **not understood** | not read; findings/submap.md | 421 fn, 49 kB |
| h10 | Low-level audio: XAudio2 voices, four custom effects, media streams, obstruction job | libs/adapter/sound 0x448336-0x453d31, 0x401000-0x4058be | *.wav (PCM / Vorbis payloads) | **not understood** | API surface listed; code not read; findings/submap.md 6; WATCHMEN_EXTRACTION_MASTER.md (containers) | 555 fn, 83 kB |

Read in this pass: `SoundDef.ChooseChild` 0x82b53d. A `SoundDef` with children picks one by
`_iselectionmethod`: 0 = random start, then the first child that is not quarantined; 1 (the default,
and the value on her voice lines) = the same but never the child played last; 2 = round robin.
Quarantine times, delays, random pitch and volume ranges and 3D ranges are properties of the
definition (her voice lines: range 7 - 150 m, obstruction on, priority 1). `Play` 0x82b44b hands over
to the native `SoundSlot::PlayGroupPos...` / `PlayGroupPivot...` calls; from there down nothing is
read.

### i. FX and feedback

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| i1 | Which damage effect plays | CharacterEffectDef.command_play_damage_effect 0x6673d0, initialize_local 0x66766c<br>ProjectAnimationLib.IsUpperDamagePose | EffectDb.fragment "EnemyDamageEffectDef": head / body x fast / heavy / uber / weapon wood / weapon steel / kill, sharp weapon, stun, knockdown, block | **understood now** | read from code | 3 fn, 2 kB |
| i2 | Effect objects: particle, sound, speak; effect controller | EffectCtrl.StateActive 0x715eed, command_start_effect_by_id 0x71cb5a<br>EffectParticle.Fire 0x7162f0, command_start_effect 0x71ce96<br>EffectBase, EffectSound, EffectSpeak, EffectsLib.FireGenericParticle 0x7167a4 | EffectDb.fragment: 113 EffectParticle, 72 EffectSound, 57 EffectSpeak; ParticleDb.fragment | **partly understood** | data read; code not read | 60 fn, 12 kB |
| i3 | Particle system runtime | kernel/assets/particles + emitter nodes 0x5552d3-0x565e7e | *.particle (decoded), art/Effects/CombatEffects/Blood, Pow, Spray, Teeth | **partly understood** | file format read; runtime not; FORMATS_MISC.md | 635 fn, 104 kB |
| i4 | Weapon trails | EffectsLib.SpriteLine 0x71d694 (candidate) | art/Effects/MotionTrails/Textures; WeaponBase._eglowingmodel | **not understood** | not established | 1 fn, 1 kB |
| i5 | Electricity on her (Nite Owl's armour, the boss's cattle prod) *The cattle prod is the Twilight Lady's (BS2_COM_ATT_cattleprod_*), not a Dominatrix weapon.* | ElectricArmor (10.2 kB), FXLighting (7.0 kB), FXLightning* classes<br>CharacterRootLogic: command_send_lightning_to_character, events 30 / 31 | art/Effects/ElectrifyArmor; speak DAMAGED_ELECTRIFY | **not understood** | names only; re/events.md (events 30, 31) | 60 fn, 25 kB |
| i6 | Camera feedback: shake, FOV kick, recoil, special cuts for counters / finishers | CameraModifierSinusShake.command_get_shake 0x6466fd, CameraModifierRecoil, CameraModifierBase<br>CameraCombatSpecialCuts (18.7 kB)<br>CharacterCamera (47 kB; only the modifier entry points matter here) | - | **not understood** | trigger sites read in give_damage; the cameras not | 60 fn, 24 kB |
| i7 | Controller rumble | VibrationMotorCtrl.StateActive 0x8ab937, SetVibration 0x8a9645<br>event IMPACT_EFFECTS (rumble by damage pose)<br>XInputSetState via 0x4251bc | - | **partly understood** | trigger read (events.md); controller not read; re/events.md | 9 fn, 2 kB |
| i8 | HUD she drives: finisher button prompt, combo counter, health / progress bars *There is no per-enemy health bar in the data; BossHUD is for the Twilight Lady.* | SpriteWobbler (prompt animation)<br>PlayerHUD (8.4 kB), ComboBuildupHud.command_visualize_combo_buildup 0x6ed9d5, ComboButtonHud, ComboTextShaker | template: four Sprite + SpriteWobbler(TextBox) with text slots 108-110, font DaveGibbons40 | **partly understood** | the prompt trigger read (d5); HUD classes not read | 98 fn, 28 kB |
| i9 | Sprites and text (engine) | Sprite, TextBox, TextSlot, Font, TextRes | art/Fonts/*.font, Localize/ | **not understood** | formats read; nodes not; FORMATS_MISC.md (.font) | 251 fn, 36 kB |
| i10 | Slow motion on heavy hits and kills | CharacterRoot.command_give_damage (WorldLib.SetTimeMultiplier), CharacterRoot.StateActive (restore)<br>WorldLib.SetTimeMultiplier | CharacterRoot._nslomotimemultiplier, _nslomotime | **understood now** | read from code | 1 fn, 400 B |

Read in this pass: `CharacterEffectDef.command_play_damage_effect` 0x6673d0. The definition holds
lists indexed by "upper or not" (`ProjectAnimationLib.IsUpperDamagePose`: head versus body). Choice:
a rage hit takes the uber list; a killing hit the kill list; a weapon hit the weapon list by the
weapon's effect type (wood, steel; a sharp weapon also fires its own effect); otherwise the fast list
for the light poses (1, 2, 5, 6, 23, 24) and the heavy list for the rest. Knockdown poses (17, 18,
27, 28) add the knockdown effect, stun poses (19 - 22) the stun effect. Each effect is an
`EffectBase` with children: `EffectParticle` (a `ParticleDb` entry and a placement), `EffectSound` (a
`SoundDef`), `EffectSpeak` (a speak id, for example 30 `DAMAGED_LIGHT_MIDDLE`).

### j. Game flow

| id | step | code | data | verdict | evidence, doc | size |
|---|---|---|---|---|---|---|
| j1 | Achievements she feeds | AchievementPart2Ctrl.command_enemy_killed_by_signed_in_player 0x599fd3, command_damage_by_signed_in_player 0x59a23d, command_player_received_damage 0x599f5d, command_enemy_thrown 0x59a883, command_combo_by_signed_in_player 0x59a4e3 | AchievementPart2Ctrl props: Tag'Em 10 kills within 10 s of prone, Focus Fire 10 in a row, Gentleman 20 s between combat | **understood now** | three handlers read | 22 fn, 5 kB |
| j2 | Game events on damage and death | GameEventCtrl.BroadcastGameEvent 0x74c677, command_flush 0x74c027<br>CharacterRoot.command_game_event 0x694649 | enum GAME_EVENTS (201 CHARACTER_DEAD ...) | **partly understood** | senders read; controller not | 14 fn, 4 kB |
| j3 | Checkpoints and saves *Inferred: only a checkpoint id is stored; a restore reloads the level and fires the checkpoint's child actions, so her individual state is not saved.* | GameStateCtrl.command_game_checkpoint_reached 0x74f382, restore_checkpoint 0x74f5f1, StateLoad 0x74fa94<br>TriggerActionCheckpoint.command_restore_checkpoint 0x85d2de<br>LevelProgressState, SaveFragment<br>archive_win32.cpp | MissionStructure.fragment: 13 TriggerActionCheckpoint | **partly understood** | call lists | 120 fn, 17 kB |
| j4 | Co-op target sharing *Bytes counted under c7 / c4.* | CombatOrchestrator.command_choose_target, ShouldSwitchTarget<br>AttackEnemy.command_may_attack (voice line per target) | - | **understood now** | read from code | - |
| j5 | The AI partner fighting her (single-player) | Partner, CombatPartner, CombatHelpPartner, CrowdControlPartner, AttackKillTargetPartner, FollowPartner, PartnerDef | Bordello/Gameplay/PartnerAI.fragment | **not understood** | not read | 183 fn, 75 kB |

Read in this pass: three `AchievementPart2Ctrl` handlers. A kill by the signed-in player counts
toward Focus Fire (10 defeated while staying on one enemy at a time: hitting a different enemy
resets the count, 0x59a23d) and, when the victim was knocked prone by that player less than 10 s
before, toward Tag 'Em (10). The Gentleman achievement is specific to her: hitting a character of
type 33 (Dominatrix) or 35 (Twilight Lady) before a lady has hit the player in the current fight
(fights are separated by 20 s without combat) clears `_tplayer_is_a_gentleman`; being hit by one sets
"it is ok to hit the ladies now" (0x59a23d, 0x599f5d).

## 7. Method findings other researchers can use

- **Member layout of script objects** (read on `CharacterRoot`, `CharacterSpawner`, `EnemyDef`,
  `Enemy`, `CharacterLodCtrl`; every offset checked gave a sensible name): the block at entity+0x10
  holds the registered properties in registration order, 4 bytes each, a vector property 12 bytes
  inline, a quaternion 16, strings and lists one pointer. A derived class's property list in
  `reg_dump.json` already starts with the parent's. Example: `CharacterRoot.m_nhealth` is at +0x64,
  `m_istateofmind` at +0x78, `_iweapontype` at +0x190.
- **Handler locals**: the tail of each registration function names the locals and parameters of each
  handler (read on `CharacterSpawner__register` 0x6d1b8f: `etemplist`, `iactive`, `ideactive`,
  `<return>`, `eCharacterRoot`, `enode`, `ecreateparent`, `tstillactivedeadenemies`, `ecorpse`,
  `tUberKill`, `damstruct`, `_iBodyNumber` ...). They are not member declarations, as the subsystem
  map guessed.
- **Coroutines** read well once the resume-label boilerplate is folded (`rdx.py`), and a handler's
  ordered command list (`calls.py`) is a usable first description of a 5 kB handler.
- **Calls to a class's own methods** appear as `InvokeHandler(*(*(vtbl) + OFF) + 0x24, self, ...)`.
  `OFF / 4` is the index into the class's command list in `reg_dump.json` (checked: `Enemy` 0xcc ->
  `SetState`, `CharacterRoot` 0x260 -> `DecreaseHealth`, 0x264 -> `IsAIPartner`, 0x288 ->
  `DeleteCharacterRootFragment`, `AttackEnemy` 0x8c -> `FindUsableCombo`).
- Property hash 0x2708acba is `enabled`; 0xf3f92d91 `worldPos`; 0x97e82c5a `worldOrient`.
- The game time (`WorldLib` object +0x20) and real time (+0x28) are two clocks; slow motion uses the
  second for its own timers.

## 8. Not established (collected)

- Whether the global difficulty preference changes anything for enemies.
- The gate in front of the reaction table; the roll for combos; the orchestrator's grant rule.
- Everything marked "partly" or "not understood" in the tables, in particular: the render pipe, the
  ragdoll rig, the character controller, block / dodge / counter windows, the damage formula, the
  sub-behaviours' geometry, the Kynapse services in use, the speak queue's priorities, 3D sound
  positioning, which node classes update in which native phase.
- Which effect draws her hair, and whether the target highlight does anything visible.
- Where `Dominatrix_3.glb` in the export comes from.
- Several rules in `Enemy.Evaluate` are inferred (marked * in section 6c).

## 9. Files

- `findings/dominatrix_audit.md` (this report)
- `findings/dominatrix_audit.json` (`meta`, `coverage`, `work_packages`, `steps`: id, area, step,
  code, data, verdict, evidence, doc_ref, size_estimate_functions, size_estimate_bytes,
  understood_fraction_estimate, code_kind, notes)
- `work/domaudit/` scratch: `steps.py` (the source of both files), `gen.py`, `genmd.py`, `body.md`,
  `rdx.py`, `calls.py`, `cls.py`, `sz.py`, `dominatrices_fragment_tk150.txt` (her definition as the
  1.4.0 parser reads it), `en4vis.txt`, `en_eval.txt`, `sa.txt`.
