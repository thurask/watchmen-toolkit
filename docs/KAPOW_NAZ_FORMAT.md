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

### 1.1 What the engine does with an archive
*Added 2026-10-05 (mount 0x4428fb, called from 0x442e81; lookup 0x43f9a1).*

- At start-up an empty archive list mounts every `.naz` **and `.zip`** in `/`, in listing order;
  a non-empty list (names separated by space or comma) is mounted in order.
- Mount: read 20 bytes at `fileSize − 22`. `u32 @0 == 0x16ED5B50` marks a `.naz` (names rotated,
  entry fields 8 bytes earlier); **any other value is treated as a plain zip** with standard
  offsets and no rotation. The central-directory magic (0x0406F370) is never read.
- Per entry the engine keeps only `{dataOffset = localHeaderOffset + 30 + nameLen + extraLen,
  size}`. `size` is the one field at naz +16 (zip "uncompressed size"). **No compression method
  is read and nothing is inflated**: an entry is used as stored.
- It keeps **no names**. The index key is the raw CRC (0x423ca1, no `& 0xDF` fold) of the name
  with `\` turned into `/` and A–Z lower-cased (0x4ebe76). A file is looked up by its path
  without the leading `/`, lower-cased, same CRC; archives are searched before the disk.
  (Measured: the 235 entry names of the four shipped archives are lower case throughout.
  Asset paths inside the blocks are not: see "Asset names" in
  [ENGINE_CONSTANTS.md](ENGINE_CONSTANTS.md) for the 41 that differ between the game sets
  and the one spelling `extract` writes them under.)
- Duplicates: inside one archive a later entry with the same key replaces the earlier one;
  across archives the **lowest mount slot wins**. Room for five archives is inferred from the
  handle array (0xd91d24 … 0xd91d38), which the mount code does not bounds-check.

`watchmen_extract.naz_entries` differs on purpose: it keeps the names, checks the directory
magic, rejects a plain zip, reads `psize` (naz +12) bytes and `naz_read` would inflate method 8.
Each entry now carries `key` (`naz_key(name)`, the engine's index key) and `naz_entries(path,
warn=...)` reports any entry whose compression method is not 0, since the engine would read it
as stored. Measured since (`naz_entries` on three archives): 57 entries, 57 unique keys, every
key = `naz_key(name)`, method 0, +12 == +16 (`psize == usize`) on the PC Part 2 archive, the
Bordello-mod archive and the XBLA Part 2 archive, so reading the length at +12 (toolkit) or +16
(engine) gives the same bytes there. The PS3 archives were not opened for this check.

---

## 2. Layer two — the Kapow "block" (`block_h_z` + `block_s_z`)

A level (e.g. `bordello`, `nightclub`, `streetsofriot`, …) ships as **two files**:

- **`<name>.block_h_z`** — the **header file**: a fixed header, a directory (table of
  contents) of every asset in the level, then each asset's **header blob** (its
  metadata / property bag).
- **`<name>.block_s_z`** — the **stream file**: a flat pool of every asset's bulk
  **stream blob** (texel data, vertex buffers, audio, …).

Splitting "what is it" (headers, small, parsed first) from "the heavy bytes"
(streams) is the core idea of the format. The header file is parsed up front to
build the asset table. *[Corrected 2026-10-05; this said "stream blobs are pulled
from `block_s_z` only when an asset is actually needed".]* For a load block that
is not what happens: when the last header blob has been read the loader hands
**every** stream record of the block to the stream manager (state 5 of
0x4a36d8 → 0x4e0515), at most 10 requests are queued at a time (0x4de7af), and
the block does not reach its final state — the trailing fragment is not read
and nothing is applied — until every stream has been delivered (state 6,
0x497ee9 → 0x4df5bb). A record whose asset is a "missing asset" is not
requested but counts as delivered. See §2.4.

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
     @32   u32      versionSignature  block version signature (see below)
     @36   char[36] GUID text (no reader found)
     @72   char[255] fingerprint: C string, LFSR-encrypted with the key
                    "1E564E3B-D243-4ec5-AFB7" (FUN_0049dd0e); shipped blocks decrypt to
                    "THIS IS THE DEFAULT FINGERPRINT KEY, PLEASE CHANGE IT!"
     @327  u8       fingerprintDisplay  0 = draw " Finger Print Key: <text>" on debug overlay
                                      page 2 until 20 s after its first draw in the process, then
                                      the engine sets 2; 1 = always; 2 = never (0x49dd59 →
                                      LoadBlock+0x1e4; reader 0x490e35; Unload resets to 0).
                                      2 in every shipped block.
     @328  u32      fingerprintCrc    kapow_hash (no fold) of the 255-byte plaintext fingerprint
                                      field (text + zero padding), stored little-endian on all
                                      platforms; 0x593F880A for the default fingerprint; not read
                                      by the loader; the writer is not in the game executable.
     @332  u32      tablesSize        directory bytes, starting at 400
     @336  u32      entry0Size        header-blob size of entry 0 (the first blob read)
     @340  u32      ioBufferSize      max(tablesSize, largest header blob)
     @344  u32      fragmentOffset    = 400 + tablesSize + Σ blob sizes: a trailing blob
     @348  u32      fragmentSize      8 (two zero counts, see §2.4)
     @352  u32      numEntries        records in the MAIN directory
     @356  u32      numLocalized      records behind the per-language seek
                                      (mainmenu = 1 logo bmp, watchmenpart2 = 14
                                      _uk text assets)
     @360  u32      numStreams        records with hasStream = 1
     @364  u32[6]   languageHeaderOffset   file offset of the localized header
                                      blobs, one per language slot
     @388  u8       lowViolence       OR-ed into the platform's low-violence flag
                                      (0x435c0b, sticky); 389–399 zero
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

*Corrected 2026-10-05 (header fields @32, @327, @328, @388).*

- **@32 is the block version signature**, in block byte order. The engine computes it in
  0x49db60: a CRC over `"8"` (block version 8) and then, for every asset type sorted by name
  hash (script classes and `Asset` itself left out), `"%d"` of the type's version + 0x80000.
  Recomputing that from the PC Part 2 executable gives **0x79D3E0DA**, the value at @32 of every
  Part 2 block (PC, X360, PS3) and of PS3 Part 1; PC and X360 Part 1 carry 0xEE1FB0A3 (another
  build's type versions). The PC loader calls the function (0x4a3b5e) and **discards the
  result**: the file's value is never compared. The X360 Part 2 loader does the same in the
  decompilation; PS3 Part 2 (0x20e850, read from the decompilation only) discards it too.
- **@328 is not the signature.** Earlier versions of this document printed it as the u32
  `0x593F430A`; the bytes are `0a 88 3f 59` (0x593F880A read little-endian) and they are
  identical on the big-endian consoles, where every neighbouring u32 is byte-swapped — so it is
  not a platform-order integer. It is `fingerprintCrc`: the unfolded bit-CRC (`kapow_hash`) of
  the 255-byte plaintext fingerprint field, the text followed by zero bytes (recomputed: the
  54-character default text plus 201 zeros gives 0x593F880A; 254 or 256 bytes, or the folded
  name hash, do not). The loader does not read it and the writer is not in the game executable.
  `parse_block_header` returns the u32 @32 as `version_signature`, the value @328 as
  `fingerprint_crc` with `fingerprint_crc_ok` (does it match the decrypted fingerprint) and
  still the four bytes as `unknown_328` (up to 1.3.0 `version_signature` held the @328 value).
- **@388** is the low-violence flag: 0x4a36d8 passes the byte to 0x435c0b on the platform
  object, which only ever sets the flag; `GetIsLowViolenceMSG` (0x47b135) returns it. It is 0 in
  all nine staged blocks (`low_violence` False).
- **@327** is the fingerprint display mode (`fingerprint_display`; `unknown_327` is kept): 0 =
  the debug overlay (0x490a45, page 2) draws " Finger Print Key: <text>" until 20 s after its
  first draw in the process (the test is t ≥ 20.0 on one process-wide timer, 0xe14400), then
  the engine sets 2; 1 = always; 2 = never. `Unload` resets it to 0 (0x4a0464). It is 2 in all
  nine staged blocks.

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
*[2026-10-04, replacing "which language each slot number means is not
established":]* The slot number is the engine's `LANGUAGE` value (enum
registered at 0x47ff8c): **0 English, 1 French, 2 Italian, 3 German,
4 Spanish, 5 Danish**. That the block slots use this numbering is inferred
from the loader (the slot index is the current language) and checked on data:
the same text asset decoded from the six slots of the main block is English,
French, Italian, German and Spanish in slots 0 - 4 (Parts 1 and 2; PC, X360,
PS3). Slot 5 is a byte copy of slot 0 in every shipped block: no Danish text
exists. The localized records are the 14 text tables of the main block and
one texture (`WB_WatchmenLogo_01_uk.bmp`) of the menu block. The extractor
writes slot 0 to `extracted/` by default (`--language 0..5`) and every
language's text tables to `text/`.

#### Text assets (`textRes`)

    [u32 rows]  rows x ( [u32 n][n UTF-16 units]  [u32 n][n UTF-16 units] )     key, text

`n` counts the terminating NUL. Integers and code units are little-endian on
PC and big-endian on X360 / PS3. There is no other header (loader 0x5387ae).
A `TextSlot` shows row `currentIndex`; only the subtitle slots look rows up by
key (see [TEXT_ASSETS.md](TEXT_ASSETS.md)).

#### Navigation files

`<level>.hpd` (the Kynapse path data) is a plain NAZ entry under
`data/levels/<set>/<level>/gameplay/`, written to `files/` like every entry;
`<Level>.aipathdata` (the world definition) is a block asset. Both formats
are in [NAV_DATA.md](NAV_DATA.md). Part 1 PC keeps its `.hpd` loose in the
game's `data/` folder, spelled `data/Levels/Game_Levels/<Level>/Gameplay/`;
`extract` copies them to `files/` under the archive's lower-case name
(`files/data/levels/game_levels/<level>/gameplay/<name>.hpd`) unless
`--names stored` is given.

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
| `0x62f2722a` | `font` *(named 2026-10-05; registered 0x5431f5)* |
| `0xf1fdbe49` | `terrainColoringAsset` *(named 2026-10-05; registered 0x531981)* |

`font`: three records in each of the five staged main blocks (Parts 1 and 2; PC, X360, PS3):
`DaveGibbons40.font`, `TwCentMTCondExtra60.font`, `default.font`. With the two names added no
record of the nine staged blocks has an unnamed type. `terrainColoringAsset`: no record in any
Part 2 block and none in the three staged Part 1 **main** blocks; Part 1 data has five
`.terraincoloringasset` records (final audit of the full Part 1 extracts on the user's PC; not
re-counted here). Neither type has a decoder: both are written raw.

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

*[Corrected 2026-10-05; this said a blob is compressed "when its first byte is `0x78`".]*
Whether a blob (header *or* stream) is zlib-compressed is decided by the **asset type**, not by
its bytes: `0x5480fe` = config `useCompressedAssets` (default 1) **and** the type's
compressible flag, which every type has except **`mediastream`** (0x554a2e clears it). A
compressed blob is read through zlib inflate bounded by the directory size (0x437546).
`_maybe_inflate(blob, type_name)` follows the type and reports a blob that should inflate and
does not (`extract_block(..., report=...)`, `Toc.compressed`, `Toc.inflate_failed`); only a blob
of an unknown type is still sniffed. Four PC Part 2 blocks: **2,161 header blobs inflate, 7
`mediastream` headers are raw, 444 of 444 stream blobs inflate, 0 failures.**

Engine cross-reference: the asynchronous block loader is `FUN_004a36d8`
(`loadblock.cpp`, log string *"Allocating 2 buffers for asset block loading"*). It
streams `block_s_z` in chunks (chunk-size array at loader-context `+0x1C0`, count at
`+0x1B8 & 0xFFFFFF`) into a ping-pong **double buffer** (`+0x1A4`/`+0x1A8`, indices
swapped at `+0x1AC`/`+0x1B0`, both allocated with `ioBufferSize`), consuming the
`(off,sz)` pairs of the records.

### 2.4 Loading rules and the trailing blob
*Added 2026-10-05 (0x4a36d8, 0x4addf6, 0x4e0e5d, 0x55243f; `LoadBlock` is driven from the end of
the frame with the frame's spare milliseconds and keeps a 5 ms margin).*

1. **Order.** Header (400 bytes) → directory → header blobs in record order, blob *i+1* being
   read by the I/O thread while blob *i* is deserialised (that is what the two buffers are for)
   → at record `numEntries` a seek to `languageHeaderOffset[language]` for the localized records
   → all stream records queued (above) → when every stream is delivered, the trailing blob at
   `fragmentOffset` is read → `ApplyLoaded` (0x4addf6) reads its stream-set tables, applies the
   block's fragment, frees the non-reapplyable fragment buffers.
2. **Stream language.** The stream worker (0x4e0e5d) seeks `offset[language]` and reads
   `size[language]` of the record's six pairs.
3. **An asset must be listed in a loaded block.** With asset blocks in use (`useassetblocks`,
   default true) an asset that no loaded block lists is created **empty** — no header — and a
   notice "single file loading is currently disabled" is logged (0x55243f). It is *not* flagged
   as a missing asset. The "missing asset" mark is set only when single-file loading is forced
   on and the derived file fails to load; the engine does that for its three helper models
   (`/Helpers/unitsphere.model`, `unit_cone.model`, `unit_box.model`, 0x58f050).
   A standalone derived header file (`*.modelres_h_z`, `*.texture_h_z`,
   `*.pivotbook_h_z`) is `[u32 version signature][u32 second word][zlib
   stream]` in platform byte order (measured: the zlib stream starts at
   offset 8 on the 36 such files of the six sets; an `_s_z` file has no
   preamble, its zlib stream starts at offset 0, 5 files checked).
   `watchmen_extract.standalone_preamble` returns it.

   | Type | Part 2 (PC / X360 / PS3) and PS3 Part 1 | Stand-alone Part 1 (PC / X360) |
   |---|---|---|
   | `.modelres_h_z` | 0xEFD1E8BB | 0x520D5FD8 |
   | `.texture_h_z` | 0x9DDD1B02 | 0x9DDC1B02 |
   | `.pivotbook_h_z` | 0x00080002 | 0x00070002 |

   The value carries the type's version plus a build constant: 0x80000 in
   the newer build, 0x70000 in the stand-alone Part 1 build (seen directly on
   the pivot book, version 2, and as the 0x10000 difference of the two
   texture values). The second word differs per file and per platform; that
   it is the source CRC is read from code and was not checked on files. Two
   standalone pairs with the same base name in different folders no longer
   overwrite each other in `extract`: a copy with different bytes is written
   as `<name>~<folder>.<ext>` with a WARNING (none occurs in the six sets:
   three distinct base names each).
4. **Trailing blob** (`parse_block_trailer`; readers 0x4ab461, 0x4a01d7, 0x4e1a59):

       [u32 nAuto]   nAuto × StreamSet                          automatic stream blocks
       [u32 nManual] nManual × { [u32 n][n × u32 pathId] StreamSet }   → a StreamBlockNode found by path
       StreamSet = [f32×3 min][f32×3 max][str streamFile][u32 = count][u32 count]
                   count × { [u32 typeHash][str name] 6 × ([u32 offset][u32 size]) }

   *Corrected 2026-10-05 from data.* The bounds are two 3-float vectors (this section
   said two 4-float vectors, from the code reading; `parse_block_trailer` tries the
   4-float layout only when the 3-float one does not end at the blob's end and
   reports `bounds_floats`). Both counts are 0 in every shipped block but one: the
   blob is eight zero bytes and `fragmentOffset == fileSize − 8` in the 7 blocks of
   each Part 2 set and in 7 of the 8 of each Part 1 set. **Part 1's
   `Prison.block_h_z`** has a blob of 11,765 / 11,769 / 11,773 bytes (PC / PS3 /
   Xbox 360) with 0 automatic and 4 manual sets of 26 + 24 + 8 + 38 = 96 entries
   (65 models, 31 textures; 92 distinct assets).
   - `streamFile` is a full path from the platform's derived root, e.g.
     `/derived_pc/Levels/Game_Levels/Prison/Art/PrisonYard.block_s_z`. The four
     files are **stream-only blocks**: a `.block_s_z` with no `.block_h_z`.
   - An entry's asset is in the Prison directory with `hasStream` 0; its six
     offset / size pairs point into the stream file, whose blobs are zlib like any
     other stream. Each file is exactly the sum of its entries; all 96 inflate.
   - Four names are listed in two sets; whether both copies hold the same bytes
     was not compared (the first set that resolves is used).
   - `extract` resolves these streams (`block_stream_sets`, `stream_file_lookup`,
     `extract_block(..., stream_files=)`) and prints a `STREAM SETS` section.
     Automatic sets and `%03d.block` multi-part streams occur in no shipped block,
     so those two layouts are from the code only.
5. **Path variants** (0x54e890 / 0x54eac3): with the localize flag `/uk/` → `/<code>/` and `_uk`
   → `_<code>`; with the platform flag `_pc` → `_<platform>`; with the low-violence flag `_lowv`
   before the extension. The variants are tried in order, then the plain path.
   No shipped set contains a `_lowv`, `_<platform>` or non-`uk` language sibling; console archives
   keep the `_pc` and `_uk` names (measured, 66,499 paths, six sets).
6. **Frame-time budget.** Frame-time target 33.333 ms (`Gfx+0x10`, f32 0x9e9350); budget =
   target − ms since the last present − 1.0 (0x42af4f); the loader works while more than 5 ms of
   it remain (0x4a36d8).
7. **`_lowv` file variants are never tried on PC**: `AssetManager+0xec` is written only by the
   constructor (0x550aaa).
8. **Unloading.** `Unload` (0x4a02f0) frees whole allocators and child nodes, not single assets;
   an asset listed again by a later block is destroyed and rebuilt in place with its name,
   reference count and referrers (0x551f10).
9. **StreamingProbe**: sector 0 = inside `sector0Radius`, 1 = inside the frustum, 2 = inside
   `sector2Radius` (0x4e244e); priority key = sector code (0, 0x20000000, 0x40000000; 0x60000000
   otherwise) | int(distance × 100) & 0x1FFFFFFF, smallest first (0x4de3b3). No Part 2 block has stream sets; Part 1 `Prison.block_h_z` has four manual sets (rule 4; measured).
10. **PS3 Part 2** (0x20e850) discards the signature result, as PC does.

*(Rules 6–10 read 2026-10-06.)*

**Memory budgets.** The PC Part 2 executable embeds the engine configuration for every platform
(text at 0xc8f178, 3,630 bytes; reader 0x41cf54; suffixes K / M / G shift by 10 / 20 / 30):

| Key | editor | ps3 (testkit) | ps3_devkit | x360 | pc |
|---|---|---|---|---|---|
| MoviePlayerBlock | 6300K | 5320K | 5320K | 5877K | 6300K |
| PhysicalBlock | 0 | 8M | 6M | 49151K | 0 |
| PhysXBlockNormal / Large / Cloth | 0 / 0 / 0 | 11M / 10M / 0 | 11M / 10M / 0 | 10M / 12M / 850K | 12M / 17M / 1M |
| KynapseBlock | 0 | 10000K | 10600K | 12M | 12M |
| SceneNodeBlock | 0 | 17000K | 16M | 19M | 25M |
| DefragmentingBlock | 20M | 4608K | 4608K | 4608K | 7M |
| DefragmentingTableSize | 65534 | 65534 | 65534 | 65534 | 65534 |
| AssetBlock | 256M | 56M | 58M | 262143K | 512M |
| GfxBlock | – | 256M (clamped to local memory minus AssetBlockGfx) | 256M | – | – |
| AssetBlockGfx | – | 187M | 187M | – | – |
| TempBlock / TempThreadBlock | 16M / 2M | 768K / 128K | 768K / 128K | 768K / 128K | 768K / 128K |
| ListTypeStructPoolSize | 128K | 128K | 128K | 128K | 128K |

*(Every value re-read from the executable's bytes on 2026-10-05.)*

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

**The header states its byte order** *(added 2026-10-05, from data)*: `typeNameLen`
is in the byte order of the block the header came from, and it is a valid name
length in one order only, so an extracted header can be read without knowing
its platform (`watchmen_extract.header_order`; 5,490 of 5,490 model headers of
six sets — Parts 1 and 2 on PC, Xbox 360, PS3 — say so, and the result agrees
with the platform). The toolkit uses this for every header it reads outside
its block (character parts, ragdoll rig, model nodes, skeleton names). A rule
that counted mesh descriptors per order tied on single-submesh models and
picked the wrong order on 87 console Part 2 and 156 console Part 1 models.

**Property records, two layouts** *(added 2026-10-05, from data)*. A record of
the bag is `[u32 owner][u32 key][u32 typeHash][u32 k][k dwords]` in Part 2 and
in the PS3 build of Part 1 (block signature 0x79D3E0DA). The standalone Part 1
on PC and Xbox 360 (signature 0xEE1FB0A3) stores `[u32 owner][u32 key][u32 k]
[k dwords]`, without the type hash. The object header `[u32 len][name][u32
dwordCount]` is the same, so the layout of an object is the one whose records
end exactly at its dword count; nothing is guessed. Value types of the older
layout are those the typed build stores for the same (class, property): 260
pairs, 140 names, each with one type (`kapow_props.untyped_types`), covering
every pair that occurs. `kapow_props.read_records` / `find_objects` read both;
texture sheets, `.pb`, `.grass`, `.detailmesh` and the model property bag go
through them. Read from the data, not from an executable. A 64-bit value
(`uniqueID`, type hash 0xEDEF427C) is two u32 words, low word first, on every
platform; console swaps the bytes of each word, not of the eight.
The older **ModelRes header** (the type-specific body after the bag) differs
in one more byte per submesh record and is read as well: see "The stand-alone
Part 1 header" in §6b (`parse_model_header` reads 1,090 of 1,090).

*Corrected 2026-10-02.* The u32 after the type name was documented as a
"classId / version" (`0x2D` for textures, `0x5B` for models). It is the
dword count of the property bag (engine `FUN_00511f96`): 45 for `Texture`, 91
for `ModelRes`, 55 for `TextureEffects(Texture)`, 96 for
`ModelEffects(ModelRes)`. The body starts at
`4 + typeNameLen + 4 + 4·bagDwords`.

Reading `typeName` is how you classify an asset without guessing. **In situ
(bordello)** the class histogram is roughly: 843 `sound`, 273 `Texture`, 217
`ModelRes`, 76 `ModelEffects(ModelRes)`, plus particle systems (their format:
[PARTICLE_FORMAT.md](PARTICLE_FORMAT.md)), grass, detail
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
 if hasAnim:
   u32 serial
   Cycle:  u32 mode (1 = pingpong, else loop), i32 repeat (−1 = endless; 0x52c6f5), u32 (no reader found)
           u32 nSteps;  nSteps x { u32 isSubCycle, u32 index }
           u32 nItems;  nItems x { u32 frameMin, u32 frameMax, u32 timeMinMs, u32 timeMaxMs, u32 id }
           u32 nSub;    nSub x Cycle
 embedded TextureSheet objects (virtual at Texture+0xb0; §4.7)
```

The animation block (read from code: readers 0x53345a, 0x530639, 0x529337): a step
with isSubCycle 0 plays item `index`: a random frame in [frameMin, frameMax]
(0x52929b) for a random time in [timeMinMs, timeMaxMs] ms (0x5292bb). The name
`id` is inferred (the code only stores the value). `parse_texture_frames`
returns the block as `anim_tail` and `sheet.json` carries it as `animation`,
plus `frame_ms` (one entry per frame) where an item shows exactly one frame for
a fixed time. Measured: four Part 2 textures have the block (`Caustics01_001`,
`Caustics01_001_g`, `movie_projection0000`, `SavingAnim01`; 32, 32, 51 and 32
frames) and one Part 1 texture (`Caustics01_001_g`), on PC, Xbox 360 and PS3
alike, every frame for 65 ms.

The property bag is 20-byte records, each beginning with the same per-asset
`salt` u32. A plain `Texture` has 9 of them (45 dwords), so its body begins at
offset 196; a `TextureEffects(Texture)` has 11.

The source path gives **100 %-correct asset names** and the folder tree to
rebuild on extraction.

### 4.2 The image descriptor (per slot)

```
 Desc (29 bytes): u32 width, u32 height, u32 format,
                  u32 usage (0 in block textures and fonts, 1 in the terrain colouring maps; 2 = dynamic, 3 = render target, 5 = depth-stencil on engine-made buffers; 4 = managed with one level; 0x456d46),
                  u32 type (1 = 2D, 2 = cube), u8 hasAlpha, u32 mipCount,
                  u32 x360Size (stored byte size of the layer for the Xbox 360 target,
                                written by the converter 0x45473f; 0 on PC and PS3)
```

*Console (added 2026-10-05, from data):* the Xbox 360 and PS3 texture header is
this same layout in big-endian (`parse_texture_frames(hdr, ">")`). On Xbox 360
the last u32 of the descriptor is the **stored byte size of that layer** (0 on
PC and PS3); the sizes add up to the stream length on 937 of 937 Part 2 and
1,190 of 1,190 Part 1 textures, and for a cube layer the size is six times the
2D rule. `extract` plans the console carve from this header and falls back to
the stride walk, with a `WARNING:` line and `decodeWarnings` in `sheet.json`,
only when it does not read (0 times on the four console sets).

`hasAlpha` of slot 0 is what enables the alpha test (0x429e77 → 0x571d5d); `sheet.json`
records it as `textureHasAlpha`.

The slot index is the layer's role (read from code: the loader 0x5382aa stores
file slot *i* at frame +4·*i*; the sheet asks by **engine layer**, 0x4991f0 /
0x49be2d and the accessors 0x49bcbe…0x49bdff; the names are those of the
`Get…MapOverrideName` getters 0x523d0e…, `fallOff` by elimination). The
renderer counts engine layers, the file counts slots:

| File slot | Engine layer | Role | Sheet override | Default when the slot is absent |
|---|---|---|---|---|
| 0 | 0, 1 | diffuse | +0x190 | always present |
| 1 | 2 | normal (`ATI2`) | +0x19c | Gfx+0x598 (bytes 80 80 80 80) |
| 2 | 4 | specular (`DXT1`), "specMap" | +0x1a8 | +0x59c (white) |
| 3 | 5 | glow (`DXT1`) | +0x1b4 | +0x59c |
| 4 | 3 | height (`L8`), the parallax map | +0x1c0 | +0x5a0 (bytes ff 00 00 00; opaque black, inferred) |
| 5 | 6 | fallOff | +0x1cc | +0x59c |
| 6 | 7 | ambOcc | +0x1d8 | +0x59c |
| 7 | 8 | specSize (`L8`), the specular-power map | +0x1e4 | +0x5a0 |

When the texture itself is not loaded the sheet uses other fallbacks: diffuse
and specular +0x5a0, normal +0x598, height and specSize +0x5a0, glow, fallOff
and ambOcc +0x59c (0x49bcbe…0x49bdff). The shaders' use of the height layer was
not re-read.

Measured on every texture header of the six sets (937 per Part 2 set, 1,206
per Part 1 set; the three platforms agree): Part 2 has slot 3 on 59 textures
(lamps, neon signs, windows, TV and movie screens), slot 4 on 10 (ground, floor
and roof textures plus `pickupWindows`) and slot 7 on 55; Part 1 has slot 4 on
24 and slot 7 on 33; slots 5 and 6 occur on none. `extract` names every layer
PNG by its slot (`watchmen_extract.TEXTURE_SLOT_LABELS`): `diffuse`, `normal`,
`specMap`, `glow`, `height`, `fallOff`, `ambOcc`, `specSize`. In 1.3.0 a slot-3
map without a slot-2 map was written `_specMap_` (15 textures per Part 2 set,
23 per Part 1 set) and a slot-4 map `_specSize_` (10 and 24), and the material
writers used them as a specular-colour map and a specular-power map. The
format rule that produced those names is kept only for a layer whose slot is
not known (the stride walk and the drift rescue, which decode no shipped
texture).

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
| 3 / 4 | `L8` | linear, 1 B/px (grayscale; used for the specSize and height maps) |
| 5 | `DXT1` (BC1) | block, 8 B / 4×4 |
| 6 | `DXT3` (BC2) | block, 16 B / 4×4 |
| 7 | `DXT5` (BC3) | block, 16 B / 4×4 |
| 9 | `ATI2` / `BC5` | block, 16 B / 4×4 — a two-channel **normal map** |
| 8 (Xbox 360 only) | `DXT3A` | block, 8 B / 4×4, 4 bits per texel — the height map, in slot 4 where PC has `L8` |

*Format 8, added 2026-10-05:* the Xbox 360 executable's table at 0x830892d8
maps id 8 to DXT3A. The name and the nibble order are inferred and then
confirmed by pixels (1 layer identical, 32 within tolerance against the PC `L8`
map). No PC path accepts id 8. On Xbox 360 the slot-7 specular-size map is
`DXT1` (PC and PS3: `L8`); `extract` writes its red channel as a grayscale PNG
(red matches the PC map within a mean of 8.4 on 88 of 88; which channel the
console shader samples was not read from code). The `L8` / `DXT3A` map of
slot 4 (10 + 24 textures in Parts 2 + 1) is the height map and is written
`_height_`; the one of slot 7 (55 + 33) is `specSize`. File slot 7 is engine
layer 8 (table above).

**Cube maps** *(added 2026-10-05, from data; 110 cube maps in Part 2, 200 in
Part 1)*: the stream holds
- on PC: the mip **levels** one after another, six faces per level;
- on Xbox 360: the same, each face of a level padded to 32 × 32 blocks, so
  face *k* of level 0 starts at *k* × the padded level-0 size (a cube under 32
  texels packs its tail differently: only face 0 is written, with a warning;
  none is shipped);
- on PS3: one segment of six face mip chains, each but the last padded to 128
  bytes (segment size = 5·align128(C) + C on 310 of 310; the mip count is
  byte 13 of the 36-byte segment descriptor).
Read this way all six faces of all 310 maps are pixel-identical on the three
platforms. Up to this correction the extractor read a PC cube as six face
chains — only face 0 is right that way — and wrote one face on PS3
(`watchmen_extract.PC_CUBE_LEVEL_MAJOR = False` gives the old PC reading).
Code: 0x454384 reads level by level, six faces per level, into the pointers
0x454492 took from `LockRect(face, level)`; file face *k* is D3D cube face *k*
(+X, −X, +Y, −Y, +Z, −Z). `sheet.json` of a cube map states it as
`cubeFaceOrder`; the `faceN_` file names are unchanged. Runtime check
(measured): in the D3D9 gameplay captures the six level-0 face uploads of 94
cube textures match file slices 0…5 in that order.

A typical material packs: slot 0 diffuse (`DXT1`/`DXT5`), slot 1 normal
(`ATI2`/BC5), slot 2 specular (`DXT1`), optionally slot 7 **glossiness**
(`L8`) — the gloss / specular-power channel (not a reflection mask).

*Corrected 2026-10-03:* the two channels of a PC `ATI2` layer are stored **Y
block first, X block second** (each 8 bytes of the 16-byte block). Earlier
versions of this document did not state the order and the extractor read the
first block as X; see §4.5.

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
observed). The face order inside a PC cube stream is read from code (0x454384,
above).

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
  *Corrected 2026-10-03:* on PC (format enum 9) the **first** 8-byte block of
  each 16-byte block is **Y** and the **second** is **X**
  (`watchmen_extract.ati2_xy`). Up to toolkit 1.3.0 the extractor wrote the
  first block to red, so every PC `*_normal_*_ATI2.png` it produced has X and
  Y swapped; PNGs from those versions must be extracted again. The X360
  layers (enum 10) and the PS3 `DXT5` layers decode X-first and were always
  right. In the written PNG, red is X along +u and green is Y along +v (the
  direction of the stored bitangent); a glTF normal texture needs green
  inverted. Evidence — the pixel shader pairs sampler `.x` with the tangent
  and `.y` with the bitangent, the mixed partials of the maps agree only in
  that order, and a render test — is in `ENGINE_CONSTANTS.md`, section
  "2026-10-03".
- **X8R8G8B8 / A8R8G8B8** → raw 4 B/px, swizzle BGRA→RGB.
- **L8** → raw 1 B/px grayscale.

The on-disk data is the **authored** mip chain; the GPU copy at run time may be one
or more mip levels smaller (the engine drops top mips under memory pressure). Decode
the top stored mip for maximum resolution.

### 4.6 Material switches in the property bag (`sheet.json`)

*Added 2026-10-03.* The 20-byte records of the header's property bag (§4.1)
are `[salt u32][name hash u32][type hash u32][tag u32][value]`, both hashes
being the engine name hash of the strings. Nine of the names are the
TextureSheet's material switches (`watchmen_extract.TEXTURE_SHEET_PROPS`):

| property | type | meaning |
|---|---|---|
| `renderType` | integer | 0 Standard, 1 Standard with blending, 2 glass, 3 water, 6 hair, 7 skybox, 9 sprite, 10 falloff, 11 wet |
| `twoSided` | truth | the byte the renderer turns into `D3DCULL_NONE` (`FUN_00571d5d`, sheet+0xA4); one-sided materials are drawn with `D3DCULL_CW` |
| `alphaThreshold` | integer | alpha-test reference, 0..255 (the D3D9 capture shows `D3DRS_ALPHAREF 95`) |
| `normalMapPower` | number | scales the normal map's x and y (`$effectFactors.x`) |
| `enableNormalMapping` | truth | when false, `extract --glb` embeds no normal texture |
| `opacity` | number | below 0.99 a type 0 / 10 sheet is drawn in the blended list (0x5739d0) and a type 7 sheet is faded by the sky pass (0x589dd9: the pixel shader's alpha factor); exported as `BLEND` with the opacity as base-colour alpha |
| `blendType` | integer | 0 standard, 1 add, 2 subtract, 3 manual. The character writer turns a subtractive layer (Rorschach's inkblots) into black ink with alpha, `alphaMode: BLEND`; `extract --glb` does not use it *(corrected 2026-10-04)* *[corrected again 2026-10-04: `extract --glb` uses it too, with the same code; §4.7]* |
| `isLit`, `writeDepthBuffer` | truth | recorded, not used by the GLB writers |

`texture_sheet(header)` returns them for the first sheet of the header (later
sheets hold defaults *[corrected 2026-10-04: a texture can hold several named
sheets, each with a `uniqueID` and eight `<layer>MapOverride` paths, and a
collection node can select one of them; they are alternatives, not defaults.
`face_rule.texture_sheets` reads them all. See `ENGINE_CONSTANTS.md`, section
"2026-10-04", "Texture sheets"]*); texture extraction writes them as `sheet.json` beside
the layer PNGs, and the GLB writers map `twoSided` → `doubleSided`,
`renderType` 1 → `alphaMode: BLEND`, `alphaThreshold` / 255 → the `MASK`
cutoff and `normalMapPower` → the normal texture's `scale`.
*[2026-10-04: that is the mapping of `--materials legacy`. The default now
builds the whole material from the sheet (`wlib/materials.py`):
`twoSided` → `doubleSided`. Alpha follows the render list the engine sorts
the sheet into (`renderType`, 0x5739d0): types 0, 10 and 11 are opaque and
alpha-tested at `alphaThreshold` / 255 when the diffuse layer has alpha
(`MASK`; hair included); type 1, and `opacity` below 0.99 on a type 0, 7
or 10 sheet, are blended (`BLEND`, `opacity` as base-colour alpha). `normalMapPower` → the normal
texture's `scale`. `specularSize` is the exponent n of the game's highlight
(multiplied per texel by specSize.g² · 256 + 1 when the texture has a
specSize layer), `specularPower` its intensity: roughness = (2 / (n +
2))^0.25, reflectance F0 = 4 · (2 / (n + 2)) · intensity · specular layer,
written with `KHR_materials_specular` and, above 0.04, `KHR_materials_ior`;
both are corrected for the game lighting display-encoded values. A sheet
without any highlight (`specularPower` ≤ 0 and no cube reflection, or F0 = 0
everywhere) is written with roughness 1.0 and no roughness texture, so that
it is matte also where the specular extension is ignored.
`selfIlluminance` · `selfIlluminanceColor` · glow layer · (albedo + specular
layer) is the emission. Missing layers count as: specular white, glow white,
specSize black. The sheet's values are copied to
`material.extras.watchmen.sheet_values`. Sheet offsets in the executable:
`specularPower` +0x8c, `specularSize` +0x90, `writeDepthBuffer` +0xa1,
`twoSided` +0xa4.]* The names come
from the registration strings of texturesheet.cpp in the executable, the
`renderType` values from the editor's dropdown string; the `twoSided` byte
and the cull modes are read from code and confirmed on the capture
(`re/vcolor.md` §5).

### 4.7 Texture sheets: several per texture, layer overrides, blend

*Added 2026-10-04.* A Texture header holds one or more TextureSheets, one
after the other, each a run of property records (§4.6) sharing one salt. A
record is `[salt u32][name hash u32][type hash u32][payload dwords
u32][payload]`; a string payload is `[length u32][bytes, NUL-padded to 4]`.
Part 2 PC: 936 textures, 769 with one sheet, 123 with two, up to eight.
`watchmen_extract.texture_sheets(header)` returns them in file order, and
`sheet.json` lists them under `sheets`.

| property | meaning |
|---|---|
| `name` | the sheet's name ("default", "Black", "BlueButton", "New Sheet0" …); unique within a texture in the shipped data |
| `uniqueID` | 64-bit id (type hash 0xEDEF427C, payload = high dword, low dword). This is what a fragment refers to |
| `diffuseMapOverride`, `normalMapOverride`, `specularMapOverride`, `specSizeMapOverride`, `glowMapOverride`, `heightMapOverride`, `fallOffMapOverride`, `ambOccMapOverride` | asset path of another texture whose layer of the same kind replaces this one. Empty = the texture's own layer. 43 textures use them, 3 on their first sheet |
| `twoSided`, `alphaThreshold`, `opacity`, `writeDepthBuffer`, `isLit`, `normalMapPower`, `specularPower` (intensity), `specularSize` (exponent) | per-sheet material switches (§4.6); the exporters take them from the sheet the part wears |
| `blendType` | 0 standard, 1 add, 2 subtract, 3 manual; used for render types 1, 7 and 9, and for a type 0 / 10 sheet with opacity below 0.99 |
| `srcBlend`, `dstBlend`, `blendOp` | for `manual`: Direct3D `D3DBLEND` 1…11 and `D3DBLENDOP` (1 add, 2 subtract, 3 revSubtract, 4 max, 5 min) |
| `uScrollSpeed`, `vScrollSpeed`, `u2ScrollSpeed`, `v2ScrollSpeed`, `enableAnimation` | UV scroll and frame animation. In `sheet.json` only; not written to glTF |

Which sheet a mesh wears is not in the texture: the first, unless the
fragment node that places the model names another. The node's
`textureSheetsDescription` is a comma-separated string:

```
2,<slot>,<pivot>,<lod>,<texture path>,<sheet uniqueID>,   … repeated   (version 2)
1,<slot>,<pivot>,<texture path>,<sheet uniqueID>,         … repeated   (version 1)
```

`slot` indexes the node's `modelNames`. A record applies to the meshes of
that slot, pivot and LOD whose texture path equals the record's; an id the
texture does not have selects the first sheet; the last matching record
wins. `characters_export.sheet_records` parses both versions,
`variant_sheets(…, node=k)` resolves one outfit node.

Seen at run time (measured, three draws of a D3D9 gameplay capture): the
Heavy's `Heavy_Button` sheet `BlueButton` draws with the diffuse of
`Heavy_ButtonBlue.bmp` and the normal map and constants of `Heavy_Button.bmp`.
The engine takes entry `sheet+0x6c` of the override texture's frame table
(0x49bcbe; the meaning of +0x6c is inferred); the exporters take the override
texture's first layer file of that kind, which is the same thing unless the
override texture has more than one frame (no case was looked for).

How the exporters write a blend type (`watchmen_extract.sheet_blend`,
`blend_material`; engine states in `ENGINE_CONSTANTS.md`, "Blend states"):
`standard` → `alphaMode: BLEND`; `subtract` → the layer rewritten as black
with alpha = brightness × alpha (exact over white); `add`, and a manual
SRCALPHA or ONE / ONE ADD → base colour black, the layer normalised to full
brightness as emissive texture, alpha = its peak × alpha (an approximation);
any other manual blend → the raw layer, no alpha mode. The material's
`extras.watchmen` holds `blend`, `src`, `dst`, `op`. OBJ/MTL cannot express a
blend equation and links the raw layer.

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
 u32 maxLodIndex, bool hasSkeleton, u32 skinnedBoneCount (0x53db65; 0xFFFFFFFF without a skeleton), bool hasCloth, [u32 n][n×32 B bone boxes: min, max], [u32 n][n×4 B bone index]
 vec3 bboxMin, vec3 bboxMax
 u32 nTex  { bool flag (asset flag bit 4, 0x543e10); string path }            texture list
 u32 nPb   { string path }                  pivotbooks
 u32 nParts { Part }
 … articulated body (ragdoll), optional cloth object: see "Articulated body" below;
   list `[u32 n]{f32, string name, [u32 m][m × 8 B]}` (ModelRes+0x134, writer 0x543e10;
   searched by name by 0x4b38b6 and sized into `Character`'s channel arrays by 0x4b9bfe, so
   inferred to be the morph-channel list); not parsed

 Part:    vec3 pos, quat (xyzw), string name, u32, i32 parent
          u32 nLods { u32 nSub { Submesh } }
          u32 nGroups { u32 n { bool fromCloth; i32 clothSubmesh; MeshBuffer } }      shadow hulls
              (0, −1) = merged hull, (1, i) = hull of cloth submesh i (0x544ae4)
          bool; MeshBuffer if set                               per-part occluder mesh
          2 × [ u32 n { collision volume } ]                    see FORMATS_MISC.md
          u32 n { surface }
 Submesh: string name, [u32 1][u32 textureIndex], bool, bool inline, u32, bool, bool hasClothMesh,
          MeshBuffer, [u32 size][cooked PhysX cloth]
 MeshBuffer: vec3 bboxMin, vec3 bboxMax, u8 hasColor, u8 hasAlpha, bool hasClothMesh,
          u32 flags, u32 vertexCount, u32 FORMAT,  u32 flags, u32 indexBytes, u32 primitiveType
```

- Every part is a node: `pos` / `quat` are its pivot, `parent` its parent index.
- `textureIndex` indexes the model's texture list; that is the submesh's
  material.
- A part has one or more levels of detail, each a list of submeshes.
- `FORMAT` is the vertex format id (what earlier versions called `G`).
- `indexBytes` is a byte count of `u16` indices; the last `u32` of the MeshBuffer is the primitive
  type: 0 triangle strip, 1 triangle list (table 0xc7f398 = D3D 5, 4, 6, 1, 2, 3; count rule
  0x417bf2; triangle rule 0x431206: `(i, i+1, i+2)` for even i, `(i+2, i+1, i)` for odd i).
  Measured on all three platforms: Part 2 has strips on 12 render buffers (`Palm_Banana_01`,
  `palm_banana_02`) and all 79 occluders; Part 1 on 2 render buffers (`Sky_Night_01`) and all 141
  occluders; every shadow hull is a list. `decode_model` and `decode_model_mesh` read a strip as
  a strip (`index_triangles`); `<model>.model.json` names it per submesh (`primitive`).
- `maxLodIndex` equals (largest LOD count − 1) on 740 of 740 PC Part 2 and 1,090 of 1,090 PC
  Part 1 models (measured; writer 0x543e10).
- *Added 2026-10-03:* `hasColor` (at +0x31 of the engine's MeshBuffer) is what
  makes the renderer pick the `VERTEX_COLORS` vertex shader for the buffer;
  without it the colour bytes are not read and are all 255. `hasAlpha` (+0x32)
  marks a buffer whose vertex alpha varies and implies `hasColor`. On the
  files, 1,204 format 5 / 6 buffers have neither flag, 1,400 `hasColor` only,
  53 both; 387 of 735 Part 2 PC models have at least one coloured buffer
  (`re/vcolor.md`).

**Stream blob** — for each MeshBuffer in header order (per part: the submeshes
of every LOD, then the shadow groups, then the proxy slab):

```
 vertexCount × stride[FORMAT]    vertex data
 indexBytes                      u16 indices
 [u32 n]{f32×4 boxMin, f32×4 boxMax, u32 firstIndex, u32 endIndex}  cluster table (0x4326a0; index positions; the last ends at index count − 2)
 [u32 n]{u32 channel, u32 count, count × 0x44 B} morph targets: u32 vertexIndex, then four
     float4 deltas at +4, +0x14, +0x24, +0x34, added times the channel weight to the vertex at
     +0, +0xc, +0x1c, +0x24 (0x430abd)
 [u8 has][vertexCount × {u16 vertex, u16 face0, face1, face2}]  only on cloth shadow hulls (3 of 1,154 buffers in the StreetsOfRiot block); that the values index the cloth submesh's vertices is inferred
```

| FORMAT | stride | layout |
|---|---|---|
| 5 rigid | 44 | pos f32×3 @0 · normal half3 @12 · colour BGRA @20 · uv half2 @24 · tangent half3 @28 · bitangent half3 @36 |
| 6 skinned | 56 | format 5 + joints @44 (idx0..3 = bytes 46, 45, 44, 47) · weights half4 @48 |
| 9 shadow hull | 20 | pos f32×3 @0 · normal half3 @12 |
| 10 skinned hull | 32 | format 9 + joints @20 · weights half4 @24 |

*[2026-10-05] Console files (Xbox 360 and PS3, both parts)* have the same
header and the same stream structure with other sizes: vertex strides
`[28,24,68,16,56,32,44,60,36,16,28]` (Xbox 360 exe table `0x8308b6e0`), a
**48**-byte cluster record (the PC 40 bytes plus `7FFFFFFF 00000000`) and
**0x50**-byte list items (PC 0x44). With these the computed layout consumes the
stream to the last byte on every console model that has one: 735 / 735 on each
Part 2 console set, 1,085 / 1,085 on each Part 1 console set. Everything is
big-endian.

| FORMAT | stride | console layout |
|---|---|---|
| 5 rigid | 32 | pos f32×3 @0 · normal packed @12 · colour @16 · uv half2 @20 · tangent packed @24 · bitangent packed @28 |
| 6 skinned | 44 | format 5 + joints @32 (idx0..3 = bytes 33, 34, 35, 32) · weights half4 @36 |
| 9 shadow hull | 16 | pos f32×3 @0 · normal packed @12 |
| 10 skinned hull | 28 | format 9 + joints @16 (idx0..3 = bytes 17, 18, 19, 16) · weights half4 @20 |

`packed` is one u32 holding x in 11 bits, y in 11 bits and z in 10 bits, signed,
from the low bit up (x, y / 1023, z / 511). The offsets are read from data: the
console copy of a model has the same vertices in the same order as the PC copy,
and on all 3,640 console models with a PC counterpart every decoded field
agrees with it vertex for vertex — triangles, UVs, joints and weights exactly;
normal, tangent and bitangent within 0.002 per component. Console positions are
f32 but coarser than the PC ones (differences in power-of-two steps, up to
0.5 m on the sky domes): that is in the files. Format 10 joints and weights
equal the PC copy vertex for vertex on every console model with a PC counterpart
(measured: 104 buffers / 99,312 vertices on each Part 2 console set, 130 / 153,992
on each Part 1 console set). The joint order is also read from the PS3 vertex
programs (`precompiled_shaders/shader.archive`, the same file in Part 1 and Part
2): all 22 skinned programs multiply `indices.yzwx` by `c[467].x` = 256, floor,
multiply by `c[467].y` = 3 and load the address register, and pair weight 0..3
with indices y, z, w, x (three constants per bone from `c[40]`). 19 programs take
indices from attribute 4 and weights from attribute 11 (format 6); the three
skinned `ShadowVolumeVS` programs take attribute 3 and attribute 8 (format 10).
The PS3 declaration (`p2.elf` 0x01821f48; `p1.elf` 0x01711f40, byte-equal) gives
the joints as four unsigned bytes like the colour; the rotation is in the shader.
That the four bytes reach the shader in memory order is inferred (shader rule
plus the measured byte order; 40 programs read the colour attribute unswizzled).
19 `Grass` / `GrassDepth` programs read attribute 3 as `.yzwx`; their vertex
format was not identified.

*[2026-10-06]* Both consoles' own format tables say the same, read from code.
Xbox 360: the vertex declarations at `0x82235e68…` (12-byte
`D3DVERTEXELEMENT9` records); the 44-byte one at `0x82236078` (format 6; that
format 5 is its first 32 bytes is from the strides and the data) is
POSITION FLOAT3 @0, NORMAL HEND3N @12, COLOR 0 `D3DCOLOR` @16, TEXCOORD 0
FLOAT16_2 @20, TEXCOORD 1 / 2 HEND3N @24 / @28, COLOR 1 `D3DCOLOR` @32 (the
joints), TEXCOORD 3 FLOAT16_4 @36. PS3 (Part 2 ELF): a table of 11 records
`{u32 count, u32, element pointer}` at `0x01821f48`, read by the stream
binder `0x001538e8`; an element is 12 bytes `{u8 stream, u8 attribute, u8
count, u8 type, u8 stride, 3 pad, u32 offset}` and goes to
`cellGcmSetVertexDataArray` (`0x012a0f18`). Its strides are 28, 24, 68, –,
24 + 56, 32, 44, 60, 36, 16, 28 — the Xbox 360 strides — and formats 5 / 6
are attribute 0 three floats @0, attribute 2 one 11-11-10 word @12,
attribute 3 four unsigned bytes @16, attribute 8 two halves @20, attributes 9
/ 10 one 11-11-10 word @24 / @28, attribute 4 four unsigned bytes @32,
attribute 11 four halves @36. Format 10 there: position @0, 11-11-10 normal
@12, four unsigned bytes @16, four halves @20.

**Console vertex colour** is the one field the two consoles store differently:
bytes A, R, G, B on Xbox 360 (a big-endian `D3DCOLOR` dword) and R, G, B, A on
PS3 (four unsigned bytes, in memory order) — the two format tables above. A
Part 2 model does not name its console: the Xbox 360 and PS3 copies of a
model differ only in the colour bytes, in per-build owner ids of the property
records and in leftover words of the cluster records (13 models compared byte
for byte). So the console comes from where the model was read
(`console_color_order`, `CONSOLE_COLOR_ORDERS`), in this order:

1. `WATCHMEN_CONSOLE=x360` or `ps3` (environment), or
   `watchmen_extract.set_console_platform()`;
2. the source path: a block path inside the `.naz` starts with `derived_x360/`
   or `derived_ps3/` (every block of both Part 2 console sets and of PS3
   Part 1), and the loose Xbox Live Part 1 tree is the directory
   `derived_x360`. `extract` passes this to every model. For files already
   extracted (`characters`), `console_platform_for` looks for
   `<EXTRACT_OUT>/files/derived_x360` or `derived_ps3`, and failing that takes
   the order the next rule gives on other models of the same tree (inferred);
3. inferred from the model's data: a buffer without the `hasAlpha` flag has
   alpha 255 on every vertex (all 6,419 such buffers of PC Part 1 + Part 2), so
   the byte that is 255 throughout those buffers is the alpha (equal to the PC
   buffer on all 13,378 console buffers this rule decides);
4. a big-endian header in the stand-alone Part 1 layout is Xbox 360 (of the
   four console sets only Xbox Live Part 1 has it: 1,090 of 1,090 headers).

Rule 3 alone left 13 / 13 / 22 / 23 models open (Xbox 360 Part 2 / PS3 Part 2 /
Xbox 360 Part 1 / PS3 Part 1: water surfaces, puddles, sky domes, decals and
the two Rorschach bodies — every render buffer has `hasAlpha`, or both end
bytes are 255 throughout). With the console from rule 2 all 71 decode, and
every colour of their 198 render buffers (59,858 vertices) equals the PC copy
exactly, as do the `hasColor` / `hasAlpha` flags. When no rule applies (a loose
big-endian Part 2 model with nothing naming its console) and the colours are
not plain white, they are **not decoded**: no COLOR_0, `"not_decoded":
["COLOR_0"]` in `<model>.model.json` and a `note:` line; normals and tangents
are still written, in the character GLBs too
(`asset.extras.watchmen.not_decoded.vertex_colour`).
`WATCHMEN_CONSOLE_MODELS=scan` sends console models back to the descriptor
scan.

Positions are raw floats; there is no quantisation, scale or bias in any
format. UVs are raw half floats with no scale, bias or V flip. The stride
table (`0x00C791B0`) has 11 formats; only these four occur in `.model` files
(Part 2 PC: format 5 ×2370, 6 ×287, 9 ×357, 10 ×104).

*Added 2026-10-03 — what the colour, tangent and bitangent fields are*
(`re/vcolor.md`; details and addresses in `ENGINE_CONSTANTS.md`, section
"2026-10-03"):

- **colour @20** is a `D3DCOLOR` (bytes B, G, R, A). In the game's shaders its
  rgb multiplies the complete lit colour and its alpha multiplies the
  texture's alpha. It is not ambient occlusion on the ambient term, not a
  layer mask, not a wind weight. It is used only when the buffer's `hasColor`
  flag is set.
- **tangent @28** is the geometric ∂P/∂u and **bitangent @36** is +∂P/∂v,
  both unit length. The pixel shader uses both as stored — `N′ = x·T + y·B +
  z·N` with x, y from the normal map — with no cross product, no handedness
  sign and no orthogonalisation. The bitangent is more than 10° away from
  ±cross(N, T) on 15.5 % of vertices, and `sign(dot(cross(N, T), B))` is
  negative on 33.0 % (mirrored UV islands).
- **winding**: 99.85 % of triangles wind clockwise against their normals in a
  right-handed reading. The game draws one-sided materials with `D3DCULL_CW`,
  so the front face is the side the stored normal is on. The engine's space
  is left-handed: with x negated (the toolkit's default output frame) the
  file's index order is counter-clockwise seen from the normal side.

*[2026-10-04]* The per-part coarse rigid buffer (79 parts; earlier called the
"proxy slab") is the part's **occluder** mesh: the engine submits it to its
occlusion pass (0x545927 → 0x53f9a5) and never draws it in colour. The shadow
groups are stencil shadow hulls. The extractor names the kinds `render`,
`shadow` and `occluder` (`proxy` is accepted as the old name of `occluder`),
writes only `render`, and returns the others through
`select_model_buffers(kinds=…)`.

The ModelRes property bag holds the LOD switch: `lodDistance01` …
`lodDistance45` (metres; LOD i is drawn below distance i,i+1, scaled by the
node's and the level's LOD factor), `lodFadeIn…`, `lodFadeOut…` (ModelRes
0x53ef10, selection 0x53a317). `extract` writes them to `<model>.model.json`
(format `watchmen-model-meta/1`). All 134 character models have one LOD.

**Articulated body** *(added 2026-10-04; reader 0x51e1ad; parser
`skeleton_records.parse_articulated_body`)*. After the node array:

    [u32 nDw][blob]                      property records, below
    [u32 n0]{u16 node}                   bodies of PhysX scene 0 (the ragdoll)
    [u32 n1]{u16 node}                   bodies of scene 1, the scene the cloths are created in (body+0x8c = 1; 0x51e1ad, 0x506b75, 0x50c95f)
    [u32 nC]{u16 node, u16 mesh, [u32 m]{u16, u32}}     cloths and their attachments (6-byte entries)
    [u32 nJ]{i32 parent, i32 child}      joints, as body indices

The blob is a run of property records `[objId u32][keyHash u32][typeId u32]
[nWords u32][data]` (without the `typeId` word in the stand-alone Part 1
build, below), key hash = the engine name hash; its objects come in
the order scene-0 bodies, cloths, joints. A body has mass, damping, solver
iterations and velocity limits; a joint is a PhysX D6 joint with its two
frames, swing / twist limits with spring and damping, and projection. The
shapes of a body are the collision volumes of its node (FORMATS_MISC.md).
Part 2 PC: 13 models carry a rig, each with 17 bodies and 16 joints; the two
player models also have cloths (Rorschach 2, Nite Owl 1). `docs/RAGDOLL_RIG.md`
describes the exported rig, `docs/re/wp2_physics.md` the engine side.

**The stand-alone Part 1 header** *(added 2026-10-05; PC and Xbox 360 Part 1,
block signature `0xEE1FB0A3`; PS3 Part 1 is in the Part 2 layout)*. It is the
record stream above with two differences:

1. A submesh record has **one** flag byte between its `u32` and the
   MeshBuffer, not two: `string name, [u32 1][u32 textureIndex], bool, bool
   inline, u32, bool, MeshBuffer, [u32 size][size bytes]`. The byte that is
   kept is the one the loader uses (a dynamic copy of the buffer, set on cloth
   meshes); the one that is absent is the byte the Part 2 PC loader reads and
   discards. Code: the Xbox 360 Part 1 reader `0x828bccc0` reads 1, 1, 4, 1
   bytes where the Part 2 readers (`0x542541` PC, `0x828fea68` Xbox 360) read
   1, 1, 4, 1, 1; and the submesh record's version term is 10 in the Part 1
   build (`0x828b4ff0`) against 11 in Part 2 (`0x53a563` PC, `0x828f54c0`
   Xbox 360), while the terms of the model (46), the node (10) and the mesh
   buffer (15, 8, 2, 3) are the same in both builds. The Xbox 360 Part 1
   addresses resolve with `default.pe` read as a memory image (file offset =
   RVA, image base `0x82000000`), not through its section table.
2. Every property blob — the bag of §3 and the articulated-body blob — holds
   **untyped** records `[objId][keyHash][nWords][data]`. The type of an
   articulated-body property comes from its key: each of the 86 keys carries
   one type on all 918 typed blobs of PS3 Part 1 and PC Part 2.

The header stores no version: the loaders do not branch, each build reads one
layout. `parse_model_header` tries the layout its property bag points at
(untyped records → Part 1) and then the other, and says which one read in
`"layout"`. On the files: 1,090 / 1,090 headers of each stand-alone Part 1 set
read as Part 1; the 1,085 that have a submesh read in that layout only, the 5
without one read in both and take the bag's answer. The stream blob is
unchanged (PC Part 1: consumed exactly on 1,085 / 1,085), and so are the node
records, the MeshBuffer header and the body / joint lists: counts and values
are equal to the PS3 Part 1 copy of the same model on 1,090 / 1,090. The
readers of the Part 1 node and model root were not opened; their equality is
from the data and the unchanged version terms.

**Vertices are part-local** (measured; the chain is read from code, 0x53b605). A buffer's positions are in the space
of its part; model space is `v' = conj(q)·v·q + pos`, the part first and then
every parent up to parent 0xFFFFFFFF (`model_part_transforms`). The union of
the LOD-0 submesh boxes taken through that chain equals the model box within
0.05 mm on 47 of 47 models with a moved render part in each Part 2 set (PC,
Xbox 360, PS3) and within 0.13 mm on 37 of 37 in PC Part 1; as stored it does
on 7 and 14. The model box is the box of the transformed submesh **boxes**, so
on a model with a rotated part it is larger than the vertices (5 of the 47:
`Dumpster_medium_02`, `Tripod_01`, `GrappringGunBullet`, `Rorschach_PoseRe02`,
`Sky_MainMenu_02`); every moved vertex lies inside it on 47 of 47. No shipped
model has a skinned buffer in a moved part. `decode_model` (OBJ and GLB) and
`decode_model_mesh` apply the chain to positions, normals, tangent and
bitangent of unskinned buffers (`part_space=True` returns them as stored; the
rule is measured on render buffers and applied to shadow hulls and occluders
by inference); `<model>.model.json` lists the parts under `parts` and says
`part_transforms_applied`. 1.3.0 wrote every part at the model origin.

Not established: what asset flag bit 4 (the texture-list bool) does beyond selecting
the load argument of 0x55243f (0x49b2b2); the collision volume's second u32. The submesh
flag byte the Part 1 build does not have is 'the buffer has a cloth mesh' (writer
0x53f736; measured: equal to the MeshBuffer's own cloth bool on 2,578 of 2,578 PC
Part 2 render buffers, and the one bool PC Part 1 stores is set on 41 buffers
that have no cloth mesh); `has_cloth_mesh` in `parse_model_header` (the old key
`no_defer` is kept).
*[2026-10-05, submesh and part fields:]* the submesh bool at +0x24 (`b24` in
`parse_model_header`) makes the submesh **skipped** when set — 0x4b3886
returns "flag is 0" and all five of its callers skip a flagged submesh
(the fifth, 0x53fee6, read; the other four as reported). It is 0 in all
2,575 submeshes of the 738 staged PC Part 2 models. The submesh u32 at +0x28
(`u28`) is the shadow-hull group id (`shadowID`; read from code): at build
time (0x544ae4) the submeshes of one part and LOD that have the same id above
0 and the `b24` flag clear are merged into one stencil-shadow hull, one hull
per id from 1 to the maximum; 0 = in no hull. A cloth submesh with an id above
0 gets a hull of its own. Submeshes whose MeshBuffer has flag 0x40 go to a
separate list whose use was not traced. Values 0–10 (1 on 1,851, 0 on 629,
2–10 on 95). No run-time reader was found. The part u32 `f1` (node +0x2c) is
the index into the model's pivot-book list (the `nPb` paths, model+0x9c; set
by 0x53e987, default `/pivotbooks/default.pb`); the consumer found (0x4a5961)
reads part 0's value only. It is 0 on all 6,220 parts. `parse_model_header`
and `<model>.model.json` name them `shadow_id` and `pivotbook_index` (the old
keys `u28` and `f1` stay in the parsed header).

**Extractor.** `watchmen_extract.parse_model_header` and `model_stream_layout`
implement this layout; `decode_model_mesh` returns everything per submesh
(name, part, LOD, texture, positions, normals, UVs, triangles, colour, tangent,
bitangent, joints, weights). `decode_model` writes an **OBJ + MTL** per model
(and, with `--glb`, a rigged GLB for skinned models), with LOD 0 by default
(`--model-lod N|all`) and without shadow hulls and occluders. The header
path is used only when the header parses and the layout consumes the stream
to the last byte; anything else takes the older descriptor scan, unchanged.
*[2026-10-05]* It now covers all six sets: both header layouts, and the
console streams. Every model that has a stream is decoded header-driven on
PC Part 1, Xbox 360 and PS3 (735 per Part 2 set, 1,085 per Part 1 set); the
scan remains as the fallback and decodes no shipped model.

*Corrected 2026-10-03 (toolkit 1.4.0):* with `--glb`, every header-decoded
model now gets a GLB — a rigged one when it is fully skinned, a static one
otherwise (735 on Part 2 PC, 130 before). Those GLBs carry NORMAL, TANGENT
(stored tangent, `w = −sign(dot(cross(N, T), B))`, only for a material with a
normal map), COLOR_0 (only for `hasColor` buffers; float, rgb sRGB → linear,
alpha as stored), triangles reversed so that the normal side is glTF's front
face, and materials from the texture's `sheet.json` (§4.6).
`--no-vertex-attrs` writes the 1.3.0 files instead. A model that takes the
descriptor scan gets a GLB only when skinned, without these attributes, as
before. *[2026-10-05]* Console and Part 1 models are header-decoded too (see
above), so they get the same GLBs. *[2026-10-06]* The console colour byte
order comes from the console the source path names; only a console model with
no such source and undecided data gets no COLOR_0, and says so.

*Corrected 2026-10-02:* earlier versions said the extractor also writes FBX
and STL (`--format obj,fbx,stl`). The shipped extractor has no such option
and no FBX or STL writer.

## 7. Status of the wider format

**Textures are fully solved** — naming, deterministic stream binding, and
byte-exact layer/cube/animation carving all verified end-to-end against real data
and the engine code. Models (`ModelRes`) decode from their header on Part 2 PC
*(corrected 2026-10-02: the "index-buffer recovery still partial for some
baked-environment meshes" caveat is withdrawn; see §6b)*; audio (`MediaStream`,
libVorbis/Bink) is covered in `WATCHMEN_EXTRACTION_MASTER.md` *[2026-10-04:
the multi-track layout of music streams is in §8 below, the `sound` header
in `FORMATS_MISC.md`]*. The container and block formats above are common to
all of them.

## 8. Music streams

*Added 2026-10-04 (report `re/wp6_audio.md`).*

A stream holds N synchronous tracks (music stems; N = 1 - 7 in the shipped data). It is a chain of
**groups**: one chunk per track, back to back. Every group is followed by a link record

    [u32 m][u32 size x N]        m = sum(sizes) + 4 * (N + 1)

with the chunk sizes of the next group; the link after the last group repeats the sizes of group 0
(the stream loops). Byte order: little-endian on PC, big-endian on X360 / PS3.

| Platform | Chunk |
|---|---|
| PC | `[32-byte ogg_packet][Vorbis packet]` records (0x45cbae): dword 0 not read (the engine overwrites it with the data pointer), dword 1 = packet bytes, dword 2 = 1 on a track's first packet, dword 3 = 1 on a track's last packet, u64 at +16 = granule position (the exact track length on the last packet), u64 at +24 = packet number within the track. Each track's first chunk starts with its own three Vorbis header packets. |
| X360 | whole 2048-byte XMA2 packets; group 0 has no sizes in front of it and is split with the closing link |
| PS3 | `[32-byte header][MP3 frames]` segments (header dword 0 = payload size), optionally padded to 16 bytes |

The **descriptor** is the block asset `<name>_track0.wav` of class `mediastream`:

    [u32][i32 -1][u32 0][u32 tracks][str stream path]
    [u32 m][u32 size x tracks]                 the link of group 0
    [u32 groups][u32 0]
    per track: [str source wav][u32 0][u32 samples][u32 channels][u32 rate]
               [i32 flag bit 0: 0 / -1][i32 flag bit 1: 0 / -1]
               [u32 cues] cues x ([str name][u32 sample])
               console only: PS3 12 bytes; X360 [u32 k][k x u32 seek sample][u32]

The two flag words are bits 0 and 1 of the track's flag word (writer 0x44f969). Bit 0 reaches
the voice only for one-channel tracks; that it means 3D and bit 1 looping is inferred. Music
tracks store 0 and -1.

`str` = `[u32 length][bytes, NUL included]`. Cue points are what `MusicTrackCtrl.change_on_cue`
waits for. Track names and track states are in the level's `MusicSetup` fragment
(`MusicStreamSlot.streamingSound` names the descriptor; `track0..9` are editor labels and equal in
23 of the 24 shipped setups, so they do not describe the stems).

`extract` writes one file per track and a `<stream>.json` sidecar; every track file ends at
the granule position stored with its last packet (the decoder shortens the last block to it,
0x8d29c0). `--flat-music` writes all packets in file order into one file, as 1.3.0 did, ending
at the computed block position.

Part 2 PC: 13 streams, 10 with more than one track (53 track files in all).
Up to 1.3.0 the extractor wrote the chunks of all tracks into one file.

*This document describes the shipped data of one specific title and was derived by
clean-room reverse engineering for interoperability/preservation.*
