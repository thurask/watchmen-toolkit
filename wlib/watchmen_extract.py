#!/usr/bin/env python3
"""
watchmen_extract.py  --  master asset extractor for
*Watchmen: The End Is Nigh, Part 2* (Kapow engine, PC).

Feed it game.naz and it walks the whole chain we reverse-engineered and writes:

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

Pipeline (see docs/WATCHMEN_EXTRACTION_MASTER.md for the gory detail):
  NAZ      obfuscated ZIP: filenames rotate-left-2 encrypted, custom EOCD/CD magics.
  BLOCK    <name>.block_h_z (TOC + per-asset header blobs) + <name>.block_s_z
           (per-asset zlib streams). Standalone _h_z/_s_z and .mediastream_s too.
  TEXTURE  "TextureSheet": diffuse (DXT1/DXT5) + normal (BC5/ATI2) + spec (DXT1),
           auto-located from header power-of-two dims + the BC5 normal signature.
  MODEL    interleaved vertex buffer (pos f32 + normal + RGBA8 + uv f16 + tan/bitan),
           stride 44 (rigid) / 56 (skinned), then a u16 triangle-list index buffer.
  AUDIO    raw Vorbis packets (no Ogg framing) in [32-byte block][packet] framing,
           in ~40 KB chunks, one chunk per track per group, groups chained by
           link records; rebuilt into one real Ogg Vorbis file per track.

Usage:
    python watchmen_extract.py game.naz -o OUT
        [--no-files] [--no-textures] [--no-models] [--no-audio]
        [--exact-audio]   sample-perfect Ogg granulepos (parses Vorbis modes)
        [--flat-music]    music streams as ONE file each (the 1.3.0 output)
        [--music-track-labels]  MusicStreamSlot track names in the file names
        [--smpl-loops]    RIFF smpl loop chunk on sounds with the loop flag
        [--no-text]       no text/ (every text asset, every language)
        [--no-nav]        no nav/ (per level navigation mesh + graph)
        [--limit N]       stop after N block assets (debug)
        [--quiet]

Requires numpy + Pillow for textures/models (audio is pure-stdlib). Python 3.8+.
"""

from __future__ import annotations
import argparse, io, os, re, struct, sys, zlib, array, wave
from pathlib import Path

# MS-ADPCM tables (SFX 'sound' assets are MS-ADPCM/PCM -> WAV; music stays Ogg)
_COEF = (256, 0, 512, -256, 0, 0, 192, 64, 240, 0, 460, -208, 392, -232)
_COEFB = struct.pack("<14h", *_COEF)
_ADAPT = (230, 230, 230, 230, 307, 409, 512, 614, 768, 614, 512, 409, 307, 230, 230, 230)
_C1 = (256, 512, 0, 192, 240, 460, 392)
_C2 = (0, -256, 0, 64, 0, -208, -232)

try:
    import numpy as np
    from PIL import Image

    HAVE_IMG = True
except Exception:
    HAVE_IMG = False


# ===========================================================================
# (1) NAZ container
# ===========================================================================
NAZ_HEAD = 0x16ED5B50  # EOCD magic (vs ZIP 0x06054B50)
NAZ_LIST = 0x0406F370  # central-directory entry magic
_EOCD_FMT = "<IHHHHIIH"
_EOCD = struct.calcsize(_EOCD_FMT)
_CD_FMT = "<I2H3I5H2I4H"
_CD = struct.calcsize(_CD_FMT)
_LFH = 30


def _rotl8(x, r=2):
    x &= 0xFF
    return ((x << r) | (x >> (8 - r))) & 0xFF


def _decrypt_name(b):
    return bytes(_rotl8(c, 2) for c in b).decode("utf-8", "replace")


def naz_key(name):
    """Key the engine files an archive entry under (mount 0x4428fb): the raw CRC
    (0x423ca1, no 0xDF fold) of the name with '\\' turned into '/' and A-Z
    lower-cased (0x4ebe76).  The engine keeps no entry name, only this key; a
    file is looked up by its path without the leading '/' (0x43f9a1)."""
    try:
        import kapow_props as _kp
    except ImportError:
        _d = os.path.dirname(os.path.abspath(__file__))
        if _d not in sys.path:
            sys.path.append(_d)
        import kapow_props as _kp
    low = "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in name.replace("\\", "/"))
    return _kp.kapow_hash(low.encode("utf-8", "replace").decode("latin1"))


class NazEntry:
    __slots__ = ("name", "compr", "psize", "usize", "data_off", "path", "key")

    def __init__(s, name, compr, psize, usize, data_off, path=None, key=None):
        s.name, s.compr, s.psize, s.usize, s.data_off = name, compr, psize, usize, data_off
        s.path = path  # set for loose-file entries (Part 1); None inside a .naz
        s.key = key  # engine index key (naz_key) of an archive entry; None for a loose file


# Loose asset containers (Watchmen Part 1 ships these directly on disk under
# derived_pc/ instead of packing them into a .naz -- see loose_entries()).
LOOSE_SUFFIXES = (
    ".block_h_z",
    ".block_s_z",
    ".texture_h_z",
    ".texture_s_z",
    ".modelres_h_z",
    ".modelres_s_z",
    ".pivotbook_h_z",
    ".pivotbook_s_z",
    ".mediastream_s",
)


def loose_entries(root):
    """Yield NazEntry objects for the loose asset files under a directory tree.

    Part 1 leaves the same block/texture/modelres/mediastream containers loose
    on disk that Part 2 packs into a .naz; their bytes are byte-for-byte what
    the .naz stores internally, so every downstream decoder works unchanged.
    Entry names mirror .naz naming (leading '/', forward slashes) so stems stay
    unique across directories and grab_blocks/main pair the halves correctly."""
    root = os.path.abspath(str(root))
    for dirpath, _dirs, files in os.walk(root):
        _dirs.sort()  # os.walk order is filesystem-dependent; entry order must not be
        for fn in sorted(files):
            if not fn.lower().endswith(LOOSE_SUFFIXES):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            sz = os.path.getsize(full)
            # compr=0: bytes are returned verbatim; the "_z" suffix is a naming
            # convention, not naz-level compression (inner zlib is handled by
            # extract_block / inflate_standalone downstream, same as the naz path).
            yield NazEntry("/" + rel, 0, sz, sz, 0, path=full)


def naz_entries(path, warn=None):
    """Entries of a .naz archive (or of a loose `files` tree, see loose_entries).

    What the ENGINE does with an archive (mount 0x4428fb, lookup 0x43f9a1) and
    where this reader differs on purpose:
    * it reads the EOCD at size - 22; magic 0x16ED5B50 marks a .naz (names
      rotated, fields 8 bytes earlier); any other value is taken as a plain
      .zip -- this reader raises on anything but a .naz;
    * it never reads the central-directory magic or a compression method and
      never inflates: an entry is `size` bytes (the field this reader calls
      `usize`) at local-header offset + 30 + nameLen + extraLen, used as stored.
      naz_read() inflates method 8, which the engine would not: `warn` (a
      callable taking one string) is told about every entry with compr != 0;
    * it keeps no names: the index is `key` = naz_key(name); a later entry with
      the same key replaces the earlier one, and across archives the lowest
      mount slot wins."""
    if os.path.isdir(str(path)):
        yield from loose_entries(path)
        return
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        fsize = f.tell()
        if fsize < _EOCD:
            raise ValueError("not a NAZ archive (%d bytes, shorter than the EOCD record)" % fsize)
        f.seek(fsize - _EOCD)
        magic, _dk, _dkc, _di, titem, _ds, doffs, _cs = struct.unpack(_EOCD_FMT, f.read(_EOCD))
        if magic != NAZ_HEAD:
            raise ValueError("not a NAZ archive (EOCD magic 0x%08X)" % magic)
        cur = doffs
        for _ in range(titem):
            f.seek(cur)
            rec = struct.unpack(_CD_FMT, f.read(_CD))
            (
                cmagic,
                _mt,
                _md,
                _crc,
                psize,
                usize,
                nsize,
                isize,
                csize,
                _ds2,
                _ia,
                _ea,
                hoffs,
                _cv,
                _nv,
                _flags,
                compr,
            ) = rec
            if cmagic != NAZ_LIST:
                raise ValueError("bad central-dir magic at 0x%X" % cur)
            f.seek(cur + _CD)
            name = _decrypt_name(f.read(nsize))
            if compr and warn is not None:
                warn(
                    "%s: compression method %d -- the engine reads archive entries as "
                    "stored (0x4428fb reads no method field)" % (name, compr)
                )
            yield NazEntry(
                name, compr, psize, usize, hoffs + _LFH + nsize + isize, key=naz_key(name)
            )
            cur += _CD + nsize + isize + csize


def naz_read(path, e):
    if getattr(e, "path", None) is not None:  # loose Part 1 file
        with open(e.path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        f.seek(e.data_off)
        raw = f.read(e.psize)
    if e.compr == 0:
        return raw
    if e.compr == 8:
        return zlib.decompress(raw, -15)
    raise ValueError("unsupported compression %d for %s" % (e.compr, e.name))


# ===========================================================================
# (2) Kapow block (.block_h_z / .block_s_z)
# ===========================================================================
# Fixed header = exactly 400 bytes (one read of 0x190 bytes, engine 0x4ae315);
# the directory follows at 400.  Engine: loader FUN_004a36d8, walker FUN_004a3525.
BLOCK_HEADER_SIZE = 400
BLOCK_TABLES_START, TABLES_SIZE_OFFSET, NUM_TABLES_OFFSET = BLOCK_HEADER_SIZE, 332, 352
#: every directory record carries SIX slots of (header-blob size) and of
#: (stream offset, size).  The slot index is the current LANGUAGE (FUN_0045c762),
#: not the build platform; the six are equal except on localized assets.
BLOCK_LANGUAGES = 6
STREAM_PAIRS, SIZE_VARIANTS = BLOCK_LANGUAGES, BLOCK_LANGUAGES
#: slot -> (LANGUAGE enum name 0x47ff8c, engine two-letter code registered by the
#: platform constructor 0x45fb96, ISO code used for the text/ folders)
BLOCK_LANGUAGE_NAMES = (
    ("English", "uk", "en"),
    ("French", "fr", "fr"),
    ("Italian", "it", "it"),
    ("German", "de", "de"),
    ("Spanish", "es", "es"),
    ("Danish", "dk", "da"),
)
_FINGERPRINT_KEY = b"1E564E3B-D243-4ec5-AFB7"


def _name_hash(s):
    """Engine name hash (FUN_00423ce8: every byte & 0xDF) via kapow_props."""
    try:
        import kapow_props as _kp
    except ImportError:
        _d = os.path.dirname(os.path.abspath(__file__))
        if _d not in sys.path:
            sys.path.append(_d)
        import kapow_props as _kp
    fn = getattr(_kp, "name_hash", None)
    return (
        fn(s)
        if fn
        else _kp.kapow_hash(bytes(c & 0xDF for c in s.encode("latin1")).decode("latin1"))
    )


def _kprops():
    """kapow_props, imported like _name_hash does (flat wlib module)."""
    try:
        import kapow_props as _kp
    except ImportError:
        _d = os.path.dirname(os.path.abspath(__file__))
        if _d not in sys.path:
            sys.path.append(_d)
        import kapow_props as _kp
    return _kp


#: asset-type names whose name hash is the directory's `type_hash` field.
ASSET_TYPE_NAMES = (
    "sound",
    "Texture",
    "animation",
    "fragment",
    "modelRes",
    "textRes",
    "PropertySequenceAsset",
    "ParticleSystemAsset",
    "grass",
    "mediastream",
    "DetailMeshAsset",
    "terrain",
    "pivotbook",
    "aipathdata",
    "font",  # 0x62f2722a (registered 0x5431f5): three .font records in each main block
    # 0xf1fdbe49 (registered 0x531981): no record in any Part 2 block; Part 1 data has them
    "terrainColoringAsset",
    "ModelEffects(ModelRes)",  # 0x41764525: TNT script class on top of ModelRes
    "TextureEffects(Texture)",  # 0x96ea413f: TNT script class on top of Texture
)
_ASSET_TYPES = {}


def asset_type_name(type_hash):
    """Directory type hash -> asset-type name ('' when unknown)."""
    if not _ASSET_TYPES:
        for n in ASSET_TYPE_NAMES:
            _ASSET_TYPES[_name_hash(n)] = n
    return _ASSET_TYPES.get(type_hash, "")


def asset_base_class(cls):
    """'ModelEffects(ModelRes)' -> 'ModelRes'.  Script (TNT) asset classes are read
    by their native base class's loader (FUN_0047e126 stores the base at +0x5c;
    FUN_00511f96 only re-types the entity), so they extract like the base type."""
    if cls.endswith(")") and "(" in cls:
        return cls[cls.rindex("(") + 1 : -1]
    return cls


def fingerprint_decrypt(buf, key=_FINGERPRINT_KEY):
    """Block-header fingerprint string: 3-LFSR stream cipher (FUN_00405a31 init,
    FUN_00405a8b key setup, FUN_00405b1e per byte), applied by FUN_0049dd0e."""
    a = int.from_bytes(key[0:4], "big") or 0x13579BDF
    b = int.from_bytes(key[4:8], "big") or 0x2468ACE0
    c = int.from_bytes(key[8:12], "big") or 0xFDB97531
    out = bytearray()
    for ch in buf:
        if ch == 0:
            break
        ob, oc, k = b & 1, c & 1, 0
        for _ in range(8):
            if a & 1:
                a = ((a ^ 0x80000062) >> 1) | 0x80000000
                if b & 1:
                    b, ob = ((b ^ 0x40000020) >> 1) | 0xC0000000, 1
                else:
                    b, ob = (b >> 1) & 0x3FFFFFFF, 0
            else:
                a = (a >> 1) & 0x7FFFFFFF
                if c & 1:
                    c, oc = ((c ^ 0x10000002) >> 1) | 0xF0000000, 1
                else:
                    c, oc = (c >> 1) & 0x0FFFFFFF, 0
            k = ((k << 1) & 0xFF) | (ob ^ oc)
        v = ch ^ k
        out.append(v if v else k)
    return bytes(out)


class Toc:
    """One directory record (FUN_004a3525):
    [u32 size[6]][u32 typeHash][u32 nameLen][name][u8 hasStream][6 x (u32 off, u32 size)]
    The stream pairs are the TAIL of the record they locate (no +1 shift)."""

    __slots__ = (
        "name",
        "type_hash",
        "sizes",
        "has_stream",
        "streams",
        "localized",
        "language",
        "inflate_failed",
        "stream_file",
        "stream_note",
    )

    def __init__(s):
        s.name, s.type_hash, s.sizes = "", 0, [0] * BLOCK_LANGUAGES
        s.has_stream, s.streams, s.localized, s.language = False, None, False, 0
        s.inflate_failed = []  # "header" / "stream": blobs extract_block could not inflate
        s.stream_file = None  # stream-set file the stream was read from (not the block's own)
        s.stream_note = None  # why a stream named by a stream set could not be read

    @property
    def compressed(s):
        """Whether the engine reads this record's blobs through zlib (0x5480fe:
        useCompressedAssets, default 1, and the type's compressible flag): True
        for every asset type except `mediastream`; None when the type hash is
        not a known asset type."""
        return asset_compressed(s.type_name)

    # --- names used before the layout was read from the engine (read + write) --
    @property
    def flag(s):
        return 1 if s.has_stream else 0

    @flag.setter
    def flag(s, v):
        s.has_stream = bool(v)

    @property
    def pairs(s):
        return list(s.streams) if s.streams else []

    @pairs.setter
    def pairs(s, v):
        s.streams = list(v) if v else None

    @property
    def variants(s):
        return list(s.sizes)

    @variants.setter
    def variants(s, v):
        s.sizes = list(v)

    @property
    def unknown(s):
        return s.type_hash

    @unknown.setter
    def unknown(s, v):
        s.type_hash = v

    @property
    def type_name(s):
        return asset_type_name(s.type_hash)

    @property
    def data_size(s):
        v = s.sizes[s.language] if 0 <= s.language < len(s.sizes) else 0
        if v > 0:
            return v
        for v in s.sizes:
            if v > 0:
                return v
        return s.sizes[-1]

    @property
    def best_stream(s):
        if not s.streams:
            return None
        if 0 <= s.language < len(s.streams):
            off, sz = s.streams[s.language]
            if sz > 0:
                return off, sz
        for off, sz in s.streams:
            if off > 0 and sz > 0:
                return off, sz
        return s.streams[0]


# Block numeric fields are stored in the target CPU's byte order: little-endian
# on PC, BIG-endian on the PowerPC consoles (Xbox 360 / PS3).  The naz container
# itself stays little-endian on every platform, and inner zlib + ASCII strings
# (names, GUIDs) are byte-order-independent, so ONLY the block-header integer
# reads need to flip.  detect_block_order() reads NUM_TABLES both ways and keeps
# the interpretation that is a plausible asset count -- no CLI flag required.
BLOCK_ORDER = "<"  # last auto-detected block byte order (for downstream use)


def detect_block_order(h):
    le = struct.unpack_from("<I", h, NUM_TABLES_OFFSET)[0]
    be = struct.unpack_from(">I", h, NUM_TABLES_OFFSET)[0]
    le_sz = struct.unpack_from("<I", h, TABLES_SIZE_OFFSET)[0]
    be_sz = struct.unpack_from(">I", h, TABLES_SIZE_OFFSET)[0]
    le_ok = 1 <= le <= 500000 and le_sz <= len(h)
    be_ok = 1 <= be <= 500000 and be_sz <= len(h)
    if le_ok and not be_ok:
        return "<"
    if be_ok and not le_ok:
        return ">"
    return "<" if le <= be else ">"  # correct count is small; wrong one is huge


def fingerprint_field_crc(text):
    """What a block header stores @328 for the fingerprint `text`: the engine's raw
    bit-CRC (no 0xDF fold) over the 255-byte plaintext field, the text padded with
    zero bytes."""
    field = (text.encode("latin1") + bytes(255))[:255]
    return _kprops().kapow_hash(field.decode("latin1"))


def parse_block_header(h, order=None):
    """The fixed 400-byte block_h_z header as a dict (engine FUN_004a36d8 /
    FUN_0049dd0e; field names follow what the loader does with each value)."""
    if len(h) < BLOCK_HEADER_SIZE:
        raise ValueError("not a block header: %d bytes, need %d" % (len(h), BLOCK_HEADER_SIZE))
    bo = order or detect_block_order(h)
    (
        _raw328,
        tables_size,
        entry0_size,
        io_buffer_size,
        fragment_offset,
        fragment_size,
        num_entries,
        num_localized,
        num_streams,
    ) = struct.unpack_from(bo + "9I", h, 328)
    fingerprint = fingerprint_decrypt(h[0x48:0x147]).decode("latin1")
    fingerprint_crc = int.from_bytes(h[328:332], "little")
    return {
        "order": bo,
        "bounds": struct.unpack_from(bo + "8f", h, 0),  # -> LoadBlock+0x180
        "guid": h[0x24:0x48].split(b"\0", 1)[0].decode("latin1"),
        "fingerprint": fingerprint,
        # u8 @327 -> LoadBlock+0x1e4 (0x49dd59): 0 = draw " Finger Print Key: <text>" on
        # debug overlay page 2 until 20 s after its first draw in the process, then the
        # engine sets 2; 1 = always; 2 = never (reader 0x490e35).  2 in every block.
        "fingerprint_display": h[327],
        # u32 @328, little-endian on every platform: the unfolded bit-CRC (kapow_hash)
        # of the 255-byte plaintext fingerprint field (text + zero padding); 0x593F880A
        # for the default text.  Not read by the loader.
        "fingerprint_crc": fingerprint_crc,
        "fingerprint_crc_ok": fingerprint_crc == fingerprint_field_crc(fingerprint),
        # u32 @32 in block byte order: the block version signature, a CRC over "8"
        # and every asset type's version (0x49db60).  The PC loader computes it and
        # discards the result (0x4a3b5e): it is never compared with the file.
        # 0x79D3E0DA in every Part 2 block and PS3 Part 1, 0xEE1FB0A3 in PC / X360 Part 1.
        "version_signature": struct.unpack_from(bo + "I", h, 32)[0],
        "unknown_327": h[327],  # the older name of fingerprint_display
        # the four bytes of fingerprint_crc as stored: 0a 88 3f 59 in every staged
        # block, NOT byte-swapped on the consoles.  (Up to 1.3.0 this was returned as
        # `version_signature`.)
        "unknown_328": bytes(h[328:332]),
        "low_violence": bool(h[388]),  # OR-ed into the platform's flag (0x435c0b)
        "tables_size": tables_size,  # directory bytes, starting at 400
        "entry0_size": entry0_size,  # header-blob size of entry 0 (first read)
        "io_buffer_size": io_buffer_size,  # max(tables_size, largest header blob)
        "fragment_offset": fragment_offset,  # trailing "loadblock fragment" blob
        "fragment_size": fragment_size,
        "num_entries": num_entries,
        "num_localized": num_localized,  # extra records behind the language seek
        "num_streams": num_streams,  # records with hasStream == 1
        "language_header_offset": struct.unpack_from(bo + "6I", h, 364),
    }


def parse_block_toc(h, order=None, language=0):
    """-> (entries, data_start).  `entries` holds the `num_entries` main records
    followed by the `num_localized` per-language ones (`.localized` is True)."""
    global BLOCK_ORDER
    if (
        isinstance(language, bool)
        or not isinstance(language, int)
        or not (0 <= language < BLOCK_LANGUAGES)
    ):
        raise ValueError("language slot must be 0..%d, not %r" % (BLOCK_LANGUAGES - 1, language))
    bo = order or detect_block_order(h)
    BLOCK_ORDER = bo
    tables_size = struct.unpack_from(bo + "I", h, TABLES_SIZE_OFFSET)[0]
    num = struct.unpack_from(bo + "I", h, NUM_TABLES_OFFSET)[0]
    nloc = struct.unpack_from(bo + "I", h, 356)[0]
    end = min(len(h), BLOCK_HEADER_SIZE + tables_size)
    if not 0 <= nloc <= 4096:
        nloc = 0
    out, pos = [], BLOCK_HEADER_SIZE
    for i in range(num + nloc):
        if pos + 32 > end:
            break
        t = Toc()
        t.language = language
        t.localized = i >= num
        t.sizes = list(struct.unpack_from(bo + "6I", h, pos))
        pos += 24
        t.type_hash = struct.unpack_from(bo + "I", h, pos)[0]
        pos += 4
        nlen = struct.unpack_from(bo + "I", h, pos)[0]
        pos += 4
        t.name = h[pos : pos + nlen].decode("utf-8", "replace").rstrip("\x00")
        pos += nlen
        t.has_stream = pos < end and h[pos] == 1  # ReadBool (FUN_004353e9)
        pos += 1
        t.streams = None
        if t.has_stream:
            if pos + 48 > len(h):
                t.has_stream = False
            else:
                v = struct.unpack_from(bo + "12I", h, pos)
                pos += 48
                t.streams = [(v[2 * k], v[2 * k + 1]) for k in range(BLOCK_LANGUAGES)]
        out.append(t)
    return out, BLOCK_HEADER_SIZE + tables_size


def parse_block_trailer(h, order=None):
    """The trailing "loadblock fragment" blob at header `fragment_offset`
    (readers 0x4ab461 automatic sets, 0x4a01d7 manual sets, 0x4e1a59 one set):

        [u32 nAuto]   nAuto x StreamSet
        [u32 nManual] nManual x { [u32 n][n x u32 pathId] StreamSet }
        StreamSet = [f32 x 3 min][f32 x 3 max][str streamFile][u32][u32 count]
                    count x { [u32 typeHash][str name] 6 x ([u32 offset][u32 size]) }
        str = [u32 len][len bytes]

    -> {"auto_stream_sets": [...], "manual_stream_sets": [...], "size", "end"}.
    Both lists are empty (the blob is eight zero bytes) in every block but one:
    Part 1's Prison block holds four MANUAL sets (PC, X360 and PS3 alike), whose
    `stream_file` is a separate `.block_s_z` ("/derived_pc/Levels/.../Art/
    PrisonYard.block_s_z") holding the streams of 96 Texture / ModelRes entries
    that have no stream record in the directory.  That data fixes the bounds at
    two 3-float vectors (all zero there) and shows the u32 before the count
    equal to the count; the code reading gave two 4-float vectors, which is
    tried only when the 3-float layout does not end exactly at the blob's end.
    Each set carries "bounds_floats" (6 or 8).  Raises ValueError when the blob
    follows neither layout."""
    hd = parse_block_header(h, order)
    bo = hd["order"]
    p, size = hd["fragment_offset"], hd["fragment_size"]
    end = p + size
    if end > len(h):
        raise ValueError("block trailer runs past the file (%d + %d > %d)" % (p, size, len(h)))

    def take(fmt):
        nonlocal p
        n = struct.calcsize(fmt)
        if p + n > end:
            raise ValueError("block trailer: read past its end")
        v = struct.unpack_from(bo + fmt, h, p)
        p += n
        return v

    def string():
        nonlocal p
        (n,) = take("I")
        if p + n > end:
            raise ValueError("block trailer: string runs past its end")
        v = h[p : p + n].split(b"\0", 1)[0].decode("latin1")
        p += n
        return v

    def stream_set():
        st = {"min": take(vec), "max": take(vec), "stream_file": string()}
        st["bounds_floats"] = 2 * int(vec[0])
        (st["value"],) = take("I")  # -> set+0x40; equals the entry count in the Prison data
        (n,) = take("I")
        st["entries"] = []
        for _ in range(n):
            (th,) = take("I")
            name = string()
            v = take("12I")
            st["entries"].append(
                {
                    "type_hash": th,
                    "type": asset_type_name(th),
                    "name": name,
                    "streams": [(v[2 * k], v[2 * k + 1]) for k in range(BLOCK_LANGUAGES)],
                }
            )
        return st

    def tables():
        (n_auto,) = take("I")
        auto = [stream_set() for _ in range(n_auto)]
        (n_manual,) = take("I")
        manual = []
        for _ in range(n_manual):
            (n,) = take("I")
            if n * 4 > end - p:
                raise ValueError("block trailer: node path runs past its end")
            ids = ["%08x" % x for x in take("%dI" % n)]
            st = stream_set()
            st["node_path"] = ids
            manual.append(st)
        return {"auto_stream_sets": auto, "manual_stream_sets": manual, "size": size, "end": p}

    start, first_error, loose = p, None, None
    for vec in ("3f", "4f"):  # data layout first, then the one read from the code
        p = start
        try:
            got = tables()
        except ValueError as ex:
            first_error = first_error or ex
            continue
        if got["end"] == end:
            return got
        loose = loose or got
    if loose is not None:  # parsed, but short of the blob's end: as before 1.4.0
        return loose
    raise first_error


def block_stream_sets(h, order=None):
    """Every stream set of a block (automatic first, then manual) ->
    ([set dict of parse_block_trailer], error text or None).  The error is set
    when the trailing blob does not parse; the list is then empty."""
    try:
        t = parse_block_trailer(h, order)
    except (ValueError, struct.error) as ex:
        return [], str(ex)
    return t["auto_stream_sets"] + t["manual_stream_sets"], None


def stream_file_lookup(files):
    """Resolver for the `stream_file` paths of stream sets over `files`, a
    {archive entry name: bytes} dict of the `.block_s_z` entries.  A set names
    its file from the platform's derived root ("/derived_pc/Levels/Game_Levels/
    Prison/Art/PrisonYard.block_s_z"); archive / loose-tree names start below
    it, so leading path components are dropped until one name matches
    (compared lower-cased, '/' separators).  -> callable(path) -> bytes | None."""
    low = {}
    for name, data in files.items():
        low.setdefault("/" + name.replace("\\", "/").lower().strip("/"), data)

    def find(path):
        parts = path.replace("\\", "/").lower().strip("/").split("/")
        for i in range(len(parts)):
            hit = low.get("/" + "/".join(parts[i:]))
            if hit is not None:
                return hit
        return None

    return find


def asset_compressed(type_name):
    """Engine rule for a block blob (0x5480fe, headers 0x54811c and streams
    0x548abe alike): zlib iff useCompressedAssets (config, default 1) and the
    asset type is compressible -- every type but `mediastream` (0x554a2e clears
    the flag).  None for an unknown type name."""
    if not type_name:
        return None
    return asset_base_class(type_name).lower() != "mediastream"


def _maybe_inflate(blob, type_name=None, report=None):
    """A block blob as the engine reads it.  With a known asset `type_name` the
    type decides (asset_compressed): raw for `mediastream`, zlib for every other
    type, and a blob that then does not inflate is reported through `report`
    (a callable taking the zlib error text) and returned as stored.  Without a
    type the first byte is sniffed, as before 1.4.0."""
    comp = asset_compressed(type_name)
    if comp is False:
        return blob
    if comp or (len(blob) >= 2 and blob[0] == 0x78):
        try:
            return zlib.decompress(blob)
        except zlib.error as ex:
            if comp and report is not None:
                report(str(ex))
    return blob


def asset_class(header, order=None):
    if len(header) < 8:
        return "unknown"
    for bo in ((order,) if order else ("<", ">")):
        tlen = struct.unpack_from(bo + "I", header, 0)[0]
        if 1 <= tlen <= 32 and 4 + tlen <= len(header):
            raw = header[4 : 4 + tlen]
            if all(32 <= b < 127 or b == 0 for b in raw):
                return raw.split(b"\x00", 1)[0].decode("ascii", "replace")
    return "unknown"


def header_order(header):
    """Byte order of an extracted asset header, read from the header itself: it
    opens with [u32 length][class name, NUL-terminated], the length in the byte
    order of the block it came from ("<" PC, ">" Xbox 360 / PS3) -- the field
    asset_class reads with the archive's order.  None when the opening is not such
    a name in exactly one order.  This is the ONE byte-order test for a header read
    outside its block (character parts, ragdoll rig, model nodes, skeleton names);
    inside `extract` the block's own order is passed down."""
    if len(header) < 8:
        return None
    hit = []
    for bo in ("<", ">"):
        n = struct.unpack_from(bo + "I", header, 0)[0]
        if not 2 <= n <= 64 or 4 + n > len(header):
            continue
        raw = header[4 : 4 + n]
        if raw[-1] == 0 and raw[:1].isalpha() and all(32 < b < 127 for b in raw[:-1]):
            hit.append(bo)
    return hit[0] if len(hit) == 1 else None


# WM07 stores per-texture material params in the texture header as 64-bit
# name-hashed records (verified against the game's pixel shader: $specularData.xy).
_SPEC_HI = 0xBDA17DE4
_SPEC_EXP = 0xF4142D28  # specular exponent (Blinn-Phong power)  -> c2.x
_SPEC_INT = 0xB3AB3306  # specular intensity (0 = matte)         -> c2.y


#: TextureSheet properties (texturesheet.cpp registration strings, exe 0xA2F7A7..);
#: name -> property type.  The record is [salt u32][name hash u32][type hash u32]
#: [tag u32][value], both hashes being kapow_hash of the strings.
TEXTURE_SHEET_PROPS = {
    "renderType": "integer",
    "isLit": "truth",
    "alphaThreshold": "integer",
    "writeDepthBuffer": "truth",
    "twoSided": "truth",
    "blendType": "integer",
    "opacity": "number",
    "normalMapPower": "number",
    "enableNormalMapping": "truth",
}
#: renderType values (exe dropdown string "Standard:0,Standard with blending:1,...")
SHEET_RENDER_TYPES = {
    0: "standard",
    1: "blend",
    2: "glass",
    3: "water",
    6: "hair",
    7: "skybox",
    9: "sprite",
    10: "falloff",
    11: "wet",
}
_SHEET_HASH = {}


def _sheet_hashes():
    if not _SHEET_HASH:
        for nm in list(TEXTURE_SHEET_PROPS) + ["integer", "truth", "number"]:
            _SHEET_HASH[nm] = _name_hash(nm)
    return _SHEET_HASH


def texture_sheet(header, order="<"):
    """Material properties of a Texture header's FIRST TextureSheet (the one in
    use unless a collection node selects another; a header can hold further named
    sheets, see face_rule.texture_sheets) -> {name: value} for
    TEXTURE_SHEET_PROPS, or {} when the header has none.

    twoSided is the byte the renderer turns into D3DCULL_NONE (FUN_00571d5d,
    sheet+0xA4); renderType 1 is "Standard with blending"; alphaThreshold is the
    alpha-test reference (0..255) of the standard type; normalMapPower scales the
    normal map's x and y ($effectFactors.x)."""
    H = _sheet_hashes()
    n = len(header)
    salt = None
    rt = H["renderType"]
    ti = H["integer"]
    for o in range(0, n - 20):
        s0, lo, hi = struct.unpack_from(order + "III", header, o)
        if lo == rt and hi == ti:
            salt = s0
            start = o
            break
    if salt is None:
        # older record layout (standalone Part 1, PC / X360): no type hash to find
        for sh in _untyped_sheets(header, order):
            if "renderType" in sh:
                return {
                    k: (sh[k] & 0xFFFFFFFF) if TEXTURE_SHEET_PROPS[k] == "integer" else sh[k]
                    for k in TEXTURE_SHEET_PROPS
                    if k in sh
                }
        return {}
    out = {}
    want = {H[k]: k for k in TEXTURE_SHEET_PROPS}
    for o in range(start, n - 20):
        s0, lo, hi = struct.unpack_from(order + "III", header, o)
        if s0 != salt or lo not in want:
            continue
        nm = want[lo]
        typ = TEXTURE_SHEET_PROPS[nm]
        if hi != H[typ] or nm in out:
            continue
        if typ == "number":
            out[nm] = struct.unpack_from(order + "f", header, o + 16)[0]
        elif typ == "truth":
            out[nm] = bool(struct.unpack_from(order + "I", header, o + 16)[0])
        else:
            out[nm] = struct.unpack_from(order + "I", header, o + 16)[0]
    return out


#: every property of a TextureSheet (TextureSheet::RegisterMembers 0x526589), in
#: the order a Texture header stores them
SHEET_PROPERTIES = (
    "name uniqueID renderType isLit selfIlluminance selfIlluminanceColor normalMapPower "
    "specularPower specularSize bloomPower opacity shadowPower alphaThreshold "
    "writeDepthBuffer castShadow receiveShadow twoSided enableNormalMapping enablePOM "
    "enableAnimation animationDelayInMs reflectionType depthFogPower depthFadeScale "
    "depthFadeGradient depthFadeGradientAlpha useWaterDepthFade glassThickness "
    "materialColor materialColorAlpha fresnelPower waterEffectFadeRange "
    "reflectionBumpPower refractionBumpPower reflectionLightFactor waterNormalType "
    "maxReflection uScrollSpeed vScrollSpeed u2ScrollSpeed v2ScrollSpeed resetUVOffset "
    "heightScale heightBias numHeightSamples numLightSamples secondaryHighlightShift "
    "highlightBumpScale blendType srcBlend dstBlend blendOp fallOffPower fallOffColor "
    "renderOrder lodPOMDistance lodPOMFadeOut lodNormalMapDistance lodNormalMapFadeOut "
    "diffuseMapOverride normalMapOverride glowMapOverride heightMapOverride "
    "specularMapOverride fallOffMapOverride ambOccMapOverride specSizeMapOverride "
    "diffuseMapChannel normalMapChannel glowMapChannel heightMapChannel "
    "specularMapChannel fallOffMapChannel ambOccMapChannel specSizeMapChannel "
    "inheritDeferredLight"
).split()
#: <layer>MapOverride property -> the layer label the texture carve uses.
#: Engine (read): the draw path asks the mesh's sheet for each layer through
#: 0x49c838(sheet, layer) -> 0x4991f0: the override texture of that layer when the
#: sheet has one (handles at sheet+0x190 diffuse, +0x19c normal, +0x1a8 specular,
#: +0x1b4 glow, +0x1c0 height, +0x1cc fallOff, +0x1d8 ambOcc, +0x1e4 specSize), else
#: the sheet's own texture (+0x64); then the SAME layer of that texture (0x49be2d).
#: Any sheet, the first included.  Called from the material binds at 0x58a849,
#: 0x58acd0, 0x571da8, 0x589d35 ...
SHEET_LAYER_OVERRIDES = {
    "diffuseMapOverride": "diffuse",
    "normalMapOverride": "normal",
    "specularMapOverride": "specMap",
    "specSizeMapOverride": "specSize",
    "glowMapOverride": "glow",
    "heightMapOverride": "height",
    "fallOffMapOverride": "fallOff",
    "ambOccMapOverride": "ambOcc",
}
#: blendType (exe dropdown "standard:0,add:1,subtract:2,manual:3")
SHEET_BLEND_TYPES = {0: "standard", 1: "add", 2: "subtract", 3: "manual"}
#: srcBlend / dstBlend and blendOp of blend type `manual` (the D3DBLEND / D3DBLENDOP values)
SHEET_BLEND_FACTORS = {
    1: "zero",
    2: "one",
    3: "srcColor",
    4: "invSrcColor",
    5: "srcAlpha",
    6: "invSrcAlpha",
    7: "dstAlpha",
    8: "invDstAlpha",
    9: "dstColor",
    10: "invDstColor",
    11: "srcAlphaSat",
}
SHEET_BLEND_OPS = {1: "add", 2: "subtract", 3: "revSubtract", 4: "max", 5: "min"}
_T_UNIQUE_ID = 0xEDEF427C  # type hash of the uniqueID record
_SHEET_KEYS = {}


def _sheet_keys():
    if not _SHEET_KEYS:
        for nm in SHEET_PROPERTIES:
            _SHEET_KEYS[_name_hash(nm)] = nm
        for t in ("number", "integer", "truth", "string", "vector", "color"):
            _SHEET_KEYS[("type", _name_hash(t))] = t
        _SHEET_KEYS[("type", _T_UNIQUE_ID)] = "id"
    return _SHEET_KEYS


def _untyped_sheets(header, order="<", raw=False):
    """TextureSheet objects of a Texture header in the OLDER record layout
    ([salt][name hash][payload dwords][payload], no type hash: standalone Part 1
    on PC / X360) -> [{property: value}] in file order, [] when the header has
    none.  Exact: each `[u32 13]["TextureSheet\0"][u32 dwords]` object must read
    to its end (kapow_props.read_records); value types are the ones the typed
    builds store for the same properties (kapow_props.untyped_types).  With
    `raw`, a property is kept under its name whatever it is; otherwise only
    SHEET_PROPERTIES, as texture_sheets() returns them."""
    kp = _kprops()
    K = _sheet_keys()
    ut = kp.untyped_types()
    names = kp.namedict() if raw else {}
    out = []
    for ob in kp.find_objects(header, order, ("TextureSheet",)):
        if ob["layout"] != "untyped":
            continue
        sh = {}
        for _o, key, _th, q, k in ob["records"]:
            nm = K.get(key) or names.get(key)
            if nm is None:
                continue
            val = kp.record_value(ut.get(key), header, q, k, order)
            if val is None and ut.get(key) != "string":
                continue  # no known type for this property: not guessed
            if isinstance(val, list):
                val = [round(x, 6) for x in val]
            sh.setdefault(nm, val)
        out.append(sh)
    return out


def texture_sheets(header, order="<"):
    """Every TextureSheet of a Texture header, in file order -> [dict].

    A texture holds one or more named sheets (material settings); the first is the
    one in use unless a model instance names another by its uniqueID
    (`textureSheetsDescription`, BaseModel 0x4a56c2 -> sheet lookup 0x524caf, which
    falls back to the first sheet).  Each dict has the sheet's stored properties
    (SHEET_PROPERTIES: `name`, `uniqueID`, renderType, blendType, twoSided,
    alphaThreshold, specularSize / specularPower, the UV scroll speeds ...) and
    `overrides` {layer label: texture asset path} for the non-empty
    <layer>MapOverride strings: the sheet takes that layer from another texture.

    Records are [salt u32][name hash u32][type hash u32][payload dwords u32]
    [payload]; all records of one sheet share the salt."""
    K = _sheet_keys()
    n = len(header)
    sheets, by_salt = [], {}
    o = 0
    while o + 16 <= n:
        salt, key, typ, cnt = struct.unpack_from(order + "IIII", header, o)
        nm, ty = K.get(key), K.get(("type", typ))
        if nm is None or ty is None or not 1 <= cnt <= 4096 or o + 16 + 4 * cnt > n:
            o += 1
            continue
        p = o + 16
        if ty == "number":
            val = struct.unpack_from(order + "f", header, p)[0]
        elif ty == "truth":
            val = bool(struct.unpack_from(order + "I", header, p)[0])
        elif ty == "integer":
            val = struct.unpack_from(order + "i", header, p)[0]
        elif ty == "id":
            hi, lo = struct.unpack_from(order + "II", header, p) if cnt >= 2 else (0, 0)
            val = (hi << 32) | lo
        elif ty == "string":
            val = header[p + 4 : p + 4 * cnt].split(b"\0", 1)[0].decode("latin-1")
        else:
            val = [round(x, 6) for x in struct.unpack_from(order + "%df" % cnt, header, p)]
        sh = by_salt.get(salt)
        if sh is None:
            sh = by_salt[salt] = {"overrides": {}}
            sheets.append(sh)
        if nm in SHEET_LAYER_OVERRIDES:
            if val:
                sh["overrides"].setdefault(SHEET_LAYER_OVERRIDES[nm], val)
        else:
            sh.setdefault(nm, val)
        o = p + 4 * cnt
    # a sheet has a render type; anything else that matched is not one
    sheets = [sh for sh in sheets if "renderType" in sh]
    if not sheets:  # older record layout (standalone Part 1, PC / X360)
        for src in _untyped_sheets(header, order):
            if "renderType" not in src:
                continue
            sh = {"overrides": {}}
            for nm, val in src.items():
                if nm in SHEET_LAYER_OVERRIDES:
                    if val:
                        sh["overrides"].setdefault(SHEET_LAYER_OVERRIDES[nm], val)
                else:
                    sh[nm] = val
            sheets.append(sh)
    return sheets


def select_sheet(sheets, ref=None):
    """The sheet `ref` names among `sheets` (texture_sheets / sheet.json "sheets"):
    None -> the first; an int -> the one with that uniqueID; a str -> by name.  An
    unknown id or name gives the first sheet, as the engine does (0x4a56c2)."""
    if not sheets:
        return {}
    if ref is not None:
        for sh in sheets:
            if (isinstance(ref, int) and sh.get("uniqueID") == ref) or (
                isinstance(ref, str) and sh.get("name") == ref
            ):
                return sh
    return sheets[0]


def sheet_blend(sheet):
    """How the sheet's surface is combined with what is behind it -> dict or None.

    Read from the render-state setup (0x582eb6; RESkyBox 0x589dd9 for render type
    7) and the list routing (0x5739d0).  The render types "Standard with
    blending" (1), SkyBox (7) and Sprite (9) blend; so does a Standard (0) or
    FallOff (10) sheet whose opacity is below 0.99, which the engine moves to the
    blended list and draws with the sheet's own blendType (the opacity of the
    model instance and the LOD weight multiply in at run time and are not known
    here).  {"type": standard | add | subtract | manual, "src", "dst", "op": the
    D3D blend factors / operator the engine sets, "gltf": how a glTF material can
    show it -- "exact" (alpha blending), "ink" (subtract: black with the texture's
    brightness as coverage), "glow" (add: emissive with the brightness as
    coverage) or None (no glTF expression), "cause": "renderType" | "opacity" (why
    the sheet is in a blended list)}."""
    if not sheet:
        return None
    rt = sheet.get("renderType", 1)
    cause = "renderType"
    if rt not in (1, 7, 9):
        op = sheet.get("opacity")
        if rt not in (0, 10) or op is None or not float(op) < 0.99:
            return None
        cause = "opacity"
    bt = sheet.get("blendType") or 0
    sky = rt == 7
    if bt == 0:
        src, dst, op = 5, 6, 1
    elif bt == 1:
        src, dst, op = (2, 2, 1) if sky else (5, 2, 1)
    elif bt == 2:
        src, dst, op = (2, 2, 2) if sky else (5, 2, 3)
    elif bt == 3:
        src, dst, op = sheet.get("srcBlend", 5), sheet.get("dstBlend", 6), sheet.get("blendOp", 1)
    else:
        return None
    if (src, dst, op) == (5, 6, 1):
        how = "exact"
    elif op == 1 and dst == 2 and src in (2, 5):
        how = "glow"
    elif op == 3 and dst == 2 and src in (2, 5):
        how = "ink"
    else:
        how = None
    return {
        "type": SHEET_BLEND_TYPES.get(bt, str(bt)),
        "src": SHEET_BLEND_FACTORS.get(src, src),
        "dst": SHEET_BLEND_FACTORS.get(dst, dst),
        "op": SHEET_BLEND_OPS.get(op, op),
        "gltf": how,
        "cause": cause,
    }


def blend_layer_image(img, blend):
    """The diffuse layer as a glTF base colour for a blend that is not plain alpha
    blending (sheet_blend "gltf" ink / glow); `img` and the result are PIL images.

    ink  (engine: dst - src.rgb * src.a): black, alpha = brightness * alpha.  Drawn
         alphaMode BLEND it removes the same share of a white surface; over a darker
         one it removes proportionally less than the game does.
    glow (engine: dst + src.rgb * src.a): the colour at full brightness, alpha =
         brightness * alpha; with the same image as emissive texture a BLEND material
         adds src.rgb * src.a, and dims what is behind it by that alpha, which the
         game does not."""
    from PIL import Image, ImageChops

    how = (blend or {}).get("gltf")
    if how not in ("ink", "glow"):
        return img
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    if how == "ink":
        cov = ImageChops.multiply(rgba.convert("L"), a)
        zero = Image.new("L", rgba.size, 0)
        return Image.merge("RGBA", (zero, zero, zero, cov))
    import numpy as _np

    peak = ImageChops.lighter(ImageChops.lighter(r, g), b)
    cov = ImageChops.multiply(peak, a)
    c = _np.asarray(rgba, _np.float32)[..., :3]
    m = _np.maximum(_np.asarray(peak, _np.float32), 1.0)[..., None]
    full = _np.clip(c * 255.0 / m + 0.5, 0, 255).astype(_np.uint8)
    out = _np.dstack([full, _np.asarray(cov, _np.uint8)])
    return Image.fromarray(out, "RGBA")


def blend_material(mat, blend, emissive_index=None, opacity=None):
    """Write `blend` (sheet_blend) into the glTF material dict `mat`: alphaMode,
    the emissive part of a glow, and extras.watchmen with the engine's blend.
    opacity: the sheet's opacity.  A glow whose source factor is the source alpha
    (SRCALPHA / ONE: blend type add outside the sky pass, or a manual blend) adds
    src.rgb * src.a, and the alpha the shader writes carries the opacity (SkyBoxPS:
    texture alpha * vertex alpha * opacity), so an opacity below 1 scales the
    emissiveFactor.  ONE / ONE (blend type add in the sky pass) does not read the
    alpha and keeps factor 1."""
    if not blend or blend["type"] == "standard":
        return mat
    how = blend.get("gltf")
    info = {"blend": blend["type"], "src": blend["src"], "dst": blend["dst"], "op": blend["op"]}
    if how == "ink":
        mat["alphaMode"] = "BLEND"
        mat.pop("alphaCutoff", None)
        info["note"] = (
            "engine blend type %s (dst - src): baseColorTexture is the layer "
            "rewritten as black with alpha = the game texture's brightness" % blend["type"]
        )
    elif how == "glow":
        mat["alphaMode"] = "BLEND"
        mat.pop("alphaCutoff", None)
        mat.setdefault("pbrMetallicRoughness", {})["baseColorFactor"] = [0.0, 0.0, 0.0, 1.0]
        fade = 1.0
        if opacity is not None and blend["src"] == SHEET_BLEND_FACTORS.get(5):
            fade = min(max(float(opacity), 0.0), 1.0)
        if emissive_index is not None:
            mat["emissiveTexture"] = {"index": emissive_index}
            mat["emissiveFactor"] = [round(fade, 6)] * 3
        if fade < 1.0:
            info["opacity"] = round(fade, 6)
        info["note"] = (
            "engine blend type %s (dst + src): the layer at full brightness is the "
            "emissive texture, alpha = the game texture's brightness" % blend["type"]
        )
    elif how == "exact":
        mat["alphaMode"] = "BLEND"
        mat.pop("alphaCutoff", None)
    else:
        info["note"] = "this blend has no glTF expression; the material is written unblended"
    mat.setdefault("extras", {}).setdefault("watchmen", {}).update(info)
    return mat


def sheet_layer_dirs(tex_index, sheet, warn=None):
    """{layer label: texture dir} for the layers `sheet` takes from another texture
    (its <layer>MapOverride paths), resolved in `tex_index`; missing ones are left out."""
    out = {}
    for layer, path in sorted((sheet or {}).get("overrides", {}).items()):
        d = resolve_texture(tex_index, texture_ref(path), warn) if tex_index else None
        if d is not None:
            out[layer] = d
    return out


def texture_alpha_flag(header, order="<"):
    """The alpha byte of a Texture header's layer 0 (`u8 hasAlpha` of the image
    descriptor, docs/KAPOW_NAZ_FORMAT.md section 4.2) -> bool, or None when the
    header has no image record.  The engine copies it to bit 0 of the texture
    buffer's flags (0x429e77) and the material setup enables the alpha test from
    that bit of the layer-0 texture (0x571d5d): the pixels are not inspected.
    PC: parse_texture_frames; otherwise the byte at +25 of the 30-byte window
    parse_texture_header uses (the same on X360: equal to the PC byte on all 908
    textures the two Part 2 builds share)."""
    try:
        if order == "<":
            ex = parse_texture_frames(header)
            if ex and ex["frames"] and ex["frames"][0]["slots"][0]:
                return bool(ex["frames"][0]["slots"][0]["alpha"])
        info = parse_texture_header(header, order)
        if not info or not info["images"]:
            return None
        return bool(header[info["images"][0]["rec_off"] + 25] & 1)
    except Exception:
        return None


def _write_sheet_json(header, out_dir, order="<"):
    """sheet.json next to the layer PNGs.  Top level: the FIRST sheet's material
    switches for the GLB writers (two-sided, blend, alpha threshold, normal-map
    power) and its layer `overrides`; "sheets": every sheet of the texture with
    all its properties (texture_sheets)."""
    try:
        sh = texture_sheet(header, order)
        if sh:
            import json as _json

            full = texture_sheets(header, order)
            flag = texture_alpha_flag(header, order)
            if flag is not None:  # not a sheet property: the header's alpha byte of layer 0
                sh = dict(sh, textureHasAlpha=flag)
            ex = parse_texture_frames(header, order)
            if ex:  # facts of the header itself, beside the sheet values
                slots0 = ex["frames"][0]["slots"]
                if slots0[0] and slots0[0]["type"] == 2:
                    sh = dict(sh, cubeFaceOrder=list(CUBE_FACE_ORDER))
                if ex.get("anim_tail"):
                    ms = texture_frame_ms(ex["anim_tail"], len(ex["frames"]))
                    sh = dict(sh, animation=ex["anim_tail"])
                    if any(m is not None for m in ms):
                        sh["frame_ms"] = ms
            if full:
                sh = dict(sh)
                if full[0]["overrides"]:
                    sh["overrides"] = full[0]["overrides"]
                if len(full) > 1 or "name" in full[0]:
                    sh["sheets"] = full
            with open(out_dir / "sheet.json", "w", encoding="utf-8", newline="\n") as _f:
                _f.write(_json.dumps(sh, sort_keys=True))
    except Exception as e:  # the texture is still written; its materials lose the sheet
        _sheet_warning(out_dir, "sheet.json not written", e)


def _sheet_warning(out_dir, what, e):
    """One WARNING line for a sheet.json that could not be written or updated."""
    print(
        "      WARNING: texture %s: %s (%s: %s)"
        % (getattr(out_dir, "name", out_dir), what, type(e).__name__, e)
    )


def read_sheet_json(tex_dir):
    """sheet.json of an extracted texture directory -> dict ({} if absent)."""
    try:
        import json as _json

        with open(os.path.join(str(tex_dir), "sheet.json"), encoding="utf-8") as _f:
            d = _json.load(_f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def extract_specular(header, order="<"):
    """Return (exponent, intensity) from the FIRST material block in a Texture
    header -- the engine's $specularData.xy. exponent drives the specular power,
    intensity scales the specular highlight (0 -> matte). Ground-truthed against an
    apitrace capture (nightowlbelt 20/0.58, RorschachButton 27.6/0.52).
    order '<' PC / '>' console (the 64-bit name hash + float are byte-order-flipped
    on the big-endian consoles)."""
    exp = inten = None
    n = len(header)
    for o in range(0, n - 20):
        hlo, hhi = struct.unpack_from(order + "II", header, o + 4)
        if hhi == _SPEC_HI:
            if hlo == _SPEC_EXP and exp is None:
                exp = struct.unpack_from(order + "f", header, o + 16)[0]
            elif hlo == _SPEC_INT and inten is None:
                inten = struct.unpack_from(order + "f", header, o + 16)[0]
            if exp is not None and inten is not None:
                break
    if exp is None and inten is None:
        # older record layout (no type hash to match): the first sheet's records
        # of the same two properties (specularSize 0xF4142D28, specularPower 0xB3AB3306)
        for sh in _untyped_sheets(header, order):
            if "renderType" in sh:
                return sh.get("specularSize"), sh.get("specularPower")
    return exp, inten


# ---------------------------------------------------------------------------
# Texture .header parser  (DETERMINISTIC — cracked 2026-06-24 from the bordello
# block; replaces the old offset-scan in naz_textures.identify_from_header).
#
# Layout of a "Texture" asset header (the block_h_z blob), all little-endian:
#   +0    u32  typeNameLen           (8 = "Texture\0")
#   +4    char[typeNameLen] typeName ("Texture\0")
#   +12   u32  classId/version       (always 0x2D = 45 on WM07)
#   +16   9 x 20-byte PROPERTY records (the generic property bag):
#              [salt u32][nameHashLo u32][nameHashHi u32][typeTag u32][value u32]
#         `salt` is a per-asset constant repeated on every record (it is the
#         alignment oracle that proved the record size). 9 records => 180 bytes,
#         so the image-descriptor array begins at a FIXED offset 16+180 = 196.
#   +196  IMAGE-DESCRIPTOR ARRAY: one 30-byte record per stored sub-image
#         (a material packs several: diffuse + normal + specular, sometimes 4):
#              +0  u32  flags (1 on image[0], 0 after)
#              +4  u32  authoredWidth  * 256   (low byte = flags; use >>8)
#              +8  u32  authoredHeight * 256   (   "    "    "   ; use >>8)
#              +13 u8   FORMAT ENUM   (5=DXT1 6=DXT3 7=DXT5 9=ATI2/BC5 0-4=linear)
#              +20 u32  256           (clamp constant)
#              +26 u8   authored mip count = log2(max(authoredW,authoredH))+1
#         The array ends when +13 is not a valid enum or +26 not in 1..13; what
#         follows is a length-prefixed source path "/data/.../<name>.bmp".
#
# VERIFIED: image count matches reality (sky=1, walls/props=3 diffuse+normal+spec,
# sculptures=4); authored dims match the GPU (FemaleSkinBody 512x1024 authored ->
# 256x512 stored after 1 mip-drop = the byte-exact GPU copy). Format & name are
# 100% exact. See WATCHMEN_EXTRACTION_MASTER.md §6.
# ---------------------------------------------------------------------------
TEX_ENUMS = {0, 1, 2, 3, 4, 5, 6, 7, 9, 10}
TEX_FMT = {  # enum -> (D3D name, ('blk',bytes/block) | ('lin',bpp))
    0: ("X8R8G8B8", ("lin", 4)),
    1: ("A8R8G8B8", ("lin", 4)),
    2: ("A8R8G8B8", ("lin", 4)),
    3: ("L8", ("lin", 1)),
    4: ("L8", ("lin", 1)),
    5: ("DXT1", ("blk", 8)),
    6: ("DXT3", ("blk", 16)),
    7: ("DXT5", ("blk", 16)),
    # enum 8 = X360 only (not in TEX_ENUMS, so no PC path accepts it): the engine's
    # format table 0x830892d8 maps id 8 to D3DFORMAT 0x1a20017a = DXT3A, one 4-bit
    # channel in 8-byte blocks.  It is the X360 encoding of the slot-4 L8 map, the
    # HEIGHT map (PC enum 3 in the same slot on all 10 + 23 textures that have one).
    8: ("DXT3A", ("blk", 8)),
    9: ("ATI2", ("blk", 16)),
    # enum 10 = X360's normal-map format: the SAME 2-channel BC5/ATI2 the PC
    # stores under enum 9 (verified 2026-07-14: PC-9 -> X360-10 -> PS3-7 across
    # 20 shared textures; BC5 decode of the X360 layer -> clean purple normal
    # coherence 1.3, vs 18.8 as DXT5). PS3 re-encodes the same normal as DXT5(7).
    10: ("ATI2", ("blk", 16)),
}


def _is_texture(hdr, order="<"):
    return asset_base_class(asset_class(hdr, order)) == "Texture"


#: per-frame layer slots (FUN_005382aa reads slot 0, then 7 x [present][desc]).
TEXTURE_SLOTS = 8
#: file slot -> layer label (read from code: the loader 0x5382aa stores file slot i
#: at frame +4*i; the sheet asks by ENGINE layer through 0x49be2d / 0x4991f0, whose
#: override members are named by the Get...MapOverrideName getters 0x523d0e...).
#: Slots 5 and 6 occur in no shipped texture.
TEXTURE_SLOT_LABELS = {
    0: "diffuse",
    1: "normal",
    2: "specMap",
    3: "glow",
    4: "height",
    5: "fallOff",
    6: "ambOcc",
    7: "specSize",
}
#: engine layer -> file slot (accessors 0x49bcbe...0x49bdff): the renderer counts
#: layers, the file counts slots; layers 0 and 1 are both the diffuse slot
TEXTURE_LAYER_SLOTS = {0: 0, 1: 0, 2: 1, 3: 4, 4: 2, 5: 3, 6: 5, 7: 6, 8: 7}
#: file face k of a cube map = D3D cube face k (0x454384 / 0x454492, LockRect(face, level))
CUBE_FACE_ORDER = ("+X", "-X", "+Y", "-Y", "+Z", "-Z")


def _parse_texture_anim_tail(hdr, p, order="<"):
    """The animation block that follows the frames of a Texture header with
    hasAnim (readers 0x53345a, 0x530639, 0x529337) -> ({"serial", "cycle"}, end).

    Cycle = {"head": [u32 x3], "steps": [{"sub_cycle": bool, "index"}],
    "items": [{"frame_min", "frame_max", "time_min_ms", "time_max_ms", "id"}],
    "sub_cycles": [Cycle]}.  A step that is not a sub-cycle plays item `index`: a
    random frame in [frame_min, frame_max] for a random time in [time_min_ms,
    time_max_ms] ms (0x52929b, 0x5292bb).  The name `id` is inferred (the code
    only stores it).  Raises ValueError / struct.error when it does not read."""

    def u32():
        nonlocal p
        (v,) = struct.unpack_from(order + "I", hdr, p)
        p += 4
        return v

    def count(item):
        n = u32()
        if n * item > len(hdr) - p:
            raise ValueError("count %d" % n)
        return n

    def cycle(depth):
        if depth > 8:
            raise ValueError("cycle depth")
        c = {"head": [u32(), u32(), u32()]}
        c["steps"] = [{"sub_cycle": bool(u32()), "index": u32()} for _ in range(count(8))]
        c["items"] = [
            dict(zip(("frame_min", "frame_max", "time_min_ms", "time_max_ms", "id"), vals))
            for vals in ([u32() for _ in range(5)] for _ in range(count(20)))
        ]
        c["sub_cycles"] = [cycle(depth + 1) for _ in range(count(20))]
        return c

    serial = u32()
    return {"serial": serial, "cycle": cycle(0)}, p


def texture_frame_ms(anim_tail, frames):
    """Display time of each frame in ms, [int | None] * frames, from a
    parse_texture_frames "anim_tail": a frame gets a time only where an item of
    the top cycle shows exactly that frame (frame_min == frame_max) for a fixed
    time (time_min_ms == time_max_ms); None otherwise."""
    out = [None] * frames
    for it in ((anim_tail or {}).get("cycle") or {}).get("items") or []:
        if it["frame_min"] == it["frame_max"] and it["time_min_ms"] == it["time_max_ms"]:
            if it["frame_min"] < frames and out[it["frame_min"]] is None:
                out[it["frame_min"]] = it["time_min_ms"]
    return out


_TEX_DESC = 29  # FUN_00429e77: u32 w, h, format, usage, type; u8 alpha; u32 mips, size


def _chain_bytes_exact(en, w, h, mip):
    """Stored bytes of one mip chain.  Block formats as usual; LINEAR formats keep
    every row padded to 4 bytes (the locked D3D pitch), which only shows on the
    1- and 2-texel-wide L8 mips (validated: 936/936 Part 2 PC streams exact)."""
    k, unit = TEX_FMT[en][1]
    total = 0
    for i in range(mip):
        ww, hh = max(1, w >> i), max(1, h >> i)
        if k == "blk":
            total += max(1, (ww + 3) // 4) * max(1, (hh + 3) // 4) * unit
        else:
            total += ((ww * unit + 3) & ~3) * hh
    return total


def parse_texture_frames(hdr, order="<"):
    """ENGINE-EXACT Texture header (FUN_005382aa / FUN_00429e77), or None.
    order '<' PC / '>' X360 + PS3: the same fields, big-endian (all 937 + 1,190
    headers of each console set parse to the end of the source path).

    [bag][u32 nFrames][u8 hasAnim] then per frame: slot-0 descriptor, 7 x
    ([u8 present][descriptor if present]), [u32 len][source path]; with hasAnim
    the animation block follows (_parse_texture_anim_tail).  Returns
    {"frames": [{"slots": [desc|None]*8, "path": str}], "anim": bool, "anim_tail":
    {"serial", "cycle"} | None, "end": off (past the animation block when it read)};
    desc = {slot, enum, aw, ah, mip, type (1=2D, 2=cube), alpha, usage, drift, size}.
    `usage` is TextureBuffer +0x10 (0x456d46): 0 in block textures.
    `size` is the descriptor's last u32: 0 on PC and PS3; on X360 the STORED
    byte size of the layer (all mips; all six faces of a cube) -- the sizes of a
    header add up to the stream length on 937/937 and 1,190/1,190 textures."""
    if not _is_texture(hdr, order):
        return None
    enums = TEX_ENUMS if order == "<" else TEX_FMT
    try:
        (tlen,) = struct.unpack_from(order + "I", hdr, 0)
        (nd,) = struct.unpack_from(order + "I", hdr, 4 + tlen)
        p = 4 + tlen + 4 + 4 * nd  # FUN_00511f96: bag = nd dwords
        (nf,) = struct.unpack_from(order + "I", hdr, p)
        anim = hdr[p + 4]
        p += 5
        if not 1 <= nf <= 1024 or anim > 1:
            return None
        frames = []
        for _ in range(nf):
            slots = []
            for k in range(TEXTURE_SLOTS):
                if k:
                    present = hdr[p]
                    p += 1
                    if present > 1:
                        return None
                    if not present:
                        slots.append(None)
                        continue
                w, h, en, usage, typ, alpha, mip, size = struct.unpack_from(order + "5IBII", hdr, p)
                p += _TEX_DESC
                if en not in enums or typ not in (1, 2) or alpha > 1:
                    return None
                if not (0 < w <= 8192 and 0 < h <= 8192 and 1 <= mip <= 14):
                    return None
                slots.append(
                    {
                        "slot": k,
                        "enum": en,
                        "fmt": TEX_FMT[en][0],
                        "aw": w,
                        "ah": h,
                        "mip": mip,
                        "type": typ,
                        "alpha": bool(alpha),
                        "usage": usage,
                        # slot 7 is the record the stride walk used to reach through
                        # a 4-byte "drift" (four absent-slot bytes): the specSize map
                        "drift": k == 7,
                        "chain": _chain_bytes_exact(en, w, h, mip),
                        "size": size,
                    }
                )
            (sl,) = struct.unpack_from(order + "I", hdr, p)
            if sl > 1024 or p + 4 + sl > len(hdr):
                return None
            path = hdr[p + 4 : p + 4 + sl].split(b"\0", 1)[0].decode("latin1")
            p += 4 + sl
            frames.append({"slots": slots, "path": path})
    except (struct.error, IndexError):
        return None
    tail = None
    if anim:
        try:
            tail, p = _parse_texture_anim_tail(hdr, p, order)
        except (struct.error, ValueError, RecursionError):
            tail = None  # the frames stand; the block is reported as not read
    return {"frames": frames, "anim": bool(anim), "anim_tail": tail, "end": p}


def _exact_texture_plan(hdr, stream_len):
    """plan_texture_layers() answer straight from the exact header, or None when
    the header does not parse or does not tile the stream byte-for-byte."""
    ex = parse_texture_frames(hdr)
    if not ex:
        return None
    sets = [[d for d in fr["slots"] if d] for fr in ex["frames"]]
    L = sets[0]
    key = lambda ls: [(d["slot"], d["enum"], d["aw"], d["ah"], d["mip"], d["type"]) for d in ls]
    if any(key(x) != key(L) for x in sets[1:]):
        return None
    cube = any(d["type"] == 2 for d in L)
    if cube and (len(L) != 1 or len(sets) != 1):
        return None  # layer order inside a multi-layer cube was never observed
    S = sum(d["chain"] for d in L)
    count = 6 if cube else len(sets)
    if S * count != stream_len:
        return None
    kind = "cube" if cube else ("anim" if count > 1 else "single")
    return {"kind": kind, "layers": L, "count": count, "exact": True}


def parse_texture_header(hdr, order="<"):
    """Deterministically parse a Texture .header blob.

    Returns dict(typename, path, name, images=[{enum,fmt,kind,aw,ah,mip,rec_off}])
    or None if `hdr` is not a Texture header.  order '<' PC / '>' X360+PS3 (the
    console record packs the same fields at shifted offsets: dims u32be@+6/+10,
    enum byte @+16, mips u32be@+26; console enums reflect platform re-encodes,
    e.g. X360 stores L8 spec-size maps as DXT1). `path`/`name` come straight from the
    embedded source path (100% correct naming); each image's `enum`/`fmt` are the
    engine's authoritative format; `aw`/`ah` are authored dims, `mip` the authored
    mip count.  (Stored byte-resolution still comes from the stream length — this
    block stores reduced-LOD data; see MASTER §6.)
    """
    if not _is_texture(hdr, order):
        return None
    tlen = struct.unpack_from(order + "I", hdr, 0)[0]
    p = 4 + tlen + 4  # skip typeName + classId(0x2D)
    if p + 36 > len(hdr):
        return None
    p, prs = _prop_walk(hdr, order)
    rs = 30  # image records are 30 bytes on BOTH engines
    # (only the PROPERTY records differ: 16 vs 20)
    images = []
    rec = p
    while rec + 30 <= len(hdr):
        v = _valid_rec(hdr, rec, order=order)
        if v is None:
            break
        fmt, kind = TEX_FMT[v["enum"]]
        images.append(
            {
                "enum": v["enum"],
                "fmt": fmt,
                "kind": kind,
                "aw": v["aw"],
                "ah": v["ah"],
                "mip": v["mip"],
                "rec_off": rec,
            }
        )
        rec += rs
    # source path: first length-prefixed "/data"|"/art" run after the records
    path = ""
    for marker in (b"/data", b"/Data", b"/art", b"/Art"):
        j = hdr.find(marker, rec - 4 if rec > 4 else 0)
        if j >= 4:
            plen = struct.unpack_from(order + "I", hdr, j - 4)[0]
            if 0 < plen < 512 and j + plen <= len(hdr):
                path = hdr[j : j + plen].decode("ascii", "replace").rstrip("\x00")
                break
    name = path.replace("\\", "/").rstrip("/").split("/")[-1].rsplit(".", 1)[0] if path else ""
    return {"typename": "Texture", "recsize": rs, "path": path, "name": name, "images": images}


def _is_normal_layer(images, idx, order="<"):
    """Format-agnostic normal-map test. PC normals are ATI2 (enum 9). Consoles
    re-encode the SAME normal: X360 -> enum 10 (BC5), PS3 -> enum 7 (DXT5). On
    PS3 enum 7 is also the diffuse format, but enum 7 only ever appears as
    diffuse (idx 0) on PC, so a non-idx0 DXT5 layer on console is a normal
    (spec/glow are always DXT1/L8). Verified across 20 shared PC/console
    textures, 2026-07-14."""
    en = images[idx]["enum"]
    if en in (9, 10):
        return True
    if order == ">" and en == 7 and idx > 0:
        return True
    return False


def texture_layer_label(images, idx, order="<"):
    """Layer -> label (the name in the PNG file name and the key the material
    writers look layers up by).

    A layer that knows its FILE SLOT (parse_texture_frames descriptors: every
    header the exact parse reads, all platforms) is labelled by the slot,
    TEXTURE_SLOT_LABELS: 0 diffuse, 1 normal, 2 specMap, 3 glow, 4 height (the
    parallax map; L8, DXT3A on X360), 5 fallOff, 6 ambOcc, 7 specSize (the
    specular-power map; L8, DXT1 on X360).

    Without a slot (the stride walk and the drift rescue, which see formats
    only) the older format rule applies: idx0 => diffuse; normal by format; a
    `drift` record or L8 => specSize; the FIRST colour layer after the normal =>
    specMap; a further colour layer => glow.  That rule cannot tell a slot-4
    height map from a slot-7 specSize map, nor a glow map without a specular map
    from a specular map."""
    if isinstance(images[idx], dict) and images[idx].get("slot") in TEXTURE_SLOT_LABELS:
        return TEXTURE_SLOT_LABELS[images[idx]["slot"]]
    if _is_normal_layer(images, idx, order):
        return "normal"
    if idx == 0:
        return "diffuse"
    if isinstance(images[idx], dict) and images[idx].get("drift"):
        return "specSize"  # drifted record = specSize slot (any codec)
    if images[idx]["enum"] in (3, 4, 8):  # L8 (X360: DXT3A) -> specular size / power
        return "specSize"
    # A colour layer at idx>0: the FIRST colour layer after the diffuse (layer 0)
    # is the specMap; any further colour layer is glow. Normal layers are skipped.
    prior_colors = sum(
        1
        for k in range(1, idx)
        if not _is_normal_layer(images, k, order) and images[k]["enum"] in (0, 1, 2, 5, 6, 7)
    )
    return "specMap" if prior_colors == 0 else "glow"


# ---------------------------------------------------------------------------
# DETERMINISTIC texture layer planner (cracked 2026-06-25).  Given a Texture
# header and the (now byte-exact) bound stream length, return the exact layer
# layout that tiles the stream: a single multi-layer set, a 6-face cubemap, or
# an N-frame animation/array.  Resolves 1190/1190 level-block textures.
#
# Why this is needed: the header is a SEQUENTIAL serialized stream (texture.cpp
# FUN_005382aa reads field-by-field via typed-read vtables), so a fixed 30-byte
# descriptor stride slips on trailing layers. We read what we can at stride 30
# (+4-gap fallback), then use the exact stream length as an oracle to (a) detect
# cube (6x) / animation (Nx) multiples and (b) recover a dropped trailing layer
# by scanning the header for the missing descriptor record.
# ---------------------------------------------------------------------------
def _chain_bytes(en, w, h, mip):
    """Sum of `mip` mip-level byte sizes from authored base dims, per format."""
    _, kind = TEX_FMT[en]
    k, unit = kind
    total = 0
    for _ in range(mip):
        if k == "blk":
            total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * unit
        else:
            total += max(1, w) * max(1, h) * unit
        if w == 1 and h == 1:
            break
        w = max(1, w >> 1)
        h = max(1, h >> 1)
    return total


def _tex_path_off(hdr):
    for m in (b"/data", b"/Data", b"/art", b"/Art", b"/levels", b"/Levels"):
        j = hdr.find(m)
        if j >= 4:
            return j - 4
    return len(hdr)


def _valid_rec(hdr, r, powtwo=False, order="<"):
    if r + 30 > len(hdr):
        return None
    if order == ">":
        en = hdr[r + 16]
        mip = struct.unpack_from(">I", hdr, r + 26)[0]
        f4, f8 = struct.unpack_from(">II", hdr, r + 6)
    else:
        en = hdr[r + 13]
        mip = hdr[r + 26]
        f4, f8 = struct.unpack_from("<II", hdr, r + 4)
    if en not in TEX_ENUMS or not (1 <= mip <= 13):
        return None
    aw, ah = f4 >> 8, f8 >> 8
    if not (0 < aw <= 8192 and 0 < ah <= 8192):
        return None
    if powtwo and not ((aw & (aw - 1)) == 0 and (ah & (ah - 1)) == 0):
        return None
    return {"enum": en, "mip": mip, "aw": aw, "ah": ah}


def _stride_layers(hdr, order="<"):
    info = parse_texture_header(hdr, order)
    if not info or not info["images"]:
        return [], 0, 0, 30
    rs = info.get("recsize", 30)
    r0 = info["images"][0]["rec_off"]
    end = _tex_path_off(hdr)
    out = []
    r = r0
    last = r0
    while r + 27 <= end:
        v = _valid_rec(hdr, r, order=order)
        if v:
            v["drift"] = False
            out.append(v)
            last = r
            r += rs
            continue
        v = _valid_rec(hdr, r + 4, order=order)  # 4-byte gap = the specSize slot marker
        if v:
            v["drift"] = True
            out.append(v)
            last = r + 4
            r += rs + 4
            continue
        break
    return out, last, end, rs


def plan_texture_layers(hdr, stream_len):
    """Return dict(kind, layers, count) where kind in
    {'single','cube','anim','fail'} and Sum(layer chains) * count == stream_len.
      single: one material, layers = [diffuse, normal, spec, ...]
      cube  : count == 6, layers describe ONE face
      anim  : count == N frames, layers describe ONE frame (a full material set)
    """
    ex = _exact_texture_plan(hdr, stream_len)
    if ex:
        return ex
    L, last, end, rs = _stride_layers(hdr)
    if not L:
        return {"kind": "fail", "layers": [], "count": 0}

    def total(layers):
        return sum(_chain_bytes(x["enum"], x["aw"], x["ah"], x["mip"]) for x in layers)

    S = total(L)
    if S <= 0:
        return {"kind": "fail", "layers": L, "count": 0}
    if abs(S - stream_len) <= 64:
        return {"kind": "single", "layers": L, "count": 1}
    if abs(S * 6 - stream_len) <= 400:
        return {"kind": "cube", "layers": L, "count": 6}
    # EXACT frame-multiple animation first (validated on the Part 2 level
    # blocks); inexact multiples wait until after the dropped-layer recovery --
    # Part 1 drift can make a loose multiple "fit" a stream that is really
    # layers (Caustics01_002: 60*184 ~ 11120 which is truly 16x16 + 128x128).
    n = round(stream_len / S)
    if 2 <= n <= 64 and S * n == stream_len:
        return {"kind": "anim", "layers": L, "count": n}
    # recover a dropped trailing layer using the stream length as the oracle
    if S < stream_len - 64:
        pos = last + rs
        acc = []
        add = 0
        need = stream_len - S
        while pos + 30 <= end and add < need - 64:
            v = _valid_rec(hdr, pos, powtwo=True)
            if v:
                c = _chain_bytes(v["enum"], v["aw"], v["ah"], v["mip"])
                if add + c <= need + 64:
                    acc.append(v)
                    add += c
                    pos += rs
                    continue
            pos += 1
        if acc and abs(S + add - stream_len) <= 64:
            return {"kind": "single", "layers": L + acc, "count": 1}
        if acc:
            # repaired set as an EXACT frame multiple (Caustics01_001: 32 x
            # [16x16 + drifted 128x128] = 355840)
            S2 = S + add
            n2 = round(stream_len / S2) if S2 else 0
            if 2 <= n2 <= 64 and n2 * S2 == stream_len:
                return {"kind": "anim", "layers": L + acc, "count": n2}
    if 2 <= n <= 64 and abs(S * n - stream_len) <= max(256, n * 8):
        return {"kind": "anim", "layers": L, "count": n}  # each frame = full set L (loose)
    en0 = L[0]
    S1 = _chain_bytes(en0["enum"], en0["aw"], en0["ah"], en0["mip"])
    n1 = round(stream_len / S1)
    if 2 <= n1 <= 64 and S1 >= 256 and abs(S1 * n1 - stream_len) <= max(256, n1 * 8):
        return {"kind": "anim", "layers": [en0], "count": n1}
    return {"kind": "fail", "layers": L, "count": 0}


def extract_block(h_data, s_data, language=0, report=None, stream_files=None):
    """Yield (entry, header, stream) for every asset.

    `stream_files`: callable(stream set file path) -> bytes or None (see
    stream_file_lookup).  With it, an entry that has no stream record of its own
    takes its stream from the block's stream sets (parse_block_trailer; the
    worker 0x4e0e5d seeks offset[language] in the set's file and reads
    size[language] through the same inflate): `entry.stream_file` then names
    that file.  A set entry whose file is missing or too short leaves the
    stream None, says why in `entry.stream_note` and through `report`.

    Blobs are inflated by asset type (asset_compressed), not by sniffing; one
    that should inflate and does not is yielded as stored, named in the entry's
    `inflate_failed` list and reported through `report` (a callable taking one
    string).

    Engine layout (FUN_004a3525): the header blobs follow the directory in record
    order; each record's stream pair is the tail of ITS OWN record.  After the
    `num_entries` main records the loader seeks to `language_header_offset
    [language]` and reads the `num_localized` per-language blobs from there
    (0x4a3938).  `language` picks the slot (0..5) for sizes, offsets and that seek.
    """
    entries, data_start = parse_block_toc(h_data, language=language)
    bo = BLOCK_ORDER
    num = struct.unpack_from(bo + "I", h_data, NUM_TABLES_OFFSET)[0]
    lang_off = struct.unpack_from(bo + "6I", h_data, 364)
    cur = data_start
    set_entries = {}  # (type hash, lower name) -> [(stream file, [(offset, size) x 6])]
    if stream_files is not None:
        sets, err = block_stream_sets(h_data, bo)
        if err and report is not None:
            report("stream sets of the block not readable (%s)" % err)
        for st in sets:
            for se in st["entries"]:
                set_entries.setdefault((se["type_hash"], se["name"].lower()), []).append(
                    (st["stream_file"], se["streams"])
                )
    for i, e in enumerate(entries):
        if i == num and 0 <= language < BLOCK_LANGUAGES and lang_off[language]:
            cur = lang_off[language]
        dsz = e.data_size

        def failed(what, e=e):
            def _f(msg):
                e.inflate_failed.append(what)
                if report is not None:
                    report("%s: %s does not inflate (%s)" % (e.name, what, msg))

            return _f

        header = _maybe_inflate(h_data[cur : cur + dsz], e.type_name, failed("header"))
        cur += dsz
        stream = None
        if e.has_stream and s_data is not None and e.best_stream:
            off, sz = e.best_stream
            if 0 <= off and off + sz <= len(s_data):
                stream = _maybe_inflate(s_data[off : off + sz], e.type_name, failed("stream"))
        if stream is None and not e.has_stream:
            for sfile, pairs in set_entries.get((e.type_hash, e.name.lower()), ()):
                off, sz = pairs[language] if pairs[language][1] > 0 else pairs[0]
                blob = stream_files(sfile)
                if blob is None:
                    e.stream_note = "stream file %s not found" % sfile
                elif sz <= 0 or off + sz > len(blob):
                    e.stream_note = "stream %d+%d runs past %s (%d bytes)" % (
                        off,
                        sz,
                        sfile,
                        len(blob),
                    )
                else:
                    stream = _maybe_inflate(blob[off : off + sz], e.type_name, failed("stream"))
                    e.stream_file, e.stream_note = sfile, None
                    break
            if e.stream_note and report is not None:
                report("%s: no stream (%s)" % (e.name, e.stream_note))
        yield e, header, stream


#: first u32 of a standalone `_h_z` file (platform byte order), measured on the 36
#: standalone header files of the six sets: {extension: {value: build}}.  The value
#: carries the type's version plus a build constant: 0x80000 in the newer build
#: (Part 2 on every platform, PS3 Part 1), 0x70000 in the stand-alone Part 1 build
#: (PC, Xbox 360) -- seen directly on .pivotbook (version 2), and as the 0x10000
#: difference of the two .texture values.
STANDALONE_SIGNATURES = {
    ".modelres": {0xEFD1E8BB: "part2", 0x520D5FD8: "part1"},
    ".texture": {0x9DDD1B02: "part2", 0x9DDC1B02: "part1"},
    ".pivotbook": {0x00080002: "part2", 0x00070002: "part1"},
}


def standalone_preamble(raw, order=None):
    """The 8 bytes before the zlib stream of a standalone `_h_z` file ->
    {"version_signature", "second_word", "order", "build"} or None when the file
    has no preamble (`_s_z` files: zlib starts at offset 0).

    Layout [u32 version signature][u32 second word][zlib], platform byte order.
    order None: the order in which the first word is a STANDALONE_SIGNATURES
    value ("build" then says which build; None for an unknown value, read
    little-endian).  The second word differs per file and per platform; that it
    is the source CRC is read from code elsewhere and was not checked on files."""
    if len(raw) < 10 or raw[0:1] == b"\x78" or raw[8:9] != b"\x78":
        return None
    known = {v: b for tab in STANDALONE_SIGNATURES.values() for v, b in tab.items()}
    orders = (order,) if order else ("<", ">")
    for o in orders:
        sig, second = struct.unpack_from(o + "II", raw, 0)
        if sig in known or order:
            return {
                "version_signature": sig,
                "second_word": second,
                "order": o,
                "build": known.get(sig),
            }
    sig, second = struct.unpack_from("<II", raw, 0)
    return {"version_signature": sig, "second_word": second, "order": "<", "build": None}


def inflate_standalone(raw):
    """Standalone _h_z/_s_z = 8-byte preamble + zlib (sometimes raw zlib).  The
    preamble of an `_h_z` file is read by standalone_preamble(); `_s_z` files
    have none."""
    for start in (8, 0, 4, 12, 16):
        if raw[start : start + 1] == b"\x78":
            try:
                return zlib.decompress(raw[start:])
            except zlib.error:
                pass
    return _maybe_inflate(raw)


# ===========================================================================
# (3) Texture decoding  (needs numpy + Pillow)
# ===========================================================================
DDS_MAGIC = 0x20534444
FOURCC = {"DXT1": b"DXT1", "DXT5": b"DXT5", "BC5": b"ATI2"}


def mip_chain_size(w, h, bb):
    total = mips = 0
    while True:
        total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bb
        mips += 1
        if w == 1 and h == 1:
            break
        w = max(1, w >> 1)
        h = max(1, h >> 1)
    return total, mips


def base_mip_bytes(w, h, bb):
    return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * bb


def make_dds(w, h, mips, fmt):
    flags = 0x1007 | ((0x20000 | 0x80000) if mips > 1 else 0)
    bb = 8 if fmt == "DXT1" else 16
    caps1 = 0x1000 | ((0x400000 | 0x8) if mips > 1 else 0)
    pf = struct.pack("<8I", 32, 4, struct.unpack("<I", FOURCC[fmt])[0], 0, 0, 0, 0, 0)
    hdr = (
        struct.pack("<7I", 124, flags, h, w, base_mip_bytes(w, h, bb), 0, max(1, mips))
        + b"\x00" * 44
        + pf
    )
    hdr += struct.pack("<5I", caps1, 0, 0, 0, 0)
    return struct.pack("<I", DDS_MAGIC) + hdr


def decode_dxt_base(data, w, h, fmt):
    bb = 8 if fmt == "DXT1" else 16
    base = base_mip_bytes(w, h, bb)
    if w % 4 or h % 4 or len(data) < base:
        return None
    try:
        im = Image.open(io.BytesIO(make_dds(w, h, 1, fmt) + data[:base]))
        im.load()
        return np.array(im.convert("RGBA"))
    except Exception:
        return None


def _bc4_channel(blocks8, w, h):
    n = blocks8.shape[0]
    e0 = blocks8[:, 0].astype(np.int32)
    e1 = blocks8[:, 1].astype(np.int32)
    pal = np.zeros((n, 8), np.float32)
    pal[:, 0] = e0
    pal[:, 1] = e1
    gt = e0 > e1
    for i in range(1, 7):
        pal[:, i + 1] = np.where(gt, ((7 - i) * e0 + i * e1) / 7.0, pal[:, i + 1])
    for i in range(1, 5):
        pal[:, i + 1] = np.where(~gt, ((5 - i) * e0 + i * e1) / 5.0, pal[:, i + 1])
    pal[:, 6] = np.where(~gt, 0.0, pal[:, 6])
    pal[:, 7] = np.where(~gt, 255.0, pal[:, 7])
    bits = np.zeros(n, np.uint64)
    for k in range(6):
        bits |= blocks8[:, 2 + k].astype(np.uint64) << np.uint64(8 * k)
    idx = np.zeros((n, 16), np.intp)
    for j in range(16):
        idx[:, j] = ((bits >> np.uint64(3 * j)) & np.uint64(7)).astype(np.intp)
    vals = np.take_along_axis(pal, idx, axis=1)
    bw, bh = w // 4, h // 4
    return np.clip(vals.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(h, w), 0, 255).astype(
        np.uint8
    )


def decode_bc5_base(data, w, h):
    base = base_mip_bytes(w, h, 16)
    if len(data) < base or w % 4 or h % 4:
        return None
    blk = np.frombuffer(data[:base], np.uint8).reshape(-1, 16)
    return _bc4_channel(blk[:, 0:8], w, h), _bc4_channel(blk[:, 8:16], w, h)


def ati2_xy(blocks):
    """(first, second) 8-byte-block channels of a PC `ATI2` layer -> (X, Y).

    Direct3D 9's ATI2 keeps the Y (green) block first and the X (red) block
    second; the game's pixel shaders multiply sampler .x with the tangent and .y
    with the bitangent (DeferredMain2PS: `mad r1.xyz, r0.x, v4, r1`).  Measured on
    the extracted maps: with the blocks in file order the mixed partials do not
    match (d(first)/dv vs d(second)/du correlate 0.17), swapped they do (0.57);
    the X360 (enum 10) and PS3 (DXT5) copies of the same maps already come out
    X-first (0.78).  Y points along +v (the stored bitangent is +dP/dv)."""
    return blocks[1], blocks[0]


def normal_to_png(X, Y, path):
    Xf = X.astype(np.float32) / 255 * 2 - 1
    Yf = Y.astype(np.float32) / 255 * 2 - 1
    Z = np.sqrt(np.clip(1 - Xf * Xf - Yf * Yf, 0, 1))
    B = ((Z * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8)
    Image.fromarray(np.stack([X, Y, B], -1)).save(path)


def _coherence(a):
    if a is None:
        return 1e9
    g = a.astype(np.int32).mean(2) if a.ndim == 3 else a.astype(np.int32)
    return float((np.abs(np.diff(g, axis=1)).mean() + np.abs(np.diff(g, axis=0)).mean()) / 2)


def header_dims(header):
    pows = set()
    for off in range(0, max(0, len(header) - 3)):
        v = struct.unpack_from("<I", header, off)[0]
        if 32 <= v <= 4096 and (v & (v - 1)) == 0:
            pows.add(v)
    pows = sorted(pows, reverse=True)
    dims = [(a, a) for a in pows]
    for a in pows:
        for b in pows:
            if a != b and a // 2 <= b <= a * 2:
                dims.append((a, b))
    seen, out = set(), []
    for d in dims:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out or [(512, 512), (256, 256), (1024, 1024)]


def _looks_like_normal(XY):
    if XY is None:
        return False
    X, Y = XY
    if not (112 <= X.mean() <= 144 and 112 <= Y.mean() <= 144):
        return False
    return _coherence(X) < 16 and _coherence(Y) < 16


def _unpad_linear(buf, en, w, h):
    """Top mip of a LINEAR layer without the 4-byte row padding (no-op unless the
    row size is not a multiple of 4, i.e. L8 narrower than 4 texels)."""
    k, unit = TEX_FMT[en][1]
    row = w * unit
    if k == "blk" or row % 4 == 0:
        return buf
    pitch = (row + 3) & ~3
    return b"".join(buf[y * pitch : y * pitch + row] for y in range(h))


def _decode_one_layer(buf, en, w, h, normal=False):
    """Decode a single layer's TOP mip to an RGB array (or grayscale for L8).
    normal=True: layer is a normal map -- reconstruct a proper tangent-space
    RGB normal. For PS3's DXT5-packed normals the vector is stored X->alpha,
    Y->green (the classic DXT5nm layout; R/B are constant filler), so we rebuild
    (X, Y, Z=sqrt(1-X^2-Y^2)); ATI2/BC5 already carries X,Y in two channels."""
    name = TEX_FMT[en][0]
    if normal and name in ("DXT5", "DXT3"):
        rgba = decode_dxt_base(buf, w, h, "DXT5")
        if rgba is None:
            return None
        X = rgba[:, :, 3].astype(np.float32)
        Y = rgba[:, :, 1].astype(np.float32)  # A, G
        Xf = X / 255 * 2 - 1
        Yf = Y / 255 * 2 - 1
        Z = (np.sqrt(np.clip(1 - Xf * Xf - Yf * Yf, 0, 1)) * 0.5 + 0.5) * 255
        return np.stack(
            [X.astype(np.uint8), Y.astype(np.uint8), Z.clip(0, 255).astype(np.uint8)], -1
        )
    if name in ("DXT1", "DXT5"):
        return decode_dxt_base(buf, w, h, name)
    if name == "DXT3":
        return decode_dxt_base(buf, w, h, "DXT5")  # close enough for preview
    if name == "ATI2":  # BC5 normal map
        xy = decode_bc5_base(buf, w, h)
        if not xy:
            return None
        if en == 9:  # PC ATI2 stores the Y block first (see ati2_xy)
            xy = ati2_xy(xy)
        Xf = xy[0].astype(np.float32) / 255 * 2 - 1
        Yf = xy[1].astype(np.float32) / 255 * 2 - 1
        Z = (np.sqrt(np.clip(1 - Xf * Xf - Yf * Yf, 0, 1)) * 0.5 + 0.5) * 255
        return np.stack([xy[0], xy[1], Z.clip(0, 255).astype(np.uint8)], -1)
    if name in ("X8R8G8B8", "A8R8G8B8"):
        need = w * h * 4
        if len(buf) < need:
            return None
        a = np.frombuffer(buf[:need], np.uint8).reshape(h, w, 4)
        return (
            a[:, :, 2::-1].copy() if name == "X8R8G8B8" else a[:, :, [2, 1, 0, 3]].copy()
        )  # X8->RGB, A8->RGBA
    if name == "L8":
        need = w * h
        if len(buf) < need:
            return None
        return np.frombuffer(buf[:need], np.uint8).reshape(h, w)
    if name == "DXT3A":
        return _decode_dxt3a(buf, w, h)
    return None


def _decode_dxt3a(buf, w, h):
    """X360 DXT3A (the explicit-alpha half of a DXT3 block on its own): 8 bytes per
    4x4 block, one 4-bit value per texel, low nibble first, rows top to bottom.
    Returns a grayscale array like L8 (value * 17), or None."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    if len(buf) < bw * bh * 8:
        return None
    b = np.frombuffer(buf[: bw * bh * 8], np.uint8).reshape(bh, bw, 4, 2)
    t = np.stack([b[..., 0] & 15, b[..., 0] >> 4, b[..., 1] & 15, b[..., 1] >> 4], -1)
    img = t.reshape(bh, bw, 4, 4).transpose(0, 2, 1, 3).reshape(bh * 4, bw * 4)
    return (img[:h, :w] * 17).astype(np.uint8)


# ---------------------------------------------------------------------------
# Console texture streams (2026-07-13).
#   PS3 : per-layer [36-byte header][data]; data size = u32be @ hdr+8 (self-
#         describing; a layer may carry MORE mips than the PC plan, e.g. ATI2
#         stored with the full chain). Pixel data is byte-identical to PC.
#   X360: layers concatenated raw; every mip is TILED (XGAddress2DTiledOffset)
#         and the whole stream is 16-bit byte-swapped (GPU 8-in-16). Per-layer
#         size rule (validated on bordello, 230/272 exact vs PC plans + the
#         L8->DXT1 re-encode visible in the console header records): mips are
#         stored individually while min(w,h) >= 32 texels, each padded to
#         32x32 BLOCKS; all smaller mips share one packed 32x32-block tail.
# ---------------------------------------------------------------------------
def _bswap16(b):
    import array as _arr

    a = _arr.array("H")
    a.frombytes(b[: len(b) & ~1])
    a.byteswap()
    return a.tobytes() + b[len(b) & ~1 :]


def _xg2d(x, y, w, tp):
    """XGAddress2DTiledOffset (Xenos): element offset of (x,y) in a tiled
    surface of width w elements, tp = bytes per element."""
    alw = (w + 31) & ~31
    lb = (tp >> 2) + ((tp >> 1) >> (tp >> 2))
    macro = ((x >> 5) + (y >> 5) * (alw >> 5)) << (lb + 7)
    micro = ((x & 7) + ((y & 6) << 2)) << lb
    off = macro + ((micro & ~15) << 1) + (micro & 15) + ((y & 8) << (3 + lb)) + ((y & 1) << 4)
    return (
        ((off & ~511) << 3)
        + ((off & 448) << 2)
        + (off & 63)
        + ((y & 16) << 7)
        + (((((y & 8) >> 2) + (x >> 3)) & 3) << 6)
    ) >> lb


def _xg_untile(data, we, he, bpe, alw=None, yoff=0):
    """Linearize a tiled X360 surface: we x he elements of bpe bytes
    (alw = aligned surface width used for tiling, min 32).
    yoff shifts the source row read up by yoff element-rows -- used for the
    D3D9 packed-mip-tail case where a very short surface stores its base level
    BELOW the packed tail (see _thin_mip_yoff)."""
    alw = max(alw or we, 32)
    if we <= 0 or he <= 0:
        return b""
    import numpy as np

    # every element at once: _xg2d is integer arithmetic that works on numpy arrays
    y, x = np.mgrid[0:he, 0:we].astype(np.int64)
    s = _xg2d(x.ravel(), y.ravel() + yoff, alw, bpe) * bpe
    src = np.frombuffer(data, np.uint8)
    out = np.zeros((we * he, bpe), np.uint8)
    ok = s + bpe <= len(src)  # elements past the end of the data stay 0
    out[ok] = src[s[ok, None] + np.arange(bpe)]
    return out.tobytes()


def _x360_packed_offset(kind, unit, w, h, we, he):
    """Element (x,y) offset of the BASE level inside an X360 packed-mip tile.
    Levels whose pow2-padded TEXEL dims are both >= 32 are stored normally at
    (0,0). Smaller bases live in the shared packed tail; empirically (P1
    console audit 2026-07-16, brute-forced vs PC ground truth on all 55
    affected sub-32px textures, incl. 8x64 A8R8G8B8 / 64x16 DXT1 / 16x16 DXT1 /
    4x4 ATI2 classes): the base packs 16 TEXELS in from the tile edge along its
    short axis — x for taller-or-square, y for wider — i.e. 16//blk elements.
    4x4-texel single-block layers sit at special spots: element (1,0) for
    8-byte blocks (DXT1), (26,0) for 16-byte blocks (ATI2/DXT5).
    Generalizes the old _thin_mip_yoff hack (wide blk we>=32 & he<=4 -> y 4),
    which this reproduces."""
    pw = 1 << max(0, (max(w, 1) - 1).bit_length())
    ph = 1 << max(0, (max(h, 1) - 1).bit_length())
    if min(pw, ph) >= 32:
        return 0, 0, False
    blk = 4 if kind == "blk" else 1
    if kind == "blk" and we <= 1 and he <= 1:
        return (1 if unit == 8 else 26), 0, False
    if unit == 16 and kind == "blk":
        # ATI2 128-bit blocks pack differently (empirical, exact/noise-level vs
        # PC on all 8 known instances across P1+P2): full-tile-wide thin rows
        # sit at y=16 ELEMENTS; other non-square shapes additionally need the
        # two 8-byte BC4 half-blocks swapped. Square (4x4-block) and single-
        # block layers use the standard spots unswapped. DXT5 (also 16B)
        # follows the standard rule (verified exact on 4x8) — the swap flag is
        # consumed only for ATI2 by the caller.
        if we >= 32 and he <= 4:
            return 0, 16, False
        if pw > ph:
            return 0, 16 // blk, True
        if he > we:
            return 16 // blk, 0, True
        return 16 // blk, 0, False
    if pw > ph:
        return 0, 16 // blk, False
    return 16 // blk, 0, False


def _thin_mip_yoff(kind, we, he):
    """Row offset of the base mip inside a tiled X360 surface.
    Normally 0.  For a wide, VERY short block-compressed surface (spans >=1 full
    32-block macro-tile wide but <=4 blocks tall) the D3D9 packed mip tail is
    stored in the top rows and the base level sits BELOW it -- verified 0.00 vs
    PC on the only two such textures shipped (FloorCable_BlackPlastic 64x4 blk,
    HoneyPot_lightChain 32x1 blk), both offset by 4 rows.  Gated tightly so it
    can NEVER touch a normal texture (none other match we>=32 & he<=4)."""
    return 4 if (kind == "blk" and we >= 32 and he <= 4) else 0


def _x360_layer_bytes(en, w, h, mips):
    """Stored byte size of one X360 texture layer (see rule above). The packed
    tail is the current mip's block dims each aligned UP to 32 blocks (not a
    fixed 32x32) -- correct for wide/thin textures like 256x16 (64x4 blocks ->
    64x32 tail = 16384, vs the old fixed 8192 which mis-planned them as 2x anim).
    For square small mips (<=32 blocks) this stays 32x32, so no regression."""
    _, (kind, unit) = TEX_FMT[en]
    blk = 4 if kind == "blk" else 1
    total = 0
    lvl = 0
    tail = False
    while lvl < mips:
        if min(w, h) >= 32:
            wb = (max(1, (w + blk - 1) // blk) + 31) & ~31
            hb = (max(1, (h + blk - 1) // blk) + 31) & ~31
            total += wb * hb * unit
        else:
            tail = True
            break
        w = max(1, w >> 1)
        h = max(1, h >> 1)
        lvl += 1
    if tail or lvl < mips:
        wb = (max(1, (w + blk - 1) // blk) + 31) & ~31
        hb = (max(1, (h + blk - 1) // blk) + 31) & ~31
        total += wb * hb * unit
    return total


def _ps3_segments(stream):
    """Walk PS3 per-layer [36B header][data] segments; returns [(data_off, size)]
    or None if the stream doesn't parse as a PS3 texture stream."""
    segs = []
    p = 0
    while p + 36 <= len(stream):
        sz = struct.unpack_from(">I", stream, p + 8)[0]
        if not (16 <= sz <= len(stream) - p - 36):
            return segs if segs and p >= len(stream) - 64 else None
        segs.append((p + 36, sz))
        p += 36 + sz
    return segs if segs and p >= len(stream) - 64 else None


def _console_recover_layers(header, stream, L, last, end, rs):
    """Recover trailing texture layers the stride walk dropped (serializer
    drift), using the stream as the size oracle -- the console analogue of the
    PC dropped-layer recovery in plan_texture_layers. PS3: match each self-
    describing segment's full-chain byte size to a byte-scanned power-of-two
    record. X360: byte-scan records and accept only while the platform-padded
    sizes still tile the stream exactly. Returns the fuller layer list (>= L)."""
    segs = _ps3_segments(stream)
    # candidate records anywhere in the record area (byte-granular scan)
    cands = []
    pos = last + rs
    while pos + 30 <= end:
        v = _valid_rec(header, pos, powtwo=True, order=">")
        if v:
            cands.append(v)
            pos += rs
        else:
            pos += 1
    if not cands:
        return L
    if segs is not None:  # ---- PS3: segments are exact
        if len(segs) <= len(L):
            return L
        out = list(L)
        ci = 0
        for si in range(len(L), len(segs)):
            want = segs[si][1]
            pick = None
            for k in range(ci, len(cands)):
                v = cands[k]
                if abs(_chain_bytes(v["enum"], v["aw"], v["ah"], v["mip"]) - want) <= 64:
                    pick = v
                    ci = k + 1
                    break
            if pick is None:
                break
            out.append(pick)
        return out
    # ---- X360: accept recovered records only if total padded size == stream
    base = sum(_x360_layer_bytes(x["enum"], x["aw"], x["ah"], x["mip"]) for x in L)
    add = []
    acc = 0
    for v in cands:
        c = _x360_layer_bytes(v["enum"], v["aw"], v["ah"], v["mip"])
        if base + acc + c <= len(stream) + 64:
            add.append(v)
            acc += c
        if base + acc == len(stream):
            return L + add
    return L  # no exact fill -> stay conservative


def _rsx_unswizzle(buf, w, h, unit=1):
    """PS3/RSX Morton (Z-order) unswizzle for UNCOMPRESSED layers (L8 etc.).
    DXT layers are stored linearly on RSX; L8 is swizzled — verified byte-exact
    vs the PC linear L8 across all Part-2 specSize maps (2026-07-16).  For
    non-square pow2 textures the remaining high bits of the larger dimension
    ride linearly above the interleaved low bits (standard RSX layout).
    Returns the linear top mip (w*h*unit bytes); extra chain bytes ignored."""
    import numpy as np

    if w & (w - 1) or h & (h - 1) or w * h * unit > len(buf):
        return buf  # not unswizzlable -> leave as-is
    n = w * h
    idx = np.arange(n, dtype=np.uint64)
    xs = np.zeros(n, dtype=np.uint64)
    ys = np.zeros(n, dtype=np.uint64)
    bx = by = 0
    lw = w.bit_length() - 1
    lh = h.bit_length() - 1
    src = idx
    for b in range(lw + lh):
        if bx < lw and by < lh:  # interleave: x bit first (LSB)
            if (b & 1) == 0:
                xs |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(bx)
                bx += 1
            else:
                ys |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(by)
                by += 1
        elif bx < lw:  # leftover bits -> wider dim, linear
            xs |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(bx)
            bx += 1
        else:
            ys |= ((src >> np.uint64(b)) & np.uint64(1)) << np.uint64(by)
            by += 1
    a = np.frombuffer(buf[: n * unit], dtype=np.uint8)
    if unit == 1:
        out = np.empty(n, dtype=np.uint8)
        out[(ys * np.uint64(w) + xs).astype(np.int64)] = a
    else:
        a = a.reshape(n, unit)
        out = np.empty((n, unit), dtype=np.uint8)
        out[(ys * np.uint64(w) + xs).astype(np.int64)] = a
    return out.tobytes()


def _texel32_to_pc(data, src):
    """Reorder console 32bpp (A8R8G8B8/X8R8G8B8) texel bytes to the PC little-
    endian D3D layout (B,G,R,A) the shared decoder expects (2026-07-16, P1
    console audit — 6 lightprojector/lensflare maps per console were channel-
    scrambled).
      src='ps3'  : RSX stores big-endian A,R,G,B      -> reverse each texel.
      src='x360' : stream holds PLAIN BE A,R,G,B (NOT GPU 8-in-16 swapped);
                   the unconditional _bswap16 turns it into R,A,B,G -> [2,3,0,1].
    """
    import numpy as np

    n = len(data) & ~3
    a = np.frombuffer(data[:n], np.uint8).reshape(-1, 4)
    perm = [3, 2, 1, 0] if src == "ps3" else [2, 3, 0, 1]
    return a[:, perm].tobytes() + data[n:]


def _x360_level0_bytes(en, w, h):
    """Stored bytes of level 0 of an X360 layer: its block grid padded to 32 x 32
    elements (also the step from one cube face to the next inside a level)."""
    _, (kind, unit) = TEX_FMT[en]
    blk = 4 if kind == "blk" else 1
    we = max(1, (w + blk - 1) // blk)
    he = max(1, (h + blk - 1) // blk)
    return ((we + 31) & ~31) * ((he + 31) & ~31) * unit


def _x360_base_level(raw, en, w, h):
    """Top mip of one X360 layer (or cube face) as an image array, or None.  `raw`
    starts at the layer's level 0: 16-bit swap, untile, crop out of the packed
    tail when the layer is smaller than 32 texels."""
    _, (kind, unit) = TEX_FMT[en]
    blk = 4 if kind == "blk" else 1
    we = max(1, (w + blk - 1) // blk)
    he = max(1, (h + blk - 1) // blk)
    # width aligned UP to 32 like every consumer (_xg2d/_x360_layer_bytes);
    # max(we,32) under-sized the tile buffer for non-pow2 widths > 32
    # blocks, zero-filling the tail of the untiled layer (2026-08-17).
    need = ((we + 31) & ~31) * ((he + 31) & ~31) * unit
    buf = _bswap16(raw[:need])
    xo, yo, hswap = _x360_packed_offset(kind, unit, w, h, we, he)
    if (xo or yo) and (max(we + xo, 32) * max(he + yo, 32) * unit) <= len(buf):
        import numpy as _np  # packed-tail base: untile the

        tw = max(we + xo, 32)
        th = max(he + yo, 32)  # full tile, crop at (xo,yo)
        full = _xg_untile(buf, tw, th, unit, alw=tw)
        t = _np.frombuffer(full, _np.uint8).reshape(th, tw, unit)
        sub = t[yo : yo + he, xo : xo + we].reshape(-1, unit)
        if hswap and TEX_FMT[en][0] == "ATI2":  # BC4 half-block swap (see rule)
            sub = _np.concatenate([sub[:, 8:], sub[:, :8]], axis=1)
        lin = sub.tobytes()
    else:
        lin = _xg_untile(buf, we, he, unit, alw=we, yoff=_thin_mip_yoff(kind, we, he))
    if kind == "lin" and unit == 4:  # 32bpp: undo bswap16-scramble -> PC BGRA
        lin = _texel32_to_pc(lin, "x360")
    return _decode_one_layer(lin, en, w, h)


#: sheet.json key that lists what a texture carve could not decode (absent when
#: every layer the header describes was written).
TEXTURE_DECODE_KEY = "decodeWarnings"


def _mark_texture_decode(out_dir, notes):
    """Record `notes` (a list of strings) under TEXTURE_DECODE_KEY in the texture
    directory's sheet.json, creating the file when the texture has no sheet."""
    if not notes:
        return
    try:
        import json as _json

        js = read_sheet_json(out_dir)
        js[TEXTURE_DECODE_KEY] = list(notes)
        with open(out_dir / "sheet.json", "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_json.dumps(js, sort_keys=True))
    except Exception as e:
        _sheet_warning(out_dir, "decode notes not recorded in sheet.json", e)


def _mark_stored_name(out_dir, stored):
    """Record the archive's spelling of a texture that was written under its
    canonical name (--names canonical) as "stored_name" in the texture
    directory's sheet.json.  A texture without a sheet.json gets none (the
    folders of two archives must hold the same files): its stored name is in
    _canonical_names.json only.  Nothing is written when `stored` is empty."""
    if not stored or not (out_dir / "sheet.json").is_file():
        return
    try:
        import json as _json

        js = read_sheet_json(out_dir)
        js["stored_name"] = stored
        with open(out_dir / "sheet.json", "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_json.dumps(js, sort_keys=True))
    except Exception as e:
        _sheet_warning(out_dir, "stored_name not recorded in sheet.json", e)


def _console_prefix(frames, frame, faces, face):
    """File-name prefix of one console layer image, the PC carve's scheme:
    frameN_ for a frame of an animated texture, faceN_ for a cube face."""
    return ("frame%d_" % frame if frames > 1 else "") + ("face%d_" % face if faces > 1 else "")


def _save_layer_png(img, out_dir, prefix, j, label, lay):
    Image.fromarray(img).save(
        out_dir
        / (
            "%s%d_%s_%dx%d_%s.png"
            % (prefix, j, label, lay["aw"], lay["ah"], TEX_FMT[lay["enum"]][0])
        )
    )


def _carve_x360_exact(stream, ex, out_dir, warn):
    """X360 carve from the exact header: every descriptor carries its stored byte
    size (parse_texture_frames `size`), so layers, animation frames and cube
    faces are located without any search.  Returns (png count, images per frame
    set, frame count), or None when the sizes do not add up to the stream.

    A cube layer stores its mip LEVELS one after another, each level holding the
    six faces (so face k of level 0 starts k * _x360_level0_bytes in); read that
    way all six faces equal the PS3 copy pixel for pixel (310/310 cube maps)."""
    sets = [[d for d in fr["slots"] if d] for fr in ex["frames"]]
    descs = [d for L in sets for d in L]
    if not descs or any(d["size"] <= 0 for d in descs):
        return None
    if sum(d["size"] for d in descs) != len(stream):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    off = 0
    for f, L in enumerate(sets):
        for j, d in enumerate(L):
            en, w, h = d["enum"], d["aw"], d["ah"]
            faces = 6 if d["type"] == 2 else 1
            planned = _x360_layer_bytes(en, w, h, d["mip"]) * faces
            if d["size"] != planned:
                warn(
                    "layer %d (%s %dx%d, %d mips) stores %d bytes, the layout rule gives %d: "
                    "top mip decoded from the layer start, not checked"
                    % (j, TEX_FMT[en][0], w, h, d["mip"], d["size"], planned)
                )
            step = _x360_level0_bytes(en, w, h)
            if faces > 1 and (min(w, h) < 32 or step * faces > d["size"]):
                warn(
                    "layer %d is a cube map smaller than 32 texels: where faces 1-5 sit in "
                    "the packed tail is not established, only face 0 written" % j
                )
                faces_out = 1
            else:
                faces_out = faces
            lbl = texture_layer_label(L, j, ">")
            for k in range(faces_out):
                lo = off + k * step
                img = _x360_base_level(stream[lo : off + d["size"]], en, w, h)
                if img is None:
                    warn(
                        "layer %d (%s %dx%d) not decoded" % (j, TEX_FMT[en][0], w, h)
                        + (" (face %d)" % k if faces > 1 else "")
                        + (" (frame %d)" % f if len(sets) > 1 else "")
                    )
                    continue
                if lbl == "specSize" and img.ndim == 3:
                    # slot 7 is DXT1 here where PC and PS3 store L8: the red channel
                    # is that map (mean difference <= 8.4 on 88/88; green, blue and
                    # so the luma are not on TwilightLadyHair: 163 / 164 / 114)
                    img = img[:, :, 0].copy()
                _save_layer_png(img, out_dir, _console_prefix(len(sets), f, faces, k), j, lbl, d)
                wrote += 1
            off += d["size"]
    return wrote, len(sets[0]), len(sets)


def _ps3_layer_image(data, lay, normal):
    """One PS3 layer (or cube face) -> image array.  DXT data is linear;
    uncompressed layers are RSX-swizzled, 32-bit ones big-endian ARGB."""
    kind, unit = TEX_FMT[lay["enum"]][1]
    if kind != "blk":  # uncompressed (L8...) -> RSX swizzled
        data = _rsx_unswizzle(data, lay["aw"], lay["ah"], unit)
        if unit == 4:  # 32bpp: BE ARGB -> PC BGRA
            data = _texel32_to_pc(data, "ps3")
    return _decode_one_layer(data, lay["enum"], lay["aw"], lay["ah"], normal=normal)


def _carve_ps3_exact(stream, ex, segs, out_dir, warn):
    """PS3 carve from the exact header: one [36-byte RSX descriptor][data] segment
    per descriptor, in frame then slot order (937/937 and 1,190/1,190 textures).
    Returns (png count, images per frame set, frame count), or None when the
    segment count is not the descriptor count.

    A cube segment holds the six faces one after another, each a full mip chain
    (mip count = descriptor byte 13), every face but the last padded to 128
    bytes: face k starts k * align128(chain) in (310/310 segment sizes; all six
    faces equal the X360 copy pixel for pixel)."""
    sets = [[d for d in fr["slots"] if d] for fr in ex["frames"]]
    descs = [(f, j, L) for f, L in enumerate(sets) for j in range(len(L))]
    if not descs or len(descs) != len(segs):
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    for (f, j, L), (off, sz) in zip(descs, segs):
        d = L[j]
        en, w, h = d["enum"], d["aw"], d["ah"]
        faces = 6 if d["type"] == 2 else 1
        starts = [0]
        if faces > 1:
            chain = _chain_bytes(en, w, h, stream[off - 36 + 13])
            pad = (chain + 127) & ~127
            if TEX_FMT[en][1][0] == "blk" and 5 * pad + chain == sz:
                starts = [k * pad for k in range(6)]
            else:
                warn(
                    "layer %d is a cube map whose segment (%d bytes) is not six 128-byte "
                    "aligned mip chains of %d: only face 0 written" % (j, sz, chain)
                )
        normal = _is_normal_layer(L, j, ">")
        lbl = texture_layer_label(L, j, ">")
        for k, st in enumerate(starts):
            img = _ps3_layer_image(stream[off + st : off + sz], d, normal)
            if img is None:
                warn(
                    "layer %d (%s %dx%d) not decoded" % (j, TEX_FMT[en][0], w, h)
                    + (" (face %d)" % k if faces > 1 else "")
                    + (" (frame %d)" % f if len(sets) > 1 else "")
                )
                continue
            _save_layer_png(img, out_dir, _console_prefix(len(sets), f, faces, k), j, lbl, d)
            wrote += 1
    return wrote, len(sets[0]), len(sets)


def carve_texture_console(stream, header, out_dir, log=None):
    """Console (X360/PS3) texture carve: decode the TOP mip of every layer to
    PNG.  The layer plan comes from the exact header (parse_texture_frames, big-
    endian) -- on X360 with each layer's stored size, on PS3 with one stream
    segment per layer; file names follow the PC carve (faceN_ / frameN_).  A
    header or stream that does not fit falls back to the older stride walk; that,
    and every layer or face that could not be written, is logged as one
    "WARNING: texture <name>: ..." line and listed in sheet.json under
    TEXTURE_DECODE_KEY.  Returns #PNGs written > 0."""
    if not callable(log):
        log = lambda *a, **k: None
    info = parse_texture_header(header, ">")
    ex = parse_texture_frames(header, ">")
    if ex is None and (info is None or not info["images"]):
        return False
    name = (info["name"] if info else "") or out_dir.name
    notes = []

    def warn(msg):
        notes.append(msg)
        log("      WARNING: texture %s: %s" % (name, msg))

    segs = _ps3_segments(stream)
    if ex is None:
        warn("header does not parse as the exact Texture layout: layer plan from the stride walk")
    else:
        res = _carve_x360_exact(stream, ex, out_dir, warn)
        if res is not None:
            wrote, nl, nf = res
            _write_spec_txt(header, out_dir)
            _mark_texture_decode(out_dir, notes)
            log(
                "      %s: X360 layers=%d x%d (exact stream %d) -> %s/ (%d png)"
                % (name, nl, nf, len(stream), out_dir.name, wrote)
            )
            return wrote > 0
        if segs is not None:
            res = _carve_ps3_exact(stream, ex, segs, out_dir, warn)
            if res is not None:
                wrote, nl, nf = res
                _write_spec_txt(header, out_dir)
                _mark_texture_decode(out_dir, notes)
                log(
                    "      %s: PS3 %d segs -> %s/ (%d png)" % (name, len(segs), out_dir.name, wrote)
                )
                return wrote > 0
            warn(
                "%d stream segments for %d header layers: layer plan from the stride walk"
                % (len(segs), sum(1 for fr in ex["frames"] for d in fr["slots"] if d))
            )
        else:
            sizes = sum(d["size"] for fr in ex["frames"] for d in fr["slots"] if d)
            warn(
                "header layer sizes add up to %d, the stream is %d bytes: layer plan from "
                "the stride walk, layers may be missing" % (sizes, len(stream))
            )
    L, _last, _end, _rs = _stride_layers(header, ">")
    if not L:
        return False
    L = _console_recover_layers(header, stream, L, _last, _end, _rs)
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    if segs is not None:  # ---- PS3
        for j, (off, sz) in enumerate(segs):
            lay = L[j % len(L)]
            pre = "" if len(segs) == len(L) else "seg%d_" % (j // len(L))
            is_norm = _is_normal_layer(L, j % len(L), ">")
            img = _ps3_layer_image(stream[off : off + sz], lay, is_norm)
            if img is None:
                warn("segment %d not decoded" % j)
                continue
            lbl = texture_layer_label(L, j % len(L), ">")
            _save_layer_png(img, out_dir, pre, j % len(L), lbl, lay)
            wrote += 1
        _write_spec_txt(header, out_dir)
        _mark_texture_decode(out_dir, notes)
        log("      %s: PS3 %d segs -> %s/ (%d png)" % (name, len(segs), out_dir.name, wrote))
        return wrote > 0
    # ---- X360: byteswap + per-layer offset by size rule + untile the top mip
    sizes = [_x360_layer_bytes(x["enum"], x["aw"], x["ah"], x["mip"]) for x in L]
    total = sum(sizes)
    reps = 1
    if total != len(stream):
        n = round(len(stream) / total) if total else 0
        if n >= 2 and n * total == len(stream):
            reps = n  # cube faces / anim frames
    off = 0
    for r in range(reps):
        for j, lay in enumerate(L):
            if off + 256 > len(stream):
                break
            img = _x360_base_level(stream[off:], lay["enum"], lay["aw"], lay["ah"])
            if img is not None:
                pre = "" if reps == 1 else "seg%d_" % r
                _save_layer_png(img, out_dir, pre, j, texture_layer_label(L, j, ">"), lay)
                wrote += 1
            off += sizes[j]
    if total * reps != len(stream):
        warn(
            "stride-walk plan covers %d of %d stream bytes: layers may be missing or wrong"
            % (total * reps, len(stream))
        )
    _write_spec_txt(header, out_dir)
    _mark_texture_decode(out_dir, notes)
    log(
        "      %s: X360 layers=%d x%d (%s stream %d) -> %s/ (%d png)"
        % (
            name,
            len(L),
            reps,
            "exact" if total * reps == len(stream) else "approx",
            len(stream),
            out_dir.name,
            wrote,
        )
    )
    return wrote > 0


def _write_spec_txt(header, out_dir):
    """Console PBR specular params (exponent/intensity) -> spec.txt, matching
    the PC carve. The name-hash + float are byte-order-flipped, so read BE."""
    try:
        ex, it = extract_specular(header, ">")
        if ex is not None or it is not None:
            with open(out_dir / "spec.txt", "w", encoding="utf-8", newline="\n") as _f:
                _f.write("%s %s" % ("" if ex is None else repr(ex), "" if it is None else repr(it)))
    except Exception:
        pass
    _write_sheet_json(header, out_dir, ">")


def _rescue_texture_plan(hdr, stream, order="<"):
    """Last-resort planner for headers with serializer DRIFT (a record slips a
    byte, corrupting its mip/dim fields; seen on 1/1971 Part 1 textures).
    Strategy: (1) take the FORMAT/dim sequence from a full-offset scan of valid
    power-of-two records; (2) for candidate record subsequences (all, all-minus-
    one corrupt record, each single record), brute-force per-layer mip counts
    whose chain sizes tile the stream EXACTLY; (3) among exact solutions, pick
    the one whose decoded layers score best (lowest coherence = natural images).
    Returns [(enum, aw, ah, mip)] or None."""
    info = parse_texture_header(hdr, order)
    if not info or not info["images"]:
        return None
    p0 = info["images"][0]["rec_off"]
    end = _tex_path_off(hdr)
    hits = []
    for pos in range(p0, max(p0, end - 27)):
        v = _valid_rec(hdr, pos, powtwo=True, order=order)
        if v and (not hits or pos - hits[-1][0] >= 28):
            hits.append((pos, v))
    if not (1 <= len(hits) <= 6):
        return None
    import itertools

    # candidate record subsequences: all hits, all-minus-one (drop a corrupt
    # record), and each single hit (bogus placeholder + one real texture)
    cands = [tuple(hits)]
    if len(hits) > 1:
        for k in range(len(hits)):
            cands.append(tuple(hits[:k] + hits[k + 1 :]))
        cands += [(h,) for h in hits]
    best = None
    for cand in cands:
        recs = [(v["enum"], v["aw"], v["ah"]) for _, v in cand]
        if len(recs) > 4:
            continue
        sols = []
        for mips in itertools.product(range(1, 14), repeat=len(recs)):
            if sum(_chain_bytes(e, w, h, m) for (e, w, h), m in zip(recs, mips)) == len(stream):
                sols.append(mips)
                if len(sols) > 400:
                    sols = []
                    break
        for mips in sols:
            off = 0
            tot = 0.0
            for (e, w, h), m in zip(recs, mips):
                img = _decode_one_layer(stream[off:], e, w, h)
                if img is None:
                    tot = 1e9
                    break
                tot += _coherence(img)
                off += _chain_bytes(e, w, h, m)
            if tot < 1e9 and (best is None or tot < best[0]):
                best = (tot, [(e, w, h, m) for (e, w, h), m in zip(recs, mips)])
    return best[1] if best else None


#: PC cube maps: True = mip LEVELS one after another, six faces per level; False =
#: the 1.3.0 reading (six face mip chains one after another).  Measured: read level
#: by level, all six faces of all 110 + 200 PC cube maps equal the PS3 and X360
#: copies pixel for pixel; read face by face only face 0 does (faces 1-5 of every
#: PC cube map were wrong in 1.3.0).  Set False to get the 1.3.0 files back.
PC_CUBE_LEVEL_MAJOR = True


def carve_texture(stream, header, out_dir, log=None):
    """DETERMINISTIC carve: parse the layer plan from the header + the byte-exact
    stream length, then decode every layer (diffuse / normal / spec / ...) — or
    each cube face / animation frame — with NO coherence guessing. Falls back to
    the drift-rescue planner, then the legacy heuristic, only if the header is
    not a cleanly parseable Texture."""
    if not callable(log):
        log = lambda *a, **k: None
    S = len(stream)
    if S < 16:  # was 256, which silently skipped 12 tiny valid textures
        return False
    if not _is_texture(header, "<") and _is_texture(header, ">"):
        return carve_texture_console(stream, header, out_dir, log)
    info = parse_texture_header(header)
    if info is None:
        return _carve_texture_legacy(stream, header, out_dir, log)
    plan = plan_texture_layers(header, S)
    if plan["kind"] == "fail":
        rl = _rescue_texture_plan(header, stream)
        if rl:
            out_dir.mkdir(parents=True, exist_ok=True)
            wrote = 0
            off = 0
            for j, (en, w, h, mip) in enumerate(rl):
                img = _decode_one_layer(stream[off:], en, w, h)
                off += _chain_bytes(en, w, h, mip)
                if img is None:
                    continue
                lbl = texture_layer_label([{"enum": e} for e, _, _, _ in rl], j)
                Image.fromarray(img).save(
                    out_dir / ("%d_%s_%dx%d_%s.png" % (j, lbl, w, h, TEX_FMT[en][0]))
                )
                wrote += 1
            log(
                "      %s: DRIFT-RESCUE %d layers -> %s/ (%d png)"
                % (info["name"] or out_dir.name, len(rl), out_dir.name, wrote)
            )
            if wrote:
                return True
        return _carve_texture_legacy(stream, header, out_dir, log)
    out_dir.mkdir(parents=True, exist_ok=True)
    layers, kind, count = plan["layers"], plan["kind"], plan["count"]
    cb = lambda x: x.get("chain") or _chain_bytes(x["enum"], x["aw"], x["ah"], x["mip"])
    set_bytes = sum(cb(x) for x in layers)
    wrote = 0

    def dump_set(buf, prefix):
        nonlocal wrote
        off = 0
        for j, lay in enumerate(layers):
            en, w, h = lay["enum"], lay["aw"], lay["ah"]
            c = cb(lay)
            lb = buf[off : off + c]
            if lay.get("chain"):  # exact plan: linear rows carry the 4-byte pitch
                lb = _unpad_linear(lb, en, w, h)
            img = _decode_one_layer(lb, en, w, h)
            off += c
            if img is None:
                continue
            lbl = texture_layer_label(layers, j)
            Image.fromarray(img).save(
                out_dir / ("%s%s_%s_%dx%d_%s.png" % (prefix, j, lbl, w, h, TEX_FMT[en][0]))
            )
            wrote += 1

    if kind == "single":
        dump_set(stream, "")
    elif kind == "cube":
        face = S // 6
        if PC_CUBE_LEVEL_MAJOR and plan.get("exact"):
            lay = layers[0]  # the exact plan admits one-layer cubes only
            lvl0 = _chain_bytes_exact(lay["enum"], lay["aw"], lay["ah"], 1)
            for f in range(6):
                dump_set(stream[f * lvl0 : f * lvl0 + set_bytes], "face%d_" % f)
        else:
            for f in range(6):
                dump_set(stream[f * face : (f + 1) * face], "face%d_" % f)
    elif kind == "anim":
        fr = S // count
        for f in range(count):
            dump_set(stream[f * fr : (f + 1) * fr], "frame%d_" % f)
    try:
        ex, it = extract_specular(header)
        if ex is not None or it is not None:
            with open(out_dir / "spec.txt", "w", encoding="utf-8", newline="\n") as _f:
                _f.write("%s %s" % ("" if ex is None else repr(ex), "" if it is None else repr(it)))
    except Exception:
        pass
    _write_sheet_json(header, out_dir, "<")
    log(
        "      %s: %s x%d (set=%dB) layers=%d -> %s/ (%d png)"
        % (info["name"] or out_dir.name, kind, count, set_bytes, len(layers), out_dir.name, wrote)
    )
    return wrote > 0


def _carve_texture_legacy(stream, header, out_dir, log):
    """Legacy coherence-search carve — retained as a fallback for non-Texture or
    unparseable headers (e.g. standalone _h_z blobs without a class tag)."""
    S = len(stream)
    if S < 4096:
        return False
    ordered = header_dims(header)
    ordered = [d for d in ordered if d[0] == d[1]] + [d for d in ordered if d[0] != d[1]]
    chosen, best_coh = None, None
    for w, h in ordered:
        for dfmt in ("DXT1", "DXT5"):
            bb = 8 if dfmt == "DXT1" else 16
            dsize, _ = mip_chain_size(w, h, bb)
            if dsize > S:
                continue
            if not _looks_like_normal(decode_bc5_base(stream[dsize:], w, h)):
                continue
            db = decode_dxt_base(stream, w, h, dfmt)
            if db is None:
                continue
            c = _coherence(db)
            if c < 60 and (best_coh is None or c < best_coh):
                best_coh, chosen = c, (w, h, dfmt, dsize)
    # File names follow the standard <j>_<label>_<WxH>_<FMT>.png scheme
    # (2026-08-17): the old diffuse.png/normal.png/specular.png names matched
    # neither build_texture_index's *_diffuse_*.png rglob nor _find_layer's
    # *_<label>_*.png globs, so legacy-carved textures could never be linked
    # from any OBJ/MTL.
    out_dir.mkdir(parents=True, exist_ok=True)
    if chosen is None:
        for w, h in ordered:
            for dfmt in ("DXT1", "DXT5"):
                db = decode_dxt_base(stream, w, h, dfmt)
                if db is not None and _coherence(db) < 45:
                    Image.fromarray(db).save(out_dir / ("0_diffuse_%dx%d_%s.png" % (w, h, dfmt)))
                    log(
                        "      %dx%d diffuse=%s normal=NOT-FOUND -> %s/"
                        % (w, h, dfmt, out_dir.name)
                    )
                    return True
        return False
    w, h, dfmt, dsize = chosen
    db = decode_dxt_base(stream, w, h, dfmt)
    if db is not None:
        Image.fromarray(db).save(out_dir / ("0_diffuse_%dx%d_%s.png" % (w, h, dfmt)))
    nxy = decode_bc5_base(stream[dsize:], w, h)
    if nxy:
        nxy = ati2_xy(nxy)
        normal_to_png(nxy[0], nxy[1], out_dir / ("1_normal_%dx%d_ATI2.png" % (w, h)))
    nsize, _ = mip_chain_size(w, h, 16)
    spec_off, spec_dims, best = dsize + nsize, "", None
    for sw, sh in ((w, h), (w // 2, h // 2)):
        if sw < 4 or sh < 4:
            continue
        sb = decode_dxt_base(stream[spec_off:], sw, sh, "DXT1")
        if sb is not None:
            c = _coherence(sb)
            if best is None or c < best[0]:
                best = (c, sw, sh, sb)
    if best and best[0] < 45:
        # colour spec layer -> the specMap slot _find_layer/_write_obj_mtl look up
        Image.fromarray(best[3]).save(out_dir / ("2_specMap_%dx%d_DXT1.png" % (best[1], best[2])))
        spec_dims = "%dx%d" % (best[1], best[2])
    log(
        "      %dx%d diffuse=%s normal=BC5 specular=%s -> %s/"
        % (w, h, dfmt, spec_dims or "n/a", out_dir.name)
    )
    return True


# ===========================================================================
# (4) Model decoding  (vertex/index buffers -> OBJ)
# ===========================================================================
def _sane(v):
    if v != v or abs(v) == float("inf"):
        return False
    return v == 0.0 or (1e-9 < abs(v) < 1e4)


def _vb_run(buf, off, stride, be):
    fmt = ">3f" if be else "<3f"
    n = 0
    while off + (n + 1) * stride + 12 <= len(buf):
        x, y, z = struct.unpack_from(fmt, buf, off + n * stride)
        if not (_sane(x) and _sane(y) and _sane(z)):
            break
        n += 1
    return n


def _read_ib(stream, io_off, nv, be):
    """u16 index list starting at io_off, stopping at the first index >= nv
    (that's the per-face surface table / next record)."""
    fmt = ">H" if be else "<H"
    idx = []
    o = io_off
    while o + 2 <= len(stream):
        v = struct.unpack_from(fmt, stream, o)[0]
        if v >= nv:
            break
        idx.append(v)
        o += 2
    return idx


def _pick_vb(stream):
    """Choose (off, stride, be, nv, idx). PREFER the interpretation that has a
    REAL index buffer right after the VB (>=4 tris, all indices < nv, using >=50%
    of the verts) -- this rejects false-positive float runs and picks the right
    endian/stride. FALL BACK to the longest sane vertex run (the original
    behaviour) when nothing has a valid IB, so this never decodes fewer meshes
    than before. Returns None only when there is no sane vertex run at all."""
    valid = []  # (tris, nv, pack) -- a real VB+IB pair
    anyrun = []  # (nv, pack)        -- any sane vertex run (fallback)
    for be in (False, True):
        for stride in (44, 56, 32, 40, 48, 52, 60, 64):
            o = 0
            while o < len(stream) - stride * 4:
                nv = _vb_run(stream, o, stride, be)
                if nv >= 8:
                    idx = _read_ib(stream, o + nv * stride, nv, be)
                    pack = (o, stride, be, nv, idx)
                    anyrun.append((nv, pack))
                    tris = len(idx) // 3
                    if tris >= 4 and len(idx) >= 12 and (max(idx) >= nv * 0.5):
                        valid.append((tris, nv, pack))
                    o += max(1, nv) * stride
                else:
                    o += 4
    if valid:
        valid.sort(key=lambda c: (c[0], c[1]), reverse=True)
        return valid[0][2]
    if anyrun:
        anyrun.sort(key=lambda c: c[0], reverse=True)
        return anyrun[0][1]
    return None


def _u32le(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _u32(b, o, bo="<"):
    return struct.unpack_from(bo + "I", b, o)[0]


def find_descriptors(header, order="<"):
    """Deterministic per-submesh geometry descriptors:
    [flag][vertexCount][G][flag][idxBytes][1], flag in {0,8}, G 5=rigid/44 6=skin/56.
    Integers are in block byte order (LE PC / BE X360+PS3).  The consoles use
    SMALLER vertex strides for the same G: rigid G=5 -> 32B (PC 44), skinned
    G=6 -> 44B (PC 56): the console layout packs normal/tangents as 11:11:10
    u32s instead of half3s (verified vs PC ground truth, 2026-07-13)."""
    out = []
    last = -100
    n = len(header)
    for p in range(0, n - 24):
        fa = _u32(header, p, order)
        nv = _u32(header, p + 4, order)
        G = _u32(header, p + 8, order)
        fb = _u32(header, p + 12, order)
        ib = _u32(header, p + 16, order)
        one = _u32(header, p + 20, order)
        if (
            G in (5, 6)
            and fa == fb
            and fa in (0, 8)
            and one == 1
            and 3 <= nv <= 300000
            and 6 <= ib <= 8000000
            and ib % 2 == 0
        ):
            if p - last >= 24:
                if order == ">":
                    out.append((nv, 32 if G == 5 else 44, ib))
                else:
                    out.append((nv, 44 if G == 5 else 56, ib))
                last = p
    return out


def _ib_ok(stream, vbo, nv, stride, ib, order="<", maxdeg=0.4):
    """True if the index buffer at vbo forms mostly NON-degenerate triangles
    (< maxdeg repeated-index). A false-positive VB offset (positions look sane so
    it passes _vb_ok) typically lands ~4 bytes before the real one and yields a
    ~50% repeated-index IB, while every real submesh is ~0%. Used to make the VB
    search prefer the real offset (recovered the X360 TwilightLadyHair and the
    rorschachspots decals, 2026-07-15d)."""
    ibo = vbo + nv * stride
    nt = ib // 6
    if nt == 0 or ibo + ib > len(stream):
        return True
    deg = 0
    for t in range(nt):
        a, b, c = struct.unpack_from(order + "3H", stream, ibo + t * 6)
        if len({a, b, c}) < 3:
            deg += 1
    return deg <= maxdeg * nt


def _vb_ok(stream, vbo, nv, stride, ib, order="<"):
    """STRICT carve validation: every index in range AND positions finite/bounded/
    non-degenerate (all 3 axis spans > eps). Rejects false offsets that squish a
    submesh flat (the old lenient check accepted those)."""
    ibo = vbo + nv * stride
    if ibo + ib > len(stream):
        return False
    for t in range(ib // 6):
        a, b, c = struct.unpack_from(order + "3H", stream, ibo + t * 6)
        if not (a < nv and b < nv and c < nv):
            return False
    mnx = mny = mnz = 1e30
    mxx = mxy = mxz = -1e30
    for j in range(nv):
        x, y, z = struct.unpack_from(order + "3f", stream, vbo + j * stride)
        if not (_sane(x) and _sane(y) and _sane(z)):
            return False
        if x < mnx:
            mnx = x
        if x > mxx:
            mxx = x
        if y < mny:
            mny = y
        if y > mxy:
            mxy = y
        if z < mnz:
            mnz = z
        if z > mxz:
            mxz = z
    return min(mxx - mnx, mxy - mny, mxz - mnz) > 1e-4


def _vb_ok_flat(stream, vbo, nv, stride, ib, order="<"):
    """FALLBACK for planar decals (signs/graffiti: legit meshes with one flat
    axis; 56 models, 2026-07-09 batch sweep).  Same checks as _vb_ok but only
    requires TWO non-degenerate axes.  Only use when the strict scan found
    nothing -- relaxing the primary gate shifts 174 offsets on good models
    (validated; the strictness is load-bearing)."""
    ibo = vbo + nv * stride
    if ibo + ib > len(stream):
        return False
    for t in range(ib // 6):
        a, b, c = struct.unpack_from(order + "3H", stream, ibo + t * 6)
        if not (a < nv and b < nv and c < nv):
            return False
    mnx = mny = mnz = 1e30
    mxx = mxy = mxz = -1e30
    for j in range(nv):
        x, y, z = struct.unpack_from(order + "3f", stream, vbo + j * stride)
        if not (_sane(x) and _sane(y) and _sane(z)):
            return False
        if x < mnx:
            mnx = x
        if x > mxx:
            mxx = x
        if y < mny:
            mny = y
        if y > mxy:
            mxy = y
        if z < mnz:
            mnz = z
        if z > mxz:
            mxz = z
    spans = sorted((mxx - mnx, mxy - mny, mxz - mnz))
    return spans[1] > 1e-4


def _dec1110(u):
    """Console packed normal/tangent: LSB-first x:11 y:11 z:10, signed
    two's-complement, x,y/1023 z/511 (solved vs PC half3 ground truth,
    RMS 0.001 over 1464 matched Sky_Mansion vertices)."""
    x = u & 0x7FF
    y = (u >> 11) & 0x7FF
    z = (u >> 22) & 0x3FF
    if x >= 0x400:
        x -= 0x800
    if y >= 0x400:
        y -= 0x800
    if z >= 0x200:
        z -= 0x400
    return (x / 1023.0, y / 1023.0, z / 511.0)


#: Restored content: the eyelash strips of the generic female heads.
#: The "EyeBlow" submesh of FemaleHead_White1, FemaleHead_White1_Gimp,
#: Girl_Head_White and FimaleGimpMask (72 vertices, 80 triangles: an upper and a
#: lower strip per eye, 18 vertices each, both eyes on the same UVs) stores its
#: UVs in a corner of the EyeBlow texture that is fully transparent, u 0.0033 ..
#: 0.0620, v 0.3914 .. 0.4609 (v as stored, top-down), so the alpha test of its
#: sheet (alphaThreshold 95) discards every pixel.  The same bytes are in the PC,
#: PS3 and Xbox 360 files (measured: half floats, equal value for value), so the
#: game draws no lashes on these heads.  TwilightLady_Head carries the same two
#: strips on a texture with the same painting: her lower strip has the same
#: triangle list and her upper strip contains the 18 upper vertices.  Each strip
#: of the small layout is that strip scaled down and moved (least squares against
#: her UVs of the matched vertices, uniform scale and a shift, measured):
#:   upper  uv' = 11.7691 * uv + ( 0.4736, -4.4107)   rms 0.0016 (0.2 texel of 128)
#:   lower  uv' = 11.5133 * uv + (-0.0358, -4.5707)   rms 0.0142 (1.8 texels)
#: With it 95.6 % of the painted (alpha > 95) texels are covered by lash
#: triangles (Twilight Lady's own strips: 88 %); the best single transform of the
#: whole layout covers 55 %.  Why the files hold the small layout is not
#: established.  WATCHMEN_NO_SYNTH=1 writes the stored UVs.
LASH_RESTORE = {
    "vertex_count": 72,
    "strip_vertices": 18,
    "stored_uv_min": (0.00331, 0.39136),
    "stored_uv_max": (0.06195, 0.46094),
    # strip -> (mean stored v, scale, (shift u, shift v))
    "strips": {
        "upper": (0.4137, 11.7691, (0.4736, -4.4107)),
        "lower": (0.4494, 11.5133, (-0.0358, -4.5707)),
    },
}


def synth_enabled():
    """False with WATCHMEN_NO_SYNTH set: nothing the game data does not hold is
    written (no reconstructed Dominatrix_3, eyelash UVs as stored)."""
    return not os.environ.get("WATCHMEN_NO_SYNTH")


def lash_strips(uvs):
    """["upper" | "lower"] per block of 18 vertices when `uvs` is the small
    eyelash layout of the generic female heads (LASH_RESTORE), else None.  The
    test is the layout itself: 72 vertices, the stored UV box, and four blocks
    whose mean v is that of the upper or the lower strip."""
    L = LASH_RESTORE
    if uvs is None or len(uvs) != L["vertex_count"]:
        return None
    lo, hi = L["stored_uv_min"], L["stored_uv_max"]
    for k in (0, 1):
        col = [uv[k] for uv in uvs]
        if abs(min(col) - lo[k]) > 2e-4 or abs(max(col) - hi[k]) > 2e-4:
            return None
    n = L["strip_vertices"]
    out = []
    for b in range(0, len(uvs), n):
        mv = sum(uv[1] for uv in uvs[b : b + n]) / n
        name = [s for s, (m, _, _) in L["strips"].items() if abs(mv - m) < 2e-3]
        if len(name) != 1:
            return None
        out.append(name[0])
    return out


def lash_restored_uvs(uvs):
    """The small eyelash layout (lash_strips) moved onto the painted lashes of
    its texture; None when `uvs` is not that layout."""
    strips = lash_strips(uvs)
    if strips is None:
        return None
    n = LASH_RESTORE["strip_vertices"]
    out = []
    for i, (u, v) in enumerate(uvs):
        _, s, (du, dv) = LASH_RESTORE["strips"][strips[i // n]]
        out.append((s * u + du, s * v + dv))
    return out


def lash_is_restored(uvs):
    """True when `uvs` (72 pairs) is the restored eyelash layout, i.e. what
    lash_restored_uvs returns for the stored one."""
    L = LASH_RESTORE
    if uvs is None or len(uvs) != L["vertex_count"] or len(uvs[0]) != 2:
        return False
    n = L["strip_vertices"]
    back = []
    for b in range(0, len(uvs), n):
        blk = [(float(u), float(v)) for u, v in uvs[b : b + n]]
        for mean_v, s, (du, dv) in L["strips"].values():
            inv = [((u - du) / s, (v - dv) / s) for u, v in blk]
            if abs(sum(x[1] for x in inv) / n - mean_v) < 2e-3:
                break
        else:
            return False
        back.extend(inv)
    again = lash_restored_uvs(back)
    return again is not None and all(
        abs(a[0] - float(b[0])) < 1e-4 and abs(a[1] - float(b[1])) < 1e-4
        for a, b in zip(again, uvs)
    )


def lash_reconstruction_note():
    """The "reconstruction" entry a file with restored eyelash UVs carries."""
    L = LASH_RESTORE
    return {
        "eyelash_uvs": {
            "shipped": False,
            "submesh_texture": "EyeBlow",
            "stored_uv_range": {
                "u": [L["stored_uv_min"][0], L["stored_uv_max"][0]],
                "v": [L["stored_uv_min"][1], L["stored_uv_max"][1]],
            },
            "transform": {
                k: {"scale": s, "shift": list(t)} for k, (_, s, t) in sorted(L["strips"].items())
            },
            "note": "restored content: the eyelash strips of this head store their UVs "
            "in a transparent corner of the EyeBlow texture (v counted from the top, as "
            "in the file and in glTF; an OBJ has 1 - v), so the game draws no lashes "
            "here.  Each strip (upper, lower; 18 vertices per eye) is written as "
            "uv' = scale * uv + shift, which puts it on the painted lashes the way "
            "TwilightLady_Head maps the same strips.  WATCHMEN_NO_SYNTH=1 writes the "
            "stored UVs.",
        }
    }


def _decode_sub(stream, vbo, nv, stride, be=False, restored=None):
    """Vertex fields.  PC (44/56): pos f32x3 @0, normal half3 @12, uv half2 @24.
    Console (32/44): pos f32x3 @0 (BE), normal 11:11:10 u32 @12, color @16,
    uv BE half2 @20 (then packed tangents; skinned: idx u8x4 @32, weight half4 @36).
    The eyelash strips of the generic female heads come back with restored UVs
    (LASH_RESTORE) unless WATCHMEN_NO_SYNTH is set; a list passed as `restored`
    then receives "eyelash_uvs"."""
    fmt = ">3f" if be else "<3f"
    hfmt = ">H" if be else "<H"
    verts = [struct.unpack_from(fmt, stream, vbo + i * stride) for i in range(nv)]
    norms = None
    if stride >= 20:
        try:
            norms = []
            if be:
                for i in range(nv):
                    h = _dec1110(struct.unpack_from(">I", stream, vbo + i * stride + 12)[0])
                    m = (h[0] * h[0] + h[1] * h[1] + h[2] * h[2]) ** 0.5
                    norms.append((h[0] / m, h[1] / m, h[2] / m) if m > 1e-9 else (0.0, 0.0, 0.0))
            else:
                for i in range(nv):
                    b = vbo + i * stride + 12
                    h = [_half(struct.unpack_from(hfmt, stream, b + 2 * k)[0]) for k in range(3)]
                    m = (h[0] * h[0] + h[1] * h[1] + h[2] * h[2]) ** 0.5
                    norms.append((h[0] / m, h[1] / m, h[2] / m) if m > 1e-9 else (0.0, 0.0, 0.0))
        except Exception:
            norms = None
    uvs = None
    if stride >= 28 or (be and stride >= 24):
        try:
            uo = 20 if be else 24
            uvs = [
                (
                    _half(struct.unpack_from(hfmt, stream, vbo + i * stride + uo)[0]),
                    _half(struct.unpack_from(hfmt, stream, vbo + i * stride + uo + 2)[0]),
                )
                for i in range(nv)
            ]
        except Exception:
            uvs = None
    if nv == LASH_RESTORE["vertex_count"] and uvs and synth_enabled():
        fixed = lash_restored_uvs(uvs)
        if fixed is not None:
            uvs = fixed
            if restored is not None:
                restored.append("eyelash_uvs")
    return verts, norms, uvs


_TEX_RE = re.compile(rb"/[ -~]*?\.(?:bmp|tga|dds|png|jpg)", re.I)


def texture_key(path):
    """Asset path -> the key it has in a TextureIndex: '/'-separated, lower case, no
    leading slash, the same parts `safe()` keeps ('' / '.' / '..' dropped, ':' -> '_')."""
    parts = [p for p in str(path).replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return "/".join(p.replace(":", "_") for p in parts).lower()


class TexRef(str):
    """A material name that remembers the texture ASSET PATH its model stores.

    The model header lists full paths ('/art/characters/bikers/textures/head.bmp',
    ModelRes::Read 0x547006) and the engine loads exactly that asset (0x49b2b2 ->
    AssetManager 0x55243f); the bare name ('head') is not unique in the game data.
    It still reads, prints and compares like the plain name, but two TexRefs with
    different paths are different materials (dict / set keys included)."""

    __slots__ = ("path",)

    def __new__(cls, name, path=None):
        o = str.__new__(cls, name)
        o.path = path or None
        return o

    def __eq__(self, other):
        if not str.__eq__(self, other):
            return False
        po = getattr(other, "path", None)
        return not (self.path and po) or texture_key(self.path) == texture_key(po)

    def __ne__(self, other):
        return not self.__eq__(other)

    __hash__ = str.__hash__

    def __reduce__(self):
        return (TexRef, (str(self), self.path))


def texture_ref(path):
    """Texture asset path -> TexRef(bare name, path).

    With --names canonical (default) the path is first given its canonical
    spelling (canonical_names.canonical: the shipped table, and during an
    `extract` the spelling the texture was written under), so a material is
    named like the texture folder it resolves to whatever letter case the
    referring model stores."""
    path = _names_mod().canonical(path)
    return TexRef(_material_stem(path), path)


def extract_materials(header):
    """Ordered texture names from the ModelRes header material list (one per
    render submesh, in submesh order, for character/prop models).  Each is a
    TexRef: the bare name, with the full asset path in `.path`."""
    out = []
    for m in _TEX_RE.finditer(header):
        out.append(texture_ref(m.group().decode("latin1")))
    return out


def submesh_materials(header, order="<"):
    """Per-submesh material indices, in submesh (descriptor) order.

    Engine layout (verified on Rorschach vs in-Blender ground truth,
    2026-07-08g): each render-piece record is
        [u32 len][pieceName..\0] ... [u32 1][u32 materialIndex] ... [geometry descriptor]
    i.e. the NAME+MATERIAL precede their descriptor.  Positional pairing with
    extract_materials() order is WRONG whenever one material covers several
    submeshes (Rorschach trenchcoat).  Returns list of (pieceName, matIndex),
    one per descriptor; matIndex indexes extract_materials(header)."""
    nmats = len(extract_materials(header))
    recs = []
    i = 0
    n = len(header)
    while i < n - 8:
        ln = _u32(header, i, order)
        if 2 <= ln <= 48 and i + 4 + ln <= n:
            sb = header[i + 4 : i + 4 + ln]
            if sb[-1] == 0 and all(32 <= c < 127 for c in sb[:-1]) and sb[:1].isalpha():
                for o in range(i + 4 + ln, min(i + 4 + ln + 24, n - 8), 4):
                    a, b = _u32(header, o, order), _u32(header, o + 4, order)
                    if a == 1 and b < max(nmats, 1):
                        recs.append((i, sb[:-1].decode("latin1"), b))
                        break
                i += 4 + ln
                continue
        i += 1
    # descriptor positions (same predicate as find_descriptors)
    dpos = []
    last = -100
    for p_ in range(0, n - 24):
        fa = _u32(header, p_, order)
        nv = _u32(header, p_ + 4, order)
        G = _u32(header, p_ + 8, order)
        fb = _u32(header, p_ + 12, order)
        ib = _u32(header, p_ + 16, order)
        one = _u32(header, p_ + 20, order)
        if (
            G in (5, 6)
            and fa == fb
            and fa in (0, 8)
            and one == 1
            and 3 <= nv <= 300000
            and 6 <= ib <= 8000000
            and ib % 2 == 0
        ):
            if p_ - last >= 24:
                dpos.append(p_)
                last = p_
    out = []
    for k, dp in enumerate(dpos):
        prev = [r for r in recs if r[0] < dp]
        out.append((prev[-1][1], prev[-1][2]) if prev else ("sub%d" % k, k if k < nmats else 0))
    return out


#: directory-name endings that mark a carved texture (`<asset name>/<layer>.png`)
TEXTURE_DIR_EXTS = (".bmp", ".tga", ".dds", ".png", ".jpg", ".texture")


class TextureIndex(dict):
    """Carved-texture lookup for one `textures/` tree.

    As a dict it is bare name (lower case) -> texture dir, like the old index, and
    independent of the order the file system lists directories in.  `resolve()` is
    the lookup to use: by the asset path the model stores when there is one, by
    bare name otherwise.  When a bare name fits several directories the one whose
    asset path sorts first (lower case, '/'-separated) is taken and a warning lists
    the candidates.

    by_path:    {texture_key(asset path): dir}
    candidates: {bare name: [dir, ...]} in tie-break order"""

    def __init__(self, tex_root=None, require_diffuse=True):
        dict.__init__(self)
        self.root = None if tex_root is None else Path(tex_root)
        self.by_path = {}
        self.candidates = {}
        self._warned = set()
        if self.root is None:
            return
        found = []
        try:
            for dp, dns, fns in os.walk(str(self.root)):
                dns.sort(key=lambda d: (d.lower(), d))
                if dp == str(self.root):
                    continue
                has_dif = any("_diffuse_" in f and f.lower().endswith(".png") for f in fns)
                named = os.path.basename(dp).lower().endswith(TEXTURE_DIR_EXTS)
                if has_dif or (named and not require_diffuse):
                    rel = os.path.relpath(dp, str(self.root)).replace(os.sep, "/")
                    found.append((texture_key(rel), rel, Path(dp)))
        except Exception:
            pass
        for key, _rel, d in sorted(found, key=lambda t: (t[0], t[1])):
            self.by_path.setdefault(key, d)
            name = d.name.rsplit(".", 1)[0].strip().lower()
            self.candidates.setdefault(name, []).append(d)
            self.setdefault(name, d)

    def ambiguous(self):
        """{bare name: [dir, ...]} for every name carried by more than one texture."""
        return {k: list(v) for k, v in self.candidates.items() if len(v) > 1}

    def resolve(self, ref, warn=None):
        """Texture dir for a TexRef / asset path / bare name, or None.

        1. the asset path (TexRef.path, or `ref` itself when it contains a '/'),
        2. else the bare name; if several textures carry it, the first candidate
           (asset paths sorted) -- reported once through `warn` (stderr if None)."""
        path = getattr(ref, "path", None)
        text = str(ref)
        if path is None and ("/" in text or "\\" in text):
            path, text = text, _material_stem(text)
        if path:
            d = self.by_path.get(texture_key(path))
            if d is not None:
                return d
        name = text.strip().lower()
        cands = self.candidates.get(name)
        if not cands:
            return self.get(name)
        if len(cands) > 1 and name not in self._warned:
            self._warned.add(name)
            msg = "texture name %r is ambiguous (%s): using %s; candidates: %s" % (
                text,
                ("asset path %s is not in the texture tree" % path) if path else "no asset path",
                self._rel(cands[0]),
                ", ".join(self._rel(c) for c in cands),
            )
            if warn is None:
                print("  ! " + msg, file=sys.stderr)
            else:
                warn("      ! " + msg)
        return cands[0]

    def _rel(self, d):
        try:
            return os.path.relpath(str(d), str(self.root)).replace(os.sep, "/")
        except Exception:
            return str(d)


def build_texture_index(tex_root, require_diffuse=True):
    """TextureIndex of `tex_root`: bare name (lower) -> texture output dir (which holds
    <j>_<label>_<WxH>_<FMT>.png), plus path lookup -- see TextureIndex.resolve."""
    return TextureIndex(tex_root, require_diffuse)


def resolve_texture(tex_index, ref, warn=None):
    """Texture dir for material `ref` in `tex_index` (a TextureIndex, or a plain
    {bare name: dir} dict), or None."""
    if not tex_index:
        return None
    if hasattr(tex_index, "resolve"):
        return tex_index.resolve(ref, warn)
    return tex_index.get(str(ref).lower())


def unique_material_names(mats):
    """Names for a model's material list in which two textures that share a bare
    name but not a path stay apart: the second gets '<name>__2', the third '__3'.
    Everything else keeps its name."""
    first, out = {}, []
    for m in mats:
        k = getattr(m, "path", None)
        k = texture_key(k) if k else None
        seen = first.setdefault(str(m), [])
        if k not in seen:
            seen.append(k)
        n = seen.index(k)
        out.append(str(m) if n == 0 else "%s__%d" % (m, n + 1))
    return out


def _find_layer(texdir, label):
    try:
        g = sorted(texdir.glob("*_%s_*.png" % label))
        return g[0] if g else None
    except Exception:
        return None


def _make_roughness(texdir, specsize_png, exponent):
    """Bake a Blender roughness map matching the game's specular model.
    With a specSize map (full variant): per-pixel exponent = (specSize^2*256+1)*expScale.
    Without (specMap-only): a flat exponent = expScale. roughness = sqrt(2/(exp+2)).
    expScale is the texture's $specularData.x. Cached as roughnessGen.png."""
    import math

    out = texdir / "roughnessGen.png"
    if out.exists():
        return out
    expscale = exponent if (exponent and exponent > 0) else 15.0
    try:
        import numpy as np
        from PIL import Image

        if specsize_png is not None:
            # specSize drives the per-pixel Blinn-Phong exponent = specSize^2*256+1.
            # (The material's expScale/c2.x is NOT applied here -- it crushes the whole
            # map to near-black/mirror; the specSize map alone gives the right, properly
            # oriented variation: high specSize -> glossy -> low roughness.)
            g = np.asarray(Image.open(specsize_png).convert("L"), dtype=np.float32) / 255.0
            expo = g * g * 256.0 + 1.0
            # The L8 specSize layer reads as a matte/roughness map in practice
            # (high value -> matte). Verified against in-engine renders: roughness
            # must INCREASE with specSize, so invert the exponent->roughness curve.
            rough = 1.0 - np.sqrt(2.0 / (expo + 2.0))
            Image.fromarray((np.clip(rough, 0.0, 1.0) * 255.0).astype("uint8")).save(out)
        else:
            # Flat (no specSize): roughness from the material exponent, INVERTED to
            # match in-engine renders (consistent with the per-pixel path). Low-exp
            # skin -> matte. roughness = 1 - sqrt(2/(exp+2)).
            rv = 1.0 - min(1.0, math.sqrt(2.0 / (expscale + 2.0)))
            r = int(round(min(1.0, max(0.0, rv)) * 255.0))
            Image.fromarray((np.full((4, 4), r, dtype="uint8"))).save(out)
        return out
    except Exception:
        return None


def _materials_mode():
    try:
        import materials as _mt
    except ImportError:
        _d = os.path.dirname(os.path.abspath(__file__))
        if _d not in sys.path:
            sys.path.append(_d)
        import materials as _mt
    return _mt.mode()


def _mtl_no_highlight(texdir, inten, specmap_png):
    """materials.no_highlight for a texture of the MTL writer: `inten` is the
    spec.txt intensity (= the first sheet's specularPower, which is used when
    there is no spec.txt), the cube reflection comes from sheet.json, and a
    specMap that is black everywhere
    switches the highlight off as well.  Such a material gets `Ns 0` (roughness
    1 in Blender's importer) instead of a roughnessEngine.png, as its glTF
    material gets roughnessFactor 1.0 and no roughness texture."""
    try:
        import materials as _mt

        black = False
        if specmap_png is not None and not (inten is not None and inten <= 0.0):
            from PIL import Image

            ext = Image.open(specmap_png).convert("RGB").getextrema()
            black = max(hi for _lo, hi in ext) == 0
        sheet = read_sheet_json(texdir)
        full = sheet.get("sheets")  # the first sheet in full, as rig_glb reads it
        if isinstance(full, list) and full and isinstance(full[0], dict):
            sheet = dict(full[0], **{k: v for k, v in sheet.items() if k != "sheets"})
        sb = sheet_blend(sheet) if sheet else None
        if sb and sb.get("cause") == "opacity" and sb.get("gltf") not in ("ink", "glow"):
            sb = None  # blended for its opacity alone: rig_glb builds its engine material
        if not sheet or sb:
            return False  # the GLB writer builds no engine material for these either
        return _mt.no_highlight(sheet, inten, black)
    except Exception:
        return False


def _first_sheet(texdir):
    """The texture's first sheet with all its properties, from sheet.json ({} when
    the texture has none): the top-level switches overlaid on "sheets"[0], as
    rig_glb reads it."""
    sheet = read_sheet_json(texdir)
    full = sheet.get("sheets")
    if isinstance(full, list) and full and isinstance(full[0], dict):
        sheet = dict(full[0], **{k: v for k, v in sheet.items() if k != "sheets"})
    return sheet


def _mtl_opacity(sheet):
    """`d` value of the MTL, or None: the sheet's opacity where the engine draws
    the part blended for it -- opacity < 0.99 and renderType 0 or 10 (0x5739d0) or
    7 (the sky pass, 0x589dd9)."""
    try:
        op = sheet.get("opacity")
        if op is not None and float(op) < 0.99 and sheet.get("renderType") in (0, 7, 10):
            return max(0.0, float(op))
    except (TypeError, ValueError):
        pass
    return None


def _mtl_emission(sheet):
    """What the MTL does with a glow layer -> (use it, Ke rgb | None).

    The engine adds G = selfIlluminanceColor * selfIlluminance * glow (materials.py
    header), so a glow layer shows only where the sheet's selfIlluminance is above
    0: then (True, colour * selfIlluminance clamped to 1).  selfIlluminance 0 (or
    below) -> (False, None): the layer is named in a comment and not linked (a
    level node can select another sheet of the texture, e.g. a lamp's "Lit" sheet
    after its "light off" one; a model file is written with the first sheet).  A
    texture without sheet values keeps the old behaviour, (True, None)."""
    si = (sheet or {}).get("selfIlluminance")
    if si is None or isinstance(si, bool):
        return True, None
    try:
        si = float(si)
        col = sheet.get("selfIlluminanceColor") or [1.0, 1.0, 1.0]
        ke = [min(1.0, max(0.0, float(c) * si)) for c in list(col)[:3]]
    except (TypeError, ValueError):
        return True, None
    if si <= 0.0 or len(ke) != 3:
        return False, None
    return True, ke


def _make_roughness_engine(texdir, specsize_png, exponent):
    """roughnessEngine.png: glTF / Principled roughness of the engine's lobe,
    (2 / (n + 2)) ** 0.25 with n = specularSize, times (g^2 * 256 + 1) per texel with
    a specSize layer (DeferredMain2PS; materials.roughness).  The legacy
    roughnessGen.png (1 - sqrt(2/(n+2)), sheet exponent ignored) is left alone."""
    out = texdir / "roughnessEngine.png"
    if out.exists():
        return out
    try:
        import numpy as np
        from PIL import Image
        import materials as _mt

        if specsize_png is not None:
            g = np.asarray(Image.open(specsize_png).convert("L"), dtype=np.float32) / 255.0
            r = _mt.roughness(_mt.exponent(exponent, g))
            Image.fromarray(np.round(r * 255.0).astype("uint8")).save(out)
        else:
            r = int(round(float(_mt.roughness(_mt.exponent(exponent))) * 255.0))
            Image.fromarray(np.full((4, 4), r, dtype="uint8")).save(out)
        return out
    except Exception:
        return None


def _write_obj_mtl(path, name, v, n, uv, tris, subs, mats, tex_index, log):
    path.parent.mkdir(parents=True, exist_ok=True)

    def _san(x):
        return re.sub(r"[^0-9A-Za-z_.\-]", "_", x)

    def fv(a):
        if uv and n:
            return "%d/%d/%d" % (a, a, a)
        if n:
            return "%d//%d" % (a, a)
        if uv:
            return "%d/%d" % (a, a)
        return "%d" % a

    multi = len(subs) > 1
    names = [_san(x) for x in unique_material_names(mats)]
    mtl_path = path.with_suffix(".mtl")
    objdir = path.parent
    import frame as _frame

    # true frame (default): x negated; the faces stay in file order, which is the
    # counter-clockwise (front) order there.  mirrored: the engine numbers as 1.3.0
    # wrote them (faces wind against the normals in a right-handed reader).
    true_frame = _frame.is_true()
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s  (%d verts, %d tris, %d submeshes)\n" % (name, len(v), len(tris), len(subs)))
        if true_frame:
            f.write("# %s %s (x = -engine x)\n" % (_frame.MARKER_KEY, _frame.TRUE))
        f.write("mtllib %s\n" % mtl_path.name)
        for p in v:
            if true_frame:
                p = (-p[0] + 0.0, p[1], p[2])
            f.write("v %.6f %.6f %.6f\n" % tuple(p))
        if uv:
            for u, w in uv:
                f.write("vt %.6f %.6f\n" % (u, 1.0 - w))
        if n:
            for nn in n:
                if true_frame:
                    nn = (-nn[0] + 0.0, nn[1], nn[2])
                f.write("vn %.6f %.6f %.6f\n" % tuple(nn))
        for si, (base, vc, tstart, tcount, st) in enumerate(subs):
            mat = names[si] if si < len(mats) else ("submesh_%d" % si)
            f.write(("o %s_%s\n" % (_san(name), mat)) if multi else ("o %s\n" % _san(name)))
            f.write("usemtl %s\n" % mat)
            for a, b, c in tris[tstart : tstart + tcount]:
                f.write("f %s %s %s\n" % (fv(a + 1), fv(b + 1), fv(c + 1)))
    # MTL: diffuse->map_Kd, normal->norm, specular->map_Ks, glossiness->map_Ns
    # (verified in Blender's importer: 'norm' is IGNORED; map_Bump routes through a
    # Normal Map node). map_Ns lands in Roughness, which is
    # gloss-inverted, but it links the map.
    seen = set()
    with open(mtl_path, "w", encoding="utf-8", newline="\n") as mf:
        mf.write("# materials for %s (textures linked from the textures/ dump)\n" % name)
        for raw, mm in zip(mats, names):
            if mm in seen:
                continue
            seen.add(mm)
            mf.write("newmtl %s\n" % mm)
            mf.write("Kd 0.8 0.8 0.8\n")
            texdir = (
                None
                if (str(raw).startswith("submesh_") or not tex_index)
                else resolve_texture(tex_index, raw, log if callable(log) else None)
            )
            if texdir:

                def _rel(fp):
                    return os.path.relpath(str(fp), str(objdir)).replace("\\", "/")

                # per-texture specular params ($specularData.xy) written at carve time
                exp = inten = None
                sp = texdir / "spec.txt"
                if sp.exists():
                    try:
                        parts = sp.read_text().split()
                        exp = float(parts[0]) if len(parts) > 0 and parts[0] else None
                        inten = float(parts[1]) if len(parts) > 1 and parts[1] else None
                    except Exception:
                        pass
                # layers the texture's first sheet takes from another texture
                over = sheet_layer_dirs(
                    tex_index if hasattr(tex_index, "resolve") else None,
                    read_sheet_json(texdir),
                    log if callable(log) else None,
                )
                dif = _find_layer(over.get("diffuse", texdir), "diffuse")
                nrm = _find_layer(over.get("normal", texdir), "normal")
                spm = _find_layer(over.get("specMap", texdir), "specMap")
                sps = _find_layer(over.get("specSize", texdir), "specSize")
                glw = _find_layer(over.get("glow", texdir), "glow")
                sheet0 = _first_sheet(texdir) if _materials_mode() == "engine" else {}
                if dif:
                    mf.write("map_Kd %s\n" % _rel(dif))
                    mf.write("map_d %s\n" % _rel(dif))  # transparency from diffuse alpha
                    fade = _mtl_opacity(sheet0)
                    if fade is not None:  # drawn blended for the sheet's opacity
                        mf.write("d %.4f\n" % fade)
                if nrm:
                    mf.write("map_Bump -bm 1.000000 %s\n" % _rel(nrm))
                # Specular gated by intensity (c2.y): intensity 0 => matte, no spec.
                matte = inten is not None and inten <= 0.0
                if matte:
                    mf.write("Ks 0 0 0\n")
                else:
                    spec_src = spm or sps
                    if spec_src:
                        mf.write("map_Ks %s\n" % _rel(spec_src))
                    if inten is not None:
                        k = min(1.0, inten)
                        mf.write("Ks %.4f %.4f %.4f\n" % (k, k, k))
                # Roughness baked from the real exponent (c2.x) and the specSize curve.
                if _materials_mode() == "engine":
                    if _mtl_no_highlight(texdir, inten, spm):
                        # the game draws no highlight: fully rough, and no bake
                        # (roughnessEngine.png would hold the sheet's narrow lobe)
                        rough = None
                        mf.write("Ns 0.000000\n")
                    else:
                        rough = _make_roughness_engine(texdir, sps, exp)
                else:
                    rough = _make_roughness(texdir, sps, exp)
                if rough:
                    mf.write("map_Ns %s\n" % _rel(rough))
                if glw:
                    lit, ke = _mtl_emission(sheet0)
                    if ke is not None:
                        mf.write("Ke %.4f %.4f %.4f\n" % tuple(ke))
                    if lit:
                        mf.write("map_Ke %s\n" % _rel(glw))
                    else:  # the engine multiplies the layer with selfIlluminance = 0
                        others = [
                            s
                            for s in (read_sheet_json(texdir).get("sheets") or [])[1:]
                            if isinstance(s, dict) and (s.get("selfIlluminance") or 0) > 0
                        ]
                        mf.write(
                            "# glow layer not linked (selfIlluminance 0 in the first sheet; "
                            "%d other sheet(s) of the texture light it): %s\n"
                            % (len(others), _rel(glw))
                        )
            mf.write("\n")


# ---- rigged/textured .glb export (optional; --glb). FILE-DERIVED (2026-07-13):
#      the flat skin rig takes its joint names + palette ORDER from the model's own
#      embedded skeleton header (extract_skeletons.skeleton_from_header), so the old
#      capture artifacts (skeleton_female_biped.json / bundled_clip_*.npz) are no
#      longer read. Emitted glbs are bind-pose; engine-exact ANIMATED per-character
#      glbs come from the QA'd file-only pipeline: `watchmen.py characters` (binds ->
#      bake -> variant glbs). ----
#: "attrs": --glb also writes the engine's per-vertex data (NORMAL, TANGENT,
#: COLOR_0), sheet-driven materials and static .glb files for rigid models;
#: --no-vertex-attrs clears it and the .glb output is the 1.3.0 one.
_RIG = {"on": False, "mod": None, "loaded": False, "attrs": True}


def _rig_load():
    if _RIG["loaded"]:
        return _RIG["mod"] is not None
    _RIG["loaded"] = True
    try:
        import rig_glb

        _RIG["mod"] = rig_glb
    except Exception:
        _RIG["mod"] = None
    return _RIG["mod"] is not None


def _model_palette(header):
    """Joint table for the flat skin rig, decoded from the MODEL's own header
    (palette order = header node order). Returns {'bone_count','bones':[{'name'}]}."""
    try:
        import extract_skeletons as _es

        sk = _es.skeleton_from_header(header, "palette")
        if sk and sk.get("bone_count"):
            return sk
    except Exception:
        pass
    return None


def _model_is_body(header):
    """True if the model embeds a full biped body skeleton (has leg bones). Head /
    accessory models embed their own small palette (face bones, no legs) -- those must
    NOT be rigged with the shared body skeleton (their joint indices reference their own
    palette, which would otherwise collapse the head into the chest)."""
    try:
        import parse_model_nodes as _pmn

        names, _p, _q, _par = _pmn.parse(header)
        if len(names) <= 1:
            return True  # nothing decoded -> assume body, never silently unrig
        return any(("Calf" in n) or ("Thigh" in n) for n in names)
    except Exception:
        return True  # default: treat as body (prior behaviour)


# ---------------------------------------------------------------------------
# ENGINE-EXACT ModelRes header (PC).  Reader chain, all read from the exe:
#   FUN_00547006 ModelRes::Read -> FUN_00545927 (part / pivot node)
#   -> FUN_00542541 (submesh record) -> FUN_004336ec (MeshBuffer header).
# The stream blob then holds, per MeshBuffer in header order, the bulk fields in
# the order FUN_00433ef4 reads them: vertices, indices, cluster table, lists,
# optional per-vertex array.  Every offset is computed -- nothing is searched.
# ---------------------------------------------------------------------------
#: vertex stride per format id (exe table 0x00C791B0); the id is the third u32
#: of the vertex-buffer descriptor and selects the D3D9 declaration (FUN_0045544e).
VERTEX_STRIDES = (28, 24, 68, 16, 56, 44, 56, 60, 48, 20, 32)
#: byte offsets of the elements of the formats ModelRes files use.
#:   normal/tangent/bitangent = half3 (+1 unused half), uv = half2,
#:   color = D3DCOLOR (bytes B,G,R,A), joints = D3DCOLOR (idx0..3 = bytes 2,1,0,3),
#:   weights = half4.  Writers: FUN_00430efe (5), FUN_0043106f (6),
#:   FUN_0043114e (9), FUN_00431195 (10).
VERTEX_FORMATS = {
    5: {"position": 0, "normal": 12, "color": 20, "uv": 24, "tangent": 28, "bitangent": 36},
    6: {
        "position": 0,
        "normal": 12,
        "color": 20,
        "uv": 24,
        "tangent": 28,
        "bitangent": 36,
        "joints": 44,
        "weights": 48,
    },
    9: {"position": 0, "normal": 12},  # rigid shadow hull
    10: {"position": 0, "normal": 12, "joints": 20, "weights": 24},  # skinned shadow hull
}
#: the same two tables for the big-endian console files (Xbox 360 and PS3, both
#: parts).  Strides: Xbox 360 exe table 0x8308b6e0; with them (and the console
#: cluster / list record sizes below) the stream blob of every console model of
#: the four console sets is consumed exactly.  Element offsets: read from data
#: against the PC copy of the same vertex (normal, colour, uv, tangent frame,
#: skin).  normal / tangent / bitangent = one packed u32 each (_dec1110), uv =
#: half2, joints = u32 (idx0..3 = bytes 1,2,3,0), weights = half4.  color: four
#: bytes A,R,G,B on Xbox 360 and R,G,B,A on PS3 -- the one field the two
#: consoles store differently (console_color_order).
#: Xbox 360: the streams are read into the GPU buffer unconverted -- the
#: vertex / index buffer code of the image (0x82a30000-0x82a38800) contains no
#: D3D pack or unpack instruction (measured with the VMX128 language,
#: tools/ghidra/README.md "Further tooling").
CONSOLE_VERTEX_STRIDES = (28, 24, 68, 16, 56, 32, 44, 60, 36, 16, 28)
CONSOLE_VERTEX_FORMATS = {
    5: {"position": 0, "normal": 12, "color": 16, "uv": 20, "tangent": 24, "bitangent": 28},
    6: {
        "position": 0,
        "normal": 12,
        "color": 16,
        "uv": 20,
        "tangent": 24,
        "bitangent": 28,
        "joints": 32,
        "weights": 36,
    },
    9: {"position": 0, "normal": 12},  # rigid shadow hull
    # skinned shadow hull; joints bytes 17,18,19,16 (measured against PC; PS3 shader indices.yzwx)
    10: {"position": 0, "normal": 12, "joints": 16, "weights": 20},
}
#: bytes of one cluster record / one item of the per-buffer lists in the stream
#: blob, PC and console (data: the only sizes that tile the console streams)
_STREAM_RECORDS = {"<": (40, 0x44), ">": (48, 0x50)}
_VOLUME_FLOATS = {5: 3, 6: 1, 7: 2}  # box / sphere / capsule (FUN_00524b23)


def console_header_decode():
    """False when WATCHMEN_CONSOLE_MODELS=scan: console (big-endian) models are
    then decoded by the descriptor scan as before 2026-10-05, not from their
    header.  Default: header-driven."""
    return os.environ.get("WATCHMEN_CONSOLE_MODELS", "header").strip().lower() != "scan"


def vertex_strides(order="<"):
    """Vertex stride per format id for a byte order ("<" PC, ">" console)."""
    return CONSOLE_VERTEX_STRIDES if order == ">" else VERTEX_STRIDES


def vertex_formats(order="<"):
    """Element offsets per format id for a byte order ("<" PC, ">" console)."""
    return CONSOLE_VERTEX_FORMATS if order == ">" else VERTEX_FORMATS


class _Rd:
    """Bounds-checked sequential reader (raises ValueError past the end)."""

    def __init__(s, b, order="<"):
        s.b, s.p, s.o = b, 0, order

    def _need(s, n):
        if n < 0 or s.p + n > len(s.b):
            raise ValueError("read past end")

    def u32(s):
        s._need(4)
        v = struct.unpack_from(s.o + "I", s.b, s.p)[0]
        s.p += 4
        return v

    def u8(s):
        s._need(1)
        v = s.b[s.p]
        s.p += 1
        return v

    def boolean(s):
        v = s.u8()
        if v > 1:
            raise ValueError("bool %d" % v)
        return v

    def floats(s, n):
        s._need(4 * n)
        v = struct.unpack_from(s.o + "%df" % n, s.b, s.p)
        s.p += 4 * n
        return v

    def skip(s, n):
        s._need(n)
        s.p += n

    def count(s, item_bytes=1):
        """u32 element count, rejected when the elements cannot fit."""
        n = s.u32()
        if n * item_bytes > len(s.b) - s.p:
            raise ValueError("count %d" % n)
        return n

    def string(s):
        n = s.count()
        if n > 65536:  # merged-mesh names run to a few KB (TwilightMansion_Attic)
            raise ValueError("string %d" % n)
        v = s.b[s.p : s.p + n]
        s.p += n
        return v.split(b"\0", 1)[0].decode("latin1")


def _mr_meshbuffer(r):
    """MeshBuffer header, FUN_004336ec."""
    # two corners of the buffer's box (minimum, then maximum), not centre / half extent
    m = {"bbox_min": r.floats(3), "bbox_max": r.floats(3)}
    m["has_color"] = r.u8()  # source flag bit 1 (builder 0x0043426c)
    m["has_alpha"] = r.u8()  # source flag bit 2
    if r.boolean():  # FUN_0042f9c1: cloth / physics side arrays
        r.u8()
        for sz in (12, 2, 12, 2, 2):
            r.skip(r.count(sz) * sz)
    m["vertex_flags"], m["vertex_count"], m["format"] = r.u32(), r.u32(), r.u32()
    m["index_flags"], m["index_bytes"], m["ix"] = r.u32(), r.u32(), r.u32()
    # the last u32 is the primitive type: 0 triangle strip, 1 triangle list (table 0xc7f398)
    m["primitive_type"] = m["ix"]
    if m["format"] >= len(VERTEX_STRIDES) or m["index_bytes"] % 2:
        raise ValueError("vertex format %d" % m["format"])
    return m


#: MeshBuffer primitive type -> name in <model>.model.json (engine table 0xc7f398 maps
#: 0..5 to D3D 5, 4, 6, 1, 2, 3; only 0 and 1 occur in the shipped models)
PRIMITIVE_NAMES = {0: "triangle_strip", 1: "triangle_list"}


def index_triangles(idx, primitive_type):
    """Triangles of an index run: 1 = list, 0 = strip (engine 0x431206: (i, i+1, i+2)
    for even i, (i+2, i+1, i) for odd i); the toolkit leaves out a strip triangle that
    repeats an index."""
    if primitive_type == 1:
        return [idx[i : i + 3] for i in range(0, len(idx) - 2, 3)]
    if primitive_type != 0:
        raise ValueError("primitive type %d" % primitive_type)
    out = []
    for i in range(len(idx) - 2):
        t = (idx[i], idx[i + 1], idx[i + 2]) if i % 2 == 0 else (idx[i + 2], idx[i + 1], idx[i])
        if len(set(t)) == 3:
            out.append(t)
    return out


def _mr_part(r, pi, buffers, layout="part2"):
    """Part / pivot node, FUN_00545927; submesh records FUN_00542541.  layout
    "part1": the submesh record of the stand-alone Part 1 build, which has no
    fifth flag byte (MODEL_LAYOUTS)."""
    P = {"pos": r.floats(3), "quat": r.floats(4), "name": r.string()}
    P["f1"], P["parent"] = r.u32(), r.u32()
    # f1 = index into the model's pivot-book list (0x53e987; model+0x9c)
    P["pivotbook_index"] = P["f1"]
    P["lods"] = []
    for li in range(r.count(4)):
        lod = []
        for si in range(r.count(20)):
            sm = {"name": r.string()}
            sm["tex_index"] = [r.u32() for _ in range(r.count(4))]
            sm["b24"], inline, sm["u28"] = r.boolean(), r.boolean(), r.u32()
            sm["hidden"] = sm["b24"]  # 0x4b3886: a set flag skips the submesh
            # u28 = shadow-hull group id ("shadowID", builder 0x544ae4); 0 = in no hull
            sm["shadow_id"] = sm["u28"]
            sm["dynamic_copy"] = r.boolean()
            sm["no_defer"] = r.boolean() if layout == "part2" else None
            # the fifth bool is "the buffer has a cloth mesh" (writer 0x53f736)
            sm["has_cloth_mesh"] = sm["no_defer"]
            if inline:  # FUN_00433ef4 inline bulk: never seen in shipped data
                raise ValueError("inline mesh buffer")
            mb = _mr_meshbuffer(r)
            r.skip(r.count())  # cooked physics blob
            sm.update(mb, kind="render", part=pi, lod=li)
            lod.append(sm)
            buffers.append(sm)
        P["lods"].append(lod)
    P["shadow"] = []
    for _ in range(r.count(4)):
        for _ in range(r.count(30)):
            fc, cs = r.boolean(), r.u32()
            mb = _mr_meshbuffer(r)
            mb.update(kind="shadow", part=pi, lod=None, name="", tex_index=[])
            # 0x544ae4: (0, -1) merged hull; (1, i) hull of cloth submesh i
            mb["from_cloth"] = bool(fc)
            mb["cloth_submesh"] = None if cs == 0xFFFFFFFF else cs
            P["shadow"].append(mb)
            buffers.append(mb)
    P["occluder"] = P["proxy"] = None
    if r.boolean():
        # the part's OCCLUDER mesh for the engine's occlusion culling (0x545927 ->
        # FUN_0053f9a5 "... not supported for occluder"); "proxy" is the old name
        mb = _mr_meshbuffer(r)
        mb.update(kind="occluder", part=pi, lod=None, name="", tex_index=[])
        P["occluder"] = P["proxy"] = mb
        buffers.append(mb)
    P["lists_offset"] = r.p  # the two volume lists + the particle-surface list
    for _ in range(2):  # collision volumes (FUN_00524b23) + cooked blob
        for _ in range(r.count(8)):
            t = r.u32()
            r.u32()
            if t in _VOLUME_FLOATS:
                r.floats(_VOLUME_FLOATS[t])
            elif t in (2, 4):
                r.u32()
                r.skip(r.count(12) * 12)
                r.skip(r.count(4) * 4)
            else:
                raise ValueError("volume type %d" % t)
            r.floats(7)
            r.skip(r.count())
    P["surface_count"] = r.count(12)  # MeshParticleData list (FUN_00561d1c)
    for _ in range(P["surface_count"]):
        r.skip(r.count(20) * 20)
        r.skip(r.count(12) * 12)
        r.skip(r.count(4) * 4)
    return P


#: the two ModelRes header layouts.  "part2": Part 2 on every platform and the
#: PS3 Part 1 rebuild.  "part1": the stand-alone Part 1 build (PC, Xbox 360) --
#: the same record stream except that (a) a submesh record has no fifth flag
#: byte (its reader, Xbox 360 Part 1 image 0x828bccc0, reads 1, 1, 4, 1 bytes
#: before the MeshBuffer where Part 2's 0x542541 / 0x828fea68 reads 1, 1, 4, 1, 1)
#: and (b) every property blob holds untyped records (kapow_props.read_records).
MODEL_LAYOUTS = ("part2", "part1")


def model_header_layout_hint(header, order="<"):
    """Which MODEL_LAYOUTS entry the header's own property bag points at:
    "part1" when its records are untyped, "part2" when typed, None when the bag
    does not read (nothing else in the header states the build)."""
    try:
        tlen = struct.unpack_from(order + "I", header, 0)[0]
        if not 2 <= tlen <= 64:
            return None
        p = 4 + tlen
        ndw = struct.unpack_from(order + "I", header, p)[0]
    except struct.error:
        return None
    got = _kprops().read_records(header, p + 4, p + 4 + 4 * ndw, order)
    if got is None:
        return None
    return "part1" if got[0] == "untyped" else "part2"


def _parse_model_header_as(header, order, layout):
    try:
        r = _Rd(header, order)
        M = {"type": r.string()}
        r.skip(r.count(4) * 4)  # property bag: dword count (FUN_00511f96)
        r.u32()
        M["has_skeleton"] = r.boolean()
        # 0x53db65: highest bone index used by part 0 / LOD 0, + 1
        v = r.u32()
        M["skinned_bone_count"] = None if v == 0xFFFFFFFF else v
        M["has_cloth"] = r.boolean()
        r.skip(r.count(32) * 32)
        r.skip(r.count(4) * 4)
        # the model's box as its minimum and maximum corner (it is a little larger than
        # the boxes of the buffers); in no output file
        M["bbox_min"], M["bbox_max"] = r.floats(3), r.floats(3)
        tex = [(r.boolean(), r.string()) for _ in range(r.count(5))]
        M["texture_flags"] = [t[0] for t in tex]
        M["textures"] = [t[1] for t in tex]
        M["pivotbooks"] = [r.string() for _ in range(r.count(4))]
        buffers = []
        M["parts"] = [_mr_part(r, pi, buffers, layout) for pi in range(r.count(40))]
        M["buffers"] = buffers
        M["end"] = r.p  # physics / cloth / animation-event tail follows
        M["layout"] = layout
    except (ValueError, struct.error, IndexError):
        return None
    return M


def parse_model_header(header, order="<", layout=None):
    """ModelRes header -> dict, or None when the blob follows neither header
    layout (truncated data, a foreign blob): callers then fall back to the
    descriptor scan.

    {"type", "textures": [path], "texture_flags", "pivotbooks", "bbox_min",
     "bbox_max", "parts": [{name, pos, quat, f1, parent, lods: [[submesh]],
     shadow: [buf], occluder: buf|None (also under the old key "proxy"),
     lists_offset, surface_count (see model_surfaces)}],
     "buffers": [buf in STREAM order], "end", "layout"}
    Every buf has kind ('render' | 'shadow' | 'occluder'), part, lod, name,
    tex_index, format, vertex_count, index_bytes, has_color, has_alpha, bbox_min, bbox_max
    (the two corners of the box; these keys are in no output file).

    "layout" is the MODEL_LAYOUTS entry the header was read with.  It is taken
    from the header itself, never from a path: the layout the property bag
    points at (model_header_layout_hint) is tried first, then the other one;
    `layout` restricts the read to one.  A header without any submesh reads the
    same either way and keeps the bag's answer."""
    if asset_base_class(asset_class(header, order)).lower() not in ("modelres", "model"):
        return None
    if layout is not None:
        return _parse_model_header_as(header, order, layout)
    hint = model_header_layout_hint(header, order) or MODEL_LAYOUTS[0]
    for lay in (hint,) + tuple(x for x in MODEL_LAYOUTS if x != hint):
        M = _parse_model_header_as(header, order, lay)
        if M is not None:
            return M
    return None


def model_stream_layout(model, stream, order="<"):
    """Locate every buffer of `model` (parse_model_header) in the stream blob.
    Adds vb / ib / stride / clusters=(offset, count) to each buffer and returns
    the buffer list, or None unless the layout consumes the stream EXACTLY.
    order ">" (console files): the console vertex strides and the console sizes
    of the cluster and list records (_STREAM_RECORDS)."""
    p, n = 0, len(stream)
    strides = vertex_strides(order)
    cluster, item = _STREAM_RECORDS[">" if order == ">" else "<"]
    try:
        for b in model["buffers"]:
            b["stride"] = strides[b["format"]]
            b["vb"] = p
            p += b["vertex_count"] * b["stride"]
            b["ib"] = p
            p += b["index_bytes"]
            (nc,) = struct.unpack_from(order + "I", stream, p)
            b["clusters"] = (p + 4, nc)
            p += 4 + nc * cluster
            (nl,) = struct.unpack_from(order + "I", stream, p)
            p += 4
            for _ in range(nl):
                p += 8 + struct.unpack_from(order + "I", stream, p + 4)[0] * item
            if p >= n:
                return None
            if stream[p] > 1:
                return None
            p += 1 + (b["vertex_count"] * 8 if stream[p] else 0)
            if p > n:
                return None
    except struct.error:
        return None
    return model["buffers"] if p == n else None


def _material_stem(path):
    return path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]


def check_lod(lod):
    """`lod` as decode_model / select_model_buffers accept it: 'all' / None or an
    int >= 0.  ValueError otherwise (a negative LOD used to select no buffer and
    silently drop the model onto the legacy scan)."""
    if lod in (None, "all"):
        return lod
    if isinstance(lod, bool) or not isinstance(lod, int) or lod < 0:
        raise ValueError("model LOD must be a whole number >= 0 or 'all', not %r" % (lod,))
    return lod


def _model_lod_arg(v):
    import argparse

    try:
        return check_lod(v if v == "all" else int(v))
    except ValueError:
        raise argparse.ArgumentTypeError("expected a whole number >= 0 or 'all', got %r" % v)


def language_slot(v):
    """Language slot 0..5 of a slot number, a LANGUAGE name ('german'), an engine
    code ('de', 'uk', 'dk') or an ISO code ('en', 'da'), case-insensitive; None
    when `v` is none of them."""
    t = str(v).strip().lower()
    for i, names in enumerate(BLOCK_LANGUAGE_NAMES):
        if t in [n.lower() for n in names]:
            return i
    try:
        n = int(t)
    except ValueError:
        return None
    return n if 0 <= n < BLOCK_LANGUAGES else None


def _language_arg(v):
    import argparse

    n = language_slot(v)
    if n is None:
        raise argparse.ArgumentTypeError(
            "expected a language slot 0..%d or a language name / code (%s), got %r"
            % (
                BLOCK_LANGUAGES - 1,
                ", ".join("%s|%s" % (a.lower(), b) for a, b, _c in BLOCK_LANGUAGE_NAMES),
                v,
            )
        )
    return n


#: buffer kinds of a model: "render" (drawn), "shadow" (stencil shadow-volume hull,
#: vertex formats 9 / 10, REShadowVolume), "occluder" (occlusion-culling mesh).
#: Only "render" is ever exported as visible geometry.
BUFFER_KINDS = ("render", "shadow", "occluder")
BUFFER_KIND_ALIASES = {"proxy": "occluder", "shadow_hull": "shadow"}
#: what a non-render kind is (decode_model_mesh submesh "role")
BUFFER_ROLES = {"render": "render", "shadow": "shadow_hull", "occluder": "occluder"}
_LOD_PAIRS = ("01", "12", "23", "34", "45")


def model_property_bag(header, order="<"):
    """The property bag at the start of a ModelRes header -- `[u32 len][type
    name][u32 dwords][records]` (reader 0x511f96) -- in either record layout ->
    {"record_layout": "typed" | "untyped", "records": kapow_props.read_records
    tuples, "properties": {name: value}} or None when the records do not read
    exactly to the stored dword count.  A property whose type is not known is
    listed as {"hex": ...}."""
    kp = _kprops()
    try:
        tlen = struct.unpack_from(order + "I", header, 0)[0]
        if not 2 <= tlen <= 64:
            return None
        p = 4 + tlen
        ndw = struct.unpack_from(order + "I", header, p)[0]
    except struct.error:
        return None
    got = kp.read_records(header, p + 4, p + 4 + 4 * ndw, order)
    if got is None:
        return None
    names, ut, props = kp.namedict(), kp.untyped_types(), {}
    for _o, key, th, q, k in got[1]:
        if th is None:
            tn = ut.get(key)
        else:
            tn = "id" if th == kp.T_UNIQUE_ID else kp.TYPES.get(th)
        val = kp.record_value(tn, header, q, k, order)
        if isinstance(val, float):
            val = round(val, 6)
        elif val is None:
            val = {"hex": header[q : q + 4 * k].hex()}
        props.setdefault(names.get(key) or "%08x" % key, val)
    return {"record_layout": got[0], "records": got[1], "properties": props}


def model_lod_info(header, order="<"):
    """LOD switch distances of a ModelRes header's property bag (lodDistance01..45,
    lodFadeIn.., lodFadeOut..; ModelRes::vfunc_06 0x53ef10) -> {"lods": [{"lod": i,
    "max_distance", "fade_in", "fade_out"}], "store_lowest_lod_in_header"} or None.

    The engine (FUN_0053a317) draws LOD i while the scaled camera distance is below
    max_distance[i]; LOD i-1 keeps fading out for fade_out[i-1] metres past its own
    limit and LOD i+1 fades in over the last fade_in[i] metres (alpha blended, no
    hysteresis); past the last LOD's distance the model is not drawn.  Distance =
    distance to the bounds minus the bounding radius, times the node's
    geometryLodFactor and the level's globalGeometryLodFactor."""
    try:
        tlen = struct.unpack_from(order + "I", header, 0)[0]
        p = 4 + tlen + 4
        end = _propbag_end(header, order)
        num = _name_hash("number")
        want = {}
        for pair in _LOD_PAIRS:
            for key in ("lodDistance", "lodFadeIn", "lodFadeOut"):
                want[_name_hash(key + pair)] = (key, pair)
        want[_name_hash("storeLowestLODInHeader")] = ("store", "")
        got = {}
        bag = model_property_bag(header, order)
        if bag is not None:
            # exact walk of the bag in either record layout.  (The fixed 20-byte
            # stride below loses its place on a string longer than one dword: a
            # model with an `animation` path -- 22 in PC Part 2 -- had no LODs.)
            num_ok = (None, num)
            for _o, lo, th, q, k in bag["records"]:
                if lo in want and k == 1:
                    key = want[lo]
                    if key[0] == "store":
                        got[key] = bool(struct.unpack_from(order + "I", header, q)[0])
                    elif th in num_ok:
                        got[key] = struct.unpack_from(order + "f", header, q)[0]
            p = end
        while p + 20 <= end:
            _salt, lo, hi, tag, val = struct.unpack_from(order + "5I", header, p)
            if lo in want:
                key = want[lo]
                if key[0] == "store":
                    got[key] = bool(val)
                elif hi == num:
                    got[key] = struct.unpack_from(order + "f", header, p + 16)[0]
            p += 24 if tag == 2 else 20
    except (struct.error, IndexError):
        return None
    if not any(k[0] == "lodDistance" for k in got):
        return None
    lods = []
    for i, pair in enumerate(_LOD_PAIRS):
        if ("lodDistance", pair) not in got:
            break
        lods.append(
            {
                "lod": i,
                "max_distance": round(got[("lodDistance", pair)], 4),
                "fade_in": round(got.get(("lodFadeIn", pair), 0.0), 4),
                "fade_out": round(got.get(("lodFadeOut", pair), 0.0), 4),
            }
        )
    return {"lods": lods, "store_lowest_lod_in_header": got.get(("store", ""))}


def model_surfaces(header, model=None, order="<"):
    """Particle emission surfaces of a header-decoded model, mesh nodes included
    (node+0x64 list of MeshParticleData, reader 0x561d1c; consumer SurfaceSpawner
    0x54fc6b / 0x54decc) -> [{"part", "node", "surface", ... the dict of
    skeleton_records.parse_volume_lists: class, tris [{normal, area_weight,
    material_id}], verts, indices, weight_sum, weight_is_area}] in file order,
    or None when the header does not follow the Part 2 layout."""
    M = model or parse_model_header(header, order)
    if M is None:
        return None
    try:
        import skeleton_records as _sr
    except ImportError:
        _d = os.path.dirname(os.path.abspath(__file__))
        if _d not in sys.path:
            sys.path.append(_d)  # append, never insert(0)
        import skeleton_records as _sr
    out = []
    for pi, P in enumerate(M["parts"]):
        if not P.get("surface_count"):
            continue
        try:
            _lists, surfaces, _end = _sr.parse_volume_lists(header, P["lists_offset"], order)
        except (ValueError, struct.error):
            return None
        for si, s in enumerate(surfaces):
            out.append(dict(s, part=pi, node=P["name"], surface=si))
    return out


def _surface_summary(s):
    """One model_surfaces() element as it is written into <name>.model.json."""
    ids = {}
    for t in s["tris"]:
        ids[t["material_id"]] = ids.get(t["material_id"], 0) + 1
    return {
        "node": s["node"],
        "part": s["part"],
        "class": s["class"],
        "triangles": len(s["tris"]),
        "vertices": int(len(s["verts"])),
        "material_ids": {str(k): ids[k] for k in sorted(ids)},
        "weight_sum": round(s["weight_sum"], 6),
        "weight_is_area": s["weight_is_area"],
        # every weight exactly 1.0, whatever the triangle's area
        **({"weight_is_unit": True} if s.get("weight_is_unit") else {}),
    }


def _parts_summary(M):
    """The parts of a parse_model_header dict as <name>.model.json lists them."""
    xfs = model_part_transforms(M)
    out = []
    for pi, P in enumerate(M["parts"]):
        par = P["parent"]
        out.append(
            {
                "name": P["name"],
                "parent": par if 0 <= par < len(M["parts"]) else -1,
                "pos": [round(float(c), 6) for c in P["pos"]],
                "quat": [round(float(c), 6) for c in P["quat"]],
                "moved": xfs[pi] is not None,
                "pivotbook_index": P["f1"],
                "submeshes": [
                    {
                        "lod": li,
                        "name": sm["name"],
                        "shadow_id": sm["u28"],
                        "in_shadow_hull": bool(sm["u28"] > 0 and not sm["b24"]),
                        "primitive": PRIMITIVE_NAMES.get(
                            sm.get("primitive_type"), "type %s" % sm.get("primitive_type")
                        ),
                    }
                    for li, lod in enumerate(P["lods"])
                    for sm in lod
                ],
                "shadow_hulls": len(P["shadow"]),
                "occluder": bool(P.get("occluder")),
            }
        )
    return out


PARTS_NOTE = (
    "parts: the model's nodes in file order.  pos / quat are the part's local transform as "
    "stored (engine numbers; a vector rotates as conj(q)·v·q), parent -1 = none; `moved` = "
    "the chain up to the root is not the identity.  Vertices are stored part-local; the "
    "OBJ / GLB hold them in model space when part_transforms_applied is true.  "
    "pivotbook_index = index into the model's pivot-book list (0x53e987).  shadow_id = the "
    "submesh's shadow-hull group (builder 0x544ae4): submeshes of one part and LOD with "
    "the same id above 0 and the b24 flag clear are merged into one stencil-shadow hull "
    "(in_shadow_hull); 0 = in no hull.  primitive = how the buffer's indices are read: "
    "triangle_list, or triangle_strip (engine 0x431206; the OBJ / GLB hold the strip's "
    "triangles)"
)


def model_meta(header, model=None, order="<"):
    """Sidecar content of a header-decoded model (decode_model writes it as
    <name>.model.json): LOD count and switch distances, the buffers that are
    NOT exported -- shadow hulls and occluders -- so their presence is on
    record, and (only on a model that has any) its particle emission surfaces.
    A header in the stand-alone Part 1 layout (MODEL_LAYOUTS) carries
    "header_layout": "part1"; the key is absent for the Part 2 layout."""
    M = model or parse_model_header(header, order)
    if M is None:
        return None
    surfaces = model_surfaces(header, M, order) or []
    nl = max([len(P["lods"]) for P in M["parts"]] or [0])
    info = model_lod_info(header, order) or {"lods": []}
    # the stand-alone Part 1 header says so; a Part 2 sidecar is unchanged
    layout = {"header_layout": "part1"} if M.get("layout") == "part1" else {}
    return {
        "format": "watchmen-model-meta/1",
        **layout,
        "lod_count": nl,
        "lods": info["lods"][: max(nl, 1)],
        "lod_note": "LOD i is drawn below max_distance (metres, scaled by the node and "
        "level LOD factors); it fades out over fade_out past it; nothing is drawn past "
        "the last LOD's distance",
        "not_exported": {
            "shadow_hull": sum(len(P["shadow"]) for P in M["parts"]),
            "occluder": sum(1 for P in M["parts"] if P.get("occluder")),
        },
        "parts": _parts_summary(M),
        "parts_note": PARTS_NOTE,
        **(
            {
                "particle_surfaces": [_surface_summary(s) for s in surfaces],
                "particle_surface_note": "MeshParticleData lists of the nodes (0x561d1c): "
                "the triangles a SurfaceSpawner may emit from.  A triangle is used when its "
                "material_id equals the spawner's materialId (-1 on the spawner: 0x54e23e), "
                "its normal rotated by the Model node has world Y >= faceCullLimit and its "
                "centre lies within the spawner radius in XZ; the budget is "
                "trunc(particleAmount x sum of weights) (0x553c41).  weight = the triangle's "
                "area in m^2 where weight_is_area is true (data); 1.0 per triangle, whatever "
                "the area, where weight_is_unit is true (2 Part 2 and 17 Part 1 surfaces, "
                "2-292 triangles; 8 on nodes named like splash emitter / surface, 2 on other "
                "named nodes, 7 on the unnamed root; why is not established).  Stored normals "
                "are unit length and opposite to the index winding; on Rorschach's arm "
                "surfaces they are 21-36 degrees off the face normal.  The geometry itself is "
                "not exported",
            }
            if surfaces
            else {}
        ),
    }


def model_meta_reduced(header, order="<"):
    """Sidecar content of a model whose header follows NEITHER layout of
    parse_model_header (none in the six shipped sets since the stand-alone
    Part 1 layout is read; geometry comes from the descriptor scan): what the
    property bag at the start of the header states -- the LOD switch distances
    and the bag itself -- with the parts that need the full header layout named
    under "not_decoded" instead of being left out silently.  None when the
    property bag does not read exactly (nothing is written then)."""
    bag = model_property_bag(header, order)
    if bag is None:
        return None
    info = model_lod_info(header, order) or {"lods": []}
    return {
        "format": "watchmen-model-meta/1",
        "header_decoded": False,
        "record_layout": bag["record_layout"],
        "lod_count": None,
        "lods": info["lods"],
        "lod_note": "LOD i is drawn below max_distance (metres, scaled by the node and "
        "level LOD factors); it fades out over fade_out past it; nothing is drawn past "
        "the last LOD's distance.  These are the header's five distance slots: how many "
        "LODs the model really has is not decoded for this header layout",
        "properties": bag["properties"],
        "not_decoded": [
            "lod_count",
            "not_exported.shadow_hull",
            "not_exported.occluder",
            "particle_surfaces",
        ],
        "not_decoded_note": "this header follows neither known ModelRes layout (Part 2, "
        "stand-alone Part 1), so the engine-exact header path does not read it; the mesh "
        "was found by the descriptor scan",
    }


def model_meta_scanned(header, order="<"):
    """Sidecar of a model whose MESH came from the descriptor scan (the
    header-driven path did not apply: decode_model).  Where the header itself
    follows one of the two header layouts in this byte order it is the full
    model_meta() with "header_decoded": true; otherwise model_meta_reduced().
    "mesh_source": "descriptor scan" marks both."""
    M = parse_model_header(header, order)
    meta = model_meta(header, M, order) if M is not None else None
    if meta is not None:
        meta["header_decoded"] = True
        # the scan does not know which part a buffer belongs to
        meta["part_transforms_applied"] = False
    else:
        meta = model_meta_reduced(header, order)
    if meta is not None:
        meta["mesh_source"] = "descriptor scan"
    return meta


def select_model_buffers(model, lod=0, kinds=("render",)):
    """Buffers of the requested kinds (BUFFER_KINDS; "proxy" is accepted for
    "occluder"), in stream order.  `lod`: an int picks that LOD of every part
    (clamped to the part's last LOD); 'all' / None keeps all."""
    lod = check_lod(lod)
    kinds = tuple(BUFFER_KIND_ALIASES.get(k, k) for k in kinds)
    out = []
    for b in model["buffers"]:
        if b["kind"] not in kinds:
            continue
        if b["kind"] == "render" and lod not in (None, "all"):
            nl = len(model["parts"][b["part"]]["lods"])
            if b["lod"] != min(int(lod), nl - 1):
                continue
        out.append(b)
    return out


def _part_local_matrix(pos, quat):
    """Engine local transform of a part as (3x3 rows, translation): a vector
    rotates as conj(q)·v·q (q = x, y, z, w as stored), then pos is added."""
    x, y, z, w = (float(c) for c in quat)
    m = (
        (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)),
        (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)),
        (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)),
    )
    return m, tuple(float(c) for c in pos)


def _part_is_identity(P):
    q = tuple(P["quat"])
    return tuple(P["pos"]) == (0.0, 0.0, 0.0) and q[:3] == (0.0, 0.0, 0.0) and abs(q[3]) == 1.0


def model_part_transforms(model):
    """Model-space transform of every part of a parse_model_header dict:
    [None | (3x3 rows, translation)], None where the whole chain is identity.

    The vertices of a buffer are stored in the space of its part (measured: the
    union of the full-detail submesh boxes equals the model box on every model
    with a moved render part only when each part's vertices are transformed by
    v' = conj(q)·v·q + pos, the part first and then every parent up to parent
    0xFFFFFFFF).  A parent index that is out of range or closes a loop ends the
    chain.  The decoders do not apply it to skinned buffers (a format with
    joints), which the bone palette places; no shipped model has one in a moved
    part."""
    parts = model["parts"]
    out = []
    for pi in range(len(parts)):
        chain, seen, k = [], set(), pi
        while 0 <= k < len(parts) and k not in seen:
            seen.add(k)
            chain.append(parts[k])
            k = parts[k]["parent"]
        if all(_part_is_identity(P) for P in chain):
            out.append(None)
            continue
        M = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        t = (0.0, 0.0, 0.0)
        for P in chain:  # the part itself, then its parents
            m, p = _part_local_matrix(P["pos"], P["quat"])
            M = tuple(
                tuple(sum(m[i][k] * M[k][j] for k in range(3)) for j in range(3)) for i in range(3)
            )
            t = tuple(sum(m[i][k] * t[k] for k in range(3)) + p[i] for i in range(3))
        out.append((M, t))
    return out


def apply_part_transform(xf, vectors, point=True):
    """`vectors` [(x, y, z)] through one model_part_transforms entry: rotated,
    and translated when `point`.  None (identity chain) returns the input."""
    if xf is None or vectors is None:
        return vectors
    M, t = xf
    if not point:
        t = (0.0, 0.0, 0.0)
    (a, b, c), (d, e, f), (g, h, i) = M
    return [
        (a * x + b * y + c * z + t[0], d * x + e * y + f * z + t[1], g * x + h * y + i * z + t[2])
        for x, y, z in vectors
    ]


def _dec1110_array(u):
    """_dec1110 for an array of packed u32 -> (N,3) float32."""
    u = np.asarray(u, np.uint32).astype(np.int64)
    x, y, z = u & 0x7FF, (u >> 11) & 0x7FF, (u >> 22) & 0x3FF
    x = np.where(x >= 0x400, x - 0x800, x) / 1023.0
    y = np.where(y >= 0x400, y - 0x800, y) / 1023.0
    z = np.where(z >= 0x200, z - 0x400, z) / 511.0
    return np.stack([x, y, z], 1).astype(np.float32)


#: colour byte order per console.  Read from code: the Xbox 360 vertex
#: declaration of the 44-byte format (0x82236078) gives COLOR 0 at offset 16 as
#: D3DDECLTYPE_D3DCOLOR (0x182886; a big-endian A,R,G,B dword), the PS3 format
#: table (0x01821f48, 12-byte elements read by 0x001538e8) gives attribute 3 of
#: formats 5 and 6 at offset 16 as four unsigned bytes (type 4; R,G,B,A in
#: memory order).
#: Measured: with these orders every colour of the 71 models the alpha rule
#: leaves open equals the PC copy exactly.
CONSOLE_COLOR_ORDERS = {"x360": "argb", "ps3": "rgba"}
#: the console of the source being read ("x360" / "ps3" / None): set by
#: set_console_platform(); $WATCHMEN_CONSOLE overrides it (console_platform)
CONSOLE_PLATFORM = None
_PLATFORM_DIRS = {"derived_x360": "x360", "derived_ps3": "ps3"}
_PLATFORM_CACHE = {}


def console_platform_of(path):
    """ "x360" / "ps3" when a path names the console's derived root (a block
    path inside a .naz: "derived_ps3/levels/...", or a loose source tree
    ".../derived_x360"), else None."""
    for seg in str(path or "").replace("\\", "/").lower().split("/"):
        if seg in _PLATFORM_DIRS:
            return _PLATFORM_DIRS[seg]
    return None


def set_console_platform(platform):
    """Name the console of the big-endian models decoded from here on ("x360",
    "ps3" or None = not known).  Returns the previous value."""
    global CONSOLE_PLATFORM
    if platform not in (None, "x360", "ps3"):
        raise ValueError("console platform %r: expected 'x360', 'ps3' or None" % (platform,))
    old, CONSOLE_PLATFORM = CONSOLE_PLATFORM, platform
    return old


def console_platform():
    """The console in effect: $WATCHMEN_CONSOLE (x360 / ps3) when set, else what
    set_console_platform() was given, else None."""
    env = os.environ.get("WATCHMEN_CONSOLE", "").strip().lower()
    if env in CONSOLE_COLOR_ORDERS:
        return env
    return CONSOLE_PLATFORM


def detect_console_platform(extract_out=None, naz=None, sample=40):
    """The console of an extract output directory and / or its source, or None
    (PC, or not established).  In this order:
      1. $WATCHMEN_CONSOLE;
      2. the source path, or an entry name of the .naz, naming derived_x360 /
         derived_ps3 (console_platform_of);
      3. a derived_x360 / derived_ps3 directory under <extract_out>/files;
      4. INFERRED from the tree: the colour order the alpha rule
         (console_color_order) gives on the first models under
         <extract_out>/extracted that decide it (at most `sample` big-endian
         models are read; they must agree)."""
    env = os.environ.get("WATCHMEN_CONSOLE", "").strip().lower()
    if env in CONSOLE_COLOR_ORDERS:
        return env
    if naz:
        p = console_platform_of(naz)
        if p is None and os.path.isfile(str(naz)):
            try:
                for e in naz_entries(naz):
                    p = console_platform_of(e.name)
                    if p:
                        break
            except Exception:
                p = None
        if p:
            return p
    if not extract_out:
        return None
    try:
        for n in sorted(os.listdir(os.path.join(str(extract_out), "files"))):
            if n.lower() in _PLATFORM_DIRS:
                return _PLATFORM_DIRS[n.lower()]
    except OSError:
        pass
    seen = set()
    n = 0
    root = os.path.join(str(extract_out), "extracted")
    for dp, dns, fns in os.walk(root):
        dns.sort(key=lambda x: (x.lower(), x))
        for f in sorted(fns, key=lambda x: (x.lower(), x)):
            if not f.endswith(".model") or n >= sample:
                continue
            try:
                with open(os.path.join(dp, f), "rb") as fh:
                    mh = fh.read()
                if header_order(mh) != ">":
                    if header_order(mh) == "<":
                        return None  # a PC tree
                    continue
                with open(os.path.join(dp, f + ".stream"), "rb") as fh:
                    ms = fh.read()
                M = parse_model_header(mh, ">")
                if M is None or model_stream_layout(M, ms, ">") is None:
                    continue
            except (OSError, ValueError, struct.error, IndexError):
                continue
            n += 1
            co = _console_color_order_inferred(ms, M["buffers"])
            if co:
                seen.add(co)
        if n >= sample or len(seen) > 1:
            break
    if len(seen) == 1:
        return {v: k for k, v in CONSOLE_COLOR_ORDERS.items()}[seen.pop()]
    return None


def console_platform_for(path):
    """console_platform(), else detect_console_platform() of the extract output
    directory `path` lies in (the parent of its `extracted` ancestor; cached per
    directory), else None."""
    p = console_platform()
    if p or not path:
        return p
    d = os.path.abspath(str(path))
    while True:
        parent = os.path.dirname(d)
        if parent == d:
            return None
        if os.path.basename(d).lower() == "extracted":
            break
        d = parent
    if parent not in _PLATFORM_CACHE:
        if len(_PLATFORM_CACHE) > 64:
            _PLATFORM_CACHE.clear()
        _PLATFORM_CACHE[parent] = detect_console_platform(parent)
    return _PLATFORM_CACHE[parent]


def _console_color_order_inferred(stream, buffers):
    """The alpha rule of console_color_order: "argb" / "rgba" / None."""
    if not HAVE_IMG:
        return None
    a0 = a3 = True
    n = 0
    for b in buffers:
        lay = CONSOLE_VERTEX_FORMATS.get(b["format"], {})
        if b["kind"] != "render" or "color" not in lay or b.get("has_alpha") or "vb" not in b:
            continue
        nv, st = b["vertex_count"], b["stride"]
        if not nv:
            continue
        c = np.frombuffer(stream, np.uint8, nv * st, b["vb"]).reshape(nv, st)
        n += 1
        a0 = a0 and bool((c[:, lay["color"]] == 255).all())
        a3 = a3 and bool((c[:, lay["color"] + 3] == 255).all())
    if not n or a0 == a3:
        return None
    return "argb" if a0 else "rgba"


def console_color_order(stream, buffers, platform=None, layout=None):
    """Byte order of the vertex colour in a console model's located buffers
    (model_stream_layout): "argb" (Xbox 360), "rgba" (PS3) or None when it is
    not known.

    The order is the console's (CONSOLE_COLOR_ORDERS, read from the two vertex
    format tables), and nothing in a Part 2 model names its console: the Xbox 360
    and PS3 copies of a model differ in the colour bytes, per-build ids and
    writer leftovers only.  So the console comes from outside: `platform`
    ("x360" / "ps3"), else console_platform() -- the extract sets it from the
    block's path (derived_x360 / derived_ps3); detect_console_platform and
    console_platform_for give it for an extract output directory.

    Without a console the order is INFERRED from the data: a buffer whose
    has_alpha flag is clear has alpha 255 on every vertex (true of all 6,419
    such render buffers of PC Part 1 + Part 2), so the byte that is 255
    throughout those buffers is the alpha.  That fails when no render buffer has
    the flag clear, or when both candidate bytes are 255 throughout; then a
    header `layout` (parse_model_header "layout") of "part1" gives "argb": of the
    four console sets only stand-alone Part 1 for Xbox 360 has that layout
    (1,090 of 1,090 headers; PS3 Part 1 has the Part 2 layout).  Else None."""
    p = platform or console_platform()
    if p in CONSOLE_COLOR_ORDERS:
        return CONSOLE_COLOR_ORDERS[p]
    co = _console_color_order_inferred(stream, buffers)
    if co is None and layout == "part1":
        co = CONSOLE_COLOR_ORDERS["x360"]
    return co


def _console_color_white(stream, b):
    """True when every colour byte of a located console buffer is 255: opaque
    white whichever way the four bytes are ordered."""
    lay = CONSOLE_VERTEX_FORMATS.get(b["format"], {})
    if "color" not in lay or not HAVE_IMG:
        return False
    nv, st, c = b["vertex_count"], b["stride"], lay["color"]
    a = np.frombuffer(stream, np.uint8, nv * st, b["vb"]).reshape(nv, st)
    return bool((a[:, c : c + 4] == 255).all())


def console_color_undecoded(stream, buffers, platform=None, layout=None):
    """Render buffers of a located console model whose vertex colours are in use
    (has_color) but cannot be read: the console is not known, the data does not
    decide the colour byte order (console_color_order) and the colours are not
    plain white."""
    if console_color_order(stream, buffers, platform, layout) is not None:
        return []
    return [
        b
        for b in buffers
        if b["kind"] == "render"
        and b["format"] in (5, 6)
        and b.get("has_color")
        and not _console_color_white(stream, b)
    ]


def decode_vertex_attributes(stream, buf, order="<", color_order=None):
    """Numpy views of ONE located buffer (model_stream_layout) beyond what the
    OBJ writer uses.  Keys present depend on the vertex format:
      color      (N,4) uint8 RGBA                       (formats 5, 6)
      tangent    (N,3) float32  = dP/du                 (formats 5, 6)
      bitangent  (N,3) float32  = dP/dv                 (formats 5, 6)
      joints     (N,4) uint8, weights (N,4) float32 raw (formats 6, 10)
    order ">" reads the console layout (CONSOLE_VERTEX_FORMATS) and also gives
      normal     (N,3) float32 as stored (packed, not normalised)
    and gives `color` only with a `color_order` (console_color_order) or when
    every colour byte is 255: the two consoles store it differently, and a guess
    is not written."""
    be = order == ">"
    lay = vertex_formats(order).get(buf["format"])
    if lay is None or not HAVE_IMG:
        return {}
    nv, st = buf["vertex_count"], buf["stride"]
    a = np.frombuffer(stream, np.uint8, nv * st, buf["vb"]).reshape(nv, st)
    hdt = ">f2" if be else "<f2"
    half = lambda off, k: np.ascontiguousarray(a[:, off : off + 2 * k]).view(hdt)
    packed = lambda off: _dec1110_array(np.ascontiguousarray(a[:, off : off + 4]).view(">u4")[:, 0])
    out = {}
    if be:
        out["normal"] = packed(lay["normal"])
    if "color" in lay:
        c = lay["color"]
        if not be:
            sel = [c + 2, c + 1, c, c + 3]
        elif color_order == "argb":
            sel = [c + 1, c + 2, c + 3, c]
        elif color_order == "rgba" or bool((a[:, c : c + 4] == 255).all()):
            sel = [c, c + 1, c + 2, c + 3]
        else:
            sel = None
        if sel is not None:
            out["color"] = np.ascontiguousarray(a[:, sel])
    if "tangent" in lay:
        if be:
            out["tangent"] = packed(lay["tangent"])
            out["bitangent"] = packed(lay["bitangent"])
        else:
            out["tangent"] = half(lay["tangent"], 3).astype(np.float32)
            out["bitangent"] = half(lay["bitangent"], 3).astype(np.float32)
    if "joints" in lay:
        j = lay["joints"]
        sel = [j + 1, j + 2, j + 3, j] if be else [j + 2, j + 1, j, j + 3]
        out["joints"] = np.ascontiguousarray(a[:, sel])
        out["weights"] = half(lay["weights"], 4).astype(np.float32)
    return out


def gltf_tangents(normals, tangents, bitangents, green_up=True):
    """(N,4) float32 glTF TANGENT: unit stored tangent + handedness w.

    The engine shades with N' = x*T + y*B + z*N from the STORED tangent and
    bitangent (DeferredMain2PS; the bitangent is +dP/dv).  glTF rebuilds the
    bitangent as cross(N, T) * w and multiplies it with the texture's green.
    With s = sign(dot(cross(N, T), B)):
      green_up=True  (default) -> w = -s, for the glTF normal texture the GLB
                     writers embed (green inverted, +Y = -v);
      green_up=False -> w = +s, for a texture left in the engine's orientation.
    Rendered against the engine math in three.js on four models: w = -s with the
    inverted-green texture is within 0.5..1.1 degrees (median), w = +s is 2.4..17
    degrees off.  (1.3.0 returned +s; no shipped GLB used it.)"""
    n = np.asarray(normals, np.float32)
    t = np.asarray(tangents, np.float32)
    b = np.asarray(bitangents, np.float32)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    t = np.where(ln > 1e-9, t / np.maximum(ln, 1e-9), np.array([[1.0, 0.0, 0.0]], np.float32))
    w = np.where((np.cross(n, t) * b).sum(1) < 0, -1.0, 1.0).astype(np.float32)
    if green_up:
        w = -w
    return np.concatenate([t, w[:, None]], 1).astype(np.float32)


def decode_model_mesh(header, stream, lod=0, kinds=("render",), order=None, part_space=False):
    """Header-driven mesh decode: PC headers of either layout, and console
    (big-endian) ones.  order: "<" / ">", None = the order the header states.
    Positions, normals, tangent and bitangent are in MODEL space: the stored
    part-local values taken through the part's chain (model_part_transforms;
    measured for render buffers, applied to shadow hulls and occluders by the
    same rule, which is inferred for them).  part_space=True returns them as
    stored.  Each submesh carries "part_moved".
    Returns None when the header path does not apply (use decode_model's scan
    fallback), else
    {"model": parse_model_header dict, "order", "submeshes": [ {name, kind, part,
      lod, format, stride, material (texture stem or None), texture (path or None),
      positions, normals, uvs  (python lists, same values as the OBJ writer gets),
      triangles [(a, b, c)] local indices, vb, ib,
      + decode_vertex_attributes() keys,
      + "restored": ["eyelash_uvs"] on a submesh whose UVs are restored content
        (LASH_RESTORE; not with WATCHMEN_NO_SYNTH)} ]}.
    A console model with vertex colours that cannot be read
    (console_color_undecoded) has no "color" on those submeshes, the has_color /
    has_alpha flags of ALL its buffers are cleared (the stored ones stay under
    has_color_file / has_alpha_file) and the result carries "not_decoded":
    ["COLOR_0"]."""
    if order is None:
        order = header_order(header) or "<"
    if order == ">" and not console_header_decode():
        return None
    M = parse_model_header(header, order)
    if M is None or stream is None or model_stream_layout(M, stream, order) is None:
        return None
    formats = vertex_formats(order)
    lay = M.get("layout")
    corder = console_color_order(stream, M["buffers"], None, lay) if order == ">" else None
    not_decoded = []
    if order == ">" and console_color_undecoded(stream, M["buffers"], None, lay):
        not_decoded.append("COLOR_0")
        for b in M["buffers"]:
            b["has_color_file"], b["has_alpha_file"] = b.get("has_color"), b.get("has_alpha")
            b["has_color"] = b["has_alpha"] = 0
    subs = []
    xfs = [None] * len(M["parts"]) if part_space else model_part_transforms(M)
    for b in select_model_buffers(M, lod, kinds):
        nv, st = b["vertex_count"], b["stride"]
        _restored = []
        verts, norms, uvs = _decode_sub(stream, b["vb"], nv, st, order == ">", _restored)
        # a skinned buffer is placed by its bone palette: left as stored
        xf = None if "joints" in formats.get(b["format"], {}) else xfs[b["part"]]
        verts = apply_part_transform(xf, verts)
        norms = apply_part_transform(xf, norms, point=False)
        if "uv" not in formats.get(b["format"], {}):
            uvs = None
        idx = struct.unpack_from(order + "%dH" % (b["index_bytes"] // 2), stream, b["ib"])
        ti = b["tex_index"][0] if b["tex_index"] else None
        tex = M["textures"][ti] if ti is not None and ti < len(M["textures"]) else None
        d = {
            "name": b["name"],
            "kind": b["kind"],
            "role": BUFFER_ROLES.get(b["kind"], b["kind"]),
            "part": b["part"],
            "lod": b["lod"],
            "format": b["format"],
            "stride": st,
            "vb": b["vb"],
            "ib": b["ib"],
            "texture": tex,
            "material": texture_ref(tex) if tex else None,
            "positions": verts,
            "normals": norms,
            "uvs": uvs,
            "triangles": index_triangles(idx, b.get("primitive_type", 1)),
            "primitive": PRIMITIVE_NAMES.get(b.get("primitive_type", 1)),
        }
        d.update(decode_vertex_attributes(stream, b, order, corder))
        d.pop("normal", None)  # "normals" already holds it, normalised
        d["part_moved"] = xf is not None
        if _restored:
            d["restored"] = _restored
        if xf is not None:
            rot = np.asarray(xf[0], np.float64).T
            for key in ("tangent", "bitangent"):
                if key in d:
                    d[key] = (d[key].astype(np.float64) @ rot).astype(np.float32)
        subs.append(d)
    out = {"model": M, "order": order, "submeshes": subs}
    if not_decoded:
        out["not_decoded"] = not_decoded
    return out


def _header_model_plan(header, stream, lod, order="<"):
    """Render buffers of the requested LOD with exact stream offsets, or None when
    the engine-exact header path does not apply to this model."""
    if order == ">" and not console_header_decode():
        return None
    M = parse_model_header(header, order)
    if M is None or not stream or model_stream_layout(M, stream, order) is None:
        return None
    bufs = [b for b in select_model_buffers(M, lod) if b["format"] in (5, 6)]
    if not bufs:
        return None
    return M, bufs


def _model_skipped(log, out_path, reason):
    """decode_model's "nothing written" result, with the reason in the log."""
    mark = "note:" if reason.startswith("empty stream") else "WARNING:"
    log("      %s model %s: not decoded: %s" % (mark, out_path.name, reason))
    return False


class OutputNames:
    """Which asset names this run has already written, so that a name stored in
    several blocks is written once and never silently overwritten.

    The level blocks repeat their shared assets (Part 2 PC: 8,711 block entries
    are 7,023 names), and the copies are byte-identical in every set measured
    (six sets, 1.4.0: no name has two different header / stream pairs; in Part 1
    the Prison block lists 22 names without the stream its other copies have).
    place() makes the rule explicit instead of relying on that:

    * the first copy keeps the name as stored ("new");
    * a later copy with the same bytes is not written again ("repeat"); it is
      written under the FIRST copy's spelling when only the letter case differs
      (Rubble_RoofTop_02 / Rubble_Rooftop_02), which is what a case-insensitive
      file system did anyway;
    * a copy that brings the stream an earlier one lacked completes it ("fill");
    * a copy with DIFFERENT bytes gets its own name, `<stem>~<block>.<ext>`
      (`~<block>~2` ... if that is taken too), and a log line ("variant") -- the
      earlier file stays as it is.
    Blocks are processed in sorted order, so the result does not depend on the
    archive's entry order.

    `run` (a canonical_names.Run) gives every name its canonical spelling before
    it is placed and records the stored one; without it names stay as stored."""

    def __init__(self, log=None, run=None):
        self._log = log if callable(log) else (lambda *a: None)
        self._run = run
        self._by = {}  # lower-case name -> [variant dict]
        self._taken = set()  # lower-case output names
        self.repeats = 0
        self.case_twins = []  # (spelling skipped, spelling written)
        self.variants = []  # (name as stored, name written, block)

    @staticmethod
    def _digest(header, stream):
        import hashlib

        return (
            hashlib.sha1(header or b"").digest(),
            hashlib.sha1(stream).digest() if stream else None,
        )

    @staticmethod
    def variant_name(name, block, k=1):
        """`dir/Stem.ext` -> `dir/Stem~<block>.ext` (k > 1: `~<block>~<k>`)."""
        head, _, base = name.replace("\\", "/").rpartition("/")
        stem, dot, ext = base.partition(".")
        tag = "".join(c if c.isalnum() or c in "-_" else "_" for c in block.split("/")[-1])
        tag = tag[: -len("_block")] if tag.lower().endswith("_block") else tag
        base = "%s~%s%s%s%s" % (stem, tag or "block", "~%d" % k if k > 1 else "", dot, ext)
        return (head + "/" if _ else "") + base

    def place(self, name, block, header, stream):
        """-> (name to write under, status): "new", "repeat", "fill" or "variant"."""
        stored = name
        if self._run is not None:
            # --names canonical: the table's spelling (noted below, for the copy written)
            name = self._run.name(stored, record=False)
        key = name.replace("\\", "/").lower()
        hd, sd = self._digest(header, stream)
        known = self._by.setdefault(key, [])
        for v in known:
            if v["hd"] != hd or (sd is not None and v["sd"] is not None and v["sd"] != sd):
                continue
            if stored != v["stored"] and stored not in v["twins"]:
                v["twins"].add(stored)
                if stored != v["name"]:
                    self.case_twins.append((stored, v["name"]))
                    if self._run is not None:
                        self._run.twin(stored, v["name"])
            if v["sd"] is None and sd is not None:
                v["sd"] = sd
                return v["name"], "fill"
            self.repeats += 1
            return v["name"], "repeat"
        out, k = name, 1
        if known:
            out = self.variant_name(name, block)
            while out.lower() in self._taken:
                k += 1
                out = self.variant_name(name, block, k)
            self.variants.append((name, out, block))
            self._log(
                "      WARNING: %s is stored with different content in %s than in %s: written as %s"
                % (name, block, known[0]["block"], out)
            )
        self._taken.add(out.lower())
        known.append(dict(hd=hd, sd=sd, name=out, stored=stored, twins=set(), block=block))
        if self._run is not None:
            if name != stored:
                self._run.renamed_as(out, stored)
            if not known[:-1]:
                self._run.wrote(out)  # references in another letter case follow this spelling
        return out, ("variant" if known[:-1] else "new")


def standalone_output_name(names, stem, header, stream):
    """Output name of a standalone `_h_z` / `_s_z` pair (`stem` = its archive path
    without the suffix) through the run's OutputNames -> (name, status).  Two
    pairs with the same base name in different folders used to overwrite each
    other; a copy with different bytes is now written as `<name>~<folder>.<ext>`
    with a WARNING, an identical one is "repeat" (not written again)."""
    stem = stem.replace("\\", "/")
    folder = stem.rpartition("/")[0]
    return names.place(stem.split("/")[-1], folder or stem, header, stream)


#: what the last decode_model call recorded when it was given no `status` dict
MODEL_STATUS = {}


def decode_model(
    header,
    stream,
    out_path,
    tex_index=None,
    log=None,
    order=None,
    lod=0,
    status=None,
    stored_name=None,
):
    """Per-submesh OBJ (+ .mtl linking the diffuse/normal/specular/glossiness maps
    dumped to textures/), each material named by its texture.

    Models are decoded HEADER-DRIVEN (parse_model_header: every buffer offset
    and the texture-list index of each submesh come from the file) on PC and on
    the consoles, in both header layouts.  `lod` picks the level of detail
    written: 0 (default) = the full-detail mesh, an int = that LOD, 'all' = every
    LOD.  Shadow hulls and per-part proxy slabs are never written.  Anything the
    header path rejects (a header of neither layout, a stream its buffers do not
    tile exactly) takes the descriptor scan: strict VB search, then the single-run
    _pick_vb scan.  With --glb, also emits a rigged + textured .glb for skinned
    (stride-56) character models; header-decoded models get NORMAL, TANGENT,
    COLOR_0 (buffers with the has_color flag) and sheet-driven materials in it,
    and rigid models a static .glb, unless _RIG["attrs"] is off.

    Nothing is left out silently.  With --glb, a model that gets NO .glb has
    `"glb": {"written": false, "reason": ...}` in its .model.json, and a scan
    decode that found fewer submeshes than the header lists (or could not pair
    its materials) has "submeshes" under `not_decoded`.  `status` (a dict the
    caller passes) receives the same facts for the run summary: "glb" (True /
    False / None without --glb), "glb_reason", "color_not_decoded", "partial".
    `stored_name`: the archive's spelling of a model written under a canonical
    name (--names canonical); it goes into the .model.json as "stored_name"."""
    if status is None:
        status = MODEL_STATUS  # the last call's facts, for callers that pass none
    status.clear()
    status.update(glb=None, glb_reason=None, color_not_decoded=False, partial=None)
    if tex_index is None:
        tex_index = {}
    if not callable(log):
        log = lambda *a, **k: None
    ho = order or header_order(header)  # auto: the header states its order
    hplan = _header_model_plan(header, stream, lod, ho or "<")
    if hplan:
        order = ho or "<"
    elif order is None:
        order = ho
    if order is None:
        # header without a readable class name: the order with MORE descriptors
        # (a BE model can throw a stray false-positive LE descriptor, so "LE if
        # non-empty" mis-detects those; a tie -- single-submesh models -- stays LE).
        order = (
            ">" if len(find_descriptors(header, ">")) > len(find_descriptors(header, "<")) else "<"
        )
    be = order == ">"
    part_xf = None
    if hplan:
        descs = [(b["vertex_count"], b["stride"], b["index_bytes"]) for b in hplan[1]]
        part_xf = model_part_transforms(hplan[0])
    else:
        descs = find_descriptors(header, order)
    V = []
    N = []
    U = []
    T = []
    subs = []
    have_n = True
    have_u = True
    SKIN_I = []
    SKIN_W = []
    have_skin = True
    rig = _RIG["on"] and _rig_load()
    didx = []  # descriptor index per emitted sub (for submesh_materials pairing)
    restored = []  # restored content in this model (_decode_sub)
    if descs:
        off = 0
        for di, (nv, stride, ib) in enumerate(descs):
            hi = len(stream) - nv * stride - ib
            cand = off
            vbo = hplan[1][di]["vb"] if hplan else None
            while vbo is None and cand <= min(off + 65536, hi):
                if (
                    _sane(struct.unpack_from(order + "f", stream, cand)[0])
                    and _vb_ok(stream, cand, nv, stride, ib, order)
                    and _ib_ok(stream, cand, nv, stride, ib, order)
                ):
                    vbo = cand
                    break
                cand += 1
            if vbo is None:
                # planar-decal fallback (strict scan exhausted)
                cand = off
                while cand <= min(off + 65536, hi):
                    if _sane(struct.unpack_from(order + "f", stream, cand)[0]) and _vb_ok_flat(
                        stream, cand, nv, stride, ib, order
                    ):
                        vbo = cand
                        break
                    cand += 1
            if vbo is None:
                continue
            base = len(V)
            verts, norms, uvs = _decode_sub(stream, vbo, nv, stride, be, restored)
            if part_xf is not None:  # part-local -> model space (not skinned buffers)
                _b = hplan[1][di]
                skinned_fmt = "joints" in vertex_formats(order).get(_b["format"], {})
                xf = None if skinned_fmt else part_xf[_b["part"]]
                verts = apply_part_transform(xf, verts)
                norms = apply_part_transform(xf, norms, point=False)
            if rig:
                # pass the detected byte order (2026-08-17): without it decode_skin
                # used the PC layout, whose stride>=56 gate rejected every console
                # (stride-44) skinned submesh -> no console glb was ever emitted.
                si, sw = _RIG["mod"].decode_skin(stream, vbo, nv, stride, order)
                if si is None:
                    have_skin = False
                else:
                    SKIN_I.append(si)
                    SKIN_W.append(sw)
            tstart = len(T)
            ibo = vbo + nv * stride
            if hplan and hplan[1][di].get("primitive_type", 1) == 0:
                # a triangle strip (engine 0x431206): read as a list it gives wrong faces
                _idx = struct.unpack_from(order + "%dH" % (ib // 2), stream, ibo)
                _tris = index_triangles(_idx, 0)
            else:
                _tris = [
                    struct.unpack_from(order + "3H", stream, ibo + t * 6) for t in range(ib // 6)
                ]
            for a, b, c in _tris:
                if a < nv and b < nv and c < nv and len({a, b, c}) == 3:
                    T.append((base + a, base + b, base + c))
            V.extend(verts)
            if norms is None:
                have_n = False
            else:
                N.extend(norms)
            if uvs is None:
                have_u = False
            else:
                U.extend(uvs)
            subs.append((base, len(V) - base, tstart, len(T) - tstart, stride))
            didx.append(di)
            off = ibo + ib
    if not T:
        if not stream:  # skeleton-only models and a few empty props: nothing to decode
            return _model_skipped(log, out_path, "empty stream: the model has no mesh data")
        pick = _pick_vb(stream)
        if pick is None:
            return _model_skipped(
                log,
                out_path,
                "no vertex buffer found (%d descriptor(s) in the header, %d stream bytes)"
                % (len(descs), len(stream)),
            )
        off, stride, be, nv, idx = pick
        if nv < 8:
            return _model_skipped(log, out_path, "the buffer scan found only %d vertices" % nv)
        verts, norms, uvs = _decode_sub(stream, off, nv, stride, be)
        ntri = len(idx) // 3
        if ntri == 0:
            return _model_skipped(log, out_path, "the buffer scan found no triangles")
        V = verts
        have_n = norms is not None
        have_u = uvs is not None
        N = norms or []
        U = uvs or []
        T = [
            (idx[i], idx[i + 1], idx[i + 2])
            for i in range(0, ntri * 3, 3)
            if len({idx[i], idx[i + 1], idx[i + 2]}) == 3
        ]
        subs = [(0, len(V), 0, len(T), stride)]
        didx = []  # no descriptors -> no per-submesh material records
    if not T:
        return _model_skipped(log, out_path, "every triangle of the scanned buffer is degenerate")
    mats = extract_materials(header)
    materials = None
    if hplan and didx and len(didx) == len(subs):
        # the submesh record carries the index into the model's texture list
        # (FUN_00542541, array at record+0x18)
        tex = hplan[0]["textures"]
        materials = []
        for k in didx:
            ti = hplan[1][k]["tex_index"]
            ok = ti and ti[0] < len(tex)
            materials.append(texture_ref(tex[ti[0]]) if ok else "submesh_%d" % k)
    # Per-submesh materialIndex read from the header records (2026-08-17): positional
    # pairing is WRONG whenever one material covers several submeshes (see the
    # submesh_materials docstring; Rorschach trenchcoat) -- same pattern as
    # char_lib._parts.  Falls back to the old positional logic when the records
    # are unavailable/unparsable (or the _pick_vb path, which has no descriptors).
    if materials is None and mats and didx and len(didx) == len(subs):
        try:
            smat = submesh_materials(header, order)
        except Exception:
            smat = []
        if smat:
            materials = [
                (
                    mats[smat[k][1]]
                    if k < len(smat) and smat[k][1] < len(mats)
                    else (mats[k] if k < len(mats) else "submesh_%d" % k)
                )
                for k in didx
            ]
    if materials is None:
        # material list aligns to submeshes in order; when fewer materials than
        # submeshes, assign what we have and leave the remainder as fallback rather
        # than discarding the whole mapping.
        if len(mats) == len(subs):
            materials = mats
        elif 0 < len(mats) < len(subs):
            materials = list(mats) + ["submesh_%d" % k for k in range(len(mats), len(subs))]
        else:
            materials = ["submesh_%d" % k for k in range(len(subs))]
            if mats:
                status["partial"] = (
                    "the header lists %d texture(s) but the scan gave %d submesh(es) and no "
                    "submesh records: no material assigned, the mesh is likely incomplete"
                    % (len(mats), len(subs))
                )
                # more textures than decoded submeshes and no submesh records to pair
                # them: the buffer scan found fewer buffers than the model has
                # (console Palm_Banana_01 / palm_banana_02: 1 of 3).  Say so.
                log(
                    "      WARNING: model %s: no material assigned: the header lists %d textures (%s)"
                    " but %s gave %d submesh(es) and no submesh records, so the pairing is not"
                    " known; the mesh is likely incomplete"
                    % (
                        out_path.name,
                        len(mats),
                        ", ".join(str(m) for m in mats),
                        "the descriptor scan" if didx else "the single-buffer scan",
                        len(subs),
                    )
                )
    _write_obj_mtl(
        out_path,
        out_path.stem,
        V,
        N if have_n else None,
        U if have_u else None,
        T,
        subs,
        materials,
        tex_index,
        log,
    )
    meta = None  # the .model.json content; written after the GLB, whose fate it records
    if hplan and _materials_mode() == "engine":
        try:
            meta = model_meta(header, hplan[0], order)
            meta["part_transforms_applied"] = True
            if order == ">" and console_color_undecoded(
                stream, hplan[0]["buffers"], None, hplan[0].get("layout")
            ):
                status["color_not_decoded"] = True
                meta["not_decoded"] = ["COLOR_0"]
                meta["not_decoded_note"] = (
                    "vertex colours: Xbox 360 and PS3 store the colour bytes in a different "
                    "order, the console of this model is not known (no derived_x360 / "
                    "derived_ps3 source path, WATCHMEN_CONSOLE not set) and its data does "
                    "not show which (console_color_order)"
                )
                log(
                    "      note: model %s: vertex colours not decoded: the console is not "
                    "known and the colour byte order cannot be told from this model "
                    "(set WATCHMEN_CONSOLE=x360 or ps3)" % out_path.name
                )
        except (TypeError, ValueError) as ex:
            meta = None
            log("      ! model meta %s: %s" % (out_path.stem, ex))
    elif _materials_mode() == "engine":
        # scan-decoded model (the header path did not apply): the header, or at
        # least its property bag, still reads
        try:
            meta = model_meta_scanned(header, order)
            if meta is None:
                log(
                    "      WARNING: model meta %s: property bag of the header not readable, "
                    "no .model.json" % out_path.stem
                )
            else:
                # fewer submeshes than the header's full-detail render buffers: the
                # scan missed some (console Palm_Banana_01: 1 of 3)
                M2 = parse_model_header(header, order)
                want = len(
                    [b for b in select_model_buffers(M2, 0) if b["format"] in (5, 6)] if M2 else []
                )
                if want > len(subs) and not status["partial"]:
                    status["partial"] = (
                        "the header lists %d full-detail render buffer(s), the scan found "
                        "%d submesh(es)" % (want, len(subs))
                    )
                    log(
                        "      WARNING: model %s: incomplete: %s"
                        % (out_path.name, status["partial"])
                    )
                if status["partial"]:
                    meta["not_decoded"] = list(meta.get("not_decoded") or []) + ["submeshes"]
                    meta["submeshes"] = {
                        "decoded": len(subs),
                        "header_render_buffers_lod0": want if M2 else None,
                        "note": status["partial"],
                    }
        except (TypeError, ValueError, struct.error) as ex:
            meta = None
            log("      ! model meta %s: %s" % (out_path.stem, ex))
    log(
        "      model %d verts %d tris %d submeshes%s -> %s"
        % (
            len(V),
            len(T),
            len(subs),
            " +mtl" if any(not m.startswith("submesh_") for m in materials) else "",
            out_path.name,
        )
    )
    # rigged + textured .glb (skinned character models only; bind pose, flat rig
    # with the model's OWN palette joint names -- fully file-derived)
    skinned = bool(have_skin and SKIN_I and len(SKIN_I) == len(subs))
    # per-vertex attributes need the header-driven decode: its buffers carry the
    # has_color / has_alpha flags and the tangent frame at known offsets
    attrs = None
    if rig and hplan and _RIG.get("attrs", True) and didx and len(didx) == len(subs):
        try:
            attrs = _RIG["mod"].mesh_vertex_attributes(header, stream, subs, lod)
        except Exception as ex:
            status["glb_reason"] = "vertex attributes not decoded: %s" % ex
            log("      ! vertex attributes %s: %s" % (out_path.stem, ex))
    if rig and (skinned or attrs is not None):
        try:
            import numpy as _np

            glb_path = out_path.with_suffix(".glb")
            if skinned:
                SI = _np.concatenate(SKIN_I)
                SW = _np.concatenate(SKIN_W)
                _is_body = _model_is_body(header)  # head/accessory -> own palette, static
                pal = _model_palette(header)
                need = int(SI.max()) + 1 if SI.size else 0
                names = [b["name"] for b in pal["bones"]] if pal else []
                if len(names) < need:
                    names += ["bone_%d" % i for i in range(len(names), need)]
                pal = {"bone_count": len(names), "bones": [{"name": x} for x in names]}
            else:  # rigid (or mixed) model: mesh + materials only
                SI = SW = None
                _is_body = False
                pal = {"bone_count": 0, "bones": []}
            kw = {}
            if attrs is not None:
                kw = dict(
                    normals=attrs["normals"],
                    colors=attrs["colors"],
                    tangents=attrs["tangents"],
                    has_color=attrs["has_color"],
                    has_alpha=attrs["has_alpha"],
                    engine_materials=True,
                )
            _RIG["mod"].build_rigged_glb(
                glb_path,
                _np.asarray(V, float),
                None,
                U if have_u else None,
                SI,
                SW,
                T,
                subs,
                materials,
                tex_index,
                pal,
                None,
                log,
                static=not _is_body,
                **kw,
            )
            log(
                "      %s glb (%d joints, bind pose) -> %s"
                % ("rigged" if _is_body else "static", pal["bone_count"], glb_path.name)
            )
            status["glb"] = True
        except Exception as ex:
            status["glb_reason"] = "the GLB writer failed: %s" % ex
            log("      ! rig glb %s: %s" % (out_path.stem, ex))
    if rig and not status["glb"]:
        # never silent: say in the sidecar why this model has no .glb
        status["glb"] = False
        if status["glb_reason"] is None:
            if not hplan:
                why = (
                    "the mesh came from the descriptor scan (the header-driven decode did "
                    "not apply) and has no skin: a static GLB is only written from the "
                    "header-driven decode"
                )
            elif not _RIG.get("attrs", True):
                why = "--no-vertex-attrs: only skinned models get a GLB (the 1.3.0 output)"
            elif attrs is None:
                why = "the vertex attributes of the header's buffers could not be paired"
            else:
                why = "not written"
            status["glb_reason"] = why
        if meta is not None:
            meta["glb"] = {"written": False, "reason": status["glb_reason"]}
    if meta is not None:
        if stored_name:
            meta["stored_name"] = stored_name
        if "eyelash_uvs" in restored:
            meta["reconstruction"] = lash_reconstruction_note()
        try:
            import json as _json

            with open(
                out_path.with_suffix(".model.json"), "w", encoding="utf-8", newline="\n"
            ) as _f:
                _json.dump(meta, _f, indent=1)
                _f.write("\n")
        except (OSError, TypeError, ValueError) as ex:
            log("      ! model meta %s: %s" % (out_path.stem, ex))
    return True


def _half(u):
    s = (u >> 15) & 1
    e = (u >> 10) & 0x1F
    f = u & 0x3FF
    val = (f / 1024) * 2**-14 if e == 0 else (0.0 if e == 31 else (1 + f / 1024) * 2 ** (e - 15))
    return -val if s else val


# ===========================================================================
# (5) Audio  (.mediastream_s  ->  Ogg Vorbis)
# ===========================================================================
def _audio_packets(d):
    N = len(d)

    def ok(o):
        if o + 32 > N:
            return False
        _a, plen, _b = struct.unpack_from("<III", d, o)
        return 1 <= plen <= 8192 and o + 32 + plen <= N

    o, pk = 0, []
    while o + 32 <= N:
        _a, plen, _b = struct.unpack_from("<III", d, o)
        if 1 <= plen <= 8192 and o + 32 + plen <= N:
            pk.append(d[o + 32 : o + 32 + plen])
            o += 32 + plen
        else:  # chunk boundary -> resync
            scan, found = o, None
            while scan < min(N - 64, o + 200000):
                if ok(scan):
                    _x, nlen, _y = struct.unpack_from("<III", d, scan)
                    if ok(scan + 32 + nlen):
                        found = scan
                        break
                scan += 1
            if found is None:
                break
            o = found
    return pk


def _ogg_crc_table():
    t = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (r & 0x80000000) else (r << 1) & 0xFFFFFFFF
        t.append(r)
    return t


_OGGCRC = _ogg_crc_table()


def _ogg_crc(data):
    c = 0
    for b in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ _OGGCRC[((c >> 24) & 0xFF) ^ b]
    return c


def _lacing(L):
    return [255] * (L // 255) + ([0] if L % 255 == 0 else [L % 255])


def _ogg_page(serial, seq, granule, htype, packets):
    seg, body = [], b""
    for p in packets:
        seg += _lacing(len(p))
        body += p
    h = (
        b"OggS"
        + bytes([0, htype])
        + struct.pack("<q", granule)
        + struct.pack("<I", serial)
        + struct.pack("<I", seq)
        + b"\x00\x00\x00\x00"
        + bytes([len(seg)])
        + bytes(seg)
    )
    pg = h + body
    return pg[:22] + struct.pack("<I", _ogg_crc(pg)) + pg[26:]


class _BR:
    def __init__(s, d):
        s.d, s.p = d, 0

    def read(s, n):
        v = 0
        for i in range(n):
            v |= ((s.d[s.p >> 3] >> (s.p & 7)) & 1) << i
            s.p += 1
        return v


def _ilog(x):
    n = 0
    while x > 0:
        n += 1
        x >>= 1
    return n


def _lk1(entries, dim):
    v = 0
    while (v + 1) ** dim <= entries:
        v += 1
    return v


def _vorbis_blockflags(setup, channels):
    b = _BR(setup)
    assert b.read(8) == 5
    for c in b"vorbis":
        assert b.read(8) == c
    for _ in range(b.read(8) + 1):  # codebooks
        assert b.read(24) == 0x564342
        dim = b.read(16)
        ent = b.read(24)
        if not b.read(1):
            sp = b.read(1)
            for _e in range(ent):
                if sp:
                    if b.read(1):
                        b.read(5)
                else:
                    b.read(5)
        else:
            cur = 0
            b.read(5)
            while cur < ent:
                cur += b.read(_ilog(ent - cur))
        lut = b.read(4)
        if lut in (1, 2):
            b.read(32)
            b.read(32)
            vb = b.read(4) + 1
            b.read(1)
            for _v in range(_lk1(ent, dim) if lut == 1 else ent * dim):
                b.read(vb)
    for _ in range(b.read(6) + 1):
        assert b.read(16) == 0
    for _ in range(b.read(6) + 1):  # floors
        ft = b.read(16)
        if ft == 0:
            b.read(8)
            b.read(16)
            b.read(16)
            b.read(6)
            b.read(8)
            for _ in range(b.read(4) + 1):
                b.read(8)
        elif ft == 1:
            plist = [b.read(4) for _ in range(b.read(5))]
            mx = max(plist) if plist else -1
            cd = [0] * (mx + 1)
            for j in range(mx + 1):
                cd[j] = b.read(3) + 1
                cs = b.read(2)
                if cs > 0:
                    b.read(8)
                for _ in range(1 << cs):
                    b.read(8)
            b.read(2)
            rb = b.read(4)
            for j in plist:
                for _ in range(cd[j]):
                    b.read(rb)
        else:
            raise ValueError("floor %d" % ft)
    for _ in range(b.read(6) + 1):  # residues
        b.read(16)
        b.read(24)
        b.read(24)
        b.read(24)
        cl = b.read(6) + 1
        b.read(8)
        casc = []
        for _ in range(cl):
            lo = b.read(3)
            casc.append(lo + 8 * (b.read(5) if b.read(1) else 0))
        for c in casc:
            for k in range(8):
                if c & (1 << k):
                    b.read(8)
    for _ in range(b.read(6) + 1):  # mappings
        assert b.read(16) == 0
        sm = (b.read(4) + 1) if b.read(1) else 1
        if b.read(1):
            for _ in range(b.read(8) + 1):
                b.read(_ilog(channels - 1))
                b.read(_ilog(channels - 1))
        assert b.read(2) == 0
        if sm > 1:
            for _ in range(channels):
                b.read(4)
        for _ in range(sm):
            b.read(8)
            b.read(8)
            b.read(8)
    flags = []
    for _ in range(b.read(6) + 1):  # modes
        flags.append(b.read(1))
        assert b.read(16) == 0 and b.read(16) == 0
        b.read(8)
    return flags


def _ogg_from_packets(pk, exact, end=None):
    """One Ogg Vorbis file from a Vorbis packet list (3 header packets + audio).
    end: the stream's own end sample position (stamped on the last page so a
    decoder trims the final block, as Vorbis intends); None = computed position.
    Returns (ogg bytes, channels, rate, audio packet count, last granulepos) or None."""
    headers = [p for p in pk if p and p[0] in (1, 3, 5)][:3]
    audio = [p for p in pk if p and p[0] not in (1, 3, 5)]
    if len(headers) < 3 or not audio:
        return None
    if headers[0][:7] != b"\x01vorbis":
        return None
    ch = headers[0][11]
    rate = struct.unpack_from("<I", headers[0], 12)[0]
    gr = None
    if exact:
        # Sample-perfect granulepos from the per-packet Vorbis block sizes. The
        # approximate 1024/packet path OVERSHOOTS (stamps more samples than the page
        # holds), and players that sync to granulepos then insert gaps -> choppy.
        try:
            bsb = headers[0][28]
            bs0, bs1 = 1 << (bsb & 0xF), 1 << (bsb >> 4)
            fl = _vorbis_blockflags(headers[2], ch)
            mb = _ilog(len(fl) - 1)
            bss = [
                (bs1 if fl[((p[0] >> 1) & ((1 << mb) - 1)) if mb else 0] else bs0) for p in audio
            ]
            gr, g = [0], 0
            for n in range(1, len(bss)):
                g += (bss[n - 1] + bss[n]) // 4
                gr.append(g)
        except Exception:
            gr = None
    if gr is None:
        gr = [(i + 1) * 1024 for i in range(len(audio))]
    if end is not None and (len(gr) < 2 or gr[-2] < end) and end <= gr[-1]:
        gr[-1] = end
    out = _ogg_page(1, 0, 0, 0x02, [headers[0]]) + _ogg_page(1, 1, 0, 0, [headers[1], headers[2]])
    seq = 2
    for i, p in enumerate(audio):
        out += _ogg_page(1, seq, gr[i], 0x04 if i == len(audio) - 1 else 0, [p])
        seq += 1
    return out, ch, rate, len(audio), gr[-1]


def decode_audio(raw, out_path, exact, log=None):
    """The 1.3.0 single-file output: every packet of the stream in file order.
    Correct for a one-track stream; a multi-track stream comes out as its tracks'
    chunks appended in turn (use decode_audio_tracks)."""
    if not callable(log):
        log = lambda *a, **k: None
    r = _ogg_from_packets(_audio_packets(raw), exact)
    if r is None:
        return False
    out, ch, rate, npk, last = r
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    log(
        "      Vorbis %dch %dHz %d pkts -> %s (%.1fs)" % (ch, rate, npk, out_path.name, last / rate)
    )
    return True


# ---------------------------------------------------------------------------
# Multi-track streams.  A mediastream_s holds N synchronous tracks (music
# stems).  It is a sequence of groups; a group is one chunk per track, back to
# back, and is followed by a link record
#     [u32 m][u32 size x N],  m = sum(sizes) + 4 * (N + 1)
# giving the chunk sizes of the NEXT group; the link after the last group
# repeats group 0's sizes (the loop).  Read on all 13 Part-2 music streams of
# each platform; engine side: MusicStreamSlot track0..9 / SoundSlot
# numStreamTracks (0x4da99c), MusicTrackCtrl.track_index.
# PC: a chunk is [32-byte packet header][Vorbis packet] records, and each
# track's first chunk starts with its own three Vorbis header packets.
# ---------------------------------------------------------------------------
def _media_link(raw, o, n, bo="<"):
    """Chunk sizes of the link record at `o` for `n` tracks, or None."""
    if n < 1 or o + 4 * (n + 1) > len(raw):
        return None
    v = struct.unpack_from(bo + "%dI" % (n + 1), raw, o)
    return list(v[1:]) if v[0] == sum(v[1:]) + 4 * (n + 1) else None


def media_tracks_pc(raw):
    """Tracks of a PC mediastream_s: [{"packets": [...], "end_sample": n}, ...]
    (headers first).  end_sample is the granule position the stream stores with
    the track's last packet (packet header dwords 4-5; equal to the block-size
    sum on every other packet, and the exact track length on the last).  None
    when the stream does not walk cleanly to its end (callers then fall back to
    the flat packet scan)."""
    N = len(raw)

    def packets(o, end, into):
        while o < end:
            if o + 32 > end:
                return None
            plen = struct.unpack_from("<I", raw, o + 4)[0]
            if not (1 <= plen and o + 32 + plen <= end):
                return None
            into["packets"].append(raw[o + 32 : o + 32 + plen])
            into["end_sample"] = struct.unpack_from("<Q", raw, o + 16)[0]
            o += 32 + plen
        return o

    # group 0: a new track starts at every Vorbis identification header
    tracks, o = [], 0
    while o + 32 <= N:
        if tracks and _media_link(raw, o, len(tracks)) is not None:
            break
        plen = struct.unpack_from("<I", raw, o + 4)[0]
        if not (1 <= plen <= 65536 and o + 32 + plen <= N):
            return None
        p = raw[o + 32 : o + 32 + plen]
        if p[:7] == b"\x01vorbis":
            tracks.append({"packets": [], "end_sample": 0})
        if not tracks:
            return None
        tracks[-1]["packets"].append(p)
        tracks[-1]["end_sample"] = struct.unpack_from("<Q", raw, o + 16)[0]
        o += 32 + plen
    n = len(tracks)
    while o + 4 * (n + 1) <= N:
        sizes = _media_link(raw, o, n)
        if sizes is None:
            return None
        o += 4 * (n + 1)
        if o + sum(sizes) > N:
            break  # the closing link: group 0's sizes again
        for k in range(n):
            o = packets(o, o + sizes[k], tracks[k])
            if o is None:
                return None
    return tracks if tracks and o == N else None


_TRACK0 = re.compile(r"_track0(?=\.[^/]*$|$)", re.I)


def media_track_name(name, k, label=None):
    """Output name of track `k` of the stream `name` (`..._track0.mediastream_s`):
    the same name with the track number replaced and, when the MusicStreamSlot
    gives one, its track label: `underground_track1_Intro_loop.mediastream_s`."""
    lab = re.sub(r"[^A-Za-z0-9_-]+", "_", (label or "").strip()).strip("_")
    if lab.lower() in ("", "none"):
        lab = ""
    tag = "_track%d%s" % (k, "_" + lab if lab else "")
    if _TRACK0.search(name):
        return _TRACK0.sub(lambda m: tag, name, count=1)
    base, dot, ext = name.rpartition(".")
    return (base + tag + dot + ext) if dot and "/" not in ext else name + tag


def decode_audio_tracks(raw, out_dir, name, exact=True, log=None, labels=None):
    """Write a PC stream as one Ogg Vorbis file per track under `out_dir`.

    A one-track stream keeps the name decode_audio gives it; like every track it
    ends at the stream's stored end position.  Returns [{index, file, label, channels, rate, samples, duration_s}]
    or None when the stream is not a clean multi-track stream (nothing written)."""
    if not callable(log):
        log = lambda *a, **k: None
    tracks = media_tracks_pc(raw)
    if not tracks:
        return None
    out = []
    for k, trk in enumerate(tracks):
        lab = labels[k] if labels and k < len(labels) else None
        tname = (name if len(tracks) == 1 else media_track_name(name, k, lab)) + ".ogg"
        r = _ogg_from_packets(trk["packets"], exact, trk["end_sample"])
        if r is None:
            return None
        data, ch, rate, npk, last = r
        outp = safe(out_dir, tname)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(data)
        log(
            "      Vorbis %dch %dHz %d pkts -> %s (%.1fs)%s"
            % (ch, rate, npk, outp.name, last / rate, "" if len(tracks) == 1 else " [track %d]" % k)
        )
        out.append(
            dict(
                index=k,
                file=out_rel(out_dir, tname),
                label=lab,
                channels=ch,
                rate=rate,
                samples=last,
                duration_s=round(last / rate, 4),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Console (X360/PS3) streamed audio.  Console `mediastream_s` files are NOT the
# PC Vorbis packet container; they are the engine's segment-chained stream:
#     [seg0][link][seg1][link]...[EOF loop-link]
# link = [u32be m][u32be size...]:  m = sum(sizes) + 4*(n+1); the FIRST size is
# the next segment's byte length (multi-entry links = streaming prefetch info).
#   X360 segments: raw XMA2 2048-byte packets (seg0 found by bootstrap scan).
#   PS3  segments: [32-byte header][MP3 frames]; header dword0 = payload size;
#                  MP3 frame sync sits at +0x20.  Link records are NOT emitted
#                  after every segment: most Part-2 music packs several headered
#                  segments back-to-back with a multi-entry link only between
#                  groups, and one file (str_p2) pads each segment up to a
#                  16-byte boundary.  _ps3_media_walk handles all observed
#                  layouts record-by-record (link OR segment at each offset,
#                  exact-offset first, align-16 fallback); verified lossless on
#                  all 13 Part-2 music streams (0 junk bytes, durations == PC).
# Channels/rate/total-samples come from the block 'mediastream' asset header
# (media_meta_from_header).
# ---------------------------------------------------------------------------
def _media_walk_segments(raw, seg0):
    u = lambda o: struct.unpack_from(">I", raw, o)[0]
    if not (0 < seg0 <= len(raw)):
        return None
    segs = [(0, seg0)]
    o = seg0
    while o + 8 <= len(raw):
        m = u(o)
        ents = []
        q = o + 4
        hit = False
        while q + 4 <= len(raw) and len(ents) < 32:
            e = u(q)
            ents.append(e)
            q += 4
            if m == sum(ents) + 4 * (len(ents) + 1):
                hit = True
                break
            if sum(ents) >= m:
                return None
        if not hit:
            return None
        nxt = ents[0]
        if q + nxt > len(raw):
            return segs  # EOF loop-back link
        segs.append((q, nxt))
        o = q + nxt
    return segs


def _ps3_media_link(raw, o):
    """Try to parse a link record at o: [u32be m][u32be sizes...] with
    m = sum(sizes) + 4*(n+1).  Returns end-of-link offset or None."""
    u = lambda x: struct.unpack_from(">I", raw, x)[0]
    if o + 8 > len(raw):
        return None
    m = u(o)
    ents = []
    q = o + 4
    while q + 4 <= len(raw) and len(ents) < 32:
        ents.append(u(q))
        q += 4
        if m == sum(ents) + 4 * (len(ents) + 1):
            return q
        if sum(ents) >= m:
            return None
    return None


def _ps3_media_seg(raw, o):
    """True if a [32B header][MP3 frames] segment starts at o (header dword0 =
    payload size, MP3 frame sync at +0x20)."""
    if o + 0x24 > len(raw):
        return False
    sz = struct.unpack_from(">I", raw, o)[0]
    return (
        raw[o + 0x20] == 0xFF
        and (raw[o + 0x21] & 0xE0) == 0xE0
        and 0 < sz
        and o + 0x20 + sz <= len(raw)
    )


def _ps3_media_walk(raw):
    """De-chain a PS3 mediastream_s: at each offset either a link record (skip)
    or a headered MP3 segment (collect payload).  After a segment the next
    record sits at the exact end offset OR padded to a 16-byte boundary
    (str_p2).  Returns the joined MP3 stream, or None."""
    u = lambda x: struct.unpack_from(">I", raw, x)[0]
    o = 0
    out = []
    while o + 0x24 <= len(raw):
        q = _ps3_media_link(raw, o)
        if q is not None:
            if q + 0x24 > len(raw):
                break  # EOF loop-back link
            o = q
            continue
        if not _ps3_media_seg(raw, o):
            return None
        sz = u(o)
        out.append(raw[o + 0x20 : o + 0x20 + sz])
        nxt = o + 0x20 + sz
        a = (nxt + 15) & ~15
        if nxt + 8 > len(raw):
            break
        if _ps3_media_link(raw, nxt) is not None or _ps3_media_seg(raw, nxt):
            o = nxt
        elif a != nxt and (
            a + 8 > len(raw) or _ps3_media_link(raw, a) is not None or _ps3_media_seg(raw, a)
        ):
            o = a  # 16-byte aligned next record
        else:
            return None
    return b"".join(out) if out else None


def _console_media_parse(raw):
    """Detect + de-chain a console mediastream_s. Returns (codec, data) with the
    engine framing stripped ('mp3' PS3 / 'xma' X360), or None."""
    if len(raw) < 0x1000 or len(raw) < 0x24:
        return None
    # PS3: MP3 sync right after the 32-byte segment header
    if raw[0x20] == 0xFF and (raw[0x21] & 0xE0) == 0xE0:
        out = _ps3_media_walk(raw)
        if out:
            return ("mp3", out)
    # X360: XMA2 packets; segment sizes are 2048-aligned -> bootstrap seg0
    for s0 in range(0x800, min(len(raw), 0x200000), 0x800):
        segs = _media_walk_segments(raw, s0)
        if segs and len(segs) >= 2 and sum(sz for _, sz in segs) >= len(raw) * 0.9:
            return ("xma", b"".join(raw[o : o + sz] for o, sz in segs))
    # X360 fallback: single segment, engine trailer only at EOF
    if (
        len(raw) >= 2048
        and (raw[0] >> 2)
        and struct.unpack_from(">I", raw, 0)[0] & 0xFFFF == 0x0100
    ):
        return ("xma", raw[: len(raw) - (len(raw) % 2048)])
    return None


def _ps3_media_tracks(raw):
    """Per-track MP3 byte strings of a PS3 mediastream_s (see the multi-track
    note above decode_audio_tracks): group 0 is one headered segment per track,
    then [link][one chunk per track]...  A chunk is [32-byte header][MP3 frames]
    segments, each optionally padded to a 16-byte boundary.  None if it does not
    walk to the end of the file."""
    N = len(raw)

    def seg(o, end):
        for q in (o, (o + 15) & ~15):
            if q + 0x24 <= end and _ps3_media_seg(raw, q):
                sz = struct.unpack_from(">I", raw, q)[0]
                if q + 0x20 + sz <= end:
                    return q, sz
        return None

    tracks, o = [], 0
    while True:
        if tracks:
            for q in (o, (o + 15) & ~15):
                if _media_link(raw, q, len(tracks), ">") is not None:
                    o = q
                    break
            else:
                q = None
            if q is not None:
                break
        r = seg(o, N)
        if r is None or len(tracks) >= 32:
            return None
        tracks.append([raw[r[0] + 0x20 : r[0] + 0x20 + r[1]]])
        o = r[0] + 0x20 + r[1]
    n = len(tracks)
    while o + 4 * (n + 1) <= N:
        sizes = _media_link(raw, o, n, ">")
        if sizes is None:
            q = (o + 15) & ~15
            sizes = _media_link(raw, q, n, ">")
            if sizes is None:
                return None
            o = q
        o += 4 * (n + 1)
        if o + sum(sizes) > N:
            break  # closing link
        for k in range(n):
            end = o + sizes[k]
            while o < end:
                r = seg(o, end)
                if r is None:
                    if end - o < 16:  # trailing pad of the chunk
                        break
                    return None
                tracks[k].append(raw[r[0] + 0x20 : r[0] + 0x20 + r[1]])
                o = r[0] + 0x20 + r[1]
            o = end
    return [b"".join(t) for t in tracks]


def _x360_media_tracks(raw):
    """Per-track XMA2 packet strings of an X360 mediastream_s.  Chunks are whole
    2048-byte packets; group 0 has no sizes in front of it, so it is split with
    the closing link (which repeats group 0's sizes).  None if the links do not
    chain to the end of the file or the closing link does not add up."""
    N = len(raw)
    first = None
    for o in range(0x800, min(N, 0x400000), 0x800):
        for n in range(1, 17):
            sizes = _media_link(raw, o, n, ">")
            if sizes and all(x and x % 2048 == 0 for x in sizes):
                first = (o, n)
                break
        if first:
            break
    if not first:
        return None
    g0, n = first
    o = g0
    spans = []  # (offset, sizes) of groups 1..
    sizes = None
    while o + 4 * (n + 1) <= N:
        sizes = _media_link(raw, o, n, ">")
        if sizes is None:
            return None
        o += 4 * (n + 1)
        if o + sum(sizes) > N:
            break
        spans.append((o, sizes))
        o += sum(sizes)
    if sizes is None or sum(sizes) != g0 or o + sum(sizes) <= N:
        return None  # the last link read must be the closing one, equal to group 0
    tracks = [[] for _ in range(n)]
    for off, sz in [(0, sizes)] + spans:
        for k in range(n):
            tracks[k].append(raw[off : off + sz[k]])
            off += sz[k]
    return [b"".join(t) for t in tracks]


def media_tracks_console(raw):
    """(codec, [track bytes, ...]) of a console mediastream_s, one entry per
    track with the engine framing stripped ('mp3' PS3 / 'xma' X360), or None."""
    if len(raw) < 0x1000:
        return None
    if raw[0x20] == 0xFF and (raw[0x21] & 0xE0) == 0xE0:
        t = _ps3_media_tracks(raw)
        return ("mp3", t) if t else None
    t = _x360_media_tracks(raw)
    return ("xma", t) if t else None


def _xma2_riff(data, ch, rate, nsamp):
    """Wrap raw XMA2 packet data in a Microsoft XMA RIFF (XMA2WAVEFORMATEX)."""
    fmt = struct.pack("<HHIIHHH", 0x166, ch, rate, rate * ch * 2, 4, 16, 34)
    fmt += struct.pack(
        "<HIIIIIIIBBH",
        (ch + 1) // 2,
        3 if ch == 2 else 4,
        nsamp,
        0x10000,
        0,
        nsamp,
        0,
        0,
        0,
        4,
        (len(data) + 0xFFFF) // 0x10000,
    )
    return (
        b"RIFF"
        + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def _xma_frame_count(data):
    return sum(data[o] >> 2 for o in range(0, len(data) - 2047, 2048))


def media_meta_from_header(header, order="<"):
    """From a block 'mediastream' asset header: (mediastream_path, channels,
    rate, total_samples) -- channels/rate/samples may be None if not found
    (the u32 before channels = XMA frame-count*512 exactly, i.e. total samples)."""
    m = re.search(rb"/[ -~]{4,220}?\.mediastream_s\x00", header, re.I)
    if not m:
        return None
    path = m.group()[:-1].decode("latin1")
    ch = rate = samples = None
    w = re.search(rb"\.wav\x00", header, re.I)
    if w:
        tail = header[w.end() : w.end() + 48]
        for off in range(0, 25):
            if off + 12 <= len(tail):
                a, b2, c = struct.unpack_from(order + "III", tail, off)
                if 1 <= b2 <= 8 and 8000 <= c <= 96000:
                    samples, ch, rate = a, b2, c
                    break
    return (path, ch, rate, samples)


def media_desc_from_header(header, order="<"):
    """The whole block 'mediastream' descriptor (the `<x>_track0.wav` asset):
    {"stream", "groups", "first_group_sizes", "tracks": [{"source", "samples",
    "channels", "rate", "cue_points": [{"name", "sample"}]}]}, or None.

    After the stream path: [u32 m][u32 chunk size x tracks] (group 0's link,
    see media_tracks_pc), [u32 groups][u32 0], then per track
    [str source wav][u32 0][u32 samples][u32 channels][u32 rate][u32 0][i32 -1]
    [u32 cues] cues x ([str name][u32 sample]); str = [u32 len][bytes, NUL
    included].  The u32 before the path's length is the track count.  Console
    track records carry codec fields after the cues (skipped).  Layout read on
    the 13 Part-2 descriptors of PC, X360 and PS3 and the 13 of Part 1 PC."""
    m = re.search(rb"/[ -~]{4,220}?\.mediastream_s\x00", header, re.I)
    if not m or m.start() < 8:
        return None
    u = lambda o: struct.unpack_from(order + "I", header, o)[0]

    def string(o):
        if o + 4 > len(header):
            raise ValueError("descriptor ends inside a string")
        n = u(o)
        if not (1 <= n <= 512) or o + 4 + n > len(header):
            raise ValueError("bad string length")
        return header[o + 4 : o + 4 + n].split(b"\x00")[0].decode("latin1"), o + 4 + n

    try:
        n = u(m.start() - 8)
        if not (1 <= n <= 32) or u(m.start() - 4) != len(m.group()):
            return None
        o = m.end()
        sizes = _media_link(header, o, n, order)
        if sizes is None:
            return None
        o += 4 * (n + 1)
        groups = u(o)
        o += 8
        tracks = []
        for _ in range(n):
            src, o = string(o)
            _z, samples, ch, rate, _z2, _m1, ncue = struct.unpack_from(order + "7I", header, o)
            o += 28
            if not (1 <= ch <= 8 and 8000 <= rate <= 96000 and ncue <= 4096):
                return None
            cues = []
            for _c in range(ncue):
                nm, o = string(o)
                cues.append({"name": nm, "sample": u(o)})
                o += 4
            tracks.append(
                {
                    "source": src,
                    "samples": samples,
                    "channels": ch,
                    "rate": rate,
                    "cue_points": cues,
                }
            )
            if len(tracks) < n:
                # console records end with codec fields before the next source
                # path: PS3 12 bytes (padded samples, bytes/s, MP3 ratio),
                # X360 [u32 k][k x u32 seek sample][u32 XMA quality]; PC none
                k = u(o) if o + 4 <= len(header) else 0
                for q in (o, o + 12, o + 8 + 4 * k):
                    if q + 5 <= len(header) and 1 <= u(q) <= 512 and header[q + 4 : q + 5] == b"/":
                        o = q
                        break
                else:
                    return None
    except (struct.error, ValueError):
        return None
    return {
        "stream": m.group()[:-1].decode("latin1"),
        "groups": groups,
        "first_group_sizes": sizes,
        "tracks": tracks,
    }


def _emit_audio(container, ext, name, out_dir, vgmstream_cli, log, tag, keep_container=False):
    """Write an audio container; convert to .wav via vgmstream-cli if provided.
    keep_container=True also writes the raw container (.xma/.mp3) alongside the
    .wav -- valid XMA2/MP3 that any working decoder can re-convert (see MASTER
    §14: short X360 XMA2 fails in current vgmstream/ffmpeg but the data is good).

    X360 XMA is ALWAYS kept (keep default-on for `.xma`): the raw container is
    the reliable artifact and a .wav is only produced when --vgmstream-cli is
    given.  --keep-xma still forces keeping PS3 .mp3 containers too."""
    keep_container = keep_container or ext == ".xma"
    base = safe(out_dir, name)

    def _keep():
        outp = base.with_suffix(base.suffix + ext)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(container)
        return outp

    if vgmstream_cli:
        import subprocess, tempfile, os as _os

        wav = base.with_suffix(base.suffix + ".wav")
        wav.parent.mkdir(parents=True, exist_ok=True)
        tf = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            try:
                tf.write(container)
            finally:
                tf.close()  # also when the write fails: an open file cannot be unlinked on Windows
            pr = subprocess.run(
                [str(vgmstream_cli), "-o", str(wav), tf.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if pr.returncode == 0 and wav.exists():
                kept = " +%s" % _keep().name if keep_container else ""
                log("      %s %s -> %s%s" % (tag, name.split("/")[-1], wav.name, kept))
                return True
            log("      ! vgmstream failed on %s (rc=%s); writing %s" % (name, pr.returncode, ext))
        finally:
            try:
                _os.unlink(tf.name)
            except OSError:
                pass
    outp = _keep()
    log("      %s %s -> %s" % (tag, name.split("/")[-1], outp.name))
    return True


def decode_sfx_console(header, order, name, out_dir, vgmstream_cli, log, keep_container=False):
    """Console inline 'sound' assets (PC uses decode_sfx): the header's audio
    is written as a container (.xma X360 / .mp3 PS3; .wav with vgmstream-cli).
    Returns the sfx_info record of the sound ("file" = the file written,
    relative to out_dir) or False when nothing was written.

    X360: the XMA2 packets start at pe+26, right after their byte count (the
    packet frame counts add up to samples / 512 there on every shipped sound;
    1.3.0 cut them from pe+30, four bytes into the first packet, and no decoder
    read the result).  PS3: the MP3 bytes of the header's one segment.  A
    header sfx_info does not read falls back to a byte scan, and says so."""
    try:
        info = sfx_info(header, order)
    except (struct.error, IndexError, ValueError):
        info = None

    def done(ok, ext, rec):
        if not ok:
            return False
        wav = vgmstream_cli and safe(out_dir, name + ".wav").exists()
        rec.pop("_pe", None)
        rec["file"] = out_rel(out_dir, name + (".wav" if wav else ext))
        if wav:
            try:
                with wave.open(str(safe(out_dir, name + ".wav")), "rb") as w:
                    rec["decoded_samples"] = w.getnframes()
                    rec["decoded_duration_s"] = round(w.getnframes() / float(w.getframerate()), 4)
            except (wave.Error, OSError, EOFError, ZeroDivisionError):
                pass
        if not rec.get("duration_s"):
            rec["duration_s"], rec["duration_source"] = None, "none"
            log(
                "      WARNING: sfx %s: no sample count in the header and no frames: no duration"
                % name
            )
        return rec

    if info and info["codec"] in ("xma2", "mp3"):
        o, n = info["data_offset"], info["data_bytes"]
        data = header[o : o + n]
        if info["codec"] == "xma2" and n and n % 2048 == 0 and len(data) == n:
            rate = info["rate"] if 8000 <= info["rate"] <= 96000 else 44100
            ns = info["samples"] or _xma_frame_count(data) * 512
            ok = _emit_audio(
                _xma2_riff(data, info["channels"], rate, ns),
                ".xma",
                name,
                out_dir,
                vgmstream_cli,
                log,
                "XMA-SFX",
                keep_container,
            )
            return done(ok, ".xma", info)
        if info["codec"] == "mp3" and len(data) == n:
            if not info["mp3_clean"]:
                log(
                    "      WARNING: sfx %s: MP3 data is not whole frames (%d frames walked); written as stored"
                    % (name, info["mp3_frames"])
                )
            ok = _emit_audio(
                data, ".mp3", name, out_dir, vgmstream_cli, log, "MP3-SFX", keep_container
            )
            return done(ok, ".mp3", info)
    # not a layout sfx_info reads: the fallback scan (no header facts are known)
    pe = _propbag_end(header, order)
    if pe + 30 > len(header):
        return False
    unknown = dict(codec=None, duration_s=None, duration_source="none", header="not recognised")
    ch = struct.unpack_from(order + "H", header, pe + 4)[0]
    codec = struct.unpack_from(order + "I", header, pe + 10)[0]
    rate = struct.unpack_from(order + "I", header, pe + 14)[0]
    nsamp = struct.unpack_from(order + "I", header, pe + 18)[0]
    dsz = struct.unpack_from(order + "I", header, pe + 22)[0]
    if codec == 3 and 1 <= ch <= 2 and dsz and dsz % 2048 == 0 and pe + 26 + dsz <= len(header):
        data = header[pe + 26 : pe + 26 + dsz]
        if not (8000 <= rate <= 96000):
            rate = 44100
        ns = min(nsamp, 0xFFFFFFFF) or _xma_frame_count(data) * 512
        log(
            "      WARNING: sfx %s: sound header not recognised; XMA2 packets cut by the fallback scan"
            % name
        )
        ok = _emit_audio(
            _xma2_riff(data, ch, rate, ns),
            ".xma",
            name,
            out_dir,
            vgmstream_cli,
            log,
            "XMA-SFX",
            keep_container,
        )
        return done(ok, ".xma", dict(unknown, codec="xma2"))
    for i in range(pe, min(len(header) - 4, pe + 256)):
        if header[i] == 0xFF and (header[i + 1] & 0xE0) == 0xE0:
            best = None
            for o in range(pe, min(pe + 64, len(header) - 4)):
                v = struct.unpack_from(">I", header, o)[0]
                if 0 < v <= len(header) - i and (len(header) - i) - v < 512:
                    best = v
                    break
            data = header[i : i + best] if best else header[i:]
            fs = mp3_frame_stats(data)
            if not fs["frames"]:
                continue  # two bytes that look like a sync, not an MP3 frame
            log(
                "      WARNING: sfx %s: sound header not recognised; MP3 cut by the fallback scan"
                % name
            )
            rec = dict(
                unknown,
                codec="mp3",
                channels=fs["channels"],
                rate=fs["rate"],
                samples=fs["samples"],
                mp3_frames=fs["frames"],
                duration_s=round(fs["samples"] / float(fs["rate"]), 4),
                duration_source="frame_count",
            )
            ok = _emit_audio(
                data, ".mp3", name, out_dir, vgmstream_cli, log, "MP3-SFX", keep_container
            )
            return done(ok, ".mp3", rec)
    return False


def decode_console_audio(
    name,
    raw,
    out_dir,
    meta,
    vgmstream_cli,
    log,
    keep_container=False,
    tracks=False,
    labels=None,
    desc=None,
):
    """Decode one console mediastream_s. meta = (ch, rate, samples) or None.
    Writes .wav via vgmstream-cli when available; else .mp3 (PS3) / .xma (X360).

    tracks=True: a multi-track stream is written as one file per track
    (media_track_name; `labels` = the MusicStreamSlot track names, `desc` =
    media_desc_from_header for per-track sample counts) and the list of track
    records is returned.  A one-track stream, or one that does not split
    cleanly, is written by the single-file path below (the 1.3.0 files) and
    returned as a one-record list.  tracks=False returns True / False."""
    split = media_tracks_console(raw) if tracks else None
    if split and len(split[1]) > 1:
        codec, parts = split
        ch, rate, samples = meta if meta else (None, None, None)
        out = []
        for k, data in enumerate(parts):
            lab = labels[k] if labels and k < len(labels) else None
            tname = media_track_name(name, k, lab)
            dt = desc["tracks"][k] if desc and k < len(desc.get("tracks", [])) else {}
            tch, trate = dt.get("channels") or ch or 2, dt.get("rate") or rate or 48000
            if codec == "mp3":
                container, ext = data, ".mp3"
                ns = dt.get("samples") or samples
            else:
                ns = min(dt.get("samples") or (_xma_frame_count(data) * 512), 0xFFFFFFFF)
                container, ext = _xma2_riff(data, tch, trate, ns), ".xma"
            _emit_audio(
                container, ext, tname, out_dir, vgmstream_cli, log, codec.upper(), keep_container
            )
            out.append(
                dict(
                    index=k,
                    file=out_rel(
                        out_dir,
                        tname
                        + (
                            ".wav"
                            if vgmstream_cli and safe(out_dir, tname + ".wav").exists()
                            else ext
                        ),
                    ),
                    label=lab,
                    channels=tch,
                    rate=trate,
                    samples=ns,
                    duration_s=round(ns / trate, 4) if ns else None,
                )
            )
        return out
    r = _console_media_parse(raw)
    if r is None:
        return False
    codec, data = r
    ch, rate, samples = meta if meta else (None, None, None)
    if desc and len(desc.get("tracks") or ()) == 1:
        # no stream facts by path (a loose tree): the one-track descriptor has them
        d0 = desc["tracks"][0]
        ch, rate = ch or d0.get("channels"), rate or d0.get("rate")
        samples = samples or d0.get("samples")
    if codec == "mp3":
        container, ext = data, ".mp3"
    else:
        nsamp = min(samples or (_xma_frame_count(data) * 512), 0xFFFFFFFF)
        container, ext = _xma2_riff(data, ch or 2, rate or 48000, nsamp), ".xma"
    ok = _emit_audio(
        container, ext, name, out_dir, vgmstream_cli, log, codec.upper(), keep_container
    )
    if not (ok and tracks):
        return ok
    ns = samples or (None if codec == "mp3" else nsamp)
    return [
        dict(
            index=0,
            file=out_rel(
                out_dir,
                name + (".wav" if vgmstream_cli and safe(out_dir, name + ".wav").exists() else ext),
            ),
            label=None,
            channels=ch,
            rate=rate,
            samples=ns,
            duration_s=round(ns / rate, 4) if ns and rate else None,
        )
    ]


# ===========================================================================
# Driver
# ===========================================================================
#: names Windows reserves for devices (in any letter case, with or without an extension)
_WIN_DEVICES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + ["COM%d" % i for i in range(1, 10)]
    + ["LPT%d" % i for i in range(1, 10)]
)


def _not_a_device(part):
    """`part`, or `_part` when Windows would open a device for it (CON, NUL.txt, ...)."""
    return "_" + part if part.split(".", 1)[0].strip().upper() in _WIN_DEVICES else part


def safe(base, name):
    """Archive entry name -> a path guaranteed to stay under `base`.

    Entry names are attacker-controlled (rot-2 obfuscated, not authenticated), so
    strip '..'/absolute anchors AND ':' -- pathlib treats 'C:/x' as a new anchor
    on Windows and would otherwise escape `base` entirely.  A component Windows
    reserves for a device (CON, NUL.txt, ...; none in the shipped archives) gets a
    leading '_' on every platform.

    Unless --names stored is in force the components take their canonical
    spelling (canonical_names.output_parts)."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    parts = [_not_a_device(p.replace(":", "_")) for p in parts]
    # --names canonical (default): the table's spelling, and one spelling per folder
    parts = _names_mod().output_parts(base, parts)
    out = base.joinpath(*parts) if parts else base / "_unnamed"
    if os.path.commonpath([os.path.abspath(base), os.path.abspath(out)]) != os.path.abspath(base):
        raise ValueError("unsafe archive entry name %r" % name)
    return out


def out_rel(base, name):
    """`name` as a "file" value of a JSON beside it: '/'-separated, relative to the
    output tree `base`.  With --names canonical it is the path safe() writes
    (folders in the spelling of the tree), so the value names the file on a
    case-sensitive file system too; with --names stored the name as stored."""
    if _names_mod().is_canonical():
        return safe(Path(base), name).relative_to(Path(base)).as_posix()
    return name.replace("\\", "/").lstrip("/")


def _clamp16(x):
    return -32768 if x < -32768 else (32767 if x > 32767 else x)


def _prop_walk(H, order="<"):
    """Walk the salt-prefixed property records after [typeName][classId].
    Part 2 (WM07) records are 20 bytes ([salt][hashLo][hashHi][tag][val],
    +4 when tag==2); Part 1 (WM06) records are 16 bytes ([salt][hash][tag]
    [val], +4 when tag==2). The stride is auto-detected by which one yields
    more consecutive salt hits. Returns (end_offset, base_record_size)."""
    tlen = struct.unpack_from(order + "I", H, 0)[0]
    p = 4 + tlen + 4
    if p + 4 > len(H):
        return p, 20
    salt = struct.unpack_from(order + "I", H, p)[0]

    def walk(rs, tagoff):
        q = p
        n = 0
        while q + rs <= len(H) and struct.unpack_from(order + "I", H, q)[0] == salt and n < 64:
            tag = struct.unpack_from(order + "I", H, q + tagoff)[0]
            q += rs + 4 if tag == 2 else rs
            n += 1
        return n, q

    n1, q1 = walk(16, 8)
    n2, q2 = walk(20, 12)
    return (q1, 16) if n1 > n2 else (q2, 20)


def _propbag_end(H, order="<"):
    return _prop_walk(H, order)[0]


def _adpcm_mono(d, ba):
    out = array.array("h")
    o = 0
    N = len(d)
    while o + ba <= N:
        b = d[o : o + ba]
        o += ba
        pred = b[0]
        if pred > 6:
            break
        dl = struct.unpack_from("<h", b, 1)[0]
        s1 = struct.unpack_from("<h", b, 3)[0]
        s2 = struct.unpack_from("<h", b, 5)[0]
        c1, c2 = _C1[pred], _C2[pred]
        out.append(s2)
        out.append(s1)
        for k in range(7, ba):
            for nib in ((b[k] >> 4) & 0xF, b[k] & 0xF):
                p = (s1 * c1 + s2 * c2) >> 8
                n = nib - 16 if nib >= 8 else nib
                v = _clamp16(p + n * dl)
                out.append(v)
                s2 = s1
                s1 = v
                dl = (_ADAPT[nib] * dl) >> 8
                if dl < 16:
                    dl = 16
    return out


def _adpcm_stereo(d, ba):
    out = array.array("h")
    o = 0
    N = len(d)
    while o + ba <= N:
        b = d[o : o + ba]
        o += ba
        pL, pR = b[0], b[1]
        if pL > 6 or pR > 6:
            break
        dL = struct.unpack_from("<h", b, 2)[0]
        dR = struct.unpack_from("<h", b, 4)[0]
        s1L = struct.unpack_from("<h", b, 6)[0]
        s1R = struct.unpack_from("<h", b, 8)[0]
        s2L = struct.unpack_from("<h", b, 10)[0]
        s2R = struct.unpack_from("<h", b, 12)[0]
        c1L, c2L = _C1[pL], _C2[pL]
        c1R, c2R = _C1[pR], _C2[pR]
        out.append(s2L)
        out.append(s2R)
        out.append(s1L)
        out.append(s1R)
        for k in range(14, ba):
            hi = (b[k] >> 4) & 0xF
            lo = b[k] & 0xF
            p = (s1L * c1L + s2L * c2L) >> 8
            n = hi - 16 if hi >= 8 else hi
            v = _clamp16(p + n * dL)
            out.append(v)
            s2L = s1L
            s1L = v
            dL = (_ADAPT[hi] * dL) >> 8
            dL = 16 if dL < 16 else dL
            p = (s1R * c1R + s2R * c2R) >> 8
            n = lo - 16 if lo >= 8 else lo
            v = _clamp16(p + n * dR)
            out.append(v)
            s2R = s1R
            s1R = v
            dR = (_ADAPT[lo] * dR) >> 8
            dR = 16 if dR < 16 else dR
    return out


def sfx_info(header, order="<"):
    """Fields of a 'sound' asset header (loader 0x449e40), or None.

    pe = property-bag end:  +0 u8 looping, +1 u8 is3d, +2 u32 channels,
    +6 u32 original rate, +10 u32 format (1 PCM16, 2 MS-ADPCM, 3 XMA2),
    +14 u32 sample rate.  PCM: +18 samples, +22 data bytes, +26 data.
    ADPCM: +22 samples, +26 block align, +30 seven coefficient pairs, +58 data
    bytes, +62 data.  A cue list (u32 count, then [str name][u32 time]) follows
    the data; no shipped PC sound has cues.  The rate at +14 is 44100 on every
    mono PC sound and the file's own rate on the stereo ones.

    Console (order ">", layouts read on the data of all four console sets):
    X360 is the PCM layout with format 3: +18 samples (= XMA2 frames x 512),
    +22 data bytes, +26 the 2048-byte XMA2 packets.  PS3 has its own layout
    (codec "mp3", see _ps3_sound_info).  Console records carry
    `duration_source`: "header" (the stored sample count), "frame_count"
    (stored count is 0: frames x frame size) or "none" (no duration)."""
    pe = _propbag_end(header, order)
    if pe + 30 > len(header):
        return None
    loop, is3d = header[pe], header[pe + 1]
    ch, orig, fmt, rate = struct.unpack_from(order + "4I", header, pe + 2)
    if not (1 <= ch <= 2) or fmt not in (1, 2, 3):
        return _ps3_sound_info(header, pe) if order == ">" else None
    out = dict(
        looping=bool(loop),
        is3d=bool(is3d),
        channels=ch,
        original_rate=orig,
        codec={1: "pcm16", 2: "ms-adpcm", 3: "xma2"}[fmt],
        rate=rate,
        _pe=pe,
    )
    if fmt == 2:
        if pe + 62 > len(header):
            return None
        out["samples"], out["block_align"] = struct.unpack_from(order + "2I", header, pe + 22)
        out["data_bytes"] = struct.unpack_from(order + "I", header, pe + 58)[0]
        out["data_offset"] = pe + 62
    else:
        out["samples"], out["data_bytes"] = struct.unpack_from(order + "2I", header, pe + 18)
        out["data_offset"] = pe + 26
    end = out["data_offset"] + out["data_bytes"]
    cues = []
    if fmt != 3 and end + 4 <= len(header):
        try:
            n = struct.unpack_from(order + "I", header, end)[0]
            o = end + 4
            for _ in range(n if n <= 4096 else 0):
                ln = struct.unpack_from(order + "I", header, o)[0]
                nm = header[o + 4 : o + 4 + ln].split(b"\x00")[0].decode("latin1")
                cues.append(
                    {"name": nm, "sample": struct.unpack_from(order + "I", header, o + 4 + ln)[0]}
                )
                o += 8 + ln
        except struct.error:
            cues = []
    out["cue_points"] = cues
    if fmt == 3:  # X360: the stored count is whole XMA2 frames (512 samples each)
        data = header[out["data_offset"] : end]
        out["xma_frames"] = _xma_frame_count(data) if len(data) == out["data_bytes"] else None
        out["duration_source"] = "header"
        if not out["samples"] and out["xma_frames"]:
            out["samples"] = out["xma_frames"] * 512
            out["duration_source"] = "frame_count"
    if out["samples"] and 8000 <= rate <= 96000:
        out["duration_s"] = round(out["samples"] / rate, 4)
    elif fmt == 3:
        out["duration_s"], out["duration_source"] = None, "none"
    return out


_MP3_KBPS = {
    3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),  # MPEG-1 layer III
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),  # MPEG-2 layer III
    0: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),  # MPEG-2.5
}
_MP3_RATE = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def mp3_frame_stats(data):
    """Walk the layer III frames of `data` from offset 0:
    {"frames", "samples" (frames x 1152, or x 576 for MPEG-2 / 2.5), "rate",
    "channels", "bytes" (length of the whole frames), "clean" (the walk used
    every byte)}.  frames = 0 when `data` does not start with a frame."""
    o = n = samples = 0
    rate = ch = None
    N = len(data)
    while o + 4 <= N:
        b1, b2 = data[o + 1], data[o + 2]
        ver, bi, si = (b1 >> 3) & 3, b2 >> 4, (b2 >> 2) & 3
        if data[o] != 0xFF or (b1 & 0xE0) != 0xE0 or ver == 1 or ((b1 >> 1) & 3) != 1:
            break
        if not (0 < bi < 15) or si == 3:
            break
        spf = 1152 if ver == 3 else 576
        size = spf // 8 * _MP3_KBPS[ver][bi] * 1000 // _MP3_RATE[ver][si] + ((b2 >> 1) & 1)
        if o + size > N:
            break
        if not n:
            rate, ch = _MP3_RATE[ver][si], 1 if (data[o + 3] >> 6) == 3 else 2
        n += 1
        samples += spf
        o += size
    return {
        "frames": n,
        "samples": samples,
        "rate": rate,
        "channels": ch,
        "bytes": o,
        "clean": o == N,
    }


def _ps3_sound_info(header, pe):
    """Fields of a PS3 'sound' asset header (big-endian; read on the data: the
    2,921 Part-2 and 3,953 Part-1 sounds of the PS3 disc all fit, the PS3
    loader itself was not read).  pe = property-bag end:
    +0 u8 looping, +1 u8 is3d, +2 u8 (1 on every sound; meaning not
    established), +3 u32 sample rate, +7 u32 channels, +11 u32 samples,
    +15 u32 bytes per second, +19 u32 size (32 + MP3 bytes + 0..15 padding),
    +23 the 32-byte segment header of the streams (dword 0 = MP3 bytes; dword 4,
    on looping sounds only, is the byte length of two MP3 frames, floor(2 x 1152 x
    bytes per second / rate): 384 / 417 / 768, measured on 145 of 145 looping
    sounds of both PS3 sets; inferred: the byte offset of the looped region, which
    matches the sample count of frames - 2), +55 the MP3
    frames, then the padding and a u32 cue count (0 on every shipped sound).

    `samples` counts whole MP3 frames (frames x 1152: the encoder delay and
    the padding of the last frame are inside it), so the duration runs 0.03 -
    0.06 s over the PC sound's.  A looping sound holds two frames more than
    its count.  None when the bytes do not fit this layout."""
    if pe + 59 > len(header):
        return None
    loop, is3d = header[pe], header[pe + 1]
    rate, ch, samples, bps, size, seg0 = struct.unpack_from(">6I", header, pe + 3)
    d0 = pe + 55
    if not (1 <= ch <= 2 and 8000 <= rate <= 96000 and 0 < seg0 <= len(header) - d0):
        return None
    if not (seg0 + 32 <= size <= len(header) - pe - 23):
        return None
    fs = mp3_frame_stats(header[d0 : d0 + seg0])
    if not fs["frames"]:
        return None
    out = dict(
        looping=bool(loop),
        is3d=bool(is3d),
        channels=ch,
        original_rate=None,  # the PS3 header stores one rate only
        codec="mp3",
        rate=rate,
        _pe=pe,
        samples=samples,
        data_bytes=seg0,
        data_offset=d0,
        bytes_per_second=bps,
        mp3_frames=fs["frames"],
        mp3_frame_samples=fs["samples"],
        mp3_clean=fs["clean"],
    )
    w4 = struct.unpack_from(">I", header, pe + 23 + 16)[0]
    if w4:
        out["segment_word4"] = w4
        out["segment_word4_rule"] = "2 mp3 frames in bytes"
        out["loop_skip_frames"] = 2
    cues, o = [], pe + 23 + size
    try:  # the PC cue list layout; no shipped console sound has a cue
        n = struct.unpack_from(">I", header, o)[0] if o + 4 <= len(header) else 0
        o += 4
        for _ in range(n if n <= 4096 else 0):
            ln = struct.unpack_from(">I", header, o)[0]
            nm = header[o + 4 : o + 4 + ln].split(b"\x00")[0].decode("latin1")
            cues.append({"name": nm, "sample": struct.unpack_from(">I", header, o + 4 + ln)[0]})
            o += 8 + ln
    except struct.error:
        cues = []
    out["cue_points"] = cues
    out["duration_source"] = "header"
    if not samples:
        out["samples"], out["duration_source"] = fs["samples"], "frame_count"
    out["duration_s"] = round(out["samples"] / rate, 4)
    return out


def decode_sfx(header):
    """SFX/voice 'sound' assets -> (pcm16_bytes, channels, rate). Codec tag at
    propbagEnd+10: 1 = 16-bit PCM, 2 = MS-ADPCM. The rate is the header's own
    (pe+14; the voice is created with it, 0x40271b): 44100 on every mono sound
    (resampled at bake time), the file's rate on stereo ones. pe+6 is the
    *source* rate, not playback."""
    pe = _propbag_end(header)
    if pe + 30 > len(header):
        return None
    tag = struct.unpack_from("<H", header, pe + 10)[0]
    ch = struct.unpack_from("<H", header, pe + 2)[0]
    rate = struct.unpack_from("<I", header, pe + 14)[0]
    if not (8000 <= rate <= 96000):
        rate = 44100
    if not (1 <= ch <= 2):
        return None
    if tag == 1:
        nsamp, dsz = struct.unpack_from("<II", header, pe + 18)
        if dsz == nsamp * 2 * ch and pe + 26 + dsz <= len(header):
            data = header[pe + 26 : pe + 26 + dsz]  # loader 0x449e40: data follows its size
        else:  # not that layout: the 1.3.0 slice
            data = header[pe + 30 : pe + 30 + nsamp * 2 * ch]
        return (data, ch, rate) if len(data) >= 16 else None
    if tag == 2:
        j = header.find(_COEFB, pe)
        if j < 0:
            return None
        ba = struct.unpack_from("<H", header, j - 4)[0]
        if not (16 <= ba <= 4096):
            return None
        adata = header[j + 32 :]
        pcm = _adpcm_stereo(adata, ba) if ch == 2 else _adpcm_mono(adata, ba)
        return (pcm.tobytes(), ch, rate) if len(pcm) >= 16 else None
    return None


def _smpl_chunk(rate, frames):
    """A RIFF 'smpl' chunk with one forward loop over the whole sample (the
    engine loops the whole buffer: LoopLength = sample count, 0x40228c)."""
    body = struct.pack("<9I", 0, 0, int(round(1e9 / rate)), 60, 0, 0, 0, 1, 0)
    body += struct.pack("<6I", 0, 0, 0, max(frames - 1, 0), 0, 0)
    return b"smpl" + struct.pack("<I", len(body)) + body


def write_wav(pcm_bytes, ch, rate, path, loop=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:  # closed also when a write fails
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm_bytes)
    if loop:  # append the loop chunk and fix the RIFF size
        chunk = _smpl_chunk(rate, len(pcm_bytes) // (2 * ch))
        with open(str(path), "r+b") as fh:
            fh.seek(0, 2)
            fh.write(chunk)
            size = fh.tell() - 8
            fh.seek(4)
            fh.write(struct.pack("<I", size))


_KJ = {}
_CN = {}


#: asset classes / name suffixes that some step of the toolkit decodes (extract itself,
#: binds / characters for animations, the nav and text exports).  Anything else that
#: `extract` meets is kept raw under extracted/ and counted in its summary ("raw only").
_DECODED_CLASSES = frozenset(("Texture", "Model", "ModelRes", "sound", "mediastream"))
_DECODED_SUFFIXES = (".animation", ".aipathdata", ".txt", ".wav", ".bmp", ".tga", ".model")


def _names_mod():
    """canonical_names (--names canonical|stored), imported on first use."""
    if "mod" not in _CN:
        import sys as _sys, os as _os

        _sys.path.append(_os.path.dirname(_os.path.abspath(__file__)))
        import canonical_names as _cnm

        _CN["mod"] = _cnm
    return _CN["mod"]


def _kapow_json():
    """Lazy import of kapow_json (fragment/pb/sequence/particle/... -> JSON)."""
    if "mod" not in _KJ:
        try:
            import sys as _sys, os as _os

            _sys.path.append(_os.path.dirname(_os.path.abspath(__file__)))
            import kapow_json as _kj

            _KJ["mod"] = _kj
        except Exception:
            _KJ["mod"] = None
    return _KJ["mod"]


def main(argv):
    """`extract`: see --help.  The run's name record (canonical_names.Run) is
    closed however the extraction ends."""
    try:
        return _extract_main(argv)
    finally:
        _names_mod().end()


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
        type=_model_lod_arg,
        default=0,
        metavar="N|all",
        help="which level of detail of each model to write: 0 (default) = full detail, N = that LOD (clamped per part), 'all' = every LOD in one file",
    )
    ap.add_argument(
        "--language",
        type=_language_arg,
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
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if not a.naz.exists():
        print("error: %s not found" % a.naz, file=sys.stderr)
        return 2
    _RIG["on"] = bool(getattr(a, "glb", False))
    _RIG["attrs"] = not bool(getattr(a, "no_vertex_attrs", False))
    if getattr(a, "frame", None):
        os.environ["WATCHMEN_FRAME"] = a.frame  # frame.mode() reads it
    if getattr(a, "names", None):
        os.environ["WATCHMEN_NAMES"] = a.names  # canonical_names.mode() reads it
    if _RIG["on"] and a.no_models:
        print("note: --glb requires model decoding; overriding --no-models", file=sys.stderr)
        a.no_models = False
    if _RIG["on"] and not _rig_load():
        print(
            "warning: --glb requested but rig_glb.py (or numpy) not importable; skipping rig export",
            file=sys.stderr,
        )
        _RIG["on"] = False
    log = (lambda *x: None) if a.quiet else (lambda *x: print(*x))
    do_tex = not a.no_textures and HAVE_IMG
    do_mdl = not a.no_models and HAVE_IMG
    do_extract_all = not a.no_extract_all
    if (not a.no_textures or not a.no_models) and not HAVE_IMG:
        log("note: numpy/Pillow not available -> skipping textures & models")

    entries = list(naz_entries(a.naz, warn=lambda m: log("  ! " + m)))
    log("NAZ %s : %d entries -> %s" % (a.naz, len(entries), a.out))
    # the console of a big-endian source, named by its derived root (the path of
    # a loose tree, or the block paths inside the .naz); None on PC
    run_platform = console_platform_of(a.naz)
    for e in entries:
        if run_platform:
            break
        run_platform = console_platform_of(e.name)
    blocks = {}
    console_audio = []  # (name, raw) console mediastream_s, decoded post-blocks
    pc_audio = []  # (name, raw) PC mediastream_s, split per track post-blocks
    media_meta = {}  # mediastream path (lower, no leading /) -> (ch, rate, samples)
    media_desc = {}  # same key -> (descriptor asset name, media_desc_from_header)
    music_frags = []  # (name, header, order) of fragments holding a MusicStreamSlot
    sound_info = {}  # sound asset name -> header facts (audio/sound_info.json)
    sfx_failed = []  # console sound assets no audio could be written for
    stats = dict(files=0, tex=0, mdl=0, aud=0)
    # --names: the canonical spelling of every output path, and what was respelled
    name_run = _names_mod().begin()
    # extracted/, textures/, models/ and audio/ spell every folder alike
    _names_mod().share_folders(a.out)
    names = OutputNames(log, name_run)  # one output per asset name (repeats, twins, variants)
    model_stored = {}  # model output path -> the archive's spelling of a respelled name
    tex_repeats = mdl_repeats = 0
    text_writer = None
    if not a.no_text:
        try:
            import text_assets as _ta

            text_writer = _ta.TextWriter(a.out, log)
        except Exception as ex:
            log("note: text_assets not importable (%s) -> no text/" % ex)
    n_assets = 0
    no_stream = {}  # Texture / ModelRes name -> (class, why) left without stream data
    misc = {}  # JSON kind (".font", ...) -> [assets, not fully decoded]
    raw_only = {}  # class / suffix of assets no decoder of this command reads -> count
    from_sets = {}  # stream-set file -> assets whose stream came from it

    for e in entries:
        try:
            data = naz_read(a.naz, e)
        except Exception as ex:
            log("  ! %s: %s" % (e.name, ex))
            continue
        low = e.name.lower()
        if not a.no_files:
            p = safe(a.out / "files", name_run.name(e.name))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            stats["files"] += 1
        # pair block halves; defer processing until both are read
        if low.endswith(".block_h_z") or low.endswith(".block_s_z"):
            stem = e.name[: -len("_h_z")] if low.endswith("_h_z") else e.name[: -len("_s_z")]
            blocks.setdefault(stem, {})["h" if low.endswith("_h_z") else "s"] = data
            continue
        # standalone audio (PC = Vorbis packet container; console handled after
        # the block pass so channel/rate metadata is available)
        if not a.no_audio and low.endswith(".mediastream_s"):
            try:
                if not a.flat_music and _audio_packets(data):
                    pc_audio.append((e.name, data))  # needs the descriptors
                elif decode_audio(data, safe(a.out / "audio", e.name + ".ogg"), True, log):
                    stats["aud"] += 1
                else:
                    console_audio.append((e.name, data))
            except Exception as ex:
                log("      ! audio %s: %s" % (e.name, ex))
            continue
        # standalone texture / model (paired _h_z + _s_z handled via the block dict
        # path above only for *.block_*; helper textures use *.texture_h_z etc.)
        if low.endswith(".texture_h_z") or low.endswith(".modelres_h_z"):
            blocks.setdefault(e.name[: -len("_h_z")], {})["h"] = inflate_standalone(data)
            blocks[e.name[: -len("_h_z")]]["standalone"] = True
            continue
        if low.endswith(".texture_s_z") or low.endswith(".modelres_s_z"):
            blocks.setdefault(e.name[: -len("_s_z")], {})["s"] = inflate_standalone(data)
            blocks[e.name[: -len("_s_z")]]["standalone"] = True
            continue

    # process collected blocks + standalone pairs
    # stream-only `.block_s_z` files (no header half): the stream sets of another
    # block's header name them (Part 1 Prison: four rooms)
    _stream_only = {k + "_s_z": v["s"] for k, v in blocks.items() if "h" not in v and "s" in v}
    _stream_used = {}

    def _stream_file(path, _find=stream_file_lookup(_stream_only)):
        blob = _find(path)
        if blob is not None:
            _stream_used[path] = _stream_used.get(path, 0) + 1
        return blob

    model_jobs = []  # (header, stream, out_path) -- deferred until all textures are dumped
    # blocks in a fixed order that does not depend on the letter case an archive
    # stores their paths in (OutputNames: the first copy names the output)
    for stem, hs in sorted(blocks.items(), key=lambda kv: (kv[0].lower(), kv[0])):
        if "h" not in hs:
            continue
        if hs.get("standalone"):
            header, stream = hs["h"], hs.get("s")
            low = stem.lower()
            if stream is None:
                continue
            # same registry as the block assets; the folder names a differing copy
            name, placed = standalone_output_name(names, stem, header, stream)
            if placed == "repeat":
                continue
            if do_tex and ".texture" in low:
                try:
                    if carve_texture(stream, header, safe(a.out / "textures", name), log):
                        stats["tex"] += 1
                        _mark_stored_name(safe(a.out / "textures", name), name_run.stored_of(name))
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and ".modelres" in low:
                model_jobs.append(
                    (
                        header,
                        stream,
                        safe(a.out / "models", name + ".obj"),
                        None,
                        console_platform_of(stem) or run_platform,
                    )
                )
            continue
        # real block pair
        if a.limit is not None and n_assets >= a.limit:
            break  # --limit N: stop after N block assets (was accepted but ignored)
        log("\nBLOCK %s" % stem)
        if text_writer is not None:  # text assets, all six language slots
            try:
                text_writer.add_block(hs["h"], stem)
            except Exception as ex:
                log("  ! text assets: %s" % ex)
        try:
            _rep = lambda m: log("  ! " + m)
            if a.language:
                it = list(
                    extract_block(
                        hs["h"], hs.get("s"), a.language, report=_rep, stream_files=_stream_file
                    )
                )
            else:
                it = list(
                    extract_block(hs["h"], hs.get("s"), report=_rep, stream_files=_stream_file)
                )
        except Exception as ex:
            log("  ! parse failed: %s" % ex)
            continue
        for e, header, stream in it:
            if a.limit is not None and n_assets >= a.limit:
                break
            n_assets += 1
            # script classes ("ModelEffects(ModelRes)", "TextureEffects(Texture)")
            # are read by their base class loader -> dispatch on the base name
            cls = asset_base_class(asset_class(header, BLOCK_ORDER))
            # the name this copy is written under, and whether an earlier block
            # already wrote the same bytes (OutputNames: "repeat")
            name, placed = names.place(e.name, stem, header, stream)
            low = name.lower()
            # class-name compare is case-insensitive (2026-08-17): the source had
            # both "mediastream" and "MediaStream" literals; only one spelling can
            # match the on-disk typename, and a miss here left media_meta empty
            # (console XMA then wrapped with default 2ch/48000 instead of the real
            # channel/rate/sample values).
            if not a.no_audio and cls.lower() == "mediastream":
                try:
                    mm = media_meta_from_header(header, BLOCK_ORDER)
                    if mm:
                        media_meta[mm[0].lower().lstrip("/")] = mm[1:]
                    md = media_desc_from_header(header, BLOCK_ORDER)
                    if md:
                        media_desc[md["stream"].lower().lstrip("/")] = (name, md)
                except Exception:
                    pass
            if not a.no_audio and low.endswith(".fragment") and b"MusicStreamSlot" in header:
                music_frags.append((name, header, BLOCK_ORDER))
            # dump EVERY asset raw (header + optional stream) to extracted/ for offline analysis
            if do_extract_all:
                _ep = safe(a.out / "extracted", name)
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
                    # counted once per output name (an identical copy in a later block
                    # is written again but is the same asset)
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
                                    name, header, stream, str(_ep), BLOCK_ORDER, glb=bool(a.glb)
                                )
                            else:
                                d = kj.to_json(low, header, order=BLOCK_ORDER)
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
                                import json as _json

                                with open(
                                    _ep.parent / (_ep.name + ".json"),
                                    "w",
                                    encoding="utf-8",
                                    newline="\n",
                                ) as _f:
                                    _f.write(_json.dumps(d, indent=1))
                        else:
                            _cnt[1] += _one
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
                    if BLOCK_ORDER == "<":
                        r = decode_sfx(header)
                        if r:
                            wn = name if name.lower().endswith(".wav") else name + ".wav"
                            si = sfx_info(header) or {}
                            loop = bool(si.get("looping"))
                            write_wav(
                                r[0], r[1], r[2], safe(a.out / "audio", wn), a.smpl_loops and loop
                            )
                            stats["aud"] += 1
                            if si:
                                si.pop("_pe", None)
                                si["file"] = out_rel(a.out / "audio", wn)
                                sound_info[name.replace("\\", "/").lstrip("/")] = si
                        else:
                            sfx_failed.append(name)
                            log(
                                "      WARNING: sfx %s: sound header not decoded; no audio written"
                                % name
                            )
                    else:
                        si = decode_sfx_console(
                            header,
                            BLOCK_ORDER,
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
                    if carve_texture(stream, header, safe(a.out / "textures", name), log):
                        stats["tex"] += 1
                        _mark_stored_name(safe(a.out / "textures", name), name_run.stored_of(name))
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and (cls in ("Model", "ModelRes") or ".modelres" in low):
                if placed == "repeat":
                    mdl_repeats += 1
                    continue
                if name_run.stored_of(name):
                    model_stored[safe(a.out / "models", name + ".obj")] = name_run.stored_of(name)
                model_jobs.append(
                    (
                        header,
                        stream,
                        safe(a.out / "models", name + ".obj"),
                        BLOCK_ORDER,
                        console_platform_of(stem) or run_platform,
                    )
                )
            elif not a.no_audio and (cls.lower() == "mediastream" or ".mediastream" in low):
                try:
                    if decode_audio(stream, safe(a.out / "audio", name + ".ogg"), True, log):
                        stats["aud"] += 1
                except Exception as ex:
                    log("      ! audio %s: %s" % (name, ex))

    if from_sets or _stream_only:
        log("\nSTREAM SETS: %d stream-only block file(s)" % len(_stream_only))
        for sfile, cnt in sorted(from_sets.items()):
            log("  %s: %d asset stream(s) read" % (sfile, cnt))
        _find = stream_file_lookup({k: k for k in _stream_only})
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

        jp = safe(a.out / "audio", name + ".json")
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

    for name, raw in pc_audio:
        try:
            tr = decode_audio_tracks(raw, a.out / "audio", name, True, log, _slot_labels(name))
            if tr:
                stats["aud"] += len(tr)
                _music_sidecar(name, tr, "one file per track")
            elif decode_audio(raw, safe(a.out / "audio", name + ".ogg"), True, log):
                stats["aud"] += 1
                log("      ! %s does not split into tracks: written as one file" % name)
            else:
                console_audio.append((name, raw))
        except Exception as ex:
            log("      ! audio %s: %s" % (name, ex))

    if sound_info or sfx_failed:
        import json as _json

        doc = {"format": "watchmen-sound-info/1", "sounds": dict(sorted(sound_info.items()))}
        if sfx_failed:  # marker: sound assets whose header no reader took
            doc["not_decoded"] = sorted(n.replace("\\", "/").lstrip("/") for n in sfx_failed)
        (a.out / "audio").mkdir(parents=True, exist_ok=True)
        with open(
            safe(a.out / "audio", "sound_info.json"), "w", encoding="utf-8", newline="\n"
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
        for name, raw in console_audio:
            try:
                meta = media_meta.get(name.lower().lstrip("/"))
                r = decode_console_audio(
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

    # all blocks parsed -> textures are now on disk; decode models last with the
    # full texture index so per-submesh materials resolve correctly.
    tex_index = build_texture_index(a.out / "textures")
    # SKELETON REFERENCE DUMP: decode the base *_Skeleton.model rest poses to
    # OUT/skeletons/*.json (file-decoded; see docs/ENGINE_CONSTANTS.md).  This is
    # reference output only -- the glb rig takes its joint names/order from each
    # model's OWN embedded palette in decode_model (skeleton assets have a 0-byte
    # stream, so they never enter model_jobs; collect them straight from the naz).
    if _RIG["on"]:
        try:
            import extract_skeletons as _es, json as _json

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
    _platform_before = CONSOLE_PLATFORM
    for header, stream, out_path, mo, mplat in model_jobs:
        try:
            _st = MODEL_STATUS
            _st.clear()
            set_console_platform(mplat)
            # stored_name only for a respelled model (--names canonical)
            _kw = {"stored_name": model_stored[out_path]} if out_path in model_stored else {}
            if decode_model(
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
    set_console_platform(_platform_before)

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
    if _RIG["on"]:
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
        log("  ! %s: %s" % (_names_mod().RUN_FILE, ex))
    if name_run.renamed:
        log(
            "  names       : %d written under their canonical spelling (--names stored keeps"
            " the archive's); canonical -> stored in %s"
            % (len(name_run.renamed), _names_mod().RUN_FILE)
        )
    log("  audio       : %d" % stats["aud"])
    log("  output      : %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
