# Research reports — full decompilation pass, 2026-10-02

Nine reports on `KapowMultiDEDRM.exe` (32-bit x86 PE, image base 0x400000),
shipped verbatim as reference. Each cites the function addresses it rests on
and marks every finding as read from code, inferred, measured on the shipped
data, or not established.

**These are the reports as written before anything was implemented.** They
contain proposals ("proposed toolkit change"), comparisons with toolkit code
that has since been changed, and a few statements that implementation showed
to be wrong or incomplete. They are not edited. Corrections found afterwards
are recorded in [`../ENGINE_CONSTANTS.md`](../ENGINE_CONSTANTS.md) (section
"2026-10-02 (later) — full decompilation pass") and listed at the end of this
file. Where a report and the toolkit disagree, the toolkit and
`ENGINE_CONSTANTS.md` are current.

The decompilation they were read from is produced by the scripts in
[`../../tools/ghidra/`](../../tools/ghidra/README.md). Addresses belong to this
one build.

**Added 2026-10-03 (toolkit 1.4.0):** two more reports, `physx_d6.md` and
`vcolor.md`, described under "Reports added 2026-10-03" below. They follow the
same rules with two differences. `physx_d6.md` is read from `PhysXCore.dll`
(PhysX 2.8.1.1, image base 0x10000000), not from the game executable. And both
were amended by their authors after the implementation: each opens with a
dated block ("Addendum", "Correction") that withdraws statements further down.
The body under that block is the report as first written; read the block
first. The corrections are also listed at the end of this file and in
`ENGINE_CONSTANTS.md`, section "2026-10-03 — PhysX soft-limit jiggle; vertex
colour, tangent frame and normal-map channels".

**Added 2026-10-04 (toolkit 1.4.0):** ten more reports on the renderer,
physics, combat, AI, runtime, audio, effects, the script layer and the face
system, described under "Reports added 2026-10-04" at the end of this file,
with the corrections made to them since.

## The reports

### [events.md](events.md) — what each animation event does

Reads the sender (`CheckPlayPosEvents` 0x5b51f3), the delivery path and the
receiver `CharacterRootLogic.command_animation_event_received` (0x6a525e, 37
kB), and gives a case map for every `ANIMATION_EVENT` id: which fields it
writes and which commands it sends. Establishes the four trigger kinds
(`PLAY_POS`, `ENTER_STATE`, `LEAVE_STATE`, `TOTAL_PLAY_TIME`), that
`ABSOLUTE_GOTO_TARGET_POS` only sets one capsule flag, that `LOOK_AT_TARGET`
is a camera event, and what `LEAVE_ABSOLUTE_MODE` and
`KILL_ANIMATION_PARTNER` do. Evidence: read from code throughout; ten cases
(ids 6, 23, 29, 30, 31, 40, 59, 70, 76, 77) were skimmed for commands and
field writes rather than read instruction by instruction, and the report says
so. All ten have been read since (see "Corrections found in the review
pass"). Table: `events_table.json` (93 ids).

### [placement.md](placement.md) — paired animation placement

Answers the points the first placement write-up left open: the placement
block in `CharacterRoot.StateActive` runs every tick; its output takes effect
only while the partner capsule's flag at +0xb8 is set; no shipped master state
is an absolute animation, so the master is never snapped; how a pair ends; the
loop offset; the auto-align step. Ends with a rule for tool writers, split into
"read from code" and "inferred". Evidence: read from decompilation and
disassembly, plus tallies measured on the Part 2 PC fragments and clips; the
open points are listed in its last sections. Constants:
`placement_constants.json`.

### [sync.md](sync.md) — transition sync markers and start play position

Property table of `AnimationTransition`, how the eight (local, remote) marker
pairs are sorted and cached at init (`UpdateSuperSync` 0x5fa582), how they gate
a transition (`TransitionMet` 0x5c5ea4) and choose the target's start position
(`TransitionPlayPos` 0x5ac1aa), and the priority order of the four start
rules. Evidence: read from code, with the constants checked in the exe bytes;
one field meaning is marked inferred. Includes a data check over the Part 2 PC
fragments.

### [enums.md](enums.md) — every enum the executable registers

How enums are registered (`FUN_005052c9(family, name, value)`), all 1,813
registrations resolved into 186 families and 1,801 names, the criteria kinds
and what each reads, and five disagreements with what the toolkit assumed
(enum variable 11 is the opponent's model type; the "value slot" is not a
selector). Evidence: read from code; the animation families were checked
against the editor captions in the shipped fragments. The report lists the
animation-related families in full and all families by name; the complete
machine-readable table is not shipped here — the 30 families the toolkit uses
are in `wlib/engine_enums.json`.

### [pages.md](pages.md) — animation pages and play position

`SetupNewPage` 0x5b7788 and `UpdatePagePlayPos` 0x5b56a9: what a page is, the
record offsets of states, transitions, slots and blend nodes, the rate and the
6.6 /s clamp, loop wrap, page blending, event latching, and how a clip time
becomes a key index. Closes with an item-by-item comparison against
`bake_v4.py` and `anim_state_machine.py` as they were before this release.
Evidence: read from code unless tagged otherwise; counts measured on 8 class
fragments and 1,185 clips. Offsets: `pages_offsets.json`.

### [skeleton_blobs.md](skeleton_blobs.md) — the "joint blobs" are collision volumes

The records in a `.model` node tail that earlier notes called
"EmbeddedJointNode joints, types 4/5/6/7" are the node's collision volumes:
concave mesh, convex mesh, box, sphere, capsule, in two lists (one per PhysX
scene) followed by a third list. Gives the reader (`Node::Deserialize`
0x545927, factory 0x524b23) and the layout per type. Evidence: read from
code, tiling verified on the extracted files. Layout:
`skeleton_blobs_layout.json`.

### [jiggle.md](jiggle.md) — secondary motion, exe side

Setup (`CharacterAddonCtrl` 0x6574cd), joint configuration (0x648858), the
physics step, the per-frame anti-gravity force and the write-back
(0x6563a0). Shows that the simulated body is a 0.8 m box pivoting about the
parent bone origin, that the bone's local position and rotation are both
replaced, that gravity is cancelled, and that nothing on the path scales the
spring or damping — so no constant in the exe explains the old amplitude
factor. Evidence: read from code, cross-checked against capture palettes; the
effective stiffness and damping are stated as not derivable from the exe.
Constants: `jiggle_constants.json`.

### [formats.md](formats.md) — file formats from the engine's loaders

Block header and directory, the two unnamed asset-type hashes, the complete
set of vertex formats and the ModelRes header and stream layout, the
`.sequence` grammar, the Texture header, and the per-platform texture format
table. States plainly what the PC executable cannot answer (PS3 cube framing,
the X360 2D mip tail). Evidence: read from code, and "validated" where the
reference parsers reproduce real files exactly (models 740 / 740, textures
936 / 936, sequences 194 / 194). Tables: `formats_tables.json`,
`formats_vertex_decls.json`. The reference parsers it mentions are not
shipped; their logic is in `wlib/watchmen_extract.py` and
`wlib/decode_sequence.py`.

### [names.md](names.md) — the name hash, command hashes, property names

The engine folds every byte of a name with `& 0xDF` before hashing, which
differs from upper-casing for digits and punctuation. With that, all 1,696
distinct command hashes are reproduced (bare name, or `name(type,…)` for
commands with parameters) and all 3,695 registered property hashes are named.
Also lists ten errors in the previous `reg_dump.json`. Evidence: the hasher
and the registration records are read from code; that the offline script
compiler used the same routine for signatures is inferred from the exact
reproduction. The per-hash tables it refers to are not shipped here; the
results are in `wlib/reg_dump.json`, `wlib/command_signatures.json` and
`wlib/kapow_fragment_keys.pkl`.

## Reports added 2026-10-03

### [physx_d6.md](physx_d6.md) — what PhysX does with the jiggle joint

Follows the game's joint descriptor into `PhysXCore.dll`: the class and
descriptor path (`NpD6Joint::loadFromDesc` 0x10135430 → `PxsD6Joint`), the
constraint setup the island solver calls once per substep (0x10227db0), the
angular, linear and soft row builders (0x10227a70, 0x10227640, 0x102068b0),
the row iteration and the conclude pass (0x1022ce80 / 0x1022ccb0, 0x1022d500 /
0x1022d450), body integration (0x101ffb50, 0x102008a0) and the kinematic
anchor (0x10034c10). Establishes that the joint has no drive — every
`driveType` is 0 — and that the file's spring and damping are the soft swing
limits; that two limited swing axes are one cone limit, here of radius 0
(45° and 0°), a one-sided soft row whose error is tan(swing/4); the row
coefficients (`gamma = 1/(dt(d + k·dt))`, `erp = k·dt/(d + k·dt)`, scaled by
the cube's inertia about its centre, position term × 0.7); 4 iterations and a
conclude pass, with the pose integrated from the pre-conclude velocity; and
that no stiffness / damping pair of a linear model reproduces the result — it
is a per-step procedure. Evidence: the DLL-side statements are read from
decompilation and disassembly, with the constants taken from the DLL's bytes;
the game-side cross-check (§7) is read from the executable. Three things are
inferred and say so: that the kinematic anchor has zero inverse mass in the
solver, which actor is `actor[0]`, and that the high-level `D6Joint`
functions (0x10082550, 0x100868c0) do not also act. The capture comparisons
(§5) are measurements. Collision of the 0.8 m jiggle box and hair are not
established (no hair capture exists). Table: `physx_d6.json` (addresses,
offsets, constants, test results). The reference integrator it mentions
(`d6_ref.py`) is not shipped; its logic is `jiggle_d6.SoftLimitJoint`, and a
frozen transcription is in `tests/test_jiggle_solver.py`.

### [vcolor.md](vcolor.md) — vertex colour, tangent frame, winding

Disassembles all 243 shaders of the game's shader archive (a from-scratch
SM3 disassembler, checked against the shaders the game creates in a D3D9
capture) and reads the executable for how a shader variant is chosen.
*Frame note (2026-10-05):* the reports in this folder were written when the
toolkit wrote the engine's left-handed numbers verbatim. Where they say "the
export is a mirror image", "mirror X", "the GLB is the same space as the
engine" or "indices must be reversed", they describe what is now `--frame
mirrored`. The default output is true-handed (x = −engine x, file winding);
the reports' own alternative — "negate X on positions, normals and tangents
and keep the indices … negate [TANGENT w] once more" (`vcolor.md`, section 6)
— is what the default now does. The texts are kept as written.

Establishes that `COLOR0` on a model vertex multiplies the complete lit
colour (rgb) and the output alpha (a), and nothing else; that it is used
exactly when the mesh buffer's `hasColor` byte is set (`MeshBuffer+0x31`,
selecting the `VERTEX_COLORS` vertex shader), which is 387 of 735 models and
1,453 buffers; that the pixel shader builds the shading normal as
`x·T + y·B + z·N` from the **stored** tangent and bitangent, with no cross
product and no handedness sign; that one-sided materials are drawn with
`D3DCULL_CW` and two-sided ones (`sheet+0xA4`) with `D3DCULL_NONE`; and the
statistics of the stored colours and tangent frames. Evidence: tagged per
statement as read from shader bytecode, read from the executable, measured on
the Part 2 PC models, or measured on the capture; the handedness reading and
one shader-quality flag are inferred. 19 of 243 shader define sets are
unresolved, none of them a model vertex shader in the capture. Not
established: which rule sends a material to which render effect; what
produced the colours (bake or paint); console shader archives were not
examined. Scope is Part 2 PC, vertex formats 5 and 6. Table:
`vcolor_shaders.json` (every shader's define set, inputs and the
instructions that read `COLOR0`; colour and tangent statistics; the capture
draw table). The disassembler and the per-shader listings it mentions are
not shipped.

The two implementation notes these reports' opening blocks refer to
(`impl_jiggle_solver.md`, `impl_vcolor.md`) and the render-test images are not
shipped. What they found is in `CHANGELOG.md` (1.4.0) and in the
`ENGINE_CONSTANTS.md` section named above.

## Known corrections

Found while implementing; details and addresses in `ENGINE_CONSTANTS.md`.

- **names.md — property registration argument order.** An earlier revision of
  the report had the default and UI-string arguments of `0x47fde4` swapped.
  The shipped text is the corrected one: `(hash, defaultVA|0, uiVA, flags,
  typeIdx)`.
- **`typeIdx` is the declaring class.** The last argument of the property and
  command registrations indexes `DAT_00c89ebc` and identifies the class that
  declares the member (it equals the class's own id at 4,262 of 5,090 property
  sites). It is not a value type, so a registration site cannot type a
  property. names.md says this; read any other mention of "type index" the
  same way.
- **events.md — the `PLAY_POS` window test is superseded by the latch rule.**
  The report says a looping state fires an event when the position crosses it
  inside (previous, current]. That window is used only under the
  AnimationData debug play-position override. In normal play an event fires
  once per pass when `m_nplaypos <= play position` and it has not fired yet
  (0x5b55c4); `TOTAL_PLAY_TIME` fires when `m_nplaypos <= seconds played`
  (0x5b52c1). pages.md has the latch but writes the comparison as `<`; it is
  `<=`, and an event at or before the page's start position is created already
  fired (0x5b8f16).
- **events.md, placement.md — the partner's blend time.** Both leave it open.
  It is the partner state's own ease-in: `goto_slave_mode` 0x5b32a2 →
  `ForceToState` 0x5b4933 with ease −1 → `SetupNewPage` takes the state's
  `m_neaseinduration` and passes page +0x0c to the absolute-mode message.
- **placement.md — "the slave is not time-synced to the master".** It is.
  `goto_slave_mode` stores the master's first animation source in the
  partner's controller, and `UpdatePagePlayPos` 0x5b5756 copies that source's
  play position into the partner's top page every frame until it reaches 1.
- **placement.md — 33 pairs with a turning master, 39 in the export.** The
  two counts use different definitions. The report's count compares the
  master's `GamePivot` yaw at a start and an end point; the export takes the
  largest turn from t = 0 anywhere inside the partner's anchored window
  (threshold 2° in both), over the 240 primary pairs of the final table
  rather than the 234 the report had. The case both name agrees exactly:
  `RSH_COM_ATT_throw_EN1`, drift 1.447 m.
- **pages.md — item B6, the constant position of type 1 / 3 clip tracks.**
  The proposed baker change was not made. The shipped constants are absolute
  values (prone pose clips match their continuation clips to 1 mm), so adding
  the bind offset would create a pop. `bake_v4.py` is unchanged; what the
  engine's added pose term holds is an open question.
- **pages.md, sync.md — page +0x14.** sync.md calls it a cycle length. It is
  a rate (play position per second); `SynchronizePages` blends periods. The
  per-slot speed pages.md could not place is the slot's `speedFactor`
  property.
- **pages.md — criteria and transition ownership.** A transition to a state
  is gated by the transition's criteria, the target state's own criteria
  (appended by `AnimationTransition.initialize_external` 0x5f9b13) and its
  owning groups' criteria. The class root owns no transitions.
- **skeleton_blobs.md — counts.** "1475 `.model` files" counts the
  `.model.stream` files too; there are 740 models. With the engine layout
  2,069 of 2,069 mesh-free node regions tile. The third list is not always
  empty: one node in the PC corpus (`ACUnit_Wall_02`, "splash emitter") has
  one element. `Female_Skeleton.model` has 32 volumes, not 30.
- **jiggle.md — capture figures.** The stiffness and damping it quotes from
  earlier capture fits (K ≈ 150–170, D ≈ 11–19) assumed a 30 fps capture. The
  capture runs at about 55 fps by clip matching; re-measured, the breast
  values are K ≈ 570 s⁻², D ≈ 37.5 s⁻¹. `SetMass` is "argument if above a
  threshold, else 0.1", not `max(arg, 0.1)` (same result here).
  *[corrected 2026-10-03: the 55 fps estimate is withdrawn too, and with it
  the K / D values, which scale with the assumed rate. The capture averaged
  about 64–65 fps with frames that took no physics step; see "Corrections
  found on 2026-10-03" below.]*
- **enums.md — asset names.** The report did not examine whether asset names
  use the folding hash. They do (`FUN_005511b8`, `FUN_0054ba59`).
- **events.md §8** describes event properties decoding under float bit
  patterns as key names. It was written before the fragment parser fixes of
  this release (name-hash fold, type records) and has not been re-checked
  against the new output.

### Corrections found on 2026-10-03 (toolkit 1.4.0)

Found while porting `physx_d6.md` and `vcolor.md` to the toolkit; details and
addresses in `ENGINE_CONSTANTS.md`, section "2026-10-03 — PhysX soft-limit
jiggle; vertex colour, tangent frame and normal-map channels".

- **physx_d6.md §0.3, §5, §7 — "belly not explained".** It is explained. The
  capture's one-step map matches the solver with the file's k = 70 (captured
  0.899 / −0.778 / 0.798, solver 0.890 / −0.775 / 0.800; k = 200 would give
  0.817 for the first coefficient). The deficit in the trace comparison came
  from how the comparison was run: 7.7 % of the belly frames took no physics
  step, and the segments (100–272 frames) begin in mid-motion while the
  comparison started each one at rest. With the observed step pattern the
  solver reaches 1.34° rms on frames 60 onward, against 1.30° for the
  capture-fitted model. The report's own addendum says this.
- **physx_d6.md §5 — "the breast capture ran at 60 fps".** It did not. 5.9 %
  of the breast frames and 7.7 % of the belly frames have a bit-identical
  jiggle palette while the parent moves: frames in which the game ran no
  physics step (`floor(acc/h) = 0`, game 0x4f4ddc). That puts the average
  rate at about 64–65 fps with uneven frame times. "60 fps fits best" meant
  one physics step per captured frame. This also withdraws the 55 fps
  estimate of 1.3.0 and the 30 fps reading before it.
- **physx_d6.md §3 — "frames without a physics step … effect on screen not
  established".** Such frames are in the captures. Modelling them, and the
  doubled anti-gravity force on the step that follows, improves the reference
  fit slightly (BreastR 2.64° → 2.54° rms).
- **physx_d6.md §8 — the proposed model name and the belly advice.** The
  toolkit model is `model="solver"` (`jiggle_d6.SoftLimitJoint`), not
  `model='physx'`, and item 2 ("keep `pivot` for the belly until §7 is
  resolved") no longer has a reason. `solver` is the default model of 1.4.0, for
  every group.
- **physx_d6.md §0.1 — "the task brief's angular drive springs".** The brief
  is not shipped; the toolkit documentation did not describe drive springs.
  What it did say, and what this report corrects, is listed in
  `ENGINE_CONSTANTS.md`: a torque law `spring × error + damping × velocity`,
  one swing axis free to 45°, and the `solver_soften` formula.
- **vcolor.md §6 and its "things to verify" — the TANGENT advice.** The
  suspected clash ("`gltf_tangents` returns w = s while `char_lib` flips
  green") cannot occur in files written by 1.3.0: none of its GLBs carries
  TANGENT or NORMAL. The defect found by rendering is a different one: the PC
  `ATI2` normal layers were decoded with X and Y swapped (Direct3D 9 `ATI2`
  stores the Y block first). With the channels right and green inverted for
  glTF, **w = −s** matches the engine's pixel math to about 1° in the median
  in three.js and in Blender; w = +s does not. The report's own correction
  block says this. `gltf_tangents` now returns −s by default.
- **vcolor.md §6 — "Keep the current flip"** (winding). 1.3.0 flipped the
  winding only in `rig_glb.build_rigged_glb` when normals were passed, which
  no command did. 1.4.0 reverses a primitive's triangles when it writes NORMAL
  for it and the triangles wind against those normals.
- **vcolor.md §5 — non-orthogonal tangents.** The report measures |N·T| > 0.1
  on 9.5 % of 1.80 M vertices; the 1.3.0 notes say 29 % (a different,
  smaller sample: 244,791 triangles). The two figures have not been
  reconciled; the report suggests a different threshold was used.
- **vcolor.md §0 — "31 models".** The figure in the 1.3.0 CHANGELOG ("the 31
  models that have authored colours") is wrong. 387 of 735 Part 2 PC models
  have at least one coloured buffer; 39 of them are under `art/characters`
  and `Animation`. The report says so; the 1.3.0 entry is left as written.

## Reports added 2026-10-04 (toolkit 1.4.0)

Ten more reports, shipped as written. They were read from the same build
with the repaired decompilation and, for the script layer, from the lifted
script handlers that `wp0_script_names.md` describes. They follow the rules
at the top of this file: nothing in them is edited, and several statements
were corrected afterwards — by the implementation, and by one report
correcting another. **Read the "Corrections" list below before relying on
any of them.** Where a report and the toolkit disagree, the toolkit and
`ENGINE_CONSTANTS.md` are current.

The reports name scratch paths (`findings/…`, `work/…`) and large companion
tables that are not in this repository. Only `wp2_ragdoll_rigs.json` is
shipped. The others — `wp0_builtins.json`, `wp0_script_layout.json`,
`wp0_lift_stats.json`, `wp1_renderer.json`, `wp2_physx_vtables.json`,
`wp3_combat_tables.json`, `wp4_ai_tables.json`, `wp5_runtime_tables.json`,
`wp6_sound_tables.json`, `wp7_tables.json`, `dominatrix_audit.json`,
`face_map.json` and the lifted scripts — are kept with the decompilation on
the owner's disk, under `ghidra_kapow_out/engine/engine_notes/`.

| Report | What it establishes | Evidence |
|---|---|---|
| [dominatrix_audit.md](dominatrix_audit.md) | An audit of everything one enemy type touches in the engine, ranked by how much of it was understood; the starting point of the other reports. Establishes that `Dominatrices.fragment` holds nine variants (no `Dominatrix_3`), her weapon collection (baton, paddle), and that the `.fragment.json` files beside the fragments on the owner's disk were stale. | Mixed: a first skim for most steps, stated per step. Superseded in detail by wp1 – wp7. |
| [wp0_script_names.md](wp0_script_names.md) | How the baked script classes name their storage: the variable table at the tail of every `Class__register` (13,205 records, 441 classes, 108 type objects), the three frame models, the member rule; the lifter that turns handlers into readable C. | Read from code; counts measured on the extracted tables. |
| [wp1_renderer.md](wp1_renderer.md) | How a frame is rendered: every pass with its code, target and state; which render list and shader variant a sheet selects; the colour shader's lighting equation; the falloff (rim) term; the post-process grade; occluder meshes and LOD selection. | Read from code and shader bytecode; checked on a 410-frame D3D9 capture of the **main menu** (no combat level, no Dominatrix draw call was captured). |
| [wp2_physics.md](wp2_physics.md) + `wp2_ragdoll_rigs.json` | The ragdoll rig as data in the model file (articulated-body section, 13 rigs), how a character instantiates and runs it, collision groups, the character controller, the PhysX layer's call sites. | Read from code; rigs read from the game files. Ends with its own **Errata** (five items). |
| [wp3_combat.md](wp3_combat.md) | Combat rules: input to action, attack states and combos, damage poses and their run-time modifiers, the defender's reaction table, counters, finishers, health and damage constants, weapons. | Read from the lifted script handlers; constants re-read from the executable; data from the binary fragments. |
| [wp4_ai.md](wp4_ai.md) | Enemy AI: the `Enemy` root behaviour and its ten states, the combat orchestrator, perception, the Kynapse bridge, navigation data (`.aipathdata`, `.hpd` outside the archives). | Read; values from the binary fragments. Its §9 corrects the audit. |
| [wp5_runtime.md](wp5_runtime.md) | From files on disk to a running level: start-up, the scene and node tree, fragment loading, script update order, play modes, save data, level flow, spawners and character groups. Source of the `m_ezonetrigger` key. | Read; measured on the 906 fragments, the `.scene` file and a save profile. |
| [wp6_audio.md](wp6_audio.md) | Audio from game event to speaker: sound definitions and variation, the speech queue and its three categories, footsteps, music, XAudio2 voices and submixes; three extractor defects (multi-track music, stereo rate, PCM offset). | Read from code and bytes; data from fragments and sound headers. |
| [wp7_fx_camera_hud.md](wp7_fx_camera_hud.md) | Effects (particles, sounds, speech per effect), hit feedback, the camera system, HUD and prompts, rumble and time scaling. | Read; data through the toolkit parsers. |
| [face.md](face.md) | The face system: the head as a second character with its own animation class, its four inputs, how a hit, an attack, speech and idle reach the face, and the baked-track rule. Read on 2026-10-03; the base of the toolkit's `--face-rule engine`. | Read from code; measured on the fragments. Extended by the toolkit since (head and neck copy space, the `*_BACK` pose rule, speech: see `ANIMATION_META.md`). |

### Corrections to these reports

Each item names the report that is wrong and where the correction comes
from.

- **wp2_physics.md §0.5(b) — "`kapow_fragment_keys.pkl` lacks the D6 swing
  keys".** Wrong; the report's own Errata item 1 says so. The keys are in the
  table in 1.3.0 and since. The author had read a stale
  `CharacterRootTemplate_Enemy.fragment.json`; the binary parse names every
  key. A test pins the ten hashes.
- **wp2_physics.md A.2 / F — shape size.** The engine grows every shape by
  0.025 and sets a skin width of 0.025; the surface things rest on is the
  stored size (Errata item 2). The exported proxies and the `contact` record
  use the stored size.
- **wp2_physics.md B.3 — velocity at the kinematic → dynamic switch, bones
  without a body, the unique ragdoll collision groups.** Left open in the
  body of the report, read afterwards (Errata items 3 – 5; summarised in
  `RAGDOLL_RIG.md`, "While the game runs").
- **wp6_audio.md — Gimp and GimpGagBall on body class `Enemy01`.** Wrong:
  both use `EnemyBig` (EN2), like ThugBig (`CharacterDef.m_emodelfragment` →
  `PrisonerBigCharVisual` → class id 5). `wp6_sound_tables.json` carries the
  same error and is superseded by `watchmen soundmeta`, which reads the class
  from the fragments.
- **wp6_audio.md §2.4 and dominatrix_audit.md i1 — "a sharp weapon also
  fires its own effect".** Wrong (wp7 §1): weapon type 2 SHARP only selects
  the sharp-weapon effect from the list; the extra effect belongs to type 3
  **TASER** and is effect id 1.
- **wp6_audio.md §0.4 — the three extractor defects.** Fixed in 1.4.0; the
  counts in the report (10 of 13 streams, 35 stereo sounds, PCM read 4 bytes
  late) were confirmed on the full Part 2 PC set: 76 of 2,921 sound files
  change, 10 track-0 files change, 40 track files are new.
- **dominatrix_audit.md d11 — "ragdoll limits and masses are in code, not
  data".** The wrong way round (wp2 §0.1): the rig is data in the model
  file; the code tables are an editor tool's authoring defaults.
- **dominatrix_audit.md c3 — the defender's reaction "comes from
  `PRE_IMPACT` → `hit_soon` → `when_attacked`".** The reaction table is
  evaluated when the attacker enters an attack state
  (`CombatOrchestrator.command_attack_animation_stated` 0x6e6495);
  `hit_soon` → `when_attacked` is the separate face-the-attacker pause (wp3
  "Corrections" 1, wp4 §9).
- **dominatrix_audit.md c3 — tactical flag 0x400 "not established".** It is
  `PLACEMENT_REAR`; 0x200 is `PLACEMENT_FRONT` (wp3 "Corrections" 2, wp4 §9).
- **dominatrix_audit.md — the finisher prompt and the counter.** The prompt
  rolls one of 3 buttons on PC and one of 4 on consoles; a counter needs the
  target to be attacking (or just dodged) and at least 0.13 s before its
  IMPACT, not a special "fourth attack" (wp3 "Corrections" 3, 4).
- **dominatrix_audit.md c2 — `ATTACKING` "when within the attack
  distance".** Within the orchestrator's engagement distance (8 m);
  `m_nattackdistance` is the stand-off range inside `AttackEnemy` (wp4 §9).
- **dominatrix_audit.md c9 — `KynapseCharacter.StateActive` "turns the brain
  velocity into the movement request".** It is a test class with no instance
  in the data; the behaviours read `aiVelocity` themselves (wp4 §9).
- **dominatrix_audit.md c4 — where `_tdocombo` is rolled.** In
  `AttackEnemy.StateActive` at request time, with multiplicity in a uniform
  pick and a weapon filter (wp4 §9).
- **dominatrix_audit.md c12 — difficulty enum order.** NORMAL 0, EASY 1,
  HARD 2; no consumer exists (wp4 §9). The "AI sheets / `AiSheetChanger`" of
  the brief are registered but have no instance (wp4 §9).
- **dominatrix_audit.md b1 — "in pause mode only the script update runs".**
  That sentence describes the branch taken when the flag at scene+0x2d8 is
  set, which is not the pause mode. In play mode 2 (pause) the time step is 0
  and neither update runs; the game's own pause does not use this mode at
  all (wp5 §3).
- **dominatrix_audit.md — "the `.fragment.json` files … should be
  regenerated or deleted".** Still true of the files on the owner's disk; the
  toolkit no longer reads a `.fragment.json` when the binary is there
  (`kapow_json.load_fragment`).
- **wp1_renderer.md §2 — "`impl_sheets.md` 2.1 says twoSided (+0xa1)".** The
  note it corrects is not shipped; the offsets are `writeDepthBuffer` +0xa1,
  `twoSided` +0xa4, as `KAPOW_NAZ_FORMAT.md` §4.6 has them. Its corrections
  of `vcolor.md` (what routes a material to a render list and a shader
  variant) and of the older texture notes (specSize is an exponent
  multiplier, not a matte map; glTF roughness is (2 / (n + 2))^0.25) are in
  `ENGINE_CONSTANTS.md`, "2026-10-04 — renderer, materials, ragdoll, audio".
- **wp1_renderer.md — the falloff gradient.** Not in the report; found while
  implementing the materials: the rim uses the sheet's `depthFadeGradient`
  string baked to a texture at load (0x525650).
- **wp5_runtime.md — key `0x0991b0d4`.** The report identifies it as
  `CharacterGroup.m_ezonetrigger`, an entity reference. Verified (the name
  hashes to the key; 906 of 906 fragments parse with no unknown key) and in
  the key table since.
- **wp7_fx_camera_hud.md §6.9 — `FORMATS_MISC.md` "third list … inferred".**
  Read; `FORMATS_MISC.md` now says so.
- **wp4_ai.md — "`.hpd` outside the archives".** Wrong: the `.hpd` files are
  plain NAZ entries and `watchmen extract` has always written them to
  `files/data/levels/<set>/<level>/gameplay/` (PC, X360 and PS3). Only Part 1
  PC ships them loose in the game's `data/`. Both navigation formats are now
  decoded (`docs/NAV_DATA.md`); the report's item "which level node a
  path-object id is" is answered: the id indexes the serialised
  `aiStaticPathObjectNodes` list of the level's AIWorldNode
  (`docs/NAV_DATA.md`); the level export joins by it.
- **wp5_runtime.md §6.2 — the movie action and `Cam_MainHall`.** The movie
  action's own `_eauxaction` points at the movie node; `Cam_MainHall` is
  reached through the movie action's child `StartCam` (fired after the movie)
  and that child's aux action. `Bordello.level.json` shows exactly this.
- **wp5_runtime.md §2.6 — the nine discrepancies between the engine's
  reference resolution and the toolkit's.** Implemented
  (`docs/FRAGMENT_FORMAT.md`); item 8 was already fixed. The tag-3 fallback
  past the own instance is the one part still on the old rule.
- **wp7_fx_camera_hud.md §5 — event times "from state start".** They were
  play position times duration and ignored the start position, the slot speed
  and the trigger kind: in `Disarm_1h` the report's 0.43 / 0.69 / 1.13 s are
  wrong (DISABLE_ROTATION_INPUT is a TOTAL_PLAY_TIME event, 0.1 s after
  entry; SPEAK, LOOK_AT_TARGET and DROP_WEAPON_WITH_ANIM are ENTER_STATE
  events, 0 s). The clip positions agree with the export to the centisecond.
  Pair numbers 318 / 384 are 334 / 406 in the current table.
- **wp7_fx_camera_hud.md — "273 states / 1,328 events".** The same 1,328
  events sit on 263 states in the toolkit's count: the report's key counted a
  state's blend and folder parents separately.
- **wp7_fx_camera_hud.md §3.4 — the cut angle.** "Relative to the heading
  between the two characters; 0 = pick a free side" is now exact
  (`docs/ENGINE_CONSTANTS.md`, feature-round section; `fx_meta.cut_camera`).
- **wp7_fx_camera_hud.md §2 — particles.** The emission axis is +Y, not Z;
  `startTime` / `endTime` are seconds, not fractions of the duration; the
  first dword of a record is the object id and is interpreted;
  `particleOrientation` is at type +0xb0; `ProximityNoise` is an affector;
  `SurfaceSpawner`, `TerrainSurfaceSpawner` and `EventGeneratorAffector` are
  used by Part 1 data. The five items the report left open (VarianceInitializer,
  GeometryCollisionAffector, the billboard alignment maths, the ring pool
  head, emitter auto-delete) are read: `docs/PARTICLE_FORMAT.md`.
- **events.md — case 59 "skimmed".** Cases 56, 59 and 61 have since been
  read instruction by instruction (`docs/FX_META.md`, `fx.event_fields`).
- **formats.md / KAPOW_NAZ_FORMAT — the language slots.** Established: slot =
  the `LANGUAGE` enum value (English, French, Italian, German, Spanish,
  Danish), slot 5 a copy of slot 0 (`docs/TEXT_ASSETS.md`).
- **wp3_combat.md — additions, no contradiction.** What the combat export
  established beyond the report (combo speed-up by animation type, kick
  damage, the damage-modifier inputs, the counter margin as clip time) is in
  `docs/ENGINE_CONSTANTS.md`, feature-round section.
- **face.md — what was "not established".** Since read or implemented: the
  space of the head / neck bone copy (bone-local), the `*_BACK` pose rule
  (attacker behind: victim-local z < −0.2), how long a voice line lasts
  (`sound_meta`), and the talk segment of a fixed line (face format 2). Since
  read (2026-10-05): the Attack state plays its first slot alone; the COMBAT
  mode rule; the damage-pose conversions and their order
  (`combat.rules.damage_pose`). Still open: the pose a given hit ends with,
  which depends on run-time inputs.

### Corrections found in the review pass (2026-10-05, toolkit 1.4.0)

Each point was read from the executable and checked independently; the
shipped reports keep their text. `docs/ENGINE_CONSTANTS.md`, section
"2026-10-05", has the addresses.

- **wp3_combat.md — "where throw damage is applied: not established".**
  Settled: the property is never read; a throw's damage is ragdoll contact
  damage (COMBAT_META.md "Throws and ragdoll contact damage").
- **wp3_combat.md — sweep stepped at `m_nchecksprsec`.** Wrong: one check per
  0.05 of play position; the property is never read.
- **wp3_combat.md, damage struct note — "+0x1c is the rage flag".** Wrong:
  +0x1c is the push-back time, +0x3c the rage flag, +0x40 ignore-weapon.
- **wp3_combat.md — armour shock "pose NO_POSE".** The attacker gets
  LIGHT_UPPER_STRAIGHT; NO_POSE only for an Underboss attacker.
- **wp4_ai.md — PASSIVE: "no gate on targeting was found".** There is one: a
  PASSIVE enemy idles, or returns to its combat zone when outside it, and
  `Enemy.Evaluate` ends there (0x726214); it neither chases nor attacks until
  it is attacked, damaged, hit by a ragdoll, made an attack target, or woken
  by a SET_AI_STATE action. Also: `_nattackwaittime` is not 0, its registered
  default is 0.5.
- **wp1_renderer.md — the shadow mode switch (`DAT_00c8d3ac`) and
  `castShadow` / `receiveShadow`.** The report gives the switch without its
  source and the two properties as not read; a later research note called
  the switches compile-time and the properties dead. Neither holds: the mode
  is a config key (`shadowmode`: stencil by default, shadowmaps, none), as is
  `usescaledbuffers`; the properties are not read in the default stencil
  mode, and whether the shadow-map mode reads them was not established.
- **wp7_fx_camera_hud.md §5 — how a cut behaves.** An invalid transition
  makes the cut a hard cut, it does not send the camera back; co-op keeps the
  split screen except on the 16 cuts that sit on a slave state; the cast is a
  sweep of width = height = 0.2; a cut's shake values are not applied by the
  cut camera. The toolkit's own later reading that the camera then follows
  the looked-at root was wrong as well: `UpdateWorldPos` has no caller, the
  position is fixed for the shot and only the aim tracks (`docs/FX_META.md`).
- **placement.md §1.3 item 2 — the partner before its go-to event.** It holds
  its entry pose; it does not play its GamePivot motion
  (`docs/ANIMATION_META.md`, *Pair timeline*). And "whether the master's node
  turns" is read: the node is the GamePivot frame, so the anchor swings.
- **formats.md — block header 0x148 (328).** Printed as the u32 `0x593F430A`
  and "inferred to be the version signature" (also in `formats_tables.json`).
  The bytes are `0a 88 3f 59`, identical on the big-endian consoles, with no
  reader. The version signature is the u32 at 32 (0x79D3E0DA), which the
  report lists as unread.
- **skeleton_blobs.md — "third list always 0".** That came from a reader that
  skipped mesh nodes: there are 29 surfaces in 19 models. The list is
  `MeshParticleData`; its float is the triangle area on 27 of 29.
- **formats.md — open items now read.** `.sequence` asset `u94` is the loop
  mode 0..4 and object `u4` the number of fragment hosts to climb (a tag-4
  `a - 1`); "the runtime routing of stream bytes": a load block queues every
  stream and is applied only when all are delivered, and a blob is
  compressed by its asset type (`mediastream` raw), not by its first byte.
- **events.md row 29/30 and `events_table.json` id 30 — "same block as
  FLASH_GRENADE".** Event 30 leaves before the grenade loop; its area damage
  is dealt by `ElectricArmor.AreaDamage` 0x72769f. The row and the table are
  corrected in place. The report's closing note that cases 23, 29/30, 31, 59,
  70 and the footstep block "were skimmed" no longer holds: the footstep
  block was read for the sound table (`wp6_audio.md` 2.2), 23 for the combat
  rules (`wp3_combat.md`), 59 for the effects table, 29–31 and 70 in the
  damage pass.
- **face.md — "hit faces are held 0.75 s".** Conditional: `STUN_MIDDLE` on a
  silent enemy leaves after one update; an attacking character changes to
  `Attack`.
- **vcolor.md — vertex alpha does not select the blended list.** The report
  had a material BLEND whenever the buffer's vertex alpha varies. The list is
  chosen by renderType and opacity alone (0x5739d0) and the opaque lists are
  drawn with blending off; vertex alpha only reaches the alpha test there.
  Where a report derives "the texture has alpha" from the pixels, the engine
  uses the header's `hasAlpha` byte (0x429e77).
- **wp3_combat.md — "the unique attack id rejects a second hit (inferred)".**
  There is no such check: the id is passed by `give_damage` to
  `DecreaseHealth` and from there only into game events 0xcb and 0xc9; no
  handler compares it.
- **wp3_combat.md — "the sender of `i_will_hit_you` is the AI attack
  behaviour".** It is `CharacterRootLogic.command_start_animation_state`
  0x688961, for all characters, when a state with `m_tisattackstate` or special
  handling 4 starts and an attack target exists; the receiver keeps the entry
  1.5 s.
- **wp2_physics.md B.5 (and its summary line) — "corpse timers
  `_nragdolldeathtime` 3 s / fail-safe 15 s".** They are kill conditions of a
  ragdoll-driven character at the end of `command_update_ragdoll` 0x6bc3e2, not
  corpse timers (RAGDOLL_RIG.md, "Get-up failure and corpse settle").
- **ELECTRIFY pose pairs (the wave B small check).** The pair 17 / 14 was
  missing; and the range is the constant 10.0, not a special-data member
  (COMBAT_META.md, area attacks).
- **Property record (the wave C runtime research).** +0x10 is the default
  string, +0x14 the UI string, and +0xc a slot index, not a byte offset
  (SCRIPT_DATABASE.md).

Settled in the same pass without overturning a statement of a shipped
report (the research notes behind them are not shipped):

- Script dispatch: for a command with several versions and a root one, the
  root version is the fallback whenever no state frame above owns the
  command, not only when the entity has no task. `rand_number` is in [0, 1].
- The grade formula: "applied only when enableFilters" holds for the bloom
  filter, grade, gamma and noise, not for depth of field and anti-aliasing;
  fog always comes from the first enabled node.
- The capitalised property names of the dictionary (`Texture`, `Duration`,
  `Position` …) were editor captions; the classes register the lower-case
  forms, and the dictionary now has those (`registered_names.json`).
- Subtitles: the `_uk` / `_pc` cuts of a wave name are case-sensitive, only
  the table lookup folds case; an end time is dropped when `0 <= end <
  start`; a delayed cutscene row appears at the latest end of all earlier
  rows.
- The bone-type table of `CharacterVisual.SetupBoneMap` has 23 entries; type
  22 is `RUpArmTwist`.
- formats.md lists "whether vertices are part-local" and the ModelRes fields
  `u28` and the part's first u32 as open. Measured since: vertices are
  part-local (model space = conj(q)·v·q + pos up the parent chain). Read
  from code since: `u28` is the shadow-hull group id (0x544ae4) and the part
  u32 the pivot-book index (0x53e987). `KAPOW_NAZ_FORMAT.md` §6b.

## Added 2026-10-06 (toolkit 1.4.0): findings without a new report

No report is added here; the material is research tooling kept outside the
toolkit and described in [`../../tools/ghidra/README.md`](../../tools/ghidra/README.md),
"Further tooling, 2026-10-06".

| Subject | What it establishes | Evidence level and limits |
|---|---|---|
| Gap sweep of the PC executable | 324,616 bytes of code lie between the 19,233 dumped functions: tails of 21 functions and 16,318 functions the dump never had, 28 of them registered command handlers (156 registrations). Function bodies that end mid-stream are caused by string tails and table entries taken as code pointers, not by no-return flags | Measured on the executable. Reachability from handlers is a lower bound; 252 functions accepted on decode plausibility only |
| PS3 Part 2 with the Cell VMX instructions | 207 truncated functions completed; none of them is a model, texture or sound loader | Measured on the program. Encodings written from memory, corroborated by disassembly at 469 sites; 531 functions re-decompiled, no full re-dump |
| Xbox 360 Part 2 with VMX128 | 2,049 functions that stopped at bad data re-decompiled; console twins of the model loader, texture and vertex buffer code; no CPU-side packed-vertex decode exists in engine code (0 D3D pack / unpack instructions in 0x82a30000–0x82a38800) | Measured on the image; decompiled C is unreliable for values passing through stack temporaries (331 of 2,049 functions flagged by a text heuristic) |

### Corrections to the shipped reports

- **placement.md §"world data" and its open list — "0xd91bf8 (in .bss, set at
  run time — value not established)".** The address lies in the zero-filled
  tail of `.data` (the file-backed part ends at 0xd90000); the executable
  refers to it 11 times, each an `fld`, and no instruction stores to it
  directly. So the tolerance is 0.0, an exact compare (inferred; a write
  through a computed pointer is not excluded, and it was not read in a
  debugger). `placement_constants.json` keeps its note as written.
- **Statements that a handler "is not in the dump".** 28 registered handlers
  have no function in the 19,233-function dump (0x87b96e, the default
  `command_is_behavior_running`, among them: it writes 0 and returns, read
  from code — as `placement.md` and `wp4_ai.md` assume). Their text is in the
  gap-sweep folder.
- **wp2_physics.md / RAGDOLL_RIG.md — velocity when a ragdoll goes limp.**
  Still read from code only. Knock-downs are located in the D3D9 captures
  (`docs/RAGDOLL_RIG.md`), but the captures hold no frame time and no engine
  state, so the first dynamic frame's velocity is not established.

## Coverage of the executable (2026-10-07)

Measured by cited-address coverage over the merged dump `dump_v5` (35,542 functions: the 19,233
of the earlier dump, 21 of them with their cut tails restored, and 16,309 found by the gap sweep;
kept outside the toolkit, see [`../INDEX.md`](../INDEX.md) §8): every hex address inside `.text`
that a research report or a document of `docs/` cites is mapped to the function whose exact body
ranges contain it, and a function counts as read when at least one cited address falls inside
it. 281 files, 19,166 citations mapped.

| | functions | bytes cited | bytes | share |
|---|---|---|---|---|
| Whole merged dump (35,542 functions) | 3,873 | 2,980,661 | 6,088,997 | 49.0 % |
| Live code (engine and gameplay, without the declarative `*__register` / `RegisterMembers` functions and the debug tests; 14,578 hand-written functions, 513 of them found by the gap sweep) | 3,468 | 1,948,530 | 3,309,065 | 58.9 % |
| – of it cited by a check, review or verify report | | 1,086,183 | 3,309,065 | 32.8 % |
| – never cited | | 1,360,535 | 3,309,065 | 41.1 % |

- The figure is an upper bound on what was read in depth: one cited instruction inside a large
  function marks the whole function, and an address listed under "not established" counts too.
- Not in the live row: 4,368 compiler-generated funclets and stubs whose parent is live code
  (44,459 bytes; 2 of them cited, 18 bytes). Counting them gives 58.1 %.
- Declarative code, with the funclets of the register functions: 909,580 of 1,472,161 bytes
  cited. Libraries and runtime (Kynapse, CRT, vorbis, expat, libjpeg, ATI compress, libpng,
  zlib and smaller ones): 147,334 of 1,390,301 (10.6 %). Debug tests: 1,801 of 177,581.
- The six areas of the "2026-10-07" section of
  [`../ENGINE_CONSTANTS.md`](../ENGINE_CONSTANTS.md), cited / total bytes: animation data
  classes 82.4 %, trigger / waypoint / level-flow classes 77.6 %, effects / lights / tracks /
  cameras 76.6 %, text boxes / sprites / HUD 72.3 %, sound 65.3 %, scene-graph core and model
  resource 62.5 %.
- Largest uncited blocks of live code, in bytes: HUD and menus 123,746; AI 117,669; physics
  85,499; script database 64,517; render core 60,563; character 56,789; triggers and level flow
  50,801; core toolbox 49,631; low-level audio 47,466; player input 46,125.
- The previous count, over the 19,233-function dump and before the reads of 2026-10-07, was
  1,531,660 of 3,268,845 bytes of live code (46.9 %). The live base grew by 28,816 bytes of
  restored tails and 11,404 bytes of hand-written functions found by the gap sweep.
