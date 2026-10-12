# Reverse-engineering notes

Twenty-one notes read from the decompiled game executable `KapowMultiDEDRM.exe` (32-bit x86 PE,
image base 0x400000), plus one (`physx_d6.md`) read from `PhysXCore.dll` (PhysX 2.8.1.1, image base
0x10000000). Each cites the function addresses it rests on and tags every finding as read from code
(`[code]`), inferred, measured on the shipped data or on a capture, or not established. Addresses
belong to this one build. The decompilation they are read from is produced by the scripts in
[`../../tools/ghidra/`](../../tools/ghidra/README.md).

The notes describe the engine. Where a note and the toolkit disagree, the toolkit and
[`../ENGINE_CONSTANTS.md`](../ENGINE_CONSTANTS.md) are current. The companion `*.json` files in this
folder are the notes' machine-readable tables. The larger scratch tables the notes mention
(`wp0_builtins.json`, `wp0_script_layout.json`, `wp0_lift_stats.json`, `wp1_renderer.json`,
`wp2_physx_vtables.json`, `wp3_combat_tables.json`, `wp4_ai_tables.json`, `wp5_runtime_tables.json`,
`wp6_sound_tables.json`, `wp7_tables.json`, `dominatrix_audit.json`, `face_map.json`, the lifted
scripts, and the `findings/…` / `work/…` paths) are kept with the decompilation outside this
repository, under `ghidra_kapow_out/engine/engine_notes/`. Only `wp2_ragdoll_rigs.json` of that set
is shipped here.

## The notes

### [events.md](events.md) — what each animation event does

Reads the sender (`CheckPlayPosEvents` 0x5b51f3), the delivery path and the receiver
`CharacterRootLogic.command_animation_event_received` (0x6a525e, 37 kB), and gives a case map for
every `ANIMATION_EVENT` id: which fields it writes and which commands it sends. Establishes the
four trigger kinds (`PLAY_POS`, `ENTER_STATE`, `LEAVE_STATE`, `TOTAL_PLAY_TIME`), that
`ABSOLUTE_GOTO_TARGET_POS` only sets one capsule flag, that `LOOK_AT_TARGET` is a camera event, and
what `LEAVE_ABSOLUTE_MODE` and `KILL_ANIMATION_PARTNER` do. Evidence: read from code throughout;
all cases (ids 6, 23, 29, 30, 31, 40, 59, 70, 76, 77 among them) are read instruction by
instruction — 56, 59 and 61 for the effects table (`docs/FX_META.md`, `fx.event_fields`), 23 for the
combat rules (`wp3_combat.md`), 29–31 and 70 in the damage pass, and the footstep block for the
sound table (`wp6_audio.md` 2.2). Table: `events_table.json` (93 ids).

### [placement.md](placement.md) — paired animation placement

The placement block in `CharacterRoot.StateActive` runs every tick; its output takes effect only
while the partner capsule's flag at +0xb8 is set; no shipped master state is an absolute animation,
so the master is never snapped; how a pair ends; the loop offset; the auto-align step. Ends with a
rule for tool writers, split into "read from code" and "inferred". Evidence: read from
decompilation and disassembly, plus tallies measured on the Part 2 PC fragments and clips; the
open points are listed in its last sections. Constants: `placement_constants.json`.

### [sync.md](sync.md) — transition sync markers and start play position

Property table of `AnimationTransition`, how the eight (local, remote) marker pairs are sorted and
cached at init (`UpdateSuperSync` 0x5fa582), how they gate a transition (`TransitionMet` 0x5c5ea4)
and choose the target's start position (`TransitionPlayPos` 0x5ac1aa), and the priority order of
the four start rules. Evidence: read from code, with the constants checked in the exe bytes; one
field meaning is marked inferred. Includes a data check over the Part 2 PC fragments.

### [enums.md](enums.md) — every enum the executable registers

How enums are registered (`FUN_005052c9(family, name, value)`), all 1,813 registrations resolved
into 186 families and 1,801 names, the criteria kinds and what each reads, and five points where
the engine differs from what a reader of the fragments would assume (enum variable 11 is the
opponent's model type; the "value slot" is not a selector). Evidence: read from code; the animation
families are checked against the editor captions in the shipped fragments. The note lists the
animation-related families in full and all families by name; the complete machine-readable table
is not shipped here — the 30 families the toolkit uses are in `wlib/engine_enums.json`.

### [pages.md](pages.md) — animation pages and play position

`SetupNewPage` 0x5b7788 and `UpdatePagePlayPos` 0x5b56a9: what a page is, the record offsets of
states, transitions, slots and blend nodes, the rate and the 6.6 /s clamp, loop wrap, page
blending, event latching, and how a clip time becomes a key index. Closes with an item-by-item
comparison against `bake_v4.py` and `anim_state_machine.py`. Evidence: read from code unless tagged
otherwise; counts measured on 8 class fragments and 1,185 clips. Offsets: `pages_offsets.json`.

### [skeleton_blobs.md](skeleton_blobs.md) — the "joint blobs" are collision volumes

The records in a `.model` node tail are the node's collision volumes: concave mesh, convex mesh,
box, sphere, capsule, in two lists (one per PhysX scene) followed by a third list. Gives the reader
(`Node::Deserialize` 0x545927, factory 0x524b23) and the layout per type. Evidence: read from code,
tiling verified on the extracted files. Layout: `skeleton_blobs_layout.json`.

### [jiggle.md](jiggle.md) — secondary motion, exe side

Setup (`CharacterAddonCtrl` 0x6574cd), joint configuration (0x648858), the physics step, the
per-frame anti-gravity force and the write-back (0x6563a0). Shows that the simulated body is a
0.8 m box pivoting about the parent bone origin, that the bone's local position and rotation are
both replaced, that gravity is cancelled, and that nothing on the path scales the spring or damping.
Evidence: read from code, cross-checked against capture palettes; the effective stiffness and
damping are stated as not derivable from the exe. Constants: `jiggle_constants.json`.

### [formats.md](formats.md) — file formats from the engine's loaders

Block header and directory, the two unnamed asset-type hashes, the complete set of vertex formats
and the ModelRes header and stream layout, the `.sequence` grammar, the Texture header, and the
per-platform texture format table. States plainly what the PC executable cannot answer (PS3 cube
framing, the X360 2D mip tail). Evidence: read from code, and "validated" where the reference
parsers reproduce real files exactly (models 740 / 740, textures 936 / 936, sequences 194 / 194).
Tables: `formats_tables.json`, `formats_vertex_decls.json`. The reference parsers it mentions are
not shipped; their logic is in `wlib/watchmen_extract.py` and `wlib/decode_sequence.py`.

### [names.md](names.md) — the name hash, command hashes, property names

The engine folds every byte of a name with `& 0xDF` before hashing, which differs from
upper-casing for digits and punctuation. With that, all 1,696 distinct command hashes are
reproduced (bare name, or `name(type,…)` for commands with parameters) and all 3,695 registered
property hashes are named. Evidence: the hasher and the registration records are read from code;
that the offline script compiler used the same routine for signatures is inferred from the exact
reproduction. The per-hash tables it refers to are not shipped here; the results are in
`wlib/reg_dump.json`, `wlib/command_signatures.json` and `wlib/kapow_fragment_keys.pkl`.

### [physx_d6.md](physx_d6.md) — what PhysX does with the jiggle joint

Follows the game's joint descriptor into `PhysXCore.dll`: the class and descriptor path
(`NpD6Joint::loadFromDesc` 0x10135430 → `PxsD6Joint`), the constraint setup the island solver
calls once per substep (0x10227db0), the angular, linear and soft row builders (0x10227a70,
0x10227640, 0x102068b0), the row iteration and the conclude pass (0x1022ce80 / 0x1022ccb0,
0x1022d500 / 0x1022d450), body integration (0x101ffb50, 0x102008a0) and the kinematic anchor
(0x10034c10). Establishes that the joint has no drive — every `driveType` is 0 — and that the
file's spring and damping are the soft swing limits; that two limited swing axes are one cone
limit, here of radius 0 (45° and 0°), a one-sided soft row whose error is tan(swing/4); the row
coefficients (`gamma = 1/(dt(d + k·dt))`, `erp = k·dt/(d + k·dt)`, scaled by the cube's inertia
about its centre, position term × 0.7); 4 iterations and a conclude pass, with the pose integrated
from the pre-conclude velocity; and that no stiffness / damping pair of a linear model reproduces
the result — it is a per-step procedure. Evidence: the DLL-side statements are read from
decompilation and disassembly, with the constants taken from the DLL's bytes; the game-side
cross-check (§7) is read from the executable. Three things are inferred and say so: that the
kinematic anchor has zero inverse mass in the solver, which actor is `actor[0]`, and that the
high-level `D6Joint` functions (0x10082550, 0x100868c0) do not also act. The capture comparisons
(§5) are measurements. Collision of the 0.8 m jiggle box and hair are not established (no hair
capture exists). Table: `physx_d6.json` (addresses, offsets, constants, test results). The
reference integrator it mentions (`d6_ref.py`) is not shipped; its logic is
`jiggle_d6.SoftLimitJoint`, and a frozen transcription is in `tests/test_jiggle_solver.py`.

### [vcolor.md](vcolor.md) — vertex colour, tangent frame, winding

Disassembles all 243 shaders of the game's shader archive (a from-scratch SM3 disassembler, checked
against the shaders the game creates in a D3D9 capture) and reads the executable for how a shader
variant is chosen. Establishes that `COLOR0` on a model vertex multiplies the complete lit colour
(rgb) and the output alpha (a), and nothing else; that it is used exactly when the mesh buffer's
`hasColor` byte is set (`MeshBuffer+0x31`, selecting the `VERTEX_COLORS` vertex shader), which is
387 of 735 models and 1,453 buffers; that the pixel shader builds the shading normal as
`x·T + y·B + z·N` from the **stored** tangent and bitangent, with no cross product and no
handedness sign; that one-sided materials are drawn with `D3DCULL_CW` and two-sided ones
(`sheet+0xA4`) with `D3DCULL_NONE`; and the statistics of the stored colours and tangent frames.
Evidence: tagged per statement as read from shader bytecode, read from the executable, measured on
the Part 2 PC models, or measured on the capture; the handedness reading and one shader-quality
flag are inferred. 19 of 243 shader define sets are unresolved, none of them a model vertex shader
in the capture (`wp1_renderer.md` 3.4 resolves 16 of the 19). Not established: what produced the
colours (bake or paint); console shader archives are not examined. Scope is Part 2 PC, vertex
formats 5 and 6. Table: `vcolor_shaders.json` (every shader's define set, inputs and the
instructions that read `COLOR0`; colour and tangent statistics; the capture draw table). The
disassembler and the per-shader listings it mentions are not shipped.

### [dominatrix_audit.md](dominatrix_audit.md) — everything one enemy type touches

An audit of everything one enemy type touches in the engine, ranked by how much of it is
understood; the starting point of the wp1–wp7 notes. Establishes that `Dominatrices.fragment`
holds nine variants (no `Dominatrix_3`) and her weapon collection (baton, paddle). Evidence:
mixed, a first skim for most steps, stated per step. Superseded in detail by wp1–wp7; the points
where it is wrong are listed under "Findings recorded here".

### [wp0_script_names.md](wp0_script_names.md) — names for the baked scripts

How the baked script classes name their storage: the variable table at the tail of every
`Class__register` (13,205 records, 441 classes, 108 type objects), the three frame models, the
member rule; the lifter that turns handlers into readable C. Evidence: read from code; counts
measured on the extracted tables.

### [wp1_renderer.md](wp1_renderer.md) — how a frame is rendered

Every pass with its code, target and state; which render list and shader variant a sheet selects;
the colour shader's lighting equation; the falloff (rim) term; the post-process grade; occluder
meshes and LOD selection; what the mapping means for a glTF export. Evidence: read from code and
shader bytecode; checked on a 410-frame D3D9 capture of the **main menu** (no combat level, no
Dominatrix draw call).

### [wp2_physics.md](wp2_physics.md) + `wp2_ragdoll_rigs.json` — ragdolls and the PhysX layer

The ragdoll rig as data in the model file (articulated-body section, 13 rigs), how a character
instantiates and runs it, collision groups, the character controller, the PhysX layer's call
sites, and the GLB / Blender representation of a rig. Evidence: read from code; rigs read from the
game files.

### [wp3_combat.md](wp3_combat.md) — combat rules

Input to action, attack states and combos, damage poses and their run-time modifiers, the
defender's reaction table, counters, finishers, health and damage constants, weapons; a worked
example for the Dominatrix. Evidence: read from the lifted script handlers; constants re-read from
the executable; data from the binary fragments.

### [wp4_ai.md](wp4_ai.md) — enemy AI

The `Enemy` root behaviour and its ten states, the combat orchestrator, perception, the Kynapse
bridge, navigation data (`.aipathdata`, `.hpd`). Evidence: read; values from the binary fragments.
Its §9 corrects the audit.

### [wp5_runtime.md](wp5_runtime.md) — from files on disk to a running level

Start-up, the scene and node tree, fragment loading, script update order, play modes, save data,
level flow, spawners and character groups. Source of the `m_ezonetrigger` key. Evidence: read;
measured on the 906 fragments, the `.scene` file and a save profile.

### [wp6_audio.md](wp6_audio.md) — audio from game event to speaker

Sound definitions and variation, the speech queue and its three categories, footsteps, music,
XAudio2 voices and submixes; three extractor defects (multi-track music, stereo rate, PCM offset).
Evidence: read from code and bytes; data from fragments and sound headers.

### [wp7_fx_camera_hud.md](wp7_fx_camera_hud.md) — effects, camera, HUD

Effects (particles, sounds, speech per effect), hit feedback, the camera system, HUD and prompts,
rumble and time scaling. Evidence: read; data through the toolkit parsers.

### [face.md](face.md) — the face system

The head as a second character with its own animation class, its four inputs, how a hit, an
attack, speech and idle reach the face, and the baked-track rule; the base of the toolkit's
`--face-rule engine`. Evidence: read from code; measured on the fragments. Extended by the toolkit
(head and neck copy space, the `*_BACK` pose rule, speech: see `ANIMATION_META.md`).

## Frame convention

The notes write the engine's left-handed numbers verbatim. Where they say "the export is a mirror
image", "mirror X", "the GLB is the same space as the engine" or "indices must be reversed", they
describe the `--frame mirrored` output. The default output is true-handed (x = −engine x, file
winding); the notes' own alternative — "negate X on positions, normals and tangents and keep the
indices … negate [TANGENT w] once more" (`vcolor.md`, section 6) — is what the default does.

## Findings recorded here

Facts established after the notes were written, which the notes do not state or state otherwise.
Addresses and details are in `ENGINE_CONSTANTS.md`; the toolkit documents named are current.

### names.md, enums.md

- Property registration `0x47fde4` takes `(hash, defaultVA|0, uiVA, flags, typeIdx)`.
- `typeIdx` is the declaring class: the last argument of the property and command registrations
  indexes `DAT_00c89ebc` and identifies the class that declares the member (it equals the class's
  own id at 4,262 of 5,090 property sites). It is not a value type, so a registration site cannot
  type a property; read every mention of "type index" that way.
- A property record: +0x10 is the default string, +0x14 the UI string, +0xc a slot index, not a
  byte offset (`SCRIPT_DATABASE.md`).
- Asset names use the folding hash (`FUN_005511b8`, `FUN_0054ba59`).
- The capitalised property names of the dictionary (`Texture`, `Duration`, `Position` …) are editor
  captions; the classes register the lower-case forms, and the dictionary has those
  (`registered_names.json`).
- Script dispatch: for a command with several versions and a root one, the root version is the
  fallback whenever no state frame above owns the command, not only when the entity has no task.
  `rand_number` is in [0, 1].

### events.md, pages.md, sync.md

- Event latching: in normal play an event fires once per pass when `m_nplaypos <= play position`
  and it has not fired yet (0x5b55c4); `TOTAL_PLAY_TIME` fires when `m_nplaypos <= seconds played`
  (0x5b52c1). The comparison is `<=`, and an event at or before the page's start position is
  created already fired (0x5b8f16). The (previous, current] window test applies only under the
  AnimationData debug play-position override.
- The partner's blend time is the partner state's own ease-in: `goto_slave_mode` 0x5b32a2 →
  `ForceToState` 0x5b4933 with ease −1 → `SetupNewPage` takes the state's `m_neaseinduration` and
  passes page +0x0c to the absolute-mode message.
- Page +0x14 is a rate (play position per second), not a cycle length; `SynchronizePages` blends
  periods. The per-slot speed is the slot's `speedFactor` property.
- A transition to a state is gated by the transition's criteria, the target state's own criteria
  (appended by `AnimationTransition.initialize_external` 0x5f9b13) and its owning groups' criteria.
  The class root owns no transitions.
- pages.md item B6, the constant position of type 1 / 3 clip tracks: the shipped constants are
  absolute values (prone pose clips match their continuation clips to 1 mm), so adding the bind
  offset would create a pop; `bake_v4.py` does not add it. What the engine's added pose term holds
  is open.
- Event 30 (events.md row 29/30, `events_table.json` id 30) leaves before the grenade loop; its
  area damage is dealt by `ElectricArmor.AreaDamage` 0x72769f.
- events.md §8 describes event properties decoding under float bit patterns as key names; it was
  written before the fragment parser's name-hash fold and type records and is not re-checked
  against the current output.

### placement.md

- The slave is time-synced to the master: `goto_slave_mode` stores the master's first animation
  source in the partner's controller, and `UpdatePagePlayPos` 0x5b5756 copies that source's play
  position into the partner's top page every frame until it reaches 1.
- Turning masters: the note's count (33 pairs) compares the master's `GamePivot` yaw at a start and
  an end point over 234 pairs; the export (39) takes the largest turn from t = 0 anywhere inside the
  partner's anchored window (threshold 2° in both) over the 240 primary pairs of the final table.
  The case both name agrees exactly: `RSH_COM_ATT_throw_EN1`, drift 1.447 m.
- §1.3 item 2, the partner before its go-to event: it holds its entry pose; it does not play its
  GamePivot motion (`docs/ANIMATION_META.md`, *Pair timeline*). The master's node is the GamePivot
  frame, so the anchor swings.
- The tolerance at 0xd91bf8: the address lies in the zero-filled tail of `.data` (the file-backed
  part ends at 0xd90000); the executable refers to it 11 times, each an `fld`, and no instruction
  stores to it directly. So the tolerance is 0.0, an exact compare (inferred; a write through a
  computed pointer is not excluded, and it was not read in a debugger). `placement_constants.json`
  keeps its note as written.
- The default `command_is_behavior_running` 0x87b96e, which placement.md and wp4_ai.md assume,
  writes 0 and returns (read from code; it is one of the 28 registered handlers that have no
  function in the 19,233-function dump, see "Coverage").

### skeleton_blobs.md, formats.md

- "1475 `.model` files" counts the `.model.stream` files too; there are 740 models. With the engine
  layout 2,069 of 2,069 mesh-free node regions tile. `Female_Skeleton.model` has 32 volumes, not 30.
- The third list is `MeshParticleData` (emitter surfaces): 29 surfaces in 19 models (a reader that
  skips mesh nodes sees none); its float is the triangle area on 27 of 29. One node in the PC corpus
  (`ACUnit_Wall_02`, "splash emitter") has one element.
- Block header 0x148 (328): the bytes are `0a 88 3f 59`, identical on the big-endian consoles, with
  no reader; the u32 `0x593F430A` printed there (also in `formats_tables.json`) is not a version
  signature. The version signature is the u32 at 32 (0x79D3E0DA).
- `.sequence` asset `u94` is the loop mode 0..4 and object `u4` the number of fragment hosts to
  climb (a tag-4 `a - 1`). The runtime routing of stream bytes: a load block queues every stream and
  is applied only when all are delivered, and a blob is compressed by its asset type (`mediastream`
  raw), not by its first byte.
- Vertices are part-local (model space = conj(q)·v·q + pos up the parent chain) [measured]. ModelRes
  `u28` is the shadow-hull group id (0x544ae4) and the part's first u32 the pivot-book index
  (0x53e987) [code]. `KAPOW_NAZ_FORMAT.md` §6b.
- The language slots: slot = the `LANGUAGE` enum value (English, French, Italian, German, Spanish,
  Danish), slot 5 a copy of slot 0 (`docs/TEXT_ASSETS.md`).
- The bone-type table of `CharacterVisual.SetupBoneMap` has 23 entries; type 22 is `RUpArmTwist`.

### jiggle.md, physx_d6.md

- The capture figures: the stiffness and damping quoted from capture fits (K ≈ 150–170, D ≈ 11–19)
  assume a 30 fps capture; a re-measurement at an assumed 55 fps gave K ≈ 570 s⁻², D ≈ 37.5 s⁻¹.
  Both rates are withdrawn, and with them the K / D values, which scale with the assumed rate: 5.9 %
  of the breast frames and 7.7 % of the belly frames have a bit-identical jiggle palette while the
  parent moves — frames in which the game ran no physics step (`floor(acc/h) = 0`, game 0x4f4ddc).
  That puts the average rate at about 64–65 fps with uneven frame times; "60 fps fits best" means
  one physics step per captured frame.
- `SetMass` is "argument if above a threshold, else 0.1", not `max(arg, 0.1)` (same result here).
- physx_d6.md §0.3, §5, §7, the belly: it is explained. The capture's one-step map matches the
  solver with the file's k = 70 (captured 0.899 / −0.778 / 0.798, solver 0.890 / −0.775 / 0.800;
  k = 200 would give 0.817 for the first coefficient). The deficit in the trace comparison comes
  from how the comparison was run: 7.7 % of the belly frames took no physics step, and the segments
  (100–272 frames) begin in mid-motion while the comparison started each one at rest. With the
  observed step pattern the solver reaches 1.34° rms on frames 60 onward, against 1.30° for the
  capture-fitted model.
- Frames without a physics step are in the captures. Modelling them, and the doubled anti-gravity
  force on the step that follows, improves the reference fit slightly (BreastR 2.64° → 2.54° rms).
- The toolkit model is `model="solver"` (`jiggle_d6.SoftLimitJoint`), the default for every group;
  there is no `model='physx'`, and no reason to keep `pivot` for the belly.
- The brief physx_d6.md §0.1 argues against ("the task brief's angular drive springs") is not
  shipped; what it corrects in the toolkit's earlier description is a torque law
  `spring × error + damping × velocity`, one swing axis free to 45°, and the `solver_soften`
  formula (`ENGINE_CONSTANTS.md`).

### vcolor.md

- TANGENT w: with the PC `ATI2` normal layers decoded in the right channel order (Direct3D 9 `ATI2`
  stores the Y block first) and green inverted for glTF, **w = −s** matches the engine's pixel math
  to about 1° in the median in three.js and in Blender; w = +s does not. `gltf_tangents` returns
  −s by default. The suspected clash of §6 ("`gltf_tangents` returns w = s while `char_lib` flips
  green") does not occur.
- Winding: a primitive's triangles are reversed when NORMAL is written for it and the triangles
  wind against those normals.
- Non-orthogonal tangents: the note measures |N·T| > 0.1 on 9.5 % of 1.80 M vertices; an earlier
  figure of 29 % came from a different, smaller sample (244,791 triangles). The two are not
  reconciled; a different threshold is the likely reason.
- 387 of 735 Part 2 PC models have at least one coloured buffer; 39 of them are under
  `art/characters` and `Animation`. A figure of "31 models" is wrong.
- Vertex alpha does not select the blended list. The list is chosen by renderType and opacity
  alone (0x5739d0) and the opaque lists are drawn with blending off; vertex alpha only reaches the
  alpha test there. Where a note derives "the texture has alpha" from the pixels, the engine uses
  the header's `hasAlpha` byte (0x429e77).
- What routes a material to a render list and a shader variant: `wp1_renderer.md` 2.1 and 3.2.
  The older texture notes' reading of specSize as a matte map is wrong: it is an exponent
  multiplier, and the glTF roughness is (2 / (n + 2))^0.25 (`wp1_renderer.md` 4.4, 7.2).

### dominatrix_audit.md

- d11, "ragdoll limits and masses are in code, not data": the wrong way round (wp2 §0.1): the rig
  is data in the model file; the code tables are an editor tool's authoring defaults.
- c3, the defender's reaction "comes from `PRE_IMPACT` → `hit_soon` → `when_attacked`": the reaction
  table is evaluated when the attacker enters an attack state
  (`CombatOrchestrator.command_attack_animation_stated` 0x6e6495); `hit_soon` → `when_attacked` is
  the separate face-the-attacker pause (wp3 §0, wp4 §9).
- c3, tactical flag 0x400: it is `PLACEMENT_REAR`; 0x200 is `PLACEMENT_FRONT` (wp3 §0, wp4 §9).
- The finisher prompt rolls one of 3 buttons on PC and one of 4 on consoles; a counter needs the
  target to be attacking (or just dodged) and at least 0.13 s before its IMPACT, not a special
  "fourth attack" (wp3 §0).
- c2, `ATTACKING` "when within the attack distance": within the orchestrator's engagement distance
  (8 m); `m_nattackdistance` is the stand-off range inside `AttackEnemy` (wp4 §9).
- c9, `KynapseCharacter.StateActive` "turns the brain velocity into the movement request": it is a
  test class with no instance in the data; the behaviours read `aiVelocity` themselves (wp4 §9).
- c4, where `_tdocombo` is rolled: in `AttackEnemy.StateActive` at request time, with multiplicity
  in a uniform pick and a weapon filter (wp4 §9).
- c12, difficulty enum order: NORMAL 0, EASY 1, HARD 2; no consumer exists. The "AI sheets /
  `AiSheetChanger`" are registered but have no instance (wp4 §9).
- b1, "in pause mode only the script update runs": that sentence describes the branch taken when
  the flag at scene+0x2d8 is set, which is not the pause mode. In play mode 2 (pause) the time step
  is 0 and neither update runs; the game's own pause does not use this mode at all (wp5 §3).
- i1 (and wp6_audio.md §2.4), "a sharp weapon also fires its own effect": weapon type 2 SHARP only
  selects the sharp-weapon effect from the list; the extra effect belongs to type 3 **TASER** and is
  effect id 1 (wp7 §1).
- The `.fragment.json` files beside the fragments on the owner's disk are stale; the toolkit does
  not read a `.fragment.json` when the binary is there (`kapow_json.load_fragment`).

### wp4_ai.md

- PASSIVE: a PASSIVE enemy idles, or returns to its combat zone when outside it, and
  `Enemy.Evaluate` ends there (0x726214); it neither chases nor attacks until it is attacked,
  damaged, hit by a ragdoll, made an attack target, or woken by a SET_AI_STATE action.
  `_nattackwaittime` is not 0; its registered default is 0.5.
- The `.hpd` files are plain NAZ entries and `watchmen extract` writes them to
  `files/data/levels/<set>/<level>/gameplay/` (PC, X360 and PS3); only Part 1 PC ships them loose in
  the game's `data/`. Both navigation formats are decoded (`docs/NAV_DATA.md`); a path-object id
  indexes the serialised `aiStaticPathObjectNodes` list of the level's AIWorldNode, and the level
  export joins by it.

### wp5_runtime.md

- Key `0x0991b0d4` is `CharacterGroup.m_ezonetrigger`, an entity reference: the name hashes to the
  key, 906 of 906 fragments parse with no unknown key, and it is in the key table.
- §6.2, the movie action and `Cam_MainHall`: the movie action's own `_eauxaction` points at the
  movie node; `Cam_MainHall` is reached through the movie action's child `StartCam` (fired after the
  movie) and that child's aux action. `Bordello.level.json` shows exactly this.
- §2.6, the nine discrepancies between the engine's reference resolution and the toolkit's: the
  toolkit follows the engine (`docs/FRAGMENT_FORMAT.md`), except the tag-3 fallback past the own
  instance, which is still on the old rule.
- Subtitles: the `_uk` / `_pc` cuts of a wave name are case-sensitive, only the table lookup folds
  case; an end time is dropped when `0 <= end < start`; a delayed cutscene row appears at the latest
  end of all earlier rows.

### wp6_audio.md

- Gimp and GimpGagBall use body class `EnemyBig` (EN2), like ThugBig (`CharacterDef.m_emodelfragment`
  → `PrisonerBigCharVisual` → class id 5), not `Enemy01`. `wp6_sound_tables.json` carries the
  `Enemy01` error and is superseded by `watchmen soundmeta`, which reads the class from the fragments.
- §0.4, the three extractor defects (10 of 13 streams, 35 stereo sounds, PCM read 4 bytes late),
  measured on the full Part 2 PC set: 76 of 2,921 sound files change, 10 track-0 files change, 40
  track files are new. The toolkit extractor has the fixes.

### wp7_fx_camera_hud.md

- §5, event times "from state start": the note's times are play position times duration and ignore
  the start position, the slot speed and the trigger kind. In `Disarm_1h` its 0.43 / 0.69 / 1.13 s
  are wrong: DISABLE_ROTATION_INPUT is a TOTAL_PLAY_TIME event, 0.1 s after entry; SPEAK,
  LOOK_AT_TARGET and DROP_WEAPON_WITH_ANIM are ENTER_STATE events, 0 s. The clip positions agree
  with the export to the centisecond. Pair numbers 318 / 384 are 334 / 406 in the current table.
- "273 states / 1,328 events": the same 1,328 events sit on 263 states in the toolkit's count; the
  note's key counts a state's blend and folder parents separately.
- §3.4, the cut angle: relative to the heading between the two characters; 0 = pick a free side
  (`docs/ENGINE_CONSTANTS.md`; `fx_meta.cut_camera`).
- §5, how a cut behaves: an invalid transition makes the cut a hard cut, it does not send the camera
  back; co-op keeps the split screen except on the 16 cuts that sit on a slave state; the cast is a
  sweep of width = height = 0.2; a cut's shake values are not applied by the cut camera. The camera
  does not follow the looked-at root afterwards: `UpdateWorldPos` has no caller, the position is
  fixed for the shot and only the aim tracks (`docs/FX_META.md`).
- §2, particles: the emission axis is +Y, not Z; `startTime` / `endTime` are seconds, not fractions
  of the duration; the first dword of a record is the object id and is interpreted;
  `particleOrientation` is at type +0xb0; `ProximityNoise` is an affector; `SurfaceSpawner`,
  `TerrainSurfaceSpawner` and `EventGeneratorAffector` are used by Part 1 data. The five items the
  note leaves open (VarianceInitializer, GeometryCollisionAffector, the billboard alignment maths,
  the ring pool head, emitter auto-delete) are read: `docs/PARTICLE_FORMAT.md`.
- §6.9, `FORMATS_MISC.md` "third list … inferred": read; `FORMATS_MISC.md` says so.
- ELECTRIFY pose pairs: the pair 17 / 14 belongs in the table, and the range is the constant 10.0,
  not a special-data member (`COMBAT_META.md`, area attacks).

### face.md

- Read or implemented since the note: the space of the head / neck bone copy (bone-local), the
  `*_BACK` pose rule (attacker behind: victim-local z < −0.2), how long a voice line lasts
  (`sound_meta`), the talk segment of a fixed line (face format 2), the Attack state playing its
  first slot alone, the COMBAT mode rule, and the damage-pose conversions and their order
  (`combat.rules.damage_pose`). Still open: the pose a given hit ends with, which depends on
  run-time inputs.
- "Hit faces are held 0.75 s" is conditional: `STUN_MIDDLE` on a silent enemy leaves after one
  update; an attacking character changes to `Attack`.

### Post-processing (no note)

- "Applied only when enableFilters" holds for the bloom filter, grade, gamma and noise, not for
  depth of field and anti-aliasing; fog always comes from the first enabled node.

## Findings outside the notes

Research tooling kept outside the toolkit and described in
[`../../tools/ghidra/README.md`](../../tools/ghidra/README.md), "Further tooling".

| Subject | What it establishes | Evidence level and limits |
|---|---|---|
| Gap sweep of the PC executable | 324,616 bytes of code lie between the 19,233 dumped functions: tails of 21 functions and 16,318 functions the dump never had, 28 of them registered command handlers (156 registrations). Function bodies that end mid-stream are caused by string tails and table entries taken as code pointers, not by no-return flags | Measured on the executable. Reachability from handlers is a lower bound; 252 functions accepted on decode plausibility only |
| PS3 Part 2 with the Cell VMX instructions | 207 truncated functions completed; none of them is a model, texture or sound loader | Measured on the program. Encodings written from memory, corroborated by disassembly at 469 sites; 531 functions re-decompiled, no full re-dump |
| Xbox 360 Part 2 with VMX128 | 2,049 functions that stopped at bad data re-decompiled; console twins of the model loader, texture and vertex buffer code; no CPU-side packed-vertex decode exists in engine code (0 D3D pack / unpack instructions in 0x82a30000–0x82a38800) | Measured on the image; decompiled C is unreliable for values passing through stack temporaries (331 of 2,049 functions flagged by a text heuristic) |

Statements in the notes that a handler "is not in the dump": 28 registered handlers have no
function in the 19,233-function dump (0x87b96e, the default `command_is_behavior_running`, among
them). Their text is in the gap-sweep folder.

## Coverage of the executable

Measured by cited-address coverage over the merged dump `dump_v5` (35,542 functions: the 19,233
of the earlier dump, 21 of them with their cut tails restored, and 16,309 found by the gap sweep;
kept outside the toolkit, see [`../INDEX.md`](../INDEX.md) §8): every hex address inside `.text`
that a note or a document of `docs/` cites is mapped to the function whose exact body ranges
contain it, and a function counts as read when at least one cited address falls inside it. 281
files, 19,166 citations mapped.

| | functions | bytes cited | bytes | share |
|---|---|---|---|---|
| Whole merged dump (35,542 functions) | 3,873 | 2,980,661 | 6,088,997 | 49.0 % |
| Live code (engine and gameplay, without the declarative `*__register` / `RegisterMembers` functions and the debug tests; 14,578 hand-written functions, 513 of them found by the gap sweep) | 3,468 | 1,948,530 | 3,309,065 | 58.9 % |
| – of it cited by a check, review or verify note | | 1,086,183 | 3,309,065 | 32.8 % |
| – never cited | | 1,360,535 | 3,309,065 | 41.1 % |

- The figure is an upper bound on what was read in depth: one cited instruction inside a large
  function marks the whole function, and an address listed under "not established" counts too.
- Not in the live row: 4,368 compiler-generated funclets and stubs whose parent is live code
  (44,459 bytes; 2 of them cited, 18 bytes). Counting them gives 58.1 %.
- Declarative code, with the funclets of the register functions: 909,580 of 1,472,161 bytes
  cited. Libraries and runtime (Kynapse, CRT, vorbis, expat, libjpeg, ATI compress, libpng,
  zlib and smaller ones): 147,334 of 1,390,301 (10.6 %). Debug tests: 1,801 of 177,581.
- The six areas of [`../ENGINE_CONSTANTS.md`](../ENGINE_CONSTANTS.md), cited / total bytes:
  animation data classes 82.4 %, trigger / waypoint / level-flow classes 77.6 %, effects / lights /
  tracks / cameras 76.6 %, text boxes / sprites / HUD 72.3 %, sound 65.3 %, scene-graph core and
  model resource 62.5 %.
- Largest uncited blocks of live code, in bytes: HUD and menus 123,746; AI 117,669; physics
  85,499; script database 64,517; render core 60,563; character 56,789; triggers and level flow
  50,801; core toolbox 49,631; low-level audio 47,466; player input 46,125.
- Over the 19,233-function dump alone the count is 1,531,660 of 3,268,845 bytes of live code
  (46.9 %); the merged dump adds 28,816 bytes of restored tails and 11,404 bytes of hand-written
  functions found by the gap sweep to the live base.
