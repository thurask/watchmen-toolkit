# Changelog

## 1.3.0 — 2026-10-02

Two things in one release. **Animation metadata** for consumers of the
character GLBs: states, events, transitions, the pair table and partner
placement, in glTF `extras` and a JSON sidecar; joint node names, hierarchy
and keyframes are unchanged. And the results of a **full decompilation pass**
over the executable, implemented: nine research reports (`docs/re/`) closed a
number of documented unknowns — block header, mesh and texture headers, the
name hash, events, sync markers, page and play-position rules, jiggle setup —
and the toolkit follows the engine's own loaders and update functions where
they were read. **Several defaults change output**; they are listed first,
each with how to get the 1.2.0 result.

A development build of this release, never tagged, wrote animation metadata
as `watchmen-anim-meta/1`. The released format is `watchmen-anim-meta/2`.
Against a format 1 file: event times have a unit and count from the state's
start position, 644 of 1,130 state paths gain groups that build had dropped,
and 18 pair candidates (6 primary) are added. `docs/ANIMATION_META.md` has
the full list for anyone who read a format 1 file.

### Behaviour changes

- **Models: LOD 0 only.** PC models are now decoded from their header, which
  says which buffers belong to which level of detail. The extractor used to
  merge every LOD into one mesh; it now writes the full-detail LOD. 117 of the
  740 Part 2 PC models have more than one LOD; triangles written drop from
  1,368,216 to 1,285,766.
  *Old output:* `watchmen extract … --model-lod all`
  (`decode_model(…, lod="all")`) writes every LOD into one file; `--model-lod
  N` picks one, clamped to each part's last LOD.
- **Models: proxy slabs are not written.** 79 parts carry one extra rigid
  buffer — a coarse slab inside the visible mesh (a 5-triangle slab inside a
  196-triangle door). It is not render geometry; its role in the engine is not
  established. 38 models lose such a slab.
  *Old output:* there is no CLI switch. The buffers are available as
  `kind == "proxy"` from `watchmen_extract.decode_model_mesh(header, stream,
  kinds=("render", "proxy"))`.
- **Models: materials are named from the submesh record.** Each submesh
  stores an index into the model's texture list. The previous pairing searched
  for a byte pattern after the piece name and often landed on index 0. Names
  change on 192 models (`PeepingRooms_Booths`: `Door_401k_02 ×3` →
  `Door_401k_02, HoneyPot_Plywood_01, Scaffold_Metal_01`).
  *Old output:* not available for header-driven models; the old names were
  wrong. `submesh_materials` / `extract_materials` are unchanged and still
  used where the header path does not apply (console files, Part 1) and by the
  character pipeline.
- **Localized block entries are extracted, from language slot 0.** The six
  size / stream slots of a block directory record are languages, not
  platforms, and each block has extra records behind a per-language seek that
  the old parser never listed: 15 per game (Part 2: the menu logo and 14 `_uk`
  text assets). The 8,696 entries listed before are unchanged.
  *Other slots:* `--language 0..5` (`extract_block(h, s, language=N)`). Which
  language each slot number means is not established. *Old output:* there is no
  switch to leave them out. With `--limit N` the extra entry in `mainmenu`
  moves the window by one asset.
- **Jiggle: the baked result is unchanged, the cache directory is not.**
  The default jiggle model is still the one of 1.2.0 (`pinned`), bit-identical.
  `watchmen characters` now keeps jiggled palettes in
  `OUT_DIR/_bake/<skeleton>_j_<model>-<mode>-<constants hash>/` instead of
  `<skeleton>_j/`, so palettes baked with one model or one set of constants
  are never served for another. An existing `<skeleton>_j/` is not read: the
  jiggle is re-baked once (same numbers) and the old directory can be deleted.
  Existing GLBs are never rebuilt; delete them to re-export with another model.
- **`watchmen hash` and `watchmenlib.kapow_hash` use the engine's fold.** The
  engine ANDs every byte of a name with 0xDF before hashing; it does not
  upper-case. The result differs for names containing digits or punctuation
  and is the same for names made of letters and `_`.
  *Old output:* `kapow_props.kapow_hash(name.upper())` — `kapow_props.kapow_hash`
  is unchanged and hashes the bytes as given.
- **Fragment JSON.** Keys whose names contain digits resolve (`key_ee2a40a0`
  … are `m_nsupersynclocal1..8`, `key_4cadfb2b` … `m_nsupersyncremote1..8`);
  27 key names change letter case to the engine's spelling (`pivotsheet_id` →
  `pivotSheet_Id`, `loopmode` → `loopMode`); created nodes carry their type;
  2,489 properties move to the node they belong to. Of the 1,238,028
  properties the old parser emitted with a known type, all are present with
  identical name, type and value. *Old output:* not available; it was a
  misparse.
- **Sequence JSON** carries `"format": "kapow-sequence/2"` when the engine
  grammar parses the file to its last byte (all shipped files). An object can
  have both `path` and `ids`. Every object, track, key time and value of the
  old output is still there, with one exception: `handles` disappears from
  the last key of some step tracks (33 keys on Part 2 PC, 47 on Part 1 — e.g.
  `impassable` in `Door_HoneyPot_01CLOSE.sequence`, `handles: [0,0,0,0]`).
  Step keys have no handles; the old scanner had read the first 20 bytes of
  the next object as one, which is also why it lost objects.
- **`extract --model-lod` / `--language` reject bad values.** A negative
  LOD used to select no buffer and silently fall back to the legacy scan; a
  language slot outside 0..5 was accepted and ignored. Both are now usage
  errors (`decode_model(lod=-1)` / `extract_block(language=7)` raise
  `ValueError`).
- **`Toc.flag` / `Toc.pairs`** describe the entry's own stream, not the
  previous entry's.
- **`parse_model_nodes.parse_node_aux`**: `pos` is the volume's position. It
  used to hold a capsule's (diameter, height, x). `a` / `a2` are a capsule's
  diameter and height and `None` for the other volume types (they were always
  floats: two components of the misread position).
- **State-machine simulations differ** from 1.2.0 output: fewer transitions,
  different weights during crossfades. `Interpreter(done_fallback=True)`
  restores the one old rule that has no engine counterpart ("a finished page
  falls back").
- **`reg_dump.json`**: `argc` is removed from command records (it never was an
  argument count), and `classId` now holds the real class id. The class `name`
  changes on 12 records — six that had none get one, and six that carried the
  name of a neighbouring registration are corrected (`AnimationEvent` →
  `AnimationEventWM`, `Texture` → `TextureEffects`, `CollisionCapsuleNode` →
  `CharacterPhysics`, `Behavior` → `FollowPivotBehavior`, `TriggerActionBase`
  → `TriggerActionCamera`, `TriggerCharacter` → `TriggerUse`) — and `base` on
  4 more. The file is still a bare JSON list and carries no format marker;
  "kapow-reg-dump/2" (`gen_data.REG_DUMP_FORMAT`) names the layout in the
  documentation only. A reader can tell the two apart by the absence of
  `argc`; code that indexes `cmd["argc"]` needs `cmd.get("argc")`.

### Added

- **Animation metadata** (`wlib/anim_meta.py`, `watchmen animmeta EXTRACT_OUT
  OUT.json [BINDS]`, format `watchmen-anim-meta/2`; see
  `docs/ANIMATION_META.md`). Reads the game's AnimationClass fragments and
  clip root tracks into one table. Part 2 PC: 1,290 states, 2,593 transitions,
  5,099 events, 1,159 clips, 413 pair candidates, 240 primary.
  - *States* carry clips, loop, start play position, `speed`, `criteria_tree`,
    `special_handling`, `animation_type` and events. *Classes* list their
    `transitions` with sync markers. Names and ids come from the executable
    (`enums`, `event_semantics`).
  - *Events* carry `trigger`, `raw`, `time_s`, `play_time_s`, `time_unit`, and
    the `start_playpos` / `start_basis` their times were computed for. A state
    is entered at its own start position (563 of 1,290 states start past 0),
    so a `PLAY_POS` event at r fires (r − start) × duration / speed seconds
    after entry; a `TOTAL_PLAY_TIME` event stores seconds and sits at start +
    t × speed / duration; enter / leave events have no position. Events at or
    before the start carry `fires_first_pass: false` (34).
  - *Pairs from the game's own table.* A master state names its slave through
    `m_imasterof`; the partner class files it under `SlaveStates` by
    `m_istategroupid` / `m_istateid`, and criteria on the opponent's model
    type (enum variable 11) pick the child. This replaces matching halves by
    name, which cannot see that Nite Owl's throw plays `RSH_COM_ATT_throw_EN1`
    or that counters against Enemy04 reuse the `…_EN1_*` attacker clips. Pairs
    also carry `weapons` and group criteria.
  - *Partner placement — the engine's rule*, read from the executable
    (`CharacterRoot.StateActive` 0x6b9035–0x6b94e9): the anchor is the
    master's `interact` marker, its frame turned 180° about +Y (a literal −π/2
    half-angle constant), and every actor moves by its own `GamePivot` track
    relative to that track's first key. When the master's interact is not
    authored the engine uses the offset (0.11, 0.04, 1.12). Each pair reports
    where the partner clip's *own* GamePivot start falls, an optional
    geometric contact check, and a `confidence` from those (198 verified, 32
    plausible, 10 unverified of 240).
  - *Pair timeline* on the master's clock (the partner's play position is
    copied from the master every frame), starting at the master's start
    position (`timeline.start_playpos`, past 0 on 205 of 240 primary pairs).
    The master is not an absolute animation and is never snapped; the partner
    holds its entry pose until its `ABSOLUTE_GOTO_TARGET_POS` event, blends
    onto the anchor over its ease-in, and is released at its first
    `LEAVE_ABSOLUTE_MODE`. Every master state is entered only through group
    transitions without an override or sync start, every partner state only by
    `goto_slave_mode` (`master.entry_alternatives` is empty throughout).
  - `anim_meta` calls the rule functions of `anim_state_machine`; no engine
    rule is implemented twice.
- **GLB `extras`.** `asset.extras` carries the coordinate conventions
  (including that the export is a mirror image); the skin carries the real
  bone names, parent indices, the `GamePivot` / `interact` / `Bip` joint
  indices and the attach joints; each joint node carries its `bone` and
  `parent`; each animation carries its clip record with events timed against
  the animation as written. `watchmen characters` builds the table once, saves
  it as `OUT_DIR/anim_meta.json`, and embeds it.
- **Header-driven model decode** (`watchmen_extract`): `parse_model_header`,
  `model_stream_layout`, `select_model_buffers`, `decode_model_mesh`,
  `decode_vertex_attributes`, `gltf_tangents`, `VERTEX_STRIDES`,
  `VERTEX_FORMATS`. Every buffer offset is computed from the header; nothing
  is searched. Used only when the header parses and the layout consumes the
  stream to the last byte (735 of 735 Part 2 PC models with a stream);
  otherwise the previous scan runs unchanged (console files, Part 1).
- **Script asset classes.** `ModelEffects(ModelRes)` and
  `TextureEffects(Texture)` — the two asset-type hashes that had no name — are
  read by their base class's loader. Part 2 PC: +307 model jobs (674 → 981),
  +53 textures. `ASSET_TYPE_NAMES`, `asset_type_name`, `asset_base_class`.
- **Block header.** `parse_block_header()` returns the 400-byte header as
  named fields; `fingerprint_decrypt()` decodes the fingerprint string;
  `Toc` gained `type_hash`, `type_name`, `sizes`, `has_stream`, `streams`,
  `localized`, `language` (the old attribute names `flag`, `pairs`,
  `variants`, `unknown` still work, for reading and writing). A header
  shorter than 400 bytes raises `ValueError("not a block header …")`.
- **Exact Texture header**: `parse_texture_frames`; `plan_texture_layers`
  returns the exact plan (layers carry `slot` and `chain`) when it tiles the
  stream, else the previous planner runs.
- **Sequences**: `decode_sequence.parse_exact`, `evaluate(track, t)` (step /
  linear / cubic Hermite) and `euler_deg_to_quat`. Tracks carry
  `interpolation`, `value_type`, `spline`; keys carry `in` / `out` handles and,
  on quaternion tracks, `euler_deg` / `quat`. The linear branch of `evaluate`
  assumes a component-wise lerp; the engine's per-type interpolator was not
  read.
- **Node collision volumes.** `skeleton_records.parse_node_tail` /
  `parse_volume_lists` read the per-node layout (box, sphere, capsule, convex
  and concave mesh; two lists per node plus an emitter-surface list).
  `skeleton_records.parse()` records carry `volumes`; skeleton JSON bones carry
  an optional `collision_volumes`. 934 volumes in 23 Part 2 PC models; all
  2,069 mesh-free node regions tile. Rest poses, hierarchies, names and binds
  are bit-identical.
- **GLB vertex attributes — available in the API, off in the CLI.**
  `rig_glb.build_rigged_glb(…, normals=, tangents=, colors=)` can write
  NORMAL, TANGENT and COLOR_0 (`rig_glb.mesh_vertex_attributes` supplies them)
  and flips the winding of primitives that carry normals. Its positional `N`
  argument is ignored exactly as in 1.2.0, so existing callers get the same
  file. `watchmen extract --glb` does not pass the
  data, so its GLBs carry none of the three and keep the file's winding (with
  the caller unchanged, the new writer's output is byte-identical to the old
  writer's on all 130 GLBs of Part 2 PC). The reasons: what the engine
  does with the vertex colour is not established, and as a glTF `COLOR_0` it
  darkens the 31 models that have authored colours by about 17 %; the stored
  tangents are not perpendicular to the normals (|n·t| above 0.1 on 29 % of
  vertices); and writing normals means flipping the winding of 279 of 283
  primitives, because the game's triangles are clockwise against their
  normals.
- **Name hash API**: `kapow_props.name_fold`, `name_hash`.
- **`wlib/engine_enums.py`** and `engine_schema.commands_by_hash()`.
- **Interpreter**: `Interpreter(seed=…, rng=…)` and CLI `--seed` for the
  per-layer blend-node choice; `Interpreter.fired` (events); `Env.speed`,
  `Env.force_linear`, `Env.no_override_layer`, `Env.force_update`;
  `Page.slot_playpos`; the shared rule functions `interval_met`, `event_due`,
  `event_prelatched`, `criteria_of`, `transitions_of`, `members`,
  `transition_criteria`, `marker_pairs`, `map_markers`, `start_playpos`,
  `slot_speed`, `state_speed`, `event_timing`, `resolve_ref`.
- **Jiggle: the `pivot` model, opt-in.** `watchmen characters … --jiggle-model
  pivot` (also on `char`, where the option turns the jiggle bake on),
  `apply_jiggle(…, model="pivot")`, `characters_export.export(…,
  jiggle_model=)`, `variant_glb.build(…, jiggle_model=)`. The default stays
  `pinned` (`jiggle_d6.DEFAULT_MODEL`), because the pivot model's swing
  constants are fitted to captures at an estimated frame rate.
  In the pivot model the simulated body swings about the *parent* bone origin
  on the parent→bone lever; its pose replaces the bone's local position *and*
  rotation; gravity is not applied (the game cancels it every frame); twist
  about the parent X axis is locked; the clamp is the bone-origin displacement
  in metres (0.08 m breasts, 0.10 m belly); the body trails the parent by one
  frame. Against the in-game captures (BreastL / BreastR / JiggleBelly),
  pinned → pivot: rotation error 5.90° / 5.64° / 4.09° → 4.29° / 4.13° / 1.96°
  rms; bone-origin error 16.4 / 15.8 / 5.6 mm → 8.0 / 7.7 / 3.5 mm;
  least-squares amplitude factor 0.34 / 0.35 / 0.16 → 0.98 / 0.96 / 0.87;
  correlation 0.29 / 0.29 / 0.26 → 0.59 / 0.59 / 0.63. The plain ratio of mean
  deviation magnitudes moves the other way, 1.05 / 1.02 / 0.52 → 1.57 / 1.47 /
  1.58; why is not established (the capture input has no root motion). On
  baked clips the pivot model has no static sag and smaller swing angles (EN4
  `run_cycle` breasts 4.62° / 4.15° → 3.04° / 2.85° mean; `idle_stand` 1.51° /
  1.65° → 0.01°).
  *What is read from the exe:* the geometry above, body size and mass, angular
  damping, the 1/60 s step. *What is capture-measured:* the swing stiffness
  and damping (`mode='capture'`: breast K 570 s⁻², D 37.5 s⁻¹; belly 308,
  19.2), which depend on an estimated capture rate of about 55 fps, and the
  one-frame latency (consistent with the update order in the exe, measured on
  the captures). Hair has no capture and uses the file constants.
  Also new: `swing_constants`, `resolve_model`, `cache_signature`,
  `apply_jiggle_legacy`, `apply_jiggle(…, latency=)`,
  `jiggle_pass.apply_jiggle(…, model=)`.
- **`tools/ghidra/`**: three Ghidra scripts and the handler table used to
  produce the decompilation the reports were read from (see its README).

### Fixed

- **Name hash.** `FUN_00423ce8` folds each byte with `& 0xDF`: digits and
  punctuation fold too (`'0'..'9'` → 0x10..0x19, `(` → 0x08). Every name with a
  digit was filed under a hash the game never uses.
- **Fragment parser.** `0xFFFFFFFF` introduces a type record (`Class(Native)`
  or a bare native class) wherever it occurs, never properties; the parser
  accepted only the opening block and read later records as property keys. A
  17-byte header-only file is an empty fragment, not a failure. Part 2 corpus:
  906 / 906 files parse (was 897); unknown-key occurrences 580,286 → 22;
  node entries 108,348 → 118,408; 483,682 more properties typed.
- **Fragment loader** (`anim_state_machine.load_tree`). The top-level nodes of
  a nested fragment were dropped and their children re-parented (126 states
  and 82 groups on Part 2 PC), and a fragment was spliced only once; node
  classes came from the preamble table only (44 nodes had none); references
  were resolved by id across instances. All three fixed; a reference to the
  fragment's own slot is the group that instances it.
- **Models.** 42 models had 1–4 submeshes decoded from a wrong stream offset
  (`TwilightMansion_Bath_Stairs`: a 28-vertex submesh read at 73039, it is at
  57562); 53 gain submeshes the scan never found (`lock_casing_start` 918 →
  7,274 triangles); 12 vegetation submeshes on two palm models were dropped by
  a field test. No model lost geometry that was right.
- **Model node table** (`parse_model_nodes.parse`): header-driven on PC. 29
  mesh-only props no longer raise `ValueError('no node names')`; three
  bridge / sky models regain nodes the scan dropped for being more than 100
  units from the origin. All skeleton and character models are identical.
- **Textures.** 4-byte row padding of linear formats; 10 two- or three-layer
  materials were read as flipbooks (`baseballbat`, `CityBackdrop_01/02/03` …);
  the header of a `TextureEffects` texture did not parse (28 on Part 2 PC).
  Run through `carve_texture`, 898 of 936 Part 2 PC textures are
  byte-identical and those 38 change.
- **Sequences.** The scanner missed objects — in the 15 door sequences the
  door's own `localorient` track. Part 2 PC: 351 → 366 objects, 1,972 → 2,002
  keys; totals now agree across PC, X360 and PS3.
- **Interpreter.** Sync markers were read under the pre-fix key names;
  interval tests (`LESS_THAN` is `x < max`, intervals are half-open); events
  fire when the position is reached (`<=`); a transition to a state also
  carries that state's criteria; "entry only" criteria are skipped only inside
  their owner; fallback transitions only in the fallback pass.
- **`gendata regdump`** missed 114 property registrations, 5 command hashes
  and 88 short command names; `classId` was wrong for most classes.
- `anim_state_machine.load_tree` raised `IndexError` on a sub-fragment with no
  instances (several `SoundEvents` fragments parse that way), which lost the
  whole `AnimationClassEnemyBig` tree. Empty fragments are skipped.
- `load_tree` read the `.fragment.json` on disk, so JSON written by an older
  extractor — with `key_xxxxxxxx` names where the current key table has `m_…`
  — silently produced a tree with no usable properties. It now parses the
  binary `.fragment` beside it and falls back to the JSON only when the binary
  is absent. Sub-fragment paths are resolved on Windows separators too.

### Changed

- **State-machine interpreter v2.** Page setup follows `SetupNewPage`
  (same-state and re-entry handling, walk-cycle phase carry-over, ease-in rule,
  force-stay timer, no page cap); play position uses the weighted rate with
  slot speed and the 6.6 /s clamp; the blend curve applies only with "Soft
  Blend To"; one blend node per layer list; overlay fade-out; events. The
  slave lock of a paired animation is not modelled (the interpreter runs one
  character).
- **`parse_node_aux`** is a wrapper over `skeleton_records.parse_node_tail`
  and reads every volume type.
- **`bake_v4.py` is unchanged.** The executable adds a pose term to the
  constant position of type 1 / 3 clip tracks; the shipped constants are
  absolute values, so the baker keeps "non-zero constant = absolute". Open
  question, recorded in `docs/ENGINE_CONSTANTS.md`.

### Data tables

- `kapow_fragment_keys.pkl` and `prop_hash_dict.pkl` re-keyed under the engine
  hash: 480 keytable, 16,293 nameable and 8,343 dictionary entries moved. No
  entry was kept under its old hash; none of the old hashes is attested.
  862 built-in node properties typed from the engine's typed registration
  wrappers (`promoted` 3 → 865); new 8-byte `biginteger` value type.
- `reg_dump.json` format 2 (`gendata regdump`): 441 classes, 5,090 property
  and 6,630 command registrations. Properties carry `name`, `flags`,
  `typeidx`; commands carry `slot` (command 3,939 / state 841 / method 1,850),
  `kind`, `arg3`, `typeidx`, `signature`; classes carry `classId`,
  `native_base`, `parent`. Still a bare list of classes.
- `command_signatures.json` (new): the 830 hashed strings of commands that
  take parameters, `name(type,…)`. Research output — the strings are not in
  the executable; each is verified by re-hashing.
- `engine_enums.json` (new): 30 enum families as the executable registers
  them, the family each criteria enum variable takes its values from, the
  interval types, and what each of the 93 animation events does.

### Documentation

- `docs/re/`: the nine research reports and their tables, shipped verbatim,
  with a README that says what each establishes and lists the corrections
  found while implementing.
- `docs/ANIMATION_META.md` (new).
- `docs/ENGINE_CONSTANTS.md`: a new section for this pass; earlier statements
  now known to be wrong carry an inline `[corrected 2026-10-02: …]` note
  instead of being rewritten.
- `docs/KAPOW_NAZ_FORMAT.md`, `FORMATS_MISC.md`, `FRAGMENT_FORMAT.md`,
  `WATCHMEN_EXTRACTION_MASTER.md` corrected and marked the same way: the block
  header is 400 bytes and the stream pair belongs to its own record (there is
  no "+1 shift"); the six slots are languages; the u32 after an asset's type
  name is the property-bag length; the texture descriptor is 29 bytes plus a
  presence byte per slot; vertex formats; the `.sequence` grammar; the
  "stride-16 int16 baked mesh" claim is withdrawn; the "EmbeddedJointNode
  joint records" are collision volumes.
- `tools/ghidra/README.md`.

### Tests

- Seven new files, 184 tests, synthetic fixtures only: `test_anim_meta.py`
  (20), `test_names.py` (28),
  `test_anim_meta_v2.py` (18), `test_interp_v2.py` (25), `test_formats_v2.py`
  (23), `test_phys_v2.py` (27), `test_followup.py` (43). Suite: 406 tests,
  independent of test order and hash seed, pyflakes-clean. Event times and the
  pair timeline for states that start past 0 are checked against an
  `Interpreter` run of the same state.
- Existing tests edited where a change invalidated what they pinned:
  `test_v120_regressions.py` (the node-aux fixture is built in the engine
  layout), two docstrings in `test_kapow_hash.py`.
- Real-data validation, read-only, numbers as quoted above: Part 2 PC (740
  models, 936 textures, 194 sequences, 906 fragments, 45 animation fragments),
  plus X360 / PS3 Part 2 and PC Part 1 for the block directory, models and
  sequences. `watchmen characters` was run on Part 2 PC with the new metadata (26
  GLBs). Not run on real data: a full extraction, console files through
  `parse_node_aux`.

## 1.2.0 — 2026-08-17

A second correctness pass. The dominant theme: fixes the bulk `characters`
path (`char_lib`) collected in July that the single-model paths never
received. **Output-affecting for console extraction, `watchmen char`, bulk
walk/run timing, and `export_female_anims`** — details below.

### Output-affecting

- **Console rigged GLBs from the extractor.** `decode_model` auto-detected the
  byte order but didn't pass it to `decode_skin`, so the PC `stride >= 56`
  gate rejected every console (stride-44) skinned submesh and `--glb` on an
  X360/PS3 naz silently produced no skinned GLB at all. The `watchmenlib`
  facade wrapper dropped the argument too. Both now thread the order through.
- **`watchmen char` / `wl.build_variant_glb` skinning.** `variant_glb.
  load_parts` was missing the 2026-07-13 `BipNN`-prefix-insensitive bone-name
  fallback `char_lib` has, so Thug/Heavies-style name mismatches silently
  dropped mid-list bones and shifted the rotate-by-one palette (mis-skinned
  arms/head). Also ported from `char_lib`: byte-order autodetection (the path
  was little-endian-only), the `_ib_ok` clean-index-buffer guard, and
  engine-exact `submesh_materials` pairing (positional pairing textures the
  wrong submeshes when one material covers several). The extractor's OBJ/MTL
  path got the same `submesh_materials` fix.
- **Bulk locomotion timing.** `watchmen characters` never applied the
  capture-verified `SPEED_MULT` runtime sync that `watchmen char` applies, so
  the two writers disagreed on walk/run clips. The bulk path now applies it.
- **`export_female_anims`** still carried the pre-1.1.0 Z-up→Y-up conversion —
  and applied it twice (baked into POSITION *and* on the Armature root), so
  its output was rotated. No conversion is applied now; output matches the
  other writers. Also: removed an orphaned duplicate IBM accessor, replaced a
  bare `except`, and a naz without the female skeleton now fails with a clear
  message instead of a `TypeError`.
- **Clip-bank lookups in `variant_glb.build()`** only matched keys named
  `<clip>.animation`, while `bake_v4` accepts bare names too; a bare-keyed
  bank silently missed every clip and fell back to 30 fps. Lookups are now
  tolerant the same way `bake_v4`'s are.

### Correctness

- `bake_v4`: the frame count came from quaternion tracks only; a clip whose
  longest track is positional had its position keys silently down-sampled.
- `jiggle_d6`/`jiggle_pass`: the sim→clip resample clamped the index but not
  the weight, so clips faster than the integration grid extrapolated past the
  last sim sample (and could overshoot the engine distance clamp). Clamped.
- `variant_glb`: face-first materials silently lost their specular layer (the
  face material block was a copy of the body block minus the
  `KHR_materials_specular` handling); one `try/except` around the face-synth
  import also swallowed per-pose errors and disabled all auto-pairing on the
  first bad pose — it now guards only the import and reports failing poses.
- `skeleton_records` and `parse_model_nodes.parse_node_aux` were
  little-endian-only; both are byte-order aware now (facade callers get
  console support with no signature change).
- X360 texture carve: the tile buffer sized width as `max(w, 32)` where every
  consumer aligns width up to 32; non-power-of-two widths over 32 blocks got
  their untiled tail zero-filled (blank PNG bands).
- `mediastream` vs `MediaStream`: the console-audio metadata pass compared the
  asset class against two different spellings, so at most one branch could
  ever match; both comparisons are case-insensitive now.
- Legacy-carved textures (`diffuse.png`, …) used names the texture index and
  MTL linker can't see; they now use the standard
  `<i>_<label>_<WxH>_<FMT>.png` scheme and link into OBJ materials.
- `kapow_props.parse` bounds-checks payload reads (truncated propbags return
  partial results with a `warn` entry instead of raising `struct.error`), and
  the dead `wc + 1 != k` validation actually warns now.

### CLI and library surface

- `hash` and `gendata` dispatch before the facade import: `watchmen hash` no
  longer imports numpy/Pillow/the data tables, and `watchmen gendata
  keys-import` — the documented recovery when `kapow_fragment_keys.pkl` is
  missing — no longer dies on the very import error it exists to fix.
- `kapow_fragment` raises `ImportError` instead of `SystemExit` when its key
  table is missing: `SystemExit` derives from `BaseException`, so it escaped
  every `except Exception` guard (pytest collection died with zero tests run;
  `import watchmenlib` could kill a host process). The CLI catches it (and
  `struct.error`) and prints an `error:` line; missing-table exit code is now
  2, not 1.
- `--limit N` on the extractor actually stops after N block assets, as its
  help always claimed.
- Stale docs/comments swept: the extractor's `OUT/streams/` claim, a dead
  `_RIG["skeletons"]` store and its misleading comment, a dead `stats`
  counter, `rig_glb`'s claim that its (legacy, caller-less) animation path
  decodes translations, `extract_skeletons`' description of the removed
  biped-name parent fallback, and the removed `sys.argv` snapshot note in
  `watchmen.py`.
- The key-count-cap regression test now actually fails when the cap is
  removed (it fed keys the dimension check rejected anyway, so it pinned
  nothing).
- Added `tests/test_v120_regressions.py` (34 tests, 2026-09-01): one or more
  per fix above, each verified to fail on 1.1.0 (28 of the 34 fail there; the
  rest are reference fixtures). No game files needed. Suite: 222 tests.
- Verified on real assets (2026-09-01): the X360 Rorschach model now yields a
  rigged GLB whose joint indices and weights are identical to the PC export and
  whose positions agree to 0.5 mm (half-float quantisation); on 1.1.0 the same
  input produced no GLB. The OBJ material list for that model now shows
  `RorschachTrenchcoat` on all three trenchcoat submeshes instead of the
  positional shift (`submesh_9`, `submesh_10` fallbacks).

## 1.1.0 — 2026-07-24

A correctness pass over the whole toolkit. **Three changes alter output**; the
rest are robustness, security, portability and packaging. Re-export anything you
generated with 1.0.0.

### Output-affecting

- **Axis convention.** The Kapow engine is Y-up, the same as glTF, so no axis
  conversion is applied any more. Previously both GLB writers rotated positions
  by a Z-up→Y-up matrix. In `variant_glb` an exact inverse was folded into the
  joint world matrices, so the animated result cancelled out correctly but the
  raw `POSITION` data — and therefore the bind pose — was 90° about X. In
  `rig_glb` nothing cancelled it, so every model it wrote (static props, heads,
  and rigged bodies) came out on its back. Animated character output is
  numerically unchanged (verified 1e-7 against the previous writer); `POSITION`
  and everything `rig_glb` produces is now upright.

  Evidence: skinned frame-0 bbox of a shipped character GLB is 1.75 m tall along
  Y with feet down, while its `POSITION` alone measured 1.80 m along Z. The
  original Z-up reading came from `decode_skeleton_model.py` (see below), which
  was superseded for an off-by-one bug and also reported a 1.4 m character.

- **Character GLB rest pose.** Joint nodes were emitted with identity TRS while
  the inverse bind matrices were real, so with no animation playing the skinning
  matrix was the IBM alone and the mesh rendered in bind-*local* space —
  measured 0.72 m mean vertex displacement and a mesh collapsed to about a fifth
  of its animated size. Joint nodes now carry the bind pose. Anything that shows
  the scene before you pick an action (Blender's rest pose, the default glTF
  viewer state, thumbnailers) is now correct.

- **Clip timing in `variant_glb.build()`** (i.e. `watchmen char` and
  `wl.build_variant_glb`). It read the clip header's field 0 as the duration;
  field 0 is the key RATE and field 1 is the duration. Since
  `keyRate == (keyCount-1)/duration`, the computed fps came out as
  approximately the duration in seconds — roughly 3× too slow on a typical
  clip. `bake_v4` had been fixed for this in 2026-07-09 and carries a comment
  saying so 20 lines above the offending call; `build()` was never updated. The
  bulk paths (`watchmen characters`, `charlibs`) computed fps correctly via
  `bake_v4.fps_for` and are unaffected.

### Correctness

- `OUT/skeletons/*.json` was built by `decode_skeleton_model.decode()`, which
  that module's own docstring marked SUPERSEDED for an off-by-one: the 28-byte
  `[pos][quat]` transform *precedes* the name in a node record, so every bone
  was published carrying its successor's rest transform, the last bone of every
  skeleton was dropped, `bone_count` was short by one, and parents were guessed
  from biped names instead of read from the record. `extract_skeletons` is now
  built on `parse_model_nodes.parse()`, and `decode_skeleton_model.py` is
  **removed**.
- Console (X360/PS3) skeletons: `extract_skeletons` read the per-node parent
  field little-endian only, which threw `struct.error` on every big-endian
  header — swallowed by two `except Exception: pass` handlers, so console runs
  logged "0 base skeletons decoded" and every rigged console GLB got joints
  named `bone_0`, `bone_1`, … `_model_is_body` had the same problem but returned
  empty instead of raising, so its safety net never fired and every skinned
  console character was exported *static*, silently. Both now use the same
  byte-order autodetection as the rest of the codebase.
- `kapow_json`: the duplicate-resource-reference filter was `pass` where
  `continue` was meant, so every fragment JSON emitted each resource path twice,
  usually under two different key names.
- `parse_model_nodes`: bounds-check every record read, and fail loudly when the
  number of nodes parsed disagrees with the header's own count (a silently
  dropped node shifted every later parent index and corrupted the hierarchy).
- `jiggle_d6`: solver softening used a hardcoded 120 Hz instead of the
  integration rate read from the fragment. No change at the shipped 60 Hz;
  correct, and stable, at any other rate.
- glTF conformance: empty `animations`/`skins`/`images`/`textures`/`materials`
  arrays are no longer emitted (glTF 2.0 sets `minItems: 1`; the Khronos
  validator reports them as errors), and animation input accessors carry their
  real `min`/`max` instead of a hardcoded `0.0`.

### Security / robustness

- `safe()` neutralizes Windows drive-relative entry names (`C:/…`, `D:evil.txt`,
  which `pathlib` treats as a new anchor and which therefore escaped the output
  directory), maps an empty entry name to `_unnamed` instead of returning the
  output directory itself, and asserts containment.
- Removed a `pickle.load` fallback to `/tmp/prop_hash_dict.pkl` — a
  world-writable path, and `pickle.load` executes code. A missing or corrupt
  table now warns on stderr instead of silently degrading every property key to
  a hex hash behind a bare `except:`.
- `decode_sequence` bounds-checks truncated buffers and has a forward-progress
  guard (its resync window scans backwards, so a 2-cycle was representable).
- `naz_entries` on a file shorter than the EOCD record says "not a NAZ archive"
  instead of raising `OSError(EINVAL)` from a negative seek.
- A stale `<clip>.npz.tmp.npz` from a killed chunked bake matched the resume
  glob and was loaded as a real animation — permanently, since nothing cleaned
  it up. Temps are now skipped and swept.

### Determinism and portability

- `build_texture_index` and the loose-tree walk no longer depend on filesystem
  enumeration order, so which texture directory wins for a colliding basename is
  stable across machines.
- All text output is written UTF-8 with LF line endings, so output is
  byte-identical across platforms.

### Library surface

- `import watchmenlib` no longer rewrites the host program's `sys.argv`, no
  longer raises the process recursion limit, and no longer resolves paths into
  `site-packages`. `bake_v4.bake()` takes `bind=` / `conj=` / `bank=` directly;
  the six `sys.argv = [...]` + `importlib.reload()` sites are gone.
- The dead `wl.BINDS` / `variant_glb.BINDS` tables (every entry pointed at a
  developer-machine directory that never shipped) are replaced by
  `wl.ensure_binds(naz, outdir)` and `variant_glb.binds_from_dir(dir)`.
  `ensure_binds` now requires an explicit `outdir` instead of defaulting to a
  path inside `site-packages` — and creating it there.
- `wlib/__init__` appends to `sys.path` instead of inserting at position 0, so
  the flat module names can no longer shadow the stdlib.

### CLI

- `watchmen --version`.
- Bad paths and wrong file types produce `error: …` lines and non-zero exit
  codes instead of tracebacks; `watchmen fragment` on an unrecognized file no
  longer writes `null` and then crashes.
- `watchmen gendata check` explains what it needs instead of tracebacking when
  there is no game install; missing positional arguments are reported.
- `watchmen --help`, `--version` and `hash` no longer import numpy, Pillow and
  three pickled data tables, and no longer fail when a data table is missing.
- `watchmen char` takes an optional `BINDDIR` and `BAKEDIR`.

### Docs and release hygiene

- Removed the author's private working-tree paths (`D:\…`, `claude/work_*/…`)
  from 12 source files and the docs, and repointed 21 references to documents
  that never shipped at the ones that do.
- Neutral phrasing around DRM: the docs no longer instruct readers to obtain a
  specific de-DRM'd executable. `gendata regdump` — the only path that needs an
  executable with an unencrypted `.text` — says so plainly and states that this
  toolkit neither provides such a binary nor helps produce one.
- `gendata regdump` sanity-checks the recovered class count, because the
  registration-function addresses it uses were reversed from one specific build.
- Added `tests/` (188 tests, no game files needed) and a `CHANGELOG`.
