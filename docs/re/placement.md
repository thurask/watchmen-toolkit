# Paired (master/slave) animation placement — open questions

Target `KapowMultiDEDRM.exe`. Extends `toolkit/docs/ANIMATION_META.md` and the section
"2026-10-02 — dual (master/slave) animation placement" of `ENGINE_CONSTANTS.md`.
Evidence levels: **read** = traced in decompile and/or disassembly, **data** = measured in the
shipped Part 2 PC files (user's PC, read-only), **inferred**, **not established**.
Machine-readable constants and data tallies: `findings/placement_constants.json`.

## 0. What changes against the existing docs

| Doc statement | What the code/data says |
|---|---|
| "whether the placement block runs once or every frame" is open | It runs **every tick** (§1). |
| The partner "plays its own absolute animation from the computed start" | True only after the slave's `ABSOLUTE_GOTO_TARGET_POS` event. Until then the slave's start frame is **its own pose when it entered the state**; the placement block's output is ignored (§1.3). After the event it blends in over the blend time. |
| "how the master's own start frame is chosen" is open | In shipped data **no master state is an absolute animation** (0 of 123). The master never gets a start frame; it keeps moving under the normal character controller (§2). |
| `get_slave_pos_at_time` (0x5b0698) "has no caller by hash" | It is called by hash 0xe873fd55 from `CharacterRoot.StateActive` (auto-align block, decompile line 3549 of the function, between yield points 0x60 and 0x61). |
| "Δ = track0(t) − track0(0)" | Confirmed, the index is the literal 0 (0x5af938 `and [ebp-0x30],0`), not clip+0x48. In all 234 primary master clips file track 0 is `GamePivot` (data), so it equals the GamePivot displacement — assuming runtime track index = file order (inferred). |
| "CharacterRoot +0x24 = master node" | CharacterRoot data +0x24 is the **CharacterVisual** node (it receives `get_ragdoll_pelvis_position` 0x637ab144 at 0x6b95b0), +0x28 is the CollisionCapsuleNode. M / Q_M are the master's *visual* node world transform. |
| start frame = capsule +0x10 / +0x28 | Those are only properties. The frame actually used per tick is a `PivotNode` named `worldstartnode` created at state init (0x6a1e1d); it is refreshed from the properties only by `command_update_world_data` 0x6b201d, which runs only while capsule +0xb8 ≠ 0 (§1.2). |

## 1. Once or every frame? What re-anchors the slave?

### 1.1 The block runs every tick — **read**

`CharacterRoot.StateActive` 0x6b367a is a coroutine. Its per-tick loop starts at 0x6b3b67
(resume points 0x80/0x81) and ends by storing resume point 0x80 and calling 0x4797e9 (wake next
frame). The placement block sits in that loop behind three tests, re-evaluated each tick:

| Address | Test | Fail → |
|---|---|---|
| 0x6b9035–0x6b9059 | own capsule (`[self+0x28]`) `is_absolute_mode` 0x16e9e0c ≠ 0. Handler returns 1 only while the capsule is in state 0x30 `StateAbsoluteAnimation` (0x7f09ac), else 0 (0x87b96e) | 0x6b9599 (skip) |
| 0x6b905f–0x6b9083 | own AnimationCtrl (`[self+4]`) `is_in_slave_mode` 0xa7bea2cd ≠ 0, i.e. AnimationCtrl data +0x60 ≠ 0 (0x5af862) | 0x6b9515 |
| 0x6b9089–0x6b9097 | AnimationCtrl data +4 (`Animation partner`) ≠ 0 | 0x6b94eb |

There is no "done" flag; nothing in the block clears its own condition. So every tick it rewrites
capsule +0x10 (`m_vWorldStartPos`, 0x6b9320) and +0x28 (`m_qWorldStartOrient`, 0x6b9478) from the
master's **live** visual-node transform, and copies the master capsule's world position to own
data +0x160 (0x6b94dd).

What sets/clears the flags:

- AnimationCtrl +0x60 set by `goto_slave_mode` 0x5b32a2 / `goto_slave_mode_state` 0x5af6d9
  (`= args[1]`, the master's main blend source passed from `SetupNewPage` 0x5b9b40); cleared by
  `leave_slave_mode` 0x5b3310.
- AnimationCtrl +4 set by `CharacterRoot.command_request_me_as_dual_animation_partner` 0x693d5f
  (to the requester's character root, via `get_character_root` 0xc70ac120). The handler refuses if
  the receiver is dead (data +0x198) or already in slave mode. It then calls
  `UptateAnimationDataAnimPartner` 0x676172 (sets animation enum 0xb = partner's model type and
  0xc = partner's weapon type — this is what the slave-state criteria test) and stores the
  partner's visual-node position at data +0x1e8.
- capsule state 0x30 entered by `goto_animation_mode` 0x67bd36, left by
  `goto_phys_normal_mode` 0x67f56b (→ `StateOnGround`).

### 1.2 The writes take effect only while capsule +0xb8 ≠ 0 — **read**

`StateAbsoluteAnimation` 0x6a1e1d (init, resume point 0) creates two PivotNodes,
`worldstartnode` (state local [0]) and `worldendnode` (local [1]), and sets them once from capsule
+0x10/+0x28 and +0x1c/+0x38. `command_absolute_update` 0x67f7b0 reads the start frame from the
*node* (`local[0]` world position/orientation), not from the properties.

The only thing that moves the node afterwards is `command_update_world_data` 0x6b201d: it compares
the properties with the state's private copies (locals +0x10…+0x44) and, if the start changed,
sets `worldstartnode` to the new start and recomputes the end
(`end = start + R(startnode)·(GP(len) − GP(0))`, end orient `q_GP(len) * start`). If only the end
changed it back-computes the start. Tolerance for the quaternion compare is the float at 0xd91bf8
(in .bss, set at run time — value **not established**).

`update_world_data` is called from exactly one place: the top of `absolute_update`, guarded by
capsule data +0xb8 (`piVar11[0x2e]`). The same flag gates the blend-in (below).

Writers of capsule +0xb8:

| Where | Value |
|---|---|
| `goto_animation_mode` 0x67bd36, first statement | `= args[4]` |
| `CharacterRootLogic.command_goto_phys_absolute_mode` 0x68a79f builds that arg: 1 iff the character's current state has `Special handling` (`m_ispecialhandling`, state data +0x9c) == 0, else 0 | |
| `StateAbsoluteAnimation` resume point 5/6 (one tick after init) | `= 0` if the current state's `Master of` (+0x30) ≠ 0 |
| event `ABSOLUTE_GOTO_TARGET_POS` (id 0x1c), `command_animation_event_received` 0x6a525e (decompile line 3791) | `= 1` on the capsule of the character whose state carries the event |
| in-state `goto_animation_mode` 0x6a32ce | `= 1` when the state's special handling is 0xc |

State property offsets used here (**read** for +0xc, +0x30, +0x34 against known uses; **inferred**
for the rest by counting 4-byte properties in registration order 0x605d0a… with three vec3
properties): +0x1c absolute, +0x20 defines movement, +0x24 defines rotation, +0x30 Master of,
+0x34 looping, +0x9c Special handling, +0x15c Animation type. `kapow_hash("m_ispecialhandling")`
= 0x27cca287 matches the registration.

### 1.3 Consequence for shipped slaves — **read + data**

Data (all AnimationClass fragments, Part 2 PC): 161 of 166 absolute slave states have
`Special handling = 3` and an `ABSOLUTE_GOTO_TARGET_POS` event (playpos 0.20–0.21); the other 5
(bull-move targets) have special handling 0 and no such event. So for a normal counter/finisher/throw victim:

1. Entry (`goto_animation_mode`, flag 0, 0x67bdbb–0x67be1b): start = the slave's **own current
   visual-node position and orientation**. It is not moved or turned. +0xb8 = 0.
2. Until the event: `pos = entry + R(entry)·(GP_p(t) − GP_p(0))`, orientation
   `q_GPp(t) * entry`. The placement block is already writing the properties each tick but nobody reads them.
3. At `ABSOLUTE_GOTO_TARGET_POS`: +0xb8 = 1. From the next update on, `update_world_data` copies
   the freshly written start into `worldstartnode` every tick, and the blend timer starts.
4. Blend (0x67fd…, `absolute_update`): timer `T` = state local +0x48, initialised to the blend time
   passed to `goto_phys_absolute_mode` (args[1]; `SetupNewPage` passes page +0xc — which page
   field that is, **not established**; the state's ease-in is 0.2–0.21 s on these states).
   Each update `T -= clamp(dt, 0, 0.1)`; while `T > 0`: `w = T / blend`,
   `pos = w·entry_pos + (1−w)·abs_pos`, orientation = quaternion blend (0x41fd54) of the
   absolute orientation and the entry orientation with weight `w`. `entry_pos/orient` are the
   visual-node pose captured at state init (locals +0x50, +0x5c), i.e. the blend starts from where
   the slave stood when the state began, not from where it is at the event.
5. For the 5 special-handling-0 slaves the flag is 1 from the start: the start node is taken from
   whatever the properties held at entry (stale until the first placement tick), then re-anchored
   and blended immediately.

### 1.4 Who actually advances the slave — **read**

In state 0x30 `attempt_move` is 0x67f727. It asks the owner's AnimationCtrl `is_in_slave_mode`
(0x67f743–0x67f760):

- not a slave → `absolute_update(dt, apply=1)` → `ForceSetWorldPosOrient` 0x6a5070.
- slave → `DccAttemptMove` 0x680471 with the caller's move vector; **no** `absolute_update`.

The slave's `absolute_update` is instead sent by the **master's** capsule: `DccUpdate` 0x680654
(lines 118–152 of its decompile) checks own current state `Master of` ≠ 0, partner alive, partner
capsule data[1] == 3 (set by `StateAbsoluteAnimation`), partner capsule +0xb8 ≠ 0, and passes the
partner's capsule to `DccJoint` 0x6a3d71. `DccJoint` sends `absolute_update(dt = frame dt 0xe14304,
apply = 0)` to that capsule (0x6a4274–0x6a4280), reads its predicted next position/orientation
(capsule +0x7c / +0x88), sweeps from the master's position to it, pulls the target back out of
level geometry if blocked, adds the same correction to the **master's** pending displacement
(+0x180…), and drives an `EmbeddedJointNode` ("DCC joint", debug name "DualAnimationJoint") to the
result. With no eligible partner it calls `DccJoint(0)` which releases the joint.

So before the event the slave has no joint to the master; after it the slave is physically jointed
to the master at its absolute target, and walls move both. The detailed joint parameters (the
0x5179xx setters, values 0/2) were not decoded — **not established**.

### 1.5 Does the slave follow the master's GamePivot motion?

It is re-anchored to the master's live transform every tick (after the event), but the anchor
expression cancels the master's *translation*:

```
anchor_pos(t) = M(t) · (I0 − Δ(t)),   Δ(t) = GP_m(t) − GP_m(0)      (read)
```

If M(t) = master start + R·(GP_m(t) − GP_m(0)) with an unrotated frame R, this is the constant
`start_m + R·I0`: the slave does not follow the master's root motion, it stays on the marker, and
only follows *external* displacement of the master (collision push, joint correction, auto-align).
That is the evident purpose of Δ (**inferred**).

Rotation is not cancelled. `anchor_orient = r * Q_M(t)` and the offset is rotated by M(t), so if the
master's visual node turns with its GamePivot during the clip, the anchor swings round the master.
Whether the non-absolute master's node orientation follows the GamePivot rotation mid-clip was
**not established** (the non-absolute root-motion path was not traced). Data check: in 33 of 234
primary pairs the master's GamePivot yaw changes by more than 2° inside the slave's
[`ABSOLUTE_GOTO_TARGET_POS`, first `LEAVE_ABSOLUTE_MODE`] window (up to 180° for
`RSH_COM_ATT_throw_EN1`, 87° for `NTO_COM_ATT_counter_EN1_E`); if the node did follow it, the
anchor would drift by 0.16–1.45 m from the authored marker in those pairs. In the data the
`interact` track is a child of GamePivot including rotation and is world-fixed
(`GP(t) + R_GP(t)·interact(t)` is constant: e.g. `RSH_COM_ATT_finish_EN1_B` gives (0.000, 0.856) at
t = 0 and (0.001, 0.855) at the end, with GP turned 180°). A consumer should therefore keep the
fixed marker (§8); treat the rotating-master case as unverified against the running game.

## 2. The master's own start

**Data:** all 123 master states (`Master of` ≠ 0) have `Is an absolute animation` = false,
`Anim defines movement` = true (rotation true on 77, false on 46 enemy counters), special handling
6 (4 throws: 1), animation type 8 (counter), 9/12 (finish), 10 (throw), 0 (bull-move impact).

**Read:** `SetupNewPage` (0x5b7788, decompile lines 1073–1083) sends `SendGotoPhysAbsoluteMode`
only when state +0x1c ≠ 0, otherwise `SendGotoPhysNormalMode`. So a master goes to / stays in
normal physics mode: no start frame, no snap, no blend to the victim. It plays its clip's root
motion from wherever it stands, facing wherever it faces, and the *slave* is brought to it.

If a master state were absolute (none shipped), `goto_animation_mode` 0x67bd36 would do — **read**:

| args[4] flag | capsule +0x48 | start frame |
|---|---|---|
| 0 | – | current visual-node position and orientation (0x67bdbb, 0x67be1b); end = start + R·(GP(len) − GP(0)), `q_GP(len) * start` |
| 1 | 0 | stored `m_vWorldStartPos`/`m_qWorldStartOrient` kept as they are (jump to 0x67c616) |
| 1 | ≠ 0 | use-trigger alignment: `start_orient = m_qAbsInteractOrient` (+0x58), `start_pos = m_vAbsInteractPos` (+0x4c) − R(start_orient)·(conj-rotated `interact(0)` of the clip). Writers are scripted interactions (`CharacterRoot.command_play_specific_anim` 0x6af969, `TriggerCharacter.StatePullSwitch` 0x896bb0), not combat |

and one tick later +0xb8 is cleared because `Master of` ≠ 0 (no blend, no world-data refresh).

`set_world_start_pos_from_next_pos_and_orient` 0x6a24e1 and `reset_world_start_pos` 0x6a2cd4 are
sent only by `UnderbossPhase1` code (0x88ee37, 0x88bcff, 0x88d868, 0x88e961) — not part of the
pair flow. `CharacterRoot.command_set_world_position_and_orient` 0x6b2af5 is reached only from
`command_teleport` 0x68f6b8 and `command_animation_driven_set_transform` 0x693871; it teleports
the capsule to `pos + (0, capsuleHeight·0.5, 0)` and sets heading from the quaternion.

### 2.1 What happens before/at the start of a pair — **read**

- `CharacterRootLogic.command_start_animation_state` 0x688961 does not position anybody. For a
  master state with special handling 1 (throws) it does a physics overlap query at
  `0.5·(masterPos + partnerPos) + (0, 0.8, 0)` (0.8 = double at 0x9ea130, up vector 0x9e807c),
  radius 0.5 (0x9e6174); if a blocking static body is found it fires animation actions 5 and 0xe
  and forces animation 9 instead (no room for the throw). For animation type 9 it clears four
  collision helpers on the partner's capsule (+0xbc…+0xc8); for type 8 it notifies
  `CombatOrchestrator.command_attack_animation_stated`.
- `DualAnimBroken` 0x675f4f: if the master's main-state play position is < 0.75 (0xa01020) when
  the pair breaks, it forces animation 9 with blend 0.3 (0x9e650c) and, if play position > 0.3,
  fires actions 0xe and 0x1e; then `leave_slave_mode`.

### 2.2 The auto-align step — **read (decompile level)**

It is not specific to pairs. `CharacterRoot.StateActive` (decompile lines ~3150–3725, resume
points 0x5a–0x62) runs it each tick while the character has a current attack target equal to its
locked target (`[0x1c] == [0x82]`). It closes the gap so the hit lands at the authored impact
distance:

```
d        = horizontal distance to target (target position, or the nearer of two ragdoll bones if prone)
active   if forced-flag [0x22] or d < 1.9 (0xa55538; 2.2 (0xa46b90) if the target `is_big`)
maxFix   = 1.1 (0x9e5fb8); 1.75 (0xa5f030) if forced; 1.3 (0x9e60c0) if big
gap      = d − targetRadius(def +0x70 or +0x74)                       (not subtracted when prone)
want     = impact distance [0x3a]; replaced by the DO_AUTO_ALIGN value while its timer runs
residual = gap − (want − |get_slave_pos_at_time(tImpact)|) − |get_delta_movement_at_time(tImpact)|
if residual < maxFix and time-to-impact window ok (≤ 0.3 s, 0.6 s prone, or forced timer):
    k    = min(k + dt·40, 8)          (0xa06aa8, 0x9ea750)
    move = dir · residual · k  (·2 or ·3 near impact / prone), added to this tick's displacement
```

`DO_AUTO_ALIGN` (event 0x50, decompile line 3233 of 0x6a525e) sends `force_auto_align` 0x76d0c085
with the event's two values; the handler 0x694ed7 stores `data+0x270 = value0` (the distance to
use as `want`) and `data+0x26c = now + value1` (until when), and zeroes the gain. No angle is
involved; facing is handled by heading/target-lock code that was not traced
(`LOOK_AT_TARGET`, `SET_HEADINGS_FROM_ALIGNEMENT` — **not established**).

No "snap to victim" exists for the master: **not found** in any of the functions named in the task.

## 3. `get_interact_initial_pos`, `get_slave_pos_offset`, `get_slave_alignment`

All three are AnimationCtrlWM handlers working on the controller's current top page's main clip
object (same pointer chain in each). Sampler: 0x594544 → 0x593d06 → 0x59342b(out, trackIndex,
time) → clip vtable +0x14; returns the zero vector 0x9e803c when there is no clip data or the
index is < 0 or ≥ track count (**read**).

| Command | Returns | Evidence |
|---|---|---|
| `get_interact_initial_pos` 0xa591eb43, 0x5b082a | position of track `clipdata+0x4c` (interact index) at time 0. (0,0,0) if the clip has no `interact` track | read, 0x5b08a0–0x5b08c5 |
| `get_slave_pos_offset` 0x90349206, 0x5af879 | `pos(track 0, t) − pos(track 0, 0)`, `t = clipLength · playpos` = current clip time (0x591951 × 0x591920) | read, 0x5af935–0x5afa66 |
| `get_slave_pos_at_time` 0xe873fd55, 0x5b0698 | same with `t = args[3]` | read |
| `get_slave_alignment` 0xeb960eb9, 0x5b0ddf | identity quaternion (0,0,0,1); shared stub with `get_absolute_orient`; no sender found by hash | read |

The "slave pos offset" is not a property and no command sets it; it is recomputed on demand. The
block caches the two results in StateActive locals +0x25c (Δ) and +0x268 (I0).

Is Δ ever non-zero? **Yes** (data): it is the master's GamePivot displacement since t = 0, e.g.
`RSH_COM_ATT_finish_EN1_B` GamePivot moves (−0.110, −0.885) → (0.480, 0.725). It is zero only at
t = 0 or for a master whose GamePivot does not translate. Because the block only matters from the
`ABSOLUTE_GOTO_TARGET_POS` event (playpos ≈ 0.2) on, Δ is generally non-zero when it is first used.

Women's skeletons (`female`, `bs2`) have no `interact` track → I0 = 0 → default offset
(0.11, 0.04, 1.12) (bytes ae47e13d / 0ad7233d / 295c8f3f at 0xa5f02c / 0x9e616c / 0xa5f028).
The test is exact float equality of all three components against 0x9e803c (0x6b9214–0x6b9240).

## 4. Frame of I0 and quaternion order — **read**

- Position, 0x6b92c1–0x6b9305: `node = [[master+0x10]+0x24]` (master CharacterVisual node).
  Node class A (type 0xe14270) → 0x48ec72/0x48e5bf; class B (0xe152d8) → 0x5133e4, which is
  `out = v.x·row(+0x4c) + v.y·row(+0x5c) + v.z·row(+0x6c) + row(+0x7c)` — the node's **current
  world matrix**. Input vector = `I0 − Δ` (0x6b9282–0x6b92ad: `fld I0; fsub Δ`).
  It is the master's live world transform, not any stored start orient (the master has none, §2).
- Orientation, 0x6b935c–0x6b946d: `a = Q_M` = world quaternion of the same node (0x481e33 /
  0x4f2e56), copied to [ebp+0x50]; `b = r` from local +0x284, copied to [ebp+0x2c]. The x87 code
  computes `x = b.w·a.x + b.x·a.w + b.y·a.z − b.z·a.y` (and cyclic), `w = b.w·a.w − b·a`, i.e. the
  Hamilton product **r ⊗ Q_M**, in the engine's "child * parent" notation `r * Q_M`. Same
  operand order as `absolute_update` (`q_GP ⊗ startnode`).
- `r = (0, sin(c), 0, cos(c))`, c = float at 0x9e8440 = bytes db0fc9bf = −1.5707964; 0x423b20 →
  0x9933f0 is `fsin`, 0x402b11 → 0x990d10 is `fcos` (checked in the CRT bodies). r = (0, −1, 0, ≈0):
  a half-turn about Y. Applied on the child side, so the slave frame is the master's frame turned
  180° about the master's own up axis.

Rotated master at t = 0: irrelevant in practice — every primary master clip has GamePivot yaw 0 at
t = 0 (data: `yaw_start_deg` = 0.0 for all 234 primary pairs), and the code uses the
node transform anyway, never the clip's GamePivot orientation at t = 0.

## 5. How the pair ends — **read (decompile level)**

Three ways out, all ending in `leave_slave_mode`:

1. Slave's `LEAVE_ABSOLUTE_MODE` event (id 0x13; 0x6a525e decompile line 1819): sends
   `goto_phys_normal_mode` 0x2b604830 to itself, then, if it has a partner, `leave_slave_mode`
   and `break_joint` 0xc40d9345 (→ `CleanUp_eDccJoint` 0x676db9) to the other side's capsule.
   Data: 161 slave states carry it, first occurrence at playpos 0.26–0.82; 5 throw victims have none.
2. Slave's own watchdog in `StateActive` (decompile lines 2858–2915, resume points 0x4c–0x4f):
   each tick, with `n = return_slave_node` (AnimationCtrl +0x60): leave if partner pointer is
   null, partner is dead (+0x198), or the master's `get_main_state_main_blendsource` 0x45323943
   ≠ n (the master has left the paired state).
3. Master changes to another non-override state: `SetupNewPage` line 127–131 sends
   `leave_slave_mode`; `DualAnimBroken` 0x675f4f does the same.

`CharacterRoot.command_leave_slave_mode` 0x693a09: if alive, unregisters the manual script resume,
sends `dual_end` 0xf39458ac to its own and the partner's capsule, then AnimationCtrl
`leave_slave_mode` (+0x60 = 0). `command_dual_end` 0x67ac22: if the capsule has its DCC joint node
(data +0x190), sets four joint fields (0x51793a/70/82/94) to 2 — the "released" configuration
`DccJoint` uses when it has no partner.

Capsule side: `goto_phys_normal_mode` 0x67f56b switches state 0x30 → `StateOnGround`. The exit
branch of `StateAbsoluteAnimation` (0x6a1e68 default case) stores
`visualNode.pos − capsule.pos` into the visual node's data +0x80 with weight +0x8c = 1.0 and
+0x90 = 0, and deletes the two pivot nodes.

Position afterwards: **kept**. There is no snap to a navmesh or to the ground in this path; the
capsule resumes normal controller physics from where the absolute animation left it, and the
visual/capsule offset recorded at exit is handed to the visual node (its decay was not traced —
**inferred** to be blended out). Orientation: while absolute, `StateActive` copies the capsule's
`get_world_orient` 0x590a049a into `set_world_orientation` 0xb60f5882 each tick (0x6b9515), which
converts it to a heading, so the heading at exit is the last absolute yaw.
`KILL_ANIMATION_PARTNER` (0x14) and `DIE` handling were **not traced**.

## 6. `loopOffset` — **read**

Two separate mechanisms in `absolute_update` 0x67f7b0 / `absolute_loop` 0x67f5d2:

- Persistent: state local +0x70 holds `−GP(0)` (set at init). Each time the animation controller
  reports a wrap (`SendAbsoluteAnimationLooped` 0x5ac5f7 → logic 0x68a592 → capsule
  `absolute_loop`), it adds `GP(len) − GP(0)`. After n loops the term is
  `n·(GP(len) − GP(0)) − GP(0)`.
- Transient: `absolute_update` evaluates at `t' = playpos·len + dt`. If `t' > len`: non-looping
  state (+0x34 = 0) → clamp to `len`; looping → local +0xe4 = `GP(len) − GP(0)` for this call only
  and `t' −= len`. It is zeroed at the start of every call.

```
pos = startnode.pos + R(startnode) · (GP(t') + transient + local70)
    = start + R · (GP(t') − GP(0) + n·(GP(len) − GP(0)))
orient = q_GP(t') * startnode.orient          (rotation is NOT accumulated across loops)
```

Time is not advanced at all while the state's data +0x164 ≠ 0 (meaning not established; the
`transient` stays 0 then).

Do pairs loop? **No** (data): every master state and every absolute slave state has
`Is looping` = false. The only looping slave states are two non-absolute `ThrownByRorschachRagdolled`.

## 7. Other things a consumer must know

- **Mirroring:** none. No mirror flag is read anywhere in the placement block,
  `goto_animation_mode`, `absolute_update` or `update_world_data` (read).
- **Scale:** no per-character-type scale in those functions (read). The only per-type inputs are
  the capsule half height (property 0xdaec7a56 × 0.5, used by teleport) and the target radius in
  auto-align.
- **Height:** the anchor is the full 3-D `M·(I0 − Δ)`; nothing zeroes Y or snaps to ground. I0.y is
  0 in authored clips (GamePivot-local, GamePivot is 1.0 m above ground in both skeletons), the
  default offset has y = 0.04. On uneven ground the slave is therefore placed at the master's
  height. At the end of `absolute_update`, for state ids 4 and 0x28 only the vertical distance is
  reported to the animation value 9; otherwise the 3-D distance between capsule and the target.
- **Capsule vs visual node:** the master frame M and the slave's entry pose are read from the
  CharacterVisual node; the result of `absolute_update` is applied to the capsule node
  (`ForceSetWorldPosOrient`). Whether the two nodes share an origin was **not established**
  (the exit code storing their difference shows they can differ during an absolute animation).
- **Slave state choice:** `CharacterRoot.command_goto_slave_mode` 0x693b2e walks the slave-state
  group whose id = the master's `Master of`, asking each `get_valid_state` 0x499d201a, after
  0x676172 has published the partner's model type and weapon type. Ignored if the receiver is dead
  or already a slave.
- **Timing:** both clips run on their own controllers; the slave is not time-synced to the master
  in the code read here (the slave's Δ uses the *master's* clip time).
- **Blend, not snap:** the slave is never teleported. Expect it at its own spot for the first
  ~20 % of the clip, then a blend of `blend` seconds onto the marker.

## 8. Rule for a tool writer

Notation: engine quaternions, `a * b` = Hamilton `a ⊗ b` ("child * parent"), vectors rotate as
`conj(q)·v·q`; `R(q)` is that rotation. `GP_x(t)`, `I_m(t)` = position keys of the `GamePivot` /
`interact` tracks; `qGP_x(t)` = GamePivot rotation key. `(P_m, Q_m)` = world pose you give the
master at t = 0.

**Read from code**

```
I0      = I_m(0)            ; if exactly (0,0,0) or no interact track: (0.11, 0.04, 1.12)
r       = (0, -1, 0, 0)     ; half-turn about +Y
master  : not absolute. Root motion from its own clip, from (P_m, Q_m). No snap.
anchor(t):  pos = M(t) · (I0 − (GP_m(t) − GP_m(0)))      M(t) = master visual node world matrix
            rot = r * Q_M(t)
slave before its ABSOLUTE_GOTO_TARGET_POS event (time tE):
            pos = P_s + R(Q_s)·(GP_p(t) − GP_p(0)),  rot = qGP_p(t) * Q_s     (P_s,Q_s = its own pose at entry)
slave after tE, blended over `blend` seconds from (P_s, Q_s):
            abs_pos = anchor.pos + R(anchor.rot)·(GP_p(t) − GP_p(0))
            abs_rot = qGP_p(t) * anchor.rot
            w = max(0, 1 − (t − tE)/blend);  pos = w·P_s + (1−w)·abs_pos;  rot = slerp(abs_rot, Q_s, w)
slave after its LEAVE_ABSOLUTE_MODE event: free (normal physics), position kept.
```

**Inferred (recommended for an offline viewer)** — take the master's node frame as fixed for the
clip, so the anchor is constant:

```
master_world(t)  = P_m + R(Q_m)·(GP_m(t) − GP_m(0)),   rot = qGP_m(t) * Q_m
anchor           = P_m + R(Q_m)·I0,                     rot = r * Q_m
partner_world(t) = anchor.pos + R(r * Q_m)·(GP_p(t) − GP_p(0)),   rot = qGP_p(t) * r * Q_m
```

This is what `ANIMATION_META.md` already implements and what the authored data supports (the
`interact` marker is world-fixed). For a faithful reproduction of the first part of the move, hold
the partner at its own pose until `ABSOLUTE_GOTO_TARGET_POS` and blend; for showing the authored
choreography, apply the anchor from t = 0. Do not carry the partner past its first
`LEAVE_ABSOLUTE_MODE` event with the anchor rule if you want engine behaviour: from there the
engine lets physics/ragdoll take over.

## 9. Not established

- Whether a non-absolute master's visual node turns with its GamePivot rotation during the clip
  (decides whether the anchor swings in the 33 pairs of §1.5).
- Value of the quaternion tolerance at 0xd91bf8; which page field supplies the slave's blend time.
- The DCC joint's parameters and exactly how much it constrains the slave vs. the master.
- Visual-node vs capsule-node origin offset; decay of the offset stored at exit.
- `KILL_ANIMATION_PARTNER`, `DIE`, `LOOK_AT_TARGET`, `SET_HEADINGS_FROM_ALIGNEMENT` handlers.
- How combat code decides a pair may start (range/angle gates in PlayerCtrl / AI); only the
  obstacle test in §2.1 and the generic auto-align were read.
- Receiver objects of a few dispatches were taken from the decompile without checking `ecx` in
  disassembly (the `leave_slave_mode` / `break_joint` sends in §5, the `DccUpdate` partner chain).
- Runtime track index = file track order (needed for "track 0 = GamePivot").

## 10. How this was checked

Decompile dump (`fn.py`), disassembly (`xdis.py`) for 0x6b8ff0–0x6b95e3, 0x5af8e0–0x5afa6d,
0x5b0890–0x5b08ee, 0x67f727–0x67f7af, 0x6a41f4–0x6a4298, the CRT sin/cos bodies; constants read
with `rd`. Game data read on the user's PC with the toolkit's `anim_meta`/`bake_v4` (read-only):
state property tallies over 5 AnimationClass fragments, track order and GamePivot/interact keys of
all 234 primary pairs. Nothing was run in the game, so every "read" item is static analysis.
