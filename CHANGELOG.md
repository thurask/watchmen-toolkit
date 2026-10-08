# Changelog

## 1.4.0 — 2026-10-08

Much of what the toolkit writes changes. **The export is no longer a
mirror image.** The engine is left-handed; 1.3.0 wrote its numbers verbatim
into right-handed glTF, so every viewer showed the game mirrored: a wall
sign read backwards and a character's left hand was on its right. Every GLB
and OBJ, and every number given in their frame, is now true-handed — the
data itself is reflected, no node is scaled — and `--frame mirrored` writes
the 1.3.0 frame. **The GLBs carry the meshes' own
shading data** — normals, tangents, vertex colours — after the game's shaders
were disassembled and the result rendered against the engine's pixel math.
That test found that **every PC normal map extracted so far has its X and Y
channels swapped**; this is fixed and cannot be switched off. **Jiggle bones
are baked with a new model, `solver`**, which steps PhysX 2.8.1's own
arithmetic for the joint's soft swing limit, read from `PhysXCore.dll`, with
the constants of the game files only, and closes looping clips into one
seamless lap. **Faces follow the game's own rule**: every body clip carries
the face poses the game shows with it, read from the face animation classes,
in place of a pose guessed from the clip name and invented blinks, and five
more characters get the game's face-rigged head. And **textures are found by
the path the model stores**, not by the first folder with that name, which
gives Rorschach his face. **A character GLB shows one outfit and no weapon**,
as the game does, where it used to show every hairstyle, jacket and weapon
of a variant at once; the other outfits and the weapons stay in the file as
switched-off nodes. **Each part wears the texture sheet its outfit selects**
(the Heavy's jacket and button colours, the KnotTops' T-shirts). And
**`extract --glb` honours a sheet's blend type**: Rorschach's ink blots and
additive light layers are no longer written as plain textures. **Materials
are derived from the game's own shader**: roughness and specular strength
from the sheet's specular exponent and intensity, no highlight where the
game has none, nothing metallic. **Each character GLB carries its ragdoll
rig** as hidden helper nodes, with a `.ragdoll.json` beside it. And **music
is written one file per track**, 35 stereo sounds get their real sample
rate and 50 PCM sounds their first four bytes back. And **`.particle.json`
is the engine's own tree**, every class and property named, in place of a
flat block list.

Six exports are new and change nothing that was written before. **The combat
rules are data**: every attack state's damage, timings, reach and counter
window, every pair's trigger, the combo databases and AI reaction tables, in
`anim_meta.json`. **Effects, the finisher cameras and rumble** are in the same
table: the cameras turn out to be procedural, placed by a rule from the two
characters' positions, and the rule is exported with every cut. **Levels**
come out as one JSON each — placements with glTF transforms, the trigger
graph, checkpoints, camera tours — and save files can be read. **Every text
table in five languages**, with the subtitles joined to the voice lines.
**The particle format** is read from the engine's loader. And **the
navigation mesh and graph** of every level are decoded to the last byte and
written as JSON and GLB.

The exports state the engine's rules where the executable gives them, each
read from the code and compared with the game data: a thrown enemy is
hurt by ragdoll contacts and by nothing else; a blend without a control
parameter plays its first child alone, which is the answer to the attack
face; the idle face starts in a random member; the finisher camera does not
follow the action, only its aim does; a pair's bodies turn with their
`GamePivot`; a material's alpha mode comes from the render list, and for a sky
sheet from its opacity; which
model and weapon a placed enemy gets is fixed by the level file for some and
a least-used pick for the rest; a `PASSIVE` enemy neither chases nor
attacks; the cutscene subtitle tables belong to their movies; a path
object's id names its level node; and the property dictionary spells the
names the engine's classes register the way they register them.

The toolkit reads six game sets — Parts 1 and 2 on PC, Xbox 360 and PS3 —
and the outputs of the three platforms of a part are compared with each
other. The items marked "Parts 1 and 2 on all platforms" below are the
faults that comparison shows in what 1.3.0's readers give, most of them on the console
sets and on the standalone Part 1: console characters have all their parts
and their ragdoll rig, PS3 sounds have a length, Xbox 360 sounds decode,
Xbox 360 textures have all their layers, cube maps have six correct faces
on every platform (PC included), Part 1's Prison level has the 70 assets it
keeps in separate stream files, the standalone Part 1 has its texture
sheets, and the `instances` section of a fragment JSON no longer invents
text. **The formats that were raw only are decoded**: `.font`, `.scene`,
the whole `.terrain` (with a height map and a surface GLB), Part 1's
`.terraincoloringasset` and the last bytes of `.detailmesh`. **The model
header of the stand-alone Part 1 is read**, which gives PC and Xbox Live
Part 1 their ragdoll rigs and full model sidecars. **Console models are
decoded from their header** like the PC ones, so they get a GLB each, with
normals, tangents and vertex colours. What a set does not decode is said in
the log and in the output, and tabulated in the README ("Platform
support").

More of what 1.3.0 wrote changes: **Models made of several rigid
parts are assembled** (1.3.0 wrote every part at the model origin).
**Texture layers are named by their file slot**: a glow map and a height
map are no longer written, and used, as specular colour and specular power.
**The clip baker follows the engine's rest-pose rule**, which moves 7 clips,
**and applies the engine's twist-bone pass, binding Part 2 tracks by exact
name.**
**Console vertex colours are decoded on every model.** **Character GLBs
have 0 in unused joint slots**, and **`.fragment.json` keys are spelled as
the engine registers them** (letter case only); the MTL files, the loop
flag of clips and `watchmen char` change in smaller ways. The rest adds keys: sound
events and loop flags in `anim_meta.json`, more combat, camera and effect
rules, AI sight, forced states and cube maps in the level files, mesh-link
gates in the navigation files, speech and music rules in `sound_meta.json`,
subtitle routes in `text_meta.json`, cloth in the ragdoll files.

Measured on a full export of the six sets on Windows (54 steps, every exit
code 0, no `WARNING:` line in any log; the counts are in the README,
"Platform support", and under "Tests", "Six-set export"). Where a number
comes from single blocks, levels or functions instead, its item says so.

The changes that alter output are listed first, each with how to get the
1.3.0 result and what cannot be brought back. In short: `watchmen characters …
--frame mirrored --jiggle-model pinned --face-rule legacy --no-vertex-attrs
--parts all --materials legacy --no-ragdoll` writes the animation, skin and
mesh data of 1.3.0 (`--frame mirrored` also belongs on `extract`, `all`,
`char`, `charlibs`, `faces` and `animmeta` for their 1.3.0 files); the corrected normal maps, the texture choice, the texture sheets,
the clip baker's rest-pose rule, twist pass and track binding, the header
rate of the walk and run cycles and one corrected sentence in the metadata
stay. For audio, `extract …
--flat-music` writes music as 1.3.0 did; the corrected sample rates and PCM
offsets stay. `extract … --no-text --no-nav` leaves the two new folders out;
the new `.particle.json` layout and the added metadata keys have no switch.

### Behaviour changes

- **GLBs, OBJs and all data in their frame are true-handed; the 1.3.0 frame
  is `--frame mirrored`.** The engine's coordinates are left-handed (+Y up,
  characters face +Z, a character's left hand at −X). 1.3.0 wrote them
  unchanged into right-handed glTF, which every viewer and Blender show as a
  mirror image, and told the reader to mirror X and swap L / R. The default
  frame is now x = −engine x, right-handed, with +Y up and "facing +Z" kept:
  text reads the right way round, a character facing +Z has its left hand at
  +X, and the bone names `L` / `R` are truthful. Nothing has to be mirrored
  by the consumer any more.
  - *What is reflected.* The data, never a node scale: positions, normals
    and morph deltas (x negated), TANGENT (x negated and **w negated** — glTF
    rebuilds the bitangent as cross(N, T) · w, and a reflection reverses the
    cross product), inverse bind matrices and node matrices (S M S with S =
    diag(−1, 1, 1), which stays a proper rotation), node and animation
    translations (x negated) and rotations ((x, y, z, w) → (x, −y, −z, w)),
    accessor bounds, and the triangle winding (reversed against the mirrored
    file). Scales, UVs, colours, weights, joints and times are the same
    bytes. One function does it on the finished document
    (`frame.reflect_gltf`), for every writer: `extract --glb`, `characters`,
    `char`, `charlibs`, `faces` (body, weapons, the switched-off outfit and
    alternative nodes, the face skin, the baked jiggle and face channels,
    the ragdoll helper nodes) and the navigation GLB.
  - *Winding.* The game draws one-sided materials with `D3DCULL_CW`, and its
    triangles wind clockwise against their normals in a right-handed reading
    of the numbers. With x negated the file's own index order is
    counter-clockwise seen from the normal side, i.e. glTF's front face: in
    the true frame the triangles are written in file order, where the
    mirrored frame needs the reversal described below. Primitives without
    NORMAL (`--no-vertex-attrs`, console and Part 1 models) are in file
    order in both frames: front-facing in the true one, back-facing in the
    mirrored one as in 1.3.0. Generated ragdoll proxy meshes (`RB.*`, no
    NORMAL) are wound outward in both frames, so their index order is
    reversed between the frames as well. OBJ: `v` / `vn` with x negated, faces in file
    order; the true OBJ winds with its normals, the mirrored OBJ (and
    1.3.0's) against them.
  - *Data that follows the GLBs.* `anim_meta.json` and the animation extras:
    `clips[*].game_pivot` / `interact` (`pos_start`, `pos_end`,
    `yaw_start_deg`, `yaw_end_deg`) and `pairs[*].placement` (every `*_xz`
    pair, `partner_yaw_deg`, `check.partner_game_pivot_start_xz`): x and yaw
    change sign. The yaw numbers are the engine's heading angle, as in
    1.3.0, which is the opposite of the right-handed angle of the GLB's own
    node rotation: a value *a* is a rotation of −a about +Y in the file, in
    both frames (measured on Rorschach: all 48 `game_pivot` and 111
    `interact` yaws that are not 0 or ±180). In the true frame a positive
    yaw turns +Z towards −X, the character's right. `conventions.yaw` of a
    true-frame table says so. `<Variant>.ragdoll.json` and the ragdoll extras in the GLB:
    every position, quaternion, frame axis, matrix and convex-mesh vertex;
    the limits keep their values, the asymmetric twist range included (a
    frame F becomes S F S, about whose twist axis a turn keeps its sign;
    swing limits are symmetric). `<Level>.level.json`: `gltf`, `forward` and
    `yaw_deg` of every placement. `<Level>.nav.glb`.
  - *Data that stays in engine coordinates* (left-handed, labelled as such):
    `world.pos` / `world.quat` and every other position of the level JSON;
    the whole `<Level>.nav.json`; in `anim_meta.json` the values copied from
    the game files — a state's `impact.position` / `direction`, event
    payload vectors, the effects' `local_position` / `local_direction` /
    `local_orientation`, the camera-cut parameters and the formulas of
    `fx.camera.cut_placement`, the camera rig, sweep angles,
    `face.attachment.head_model_yaw_deg` (`conventions.engine_values` lists
    them; `fx_meta.cut_camera(..., frame="true")` takes and returns
    true-frame positions); particle, fragment and skeleton JSON.
  - *Marker.* A true-frame file says so: GLB
    `asset.extras.watchmen.coordinate_frame = "right-handed-true"` (with a
    one-sentence `coordinate_frame_note`), the same key at the top of
    `anim_meta.json`, `*.ragdoll.json`, `*.level.json`; a comment line in an
    OBJ; `conventions.glb_frame` in `*.nav.json`. **A file without the key
    is in the mirrored frame** ("engine-mirrored"): that covers everything
    1.3.0 wrote, including `anim_meta.json` with its unchanged format string
    `watchmen-anim-meta/2`. No format string changes.
  - *Blender.* Its importer maps glTF (x, y, z) to (x, −z, y): a character
    stands on +Z, faces −Y (towards the front view) and has its left side at
    +X, Blender's own convention for `.L`. Checked with Blender 5.0.1 on a
    real Dominatrix: `L Hand` at x = +0.577 (mirrored frame: −0.577), no
    object with a negative scale. Checked again with Blender 5.2.2 on
    exported files (Dominatrix_1, Rorschach, six model GLBs): `L Hand` x =
    +0.577 / +0.518, toes at −Y of the ankle, no negative scale, four signs
    read correctly.
  *1.3.0 output:* `--frame mirrored` (or `WATCHMEN_FRAME=mirrored`) on
  `all`, `extract`, `characters`, `char`, `charlibs`, `faces`, `animmeta`,
  `fxmeta`, `levelmeta`, `navmeta`, `ragdoll`; a usage error elsewhere. The
  files then carry no marker and are byte-identical to what the toolkit
  wrote before the option existed. **Every "*1.3.0 output*" note below that
  concerns a GLB, an OBJ or `anim_meta.json` assumes `--frame mirrored` in
  addition to the switch it names**, and the counts and byte comparisons
  quoted in this entry were made on the engine's numbers, which is that
  frame. A resumed `characters` run rewrites a GLB or `anim_meta.json` it
  finds in the other frame, so one folder holds one frame.
  Established: on 28 synthetic output files of every kind (GLBs of both
  writers, OBJ / MTL, `anim_meta.json`, effects, level, navigation and
  ragdoll JSON) and on real Part 2 PC data (three street-sign models: GLB,
  OBJ, MTL; a Dominatrix library GLB; `animmeta`, `levelmeta` on six
  levels, `navmeta` and `ragdoll` on a staged part of the extract, 13
  files) `--frame mirrored` is byte-identical to the same code without the
  frame conversion, and the sign files are byte-identical to the ones the
  installed toolkit had written. That is what the option promises: the
  engine's numbers, placed as 1.3.0 placed them. It is not a promise about
  materials: the rule for materials without a highlight (below) applies in
  both frames. Between the two frames those 13 JSON files differ
  only in the keys named above, each by exactly its rule (2,932 values in
  `anim_meta.json`, 345 in the ragdoll file, 24,934 in the level files;
  none anywhere else). True against mirrored on real
  data: the Dominatrix library GLB written in both frames (11 poses), and
  two full character exports reflected with the writers' own pass —
  `Dominatrix_1` (202 animations, 36 mesh nodes of which 34 hidden, two
  skins, 405 poses) and `Rorschach` (295 animations, 45 mesh nodes, 591
  poses): the skinned positions of every mesh node, ragdoll proxies
  included, are exact reflections in the bind pose and at every sampled
  key, maximum deviation 0. A stop sign rendered in Blender reads "STOP" in the true
  frame and mirrored in the other.
  The full Part 2 PC outputs written in the true frame were compared with
  the mirrored ones, by a checker that
  does not use the toolkit's reflection code:
  - *Characters* (26 GLBs, 5,731 animations): the binary chunk of every
    GLB is byte for byte the reflection of the mirrored file's — positions
    (953,256 values), normals, tangents with `w`, 418,996 triangles
    (index order), inverse bind matrices, 734,120 animation output accessors
    (translation and rotation), maximum deviation 0 in every class; times,
    UVs, colours, joints and weights unchanged. Node transforms and the
    extras differ by their rules only, and nothing else differs. Skinned
    world positions at four poses per character (104 samples, 1,693,000
    vertices): deviation 0. The 26 ragdoll files and `anim_meta.json`
    differ only in the keys named above, each by its rule;
    `sound_meta.json` is byte-identical. glTF-validator: 0 errors and the
    same issue counts in both frames (the counts themselves are under
    "Fixed": the validator item).
  - *Models* (738 GLBs, 738 OBJ): every GLB binary chunk is the exact
    reflection, every OBJ has `v` / `vn` x negated and nothing else
    changed but the marker line (1,599,177 vertices); the 738 `.mtl` and
    738 `.model.json` are byte-identical in both frames. The
    counter-clockwise triangle normal agrees with the vertex normals on
    1,284,805 of 1,286,000 triangles (99.907 %) in the true GLBs; in the
    OBJ on 1,284,790 (mirrored OBJ: 799). glTF-validator: 0 errors, 92
    warnings, 1 info, as in the mirrored set.
  - *Levels and navigation*: in the six level files all 20,019 `gltf`
    transforms satisfy S M S exactly and every `world` value is unchanged;
    the five `.nav.glb` are exact reflections, their `.nav.json` differ
    in three convention entries.
  - *Not affected by the frame*, checked on the real archive with the
    default frame: the 67 music tracks and sidecars, 226 text files and 5
    skeleton files of a plain run, 1,099 of the extract's JSON files and
    2,085 texture files of 409 textures are byte-identical to the mirrored
    extract.
  - *`--frame mirrored` on the same data*: all 2,952 model files, six
    character GLBs with their ragdoll files, `anim_meta.json`, the ten
    navigation files and the six level files are byte-identical to the
    mirrored outputs. Those mirrored outputs and this comparison were made
    before the rule for materials without a highlight, which is the same in
    both frames; a mirrored file written now differs from them in exactly
    those materials. Checked with the rule on two characters (`Heavy`,
    `TwilightLady`, `--frame mirrored`): every accessor byte-identical to
    the earlier mirrored GLB, the ragdoll files and `anim_meta.json`
    byte-identical, and in the GLB only the 4 and 1 materials without a
    highlight differ. The comparisons of the true frame above were made
    before that rule and before `conventions.yaw` as well: the final
    true-frame GLBs differ from the ones compared there in those materials
    and that text only (see "Materials follow the game's shader").
  - Rendered through Blender's glTF importer, the fire-extinguisher sign,
    a "Strigidae Industries" sign, a "No Trespassing" plate and a poster
    read correctly in the true frame and mirrored in the other; with back
    faces made invisible nothing is missing in either.
  Not established: a level assembled from true-frame files in a viewer,
  and `--frame mirrored` on Windows. (Part 1 and the console sets are
  exported in the true frame, on Windows, in the six-set export under
  "Tests".)

- **PC normal-map PNGs: X and Y were swapped; fixed.** A Direct3D 9 `ATI2`
  layer stores the Y block first and the X block second. The decoder wrote
  the first block to red, so every `*_normal_*_ATI2.png` extracted from a PC
  archive by 1.3.0 or earlier has X in green and Y in red; no green flip or
  tangent sign repairs a transposed map. The PNGs now have X in red and Y in
  green, and everything built from them changes with them: the normal
  texture embedded in the character GLBs and the image an OBJ's `map_Bump`
  points to. Measured against the engine's pixel math, median angle between
  the shading normals (three.js / Blender): 1.3.0 character GLBs 14.4° /
  17.0° (`Fimale_GimpSuit_01`) and 12.2° / 13.9° (`NightOwl_No_Mask`); with
  the fixed map and the new attributes 1.1° / 1.4° and 1.1° / 1.0°. X360 and
  PS3 extractions were already in the right order and do not change.
  *1.3.0 output:* not available. There is no switch, and `--no-vertex-attrs`
  does not affect it. **PNGs written by an earlier version are wrong and stay
  wrong until the textures are extracted again**; nothing in a PNG says which
  version wrote it. Run `extract` again before `characters`, `char`,
  `charlibs` or `faces`: a character GLB built from an old texture tree
  combines the new tangents with a transposed map, and finds no `sheet.json`.

- **`extract --glb` writes a GLB for every header-decoded model**, not only
  for fully skinned ones: 735 instead of 130 on Part 2 PC. Rigid models get a
  static GLB (mesh and materials, no skin). **Those GLBs carry NORMAL, TANGENT
  and COLOR_0, corrected winding and sheet-driven materials.** NORMAL is the
  stored normal. TANGENT is the stored tangent with w = −sign(dot(cross(N, T),
  B)) on the engine's numbers (the true frame negates x and w, see above),
  written for materials that have a normal map. COLOR_0 is written only
  for mesh buffers whose `hasColor` flag is set, as float, rgb converted sRGB
  → linear, alpha as stored. The normal side is glTF's front face: in the
  mirrored frame a primitive that gets NORMAL has its triangles reversed
  when they wind against the normals (the game's triangles are clockwise
  against them in those numbers); in the true frame the file order already
  is the front face. Materials
  follow the texture's `sheet.json` (this paragraph describes the writer
  that `--materials legacy` now selects; the default is described under
  "Materials follow the game's shader"): `doubleSided` is the sheet's `twoSided`
  (1.3.0: always true; still true when there is no `sheet.json`);
  `alphaMode` is `BLEND` when the buffer's vertex alpha varies, or when the
  sheet's `renderType` is 1 ("Standard with blending") and the diffuse layer
  has alpha; otherwise `MASK` when the diffuse layer has alpha, with the
  cutoff at `alphaThreshold` / 255 (95 → 0.372549; 0.5 when no threshold is
  known, and no alpha mode when the threshold is 0); when both apply, `BLEND`
  wins. (With the default `--materials engine` vertex alpha does not select
  `BLEND`; see "Materials follow the game's shader".) The normal map is embedded with green inverted and `scale` =
  `normalMapPower` when that is not 1. 1.3.0 materials were diffuse only,
  opaque and double-sided. On Part 2 PC (735 GLBs, 2,385 primitives): NORMAL
  on 2,385 primitives, TANGENT on 2,223, COLOR_0 on 1,367 (387 models);
  `BLEND` on 234 primitives, `MASK` on 236; single-sided 2,259, double-sided
  126. (Counted before the texture lookup changed, below; 17 character models
  now take their sheet from another copy of a texture, so the material counts
  may be off by a few.)
  *1.3.0 output:* `watchmen extract … --glb --no-vertex-attrs`. OBJ, MTL and
  GLB are then those of 1.3.0, and only skinned models get a GLB — except for
  the models whose texture is now found by its path (17 character models
  known, see "Textures" below). Established: byte-identical to 1.3.0 on 735
  of 735 Part 2 PC models before the lookup changed, and on the synthetic
  models of the test suite with the released code. Console and Part 1 models
  are NOT the 1.3.0 files under this switch: their mesh now comes from the
  header (the full-detail LOD, the header's materials; see "Console models
  are decoded from their header" below). `WATCHMEN_CONSOLE_MODELS=scan`
  brings the scan decode of console models back; the PC Part 1 header decode
  has no switch.

- **Character GLBs carry NORMAL, TANGENT and COLOR_0, and their triangles
  have glTF's winding** (`characters`, `char`, `charlibs`, `faces`,
  and the character step of `all`; the normal side is the front face in
  both frames, see the first item). 1.3.0 character GLBs had no NORMAL, so
  glTF consumers shaded them flat. Parts whose vertex alpha varies
  (Rorschach's `layer03` / `layer04`) point at an `alphaMode: BLEND` copy of
  their material (the legacy writer, and engine materials whose sheet blends;
  an engine material on an opaque list gets no copy and is marked
  `extras.watchmen.vertex_alpha`). The `MASK` cutoff and the normal texture's `scale` follow
  `sheet.json` when the texture has one. Unlike `extract --glb`, character
  materials stay double-sided, and `renderType` 1 does not make them `BLEND`.
  (That is the `--materials legacy` writer. With the default `--materials
  engine` the character materials follow the sheet in both respects; see
  "Materials follow the game's shader" below.)
  The attributes come from the header-driven decode of the same buffer the
  mesh was read from, so a part whose buffer the header does not account for,
  and every Part 1 or console character, gets none. Weapon and rigid
  attachments have their normal, tangent and bitangent rotated with the
  positions; the face-twin and synthetic-hair rebuilds and the degenerate-UV
  fix, which duplicates vertices, keep the attributes of the vertices they
  copy. Counted on the 26 Part 2 PC character GLBs built with the 1.3.0 heads
  (501 primitives): NORMAL on 501, TANGENT on 429, COLOR_0 on 163, winding
  reversed against the file order on 501 (counted on the engine's numbers,
  the mirrored frame; in the true frame those 501 are in file order), `BLEND` copies on 4; positions, UVs, joints, weights,
  skins, inverse bind matrices, images and all 658,330 animation samplers
  were unchanged by the attributes.
  *1.3.0 output:* `--no-vertex-attrs` on those commands, or
  `WATCHMEN_VERTEX_ATTRS=0` in the environment: no NORMAL, TANGENT or
  COLOR_0, the file's winding, no `BLEND` copies, no sheet-driven cutoff or
  normal scale. The option is accepted by `extract` (meaningful with
  `--glb`), `all`, `characters`, `char`, `charlibs` and `faces`, and is a
  usage error on any other command; the environment variable switches the
  character writer only. It does not bring back the old normal-map PNGs, does
  not stop `sheet.json` from being written, and does not undo the texture
  lookup or the ink layers described under "Textures". A resumed export
  rewrites a GLB written with the other setting (see "Changed", options
  record).

- **Jiggle bones are baked with the `solver` model by default.** `watchmen
  characters` and `jiggle_d6.apply_jiggle()` / `jiggle_pass.apply_jiggle()`
  without `model=` used `pinned` in 1.3.0; they now use `solver`: the PhysX
  2.8.1 soft swing-limit joint stepped as the game's DLL does, with the
  spring and damping from the game files only (see "Added"). Every female and
  Gimp character GLB gets different breast and belly channels: idles no
  longer sag 1.5–2.3° under gravity (0.1–0.2° on stand idles), most clips
  swing about half as far at their peaks (`EN4_COM_ATT_light_A` 11–12° →
  6.6°), fast spins swing more (`EN4_COM_ATT_dash_cycle` 5.6–5.9° → 10.7–11.9°
  mean; no capture exists to check that one against), and the jiggle bone
  now also translates, as in the game. On the full export the change per
  clip is 3.1–3.7° in the mean, 28° at most, and 4–6 mm, 97 mm at most. No
  other bone and no other character changes.
  - Looping clips (the game's `loop` flag, as in `anim_meta.json`) are baked
    as one closed lap of their settled motion: the clip is played until the
    jiggle repeats (or 12 s have passed), one more lap is recorded and closed,
    so the last frame hands over to the first without a jump. Wrap
    discontinuity on the full export, 1.3.0 jiggle → `solver`: Gimp skeleton
    (35 looping jiggle channels) median 2.61° → 0.03°, maximum 7.02° → 0.50°;
    female skeletons (94 channels) median 1.71° → 0.03°, maximum 5.63° →
    3.72°. Where it does not reach zero the clip's own body pose does not
    close (`EN4_COM_MOV_strafe_right_long`: `Spine2` itself differs by 3.72°
    between last and first frame); the jiggle is continuous with its parent
    there.
  - Clips that do not loop get a 0.25 s lead-in at the velocity of their first
    frame interval, so a clip cut out of ongoing motion does not start with
    the jiggle bone at rest (a clip that starts still is unaffected). On
    windows cut out of the captures this lowers the frame-0 error by 14–28 %.
    What the game played before a clip is not known; any start is an
    assumption.
  - Clips of fewer than four frames are left as they are (held poses).
  - A clip is baked as a loop when a looping state plays it, as the state's
    main clip or as a member of its blend (`clips[].loop`): the run and jog
    cycles that are blend members (`EN4_COM_MOV_run_cycle`,
    `EN2_COM_MOV_strafe_left`, `EN1_COM_MOV_run_cycle`,
    `NTO_COM_MOV_jog_cycle`, …) loop like the main clips do.
  - The bake took 6.9 s (Gimp skeleton, 199 clips), 13.6 s and 14.3 s (the two
    female skeletons, 190 clips each) on the full export, once per skeleton,
    then cached. It writes its own cache directory
    (`_bake/<key>_j_solver-file-<hash>`); the tag carries the model's
    constants and bake policy, not the per-clip loop flag, so if a run baked
    without metadata (its build failed) delete that directory.
  - The bake is the same bit for bit on every platform. From the palettes in
    to the palettes out the solver uses float `+ - * /` and `sqrt` only; its
    sine, cosine, arctangent and arccosine (fdlibm kernels), its nearest
    rotation (a Newton iteration in place of an SVD) and its sums (left
    folds) are in `wlib/exact_math.py`, so the C library, the Python version
    (`sum()` of floats is compensated from Python 3.12 on) and the LAPACK
    build inside numpy do not enter. That matters because PhysX does not
    execute an anchor rotation below 0.16° per step (`SOLVER_KIN_EPS`): on a
    slow clip one last bit decides whether the anchor turns in a step, and
    the baked bone ends up millimetres to centimetres away. Measured on the
    six-set export, PC Part 2, from the export's own raw bakes: the same
    solver written with `math.sin` / `sum()` / `numpy.linalg.svd` gives, on
    Linux with Python 3.10, other values than on Windows with Python 3.14 in
    34 of 199 Gimp clips and 73 of 190 Dominatrix clips (largest difference
    in a palette 7.3 cm; 44 animation accessors of `Gimp1.glb`, all
    `JiggleBelly`, and 151 of `Dominatrix_3.glb`, all `BreastL` / `BreastR`),
    and a third set on Linux with Python 3.13; `KnotTop_Small` has no jiggle
    bone and no difference. With `exact_math`, 262 bakes (131 of those clips,
    each as a loop and as a one-shot clip) are bit-identical between Python
    3.10 / numpy 2.2 and Python 3.13 / numpy 2.5 on Linux. Windows gives
    the same bits (measured on the six-set export): every jiggled palette
    the export wrote on Windows is bit-identical to the one Linux with
    Python 3.10 and numpy 2.2 computes from the export's raw bake of the
    clip (1,773 palettes of eight skeletons on each Part 2 set, 1,469 of
    five on each Part 1 set), and the 26 character GLBs of PC Part 2 built
    on Linux from the export's `extracted/` files and animation table equal
    the export's in all 744,692 animation accessors and in every mesh
    accessor; they
    differ in the PNG compression (pixels equal), in the last digits of
    node rest transforms, on 4 GLBs in one entry of an inverse bind
    matrix (by 1.4e-14) and on 2 in the last digit of the ragdoll's
    `total_mass`. The digests in `test_s2_jiggle_determinism` pin the same
    on any machine. The raw bakes that go in (611 clips of three
    skeletons) are byte-identical between the Windows and the Linux run.
    `pinned` and `pivot` keep their arithmetic and their cache tags.

  *1.3.0 output:* `--jiggle-model pinned` (CLI), `model="pinned"`
  (`apply_jiggle`), `characters_export.export(jiggle_model="pinned")`.
  `pinned` and `pivot` are byte for byte the models of 1.3.0 and keep their
  cache tags, so `_j_pinned-engine-…` directories written by 1.3.0 are
  reused. Compared with the 1.3.0 source: synthetic clips at 20, 30 and 60
  fps, and 32 real baked clips (9 directly; 23 through a byte-identical
  intermediate bake). A resumed
  export rewrites the GLBs written with another model (see "Changed",
  options record).

- **Face channels follow the game's face rule.** A character's head runs its
  own small animation class, fed by four inputs from the body (combat mode,
  "attacking", a hit with its damage pose, speaking). The export simulates
  that class for every body state and pair and bakes the result: each clip
  starts in a seeded member of the idle cycle and shows hit, attack and death
  poses at the times the game sends them, easing in over the state's ease-in
  (0.21 s; 0.37 s for the Twilight Lady / Dominatrix knock-down face), hit
  poses held for 0.75 s unless the face class leaves earlier (a `STUN_MIDDLE`
  hit on a silent enemy changes to `Retreat` on the next update; an attacking
  character changes to `Attack`). In
  1.3.0 a clip held one pose for its whole length, picked from words in the
  clip name, with an invented blink every ~3 s.
  - The invented blink is gone. Idle stretches show a seeded instance of the
    game's own random idle cycle: Twilight Lady and the Dominatrices blink
    (eyes closed for at least 0.5 s after at least 3 s open), Thugs, Gimps and
    the Heavy flash the `Provocatively` pose, Nite Owl has no idle change.
    Clips shorter than 3 s have none. `--no-face-idle` (or
    `WATCHMEN_FACE_IDLE=0`) leaves the cycle out.
  - Each idle stretch starts in a random member of the idle group, as in the
    game (`command_get_valid_state` 0x5f076f; the default state of
    Enemy01Face and Enemy04Face is the group itself), drawn from a seeded
    stream (`idle_cycle.entry`). About half the Thug / Gimp / Heavy /
    Dominatrix / Twilight Lady stretches therefore start on the second idle
    state (the sneer, or closed eyes for at least 0.5 s). A draw that could
    not return before the clip ends is replaced by the first idle state (a
    rule of the bake, so that a short loop does not keep its eyes shut).
    Nite Owl's default state is a single state and is not drawn. On the
    staged Part 2 PC clips 95 of 243 baked face schedules start this way or
    differ because of it (Enemy01Face 54 of 89, Enemy04Face 41 of 82). In
    the full Part 2 PC export 161 distinct clips carry a different face track
    for this reason, in 22 of the 26 character GLBs (51 clips in each
    Dominatrix and the Twilight Lady file, 52 in each Gimp, 58 in the Heavy
    and each KnotTop; none in Nite Owl and Rorschach). In every one of them
    the first pose that differs is the first idle state replaced by the
    second (`MouthClosed_EyesClosed` on the women, `Provocatively` on the
    men), at the start of the clip in 702 of the 1,157 clip instances and
    later in the rest; only the 13 face joints' channels change, by at most 28.3° (the women's eyelid) and 1.4° /
    0.9 mm on the men's faces.
  - Not baked, and listed per clip in `extras.watchmen.face.not_baked`:
    speech (its length is that of the wave played, but voice and wave are
    drawn at play time and the line can be suppressed), Nite Owl's exit from
    a hit pose (it ends with his grunt) and hits whose pose depends on the
    attack that landed. Those stretches stay on the idle pose. An attack
    state with two pose slots shows the first: the engine plays the first
    child of such a blend alone (see "A blend without a control parameter").
  - What the face block states about the inputs: talk ends when no voice has
    the character root as pivot (a footstep's voice has it too); a line of
    speech category 0 sends no start; `DAMAGE_POSE` on the head is never
    cleared; the mode is COMBAT when the character is in combat, holds a
    weapon or is forced to, and is playable, player-controlled or not
    PASSIVE (`face.drivers.CHARACTER_MODE.rule`); the face class is
    evaluated while the head is in a camera frustum within 9 m.
  - Nite Owl's clips no longer hold `NiteOwl_Biting` throughout: 1.3.0 took
    the alphabetically first pose as his neutral one.
  - On the full export the clips that carry a face track are: Thug, ThugBig
    and ThugFast 222 of 236 each; Gimp and GimpGagBall 199 of 213; the
    Dominatrices and Twilight Lady 190 of 202; Heavy 222 of 236; Nite Owl 235
    of 242. The others have no track in the metadata, hold the neutral pose
    and say so in their `extras`.
  - Which track a clip gets when several states or pairs play it is a rule of
    the toolkit (the pair's, else the state's whose main clip it is, else a
    blend partner's; the game has no such choice, the state decides). It is
    recorded per clip with the candidates.

  *1.3.0 output:* `--face-rule legacy` (or `WATCHMEN_FACE_RULE=legacy`,
  `export(face_rule="legacy")`, `write_glb(face_rule="legacy")`): name-based
  pose, synthetic blinks, no face extras, static heads (next item). The
  option exists on `characters` only; `char`, `charlibs` and `all` attach no
  face.

- **Thug, ThugFast, ThugBig, Gimp and GimpGagBall carry the game's
  face-rigged head** (`face_root` skin, the 11 `FACE EN1/…` poses and one
  synthetic loop, face channels on their clips) in place of the static head
  their fragment lists: 10 GLBs gain a face rig. The head is the one the game
  itself attaches: the variant's head model type selects a model of the head
  collection (`ThugFace`), with the texture sheet that collection node names
  (Thug `Medium_Head_1`, ThugBig `Large_Head_1`, ThugFast `Small_Head_1KT`,
  the two Gimps `GimpHead3`, the gag-ball Gimps `GimpHead1` or `GimpHead2`).
  The separate eye model is dropped where the rigged head has eyes.
  KnotTop_Large's rigged head, with the "Goatee" sheet of its skin texture,
  is not the same sculpt as its static one: heavier jowls, up to 4 cm off at
  the jaw; the other heads match their static copies to within millimetres.
  In the bind pose (no animation applied) these heads have their eyes closed,
  like the Heavy's. Not established: whether the game also draws the static
  head the body's own model list names.
  *1.3.0 output:* `--face-rule legacy` keeps the static heads.

- **Textures are resolved by the path the model stores**, not by the first
  folder with that name. A model header lists full texture asset paths
  (`/art/characters/knottops/textures/head.bmp`) and the game loads exactly
  those; the toolkit looked textures up by bare name and took the first
  match. Twelve names exist in more than one folder of Part 2 (`head`,
  `head02`, `EnemyEye`, `skinarms`, `Biker_DenimVest1`, `Head_Beard`,
  `KnotTop_LargeHeadF`, `Teeth`, `EyeBlow`, `WomanMouth`, `white`, `gray`),
  and for
  `watchmen characters` the "first match" was whatever order the file system
  listed the folders in, so two extractions of the same game could give
  different heads. Characters, `extract --glb` and the OBJ/MTL writer now all
  go by path. On the full export all 371 embedded diffuse images come from
  the folder the variant's own models name.
  - **Rorschach's face and inkblot are textured.** `RorschachFaceClean.BMP`
    (upper-case extension) and `rorschachspots01 .bmp` / `RorschachSpots02
    .bmp` (a blank before the dot) were never found; 30 texture folders with
    an upper-case `.BMP` were invisible to the character export. The two
    inkblot layers use the engine's subtractive blend (texture sheet blend
    type 2): white blots on black, taken away from the mask behind them. glTF
    has no such blend, so each layer is written as black ink whose alpha is
    the texture's brightness, `alphaMode: BLEND`, and marked
    `extras.watchmen.blend: "subtract"`. The vertex-alpha fade at the edge of
    the mask is kept.
  - Character GLBs that get other images than the by-name lookup gave them
    on the test machine: Heavies/Heavy (`Teeth`), TwilightLady/TwilightLady
    (`EyeBlow`, `WomanMouth`), ThugBig/KnotTop_Large (head, vest, eye normal
    map), Thug/KnotTop_Medium (only with `--face-rule legacy`: the static
    head's skin and the eye normal map; its rigged head uses the copy the old
    lookup happened to pick), Rorschach/Rorschach and Rorschach_Dry. On
    another machine 1.3.0 may have picked differently.
  - Model exports that change: 17 character models (KnotTop heads, eyes, arms
    and vests, `Medium_Head_1/2`, `Large_Head_2`, `Heavies_Head_1`,
    `TwilightLady_Head`) take their images from another folder than in
    1.3.0. When one model uses two textures with the same name
    (`Large_Head_2`: two `EnemyEye`), the second OBJ/MTL material is named
    `<name>__2`. Of the twelve names only `white` and `gray` are not
    character textures, and only the three engine helper models use them:
    `unit_box` and `unit_cone` find `/art/textures/gray.bmp` by its path;
    `unitsphere` names `/engine/helpers/white.bmp`, the stand-alone texture
    that `extract` writes as `textures/white.texture`, so it is looked up
    by name (`art/environments/common/textures/Grids/white.bmp`, with the
    warning). On the full extract, against the 1.3.0 code run on the same
    archive, no MTL of a prop or an environment names another texture
    folder: the 738 MTLs differ in the roughness file name (712 in nothing
    else; compared before materials without a highlight got `Ns 0` in
    place of that line), the 17 character models above, the three helpers, and six
    KnotTop models whose first sheet replaces the diffuse layer (below).
  - A texture that can only be looked up by name (no path in the header, or
    the path is not in the texture tree) is chosen deterministically: of the
    folders with that name, the one whose asset path sorts first. With more
    than one candidate a warning lists them all.
  - Limits. A variant can select another *sheet* of a texture, and a sheet
    can replace a layer with another texture (`diffuseMapOverride` and seven
    more). The export follows that for the face-rigged heads it takes from a
    head collection; body parts and `extract --glb` use each texture's first
    sheet. `extract --glb` and the OBJ/MTL writer do not rewrite subtractive
    layers: Rorschach's two inkblot materials come out there as the raw
    white-on-black textures.

  *1.3.0 output:* none. The old choice depended on directory listing order
  and is not reproduced by any switch.

- **What the three switches together restore.** `--jiggle-model pinned
  --face-rule legacy --no-vertex-attrs` gives character GLBs whose nodes,
  skins, meshes and animation samplers are those of 1.3.0. Not restored: the
  normal-map channels, the texture choice (including Rorschach's textures
  and ink layers), and the `joint_space` sentence under "Fixed". One mesh
  follows from the textures: Rorschach's face part now has a normal map and
  so gets the degenerate-UV vertex split that every normal-mapped part gets
  (369 → 459 vertices).
  How far this is established: on the synthetic character of the test suite
  the 1.3.0 code and this release, so switched, write the same bytes apart
  from that sentence. On real data it was checked in steps, not in one run
  against 1.3.0: the attribute switch against the 1.3.0 code (one character
  GLB byte-identical); `pinned` and `pivot` against the 1.3.0 source; and
  the full export with `--jiggle-model pinned --face-rule legacy` against an
  export made with by-name textures, on 20 GLBs: every animation sampler,
  skin, node and mesh buffer equal, the only differences being the texture
  corrections above, Rorschach's face part and the `joint_space` sentence.

- **`watchmen char` uses the animation metadata** when its fragment lies
  under `EXTRACT_OUT/extracted`: clips get the same `extras` as in
  `characters`, and with `--jiggle-model` looping clips are baked as closed
  laps. `char` still bakes no jiggle unless `--jiggle-model` names a model,
  and attaches no head, so its GLBs have no face rig and no face channels
  (nor textures, tangents, weapons or ragdoll helpers: `characters` writes
  the full character).
  *1.3.0 output:* `--no-meta`, or a fragment anywhere else: no clip extras,
  every clip baked as non-looping.

- **`Interpreter.get_valid_state` scans a group as the engine does**
  (`command_get_valid_state` 0x5f076f): from its first member, or from a
  random member in "Choose Random State" groups, instead of continuing after
  the member it returned last. The draw comes from `Interpreter(seed=…)` /
  `rng=`. Run over the shipped body classes, Enemy01, Enemy04, NiteOwl and
  Rorschach are tick-identical to 1.3.0; EnemyBig now starts in a randomly
  chosen idle fidget. `anim_meta.json` does not use the interpreter for body
  classes. *1.3.0 behaviour:* not available.

- **A character GLB shows one outfit, unarmed.** A character collection
  holds complete outfits under one name — 18 for `Heavy`, 11 for
  `KnotTop_Medium`, 11 for `KnotTop_Large`, 9 for `KnotTop_Small` — and the
  extractor's per-name record is the union of their model lists, which is
  what the GLBs showed: three hairstyles and every jacket at once, and every
  weapon of the character stacked in the right hand. The engine gives each
  spawned character one outfit (`CharacterModelCollection.command_get_model`
  0x66ca15: the one asked for, else the least-used so far, the first of them
  in the collection's child list; nothing is random) and at most one weapon,
  none unless the spawner or a pick-up sets a weapon type
  (`CharacterRoot.command_set_weapon` 0x694378). The GLB now shows outfit 1
  and no weapon. The 22 variants with a single outfit look as before, minus
  the weapons; Twilight Lady keeps her whip, which is part of her own model.
  - Models that every outfit wears with the same texture sheets stay in the
    main mesh. Every other model is a node of its own, `OUTFIT <k> <model>`,
    once per outfit `k` that wears it, with that outfit's materials; the
    nodes of one model share their vertex data. The nodes of outfit 1 are in
    the scene; those of the other outfits, and the weapons (`WPN_<model>`),
    hang under a node `alternatives` that belongs to no scene. Viewers draw
    scenes and do not show them; Blender imports them into the collection
    "Orphan Nodes", switched off, bound to the armature. To see outfit `k`:
    hide the `OUTFIT 1 …` objects, show the `OUTFIT k …` objects. On the
    full export: Heavy 7 outfit nodes shown and 99 hidden, KnotTop_Medium
    3 / 36, KnotTop_Large 5 / 42, KnotTop_Small 4 / 30; weapons hidden: 2 on
    each Dominatrix, 5 on each Gimp, 3 on the Heavy, 8 on each KnotTop, 14 on
    Rorschach, 15 on Nite Owl.
  - `asset.extras.watchmen.parts` records the outfits (`members[]`: models,
    nodes, sheets, head type), the one shown, the common models, the hidden
    nodes, the weapons with their collection and class, and the engine rules.
  - What moves: against the `--parts all` output of the same data every triangle of
    the shown outfit is present with identical positions, normals, tangents,
    UVs, colours, joints and weights, but the main mesh is regrouped (fewer
    primitives; the outfit models are separate meshes), so accessor contents
    and order are not byte-identical. Animations (5,731 clips, every channel),
    skins and bone nodes are byte-identical on all 26 files.
  - Limits: the face rig is that of outfit 1 (an outfit with another head
    type, or another face sheet, keeps outfit 1's head); which outfit a level
    spawner asks for is not read.
  *1.3.0 output:* `--parts all` (or `WATCHMEN_PARTS=all`,
  `export(parts="all")`): every listed model in the main mesh and every
  weapon in the hand, no `alternatives` node, no `parts` record. Triangles,
  mesh nodes, animations and skins are then those of 1.3.0;
  what remains different is the texture sheets (next item) and the
  `weapon_use` metadata.

- **Each part wears the texture sheet its outfit selects.** A texture has
  one or more sheets — named parameter sets that can also replace single
  layers with another texture. A fragment node picks a sheet per model slot
  (`textureSheetsDescription`); with no record the first sheet applies. The
  export used the first sheet's switches and never its layer overrides.
  Now: a part takes its sheet from its own outfit node; a sheet's layer
  overrides are followed (the renderer asks the sheet for each layer and
  gets the override texture's layer when one is set, 0x49c838 / 0x4991f0);
  alpha mode, two-sidedness, blend type and roughness come from that sheet.
  A material on a sheet other than the first is named `<texture> [<sheet>]`
  and carries `extras.watchmen.sheet`. What changes on the full export:
  - Heavy: jacket and trousers in the outfit's colour (`Heavy_Outfit1`
    sheets Outfit2 / 3 / 4), buttons Blue / Yellow / Brown / beige; outfit 1
    has blue shirt buttons.
  - KnotTops: T-shirts Red / Purple / ver2beige / ver2red / ver2green,
    sleeves Red. The FIRST sheet of three KnotTop textures replaces the
    diffuse layer, so these change on every outfit: `KnotTop_TShirt`
    (`KnotTop_TShirtBeige`; no longer alpha-tested, that image has no
    alpha), `SkinTorso` (`KnotTop_SmallTorsoSkin`), `denim` (`DenimB2`,
    visibly darker jeans).
  - Dominatrix_5, _7, _10 (and the reconstructed _3): the dark body skin was
    a built-in whole-texture swap; it is now the sheet their nodes name, so
    the diffuse image is the same and the material gains the body texture's
    normal and specular maps, as in the game.
  `extract --glb` and the OBJ/MTL writer use each texture's first sheet, as
  the engine does without a fragment: 8 KnotTop models change (arms, torso,
  trousers).
  *1.3.0 output:* not available; the sheets are what the game data says.

- **`extract --glb` writes blended layers by their blend type**, with the
  same code as the character export. A sheet of render type "with
  blending", "sky box" or "sprite" — or a standard or fall-off sheet whose
  opacity is below 0.99, which the game draws in the blended pass — has a
  blend type: `standard` (alpha
  blend, written as `BLEND` as before), `add`, `subtract`, or `manual` with
  explicit Direct3D factors. `subtract` (Rorschach's two ink-blot layers) is
  written as black ink with alpha = the texture's brightness; `add`, and a
  `manual` blend equal to it, as an emissive layer (base colour black,
  emissive texture = the layer at full brightness, alpha = its peak); a
  `manual` blend with no glTF expression keeps the raw layer. An emissive
  layer whose blend reads the source alpha (SRCALPHA / ONE: `add` outside
  the sky pass, or such a `manual` blend) carries its sheet's opacity: the
  alpha the shader writes holds it (`SkyBoxPS`: texture alpha × vertex
  alpha × opacity, read from code; for the standard pass the item alpha of
  0x5739d0 holds the sheet opacity, and that the shader multiplies it in
  is inferred), so `emissiveFactor` is the opacity where that is below 1,
  and `extras.watchmen.opacity` records it. `add` in the sky pass is ONE /
  ONE and keeps factor 1. Measured on the six-set export's files: 4 model
  GLBs per Part 2 set (`Sky_MainMenu_02` 0.6 through `Sky_SunRay_01`,
  `Disco_Ball_01` 0.08, `PickupTruck_OnFire` and `Sedan_BurnedOut` 0.63)
  and 3 per Part 1 set (`Sky_Sunset_02` and `CityBackdrop` 0.6,
  `Building_03_Happy_Harrys_Doorlight` 0.25) change, in `emissiveFactor`
  and the new key only. The engine's
  state is recorded in `extras.watchmen` (`blend`, `src`, `dst`, `op`). 9
  of the 735 Part 2 PC model GLBs change: Rorschach, Rorschach_Dry,
  Disco_Ball_01, PickupTruck_OnFire, Sedan_BurnedOut,
  BrooklynBridgeLightFlares_01 and three sky boxes. OBJ/MTL has no blend
  equation and keeps the raw layers.
  *1.3.0 output:* not available.

- **Materials follow the game's shader** (`--materials engine`, the default;
  also `$WATCHMEN_MATERIALS`; on `extract`, `all`, `characters`, `char`,
  `charlibs`, `faces`). One colour shader lights every opaque and
  alpha-tested surface in the game; the GLB material is now built from the
  texture sheet the way that shader uses it:
  - roughness = (2 / (n + 2))^0.25 with n the sheet's `specularSize`, per
    texel (a roughness texture) where the texture has a specSize layer;
  - specular strength from `specularPower` and the specular layer, written
    with `KHR_materials_specular` and, above a reflectance of 0.04,
    `KHR_materials_ior`; `specularPower` 0 means no highlight
    (`specularFactor` 0); nothing is metallic;
  - a material the game draws no highlight on at all (`specularPower` ≤ 0
    and no cube reflection, or a reflectance of nothing, e.g. a black
    specular layer) is written fully rough: `roughnessFactor` 1.0 and no
    roughness texture, whatever its `specularSize` and specSize layer say.
    The width of a lobe that is not there has no meaning, and a viewer that
    ignores `KHR_materials_specular` (F3D) would otherwise draw the default
    dielectric highlight at that width: wet-looking hair, brows and eyes.
    With the extension the lobe is off and the roughness is not seen. A
    highlight of any strength above zero keeps the sheet's roughness;
  - emission from `selfIlluminance` (colour × glow layer × (albedo +
    specular layer)), with `KHR_materials_emissive_strength` above 1;
  - alpha from the render list the engine sorts the sheet into, and from
    nothing else (0x5739d0; the opaque lists are drawn with blending off):
    `BLEND` only for render type 1, or `opacity` below 0.99 on a type 0, 7
    or 10 sheet, otherwise `MASK`
    at `alphaThreshold` when the diffuse texture has alpha (hair included:
    it is never blended), otherwise opaque. Vertex alpha never makes a
    material `BLEND` by itself; a material used with varying vertex alpha
    carries `extras.watchmen.vertex_alpha: true`, and `extract --glb` writes
    one material where the legacy writer writes a `BLEND` copy. "The texture
    has alpha" is the Texture header's flag, as in the engine (0x429e77 →
    0x571d5d), which the texture pass now writes to `sheet.json` as
    `textureHasAlpha`; an extract without the key falls back to the pixels.
    A flagged texture whose alpha is 255 everywhere is written opaque.
    Sky-box and sprite sheets (their own blending passes) and materials
    without a known sheet follow the vertex-alpha rule of the legacy writer.
    `twoSided` decides `doubleSided`, in the character GLBs too. Part 2 PC,
    by sheet values: none of the 438 character materials and 3 of the 2,126
    model materials are opaque where vertex alpha alone would have made them
    `BLEND` (`Ground_Marble_Tiles_01` in TwilightMansion_Atrium_01 and
    TwilightMansion_Hall, `ground_autumnleaves_01` in LeavesPile_01); flag
    and pixels agree on 931 of 937 textures, and the six that differ are
    flagged but fully opaque;
  - the sheet's own numbers, including the rim ("falloff") parameters glTF
    cannot express, are in `material.extras.watchmen.sheet_values`.
  The ink and glow handling of blended layers is unchanged. OBJ/MTL link
  `roughnessEngine.png` in place of `roughnessGen.png`; a material without
  a highlight gets `Ns 0` (fully rough in Blender's importer) and no
  `roughnessEngine.png` is baked for it.
  On the 26 character GLBs every material but one changes (399 materials):
  all get the sheet's roughness and a specular extension, 213 an `ior`, 104
  no highlight at all, 279 become single-sided, 1 emits, 2 turn from `MASK`
  to `BLEND` (Twilight Lady's tights and brows, render type 1). The baked
  roughness images of the old writer are gone (2 to 31 fewer images per
  file). 645 of the 735 extracted model GLBs and 701 MTLs change.
  *Materials without a highlight on the real data* (the full Part 2 PC
  export written with and without the rule and compared by a checker of its
  own): in the 26 character GLBs 104 of 438 materials have no highlight,
  in 24 of the files (hair, brows, eyes, mouths and teeth, the KnotTops'
  T-shirts and denim, Rorschach's scarf and trousers, held props); their
  `roughnessFactor` was 0.49 to 0.88 or a texture and is 1.0, five lose a
  roughness texture (69,082 bytes of images), and nothing else differs:
  all 751,744 accessors are byte-identical, and so are the ragdoll files
  and `sound_meta.json`. In the 738 model GLBs it is 236 materials in 165
  files (20 roughness textures, 2.2 MB, not written), with every accessor
  of those files byte-identical; the same 165 MTLs get `Ns 0` for 234
  materials in place of the `map_Ns` line; the other 573 GLBs and MTLs and
  all OBJ and `.model.json` files are byte-identical. glTF-validator: 0
  errors and unchanged counts on both sets. A head close-up of
  `Dominatrix_6` rendered in Blender (which reads the specular extension)
  is pixel-identical with and without the rule; in F3D 3.5.0, which does
  not read it, the highlights on her hair are gone. Skin and other
  materials with a weak highlight still look glossier in F3D than in the
  game: they keep the right width at F3D's default strength.
  *How much closer it is:* rendered against the game's lighting equation,
  the mean error falls by 3 to 17 % on skin, clothing, latex and hair in
  three.js and Blender. The gain is modest and not uniform: it is not
  smaller under every light direction, and two small accessory materials
  of the Dominatrix suit (lace, ring) come out slightly worse; they get the
  same mapping as everything else. The larger difference to the game — its
  rim light and its lighting on display-encoded values — has no glTF
  equivalent. In a viewer with a bright environment, the strongly specular
  materials (latex, Nite Owl's armour) reflect that environment, which the
  game does not have.
  *1.3.0 output:* `--materials legacy`: the materials of the previous
  writer, GLB and MTL byte for byte (checked on all 26 characters and all 735
  models against the legacy writer's own reference output; 1.3.0 itself
  also lacked the sheet switches listed above, so its files differ there).

- **Character GLBs carry the ragdoll rig, and a `<Variant>.ragdoll.json` is
  written beside each.** The 17 bodies and 16 six-degree-of-freedom joints
  the game instantiates from the model in slot 0 of the variant's model list
  are helper nodes under a node `ragdoll` that, like `alternatives`, belongs
  to no scene: `RB.<bone>.<i>` proxy meshes skinned rigidly to the bone
  (17 to 43 per file), `RJ.<child bone>` empties at the joint frames (16),
  values in `extras.watchmen.ragdoll`. Viewers do not draw them; Blender puts
  them in "Orphan Nodes", switched off. Meshes, skins and animations of the
  character are untouched. See `docs/RAGDOLL_RIG.md`.
  *1.3.0 output:* `--no-ragdoll` (or `WATCHMEN_RAGDOLL=0`): no helper nodes,
  no sidecar.

- **Music streams are written one file per track.** A `.mediastream_s`
  holds up to seven synchronous stems; 1.3.0 appended them chunk by chunk
  into one file (`Underground`: 239.8 s instead of five 48.0 s tracks; on
  X360 a 25 s patchwork). `extract` now writes
  `<name>_track<k>.mediastream_s.ogg` (PC), `.xma` / `.mp3` or `.wav`
  (consoles), each with its exact length, and a `<name>.mediastream_s.json`
  sidecar with the tracks, cue points and the `MusicSetup` track states. On
  Part 2 PC 10 of the 13 streams change (their `_track0` file is now the
  first stem only) and 40 track files are new; the three one-track streams
  keep their name and now end at the stream's stored end position (704, 832
  and 704 samples shorter; Part 1 Intro01 106).
  *1.3.0 output:* `extract … --flat-music`.

- **35 stereo sounds have their own sample rate, 50 PCM sounds start at
  their first sample** (Part 2 PC; 18 and 319 in Part 1). The stereo sounds
  were written at 44100 Hz although their header says about 48000 and played
  8 % slow (`ExplosionAndFire` 13.63 s → 12.52 s); the PCM sounds were read
  4 bytes late. 76 of the 2,921 Part 2 PC sound files change (9 for both
  reasons), the other 2,845 are byte-identical.
  *1.3.0 output:* not available. An `audio` folder written by 1.3.0 keeps
  the old files until `extract` is run again.

- **Twilight Lady talks in her four cattle-prod counters.** The clips
  `BS2_COM_ATT_cattleprod_counter_{NTO,RSH}_{A,B}` start one fixed voice
  line each; their face track now holds the talk cycle for the length of
  that line (2.45 / 5.23 / 2.81 / 2.02 s). The ten Dominatrix GLBs share the
  clips and change with them (11 GLBs × 4 animations); no other animation
  channel of the export changes. `face_format` is `watchmen-face/2`.
  *1.3.0 output:* `--face-rule legacy` (which removes all face tracks of
  this release); there is no switch for the talk segment alone.

- **`watchmen_extract.gltf_tangents`** returns w = −sign(dot(cross(N, T), B))
  by default, the handedness for a normal texture with green inverted, for
  the vectors it is given (the writers call it on the engine's numbers).
  *1.3.0 result:* `gltf_tangents(…, green_up=False)`.
  **`rig_glb.build_rigged_glb`** writes COLOR_0 as float with rgb converted
  to linear instead of normalised bytes. No 1.3.0 command used either.
  **`watchmen_extract.extract_materials()`** and the `material` of
  `model_submeshes()` return `TexRef` strings: the bare name as before, with
  the asset path in `.path`; two with the same name and different paths are
  different dictionary keys. `build_texture_index()` returns a
  `TextureIndex`, still a `{name: folder}` dict.
- **`<name>.particle.json` is the `kapow-particle/2` tree.** It was the flat
  `blocks` list of the generic property-bag walk, without a `format` key.
  Now: `system` → `types[]` → `affectors[]` / `spawners[]` /
  `initializers[]`; a record's `key` is `name`, in the engine's spelling
  (`texture`, `duration`, `position`, `speed`, `force`, `ambient`, `factor`
  were capitalised; `open`, `life`, `numX`, `numY`, `damp` were hex keys);
  `truth` is a JSON boolean (was 0 / 1), `number` the shortest decimal of the
  float32 (0.01, was 0.009999999776482582), a null string `null` (was `""`),
  `vector` / `quaternion` plain lists; `pre`, `owner` and `schema` are gone
  (they were the list counts, the object id and the payload length). New per
  record: `enum`, `flags`, `keys` (parsed gradient), `default`. See
  `docs/PARTICLE_FORMAT.md`, section 7.
  *1.3.0 output:* no switch. `kapow_props.parse(data)` still returns the old
  walk, and a file that is not a complete tree still gets it, with a `warn`
  line (no shipped file is one). `.grass`, `.detailmesh`, `.pb` and
  `.terrain` JSON are written as before, except that five hashes that were
  hex keys are now named wherever they occur (`life`, `numX`, `numY`,
  `damp`, `open`).
- **`extract` writes two more folders, `text/` and `nav/`.** `text/` holds
  every text asset in every language (see "Added", text and subtitles);
  `nav/` the navigation data of every level whose path data is under
  `files/` (see "Added", navigation). Every file of the previous output is
  byte-identical (checked for `text/` on four Part 2 PC block pairs and the
  music streams: 5,439 files identical, 226 new, all under `text/`; the
  `nav/` step only reads `files/` and `extracted/` and writes under `nav/`).
  The log gains a `TEXT:` and a `NAV:` line.
  *1.3.0 output:* `--no-text`, `--no-nav`.
- **Fragment JSON has a `header`, and more nodes have a `type`.** Every
  `.fragment.json` gains the key `header` (version, singleton,
  smart_selectable, name, reapplyable, typed, chunks). Native nodes whose
  type record opens the stream (`SceneNode`, leading `Folder`s) used to be
  skipped by the schema scan and now carry their `type`: 111 of the 907
  Part 2 PC files, 138 of the 759 Part 1 PC files. Instance records and
  properties are identical in every file, in the same order, and all stay
  lossless. `.scene` files, refused before, are accepted by the JSON
  converter (`watchmen fragment`); `extract` writes none for them.
  *1.3.0 output:* no switch.
- **`anim_meta.json` carries the combat and effects blocks; the character
  GLBs carry part of them.** Additive: the format string stays
  `watchmen-anim-meta/2`, and with the added keys removed the table equals
  the one written before (compared on Part 2 PC for each block on its own:
  equal for the combat block, byte-identical for the effects block). The file
  grows from 12.4 MB to 15.7 MB with the combat block alone and to 14.4 MB
  with the effects block alone (with both blocks and the face block, in the
  six-set export: 21.5 MB on PC Part 2, 17.2 MB on PC Part 1; measured). In the
  GLBs, every animation's `extras.watchmen` gains `payload` /
  `payload_stale` on its events and `camera_cuts` / `camera_return` /
  `trigger` on its pair entries where the pair has them, and
  `asset.extras.watchmen.fx_attachments` is added for Rorschach, Nite Owl
  and Twilight Lady. No vertex, skin or animation data changes.
  *1.3.0 output:* no switch for the table. `char --no-meta` writes a GLB
  without the clip extras.
- **`sound_meta.json`**: every wave of a speak voice gains `subtitle_key`;
  the `effects.damage_rule` sentence is corrected (see "Fixed"). No other
  value changes.
- **`grade_meta.json`** (`watchmen grademeta`): every node gains
  `_iplayerctrl`, `m_tinitialgfxnode`, `skyboxblur`, `edgedetectgradient`,
  `edgedetectcutoff`, `noisetexture` and `shadowblurpower`, and the file
  gains `platform_adjustment`.
- **A blend without a control parameter plays its first child alone**
  (`command_evaluate_blends` 0x59e905 writes the blend on the first child
  only; `SetAllSlotBlends` 0x5b4ef7 sets the other slots to 0).
  `Interpreter.slot_weights()` gives 1.0 to the slot with the lowest
  `siblingOrder` (file order among equals) and 0 to the rest, where 1.3.0
  gave every slot of such a blend the full weight, and no longer multiplies
  by `m_nweight`
  (no reader in the executable; 1.0 on all 1,899 slots of the Part 2 PC
  classes). Four body states are affected: Enemy01 `AnimsToAdd`; EnemyBig
  `StrafeRight`, `HeavyMiddleBack`, `AnimsToAdd`. `main_clip` and a state's
  `clips[].weight` (the stored value) are as before.
  *1.3.0 output:* not available.
- **`check.contact` of a pair turns each body with its `GamePivot`.** A
  joint's position is `GamePivot(t) + R(q_GamePivot(t)) · joint`; 1.3.0 left
  the rotation out. Read from code (`UpdateAnimPoseAndCloth` 0x6b015d,
  `UpdatePagePlayPos` 0x5b56a9) and seen in the data: `interact` is fixed in
  the world to 1 cm on 67 of the 72 clips whose `GamePivot` turns with the
  rotation applied, on none without it. Part 2 PC: `closest_m` changes on 64
  of the 413 pairs, on 11 primary rows by more than 2 cm, and the four primary
  `_X` counter rows (`RSH_COM_ATT_counter_EN1_X` / `EN1_COM_DMG_counter_RSH_X`
  among them) go from plausible to unverified: 198 verified, 28 plausible, 14
  unverified of 240, where 1.3.0 had 198 / 32 / 10 (the full export; all 413
  pairs have a check. The staged set, which lacks two clips, gave 196 / 28 /
  14 and two pairs without a check). Two non-primary rows change the same
  way. No `placement` value changes.
  *1.3.0 output:* not available.
- **`.fragment.json`: property keys are spelled as the engine registers
  them.** Both name tables now spell a name the way the engine's class
  registers it (see "Data tables"), so keys change letter case and nothing
  else; the key hash folds case, and hashes, types and values are as before.
  - *`nodes_full` (and with it `instances` and the `.scene.json`).* 99 names
    of the fragment key table differed from the registered spelling in letter
    case only. 48 of them occur in the PC Part 2 fragments (285,211 keys, in
    897 of the 906 fragments and the scene file) and 49 in PC Part 1 (436,865
    keys, in 746 of the 758 and the scene file); the PS3 Part 2 and Xbox 360
    Part 1 sets give the same counts within 5 keys. The frequent ones:
    `UseRealTime` → `useRealtime`, `Open` → `open`, `Visible` → `visible`,
    `Locked` → `locked`, `UserType` → `userType`; the ten `SoundSlot` keys
    (`minrange` → `minRange`, `maxrange` → `maxRange`, `dopplerfactor` →
    `dopplerFactor`, `reverbmixfactor` → `reverbMixFactor`,
    `enableobstructionandocclusion` → `enableObstructionAndOcclusion`,
    `Priority` → `priority` …); `Mass` → `mass`, `Brightness` → `brightness`;
    the `LensFlare` and `Sprite` keys (`FadeFlareAngle` → `fadeFlareAngle`,
    `v1u` → `v1U`, `cullmode` → `cullMode` …); `nearclip` / `farclip` →
    `nearClip` / `farClip`; `textres` → `textRes`; `modelres` → `modelRes`
    (Part 1). Measured by decoding every raw file of the four sets that has a
    JSON beside it (1,207 per Part 2 set, 1,174 per Part 1 set) with both
    tables: no file differs in anything but the letter case of keys, and the
    `.sequence`, `.particle`, `.pb`, `.grass`, `.detailmesh`, `.terrain` and
    `.font` JSON do not change at all. None of the 99 is an entry of a script
    database (`Database.bin`); the spelling is that of the registration
    string. The toolkit's own readers take either spelling, so a
    `.fragment.json` of an older version is still read. In the metadata
    tables two keys follow: `nearClip` / `farClip` of the four camera rigs in
    `fx.camera.rig` (`anim_meta.json`, `fx_meta.json`); `anim_meta.json`,
    `sound_meta.json`, `text_meta.json` and the level and navigation files of
    PC Part 2 are otherwise the same with both tables.
  - *The `instances` list and `.grass.json`*, from the property dictionary:
    `targetanimation` → `targetAnimation`, `Texture` →
  `texture`, `textres` → `textRes`, `PivotID` → `pivotID`. On the nine
  staged blocks (Parts 1 and 2; PC, Xbox 360, PS3) the first three are the
  only keys of this kind that change, in 38 of the 303 fragments of the Part 2 main block
  and 38 of the 276 of Part 1; the `.pb`, `.sequence` and `.particle` JSON of
  those blocks are unchanged. On all
  seven blocks of the Part 2 PC archive: 254 of 1,068 fragment records
  change (main 38 of 303, Bordello 72 of 335, NightClub 84 of 213,
  StreetsOfRiot 49 of 168, MainMenu 6 of 12, PlayerVsPlayer 3 of 18,
  Tutorial 2 of 19); `PivotID` occurs only in StreetsOfRiot (6 keys); all 7
  `.grass` records change in one place, the `key` of their `Texture`
  property (now `texture`, which `GrassAsset` registers); the `.detailmesh`
  (8), `.terrain` (3), `.pb` (6), `.sequence` (271) and `.particle` (112)
  records are unchanged.
  *1.3.0 output:* not available; compare keys by `name_hash` or without
  regard to case.
- **`anim_meta.json` `event_semantics`**: the `effect` text of events 29, 30
  and 31 is rewritten (see "Fixed") and ten `evidence` strings no longer say
  "skimmed"; `enums` gains `CHARACTER_BONE_TYPES`; the table carries
  `revision`.
- **`parse_block_header`: `version_signature` is the u32 at offset 32.** It
  used to return the four bytes at 328, which are not the signature. The
  signature (0x79D3E0DA in every Part 2 block and in PS3 Part 1, 0xEE1FB0A3
  in PC / Xbox 360 Part 1) is what the engine computes from its asset type
  versions (0x49db60); the PC loader computes it and throws it away. The
  bytes at 328 (`0a 88 3f 59` in every block, not byte-swapped on the
  consoles) are the CRC of the fingerprint: the unfolded bit-CRC of the
  255-byte plaintext fingerprint field, text plus zero padding, 0x593F880A
  for the default text; the loader does not read it. They are returned as
  `fingerprint_crc`, with `fingerprint_crc_ok` (it matches the decrypted
  fingerprint; true on all 45 block headers of Parts 1 and 2 on all platforms; measured), and still as `unknown_328`. New fields `low_violence` (byte 388)
  and `fingerprint_display` (byte 327, also `unknown_327`: 0 = the debug
  overlay shows the fingerprint until 20 s after its first draw in the
  process, 1 = always, 2 = never; 2 in every
  block). `watchmen_extract.fingerprint_field_crc(text)`. No written file
  carries these values.
- **Block blobs are inflated by asset type, not by their first byte.** Every
  type is zlib-compressed except `mediastream`, as in the engine (0x5480fe,
  0x554a2e). A blob that should inflate and does not is reported in the
  extract log and written as stored. Four PC Part 2 blocks: 2,161 header
  blobs inflate, 7 `mediastream` headers are raw, 444 of 444 streams inflate,
  none fails — the output is unchanged.
- **`decode_sequence.evaluate`: a linear key blends only number, vector and
  quaternion values.** An integer goes `a + trunc((b − a) · t)` (read from
  code: 0x4fac1c converts with `cvttsd2si`); truth, colour and every other
  type hold the first key, as the engine's interpolators do (0x47fc01). No
  value changes on the shipped sequences checked (every truth track is step).
- **`extract --language`** also takes a language name or code (`german`,
  `de`, `uk`, `dk` …). `--language uk` used to be an error.

- **Parts 1 and 2 on all platforms: what changes in output that was written before.** PC
  Part 2 first, because it is the reference set; each line names the fix
  under "Fixed" or "Added" that causes it.
  - *PC, both parts: cube maps.* `face1_` … `face5_` of every cube map
    change (550 PNGs in 110 folders of Part 2, 1,000 in 200 of Part 1);
    `face0_` and every other texture file are byte-identical (937 of 937 and
    1,190 of 1,190 folders compared with the cube switch off).
    *1.3.0 output:* `watchmen_extract.PC_CUBE_LEVEL_MAJOR = False`.
  - *Every set: `.fragment.json`.* `nodes`, `named_instances`, `instances`
    and `transforms` are built from the exact parse; `schema`, `nodes_full`,
    `header` and `lossless` do not change. PC Part 2: `instances` changes
    in 558 of 906 files, `nodes` in 897, `transforms` in 61,
    `named_instances` in 58; every file gains `instances_source`. In
    `instances`, text is listed under the property's own name
    (`m_smainbehavior`, not `str_c44328b5`); `str_<id>` is kept for a node's
    type record only; elements of a `list(string)` property appear under
    the list's name, and resource paths among them also under `model_ref` /
    `texture_ref` / … as before; empty strings are listed; `texture_table`,
    and `*_ref` for plain string properties, are gone. A `nodes` entry is
    `{type, hash}` with the type's own id; `depth` is gone (it was the name
    length of the following record). `model_ref`, which the character
    export reads, is the same per instance in 391 of 393 PC Part 2 files;
    the two others are level fragments where a path moved to its owner.
    *1.3.0 output:* not available (`kapow_json.fragment_json` still is the
    old sweep).
  - *Every set: one output per asset name.* `extract` writes an asset that
    several level blocks store once. PC Part 2: the name inside
    `Rubble_Rooftop_02.model.{obj,mtl,glb}` and `Rubble_RoofTop_03.model.*`
    is now the file's own name (it was the spelling of the last block
    written); no other file changes. The summary lines `textures` and
    `models` count files written, not block entries (Part 2: 939 and 743
    where 1.3.0 printed 1,401 and 984), `MODELS: n` is the number of
    distinct models, and a model without output is named with its reason.
  - *PC Part 2: `.model.json`.* `lods` is no longer empty in 22 of 738
    files (models whose property bag holds an `animation` path).
  - *Every set: level JSON.* Added keys only (`stable_uid`, `stable_id`,
    `stable_ids`, `conventions.stable_uid`; `nav_note` where a level has
    path objects and the extract no path data).
  - *Every set: `faces/Large_Head_2.glb`* gains its `EnemyEye` card (one
    piece, 40 vertices). No Part 2 character wears that head; seven Part 1
    `BikerBig` variants do and gain the piece.
  - *Xbox 360:* every sound `.xma` changes (2,921 in Part 2, 3,953 in
    Part 1: four bytes earlier, now decodable); 179 of 937 texture folders
    in Part 2 and 257 of 1,190 in Part 1 change (cube faces, animation
    frames, the fourth layer, the `specSize` label). *PS3:* 58 (Part 2) and
    79 (Part 1) `.mp3` files get their cut tail back; cube maps are six
    PNGs instead of one (114 and 201 folders change). Console texture files
    are named `faceN_` / `frameN_` as on PC (`segN_` only where the exact
    header does not read). Layer PNGs, counted in the six-set export as
    every `.png` under `textures/` except `roughnessEngine.png` (which the
    material writer adds): 2,886 in each Part 2 set and 3,656 in each
    Part 1 set, the same number on PC, Xbox 360 and PS3.
  - *Console and Part 1 characters:* 11 Part 2 GLBs per console gain 29
    pieces, all 26 gain the ragdoll nodes and a `.ragdoll.json`; Xbox 360
    Part 1 gains the sunglasses in 19 GLBs; PS3 Part 1 gains 26 pieces and
    80 ragdoll files; PC and Xbox 360 Part 1 regroup the outfits of six
    GLBs by their sheets (Mercenary ×2, the four KnotTop thugs: 283 pieces
    go, 116 come) and end at 1,525 pieces, from 1,685 and 1,666. Every console or Part 1 character GLB gains
    `asset.extras.watchmen.not_decoded`.
  - *Standalone Part 1 (PC, Xbox Live):* `sheet.json` and `spec.txt` exist
    for every texture (0 → 1,206 headers read), so `roughnessEngine.png`,
    the MTL files and the character materials follow the sheets where they
    used defaults; `.pb.json`, `.grass.json` and `.detailmesh.json` are
    decoded in full and carry `"record_layout": "untyped"`; 7 files more
    under `files/` (the path data), 6 nav GLBs. *All Part 1 sets:* 16
    texture folders and 54 models more (the Prison stream files), three
    of the models skinned and so with a GLB (178 → 181; every model has a
    GLB with the header read, see "The model header of the stand-alone
    Part 1 (PC, Xbox Live) is read").
  - *Console and Part 1:* a `.model.json` beside every model.
- **Models made of several rigid parts are assembled.** A model's vertices
  are stored in the space of their part; 1.3.0 wrote every part at the model
  origin (the rotors of the helicopter at its hub, the tyres of a car in one
  heap, the rooms of the mansion on top of each other). OBJ and GLB now hold
  model space: `v' = conj(q)·v·q + pos`, the part first and then each parent,
  for positions, normals, tangent and bitangent of every unskinned buffer
  (`watchmen_extract.model_part_transforms`; skinned buffers stay with their
  bone palette; `decode_model_mesh(..., part_space=True)` returns the stored
  values). Measured: the union of the transformed LOD-0 submesh boxes equals
  the model box on 47 of 47 models with a moved render part in each Part 2
  set and 37 of 37 in PC Part 1 (7 and 14 as stored). The OBJ and the GLB
  geometry of those 47 / 37 models change; every other OBJ is the same
  bytes and every other GLB has the same geometry (PC Part 2: 688 of 735).
  Affected in Part 2: 24 `TwilightMansion_*` rooms and door sets, `Sedan_74`, `Sedan_Tires_01`, `Huey_Police_01`, three
  water towers, five `Detail_*` scatter models, three sky domes,
  `Dumpster_medium_02`, `Tripod_01`, `Clothing_Rack_01`, `SwitchInteractive`,
  `THP_DressingRoom_02`, two `lock_casing_*`, `GrappringGunBullet`,
  `Rorschach_PoseRe02`. `<model>.model.json` says `part_transforms_applied`.
- **Texture layers are named by their file slot.** The loader stores file
  slot i at frame +4·i and the sheet asks by engine layer (0x5382aa,
  0x49be2d): slot 3 is the glow map and slot 4 the height map. 1.3.0 named
  layers by format: a slot-3 map without a slot-2 map was written
  `_specMap_` and a slot-4 map `_specSize_`, and the material writers used
  them as specular colour and specular power. They are now `_glow_` and
  `_height_` (15 and 10 textures in each Part 2 set, 23 and 24 in each Part 1
  set; no other layer name changes on 937 / 1,206 textures per set). With
  that, on PC Part 2: 47 model GLBs change materials (25 materials stop
  taking roughness and specular strength from a height map; 25 take their
  emissive texture from the real glow map), and no `roughnessEngine.png` is
  baked from a height map. The format rule stays for a layer whose slot is
  not known (stride walk, drift rescue).
- **Glow maps in the MTL follow the sheet, and the sheet's opacity is
  written.** The engine adds `selfIlluminanceColor × selfIlluminance × glow`.
  A glow layer is linked as `map_Ke`, with `Ke` = colour × selfIlluminance,
  where the first sheet's `selfIlluminance` is above 0; where it is 0 the
  layer is named in a comment and not linked (1.3.0 linked every glow layer).
  The GLB already wrote emission only for `selfIlluminance` > 0. `d <opacity>`
  follows `map_d` for a render-type 0, 7 or 10 sheet with `opacity` below 0.99.
  PC Part 2: 134 of 735 MTL files change (`Ke` added in 92 materials, `d` in
  20, of which 3 are sky sheets, one MTL file each; 36 glow layers named in the comment, 30 of which were linked; 26 glow
  links added, the relabelled maps).
- **Opacity fades only what the engine blends for it.** A sheet's `opacity`
  below 0.99 moves a part to the blended list only for render types 0 and
  10 (0x5739d0), and it fades a SkyBox (7) sheet: the sky pass (0x56f9fb →
  0x58bc85 → 0x589dd9) sends the sheet's opacity to the pixel shader as
  c0.w, `SkyBoxPS` writes alpha = texture alpha × vertex alpha × c0.w, and
  the standard blend type is SRCALPHA / INVSRCALPHA (read from code and
  from the shader bytecode; that the pass enables blending is inferred from
  the state word it sets, not traced to the device call). `materials.alpha()`
  writes `BLEND` with the opacity as base-colour alpha for types 0, 7 and 10
  and for a sheet of unknown type, and the MTL writes `d` for 0, 7 and 10;
  another type (glass, water, hair, wet, sprite …) keeps its own mode —
  whether those passes use the opacity is not established. Measured on the
  sheets of every `sheet.json` of PC Part 2 and PC Part 1: an opacity
  below 0.99 occurs on types 0 (1 sheet per part, `Sewer_Dirt_02`), 1 (22 /
  29) and 7 (7 / 13) and on no other type, so no model material of the six
  sets loses a fade by this rule. Two Part 1 sky sheets store opacity 0.0
  with the standard blend type and no vertex or texture alpha — `skyflash`
  (`skyflash01`, the lightning plane) and `moon_01` (`Sky_Night_01`): they
  are `BLEND` with alpha 0 on the three Part 1 sets, as the sky pass draws
  the stored sheet (whether the game changes the two sheets at run time is
  not established). With blend type add or subtract the sky pass uses ONE
  / ONE and the alpha does not enter; the factor is written all the same.
  A layer written as emissive whose blend reads the source alpha carries
  the opacity as `emissiveFactor` (the light-layer item above):
  `Sky_SunRay_01` (type 7, opacity 0.6, manual SRCALPHA / ONE, where by the
  same trace the opacity does scale the layer) has `emissiveFactor` 0.6 in
  `Sky_Sunset_02` and `CityBackdrop` (Part 1) and `Sky_MainMenu_02`
  (Part 2) on the three platforms (measured on the six-set export); its
  MTL has `d 0.6`.
  `materials.FADED_BY_OPACITY`.

- **Parts 1 and 2 on all platforms: the log.** A line about content that is NOT in the output
  starts with `WARNING:`; a line about an absence that is expected starts
  with `note:` (the lines this entry adds; older lines keep their `!`).
  `extract` gains the sections `STREAM SETS` and `NO STREAM`, the lines
  `SOUND INFO` and `CONSOLE SFX`, and names every model it did not decode.
  The characters log gains one line per GLB without a ragdoll rig (with the
  reason), one per GLB without vertex attributes, and one per mesh piece no
  loader could decode — up to two lines per GLB on a console or Part 1 set.
  `soundmeta` and `textmeta` say how many sounds have no length.
- **`decode_sfx_console` returns the sound record** (truthy) instead of
  `True`; `ragdoll_rig.build(mb)` detects the byte order (an explicit
  `order` still works) and `watchmen ragdoll` prints why a model gives no
  rig; `sound_meta` reads `audio/sound_info.json` when `extracted/` has no
  header, before the decoded-file fallback; `level_meta.find_nav` takes the
  level's asset list.

- **The clip baker follows the engine's rest-pose rule.** Read from code: for
  a track with a constant position (types 1 and 3) the engine adds the bone's
  rest local position to the constant (0x594d38–0x594d49), and its rest pose
  has every parent-less bone at 0 (0x593685). 1.3.0 took such a constant as
  the bone's position and left a root without position keys at its bind
  position. Measured on the body bakes of four sets (PC and Xbox 360 Part 2,
  PC and PS3 Part 1; 6,484 bakes): 36 change, in 8 clips, of which one, in
  two bakes, is a clip the Xbox 360 set misread (see below), so the rule
  itself moves 7 clips (inferred: 34 bakes). `Attach RHand`
  alone moves by 6.9–11.0 cm in `EN1_COM_DMG_WPN_1H_disarm_RSH` and by 7.8 cm
  in `RSH_COM_WPN_2H_heavy_EN2` (the only two non-root tracks with a non-zero
  constant on a bone whose rest position is not 0); the whole body moves by
  the bind's `Bip` offset (2.2, 7.3 or 9.4 cm) in the clips that have no
  `Bip` track: the four `*_WPN_1H_right_arm_layer` overlays and
  `RSH_COM_WPN_1H_idle_drop`. In the Part 2 PC character export (26
  GLBs, 5,731 animations) 22 animations change through this rule, and the
  synthesized `GRIP 1H` pose of the two Rorschach GLBs with them (7.3 cm).
  The two constants are 1.3 cm and 6.6 cm away from the bone's rest position
  (which is 7.8 and 7.1 cm from its parent), so the rule puts the weapon
  attachment about one rest offset away from where 1.3.0 had it; what the
  game shows on these two clips is not established (no capture).
  Face clips are baked on a head model's own node list and do not change (18
  face GLBs, 172 animations: 0 channels differ). A cached bake carries the
  rule's number and a bake of another rule is made again.
  *1.3.0 output:* not available.
- **The clip baker applies the engine's twist-bone pass and binds Part 2
  tracks by exact name.** Read from code: each frame the engine turns every
  twist bone so that its X axis lies on its partner's (0x5958f5, pairs
  0x545019), and a clip track binds to the bone of the same name,
  case-sensitive (0x594dde, 0x53c0dc; an unmatched track is skipped,
  0x594cac). 1.3.0 baked without the pass and matched a track whose name
  differs only by a leading `BipNN `. Measured against captured palettes of
  five skeletons (13,471 matched frames): the pass is closer on 729 of 729
  twist-bone samples it moves by more than 0.5°, largest worsening 0.20°; on
  Part 2 medium, exact names with the pass give a median error of 0.16° /
  0.03° on the two `UpArmTwist` bones against 34° / 30° with the track and
  no pass. Twist-bone channels differ from 1.3.0 in every character GLB with
  body clips; in Part 2 so do medium's four `Bip02 …UpArmTwist(1)` channels
  (no track in 221 of 222 EN1 clips) and `Attach RHand` in 2 gimp clips and 1
  large / small clip. Part 1 character exports keep the prefix-insensitive
  lookup (`characters_export.track_names_for`): 983 Part 1 clips name the
  track `Bip01 Attach RHand`, no Part 1 capture exists and the Part 1
  executable was not read, so the rule there is not established. `watchmen
  bake` and the contact check of `animmeta` bake with the lookup of the
  clip's set as well: prefix for a Part 1 archive or extract, exact
  otherwise. Face clips
  are baked without the pass and with the prefix lookup, as in 1.3.0. Not
  covered by a capture: large, small, bs2 and every Part 1 skeleton. A
  cached bake stores `rule` 3, `twist_align` 1 and its `track_names`; one
  baked with the other lookup is baked again. The baker keeps 1×, 2× or 4×
  the key rate per clip by its mid-frame interpolation-error test on the
  baked palette (`characters_export.bake_cache`, `_lerp_err`), so with the
  new palettes 3 to 11 clips per skeleton are written at twice or half the
  rate of 1.3.0 (`EN4_COM_ATT_heavy_C` 20.31 → 40.62 fps,
  `RSH_COM_DMG_heavy_head_front` 30 → 15 fps): 168 of the 5,731 Part 2
  animations and 547 of the 25,040 Part 1 animations of each set (measured
  on the six-set export; on 23 of these clips of three skeletons the 1.3.0
  baker, run on the same extract, keeps the 1.3.0 rate). Female `Bip02
  Attach LHand` has no track of that name in the EN4 clips (they name it
  `Attach LHand`) and takes its rest pose: it moves by at most 1.5e-6 rad
  in 43 of the 202 animations of each female GLB.
  *1.3.0 output:* no command-line switch; in the library
  `bake_v4.bake(twist_align=False, track_names="prefix")`.
- **`EN4_EXP_MOV_dance_cage_small_C` moves on the consoles.** The scan for
  a clip's track names started at byte 0 of the file. In the big-endian
  copy of this clip the key count 0x372 and the word after it read as a
  3-byte name "r" at byte 11, so the clip was decoded as one unknown track
  and baked as a still pose: 768 equal frames on PS3 and Xbox 360 Part 2,
  where PC has 1,763 moving ones (measured). The header is five words and
  the name list starts at byte 29 in all 6,912 clip files of Parts 1 and 2
  on all platforms (measured), so the scan starts at byte 20
  (`bake_v4.NAME_SCAN_START`); both console files then bake bit-identical
  to the PC cache and the byte order of every clip is detected as before
  (measured). No other raw bake of a console set differs from PC. Per
  console Part 2 set this changes two raw and two jiggled bakes (`bs2`,
  `female`), the 11 GLBs built from them (Twilight Lady, ten Dominatrices)
  and the clip's `game_pivot` and `interact` in `anim_meta.json`, which
  were null. A cached bake stores `scan`; one without it is baked again
  when its clip reads differently from byte 0
  (`bake_v4.scan_start_matters`), which in the shipped data is this clip
  alone, and a resumed `characters` run rewrites a GLB that is older than
  the newest raw bake of its skeleton (`characters_export.glb_is_current(out,
  bakes)`, `newest_bake_time`).
  *1.3.0 output:* not available.
- **`anim_meta.json`: a state's events include its sound-event lists.** A
  state holds plain `FragmentNode`s that name a
  `SoundEvents/SE_<clip>.fragment`; the engine applies such a fragment when
  the property is set (0x498db7), so its events are the state's. They are in
  `classes.<Class>.states[*].events` and in the clip records and clip extras,
  each marked `source: "SE_<clip>.fragment"`: 3,362 events on Part 2 (PC and
  Xbox 360 measured), 2,453 on Part 1 (PC and PS3), mostly footsteps, sounds
  and speech; the Part 1 `RIGHT_FOOT_UP` / `LEFT_FOOT_UP` events (1,035) are
  in no other export. Two Rorschach states gain an `IMPACT_EFFECTS` row in
  `inflicts` and 57 (Part 2) / 44 (Part 1) states `face.notes` entries; no
  face track, pair or placement value changes. `event_names` gains id 3
  (`STOP_R`), and on Part 1 the caption learned for id 6 is `LEFT_FOOT_DOWN`
  where 1.3.0 had `FOOTSTEP`. A list the data does not contain is named in
  `classes.<Class>.missing_event_lists` (1 on Part 2, 5 on Part 1), and
  `sound_meta.json` names the same lists under the same key: Part 2
  `Enemy04`, `SE_RSH_COM_ATT_counter_EN4_B.fragment`; Part 1 `Enemy03`,
  `SE_EN3_COM_DMG_stun_body_back` and `SE_EN3_COM_DMG_stun_head_back` twice
  each and `SE_RSH_COM_ATT_counter_EN3_B`. Apart from that key
  `sound_meta.json` is byte-identical with and without the spliced lists
  (Part 2 PC, Part 1 PC). One list file is stored with a lower-case prefix,
  `se_finished_by_NO_victim02.fragment`; `source` is the file name as stored,
  so its events (9 on Part 2, 3 on Part 1) carry that spelling: count list
  events by `source != "state"` or without regard to case, not by `SE_`.
  The table's `revision` is 5.
  *1.3.0 output:* drop the events that carry `source`.
- **`clips[].loop` is true for every clip a looping state plays**, as the
  state's main clip or as a member of its blend; 1.3.0 set it for main clips
  only. 26 more clips on Part 2 and 21 on Part 1, the run and jog cycles
  among them (`EN4_COM_MOV_run_cycle`, `EN1_COM_MOV_run_cycle`,
  `NTO_COM_MOV_jog_cycle`, the three Rorschach jog cycles, the EnemyBig
  strafes); the arm-layer overlays stay false. In the Part 2 PC character
  export the flag changes in the extras of 135 animations, and the jiggle
  bones of 95 of them are baked as a closed lap (the Dominatrices' and
  Twilight Lady's `EN4_COM_MOV_run_cycle`, twelve EnemyBig clips on the seven
  Gimps).
  *1.3.0 output:* not available.
- **Character GLBs: unused joint slots are 0 and buffer views carry their
  target.** `JOINTS_0` has index 0 wherever the weight is 0 (glTF 2.0,
  3.7.3.3); 1.3.0 wrote the bone index into all four slots of a one-bone part
  and the palette's first joint into the unused slots of some skinned parts.
  Part 2 PC, 26 GLBs: 252,024 slots in 418 accessors change, none with a
  weight above 0, so the skinning is unchanged; every other vertex accessor,
  the inverse bind matrices and the ragdoll files are identical. Vertex and
  index buffer views are marked `ARRAY_BUFFER` / `ELEMENT_ARRAY_BUFFER`
  (7,002 views; 387 in the 18 face GLBs). In `--frame mirrored` the
  `JOINTS_0` bytes therefore differ from 1.3.0's.
  *1.3.0 output:* not available.
- **`watchmen char` writes each clip at its real length and names its
  archive.** A bake written by `watchmen bake` holds the palettes only, and
  1.3.0 wrote every clip at 30 fps: `EN4_COM_ATT_light_A` (2.9 s in the game)
  came out 1.93 s long. `char` takes each clip's length from the extracted
  `.animation` file when its fragment lies under an extract (real data:
  2.9 s at 20 fps, `EN4_COM_MOV_run_cycle` 1.2 s), and prints a note for a
  clip it has to write at 30 fps. `char FRAG.json VARIANT OUT.glb [BINDDIR
  [BAKEDIR [NAZ]]]` and `bake CLIPNAME BIND.npz OUT.npy [NAZ]` take the game
  archive as an argument; without it they read `01_game.naz`, else
  `game.naz`, in the current directory, as 1.3.0 did without saying so, and a
  missing archive is an error that names it. `char` reuses the
  `anim_meta.json` of a `characters` export under the same extract when it
  is current instead of building the table (minutes). Run on real data
  (Dominatrix_1, three clips, Part 2 PC archive, with metadata and
  `--jiggle-model solver`). `char` also looks for the clips of the
  variant's skeleton: 1.3.0 looked for `EN4_*` bakes on every skeleton but
  the female and the gimp one, so any other character came out with 0
  clips, exit code 0 and no message. The families are those `characters`
  bakes (`variant_glb.clip_families`: `EN1` for the three thug skeletons,
  `RSH`, `NTO`, and `EN1` + `EN2` / `EN1` + `EN3` for the big and the fast
  enemies when the fragment lies under a Part 1 extract), and a line says
  so when BAKEDIR holds none of them. Measured: KnotTop_Medium of PC Part 2
  gets 222 of 222 clips and KnotTop_Small of PC Part 1 355 of 355, each
  within 4e-6 s of its `duration_s`; Dominatrix_1 (190 clips) is
  byte-identical. Large, Rorschach and Nite Owl skeletons were not run. `Rorchach.fragment.json` lists no variant with models (measured: "variant
  not found (have: [])"), so `char` cannot build him; the Nite Owl fragment
  was not run.
  *1.3.0 output:* `--no-meta` and a fragment outside an extract give 30 fps.
- **Asset paths have one spelling on every platform, in both parts and in
  every table; `--names stored` gives the archive's.** Each archive stores
  an asset path in the letter case of its own build, and the engine does
  not tell the spellings apart (`name_hash` folds every byte with `& 0xDF`,
  the compare `0x42536e` ignores bit 0x20). 1.3.0 wrote every path and
  every string as stored. `--names canonical`, the default, on `extract`,
  `all`, `characters`, `char`, `charlibs`, `faces`, `particlemeta`,
  `levelmeta`, `animmeta`, `soundmeta`, `fxmeta` and `grademeta` (also
  `$WATCHMEN_NAMES`; `wlib/canonical_names.py`):
  - *The table.* `wlib/canonical_names.json` lists the 41 asset paths whose
    spelling differs between or inside the six game sets, keyed by the
    folded path of one component: 35 textures, 2 models and 4 folders
    (`art/environments/common/Decals`,
    `art/environments/constructionsite/Textures`, `art/props/common/chains`,
    `art/props/common/streetlines`). 40 have their Part 1 spelling: they
    exist in Part 1 and the three Part 1 sets agree on every one. Three of
    them differ between the Part 2 platforms (`Fire_01.BMP`,
    `GarbagePile_01.bmp`, `WallCables_03.bmp`), the other 37 between Part 2
    and Part 1. The folder `streetlines` is stored under two spellings
    inside Part 1 (two models say `Streetlines`) and has the spelling its
    fragments and textures use on all six sets. `extract` writes an asset
    under the table's spelling in `extracted/`, `textures/` and `models/`;
    a path the table does not list keeps the spelling of its archive.
  - *Folders.* A folder is spelled once per export: as the table lists it,
    else as the first asset written into it spells it, and `extracted/`,
    `textures/`, `models/` and `audio/` all use that spelling
    (`canonical_names.share_folders`). `extract` writes every asset to
    `extracted/` before it decodes it, so this is the spelling of that
    tree. A case-sensitive file system gets the single folder a
    case-insensitive one makes. As stored, 5 folders of Part 2 and 21 of
    Part 1 have one spelling in their first model or texture and another
    in their first asset (`Environments` beside `environments`,
    `prison_lamp` beside `Prison_Lamp`).
  - *Loose folders.* The files `extract` brings from beside a loose-folder
    source (`data/Levels/Game_Levels/<Level>/Gameplay/<name>.hpd`, the
    `.bik` movies) are named in lower case, as an archive names its entries
    (none of the 235 entry paths of the four archives holds an upper-case
    letter).
  - *Materials and audio.* A material (OBJ / MTL, GLB material and image
    names) is named after the texture as it was written, whatever letter
    case the model stores. The `file` values of `audio/sound_info.json`
    and of the music sidecars are the paths written.
  - *Tables.* Every string of a table that names a file of the export is
    spelled as that file is written, so it finds the file on a
    case-sensitive file system: the folder `textures/<path>` for a
    texture, `models/<path>.obj` / `.glb` for a model, else the file below
    `extracted/`, `audio/`, `files/data/` or `files/` (a cutscene movie is
    named without the game's `data` folder; in a level file the movie path
    inside a graph label, `MOVIE <path>`, is respelled too). This holds for
    the level JSON
    (`levelmeta`), `particles/index.json`, `fx_meta.json`,
    `grade_meta.json`, `anim_meta.json` and `sound_meta.json`, and for the
    fx attachments a character GLB takes from `anim_meta.json`. The string
    the game stores stays in the same record under `"stored"`: `{field:
    value as stored}` — for a list the list as stored, for a map whose keys
    are respelled `{key written: key stored}`. A path inside a `,` `;` `|`
    list (`textureSheetsDescription`) is respelled in place. Each table
    says which spelling it holds in `asset_names` (`spelling`, `respelled`,
    `note`). In the particle index `respelled` counts each `texture` /
    `model` of a type row, each string of a file row's list and each key
    with a `stored_name` that is written otherwise than the files store it.
    In the particle index a texture or model string is the `dir` /
    `file` of its entry with a leading slash; the entry keeps `stored_name`
    (the spellings of the files) and a file row and a type row hold their
    own strings under `stored`. A table follows the naming of the export it
    is written from (`names` in `_canonical_names.json`) unless the option
    or the variable says otherwise (`canonical_names.export_mode`).
  - *Decoded asset data keeps the stored strings:* every JSON under
    `extracted/` (`.fragment.json` with its `nodes_full`, `.sequence.json`,
    `.particle.json`, `.terrain.json`, `.grass.json`, `.detailmesh.json`),
    the per-file JSON of `particlemeta`, `config` and `config_tree` of a
    `.nav.json`, and the sheet properties (`overrides`) of `sheet.json`. Those are the
    asset, value for value. The `movie` strings of `text_meta.json` are
    table strings and are respelled like those of the level JSON
    (`movies[].movie` and `continue_link.movie`, each with `stored`; 23
    strings on each Part 2 set and 24 on each Part 1 set, after which all
    16 movie strings of a set name their file exactly; measured with
    `textmeta` on PC Part 2 and PS3 Part 1; the other four sets were not
    run). `canonical_names.resolve(
    export_dir, string)` gives the file such a string names, without regard
    to letter case as in the engine; `ExportIndex(export_dir)` with
    `.find()` and `.spell()` does it for many strings.
  - *The record.* `extract` writes `_canonical_names.json` into the output
    folder (format `watchmen-export-names/1`): `renamed`, output name →
    stored spelling for every respelled asset and loose-folder file;
    `twins`, the further spellings one asset has in other blocks; `folders`,
    the other spellings of a folder, per output tree. `renamed` and `twins`
    name an asset as its path is written. A respelled texture has
    `stored_name` in its `sheet.json`, a respelled model in its
    `.model.json`.
  - *Measured on the six sources* (PC / PS3 / Xbox 360). With `--names
    stored` the path lists of the sets differ in letter case only in 14 /
    13 / 12 paths between PC and PS3, PC and Xbox 360, PS3 and Xbox 360
    Part 2, in 6 between PS3 Part 1 and each loose-folder set, and in 304 /
    307 / 317 between the two parts of one platform. `extract` run on the
    six sources on a case-sensitive file system with the two decoders
    replaced by stubs (raw assets, texture folders, model names: 10,386
    paths per Part 2 set, 13,237 per Part 1 set): the nine comparisons give
    0 file paths and 0 folders that differ in letter case only, and in
    every set no folder of `models/` (232 in Part 2, 330 in Part 1) or
    `textures/` (1,316 and 1,660) is spelled otherwise than in
    `extracted/`. Names respelled by the table: 42 / 42 / 44 in Part 2, 11
    in each Part 1 set (9 assets under two of the folders and the two
    `Streetlines` models), plus the 18 loose-folder files of PC and Xbox
    360 Part 1. Material references whose name differs from their texture
    folder in letter case as stored: 48 / 48 / 46 of 2,186 / 2,185 / 2,187
    in Part 2 and 188 / 187 / 187 of 3,525 in Part 1. The three textures
    decoded on the three Part 2 sets: header and stream byte-identical
    between the two namings, the 7 PNGs pixel-identical, `MatressFire_03`
    finds `Fire_01.BMP` on all three. Part 1 PC with the lower-case `.hpd`:
    the six `.nav.glb` byte-identical, four `.nav.json` differ in
    `source.hpd` and nothing else.
  - *Measured on the six-set export* (PC / PS3 / Xbox 360).
    Path lists: 0 file paths and 0 folders differ in letter case only in
    the nine comparisons (three platform pairs per part, the two parts per
    platform), and 0 folders are spelled differently between `extracted/`,
    `textures/`, `models/` and `audio/` of one set (`models/` holds 231
    folders in each Part 2 set and 329 in each Part 1 set, one fewer than
    with the stub decoders, for a reason that is not established;
    `textures/` 1,316 and 1,660). Strings respelled in
    the level JSON (`asset_names.respelled`, summed over the levels):
    6,692 / 6,692 / 6,692 in Part 2
    and 32,033 / 32,033 / 32,033 in
    Part 1, of which 17 per Part 2 set and
    17 per Part 1 set are cutscene movie strings (the
    `movie` of a movie record and the path in a graph label, found below
    `files/data/`); in `particles/index.json`, `fx_meta.json`,
    `grade_meta.json`, `anim_meta.json` and `sound_meta.json` together:
    812 / 812 / 815 and 870 / 890 / 870 (the particle index alone, its
    `asset_names.respelled`: 383 / 383 / 386 and 486 in each Part 1 set).
    Strings of those tables that name an exported file and miss it by
    letter case: 0. MTL `map_` lines (9,925 per Part 2 set, 15,784 per
    Part 1 set), OBJ `mtllib` lines (738 and 1,088) and audio `file` values
    (2,974 and 4,005) that name a file under another letter case: 0.
  - Changed output besides the paths, against `--names stored`:
    `sheet.json` of a respelled texture (`stored_name`), and of 9 Part 1
    textures whose folder the archive stores in lower case (`Decals`,
    `constructionsite/Textures`); `.model.json` of a respelled model; the
    OBJ / MTL / GLB of a model whose material name follows its texture (95
    / 98 / 101 models in Part 2, 140 in each Part 1 set; in a GLB only
    `materials[].name` and `images[].name` differ, the binary chunk is
    byte-equal); the tables named above; the `source.hpd` value of four
    Part 1 `.nav.json`; the extract log (a later copy stored under the
    canonical spelling is not counted as a second spelling: 23 on each
    Part 2 set against 30 / 29 / 29, Part 1 187 as before).
  *1.3.0 output:* `--names stored` (it also writes `_canonical_names.json`,
  with `"names": "stored"`, and the tables written from that export keep
  the stored strings); on a case-sensitive file system the folders split
  again.

- **`animation_type` of a state is computed by the game's rule**
  (`DetermineAnimationType` 0x5f277a, run by `initialize_external` 0x5f0e63:
  the first ACTION criterion with a mapped action, or ENUM CHARACTER_MODE =
  STUNNED, among the state's criteria and then its groups') instead of read
  from the stored property; it changes on 150 of 1,290 Part 2 states and 196
  of 1,279 Part 1 PC states. The stored value is kept as
  `animation_type_stored`; `animation_type_basis` says that the handler
  running for every state is inferred. The combat block follows it: state
  kind, combo speed-up, `reaction_table_sees`, `kill_partner` (25 more
  Part 2 states) and `state_counts`. The table's `revision` is
  4. No switch.
- **Models: triangle-strip buffers are decoded as strips** (engine 0x431206;
  the last u32 of a mesh buffer is the primitive type). OBJ, GLB and
  `decode_model_mesh` change for `Palm_Banana_01`, `palm_banana_02` (Part 2,
  12 render buffers) and `Sky_Night_01` (Part 1, 2); every other render
  buffer and every shadow hull is a list; all occluder buffers are strips
  (79 in Part 2, 141 in Part 1), so `decode_model_mesh(kinds=("occluder",))`
  changes for them (no exported file holds an occluder). Submesh records of
  `<model>.model.json` carry `primitive`. No switch.
- **Walk and run cycles are written at their header rate.** `characters` and
  `char` wrote every clip whose name contains `walk_cycle` 2.3 times and
  every `run_cycle` 2.6 times faster than its header rate (1.3.0 did the
  same); every clip is now written at (keys − 1) / duration. The engine
  plays a page at controller speed × slot `speedFactor` × weight / duration
  (`SetAllSlotBlends` 0x5b5175); the controller speed is the class and
  controller `m_nspeedfactor` times `GetGameSpecificSpeedFactor` (0x5ab837:
  the controller's speed setting times a game-mode factor), with no term
  for the character's velocity (read from code). The slot speed factors
  stay in each clip's extras (`speeds`, 0.93–1.25 on these clips).
  `variant_glb.SPEED_MULT` and `speed_mult()` are removed. 12 clips in each
  Part 2 set and 15 in each Part 1 set, in every character GLB of their
  skeletons. Measured on real data against output written with the 2.3× /
  2.6× multiplier from the same extract and bakes (one character each):
  Rorschach (PC Part 2), NiteOwl (PC Part 1) and TwilightLady (Xbox 360
  Part 2) differ only in their walk and run animations (3, 3 and 2 of 202–295), in the sampler
  times (`RSH_COM_MOV_run_cycle` ends at 1.33333 s instead of 0.51282 s,
  `NTO_EXP_MOV_walk_cycle` at 3.46667 s instead of 1.50725 s,
  `EN4_COM_MOV_run_cycle` at 1.2 s instead of 0.46154 s) and in their
  `extras.watchmen` `written_fps`, `written_duration_s` and
  `events[].written_time_s`; the jiggle channels of those clips
  (TwilightLady's `BreastR` / `BreastL`) are solved at the header rate.
  Every other animation, node, mesh, material and the `.ragdoll.json` files
  are byte-equal. A jiggle memo stores the rate it was solved at
  (`fps`); a memo of a walk or run cycle without it is solved again.
  `docs/ENGINE_CONSTANTS.md` ("SPEED_MULT post-mortem") has the evidence.
  *1.3.0 output:* not available.
- **`all` runs the character export.** Its third step wrote three library
  GLBs (`Gimp2`, `Rorschach`, `Dominatrix`, four to seven clips each, Part 2
  paths, skipped on a Part 1 source) into `OUT/characters`; it now runs
  `characters` into `OUT/characters` (one GLB per variant with every clip,
  and `sound_meta.json`) and takes its options (`--jiggle-model`,
  `--face-rule`, `--no-face-idle`, `--parts`, `--no-ragdoll`). It stops
  after a failed extract step (see "Changed", exit codes).
  *1.3.0 output:* `watchmen charlibs OUT OUT/characters` after `all`.

### Added

- **Level JSON: what the engine builds or decides at load.**
  - Section `waypoints`: the links `WaypointController.WayPointInit`
    (0x8b1062) builds over the start node and its siblings (`next_all`,
    `next_exclusive`), with `force_next`, `force_use_trigger`, flags and
    placement; `m_eforcenext` is non-null on 28 PC waypoints.
  - `culling.groups`, `culling.visibility_groups`, `boxes[].group` and
    `visibility_rule` (0x70e0a4, 0x7052b9, 0x7054b8).
  - `files.stream_blocks`: every `StreamBlock` with the triggers that load
    and unload it (0x847c78, 0x841c78; only Part 1 Prison has any) and
    `referenced_by`, the nodes that name it through `_estreamblock` (the
    seven `TriggerActionCheckpoint` nodes of Prison).
  - Section `lights`: every native `Light` node as stored, a stored type 5 as
    type 2 with `textured` (0x4a1c4a), `flicker` on a `LightFlicker`;
    `conventions.light` has the attenuation rule (0x579fdf). PC Part 2: 2,267
    lights, 180 with flicker.
  - `cameras.tours[*].cuts` are read from the tour's sequence node: the
    `TriggerActionCamera` children of that node (PC Part 2: 198 entries on
    163 of 214 tours — 42 `SET_CAMERA`, 156 `SET_CHARACTER_CAM_DIR`; PC
    Part 1: 128 on 94 of 210 — 46, 79 and 3 `END_TOUR`); `timed_actions`
    (75 and 113) and sequence `speed_factor`.
    Graph edges `sequence_action` (PC Part 2: 1,127) and `tour_sequence`;
    `child` edges of a tour are `tour_refire` without a delay (0x4ab230,
    0x49d529, 0x84b299). `auto_sequences`: `speed_factor`,
    `update_culling_distance`, `actions`.
  - `models[]`: `visible_effective` and `pvs_root` (`visible` follows
    `PVSRootNode` ancestors only, 0x48e028; StreetsOfRiot keeps 36 placed
    `CharacterSimple` nodes under six invisible roots; no cube map's
    `candidate_at_load` changes on the 13 PC levels), `lod_override`,
    `lod_factor`, `include_in_reflections`, `include_in_ao` (0x49d00f,
    0x4a8f99), `part_overrides` (locked, disabled or invisible `SubPivot`s,
    0x4a5907, 0x49faaf: the `interact` part of `SwitchInteractive`, 10
    placements in Part 2 and 17 in Part 1; one Bordello model with two
    disabled door parts), and `motion` on the swinging
    props (`TriggerOscillateBox`, `TriggerFireBarrelEffect`: 0x874b7a,
    0x871b96).
  - Graph nodes: `applies` on general, particle and use-fragment nodes (the
    properties the class's filter shows for the action or use type;
    `wlib/filter_exposed.json`), `sound_params` on `TriggerActionSound`
    nodes (caption → value, 0x861606), `sound_done: false` on the held
    children of a sound action that starts no sound (0x86150a; on no edge of
    the 13 PC levels: the 12 SOUND_STOP actions of PC Part 1 that set the
    flag have no child), labels for use triggers, visibility conditions and
    a reactivatable `TriggerConditionTrue`, "(no effect)" on general actions
    10, 11, 12 (0x85f77b). Enum names for use type, movement type and the
    pivot-controller types; edge kinds `stream_load`, `stream_unload`,
    `grapple_end`, `force_next`, `force_use`.
  - `files.terrain[]`: `drawn_with` and `world_is_identity` — the engine draws
    a terrain with the identity matrix, not the TerrainNode's transform
    (0x49c3be; Xbox 360 0x829d8750 / 0x829a31d0); true on all 24 nodes of the
    six sets.
  - `volumes[].ai_sight.sheet_source`; six volumes store sheet id 0
    (StreetsOfRiot 4, Docks 2).
  - `asset_names.respelled` counts the paths of the new sections too.
  - The Blender importer stores `watchmen_visible_effective` on an instance
    and sorts by the node's own `visible`.
- **Cloth:** `cloths[]` of a ragdoll file gains `mesh_format`,
  `world_fixes_applied`, `world_fixes_rule`. Curtains_01's 74 world fixes are
  applied (buffer format 5; 0x507dd0 / 0x4b96bc); the character cloths are
  format 6 and have no world fix.
- **Combat flags:** `combat.flags.upper_attack` and the new `heavy_attack`
  are computed as the game does (0x5f0e63): 227 and 109 Part 2 states; the
  stored properties are false everywhere.
- **Effects table:** `fx.event_editor_params` — caption, group and range of
  every event argument the editor exposes (16 event ids, 0x5c1767);
  `payload_editor_hidden` on events with set slots the editor does not show;
  `fx.camera.rig.*.transition_editor_visibility` (0x62f298).
- **`bake`** applies the engine's per-frame twist-bone alignment (0x5958f5,
  pairs 0x545019), with `bake_v4.twist_pairs` and `apply_twist_align`;
  `twist_align=False` leaves it out. Measured against captured palettes of
  five skeletons: closer on 729 of 729 samples it moves by more than 0.5°,
  largest worsening 0.20°. A cached bake stores `twist_align` 1.
- **Track names**: `bake(track_names="exact")` matches clip tracks to bones
  by exact name, as the engine does (0x594dde, 0x53c0dc); Part 2 medium's
  four `Bip02 …UpArmTwist(1)` bones have no track (median error against
  capture 0.16° / 0.03°). Part 1 character exports use
  `track_names="prefix"` (not established for Part 1). `POSE_RULE` 3.
  `watchmenlib.bake(track_names=None)` takes the lookup of the clip's set
  (`bake_track_names`: prefix when the archive holds
  `Fragments/Enemy/Biker.fragment`), `anim_meta._ContactCheck` the one
  `characters_export.track_names_for` gives the extract, and
  `bake_is_current(path, clip, track_names)` compares the stored lookup.
  `bake_v4.archive_clip` is the archive walk of `bake`.
- **`anim_meta`**: `layer_index`, `additive`, `force_playpos_1`,
  `layer_weight` on state clip rows; `layer_use` on clips (9 clips per part
  are never a base layer). Measured on PC: 256 Part 2 and 250 Part 1 states
  have two or more layer indices. `conventions.layers` states the rule
  (0x5b7788, 0x592c8d, 0x594cac, 0x592a2f).
- **`rules.underboss`**: `movement`, `flee`, `flamer_volumes`.
- **combat**: `rules.partner_ai.waypoint_move`; the kill-target defect is
  stated with its two effects.
- **`fx.camera.gameplay.exploration.collision`**: the order of the three
  collision helpers and their constants (0x65436e, 0x654196, 0x653883,
  0x653b26, 0x644cc6).
- **Field names read from the loaders.** Terrain, terrain colouring, detail
  mesh, font and pivot-book JSON name their fields after the loader
  (`texture`, `uv_rotation_deg`, `wrap_u`, `numberOfRays`, `primitive_type`,
  `usage`, `book_id`, …); the offset-style keys remain as aliases. A pivot
  book's `book_id` is one u64 in the file's byte order (0x528326), the same
  number for the same book on all six sets (18 files).
  `parse_model_header` gives `skinned_bone_count`, a submesh's `hidden` and a
  shadow hull's `from_cloth` / `cloth_submesh`; `parse_texture_frames` gives
  each slot's `usage`. `property_store_flags.json` lists the 16 properties
  with bit 3.
- **`decode_sequence`**: `actions_fired(delays, last, new)` (0x49d529) and
  `play_position(…, speed=)`.
- **`textmeta`**: `layout_rules`, `parameters` (the `%N` table) and `senders`
  (use prompt, pickup, boss name, warning windows), read from the PC Part 2
  executable; rows list their `params`. Font JSON: `icon` per glyph,
  `fallback_code`, header fields named. `text_assets.layout_wrap` and its
  helpers reproduce the engine's line breaking (0x440c1e). Measured on Part 2
  PC: 58 of 211 glyphs are icons in both game fonts; 125 of the 5,329 aligned
  rows carry `params` (620 rows counted per language).
- **`sound_meta.json`**: footstep rows carry `owned_surface_ids`,
  `inherits_from` and `effective_by_surface` (a package takes the surfaces
  it does not own from its local default package, 0x83325a); the default
  package 58 is written with `role: local_default`; music one-shots are
  every sound-slot child with a sound and carry `class` and `change_on_cue`
  (PC Part 2: 42; Part 1: 30), `groups` lists `MusicGroupCtrl` children;
  `music_rules` gains `playback`, `cue_source` and `one_shots`.
- **A typed fragment stream** is read with its `[typeHash][wordCount]`
  framing (0x545e1b; no shipped file uses it).
- **`parse_model_header`**: `primitive_type` on every buffer and
  `has_cloth_mesh` on a submesh (the old keys `ix` and `no_defer` stay);
  `watchmen_extract.index_triangles`.

- **Jiggle: the `solver` model**, `--jiggle-model solver|pivot|pinned` on
  `characters` and `char`, `jiggle_d6.apply_jiggle(…, model="solver")`.
  *What it does.* In the game the jiggle joint has no drive: every drive
  type is 0, and the file's spring and damping are the joint's soft swing
  limits (45° and 0°). PhysX turns two limited swing axes into one cone
  limit, here of radius 0: a one-sided soft constraint on tan(swing / 4)
  that pulls the whole swing toward zero. `jiggle_d6.SoftLimitJoint` steps
  that row as the DLL does — softness from the file's k and d scaled by the
  cube's inertia about its centre, a 0.7 factor on the position term, 4
  iterations and a conclude pass, the pose integrated from the pre-conclude
  velocity, angular damping 1.0, gravity cancelled — at 1/60 s. Geometry,
  write-back, metre clamp and the one-frame delay are those of `pivot`.
  Only file constants enter (`k`, `d`, `limit` per group, the integration
  rate); nothing is fitted. A clip is stepped at 60 Hz whatever its own
  rate: the parent pose is interpolated between clip frames (Catmull-Rom,
  exact on a frame) and the result is resampled to the clip's frames.
  *Measured.* Against the in-game captures, one physics step per captured
  frame, rotation error rms after the first second (BreastL / BreastR /
  JiggleBelly): `pinned` 4.75° / 4.61° / 3.63°, `pivot` with its
  capture-fitted constants 2.32° / 2.38° / 1.30°, `solver` 2.24° / 2.40° /
  1.63°. On the breasts the file-only solver equals the fitted model; on the
  belly it is behind it in this like-for-like run and level with it (1.34°
  against 1.30°) when the capture's own step pattern is replayed, which only
  the research script does.
  *Established.* The joint configuration and every step of the row
  arithmetic are read from `PhysXCore.dll` and the executable, with the
  constants taken from the DLL's bytes. The file constants are confirmed on
  the captures for both groups: the capture's one-step map matches the
  solver with the file's k (belly 0.899 / −0.778 / 0.798 captured, 0.890 /
  −0.775 / 0.800 solver with k = 70; BreastL 0.809 / −0.673 / 0.680 against
  0.805 / −0.702 / 0.721), and scanning k puts the optimum at the file
  value.
  *Not established, not modelled.* Whether the 0.8 m jiggle box collides
  with anything (not traced; the captures do not need it). Hair: it uses the
  same code with its own constants, but there is no hair capture. Frames
  that take 0, 2 or 3 physics steps: in the game that depends on the frame
  rate; the bake takes one step per 1/60 s. Why the swing orbit dies
  somewhat faster than the model's on a few violent capture events. That the
  kinematic anchor has zero inverse mass in the solver, and which actor is
  `actor[0]`, are inferred. The steady state of a looping clip in the game:
  no capture of one in isolation exists, so the loop bake is validated for
  convergence and a seamless wrap only.
  Also new: `apply_jiggle(…, loop=, lead_in=, warmup=, stats=)`,
  `jiggle_pass.apply_jiggle(…, loop=)`, `clip_loops(meta, name)`
  (`variant_glb`, `characters_export`), `jiggle_d6.SOLVER_MODE` and the
  `SOLVER_*` constants, `MODEL_REVISION["solver"]`;
  `watchmen.JIGGLE_MODELS` lists three, default first.
- **`anim_meta.json`: the face block.** `face_format: "watchmen-face/1"` and
  `face` — the face classes (3), which face class each body class's head
  runs, the four inputs that drive a face, timing constants and the
  attachment; per body state `face` (inputs and the face track that
  follows; 981 of 1,290 states, Rorschach's 309 have none) and `inflicts`
  (hits it deals to the other character); per primary pair `face` with both
  characters' tracks on the pair's clock (240 pairs). Additive: the format
  stays `watchmen-anim-meta/2` and no key of a 1.3.0 table changes name or
  type. See `docs/ANIMATION_META.md`.
- **Character GLBs: `extras.watchmen.face`** on body clips (track, keyed
  poses, which state or pair it came from, what was not baked), on the face
  skin (head model, face class, how the head was chosen, the texture sheet
  used) and `face_pose` on the `FACE …` animations.
- **`watchmen characters … [--face-rule engine|legacy] [--no-face-idle]`,
  `watchmen char … [--no-meta]`**; `characters_export.export(face_rule=,
  face_idle=)`, `variant_glb.write_glb(face_rule=, face_idle=)`,
  `variant_glb.build(meta=)`.
- **`wlib/face_rule.py`**: the face classes, the simulation, the track choice
  per clip, the head-model rule, and `texture_sheets()` / `sheet_records()` /
  `sheet_overrides()` — the sheets of a Texture header (`name`, `uniqueID`,
  the eight `<layer>MapOverride` paths) and the sheet a collection node
  selects. `face_synth.blend_locals()`.
- **`sheet.json` beside each extracted texture** whose header has a texture
  sheet: `renderType`, `twoSided`, `alphaThreshold`, `opacity`, `blendType`,
  `normalMapPower`, `isLit`, `writeDepthBuffer`, `enableNormalMapping`
  (`watchmen_extract.texture_sheet`, `read_sheet_json`,
  `TEXTURE_SHEET_PROPS`, `SHEET_RENDER_TYPES`). Written for PC and console
  textures, from the texture's first sheet. `twoSided` is the byte the
  renderer turns into `D3DCULL_NONE`; `renderType` 1 is "Standard with
  blending"; `alphaThreshold` is the alpha-test reference (the D3D9 capture
  shows `D3DRS_ALPHAREF 95`); `normalMapPower` scales the normal map's x and
  y; `blendType` 2 is subtractive. `opacity` fades a type 0, 7 or 10 sheet
  (see "Opacity fades only what the engine blends for it").
- **Vertex colour.** `COLOR_0` on the 387 Part 2 PC models whose mesh
  buffers have authored colours. In the game's shaders the colour multiplies
  the complete lit colour (rgb) and the texture's alpha (a); it is not
  ambient occlusion, a layer mask or a wind weight. Buffers whose vertex
  alpha varies — 53 in the corpus: decals, puddles, sky layers, Rorschach's
  ink-blot layers — get `alphaMode: BLEND`.
- **`--no-vertex-attrs`** (see "Behaviour changes") and
  `watchmen.VERTEX_ATTR_COMMANDS`.
- **Texture lookup API.** `watchmen_extract.TexRef`, `TextureIndex` (with
  `resolve()`, `by_path`, `candidates`, `ambiguous()`), `resolve_texture()`,
  `texture_ref()`, `texture_key()`, `unique_material_names()`.
- **Vertex attribute API.** `watchmen_extract`: `ati2_xy`,
  `gltf_tangents(…, green_up=)`. `rig_glb`: `linear_vertex_colors`,
  `srgb_to_linear`, `gltf_normal_png`, `material_alpha`;
  `build_rigged_glb(…, has_color=, has_alpha=, engine_materials=)`;
  `mesh_vertex_attributes` also returns `has_alpha`. `variant_glb`: `Part`
  (the 6-tuple of a mesh part, carrying `.attrs`), `with_attrs`,
  `keep_attrs`, `buffer_vertex_attrs`, `VERTEX_ATTRS`,
  `vertex_attrs_enabled`. `char_lib.load_parts` returns `Part`s, which
  unpack like the tuples they replace; `_find_layers` adds the texture's
  `sheet`.
- **Outfits and weapons:** `characters --parts game|all`
  (`WATCHMEN_PARTS`, `export(parts=)`); `wlib/parts_rule.py` (`members`,
  `outfits`, `outfit_record`, `weapon_record`, `clip_weapon_use`);
  `variant_glb.write_glb(…, outfit_parts=, alt_parts=, parts_record=,
  asset_extras=)`. `characters_export.char_weapon_colls` reads a character's
  two weapon collections from its own `CharacterDef`
  (`m_emodelcollbash1h` / `m_emodelcollbash2h`).
- **Texture sheets:** `sheet.json` lists every sheet of a texture under
  `sheets` (name, uniqueID, all properties, layer `overrides`); the top
  level stays the first sheet. `watchmen_extract.texture_sheets`,
  `select_sheet`, `sheet_blend`, `blend_layer_image`, `blend_material`,
  `sheet_layer_dirs`; `characters_export.variant_nodes`, `sheet_records`
  (both `textureSheetsDescription` versions), `variant_sheets(…, node=)`;
  `char_lib.sheet_ref`, `load_parts(…, sheets=)`.
- **Metadata:** `weapon_use` per clip (the weapon class the clip is played
  with — UNARMED / BASH_1H / BASH_2H — and its basis; 177 of 1,159 clips),
  `blend_position` per state clip, `character_mode` per face record, and for
  each paired hit the pose and face state it would have with the attacker
  behind the victim. `asset.extras.watchmen.reconstruction` marks a variant
  the game does not ship (see "Fixed").
- **`kapow_json.load_fragment` / `find_fragment`**: one loader for fragment
  data, see "Fixed".
- **Materials:** `--materials engine|legacy`; `wlib/materials.py`
  (`engine_material`, `alpha`, `roughness`, `f0`, `gradient`, `apply`);
  experimental options in `$WATCHMEN_MATERIAL_OPTS` (`sheen=1` writes
  `KHR_materials_sheen` for falloff sheets).
- **`<model>.model.json`** next to each extracted model (format
  `watchmen-model-meta/1`): LOD count, switch distances and fades, and how
  many shadow-hull and occluder buffers were left out. The buffer kind
  `proxy` is now called `occluder`, which is what the engine uses it for;
  `proxy` is still accepted by `select_model_buffers(kinds=…)`.
- **`watchmen grademeta EXTRACT_OUT OUT.json`**: the post-process settings of
  every level (brightness, saturation, contrast, tint, gamma, bloom, fog)
  with the formula the game applies and, as `platform_adjustment`, what the
  options script adds to a node's brightness, contrast, gamma and saturation
  (the mapping, the four formulas and the PC / Xbox 360 / PS3 centres; on PC
  at the middle setting +0.05, +0.11, +0.12, 0;
  `materials.grade_adjustment(platform, value)`). The option values in force
  are not established, so node values are written as stored. `formula` says
  what `enableFilters` gates: the bloom filter, the grade, gamma and noise
  (noise also needs a noise texture and an intensity above 0), not depth of
  field or edge anti-aliasing; fog, LOD, light fade and shadow values always
  come from the first enabled node of the level, not from the camera's node. A level holds
  several sets and the game script blends them; the file lists them all.
- **Ragdoll:** `watchmen ragdoll MODEL [PIVOTBOOK.pb] [OUT.json]`;
  `--no-ragdoll`; `wlib/ragdoll_rig.py`;
  `skeleton_records.parse_articulated_body`, `parse_pivot_book`,
  `read_property_records`; `parse_model_nodes.model_physics`.
  `common.material` says how the engine uses the sheet's one friction value
  (static = dynamic, combined by multiplying; restitution by averaging:
  0x51555a). A cloth carries `physx`, what the engine's cloth descriptor
  holds beyond the stored properties (the flag word, the constants), and its
  `attachments` are `{vertex, cloth_body_node_index, world_fixed}`
  (0xFFFFFFFF = pinned to the world, else the node of a cloth-scene body).
  `ragdoll_rig.build(mb, cloth_only=True)` and the module's command line
  also read a model that has cloths but no ragdoll (`Curtains_01`);
  `cloth_flags`, `cloth_physx`, `cloth_attachment`.
- **Sound:** `watchmen soundmeta EXTRACT_OUT OUT.json [ANIM_META.json]` and
  `OUT_DIR/sound_meta.json` in a `characters` export (format
  `watchmen-sound-meta/1`, `wlib/sound_meta.py`): sound definitions with
  their play tree and variation rule, the SOUND / SPEAK / footstep events of
  every animation state resolved to definitions, waves and durations, the
  footstep table, attack and hit sounds, speak groups per character with
  voices and line lengths, music setups. The rules that decide what is heard
  are in the table where they are read from code: `speak_rules` (which
  playing lines block a new one; `blocks_while_playing` per speak),
  `speak_triggers` (with the senders of ids 8, 9, 36, 37 and the
  `EffectSpeak` and Underboss ids), `effects.attack_start_rule`,
  `effects.ragdoll_contact` (the force-to-volume curve, body-part masks and
  gates) and `music_rules`; a music track's `change_on_cue` is named
  (`change_on_cue_mode`: at once, at the next cue, at a named cue;
  `change_on_cue_name`: the cue of the setup's stream whose unfolded name
  CRC it is — 473 of 473 named values of the PC Part 2 table and 371 of 371
  of Part 1 resolve), and a setup lists its `cue_names`.
  `sound_meta.cue_hash`, `cue_change`, `blocks_while_playing`. `audio/sound_info.json`
  (`watchmen-sound-info/1`): rate, length, loop flag, 3D flag, codec and cue
  points of every PC sound (console extracts: see "Parts 1 and 2 on all platforms: new
  output"). A looping PS3 sound's `segment_word4` is the byte length of two
  MP3 frames (145 of 145 looping sounds of both PS3 sets); the record says so
  with `segment_word4_rule` and `loop_skip_frames`. `extract --flat-music`, `--music-track-labels`,
  `--smpl-loops` (the loop flag as a RIFF `smpl` chunk).
- **Metadata:** `anim_meta.json` `conventions.ragdoll_values` says what the
  four ragdoll animation values hold that get-up states test (pelvis
  rotation, ragdoll free, pelvis velocity, ground height;
  `CharacterVisual.command_update_ragdoll` 0x6bc3e2), and
  `anim_meta.pelvis_rotation(q)` computes the first. `fx.damage_rule` notes
  that the Twilight Lady's fake weapon is null in shipped data.
  `kapow_props.native_message_signature` / `native_message_hash`: the hash a
  native message is registered under (argument names erased, 0x4f9504).
- **Metadata:** `anim_meta.json` events keep `_etarget00`, `m_ivalue00` and
  `m_ttruth1`; `face.talk_clips` lists, per character, the voice lines that
  open the mouth with their length per voice.
- **`tools/ghidra/FixNoReturn.java`** and **`tools/ghidra/names2.tsv`** (see
  "Data tables" and `tools/ghidra/README.md`).
- **Combat metadata** (`wlib/combat_meta.py`, `docs/COMBAT_META.md`).
  `anim_meta.json` carries the game's combat rules, marked `combat_format:
  "watchmen-combat-meta/1"`:
  - every state: `group_criteria` (the criteria inherited from its state
    groups, outermost first, with each group's random-pick flag) and
    `criteria_rendered`, both rendered from the stored values rather than
    from the node captions;
  - every attack state: a `combat` block — attack class (light / heavy),
    weapon classes, entry kind (initial / dash / general), required combo
    override, base damage × damage modifier per owning CharacterDef and
    weapon class with the source of each input, PRE_IMPACT / IMPACT / BRANCH
    timings as play position and seconds from entry (the state's own event
    records), the entry play position of a combo continuation, reach and its
    modification, sweep parameters, the damage pose delivered, and what the
    defender can do (counter window, whiff distance, what the reaction table
    sees). Counter / finisher / throw masters, dodges, blocks and hit
    reactions get a short block;
  - every pair: a `trigger` block — rule (counter / enemy_counter / finisher
    / throw / bull_rush), control action, opponent model and weapon
    requirements, distance, damage source with the event and time that
    applies it (a throw has no damaging event: its `damage` names ragdoll
    contact damage, the release speed, the 3 m fall rule and what bystanders
    get), breakout window, finisher prompt numbers;
  - top level `combat`: the rules as data with their script handler and exe
    constants (damage formula and what the victim does with the number,
    unblockable, reaction table, counter, whiff, sweep stepping, ragdoll
    contact damage, who may attack when, Twilight Lady's reaction routine,
    the area attacks, finisher prompt, damage-pose conversions), every combo
    database (strings
    with the override in effect per step and the attack groups each step
    draws from), CharacterDefs with the animation class they use, AI
    definitions with their reaction rows and effective damage modifier (a
    stored 0 means the CharacterDef's value: 9 of the 31 definitions, which
    resolve to 1.0 or 1.5), weapons, per-class links and totals;
  - **throw damage.** The combo database's `throw_damage` has no reader in
    the game (`throw_damage_used: false`). A thrown body loses health only
    through ragdoll contact damage, `mass × min(|(0.2Fx, Fy, 0.2Fz)|, 4000)
    × 0.00007` per contact (`combat.rules.ragdoll_damage`, at most mass ×
    0.28 per contact; `combat_meta.contact_damage_cap`), or 100000 when it
    ends more than 3 m below the thrower. It is released at 9.0 m/s (5.0
    m/s for a big victim: 8 and 2 of the 10 throw pairs). Standing
    characters it hits take 0 damage and a 3 s stun. How much health a
    throw removes in practice depends on run-time contact forces and is not
    established;
  - `combat.rules.damage.receive` and `.death`: the receiving side of a hit
    in code order (reverse-direction window, Underboss factor, paired-move
    filter, incoming factor, the `max(1/uber, 0.7)` clamp on playable
    victims, floors) and the hero-versus-hero death outcomes;
    `combat.rules.pair_damage` has the three area attacks (FLASH_GRENADE,
    DISCHARGE_ARMOR, ELECTRIFY_ARMOR); `combat.rules.sweep`,
    `.attack_permission` and `.twilight_lady_reaction` hold the stepping of a
    sweep (one check per 0.05 of play position; `m_nchecksprsec` is never
    read), who may attack when, and her reaction constants.
  Part 2 PC: 336 attack states (Enemy01 52, Enemy04 49, EnemyBig 58, NiteOwl
  83, Rorschach 94), 413 pair triggers (257 counter, 118 finisher, 22 enemy
  counter, 10 throw, 6 bull rush), 12 combo databases, 14 CharacterDefs, 31
  AI definitions. A failing combat step logs `combat: skipped (…)` and leaves
  the table without the block; it never takes the animation table down.
- **Effects, camera cuts and rumble** (`wlib/fx_meta.py`, format
  `watchmen-fx-meta/1`, `docs/FX_META.md`). `anim_meta.json` gains:
  - on every event `payload` — the argument slots of the event node that are
    set (`_etarget00..02`, `m_ivalue00`, `m_nvalue02..10`, `m_ttruth1..3`,
    `m_vvalue1/2`) — and `payload_stale`, the set slots the handler of that
    event id never reads (event nodes are copied in the editor and keep the
    values of their former id);
  - on a state `fx`: `impact_effects` (damage pose, impact point and
    direction), `camera_cuts`, `camera_return`, `rumble`, `look_at`,
    `weapon_events`, `slow_motion`, each with the play position, the clip
    time and the play time of its event;
  - on a pair `camera_cuts` / `camera_return` on the pair's shared clock and
    `fx` (shot list with real-time lengths, impacts of both actors, rumble,
    weapon events). The finisher and counter cameras are procedural, driven
    by these events; there are no camera tracks;
  - top-level `fx`: the effect database (81 effects with their particle /
    sound / speak children; sounds are keys into `sound_meta.json`), the
    three per-character effect definitions, the damage-effect rule
    (`CharacterEffectDef.command_play_damage_effect` 0x6673d0) as data,
    weapons with their effect type, particle durations, the GFX half of the
    effect type × surface matrix, character attachments (emitters and light
    flashes on joints), the cut placement rule, the camera modifier constants
    and the per-player camera rig.
  Part 2 PC: 279 states with `fx`, 259 camera cuts, 122 pairs with cuts (789
  pair cuts; 16 of them sit on the partner's state — `Enemy04` `Counter_A|B`
  against the players' `Countered_by_BS2_cattleprod_A|B` — and carry `actor:
  "partner"` and `coop_full_screen: true`).
  - The cut camera does not follow the looked-at character: its position is
    fixed for the shot and only the aim tracks (`UpdateWorldPos` 0x633f28 has
    no caller on PC, Xbox 360 or PS3; hold update 0x633011). Every cut has
    `look_at_point` (`joint` or `root`); `look_at_joint` is `null` for bone
    type 18, which is the looked-at root and not a joint (4 state cuts).
    Every shot and slow-motion interval has `blend_s`,
    `blend_from_multiplier` and `real_s_basis`; `fx_meta.halfbell()` and
    `fx_meta.blend_real_s()` give the engine's blend curve and the real time
    a time-scale blend takes. `fx.camera.cut_placement.return` describes the
    way back to the character camera; `fx.camera.modifiers.cut_shake` says
    that a cut's shake is not applied by the cut camera. An invalid blend
    makes a cut hard, it does not reject it; co-op keeps the split screen
    except on the 16 slave-state cuts.
  - `watchmen fxmeta EXTRACT_OUT OUT.json [ANIM_META.json]`: the same data as
    one table.
  - `fx_meta.cut_camera()` places a cut's camera from the two characters'
    root positions (`SetValidStartPos` 0x6341f7: angle from the pair line,
    side shot at angle 0 at the height of the midpoint of the two roots plus
    `height_m`, kept position — the previous cut's, or the character
    camera's when there is none) and returns `fallback`, the two side
    positions an angled cut falls to when its sweep (width = height = 0.2) is
    blocked; `fx_meta.damage_slots()` /
    `resolve_slots()` answer "which effects does this pose fire".
  - Character GLBs: `asset.extras.watchmen.fx_attachments` lists the emitters
    and light flashes the game hangs on the character's joints; a clip's pair
    entries carry `camera_cuts`, `camera_return` and the combat `trigger`
    (`anim_meta.CLIP_PAIR_EXTRA_KEYS`), its events `payload`.
  - `fx.particles` is read with the particle parser below (both byte orders,
    the Part 1 record layout), falling back to the generic walk.
- **Levels** (`wlib/level_meta.py`, `docs/LEVEL_META.md`). `watchmen
  levelmeta EXTRACT_OUT OUT_DIR [LEVEL ...]` writes one `<level>.level.json`
  per level (`watchmen-level-meta/1`) with the fragment tree and its world
  transforms, character / model / volume placements (world transform in
  engine coordinates, and the glTF node transform that places a toolkit GLB,
  in the GLBs' frame), character definitions and the export folder each maps to, the
  condition / action graph with enum names and resolved targets, checkpoints
  with their restore scripts, camera tours, movies, game events, the
  reapplyable (run-time) fragments, and the level's **path objects** (doors,
  gates, climb-ups) joined by id (position as cross-check and fallback) to
  the path-object table of its navigation data: the id is the 1-based index
  into the `aiStaticPathObjectNodes` list of the level's AIWorldNode (lookup
  0x4837d5), exported as `level.ai_world` and `path_objects[].ai_world_index`;
  `path_objects[].nav.method` says which join was used and `nav` has
  `linked_by_id`, `linked_by_position_only` and `id_position_disagree`.
  `path_objects[].bound_at_run_time` (and `counts.path_objects_unbound`)
  says whether the game binds the node to its path data: the path data's
  path object finds its node by id, stores itself in the node and takes over
  its impassable flag (0x48c249 -> 0x4837d5), and
  `AIStaticPathObjectNode::SetIsImpassable` (0x48a559) reaches the path data
  only through that link (read from code), so a node that is not in the list
  is in the level but unknown to the path finder. Measured on the six-set
  export, the same on the three platforms: every path-object table has as
  many entries as its level's list; unbound are the 4 nodes of Part 1
  ConstructionSite (all disabled; list and table empty), 1 of the 15 of
  Part 1 Streets (an enabled copy of the `StreetsRollerDoor` template's
  nodes placed in `MissionStructure.fragment`; list and table 14) and the
  Bordello node of the null list entry 45.
  Part 2 PC: 6 levels, 0 unresolved references; Part 1 PC: 7
  levels, 0 unresolved.
  - What the level file fixes about the model and weapon of a placed
    character. `character_defs[type].export` lists the model collection's
    `members` (sibling order, unnamed ones too, with `priority_model` and
    `head_model_type`) and the two weapon collections; `characters[].variant`
    and `characters[].weapon` give `status` (`fixed`, `candidates`,
    `fixed_scene_model`, `none`, `unknown`), the member indices, the
    requested priority and whether a member matched it. The picker
    (0x66ca15) takes the last member whose priority equals a non-zero
    request, else the least-used member, first in order on a tie; a `candidates`
    result depends on the history of the play session. Staged Part 2 PC
    fragments, Bordello / NightClub / StreetsOfRiot: variant fixed 16 / 2 /
    0, candidates 151 / 168 / 143; weapons fixed 33 / 41 / 39, candidates 11
    / 5 / 18 (the staged StreetsOfRiot lacks its two hero placements). The
    full Part 2 PC extract, six levels and 488 placements: variant fixed 26
    (14 by a single member, 12 hero placements with `fixed_scene_model`),
    candidates 462; weapons fixed 113, candidates 34, none 341.
  - `characters[].ai_start`: `state_of_mind` (PASSIVE / AGGRESSIVE / unset)
    and the SET_AI_STATE actions that list the character (105 / 79 / 43
    actions in the three levels). A PASSIVE enemy idles or returns to its
    combat zone; it does not chase or attack (`Enemy.Evaluate` 0x726214).
  - `combat_presets`: the combat orchestrator's start values and the level's
    switches to a preset. `groups[].zone_trigger`; `groups[].return_position`
    is the position the engine computes at start (the return point, else the
    first member, +0.5 m in y; `return_position_source`), because the vector
    stored in the file is overwritten at run time and is stale in the
    shipped levels (all zero in Bordello and NightClub); the stored one is
    `return_position_stored`.
  - `cube_maps`: every CubeMapNode with its texture. A surface reflects the
    nearest CANDIDATE node (0x4d1299); the candidates are rebuilt every frame
    from the nodes that are enabled up the tree and visible on the node and
    on its `PVSRootNode` ancestors (0x4d5ca9, 0x48e028). The run-time
    switch is `CullingCtrl` hiding `CullingVisibilityGroup` nodes, which
    are `PVSRootNode`s, that no culling group around the camera lists
    (0x70e0a4, 0x7054b8 → 0x48f69a). Each node carries `visible`,
    `visible_effective` and `candidate_at_load`, and every model placement
    `cube_map` = the nearest candidate of the file state (`uid`, `texture`,
    `distance`, `same_fragment`); `cube_map_rule` states the limits.
    `cube_maps[].visibility_groups` / `pvs_roots`,
    `culling.groups[].cube_maps`, `culling.cube_maps_no_box` and
    `models[].cube_map_by_area` give the cube per culling area, with
    `counts.models_cube_by_area_single`, `_multiple` and
    `_single_differs_from_file_rule`. Measured on three D3D9 captures,
    counting the draws whose pixel shader samples a cube: the nearest
    candidate under the culling rule is the bound cube in 4,041 of 4,041
    draws of 87 frames (file state alone 3,254 of 4,041) and in 659 of 659
    draws of 18 other frames (nearest of all nodes of the level file 586:
    Bordello 328 of 328, NightClub 258 of 331). In the Part 2 sets all 152
    nodes are candidates at load. Per placement (PC Part 2): the cube is
    the same in every area for 2,157 of 3,043 models in Bordello, 2,846 of
    3,737 in NightClub and 2,559 of 3,564 in StreetsOfRiot, and for 311,
    403 and 22 of those it is not `cube_map`.
  - `models[].opacity` and `models[].cast_shadow` (the node flags the
    renderer reads: 0x5739d0, 0x4995c6), and the section `culling`: the
    `CullingBox` nodes with their box and the inside rule (0x7111b9).
    `movies.*.subtitle_table` (the same table name
    as `movies[].table` of `text_meta.json`) and `continue_link`. Eleven
    more `counts`.
  - `models[].local` (position and quaternion as stored) and
    `models[].parent_chain_without_transform` (the script class of each
    ancestor between the node and its nearest ancestor with a transform),
    with `counts.placements_below_transformless_ancestor` and
    `counts.parent_link_1`. The rule "the parent is the nearest ancestor
    with a transform" is confirmed against the terrain on StreetsOfRiot
    (measured: 188 of 282 ground props below such an ancestor within 5 cm of
    the terrain, 0 of 150 within 1 m with the local transform taken as the
    world transform). A node with `parentLink` = 1 is composed with its
    parent like any other (engine 0x49325d, 0x48d789: the flag only gates
    later parent moves in play mode); no PC Part 2 node has it and Part 1
    levels do (3 per game level, 21 in ConstructionSite, 0 in MainMenu;
    measured on PC, PS3 and Xbox 360 Part 1); ConstructionSite's 21
    `PivotNode`s lie in the frame of their Group at y = 36.
  - `models[].host_offset_copy` (`{twin}`) marks a model node that keeps
    level coordinates under a moved fragment host while a node with the same
    stored position (and a stored quaternion equal within 1e-5 per
    component) is placed under a parent that cancels the host:
    StreetsOfRiot block C has ten such `CharacterSimple` nodes 50 m above
    the street (seven with a twin at the same stored position, one for each
    of the seven placed ones); the key is on those ten and on no other
    record of the six PC Part 2 levels and seven PC Part 1 levels
    (measured). The composition is right; that they are an editor leftover
    is inferred, and whether the game draws them is not established.
    `counts.host_offset_copies`, `conventions.host_offset_copy`.
    `tools/blender_import_level.py` puts the flagged records into a
    switched-off collection, `<Level>` > `Host-offset copies`.
  - `watchmen savemeta FILE [OUT.json]`: `.kpw` save files as JSON
    (`watchmen-save-meta/1`); both files of a real profile decode completely.
    `decoded.button_map` names the controller map of `SETTINGS.kpw`
    (`m_emetadevicebuttonmap`, 675 words): save device, player, logical
    button and up to three codes, with the `SAVE_DEVICES` and
    `LOGICAL_INPUT_BUTTON` names read from the executable. `code_names`
    names the codes per device from the engine's `GamepadButton` (0x4d3514),
    `KeyboardKeys` (0x4cc842) and `MouseButtons` (0x4db801) enums
    (`wlib/input_code_enums.json`, read from code). That these enums number
    the codes — pad values on the pad devices, key values and 256 + mouse
    button on `KEYBOARD_MOUSE` — is inferred from the fit: all 16 pad codes
    and 19 keyboard codes of the one profile have a name; the code that
    fills the map and the 256 offset were not read.
  - `files.blocks` are the level's two block file names, taken from the top
    fragment's path and lower-cased as the archives store them: the Part 1
    level `Streets2` is `street2.block_*` and `Undergound` is
    `underground.block_*` (checked against the archive directory and the
    loose Part 1 trees on all 39 levels).
  - `volumes[].ai_sight`: whether the AI sight ray reports a collision node
    and whether it blocks — its pivot sheet has a bit of the level's
    `AIWorldNode.collisionMask`, and the node is a rigid body (`physicsType`
    1); a stored sheet id 0 is no sheet (0x4a4c44): mask 0, `blocks` false
    (StreetsOfRiot 4, Docks 2 volumes); `null` where a property is not stored
    (no exported volume lacks one) or a non-zero id is in no pivot book read;
    `sheet_source` says which case holds. The rule is read from the ray
    callback 0x48b44e. The sheets are those of the extract's pivot books
    (42 in Part 1, 47 in Part 2), else the bundled `wlib/pivot_sheets.json`.
    PC Part 2: 218 / 409 / 157 / 10 / 13 blocking volumes in Bordello /
    NightClub / StreetsOfRiot / Tutorial / PlayerVsPlayer, every placed
    vision blocker among them (124). `level.ai_world` carries `asset`,
    `collision_mask`, `node_collision_mask` and `generation` (the path-data
    generation inputs; the executable cannot regenerate).
  - `graph.nodes[].forced_state` on a `REQUEST_FORCED_STATE` action: the
    state (by its `ENEMY` enum name), the AI type it is meant for and the
    stop criteria and time the action sends in either case
    (`TriggerActionCharacter.ActionExecute` 0x85b858). PC Part 2: 17 in
    Bordello, 1 in PlayerVsPlayer; the four of the Twilight Lady fight ask
    for `TWILIGHT_LADY_BACK_FLIP` for 0.05 s.
  - `level.hero_models`: the nodes and models the level's `LevelSceneCtrl`
    names for the two heroes (`Rorschach_Dry` / `NightOwl_No_MaskDry` in the
    five Part 2 play levels, the wet ones in the menus and in Part 1's Docks
    and Streets). `characters[].weapon.no_collection`: the placement asks
    for a weapon its definition has no collection for and gets none (12 of
    the 188 armed Part 1 placements, none in Part 2).
  - `level_meta.ENEMY_STATES`, `STOP_CRITERIA`, `AI_BRAIN_ENUMS`,
    `SAVE_DEVICES`, `LOGICAL_INPUT_BUTTONS`; `forced_state`, `ai_sight`,
    `pivot_sheets`, `button_map`.
  - `anim_state_machine`: references are resolved the engine's way when
    fragment headers are known — tag 5 through the singleton index (name hash
    of the fragment name or file stem), tag 4 with its level count, a
    depth-first search that does not enter nested fragments, tag 3 inside the
    own instance. `load_tree(hosts="all" | callable)` splices every fragment
    host (default unchanged: state groups); asset paths are matched
    case-insensitively. `anim_meta.json` is byte-identical for Part 1 and
    Part 2 PC with the new resolution.
  - `kapow_fragment.parse_header`, `FRAGMENT_HOST_NATIVES`, `type_name_ok`.
- **Text and subtitles** (`wlib/text_assets.py`, `docs/TEXT_ASSETS.md`).
  - **Every text asset, every language.** `extract` writes
    `text/<en|fr|it|de|es>/<asset>`: the raw `textRes` table, a decoded
    `.json` (rows in order: index, key, text) and a `.csv` (UTF-8 with a
    byte-order mark, which Excel needs to show the accents), plus
    `text/index.json` — menus, tutorials, warnings, key names, the in-game
    subtitle table and the cutscene subtitle tables (15 assets, about 5,300
    strings per language in Part 2, 4,500 in Part 1). 1.3.0 did not read the
    localized block records at all. `--no-text` switches it off; `watchmen
    text NAZ_OR_FILES_DIR OUT_DIR` adds the folder to an existing extract
    without touching anything else. PC and console (big-endian) blocks, Parts
    1 and 2.
  - The block's six language slots are English, French, Italian, German,
    Spanish, Danish (slot = the engine's LANGUAGE value). The Danish slot of
    the shipped games is a copy of the English one and gets no folder.
    `--language N` (a slot number or a language name / code) still selects
    the slot written to `extracted/`. Language records carry `engine_code`
    (uk, fr, it, de, es, dk), and `text_meta.json` `selection` holds how PC,
    Xbox 360 and PS3 map the system language to a slot (anything unlisted
    is English; the Danish slot cannot be reached on PC).
  - `watchmen textmeta EXTRACT_OUT OUT.json` (`watchmen-text-meta/1`): all
    strings per language with key and source asset, and the subtitles joined
    to the audio — wave → key → lines per language with times, and per speak
    group / line / voice the waves with their subtitle. A sound finds its
    subtitle by the file name of its wave, cut at the first `_uk`, then the
    first `_pc` (case-sensitive cuts, 0x4d89d0; the table lookup folds A–Z).
    `text_assets.parse_subtitle_key` does not cut a name at 127 characters
    and drops an end time that lies before the start (`0 <= end < start`),
    as the engine does.
  - `text_meta.json` `movies`: every movie player with its `.bik`, the
    subtitle table its slot names, and the lines with `from_s`, `to_s` and
    `shown_from_s` (a line that starts before an earlier one has ended
    appears when that one ends). Part 2: 16 players, 9 with a table, 94
    lines; Part 1: 16 / 9 / 183. `subtitles.rules`: the two ways a sound can
    ask for a line, the one-owner priority rule, the option being off by
    default, and the clock (real frame time).
  - `sound_meta.json`: speak waves carry `subtitle_key`.
  - `text_meta.json`, per subtitled sound: `routes` and `referrers` — which
    reference properties of the extract's fragments reach a `SoundDef` above
    the wave (`speak_group`, `trigger_action`, `other`) — and `unreferenced`
    when none does: 56 of the 1,205 subtitled Part 2 waves (54 leaves of
    SoundDefs nothing points at, 2 test-sound values), 174 of 1,807 in Part
    1. `audio_start_delay_s`: the definition's start delay, by which a line
    leads its audio. Per line `languages_missing` (and `shown_in`) when a
    language's table has no such row, counted in `subtitles.incomplete_lines`
    (21 in Part 2, 19 in Part 1; `EN2_THGSpotRSH_GMP1_11` has German and
    Spanish rows only). Per movie `frames`, `fps` and `duration_s` from the `.bik` header when the
    file is in the extract (every subtitled Part 2 movie ends after its last
    row). An archive holds the movies; for a loose-folder source (Part 1 on
    PC and Xbox Live) `extract` copies the 12 `.bik` from the sibling
    `data/Art/cutscenes` to `files/data/Art/cutscenes`, 568 MB per set (not
    with `--no-files` or `--no-nav`: such an extract has no movie lengths). `text_assets.bik_header`,
    `sound_def_referrers`, `routes_of`.
- **Particle systems** (`wlib/particle_asset.py`, `docs/PARTICLE_FORMAT.md`):
  the engine's `.particle` grammar (format `kapow-particle/2`), read from the
  loader 0x55d3ed. `parse` returns the typed tree ParticleSystemAsset →
  ParticleType → affectors / spawners / initializers with the executable's
  class, property and enum names (28 classes, every name reproduces its
  hash), constructor defaults, parsed gradients and flag names; unknown
  records are preserved; `build` writes the bytes back. Both byte orders.
  Also reads the untyped record layout of the Part 1 PC / X360 build, which
  the old reader could not parse (260 files). All 746 `.particle` files of
  seven extracts parse to the last byte with no unknown class or property
  and rebuild byte-exact. `kapow_props.namedict()` resolves `life`, `numX`,
  `numY`, `damp`, `open`.
  - `watchmen particlemeta EXTRACT_OUT OUT_DIR [TEXTURES_DIR]`
    (`wlib/particle_meta.py`): every `.particle` under
    `EXTRACT_OUT/extracted` (or of any folder, or one file) as
    `OUT_DIR/<asset path>.particle.json` — byte for byte the file `extract`
    writes beside the asset — plus `OUT_DIR/index.json`
    (`watchmen-particle-meta/1`): per file size, byte order, record layout,
    `emit_duration_s`, `loop`, object and class counts, the byte-exact
    rebuild check and one row per particle type (name, texture, model,
    render style, blend mode, alignment and simulation mode by their item
    names, `max_particles`, life, size, the spawn window, the classes of its
    three module lists, the `uv_grid` of a UVArray module); a `textures`
    table that looks each texture string up by its asset path, in any case,
    in `EXTRACT_OUT/textures` (or `TEXTURES_DIR`) and lists the folder and
    its images and the files that use it; the same for `model` strings under
    `extracted/`; totals. The values are those of `particle_asset.values`;
    the command adds none of its own. A file that is not a complete tree is
    still written (the generic walk with a `warn`), listed under `errors`,
    and the command exits with status 1. Nothing in the extract is changed.
    On the Part 2 PC extract: 89 files, 208 types, 1,464 objects, 56
    textures named, all 56 found, no model named; the 89 JSON files equal
    the ones written from `particle_asset.to_json` directly.
- **Navigation data** (`wlib/nav_data.py`, `docs/NAV_DATA.md`): the Kynapse
  path data (`.hpd`, written by `extract` to `files/` all along) and world
  definition (`.aipathdata`) are decoded completely — every shipped file is
  consumed to the last byte (11 `.hpd`, 17 definitions) — and exported per
  level as `<Level>.nav.json` (`watchmen-nav/1`: graph vertices and edges
  with length and path-object link, AI-mesh floors with walls, links, inner
  walls and one-way zones, path objects, the definition tree and a summary
  with `generated`, the one generation stamp all cells of a file carry)
  and `<Level>.nav.glb` (mesh as triangles, graph as lines). The JSON is in
  engine space; the GLB is in the frame of the model exports (true-handed
  by default, where its x is the file's own x; engine space with `--frame
  mirrored`), so it overlays them and a level assembled from the level
  export. `extract` writes
  them to `nav/` (`--no-nav`); `watchmen navmeta FILE_OR_DIR OUT_DIR` does
  the same for an extract output, a game data folder or one file. The data
  lies about 1 m above the walking surface (median 1.025 m above character
  placements); `nav_data.locate` tests a point against the mesh with an
  altitude window. Three fields are named from the Kynapse code: a path
  object's `flags_decoded` (created at run time, per-entity pass bits,
  starts passable); a mesh link's `gate` (`dir_x`, `min_dot`, `dir_z`: a
  trace crosses only when its direction has more than `min_dot` along the
  gate direction) with `crossable`, and `summary.mesh.mesh_links_never_crossable`
  (51 of the 593 mesh links of PC Part 2); and `config_runtime_overrides`,
  the four values of the definition the engine writes over per agent from
  `AIBrainNode` properties.
- **`watchmen grademeta`**: each grade node carries `_iplayerctrl` (whose
  camera it grades: 0 / 1 = that playable character, 2 = both;
  `FXGfxEffectCtrl.initialize_external` 0x73ccb6) and `m_tinitialgfxnode`,
  as stored.

- **`.sequence`: loop mode, entity-path depth and target kind.**
  `<name>.sequence.json` gains `loop_mode` / `loop_mode_name` (loop, oneshot,
  oneshot_reverse, loop_reverse, pingpong; the header word 1.3.0 called
  `flags`), and per object `hosts_up` (how many fragment hosts above the
  playing node's own host the id path starts; the old key `flag` stays) and
  `target_kind` (`texture_sheet` with `texture` and `sheet_index`, `asset`,
  `entity_path`, `self`, `name`). `decode_sequence.play_position(seq, t)`
  gives the play position for the five modes.
- **Particle emission surfaces of models.** The third list of a model node is
  a `MeshParticleData` mesh a `SurfaceSpawner` emits from. Its triangles are
  named `normal`, `area_weight`, `material_id` (the 1.3.0 keys `vec`,
  `value`, `id` stay beside them), and each surface has `weight_sum` and
  `weight_is_area`. The surfaces of mesh nodes are read too: 29 surfaces in
  19 of the 738 staged PC Part 2 models, where the reader that skipped mesh
  nodes saw one; the weight is the triangle's area in m² on 27 of them.
  `<name>.model.json` lists them as `particle_surfaces` on those models.
  `watchmen_extract.model_surfaces()`; `skeleton_records.parse_node_tail(...,
  meshes=True)` (the default result of `parse_node_tail`, and with it the
  skeleton JSON volumes, is unchanged). A surface whose weights are all
  exactly 1.0 carries `weight_is_unit` (2 Part 2 and 17 Part 1 surfaces).
- **Model parts in `<model>.model.json`.** `parts`: every node of the model
  with its parent, stored position and rotation, `moved`, `pivotbook_index`
  (the part's index into the model's pivot-book list, 0x53e987) and per
  submesh `shadow_id` / `in_shadow_hull` (the shadow-hull group id: submeshes
  of one part and LOD with the same id above 0 and the skip flag clear are
  merged into one stencil-shadow hull, builder 0x544ae4);
  `part_transforms_applied`. `parse_model_header` names the two fields
  beside the old keys `f1` and `u28`.
- **Texture header: animation block and cube face order.**
  `parse_texture_frames` reads the block that follows the frames of an
  animated texture (`anim_tail`: cycles of steps and items, an item = a
  frame range and a time range in ms; readers 0x53345a, 0x530639) and ends
  after it. `sheet.json` carries it as `animation`, with `frame_ms` where
  each frame is shown for a fixed time (four Part 2 textures and one Part 1
  texture, 65 ms a frame), and `cubeFaceOrder` on a cube map (file face k =
  D3D face k, 0x454384; 110 and 200 cube maps).
  `watchmen_extract.TEXTURE_SLOT_LABELS` / `TEXTURE_LAYER_SLOTS` hold the
  slot and engine-layer tables.
- **Standalone header files.** `watchmen_extract.standalone_preamble()`
  returns the 8 bytes in front of a standalone `_h_z` file's zlib stream
  (version signature, second word, byte order, build);
  `STANDALONE_SIGNATURES` has the six values measured on the 36 such files
  of the six sets.
- **More sheet values in a GLB material** (`extras.watchmen.sheet_values`):
  `blendType`, `srcBlend`, `dstBlend`, `blendOp`, `writeDepthBuffer`,
  `normalMapPower`, `enableNormalMapping`, `fresnelPower`, `maxReflection`,
  and the sheet's layer `overrides`. `grademeta`: `platform_adjustment`
  gains `option_default` (0.5, the value the four options start at,
  0x82be66) and `default_offsets` per platform.
- **Block trailing blob**: `watchmen_extract.parse_block_trailer` (two stream
  set tables; empty in every shipped block except Part 1's
  `Prison.block_h_z`, which has four manual sets, see "Fixed"). **Asset types `font` and
  `terrainColoringAsset`** are named; no record of the nine staged blocks has
  an unnamed type any more. (`terrainColoringAsset` has records in Part 1
  data — five files; none is in the staged blocks.)
  **`.naz` entries carry the engine's index key** (`NazEntry.key`,
  `naz_key()`), and an entry stored with a compression method is reported:
  the engine reads archive entries as stored.
- `sheet.json`: `textureHasAlpha`. `watchmen_extract.texture_alpha_flag`,
  `materials.texture_has_alpha`, `materials.alpha(..., pixel_alpha=)`,
  `rig_glb.material_alpha(..., legacy=)`. `sheet_blend()` also describes a
  Standard or FallOff sheet whose opacity is below 0.99 and says why a sheet
  blends (`cause`); one shipped Part 2 sheet is of that kind
  (`Sewer_Dirt_02`, standard blend), and its output is unchanged.
- Animation table: `pairs[].timeline.anchor_frame`;
  `face.classes.*.hit_pose_then` and `idle_cycle.entry`;
  `face.drivers.CHARACTER_MODE.rule` (when the mode is COMBAT);
  `face.conventions.evaluation` / `hit_hold`; `face_rule.clip_mix()` (a
  two-slot face state's `clip_mix` is an object: rule, the slot shown,
  weights, evidence), `face_rule.idle_entry()`, `idle_plan(..., entry=)`.
- `gendata respell [PKL] [-o OUT.pkl]`: the registered spellings applied to
  a property dictionary, without any game file.

- **Parts 1 and 2 on all platforms: stated gaps.** Where the toolkit cannot decode something
  it says so in the output as well as in the log:
  - `asset.extras.watchmen.not_decoded` in a character GLB that lacks
    something the game data holds: `vertex_attributes` (`missing`, `pieces`,
    `pieces_without`, `reason`), `ragdoll` (`reason`), `pieces` (model,
    submesh, vertices, stride, index bytes, byte order, reason). Absent when
    nothing is missing, which is every PC Part 2 character.
  - `sheet.json` key `decodeWarnings`: every layer or face a console
    texture carve could not place (0 on the four console sets).
  - Fragment JSON keys `instances_source` (`"exact"`, or `"sweep"` when the
    property stream does not parse to its end) and `unknown_keys` (only when
    a key is in no table): 0 sweeps and 0 unknown keys in the six sets.
  - `.model.json` of a scan-decoded model: `mesh_source: "descriptor scan"`,
    `header_decoded`, and in the reduced form (a header of neither known
    layout) `lod_count: null` and a `not_decoded` list. No model of the six
    sets is scan-decoded or reduced: the stand-alone Part 1 header and
    the console streams are read (the two items on them below).
  - `audio/sound_info.json`: `not_decoded` (names of sound headers no reader
    took) and per record `duration_source` (`header` / `frame_count` /
    `none`); `sound_meta.json`: a `wave_durations` block (`codecs`,
    `sources`, `without_duration`, `reparsed_fragments`) on console tables.
  - Level JSON `nav_note`.
- **Parts 1 and 2 on all platforms: new output and API.**
  - `audio/sound_info.json` on console extracts, with the PC keys plus
    `duration_source`, `xma_frames` or `mp3_frames`, `mp3_frame_samples`,
    `bytes_per_second`. PC records are unchanged.
  - `<model>.model.json` for console and Part 1 models. Where the header
    reads it is the full sidecar (every model of the six sets, in either
    header layout); a header of neither layout gets the LOD distances and
    the property bag, with a `not_decoded` list.
  - Level JSON: `stable_uid` on graph nodes (`<node id>@<instance id>`),
    `stable_id` on fragments, `stable_ids` by instance index. The instance
    id is the first 8 hex digits of the SHA-1 of the host chain, so it does
    not depend on the load order: PC and PS3 Part 2 match on every node
    that exists on both, where 0 to 21 % of the `uid` values matched. A
    toolkit naming rule, not an engine value. `uid` is unchanged.
  - Seven Part 1 fragment keys are named and typed
    (`kapow_fragment.PART1_KEYS`): `_idebugrunthroughmode`, `_tdebugtmp01`,
    `_nsteplengthinmeters`, `_ntimeprstepinsec`, `_tuseteleport`
    (WaypointController), `_nobstructionfactor` (SoundEnvironment),
    `_tstartenabled` (visionblocker). No unknown key remains in the 758
    Part 1 fragments on any platform (95 properties before). All seven
    spellings and types are entries of the Part 1 `database.bin`. A name
    with an exact hash but no such source would be listed in the fragment
    JSON under `inferred_names` (name, key, count,
    `confidence: "inferred"`, the caption) with an `inferred_names_note`
    (`kapow_fragment.PART1_INFERRED`, `inferred_names()`); that table is
    empty, so no fragment JSON carries the list.
  - `watchmen_extract.header_order` (the one byte-order test for a header
    read outside its block), `mp3_frame_stats`, `block_stream_sets`,
    `stream_file_lookup`, `model_property_bag`, `model_meta_scanned`,
    `model_meta_reduced`, `OutputNames`, `extract_block(..., stream_files=)`,
    `Toc.stream_file` / `stream_note`, `bounds_floats` on a parsed stream
    set, `parse_texture_frames(hdr, order)` with a `size` per descriptor,
    `PC_CUBE_LEVEL_MAJOR`.
  - `kapow_props.read_records`, `find_objects`, `record_value`,
    `untyped_types`, `type_hash`, `pivot_book`; `kapow_fragment.sections`,
    `unknown_keys`, `notes` (`parse()` also returns `order`, `schema_lead`
    and `at`); `char_lib.header_order`, `model_order`, `dropped_pieces`;
    `ragdoll_rig.byte_order`, `explain`; `characters_export.bind_mismatches`,
    `not_decoded_extras`, `anim_meta_failures`; `anim_meta.BUILD_FAILED_KEY`;
    `nav_data.loose_source_files`, `stage_loose_source`;
    `level_meta.instance_chain`, `instance_stable_id`;
    `skeleton_records.scan_note`; `jiggle_d6.cache_file`,
    `CACHE_KEY_VERSION`.

- **The raw-only formats are decoded.** `extract`
  now writes JSON for `.font`, `.scene` and `.terraincoloringasset`, decodes
  the whole `.terrain` (header and stream) and the last bytes of
  `.detailmesh`. Measured on the six sets (PC, Xbox 360, PS3; both parts):
  18 fonts, 6 scenes, 24 terrains, 15 colouring maps and 30 detail meshes,
  no byte left over.
  - `.font` (`font_asset.py`, format `kapow-font/1`): descriptor, glyph
    table, atlas as `<name>.font.png`. All 18 rebuild byte for byte; the
    atlas is the same image on the three platforms. The format holds no
    kerning data.
  - `.scene`: a Fragment; `<name>.scene.json` with a `scene` section (the
    level list with its load-block settings). `levelmeta` keeps reading the
    binary file.
  - `.terrain` (`terrain_asset.py`, format `kapow-terrain/2`): sectors,
    cells, buffers, per-layer draw ranges, grass / detail maps, decal
    rectangles. Writes `<name>.terrain.height.png` (16-bit),
    `.layers.png` and, with `--glb`, `<name>.terrain.glb` (the surface, one
    node per texture layer, no textures; in the frame `--frame` selects,
    with the `coordinate_frame` marker). The file stores no height map; the
    PNG is built from the vertices, in engine axes. `tail_bytes` is 0
    (1.3.0: 74 to 95 % of each file). The keys `version` and `header` are
    replaced by `quad_size`, `sector_quads`, `sectors_x`, `sectors_z`
    ("version" was the quad size); `texture_layers`, `grass` and
    `detailmeshes` keep their values. The console vertex layout (36 bytes
    against 48) is matched against the PC values, not read from console
    code.
  - `.terraincoloringasset` (Part 1): header JSON and the map as PNG. PS3
    equals PC pixel for pixel; Xbox 360 (4-bit DXT3A) is within 16. The one
    1×1 Xbox 360 map reads 204 against 255: where its texel sits in the
    block is not established, the JSON marks it `unverified` and the log
    has a `note:`.
  - `.detailmesh`: the 25 bytes after the bag (24 in the standalone Part 1,
    which has no flag byte) are the mesh flag and two buffer descriptors,
    written as `mesh`; `trailing_bytes` is 0; `stream` gives the layout of
    the stream. `blocks` is unchanged.
  - Fields whose meaning is not read from code are listed in each JSON
    under `inferred` or `not_established`.
  - PC Part 2 output: the 3 `.terrain.json` and 5 `.detailmesh.json` change
    as above; 3 `.font.json` + `.font.png`, 1 `.scene.json`, 3 + 3 terrain
    PNGs and 3 terrain GLBs are new. Old and new code give the same JSON
    for all 906 fragments and all 289 `.sequence` / `.pb` / `.particle` /
    `.grass` files.
- **The model header of the stand-alone Part 1 (PC, Xbox Live) is read.** It is the Part 2 layout with one flag byte
  fewer per submesh record and untyped property records (Xbox 360 Part 1
  reader `0x828bccc0` against `0x542541`; the submesh version term is 10
  against 11). `parse_model_header` reads both layouts and reports which
  (`"layout"`), taken from the header, not from a path: 1,090 of 1,090
  headers of each set. Result: the full `.model.json` (with
  `header_layout: "part1"`; equal to the PS3 Part 1 one on 1,090 of 1,090
  on Xbox 360 and on 1,082 on PC, the 8 others differing in
  particle-surface weights; `lod_count` is a number again, where the
  reduced sidecar listed five distance slots under `lods` and gave no
  count), 80 of 80 ragdoll rigs on both sets (0 before; Xbox 360 equal to
  PS3 Part 1 on 80, PC on 43, the other 37 differing by one bit of one
  stored float), and on PC header-driven meshes: LOD 0 only, 1,085 model
  GLBs (181 before), NORMAL / TANGENT / COLOR_0 on 292 of 292
  character-model pieces. Against the scan decode, 789 of 1,085 PC Part 1
  OBJ are the same mesh, 206 lose the lower LODs the scan had stacked, and
  90 differ where the scan had missed or added triangles. On PC Part 1, 45
  static props get a different node table (36 raised in the name scan
  before); no character model is among them. Not opened: the Part 1
  readers of the node and of the model root; their equality with Part 2
  rests on the data and on the unchanged version terms.
- **Console models are decoded from their header.** The console stream has the PC structure with the console vertex
  strides, a 48-byte cluster record and 0x50-byte list items; with these
  every console model with a stream is located exactly (735 per Part 2 set,
  1,085 per Part 1 set). Against the PC copy, vertex for vertex: same
  triangles, UVs, joints and weights; normal and tangent frame within
  0.002. Console positions are coarser in the files than on PC (steps of
  up to 0.5 m on the Part 2 sky domes, 1.0 m in Part 1). Result: OBJ with
  LOD 0 only and the header's materials, a GLB for every model (735 per
  Part 2 console set, 120 before), NORMAL / TANGENT / COLOR_0 on console
  GLBs, both `Palm_Banana` models complete. This changes the model files
  of all four console sets, PS3 included (per Part 2 console set 197 OBJ
  and 81 MTL of 735; per Part 1 console set 321 and 151 of 1,085; every
  `.model.json` loses `mesh_source` and `header_decoded`). Vertex colour is
  stored A,R,G,B on Xbox 360 and R,G,B,A on PS3 and a model does not name
  its console: the order is inferred from the alpha of buffers without
  `hasAlpha` (equal to PC on all 13,378 buffers decoded so); where that
  does not decide, the colour is not written and the sidecar says
  `not_decoded: ["COLOR_0"]`, with a `note:` line (13 / 13 / 22 / 23
  models on Xbox 360 Part 2 / PS3 Part 2 / Xbox 360 Part 1 / PS3 Part 1;
  the two Rorschach bodies are among them, so 4 character-model pieces per
  console set stay without attributes). Inferred and not compared: the
  joint offsets of the skinned shadow hull. `WATCHMEN_CONSOLE_MODELS=scan`
  restores the scan decode.
- **Nothing that is not decoded stays silent.**
  - `extract` counts every asset it writes JSON for, per kind, and ends
    with two lines: `misc JSON   : .font 3, .fragment 906, …` and
    `not decoded completely: none` (or `.font 1 of 3, …`). An asset that
    is not decoded completely has a `WARNING:` line naming it and a marker
    in its JSON (`not_decoded`, `leftover_bytes`, `tail_bytes`,
    `trailing_bytes`, `parse_error`, `unknown_keys`, `warn`, the same in
    its `stream` section, `atlas_not_written`, `outputs_not_written`,
    `glb_not_written`); `kapow_json.undecoded(doc)` reads them. An asset
    of a kind no step decodes is counted in a `WARNING: raw only …` line
    (none in the six sets).
  - With `--glb` the summary has `model GLBs  : N`. A decoded model that
    gets no GLB has `"glb": {"written": false, "reason": …}` in its
    `.model.json`, and the summary has one `note: no GLB for N model(s):
    <reason>: <names>` line per reason. A scan decode that found fewer
    submeshes than the header lists, or could not pair its materials, has
    `"submeshes"` under `not_decoded` with the two counts, and a
    `WARNING:` line. A `.model.json` with a GLB has no `glb` key, so PC
    Part 2 sidecars are unchanged.
  - `decode_model(..., status=)` and `watchmen_extract.MODEL_STATUS` give
    the caller the same facts.
  - The blocks of an archive are taken in case-insensitive order of their
    paths. A name stored under two letter-case spellings is written under
    the spelling of the first block in that order, which is the same on
    the three platforms for all such names: 30 / 29 / 29 (PC / Xbox 360 /
    PS3 Part 2) and 187 (Part 1, each platform), as the extract logs count
    them with `--names stored` (the default naming: 23 on each Part 2 set);
    the order equals the old one on the six sets, so no path changes.
    Three Part 2 textures are stored under one spelling per archive that
    differs between the platforms (`Fire_01.BMP` on PC and PS3 against
    `Fire_01.bmp` on Xbox 360, `WallCables_03.bmp` on PC against
    `wallcables_03.bmp` on both consoles, `garbagepile_01.bmp` against
    `GarbagePile_01.bmp` on PS3; the source path inside the texture header
    differs the same way). They are written under one spelling, see "Asset
    paths have one spelling" under "Behaviour changes"; `--names stored`
    writes them as stored.
  - The `not_decoded.vertex_attributes` marker of a character GLB gives the
    reason its log line gives (the header does not locate the vertex buffer,
    or a console piece whose colour byte order is not known:
    `characters_export.VERTEX_ATTRS_REASON`); a text naming "PC Part 2 mesh
    buffers only" is not true of a toolkit that decodes the console and
    Part 1 headers. No character GLB of the six-set export carries the
    marker.
- **The script name database and the builtin script module.**
  - `wlib/script_database.py` (`watchmen scriptdb DATABASE.bin [OUT.json]
    [--find KEY ...]`): reader for the script name database `database.bin`
    (layout from the loader 0x47c5f5; ids are the name hash of the text
    before `:`). Part 2 holds 3,693 properties and 1,672 messages, Part 1
    3,410 and 1,551 (PC file; PS3 has 1,552 messages); every file parses to its last byte. `--find` takes a
    hash (`0x40cb4063`, `key_40cb4063`) or a name; eight bare hex digits
    are read as a hash first and hashed as a name when no entry has that
    id. See `docs/SCRIPT_DATABASE.md`.
  - `wlib/builtins.json` and `wlib/script_builtins.py`: the builtin script
    module as registered at 0x47ff8c. 123 functions and 19 properties with
    signature, type codes, slot layout, handler address (PC and PS3; Xbox
    360 where known), stub mark and one line of semantics, plus the
    `LANGUAGE` and `PLATFORM` values. 20 registrations share the empty
    body 0x48d55e and three the "return 0" body 0x4fa89c. See
    `docs/BUILTINS.md`.
- **Level JSON: where the terrain is placed.** `files.terrain` lists every
  node that names a `.terrain`: the asset, the GLB the extractor writes
  for it, the node's `local` transform as stored, `world` (composed with
  its parents), `gltf` in the frame of the level file (`--frame`), the
  node's quad and sector numbers, and `scale: null` (the node has no scale
  property). `files.terrain_rule` states the rule; `files.loose` is
  unchanged and the terrain GLB is unchanged. The placement is the
  composed transform, not `localPos`: Bordello's TerrainNode has
  `localPos` (0, −24, 76) under a fragment host at (0, 24, −76), so it is
  at the origin like the other two Part 2 terrains — the three GLBs were
  in the right place already. Measured: all 24 TerrainNodes of Parts 1 and 2
  on all platforms compose to the world origin, unrotated; on Bordello 61
  of 129 placed models above the terrain rest within 0.5 m of its surface
  with the GLB at the origin and none with either offset.
- **Detail mesh JSON says what is not read.** `.detailmesh.json` carries
  `not_established` (empty: the three lists of the stream, the index
  buffer's primitive type and the buffer flags are read from code,
  0x5369e7, 0x429f21, 0x454159) and `inferred` like the terrain and font
  JSON. The vertex
  stride is derived from the stream size, and the JSON now says so:
  `stream.vertex_stride_source`, `stream.format_stride` (the PC stride
  table's value for the format id) and `stream.stride_matches_format`; a
  `WARNING:` line when the two differ (no file of the six sets). `inferred`
  says which stride tables were read: the PC one and the Xbox 360 one
  (0x8308b6e0, 60 for format 7 as well); the PS3 table was not read. All
  30 detail meshes of the six sets tile with 60 bytes.

- **Combat metadata: more rules, the partner AI, the Underboss, the
  achievements.** `combat.rules` gains `bull_rush` (start, contact value,
  secondary victims, the blocked rush), `partner_ai` (the AI hero: evaluate
  order, the two run-time overrides, reaction multipliers, special-move
  ranges, follow numbers, two defects of the shipped code),
  `special_handling.BULL_MOVE`, `attack_id`, `sweep.check_point` and
  `sweep.direction`, `attack_permission.faction_filter`,
  `damage.override` with `damage.override_events` (the `IMPACT_EFFECTS`
  events that deal damage themselves: 27 on Part 2, 5 on Part 1),
  `pair_damage.ELECTRIFY_ARMOR_range_m` (10.0, a code constant) and, when the
  data has an `UnderbossDef` (Part 1), `underboss` with the definition's
  phases (shipped: 1.0 → 0.8 → 0.7 → 0.5 → 0.375 → 0.25 → 0.125 → 0, maximum
  health 1000) and `attack.target_recheck_is` (the 6.0 s target re-check is a
  registered default, like the hit / block counts and the shockwave numbers). `combat.achievements`: names from the executable's
  `ACHIEVEMENTS` family, the conditions, the thresholds of the set's
  controller (Part 1: 4800 s, 20 kills in 101 s, 25, 100, 200, 250) and the
  two counter defects. `combat.ai_defs`: 24 more numbers on a `PartnerDef`,
  `visual_range` and `allowed_speed_change_per_s` on every definition, and
  `weight` on each crowd-control combo. `combat.enums`: six partner-AI
  families. States with special handling BULL_MOVE carry
  `combat.special_handling_rule` (125 on Part 2, 93 on Part 1). All read from
  code unless the block says otherwise; nothing of it was checked in the
  running game. The object push `FeedBack` 0x681e7b never runs (its only
  caller, the command `CollisionResponse`, has no sender). An AI-driven
  partner hero has no `PlayerCtrl` (`IsAIPartner` 0x678254), so the wall stop
  is player-only. `Perception.m_forceperceptedcharacter` is written by
  `Enemy.StateActive` (0x725078). `CharacterSpecialDef.m_nelectrifyrange` has
  one reader (0x6a71b6) whose result is unused. `docs/COMBAT_META.md`.
- **Effects and camera metadata: the gameplay cameras and what was still
  open.** `fx.camera.gameplay`: the combat, exploration and player-vs-player
  camera updates as constants and formulas (read from code, not checked in
  the game), with the reference functions `fx_meta.power_smooth`,
  `symmetric_halfbell`, `pvp_camera` and `exploration_camera`.
  `fx.event_effects` (effect ids the event cases 29, 30, 31, 60, 69 fire;
  in case 60 id 12 is fired and id 13 started),
  `fx.rumble.senders`, `fx.camera.cut_placement.hard_cut_push_in` and
  `return_in_vector`, `fx.camera.rig.*.property_use`, `use` on the camera
  states a button or the stick selects, `fx.fake_twilight_lady_weapon`; an
  `impact_effects` entry with `truth1` gains `deals_damage` and
  `override_damage` (`truth1` / `value` stay). The transition clock, the
  shake formula, the validity sweep and the return direction are stated as
  read; four items leave `fx.not_established`. `docs/FX_META.md` gains
  "Gameplay cameras" and "Lens flare".
- **Level JSON: `cameras.pvp_focus`, `auto_sequences`, `scene_ctrl`.** The
  `PlayerVsPlayerFocusPoint` node the PvP camera is aimed by (Bordello and
  PlayerVsPlayer on Part 2), the `PropertySequenceNode`s that start by
  themselves (291 instances in the six Part 2 PC levels, 615 in the seven of
  Part 1 PC), and the hero models the level's `LevelSceneCtrl` names
  (`override_models`: `nto`, `nto_flashing`, `rsh`, `rsh_rage`, `nto_head`).
  Run on the 13 PC levels: nothing else in the files changes.
- **`engine_enums.json`**: the families `ACHIEVEMENTS`,
  `PLAYABLE_CHARACTERS`, `GAME_MODES` and `AIAGENTFACTION`;
  `event_semantics` gains `heading_offset_rad` on events 41, 49, 54, 55, and
  the `effect` text of 38, 54, 55, 66, 67, 68, 71, 81 and 86 says more.
- **`wlib/property_store_flags.json`**: the registered properties the
  engine's writer never stores (61) and the deprecated aliases it reads but
  never writes (56); `docs/FRAGMENT_FORMAT.md`.
- **`tools/blender_import_level.py`**: a `<Level>.level.json` in Blender,
  each model GLB imported once and every placement a collection instance at
  its `gltf` transform, with the terrain, the sky, the navigation mesh and
  the placed characters in their idle pose, sorted into collections. Where
  the game chooses a character's variant at run time, the candidates are
  handed out in turn, and members that share a GLB are shown as its outfits
  (the 168 Heavies of NightClub wear its 18 outfits). Identical embedded
  images are merged while the library is built, a level that is already in
  the file is refused, and every GLB is checked before anything is created
  (Bordello: 3,070 instances from 264 library collections in 66 s, a 312 MB
  file, 2.6 GB of memory at the peak, Blender 3.6.0). A record with
  `host_offset_copy` goes into `<Level>` > `Host-offset copies`, a
  collection that is switched off, with `watchmen_host_offset_copy` and
  `watchmen_host_offset_twin` on the instance: whether the game draws
  these nodes is not established. Blender 5.2.2 on Windows, background mode
  (measured): PC Part 2 Bordello imports as 3,070 instances from 264 GLBs in
  40 s into a 260 MB file, NightClub as 3,811 instances from 277 GLBs in 42
  s into a 257 MB file, both without an error; every prop instance sits
  within 0.02 mm of the `gltf` placement of its level record.
  `docs/LEVEL_META.md`, "A level in Blender".
- **`tools/blender_attach_extras.py`**: Blender's glTF importer (checked:
  5.2.2) does not import `animations[i].extras`, so the actions arrive
  without the clip metadata; the script reads the GLB's JSON chunk and sets
  `action["watchmen"]` (`null` values dropped). README, "Coordinate frame".
- **`anim_meta.json` / `watchmen characters`**: the contact check knows the
  Part 1 `EN3` clips (8 pairs per Part 1 set gain `placement.check.contact`:
  237 of 237), every bind is built before the table so that a first run
  checks the Twilight Lady pairs too, and `characters` says how many placed
  pairs have no check.

### Fixed

- A `sheet.json` that cannot be written, or whose decode notes or stored
  name cannot be added, gives a `WARNING: texture <name>: …` line; 1.3.0
  dropped the error silently and the texture's materials fell back to the
  rules for a texture without a sheet.
- `face_rule.sheet_records` reads the version-1 sheet descriptions
  (`1,slot,pivot,<path>,<id>,`) through `characters_export.sheet_records`,
  the one parser (it read them as version 2). `face_rule.sheet_overrides`
  and `characters_export._texture_sheets` find a texture header whose stored
  path differs in letter case from the extracted file, as the engine does;
  on a case-sensitive file system they missed it. On Windows nothing
  changes; whether a shipped record depends on it on a case-sensitive file
  system is not established here.
- `bake_v4.bake(track_names="prefix")`: a root bone takes the track the
  lookup found; a root whose track differs by a `BipNN ` prefix was decoded
  and then placed at its rest pose. No shipped root is named that way
  (measured on PC Part 2 and 1, Xbox 360 Part 2, PS3 Part 1: no root
  matches a track by prefix only), so no output changes.
- An archive entry named like a Windows device (`CON`, `NUL.txt`, `LPT1`)
  is written with a leading `_` on every platform; none is in the shipped
  archives.
- `watchmenlib.bind_from_skeleton_header` removes its temporary header file
  and writes `bind_file.npz` in the current directory by default (was
  `/tmp/bind_file.npz`); `rig_glb.decode_skin` reads the weights as
  little-endian half floats on any host.
- `tools/blender_import_level.py` and `docs/LEVEL_META.md` named an option
  `--names export` that does not exist: the level file must use the naming
  of its export, which `levelmeta` follows by default.
- Xbox 360 addresses of the subtitle key code in the text evidence:
  0x82949958 (Part 1) and 0x8298e130 (Part 2); Xbox 360 addresses are
  0x82000000 + file offset.
- `anim_meta.CONVENTIONS` states the unit of criteria bounds
  (`criteria_units`): radians for the angle values, degrees for
  CHARACTER_PELVIS_ROTATION.

- **Files are closed where they are read or written.** Every `open()` of the
  toolkit is the subject of a `with` (50 were not: model, stream, clip,
  pivot-book and table reads as `open(p, "rb").read()`, the character GLB
  written as `open(tmp, "wb").write(...)` before it is renamed, two texture
  probes that could leave a PNG open). Nothing else changes: measured on the
  six-set export, PC Part 2, the first 3,628 files of an `extract` and the
  character GLBs of `Gimp` are byte-identical apart from the jiggle channels
  named above, and the `characters` step that printed 96 `ResourceWarning`
  lines under `python -X dev` prints none. The suite passes with
  `-X dev -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`.
- **Console vertex colours are decoded on every model.** The colour byte order is the console's (Xbox 360 `D3DCOLOR` = A,R,G,B, declaration `0x82236078`; PS3 four unsigned bytes = R,G,B,A, format table `0x01821f48`) and a Part 2 model does not name its console, so the console now comes from the source: the block path in the archive (`derived_x360/`, `derived_ps3/`) or the source directory in `extract`, `<EXTRACT_OUT>/files/derived_…` (else inferred from the tree) in `characters`, `WATCHMEN_CONSOLE=x360|ps3` by hand; then the alpha rule as before, then "a big-endian Part 1 layout header is Xbox 360". The 13 / 13 / 22 / 23 models that had `not_decoded: ["COLOR_0"]` (Xbox 360 Part 2 / PS3 Part 2 / Xbox 360 Part 1 / PS3 Part 1) decode with every colour equal to the PC copy (198 render buffers, 59,858 vertices, largest difference 0) and keep PC's `hasAlpha` flags, so the two Docks water surfaces get their vertex-alpha BLEND material; the four Rorschach pieces per console set get NORMAL / TANGENT / COLOR_0. A console piece whose colour stays unknown (no console named, data undecided) now keeps NORMAL / TANGENT in a character GLB and is listed under the new `not_decoded.vertex_colour` (`VERTEX_COLOUR_REASON`); `not_decoded.vertex_attributes` no longer names that case. New: `CONSOLE_COLOR_ORDERS`, `console_platform_of`, `set_console_platform`, `console_platform`, `detect_console_platform`, `console_platform_for`; `console_color_order` / `console_color_undecoded` take `platform` and `layout`, `variant_glb.buffer_vertex_attrs` takes `platform` and returns `color_not_decoded`. On the six-set export no `.model.json` of the four console sets (738 per Part 2 set, 1,088 per Part 1 set) has `not_decoded: ["COLOR_0"]`. Tests: `test_p5_console_colour` (15).
- **Pair placement of a master that starts turned: the offset turned the
  wrong way.** `anim_meta.placement` turns the `interact` offset by the
  master's `yaw_start_deg` when that is not 0. It did so in the right-handed
  sense, but the yaw numbers are the engine's heading angle, the opposite
  sense (see the frame item above). The offset is now turned as the engine
  turns a vector and as the GLB's `GamePivot` → `interact` hierarchy shows
  it: on 32 turned solo clips of Rorschach, NiteOwl and the Heavy the result
  equals `GamePivot(0) · interact(0)` of the GLB to 0.1 mm, where the old
  sense was off by up to 1.66 m. No output changes: `yaw_start_deg` is 0 on
  the master of every shipped pair, so the branch never ran on the game's
  data. Not established: that a master's node carries the clip's yaw at
  t = 0 at all (the engine reads the live node).
  *1.3.0 output:* identical on the shipped data.

- **Fragment JSON keeps every `created` entry.** Found by the full extract of
  the Part 2 PC archive, before release. Reading the file header exactly
  (see "Fragment JSON has a header") starts the stream at its first byte. A
  fragment whose type records all carry a bare native name (`Model`,
  `SubPivot`, `FragmentNode`: models, props, `AllPlayerTypes`) opens with
  them, and that whole run was taken as schema only: `nodes_full` lost the
  `{"created": true, "props": []}` entry of each, 1,492 entries in 266 of
  the 906 Part 2 PC fragment JSONs. They are back
  (`kapow_fragment.parse`: the leading records go to the schema alone only
  when a `Class(Native)` record follows in the head, as for a `.scene`).
  `instances`, the property records and the node tree built from them were
  the same either way (checked on all 906 fragments), so no export changed:
  `anim_meta.json`, `sound_meta.json`, the effects table, the six level
  files, `text_meta.json` and the grade table are byte-identical with and
  without the fix.
- **`text/index.json` names a block the same way from an archive and from a
  `files` tree**: `derived_pc/…/x.block`. `watchmen text FILES_DIR` wrote it
  with the leading `/` of a loose entry name; it was the only difference
  between `text/` written by `extract` from the archive and by `text` from
  the extracted `files/`.
- **Twilight Lady lost her whip on a case-sensitive file system.**
  `Bs2CharVisual` names the model `/Art/Characters/twilightlady/models/TW_weapon.model`,
  the extract has `art/characters/...`; `characters` tested that path as
  written and, where the file system distinguishes case (Linux, macOS),
  wrote the GLB without the weapon. The model is now found by name when the
  path as written is not there, as the weapon collections already were
  (`characters_export._tw_weapon_spec`). Windows output is unchanged.
- **PC `ATI2` normal maps decoded with X and Y swapped** — see "Behaviour
  changes". Both the exact carve and the legacy carve are fixed
  (`watchmen_extract.ati2_xy`).
- **Character GLBs were flat-shaded** in glTF consumers, because they had no
  NORMAL. glTF-validator no longer reports
  `MESH_PRIMITIVE_GENERATED_TANGENT_SPACE` on them.
- **Wrong or missing textures** from the by-name lookup — see "Textures are
  resolved by the path the model stores": copies from another character's
  folder, Rorschach's untextured face and inkblots, and two same-named
  textures of one model sharing the first one's maps in the OBJ/MTL.
- **A stale `.fragment.json` is never preferred over the fragment.** The
  character export, the weapon table, the jiggle constants and `char` read
  the `.fragment.json` beside a fragment; one written by an older extractor
  has unnamed keys (and a desynchronised `EnemyDef` in
  `Dominatrices.fragment`). Every reader now parses the binary `.fragment`
  and falls back to the JSON only when the binary is missing.
- **ThugBig had no two-handed weapons.** The built-in table gave it one
  collection; its `CharacterDef` names `ThugsWeapons_2H` as well, so
  `KnotTop_Large.glb` gains five (hidden) weapon nodes. The collections are
  now read from the fragment; the table is the fallback.
- **`Dominatrix_3` is marked as what it is.** `Dominatrices.fragment` holds
  nine variants (1, 2, 4–10). `Dominatrix_3.glb` is a reconstruction the
  toolkit has written since at least 1.3.0 (Dominatrix_2 with Twilight Lady's hair,
  tinted, and the `Dominatrix1` body-skin sheet, after pre-release
  screenshots). The file now says so in
  `asset.extras.watchmen.reconstruction`; `WATCHMEN_NO_SYNTH=1` leaves it
  out.
- **The generic female heads get their eyelashes (restored content).** The
  `EyeBlow` submesh of `FemaleHead_White1`, `FemaleHead_White1_Gimp`,
  `Girl_Head_White` and `FimaleGimpMask` (72 vertices, 80 triangles: an
  upper and a lower strip per eye, both eyes on the same UVs) stores its
  UVs in a fully transparent corner of the 128-pixel `EyeBlow` texture, u
  0.0033 to 0.0620 and v 0.3914 to 0.4609 from the top, so the sheet's
  alpha test (`alphaThreshold` 95) discards every pixel and the game draws
  no lashes on these heads. The stored values are half floats and equal,
  value for value, in the PC, PS3 and Xbox 360 files (measured). Read as
  16-bit integers at five scales, with the bytes swapped or as single
  bytes, the same four bytes give a line or a scatter over the texture (at
  most 15 % of the strip area on painted texels), so this is the game's
  data and not a decoding fault; why the files hold it is not
  established. `TwilightLady_Head` has the same strips mapped onto a
  texture with the same painting: her lower strip has the same triangle
  list, her upper strip contains the 18 upper vertices. Against her UVs of
  the matched vertices each strip of the small layout is a uniform scale
  and a shift (least squares): upper `uv' = 11.7691 uv + (0.4736,
  −4.4107)`, rms 0.0016 (0.2 texel); lower `uv' = 11.5133 uv + (−0.0358,
  −4.5707)`, rms 0.0142 (1.8 texels). Written that way the strips cover
  95.6 % of the texels above the alpha threshold and 50 % of the strip
  area is on such texels (Twilight Lady's own strips on the same texture:
  88 % and 48 %); one scale and shift for the whole layout reaches at most
  55 % (an affine fit to her UVs), 21 % (box onto the painted box), 21 %
  (16 × 8). The restored UVs are written by default, under the switch of
  the reconstructed `Dominatrix_3`: in the head's OBJ and GLB, in
  `faces/<head>.glb`, and in the character GLBs that wear such a head. The
  files say so: `"reconstruction": {"eyelash_uvs": {...}}` in the head's
  `.model.json` and in `asset.extras.watchmen` of a face or character GLB,
  with the stored UV range and the two transforms. `WATCHMEN_NO_SYNTH=1`
  writes the stored UVs and no mark. Measured on the six-set export's
  files: the layout is on 4 of 740 models in each Part 2 set and on none of
  the 1,090 of a Part 1 set; per Part 2 set 12 files under `models/` (OBJ,
  GLB and `.model.json` of the four heads), `faces/FemaleHead_White1.glb`
  and `faces/FemaleHead_White1_Gimp.glb`, and the character GLBs
  `Dominatrix_1`, `_2`, `_3` and `_9` change; on PC Part 2, written with
  and without the switch, the 12 model files and those six GLBs differ in
  the 72 UVs and the mark and in nothing else. New:
  `watchmen_extract.LASH_RESTORE`, `lash_strips`, `lash_restored_uvs`,
  `lash_is_restored`, `lash_reconstruction_note`, `synth_enabled`;
  `decode_model_mesh` marks the submesh with `restored`. Tests:
  `test_s2_lash` (13).
- **The outfit order is the engine's.** Outfits are ordered by the nodes'
  `siblingOrder`, as the engine's child list is (0x48f556), not by position
  in the file; in the shipped fragments the two agree.
- **The last unnamed fragment key has its name.** `0x0991b0d4` was read as
  an integer `key_0991b0d4`; it is `CharacterGroup.m_ezonetrigger`, an entity
  reference (the combat zone). Read as an integer, the node id of the 22 set
  references was taken for an unknown key. All 906 Part 2 PC fragments now
  parse with no unknown key (and stay lossless); so do the 758 of Part 1
  with the seven keys named under "Added".
- **`characters` reuses an `anim_meta.json` it finds in the output folder
  only when the table carries the current `face_format`, `combat_format` and
  `fx_format`** (`characters_export.anim_meta_is_current`); 1.3.0 tested
  `format` alone.
- **Gimp and GimpGagBall use the body class `EnemyBig`**, not `Enemy01`, as
  one of the research reports said. No shipped table carried the wrong
  class: `sound_meta` and the face rule read the class from the fragments.
- **Directory listing order no longer decides anything.** A fragment's model
  reference is resolved by its path; the by-name model index
  (`characters_export`, `watchmenlib.ensure_binds`), the clip scans and the
  remaining "first file found" picks are sorted. On Part 2 PC only the
  texture lookup had names that collide in a way that changed output.
- **The `joint_space` sentence** in `anim_meta.json` (`skeletons.*`) and in
  the skin `extras` of every character GLB said that `GamePivot` and
  `interact` both carry absolute scene tracks. Only `GamePivot` does;
  `interact` is written relative to it like every other joint, as
  `docs/ANIMATION_META.md` already described. The text is corrected; no
  number changes. It is the one difference no switch removes, so no
  character GLB of this release is byte-identical to its 1.3.0 counterpart.
- **Nite Owl's face** held `NiteOwl_Biting` on every clip: the neutral-pose
  fallback took the alphabetically first pose.
- **Interpreter:** members already tested in one transition evaluation are
  not tried again (`_etestedstates`). A state group re-entered every frame —
  the face classes' "Active" group on every silent frame — no longer
  re-rolls its current state each frame.
- **The weapon that fires an extra effect on a hit is the TASER type**
  (effect id 1 `ELECTRIC_ARMOR_DISCHARGE`, then the STEEL slot), not SHARP:
  SHARP only selects the single `sharpweapon` slot. `sound_meta.json`
  `effects.damage_rule` said "sharp adds sharpweapon"; the sentence is
  corrected, no table changes.
- **`.particle` files of Part 1 PC and X360 were not parsed at all** (one
  block with no records and the rest of the file as trailing bytes, in all
  260), one Part 1 PS3 file ended with 4 unread bytes, and in every set five
  property hashes stayed hex keys and seven names were mis-cased (Part 2:
  1,776 and 971 records). See "Behaviour changes".
- **`.scene` files were refused** by the fragment reader; a level's
  references into singleton fragments and across fragment hosts were
  resolved by a nearest-instance rule that differs from the engine's in a
  few references per level (Bordello 7 of about 36,000, NightClub 10 of
  27,000, StreetsOfRiot 15 of 28,000). Inside the animation classes the two rules agree.
- **The language slots are known**, where the 1.3.0 README and
  `KAPOW_NAZ_FORMAT.md` said they were not established.
- **The `.hpd` navigation files are not outside the archive**, as the
  research report `wp4_ai.md` has it. They are plain NAZ entries and were
  always extracted to `files/`; only Part 1 on PC and Xbox Live ships them
  loose, beside the folder `extract` is given (it copies them now, see
  "Fixed").

- **Event table: ELECTRIFY_ARMOR (30) does not run the grenade's area
  query.** It charges the armour and pays `m_narmorcost`; the area damage is
  dealt by `ElectricArmor.AreaDamage` 0x72769f. Rows 29–31 of
  `event_semantics` state their damage.
- **Pair timeline: a partner holds its entry pose until its go-to flag is
  set.** The 1.3.0 text had it playing its GamePivot motion from there. That
  the master's node is its GamePivot frame is read from code, no longer
  assumed: while anchored, the partner is rigid in that frame and swings
  with a master that turns (`pairs[].timeline.anchor_frame`), and
  `anchor_drift_if_master_turns_m` is the engine's departure from the fixed
  marker; the shipped values are unchanged. For a master turned at t = 0 the
  partner clip is turned by 180° + that yaw in `partner_origin_shift_xz` and
  `check` (no shipped pair). `conventions.body_space` and `pair_space` say
  that a body turns with its GamePivot, and that only the horizontal part of
  the partner's first GamePivot key is subtracted.
- `docs/KAPOW_NAZ_FORMAT.md` printed the block header bytes at 328 as
  `0x593F430A`; the bytes are `0a 88 3f 59`. It also said stream blobs are
  read only when an asset is needed: a load block queues every stream and
  is not applied before all are delivered.

- **Parts 1 and 2 on all platforms, console characters: no ragdoll rig.** The rig reader was
  always run little-endian, so Xbox 360 and PS3 extracts got no helper nodes
  and no `<Variant>.ragdoll.json`. The byte order is now read from the model
  header: it opens with a length-prefixed class name that is a valid name in
  one order only (5,490 of 5,490 model headers of the six sets). Part 2 on
  Xbox 360 and PS3: 26 of 26 sidecars, byte-identical to the PC ones. PS3
  Part 1: 80 of 80 (17 bodies, 16 joints). The standalone Part 1 (PC, Xbox
  Live) has an older model header, which the item "The model header of the
  stand-alone Part 1 (PC, Xbox Live) is read" covers: 80 of 80 on both sets
  (a header no reader takes gives no rig, with the reason in the log and in
  `not_decoded.ragdoll`).
- **Parts 1 and 2 on all platforms: a 64-bit record value on console.** It is stored as two
  32-bit words, low word first, each word byte-swapped;
  `skeleton_records.record_value` read the eight bytes as one big-endian
  number, which exchanged the halves (the Ragdoll sheet id came out as
  `0x45af888d43b830d4`). It now reads `0x43b830d445af888d` on all six sets,
  as the fragment parser always did.
- **Parts 1 and 2 on all platforms, console characters: missing parts.** The byte order of a
  part model was chosen by counting mesh descriptors per order;
  single-submesh models tied and were read little-endian, which lost the
  part (Heavy's chains and sunglasses, the 2x4 weapon, three Gimp parts: 29
  pieces in 11 Part 2 characters on each console; the sunglasses of 19
  Part 1 variants on Xbox 360). The four part loaders, `decode_model` without
  an order, the model-node reader and the skeleton-name reader now take the
  order the header states (`watchmen_extract.header_order`); the count rule
  is left for a header without a class name, which no shipped model has.
  Xbox 360 and PS3 Part 2 characters have the PC piece list (787 pieces,
  same vertex and triangle counts, bounding boxes within 0.3 mm on the full
  export); the three Part 1 sets have one piece list too (1,525 pieces in
  80 GLBs). The count depends on the texture sheets of the standalone
  Part 1 (see "the older record layout of the standalone Part 1"): six GLBs
  (Mercenary ×2, the four KnotTop thugs) group their meshes by sheet, and
  with the sheets an outfit that differs only in its sheet is one mesh with
  material variants, as on PS3 (without them PC Part 1 has 1,685 pieces;
  in those six GLBs 283 pieces go and 116 come on PC and on Xbox Live).
- **Parts 1 and 2 on all platforms: planar character pieces.** A submesh with one flat axis
  failed the strict buffer scan and was dropped on every platform
  (`Large_Head_2`, an eye card of 40 vertices). The part loader falls back
  to the planar scan the model extractor already uses; the offset it finds
  is the one the PC header gives.
- **Parts 1 and 2 on all platforms: PS3 sounds had no length.** The PS3 `sound` header is
  now read: sample count at +11 after the property bag, MP3 at +55, on all
  2,921 + 3,953 sounds; the count equals the MP3 frames × 1,152 (frames − 2
  on the 55 / 90 looping sounds). `text_meta.json` had no duration on any
  PS3 sound (5,704 values in Part 2, 14,779 in Part 1) and has all of them
  now; in `sound_meta.json` the `duration_s` keys without a value go from
  11,102 to 118 and from 23,732 to 243, the PC counts, and `talk_s` from
  442 and 1,311 to 0. The four Twilight Lady counter waves have a talk
  length again, and on the full export the PS3 face confidence counts
  equal PC (Part 2: 957 "high", 24 "medium", none "low", where the first
  export had 953 / 24 / 4).
- **Parts 1 and 2 on all platforms: no Xbox 360 sound could be decoded.** The XMA2 packets
  start 26 bytes after the property bag; 1.3.0 cut from byte 30, so every
  `.xma` began four bytes into its first packet and ended with the cue
  count. All 2,921 + 3,953 files were the right data shifted by four. Three
  fixed files were decoded with ffmpeg: correlation 1.0 / 0.997 / 1.0 with
  the PC sound at zero lag, where the 1.3.0 files gave "Invalid data" or
  silence. vgmstream decodes the files of the full export (26 of 26
  sampled, 14 of Part 2 and 12 of Part 1; correlation with the PC sound
  0.99 in 4,096-sample windows; five files cut the 1.3.0 way
  gave silence or 0.03). The header's sample count equals
  the XMA2 frame count × 512 on every sound.
- **Parts 1 and 2 on all platforms: PS3 `.mp3` files cut short.** The size scan took the
  bytes-per-second or the rate field for the data length on 58 (Part 2) and
  79 (Part 1) sounds, by 64 to 448 bytes in Part 2. The MP3 is the header's
  whole segment; the other 2,863 / 3,874 files are byte-identical.
- **Parts 1 and 2 on all platforms: a loose Xbox 360 tree left four one-track music streams
  without channels, rate and duration** (the stream is named without
  `derived_x360/`). They are taken from the stream's own descriptor.
- **Parts 1 and 2 on all platforms: one fragment was read in the wrong byte order.**
  `kapow_fragment.detect_order` took the first order whose chunk walk ends
  on the last byte; a 393-byte big-endian fragment
  (`SE_Countered_victim02.fragment`) passes the little-endian walk by
  accident and parsed to no node, which cost three sound events on console
  Part 2 (3,877 → 3,880, as PC). When both walks pass, the order whose
  payload holds a schema record is taken. Over every fragment of the six
  sets (906 per Part 2 set, 758 per Part 1 set) that one file on the two
  Part 2 consoles is the only result that changes.
- **Parts 1 and 2 on all platforms, Part 1: four stream files were never read.** Part 1's
  Prison level keeps the streams of 92 assets in four stream-only files
  (`Prison/Art/PrisonYard`, `Buildings/BuildingPrisonShowerRoom`,
  `GeneratorRoom`, `hallway` `.block_s_z`), named by four manual stream sets
  in the trailing blob of `Prison.block_h_z` (96 entries; each file is
  exactly the sum of its entries). They are resolved now: texture headers
  with a stream 1,190 → 1,206 of 1,206, models with stream data 1,031 →
  1,085 of 1,090, the same on PC, Xbox 360 and PS3 Part 1. The five models
  that remain have an empty stream record (the three skeleton models,
  `GuardRoom_Door_02`, `Docks_waterSurface_aligner`).
- **Parts 1 and 2 on all platforms: `parse_block_trailer` read the stream-set bounds as two
  4-float vectors.** They are two 3-float vectors on all three platforms
  (the code reading had it wrong; the Prison block is the only shipped data
  with a set). The 4-float layout is tried only when the 3-float one does
  not end at the blob's end.
- **Parts 1 and 2 on all platforms: the older record layout of the standalone Part 1.** PC
  and Xbox Live Part 1 store a property record without its type hash
  (`[owner][key][k][k dwords]`). Texture sheets (`sheet.json`, `spec.txt`),
  `.pb`, `.grass`, `.detailmesh`, the model property bag and the ragdoll
  material of the pivot book are read in that layout; which layout a block
  has is decided by which one ends exactly at the block's dword count, and
  the value types are those the typed build stores for the same property
  (140 names). Before: no `sheet.json` on 1,206 textures, 42 to 98 % of
  the three property files undecoded. After, against the PS3 build of
  Part 1: all 1,206 first sheets and specular pairs, 1,090 model bags and
  12 property files are equal; of 1,436 sheets 1,035 are equal in every
  property, 400 differ only in `uniqueID` and one in `reflectionType`
  (`Ground_PrissonFloor_01`). The 24 bytes after the `.detailmesh` bag (25
  in the newer layout) and the model header of this layout are read by the
  items "The raw-only formats are decoded" and "The model header of the
  stand-alone Part 1 (PC, Xbox Live) is read".
- **Parts 1 and 2 on all platforms: `model_lod_info` lost the LOD distances behind an
  `animation` path** (a fixed 20-byte stride; 22 models in each Part 2 set,
  31 in PS3 Part 1). The bag is walked record by record.
- **Parts 1 and 2 on all platforms: fragment JSON `instances` presented integers as text.**
  `nodes`, `named_instances`, `instances` and `transforms` came from a byte
  sweep of the raw file, chunk headers included: an integer followed by a
  key hash of printable bytes read as text (`siblingOrder: ['XdV/']`, the
  bytes reversed on console), a name or string cut by a chunk boundary was
  lost, a `localPos` whose value starts a chunk was read one word early,
  and `nodes` paired each type with the id of the following record. The
  four sections are built from the exact parse. Fragments whose `instances`
  disagree with their own `nodes_full`: 553 → 0 in each Part 2 set, 486 → 0
  in each Part 1 set (635 fake values in 80 files on PC Part 2). Fragment
  JSON files that differ between PC and console: 53 → 4 in Part 2; in
  Part 1 PC against PS3 80 → 12, PC against Xbox 360 70 → 0. Every
  remaining difference is a typed value of the source: the Bordello enemy
  types and three Bordello sound volumes of the PC archive, one or two
  nodes in two level fragments, and the newer build of PS3 Part 1.
- **Parts 1 and 2 on all platforms: a wrong type guess swallowed the next record.** A vector
  or quaternion guess for an unknown key is refused when a component is a
  marker, a known key hash or not an ordinary float. Part 1
  `WaypointController` nodes lost `_tuseteleport` inside a vector
  `[0.5, -1448569344.0, 0.0]` (6 nodes per set).
- **Parts 1 and 2 on all platforms: false "extract looks like Part 1" warning.** It tested
  whether the source path contains "part1", and fired on PS3 and Xbox 360
  Part 1. It now compares each bind in `<extract>/binds` with the extract's
  own skeleton model (bone list, rest pose) and names the bind that does
  not match; none does on the six sets.
- **Parts 1 and 2 on all platforms: Xbox 360 textures with more than three layers.** The
  layer plan is read from the exact big-endian header, where each layer
  carries its stored size (the last u32 of the image descriptor; the sizes
  add up to the stream on 937 of 937 and 1,190 of 1,190 textures). The
  stride walk it replaces stopped at format 8, which is DXT3A on this
  console and holds the slot-4 height map (the name and nibble order are
  inferred, then confirmed by pixels against the PC L8 map). The fourth
  layer of 9 / 22 textures is written, `pickupWindows` has its 3 layers,
  `Caustics01_001` is 32 frames × 2 layers instead of 160 images, and the
  slot-7 specular-size map (DXT1 here) is labelled `specSize` and written
  as its red channel on 10 / 2 textures. "approx stream" lines: 13 and 38 →
  0. Layers missing against PC: 54 and 27 → 0; layers PC does not have: 140
  and 4 → 0.
- **Parts 1 and 2 on all platforms: cube maps, all three platforms.** A cube map stores its
  mip LEVELS in order with six faces per level on PC and Xbox 360 (Xbox 360
  faces padded to 32 × 32 blocks), and six face chains each padded to 128
  bytes on PS3. Read that way the six faces of all 310 cube maps (110 in
  Part 2, 200 in Part 1) are pixel-identical on the three platforms. Before,
  PC and Xbox 360 read six face chains, so faces 1–5 were wrong on both, and
  PS3 wrote one face. An Xbox 360 cube under 32 texels and a PS3 segment
  that is not six aligned chains write face 0 only and say so; neither
  occurs in the six sets.
- **Parts 1 and 2 on all platforms: `extract` and an asset stored in several blocks.**
  Identical copies were decoded and written again (Part 2: 462 texture and
  241 model copies), and a name stored under a second spelling that differs
  only in letter case (30 in PC Part 2, 187 in PC Part 1) put the last
  spelling inside a file named with the first. An asset is written once,
  under its first spelling (its canonical one where
  `wlib/canonical_names.json` lists it). No name of the six sets has two different
  header / stream pairs; a copy with different bytes would be written as
  `<stem>~<block>.<ext>` with a log line. Standalone `_h_z` / `_s_z` pairs
  go through the same registry: two pairs with one base name in different
  folders overwrote each other; a copy with different bytes is now written
  as `<name>~<folder>.<ext>` with a WARNING and an identical one is not
  written again (the six sets have three distinct base names each, so their
  output is unchanged).
- **`weight_is_area` on console models.** The area test used rtol 1e-3; the
  console copies of five Part 1 models store triangle areas 0.10–0.16 % off
  and were reported as not area-weighted. The tolerance is 5e-3.
- **Parts 1 and 2 on all platforms: a loose-folder source had no navigation data.** Part 1
  on PC (`derived_pc`) and Xbox Live (`derived_x360`) keeps the `.hpd` files
  and `database.bin` in the sibling `data/` and `data_baked/` folders.
  `extract` copies them to `files/data/…` and `files/data_baked/…`, where
  the archive sets have them (`--no-files`: reads them in place), together
  with the `.bik` movies of `data/Art/cutscenes` (the log line `LOOSE
  SOURCE` counts path data, movies and other files): 6 nav
  GLBs instead of 0, byte-identical to the PS3 Part 1 ones. A level also
  finds its path data through the `.aipathdata` it names when its name is
  not the folder's (`Streets2`, `Undergound`: `nav` was null on PS3 Part 1
  too).
- **Parts 1 and 2 on all platforms, small:** the transform scan of `skeleton_records.parse`
  skips non-finite probe positions (it raised a numpy `RuntimeWarning` in
  every extract log; same result, one `note:` line); a table whose combat
  effects or face block failed to build records that (`build_failed`) and is
  reused instead of rebuilt on every run; the jiggle cache file carries the
  clip's loop flag and the solver key a version, so a bake made without the
  animation table is not served later; `watchmen gendata` lists `respell`
  in its usage line.

- **glTF-validator on the character GLBs: 0 errors, 1,244 warnings, 51
  infos, no hints.** Part 2 PC, 26 GLBs, validator 2.0.0-dev.3.10. With the
  joint slots and buffer views as 1.3.0 wrote them the same export has
  252,024 `ACCESSOR_JOINTS_USED_ZERO_WEIGHT` warnings and 7,002
  `BUFFER_VIEW_TARGET_MISSING` hints more (see "Behaviour changes"). What
  remains is intended: `NODE_SKINNED_MESH_NON_ROOT` (1,244 warnings; every
  skinned mesh hangs under the transform-less `root`, `alternatives`,
  `ragdoll` or `face_root` group) and `UNUSED_OBJECT` (51 infos; the
  `alternatives` and `ragdoll` nodes are in no scene on purpose). The 18 face
  GLBs: 18 warnings of the first kind, no hints.
- **A failing face step does not cost the animation table.** `anim_meta`
  wraps `face_rule.build` like the combat and effects steps: on an error the
  records it had written are removed, the failure is recorded under
  `build_failed.face`, the table is written, and `characters` reuses it
  instead of rebuilding it on every run.
- **A jiggle memo is read only when it is not older than its raw bake**;
  otherwise the clip is baked again.
- `tests/test_p3_raw_formats.py` accepts the `int32` array Pillow before
  10.3 returns for a 16-bit grey PNG (the file written is the same). The
  suite passes on Python 3.8.20 and 3.9.25 with the minimum pins (numpy
  1.20.0, Pillow 9.0.0).

### Changed

- **A resumed export keeps a GLB only when it was written with the same
  options (options record).** `characters` and `faces` record every GLB
  they write in `<OUT_DIR>/_glb_options.json` (format
  `watchmen-glb-options/1`): the coordinate frame, materials, names,
  vertex attributes, the `WATCHMEN_MATERIAL_OPTS` / `NORMALS` / `CONSOLE` /
  `NO_SYNTH` / `NO_RESTORE` switches, a writer revision
  (`characters_export.GLB_REVISION`) and, for `characters`, the jiggle
  cache signature, face rule and idle cycle, parts, ragdoll and the format
  and revision of the animation table. A GLB without a record or with
  other options is written again and the log names the difference; the run
  says how many GLBs it kept. 1.3.0 kept every GLB that existed, also after
  `--jiggle-model` changed, so a folder could hold GLBs of two settings
  without a word; the options new in 1.4.0 are recorded as well. A GLB
  without a record (every GLB of 1.3.0) is written again once. Measured on
  real data: a second `characters` run with the same options keeps the GLB
  (TwilightLady, Xbox 360 Part 2), one with `WATCHMEN_PARTS=all` rewrites
  it; the record changes no GLB byte (the 18 `faces` GLBs of PC Part 2).
- **The `characters` log names the GLB it wrote.** `characters` and
  `faces` pass the final name to `write_glb`, which writes `<name>.tmp` and
  renames it, so a killed run leaves no partial GLB and the `wrote` line
  names a file that exists. *1.3.0 output:* the `wrote` lines of
  `characters` name `<variant>.glb.tmp`, a file that no longer exists after
  the rename.
- **A cached bake records the bind and the clip it was baked from.** Every
  `_bake/<skeleton>/<clip>.npz` stores `bind_sha` (sha1 of the bind's
  `Rb`, `tb`, `tloc`, `par`, `names`: equal for two binds that bake the
  same) and `clip_sha` (sha1 of the `.animation` file); a bake whose bind or
  clip differs, or that has neither key, is baked again
  (`characters_export.bake_is_current(..., bind=)`, `bind_digest`,
  `clip_digest`). 1.3.0 reused a bake made with another bind (after the
  binds were rebuilt) or from another extract written into the same
  folder. The hash keys change no palette: the 204 raw bakes of NiteOwl
  (PC Part 1) equal, array for array, those baked without them.
- **The jiggle constants come from the extract.** `characters` and
  `char --jiggle-model` read the `PhysicsWorld` values (gravity, rate,
  spring, damping, limit per group) of the extract's `GameEssentials`
  fragment and pass them to the solver; `jiggle_d6.load_world_props` no
  longer looks in a folder next to the toolkit, and without an extract, or
  when the fragment cannot be read (one `WARNING` line), it gives the
  shipped values. The values are equal in the six shipped sets,
  so no output changes; values other than the shipped ones enter the jiggle
  cache tag (`jiggle_d6.cache_signature(props=)`, `jiggle_cache_dir(...,
  props)`), and the tags of the shipped values stay as they were.
  `variant_glb.build` takes `extract_root`.
- **Exit codes.** `extract` and `all` return the extractor's exit code (2
  for an archive that is not there or a bad option; 1.3.0 returned 0, and
  `all` went on to the bind step). `characters`, `faces`, `charlibs`,
  `animmeta`, `fxmeta`, `soundmeta` and `grademeta` stop with exit code 2
  when EXTRACT_OUT has no `extracted/` folder (`wlib/extract_out.py`);
  1.3.0 (which had the first four) wrote empty tables with exit code 0,
  and `faces` created `<EXTRACT_OUT>/binds/face`. `faces`
  creates its folders once a head is found.
- **`characters` reads `01_game.naz`, else `game.naz`, when no archive is
  named**, as `char` and `bake` do. A bind that needs the archive (its
  skeleton model is not in the extract) and an archive that is not there
  give one error that names the third argument; `ensure_binds` with an
  extract no longer opens a missing archive.
- **Xbox 360 textures untile about eight times faster.** `_xg_untile`
  computes every element's address at once (numpy); the bytes are the same
  (1024 × 1024 32-bit layer: 1.42 s before, 0.17 s after, equal digests).
- **The clip baker reads clips only from the bank it is given.**
  `bake_v4.bake(bank=...)` replaces the module function `_bank_lookup`,
  which the character, face and library writers overwrote at run time and
  which otherwise unpickled four fixed files in `/tmp`
  (`/tmp/clipbank_*.pkl`); `variant_glb`'s script no longer defaults to
  `/tmp/clipbank_en4.pkl` and `/tmp/allbake` (`--bank` names a pickle,
  `--bakedir` defaults to `bake`).
- **Tables do not depend on the Python version.** The means in
  `sound_meta.json` and `anim_meta.json` (`duration_s.mean`, `talk_s.mean`)
  are summed with `math.fsum`: `sum()` of floats is a plain fold up to Python
  3.11 and compensated from 3.12 on, and the last bit decides a rounding to
  4 decimals now and then (14 `talk_s.mean` values of PC Part 2 differ by
  0.0001 between the two). Measured on the six-set export: `anim_meta.json`
  built on Linux with Python 3.10 is byte-identical to the one built on
  Windows with Python 3.14 for PC Part 2 and PS3 Part 1, and `sound_meta.json`
  for PC Part 2, PC Part 1 and Xbox 360 Part 2 apart from the added
  `missing_event_lists`.
- **`animmeta` / `soundmeta` walk the extract once.** The searches for the
  class, face, character-visual and enemy fragments
  (`extracted/**/CharacterAnimation/AnimationClass*.fragment` and the like)
  share one directory listing while a table is built (`kapow_json.tree_cache`
  / `glob_tree`; the paths found are glob's), and the node-type scan of
  `kapow_json.fragment_json` judges each NUL-free run once instead of once
  per start offset, which was quadratic in the length of a run. Measured on
  the six-set export, PC Part 2, read through a network file system: the
  animation table builds in 81 s where one walk per search and the
  per-offset scan take 155 s, and the two tables are byte-identical; the
  907 fragment and scene files of that extract give the same JSON in both
  byte orders (38.8 s -> 15.1 s for the parse alone).
- `characters_export.animation_meta()` rebuilds an `anim_meta.json` cached by
  1.3.0 when the extract has face fragments and the table lacks the face
  block. Apart from the added keys, the rebuilt table differs from the 1.3.0
  one only in the `joint_space` sentence.
- `watchmen.JIGGLE_MODELS` and the usage strings list `solver` first;
  `variant_glb`'s own `--jiggle-model` option takes its choices from
  `jiggle_d6.MODELS`.
- `tools/ghidra/DefineKapowHandlers.java` labels a row of `names2.tsv`
  "Kapow name evidence" in the plate comment instead of "Kapow handler".
- `characters_export.TEX_OVERRIDES` is empty: the Dominatrix body skins come
  from the fragment's sheets.
- glTF-validator on the 26 character GLBs: 0 errors, as before. Each hidden
  skinned node (outfit, weapon, ragdoll proxy) adds one
  `NODE_SKINNED_MESH_NON_ROOT` warning (1,244 in all, 186 before) and the
  `alternatives` and `ragdoll` nodes one `UNUSED_OBJECT` note each.
- `bake_v4.py`, the clip decoder and the binds are unchanged.
- `kapow_json.to_json` routes `.particle` to `particle_asset.to_json` and
  accepts `.scene`; `kapow_fragment.parse()` returns `header`.
- `nav_data.find_inputs` accepts a list of trees; `nav_data.export` creates
  its output folder only when there is something to write.
- `watchmen.py`: `levelmeta`, `savemeta`, `text`, `textmeta`, `fxmeta`,
  `navmeta`, `particlemeta` in the usage table; `extract` lists `--no-text` and `--no-nav`.
  `--frame true|mirrored` on the eleven commands of `watchmen.FRAME_COMMANDS`
  (and in `watchmen_extract.py`'s own parser).
- `materials.NO_HIGHLIGHT`, `materials.no_highlight(sheet, intensity=None,
  spec_black=False)`.
- New module `wlib/frame.py`: `mode()`, `reflect_gltf()` (it also swaps the
  bounds of rotation and matrix accessors, refuses bounds it cannot reflect,
  and refuses any two accessors whose byte ranges overlap unless they are
  the same range in the same role), `finish_gltf()`,
  the scalar rules (`vec`, `quat`, `xz`, `yaw_deg`, `mat34`, `mat4`,
  `tangents`), `stamp_json()`, `frame_of()`, `glb_frame()`. Per module:
  `anim_meta.build(..., frame=)`, `apply_frame`, `to_frame`, `reflect_meta`,
  `conventions()`; `ragdoll_rig.reflect_rig`, `sidecar(..., frame=)`,
  `glb_helpers(..., frame=)` (its `extras` are in the output frame, its
  vertices and node transforms stay engine numbers for the writer),
  `conventions()`; `level_meta.gltf_trs(pos, quat, frame=)`,
  `conventions()`; `fx_meta.cut_camera(..., frame=)`, `cut_placement()`;
  `characters_export.glb_is_current()`. The bake and bind caches are engine
  numbers as before and are shared by both frames.
- `wlib/engine_enums.json`: the enum families the new modules need (combat
  buttons and combo items, effect and placement ids, collision types,
  particle events) are constants of those modules and exported in their own
  blocks; the table itself changes in two places only, listed under "Data
  tables".
- A cached `anim_meta.json` is told apart by content, not only by layout:
  the table carries `revision` (`anim_meta.REVISION`), and a resumed
  `characters` export rebuilds a table whose revision is missing or
  different (`characters_export.anim_meta_is_current`). The format markers
  (`watchmen-anim-meta/2`, `watchmen-face/2`, `watchmen-combat-meta/1`,
  `watchmen-fx-meta/1`) name the layout. A resumed export rewrites a GLB
  whose recorded table revision differs (options record, below).

### Data tables

- `sound_meta` `not_established` lists the 2D listener path and
  `SoundDef.Active` on PC Part 1.
- `wlib/property_store_flags.json`: `bit3`, the 16 properties whose
  registration sets bit 3 of record +0x38 (meaning not established).
- `wlib/event_editor_params.json` (the editor's argument table of 16 event
  ids, 0x5c1767) and `wlib/filter_exposed.json` (the property filters of
  `TriggerActionGeneral`, `TriggerActionParticle` and `TriggerUseFragment`:
  0x85e3e8, 0x86038f, 0x873568). Read from the executable; no regeneration
  command.
- `wlib/input_code_enums.json` gains `LogicalInputButtons`
  (0x80d17a–0x80d3b8) and `MetaInputDevices` (0x775a93–0x775ac3); the mouse
  codes 0x101 / 0x102 / 0x104 are read from code (0x7afdba).

- `prop_hash_dict.pkl`: a name a native class registers is spelt as
  registered. The hash ignores case, and 1.3.0 had, for 61 such hashes,
  another case variant — mostly the capitalised editor caption (`Texture`,
  `Duration`, `Position`, `Speed`, `Force`, `Ambient`, `Factor`, `Animation`,
  `Mass`, `Priority` …) or an all-lower-case form (`textres`, `movementtype`,
  `targetanimation` …). 58 are respelled; three stay because the dictionary
  spelling is a real name of its own (`PLATFORM`, `Scene`,
  `physicsTimepassed`). 17 registered names the table lacked are added
  (`pi`, `fog`, `Play`, `damp`, `dump`, `time`, `life`, `mode`, `numX`,
  `numY`, `is3d`, `edit`, `stop`, `Save`, `open` and two editor option
  names). Nothing else in the table differs: it is the 1.3.0 table with
  `gendata respell` applied (23,753 → 23,770 names), and applying it again
  changes no byte. Sprite registers `is3D` where the sound assets register
  `is3d`; the generic walk uses the class's spelling for a `Sprite` block.
  What this changes in written files is under "Behaviour changes"
  (`.fragment.json`).
- `kapow_fragment_keys.pkl` (the fragment key table, `kapow_fragment.NAMES`):
  the 99 names that differed from the registered spelling in letter case
  only are spelt as registered (`Visible` → `visible`, `Open` → `open`,
  `UseRealTime` → `useRealtime`, `textres` → `textRes` …; 98 in `keytable`,
  2 of them also in `stdkeys`, and the same names in `nameable`); every
  name still hashes to its key. Four keys take the type their native
  registration gives: `alphaThreshold` and `density` integer,
  `materialColorAlpha` number, `model` string (no fragment carries them).
  19 properties the executable registers through its list and
  `netparticipant` wrappers are typed: `typeAffectors`, `spawners`,
  `affectors`, `initializers`, `subPivots`, `actors`, `joints`, `cloths`,
  `particleTypes`, `sheetVec` and two editor lists as `list(Entity)`, two
  log-channel lists as `list(string)`, `boneScaleFactors` and one editor
  list as `list(vector)`, one as `list(quaternion)`, `remoteParticipants`
  as `list(netparticipant)` and `localParticipant` as `netparticipant` (one
  4-byte slot; `kapow_props.TYPES` knows the type). Decoding every fragment
  of four sets gives the same values with the old and the new table. The
  readers that look a fragment property up by name take either spelling.
  What this changes in written files is under "Behaviour changes".
- `registered_names.json` (new): the spelling of the 1,224 property and
  command hashes the native classes of the Part 2 PC executable register
  (1,371 registrations), with the classes, the three kept names and the
  `is3D` exception. Research output from the registration sites — the scan
  needs a disassembly's function index, so the table is shipped rather than
  regenerated — and each entry is re-hashed on load.
  `gen_data.build_prop_dict` uses it (a registered spelling found in the
  executable outranks every other string of that hash).
  The shipped dictionary is not the byte output of `gendata strings` on the
  Part 2 PC executable alone (that gives 40,575 names against 23,753, with
  675 shared hashes in another letter case), so it was respelled, not
  regenerated. The file also lists the native messages (`native_messages`):
  the 589 registration strings of the executable under the hash each is
  registered with (577 hashes; `kapow_props.native_message_hash`). The rule
  is read from code; the hashes are not validated against a sender.
- `reg_dump.json`: every class gains `root_index`, every command `visibility`
  (the same number as `kind`), `dispatch_kind` and `dispatch_index` (how a
  command sent by hash is routed: 3,166 root-only, 295 state-only, 61 with
  several state versions, 134 state overrides with a root fallback). The
  file regenerates byte-identically from the executable; nothing else in it
  changed.
- `engine_enums.json`: family `CHARACTER_BONE_TYPES` (23 bone types, 0 = Head
  … 22 = RUpArmTwist; an out-of-range type gives 18, GamePivot); the `effect`
  of events 29, 30, 31 and the `evidence` of events 6, 23, 29, 30, 31, 40,
  59, 70, 76, 77, each naming the later read.
- `tools/ghidra/names2.tsv` (new): 5,036 further function names for the
  decompilation, same four columns as `handlers.tsv`, each with a confidence
  (`high` 2,278, `medium` 2,758) and the source of the name; among them the 28
  functions of the Kynapse bridge, named from their role. Research
  output; not used by the toolkit.
- `wlib/builtins.json` (new, format `kapow-builtins/1`): the 123 builtin
  script functions and 19 properties, walked from the registration
  function 0x47ff8c with capstone. Research output; read by
  `wlib/script_builtins.py`, not used by the extractor. `other_builds` says
  what the other images differ in, from their member-name strings: Xbox 360
  Part 2 and both PS3 parts have the same 139 names; Xbox 360 Part 1 lacks
  eight (indices 68, 69, 98, 99, 100, 119, 120, 121) and has two of its own.
- `wlib/pivot_sheets.json` (new): the 47 pivot sheets of PC Part 2 (book,
  name, id, collision mask, friction, restitution), measured on the three
  pivot books. `level_meta` uses it for `ai_sight` when an extract has no
  pivot books of its own.
- `wlib/input_code_enums.json` (new): the `KeyboardKeys`, `GamepadButton`
  and `MouseButtons` enums of the executable (0x4cc842, 0x4d3514, 0x4db801),
  for `decoded.button_map.code_names` of `savemeta`.

### Documentation

- Fall-off and cube-reflection formulas of the deferred main pass, from the
  shader text.
- No sRGB sampler or render state in `KapowMulti.1.trace`.
- Frame time of a capture from two scroll constants; 12 captured ragdoll
  switches with start velocities.
- Two-listener mixing rule and the `multiListener*` field map.
- The 128 voice limit counts playing voices plus voices queued for
  destruction.
- `equalizer` and `compressor` are not registered effect types.
- Effect blend rules for integer, truth and choice parameters.
- Float-to-int conversion sites of the script handlers.
- Player controllers are activated only on scene activation.
- Xbox 360 Part 1 `SubtitleHUD` bodies.
- Weapon variant counts are neither reset nor given back; exploration camera
  collision rules; decal rules; reader of `m_iagentbasetype`; Kynapse
  capacities 500 / 8 / 10; `BackFlip` exit transitions.
- Layer mix of the animation system (0x5b7788, 0x596636; 0xc8e03c = 2π) and
  the "Layers" section of `docs/ANIMATION_META.md`; clip tracks bind by name
  through the channel table 0xe157e0; `LinearDampSignedAngle` and the NPC
  heading smoothing; the footstep hit lists by the owner's collision mask
  bit 0x1000; Underboss movement, flee and flamethrower volumes;
  `BehaviorWaypointMove` per frame.
- The shipped PC configuration sets neither `shadowmode` nor
  `usescaledbuffers`; the message hash is the message id (0x4ef657,
  0x50ed51); PS3 Part 2 twins of the electric-armor hit, the 11.0 − distance
  store, the decay of 20 per second and the bone map; texture `usage`
  values, the model header's `skinnedBoneCount`, the shadow hull's cloth
  link, the 40-byte cluster record, the per-vertex u16×4 table of cloth
  shadow hulls, the texture animation `Cycle` head, the pivot-book header;
  particle rules of `EmitterTrailSpawner`, `EventGeneratorAffector`,
  `TerrainSurfaceSpawner` and the spawn position, with the use of the less
  common classes on four sets; `SpriteBar` chunk motion and `ScreenFadeCtrl`.
- `docs/ENGINE_CONSTANTS.md`, "2026-10-07": sound nodes (SoundSlot,
  SoundSystemNode, the I3DL2 effect definition and its 30 presets, stream
  records, music playback, option volumes), the Light and Camera nodes, the
  sequence action track and the camera tour, Track / GeometryEffect / Wind /
  DecalManager, the trigger, use-trigger, waypoint and culling classes, the
  scene-graph and model-resource functions, the twist-bone pass and the
  additive layer rule; the AI partner test (`IsAIPartner` 0x678254); the
  sight-cache defaults (0.2 s / 1 s, 0x935710).
- AI sight cache: 0.3 s / 1 s on every level of the six sets (33 nav
  files); `CollisionNode` constructor defaults: `physicsType` 1, first sheet
  of `/pivotbooks/default.pb` (0x4a8944) (`docs/NAV_DATA.md`).
- Xbox 360 Part 1 `SoundDef.Active` (0x82b21808) asks for the subtitle of
  the definition itself, like PS3 Part 1 (read from code).
- Console joint order read from the 22 skinned PS3 vertex programs
  (`indices.yzwx`); console format 10 joints are bytes 17, 18, 19, 16 and
  equal PC on all four console sets (measured).
- PS3 `shader.archive` layout (`docs/FORMATS_MISC.md`).
- `SaveFragment.command_save_fragment` (0x8127b5) calls an empty stub.
- `docs/FORMATS_MISC.md` `.sequence`: action track, update culling distance,
  frame-step time base, start / stop events; `.font`: the header and glyph
  fields. `docs/FX_META.md`: level cameras, decals (no decal node in the PC
  levels). `docs/TEXT_ASSETS.md`: "TextBox layout". `docs/SOUND_META.md`:
  distance attenuation, reverb send, volume taper, option volumes, Doppler.
  `docs/KAPOW_NAZ_FORMAT.md`: the PC stream record as an `ogg_packet`, the
  primitive type, the morph-target records, the cloth-mesh flag.
  `docs/ANIMATION_META.md`: criteria units, the editor's event and impact
  rules. `docs/RAGDOLL_RIG.md`: when a cloth's world fixes are applied.
- `tools/ghidra/README.md`: why 62 handlers were lost in the second dump
  and how to get them back.
- `docs/re/README.md`, "Coverage of the executable": 58.9 % of the live engine code is cited
  by a report (1,948,530 of 3,309,065 bytes of the merged 35,542-function dump; 32.8 % by a
  check, review or verify report; measured by cited-address coverage).

- `docs/re/`: two more research reports with their tables — `physx_d6.md` /
  `.json` (what PhysX does with the jiggle joint) and `vcolor.md` /
  `vcolor_shaders.json` (vertex colour, tangent frame, winding). Each opens
  with its author's own correction block. `docs/re/README.md` says what each
  establishes, at what evidence level, and lists what the implementation
  corrected: the belly is explained; the capture ran at about 64–65 fps with
  zero-step frames, not at 60 and not at 55; the tangent sign was not the
  bug, the swapped normal-map channels were.
- `docs/ENGINE_CONSTANTS.md`: two new dated sections. "2026-10-03 — PhysX
  soft-limit jiggle; vertex colour, tangent frame and normal-map channels"
  and "2026-10-04 — the face system; texture paths and texture sheets", the
  latter with the head controller, the four inputs of a face class, how a
  model's textures are resolved, texture sheets and their overrides, and how
  the solver bakes a clip. Earlier statements now known to be wrong carry an
  inline `[corrected 2026-10-03: …]` or `[corrected 2026-10-04: …]` note:
  the spring as a torque law and the "wedge" with a free swing axis, the
  `solver_soften` formula, every capture frame rate and the K / D pairs
  derived with them, the SDK's 7 rad/s angular-velocity limit, the open
  point on the vertex colour, the share of non-orthogonal tangents, the
  `ATI2` channel order, `get_valid_state` as a round robin, "a blink does
  not exist" (it does, as data), and the face pairing by clip name.
- `docs/ANIMATION_META.md`: the face block, in the table and in the GLBs.
- `docs/KAPOW_NAZ_FORMAT.md`: the `ATI2` block order (§4.2, §4.5), a new
  §4.6 on the texture's material switches, what the colour, tangent and
  bitangent fields and the `hasColor` / `hasAlpha` flags are (§6b), and the
  GLB output. `docs/WATCHMEN_EXTRACTION_MASTER.md`: a corrections summary
  (§0.7) and dated notes in place; its statement that the PC / X360
  normal-map divergence was "proven not a decode bug" is withdrawn, since
  the PC side of that comparison was transposed. `docs/FORMATS_MISC.md`: the
  alpha of a terrain vertex colour is a layer id in the terrain shaders.
- New: `docs/RAGDOLL_RIG.md`, `docs/SOUND_META.md`. Materials, ragdoll and
  audio: `README.md`, `docs/INDEX.md`, `docs/ANIMATION_META.md` (face format
  2, talk clips), `docs/KAPOW_NAZ_FORMAT.md` (§4.6 corrected, multi-track
  music streams, the model's articulated-body section, the pivot book, the
  occluder buffers and LOD distances), `docs/FORMATS_MISC.md` (the `sound`
  header), `docs/ENGINE_CONSTANTS.md` ("2026-10-04 — renderer, materials,
  ragdoll, audio", with inline corrections of the roughness statements taken
  from the older texture notes).
- `docs/re/`: ten more research reports (`wp0_script_names.md` …
  `wp7_fx_camera_hud.md`, `dominatrix_audit.md`, `face.md`) and
  `wp2_ragdoll_rigs.json`; `docs/re/README.md` lists what each establishes
  and every correction made to them since.
- Outfits, weapons, texture sheets and blend types: `README.md` ("Outfits
  and weapons", "Texture sheets and blend types"), `docs/INDEX.md`,
  `docs/ANIMATION_META.md` (`weapon_use`, the `parts` record),
  `docs/KAPOW_NAZ_FORMAT.md` (§4.7 texture sheets; `textureSheetsDescription`
  in the fragment), `docs/ENGINE_CONSTANTS.md` ("2026-10-04 — outfits,
  weapons, sheet lookup and blend states", with inline corrections of the
  three points the previous section left open).
- `README.md`, `docs/INDEX.md`: the three jiggle models, faces, the vertex
  attributes, `sheet.json`, the new options. The README's statement that the
  default jiggle model's constants are capture-measured was wrong for 1.3.0
  (that is `pivot`) and is gone.
- `tools/ghidra/README.md`: `FixNoReturn.java`, `names2.tsv`, the order of
  the steps and what the run found (functions 17,225 → 19,233).
- The 1.3.0 entry below is left as written. Three of its statements are
  superseded: "what the engine does with the vertex colour is not
  established" (it is), "the 31 models that have authored colours" (387),
  and the capture rate of "about 55 fps" behind the `pivot` constants (about
  64–65 fps; the constants themselves are unchanged in the code).

- New documents: `docs/COMBAT_META.md` (the `combat` block: every field, its
  evidence class, the rules behind it, how to consume it), `docs/FX_META.md`
  (event payloads, state and pair `fx`, the effect database, the camera rule
  and rig), `docs/LEVEL_META.md` (the level JSON, the graph's edge kinds, the
  path-object link, save files), `docs/TEXT_ASSETS.md` (the `text/` folder,
  the subtitle rule, the `textmeta` table), `docs/PARTICLE_FORMAT.md` (the
  grammar, all 28 classes with every property, enums and gradients, what the
  simulation and renderer do with them, the JSON, the `particlemeta` index)
  and `docs/NAV_DATA.md`
  (both navigation formats byte by byte, the export, the coordinate space
  and the 1 m height of the data, how path objects match level nodes). Each
  ends with what is not established.
- Corrected: `docs/FRAGMENT_FORMAT.md` (file header, `.scene`, leading native
  type records, entity references as the engine resolves them,
  case-insensitive asset paths; the "22 unknown-key occurrences" remark is
  obsolete), `docs/KAPOW_NAZ_FORMAT.md` (the language slots; the `textRes`
  layout; where the navigation files are), `docs/FORMATS_MISC.md` (the
  `.particle` bullet, the "stray u32s" of the block grammar, the particle
  emission surface of the model node records and its use by Part 1's rain,
  the JSON pipeline).
- Extended: `docs/ANIMATION_META.md` (the two new blocks and their markers,
  event `payload`, the added state / pair keys, the file layout, the GLB
  extras), `docs/SOUND_META.md` (`subtitle_key`, the TASER wording),
  `docs/ENGINE_CONSTANTS.md` ("2026-10-04 (feature round) — combat, effects
  and camera, levels, text, particles, navigation": the handlers and
  constants behind the six exports and what stays open), `docs/INDEX.md`
  (sections 4a and 6c to 6g, the code map), `docs/re/README.md` (twelve
  further corrections to the reports, among them the `.hpd` location, the
  event times of the effects report and five particle statements),
  `README.md` (the new outputs, commands and options; "Levels, text,
  navigation").
- The coordinate frame: `README.md` ("Coordinate frame", the option on every
  usage line), `docs/ANIMATION_META.md` ("Coordinate conventions"),
  `docs/LEVEL_META.md`, `docs/NAV_DATA.md`, `docs/FX_META.md`,
  `docs/RAGDOLL_RIG.md`, `docs/ENGINE_CONSTANTS.md` ("Tangent frame, culling
  and winding": what the facts mean for each frame), `docs/KAPOW_NAZ_FORMAT.md`,
  `docs/INDEX.md`. The research reports under `docs/re/` keep their text;
  `docs/re/README.md` notes that their "the export is a mirror image" and
  "mirror X" remarks describe the mirrored frame.

- Rules read from the executable: `docs/COMBAT_META.md` (throws and ragdoll contact damage,
  the receiving side, area attacks, sweep, attack permission),
  `docs/LEVEL_META.md` and `docs/NAV_DATA.md` (variants and weapons, AI start
  state, presets, groups, cube maps, the id join, the generation stamp),
  `docs/ANIMATION_META.md` and `docs/FX_META.md` (first-child blend, idle
  entry, hit hold, body and pair space with the GamePivot rotation, the fixed
  cut camera, blend times), `docs/FORMATS_MISC.md` (`.sequence` loop mode,
  `hosts_up`, target kinds, the linear rule per data type; particle emission
  surfaces), `docs/KAPOW_NAZ_FORMAT.md` (what the engine does with an
  archive, §1.1; header fields 32 / 327 / 328 / 388; compression by type;
  loading rules, the trailing blob and the memory budget table, §2.4;
  submesh fields; the texture alpha flag), `docs/TEXT_ASSETS.md` (language
  slots and selection; the exact key rule; when a line is asked for and who
  owns it; cutscene subtitles with both movie tables),
  `docs/ENGINE_CONSTANTS.md` (dated section "2026-10-05" with the script
  runtime, loading, renderer and AI rules; statements a later read had
  settled are corrected where they stand), `docs/re/README.md` (the points the checks overturned in the
  shipped reports), `README.md` and `docs/INDEX.md`.
- `README.md`: four claims are reworded to what was measured — the
  platforms do not produce identical assets, console untiling is not
  byte-exact against PC on every layer, the "3 to 17 % closer" material
  figure has no established noise floor, and byte-identical repeat runs
  are measured on one platform only. "Notes" says what has run on Windows
  (the six-set export) and what has not (the suite, the commands the
  export batch does not call, `--frame mirrored`), and what a Linux run of
  the same raw files gave: 30 models and one character equal in OBJ, MTL,
  `.model.json`, ragdoll JSON and every accessor compared; GLB files not
  byte-identical (PNG compression).
- **Parts 1 and 2 on all platforms.** `README.md`: a measured "Platform support" table (per
  set what decodes and what does not) replaces the "Platform differences"
  note; the statements that some console parts are dropped, that no console
  ragdoll is written, that PS3 sound durations are empty and that four
  Part 1 blocks are not read are gone with their causes. `docs/
  KAPOW_NAZ_FORMAT.md`: stream sets and stream-only blocks (§2.4, with the
  bounds corrected to two 3-float vectors), the byte order a header states
  and the two property-record layouts (§3), the console texture header,
  Xbox 360 format 8 and cube map storage on the three platforms (§4.2).
  `docs/FORMATS_MISC.md`: the Xbox 360 and PS3 `sound` headers, the older
  record layout in `.pb` / `.grass` / `.detailmesh`. `docs/
  FRAGMENT_FORMAT.md`: the JSON sections and the seven Part 1 keys with
  their evidence. `docs/RAGDOLL_RIG.md` (platforms), `docs/SOUND_META.md`
  (`wave_durations`), `docs/LEVEL_META.md` (`stable_uid`, `nav_note`),
  `docs/NAV_DATA.md` (loose sources), `docs/ENGINE_CONSTANTS.md` and
  `docs/INDEX.md`. `docs/WATCHMEN_EXTRACTION_MASTER.md` §14: the XMA2
  offset is corrected to +26 and the passage that put the silent Xbox 360
  sounds down to the decoders is marked superseded, as is the PS3 cube
  note. Also corrected where they stood: `ENGINE_CONSTANTS.md` no longer
  lists the pair GamePivot question as open, `docs/re/formats.md` and
  `formats_tables.json` name the version signature at 32, and the
  `fx_meta` comment on a blended shot's length.
- **Raw formats, Part 1 header, console models.** `docs/FORMATS_MISC.md`: `.font`, `.terrain`
  and `.detailmesh` rewritten from the loaders (the `.font` section named a
  `decode_font.py` that was never in the tree, and its header breakdown was
  wrong), new sections for `.terraincoloringasset` and `.scene`.
  `docs/KAPOW_NAZ_FORMAT.md` §6b: the stand-alone Part 1 header, the
  console stream sizes and the console colour order. `docs/
  FRAGMENT_FORMAT.md`: the `inferred_names` marker. `docs/RAGDOLL_RIG.md`
  (Part 1 rigs), `docs/ENGINE_CONSTANTS.md` (a section with the facts of
  these items and their evidence level), `docs/INDEX.md`,
  `docs/WATCHMEN_EXTRACTION_MASTER.md` and `docs/re/wp5_runtime.md` (the
  asset table). `README.md`: the "Platform support" table and the list
  under it are split into what has a log line and a marker and what one
  set alone cannot show; the Xbox 360 Part 1 texture cell is 7 by the
  table's own metric (it read 8, counting `streamingwater` by its colour
  channels); the model GLB row states its basis (735 models, plus the three
  unit primitives on PC Part 2).
- **With the research tooling.** `docs/SCRIPT_DATABASE.md` and
  `docs/BUILTINS.md` (new). `docs/FRAGMENT_FORMAT.md`: the seven Part 1
  keys are database entries, no spelling is inferred.
  `docs/LEVEL_META.md`: "Terrain placement". `docs/FORMATS_MISC.md`: the
  detail mesh markers and where the terrain GLB's placement is.
  `docs/KAPOW_NAZ_FORMAT.md` and `docs/ENGINE_CONSTANTS.md`: the Xbox 360
  Part 1 addresses resolve with `default.pe` read as a memory image (file
  offset = RVA), not through its section table. The lifted script corpus
  is not part of the toolkit; the docs say where it is kept.
- **Models, textures, renderer.** `docs/KAPOW_NAZ_FORMAT.md`: the texture
  slot / engine layer table with the defaults of an absent slot, the
  descriptor's `usage` and `x360Size` fields, the animation block, the cube
  face order from code, part-local vertices, the shadow-hull group id and
  the pivot-book index, the standalone file preamble. `docs/ENGINE_CONSTANTS.md`
  (renderer): which flags cast a stencil shadow and which a shadow-map one,
  the pixel shader constants c13 / c16 / c17 / c28, render list 9, the
  occlusion test, culling boxes, the cube-map candidates, the gradient
  texture bytes, the start value of the grade options, and what the
  gameplay D3D9 captures confirmed (63 skinned draws equal `sheet.json` on
  every register their shader reads). `docs/LEVEL_META.md`: cube maps,
  renderer flags, culling boxes. `docs/FORMATS_MISC.md`: unit-weight
  particle surfaces. `README.md`: layer names, the MTL's glow and opacity
  lines, what Blender does with `Ns 0` and with `map_Ns` (it tags the
  roughness image sRGB), multi-part models.
- **Levels, AI, formats, script runtime, audio, physics, names: what a sweep
  of the open points read from the executable.** Each statement keeps the
  evidence word of its check (read from code, measured, inferred, not
  established).
  `docs/ENGINE_CONSTANTS.md`: the scene play mode; the `AIBrainNode` /
  Kynapse bridge (constructor against template values, what an entity sends
  to Kynapse, the occlusion and first-hit callbacks, faction filter, cache
  freshness in milliseconds); the property record and the native message
  hash; in "Script runtime" the `_root` frame, list `+`, the replication
  gate of set-by-hash, node enable, immediate `DeleteNode`, the savepoint
  residue, the game mode, what runs between the two native update lists,
  and `MasterSceneCtrl.StateActivateScene`; animated texture sheets; the
  jiggle joint's actor order and the kinematic anchor; ragdoll get-up, the
  character controller and `NxCharacter.dll`; frame-time globals and the
  sound system's limits; the console twins of the name hashers; restart and
  the outfit counts; the three texture names stored in different letter
  case (data: stored once per archive, what refers to them, the compare
  0x42536e).
  `docs/NAV_DATA.md`: the values the engine overrides at run time, AI sight,
  path-object flags, the mesh-link gate, the sector word and mesh +0x30,
  why the data lies 1.025 m up (inferred), the id join on all 39 levels.
  `docs/LEVEL_META.md`: `ai_sight`, `forced_state`, `hero_models`, block
  names, which level hosts which face class, the delay limit of 20 children,
  the simulated curtain, all eight terrains.
  `docs/SOUND_META.md`: "Engine rules" (speak blocking, senders, attack
  start, ragdoll contact, voice limits, listener, obstruction, zones, pitch,
  equalizer) and the music cue rule. `docs/TEXT_ASSETS.md`: the subtitle
  clock against a start delay, the playing leaf per build, the unreferenced
  waves and incomplete lines, the `.bik` header. `docs/RAGDOLL_RIG.md`:
  material combine modes and a "Cloth" section (descriptor, flags,
  attachments, the per-frame blend, the script rules).
  `docs/COMBAT_META.md`: `EnemyDef` members that are not tuning values,
  movement contact rules, three Xbox 360 notes. `docs/ANIMATION_META.md`:
  the four ragdoll values. `docs/KAPOW_NAZ_FORMAT.md`: the fingerprint
  display byte and CRC, five more loading rules, the archive key check on
  three archives. `docs/FRAGMENT_FORMAT.md`: key spelling, creation against
  property records, the unused tag-3 fallback, `netparticipant`.
  `docs/FORMATS_MISC.md`: the PS3 loop word, the Xbox 360 surface spawner.
  `docs/BUILTINS.md`: "Other builds". `docs/re/`: `wp4_ai.md` (forced-state
  order, the back-flip request, `DetermineForwardHeading`, four script
  defects, sight), `wp2_physics.md`, `physx_d6.md`, `wp5_runtime.md` (the
  button map), `enums.md` (the `AIBrainNode` constants).

- **Open-items register** (statements only; evidence
  level as given in each place). `docs/ENGINE_CONSTANTS.md`: the page rate's
  two lists, the rest pose added to constant tracks with the measured effect
  of the baker's rule, `DccJoint` on a wall hit and the master's heading
  constants, event cases 23 / 38 / 70 and the footstep block, the addon
  controller table (which CharVisual fragments have one, three Part 2
  platforms and PC Part 1), `DeleteOldPages`, the Underboss, a "Partner AI"
  section, "Gameplay cameras", run-time sheet changes, the property record.
  `docs/ANIMATION_META.md`: the layer's two lists, the master's heading and
  the wall correction during a pair, pair placement on PS3 and Xbox 360
  Part 2 (constants and hashes read from the executables), the parked
  `interact` marker and the stray key of `EN2_COM_DMG_wpn_1H_disarm_NTO`, the
  yaw sense checked on every character GLB of the six sets.
  `docs/COMBAT_META.md`: sweeps, bull rush, Underboss, achievements, partner
  AI. `docs/FX_META.md`: gameplay cameras, lens flare, the attachment
  transform rule in a true-frame GLB (measured on 14 attachers of 3
  characters), the fake Twilight Lady weapon (null in shipped data).
  `docs/PARTICLE_FORMAT.md`: the spread rotation order, seeds, five property
  meanings, what the writer skips. `docs/TEXT_ASSETS.md`: the `%N` parameter
  rule. `docs/RAGDOLL_RIG.md`: get-up failure and corpse settle, the native
  writers of the body mass, the hang test in Blender 5.2.2.
  `docs/SCRIPT_DATABASE.md`: the property record. `docs/LEVEL_META.md`: the
  three new keys. `docs/re/`: `events.md`, `events_table.json`, `sync.md`,
  `wp7_fx_camera_hud.md` corrected in place; five rows in the corrections
  index of `docs/re/README.md`.
- `README.md`: `char` and `bake` name their archive; Blender and the clip
  extras; what a Windows-native export was compared with (30 models and one
  character: equal except the PNG compression inside GLBs).

- **Measured figures in the documentation.** Statements of the kind "not
  run", "not measured", "not built" carry the figure measured on the
  six-set export where it has one: the model counts
  of PC Part 2 on one basis (743 names = 740 headers + 3 unit primitives;
  735 with mesh data; 738 outputs), `anim_meta.json` with all blocks
  (21.5 MB PC Part 2, 17.2 MB PC Part 1), the particle and
  subtitle figures of all six sets (`PARTICLE_FORMAT.md`, `TEXT_ASSETS.md`),
  the path-id join on Tutorial and PlayerVsPlayer (`NAV_DATA.md`), the
  texture comparison with the fixed normal-map decoder and vgmstream on
  the Xbox 360 sounds (`WATCHMEN_EXTRACTION_MASTER.md`), the script
  database and builtins table (`ENGINE_CONSTANTS.md`). README: the file
  counts under `extracted/` in the introduction (9,922 / 12,132), the
  origin of the PC Part 2 Bordello difference (a modified archive), the
  two jiggle figures marked as measured once, and what has and has not
  run on Windows ("Notes").
- **Research tooling outside the toolkit** (`tools/ghidra/README.md`,
  "Further tooling, 2026-10-06"; `docs/re/README.md`; `docs/INDEX.md` §8):
  a sweep of the gaps between the 19,233 dumped functions of the PC
  executable (16,309 more functions, 14,796 of them exception-handling
  funclets, and 28 registered command handlers with 156 registrations that
  the dump lacked; 21 functions re-bodied), a Ghidra language addition for
  the three Cell VMX instructions of the PS3 executable (`lvlx`, `stvlx`,
  `stvrx`; 207 functions completed) and a Ghidra language for the Xbox
  360 CPU (VMX128; 1,866 of the 2,049 functions that stopped at bad data
  now decompile). The files are research material, not part of the toolkit
  tree; the documents say what each establishes and what it does not. The
  28 handlers were already in `wlib/reg_dump.json` (the table is read from
  the registration calls, not from the function list), so no data table
  changes. `docs/ENGINE_CONSTANTS.md`: `0x87b96e`, the body behind 86
  registrations (35 of them `command_is_behavior_running`), writes 0 and
  returns (read from code); the quaternion tolerance at 0xd91bf8 is 0.0
  (inferred, not read in a debugger); the PS3 vector idioms.
  `docs/RAGDOLL_RIG.md` lists the captured knock-downs; `TEXT_ASSETS.md`
  says what the language-override question still needs.

### Tests

- `test_s5_code_findings.py` (38) and `test_text_layout.py` (20), synthetic
  fixtures only: the animation type rule and the two computed flags, the
  editor argument table, the twist pairs and the alignment, the twist pass
  as the default of `bake` in the engine gauge, a track bound by exact name
  and by prefix, the track lookup of the character export by part, of
  `watchmenlib.bake` by archive and of the contact check, a cached bake of
  the other lookup, a level
  with waypoints, culling groups with their cube maps per area, stream blocks, a swinging prop, lights, a
  camera tour with its sequence, use triggers and sound actions, PVS-root
  visibility, `parentLink` 1, SubPivot overrides, a stored sheet id 0, the
  terrain keys; strips, the cloth rule, a typed fragment stream, local
  default packages, music one-shots; the 16 wrap cases, placement, `%N`
  and the three tables. `test_formats_v2.py`: console format 10 joint order
  and the strip reading of the `ix == 0` submesh. `test_audio_v2.py`: a one-track stream ends at its
  stored position. Fixtures of `test_combat_meta.py`,
  `test_anim_meta_v2.py`, `test_p6_level_renderer.py` and
  `test_s4_review_fixes.py` follow the computed animation type, PVS-root
  visibility and the composed `parentLink`.
- `test_s6_findings.py` (13), synthetic fixtures only: the layer fields of a
  state's clip rows and `layer_use`; `rules.partner_ai.waypoint_move`, the
  kill-target defect and the Underboss movement, flee and flamethrower
  blocks; the exploration camera collision block; terrain, colouring,
  detail-mesh and font JSON with the loader's names, a JSON with only the
  names and one with only the offset-style keys building the same bytes;
  the pivot-book header in both byte orders and both record layouts; the
  model header's `skinned_bone_count`, `hidden`, `from_cloth` /
  `cloth_submesh`; a texture slot's `usage`. `test_p8_canonical_names.py`:
  the `--names stored` assertions compare without regard to case on a file
  system that folds case. `test_p6_level_renderer.py`, `test_p6_combat.py`,
  `test_p6_audio.py`, `test_p6_fx_tools.py`, `test_p6_anim.py` and
  `test_p3_raw_formats.py` follow the evidence text of `cube_maps`, the
  `not_established` lists, the `bit3` list, the table revision and the
  named fields.

- `test_s2_jiggle_determinism` (16: the `exact_math` functions against the C
  library and pinned digest by digest, the solver bake pinned on four
  synthetic clips, the solver run with every platform-dependent call
  forbidden, the last-bit sensitivity and its cause), `test_s2_fragment_scan`
  (4: the node-type scan against the per-offset scan on 3,000 random buffers
  in both byte orders, linear time), `test_s2_tree_glob` (8: `glob_tree`
  against `glob` with and without the cache), `test_s2_mean_fsum` (3),
  `test_s2_sound_event_lists` (3), `test_s2_path_objects_unbound` (5),
  `test_s2_file_handles` (7: no `open()` outside a `with` in the toolkit's
  code).
- Five new files, 128 tests, synthetic fixtures only: `test_jiggle_solver.py`
  (18), `test_jiggle_default.py` (20), `test_vcolor.py` (20),
  `test_face_rule.py` (46), `test_texture_lookup.py` (24). Run against the 1.3.0 code, all 24 of `test_texture_lookup`
  and all 20 of `test_vcolor` fail, `test_face_rule` cannot be imported, and
  35 of the 38 jiggle tests fail; the other three are the comparisons with older output described below.
- Three more files, 39 tests, synthetic fixtures only:
  `test_texture_sheets.py` (15), `test_parts_and_face2.py` (17),
  `test_outfits_integration.py` (7). All three files fail at import against the code without these features.
- Four more files, 68 tests: `test_materials_v2.py` (21),
  `test_ragdoll_rig.py` (18), `test_audio_v2.py` (25),
  `test_wave2_integration.py` (4).
- Seven more files, 143 tests, synthetic fixtures only:
  `test_combat_meta.py` (22: rendered criteria and group chain, the attack
  block with damage and its sources, timings taken from the event records,
  counter window, whiff distance, combo speed-up, damage-pose conversions,
  reaction rows, CharacterDef → class link, combo step overrides, pair
  triggers, and that a failing combat build leaves the table intact),
  `test_fx_meta.py` (19: the damage-effect rule, the cut camera against the
  engine constants, event payload and stale slots, state and pair `fx` on
  their clocks, the effect table, attachments, the `fxmeta` command),
  `test_level_meta.py` (20: fragment header, the engine's reference
  resolution, `.scene`, world transforms, the level sections, the save
  reader), `test_text_assets.py` (13: `textRes` in both byte orders, the
  subtitle key and time grammar, `extract` writing every language with
  nothing else changing, `text`, `textmeta`), `test_particle_asset.py` (13:
  the grammar in both byte orders and both record layouts, defaults, enums,
  gradients, unknown records kept, byte-exact rebuild, the fallback),
  `test_particlemeta.py` (10: which files are walked and in which order,
  the per-file JSON equal to the extractor's, the index rows with enum
  names, defaults and the UV grid, textures and models found by asset path
  in another case and never outside the tree, the untyped layout, a broken
  file reported and still written, determinism, the command and its exit
  codes),
  `test_nav_data.py` (35: both formats field by field, the mesh versions,
  truncation, triangulation against the parity test, `locate`, the document
  in engine space, the GLB, the command) and `test_feature_seams.py` (21:
  the cached table needs every block marker; the combat and effects blocks
  share the table without a common key and with those keys removed the table
  is the plain one; the camera cuts and the trigger in a clip's GLB extras;
  the effects block reading particles through the grammar in both byte
  orders; the grade node's owner; `extract` writing `nav/`, `--no-nav`, no
  empty folder; the path-object join) `test_realdata_r5.py` (2: the
  whip found when the reference's folder case differs from the extract's)
  and `test_fullextract.py` (3: type records at the head of a fragment keep
  their `created` entries, bare records in front of a `Class(Native)` record
  still go to the schema only, the text index names a block the same way
  from an archive and from a `files` tree).
  None of these files passes against the code without its feature: five cannot be
  imported there, `test_fx_meta` and `test_text_assets` fail test by test.
- `test_frame.py` (50, synthetic): the reflection rules (quaternion and
  matrix conjugation, the tangent sign derived from the glTF bitangent,
  yaw); `reflect_gltf` on every accessor role, row by row, its bounds, its
  refusals (sparse, strips, an accessor in two roles) and that it is an
  involution; a model GLB in both frames (exact reflection, file order in
  the true frame, the counter-clockwise triangle normal on the side of the
  vertex normals in both, the minority winding, primitives without
  normals); **the invariant**: for a character with attributes, a weapon, a
  hidden alternative, two outfits sharing data, the face skin with baked
  face channels and the ragdoll helpers, the skinned positions of every mesh
  node computed from the file's own nodes, inverse binds and channels are
  the reflection of the mirrored file's, in the bind pose and at every key
  of every animation, and every node matrix is S M S with a positive
  determinant; the classic skinning checks against the engine input in the
  default frame; clip extras; the placement formula on reflected clips;
  table conversion both ways; the ragdoll frames, axes and limits (a turn
  about the twist axis keeps its sign, swings change theirs), helpers from
  the reflected rig, the sidecar; the level transform (a GLB placed with
  `gltf` lands on the reflected engine position) and the level file; the
  navigation GLB and JSON; OBJ; the camera rule; the marker; the option on
  each of the eleven commands, its refusal elsewhere, the resumed export.
  The mirrored frame is tested not to enter the reflection at all.
- `test_review_r6.py` (19, synthetic), on the frame rules: the sense of a yaw number derived from an engine
  quaternion (minus the right-handed yaw of the GLB rotation, in both
  frames), the pair offset of a turned master against the engine's vector
  rotation for four angles, the `conventions.yaw` text; a character part
  without normals keeps the file's triangle order in both frames and one
  with normals is reversed against the mirrored file; the OBJ's `vn` lines
  are reflected (on normals with an x component); `reflect_gltf` swaps the bounds of rotation and matrix accessors,
  refuses a `min` without a `max` or of the wrong length, rewrites two
  accessors on the same bytes once, and refuses accessors that overlap at
  different offsets or lengths and an unreflected accessor on reflected
  bytes; `frame.vec`. Each fails with its rule removed: the pre-reversal of normal-less parts,
  the `vn` negation, the accessor rules of `frame.py`, the yaw sense of
  `anim_meta.py`.
  `test_placement_offset_is_in_the_master_nodes_frame` pinned the old sense
  of the turned-master offset and now expects the engine's.
- `test_materials_no_highlight.py` (14, synthetic): a sheet without a
  highlight gives roughness 1.0 and no roughness texture, with and without
  a specSize layer, and so does a black specular layer; a cube reflection
  keeps the sheet's roughness; a weak highlight (`specularPower` 1e-4,
  0.002, 0.05) is exactly what it was, by formula and by pinned values;
  emission and the sheet values of such a material are unchanged; the
  character GLB and `extract --glb` (no roughness image embedded); the MTL
  (`Ns 0`, no `roughnessEngine.png`; the bake stays for a highlight and for
  a cube reflection); `--materials legacy` unchanged in all three writers.
  Nine of the fourteen fail on the code without the rule.
- Engine rules, six files, 147 tests, synthetic fixtures only:
  - `test_p1_combat.py` (18): the throw pair's damage source and release
    speed, the ragdoll rule with the CharacterVisualDef numbers, the contact
    cap, the receiving side, the three area attacks, new constants with
    addresses, the settled rules, the effective damage modifier, event rows
    29–31, and that per-state numbers and the other pair rules do not
    change.
  - `test_p1_level.py` (23): the model picker (priority 0, last of two
    matches, unmatched priority, single unnamed member, empty collection),
    definition members and weapon collections, placement `variant` /
    `weapon` / `ai_start`, exact trigger class match, combat presets, group
    zone trigger and return position, cube maps, movie subtitle table and
    continue link, the path-object id join (id, null entry by position, id
    kept against position, no ids), the nav stamp summary.
  - `test_p1_anim.py` (32): first-child blend weights, random idle entry and
    its loop rule, the stun-hit follow-up, a turned master's placement and
    drift, the contact check with GamePivot rotation, the cut camera's
    fallback / kept position / side height, HalfBell and blend time,
    partner-side cuts.
  - `test_p1_formats.py` (39): sequence loop mode, `hosts_up`, target kinds,
    linear rules and `play_position`; surface keys, area weight, mesh-node
    tails and the model sidecar; block header fields, asset types, inflate
    by type with the failure report, the trailing blob; `.naz` keys;
    language codes and `--language` names; subtitle key edge cases,
    `shown_from`, the `movies` section and the rules;
    `CHARACTER_BONE_TYPES`; reg_dump dispatch kinds.
  - `test_p1_materials.py` (26): the alpha-mode rule in both GLB writers and
    the legacy rule beside it, the header alpha flag and its pixel fallback,
    `sheet_blend` for a faded Standard sheet, the grade formula, platform
    adjustment and new node keys.
  - `test_p1_integration.py` (9): a cached table without the current
    revision is rebuilt; the format markers stay; every registered name is
    spelt as registered in the dictionary (outside the three kept names),
    respelling the shipped dictionary changes no byte, `build_prop_dict`
    prefers the registered spelling, `is3D` only for Sprite, and the readers
    of fragment nodes do not depend on letter case.
  - Existing tests edited because a pinned value legitimately changed:
    `test_fx_meta.py` (`look_at_joint` of a root cut is `null`, the
    slow-motion records have three more keys, a fixture key spelt
    `duration`), `test_materials_v2.py` (hair with vertex alpha is `MASK`),
    `test_texture_sheets.py` (`sheet_blend` has `cause`), `test_vcolor.py`
    (the new rule, and `legacy=True` for the old one),
    `test_feature_seams.py` (`nav.method`; the cached-table fixture carries
    `revision`), `test_frame.py` and `test_wave2_integration.py` (the same
    fixture), `test_followup.py` (`--language uk` is valid now),
    `test_names.py` (three more command keys), `test_ragdoll_rig.py`
    (`mass`, `movementType`).
  - Twenty existing tests compare a written file with their synthetic engine
  input (in `test_anim_meta`, `test_feature_seams`, `test_followup`,
  `test_glb_skinning`, `test_level_meta`, `test_nav_data`,
  `test_ragdoll_rig`, `test_vcolor`, `test_wave2_integration`). They now
  ask for the mirrored frame through the `engine_frame` fixture of
  `conftest.py` and are otherwise unchanged; `test_frame.py` holds the same
  checks for the true frame.
- Three tests pin `pinned` and `pivot` to their old output.
  `test_model_pinned_matches_frozen_1_3_0_values` holds rows that 1.3.0
  baked by default and always runs (tolerance 1e-6; it passes on the 1.3.0
  code too). Two compare bytes with another source tree and are **skipped
  when that tree is absent**: one in `test_jiggle_solver` needs a 1.3.0 tree
  (`$WATCHMEN_TK130`, or `../tk130` next to the checkout); one in
  `test_jiggle_default` needs a development snapshot from before the default
  moved to `solver` (`$WATCHMEN_TK140`, or `../tk140`), which was never
  released. A checkout on its own therefore skips those two (2 skipped, see the final
  count below); all passing needs both trees beside it.
- `test_jiggle_solver` holds a frozen numpy transcription of the reference
  integrator; `SoftLimitJoint` agrees with it to 1e-9 over 240 steps.
- `test_wave2_integration.py`: its cached-table fixture now carries the
  combat and effects markers (a table without them is rebuilt, which is what
  `test_feature_seams` pins).
- Existing tests edited where a change invalidated what they pinned, in four
  files: `test_followup.py` and `test_formats_v2.py` (tangent w is −s, with
  the old sign checked under `green_up=False`; COLOR_0 is linear float; the
  default jiggle cache directory is the solver's), `test_phys_v2.py` and
  `test_v120_regressions.py` (they name `pinned` where they test the 1.2.0
  model, and the default-model test asserts `solver`).
- Real-data validation, read-only.
  - *Full export*, Part 2 PC, defaults: 26 GLBs and `anim_meta.json` (11.7
    MB), 959.6 MB. glTF-validator 2.0: 0 errors on 26 of 26 (warnings
    `NODE_SKINNED_MESH_NON_ROOT`, `ACCESSOR_JOINTS_USED_ZERO_WEIGHT`).
    Compared with an export of the same game made with `pinned` jiggle,
    name-based faces and by-name textures: every sampler of every body bone
    other than the jiggle bones and the face joints byte-equal in all 26;
    skin 0 (joint names, inverse bind matrices, rest pose) identical in 26;
    the jiggle channels that differ are `JiggleBelly` (Gimp skeleton),
    `BreastL` and `BreastR` (female skeletons) and nothing else; 10 GLBs
    gain a face rig; 371 embedded diffuse images each matched by bytes to
    the folder the variant's own models name, 0 from a wrong folder.
    Rendered and looked at: all 13 head types sit on their necks with no
    doubled head; Rorschach's mask shows black blots on white from every
    side.
  - *Switches*: the same export with `--jiggle-model pinned --face-rule
    legacy`, 20 GLBs compared (see "What the three switches together
    restore").
  - *`extract --glb`* on all 735 Part 2 PC models with a stream (with the
    textures found by name): structural checks on every GLB (accessor
    counts, bounds, unit normals and tangents, w = ±1, COLOR_0 in 0..1,
    indices, winding against normals) 0 problems; glTF-validator 0 errors.
    Console and Part 1: the first 400 models each of X360 Part 2, PS3 Part 2
    and PC Part 1; that sample holds few skinned models (8, 8 and 6 GLBs).
  - *Jiggle*: 9 real baked clips, `pinned` and `pivot` byte-identical to
    1.3.0; 23 real clips (36 bone tracks) byte-identical to a development
    build that had passed that comparison; two in-game captures.
  - *Render test*: three.js r160 and Blender 5.0.1 against a numpy
    rasteriser with the pixel shader's math; no real game frame was used as
    reference.
  - *Combat block*, Part 2 PC: with the added keys removed the table equals
    the one exported without the block; every one of the 336 attack states has a block
    (4 without damage, each with the reason); the Dominatrix numbers and 12
    states of the other classes agree with an independent read of the
    fragments and the lifted script.
  - *Effects block*, Part 2 PC: with the added keys removed the table is
    byte-identical to the one exported without the block (12,380,171 bytes); 259 camera
    cuts and 1,328 events of the census reproduced; three moves walked
    through event by event.
  - *Levels*: Part 2 PC 6 levels and Part 1 PC 7 levels, 0 unresolved
    references; the fragment parser old against new on 907 + 759 files
    (instance records and properties identical, all lossless);
    `anim_meta.json` byte-identical for both parts with the new reference
    resolution; the Bordello main hall assembled from `Bordello.level.json`
    (73 model instances close into a ring, ten enemies 0.000 m above their
    floor); both save files of a real profile.
  - *Text*: all six sets (Parts 1 and 2; PC, X360, PS3), 15 assets × 6 slots
    each, 0 bytes left in every table; a full `extract` of four Part 2 PC
    block pairs old against new: 5,439 files byte-identical, 226 new, all
    under `text/` (the complete `game.naz`: see the full extract below).
  - *Particles*: 746 files of seven extracts, 0 unknown classes, properties
    or trailing bytes, byte-exact rebuild; all 208 Part 2 texture references
    exist. `fx_meta.particle_facts` through the new parser against the
    generic walk: equal on the 49 Part 2 PC files checked.
  - *Navigation*: 11 `.hpd` and 17 `.aipathdata` files, 0 undecoded bytes;
    stored edge lengths equal `floor(16 × length)` for all 17,534 edges; the
    triangulation against the engine's parity test on 8,080 random points, 0
    disagreements; character placements on the mesh: Bordello 165 of 167,
    NightClub 165 of 168, StreetsOfRiot 141 of 143 (the rest 0.03 to 1.7 m
    outside its edge); an overlay on four Bordello room models (floor 1.05 m
    below the mesh).
  - *Path objects against level nodes* (on copies of the
    Part 2 PC fragments and `.hpd` files): Bordello 62 of 62, NightClub 48 of
    48, StreetsOfRiot 18 of 18 linked; 126 within 0.00002 m, two within
    0.16 m; the next-nearest node at least 3.9 m away. On the PC data
    Tutorial (2 of 2) and PlayerVsPlayer (1 of 1) link as well: 131 of 131.
    By id (the staged fragments): Bordello 61 by id + 1 by
    position (list entry 45 is null), NightClub 48, StreetsOfRiot 18; no id /
    position disagreement. On the PC extract Tutorial (2) and PlayerVsPlayer
    (1) join by id too: 130 by id + 1 by position.
  - *Full extract* (`extract game.naz OUT --glb --vgmstream-cli …`, Part 2
    PC, all features together; 2026-10-04, Python 3.10 in a Linux VM writing
    to the Windows disk). The shell there ends every call after 180 s, so
    the command ran in 24 resumable pieces through a driver that calls
    `watchmen.py extract` unchanged and answers the calls an earlier piece
    completed from a log. Result: 8,711 assets of 12 blocks; 21,560 files,
    4.06 GB — `files/` 57, `extracted/` 9,906, `textures/` 5,416 (1,401
    textures), `models/` 2,952 (984 model records, 978 decoded, 738 names:
    OBJ, MTL, GLB and `.model.json` each), `audio/` 2,988 (3,211 sound records,
    2,921 names; 53 music tracks of 13 streams), `text/` 226, `nav/` 10, `skeletons/` 5.
    - Every JSON, texture and model file was written a second time straight
      from the archive, without the driver, and is byte-identical: 1,203
      JSON, 4,764 texture files (the 652 `roughnessEngine.png` come with the
      models), 2,952 model files; so are the music tracks, sidecars and
      `sound_info.json` (67), `text/` (226), `skeletons/` (5) and `nav/`
      (10) from one plain run.
    - `text/` and `nav/` as `extract` writes them equal what `text` and
      `navmeta` write (236 files).
    - glTF-validator 2.0.0-dev.3.10 on all 738 GLBs (1.16 GB, 2,388
      primitives, 92 skinned): 0 errors, 92 warnings
      (`NODE_SKINNED_MESH_NON_ROOT`, one per skinned model), 1 info
      (`IMAGE_NPOT_DIMENSIONS`).
    - Against the 1.3.0 code run on the same archive, every difference is
      one this entry describes: 565 normal maps with X and Y exchanged and
      nothing else changed in them, the other 3,260 texture files
      byte-identical, 939 `sheet.json` and 652 `roughnessEngine.png` new;
      737 of 738 OBJ byte-identical (`Large_Head_2`: the `__2` material),
      738 GLB and 738 `.model.json` new, the MTLs as listed under
      "Textures are resolved by the path the model stores"; 906 fragment
      JSON (the `header`; 110 with newly typed nodes; three `Enemies`
      fragments with `m_ezonetrigger`), 89 particle JSON, 3 `.pb` JSON (key
      names); the 194 sequence, 3 grass, 5 detail-mesh and 3 terrain JSON
      byte-identical. Of the 2,921 sound files of an extract made in July,
      2,845 are byte-identical and 76 differ as described under "35 stereo
      sounds…"; the 3 one-track music streams end 704 / 832 / 704 samples earlier, 10 change
      and 40 track files are new.
    - `particlemeta`, `navmeta`, `text`, `textmeta` and `levelmeta` on that
      tree give the files made from an older extract (89 particle
      JSON, 10 navigation files, 226 text files — `text/index.json` once
      the block name is spelled alike, see "Fixed" —, `text_meta.json`, 5 of
      6 level files). `Bordello.level.json` differs because the archive on
      that machine is not the one the older extract was made from: one
      entry, `bordello.block_h_z`, differs in 53,255 bytes, and 59 character
      placements have another character type (the archive is a modified
      copy: Gimps replaced by Dominatrices).
    - Two models, `Rubble_Rooftop_02` and `Rubble_RoofTop_03`, are stored
      under two spellings that differ in letter case (their bytes are the
      same in all five blocks); that extract wrote the last spelling into a
      file named with the first. See "Fixed".
  - *Materials without a highlight*: the character export and the model
    files were written with and without the rule and compared, see
    "Materials follow the game's shader". The full extract described above
    is one without the rule: of its files, the 165 model GLBs and 165 MTLs
    named there differ, and an extract with the rule bakes no
    `roughnessEngine.png` for a texture without a highlight
    (measured on the six-set export, PC Part 2: of the 652 textures the 738
    MTL files name, 91 have no highlight — `Ns 0`, no `roughnessEngine.png`
    — and 561 are baked; 561 `roughnessEngine.png` per Part 2 set, 601 per
    Part 1 set).
  - *Coordinate frame* (the items above it were run on the engine's numbers):
    see the first item of "Behaviour changes" for
    what was compared. Blender 5.0.1 (the `bpy` module, not an interactive
    session) imported the true-frame sign and character GLBs.
  - Not run or not checkable: hair; the look of the dash cycles and of looping jiggle against the game
    (no capture). The full `characters` export was
    run with both blocks (26 GLBs: binary chunks and ragdoll files
    byte-identical to the export without the blocks, only keys added, `anim_meta.json` 17.8 MB, glTF-validator 0 errors). Not run: a
    Blender import of either full output. (The six-set export under "Six-set export" below is a Windows run of `extract`, `characters`, `faces`,
    `levelmeta`, `textmeta`, `fxmeta`, `particlemeta` and `grademeta` on
    all six sets; what has and has not run on Windows is in the README,
    "Notes".)
  - *Engine rules on staged data* (copies of Part 2 PC fragments, clips
    and blocks and on the nine staged blocks of both parts and three
    platforms): the
    numbers given with each item above were reproduced there. Besides those:
    336 attack states and the 413 pair rules, per-state `combat`
    blocks identical to the table made without these rules; `placement` of all
    407 placed pairs unchanged; `sound_meta.json` unchanged apart from three
    convention texts and one fewer open point; the 49 staged `.particle.json`
    and the particle index byte-identical; both save files decode to the
    same JSON; of 22 staged ragdoll files two change, by one key
    (`cloths[].properties.movementtype` → `movementType`, Nite Owl's two models).
  - *Engine rules on the PC data* (the Part 2 PC extract and
    `game.naz`; Python 3.10 in a Linux VM): `characters` (26 GLBs),
    `levelmeta`, `text`, `textmeta`, `navmeta`, `fxmeta`, `grademeta` and
    `particlemeta` were run with all defaults, and the model outputs of all
    984 model records were regenerated from the archive. Every difference
    from the outputs made without these rules was classified; none is
    unexplained.
    - Character GLBs: every geometry accessor and both skins' inverse bind
      matrices of all 26 files byte-identical; of 734,120 animation channels
      the 28,603 that differ are face-joint channels of the 161 clips named
      under "Faces" (idle entry); no material and no image differs; the
      JSON differs only in the keys this entry lists (face schedule,
      `clip_mix`, camera cuts and returns of four pairs, `look_at_joint` /
      `look_at_point`, contact check, throw `damage`, `anchor_frame`, three
      convention texts). glTF-validator 2.0.0-dev.3.10: 0 errors.
      `--frame mirrored` on two characters (Heavy, Twilight Lady): every
      accessor is byte for byte the reflection of the true-frame file, and
      the differences from a mirrored export without these rules are the same
      channels and keys.
    - `anim_meta.json`: contact check 198 / 28 / 14 on the primary pairs;
      the 10 throw pairs have `damage.source` `ragdoll_contact`; 122 pairs
      with camera cuts (65 primary), 789 pair cuts; `clip_mix` on 159 state
      track segments and 2 class states; `look_at_joint` null on 4 state and
      16 pair cuts. A second, mirrored build of the table differs from it
      only by the frame rule.
    - Ragdoll files: 4 of 26 change, by the one key
      `cloths[].properties.movementtype` → `movementType` (6 cloth blocks:
      one in each Nite Owl file, two in each Rorschach file).
    - Levels, all six: the totals given above (variants 26 / 462, weapons
      113 / 34 / 341, path objects 130 by id + 1 by position);
      SET_AI_STATE 105 / 79 / 43, FORCE_MOVE 29 / 4 / 1, PASSIVE 41 / 70 /
      44, groups 56 / 43 / 42 with 4 / 2 / 16 zone triggers and a changed
      `return_position` on every group, preset switches 16 / 8 / 8 (Bordello
      / NightClub / StreetsOfRiot); 0 unresolved references. Against the
      level files made without these rules only keys are added, besides
      `groups[].return_position`, `counts.references_resolved` and six rule
      and evidence texts.
    - Text: `text_meta.json` has 16 movie players, 9 with a table, 94
      distinct rows (99 counted per player: two players share
      `Cutscene08a`), one delayed row (`Cutscene08B`); of the 226 `text/`
      files 76 change, by the added `engine_code` only.
    - `fx_meta.json` and `grade_meta.json` differ from the tables made
      without these rules by the listed keys only; the 89 particle JSON
      files and their index are byte-identical; the five `.nav.glb` are
      byte-identical and each `.nav.json` gains `summary.generated` and two
      evidence texts.
    - Archive and blocks (`game.naz`, 7 blocks): 57 entries with 57 distinct
      keys, none stored with a compression method; version signature
      0x79D3E0DA, `unknown_328` `0a883f59`, `low_violence` false and an
      empty trailer on all seven; 8,693 header blobs and 2,391 stream blobs
      inflate, the 18 `mediastream` headers are raw, none fails (2,161 / 7
      / 444 on the main, MainMenu, PlayerVsPlayer and Tutorial blocks); the
      three `.font` records are named and no record has an unnamed type; 29
      particle surfaces in 19 of 740 model records, 27 area-weighted; of the
      271 `.sequence` records 7 are `pingpong` (three of the main menu, four
      Huey sequences of StreetsOfRiot), the rest `loop` or `oneshot`.
    - Models: of the 738 model outputs 40 GLBs and 19 `.model.json` differ
      from those made without these rules, no `.obj` and no `.mtl`. Geometry and
      skins of the 40 are byte-identical. Three materials are no longer
      `BLEND` (the three named under "Materials follow the game's shader":
      the `BLEND` copy of `Ground_Marble_Tiles_01` is gone from two Twilight
      Mansion models, `ground_autumnleaves_01` is opaque and marked); 49
      materials in the other 37 GLBs gain `extras.watchmen.vertex_alpha` and
      nothing else; the 19
      sidecars gain `particle_surfaces`. A sample of 191 of the regenerated
      GLBs (every changed one among them) validates with 0 errors and the
      same 17 warnings as without them.
    Not run: `Interpreter.slot_weights()` of the four body states on the
    PC data (no exported file carries it). (A full extract, the Part 1
    colouring records and the console and Part 1 outputs are in the six-set
    export below.)
- **Parts 1 and 2 on all platforms:** eight new files, 155 tests, synthetic only; the
  big-endian and older-layout fixtures are built in the tests.
  `test_p2_console_chars.py` (21: header byte order, the tie that lost
  parts, planar pieces, the big-endian rig and pivot book, the reasons for a
  missing rig, the bind check, the `not_decoded` marker), `test_p2_audio.py`
  (20: PS3 and Xbox 360 sound headers, the XMA2 cut, durations in
  `sound_meta` and `text_meta`, console `sound_info.json`),
  `test_p2_part1.py` (33: stream sets, stream-only blocks, both record
  layouts, sheets, the model bag and LODs), `test_p2_fragment.py` (21:
  sections against `nodes_full` in both byte orders and across chunk
  boundaries, refused guesses, the Part 1 keys), `test_p2_x360_textures.py`
  (16: the console header, DXT3A, cube maps on the three platforms,
  warnings and `decodeWarnings`), `test_p2_small.py` (23) and
  `test_p2_small_integration.py` (7: one output per name, the summary,
  loose-folder nav, `stable_uid`, the skeleton scan, cache keys, the
  recorded build failure), `test_p2_integration.py` (14: one byte-order
  test for every standalone reader, the 64-bit value, the ragdoll material
  from either record layout, the fragment order tie, one "no stream" line
  per asset). No existing test was edited.
- **Raw formats, Part 1 header, console models, reporting:** four files,
  93 tests, synthetic only.
  `test_p3_raw_formats.py` (34: font, terrain header and stream, the
  height field and the GLB in both frames, the colouring map, the detail
  mesh tail, the scene summary, two `extract` runs on a built block),
  `test_p3_part1_model.py` (43: both header layouts in both byte orders,
  untyped property records, the Part 1 rig equal to the Part 2 one, the
  console stream sizes, console against PC vertex for vertex, the colour
  order that is not guessed, the scan switch), `test_p3_reporting.py` (15:
  the markers `undecoded` reads, the per-kind summary that counts a repeated asset once, the raw-only count,
  the `glb` and `submeshes` markers, the summary lines, `inferred_names`,
  the block order). `test_p3_batch.py` (1: the reason text of the
  character `not_decoded` marker); one assertion of `test_p2_console_chars.py` follows the reason text.
- **Script database, builtins, terrain placement:** four files, 33 tests, synthetic only.
  `test_p3t_script_database.py` (14) and `test_p3t_builtins.py` (9);
  `test_p4_scriptdb_cli.py` (6: the `scriptdb` command, its usage line and
  argument errors, `--find` reaching the reader and taking several values, a key of eight hex digits
  read as a hash first and as a name second); `test_p4_level_terrain.py`
  (4: `files.terrain` — the composed transform and not `localPos`, `gltf`
  in both frames, a level without terrain). In existing files:
  `test_p3_reporting.py` has 16 tests (the three on `inferred_names` now
  pin that no Part 1 name is marked and that the mechanism still works for
  a name put into the table; one added), and `test_p3_raw_formats.py`
  pins the detail mesh markers and the stride fields in its three detail
  mesh tests.
- **Models, textures, materials, level flags:** four files, 71 tests,
  synthetic only. `test_p6_models.py` (16: the part transform and its
  quaternion convention, parent chains and loops, OBJ / mesh / GLB of a
  model with moved and rotated parts, a skinned buffer left alone, the
  `parts` sidecar, `weight_is_unit` and the area tolerance, the standalone
  preamble, two standalone pairs with one name), `test_p6_textures.py` (16:
  the slot tables, labels by slot and the format rule without one, the PC
  carve names, the animation block and `frame_ms`, `cubeFaceOrder`),
  `test_p6_materials.py` (33: opacity by render type — a sky sheet with
  opacity 0 and 0.25, a sprite sheet, the types that keep their mode —, the
  sheet values in
  `extras`, the grade option default, the MTL's `d` / `Ke` / `map_Ke` /
  comment, emissive in the GLB with and without `selfIlluminance`, seven
  sheets with the constants the gameplay captures show) and
  `test_p6_level_renderer.py` (6: cube candidates up the tree, the nearest candidate
  per placement and ties, `opacity` / `cast_shadow`, culling boxes). Three
  existing tests follow the new layer names and sidecar keys.
- **Models, textures, materials, level flags on the game files** (the six
  exported sets, read-only).
  *Part transforms:* every model with a moved render part decoded to OBJ
  and GLB, 47 per Part 2 set and 37 per Part 1 set (252 models): every
  vertex inside the model box on 252 of 252, OBJ and GLB extents equal on
  252 of 252; GLB extents equal to the model box within 0.2 % on 42 and 32
  per set — the other five have a rotated part, where the model box is the
  box of the rotated submesh boxes. *Old against new on PC Part 2*, all 740
  models decoded with both trees: 688 of 735 OBJ files identical, 47 differ
  (the moved models); 131 MTL files differ (134 with the `d` line of the
  three sky sheets); GLB geometry differs on the same
  47, the embedded images on 47 (the models that wear a relabelled texture)
  and a material value on 33 (26 roughness or specular, 7 emissive
  strength).
  *Layer names:* the file names both trees give the layers of all 937 and
  1,206 textures of each of the six sets (pixel decoding stubbed out): 25
  folders change names per Part 2 set, 47 per
  Part 1 set, the same textures on the three platforms, no error.
  *Standalone files:* 36 of 36 `_h_z` preambles name a known build, 30 of
  30 `_s_z` files have none. *Levels:* the six PC Part 2 levels rebuilt:
  10,656 model placements and 152 cube nodes equal to the exported ones
  apart from the new fields; 152 of 152 cube nodes are candidates at load,
  853 placements store an opacity below 1, 53 do not cast, 233 culling
  boxes. *Sheet values:* the `sheet.json` of ten textures drawn in the
  gameplay captures equals the captured shader constants (10 of 10). The six-set export gives the
  same counts on every set ("Six-set export" below). Not run: Blender.
- **Raw formats, Part 1 header, console models, on the game files**
  (read-only): the readers over every `.font`, `.scene`, `.terrain`,
  `.terraincoloringasset`, `.detailmesh` and model of the six exported
  sets (the numbers in the items above); `decode_model` end to end on all
  735 PC Part 2 models (`.model.json`, OBJ and MTL byte-identical to the
  export, 105 sampled GLBs too). `extract --glb` of the
  MainMenu and WatchMen blocks of PC Part 1: 24 of 24 models with a GLB (4
  without the Part 1 header reader), 3 fonts and the scene written, `not
  decoded completely: none`, no `WARNING:` line; 3,268 other files
  byte-identical to the output without these items, and `levelmeta` output
  identical.
- **Parts 1 and 2 on all platforms, on single blocks** (the six exported sets, read-only,
  on the machine that holds them; the readers were run over every affected
  header, see the numbers under "Fixed"). `extract --glb` of the MainMenu
  block of PC, Xbox 360 and PS3 Part 2 and of PC Part 1. PC Part 2 against
  the output without these items: 568 files, of which the 12 fragment JSON
  and 5 cube faces differ and nothing else; the logs are identical. Both
  consoles: no `WARNING:` line, the 12 fragment JSON byte-identical to PC, 6
  of 6 sounds with a header length. PC Part 1: 35 of 35 `sheet.json`, 9 of 9
  `.model.json`, the MTL files take their specular values from the sheets.
  The Prison block of PC Part 1 (log only): 24 + 26 + 6 + 36 streams read
  from the four stream files. The Ragdoll sheet id and material on all six
  sets, the rig of the five skeleton models of both Part 2 consoles equal
  to PC, the header byte order of 740 / 740 / 1,090 models.
- **Six-set export** (on Windows, `extract --glb`, `binds`,
  `characters`, `faces`, `levelmeta`, `textmeta`, `fxmeta`, `particlemeta`
  and `grademeta` on each of the six sets; PC Part 2 from the original
  `game.naz`). 54 steps, every exit code 0, no `WARNING:` line and no
  traceback in any step log (the suite step was not run: pytest is not
  installed under the batch's Python); every extract log ends with `not decoded
  completely: none`, and the character step finishes in one pass on every
  set. `note:` lines (expected absences) per set: 6 on each Part 2 set, 7 on
  PC and PS3 Part 1, 8 on Xbox 360 Part 1. Files outside the `_bake`
  caches: 21,686 per Part 2 set, 27,820 on PC and Xbox 360 Part 1 and
  27,821 on PS3 Part 1; every GLB among them is structurally valid (790
  per Part 2 set, 1,193 per Part 1 set) and every JSON file parses (3,114
  and 3,795). The sky opacity (the `d` line of 8 MTL files and the alpha
  mode of 2 GLB materials per Part 1 set, the `d` line of 3 MTL files per
  Part 2 set) and the movies (12 `.bik` under `files/data/` in every set)
  are in it. A character GLB built on Linux from the export's `extracted/`
  files and animation table equals the Windows one in every mesh and
  animation accessor and in the pixels of every image and differs in the
  PNG compression and in the last digits of node rest transforms (26 GLBs
  of PC Part 2; the jiggle item under "Behaviour changes" has the rest).
  - *Models:* 738 `.glb` under `models/` in each Part 2 set and 1,088 in
    each Part 1 set (the three unit primitives included). 47 OBJ and GLB per
    Part 2 set and 37 per Part 1 set have a moved part
    (`part_transforms_applied`); on 16 of them, in three sets, the vertices
    read from the raw stream and taken through `v' = conj(q)·v·q + pos` up
    the parent chain equal the OBJ within 3.6e-6 and the normals within
    1.2e-6. No `.model.json` lists COLOR_0 under `not_decoded`. COLOR_0 of the 13
    (PS3 Part 2), 13 (Xbox 360 Part 2), 23 (PS3 Part 1) and 22 (Xbox 360
    Part 1) models whose colours the data alone does not order is
    byte-equal to the PC GLB; the six Docks water and patch models of the
    console Part 1 sets are `BLEND` as on PC.
  - *Textures and materials:* layer files named by slot: 56 files in 25
    folders per Part 2 set (46 `glow`, 10 `height`) and 47 files in 47
    folders per Part 1 set (23 / 24), the same textures on the three
    platforms. `roughnessEngine.png` for the same textures on the three
    platforms (561 per Part 2 set, 601 per Part 1 set). 131 MTL files per
    Part 2 set and 124 per Part 1 set differ from an export without the
    emission and opacity rules, not counting the sky sheets' `d` line (3
    more files per Part 2 set, up to 8 per Part 1 set) (`Ke`, `map_Ke`, `d`, comments, a `map_Ks`
    removed), besides the sky files named above. On PC Part 2, 98 of the 1,904 materials of the model
    GLBs have `selfIlluminance` above 0 and all 98 have an emissive texture;
    none of the other 1,806 has one. 114 `sheet.json` per Part 2 set and 201
    per Part 1 set have `cubeFaceOrder`, `animation` or `frame_ms`.
  - *Fragment JSON:* 906 per Part 2 set and 758 per Part 1 set, typed and
    lossless; 897 and 746 of them (and the scene file) hold a key whose
    letter case follows the registration, 48 distinct names on Part 2 and 49
    on Part 1. No Part 1 fragment JSON lists `inferred_names`.
  - *Raw-only formats, all six sets:* 18 fonts, 6 scenes, 24 terrains, 15
    colouring maps and 30 detail meshes parse to the last byte of header
    and stream; fonts, terrain headers, colouring headers and detail mesh
    tails rebuild byte for byte (the scene is a lossless Fragment parse).
    Each `.detailmesh.json` carries the five keys of "Detail mesh JSON says
    what is not read".
  - *Characters:* 26 GLBs and 26 `.ragdoll.json` per Part 2 set, 80 and 80
    per Part 1 set. JOINTS_0 is 0 in every zero-weight slot of
    every GLB. No GLB carries a `not_decoded` marker. Four ragdoll files per
    set have cloth (6 `physx` blocks); no cloth-only model is among the
    characters, so `build(mb, cloth_only=True)` is not exercised by the
    export. The clips whose channels differ from an export without the
    rest-pose, grip and loop items are the seven pose-rule clips and, on the
    console Part 2 sets, `EN4_EXP_MOV_dance_cage_small_C`, `GRIP 1H`
    on the two Rorschach GLBs and 13 enemy movement clips (12 `EN2_*`,
    `EN4_COM_MOV_run_cycle`), the last on jiggle bones only (9 of 318 GLBs
    compared accessor by accessor).
  - *Tables:* `anim_meta.json` of that export (`revision` 3; a table written now has 5), 8,461 events on Part 2 and
    6,768 on Part 1 (the added ones with `source`), `"loop": true` on 409 and
    390 clips, the four enum families, `conventions.ragdoll_values`,
    `combat.achievements` and `fx.event_effects`. `sound_meta.json`:
    `music_rules`, `speak_rules`, `blocks_while_playing` on 335 (Part 2) and
    611 (Part 1) sounds, 18 speak triggers. `text_meta.json`: `routes`,
    `referrers`, `unreferenced`, `audio_start_delay_s`, `languages_missing`
    and `incomplete_lines` on all sets; `frames`, `fps` and `duration_s` on
    all 16 movie players of every set, and every subtitled movie ends after
    its last row (Part 1: `Cutscene00` 2,777 frames, 92.659 s, last row ends
    at 90.306 s). `grade_meta.json`: `option_default` 0.5 and
    `default_offsets`. PS3 `sound_info.json`: `loop_skip_frames` on 55 (Part
    2) and 90 (Part 1) records.
  - *Levels and navigation:*

    | | Part 2 sets | Part 1 sets |
    |---|---|---|
    | Placements with an opacity below 1 | 853 | 327 |
    | Placements with `cast_shadow` false | 53 | 5 |
    | Cube nodes that are candidates at load | 152 of 152 | 203 of 204 |
    | Culling boxes | 233 | 0 |
    | Volumes that block AI sight | 807 | 814 |
    | Forced-state actions | 18 | 0 |
    | `weapon.no_collection` | 0 | 12 |
    | Mesh links with `gate` and `crossable` | 593 | 6,189 |

    The nearest candidate recomputed for every placement equals the exported
    `cube_map` (10,656 placements on PC and Xbox 360 Part 2, 26,932 on PC
    Part 1). `Bordello.level.json` of PC Part 2 has 36 `GIMP`, 23
    `GIMP_WITH_GAGBALL`, 92 Dominatrice, 14 Twilight Lady and the two heroes;
    `weapons_fixed` 33, `weapons_candidates` 11, `weapons_none` 123.
  - *Across the platforms:* fragment JSON equal on the three platforms in 904 of
    906 (Part 2) and 746 of 758 (Part 1; PC equals Xbox 360 in all 758), the
    rest differing in `nodes_full`, that is in the game data; no property
    under an unnamed key. `.ragdoll.json` byte-identical on the three Part 2
    sets (26) and between Xbox 360 and PS3 Part 1 (80; the PC files in 43 of
    80, the other 37 differing in one value by 4.8e-7, one bit in the PC
    data). The figures from here to the end of this item were measured
    without the part-transform, texture-slot and key-spelling items and not
    measured again with them. Textures, every layer against PC (3,448 and 4,252 per part): PS3
    none off by more than a mean of 8; Xbox 360 the layers the README names
    (seven per part, and `streamingwater` in Part 1 at 8.37 on its colour
    channels); all 660 + 1,200 cube faces pixel-identical on both consoles;
    no "approx stream" line. Console OBJ bounding boxes agree with PC within
    1 mm on 732 and 1,083 models and within 0.125 m on all, with the vertex,
    face and material-group counts of the PC one on every model; character
    piece lists (787 and 1,525 pieces) equal on the three platforms of a
    part. A length for
    every PS3 sound; 3,880 sound events on the three Part 2 sets.
    Standalone Part 1: 1,208 `sheet.json`, 1,088 `.model.json`, `.pb` /
    `.grass` decoded with no byte left, 6 nav GLBs, 92 Prison streams read
    and no asset left without its stream.
  - *glTF validator 2.0.0-dev.3.10:* 0 errors, 0 warnings and 0 infos on 30
    model GLBs (5 per set: moved-part, console-colour and relabelled-texture
    models); 0 errors on 12 character GLBs (Rorschach and one other per
    set; 548 warnings, all `NODE_SKINNED_MESH_NON_ROOT`, and 24 infos, all
    `UNUSED_OBJECT`). Measured without the part-transform, texture-slot and
    key-spelling items: no error
    in the 11 terrain GLBs of PC Part 2, PC Part 1 and PS3 Part 2, in 150
    static models of PC Part 1, in the 80 character GLBs each of PC and
    Xbox 360 Part 1, or in 915 further GLBs (characters of Xbox 360 Part 2,
    PC Part 1 and PS3 Part 1; 100 models, the faces and the nav meshes of
    each set). One terrain GLB of each part was rendered and looked at.
  - Not run: Blender; any command the export
    batch does not call, and `--frame mirrored`, on Windows; the validator
    on every GLB; vgmstream beyond 26 sampled files.
  - *Caches and commands outside the batch (measured):* the 9,726 raw and
    9,726 jiggled bakes of the six sets open, each palette `(frames, bones,
    3, 4)` with the bone count of its bind, no NaN, `dur` within 4.4e-6 s of
    `duration_s`; console raw bakes are bit-identical to PC except the one
    clip under "Behaviour changes". 8 clips per Part 2 set and 9 per Part 1
    set have constant tracks only and are baked as one frame, so their GLB
    clip has zero length while `duration_s` has the clip's. The 45 block
    headers of the six sources have display byte 2, the default fingerprint
    and a matching CRC. `savemeta` decodes both files of the profile to the
    last byte (22 and 10 records). All 413 (Part 2) and 237 (Part 1) placed
    pairs have a contact check, 0.032–0.960 m. The validator reports no
    error on the 96 face, 24 terrain and 33 navigation GLBs of the six sets.
- Seven more files, 50 tests, synthetic fixtures only: `test_p6_level.py`
  (12: forced state, AI sight with PC and console pivot-book ids, AI world,
  hero models, block names, the weapon without a collection, the button
  map), `test_p6_nav.py` (4), `test_p6_formats.py` (12: fingerprint CRC,
  native message hash, key types and spellings, `netparticipant`, the PS3
  loop word), `test_p6_audio.py` (7), `test_p6_text.py` (6),
  `test_p6_physics.py` (6: cloth flags, the cloth-only model, material,
  pelvis rotation), `test_p6_names.py` (3). Two older tests follow the key
  spelling and the settled first-frame point.
  On the game files (read-only, the six-set export and the archives):
  - *Key spelling:* every raw file with a JSON beside it decoded with the
    old and the new key table — 1,207 files of PC Part 2 and of PS3 Part 2,
    1,174 of PC Part 1 and of Xbox 360 Part 1: 898 and 747 files differ, all
    in the letter case of keys only.
  - *Levels:* all 13 PC levels and 6 console levels (Xbox 360 Part 1
    Streets2 and Undergound, PS3 Part 1 Streets2, PS3 Part 2 NightClub,
    Xbox 360 Part 2 Tutorial) built with the old and the new code: nothing
    removed; changed only `files.blocks` of Streets2 and Undergound and
    three evidence texts; the added keys as listed. The console levels give
    the same `ai_sight` counts as PC.
  - *Navigation:* the five PC Part 2 files: 593 mesh links, 542 with a unit
    gate direction, 51 never crossable; 131 path objects, all flags 8.
  - *Sound and text tables* of PC Part 2 and PC Part 1, old against new
    code: additions only, apart from the rewritten rule texts and the
    shorter open-point lists.
  - *Block headers:* 44 of 44 (five archives and the loose PC Part 1) have
    display byte 2 and a matching fingerprint CRC. *PS3 loop word:* 145 of
    145. *Ragdoll sidecars:* 44 rigs of PC Part 2, differences as listed;
    `Curtains_01` gives flags 0x4164 and 74 world pins. *Save file:* the
    user's `SETTINGS.kpw` gives the 6 × 2 × 41 × 3 map. *Animation table*
    of PC Part 2: only the listed additions and the two camera-rig keys.
  The six-set export has these keys on all six sets (the counts under
  "Six-set export").

- Three more files, 51 tests, synthetic fixtures only: `test_p6_anim.py`
  (17: the baker's pose rule and its cache, the loop flag, the sound-event
  lists, the contact check, a failing face step), `test_p6_combat.py` (18:
  the added rules, the Underboss phases, achievements, partner numbers and
  families) and `test_p6_fx_tools.py` (16: the camera reference functions,
  the settled effect fields, the level keys, joint slots and buffer-view
  targets, `char` timing and archive, the Blender script).
  - *Real data* (Part 2 PC unless said, from an extract of the Bordello mod
    archive, which differs from the original in the enemy types of one
    level): the animation table built with and without the changes on
    four sets (PC and Xbox 360 Part 2, PC and PS3 Part 1) and compared key by
    key; `sound_meta.json` on two sets; the full character export (26 GLBs,
    5,731 animations) and the 18 face GLBs compared accessor by accessor and
    validated; 6,484 body bakes under both pose rules; the 13 PC level files;
    `char` end to end on the PC. The numbers are in the items above.
    The six-set export ran the character step with these items on all six
    sets. Not run: the mirrored frame on real data; anything in the running
    game.
- **Console vertex colours:** one file, 15 tests, synthetic only:
  `test_p5_console_colour.py` (the two byte orders, the console from a block
  path, a source directory, an extract tree and `WATCHMEN_CONSOLE`, the
  Part 1 layout rule, a model with no console named, the split marker of a
  character GLB, `extract` passing the console to every model). One
  assertion each in `test_p3_part1_model.py`, `test_p3_batch.py` and
  `test_p2_console_chars.py` follows the split marker. On the game files
  (the four console sets, read-only): every format 5
  / 6 render buffer of every model against the PC copy, largest colour
  difference 0 (2,578 buffers per Part 2 set, 3,943 per Part 1 set). In the
  six-set export no model sidecar and no character GLB of the four console
  sets carries a colour marker.
- **Documentation:** one file, 6 tests: `test_p6_docs.py` (the console
  stride note and the detail-mesh note in both byte orders, the `members`
  docstring, the 28 handlers the function dump lacks in `reg_dump.json`, one 1.4.0
  heading in this file).
- **All items together on PC Part 2 files** (an extract of PC Part 2, run
  on Linux). The full character export
  (26 GLBs, 5,731 animations) with and without the model, material, level,
  format and physics items: every mesh accessor, skin and animation channel
  is equal; 406 of 432 materials gain the nine `sheet_values` keys (36 an
  `overrides` entry) and none changes its alpha mode, emission, roughness
  or specular values; the 26 ragdoll JSON differ in the keys listed under
  "Added" and in nothing else. `levelmeta` of the six levels: the added
  keys and nothing else (853 placements with an opacity below 1, 53 that do
  not cast, 152 cube candidates, 233 culling boxes, 807 volumes that block
  AI sight, 18 forced-state actions). `animmeta`: the table of the
  animation items plus `conventions.ragdoll_values`, the fake-weapon text
  and the two camera-rig key spellings. 568 models decoded without a
  texture index: 12 OBJ / GLB pairs differ from the output without the part
  transforms, all of them models with a moved part. The run with all items
  together on all six sets, from the archives and on Windows, is the
  six-set export.
- **Eyelashes, movie strings, the particle index, light layers:** three
  files, 31 tests, synthetic only. `test_s2_lash.py` (13): the stored
  layout is recognised by its own numbers and nothing else is, each strip's
  scale and shift, `_decode_sub` on the PC and the console vertex layout,
  the OBJ `vt` lines and the `.model.json` note of `decode_model`, the mark
  in a character GLB beside the record of a reconstructed variant, and
  `WATCHMEN_NO_SYNTH=1` giving the stored UVs and no mark.
  `test_s2_names.py` (8): a movie string finds its file below
  `files/data/`, the stored string is kept, the path after `MOVIE ` in a
  graph label, `levelmeta` counting both, `--names stored` leaving every
  string, and `asset_names` of the particle index with its count.
  `test_s2_glow_opacity.py` (10): the opacity as `emissiveFactor` for a
  SRCALPHA / ONE layer in `blend_material`, `extract --glb` and a
  character GLB, factor 1 for ONE / ONE, for full or unknown opacity and
  for the call without it.
- **Asset names:** 48 tests, synthetic only. `test_p8_canonical_names.py`
  (47): the mode and the table (41 entries), `canonical()` on the three
  Part 2 textures in each platform's spelling, an asset placed under its
  canonical name with the stored one on record, a later copy as a twin, a
  reference in another letter case, `safe()` with one spelling per folder,
  three synthetic archives in the spellings of the three platforms giving
  one path list, a model and its texture that store their folder in two
  spellings landing in one folder of `models/`, `textures/` and
  `extracted/`, `stored_name` in `sheet.json` and `.model.json`, `--names
  stored`, the loose-folder files, `ExportIndex` (a texture folder, a
  model, a raw asset, an archive entry, a sound; a string that names no
  file is left alone), `respell()` (field, list, map keys, a path inside a
  separated list, `stored` beside each, a second pass changes nothing), a
  table following the naming of its export, the particle index, the fx,
  animation and grade tables, the option on the twelve commands.
  `test_level_meta.py` (1): every string of a level JSON that names an
  exported file resolves with exact case, the stored strings put back give
  the level `build_level` returns, `--names stored` writes that level.
  `test_p8_canonical_names.py` cannot be imported on a tree without
  `canonical_names`. Three assertions of `test_p2_small.py` follow the
  lower-case names of the loose-folder files; `test_particlemeta.py`
  expects the index strings in the spelling of their folder.
- `test_s4_review_fixes.py` (15): the name scan on a big-endian clip with
  882 keys, a cached bake of such a clip baked again and the others kept, a
  GLB older than a bake, the clip families of `char` in both parts,
  `models[].local` / `parent_chain_without_transform` / `host_offset_copy`
  and the three counts on a fragment whose host is moved (a twin whose
  stored quaternion differs by 1e-6 in one component, none at 1e-3), a host
  at the origin marking nothing, `code_names`, the movie strings of `text_meta.json`
  with and without `--names stored`, the markup evidence, event 60, the
  navigation override evidence, and no "until 1.4.0" in any document or
  module. One of the 15, the movie strings with `--names stored`, also
  passes without the changes it stands beside: it is a guard.
  `test_blender_import_level.py` (17): one of them pins that a record with
  `host_offset_copy` keeps its kind and placement and goes to the
  `Host-offset copies` group, a disabled one to `Disabled`.
  `test_p6_combat.py` pins the re-check default of the Underboss.
- `test_s8_review_fixes.py` (41): clip timing without a walk / run
  multiplier, the jiggle memo rate, the options record of `characters` and
  `faces`, the bake identity, the bank-only clip lookup, the jiggle
  constants of the extract and the warning for a `GameEssentials` fragment
  that cannot be read, the exit codes of `extract` / `all`, the error on a
  folder that is missing or has no `extracted/` (six commands each), the
  `characters` usage text, `all` running the character export, the
  sheet-record parser and letter-case lookup, the `sheet.json` warning,
  the missing-archive message, the vectorised untiling, the prefix-matched
  root and device names, the GLB name in the `wrote` line and the
  temp-file write of `write_glb`. 35 of them fail without these changes;
  the four untiling cases and the two `write_glb` cases are guards.
- `conftest.py` fails a test that leaves a `WATCHMEN_*` variable changed;
  the CLI tests that set one undo it, so the result does not depend on
  the order the tests run in (measured: ten random orders, five per frame,
  with the CPU under load).
- **Suite: 1,774 tests.** A checkout on its own reports 1,772 passed
  and 2 skipped (the two comparisons with an older source tree); with a
  1.3.0 tree and the development snapshot beside it all 1,774 pass. 21 of
  the tests of the `test_p6_*` files also pass on a tree without the items
  they belong to: they are guards on behaviour that stays (a one-key keyed
  track stays absolute, a blending sheet keeps its opacity factor, low
  opacity blends a type 0 / 10 sheet and leaves a sprite or wet sheet
  alone, the two glow-map cases, the seven sheets read back with the
  captured constants) and do not pin a change. With
  `WATCHMEN_FRAME=mirrored` the suite gives the same result (Linux, Python
  3.13). With Python 3.8.20 and 3.9.25 on the minimum pins (numpy 1.20.0,
  Pillow 9.0.0) a lone checkout without `capstone` gives 1,771 passed and
  3 skipped in both frames (the two comparisons with an older tree and the
  `capstone` test). On Windows (Python 3.13.13, numpy 2.4.6) the suite
  without `test_s8_review_fixes.py` and its companion test updates passed
  in both frames with the same three skipped; the full suite has not run
  there.

- Measurement, no code: three frames of the Bordello capture rendered from
  the exported character GLBs with the captured camera, bone palettes,
  lights and post-processing constants (`docs/MATERIAL_COMPARISON.md`). The
  engine's lighting equation with the constants of each draw differs from
  the game frame by 2.4, 5.0 and 12.3 of 255 on the character pixels (mean
  absolute difference), the GLB materials in Blender 3.6.0 Cycles by 13.3,
  11.1 and 23.5; the table there gives the difference per material beside
  the terms of the engine's equation (display-space lighting, the falloff
  term, highlights without Fresnel). The Blender light levels are
  estimates, so the Blender column measures them together with the
  materials.

## 1.3.0 — 2026-10-02

Two things in one release. **Animation metadata** for consumers of the
character GLBs: states, events, transitions, the pair table and partner
placement, in glTF `extras` and a JSON sidecar; joint node names, hierarchy
and keyframes are unchanged. And the results of a **full decompilation pass**
over the executable, implemented: nine research reports (`docs/re/`) closed a
number of documented unknowns — block header, mesh and texture headers, the
name hash, events, sync markers, page and play-position rules, jiggle setup —
and the toolkit follows the engine's own loaders and update functions where
they were read. **Several defaults change output**; they are listed first,
each with how to get the 1.2.0 result.

A development build of this release, never tagged, wrote animation metadata
as `watchmen-anim-meta/1`. The released format is `watchmen-anim-meta/2`.
Against a format 1 file: event times have a unit and count from the state's
start position, 644 of 1,130 state paths gain groups that build had dropped,
and 18 pair candidates (6 primary) are added. `docs/ANIMATION_META.md` has
the full list for anyone who read a format 1 file.

### Behaviour changes

- **Models: LOD 0 only.** PC models are now decoded from their header, which
  says which buffers belong to which level of detail. The extractor used to
  merge every LOD into one mesh; it now writes the full-detail LOD. 117 of the
  740 Part 2 PC models have more than one LOD; triangles written drop from
  1,368,216 to 1,285,766.
  *Old output:* `watchmen extract … --model-lod all`
  (`decode_model(…, lod="all")`) writes every LOD into one file; `--model-lod
  N` picks one, clamped to each part's last LOD.
- **Models: proxy slabs are not written.** 79 parts carry one extra rigid
  buffer — a coarse slab inside the visible mesh (a 5-triangle slab inside a
  196-triangle door). It is not render geometry; its role in the engine is not
  established. 38 models lose such a slab.
  *Old output:* there is no CLI switch. The buffers are available as
  `kind == "proxy"` from `watchmen_extract.decode_model_mesh(header, stream,
  kinds=("render", "proxy"))`.
- **Models: materials are named from the submesh record.** Each submesh
  stores an index into the model's texture list. The previous pairing searched
  for a byte pattern after the piece name and often landed on index 0. Names
  change on 192 models (`PeepingRooms_Booths`: `Door_401k_02 ×3` →
  `Door_401k_02, HoneyPot_Plywood_01, Scaffold_Metal_01`).
  *Old output:* not available for header-driven models; the old names were
  wrong. `submesh_materials` / `extract_materials` are unchanged and still
  used where the header path does not apply (console files, Part 1) and by the
  character pipeline.
- **Localized block entries are extracted, from language slot 0.** The six
  size / stream slots of a block directory record are languages, not
  platforms, and each block has extra records behind a per-language seek that
  the old parser never listed: 15 per game (Part 2: the menu logo and 14 `_uk`
  text assets). The 8,696 entries listed before are unchanged.
  *Other slots:* `--language 0..5` (`extract_block(h, s, language=N)`). Which
  language each slot number means is not established. *Old output:* there is no
  switch to leave them out. With `--limit N` the extra entry in `mainmenu`
  moves the window by one asset.
- **Jiggle: the baked result is unchanged, the cache directory is not.**
  The default jiggle model is still the one of 1.2.0 (`pinned`), bit-identical.
  `watchmen characters` now keeps jiggled palettes in
  `OUT_DIR/_bake/<skeleton>_j_<model>-<mode>-<constants hash>/` instead of
  `<skeleton>_j/`, so palettes baked with one model or one set of constants
  are never served for another. An existing `<skeleton>_j/` is not read: the
  jiggle is re-baked once (same numbers) and the old directory can be deleted.
  Existing GLBs are never rebuilt; delete them to re-export with another model.
- **`watchmen hash` and `watchmenlib.kapow_hash` use the engine's fold.** The
  engine ANDs every byte of a name with 0xDF before hashing; it does not
  upper-case. The result differs for names containing digits or punctuation
  and is the same for names made of letters and `_`.
  *Old output:* `kapow_props.kapow_hash(name.upper())` — `kapow_props.kapow_hash`
  is unchanged and hashes the bytes as given.
- **Fragment JSON.** Keys whose names contain digits resolve (`key_ee2a40a0`
  … are `m_nsupersynclocal1..8`, `key_4cadfb2b` … `m_nsupersyncremote1..8`);
  27 key names change letter case to the engine's spelling (`pivotsheet_id` →
  `pivotSheet_Id`, `loopmode` → `loopMode`); created nodes carry their type;
  2,489 properties move to the node they belong to. Of the 1,238,028
  properties the old parser emitted with a known type, all are present with
  identical name, type and value. *Old output:* not available; it was a
  misparse.
- **Sequence JSON** carries `"format": "kapow-sequence/2"` when the engine
  grammar parses the file to its last byte (all shipped files). An object can
  have both `path` and `ids`. Every object, track, key time and value of the
  old output is still there, with one exception: `handles` disappears from
  the last key of some step tracks (33 keys on Part 2 PC, 47 on Part 1 — e.g.
  `impassable` in `Door_HoneyPot_01CLOSE.sequence`, `handles: [0,0,0,0]`).
  Step keys have no handles; the old scanner had read the first 20 bytes of
  the next object as one, which is also why it lost objects.
- **`extract --model-lod` / `--language` reject bad values.** A negative
  LOD used to select no buffer and silently fall back to the legacy scan; a
  language slot outside 0..5 was accepted and ignored. Both are now usage
  errors (`decode_model(lod=-1)` / `extract_block(language=7)` raise
  `ValueError`).
- **`Toc.flag` / `Toc.pairs`** describe the entry's own stream, not the
  previous entry's.
- **`parse_model_nodes.parse_node_aux`**: `pos` is the volume's position. It
  used to hold a capsule's (diameter, height, x). `a` / `a2` are a capsule's
  diameter and height and `None` for the other volume types (they were always
  floats: two components of the misread position).
- **State-machine simulations differ** from 1.2.0 output: fewer transitions,
  different weights during crossfades. `Interpreter(done_fallback=True)`
  restores the one old rule that has no engine counterpart ("a finished page
  falls back").
- **`reg_dump.json`**: `argc` is removed from command records (it never was an
  argument count), and `classId` now holds the real class id. The class `name`
  changes on 12 records — six that had none get one, and six that carried the
  name of a neighbouring registration are corrected (`AnimationEvent` →
  `AnimationEventWM`, `Texture` → `TextureEffects`, `CollisionCapsuleNode` →
  `CharacterPhysics`, `Behavior` → `FollowPivotBehavior`, `TriggerActionBase`
  → `TriggerActionCamera`, `TriggerCharacter` → `TriggerUse`) — and `base` on
  4 more. The file is still a bare JSON list and carries no format marker;
  "kapow-reg-dump/2" (`gen_data.REG_DUMP_FORMAT`) names the layout in the
  documentation only. A reader can tell the two apart by the absence of
  `argc`; code that indexes `cmd["argc"]` needs `cmd.get("argc")`.

### Added

- **Animation metadata** (`wlib/anim_meta.py`, `watchmen animmeta EXTRACT_OUT
  OUT.json [BINDS]`, format `watchmen-anim-meta/2`; see
  `docs/ANIMATION_META.md`). Reads the game's AnimationClass fragments and
  clip root tracks into one table. Part 2 PC: 1,290 states, 2,593 transitions,
  5,099 events, 1,159 clips, 413 pair candidates, 240 primary.
  - *States* carry clips, loop, start play position, `speed`, `criteria_tree`,
    `special_handling`, `animation_type` and events. *Classes* list their
    `transitions` with sync markers. Names and ids come from the executable
    (`enums`, `event_semantics`).
  - *Events* carry `trigger`, `raw`, `time_s`, `play_time_s`, `time_unit`, and
    the `start_playpos` / `start_basis` their times were computed for. A state
    is entered at its own start position (563 of 1,290 states start past 0),
    so a `PLAY_POS` event at r fires (r − start) × duration / speed seconds
    after entry; a `TOTAL_PLAY_TIME` event stores seconds and sits at start +
    t × speed / duration; enter / leave events have no position. Events at or
    before the start carry `fires_first_pass: false` (34).
  - *Pairs from the game's own table.* A master state names its slave through
    `m_imasterof`; the partner class files it under `SlaveStates` by
    `m_istategroupid` / `m_istateid`, and criteria on the opponent's model
    type (enum variable 11) pick the child. This replaces matching halves by
    name, which cannot see that Nite Owl's throw plays `RSH_COM_ATT_throw_EN1`
    or that counters against Enemy04 reuse the `…_EN1_*` attacker clips. Pairs
    also carry `weapons` and group criteria.
  - *Partner placement — the engine's rule*, read from the executable
    (`CharacterRoot.StateActive` 0x6b9035–0x6b94e9): the anchor is the
    master's `interact` marker, its frame turned 180° about +Y (a literal −π/2
    half-angle constant), and every actor moves by its own `GamePivot` track
    relative to that track's first key. When the master's interact is not
    authored the engine uses the offset (0.11, 0.04, 1.12). Each pair reports
    where the partner clip's *own* GamePivot start falls, an optional
    geometric contact check, and a `confidence` from those (198 verified, 32
    plausible, 10 unverified of 240).
  - *Pair timeline* on the master's clock (the partner's play position is
    copied from the master every frame), starting at the master's start
    position (`timeline.start_playpos`, past 0 on 205 of 240 primary pairs).
    The master is not an absolute animation and is never snapped; the partner
    holds its entry pose until its `ABSOLUTE_GOTO_TARGET_POS` event, blends
    onto the anchor over its ease-in, and is released at its first
    `LEAVE_ABSOLUTE_MODE`. Every master state is entered only through group
    transitions without an override or sync start, every partner state only by
    `goto_slave_mode` (`master.entry_alternatives` is empty throughout).
  - `anim_meta` calls the rule functions of `anim_state_machine`; no engine
    rule is implemented twice.
- **GLB `extras`.** `asset.extras` carries the coordinate conventions
  (including that the export is a mirror image); the skin carries the real
  bone names, parent indices, the `GamePivot` / `interact` / `Bip` joint
  indices and the attach joints; each joint node carries its `bone` and
  `parent`; each animation carries its clip record with events timed against
  the animation as written. `watchmen characters` builds the table once, saves
  it as `OUT_DIR/anim_meta.json`, and embeds it.
- **Header-driven model decode** (`watchmen_extract`): `parse_model_header`,
  `model_stream_layout`, `select_model_buffers`, `decode_model_mesh`,
  `decode_vertex_attributes`, `gltf_tangents`, `VERTEX_STRIDES`,
  `VERTEX_FORMATS`. Every buffer offset is computed from the header; nothing
  is searched. Used only when the header parses and the layout consumes the
  stream to the last byte (735 of 735 Part 2 PC models with a stream);
  otherwise the previous scan runs unchanged (console files, Part 1).
- **Script asset classes.** `ModelEffects(ModelRes)` and
  `TextureEffects(Texture)` — the two asset-type hashes that had no name — are
  read by their base class's loader. Part 2 PC: +307 model jobs (674 → 981),
  +53 textures. `ASSET_TYPE_NAMES`, `asset_type_name`, `asset_base_class`.
- **Block header.** `parse_block_header()` returns the 400-byte header as
  named fields; `fingerprint_decrypt()` decodes the fingerprint string;
  `Toc` gained `type_hash`, `type_name`, `sizes`, `has_stream`, `streams`,
  `localized`, `language` (the old attribute names `flag`, `pairs`,
  `variants`, `unknown` still work, for reading and writing). A header
  shorter than 400 bytes raises `ValueError("not a block header …")`.
- **Exact Texture header**: `parse_texture_frames`; `plan_texture_layers`
  returns the exact plan (layers carry `slot` and `chain`) when it tiles the
  stream, else the previous planner runs.
- **Sequences**: `decode_sequence.parse_exact`, `evaluate(track, t)` (step /
  linear / cubic Hermite) and `euler_deg_to_quat`. Tracks carry
  `interpolation`, `value_type`, `spline`; keys carry `in` / `out` handles and,
  on quaternion tracks, `euler_deg` / `quat`. The linear branch of `evaluate`
  assumes a component-wise lerp; the engine's per-type interpolator was not
  read.
- **Node collision volumes.** `skeleton_records.parse_node_tail` /
  `parse_volume_lists` read the per-node layout (box, sphere, capsule, convex
  and concave mesh; two lists per node plus an emitter-surface list).
  `skeleton_records.parse()` records carry `volumes`; skeleton JSON bones carry
  an optional `collision_volumes`. 934 volumes in 23 Part 2 PC models; all
  2,069 mesh-free node regions tile. Rest poses, hierarchies, names and binds
  are bit-identical.
- **GLB vertex attributes — available in the API, off in the CLI.**
  `rig_glb.build_rigged_glb(…, normals=, tangents=, colors=)` can write
  NORMAL, TANGENT and COLOR_0 (`rig_glb.mesh_vertex_attributes` supplies them)
  and flips the winding of primitives that carry normals. Its positional `N`
  argument is ignored exactly as in 1.2.0, so existing callers get the same
  file. `watchmen extract --glb` does not pass the
  data, so its GLBs carry none of the three and keep the file's winding (with
  the caller unchanged, the new writer's output is byte-identical to the old
  writer's on all 130 GLBs of Part 2 PC). The reasons: what the engine
  does with the vertex colour is not established, and as a glTF `COLOR_0` it
  darkens the 31 models that have authored colours by about 17 %; the stored
  tangents are not perpendicular to the normals (|n·t| above 0.1 on 29 % of
  vertices); and writing normals means flipping the winding of 279 of 283
  primitives, because the game's triangles are clockwise against their
  normals.
- **Name hash API**: `kapow_props.name_fold`, `name_hash`.
- **`wlib/engine_enums.py`** and `engine_schema.commands_by_hash()`.
- **Interpreter**: `Interpreter(seed=…, rng=…)` and CLI `--seed` for the
  per-layer blend-node choice; `Interpreter.fired` (events); `Env.speed`,
  `Env.force_linear`, `Env.no_override_layer`, `Env.force_update`;
  `Page.slot_playpos`; the shared rule functions `interval_met`, `event_due`,
  `event_prelatched`, `criteria_of`, `transitions_of`, `members`,
  `transition_criteria`, `marker_pairs`, `map_markers`, `start_playpos`,
  `slot_speed`, `state_speed`, `event_timing`, `resolve_ref`.
- **Jiggle: the `pivot` model, opt-in.** `watchmen characters … --jiggle-model
  pivot` (also on `char`, where the option turns the jiggle bake on),
  `apply_jiggle(…, model="pivot")`, `characters_export.export(…,
  jiggle_model=)`, `variant_glb.build(…, jiggle_model=)`. The default stays
  `pinned` (`jiggle_d6.DEFAULT_MODEL`), because the pivot model's swing
  constants are fitted to captures at an estimated frame rate.
  In the pivot model the simulated body swings about the *parent* bone origin
  on the parent→bone lever; its pose replaces the bone's local position *and*
  rotation; gravity is not applied (the game cancels it every frame); twist
  about the parent X axis is locked; the clamp is the bone-origin displacement
  in metres (0.08 m breasts, 0.10 m belly); the body trails the parent by one
  frame. Against the in-game captures (BreastL / BreastR / JiggleBelly),
  pinned → pivot: rotation error 5.90° / 5.64° / 4.09° → 4.29° / 4.13° / 1.96°
  rms; bone-origin error 16.4 / 15.8 / 5.6 mm → 8.0 / 7.7 / 3.5 mm;
  least-squares amplitude factor 0.34 / 0.35 / 0.16 → 0.98 / 0.96 / 0.87;
  correlation 0.29 / 0.29 / 0.26 → 0.59 / 0.59 / 0.63. The plain ratio of mean
  deviation magnitudes moves the other way, 1.05 / 1.02 / 0.52 → 1.57 / 1.47 /
  1.58; why is not established (the capture input has no root motion). On
  baked clips the pivot model has no static sag and smaller swing angles (EN4
  `run_cycle` breasts 4.62° / 4.15° → 3.04° / 2.85° mean; `idle_stand` 1.51° /
  1.65° → 0.01°).
  *What is read from the exe:* the geometry above, body size and mass, angular
  damping, the 1/60 s step. *What is capture-measured:* the swing stiffness
  and damping (`mode='capture'`: breast K 570 s⁻², D 37.5 s⁻¹; belly 308,
  19.2), which depend on an estimated capture rate of about 55 fps, and the
  one-frame latency (consistent with the update order in the exe, measured on
  the captures). Hair has no capture and uses the file constants.
  Also new: `swing_constants`, `resolve_model`, `cache_signature`,
  `apply_jiggle_legacy`, `apply_jiggle(…, latency=)`,
  `jiggle_pass.apply_jiggle(…, model=)`.
- **`tools/ghidra/`**: three Ghidra scripts and the handler table used to
  produce the decompilation the reports were read from (see its README).

### Fixed

- **Name hash.** `FUN_00423ce8` folds each byte with `& 0xDF`: digits and
  punctuation fold too (`'0'..'9'` → 0x10..0x19, `(` → 0x08). Every name with a
  digit was filed under a hash the game never uses.
- **Fragment parser.** `0xFFFFFFFF` introduces a type record (`Class(Native)`
  or a bare native class) wherever it occurs, never properties; the parser
  accepted only the opening block and read later records as property keys. A
  17-byte header-only file is an empty fragment, not a failure. Part 2 corpus:
  906 / 906 files parse (was 897); unknown-key occurrences 580,286 → 22;
  node entries 108,348 → 118,408; 483,682 more properties typed.
- **Fragment loader** (`anim_state_machine.load_tree`). The top-level nodes of
  a nested fragment were dropped and their children re-parented (126 states
  and 82 groups on Part 2 PC), and a fragment was spliced only once; node
  classes came from the preamble table only (44 nodes had none); references
  were resolved by id across instances. All three fixed; a reference to the
  fragment's own slot is the group that instances it.
- **Models.** 42 models had 1–4 submeshes decoded from a wrong stream offset
  (`TwilightMansion_Bath_Stairs`: a 28-vertex submesh read at 73039, it is at
  57562); 53 gain submeshes the scan never found (`lock_casing_start` 918 →
  7,274 triangles); 12 vegetation submeshes on two palm models were dropped by
  a field test. No model lost geometry that was right.
- **Model node table** (`parse_model_nodes.parse`): header-driven on PC. 29
  mesh-only props no longer raise `ValueError('no node names')`; three
  bridge / sky models regain nodes the scan dropped for being more than 100
  units from the origin. All skeleton and character models are identical.
- **Textures.** 4-byte row padding of linear formats; 10 two- or three-layer
  materials were read as flipbooks (`baseballbat`, `CityBackdrop_01/02/03` …);
  the header of a `TextureEffects` texture did not parse (28 on Part 2 PC).
  Run through `carve_texture`, 898 of 936 Part 2 PC textures are
  byte-identical and those 38 change.
- **Sequences.** The scanner missed objects — in the 15 door sequences the
  door's own `localorient` track. Part 2 PC: 351 → 366 objects, 1,972 → 2,002
  keys; totals now agree across PC, X360 and PS3.
- **Interpreter.** Sync markers were read under the pre-fix key names;
  interval tests (`LESS_THAN` is `x < max`, intervals are half-open); events
  fire when the position is reached (`<=`); a transition to a state also
  carries that state's criteria; "entry only" criteria are skipped only inside
  their owner; fallback transitions only in the fallback pass.
- **`gendata regdump`** missed 114 property registrations, 5 command hashes
  and 88 short command names; `classId` was wrong for most classes.
- `anim_state_machine.load_tree` raised `IndexError` on a sub-fragment with no
  instances (several `SoundEvents` fragments parse that way), which lost the
  whole `AnimationClassEnemyBig` tree. Empty fragments are skipped.
- `load_tree` read the `.fragment.json` on disk, so JSON written by an older
  extractor — with `key_xxxxxxxx` names where the current key table has `m_…`
  — silently produced a tree with no usable properties. It now parses the
  binary `.fragment` beside it and falls back to the JSON only when the binary
  is absent. Sub-fragment paths are resolved on Windows separators too.

### Changed

- **State-machine interpreter v2.** Page setup follows `SetupNewPage`
  (same-state and re-entry handling, walk-cycle phase carry-over, ease-in rule,
  force-stay timer, no page cap); play position uses the weighted rate with
  slot speed and the 6.6 /s clamp; the blend curve applies only with "Soft
  Blend To"; one blend node per layer list; overlay fade-out; events. The
  slave lock of a paired animation is not modelled (the interpreter runs one
  character).
- **`parse_node_aux`** is a wrapper over `skeleton_records.parse_node_tail`
  and reads every volume type.
- **`bake_v4.py` is unchanged.** The executable adds a pose term to the
  constant position of type 1 / 3 clip tracks; the shipped constants are
  absolute values, so the baker keeps "non-zero constant = absolute". Open
  question, recorded in `docs/ENGINE_CONSTANTS.md`.

### Data tables

- `kapow_fragment_keys.pkl` and `prop_hash_dict.pkl` re-keyed under the engine
  hash: 480 keytable, 16,293 nameable and 8,343 dictionary entries moved. No
  entry was kept under its old hash; none of the old hashes is attested.
  862 built-in node properties typed from the engine's typed registration
  wrappers (`promoted` 3 → 865); new 8-byte `biginteger` value type.
- `reg_dump.json` format 2 (`gendata regdump`): 441 classes, 5,090 property
  and 6,630 command registrations. Properties carry `name`, `flags`,
  `typeidx`; commands carry `slot` (command 3,939 / state 841 / method 1,850),
  `kind`, `arg3`, `typeidx`, `signature`; classes carry `classId`,
  `native_base`, `parent`. Still a bare list of classes.
- `command_signatures.json` (new): the 830 hashed strings of commands that
  take parameters, `name(type,…)`. Research output — the strings are not in
  the executable; each is verified by re-hashing.
- `engine_enums.json` (new): 30 enum families as the executable registers
  them, the family each criteria enum variable takes its values from, the
  interval types, and what each of the 93 animation events does.

### Documentation

- `docs/re/`: the nine research reports and their tables, shipped verbatim,
  with a README that says what each establishes and lists the corrections
  found while implementing.
- `docs/ANIMATION_META.md` (new).
- `docs/ENGINE_CONSTANTS.md`: a new section for this pass; earlier statements
  now known to be wrong carry an inline `[corrected 2026-10-02: …]` note
  instead of being rewritten.
- `docs/KAPOW_NAZ_FORMAT.md`, `FORMATS_MISC.md`, `FRAGMENT_FORMAT.md`,
  `WATCHMEN_EXTRACTION_MASTER.md` corrected and marked the same way: the block
  header is 400 bytes and the stream pair belongs to its own record (there is
  no "+1 shift"); the six slots are languages; the u32 after an asset's type
  name is the property-bag length; the texture descriptor is 29 bytes plus a
  presence byte per slot; vertex formats; the `.sequence` grammar; the
  "stride-16 int16 baked mesh" claim is withdrawn; the "EmbeddedJointNode
  joint records" are collision volumes.
- `tools/ghidra/README.md`.

### Tests

- Seven new files, 184 tests, synthetic fixtures only: `test_anim_meta.py`
  (20), `test_names.py` (28),
  `test_anim_meta_v2.py` (18), `test_interp_v2.py` (25), `test_formats_v2.py`
  (23), `test_phys_v2.py` (27), `test_followup.py` (43). Suite: 406 tests,
  independent of test order and hash seed, pyflakes-clean. Event times and the
  pair timeline for states that start past 0 are checked against an
  `Interpreter` run of the same state.
- Existing tests edited where a change invalidated what they pinned:
  `test_v120_regressions.py` (the node-aux fixture is built in the engine
  layout), two docstrings in `test_kapow_hash.py`.
- Real-data validation, read-only, numbers as quoted above: Part 2 PC (740
  models, 936 textures, 194 sequences, 906 fragments, 45 animation fragments),
  plus X360 / PS3 Part 2 and PC Part 1 for the block directory, models and
  sequences. `watchmen characters` was run on Part 2 PC with the new metadata (26
  GLBs). Not run on real data: a full extraction, console files through
  `parse_node_aux`.

## 1.2.0 — 2026-08-17

A second correctness pass. The dominant theme: fixes the bulk `characters`
path (`char_lib`) collected in July that the single-model paths never
received. **Output-affecting for console extraction, `watchmen char`, bulk
walk/run timing, and `export_female_anims`** — details below.

### Output-affecting

- **Console rigged GLBs from the extractor.** `decode_model` auto-detected the
  byte order but didn't pass it to `decode_skin`, so the PC `stride >= 56`
  gate rejected every console (stride-44) skinned submesh and `--glb` on an
  X360/PS3 naz silently produced no skinned GLB at all. The `watchmenlib`
  facade wrapper dropped the argument too. Both now thread the order through.
- **`watchmen char` / `wl.build_variant_glb` skinning.** `variant_glb.
  load_parts` was missing the 2026-07-13 `BipNN`-prefix-insensitive bone-name
  fallback `char_lib` has, so Thug/Heavies-style name mismatches silently
  dropped mid-list bones and shifted the rotate-by-one palette (mis-skinned
  arms/head). Also ported from `char_lib`: byte-order autodetection (the path
  was little-endian-only), the `_ib_ok` clean-index-buffer guard, and
  engine-exact `submesh_materials` pairing (positional pairing textures the
  wrong submeshes when one material covers several). The extractor's OBJ/MTL
  path got the same `submesh_materials` fix.
- **Bulk locomotion timing.** `watchmen characters` never applied the
  capture-verified `SPEED_MULT` runtime sync that `watchmen char` applies, so
  the two writers disagreed on walk/run clips. The bulk path now applies it.
- **`export_female_anims`** still carried the pre-1.1.0 Z-up→Y-up conversion —
  and applied it twice (baked into POSITION *and* on the Armature root), so
  its output was rotated. No conversion is applied now; output matches the
  other writers. Also: removed an orphaned duplicate IBM accessor, replaced a
  bare `except`, and a naz without the female skeleton now fails with a clear
  message instead of a `TypeError`.
- **Clip-bank lookups in `variant_glb.build()`** only matched keys named
  `<clip>.animation`, while `bake_v4` accepts bare names too; a bare-keyed
  bank silently missed every clip and fell back to 30 fps. Lookups are now
  tolerant the same way `bake_v4`'s are.

### Correctness

- `bake_v4`: the frame count came from quaternion tracks only; a clip whose
  longest track is positional had its position keys silently down-sampled.
- `jiggle_d6`/`jiggle_pass`: the sim→clip resample clamped the index but not
  the weight, so clips faster than the integration grid extrapolated past the
  last sim sample (and could overshoot the engine distance clamp). Clamped.
- `variant_glb`: face-first materials silently lost their specular layer (the
  face material block was a copy of the body block minus the
  `KHR_materials_specular` handling); one `try/except` around the face-synth
  import also swallowed per-pose errors and disabled all auto-pairing on the
  first bad pose — it now guards only the import and reports failing poses.
- `skeleton_records` and `parse_model_nodes.parse_node_aux` were
  little-endian-only; both are byte-order aware now (facade callers get
  console support with no signature change).
- X360 texture carve: the tile buffer sized width as `max(w, 32)` where every
  consumer aligns width up to 32; non-power-of-two widths over 32 blocks got
  their untiled tail zero-filled (blank PNG bands).
- `mediastream` vs `MediaStream`: the console-audio metadata pass compared the
  asset class against two different spellings, so at most one branch could
  ever match; both comparisons are case-insensitive now.
- Legacy-carved textures (`diffuse.png`, …) used names the texture index and
  MTL linker can't see; they now use the standard
  `<i>_<label>_<WxH>_<FMT>.png` scheme and link into OBJ materials.
- `kapow_props.parse` bounds-checks payload reads (truncated propbags return
  partial results with a `warn` entry instead of raising `struct.error`), and
  the dead `wc + 1 != k` validation actually warns now.

### CLI and library surface

- `hash` and `gendata` dispatch before the facade import: `watchmen hash` no
  longer imports numpy/Pillow/the data tables, and `watchmen gendata
  keys-import` — the documented recovery when `kapow_fragment_keys.pkl` is
  missing — no longer dies on the very import error it exists to fix.
- `kapow_fragment` raises `ImportError` instead of `SystemExit` when its key
  table is missing: `SystemExit` derives from `BaseException`, so it escaped
  every `except Exception` guard (pytest collection died with zero tests run;
  `import watchmenlib` could kill a host process). The CLI catches it (and
  `struct.error`) and prints an `error:` line; missing-table exit code is now
  2, not 1.
- `--limit N` on the extractor actually stops after N block assets, as its
  help always claimed.
- Stale docs/comments swept: the extractor's `OUT/streams/` claim, a dead
  `_RIG["skeletons"]` store and its misleading comment, a dead `stats`
  counter, `rig_glb`'s claim that its (legacy, caller-less) animation path
  decodes translations, `extract_skeletons`' description of the removed
  biped-name parent fallback, and the removed `sys.argv` snapshot note in
  `watchmen.py`.
- The key-count-cap regression test now actually fails when the cap is
  removed (it fed keys the dimension check rejected anyway, so it pinned
  nothing).
- Added `tests/test_v120_regressions.py` (34 tests, 2026-09-01): one or more
  per fix above, each verified to fail on 1.1.0 (28 of the 34 fail there; the
  rest are reference fixtures). No game files needed. Suite: 222 tests.
- Verified on real assets (2026-09-01): the X360 Rorschach model now yields a
  rigged GLB whose joint indices and weights are identical to the PC export and
  whose positions agree to 0.5 mm (half-float quantisation); on 1.1.0 the same
  input produced no GLB. The OBJ material list for that model now shows
  `RorschachTrenchcoat` on all three trenchcoat submeshes instead of the
  positional shift (`submesh_9`, `submesh_10` fallbacks).

## 1.1.0 — 2026-07-24

A correctness pass over the whole toolkit. **Three changes alter output**; the
rest are robustness, security, portability and packaging. Re-export anything you
generated with 1.0.0.

### Output-affecting

- **Axis convention.** The Kapow engine is Y-up, the same as glTF, so no axis
  conversion is applied any more. Previously both GLB writers rotated positions
  by a Z-up→Y-up matrix. In `variant_glb` an exact inverse was folded into the
  joint world matrices, so the animated result cancelled out correctly but the
  raw `POSITION` data — and therefore the bind pose — was 90° about X. In
  `rig_glb` nothing cancelled it, so every model it wrote (static props, heads,
  and rigged bodies) came out on its back. Animated character output is
  numerically unchanged (verified 1e-7 against the previous writer); `POSITION`
  and everything `rig_glb` produces is now upright.

  Evidence: skinned frame-0 bbox of a shipped character GLB is 1.75 m tall along
  Y with feet down, while its `POSITION` alone measured 1.80 m along Z. The
  original Z-up reading came from `decode_skeleton_model.py` (see below), which
  was superseded for an off-by-one bug and also reported a 1.4 m character.

- **Character GLB rest pose.** Joint nodes were emitted with identity TRS while
  the inverse bind matrices were real, so with no animation playing the skinning
  matrix was the IBM alone and the mesh rendered in bind-*local* space —
  measured 0.72 m mean vertex displacement and a mesh collapsed to about a fifth
  of its animated size. Joint nodes now carry the bind pose. Anything that shows
  the scene before you pick an action (Blender's rest pose, the default glTF
  viewer state, thumbnailers) is now correct.

- **Clip timing in `variant_glb.build()`** (i.e. `watchmen char` and
  `wl.build_variant_glb`). It read the clip header's field 0 as the duration;
  field 0 is the key RATE and field 1 is the duration. Since
  `keyRate == (keyCount-1)/duration`, the computed fps came out as
  approximately the duration in seconds — roughly 3× too slow on a typical
  clip. `bake_v4` had been fixed for this in 2026-07-09 and carries a comment
  saying so 20 lines above the offending call; `build()` was never updated. The
  bulk paths (`watchmen characters`, `charlibs`) computed fps correctly via
  `bake_v4.fps_for` and are unaffected.

### Correctness

- `OUT/skeletons/*.json` was built by `decode_skeleton_model.decode()`, which
  that module's own docstring marked SUPERSEDED for an off-by-one: the 28-byte
  `[pos][quat]` transform *precedes* the name in a node record, so every bone
  was published carrying its successor's rest transform, the last bone of every
  skeleton was dropped, `bone_count` was short by one, and parents were guessed
  from biped names instead of read from the record. `extract_skeletons` is now
  built on `parse_model_nodes.parse()`, and `decode_skeleton_model.py` is
  **removed**.
- Console (X360/PS3) skeletons: `extract_skeletons` read the per-node parent
  field little-endian only, which threw `struct.error` on every big-endian
  header — swallowed by two `except Exception: pass` handlers, so console runs
  logged "0 base skeletons decoded" and every rigged console GLB got joints
  named `bone_0`, `bone_1`, … `_model_is_body` had the same problem but returned
  empty instead of raising, so its safety net never fired and every skinned
  console character was exported *static*, silently. Both now use the same
  byte-order autodetection as the rest of the codebase.
- `kapow_json`: the duplicate-resource-reference filter was `pass` where
  `continue` was meant, so every fragment JSON emitted each resource path twice,
  usually under two different key names.
- `parse_model_nodes`: bounds-check every record read, and fail loudly when the
  number of nodes parsed disagrees with the header's own count (a silently
  dropped node shifted every later parent index and corrupted the hierarchy).
- `jiggle_d6`: solver softening used a hardcoded 120 Hz instead of the
  integration rate read from the fragment. No change at the shipped 60 Hz;
  correct, and stable, at any other rate.
- glTF conformance: empty `animations`/`skins`/`images`/`textures`/`materials`
  arrays are no longer emitted (glTF 2.0 sets `minItems: 1`; the Khronos
  validator reports them as errors), and animation input accessors carry their
  real `min`/`max` instead of a hardcoded `0.0`.

### Security / robustness

- `safe()` neutralizes Windows drive-relative entry names (`C:/…`, `D:evil.txt`,
  which `pathlib` treats as a new anchor and which therefore escaped the output
  directory), maps an empty entry name to `_unnamed` instead of returning the
  output directory itself, and asserts containment.
- Removed a `pickle.load` fallback to `/tmp/prop_hash_dict.pkl` — a
  world-writable path, and `pickle.load` executes code. A missing or corrupt
  table now warns on stderr instead of silently degrading every property key to
  a hex hash behind a bare `except:`.
- `decode_sequence` bounds-checks truncated buffers and has a forward-progress
  guard (its resync window scans backwards, so a 2-cycle was representable).
- `naz_entries` on a file shorter than the EOCD record says "not a NAZ archive"
  instead of raising `OSError(EINVAL)` from a negative seek.
- A stale `<clip>.npz.tmp.npz` from a killed chunked bake matched the resume
  glob and was loaded as a real animation — permanently, since nothing cleaned
  it up. Temps are now skipped and swept.

### Determinism and portability

- `build_texture_index` and the loose-tree walk no longer depend on filesystem
  enumeration order, so which texture directory wins for a colliding basename is
  stable across machines.
- All text output is written UTF-8 with LF line endings, so output is
  byte-identical across platforms.

### Library surface

- `import watchmenlib` no longer rewrites the host program's `sys.argv`, no
  longer raises the process recursion limit, and no longer resolves paths into
  `site-packages`. `bake_v4.bake()` takes `bind=` / `conj=` / `bank=` directly;
  the six `sys.argv = [...]` + `importlib.reload()` sites are gone.
- The dead `wl.BINDS` / `variant_glb.BINDS` tables (every entry pointed at a
  developer-machine directory that never shipped) are replaced by
  `wl.ensure_binds(naz, outdir)` and `variant_glb.binds_from_dir(dir)`.
  `ensure_binds` now requires an explicit `outdir` instead of defaulting to a
  path inside `site-packages` — and creating it there.
- `wlib/__init__` appends to `sys.path` instead of inserting at position 0, so
  the flat module names can no longer shadow the stdlib.

### CLI

- `watchmen --version`.
- Bad paths and wrong file types produce `error: …` lines and non-zero exit
  codes instead of tracebacks; `watchmen fragment` on an unrecognized file no
  longer writes `null` and then crashes.
- `watchmen gendata check` explains what it needs instead of tracebacking when
  there is no game install; missing positional arguments are reported.
- `watchmen --help`, `--version` and `hash` no longer import numpy, Pillow and
  three pickled data tables, and no longer fail when a data table is missing.
- `watchmen char` takes an optional `BINDDIR` and `BAKEDIR`.

### Docs and release hygiene

- Removed the author's private working-tree paths (`D:\…`, `claude/work_*/…`)
  from 12 source files and the docs, and repointed 21 references to documents
  that never shipped at the ones that do.
- Neutral phrasing around DRM: the docs no longer instruct readers to obtain a
  specific de-DRM'd executable. `gendata regdump` — the only path that needs an
  executable with an unencrypted `.text` — says so plainly and states that this
  toolkit neither provides such a binary nor helps produce one.
- `gendata regdump` sanity-checks the recovered class count, because the
  registration-function addresses it uses were reversed from one specific build.
- Added `tests/` (188 tests, no game files needed) and a `CHANGELOG`.
