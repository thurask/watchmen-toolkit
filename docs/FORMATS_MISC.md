# Misc Kapow asset formats — ALL DECODED (2026-07-02 session)

The 7 leftover extensions in `20260628/extracted`, plus the universal serialization
they revealed. Decoders in this folder; JSON emission integrated into
`watchmen_extract.py` (writes `extracted/<name>.json` next to each raw asset;
batch-converted tree: 1203/1203 files, 0 errors).

## THE KEY DISCOVERY: the Kapow property-hash
Property/type names are hashed with a bit-serial CRC32 (poly 0x04C11DB7, MSB test
before shift-in, bits LSB-first per char, NO salt) over the name with **every
byte ANDed with 0xDF**:
`name_hash('NAME') = 0x7282b2a2`, `name_hash('LOCALPOS') = 0x2f0823c4`,
`name_hash('LOCALORIENT') = 0x51172879` — the "unknown keys" in FRAGMENT_FORMAT.md
are nameable. Dictionary built by hashing all 24k exe strings:
`prop_hash_dict.pkl` (kapow_props.namedict()). Type tags = name_hash of
'NUMBER','INTEGER','TRUTH','STRING','VECTOR','QUATERNION',...
Implementation: `kapow_props.name_hash` (`kapow_props.kapow_hash` is the raw CRC
over the bytes as given).

*Corrected 2026-10-02:* this section said "over the UPPERCASE name". The
engine's hasher (`FUN_00423ce8`, `and cl,0xdf` at 0x423cf7) folds every byte,
not only letters: `'0'..'9'` → 0x10..0x19, `(` → 0x08, `)` → 0x09, `,` → 0x0C.
For names made of letters and `_` the two agree, so the three examples above
are unchanged; every name containing a digit or punctuation had the wrong hash.
The same hash is used for asset type names, asset names, enum names and command
signatures (`name(type,...)`); see `re/names.md`.

## Universal property-bag format (.particle/.grass/.detailmesh/.pb/(fragment))
```
block:  [0-4 stray u32s][u32 namelen][ClassName\0][u32 schemaCount]
record: [u32 ownerId][u32 keyHash][u32 typeHash][u32 k][k dwords payload]
        string payload: [u32 wordcount][wordcount*4 chars] (k=1+wordcount)
```
Parser: `kapow_props.py` (name resolution via the hash dict).
*[2026-10-05: the standalone Part 1 on PC / Xbox 360 stores the record without `typeHash`
(`[ownerId][keyHash][k][payload]`); `kapow_props.parse` takes that layout when, and only
when, the typed layout does not end at the block's dword count and the older one does, and
marks the JSON `"record_layout": "untyped"`. See KAPOW_NAZ_FORMAT.md §3. Measured on PC and
Xbox 360 Part 1 against the PS3 build of the same files: `.grass` 4 of 4 equal (24 properties,
0 trailing; before 1 property and 428–432 bytes trailing), `.detailmesh` 5 of 5 equal (24
bytes trailing, 25 in the newer layout), `.pb` 3 of 3 equal (10 / 10 / 25 blocks; before 1).
A property with no known type would be written with type `"unknown"`, its raw hex and a
`warn` line; that occurs 0 times.]*
*[2026-10-04: the generic `[0-4 stray u32s]` rule is a heuristic of `kapow_props.py`. In an
asset whose loader is known the dwords between objects are counts — in `.particle` the list
lengths. Whether the same holds for `.grass` / `.detailmesh` / `.pb` was not checked.]*
- **.particle**: not walked as a generic property bag any more — see
  [PARTICLE_FORMAT.md](PARTICLE_FORMAT.md) (`particle_asset.py`, format `kapow-particle/2`). The
  file is `object(ParticleSystemAsset)`, a type count, and per `ParticleType` three counted
  lists (affectors, spawners, initializers); an object is
  `[u32 nameLen][ClassName\0][u32 payloadDwords][records]`. What this section calls "stray
  u32s" before a block are those list counts, `schemaCount` is the payload length in dwords,
  and `ownerId` is the saved entity's session id (the loader stops applying records when it
  changes). 746 / 746 files of seven extracts parse to the last byte and rebuild byte-exact,
  including the Part 1 PC / X360 files (records without a type hash), which the generic walk
  could not read at all. *[Before 2026-10-04 this bullet read "89/89 clean": the walk consumed
  the 89 Part 2 files, but left 1,776 records with a hex key and 971 with a mis-cased name.]*
- **.grass** (3/3, 0 trailing): grass template — texture, density, cell counts,
  width/height+variance, sway (sinMod/cosMod), LOD, collisionPower etc.
- **.detailmesh** (5/5): scatter template -> model path + lighting/sway/range params,
  then the mesh descriptors (reader `0x52de50`): `[u8 hasMesh]` and, when set, the vertex
  buffer `[u32 flags][u32 vertexCount][u32 formatId]` (`0x429e11`) and the index buffer
  `[u32 flags][u32 byteCount][u32 x]` (`0x429f21`). The format id is 7 (60-byte float
  vertex) in every file. The standalone Part 1 (PC, Xbox 360) has no `hasMesh` byte: its
  reader (`0x828dae50` in the Xbox 360 Part 1 image) goes from the bag straight to the two
  descriptors, which is why those files end 24 bytes after the bag and the others 25.
  *[2026-10-05: this bullet called the 25 bytes a "stream-linkage descriptor" and the JSON
  left them as `trailing_bytes`. `kapow_json.detailmesh_json` now writes them as `mesh`
  (`has_mesh`, `has_mesh_byte`, `vertex_buffer`, `index_buffer`), `trailing_bytes` is 0, and
  with the stream at hand a `stream` section gives the layout below. 30 of 30 files of the
  six sets; the rebuilt tail equals the file's in all 30. `x` is the primitive type (1 =
  triangle list).]*
  The three stream lists hold, per source mesh, `first_index_a`, `first_index_b` (= a + index
  count) and `triangle_count` (builder 0x5369e7; b = a + 3c and next a = a + 6c on 10 of 10 PC
  files). `inferred` says that `stream.vertex_stride` is **derived from the
  stream size** — (stream bytes − lists − index bytes) / vertex count — and not read from
  the file, so `leftover_bytes: 0` only says that the vertex count divides what is left.
  `stream.vertex_stride_source` is `"stream size"`, `stream.format_stride` is the stride the
  PC table `0x00C791B0` gives for the format id (60 for format 7) and
  `stream.stride_matches_format` compares the two (a `WARNING:` line when they differ).
  `inferred["stream.format_stride on consoles"]` says what that comparison rests on for a
  console file: the Xbox 360 executable's table (0x8308b6e0,
  `watchmen_extract.CONSOLE_VERTEX_STRIDES`) gives 60 for format 7 as well; the PS3 table was
  not read. All 30 detail meshes of the six sets tile with 60 bytes (measured).
  Its `.stream` (reader `0x5322c6`) =
  `[u32 n][n index offsets][u32 n][n mid offsets][u32 n][n counts]`, then
  60-byte float vertices (`float3 position, float3 normal, …`), then
  `6·Σcounts` u16 indices. Verified 5/5: the highest index equals
  vertexCount − 1 in all five files.
  *Corrected 2026-10-02:* this said "packed scatter geometry … the known
  stride-16 baked-env vertex class". There is no such class: no vertex
  declaration in the executable has a SHORT element (format 3, stride 16, is
  `FLOAT2 pos + FLOAT2 uv`), all 735 model streams of Part 2 PC tile exactly
  with float formats 5, 6, 9, 10, and these five streams are float data.
- **.pb** (3/3): 12B preamble then PivotSheet blocks ("Default","Ragdoll","Cloth",
  "Camera","Trigger",...) with friction/restitution/collisionMask + u64 uniqueID.

## .font (font_asset.py)
*Rewritten 2026-10-05 from the engine's readers (`Font` header reader `0x540c6e`, `FontBuffer`
reader `0x44245e`, texture descriptor `0x429e77`). The earlier text named a `decode_font.py`
that is not in the tree and split the header differently (`[u16 ver][u32 npanes][u16 fmt]…`,
"16B float params"); the fields below are what the loader reads.*
```
u8   hasData
texture descriptor, 29 bytes (the one every texture layer has):
     u32 width, u32 height, u32 formatEnum, u32 x, u32 type (1 = 2D), u8 alpha,
     u32 mips, u32 size (0 on PC / PS3; Xbox 360: stored bytes of the atlas)
atlas pixels, INLINE (a font has no stream file):
     PC    the full mip chain (A8R8G8B8, 1024x512 with 11 mips = 2,796,204 bytes)
     X360  `size` bytes, tiled and 16-bit swapped like a texture stream layer
     PS3   a 36-byte RSX descriptor (u32 at +8 = byte count) + the mip chain
u32  glyphHeight (px)   u32 b04   u32 b38   u32 b3c
f32x2 v28   f32x2 v30   f32 glyphHeightV = (glyphHeight - 1) / atlasHeight   f32 f24
u32  glyphCount
glyph, 27 bytes: u16 code, f32x2 offset, f32 width, f32x2 uv, f32 uWidth, u8 flag
```
All values are big-endian on the consoles. Read from code: the field order and sizes, the glyph
lookup by `code` (`0x441f47`), `glyphHeightV` and `width` (the debug-font builder `0x4425fb`
computes the first and averages the second into `f24`). **Inferred** from the values and
checked on every glyph of the 18 files: `uv` is the top-left corner in atlas units (`u·width`
is a whole pixel), `uWidth = width / atlasWidth`, every cell lies inside the atlas. Read from
the TextBox code (PC Part 2):

| field | meaning |
|---|---|
| `b04` | buffer +0x04: flags; bit 2 = every glyph advances by `f24` (0x43d390) |
| `b38` | buffer +0x38: horizontal alignment, overwritten at each TextBox draw (0x43d26e) |
| `b3c` | buffer +0x3c: vertical alignment, never read |
| `v28` | buffer +0x28: (letter spacing, extra line spacing); [0] is overwritten at each draw |
| `v30` | buffer +0x30: (scale x, scale y); overwritten at each draw |
| `f24` | buffer +0x24: the advance of every glyph when `b04 & 4` |
| `offset` | +0x04; pixels from the pen position to the quad's top-left (0x43efbb) |
| `width` | +0x0c; the advance in pixels (0x43d390) |
| `flag` | +0x1c; 1 = icon glyph: drawn white with the current alpha, not with the text colour (0x43efbb); `icon` in the JSON. 58 of the 211 glyphs of each game font in Part 2 PC |

The JSON names the buffer fields `flags` (`b04`), `h_align` (`b38`), `v_align` (`b3c`),
`spacing` (`v28`), `scale` (`v30`) and `fixed_advance` (`f24`), and the texture's `usage`
(`x`); the offset-style keys remain as aliases.
A code without a glyph is drawn as `@` (0x43ef1f; `fallback_code` 64). `x` is the texture usage (0x456d46; 0 in every font).
`default.font` = TOTAL OVERDOSE icon page (512x512, 200–202 glyphs, PS2 button prompts + TO
logo — inherited engine asset). DaveGibbons40 / TwCentMTCondExtra60 = 1024x512, 209 glyphs in
Part 1 and 211 in Part 2; the atlas also holds the controller button icons.

`watchmen extract` writes `<name>.font.json` (format `kapow-font/1`: descriptor, fields,
glyph table with a derived `rect_px`, `inferred` / `not_established` lists, `checks`) and the
atlas as `<name>.font.png` beside the raw asset. `font_asset.build(doc, pixels)` returns the
file: 18 of 18 fonts of the six sets rebuild byte for byte, and the decoded atlas is the same
image on PC, Xbox 360 and PS3 for all three fonts of both parts.

## .terrain (terrain_asset.py)
*Rewritten 2026-10-05 from the engine's readers (header `0x5397d0`, sector `0x52e011`,
render sector `0x529a1a`, stream `0x535e15` → `0x5345b1` → `0x532a6a`). The earlier text
gave the first float as a version and decoded the three path lists; 74 to 95% of each header
stayed in `tail_bytes`.*
```
f32 quadSize   u32 sectorQuads   u32 sectorsX   u32 sectorsZ      (sector = x * sectorsZ + z)
u32 n, n x ([u32 len][bmp path\0][u64 id])      texture layers
u32 n, n x path                                  grass assets
u32 n, n x path                                  detail mesh assets
u32 n, n x (path, u64 id)                        a second texture list ("decal textures")
u32 n, n x rectangle ("decal"):
    i32x4 quad rect x0 z0 x1 z1   u8 b10   f32 f14   u8 b18 b19 b1a   f32x4 f1c
    u32x4 place: sector, cell, vertex in sector, vertex in cell
    f32x3 box min   f32x3 box max   f32x4 sphere   vertex buffer [flags][count][formatId]
sectorsX * sectorsZ times: u8 present, then
    u8 flag   f32x3 x4: drawn box min/max, box min/max   f32x3 origin
    (sectorQuads / 32)^2 cells:
        f32x3 x4 boxes   u32 quadsX   u32 quadsZ   f32x3 origin   f32 quadSize
        vertex buffer [flags][count][formatId]   u8 hasIndices [flags][bytes][x]
        u32 grassMask   u32 detailMask       (bit id+1 per asset the cell uses)
```
`.terrain.stream`: the vertex buffer of every rectangle, then per present sector and cell
```
vertices   count x 48 bytes on PC (vertex format 8), 36 bytes on Xbox 360 / PS3
indices    u16, when the cell has an index buffer
u32x2      draw range of the whole cell (first index, end index)
u32 n, n x (first, end)   u32 n, n x layer      pass 1: one range per texture layer
u32 n, n x (first, end)   u32 n, n x layer      pass 2
u8 x (quadsX+1)(quadsZ+1)   grass id + 1 per vertex (0 = none)
u8 x (quadsX+1)(quadsZ+1)   detail mesh id + 1 per vertex
```
Vertex, PC: `float3 position`, half4 normal @12, D3DCOLOR @20, half4 uv @24, half4 tangent
@32, half4 bitangent @40 (stride 48 = format 8 of the stride table `0x00C791B0`). Consoles:
`float3 position`, packed 11:11:10 normal @12, colour @16 (A,R,G,B on Xbox 360; R,G,B,A on
PS3), half4 uv @20, packed tangent @28 and bitangent @32. The console layout is **matched
against the PC values, not read from console code**: over all 8 terrains positions, colours,
uvs, indices and both byte maps are identical to PC on both consoles and normals agree to
0.002. The colour's alpha is the texture layer of the vertex (see the 2026-10-03 note below).

Read from code: every field's position and type; the sector grid and its index; cells per
sector (`0x539577`); that a range is `(first index, end index)` drawn as `(end - first) / 3`
triangles (`0x52b16a`) for one texture layer (`0x5370f7` pass 1, `0x5371ef` pass 2, called
layer by layer from `0x53886b`); that the two byte maps are compared with `id + 1` under the
cell's masks when grass (`0x52e3ab`) and detail meshes (`0x53260b`) are placed. **The height
field is not stored**: at load the engine fills a 16-bit height texture from the mesh
(`0x535e15`). **Inferred** and counted on every file (`checks` in the JSON, all agree on 24
of 24 files): the boxes (all vertices / vertices the indices use; a cell without indices has
the empty box `+FLT_MAX / −FLT_MAX`), the meaning of `place` (the PC loader reads those 16
bytes raw), pass 2 as the blend overlay (each of its triangles repeats a pass 1 triangle
under another layer; pass 1 covers the surface once), and the name "decal" for the
rectangles (their textures are in a `Decals` folder; the code draws them after the terrain
passes). Read from code: sector `enabled` (+0x14; 0 = not drawn, 0x536321); decal `texture`
(index into the second texture list, 0x53886b), `wrap_u` / `wrap_v` (sampler address, 1 =
wrap, 0 = clamp; 0x4aebdb, 0x4aec0e, 0x458794); the index buffer's `primitive_type` (table
0xc7f398; 1 = triangle list); buffer `flags` (index: bit 0 = dynamic; vertex: bit 0 or bit 1 =
dynamic with a second buffer; bit 3 comes from the loader, not the file; 0x454159, 0x454a41).
Measured: `uv_rotation_deg` (uv − 0.5 = R(angle)·(st − 0.5) on 131 decals, residual ≤ 6.1e-4)
and `uv_scale` (v = t / 0.86 on 16 decals). **Not established**: `b18`; how `uv_offset` enters
the UV (one configuration in the data). The offset-style keys (`b10`, `f14`, `b19`, `b1a`,
`f1c`, `flag`, `x`) remain as aliases.

`watchmen extract` writes beside the raw asset: `<name>.terrain.json` (format
`kapow-terrain/2`: the whole header, `stream` with every offset and range, `height_field`,
`checks`, `inferred` / `not_established`; `tail_bytes` is 0), `<name>.terrain.height.png`
(16-bit, 0 = no sector there, else `min + (v − 1) / 65534 · (max − min)`; row = z, column =
x, engine axes), `<name>.terrain.layers.png` (texture layer per vertex, 255 = no data) and,
with `--glb`, `<name>.terrain.glb`: the pass 1 triangles, one node per texture layer, in
the frame of the toolkit's model exports (`--frame`), world space: the engine draws the
vertices with the identity matrix (0x49c3be), so the GLB needs no placement;
`files.terrain[].world` is the identity on all 24 shipped nodes (see
[LEVEL_META.md](LEVEL_META.md) "Terrain placement"), without textures. `terrain_asset.build` returns the header: 24
of 24 files of the six sets rebuild byte for byte, and all 24 streams are walked to their
last byte. The old keys `texture_layers` (`path`, `id`), `grass`, `detailmeshes` and
`tail_bytes` are kept; `version` and `header` are gone (`quad_size`, `sector_quads`,
`sectors_x`, `sectors_z`), and each layer has `unique_id`, the id as one number (two u32,
low word first, equal across platforms).
(2026-10-03: in the `TERRAIN` shader variants the colour's alpha is not an
opacity. It is a terrain layer id: `DeferredMain2VS` compares it with
`$terrainTextureNr` and passes 1 or 0. With `VERTEX_COLORS` the rgb is passed
on as a tint, as on models. Read from the shader bytecode, `re/vcolor.md` §2.
2026-10-05: on the stream bytes of all 8 terrains the alpha is below the layer count in
every vertex.)

## .terraincoloringasset (terrain_asset.py)
Part 1 only (5 per set). Header, 64 bytes (reader `0x52da01`): `u32 ×4` (the first two equal
the map size, the other two are 2), `f32 ×2`, `u32`, `f32`, `u8 ×3`, then one texture
descriptor (`0x429e77`). The stream is that texture: one 8-bit channel, L8 on PC (rows padded
to 4 bytes) and PS3 (behind a 36-byte RSX descriptor), DXT3A on Xbox 360. Sizes 768×768,
3072×2048 and one 1×1. `watchmen extract` writes `<name>.terrainColoringAsset.json` (format
`kapow-terraincoloring/1`; the values under their property names — `map_width`, `map_height`,
`ambientTextureWidth`, `ambientTextureHeight`, `ambientOcclusionBrightness`,
`ambientOcclusionContrast`, `numberOfRays`, `raycastLength`, `useTerrainAO`,
`randomDistribution`, `blurTexture` (read from code: 0x52da01 and the getters 0x52cb15 …
0x53a5f8; `numberOfBlurPasses` is not stored) — with the offset keys as aliases) and the map as `.png`. 15 of 15 headers rebuild; the PS3 image equals the PC
image pixel for pixel in 5 of 5; the Xbox 360 image differs by at most 16 (4-bit DXT3A),
and its 1×1 map reads 204 against 255 — the JSON marks that one `unverified`. That the map
is an ambient / colouring term is **inferred** (the editor command that writes the asset is
captioned "Generate Terrain Ambient"); how the renderer samples it was not read.

## .scene
The project scene (`WatchMenPart2.scene`, `WatchMen.scene`) is a **Fragment**: the asset
type `fragment` is registered with the source extensions `scene` and `fragment` (`0x542c1a`)
and has one header reader (`0x54306d`). Its root is the `SceneNode`; under a `Folder` it
holds one `SceneScope(LoadBlock)` per level (name, `assetName` = the level fragment, scene
id, cutscene movies, quad-tree bounds, four `LoadBlockMemorySetup` nodes for editor / PC /
X360 / PS3) and two `SceneScope(FragmentNode)` (the movie database and GameEssentials). `watchmen extract`
now writes `<name>.scene.json`: the fragment JSON plus a `scene` section (`root`, `scopes`,
`other_nodes`). 6 of 6 parse to the last byte (`lossless`), and the `scene` section is
identical on the three platforms of each part (8 scopes in Part 2, 9 in Part 1).

## .sequence — engine grammar (decode_sequence.py)
*Rewritten 2026-10-02 from the engine's readers (asset `FUN_0054558c`, object
`FUN_00544374` / `FUN_0054113c`, track `FUN_005415bf`, keys `FUN_00547f4c` /
`FUN_00547fdb`).* The previous description had the first float as a "version
(1.0/6.0/20.0)", per-key handle presence found by lookahead, and "slop bytes"
at object boundaries that the parser scanned across. None of that exists.

Keyframe tracks driving NODE PROPERTIES (cutscene cameras, doors, menu fades,
texture scrolls, AI-path gating):
```
[f32 durationSec][u32 loopMode][u32 nObjects]
object: [str targetPath][u32 hostsUp][u32 nIds][u32 id × nIds][str className][u32 nTracks]
track:  [str property][u32 interpolation][u32 nKeys]
key:    [f32 time][u32 interpolation][u32 dim][f32 value × dim]
        spline-capable tracks only: [u32 n][n × (f32 inT, inV, outT, outV)]
str = [u32 len][len bytes incl. NUL]; an empty path is [1]["\0"]
```
- interpolation: 0 inherited (on a key: use the track's), 1 step, 2 linear,
  3 spline. Per-key overrides are always 0 in the shipped data.
- A track carries the handle block on **every** key iff its property type is
  number, vector or quaternion (`FUN_00539dd9`). Handles are absolute
  (time, value) points; segments are cubic Hermite (`FUN_0040f5a1`).
- Quaternion properties are keyed as **Euler degrees** (x, y, z + one unused
  float), interpolated as a vector, then converted `q = qx·qy·qz`
  (`FUN_00499733`).
- The first float is the duration in seconds, not a version.
- An object can have a target path, instance ids, or both.
- No slop bytes: 194 / 194 (Part 2) and 260 / 260 (Part 1) files parse to the
  last byte on every platform checked. Part 2 PC: 366 objects, 584 tracks,
  2,002 keys (the old scanner found 351 / 569 / 1,972; the objects it missed
  are real — in the 15 door sequences, the door's own `localorient` track).
- **Header u32 = loop mode** *(2026-10-05; reader 0x54558c stores it at
  asset+0x94, the describe function 0x53cfce names it `loopmode`)*:
  0 `loop`, 1 `oneshot`, 2 `oneshot_reverse`, 3 `loop_reverse`, 4 `pingpong`.
  Play (0x49d705) starts modes 2 and 3 at `duration` running backwards, the
  others at 0. Per frame (0x49d7fe) the position moves by speed factor × the
  node's frame step (0xe14304: the game step, or the real step for a node with `useRealtime`,
  0x48e3a9; no PropertySequenceNode instance has `useRealtime` on PC Part 2 (813) or Part 1
  (1,050)); past the end: loop → position **0.0** (a reset, the overshoot is
  dropped, not a modulo), oneshot → `duration` and stop, pingpong → `duration`
  and turn round; below 0: oneshot_reverse → 0 and stop, loop_reverse →
  `duration`, pingpong → 0 and turn round. `PlayOverrideLoop(integer)`
  (0x49d794) plays with another mode; whether any script uses it is not
  established. Output: `loop_mode`, `loop_mode_name` (`h1` is kept);
  `decode_sequence.play_position(seq, t, mode=None, dt=None)`.

  | Staged set | files | loop | oneshot | pingpong |
  |---|---|---|---|---|
  | PC Part 2 `mainmenu` | 5 | 2 | 0 | 3 |
  | PC Part 2 `playervsplayer` | 4 | 2 | 2 | 0 |
  | PC Part 2 `tutorial` | 7 | 1 | 6 | 0 |
  | Part 2 main block, PC / X360 / PS3 (each) | 21 | 17 | 4 | 0 |
  | Part 1 main block, PC / X360 / PS3 (each) | 11 | 9 | 2 | 0 |
  | PC Part 2 `bordello` | 75 | 25 | 50 | 0 |
  | PC Part 2 `nightclub` | 84 | 32 | 52 | 0 |
  | PC Part 2 `streetsofriot` | 75 | 29 | 42 | 4 |
  | **Part 2, each of PC / X360 / PS3 (all files)** | 194 | 57 | 130 | 7 |
  | **Part 1, each of PC / X360 / PS3 (all files)** | 260 | 71 | 175 | 14 |

  Modes 2 and 3 are unused in all six sets (measured on the first 12 bytes of
  all 1,362 raw `.sequence` files); mode and duration are equal across the
  three platforms of a part; the exported `loop_mode` equals the raw value on
  1,362 / 1,362. The four pingpong records of
  StreetsOfRiot are Huey helicopter sequences (`Huey_01`, `Huey_03Streets`,
  `Huey_03aStreets`, `Huey_StreetOfRiot_Area_J`).
- **Action track** (read from code: 0x4ab2fe → 0x4ab230, 0x4a5d5e, 0x49d529, 0x4999e7):
  every direct child with a script class, `command_fire_action(entity)` and `_ndelay` (the
  `TriggerAction*` classes and `DelayedEmitterActivator`) is fired with itself as argument
  when the position passes `_ndelay` (last <= delay < new). Play sets the mark to 0
  (0x498192). Nothing fires on a falling position; a delay equal to the duration never fires;
  a loop wrap skips the rest. Measured: 1,127 such children in PC Part 2, 409 in Part 1.
  `decode_sequence.actions_fired(delays, last, new)` is the test; the level JSON has the
  children as `sequence_action` edges (LEVEL_META.md).
- **`updateCullingDistance`** (+0x150): when > 0 the whole update is skipped unless a camera
  of 0x49398c is nearer (0x49d7fe). Non-zero on 63 of 813 instances in Part 2, 215 of 1,050 in
  Part 1.
- `OnSequenceStart` is sent by Play (0x49d705), `OnSequenceStop` only by Stop (0x49d7a2), not
  when a oneshot ends.
- `speedFactor` is signed in code and neither branch clamps the far side; no stored value is
  negative (0.005–100). `decode_sequence.play_position(seq, t, speed=)` takes it.
- **Object u32 = `hosts_up`** *(2026-10-05; 0x5411dc → 0x53c224)*: the ids are
  an entity path. It starts at the fragment host of the **playing**
  PropertySequenceNode (the nearest `FragmentNode` at or above it, 0x48e4fe),
  climbs `hosts_up` further hosts (0x48e4e2), then finds each id as a child
  without entering nested hosts (0x53a5ff). The scene is never the base and
  there is no fallback when a step fails. It equals a fragment tag-4
  reference's `a − 1`. Data: the only non-zero value in the seven PC Part 2
  blocks is 1: on five path-object targets of NightClub's
  `MainRoomSetStaticPathToPassable.sequence`, and on the Sprite `5a787f10 / 42caa4a1 / a81361bb` of
  `MainMenuToIngameMenu.sequence`; its first id exists only one host above the
  node that plays the sequence. Output: `hosts_up` (the old key `flag` is kept).
- **Target kind** *(derived at load, 0x53ccab; output `target_kind`)*:
  `texture_sheet` — class `TextureSheet`, path `<texture path>#<n>` with n the
  0-based sheet of that texture (0x5443e2; output `texture`, `sheet_index`,
  −1 without `#`); `asset` — the class is an asset type (the engine tests the
  class tree; the toolkit uses the list of asset type names); `entity_path` —
  ids present; `self` — path `_this_`, the sequence node; `name` — any other
  path, a node **name** searched depth-first under the node's fragment host,
  nested fragments included (0x543601 → 0x48e3fd; case sensitivity not read).
  The 71 objects of the four PC Part 2 blocks are 31 `texture_sheet` and 40
  `entity_path`.

Classes seen: Camera(90), AIStaticPathObjectNode(26), TextBox, Model, PivotNode,
Sprite, TextureSheet, visionblocker(CollisionBoxNode)... Props: localpos(106),
impassable(27), opacity, localorient, uscrollspeed/vscrollspeed (the MaskSequence
Rorschach-mask UV scroll!), angle, textscaling...

`decode_sequence.parse()` tries the engine grammar first (`parse_exact`; the
result carries `"format": "kapow-sequence/2"`) and falls back to the old
scanner when a file does not parse to its last byte. The key class of a track
comes from the property's registered type (`kapow_fragment.NAMES`); all 27
property names used by the Part 2 sequences are typed there.
`evaluate(track, t)` samples a track. A linear segment uses the data type's
own interpolator (vtable +0x68, dispatched by 0x53aa43) *(2026-10-05)*:

| type | function | rule |
|---|---|---|
| number | 0x4fa5bb | `a + (b − a)·t` |
| vector | 0x4fbf8d | per component |
| quaternion track | 0x53aa43 | the vector rule on the Euler-degree keys |
| integer | 0x4fac1c | `a + trunc((b − a)·t)` (0x990ba0 is `cvttsd2si`) |
| truth, color, every other type | 0x47fc01 (base) | copies key A: a hold |

`evaluate` follows it: it blends number / vector / quaternion, truncates on
integer and holds key A otherwise (also on a non-spline track whose property
is not in the name table). No value changes on the staged blocks: every
`truth` track there is step, and there is no integer or color track.

## .model node tail — collision volumes
*Added 2026-10-02 (`Node::Deserialize` 0x545927; report `re/skeleton_blobs.md`).*
Earlier notes called these records "EmbeddedJointNode joints, types 4/5/6/7"
and read them as fixed 48-byte records `[type][0][pos][a][a'][quat]`. They are
the node's collision shapes; only the capsule is 48 bytes, and what was read
as `pos` was a capsule's (diameter, height, x).

After `[u32 f1][i32 parent]` comes the node's mesh section, then three lists:

    [u32 nLod] nLod × ( [u32 nSub] nSub × submesh )           nSub > 0 only on mesh nodes
    [u32 nGroup] nGroup × ( [u32 n] n × shadow hull )          a group may be empty
    [u8 hasOccluder] ( MeshBuffer )
    [u32 n0] n0 × volume     shapes for PhysX scene 0
    [u32 n1] n1 × volume     shapes for PhysX scene 1
    [u32 n2] n2 × surface    particle emission meshes (class MeshParticleData)

    volume  = [u32 type][u32 0][type data][f32×3 pos][f32×4 quat xyzw][u32 blobLen][blob]
    surface = [u32 nT][nT × (f32×3 normal, f32 weight, i32 materialId)]
              [u32 nV][nV × f32×3][u32 nI][nI × u32]

*(2026-10-05)* Many mesh-free bones have `nGroup = 1` with an empty group
(e.g. every bone of `Heavies_FlaredTrousers.model`). The name-anchored reader
`skeleton_records.parse_node_tail` gives up on any non-zero group count, as it
always did; `parse_node_tail(..., meshes=True)` walks the mesh section
(submesh 0x542541, MeshBuffer 0x4336ec) and reads the lists of every node.
The header-driven readers (`watchmen_extract.parse_model_header`,
`parse_model_nodes.model_physics`) read every node of every model.

| type | shape | type data | bytes without blob |
|---|---|---|---|
| 2 | concave mesh | u32 mode, u32 nV, verts, u32 nI, indices | variable |
| 4 | convex mesh (blob "NXS\x01CVXM…") | same | variable |
| 5 | box | f32×3 full extents | 52 |
| 6 | sphere | f32 radius | 44 |
| 7 | capsule | f32 diameter, f32 height along local Y | 48 |

`pos` / `quat` are the volume's placement in the node's (bone's) frame. The
blob is a cooked PhysX mesh and exists only for the mesh types.

PC corpus (740 models): 934 volumes in 23 models (743 capsules, 123 boxes, 51
spheres, 17 convex meshes); 2,069 / 2,069 mesh-free node regions tile. These
are not joints: the jiggle joint is created at run time in the parent bone's
frame (ENGINE_CONSTANTS.md). Which game purpose each of the two PhysX scenes
serves is not established; that the third list is a particle-emission surface
is inferred. *(The 2,069 is 2,081 on the 738 distinct models staged for the
2026-10-05 pass.)* *[2026-10-04: both settled. List 0 (scene 0) holds the ragdoll /
"default collision" shapes, list 1 (scene 1) the shapes cloth collides with
(`re/wp2_physics.md` §0.3, A.1); the third list is the particle emission
surface consumed by `SurfaceSpawner` (0x553d4d, `re/wp7_fx_camera_hud.md`
§2.4): triangles `(f32x3, f32, i32)`; the i32 is the material id compared
with the spawner's `materialId` (negative = any), a triangle is used when its
world normal's Y is at least `faceCullLimit`, and the float is the area
weight for `particleAmount` particles per m2 (the float's meaning is
inferred). No Part 2 `.particle` uses a `SurfaceSpawner`; **Part 1 does**
(`rain_surfacesplash.particle`, three types: 0.25 / 0.5 / 10 particles/m2
within 18 / 9 / 7 m, `faceCullLimit` -0.6, `spawnOnGeometry` only,
`materialId` -1), so the list is the rain-splash surface of Part 1 level
models and unused content in Part 2.]*

### Particle emission surfaces (the third list)
*Added 2026-10-05. This replaces "non-empty on one node of the PC corpus" and
"the float's meaning is inferred" above.*

- **Class** `MeshParticleData`: the element constructor 0x560601 installs
  vtable 0xa3d538; reader 0x561d1c reads the per-triangle records, then the
  base `MeshData` reader the vertices and indices.
- **Data** (738 distinct PC Part 2 `.model` files staged): **29 surfaces in 19
  models**, 1,094 triangles; 15 of the 29 sit on nodes that carry meshes.
  `Rorschach.model` and `Rorschach_Dry.model` have six each, the other 17
  models one each.
- **Weight = triangle area in m²** on 27 of the 29 surfaces (rtol 5e-3: the
  console copies of five Part 1 models store areas 0.10–0.16 % off, which
  the earlier 1e-3 reported as "not the area"). The two exceptions
  (`ACUnit_Wall_02`, 2 triangles of 0.4928 m²; `Pallet_01`, 4 triangles) have
  weight exactly 1.0 on every triangle, whatever the area
  (`weight_is_unit` in the sidecar). Part 1 has 17 such surfaces among 109
  (2–292 triangles, 13 of them with unequal triangles); over both parts 8
  are on nodes named like splash emitter / surface, 2 on other named nodes,
  7 on the unnamed root, so the constant is not tied to the node name. Why
  is not established. Stored normals are unit length and opposite to the
  index winding; on Rorschach's Spine2 and Head surfaces the normal is the
  face normal, on his four arm surfaces it is 21–36° off (measured; the
  cause is not established). `particleAmount` is
  captioned `Particles/m2`, so the budget is particles per m² × collected area.
- **Material ids** over all triangles: −1 on 1,018, 0 on 30, 2 on 32, 1 on 14
  (`OilBarrel_01`: 60 triangles, 0 / 1 / 2 on 14 / 14 / 32).
- **Stored vector**: on props it is exactly opposite the normal the index
  winding gives (as on render meshes); on the two Rorschach models it is not
  the face normal (cosine 0.81–0.94 against it).
- **Geometry rule** (`SurfaceSpawner`, 0x54fc6b → 0x54decc; with `materialId`
  < 0 on the spawner 0x54e23e): a triangle is collected when its id equals the
  spawner's `materialId` (integer compare), its normal rotated by the **Model
  scene node's** matrix (one matrix for the whole model; the per-node pivot is
  not applied) has world Y ≥ `faceCullLimit`, and its centroid lies within
  `radius` in XZ. The collector stops at 1,500 triangles.
- **Spawn** (0x553c41): budget = trunc(`particleAmount` × Σ weight). Each pick
  takes a random collected triangle and costs one unit of budget; it spawns
  one particle per whole unit of the triangle's weight above 1 (one more unit
  of budget each), then one more with probability equal to the remainder.
- **Character rule** (`spawnOnCharacters`, 0x553bae tests the two flags;
  0x54fba7): surfaces are collected per ragdoll **body**, from the node that
  body is bound to (node index at body+0x98), transformed by the body's world
  matrix (body+0x4c), culled by `faceCullLimit` and material id — there is no
  radius test on this path (0x54dc28 never reads its centre argument). A
  surface on a node that is not a ragdoll body's node is never collected.
  X360 Part 2 has the same rule (`0x828e9340` → `0x828e3a10` → `0x823255e8`
  when `materialId` < 0, else `0x82325310`); body node index at +0x9c, matrix
  at +0x50. The triangle buffer holds 1,500 records on both (PC 102,000 bytes
  at 68, X360 120,000 at 80). The constant third argument of the PC call
  (`0x9e803c`) is not passed on X360.
- **Output.** `parse_volume_lists` surfaces: `class`, `tris` [{`normal`,
  `area_weight`, `material_id`}] (the old keys `vec`, `value`, `id` are kept
  for one release), `verts`, `indices`, `weight_sum`, `weight_is_area`.
  `watchmen_extract.model_surfaces(header)` returns them for every node,
  `parse_model_nodes.model_physics` puts them on its nodes, and the model
  sidecar `<name>.model.json` gains `particle_surfaces` [{`node`, `part`,
  `class`, `triangles`, `vertices`, `material_ids`, `weight_sum`,
  `weight_is_area`}] on the 19 models that have any (no key otherwise); a
  surface whose weights are all exactly 1.0 also carries `weight_is_unit`.
- **Not established**: the scene assignment of lists 0 / 1 was not re-read in
  this pass; why splash-emitter triangles hold 1.0.

Parsers: `skeleton_records.parse_node_tail(mb, start, end, order)` /
`parse_volume_lists`; `skeleton_records.parse()` records carry `volumes`; the
skeleton JSON has an optional `collision_volumes` per bone (`type`, `scene`,
`pos`, `quat_xyzw`, and `size` | `radius` | `diameter` + `height` | `mode` +
`verts` + `indices` + `cooked_blob_bytes`).
`parse_model_nodes.parse_node_aux(mb, start, end, order)` returns the same
tail: `volumes` = [scene 0 list, scene 1 list], `surfaces`, and `joints` =
the same volumes flattened for older callers (`type`, `pos`, `quat`, `blob`,
`scene`; `a` / `a2` = a capsule's diameter / height). Mesh nodes are not read
(3,401 of 5,470 node records).

## The `sound` asset

*Added 2026-10-04 (loader 0x449e40; report `re/wp6_audio.md`).*

After the property bag (`pe` = its end; loader 0x449e40):

| Offset | Type | Field |
|---|---|---|
| pe+0 | u8 | looping (55 sounds; the whole sample loops, there are no loop points) |
| pe+1 | u8 | 3D |
| pe+2 | u32 | channels (1 or 2) |
| pe+6 | u32 | original (source) rate |
| pe+10 | u32 | codec: 1 PCM16, 2 MS-ADPCM, 3 XMA2 |
| pe+14 | u32 | sample rate of the stored data: 44100 on every mono sound, the file's own rate (43937 ... 48016) on the 35 stereo sounds |
| PCM: pe+18 / pe+22 / pe+26 | u32 / u32 / bytes | samples, data bytes, data |
| ADPCM: pe+22 / pe+26 / pe+30 / pe+58 / pe+62 | u32 / u32 / 14 x i16 / u32 / bytes | samples, block align, coefficients, data bytes, data |
| after the data | u32 + list | cue count (0 in every shipped sound), then `[str name][u32 sample]` |

`extract` writes `audio/sound_info.json` with these fields per sound. Up to 1.3.0 every sound was
written at 44100 Hz and PCM data was read from pe+30.

**Console** *(added 2026-10-05, from data on all 2,921 Part 2 and 3,953 Part 1 sounds of
each console; the console loaders were not read)*. Big-endian.

Xbox 360 follows the table above with codec 3: sample count at pe+18, data size at pe+22
(a multiple of 2,048), **XMA2 packets from pe+26**, then the cue count. The sample count
equals the packets' frame counts × 512 on every sound. (1.3.0 cut from pe+30: every `.xma`
began four bytes into its first packet and ended with the cue count, and no decoder read
it.)

PS3:

| Offset | Type | Field |
|---|---|---|
| pe+0 | u8 | looping |
| pe+1 | u8 | 3D |
| pe+2 | u8 | 1 on every sound (meaning not established) |
| pe+3 | u32 | rate |
| pe+7 | u32 | channels |
| pe+11 | u32 | samples: MP3 frames × 1,152 on a non-looping sound, (frames − 2) × 1,152 on a looping one (55 in Part 2, 90 in Part 1) |
| pe+15 | u32 | bytes per second |
| pe+19 | u32 | size |
| pe+23 | 32 bytes | segment header (its dword 4, on looping sounds only, is the byte length of two MP3 frames, floor(2 × 1152 × bytes per second ÷ rate): 384 / 417 / 768, on 145 of 145 looping sounds of both PS3 sets. Inferred: the byte offset of the looped region, matching the sample count of frames − 2. Exported as `segment_word4`, with `segment_word4_rule` and `loop_skip_frames` 2) |
| pe+55 | bytes | MP3, whole frames; then 0–15 bytes of padding and the u32 cue count |

Console lengths are whole codec frames: Xbox 360 0 to 0.02 s over the PC length (median
0.010 s), PS3 0.03 to 0.064 s over (median 0.045 s; the encoder delay and frame padding are
inside the count). Loop flag, 3D flag, channels and rate agree with PC on every sound. A
console record of `sound_info.json` carries `duration_source` (`header`, `frame_count`,
`none`) and `xma_frames` or `mp3_frames`. No shipped console sound has a cue point.

Part 2 PC, 2,921 sounds: 35 stereo sounds carry their own rate (27 of them
about 48000 Hz), 50 are PCM; 76 files were wrong in 1.3.0 for one or both
reasons, the other 2,845 are byte-identical.

## `.pb` pivot book

*Added 2026-10-04 (parser `skeleton_records.parse_pivot_book`).* A pivot
book is a list of pivot sheets — physical surface materials:

    [u64 bookId][u32 sheetCount]                      12-byte header (0x528326; default.pb 0x0000296416269EFA;
                                                      one u64 in the file's byte order, the same id on all six sets)
    count × { [u32 n]["PivotSheet\0"][u32 nDw][property records] }
    closing object "PivotBook\0"

Property records are `[objId u32][keyHash u32][typeId u32][nWords u32][data]`,
the same record the model's articulated-body blob uses (KAPOW_NAZ_FORMAT.md
§6b). A sheet has a name, friction, restitution and a collision mask.
`default.pb`: sheet `Ragdoll` friction 0.6, restitution 0, mask 0x1;
`Ragdoll_All` (the two players) 0.6 / 0 / 0x401. Read on 3 of 3 files.
The standalone Part 1 (PC, Xbox 360) stores these records without `typeId`;
`ragdoll_rig.pivot_sheets` then reads the book through `kapow_props.pivot_book`. The Ragdoll
sheet's `uniqueID` is `0x43b830d445af888d` on all six tested sets (a 64-bit value is two
words, low word first, each byte-swapped on console).
`watchmen ragdoll MODEL default.pb` puts the sheet into the rig's `common.material`.

## Console shader archive (PS3)

`shader.archive`: u32 version (2), u32 count, then count × {u32 name length, name with
NUL, u32 offset, u32 size}; offsets are relative to the end of the index; big-endian. PS3
(one file for both parts, md5 a741f39e7b2b96bbf0ac9b74d9cbbff2): 243 entries, index ends at
0x444f. An entry is `"CGB\0"`, a 0x20-byte header, NV40 vertex or fragment microcode
(vertex: 16 bytes per instruction, last-instruction flag in bit 0 of the fourth word),
constants ({u16 size, u16 count, u16 index…, 4 floats}), then a parameter table and names.
The Xbox 360 archive (md5 b83733fb…) and the PC archive differ and were not opened here.
The toolkit does not read this file; the layout is measured on the PS3 file and is what the
console joint order in [KAPOW_NAZ_FORMAT.md](KAPOW_NAZ_FORMAT.md) §6b was read through.

## JSON pipeline (integrated)
`watchmen_extract.py` now emits `.json` beside every extracted
.fragment/.scene/.sequence/.pb/.particle/.grass/.detailmesh/.terrain/.terraincoloringasset/.font
(lazy import of
`kapow_json.py`; `--no-extract-all` disables). `kapow_json.fragment_json` merges the
schema node tree (decode_fragment) + named instances + keyed transforms
(decode_spawns) into one dict. Standalone: `python3 kapow_json.py FILE [OUT.json]`.
*[2026-10-04: `.particle` goes to `particle_asset.to_json` (format `kapow-particle/2`); a file
that is not a complete tree still gets the generic walk plus a `warn` line. `.scene` is read as
a fragment, and fragment JSON carries the file `header`. The others are unchanged.
2026-10-05: `.font`, `.scene`, `.terrain`, `.terraincoloringasset` and `.detailmesh` go
through `kapow_json.export`, which also writes the atlas / map PNGs and the terrain GLB and
returns the log lines; an asset or part that is not decoded has a marker in its JSON
(`not_decoded`, `leftover_bytes`, `trailing_bytes`, `tail_bytes`, `stream.not_decoded`,
`unverified`) and a `WARNING:` / `note:` line in the log. Text tables
(`textRes`) are written decoded to `text/` (TEXT_ASSETS.md), navigation data to `nav/`
(NAV_DATA.md).]*
Backup of pre-patch extractor: `watchmen_extract.py.bak3`.
