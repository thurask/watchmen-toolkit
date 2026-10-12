#!/usr/bin/env python3
"""watchmen — CLI for the Watchmen: The End Is Nigh asset-extraction toolkit
(Parts 1 & 2; PC, Xbox 360, PS3).

All real logic lives in wlib/ (see watchmenlib.py facade); this is just the CLI.

Commands
--------
  all NAZ OUT                    In order: extract -> binds -> `characters` (the
                                 character export into OUT/characters); takes the
                                 options of `extract` and of `characters`
  extract NAZ OUT [opts]         Full asset extraction (+JSON for all types)
                                 opts passed through, e.g. --vgmstream-cli PATH
                                 (any platform's vgmstream-cli; decodes console
                                 X360 XMA2 / PS3 MP3 audio to .wav — without it
                                 console audio is written as .xma/.mp3)
                                 Music streams are written one file per track
                                 (<name>_track<k>...) with a <name>.json sidecar
                                 (tracks, cue points, MusicSetup track states);
                                 --flat-music writes one file per stream instead
                                 (the output of releases before 1.4.0),
                                 --music-track-labels adds the MusicStreamSlot
                                 track names to the file names, --smpl-loops adds
                                 a RIFF smpl loop to looping sounds.  Sound facts
                                 (rate, loop flag, length) go to
                                 audio/sound_info.json.  Also written: text/ (every
                                 text asset in every language, see `text`;
                                 --no-text) and nav/ (the levels' navigation data,
                                 see `navmeta`; --no-nav).
  binds NAZ OUT_DIR              Build engine-exact FILE-ONLY binds for all skeletons
  charlibs EXTRACT_OUT OUT_DIR [NAZ]
                                 Textured+animated character-library glbs (needs
                                 extract+binds; NAZ, read for a bind that is
                                 missing: default 01_game.naz, else game.naz)
  animmeta EXTRACT_OUT OUT.json [BINDS_DIR]
                                 The game's own animation metadata as JSON (format
                                 "watchmen-anim-meta/2"): every state's clips, loop,
                                 criteria and events (trigger kind, seconds or play
                                 position), transitions with their sync markers,
                                 which clip pairs with which (counters, finishers,
                                 throws), where the partner stands and when it is
                                 anchored and released, and the engine's enum tables.
                                 `characters` writes the same table to
                                 OUT_DIR/anim_meta.json and embeds it per clip.
  levelmeta EXTRACT_OUT OUT_DIR [LEVEL ...]
                                 One OUT_DIR/<level>.level.json per level of the
                                 extract's *.scene (format "watchmen-level-meta/1"):
                                 fragment tree with world transforms, character,
                                 model and volume placements (world and glTF node
                                 transforms), the condition / action graph with
                                 resolved targets, checkpoints, camera tours,
                                 movies (with their subtitle table), game events
                                 and the path objects (doors, gates) linked by id
                                 to the level's navigation data when EXTRACT_OUT
                                 has it; per placed character what the file fixes
                                 about its model and weapon (`variant`, `weapon`:
                                 fixed, or the candidates the engine picks the
                                 least-used of) and its AI start state; the combat
                                 presets the level switches to; the cube maps, the
                                 lights, the waypoint chain, the culling groups and
                                 the stream blocks.  See docs/LEVEL_META.md.
  savemeta FILE [OUT.json]       A `.kpw` save file (PROGRESS.kpw, SETTINGS.kpw)
                                 as JSON (format "watchmen-save-meta/1").
  soundmeta EXTRACT_OUT OUT.json [ANIM_META.json]
                                 What the game plays, when and for how long (format
                                 "watchmen-sound-meta/1"): sound definitions with
                                 their play tree and variation rule, per animation
                                 state the SOUND / SPEAK / footstep events resolved
                                 to definitions, waves and durations, the footstep
                                 table (effect type x surface), attack-start and
                                 hit sounds, speak groups per character with
                                 voices, categories and line lengths, music setups.
                                 Event times in seconds come from ANIM_META.json
                                 (built on the fly when not given).  `characters`
                                 writes the same table to OUT_DIR/sound_meta.json.
  text NAZ OUT_DIR               Only the text assets (menus, tutorials, warnings,
                                 key names, in-game and cutscene subtitles), every
                                 language: OUT_DIR/text/<en|fr|it|de|es>/<asset> raw,
                                 + .json (rows in order) and + .csv, and
                                 text/index.json.  `extract` writes the same folder
                                 (--no-text switches it off); this command adds it to
                                 an existing extract without touching anything else.
  textmeta EXTRACT_OUT OUT.json  All strings per language with key and source asset,
                                 and the subtitles: sound -> key -> lines per
                                 language with their times, and per speak group /
                                 line / voice the waves with their subtitle; the
                                 cutscene movies with their subtitle table and line
                                 times (`movies`), when a line is shown
                                 (`subtitles.rules`) and how each platform picks
                                 the language (`selection`) (format
                                 "watchmen-text-meta/1"; needs EXTRACT_OUT/text).
  fxmeta EXTRACT_OUT OUT.json [ANIM_META.json]
                                 Effects, camera and rumble data as one table (format
                                 "watchmen-fx-meta/1"): effects with their particle /
                                 sound / speak children, the damage-effect rule and
                                 the per-character definitions, weapons, character
                                 attachments, the camera rig; with ANIM_META.json
                                 also every state's decoded fx events and every
                                 pair's camera cuts.  `animmeta` / `characters`
                                 already put all of it into anim_meta.json (`fx`).
  particlemeta EXTRACT_OUT OUT_DIR [TEXTURES_DIR]
                                 Every particle system of the extract: per file
                                 OUT_DIR/<asset path>.particle.json (the engine's
                                 tree, format "kapow-particle/2", as `extract`
                                 writes it beside the asset) and OUT_DIR/index.json
                                 (format "watchmen-particle-meta/1": duration, loop,
                                 the particle types with texture, render style,
                                 blend mode and module classes, textures looked up
                                 in EXTRACT_OUT/textures or TEXTURES_DIR, the
                                 byte-exact rebuild check).  EXTRACT_OUT may also be
                                 any folder of .particle files or a single file.
                                 See docs/PARTICLE_FORMAT.md.
  scriptdb DATABASE.bin [OUT.json] [--find KEY ...]
                                 The script name database (data_baked/tnt/production/
                                 database.bin): counts, type histogram, whether the
                                 file was consumed exactly; --find looks up a hash
                                 (0x40cb4063, key_40cb4063) or a name; OUT.json gets
                                 every property and message (format
                                 "kapow-script-database/1").
                                 See docs/SCRIPT_DATABASE.md.
  faces EXTRACT_OUT OUT_DIR      Cutscene-head glbs: engine-exact face binds + the 24
                                 facial expression POSES (game has no keyframed face anims)
  characters EXTRACT_OUT OUT_DIR [NAZ] [--jiggle-model solver|pivot|pinned]
                                 [--face-rule engine|legacy] [--no-face-idle]
                                 [--parts game|all]
                                 [--no-vertex-attrs] [--no-ragdoll]
                                 Folder per character, one glb per fragment
                                 variant, EVERY animation of its skeleton (resumable).
                                 NAZ default: 01_game.naz, else game.naz.
                                 Jiggle bones are baked with the PhysX soft-limit
                                 `solver` model (default; the `PhysicsWorld` values
                                 of EXTRACT_OUT), the linear `pivot` model or
                                 `pinned` (the model of releases before 1.4.0);
                                 each has its own cache directory.
                                 --face-rule (also $WATCHMEN_FACE_RULE):
                                 `engine` (default): every body clip carries the
                                 face track the game plays with it, read from the
                                 face animation classes (see anim_meta.json "face");
                                 `legacy`: the rule of releases before 1.4.0 (pose
                                 guessed from the
                                 clip name, synthetic blinks, no face rig on the
                                 Thug / Gimp characters).  --no-face-idle (also
                                 $WATCHMEN_FACE_IDLE=0) leaves the seeded idle
                                 cycle (the game's random blink / fidget) out of
                                 the baked track.  --jiggle-model pinned
                                 --face-rule legacy --no-vertex-attrs together give
                                 the animation and mesh data of releases before
                                 1.4.0; textures are found by the path the model
                                 stores in either case.
                                 --parts (also $WATCHMEN_PARTS): `game` (default)
                                 shows what the game shows for the variant: the
                                 models of the collection's first outfit (ONE
                                 hairstyle, ONE jacket) and no weapon.  Models
                                 that differ between outfits are nodes `OUTFIT <k>
                                 <model>`; those of the other outfits and the
                                 weapons (`WPN_...`) are kept under a node
                                 `alternatives` outside the scene: viewers do not
                                 draw it, Blender imports it as the switched-off
                                 collection "Orphan Nodes".  `all`: every listed
                                 model and every weapon at once.
                                 Each GLB also carries the character's ragdoll
                                 rig (bodies, shapes, D6 joints of the skeleton
                                 model) as helper nodes under a node `ragdoll`
                                 outside the scene, and <Variant>.ragdoll.json is
                                 written beside it; --no-ragdoll (also
                                 $WATCHMEN_RAGDOLL=0) leaves both out.
  ragdoll MODEL [PIVOTBOOK.pb] [OUT.json]
                                 The ragdoll rig stored in a skeleton / character
                                 .model (17 bodies, 16 joints, shapes, limits) as
                                 JSON; with a pivot book, the "Ragdoll" material.
  --materials engine|legacy      (extract, all, characters, char, charlibs, faces;
                                 also $WATCHMEN_MATERIALS) `engine` (default): glTF
                                 materials from the texture sheet's values as the
                                 game's shader uses them -- roughness and specular
                                 strength from specularSize / specularPower and the
                                 specSize layer, emission from selfIlluminance, alpha
                                 test / blend / culling from renderType, alphaThreshold,
                                 opacity and twoSided; a <model>.model.json next to
                                 each extracted model (LOD distances).  `legacy`: the
                                 materials of releases before 1.4.0 (GLB and MTL
                                 byte-identical to them).
  --rig hierarchy|flat           (all, extract, characters, char, charlibs, faces;
                                 also $WATCHMEN_RIG) The skeleton of the rigged
                                 GLBs.  `hierarchy` (default): one joint node per
                                 bone, named after it and parented as the skeleton
                                 says, with rest pose and animation channels local
                                 to the parent; the skinned mesh nodes are scene
                                 roots.  `flat`: the layout of the 1.4.0 files --
                                 joint nodes b0..bN, all children of `root`, each
                                 carrying the joint's world transform (extract
                                 --glb: joints
                                 without a transform, identity inverse binds).  The
                                 skinning and every pose are the same in both.
  --frame true|mirrored          (all, extract, characters, char, charlibs, faces,
                                 animmeta, fxmeta, levelmeta, navmeta, ragdoll)
                                 The coordinate frame of every GLB / OBJ and of the
                                 data in their frame.  `true` (default): right-handed,
                                 +Y up, x = -engine x -- the game as it looks: text
                                 reads the right way round, a character facing +Z
                                 has its left hand at +X, bone names L / R are
                                 truthful.  Files carry coordinate_frame =
                                 "right-handed-true" (GLB: asset.extras.watchmen).
                                 `mirrored`: the engine's left-handed numbers
                                 verbatim, a mirror image (the files of releases
                                 before 1.4.0, byte-identical); no coordinate_frame
                                 key.  Raw engine
                                 values (level world.pos, nav JSON, fragment /
                                 particle JSON) are engine coordinates in both.
  --names canonical|stored       (all, extract, characters, char, charlibs, faces,
                                 particlemeta, levelmeta, animmeta, soundmeta,
                                 fxmeta, grademeta; also $WATCHMEN_NAMES)
                                 The archives store some asset paths in a letter
                                 case of their own (the engine does not tell the
                                 spellings apart).  `canonical` (default): output
                                 paths and material names use the one spelling
                                 wlib/canonical_names.json lists for the 41 asset
                                 paths that differ between the six game sets; a
                                 folder is spelled once per export (the table's
                                 spelling, else that of the first asset written
                                 into it) in extracted/, textures/, models/ and
                                 audio/ alike; the files brought from beside a
                                 loose folder (data/Levels/...) are named in lower
                                 case like an archive's.  In the tables (level
                                 JSON, particle index, fx / grade / anim / sound
                                 meta) a string that names an exported file is
                                 spelled as that file is written, the stored
                                 string beside it under "stored".  `extract`
                                 writes _canonical_names.json (canonical -> stored),
                                 "stored_name" into the texture's sheet.json and
                                 the model's .model.json.  `stored`: every path
                                 and string as its archive stores it; a table
                                 follows the naming of the export it reads unless
                                 the option is given.  Decoded asset data
                                 (extracted/**.json, the per-file particle JSON)
                                 always keeps the stored strings.
  --json-floats exact|rounded    (all, extract, fragment; also $WATCHMEN_JSON_FLOATS)
                                 How the decoded JSON (extracted/**.fragment.json,
                                 .sequence.json, .pb.json, ...) writes the game's
                                 float32 values.  `exact` (default): the shortest
                                 decimal that reads back as the same float32, bit
                                 for bit (1.2345e-05, not 1.2e-05); NaN / infinity
                                 as null.  `rounded`: the output of the 1.4.0
                                 files (6 places for property values, 5 for
                                 sequence keys, 3 / 4 for transform pos / quat),
                                 byte for byte.  Derived
                                 numbers (yaw_deg, a sequence key's quat) are
                                 rounded in both.
  grademeta EXTRACT_OUT OUT.json The levels' post-process grade (contrast, tint,
                                 gamma, bloom, fog) from their GFXEffect nodes, and
                                 what the game's options add to brightness,
                                 contrast, gamma and saturation per platform
                                 (`platform_adjustment`)
  navmeta FILE_OR_DIR OUT_DIR    The levels' navigation data: per level
                                 <Level>.nav.json (format "watchmen-nav/1": the
                                 path-finding graph, the walkable "AI mesh" floors,
                                 path objects and the Kynapse world definition, in
                                 engine space) and <Level>.nav.glb (mesh as
                                 triangles, graph edges as lines; overlays the
                                 model exports).  FILE_OR_DIR is an extract output
                                 (.hpd under files/, .aipathdata under extracted/),
                                 a game data directory or a single file.
  fragment FILE [OUT.json]       Lossless .fragment -> JSON (also .pb, .sequence,
                                 ...; --json-floats as for extract).  Exit code 0:
                                 written and `lossless` (parsed to its end, every
                                 stored value in the JSON); 3: written, but the
                                 parse did not reach the end of the file (`lossless`
                                 false, the `warn` key says where); 2: not a Kapow
                                 asset or not readable.
  bake CLIPNAME BIND.npz OUT.npy [NAZ]
                                 Engine-exact palettes for one clip, read from the
                                 archive NAZ (default: 01_game.naz, else game.naz,
                                 in the current directory).  Tracks are matched to
                                 bones as the character export does for the set: by
                                 exact name, and for a Part 1 archive also without
                                 a leading 'BipNN '.
  char FRAG.json VARIANT OUT.glb [BINDDIR [BAKEDIR [NAZ]]]
                                 [--jiggle-model solver|pivot|pinned] [--no-meta]
                                 Character variant -> GLB with all its clips
                                 (--jiggle-model also bakes the jiggle bones,
                                 which `char` otherwise leaves as authored).
                                 The meshes are read from the archive NAZ
                                 (default: 01_game.naz, else game.naz, in the
                                 current directory); the clips are the bakes in
                                 BAKEDIR (default: bake) of the clip families
                                 of the variant's skeleton.  VARIANT is an
                                 entry of FRAG.json that lists models: the
                                 enemy fragments have them, Rorschach's own
                                 fragment has none (use `characters`).
                                 When FRAG.json lies under EXTRACT_OUT/extracted,
                                 each clip gets its real length from the extracted
                                 .animation file (a clip without one is written at
                                 30 fps and named), and the animation metadata of
                                 that tree is used -- the anim_meta.json of a
                                 `characters` export under EXTRACT_OUT when it is
                                 current, else built now (minutes): clips get the
                                 same extras as in `characters` and looping clips
                                 are jiggle-baked as closed laps.
                                 --no-meta (or a fragment elsewhere): no extras,
                                 every clip baked as non-looping.
                                 The GLB has flat materials: no textures, no
                                 tangents, no face rig or face channels, no weapons
                                 and no ragdoll helpers (use `characters` for the
                                 full character).
  hash NAME                      Kapow property-key hash of a name
  --version                      Print the toolkit version and exit
  gendata SUBCMD ...             Regenerate wlib's data tables from a game
                                 install (strings/respell/regdump/propnames/keys-export/
                                 keys-import/check; see gendata -h)

Exit codes
----------
  0 done; 1 an unknown command, or a failure the command reports itself (`ragdoll`
  on a model without joints, `scriptdb` on a file it does not consume exactly,
  `navmeta` / `particlemeta` when a file fails); 2 bad arguments or options, a
  missing / unreadable input or data table, a Python older than 3.13;
  3 `fragment` wrote a JSON that is not lossless; 130 interrupted.
  Set WATCHMEN_DEBUG=1 to see the traceback of an error before its one-line message.

Examples
--------
  python3 watchmen.py all game.naz OUT      # fresh install -> everything
  python3 watchmen.py extract game.naz OUT
  python3 watchmen.py fragment OUT/extracted/.../Gimp.fragment
  python3 watchmen.py char Gimp.fragment.json Gimp2 CHAR_Gimp2.glb
"""

import os
import sys
import json
import struct

#: The oldest Python the toolkit runs on (pyproject.toml: requires-python).
MIN_PYTHON = (3, 13)


def python_too_old(version_info=None):
    """The error line for an interpreter older than MIN_PYTHON, else None.

    Checked before anything from wlib/ is imported: wlib uses library features of
    Python 3.13 (``itertools.batched``, exception notes), and on an older
    interpreter a command would otherwise stop later with an ImportError that does
    not say why.  pip refuses the install on such a Python; this covers
    ``python3 watchmen.py`` run from a checkout."""
    v = sys.version_info if version_info is None else version_info
    if tuple(v[:2]) >= MIN_PYTHON:
        return None
    return "error: watchmen-kapow-toolkit needs Python %d.%d or later (this is %d.%d)" % (
        MIN_PYTHON + tuple(v[:2])
    )


if python_too_old():
    print(python_too_old(), file=sys.stderr)
    sys.exit(2)

# append, never insert(0): wlib holds flat, generically-named modules
# (char_lib, gen_data, engine_schema, ...) that must not shadow the stdlib.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wlib"))


def _version():
    """The toolkit version: ``wlib.__version__`` -- the one place the code holds it
    (pyproject.toml repeats it for packaging; tests/test_v150_cli.py checks that the
    two, this value and the first CHANGELOG heading agree).

    ``importlib.metadata`` is deliberately not asked first: the metadata of an
    installed distribution can be another version than the checkout being run (a
    stale ``pip install`` next to a source tree), and the version printed must be
    the code's.  When the ``wlib`` package cannot be imported as a package (the
    script copied elsewhere with its wlib/ folder beside it), the value is read from
    wlib/__init__.py as text."""
    try:
        from wlib import __version__

        return __version__
    except Exception:
        import re

        try:
            here = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(here, "wlib", "__init__.py"), encoding="utf-8") as fh:
                m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', fh.read(), re.M)
            return m.group(1) if m else "unknown"
        except OSError:
            return "unknown"


VERSION = _version()


from wutil import read_bytes as _read_bytes  # one copy, in wlib/wutil.py  # noqa: E402


def _wl():
    """Import the facade lazily.

    `watchmenlib` costs numpy + Pillow + three pickled data tables at import
    time, so --help / --version / hash must not pay for it (and must not fail
    when a data table is missing)."""
    import watchmenlib as wl

    return wl


# per-command positional spec: (min_positional_args, one-line usage).
# lets a bare/short `watchmen.py CMD` print a clean usage line instead of an
# IndexError traceback, and gives every command its own -h/--help.
JIGGLE_MODELS = ("solver", "pivot", "pinned")  # jiggle_d6.MODELS; "solver" is the default
_JM = "|".join(JIGGLE_MODELS)

USAGE = {
    "all": (
        2,
        "all NAZ OUT [--no-vertex-attrs] [--materials engine|legacy] [--no-text] [--no-nav]"
        " [--rig hierarchy|flat] [--glb-texture-size N] [--frame true|mirrored] [--names canonical|stored] [--jiggle-model %s]"
        " [--json-floats exact|rounded] [--face-rule engine|legacy] [--no-face-idle] [--parts game|all] [--no-ragdoll]"
        % _JM,
    ),
    "extract": (
        2,
        "extract NAZ OUT [--vgmstream-cli PATH] [--keep-xma] [--glb [--no-vertex-attrs]"
        " [--rig hierarchy|flat] [--glb-texture-size N] ...] [--materials engine|legacy] [--no-text] [--no-nav] [--frame true|mirrored] [--names canonical|stored]"
        " [--json-floats exact|rounded] [--quiet]",
    ),
    "binds": (2, "binds NAZ OUT_DIR"),
    "charlibs": (
        2,
        "charlibs EXTRACT_OUT OUT_DIR [NAZ] [--no-vertex-attrs] [--materials engine|legacy]"
        " [--rig hierarchy|flat] [--frame true|mirrored] [--names canonical|stored]",
    ),
    "faces": (
        2,
        "faces EXTRACT_OUT OUT_DIR [--no-vertex-attrs] [--materials engine|legacy]"
        " [--rig hierarchy|flat] [--frame true|mirrored] [--names canonical|stored]",
    ),
    "animmeta": (
        2,
        "animmeta EXTRACT_OUT OUT.json [BINDS_DIR] [--frame true|mirrored] [--names canonical|stored]",
    ),
    "levelmeta": (
        2,
        "levelmeta EXTRACT_OUT OUT_DIR [LEVEL ...] [--frame true|mirrored] [--names canonical|stored]",
    ),
    "savemeta": (1, "savemeta FILE [OUT.json]"),
    "soundmeta": (
        2,
        "soundmeta EXTRACT_OUT OUT.json [ANIM_META.json] [--names canonical|stored]",
    ),
    "text": (2, "text NAZ OUT_DIR"),
    "textmeta": (2, "textmeta EXTRACT_OUT OUT.json"),
    "fxmeta": (
        2,
        "fxmeta EXTRACT_OUT OUT.json [ANIM_META.json] [--frame true|mirrored] [--names canonical|stored]",
    ),
    "particlemeta": (
        2,
        "particlemeta EXTRACT_OUT OUT_DIR [TEXTURES_DIR] [--names canonical|stored]",
    ),
    "scriptdb": (1, "scriptdb DATABASE.bin [OUT.json] [--find KEY ...]"),
    "characters": (
        2,
        "characters EXTRACT_OUT OUT_DIR [NAZ] [--jiggle-model %s]"
        " [--face-rule engine|legacy] [--no-face-idle] [--parts game|all] [--no-vertex-attrs]"
        " [--materials engine|legacy] [--no-ragdoll] [--rig hierarchy|flat] [--frame true|mirrored]"
        " [--names canonical|stored]" % _JM,
    ),
    "fragment": (1, "fragment FILE [OUT.json] [--json-floats exact|rounded]"),
    "ragdoll": (1, "ragdoll MODEL [PIVOTBOOK.pb] [OUT.json] [--frame true|mirrored]"),
    "bake": (3, "bake CLIPNAME BIND.npz OUT.npy [NAZ]"),
    "char": (
        3,
        "char FRAG.json VARIANT OUT.glb [BINDDIR [BAKEDIR [NAZ]]] [--jiggle-model %s] [--no-meta]"
        " [--no-vertex-attrs] [--materials engine|legacy] [--rig hierarchy|flat]"
        " [--frame true|mirrored] [--names canonical|stored]" % _JM,
    ),
    "grademeta": (
        2,
        "grademeta EXTRACT_OUT OUT.json [--names canonical|stored]",
    ),
    "navmeta": (2, "navmeta FILE_OR_DIR OUT_DIR [--frame true|mirrored]"),
    "hash": (1, "hash NAME"),
    "gendata": (
        1,
        "gendata strings|respell|regdump|propnames|keys-export|keys-import|check ...",
    ),
}


VERTEX_ATTR_COMMANDS = ("all", "characters", "char", "charlibs", "faces")
JIGGLE_COMMANDS = ("all", "characters", "char")
FACE_RULE_COMMANDS = ("all", "characters")
PARTS_COMMANDS = ("all", "characters")
PARTS_MODES = ("game", "all")
RAGDOLL_COMMANDS = ("all", "characters")
FACE_RULES = ("engine", "legacy")
MATERIALS_COMMANDS = ("all", "extract", "characters", "char", "charlibs", "faces")
MATERIALS_MODES = ("engine", "legacy")
# --rig hierarchy|flat: the skeleton layout of the rigged GLBs (variant_glb.RIG_MODES)
RIG_COMMANDS = ("all", "extract", "characters", "char", "charlibs", "faces")
RIG_MODES = ("hierarchy", "flat")
# --frame true|mirrored: every command that writes GLBs or data in the GLBs' frame
FRAME_COMMANDS = (
    "all",
    "extract",
    "characters",
    "char",
    "charlibs",
    "faces",
    "animmeta",
    "fxmeta",
    "levelmeta",
    "navmeta",
    "ragdoll",
)
FRAME_MODES = ("true", "mirrored")  # frame.MODES; "true" is the default
# --names canonical|stored: every command that writes paths or names taken from asset names
NAMES_COMMANDS = (
    "all",
    "extract",
    "characters",
    "char",
    "charlibs",
    "faces",
    "particlemeta",
    "levelmeta",
    "animmeta",
    "soundmeta",
    "fxmeta",
    "grademeta",
)
NAMES_MODES = ("canonical", "stored")  # canonical_names.MODES; "canonical" is the default
# --json-floats exact|rounded: the commands that write fragment / sequence / property-bag JSON
JSON_FLOATS_COMMANDS = ("all", "extract", "fragment")
JSON_FLOATS_MODES = ("exact", "rounded")  # f32json.MODES; "exact" is the default


# ---- the options of the commands, as one table ------------------------------------
#
# Each option: the flag, its values (a tuple of choices, "N" for an integer the
# command checks itself, None for a switch), the commands it applies to, the
# environment variable it sets (and the value a switch sets), the commands that get
# the token(s) passed on unchanged (the extractor parses them itself), and a help
# line.  main() consumes the options with this table; `watchmen.py CMD -h` prints
# CMD's usage and the options of CMD, from argparse parsers built of one parent
# parser per option.


class Option:
    __slots__ = (
        "flag",
        "values",
        "commands",
        "env",
        "env_value",
        "env_commands",
        "keep",
        "label",
        "help",
    )

    def __init__(
        self,
        flag,
        values,
        commands,
        env=None,
        env_value=None,
        env_commands=None,
        keep=(),
        label=None,
        help="",
    ):
        self.flag, self.values, self.commands = flag, values, tuple(commands)
        self.env, self.env_value = env, env_value
        self.env_commands = self.commands if env_commands is None else tuple(env_commands)
        self.keep, self.label, self.help = tuple(keep), label, help

    def applies_message(self):
        if self.label:  # two flags that share one message (--face-rule / --no-face-idle)
            return "error: %s apply to: %s" % (self.label, ", ".join(self.commands))
        return "error: %s applies to: %s" % (self.flag, ", ".join(self.commands))


OPTIONS = (
    Option(
        "--jiggle-model",
        JIGGLE_MODELS,
        JIGGLE_COMMANDS,
        help="bake the jiggle bones with this model (default: solver)",
    ),
    Option(
        "--no-vertex-attrs",
        None,
        ("extract",) + VERTEX_ATTR_COMMANDS,
        env="WATCHMEN_VERTEX_ATTRS",
        env_value="0",
        env_commands=VERTEX_ATTR_COMMANDS,
        keep=("extract", "all"),
        help="GLBs without NORMAL / TANGENT / COLOR_0 (the 1.3.0 files)",
    ),
    Option(
        "--face-rule",
        FACE_RULES,
        FACE_RULE_COMMANDS,
        env="WATCHMEN_FACE_RULE",
        label="--face-rule / --no-face-idle",
        help="the face track of the body clips: engine (default) or the 1.3.0 rule",
    ),
    Option(
        "--no-face-idle",
        None,
        FACE_RULE_COMMANDS,
        env="WATCHMEN_FACE_IDLE",
        env_value="0",
        label="--face-rule / --no-face-idle",
        help="leave the seeded idle cycle out of the baked face track",
    ),
    Option(
        "--parts",
        PARTS_MODES,
        PARTS_COMMANDS,
        env="WATCHMEN_PARTS",
        help="which models a character GLB shows: what the game shows (default) or all",
    ),
    Option(
        "--materials",
        MATERIALS_MODES,
        MATERIALS_COMMANDS,
        env="WATCHMEN_MATERIALS",
        help="glTF materials from the texture sheets (engine, default) or as before",
    ),
    Option(
        "--rig",
        RIG_MODES,
        RIG_COMMANDS,
        env="WATCHMEN_RIG",
        help="skeleton of the rigged GLBs: one node per bone, parented (default), "
        "or the flat layout of 1.4.0",
    ),
    Option(
        "--glb-texture-size",
        "N",
        ("all", "extract"),
        keep=("all", "extract"),
        help="extract --glb: shrink the embedded textures to at most N x N "
        "(default: their full size; 512 gives the 1.4.0 images)",
    ),
    Option(
        "--frame",
        FRAME_MODES,
        FRAME_COMMANDS,
        env="WATCHMEN_FRAME",
        help="coordinate frame: true (default, as the game looks) or mirrored (engine numbers)",
    ),
    Option(
        "--names",
        NAMES_MODES,
        NAMES_COMMANDS,
        env="WATCHMEN_NAMES",
        help="asset path spelling: canonical (default) or as each archive stores it",
    ),
    Option(
        "--json-floats",
        JSON_FLOATS_MODES,
        JSON_FLOATS_COMMANDS,
        env="WATCHMEN_JSON_FLOATS",
        help="decoded JSON floats: exact float32 values (default) or rounded as in 1.4.0",
    ),
    Option(
        "--no-ragdoll",
        None,
        RAGDOLL_COMMANDS,
        env="WATCHMEN_RAGDOLL",
        env_value="0",
        help="character GLBs without the ragdoll helpers and .ragdoll.json",
    ),
    Option("--no-meta", None, ("char",), help="no clip metadata (the GLB of 1.3.0)"),
)
_OPTION = {o.flag: o for o in OPTIONS}

#: commands that hand every other option to a parser of their own: the extractor
#: (`extract`, and `all`, which runs it first) and `gendata`
PASSTHROUGH_COMMANDS = ("extract", "all", "gendata")
#: options a command's own reader takes (handed on unchanged)
OWN_OPTIONS = {"scriptdb": ("--find",)}


class OptionError(Exception):
    """A command-line option the command does not take; str() is the message."""


def move_out_option(args):
    """`extract` / `all`: OUT given as `-o OUT`, `--out OUT` or `--out=OUT` (the
    extractor's own spelling, which `extract -h` shows) -> the second positional
    argument, after NAZ.  OptionError when it has no value or OUT is given twice."""
    out, rest, i = None, [], 0
    while i < len(args):
        a = args[i]
        if a in ("-o", "--out"):
            if i + 1 >= len(args) or args[i + 1].startswith("-"):
                raise OptionError("error: %s needs the output folder" % a)
            val, i = args[i + 1], i + 2
        elif a.startswith("--out="):
            val, i = a.removeprefix("--out="), i + 1
        else:
            rest.append(a)
            i += 1
            continue
        if out is not None:
            raise OptionError("error: the output folder is given twice")
        out = val
    if out is None:
        return list(args)
    if len(rest) > 1 and not rest[1].startswith("-"):
        raise OptionError("error: the output folder is given twice (%s and %s)" % (rest[1], out))
    return rest[:1] + [out] + rest[1:]


def parse_options(cmd, args, env=None):
    """Consume the table's options of `cmd` from `args` -> (remaining args, {flag:
    value}).  Options in `keep` stay in the remaining args, in place; the environment
    variables are set in `env` (default os.environ) only when the whole line is
    valid.  OptionError: an option of another command, a value that is not one of
    the choices, or an unknown --option of a command that has no parser of its
    own."""
    env = os.environ if env is None else env
    rest, values, setenv = [], {}, []
    i = 0
    while i < len(args):
        a = args[i]
        opt = _OPTION.get(a)
        if opt is None:
            if (
                a.startswith("--")
                and len(a) > 2
                and cmd not in PASSTHROUGH_COMMANDS
                and a not in OWN_OPTIONS.get(cmd, ())
            ):
                raise OptionError(
                    "error: unknown option %s for %s (see `watchmen.py %s -h`)" % (a, cmd, cmd)
                )
            rest.append(a)
            i += 1
            continue
        if cmd not in opt.commands:
            raise OptionError(opt.applies_message())
        if opt.values is None:  # a switch
            value, n = True, 1
        else:
            value, n = (args[i + 1] if i + 1 < len(args) else None), 2
            if isinstance(opt.values, tuple) and value not in opt.values:
                raise OptionError("error: %s takes one of: %s" % (opt.flag, ", ".join(opt.values)))
        if cmd in opt.keep:
            rest.extend(args[i : i + n])
        values[opt.flag] = value
        if opt.env and cmd in opt.env_commands:
            setenv.append((opt.env, opt.env_value if opt.values is None else value))
        i += n
    for k, v in setenv:
        env[k] = v
    return rest, values


def _command_help():
    """{command: its description lines} from the Commands list of this module's
    docstring (the text in the description column; the usage continuation lines,
    `[--option ...]`, are left out)."""
    col = 33  # the description column of the list
    out, cur = {}, None
    for line in __doc__.split("Exit codes\n----------")[0].splitlines():
        if line.startswith("  ") and not line.startswith("   ") and line[2:3].isalpha():
            cur = line[2:].split(" ", 1)[0]
            out.setdefault(cur, [])
        elif not (cur and line.startswith(" " * col)):
            cur = None
            continue
        text = line[col:].strip() if len(line) > col and line[col - 1] == " " else ""
        if text and not text.startswith("["):
            out[cur].append(text)
    return out


def command_parser(cmd):
    """The argparse parser that documents `cmd`: its usage line, its description from
    the docstring and one parent parser per option of the table that applies to it
    (used for `watchmen.py CMD -h`; main() parses with parse_options)."""
    import argparse

    parents = []
    for o in OPTIONS:
        if cmd not in o.commands:
            continue
        p = argparse.ArgumentParser(add_help=False)
        if o.values is None:
            p.add_argument(o.flag, action="store_true", help=o.help)
        elif isinstance(o.values, tuple):
            p.add_argument(o.flag, choices=o.values, help=o.help)
        else:
            p.add_argument(o.flag, metavar=o.values, type=int, help=o.help)
        parents.append(p)
    desc = "\n".join(_command_help().get(cmd, [])) or None
    epilog = None
    if cmd == "all":
        epilog = "Every option of `extract` (see `watchmen.py extract -h`) is passed on to its first step."
    elif cmd == "gendata":
        epilog = "The sub-commands take options of their own: see `watchmen.py gendata` without arguments."
    elif cmd in OWN_OPTIONS:
        epilog = "Also: %s (read by the command itself, see the usage line)." % ", ".join(
            OWN_OPTIONS[cmd]
        )
    return argparse.ArgumentParser(
        prog="watchmen.py " + cmd,
        usage="watchmen.py " + USAGE[cmd][1],
        description=desc,
        epilog=epilog,
        parents=parents,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )


def extract_out_of(path):
    """The EXTRACT_OUT directory a file lies in (the parent of its `extracted`
    ancestor), or None."""
    p = os.path.abspath(path)
    while True:
        parent = os.path.dirname(p)
        if parent == p:
            return None
        if os.path.basename(p).lower() == "extracted":
            return parent
        p = parent


def char_clip_bank(frag):
    """{clip name: .animation path} of the EXTRACT_OUT the fragment lies in ({} when it
    lies somewhere else): `char` takes each clip's duration from it, because a bake
    written by `watchmen bake` holds the palettes only."""
    ex = extract_out_of(frag)
    if ex is None:
        return {}
    import glob

    bank = {}
    for f in sorted(
        glob.glob(os.path.join(ex, "extracted", "Animation", "**", "*.animation"), recursive=True)
    ):
        bank.setdefault(os.path.basename(f)[: -len(".animation")].strip(), f)
    return bank


def stored_char_meta(ex):
    """(table, path) of an anim_meta.json a `characters` export left under EXTRACT_OUT
    (EXTRACT_OUT/<any folder>/anim_meta.json) that this toolkit would write again
    (characters_export.anim_meta_is_current), or (None, None)."""
    import glob
    import json

    import characters_export

    for path in sorted(glob.glob(os.path.join(ex, "*", "anim_meta.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                m = json.load(fh)
        except (OSError, ValueError):
            continue
        if characters_export.anim_meta_is_current(m, ex):
            return m, path
    return None, None


def char_meta(frag, binddir=None):
    """Animation metadata for `char`: the table of the EXTRACT_OUT the fragment lies
    in -- a current anim_meta.json of a `characters` export there when one exists,
    else built now (as `characters` does) -- or None when the fragment is somewhere
    else or that tree has no animation classes."""
    ex = extract_out_of(frag)
    if ex is None:
        print("  char: %s is not under an EXTRACT_OUT/extracted tree -- no clip metadata" % frag)
        return None
    try:
        import anim_meta

        if not anim_meta.find_class_fragments(ex):
            print("  char: no animation classes under %s -- no clip metadata" % ex)
            return None
        m, path = stored_char_meta(ex)
        if m is not None:
            print("  char: clip metadata from %s (%s)" % (path, anim_meta.summary(m)))
            return m
        bdir = binddir if binddir and os.path.isdir(binddir) else os.path.join(ex, "binds")
        m = anim_meta.build(ex, binds=bdir if os.path.isdir(bdir) else None)
    except Exception as e:  # optional decoration: never stops the export
        print("  char: clip metadata skipped (%s: %s)" % (type(e).__name__, e))
        return None
    print("  char: clip metadata from %s (%s)" % (ex, anim_meta.summary(m)))
    return m


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0 if len(argv) >= 2 else 1
    if argv[1] in ("-V", "--version", "version"):
        print("watchmen-kapow-toolkit %s" % VERSION)
        return 0
    cmd, args = argv[1], argv[2:]
    if cmd not in USAGE:
        print("unknown command %r" % cmd, file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 1
    if "-h" in args or "--help" in args:
        if cmd == "extract":
            # forward to the extractor's argparse help (shows --vgmstream-cli, --glb, ...),
            # after the command's own usage line: OUT is the second argument here
            import watchmen_extract as _we

            print("usage: watchmen.py %s" % USAGE[cmd][1])
            print("OUT is the second argument (or -o / --out OUT). The extractor's options:\n")
            return _we.main(["--help"])
        command_parser(cmd).print_help()
        return 0
    try:
        if cmd in ("extract", "all"):
            args = move_out_option(args)
        args, opts = parse_options(cmd, args)
    except OptionError as ex:
        print(ex)
        print("usage: watchmen.py %s" % USAGE[cmd][1])
        return 2
    jiggle_model = opts.get("--jiggle-model")
    no_meta = bool(opts.get("--no-meta"))
    need = USAGE[cmd][0]
    if len(args) < need:
        print("usage: watchmen.py %s" % USAGE[cmd][1])
        print("  (%s takes at least %d argument%s)" % (cmd, need, "" if need == 1 else "s"))
        return 2

    # hash + gendata are dispatched BEFORE _wl(): neither needs the facade
    # (numpy, Pillow, the pickled tables), and `gendata keys-import` is the
    # documented recovery path when kapow_fragment_keys.pkl is MISSING -- it
    # must not die on the very import error it exists to fix.
    if cmd == "hash":
        import kapow_props

        # same convention as wl.kapow_hash: bytes & 0xDF, engine FUN_00423ce8
        print("%08x" % kapow_props.name_hash(args[0]))
        return 0
    if cmd == "gendata":
        import gen_data

        return gen_data.main(["gen_data"] + args)

    wl = _wl()

    if cmd == "extract":
        naz, out = args[0], args[1]
        rc = wl.extract_all(naz, out, *args[2:])  # extras: e.g. --vgmstream-cli PATH
        if rc:
            return rc  # the extractor's exit code (2: archive not found, bad option)

    elif cmd == "all":
        naz, out = args[0], args[1]
        print("[1/3] extract %s -> %s" % (naz, out))
        rc = wl.extract_all(naz, out, *args[2:])
        if rc:
            print(
                "error: the extract step failed (exit code %d); binds and characters not run" % rc
            )
            return rc
        # binds + character glbs work on console too: the
        # skeleton/mesh/skin decoders are byte-order aware (X360/PS3 = BE).
        print("[2/3] binds -> %s/binds" % out)
        wl.ensure_binds(naz, os.path.join(out, "binds"), extract_dir=out)
        chars = os.path.join(out, "characters")
        print("[3/3] character glbs -> %s (the `characters` export)" % chars)
        rc = run_characters(out, chars, naz, jiggle_model)
        print("done.")
        return rc

    elif cmd == "characters":
        exout, outdir = args[0], args[1]
        import bake_v4

        naz = args[2] if len(args) > 2 else bake_v4.default_naz()
        return run_characters(exout, outdir, naz, jiggle_model)

    elif cmd == "ragdoll":
        import ragdoll_rig

        rig = ragdoll_rig.build(_read_bytes(args[0]))
        if rig is None:
            print("error: %s has no articulated body with joints" % args[0])
            return 1
        rest = args[1:]
        mat = None
        if rest and rest[0].lower().endswith(".pb"):
            mat = ragdoll_rig.material_from_pivot_book(_read_bytes(rest[0]))
            rest = rest[1:]
        doc = ragdoll_rig.sidecar(rig, material=mat, source_model=os.path.basename(args[0]))
        if rest:
            with open(rest[0], "w", encoding="utf-8", newline="\n") as f:
                json.dump(doc, f, indent=1)
            print(
                "wrote %s (%d bodies, %d joints, total mass %g, tuned=%s)"
                % (rest[0], len(rig["bodies"]), len(rig["joints"]), rig["total_mass"], rig["tuned"])
            )
        else:
            json.dump(doc, sys.stdout, indent=1)
            print()

    elif cmd == "faces":
        import face_export

        face_export.export(args[0], args[1])

    elif cmd == "animmeta":
        import anim_meta

        binds = args[2] if len(args) > 2 else os.path.join(args[0], "binds")
        meta = anim_meta.write(args[0], args[1], binds=binds if os.path.isdir(binds) else None)
        print("wrote %s: %s" % (args[1], anim_meta.summary(meta)))

    elif cmd == "levelmeta":
        import level_meta

        try:
            done = level_meta.write(args[0], args[1], only=args[2:] or None)
        except FileNotFoundError as e:
            print("error: %s" % e, file=sys.stderr)
            return 2
        print("wrote %d level file(s) to %s" % (len(done), args[1]))

    elif cmd == "savemeta":
        import level_meta

        try:
            j = level_meta.read_save(args[0])
        except (OSError, ValueError) as e:
            print("error: %s: %s" % (args[0], e), file=sys.stderr)
            return 2
        out = args[1] if len(args) > 1 else args[0] + ".json"
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(j, indent=1))
        raw = sum(1 for r in j["records"] if "raw_words" in r)
        print("wrote %s: %r, %d records (%d undecoded)" % (out, j["title"], len(j["records"]), raw))
    elif cmd == "text":
        import text_assets

        if text_assets.extract_text(args[0], args[1]) is None:
            print("error: no text assets found in %s" % args[0], file=sys.stderr)
            return 2

    elif cmd == "textmeta":
        import text_assets

        meta = text_assets.write(args[0], args[1])
        print("wrote %s: %s" % (args[1], text_assets.summary(meta)))

    elif cmd == "soundmeta":
        import sound_meta

        anim = args[2] if len(args) > 2 else None
        if anim is None:
            import anim_meta

            anim = anim_meta.build(args[0]) if anim_meta.find_class_fragments(args[0]) else None
        meta = sound_meta.write(args[0], args[1], anim=anim)
        print("wrote %s: %s" % (args[1], sound_meta.summary(meta)))

    elif cmd == "fxmeta":
        import fx_meta

        meta = fx_meta.write(args[0], args[1], args[2] if len(args) > 2 else None)
        print("wrote %s: %s" % (args[1], fx_meta.summary(meta)))

    elif cmd == "particlemeta":
        import particle_meta

        return particle_meta.main(args[:3])

    elif cmd == "scriptdb":
        import script_database

        return script_database.main(args)

    elif cmd == "charlibs":
        exout, outdir = args[0], args[1]
        import extract_out

        extract_out.require(exout)
        import bake_v4

        binds = wl.ensure_binds(
            args[2] if len(args) > 2 else bake_v4.default_naz(),
            os.path.join(exout, "binds"),
            extract_dir=exout,
        )
        import char_lib

        char_lib.build_all(exout, binds, outdir)

    elif cmd == "binds":
        naz, out = args[0], args[1]
        r = wl.ensure_binds(naz, out)
        for k, v in sorted(r.items()):
            print("%-8s %s" % (k, v))

    elif cmd == "grademeta":
        import materials as _mt
        import extract_out

        extract_out.require(args[0])
        g = _mt.level_grades(args[0], wl.fragment_json_file)
        import canonical_names

        canonical_names.respell_export(g, args[0])  # texture strings as the folders are written
        with open(args[1], "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(g, indent=1) + "\n")
        print(
            "wrote %s (%d fragments, %d GFX nodes)"
            % (args[1], len(g["fragments"]), sum(len(v) for v in g["fragments"].values()))
        )
    elif cmd == "navmeta":
        import nav_data

        return nav_data.main(args[:2])
    elif cmd == "fragment":
        j = wl.fragment_json_file(args[0])
        if j is None:
            print("error: %s is not a recognized Kapow asset type" % args[0], file=sys.stderr)
            return 2
        out = args[1] if len(args) > 1 else args[0] + ".json"
        import f32json

        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f32json.dumps(j, indent=1))  # exact mode: NaN / infinity -> null
        print("wrote", out, "(lossless:", j.get("lossless"), ")")
        if j.get("lossless") is False:
            print("warning: parse was not lossless -- see the 'warn' key", file=sys.stderr)
            return 3

    elif cmd == "bake":
        clip, bind, out = args[0], args[1], args[2]
        import numpy as np

        pal, dur = wl.bake(clip, bind, naz=args[3] if len(args) > 3 else None)
        np.save(out, pal)
        print("baked %s %s dur %.2fs -> %s" % (clip, pal.shape, dur, out))

    elif cmd == "char":
        frag, variant, out = args[0], args[1], args[2]
        kw = {}
        if len(args) > 3:
            kw["binddir"] = args[3]
        if len(args) > 4:
            kw["bakedir"] = args[4]
        if len(args) > 5:
            kw["naz"] = args[5]
        import bake_v4

        if not os.path.exists(kw.get("naz") or bake_v4.default_naz()):
            print(
                "error: `char` reads the meshes from the archive %r, which does not exist:"
                " name it (char FRAG.json VARIANT OUT.glb BINDDIR BAKEDIR NAZ)"
                % (kw.get("naz") or bake_v4.default_naz())
            )
            return 2
        bank = char_clip_bank(frag)
        if bank:  # the clips' real lengths (a bake holds no duration)
            kw["bank"] = bank
        else:
            print(
                "  char: %s is not under an EXTRACT_OUT/extracted tree -- the clips' lengths"
                " are not known, every clip is written at 30 fps" % frag
            )
        if jiggle_model is not None:
            kw.update(jiggle=True, jiggle_model=jiggle_model)
            if extract_out_of(frag) is not None:
                kw["extract_root"] = extract_out_of(frag)  # its PhysicsWorld values
        if not no_meta:
            kw["meta"] = char_meta(frag, kw.get("binddir"))
        wl.build_variant_glb(frag, variant, out, **kw)

    else:
        print("unknown command %r" % cmd)
        print(__doc__)
        return 1
    return 0


def run_characters(exout, outdir, naz, jiggle_model=None):
    """`characters` (also step 3 of `all`): the character export and its sound_meta.json;
    exit code 0 (bakes still pending are reported, a rerun continues them)."""
    import characters_export

    pending = characters_export.export(exout, outdir, naz, jiggle_model=jiggle_model)
    pending = pending if isinstance(pending, int) else len(pending or ())
    print("pending bakes: %d%s" % (pending, " -- rerun to continue" if pending else " -- complete"))
    write_sound_meta(exout, outdir)
    return 0


def write_sound_meta(extract_out, outdir):
    """OUT_DIR/sound_meta.json next to the anim_meta.json that `characters`
    writes (a sidecar: sounds are not per clip, and the table would grow
    anim_meta.json by half).  Kept when it is already there in this format; a
    failure is reported, not fatal -- the glbs do not depend on it."""
    path = os.path.join(outdir, "sound_meta.json")
    try:
        import sound_meta

        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                if json.load(fh).get("format") == sound_meta.FORMAT:
                    return path
        am = os.path.join(outdir, "anim_meta.json")
        meta = sound_meta.build(extract_out, anim=am if os.path.exists(am) else None)
        if not meta["definitions"]:
            return None  # an extract without sound fragments
        os.makedirs(outdir, exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8", newline="\n") as fh:
            json.dump(meta, fh, indent=1)
        os.replace(path + ".tmp", path)
        print("sound_meta: %s" % sound_meta.summary(meta))
        return path
    except Exception as ex:
        print("  sound_meta: skipped (%s: %s)" % (type(ex).__name__, ex))
        return None


def debug_enabled(env=None):
    """True when $WATCHMEN_DEBUG is set to anything but '' or '0'."""
    v = (os.environ if env is None else env).get("WATCHMEN_DEBUG", "")
    return v.strip() not in ("", "0")


def cli():
    """Console-script entry point (``watchmen`` / ``watchmen-kapow`` after ``pip install``)."""
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, struct.error, ImportError) as ex:
        # bad path / wrong file type / truncated asset / missing data table:
        # an actionable line, not a traceback (truncated propbags raise
        # struct.error, and kapow_fragment raises ImportError for a missing
        # key table).
        # WATCHMEN_DEBUG=1 prints the traceback first: where it happened.
        # The notes of the error (where it happened: archive entry, offset, asset)
        # go under the `error:` line; the traceback already ends with them, so they
        # are printed once either way.
        debug = debug_enabled()
        if debug:
            import traceback

            traceback.print_exc()
        print("error: %s" % ex, file=sys.stderr)
        if not debug:
            for note in getattr(ex, "__notes__", ()):
                print("  %s" % note, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    cli()
