# watchmen-kapow-toolkit

*Disclaimer: this project was created with the help of generative AI.*

Asset-extraction toolkit for **Watchmen: The End Is Nigh, Parts 1 & 2**
(Deadline Games, 2009 — **Kapow engine**), reverse-engineered from the shipped
game files. Everything is *file-derived*: the pipeline runs on a fresh install
of the game with no captures, memory dumps, or other side data.

Supported sources. The three platforms of a part hold the same asset names
(9,922 files under `extracted/` for Part 2, 12,132 for Part 1, the decoded JSON,
PNG and terrain GLB beside the raw assets included), but what the toolkit
writes from them is not identical — see "Platform support" for what each
set decodes and what it does not:

| Platform | Source |
|---|---|
| PC | `game.naz` archive (or a loose `derived_pc` directory for Part 1) |
| Xbox 360 | XBLA loose `derived_x360` tree, or a `.naz` |
| PS3 | `USRDIR/.../game.naz` |

What it extracts / builds:

- **Textures** → PNG (DXT1/3/5, ATI2, L8, 32bpp, DXT3A on Xbox 360; console
  textures are untiled / unswizzled; every layer and cube face PC has is
  written on console too, most but not all pixel-identical to PC, see
  "Platform support"), with a `sheet.json` beside each texture that holds its
  material switches (two-sided, render type, alpha threshold, normal-map power)
- **Models** → OBJ + textured, bind-pose **GLB** (`extract --glb`), rigged
  when the model is skinned. Models are decoded from their header on PC,
  Xbox 360 and PS3, in both parts; the full-detail LOD is written by default
  (`--model-lod N|all`). Header-decoded models carry normals, tangents and
  vertex colours in the GLB (see "Vertex attributes in the GLB exports")
- **Audio** → WAV (SFX) and one Ogg per music track (console XMA2/MP3 decoded
  via `--vgmstream-cli`), with `audio/sound_info.json` (rate, length, loop
  flag of every sound) and a sidecar per music stream (tracks, cue points)
- **Sound metadata** → `sound_meta.json`: which sound every animation event,
  footstep, attack and hit plays, speak groups and voices, music setups
  (see [`docs/SOUND_META.md`](docs/SOUND_META.md))
- **Ragdoll rigs** → hidden helper nodes in each character GLB and a
  `.ragdoll.json` (see [`docs/RAGDOLL_RIG.md`](docs/RAGDOLL_RIG.md))
- **All misc formats** → lossless JSON (`.fragment`, `.scene`, `.pb`,
  `.sequence`, `.font`, `.particle`, `.terrain`, `.terraincoloringasset`,
  `.grass`, `.detailmesh`), with the font atlas, the terrain colouring map
  and a terrain height / layer map as PNG and, with `--glb`, the terrain
  surface as GLB
  — the Kapow name hash is known (CRC over the name's bytes `& 0xDF`), so
  property keys are named (no unknown key remains in the 906 Part 2
  fragments or the 758 Part 1 fragments). Particle systems are written as the engine's own tree, every
  class and property named; `particlemeta` writes all of them to one folder
  with an index (duration, particle types, textures found in the extract)
  (see [`docs/PARTICLE_FORMAT.md`](docs/PARTICLE_FORMAT.md))
- **Text and subtitles** → `text/<en|fr|it|de|es>/`: every text table (menus,
  tutorials, warnings, key names, in-game and cutscene subtitles) raw, as
  JSON and as CSV; `textmeta` joins the subtitles to the voice lines
  (see [`docs/TEXT_ASSETS.md`](docs/TEXT_ASSETS.md))
- **Levels** → `<level>.level.json`: placements of characters, models and
  volumes with glTF node transforms, the trigger graph, checkpoints, camera
  tours (see [`docs/LEVEL_META.md`](docs/LEVEL_META.md)); `.kpw` save files
  as JSON
- **Navigation data** → `nav/<Level>.nav.json` and `.nav.glb`: the walkable
  mesh and the path-finding graph of every level
  (see [`docs/NAV_DATA.md`](docs/NAV_DATA.md))
- **Script names** → `watchmen scriptdb` reads the game's script name
  database `database.bin`: every script property (`name:type`) and message
  behind the 32-bit keys of the fragments
  (see [`docs/SCRIPT_DATABASE.md`](docs/SCRIPT_DATABASE.md))
- **Builtin script functions** → `wlib/builtins.json`: the 123 functions and
  19 properties a script can call without a node, with signatures and what
  each does (see [`docs/BUILTINS.md`](docs/BUILTINS.md))
- **Character animation** → engine-exact file-only binds for all skeletons, and
  per-character GLBs carrying *every* animation of the character's skeleton,
  including jiggle dynamics (three models, see "Jiggle bones"), face-rigged
  heads with the face poses the game shows during each clip (see "Faces"),
  weapon attachments, and the animation state machine's overlay pages
- **Animation metadata** → `anim_meta.json` and GLB `extras`: states, events,
  transitions, paired clips with placement and timeline (see below), the
  combat rules (damage, timings, reach, counters, combos; see
  [`docs/COMBAT_META.md`](docs/COMBAT_META.md)) and effects, finisher camera
  cuts and rumble (see [`docs/FX_META.md`](docs/FX_META.md))

## Install

```
pip install .
```

Dependencies: `numpy`, `Pillow` (that's all). Optional external tool:
[vgmstream-cli](https://vgmstream.org) for console audio → WAV.

## Quick start

```
# in order: extract -> binds -> the character export (OUT/characters, as `characters`):
watchmen all game.naz OUT

# or step by step:
watchmen extract game.naz OUT            # assets + JSON (add --glb for rigged glbs)
watchmen extract game.naz OUT --model-lod all --language italian   # every LOD; Italian (slot 2)
watchmen binds game.naz OUT/binds        # engine-exact file-only skeleton binds
watchmen characters OUT CHARS game.naz   # one glb per character variant (resumable)
watchmen characters OUT CHARS game.naz --jiggle-model pinned --face-rule legacy   # jiggle and faces as 1.3.0
watchmen characters OUT CHARS game.naz --parts all   # every outfit and weapon at once, as 1.3.0
watchmen characters OUT CHARS game.naz --materials legacy --no-ragdoll   # previous materials, no ragdoll helpers
watchmen characters OUT CHARS game.naz --frame mirrored   # the engine's left-handed numbers (a mirror image), as 1.3.0
watchmen soundmeta OUT OUT/sound_meta.json   # what the game plays, when, for how long
watchmen ragdoll OUT/extracted/.../Medium_Skeleton.model   # one model's ragdoll rig as JSON
watchmen grademeta OUT OUT/grade_meta.json   # the levels' post-process settings
watchmen levelmeta OUT OUT/levels            # one <level>.level.json per level (add names to pick levels)
watchmen savemeta PROGRESS.kpw               # a .kpw save file as JSON
watchmen text game.naz OUT                   # only OUT/text/ (extract writes it too)
watchmen textmeta OUT OUT/text_meta.json     # all strings per language + subtitles joined to the audio
watchmen fxmeta OUT OUT/fx_meta.json         # effects, camera cuts, rumble as one table
watchmen navmeta OUT OUT/nav                 # navigation mesh + graph (extract writes it too)
watchmen particlemeta OUT OUT/particles      # every particle system as JSON + index.json
watchmen scriptdb database.bin db.json --find key_40cb4063   # the script name database
watchmen animmeta OUT OUT/anim_meta.json # pairs, partner placement, events, bone names
watchmen faces OUT FACES                 # cutscene heads + 24 expression poses
watchmen fragment OUT/extracted/.../Gimp.fragment   # lossless fragment -> JSON
watchmen hash SomePropertyName           # Kapow property-key hash
watchmen --version
```

`watchmen --help` lists all commands; `watchmen extract --help` shows extractor
options (`--glb`, `--vgmstream-cli`, `--keep-xma`, ...). `extract` and `all`
exit with the extractor's code (2 for an archive that is not there; `all` then
stops). A command that reads an extract output (`characters`, `faces`,
`charlibs`, `animmeta`, `fxmeta`, `soundmeta`, `grademeta`) stops with exit code 2
when the folder has no `extracted/`. New in 1.3.0:

- `--model-lod N|all` — which level of detail of each model to write.
  Default 0, the full-detail mesh; before 1.3.0 all LODs were merged into one
  file, which `all` still does (per-part proxy slabs are no longer written).
  In 1.3.0 this applied to PC models only; since 1.4.0 console and Part 1
  models are decoded from their header as well and take the same option
  (read from code; the six-set export used the default, `--model-lod all`
  was not run on a console set).
- `--language 0..5|NAME` — language for the localized block entries (the menu
  logo and the `_uk` text assets) written to `extracted/`. Default 0. A slot
  number or a name / code: `english|uk|en`, `french|fr`, `italian|it`,
  `german|de`, `spanish|es`, `danish|dk|da` (the slots were established in
  1.4.0; the Danish slot of the shipped games holds a copy of the English
  one). The `text/` folder holds every language whatever this option says.

`watchmen hash` now folds the name the way the engine does; names containing
digits or punctuation hash differently from 1.2.0.

New in 1.4.0:

- `--frame true|mirrored` on `all`, `extract`, `characters`, `char`,
  `charlibs`, `faces`, `animmeta`, `fxmeta`, `levelmeta`, `navmeta` and
  `ragdoll` (also `WATCHMEN_FRAME`). `true`, the default, writes every GLB
  and OBJ, and the data given in their frame, true-handed: the game as it
  looks. `mirrored` writes the engine's left-handed numbers unchanged, a
  mirror image, byte-identical to 1.3.0's frame (see "Coordinate frame").
- `--names canonical|stored` on `all`, `extract`, `characters`, `char`,
  `charlibs`, `faces`, `particlemeta`, `levelmeta`, `animmeta`,
  `soundmeta`, `fxmeta` and `grademeta` (also `WATCHMEN_NAMES`). The
  archives store some asset paths in a letter case of their own, and the
  engine does not tell the spellings apart. `canonical`, the default, writes
  the 41 asset paths that differ between the six game sets under the one
  spelling `wlib/canonical_names.json` lists for them, spells a folder once
  per export (the table's spelling, else that of the first asset written
  into it; `extracted/`, `textures/`, `models/` and `audio/` agree folder
  for folder), and names the files brought from beside a loose folder in
  lower case, as an archive names its entries. Material names follow. In
  the tables (level JSON, particle index, `fx_meta.json`,
  `grade_meta.json`, `anim_meta.json`, `sound_meta.json`) every string that
  names an exported file is spelled as that file is written, and the string
  the game stores stays beside it under `"stored"` (see "Asset strings in
  the JSON files"). `extract` writes `_canonical_names.json` into the
  output folder (`renamed`: output name → stored spelling; `twins`;
  `folders`) and `stored_name` into the `sheet.json` of a respelled texture
  and the `.model.json` of a respelled model. `stored` writes every path
  and every string as the archive stores it.
- `--jiggle-model solver|pivot|pinned` on `characters` and `char`. `solver`
  is new and is the default: the PhysX soft swing-limit joint with the file's
  constants, looping clips baked as one closed lap (see "Jiggle bones").
  `pinned` gives the jiggle of 1.3.0.
- `--face-rule engine|legacy` and `--no-face-idle` on `characters`. `engine`,
  the default, bakes the face poses the game shows with each clip and gives
  five more characters the game's face-rigged head (see "Faces"). `legacy`
  gives the faces and heads of 1.3.0: a pose guessed from the clip name and
  invented blinks. `--no-face-idle` leaves the game's random idle cycle out.
- `--parts game|all` on `characters` (also `WATCHMEN_PARTS`). `game`, the
  default, shows one outfit and no weapon, as the game does; the other
  outfits and the weapons are switched-off nodes in the same file (see
  "Outfits and weapons"). `all` puts everything in the scene, as 1.3.0 did.
- `--materials engine|legacy` on `extract`, `all`, `characters`, `char`,
  `charlibs` and `faces` (also `WATCHMEN_MATERIALS`). `engine`, the default,
  derives roughness, specular strength, emission, alpha mode and culling
  from the texture sheet as the game's shader uses it (see "Materials");
  `legacy` writes the previous materials, byte for byte.
- `--no-ragdoll` on `characters` (also `WATCHMEN_RAGDOLL=0`): no ragdoll
  helper nodes in the GLBs and no `.ragdoll.json`.
- `extract --flat-music` writes each music stream as one file, as 1.3.0 did
  (default: one file per track); `--music-track-labels`, `--smpl-loops`.
- `--no-vertex-attrs` on `extract` (with `--glb`), `all`, `characters`,
  `char`, `charlibs` and `faces` — write the GLBs as 1.3.0 did: no NORMAL,
  TANGENT or COLOR_0, file winding, and from `extract --glb` only skinned
  models with diffuse-only double-sided materials. For the character commands
  the environment variable `WATCHMEN_VERTEX_ATTRS=0` does the same.
- `extract` also writes **`text/`** (every text asset in every language: raw,
  `.json`, `.csv`; `--no-text` switches it off) and **`nav/`** (per level
  `<Level>.nav.json` + `<Level>.nav.glb`; `--no-nav`). Nothing else in the
  output changes with either.
- New commands (each also in the quick start above):
  - `watchmen levelmeta EXTRACT_OUT OUT_DIR [LEVEL ...]` — one
    `<level>.level.json` per level (see
    [`docs/LEVEL_META.md`](docs/LEVEL_META.md));
  - `watchmen savemeta FILE [OUT.json]` — a `.kpw` save file as JSON;
  - `watchmen text NAZ_OR_FILES_DIR OUT_DIR` — only the `text/` folder, added
    to an existing extract without touching anything else;
  - `watchmen textmeta EXTRACT_OUT OUT.json` — all strings per language and
    the subtitles joined to waves and speak lines; `movies` joins each
    cutscene movie to its subtitle table and line times, with the movie's
    frame count, rate and length when its `.bik` is under `files/` (an
    archive holds the movies; `extract` copies those of a loose-folder
    source, not with `--no-files` or `--no-nav`), `subtitles.rules`
    says when a line is shown, `selection` how each platform picks the
    language (needs `EXTRACT_OUT/text`;
    see [`docs/TEXT_ASSETS.md`](docs/TEXT_ASSETS.md));
  - `watchmen fxmeta EXTRACT_OUT OUT.json [ANIM_META.json]` — effects, camera
    cuts, rumble (see [`docs/FX_META.md`](docs/FX_META.md)); `characters` /
    `animmeta` put the same data into `anim_meta.json` (`fx`, per-state `fx`,
    per-pair `camera_cuts`);
  - `watchmen navmeta FILE_OR_DIR OUT_DIR` — the navigation data of an
    extract output, a game data folder or a single `.hpd` / `.aipathdata`
    (see [`docs/NAV_DATA.md`](docs/NAV_DATA.md));
  - `watchmen scriptdb DATABASE.bin [OUT.json] [--find KEY ...]` — the
    script name database (`data_baked/tnt/production/database.bin`): counts,
    type histogram, whether the file was read to its last byte, a lookup by
    hash or name, the whole table as JSON
    (see [`docs/SCRIPT_DATABASE.md`](docs/SCRIPT_DATABASE.md));
  - `watchmen particlemeta EXTRACT_OUT OUT_DIR [TEXTURES_DIR]` — every
    `.particle` under `EXTRACT_OUT/extracted` as
    `OUT_DIR/<asset path>.particle.json` (the same file `extract` writes
    beside the asset) plus `OUT_DIR/index.json` (`watchmen-particle-meta/1`:
    per file the duration, loop flag and particle types with texture, render
    style, blend mode and module classes; each texture looked up in
    `EXTRACT_OUT/textures`, or in `TEXTURES_DIR`; the byte-exact rebuild
    check). Nothing in the extract is changed (see
    [`docs/PARTICLE_FORMAT.md`](docs/PARTICLE_FORMAT.md), section 6a).
- **`.particle.json` has a new layout** (`format: "kapow-particle/2"`): the
  engine's tree instead of a flat block list, with other key names and value
  forms. No switch back; `kapow_props.parse` still gives the old walk to
  library callers.
- `anim_meta.json` gains the `combat` and `fx` blocks (the format string
  stays `watchmen-anim-meta/2`); an `anim_meta.json` written before them is
  rebuilt by `characters` instead of reused.
- `--no-meta` on `char`. `char` now takes the animation metadata of the
  extract its fragment lies in (clip extras, loop flags for the jiggle bake) —
  the `anim_meta.json` of a `characters` export under that extract when it is
  current, else built on the spot, which takes minutes; `--no-meta` leaves it
  out, as in 1.3.0.
- `char` and `bake` read the game archive: `char FRAG.json VARIANT OUT.glb
  [BINDDIR [BAKEDIR [NAZ]]]` reads the meshes from `NAZ`, `bake CLIPNAME
  BIND.npz OUT.npy [NAZ]` the clip. Without the argument both read
  `01_game.naz` (else `game.naz`) in the current directory. BAKEDIR holds
  `<clip>.npy` files as `watchmen bake` writes them. `bake` matches tracks to
  bones as the character export does for the set: by exact name, and for a
  Part 1 archive (one that holds `Fragments/Enemy/Biker.fragment`) also
  without a leading `BipNN `. A bake holds no
  duration: `char` takes each clip's length from the extracted `.animation`
  file when its fragment lies under an extract, and writes a clip without one
  at 30 fps and says so. Every clip, the walk and run cycles included, is
  written at its header rate (see "Animation metadata"). With
  `--jiggle-model`, `char` takes the jiggle constants from that extract. A `char` GLB has flat materials and no textures,
  tangents, face rig, weapons or ragdoll helpers; `characters` writes the full
  character.
- **Some paths and strings change letter case.** 41 asset paths that an
  archive spells differently from the other part or from another platform
  are written under one spelling (`GarbagePile_01.bmp`,
  `art/props/common/chains/`), the folders of `models/` and `textures/` are
  spelled as in `extracted/` (`models/art/environments`, where the models
  store `Environments`), and the `.hpd` and `.bik` files of a loose-folder
  source lie under `files/data/` in lower case. In the level JSON, the
  particle index and the fx, grade, animation and sound tables a string
  that names an exported file has the letter case of that file; a reader
  that needs the game's own string takes it from `"stored"` in the same
  record. `--names stored` keeps every path and string as stored;
  `_canonical_names.json` lists what was respelled. Extract into a new
  folder: on a case-insensitive file system an existing folder keeps the
  spelling it has.
- **Extract textures again.** PC normal maps written by 1.3.0 and earlier have
  their X and Y channels swapped, and there is no switch that brings the old
  PNGs back or repairs them: nothing in a PNG says which version wrote it.
- **Extract audio again.** 76 of the 2,921 Part 2 PC sounds were written at
  the wrong rate or 4 bytes late, and multi-track music was one scrambled
  file; an `audio` folder from 1.3.0 keeps the old files until `extract` is
  run again (`--no-textures --no-models --no-files --no-extract-all` limits
  the run to audio: about two minutes for Part 2 PC).
- **Texture sheets.** Each character part wears the sheet its outfit selects,
  and `extract --glb` writes additive and subtractive layers by their blend
  type (see "Texture sheets and blend types"). No switch back.
- **Textures are looked up by the path the model stores.** Six character GLBs
  and 17 extracted character models get other textures than in 1.3.0,
  Rorschach's mask among them; there is no switch back, because the old pick
  depended on the order the file system listed folders in.

The changes that affect output are listed under "Behaviour changes" in
[`CHANGELOG.md`](CHANGELOG.md), each with what brings the 1.3.0 result back
and what does not.

Without installing: `python3 watchmen.py <command> ...` from this directory
works identically.

## Coordinate frame

The engine is left-handed: +Y up, characters face +Z, and a character's
left hand is at −X. glTF is right-handed. Up to 1.3.0 the toolkit wrote the
engine's numbers unchanged, so every viewer showed a mirror image: a wall
sign read backwards, and the bone called `L Hand` was on the right-hand
side of the picture.

Since 1.4.0 the default output is **true-handed**: x = −engine x, +Y up and
"facing +Z" as before. Text reads the right way round, a character facing
+Z has its left hand at +X, and the bone names `L` / `R` say what they are.
Nothing has to be mirrored and no node carries a negative scale: the data
itself is reflected — positions, normals, tangents (with their sign),
inverse bind matrices, joint and animation transforms, triangle winding.
In Blender (whose importer turns glTF's (x, y, z) into (x, −z, y)) a
character stands on +Z, faces −Y, towards the front view, and has its left
side at +X.

Blender's glTF importer (checked: 5.2.2, io_scene_gltf2 5.2.40) does not
import `animations[i].extras`: the actions arrive under their clip names
without custom properties. Read the extras from the GLB's JSON chunk, or run
`tools/blender_attach_extras.py`. In Blender the character's origin is 1 m
above its soles (feet at z ≈ −1.0).

| | `--frame true` (default) | `--frame mirrored` |
|---|---|---|
| GLB, OBJ | x = −engine x | engine numbers, as 1.3.0 |
| marker | `coordinate_frame: "right-handed-true"` (GLB: `asset.extras.watchmen`; top of `anim_meta.json`, `*.ragdoll.json`, `*.level.json`; a comment in an OBJ) | none: **a file without the key is mirrored** |
| `anim_meta.json`: `game_pivot`, `interact`, pair `placement` | true frame | engine numbers |
| `*.ragdoll.json`, ragdoll extras | true frame (limits unchanged) | engine numbers |
| `*.level.json`: `gltf`, `forward`, `yaw_deg` | true frame | engine numbers |
| `*.nav.glb` | true frame | engine numbers |
| level `world.pos` / `world.quat`, `*.nav.json`, effect offsets and camera parameters in `anim_meta.json`, particle / fragment / skeleton JSON | engine coordinates | engine coordinates |

Values the toolkit copies from the game files stay in engine coordinates in
both frames and are labelled so; to use one with a true-frame GLB negate x
of a position or direction and turn a quaternion (x, y, z, w) into
(x, −y, −z, w). `--frame mirrored` output is identical to what the same
toolkit writes without the frame conversion: the engine's numbers, as 1.3.0
placed them. Everything else in 1.4.0 (materials, attributes, parts) is the
same in both frames. Do not mix the two frames in one
scene; a resumed `characters` run rewrites files it finds in the other one.

## Animation metadata

`watchmen characters` also writes `CHARS/anim_meta.json` and embeds the same
facts in each GLB's `extras`: the real bone names and parents, per-clip loop
flag and events (hit, kill-partner, camera cut … with their trigger kind and
time), transitions with sync markers, which clip pairs with which for
counters, finishers and throws, where the partner stands, and when it is
anchored and released. All of it is read from the game's AnimationClass
fragments and the clips' root tracks; names and ids are the executable's own
(`wlib/engine_enums.json`). Every clip is written at its header rate,
(keys − 1) / duration; the engine plays a state's page at controller speed ×
slot `speedFactor` × weight / duration (read from code, 0x5b5175), which has
no velocity term, and the slot speed factors are in each clip's extras
(`speeds`). The walk and run cycles are not sped up (1.3.0 wrote them 2.3 /
2.6 times faster). The format is `watchmen-anim-meta/2`;
[`docs/ANIMATION_META.md`](docs/ANIMATION_META.md) describes it and lists what
changed since format 1 (written only by an untagged development build).

Since 1.4.0 the same table carries two more blocks, each with its own format
marker, without changing any existing key:

- `combat` (`combat_format`): per attack state the attack class, base damage
  times modifier per character and weapon class, the PRE_IMPACT / IMPACT /
  BRANCH timings, reach, the damage pose and what the defender can do; per
  pair the rule that starts it (counter, finisher, throw, bull rush) and its
  damage (a throw's is ragdoll contact damage, with the rule that computes
  it); the combo databases, character and AI definitions with their effective
  damage modifier, weapons and the fixed rules with their constants (the hit
  formula and its receiving side, the area attacks, sweep stepping, who may
  attack when). [`docs/COMBAT_META.md`](docs/COMBAT_META.md).
- `fx` (`fx_format`): the argument slots of every event, per state the impact
  effects, camera cuts, rumble and slow motion, per pair the camera cuts on
  the pair's clock, and the effect database with the rule that picks an
  effect for a hit. The finisher and counter cameras are procedural: there
  are no camera tracks, and `fx_meta.cut_camera()` places a cut from the two
  characters' positions. The camera then stays where the cut put it; only
  its aim follows the looked-at point. [`docs/FX_META.md`](docs/FX_META.md).

In the GLBs a clip's pair entries carry the camera cuts and the pair trigger,
the events their argument slots, and `asset.extras.watchmen.fx_attachments`
lists the emitters and light flashes the game hangs on the character's
joints. The per-state blocks stay in `anim_meta.json`.

## Levels, text, navigation

`watchmen levelmeta OUT OUT/levels` writes one `<level>.level.json` per level:
every fragment instance with its world transform, character / model / volume
placements with the glTF node transform that places a toolkit GLB there, the
condition / action graph with resolved targets and enum names, checkpoints
with their restore scripts, camera tours and movies. For every placed
character it says what the file fixes about its model and weapon (fixed, or
a candidate set with the engine's least-used rule), its AI start state and
the actions that wake it; it also lists the combat presets the level
switches to, the cube maps, the lights, the waypoint chain with the links
the engine builds at load, the culling groups and the stream blocks. Place every entry with
its `gltf` transform and the level stands as the game shows it; `world` is
the same placement in engine coordinates. (With `--frame mirrored` the
`gltf` transforms are the engine's numbers and the assembled level is a
mirror image, as the GLBs of that frame are.)
[`docs/LEVEL_META.md`](docs/LEVEL_META.md).

`tools/blender_import_level.py` does that in Blender: run it from the
Scripting workspace and pick a `<Level>.level.json` of an export, or
`blender -b --python tools/blender_import_level.py -- LEVEL.json --save
OUT.blend`. Every model GLB is imported once and every placement is a
collection instance of it, so a level of 3,500 placements stays light;
the terrain, the sky, the navigation mesh and the placed characters (in
their idle pose; the variant and outfit the level file fixes, the
candidates handed out in turn where the game chooses at run time) are
added, sorted into collections, and each instance carries the node id,
fragment and model path of its record. Bordello: 3,070 instances from 264
library collections in 66 s, a 312 MB file, 2.6 GB of memory at the peak
(Blender 3.6.0, two cores). A level that is already in the file is
refused. The records a level file marks with `host_offset_copy` (ten
background characters of StreetsOfRiot, 50 m above the street) go into a
switched-off collection, `<Level>` > `Host-offset copies`: whether the game
draws them is not established. Blender 5.2.2 on Windows, background mode
(measured): PC Part 2 Bordello imports as 3,070 instances from 264 GLBs in
40 s into a 260 MB file, NightClub as 3,811 instances from 277 GLBs in 42 s
into a 257 MB file, both without an error; every prop instance sits within
0.02 mm of the `gltf` placement of its level record.

`extract` writes `OUT/text/<en|fr|it|de|es>/`: each text table raw, decoded
(`.json`) and as `.csv` (UTF-8 with a byte-order mark, so that Excel shows
the accents). `watchmen textmeta` joins the in-game subtitle table
to the audio: a playing sound finds its subtitle by the file name of its
wave. `watchmen text game.naz OUT` adds the folder to an extract made by an
older version. [`docs/TEXT_ASSETS.md`](docs/TEXT_ASSETS.md).

`extract` also writes `OUT/nav/`: per level the Kynapse path data as
`<Level>.nav.json` (engine coordinates, like the level export's `world`) and
`<Level>.nav.glb` (the walkable mesh as triangles, the graph as lines, in
the frame of the model exports, so it overlays them).
A loose-folder source (Part 1 on PC and Xbox Live) keeps the path data in
the sibling `data/` and `data_baked/` folders; `extract` copies it to
`files/` first, with the 12 `.bik` movies of `data/Art/cutscenes` (568 MB),
which `textmeta` reads for the movie lengths. The data lies about 1 m above the floor; the level export links the path
objects (doors, gates) to their level nodes by their id, with the position
as cross-check.
[`docs/NAV_DATA.md`](docs/NAV_DATA.md).

## Asset strings in the JSON files

The game names its assets by path (`/Art/Effects/Noise.bmp`) and reads such
a string without regard to letter case, so the string a fragment stores
often differs in case from the path of the asset it names. The export has
one spelling per path (see `--names`), and two kinds of JSON:

- **Tables written from an export** — the level JSON (`levels/`),
  `particles/index.json`, `fx_meta.json`, `grade_meta.json`,
  `anim_meta.json`, `sound_meta.json`. A string that names an exported file
  is spelled as that file is written: `textures/<path>/` for a texture,
  `models/<path>.obj` and `.glb` for a model, else the file below
  `extracted/`, `audio/`, `files/data/` or `files/` (a cutscene movie is
  named without the game's `data` folder: `/Art/cutscenes/Cutscene10A.bik`
  is `files/data/art/cutscenes/cutscene10a.bik`). The string the game
  stores is kept in the same record under `"stored"`, only where it differs:

  ```json
  {"model": "/art/characters/rorschach/models/Rorschach_Dry.model",
   "stored": {"model": "/Art/Characters/rorschach/models/Rorschach_Dry.model"}}
  ```

  For a list `stored` holds the list as stored, for a map whose keys are
  respelled `{key written: key stored}`. `asset_names` at the top of the
  table gives the spelling (`export`) and the number of strings respelled.
  In a level file the movie path inside a graph label (`MOVIE <path>`) is
  respelled as well.
  With `--names stored`, or for an export made with it, the tables hold
  the stored strings and have no `stored` and no `asset_names`.
- **Decoded asset data** — every JSON under `extracted/`, the per-file
  JSON under `particles/`, `config` / `config_tree` of a `.nav.json`, the
  `overrides` of a texture's `sheet.json`. These are the asset, value for
  value, and keep its strings. Look a string up without regard to case:

  ```python
  import sys; sys.path.append("wlib")
  import canonical_names
  canonical_names.resolve("OUT", "/art/effects/NOISE.bmp")   # 'textures/art/Effects/Noise.bmp'
  index = canonical_names.ExportIndex("OUT")                 # for many strings
  index.find("/Art/Props/Crate.model")    # ('models', 'art/props/Crate.model') or None
  index.spell("/Art/Props/Crate.model")   # '/art/props/Crate.model'
  ```

## Library use

```python
import wlib                     # puts the flat modules on sys.path
import watchmenlib as wl        # the facade — one import for everything

j = wl.fragment_json_file('X.fragment')          # lossless fragment JSON
binds = wl.ensure_binds('game.naz', 'OUT/binds') # file-only engine-exact binds
pal, dur = wl.bake('run_cycle', binds['female']) # (F,NB,3,4) engine palettes
wl.build_variant_glb('Gimp.fragment.json', 'Gimp2', 'out.glb',
                     binddir='OUT/binds')
```

(The three lines after the imports need game files; `import wlib` /
`import watchmenlib` on their own do not, and have no side effects on your
process — no `sys.argv` rewriting, no recursion-limit changes, and the package
directory is appended to `sys.path`, never prepended, so it cannot shadow the
stdlib.) Once called, some modules keep state in module globals: the bind
`bake_v4` last loaded, the folder spellings of the current `extract` run
(`canonical_names`), the block order and console platform of the archive being
extracted. Run one export at a time per process.

`wlib/watchmenlib.py` documents the full facade. Notable standalone modules:
`wlib/anim_state_machine.py` (animation state-machine loader and interpreter;
`python3 wlib/anim_state_machine.py FRAG.json --seed N` seeds its one random
choice, the blend node per layer),
`wlib/engine_schema.py` (441-class engine serialization schema recovered from
the executable), `wlib/engine_enums.py` (the engine's enum tables),
`wlib/jiggle_d6.py` (the three jiggle models; `SoftLimitJoint` steps the
PhysX D6 joint's soft swing limit), `wlib/exact_math.py` (the solver's
trigonometry, nearest rotation and sums in plain float arithmetic: the same
bits on every platform),
`wlib/kapow_fragment.py` (lossless `.fragment` parser, 906/906 files
round-trip).

## Jiggle bones (breasts, belly, hair)

`watchmen characters` bakes the game's secondary motion into the clips of
skeletons that have jiggle bones, and `watchmen char` does when
`--jiggle-model` is given. There are three models
(`--jiggle-model solver|pivot|pinned`, or
`jiggle_d6.apply_jiggle(P, fps, bind, model=…)`):

| model | what it is | constants |
|---|---|---|
| `pinned` (the default up to 1.3.0) | the model of 1.2.0, bit-identical: a spring-damper about the bone origin, with gravity sag | the file's values through a softening formula |
| `pivot` (1.3.0) | the engine's geometry — swing about the parent bone origin, bone position and rotation both written back, clamp in metres, one frame of delay — with a linear spring-damper | fitted to in-game captures |
| `solver` (new in 1.4.0, the default) | the same geometry, stepped with PhysX 2.8.1's own arithmetic for the joint's soft swing limit, at 1/60 s | the `PhysicsWorld` values of the extract's `GameEssentials` fragment only (equal in the six shipped sets; the shipped values when `char` has no extract, and with a `WARNING` line when the fragment cannot be read) |

In the game the jiggle joint has no drive: the file's spring and damping are
the joint's soft swing limits, which PhysX solves as one one-sided constraint
row per step. `solver` reproduces that row; nothing in it is fitted. Against
the in-game captures (one measurement by the implementer, not repeated
independently; the captures are not shipped) it matches the capture-fitted `pivot` model on the
breasts (rotation error 3.02° / 2.70° rms left / right, `pivot` 3.15° /
2.73°, `pinned` 5.38° / 4.93°) and is somewhat behind it on the belly (2.35°,
`pivot` 1.99°, `pinned` 4.25°; one physics step per captured frame, each
track started at rest). It costs more than `pinned`: on a full export the
bake took 7 to 14 s for each of the three skeletons that have jiggle bones,
once, then cached.

`solver` is the default. `--jiggle-model pinned` gives the jiggle of 1.2.0
and 1.3.0 byte for byte; `pivot` is unchanged from 1.3.0 too. Each model keeps its own cache
directory (`CHARS/_bake/<skeleton>_j_<model>-<mode>-<hash>`; the hash also
covers `PhysicsWorld` values other than the shipped ones), so nothing has to be
deleted when you switch. A resumed export keeps a GLB only when
`CHARS/_glb_options.json` records it as written with the options of this run
(frame, jiggle model and constants, face rule and idle cycle, parts,
materials, names, vertex attributes, ragdoll, the `WATCHMEN_*` switches and
the animation table's revision) and it is not older than the newest raw bake
of its skeleton; any other GLB is written again, the log says why, and how
many were kept. `faces` keeps its GLBs by the same record
(`FACES/_glb_options.json`). A cached raw bake records the bind and the clip
bytes it was baked from (`bind_sha`, `clip_sha`) and is baked again when
either differs, or when it was cached without them. A jiggle memo records the
rate it was solved at.

How the solver bakes a clip. A looping clip (the game's `loop` flag, from the
animation metadata) is played until the jiggle repeats from lap to lap, or for
12 s, and then one more lap is recorded and closed, so the clip loops without
a jump (measured once, wrap discontinuity 0.00–0.03° where the body pose itself
closes; 1.4–4.9° with `pinned`, the 1.3.0 default). A clip that does not loop gets a 0.25 s lead-in at
the velocity of its first frame interval instead of starting at rest. Clips of
fewer than four frames are left alone. `watchmen char` has the loop flags only
when it finds the extract (see `char` in `watchmen --help`).

The `solver` bake is the same bit for bit on every platform: it uses float
`+ - * /` and `sqrt` only and takes its trigonometry from `wlib/exact_math.py`,
not from the C library, numpy's LAPACK or `sum()`. PhysX does not execute an
anchor rotation below 0.16° per step, so on a slow clip (most idles) the last
bit of one value decides a step and the bone ends up millimetres to
centimetres elsewhere: written with `math.sin`, `sum()` and
`numpy.linalg.svd` the same bake differs between Windows / Python 3.14 and
Linux / Python 3.10 on 107 of the 389 Gimp and Dominatrix clips of PC Part 2,
by up to 7.3 cm (measured). Neither result is the wrong one; on those clips
the game's own result depends on its frame times in the same way. With
`exact_math` the palettes the six-set export baked on Windows equal, bit for
bit, the ones Linux / Python 3.10 computes from the same raw bakes (1,773 per
Part 2 set, 1,469 per Part 1 set; measured).

Limits of the bake. In the game the result depends on the frame rate (a frame
takes 0 to 3 physics steps); the bake takes exactly one step per 1/60 s. What
the game played before a clip is not known, so every start is an assumption.
A clip is baked as a loop when a looping state plays it, as its main clip or
as a blend member (`EN4_COM_MOV_run_cycle`, `EN2_COM_MOV_strafe_left` among
them). Hair uses
the same code with its own file constants and has not been compared with the
game: there is no capture of it.

## Faces

A character's head is a separate model with its own skeleton (jaw, lips,
cheeks, brows, eyelids) and its own small animation class. It is not keyframed
and not driven by the body's states: the game feeds it four inputs — the
character mode, "attacking" on every frame of an attack state, a hit with its
damage pose, and start / stop speaking — and the face class answers with
one-frame poses: an idle pose, an attack face, hit faces held for 0.75 s
unless the face class leaves earlier (a `STUN_MIDDLE` hit on a silent enemy
changes to `Retreat` on the next update; an attacking character changes to
`Attack`), a dead face, each easing in over 0.21 s (0.37 s for the Twilight
Lady / Dominatrix knock-down face).

`watchmen characters` reproduces that. `anim_meta.json` gets a `face` block
(the face classes, which body class uses which, and for every body state and
pair the inputs the game sends and the face track that follows), and every
body clip of a character with a face rig carries that track as keys on the
face bones, with the details in `extras.watchmen.face`. What is random in the
game is treated as such: the idle cycle (a blink for Twilight Lady and the
Dominatrices, a brief sneer for the male enemies) is baked as one seeded
instance, each idle stretch starting in a seeded random member as in the
game, and can be left out with `--no-face-idle`; speech is not baked: its
length is that of the wave played, but which wave and voice is drawn at play
time, and the line can be suppressed.

Thug, ThugFast, ThugBig, Gimp and GimpGagBall get the head the game attaches
to them (chosen from the head collection by the variant's head model type, with
the texture sheet that collection names) in place of the static head their
fragment lists. Heavy, Twilight Lady, the Dominatrices and Nite Owl had face
rigs in 1.3.0 already. Rorschach has no face controller: his mask is part of the body.

`--face-rule legacy` gives the faces of 1.3.0: one pose per clip guessed from
the clip name, invented blinks, static heads on the five characters above.
[`docs/ANIMATION_META.md`](docs/ANIMATION_META.md) describes the face block.

## Outfits and weapons

A character collection holds complete outfits under one name: 18 for the
Heavy, 11 for KnotTop_Medium, 11 for KnotTop_Large, 9 for KnotTop_Small; the
other variants have one. The game hands them out in turn — the least-used
one, first in the collection's list, nothing random, unless a placement asks
for a priority that a member has (`watchmen levelmeta` says for every
placement whether its model is fixed) — and attaches at most
one weapon, none unless a spawner or a pick-up sets one. A character GLB
therefore shows outfit 1, unarmed (Twilight Lady keeps her whip, which is
part of her model).

Everything else is still in the file:

- models that every outfit wears identically are in the main mesh;
- every other model is a node `OUTFIT <k> <model>`, once per outfit `k` that
  wears it, with that outfit's texture sheets (jacket colour, buttons,
  T-shirt). The nodes of outfit 1 are in the scene;
- the other outfits' nodes and the weapons (`WPN_<model>`) hang under a node
  `alternatives`, which belongs to no scene.

Viewers show the scene only. Blender imports the rest into the collection
"Orphan Nodes", switched off: enable it, hide the `OUTFIT 1 …` objects and
show the `OUTFIT k …` objects to see outfit `k`; show one `WPN_…` object to
arm the character (it is skinned to the bone `Attach RHand`).
`asset.extras.watchmen.parts` lists the outfits, their nodes and sheets, and
the weapons with their class (`BASH_1H` / `BASH_2H`); each clip's
`weapon_use` says which class it is played with. The face rig is that of
outfit 1. `--parts all` writes every model and weapon into the scene, as
1.3.0 did.

`Dominatrix_3.glb` is not a variant of the shipped game (its fragment has
1, 2 and 4–10): it is a reconstruction after pre-release screenshots, marked
in `asset.extras.watchmen.reconstruction`. `WATCHMEN_NO_SYNTH=1` leaves it
out.

**Eyelashes of the generic female heads** are restored content under the
same switch. The lash strips of `FemaleHead_White1`,
`FemaleHead_White1_Gimp`, `Girl_Head_White` and `FimaleGimpMask` (submesh
`EyeBlow`, 72 vertices: an upper and a lower strip per eye) store their UVs
in a corner of the `EyeBlow` texture that is fully transparent (u 0.0033 to
0.0620, v 0.3914 to 0.4609 from the top), so the sheet's alpha test discards
every pixel and the game shows these heads without lashes; the bytes are the
same in the PC, PS3 and Xbox 360 files (measured). `TwilightLady_Head` has
the same two strips on a texture with the same painting, mapped onto the
lashes: her lower strip has the same triangle list, and her upper strip
contains the 18 upper vertices. Each strip of the small layout is that strip
scaled down and moved, so the toolkit writes `uv' = scale × uv + shift` per
strip — upper 11.7691 and (0.4736, −4.4107), lower 11.5133 and (−0.0358,
−4.5707), a least-squares fit to her UVs of the matched vertices (rms 0.2
and 1.8 texels of the 128-pixel texture). With it the strips cover 95.6 % of
the painted texels (her own strips: 88 %; the best single scale-and-shift of
the whole layout: 55 %). Why the files hold the small layout is not
established. The restored UVs are in the head's OBJ and GLB, in
`faces/<head>.glb` and in the character GLBs that wear such a head (in the
Part 2 sets `Dominatrix_1`, `_2`, `_3` and `_9`; no Part 1 model has the
layout). They are marked: `reconstruction.eyelash_uvs` in the head's
`.model.json` and in `asset.extras.watchmen` of a face or character GLB,
with the stored UV range and the two transforms. `WATCHMEN_NO_SYNTH=1`
writes the UVs as stored and no mark.

## Texture sheets and blend types

A texture carries one or more sheets: named sets of material parameters
(render type, alpha threshold, two-sided, blend type, specular, UV scroll)
that can also replace single layers with another texture. A model wears the
first sheet unless the fragment that places it names another one per model
slot. `sheet.json` in each texture folder has the first sheet's values at
top level and every sheet under `sheets`. `textureHasAlpha` there is the texture header's
alpha flag, which is what switches the game's alpha test on.

The layer PNGs of a texture are named by the layer's slot in the file:
`diffuse`, `normal`, `specMap` (specular colour), `glow`, `height` (the
parallax map), `fallOff`, `ambOcc`, `specSize` (specular power); `fallOff`
and `ambOcc` occur in no shipped texture. 1.3.0 named a glow map
without a specular map `specMap` and a height map `specSize` (15 + 10
textures in Part 2, 23 + 24 in Part 1) and used them as such in the
materials. `sheet.json` of a cube map states the face order
(`cubeFaceOrder`: +X, −X, +Y, −Y, +Z, −Z) and that of an animated texture
its animation block (`animation`) and, where every frame is shown for a
fixed time, `frame_ms`.

- `characters`: each part takes the sheet of its own outfit. A material on
  another sheet than the first is named `<texture> [<sheet>]`.
- `extract --glb` and OBJ/MTL: the first sheet, including its layer
  overrides.
- Blend types (render types "with blending", "sky box", "sprite", and a
  standard or fall-off sheet with `opacity` below 0.99, which the game draws
  blended):
  `standard` is glTF `BLEND`; `subtract` (Rorschach's ink blots) is written
  as black ink with alpha, exact over white; `add` as an emissive layer, an
  approximation (where the blend reads the source alpha, SRCALPHA / ONE,
  the sheet's opacity is its `emissiveFactor`: the sun rays of three sky
  models at 0.6); `manual` (explicit Direct3D factors) as one of these when
  it equals one, otherwise untouched. `extras.watchmen` on the material
  holds the engine's state (`blend`, `src`, `dst`, `op`). OBJ/MTL has no
  blend equation and links the raw layer.
- UV scroll and texture animation are not written to glTF; the values are in
  `sheet.json`.

## Materials

With `--materials engine` (the default) a GLB material is built from the
texture sheet the way the game's colour shader uses it
(`wlib/materials.py`):

| glTF | from the sheet |
|---|---|
| `roughnessFactor` (a roughness texture with a specSize layer) | `specularSize` = the highlight exponent n: (2 / (n + 2))^0.25. Where the game draws no highlight: 1.0, and no roughness texture |
| `KHR_materials_specular`, and `KHR_materials_ior` above a reflectance of 0.04 | `specularPower` × specular layer; 0 = no highlight (`specularFactor` 0) |
| `metallicFactor` 0 | the game has no metal path |
| emissive texture (+ `KHR_materials_emissive_strength`) | `selfIlluminance` × colour × glow layer, only where the sheet's `selfIlluminance` is above 0: the engine multiplies the glow layer by it, so a glow map on a sheet with 0 (a lamp's "off" sheet) is not written as emission |
| `alphaMode` | the render list the engine puts the sheet in: `BLEND` only for render type 1, or for `opacity` < 0.99 on a standard, fall-off or sky-box sheet (render type 0, 10 or 7; with the opacity as base-colour alpha — a sky sheet with opacity 0, as `skyflash` and `moon_01` of Part 1, is an invisible layer); otherwise `MASK` at `alphaThreshold` / 255 when the diffuse texture has alpha (hair too); otherwise opaque. "Has alpha" is the texture header's flag (`sheet.json` `textureHasAlpha`; the pixels when an older extract lacks it). Vertex alpha multiplies the texture alpha but never selects `BLEND`; a material used with varying vertex alpha carries `extras.watchmen.vertex_alpha`. Sky-box and sprite sheets, and textures without a `sheet.json`, keep `BLEND` on vertex alpha |
| `doubleSided` | `twoSided` |
| `extras.watchmen.sheet_values` | the sheet's own numbers, incl. the rim ("falloff") parameters glTF cannot express, the blend triple, the normal-map switch and power, the wet-surface pair (`fresnelPower`, `maxReflection`) and the layer `overrides` |

Both corrections for the game lighting display-encoded values are applied.
In the one comparison made — renders in three.js and Blender against the
game's lighting equation — the result was 3 to 17 % closer than the
previous materials on skin, clothing, latex and hair, not uniform over
light directions, and two small accessory materials came out slightly
worse. The noise floor of that comparison was not established, so the
figure is an indication, not a measured gain. The game's rim
light and display-space lighting have no glTF equivalent. The game lights
in display space: albedo × light is computed on the display values of the
textures. Measured on one captured frame (`docs/MATERIAL_COMPARISON.md`):
the display-space product gives skin (0.188, 0.134, 0.107) against the
game's (0.187, 0.133, 0.106), where the same product in linear light gives
(0.119, 0.079, 0.058) before the rim term; the sampler's sRGB state was not
read, so this rests on the fit. When a render is compared with the game,
use Blender's Standard view transform: it applies the sRGB curve only,
while Filmic and AgX add a tone curve the game does not have. Strongly specular
materials (latex, armour) reflect a viewer's environment, which the game
does not have; under a bright uniform world they look greyer than in game.
three.js and Blender 5.0.1 import both extensions. Blender 3.6 (glTF
importer `io_scene_gltf2` 3.6.27) does not use `specularFactor`: for a
material without a specular texture it computes Specular from the specular
colour and the IOR alone, which gives 0.5 at IOR 1.5 (read from the
importer's source; the fully rough rule below is what keeps a material
without a highlight matte there). A viewer that ignores the extensions
(F3D for one) shows a plain dielectric with the right roughness, so every
highlight has the right width but the default strength. A material the game
draws **no** highlight on (`specularPower` 0 without a cube reflection, or a
specular layer that is black: hair, brows, lashes and the like) is therefore
written fully rough — `roughnessFactor` 1.0, no roughness texture — and
stays matte in such a viewer too; with the extension its lobe is off and
the roughness is not seen, so nothing changes there (a Blender render of a
character before and after is identical). In the OBJ's MTL such a material
gets `Ns 0` and no `roughnessEngine.png`. `--materials legacy` writes the
previous materials.

The MTL follows the same rules where the format allows: `d <opacity>` after
`map_d` for a standard, fall-off or sky-box sheet with `opacity` below 0.99; a glow
layer as `Ke <colour × selfIlluminance>` + `map_Ke` where the first sheet's
`selfIlluminance` is above 0, and only named in a comment where it is 0 (the
comment says how many other sheets of the texture light it). Two things an
OBJ importer does differently from the GLB (measured in Blender 5.2.2, one
material each): `Ns 0` with `Ks 0 0 0` imports as roughness 1.0 with
specular 0 (Blender's rule is roughness = 1 − sqrt(Ns / 1000)); and
`map_Ns roughnessEngine.png` is linked into Roughness with the image tagged
**sRGB**, so the stored value is decoded before use (88 / 255 = 0.345 would
arrive as about 0.098; inferred from the colour-space tag, not measured by a
render). Set the image to Non-Color after import, or use the GLB, whose
roughness texture is read as data. On that material (`Bottle_02` of
`Bottle_01.model`) the PNG value (0.345) and the GLB's `roughnessFactor`
(0.2869) also differ before any colour-space effect, and this holds for
every material with a highlight: `roughnessEngine.png` is the roughness of
the sheet's exponent alone, (2 / (n + 2))^0.25 with n = `specularSize`
142.1, which is 0.343; the GLB material widens the exponent by the
display-space factor of its diffuse texture first (`materials.py`; 2.062
for a mean diffuse of 0.235), (2 / (2.062 n + 2))^0.25 = 0.2869 (read from
code, measured on that material).

Material numbers differ a little between the platforms of a part, because
they are computed from the texture layers and the Xbox 360 archives hold
some layers with other texels or in another format than PC and PS3 (for
`Archie_MainBody02` the diffuse and specular layers differ in 37 % and 29 %
of the texels by 0.7 and 0.8 of 255 on average; `Cops_Head1` has its
`specSize` layer as DXT1 where PC and PS3 have L8), with the `sheet.json`
equal. On the six-set export `KHR_materials_ior`, `specularFactor` or
`roughnessFactor` of at least one material differ between PC and Xbox 360
in 166 of 1,088 model GLBs of Part 1 and 99 of 738 of Part 2 (largest
`specularFactor` difference 0.14, `roughnessFactor` 0.005); between PC and
PS3 they are equal in every GLB (in three Part 1 GLBs the copied sheet
value `reflectionType` of `Ground_PrissonFloor_01` differs, as the PS3
sheet stores it). Recomputed from each platform's own layers, the two
materials above give each platform's GLB values (measured).

A model made of several rigid parts (a car and its tyres, a helicopter and
its rotors, the rooms of the mansion) stores each part's vertices in the
part's own space. OBJ and GLB hold them in model space (the part's stored
position and rotation applied, then its parents'); 1.3.0 wrote every part at
the model origin. `<model>.model.json` lists the parts (`parts`: name,
parent, stored position and rotation, pivot-book index, shadow-hull group of
each submesh) and says `part_transforms_applied`.

`extract` also writes `<model>.model.json` beside each model (LOD switch
distances and fades; how many shadow hulls and occluder meshes were left
out). Models with particle emission meshes list them there as
`particle_surfaces`. `watchmen grademeta` lists the levels' post-process
settings; each node says whose camera it grades (`_iplayerctrl`: 0 / 1 =
that playable character, 2 = both). `formula` states what `enableFilters`
gates (bloom filter, grade, gamma, noise — not depth of field or
anti-aliasing) and that fog always comes from the level's first enabled
node. `platform_adjustment` gives what the game's options add to a node's
brightness, contrast, gamma and saturation on PC, Xbox 360 and PS3 (on PC at
the middle setting: +0.05, +0.11, +0.12, 0). The settings a player actually
has are not known, so the node values are written as stored.

## Ragdoll

Each character GLB carries the ragdoll the game uses for it — 17 rigid
bodies and 16 joints, read from the model in slot 0 of the variant — as
helper nodes under a node `ragdoll` outside the scene (`RB.<bone>.<i>`
proxy meshes skinned to the bones, `RJ.<child bone>` empties at the joint
frames), and `<Variant>.ragdoll.json` holds the whole rig. Blender shows the
helpers in "Orphan Nodes", switched off, next to the outfit and weapon
alternatives. The rig is in the GLB's frame: in the default true frame
every position and frame is the file's value reflected, and every limit
has the file's value. [`docs/RAGDOLL_RIG.md`](docs/RAGDOLL_RIG.md) has the format,
the Blender axis mapping and settings that work for a rigid-body setup.
`--no-ragdoll` leaves both out. Xbox 360 and PS3 extracts give the same rig
(the Part 2 sidecars are byte-identical to PC). The standalone Part 1 (PC,
Xbox Live) stores the rig in an older header layout, which is read too (80
of 80 rigs on both sets). A GLB without a rig says so in
`asset.extras.watchmen.not_decoded`.

## Sound

`extract` writes one file per music track with a sidecar (tracks, cue
points, the game's track states) and `audio/sound_info.json` (on console
too: each record says where its length comes from, `duration_source`).
Console sounds stay `.xma` / `.mp3` unless `--vgmstream-cli` is given.
`watchmen soundmeta` (and `characters`, as `sound_meta.json`) writes what
the game plays: per animation state the sound, speech and footstep events
with the definition, its variation rule, waves and durations; the footstep
table by character type and ground surface; attack and hit sounds; speak
groups per character with voices; music setups.
[`docs/SOUND_META.md`](docs/SOUND_META.md) describes the table. A clip that
starts one fixed voice line has the talk baked into its face track
(Twilight Lady's four cattle-prod counters). Every wave of a speak voice
carries `subtitle_key`, the key of its subtitle rows in the `textmeta` table.

## Vertex attributes in the GLB exports

The GLBs carry the mesh buffers' own per-vertex data (new in 1.4.0):

| Attribute | Source (PC vertex formats 5 / 6) | Written as |
|---|---|---|
| NORMAL | half3 @12 | unit VEC3 |
| TANGENT | tangent half3 @28 (∂P/∂u), bitangent half3 @36 (+∂P/∂v) | stored tangent, w = −sign(dot(cross(N, T), B)) in engine numbers; only on materials with a normal map |
| COLOR_0 | D3DCOLOR @20, only when the mesh buffer's `hasColor` flag is set | VEC4 float, rgb sRGB → linear, alpha as stored |
| indices | u16 triangle list, clockwise against the normal in engine numbers | the normal side is glTF's front face: file order in the true frame, reversed in the mirrored one |

The table gives the engine's numbers, which is the file with `--frame
mirrored`. In the default true frame x of NORMAL and TANGENT is negated
with the positions and TANGENT w with it.

In the game's shaders the vertex colour multiplies the final lit colour (rgb)
and the texture's alpha (a). The game does that on display-encoded values and
glTF on linear base colour, hence the conversion. 387 of the 735 Part 2 PC
models have coloured buffers; the mean factor over their coloured vertices is
0.84, so they are darker with the colour than without, which is the authored
look. Specular and glow are tinted in the game too, but not in glTF.

The game shades with N′ = x·T + y·B + z·N from the stored tangent and
bitangent, x and y being the two channels of the normal map. glTF rebuilds
the bitangent as cross(N, T)·w and expects +Y to point up the image, so the
embedded normal texture has green inverted and w is the negated stored
handedness. About 15 % of vertices have a bitangent that is not ±cross(N, T);
glTF cannot represent that, and the result differs from the engine's pixel
math by about 1° in the median. Blender's glTF importer ignores TANGENT and
builds its own from the UVs; three.js uses it.

`extract --glb` writes a GLB for every header-decoded model (rigged if the
model is skinned, static otherwise) and takes its material switches from the
texture's `sheet.json`: `twoSided` → `doubleSided`; `renderType` 1
("Standard with blending") with an alpha-carrying diffuse layer, or vertex
alpha that varies → `alphaMode: BLEND`; otherwise a diffuse layer with alpha
→ `MASK` at `alphaThreshold`/255; `normalMapPower` → the normal texture's
`scale`. The character GLBs get the same attributes, a `BLEND` copy of the
material for parts whose vertex alpha varies, and the `MASK` cutoff and
normal scale from the sheet; their materials stay double-sided and
`renderType` 1 is not applied to them. (That is `--materials legacy`; with
the default the alpha mode, culling, roughness and specular of both kinds of
GLB follow the sheet as described under "Materials".)

Limits: a console model whose console is not known and whose data does not
show the colour byte order gets no COLOR_0 (none in the four console sets;
see "Platform support"), and a model the header path does not read
(none in the six tested sets) takes the descriptor scan and gets none of
these attributes; a character GLB records missing attributes in
`asset.extras.watchmen.not_decoded.vertex_attributes` and a missing colour in
`.vertex_colour`. A texture tree extracted before 1.4.0 has no
`sheet.json` (materials then stay double-sided with a 0.5 cutoff) and its PC
normal maps have X and Y swapped: extract the textures again.
`--no-vertex-attrs` writes the 1.3.0 attribute set.

## Platform support

What each of the six tested sets gives. "Part 1" on PC and Xbox 360 is the
standalone game (Xbox Live Arcade on the console); the PS3 disc carries
Part 1 rebuilt in the newer Part 2 file format, which is why its column
differs. The counts are from a full export of the six sets on Windows
(54 steps, every exit code 0, no `WARNING:` line in any log);
PC Part 2 is read from the original `game.naz`.

| | PC Part 2 | Xbox 360 Part 2 | PS3 Part 2 | PC Part 1 | Xbox 360 Part 1 | PS3 Part 1 |
|---|---|---|---|---|---|---|
| Files under `extracted/` (raw assets and the JSON, PNG and terrain GLB written beside them) | 9,922 | 9,922 | 9,922 | 12,132 | 12,132 | 12,132 |
| Fragment JSON typed and lossless | 906 of 906 | 906 of 906 | 906 of 906 | 758 of 758 | 758 of 758 | 758 of 758 |
| Fragment keys without a name | 0 | 0 | 0 | 0 | 0 | 0 |
| Texture headers with pixel data | 937 of 937 | 937 of 937 | 937 of 937 | 1,206 of 1,206 | 1,206 of 1,206 | 1,206 of 1,206 |
| Layers that differ from PC by more than 8 (mean absolute difference over the four channels R, G, B, A) | reference | 7 | 0 | reference | 7 | 0 |
| Cube maps, six faces equal to PC | reference | 110 of 110 | 110 of 110 | reference | 200 of 200 | 200 of 200 |
| `sheet.json` (material switches) | yes | yes | yes | yes | yes | yes |
| Model headers / models with mesh data | 740 / 735 | 740 / 735 | 740 / 735 | 1,090 / 1,085 | 1,090 / 1,085 | 1,090 / 1,085 |
| Model decode | header | header | header | header | header | header |
| Model GLB, one per model with mesh data (the three engine unit primitives `unit_box`, `unit_cone`, `unitsphere` not counted; every set writes a GLB for them too, so `models/` holds 738 / 1,088 `.glb` files and the `model GLBs` summary line prints that number) | 735 | 735 | 735 | 1,085 | 1,085 | 1,085 |
| `.model.json` | full | full | full | full | full | full |
| NORMAL / TANGENT / COLOR_0 | yes | yes | yes | yes | yes | yes |
| Movie length in `text_meta.json` (16 players, 12 `.bik`) | yes | yes | yes | yes (the `.bik` copied from beside `derived_pc`) | yes (copied from beside `derived_x360`) | yes |
| Character GLBs | 26 | 26 | 26 | 80 | 80 | 80 |
| Character mesh pieces | 787 | 787 | 787 | 1,525 | 1,525 | 1,525 |
| Ragdoll rig and `.ragdoll.json` | 26 | 26 | 26 | 80 | 80 | 80 |
| Sounds | 2,921 `.wav` | 2,921 `.xma` | 2,921 `.mp3` | 3,953 `.wav` | 3,953 `.xma` | 3,953 `.mp3` |
| Subtitled sounds without a length (`text_meta.json`) | 0 | 0 | 0 | 0 | 0 | 0 |
| Music tracks (13 streams) | 53 `.ogg` | 53 `.xma` | 53 `.mp3` | 52 | 52 | 52 |
| Sound events in `sound_meta.json` | 3,880 | 3,880 | 3,880 | 1,788 | 1,788 | 1,788 |
| Levels / navigation GLBs | 6 / 5 | 6 / 5 | 6 / 5 | 7 / 6 | 7 / 6 | 7 / 6 |
| `.pb`, `.grass`, `.detailmesh` JSON (no bytes left) | decoded | decoded | decoded | decoded | decoded | decoded |
| `.font` JSON + atlas PNG | 3 | 3 | 3 | 3 | 3 | 3 |
| `.scene` JSON | 1 | 1 | 1 | 1 | 1 | 1 |
| `.terrain` JSON, height / layer PNG, GLB | 3 | 3 | 3 | 5 | 5 | 5 |
| `.terraincoloringasset` JSON + PNG | – | – | – | 5 | 5 (the 1×1 map unverified) | 5 |

Not decoded. Each item of this first list has a line in the log of the
step that meets it (`WARNING:` for content that is missing from the output,
`note:` for an expected absence) and the marker named here in the output.
`extract` ends with `not decoded completely: none` when every asset it
writes JSON for is decoded to the last byte, and with the count per kind
otherwise:

- **Console vertex colours** are decoded on every model of the four console
  sets. Xbox 360 and PS3 store the colour bytes in a different order
  (A,R,G,B / R,G,B,A) and a Part 2 model does not say which console it is
  from; `extract` takes the console from the block path inside the archive
  (`derived_x360/…`, `derived_ps3/…`) or from the source directory, and
  `characters` from the extract output (`files/derived_…`, else inferred
  from the tree). `WATCHMEN_CONSOLE=x360` or `ps3` names it by hand. The 13 /
  13 / 22 / 23 models (Xbox 360 Part 2, PS3 Part 2, Xbox 360 Part 1, PS3
  Part 1) whose data alone leaves the order open equal the PC colours on
  every vertex in the export. Only a loose
  console model with nothing naming its console can still end without
  COLOR_0: the `.model.json` then says `not_decoded: ["COLOR_0"]`, the log
  has a `note:` line and a count in the summary, and a character GLB keeps
  NORMAL / TANGENT and lists the pieces under
  `asset.extras.watchmen.not_decoded.vertex_colour`.
- **A model that gets no GLB** with `--glb` has `"glb": {"written": false,
  "reason": …}` in its `.model.json`, and the summary names it under `note:
  no GLB for N model(s)`. A model the header path does not read is decoded
  by the descriptor scan (`mesh_source` in the sidecar; `"submeshes"` under
  `not_decoded` when the scan found fewer than the header lists). Neither
  occurs in the six sets.
- **Console sounds** stay `.xma` / `.mp3` without `--vgmstream-cli` (2,974
  and 4,005 files per set with the music; the log says so).
- **Models without mesh data** give no OBJ: the five skeleton models in
  Part 2; three skeleton models, `Docks_waterSurface_aligner` and
  `GuardRoom_Door_02` in Part 1 (one `note:` line each, and named in the
  summary).
- **A character GLB without a ragdoll rig, without vertex attributes or
  with a mesh piece no loader could decode** has one log line each and the
  reason under `asset.extras.watchmen.not_decoded`.
- **Fragment keys named by inference:** none. The seven Part 1 keys are
  entries of the Part 1 `database.bin` (see `docs/SCRIPT_DATABASE.md`), so
  no fragment JSON carries `inferred_names`; the marker stays in the code
  for a name added later without such a source.
- **Terrain, fonts, terrain colouring:** decoded to the last byte on every
  set. Not established, and listed in the terrain JSON under
  `not_established`: one decal byte (`b18`) and how a decal's `uv_offset`
  enters the UV; also the texel position of the one 1×1 Xbox 360
  colouring map (`stream.unverified`, a `note:` line). The fields are named
  after the loader, with the offset-style keys of earlier files as aliases. `inferred` lists
  the fields whose meaning is matched against data, not read from code.

Known limits that no log line can state, because one set alone does not
show them:

- **Console sound decoding** was checked on samples only:
  vgmstream decoded 26 of 26 Xbox 360 files (14 of Part 2, 12 of Part 1;
  correlation with the PC sound 0.99 in 4,096-sample windows, median over
  the files), ffmpeg 8 of 8 PS3 files (0.96; the decoded length equals the
  header's sample count on all 8). Console lengths are whole codec
  frames: Xbox 360 0 to 0.02 s over
  the PC length (median 0.010 s), PS3 0.03 to 0.064 s over (median
  0.045 s; the MP3 encoder delay and padding are inside the count),
  measured on all 2,921 and 3,953 sounds. No shipped console sound has a
  cue point, so the console cue reader is untested on data.
- **Xbox 360 textures that still differ from PC** (seven layers per part
  by the metric of the table): `ArrowMore`; the alpha
  byte of four (Part 2) or five (Part 1) A8R8G8B8 effect maps, 0 where PC
  has 255; the `SawmillRope` and `HarleyMotorcycleSpokes01` normal maps
  (their place in the packed mip tail is not known). `streamingwater`
  specSize in Part 1 is below the line by that metric (6.28 over R, G, B,
  A) and above it over the colour channels alone (8.37). The slot-7
  specular-size map
  is DXT1 on this console and is written as its red channel (measured
  against the PC map, not read from the shader). PS3 stores DXT5 where PC
  has ATI2 normal maps (574 / 660 layers), which is the "within 8" group.
- **Console models:** positions are coarser in the console files than on
  PC (steps of up to 0.5 m on the Part 2 sky domes, 1.0 m in Part 1). The
  console vertex layouts of models and terrain are matched against the PC
  values, not read from console code.
- **The terrain GLB** has no textures (each node names its layer's texture
  path) and holds the first draw pass only; decal rectangles and the blend
  pass are in the JSON. The detail mesh geometry is located (`stream`) but
  not written as a mesh. The glTF validator reports no error and no warning
  on the 11 terrain GLBs checked, and 2 to 8 unused objects in each (an
  info).
- **Part 1 levels:** `ConstructionSite` links 0 of 4 path objects (its
  `.hpd` has no path-object table), `Streets` 14 of 15.
- **Letter case of names:** 41 asset paths are stored under a spelling
  that differs between the six sets: three textures between the Part 2
  platforms (`Fire_01.BMP` / `Fire_01.bmp`, `WallCables_03.bmp` /
  `wallcables_03.bmp`, `garbagepile_01.bmp` / `GarbagePile_01.bmp`), 37
  paths between Part 2 and Part 1, one folder inside Part 1; the loose
  Part 1 folders also spell `data/Levels/Game_Levels/<Level>/Gameplay`
  where the archives have lower case. They are written under one spelling
  (`--names canonical`, the default), so the path lists of the sets compare
  without regard to platform or part: with `--names stored` they differ in
  letter case only in 14 / 13 / 12 paths between the Part 2 platforms, 6 in
  Part 1 and 304 / 307 / 317 between the parts; in the six-set export
  0 file paths and 0 folders do. A path
  the table does not list keeps its archive's spelling; a new archive (a
  mod) can therefore bring spellings the table does not know.
- **Stored strings in decoded data:** the JSON files that are one asset,
  value for value, keep the strings as the asset stores them, in whatever
  letter case: everything under `extracted/` (`.fragment.json`,
  `.sequence.json`, `.particle.json`, `.terrain.json`, `.grass.json`,
  `.detailmesh.json`), the per-file JSON under `particles/`, `config` and
  `config_tree` of a `.nav.json` and the `overrides` of `sheet.json`. Such
  a string can name a file whose path differs from it in letter case; see
  "Asset strings in the JSON files" for the lookup.
- Stream sets other than manual ones, and `%03d.block` multi-part streams,
  do not occur in the shipped data and are untested.

Differences that are in the game data, not in the decoding: platform text
tables; spline handles of 7 (Part 2) and 20 (Part 1) sequences, off by
1/128; one or two nodes in two Part 2 level fragments; 12 fragments, 400
texture-sheet ids and one `reflectionType` of the PS3 Part 1 build. (The
PC Part 2 Bordello level has the consoles' 92 Dominatrices, 36 Gimps and 23
Gimps with gag ball; a modified copy of the archive, with the Gimps
replaced, differs in that level only.) Level `uid` values contain a load-order index and do
not match across platforms; `stable_uid` does.

## Tests

```
pip install -e ".[dev]"
pytest
```

The suite runs with **no game files**: it covers the archive-entry path
sanitizer, the Kapow property hash, the little/big-endian skeleton decoder
against synthetic ModelRes headers, glTF structural conformance of the GLB
writer (chunk padding, accessor alignment, accessor min/max, no empty arrays),
clip-timing arithmetic, and output determinism. It is the executable form of
the correctness claims below — if you change a decoder, this is what tells you
whether you changed its output.

`tests/test_v120_regressions.py` pins every fix in the 1.2.0 correctness pass;
each of its tests was verified to fail on 1.1.0, so the byte-order plumbing,
skinning-slot fallback, material pairing and CLI/import contracts cannot
silently regress. The 1.3.0 changes are pinned the same way by seven files
(`test_anim_meta`, `test_names`, `test_formats_v2`, `test_phys_v2`, `test_interp_v2`,
`test_anim_meta_v2`, `test_followup`), on synthetic fixtures, and the 1.4.0
changes by twenty-three (`test_jiggle_solver`, `test_jiggle_default`, `test_vcolor`,
`test_face_rule`, `test_texture_lookup`, `test_texture_sheets`,
`test_parts_and_face2`, `test_outfits_integration`, `test_materials_v2`,
`test_ragdoll_rig`, `test_audio_v2`, `test_wave2_integration`,
`test_combat_meta`, `test_fx_meta`, `test_level_meta`, `test_text_assets`,
`test_particle_asset`, `test_particlemeta`, `test_nav_data`, `test_feature_seams`,
`test_realdata_r5`, `test_fullextract`, `test_frame`, the six
`test_p1_*` files of the engine rules, the eight `test_p2_*` files of
Parts 1 and 2 on all platforms and the four `test_p3_*` files of the raw formats, the Part 1
header and the console models, whose
big-endian and older-layout fixtures are built in the tests, the two
`test_p3t_*` files of the script database and the builtins table, the two
`test_p4_*` files of the terrain placement and the `scriptdb` command,
`test_p5_console_colour` of the console vertex colours, and the fifteen
`test_p6_*` files of the sweep of the open points, `test_p6_docs` of the
documentation audit among them). Two of those tests compare `pinned`
and `pivot` byte for byte with an older source tree and are skipped when it is
not there: one in `test_jiggle_solver` needs a 1.3.0 tree (`$WATCHMEN_TK130`,
or `../tk130` next to the checkout), one in `test_jiggle_default` a
development snapshot that was never released (`$WATCHMEN_TK140`, `../tk140`).
`test_p8_canonical_names` pins the naming (`--names`), and the ten
`test_s2_*` files pin the restored eyelash UVs, the movie strings, a light
layer's opacity, the platform-independent jiggle bake and tables, the
unbound path objects and the closed file handles; `test_s4_review_fixes`
pins the name scan of a clip, the bake and GLB rules of a resumed export, the
clip families of `char`, the stored transform and the host-offset mark of a
level record, the button names of a save file and the movie strings of
`text_meta.json`; `test_s5_code_findings` and `test_text_layout` pin the rules
read from the executable after the six-set export (the animation type rule,
waypoint links, PVS-root visibility, triangle strips, the TextBox line
breaker, the cube map per culling area and the others listed in the
changelog); `test_s6_findings` pins the layer fields of a state, the
partner's waypoint constants, the Underboss movement rules and the field
names of the terrain, font, pivot-book and model headers. A checkout on its own
therefore reports 1,772 passed, 2 skipped (1,774 tests); the comparison
with 1.3.0 values still runs there on frozen numbers. `test_s8_review_fixes`
pins the clip timing (no walk / run multiplier), the options record of a
resumed export, the bake identity, the exit codes of `extract` / `all`, the
error on a folder that is not an extract output and the GLB name in the
`wrote` line. `conftest.py` fails a test that leaves a `WATCHMEN_*`
variable changed, so the result does not depend on the order the tests
run in. The suite writes about 55 MB below the temp folder (`$TMPDIR`); on
a full temp disk tests fail with `No space left on device` and pytest can
stop with an internal error.

Round-tripping the real corpus (the "906/906 fragments" figure) needs a game
archive and is not part of the offline suite.

## Documentation

Format specifications and the complete reverse-engineering record live in
[`docs/`](docs/INDEX.md) — start with `docs/INDEX.md`.

- Coverage of the executable, measured by cited-address coverage over the merged
  35,542-function dump (every code address a report or document cites is mapped to the
  function whose body ranges contain it; a function with at least one cited address counts
  as read): 1,948,530 of 3,309,065 bytes of live engine and gameplay code (58.9 %; 32.8 %
  cited by a check, review or verify report), 2,980,661 of 6,088,997 bytes of the whole
  dump (49.0 %); an upper bound on what was read in depth
  ([`docs/re/README.md`](docs/re/README.md), "Coverage of the executable").
- [`docs/re/`](docs/re/README.md) — the research reports of the 2026-10-02
  decompilation pass, the two added on 2026-10-03 (the PhysX joint solver,
  the shaders' use of vertex colour and tangents) and the ten of 2026-10-04
  (script names, renderer, physics, combat, AI, runtime, audio, effects /
  camera / HUD, the Dominatrix audit, the face system), shipped as written,
  with an index of what each establishes and what was corrected afterwards.
- `tools/blender_import_level.py` (a level into Blender, above) and
  `tools/blender_attach_extras.py` (clip metadata onto imported actions).
- [`tools/ghidra/`](tools/ghidra/README.md) — the Ghidra scripts that produce
  the decompilation those reports were read from. Not needed for extraction.
  Its last section says what further research tooling exists outside this
  repository (a gap sweep of the PC executable, Ghidra language files for
  the PS3 and Xbox 360 executables) and what each establishes.

## Shipped data tables and their provenance

`wlib/` ships ten data tables. `watchmen gendata` can regenerate the first
two from a game install and `gendata check GAME_ROOT` compares the shipped
copies with a fresh regeneration:

- `prop_hash_dict.pkl` — name-hash → name dictionary, a string harvest over
  the exe and every naz block payload + identifier tokenization (`gendata
  strings EXE game.naz`; works even on the retail DRM-packed
  `KapowMulti.exe`, whose string sections are unencrypted). The shipped
  table is an earlier harvest and not the byte output of today's generator:
  from the Part 2 PC executable alone `strings` gives 40,575 names against
  the table's 23,770, with 675 shared hashes in another letter case (no run
  with the archive was compared). Names the engine's native classes
  register are spelt as registered: `gendata respell` applies
  `registered_names.json` to a table without any game file, which is how the
  shipped table got them, and running it again changes no byte.
- `registered_names.json` — the spelling of the 1,224 property and command
  hashes the native classes register (Part 2 PC executable), the three names
  the dictionary keeps (`PLATFORM`, `Scene`, `physicsTimepassed`) and the
  per-class exception `is3D` (Sprite) / `is3d`. Research output from the
  registration sites; each entry is verified by re-hashing. Its
  `native_messages` section lists the 589 native message registration strings
  under their hashes (not validated against a sender).
- `builtins.json` — the builtin script module (123 functions, 19 properties,
  the `LANGUAGE` and `PLATFORM` values; format `kapow-builtins/1`), walked
  from the registration function 0x47ff8c with capstone. Research output,
  not regenerable with `gendata`; `wlib/script_builtins.py` reads it and
  `script_builtins.check()` verifies its internal consistency. See
  [`docs/BUILTINS.md`](docs/BUILTINS.md). `other_builds` says what the console
  images differ in (member-name strings only).
- `pivot_sheets.json` — the 47 pivot sheets of PC Part 2 (collision mask,
  friction, restitution), measured on the three pivot books; the level
  export's `ai_sight` uses it when an extract has no pivot books of its own.
- `reg_dump.json` — 441 engine classes (5,090 property and 6,630 command
  registrations: names, defaults, UI captions, handler addresses and slots;
  format `kapow-reg-dump/2`) recovered from registration call sites in the
  executable's code.
  Regenerable (`gendata regdump EXE`, needs `pip install .[regdump]`) but only
  from a DRM-free executable — retail `.text` is SecuROM-encrypted in place.
  Its sibling `prop_names_from_reg.json` is a pure aggregation and is derived
  at runtime (not shipped).
- `kapow_fragment_keys.pkl` — the fragment property-key crack: names AND value
  types for ~4.5k hashes, recovered by corpus-wide type inference, caption
  synthesis, and manual work. This is research output (like the bind formula),
  not something latent in the game files — it cannot be regenerated
  mechanically. `gendata keys-export` dumps it to readable JSON for inspection
  or hand-maintenance (`keys-import` converts back). A name a native class
  registers is spelt as registered (`visible`, `open`, `useRealtime`), as in
  the property dictionary.
- `command_signatures.json` — the hashed strings of the 830 commands that take
  parameters (`name(type,…)`). Research output: the strings are not in the
  executable; each entry is verified by re-hashing.
- `engine_enums.json` — 34 enum families (id ↔ name) exactly as the executable
  registers them, the family each criteria variable takes its values from, and
  what each of the 93 animation events does. Read from the executable; there
  is no regeneration command.
- `property_store_flags.json` — the registered properties the engine's writer
  never stores (61) and the deprecated aliases it reads but never writes (56)
  (`docs/FRAGMENT_FORMAT.md`). Read from the executable; no regeneration
  command.
- `input_code_enums.json` — the engine's `KeyboardKeys` (118 names),
  `GamepadButton` (16) and `MouseButtons` (3) enums, which `savemeta` uses
  to name the codes of a save file's button map (`docs/LEVEL_META.md`), and
  the `LogicalInputButtons` and `MetaInputDevices` enums the `%N` text
  parameters use (`docs/TEXT_ASSETS.md`). Read from the executable; no
  regeneration command.
- `event_editor_params.json` — caption, group and range of every animation
  event argument the editor exposes (16 event ids;
  `AnimationEventWM.FilterExposedProperties` 0x5c1767); `fx.event_editor_params`
  of `anim_meta.json`. Read from the executable; no regeneration command.
- `filter_exposed.json` — which properties the property filters of
  `TriggerActionGeneral`, `TriggerActionParticle` and `TriggerUseFragment`
  show per action or use type (0x85e3e8, 0x86038f, 0x873568); `applies` on
  the graph nodes of a level JSON. Read from the executable; no regeneration
  command.
- `canonical_names.json` — the one spelling of the 41 asset paths (35
  textures, 2 models, 4 folders) whose letter case differs between the six
  game sets, keyed by the folded path; format `watchmen-canonical-names/1`.
  Measured on the path lists of the six sets; 40 values are the Part 1
  spelling, the folder `streetlines` the one its fragments and textures
  use. No regeneration command: a new difference is added by hand
  (`wlib/canonical_names.py` reads it; see "Asset names" in
  `docs/ENGINE_CONSTANTS.md`).

The retired capture-fit `jiggle_params.npz` is intentionally absent: without
it the jiggle path uses `jiggle_d6`. Its geometry and physics settings are
read from the executable and the game files. Only the `pivot` model uses
capture-measured numbers (its swing stiffness and damping, built into the
module); `solver`, the default, and `pinned` take the spring and damping from
the game files.

## Notes

- Skeleton binds and clip decoding are **engine-exact**: in our testing,
  validated against GPU-captured bone palettes (frames are matched on all
  non-twist bones within 1.0°; on those frames the twist bones are within rms
  0.18–0.39° per skeleton, max 23.4°, over 13,471 matched frames of five
  skeletons) and against the decompiled executable's math. The captures
  themselves are research input and are not shipped, so that specific number is
  not reproducible from this repository alone; what *is* checkable here is in
  `tests/` (see **Tests** above).
- Extraction output is deterministic on one machine: repeated runs over the
  same archive produce byte-identical files (measured in a Linux VM). All
  text output is written UTF-8 with LF endings.
- What has run on Windows. The six-set export is a Windows run (measured,
  the batch summary: 54 of 54 steps exit code 0) of `extract --glb`, `binds`,
  `characters`, `faces`, `levelmeta`, `textmeta`, `fxmeta`, `particlemeta`
  and `grademeta` on all six sets, in the default frame. A Linux run over
  the same raw files was compared with that output on 30 Part 2 PC models
  and one character (Rorschach, 12 clips): OBJ, MTL, `.model.json`, the
  ragdoll JSON and every mesh and animation accessor compared were
  byte-identical; the model GLBs differ in bytes (on the one opened, in the
  compression of the embedded PNGs only, equal pixels — that this is the
  cause on the other 29 is inferred), so GLB files are not byte-identical
  across platforms. One synthesized pose clip (`GRIP 1H`, 34 channels)
  differed; the cause (the cut-down clip set of that run) is inferred. The
  `characters` step of three PC Part 2 characters run on Linux from the
  export's own extract: the 611 raw bakes of their skeletons, the ragdoll
  JSON and every mesh and skin accessor are byte-identical with the Windows
  files; the embedded PNGs differ in bytes on 18 of 28 images of `Gimp1.glb`
  and node rest transforms in the 15th digit; `KnotTop_Small` (no jiggle
  bone) is equal in all 29,995 accessors. The jiggled palettes the
  six-set export baked on Windows equal the Linux ones bit for bit (see "Jiggle bones"); `anim_meta.json`
  and `sound_meta.json` built on Linux are byte-identical with the Windows
  ones (PC Part 2, PS3 Part 1; PC Part 2, PC Part 1, Xbox 360 Part 2).
- The test suite without `test_s8_review_fixes.py` ran on Windows-native
  Python (Python 3.13.13, numpy 2.4.6) in both frames (measured); the
  full 1,774-test suite has not run on Windows.
- What has not run on Windows: the commands the export batch
  does not call (`all`, `char`, `bake`, `charlibs`, `text`, `ragdoll`,
  `savemeta`, `scriptdb`, `fragment`, `hash`, `gendata`, and stand-alone
  `animmeta`, `soundmeta`, `navmeta`); `--frame mirrored` and every other
  non-default switch.
- Platform differences: identical across the three platforms of a part are
  the asset names, the skeleton JSON, the Part 2 navigation JSON,
  `fx_meta.json` and `grade_meta.json`, the counts, names and joint counts
  of the character animations, and all but 4 (Part 2) of the fragment JSON
  files. What is not, and what each set does not decode, is under "Platform
  support".
- Coordinates: the Kapow engine is Y-up, the same as glTF, so no axis is
  swapped; GLB output is upright both at rest and animated. The engine is
  left-handed, so x is negated (see "Coordinate frame"; `--frame mirrored`
  writes the numbers unchanged).
- Console block payloads are big-endian; byte order is auto-detected per
  archive — there is no flag to pass.
- This toolkit reads only data you extracted from your own copy of the game;
  it ships no game assets.

## License

MIT — see [LICENSE](LICENSE). The reverse-engineered code and documentation
are original work; identifier strings inside some data tables were extracted
from the game executable for interoperability and remain their rights
holders' property (see the note in LICENSE).
