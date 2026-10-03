# The Kapow `.naz` / Block Format — *Watchmen: The End Is Nigh, Part 2*

A from-the-bytes description of how this game stores its assets, written so that
someone with a hex editor and the game files can follow along. Everything here was
recovered by reverse-engineering the shipped data (`game.naz` and the derived
`*.block_h_z` / `*.block_s_z` pairs) against a Ghidra decompile of the game
executable, and verified by extracting and decoding real assets byte-for-byte.

> **Provenance.** The game runs on **Kapow** (internal codename **WM07**), the
> in-house engine of *Deadline Games* (Copenhagen). It is a 32-bit Direct3D 9 PC
> title from 2009, cross-built for X360/PS3 (that heritage leaves fingerprints in
> the data — endian-swap helpers, per-platform format tables). Source-path strings inside
> the binary point at `c:\Develop\KapowMulti\delivery\...`, e.g.
> `kernel/assets/texture/texture.cpp`, which is how individual loaders were named.
>
> **Corrected 2026-10-02.** The block header, the directory record, the asset
> header, the texture descriptor and the ModelRes layout below were re-read from
> the engine's own loaders (research report: [`re/formats.md`](re/formats.md)).
> Where an earlier version of this document was wrong, the text is corrected
> and the correction is marked with that date. The main ones: the fixed header
> is 400 bytes and the directory starts at 400, not 399; a stream pair belongs
> to its own record, so there is no "+1 shift"; the six slots of a record are
> languages, not platforms; the u32 after an asset's type name is the length of
> its property bag, not a class id.

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

- **`<name>.block_h_z`** — the **header file**: a fixed header, a directory (table of
  contents) of every asset in the level, then each asset's **header blob** (its
  metadata / property bag).
- **`<name>.block_s_z`** — the **stream file**: a flat pool of every asset's bulk
  **stream blob** (texel data, vertex buffers, audio, …).

Splitting "what is it" (headers, small, parsed eagerly) from "the heavy bytes"
(streams, loaded on demand) is the core idea of the format. The header file is
parsed up front to build the asset table; stream blobs are pulled from `block_s_z`
only when an asset is actually needed.

Despite the `_z` suffix, **the block files are not zlib-compressed as a whole** —
their first bytes are not the zlib `0x78` marker. Compression is applied
*per asset blob* (see layer 3).

### 2.1 `block_h_z` overall layout

*Corrected 2026-10-02.* Earlier versions called the first ~330 bytes an opaque
high-entropy preamble, placed a "small fixed header at 327" and started the
directory at 399. The engine reads **exactly 400 bytes in one call**
(`FUN_004a36d8`, `push 0x190` at 0x4ae315) and the directory follows at 400.
The high-entropy part is the encrypted fingerprint string.

```
 offset 0 ─ 399 : fixed header
     @0    f32[8]   bounds (two vec4)
     @32   u32      (not established; no reader found)
     @36   char[36] GUID text (no reader found)
     @72   char[255] fingerprint: C string, LFSR-encrypted with the key
                    "1E564E3B-D243-4ec5-AFB7" (FUN_0049dd0e); shipped blocks decrypt to
                    "THIS IS THE DEFAULT FINGERPRINT KEY, PLEASE CHANGE IT!"
     @327  u8       2                 (meaning not established)
     @328  u32      0x593F430A        never checked by the loader; inferred to be
                                      the block version signature
     @332  u32      tablesSize        directory bytes, starting at 400
     @336  u32      entry0Size        header-blob size of entry 0 (the first blob read)
     @340  u32      ioBufferSize      max(tablesSize, largest header blob)
     @344  u32      fragmentOffset    = 400 + tablesSize + Σ blob sizes: a trailing blob
     @348  u32      fragmentSize      8
     @352  u32      numEntries        records in the MAIN directory
     @356  u32      numLocalized      records behind the per-language seek
                                      (mainmenu = 1 logo bmp, watchmenpart2 = 14
                                      _uk text assets)
     @360  u32      numStreams        records with hasStream = 1
     @364  u32[6]   languageHeaderOffset   file offset of the localized header
                                      blobs, one per language slot
     @388  u8       flag (meaning not established); 389–399 zero
 offset 400 ───────────────: DIRECTORY, `tablesSize` bytes
 offset 400 + tablesSize ──: HEADER-BLOB POOL — each asset's header blob,
                             concatenated in directory order
```

The former names for @336 / @340 / @344 (`firstBlobSize`, `maxBlobSize`,
`fileSize-8`) described the same numbers: the file ends with the 8-byte
trailing blob, so `fragmentOffset == fileSize − 8`.

**In situ (bordello):** `tablesSize=243241`, `numEntries=2291`, directory spans
`[400, 243641)`, header blobs start at `243641`. The first entry is
`/Levels/Game_Levels_Part2/Bordello` (the scene fragment).

`watchmen_extract.parse_block_header(h)` returns these fields;
`fingerprint_decrypt()` is the cipher.

### 2.2 The directory record (per asset)

*Corrected 2026-10-02.* Earlier versions started at 399 and read the record as
`flag, pair, sizes, hash, name`; the flag and pair are the **tail** of the
record, and the six copies are per **language**, not per build platform.

Walking from offset **400**, each record is variable-length (engine
`FUN_004a3525`):

```
 6 × u32   size[language]      header-blob size, one per LANGUAGE slot
 u32       typeHash            name_hash(assetTypeName), see below
 u32       nameLen
 char[nameLen]  name           the asset's virtual path, e.g.
                               "/art/environments/sky/Sky_Moon_02.bmp"
 u8        hasStream           1 ⇒ a stream pair block follows
 if hasStream:
   6 × { u32 off; u32 sz }     stream (offset, size) into block_s_z, one pair per
                               language slot
```

The slot index is the current language (engine `FUN_0045c762`, the index the
loader logs as "language: %s"). The six slots are equal except on the
`numLocalized` records that follow the main directory; for those the loader
seeks to `languageHeaderOffset[language]` before reading their header blobs.
Which language each slot number means is not established. The extractor uses
slot 0 by default (`--language 0..5`).

Type hashes (`kapow_props.name_hash` of the type name — the hash folds every
byte with `& 0xDF`, it does not upper-case):

| hash | type name |
|---|---|
| `0x80aa346d` | `sound` |
| `0x7d8d9a63` | `Texture` |
| `0x45870ad6` | `animation` |
| `0xa048cb21` | `fragment` |
| `0xf2e47acb` | `modelRes` |
| `0x7d6d720b` | `textRes` |
| `0x5cf8a3cf` | `PropertySequenceAsset` |
| `0x46b6f587` | `ParticleSystemAsset` |
| `0x86a9d7dd` | `grass` |
| `0xe1faf50f` | `mediastream` |
| `0xdeb3f74e` | `DetailMeshAsset` |
| `0x41764525` | `ModelEffects(ModelRes)` *(named 2026-10-02)* |
| `0x96ea413f` | `TextureEffects(Texture)` *(named 2026-10-02)* |
| `0x6532e9b4` | `terrain` |
| `0xd8c06967` | `pivotbook` |
| `0x48d86c33` | `aipathdata` |

`ModelEffects(ModelRes)` and `TextureEffects(Texture)` are script classes on
top of a native asset class. They have no reader of their own: the base
class's loader runs, with a longer property bag.

**Counts (bordello):** of 2291 records, **581 have `hasStream == 1`** and 1710
do not. The header blobs are read in order: blob *i* is `size_i` bytes
starting where blob *i−1* ended, beginning at `400 + tablesSize`.

### 2.3 The stream-binding rule

*Corrected 2026-10-02.* This section used to describe a "+1 shift": the stream
of asset *i* was taken from the pair parsed with record *i+1*, and the
directory was said to open with a sentinel flag. Both were artefacts of
starting the walk at 399 — byte 399 is a zero pad byte of the fixed header and
happened to parse as `flag = 0`. Read from 400, with the flag and pairs at the
end of the record, **an asset's stream is the pair stored in its own record**,
and there is no sentinel.

The two readings bind the same bytes to the same assets, which is why
extraction was correct before: across all blocks of Part 2 PC (8,696 entries)
the corrected parser returns the same header and stream for every entry.
What the old reading could not see were the `numLocalized` records.

**In situ.** The record's own pair inflates to the stream length the asset's
header predicts:

| record | asset | predicted stream | own pair inflates to |
|---|---|---|---|
| 1 | `2d_noise4.bmp` | 174 776 | 174 776 |
| 3 | `Sky_SunFlare_01.bmp` | 10 936 | 10 936 |
| 4 | `Sky_Moon_02.bmp` | 87 408 | 87 408 |

and the walk from 400 ends exactly at `400 + tablesSize`.

Each blob (header *or* stream) is then **individually zlib-compressed** when its
first byte is `0x78` — inflate it; otherwise it is stored raw. (`maybe_inflate`.)

Engine cross-reference: the asynchronous block loader is `FUN_004a36d8`
(`loadblock.cpp`, log string *"Allocating 2 buffers for asset block loading"*). It
streams `block_s_z` in chunks (chunk-size array at loader-context `+0x1C0`, count at
`+0x1B8 & 0xFFFFFF`) into a ping-pong **double buffer** (`+0x1A4`/`+0x1A8`, indices
swapped at `+0x1AC`/`+0x1B0`, both allocated with `ioBufferSize`), consuming the
`(off,sz)` pairs of the records.

---

## 3. Layer three — the per-asset header blob (property bag)

Every header blob (the bytes for asset *i* in the header-blob pool) starts the same
way and then carries a type-specific body:

```
 u32      typeNameLen          e.g. 8
 char[]   typeName             "Texture", "ModelRes", "sound", "TextureEffects(Texture)", …
 u32      bagDwords            length of the property bag in 32-bit words
 …        bagDwords × 4 bytes of property records, then the type-specific body
```

*Corrected 2026-10-02.* The u32 after the type name was documented as a
"classId / version" (`0x2D` for textures, `0x5B` for models). It is the
dword count of the property bag (engine `FUN_00511f96`): 45 for `Texture`, 91
for `ModelRes`, 55 for `TextureEffects(Texture)`, 96 for
`ModelEffects(ModelRes)`. The body starts at
`4 + typeNameLen + 4 + 4·bagDwords`.

Reading `typeName` is how you classify an asset without guessing. **In situ
(bordello)** the class histogram is roughly: 843 `sound`, 273 `Texture`, 217
`ModelRes`, 76 `ModelEffects(ModelRes)`, plus particle systems, grass, detail
meshes, media streams, and ~686 untyped/metadata records.

The body is a **sequential serialized stream**: the engine reads it field-by-field
through typed-read methods (`read u32`, `read float`, `read bool`, …) rather than as
a fixed-offset struct.

---

## 4. The Texture asset

A `Texture` header describes a **material**: one or more stacked image layers
(diffuse, normal, specular, glossiness…), each a full mip chain, packed back-to-back
in a single stream.

### 4.1 Header body

*Corrected 2026-10-02 (engine `FUN_005382aa`, descriptor `FUN_00429e77`).*
Earlier versions described "one ~30-byte record per stored layer" starting at
a fixed offset 196, with a stride that drifts.

```
 (typeName, bagDwords, property bag as in §3)
 u32 nFrames; u8 hasAnim
 per frame:
   Desc                                  slot 0
   7 × { u8 present; Desc if present }   slots 1..7
   u32 pathLen; char path[pathLen]       the source path, e.g.
                                         "/data/art/characters/twilightlady/textures/TwilightLadyAcce.bmp"
```

The property bag is 20-byte records, each beginning with the same per-asset
`salt` u32. A plain `Texture` has 9 of them (45 dwords), so its body begins at
offset 196; a `TextureEffects(Texture)` has 11.

The source path gives **100 %-correct asset names** and the folder tree to
rebuild on extraction.

### 4.2 The image descriptor (per slot)

```
 Desc (29 bytes): u32 width, u32 height, u32 format, u32 0, u32 type (1 = 2D, 2 = cube),
                  u8 hasAlpha, u32 mipCount, u32 0
```

The slot index is the layer's role. Seen in Part 2 PC: 0 diffuse, 1 normal
(`ATI2`), 2 specular (`DXT1`), 3 `DXT1`, 4 `L8`, 7 `L8` (the gloss / specular-power
map, "specSize"); 5 and 6 are never present. The roles of slots 3 and 4 are
not established.

The offsets earlier versions gave for a "30-byte record" (`+4` width × 256,
`+8` height × 256, `+13` format, `+20 == 256`, `+26` mip count) are these same
fields read through a window that began five bytes early, at `nFrames`: the
"× 256" is the `hasAnim` byte in front of the width, and the "256 signature" is
the type field (1) seen one byte early.

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

A typical material packs: slot 0 diffuse (`DXT1`/`DXT5`), slot 1 normal
(`ATI2`/BC5), slot 2 specular (`DXT1`), optionally slot 7 **glossiness**
(`L8`) — the gloss / specular-power channel (not a reflection mask).

### 4.3 Why a fixed 30-byte stride did not work

*Corrected 2026-10-02.* The "drift" earlier versions worked around is the
presence byte: a present slot costs 1 + 29 bytes, an absent one 1 byte. A
29-byte descriptor followed by the next slot's presence byte looks like a
30-byte record until a slot is skipped; the gloss map in slot 7 sits behind the
presence bytes of the empty slots before it. No extra field exists.

### 4.4 Layer sizing

Each layer is stored as a mip chain at its **authored base dimensions**, top mip
first, containing exactly `mipCount` levels:

```
 chainBytes(layer) = Σ_{k=0..mipCount-1}  levelBytes(w>>k, h>>k)
 levelBytes(w,h) = ceil(w/4)·ceil(h/4)·bpb          (block formats: DXT1=8, DXT5/DXT3/ATI2=16)
                 = h · align4(w·bpp)                 (linear: X8R8G8B8=4, L8=1)
```

*Corrected 2026-10-02:* **linear formats store every row padded to 4 bytes.**
That adds 5–7 bytes to an `L8` chain that reaches 2×2 and 1×1; earlier versions
had `w·h·bpp` and absorbed the difference with a tolerance.

The inflated stream is, for each frame, each present slot's chain in slot order
(× 6 for a cube), with no per-layer header. The header says which shape it is:

| shape | header | stream |
|---|---|---|
| **single** | `nFrames == 1`, type 1 | diffuse ‖ normal ‖ spec ‖ … |
| **cube** | type 2 | 6 faces |
| **anim** | `nFrames > 1`, `hasAnim` | an N-frame flipbook: each frame = the layer set |

With the row padding, header and stream length agree exactly on **936 / 936**
Part 2 PC textures (822 single, 110 cube, 4 anim), so the stream length is no
longer needed as an oracle to pick the shape. Earlier versions inferred the
shape from the length (`Σ == len`, `Σ·6 == len`, `Σ·N == len`) and reported
more flipbooks: 10 two- or three-layer materials with same-size `DXT1` layers
had been read as N frames.

The extractor uses the exact plan when it tiles the stream byte-for-byte and
falls back to the length-based planner otherwise (console files; cube textures
with more than one layer and flipbooks whose frames differ were never
observed). The face order inside a PC cube stream was not traced in code.

Cubemaps are confirmed in code: the texture-buffer build `FUN_0045473f` branches on
the descriptor type (`1` = 2D, `2` = cube → `WrappedCreateCubeTexture`).

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

*Corrected 2026-10-02 (steps 1–3).*

1. Open `block_h_z`; read `tablesSize @332`, `numEntries @352`, `numLocalized @356`;
   walk the directory from `400` (§2.2). Compute each header blob's offset from
   the running sum of sizes, starting at `400 + tablesSize`; the localized
   blobs start at `languageHeaderOffset[language]`.
2. For asset *i*, its stream is the `(off, sz)` pair in **its own record**
   (§2.3): read those bytes from `block_s_z`, `maybe_inflate`.
3. If the header's type is `Texture` or `TextureEffects(Texture)`: parse the
   frames and slot descriptors (§4.1–4.2), compute the chains (§4.4), carve,
   and decode each layer / face / frame (§4.5).
4. Write each PNG under the asset's embedded source path to rebuild the original
   `/data/art/...` tree.

This is what the texture path in `wlib/watchmen_extract.py` implements, and
it needs nothing but the block files and Python + Pillow + numpy.

---

## 6. Engine function reference (Ghidra, game executable)

| address | role |
|---|---|
| `0x00442910` | `FileBuffer` — `.naz` (obfuscated ZIP) mount: EOCD/CD walk, name de-rotation |
| `0x004A36D8` | `loadblock.cpp` async block loader — fixed header, double-buffered streaming |
| `0x004A3525` | directory walker — one record per call |
| `0x0049DD0E` | block header consumer — decrypts the fingerprint |
| `0x0045C762` | current language index (selects the slot) |
| `0x00423CE8` | name hash — bit-CRC32 over bytes `& 0xDF` |
| `0x0054BA59` | asset lookup by name (hash table) |
| `0x00511F96` | asset header: type string + property bag (dword count) |
| `0x005382AA` | `texture.cpp` Texture deserialize — frames, 8 slots per frame |
| `0x00429E77` | texture descriptor (29 bytes) |
| `0x00538184` | Texture finalize — iterates the image array (`[size, ptr]` per image) |
| `0x0045473F` | texture-buffer build — branches 2D vs cube on the descriptor type |
| `0x004540D7` | D3D `CreateTexture` / `CreateCubeTexture` path |
| `0x00C799E0` | data: format enum → `D3DFORMAT` table |
| `0x00547006` | `ModelRes::Read` |
| `0x00545927` | model part / node (`Node::Deserialize`) |
| `0x00542541` | submesh record |
| `0x004336EC` | mesh-buffer header |
| `0x00C791B0` | data: vertex stride per format id |

Most of these open with the `__EH_prolog` call and decompile to a 10-byte stub
in a default Ghidra analysis; `tools/ghidra/FixEHProlog.java` repairs that.

---

## 6b. The ModelRes (mesh) asset

*Rewritten 2026-10-02 from the engine's readers (`ModelRes::Read` `FUN_00547006`
→ part `FUN_00545927` → submesh `FUN_00542541` → mesh buffer `FUN_004336ec`).*
Earlier versions described a 7×u32 "geometry descriptor" found by scanning, a
field `G` read as an element count, an index buffer that "ends at the first
index ≥ vertexCount", and an open "multi-submesh reality". All of that is
replaced by the layout below, which reproduces the stream length exactly on
740 / 740 Part 2 PC models.

A `ModelRes` is a mesh. Like a texture it splits across the two block files: the
**header blob** carries the structure, the **stream blob** the raw geometry.

**Header blob** (after the type string and property bag of §3):

```
 u32, bool hasSkeleton, u32, bool hasCloth, [u32 n][n×32 B], [u32 n][n×4 B]
 vec3 bboxCenter, vec3 bboxHalfExtent
 u32 nTex  { bool; string path }            texture list
 u32 nPb   { string path }                  pivotbooks
 u32 nParts { Part }
 … physics / ragdoll, optional cloth object, animation-event list (not parsed)

 Part:    vec3 pos, quat (xyzw), string name, u32, i32 parent
          u32 nLods { u32 nSub { Submesh } }
          u32 nGroups { u32 n { bool; u32; MeshBuffer } }      shadow hulls
          bool; MeshBuffer if set                               per-part proxy slab
          2 × [ u32 n { collision volume } ]                    see FORMATS_MISC.md
          u32 n { surface }
 Submesh: string name, [u32 1][u32 textureIndex], bool, bool inline, u32, bool, bool,
          MeshBuffer, [u32 size][size bytes]
 MeshBuffer: vec3 bboxCenter, vec3 bboxHalfExtent, u8 hasColor, u8 hasAlpha, bool extra,
          u32 flags, u32 vertexCount, u32 FORMAT,  u32 flags, u32 indexBytes, u32
```

- Every part is a node: `pos` / `quat` are its pivot, `parent` its parent index.
- `textureIndex` indexes the model's texture list; that is the submesh's
  material.
- A part has one or more levels of detail, each a list of submeshes.
- `FORMAT` is the vertex format id (what earlier versions called `G`).
- `indexBytes` is a byte count; indices are always `u16` triangle lists.

**Stream blob** — for each MeshBuffer in header order (per part: the submeshes
of every LOD, then the shadow groups, then the proxy slab):

```
 vertexCount × stride[FORMAT]    vertex data
 indexBytes                      u16 indices
 [u32 n][n × 40 B]               cluster table
 [u32 n] lists
 [u8 has][vertexCount × 8 B]
```

| FORMAT | stride | layout |
|---|---|---|
| 5 rigid | 44 | pos f32×3 @0 · normal half3 @12 · colour BGRA @20 · uv half2 @24 · tangent half3 @28 · bitangent half3 @36 |
| 6 skinned | 56 | format 5 + joints @44 (idx0..3 = bytes 46, 45, 44, 47) · weights half4 @48 |
| 9 shadow hull | 20 | pos f32×3 @0 · normal half3 @12 |
| 10 skinned hull | 32 | format 9 + joints @20 · weights half4 @24 |

Positions are raw floats; there is no quantisation, scale or bias in any
format. UVs are raw half floats with no scale, bias or V flip. The stride
table (`0x00C791B0`) has 11 formats; only these four occur in `.model` files
(Part 2 PC: format 5 ×2370, 6 ×287, 9 ×357, 10 ×104).

Not established: the role of the per-part proxy slab (one coarse rigid buffer
on 79 parts — on real files a slab inside the visible mesh); whether vertices
are part-local; several u32 / bool fields of the part and submesh records;
the unit of the cluster ranges.

**Extractor.** `watchmen_extract.parse_model_header` and `model_stream_layout`
implement this layout; `decode_model_mesh` returns everything per submesh
(name, part, LOD, texture, positions, normals, UVs, triangles, colour, tangent,
bitangent, joints, weights). `decode_model` writes an **OBJ + MTL** per model
(and, with `--glb`, a rigged GLB for skinned models), with LOD 0 by default
(`--model-lod N|all`) and without shadow hulls and proxy slabs. The header
path is used only when the header parses and the layout consumes the stream
to the last byte; console files and Part 1 PC headers do not follow this
layout and take the older descriptor scan, unchanged.

*Corrected 2026-10-02:* earlier versions said the extractor also writes FBX
and STL (`--format obj,fbx,stl`). The shipped extractor has no such option
and no FBX or STL writer.

## 7. Status of the wider format

**Textures are fully solved** — naming, deterministic stream binding, and
byte-exact layer/cube/animation carving all verified end-to-end against real data
and the engine code. Models (`ModelRes`) decode from their header on Part 2 PC
*(corrected 2026-10-02: the "index-buffer recovery still partial for some
baked-environment meshes" caveat is withdrawn; see §6b)*; audio (`MediaStream`,
libVorbis/Bink) is covered in `WATCHMEN_EXTRACTION_MASTER.md`. The container
and block formats above are common to all of them.

*This document describes the shipped data of one specific title and was derived by
clean-room reverse engineering for interoperability/preservation.*
