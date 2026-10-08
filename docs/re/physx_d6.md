# PhysX 2.8.1.1 D6 joint as the jiggle bones use it — what the solver does per step

Target: `physx/PhysXCore.dll` (image base 0x10000000). Game-side addresses are `KapowMultiDEDRM.exe`.
Evidence tags: **[code]** read from decompilation and/or disassembly at the address given (constants from DLL bytes),
**[inferred]**, **[not established]**, **[data]** measured on the capture palettes.
Machine-readable: `findings/physx_d6.json` (addresses, offsets, constants, all test results).
Scratch: `work/physx/` — `d6_ref.py` (reference integrator), `synth_tests.py`, `cap_eval.py`, `cap_var.py`, `cap_fps.py`,
`cap_belly.py`, `fit_pivot_to_ref.py`, `rtti.py`, `all.asm` (linear disassembly of all 7,813 functions).

> **Addendum (after the toolkit port, see `findings/impl_jiggle_solver.md`).** Three statements below are superseded:
> (1) the belly IS explained — the capture's one-step map matches the solver with the file's k = 70
> (0.899 / −0.778 / 0.798 captured vs 0.890 / −0.775 / 0.800), and the earlier trace deficit came from zero-step
> frames and from segments that start in mid-motion (1.34° rms vs 1.30° for the fitted model once both are handled);
> (2) the capture did not run at 60 fps: 5.9 % / 7.7 % of frames have a frozen jiggle palette (no physics step), i.e.
> about 64–65 fps on average — "60 fps fits best" below only means one step per frame;
> (3) frames without a physics step are observed in the captures, not hypothetical.

## 0. Answer first

1. **The jiggle joint has no drive.** The game sets every `driveType` to 0; the spring/damping file values go into the
   **soft swing limits** (`swing1Limit` 45°, `swing2Limit` 0°, both `LIMITED`). jiggle.md already said this; the task brief's
   "angular drive springs" is wrong. In PhysX two limited swing axes become one **elliptic cone limit**; with a 0° semi-axis
   the cone has zero radius, so the limit row is active whenever the swing is non-zero and pulls the whole swing (both axes)
   to zero. It is a **unilateral** row (impulse ≥ 0, toward the centre only).
2. The row is the textbook implicit soft constraint (found in the instructions, §2), with three things that are not textbook:
   the error is **tan(swing/4)** (≈ θ/4), the position term carries a hard-coded **0.7**, and the velocity that survives the
   step has the limit's position bias removed by a "conclude" pass. With 4 iterations the result is close to a **first-order
   relaxation** of the swing toward zero with rate `0.175·k / (d + k·dt)` — 8.5 s⁻¹ for the breasts, 6.2 s⁻¹ for the belly —
   not a second-order oscillator with the file's K and D.
3. **Is the capture-fitted stiffness explained?** For the breasts, yes in the sense that matters: the reference integrator
   (`work/physx/d6_ref.py`, file constants k = 200, d = 0.8, nothing fitted) reproduces the captures as well as the
   capture-fitted model (rot error 3.02° / 2.70° rms at 60 fps against 3.12° / 2.69° for the fitted pivot model; scanning k in the
   integrator, the file value 200 is the optimum). The numbers 570 s⁻² / 37.5 s⁻¹ themselves are **not** reproduced by a
   formula: they are the linear surrogate of a non-linear process, and the best linear surrogate of the integrator's own output
   is a flat valley around K ≈ 900, D ≈ 25–30 (570 / 37.5 is 9 % worse in that valley). For the belly the integrator is clearly
   better than the file-constant pivot model but worse than the capture-fitted one (2.2–2.5° against 1.96° rms) and the belly
   capture does not discriminate k at all — **not explained**, see §7.
4. There is no closed-form `file constants → (K_eff, D_eff)` for the toolkit's linear model. What can be given in closed form
   is §4 (relaxation rate, row coefficients). The recommendation is to port `d6_ref.py` (about 300 lines, numpy only).

## 1. Class map and descriptor path **[code]**

| what | address |
|---|---|
| `NpD6Joint` vtable / `loadFromDesc` (string "NpD6Joint::loadFromDesc") | 0x10290b5c / 0x10135430 |
| desc → internal structs, dispatch `joint->vtbl[0]` | 0x10147330 |
| `D6Joint` vtable (125 slots) / copy of the D6 block to `this+0x130…` | 0x10282ec4 / 0x1007ff40 |
| `D6Joint` prepare: *limited with value 0 **and spring 0*** → locked; `tan(limit/4)`, `tan(limit/2)` | 0x100804c0 |
| `D6Joint` → low-level desc (0x138 bytes) → `PxdD6JointCreate` | 0x10081ad0 → 0x101aa8a0 |
| `PxsD6Joint` vtables / ctor from low-level desc / cached tangents and counts | 0x102a1064, 0x102a0f9c (iface at +0x14) / 0x102271e0 / 0x10226580 |
| **`PxsD6Joint` constraint setup**, called once per substep as `joint->vtbl[1](rowBuffer, dt)` from the island solve 0x10201330 | **0x10227db0** (19 185 bytes) |
| angular row builder / linear row builder / soft-row modifier | 0x10227a70 / 0x10227640 / 0x102068b0 |
| solver core (`PxsSolverCoreGeneral` vtable 0x102a10d4) | 0x1022c8d0 |
| row iteration: linear (type 4) / angular (type 5); table 0x102bac18 | 0x1022ccb0 / 0x1022ce80 |
| row conclude: linear / angular; table 0x102bac38 | 0x1022d450 / 0x1022d500 |
| `PxfD6Joint` 0x1029c354, `PxnD6Joint` 0x1029e1c4 (pure-call base) | not traced |

`NxD6JointDesc` offsets (word indices read in 0x10135430, consistent with the game's fill 0x5146ec): actors +0x08/+0x0c,
localNormal +0x10/+0x1c, localAxis +0x28/+0x34, localAnchor +0x40/+0x4c, maxForce +0x58, maxTorque +0x5c,
solverExtrapolationFactor +0x60, useAccelerationSpring +0x64, jointFlags +0x70, x/y/z/swing1/swing2/twist motion +0x74…+0x88,
linearLimit +0x8c, swing1Limit +0x9c, swing2Limit +0xac, twistLimit low/high +0xbc/+0xcc (each `{value, restitution, spring,
damping}`), xDrive/yDrive/zDrive/swingDrive/twistDrive/slerpDrive +0xdc/+0xec/+0xfc/+0x10c/+0x11c/+0x12c (each `{driveType,
spring, damping, forceLimit}`), drivePosition +0x13c, driveOrientation +0x148, driveLinearVelocity +0x158,
driveAngularVelocity +0x164, projectionMode +0x170, projectionDistance +0x174, projectionAngle +0x178, gearRatio +0x17c,
flags +0x180. `PxsD6Joint` field offsets and the 0x80-byte solver row layout are in the JSON.

Motion enum is remapped in 0x10081ad0: Nx 0 locked / 1 limited / 2 free → low-level **2 / 1 / 0**.
0x100804c0 turns `LIMITED` into `LOCKED` only when limit value **and** spring are both 0; the game's swing2 (value 0,
spring k) therefore stays limited.

The high-level `D6Joint` also has large functions of its own (0x10082550, 17 258 bytes; 0x100868c0). That the low-level joint
is created and is what the island solver calls is **[code]**; that those high-level functions do not also act on a
software scene is **[inferred]** (not traced; the capture agreement in §5 supports it).

## 2. The row math **[code]**

### 2.1 Geometry — 0x10227db0

World joint frames from body pose × local frame (0x10227e..–0x102283..). `q = conj(q0)·q1` = frame 1 relative to frame 0;
components with |·| < 1e-4 (0x1028089c) are set to 0, sign flipped to w ≥ 0, renormalised.
Swing/twist split (0x10226ed0): `s = sqrt(qx² + qw²)`, `swing = (0, (qw·qy − qz·qx)/s, (qx·qy + qz·qw)/s, s)`.

Rows emitted for the game's configuration, in buffer order:

1. **twist locked** (count of locked angular axes = 1): axis from 0x10226e60 (X axis of the mean frame),
   `rhs = −2·qx / dt` (0x10280530 = −2.0), bilateral.
2. **cone limit** (swing1 and swing2 both limited, 0x1022bcf1–0x1022be9b), with y, z, w the swing quaternion:
   `fy = y²/(y²+z²)`, `fz = z²/(y²+z²)`, `limit = L1·L2 / (L1·fz + L2·fy)` with `L1 = tan(swing1/4)` (+0x15c),
   `L2 = tan(swing2/4)` (+0x160) (0.25 at 0x10280594, `fptan` at 0x102265e9), `e = sqrt(y²+z²)/(w + 1.0)` = tan(swing/4)
   (1.0 at 0x102802b4). Row emitted when `limit − 0.025005 < e` (0x102a0f84; `fcompp / test ah,5 / jp` at 0x1022bd73, so a NaN
   limit emits nothing). Axis = normalize(Y0·y + Z0·z) (frame-0 axes), `rhs = (limit − e)/dt`, **limit flag** (lo = 0),
   soft parameters = the two limits' spring/damping/restitution blended `S1·S2/(fy·S2 + fz·S1)` (= k, d when both equal).
   With L2 = 0: `limit = 0` whenever z ≠ 0, and `0/0 = NaN` when z = 0 exactly. Consequence: **the spring acts on the whole swing
   whenever the swing-2 component of q is ≥ 1e-4 (0.0115°), and not at all when it is below** — a pure swing-1 deviation is
   unrestrained. In real motion the z component is practically never below the threshold, which is why the captures show the
   two swing axes alike.
3. **three locked linear rows** (one block): if |d|² > 1.19e-7 (0x1028058c) the axes are d̂ and two perpendiculars
   (0x10227010), else the frame-0 axes; `rhs = −(n·d)/dt`, d = anchor separation.

### 2.2 Row coefficients — 0x10227a70 (angular), 0x10227640 (linear), 0x102068b0 (soft)

    m      = 1 / Σ_bodies (J · M⁻¹ · Jᵀ)          angular row: 1/(a·I⁻¹·a) with the body's WORLD inverse inertia about its COM
    B      = m · 0.7                               f32 @0x1029e1b8 (0x10227cba fmul)
    rhs    = geometric error / dt                  row+0x1c
    hi     = maxTorque (maxForce)                  row+0x74;  lo = −hi, or 0 for a limit row (row+0x78)
    sef    = solverExtrapolationFactor             row+0x5c

    soft, spring ≠ 0 (0x10227cde–0x10227d36):
    dd = max(damping, 1e-5);  a = spring·dt;  s = a + dd
    gamma = 1/(s·dt)  = 1/(dt·(d + k·dt))          erp = a/s = k·dt/(d + k·dt)
    0x102068b0(gamma, erp, improvedSpring, useAccelerationSpring):
        B *= erp
        force spring (useAccelerationSpring = 0):  f = 1/(m·gamma + 1);  c = m/(1/gamma + m)  [only if improvedSpring]
        acceleration spring:                       f = 1/(gamma + 1);    c = 1/(1/gamma + 1)
        B *= f;  m *= f

So spring and damping are **force quantities** here (N·m/rad, N·m·s/rad): the softness is scaled by the row's effective mass.
That effective mass is the cube's inertia about its **centre** (0.010667 kg·m²), not about the pivot; the lever enters only
through the three linear rows that the iterations couple to the angular one. `improvedSpring` = context byte +0xe5 =
`NX_IMPROVED_SPRING_SOLVER` (SDK parameter 98 > 0, read at 0x100c7d4d; default 1.0 at 0x100ac8d0).
Numbers at dt = 1/60: breast gamma 14.52, erp 0.806, f 0.866, m′ 0.009236, B 0.005214, c 0.1341; belly gamma 30.51,
erp 0.593, f 0.754, m′ 0.008048, B 0.003342, c 0.2455.

### 2.3 Iteration — 0x1022ce80 (disassembly 0x1022ce93–0x1022cf27), 0x1022ccb0

    t        = (target − J·v) · m                  target = row+0x7c (restitution bounce; 0 here)
    lambda_v = lambda_v + (t − c·lambda_v)·sef     row+0x6c
    dl       = (t − B·rhs − c·lambda)·sef
    lambda   = clamp(lambda + dl, lo, hi)          row+0x70
    v0 += M0⁻¹·J0ᵀ·dl ;  v1 −= M1⁻¹·J1ᵀ·dl

0x1022c8d0: `iterations` passes over all rows in buffer order (iterations = largest solverIterationCount of the island's
bodies, body+0xa8, read at 0x10201412; 4 here), then every solver body's velocity is copied to its "motion velocity"
(0x10206570), then one **conclude** pass per block (0x1022d500 / 0x1022d450): `rhs = 0` for bilateral rows,
`rhs = max(rhs, 0)` for limit rows, `c *= lambda_v/lambda` if |lambda| > 1e-10 (0x102a10dc), `sef = 1`, one more solve.
The pose is integrated with the motion velocity; the body keeps the post-conclude velocity (0x10206500, 0x102008a0).

### 2.4 Per-step update for one body on a kinematic anchor

Converged solver, limit row active, small swing φ about a fixed axis, I_p = inertia about the pivot, φ̇* = relative swing
rate after force integration and damping (algebra from §2.2–2.3: at the fixed point `J·v + gamma·lambda = −0.7·erp·rhs`):

    lambda = dt·[0.7·k·e + (d + k·dt)·φ̇⁺] ≥ 0,     e = tan(φ/4) ≈ φ/4
    φ̇⁺ = (I_p·φ̇* − 0.7·k·dt·φ/4) / (I_p + d·dt + k·dt²)     if lambda > 0, else φ̇⁺ = φ̇*
    φ⁺ = φ + dt·φ̇⁺

**[inferred from the code's formulas]**; I_p = 0.01242 (breast) gives φ̇⁺ = 0.150·φ̇* − 7.17·φ, whose slow mode decays at
9.4 s⁻¹. The limit only pushes inward, so the return can never be slower than the boundary `φ̇ = −0.175·k/(d + k·dt)·φ`
(8.47 s⁻¹ breast, 6.23 belly, 7.09 hair): the swing relaxes at about that rate. The exact 4-iteration arithmetic
(`d6_ref.py`) gives 0.87 per step = 7.9 s⁻¹ for a 5° step (table in §6), and removes most of the spring impulse from the kept
velocity (lambda_v relaxes by only c per iteration, so after 4 iterations it is far from its fixed point and the conclude pass cancels the bias impulse; seen in the integrator, final lambda = 0 from the third step of the step test): the
spring moves the pose, hardly the velocity. Force limit: `hi = maxTorque = FLT_MAX`, never reached.

## 3. Body integration and scene details

| item | finding | evidence |
|---|---|---|
| order in a substep | per island: `v += a·dt`, damping, velocity clamps (0x101ffb50) → solver bodies (0x102062d0) → joint rows → 4 iterations + conclude → pose integration (0x102008a0) | **[code]** 0x10201330 |
| angular damping | `ω *= 1 − c·dt` (0 if c·dt ≥ 1); linear likewise | **[code]** 0x101ffb50 |
| max angular velocity | `|ω|² ≤ atom+0x8c` in 0x101ffb50; SDK default 7.0 (param 7), the game calls `setMaxAngularVelocity(200)`. Pose integration clamps only at 1e18 (0x1029fb38) | **[code]** |
| pose integration | `x += v_m·dt`; `q = (sin(|ω|dt/2)·ω̂, cos(|ω|dt/2))·q` | **[code]** 0x102008a0 |
| forces | `addForce(NX_FORCE)` adds `F·invMass` to body+0x23c (0x100339b0); every substep takes the accumulator as acceleration; it is cleared only on the **last** substep of a simulate (0x10035330, flag from 0x100c35d0 `nbSubsteps == index+1`). The anti-gravity force therefore cancels gravity in every substep | **[code]** |
| frames without a physics step | the game calls simulate only when `floor(acc/h) > 0` (0x4f4ddc) but applies the force every frame, so above 60 fps the next step carries two forces: net +|g| upward for one step | **[code]** game + DLL; effect on screen **[not established]** |
| sleep | body flags 0x900 = visualization + energy sleep test; SDK defaults sleep energy 0.005, lin/ang vel² 0.0225 / 0.0196. The game's per-frame `addForce(…, wake = true)` keeps the body awake | defaults **[code]** 0x100ac8d0; wake path **[inferred]** from the argument |
| kinematic anchor | `moveGlobalPose` stores a target (0x10033430). On the first substep: `v = Δx/(n·dt)`, `ω = 2·acos(w)/(n·dt)·axis`, pushed to the low-level atom as its velocity; target flags cleared, velocity kept for all n substeps (0x10034c10, n from 0x100ca870) | **[code]** |
| kinematic deadband | if `|w − 1| ≤ 1e-6` (0x102a1990) the angular velocity is 0: an anchor rotation below 0.16° per frame is not executed until it accumulates | **[code]** 0x10034c10 |
| anchor in the solver | zero inverse mass / inertia, velocity entering J·v | **[code]** `Body::setKinematic` 0x10037f30 writes inverse mass 0, inverse inertia 0 and damping 0 to the atom; atom +0xa1 is the sleep flag (property 7; 0x10036240, 0x100369d0) |
| one-frame latency | not a PhysX delay: the anchor reaches its target at the end of the same simulate. The game moves the anchor (deferred target) and reads the body pose in the same update, so the pose it writes is the result of the previous simulate | **[code]** 0x6563a0 + 0x50bd0f + 0x10033430 |
| substeps | `n = trunc(residual/h + 1e-6)`, capped at maxIter, residual carried (0x10156240). With the game's `simulate(n·h)` the count is exactly n (checked in float arithmetic) | **[code]** |
| skin width / adaptive force | skin width 0.025 (game sets the same value); adaptive force scales accelerations by 1/contacts only for bodies in contact (0x10035330) | **[code]**; whether the 0.8 m box touches anything **[not established]** |

## 4. Effective dynamics for the game's setup

Body: cube 0.8 m, mass 0.1, I_cm = 0.010667; lever 0.1323 m (breast) / 0.1015 m (belly); dt = 1/60; 4 iterations.

| | breast (k 200, d 0.8) | belly (k 70, d 0.8) | hair (k 100, d 0.8) |
|---|---|---|---|
| relaxation rate `0.175·k/(d + k·dt)` | 8.47 s⁻¹ (τ 0.118 s) | 6.23 s⁻¹ (τ 0.161 s) | 7.09 s⁻¹ |
| converged linearisation of §2.4 as pivot-model constants (K, D at 60 Hz, incl. angular damping) | 430 s⁻², 51 s⁻¹ | 275 s⁻², 44 s⁻¹ | 338, 48 |
| best linear pivot-model fit **to the integrator's output** on the capture parent motion (55 / 60 fps) | K 900, D 25–30 (residual 1.7° of 3.4° rms) | K 570–650, D 15–19 (residual 1.2° of 1.8°) | — |
| capture fit (impl_phys, 55 fps) | 570, 37.5 | 308, 19.2 | — |
| capture fit rescaled to 60 fps / 30 fps (K ∝ fps², D ∝ fps) | 678, 40.9 / 170, 20.5 | 366, 20.9 / 92, 10.5 | — |

The three model rows disagree with each other because the process is not linear (unilateral row, position-level action);
a linear (K, D) pair depends on the excitation. The capture-fitted values are of the same order as every code-derived
surrogate and are not reproduced exactly by any of them. Rigid readings such as K = k/I ≈ 16 000 are wrong by the factor
tan(θ/4) ≈ θ/4, the 0.7 and the implicit softening.

## 5. Decisive test — capture traces **[data]**

Method of `work/impl_phys/harness.py` (captured parent motion in, bone compared frame by frame), capture files staged
read-only (`track_NN_pals.npy`, `gimp_captured_palettes_t2.npy`, binds). Reference = `d6_ref.apply_jiggle_ref`, file
constants, nothing fitted, game frame order and metre clamp included. Tracks 23 and 39 excluded for the breasts as in impl_phys.

| model (55 fps unless noted) | BreastL rms / corr / lsq | BreastR | JiggleBelly |
|---|---|---|---|
| pinned (toolkit default) | 5.16° / 0.35 / 0.34 | 4.72° / 0.38 / 0.36 | 4.09° / 0.26 / 0.16 |
| pivot, file K/D + latency | 4.81° / 0.56 / 0.45 | 4.46° / 0.60 / 0.45 | 3.26° / 0.44 / 0.32 |
| pivot, capture-fitted K/D + latency | 3.12° / 0.72 / 0.98 | 2.69° / 0.76 / 0.96 | 1.96° / 0.63 / 0.87 |
| **PhysX reference, file k/d** | 3.11° / 0.72 / 0.95 | 2.83° / 0.73 / 0.89 | 2.52° / 0.36 / 0.49 |
| PhysX reference at 60 fps | **3.02° / 0.74 / 0.96** | **2.70° / 0.76 / 0.90** | 2.35° / 0.45 / 0.61 |
| PhysX reference at 30 fps | 3.40° / 0.65 / 1.08 | 2.93° / 0.70 / 1.07 | 2.16° / 0.51 / 1.04 |

All tracks (incl. 23, 39) at 55 fps: reference 4.29° / 4.23° / 2.52°, fitted pivot 4.29° / 4.13° / 1.96°.
Origin error (excl.): reference 6.2 / 5.7 mm, fitted pivot 6.2 / 5.6 mm.

- Scanning k inside the integrator at 60 fps (BreastL rms): k 20 → 9.0°, 40 → 6.3°, 70 → 4.7°, 120 → 3.4°, **200 → 3.02°**,
  400 → 3.11°. The file value is the optimum. d = 3.0 instead of 0.8: 3.5°.
- Variants (55 fps, BreastL): 2 iterations 3.11°, **4 → 3.11°**, 8 → 3.31°, 16 → 3.69°; improved spring off 3.34°; bias 1.0
  instead of 0.7 3.30°; angular damping 0.05 3.26°; acceleration spring 19.6° (rejected). The traces confirm the reading but
  separate the fine variants only weakly.
- Frame-rate scan of the parameter-free integrator: breasts best at **60 fps** (3.02°), 55 → 3.11°, 50 → 3.32°, 45 → 3.38°,
  70 → 3.64°. This suggests the breast capture ran at 60 fps (one physics step per frame), not 55 **[inferred]**.
- Belly: flat (2.14–2.52°) over frame rate and over k; the fitted linear model stays better. See §7.

## 6. Synthetic tests (60 fps; `work/physx/synth_tests.txt`, `.json`)

Parent frame = joint frame (X twist, Y swing1, Z swing2); child deviation relative to the parent of the same frame.
"pinned" has no capture constants (`mode='capture'` raises, K_eff/D_eff overrides are ignored).

Step, parent rotated 5° about Z in one frame, breast (deviation in deg at frames +0…+12, +20):

    PhysX ref   -5.00 -5.00 -4.39 -3.82 -3.32 -2.87 -2.49 -2.15 -1.85 -1.59 -1.34 -1.10 -0.86 | +0.21   settle(<0.5°) 0.233 s
    pivot file  -6.25 -3.35 -3.48 -2.19 -1.18 -0.41  0.17  0.57  0.84  1.01  1.08  1.10  1.07 | +0.35   0.317 s
    pivot capt  -6.25 -2.77 -1.65  0.28  0.96  1.06  0.93  0.74  0.55  0.39  0.27  0.18  0.12 |  0.00   0.150 s
    pinned file -3.58 -3.44 -1.93 -0.78  0.08  0.68  1.09  1.35  1.49  1.54  1.54  1.48  1.41 | +0.74   never (gravity sag 0.55°)

Belly, PhysX ref: −5.00 −5.00 −4.61 −4.18 −3.78 −3.41 −3.07 −2.76 −2.48 −2.20 −1.92 −1.65 −1.39 (settle 0.267 s).
Step about X (twist): followed within one step by ref and pivot. Step about Y alone: the reference does not return at all
(§2.1, swing-2 component exactly 0); a mixed Y+Z axis behaves like Z.

Sinusoid, parent rotation ±5° about Z — amplitude of the child deviation / phase against the input:

| breast | 1 Hz | 2 Hz | 3 Hz | 4 Hz |
|---|---|---|---|---|
| PhysX ref | 0.62° / −83° | 1.27° / −85° | 2.61° / −86° | 6.22° / −69° |
| pivot file | 1.74° / −63° | 4.76° / −100° | 6.21° / −127° | 6.62° / −143° |
| pivot capture | 0.73° / −69° | 2.10° / −75° | 3.76° / −89° | 5.29° / −104° |
| pinned file | 1.68° / −42° | 3.69° / −80° | 4.00° / −95° | 4.09° / −103° |

| belly | 1 Hz | 2 Hz | 3 Hz | 4 Hz |
|---|---|---|---|---|
| PhysX ref | 0.67° / −75° | 2.11° / −78° | 6.58° / −57° | 9.3° / −142° (not sinusoidal, residual 6.9°) |
| pivot file | 3.08° / −82° | 5.46° / −126° | 6.00° / −145° | 6.09° / −155° |
| pivot capture | 1.01° / −57° | 3.56° / −74° | 6.38° / −104° | 7.55° / −129° |
| pinned file | 3.67° / −70° | 4.80° / −109° | 4.95° / −123° | 5.02° / −132° |

Rotation about (Y+Z)/√2 gives the same reference numbers within 5 %; rotation about Y alone leaves the reference body
behind completely (5.00° / −180°). Parent translation ±2 cm perpendicular to the lever (breast): reference 0.04° / 0.09° /
0.40° / 1.08° at 1–4 Hz, pivot capture 0.08° / 0.29° / 0.56° / 0.82°.
Below 3 Hz the reference responds like the capture-fitted pivot model at 0.6–0.85 of its amplitude with a near −85° phase
(first-order lag); at 4 Hz it responds more strongly and loses the sinusoidal shape.

## 7. Game-side cross-check **[code]** unless noted

| field | value | where |
|---|---|---|
| drives (x, y, z, swing, twist, slerp) | all `driveType` 0; the motor block is skipped when joint+0x3c = 0 | 0x51478e–0x5147c7, 0x514b4e |
| motions | x, y, z, twist locked; swing1, swing2 limited | 0x648858 (jiggle.md), copied by 0x51469e… |
| swing limits | 45° and 0°, restitution 0, spring k, damping d verbatim | jiggle.md §2, not re-traced |
| useAccelerationSpring / solverExtrapolationFactor | 0 / 1.0 (descriptor defaults, not overwritten) | 0x5148c2, 0x5148dc |
| maxForce / maxTorque | FLT_MAX (0xa2367c) unless joint+0x48 | 0x5148bc, 0x5148c8 |
| jointFlags / D6 flags / projection | 2 (visualization), collision bit only if joint+0x54 / 0 / mode 0 when joint+0x3d = 0 (distance 0.1, angle 0.0872 unused) | 0x5148e2, 0x514917, 0x514966 |
| body flags | 0x900 dynamic, 0x980 (adds `NX_BF_KINEMATIC`) for movement type 1; gravity is **not** disabled by flag | 0x506d9a, 0x506e27 |
| body desc | angularDamping 0.05 then `setAngularDamping(1.0)`; linear 0; wakeUpCounter 0.4; sleep thresholds −1 (SDK defaults); solverIterationCount 4; then `updateMassFromShapes(0, mass)`, `setMaxAngularVelocity(200)` | 0x506de0–0x5072a4, 0x4fe329 |
| anchor move | RigidBody vtable slot 28 (0x50bd0f): kinematic → `moveGlobalPose` (NxActor +0x34) when global `[0xe14324]+0x2d4 == 0`, else `setGlobalPose` (+0x14); dynamic → `setGlobalPose` | 0x50be93–0x50beb4; state 0 is PLAY (read: 0x495d85; see ENGINE_CONSTANTS "Scene play mode") |
| SDK parameters | only `NX_SKIN_WIDTH = 0.025` is set in the physics module (0x50d51f); improved spring solver stays at its default 1 | scan of 0x4f0000–0x520000 for `call [reg+8]`; other modules not scanned |
| timing | `setTiming(1/rate, maxSteps, NX_TIMESTEP_FIXED)`, `simulate(min(n, maxSteps)·h)` only when n > 0 | 0x4f4d20, 0x4f4ddc |

Not established:
- **Belly**: why the capture-fitted linear model beats the integrator there, and why the belly traces are insensitive to k.
  Candidates not tested: the gimp capture's time base (two interleaved streams; the integrator's belly error is lowest when
  the stream is read at 20–30 fps), a different anchor/lever for `JiggleBelly`, contacts of the 0.8 m box.
- Which actor is `actor[0]` (taken from jiggle.md: the dynamic box) and the joint frame orientation relative to the bone
  axes; the integrator assumes joint frame = parent bone frame. With the cube's isotropic inertia a swap changes only which
  frame's Y/Z build the cone axis.
- Whether the 0.8 m jiggle box collides with anything (collision groups not traced).
- Kinematic anchor: inverse mass 0 and no damping of its velocity, read from 0x10037f30; keep the integrator
  option `anchor_ang_damp` off.
- The capture frame rate (55 estimated by impl_phys; 60 fits the integrator best).
- Float32 effects: the integrator runs in float64 with the DLL's thresholds kept.

## 8. Proposed toolkit change

1. Add `d6_ref.PhysXD6Jiggle` / `run_addon` as a third model (e.g. `model='physx'`): file constants only, no fitted numbers,
   breasts equal to the capture-fitted model on every metric; 14 000 frames take about 10 s in pure Python.
2. Keep `pivot` + capture constants for the belly until §7's belly item is resolved.
3. Docs to correct: "D6 with angular drive springs" → soft swing limits forming a zero-radius cone; "K, D not derivable" →
   derivable as a per-step procedure, not as a (K, D) pair; `solver_soften` (k/(1 + d·dt + k·dt²)) is not what the DLL does
   (softness is scaled by the row inertia, error is tan(θ/4), bias 0.7, unilateral).
