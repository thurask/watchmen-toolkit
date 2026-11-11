"""A Kapow block: `<name>.block_h_z` (directory + per-asset header blobs) and
`<name>.block_s_z` (per-asset zlib streams); standalone `_h_z` / `_s_z` files
and `.mediastream_s` too.  The block header, directory and trailer
(`parse_block_header`, `parse_block_toc`, `parse_block_trailer`), the byte order
of the block (`detect_block_order`, `BLOCK_ORDER`), language slots and stream
sets, one asset's header and stream (`extract_block`, `maybe_inflate`,
`inflate_standalone`), asset types and classes, and the property-bag walk
(`prop_walk`, `propbag_end`).
"""

import functools
import hashlib
import itertools
import os
import struct
import sys
import zlib

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
from wutil import order_name  # noqa: E402

import extract_log  # noqa: E402
import naz_archive  # noqa: E402


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
    import kapow_props as _kp

    fn = getattr(_kp, "name_hash", None)
    return (
        fn(s)
        if fn
        else _kp.kapow_hash(bytes(c & 0xDF for c in s.encode("latin1")).decode("latin1"))
    )


def props_module():
    """kapow_props, imported like _name_hash does (flat wlib module)."""
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


@functools.cache
def _asset_types():
    """{name hash: asset-type name} of ASSET_TYPE_NAMES (read-only)."""
    return {_name_hash(n): n for n in ASSET_TYPE_NAMES}


def asset_type_name(type_hash):
    """Directory type hash -> asset-type name ('' when unknown)."""
    return _asset_types().get(type_hash, "")


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

    # --- alias names of the same fields (read + write) --
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
    return props_module().kapow_hash(field.decode("latin1"))


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
        "unknown_327": h[327],  # alias of fingerprint_display
        # the four bytes of fingerprint_crc as stored: 0a 88 3f 59 in every staged
        # block, NOT byte-swapped on the consoles.
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
                t.streams = list(itertools.batched(v, 2))  # (offset, size) per language
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
                    "streams": list(itertools.batched(v, 2)),  # (offset, size) per language
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
    if loose is not None:  # parsed, but short of the blob's end
        return loose
    first_error.add_note(
        "block trailer at 0x%X, %d bytes, %s: read with 3-float and with 4-float stream-set "
        "bounds" % (start, size, order_name(bo))
    )
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


def maybe_inflate(blob, type_name=None, report=None):
    """A block blob as the engine reads it.  With a known asset `type_name` the
    type decides (asset_compressed): raw for `mediastream`, zlib for every other
    type, and a blob that then does not inflate is reported through `report`
    (a callable taking the zlib error text) and returned as stored.  Without a
    type the first byte is sniffed."""
    comp = asset_compressed(type_name)
    if comp is False:
        return blob
    if comp or (len(blob) >= 2 and blob[0] == 0x78):
        try:
            return naz_archive.inflate(blob)
        except zlib.error as ex:
            if comp and report is not None:
                report(str(ex))
    return blob


def asset_class(header, order=None):
    if len(header) < 8:
        return "unknown"
    for bo in (order,) if order else ("<", ">"):
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
    try:
        entries, data_start = parse_block_toc(h_data, language=language)
        bo = BLOCK_ORDER
        num = struct.unpack_from(bo + "I", h_data, NUM_TABLES_OFFSET)[0]
        lang_off = struct.unpack_from(bo + "6I", h_data, 364)
    except (struct.error, ValueError) as ex:
        ex.add_note("block header: %d bytes, language slot %r" % (len(h_data), language))
        raise
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

        try:
            header = maybe_inflate(h_data[cur : cur + dsz], e.type_name, failed("header"))
            stream = None
            if e.has_stream and s_data is not None and e.best_stream:
                off, sz = e.best_stream
                if 0 <= off and off + sz <= len(s_data):
                    stream = maybe_inflate(s_data[off : off + sz], e.type_name, failed("stream"))
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
                        stream = maybe_inflate(blob[off : off + sz], e.type_name, failed("stream"))
                        e.stream_file, e.stream_note = sfile, None
                        break
                if e.stream_note and report is not None:
                    report("%s: no stream (%s)" % (e.name, e.stream_note))
        except (zlib.error, ValueError, struct.error) as ex:
            ex.add_note(
                "block asset %s (record %d, type %s, %s): header blob at 0x%X, %d bytes"
                % (e.name, i, e.type_name or "0x%08x" % e.type_hash, order_name(bo), cur, dsz)
            )
            raise
        cur += dsz
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
    is the source CRC is read from code elsewhere and is not checked on files."""
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
                return naz_archive.inflate(raw[start:])
            except zlib.error:
                pass
    return maybe_inflate(raw)


def header_order_or_none(header):
    """header_order(), or None when `header` is not something it reads (error notes)."""
    try:
        return header_order(header)
    except Exception:
        return None


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


def language_arg(v):
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


def prop_walk(H, order="<"):
    """Walk the salt-prefixed property records after [typeName][classId].
    Part 2 (WM07) records are 20 bytes ([salt][hashLo][hashHi][tag][val],
    +4 when tag==2); Part 1 (WM06) records are 16 bytes ([salt][hash][tag]
    [val], +4 when tag==2). The stride is auto-detected by which one yields
    more consecutive salt hits. Returns (end_offset, base_record_size).  The
    walk stops after _PROP_WALK_CAP records; a bag that goes on past that gets
    a WARNING line (once per distinct header), since the end offset then lies
    inside the bag."""
    tlen = struct.unpack_from(order + "I", H, 0)[0]
    p = 4 + tlen + 4
    if p + 4 > len(H):
        return p, 20
    salt = struct.unpack_from(order + "I", H, p)[0]

    def walk(rs, tagoff):
        q = p
        n = 0
        while (
            q + rs <= len(H)
            and struct.unpack_from(order + "I", H, q)[0] == salt
            and n < _PROP_WALK_CAP
        ):
            tag = struct.unpack_from(order + "I", H, q + tagoff)[0]
            q += rs + 4 if tag == 2 else rs
            n += 1
        return n, q

    n1, q1 = walk(16, 8)
    n2, q2 = walk(20, 12)
    q, rs = (q1, 16) if n1 > n2 else (q2, 20)
    if (
        max(n1, n2) == _PROP_WALK_CAP
        and q + rs <= len(H)
        and struct.unpack_from(order + "I", H, q)[0] == salt
    ):
        key = hashlib.sha1(bytes(H[:q])).digest()
        if key not in _PROP_WALK_WARNED:
            _PROP_WALK_WARNED.add(key)
            extract_log.warn(
                "      WARNING: %s header: property bag has more than %d records; the walk "
                "stopped inside it, offsets read after the bag are not reliable"
                % (
                    bytes(H[4 : 4 + tlen]).split(b"\0")[0].decode("ascii", "replace"),
                    _PROP_WALK_CAP,
                )
            )
    return q, rs


#: prop_walk: most property records walked
_PROP_WALK_CAP = 64
#: prop_walk: headers already reported as running past the cap
_PROP_WALK_WARNED = set()


def propbag_end(H, order="<"):
    return prop_walk(H, order)[0]
