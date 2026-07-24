# Watchmen: The End Is Nigh, Part 2 — Asset Extraction · MASTER SUMMARY & HANDOFF

Single source of truth for the project. Goal: a **pure-Python, fully static**
extractor that turns `game.naz` into proper **models, textures, and sounds**
(descending priority) with **no** running the game, debugging the exe, dumping
memory, or NinjaRipper. Engine = **Kapow** (Deadline Games, codename WM07), a
32-bit D3D9 title.

> If you only read one doc, read this. `docs/INDEX.md` lists the others.

---
## 0. Quick status board

| Subsystem | Status | Notes |
|---|---|---|
| `.naz` archive → blocks | ✅ solved & verified | obfuscated ZIP; 2291 assets, 0 mismatch |
| block → asset (header+stream) | ✅ solved & verified | `extract_block(header, RAW block_s_z)` |
| Asset property-bag header format | ✅ characterized | typed, name-HASHED records (config) |
| **Texture header → name/format/layers** | ✅ **SOLVED & verified** | `parse_texture_header()`; 100% exact name+format+layers, all 186 |
| **Models — geometry → OBJ/FBX/STL** | ✅ **deterministic, multi-submesh** (640/642) | `wlib/watchmen_extract.py`; header submesh descriptors + IB-validated carve; OBJ submesh groups; see §5 below |
| **Models — collision mesh / full byte-faithful parse** | ◻️ mapped, not extracted | ~19% of stream is collision volumes (excluded from render); skeleton parse pending |
| **Models — skin weights** | ✅ **decoded** (4×u8 idx @+44, 4×half wt @+48, Σ=1) | rigged FBX still needs skeleton+keyframes from the `.ani` asset; see §5 below |
| **Animation / skeleton (`.animation`)** | ⚠️ **mapped** — skeleton extracted (428/428), keyframe format decoded | bone names+fps+frames parse; compact quat/trans tracks mapped; full rigged FBX = assembly step; see `ENGINE_CONSTANTS.md` |
| **Per-variant character glbs** | ✅ 25 glbs, ALL user-QA'd (2026-07-13): header-exact fps, finger-shear dense bakes, d6 jiggle default, face attaches incl. NiteOwl cowl + Heavies_Head_1, BipNN name fixes | `watchmen.py characters 20260708 20260708/characters`; current state + engine truths in `docs/ENGINE_CONSTANTS.md` |
| **Toolkit layout + one-command run** | ✅ `wlib/` next to `watchmen.py` (canonical lib); `python3 watchmen.py all game.naz OUT` = extract → binds → character glbs | see the README §Quick start |
| **Fresh-install clean-room run** | ✅ **verified** (2026-07-08c) | binds bit-identical + character glb numerically identical from game.naz alone; `watchmen.py extract/binds` |
| **Character BIND (rest pose → skinning palettes)** | ✅ **SOLVED, FILE-ONLY, engine-exact** (2026-07-08, all 7 skeletons) | node records store [pos][quat XYZW] BEFORE the name (old parser off-by-one); bind Rb = conj-quat FK, tb = FK(Rb, node locals); palette order = bone list rotated by one. `wlib/build_bind_file.py`, `wl.ensure_binds()`, see `docs/ENGINE_CONSTANTS.md` |
| Vertex normal packing | ✅ solved | HALF4 (3×f16) at vertex+12 |
| **Textures — format enum** | ✅ solved (Ghidra) | enum→D3DFORMAT table @0xc799e0 |
| **Texture → stream binding** | ✅ **SOLVED, deterministic** (1190/1190, no search) | (off,sz) is a per-asset TRAILER; +1 shift. See §6 below |
| **Textures — pixel decode** | ✅ **COMPLETE — 1190/1190** stream-exact | `plan_texture_layers()` tiles every stream as single / cube×6 / animN; multi-layer diffuse+BC5 normal+spec all decode; see §6 below |
| **Audio — SFX (`sound`)** | ✅ **COMPLETE — 848/848** → WAV | `wlib/watchmen_extract.py`; format tag @+10 selects MS-ADPCM (98%) / PCM (2%); mono+stereo; see §7 below |
| **Audio — music (`.mediastream_s`)** | ✅ **13/13 → Ogg Vorbis** | `naz_sound_extract.py game.naz` / `watchmen_extract.py` |
| **Determinism** | textures+archive ✅ verified reproducible; meshes+SFX empirical/blocked | textures: identical manifest + byte-identical PNG across runs |
| Full-binary decompile corpus | ✅ available | `ghidra_kapow_out\` (14,910 funcs) |

---
## 0.5 Session changelog — 2026-07-16 (before PS3 pass)

All changes below are on disk (`wlib/`, `watchmen.py`) and verified. **PS3 is the
next target; it is big-endian like X360, and every decoder touched this session is
already byte-order aware, so these carry over.**

- **Dominatrix_3 reconstruction (fabricated cut character).** Cloned Dominatrix_2
  minus its gogo hair, grafted the Twilight Lady hair submesh (from
  `BS2_WithoutWeapon`, material `TwilightLadyHair` — no standalone hair model
  exists), fabricated a brown-tinted hair texture (median brown [87,52,27] sampled
  from `FimaleGimpMask1`, luminance detail + alpha cutout preserved), and swapped
  the body skin to `FemaleSkinBody_Dominatrix1` (Dominatrix_3 ONLY). Wired into
  `watchmen.py characters` via `characters_export.py`: `SYNTH_VARIANTS`,
  `_brown_hair_layers`, `discover()` injection, `export()` graft, `TEX_OVERRIDES`.
  A `characters` run now emits `Dominatrix_3`.
- **Degenerate-UV → black-quad fix (general).** Normal-mapped faces with a
  collapsed (zero-area) UV triangle get a NaN tangent and render pure black (was
  visible on the hair crown). `variant_glb._sanitize_uv_tangents` splits such
  faces (dup verts, spread UVs ~1.5 texel); gated on normal-mapped materials.
  Runs for EVERY glb (`write_glb`), so `characters`/`charlibs`/`faces`/`--glb` all
  get it. Full cast had 72 parts / 2236 degenerate faces → all fixed, 0 regressions.
- **Binds no longer need the naz.** `ensure_binds(..., extract_dir=)` builds each
  skeleton bind from the `.model` header already in `<out>/extracted` (bit-identical
  to the naz-built bind). `all`, `charlibs`, `characters` all pass it — so after a
  completed extract, `characters` needs NO naz (it's a pure fallback now).
- **`watchmen.py` CLI help.** Every subcommand has a usage line + `-h`; a bare/short
  subcommand prints clean usage instead of an IndexError traceback.
- **X360 `--keep-xma` is now DEFAULT.** `_emit_audio` always keeps `.xma`; `.wav`
  only when `--vgmstream-cli` is given. `--keep-xma` flag now only also-keeps PS3
  `.mp3`. (Short X360 SFX still silent in vgmstream r2117 — data is byte-valid.)
- **Rorschach decal spots** (`rorschachspots01/02`) now decode BIT-IDENTICAL X360↔PC
  (the clean-IB VB search resolved the old drift). Doc note was stale; corrected.
- **X360 textures — thin block-compressed FIXED, cubemaps DEFERRED.** See §14:
  `_xg2d` is already the exact `XGAddress2DTiledOffset`. Thin wide-short block
  textures fixed byte-exact via `_thin_mip_yoff` (2 textures, 0 regressions). Cube
  faces 1-5 PROVEN to need Xenos cube/array addressing (not plain XGAddress) —
  deferred; face 0 exact. One linear (A8R8G8B8) minigame bg still off.
- **Gimp3-6 do NOT exist as characters** (user asked). Only Gimp1-2 (`Gimp.fragment`)
  and Gimp7-11 (`GimpGagBall.fragment`) have model combos; Gimp3-6 are name-only
  entries in the `AllBodelloTypes` speak roster — no models/textures/spawns, no
  prerelease art. Left unbuilt.

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
artifact.

**Code + docs** — this repository: `wlib/` (library), `watchmen.py` (CLI),
`docs/` (this record).
---
## 2. The `.naz` archive  (✅ verified vs engine + round-trip)
- `.naz` is an **obfuscated ZIP**:
  - EOCD magic `0x16ED5B50`, central-dir entry magic `0x0406F370`.
  - Filenames are **rotate-left-2** per byte: `b = (b>>6)|(b<<2)`.
  - NAZ central-dir fields are shifted **8 bytes** vs standard ZIP (engine does
    `if (NAZ) ptr -= 8`).
- Inside, level data is packaged as **blocks**: a `block_h_z` (all per-asset HEADERS)
  and a `block_s_z` (all per-asset STREAMS). See `KAPOW_NAZ_FORMAT.md`.

## 3. Block format  (✅ verified, 2291 assets, 0 mismatch)
- `block_h_z` decompresses (or is read raw — it parses either way) to the header
  block: a TOC + the per-asset header blobs (each blob itself zlib-compressed).
- TOC fields: `TABLES_SIZE @332`, `NUM_TABLES @352`, entries start ~`399`. Each TOC
  entry: `flag`, 6 stream `(offset,size)` pairs, 6 `variants` (header sizes), an
  `unknown`, then a length-prefixed name.
- **`block_s_z` is a CONCATENATION of per-asset zlib substreams.** Each asset's
  stream = `inflate(block_s_z[offset : offset+size])` using the TOC pair.
- **Correct entry point:** `watchmen_extract.extract_block(decompressed_header_block,
  RAW block_s_z)`. ⚠️ Do **not** `zlib.decompress` the whole `block_s_z` first — that
  returns only the first substream and silently truncates everything (the bug that
  caused much earlier confusion). See `KAPOW_NAZ_FORMAT.md`.
- Header→stream pairing is correct (proven: FemaleSkinBody_Black → stream offset 0 →
  inflates to 87400 B == the running game's GPU copy, byte-for-byte).

## 4. Asset header = property bag  (✅ characterized)
Each per-asset header (the inflated TOC blob) is a serialized **property bag**:
```
+0  u32 typeNameLen          (e.g. 7 = "Texture", 8 = "ModelRes")
+4  char[len] typeName
+.. u32 propCount
+.. propCount typed records
```
Record (typical scalar) = `[typeGUID u32][nameHash u64][typeTag u32][value]` (20 B for
a scalar). **Property names are name-HASHED at runtime** (no plaintext), and values
are config (LOD distances, scales, flags) — NOT geometry. The header is read
**sequentially as a stream** by the engine (see §8 primitives), so sub-structures
(like the texture image descriptor) sit at positions determined by the preceding
records. Full notes: §4 below.

---
## 5. MODELS  (float-VB ✅ · stride-16 ⚠️)
- Geometry lives in the **stream**, read by `ModelResDerivedIO::Read @ ~0x542541`:
  `[count][element-table (count×u32)][flags][bbox vec3 min/max][blobSize][blob]`.
  Stream primitives: `ReadU32 = 0x435459`, `ReadByte = 0x4353E9`. CVarList = 24-bit
  count + 8-bit flags (the `& 0xFFFFFF` seen everywhere).
- **Vertex normal = HALF4** (3× float16 + pad) at `vertex+12`, little-endian.
  Validated (unit_box 24/24; body 0.976).
- **Two vertex formats:**
  - *Compact float VB* (stride 44/56) → **fully decodes to OBJ** today
    (`watchmen_extract.decode_model`, IB-validated VB pick + tri gate).
  - *Stride-16 "baked" env meshes* → int16 positions normalized to a per-mesh bbox,
    packed normal/uv in trailing int16s. **Not fully decodable from `.naz` yet**: the
    extracted asset is missing the **index buffer** and the **bbox** (the engine
    dequant runs at GPU-upload time via a runtime vtable). Point-cloud shape is
    recoverable; a usable mesh is not. NinjaRipper capture is the only
    complete path for these right now. **Next:** read the exact
    `ModelResDerivedIO::Read` record layout in `ghidra_kapow_out\` to find whether
    the IB/bbox are in the stream just outside the current slice. See
    §5 below.

## 6. TEXTURES  (format ✅ · extractor ~39/186 ⚠️)
**Texel data:** raw DXT/BC mip chain, top level first, **no per-stream header**
(starts directly with DXT block bytes; verified byte-exact vs GPU).

**Format enum table** — executable `@ VA 0xc799e0` (`formatTable[enum]`):
```
0 X8R8G8B8(4bpp)  1 A8R8G8B8(4bpp)  2 A8R8G8B8  3 L8(1bpp)  4 L8
5 DXT1(8B/blk)    6 DXT3(16B/blk)   7 DXT5(16B/blk)   9 ATI2/BC5(16B/blk, normals)
11-15 HDR/16-bit
```
Found via `cmp eax,'DXT1'/'DXT5'` @0x455695/0x4556a3 + `[0xc799e0+enum*4]`.

**In-memory texture struct:** `+4 width, +8 height, +0xc format-enum, +0x40 mipcount`.

**Mip-drop on load** (`FUN_005291f9` + `FUN_00453d4b`):
`mipCalc(x)=bit_length(x-1)`; `if (W>256 && H>256) drop = bit_length(min(W,H)-1)-8;
else drop=0`. Loaded size = `(W>>drop, H>>drop)` (smaller side caps ~256). Explains
why authored vs stored vs dump sizes differ.

### Header structure — ✅ FULLY CRACKED 2026-06-24  (`watchmen_extract.parse_texture_header`)
The `.header` (block_h_z) of a `Texture` asset, little-endian:
```
+0    u32  typeNameLen (=8, "Texture\0")
+4    char[8] "Texture\0"
+12   u32  classId/version (always 0x2D = 45)
+16   9 x 20-byte PROPERTY records  (the generic property bag, fixed 180 B):
          [salt u32][nameHashLo u32][nameHashHi u32][typeTag u32][value u32]
      `salt` = per-asset constant repeated on every record (the alignment oracle
      that proved the 20-byte record size). 9 records ⇒ descriptor begins at 196.
+196  IMAGE-DESCRIPTOR ARRAY: one 30-byte record per stored sub-image
          +4  u32  authoredWidth  * 256   (use >>8; low byte carries a flag)
          +8  u32  authoredHeight * 256   (use >>8)
          +13 u8   FORMAT ENUM            (5=DXT1 6=DXT3 7=DXT5 9=ATI2/BC5 0-4 linear)
          +26 u8   authored mip count = log2(max(authoredW,authoredH))+1
      Array ends when +13 isn't a valid enum / +26 ∉ 1..13; then a length-prefixed
      source path "/data/.../<name>.bmp".
```
**100% exact & verified on all 186 bordello textures:** asset NAME, per-image
FORMAT, image COUNT, and LAYER structure. Most textures are **multi-layer
materials** (73 single · 10×2 · 98×3 · 5×4 images) = diffuse(DXT1) + normal(ATI2/
BC5) + specular(DXT1). Authored dims verified vs GPU: FemaleSkinBody authored
512×1024 → 1 mip-drop → **256×512 DXT1 = the byte-exact GPU copy**.

### ⚠️ The remaining wall — STORED resolution is NOT in the header
The header carries the **authored** texture; the stream stores a **runtime-reduced**
copy whose resolution is recorded **nowhere in the header**. Proof: `MansionDoor_01`,
`Mansion_wood_01`, `Mansion_plaster_03` have **byte-identical** 512/512/512
descriptors yet streams of **11632 / 101244 / 9418** bytes. So stored dims must be
recovered from the **stream length**:
- **Single image:** length + (authoritative) format + authored aspect + decode
  coherence → solved. **33/64 single textures decode** (incl. 15 cubemaps, which
  store `6 × face-chain`). FemaleSkinBody reproduces the GPU ground truth.
- **Multi-image (the bulk):** the concatenated stream does **not** split at simple
  per-layer pow2 mip-chain boundaries — 62/112 have **no** aspect-consistent
  summing combo at all ⇒ the layout is mip-interleaved / array-packed / padded.
  The function that knows it is the **texture stream reader** in
  `texturebuffer_dx9.cpp` (≈0x45b961 / 0x45bc5f) — but those functions
  **decompiled to stubs** in `ghidra_kapow_out` (Ghidra bailed; they all forward to
  the SEH stub `FUN_00991850`). **To finish multi-image we need a clean re-decompile
  of those specific functions** (targeted `KapowDecompExport.java` seeded on
  `45b961,45bc5f,5291f9,45413e,4540d7` + string anchor `"texturebuffer_dx9"`),
  **or** the `KapowMulti.DMP` as a per-layer dims oracle.

### Extractor (texture path in `wlib/watchmen_extract.py`, rewritten 2026-06-24)
Uses `parse_texture_header` → always writes a `<name>.txt` sidecar with exact
name/format/layers, decodes single-image + cubemaps to PNG, best-effort carves
multi-image (shared-size + coherence). 
Engine evidence: §14 below and the texture section of this document.

## 7. AUDIO  (◻️ partial)
libVorbis + Bink + libpng/zlib present. `watchmen_extract.decode_audio` exists
(Ogg/Vorbis path with CRC + lacing). Not the focus yet; same property-bag reader
(§8) will help once found.

---
## 8. Engine serialization primitives (StreamBuffer)
`ReadU32 = 0x435459 · ReadVec4 = 0x4354a8 · ReadVec3 = 0x43552a · ReadFloat = 0x435494
· ReadBool/Byte = 0x4353e9`. The header/stream are read sequentially with these.
Sheet deserializers `FUN_00529a1a` / `FUN_0052e011` show the pattern
(width→this+4, height→this+8 via ReadU32, etc.).

---
## 8.5 Stub recovery — SOLVED (`KapowDecompDeep.java`, deep3 export 2026-06-24)
Ghidra mis-flagged the MSVC SEH frame-setup helper `FUN_00991850` as **noreturn**,
which truncated every SEH-using function to a ~14-byte stub (`{ FUN_00991850(); }`).
`KapowDecompDeep.java` fixes this: (1) clear the bad noreturn flag; (2) for each
truncated function, **re-disassemble the terminal call** (now that the callee
returns, the call regains its fallthrough + continuation and the decompiler stops
truncating), then recompute the body in place (`recomputeBody`, version-stable APIs,
non-destructive). Result: **`FUN_005351f6` 14 → 2215 B, `FUN_0045b961` 10 → 577 B,
5014 bodies regrown, only 200 disasm-fallback left.** Best run also disabled the
"Non-Returning Functions - Discovered" analyzer + enabled Decompiler Parameter ID.
The recovered `ghidra_kapow_out\deep3\` is now the corpus to use for textures/audio.

What the recovered texture loader (`FUN_005351f6`, texturesheet upload) shows:
- A **Texture is a multi-slot MATERIAL**: layer pointers at object `+0xe0/+0xe4/+0xe8/
  +0xec/+0xf0` (diffuse/normal/spec/…); each built as a **MutableTextureBuffer**
  (`FUN_0043a183`) and uploaded as a 0x20-byte image element (`FUN_0053508e` append).
- **Mip-drop is CONDITIONAL** on the runtime quality global `DAT_00e1563c` and applied
  **per layer** at GPU-upload (`FUN_005291f9`) — confirming the block stores a
  quality-scaled copy, not authored full-res. (Bordello env textures compress ~14×,
  i.e. low-entropy reduced mips; full-res likely lives in other `.naz` blocks.)
- Per-layer texel data + dims are filled UPSTREAM by the asset deserializer into those
  slots; tracing that (now decompiled cleanly in deep3) gives the exact per-layer
  stored sizes → finishes multi-image carving. Also: scan ALL game.naz blocks for the
  highest-res copy of each texture.

### Dump cross-check — KEY FINDING (2026-06-24, memory dump + GPU DDS ground truth)
Worked backwards from `KapowMulti.DMP` (parsed MDMP, built VA→file-offset map from the
Memory64List; 1861 ranges / 1681 MB). Results:
- **Single-layer `.naz` == GPU, byte-exact** (FemaleSkinBody DXT1 256×512 found verbatim
  in the dump at VA 0x2bf35020). In-memory surface descriptor = `[4CC 'DXT1'][..][w][h]
  [..][texel ptr]` (e.g. 'DXT1' at ptr−60, dims at ptr−52/−48, mipcount at ptr−72).
- **The user supplied GPU ground truth** for a 4-layer material (Gimp_BondageGear): the
  dumped surfaces are **uncompressed 32-bit BGRA**, full-res — diffuse 256², normal 512²,
  spec 256², reflection 256².
- **The multi-layer `.naz` streams do NOT contain these:** Gimp_BondageGear1 (watchmenpart2
  block) binds to a single 174800-byte stream (all 6 TOC pairs identical → binding is
  correct), but it decodes to a *coherent different texture*, not the gear. The GPU 512²
  normal alone (>256 KB) **cannot fit** the 174800-byte stream. No block (raw or inflated)
  contains the GPU bytes verbatim. Several multi-layer streams have **odd byte counts**
  (9418, 33999, 159579) — impossible for pure DXT, so there is in-stream framing.
- **Conclusion:** the dumped textures are a **higher-resolution source** than the shipped
  `.naz` level/general blocks. The dumped game most likely ran the **play-mode / authored
  path** (`.bmp` source → `WrappedCompressSurface`), not these blocks. So the dump is NOT a
  transform-of-the-`.naz`; it is a different (better) source.
- **Therefore the most reliable route to usable, full-res textures is to extract them
  DIRECTLY from the dump** via the surface descriptors (4CC+dims+ptr → decodable DXT/RGBA),
  bypassing the `.naz` multi-layer encoding entirely. The `.naz` multi-layer framing is
  still worth finishing for a dump-free pipeline, but the dump gives game-quality output now.
- Loader (per the engine): `kernel/scenegraph/loadblock.cpp` — async 2-buffer (header +
  stream) streaming system (`FUN_004a36d8`, "Allocating 2 buffers for asset block loading").

### Block layout — CONFIRMED (general vs level blocks)
`game.naz` blocks are nested: `derived_pc/levels/game_levels_part2/`
- **`watchmenpart2.block_h/s_z` = the GENERAL/shared block** (parent level): 1704
  assets, 55 textures — all the global UI/FX (`gray`, `white100`, `ArrowMore`,
  `LightningStrike`, `Spark`), all single-layer.
- **`<level>/<level>.block_h/s_z`** (bordello, nightclub, streetsofriot, playervsplayer,
  tutorial; + `game_levels/mainmenu`) = per-level content, incl. the multi-layer
  material textures. So shared assets live in the parent block, level assets in the level.

### Multi-layer texture stream — still framed (NOT plain concatenated mip chains)
A 3-layer material (e.g. MansionDoor) = one source `.bmp` built into diffuse(DXT1) +
normal(ATI2/BC5) + spec(DXT1), concatenated in ONE stream. BUT: the stream does NOT
split into 3 plain mip chains (0 valid (w,h) solutions even with diffuse==spec), and
several totals are ODD (9418, 33999) — impossible for pure block data. ⇒ there is
**per-layer framing** (a small header/size prefix) inside the stream that still needs
decoding (probe the inflated stream directly), OR read it from the asset-stream
deserializer in deep3 (the generic resource reader that binds block_s_z → layers).
Mip-drop (`FUN_005291f9`) is upload-only, so it does NOT size the stored data.

## 9. ▶ NEXT — start here  (the header blocker is SOLVED; one wall remains)
The old "generic property-bag deserializer" blocker is **resolved on the data side**:
`watchmen_extract.parse_texture_header()` parses every Texture header deterministically
(name + per-image format + layers + authored dims). The 9-record property bag is a
fixed 180-byte prefix; the image descriptor follows at offset 196 (see §6).

**The one remaining wall = multi-image STORED-stream layout.** The header gives
authored dims, but the stream stores a runtime-reduced copy and multi-layer materials
(≈60% of textures) don't split at simple pow2 mip-chain boundaries. Two ways through:

A targeted re-decompile (`seeded.c`) **confirmed the architecture** (see
`docs/ENGINE_CONSTANTS.md`): a TextureAsset holds an image array at
`+0x90` (count `*(this+0x94)&0xFFFFFF`, **16 B/image = `[u32 size][void* data]…`**);
`FUN_0048e78f` `memcpy`s each image by that explicit **size** ⇒ the concatenated
stream is split by per-image sizes that are *stored metadata*, not derivable from the
header (proven: identical descriptors → 11632/101244/9418 B; Bordello_Lamp 218488 B
has no valid 3-chain partition). Mip-drop `FUN_005291f9` and the cube path
(`desc[3]==2`, 6 faces) are confirmed.

1. **Recover the stub functions (preferred — `KapowDecompDeep.java`).** ROOT CAUSE
   found 2026-06-24: the texel-split logic lives in functions that Ghidra emitted as
   one-line **stubs** (`FUN_005351f6`, `FUN_0045b961`, `FUN_004540d7`, …). They are
   *not* genuinely undecompilable — Ghidra mis-flagged the SEH frame-setup helper
   `FUN_00991850` as **noreturn**, which truncates all ~700 of its callers. The new
   `KapowDecompDeep.java` (whole-binary) clears that bogus flag (phase 1), re-decompiles
   everything, and falls back to raw disassembly for any residual stub. Run it; the
   recovered `FUN_005351f6` (per-image upload) + the producer that fills
   `TextureAsset+0x90` `[size,ptr]` give the per-image split sizes → multi-image
   byte-exact. (Targeted `KapowDecompExport.java` is also pre-seeded on the texture
   ranges as a smaller alternative.)
2. **Dump oracle.** `KapowMulti.DMP` holds each live surface's W/H/levels (struct +4 W,
   +8 H, +0xc fmt, +0x40 mips). One-time stamp of per-layer stored dims (not dump-free).

---
## 10. How to run things
- Extract textures from a block:
  `python3 -m watchmen extract game.naz OUT`  (or the block pair directly, see §3)
  (keep `watchmen_extract.py` alongside; correct ones land in `out\`, low-confidence
  in `out\uncertain\`).
- Decompile a subsystem (local Ghidra, AFTER auto-analysis): Script Manager →
  `KapowDecompExport.java` → Save → send the `.c`.
- Re-make the whole corpus: `KapowDecompAll.java` (tens of minutes; produced
  `ghidra_kapow_out`).

## 11. Workflow that works (division of labor)
The sandbox can't run Ghidra full-analysis (OOM); the user's local Ghidra can. So:
**user runs Ghidra exporters locally → sends `.c`/corpus → Claude writes the Python
parser**. This is the loop that produced every recent win and is how to finish.

## 12. Gotchas
- Sandbox **mount intermittently serves truncated/corrupted file copies** to bash
  (host/editor files are fine). If a script errors on a line that looks correct, it's
  the mount — retry, or run locally.
- Analysis of engine CODE requires an executable whose `.text` is not
  encrypted; the retail build's is SecuROM-packed in place. The toolkit does
  not unpack it and does not need it for anything except `gendata regdump`.
- `block_s_z` = concatenated zlib substreams; never bulk-decompress it (see §3).
- Property names are runtime-hashed — locate loaders by call/primitive patterns, not
  by grepping names.
- TOD (Tale of Despereaux) reverse-engineering tools are NOT 1:1 with Watchmen — the
  Kapow build differs (property-serialized headers vs TOD's fixed structs).

## 13. Watchmen **Part 1** support (2026-07-13)
Part 1 (`part1_pc/Watchmen/`) runs through the **same pipeline** — the block,
kapow, fragment, texture, model, and audio formats are **byte-identical** to
Part 2. The only difference is **packaging**: Part 1 ships the asset containers
**loose on disk** under `derived_pc/` (`*.block_h_z`/`*.block_s_z`,
`*.texture_*_z`, `*.modelres_*_z`, `*.pivotbook_h_z`, `*.mediastream_s`) instead
of packing them into a `.naz`. Those loose files are byte-for-byte what the
`.naz` stored internally, so every decoder works unchanged.

Enablement: `naz_entries()`/`naz_read()` in `wlib/watchmen_extract.py` now accept
a **directory** as well as a `.naz`. Point any command at the loose tree:

```
python3 watchmen.py extract part1_pc/Watchmen/derived_pc  OUT
```

`loose_entries()` walks the tree, yields the known asset suffixes with `.naz`-style
names (leading `/`, forward slashes → unique stems), and `naz_read` returns loose
files verbatim (`_z` is a naming convention, not naz-level compression). Verified:
Part 1 MainMenu block → 74 assets; full `derived_pc` extract → 304 PNG textures
(diffuse/normal/specular splits), 106 models, 72 lossless JSON, fragments/
sequences/particles/animations, 13 decoded OGG. 8 fully-paired blocks; 4
header-less `.block_s_z` (Prison/Art) are handled gracefully.

Caveat: character-glb/bind commands (`binds`/`charlibs`/`characters`) key on
Part 2 skeleton asset names in `wl._SKEL_ASSETS`; Part 1's cast differs, so those
would need a Part 1 skeleton map before they run. Core extraction is unaffected.

**Part 1 header format difference — SOLVED 2026-07-13 (second pass).** Part 1 is
the WM06 engine: asset-header PROPERTY records are **16 bytes**
(`[salt][hash32][tag][val]`, +4 when tag==2) vs Part 2/WM07's 20 bytes
(`[salt][hashLo][hashHi][tag][val]`). `_prop_walk()` auto-detects the stride by
which one yields more consecutive salt hits — no version flag. The texture
IMAGE records are 30 bytes on BOTH engines with identical field offsets; only
the record-area START shifts. This one difference had broken two things on
Part 1: (a) `parse_texture_header` found zero image records → textures fell to
the legacy coherence-guess carve → grid/stripe/mip garbage (user-reported:
Biker_DenimVest*, Generic_door05, …). Now 1970/1971 Part 1 textures plan
deterministically (1713 single / 201 cube / 56 anim; sole fail =
Floor_Sidewalk_Curb_01). (b) `_propbag_end` walked 20-byte records → wrong
propbag end → `decode_sfx` bailed → **no SFX/dialog** (music was unaffected =
separate loose-file path). Sound field layout after the propbag is byte-
identical to Part 2; sample of 60 Part 1 SFX now decode 60/60. Part 2
regression after the change: bordello 273/273 texture plans, mainmenu 6/6 SFX,
console texture carve unaffected.

**Texture planner hardening (2026-07-13c, prompted by Part 1 field reports).**
Part 1 headers exhibit serializer DRIFT (a record slips a byte, corrupting
dim/mip fields) which produced three failure modes: exploding false "anim"
plans (Mercenary_armor2: bogus 4×4 record → 116,510 tiny PNGs; Caustics01_002:
×60), stolen layer sets, and 1 hard fail. Planner changes in
`plan_texture_layers`: anim counts capped at 64 and tiered — EXACT frame
multiples are accepted before the dropped-layer recovery, LOOSE multiples only
after it; the recovery can now also return a repaired set as an exact frame
multiple (Caustics01_001 = 32 × [16×16 + drifted 128×128]). New
`_rescue_texture_plan` (carve-time, fail path only): full-offset record scan →
record-subsequence + mip brute force to EXACT stream tiling → coherence-scored
pick (solves Floor_Sidewalk_Curb_01's 4-layer drift). Results: Part 1
1971 textures → 1734 single / 201 cube / 35 anim (all ≤×32, legit variants) /
1 drift-rescued. Part 2 bordello: 234 single / 37 cube / 2 anim / 0 fail —
NOTE: Mansion_Floor_Wood_01/02 and Highlight_01 were misplanned as anims since
June (frames 1+ were garbage); they are really [512-set + 1024×1024 L8] and
[32×32 + 128×128] singles (verified by decode coherence: L8 8.8 vs 40.9
garbage). Part 2 texture re-extraction recommended.

**Full-sweep verification (2026-07-13d, autonomous pass):**
- Part 1: all 8 blocks, 1971/1971 textures carve, 0 legacy fallbacks, 0 fails,
  1 drift-rescue (curb), 3581 PNGs; 400-sample coherence scan found ONE outlier
  = NightVision_Raster.BMP, which is a genuine 0/255 scanline overlay (rows
  alternate exactly — correct decode, incoherent by design).
- Part 2: all 7 blocks, 1333/1333 textures carve, 0 fails, 0 legacy;
  1203 single / 112 cube / 18 anim (all counts ≤32). Caustics01_001's repaired
  ×32 plan decodes frame-for-frame IDENTICAL coherence to the visually-QA'd
  Caustics01_001_g — the re-planned textures are confirmed good.
**Stub-diffuse materials are REAL packing (2026-07-13e, user question re
Mercenary_armor2 = 4×4 "diffuse" + 2048×2048 "specMap").** The byte tiling is
exact, and it is not unique: 9 Part 1 textures pack a ≤8×8 layer0 followed by
full-size layers — e.g. RorschachButton = [8×8 DXT1, 32×32 ATI2, 64×64 DXT1]
(the SAME shape ships on X360, so it's authored, not drift), and
KnotTop_RidersTorsoS = [4×4 DXT1 + 256×512 ATI2]. Layer LABELS follow the
engine's shader-slot order (layer0 = $diffuseMap, first colour layer after it
= $specMap), so the 2048 layer lands in the specMap slot — for materials whose
diffuse is a stub, the payload map is the interesting one. Caveat: slot roles
for stub materials are unverified against a render capture; if they matter,
check with apitrace. No code change — packing decode is correct.

**Part 1 `characters` coverage (2026-07-13e, user report: only Rorschach,
NiteOwl, KnotTops exported).** Expected with current code: discovery is driven
by the hardcoded Part 2 cast list `ENEMY_FRAGS` in `characters_export.py`
('Dominatrices','Gimp','GimpGagBall','TwilightLady','Heavies','Thug',
'ThugFast','ThugBig') plus the player models via `MODEL_BIND`
(rorschach→rsh, owl→nto). On Part 1 only the stems that also exist there
matched (Thug* = the KnotTops; players by model name). Part 1 ships only
Medium/Small/Large skeletons (no Female/Gimp), so its whole cast rides the
M/S/L binds that already build file-only. **✅ SHIPPED 2026-07-14:** `characters_export.py` now carries `ENEMY_FRAGS_P1`
(Biker, BikerBig, Cop/Fast/Leader, Mercenary/Fast/Leader, Minion/Fast,
Prisoner/Elite/Fast, ThugLeader — added when the P1 marker fragment exists)
and `CLIP_PREFIX_P1` (per the AnimationClass fragments: Enemy01=EN1 medium;
Enemy03=EN1+EN3 small; EnemyBig=EN1+EN2 large — **'EN2' means gimp on Part 2
but big-enemy on Part 1**, hence the per-platform map). Discovery on Part 1
now yields 19 characters / 80 variants, all on the M/S/L + rsh/nto binds.
Underboss (BS1 clips, no skeleton ref in its fragment) is still not exported.

**CRITICAL bind gotcha (found same pass): Part 1's Medium/Small/Large REST
POSES DIFFER from Part 2's** (same 45 bones; rest quats differ up to 0.65,
positions up to 1 cm — the cast was re-rigged between games; bind Rb diff up
to 1.29). Binds MUST be built from the Part 1 source: pass it as the 3rd arg
(`watchmen.py characters OUT_pc_p1 CHARS_p1 part1_pc/Watchmen/derived_pc`).
`export()` prints a WARNING when the extract looks like Part 1 but naz
doesn't. Any binds/bakes/glbs produced with the default `game.naz` (i.e. the
first user run: Rorschach/NiteOwl/KnotTops) are MIS-BOUND — delete
`OUT_pc_p1/binds`, the characters outdir and its `_bake` and re-run.
End-to-end verified in-sandbox with P1-built binds: Biker exported 10+ variant
glbs (46 joints, 220 EN1 anims + GRIP poses, 24 embedded textures each).

- **--glb on Part 1 — ✅ verified (same pass).** The file-derived rig path
  works on WM06 unchanged (the model-header palette decode is name-scan based,
  not propbag based): 241 skinned Part 1 models → 241 OBJs, 231 glb events
  (170 rigged / 61 static, e.g. Seagull correctly static — no leg bones),
  0 invalid glbs, 0 exceptions. Rorschach/NiteOwl bind to their own 64-joint
  palettes, heads to their own 46. The handful without glbs are props with
  partial skin channels (sewer chains, cables, naked trees, tarps) — mixed
  44/56 submeshes, skipped by design (`len(SKIN_I) != len(subs)`).

## 14. Console (Xbox 360 / PS3) support (2026-07-13)
The consoles ship the **same Kapow format** as PC; the platform differences are
byte order and a few codecs. Dumps in the work dir: `xbla/…/game.naz` (+ loose
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
PC**; PC bordello still auto-picks LITTLE → 2291 (no regression). Console carve
lands 2291 correctly-named assets on disk (fragments/wav/animation/model/bmp).
`naz_entries`/`naz_read` already work on the console nazes with no change.

**What works now:** naz enumeration + **block→named-asset carving on X360/PS3
with zero flags** (the `files/` + `extracted/` raw trees).

**Decoder gaps (per-platform follow-up), in value order:**
1. **Fragments/sequences/JSON — ✅ DONE 2026-07-13.** All four parsers
   (`kapow_fragment`, `kapow_json`, `kapow_props`, `decode_sequence`) take an
   endian prefix: `parse(..., order='<'|'>')` / `to_json(name, data, order=)`,
   with per-format auto-detect when order is omitted (`detect_order()`:
   fragment = chunk-size walk / schema-record scan; sequence & terrain = f32
   version plausibility 0.01–1000; propbag = leading `[namelen][ClassName\0]`
   record). `watchmen_extract` passes `order=BLOCK_ORDER` through. Key hashes
   are unchanged integers once read in the right order, so the pkl key tables
   work as-is. **Verified on the bordello block:** PC regression 433/433 JSON
   byte-identical to the pre-port parser; X360 & PS3 both 433 assets, 0
   exceptions, fragments lossless 333/335 — the 2 failures are the same two
   TNT CharacterAnimation fragments that already fail on PC (not endian).
   174/433 console JSONs are byte-identical to PC; the other 259 differ only
   in genuine per-build values (owner/GUID ids, raw4 hashes), not structure.
2. **Audio — ✅ DONE 2026-07-13.** Console audio fully cracked:
   - **Music (`mediastream_s`)** is the engine's segment-chained stream, not
     the PC Vorbis packet container: `[seg0][link][seg1][link]…[EOF loop-link]`,
     link = `[u32be m][u32be sizes…]` with `m = sum(sizes)+4*(n+1)`, first size
     = next segment length. X360 segments = raw XMA2 2048-byte packets (seg0
     found by bootstrap scan over 2048-aligned candidates); PS3 segments =
     `[32B header][MP3 frames]`, header dword0 = MP3 payload size.
     **PS3 framing update (2026-07-16):** links are NOT emitted after every
     segment — most Part-2 music packs several headered segments back-to-back
     with a multi-entry link only between groups, and `str_p2` pads each
     segment up to a 16-byte boundary.  `_ps3_media_walk` parses record-by-
     record (link OR segment at each offset; exact next offset first, align-16
     fallback).  Verified lossless on all 13 Part-2 music streams: MP3 frame
     walk = 0 junk bytes, durations match PC Vorbis within 0.6 s, and the 3
     streams the old walker handled de-chain byte-identically.
   - **Channels / rate / total samples** come from the block `mediastream`
     asset header (`media_meta_from_header`): after the `.wav\0` path,
     `[u32 totalSamples][u32 channels][u32 rate]` in block order (totalSamples
     verified == XMA frame-count × 512 exactly). The trailing u32 table in that
     header (count then per-segment values) is the seek table.
   - **SFX (`sound` class, inline)**: X360 = codec tag 3, XMA2 packets at
     propbagEnd+30 (`[+4 u16 ch][+14 u32 rate][+18 u32 samples][+22 u32 size]`,
     size % 2048 == 0); PS3 = raw MP3 from the first frame sync after the
     propbag (`decode_sfx_console`). PC keeps the old `decode_sfx` path.
   - **vgmstream is NOT bundled**: `watchmen.py extract NAZ OUT --vgmstream-cli
     PATH` (any platform's vgmstream-cli binary) converts console audio to
     .wav; without the flag, X360 audio is written as playable `.xma`
     (XMA2WAVEFORMATEX RIFF built by `_xma2_riff`) and PS3 as `.mp3`.
   - Verified: menu48 decodes on both consoles to the same 3:33 track
     (X360 XMA 2ch/48k, PS3 MP3 2ch/48k, healthy RMS at 10/50/90%); mainmenu
     SFX 6/6 on both consoles (durations/rates match X360↔PS3; the one odd
     rain_R 9.7s vs L 37.6s is identical on both = genuine asset).
   - Also fixed: `asset_class()` was LE-only (console blocks classified
     everything 'unknown'); now byte-order aware.
   - **X360 SHORT SFX decode to SILENCE — decoder limitation, 2026-07-15.**
     ~46% of X360 SFX wavs (almost all the short `Speaks/` dialog barks) come
     out all-zero. Root cause is NOT the extraction: the inline XMA2 is read
     correctly (codec 3, ch/rate/samples/dsz fields verified; frames present,
     e.g. Dash = 5 packets / 134 frames, structurally identical to audible
     files). The problem is that **short XMA2 streams (≲6 × 2048-byte packets)
     fail to decode in BOTH vgmstream r2117 AND ffmpeg 4.4** ("broken frame:
     channel len > samples_per_frame"); truncating a known-good long stream to
     5 packets also goes silent, and padding the short stream with valid
     warm-up packets does NOT recover it (the short stream's own frames still
     decode to zero). The game's own XMA context decodes them; standalone
     decoders need more. LONG SFX and ALL music decode perfectly. Options for
     later: a newer/patched XMA2 decoder, a proper per-file XMA2 seek-table /
     block-align wrapper, or pooling barks into their parent bank before decode.
     The raw XMA data IS preserved (extractable), so no information is lost.
   - **2026-07-15 update — a COMPLETE working reference set exists:**
     `Watchmen_Part_2_Audio_X360/wave/` (2908 wavs) is a byte-for-byte complete
     set of every X360 inline SFX, converted long ago by an unknown tool, and
     ALL 1583 of my silent files are present there and audible. This PROVES the
     data is decodable and confirms my extraction is byte-correct: the working
     wav for Dash is exactly 53760 samples @ 48000 = the `ns`/`dsz`/5-packet/
     134-frame content I extract. So the silence is purely a vgmstream-VERSION
     decoder bug on short XMA2 — reproduced in bundled r2117, the user's
     vgmstream-win64, AND ffmpeg 4.4, across fmt-0x166 / 'seek'-chunk / legacy
     'XMA2'-chunk containers (every one -> peak 0). The old converter (now
     unidentifiable — bare PCM, no tool metadata) simply had a working short-
     XMA2 decoder. Practical options: (a) USE the `Audio_X360/wave` set as the
     X360 SFX source (complete, flat filenames); (b) find a vgmstream build that
     decodes short XMA2; (c) add a pipeline fallback that copies a matching wav
     from a reference dir when vgmstream returns silence. Music + long SFX
     remain fine through the normal path.
   - **`--keep-xma` flag (2026-07-15, shipped):** `watchmen.py extract NAZ OUT
     --vgmstream-cli PATH --keep-xma` writes the raw container (.xma X360 /
     .mp3 PS3) next to every decoded .wav (via `_emit_audio(keep_container=)`,
     threaded through decode_sfx_console / decode_console_audio). The kept .xma
     is a valid "Microsoft XMA RIFF header" (vgmstream reads it as Xbox Media
     Audio 2 with the right rate/samples), so the short SFX this vgmstream can't
     decode are preserved as re-convertible XMA for a working decoder — nothing
     lost. Verified: keeps both .wav and .xma for audible + silent SFX + music.
   - **X360 audio "garbled" (user report, 2026-07-14) — INVESTIGATED, NOT A
     DATA BUG.** The user's on-disk X360 wavs (2934 files) are all valid PCM,
     identical header format to the working PS3 wavs, with clean audio (no
     clicks/dropouts/noise; ZCR/RMS on par with PS3; sizes comparable). The
     definitive test: decoded X360 menu48 cross-correlates **0.998 at lag 0**
     with the PC-ogg ground truth of the same track — i.e. the X360 extraction
     is byte-correct music. Whatever playback issue was seen is environmental
     (player / codec on the user's machine), not in the extracted data. The XMA
     wrapper (`_xma2_riff`) and segment de-chain are confirmed correct; vgmstream
     decodes them to the right audio. If it recurs, ask which player + try VLC/
     Audacity on a specific file.
3. **Textures — ✅ DONE 2026-07-13** (`carve_texture_console`, auto-routed from
   `carve_texture` when the header only parses BE).
   - **Console header records** pack the same fields at shifted offsets: dims
     u32be @+6/+10 (>>8), format enum byte @+16, mip count u32be @+26 (stride
     30, records still start after the 9 salt-props @196). Console enums
     reflect platform re-encodes (X360 stores L8 spec-size maps as DXT1).
   - **PS3 streams are self-describing:** per-layer `[36-byte header][data]`,
     data size = u32be @ hdr+8; pixel data is byte-identical to PC (a layer may
     carry more mips than PC, e.g. ATI2 stored with its full chain).
   - **X360**: whole stream is 16-bit byte-swapped (GPU 8-in-16) and every mip
     is tiled — `XGAddress2DTiledOffset` reimplemented (`_xg2d`/`_xg_untile`),
     verified BYTE-EXACT vs PC after swap+untile. Per-layer size rule
     (`_x360_layer_bytes`): mips stored individually while min(w,h) ≥ 32
     texels, each padded to 32×32 blocks; all smaller mips share one packed
     32×32-block tail. Bordello: 204/273 streams exact-size, all 273 produce
     PNGs (approx cases still land layer0 correctly at offset 0).
   - **Verified**: 273/273 textures carve on PC, X360 and PS3; layer-0 pixel
     compare on 60 sampled textures ×2 consoles = 114/120 identical to PC.

   **Multi-layer / normal-map fixes (2026-07-14, from user field report:
   X360 missing normals+specs, PS3 normals mislabeled as specMap).** Root cause
   was the console NORMAL format enum. Verified across 20 shared textures the
   enum correspondence **PC 9 (ATI2) → X360 10 → PS3 7**:
   - **X360 enum 10** was not in `TEX_ENUMS`, so `_stride_layers` aborted after
     the diffuse layer → X360 dumped ONLY diffuse for every multi-layer texture.
     Enum 10 is the same 2-channel BC5/ATI2 as PC enum 9 (BC5 decode → clean
     purple normal, coherence 1.3 vs 18.8 as DXT5). Added `TEX_FMT[10]=ATI2`.
   - **Labeling was format-based** (`enum==9 → normal`), so PS3's DXT5-encoded
     normal (enum 7) was labeled specMap and the real spec became glow. New
     `_is_normal_layer(order)` is format-agnostic: enum 9/10 = normal, and on
     console a non-idx0 DXT5 (enum 7) = normal (enum 7 only ever appears as
     diffuse at idx0 on PC; spec/glow are always DXT1/L8). `texture_layer_label`
     takes an `order` arg; console carve passes ">".
   - **PS3 DXT5 normals** are the DXT5nm layout (X→alpha, Y→green, R/B filler);
     `_decode_one_layer(normal=True)` rebuilds (X, Y, Z) → proper purple normal
     matching PC within a bit (126,126,252 vs 127,126,252).
   - **Dropped-layer recovery on console** (`_console_recover_layers`): the
     stride walk drops trailing records under serializer drift (same as PC).
     PS3 recovers via its exact self-describing segment sizes → **271/271
     bordello textures now match PC layer count**. X360 recovers via
     byte-scan + exact-fill validation → 265/271 (the 6 misses are 4-layer
     textures whose 4th L8 specSize map isn't recovered; X360 still gets
     diffuse+normal+specMap). Recovery is conservative — never adds spurious
     layers (0 over-count on either platform).
   - **Pixel-verified** PC≡X360≡PS3 on diffuse/normal/spec for sampled textures
     (dominatrixsuits1, wall_light_02, 2d_noise4 identical). Minor remaining
     cosmetic: X360's drift-recovered specSize layer is labeled "specMap" (the
     grayscale DATA is correct, ~26/26/26 = PC's specSize; only the filename
     tag differs because X360 renumbers that record's enum to DXT1).
   - ~~**Extra X360 assets** (arrowmore, loadscreen_03, nail, white/gray/black
     variants, garage02 — ~12 more than PC) are REAL X360-exclusive UI/loading
     textures~~ **CORRECTED 2026-07-16:** these exist on ALL platforms; PC/PS3
     skipped them because `carve_texture` rejected streams < 256 B (tiny 8×32 /
     16×24 / solid textures; X360 escapes the guard only because its layer
     padding inflates every stream to ≥ 8192 B). Guard lowered to 16 B; all 12
     now carve on PC and PS3 too (texture dir sets are byte-for-byte EQUAL
     across the three platforms: 1281 = 1281 = 1281).

   **specSize / glow / PS3-L8 fixes (2026-07-16, from the PS3 dump sanity
   audit).** Three related texture bugs found and fixed:
   - **PS3 L8 layers were Morton-swizzled garbage.** RSX stores UNCOMPRESSED
     layers (L8 specSize) in Morton/Z-order; DXT layers are linear. The carve
     decoded L8 linearly → scrambled specSize maps (histogram right, pixels
     wrong, corr≈0.03 vs PC) — and every PS3 roughnessGen baked from them was
     equally wrong. New `_rsx_unswizzle` (x from even bits, y from odd,
     non-square pow2 = leftover high bits ride linearly on the wider dim) makes
     all 65 PS3 specSize maps BYTE-IDENTICAL to PC's linear L8.
   - **X360's "glow" at slot 3 is usually specSize.** X360 re-encodes the L8
     specSize map as DXT1 (same enum as glow → mislabeled `3_glow_*`, and
     roughnessGen fell back to flat). File-only discriminator found: the
     specSize record is preceded by an extra 4-byte header field (the +4
     "drift" the stride walk tolerates) on EVERY platform — 45/45 specSize
     records have it, 0/39 true-glow records do (PC+PS3+X360 audit).
     `_stride_layers` now tags `drift`, `texture_layer_label` maps drift →
     specSize regardless of codec. 45 X360 textures relabeled + roughnessGen
     rebaked from the real specSize data.
   - **Known residual (X360 only):** records that arrive via
     `_console_recover_layers` byte-scan lose the drift context, and the
     last-recovered-record heuristic is provably unsafe (PS3 ground truth:
     24 recovered trailing layers are true glow, 20 are L8 specSize). So ~20
     recovery-path X360 textures keep a `*_glow_*`/missing 4th layer. PS3+PC
     are authoritative for specSize; X360's copy is redundant platform data.

   **Cross-platform divergence audit (2026-07-15, user asked to confirm X360 vs
   PC divergence isn't absurd).** Bi-endian audit: every console-touched
   decoder is `order`-aware; the remaining hardcoded-LE `struct` reads are all
   PC-only paths (`decode_audio`/`decode_sfx` Vorbis+ADPCM, `_carve_texture_
   legacy`, `_valid_rec`'s `<` branch). Made `extract_specular` order-aware and
   wired spec.txt into the console carve — **spec exponent/intensity now match
   PC exactly on X360 & PS3** (nightowlbelt 20/0.58, dominatrix 43/1.17).
   Pixel divergence, 90 shared bordello textures, X360 vs PC:
   - **diffuse: 82/90 byte-IDENTICAL** (median mean-abs-diff 0.00); the few
     non-zero are genuine per-build differences.
   - **specMap: 38/52 identical**, p90 mean-abs-diff 1.76 (negligible).
   - **normal: semantically correct but byte-divergent** (median angular ~9.6°,
     concentrated in the R/G channels, Z ~0.3). **Proven NOT a decode bug:** on
     the divergent textures the DIFFUSE is byte-identical (same size/format/
     untile path → untiling & layer offsets are correct), corners match, and no
     spatial block-shift reduces the diff — X360 just ships normals compressed
     with a DIFFERENT BC5 encoder than PC (higher variance, same means). Small
     normals (≤256²) often match to ~2/255; larger ones diverge more. This is
     genuine platform content difference, not a pipeline error.
   Bottom line: divergence is confined to normal-map re-encoding; diffuse, spec
   colour and spec params are near-identical. Not absurd.

   **The 8 non-identical diffuses characterized (2026-07-15; deep-dived 2026-07-16):**
   `_xg2d` IS the exact canonical Xenia `XGAddress2DTiledOffset` (verified bit-for-
   bit); it is byte-EXACT for square / ≥32-block-aligned 2D surfaces. The two
   remaining gaps are NOT the address formula — they are (a) cube-ARRAY slice
   addressing and (b) the D3D9 packed-MIP-TAIL Y-offset. Both proven below using
   PC raw streams as known-plaintext (all X360 blocks are present + byteswap is
   correct, so the data is fully recoverable — only the LAYOUT differs).
   - **6 cubemaps** (`*_cubemap.bmp`, e.g. `01_TWM_Atrium_01_a`, 64×64 DXT1, 6
     faces × 24576 B): FACE 0 byte-perfect (0.00). Faces 1-5: **PROVEN not
     expressible as `_xg2d(X0+x, Y0+y, W)`** for ANY width W≤512, origin (X0,Y0),
     or of the 8 flips/transposes (exhaustive anchored search, 2026-07-16). All
     256 blocks of every face ARE present in the byteswapped stream, but faces
     1-5 use Xenos cube/array addressing (a different function than the 2D
     XGAddress). Face1's swizzle matches face0's SHAPE but shifted (its origin
     lands mid-micro-tile), confirming array-slice interleave. A real fix needs
     the Xenos cube address (XGAddress2DTiledOffset with array-slice bit
     interleaving) — substantial, low payoff (~13 probes, face 0 already right).
   - **Thin block-compressed textures — ✅ FIXED 2026-07-16.** A wide, VERY short
     block surface (spans ≥1 full 32-block macro-tile wide but ≤4 blocks tall)
     stores its base level BELOW the D3D9 packed mip tail. `_xg_untile` now takes
     a `yoff`; `_thin_mip_yoff(kind, we, he)` returns 4 for exactly this class
     (`blk & we≥32 & he≤4`), else 0. Verified BYTE-EXACT (0.00 vs PC) on the only
     two shipped such textures — `FloorCable_BlackPlastic_01` (256×16 = 64×4 blk)
     and `HoneyPot_lightChain_01` (128×4 = 32×1 blk) — and a full sweep of all 45
     aspect-ratio thin textures shows **the fix touches ONLY those two, zero
     regressions** (the other 43 already decoded at row 0 and are unchanged). The
     gate is deliberately tight: no normal texture matches we≥32 & he≤4, so it
     can't misfire. (Offset derived+verified as a constant 4 for this data; the
     general D3D packed-mip-tail 2D corner-packing formula wasn't needed.)
   - **1 linear holdout** (`LockpickBackground`, 8×64 A8R8G8B8 = enum 1, NOT
     block-compressed): still ~77/255 off — a linear-format channel-order/tiling
     nuance (cf. `test01.bmp`), separate from the block-tile path. One minigame
     background; deferred.
   - **test01.bmp** (1.8/255) = effectively identical (linear A8R8G8B8 channel
     nuance). **lensflare_donut.bmp** = genuine per-build recompression diff.
   Net: `_xg_untile`/`_xg2d` are correct for all normal 2D textures. The two
   holdouts (cube array-slice + packed-mip-tail) affect ~14 environment textures
   and are DEFERRED pending a decision on the (large) Xenos-internals effort.
4. **Models — ✅ DONE 2026-07-13.** `find_descriptors`/`_vb_ok`/`decode_model`
   take `order=`; model_jobs carry their block's order (deferred decode).
   Console vertex declarations are SMALLER than PC for the same descriptor G:
   rigid G=5 → 32B (PC 44), skinned G=6 → 44B (PC 56). Console layout:
   pos f32×3 BE @0 · normal packed u32 @12 (LSB-first x:11 y:11 z:10 signed,
   x,y/1023 z/511 — `_dec1110`, solved vs PC half3 ground truth, max 0.13°) ·
   color @16 (X360 ARGB / PS3 RGBA) · uv BE half2 @20 · packed tangents
   @24(+28) · skinned adds joint idx u8×4 @32 + weights BE half4 @36.
   Verified: bordello block 194/194 models decode on PC, X360 AND PS3;
   positions/uvs/faces byte-identical PC↔console (incl. a skinned model
   PC↔PS3), normals within quantization (≤0.13°).

   **Console CHARACTER pipeline (`all` steps 2 & 3) — ✅ DONE 2026-07-15.**
   The rig pipeline is now byte-order aware end-to-end, so `watchmen.py all`
   builds binds + character glbs on X360/PS3 (was: crashed in
   `parse_model_nodes` "no node names"; then temporarily skipped). Ports:
   `parse_model_nodes.parse` and `extract_skeletons._ordered_names` take
   `order` (auto-detect); `char_lib.load_parts` detects model order and threads
   it through find_descriptors / submesh_materials / _vb_ok / _decode_sub / the
   index reads; `rig_glb.decode_skin(order=">")` reads the console 44-byte
   skinned vertex — **BLENDINDICES = D3DCOLOR u32 @+32 BE → joint quad bytes
   [33,34,35,32]; BLENDWEIGHT = BE float16×4 @+36** (brute-forced then verified
   1148/1148 skin (joint,weight) sets == PC on Rorschach_Dry). `watchmenlib.
   block_order()` gates behaviour; `all` no longer skips console.
   **Verified vs PC:** X360 binds bit-IDENTICAL to PC on all 7 skeletons
   (Rb/tb max-diff 0.0 — same game data, just BE); X360 Rorschach char parts
   11/11 with matching materials, vertex positions ≤0.0005, skin 100% match; a
   full rigged X360 glb builds (64 joints, 11 prims, 9 embedded textures, 1 MB).
   (Parts 9/10 = the tiny `rorschachspots01`/`RorschachSpots02` decal submeshes,
   132 verts / 224 tris each. Once flagged as picking a slightly different VB
   offset on one platform; RESOLVED by the clean-IB (`_ib_ok`) VB search —
   verified 2026-07-16 X360 sub9/sub10 decode BIT-IDENTICAL to PC, meanΔ=maxΔ=0.0
   on both. No PS3 dump on hand to re-confirm, but the same code path applies.)
   **Animation clips too (2026-07-15b):** `bake_v4.walk`/`bake` were LE-only and
   crashed `all` step 3 on console (`o>=4` on None — no BE names found). Now
   order-aware (`_detect_clip_order`; f4/i2 dtypes + struct reads flipped for
   BE). Console `.animation` clips decode to tracks BIT-IDENTICAL to PC (max
   quat diff 0.0 on BS2_COM_MOV_idle_taunt_A, 47/47 tracks). Full X360 char
   library glb now builds end-to-end: `build_lib` → 11 parts / 64 joints / N
   animated clips / embedded textures. `watchmen.py all` completes on X360/PS3.
   **Two follow-up X360 char fixes (2026-07-15c, from user render QA):**
   (1) **Order-detection bug** — `char_lib.load_parts` and `decode_model` picked
   `<` whenever the LE descriptor scan found ANY descriptor, but a BE model can
   throw a stray false-positive LE descriptor (X360 GimpBody: LE=1 vs BE=2), so
   those models decoded little-endian and dropped their real submeshes (Gimp
   missing chest+hands). Fixed to compare descriptor COUNTS (pick the order with
   more). Verified: Gimp2 now 8/8 parts; bordello models still 194/194 both
   platforms. (2) **False-positive VB → clean-IB search (2026-07-15d).** On X360
   the VB offset search grabbed a false vbo sitting ~4 BYTES before the real
   one: it passes `_vb_ok` (positions look sane) but its index buffer is ~50%
   repeated-index (degenerate). This hit the Rorschach ink-blot decals (the
   exploded "broken face" — the spots sit on the mask) AND, via the `characters`
   export, the Twilight Lady HAIR submesh of BS2_WithoutWeapon (dropped → bald).
   Fix: new `_ib_ok()` requires the found VB to have a mostly-non-degenerate IB
   (<40% repeated-index), so the search skips the false offset and finds the
   real one 4 bytes on. Threaded into `decode_model`, `char_lib.load_parts`, and
   both `characters_export` attach/head decode loops (which were ALSO still
   LE-hardcoded — now order-aware). This RECOVERS the geometry (better than
   merely skipping): X360 Rorschach spots now vdiff 0.0000 + skin 100% vs PC
   (11/11 parts); Twilight Lady hair present; bordello models 194/194 both
   platforms, no regression.
   **Dominatrix "missing hair" is NOT an X360 bug:** the `all` LIBS Dominatrix
   has no hair geometry on EITHER platform (Girl_Head_White = 3 submeshes
   skin/eyes/eyebrow, identical PC↔X360; textures all resolve). The full
   per-variant cast WITH hair comes from `watchmen.py characters`, same as PC;
   `all` only builds the 3 minimal library chars (Gimp2/Rorschach/Dominatrix).

   The --glb path is FILE-DERIVED as of 2026-07-13:
   joint names/palette order come from each model's own embedded skeleton
   header (`_model_palette`); the retired capture artifacts
   (skeleton_female_biped.json / bundled_clip_*.npz) are no longer read, and
   glbs are emitted in bind pose — engine-exact animated glbs come from
   `watchmen.py characters`. (Bonus: models like Rorschach now rig with
   their own 64-joint palette instead of the female 48-bone template.)

Operational note (recurred 2026-07-13, survives reboots): after editing
`wlib/*.py` from the host side, the Linux-sandbox mount may serve the file
truncated at its PRE-edit byte size (it can heal after some minutes). The
on-disk file is always correct — verify via the editor view. For sandbox
testing, regenerate/patch the `/tmp/wlibx` copy directly instead of copying
from the mount.

## 15. Part 1 console extraction + 3-way audit (2026-07-16, session 2)

All three Part-1 platforms extracted and cross-audited. Sources: PS3
`ps3/…/USRDIR/p1/game.naz` (64 naz entries), X360 loose tree
`xbla/…Part I…/5841096E/000D0000/derived_x360` (44 loose entries; the 239
`precompiled_shaders/*.bin` are not assets), PC `part1_pc/Watchmen/derived_pc`
(OUT_pc_p1 completed this session — it previously held only textures).
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
PC. X360 music: 9/13 wav durations off (short-XMA/chain vgmstream quirk, both
longer AND shorter, e.g. Str_p1 1021 s vs PC 355 s) — raw `.xma` kept, PS3+PC
authoritative (same class as the P2 nit).

**Console texture fixes landed in `wlib/watchmen_extract.py` (this session):**
1. `_texel32_to_pc()` — console uncompressed 32bpp (A8R8G8B8/X8R8G8B8) texel
   byte order. PS3/RSX stores big-endian `A,R,G,B` (decoder assumed PC LE
   `B,G,R,A`); X360 stores PLAIN BE `A,R,G,B` (NOT GPU 8-in-16 swapped), so
   the unconditional `_bswap16` scrambled it to `R,A,B,G`. Both paths now
   reorder to PC layout before the shared decoder. Fixed the 6
   lensflare/lightprojector/lockpick maps per console; PS3 6/6 byte-identical
   to PC after fix. X360 alpha byte holds 0 where PC stores 255 (X8-style
   padding; RGB byte-identical) — accepted.
2. `_x360_packed_offset()` — X360 packed-mip-tail BASE-level offsets,
   generalizing the old `_thin_mip_yoff` hack. Every texture whose pow2-padded
   texel dims aren't both >=32 packs its base level 16 TEXELS in from the tile
   edge along the short axis (x for taller-or-square, y for wider), i.e.
   `16//blk` elements; 4x4-texel single-block layers sit at element (1,0) for
   8-byte blocks / (26,0) for 16-byte blocks. Derived by brute-forcing all 55
   affected sub-32px P1 textures against PC ground truth; after the fix 36
   byte-identical + 17 within DXT-recompression noise (mean<=8). **This bug
   also affects OUT_x360_p2** (the "12 small textures" class) — re-carve is a
   cheap follow-up.
3. Standalone `gray.texture` re-carved via the same path (byte-identical now).

**Residual nits (P1, accepted):**
- PS3 cubemaps: 212 dirs carve only face0 (PC/X360 emit 6 faces; X360 names
  them `segN_`, PC `faceN_` — cosmetic). The PS3 stream is ONE 36B-headered
  segment of 6x10996 B; face0 decodes byte-exact at offset 0 but faces 1-5 sit
  at irregular offsets (13752/30320/44072/54504…) and are NOT byte-exact vs PC
  (recompressed?). Needs the PS3 cube header fields decoding — TODO (~1000
  pngs; also latent in P2).
- PS3 `floor_sidewalk_curb_01` 3_specSize 32x512 L8 differs from PC (not a
  permutation — histograms differ; other 47/48 L8 byte-identical).
- X360 `SawMillRope` 1_normal 64x16 ATI2: no tail offset matches (best mean
  33 @ (2,4)) — wide ATI2 tail special-case unknown.
- X360 `ArrowMore` 16x24 DXT1 differs vs PC/PS3 (PS3==PC; possibly different
  X360 content — no crop of the tile matches).
- roughnessGen: PS3/X360 differ from PC on flat-exponent dirs where the PC
  carve wrote NO spec.txt but consoles read `$specularData` fine (e.g. crowbar
  expScale 26.95) — the CONSOLE bake is the better-informed one; PC-side gap.
- X360 re-encodes PC's L8 specSize as DXT1 (48 PC/PS3 L8 vs 31+ X360 DXT1
  specSize) — P2-known, set-level only.
- X360 DXT1 diffs at mean 1-2 (e.g. brick specmaps): recompression noise in
  the X360 build, not a decode bug.

**Reference-dump caveat (2026-07-16, same day).** OUT_pc_p1 was re-extracted
by the user on the host with `--glb` (178 glb companions) and a different
PIL/zlib than the sandbox — PNG BYTES differ everywhere (md5 useless vs this
reference) but PIXELS are what count: re-certified pixel-level 47/48 L8, 6/6
fixed 32bpp, 60/60 random sample vs PS3. Its loose-music stems carry a
`derived_pc/` prefix (extracted from one level up), same cosmetic class as
PS3's `derived_ps3/`. When auditing against it, compare decoded pixels, not
file hashes.

**Follow-up session (2026-07-16, session 2b): P2 re-carves + ATI2 tail.**
The P1 fixes were applied retroactively to Part 2 and the ATI2 packed-tail
class was solved:
- OUT_x360_p2: 36 affected dirs + standalone gray.texture re-carved →
  34 pixel-identical + 7 recompression-noise vs PC, 1 residual (ArrowMore).
- OUT_ps3_p2: 5 A8R8G8B8 dirs re-carved → 5/5 pixel-identical vs PC.
- **ATI2 (BC5/DXN) packed-tail rule** (extends `_x360_packed_offset`, which now
  returns `(xo, yo, halfswap)`): 16-byte ATI2 tail bases are shape-dependent —
  full-tile-wide thin rows (we>=32, he<=4) sit at y=16 ELEMENTS unswapped
  (HoneyPot_lightChain exact); other non-square shapes use the standard 16-texel
  spot but need the two 8-byte BC4 half-blocks SWAPPED per block (SawMillRope
  4.5, Harley spokes 0.7 — noise-level); square 4x4-block (NeonSign, Huey
  window: exact) and single-block (26,0) layers are unswapped. DXT5 (also 16B)
  needs NO swap (valuearrows exact). Empirical, validated on all 8 known
  instances across P1+P2. After this: P1 X360 small+32bpp = 41 identical +
  19 noise + 1 residual (ArrowMore again).
- **ArrowMore (16x24 DXT1) is a hard residual on X360 (both parts, same
  bytes):** PC==PS3; the X360 8192-B stream tile decodes to a white bar +
  garbage; no crop / linear pitch (4-64) / transposition / rot90/270 of the
  bswapped or raw tile matches PC (best mean 57). Possibly partially-
  initialized padding or X360-specific UI variant. 1 texture, accepted.

**P1 console character binds — VERIFIED IDENTICAL (2026-07-16 session 2b).**
`watchmen.py binds` on the PS3 p1 naz and the X360 derived_x360 loose tree
produces all 5 P1 skeleton binds (large, medium, nto, rsh, small) numerically
IDENTICAL to PC (every npz key array_equal, all three platforms; runs in
<45 s per platform). Console P1 skeleton/rest-pose decode is therefore exact;
the full `characters` glb export on console sources would consume these same
binds + the already-audited extract-out, so parity is expected — running the
(long, resumable) export remains optional.

**PS3 cubemap framing — partial findings (faces 1-5 recovery, TODO).**
Confirmed the face data IS byte-exact in the PS3 stream (PC probe bytes found
verbatim), so full recovery is possible once the framing is decoded:
- Stream = one 36-B segment header + data (128px DXT1 cube: 65976 B ≈ 6x10996).
- PC layout (extracted/*.stream) is plain face-major chains of 10936 B.
- PS3: face-mip0 starts observed at 0 / 13752 / 27504 / 44072 / 57824
  (faces 0-4; face5 scattered) — stride 13752 = 8192 (mip0) + 2816 (gap)
  + 2744 (mip1-7 subchain), i.e. per face [mip0][2816-B inclusion][subchain],
  with face3 shifted +2816 more. BUT 6x13752 > file size, and the 2816-B
  inclusions drift INTO later faces' mip0 at content-dependent offsets
  (face2 broken at byte 2560, face1 at ~5120, face5 sliced ~2048/8960) —
  probe-mapping partially contaminated by repeating sky content. 2816 ≈ a
  padded mip subchain (2744+72). Next step: dump the 2816-B gap regions
  (data[8192:11008], data[21944:24760]) and identify whose bytes they are;
  or decode the 36-B header fields (u32be: [0, 128(w), 65976(total), …,
  43748@+16?, 0x800080…]) for a face-pitch field.
  Gap-region probe results (contradict the simple foreign-inclusion model —
  needs fresh eyes): the "gap" at data[21944:24760] is actually face1's own
  CONTINUATION (pc face1 bytes [5632:8448] verbatim) — i.e. something ~2816 B
  was inserted mid-face and everything after just shifts; the gap at
  data[8192:11008] maps to pc face4[5408:7456] + face5 pieces (possibly sky-
  content false positives). Also: header u32be @+16 = 43748 ≈ 4x10936 (pc
  face4 chain offset, off by 4) — possibly an offset/pitch field. All probe
  code patterns are in this section's history; PC face-major chains (10936 B)
  are the ground truth to reassemble against.

**Ops (chunked long jobs).** Bash calls cap at 45 s and background procs are
reaped between calls. This session's extraction driver
(`/tmp/wl/chunk_extract.py`, resumable port of `watchmen_extract.main()` with
a JSON state file; stages files→blocks(+per-asset resume)→console-audio(+per-
item save)→models, model jobs spilled to disk, texture index cached) is the
pattern that works: ~25-30 s work per call, state saved before exit.
