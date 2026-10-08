"""frame -- the coordinate frame of everything the toolkit writes for a viewer.

The engine is left-handed (+Y up, characters face +Z, a character's left hand
at -X).  glTF is right-handed.  Two output frames exist:

  "true"      (default)  x = -engine x.  Right-handed, +Y up, facing +Z kept;
              a character's LEFT hand is at +X and text on a sign reads the
              right way round.  Marker: coordinate_frame = "right-handed-true".
  "mirrored"  engine numbers verbatim, which a right-handed viewer shows as a
              mirror image.  This is what 1.3.0 wrote; the files carry NO
              marker and are byte-identical to it.

`--frame true|mirrored` on the command line sets $WATCHMEN_FRAME, which mode()
reads -- the same pattern as --materials / $WATCHMEN_MATERIALS.

The reflection R is x -> -x, S = diag(-1, 1, 1):
  vectors / positions / normals   (x, y, z)    -> (-x, y, z)
  rotation quaternions            (x, y, z, w) -> (x, -y, -z, w)
  matrices                        M            -> S M S
  glTF TANGENT                    xyz as a vector, w negated
  triangles                       winding reversed
  yaw about +Y                    negated
Scales, UVs, colours, weights and times do not change.  S M S keeps every
transform a proper rotation: there is no negative scale anywhere in a file.

reflect_gltf() applies R to a finished glTF document (JSON dict + binary
buffer) in place; every GLB writer calls finish_gltf() just before it
serialises.  The scalar helpers below are for JSON side data.
"""

import os
import struct

import numpy as np

ENV = "WATCHMEN_FRAME"
MODES = ("true", "mirrored")
DEFAULT_MODE = "true"
#: key of the marker (GLB: asset.extras.watchmen.<key>; JSON: top level)
MARKER_KEY = "coordinate_frame"
NOTE_KEY = "coordinate_frame_note"
TRUE = "right-handed-true"
#: what a file WITHOUT the marker is in (1.3.0 files and --frame mirrored)
MIRRORED = "engine-mirrored"
NOTES = {
    "true": (
        "right-handed, +Y up, x = -engine x: a character facing +Z has its LEFT hand at "
        "+X (bone names L / R are truthful); written by --frame true (default)"
    ),
    "mirrored": (
        "engine (left-handed) coordinates verbatim in right-handed glTF: a MIRROR IMAGE, "
        "a character facing +Z has its LEFT hand at -X; written by --frame mirrored and "
        "by toolkit 1.3.0 (files in this frame carry no coordinate_frame key)"
    ),
}
#: for raw values the toolkit copies from the game files
ENGINE_NOTE = (
    "engine coordinates (left-handed, +Y up). In a file whose coordinate_frame is "
    "'right-handed-true', GLB x = -engine x: negate x of a position or direction and "
    "turn a quaternion (x, y, z, w) into (x, -y, -z, w); a yaw angle changes sign"
)


def mode(value=None):
    """The frame in force: `value`, else $WATCHMEN_FRAME, else "true"."""
    v = value or os.environ.get(ENV) or DEFAULT_MODE
    if v not in MODES:
        raise ValueError("frame must be one of %s, not %r" % (", ".join(MODES), v))
    return v


def is_true(value=None):
    return mode(value) == "true"


def marker(value=None):
    """The coordinate_frame value of files written in this mode."""
    return TRUE if is_true(value) else MIRRORED


def frame_of(doc):
    """ "true" / "mirrored" for a JSON document (or any dict holding the marker):
    no marker means mirrored (1.3.0 and --frame mirrored)."""
    return "true" if isinstance(doc, dict) and doc.get(MARKER_KEY) == TRUE else "mirrored"


# ---------------------------------------------------------------- scalar helpers
def _z(x):
    """Negate without leaving a -0.0 in a JSON file."""
    return -x + 0.0


def vec(v):
    """Position / direction [x, y, z, ...] -> reflected copy (a list).  x comes
    back as a float (-x + 0.0, so never -0.0); the other entries are returned
    as they were given."""
    v = list(v)
    v[0] = _z(v[0])
    return v


def xz(p):
    """[x, z] pair -> reflected copy."""
    return [_z(p[0]), p[1]]


def quat(q):
    """Rotation quaternion (x, y, z, w) -> (x, -y, -z, w).  The same rule for the
    glTF convention and for the engine's (conj(q) v q): it is S R S either way."""
    return [q[0], _z(q[1]), _z(q[2]), q[3]]


def yaw_deg(a, half_open_low=True):
    """Yaw about +Y in degrees -> its reflection, in the field's own range:
    [-180, 180) when half_open_low (anim_meta), else (-180, 180] (atan2)."""
    if a is None:
        return None
    b = _z(float(a))
    if half_open_low:
        return -180.0 if b >= 180.0 else b
    return 180.0 if b <= -180.0 else b


_M34 = (1, 2, 3, 4, 8)  # row-major 3x4: entries with exactly one index on x
_M44_COL = (1, 2, 3, 4, 8, 12)  # column-major 4x4 (glTF), same entries


def mat34(m):
    """Row-major 3x4 (12 numbers) -> S M S."""
    m = list(m)
    for i in _M34:
        m[i] = _z(m[i])
    return m


def mat4(M):
    """4x4 (or 3x3) numpy matrix -> S M S (copy)."""
    M = np.array(M, dtype=float)
    M[0, 1:] = -M[0, 1:]
    M[1:, 0] = -M[1:, 0]
    return M + 0.0


def tangents(T4):
    """(n, 4) glTF TANGENT -> reflected: xyz as a vector, w negated (the bitangent
    glTF rebuilds is cross(N, T) * w, and cross(S n, S t) = -S cross(n, t))."""
    t = np.array(T4, np.float32)
    t[:, 0] = -t[:, 0]
    t[:, 3] = -t[:, 3]
    return t


# ---------------------------------------------------------------- glTF document
_NP = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
# op -> (accessor type, columns to negate)
_OPS = {
    "vec3": ("VEC3", (0,)),
    "tan4": ("VEC4", (0, 3)),
    "quat": ("VEC4", (1, 2)),
    "mat4": ("MAT4", _M44_COL),
}


class FrameError(ValueError):
    """A glTF document the reflection does not cover (never written silently)."""


def _plan(j):
    """{accessor index: op} for every accessor that holds spatial data."""
    ops = {}

    def want(acc, op, what):
        if acc is None:
            return
        old = ops.get(acc)
        if old is not None and old != op:
            raise FrameError("accessor %d is used as %s and as %s (%s)" % (acc, old, op, what))
        ops[acc] = op

    for mi, mesh in enumerate(j.get("meshes") or []):
        for pi, prim in enumerate(mesh.get("primitives") or []):
            what = "mesh %d primitive %d" % (mi, pi)
            at = prim.get("attributes") or {}
            want(at.get("POSITION"), "vec3", what)
            want(at.get("NORMAL"), "vec3", what)
            want(at.get("TANGENT"), "tan4", what)
            for tg in prim.get("targets") or []:
                for k in ("POSITION", "NORMAL", "TANGENT"):
                    want(tg.get(k), "vec3", what)
            pmode = prim.get("mode", 4)
            if pmode == 4:
                if prim.get("indices") is None:
                    raise FrameError("%s: triangles without indices" % what)
                want(prim["indices"], "tri", what)
            elif pmode in (5, 6):
                raise FrameError("%s: triangle strips / fans are not supported" % what)
            else:
                want(prim.get("indices"), "keep", what)
    for si, skin in enumerate(j.get("skins") or []):
        want(skin.get("inverseBindMatrices"), "mat4", "skin %d" % si)
    for ai, anim in enumerate(j.get("animations") or []):
        sm = anim.get("samplers") or []
        for ch in anim.get("channels") or []:
            path = (ch.get("target") or {}).get("path")
            out = sm[ch["sampler"]].get("output")
            what = "animation %d" % ai
            if path == "translation":
                want(out, "vec3", what)
            elif path == "rotation":
                want(out, "quat", what)
            else:
                want(out, "keep", what)
    return ops


def _span(A, views):
    """(start, end) byte range of an accessor in buffer 0, or None when it has no
    buffer view there."""
    if A.get("bufferView") is None:
        return None
    bv = views[A["bufferView"]]
    if bv.get("buffer", 0) != 0:
        return None
    size = _NCOMP[A["type"]] * np.dtype(_NP[A["componentType"]]).itemsize
    n = A.get("count", 0)
    off = bv.get("byteOffset", 0) + A.get("byteOffset", 0)
    stride = bv.get("byteStride") or size
    return off, (off + stride * (n - 1) + size if n > 0 else off)


def reflect_gltf(j, binbuf):
    """Reflect a finished glTF document in place (x -> -x): vertex data, inverse
    bind matrices, node transforms, animation outputs, accessor bounds, triangle
    winding.  `binbuf`: the bytearray of buffer 0.  -> number of accessors rewritten.

    Raises FrameError for anything it does not cover (sparse or interleaved
    accessors, integer-typed spatial data, an accessor shared by two roles, byte
    ranges that overlap without being the same data in the same role)."""
    ops = _plan(j)
    accs = j.get("accessors") or []
    views = j.get("bufferViews") or []
    # Every accessor of buffer 0 in byte order, so that an overlap of any two
    # ranges is seen: two accessors on exactly the same bytes in the same role are
    # rewritten once; any other overlap with rewritten bytes is refused.
    order = []
    for ai, A in enumerate(accs):
        op = ops.get(ai)
        if op == "keep":
            op = None
        if op is not None:
            if "sparse" in A:
                raise FrameError("accessor %d is sparse" % ai)
            bv = views[A["bufferView"]]
            if bv.get("buffer", 0) != 0 or bv.get("byteStride"):
                raise FrameError("accessor %d: unsupported buffer view" % ai)
        span = _span(A, views)
        if span is not None and (op is not None or span[1] > span[0]):
            order.append((span[0], span[1], ai, op))
    order.sort(key=lambda r: (r[0], r[1], r[2]))
    done = {}
    end_rewritten = end_kept = -1  # furthest byte reached by each kind so far
    count = 0
    for off, end, ai, op in order:
        A = accs[ai]
        if op is None:
            if off < end_rewritten:
                raise FrameError("accessor %d overlaps reflected data but is not reflected" % ai)
            end_kept = max(end_kept, end)
            continue
        ct, typ, n = A["componentType"], A["type"], A["count"]
        key = (off, ct, typ, n)
        # two accessors on the same bytes (identical data written once): once only
        if done.get(off) == (key, op):
            pass
        elif off < end_rewritten or (off < end_kept and end > off):
            raise FrameError(
                "accessor %d overlaps another accessor's bytes (different range or role)" % ai
            )
        else:
            done[off] = (key, op)
            end_rewritten = max(end_rewritten, end)
            if op == "tri":
                if typ != "SCALAR" or ct not in (5121, 5123, 5125) or n % 3:
                    raise FrameError("accessor %d: not a triangle index list" % ai)
                a = np.frombuffer(binbuf, _NP[ct], n, off).reshape(-1, 3)
                a[:, [1, 2]] = a[:, [2, 1]]
            else:
                want_type, cols = _OPS[op]
                if typ != want_type or ct != 5126:
                    raise FrameError(
                        "accessor %d: %s needs float %s, found %s/%d" % (ai, op, want_type, typ, ct)
                    )
                k = _NCOMP[typ]
                a = np.frombuffer(binbuf, "<f4", n * k, off).reshape(n, k)
                idx = list(cols)
                a[:, idx] = -a[:, idx]
            del a
        # bounds: a negated component swaps its min and max (index lists keep theirs)
        if op != "tri" and ("min" in A or "max" in A):
            k = _NCOMP[A["type"]]
            if "min" not in A or "max" not in A or len(A["min"]) != k or len(A["max"]) != k:
                raise FrameError(
                    "accessor %d: min / max must both be given, %d numbers each" % (ai, k)
                )
            lo, hi = list(A["min"]), list(A["max"])
            for c in _OPS[op][1]:
                lo[c], hi[c] = _z(A["max"][c]), _z(A["min"][c])
            A["min"], A["max"] = lo, hi
        count += 1
    for nd in j.get("nodes") or []:
        if "translation" in nd:
            nd["translation"] = vec(nd["translation"])
        if "rotation" in nd:
            nd["rotation"] = quat(nd["rotation"])
        if "matrix" in nd:
            m = list(nd["matrix"])
            for i in _M44_COL:
                m[i] = _z(m[i])
            nd["matrix"] = m
    return count


def stamp_gltf(j, value=None):
    """Write the marker into asset.extras.watchmen (true frame only: files in the
    mirrored frame stay exactly as they were)."""
    if not is_true(value):
        return j
    w = j.setdefault("asset", {}).setdefault("extras", {}).setdefault("watchmen", {})
    w[MARKER_KEY] = TRUE
    w[NOTE_KEY] = NOTES["true"]
    return j


def finish_gltf(j, binbuf, value=None):
    """Last step of every GLB writer: in the true frame reflect the document and
    stamp it; in the mirrored frame do nothing at all."""
    if is_true(value):
        reflect_gltf(j, binbuf)
        stamp_gltf(j, "true")
    return j


def stamp_json(doc, value=None, after="format"):
    """A JSON document with the marker (true frame) placed right after `after`;
    the same object, untouched, in the mirrored frame."""
    if not is_true(value) or not isinstance(doc, dict):
        return doc
    out = {}
    put = False
    for k, v in doc.items():
        if k in (MARKER_KEY, NOTE_KEY):
            continue
        out[k] = v
        if k == after:
            out[MARKER_KEY] = TRUE
            out[NOTE_KEY] = NOTES["true"]
            put = True
    if not put:
        out = dict(((MARKER_KEY, TRUE), (NOTE_KEY, NOTES["true"])), **out)
    doc.clear()
    doc.update(out)
    return doc


def glb_frame(path):
    """ "true" / "mirrored" for a GLB on disk (None when it is not a GLB): looks
    for the marker in the JSON chunk."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(20)
            if len(head) < 20 or head[:4] != b"glTF":
                return None
            n = struct.unpack_from("<I", head, 12)[0]
            js = fh.read(n)
    except OSError:
        return None
    key = ('"%s"' % MARKER_KEY).encode()
    i = js.find(key)
    if i < 0:
        return "mirrored"
    tail = js[i + len(key) : i + len(key) + 8 + len(TRUE)]
    return "true" if ('"%s"' % TRUE).encode() in tail else "mirrored"
