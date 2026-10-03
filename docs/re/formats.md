# File formats — closing the documented unknowns from the engine's loaders

Target: `KapowMultiDEDRM.exe` (PC, image base 0x400000). Evidence levels: **read from code** (traced in
disassembly/decompilation, address given), **validated** (additionally reproduced on real files through the
read-only device share), **inferred**, **not established**.

Companion files:

- `findings/formats_vertex_decls.json` — all 11 vertex formats (D3D9 elements, strides, semantics), dumped from exe bytes.
- `findings/formats_tables.json` — block header map, TOC record, type hashes, texture enum/usage tables, sequence grammar.
- `findings/formats_ref_parsers.py` — reference parsers transcribed from the loaders. Run on the extracted Part 2
  tree: **models 740/740** (stream length reproduced exactly; 5 have no stream file), **textures 936/936**,
  **sequences 194/194 to EOF**, bordello block TOC exact. No scanning, no slop, no heuristics except one
  (sequence key class, see §4).
- `work/formats/*.asm`, `work/formats/d.py` — annotated disassembly helpers and listings.

**Tooling caveat that affects everyone:** 2,081 functions in `dump/` are 10-byte stubs
(`{ FUN_00991850(); }`) because Ghidra treated the SEH prologue helper as noreturn. Every loader in this
report is one of them (`FUN_00545927`, `FUN_00542541`, `FUN_004a36d8`, `FUN_004a3525`, `FUN_005382aa`,
`FUN_005415bf`, `FUN_0047e126` …). They were read from disassembly (`work/formats/d.py VA`).

**Doc corrections that fall out of this (details below):**

| Doc statement | What the code says |
|---|---|
| `ReadVec4 = 0x4354a8` | It reads **12 bytes** (vec3). 16-byte reads are `0x4354d1` / `0x43553c`. `0x4353e9` is ReadBool (`==1`), `0x435403` ReadU8. |
| `kapow_hash` uppercases | Engine `FUN_00423ce8` ANDs **every** byte with `0xDF`. Identical for letters, different for digits and punctuation — which is exactly why the two type hashes never resolved. |
| u32 after the type name is "classId/version" (0x2D, 0x5B) | It is the **dword count of the property bag** (`FUN_00511f96`). Body starts at `4 + nameLen + 4 + 4*N`. |
| Six copies per TOC entry are per **platform** | Slot index is the current **language** (`FUN_0045c762`, same index the loader logs as "language: %s"). |
| Directory starts at 399 with a sentinel flag; stream binding is a "+1 trailer shift" | Fixed header is exactly **400 bytes**; the stream pair is the **tail of its own record**. |
| Texture image descriptor is ~30 bytes with "drift" | 29-byte descriptor + **1 presence byte per optional slot** (8 slots per frame). |
| `.sequence` first float is a version (1.0/6.0/20.0) | It is **durationSec**. |
| Stride-16 "baked env mesh, int16 positions" | No vertex declaration in the exe has a SHORT element; format 3 (stride 16) is `FLOAT2 pos + FLOAT2 uv`. |

---

## 1. Block header and directory (`.block_h_z`)

Loader: state machine `FUN_004a36d8` (loadblock.cpp), started by `FUN_004ae0fd`; directory walker
`FUN_004a3525`; header consumer `FUN_0049dd0e`. Listing: `work/formats/loadblock_4a36d8.asm`.

### 1.1 Fixed header — 400 bytes, read in one call

`0x4ae315: push 0x190` → read into `ctx+0x10`. So file offset `o` ↔ `ctx+0x10+o`.

| file off | type | field | what the engine does | evidence |
|---|---|---|---|---|
| 0x000 | f32[8] | bounds (2 × vec4) | copied to `LoadBlock+0x180` (`FUN_0042af16`, call at 0x4a3cad) | read from code |
| 0x020 | u32 | ? (0x79D3E0DA in bordello) | no reader found | not established |
| 0x024 | char[36] | GUID text | no reader found | not established |
| 0x048 | char[255] | **fingerprint**, encrypted C string | `FUN_0049dd0e` decrypts in place with a 3-LFSR stream cipher (`FUN_00405a31/00405a8b/00405b1e`), key `"1E564E3B-D243-4ec5-AFB7"`, stores at `LoadBlock+0x1d4` | read from code + **validated**: bordello decrypts to `THIS IS THE DEFAULT FINGERPRINT KEY, PLEASE CHANGE IT!` |
| 0x147 (327) | u8 | `2` | copied to `LoadBlock+0x1e4` (0x49dd59) | store read from code; meaning not established |
| 0x148 (328) | u32 | `0x593F430A` | never read by the loader. `FUN_0049db60` builds a CRC over `"8"` ("Block version: 8") and each asset class's version; its return value is discarded at 0x4a3b63 | **inferred** to be that version signature (not recomputed) |
| 0x14C (332) | u32 | tablesSize | size of read #2 | read from code |
| 0x150 (336) | u32 | **unk1** = header-blob size of entry 0 | size of read #3 (0x4a3b20) | read from code + validated (2903 = entry 0) |
| 0x154 (340) | u32 | **unk2** = I/O buffer size | both ping-pong buffers are allocated with it (0x4a3be7, 0x4a3c2d); the directory is read into the same buffer | read from code + validated: `max(tablesSize, largest blob)` |
| 0x158 (344) | u32 | trailer offset | seek target after the last header (0x4a381d) | read from code + validated: `400 + tablesSize + Σ sizes` |
| 0x15C (348) | u32 | trailer size (8) | allocated and read as the "loadblock fragment" blob (0x4a379a) | read from code |
| 0x160 (352) | u32 | numEntries | | read from code |
| 0x164 (356) | u32 | **unk5** = numLocalized | entries that follow the language seek; total = numEntries + numLocalized (0x4a3a3a, 0x4a3d1b) | read from code |
| 0x168 (360) | u32 | numStreams | reserve count for the stream table (0x4a3d04) | read from code + validated (581) |
| 0x16C (364) | u32[6] | per-language header offset | when the running index reaches numEntries the loader logs "Loading localized header assets (language: %s)" and seeks to `[ctx+0x17c + lang*4]` (0x4a3938–0x4a3994) | read from code |
| 0x184 (388) | u8 | flag | `FUN_00435c0b(0xd92a14, b)` at 0x4a3b78 (sticky OR into a global) | store read from code; meaning not established |
| 0x185–0x18F | | zero | part of the 400-byte read | read from code |

### 1.2 Directory record (`FUN_004a3525`, 0x4a357f–0x4a36a2)

```
u32 headerBlobSize[6]      only slot == FUN_0045c762() (current language) is kept
u32 typeHash               FUN_004fd931 -> datatype registry (global 0xe151d0)
u32 nameLen; char name[]   FUN_00437469; asset looked up (FUN_0054ba59) or created (class vtable+0x6c)
u8  hasStream              ReadBool
if hasStream: 6 x { u32 offset, u32 size }    -> stream entry: offset[6] at +0x10, size[6] at +0x28 (FUN_004a2aed)
```

- **Per-entry flag** = `hasStream`, nothing more (read from code). It belongs to the record it follows.
  Validated: parsing from **400** with this grammar ends exactly at `400 + tablesSize`, and
  `2d_noise4.bmp`'s own pair inflates to 174,776 bytes — its own stream. The documented "+1 shift" is an artefact
  of starting at 399 (a zero pad byte that happened to parse as `flag=0`).
- The **six slots are languages**, not platforms (read from code: same index function as the language log line
  and the per-language offset table). On Part 2 PC data all six are equal (validated: 0 differing entries in
  bordello). Which slot the *stream* reader uses was not traced (inferred: the same language index).

**Proposed toolkit change:** `parse_block_toc`: start at 400, read `[6 sizes][hash][name][u8 hasStream][6 pairs]`,
bind the pair to its own entry, drop the +1 shift; rename `unknown` → `type_hash`; pick slot by language when
slots differ (localized entries, e.g. `watchmenpart2` `_uk` text and the `mainmenu` logo). Expose
`entry0Size / bufSize / trailerOff / trailerSize / numLocalized / langHeaderOff`. Reference:
`parse_block_header()`.

---

## 2. Asset-type hashes 0x41764525 and 0x96ea413f

| hash | type name | evidence |
|---|---|---|
| `0x41764525` | **`ModelEffects(ModelRes)`** | validated: `FUN_00423ce8("ModelEffects(ModelRes)")`; it is also the literal type string in those header blobs |
| `0x96ea413f` | **`TextureEffects(Texture)`** | same |
| `0x6532e9b4` | `terrain` | hash match (bonus) |
| `0xd8c06967` | `pivotbook` | hash match (bonus) |
| `0x48d86c33` | `aipathdata` | hash match (bonus) |

Why earlier brute force failed: `FUN_00423ce8` masks every byte with `0xDF`, so `(` and `)` hash as 0x08/0x09.
`kh.py` and `kapow_props.kapow_hash(name.upper())` are only correct for names made of letters and `_`.

**Loader.** These are script (TNT) classes derived from a native asset class. Registration:
`FUN_007b0053` → `FUN_0047e126(desc, "ModelEffects", 0x26, "ModelRes", …)` and `FUN_00848a1b` →
`FUN_0047e126(desc, "TextureEffects", 0x3f, "Texture", …)`; `desc+0x5c` = base class (`FUN_004fd9a4`). They have
no reader of their own: the base reader runs. `FUN_00511f96` reads the type string and, if it differs from the
asset's current type, re-types the entity (`FUN_005022f6` → vtable+4) before reading the bag (read from code).

**Payload layout** = the base class layout with a longer property bag (validated on 219 `ModelEffects` models
and 28 `TextureEffects` textures):

- `ModelEffects(ModelRes)`: bag is 96 dwords vs 91 → one extra 20-byte record, key `0x4d10a1c1`
  (UI string "Collision Effect Type"). Then the ModelRes body of §3.
- `TextureEffects(Texture)`: bag is 55 dwords vs 45 → two extra records, `0x4d10a1c1` (Collision Effect Type)
  and `0x2a1529e3` (Special Collision Effect Type). Then the Texture body of §5.1.

**Proposed toolkit change:** add the two names (and the three bonus ones) to the type table; make the hash
`byte & 0xDF`; compute the body offset from the bag dword count instead of assuming 196 for textures.

---

## 3. Mesh buffers (ModelRes)

### 3.1 Vertex formats — the complete set

Stride table `0x00C791B0` (u32[11], exe bytes): `28, 24, 68, 16, 56, 44, 56, 60, 48, 20, 32`.
Declarations are created in `FUN_0045544e` (11 × `CreateVertexDeclaration` into `device+0x79c + 4*fmt`) and
selected with `SetVertexDeclaration(device[0x79c + fmt*4])` (part_0002.c:13373). All read from code; element
tables dumped from exe bytes into `formats_vertex_decls.json`.

The **format id is stored in the file**: it is the third u32 of the vertex-buffer descriptor (the field the
docs call `G`). `G=5/6` were never "element counts".

| fmt | stride | elements (offset: type usage) | used by |
|---|---|---|---|
| 5 | 44 | 0: FLOAT3 POSITION · 12: FLOAT16_4 NORMAL · 20: D3DCOLOR COLOR0 · 24: FLOAT16_2 TEXCOORD0 · 28: FLOAT16_4 TEXCOORD1 · 36: FLOAT16_4 TEXCOORD2 | rigid render mesh |
| 6 | 56 | fmt 5 + 44: D3DCOLOR COLOR1 · 48: FLOAT16_4 TEXCOORD3 | skinned render mesh |
| 9 | 20 | 0: FLOAT3 POSITION · 12: FLOAT16_4 NORMAL | rigid shadow hull |
| 10 | 32 | 0: FLOAT3 POSITION · 12: FLOAT16_4 NORMAL · 20: D3DCOLOR COLOR0 · 24: FLOAT16_4 TEXCOORD0 | skinned shadow hull |
| 8 | 48 | pos · 12: half4 normal · 20: colour · 24/32/40: half4 TEXCOORD0-2 | `.terrain.stream` (stride match with FORMATS_MISC; not re-validated here) |
| 2 | 68 | float variant: pos · 12: FLOAT3 normal · 24: colour · 28: FLOAT4 uv · 44/56: FLOAT3 | not in `.model` corpus |
| 7 | 60 | pos · FLOAT3 normal · colour · FLOAT2 uv · 2 × FLOAT3 | not in corpus |
| 4 | 56 | two streams: s0 24 B instance (TEXCOORD3-5), s1 56 B vertex | instancing; not in corpus |
| 0, 1, 3 | 28, 24, 16 | 2D/UI: FLOAT4 or FLOAT3 pos + colour + FLOAT2 uv; fmt 3 = FLOAT2 pos + FLOAT2 uv | not in corpus |

Corpus census (Part 2 PC, 740 models, 3,118 buffers): fmt 5 ×2370, fmt 6 ×287, fmt 9 ×357, fmt 10 ×104.
Nothing else occurs.

### 3.2 Field semantics (writers `FUN_0043106f` fmt 6, `FUN_00430efe` fmt 5/2, `FUN_0043114e` fmt 9, `FUN_00431195` fmt 10; half packer `FUN_0042a83c`)

| field | finding | evidence |
|---|---|---|
| Position | raw `float32 × 3`. **No quantisation, scale or bias in any format.** The two vec3 in the MeshBuffer header are the AABB centre and half-extent, not dequantisation terms. | read from code |
| Normal | `half × 3`; 4th half is never written by the fmt 5/6 writers and is zeroed for fmt 9/10 | read from code; validated: 4th half = 0 on 13,521 sampled vertices, \|N\| = 1.000 |
| COLOR0 @20 | D3DCOLOR `A<<24 \| R<<16 \| G<<8 \| B` = `ftol(c × 255.0)` (constant at 0x9e6ce8); memory order **B, G, R, A**. Defaults to 1.0 when the mesh has no colours. | read from code |
| UV @24 | two raw half floats. **No scale, no bias, no V flip** in the exe. One UV set only in fmt 5/6. | read from code; observed range −1.24…1.92 (tiling) |
| TEXCOORD1 @28 | `half × 3` + 0 — **tangent** | writer offsets read from code; role **validated**: dot with geometric dP/du = 0.89–1.00 on four models, ≈0 with dP/dv |
| TEXCOORD2 @36 | `half × 3` + 0 — **bitangent** | same; dot with dP/dv = 0.90–0.99 |
| COLOR1 @44 (fmt 6) | 4 bone indices, shuffled (`FUN_0042a94f`): byte **+46 = idx0, +45 = idx1, +44 = idx2, +47 = idx3** | read from code |
| TEXCOORD3 @48 (fmt 6) | 4 weights, `half × 4`, order w0..w3, not sorted | read from code; validated: sums ≈ 1.0 |
| fmt 10 | bone indices @20 (same shuffle, `FUN_0042a974`), weights `half × 4` @24 | read from code |
| Format choice | builder at 0x0043426c: source flag bit 4 (skinned) ? (bit 7 ? 10 : 6) : (bit 7 ? 9 : 5); bit 1 → `hasColor`, bit 2 → `hasAlpha` | read from code |
| Indices | always `u16`: `CreateIndexBuffer(count*2, usage, D3DFMT_INDEX16=0x65)` in `FUN_00454a41`. The IB descriptor stores a **byte** count (`>>1` in `FUN_00429f21`). Triangle list. | read from code |

### 3.3 Header-blob layout (after the property bag)

`ModelRes::Read` = `FUN_00547006` (`work/formats/modelres_read_547006.asm`):

```
u32 b4 · bool e0 · u32 e4 · bool e8
u32 n; n x 32 bytes            u32 n; n x 4 bytes
vec3 bboxCenter · vec3 bboxHalfExtent
u32 nTex   { bool flag; string path }          texture list
u32 nPb    { string path }                     pivotbooks
u32 nParts { Part }                            FUN_00545927, 0x74-byte objects
... physics/ragdoll (FUN_0051e1ad), optional cloth object, anim-event list — not needed for geometry
```

`Part` = `FUN_00545927`:

```
vec3 pos · 16 bytes quat · string name · u32 u2c · u32 u70
u32 nLods { u32 nSub { Submesh } }
u32 nGroups { u32 n { bool b; u32 v; MeshBufferHeader } }     shadow hulls (fmt 9 / 10)
bool has; if has: MeshBufferHeader                            extra fmt-5 buffer (79 parts)
2 x [ u32 n { Volume; vec3; vec4; u32 size; size bytes } ]    collision volumes + cooked blob
u32 n { u32 k; k x 20 B; u32 nV; nV x 12 B; u32 nI; nI x 4 B }   FUN_00561d1c
```

`Submesh` = `FUN_00542541` (0x2c-byte record):

```
string name
u32 n; u32 texIndex[n]      n == 1 in every submesh; value indexes the model's texture list (validated on Rorschach: 0..8 of 9)
bool b24 · bool inline · u32 u28 · bool dynCopy · bool noDefer
MeshBufferHeader            (FUN_004336ec; inline == 0 in the whole corpus)
u32 size; size bytes        cooked physics blob (cloth pieces only)
```

`MeshBufferHeader` = `FUN_004336ec`:

```
vec3 bboxCenter · vec3 bboxHalfExtent
u8 hasColor · u8 hasAlpha
bool hasExtra; if set (FUN_0042f9c1): u8; then 5 x [u32 n; n x {12,2,12,2,2} bytes]
VB: u32 flags · u32 vertexCount · u32 FORMAT ID         (FUN_00429e11)
IB: u32 flags · u32 indexBytes  · u32 ix                (FUN_00429f21)
```

`Volume` = `FUN_00524b23`: `u32 type; u32;` then type 5 → 3 floats, 6 → 1 float, 7 → 2 floats,
2/4 → `u32; u32 nV; nV×12; u32 nI; nI×4`.

Flags (read from code): VB/IB `flags` bit 3 = bulk data deferred to the stream blob (forced from the load mode,
`FUN_00429e11`); bits 0/1 = dynamic (`D3DUSAGE_DYNAMIC`, `FUN_00454159`). In files: 8 on static rigid meshes,
0 on skinned ones — the data is in the stream blob either way.
Not established: `b24`, `u28` (0–10 observed), `ix` (1; 0 on 12 vegetation submeshes), `u2c`, `u70`, `b4`, `e4`.

### 3.4 Stream-blob layout

For every MeshBuffer, **in header order** (per part: submeshes of every LOD, then shadow groups, then the
optional extra buffer):

```
vertexCount x stride[fmt]      vertex data
indexBytes                     u16 indices
u32 nClusters; nClusters x 40 B     { vec3 centre, pad, vec3 halfExtent, pad, u32 a, u32 b }
u32 nLists;   each { u32; u32 n; n x 0x44 B }      (non-zero in 1 buffer)
u8 hasPerVertex; if set: vertexCount x 8 B          (8 buffers, fmt 9/10 only)
```

The field order is the order `FUN_00433ef4` reads bulk data (read from code); the split between the two blobs
and the buffer order are **validated**: the sum reproduces the stream length exactly for 740/740 models.
`dynCopy` buffers (cloth; `FUN_00433c40` makes a runtime fmt-5 copy) add nothing to the stream.
Not established: how the engine routes these bytes at load time (`FUN_004341f5` consumes a pointer table
whose producer was not traced), and the unit of the cluster ranges `a, b` (0,150 / 150,303 / …).

### 3.5 What `watchmen_extract.py` gets wrong or skips

1. **Finds buffers by scanning** (`find_descriptors` pattern match, then a byte-by-byte search for a "sane" VB
   offset with `_vb_ok` / `_ib_ok`). All offsets are computable; the scan is only needed because shadow hulls
   and cluster tables sit between render buffers.
2. **Requires the third IB field == 1** → silently drops the 12 `ix == 0` submeshes (e.g. `Palm_Banana_01`).
3. **Requires format ∈ {5, 6}** — correct for render meshes, but it then cannot account for the fmt 9/10 bytes
   it has to skip.
4. **Merges every LOD** into one mesh (250 parts have 2–3 LODs) and also emits the per-part extra fmt-5 buffer
   (79 parts) as if it were a render submesh. Whether that extra buffer is a render or a proxy mesh is not
   established.
5. **Material binding is guessed** (`submesh_materials` / `extract_materials` regex). The submesh record carries
   the texture-list index directly.
6. **Skips** vertex colour (@20), tangent (@28), bitangent (@36), `hasColor`/`hasAlpha`, submesh and part names,
   per-part pivot `pos`/`quat`. Whether vertices are part-local was not established — check multi-part rigid
   models before relying on the merged output.
7. Drops degenerate triangles and reads normals/UVs under `try/except` — unnecessary once offsets are exact.
8. **Already correct:** positions, normal `half3 @12`, UV `half2 @24`, u16 triangle list, and
   `rig_glb.decode_skin` on PC (`[46,45,44,47]`, weights `half4 @48`) matches the engine byte for byte.
9. The docs' "stride-16 baked env mesh with int16 positions" has no counterpart in the exe (§ corrections table).
   Whatever those bytes are, they are not a vertex format; the 40-byte cluster table and cooked collision blobs
   are the likeliest misreads (inferred).

**Proposed toolkit change:** replace `find_descriptors` + VB search with `parse_model()` +
`model_stream_layout()` from `formats_ref_parsers.py`; export LOD 0 only by default; name materials from
`texIndex`; add colour/tangent attributes. Console layouts were not examined (PC exe only).

---

## 4. `.sequence` (PropertySequenceAsset)

Readers: asset `FUN_0054558c`; object `FUN_00544374` + `FUN_0054113c`; track `FUN_005415bf`; key base
`FUN_00547f4c`; spline key `FUN_00547fdb`; evaluation `FUN_0053aa43`; apply `FUN_00499733`.

```
f32 durationSec                 asset+0x90 (property Get/SetDurationSec, registration FUN_005436f3)
u32 u94                         asset+0x94
u32 nObjects
object: string targetPath       empty path is [u32 1]["\0"]  — this is the "slop"
        u32 u4
        u32 nIds; u32 ids[nIds]
        string className
        u32 nTracks
track:  string propertyName     resolved by FUN_004ee0e7; unknown -> "InvalidSequenceProperty"
        u32 interpolation       1 step, 2 linear, 3 spline
        u32 nKeys
key:    f32 time
        u32 interpolation       0 = inherited (use the track's)
        u32 dim; f32 value[dim]
        if spline-capable track: u32 n; n x { f32 inT, f32 inV, f32 outT, f32 outV }
```

| doc unknown | resolution | evidence |
|---|---|---|
| "version 1.0/6.0/20.0" | **duration in seconds** | read from code |
| track `ttype` | interpolation mode; enum string at 0x00a361a0 is `inherited,step,linear,spline`; dispatch in `FUN_0053aa43` (1 → copy key A, 2 → type lerp, 3 → spline) | read from code |
| key `mode` | per-key interpolation override, 0 = inherit | read from code; always 0 in 2,002 keys |
| "handle presence is per-key (lookahead)" | **per track, decided by the property's data type**: `FUN_00539dd9` is true for `number`, `vector`, `quaternion` (globals 0xe15190 / 0xe15184 / 0xe15174), which selects the 0x60-byte spline key class (vtable 0xa37328) for every key of the track; all other types use the plain 0x20-byte key | read from code |
| handle layout | per component: in-handle `(time, value)` then out-handle `(time, value)`, absolute coordinates. Evaluated as a cubic Hermite (`FUN_0040f5a1`): slopes `(out−P0)` and `(P1−in)`, `u = (t−t0)/(t1−t0)` | read from code |
| `localorient` keys with dim 4 and 3 handles | quaternion tracks are keyed as **Euler angles in degrees** `(x, y, z, pad)`, interpolated as a vector, then converted with `q = qx·qy·qz` (constant π/180 at 0xc8aa10) | read from code; observed dim 4 / n 3 on all 522 such keys |
| object "slop bytes" | none — the grammar above parses all 194 files to EOF | validated |
| header `u32` (0/1/4), object `u32` (0/1) | stored at asset+0x94 / object+4; no reader found | **not established** |

Without the property-type table, the reference parser decides the key class per track by trying both and
keeping the one that parses to EOF — the only heuristic left, and it was unambiguous on the corpus.

**Proposed toolkit change:** replace the scanning parser with `parse_sequence()`; rename `version` →
`durationSec`, `ttype`/`mode` → `interpolation`; emit `in`/`out` handles; convert quaternion-typed tracks from
Euler degrees. Better still, take the key class from the property's registered type instead of trial parsing.

---

## 5. Textures and the console-only items

### 5.1 PC Texture header (`FUN_005382aa`, descriptor `FUN_00429e77`)

```
bag (FUN_00511f96)
u32 nFrames · bool hasAnim
frame x nFrames:
    Desc slot0
    7 x { u8 present; if present: Desc }      absent slots use device default textures
    string sourcePath
if hasAnim: animation info (FUN_0053345a) · then a virtual reader at +0xb0 — not parsed

Desc (29 bytes): u32 width · u32 height · u32 formatEnum · u32 x · u32 type (1 = 2D, 2 = cube)
                 u8 hasAlpha · u32 mipCount · u32 z
```

- Slot index is the layer role. Observed: 0 diffuse, 1 normal (ATI2), 2 specular (DXT1), 3 DXT1, 4 L8, 7 L8;
  5 and 6 never present. Labels no longer need the "drift" trick.
- `nFrames > 1` with `hasAnim` is the flipbook case; `type == 2` is the cubemap case (×6).
- Stream length = Σ over frames and present slots of the mip chain (×6 for cubes) — **validated 936/936**, with
  one correction to the docs: **linear formats (L8, X8/A8R8G8B8) store each mip row padded to 4 bytes** (65 files
  were off by 5–7 bytes without it).
- Format enum → D3DFORMAT table at 0x00C799E0 has 19 entries: 0→22, 1/2→21, 3/4→50, 5 DXT1, 6 DXT3, 7 DXT5,
  9 ATI2, 11/12→114, 13→113, 14/15→81, 16→75, 17→63; 8, 10, 18 are 0 on PC.
- Cube face order inside the PC stream was **not traced**. The lock helper `FUN_00454492` indexes its table
  `[face × mipCount + level]` with D3D faces 0..5, consistent with the documented face-major layout, but the
  code that copies stream bytes into it was not found.

**Proposed toolkit change:** replace the stride walk and stream-shape oracle with `parse_texture()` +
`tex_chain_bytes()`; label layers by slot.

### 5.2 Per-platform format mapping (read from exe data)

`FUN_0042bb4e` / `FUN_0042bb61` index `[platform*10 + usage]` (platform 0 editor, 1 pc, 2 x360, 3 ps3).
Compressed table at 0x009E8F78:

| usage | pc | x360 | ps3 |
|---|---|---|---|
| 0 | 5 (DXT1) | 5 | 5 |
| 1 | 7 (DXT5) | 7 | 7 |
| 2 (normal) | 9 (ATI2) | **10** | **7** |
| 3 | 3 (L8) | **8** | 3 |
| 8 | 3 (L8) | 5 | 3 |
| 9 | 15 | 14 | 14 |

This confirms the documented PC 9 → X360 10 → PS3 7 normal-map mapping from the exe itself. X360 enum 8 has no
D3DFORMAT in the PC table, so its identity cannot be read here.

### 5.3 PS3 cubemap framing — **the PC exe cannot answer this**

There is no PS3 texture packing code in the exe. PS3 appears only as platform index 3 in the tables above and
in shader-compiler argument strings (`-p sce_fp_rsx`). The 36-byte per-layer header and the cube framing are
produced by code that is not in this binary. No further claim is made.

### 5.4 X360 wide ATI2 / 3Dc mip tail — **the PC exe cannot answer this either**

- The exe imports 15 functions from `XBox360LibraryWrapper.dll`, including `WrappedXGTileTextureLevel`,
  `WrappedXGGetMipLevelOffset`, `WrappedXGSetTextureHeaderEx` and `WrappedXGSetCubeTextureHeaderEx`. Tiling and
  mip-tail offsets are computed inside that DLL (Microsoft XGraphics), not in the exe.
- The **2D** bake path is compiled out: in `FUN_0045473f` the 2D branch calls `FUN_0044f5b5`, a stub that
  returns 0. No code in the exe positions a 2D mip tail, so the `SawMillRope` 64×16 ATI2 case is unanswerable
  from this binary.
- The **cube** bake path survives (`FUN_0042578e`) and does document the X360 cube layout (read from code):
  `XGSetCubeTextureHeaderEx(width, levels, fmt, 0, &baseSize, &mipSize)`; buffer = `baseSize + mipSize`; then
  for face 0..5, for level 0..levels−1: `off = XGGetMipLevelOffset(tex, face, level)`, plus `baseSize` when
  `level > 0 && mipSize != 0`; `XGTileTextureLevel(width, height, level, fmt, buf + off, src, pitch)`.
  So X360 cube streams are a standard XG cube image — a base region then a mip region — with per-face offsets
  from `XGGetMipLevelOffset`. That is the right function to emulate for the documented "faces 1–5" gap; the
  offset formula itself is in the DLL.

---

## Not established (summary)

- Block header: u32 @0x20, GUID @0x24 (no reader found), meaning of bytes @327 and @388, whether @328 equals the
  computed version signature, which language slot the stream reader uses.
- ModelRes: `b24`, `u28`, `ix`, `u2c`, `u70`, `b4`, `e4`; cluster range units; the role of the per-part extra
  fmt-5 buffer; whether vertices are part-local; the runtime routing of stream bytes; the physics/cloth tail.
- Sequence: asset `u94`, object `u4`.
- Texture: PC cube face order (code not traced), fields `x` and `z` of the descriptor (always 0), the animation
  tail.
- Console: everything in §5.3 and the 2D half of §5.4.
