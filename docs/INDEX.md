# Documentation index

Reading order for someone new to the codebase. These are the living technical
records from the reverse-engineering effort; later sections supersede earlier
ones within each file (each keeps a dated changelog).

## 1. [KAPOW_NAZ_FORMAT.md](KAPOW_NAZ_FORMAT.md) — the archive
The `.naz` container: layout, zlib framing, the naz→zip mapping, and the
`.block_h_z` / `.block_s_z` header+stream pair format that everything else
sits inside: the 400-byte block header, the directory record, the asset
header, the Texture descriptor and the ModelRes header and stream (corrected
2026-10-02 from the engine's loaders). Since 2026-10-05: what the engine
does with an archive (§1.1), the block header's version signature at 32,
compression by asset type, loading rules, the trailing blob and the memory
budgets (§2.4). Since 2026-10-03 also the channel
order of PC `ATI2` normal maps (Y block first), the texture's material
switches (`sheet.json`, §4.6) and what the vertex colour, tangent and
bitangent fields are (§6b). Since 2026-10-04 texture sheets in full (§4.7:
uniqueID, layer overrides, per-sheet switches, the blend enum) and the
fragment property that selects them (`textureSheetsDescription`); how the
GLB material is built from a sheet (§4.6), the occluder buffers and LOD
distances and the model's articulated-body (ragdoll) section (§6b), and the
multi-track layout of music streams (§8). Also: stream sets and Part 1's stream-only blocks (§2.4), the byte
order a header states and the older property-record layout of the standalone
Part 1 (§3), the console texture header, Xbox 360 format 8 and the cube map
storage of the three platforms (§4.2).

## 2. [WATCHMEN_EXTRACTION_MASTER.md](WATCHMEN_EXTRACTION_MASTER.md) — the master record
The central document. Block TOC format, asset property-bag headers, model
vertex-buffer layouts, texture formats and the shader-driven material
pipeline, audio containers, plus:

- **§13** — Part 1 support (loose-file trees, WM06 16-byte property records)
- **§14** — Console support (X360/PS3): big-endian payloads, XMA2/MP3 audio
  segment chains, PS3 texture segments, X360 tiling/untiling, packed mip tails
- **§15** — Part 1 console extraction + 3-way PC/PS3/X360 audit (scorecard,
  accepted residuals, ops patterns for long jobs)

## 3. [FRAGMENT_FORMAT.md](FRAGMENT_FORMAT.md) — level/character data
The `.fragment` property-bag: schema table + instance stream, transform keys,
how spawns/cameras/character composition are encoded. The lossless parser is
`wlib/kapow_fragment.py`; the name hash (CRC32 0x04C11DB7 over the name's
bytes `& 0xDF` — not upper-case) is `name_hash` in `wlib/kapow_props.py`.
Since 2026-10-04 also the file header (version, singleton, name,
reapplyable), `.scene` files, and entity references as the engine resolves
them (singleton index, host levels, scope search). Since 2026-10-05 the
sections of `.fragment.json` (built from the exact parse), the refused type
guesses and the seven Part 1 keys (all seven spellings are entries of the
Part 1 `database.bin`; the `inferred_names` marker is unused but kept).

## 4. [FORMATS_MISC.md](FORMATS_MISC.md) — the small formats
`.font`, `.scene`, `.particle`, `.terrain`, `.terraincoloringasset`,
`.grass`, `.pb`, `.sequence`, `.detailmesh` — all decoded, all with JSON
emitters in `wlib/kapow_json.py` (`export` also writes the font atlas, the
terrain maps and the terrain GLB; `undecoded` reads the markers of a JSON
that is not a complete decode).
Also the collision volumes in a `.model` node tail, the `sound` asset header
(PC, and since 2026-10-05 Xbox 360 and PS3) and the `.pb` pivot book. Since 2026-10-05: the `.sequence` loop mode,
entity-path depth (`hosts_up`) and target kinds; the particle emission
surfaces of model nodes (`MeshParticleData`). `.particle` has its own document since 2026-10-04:

## 4a. [PARTICLE_FORMAT.md](PARTICLE_FORMAT.md) — particle systems
The engine's `.particle` grammar (format `kapow-particle/2`): system, types
and their affector / spawner / initializer lists, all 28 classes with every
property (hash, type, constructor default, meaning), enums, gradients, what
the simulation and the renderer do with the parameters, how the
extractor's `.particle.json` changed, and the `watchmen particlemeta`
command with its `index.json` (`watchmen-particle-meta/1`).

## 5. [ENGINE_CONSTANTS.md](ENGINE_CONSTANTS.md) — the animation engine
The deep record of the animation system, recovered from the executable and
validated against GPU captures: skeleton rest poses and the file-only bind
construction (Rb = conjugated FK), clip decode (quat/10000, POSITION/1000),
frame-rate scale (FULL/HALF/THIRD), the state-machine interpreter and overlay
pages (two-stack model), jiggle dynamics (PhysX NxD6Joint soft limits), face
synthesis, weapon attachment, and the per-session changelogs that got there.
It is an append-only notebook: the last sections are current —
"2026-10-02 (later) — full decompilation pass", "2026-10-03 — PhysX
soft-limit jiggle; vertex colour, tangent frame and normal-map channels" and
"2026-10-04 — the face system; texture paths and texture sheets", followed by
"2026-10-04 — outfits, weapons, sheet lookup and blend states" (which outfit
a character gets, 0x66ca15; which weapon, 0x694378; how a mesh finds its
sheet and its layers; the render state of each blend type),
"2026-10-04 — renderer, materials, ragdoll, audio" (the frame's passes, the
lighting equation the materials are derived from, how the ragdoll is
instantiated and run, the path from a game event to the speaker) and
"2026-10-04 (feature round) — combat, effects and camera, levels, text,
particles, navigation" (the handlers and constants behind the six new
exports, and what stays open in each) —
and earlier statements they overturn carry an inline `[corrected 2026-10-02:
…]`, `[corrected 2026-10-03: …]` or `[corrected 2026-10-04: …]` note. The
2026-10-04 section has how the head is attached and what drives its animation
class, how a model's textures are resolved, and what a texture sheet is. The 2026-10-03 section has what
PhysX does with the jiggle joint per step, what the shaders do with the
vertex colour and the tangent frame, and the evidence for the `ATI2` channel
order.

## 6. [ANIMATION_META.md](ANIMATION_META.md) — states, events, transitions, pairs
Format 2 of the `anim_meta.json` sidecar and the `extras` embedded in the
character GLBs: every state with its criteria, speed and events (trigger kind
and real time), transitions with sync markers, which clip plays against which
(from the game's `Master of` table), where the partner stands and when it is
anchored and released, and the bone names and parents. Has a section on what
changed since format 1, "Outfits and weapons in the GLB" (the `parts` record, `weapon_use`), and "The face block": the face classes, which face
state the game shows during which body state or pair, and how the character
GLBs carry it.

**Coordinate frame.** Since 1.4.0 GLBs, OBJs and the data given in their frame
are true-handed by default (x = −engine x; marker `coordinate_frame:
"right-handed-true"`); `--frame mirrored` writes the engine's left-handed
numbers as 1.3.0 did, and a file without the marker is in that frame. The
rules are in README.md "Coordinate frame" and ANIMATION_META.md "Coordinate
conventions"; LEVEL_META.md, NAV_DATA.md, RAGDOLL_RIG.md and FX_META.md say
which of their values follow the GLBs and which stay in engine coordinates;
the code is `wlib/frame.py`.

## 6a. [RAGDOLL_RIG.md](RAGDOLL_RIG.md) — the exported ragdoll
What `<Variant>.ragdoll.json` and the `ragdoll` helper nodes of a character
GLB contain: bodies, shapes with their three size records, D6 joints and
limits, units and frames, the Blender axis mapping and settings that work
for a rigid-body setup, what the game does with the rig at run time.

## 6b. [SOUND_META.md](SOUND_META.md) — what the game plays
`sound_meta.json`: sound definitions and their variation rules, the sound,
speech and footstep events of every animation state with times and
durations, footsteps by character type and surface, attack and hit sounds,
speak groups and voices, music setups.

## 6c. [FX_META.md](FX_META.md) — effects, camera cuts, rumble
Event payloads, the per-state `fx` section, pair camera cuts (the finisher
and counter cameras are procedural, there are no camera tracks), the effect
database and the damage-effect rule, weapons, character attachments, the cut
placement rule and the camera rig; what of it a character GLB carries.

## 6d. [COMBAT_META.md](COMBAT_META.md) — combat rules as data
The `combat` block of `anim_meta.json` (`combat_format`): per attack state
the attack class, damage, timings, reach, damage pose and defender options;
per pair the trigger rule and damage; the combo databases, CharacterDefs, AI
reaction tables with the effective damage modifier, and the fixed rules (hit
damage and its receiving side, ragdoll contact damage for throws, area
attacks, sweep stepping, attack permission) with the script handlers and exe
constants they were read from.

## 6e. [LEVEL_META.md](LEVEL_META.md) — levels and save files
`watchmen levelmeta`: one `<level>.level.json` per level with the fragment
tree and world transforms, character / model / volume placements with their
glTF node transforms, the condition / action graph, checkpoints, camera
tours, movies (with their subtitle tables), path objects and their link by
id to the navigation data, what is fixed about each placement's model and
weapon, AI start state, combat presets, cube maps, lights, waypoints,
culling groups and stream blocks, and where each
terrain is placed (`files.terrain`).
`watchmen savemeta`: `.kpw` save files.

## 6f. [TEXT_ASSETS.md](TEXT_ASSETS.md) — text and subtitles
The `text/` folder of an extract (every text table in five languages, raw,
JSON and CSV), the `textRes` format, the language slots and how each
platform picks one, how a playing sound finds its subtitle (the wave's file
name) and when the line is shown, the cutscene subtitle tables of each
movie, and the `textmeta` table that joins strings, waves, speak lines and
movies.

## 6g. [NAV_DATA.md](NAV_DATA.md) — navigation mesh and graph
The Kynapse path data (`.hpd`) and world definition (`.aipathdata`), byte by
byte, the `nav/` folder (`<Level>.nav.json`, `<Level>.nav.glb`), the
coordinate space, the 1 m height of the data above the ground, the
generation stamp, and how a path-object id names a level node.

## 6h. [SCRIPT_DATABASE.md](SCRIPT_DATABASE.md) — the script name database
`database.bin`: layout, the four retail files, what its names look like, how
it compares with the toolkit's name tables, the seven Part 1 keys.
`watchmen scriptdb`.

## 6i. [BUILTINS.md](BUILTINS.md) — the builtin script module
The 123 functions and 19 properties scripts can call without a node, their
calling convention, type codes, stubs, enums.

## 7. [re/](re/README.md) — research reports
The nine reports of the 2026-10-02 decompilation pass (events, placement,
sync markers, enums, pages, collision volumes, jiggle, file formats, names)
and two added on 2026-10-03 — `physx_d6.md` (the PhysX 2.8.1 solver's
treatment of the jiggle joint, read from `PhysXCore.dll`) and `vcolor.md`
(vertex colour, tangent frame and winding, read from the shader bytecode) —
with their tables, shipped verbatim, and ten added on 2026-10-04: the script
layer (`wp0_script_names.md`), the renderer (`wp1_renderer.md`), ragdolls and
the PhysX layer (`wp2_physics.md`, with `wp2_ragdoll_rigs.json`), combat
rules (`wp3_combat.md`), enemy AI (`wp4_ai.md`), the runtime core and level
flow (`wp5_runtime.md`), audio (`wp6_audio.md`), effects / camera / HUD
(`wp7_fx_camera_hud.md`), the audit that started them
(`dominatrix_audit.md`) and the face system (`face.md`). `re/README.md` says
what each establishes, at what evidence level, and which statements were
corrected afterwards — by the implementation and by the later reports.
The lifted script corpus those reports read is research output outside the
toolkit; its second version (builtin calls by name, the task flags named,
typed format calls) is kept on the project PC under
`ghidra_kapow_out\engine\script_lifted_v2`, the third (every registered
handler as C text, native members named from their accessors) under
`ghidra_kapow_out\engine\script_lifted_v3`.

## 8. [../tools/ghidra/](../tools/ghidra/README.md) — Ghidra scripts
Define the registered command handlers, repair the functions truncated at
`__EH_prolog`, dump the decompilation. Needed only to read the executable,
not to extract assets.
Its last section, "Further tooling, 2026-10-06", describes three pieces of
research tooling that are kept outside the toolkit, on the project PC under
`ghidra_kapow_out\`: `engine\gap_sweep` (the code between the dumped
functions of the PC executable: 16,309 more functions, 28 of them registered
command handlers), `ps3_p2\lang_cell` (the three Cell VMX instructions
Ghidra lacks, for the PS3 executable) and `x360_p2\lang_vmx128` (a Ghidra
language for the Xbox 360 executables, VMX128). They are needed only to read
the executables.
Added there on 2026-10-07, also outside the toolkit: `engine\dump_v5` (the
merged dump of the PC executable, 35,542 functions: the 19,233 dumped ones,
21 of them with their cut tails restored, and the 16,309 of the gap sweep;
with call references, exact body ranges and the lookup scripts `fn.py`,
`hh.py` and `xdis.py`), `engine\script_lifted_v3` (the lifted script corpus,
third version), the console dumps `x360_p2\dump_vmx128` (Xbox 360 Part 2,
decompiled with VMX128) and `ps3_p2\dump_cell` (PS3 Part 2, decompiled with
the Cell instructions), each with its table of registered commands joined to
the PC registry, and `engine\engine_notes\step7_2026-10-07` (the
per-function coverage table behind the figures of `re/README.md`).

## Code map

| Area | Module |
|---|---|
| CLI | `watchmen.py` |
| Facade (import this) | `wlib/watchmenlib.py` |
| naz walk, block extract, textures/models/audio | `wlib/watchmen_extract.py` (since 1.4.0 also `texture_sheet` / `read_sheet_json`: the material switches written as `sheet.json` beside each texture; `ati2_xy`: the PC `ATI2` channel order; `TexRef` / `TextureIndex` / `resolve_texture`: textures by the asset path the model stores) |
| Fragment parser (lossless) | `wlib/kapow_fragment.py` |
| Name hash (`name_hash`) + prop-bag JSON | `wlib/kapow_props.py`, `wlib/kapow_json.py` |
| Skeleton/mesh decode | `wlib/parse_model_nodes.py` (the node decoder), `wlib/extract_skeletons.py`, `wlib/skeleton_records.py` (node collision volumes; byte-order aware since 1.2.0) |
| File-only binds | `wlib/build_bind_file.py` |
| Clip → palette baker (engine-exact) | `wlib/bake_v4.py` |
| Character GLBs | `wlib/variant_glb.py`, `wlib/char_lib.py`, `wlib/characters_export.py`, `wlib/rig_glb.py` (`extract --glb`). Since 1.4.0 both writers put NORMAL, TANGENT and COLOR_0 into the GLBs and reverse the winding to match; `--no-vertex-attrs` (character commands also `WATCHMEN_VERTEX_ATTRS=0`) writes the 1.3.0 attribute set. `rig_glb.material_alpha`, `linear_vertex_colors`, `gltf_normal_png`; `variant_glb.Part`, `buffer_vertex_attrs` |
| Faces | `wlib/face_rule.py` (the game's rule: face classes, inputs per body state, face tracks, idle entry (`idle_entry`), `clip_mix`, track choice per clip, the head a variant gets, texture sheets; `--face-rule engine|legacy`, `--no-face-idle`), `wlib/face_export.py` (`watchmen faces`), `wlib/face_synth.py` (pose blending; the name-based pose of `--face-rule legacy`) |
| Jiggle | `wlib/jiggle_d6.py` (`apply_jiggle(…, model=…, loop=…)`: `"solver"`, new in 1.4.0 and the default, which steps PhysX's soft swing-limit row with the file constants only — class `SoftLimitJoint` — and bakes looping clips as a closed lap; `"pivot"`, the engine-geometry model with capture-fitted constants added in 1.3.0; `"pinned"`, the default of 1.2.0 to 1.3.0; `--jiggle-model solver|pivot|pinned` on `characters` / `char`), `wlib/jiggle_pass.py` (spring fallback), `wlib/exact_math.py` (the solver's trigonometry, nearest rotation and sums in plain float arithmetic, bit-identical on every platform) |
| State machine | `wlib/anim_state_machine.py` (loader, the engine's rules, interpreter; `python3 wlib/anim_state_machine.py FRAG.json [--seed N]`) |
| Pairs, placement, events, skeleton tables | `wlib/anim_meta.py` (`watchmen animmeta`; see [ANIMATION_META.md](ANIMATION_META.md)) |
| Combat rules | `wlib/combat_meta.py` (the `combat` block of `anim_meta.json`; `python3 wlib/combat_meta.py ANIM_META.json` prints the totals; see [COMBAT_META.md](COMBAT_META.md)) |
| Effects, camera cuts, rumble | `wlib/fx_meta.py` (`watchmen fxmeta`; `cut_camera`, `halfbell`, `blend_real_s`, `damage_slots`, `resolve_slots`, `character_attachments`; see [FX_META.md](FX_META.md)) |
| Levels, save files | `wlib/level_meta.py` (`watchmen levelmeta`, `savemeta`; `link_nav`; see [LEVEL_META.md](LEVEL_META.md)) |
| Text and subtitles | `wlib/text_assets.py` (`watchmen text`, `textmeta`; `extract` writes `text/`; see [TEXT_ASSETS.md](TEXT_ASSETS.md)) |
| Particle systems | `wlib/particle_asset.py` (`parse`, `build`, `values`; the extractor's `.particle.json`), `wlib/particle_meta.py` (`watchmen particlemeta`: all files plus an index); see [PARTICLE_FORMAT.md](PARTICLE_FORMAT.md) |
| Asset names | `wlib/canonical_names.py` (+ `canonical_names.json`: the one spelling of the 41 asset paths whose letter case differs between the six sets; `--names canonical|stored`; `extract` writes `_canonical_names.json`; `ExportIndex`, `resolve`, `respell_export`: the strings of a table that name an exported file, spelled as the file is written; see "Asset names" in [ENGINE_CONSTANTS.md](ENGINE_CONSTANTS.md)) |
| Navigation data | `wlib/nav_data.py` (`watchmen navmeta`; `extract` writes `nav/`; see [NAV_DATA.md](NAV_DATA.md)) |
| Script name database | `wlib/script_database.py` (`watchmen scriptdb`; see [SCRIPT_DATABASE.md](SCRIPT_DATABASE.md)) |
| Builtin script module | `wlib/script_builtins.py` (+ `builtins.json`; see [BUILTINS.md](BUILTINS.md)) |
| Level grade | `wlib/materials.py` `level_grades` (`watchmen grademeta`; `PLATFORM_ADJUSTMENT`, `grade_adjustment`) |
| Alpha mode of a material | `wlib/materials.py` `alpha`, `texture_has_alpha`; `wlib/rig_glb.py` `material_alpha`; `watchmen_extract.texture_alpha_flag` (`sheet.json` `textureHasAlpha`), `sheet_blend` |
| Is a folder an extract output | `wlib/extract_out.py` (`require`: the test the EXTRACT_OUT commands make first) |
| Coordinate frame of the output | `wlib/frame.py` (`--frame true\|mirrored`, `$WATCHMEN_FRAME`; `reflect_gltf`, the scalar rules, the marker) |
| Engine serialization schema | `wlib/engine_schema.py` (+ `reg_dump.json` format 2, `command_signatures.json`; prop-names view derived at runtime) |
| Engine enum tables | `wlib/engine_enums.py` (+ `engine_enums.json`: 34 families, criteria variables, event semantics) |
| Data-table regeneration | `wlib/gen_data.py` (`watchmen gendata`; provenance of every shipped table in its docstring and README; `respell` applies the registered spellings of `registered_names.json` to the property dictionary; `add_dispatch` derives the command dispatch keys of `reg_dump.json`) |
| Small formats | `wlib/decode_sequence.py` (`.sequence`, engine grammar; `evaluate`, `play_position`) |
| Fonts, terrain, terrain colouring, detail mesh tail | `wlib/font_asset.py` (`parse`, `build`, `atlas_image`), `wlib/terrain_asset.py` (`parse`, `build`, `decode_stream`, `height_field`, `build_glb`; `coloring_*`; `detail_tail`) |
| Model header layouts, console streams | `wlib/watchmen_extract.py` (`parse_model_header(layout=)`, `MODEL_LAYOUTS`, `model_stream_layout`, `CONSOLE_VERTEX_STRIDES`, `console_color_order`, `CONSOLE_COLOR_ORDERS`, `console_platform_of` / `set_console_platform` / `detect_console_platform` / `console_platform_for` (`WATCHMEN_CONSOLE`); `decode_model(status=)` / `MODEL_STATUS`: why a model has no GLB), `wlib/skeleton_records.py` (`read_property_records(layout=)`, the untyped records) |
| Multi-part models, texture layer slots, standalone files | `wlib/watchmen_extract.py` (`model_part_transforms`, `apply_part_transform`, `decode_model_mesh(part_space=)`; `TEXTURE_SLOT_LABELS`, `TEXTURE_LAYER_SLOTS`, `CUBE_FACE_ORDER`, `texture_frame_ms`; `standalone_preamble`, `STANDALONE_SIGNATURES`, `standalone_output_name`); tests `test_p6_models`, `test_p6_textures`, `test_p6_materials`, `test_p6_level_renderer` |
| Legacy standalone exporter | `wlib/export_female_anims.py` (also the `grab_blocks` helper everything uses) |
| Exported materials beside captured frames (one measurement) | `docs/MATERIAL_COMPARISON.md` |
| Tests (no game files needed) | `tests/` — run `pytest` (1,774 tests); `test_frame` and `test_review_r6` pin the coordinate frame (`--frame`: the true-handed output is the exact reflection of the mirrored one; the sense of the yaw numbers); `test_materials_no_highlight` pins that a material without a highlight is fully rough; `tests/test_v120_regressions.py` pins every 1.2.0 fix (each verified to fail on 1.1.0); `test_names`, `test_formats_v2`, `test_phys_v2`, `test_interp_v2`, `test_anim_meta_v2`, `test_followup` pin 1.3.0; `test_jiggle_solver`, `test_jiggle_default`, `test_vcolor`, `test_face_rule`, `test_texture_lookup`, `test_texture_sheets`, `test_parts_and_face2`, `test_outfits_integration`, `test_materials_v2`, `test_ragdoll_rig`, `test_audio_v2`, `test_wave2_integration`, `test_combat_meta`, `test_fx_meta`, `test_level_meta`, `test_text_assets`, `test_particle_asset`, `test_particlemeta`, `test_nav_data`, `test_feature_seams`, `test_realdata_r5`, `test_fullextract` and the engine rules' `test_p1_combat`, `test_p1_level`, `test_p1_anim`, `test_p1_formats`, `test_p1_materials`, `test_p1_integration` pin 1.4.0 (`test_p1_anim`: the first-child blend rule, the random idle entry, the turned-master placement and the fixed cut camera; `test_p1_integration`: the table revision and the registered spellings); for Parts 1 and 2 on all platforms, `test_p2_console_chars` (header byte order, console parts and ragdoll, the `not_decoded` marker), `test_p2_audio` (PS3 / Xbox 360 sound headers, durations), `test_p2_part1` (stream sets, the older record layout), `test_p2_fragment` (JSON sections from the exact parse, type guesses, Part 1 keys), `test_p2_x360_textures` (console texture header, DXT3A, cube maps), `test_p2_small` and `test_p2_small_integration` (one output per name, loose-folder nav, `stable_uid`, cache keys) and `test_p2_integration` (the seams between them); after the six-set export `test_p3_raw_formats` (font, terrain, terrain colouring, detail mesh tail, scene), `test_p3_part1_model` (the stand-alone Part 1 model header, untyped records, console streams and colour order) and `test_p3_reporting` (the not-decoded markers and summary lines, the `glb` marker, `inferred_names`, the block order) and `test_p3_batch` (the reason text of the character `not_decoded` marker); `test_p8_canonical_names` (one spelling for asset paths, folders and the strings of the tables, `--names`); `test_s2_lash` (the restored eyelash UVs and their mark, `WATCHMEN_NO_SYNTH`), `test_s2_names` (movie strings below `files/data/`, `asset_names` of the particle index), `test_s2_glow_opacity` (a light layer's opacity as `emissiveFactor`), `test_s2_jiggle_determinism` (`exact_math` and the solver bake pinned by digest), `test_s2_fragment_scan`, `test_s2_tree_glob`, `test_s2_mean_fsum`, `test_s2_sound_event_lists`, `test_s2_path_objects_unbound` and `test_s2_file_handles` (no `open()` outside a `with`); `test_s4_review_fixes` (the clip name scan and stale bakes, the clip families of `char`, `host_offset_copy` and the stored transform of level models, `code_names`, the movie strings of `text_meta.json`); `test_s5_code_findings` and `test_text_layout` (rules read from the executable after the six-set export: the animation type rule, waypoint links, culling groups, lights, the sequence action track, PVS-root visibility, triangle strips, the typed fragment stream, the TextBox line breaker, the `%N` and sender tables; the twist pass and exact track names of `bake`, the cube map per culling area); `test_s8_review_fixes` (clip timing without a walk / run multiplier, the options record of a resumed export, the bake identity, the jiggle constants of the extract, the exit codes, the error on a folder that is not an extract output and the GLB name in the log); `test_s6_findings` (layer fields of a state and `layer_use`, the partner's waypoint constants and the Underboss movement, flee and flamethrower rules, the exploration camera collision block, the field names and aliases of the terrain, colouring, detail-mesh, font and pivot-book JSON, `skinned_bone_count`, `hidden`, `from_cloth` / `cloth_submesh`, texture `usage`) |
| Blender | `tools/blender_import_level.py` (a `<Level>.level.json` as instanced models, terrain, sky, characters; LEVEL_META.md "A level in Blender"; test `test_blender_import_level`), `tools/blender_attach_extras.py` (clip metadata onto imported actions) |
| Ghidra scripts | `tools/ghidra/` |
| Reading the D3D9 captures | `tools/apitrace/` (`atx.c`, a seekable apitrace reader; research tool, not used by the toolkit) |

Extractor options added in 1.3.0: `--model-lod N|all` (default 0: the
full-detail LOD only) and `--language 0..5|NAME` (slot, language name or
code for localized block entries, default 0; names since 1.4.0).

Added in 1.4.0:

- `--frame true|mirrored` (`all`, `extract`, `characters`, `char`, `charlibs`,
  `faces`, `animmeta`, `fxmeta`, `levelmeta`, `navmeta`, `ragdoll`). `true`,
  the default: GLBs, OBJs and the data in their frame are true-handed
  (x = −engine x), marked `coordinate_frame: "right-handed-true"`.
  `mirrored`: the engine's left-handed numbers verbatim, as 1.3.0 wrote
  them, no marker, byte-identical to the output before the option.
- `--jiggle-model solver|pivot|pinned` (`characters`, `char`). The three
  jiggle models: `solver` (new, and the default: engine geometry, PhysX's
  soft swing-limit arithmetic, file constants only; looping clips are baked
  as one closed lap, other clips get a 0.25 s lead-in), `pivot` (engine
  geometry, capture-fitted spring), `pinned` (the default up to 1.3.0: the
  model of 1.2.0, file constants through a softening formula). Each has its
  own cache directory under `_bake/`. `--jiggle-model pinned` is the 1.3.0
  jiggle.
- `--no-vertex-attrs` (`extract` with `--glb`, `all`, `characters`, `char`,
  `charlibs`, `faces`): GLBs without NORMAL / TANGENT / COLOR_0 and with the
  file's winding, as 1.3.0 wrote them; from `extract --glb`, skinned models
  only. It does not bring back the old normal-map PNGs.
- Vertex attributes in the GLBs: NORMAL; TANGENT (stored tangent, w = −sign(
  dot(cross(N, T), B)), on normal-mapped materials); COLOR_0 (float, rgb sRGB →
  linear, only for buffers with the `hasColor` flag); winding reversed to
  glTF's. PC Part 2 header-decoded models only.
- `sheet.json` beside each extracted texture: `renderType`, `twoSided`,
  `alphaThreshold`, `opacity`, `blendType`, `normalMapPower`, `isLit`,
  `writeDepthBuffer`, `enableNormalMapping`. `extract --glb` builds its
  materials from it; the character GLBs take the `MASK` cutoff and the normal
  scale from it.

- `--face-rule engine|legacy` and `--no-face-idle` (`characters`): the face
  channels of body clips follow the game's face classes (`engine`, default)
  or the clip name (`legacy`, as 1.3.0). `anim_meta.json` has a `face` block.
  Thug, ThugFast, ThugBig, Gimp and GimpGagBall get the game's rigged head.
- Textures are resolved by the asset path in the model header (`TexRef`,
  `TextureIndex`); a face-rigged head taken from a head collection uses the
  texture sheet that collection names, including a sheet's layer override;
  subtractive layers (Rorschach's inkblots) are written as black ink with
  alpha.
- `--no-meta` (`char`): `char` otherwise builds the animation metadata from
  the extract its fragment lies in.

- `anim_meta.json` carries two more blocks, each with its own format marker:
  `combat` (`combat_format`, COMBAT_META.md) and `fx` (`fx_format`,
  FX_META.md). The table stays `watchmen-anim-meta/2`; a table without the
  markers is rebuilt by `characters`.
- New commands: `levelmeta`, `savemeta`, `text`, `textmeta`, `fxmeta`,
  `navmeta`, `particlemeta`. `extract` also writes `text/` (`--no-text`) and `nav/`
  (`--no-nav`).
- `<name>.particle.json` is the `kapow-particle/2` tree; fragment JSON has a
  `header`; `.scene` files are parsed as fragments; fragment property keys are
  spelt as the engine registers them (`visible`, `open`, `useRealtime`).
- Level files say which collision volumes block AI sight (`ai_sight`), what a
  forced-state action asks for and which models the two heroes take; nav
  files name the mesh-link gate and the path-object flags; the sound and text
  tables carry the speak, cue and subtitle-route rules (LEVEL_META.md,
  NAV_DATA.md, SOUND_META.md, TEXT_ASSETS.md).

Changes that affect output are recorded in [`../CHANGELOG.md`](../CHANGELOG.md).
