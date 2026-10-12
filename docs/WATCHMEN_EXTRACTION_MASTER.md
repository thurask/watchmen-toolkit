# Watchmen: The End Is Nigh, Part 2 — Asset Extraction · Master overview

The overview of the extraction pipeline: a **pure-Python, fully static**
extractor that turns `game.naz` into **models, textures, and sounds** with
**no** running the game, debugging the exe, dumping memory, or NinjaRipper.
Engine = **Kapow** (Deadline Games, codename WM07), a 32-bit D3D9 title.

This document is the index: it says what each layer is, which document holds
the authoritative layout, and it keeps the facts that live nowhere else — the
console storage of textures and audio, the Part 1 loose trees, the verification
counts, the memory-dump cross-check and the decompilation corpus. The byte
layouts themselves are in [`KAPOW_NAZ_FORMAT.md`](KAPOW_NAZ_FORMAT.md) (container,
block, asset header, Texture, ModelRes, music streams),
[`FORMATS_MISC.md`](FORMATS_MISC.md) (`.sequence`, `.detailmesh`, node collision
volumes, the `sound` asset, `.pb`, `.font`, `.terrain`) and
[`ENGINE_CONSTANTS.md`](ENGINE_CONSTANTS.md) (what the engine does with the
data). `docs/INDEX.md` lists the others; the README has the command line and the
per-platform result table.

---
## 0. Status board

| Subsystem | Status | Notes |
|---|---|---|
| `.naz` archive → blocks | solved & verified | obfuscated ZIP; 2291 assets (bordello), 0 mismatch. `KAPOW_NAZ_FORMAT.md` §1 |
| block → asset (header+stream) | solved & verified | `extract_block(header, RAW block_s_z)`. `KAPOW_NAZ_FORMAT.md` §2 |
| Asset property-bag header format | characterized | typed, name-HASHED records (config). `KAPOW_NAZ_FORMAT.md` §3 |
| **Texture header → name/format/layers** | **solved & verified** | exact header grammar; 100 % exact name + format + layers on all 186 bordello textures. `KAPOW_NAZ_FORMAT.md` §4 |
| **Models — geometry → OBJ / GLB** | **header-driven on all six sets** (735 models with a stream per Part 2 set, 1,085 per Part 1 set; PC, Xbox 360, PS3) | `wlib/watchmen_extract.py`. Every buffer offset comes from the model header (§5); the descriptor scan is the fallback and decodes no shipped model. The extractor writes OBJ + MTL (and GLB with `--glb`); it has no FBX or STL writer |
| **Models — full byte-faithful parse** | header + stream tile exactly (740/740 Part 2 PC); node collision volumes parsed | The non-render bytes of the stream are shadow hulls, per-part occluders and cluster tables; collision volumes are in the header, per node (`skeleton_records.parse_node_tail`, `FORMATS_MISC.md`); the articulated body (ragdoll) and cloth lists are parsed (`KAPOW_NAZ_FORMAT.md` §6b) |
| **Models — skin weights** | **decoded** (4×u8 idx @+44, 4×half wt @+48, Σ=1) | rigged GLBs need the skeleton + keyframes from the `.animation` asset; see §5 |
| **Animation / skeleton (`.animation`)** | **decoded** — skeleton extracted (428/428), keyframe format decoded | bone names + fps + frames parse; compact quat/trans tracks decoded; `ENGINE_CONSTANTS.md` |
| **Per-variant character GLBs** | 26 GLBs per Part 2 set, 80 per Part 1 set, all QA'd in a renderer: header-exact fps, finger-shear dense bakes, d6 jiggle default, face attaches incl. NiteOwl cowl + Heavies_Head_1, BipNN name fixes | `watchmen.py characters OUT CHARS`; engine truths in `docs/ENGINE_CONSTANTS.md` |
| **Toolkit layout + one-command run** | `wlib/` next to `watchmen.py` (canonical lib); `python3 watchmen.py all game.naz OUT` = extract → binds → the `characters` export (OUT/characters) | README §Quick start |
| **Fresh-install clean-room run** | **verified** | binds bit-identical + character GLB numerically identical from `game.naz` alone; `watchmen.py extract/binds` |
| **Character BIND (rest pose → skinning palettes)** | **solved, file-only, engine-exact** (all 7 skeletons) | node records store [pos][quat XYZW] BEFORE the name; bind Rb = conj-quat FK, tb = FK(Rb, node locals); palette order = bone list rotated by one. `wlib/build_bind_file.py`, `wl.ensure_binds()`, `docs/ENGINE_CONSTANTS.md` |
| Vertex normal packing | solved | HALF4 (3×f16) at vertex+12 |
| **Textures — format enum** | solved (Ghidra) | enum→D3DFORMAT table @0xc799e0 |
| **Texture → stream binding** | **solved, deterministic** (1190/1190, no search) | the (off,sz) pair is the tail of the asset's own directory record. `KAPOW_NAZ_FORMAT.md` §2.3 |
| **Textures — pixel decode** | **complete — 1190/1190** stream-exact | the exact header plans every stream as single / cube×6 / animN; multi-layer diffuse + BC5 normal + spec all decode; §6 |
| **Audio — SFX (`sound`)** | **complete — 848/848** → WAV | `wlib/watchmen_extract.py`; format tag @+10 selects MS-ADPCM (98 %) / PCM (2 %); mono + stereo; §7 |
| **Audio — music (`.mediastream_s`)** | **13/13 → Ogg Vorbis** (one file per track) | `watchmen_extract.py`; `KAPOW_NAZ_FORMAT.md` §8 |
| **Determinism** | textures + archive verified reproducible | identical manifest + byte-identical PNG across runs |
| Full-binary decompile corpus | available | `ghidra_kapow_out\` (14,910 funcs); the pass with the scripts in `tools/ghidra/` has 19,233 functions (17,225 after `FixEHProlog`); the research reports are in `docs/re/` |

---
## 1. File map

**Inputs (on your machine)** — nothing here ships with the toolkit; every path
is relative to your own game install and working directory.

- `game.naz` — the source archive (~937 MB on PC).
- `Data/Engine/KapowMulti*.exe` — the game executable. Only
  `watchmen gendata regdump` reads it, and only usefully when its `.text`
  section is not encrypted; the retail build is SecuROM-packed in place and this
  toolkit neither unpacks it nor helps you obtain one that is unpacked. The
  string sections (`.rdata`/`.data`) *are* readable in the retail build, which is
  why `gendata strings` works on it.
- a pre-extracted `<level>.block_h_z` / `.block_s_z` pair — handy as a standing
  test case while working on the block layer.
- the Microsoft Direct3D 9 reference (D3DFORMAT, DXT/BC, surface and mip
  semantics) — consulted for the texture work.

**Reverse-engineering corpus** — a decompilation of the executable (function
index, string table, per-function decompiled C). Function addresses quoted
throughout this document refer to it. It is research input, not a shipped
artifact (§9).

**Code + docs** — this repository: `wlib/` (library), `watchmen.py` (CLI),
`docs/` (this record).

---
## 2. The `.naz` archive

`KAPOW_NAZ_FORMAT.md` §1 has the layout. In short:

- `.naz` is an **obfuscated ZIP**: EOCD magic `0x16ED5B50`, central-dir entry
  magic `0x0406F370`; filenames are **rotate-left-2** per byte
  (`b = (b>>6)|(b<<2)`); the central-dir fields are shifted **8 bytes** vs
  standard ZIP (engine does `if (NAZ) ptr -= 8`).
- Inside, level data is packaged as **blocks**: a `block_h_z` (all per-asset
  HEADERS) and a `block_s_z` (all per-asset STREAMS).

## 3. Block format

`KAPOW_NAZ_FORMAT.md` §2 has the header, the directory record and the loading
rules. What matters for an implementer:

- `block_h_z` is read raw: a fixed header of 400 bytes, a TOC + the per-asset
  header blobs (each blob itself zlib-compressed, by asset type). TOC fields:
  `TABLES_SIZE @332`, `NUM_TABLES @352`, entries start at `400`. Each TOC entry:
  6 header-blob sizes (one per language slot), the asset-type hash, a
  length-prefixed name, a `hasStream` byte and, if set, 6 stream `(offset,size)`
  pairs. `numLocalized @356` further records follow the main directory;
  `--language 0..5` picks their slot. `Toc` keeps the attribute names `flag`, `pairs`, `variants` and `unknown`
  as properties; `flag` / `pairs` describe the entry's own stream, `unknown` is
  the type hash.
- **`block_s_z` is a CONCATENATION of per-asset zlib substreams.** Each asset's
  stream = `inflate(block_s_z[offset : offset+size])` using the TOC pair.
- **Correct entry point:** `watchmen_extract.extract_block(decompressed_header_block,
  RAW block_s_z)`. Do **not** `zlib.decompress` the whole `block_s_z` first — that
  returns only the first substream and silently truncates everything.
- Header→stream pairing is proven: FemaleSkinBody_Black → stream offset 0 →
  inflates to 87400 B == the running game's GPU copy, byte-for-byte. 2291
  bordello assets, 0 mismatch.

## 4. Asset header = property bag

`KAPOW_NAZ_FORMAT.md` §3. Each per-asset header (the inflated TOC blob) is a
serialized **property bag**:
```
+0  u32 typeNameLen          (e.g. 7 = "Texture", 8 = "ModelRes")
+4  char[len] typeName
+.. u32 bagDwords            length of the property bag in 32-bit words
+.. bagDwords x 4 bytes of typed records, then the type-specific body
```
`bagDwords` (engine `FUN_00511f96`) is 45 for `Texture` (9 records of 20
bytes), 91 for `ModelRes`, 55 for `TextureEffects(Texture)`, 96 for
`ModelEffects(ModelRes)`. The body starts at `4 + typeNameLen + 4 + 4·bagDwords`.
A scalar record is 20 B: `[salt u32][name hash u32][type hash u32][tag u32][value]`
(`salt` is the per-asset constant repeated on every record — the alignment
oracle that proves the record size). **Property names are name-HASHED** (no
plaintext), and values are config (LOD distances, scales, flags) — NOT geometry.
The header is read **sequentially as a stream** by the engine (§8 primitives),
so sub-structures (like the texture image descriptor) sit at positions
determined by the preceding records. The name hash (`kapow_props.name_hash`)
folds every byte with `& 0xDF`; it does not upper-case. The two asset-type
hashes without a plain class name are `ModelEffects(ModelRes)` (0x41764525)
and `TextureEffects(Texture)` (0x96ea413f): script classes over a native
asset class. The node "joint records" of a model header are collision volumes
(`FORMATS_MISC.md`). The raw header blob is written as `<asset>.header` under
`extracted/`.

---
## 5. Models

Layout: `KAPOW_NAZ_FORMAT.md` §6b (header, stream, vertex formats on PC and
on the consoles, part transforms, the articulated body, the stand-alone Part 1
header).

- The reader chain is `ModelRes::Read` `FUN_00547006` → part `FUN_00545927` →
  submesh `FUN_00542541` → mesh buffer `FUN_004336ec`. `0x542541` is the
  submesh record; `0x4353E9` is ReadBool.
- The **header** lists every buffer (render submeshes per LOD, shadow hulls,
  an optional per-part occluder) with its vertex count, vertex **format id**
  and index byte count. The **stream** holds them in header order: vertices,
  u16 indices, a cluster table, lists, an optional per-vertex array. The sum
  reproduces the stream length exactly on 740 / 740 Part 2 PC models, so every
  offset is computed and nothing is searched.
- **Vertex formats** (stride table at `0x00C791B0`): 5 rigid (44 bytes), 6
  skinned (56), 9 shadow hull (20), 10 skinned shadow hull (32). Positions are
  raw `float32 × 3` in every format. **Vertex normal = HALF4** (3× float16 +
  pad) at `vertex+12`, little-endian — validated (unit_box 24/24; body 0.976).
  Colour, UV, tangent and bitangent offsets and what the fields are: the colour
  multiplies the lit colour and the texture alpha on buffers with `hasColor`;
  tangent and bitangent are ∂P/∂u and +∂P/∂v, used as stored; triangles wind
  clockwise against the normals. With `--glb` the extractor writes them as
  NORMAL / TANGENT / COLOR_0 and writes a GLB for rigid models too
  (`--no-vertex-attrs` turns that off).
- `watchmen_extract.decode_model` writes the full-detail LOD by default
  (`--model-lod N|all`), names each material from the submesh's texture-list
  index, and writes neither shadow hulls nor occluders. A model header lists
  its textures as full asset paths and the game loads exactly those
  (`ModelRes::Read` 0x547006): twelve bare names exist in more than one folder
  of Part 2, so the toolkit resolves textures by path
  (`watchmen_extract.TextureIndex`), never by material name alone
  (`ENGINE_CONSTANTS.md`, "How a model's textures are resolved").
- **The character pieces read the header too.** `char_lib.load_parts`,
  `variant_glb.load_parts`, the weapon / rigid attachments of
  `characters_export` and `export_female_anims.mesh_arrays` all go through
  `wlib/mesh_loader.py` `load_submeshes`: every render buffer of format 5 / 6
  at the stream offset `decode_model_mesh` gives (part-local positions, the
  primitive type honoured), paired with its geometry descriptor so that the
  material is the one the descriptor index selects; a buffer the header lists
  without a descriptor (a strip: the descriptor's last word is the primitive
  type, `find_descriptors` wants 1) is decoded from the header. The descriptor
  search (`_vb_ok` / `_ib_ok` from the end of the previous piece, then
  `char_lib.flat_buffer`) runs only when the header path does not apply, and
  logs `note: <model> sub<i>: header path not applicable (<why>); scanned`.
  Measured on the six sets: every pipeline load (body parts of every variant
  with its bind, face heads with their face binds, weapon attachments) took the
  header path — 2,091 piece loads, 0 scanned, 0 strips, 3 degenerate triangles
  (one per Part 2 set) — and gave arrays bit-identical to the scan's; on the
  900 character models with a stream the scan had found every piece at the
  header's offset (1,788 of 1,788 descriptors, 6 of them by the planar
  fallback).
- CVarList = 24-bit count + 8-bit flags (the `& 0xFFFFFF` seen everywhere).
  Stream primitive: `ReadU32 = 0x435459`.

**The descriptor scan (fallback).** `find_descriptors` / `_vb_ok` /
`decode_model` take `order=`; model jobs carry their block's order. The scan's
vertex class is the format id `G` read from the descriptor (not an element
count; the console declarations are not in the PC executable). Rules it uses:
the byte order is the one with **more** descriptors (a BE model can throw a
stray false-positive LE descriptor: X360 GimpBody LE=1 vs BE=2); `_ib_ok()`
requires the found VB to have a mostly-non-degenerate IB (<40 % repeated
index), because on X360 a false vbo ~4 bytes before the real one passes
`_vb_ok` (positions look sane) with an index buffer ~50 % repeated-index —
that false offset hit the Rorschach ink-blot decals (`rorschachspots01` /
`RorschachSpots02`, 132 verts / 224 tris each; the spots sit on the mask) and
the Twilight Lady hair submesh of `BS2_WithoutWeapon`; with `_ib_ok` both
decode bit-identical to PC (vdiff 0.0000, skin 100 %, 11/11 Rorschach parts).
Measured with the scan: bordello block 194/194 models on PC, X360 and PS3;
positions / uvs / faces byte-identical PC↔console (incl. a skinned model
PC↔PS3), normals within quantization (≤0.13°, `_dec1110` solved against the PC
half3 ground truth). `WATCHMEN_CONSOLE_MODELS=scan` sends console models to
the scan.

**Ruled out.**
- A "stride-16 baked env mesh" with int16 positions. No vertex declaration in
  the executable has a SHORT element; format 3 (stride 16) is a 2D format,
  `FLOAT2 pos + FLOAT2 uv`. All 735 model streams of Part 2 PC tile exactly
  with formats 5, 6, 9 and 10, which leaves no room for another vertex class,
  and the five `.detailmesh.stream` files the claim was attached to are float
  data (`FORMATS_MISC.md`). Which file the original observation was read from
  could not be found; it may have described a run-time buffer in a capture.
- A rigged export that skips models with mixed 44/56-byte submeshes
  (`len(SKIN_I) != len(subs)`): every model with a stream gets a GLB from the
  header path.
- The names `ModelResDerivedIO::Read @ ~0x542541` and `ReadByte = 0x4353E9`
  for those two functions.

---
## 6. Textures

Layout: `KAPOW_NAZ_FORMAT.md` §4 (header grammar, the 29-byte descriptor plus a
presence byte per optional slot, eight slots per frame, slot roles, layer
sizing with 4-byte row padding, cube maps per platform, decoding, material
switches and texture sheets).

**Header** (engine `FUN_005382aa` / `FUN_00429e77`; `watchmen_extract.parse_texture_frames`
reads it exactly): after the bag `u32 nFrames, u8 hasAnim`, then per frame eight
slots — a 29-byte descriptor for slot 0 and, for slots 1–7, a presence byte
followed by a descriptor if present — and the source path. The descriptor is
`u32 width, u32 height, u32 format, u32 0, u32 type (1 = 2D, 2 = cube), u8
hasAlpha, u32 mipCount, u32 0` (the two zero fields are the buffer's usage class,
0 in files, and the Xbox 360 stored size, 0 on PC and PS3); the slots are 0
diffuse, 1 normal, 2 specular, 3 glow, 4 height, 5 fallOff, 6 ambOcc, 7
specSize. A plain `Texture` has 9 property records, so the descriptor area
begins at offset 196. The source path "/data/.../<name>.bmp" gives the asset
name. The property bag carries the material switches `twoSided`, `renderType`,
`alphaThreshold`, `normalMapPower` and the rest of the texture sheet; extraction
writes them as `sheet.json` beside the PNGs (`twoSided` is what the renderer
turns into `D3DCULL_NONE`; `renderType` 1 is "Standard with blending";
`alphaThreshold` is the alpha-test reference).

**Texel data:** raw DXT/BC mip chain, top level first, **no per-stream header**
(starts directly with DXT block bytes; verified byte-exact vs GPU). The header
and the inflated stream length agree on 936 / 936 Part 2 PC textures; there is
no per-layer framing.

**Format enum table** — executable `@ VA 0xc799e0` (`formatTable[enum]`):
```
0 X8R8G8B8(4bpp)  1 A8R8G8B8(4bpp)  2 A8R8G8B8  3 L8(1bpp)  4 L8
5 DXT1(8B/blk)    6 DXT3(16B/blk)   7 DXT5(16B/blk)   9 ATI2/BC5(16B/blk, normals)
11-15 HDR/16-bit
```
Found via `cmp eax,'DXT1'/'DXT5'` @0x455695/0x4556a3 + `[0xc799e0+enum*4]`.
Enum 9 on PC stores each 16-byte block as **Y (8 bytes) then X (8 bytes)**;
`watchmen_extract.ati2_xy` reads them in that order. A PC `*_normal_*_ATI2.png`
decoded X-first has X and Y swapped, and nothing in a PNG says which decoder
wrote it. Console enums: PC 9 (ATI2) → X360 10 → PS3 7 (§14).

**In-memory texture struct:** `+4 width, +8 height, +0xc format-enum, +0x40 mipcount`.

**Mip-drop on load** (`FUN_005291f9` + `FUN_00453d4b`):
`mipCalc(x)=bit_length(x-1)`; `if (W>256 && H>256) drop = bit_length(min(W,H)-1)-8;
else drop=0`. Loaded size = `(W>>drop, H>>drop)` (smaller side caps ~256). This is
why authored vs GPU-dump sizes differ. The drop is **conditional** on the
runtime quality global `DAT_00e1563c` and applied **per layer** at GPU upload;
it is upload-only and does not size the stored data.

**Texture upload** (`FUN_005351f6`, texturesheet upload): a Texture is a
multi-slot MATERIAL with layer pointers at object `+0xe0/+0xe4/+0xe8/+0xec/+0xf0`
(diffuse/normal/spec/…); each is built as a **MutableTextureBuffer**
(`FUN_0043a183`) and uploaded as a 0x20-byte image element (`FUN_0053508e`
append). A TextureAsset holds an image array at `+0x90` (count
`*(this+0x94)&0xFFFFFF`, **16 B/image = `[u32 size][void* data]…`**);
`FUN_0048e78f` `memcpy`s each image by that explicit size (`TextureAsset+0x90`
`[size,ptr]`; a targeted re-decompile, `seeded.c`, confirmed the architecture).
The cube path is `desc[3]==2`, 6 faces (`FUN_004540d7` is the D3D
`CreateTexture` / `CreateCubeTexture` path). Sheet deserializers `FUN_00529a1a`
/ `FUN_0052e011` show the read pattern (width→this+4, height→this+8 via
ReadU32, etc.).

**Measured (bordello, 186 textures):** asset NAME, per-image FORMAT, image
COUNT and LAYER structure are 100 % exact. Most textures are **multi-layer
materials** (73 single · 10×2 · 98×3 · 5×4 images) = diffuse(DXT1) +
normal(ATI2/BC5) + specular(DXT1). Authored dims verified vs GPU:
FemaleSkinBody authored 512×1024 → 1 mip-drop → **256×512 DXT1 = the byte-exact
GPU copy**.

**General vs level blocks** (`derived_pc/levels/game_levels_part2/`):
- **`watchmenpart2.block_h/s_z` = the GENERAL/shared block** (parent level):
  1704 assets, 55 textures — all the global UI/FX (`gray`, `white100`,
  `ArrowMore`, `LightningStrike`, `Spark`), all single-layer.
- **`<level>/<level>.block_h/s_z`** (bordello, nightclub, streetsofriot,
  playervsplayer, tutorial; + `game_levels/mainmenu`) = per-level content,
  incl. the multi-layer material textures. Shared assets live in the parent
  block, level assets in the level.

**The length-based planner (fallback).** `watchmen_extract.parse_texture_header()`
(the stride walk over 30-byte windows, §4.3 of the format doc) and
`plan_texture_layers()` (shape from the stream length: single / cube×6 / animN)
decode no shipped texture; they run only when the exact header does not read. Their rules: anim counts capped at 64 and
tiered — EXACT frame multiples are accepted before the dropped-layer recovery,
LOOSE multiples only after it; the recovery can return a repaired set as an
exact frame multiple (Caustics01_001 = 32 × [16×16 + drifted 128×128]).
`_rescue_texture_plan` (carve-time, fail path only): full-offset record scan →
record-subsequence + mip brute force to EXACT stream tiling → coherence-scored
pick (Floor_Sidewalk_Curb_01's 4-layer drift). Results of that planner: Part 1
1971 textures → 1734 single / 201 cube / 35 anim (all ≤×32) / 1 drift-rescued;
Part 2 bordello 234 single / 37 cube / 2 anim / 0 fail; Part 1 all 8 blocks
1971/1971, 3581 PNGs, a 400-sample coherence scan with ONE outlier =
NightVision_Raster.BMP, a genuine 0/255 scanline overlay (rows alternate
exactly); Part 2 all 7 blocks 1333/1333 (1203 single / 112 cube / 18 anim).
Mansion_Floor_Wood_01/02 and Highlight_01 are singles ([512-set + 1024×1024
L8] and [32×32 + 128×128]; L8 coherence 8.8 vs 40.9 for a wrong plan), not
anims; Caustics01_001's ×32 plan decodes frame-for-frame identical in coherence
to Caustics01_001_g.

**Stub-diffuse materials are real packing.** 9 Part 1 textures pack a ≤8×8
layer 0 followed by full-size layers — e.g. Mercenary_armor2 = 4×4 "diffuse" +
2048×2048 "specMap", RorschachButton = [8×8 DXT1, 32×32 ATI2, 64×64 DXT1] (the
SAME shape ships on X360, so it is authored, not drift), KnotTop_RidersTorsoS =
[4×4 DXT1 + 256×512 ATI2]. Layer labels follow the engine's slot order (layer 0
= $diffuseMap, the next colour layer = $specMap), so the 2048 layer lands in
the specMap slot; for a material whose diffuse is a stub, the payload map is
the interesting one. The slot roles of stub materials are unverified against a
render capture.

**Ruled out.**
- "Stored resolution is not in the header / the stream stores a
  runtime-reduced copy with per-layer framing": `MansionDoor_01`,
  `Mansion_wood_01` and `Mansion_plaster_03` have byte-identical 512/512/512
  descriptors and streams of 11632 / 101244 / 9418 bytes; several streams
  have odd byte counts (9418, 33999, 159579); Bordello_Lamp is 218488 B. All
  of these are the exact layer sums of the format doc's §4.4 (the odd counts
  come from the 4-byte row padding of `L8` chains and the multi-slot header),
  not framing. Mip-drop does not size the stored data.
- Multi-image carving did not need the texture stream reader in
  `texturebuffer_dx9.cpp` (≈0x45b961 / 0x45bc5f, string anchor
  `"texturebuffer_dx9"`) or the `KapowMulti.DMP` as a per-layer dims oracle.
- A PC cube map is not stored as `6 × face-chain` (face-major); it is
  level-major (format doc §4.2).

### Memory-dump cross-check [measured]

`KapowMulti.DMP` (parsed MDMP, VA→file-offset map from the Memory64List; 1861
ranges / 1681 MB) against the `.naz` streams:
- **Single-layer `.naz` == GPU, byte-exact**: FemaleSkinBody DXT1 256×512 found
  verbatim in the dump at VA 0x2bf35020. In-memory surface descriptor = `[4CC
  'DXT1'][..][w][h][..][texel ptr]` ('DXT1' at ptr−60, dims at ptr−52/−48,
  mipcount at ptr−72).
- The GPU copy of the 4-layer material Gimp_BondageGear: **uncompressed 32-bit
  BGRA**, full-res — diffuse 256², normal 512², spec 256², reflection 256².
  The `.naz` Gimp_BondageGear1 (watchmenpart2 block) binds to a single
  174800-byte stream (all 6 TOC pairs identical), a coherent different
  texture; the GPU 512² normal alone (>256 KB) cannot fit it, and no block
  (raw or inflated) contains the GPU bytes verbatim. The dumped game ran with
  a different (higher-resolution) texture source than these blocks, most
  likely the play-mode / authored path (`.bmp` source → `WrappedCompressSurface`)
  [inferred]. Dumps are validation input only; the shipped pipeline reads the
  blocks.
- Loader: `kernel/scenegraph/loadblock.cpp` — async 2-buffer (header + stream)
  streaming system (`FUN_004a36d8`, "Allocating 2 buffers for asset block
  loading").

## 7. Audio

libVorbis + Bink + libpng/zlib are present in the executable.
`watchmen_extract.decode_audio` is the PC music path (Ogg/Vorbis with CRC +
lacing; one file per track, `KAPOW_NAZ_FORMAT.md` §8); `decode_sfx` the PC
`sound` path (`FORMATS_MISC.md`, "The `sound` asset"); the console paths are
in §14.

---
## 8. Engine serialization primitives (StreamBuffer)

`ReadU32 = 0x435459 · ReadVec3 = 0x4354a8 (12 bytes) · ReadFloat = 0x435494
· ReadBool = 0x4353e9 (byte == 1) · ReadU8 = 0x435403`. The 16-byte readers
are `0x4354d1` and `0x43553c`. `0x43552a` was listed as ReadVec3 and was not
re-checked. The header/stream are read sequentially with these.

---
## 9. The decompilation corpus

Ghidra flags the MSVC SEH frame-setup helper `FUN_00991850` as **noreturn**,
which truncates every SEH-using function to a ~14-byte stub
(`{ FUN_00991850(); }`). The shipped repair is `tools/ghidra/FixEHProlog.java`
(it attaches Ghidra's `EH_prolog` call-fixup and re-bodies 2,000 functions;
`tools/ghidra/README.md`); the corpus made with the scripts in `tools/ghidra/`
has 19,233 functions (17,225 after `FixEHProlog`, 19,233 after `FixNoReturn`).
`DumpDecomp.java` writes it; `KapowDecompExport.java`, `KapowDecompAll.java`
and `KapowDecompDeep.java` (an unshipped whole-binary run that cleared the
noreturn flag, re-disassembled the terminal call of each truncated function
and recomputed the body in place (`recomputeBody`) — `FUN_005351f6` 14 →
2215 B, `FUN_0045b961` 10 → 577 B, 5014 bodies regrown, 200 disasm-fallback
left, with the "Non-Returning Functions - Discovered" analyzer off and
Decompiler Parameter ID on; its output `ghidra_kapow_out\deep3\`) are not in
the repository. `ghidra_kapow_out` (14,910 funcs) is the first whole-binary
corpus. The research reports: `docs/re/formats.md` (the loaders),
`docs/re/names.md` (name hash, registration), `docs/re/skeleton_blobs.md`
(node blobs), `docs/re/vcolor.md` (shaders, vertex colour), and the `wp*.md`
reports.

Analysis of engine CODE requires an executable whose `.text` is not
encrypted; the retail build's is SecuROM-packed in place. The toolkit does
not unpack it and does not need it for anything except `gendata regdump`.

---
## 10. How to run things

The README has the command line. `watchmen extract game.naz OUT` (or
`python3 watchmen.py extract game.naz OUT`) extracts an archive or a loose
tree (§13); the block pair can be given directly (§3). To decompile a
subsystem in a local Ghidra after auto-analysis: Script Manager →
`DumpDecomp.java` (see `tools/ghidra/README.md`).

## 11. Workflow

Ghidra full-analysis of the executable needs a machine with enough memory for
it; the Python parsers are written against the exported `.c` corpus and
verified on the files.

## 12. Gotchas

- `block_s_z` = concatenated zlib substreams; never bulk-decompress it (§3).
- Property names are runtime-hashed — locate loaders by call/primitive patterns, not
  by grepping names.
- TOD (Tale of Despereaux) reverse-engineering tools are NOT 1:1 with Watchmen — the
  Kapow build differs (property-serialized headers vs TOD's fixed structs).
- A Part 1 extract and a Part 2 archive do not mix in the character commands:
  the binds must come from the same game (§13).

## 13. Watchmen **Part 1** support

Part 1 (`part1_pc/Watchmen/`) runs through the **same pipeline** — the block,
kapow, fragment, texture, model, and audio formats are the same as Part 2's,
with two layout differences in the asset headers (below). Part 1 ships the
asset containers **loose on disk** under `derived_pc/`
(`*.block_h_z`/`*.block_s_z`, `*.texture_*_z`, `*.modelres_*_z`,
`*.pivotbook_h_z`, `*.mediastream_s`) instead of packing them into a `.naz`.
Those loose files are byte-for-byte what the `.naz` stored internally, so every
decoder works unchanged.

`naz_entries()`/`naz_read()` in `wlib/watchmen_extract.py` accept a
**directory** as well as a `.naz`. Point any command at the loose tree:

```
watchmen extract part1_pc/Watchmen/derived_pc  OUT
```

`loose_entries()` walks the tree, yields the known asset suffixes with `.naz`-style
names (leading `/`, forward slashes → unique stems), and `naz_read` returns loose
files verbatim (`_z` is a naming convention, not naz-level compression). Measured:
Part 1 MainMenu block → 74 assets; a full `derived_pc` extract → 304 PNG textures
(diffuse/normal/specular splits), 106 models, 72 lossless JSON, fragments/
sequences/particles/animations, 13 decoded OGG. 8 fully-paired blocks; the 4
header-less `.block_s_z` (Prison/Art) are the stream-only blocks of
`KAPOW_NAZ_FORMAT.md` §2.4.

**Header layout differences.** The stand-alone Part 1 (PC and Xbox 360; the
PS3 disc carries Part 1 in the Part 2 layout) stores property records without
the type-hash word and one flag byte fewer per submesh record
(`KAPOW_NAZ_FORMAT.md` §3 and §6b, "The stand-alone Part 1 header"). In the
stride-walk fallback the same difference is the record size: Part 2 / WM07
records are 20 bytes (`[salt][hashLo][hashHi][tag][val]`, +4 when tag==2),
Part 1 / WM06 records 16 bytes (`[salt][hash32][tag][val]`, +4 when tag==2);
`_prop_walk()` auto-detects the stride by which one yields more consecutive
salt hits — no version flag. The texture descriptor (29 bytes plus one
presence byte per optional slot) is the same on both engines; only the start of
the descriptor area shifts. The `sound` field layout after the propbag is
byte-identical to Part 2. Measured: 1970/1971 Part 1 textures plan
deterministically in the fallback planner (1713 single / 201 cube / 56 anim;
sole fail = Floor_Sidewalk_Curb_01, rescued by `_rescue_texture_plan`); a
sample of 60 Part 1 SFX decode 60/60 (`_propbag_end` must walk the right
record size, or `decode_sfx` bails and no SFX/dialog is written; music is a
separate loose-file path). Part 2: bordello 273/273 texture plans, mainmenu
6/6 SFX. Part 1 headers show serializer DRIFT in the stride walk (a record
slips a byte, corrupting dim/mip fields: Mercenary_armor2's bogus 4×4 record
would give 116,510 tiny PNGs, Caustics01_002 ×60) — the exact header grammar
has no such drift.

**`characters` on Part 1.** Discovery is driven by the Part 2 cast list
`ENEMY_FRAGS` in `characters_export.py` ('Dominatrices', 'Gimp',
'GimpGagBall', 'TwilightLady', 'Heavies', 'Thug', 'ThugFast', 'ThugBig') plus
the player models via `MODEL_BIND` (rorschach→rsh, owl→nto), and
`ENEMY_FRAGS_P1` (Biker, BikerBig, Cop/Fast/Leader, Mercenary/Fast/Leader,
Minion/Fast, Prisoner/Elite/Fast, ThugLeader — added when the P1 marker
fragment exists) with `CLIP_PREFIX_P1` (per the AnimationClass fragments:
Enemy01=EN1 medium; Enemy03=EN1+EN3 small; EnemyBig=EN1+EN2 large — **'EN2'
means gimp on Part 2 but big-enemy on Part 1**, hence the per-game map). On
Part 1 the Thug* stems are the KnotTops and the players match by model name.
Part 1 ships only Medium/Small/Large skeletons (no Female/Gimp), so its whole
cast rides the M/S/L binds, which build file-only. Discovery on Part 1 yields
19 characters / 80 variants, all on the M/S/L + rsh/nto binds. Underboss (BS1
clips, no skeleton ref in its fragment) is not exported. The character
commands key on skeleton asset names in `wl._SKEL_ASSETS`.

**Binds must come from the same game.** Part 1's Medium/Small/Large REST POSES
DIFFER from Part 2's (same 45 bones; rest quats differ up to 0.65, positions
up to 1 cm — the cast was re-rigged between games; bind Rb diff up to 1.29).
Build the binds from the Part 1 source: pass it as the 3rd arg
(`watchmen characters OUT_pc_p1 CHARS_p1 part1_pc/Watchmen/derived_pc`).
`export()` prints a WARNING when the extract looks like Part 1 but the archive
does not. Binds/bakes/GLBs produced for a Part 1 extract with a Part 2
`game.naz` are MIS-BOUND — delete `OUT_pc_p1/binds`, the characters outdir and
its `_bake` and re-run. Verified end-to-end with P1-built binds: Biker exports
10+ variant GLBs (46 joints, 220 EN1 anims + GRIP poses, 24 embedded textures
each). `ensure_binds(..., extract_dir=)` builds each skeleton bind from the
`.model` header already in `<out>/extracted` (bit-identical to the
archive-built bind); `all`, `charlibs` and `characters` pass it, so after a
completed extract `characters` needs no archive (the archive is a fallback).

**`--glb` on Part 1** uses the same file-derived rig path as Part 2: joint
names and palette order come from each model's own embedded skeleton header
(`_model_palette`); the capture artifacts `skeleton_female_biped.json` /
`bundled_clip_*.npz` are not read. GLBs from `extract --glb` are in bind pose,
engine-exact animated GLBs come from `watchmen.py characters`. Rorschach/NiteOwl bind to their
own 64-joint palettes, heads to their own 46 (Rorschach rigs with its own
64-joint palette, not the female 48-bone template); Seagull is static (no leg
bones).

## 14. Console (Xbox 360 / PS3) support

The consoles ship the **same Kapow format** as PC; the platform differences are
byte order and a few codecs. Sources: `xbla/…/game.naz` (+ loose
`derived_x360/`) for X360, and `ps3/…/PS3_GAME/USRDIR/{p1,p2}/game.naz` for PS3
(both parts).

**Byte order — the key fact.** The **naz container is little-endian on every
platform** (EOCD magic `50 5B ED 16`, `titem=57`, rotl8 names all parse
unchanged — verified on both console nazes). Only the **block payload integers**
flip: little-endian on PC, **BIG-endian on the PowerPC consoles**. Inner `block_s_z`
zlib is still `78 9C`, and ASCII (names, the `DB851B2E…` GUID) is byte-order-
independent, so only the block-header `struct` reads change.

**Auto-detect, no flag.** `detect_block_order(h)` reads `NUM_TABLES` (@352) both
ways and keeps the plausible asset count (the wrong endianness reads as a huge
number); `parse_block_toc(h, order=None)` calls it and records `BLOCK_ORDER`.
Verified: X360 & PS3 bordello block → auto-picks BIG → **2291 assets, identical to
PC**; PC bordello auto-picks LITTLE → 2291. Console carve lands 2291
correctly-named assets on disk (fragments/wav/animation/model/bmp).
`naz_entries`/`naz_read` work on the console nazes with no change; block →
named-asset carving on X360/PS3 needs no flag (the `files/` + `extracted/` raw
trees). `asset_class()` is byte-order aware.

### 14.1 Fragments / sequences / JSON

All four parsers (`kapow_fragment`, `kapow_json`, `kapow_props`,
`decode_sequence`) take an endian prefix: `parse(..., order='<'|'>')` /
`to_json(name, data, order=)`, with per-format auto-detect when order is omitted
(`detect_order()`: fragment = chunk-size walk / schema-record scan; sequence &
terrain = f32 version plausibility 0.01–1000; propbag = leading
`[namelen][ClassName\0]` record). `watchmen_extract` passes `order=BLOCK_ORDER`
through. Key hashes are unchanged integers once read in the right order, so the
pkl key tables work as-is. **Verified on the bordello block:** PC 433/433 JSON
byte-identical to the pre-port parser; X360 & PS3 both 433 assets, 0
exceptions, fragments lossless 333/335 — the 2 failures are the same two TNT
CharacterAnimation fragments that fail on PC (not endian). 174/433 console JSONs
are byte-identical to PC; the other 259 differ only in genuine per-build values
(owner/GUID ids, raw4 hashes), not structure.

### 14.2 Audio

- **Music (`mediastream_s`)** is the segment-chained stream of
  `KAPOW_NAZ_FORMAT.md` §8: `[seg0][link][seg1][link]…[EOF loop-link]`, link =
  `[u32be m][u32be sizes…]` with `m = sum(sizes)+4*(n+1)`, first size = next
  segment length. X360 segments = raw XMA2 2048-byte packets (seg0 found by
  bootstrap scan over 2048-aligned candidates); PS3 segments =
  `[32B header][MP3 frames]`, header dword0 = MP3 payload size. **PS3 framing:** links
  are NOT emitted after every segment — most Part 2 music packs several headered
  segments back-to-back with a multi-entry link only between groups, and
  `str_p2` pads each segment up to a 16-byte boundary. `_ps3_media_walk` parses
  record-by-record (link OR segment at each offset; exact next offset first,
  align-16 fallback). Verified lossless on all 13 Part 2 music streams: MP3
  frame walk = 0 junk bytes, durations match PC Vorbis within 0.6 s.
- **Channels / rate / total samples** come from the block `mediastream` asset
  header (`media_meta_from_header`): after the `.wav\0` path,
  `[u32 totalSamples][u32 channels][u32 rate]` in block order (totalSamples verified ==
  XMA frame-count × 512 exactly). The trailing u32 table in that header (count
  then per-segment values) is the seek table.
- **SFX (`sound` class, inline)**: X360 = codec tag 3, XMA2 packets at
  propbagEnd+26 (`[+4 u16 ch][+14 u32 rate][+18 u32 samples][+22 u32 size]`,
  size % 2048 == 0; the PS3 layout and the full header: `FORMATS_MISC.md` "The
  `sound` asset"); PS3 = raw MP3 from the first frame sync after the propbag
  (`decode_sfx_console`). PC keeps the `decode_sfx` path. A cut at
  propbagEnd+30 is four bytes into the first packet and ends the file with the
  4-byte cue count: every `.xma` so cut (2,921 + 3,953 files per export) is the
  correct data shifted by four; ffmpeg decodes three correctly cut files to the
  PC audio (correlation 1.0 / 0.997 / 1.0 at zero lag, one to the exact PC
  sample count), and vgmstream decodes 26 of 26 sampled Xbox 360 files of the
  six-set export (correlation with the PC sound 0.99).
- **vgmstream is NOT bundled**: `watchmen extract NAZ OUT --vgmstream-cli PATH`
  (any platform's vgmstream-cli binary) converts console audio to `.wav`;
  without the flag, X360 audio is written as playable `.xma` (XMA2WAVEFORMATEX
  RIFF built by `_xma2_riff`; vgmstream reads it as Xbox Media Audio 2 with the
  right rate/samples) and PS3 as `.mp3`. `_emit_audio(keep_container=)` always
  keeps `.xma`; `.wav` is written only when `--vgmstream-cli` is given;
  `--keep-xma` additionally keeps the PS3 `.mp3` beside the decoded `.wav`
  (threaded through `decode_sfx_console` / `decode_console_audio`).
- Verified: menu48 decodes on both consoles to the same 3:33 track (X360 XMA
  2ch/48k, PS3 MP3 2ch/48k, healthy RMS at 10/50/90 %); mainmenu SFX 6/6 on both
  consoles (durations/rates match X360↔PS3; the one odd rain_R 9.7s vs L 37.6s
  is identical on both = genuine asset). Decoded X360 menu48 cross-correlates
  **0.998 at lag 0** with the PC-ogg ground truth of the same track; the
  on-disk X360 wavs (2934 files) are valid PCM with clean audio (no clicks /
  dropouts / noise; ZCR / RMS on par with PS3). A playback problem with such a
  file is in the player, not the data.
- A reference set `Watchmen_Part_2_Audio_X360/wave/` (2908 wavs, bare PCM, no
  tool metadata) is a byte-for-byte complete set of every X360 inline SFX
  converted by an unknown tool; its wav for Dash is exactly 53760 samples @
  48000 = the `ns`/`dsz` content the extractor reads (5 packets / 134 frames,
  structurally identical to the long files).
- **Ruled out.** "Short XMA2 streams (≲6 × 2048-byte packets) fail to decode in
  vgmstream r2117 and ffmpeg 4.4 ('broken frame: channel len >
  samples_per_frame')" — ~46 % of X360 SFX wavs (1583 files, almost all the
  short `Speaks/` dialog barks) came out all-zero, across fmt-0x166 /
  'seek'-chunk / legacy 'XMA2'-chunk containers, and padding with warm-up
  packets did not recover them. The cause was the four-byte shift above, not a
  decoder limit; the fallback of copying a matching wav from a reference dir
  is not needed. X360 music durations under vgmstream can still differ from
  PC on chained streams (Part 1: 9/13 off, both longer and shorter, e.g.
  Str_p1 1021 s vs PC 355 s); the raw `.xma` is kept and PS3 + PC are
  authoritative for length.

### 14.3 Textures

`carve_texture_console` is auto-routed from `carve_texture` when the header
only parses big-endian. The layer plan comes from the exact header
(`parse_texture_frames(hdr, ">")`): on X360 with each layer's stored size, on
PS3 with one stream segment per layer; file names follow the PC carve
(`faceN_` / `frameN_`). Console enums reflect platform re-encodes: **PC 9
(ATI2) → X360 10 → PS3 7**; X360 stores L8 spec-size maps as DXT1
(`KAPOW_NAZ_FORMAT.md` §4.2). `extract_specular` is order-aware and writes
`spec.txt` on the consoles too (spec exponent/intensity match PC exactly on
X360 & PS3: nightowlbelt 20/0.58, dominatrix 43/1.17).

- **PS3 streams are self-describing:** per-layer `[36-byte header][data]`,
  data size = u32be @ hdr+8; DXT pixel data is byte-identical to PC (a layer may
  carry more mips than PC, e.g. ATI2 stored with its full chain). PS3 normal
  layers are **DXT5nm** (X→alpha, Y→green, R/B filler);
  `_decode_one_layer(normal=True)` rebuilds (X, Y, Z) → a normal matching PC
  within a bit (126,126,252 vs 127,126,252). RSX stores UNCOMPRESSED layers
  (L8 specSize) in **Morton/Z-order**; DXT layers are linear. `_rsx_unswizzle`
  (x from even bits, y from odd, non-square pow2 = leftover high bits ride
  linearly on the wider dim) makes all 65 PS3 specSize maps BYTE-IDENTICAL to
  PC's linear L8. A linear decode gives scrambled maps (histogram right, pixels
  wrong, corr≈0.03 vs PC).
- **X360**: the whole stream is 16-bit byte-swapped (GPU 8-in-16) and every mip
  is tiled (`XGAddress2DTiledOffset`) — `XGAddress2DTiledOffset` reimplemented (`_xg2d`/`_xg_untile`;
  `_xg2d` is the exact canonical Xenia `XGAddress2DTiledOffset`, bit-for-bit),
  verified BYTE-EXACT vs PC after swap + untile. Per-layer size rule
  (`_x360_layer_bytes`): mips stored individually while min(w,h) ≥ 32 texels,
  each padded to 32×32 blocks; all smaller mips share one packed 32×32-block
  tail. X360 enum 10 is the same 2-channel BC5/ATI2 as PC enum 9
  (`TEX_ENUMS` / `TEX_FMT[10]=ATI2`; BC5 decode → clean purple normal, coherence
  1.3 vs 18.8 as DXT5).
- **Packed mip tail** (`_x360_packed_offset()`, returns `(xo, yo, halfswap)`):
  every texture whose pow2-padded texel dims are not both ≥32 packs its base
  level 16 TEXELS in from the tile edge along the short axis (x for
  taller-or-square, y for wider), i.e. `16//blk` elements; 4×4-texel
  single-block layers sit at element (1,0) for 8-byte blocks / (26,0) for
  16-byte blocks. Derived by brute-forcing all 55 affected sub-32px P1 textures
  against PC ground truth: 36 byte-identical + 17 within DXT-recompression
  noise (mean ≤ 8). Thin block-compressed textures — a wide, very short block
  surface spanning ≥1 full 32-block macro-tile wide but ≤4 blocks tall
  (`blk & we≥32 & he≤4`) — store the base level 4 rows below the packed tail
  (`_thin_mip_yoff(kind, we, he)` = 4 for exactly that class, else 0): BYTE-EXACT (0.00 vs
  PC) on the only two shipped such textures, `FloorCable_BlackPlastic_01`
  (256×16 = 64×4 blk) and `HoneyPot_lightChain_01` (128×4 = 32×1 blk); of the
  45 aspect-ratio thin textures the other 43 decode at row 0. 16-byte ATI2
  tail bases are shape-dependent: full-tile-wide thin rows (we≥32, he≤4) sit at
  y=16 ELEMENTS unswapped (HoneyPot_lightChain exact); other non-square shapes
  use the standard 16-texel spot but need the two 8-byte BC4 half-blocks
  SWAPPED per block (SawMillRope 4.5, Harley spokes 0.7 — noise-level); square
  4×4-block (NeonSign, Huey window: exact) and single-block (26,0) layers are
  unswapped. DXT5 (also 16 B) needs NO swap (valuearrows exact). Empirical,
  validated on all 8 known instances across P1+P2. After this: P1 X360 small +
  32bpp = 41 identical + 19 noise + 1 residual (ArrowMore); OUT_x360_p2's 36
  affected dirs + the standalone `gray.texture` = 34 pixel-identical + 7
  recompression-noise vs PC, 1 residual (ArrowMore).
- **Uncompressed 32bpp** (`_texel32_to_pc()`): PS3/RSX stores big-endian
  `A,R,G,B`; X360 stores PLAIN BE `A,R,G,B` (NOT GPU 8-in-16 swapped, so an
  unconditional `_bswap16` scrambles it to `R,A,B,G`). Both are reordered to
  the PC layout (`B,G,R,A`) before the shared decoder. The 6
  lensflare/lightprojector/lockpick maps per console: PS3 6/6 byte-identical
  to PC; X360's alpha byte holds 0 where PC stores 255 (X8-style padding; RGB
  byte-identical) — accepted. OUT_ps3_p2's 5 A8R8G8B8 dirs: 5/5
  pixel-identical. `LockpickBackground` (8×64 A8R8G8B8 = enum 1) and
  `test01.bmp` (1.8/255) are this class.
- **Cube maps** are level-major with faces padded to 32×32 blocks on X360 and
  one 36-B-headered segment of six face chains, each but the last padded to
  128 bytes, on PS3 (`KAPOW_NAZ_FORMAT.md` §4.2): all 660 + 1,200 faces of the
  six-set export are pixel-identical to PC on both consoles, and the files are
  named `faceN_` / `frameN_` like PC (not `segN_`). The six level-0 face
  uploads of 94 cube textures in the D3D9 gameplay captures match file slices
  0…5 in the order +X, −X, +Y, −Y, +Z, −Z. Observed fields of the 36-byte
  header of a 128px DXT1 cube (65976 B ≈ 6×10996; the PC face chain is 10936
  B): u32be `[0, 128 (w), 65976 (total), …, 43748 @+16, 0x800080…]`; byte 13 is
  the mip count, @+8 the data size.
- **Tiny textures.** `carve_texture` accepts streams from 16 B: ~12 textures
  (arrowmore, loadscreen_03, nail, white/gray/black variants, garage02; tiny
  8×32 / 16×24 / solid) exist on ALL platforms, and X360's layer padding
  inflates every stream to ≥ 8192 B. Texture dir sets are byte-for-byte EQUAL
  across the three platforms (1281 = 1281 = 1281).
- **Residuals (X360, accepted):** `ArrowMore` (16×24 DXT1; both parts, same
  bytes): PC==PS3; the X360 8192-B stream tile decodes to a white bar +
  garbage; no crop / linear pitch (4-64) / transposition / rot90/270 of the
  bswapped or raw tile matches PC (best mean 57) — possibly
  partially-initialized padding or an X360-specific UI variant. `SawMillRope`
  1_normal 64×16 ATI2 (best mean 33 @ (2,4) without the half-swap; 4.5 with
  it). `lensflare_donut.bmp` = genuine per-build recompression diff. X360 DXT1
  diffs at mean 1-2 (e.g. brick specmaps) are recompression noise in the X360
  build. The slot-7 specSize map that X360 re-encodes as DXT1 (48 PC/PS3 L8 vs
  31+ X360 DXT1 in Part 1) is written from its red channel.
- **Residuals (PS3, accepted):** `floor_sidewalk_curb_01` 3_specSize 32×512 L8
  differs from PC (not a permutation — histograms differ; the other 47/48 L8
  are byte-identical). PS3 stores DXT5 where PC has ATI2 normal maps: 574
  (Part 2) / 674 (Part 1) layers are not identical to PC and are within a mean
  of 8 (a small encoder difference), no PS3 layer is off by more.
- **Legacy materials** (`--materials legacy`, `roughnessGen.png`): PS3/X360
  differ from PC on flat-exponent dirs where the PC carve wrote NO `spec.txt`
  but the consoles read `$specularData` (e.g. crowbar expScale 26.95) — the
  console bake is the better-informed one.
- **Stride-walk fallback on console** (`_stride_layers`, `_is_normal_layer(order)`,
  `texture_layer_label(order)`, `_console_recover_layers`; reached 0 times on
  the four console sets): console header records pack the fields at shifted
  offsets (dims u32be @+6/+10 (>>8), format enum byte @+16, mip count u32be
  @+26, records of 30 bytes after the 9 salt-props @196). `_is_normal_layer` is
  format-agnostic, not `enum==9 → normal`: enum 9/10 = normal, and on console a non-idx0 DXT5 (enum 7)
  = normal (enum 7 only appears as diffuse at idx0 on PC; spec/glow are always
  DXT1/L8). The specSize record is preceded by an extra 4-byte field — the
  presence bytes of the empty slots in front of slot 7 — on EVERY platform
  (45/45 specSize records, 0/39 true-glow records; PC+PS3+X360 audit), so the
  walk tags it `drift` and labels it specSize regardless of codec. The
  recovery of trailing records dropped under drift: PS3 via its exact segment
  sizes (271/271 bordello textures match the PC layer count); X360 via
  byte-scan + exact-fill validation (265/271; the 6 misses are 4-layer
  textures whose 4th L8 specSize map is not recovered). A record recovered by
  byte-scan loses the drift context, and the last-recovered-record heuristic
  is unsafe (PS3 ground truth: 24 recovered trailing layers are true glow, 20
  are L8 specSize), so ~20 recovery-path X360 textures keep a `*_glow_*` /
  missing 4th layer in that path, and an X360 L8 specSize re-encoded as DXT1
  (the glow enum) is written `3_glow_*` unless the drift tag marks it. The bi-endian rule: every console-touched decoder is
  `order`-aware; the hardcoded-LE `struct` reads are PC-only paths
  (`decode_audio`/`decode_sfx` Vorbis+ADPCM, `_carve_texture_legacy`,
  `_valid_rec`'s `<` branch).
- **Ruled out.** (a) "X360 ships normals compressed with a different BC5
  encoder than PC" (diffuse 82/90 byte-identical, specMap 38/52, normal median
  angular ~9.6° concentrated in R/G, Z ~0.3, on 90 shared bordello textures):
  the PC side of that comparison was decoded with X and Y swapped and the
  console side was not — on the same maps the mixed-partials test gives
  0.17 / 0.57 (as written / swapped) for the PC PNGs and 0.78 / 0.15 for the
  X360 and PS3 ones, and a divergence concentrated in R/G with matching means
  is what a transposed map shows [inferred]. With the Y-first decoder the
  remaining differences are the PS3 DXT5 re-encodes above. (b) "X360 cube
  faces 1-5 use Xenos cube/array addressing, not expressible as
  `_xg2d(X0+x, Y0+y, W)` for any W≤512, origin or flip" (6 `*_cubemap.bmp`,
  e.g. `01_TWM_Atrium_01_a`, 64×64 DXT1, 6 faces × 24576 B; face 0 exact,
  face 1's swizzle shaped like face 0's but shifted): the faces are level-major
  with 32×32-block padding, and all faces decode. (c) "Extra X360-only UI
  textures": the ~12 tiny textures above exist on all platforms. (d)
  "Dominatrix missing hair on X360": the `all` library Dominatrix has no hair
  geometry on either platform (Girl_Head_White = 3 submeshes skin/eyes/eyebrow,
  identical PC↔X360; textures all resolve); the per-variant cast with hair
  comes from `watchmen characters`; `all` builds the 3 minimal library
  characters (Gimp2/Rorschach/Dominatrix).

Comparing against a reference export made with another PIL/zlib: PNG BYTES
differ (md5 is useless) but PIXELS are what count — compare decoded pixels,
not file hashes. Loose-music stems of an extract made one level up carry a
`derived_pc/` prefix, PS3 standalone music the naz-internal `derived_ps3/`
prefix (cosmetic).

### 14.4 Models and characters

Console model streams: `KAPOW_NAZ_FORMAT.md` §6b "Console streams" (strides 32
/ 44 / 16 / 28, packed 11-11-10 normals `_dec1110`, colour byte order per
console, skinned joints `D3DCOLOR` u32 @+32 BE → joint quad bytes [33,34,35,32],
weights BE half4 @+36 — verified 1148/1148 skin (joint, weight) sets == PC on
Rorschach_Dry).

The rig pipeline is byte-order aware end-to-end, so `watchmen.py all` builds
binds + character GLBs on X360/PS3: `parse_model_nodes.parse` and
`extract_skeletons._ordered_names` take `order` (auto-detect);
`char_lib.load_parts` detects the model order; `rig_glb.decode_skin(order=">")`
reads the console 44-byte skinned vertex; `watchmenlib.block_order()` gates
behaviour. Verified vs PC: X360 binds bit-IDENTICAL on all 7 skeletons (Rb/tb
max-diff 0.0); X360 Rorschach character parts 11/11 with matching materials,
vertex positions ≤0.0005, skin 100 % match; a full rigged X360 GLB builds (64
joints, 11 prims, 9 embedded textures, 1 MB). Gimp2: 8/8 parts.

Animation clips: `bake_v4.walk`/`bake` are order-aware (`_detect_clip_order`;
f4/i2 dtypes + struct reads flipped for BE). Console `.animation` clips decode
to tracks BIT-IDENTICAL to PC (max quat diff 0.0 on BS2_COM_MOV_idle_taunt_A,
47/47 tracks). The X360 character library GLB builds end-to-end: `build_lib` →
11 parts / 64 joints / N animated clips / embedded textures.

## 15. Part 1 console extraction + 3-way audit

Sources: PS3 `ps3/…/USRDIR/p1/game.naz` (64 naz entries), X360 loose tree
`xbla/…Part I…/5841096E/000D0000/derived_x360` (44 loose entries; the 239
`precompiled_shaders/*.bin` are not assets), PC `part1_pc/Watchmen/derived_pc`.
Identical topline stats on ALL THREE: **8 block pairs, 13802 block assets,
1990 texture carves, 1115 model jobs (790 unique .obj), 5898 audio**.

**Parity scorecard (P1):**

| category                   | pc / ps3 / x360    | set diffs |
|----------------------------|--------------------|-----------|
| extracted assets           | 8614 each          | 0 (P2 had 2 case-renames; P1 has none) |
| lossless JSONs             | 1165 each          | 0 |
| texture dirs (w/ png)      | 1154 each          | 0 |
| models (.obj)              | 790 each           | 0 |
| audio stems (normalized)   | 4085 each          | 0 |
| music tracks               | 13 each            | 0 |

Audio-stem normalization: console SFX are written `name.wav.wav` because WM06
P1 sound asset names already end in `.wav` and `decode_sfx_console` appends
unconditionally (cosmetic; PC keeps `name.wav`); PS3 standalone music carries
the naz-internal `derived_ps3/` prefix. Music: PS3 13/13 wavs within ±0.6 s of
PC; X360 music durations under vgmstream: §14.2.

Pixel-level audit against the PC reference: 47/48 L8, 6/6 32bpp, 60/60 random
sample vs PS3. Both Part 1 console sets export 80 character GLBs with piece
lists equal to PC.

**P1 console character binds — identical.** `watchmen.py binds` on the PS3 p1 naz
and the X360 derived_x360 loose tree produces all 5 P1 skeleton binds (large,
medium, nto, rsh, small) numerically IDENTICAL to PC (every npz key
array_equal, all three platforms; runs in <45 s per platform).

## 16. Reconstructed content and export fixes

- **Dominatrix_3 (a cut character, reconstructed).** Dominatrix_2 minus its
  gogo hair, the Twilight Lady hair submesh grafted (from `BS2_WithoutWeapon`,
  material `TwilightLadyHair` — no standalone hair model exists), a
  brown-tinted hair texture (median brown [87,52,27] sampled from
  `FimaleGimpMask1`, luminance detail + alpha cutout preserved), and the body
  skin `FemaleSkinBody_Dominatrix1` (Dominatrix_3 ONLY). Wired into `watchmen
  characters` via `characters_export.py`: `SYNTH_VARIANTS`,
  `_brown_hair_layers`, `discover()` injection, `export()` graft,
  `TEX_OVERRIDES`. `WATCHMEN_NO_SYNTH=1` turns reconstructed content off.
- **Gimp3-6 do NOT exist as characters.** Only Gimp1-2 (`Gimp.fragment`) and
  Gimp7-11 (`GimpGagBall.fragment`) have model combos; Gimp3-6 are name-only
  entries in the `AllBodelloTypes` speak roster — no models/textures/spawns, no
  prerelease art. Left unbuilt.
- **Degenerate-UV → black-quad fix.** Normal-mapped faces with a collapsed
  (zero-area) UV triangle get a NaN tangent and render pure black (visible on
  the hair crown). `variant_glb._sanitize_uv_tangents` splits such faces (dup
  verts, spread UVs ~1.5 texel); gated on normal-mapped materials. Runs for
  EVERY GLB (`write_glb`), so `characters`/`charlibs`/`faces`/`--glb` all get
  it. Full cast: 72 parts / 2236 degenerate faces, all fixed, 0 regressions.
- **Rorschach decal spots** (`rorschachspots01/02`) decode BIT-IDENTICAL
  X360↔PC (§5).
- **CLI help.** Every subcommand has a usage line + `-h`; a bare/short
  subcommand prints usage instead of a traceback.
