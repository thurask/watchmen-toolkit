# `.particle` — particle system assets (format `kapow-particle/2`)

Parser: `wlib/particle_asset.py` (`parse`, `build`, `to_json`, `values`, `references`,
`parse_gradient`, `gradient_at`, `schema_table`, `detect_order`). The extractor writes its result
as `<name>.particle.json` (`kapow_json.to_json`); `watchmen fragment FILE.particle` does the same
for one file; `watchmen particlemeta EXTRACT_OUT OUT_DIR` writes all of them into one folder with an
index (`wlib/particle_meta.py`, section 6a).

Source: the Part 2 PC executable. Loader `ParticleSystemAsset::vfunc_24` 0x55d3ed, writer
`vfunc_23` 0x558a29, object reader 0x511f96 (into an existing object) / 0x511eb5 (create by class
name), record application 0x510e5f, record writer 0x5015d7, data types 0x501f6a.

Evidence marks: **[R]** read from the executable (address given), **[D]** read from the game data,
**[I]** inferred, **[wp7]** taken over from `re/wp7_fx_camera_hud.md` section 2 without re-reading.

Coverage on real data (2026-10-04, seven extracts, 746 files): Part 2 PC / X360 / PS3 89 files
each, Part 1 PS3 130, Part 1 PC 130, Part 1 X360 130 — every file parses to the last byte with no
unknown class, no unknown property hash and no ignored record, and `build(parse(x)) == x`.

## 1. Grammar [R]

```
file    = object(ParticleSystemAsset)
          u32 nTypes
          nTypes x { object(ParticleType)
                     u32 nAffectors     nAffectors    x object     -> type+0x60
                     u32 nSpawners      nSpawners     x object     -> type+0x48
                     u32 nInitializers  nInitializers x object     -> type+0x54 }
object  = u32 nameLen, nameLen bytes "ClassName\0"          (0x437469; nameLen counts the NUL)
          u32 payloadDwords, payloadDwords x 4 bytes of records
record  = u32 objectId, u32 nameHash, u32 typeHash, u32 k, k dwords of value
```

- There is no file header, no version and no padding; the file ends after the last list.
- **Class identification**: the class name string. 0x511eb5 looks the name up in the type registry
  (0x50211a) and creates the object through the type (vfunc +0x6c; the class factory is the
  pointer the registration stores at `type+0x2c`); 0x511f96 compares it with the type of the
  object being filled and re-types the object when it differs.
- **`objectId`** is the session id of the saved entity (`entity+0x28`, written by 0x5015d7). All
  records of an object carry the same value; 0x510e5f stops applying at the first record whose id
  differs from the first record's. It has no other meaning to the loader.
- **`nameHash`** = `kapow_props.name_hash(property name)`; **`typeHash`** = `name_hash(type name)`
  (`DataType+0x1c`, set by 0x4fa12f).
- A record is **applied** only if the class (or a base class) registers a property with that hash
  and the stored type hash equals that property's type, and two per-property checks pass (0x4f934b,
  0x4f93ec: bit 0 of the property flags must be clear; not analysed further). Otherwise it is
  skipped by `k`. For an applied record the engine advances by the
  type's own size, not by `k` (the two agree in every file).
- The writer (0x50c74e -> 0x50b6ac) emits one record per stored property; in the data [D] these are
  always the complete set in registration order, base class first, defaults included. `absent` is therefore empty for
  all Part 2 files.
- **Byte order**: little-endian on PC, big-endian on X360 / PS3. 0x5015d7 byte-swaps the three
  header dwords, `k` and every value dword (`DataType::vfunc_07` 0x4f361f); for a string only the
  word count is swapped (`StringType::vfunc_07` 0x4ebaa2). `detect_order` takes the order in which
  the first dword is a class-name length followed by that many bytes ending in NUL.

Value encodings (`DataType` constructors, id / name / dwords):

| Type | Hash | k | Encoding |
|---|---|---|---|
| `number` (1) | `bda17de4` | 1 | float32 |
| `integer` (2) | `36604ff4` | 1 | int32 |
| `truth` (5) | `fd034a24` | 1 | dword, low byte 0 / 1 (`TruthType::vfunc_13` 0x4fb3b3) |
| `vector` (6) | `71d8181d` | 3 | x, y, z float32 |
| `quaternion` (7) | `d007189c` | 4 | x, y, z, w float32 (identity 0 0 0 1) |
| `color` (8) | `a63a59bd` | 1 | dword (no particle property uses it) |
| `string` (4) | `144b7b5d` | 1 + words | u32 words, words x 4 chars, NUL padded; words = (len + 4) >> 2, so "" is one zero word; a null pointer is the single dword 0 (`StringType::vfunc_13/14` 0x4ebac7 / 0x4ebb1d) |

## 2. The Part 1 PC / X360 record layout [D]

The Part 1 PC and X360 archives were written by an older build. Its records have no type hash:

```
record  = u32 objectId, u32 nameHash, u32 k, k dwords of value          ("untyped")
```

Everything else is the same. This is read from the data, not from an executable: all 260 files
parse to the last byte with the Part 2 class tables, no unknown hash and every value size equal to
the registered type's. Differences in content: `ParticleSystemAsset` has no `renderInstanced` /
`numVariations`, and `ParticleType` stores the deprecated `localMode` instead of `simulationMode`.
Part 1 on PS3 (the combined disc) uses the typed layout. `parse` tries the typed layout first and
reports `record_layout`.

## 3. Classes [R]

28 classes can appear (two tree classes and 26 modules). Modules derive from `ParticleModule`
(0x5605b8, base `Entity`) through `ParticleAffector` (0x565242), `ParticleInitializer` (0x56528b) or
`ParticleSpawner` (0x5652d4); `ParticleTypeAffector` (0x56531d) and `ParticleAligner` (0x565366) are
registered bases without a concrete class. The loader does not check that a module sits in the list
of its base class (the parser reports a mismatch as `warn`; none occurs).

Every `Entity`-derived object (the type and all modules, not the asset) stores five `Entity`
properties first (`Entity::RegisterMembers` 0x511603, constructor 0x50da83):

| Property | Hash | Type | Default | Offset | Meaning |
|---|---|---|---|---|---|
| `name` | `7282b2a2` | string | "" | +0x20 | editor name (type names such as "SmallArc"; modules are unnamed) |
| `useRealtime` | `9b9b2ff5` | truth | false | +0x2c | |
| `recordInSavepoints` | `2bb48300` | truth | true | +0x2d | no reader in the PC build |
| `runScript` | `7829e877` | truth | true | +0x34 | "Auto-resume script" |
| `open` | `f20aa272` | truth | false | +0x2e | editor tree state |

`ParticleType` also registers the lists `typeAffectors` (+0x3c), `spawners` (+0x48), `affectors`
(+0x60), `initializers` (+0x54) and `ownerAsset` (+0x104), and the asset `particleTypes` (+0x90,
`list(entity)`); none of them is stored as a record - the lists are the counted object sequences
of the grammar. `typeAffectors` is not in the file at all.

Defaults are the constructor values (float constants read from the executable's bytes). Offsets are
read from the getters. "UI range" is the editor's spinner range from the registration string; it is
not enforced by the setters unless stated.


### `ParticleSystemAsset` (system; base `Asset`; RegisterMembers 0x55da60, constructor 0x559fed)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `duration` | `ad24189d` | number | 1.0 | +0x9c | 0..50 | s; a non-looping emitter is stopped (clock reset, EMITTERSTOP event 3) when its clock exceeds it (0x55b104); period of the per-type startTime/endTime window (0x55a722) |
| `loop` | `32f2f20a` | truth | true | +0xa0 |  | copied to each emitter (+0x15, 0x55d31c); looping emitters never stop at `duration` |
| `enableUpdateEvents` | `3ba0ac68` | truth | false | +0xa1 |  | raise PARTICLEUPDATE (7) per live particle per frame (0x55a643) |
| `enableDieEvents` | `96cef61c` | truth | false | +0xa2 |  | raise PARTICLEDIE (5) when timeLeft <= 0 (0x55a503) |
| `enableSpawnEvents` | `f2ee7065` | truth | false | +0xa3 |  | raise PARTICLESPAWN (6) after the initializers (0x55f512) |
| `alwaysUpdate` | `15bf11c4` | truth | false | +0xa4 |  | simulate even when culled (0x5586e3) [wp7] |
| `evolveFramesOnStart` | `87eaf40e` | integer | 0 | +0xa8 | 0..100 | frames of 0.033 s pre-simulated at start (0x55d180) [wp7] |
| `cullingRadius` | `b9796801` | number | 1.0 | +0xac |  | m; bounding sphere tested against the frustum [wp7] |
| `cullingDistance` | `4566ffd1` | number | 60.0 | +0xb0 |  | m; no simulation beyond this camera distance [wp7] |
| `renderInstanced` | `660614f6` | truth | false | +0xb4 |  | setter rebuilds `numVariations` pre-built emitter variations (0x55d695 -> 0x55d31c) |
| `numVariations` | `d87ed69a` | integer | 1 | +0xb8 | 1..20 | number of pre-built variations when renderInstanced (0x55d31c). With `renderInstanced` the asset pre-builds N shared simulation instances, one emitter each, loop flag copied from the asset; each owning node, on binding, takes `variations[rand_integer(N)]` and allocates no particle storage of its own (0x55d31c, 0x55a1af, 0x556fa1) |

### `ParticleType` (type; base `Entity`; RegisterMembers 0x55c1d2, constructor 0x55b2bb)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `simulationMode` | `fe3ed166` | integer | 0 | +0x6c | World space:0,Local space:1,Local Instanced:2 | 0 world: particles live in world space; 1 local: in emitter space (world matrix applied at draw, 0x5892c1). The setter stores only 0 or 1 (0x55733e), so "Local Instanced" (2) is not accepted |
| `maxParticles` | `80201462` | integer | 50 | +0xe0 | 0..10000 | ring pool capacity; at most capacity-1 alive, further spawns are dropped (0x55e17b) |
| `particleSpeed` | `d66edb54` | number | 0.0 | +0x80 | 0..10 | m/s; initial velocity = speed x localOrientation(0,1,0) (0x5560c1) |
| `particleLife` | `11a9ce0d` | number | 1.0 | +0x84 | 0..30 | s; initial life = time left (0x5560c1) |
| `particleSize` | `e9a9f60d` | number | 1.0 | +0x78 | 0..30 | m; initial size x = y (0x5560c1) |
| `blendMode` | `13d0f5fb` | integer | 0 | +0xe4 | Normal:0,Additive:1,Subtract:2,Multiply:3,Custom:4 | render states (0x5892c1): Normal srcAlpha/invSrcAlpha add; Additive srcAlpha/one add; Subtract srcAlpha/one subtract; Multiply dstColor/zero add; Custom = the three properties below |
| `srcBlend` | `25c4128d` | integer | 2 | +0x114 | zero:1,one:2,srcColor:3,invSrcColor:4,srcAlpha:5,invSrcAlpha:6,dstAlpha:7,invDestAlpha:8,dstColor:9,invDstColor:10,srcAlphaSat:11 "src blend" | D3DBLEND, used only with blendMode Custom |
| `dstBlend` | `c445e31e` | integer | 2 | +0x118 | zero:1,one:2,srcColor:3,invSrcColor:4,srcAlpha:5,invSrcAlpha:6,dstAlpha:7,invDestAlpha:8,dstColor:9,invDstColor:10,srcAlphaSat:11 "dst blend" | D3DBLEND, used only with blendMode Custom |
| `blendOp` | `6f15d49e` | integer | 1 | +0x11c | add:1,subtract:2,revSubtract:3,max:4,min:5 "blend operator" | D3DBLENDOP, used only with blendMode Custom |
| `particleDepth` | `9d6798a5` | number | 0.0 | +0x7c | 0..30 | m; > 0 selects the soft-particle pixel shader with constant 1/particleDepth (0x5892c1) |
| `texture` | `7d8d9a63` | string | null | +0xf0 |  | texture asset path (`*.bmp`); null string = none |
| `model` | `469e1422` | string | null | +0xf8 |  | model asset path (`*.model`) for renderStyle Model; null in every shipped file |
| `renderStyle` | `27c6198a` | integer | 0 | +0xe8 | Billboard:0,Model:1,Refraction:2 "Appearance" | 0 billboard quads, 1 model instances (0x58d928), 2 refraction quads (normal map distorting the scene copy, uScale/vScale) |
| `alignment` | `d40b108d` | integer | 1 | +0x70 | None:0,Camera:1,Velocity:2,Camera (Stretch last):3,Camera (Stretch first):4 | vertex-shader variant (0x583a62): 0 quad in world axes (identity $camOrient), 1 camera-facing, 2 ALIGN_VELOCITY, 3 ALIGN_RESTRAINCAM, 4 ALIGN_RESTRAINVELOCITY |
| `stretchFactor` | `1536067d` | number | 0.0 | +0xc8 | 0..1.0 | alignment 3: length = max(size.y, 0.01 x stretchFactor x |v perpendicular to the view ray|); alignment 4: length = size.y x max(1, stretchFactor) (0x583a62 + ParticleVS) |
| `startTime` | `6e9442d7` | number | 0.0 | +0xc0 | 0..1.0 | spawners run only while startTime <= fmod(emitter clock, duration) < endTime (0x55a722): compared in seconds, not as a fraction of `duration` (the UI range is 0..1) |
| `endTime` | `be87ea34` | number | 1.0 | +0xc4 | 0..1.0 | see startTime |
| `localPosition` | `f91ab721` | vector | [0.0, 0.0, 0.0] | +0x90 |  | m; emitter-local offset of the spawn point |
| `localOrientation` | `71aa27ca` | quaternion | [0.0, 0.0, 0.0, 1.0] | +0xa0 |  | quaternion xyzw; rotates the emission axis +Y (0x5560c1) and the VarianceInitializer offsets |
| `particleOrientation` | `3c113d26` | quaternion | [0.0, 0.0, 0.0, 1.0] | +0xb0 |  | quaternion; converted to Euler angles (+0x120) = initial particle angles (0x557384, 0x5560c1) |
| `immortalParticles` | `274461e0` | truth | false | +0xec | "Immortal Particles" | use the integrator without life countdown (0x555456) |
| `localMode` | `104f27ff` | truth | false (never stored by the Part 2 build) |  |  | deprecated: setting true sets simulationMode = 1 (0x557481); getter always false; stored only by the Part 1 PC/X360 build |
| `uScale` | `3817470e` | number | 1.0 | +0x88 | "U Scale" | renderStyle 2: x of pixel-shader constant 1 of ParticleRefractionPS (0x5892c1) |
| `vScale` | `fbddf3da` | number | 1.0 | +0x8c | "V Scale" | renderStyle 2: y of the same constant |
| `alphaFalloffEnabled` | `023a32ba` | truth | false | +0x110 | "Enable Falloff" | distance fade: alpha x saturate((viewZ - end) / (start - end)) ($falloff, ParticleVS) |
| `alphaFalloffStart` | `c8a7346c` | number | 0.0 | +0x108 | "Falloff start" | m (view depth at which the fade factor is 1) |
| `alphaFalloffEnd` | `467c6b82` | number | 20.0 | +0x10c | "Falloff end" | m (view depth at which it is 0) |
| `useOcclusion` | `254e4c1e` | truth | false | +0x12c | "Use Occlusion" | darkening inside ParticleOcclusionBox nodes with the same id |
| `occlusionAttenuationLow` | `272ad0e2` | number | 0.9 | +0x130 | "Occlusion low" | clamped to 0..1 by the setter (0x55743e); shader scale 1/(high-low), bias -low/(high-low) |
| `occlusionAttenuationHigh` | `8cd40cf7` | number | 1.0 | +0x134 | "Occlusion High" | clamped to 0..1 (0x557459) |
| `occlusionId` | `9fb76da2` | integer | 1 | +0x138 | "Occlusion ID" | id matched against ParticleOcclusionBox.occlusionId |

### `RegularSpawner` (spawner; base `ParticleSpawner`; RegisterMembers 0x564b2d, constructor 0x564319)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `particlesPerSec` | `95da543e` | number | 10.0 | +0x40 | 0..10000 | count per frame = floor(t x rate) - floor((t - dt) x rate) (0x55f307) |

### `IrregularSpawner` (spawner; base `ParticleSpawner`; RegisterMembers 0x55b6ea, constructor 0x55a945)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `particlesPerSec` | `95da543e` | number | 10.0 | +0x40 | 0..100 | next spawn after 1 / (rate + (2u-1) x variance) s (0x55b804) |
| `variance` | `54fc0fba` | number | 0.0 | +0x44 | 0..100 | see particlesPerSec |

### `BurstSpawner` (spawner; base `ParticleSpawner`; RegisterMembers 0x554166, constructor 0x552ca5)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `minBurstAmount` | `541d54f7` | integer | 10 | +0x40 | 0..100 | per burst int(U(min, max)) particles (0x554342) |
| `maxBurstAmount` | `79446477` | integer | 10 | +0x44 | 0..100 |  |
| `minBurstInterval` | `17eac7a9` | number | 1.0 | +0x48 | 0..100 | s; next burst after U(min, max); first burst at emitter start |
| `maxBurstInterval` | `40e209a0` | number | 1.0 | +0x4c | 0..100 |  |

### `EmitterTrailSpawner` (spawner; base `ParticleSpawner`; RegisterMembers 0x54fd2e, constructor 0x54901a)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `stretchAdjust` | `97f0eae1` | number | 1.0 | +0x40 | 0..100 | motion-trail quad between emitter positions, size.y = max(size, stretchAdjust x displacement / 2) (0x549059) [wp7]; velocity = displacement × 0.001 (0x549059) |

### `EventSpawner` (spawner; base `ParticleSpawner`; RegisterMembers 0x557b50, constructor 0x555d62)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `eventChannel` | `5b3cc55b` | integer | 4 | +0x48 | COLLISION:4,DIE:5,CUSTOM_1:9,CUSTOM_2:10 | particle event listened to: COLLISION 4, DIE 5, CUSTOM_1 9, CUSTOM_2 10 |
| `particleTypeNr` | `0bb2bb7d` | integer | 0 | +0x50 | 0..100 | index of the particle type whose events are listened to (read, 0x559d33); events of the spawner's own type are ignored |
| `minBurstAmount` | `541d54f7` | integer | 10 | +0x40 | 0..100 | particles per event |
| `maxBurstAmount` | `79446477` | integer | 10 | +0x44 | 0..100 |  |
| `inheritedVelocity` | `9c9b29c3` | number | 0.0 | +0x454 | 0..100 | 0..1 (setter clamps, 0x556f57): new velocity = blend of own and source velocity by this factor (0x4af4f7, not re-read) |

### `SurfaceSpawner` (spawner; base `ParticleSpawner`; RegisterMembers 0x55384e, constructor 0x552a85)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `particleAmount` | `65f64da9` | number | 0.1 | +0x50 | 0..100 "Particles/m2" | particles per m2 of emitter surface: budget = trunc(particleAmount × the summed `area_weight` of the collected triangles), 0x553c41 (model node surface lists, FORMATS_MISC.md "Particle emission surfaces") |
| `radius` | `29e0c05b` | number | 100.0 | +0x54 | 0..100 "radius" | m; nodes within this radius are queried |
| `speed` | `78a2e46d` | number | 0.0 | +0x58 | 0..100 "speed" | m/s |
| `lifeVariance` | `5667c2dd` | number | 0.0 | +0x5c | 0..100 "Life Variance" | s |
| `faceCullLimit` | `c9a564f1` | number | 0.0 | +0x60 | -1..1 "Face Cull" | -1..1; a triangle is used when its world normal Y >= this |
| `spawnOnCharacters` | `d59b6b73` | truth | false | +0x64 | "Use Characters" | use character bone surfaces |
| `spawnOnGeometry` | `72a9efa9` | truth | true | +0x65 | "Use Geometry" | use model node surfaces |
| `materialId` | `6cacf5e4` | integer | -1 | +0x68 | "Material ID" | triangle material id filter; negative = any |

### `TerrainSurfaceSpawner` (spawner; base `ParticleSpawner`; RegisterMembers 0x553e77, constructor 0x552b43)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `particleAmount` | `65f64da9` | number | 10.0 | +0x40 | 0..100 "Spawn amount" | "Spawn amount": count = trunc((2 × radius)² × `particleAmount` / 1000) (0x54944b); point = emitter + radius × (U(−1, 1), 0, U(−1, 1)) dropped on the terrain; position = point + `spawnOffset` × normal; velocity = `speed` × normal; lifetime = type lifetime × (1 − U(0, `lifeVariance`)) (0x5491c5) |
| `radius` | `29e0c05b` | number | 10.0 | +0x44 | 0..100 "radius" | m |
| `speed` | `78a2e46d` | number | 0.0 | +0x48 | 0..100 "speed" |  |
| `lifeVariance` | `5667c2dd` | number | 0.0 | +0x4c | 0..100 "Life Variance" |  |
| `spawnOffset` | `3b9fa7d7` | number | 0.0 | +0x50 | 0..100 "Spawn Offset" |  |

### `VarianceInitializer` (initializer; base `ParticleInitializer`; RegisterMembers 0x5501a8, constructor 0x5495ce)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `position` | `15de4806` | vector | [0.0, 0.0, 0.0] | +0x60 |  | m per axis: pos += localOrientation x (U(-1,1) x position) |
| `orientation` | `c97cd687` | vector | [0.0, 0.0, 0.0] | +0x50 |  | degrees per axis: particle angles += U(-1,1) x orientation |
| `rotation` | `6bb581d1` | vector | [0.0, 0.0, 0.0] | +0x40 |  | degrees/s per axis: angular rate += U(-1,1) x rotation |
| `sizeVariance` | `b0e03356` | number | 0.0 | +0x70 | 0..10 | m: size x and y += U(-1,1) x sizeVariance (one draw) |
| `alpha` | `5284c902` | number | 0.0 | +0x80 | 0..10 | alpha = 1 - U(0,1) x alpha |
| `life` | `329262a2` | number | 0.0 | +0x78 | 0..10 | s: life += U(-1,1) x life (time left is set to life afterwards, 0x55f512) |
| `speed` | `78a2e46d` | number | 0.0 | +0x74 | 0..10 "Speed Variance (pct)" | percent: speed += speed/100 x U(-1,1) x speed0 |
| `spread` | `8c583d7d` | number | 0.0 | +0x7c | 0..10 "Spread (degrees)" | degrees: the emission axis is tilted by U(-1,1) x spread about X and about Z |
| `useLocalOrientation` | `93c34ca8` | truth | false | +0x84 | "use localorientation" | world mode with an emitter: also rotate by the type localOrientation (else only by the emitter orientation) |

### `ColorRangeInitializer` (initializer; base `ParticleInitializer`; RegisterMembers 0x5519f0, constructor 0x54d28e)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `colorSequence` | `0b3dfb5e` | string | "" | +0x68 | "start color" | gradient; particle rgb = gradient at a random t [wp7] |

### `UVArrayInitializer` (initializer; base `ParticleInitializer`; RegisterMembers 0x5576aa, constructor 0x5559a9)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `numX` | `72aab21a` | integer | 1 | +0x40 | 0..10000 | atlas columns; a random cell is chosen [wp7] |
| `numY` | `72aab29a` | integer | 1 | +0x44 | 0..10000 | atlas rows |

### `PositionInitializer` (initializer; base `ParticleInitializer`; RegisterMembers 0x5571d5, constructor not read)

No properties of its own.


### `LinearForceAffector` (affector; base `ParticleAffector`; RegisterMembers 0x55793f, constructor 0x555b32)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `force` | `576d3f5b` | vector | [0.0, 0.0, 0.0] | +0x40 |  | m/s2: v += dt x force |

### `DampeningAffector` (affector; base `ParticleAffector`; RegisterMembers 0x557a99, constructor 0x555c2f)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `damp` | `2282b20a` | number | 0.0 | +0x40 |  | 1/s: v -= damp x dt x v (only when damp > 0) |

### `GrowthAffector` (affector; base `ParticleAffector`; RegisterMembers 0x564c7a, constructor 0x56433e)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `growth` | `aa7d904e` | number | 0.0 | +0x40 | -10..10 | m/s: size x and y += growth x dt |

### `RotateAffector` (affector; base `ParticleAffector`; RegisterMembers 0x5577c4, constructor 0x555a8d)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `rotationx` | `326fdcec` | number | 0.0 | +0x40 | -360..360 "X deg/sec" | deg/s added to the particle angles [wp7]; plain store; added per second to the same fields VarianceInitializer fills in radians (inferred: acts as rad/s) |
| `rotationy` | `326fdc6c` | number | 0.0 | +0x44 | -360..360 "Y deg/sec" |  |
| `rotationz` | `326fdcac` | number | 0.0 | +0x48 | -360..360 "Z deg/sec" |  |

### `TraceAffector` (affector; base `ParticleAffector`; RegisterMembers 0x564dc7, constructor 0x56435b)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `stretchRatio` | `3db29a98` | number | 1.0 | +0x40 | -10..10 | size.y += ratio x speed x dt [wp7] |

### `SizeSequenceAffector` (affector; base `ParticleAffector`; RegisterMembers 0x564f30, constructor 0x564378)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `sizeOverTime` | `41073a8b` | string | "" | +0x6c |  | gradient (first channel); size x = y = factor x curve(t) |
| `factor` | `63b3edaf` | number | 1.0 | +0x40 | 1..10 | m |

### `OpacitySequenceAffector` (affector; base `ParticleAffector`; RegisterMembers 0x5585ae, constructor 0x5579f6)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `colorSequence` | `0b3dfb5e` | string | "" | +0x68 | "Opacity over time" | gradient (first channel); alpha = curve(clamp01(t)) |

### `ColorSequenceAffector` (affector; base `ParticleAffector`; RegisterMembers 0x551939, constructor 0x54ffc1)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `colorSequence` | `0b3dfb5e` | string | "" | +0x68 | "Color over time" | gradient; rgb = gradient(t), alpha kept [wp7] |

### `IlluminationAffector` (affector; base `ParticleAffector`; RegisterMembers 0x56504a, constructor 0x5643e0)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `ambient` | `52cdc81f` | truth | true | +0xac | "Receive ambient" | "Receive ambient" |
| `selfIllumination` | `c701fdf3` | string | "" | +0x68 |  | gradient -> particle illumination rgb (+0x60) [wp7] |
| `bloomFactor` | `875ff4fc` | number | 1.0 | +0xa8 | 0..1 | 0..1; $bloomfactor of the bloom pass (0x5892c1 reads it through type+0x74) |
| `bloomSequence` | `7dadce0c` | string | "" | +0x9c |  | gradient -> packed bloom colour (+0x78) [wp7] |

### `UVArrayAffector` (affector; base `ParticleAffector`; RegisterMembers 0x565445, constructor 0x5644bc)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `frameRate` | `4c125b83` | number | 10.0 | +0x40 | "Frame Rate" | frames/s of the flip-book: f = trunc(timeLeft × frameRate) — time left, not age; forward mode frame = n − (f mod n), reverse mode frame = f, n = numX × numY |
| `numX` | `72aab21a` | integer | 1 | +0x44 | "columns" | columns (setter clamps to >= 1 and stores 1/numX, 0x560b74) |
| `numY` | `72aab29a` | integer | 1 | +0x48 | "rows" | rows |
| `animationMode` | `0b83bb56` | integer | 0 | +0x4c | Forward:0,reverse:1 | 0 Forward, 1 reverse |
| `randomize` | `2e39ca34` | truth | not set by the constructor | +0x50 | "Randomize" | random start frame; constructor leaves the byte unset |

### `GeometryCollisionAffector` (affector; base `ParticleAffector`; RegisterMembers 0x54f8a8, constructor 0x548c7d)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `radius` | `29e0c05b` | number | 0.1 | +0x40 | 0..10 | m; the ray is extended by radius; resting distance = radius - 0.025 |
| `elasticity` | `8095e2e0` | number | 0.8 | +0x44 | 0..10 | v = lerp(tangential part of the damped reflection, reflection, elasticity) |
| `friction` | `b00a668a` | number | 0.0 | +0x48 | 0..10 | 1/s: reflected velocity x (1 - friction x dt) |
| `collisionMask` | `4d16aa4d` | integer | 0 | +0x4c | COLLISION_TYPES | COLLISION_TYPES flags of the line check (0x50a384) |
| `alignToCollisionNormal` | `0dfe6bd4` | truth | false | +0x50 | "Align to Normal" | velocity = |v| x elasticity x normal and the particle angles are set to face the normal |
| `safetyRadius` | `7f7c63b1` | number | 0.5 | +0x54 | "Safety Radius" | m; > 0: three more line checks around the hit point must find the same normal, else no collision this frame |
| `dieOnImpact` | `e6bd6733` | truth | false | +0x58 | "Die on impact" | time left = 0 on impact |

### `PlaneCollisionAffector` (affector; base `ParticleAffector`; RegisterMembers 0x55aa4f, constructor 0x55943b)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `radius` | `29e0c05b` | number | 0.5 | +0x40 | 0..10 |  |
| `elasticity` | `8095e2e0` | number | 0.8 | +0x44 | 0..10 |  |
| `nodeRef` | `3324885c` | string | "" | +0x5c |  |  |

### `TerrainCollisionAffector` (affector; base `ParticleAffector`; RegisterMembers 0x55b96a, constructor 0x55abca)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `radius` | `29e0c05b` | number | 0.5 | +0x40 | 0..10 |  |
| `elasticity` | `8095e2e0` | number | 0.8 | +0x44 | 0..10 |  |
| `nodeRef` | `3324885c` | string | "" | +0x5c |  |  |

### `EventGeneratorAffector` (affector; base `ParticleAffector`; RegisterMembers 0x54fde5, constructor 0x54948f)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `eventChannel` | `5b3cc55b` | integer | 9 | +0x40 | CUSTOM_1:9,CUSTOM_2:10 | CUSTOM_1 9 / CUSTOM_2 10 event raised per particle: when `interval` < timer: every live particle with normalised age 1 − timeLeft / lifetime in [`startTime`, `endTime`] raises the event and the timer is set to 0; then timer += dt (0x5494bf) |
| `interval` | `06331c10` | number | not set by the constructor | +0x44 | 0..10 | s; constructor leaves it unset |
| `startTime` | `6e9442d7` | number | 0.0 | +0x4c | 0..1 |  |
| `endTime` | `be87ea34` | number | 1.0 | +0x50 | 0..1 |  |

### `ProximityNoise` (affector; base `ParticleAffector`; RegisterMembers 0x5544d8, constructor 0x552d20)

| Property | Hash | Type | Default | Offset | UI range / items | Meaning |
|---|---|---|---|---|---|---|
| `spawnDistance` | `8341c49b` | number | 10.0 | +0x4c | 0..100 |  |
| `fadeDistance` | `5f615d5b` | number | 5.0 | +0x50 | 0..100 |  |
| `particleDensity` | `83d3acfb` | number | 500.0 | +0x54 | 0..100 |  |
| `jitter` | `f750cbea` | number | 0.0 | +0x7c | 0..100 |  |
| `scroll` | `f78af04c` | vector | [0.0, 0.0, 0.0] | +0x6c |  |  |
| `followCamera` | `6e978e91` | truth | false | +0x58 |  |  |
| `useTerrainLayer` | `6de4cc28` | truth | true | +0x59 |  |  |
| `spawnHeight` | `755405bc` | number | 2.0 | +0x48 | 0..100 |  |
| `terrainOffset` | `3cf5fa7f` | number | 0.0 | +0x84 | 0..100 |  |

## 4. Enums and gradients [R]

Dropdown items are in the property registration strings (0x55c1d2 and the module registrations):

| Property | Items |
|---|---|
| `simulationMode` | World space 0, Local space 1, Local Instanced 2 (the setter rejects 2) |
| `blendMode` | Normal 0, Additive 1, Subtract 2, Multiply 3, Custom 4 |
| `srcBlend`, `dstBlend` | zero 1, one 2, srcColor 3, invSrcColor 4, srcAlpha 5, invSrcAlpha 6, dstAlpha 7, invDestAlpha 8, dstColor 9, invDstColor 10, srcAlphaSat 11 (D3DBLEND) |
| `blendOp` | add 1, subtract 2, revSubtract 3, max 4, min 5 (D3DBLENDOP) |
| `renderStyle` | Billboard 0, Model 1, Refraction 2 |
| `alignment` | None 0, Camera 1, Velocity 2, Camera (Stretch last) 3, Camera (Stretch first) 4 |
| `animationMode` (UVArrayAffector) | Forward 0, reverse 1 |
| `eventChannel` | EventSpawner: COLLISION 4, DIE 5, CUSTOM_1 9, CUSTOM_2 10; EventGeneratorAffector: CUSTOM_1 9, CUSTOM_2 10 (values of `PARTICLESYSTEMEVENT`) |
| `collisionMask` | flags `COLLISION_TYPES` (0x8bbc25): RAGDOLL 1, CHARACTER_PHYSICS 2, CAMERA 4, CLOTH 8, TRIGGER 0x10, SOLID 0x20, BLOCKER_RORSCHACH 0x40, BLOCKER_NITEOWL 0x80, BLOCKER_ENEMY 0x100, MOVEMENT_STOPPER 0x200, RAGDOLL_ALLY 0x400, BLOCKER_UNDERBOSS 0x800, WATER 0x1000, KYNAPSE 0x2000, WAYPOINT 0x4000, PARTICLES 0x8000 |

These live in `particle_asset.ENUMS` / `COLLISION_TYPES`; `engine_enums.json` is not changed
(`COLLISION_TYPES` and `PARTICLESYSTEMEVENT` are candidates for it; both are registered families).

**Gradients** (`colorSequence`, `sizeOverTime`, `selfIllumination`, `bloomSequence`) are strings
`t,r,g,b,a|t,r,g,b,a|...` written with `"%f,%f,%f,%f,%f|"` (0x4124a3). Reader 0x413360: split at
`|`, then at `,`, `atof`; `t` is stored as an integer number of milliseconds (`t x 1000`, truncated);
a key is `{int ms, float first channel, r, g, b, a}` (0x18 bytes). Evaluation (0x4116b3, 0x411783,
0x411883): before the first key the first key, after the last key the last key, between two keys
linear; one key is a constant; no key gives white (1, 1, 1, 1) / brightness 1. "Brightness"
gradients (`sizeOverTime`, opacity) use the first channel. `t` is the particle's normalised age
`1 - timeLeft / life`. The constructors install default keys that a stored string replaces:
ColorSequence / ColorRange `0: (1,1,0,1)`, `1: (1,0,0,1)`; OpacitySequence `0: 1`, `1: 0`;
Illumination `selfIllumination 0: (0,0,0,1)`, `bloomSequence 0: (1,1,1,1)`; SizeSequence none.

**References**: `ParticleType.texture` (`*.bmp`, resource at +0xf0) and `ParticleType.model`
(`*.model`, +0xf8) are asset paths as stored in the archive (`/Art/Effects/.../x.bmp`); a null
string means none. `PlaneCollisionAffector.nodeRef` / `TerrainCollisionAffector.nodeRef` name a
scene node (classes unused). There is no sound reference in a `.particle`; sounds are attached by
the script classes (`GFXParticleEffectType.m_eparticlesoundreference`).

## 5. What the simulation does with the parameters [R unless marked]

- **Particle** (128 bytes): position +0x00, velocity +0x10, angles +0x20, angular rate +0x30,
  time left +0x40, life +0x44, fade +0x48, rgb +0x50, alpha +0x5c, illumination +0x60, size x / y
  +0x70 / +0x74, bloom colour +0x78, uv cell +0x7c [wp7 for the last three].
- **Pool** (per type and emitter set): `maxParticles` slots, alive flags, first-alive index +0x44,
  allocation cursor +0x48. Allocation 0x55e17b takes the slot at the cursor and advances it modulo
  the capacity; it **fails when the next index equals the first-alive index**, so at most
  `maxParticles - 1` are alive and a full pool drops new particles (nothing is overwritten). After
  the frame 0x55e07b advances the first-alive index over dead slots up to the cursor. The update
  runs over `[first, cursor)`, in two pieces when wrapped (0x55a722).
- **Frame** (0x55b16f): emitter clocks += dt (0x55b104; a non-looping emitter whose clock exceeds
  `duration` is reset, deactivated and raises EMITTERSTOP 3); per type (0x55a722), for each active
  emitter with `startTime <= fmod(clock, duration) < endTime` (seconds) run the spawners; then
  integrate and run the affectors in file order (0x55a643); then update events if enabled.
- **Spawning** (`ParticleSpawner::vfunc_15` 0x55f512): the spawner returns a count (vfunc 19);
  per particle: allocate, default state (0x5560c1: colour white, fade 1, size = `particleSize`,
  angles = Euler of `particleOrientation`, velocity = `particleSpeed` x `localOrientation` applied to
  **+Y (0, 1, 0)** - constant 0x9e807c; wp7 said Z - life = time left = `particleLife`), position
  (0x5563a3, interpolated along the emitter's motion by `i / count`: particle i of n uses t = i / n;
  world-simulated type: orientation = slerp(current, previous, t), base = lerp(current position,
  previous position − dt × initial velocity, t); local type: base 0 and the type's own
  orientation; position = base + rotated type offset (+0x90); velocity = type speed (+0x80) ×
  rotated (0, 1, 0)), the spawner's
  own hook (vfunc 20), the initializers in file order (0x559211), then `timeLeft = life`, then the
  spawn event if enabled.
- **Integrator** (0x55a503): `pos += dt x vel`, `angles += dt x rate`, `timeLeft -= dt`; `<= 0`
  clears the alive flag (and raises PARTICLEDIE if enabled). `immortalParticles` uses 0x555456.
- **Random numbers** (0x54833c): 32-bit LCG `s = s x 0x19660d + 0x3c6ef35f`, value `s x 2^-32`;
  `U(a, b)` = `a + (b - a) x value` (0x54836d). Seeds: low dword of QueryPerformanceCounter (0x405d53), per instance or per function; not reproducible.
- **VarianceInitializer** (0x54964e; closes the wp7 item): `angles += U(-1,1) x orientation` and
  `rate += U(-1,1) x rotation` per axis (both converted from degrees by the setters, 0x54d70e /
  0x54d760, factor at 0xc8cdb0 = pi/180); speed `s = s0 + speed/100 x U(-1,1) x s0` with `s0 = |v|`
  (0x5484e5, divisor 100.0 at 0x9e5bd0); direction: spread = conj(q)·(0, s, 0)·q with q = qx(a)⊗qz(c), a and c = U(−1,1) × spread
  (radians): X first, then Z; direction = s × (cos a·sin c, cos a·cos c, −sin a), then the type
  orientation — by the
  type's `localOrientation` when there is no emitter or `simulationMode != 0`, otherwise by the
  emitter orientation (emitter +0x58) and, only if `useLocalOrientation`, by `localOrientation`
  too; `life += U(-1,1) x life`; `size.x` and `size.y` `+= U(-1,1) x sizeVariance` (one draw for
  both); `alpha = 1 - U(0,1) x alpha`; `pos += R x (U(-1,1) x position)` per axis, R = the type's
  `localOrientation` (and the emitter orientation in world mode).
- **GeometryCollisionAffector** (0x54bfab; closes the wp7 item): per live particle that moves this
  frame, a line check (0x50a384, mask `collisionMask`) from `pos` to `pos + dt x vel + radius x dir`.
  On a hit with `safetyRadius > 0` three more line checks, offset by `safetyRadius` along the two
  surface tangents and spanning +-`safetyRadius` along the travel direction, must each hit a surface
  with the same normal (squared difference <= 1e-5, 0xa37150); otherwise the hit is ignored this
  frame. Response: `pos = hit + (radius - 0.025) x n`; without `alignToCollisionNormal`:
  `r = v - 2 (v.n) n`, `d = r x (1 - friction x dt)`, `v = T + elasticity x (r - T)` with T the
  tangential part of d; with it: `v = |v| x elasticity x n` and the particle angles are set to the
  rotation taking +Y to n; `dieOnImpact` sets time left to 0; if `|v|^2 > 0.01` the event
  PARTICLECOLLIDE (4) is raised for the particle (this is what `EventSpawner` listens to).
- Other affector bodies: LinearForce `v += dt x force` (0x555b81); Dampening `v -= damp x dt x v`
  when `damp > 0` (0x555c4c); Growth `size += growth x dt` (0x55f332); SizeSequence
  `size.x = size.y = factor x curve(t)` (0x55f3fe, replaces `particleSize`); OpacitySequence
  `alpha = curve(clamp01(t))` (0x5552d3); the rest as in wp7 section 2.2.
- **PositionInitializer** (0x5553d0): `pos += U(-1,1)` per axis (a 2 m cube). Not used in data.
- **Emitter auto-delete** (closes the wp7 item): `ParticleSystemSlot.CreateEmitter(vector,
  quaternion, entity, truth)` 0x55d059 stores the truth at emitter +0x14; the per-frame sweep
  0x55c16c deletes every emitter with +0x14 set whose active flag (+0x68) is clear. Emitter fields:
  clock +0x00, position +0x04, orientation +0x18, auto-delete +0x14, loop +0x15 (copied from the
  asset), active +0x68, parent entity +0x6c.
- **Rendering**, draw 0x5892c1 and vertex-shader choice 0x583a62 (closes the wp7 item):
  - blend states by `blendMode`: Normal `srcAlpha, invSrcAlpha, add`; Additive `srcAlpha, one, add`;
    Subtract `srcAlpha, one, subtract`; Multiply `dstColor, zero, add`; Custom `srcBlend, dstBlend,
    blendOp`. So `srcBlend` / `dstBlend` / `blendOp` matter only for Custom.
  - `particleDepth > 0` (and soft particles enabled) selects the soft pixel shader with `1 /
    particleDepth`; `alphaFalloffEnabled` sets `$falloff = (end, start - end)` and the vertex shader
    multiplies alpha by `saturate((viewZ - end) / (start - end))`; occlusion sets scale
    `1 / (high - low)` and bias `-low x scale`; `simulationMode` 1 sets the world matrix from the
    emitter (identity otherwise).
  - `alignment` -> `ParticleVS` variant (defines from `re/vcolor_shaders.json`, maths from the
    disassembled shader bytecode). In every variant the quad corner is scaled by
    `(size.x, size.y)` and rotated by the particle's three Euler angles, then mapped onto three
    world axes:
    - 0 None: no define, `$camOrient` = identity -> the quad lies in world axes, oriented only by
      the particle angles;
    - 1 Camera: no define, `$camOrient` = the camera's basis (camera +0x58..+0x80) -> camera-facing
      billboard, the angles spin it in the view plane;
    - 2 Velocity: `ALIGN_VELOCITY` - axes = velocity direction d, `normalize(cross(up', d))` with
      up' = (0.001, 1, 0.001), and their cross product; no camera term;
    - 3 Camera (Stretch last): `ALIGN_RESTRAINCAM`, `$camPos`, `$stretchFactor = 0.01 x
      stretchFactor` - faces the view ray e, long axis = the velocity projected into the view
      plane, `size.y = max(size.y, 0.01 x stretchFactor x |v x e|)`;
    - 4 Camera (Stretch first): `ALIGN_RESTRAINVELOCITY`, `$camPos`, `$stretchFactor =
      stretchFactor` - long axis = the velocity direction, turned about it towards the camera,
      `size.y = size.y x max(1, stretchFactor)`.

## 6. JSON (`particle_asset.parse` / the extractor's `<name>.particle.json`)

```
format         "kapow-particle/2"
byte_order     "little" | "big"
record_layout  "typed" | "untyped"            (section 2)
evidence       one line
system         object(ParticleSystemAsset)
types          [ object(ParticleType) + "affectors": [object], "spawners": [object],
                                         "initializers": [object] ]
summary        {types, objects, classes{name: n}, unknown_classes[], unknown_properties[],
                ignored_records, trailing_bytes}
trailing       hex, only when bytes follow the tree

object  {class, base, id (hex objectId), props[], absent{}?, unknown_class?, warn?}
props   records in file order: {name, type, value} and, when they apply,
          enum      dropdown item name (null when the value is not an item)
          flags     names of the set bits (collisionMask)
          keys      [[t, r, g, b, a], ...] of a gradient string
          default   true: the value equals the constructor default
          hash, unknown   a record the class does not register - kept, never dropped
          name_guess      (unknown class only) the hash dictionary's name for the hash
          ignored   "type-mismatch (...)" / "size-mismatch (...)" / "id-change": not applied
          id        the record's own objectId when it differs from the object's
          raw       payload hex when value does not re-encode to exactly these bytes
absent  {name: constructor value} of registered, normally stored properties with no record
```

Value forms: number = float (shortest decimal of the float32), integer = int, truth = bool,
vector = [x, y, z], quaternion = [x, y, z, w], string = str or null (null string), color = hex.
`particle_asset.values(obj)` gives the effective `{name: value}` (records over defaults, with the two
non-trivial `ParticleType` setters applied: `simulationMode` accepts only 0 / 1, `localMode = true`
means `simulationMode = 1`). `particle_asset.build(tree)` writes the bytes back (byte-exact for
every file of the seven extracts). `absent` uses the Part 2 constructors also for Part 1 files.
Truncated or malformed input raises `particle_asset.ParticleError` (a `ValueError`).

## 6a. `watchmen particlemeta`: all files plus an index

```
watchmen particlemeta EXTRACT_OUT OUT_DIR [TEXTURES_DIR]
```

`EXTRACT_OUT` is an `extract` output (only its `extracted/` folder is walked), any other folder
that holds `.particle` files, or a single file. Files are taken in the order of their path (lower
case first), whatever order the file system lists them in. The extract is not changed.

```
OUT_DIR/<asset path>.particle.json    the tree of section 6 ("kapow-particle/2"), byte for byte the
                                      file `extract` writes beside the asset
OUT_DIR/index.json                    format "watchmen-particle-meta/1"
```

`index.json` (`particle_meta.build` / `write`):

```
format           "watchmen-particle-meta/1"
particle_format  "kapow-particle/2"
evidence         {topic: one line}
texture_tree     name of the folder textures were looked up in, null when there is none
counts           {files, parsed, failed, roundtrip_exact, types, objects, looping,
                  byte_order{}, record_layout{}, unknown_classes, unknown_properties,
                  ignored_records, textures, textures_found, models, models_found}
classes          {class name: objects of that class in all files}
files            [ file row ]              in path order
textures         {texture string: {found, dir, images[], used_by[], stored_name[]}}
models           {model string: {found, file, used_by[], stored_name[]}}
errors           [{file, error}]           files that are not a complete tree

file row   {file (path below the walked folder), asset ("/" + file), json, bytes, parsed,
            byte_order, record_layout, roundtrip (build(parse(x)) == x),
            emit_duration_s, loop           ParticleSystemAsset.duration / loop
            types, objects, classes{}, unknown_classes, unknown_properties, ignored_records,
            trailing_bytes                  the `summary` of section 6
            particle_life_s_max             longest particleLife of its types
            max_particles_total             sum of maxParticles (pool capacities)
            textures[], models[]            the distinct strings its types name
            type_list[]}
type row   {index, name, texture, model (null: none),
            render_style, blend_mode, alignment, simulation_mode    the dropdown item name
                                            (section 4); the number when it is not an item
            max_particles, particle_life_s, particle_size_m, start_time_s, end_time_s,
            affectors[], spawners[], initializers[]    class names in file order
            uv_grid {x, y, from}?}          numX / numY of the first UVArrayInitializer /
                                            UVArrayAffector of the type, when it has one
a file that does not parse: {file, asset, json, bytes, parsed: false, error}
```

- Every value is `particle_asset.values(...)` of the object (records over constructor defaults,
  section 6); the index adds no fact of its own. For Part 1 PC / X360 files the defaults are the
  Part 2 constructors' (section 8).
- `asset` is the path of the file below `extracted/` as the extractor wrote it. The strings other
  assets use for the same file can differ from it in case (`/Art/...` against `art/...`).
- **Textures** are looked up by the asset path of the string (`/Art/Effects/x.bmp` ->
  `<tree>/art/effects/x.bmp/`, each component as written or, failing that, in any case) in
  `TEXTURES_DIR` when given, else `EXTRACT_OUT/textures`. `dir` is the texture's folder relative to
  that tree and `images` its `.png` files. There is no lookup by bare name: a texture that is not
  at its path is `found: false`. Which layer of a texture the particle shader samples is not part
  of the index. **Models** are looked up the same way under the walked folder; no shipped file
  names one.
- **Spelling of the strings** (`--names canonical`, the default; `evidence.names`). A texture or
  model string of the index — the keys of `textures` / `models`, `textures[]` / `models[]` of a
  file row, `texture` / `model` of a type row — is spelled as the folder or file it names is
  written: it is `"/" + dir` (or `"/" + file`) of its entry, so it finds the folder on a
  case-sensitive file system. A string that names nothing in the tree has the spelling of
  `wlib/canonical_names.json`. Where the files store another spelling, the entry lists the
  spellings in `stored_name`, and a file row and a type row keep their own strings under
  `stored` (`{"textures": [...]}`, `{"texture": "..."}`). The per-file JSON is the file and keeps
  the stored string. `asset_names` at the end of the index is `{spelling: "export", respelled,
  note}` as in the other tables; `respelled` counts the strings written in another spelling
  than the files store: each `texture` / `model` of a type row, each string of a file row's
  `textures` / `models` list and each key that has a `stored_name` (383 on PC and PS3 Part 2,
  386 on Xbox 360 Part 2, 486 on each Part 1 set, measured on the six-set export).
  `--names stored`: every string as the file stores it, no `stored_name`,
  no `stored`, no `asset_names`. Measured on the files of PC Part 2 and PS3 Part 1 (2026-10-07): 49 of 56 and 56
  of 66 texture strings are stored in another letter case than their folder has (`/Art/Effects/`
  against `art/Effects/`), 176 of 208 and 229 of 286 type rows; spelled as written, every
  string names its folder exactly.
- A file that is not a complete tree still gets its JSON (the generic block walk with a `warn`, as
  `extract` writes it), a row with `parsed: false` and an entry in `errors`; the command then exits
  with status 1. Without any `.particle` it writes nothing and exits with status 1.
- On real data (2026-10-04, Part 2 PC extract): 89 files, 89 parsed and rebuilt byte-exact, 208
  types, 1,464 objects, 51 looping systems, 56 distinct textures, all 56 found (in the tree
  extracted with 1.4.0 and in the older one), no model string, 71 types with a UV grid. The 89
  JSON files are byte-identical to those written by calling `particle_asset.to_json` per file.
  Six-set export of 2026-10-05 (measured, the six `particlemeta` logs): 89 files, 208 types, 1,464
  objects, 56 of 56 textures on each Part 2 set (PC, Xbox 360, PS3); 130 files, 286 types, 2,052
  objects, 66 of 66 textures on each Part 1 set; every file parsed and rebuilt byte-exact.

## 7. What changed in `<name>.particle.json`

Up to 1.3.0 the file was the flat `blocks` list of the generic property-bag walk
(`kapow_props.parse`), without a `format` key:

```json
{"blocks": [{"class": "ParticleType", "pre": [1], "owner": "d23b8f41", "schema": 197,
             "props": [{"key": "Texture", "type": "string", "value": "/Art/..."},
                       {"key": "329262a2", "type": "number", "value": 0.0}]}],
 "trailing_bytes": 0}
```

- The flat list is now the tree `system` -> `types[]` -> `affectors[] / spawners[] /
  initializers[]`. `pre` was the list counts, `owner` is `id`, `schema` was the payload length in
  dwords.
- Record key `key` -> `name`, in the engine's spelling: `texture`, `duration`, `position`, `speed`,
  `force`, `ambient`, `factor` (were capitalised), `open`, `life`, `numX`, `numY`, `damp` (were
  hex).
- Values: `truth` is a JSON boolean (was 0 / 1); `number` is the shortest decimal that packs to the
  same float32 (0.01, was 0.009999999776482582); a null string is `null` (was `""`); `vector` /
  `quaternion` are plain lists (were `{"raw_type", "floats", "hex"}`).
- A file that is not a complete tree still gets the old `blocks` output plus a `warn` line. No
  shipped file is one.
- `.grass`, `.detailmesh`, `.pb`, `.terrain` JSON are still written by the generic walk; the five
  names added to `kapow_props.namedict()` (`life`, `numX`, `numY`, `damp`, `open`) now resolve
  there too. `wlib/prop_hash_dict.pkl` spells the seven names above in lower case as well since
  2026-10-05: every class that registers them does so in lower case (`.grass` included), and the
  capitalised forms were editor captions. The `.particle.json` files are byte-identical with
  either dictionary (49 staged files compared).
- `fx_meta.particle_facts` (the `fx.particles` table of `anim_meta.json`) reads the files through
  this parser and falls back to the generic walk; on the 49 Part 2 PC files checked the two give
  the same facts.

## 8. Not established

- The untyped Part 1 PC / X360 record layout is read from data only (no Part 1 executable). The
  older build stores every registered property except `simulationMode`, `renderInstanced`,
  `numVariations`, which it lacks (it has `localMode`); all other values equal the PS3 Part 1
  copy except `alwaysUpdate` in 46 files (measured, 130 files per set). `absent` on those files
  therefore lists exactly these three.
- The writer (Entity vfunc 7, 0x5016d8) skips a property when it is `script`, has no setter
  (record +0x20 == 0), has flag bit 0 or bit 1 of record +0x38, or is `assetName` on an entity
  whose native class is SceneNode. The properties carrying bit 0 (never written) and bit 1
  (deprecated alias) are listed in `wlib/property_store_flags.json`.
- Not read: `SurfaceSpawner` triangle walk (0x54decc / 0x54e23e), `ProximityNoise`,
  `PlaneCollision` / `TerrainCollision` (the last three are in no file of the sets counted).
  `EventSpawner`, `UVArrayAffector` and the `RotateAffector` body are read.
- Use of the less common classes, measured on pc_p2, pc_p1, x360_p2, ps3_p1:

  | Class | Part 2 files (of 89) | Part 1 files (of 130) |
  |---|---|---|
  | `IlluminationAffector` | 56 | 72 |
  | `EmitterTrailSpawner` | 1 | 1 |
  | `EventGeneratorAffector` | 0 | 2 (`lightning_02`, `BloodSplatter_Ground_01`) |
  | `SurfaceSpawner` | 0 | 1 (`rain_surfacesplash`) |
  | `TerrainSurfaceSpawner` | 0 | 1 (`rain_terrainsplash`) |
  | `TraceAffector`, `ProximityNoise`, `PlaneCollisionAffector`, `TerrainCollisionAffector` | 0 | 0 |
- Constructor defaults the constructor does not set: `EventGeneratorAffector.interval`,
  `UVArrayAffector.randomize`. The files always store them.
- Model particles (`renderStyle` 1; no data uses it), the
  pixel shaders (soft-particle depth fade, refraction, bloom), the Euler convention of the particle
  angles in `ParticleVS`.
- PS3 Part 1 has 20 more local-space types than PC Part 1 (72 against 52) because four files
  (`prisonhallwaysmoke_02`, `openfire_01`, `openfire_02`, `openfire_outdoor_01`) are
  render-instanced there (`numVariations` 5 / 5 / 5 / 3) and all their types simulate locally
  (measured; that instancing forces local simulation is inferred from the 20 of 20
  co-occurrence).
