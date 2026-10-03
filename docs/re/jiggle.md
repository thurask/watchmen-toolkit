# Topic C — jiggle (secondary motion) from the exe side

Evidence tags: **[code]** read from the exe (decompilation plus capstone for every constant and branch quoted),
**[data]** measured on the user's files (read-only: skeleton models, bind npz, capture palettes), **[inferred]**, **[not established]**.
Constants table: `findings/jiggle_constants.json`. Scratch: `work/jiggle/`.

## Verdict on the ≈1.7 factor

**No constant in the exe explains it, and none is expected to.** Nothing the game hands to PhysX is scaled (spring and damping go in
verbatim, only limit angles are converted deg→rad), and the write-back from the simulated body to the bone has no gain.
What the exe shows instead is that our model differs from the engine in geometry and drive, in ways that change amplitude:

1. the pivot is the **parent bone origin** and the bone is written back with **translation as well as rotation**; we pin the bone origin and rotate about it;
2. our lever `r = tb[k]` is the bone's bind position measured from the **model origin** (0.346 m for the breasts), not the parent→bone offset (0.132 m);
   the same wrong length sets our angle clamp (13.2° instead of 35.2°);
3. the game **cancels gravity** on the jiggle bodies every frame; we drive with gravity;
4. the PhysX substep is 1/60 s; our "2 substeps → 1/120" softening has no basis in the exe.

All four are confirmed independently by the capture palettes (§5). The effective stiffness/damping the PhysX solver produces from
k = 200, d = 0.8 on this body cannot be derived from the exe (it is inside PhysXCore) — that part stays empirical.

## 1. Setup — `CharacterAddonCtrl` 0x6574cd **[code]**

Per addon i (count = `[0xe171f4]+0x10 → +0x78`): parent bone list `Spine2, Spine2, Spine, Head`, child bone list `BreastL, BreastR, JiggleBelly, Hair`
(string 0xa3f008). For each child bone that exists, a record `{boxA, boxB, jointNode, limit}` is created:

| | box A (record[0]) | box B (record[1]) |
|---|---|---|
| node class | `MockupBox` | `MockupBox` |
| size props 0x33aba79c / 0x7801dabd / 0xdaec7a56 | **0.1** each (f32 @0x9e664c) | **0.8** each (f32 @0xa06d84) |
| `RigidBody::SetMass` 0x4fe514 | 0.1 | 0.1 |
| placed at | parent bone world pos/orient (`FUN_004b0557` / `FUN_004b0582`) | child bone world pos/orient |
| movement type (prop 0x61f13948) | 1 | 1 here, **2 (dynamic)** in initialize_external 0x648d58 |

Docs said "0.1³ MockupBox": that is the anchor box; the simulated body is the 0.8 m cube.
An `EmbeddedJointNode` is created as a **child of box A** (0x657c..: parent argument = record[0]); `record+0xc` = distance limit from the
PhysicsWorld block (+0x24 breast, +0x30 belly, +0x3c hair).

`SetMass` stores `max(arg, 0.1)`; no other RigidBody property is set, so the constructor defaults apply (0x4fe311):
numSolverIterations **4** (+0x9c), linearDamping **0.0** (+0xa4), **angularDamping 1.0** (+0xa8), max linear / angular velocity **200** (0x9e615c).
Actor creation 0x506b79 (0x50722f–0x5072a4): `actor->vtbl+0xcc(0.0, mass)` (update mass from shapes with total mass, **[inferred]** from the argument pair),
then linear damping, angular damping, max angular velocity. So mass 0.1 with the inertia of the body's shapes; if the shape is the
0.8 m box, I_cm = m·s²/6 = 0.0107 kg·m² **[inferred]**.

## 2. Joint — `CharacterAddonCtrl.initialize_external` 0x648858 **[code]**

Setter ↔ name mapping from the D6Joint property table `FUN_0051ff66` (now in the dump).

    EmbeddedJointNode.SetChildNode (0x4a6e1c, node+0x130) = box A
    EmbeddedJointNode.SetParentNode(0x4a6e6c, node+0x134) = box B
    Joint flags (0x516722 +0x54, 0x5166a2 +0x48, 0x516731 +0x3c, 0x5166b1 +0x3d) = 0   ; collision off, not breakable, no motors, no projection
    MainJointType  (0x517928) = 0 (D6)
    Swing1MotionType (0x51793a) = 1 Limited      Swing2MotionType (0x51794c) = 1 Limited
    TwistMotionType  (0x51795e) = 0 Locked       X / Y / Z MotionType (0x517970 / 0x517982 / 0x517994) = 0 Locked
    Swing1LimitSpring (0x5194ed) = k             Swing2LimitSpring (0x5195b0) = k
    Swing1LimitDamping (0x519516) = d            Swing2LimitDamping (0x5195d9) = d
    Swing1LimitValue (0x51947c) = 45.0 (0x9fffa8)   Swing2LimitValue (0x51953f) = 0

k, d per addon from the PhysicsWorld block: breast +0x1c / +0x20, belly +0x28 / +0x2c, hair +0x34 / +0x38.
The setters clamp spring and damping to ≥ 0 and limit values to [0, 180]; restitution stays at its constructor value 0.

**Descriptor fill** `0x5146ec` → `0x5141ee` **[code]**: motion enums copied (Locked 0 / Limited 1 / Free 2); a Limited axis copies its limit block
through `0x514611`: `value × [0xc8c574]` (**0.0174533**, deg→rad), restitution, spring, damping copied unchanged. Linear limit through `0x514637`, no scaling.
There is no multiplication of spring or damping anywhere on this path.

**Frames** (`EmbeddedJointNode` update 0x4a8dd5 → `0x51636c`, `0x49805d` → `0x516036`): both local frames are derived from the joint node's
world matrix, i.e. box A's frame = the **parent bone** frame. In the descriptor actor[0] = box B with anchor = box A's origin expressed in B,
actor[1] = box A with anchor (0,0,0); axes are X (twist) / Y (swing1) / Z (swing2) of that frame (captions "Twist around X", "Swing around Y", "Swing around Z").
So the body is a pendulum about the parent bone origin with lever = parent→child bone offset; translation and twist locked,
swing about Y free up to 45° then sprung, swing about Z sprung from 0.

## 3. Simulation parameters **[code]**

- Gravity: PhysicsSystem ctor 0x50d1e1 default (0, −9.82, 0) (0xa26418); `PhysicsWorld::SetGravity` 0x517ab4 writes node+0x58 and forwards. File value (0, −14.82, 0).
- Timestep: `FUN_004f4d20` accumulates the frame dt, `h = 1 / physicsIntegrationRateInHz`, `n = floor(acc / h)`;
  `FUN_004f4ddc` calls `scene->setTiming(h, maxPhysicsIntegrationTimesteps, fixed)` (vtbl+0x148) and simulates `min(n, maxSteps) × h`.
  Scene descriptor `FUN_004f49f8`: maxTimestep = 1/rate, maxIter = max steps, fixed stepping. With the file values: **h = 1/60 s, up to 3 steps per frame**.
- Solver iterations: 4 per body (default; `SetNumSolverIterations` 0x4fe4df is never called for the addon boxes).
- **Anti-gravity** (update 0x656fb4–0x65707c): every frame `force = −bodyB.mass × PhysicsWorld.gravity` is applied through
  `RigidBody::ApplyForce` 0x4f6b47 → `0x4f4463` → `NxActor vtbl+0x120(force, mode 0, wake 1)` (only when the body is dynamic).
  `FUN_005482e0` is the registered `PhysicsWorld::GetGravity` getter. Gravity therefore does not act on the jiggle bodies
  (exactly at one physics step per frame; behaviour over several substeps is **[not established]**).

## 4. Write-back — `command_update_addons` 0x6563a0 **[code]**

Per addon and frame:

1. box A is moved to the parent bone's world position and orientation (`0x47da30`, `0x483171`);
2. `p = conj(qA) · (posB − posA) · qA` — box B position in box A's frame; `q` = box B orientation relative to box A;
3. the anti-gravity force of §3;
4. `p0`, `q0` = the child bone's current (animated) **local** position and orientation (`FUN_004b05b3`, `FUN_004b05de`);
5. `δ = p − p0`, `len = |δ|`; if `len > limit`: `t = limit / len`, `p = p0 + δ·t`, `q = slerp(q0, q, t)` (`FUN_0041fd54`);
6. unless the addon-debug flag is set, `SetBoneLocal(childBone, p, q)` (`FUN_004ba7ad` → `FUN_004ba3e1`).

The bone's local **position and orientation** are both replaced by the box pose; there is no gain or multiplier.
The limit is a distance in metres on the bone origin, not an angle.

## 5. Checks against the user's data **[data]**

Levers (skeleton `.model`, engine-exact parse): BreastL / BreastR parent→bone offset 0.1323 / 0.1317 m; bind position from the model
origin 0.3460 m (what `jiggle_d6` uses as `r`); JiggleBelly 0.1015 vs 0.1929 m.

Capture palettes, child relative to parent (6000 sampled frames each):

| | BreastL | BreastR | JiggleBelly |
|---|---|---|---|
| rotation angle mean / p90 / p99 / max | 4.08° / 9.7° / 23.2° / 60.6° | 3.80° / 8.9° / 21.9° / 44.5° | 2.06° / 6.4° / 18.4° / 35.9° |
| bone-origin displacement mean / max | 12.7 mm / **80.0 mm** | 11.8 mm / **80.0 mm** | 4.5 mm / **100.0 mm** |
| least-squares fixed point of the relative motion (bind space) | (0.026, 0.255, −0.027) | (0.016, 0.252, −0.030) | (−0.002, 0.087, −0.008) |
| parent bone origin (bind space) | (0, 0.275, −0.012) | same | (0, 0.092, −0.003) |
| child bone origin (bind space) | (−0.094, 0.327, 0.065) | (0.094, 0.327, 0.065) | (0, 0.192, −0.015) |
| mean rotation vector | (−0.1°, 0.1°, −0.1°) | similar | ≈ 0 |

- The maxima equal the file distance limits (0.08 / 0.1 m) to four digits → §4 step 5.
- The fixed point sits at the parent bone origin, not at the child bone origin → §2 frames.
- The mean deviation is zero → no gravity sag, §3 anti-gravity. Our model has a constant sag of about 1.6°.
- Angles of 20–60° occur; our clamp caps the angle at `limit / |tb|` = 13.2° (breast) and 29.7° (belly).
  The engine's geometric bound for a pure rotation about the parent origin is `2·asin(limit / (2·lever))` = 35.2° and 59.0°.
- In the parent bone's frame the RMS rotation is 2.7° about X and 4.2° about each of Y and Z: the locked twist axis is the quiet one,
  the two swing axes respond alike. This supports keeping the swing response isotropic.

## 6. What stays unexplained

- The emergent stiffness and damping (capture fits near K ≈ 150–170 s⁻², D ≈ 11–19 s⁻¹). With k = 200 N·m/rad on a body whose inertia
  about the pivot is of order 0.012 kg·m² (0.8 m cube, 0.1 kg, lever 0.13 m — **[inferred]**), a rigid-spring reading gives a far stiffer system;
  how PhysX 2.8.1 treats a soft swing limit of value 0 next to a 45° one, and how its implicit spring behaves at h = 1/60, is not in the exe.
- Whether the addon force is applied on every substep when a frame takes several.
- Per-slot AnimSlot speed and anything else upstream is unrelated to jiggle.

## Proposed toolkit change (`wlib/jiggle_d6.py: apply_jiggle`)

Minimal, in order of confidence:

1. **Lever**: use the parent→bone offset, `r = tloc[k]` (already in the bind npz, parent-local), instead of `r = tb[k]`. This also fixes the
   frame mix-up in `np.cross(r, f_o)` (`f_o` is parent-local, `tb` is model-space).
2. **Clamp**: clamp the bone-origin displacement, not the angle: with `x` the deviation rotation, `δ = R(x)·r − r`; if `|δ| > limit` scale by
   `t = limit/|δ|` (position) and slerp the rotation by `t`. Replace `max_x = lim / rlen`.
3. **Write-back about the parent origin**: the palette of the jiggle bone becomes `T(c)·D·T(−c)·P_old` with `c` = world position of the parent
   bone origin (`P[i,p]·tb[p]`) and `D` the world deviation rotation — i.e. `P[i,k,:,:3] = Dm @ P[i,k,:,:3]`,
   `P[i,k,:,3] = c + Dm @ (P_old[i,k,:,3] − c)` — instead of re-pinning the origin with `jw − P·tb[k]`.
4. **Drop gravity from the drive**: `f_o = A_oᵀ·(−acc_o)`; keep the `−α_parent` term.
5. **Substep**: pass `dts = 1/hz` to `solver_soften` (or drop the softening and fit K, D once), since the exe steps at 1/60. This changes the
   effective constants and must be re-validated against the capture before it ships; items 1–4 are independent of it.
6. Remove `joint_frames()` / `mode='aniso'` inputs taken from the model's "joint records": those are collision capsules (`findings/skeleton_blobs.md`).
   The real swing axes are the parent bone's Y and Z.

After 1–4 the empirical amplitude factor should be re-measured from zero; it was compensating for the missing translation, the
short clamp and the gravity bias at the same time, so it is not expected to survive as a single number.
Docs to correct: "0.1³ MockupBox" (the dynamic body is 0.8³), "gravity (0, −14.82, 0) drives the pendulum" (cancelled per frame),
"dts = 1/120, 2 solver substeps" (no exe basis), "EmbeddedJointNode type-7 records are the D6 frames" (they are capsules).
