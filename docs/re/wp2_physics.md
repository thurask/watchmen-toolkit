# WP2 — ragdolls, character controller and the PhysX layer

Target `KapowMultiDEDRM.exe`, PhysX 2.8.1 (`PhysXCore.dll` 2.8.1.1 decompiled, `NxCharacter.dll` not).
Evidence tags: **[code]** traced in the decompilation/disassembly (address given), **[data]** read from the
user's game files (read-only), **[inferred]** with the reason, **[not established]**.
Machine-readable: `findings/wp2_ragdoll_rigs.json` (13 rigs + common tables, schema in the file),
`findings/wp2_physx_vtables.json` (SDK vtable names + game call sites). Scratch: `work/wp2/`
(`NOTES.md`, `rigs_sel.json` raw file dump, `build_rigs.py`, `vcalls.py`, `pxvt.py`, `vt_*.txt`,
`group_matrix.json`, `cji_table.json`).

## 0. What changes against the brief and the earlier documents

1. **The ragdoll rig is not built in code. It is data in the skeleton `.model` file.** `CharacterRagdollSetup`
   is an editor tool: its only entry `command_setup_default_character` (hash 0x73ae8e9, handler 0x682b7c) is
   the target of a `control=button` property and has no sender anywhere in the dump **[code]**. Its tables are
   the authoring defaults; the shipped files contain exactly those numbers (checked) plus per-skeleton edits
   **[data]**. The dominatrix audit's "limits and masses are in code, not data" (d11) is the wrong way round.
2. The model's articulated-body section (called "physics/ragdoll … not parsed" in `KAPOW_NAZ_FORMAT.md` /
   `formats.md` 3.3) is now fully parsed: 13 character rigs extracted, all files tile to 4 bytes before EOF.
3. The two volume lists per node are **ragdoll/"default collision" shapes (list 0, PhysX scene 0)** and
   **cloth-collision shapes (list 1, PhysX scene 1)**. `skeleton_blobs.md` left the meaning open.
4. The gameplay capsule **is** an `NxController` (class `Physics::CharacterController`, the "actor" of the
   `CharacterPhysics(CollisionCapsuleNode)` node), moved by `NxController::move`; gravity on the ground is a
   constant −3 m/s sink term, and no integrating free-fall state was found (C).
5. Side findings for the toolkit: (a) `.pb` pivot books and the model AB blob use one record format
   `[objId][propHash][typeId][nWords][data]`; (b) `kapow_fragment_keys.pkl` lacks the D6 swing keys
   (0xe3ba246d `swing1LimitType`, 0x6f1c1d46 `swing1MotionLimitValue`, 0x96f40d0c `swing2LimitType`,
   0x1c2a4efb `swing2MotionLimitValue`, 0x0a3f7a6e / 0x1de40e20 / 0x09ebf0a2 and 0x9f5e10ab / 0xc640881e /
   0x97bd4e2a restitution/spring/damping) so D6Joint objects in fragments are mis-typed today (e.g.
   `"key_96f40d0c": "vector?"` in `CharacterRootTemplate_Enemy.fragment.json`) **[data]**.

---

## A. The ragdoll rig

### A.1 Where it lives and how it is read

`ModelRes::Read` 0x547006 calls `0x51e1ad` right after the node (part) array **[code]**:

```
u32 nDw; nDw x u32            property blob (kept at ab+0x84, applied last)
u32 n0;  n0 x u16 node        "default collision actors": RigidBody, body+0x8c = 0 (scene 0), body+0x98 = node
u32 n1;  n1 x u16 node        cloth actors: RigidBody, body+0x8c = 1 (scene 1)
u32 nC;  nC x { u16 node; u16 meshIndex; u32 m; m x { u16 vertex; u32 value } }     cloths (attachments)
u32 nJ;  nJ x { i32 parentBody; i32 childBody }                                     D6 joints, default frame by 0x517b34
```

`0x51a435` then applies the blob with `0x510e5f`: records `[objectId][propHash][typeId][nWords][nWords×4]`,
one run per object, in the order bodies (list ab+0x3c), cloths (ab+0x54), joints (ab+0x48). Scene-1 bodies get
no properties (they keep constructor defaults). Type ids seen: 0x144b7b5d string, 0xfd034a24 truth,
0x36604ff4 integer, 0xbda17de4 number, 0x71d8181d vector, 0xd007189c quaternion **[code + data]**.
`0x51cda2` contains the string "Cloth actors can only be added to pivots that also have a default collision
actor for that pivot" — that names the two lists **[code]**. The older XML path (`.modelInfo`, 0x51e623
"…has ragdoll data in an old format…") is editor-only.

A `Character` builds its own instance from **model slot 0** only: `Character` vtable slot 41 (0x4bee1e) calls
`0x51d5ad(model[0]->ab (+0x12c), character->ab (+0x154))`, which clones bodies, joints (frames copied) and
re-applies the blob; cloths of the other slots are appended by `0x51d8c2` **[code]**. Slot 0 is the skeleton
model in every character definition (`modelNames[0]`, 1203 fragment JSONs scanned) **[data]**:

| rig key (JSON) | slot-0 model | users | total mass | lin / ang damping | joint projection | shapes (list 0) |
|---|---|---|---|---|---|---|
| `medium` | common/skeletons/Medium_Skeleton | 60 model lists (Knot-Tops, Heavies …) | 85 | 0.5 / 2.0 | 15 of 16 | 23 capsules, 3 spheres, 2 boxes |
| `large` | common/skeletons/Large_Skeleton | 26 | 120 | 0.5 / 2.0 | 16 | 25 c, 3 s, 4 b |
| `small` | common/skeletons/Small_Skeleton | 9 (ThugFast) | 75 | 0.5 / 2.0 | 16 | 17 convex meshes (10–32 vertices) |
| `female` | common/skeletons/Female_Skeleton | 9 (Dominatrices) | 85 | 0.5 / 2.5 | 0 | 26 c, 2 s, 4 b |
| `gimp` | gimps/models/Large_Gimp_Skeleton | 7 | 185 | 0.5 / 2.5 | 0 | 25 c, 3 s, 4 b |
| `rsh` | rorschach/models/Rorschach_Dry | Rorschach in levels | 85 | 0.5 / 2.0 | 0 | 24 c, 2 s, 4 b (+ 5 cloth bodies, 2 cloths) |
| `nto` | niteowl/models/NightOwl_No_MaskDry | Nite Owl in levels | 81.89 | 0.5 / 2.0 (Spine1 0.5/1.0, Head 0/1.0) | 0 | 36 c, 5 s, 2 b (+ 17 cloth bodies, 1 cloth) |
| `bs2` | twilightlady/models/BS2_WithoutWeapon | Twilight Lady | 1700 | 0 / 1.0 | 0 | female shapes; **untuned**: every mass 100, every limit "limited 0", spring 0 |
| `gogo_*` | gogodancers/model/GoGo{White1,White2,Black} | dancer NPCs | 1700 | 0 / 1.0 | 0 | untuned like bs2 |
| `rsh_wet`, `nto_wet` | Rorschach.model, NightOwl_No_Mask.model | main menu only | 85 / 175.9 | | | as dry; `nto_wet` Head mass 100 (unedited) |

The female part models (Dominatrix_*, Fimale_*, GoGo*_Head …) and the gimp part models carry their own AB
copies with different numbers; they are never slot 0, so only their cloth list could matter and it is empty
**[code + data]**. All 13 rigs have **17 bodies and 16 joints**:

```
Pelvis ─ Spine ─ Spine1 ─ Spine2 ─┬─ Head
   │                               ├─ L UpperArm ─ L Forearm ─ L Hand
   │                               └─ R UpperArm ─ R Forearm ─ R Hand
   ├─ L Thigh ─ L Calf ─ L Foot
   └─ R Thigh ─ R Calf ─ R Foot
```

No Neck, Clavicle, twist-bone, finger, toe or jiggle body. Node indices and file order differ per skeleton
(JSON `node_index`).

### A.2 Bodies

Per body the file stores (property name → `RigidBody` member, registration 0x4fe… / ctor 0x4fe311): `Mass`
(+0xa0), `linearDamping` (+0xa4), `angularDamping` (+0xa8), `numSolverIterations` (+0x9c, 4 in every file),
`maxLinearVelocity`/`maxAngularVelocity` (200), `movementtype` (0), zero velocities **[data]**.

Masses are the editor formula of `CreateBoneInfo` 0x682c60 evaluated with exe constants (0xa5ea08 = 0.125,
0x9e70a0 = 5, 0x9e8670 = 3, 0x9e5a40 = 4, 0xa55530 = 7, 0xa07770 = 6, 0x9e5dc8 = 0.5, 0x9eb370 = 0.25) for a
total mass T **[code, reproduces the files to 7 digits]**:

| body | fraction of T | T = 85 |
|---|---|---|
| Pelvis, Spine, Spine1 | 3/28 = 0.107143 | 9.1071 |
| Spine2 | 3/28 (own 3/112 plus Neck, L/R Clavicle 3/112 each, folded in by `BoneMasses` 0x683545 because those bones have no body) | 9.1071 |
| Head | 1/14 | 6.0714 |
| UpperArm | 1/32 | 2.6563 |
| Forearm | 3/128 | 1.9922 |
| Hand | 1/128 | 0.6641 |
| Thigh | 15/128 | 9.9609 |
| Calf | 27/512 | 4.4824 |
| Foot | 9/512 | 1.4941 |

T comes from the `CharacterRagdollSetup` node (`m_ntotalmass`, default 85; `m_nlineardamping` 0.5,
`m_nangulardamping` 2.0 default, 2.5 in the shipped `CharacterVisual.fragment`) at authoring time; the game
reads none of these **[code + data]**. "Per-character scaling" is therefore only the choice of slot-0 model:
T = 75 / 85 / 120 / 185. No run-time mass or size scale was found on the path (`0x51d5ad` copies verbatim).

Actor creation `Physics::RigidBody` vtable slot 18, 0x506b75 **[code]**: one `NxShapeDesc` per volume of
`node.volumes[body+0x8c]` (slot 15, 0x5073eb → factory 0x4f73d5); `shape.group` = `actor.group` = body+0x48
(u16); `shape.userData` = body; density 1.0 and body descriptor only for movement type 1 (flags 0x980,
kinematic) or 2 (0x900); scene = `PhysicsSystem[+0x30 + 4·(body+0x8c)]`, `createActor` (+0x1c); then for
non-static bodies `updateMassFromShapes(0, mass)` (+0xcc), `setLinearDamping` (+0xd0), `setAngularDamping`
(+0xd8), `setMaxAngularVelocity` (+0xf0).

Shape descriptors **[code]**, constants read from exe bytes (0xa23760 = 0.025 double, 0x9e600c = 0.025,
0xaad40c = 0.001, 0xa23590 = 1e-5):

| volume | PhysX shape | dimensions |
|---|---|---|
| capsule (type 7) 0x4f727a | NX_SHAPE_CAPSULE, axis = shape local Y | radius = diameter/2 + 0.025; height = total height − diameter, 0.001 if ≤ 0 |
| box (5) 0x4f6f54 | NX_SHAPE_BOX | half extents = max(|size|/2, 1e-5) + 0.025 |
| sphere (6) 0x4f7145 | NX_SHAPE_SPHERE | radius = max(r, 1e-5) + 0.025 |
| convex (4) / concave (2) | cooked mesh from the blob | as cooked |

All: `skinWidth` 0.025, `shapeFlags` 0x120008 (SDK default), `materialIndex` 0 in the descriptor, local pose =
the volume's position and quaternion in the bone frame.

Material **[data + code]**: not in the model. It comes from the *pivot sheet* of the owning `Character` node
(fragment property `pivotsheet_id`, a 64-bit id) looked up in the pivot book the model names
(`/pivotbooks/default.pb`); `PivotSheet` has `friction`, `restitution`, `collisionMask`
(registration strings 0x526504, 0x5264a8). Enemies (`En3/En4/Goon/Prisoner*/Bs2CharVisual.fragment`) use
sheet **"Ragdoll": friction 0.6, restitution 0, mask 0x1**; Rorschach and Nite Owl use **"Ragdoll_All":
friction 0.6, restitution 0, mask 0x401**. `NxMaterial`s are created through scene +0x90 (0x51555a,
0x519168); static = dynamic = sheet friction; friction combine MULTIPLY, restitution combine AVERAGE
(0x51555a).

Run-time overrides **[code]**: `CharacterVisual.command_activate_ragdoll` 0x69eac6 enables the AB and calls
`RigidBody::SetNumSolverIterations(10)` on every body (→ `NxActor::setSolverIterationCount`, +0x174) — the
file's 4 is not what runs. Movement type: see B.

### A.3 Joints

Every joint is a D6 (`jointType` 0). Frame **[code]**: the loader's `0x517b34` builds the joint frame as
`Rz(180°) · childBone` (three half-angles: 0, 0 and the double 0xa0f230 = π/2; offset vector 0x9e803c = 0),
stores it relative to the child body (+0x78 pos, +0x88 orient) and relative to the parent body (+0x58,
+0x68). The file stores only `childSpacePos` (0,0,0) and `childSpaceOrient` (0,0,1,0) — identical in all
683 joints of the 44 models that have joints (the 13 character rigs, the character part models, a chain and
a clothing rack) **[data]** — and no parent-space property, so the parent frame is always the
bind-pose derivation. Consequences:

- anchor = **child bone origin**;
- twist axis X = **−X of the child bone**, swing1 axis Y = **−Y**, swing2 axis Z = **+Z** (child frame);
  the parent frame is the same world frame at bind pose expressed in the parent bone (JSON `parent_frame`,
  computed with the engine's quaternion rule and checked: the parent anchor equals the child bone's local
  position for every joint);
- the limits are symmetric about the **bind pose of the skeleton model** (e.g. the elbow is bent 15° in the
  female bind, the limit is ±90° about that).

The editor's `JointLimits` 0x683d12 additionally rotates the *parent* frame about the swing1 axis by a
per-joint offset (table field +0x48: spine −9, forearm 60, thigh 10, calf 30; `CreateJointInfo` 0x6846e8).
That rotation is not serialised and the loader rebuilds the symmetric frame, so the shipped game does not
have it **[code + data; the offsets' unit scale `[0xe171c0→+0x10→+0x60]` was not resolved]**.

Descriptor fill `Physics::D6Joint` slot 12 0x5146ec → 0x5141ee **[code]**: `actor[0]` = parent (+0xa4),
`actor[1]` = child (+0xa8); `localAxis[i]` = image of X, `localNormal[i]` = image of Y under the stored
quaternion (rows `(1−2(y²+z²), 2(xy−zw), 2(xz+yw))` and `(2(xy+zw), 1−2(x²+z²), 2(yz−xw))`), anchors
+0x58 / +0x78; limit angles × 0.0174533 (0xc8c574), spring/damping/restitution unscaled; `maxForce`/
`maxTorque` FLT_MAX unless `breakable`; `NX_JF_COLLISION_ENABLED` only if `actorCollisionEnabled`;
projection (`jointProjection`) → `projectionMode` 1 with `jointProjectionDist`, `jointProjectionAngle`;
x/y/z all locked.

Limits shared by `female`, `medium`, `large`, `gimp`, `rsh` (and `nto` with springs 5000/1000/200/2000
instead of 5000.3/1000.3/200.1/2000.1) **[data]**; they equal the `CreateJointInfo` table (first 20 of its 32
rows decoded value by value in `work/wp2/cji_table.json`; the remaining rows are filled through struct
copies and were compared by eye):

| joint (child → parent) | swing1 (about −Y) | swing2 (about Z) | twist (about −X) | spring / damping |
|---|---|---|---|---|
| Spine→Pelvis, Spine1→Spine, Spine2→Spine1 | ±10° | ±10° | −5…5° | 5000.3 / 70 |
| Head→Spine2 | ±20° | ±30° | −20…20° | 1000.3 / 31 |
| UpperArm→Spine2 | ±60° | ±60° | −15…15° | 200.1 / 14 |
| Forearm→UpperArm | ±90° | ±10° | −20…20° | 200.2 / 14 |
| Hand→Forearm | ±20° | ±15° | −5…5° | 200.2 / 14 |
| Thigh→Pelvis | ±40° | ±20° | −10…10° | 2000.1 / 44 |
| Calf→Thigh | ±40° | limited 0 (soft) | locked | 2000.1 / 44 |
| Foot→Calf | limited 0 | limited 0 | locked | 0 / 0 (hard) |

All restitutions 0; no joint is breakable (`maxForceBeforeBreak` 500 is inert); `actorCollisionEnabled` 0
everywhere (adjacent bodies do not collide; non-adjacent ones do, they share one group); `enableJointMotors`
0 in the files (enabled at run time, B.3). `small` differs: spines 200.3/14, head 500.2/2, legs 500.1/22,
knee ±50°. `bs2` / `gogo_*`: all "limited 0", spring 0.

Projection: `medium` 15 joints (not L Hand), `large` and `small` all 16, distance 0.02 m, angle 0.01745 rad;
the others none.

### A.4 Collision group and filtering of the bodies

Groups are the script enum `COLLISION_GROUP_TYPES` (0 WORLD, 1 ACTIVE_CHAR_PHYSICS, 2 INACTIVE_CHAR_PHYSICS,
3 RAGDOLL_IN_WORLD, 4 KINEMATIC_RAGDOLL, 5 DYNAMIC_WORLD, 7 EXPAND_VOLUME_PHYSICS, 8 KINEMATIC_RAGDOLL_ROR,
9 KINEMATIC_RAGDOLL_NO, 10 SIMPLE_RAGDOLL, 11 AI_SYSTEM_WAYPOINT, 12–15 player capsules, 16–19 player
ragdolls). `CharacterVisual.command_reset_collision_group` 0x69e9a5: animated character → 4 (enemy), 8
(Rorschach), 9 (Nite Owl); argument ≠ 0 → 10. On entering the ragdoll state the bodies get a **unique
group** from `PhysicsSimulation.command_create_unique_ragdoll_collision_group` 0x7dfe37 (released by
`command_unregister_unique_collision_group`). The pair matrix is set once by
`PhysicsSimulation.command_setup_collision_groups` 0x7dffbf (186 calls of `PhysicsWorld` 0x512b81 →
`NxScene::setGroupCollisionFlag` +0xbc and `setActorGroupPairFlags` +0xcc with 0x86 = start-touch |
end-touch | forces); the 135 constant pairs are in the JSON (`common.collision_groups`), the 49 calls for
the computed unique groups were not tabulated. Relevant rows: KINEMATIC_RAGDOLL collides with WORLD and
RAGDOLL_IN_WORLD, not with DYNAMIC_WORLD or capsules; SIMPLE_RAGDOLL with WORLD and DYNAMIC_WORLD only.

---

## B. Animation ↔ physics hand-over

### B.1 Modes of the bodies

`RigidBody` movement type (+0x40): 0 static, 1 kinematic, 2 dynamic (0x506b75). After
`CharacterVisual.command_activate_model` 0x69e354 the Character node has physics type 1 and movement type 1:
the 17 bodies are **kinematic and follow the animated bones every frame** (`RigidBody` slot 28, 0x50bd0f:
kinematic → `moveGlobalPose` +0x34, dynamic → `setGlobalPose` +0x14), in group 4/8/9, subscribed to contact
messages (`CollisionNode::SubscribeToCollisionInfo`). That is what dynamic props and other ragdolls collide
with; melee hits are not geometric (dominatrix audit d13).

### B.2 What triggers the ragdoll — it is an animation state **[code + data]**

`AnimationCtrl.CharacterRagdollAnimTransferControl` 0x5b9c8f looks at the newest state in the bank list: if
it carries ragdoll joint settings (list at state-struct +0x3c non-empty, written by a `BehaviorAnimation`
node of that state) it runs `PreCharacterTransferToRagdollControl` + `CharacterTransferToRagdollControl`,
otherwise (and ragdoll weight ≠ 0) the two `…ToAnimationControl` handlers. So death, knock-down and throws
ragdoll because their animation classes route into a state of the `RagdollGroup`. For Enemy04 (data,
`anim_meta_v2.json`): `Knockdown*` clips → `RagdollGroup/Egg` at play position ≥ 0.95 (ease 0.2 s);
`Ragdoll-Hit` and `Ragdoll-Idle` → `Egg` after 0.4 s; `ThrownByRorschachRagdolled` after 0.5 s;
`BullmoveImpactTarget` at 0.55; action `RAGDOLL` (`CONTROL_ACTION_TYPE___RAGDOLL`) sends any get-up state
back to `Ragdoll-Idle`; every get-up pose has a transition to `Dead`. No handler on this path sends a
"go ragdoll" command directly: the senders of `command_ragdoll_driven` (0x633b7f2f) and
`command_state_ragdoll_driven` (0xec42f9c0) are only 0x5b16ed and 0x6937d1. How the
`KILL_ANIMATION_PARTNER` event and the damage poses select the knock-down/ragdoll states is state-machine
and combat logic (events.md, WP3) and was **not traced here**. Impact-driven
ragdoll of an animated character (thresholds `CharacterVisualDef`: ragdoll 6000, animation 2000, ignore 500,
decrease 2500/s, collider force scale 1.2, height mask 0.6 in the shipped fragment) is handled in
`CharacterVisual.ModelCollisionContactAdded` 0x69d00a / `DetermineDamageReaction` 0x6a18d1 — **not read**.

### B.3 Transfer to ragdoll **[code]**

1. `AnimationCtrl.CharacterTransferToRagdollControl` 0x5ad022: sets property `movementtype` (0x61f13948) = 2
   on the character (bodies become dynamic, keeping pose; velocities: see 3), calls native
   `Character::TransferToRagdollControl(t)` 0x4b5f26 with t = the state's blend time, and schedules
   `command_character_transfer_to_ragdoll_control_callback` at now + t (fired from `PostUpdate` 0x5cab6b →
   0x5af75c → `CharacterVisual.command_start_trasfer_to_ragdoll_done`).
2. `AnimationCtrlWM` override 0x5b16ed: `CharacterRoot.command_ragdoll_driven` 0x6937d1 (→
   `CharacterVisual.command_state_ragdoll_driven`, `CharacterPhysics.command_state_ragdoll`),
   `CharacterVisual.command_start_trasfer_to_ragdoll`; with an animation partner (a throw):
   `command_enemy_thrown`, then the ragdoll's velocity is re-aimed at the partner's throw target (entity at
   partner+0x8c or vector +0x90; unset = −10000, 0x9e6730 → keep the direction of the ragdoll's mean
   velocity) with speed **9.0** m/s (0xa45bec), **5.0** if `command_is_big` (0x9e97fc), using
   `MathLib.CalcProjectileAngle` and `characterlib.RotateAndScaleRagdollVelocity` 0x6650bf.
3. `CharacterVisual.StateRagdollDriven` 0x69ed7c (state init): unique collision group; if
   `m_nnormragdollspeed` > 0 and the mean body speed > 0.5 (0x9e6174) all body velocities are scaled to that
   speed (`ScaleRagdollBoneVelocities` 0x6653a5); `m_vragdollvelincrease` is added
   (`AddRagdollBoneVelocities` 0x67a035); collider impulse × 1.2 → `SetRagdollMeanImpuls` 0x664ff3; collider
   velocity × 1.2 → `SetRagdollMeanVelocity` 0x664f7d; collider angular velocity → pelvis
   (`SetRagdollAngularVelocity` 0x66b43d, bone enum 32 = PELVIS). The *initial* body velocities are whatever
   PhysX derived for the kinematic bodies that were following the animation (kinematic → dynamic switch);
   no explicit pose/velocity copy function exists **[inferred from the absence of one on this path]**.
4. Per frame in that state: accumulated ragdoll damage > 1 → `CharacterRoot.command_give_ragdoll_damage_increment`
   0x6914f2; added damage decays 20/s (0x9e5c68); the first time the pelvis speed drops below 1.5 m/s
   (0x9e5ff0) `m_tcandamagebetransfered` is cleared and `command_reset_collision_group(1)` moves the bodies
   from their unique group to SIMPLE_RAGDOLL (10: world and dynamic world only, no characters); then
   `command_update_ragdoll` 0x6bc3e2.

Native blend (the "TransferTo…" calls) **[code]**: `Character` +0x1f0 `ragdollBlendWeight`, +0x1f8 state
(0 → ragdoll, 1 → animation, 2 idle), +0x1fc/+0x200 start/end time. Per frame `0x4b5c56`: weight = linear
ramp (0x4af07d); if weight ≥ 1e-5 the ragdoll pose is built from the bodies' world transforms brought into
character space (`0x51a9dc`), mapped onto the full skeleton by a body↔bone mapper (`0x58f399`, tables from
`0x4b96da`: per body the bind-pose matrix relative to its bone), and either lerped with the animation pose
(weight ≤ 0.99999) or used alone. So while ragdolled **the 17 body bones are driven by the bodies**
(position and orientation); bones without a body keep their animated local transform under the driven
parent **[inferred from the mapper call shape; the mapper internals 0x58edf9/0x58eea3 were not read]**.

Powered / partial ragdoll **[code]**: joint motors are switched on for every AB joint when the model
changes (`command_model_changed` 0x5b33d4: `Joint::SetEnableJointMotors(1)`, `SetTwistMotorType(1)`,
power 0). While a state with a `BehaviorAnimation` node is active, `AnimationCtrl.PostUpdate` 0x5cab6b does
per joint: target = joint-space orientation of the *animation* (`MuscleOrientationAnim` 0x5acd3c), current =
`MuscleOrientationRagdoll` 0x5ba03b (`childSpaceOrient ⊗ q_child ⊗ conj(parentSpaceOrient ⊗ q_parent)`);
`D6Joint::SetOrientMotorTargetOrient` (0x5178bb → `NxD6Joint::setDriveOrientation` +0x70) when it changed;
`SetOrientMotorPower` 0x5175b0 (joint+0x1a8 → swing drive, position mode, spring = power, damping 0);
`SetTwistMotorPower(max(10, 10·power))` (joint+0x1a0 → twist drive). Power per joint =
`m_ndefaultmusclepower` × `m_njointmusclepowerscaleN` (+ extra, blended in over `m_nmuscleblendintime`;
`BehaviorAnimation.StateActive` 0x615ed3, audit d10; 16 scales = the 16 joints). Per body: bodies whose entry in `m_wantedboneposestructlist` is clear are dynamic (movement type 2), the others are
set kinematic (1) and placed at the
animated bone each frame (`SetWorldPosAndOrient`); the list is filled from `BehaviorAnimation.m_iselectedbones`
(flags `ANIMATIION_BONE_TYPES`; which polarity means "physics" was not checked). `command_state_partial_ragdoll_driven` (0x757b0abf) has
no sender in the code; partial ragdoll is this per-body switch.

### B.4 Root follows the ragdoll, get-up **[code + data]**

`command_update_ragdoll` 0x6bc3e2 each frame: reads the pelvis body (`_echaracterragdollpelvisbone`), moves
the character root/visual pivot with it (`Actor/PivotNode::SetWorldPosAndOrient`), casts a capsule down
(`PhysicsWorld::CastCapsule_AllHitsSorted`) for the ground, and writes animation values
`CHARACTER_PELVIS_VELOCITY` (10) = pelvis speed, `CHARACTER_PELVIS_GROUND_HEIGHT` (11),
`CHARACTER_PELVIS_RAGDOLL_FREE` (8) = 0/1, `CHARACTER_PELVIS_ROTATION` (6) = an angle in degrees computed
from two dot products of pelvis axes by a two-argument class helper (class handler slot 0x100; an atan2,
**[inferred]**) × rad→deg (`[0xe171c0→+0x10→+0x5c]`). The get-up clip is then chosen by the **state machine**,
not by code — Enemy04: `Egg → Group GetupPoses` when velocity < 0.25 and ragdoll-free ≥ 1; pose by rotation:
[−45, 45) `GetupPoseFaceUp` (`EN4_COM_DMG_prone_back_pose`), [45, 135) `…Left`, [−135, −45) `…Right`, else
`…FaceDown`; each pose state is a one-frame clip (ease-in 0.1 s) → `Getup<Dir>Start` → `Getup<Dir>End` →
`CombatGroup`. Entering the pose state (no ragdoll joint list) makes 0x5b9c8f run the transfer back:
`CharacterVisual.command_pre_transfer_to_animation_control` 0x69fde4 (new unique group),
`Character::TransferToAnimationControl(t)` 0x4b5f6b via 0x5ad0e8 (weight ramps 1 → 0 over the state's blend
time), `command_start_transfer_to_animation_control` 0x6b09d9 (capsule `command_init_state_free_fall`,
movement type back, root placed at the get-up position `m_vcharactergetuppos` / `m_qcharactergetuporient`),
and at the end 0x69fea0 (restores capsule width/height, `CharacterRoot.command_animation_driven_set_transform`).
Position checks before standing (`VerifyCharacterLocation` 0x6a01d4, `solveStaticObject` 0x6a10cb,
`dynamic_getup_logic`) were **not read**.

### B.5 Corpses

Read in the dominatrix audit (d9, `CharacterRoot.StateDead` 0x6bb12a): while the ragdoll's mean speed is
above 0.01 the pose is refreshed only when in a frustum; at rest the corpse is re-parented to its culling
group, `Character::SetFreeze(1)`, the articulated body cleared and physics deleted; fell-out-of-world test at
y = −100; `FREEZE_ACTIVE_RAGDOLLS` trigger actions force it (`TriggerActionCharacter.FreezeActiveRagdoll`
0x852a99). Added here: `CharacterVisual` has `_nragdolldeathtime` 3.0 s and a fail-safe 15.0 s
(registry defaults) **[data; the code using them not read]**.

---

## C. Character controller

Auto-align, absolute animation mode and the paired "DCC" flow are in `findings/placement.md` (sections 1–5);
not repeated.

**Object** **[code + data]**: `CharacterPhysics(CollisionCapsuleNode)` node "MovementPhysics" in
`CharacterRootTemplate_{Enemy,Rorschach,NiteOwl}.fragment`: width 0.8, height 2.0 (identical for all three),
`m_ninitsteplimit` 0.3, `_nsharpness` 1.0; its actor (mass 100, movement type 2) is a
`Physics::CharacterController` (cast 0x5aad76 in `command_attempt_move`). Creation, vtable slot 18 0x4fdfb3:
`NxCapsuleControllerDesc` radius = width/2 + 0.025 = **0.425**, height = height − width = **1.2** (must be
> 0), `slopeLimit` = cos(slope-limit° × 0.0174533) (controller+0xa0, setter 0x4fe288), `skinWidth` 0.025,
`stepOffset` = controller+0xa4 (setter 0x4fe2cb), callback `ControllerCallback`, `interactionFlag` 2, position
as three doubles; `NxControllerManager::createController(scene 0, desc)`; then `getActor()`, actor and shape
group = the node's collision group. Also in the template: a `WorldJoint` D6 on the capsule (all linear and
swing axes free, orient motor 5000 / 10000) and the `ExpandVolume` capsule 0.08 × 0.2 with `FollowJoint`
(linear limit spring 200, damping 25) and `FollowPivot` box — the get-up/expand helper (audit e3), not read.

**Move** `0x5027b5` (via `CharacterController::Move` 0x506a07 / 0x502baa) **[code]**: horizontal displacement
capped at 25 m (0xa24b38; test 625); `NxGroupsMask{bits0 = caller mask, bits1 = 1 << physics type (body+0x3c; controller 4, cloth 3), bits2 = 0,
bits3 = caller}`; `NxController::move(disp, activeGroups, max(minDist, 1e-5), &flags, sharpness, &mask)`;
if the controller moved less than `minDist` it is put back (`setPosition`), otherwise the node transform is
updated from `getPosition()`. Moving the node from outside (`NotifyPivot`, slot 28 0x502bfe) does a
`move(delta, minDist 0.001, sharpness 1)`; in teleport mode `setPosition`.

**Script states** (`CharacterPhysics`, enum `CHARACTER_PHYSIC_STATES` 0 ON_GROUND, 1 FREE_FALL, 2 RAGDOLL,
3 ABS_ANIMATION, 4 CHARGE):

- `StateOnGround` 0x67d2a5: state 0; `m_icharactercollisiongroupmask` = 2⁰+2¹+2²+2⁵ = 0x27 (WORLD,
  ACTIVE/INACTIVE_CHAR_PHYSICS, DYNAMIC_WORLD); collision group 1; per frame `DccUpdate` 0x680654.
- `command_attempt_move` 0x67d52c (args: velocity, dt): `DccAttemptMove` first (if the DCC joint handles the
  move, no controller move); else `_ngravityvel = −(PhysicsWorld.physicsIntegrationRateInHz × 0.05)`
  (0xa00168; **−3.0 m/s at 60 Hz**) is added to the Y velocity and
  `Move((v + (0, g, 0))·dt, minDist = PhysicsSimulation.m_nminimummovement (0.005), sharpness, mask bits0 =
  m_icollisionmask, activeGroups = m_icharactercollisiongroupmask)`. Gravity is this constant sink speed, not
  an integrated acceleration; "falling" is the animation's business (`ANIMATION_VALUE` FREEFALL).
  `command_state_free_fall` / `command_init_state_free_fall` only switch states (0x6802fb, 0x6802cd).
- The velocity comes from `CharacterRoot.StateActive` 0x6b367a, which sends `command_attempt_move(v, dt =
  frame dt)` when the capsule is not in absolute mode. `v` is the animation's `GamePivot` motion turned into
  world space plus a push-back term that decays linearly (members [0x3e], [0x3f]); the assembly of `v` is in
  the unread two thirds of `StateActive` **[partly established]**.
- `StateAbsoluteAnimation` 0x6a1e1d: placement.md. `StateRagdoll` 0x68012e: script disabled on the capsule,
  collision group swapped; `StateCharge`, `StateGrapplingHook`: player only, not read.
- Pushing: the controller's hit report and the contact report queue "contact added" messages;
  `CollisionContactAdded` 0x67c845 sends `command_being_pushed_by` to its own character root when the
  horizontal part of contact-info field +0x28 exceeds 200 (0x9eba88) and its own animation velocity is
  below 1.0; then sets `_tgroundcollision` when normal·up > 0.9 (0xa299a0). Field +0x28 is the motion
  direction for a controller hit (0x50bb4e) and the summed normal + friction force for a contact report
  (0x50cfaa → 0x50c359), so only contact reports can pass 200; `FeedBack` 0x681e7b applies impulses to dynamic bodies it touches
  (`RigidBody::ApplyImpulse`); `RagdollFeedBack` 0x6823dc ray-casts for ragdolls; `command_detect_wall`
  0x67b508 (`m_nangleforwallcontrol` 46°). The numbers and rules of these four are read since
  (2026-10-06): `docs/COMBAT_META.md`, "Movement contact rules". `FeedBack` never runs: its only
  caller, the command `CollisionResponse` 0x67c7e4, has no sender (hash 0x4cb780c2 only at its
  registration; no subscription names it; the native handle in 0xe15290 is stored at 0x50f255 and
  never read) (read from code).
- Character-vs-character separation in pairs: the DCC joint (`DccJoint` 0x6a3d71, `DccUpdate`), an
  `EmbeddedJointNode` between the two capsules — placement.md 1.4; its D6 parameters were not extracted.

**Filtering** **[code]**: scene creation `0x502fda` sets `setFilterOps(AND, AND, AND)`, `setFilterBool(true)`,
`setFilterConstant0/1 = {0xffffffff, 0, 0xffffffff, 0xffffffff}` (0x4fec19) and all 32×32 group pairs to
"same group only" before the script matrix (A.4). Two shapes pass the mask filter when their `bits0`
(pivot-sheet `collisionMask`) or `bits3` share a bit; word 1 (the physics-type bit) is masked out. Capsule sheets:
`Character_Enemy` 0x102, `Character_Rorschach` 0x2042, `Character_NiteOwl` 0x208a (friction 0).

**Two scenes** **[code]**: `PhysicsSystem` ctor 0x50d1e1 creates scene 0 (descriptor 0x4f49f8: user notify,
trigger report, contact report, `CustomScheduler` at system+0x50, flags 0x58 (= ENABLE_MULTITHREAD |
ENABLE_ACTIVETRANSFORMS | DISABLE_SCENE_MUTEX by the 2.8.1 enum values, **[inferred]**: the descriptor's
default block 0x44 matches the SDK default), static AABB tree / dynamic AABB tree; optional bounds ±1000 with
`NX_BP_TYPE_SAP_MULTI` 8×8 when 0xe14605) and scene 1 (0x4f4b5e: same but **no** notify/trigger/contact
reports, scheduler at +0x80). Scene 0 = world, capsules, ragdolls, triggers, jiggle boxes; scene 1 = cloth
and the kinematic cloth-collision bodies. Both use the same gravity, rate and step.

**Stepping** (jiggle.md §3, re-read): `0x4f4d20` accumulates frame dt, h = 1/rate (60 Hz default, ctor),
n = floor(acc/h); `0x4f4ddc` per scene: `setTiming(h, maxSteps = 8, NX_TIMESTEP_FIXED)` (+0x148) and
`simulate(min(n·h, maxSteps·h))` posted as a job. Kinematic targets: `moveGlobalPose` once per frame.
SDK: `NxCreatePhysicsSDK(0x2080100, Physics::Allocator, ErrorStream, desc)`, `setParameter(NX_SKIN_WIDTH,
0.025)`; default gravity (0, −9.82, 0) (0xa26418) until the `PhysicsWorld` node sets its own.

---

## D. PhysX wrapper inventory

### D.1 Game-implemented interfaces (RTTI vtables, `work/wp2/cb_vtables.json`)

| class (vtable) | interface | what it does | evidence |
|---|---|---|---|
| `Physics::Allocator` (0xa2395c) | NxUserAllocator | malloc/mallocDEBUG/realloc/free → engine `MemoryManager` (slots 0x4f7773, 0x4f7767, 0x4f7716, 0x4f7705, 0x4fdf33) | [inferred from the interface and slot sizes; bodies not read] |
| `ErrorStream` (0xa239cc) | NxUserOutputStream | `reportError` 0x4fe982 / `reportAssertViolation` 0x4fead6 / `print` 0x4f7783 → engine log | [inferred likewise] |
| `Physics::CustomScheduler` (0xa25860), two instances | NxUserScheduler | `addTask`/`addBackgroundTask`/`waitTasksComplete` → engine job scheduler (`PhysicsTaskJobContainer` 0xa25874) | [inferred from slots 0x506967…0x50babf] |
| `UserReport` (0xa23930) | NxUserNotify | `onJointBreak` 0x4f7619: notifies the joint's node, returns true (joint released); wake/sleep unused | [code] |
| `ContactReport` (0xa23950) | NxUserContactReport | `onContactNotify` 0x50cfaa: END_TOUCH → message type 2; START_TOUCH → walks the contact stream, one message type 1 per point (point, normal, feature) to **both** owner nodes that run scripts (queue 0x50c359 → 0x4a6c73). Scripts receive them as `CollisionContactAdded` / `ModelCollisionContactAdded` → ragdoll damage, impact sounds (`COLLISION_EFFECT_TYPE_*`), capsule push | [code]; consumers skimmed |
| `TriggerReport` (0xa23944) | NxUserTriggerReport | `onTrigger` 0x4f7674: ON_ENTER / ON_LEAVE → `Trigger` node enter/leave lists (0x51ceb6) | [code] |
| `ControllerCallback` (0xa2386c) | NxUserControllerHitReport | `onShapeHit` 0x50bb4e: same contact message (world position, normal, direction, length) to the capsule's and the hit body's nodes; returns 1 (NX_ACTION_PUSH) | [code] |
| `PhysXRaycastReport` (0xa237cc), `PhysXScriptRaycastReport` (0xa239ec) | NxUserRaycastReport | `onHit` 0x50a202 / 0x50a0ee: collect hits for native callers / for the script `castray_*` commands (list of `PhysicsCastHitInfo`) | [inferred from names and callers; bodies not read] |
| `ScriptSweepReport` (0xa2376c) | NxUserEntityReport<NxSweepQueryHit> | `onEvent` 0x509c7b: results of `castcapsule_*` (`linearCapsuleSweep` +0x1e0) | [inferred likewise] |
| `OverlapReport<…>` (0xa237d8) | NxUserEntityReport<NxShape*> | `onEvent` 0x50ad73: `check*overlap` (`overlapOBBShapes` +0x1cc …) | [inferred likewise] |
| `ActorOverlapReport` (0xa239f8), `SceneQueryReport` (0xa24a68) | NxSceneQueryReport | batched scene queries (`createSceneQuery` +0x25c / `releaseSceneQuery` +0x260 in 0x4ff0e3, 0x50c49a) | [inferred from slots] |
| `MemoryWriteBuffer` (0xa29658), `MemoryReadBuffer` (0xa29690) | NxStream | cooking output / cooked-blob input (`createTriangleMesh`, `createConvexMesh`, cloth mesh) | [code, skeleton_blobs.md] |

Which raycasts the camera and combat use (`PhysicsWorld::CastRay_*`, `CastCapsule_*`, `Check*Overlap`
0x51be80–0x51c595, all taking a pivot-sheet mask, node mask and shape-group mask) is a script-side question
and was not surveyed.

### D.2 SDK method identification

Method: vtables of `NpActor`, `NpScene`, `NpPhysicsSDK`, `NpD6Joint` located through RTTI in `PhysXCore.dll`
(`work/wp2/pxvt.py`), each slot's function searched for the SDK's own error strings
("Actor::createShape: …", "Scene::raycastAnyBounds: …"), and the 2.8.1 public header order laid over the
anchors. In every interface slot 0 is one extra entry before the first documented method.

- **NxActor — certain.** 22 string anchors (slots 17, 39–44, 48–50, 53, 55, 58, 59, 61, 63, 66, 67, 76, 91,
  94, 95) all fall on the header order; the game's 20 used offsets resolve to sensible methods
  (`SetMass` → +0xb4 `setMass`, `SetNumSolverIterations` → +0x174 `setSolverIterationCount`).
- **NxScene — certain up to slot 142** (22 anchors incl. the six raycasts 107–112, `simulate` 140,
  `fetchResults` 142); slots 143–156 by header order only.
- **NxD6Joint**: `loadFromDesc` = slot 25 (string); +0x6c `setDrivePosition`, +0x70 `setDriveOrientation`,
  +0x74 `setDriveLinearVelocity` follow — certain for +0x70 (called by `SetOrientMotorTargetOrient`).
- **NxPhysicsSDK, NxController, NxControllerManager — inferred** from header order with 4 / 5 / 2 consistent
  call sites each.
- **NxCloth (member +0x9c of `Physics::Cloth`, 16 offsets used), NxShape, NxMaterial — not established.**

Tables and the game's call sites per offset: `findings/wp2_physx_vtables.json`. The scan
(`work/wp2/vcalls.py`) finds 561 indirect call sites in 0x4f4000–0x525000; 180 have a receiver my
pattern does not classify, so the per-interface lists are lower bounds.

---

## E. Collision volumes in model files

- **List 0** (`node+0x4c`): shapes of the node's scene-0 body — the ragdoll body *and* the kinematic body that
  represents the animated character to the world (same actor, movement type switched). A node's list 0 is
  used only if the AB section lists that node as a body; in the 13 rigs every node with list-0 volumes is a
  body and vice versa **[code + data]**. Yes: **the ragdoll uses them; they are its only geometry.**
- **List 1** (`node+0x58`): shapes of kinematic bodies in the cloth scene, created only when the model's AB
  has cloths (Rorschach: Pelvis, both thighs and calves for coat and belt; Nite Owl: all 17 for the cape).
  The 17-body list-1 sets in the female part models are inert in the shipped game (those models are never
  slot 0 and have no cloth) **[code + data]**.
- Third list: emitter surfaces, unrelated (skeleton_blobs.md).
- Character **hit detection does not use volumes** (range checks; audit d13). World collision of a living
  character is the controller capsule, not the volumes.

---

## F. Export specification

Goal: a Blender user imports the character GLB and gets bodies, shapes and constraints in place.
Everything needed per skeleton is in `wp2_ragdoll_rigs.json` → `rigs[<key>]`; nothing below needs the exe.

### F.1 What to write

1. **Sidecar** `<character>.ragdoll.json` = the rig entry verbatim plus `common`, keyed by the skeleton the
   character uses (slot-0 model: `female`, `medium`, `large`, `small`, `gimp`, `rsh`, `nto`, `bs2`).
2. **Helper nodes in the GLB** (so that Blender's importer, which re-orients bones, still places everything):
   - per shape a node `RB.<bone>.<i>` as **child of the bone's joint node**, `translation` = `local_pos`,
     `rotation` = conjugate of `local_quat_xyzw` (same rule the exporter already applies to rest
     quaternions), `extras.kapow_shape` = `{type, physx:{…}, file:{…}}`; for convex meshes also a mesh
     primitive from `file.vertices`/`indices` (mode 1 = triangle list);
   - per body `extras.kapow_body` on the bone's joint node: `{mass, linear_damping, angular_damping,
     solver_iterations: 10, friction: 0.6, restitution: 0, group}`;
   - per joint a node `RJ.<child bone>` as child of the **child** bone's joint node with `translation`
     (0,0,0) and `rotation` = conjugate of `child_frame.quat_xyzw` (= 180° about Z), `extras.kapow_joint` =
     `{parent_bone, child_bone, twist:[low,high], swing1, swing2, motions, springs, projection}`;
   - on the skin root: `extras.kapow_ragdoll = {format: "wp2_ragdoll_rigs/1", rig: <key>, sidecar: <file>}`.
   - cloth-scene bodies only as data in the sidecar (`cloth_scene_bodies`), no nodes by default.
3. Mirror: the GLB is the engine's mirror image (ANIMATION_META.md). Helper nodes are children of the
   joints, so they mirror with the skeleton if the user un-mirrors. Angle ranges about an axis change sign
   under a reflection (`[low, high]` → `[−high, −low]`); every twist range in the game data is symmetric, so
   nothing changes in practice.

### F.2 Blender mapping (to be done by an add-on script or by hand)

- Body: one mesh object per `RB.*` node (capsule = cylinder length `physx.height` + two hemispheres radius
  `physx.radius` along the node's Y; box = `2·half_extents`; sphere), rigid-body shape CAPSULE / BOX / SPHERE /
  CONVEX_HULL; several shapes of one bone grouped under one object with the "Compound Parent" shape where the
  Blender version has it (otherwise one convex hull of the union), mass = `mass`, friction 0.6, bounciness 0.
  Damping: Blender/Bullet's 0…1 damping is not PhysX's 1/s coefficient c. Bullet scales velocity by
  `(1 − d)^dt`, PhysX by about `e^(−c·dt)`, so d = 1 − e^(−c): translation 0.39 for c = 0.5, rotation 0.86 /
  0.92 for c = 2.0 / 2.5 (conversion from the two libraries' formulas, not measured — to be checked in
  Blender). `collision_margin` 0 if the +0.025 inflated `physx` sizes are used, or 0.025
  with the `file` sizes. Bone ← body: `Copy Transforms`/`Child Of` from the 17 bones to their body objects.
- Joint: `GENERIC` rigid-body constraint on an empty at the `RJ.*` node (world transform at bind =
  `frame_world_bind`), `object1` = parent body, `object2` = child body, `disable_collisions` = true. Linear
  X/Y/Z limits 0…0. Angular: `limit_ang_x` = `[twist.low, twist.high]` (locked → 0…0), `limit_ang_y` =
  `[−swing1, +swing1]`, `limit_ang_z` = `[−swing2, +swing2]` (radians); "limited 0" → 0…0.
  The constraint axes are the empty's local axes, which is exactly the D6 frame (X twist, Y swing1, Z swing2).
- Solver: 60 steps/s, 10 solver iterations.

### F.3 Not representable in Blender's rigid-body constraints

- **Soft limits**: PhysX limit spring/damping act only *beyond* the limit; Blender's `GENERIC_SPRING` springs
  act around the rest angle. Export the numbers, use hard limits.
- **Swing cone**: PhysX couples swing1/swing2 as an elliptic cone and measures twist after swing; Blender
  limits three Euler angles independently — equal only for small angles.
- **Joint projection**, **muscles** (swing/twist position drives toward the animation), per-body
  kinematic/dynamic switching, unique collision groups and the 20×20 group matrix, PhysX damping semantics,
  max linear/angular velocity 200, `skinWidth`.
- `bs2` and `gogo_*` rigs are unusable as authored (all limits 0, masses 100): export shapes, flag
  `"untuned": true`, and suggest the `female` limits (same skeleton, same shapes).

---

## G. Not established, and what each would take

| item | what it takes |
|---|---|
| Impact → ragdoll decision for a living character (thresholds 6000 / 2000 / 500, height mask) and ragdoll damage, impact sounds | read `CharacterVisual.ModelCollisionContactAdded` 0x69d00a (large), `DetermineDamageReaction` 0x6a18d1, `CharacterRoot.command_give_ragdoll_damage_increment` 0x6914f2 |
| Bones without a body while ragdolled; exact blend | read the pose mapper 0x58edf9 / 0x58eea3 / 0x58f942 and `0x596525` |
| Explicit velocity hand-over at the kinematic → dynamic switch | read `CollisionNode::SetMovementType` → `RigidBody` slot 12 0x4fe677 (raise/clear body flag) and check for a velocity write; or a capture |
| Get-up position checks, expand volume | `VerifyCharacterLocation` 0x6a01d4, `solveStaticObject` 0x6a10cb, `staticDynamicOverlap` 0x6a0a60, `dynamic_getup_logic` 0x728e00, `CharacterExpandVolume` 0x66d0ec |
| How `PELVIS_ROTATION` is formed from the pelvis axes (which axis = "face up") | read lines 1088–1310 of 0x6bc3e2 (vector algebra); needed only to reproduce clip choice offline |
| Controller slope limit value; step limit after init | find the writers of `CharacterController::SetSlopeLimit` 0x4fe288 / `SetStepLimit` 0x4fe2cb in the script (`m_ninitsteplimit` user) |
| Assembly of the move velocity from `GamePivot` motion, push-back, rotation clamps | finish `CharacterRoot.StateActive` 0x6b367a (also WP3's item) |
| Push/wall/feedback rules and numbers; DCC joint parameters | read `CollisionContactAdded` 0x67c845, `FeedBack` 0x681e7b, `command_detect_wall` 0x67b508, `DccJoint` 0x6a3d71 (4.9 kB), `DccUpdate` 0x680654 (6.2 kB) |
| Collision rows of the unique ragdoll groups (≥ 20), `command_set_safe_ragdoll_collision_groups` | resolve the 49 non-constant calls in 0x7dffbf from the disassembly; read 0x7df74a |
| NxShape vtable names; the 180 unclassified call sites | improve receiver tracking in `vcalls.py` (NxCloth, 92 slots, and NxMaterial, 23 slots, are named since from their own name strings: `docs/RAGDOLL_RIG.md` "Cloth") |
| Editor swing offsets (−9 / 60 / 10 / 30) — units and whether any file still has them | only if a file with a non-default `childSpaceOrient` turns up; none of the 44 models with joints (683 joints) has one |
| Corpse timers `_nragdolldeathtime` 3 s / fail-safe 15 s | find their users in `CharacterVisual` (`_nragdolldeathtimer`) |
| Run-time verification of any of the above | a capture; none was used in this work package |

---

## Errata (2026-10-04, from the implementation pass — details in `findings/impl_ragdoll.md`)

1. **0.5(b) is wrong.** `kapow_fragment_keys.pkl` does contain the D6 swing keys (0xe3ba246d, 0x6f1c1d46,
   0x96f40d0c, 0x1c2a4efb and the six restitution / spring / damping hashes) in 1.3.0, 1.5.0 and 1.6.0. I read
   a stale `CharacterRootTemplate_Enemy.fragment.json` on the PC, written by an older toolkit. The current
   binary parse of that fragment names every key (0 `key_…` left) **[data, re-checked on the PC]**.
2. **A.2 / F, shape size.** The engine grows every primitive by 0.025 and sets skinWidth 0.025. That is the
   SDK's own recipe for hiding the permitted sinking-in ("inflate the size of physics objects with respect to
   their graphical representation", PhysX documentation, *Skin Width*). The surface things rest on is therefore
   the **stored** size. Check **[data]**: at the stored size no two bodies of any of the 13 rigs overlap in the
   bind pose unless a joint connects them; at the grown size 4–7 pairs per rig do (up to 4.6 cm). A solver
   without a skin width must use the stored size.
3. **B.3 item 3, velocity at the switch — now read.** `RigidBody` slot 12 0x4fe5ed: `wakeUp([0xa23680])`, then
   `clearBodyFlag(NX_BF_KINEMATIC)` when the old type was 1, else `raiseBodyFlag(0x80)`; a change from or to
   static recreates the actor (slot 18). No velocity is written **[code]**. The SDK text says a kinematic
   actor "lacks real velocity" and that after a move "the velocity is returned to zero" **[SDK documentation;
   the 2.8.1 run-time behaviour was not captured]**.
4. **B.3, bones without a body — now read** **[code]**: the mapper table (0x4b96da → `AddMapping` 0x58f942) has
   one entry per body {body index, bone index, offset}. `0x58edf9` writes each mapped bone's model-space
   transform (`0x5958c3`), after `0x595704` has marked all its descendants "model-space stale" (those that had
   an explicit model-space value get their local value rebuilt first, 0x594392). A stale bone is recomputed as
   local × parent (0x5936e2). So an unmapped bone keeps its animated local transform under its nearest mapped
   ancestor. When every bone is mapped, `0x58eea3` writes all of them directly.
5. **A.4 / G, unique ragdoll groups — now read** (lifted script, `PhysicsSimulation`): pools 20–23
   (`GetRagdollNonDynamicCollisionGroup` 0x7d82f0), 24–27 (`GetRagdollDynamicCollisionGroup` 0x7d837d), 28–31 in
   pairs (`GetRagdollPairedCollisionGroup` 0x7d823f). Rows: all three collide with WORLD 0, RAGDOLL_IN_WORLD 3,
   KINEMATIC_RAGDOLL 4; 24–31 also with DYNAMIC_WORLD 5; none with 1, 2, 6–11; a pair (g, g+1) not with each
   other. `StateRagdollDriven` asks for a group with both arguments 1 (pool 24–27),
   `command_pre_transfer_to_animation_control` with (1, 0) (pool 20–23). Unset pairs keep the scene default
   "same group only" (0x502fda), so a ragdoll's bodies collide with one another (not across a joint), and no
   `setActorPairFlags` call exists on this path (its only wrapper `PhysicsWorld::SetActorPairCollisionFlagMSG`
   0x514ddc has no script user).
