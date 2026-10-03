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
- **.particle** (89/89 clean): ParticleSystemAsset + per-variation ParticleType
  ("Smoke": maxParticles/blendMode/Texture=.bmp/...) + affector/spawner blocks
  (SizeSequence/OpacitySequence/Illumination/ColorSequence/LinearForce/Dampening,
  Regular/Irregular/BurstSpawner, VarianceInitializer, UVArrayInitializer).
- **.grass** (3/3, 0 trailing): grass template — texture, density, cell counts,
  width/height+variance, sway (sinMod/cosMod), LOD, collisionPower etc.
- **.detailmesh** (5/5): scatter template -> model path + lighting/sway/range params;
  25B tail = stream-linkage descriptor. Its `.stream` =
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

## .font — SOLVED (decode_font.py)
30B header [u16 ver=1][u32 npanes][u16 fmt=2][u32 256][u32 0][u32 256][u16 256]
[u16 pointsize?][6B 0]; ONE RGBA8 atlas W=256*npanes, H=512 + full mip chain
(~W*H*16/3 bytes); 16B float params; u32 count; 27B glyph records
[u16 char][u32][f32 yoff][f32 advance px][f32 u][f32 v][f32 uwidth][u8 flag].
default.font = TOTAL OVERDOSE icon page (512x512, 202 glyphs, PS2 button prompts
+ TO logo — inherited engine asset). DaveGibbons40/TwCentMTCondExtra60 = 1024x512,
211-212 glyphs. Verified by atlas render.

## .terrain — SOLVED (kapow_json.terrain_json)
`[f32 1.0][u32 64][u32 6][u32 8][u32 ntex]` + ntex x ([u32 len][bmp path\0][u64 id])
+ [u32 nGrass][paths...] + [u32 nDetail][paths...] + tail params.
`.terrain.stream` = plain 48B-stride VERTEX BUFFER (Mansion: exactly 18642 verts,
grid positions x stepping 1.0; standard env vertex layout pos3f+normal+color+uv;
indices procedural). Ties terrain -> its .grass + .detailmesh scatter layers.
(2026-10-02: stride 48 is the engine's vertex format 8 — pos, half4 normal,
colour, three half4 texcoords; matched by stride, not re-validated on the file.)

## .sequence — engine grammar (decode_sequence.py)
*Rewritten 2026-10-02 from the engine's readers (asset `FUN_0054558c`, object
`FUN_00544374` / `FUN_0054113c`, track `FUN_005415bf`, keys `FUN_00547f4c` /
`FUN_00547fdb`).* The previous description had the first float as a "version
(1.0/6.0/20.0)", per-key handle presence found by lookahead, and "slop bytes"
at object boundaries that the parser scanned across. None of that exists.

Keyframe tracks driving NODE PROPERTIES (cutscene cameras, doors, menu fades,
texture scrolls, AI-path gating):
```
[f32 durationSec][u32 flags][u32 nObjects]
object: [str targetPath][u32 flag][u32 nIds][u32 id × nIds][str className][u32 nTracks]
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
- Not established: the header `flags` (0 / 1 / 4 observed) and the object
  `flag` (0 / 1).

Classes seen: Camera(90), AIStaticPathObjectNode(26), TextBox, Model, PivotNode,
Sprite, TextureSheet, visionblocker(CollisionBoxNode)... Props: localpos(106),
impassable(27), opacity, localorient, uscrollspeed/vscrollspeed (the MaskSequence
Rorschach-mask UV scroll!), angle, textscaling...

`decode_sequence.parse()` tries the engine grammar first (`parse_exact`; the
result carries `"format": "kapow-sequence/2"`) and falls back to the old
scanner when a file does not parse to its last byte. The key class of a track
comes from the property's registered type (`kapow_fragment.NAMES`); all 27
property names used by the Part 2 sequences are typed there.
`evaluate(track, t)` samples a track; its linear branch is a component-wise
lerp (the engine calls the type's own interpolator, which was not read).

## .model node tail — collision volumes
*Added 2026-10-02 (`Node::Deserialize` 0x545927; report `re/skeleton_blobs.md`).*
Earlier notes called these records "EmbeddedJointNode joints, types 4/5/6/7"
and read them as fixed 48-byte records `[type][0][pos][a][a'][quat]`. They are
the node's collision shapes; only the capsule is 48 bytes, and what was read
as `pos` was a capsule's (diameter, height, x).

After `[u32 f1][i32 parent][u32 cnt34][cnt34 × u32][u32 cnt40][u8 flag]` (mesh
nodes carry data in cnt34 / cnt40):

    [u32 n0] n0 × volume     shapes for PhysX scene 0
    [u32 n1] n1 × volume     shapes for PhysX scene 1
    [u32 n2] n2 × surface    non-empty on one node of the PC corpus (ACUnit_Wall_02 "splash emitter")

    volume  = [u32 type][u32 0][type data][f32×3 pos][f32×4 quat xyzw][u32 blobLen][blob]
    surface = [u32 nT][nT × (f32×3, f32, i32)][u32 nV][nV × f32×3][u32 nI][nI × u32]

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
is inferred.

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

## JSON pipeline (integrated)
`watchmen_extract.py` now emits `.json` beside every extracted
.fragment/.sequence/.pb/.particle/.grass/.detailmesh/.terrain (lazy import of
`kapow_json.py`; `--no-extract-all` disables). `kapow_json.fragment_json` merges the
schema node tree (decode_fragment) + named instances + keyed transforms
(decode_spawns) into one dict. Standalone: `python3 kapow_json.py FILE [OUT.json]`.
Backup of pre-patch extractor: `watchmen_extract.py.bak3`.
