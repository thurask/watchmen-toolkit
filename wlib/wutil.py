"""Small helpers shared by the wlib modules.

One copy of what many modules need: reading a file's bytes,
loading the toolkit's ``.npz`` files without pickle, loading the shipped
``.pkl`` tables without letting them name a class or function, the
quaternion -> matrix conventions, and the GLB buffer packer.

This module imports only the standard library at import time (numpy is
imported inside the functions that need it): ``watchmen hash`` and
``gendata keys-import`` import modules that use it and must not pay for, or
fail on, numpy.
"""

import pickle
import struct

__all__ = [
    "default_naz",
    "read_bytes",
    "NpzData",
    "load_npz",
    "PICKLE_HINT",
    "restricted_load",
    "restricted_loads",
    "qmat_xyzw",
    "qmats_xyzw",
    "qrows_conj_xyzw",
    "GlbPacker",
    "glb_bytes",
    "LONG_PATH_LIMIT",
    "long_path",
    "plain_path",
    "rel_path",
    "order_name",
    "platform_name",
]


def default_naz():
    """The archive a command reads when none is named: ``01_game.naz`` in the
    current directory when it exists, else ``game.naz`` there (every command and
    library default uses this one rule)."""
    import os

    return "01_game.naz" if os.path.exists("01_game.naz") else "game.naz"


def read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


# ---- .npz without pickle ------------------------------------------------------

#: What to do about a bind / bake / cache .npz that holds Python objects.
PICKLE_HINT = "rebuild it with watchmen binds NAZ OUT_DIR"


class NpzData(dict):
    """The arrays of an ``.npz`` file, all read when it is loaded (the file is
    closed again at once).  Answers the parts of numpy's ``NpzFile`` the toolkit
    uses: ``z[key]``, ``key in z``, ``z.files``, ``with ... as z`` and
    ``close()``."""

    @property
    def files(self):
        return list(self.keys())

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def load_npz(path, hint=None):
    """The arrays of the ``.npz`` (or the array of the ``.npy``) at `path`,
    loaded with ``allow_pickle=False``.

    The files the toolkit writes hold numbers and unicode strings only, which
    need no pickle; a file that holds Python objects (an object array, as
    numpy writes for a list of mixed types) could run code when it is
    unpickled, so it is refused: ``ValueError: <path> holds Python objects;
    rebuild it with watchmen binds NAZ OUT_DIR`` (`hint` replaces the part after
    the semicolon); so is a file without an .npy / .npz header, which numpy would
    read as a pickle."""
    import numpy as np

    try:
        z = np.load(path, allow_pickle=False)
        if isinstance(z, np.ndarray):
            return z
        with z:
            return NpzData((k, z[k]) for k in z.files)
    except ValueError as ex:
        if "allow_pickle" not in str(ex):
            raise
        if "Object arrays" in str(ex):  # an array of Python objects inside the file
            raise ValueError("%s holds Python objects; %s" % (path, hint or PICKLE_HINT)) from ex
        # no .npy / .npz header: numpy would unpickle the whole file
        raise ValueError(
            "%s is not an .npz / .npy file (it would be read as a pickle); %s"
            % (path, hint or PICKLE_HINT)
        ) from ex


# ---- pickle tables without code ----------------------------------------------


#: The only names a plain-data pickle may name: the constructors protocols 0-3
#: write for a set, a frozenset and a bytearray (protocol 4 and later have opcodes
#: for them).  They build their argument and nothing else.
_PLAIN_GLOBALS = {
    (m, n) for m in ("builtins", "__builtin__") for n in ("set", "frozenset", "bytearray")
}


class _PlainDataUnpickler(pickle.Unpickler):
    """An unpickler that builds containers, numbers and strings only: a pickle
    that names a class or a function (``GLOBAL`` / ``STACK_GLOBAL``, the way a
    pickle runs code) is refused -- set, frozenset and bytearray excepted -- and so
    is a persistent id."""

    def find_class(self, module, name):
        if (module, name) in _PLAIN_GLOBALS:
            import builtins

            return getattr(builtins, name)
        raise pickle.UnpicklingError(
            "the pickle names %s.%s; the toolkit's tables hold plain data only" % (module, name)
        )

    def persistent_load(self, pid):
        raise pickle.UnpicklingError("the pickle holds a persistent id; plain data only")


def restricted_load(fh):
    """``pickle.load(fh)`` for plain data: dicts, lists, tuples, sets, numbers,
    strings, bytes, None and booleans.  Anything else raises
    ``pickle.UnpicklingError`` before any object of it is built (measured
    with ``pickletools``: the two shipped tables, kapow_fragment_keys.pkl and
    prop_hash_dict.pkl, protocol 4, use none of the opcodes that name a class).
    Bytes (and bytearrays) in a protocol 0-2 pickle are written as a call of
    _codecs.encode and are refused; the toolkit writes protocol 4 or later."""
    return _PlainDataUnpickler(fh).load()


def restricted_loads(data):
    """`restricted_load` of a bytes object."""
    import io

    return restricted_load(io.BytesIO(data))


# ---- error notes -----------------------------------------------------------------

#: How an error note names a byte order: by the platforms that store it.
_ORDER_NAMES = {"<": "little-endian (PC)", ">": "big-endian (Xbox 360 / PS3)"}


def order_name(order, unknown="byte order not known"):
    """A byte order (``"<"`` / ``">"``) in words for an error note, the one wording
    every note uses; `unknown` for anything else (None: not decided yet)."""
    return _ORDER_NAMES.get(order, unknown)


def platform_name(plat, order):
    """The platform of a file for an error note: the console the source names
    (`plat`, "x360" / "ps3"), else PC for a little-endian file, else 'console not
    known'."""
    return plat or ("PC" if order == "<" else "console not known")


# ---- quaternion -> rotation matrix ------------------------------------------------
#
# Conventions (one place for every module):
#   * quaternions are (x, y, z, w) as the files store them, unless a name says wxyz;
#   * qmat_xyzw / qmats_xyzw give the matrix M of the rotation v -> q v q* (the
#     "standard" one: M @ v rotates the column vector v);
#   * qrows_conj_xyzw gives the rows of the engine's own rule v -> q* v q, which
#     is the transpose of M (watchmen_extract's model-part transforms);
#   * a wxyz quaternion goes through qmat_xyzw((x, y, z, w)).
# The expressions are those of the copies they replaced, term for term, so every
# caller computes the same floats as before (the test suite's outputs are
# byte-identical, measured).


def qmat_xyzw(q):
    """3x3 numpy matrix of v -> q v q* for q = (x, y, z, w); q is used as given
    (not normalised: pass a unit quaternion)."""
    import numpy as np

    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def qmats_xyzw(q):
    """(..., 3, 3) float64 matrices of v -> q v q* for an array of (x, y, z, w)
    quaternions (..., 4); each is normalised first (a zero one stays zero)."""
    import numpy as np

    q = np.asarray(q, np.float64)
    q = q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    M = np.empty(q.shape[:-1] + (3, 3))
    M[..., 0, 0] = 1 - 2 * (y * y + z * z)
    M[..., 0, 1] = 2 * (x * y - z * w)
    M[..., 0, 2] = 2 * (x * z + y * w)
    M[..., 1, 0] = 2 * (x * y + z * w)
    M[..., 1, 1] = 1 - 2 * (x * x + z * z)
    M[..., 1, 2] = 2 * (y * z - x * w)
    M[..., 2, 0] = 2 * (x * z - y * w)
    M[..., 2, 1] = 2 * (y * z + x * w)
    M[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return M


def qrows_conj_xyzw(q):
    """Rows (three 3-tuples of Python floats) of v -> q* v q, the engine's rule for
    a stored (x, y, z, w) quaternion: the transpose of qmat_xyzw(q)."""
    x, y, z, w = (float(c) for c in q)
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)),
        (2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)),
        (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)),
    )


# ---- GLB buffer packing ---------------------------------------------------------


class GlbPacker:
    """The binary buffer of a glTF document and its bufferViews / accessors (the
    one packer of rig_glb, variant_glb, nav_data and terrain_asset).

    ``views`` and ``accessors`` are the document's own lists (appended to);
    ``bin`` is the bytearray of the BIN chunk.  Every view starts on a 4-byte
    boundary.  With ``share`` on, a view of bytes already written (with the same
    target) is the earlier view, and an accessor of an existing (view,
    componentType, count, type) is the earlier accessor -- the identical data of
    two outfit nodes is written once (sharing the accessor, not the view: a view
    shared by two accessors would need a byteStride)."""

    def __init__(self, views, accessors, binbuf=None):
        self.views = views
        self.accessors = accessors
        self.bin = bytearray() if binbuf is None else binbuf
        self.share = False
        self._view_keys = {}
        self._acc_keys = {}

    def align(self):
        """Pad the buffer with zero bytes to a multiple of 4."""
        while len(self.bin) % 4:
            self.bin.append(0)

    def view(self, data, target=None):
        """Index of a bufferView holding `data` (bytes-like); `target` (34962 /
        34963) is written when given."""
        if self.share:
            import hashlib

            key = (hashlib.sha1(bytes(data)).digest(), target)
            if key in self._view_keys:
                return self._view_keys[key]
        self.align()
        bv = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        self.bin.extend(data)
        if target is not None:
            bv["target"] = target
        self.views.append(bv)
        if self.share:
            self._view_keys[key] = len(self.views) - 1
        return len(self.views) - 1

    def accessor(self, bv, ct, count, typ, mn=None, mx=None, normalized=False):
        """Index of an accessor of view `bv`: componentType `ct`, `count` elements of
        type `typ`; `normalized` and min / max (both, when `mn` is given) are
        written when given."""
        key = (bv, ct, count, typ)
        if self.share and key in self._acc_keys:
            return self._acc_keys[key]
        a = {"bufferView": bv, "componentType": ct, "count": count, "type": typ}
        if normalized:
            a["normalized"] = True
        if mn is not None:
            a["min"] = mn
            a["max"] = mx
        self.accessors.append(a)
        if self.share:
            self._acc_keys[key] = len(self.accessors) - 1
        return len(self.accessors) - 1


def glb_bytes(doc, binbuf, empty_bin_chunk=True):
    """The .glb file of the glTF document `doc` (a dict) and its binary buffer:
    the JSON chunk (compact, space-padded) and the BIN chunk (zero-padded; left
    out when the buffer is empty and `empty_bin_chunk` is false)."""
    import json

    jb = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    jb += b" " * (-len(jb) % 4)
    bb = bytes(binbuf)
    bb += b"\x00" * (-len(bb) % 4)
    with_bin = bool(bb) or empty_bin_chunk
    total = 12 + 8 + len(jb) + ((8 + len(bb)) if with_bin else 0)
    out = [b"glTF", struct.pack("<II", 2, total), struct.pack("<I", len(jb)), b"JSON", jb]
    if with_bin:
        out += [struct.pack("<I", len(bb)), b"BIN\x00", bb]
    return b"".join(out)


# ---- Windows path length ----------------------------------------------------------

#: Absolute paths at least this long get the Windows extended-length form
#: (MAX_PATH is 260 including the drive and the terminating NUL; the margin keeps
#: a file's .tmp sibling and short suffixes inside it).
LONG_PATH_LIMIT = 240
_EXT = "\\\\?\\"


def long_path(path, nt=None):
    """`path` in the Windows extended-length form ``\\\\?\\C:\\...`` (``\\\\?\\UNC\\server\\...``
    for a network path) when Windows is the system (`nt`; default ``os.name ==
    "nt"``) and the absolute path is LONG_PATH_LIMIT characters or longer, so that
    it opens even where long paths are not enabled; otherwise `path` unchanged.
    A str gives a str, a pathlib path a path of the same type."""
    import os

    if not (os.name == "nt" if nt is None else nt):
        return path
    import ntpath

    s = str(path)
    if s.startswith(_EXT):
        return path
    a = ntpath.normpath(ntpath.abspath(s) if os.name == "nt" else s)
    if len(a) < LONG_PATH_LIMIT or not ntpath.isabs(a):
        return path
    ext = _EXT + "UNC\\" + a.removeprefix("\\\\") if a.startswith("\\\\") else _EXT + a
    return ext if isinstance(path, str) else type(path)(ext)


def plain_path(path):
    """`path` (str or pathlib path) as a str without the extended-length prefix
    long_path adds, for os.path.relpath against a path that has none."""
    s = str(path)
    if s.startswith(_EXT + "UNC\\"):
        return "\\\\" + s.removeprefix(_EXT + "UNC\\")
    return s.removeprefix(_EXT)


def rel_path(path, start):
    """os.path.relpath of two paths either of which may be in the extended-length
    form."""
    import os

    return os.path.relpath(plain_path(path), plain_path(start))
