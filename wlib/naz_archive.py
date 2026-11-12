"""The `.naz` archive: an obfuscated ZIP (file names rotate-left-2 encrypted,
custom EOCD / central-directory magics).  Entries (`naz_entries`, or
`loose_entries` for a directory of loose files such as Part 1's `derived_pc`),
their engine key (`naz_key`), one entry's bytes (`naz_read`), the bounded zlib
inflate (`inflate`, `MAX_INFLATE`), and the walk over the block pairs one block
at a time (`block_plan`, `iter_blocks`).
"""

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
import byte_reader  # noqa: E402


class ArchiveError(byte_reader.ReadError):
    """An archive or one of its entries that does not read: not a `.naz`, a bad
    central-directory record, an unknown compression method, an entry that does
    not inflate to its stated size, a blob past the inflate ceiling."""


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
            ex = ArchiveError("not a NAZ archive (%d bytes, shorter than the EOCD record)" % fsize)
            ex.add_note("archive %s" % (path,))
            raise ex
        f.seek(fsize - _EOCD)
        magic, _dk, _dkc, _di, titem, _ds, doffs, _cs = struct.unpack(_EOCD_FMT, f.read(_EOCD))
        if magic != NAZ_HEAD:
            ex = ArchiveError("not a NAZ archive (EOCD magic 0x%08X)" % magic)
            ex.add_note(
                "archive %s: EOCD record at 0x%X of %d bytes" % (path, fsize - _EOCD, fsize)
            )
            raise ex
        cur = doffs
        for i in range(titem):
            try:
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
                    raise ArchiveError("bad central-dir magic at 0x%X" % cur)
                f.seek(cur + _CD)
                name = _decrypt_name(f.read(nsize))
            except (struct.error, ValueError) as ex:
                ex.add_note(
                    "archive %s: central-directory record %d of %d at 0x%X" % (path, i, titem, cur)
                )
                raise
            if compr and warn is not None:
                warn(
                    "%s: compression method %d -- the engine reads archive entries as "
                    "stored (0x4428fb reads no method field)" % (name, compr)
                )
            yield NazEntry(
                name, compr, psize, usize, hoffs + _LFH + nsize + isize, key=naz_key(name)
            )
            cur += _CD + nsize + isize + csize


#: ceiling on the inflated size of one zlib blob (an archive entry, a block
#: asset's header or stream, a standalone `_h_z` / `_s_z` file); a blob that
#: inflates past it is refused with ArchiveError instead of filling the memory
#: (a decompression bomb).  The largest blob of the shipped archives inflates to
#: MAX_INFLATE_MEASURED bytes; $WATCHMEN_MAX_INFLATE (bytes) overrides the
#: ceiling.
MAX_INFLATE = 256 << 20


def max_inflate():
    """The inflate ceiling in bytes: $WATCHMEN_MAX_INFLATE when set (a positive
    integer), else MAX_INFLATE."""
    v = os.environ.get("WATCHMEN_MAX_INFLATE")
    if v:
        try:
            n = int(v, 0)
        except ValueError:
            raise ValueError("WATCHMEN_MAX_INFLATE must be a number of bytes, not %r" % v)  # noqa: B904
        if n <= 0:
            raise ValueError("WATCHMEN_MAX_INFLATE must be positive, not %r" % v)
        return n
    return MAX_INFLATE


def inflate(blob, wbits=zlib.MAX_WBITS, limit=None):
    """zlib.decompress(blob, wbits) with a size ceiling: the same bytes, or the
    same zlib.error, for a blob that inflates to at most `limit` bytes (default
    max_inflate()); ArchiveError for one that inflates past it -- decided after
    inflating at most limit + 1 bytes, so the memory stays bounded."""
    cap = max_inflate() if limit is None else limit
    d = zlib.decompressobj(wbits)
    out = d.decompress(blob, cap)
    if d.eof:
        return out
    if len(out) >= cap:
        # output stopped at the ceiling: one more byte decides (the end of the
        # stream may still be pending in the unconsumed input)
        more = d.decompress(d.unconsumed_tail, 1)
        if more:
            raise ArchiveError(
                "zlib blob inflates past %d bytes (the inflate ceiling, "
                "$WATCHMEN_MAX_INFLATE)" % cap
            )
        if d.eof:
            return out
    # truncated or corrupt below the ceiling: zlib.decompress raises its own error
    # (bounded: the stream ends before the ceiling)
    return zlib.decompress(blob, wbits)


def naz_read(path, e):
    if getattr(e, "path", None) is not None:  # loose Part 1 file
        with open(e.path, "rb") as f:
            return f.read()
    with open(path, "rb") as f:
        f.seek(e.data_off)
        raw = f.read(e.psize)
    try:
        match e.compr:
            case 0:
                return raw
            case 8:
                return _naz_inflate(e, raw)
        raise ArchiveError("unsupported compression %d for %s" % (e.compr, e.name))
    except (zlib.error, ValueError) as ex:
        ex.add_note(
            "archive %s: entry %s, %d bytes stored at 0x%X, method %d, %d bytes inflated"
            % (path, e.name, e.psize, e.data_off, e.compr, e.usize)
        )
        raise


def _naz_inflate(e, raw):
    """The bytes of a method-8 archive entry `e` (raw deflate) from its stored
    bytes `raw`: the central directory states the inflated size, which bounds
    the output (and must not pass the inflate ceiling)."""
    cap = max_inflate()
    if e.usize > cap:
        raise ArchiveError(
            "%s: the archive says it inflates to %d bytes, past the "
            "inflate ceiling %d ($WATCHMEN_MAX_INFLATE)" % (e.name, e.usize, cap)
        )
    d = zlib.decompressobj(-15)
    out = d.decompress(raw, e.usize) if e.usize else b""
    more = b"" if d.eof else d.decompress(d.unconsumed_tail if e.usize else raw, 1)
    if more or len(out) != e.usize or not d.eof:
        got = "more than %d bytes" % len(out) if more else "%d bytes" % len(out)
        if not more and not d.eof:
            got += " (the deflate stream ends early)"
        raise ArchiveError("%s: inflates to %s, the archive says %d" % (e.name, got, e.usize))
    return out


def block_plan(naz):
    """{block stem: {"h": NazEntry, "s": NazEntry}} of the `.block_h_z` /
    `.block_s_z` entries of an archive (or loose tree), in the order a stem's
    first half appears in its directory; a later entry of the same name replaces
    the earlier one.  Reads the directory only."""
    plan = {}
    for e in naz_entries(naz):
        low = e.name.lower()
        if low.endswith(".block_h_z"):
            plan.setdefault(e.name[: -len("_h_z")], {})["h"] = e
        elif low.endswith(".block_s_z"):
            plan.setdefault(e.name[: -len("_s_z")], {})["s"] = e
    return plan


def iter_blocks(naz, streams=True):
    """Yield (stem, {"h": header bytes, "s": stream bytes}) for every block of
    an archive (or loose tree), one block at a time, in block_plan order: the
    pairs `grab_blocks` returns, without holding the archive.  A half the
    archive does not have is not in the dict.  streams=False reads the header
    halves only (no "s" key) and skips the stream-only blocks -- enough to find
    an asset's header (clips, skeletons) at a fraction of the reading."""
    for stem, hs in block_plan(naz).items():
        if not streams and "h" not in hs:
            continue
        out = {}
        for k in ("h", "s") if streams else ("h",):
            if k in hs:
                out[k] = naz_read(naz, hs[k])
        yield stem, out
