# Misc Kapow asset formats — ALL DECODED (2026-07-02 session)

The 7 leftover extensions in `20260628/extracted`, plus the universal serialization
they revealed. Decoders in this folder; JSON emission integrated into
`watchmen_extract.py` (writes `extracted/<name>.json` next to each raw asset;
batch-converted tree: 1203/1203 files, 0 errors).

## THE KEY DISCOVERY: the Kapow property-hash
Property/type names are hashed with a bit-serial CRC32 (poly 0x04C11DB7, MSB test
before shift-in, bits LSB-first per char, NO salt) over the UPPERCASE name:
`kapow_hash('NAME') = 0x7282b2a2`, `kapow_hash('LOCALPOS') = 0x2f0823c4`,
`kapow_hash('LOCALORIENT') = 0x51172879` — the "unknown keys" in FRAGMENT_FORMAT.md
are now all nameable. Dictionary built by hashing all 24k exe strings:
`prop_hash_dict.pkl` (kapow_props.namedict()). Type tags = kapow_hash of
'NUMBER','INTEGER','TRUTH','STRING','VECTOR','QUATERNION',...
Implementation: `kapow_props.kapow_hash`.

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
  25B tail = stream-linkage descriptor. Its `.stream` = packed scatter geometry
  ([u32 8][8 sub-buffer offsets][...]; the known stride-16 baked-env vertex class).
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

## .sequence — SOLVED (decode_sequence.py, 194/194 files, 351 objects/569 tracks)
Keyframe tracks driving NODE PROPERTIES (cutscene cameras, doors, menu fades,
texture scrolls, AI-path gating):
```
[f32 version (1.0/6.0/20.0)][u32][u32 nobjects]
object: target = [u32 n][n x u32 instance-ids]  OR  [u32 len][resource path "#sub"]
        (+slop bytes) [u32 len][ClassName\0][u32 ntracks]
track:  [u32 len][propname\0][u32 ttype][u32 nkeys][keys]
key:    [f32 t][u32 mode][u32 dim][dim f32 value]
        [optional: [u32 hdim][4*hdim f32] bezier handles (inX,inY,outX,outY)/comp]
```
Classes seen: Camera(90), AIStaticPathObjectNode(26), TextBox, Model, PivotNode,
Sprite, TextureSheet, visionblocker(CollisionBoxNode)... Props: localpos(106),
impassable(27), opacity, localorient, uscrollspeed/vscrollspeed (the MaskSequence
Rorschach-mask UV scroll!), angle, textscaling...
Handle presence is per-key (lookahead-validated); object boundaries are slop-tolerant
(parser scans +-24..256 bytes).

## JSON pipeline (integrated)
`watchmen_extract.py` now emits `.json` beside every extracted
.fragment/.sequence/.pb/.particle/.grass/.detailmesh/.terrain (lazy import of
`kapow_json.py`; `--no-extract-all` disables). `kapow_json.fragment_json` merges the
schema node tree (decode_fragment) + named instances + keyed transforms
(decode_spawns) into one dict. Standalone: `python3 kapow_json.py FILE [OUT.json]`.
Backup of pre-patch extractor: `watchmen_extract.py.bak3`.
