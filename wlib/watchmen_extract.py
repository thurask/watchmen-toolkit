#!/usr/bin/env python3
"""
watchmen_extract.py  --  master asset extractor for
*Watchmen: The End Is Nigh, Part 2* (Kapow engine, PC).

Feed it game.naz and it walks the whole reverse-engineered chain and writes:

    OUT/files/      every NAZ entry, decrypted & inflated (the raw asset tree)
    OUT/textures/   <asset>/<j>_<label>_<WxH>_<FMT>.png      (diffuse/normal/
                                                              specular/glossiness)
    OUT/models/     <asset>.obj (+ .mtl)                     (Model/ModelRes:
                    per-submesh objects, each material named by its texture and
                    linking diffuse->map_Kd normal->norm specular->map_Ks
                    glossiness->map_Ns from the textures/ dump above)
    OUT/audio/      <asset>.wav (SFX/voice, MS-ADPCM/PCM at the header's rate:
                    44100 mono, the file's own rate stereo); sound_info.json
                    (rate, length, loop flag, cue points of every sound)
    OUT/audio/      <name>_track<k>.mediastream_s.ogg        (.mediastream_s =
                    Vorbis; one file per track of a music stream) + <name>.json
                    (tracks, cue points, MusicSetup track states)
    OUT/extracted/  <asset> (+ .stream, + .json)             (every raw block asset)

Pipeline: see docs/WATCHMEN_EXTRACTION_MASTER.md for the detail, and the
docstring of each module for its step.

Usage:
    python watchmen_extract.py game.naz -o OUT
        [--no-files] [--no-textures] [--no-models] [--no-audio]
        [--exact-audio]   sample-perfect Ogg granulepos (parses Vorbis modes)
        [--flat-music]    music streams as ONE file each (the output of releases before 1.4.0)
        [--music-track-labels]  MusicStreamSlot track names in the file names
        [--smpl-loops]    RIFF smpl loop chunk on sounds with the loop flag
        [--no-text]       no text/ (every text asset, every language)
        [--no-nav]        no nav/ (per level navigation mesh + graph)
        [--limit N]       stop after N block assets (debug)
        [--quiet]

Requires numpy and Pillow. Python 3.13+.
"""

import argparse
import functools
import importlib
import os
import struct
import sys
import types
from pathlib import Path


# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)

import extract_log  # noqa: E402
import extract_paths  # noqa: E402
import naz_archive  # noqa: E402
import kapow_block  # noqa: E402

# under another name: `watchmen_extract.texture_sheet` is the forwarded function, and
# Python 3.15 reads a module's own namespace before a property of its type
import texture_sheet as texture_sheet_mod  # noqa: E402
import texture_carve  # noqa: E402
import model_header  # noqa: E402
import model_mesh  # noqa: E402
import obj_mtl  # noqa: E402
import model_export  # noqa: E402
import sound_header  # noqa: E402
import audio_decode  # noqa: E402


# ===========================================================================
# Driver
# ===========================================================================


#: asset classes / name suffixes that some step of the toolkit decodes (extract itself,
#: binds / characters for animations, the nav and text exports).  Anything else that
#: `extract` meets is kept raw under extracted/ and counted in its summary ("raw only").
_DECODED_CLASSES = frozenset(("Texture", "Model", "ModelRes", "sound", "mediastream"))
_DECODED_SUFFIXES = (".animation", ".aipathdata", ".txt", ".wav", ".bmp", ".tga", ".model")


#: why kapow_json did not import (the asset loop names it on each asset it leaves raw)
_KAPOW_JSON_ERROR = []


@functools.cache
def _kapow_json():
    """Lazy import of kapow_json (fragment/pb/sequence/particle/... -> JSON); None
    (kept) when it does not import, the reason in _KAPOW_JSON_ERROR."""
    try:
        import kapow_json as _kj
    except ImportError as e:
        _KAPOW_JSON_ERROR[:] = ["%s: %s" % (type(e).__name__, e)]
        return None
    return _kj


#: stream-only block files (Part 1 Prison) kept in memory at once by `extract`
_STREAM_CACHE = 4
#: extract: a block whose inflated assets (headers + streams) take at most this many
#: bytes keeps them from the check pass for the asset pass; a larger one is parsed
#: and inflated again, so the memory stays bounded (0 = never keep)
BLOCK_CACHE_BYTES = 64 << 20


class ModelSpool:
    """The model jobs of an `extract` run: (header, stream, out_path, order,
    platform) tuples in the order they were added, the header and stream bytes
    kept in an anonymous temporary file in `folder` (removed when closed, or by
    the system if the process dies) instead of in memory.  Iterating reads one
    job back at a time."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self._f = None
        self._jobs = []

    def append(self, job):
        header, stream, out_path, order, platform = job
        if self._f is None:
            import tempfile

            self.folder.mkdir(parents=True, exist_ok=True)
            self._f = tempfile.TemporaryFile(
                prefix=".watchmen_models_", suffix=".spool", dir=str(self.folder)
            )
        f = self._f
        f.seek(0, os.SEEK_END)
        off = f.tell()
        hl = -1 if header is None else len(header)
        sl = -1 if stream is None else len(stream)
        if hl > 0:
            f.write(header)
        if sl > 0:
            f.write(stream)
        self._jobs.append((off, hl, sl, out_path, order, platform))

    def __len__(self):
        return len(self._jobs)

    def __iter__(self):
        for off, hl, sl, out_path, order, platform in self._jobs:
            self._f.seek(off)
            header = None if hl < 0 else self._f.read(hl)
            stream = None if sl < 0 else self._f.read(sl)
            yield header, stream, out_path, order, platform

    def close(self):
        if self._f is not None:
            self._f.close()
            self._f = None


def main(argv):
    """`extract`: see --help.  The run's name record (canonical_names.Run) is
    closed however the extraction ends."""
    try:
        return _extract_main(argv)
    finally:
        extract_paths.names_module().end()


def _extract_main(argv):
    ap = argparse.ArgumentParser(description="Extract Watchmen Part 2 (Kapow) assets from game.naz")
    ap.add_argument("naz", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("watchmen_out"))
    ap.add_argument(
        "--no-files", action="store_true", help="don't write the raw decrypted asset tree"
    )
    ap.add_argument("--no-textures", action="store_true")
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument(
        "--no-extract-all",
        action="store_true",
        help="don't dump every raw asset (fragment/sequence/particle/etc.) to extracted/",
    )
    ap.add_argument(
        "--glb",
        action="store_true",
        help="also emit rigged+textured .glb (bind pose) for skinned character models; the skin rig's joint names/order come from each model's own embedded skeleton header, so no capture artifacts are needed (just numpy+Pillow). For engine-exact ANIMATED per-character glbs use `watchmen.py characters` (file-only binds + baked clips).",
    )
    ap.add_argument(
        "--no-vertex-attrs",
        action="store_true",
        help="with --glb: write the 1.3.0 .glb files (skinned models only; no NORMAL / TANGENT / COLOR_0, diffuse-only double-sided materials, file winding). Default: per-vertex attributes from the mesh buffers, sheet-driven materials (alpha blend / cut-out, two-sided, normal map) and a static .glb for rigid models too.",
    )
    ap.add_argument(
        "--rig",
        choices=("hierarchy", "flat"),
        default=None,
        help="with --glb: the skeleton of a rigged model's .glb. hierarchy (default) = one joint node per header node, named after it and parented as the header says, rest transform local to the parent and real inverse bind matrices (the bones stand where the model's skeleton puts them; the mesh node is a scene root); flat = the 1.4.0 file: joints without a transform, all children of 'Armature', identity inverse bind matrices. The mesh renders the same in both. Also $WATCHMEN_RIG.",
    )
    ap.add_argument(
        "--glb-texture-size",
        type=model_export._texture_size_arg,
        default=None,
        metavar="N",
        help="with --glb: shrink every texture embedded in a model .glb to at most N x N pixels (aspect kept). Default: the full size of the extracted PNG; 512 gives the 1.4.0 files.",
    )
    ap.add_argument(
        "--frame",
        choices=("true", "mirrored"),
        default=None,
        help="coordinate frame of the models (.obj / .glb) and the nav .glb: true (default) = right-handed, x = -engine x, the game as it looks; mirrored = the engine's left-handed numbers verbatim, a mirror image, byte-identical to what 1.3.0 wrote. Also $WATCHMEN_FRAME.",
    )
    ap.add_argument(
        "--exact-audio",
        action="store_true",
        help="(default now; kept for compatibility) sample-perfect Ogg granulepos",
    )
    ap.add_argument(
        "--vgmstream-cli",
        type=Path,
        default=None,
        metavar="PATH",
        help="path to a vgmstream-cli executable (any platform); used to decode console (X360 XMA2 / PS3 MP3) music streams to .wav. Without it, console music is written as .xma/.mp3 containers instead.",
    )
    ap.add_argument(
        "--keep-xma",
        action="store_true",
        help="X360 XMA is ALWAYS kept (default), and .wav is only written when --vgmstream-cli is given. This flag additionally keeps PS3 .mp3 containers alongside their .wav. Valid XMA2/MP3 a working decoder can re-convert (some short X360 XMA2 fail in current vgmstream/ffmpeg but the data is good -- see MASTER §14).",
    )
    ap.add_argument(
        "--flat-music",
        action="store_true",
        help="write each music stream as ONE file, the 1.3.0 output: a multi-track stream then holds all its tracks' chunks appended in turn (N times the real length) and no sidecar is written. Default: one file per track (<name>_track<k>...), plus <name>.json with the tracks, their cue points and the MusicSetup track states.",
    )
    ap.add_argument(
        "--music-track-labels",
        action="store_true",
        help="append the MusicStreamSlot track name to each per-track music file name (..._track1_Intro_loop...). Off by default: every shipped setup but one carries the same ten editor names, so they do not describe the stems; the names are in the sidecar either way.",
    )
    ap.add_argument(
        "--smpl-loops",
        action="store_true",
        help="add a RIFF 'smpl' chunk (one forward loop over the whole file) to the .wav of sounds whose header has the loop flag. Default: the flag is only listed in audio/sound_info.json.",
    )
    ap.add_argument(
        "--no-text",
        action="store_true",
        help="don't write text/ (every text asset in every language: raw, .json, .csv; see docs/TEXT_ASSETS.md). --language does not apply to it.",
    )
    ap.add_argument(
        "--no-nav",
        action="store_true",
        help="don't write nav/ (per level <Level>.nav.json + .nav.glb from the .hpd under files/ and the .aipathdata under extracted/; see docs/NAV_DATA.md)",
    )
    ap.add_argument(
        "--limit", type=int, default=None, metavar="N", help="stop after N block assets (debug)"
    )
    ap.add_argument(
        "--model-lod",
        type=model_header.model_lod_arg,
        default=0,
        metavar="N|all",
        help="which level of detail of each model to write: 0 (default) = full detail, N = that LOD (clamped per part), 'all' = every LOD in one file",
    )
    ap.add_argument(
        "--language",
        type=kapow_block.language_arg,
        default=0,
        metavar="0..5|NAME",
        help="language slot used for localized block assets (per-language header blobs and streams); default 0. A number 0..5 or a name / code: english|uk|en, french|fr, italian|it, german|de, spanish|es, danish|dk|da (the Danish slot of the shipped games is a copy of English)",
    )
    ap.add_argument(
        "--names",
        choices=("canonical", "stored"),
        default=None,
        help="spelling of output paths whose letter case differs between the archives: canonical (default) = the one spelling wlib/canonical_names.json lists for them, on every platform and both parts, one spelling per folder, and lower-case names for the files brought from beside a loose folder; the stored spelling goes into _canonical_names.json, the texture's sheet.json and the model's .model.json (stored_name). stored = every path as its archive stores it. Also $WATCHMEN_NAMES.",
    )
    ap.add_argument(
        "--json-floats",
        choices=("exact", "rounded"),
        default=None,
        help="how the decoded JSON writes float32 values: exact (default) = the shortest decimal that reads back as the same float32 (NaN / infinity as null); rounded = the 1.4.0 output (6 places, 5 for sequence keys). Also $WATCHMEN_JSON_FLOATS.",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="no progress log; the warning lines ('!' and 'WARNING:') still go to stderr",
    )
    a = ap.parse_args(argv)
    if not a.naz.exists():
        print("error: %s not found" % a.naz, file=sys.stderr)
        return 2
    model_export._RIG["on"] = bool(getattr(a, "glb", False))
    model_export._RIG["attrs"] = not bool(getattr(a, "no_vertex_attrs", False))
    model_export._RIG["tex_size"] = getattr(a, "glb_texture_size", None)
    if getattr(a, "rig", None):
        os.environ["WATCHMEN_RIG"] = a.rig  # the --glb rig and variant_glb.rig_mode() read it
    if getattr(a, "frame", None):
        os.environ["WATCHMEN_FRAME"] = a.frame  # frame.mode() reads it
    if getattr(a, "names", None):
        os.environ["WATCHMEN_NAMES"] = a.names  # canonical_names.mode() reads it
    if getattr(a, "json_floats", None):
        os.environ["WATCHMEN_JSON_FLOATS"] = a.json_floats  # f32json.mode() reads it
    if model_export._RIG["on"] and a.no_models:
        print("note: --glb requires model decoding; overriding --no-models", file=sys.stderr)
        a.no_models = False
    if model_export._RIG["on"] and not model_export._rig_load():
        print(
            "WARNING: --glb requested but rig_glb.py (or numpy) not importable (%s); "
            "skipping rig export" % model_export._RIG.get("error"),
            file=sys.stderr,
        )
        model_export._RIG["on"] = False
    log = extract_log.extract_logger(a.quiet)
    do_tex = not a.no_textures
    do_mdl = not a.no_models
    do_extract_all = not a.no_extract_all

    entries = list(naz_archive.naz_entries(a.naz, warn=lambda m: log("  ! " + m)))
    log("NAZ %s : %d entries -> %s" % (a.naz, len(entries), a.out))
    # the console of a big-endian source, named by its derived root (the path of
    # a loose tree, or the block paths inside the .naz); None on PC
    run_platform = model_mesh.console_platform_of(a.naz)
    for e in entries:
        if run_platform:
            break
        run_platform = model_mesh.console_platform_of(e.name)
    # the block plan: stem -> {"h": NazEntry, "s": NazEntry[, "standalone": True]}
    # -- archive entries only; each half is read again (and inflated) when its
    # block is processed and dropped after it, so the run never holds the archive
    blocks = {}
    console_audio = []  # (name, NazEntry) console mediastream_s, decoded post-blocks
    pc_audio = []  # (name, NazEntry) PC mediastream_s, split per track post-blocks
    media_meta = {}  # mediastream path (lower, no leading /) -> (ch, rate, samples)
    media_desc = {}  # same key -> (descriptor asset name, media_desc_from_header)
    music_frags = []  # (name, header, order) of fragments holding a MusicStreamSlot
    sound_info = {}  # sound asset name -> header facts (audio/sound_info.json)
    sfx_failed = []  # console sound assets no audio could be written for
    stats = dict(files=0, tex=0, mdl=0, aud=0)
    # --names: the canonical spelling of every output path, and what was respelled
    name_run = extract_paths.names_module().begin()
    # extracted/, textures/, models/ and audio/ spell every folder alike
    extract_paths.names_module().share_folders(a.out)
    names = extract_paths.OutputNames(
        log, name_run
    )  # one output per asset name (repeats, twins, variants)
    model_stored = {}  # model output path -> the archive's spelling of a respelled name
    text_writer = None
    if not a.no_text:
        try:
            import text_assets as _ta

            text_writer = _ta.TextWriter(a.out, log)
        except Exception as ex:
            log("note: text_assets not importable (%s) -> no text/" % ex)
    no_stream = {}  # Texture / ModelRes name -> (class, why) left without stream data
    misc = {}  # JSON kind (".font", ...) -> [assets, not fully decoded]
    raw_only = {}  # class / suffix of assets no decoder of this command reads -> count
    from_sets = {}  # stream-set file -> assets whose stream came from it

    # pass 1, archive order: files/, the standalone audio streams, and the plan.
    # An entry is read here only when its bytes are used here: for files/, or a
    # standalone audio stream.  With --no-files the block halves and the standalone
    # texture / model halves are planned from the directory alone (the block pass
    # reads them), so the archive is read once, not twice.
    for e in entries:
        low = e.name.lower()
        _audio = not a.no_audio and low.endswith(".mediastream_s")
        if a.no_files and not _audio:
            data = None  # planned from the directory; read when its block is processed
        else:
            try:
                data = naz_archive.naz_read(a.naz, e)
            except Exception as ex:
                log("  ! %s: %s" % (e.name, ex))
                continue
        if data is not None and not a.no_files:
            p = extract_paths.safe(a.out / "files", name_run.name(e.name))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            stats["files"] += 1
        # pair block halves; defer processing until both are known
        if low.endswith(".block_h_z") or low.endswith(".block_s_z"):
            stem = e.name[: -len("_h_z")] if low.endswith("_h_z") else e.name[: -len("_s_z")]
            blocks.setdefault(stem, {})["h" if low.endswith("_h_z") else "s"] = e
            continue
        # standalone audio (PC = Vorbis packet container; console handled after
        # the block pass so channel/rate metadata is available)
        if not a.no_audio and low.endswith(".mediastream_s"):
            try:
                if not a.flat_music and audio_decode.audio_packets(data):
                    pc_audio.append((e.name, e))  # needs the descriptors
                elif audio_decode.decode_audio(
                    data, extract_paths.safe(a.out / "audio", e.name + ".ogg"), True, log
                ):
                    stats["aud"] += 1
                else:
                    console_audio.append((e.name, e))
            except Exception as ex:
                log("      ! audio %s: %s" % (e.name, ex))
            continue
        # standalone texture / model (paired _h_z + _s_z handled via the block dict
        # path above only for *.block_*; helper textures use *.texture_h_z etc.)
        if low.endswith(".texture_h_z") or low.endswith(".modelres_h_z"):
            blocks.setdefault(e.name[: -len("_h_z")], {})["h"] = e
            blocks[e.name[: -len("_h_z")]]["standalone"] = True
            continue
        if low.endswith(".texture_s_z") or low.endswith(".modelres_s_z"):
            blocks.setdefault(e.name[: -len("_s_z")], {})["s"] = e
            blocks[e.name[: -len("_s_z")]]["standalone"] = True
            continue
    data = None  # pass 1 keeps no entry's bytes

    def _half(hs, k):
        """Bytes of half `k` ("h" / "s") of a planned block, read now: the
        archive entry, inflated for a standalone file; None without that half."""
        ent = hs.get(k)
        if ent is None:
            return None
        raw = naz_archive.naz_read(a.naz, ent)
        return kapow_block.inflate_standalone(raw) if hs.get("standalone") else raw

    def _entry_bytes(ent):
        """An audio entry of pass 1, read again for its post-block pass."""
        return naz_archive.naz_read(a.naz, ent)

    # process collected blocks + standalone pairs
    # stream-only `.block_s_z` files (no header half): the stream sets of another
    # block's header name them (Part 1 Prison: four rooms).  Read when a set
    # first names them; the last few stay cached.
    _stream_only = {k + "_s_z": v for k, v in blocks.items() if "h" not in v and "s" in v}
    _stream_used = {}
    _stream_cache = {}  # stream-only file -> bytes, at most _STREAM_CACHE of them

    def _stream_file(path, _find=kapow_block.stream_file_lookup({k: k for k in _stream_only})):  # noqa: B008
        key = _find(path)
        if key is None:
            return None
        blob = _stream_cache.pop(key, None)
        if blob is None:
            try:
                blob = _half(_stream_only[key], "s")
            except Exception as ex:
                log("  ! %s: %s" % (key, ex))
                return None
        _stream_cache[key] = blob  # most recently used last
        while len(_stream_cache) > _STREAM_CACHE:
            _stream_cache.pop(next(iter(_stream_cache)))
        _stream_used[path] = _stream_used.get(path, 0) + 1
        return blob

    # (header, stream, out_path, order, platform) -- deferred until all textures
    # are dumped; header and stream wait in a spool file under the output folder
    model_jobs = ModelSpool(a.out)
    extract_log.push(log)
    try:
        return _extract_blocks_and_rest(
            a,
            log,
            blocks,
            _half,
            _entry_bytes,
            _stream_only,
            _stream_used,
            _stream_file,
            model_jobs,
            run_platform,
            console_audio,
            pc_audio,
            media_meta,
            media_desc,
            music_frags,
            sound_info,
            sfx_failed,
            stats,
            name_run,
            names,
            model_stored,
            text_writer,
            no_stream,
            misc,
            raw_only,
            from_sets,
            do_tex,
            do_mdl,
            do_extract_all,
        )
    finally:
        extract_log.pop()
        model_jobs.close()


def _extract_blocks_and_rest(
    a,
    log,
    blocks,
    _half,
    _entry_bytes,
    _stream_only,
    _stream_used,
    _stream_file,
    model_jobs,
    run_platform,
    console_audio,
    pc_audio,
    media_meta,
    media_desc,
    music_frags,
    sound_info,
    sfx_failed,
    stats,
    name_run,
    names,
    model_stored,
    text_writer,
    no_stream,
    misc,
    raw_only,
    from_sets,
    do_tex,
    do_mdl,
    do_extract_all,
):
    """The block pass and everything after it (`extract`, see _extract_main).  Returns
    1 when a block could not be read or parsed (its assets are missing), else 0."""
    n_assets = 0
    failed_blocks = []  # blocks whose halves did not read or whose parse failed
    tex_repeats = mdl_repeats = 0
    # blocks in a fixed order that does not depend on the letter case an archive
    # stores their paths in (OutputNames: the first copy names the output)
    for stem, hs in sorted(blocks.items(), key=lambda kv: (kv[0].lower(), kv[0])):
        if "h" not in hs:
            continue
        if hs.get("standalone"):
            low = stem.lower()
            if hs.get("s") is None:
                continue
            try:
                header, stream = _half(hs, "h"), _half(hs, "s")
            except Exception as ex:
                log("  ! %s: %s" % (stem, ex))
                failed_blocks.append(stem)
                continue
            # same registry as the block assets; the folder names a differing copy
            name, placed = extract_paths.standalone_output_name(names, stem, header, stream)
            if placed == "repeat":
                continue
            if do_tex and ".texture" in low:
                try:
                    if texture_carve.carve_texture(
                        stream, header, extract_paths.safe(a.out / "textures", name), log
                    ):
                        stats["tex"] += 1
                        texture_sheet_mod.mark_stored_name(
                            extract_paths.safe(a.out / "textures", name), name_run.stored_of(name)
                        )
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and ".modelres" in low:
                model_jobs.append(
                    (
                        header,
                        stream,
                        extract_paths.safe(a.out / "models", name + ".obj"),
                        None,
                        model_mesh.console_platform_of(stem) or run_platform,
                    )
                )
            continue
        # real block pair
        if a.limit is not None and n_assets >= a.limit:
            break  # --limit N: stop after N block assets
        log("\nBLOCK %s" % stem)
        try:
            h_data, s_data = _half(hs, "h"), _half(hs, "s")
        except Exception as ex:
            log("  ! %s: %s" % (stem, ex))
            failed_blocks.append(stem)
            continue
        if text_writer is not None:  # text assets, all six language slots
            try:
                text_writer.add_block(h_data, stem)
            except Exception as ex:
                log("  ! text assets: %s" % ex)
        _args = (h_data, s_data, a.language) if a.language else (h_data, s_data)
        try:
            # check pass: the whole block parses and inflates (what does not inflate is
            # reported here, before any asset of the block is written).  The
            # assets are kept for the asset pass while they fit in BLOCK_CACHE_BYTES;
            # a larger block is parsed again below -- holding a whole level's assets
            # is what the memory would go on
            _rep = lambda m: log("  ! " + m)
            _kept, _size, _cap = [], 0, BLOCK_CACHE_BYTES
            for _item in kapow_block.extract_block(*_args, report=_rep, stream_files=_stream_file):
                if _kept is not None:
                    _size += len(_item[1] or b"") + len(_item[2] or b"")
                    if _size <= _cap:
                        _kept.append(_item)
                    else:
                        _kept = None  # too big: the asset pass parses it again
            _item = None
        except Exception as ex:
            log("  ! parse failed: %s" % ex)
            failed_blocks.append(stem)
            continue
        # the assets one at a time (the same parse; its reports were logged above)
        if _kept is not None:
            it = iter(_kept)
        else:
            it = kapow_block.extract_block(*_args, report=None, stream_files=_stream_file)
        _kept = None
        h_data = s_data = _args = None  # the generator holds the block's bytes until done
        for e, header, stream in it:
            if a.limit is not None and n_assets >= a.limit:
                break
            n_assets += 1
            # script classes ("ModelEffects(ModelRes)", "TextureEffects(Texture)")
            # are read by their base class loader -> dispatch on the base name
            cls = kapow_block.asset_base_class(
                kapow_block.asset_class(header, kapow_block.BLOCK_ORDER)
            )
            # the name this copy is written under, and whether an earlier block
            # already wrote the same bytes (OutputNames: "repeat")
            name, placed = names.place(e.name, stem, header, stream)
            low = name.lower()
            # class-name compare is case-insensitive: the typename is spelled both
            # "mediastream" and "MediaStream"; a case-sensitive miss here would leave
            # media_meta empty (console XMA then wrapped with default 2ch/48000
            # instead of the real channel/rate/sample values).
            if not a.no_audio and cls.lower() == "mediastream":
                try:
                    mm = sound_header.media_meta_from_header(header, kapow_block.BLOCK_ORDER)
                    if mm:
                        media_meta[mm[0].lower().lstrip("/")] = mm[1:]
                    md = sound_header.media_desc_from_header(header, kapow_block.BLOCK_ORDER)
                    if md:
                        media_desc[md["stream"].lower().lstrip("/")] = (name, md)
                except (struct.error, ValueError, IndexError, KeyError) as ex:
                    log(
                        "      WARNING: music %s: stream description not read, channels and "
                        "rate left to the stream (%s: %s)" % (name, type(ex).__name__, ex)
                    )
            if not a.no_audio and low.endswith(".fragment") and b"MusicStreamSlot" in header:
                music_frags.append((name, header, kapow_block.BLOCK_ORDER))
            # dump EVERY asset raw (header + optional stream) to extracted/ for offline
            # analysis; a later copy with the same header and stream wrote the same files
            # under the same name already (raw, JSON, the files beside it), so it is skipped
            if do_extract_all and not (placed == "repeat" and names.same_bytes):
                _ep = extract_paths.safe(a.out / "extracted", name)
                _ep.parent.mkdir(parents=True, exist_ok=True)
                _ep.write_bytes(header if header else b"")
                if stream:
                    (_ep.parent / (_ep.name + ".stream")).write_bytes(stream)
                # human-readable JSON for property-bag / sequence / fragment assets
                # (.fragment.json, .pb.json, .sequence.json, .particle.json, ...)
                if header and low.endswith(
                    (
                        ".fragment",
                        ".sequence",
                        ".pb",
                        ".particle",
                        ".grass",
                        ".detailmesh",
                        ".terrain",
                        ".scene",
                        ".font",
                        ".terraincoloringasset",
                    )
                ):
                    _kind = "." + low.rsplit(".", 1)[-1]
                    # counted once per output name (a later copy without the stream the
                    # first one had is written again but is the same asset)
                    _one = 1 if placed != "repeat" else 0
                    _cnt = misc.setdefault(_kind, [0, 0])
                    _cnt[0] += _one
                    try:
                        kj = _kapow_json()
                        d = None
                        if kj:
                            _lines = []
                            if low.endswith(kj.EXPORT_EXTS):
                                # font / scene / terrain / terrain colouring / detail mesh:
                                # JSON plus the atlas, maps and terrain GLB beside the asset;
                                # what is not decoded comes back as log lines
                                d, _lines = kj.export(
                                    name,
                                    header,
                                    stream,
                                    str(_ep),
                                    kapow_block.BLOCK_ORDER,
                                    glb=bool(a.glb),
                                )
                            else:
                                d = kj.to_json(low, header, order=kapow_block.BLOCK_ORDER)
                            if d and low.endswith(".fragment"):
                                # never silent: a fragment not decoded exactly, or
                                # with values typed by guess, is named in the log
                                import kapow_fragment as _kfr

                                _lines = _kfr.notes(name, d)
                            _why = kj.undecoded(d)
                            if _why:
                                # one line per asset that is not decoded completely; the
                                # same fact is a marker in its JSON (kapow_json.undecoded)
                                _cnt[1] += _one
                                if not any(_l.startswith("WARNING:") for _l in _lines):
                                    _lines = list(_lines) + [
                                        "WARNING: %s %s: not decoded completely: %s"
                                        % (_kind[1:], name, _why)
                                    ]
                            for _ln in _lines:
                                log("      " + _ln)
                            if d:
                                import f32json as _f32j

                                with open(
                                    _ep.parent / (_ep.name + ".json"),
                                    "w",
                                    encoding="utf-8",
                                    newline="\n",
                                ) as _f:
                                    # exact mode: a NaN or an infinity is null
                                    _f.write(_f32j.dumps(d, indent=1))
                        else:
                            _cnt[1] += _one
                            log(
                                "      WARNING: %s %s: not decoded: kapow_json not importable (%s)"
                                % (_kind[1:], name, "; ".join(_KAPOW_JSON_ERROR))
                            )
                    except Exception as ex:
                        _cnt[1] += _one
                        log("      WARNING: %s %s: not decoded: %s" % (_kind[1:], name, ex))
                elif header and not (
                    cls in _DECODED_CLASSES
                    or cls.lower() in _DECODED_CLASSES
                    or low.endswith(_DECODED_SUFFIXES)
                ):
                    # a kind no step of the toolkit reads: kept raw, and counted
                    _k = cls if cls and cls != "unknown" else "." + low.rsplit(".", 1)[-1]
                    raw_only[_k] = raw_only.get(_k, 0) + (placed != "repeat")
            # SFX / voice 'sound' assets keep their PCM INLINE in the header
            # (stream is None) -> handle these before the stream-None skip below.
            if not a.no_audio and cls == "sound":
                try:
                    if kapow_block.BLOCK_ORDER == "<":
                        r = audio_decode.decode_sfx(header)
                        if r:
                            wn = name if name.lower().endswith(".wav") else name + ".wav"
                            si = sound_header.sfx_info(header) or {}
                            loop = bool(si.get("looping"))
                            audio_decode.write_wav(
                                r[0],
                                r[1],
                                r[2],
                                extract_paths.safe(a.out / "audio", wn),
                                a.smpl_loops and loop,
                            )
                            stats["aud"] += 1
                            if si:
                                si.pop("_pe", None)
                                si["file"] = extract_paths.out_rel(a.out / "audio", wn)
                                sound_info[name.replace("\\", "/").lstrip("/")] = si
                        else:
                            sfx_failed.append(name)
                            log(
                                "      WARNING: sfx %s: sound header not decoded; no audio written"
                                % name
                            )
                    else:
                        si = audio_decode.decode_sfx_console(
                            header,
                            kapow_block.BLOCK_ORDER,
                            name,
                            a.out / "audio",
                            a.vgmstream_cli,
                            log,
                            a.keep_xma,
                        )
                        if si:
                            stats["aud"] += 1
                            if isinstance(si, dict):
                                sound_info[name.replace("\\", "/").lstrip("/")] = si
                        else:
                            sfx_failed.append(name)
                            log(
                                "      WARNING: sfx %s: sound header not decoded; no audio written"
                                % name
                            )
                except Exception as ex:
                    log("      ! sfx %s: %s" % (name, ex))
                continue
            if cls in ("Texture", "Model", "ModelRes"):
                # a texture / model without stream data gets no PNG / OBJ: say so,
                # once per output name, unless a later block's copy brings the
                # stream (OutputNames: "fill")
                if stream:
                    no_stream.pop(name, None)
                elif stream is not None and do_mdl and cls != "Texture":
                    pass  # an empty stream record: decode_model names it with the reason
                elif placed != "repeat":
                    if stream is None:
                        why = "header only" + ("" if e.stream_note else ", not in any stream set")
                    else:
                        why = "its stream record is empty (0 bytes)"
                    no_stream[name] = (cls, why)
            if stream is None:
                continue
            if e.stream_file:
                from_sets[e.stream_file] = from_sets.get(e.stream_file, 0) + 1
            if do_tex and cls == "Texture":
                if placed == "repeat":  # same bytes as an earlier block's copy
                    tex_repeats += 1
                    continue
                try:
                    if texture_carve.carve_texture(
                        stream, header, extract_paths.safe(a.out / "textures", name), log
                    ):
                        stats["tex"] += 1
                        texture_sheet_mod.mark_stored_name(
                            extract_paths.safe(a.out / "textures", name), name_run.stored_of(name)
                        )
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and (cls in ("Model", "ModelRes") or ".modelres" in low):
                if placed == "repeat":
                    mdl_repeats += 1
                    continue
                if name_run.stored_of(name):
                    model_stored[extract_paths.safe(a.out / "models", name + ".obj")] = (
                        name_run.stored_of(name)
                    )
                model_jobs.append(
                    (
                        header,
                        stream,
                        extract_paths.safe(a.out / "models", name + ".obj"),
                        kapow_block.BLOCK_ORDER,
                        model_mesh.console_platform_of(stem) or run_platform,
                    )
                )
            elif not a.no_audio and (cls.lower() == "mediastream" or ".mediastream" in low):
                try:
                    if audio_decode.decode_audio(
                        stream, extract_paths.safe(a.out / "audio", name + ".ogg"), True, log
                    ):
                        stats["aud"] += 1
                except Exception as ex:
                    log("      ! audio %s: %s" % (name, ex))

    if from_sets or _stream_only:
        log("\nSTREAM SETS: %d stream-only block file(s)" % len(_stream_only))
        for sfile, cnt in sorted(from_sets.items()):
            log("  %s: %d asset stream(s) read" % (sfile, cnt))
        _find = kapow_block.stream_file_lookup({k: k for k in _stream_only})
        _hit = {_find(sfile) for sfile in _stream_used}
        for k in sorted(_stream_only):
            if k not in _hit:
                log("  WARNING: %s: no stream set of any block names this file; not read" % k)
    if no_stream:
        log("\nNO STREAM: %d texture / model asset(s) without stream data" % len(no_stream))
        for _nm, (_cls, _why) in sorted(no_stream.items()):
            log("  note: no stream: %s (%s): %s" % (_nm, _cls, _why))

    # music: block pass done -> descriptors (tracks, cue points) and the
    # MusicSetup fragments (track names, track states) are known
    setups = []
    for fname, fhead, forder in music_frags:
        try:
            import sound_meta as _sm

            setups += _sm.music_setups_from_bytes(fhead, fname, forder)
        except Exception as ex:
            log("      ! music setup %s: %s" % (fname, ex))

    def _desc_of(name):
        """(descriptor asset name, descriptor) of a stream entry: by its path,
        else by the one descriptor whose stream path ends with it (a loose tree
        rooted below `derived_<platform>/`)."""
        key = name.lower().lstrip("/")
        if key in media_desc:
            return media_desc[key]
        hits = [v for k, v in media_desc.items() if k.endswith("/" + key)]
        return hits[0] if len(hits) == 1 else (None, None)

    def _music_sidecar(name, tracks, layout):
        dname, desc = _desc_of(name)
        mine = [
            s
            for s in setups
            if dname
            and (s.get("stream_asset") or "").replace("\\", "/").lstrip("/").lower()
            == dname.replace("\\", "/").lstrip("/").lower()
        ]
        slot = mine[0]["track_names"] if mine else []
        for k, t in enumerate(tracks):
            dt = desc["tracks"][k] if desc and k < len(desc["tracks"]) else {}
            t["slot_track_name"] = slot[k] if k < len(slot) else None
            t["source"] = dt.get("source")
            if dt.get("samples"):
                t["descriptor_samples"] = dt["samples"]
            rate = t.get("rate") or dt.get("rate")
            t["cue_points"] = [
                dict(c, time_s=round(c["sample"] / float(rate), 4) if rate else None)
                for c in dt.get("cue_points", [])
            ]
        doc = {
            "format": "watchmen-music-stream/1",
            "stream": name.replace("\\", "/").lstrip("/"),
            "descriptor": dname,
            "layout": layout,
            "tracks": tracks,
            "setups": mine,
        }
        import json as _json

        jp = extract_paths.safe(a.out / "audio", name + ".json")
        jp.parent.mkdir(parents=True, exist_ok=True)
        with open(jp, "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_json.dumps(doc, indent=1))

    def _slot_labels(name):
        if not a.music_track_labels:
            return None
        dname = _desc_of(name)[0]
        for s in setups:
            if (
                dname
                and (s.get("stream_asset") or "").lstrip("/").lower() == dname.lstrip("/").lower()
            ):
                return s["track_names"]
        return None

    for name, ent in pc_audio:
        try:
            raw = _entry_bytes(ent)
            tr = audio_decode.decode_audio_tracks(
                raw, a.out / "audio", name, True, log, _slot_labels(name)
            )
            if tr:
                stats["aud"] += len(tr)
                _music_sidecar(name, tr, "one file per track")
            elif audio_decode.decode_audio(
                raw, extract_paths.safe(a.out / "audio", name + ".ogg"), True, log
            ):
                stats["aud"] += 1
                log("      ! %s does not split into tracks: written as one file" % name)
            else:
                console_audio.append((name, ent))
        except Exception as ex:
            log("      ! audio %s: %s" % (name, ex))
        raw = None

    if sound_info or sfx_failed:
        import json as _json

        doc = {"format": "watchmen-sound-info/1", "sounds": dict(sorted(sound_info.items()))}
        if sfx_failed:  # marker: sound assets whose header no reader took
            doc["not_decoded"] = sorted(n.replace("\\", "/").lstrip("/") for n in sfx_failed)
        (a.out / "audio").mkdir(parents=True, exist_ok=True)
        with open(
            extract_paths.safe(a.out / "audio", "sound_info.json"),
            "w",
            encoding="utf-8",
            newline="\n",
        ) as _f:
            _f.write(_json.dumps(doc, indent=1))
        src = {}
        for si in sound_info.values():
            if "duration_source" in si:  # console records only
                src[si["duration_source"]] = src.get(si["duration_source"], 0) + 1
        if src or sfx_failed:
            kept = sum(1 for si in sound_info.values() if not si["file"].lower().endswith(".wav"))
            log(
                "\nSOUND INFO: %d sounds -> audio/sound_info.json (duration from: %s; "
                "%d not decoded)"
                % (
                    len(sound_info),
                    ", ".join("%s %d" % kv for kv in sorted(src.items())) or "the PC header",
                    len(sfx_failed),
                )
            )
            if src:
                log(
                    "CONSOLE SFX: %d of %d sounds written as .mp3 / .xma containers (vgmstream: %s)"
                    % (kept, len(sound_info), a.vgmstream_cli or "not set")
                )

    # console music: per-stream channel/rate metadata known
    if console_audio:
        log(
            "\nCONSOLE AUDIO: %d streams (vgmstream: %s)"
            % (len(console_audio), a.vgmstream_cli or "not set")
        )
        for name, ent in console_audio:
            try:
                raw = _entry_bytes(ent)
                meta = media_meta.get(name.lower().lstrip("/"))
                r = audio_decode.decode_console_audio(
                    name,
                    raw,
                    a.out / "audio",
                    meta,
                    a.vgmstream_cli,
                    log,
                    a.keep_xma,
                    tracks=not a.flat_music,
                    labels=_slot_labels(name),
                    desc=_desc_of(name)[1],
                )
                if isinstance(r, list):
                    stats["aud"] += len(r)
                    _music_sidecar(name, r, "one file per track")
                elif r:
                    stats["aud"] += 1
                else:
                    log("      ! unrecognized mediastream %s" % name)
            except Exception as ex:
                log("      ! console audio %s: %s" % (name, ex))
            raw = None

    # all blocks parsed -> textures are now on disk; decode models last with the
    # full texture index so per-submesh materials resolve correctly.
    tex_index = obj_mtl.build_texture_index(a.out / "textures")
    # SKELETON REFERENCE DUMP: decode the base *_Skeleton.model rest poses to
    # OUT/skeletons/*.json (file-decoded; see docs/ENGINE_CONSTANTS.md).  This is
    # reference output only -- the glb rig takes its joint names/order from each
    # model's OWN embedded palette in decode_model (skeleton assets have a 0-byte
    # stream, so they never enter model_jobs; collect them straight from the naz).
    if model_export._RIG["on"]:
        try:
            import extract_skeletons as _es
            import json as _json

            _sk = _es.collect(str(a.naz))
            skdir = a.out / "skeletons"
            skdir.mkdir(parents=True, exist_ok=True)
            for _fam, _s in _sk.items():
                with open(
                    skdir / ("skeleton_%s.json" % _fam), "w", encoding="utf-8", newline="\n"
                ) as _f:
                    _json.dump(_s, _f, indent=1)
            log("\nSKELETONS: %d base skeletons decoded from file -> %s" % (len(_sk), skdir))
            for _fam, _s in sorted(_sk.items()):
                log("  skeleton_%-12s %3d bones" % (_fam, _s["bone_count"]))
            import skeleton_records as _skr

            _note = _skr.scan_note()
            if _note:
                log("  note: " + _note)
        except Exception as _ex:
            log("  ! skeleton pass: %s" % _ex)
    model_lod = a.model_lod
    log(
        "\nMODELS: %d  (textures indexed: %d)%s"
        % (
            len(model_jobs),
            len(tex_index),
            (
                "  [%d entries: %d identical copies in other blocks not decoded again]"
                % (len(model_jobs) + mdl_repeats, mdl_repeats)
                if mdl_repeats
                else ""
            ),
        )
    )
    mdl_none = []  # models that gave no output: decode_model logged the reason
    glb_yes = 0
    glb_none = {}  # reason -> [model names]: decoded models that got no .glb (--glb)
    col_none = []  # models whose vertex colours are not decoded
    mdl_partial = []  # models decoded incompletely (fewer submeshes than the header lists)
    _platform_before = model_mesh.CONSOLE_PLATFORM
    for header, stream, out_path, mo, mplat in model_jobs:
        try:
            _st = model_export.MODEL_STATUS
            _st.clear()
            model_mesh.set_console_platform(mplat)
            # stored_name only for a respelled model (--names canonical)
            _kw = {"stored_name": model_stored[out_path]} if out_path in model_stored else {}
            if model_export.decode_model(
                header, stream, out_path, tex_index, log, order=mo, lod=model_lod, **_kw
            ):
                stats["mdl"] += 1
                _mn = out_path.name[: -len(".obj")]
                if _st.get("glb"):
                    glb_yes += 1
                elif _st.get("glb") is False:
                    glb_none.setdefault(_st.get("glb_reason") or "not written", []).append(_mn)
                if _st.get("color_not_decoded"):
                    col_none.append(_mn)
                if _st.get("partial"):
                    mdl_partial.append(_mn)
            else:
                mdl_none.append(out_path.name[: -len(".obj")])
        except Exception as ex:
            mdl_none.append(out_path.name[: -len(".obj")])
            log("      ! model %s: %s" % (out_path.name, ex))
    model_mesh.set_console_platform(_platform_before)

    if text_writer is not None:
        try:
            text_writer.write()
        except Exception as ex:
            log("  ! text assets: %s" % ex)

    if not a.no_nav:  # navigation data of the levels this run (or an earlier one) wrote
        try:
            import nav_data as _nav

            trees = _nav.extract_trees(a.out)
            if a.naz.is_dir():
                # a loose-folder source (Part 1 PC / Xbox Live) keeps the .hpd path
                # data and the .bik movies beside the folder it was given: bring
                # them to files/data/, where the archive sets have them (--no-files:
                # the path data is read in place, the movies are not fetched)
                if a.no_files:
                    trees = trees + [
                        p
                        for _n, p in _nav.loose_source_files(a.naz)
                        if not p.lower().endswith(".bik")
                    ]
                else:
                    stats["files"] += len(_nav.stage_loose_source(a.naz, a.out, log, name_run))
                    trees = _nav.extract_trees(a.out)
            res = _nav.export(trees, str(a.out / "nav"))
            if res:
                bad = sum(1 for r in res if "error" in r)
                log(
                    "NAV: %d level(s) -> %s%s"
                    % (len(res) - bad, a.out / "nav", ", %d failed" % bad if bad else "")
                )
                nohpd = [r["level"] for r in res if "error" not in r and not r.get("hpd")]
                if nohpd:
                    log(
                        "  WARNING: nav: no path data (.hpd) found for %s: definition only, no .nav.glb"
                        % ", ".join(nohpd)
                    )
        except Exception as ex:
            log("  ! navigation data: %s" % ex)

    log("\nDONE  (%d assets across %d blocks)" % (n_assets, len(blocks)))
    log("  files       : %d" % stats["files"])
    log(
        "  textures    : %d%s"
        % (
            stats["tex"],
            (
                "  (+ %d identical copies in other blocks, not written again)" % tex_repeats
                if tex_repeats
                else ""
            ),
        )
    )
    log(
        "  models      : %d%s"
        % (
            stats["mdl"],
            (
                "  of %d  (%d without output, reason logged above: %s)"
                % (len(model_jobs), len(mdl_none), ", ".join(sorted(mdl_none)))
                if mdl_none
                else ""
            ),
        )
    )
    if model_export._RIG["on"]:
        _ng = sum(len(v) for v in glb_none.values())
        log(
            "  model GLBs  : %d%s"
            % (
                glb_yes,
                (
                    '  (%d decoded model(s) WITHOUT a .glb; "glb" in their .model.json'
                    " says why)" % _ng
                    if _ng
                    else ""
                ),
            )
        )
        for _why, _nms in sorted(glb_none.items()):
            log(
                "  note: no GLB for %d model(s): %s: %s"
                % (
                    len(_nms),
                    _why,
                    ", ".join(sorted(_nms)[:12]) + (" ..." if len(_nms) > 12 else ""),
                )
            )
    if mdl_partial:
        log(
            '  WARNING: %d model(s) decoded incompletely ("submeshes" under not_decoded in'
            " their .model.json): %s" % (len(mdl_partial), ", ".join(sorted(mdl_partial)))
        )
    if col_none:
        log(
            "  note: vertex colours not decoded for %d model(s) (not_decoded: COLOR_0 in"
            " their .model.json; the console is not known and their data does not show"
            " the colour byte order: set WATCHMEN_CONSOLE=x360 or ps3)" % len(col_none)
        )
    if misc:
        _bad = ["%s %d of %d" % (k, v[1], v[0]) for k, v in sorted(misc.items()) if v[1]]
        log("  misc JSON   : %s" % ", ".join("%s %d" % (k, v[0]) for k, v in sorted(misc.items())))
        log(
            "  not decoded completely: %s"
            % (", ".join(_bad) + "  (a WARNING: line above names each)" if _bad else "none")
        )
    if raw_only:
        log(
            "  WARNING: raw only (no decoder for this kind; kept under extracted/): %s"
            % ", ".join("%s %d" % kv for kv in sorted(raw_only.items()))
        )
    if names.case_twins:
        log(
            "  names       : %d stored under a second spelling that differs only in letter case;"
            " written once, under the spelling of the first block in case-insensitive block"
            " order: %s"
            % (len(names.case_twins), ", ".join("%s (= %s)" % t for t in names.case_twins))
        )
    if names.variants:
        log(
            "  names       : %d stored with different content in different blocks; each kept"
            " under its own name: %s"
            % (len(names.variants), ", ".join(v[1] for v in names.variants))
        )
    try:
        name_run.write(a.out)
    except OSError as ex:
        log("  ! %s: %s" % (extract_paths.names_module().RUN_FILE, ex))
    if name_run.renamed:
        log(
            "  names       : %d written under their canonical spelling (--names stored keeps"
            " the archive's); canonical -> stored in %s"
            % (len(name_run.renamed), extract_paths.names_module().RUN_FILE)
        )
    log("  audio       : %d" % stats["aud"])
    log("  output      : %s" % a.out)
    if failed_blocks:
        log(
            "  ! blocks    : %d not extracted (reason logged above; exit code 1): %s"
            % (len(failed_blocks), ", ".join(failed_blocks))
        )
        return 1
    return 0


# ===========================================================================
# Names that live in other modules
# ===========================================================================
#: name here -> (home module, name there).  Reading `watchmen_extract.<name>`
#: gives the home's object; setting or deleting it (monkeypatch included) sets or
#: deletes it in the home, so every caller that looks it up there sees the change.
#: Code here calls such a name as `home.name`.
_HOMES = {
    "_RUN_LOG": ("extract_log", "_RUN_LOG"),
    "_run_warning": ("extract_log", "warn"),
    "is_warning_line": ("extract_log", "is_warning_line"),
    "extract_logger": ("extract_log", "extract_logger"),
    "ByteReader": ("byte_reader", "ByteReader"),
    "_Rd": ("byte_reader", "ByteReader"),
    "OutputNames": ("extract_paths", "OutputNames"),
    "standalone_output_name": ("extract_paths", "standalone_output_name"),
    "_WIN_DEVICES": ("extract_paths", "_WIN_DEVICES"),
    "_not_a_device": ("extract_paths", "_not_a_device"),
    "_no_trailing_dots": ("extract_paths", "_no_trailing_dots"),
    "_safe_path": ("extract_paths", "_safe_path"),
    "safe": ("extract_paths", "safe"),
    "out_rel": ("extract_paths", "out_rel"),
    "_names_mod": ("extract_paths", "names_module"),
    "NAZ_HEAD": ("naz_archive", "NAZ_HEAD"),
    "NAZ_LIST": ("naz_archive", "NAZ_LIST"),
    "_EOCD_FMT": ("naz_archive", "_EOCD_FMT"),
    "_EOCD": ("naz_archive", "_EOCD"),
    "_CD_FMT": ("naz_archive", "_CD_FMT"),
    "_CD": ("naz_archive", "_CD"),
    "_LFH": ("naz_archive", "_LFH"),
    "_rotl8": ("naz_archive", "_rotl8"),
    "_decrypt_name": ("naz_archive", "_decrypt_name"),
    "naz_key": ("naz_archive", "naz_key"),
    "NazEntry": ("naz_archive", "NazEntry"),
    "LOOSE_SUFFIXES": ("naz_archive", "LOOSE_SUFFIXES"),
    "loose_entries": ("naz_archive", "loose_entries"),
    "naz_entries": ("naz_archive", "naz_entries"),
    "MAX_INFLATE": ("naz_archive", "MAX_INFLATE"),
    "max_inflate": ("naz_archive", "max_inflate"),
    "inflate": ("naz_archive", "inflate"),
    "naz_read": ("naz_archive", "naz_read"),
    "_naz_inflate": ("naz_archive", "_naz_inflate"),
    "block_plan": ("naz_archive", "block_plan"),
    "iter_blocks": ("naz_archive", "iter_blocks"),
    "BLOCK_HEADER_SIZE": ("kapow_block", "BLOCK_HEADER_SIZE"),
    "BLOCK_TABLES_START": ("kapow_block", "BLOCK_TABLES_START"),
    "TABLES_SIZE_OFFSET": ("kapow_block", "TABLES_SIZE_OFFSET"),
    "NUM_TABLES_OFFSET": ("kapow_block", "NUM_TABLES_OFFSET"),
    "BLOCK_LANGUAGES": ("kapow_block", "BLOCK_LANGUAGES"),
    "STREAM_PAIRS": ("kapow_block", "STREAM_PAIRS"),
    "SIZE_VARIANTS": ("kapow_block", "SIZE_VARIANTS"),
    "BLOCK_LANGUAGE_NAMES": ("kapow_block", "BLOCK_LANGUAGE_NAMES"),
    "_FINGERPRINT_KEY": ("kapow_block", "_FINGERPRINT_KEY"),
    "_name_hash": ("kapow_block", "_name_hash"),
    "_kprops": ("kapow_block", "props_module"),
    "ASSET_TYPE_NAMES": ("kapow_block", "ASSET_TYPE_NAMES"),
    "_asset_types": ("kapow_block", "_asset_types"),
    "asset_type_name": ("kapow_block", "asset_type_name"),
    "asset_base_class": ("kapow_block", "asset_base_class"),
    "fingerprint_decrypt": ("kapow_block", "fingerprint_decrypt"),
    "Toc": ("kapow_block", "Toc"),
    "BLOCK_ORDER": ("kapow_block", "BLOCK_ORDER"),
    "detect_block_order": ("kapow_block", "detect_block_order"),
    "fingerprint_field_crc": ("kapow_block", "fingerprint_field_crc"),
    "parse_block_header": ("kapow_block", "parse_block_header"),
    "parse_block_toc": ("kapow_block", "parse_block_toc"),
    "parse_block_trailer": ("kapow_block", "parse_block_trailer"),
    "block_stream_sets": ("kapow_block", "block_stream_sets"),
    "stream_file_lookup": ("kapow_block", "stream_file_lookup"),
    "asset_compressed": ("kapow_block", "asset_compressed"),
    "maybe_inflate": ("kapow_block", "maybe_inflate"),
    "asset_class": ("kapow_block", "asset_class"),
    "header_order": ("kapow_block", "header_order"),
    "extract_block": ("kapow_block", "extract_block"),
    "STANDALONE_SIGNATURES": ("kapow_block", "STANDALONE_SIGNATURES"),
    "standalone_preamble": ("kapow_block", "standalone_preamble"),
    "inflate_standalone": ("kapow_block", "inflate_standalone"),
    "_header_order_or_none": ("kapow_block", "header_order_or_none"),
    "language_slot": ("kapow_block", "language_slot"),
    "language_arg": ("kapow_block", "language_arg"),
    "prop_walk": ("kapow_block", "prop_walk"),
    "_PROP_WALK_CAP": ("kapow_block", "_PROP_WALK_CAP"),
    "_PROP_WALK_WARNED": ("kapow_block", "_PROP_WALK_WARNED"),
    "_propbag_end": ("kapow_block", "propbag_end"),
    "_maybe_inflate": ("kapow_block", "maybe_inflate"),
    "_language_arg": ("kapow_block", "language_arg"),
    "_prop_walk": ("kapow_block", "prop_walk"),
    "texture_alpha_flag": ("texture_header", "texture_alpha_flag"),
    "TEX_ENUMS": ("texture_header", "TEX_ENUMS"),
    "TEX_FMT": ("texture_header", "TEX_FMT"),
    "_is_texture": ("texture_header", "is_texture_header"),
    "TEXTURE_SLOTS": ("texture_header", "TEXTURE_SLOTS"),
    "TEXTURE_SLOT_LABELS": ("texture_header", "TEXTURE_SLOT_LABELS"),
    "TEXTURE_LAYER_SLOTS": ("texture_header", "TEXTURE_LAYER_SLOTS"),
    "CUBE_FACE_ORDER": ("texture_header", "CUBE_FACE_ORDER"),
    "_parse_texture_anim_tail": ("texture_header", "_parse_texture_anim_tail"),
    "texture_frame_ms": ("texture_header", "texture_frame_ms"),
    "_TEX_DESC": ("texture_header", "_TEX_DESC"),
    "chain_bytes_exact": ("texture_header", "chain_bytes_exact"),
    "parse_texture_frames": ("texture_header", "parse_texture_frames"),
    "_exact_texture_plan": ("texture_header", "_exact_texture_plan"),
    "parse_texture_header": ("texture_header", "parse_texture_header"),
    "_is_normal_layer": ("texture_header", "is_normal_layer"),
    "texture_layer_label": ("texture_header", "texture_layer_label"),
    "chain_bytes": ("texture_header", "chain_bytes"),
    "_tex_path_off": ("texture_header", "_tex_path_off"),
    "_valid_rec": ("texture_header", "_valid_rec"),
    "_stride_layers": ("texture_header", "_stride_layers"),
    "plan_texture_layers": ("texture_header", "plan_texture_layers"),
    "header_dims": ("texture_header", "header_dims"),
    "_chain_bytes_exact": ("texture_header", "chain_bytes_exact"),
    "_chain_bytes": ("texture_header", "chain_bytes"),
    "_SPEC_HI": ("texture_sheet", "_SPEC_HI"),
    "_SPEC_EXP": ("texture_sheet", "_SPEC_EXP"),
    "_SPEC_INT": ("texture_sheet", "_SPEC_INT"),
    "TEXTURE_SHEET_PROPS": ("texture_sheet", "TEXTURE_SHEET_PROPS"),
    "SHEET_RENDER_TYPES": ("texture_sheet", "SHEET_RENDER_TYPES"),
    "sheet_hashes": ("texture_sheet", "sheet_hashes"),
    "texture_sheet": ("texture_sheet", "texture_sheet"),
    "SHEET_PROPERTIES": ("texture_sheet", "SHEET_PROPERTIES"),
    "SHEET_LAYER_OVERRIDES": ("texture_sheet", "SHEET_LAYER_OVERRIDES"),
    "SHEET_BLEND_TYPES": ("texture_sheet", "SHEET_BLEND_TYPES"),
    "SHEET_BLEND_FACTORS": ("texture_sheet", "SHEET_BLEND_FACTORS"),
    "SHEET_BLEND_OPS": ("texture_sheet", "SHEET_BLEND_OPS"),
    "_T_UNIQUE_ID": ("texture_sheet", "_T_UNIQUE_ID"),
    "sheet_keys": ("texture_sheet", "sheet_keys"),
    "_untyped_sheets": ("texture_sheet", "_untyped_sheets"),
    "texture_sheets": ("texture_sheet", "texture_sheets"),
    "select_sheet": ("texture_sheet", "select_sheet"),
    "sheet_blend": ("texture_sheet", "sheet_blend"),
    "blend_layer_image": ("texture_sheet", "blend_layer_image"),
    "blend_material": ("texture_sheet", "blend_material"),
    "write_sheet_json": ("texture_sheet", "write_sheet_json"),
    "_sheet_warning": ("texture_sheet", "sheet_warning"),
    "read_sheet_json": ("texture_sheet", "read_sheet_json"),
    "extract_specular": ("texture_sheet", "extract_specular"),
    "TEXTURE_DECODE_KEY": ("texture_sheet", "TEXTURE_DECODE_KEY"),
    "_mark_texture_decode": ("texture_sheet", "mark_texture_decode"),
    "mark_stored_name": ("texture_sheet", "mark_stored_name"),
    "first_sheet": ("texture_sheet", "first_sheet"),
    "_sheet_hashes": ("texture_sheet", "sheet_hashes"),
    "_sheet_keys": ("texture_sheet", "sheet_keys"),
    "_write_sheet_json": ("texture_sheet", "write_sheet_json"),
    "_mark_stored_name": ("texture_sheet", "mark_stored_name"),
    "DDS_MAGIC": ("texture_decode", "DDS_MAGIC"),
    "FOURCC": ("texture_decode", "FOURCC"),
    "mip_chain_size": ("texture_decode", "mip_chain_size"),
    "base_mip_bytes": ("texture_decode", "base_mip_bytes"),
    "make_dds": ("texture_decode", "make_dds"),
    "decode_dxt_base": ("texture_decode", "decode_dxt_base"),
    "_bc4_channel": ("texture_decode", "_bc4_channel"),
    "decode_bc5_base": ("texture_decode", "decode_bc5_base"),
    "ati2_xy": ("texture_decode", "ati2_xy"),
    "normal_to_png": ("texture_decode", "normal_to_png"),
    "_coherence": ("texture_decode", "image_coherence"),
    "_looks_like_normal": ("texture_decode", "looks_like_normal"),
    "_unpad_linear": ("texture_decode", "unpad_linear"),
    "decode_one_layer": ("texture_decode", "decode_one_layer"),
    "_decode_dxt3a": ("texture_decode", "_decode_dxt3a"),
    "bswap16": ("texture_decode", "bswap16"),
    "xg2d_offset": ("texture_decode", "xg2d_offset"),
    "_xg_untile": ("texture_decode", "_xg_untile"),
    "_x360_packed_offset": ("texture_decode", "_x360_packed_offset"),
    "_thin_mip_yoff": ("texture_decode", "_thin_mip_yoff"),
    "_x360_layer_bytes": ("texture_decode", "x360_layer_bytes"),
    "_ps3_segments": ("texture_decode", "ps3_segments"),
    "_console_recover_layers": ("texture_decode", "console_recover_layers"),
    "rsx_unswizzle": ("texture_decode", "rsx_unswizzle"),
    "_texel32_to_pc": ("texture_decode", "_texel32_to_pc"),
    "_x360_level0_bytes": ("texture_decode", "x360_level0_bytes"),
    "x360_base_level": ("texture_decode", "x360_base_level"),
    "ps3_layer_image": ("texture_decode", "ps3_layer_image"),
    "_decode_one_layer": ("texture_decode", "decode_one_layer"),
    "_bswap16": ("texture_decode", "bswap16"),
    "_xg2d": ("texture_decode", "xg2d_offset"),
    "_rsx_unswizzle": ("texture_decode", "rsx_unswizzle"),
    "_x360_base_level": ("texture_decode", "x360_base_level"),
    "_ps3_layer_image": ("texture_decode", "ps3_layer_image"),
    "_console_prefix": ("texture_carve", "_console_prefix"),
    "_save_layer_png": ("texture_carve", "_save_layer_png"),
    "_carve_x360_exact": ("texture_carve", "_carve_x360_exact"),
    "_carve_ps3_exact": ("texture_carve", "_carve_ps3_exact"),
    "carve_texture_console": ("texture_carve", "carve_texture_console"),
    "_write_spec_txt": ("texture_carve", "_write_spec_txt"),
    "RESCUE_MAX_PLANS": ("texture_carve", "RESCUE_MAX_PLANS"),
    "_exact_mip_sums": ("texture_carve", "_exact_mip_sums"),
    "rescue_texture_plan": ("texture_carve", "rescue_texture_plan"),
    "PC_CUBE_LEVEL_MAJOR": ("texture_carve", "PC_CUBE_LEVEL_MAJOR"),
    "carve_texture": ("texture_carve", "carve_texture"),
    "_carve_texture": ("texture_carve", "_carve_texture"),
    "_carve_texture_legacy": ("texture_carve", "_carve_texture_legacy"),
    "_rescue_texture_plan": ("texture_carve", "rescue_texture_plan"),
    "_u32le": ("material_refs", "_u32le"),
    "_u32": ("material_refs", "u32_at"),
    "_TEX_RE": ("material_refs", "_TEX_RE"),
    "texture_key": ("material_refs", "texture_key"),
    "TexRef": ("material_refs", "TexRef"),
    "texture_ref": ("material_refs", "texture_ref"),
    "extract_materials": ("material_refs", "extract_materials"),
    "_u32_all": ("material_refs", "_u32_all"),
    "_descriptor_candidates": ("material_refs", "_descriptor_candidates"),
    "submesh_materials": ("material_refs", "submesh_materials"),
    "_material_stem": ("material_refs", "material_stem"),
    "VERTEX_STRIDES": ("model_header", "VERTEX_STRIDES"),
    "VERTEX_FORMATS": ("model_header", "VERTEX_FORMATS"),
    "CONSOLE_VERTEX_STRIDES": ("model_header", "CONSOLE_VERTEX_STRIDES"),
    "CONSOLE_VERTEX_FORMATS": ("model_header", "CONSOLE_VERTEX_FORMATS"),
    "_STREAM_RECORDS": ("model_header", "_STREAM_RECORDS"),
    "_VOLUME_FLOATS": ("model_header", "_VOLUME_FLOATS"),
    "console_header_decode": ("model_header", "console_header_decode"),
    "vertex_strides": ("model_header", "vertex_strides"),
    "vertex_formats": ("model_header", "vertex_formats"),
    "read_meshbuffer": ("model_header", "read_meshbuffer"),
    "PRIMITIVE_NAMES": ("model_header", "PRIMITIVE_NAMES"),
    "index_triangles": ("model_header", "index_triangles"),
    "_mr_part": ("model_header", "_mr_part"),
    "MODEL_LAYOUTS": ("model_header", "MODEL_LAYOUTS"),
    "model_header_layout_hint": ("model_header", "model_header_layout_hint"),
    "_parse_model_header_as": ("model_header", "_parse_model_header_as"),
    "parse_model_header": ("model_header", "parse_model_header"),
    "model_stream_layout": ("model_header", "model_stream_layout"),
    "check_lod": ("model_header", "check_lod"),
    "model_lod_arg": ("model_header", "model_lod_arg"),
    "BUFFER_KINDS": ("model_header", "BUFFER_KINDS"),
    "BUFFER_KIND_ALIASES": ("model_header", "BUFFER_KIND_ALIASES"),
    "BUFFER_ROLES": ("model_header", "BUFFER_ROLES"),
    "_LOD_PAIRS": ("model_header", "_LOD_PAIRS"),
    "model_property_bag": ("model_header", "model_property_bag"),
    "model_lod_info": ("model_header", "model_lod_info"),
    "model_surfaces": ("model_header", "model_surfaces"),
    "select_model_buffers": ("model_header", "select_model_buffers"),
    "_part_local_matrix": ("model_header", "_part_local_matrix"),
    "_part_is_identity": ("model_header", "_part_is_identity"),
    "model_part_transforms": ("model_header", "model_part_transforms"),
    "apply_part_transform": ("model_header", "apply_part_transform"),
    "_mr_meshbuffer": ("model_header", "read_meshbuffer"),
    "_model_lod_arg": ("model_header", "model_lod_arg"),
    "is_finite_float": ("model_mesh", "is_finite_float"),
    "_vb_run": ("model_mesh", "_vb_run"),
    "_read_ib": ("model_mesh", "_read_ib"),
    "_pick_vb": ("model_mesh", "pick_vertex_buffer"),
    "find_descriptors": ("model_mesh", "find_descriptors"),
    "ib_ok": ("model_mesh", "ib_ok"),
    "vb_ok": ("model_mesh", "vb_ok"),
    "vb_ok_flat": ("model_mesh", "vb_ok_flat"),
    "_dec1110": ("model_mesh", "_dec1110"),
    "LASH_RESTORE": ("model_mesh", "LASH_RESTORE"),
    "synth_enabled": ("model_mesh", "synth_enabled"),
    "lash_strips": ("model_mesh", "lash_strips"),
    "lash_restored_uvs": ("model_mesh", "lash_restored_uvs"),
    "lash_is_restored": ("model_mesh", "lash_is_restored"),
    "lash_reconstruction_note": ("model_mesh", "lash_reconstruction_note"),
    "_strided": ("model_mesh", "_strided"),
    "_unit_rows": ("model_mesh", "_unit_rows"),
    "_rows3": ("model_mesh", "_rows3"),
    "decode_mesh_vertices": ("model_mesh", "decode_mesh_vertices"),
    "_decode_sub_np": ("model_mesh", "_decode_sub_np"),
    "_dec1110_array": ("model_mesh", "_dec1110_array"),
    "CONSOLE_COLOR_ORDERS": ("model_mesh", "CONSOLE_COLOR_ORDERS"),
    "CONSOLE_PLATFORM": ("model_mesh", "CONSOLE_PLATFORM"),
    "_PLATFORM_DIRS": ("model_mesh", "_PLATFORM_DIRS"),
    "_PLATFORM_CACHE": ("model_mesh", "_PLATFORM_CACHE"),
    "console_platform_of": ("model_mesh", "console_platform_of"),
    "set_console_platform": ("model_mesh", "set_console_platform"),
    "console_platform": ("model_mesh", "console_platform"),
    "detect_console_platform": ("model_mesh", "detect_console_platform"),
    "console_platform_for": ("model_mesh", "console_platform_for"),
    "_console_color_order_inferred": ("model_mesh", "_console_color_order_inferred"),
    "console_color_order": ("model_mesh", "console_color_order"),
    "_console_color_white": ("model_mesh", "_console_color_white"),
    "console_color_undecoded": ("model_mesh", "console_color_undecoded"),
    "decode_vertex_attributes": ("model_mesh", "decode_vertex_attributes"),
    "gltf_tangents": ("model_mesh", "gltf_tangents"),
    "decode_model_mesh": ("model_mesh", "decode_model_mesh"),
    "half_to_float": ("model_mesh", "half_to_float"),
    "_sane": ("model_mesh", "is_finite_float"),
    "_ib_ok": ("model_mesh", "ib_ok"),
    "_vb_ok": ("model_mesh", "vb_ok"),
    "_vb_ok_flat": ("model_mesh", "vb_ok_flat"),
    "_decode_sub": ("model_mesh", "decode_mesh_vertices"),
    "_half": ("model_mesh", "half_to_float"),
    "sheet_layer_dirs": ("obj_mtl", "sheet_layer_dirs"),
    "TEXTURE_DIR_EXTS": ("obj_mtl", "TEXTURE_DIR_EXTS"),
    "TextureIndex": ("obj_mtl", "TextureIndex"),
    "build_texture_index": ("obj_mtl", "build_texture_index"),
    "resolve_texture": ("obj_mtl", "resolve_texture"),
    "unique_material_names": ("obj_mtl", "unique_material_names"),
    "find_layer": ("obj_mtl", "find_layer"),
    "_make_roughness": ("obj_mtl", "_make_roughness"),
    "_materials_mode": ("obj_mtl", "materials_mode"),
    "mtl_no_highlight": ("obj_mtl", "mtl_no_highlight"),
    "_mtl_opacity": ("obj_mtl", "_mtl_opacity"),
    "_mtl_emission": ("obj_mtl", "_mtl_emission"),
    "mtl_const_roughness": ("obj_mtl", "mtl_const_roughness"),
    "mtl_ns_of_roughness": ("obj_mtl", "mtl_ns_of_roughness"),
    "_make_roughness_engine": ("obj_mtl", "_make_roughness_engine"),
    "write_obj_mtl": ("obj_mtl", "write_obj_mtl"),
    "_find_layer": ("obj_mtl", "find_layer"),
    "_mtl_no_highlight": ("obj_mtl", "mtl_no_highlight"),
    "_mtl_const_roughness": ("obj_mtl", "mtl_const_roughness"),
    "_mtl_ns_of_roughness": ("obj_mtl", "mtl_ns_of_roughness"),
    "_write_obj_mtl": ("obj_mtl", "write_obj_mtl"),
    "_RIG": ("model_export", "_RIG"),
    "_texture_size_arg": ("model_export", "_texture_size_arg"),
    "_rig_load": ("model_export", "_rig_load"),
    "_model_palette": ("model_export", "_model_palette"),
    "_model_is_body": ("model_export", "_model_is_body"),
    "_surface_summary": ("model_export", "_surface_summary"),
    "_parts_summary": ("model_export", "_parts_summary"),
    "PARTS_NOTE": ("model_export", "PARTS_NOTE"),
    "_model_tail_meta": ("model_export", "_model_tail_meta"),
    "MORPH_CHANNEL_NOTE": ("model_export", "MORPH_CHANNEL_NOTE"),
    "model_meta": ("model_export", "model_meta"),
    "model_meta_reduced": ("model_export", "model_meta_reduced"),
    "model_meta_scanned": ("model_export", "model_meta_scanned"),
    "_header_model_plan": ("model_export", "_header_model_plan"),
    "_model_skipped": ("model_export", "_model_skipped"),
    "MODEL_STATUS": ("model_export", "MODEL_STATUS"),
    "decode_model": ("model_export", "decode_model"),
    "_decode_model": ("model_export", "_decode_model"),
    "_media_link": ("sound_header", "_media_link"),
    "media_tracks_pc": ("sound_header", "media_tracks_pc"),
    "_TRACK0": ("sound_header", "_TRACK0"),
    "media_track_name": ("sound_header", "media_track_name"),
    "_media_walk_segments": ("sound_header", "_media_walk_segments"),
    "_ps3_media_link": ("sound_header", "_ps3_media_link"),
    "_ps3_media_seg": ("sound_header", "_ps3_media_seg"),
    "_ps3_media_walk": ("sound_header", "_ps3_media_walk"),
    "_console_media_parse": ("sound_header", "console_media_parse"),
    "_ps3_media_tracks": ("sound_header", "_ps3_media_tracks"),
    "_x360_media_tracks": ("sound_header", "_x360_media_tracks"),
    "media_tracks_console": ("sound_header", "media_tracks_console"),
    "_xma_frame_count": ("sound_header", "xma_frame_count"),
    "media_meta_from_header": ("sound_header", "media_meta_from_header"),
    "media_desc_from_header": ("sound_header", "media_desc_from_header"),
    "adpcm_layout": ("sound_header", "adpcm_layout"),
    "sfx_info": ("sound_header", "sfx_info"),
    "_MP3_KBPS": ("sound_header", "_MP3_KBPS"),
    "_MP3_RATE": ("sound_header", "_MP3_RATE"),
    "mp3_frame_stats": ("sound_header", "mp3_frame_stats"),
    "_ps3_sound_info": ("sound_header", "_ps3_sound_info"),
    "_COEF": ("audio_decode", "_COEF"),
    "_COEFB": ("audio_decode", "_COEFB"),
    "_ADAPT": ("audio_decode", "_ADAPT"),
    "_C1": ("audio_decode", "_C1"),
    "_C2": ("audio_decode", "_C2"),
    "_audio_packets": ("audio_decode", "audio_packets"),
    "_ogg_crc_table": ("audio_decode", "_ogg_crc_table"),
    "_OGGCRC": ("audio_decode", "_OGGCRC"),
    "_ogg_crc": ("audio_decode", "_ogg_crc"),
    "_lacing": ("audio_decode", "_lacing"),
    "OGG_PAGE_BYTES": ("audio_decode", "OGG_PAGE_BYTES"),
    "_OggWriter": ("audio_decode", "_OggWriter"),
    "_BR": ("audio_decode", "_BR"),
    "_expect": ("audio_decode", "_expect"),
    "_ilog": ("audio_decode", "_ilog"),
    "_lk1": ("audio_decode", "_lk1"),
    "vorbis_blockflags": ("audio_decode", "vorbis_blockflags"),
    "ogg_from_packets": ("audio_decode", "ogg_from_packets"),
    "decode_audio": ("audio_decode", "decode_audio"),
    "decode_audio_tracks": ("audio_decode", "decode_audio_tracks"),
    "_xma2_riff": ("audio_decode", "_xma2_riff"),
    "_emit_audio": ("audio_decode", "_emit_audio"),
    "decode_sfx_console": ("audio_decode", "decode_sfx_console"),
    "decode_console_audio": ("audio_decode", "decode_console_audio"),
    "_clamp16": ("audio_decode", "_clamp16"),
    "ADPCM_COEF_PAIRS": ("audio_decode", "ADPCM_COEF_PAIRS"),
    "adpcm_predict": ("audio_decode", "adpcm_predict"),
    "adpcm_mono": ("audio_decode", "adpcm_mono"),
    "_adpcm_stereo": ("audio_decode", "_adpcm_stereo"),
    "decode_sfx": ("audio_decode", "decode_sfx"),
    "_smpl_chunk": ("audio_decode", "_smpl_chunk"),
    "write_wav": ("audio_decode", "write_wav"),
    "_vorbis_blockflags": ("audio_decode", "vorbis_blockflags"),
    "_ogg_from_packets": ("audio_decode", "ogg_from_packets"),
    "_COEF_PAIRS": ("audio_decode", "ADPCM_COEF_PAIRS"),
    "_adpcm_predict": ("audio_decode", "adpcm_predict"),
    "_adpcm_mono": ("audio_decode", "adpcm_mono"),
}


def _forwarding_type(homes):
    """A module type with one property per name in `homes` that reads, sets and
    deletes the name in its home module.  A property is a data descriptor, so
    attribute access goes through it before the module's own namespace, and
    monkeypatch (pytest 9.2 restores a module attribute from the module's
    namespace unless a data descriptor serves it) records and restores the
    home's value."""

    def forward(home, there):
        def get(_mod):
            return getattr(importlib.import_module(home), there)

        def put(_mod, value):
            setattr(importlib.import_module(home), there, value)

        def drop(_mod):
            delattr(importlib.import_module(home), there)

        return property(get, put, drop, "%s.%s" % (home, there))

    names = {name: forward(*home) for name, home in homes.items()}
    return type("_Forwarding", (types.ModuleType,), names)


sys.modules[__name__].__class__ = _forwarding_type(_HOMES)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
