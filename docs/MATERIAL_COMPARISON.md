# Exported materials beside captured game frames

One measurement, made on 2026-10-07 on the PC Part 2 export
(`characters_v1.4.0/*.glb`, `--materials engine`) and three frames of the
Bordello capture `KapowMulti.1.trace` (see `tools/apitrace/README.md`). The
scripts and pictures are not part of the toolkit.

## Method

- Frames 5760, 6300 and 2508 (Dominatrix from behind; Rorschach and a
  Dominatrix; Nite Owl, Rorschach and two Gimps). The screenshot named by the
  call number c of a `Present` is the frame `atx dump F-1 F`, where the index
  line of F has `next_call` = c + 1.
- Textures of a draw were identified by the CRC-32 of the level-0 upload
  against the level-0 bytes of the export's `.bmp.stream` layers (1,188 of
  1,373 textures of the capture). A draw was paired with a GLB primitive by
  diffuse texture name and triangle count.
- Pose: the bone palette of the draw (VS c40, 3 rows per bone) applied to the
  GLB primitive, joint index = palette index, x of the GLB negated to get the
  engine's numbers; the head's palette holds the face skeleton's bones in the
  order of the face skin's joints. Placement: VS c4–c7. Camera: the
  view-projection matrix is inv(c4–c7) · c0–c3 of a static draw (vertical
  field of view 45°, near plane 0.1 m), position PS c7.
- Lights: PS c0 (ambient 0.216, 0.265, 0.300 in all three frames), no
  directional light, and the positional lights of `Deferred render lights`:
  index from `$lightIndexColor` · 255, position and brightness from row
  index of `$LPT`, colour from `$LCT`, range and start of the linear
  attenuation from `$lightAttnData` (x = −1 / (range · (1 − attnStart)),
  y = 1 / (1 − attnStart)), cone from `$lightAxisVS` and c3.zw of the spot
  variant. Shadows are not in the trace as numbers and were left out.
- Post-processing: the constants of `PostProcessPS` in the frame (bloom
  weight 0.2, brightness 0.1, saturation 0, contrast 0.33, tint
  (0.54, 0.693, 1.0) × 0.3, exponent 0.7576) and of the bloom control
  filter (0.1, 0.5). The chain was inverted on the game frame, the render put
  over the result and the chain applied again; outside the characters the
  round trip differs from the frame by 0.04 to 0.13 of 255.
- Two renders of the same geometry: (a) the engine's lighting equation of
  `ENGINE_CONSTANTS.md` evaluated per pixel with the constants of each draw,
  the export's texture layers, the sheet's falloff gradient and the cube map
  the draw binds; (b) the GLB in Blender 3.6.0 (Cycles, 128 samples, Standard
  view transform, Principled BSDF). The glTF importer of 3.6 drops
  `KHR_materials_specular.specularFactor`, so the script set Specular =
  F0 / 0.08 with F0 = ((ior − 1) / (ior + 1))² · specularFactor ·
  specularColorTexture, as the extensions define it. Light levels were
  converted from the engine's display values with the sRGB curve. Blender
  4 and 5 were not used.

## Result

Mean absolute difference to the game frame over the character pixels, of 255:

| frame | character pixels | engine equation | GLB in Blender 3.6 |
|---|---|---|---|
| 5760 | 94,008 | 2.4 | 13.3 |
| 2508 | 166,646 | 5.0 | 11.1 |
| 6300 | 212,759 | 12.3 | 23.5 |

Frame 6300 has a hit flash and the animated ink blots of Rorschach's mask in
front of the characters; neither is in the renders.

The equation and the constants of the trace reproduce the frame. What the GLB
in a linear-light viewer shows differently (frame 5760 unless stated, colour
before post-processing, mean / 99.5th percentile of luma):

| material | game | GLB | what the equation says |
|---|---|---|---|
| skin (`FemaleSkinBody_White [Black]`) | 0.142 / 0.199 | 0.127 / 0.257 | diffuse 0.136, 0.103, 0.084; falloff term 0.055, 0.033, 0.024; highlight below 0.007. The same diffuse product computed in linear light is 0.119, 0.079, 0.058 |
| skin, frames 6300 and 2508 | 0.152, 0.127 | 0.068, 0.077 | as above; without a positional light near the character the GLB is at half the level |
| latex (`DominatrixSuits2`) | 0.071 / 0.155 | 0.075 / 0.220 | diffuse 0.016; cube map 0.022; falloff term 0.039; highlight 0.001 (99th percentile 0.011) |
| hair (`GogoHairAfroBlack`) | 0.022 / 0.027 | 0.028 / 0.435 | diffuse only; the GLB has F0 0.14 × its specular texture and shows glints at grazing angles |
| leather hat (`RorschachHatDry`, 6300) | 0.042 / 0.112 | 0.041 / 0.418 | `reflectionLightFactor` 2.0, `specularPower` 10: GLB F0 0.32 |
| cloth (`RorschachTrenchcoatDry`, 6300) | 0.041 | 0.017 | diffuse 0.03, 0.024, 0.019; in linear light 0.009, 0.007, 0.005 |
| cloth without highlight (`RorschachTrouserDry`, 2508) | 0.030 | 0.004 | diffuse 0.019 + falloff 0.005; in linear light 0.005 |
| suit (`NightOwlMasktoBodyDry`, 2508) | 0.079, 0.070, 0.059 | 0.056, 0.062, 0.069 | diffuse 0.064, 0.052, 0.041; cube map 0.008, 0.012, 0.012. The GLB (F0 0.245 × texture) takes the colour of the surroundings |
| buckles (`ACCGenericBelt`) | 0.064 / 0.231 | 0.070 / 0.497 | |

The Blender column depends on the light levels chosen for Blender as well
as on the materials: the same skin material renders at 0.127 in frame 5760
and at 0.068 in frame 6300, where the game shows 0.142 and 0.152 and the
engine's light term is almost all ambient in both. The readings of frames
6300 and 2508 therefore measure those light levels at least as much as the
materials.

Three properties of the engine differ from what a linear-light viewer does
with the GLB:

1. Lighting is computed on display values. Albedo × light of two small
   numbers lands on the linear toe of the sRGB curve, where the same product
   in linear light is several times darker; no choice of light level corrects
   dark and bright albedos together.
2. The falloff term is added after the albedo: falloff gradient(N·V) ·
   `fallOffPower` · (ambient + directional + positional diffuse + positional
   specular + `fallOffColor`), not multiplied by vertex colour. With
   `fallOffColor` white it is close to a constant glow in the colours of the
   gradient (a quarter to a half of what skin and latex show in these
   frames). The GLB carries the parameters in `extras` only.
3. Only positional lights give a highlight, without Fresnel and scaled by
   N·L. A GLB specular reflectance fitted to the peak of that highlight also
   reflects the surroundings, rises towards grazing angles, and is the larger
   the broader the lobe is.

Not covered: glass, emission (no draw of the three frames has
`selfIlluminance`), blended materials, any other viewer, Blender 4 or 5.

## What follows for a comparison

- The game lights in display space (property 1). The display-space equation
  gives skin in frame 5760 as (0.188, 0.134, 0.107) against the game's
  (0.187, 0.133, 0.106); the linear product would be (0.119, 0.079, 0.058)
  before the falloff term (measured). No sRGB sampler or render state is set
  anywhere in `KapowMulti.1.trace` (4,906,084 state calls, measured). Compare renders with the game under
  Blender's Standard view transform; Filmic and AgX add a tone curve the game
  does not have.
- Blender 3.6 (`io_scene_gltf2` 3.6.27) does not use
  `KHR_materials_specular.specularFactor`: the untextured branch computes
  Specular from the specular colour and the IOR only, which gives 0.5 at IOR
  1.5 (read from the importer's source). That the textured case is routed
  into Metallic was not found there: the socket passed is
  `inputs['Specular']` (`gltf2_blender_pbrMetallicRoughness.py`, line 165).
  three.js and Blender 5.0.1 import both extensions (README, "Materials").

## Open proposals

None of these is implemented; the material writer is unchanged. Each was
checked against the shader text and the numbers above.

| # | Proposal | Verdict | Reason |
|---|---|---|---|
| 1 | Emit the light-independent part of the falloff term for sheets with `fallOffColor` above 0 | CONFIRMED for the mechanism; the stated effect is WEAK | The shader line `mad r0.xyz, r1, c14, r0` adds gradient · power · colour with no light in it (read from code). The size is not established: the light-independent share is about 77 % of the term, roughly +20 % on skin, not 30 %; in frame 5760 it would overshoot red (export 0.176 + 0.042 against the game's 0.187). No render was made. The light-independent part is exactly gradient(N·V) · `fallOffPower` · `fallOffColor`; the light-dependent part multiplies the same gradient by ambient + all lights. |
| 1b | `sheen=1` for sheets with `fallOffColor` 0 | NOT SUPPORTED | No measurement |
| 2 | Cap the peak-fitted F0 at about 0.08 | WEAK | The direction is supported by hair (99.5th percentile 0.435 against 0.027) and the hat (0.418 against 0.112). The cap would not touch belt or latex (F0 0.10, still 0.497 against 0.231), and on the coat (F0 0.213) and Gimp skin (0.149) the export's highlights are already below the game's, so it moves them the wrong way. The value 0.08 is a guess |
| 3 | Treat `reflectionLightFactor` above 1 as 1 | NOT SUPPORTED | The shader does not clamp: the weight is specTex × 2.0. A per-texel min(1, factor × specTex) would follow the shader; this proposal does not. The weight is specTex · factor, unclamped; where it exceeds 1 the lit albedo gets a negative weight. |

Not proposed: removing Fresnel through `KHR_materials_ior` 0 (allowed by the
specification, untested in any importer).
