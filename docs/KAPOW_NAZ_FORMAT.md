# The Kapow `.naz` / Block Format — *Watchmen: The End Is Nigh, Part 2*

A from-the-bytes description of how this game stores its assets, written so that
someone with a hex editor and the game files can follow along. Everything here was
recovered by reverse-engineering the shipped data (`game.naz` and the derived
`*.block_h_z` / `*.block_s_z` pairs) against a Ghidra decompile of the game
executable, and verified by extracting and decoding real assets byte-for-byte.

> **Provenance.** The game runs on **Kapow** (internal codename **WM07**), the
> in-house engine of *Deadline Games* (Copenhagen). It is a 32-bit Direct3D 9 PC
> title from 2009, cross-built for X360/PS3 (that heritage leaves fingerprints in
> the data — endian-swap helpers, per-platform fields). Source-path strings inside
> the binary point at `c:\Develop\KapowMulti\delivery\...`, e.g.
> `kernel/assets/texture/texture.cpp`, which is how individual loaders were named.

There are three nested layers. Each section below peels one off:

```
 game.naz                         (1) obfuscated-ZIP container
   └─ <level>.block_h_z + .block_s_z   (2) Kapow "block": a directory + two blob pools
        └─ per-asset { header blob, stream blob }   (3) the actual assets
             └─ Texture / ModelRes / Sound / …      (4) typed payloads (textures detailed here)
```

---

## 1. Layer one — the `game.naz` container

`game.naz` (≈937 MB in this title) is an **obfuscated PKZIP archive**. It is a
normal ZIP structurally, with three deliberate changes that stop standard tools
from opening it:

| Aspect | Standard ZIP | `.naz` |
|---|---|---|
| End-of-central-directory magic | `0x06054B50` | **`0x16ED5B50`** |
| Central-directory entry magic | `0x02014B50` | **`0x0406F370`** |
| Filenames | plain bytes | **rotate-left-2 per byte**: `b = (b >> 6) \| (b << 2)` |
| Field positions | per spec | **shifted 8 bytes earlier** than spec |

Everything else is ZIP: there is an end-of-central-directory record at
`filesize − 22`, a central directory of fixed-layout entries (name length @+20,
extra @+22, comment @+24, local-header offset @+34, name at +46 after de-rotating),
and each entry's data sits at `localHeaderOffset + 30 + nameLen + extraLen`.

In the engine this is the `FileBuffer` mount (function `@0x00442910`). When it sees
the `.naz` signature it switches on name de-rotation and the 8-byte shift, then
mounts every entry into a virtual `/data/...` filesystem the rest of the engine
reads from.

**In situ (the real `game.naz`):** EOCD `magic=0x16ED5B50, entryCount=57,
cdOffset=937091304, cdSize=70383`. So the archive holds **57 top-level entries** —
the per-level block pairs plus a few engine helpers and `database.bin`. **Every
entry is STORED (compression = 0, packedSize == unpackedSize).** The container does
**not** deflate anything; the only compression in the whole format is the inner,
per-asset zlib inside the blocks (layer 3). That is the single most useful fact for
a re-implementer: to get at a block you only need to locate its STORED bytes in the
ZIP — no inflate at the container level.

---

## 2. Layer two — the Kapow "block" (`block_h_z` + `block_s_z`)

A level (e.g. `bordello`, `nightclub`, `streetsofriot`, …) ships as **two files**:

- **`<name>.block_h_z`** — the **header file**: a directory (table of contents) of
  every asset in the level, followed by each asset's **header blob** (its metadata /
  property bag).
- **`<name>.block_s_z`** — the **stream file**: a flat pool of every asset's bulk
  **stream blob** (texel data, vertex buffers, audio, …).

Splitting "what is it" (headers, small, parsed eagerly) from "the heavy bytes"
(streams, loaded on demand) is the core idea of the format. The header file is
parsed up front to build the asset table; stream blobs are pulled from `block_s_z`
only when an asset is actually needed.

Despite the `_z` suffix, **the block files are not zlib-compressed as a whole** —
their first bytes are not the zlib `0x78` marker. Compression is applied
*per asset blob* (see layer 3). The first ~330 bytes of `block_h_z` are a
high-entropy preamble (the original signed/obfuscated header); the loader does not
need it to walk the directory.

### 2.1 `block_h_z` overall layout

```
 offset 0 ────────────── ~330 : opaque preamble (high entropy; not needed for the TOC)
 a small fixed header at 327 (audited 2026-07-09, all 7 levels):
     @327  u8   2                constant
     @328  u32  0x593F430A       magic
     @332  u32  tablesSize       size in bytes of the directory region
     @336  u32  firstBlobSize    header-blob size of entry 0 (the scene fragment)
     @340  u32  maxBlobSize      largest header blob (decompression buffer size)
     @344  u32  fileSize-8       header file size minus the 8 zero tail bytes
     @348  u32  8                constant
     @352  u32  numEntries       number of assets in the MAIN directory
     @356  u32  numLocaleExtra   appended localization records after the main
                                 directory (mainmenu=1 logo bmp, watchmenpart2=14
                                 _uk text assets); their streams sit past the
                                 last referenced offset in block_s_z
     @360  u32  numFlagged       count of entries with flag==1 (stream pairs)
 the header file ends with 8 zero bytes (thus @344 == fileSize-8)
 offset 399 ──────────────────: DIRECTORY (table of contents), `tablesSize` bytes
 offset 399 + tablesSize + 1 ─: HEADER-BLOB POOL — each asset's header blob,
                                concatenated in directory order, sized by `data_size`
```

**In situ (bordello):** `tablesSize=243241`, `numEntries=2291`, directory spans
`[399, 243641)`, header blobs start at `243641`. The first entry is
`/Levels/Game_Levels_Part2/Bordello` (the scene fragment).

### 2.2 The directory record (per asset)

Walking from offset **399**, each of the `numEntries` records is variable-length:

```
 u8       flag                 1 ⇒ this record carries a stream pair; 0 ⇒ it does not
 if flag == 1:
   6 × { u32 off; u32 sz }     stream (offset,size) into block_s_z — ONE pair, stored
                               six times (one per build platform); identical on PC
 6 × u32   variants            header-blob size, stored six times (per platform);
                               identical on PC → use any non-zero one as `data_size`
 u32       assetTypeHash        kapow_hash(assetTypeName): sound 0x80aa346d,
                               Texture 0x7d8d9a63, animation 0x45870ad6,
                               fragment 0xa048cb21, modelRes 0xf2e47acb,
                               textRes 0x7d6d720b, PropertySequenceAsset,
                               ParticleSystemAsset, grass, mediastream,
                               DetailMeshAsset; 2 unnamed subtypes remain
                               (0x41764525 models, 0x96ea413f terrain/decal bmps)
 u32       nameLen
 char[nameLen]  name           the asset's virtual path, e.g.
                               "/art/environments/sky/Sky_Moon_02.bmp"
```

The "six copies" of both the stream pair and the size reflect the engine's
editor/PC/X360/PS3 multi-platform build; on the shipped PC data all six are equal,
so you read one and ignore the rest.

**Counts (bordello):** of 2291 records, **581 have `flag==1`** and 1710 have
`flag==0`. The header blobs are then read in order: blob *i* is `data_size_i` bytes
starting where blob *i−1* ended, beginning at `399 + tablesSize + 1`.

### 2.3 ⭐ The stream-binding rule (the one non-obvious part)

The naïve reading — "an asset's stream is the pair stored in its own record" — is
**wrong by one record**, and that off-by-one is the single trickiest thing in the
format. The truth:

> **The `(off,sz)` pair is a *trailer*, written after the asset's name, and it
> locates the stream of the asset whose record it terminates. A head-first parser
> (read flag → pair → variants → name) therefore reads each trailer as the *leading*
> field of the *next* record.**

So if you parse records head-first (as in §2.2), the binding is a **+1 shift**:

```
 stream(asset i)  =  parsedRecord[i+1].pair      (present iff parsedRecord[i+1].flag == 1)
```

The directory opens with one leading flag/pair that belongs to no asset (a
sentinel). Equivalently: re-align your parser so the flag+pair is the *tail* of each
record and the off-by-one disappears.

**Proof, in situ.** For every pair of consecutive stream-bearing assets, the
inflated length of the pair stored on record *i+1* equals the *predicted* stream
length of asset *i*:

| record | asset | predicted stream | pair stored *here* inflates to |
|---|---|---|---|
| 1 | `2d_noise4.bmp` | 174 776 | — |
| 2 | `Sky_Mansion_01.fragment` | — | **174 776** ← asset 1's stream |
| 3 | `Sky_SunFlare_01.bmp` | 10 936 | — |
| 4 | `Sky_Moon_02.bmp` | 87 408 | **10 936** ← asset 3's stream |
| 5 | `Sky_Mansion_BG_01.bmp` | 11 016 | **87 408** ← asset 4's stream |

Applying the +1 shift resolves **1190 / 1190** textures across all level blocks
with **zero** search and zero ambiguity. (Historically this looked like a "stream
pool" being consumed out of order; it is not a pool — it is purely the trailer
off-by-one.)

Each blob (header *or* stream) is then **individually zlib-compressed** when its
first byte is `0x78` — inflate it; otherwise it is stored raw. (`maybe_inflate`.)

Engine cross-reference: the asynchronous block loader is `FUN_004a36d8`
(`loadblock.cpp`, log string *"Allocating 2 buffers for asset block loading"*). It
streams `block_s_z` in chunks (chunk-size array at loader-context `+0x1C0`, count at
`+0x1B8 & 0xFFFFFF`) into a ping-pong **double buffer** (`+0x1A4`/`+0x1A8`, indices
swapped at `+0x1AC`/`+0x1B0`), consuming exactly the `(off,sz)` from the trailer
above.

---

## 3. Layer three — the per-asset header blob (property bag)

Every header blob (the bytes for asset *i* in the header-blob pool) starts the same
way and then carries a type-specific body:

```
 u32      typeNameLen          e.g. 8
 char[]   typeName             "Texture", "ModelRes", "sound", "ModelEffects", …
 u32      classId / version    0x2D (45) for textures on WM07
 …        type-specific body (a generic property bag, then typed records)
```

Reading `typeName` is how you classify an asset without guessing. **In situ
(bordello)** the class histogram is roughly: 843 `sound`, 273 `Texture`, 217
`ModelRes`, 76 `ModelEffects`, plus particle systems, grass, detail meshes, media
streams, and ~686 untyped/metadata records.

The body is a **sequential serialized stream**: the engine reads it field-by-field
through typed-read methods (`read u32`, `read float`, `read bool`, …) rather than as
a fixed-offset struct. This matters for parsing — see §4.3.

---

## 4. The Texture asset

A `Texture` header describes a **material**: one or more stacked image layers
(diffuse, normal, specular, reflection…), each a full mip chain, packed back-to-back
in a single stream.

### 4.1 Header body

```
 (typeName="Texture", classId=0x2D as above)
 N × 20-byte PROPERTY records   a "property bag"; each record begins with the same
                                per-asset `salt` u32 (the salt repeats, which is how
                                the record size was proven). 9 records is typical,
                                so the image array begins at a fixed offset 196.
 IMAGE-DESCRIPTOR ARRAY         one record per stored layer (≈30 bytes; see 4.2)
 u32 pathLen; char[pathLen]     the source path, e.g.
                                "/data/art/characters/twilightlady/textures/TwilightLadyAcce.bmp"
```

The trailing source path gives **100 %-correct asset names** and the folder tree to
rebuild on extraction.

### 4.2 The image-descriptor record (per layer)

Each layer's descriptor is nominally 30 bytes. The fields that matter:

| offset | type | meaning |
|---|---|---|
| `+4`  | u32 | authored width  × 256  (read as `value >> 8`) |
| `+8`  | u32 | authored height × 256  (read as `value >> 8`) |
| `+13` | u8  | **format enum** (table below) |
| `+20` | u32 | `256` — a constant that doubles as a record signature |
| `+26` | u8  | **mip count** = number of mip levels actually stored for this layer |

**Format enum** (the engine's enum→`D3DFORMAT` table lives at `0x00C799E0`):

| enum | format | storage |
|---|---|---|
| 0 | `X8R8G8B8` | linear, 4 B/px (BGRA order on disk) |
| 1 / 2 | `A8R8G8B8` | linear, 4 B/px |
| 3 / 4 | `L8` | linear, 1 B/px (grayscale; used for the glossiness map) |
| 5 | `DXT1` (BC1) | block, 8 B / 4×4 |
| 6 | `DXT3` (BC2) | block, 16 B / 4×4 |
| 7 | `DXT5` (BC3) | block, 16 B / 4×4 |
| 9 | `ATI2` / `BC5` | block, 16 B / 4×4 — a two-channel **normal map** |

A typical material packs: layer 0 diffuse (`DXT1`/`DXT5`), layer 1 normal
(`ATI2`/BC5), layer 2 specular (`DXT1`), optional layer 3 **glossiness** map
(`L8`/`X8R8G8B8`) — the gloss / specular-power channel (not a reflection mask).

### 4.3 Why a fixed 30-byte stride is not enough

Because the header body is a *sequential* typed-read stream (§3, engine
`FUN_005382aa` in `texture.cpp`, which reads an explicit image **count** and resizes
the image array at object `+0x90` to match), most layers serialize to 30 bytes but
some carry an extra field. A fixed 30-byte stride therefore **drifts** on a trailing
(usually the 4th) layer — observed as a ~5-byte slip. Read the first records at
stride 30 (with a +4-gap fallback), and use the §4.4 oracle to recover anything the
stride missed. The `+20 == 256` constant is a useful record signature when scanning.

### 4.4 Layer sizing, and the stream-shape oracle

Each layer is stored as a mip chain at its **authored base dimensions**, top mip
first, containing exactly `mipCount` levels:

```
 chainBytes(layer) = Σ_{k=0..mipCount-1}  blockBytes(w>>k, h>>k)
 blockBytes(w,h) = ceil(w/4)·ceil(h/4)·bpb   (block formats: DXT1=8, DXT5/DXT3/ATI2=16)
                 = w·h·bpp                    (linear: X8R8G8B8=4, L8=1)
```

The inflated stream is just `layer0 ‖ layer1 ‖ …` with no per-layer header, so
`Σ chainBytes` over all layers should equal the stream length. Crucially, **the
stream length is known exactly** (it comes from the §2.3 binding, read out of
`block_s_z` — it is *intrinsic to the game data*, not from any external reference).
That exact length is the oracle that disambiguates the three stream shapes:

| shape | test | meaning |
|---|---|---|
| **single** | `Σ == len` | one material: diffuse ‖ normal ‖ spec ‖ … |
| **cube** | `Σ·6 == len` | a cubemap: 6 faces, each face = the layer set |
| **anim** | `Σ·N == len` | an N-frame flipbook: each frame = the layer set |

If `Σ < len` (a layer was dropped by stride drift), scan the header for the missing
descriptor record and accept the set whose total hits `len`. This classifies
**1190 / 1190** level-block textures (≈1051 single, ≈110 cube, ≈29 anim).

Cubemaps are confirmed in code: the texture-buffer build `FUN_0045473f` branches on a
descriptor type tag (`1` = 2D, `2` = cube → `WrappedCreateCubeTexture`).

### 4.5 Decoding each layer to pixels

- **DXT1/DXT3/DXT5** → wrap the top-mip bytes in a minimal `.dds` header and let any
  BCn decoder (e.g. Pillow) expand them. **Keep the alpha channel** (decode to RGBA,
  not RGB): diffuse layers routinely carry meaningful alpha — e.g. graffiti/decal
  textures store a flat colour in RGB and the actual decal shape in the alpha, and
  DXT5/DXT3/A8R8G8B8 (and DXT1's 1-bit punch-through) all encode it. Dropping alpha
  turns a decal into a solid colour blob.
- **ATI2 / BC5** → decode the two BC4 channels to X and Y, reconstruct
  `Z = √(1 − X² − Y²)` for a viewable tangent-space normal map.
- **X8R8G8B8 / A8R8G8B8** → raw 4 B/px, swizzle BGRA→RGB.
- **L8** → raw 1 B/px grayscale.

The on-disk data is the **authored** mip chain; the GPU copy at run time may be one
or more mip levels smaller (the engine drops top mips under memory pressure). Decode
the top stored mip for maximum resolution.

---

## 5. Practical recipe (what a clean extractor does)

1. Open `block_h_z`; read `tablesSize @332`, `numEntries @352`; walk the directory
   from `399` (§2.2). Compute each header blob's offset from the running sum of
   `data_size`.
2. For asset *i*, bind its stream with the **+1 trailer shift** (§2.3): take
   `record[i+1]`'s `(off,sz)` if `record[i+1].flag==1`, read those bytes from
   `block_s_z`, `maybe_inflate`.
3. If the header `typeName == "Texture"`: parse the descriptor records (§4.2),
   plan the stream shape against the stream length (§4.4), carve, and decode each
   layer / face / frame (§4.5).
4. Write each PNG under the asset's embedded source path to rebuild the original
   `/data/art/...` tree.

This is exactly what the texture path in `wlib/watchmen_extract.py` implements, and
it needs nothing but the block files and Python + Pillow + numpy.

---

## 6. Engine function reference (Ghidra, game executable)

| address | role |
|---|---|
| `0x00442910` | `FileBuffer` — `.naz` (obfuscated ZIP) mount: EOCD/CD walk, name de-rotation |
| `0x004A36D8` | `loadblock.cpp` async block loader — double-buffered `block_s_z` streaming |
| `0x0054BA59` | asset lookup by name (hash table) |
| `0x005382AA` | `texture.cpp` Texture deserialize — reads image count, fills array `+0x90` |
| `0x00538184` | Texture finalize — iterates the image array (`[size, ptr]` per image) |
| `0x0045473F` | texture-buffer build — branches 2D vs cube on the descriptor type tag |
| `0x004540D7` | D3D `CreateTexture` / `CreateCubeTexture` path |
| `0x00C799E0` | data: format enum → `D3DFORMAT` table |

---

## 6b. The ModelRes (mesh) asset

A `ModelRes` is a mesh. Like a texture it splits across the two block files: the
**header blob** carries metadata, the **stream blob** carries the raw geometry.

**Header blob** — same property-bag layout as a texture (typeName `"ModelRes"`,
classId `0x5B`, then 20-byte salt-prefixed property records), and near its end a
geometry descriptor that includes the **vertex count** (e.g. CurtainRod_02 = 347 at
header offset 630), plus submesh/material counts and the bounding box. Engine truth:
`modelresderivedio.cpp` `FUN_00545927` deserialises it as a sequential typed-read
stream (read primitive `vtable+0x24` = "read N bytes"): an AABB (vec3 + vec4), nested
LOD→submesh count-loops (44-byte records), a material list (68-byte records), then the
geometry buffers — each **length-prefixed** (`u32 size` then that many raw bytes).

**Stream blob** — the interleaved vertex buffer followed by a `u16` triangle-list
index buffer (then a per-face surface table). The vertex layout (validated on real
meshes, byte-exact on `unit_box`):

| offset | type | field |
|---|---|---|
| `+0`  | 3×float32 | position (x, y, z) |
| `+12` | 3×float16 (HALF4, +1 pad) | normal |
| `+24` | 2×float16 | UV |

Stride is **44** for rigid meshes and **56** for skinned (the extra 12 bytes carry
bone indices/weights). The index buffer is `u16`, triangle list; it ends at the first
index ≥ vertexCount (that boundary is the surface table). Endianness/stride are
recovered by checking that the index buffer actually indexes the vertex buffer.

**Per-submesh geometry descriptor (header, verified).** Near the relevant point in
the header each geometry buffer is described by a fixed 7×u32 block:

    [flagsA] [vertexCount] [G] [flagsB] [indexBufferBytes] [1]   (flagsA==flagsB ∈ {0,8})

`G` is the vertex-element count and doubles as the rigid/skinned tag: **G=5 ⇒ stride 44
(rigid), G=6 ⇒ stride 56 (skinned)**. `indexBufferBytes` is authoritative (= triangles×6;
the empirical "read u16 until ≥ vertexCount" over-reads by a few into the surface table).
Bigger models carry material/texture name strings right after the descriptor.

**Multi-submesh reality (open).** Most models are NOT a single VB+IB: a `ModelRes`
holds a *list* of submeshes (e.g. Sky_Mansion ≈ 22, plus ~85 KB of non-render data —
collision / LOD), each with its own descriptor, and the stream concatenates them with a
layout that varies per model (the render VB is not always at offset 0). Robustly
splitting them needs the full sequential header deserializer (`FUN_00545927`) reconstructed
— the per-submesh descriptor above is the key, but the LOD/submesh/material records
between the property bag and the descriptors still need their exact byte sizes pinned.
An empirical "scan every vertex run + its index buffer" recovers most geometry (good on
architectural pieces) but includes noise/garbage triangles, so it is not yet
production-clean.


Extractor: the model path in `wlib/watchmen_extract.py` binds with the same +1 trailer rule,
extracts position/normal/UV + triangles, and writes **OBJ, FBX (ASCII 7.4), or STL
(binary)** — `--format obj,fbx,stl`. Verified: all three agree vertex/triangle counts,
STL byte-exact, FBX polygon encoding valid; wireframes render as coherent shapes
(sky dome, curtain rods, chandelier). Still open: explicit submesh/material splitting
and skin weights (the stride-56 extra bytes) for fully-rigged FBX export.

## 7. Status of the wider format

**Textures are fully solved** — naming, deterministic stream binding, and
byte-exact layer/cube/animation carving all verified end-to-end against real data
and the engine code. Models (`ModelRes`) decode to geometry (float vertex buffers,
HALF4 normals) with index-buffer recovery still partial for some baked-environment
meshes; audio (`MediaStream`, libVorbis/Bink) is partially mapped. Those are the
next layers to finish; the container and block formats above are common to all of
them, so they are the stable foundation.

*This document describes the shipped data of one specific title and was derived by
clean-room reverse engineering for interoperability/preservation.*
