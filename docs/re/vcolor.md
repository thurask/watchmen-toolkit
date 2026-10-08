# Per-vertex colour, tangent frame and winding: what the Kapow shaders do with them

> **Correction (after the render test, see `impl_vcolor.md`):** the TANGENT advice in §6 is superseded.
> No 1.3.0 GLB carries TANGENT, so the "w = s with flipped green" clash never occurred in shipped files.
> The real defect is that PC `ATI2` normal maps were decoded with X and Y swapped. With that fixed and
> green inverted for glTF, **w = −s** matches the engine (about 1° median in three.js and Blender).
> §0's "31 models" and vegetation remarks stand.

Scope: Part 2 PC, vertex formats 5 (44 B) and 6 (56 B). Evidence tags: **[bytecode]** read from the
shader instructions, **[exe]** read from the decompilation/disassembly, **[data]** measured on the
extracted Part 2 models, **[trace]** measured on `apitrace_dump.txt`, **[inferred]**, **[not established]**.

Companion: `findings/vcolor_shaders.json` (all 243 shaders: define set, inputs, every instruction that
reads COLOR0; colour statistics for all 1,453 coloured buffers; tangent statistics; capture draw table).
Scratch and tools: `work/vcolor/` (`sm3dis.py` disassembler + archive reader, `dis/*.asm` all 243
listings, `shash.py`/`bf.c`/`bfa.c` name-hash reproduction, `colour_stats.json`, `trace_shaders.txt`).

## 0. Short answers

| Question | Answer |
|---|---|
| What is COLOR0 on a model vertex? | A **multiplicative tint on the final lit colour** (rgb) and a **multiplier on output alpha** (a). Not AO-on-ambient, not a layer mask, not wind, not a specular mask. [bytecode] |
| When is it used? | Only when the mesh buffer's `hasColor` byte is 1; the engine then picks the `VERTEX_COLORS` vertex-shader variant. Otherwise the shader does not even declare COLOR0 and feeds (1,1,1). [exe] + [trace] |
| Which models? | Every buffer whose colours are not all 255: `hasColor` equals "has a non-white vertex" on 2,657 / 2,657 buffers. That is **387 of 735 models, 1,453 buffers**, not 31. [data] |
| Tangent frame | `N' = x·T + y·B + z·N` with the **stored** tangent (TEXCOORD1) and **stored** bitangent (TEXCOORD2). No cross product, no handedness sign, no orthogonalisation. [bytecode] |
| Culling | `D3DCULL_CW` for one-sided materials, `D3DCULL_NONE` for two-sided ones; two-sided pixel shaders flip the normal with `vFace`. [exe] + [trace] |

Two premises in the task did not hold on the data, both stated here so nobody carries them forward:

- "31 models have non-default colours": the corpus has 387. Under `art/characters` + `Animation` there are 39.
- "The palms and other vegetation are among them": no. Every buffer of `palm_01`, `palm_02`,
  `Palm_Banana_01`, `palm_banana_02`, `fern_01`, the trees has `hasColor = 0` and all-255 colours. [data]
  They are skinned (format 6) and animated through bones, so there is no vertex-colour wind weight.

## 1. Tooling and how it was checked

- Archive layout [data]: `u32 2; u32 243; { u32 nameLen; char name[]; u32 offset; u32 size }`, offsets
  relative to the end of the directory (17,244). Entry names are `<ShaderName><signed int>.bin`.
- `sm3dis.py` is a from-scratch SM3 disassembler. Checks: all 243 shaders parse to exactly their
  stored size; 240 of the 242 shaders that the game creates in the capture match an archive entry by
  full opcode sequence (the other two are 10-instruction pixel shaders not in the archive);
  three shaders were compared line by line with apitrace's own disassembly and are identical
  (`DeferredMain2VS1835652617`, `DeferredMain2VS-202936803`, `DeferredMain2PS-453328923`); CTAB names land
  on the registers the code reads (e.g. `$skinning` = c40 and the code indexes `c40[a0.x]`).
- The integer in the file name is a hash of the compile key [exe, `FUN_0042a25c`]: shader name, profile
  string, then each `#define` in alphabetical order, through the engine's bitwise CRC
  (`FUN_00423d7c`, poly 0x04C11DB7, LSB-first, 4 zero bytes appended). Reproducing it names the define
  set of **224 of 243** shaders, including all 95 vertex shaders but three. Sets found by the deep
  search (up to 7 defines) can be 32-bit collisions; two are flagged in the JSON. 19 are unresolved
  (15 `DeferredMainPS`, 2 `MainVS`, 1 `SimpleLightVS`, 1 `FixedFunctionPS`).

## 2. Which vertex shaders declare COLOR0 and what they compute

73 of 95 vertex shaders declare `dcl_color0`. In a D3DCOLOR input, `.x=R .y=G .z=B .w=A`.
"COL" below is the COLOR0 input register.

| Family (defines) | Instructions that read COLOR0 [bytecode] | Meaning |
|---|---|---|
| **DeferredMain2VS** `VERTEX_COLORS` (rigid / `SKIN`, with or without `TANGENTSPACE`) | `mul o1.w, c11.x, COL.w` · `mov o1.xyz, COL` | TEXCOORD0 = (r, g, b, a·`$alphaFactor`) |
| DeferredMain2VS without `VERTEX_COLORS` | COLOR0 not declared; `mad o1, c11.x, (0,0,0,1), (1,1,1,0)` | TEXCOORD0 = (1, 1, 1, `$alphaFactor`) |
| DeferredMain2VS `TERRAIN` | `add r0.x, -c10.x, COL.w` · `slt o1.w, abs(r0.x), 0.001` (+ `mov o1.xyz, COL` with `VERTEX_COLORS`) | alpha is a terrain **layer id** compared with `$terrainTextureNr`; terrain format only |
| DeferredMainVS `VERTEX_COLORS` | `mov o1, COL` | TEXCOORD0 = rgba |
| MainVS (forward) | `mov o1, COL` (always declared; `TERRAIN` variants as above) | TEXCOORD0 = rgba |
| MainVertexLightVS | `mul o1.w, c9.w, COL.w` · `mov o1.xyz, COL` | rgba, alpha scaled |
| SimpleLightVS | `mul o1.xyz, r0, COL` | vertex light × rgb |
| HairVS, GlassWaterVS, TexturingVS, SkyBoxVS, FixedFunctionVS, DbgVS, HelperVS | `mov o1, COL` / `mov oD0, COL` | passthrough |
| GrassVS, GrassDepthVS | `mul r1, c6.x, COL` → `frc` → `mova` → `c44[a0.w]` | ×256, used as **array indices** into `$grassData` (grass system, not `.model`) |
| ParticleVS | `mul r2, c10, COL` | particle colour |
| ShadowVolumeVS `SKIN` | `mul r0, c11.x, COL` → bone indices | format 10's bone-index quad, not a colour |

The matching pixel shaders, per channel [bytecode]. `v0` is TEXCOORD0:

```
DeferredMain2PS  [SPECULAR;TANGENTSPACE]  (last 8 instructions; identical tail in 8 of the 16 variants)
  add r0.xyz, r0, r3            ; ambient + directional + 4 deferred lights
  texld r2, v2, s2              ; $specMap
  mul r1.xyz, r1, r2            ; specular sum * specMap
  texld r2, v2, s0              ; $diffuseMap
  mad r0.xyz, r0, r2, r1        ; lit = light*diffuse + specular
  mul oC0.w, r2.w, v0.w         ; A:   out.a   = diffuse.a * vcol.a (* alphaFactor from the VS)
  mul r1.xyz, r0, v0            ; RGB: tinted  = lit * vcol.rgb
  mad r0.xyz, r0, -v0, c1       ;      fogColor - tinted
  mad oC0.xyz, v2.z, r0, r1     ;      out.rgb = lerp(tinted, fogColor, fog)
```

- **R, G, B** each multiply the same-named channel of the complete lit result: diffuse lighting,
  specular, and the glow/emissive term (`mad r0.xyz, c11.yzw, glow, ...` is added before the multiply
  in the `ALL_ADDITIONAL_FEATURES` variants) and reflections. Fog is applied after.
- **A** multiplies the diffuse texture's alpha. Nothing else reads it.
- Variations: the six wet-surface variants do the same multiply (`mul r0.xyz, r0, v0`) and blend the
  wet/reflection term in afterwards; the `FALLOFF` variants add the falloff/rim term after the multiply
  (`mad r0.xyz, r3, v0, r0`); `UNLIT` variants of MainPS/DeferredMainPS read only `v0.w`;
  `GlassWaterPS [GLASS]` writes `oC0.a = v.a` and ignores rgb.
- All 16 DeferredMain2PS, all lit MainPS / DeferredMainPS, MainVertexLightPS, SimpleLightPS and HairPS
  have the same structure (table of the exact lines per variant in the JSON).
- No shader in the archive uses a model's COLOR0 as an AO factor on ambient only, a texture-layer
  blend weight, a displacement/sway weight or a specular mask. The depth and shadow passes
  (`DepthVS`, `ShadowMapVS`) do not declare COLOR0, so vertex alpha does not affect depth or shadows.

Colour space [trace]: the capture contains no `SRGBTEXTURE` or `SRGBWRITEENABLE` call at all, so
textures are sampled and the result written without gamma conversion. The multiply therefore acts on
display-encoded values.

## 3. Statistics of the stored colours [data]

735 models parsed (5 skeleton models have no stream), 2,578 render buffers, 1.80 M vertices.

| `hasColor`, `hasAlpha` | buffers | content |
|---|---|---|
| 0, 0 | 1,204 | every byte 255 |
| 1, 0 | 1,400 | rgb varies, alpha all 255 |
| 1, 1 | 53 | alpha varies (21 of them with rgb all white) |

The flags match the data with zero exceptions. That is what the mesh builder in the exe computes
[exe, 0x434341–0x43469d]: `hasColor` is cleared when the minimum of all colour components is 1.0,
`hasAlpha` when the minimum alpha is 1.0, and `hasAlpha` forces `hasColor`.

Coloured buffers only (1,289,427 vertices):

| | all | characters + weapons | environments | props + minigames |
|---|---|---|---|---|
| models / buffers | 387 / 1,453 | 39 / 59 | 128 / 994 | 220 / 400 |
| mean R, G, B (0–255) | 214, 215, 216 | 200, 200, 201 | 220, 221, 221 | 192, 191, 191 |
| mean as a factor | 0.84 | 0.79 | 0.86 | 0.75 |
| vertices exactly white | 51 % | 30 % | 54 % | 42 % |
| vertices with r = g = b | 85 % | 48 % | 86 % | 87 % |
| buffers entirely grey | 1,155 | 37 | 823 | 295 |
| buffers with one single colour | 19 | 0 | 11 | 8 |
| median distinct colours per buffer | 9 | 34 | 8 | 11 |

- Per-channel 16-bin histograms are in the JSON. Shape: a spike at 240–255 (55 %), a broad hump at
  176–224, a thin tail to 0 (1.1 % of vertices below 16). The three channels are nearly identical; the
  coloured minority is a slight warm/cool tint (City blocks, NiteOwl, gimp suits, paintings 149/128/110).
- Alpha: 99.7 % of coloured vertices are 255. In the 53 alpha buffers 23 % of vertices are 0–15 and
  70 % are 240–255: a fade to zero at the border. They are decals (`SewerDecal`, `Dirt_Decal_Plane_*`,
  `PlasterDecal*`, graffiti), puddles, wine stains, sky layers, the disco-ball glints, garbage piles, and
  Rorschach's `layer03` / `layer04` (rgb white, alpha 0…255).
- Spatial pattern: smooth along edges (median edge difference 0.31 σ), so painted or baked, not noise.
  No uniform rule: correlation of brightness with height is positive (> 0.2) in 26 % of buffers and
  negative in 26 %; with a concavity proxy it is below −0.2 (darker in creases) in 14 % overall and in
  42 % of the character buffers. It is not a per-material constant (19 buffers only).

Consistency with the shader: a mostly grey 0.5–1.0 factor with white as the neutral value, plus an
alpha that feathers decal borders, is exactly what a "multiply the lit colour / multiply alpha" input
looks like. The 17 % darkening seen with COLOR_0 is the authored look (mean factor 0.84), not an artefact.
What produced the values (baked lighting, AO or hand painting) is **not established** and does not
matter for rendering.

## 4. How a shader variant is chosen

- Render effects are built once by `FUN_00572a7b` (rendereffectmanager.cpp). Each constructor compiles
  its variants through `FUN_00433486(stage, name, defines, profile)`. [exe]
- **REDeferredMain2** (`FUN_00570d06`, vtable 0xA3E81C) holds 12 vertex shaders:
  { –, `SKIN`, `TERRAIN` } × { –, `VERTEX_COLORS` } × { –, `TANGENTSPACE` }.
- Per draw item `FUN_0056bc16` calls `FUN_00569734(skinned, hasColor)` with
  `skinned = (instance+4 == 3)` and `hasColor = *(u8*)(MeshBuffer + 0x31)`. [exe]
  `MeshBuffer+0x31` is the first of the two flag bytes of the file's MeshBuffer header
  (`FUN_004336ec`), `+0x32` is `hasAlpha`.
  - passes 2, 3, 4: the `TERRAIN;VERTEX_COLORS` shader, always;
  - high shader quality: `this+0x58 + 4·hasColor` (rigid) or `this+0x60 + 4·hasColor` (skinned), the
    `TANGENTSPACE` variants;
  - when `FUN_00568974` returns 1 (a global at `FUN_0047afc1()+0x9C` is 0, [inferred] the low shader-quality
    option, or the pass is 0x19–0x1B): `this+0x30/0x38 + 4·hasColor`, the variants without tangent space.
- **REDeferredMain** (`FUN_00570a9a`) does the same in `FUN_0056909a`:
  `this+0x18 + 4·hasColor` (rigid), `this+0x20 + 4·hasColor` (skinned).
- The pixel shader is chosen from the material (texture sheet), not the mesh: `FUN_0056bcb8` picks by
  reflection mode, material type (`sheet+0x60` = 10 or 11) and an "additional features / two-sided" flag.
  Every pixel variant consumes TEXCOORD0, so the vertex shader alone decides whether colour is applied.
- `hasAlpha` (`+0x32`) has no reader in the render path that I could find; only the builder and the
  cloth copy (`FUN_00433c40`) touch it. [exe, by search; not exhaustive]
- Capture [trace]: every model colour-pass draw uses DeferredMain2VS. 5,524 format-5 draws and 1,620
  format-6 draws use the `VERTEX_COLORS` variants, 8,120 and 2,916 the plain ones. No model draw uses
  MainVS or DeferredMainVS in those 410 frames.
- **Which models get a colour-consuming shader:** exactly the buffers with `hasColor = 1`, i.e. the 387
  models listed in the JSON (`coloured_buffers`), per submesh. A model can mix coloured and uncoloured
  submeshes (Rorschach: 2 of 11).
- Not established: which rule sends a material to REDeferredMain2 rather than REDeferredMain / REMain /
  REHair (the capture shows only the first for models), and whether any CPU code reads the colour bytes
  at run time (none found; cloth setup was not traced vertex by vertex).

## 5. Tangent space, culling, winding

Vertex shader [bytecode]:

- Rigid `TANGENTSPACE`: `mov o2.xyz, v1` (normal), `mov o5.xyz, v4` (TEXCOORD1 = tangent),
  `mov o6.xyz, v5` (TEXCOORD2 = bitangent). Raw, object space, no normalisation.
- Skinned: each of the three is transformed by the blended 3×4 bone matrix and normalised on its own
  (`dp3 ×3, dp3, rsq, mul`). No cross product.

Pixel shader [bytecode]:

```
texld r0, v2, s1                 ; $normalMap (two-channel)
mad r0.xy, r0, 2, -0.996078      ; x, y = 2*tex - 254/255
mul r0.xy, r0, c11.x             ; * $effectFactors.x (bump strength)
mul r1.xyz, r0.y, v5             ; y * BITANGENT (stored)
mad r1.xyz, r0.x, v4, r1         ; + x * TANGENT (stored)
dp2add r0.x, r0, -r0, 1 ; rsq ; rcp   ; z = sqrt(1 - x² - y²)
mad r0.xyz, r0.x, v1, r1         ; + z * NORMAL
nrm r1.xyz, r0                   ; then * $worldMatIT
```

So the frame is whatever is stored. `TWO_SIDED` variants add
`cmp r, vFace, 1, -1` / `cmp n, -r, n, -n` / `mul n, n, c7.w`: the normal is negated on faces with
`vFace ≥ 0` and multiplied by a per-draw sign in `$camPosWS.w`.

Stored data [data, 1.80 M vertices, 1.40 M triangles]:

- Tangent and bitangent are unit length (0.9992–1.0000).
- Stored tangent agrees with the geometric ∂P/∂u on 97.5 % of triangles, stored bitangent with
  **+∂P/∂v** on 97.5 % (0.3 % disagree, rest degenerate UVs).
- `sign(dot(cross(N, T), B))` is + on 66.5 % and − on 33.0 % of vertices (mirrored UV islands).
- Not orthogonal: |N·T| > 0.1 on 9.5 %, |T·B| > 0.1 on 13.9 %; B is more than 10° away from
  ±cross(N, T) on 15.5 %. (The 29 % in the task presumably uses a tighter threshold.)
- 99.85 % of triangles wind clockwise against their normals under a right-handed cross product.

Culling [exe]: the render-state cache stores the cull mode in bits 4–7 of `state+0xB8`
(`FUN_0042aa66`) and passes it unchanged to `SetRenderState(D3DRS_CULLMODE = 0x16, v)` (state flush in
part_0002.c near 0x4590xx). `FUN_00571d5d` sets 1 (`D3DCULL_NONE`) when the texture sheet's two-sided
byte (`sheet+0xA4`) is set, otherwise the value on the state stack. [trace] confirms: model draws use
`D3DCULL_CW` (2) or `D3DCULL_NONE`; `D3DCULL_CCW` occurs only for light volumes.

Interpretation [inferred, consistent with the existing "export is a mirror image" finding in
ANIMATION_META.md]: `D3DCULL_CW` keeps triangles that are counter-clockwise on screen. The file's
triangles are clockwise in a right-handed reading, so the engine's space is left-handed and its front
faces are the ones whose stored normal points at the viewer. Front face = the side the normal is on;
there is no inverted-normal convention.

## 6. Recommendation for the glTF export

| Attribute | Verdict | Details |
|---|---|---|
| **COLOR_0** | **Emit, transformed**, only for buffers with `hasColor = 1` | rgb: `srgb_to_linear(c/255)` as float (or normalised u16); a: `c/255` unchanged. Reason: the engine multiplies display-encoded colour by `c`; glTF multiplies linear base colour, so a raw 0.5 would darken too little. With the conversion a diffuse-lit surface shows the same displayed factor. Do not emit for `hasColor = 0` buffers (they are all white anyway). |
| alpha of COLOR_0 | **Emit as is**; needs the right material | It multiplies base-colour alpha, which is what glTF does. The 53 `hasAlpha` buffers need `alphaMode: BLEND` (decals, puddles, sky, Rorschach layers) or they will render as opaque quads; `hasAlpha` is a usable trigger for that. |
| `_COLOR_RAW` | Optional custom attribute | Keep the untouched bytes if a round trip matters. Not needed for rendering. |
| **NORMAL** | **Emit as is** | Unit, used directly by the shader. |
| **Winding** | **Keep the current flip** (or mirror one axis and keep indices) | Coordinates are written unmirrored into a right-handed format, so indices must be reversed to make the normal side the front. Equivalent and more faithful to handedness: negate X on positions, normals and tangents and keep the indices. Two-sided sheets → `doubleSided: true`. |
| **TANGENT** | **Emit xyz as is (stored, unit); w needs care** | glTF builds `B = cross(N, T)·w`. The engine uses the stored bitangent, which is +∂P/∂v. Let `s = sign(dot(cross(N, T), B_stored))` computed on the numbers as exported. If the normal texture is exported **unchanged**, `w = s`. If the exporter **flips the green channel** (the toolkit's default "gl" mode), `w = −s`. If X is mirrored instead of flipping indices, negate once more. |
| `_BITANGENT` | Optional custom attribute | Only a custom shader can reproduce the engine exactly on the ~15 % of vertices whose stored bitangent is not ±cross(N, T). Do not orthogonalise by default: the engine does not. |

Things to verify on the toolkit side:

- `watchmen_extract.gltf_tangents` returns `w = s`. `char_lib` flips green by default. If both are active
  in the same GLB the bitangent term is inverted on every vertex (bumps read as dents along V). The
  algebra above is from the bytecode; I did not render a GLB to confirm which combination the writer
  actually ships.
- The 17 % darkening is real engine behaviour. Switching COLOR_0 off makes those 387 models brighter
  than in game and removes the decal edge fades.

What a faithful material needs beyond glTF's model:

- The tint also scales specular, glow/emissive and reflections; glTF's COLOR_0 scales base colour only.
  For exact parity scale `emissiveFactor`/specular by the same factor in a custom shader, or accept the
  difference (it only matters on glossy, strongly tinted vertices).
- The falloff/rim term is added untinted.
- The engine lights in gamma space; no transform of one attribute makes a linear-light viewer match exactly.

## 7. Not established

- The rule that routes a material to REDeferredMain2 versus the other render effects.
- 19 shader define sets (none of them a model vertex shader in the capture); two deep-search matches
  may be hash collisions.
- Any run-time CPU reader of the colour bytes (none found).
- The authoring origin of the colours (bake vs paint).
- Console shader archives were not examined.
- The handedness statement rests on the cull state plus the measured winding, not on a traced
  projection matrix.
