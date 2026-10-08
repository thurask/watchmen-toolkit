# Ragdoll rig

`watchmen.py characters` exports the ragdoll the game uses for each character: 17 rigid bodies
joined by 16 six-degree-of-freedom joints. It is data in the game's model files, not code, and
it is exported as stored. `--no-ragdoll` (or `WATCHMEN_RAGDOLL=0`) leaves it out.

## Where it is

| Place | Content |
|---|---|
| `<Variant>.ragdoll.json` | the whole rig: skeleton, bodies, shapes, joints, material, collision groups, conventions |
| GLB node `ragdoll` (in no scene) | `RB.<bone>.<i>` proxy meshes and `RJ.<child bone>` empties, each with `extras.watchmen.ragdoll` |
| GLB `asset.extras.watchmen.ragdoll` | format, body and joint counts, total mass, `tuned`, sidecar name, source model |

In Blender the helpers are in the collection "Orphan Nodes", which is switched off (together
with the `OUTFIT …` and `WPN_…` alternatives). Switch it on to see them. The proxies have an
Armature modifier on the body armature `root` and follow every clip; the `RJ` empties are
children of the empty `ragdoll` and stay at the bind pose.

The rig comes from the model in slot 0 of the character's model list: the skeleton model for the
enemies, the body model for Rorschach and Nite Owl, `BS2_WithoutWeapon` for the Twilight Lady.
`tuned: false` marks a rig nobody authored (Twilight Lady: every mass 100, every limit 0).

| Source model (slot 0) | GLBs | Total mass kg | Proxy nodes |
|---|---|---|---|
| `Female_Skeleton` | Dominatrix_1 … 10 | 85 | 32 |
| `Medium_Skeleton` | Heavy, KnotTop_Medium | 85 | 28 |
| `Large_Skeleton` | KnotTop_Large | 120 | 32 |
| `Small_Skeleton` | KnotTop_Small | 75 | 17 (convex meshes) |
| `Large_Gimp_Skeleton` | Gimp1, 2, 7 – 11 | 185 | 32 |
| `Rorschach`, `Rorschach_Dry` | Rorschach, Rorschach_Dry | 85 | 30 |
| `NightOwl_No_Mask`, `NightOwl_No_MaskDry` | NiteOwl, NiteOwl_Dry | 175.89, 81.89 | 43 |
| `BS2_WithoutWeapon` | TwilightLady | 1700 (untuned) | 32 |

Every rig has 17 bodies and 16 joints (`RJ` nodes). The `ragdoll` node sits beside the
`alternatives` node that holds the hidden outfits and weapons; both are outside the scene.

## Units and frames

- Metres, kilograms, seconds. Limit angles in degrees; `blender.*` limits in radians.
- Values are in the GLB's own space (+Y up).
  - Default, `coordinate_frame: "right-handed-true"` (top of the sidecar, and in the GLB's
    `asset.extras.watchmen`): x = −engine x. Every position, convex-mesh vertex, quaternion, axis
    and matrix is the file's value reflected (positions with x negated, quaternions (x, y, z, w) →
    (x, −y, −z, w), matrices S M S with S = diag(−1, 1, 1)).
  - `--frame mirrored` (no `coordinate_frame` key): the engine's numbers unchanged, a mirror image
    like the GLB of that frame.
- **Limits are the same numbers in both frames**, the twist range `low..high` included. A joint
  frame F of the file becomes S F S, a proper rotation whose axes are −S X (twist), S Y, S Z; a turn
  about the twist axis keeps its sign under that change, and the swing limits are symmetric
  half-angles, so their change of sign cannot show.
- Quaternions are xyzw in the engine's convention. The engine composes world = local (x) parent and
  rotates a vector as conj(q) v q; for a library that rotates q v q*, use the conjugate.
- A body's frame is its bone's frame. A shape's `local_pos` / `local_quat_xyzw` are in that frame.

## Platforms

Xbox 360 and PS3 models hold the same section in big-endian; the byte order is read from
the header's class-name length (`ragdoll_rig.byte_order`). Part 2 on both consoles gives
26 of 26 sidecars byte-identical to the PC ones; the PS3 build of Part 1 gives 80 of 80.
The standalone Part 1 (PC, Xbox Live) stores the same section with untyped property
records; it is read the same way and gives 80 of 80 rigs on both sets (Xbox 360 equal to
the PS3 Part 1 sidecars on 80, PC on 43; the other 37 differ by one bit of one stored
float). A character without a rig gets one log line per GLB
(`note: no ragdoll rig for <Variant>.glb: <model>: <reason>`) and the reason in the GLB
under `asset.extras.watchmen.not_decoded.ragdoll`. Reasons that line can give: a header
of neither layout, no articulated body, a body that does not match its records, the
slot-0 model not in the extract, a read error (those are `WARNING:` lines).

## Bodies and shapes

Per body: `mass` (the mass the body has in the game: the game's script sets a mass only on
the two character capsules of a paired move, 5.0 and 50.0, and on nothing of the ragdoll.
Native direct stores to `RigidBody` +0xa0 are the constructor 0x4fe311 (100.0) and `SetMass`
0x4fe514 (floor 0.1) only (byte scan of direct stores; copies through virtuals not scanned)), `linear_damping`, `angular_damping`
(PhysX coefficients, 1/s),
`solver_iterations_file` (4) and `solver_iterations_runtime` (10, what the game sets when the
ragdoll starts), and its shapes. Friction 0.6 and restitution 0 come from the pivot sheet
(`common.material`). The engine uses the one friction value as both static and dynamic
friction and combines two materials by multiplying (NX_CM_MULTIPLY; restitution by averaging),
read from 0x51555a (`common.material` says so: `static_friction`, `dynamic_friction`,
`friction_combine`, `restitution_combine`). Two ragdoll bodies rub with 0.36; a ragdoll on a
surface whose node has the `Default` sheet rubs with 0.54. A node without a sheet uses the SDK
default material, whose values were not read.

Each shape has three size records:

| Record | Meaning |
|---|---|
| `file` | as stored: capsule `diameter` and `height_total`, box `size_full`, sphere `radius`, convex mesh vertices |
| `physx` | what the engine creates: every size grown by 0.025, with a skin width of 0.025 (shapes may sink into each other that far) |
| `contact` | the stored size in PhysX terms (capsule `radius`, cylinder `height`): where surfaces come to rest |

Use `contact` in a solver without a skin width (Bullet, Blender). The proxy meshes have this size.
At it, no two bodies of a rig overlap in the bind pose unless a joint connects them. A capsule's
axis is the shape's local +Y.

## Joints

Every joint is a PhysX D6 joint between a parent body and a child body, anchored at the child
bone's origin. Linear motion is locked. The joint frame's X is the twist axis, Y swing1, Z swing2;
in the child bone these are −X, −Y, +Z. `swing1` and `swing2` give a half-angle about the bind pose,
`twist` a low..high range. A limit with `spring` > 0 is soft: the joint gives way beyond the angle
against that spring. A limit of 0 with spring 0 is a lock. The two bodies of a joint do not
collide with each other; other bodies of the same ragdoll do.

`RJ.<child bone>` is an empty at the joint frame in the bind pose: its +X, +Y, +Z are twist,
swing1, swing2.

## Cloth

`cloths[]` of a rig: `node_index`, `mesh_index`, `mesh_format`, `attachments`,
`world_fixes_applied`, `world_fixes_rule`, `properties` (as stored) and
`physx` (what the engine's cloth descriptor holds beyond them). Six Part 2 models carry cloths
(measured on all 740 `.model` files of each Part 2 set; the values hold for all six sets, and
`Curtains_01` exists only in Part 2): Rorschach and Rorschach_Dry (`beltCloth`, `coatCloth`),
NightOwl_No_MaskDry and NightOwl_No_Mask (`Cape01`), `props/common/curtains/Curtains_01`
(`Plane01`) and the unused `Rorschach_PoseRe02`. A model with cloths but no ragdoll is built
only on request: `python -m wlib.ragdoll_rig Curtains_01.model` (`build(mb, cloth_only=True)`);
the character export does not write a sidecar for it.

**Descriptor** (read from code, `Physics::Cloth` 0x50c95f): thickness, density, bending and
stretching stiffness, damping coefficient, pressure, collision response coefficient,
min adhere velocity and solver iterations are the cloth's properties. **Friction is that of the
owning node's pivot sheet** (0x4f5d6a), 0 if none; it is not a cloth property (0.6 for both
players through `Ragdoll_All` of `default.pb`: inferred, the sheet assignment was not
re-measured). Constants (`physx`): tear factor and attachment tear factor 1.5, attachment
response 0.2, to / from fluid response 1, wake-up counter 0.4, sleep linear velocity −1, scene
1 (the cloth scene). The mesh data is the position buffer with flags 1 (16-bit indices; the
name is from the SDK header, inferred). Group mask 0 at creation, set afterwards. The NxCloth is created only
while the node's byte +0x44 (`runFrameUpdate`, default 1, 0x513609) and the physics flag
`*(0xe1528c)+4` are set and, for a format 6 buffer in character mode, the float at +0x11c
(`physicsBlendFactor`; offset inferred from the constructor order) is non-zero (0x50c95f).

**Flags** (`physx.flags`, 0x50cd45–0x50cdee; labels from the executable's strings):

| property | value | NxClothFlag bits |
|---|---|---|
| `useGravity` | true | 0x20 |
| `dampingType` | 1 "Global" | 0x100 |
| | 2 "Local" | 0x4100 |
| `collisionType` | 0 "None" | 0x4 (collision disabled) |
| | 2 "Two-way" | 0x200 |
| `isSelfColliding` | true | 0x8 |
| `bendConstraintType` | 1 "Distance based" | 0x40 |
| | 2 "Angle based" | 0xc0 |
| `isPressurized` | true, and the mesh is closed (mesh+4 == 0; inferred meaning) | 0x1 (`pressure_flag_if_mesh_closed`; not in `flags`) |
| `useMinAdhereVelocity` | true | 0x40000 |

Shipped: Rorschach `beltCloth` 0x160, `coatCloth` 0x168; NightOwl_No_MaskDry `Cape01` 0x60
(`dampingType` 0: no damping flag); NightOwl_No_Mask `Cape01` 0x168; Curtains_01 `Plane01`
0x4164.

**Constructor defaults** (0x507bc0, constants from exe bytes): solver iterations 5, gravity on,
density / stretching / pressure / bending 1, thickness 0.04, collision type 0, collision
response 0.2, damping type 2 with coefficient 0.02, bend constraint 0, min adhere velocity 0,
`characterClothMode` true, `physicsBlendFactor` 1, illumination map top / bottom 0.9 / 0.3,
`useAnimForCollision` true, `maxAnimPenetration` 0.02, collision map top / bottom 1.0 / 0.5.

**Attachments** (`{vertex, cloth_body_node_index, world_fixed}`; read from code): the stored
value 0xFFFFFFFF is a world fix point (0x507dd0: `freeVertex`, then
`attachVertexToGlobalPosition` at the bind position × the cloth matrix (+0x4c..+0x84), skipped
when the cloth's vertex buffer is format 6 (skinned) and `characterClothMode` is on (0x4b96bc →
0x4b6e9f; the two PhysX names are inferred from the call shapes)); any other
value is the node index of a cloth-scene body the vertex is pinned to (0x517b06 / 0x507f08,
`attachVertexToShape` on that body's first shape, two-way only if `collisionType` == 2).
Measured: Rorschach 2 = Pelvis (12 and 25 vertices), Nite Owl 5 = Spine2 (22), Curtains_01 74
world fixes. Curtains_01's cloth buffer is format 5, so its 74 fixes are applied
(`world_fixes_applied`). The character cloths are format 6 and have no world fix (measured).
`mesh_format` is the stored FORMAT of the cloth's buffer (LOD 0 submesh `mesh_index` of part
`node_index`), `world_fixes_rule` the rule in words.

**Per frame** (read from code, `UpdateCharacterCloth` 0x5095d4; S = skinned position, P =
simulated position from the buffer `UpdateRenderPose` 0x507d96 fills, paint = the per-vertex
painted vector):

    wp = clamp01((paint.x − illuminationMapBottom) / (illuminationMapTop − illuminationMapBottom))
    if useAnimForCollision and the vertex is more than maxAnimPenetration behind the skinned plane:
        wp −= 1 − clamp01((paint.y − collisionMapBottom) / (collisionMapTop − collisionMapBottom))
    w   = clamp01(wp) · physicsBlendFactor
    new = S·(1 − w) + P·w          (written back with setPositions; velocity = (new − previous) / dt)

Each of the two weight functions returns the bottom value unmapped when top == bottom. The call
order of `UpdateRenderPose` and `UpdateCharacterCloth` within a frame was not traced.

**Script rules** (read from the lifted `CharacterRoot`; constants from exe bytes). Rorschach
(character type 0): only the blend-in, each cloth gets default × min(timer / blend-in time, 1).
Nite Owl (type 1), every frame: startup = min(timer / blend-in time, 1); the yaw rate of the
`Spine2` body clamped to 3..12 lowers a factor from 1.0 to 0.85, which caps the timer; a
position history (0.25 new + 0.75 old) in the visual's local frame, scaled by
(`m_nclothsideways`, `m_nclothupward`, `m_nclothfrontways`) = (100, 1.2, 35), becomes the
cloth's external acceleration. Environment cloth (`command_update_environment_cloth` 0x667aca):
impulse = (1 − d / r) · multiplier · capsule linear velocity, radius 1.5, multiplier 2.0 (Part 2
`GameEssentials`; Part 1 has no such values).

## In Blender

The stock importer turns the file's axes (x, y, z) into (x, −z, y). An object's own axes come out
as (x, z, −y), so:

- a capsule proxy's axis is the object's local Z, a box's half extents read (x, z, y);
- on an `RJ` empty, twist is local X, swing1 local Z, swing2 local Y (reversed; the limits are
  symmetric).

`extras.watchmen.ragdoll.blender` on each `RJ` node holds a ready mapping for a rigid-body
constraint of type GENERIC placed at the empty: `object1` = parent bone, `object2` = child bone,
`limit_ang_x` (twist), `limit_ang_y` (swing2), `limit_ang_z` (swing1), linear limits 0,
`disable_collisions`. `blender_bind_world_matrix` / `blender.bind_world_matrix` are the frames in
Blender world space at the rest pose.

Settings that work (Blender 5.0 and 5.2.2, checked by dropping and by releasing from a clip):

- shape size `contact`, collision margin 0; one rigid body per bone, a compound parent when a
  bone has several shapes;
- damping = 1 − exp(−c) for both coefficients (checked: the speed follows exp(−c t));
- 10 substeps per frame at 60 fps, 10 solver iterations. With 1 substep the joints come apart by
  centimetres. Built from the true-frame sidecar alone (Dominatrix_1): held by the head for 60
  frames the anchors stay within 0.22 mm and the peak speed is 2.3 m/s; with 1 substep they open
  by 15 mm;
- create the constraints while the bodies are in the bind pose. Blender fixes a constraint's
  frames at the first simulated step;
- when releasing from an animated pose, widen each limit to contain that pose. The game's limits
  are soft and nearly every clip holds poses outside them; Blender's are hard.

Blender cannot reproduce: soft limits, the swing cone and twist (it limits three Euler angles,
which match only near the bind pose), joint projection, the skin width, the collision group
matrix, the muscles that pull a ragdoll toward the animation.

## While the game runs

- Animated: the bodies are kinematic and follow the bones (collision group 4 for enemies, 8
  Rorschach, 9 Nite Owl).
- Going limp: the bodies become dynamic where they are. Neither the game (0x4fe5ed) nor PhysX
  `Body::setKinematic(false)` (DLL 0x10037f30, branch 0x100380a7) writes a velocity: the branch
  restores mass, both dampings and the maximum angular velocity, clears 0x30 bytes at body
  +0x23c and frees the kinematic target; 0x10035c00 only marks the body's group root (read from
  code). Measured on 12 switches of the 48-bone Dominatrix skeleton (`KapowMulti.1.trace` last
  animated frames 3484, 3537, 4405, 5518, 6556, 6826; `KapowMulti.2.trace` 4723, 5378, 5638,
  6106, 8406, 8901; frame = the `atx dump` argument): the node matrix stops for good and the
  pose is held for one frame (35, 37 or 48 of 48 bones move under 1 mm). Over the next three
  frames the mean bone speed is 0.8–5.0 m/s, against 0.6–14.0 m/s in the last animated frame;
  no switch starts from rest. The per-bone velocity field (mean removed) correlates 0.81–0.98
  with the last animated frame in 7 switches, 0.60 in one and −0.08 to 0.42 in 4, independent of
  the animated speed. That a body keeps the velocity of its last kinematic move unless
  `StateRagdollDriven` (0x69ed7c) overwrites it is inferred; the per-body velocity in the frame
  the flag is cleared is not established. Trace 1 frames 5136–5155 are an animated fall (the
  node moves every frame at constant height, mean vertical velocity near −3 m/s for eight
  frames). `KapowMulti.3.trace` frames 3042–3055 (a Heavy) were not analysed. Frame time: see
  `tools/apitrace/README.md`.
- A bone with a body takes the body's transform. Every other bone keeps its animated local
  transform and rides its nearest ancestor that has a body.
- An active ragdoll is in a collision group of its own (`common.collision_groups.unique_groups`):
  it collides with the world, dynamic props, other characters' kinematic bodies and corpses, not
  with the gameplay capsules.

### Get-up failure and corpse settle

Read from code (PC).

- While ragdoll-driven, the character takes 100000 damage when the get-up volume's overlap
  counter reaches 3 (+1 per 0.1 s of overlap), when `_nragdolldeathtimer` exceeds 3.0 s (it runs
  while the pose moves less than 0.001 m and a second, undecoded count condition holds), or when
  `_nragdolldeathfailsafetimer` exceeds 15.0 s.
- `CharacterRoot.StateDead` 0x6bb12a: a 3.0 s countdown runs while the ragdoll mean speed is
  below 0.1 m/s, on insta-death, or below the kill height (kill node y, else −100.0), and is
  otherwise reset; a 30.0 s limit always runs. A playable or placeholder character then waits
  indefinitely with no clean-up. Others broadcast game event 0xcf and are stripped (root
  fragment, children, LOD registration, articulated body); the corpse entity is kept.

## Command line

    watchmen.py ragdoll MODEL [PIVOTBOOK.pb] [OUT.json]

prints (or writes) the same document for one `.model`; exit code 1 when the model has no rig.
