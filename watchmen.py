#!/usr/bin/env python3
"""watchmen — CLI for the Watchmen: The End Is Nigh asset-extraction toolkit
(Parts 1 & 2; PC, Xbox 360, PS3).

The master-script functionality without the spaghetti. All real logic lives in
wlib/ (see watchmenlib.py facade); this is just the CLI.

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
                                 --flat-music gives the single file of 1.3.0,
                                 --music-track-labels adds the MusicStreamSlot
                                 track names to the file names, --smpl-loops adds
                                 a RIFF smpl loop to looping sounds.  Sound facts
                                 (rate, loop flag, length) go to
                                 audio/sound_info.json.  Also written: text/ (every
                                 text asset in every language, see `text`;
                                 --no-text) and nav/ (the levels' navigation data,
                                 see `navmeta`; --no-nav).
  binds NAZ OUT_DIR              Build engine-exact FILE-ONLY binds for all skeletons
  charlibs EXTRACT_OUT OUT_DIR   Textured+animated character-library glbs (needs extract+binds)
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
                                 `pinned`, the default up to 1.3.0; each has its
                                 own cache directory.
                                 --face-rule (also $WATCHMEN_FACE_RULE):
                                 `engine` (default): every body clip carries the
                                 face track the game plays with it, read from the
                                 face animation classes (see anim_meta.json "face");
                                 `legacy`: the rule of 1.3.0 (pose guessed from the
                                 clip name, synthetic blinks, no face rig on the
                                 Thug / Gimp characters).  --no-face-idle (also
                                 $WATCHMEN_FACE_IDLE=0) leaves the seeded idle
                                 cycle (the game's random blink / fidget) out of
                                 the baked track.  --jiggle-model pinned
                                 --face-rule legacy --no-vertex-attrs together give
                                 the animation and mesh data of 1.3.0; textures
                                 are still found by the path the model stores.
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
                                 model and every weapon at once, as before.
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
                                 materials as before (GLB and MTL byte-identical).
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
                                 verbatim, a mirror image -- what 1.3.0 wrote; no
                                 coordinate_frame key, files byte-identical to the
                                 output before this option existed.  Raw engine
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
  fragment FILE [OUT.json]       Lossless .fragment -> JSON
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
                                 every clip baked as non-looping, as in 1.3.0.
                                 The GLB has flat materials: no textures, no
                                 tangents, no face rig or face channels, no weapons
                                 and no ragdoll helpers (use `characters` for the
                                 full character).
  hash NAME                      Kapow property-key hash of a name
  --version                      Print the toolkit version and exit
  gendata SUBCMD ...             Regenerate wlib's data tables from a game
                                 install (strings/respell/regdump/propnames/keys-export/
                                 keys-import/check; see gendata -h)

Examples
--------
  python3 watchmen.py all game.naz OUT      # fresh install -> everything
  python3 watchmen.py extract game.naz OUT
  python3 watchmen.py fragment OUT/extracted/.../Gimp.fragment
  python3 watchmen.py char Gimp.fragment.json Gimp2 CHAR_Gimp2.glb
"""

import os, sys, json, struct

# append, never insert(0): wlib holds flat, generically-named modules
# (char_lib, gen_data, engine_schema, ...) that must not shadow the stdlib.
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "wlib"))

try:
    from wlib import __version__ as VERSION
except Exception:  # running from a source checkout without the package installed
    VERSION = "1.4.0"


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


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
        " [--frame true|mirrored] [--names canonical|stored] [--jiggle-model %s]"
        " [--face-rule engine|legacy] [--no-face-idle] [--parts game|all] [--no-ragdoll]" % _JM,
    ),
    "extract": (
        2,
        "extract NAZ OUT [--vgmstream-cli PATH] [--keep-xma] [--glb [--no-vertex-attrs] ...]"
        " [--materials engine|legacy] [--no-text] [--no-nav] [--frame true|mirrored] [--names canonical|stored]",
    ),
    "binds": (2, "binds NAZ OUT_DIR"),
    "charlibs": (
        2,
        "charlibs EXTRACT_OUT OUT_DIR [NAZ] [--no-vertex-attrs] [--materials engine|legacy] [--frame true|mirrored] [--names canonical|stored]",
    ),
    "faces": (
        2,
        "faces EXTRACT_OUT OUT_DIR [--no-vertex-attrs] [--materials engine|legacy] [--frame true|mirrored] [--names canonical|stored]",
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
        " [--materials engine|legacy] [--no-ragdoll] [--frame true|mirrored] [--names canonical|stored]"
        % _JM,
    ),
    "fragment": (1, "fragment FILE [OUT.json]"),
    "ragdoll": (1, "ragdoll MODEL [PIVOTBOOK.pb] [OUT.json] [--frame true|mirrored]"),
    "bake": (3, "bake CLIPNAME BIND.npz OUT.npy [NAZ]"),
    "char": (
        3,
        "char FRAG.json VARIANT OUT.glb [BINDDIR [BAKEDIR [NAZ]]] [--jiggle-model %s] [--no-meta]"
        " [--no-vertex-attrs] [--materials engine|legacy] [--frame true|mirrored] [--names canonical|stored]"
        % _JM,
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
            # forward to the extractor's argparse help (shows --vgmstream-cli, --glb, ...)
            import watchmen_extract as _we

            return _we.main(["--help"])
        print("usage: watchmen.py %s" % USAGE[cmd][1])
        return 0
    jiggle_model = None
    if "--jiggle-model" in args:
        i = args.index("--jiggle-model")
        value = args[i + 1] if i + 1 < len(args) else None
        if cmd not in JIGGLE_COMMANDS or value not in JIGGLE_MODELS:
            if cmd not in JIGGLE_COMMANDS:
                print("error: --jiggle-model applies to: %s" % ", ".join(JIGGLE_COMMANDS))
            else:
                print("error: --jiggle-model takes one of: %s" % ", ".join(JIGGLE_MODELS))
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        jiggle_model = value
        args = args[:i] + args[i + 2 :]
    # --no-vertex-attrs: GLBs without NORMAL / TANGENT / COLOR_0 (the 1.3.0 files).
    # `extract` hands it to the extractor's own parser; the character commands
    # switch variant_glb's writer.
    if "--no-vertex-attrs" in args and cmd != "extract":
        if cmd not in VERTEX_ATTR_COMMANDS:
            print(
                "error: --no-vertex-attrs applies to: extract, %s" % ", ".join(VERTEX_ATTR_COMMANDS)
            )
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        os.environ["WATCHMEN_VERTEX_ATTRS"] = "0"
        if cmd != "all":  # `all` also forwards it to its extract step
            args = [a for a in args if a != "--no-vertex-attrs"]
    # --face-rule engine|legacy / --no-face-idle: the face channels `characters`
    # bakes into body clips (face_rule.rule / face_rule.idle_enabled read these).
    if "--face-rule" in args or "--no-face-idle" in args:
        value = "engine"
        if "--face-rule" in args:
            i = args.index("--face-rule")
            value = args[i + 1] if i + 1 < len(args) else None
            args = args[:i] + args[i + 2 :]
        if cmd not in FACE_RULE_COMMANDS or value not in FACE_RULES:
            if cmd not in FACE_RULE_COMMANDS:
                print(
                    "error: --face-rule / --no-face-idle apply to: %s"
                    % ", ".join(FACE_RULE_COMMANDS)
                )
            else:
                print("error: --face-rule takes one of: %s" % ", ".join(FACE_RULES))
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        os.environ["WATCHMEN_FACE_RULE"] = value
        if "--no-face-idle" in args:
            os.environ["WATCHMEN_FACE_IDLE"] = "0"
            args = [a for a in args if a != "--no-face-idle"]
    # --parts game|all: which of a variant's models the character GLBs show
    if "--parts" in args:
        i = args.index("--parts")
        value = args[i + 1] if i + 1 < len(args) else None
        if cmd not in PARTS_COMMANDS or value not in PARTS_MODES:
            if cmd not in PARTS_COMMANDS:
                print("error: --parts applies to: %s" % ", ".join(PARTS_COMMANDS))
            else:
                print("error: --parts takes one of: %s" % ", ".join(PARTS_MODES))
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        os.environ["WATCHMEN_PARTS"] = value
        args = args[:i] + args[i + 2 :]
    # --materials engine|legacy: wlib/materials.py reads $WATCHMEN_MATERIALS
    if "--materials" in args:
        i = args.index("--materials")
        value = args[i + 1] if i + 1 < len(args) else None
        if cmd not in MATERIALS_COMMANDS or value not in MATERIALS_MODES:
            if cmd not in MATERIALS_COMMANDS:
                print("error: --materials applies to: %s" % ", ".join(MATERIALS_COMMANDS))
            else:
                print("error: --materials takes one of: %s" % ", ".join(MATERIALS_MODES))
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        os.environ["WATCHMEN_MATERIALS"] = value
        args = args[:i] + args[i + 2 :]
    # --frame true|mirrored: wlib/frame.py reads $WATCHMEN_FRAME
    if "--frame" in args:
        i = args.index("--frame")
        value = args[i + 1] if i + 1 < len(args) else None
        if cmd not in FRAME_COMMANDS or value not in FRAME_MODES:
            if cmd not in FRAME_COMMANDS:
                print("error: --frame applies to: %s" % ", ".join(FRAME_COMMANDS))
            else:
                print("error: --frame takes one of: %s" % ", ".join(FRAME_MODES))
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        os.environ["WATCHMEN_FRAME"] = value
        args = args[:i] + args[i + 2 :]
    # --names canonical|stored: wlib/canonical_names.py reads $WATCHMEN_NAMES
    if "--names" in args:
        i = args.index("--names")
        value = args[i + 1] if i + 1 < len(args) else None
        if cmd not in NAMES_COMMANDS or value not in NAMES_MODES:
            if cmd not in NAMES_COMMANDS:
                print("error: --names applies to: %s" % ", ".join(NAMES_COMMANDS))
            else:
                print("error: --names takes one of: %s" % ", ".join(NAMES_MODES))
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        os.environ["WATCHMEN_NAMES"] = value
        args = args[:i] + args[i + 2 :]
    # --no-ragdoll: character GLBs without the ragdoll helper nodes and sidecar
    if "--no-ragdoll" in args:
        if cmd not in RAGDOLL_COMMANDS:
            print("error: --no-ragdoll applies to: %s" % ", ".join(RAGDOLL_COMMANDS))
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        os.environ["WATCHMEN_RAGDOLL"] = "0"
        args = [a for a in args if a != "--no-ragdoll"]
    # --no-meta: `char` without the animation metadata (as 1.3.0 wrote the file)
    no_meta = "--no-meta" in args
    if no_meta:
        if cmd != "char":
            print("error: --no-meta applies to: char")
            print("usage: watchmen.py %s" % USAGE[cmd][1])
            return 2
        args = [a for a in args if a != "--no-meta"]
    need = USAGE[cmd][0]
    if len(args) < need:
        print("usage: watchmen.py %s" % USAGE[cmd][1])
        print("  (%s takes at least %d argument%s)" % (cmd, need, "" if need == 1 else "s"))
        return 2

    # hash + gendata are dispatched BEFORE _wl(): neither needs the facade
    # (numpy, Pillow, the pickled tables), and `gendata keys-import` is the
    # documented recovery path when kapow_fragment_keys.pkl is MISSING -- it
    # must not die on the very import error it exists to fix (2026-08-17;
    # previously both ran after _wl() and paid/failed the full import).
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
        # binds + character glbs work on console too (2026-07-15): the
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
        binds = wl.ensure_binds(
            args[2] if len(args) > 2 else "game.naz",
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
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(j, indent=1))
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


def cli():
    """Console-script entry point (``watchmen`` after ``pip install``)."""
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, struct.error, ImportError) as ex:
        # bad path / wrong file type / truncated asset / missing data table:
        # an actionable line, not a traceback (struct.error + ImportError
        # added 2026-08-17: truncated propbags raise struct.error, and
        # kapow_fragment now raises ImportError for a missing key table)
        print("error: %s" % ex, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    cli()
