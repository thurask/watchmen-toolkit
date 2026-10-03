# Documentation index

Reading order for someone new to the codebase. These are the living technical
records from the reverse-engineering effort; later sections supersede earlier
ones within each file (each keeps a dated changelog).

## 1. [KAPOW_NAZ_FORMAT.md](KAPOW_NAZ_FORMAT.md) — the archive
The `.naz` container: layout, zlib framing, the naz→zip mapping, and the
`.block_h_z` / `.block_s_z` header+stream pair format that everything else
sits inside: the 400-byte block header, the directory record, the asset
header, the Texture descriptor and the ModelRes header and stream (corrected
2026-10-02 from the engine's loaders).

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

## 4. [FORMATS_MISC.md](FORMATS_MISC.md) — the small formats
`.font`, `.particle`, `.terrain`, `.grass`, `.pb`, `.sequence`,
`.detailmesh` — all decoded, all with JSON emitters in `wlib/kapow_json.py`.
Also the collision volumes in a `.model` node tail.

## 5. [ENGINE_CONSTANTS.md](ENGINE_CONSTANTS.md) — the animation engine
The deep record of the animation system, recovered from the executable and
validated against GPU captures: skeleton rest poses and the file-only bind
construction (Rb = conjugated FK), clip decode (quat/10000, POSITION/1000),
frame-rate scale (FULL/HALF/THIRD), the state-machine interpreter and overlay
pages (two-stack model), jiggle dynamics (PhysX NxD6Joint soft limits), face
synthesis, weapon attachment, and the per-session changelogs that got there.
It is an append-only notebook: the last section ("2026-10-02 (later) — full
decompilation pass") is current, and earlier statements it overturns carry an
inline `[corrected 2026-10-02: …]` note.

## 6. [ANIMATION_META.md](ANIMATION_META.md) — states, events, transitions, pairs
Format 2 of the `anim_meta.json` sidecar and the `extras` embedded in the
character GLBs: every state with its criteria, speed and events (trigger kind
and real time), transitions with sync markers, which clip plays against which
(from the game's `Master of` table), where the partner stands and when it is
anchored and released, and the bone names and parents. Has a section on what
changed since format 1.

## 7. [re/](re/README.md) — research reports
The nine reports of the 2026-10-02 decompilation pass (events, placement,
sync markers, enums, pages, collision volumes, jiggle, file formats, names)
with their tables, shipped verbatim. `re/README.md` says what each
establishes, at what evidence level, and which statements were corrected
while implementing.

## 8. [../tools/ghidra/](../tools/ghidra/README.md) — Ghidra scripts
Define the registered command handlers, repair the functions truncated at
`__EH_prolog`, dump the decompilation. Needed only to read the executable,
not to extract assets.

## Code map

| Area | Module |
|---|---|
| CLI | `watchmen.py` |
| Facade (import this) | `wlib/watchmenlib.py` |
| naz walk, block extract, textures/models/audio | `wlib/watchmen_extract.py` |
| Fragment parser (lossless) | `wlib/kapow_fragment.py` |
| Name hash (`name_hash`) + prop-bag JSON | `wlib/kapow_props.py`, `wlib/kapow_json.py` |
| Skeleton/mesh decode | `wlib/parse_model_nodes.py` (the node decoder), `wlib/extract_skeletons.py`, `wlib/skeleton_records.py` (node collision volumes; byte-order aware since 1.2.0) |
| File-only binds | `wlib/build_bind_file.py` |
| Clip → palette baker (engine-exact) | `wlib/bake_v4.py` |
| Character GLBs | `wlib/variant_glb.py`, `wlib/char_lib.py`, `wlib/characters_export.py`, `wlib/rig_glb.py` (`extract --glb`; can write NORMAL / TANGENT / COLOR_0, not enabled in the CLI) |
| Faces | `wlib/face_export.py`, `wlib/face_synth.py` |
| Jiggle | `wlib/jiggle_d6.py` (`apply_jiggle(…, model=…)`: `"pinned"`, the default, or `"pivot"`, the engine-geometry model added in 1.3.0; `--jiggle-model` on `characters` / `char`), `wlib/jiggle_pass.py` (spring fallback) |
| State machine | `wlib/anim_state_machine.py` (loader, the engine's rules, interpreter; `python3 wlib/anim_state_machine.py FRAG.json [--seed N]`) |
| Pairs, placement, events, skeleton tables | `wlib/anim_meta.py` (`watchmen animmeta`; see [ANIMATION_META.md](ANIMATION_META.md)) |
| Engine serialization schema | `wlib/engine_schema.py` (+ `reg_dump.json` format 2, `command_signatures.json`; prop-names view derived at runtime) |
| Engine enum tables | `wlib/engine_enums.py` (+ `engine_enums.json`: 30 families, criteria variables, event semantics) |
| Data-table regeneration | `wlib/gen_data.py` (`watchmen gendata`; provenance of every shipped table in its docstring and README) |
| Small formats | `wlib/decode_sequence.py` (`.sequence`, engine grammar; `evaluate`) |
| Legacy standalone exporter | `wlib/export_female_anims.py` (also the `grab_blocks` helper everything uses) |
| Tests (no game files needed) | `tests/` — run `pytest` (406 tests); `tests/test_v120_regressions.py` pins every 1.2.0 fix (each verified to fail on 1.1.0); `test_names`, `test_formats_v2`, `test_phys_v2`, `test_interp_v2`, `test_anim_meta_v2`, `test_followup` pin 1.3.0 |
| Ghidra scripts | `tools/ghidra/` |

Extractor options added in 1.3.0: `--model-lod N|all` (default 0: the
full-detail LOD only) and `--language 0..5` (slot for localized block
entries, default 0).

Changes that affect output are recorded in [`../CHANGELOG.md`](../CHANGELOG.md).
