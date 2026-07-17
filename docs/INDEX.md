# Documentation index

Reading order for someone new to the codebase. These are the living technical
records from the reverse-engineering effort; later sections supersede earlier
ones within each file (each keeps a dated changelog).

## 1. [KAPOW_NAZ_FORMAT.md](KAPOW_NAZ_FORMAT.md) — the archive
The `.naz` container: layout, zlib framing, the naz→zip mapping, and the
`.block_h_z` / `.block_s_z` header+stream pair format that everything else
sits inside.

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
`wlib/kapow_fragment.py`; the property-name hash (CRC32 0x04C11DB7 over
UPPERCASE) is in `wlib/kapow_props.py`.

## 4. [FORMATS_MISC.md](FORMATS_MISC.md) — the small formats
`.font`, `.particle`, `.terrain`, `.grass`, `.pb`, `.sequence`,
`.detailmesh` — all decoded, all with JSON emitters in `wlib/kapow_json.py`.

## 5. [ENGINE_CONSTANTS.md](ENGINE_CONSTANTS.md) — the animation engine
The deep record of the animation system, recovered from the executable and
validated against GPU captures: skeleton rest poses and the file-only bind
construction (Rb = conjugated FK), clip decode (quat/10000, POSITION/1000),
frame-rate scale (FULL/HALF/THIRD), the state-machine interpreter and overlay
pages (two-stack model), jiggle dynamics (PhysX NxD6Joint soft limits), face
synthesis, weapon attachment, and the per-session changelogs that got there.

## Code map

| Area | Module |
|---|---|
| CLI | `watchmen.py` |
| Facade (import this) | `wlib/watchmenlib.py` |
| naz walk, block extract, textures/models/audio | `wlib/watchmen_extract.py` |
| Fragment parser (lossless) | `wlib/kapow_fragment.py` |
| Property hash + prop-bag JSON | `wlib/kapow_props.py`, `wlib/kapow_json.py` |
| Skeleton/mesh decode | `wlib/decode_skeleton_model.py`, `wlib/extract_skeletons.py`, `wlib/parse_model_nodes.py`, `wlib/skeleton_records.py` |
| File-only binds | `wlib/build_bind_file.py` |
| Clip → palette baker (engine-exact) | `wlib/bake_v4.py` |
| Character GLBs | `wlib/variant_glb.py`, `wlib/char_lib.py`, `wlib/characters_export.py`, `wlib/rig_glb.py` |
| Faces | `wlib/face_export.py`, `wlib/face_synth.py` |
| Jiggle | `wlib/jiggle_d6.py` (D6 model), `wlib/jiggle_pass.py` (spring fallback) |
| State machine | `wlib/anim_state_machine.py` |
| Engine serialization schema | `wlib/engine_schema.py` (+ `reg_dump.json`; prop-names view derived at runtime) |
| Data-table regeneration | `wlib/gen_data.py` (`watchmen gendata`; provenance of every shipped table in its docstring and README) |
