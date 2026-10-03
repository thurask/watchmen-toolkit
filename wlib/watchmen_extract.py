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
    OUT/audio/      <asset>.wav (SFX/voice, MS-ADPCM/PCM@44100) | .ogg (music)
    OUT/audio/      <asset>.ogg                              (.mediastream_s = Vorbis)
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
           split into ~40 KB chunks; rebuilt into a real Ogg Vorbis file.

Usage:
    python watchmen_extract.py game.naz -o OUT
        [--no-files] [--no-textures] [--no-models] [--no-audio]
        [--exact-audio]   sample-perfect Ogg granulepos (parses Vorbis modes)
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


class NazEntry:
    __slots__ = ("name", "compr", "psize", "usize", "data_off", "path")

    def __init__(s, name, compr, psize, usize, data_off, path=None):
        s.name, s.compr, s.psize, s.usize, s.data_off = name, compr, psize, usize, data_off
        s.path = path  # set for loose-file entries (Part 1); None inside a .naz


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


def naz_entries(path):
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
            yield NazEntry(name, compr, psize, usize, hoffs + _LFH + nsize + isize)
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

    __slots__ = ("name", "type_hash", "sizes", "has_stream", "streams", "localized", "language")

    def __init__(s):
        s.name, s.type_hash, s.sizes = "", 0, [0] * BLOCK_LANGUAGES
        s.has_stream, s.streams, s.localized, s.language = False, None, False, 0

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


def parse_block_header(h, order=None):
    """The fixed 400-byte block_h_z header as a dict (engine FUN_004a36d8 /
    FUN_0049dd0e; field names follow what the loader does with each value)."""
    if len(h) < BLOCK_HEADER_SIZE:
        raise ValueError("not a block header: %d bytes, need %d" % (len(h), BLOCK_HEADER_SIZE))
    bo = order or detect_block_order(h)
    (
        sig,
        tables_size,
        entry0_size,
        io_buffer_size,
        fragment_offset,
        fragment_size,
        num_entries,
        num_localized,
        num_streams,
    ) = struct.unpack_from(bo + "9I", h, 328)
    return {
        "order": bo,
        "bounds": struct.unpack_from(bo + "8f", h, 0),  # -> LoadBlock+0x180
        "guid": h[0x24:0x48].split(b"\0", 1)[0].decode("latin1"),
        "fingerprint": fingerprint_decrypt(h[0x48:0x147]).decode("latin1"),
        "version_signature": sig,  # written, never checked by the loader
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


def _maybe_inflate(blob):
    if len(blob) >= 2 and blob[0] == 0x78:
        try:
            return zlib.decompress(blob)
        except zlib.error:
            pass
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


# WM07 stores per-texture material params in the texture header as 64-bit
# name-hashed records (verified against the game's pixel shader: $specularData.xy).
_SPEC_HI = 0xBDA17DE4
_SPEC_EXP = 0xF4142D28  # specular exponent (Blinn-Phong power)  -> c2.x
_SPEC_INT = 0xB3AB3306  # specular intensity (0 = matte)         -> c2.y


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
_TEX_DESC = 29  # FUN_00429e77: u32 w, h, format, x, type; u8 alpha; u32 mips, z


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


def parse_texture_frames(hdr):
    """ENGINE-EXACT PC Texture header (FUN_005382aa / FUN_00429e77), or None.

    [bag][u32 nFrames][u8 hasAnim] then per frame: slot-0 descriptor, 7 x
    ([u8 present][descriptor if present]), [u32 len][source path].  Returns
    {"frames": [{"slots": [desc|None]*8, "path": str}], "anim": bool, "end": off};
    desc = {slot, enum, aw, ah, mip, type (1=2D, 2=cube), alpha, drift}."""
    if not _is_texture(hdr, "<"):
        return None
    try:
        (tlen,) = struct.unpack_from("<I", hdr, 0)
        (nd,) = struct.unpack_from("<I", hdr, 4 + tlen)
        p = 4 + tlen + 4 + 4 * nd  # FUN_00511f96: bag = nd dwords
        (nf,) = struct.unpack_from("<I", hdr, p)
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
                w, h, en, _x, typ, alpha, mip, _z = struct.unpack_from("<5IBII", hdr, p)
                p += _TEX_DESC
                if en not in TEX_FMT or typ not in (1, 2) or alpha > 1:
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
                        # slot 7 is the record the stride walk used to reach through
                        # a 4-byte "drift" (four absent-slot bytes): the specSize map
                        "drift": k == 7,
                        "chain": _chain_bytes_exact(en, w, h, mip),
                    }
                )
            (sl,) = struct.unpack_from("<I", hdr, p)
            if sl > 1024 or p + 4 + sl > len(hdr):
                return None
            path = hdr[p + 4 : p + 4 + sl].split(b"\0", 1)[0].decode("latin1")
            p += 4 + sl
            frames.append({"slots": slots, "path": path})
    except (struct.error, IndexError):
        return None
    return {"frames": frames, "anim": bool(anim), "end": p}


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
    """Layer -> WM07 shader slot, verified against the character shader bytecode:
    idx0 => diffuse ($diffuseMap s0); normal ($normalMap s1, ATI2 on PC / BC5 on
    X360 / DXT5 on PS3); L8 => specSize ($specSizeMap s7, the specular-power map);
    the FIRST colour layer after the normal => specMap ($specMap s2, specular
    colour); a further colour layer => glow ($glowMap s6).
    The specSize record is additionally preceded by a 4-byte field in the header
    (the `drift` flag from _stride_layers) on ALL platforms — 45/45 specSize vs
    0/39 glow records across PC/PS3/X360, 2026-07-16.  This disambiguates X360,
    which re-encodes the L8 specSize map as DXT1 (same enum as glow)."""
    if _is_normal_layer(images, idx, order):
        return "normal"
    if idx == 0:
        return "diffuse"
    if isinstance(images[idx], dict) and images[idx].get("drift"):
        return "specSize"  # drifted record = specSize slot (any codec)
    if images[idx]["enum"] in (3, 4):  # L8 -> specular size / power
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


def extract_block(h_data, s_data, language=0):
    """Yield (entry, header, stream) for every asset.

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
    for i, e in enumerate(entries):
        if i == num and 0 <= language < BLOCK_LANGUAGES and lang_off[language]:
            cur = lang_off[language]
        dsz = e.data_size
        header = _maybe_inflate(h_data[cur : cur + dsz])
        cur += dsz
        stream = None
        if e.has_stream and s_data is not None and e.best_stream:
            off, sz = e.best_stream
            if 0 <= off and off + sz <= len(s_data):
                stream = _maybe_inflate(s_data[off : off + sz])
        yield e, header, stream


def inflate_standalone(raw):
    """Standalone _h_z/_s_z = 8-byte preamble + zlib (sometimes raw zlib)."""
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
    return None


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
    out = bytearray(we * he * bpe)
    for y in range(he):
        for x in range(we):
            s = _xg2d(x, y + yoff, alw, bpe) * bpe
            d = (y * we + x) * bpe
            if s + bpe <= len(data):
                out[d : d + bpe] = data[s : s + bpe]
    return bytes(out)


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


def carve_texture_console(stream, header, out_dir, log=None):
    """Console (X360/PS3) texture carve: decode the TOP mip of every layer to
    PNG using the console header records. Returns #PNGs written > 0."""
    if not callable(log):
        log = lambda *a, **k: None
    info = parse_texture_header(header, ">")
    if info is None or not info["images"]:
        return False
    L, _last, _end, _rs = _stride_layers(header, ">")
    if not L:
        return False
    L = _console_recover_layers(header, stream, L, _last, _end, _rs)
    out_dir.mkdir(parents=True, exist_ok=True)
    wrote = 0
    segs = _ps3_segments(stream)
    if segs is not None:  # ---- PS3
        for j, (off, sz) in enumerate(segs):
            lay = L[j % len(L)]
            pre = "" if len(segs) == len(L) else "seg%d_" % (j // len(L))
            is_norm = _is_normal_layer(L, j % len(L), ">")
            data = stream[off : off + sz]
            if TEX_FMT[lay["enum"]][1][0] != "blk":  # uncompressed (L8...) -> RSX swizzled
                data = _rsx_unswizzle(data, lay["aw"], lay["ah"], TEX_FMT[lay["enum"]][1][1])
                if TEX_FMT[lay["enum"]][1][1] == 4:  # 32bpp: BE ARGB -> PC BGRA
                    data = _texel32_to_pc(data, "ps3")
            img = _decode_one_layer(data, lay["enum"], lay["aw"], lay["ah"], normal=is_norm)
            if img is None:
                continue
            lbl = texture_layer_label(L, j % len(L), ">")
            Image.fromarray(img).save(
                out_dir
                / (
                    "%s%d_%s_%dx%d_%s.png"
                    % (pre, j % len(L), lbl, lay["aw"], lay["ah"], TEX_FMT[lay["enum"]][0])
                )
            )
            wrote += 1
        _write_spec_txt(header, out_dir)
        log(
            "      %s: PS3 %d segs -> %s/ (%d png)"
            % (info["name"] or out_dir.name, len(segs), out_dir.name, wrote)
        )
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
            en, w, h = lay["enum"], lay["aw"], lay["ah"]
            _, (kind, unit) = TEX_FMT[en]
            blk = 4 if kind == "blk" else 1
            we = max(1, (w + blk - 1) // blk)
            he = max(1, (h + blk - 1) // blk)
            # width aligned UP to 32 like every consumer (_xg2d/_x360_layer_bytes);
            # max(we,32) under-sized the tile buffer for non-pow2 widths > 32
            # blocks, zero-filling the tail of the untiled layer (2026-08-17).
            need = ((we + 31) & ~31) * ((he + 31) & ~31) * unit
            buf = _bswap16(stream[off : off + min(need, len(stream) - off)])
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
            img = _decode_one_layer(lin, en, w, h)
            if img is not None:
                pre = "" if reps == 1 else "seg%d_" % r
                lbl = texture_layer_label(L, j, ">")
                Image.fromarray(img).save(
                    out_dir / ("%s%d_%s_%dx%d_%s.png" % (pre, j, lbl, w, h, TEX_FMT[en][0]))
                )
                wrote += 1
            off += sizes[j]
    _write_spec_txt(header, out_dir)
    log(
        "      %s: X360 layers=%d x%d (%s stream %d) -> %s/ (%d png)"
        % (
            info["name"] or out_dir.name,
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


def _decode_sub(stream, vbo, nv, stride, be=False):
    """Vertex fields.  PC (44/56): pos f32x3 @0, normal half3 @12, uv half2 @24.
    Console (32/44): pos f32x3 @0 (BE), normal 11:11:10 u32 @12, color @16,
    uv BE half2 @20 (then packed tangents; skinned: idx u8x4 @32, weight half4 @36)."""
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
    return verts, norms, uvs


_TEX_RE = re.compile(rb"/[ -~]*?\.(?:bmp|tga|dds|png|jpg)", re.I)


def extract_materials(header):
    """Ordered texture basenames from the ModelRes header material list (one per
    render submesh, in submesh order, for character/prop models)."""
    out = []
    for m in _TEX_RE.finditer(header):
        b = m.group().decode("latin1").replace("\\", "/").split("/")[-1]
        out.append(b.rsplit(".", 1)[0])
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


def build_texture_index(tex_root):
    """basename(lower) -> texture output dir (which holds <j>_<label>_<WxH>_<FMT>.png)."""
    idx = {}
    try:
        for p in sorted(Path(tex_root).rglob("*_diffuse_*.png")):
            idx.setdefault(p.parent.name.rsplit(".", 1)[0].lower(), p.parent)
    except Exception:
        pass
    return idx


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
    mtl_path = path.with_suffix(".mtl")
    objdir = path.parent
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# %s  (%d verts, %d tris, %d submeshes)\n" % (name, len(v), len(tris), len(subs)))
        f.write("mtllib %s\n" % mtl_path.name)
        for p in v:
            f.write("v %.6f %.6f %.6f\n" % p)
        if uv:
            for u, w in uv:
                f.write("vt %.6f %.6f\n" % (u, 1.0 - w))
        if n:
            for nn in n:
                f.write("vn %.6f %.6f %.6f\n" % nn)
        for si, (base, vc, tstart, tcount, st) in enumerate(subs):
            mat = _san(mats[si]) if si < len(mats) else ("submesh_%d" % si)
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
        for raw in mats:
            mm = _san(raw)
            if mm in seen:
                continue
            seen.add(mm)
            mf.write("newmtl %s\n" % mm)
            mf.write("Kd 0.8 0.8 0.8\n")
            texdir = (
                None
                if (str(raw).startswith("submesh_") or not tex_index)
                else tex_index.get(str(raw).lower())
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
                dif = _find_layer(texdir, "diffuse")
                nrm = _find_layer(texdir, "normal")
                spm = _find_layer(texdir, "specMap")
                sps = _find_layer(texdir, "specSize")
                glw = _find_layer(texdir, "glow")
                if dif:
                    mf.write("map_Kd %s\n" % _rel(dif))
                    mf.write("map_d %s\n" % _rel(dif))  # transparency from diffuse alpha
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
                rough = _make_roughness(texdir, sps, exp)
                if rough:
                    mf.write("map_Ns %s\n" % _rel(rough))
                if glw:
                    mf.write("map_Ke %s\n" % _rel(glw))
            mf.write("\n")


# ---- rigged/textured .glb export (optional; --glb). FILE-DERIVED (2026-07-13):
#      the flat skin rig takes its joint names + palette ORDER from the model's own
#      embedded skeleton header (extract_skeletons.skeleton_from_header), so the old
#      capture artifacts (skeleton_female_biped.json / bundled_clip_*.npz) are no
#      longer read. Emitted glbs are bind-pose; engine-exact ANIMATED per-character
#      glbs come from the QA'd file-only pipeline: `watchmen.py characters` (binds ->
#      bake -> variant glbs). ----
_RIG = {"on": False, "mod": None, "loaded": False}


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
_VOLUME_FLOATS = {5: 3, 6: 1, 7: 2}  # box / sphere / capsule (FUN_00524b23)


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
    m = {"bbox_center": r.floats(3), "bbox_half": r.floats(3)}
    m["has_color"] = r.u8()  # source flag bit 1 (builder 0x0043426c)
    m["has_alpha"] = r.u8()  # source flag bit 2
    if r.boolean():  # FUN_0042f9c1: cloth / physics side arrays
        r.u8()
        for sz in (12, 2, 12, 2, 2):
            r.skip(r.count(sz) * sz)
    m["vertex_flags"], m["vertex_count"], m["format"] = r.u32(), r.u32(), r.u32()
    m["index_flags"], m["index_bytes"], m["ix"] = r.u32(), r.u32(), r.u32()
    if m["format"] >= len(VERTEX_STRIDES) or m["index_bytes"] % 2:
        raise ValueError("vertex format %d" % m["format"])
    return m


def _mr_part(r, pi, buffers):
    """Part / pivot node, FUN_00545927; submesh records FUN_00542541."""
    P = {"pos": r.floats(3), "quat": r.floats(4), "name": r.string()}
    P["f1"], P["parent"] = r.u32(), r.u32()
    P["lods"] = []
    for li in range(r.count(4)):
        lod = []
        for si in range(r.count(20)):
            sm = {"name": r.string()}
            sm["tex_index"] = [r.u32() for _ in range(r.count(4))]
            sm["b24"], inline, sm["u28"] = r.boolean(), r.boolean(), r.u32()
            sm["dynamic_copy"], sm["no_defer"] = r.boolean(), r.boolean()
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
            r.boolean()
            r.u32()
            mb = _mr_meshbuffer(r)
            mb.update(kind="shadow", part=pi, lod=None, name="", tex_index=[])
            P["shadow"].append(mb)
            buffers.append(mb)
    P["proxy"] = None
    if r.boolean():  # one coarse format-5 slab per part (doors, walls, containers)
        mb = _mr_meshbuffer(r)
        mb.update(kind="proxy", part=pi, lod=None, name="", tex_index=[])
        P["proxy"] = mb
        buffers.append(mb)
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
    for _ in range(r.count(12)):  # FUN_00561d1c
        r.skip(r.count(20) * 20)
        r.skip(r.count(12) * 12)
        r.skip(r.count(4) * 4)
    return P


def parse_model_header(header, order="<"):
    """ModelRes header -> dict, or None when the blob does not follow the Part 2
    layout (console/Part 1 variants, truncated data): callers then fall back to
    the descriptor scan.

    {"type", "textures": [path], "texture_flags", "pivotbooks", "bbox_center",
     "bbox_half", "parts": [{name, pos, quat, f1, parent, lods: [[submesh]],
     shadow: [buf], proxy: buf|None}], "buffers": [buf in STREAM order], "end"}
    Every buf has kind ('render' | 'shadow' | 'proxy'), part, lod, name,
    tex_index, format, vertex_count, index_bytes, has_color, has_alpha, bbox_*."""
    if asset_base_class(asset_class(header, order)).lower() not in ("modelres", "model"):
        return None
    try:
        r = _Rd(header, order)
        M = {"type": r.string()}
        r.skip(r.count(4) * 4)  # property bag: dword count (FUN_00511f96)
        r.u32()
        M["has_skeleton"] = r.boolean()
        r.u32()
        M["has_cloth"] = r.boolean()
        r.skip(r.count(32) * 32)
        r.skip(r.count(4) * 4)
        M["bbox_center"], M["bbox_half"] = r.floats(3), r.floats(3)
        tex = [(r.boolean(), r.string()) for _ in range(r.count(5))]
        M["texture_flags"] = [t[0] for t in tex]
        M["textures"] = [t[1] for t in tex]
        M["pivotbooks"] = [r.string() for _ in range(r.count(4))]
        buffers = []
        M["parts"] = [_mr_part(r, pi, buffers) for pi in range(r.count(40))]
        M["buffers"] = buffers
        M["end"] = r.p  # physics / cloth / animation-event tail follows
    except (ValueError, struct.error, IndexError):
        return None
    return M


def model_stream_layout(model, stream, order="<"):
    """Locate every buffer of `model` (parse_model_header) in the stream blob.
    Adds vb / ib / stride / clusters=(offset, count) to each buffer and returns
    the buffer list, or None unless the layout consumes the stream EXACTLY."""
    p, n = 0, len(stream)
    try:
        for b in model["buffers"]:
            b["stride"] = VERTEX_STRIDES[b["format"]]
            b["vb"] = p
            p += b["vertex_count"] * b["stride"]
            b["ib"] = p
            p += b["index_bytes"]
            (nc,) = struct.unpack_from(order + "I", stream, p)
            b["clusters"] = (p + 4, nc)
            p += 4 + nc * 40
            (nl,) = struct.unpack_from(order + "I", stream, p)
            p += 4
            for _ in range(nl):
                p += 8 + struct.unpack_from(order + "I", stream, p + 4)[0] * 0x44
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


def _language_arg(v):
    import argparse

    try:
        n = int(v)
    except ValueError:
        n = -1
    if not 0 <= n < BLOCK_LANGUAGES:
        raise argparse.ArgumentTypeError(
            "expected a language slot 0..%d, got %r" % (BLOCK_LANGUAGES - 1, v)
        )
    return n


def select_model_buffers(model, lod=0, kinds=("render",)):
    """Buffers of the requested kinds, in stream order.  `lod`: an int picks that
    LOD of every part (clamped to the part's last LOD); 'all' / None keeps all."""
    lod = check_lod(lod)
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


def decode_vertex_attributes(stream, buf):
    """Numpy views of ONE located buffer (model_stream_layout) beyond what the
    OBJ writer uses.  Keys present depend on the vertex format:
      color      (N,4) uint8 RGBA                       (formats 5, 6)
      tangent    (N,3) float32  = dP/du                 (formats 5, 6)
      bitangent  (N,3) float32  = dP/dv                 (formats 5, 6)
      joints     (N,4) uint8, weights (N,4) float32 raw (formats 6, 10)"""
    lay = VERTEX_FORMATS.get(buf["format"])
    if lay is None or not HAVE_IMG:
        return {}
    nv, st = buf["vertex_count"], buf["stride"]
    a = np.frombuffer(stream, np.uint8, nv * st, buf["vb"]).reshape(nv, st)
    half = lambda off, k: np.ascontiguousarray(a[:, off : off + 2 * k]).view("<f2")
    out = {}
    if "color" in lay:
        c = lay["color"]
        out["color"] = np.ascontiguousarray(a[:, [c + 2, c + 1, c, c + 3]])
    if "tangent" in lay:
        out["tangent"] = half(lay["tangent"], 3).astype(np.float32)
        out["bitangent"] = half(lay["bitangent"], 3).astype(np.float32)
    if "joints" in lay:
        j = lay["joints"]
        out["joints"] = np.ascontiguousarray(a[:, [j + 2, j + 1, j, j + 3]])
        out["weights"] = half(lay["weights"], 4).astype(np.float32)
    return out


def gltf_tangents(normals, tangents, bitangents):
    """(N,4) float32 glTF TANGENT: unit tangent + handedness sign of the stored
    bitangent against cross(normal, tangent)."""
    n = np.asarray(normals, np.float32)
    t = np.asarray(tangents, np.float32)
    b = np.asarray(bitangents, np.float32)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    t = np.where(ln > 1e-9, t / np.maximum(ln, 1e-9), np.array([[1.0, 0.0, 0.0]], np.float32))
    w = np.where((np.cross(n, t) * b).sum(1) < 0, -1.0, 1.0).astype(np.float32)
    return np.concatenate([t, w[:, None]], 1).astype(np.float32)


def decode_model_mesh(header, stream, lod=0, kinds=("render",)):
    """Header-driven PC mesh decode.  Returns None when the header path does not
    apply (use decode_model's scan fallback), else
    {"model": parse_model_header dict, "submeshes": [ {name, kind, part, lod,
      format, stride, material (texture stem or None), texture (path or None),
      positions, normals, uvs  (python lists, same values as the OBJ writer gets),
      triangles [(a, b, c)] local indices, vb, ib,
      + decode_vertex_attributes() keys} ]}."""
    M = parse_model_header(header, "<")
    if M is None or stream is None or model_stream_layout(M, stream, "<") is None:
        return None
    subs = []
    for b in select_model_buffers(M, lod, kinds):
        nv, st = b["vertex_count"], b["stride"]
        verts, norms, uvs = _decode_sub(stream, b["vb"], nv, st, False)
        if "uv" not in VERTEX_FORMATS.get(b["format"], {}):
            uvs = None
        idx = struct.unpack_from("<%dH" % (b["index_bytes"] // 2), stream, b["ib"])
        ti = b["tex_index"][0] if b["tex_index"] else None
        tex = M["textures"][ti] if ti is not None and ti < len(M["textures"]) else None
        d = {
            "name": b["name"],
            "kind": b["kind"],
            "part": b["part"],
            "lod": b["lod"],
            "format": b["format"],
            "stride": st,
            "vb": b["vb"],
            "ib": b["ib"],
            "texture": tex,
            "material": _material_stem(tex) if tex else None,
            "positions": verts,
            "normals": norms,
            "uvs": uvs,
            "triangles": [idx[i : i + 3] for i in range(0, len(idx) - 2, 3)],
        }
        d.update(decode_vertex_attributes(stream, b))
        subs.append(d)
    return {"model": M, "submeshes": subs}


def _header_model_plan(header, stream, lod):
    """Render buffers of the requested LOD with exact stream offsets, or None when
    the engine-exact header path does not apply to this model."""
    M = parse_model_header(header, "<")
    if M is None or not stream or model_stream_layout(M, stream, "<") is None:
        return None
    bufs = [b for b in select_model_buffers(M, lod) if b["format"] in (5, 6)]
    if not bufs:
        return None
    return M, bufs


def decode_model(header, stream, out_path, tex_index=None, log=None, order=None, lod=0):
    """Per-submesh OBJ (+ .mtl linking the diffuse/normal/specular/glossiness maps
    dumped to textures/), each material named by its texture.

    PC models are decoded HEADER-DRIVEN (parse_model_header: every buffer offset
    and the texture-list index of each submesh come from the file).  `lod` picks
    the level of detail written: 0 (default) = the full-detail mesh, an int = that
    LOD, 'all' = every LOD.  Shadow hulls and per-part proxy slabs are never
    written.  Anything the header path rejects (console files, Part 1 variants)
    takes the descriptor scan: strict-validated VB search, then the single-run
    _pick_vb scan.  With --glb, also emits a rigged + textured .glb for skinned
    (stride-56) character models."""
    if tex_index is None:
        tex_index = {}
    if not callable(log):
        log = lambda *a, **k: None
    hplan = _header_model_plan(header, stream, lod) if order in (None, "<") else None
    if hplan:
        order = "<"
    elif order is None:  # auto: pick the order with MORE descriptors
        # (a BE model can throw a stray false-positive LE descriptor, so "LE if
        # non-empty" mis-detects those -- compare counts instead).
        order = (
            ">" if len(find_descriptors(header, ">")) > len(find_descriptors(header, "<")) else "<"
        )
    be = order == ">"
    if hplan:
        descs = [(b["vertex_count"], b["stride"], b["index_bytes"]) for b in hplan[1]]
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
            verts, norms, uvs = _decode_sub(stream, vbo, nv, stride, be)
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
            for t in range(ib // 6):
                a, b, c = struct.unpack_from(order + "3H", stream, ibo + t * 6)
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
        pick = _pick_vb(stream)
        if pick is None:
            return False
        off, stride, be, nv, idx = pick
        if nv < 8:
            return False
        verts, norms, uvs = _decode_sub(stream, off, nv, stride, be)
        ntri = len(idx) // 3
        if ntri == 0:
            return False
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
        return False
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
            materials.append(_material_stem(tex[ti[0]]) if ok else "submesh_%d" % k)
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
    if rig and have_skin and SKIN_I and len(SKIN_I) == len(subs):
        try:
            import numpy as _np

            SI = _np.concatenate(SKIN_I)
            SW = _np.concatenate(SKIN_W)
            glb_path = out_path.with_suffix(".glb")
            _is_body = _model_is_body(header)  # head/accessory -> own palette, emit static
            pal = _model_palette(header)
            need = int(SI.max()) + 1 if SI.size else 0
            names = [b["name"] for b in pal["bones"]] if pal else []
            if len(names) < need:
                names += ["bone_%d" % i for i in range(len(names), need)]
            pal = {"bone_count": len(names), "bones": [{"name": x} for x in names]}
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
            )
            log(
                "      %s glb (%d joints, bind pose) -> %s"
                % ("rigged" if _is_body else "static", pal["bone_count"], glb_path.name)
            )
        except Exception as ex:
            log("      ! rig glb %s: %s" % (out_path.stem, ex))
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


def decode_audio(raw, out_path, exact, log=None):
    if not callable(log):
        log = lambda *a, **k: None
    pk = _audio_packets(raw)
    headers = [p for p in pk if p and p[0] in (1, 3, 5)][:3]
    audio = [p for p in pk if p and p[0] not in (1, 3, 5)]
    if len(headers) < 3 or not audio:
        return False
    if headers[0][:7] != b"\x01vorbis":
        return False
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
    out = _ogg_page(1, 0, 0, 0x02, [headers[0]]) + _ogg_page(1, 1, 0, 0, [headers[1], headers[2]])
    seq = 2
    for i, p in enumerate(audio):
        out += _ogg_page(1, seq, gr[i], 0x04 if i == len(audio) - 1 else 0, [p])
        seq += 1
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    log(
        "      Vorbis %dch %dHz %d pkts -> %s (%.1fs)"
        % (ch, rate, len(audio), out_path.name, gr[-1] / rate)
    )
    return True


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
            tf.write(container)
            tf.close()
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
    """Console inline 'sound' assets (PC uses decode_sfx).  X360: codec tag 3 =
    XMA2 packets at pe+30 ([pe+4 u16 ch][pe+14 u32 rate][pe+18 u32 samples]
    [pe+22 u32 dataSize], dataSize % 2048 == 0).  PS3: MP3 frames from the first
    frame sync after the propbag (self-describing; a BE u32 near pe = size)."""
    pe = _propbag_end(header, order)
    if pe + 30 > len(header):
        return False
    ch = struct.unpack_from(order + "H", header, pe + 4)[0]
    codec = struct.unpack_from(order + "I", header, pe + 10)[0]
    rate = struct.unpack_from(order + "I", header, pe + 14)[0]
    nsamp = struct.unpack_from(order + "I", header, pe + 18)[0]
    dsz = struct.unpack_from(order + "I", header, pe + 22)[0]
    if codec == 3 and 1 <= ch <= 2 and dsz and dsz % 2048 == 0 and pe + 30 + dsz <= len(header):
        data = header[pe + 30 : pe + 30 + dsz]
        if not (8000 <= rate <= 96000):
            rate = 44100
        ns = min(nsamp, 0xFFFFFFFF) or _xma_frame_count(data) * 512
        return _emit_audio(
            _xma2_riff(data, ch, rate, ns),
            ".xma",
            name,
            out_dir,
            vgmstream_cli,
            log,
            "XMA-SFX",
            keep_container,
        )
    for i in range(pe, min(len(header) - 4, pe + 256)):
        if header[i] == 0xFF and (header[i + 1] & 0xE0) == 0xE0:
            best = None
            for o in range(pe, min(pe + 64, len(header) - 4)):
                v = struct.unpack_from(">I", header, o)[0]
                if 0 < v <= len(header) - i and (len(header) - i) - v < 512:
                    best = v
                    break
            data = header[i : i + best] if best else header[i:]
            return _emit_audio(
                data, ".mp3", name, out_dir, vgmstream_cli, log, "MP3-SFX", keep_container
            )
    return False


def decode_console_audio(name, raw, out_dir, meta, vgmstream_cli, log, keep_container=False):
    """Decode one console mediastream_s. meta = (ch, rate, samples) or None.
    Writes .wav via vgmstream-cli when available; else .mp3 (PS3) / .xma (X360)."""
    r = _console_media_parse(raw)
    if r is None:
        return False
    codec, data = r
    ch, rate, samples = meta if meta else (None, None, None)
    if codec == "mp3":
        container, ext = data, ".mp3"
    else:
        nsamp = min(samples or (_xma_frame_count(data) * 512), 0xFFFFFFFF)
        container, ext = _xma2_riff(data, ch or 2, rate or 48000, nsamp), ".xma"
    return _emit_audio(
        container, ext, name, out_dir, vgmstream_cli, log, codec.upper(), keep_container
    )


# ===========================================================================
# Driver
# ===========================================================================
def safe(base, name):
    """Archive entry name -> a path guaranteed to stay under `base`.

    Entry names are attacker-controlled (rot-2 obfuscated, not authenticated), so
    strip '..'/absolute anchors AND ':' -- pathlib treats 'C:/x' as a new anchor
    on Windows and would otherwise escape `base` entirely."""
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    parts = [p.replace(":", "_") for p in parts]
    out = base.joinpath(*parts) if parts else base / "_unnamed"
    if os.path.commonpath([os.path.abspath(base), os.path.abspath(out)]) != os.path.abspath(base):
        raise ValueError("unsafe archive entry name %r" % name)
    return out


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


def decode_sfx(header):
    """SFX/voice 'sound' assets -> (pcm16_bytes, channels, 44100). Codec tag at
    propbagEnd+10: 1 = 16-bit PCM, 2 = MS-ADPCM. The engine resamples every PC sound
    to 44100 Hz at storage (the field at pe+6 is the *source* rate, not playback)."""
    pe = _propbag_end(header)
    if pe + 30 > len(header):
        return None
    tag = struct.unpack_from("<H", header, pe + 10)[0]
    ch = struct.unpack_from("<H", header, pe + 2)[0]
    rate = 44100
    if not (1 <= ch <= 2):
        return None
    if tag == 1:
        nsamp = struct.unpack_from("<I", header, pe + 18)[0]
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


def write_wav(pcm_bytes, ch, rate, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    w = wave.open(str(path), "wb")
    w.setnchannels(ch)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(pcm_bytes)
    w.close()


_KJ = {}


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
        "--limit", type=int, default=None, metavar="N", help="stop after N block assets (debug)"
    )
    ap.add_argument(
        "--model-lod",
        type=_model_lod_arg,
        default=0,
        metavar="N|all",
        help="which level of detail of each PC model to write: 0 (default) = full detail, N = that LOD (clamped per part), 'all' = every LOD in one file",
    )
    ap.add_argument(
        "--language",
        type=_language_arg,
        default=0,
        metavar="0..5",
        help="language slot used for localized block assets (per-language header blobs and streams); default 0",
    )
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    if not a.naz.exists():
        print("error: %s not found" % a.naz, file=sys.stderr)
        return 2
    _RIG["on"] = bool(getattr(a, "glb", False))
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

    entries = list(naz_entries(a.naz))
    log("NAZ %s : %d entries -> %s" % (a.naz, len(entries), a.out))
    blocks = {}
    console_audio = []  # (name, raw) console mediastream_s, decoded post-blocks
    media_meta = {}  # mediastream path (lower, no leading /) -> (ch, rate, samples)
    stats = dict(files=0, tex=0, mdl=0, aud=0)
    n_assets = 0

    for e in entries:
        try:
            data = naz_read(a.naz, e)
        except Exception as ex:
            log("  ! %s: %s" % (e.name, ex))
            continue
        low = e.name.lower()
        if not a.no_files:
            p = safe(a.out / "files", e.name)
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
                if decode_audio(data, safe(a.out / "audio", e.name + ".ogg"), True, log):
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
    model_jobs = []  # (header, stream, out_path) -- deferred until all textures are dumped
    for stem, hs in sorted(blocks.items()):
        if "h" not in hs:
            continue
        if hs.get("standalone"):
            header, stream = hs["h"], hs.get("s")
            name = stem.split("/")[-1]
            low = stem.lower()
            if stream is None:
                continue
            if do_tex and ".texture" in low:
                try:
                    if carve_texture(stream, header, safe(a.out / "textures", name), log):
                        stats["tex"] += 1
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and ".modelres" in low:
                model_jobs.append((header, stream, safe(a.out / "models", name + ".obj"), None))
            continue
        # real block pair
        if a.limit is not None and n_assets >= a.limit:
            break  # --limit N: stop after N block assets (was accepted but ignored)
        log("\nBLOCK %s" % stem)
        try:
            if a.language:
                it = list(extract_block(hs["h"], hs.get("s"), a.language))
            else:
                it = list(extract_block(hs["h"], hs.get("s")))
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
            name = e.name
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
                except Exception:
                    pass
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
                    )
                ):
                    try:
                        kj = _kapow_json()
                        if kj:
                            d = kj.to_json(low, header, order=BLOCK_ORDER)
                            if d:
                                import json as _json

                                with open(
                                    _ep.parent / (_ep.name + ".json"),
                                    "w",
                                    encoding="utf-8",
                                    newline="\n",
                                ) as _f:
                                    _f.write(_json.dumps(d, indent=1))
                    except Exception as ex:
                        log("      ! json %s: %s" % (name, ex))
            # SFX / voice 'sound' assets keep their PCM INLINE in the header
            # (stream is None) -> handle these before the stream-None skip below.
            if not a.no_audio and cls == "sound":
                try:
                    if BLOCK_ORDER == "<":
                        r = decode_sfx(header)
                        if r:
                            wn = name if name.lower().endswith(".wav") else name + ".wav"
                            write_wav(r[0], r[1], r[2], safe(a.out / "audio", wn))
                            stats["aud"] += 1
                    elif decode_sfx_console(
                        header, BLOCK_ORDER, name, a.out / "audio", a.vgmstream_cli, log, a.keep_xma
                    ):
                        stats["aud"] += 1
                except Exception as ex:
                    log("      ! sfx %s: %s" % (name, ex))
                continue
            if stream is None:
                continue
            if do_tex and cls == "Texture":
                try:
                    if carve_texture(stream, header, safe(a.out / "textures", name), log):
                        stats["tex"] += 1
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and (cls in ("Model", "ModelRes") or ".modelres" in low):
                model_jobs.append(
                    (header, stream, safe(a.out / "models", name + ".obj"), BLOCK_ORDER)
                )
            elif not a.no_audio and (cls.lower() == "mediastream" or ".mediastream" in low):
                try:
                    if decode_audio(stream, safe(a.out / "audio", name + ".ogg"), True, log):
                        stats["aud"] += 1
                except Exception as ex:
                    log("      ! audio %s: %s" % (name, ex))

    # console music: block pass done -> per-stream channel/rate metadata known
    if console_audio:
        log(
            "\nCONSOLE AUDIO: %d streams (vgmstream: %s)"
            % (len(console_audio), a.vgmstream_cli or "not set")
        )
        for name, raw in console_audio:
            try:
                meta = media_meta.get(name.lower().lstrip("/"))
                if decode_console_audio(
                    name, raw, a.out / "audio", meta, a.vgmstream_cli, log, a.keep_xma
                ):
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
        except Exception as _ex:
            log("  ! skeleton pass: %s" % _ex)
    model_lod = a.model_lod
    log("\nMODELS: %d  (textures indexed: %d)" % (len(model_jobs), len(tex_index)))
    for header, stream, out_path, mo in model_jobs:
        try:
            if decode_model(header, stream, out_path, tex_index, log, order=mo, lod=model_lod):
                stats["mdl"] += 1
        except Exception as ex:
            log("      ! model %s: %s" % (out_path.name, ex))

    log("\nDONE  (%d assets across %d blocks)" % (n_assets, len(blocks)))
    log("  files       : %d" % stats["files"])
    log("  textures    : %d" % stats["tex"])
    log("  models      : %d" % stats["mdl"])
    log("  audio       : %d" % stats["aud"])
    log("  output      : %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
