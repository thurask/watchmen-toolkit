# WP1 — How a frame is rendered (Kapow / Watchmen Part 2 PC), and what it means for the exporter

Evidence tags: **[code]** read from the decompilation / disassembly of `KapowMultiDEDRM.exe` (function
address given), **[bytecode]** read from the SM3 listings in `work/vcolor/dis`, **[capture]** measured on
`apitrace_dump.txt` (410 frames, 1920x1080, D3D9), **[data]** measured on the extracted Part 2 PC files,
**[inferred]**, **[NE]** not established.

Tables: `findings/wp1_renderer.json`. Scratch and tools: `work/wp1/` (`rtti.py` vtable/RTTI reader,
`props.py` property-registration → member offset, `xref.py`, `bf.c` define-set search, `rf.sh`).
On the PC (scratch, outside `mnt/`): `~/scratch/wp1/c.txt.gz` (compacted UTF-8 copy of the dump),
`summ.py` (frame → pass / target / shader / state summary), `ev.py` (constants of one pass).

**Limit of the ground truth.** The capture is the **main menu** (camera `Cam_001`, Rorschach and Nite Owl
posing in a lit room), not a combat level. It contains no Dominatrix. Pass order, targets, states and the
character path are the same code (one `DeferredRA`), and the Dominatrix numbers below come from her sheets
in the game data, but no Dominatrix draw call was observed. The three large traces
(`KapowMulti.1-3.trace`, 4.5–11 GB) were not dumped.

---

## 0. The frame in one page

`FUN_00563ca4` (per frame) → for every camera `MasterRA::vfunc_02` 0x5632f6 → `DeferredRA::vfunc_01`
0x575da5 (collect) and `DeferredRA::vfunc_02` 0x56f9fb (draw) → post-process → 2-D.
The engine wraps every pass in `D3DPERF_BeginEvent` (Gfx vtable +0xd4), so the capture names the passes
itself; all 26 event names occur as strings in the exe and each was matched to its call site.

| # | pass (PERF event) | code | effect (slot of `DAT_00e166cc`) / pass id | target [capture] | state [capture] |
|---|---|---|---|---|---|
| 0 | `WaveWater`, `2DWaterSimulation` | 0x563ca4 | REWaveWater 0x7c, RE2DWaterSimulation 0x78 | 256x256 A8R8G8B8 ×2 | once per frame, before cameras |
| – | clear | 0x563ca4 | – | scene 1920x1080 A8R8G8B8 + D24S8 | colour 0xFF000000, Z 1, stencil 0 |
| 1 | `Main 3D content` → depth clear quad | 0x5632f6 / 0x56f9fb | `DepthClearVS` | R32F 1920x1080 | then Clear Z+stencil |
| 2 | `Depth info` | 0x56aecb | REDepth 0x38, pass 0 | R32F depth texture + D24S8 | lists 0, 10, 11, 3 (standard, falloff, wet, water); `HARD_ALPHA` variants alpha-tested; then detail (0x54) and `Grass` (0x50) pass 0x18 |
| 3 | `Create scaled ZBuffer` | 0x56f9fb | REScaleZBuffer 0x1c | 960x540 + own D24S8 | colour writes off, ZFUNC ALWAYS (`OutputDepthFromTexturePS`); only if `DAT_00c8d3b0` |
| 4 | `Stencil shadows` → `Stencil shadow layers` | 0x56cb5c | REShadowVolume 0x18, passes 0x11..0x14 | 960x540 A8R8G8B8, cleared white | per layer 0..3: volumes z-fail two-sided stencil (DECR / CCW INCR), then a full-screen quad writes 0 to **one colour channel** where stencil ≠ 0 (COLORWRITE 1,2,4,8) |
| 5 | `Stencil shadow blur` | 0x584f8c | `ShadowFilterPS[GAUSSIAN_N 7]` H then V | 960x540 ping-pong | |
| 6 | `MaterialBloom` / `Bloom Particles` | 0x56c707 | REBloom 0x24 | 960x540 + small Z | sky boxes, then items with `bloomPower > 0`, then bloom particles |
| 7 | `Bloom DownSampleBlur` | 0x56c707 | `DownScale2x2PS`, `GaussianBlurPS` ×2 | 480x272 | → `$matBloomMap` |
| 8 | `Deferred render lights` | 0x56add6 | REDeferredLightLayer 0x80, pass 0x1c | **MRT**: RT0 = LIB, RT1 = LAB (both 1920x1080 A8R8G8B8), cleared 0 | one light volume per draw, COLORWRITE = the light's layer channel, Z test, no Z write; lights the camera is inside: CULL_CCW + ZFUNC GREATEREQUAL |
| 9 | `Sky boxes` | 0x56f9fb | RESkyBox 0x5c | scene colour | blended, sheet blend type |
| 10 | `Terrain` | 0x56f9fb | effect index `this+0x3d0` | scene | only with terrain |
| 11 | `Deferred wet surface` | 0x56f9fb | index `this+0x3cc`, pass 10 | scene | list 11 |
| 12 | `Water surfaces` | 0x56f9fb | REDeferredWater 0x84, pass 5 | scene | list 3 |
| 13 | `Deferred main hard alpha` | 0x56f9fb | index `this+0x3c8`, pass 5 | scene | list 0, blend off, Z write on |
| 14 | `Deferred main fall-off` | 0x56f9fb | index `this+0x3d4`, pass 5 | scene | list 10 |
| 15 | `Grass`, `Detail objects` | 0x56f9fb | 0x50 pass 0x16, 0x54 pass 0x17 | scene | render options +0x9a / +0x99 |
| 16 | `Deferred main soft alpha` | 0x56f9fb | index `this+0x3c8`, pass 7 | scene | list 1, blend on, sorted |
| 17 | `Particles` | 0x56f9fb | REParticles 0x60, pass 0 | scene | soft particles read the depth texture |
| 18 | `Aux3DRA`, StretchRect scene → copy | 0x56f9fb | – | 1920x1080 copy | source for refraction |
| 19 | `RefractiveParticles`, `LensFlares` | 0x56f9fb, 0x56dc9e | REParticles pass 0x15 | scene | |
| 20 | `PostProcessing` | 0x5632f6 → REPostProcess 0x20 (0x57e044) | DownScale2x2 → BloomControlFilter → Gaussian H/V → `PostProcessPS[..]` | 480x272 ×3, then the X8R8G8B8 1920x1080 "back" surface | |
| 21 | `Debug visualization`, `ImmRA` | 0x56a8f0, 0x563ca4 | REDebug 0x28; immediate-mode RA | back surface | HUD / sprites / text: `FixedFunctionVS` + `FixedFunctionPS[TEXTURING]` |
| – | ColorFill + StretchRect (LINEAR) to the swap chain, Present | Gfx | – | back buffer | |

Optional passes that exist in the code and did not run in the capture [code]: `Shadowmap directional` /
`Shadowmap positional` (0x56ca27, only when `DAT_00c8d3ac == 0`), `Reflection - depth / render lights /
Sky boxes / Main / Particles` (0x56cd1f, planar reflection, when a visible item needs it:
`this+0x3ec`), `Refractions` + `-Depth`, `-Deferred render lights`, `-Main` (0x56d299, when the water
list is not empty: `this+0x3ed`), Bink video (not read).

All pass names, order and targets above: **[capture]** for order/state/targets, **[code]** for the call
sites. Formats: scene, LIB, LAB, refraction copy = A8R8G8B8; depth = R32F; back surface = X8R8G8B8;
`$LPT` = 256x1 A16B16G16R16F, `$LCT` = 256x1 A8R8G8B8 (four of each, used round-robin); a second set of
512x1 half-float tables belongs to the forward path. No sRGB read or write state is ever set; no
fixed-function fog state is set. [capture]

---

## 1. Frame structure in detail

### 1.1 Who calls what [code]

- `FUN_00563ca4`: frame entry. Water simulation effects, then for each viewport/camera
  (`DAT_00e165c4[i]`, event `"Camera: " + name`): `MasterRA::vfunc_01` (collect) and `vfunc_02` (draw);
  for viewport 0 afterwards `ImmRA` (0x42d911: HUD, sprites, text). Paused / movie branch
  (`DAT_00e144b8 != 0`) runs only `PostProcessing`.
- `MasterRA::vfunc_02` 0x5632f6: event `Main 3D content` → the scene RA (`FUN_005614dd()` → vtable +8),
  then `PostProcessing` = REPostProcess (slot 0x20: Begin +8, SetPass(0) +0xc, End +0x20), then
  registered overlays, then `Debug visualization`.
- Two scene render algorithms exist: `DeferredRA` (vtable 0xa3f0d0) and `Simple3DRA` (vfunc_02 0x561117, uses RESkyBox, RESimpleTerrain, REMainVertexLight, REParticles: the vertex-lit
  fallback). The capture runs `DeferredRA`.
- Render effects are created once by `FUN_00572a7b` into a 34-slot table (`DAT_00e166cc`). Common
  interface (vtable): +8 Begin, +0xc SetPass(id), +0x10 Render(itemBegin, itemEnd), +0x20 End,
  +0x24 SetWorldMatrix, +0x28 SetDirLight, +0x30 SetMaterial(sheet), +0x40 per-item.

### 1.2 The render-effect table [code: `FUN_00572a7b`; classes from RTTI]

| slot | class | shaders | used by |
|---|---|---|---|
| 0x00 | REMain | MainVS / MainPS (forward, per-material light counts) | **no RA references it** |
| 0x04 | REDeferredMain | DeferredMainVS / DeferredMainPS | DeferredRA only in the alternate set (below) |
| 0x08 | **REDeferredMain2** | DeferredMain2VS ×12 / DeferredMain2PS ×16 | DeferredRA, all model lists |
| 0x0c | REMainVertexLight | MainVertexLightVS/PS | Simple3DRA |
| 0x10 | RESimple | SimpleLightVS/PS | no RA reference found |
| 0x14 | REShadowMap | ShadowMapVS/PS | shadow-map mode only; created only if Gfx+0x468 |
| 0x18 | REShadowVolume | ShadowVolumeVS ×6, FixedColorPS, ShadowFilterPS | stencil shadows |
| 0x1c | REScaleZBuffer | OutputDepthFromTexturePS | half-res depth |
| 0x20 | REPostProcess | PostProcessPS ×9, BloomControlFilterPS | post |
| 0x24 | REBloom | BloomRenderPS, AddBloomPS, SkyBoxVS, TexturingVS | material bloom |
| 0x28 | REDebug | DbgVS/PS | debug |
| 0x2c / 0x30 | REWater / REGlass | GlassWaterVS/PS | **no RA references them** |
| 0x34 | REHelper | HelperVS/PS (2.0) | editor helpers |
| 0x38 | REDepth | DepthVS ×4, DepthPS ×3 | depth pre-pass |
| 0x3c / 0x40 / 0x44 | REAdvTerrain / RESimpleTerrain / REDeferredTerrain | | terrain |
| 0x48 (=0x4c) | REForwardGrass | GrassVS/PS | not referenced by DeferredRA |
| 0x50 / 0x54 | REDeferredGrass / REDeferredDetail | | grass, detail objects |
| 0x58 | **REHair** | HairVS/PS | **no RA references it** |
| 0x5c | RESkyBox | SkyBoxVS/PS | sky |
| 0x60 / 0x64 | REParticles (two instances) | ParticleVS ×12, ParticlePS ×6 | particles |
| 0x68 / 0x6c | REFalloff / REDeferredFalloff | | forward: unreferenced; deferred: alternate set |
| 0x70 / 0x74 | REWetSurface / REDeferredWetSurface | | same |
| 0x78 / 0x7c | RE2DWaterSimulation / REWaveWater | | water normal maps |
| 0x80 | REDeferredLightLayer | DeferredLightLayerVS/PS ×16 | light buffers |
| 0x84 | REDeferredWater | DeferredWaterVS/PS | water |

"No RA references it": every load of `DAT_00e166cc` in the exe was enumerated (`work/wp1/xref.py`, 44
sites); slots 0x00, 0x10, 0x2c, 0x30, 0x48, 0x58, 0x68, 0x70 are never read. Their shaders are compiled
(all 242 are created in the capture) and never bound: in 410 frames no `MainVS`, `MainPS`, `HairVS`,
`HairPS`, `GlassWater*`, `SimpleLight*` draw occurs [capture]. So the forward lighting model, the
Kajiya-Kay hair shader and the glass shader are **dead in the shipped PC renderer**.

`DeferredRA` picks the model effect through four indices at `this+0x3c8..0x3d4` (main, wet, terrain,
falloff). `FUN_00567dce` toggles between `{1, 0x1d, 0x11, 0x1b}` (REDeferredMain / REDeferredWetSurface /
REDeferredTerrain / REDeferredFalloff) and `{2, 2, 2, 2}` (REDeferredMain2 for everything) [code]. The
capture uses the second set for every model draw [capture]. Which value the constructor leaves and
whether anything flips it at run time: [NE] (caller 0x575041 not read).

---

## 2. Scene traversal, visibility, LOD, queues

### 2.1 Collect (`DeferredRA::vfunc_01` 0x575da5) [code]

1. `FUN_0057451f` → `FUN_00573021`: frustum culling. A quadtree (children `4·n + 1 + i`) is walked with
   the camera planes (`FUN_00572817`, plane test `FUN_0056a3c4`); the items of the surviving cells are
   tested on a worker (`QuadTreeItemCheckFrustumJobContainer`), result = one visibility byte per scene
   node (`this+0x40`, node list `this+0x28`). The reflection camera does the same (`FUN_00574659`).
2. `FUN_00574048`: occluders (render option +0x7e): visible nodes whose model has occluder data are
   rasterised by the occlusion jobs (`OcclusionRender/Query/MergeJobContainer`). Read at call-list level
   only; the occlusion test itself is [NE].
3. `FUN_0056f503`: finds the water / planar-reflection plane.
4. `FUN_005750cd` (via 0x574cdb / 0x574e20): light gathering, section 4.
5. **`FUN_005739d0`: builds the render lists.** For every visible node:
   - distance cull for model nodes: `dist² · globalGeometryLodFactor² · node.geometryLodFactor² ≤
     (2·radius + lodDistance[last] + lodFadeOut[last])²` (0x5739d0 + `FUN_0049cf99`; the radius is added twice); nodes with a forced LOD use
     57312 m.
   - `FUN_0049d00f` → `FUN_0053a317` chooses LOD A, LOD B and a cross-fade weight (2.3).
   - for every render instance (RI) of the node whose LOD byte (`RI+0x1e`) is A or B:
     `alpha = sheet.opacity (+0x98) · RI.opacity (+0x18, the node's opacity) · fade`;
     **list index = `sheet.renderType` (+0x60)**; if the type is 0 or 10 and `alpha < 0.99`
     (`_DAT_00a000b0`) the item goes to list 1. Item = 0x18 bytes `{node, RI, alpha, sortDistance}`;
     sort distance (camera to object origin, in object space) is computed for lists 1, 7 and 11.
   - items whose sheet has `bloomPower > 0` (+0x94) or type 7 are also added to the bloom list
     (`this+0x16c`).
   - shadow-hull RIs of the node go to the shadow candidate list.
6. Sorting: list 0 by a state key `FUN_00567d14` = (RI type, sheet pointer, mesh buffer) — batching, not
   depth (0x56ec84); lists 10 and 11 by 0x569bf5; lists 1, 6, 7 **by `sheet.renderOrder` ascending, then
   distance descending** (comparator `FUN_0056881d`, 0x56189f).

The twelve lists live at `DeferredRA+0x7c + 12·type`:

| list = renderType | name in the editor dropdown | depth pre-pass | drawn in | 
|---|---|---|---|
| 0 | Standard | yes | `Deferred main hard alpha` |
| 1 | Standard with blending (and any 0/10 item with alpha < 0.99) | no | `Deferred main soft alpha` |
| 2 | Glass | no | **never drawn by DeferredRA** |
| 3 | Water | yes | `Water surfaces` |
| 6 | Hair | no | **sorted (0x575da5) but never drawn by DeferredRA** |
| 7 | SkyBox | no | `Sky boxes` (+ bloom) |
| 9 | Sprite | no | not drawn as a model list (sprites go through ImmRA) |
| 10 | Falloff | yes | `Deferred main fall-off` |
| 11 | Wet surface | yes | `Deferred wet surface` |

[code] for the routing; [data] first-sheet counts over 904 textures: type 0 ×704, 1 ×80, 10 ×86, 11 ×4,
3 ×2, 7 ×17, 9 ×11; **no sheet uses type 6 (Hair) or 2 (Glass)**. Character textures (220 sheets):
type 0 ×115, 10 ×100, 1 ×5.

There is no instancing for models (one `DrawIndexedPrimitive` per RI; `SetStreamSourceFreq` in the
capture belongs to grass / particles [capture, not traced further]).

Script-level culling (`CullingGroup`, `CullingVisibilityGroup`, PVS fragments) works by enabling and
disabling nodes before this stage (dominatrix_audit g2); it was not re-read here.

### 2.2 Render instances [code]

`RenderInstance` (base ctor 0x58e173): `+4` type, `+0xc` MeshBuffer, `+0x10` TextureSheet, `+0x14`
world-matrix pointer, `+0x18` opacity, `+0x1e` LOD index. Types: 1 `MeshRI` (rigid), 2 `SkinnedRI`
(CPU-skinned copy), 3 `SkinnedRIHW` (GPU palette, `+0x28` matrices, `+0x30` count), 5 `ClothRI`,
6 `ClothShadowRI`. Static models: `FUN_0053f294` (modelres.cpp) creates one RI per submesh of **every**
LOD, plus one RI per shadow hull **only when `DAT_00c8d3ac == 1`** (stencil-shadow mode). Characters:
`FUN_004bea65` (character.cpp).

### 2.3 Model LOD [code + data]

`FUN_0053a317(model, d, mode)`, with `d = max(0, |boundsCentre − camera| − radius) ·
node.geometryLodFactor (+0x1c4) · GFX.globalGeometryLodFactor (+0xd4)` and radius = half the bounding-box
diagonal (`FUN_0049d00f`). The model stores, per LOD `i` (0x18-byte records from `ModelRes+0x13c`),
`distance[i]`, `fadeIn[i]` (+8), `fadeOut[i]` (+0x10); last LOD index at `+0xb4`.

- mode 0 "Normal": `i` = first LOD with `d ≤ distance[i]`; beyond the last distance nothing is drawn.
  Cross-fade, no hysteresis: while `distance[i-1] ≤ d < distance[i-1] + fadeOut[i-1]` LOD `i-1` is
  also drawn with weight `1 − (d − distance[i-1]) / fadeOut[i-1]`; while `d > distance[i] − fadeIn[i]`
  LOD `i+1` is also drawn with weight `(d − (distance[i] − fadeIn[i])) / fadeIn[i]`. The faded LOD is
  alpha-blended (weight < 0.99 moves it to the soft-alpha list).
- mode 1 "Force max": LOD 0. Mode 2 "Force min", or a model without the LOD flag (bit 18 of `+0x64`):
  the last LOD. Modes 3 / 4 (internal, used for shadows / reflection): last LOD, cut at `distance[0]`
  or `distance[last]`.
- A node can force a LOD (`BaseModel.geometryLodOverride`, `+0x1c8 ≠ −1`).

Where the numbers are [data]: in the ModelRes **property bag** as `lodDistance01, 12, 23, 34, 45`,
`lodFadeIn01..45`, `lodFadeOut01..45` (names built in `ModelRes::vfunc_06` 0x53ef10; hashes confirmed on
735 headers). Defaults 150 / 157 / 161 / 165 / 167 m, fade-in 2 m, fade-out 5 m then 2 m.
LOD counts over 740 models: 623 with one LOD, 113 with two, 4 with three. **All 134 character models
have exactly one LOD**; `lodDistance01` is 150 m on 75 of them, 40 m on 55, 30 m on 4 (fade-out 5 m), so
a character part simply fades out between 150 and 155 m (or 40–45 m). The character code only ever
instantiates pivot 0 / LOD 0 (`FUN_004bea65` calls every accessor with `(0, 0, i)`) [code].
`CharacterLodCtrl` (script) was not read.

---

## 3. Material → shader, constants, samplers

### 3.1 TextureSheet members used by the renderer [code: `TextureSheet::RegisterMembers` 0x526589, getter offsets]

Full list (70 properties) in the JSON. The ones the deferred path reads:

| offset | property | consumer |
|---|---|---|
| +0x60 | renderType | list routing 0x5739d0; wet / falloff branch 0x571d5d |
| +0x70 | isLit | not read by REDeferredMain2 (all sheets have 1) |
| +0x74, +0x78 | selfIlluminance, selfIlluminanceColor | `$effectFactors.yzw` = colour · selfIlluminance |
| +0x88, +0xa5 | normalMapPower, enableNormalMapping | `$effectFactors.x` = power, or 0 when disabled |
| +0x8c | specularPower | `$specularData.y` (intensity) |
| +0x90 | specularSize | `$specularData.x` (exponent) |
| +0x94 | bloomPower | bloom list; `$bloomPower` |
| +0x98 | opacity | item alpha; < 0.99 → blended list |
| +0xa0 | alphaThreshold | `D3DRS_ALPHAREF` (0x5696a7) |
| +0xa1 | writeDepthBuffer | Z write of blended items (0x582eb6) |
| +0xa2, +0xa3 | castShadow, receiveShadow | not read in this pass |
| +0xa4 | twoSided | `D3DCULL_NONE`; selects the `TWO_SIDED` bundle |
| +0xb0 | reflectionType (0 none, 1 plane, 2 cube) | pixel-shader choice 0x56bcb8 |
| +0x104, +0x10c | reflectionBumpPower, reflectionLightFactor | `$reflectionData` = (lightFactor, bumpPower) |
| +0x114..+0x124 | u/v/u2/v2 scroll | `$UVScrollData`, `$additionalGlowUVScroll` |
| +0x154..+0x160 | blendType, srcBlend, dstBlend, blendOp | 0x582eb6 |
| +0x168, +0x16c | fallOffPower, fallOffColor | `$falloffData` = (colour, power) |
| +0xc4 / +0xd4, +0xe0 | depthFadeGradient (+alpha), gradient texture | `$falloffMap` (s4) |
| +0x18c | renderOrder | blended sort key |
| +0x190.. | eight layer overrides (diffuse, normal, specular, glow, height, fallOff, ambOcc, specSize) | sampler binding |

**Correction:** `impl_sheets.md` 2.1 says "twoSided (+0xa1)". +0xa1 is `writeDepthBuffer`; `twoSided` is
+0xa4 (as vcolor.md and KAPOW_NAZ_FORMAT.md already say).

Layer ids used by `FUN_0049c838` / `FUN_00523d9a` [code]: 0/1 diffuse, 2 normal, 3 height, 4 specular,
5 glow, 6 fallOff, 7 ambOcc, 8 specSize. A texture frame holds eight slots (0x20 bytes); a missing layer
is replaced at load (part_0008 ~2420) by an engine default and flagged "not real":
normal → flat grey (Gfx+0x598, uploaded as ATI2N), **specular → white** (Gfx+0x59c), **glow → white**,
height → black (Gfx+0x5a0), fallOff → white, ambOcc → white, **specSize → black**. Confirmed on the
capture: a draw without specular layer binds the same default texture to s2 and s6 [capture].

### 3.2 Which pixel shader (`REDeferredMain2::SetMaterial` 0x571d5d, `FUN_0056bcb8`) [code]

```
extra = sheet has a real glow layer  OR  selfIlluminance != 0
        OR  sheet has a real specSize layer  OR  twoSided
low   = RenderOptions+0x9c == 0  OR  pass is 0x19..0x1b (the reflection / refraction sub-passes [inferred])

low                         : extra ? [ALL_ADDITIONAL_FEATURES;TWO_SIDED]            : []
renderType 11 (wet)         : WET_SURFACE / WET_SURFACE_LOD (+ PLANAR / CUBEMAP)      (FUN_005697a4)
renderType 10 (falloff)     : extra' ? [AAF;CUBEMAP_REFLECTION;FALLOFF;SPECULAR;TANGENTSPACE;TWO_SIDED]
                                     : [FALLOFF;SPECULAR;TANGENTSPACE]
                              extra' = extra OR reflectionType == 2   (FUN_005697fe)
reflectionType 2 (cube)     : extra ? [AAF;CUBEMAP_REFLECTION;SPECULAR;TANGENTSPACE;TWO_SIDED]
                                    : [CUBEMAP_REFLECTION;SPECULAR;TANGENTSPACE]
reflectionType 1 (plane)    : same with PLANAR_REFLECTION
otherwise                   : extra ? [AAF;SPECULAR;TANGENTSPACE;TWO_SIDED] : [SPECULAR;TANGENTSPACE]
```

`ALL_ADDITIONAL_FEATURES` and `TWO_SIDED` always come together: one flag buys glow, the specular-size map
and the `vFace` normal flip. A falloff material with a cube reflection always gets the full variant.
Vertex shader: `FUN_00569734(skinned = RI type 3, hasColor = MeshBuffer+0x31)` as vcolor.md 4 describes.
Both agree with every (VS, PS) pair in the capture.

### 3.3 Constants and samplers of the colour pass [code + bytecode; values checked on the capture]

| register | name | set by | value |
|---|---|---|---|
| PS c0 | `$ambientLight` | Begin 0x56bb7e | Gfx+0x508: sum of Ambient lights (colour · brightness), section 4.1 |
| PS c1 | `$fogColor` | 0x5787af | GFX.fogColor (+0x64) |
| PS c2 | `$specularData` | 0x571d5d | (specularSize, specularPower, 250.0, 2.0); z, w are literals (0xa3eeb8, 0x9e663c) |
| PS c3..c5 | `$worldMatIT` | 0x5691b7 | inverse-transpose world |
| PS c7 | `$camPosWS` | SetPass 0x57552b | camera position; w = 1, or −1 in passes 0x19 / 0x1a (mirrored reflection): multiplies the normal |
| PS c8, c9 | `$dirLight[2]` | 0x5695a4 | (−direction, colour · brightness) of the first Directional light; zero when none |
| PS c11 | `$effectFactors` | 0x571d5d | (normalMapPower or 0, selfIllumColor · selfIlluminance) |
| PS c12 | `$reflectionData` | 0x56bd5f | (reflectionLightFactor, reflectionBumpPower) |
| PS c13 | `$wetSurfaceConstants` | 0x56debe | not read |
| PS c14 | `$falloffData` | 0x5697fe | (fallOffColor rgb, fallOffPower) |
| PS c15 | `$additionalGlowUVScroll` | 0x56dfb0 | sheet+0x130 when glowMapChannel ≥ 1, else 0 |
| PS c29 / c30 | `$screenPosToViewportUV` / `$screenPosToScreenUV` | SetPass (Gfx +0xc4 / +0xc8) | vPos → UV of the light buffers |
| VS c0, c4 | `$worldViewProj`, `$worldMat` | 0x5691b7 | |
| VS c8 | `$camPosObj` | 0x5691b7 | |
| VS c9 | `$UVScrollData` | 0x571d5d | sheet+0x128 when +0x125 is set |
| VS c10 | `$terrainTextureNr` | 0x569702 | layer / 255 |
| VS c11 | `$alphaFactor` | 0x5696a7 | the item's alpha (opacity · node opacity · LOD fade) |
| VS c35 | `$wetEffectFade` | 0x56bb7e | (start, 1 / (start − end)) |
| VS c36 | `$fogInfo` | 0x5787af | (fogEnd, 1 / (fogEnd − fogBegin)); fog factor = 1 − sat((fogEnd − dist) · y) |
| VS c40.. | `$skinning` | 0x579bb0 → Gfx vtable +0x3c | 70 × 3 rows, section 5 |
| s0, s1, s2 | diffuse, normal, specular | 0x571d5d | layer or default (3.1) |
| s3 | `$reflectionMap` | 0x56bd5f | cube map of the nearest CubeMap node, or the planar reflection target |
| s4 | `$falloffMap` | 0x5697fe | `sheet+0xe0`: gradient texture built from `depthFadeGradient` |
| s6, s7 | glow, specSize | 0x56dfb0 | only bound when `extra` |
| s8, s9 | `$LIB`, `$LAB` | SetPass | point, clamp |
| s10, s11 | `$LPT`, `$LCT` | SetPass | current table of the ring of four |

Capture check, one falloff draw of the menu characters: `c2 = (20, 0.58, 250, 2)`, `c12 = (0.15, 0.02)`,
`c14 = (1, 1, 1, 0.06)`; next material `c2 = (11, 1.2, 250, 2)`, `c14 = (0, 0, 0, 0.42)`.

Render state per material [code 0x571d5d, 0x582eb6, 0x5696a7; capture]: cull = NONE when twoSided else the
pass default (CW); alpha test enabled when the diffuse texture has an alpha channel (`tex+0x1c` bit 0),
`ALPHAREF = alphaThreshold`, `ALPHAFUNC = GREATEREQUAL` (the only value in the capture); in the blended
pass: blendType 0 = SRCALPHA / INVSRCALPHA ADD, 1 = SRCALPHA / ONE ADD, 2 = SRCALPHA / ONE REVSUBTRACT,
3 = the sheet's own triple; Z write = writeDepthBuffer.

### 3.4 Define sets — the 19 unresolved shaders

`DeferredMainHelper` (ctor 0x58db62) composes the DeferredMainPS sets from a base list plus
`TWO_SIDED, DIR_LIGHT_ENABLE, SPECULAR, DIR_LIGHT_SHADOWS, TANGENTSPACE, TERRAIN_AO, TERRAIN_AO_FADEOUT`,
then `CUBEMAP_REFLECTION` / `PLANAR_REFLECTION`, then `SPECULAR_SIZE, UV_CHANNEL_SELECTION, TEXTURE_A0`,
and an `UNLIT` variant [code]. With that vocabulary an exhaustive subset search (`work/wp1/bf.c`, hash as
in vcolor.md) names **all 15 DeferredMainPS**, and `FixedFunctionPS453591715 = [TEXTURING]` (string at
the compile site in part_0003). 16 of 19 resolved; list in the JSON.

- **Correction to `defines_resolved.tsv`:** `DeferredMainPS-1209756536` is
  `DIR_LIGHT_ENABLE;DIR_LIGHT_SHADOWS;PLANAR_REFLECTION;SPECULAR;TANGENTSPACE;TERRAIN_AO;TWO_SIDED;WET_SURFACE`;
  the 7-define set recorded there (with two `NUM_SHADOW_CASTING_LIGHTS`) is a 32-bit collision.
- Still unresolved: `MainVS-1480351135`, `MainVS901430857` (terrain variants by their constant tables:
  `$terrainTextureNr`, `$shadowMapMats` ×3 / ×1) and `SimpleLightVS1431484195` (`$textureNr`, `$zbias`).
  All three belong to effects no render algorithm uses.

---

## 4. Lighting

### 4.1 Lights on the CPU [code]

`Light` members (`Light::RegisterMembers` 0x4a7051): type +0x130 (**Point 1, Spot 2, Directional 3,
Ambient 4, Box 6, Frustum 7**), textured +0x134, causeShadows +0x135, colour +0x138, range +0x148,
attnStart +0x14c, brightness +0x150, shadowPower +0x154, ignoreGlobalLightFading +0x158,
distFadeStart / End +0x15c / +0x160, inner / outer cone +0x164 / +0x168, box size +0x16c..+0x174.

`FUN_005750cd` (DeferredLightManager) walks the global light list:

- **Directional**: only the first enabled one is used (`this+0x28`) → `$dirLight`.
- **Ambient**: every one adds `colour · brightness` → `$ambientLight`. With lighting disabled (render
  option +0x83) or one light in the level the ambient is (0.65, 0.65, 0.65).
- **Point / Spot / Box / Frustum**: kept when the light's bounds touch the view; priority = distance fade
  `FUN_0056a4c0` (1 inside distFadeStart, 0 beyond distFadeEnd, unless ignoreGlobalLightFading).
  At most **255** ("%d light was found, only %d is rendered"); sorted by an integer at `light+0x24`
  (0x569e70; meaning [NE]); index = position + 1 (0 = no light).
- `SortLightsJobContainer` (0x58e108 → `FUN_008bc840`) assigns each light a **layer 0..3 by greedy
  colouring**: a light takes the first layer not used by an earlier light whose bounds overlap its own;
  if all four are taken it is flagged "overlapping" (`Overlapping lights: %i %s`, 0x56dd83) and put in the
  layer where the overlap is smallest. It also computes whether the camera is inside the volume.
- `FUN_0056b4a0` writes the tables: `$LPT[i]` = (world position, brightness) as half floats (Box lights:
  position pushed −1000 along their axis, i.e. treated as far away); `$LCT[i]` = colour · distance fade as
  bytes. Entry 0 is zero. So light colours are quantised to 8 bits and brightness is separate.

### 4.2 The two light buffers [code 0x58a79c, 0x5855a2; bytecode DeferredLightLayerPS]

Each light is drawn as its volume (`/Helpers/unitsphere`, `unit_cone`, `unit_box` models) with colour
writes restricted to its layer's channel (`FUN_00567e61`: 1, 2, 4, 8):

- **LIB** (RT0) channel = `index / 255` (`$lightIndexColor`).
- **LAB** (RT1) channel = `attenuation · shadow`, with
  `attenuation = sat((range − d) / (range · (1 − attnStart))) · distanceFade`
  (`$lightAttnData = (−1 / (range(1 − attnStart)), 1 / (1 − attnStart), …)`, `$lightPowers.y` = fade;
  attnStart is capped at 0.99); spots multiply `sat((cos θ − cos outer) / (cos inner − cos outer))`;
  box / frustum use their own z, w terms; `TEXTURED` variants multiply a projected texture.
  `shadow = 1 + k · (S − 1)` where `S` is the channel of the blurred stencil-shadow buffer selected by
  the one-hot `$shadowLayerSelector` and `k = sat(camDist · a + b)` fades shadows with camera distance.
  Pixels with attenuation below 1e-4 are discarded.
- The position is reconstructed from the R32F depth texture, so **the buffers describe the opaque
  surface**; later overlapping lights of the same layer overwrite earlier ones.

Consequence: each pixel sees **at most four positional lights (one per layer)** + one directional +
ambient. Blended surfaces are drawn after and read the light indices and attenuation of the opaque pixel
behind them [inferred from pass order + bytecode].

### 4.3 Shadows [code + capture]

- Mode global `DAT_00c8d3ac`: 1 = stencil volumes (value in the exe image and what the capture shows),
  0 = shadow maps (REShadowMap; no depth texture is ever created in the capture). `DAT_00c8d3b0` = 1:
  half-resolution shadow buffer.
- A light casts when `causeShadows` and the camera is within `light radius + 25 m`
  (`FUN_00574b7d`; 25.0 = `_DAT_009f8094`, the `shadowMaxRange` default).
- Casters (`FUN_005748e2`): up to 512 nodes from a spatial query around the light; enabled, visible,
  node `castShadow` (+0x12b), with shadow-hull RIs; the hull whose LOD byte matches the shadow LOD
  (`FUN_0049d149`) and whose box intersects the light is queued.
- The geometry extruded is the model's **shadow hull** (vertex formats 9 / 10; `ShadowVolumeVS`
  `[POINT|SPOT|DIRECTIONAL][SKIN]`, skinned hulls use the same 70-bone palette). Cloth has
  `ClothShadowRI`.
- The light's **layer** is also its shadow channel: lights of one layer do not overlap, so their volumes
  share one stencil pass and one channel of the 960x540 buffer; four passes, then a 7-tap Gaussian.
- The directional light has no shadow term in DeferredMain2PS [bytecode]; `DIR_LIGHT_SHADOWS` exists only
  in the unused DeferredMainPS / MainPS families.

### 4.4 The character lighting equation (DeferredMain2PS, full variant) [bytecode: `DeferredMain2PS1329511463`]

```
uv      = TEXCOORD2.xy (+ $UVScrollData in the VS)
albedo  = diffuseMap(uv)            specTex = specMap(uv)          glow = glowMap(uv + glowScroll).rgb
n       = (specSizeMap(uv).g² · 256 + 1) · specularSize           [AAF variants; otherwise n = specularSize]
I       = specularPower
N       = normalize(x·T + y·B + z·Nv), (x, y) = (2·nm.xy − 254/255) · normalMapPower, z = sqrt(1 − x² − y²)
          two-sided: N = −N on back faces;  N *= camPosWS.w;  N = worldMatIT · N
V       = normalize(camPos − P)

for the four layers k (R, G, B, A of LIB / LAB at this pixel):
   i   = LIB.k · 255/256 + 0.5/256            -> row of LPT / LCT
   C_k = LCT[i].rgb · LPT[i].w                 (colour · distance fade · brightness)
   L   = normalize(LPT[i].xyz − P),  H = normalize(L + V)
   d_k = LAB.k · sat(N·L)                      (attenuation · shadow · N·L)
   s_k = I · sat(N·H) / (n − n·sat(N·H) + sat(N·H))        (Schlick's approximation of (N·H)^n, unnormalised)

G        = selfIllumColor · selfIlluminance · glow
diffL    = ambient + dirColour · sat(N·dirDir) + G + Σ C_k · d_k
specL    = G + Σ C_k · d_k · s_k
lit      = albedo.rgb · diffL
lit      = lerp(lit, cube(reflect(−V, N)).rgb, specTex.rgb · reflectionLightFactor)     [reflection variants]
lit     += specTex.rgb · specL
F        = falloffMap(u = v = sat(N·V)).rgb · fallOffPower        (0 on back faces)      [FALLOFF variants]
rgb      = lit · vertexColour.rgb  +  F · (diffL + specL + fallOffColor)
out.rgb  = lerp(rgb, fogColor, fog)
out.a    = albedo.a · vertexColour.a · alphaFactor
```

Notes, all [bytecode] unless tagged:

- The specular term is multiplied by the **diffuse N·L and the same attenuation** as the diffuse term, has
  no Fresnel and is not energy-normalised: its peak is `I · specTex · C` whatever `n` is.
- The directional light and the ambient contribute **no specular**.
- Glow is added to **both** sums, so the emitted colour is `G · (albedo + specTex)`. With no glow layer
  the default is white: `selfIlluminance ≠ 0` alone makes the whole surface emit `colour · SI · (albedo
  + specTex)`. Negative values occur in the data (−1, −0.27, −0.15) and darken.
- The falloff term is added **after** the albedo and vertex-colour multiply: it is a light-coloured rim,
  not tinted by the texture.
- Everything is computed on display-encoded values (no sRGB anywhere) [capture].

**Reconciliation with `TEXTURE_SHADER_NOTES.md`:**

- Sampler table: correct for the full variant. In the plain `[SPECULAR;TANGENTSPACE]` variant s6 / s7 do
  not exist.
- "exponent = specSize² · 256 + 1 (× c2.x)": correct, the channel read is **G** of the specSize texture;
  without a specSize layer (or without the `extra` flag) `n = specularSize`.
- "specular = c2.y · NdotH / (NdotH + exponent · (1 − NdotH))": correct, and it is additionally × N·L ×
  attenuation × light colour.
- "finalRGB = diffuseMap · (Σ diffuse + glow) + specMap · (Σ specular + glow)": correct for the full
  variant; add ambient + directional to the first sum, the reflection lerp, vertex colour, falloff, fog.
- "z = 250, w = 2 are global constants (rim / fresnel)": they are literals pushed with every material.
  Only `DeferredMain2PS-270807833` (the low-quality full variant) reads `c2.zw` (as a scale / bias);
  no rim or Fresnel term uses them.
- **"CORRECTION: the specSize layer behaves as a matte map; roughness must increase with specSize" is not
  what the shader does.** A larger specSize gives a larger exponent, i.e. a *narrower* lobe. Because the
  lobe is not normalised, a narrow lobe is small *and no brighter*, so the surface reads as less shiny
  overall; in a PBR viewer the right translation is "narrow lobe (lower roughness) **and** lower
  specular strength" (section 7.2), not an inverted roughness.
- "roughness = sqrt(2 / (exp + 2))" yields the GGX alpha, not glTF's perceptual roughness (alpha =
  roughness²): use the fourth root.
- "$specularData is stored per texture, hashLo 0xf4142d28 / 0xb3ab3306": these are the sheet properties
  `specularSize` (+0x90, exponent) and `specularPower` (+0x8c, intensity) [code]; "the first block is
  active" = the first sheet, unless the model's `textureSheetsDescription` selects another
  (impl_sheets.md).
- "intensity 0 → matte": correct (`s_k = 0`); note that a missing specular **map** is white, not black.

**Corrections to `vcolor.md`:** 7 "the rule that routes a material to REDeferredMain2 versus the other
render effects" is now established (1.2, 2.1: there is no per-material effect choice in the deferred
RA; the material chooses a *list* by renderType and a *shader variant* by 3.2). 4 "`FUN_0056bcb8` picks
by … material type (sheet+0x60 = 10 or 11) and an additional-features / two-sided flag": the flag is the
four-way OR of 3.2.

### 4.5 Vertex-lit fallback

`Simple3DRA` + `REMainVertexLight` (`MainVertexLightVS[DIR_LIGHT_ENABLE true; NUM_POSITIONAL_LIGHTS 0|2;
SKIN]`) is the non-deferred path (directional + up to two positional lights per vertex). When it is
selected (hardware without MRT / SM3, an option): [NE].

---

## 5. Skinning and characters

- **Palette** [code + bytecode + capture]: `Character::vfunc_29` 0x4c30c9 decides per character:
  hardware skinning iff a model is set, `1 ≤ maxSkinnedBones ≤ 70` and Gfx+0x400 (device capability).
  `maxSkinnedBones` = max over the character's models of `ModelRes+0xe4` = highest bone index used by the
  LOD-0 submeshes + 1 (`FUN_0053db65`, log string "Number of skinned bones for '%s' is %d").
  The palette is the character's array at `+0x270` (4x4, 0x40 bytes per bone); `FUN_00579bb0` passes
  pointer and count to Gfx (+0x3c), which uploads **3 rows per bone at c40** (first matrix of a capture
  upload: `1,0,0,0, 0,1,0,0, 0,0,1,0`; translation in the fourth column). There is **no per-submesh
  palette split**: one palette per character node, shared by all its RIs, the depth pass, the colour pass
  and the shadow hulls. More than 70 bones → software skinning.
- **Software path** [code]: `SkinnedRI` (type 2) draws a per-character dynamic copy of the mesh
  (`FUN_00433c40`) filled by `SkinJobContainer` 0x443cfb → `FUN_004789b5` (vertex format 6 →
  `FUN_00477480`, format 10 hulls → `FUN_00477b67`) on the worker threads; it is then drawn with the
  non-`SKIN` vertex shaders. Not seen in the capture.
- **Head / face**: the head is a separate `Character` node with its own skeleton attached to the body's
  `Spine2` (face.md 1.3). For the renderer it is just another character: its own `SkinnedRIHW`s and its
  own ≤ 70-bone palette, same lists, same shaders [inferred from the Character code being
  class-wide; the head node itself was not traced].
- **Hair**: no special path. The hair sheets are `renderType` 10 (Falloff) or 0, `twoSided`,
  `alphaThreshold` 95 (e.g. `GogoHairLayeredBlonde`: Falloff, two-sided, specularPower 0) [data]. They
  are drawn **opaque, alpha-tested (ref 95/255, ≥), with Z write, in the depth pre-pass and the hard /
  fall-off pass**; no sorting, no second pass [code for the routing; data for the sheets]. `REHair` /
  `HairPS` (Kajiya-Kay, two shifted highlights) is never used (1.2).
- **Eyes, brows, mouth** (`Female_Eye_Blue`, `EyeBlow`, `WomanMouth`): plain Standard sheets with
  specularPower 0 [data]. There is no eye shader.
- **Dominatrix** [data]: suits, gloves, boots, masks (`DominatrixSuits1/2`, `Dominatrix_Glove1/2`,
  `LongBoots`, `FimaleGimp*`): Falloff, two-sided, cube reflection, specularSize 43, specularPower 1.17,
  reflectionLightFactor 0.1, fallOffPower 0.25, fallOffColor white → full variant
  `[AAF;CUBEMAP;FALLOFF;SPECULAR;TANGENTSPACE;TWO_SIDED]`, pass `Deferred main fall-off`.
  Skin (`FemaleSkinBody_White`, `GogoBody*`, heads): Falloff, one-sided, specularPower 0.05–0.29,
  specularSize 3.2–15 → `[FALLOFF;SPECULAR;TANGENTSPACE]` (or the full variant when a specSize layer
  exists). `FemaleSkinBody_Dominatrix1` / `_Black`, eyes: Standard, specularPower 0.
- **Rorschach's ink** [capture]: two draws in `Deferred main soft alpha`, `DeferredMain2VS[SKIN;
  TANGENTSPACE;VERTEX_COLORS]` + `[SPECULAR;TANGENTSPACE]`, `SRCBLEND = SRCALPHA`, `DESTBLEND = ONE`,
  `BLENDOP = REVSUBTRACT`, alpha test off, Z write off: `dst − lit · alpha`, where `lit` is the fully
  lit layer colour and alpha = texture alpha × vertex alpha.
- **Target highlight / damage**: not re-read (dominatrix_audit g13).

---

## 6. Post-processing

Settings object [code 0x57e044]: the camera's GFX node (`camera+0x348`) if it has one, else the global
`DAT_00e148ec`; class `GFXEffect` (fragment nodes of that class; in the Dominatrix levels the
`Art.fragment` nodes "RS GFX" / "NO GFX" quoted in the audit). `FXGfxEffectCtrl` / `GfxBlender` (script)
blend these values over time: [NE].

Chain [capture order, code 0x57e044, bytecode]:

1. `DownScale2x2PS`: scene → 480x272.
2. `BloomControlFilterPS`: `c = c + bloomBrightness; c = c + (c − 0.5) · bloomContrast`
   (`$filterData = (GFX+0xa0, GFX+0x9c)`; menu: 0.13, 0.46).
3. `GaussianBlurPS` horizontal, vertical (9 taps) → `$filteredMap`.
4. `PostProcessPS[AA][DOF][NOISE]` to the back surface; variant index = DOF + 2·AA + 4·NOISE:
   - AA (`enableAA` +0x75 and render option +0xa4): eight depth taps, edge when opposite depth
     differences disagree (`$aaSettings` = edgeDetectGradient, edgeDetectCutoff), edges are blurred.
   - DOF (`enableDOF` +0x81): focalDist, focalNearFallOff, focalFarFallOff, maxFocalBlur (+0x84..+0x90),
     skyBoxBlur (+0x94).
   - `c = scene + matBloom + filtered · bloomWeight`
   - `c += brightness`
   - `c += (c − mean(c)) · saturation`
   - `c += (c − 0.5) · contrast`
   - `c = sat(lerp(c, c · tintColor, tintPower))`
   - `c = c ^ (1 / gamma)`
   - NOISE: tiled noise texture, `noiseIntensity` (+0xd0), offset changed every few frames.
   `$filterData = (bloomWeight +0x98, brightness +0xa4, saturation +0xa8, contrast +0xac)`,
   `$tintData = (tintColor +0xb4, tintPower +0xb0)`, `$gammaNoiseArgs.w = 1 / gamma (+0xc4)`.
   Menu values [capture]: (0, 0.25, −0.51, 1.19), tint (0.96, 0.64, 0.192) × 0.42, gamma 1.12.
   Dominatrix level (audit): bloomWeight 0.2, contrast 0.22, saturation 0, tint (0.54, 0.69, 1.0) × 0.3,
   gamma 1.2, fog 0–80 m.
5. Material bloom (pass 6–7): `BloomRenderPS` = glowMap · diffuse · vertexColour · (diffuse.a ·
   bloomPower) at half resolution, blurred; added in step 4.

There is no tone-mapping operator, no LUT, no motion blur, no vignette in the archive [bytecode]. Fog is
per-vertex linear in the model shaders (3.3), not a post effect. Film grain = the NOISE variant.

**What changes a character's on-screen colour relative to her textures**, in order: vertex colour (mean
factor 0.79 on character buffers, vcolor.md); lighting done in gamma space with unnormalised light
colours; the falloff rim; fog (lerp to fogColor, 0 at fogBegin, 1 at fogEnd); bloom; then contrast, tint
and gamma. With the level values a mid-grey 0.5 texel fully lit comes out as
`(0.5 · lerp(1, tint, 0.3)) ^ (1 / 1.2)` = (0.50, 0.52, 0.56): slightly lifted and blue. An export
judged against screenshots must compare *before* this stage or apply it.

---

## 7. Export consequences (prioritised)

### 7.1 What to change in the toolkit

1. **Alpha mode from the list, not from the look.** renderType 0 / 10 / 11 → opaque; add
   `alphaMode: MASK`, `alphaCutoff = alphaThreshold / 255` (default 95 → 0.373) when the diffuse layer
   has an alpha channel. renderType 1 → `BLEND` (and the blend type as today). **Hair is MASK +
   doubleSided, not BLEND** — that is how the engine draws it, and it removes the sorting problem.
   `opacity < 0.99` on a type 0 / 10 sheet → `BLEND` with `baseColorFactor.a = opacity`.
2. **doubleSided = twoSided** (already done); note that the engine also flips the shading normal on back
   faces only in the `extra` variants, which twoSided itself forces — glTF viewers do the same.
3. **Specular**: emit both roughness and specular strength from `(n, I)` (7.2). A material without a
   specular layer has specTex = white, not black; a material with `specularPower = 0` has no specular at
   all regardless of maps (90 of 220 character sheets).
4. **Emission**: `emissive = selfIllumColor · selfIlluminance · glow · (albedo + specTex)`; with no glow
   layer `glow = 1`. Bake that product into the emissive texture (glTF multiplies emissive by nothing
   else). Negative selfIlluminance cannot be expressed: clamp to 0 and record it in extras.
   `bloomPower` only feeds the bloom buffer: write it to extras (optionally
   `KHR_materials_emissive_strength` for viewers with bloom), never into base colour.
5. **Falloff sheets (100 of 220 character sheets, all Dominatrix clothing and most skin)**: glTF has no
   rim term. Closest: `KHR_materials_sheen` with `sheenColorFactor ≈ fallOffPower · gradient colour` and
   high sheen roughness; keep the exact parameters (`fallOffPower`, `fallOffColor`, the
   `depthFadeGradient` string) in extras. Without sheen the export is darker at grazing angles than the
   game.
6. **Reflection (cube, 43 character sheets)**: `lerp(diffuse lighting, environment, specTex ·
   reflectionLightFactor)`. Approximation: raise F0 to at least `reflectionLightFactor · specTex`
   (7.2) so the viewer's environment shows through; do not make the material metallic (the engine
   keeps the diffuse term and does not tint the reflection). Store the factor in extras.
7. **LOD**: export LOD 0. It is the only LOD of every character model, the only one the character code
   instantiates, and for props it is what the game shows up to `lodDistance01` (30–150 m).
   `--model-lod N` should keep meaning "file LOD index N"; add the switch distances from the property
   bag (`lodDistance01..`, `lodFadeIn..`, `lodFadeOut..`) to the model's metadata, and if LODs are
   exported together use `MSFT_lod` or node names `_LOD1` with those distances in extras.
8. **Shadow hulls** (format 9 / 10 buffers): they are the stencil shadow-volume geometry, never shaded.
   Keep them out of the default export; when asked for, emit as separate meshes named `<part>_shadowhull`
   with `extras.watchmen.role = "shadow_hull"` and no material.
9. **"Proxy slab"** (one optional MeshBuffer per part, 79 models: doors, containers, rooms, city blocks,
   never a character): it is the **occluder mesh for occlusion culling** — the part reader 0x545927
   allocates a 0x14-byte occluder record from it and `FUN_0053f9a5` converts its vertices / indices,
   failing with "primitive type … not supported for occluder" (modelresderivedio.cpp) [code]. Rename the
   kind from `proxy` to `occluder`; never export it as visible geometry.
10. **Vertex colour, tangents**: as vcolor.md / impl_vcolor.md (unchanged by this work).
11. **Subtractive / additive layers**: as impl_sheets.md 2.5 (confirmed on the capture for Rorschach).
12. **Unlit preview option**: because the engine lights in gamma space with a constant ambient
    (0.65 fallback) and a contrast / tint / gamma grade, a "looks like the game" preset is: ambient-heavy
    lighting + the level's grade. Offer the grade values per level in the export metadata rather than
    baking them into textures.

### 7.2 Formulas (derived from 4.4; [inferred] — not validated against renders)

Engine specular per light: `I · specTex · C · NL · (N·H)^n` (Schlick form). A normalised Blinn-Phong /
GGX lobe with the same width has `alpha² = 2 / (n + 2)`:

```
roughness (glTF, perceptual) = (2 / (n + 2)) ^ 0.25
     n = specularSize                                   (no specSize layer)
     n = (g² · 256 + 1) · specularSize   per texel      (specSize layer, g = its green channel)
```

Matching the peak of the lobe at normal incidence (engine diffuse = albedo · E, i.e. π times a physical
Lambert) gives the equivalent Fresnel reflectance

```
F0 = 4 · alpha² · I · specTex = 8 · I · specTex / (n + 2)        (clamp to 1)
KHR_materials_specular:  specularColorFactor · specularColorTexture = F0 / 0.04   (ior 1.5, specularFactor 1)
   or KHR_materials_ior with ((ior − 1) / (ior + 1))² = F0 when a viewer clamps the colour factor at 1
I = 0  →  specularFactor = 0
```

Examples: Dominatrix suit (n 43, I 1.17): roughness 0.46, F0 0.21 · specTex. Tan skin (n 3.2, I 0.29):
roughness 0.79, F0 0.45 · specTex. White skin (n 15, I 0.05): roughness 0.59, F0 0.024 · specTex.
A flat `metallicFactor = 0` everywhere: the engine has no metal model.

What glTF cannot reproduce: specular tied to N·L and without Fresnel; no specular from the directional
and ambient light; at most four lights per pixel; gamma-space lighting; the rim term; the lerp-style
reflection; negative self-illumination; subtractive blending; vertex colour scaling specular and
emission; per-object (not per-pixel) transparency order with `renderOrder`.

---

## 8. Not established, and what each would take

| item | what it would take |
|---|---|
| A combat frame with a Dominatrix (draw order among many characters, light counts, shadow layers in a level) | dump ~3 frames of `KapowMulti.3.trace` with `apitrace dump --calls` (the 11 GB trace needs ~1 GB scratch; the VM had 100 MB free) and run `summ.py` |
| Default of `DeferredRA+0x3c4` (REDeferredMain2 vs the DeferredMain family) and what flips it | read the ctor 0x574f74 / caller 0x575041 |
| Sort key `light+0x24` | read the Light / scene-node base ctor |
| Occlusion culling (software rasteriser, occluder selection, `FUN_00583640`) | read 0x574048 callees and the three Occlusion job containers |
| `CharacterLodCtrl`, `FXGfxEffectCtrl`, `GfxBlender` (script side of LOD and grading) | script classes, WP0 naming first |
| Falloff gradient: exact format of `depthFadeGradient` and the generated texture (`sheet+0xe0`) | read setter 0x5256cf; the strings look like `pos,r,g,b[,a]\|…` |
| `$wetSurfaceConstants`, wet / water / planar-reflection passes | read 0x56debe, 0x5697a4, 0x56cd1f, 0x56d299 |
| Which cube map a reflective character samples (`FUN_004d1299`, nearest CubeMap node?) | read 0x56bd5f callees and the CubeMap node |
| `$shadowAttnData`, shadowPower use, shadow LOD (`FUN_0049d149`), volume extrusion distance | read REShadowVolume 0x582cd6 / 0x584c6d and ShadowVolumeVS |
| Alpha-test enable flag (`tex+0x1c` bit 0) = "diffuse has alpha" | read Texture finalize 0x538184 |
| When Simple3DRA (vertex-lit) is chosen; shadow-map mode | read the RA factory and the options class |
| MainVS ×2, SimpleLightVS ×1 define sets | more vocabulary; all in unused effects |
| Head node drawing, target highlight, decals on characters | trace `CharacterHeadModel` / FxHighlightCtrl / DecalManager |
| Validation of the 7.2 mapping | render a GLB next to a capture frame of the same character with the grade applied |

## 9. Files

- `findings/wp1_renderer.md` (this file), `findings/wp1_renderer.json`
- `work/wp1/`: `rtti.py`, `props.py`, `xref.py`, `ctors.py`, `bf.c` / `bf`, `rf.sh`, `ptr2name.json`
- on the PC, scratch only: `~/scratch/wp1/` (`c.txt.gz`, `compact.py`, `summ.py`, `ev.py`, `lod2.py`,
  `sheets.py`, `lod.json`, `sheets.json`)
