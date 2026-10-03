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
so. Table: `events_table.json` (93 ids).

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
- **enums.md — asset names.** The report did not examine whether asset names
  use the folding hash. They do (`FUN_005511b8`, `FUN_0054ba59`).
- **events.md §8** describes event properties decoding under float bit
  patterns as key names. It was written before the fragment parser fixes of
  this release (name-hash fold, type records) and has not been re-checked
  against the new output.
