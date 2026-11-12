"""Model mesh decoding: a ModelRes stream's vertex and index buffers as
arrays, read where the header puts them (`decode_model_mesh`,
`decode_mesh_vertices`, `decode_vertex_attributes`, `gltf_tangents`,
`half_to_float`) or found by the descriptor scan for a header neither layout
reads (`find_descriptors`, `pick_vertex_buffer`, `vb_ok`, `ib_ok`); the console
platform and vertex-colour byte order (`console_platform`,
`set_console_platform`, `detect_console_platform`, `console_platform_for`,
`console_color_order`, `CONSOLE_COLOR_ORDERS`); and the restored eyelash UVs
(`LASH_RESTORE`, `lash_strips`, `lash_restored_uvs`, `lash_is_restored`).
"""

import itertools
import os
import struct
import sys

import numpy as np

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
import kapow_block  # noqa: E402
import material_refs  # noqa: E402
import model_header  # noqa: E402
import naz_archive  # noqa: E402


def is_finite_float(v):
    if v != v or abs(v) == float("inf"):
        return False
    return v == 0.0 or (1e-9 < abs(v) < 1e4)


def _vb_run(buf, off, stride, be):
    fmt = ">3f" if be else "<3f"
    n = 0
    while off + (n + 1) * stride + 12 <= len(buf):
        x, y, z = struct.unpack_from(fmt, buf, off + n * stride)
        if not (is_finite_float(x) and is_finite_float(y) and is_finite_float(z)):
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


def pick_vertex_buffer(stream):
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


def find_descriptors(header, order="<"):
    """Deterministic per-submesh geometry descriptors:
    [flag][vertexCount][G][flag][idxBytes][1], flag in {0,8}, G 5=rigid/44 6=skin/56.
    Integers are in block byte order (LE PC / BE X360+PS3).  The consoles use
    SMALLER vertex strides for the same G: rigid G=5 -> 32B (PC 44), skinned
    G=6 -> 44B (PC 56): the console layout packs normal/tangents as 11:11:10
    u32s instead of half3s (verified vs PC ground truth)."""
    out = []
    last = -100
    n = len(header)
    for p in range(0, n - 24):
        fa = material_refs.u32_at(header, p, order)
        nv = material_refs.u32_at(header, p + 4, order)
        G = material_refs.u32_at(header, p + 8, order)
        fb = material_refs.u32_at(header, p + 12, order)
        ib = material_refs.u32_at(header, p + 16, order)
        one = material_refs.u32_at(header, p + 20, order)
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


def ib_ok(stream, vbo, nv, stride, ib, order="<", maxdeg=0.4):
    """True if the index buffer at vbo forms mostly NON-degenerate triangles
    (< maxdeg repeated-index). A false-positive VB offset (positions look sane so
    it passes vb_ok) typically lands ~4 bytes before the real one and yields a
    ~50% repeated-index IB, while every real submesh is ~0%. Used to make the VB
    search prefer the real offset (the X360 TwilightLadyHair and the
    rorschachspots decals need it)."""
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


def vb_ok(stream, vbo, nv, stride, ib, order="<"):
    """STRICT carve validation: every index in range AND positions finite/bounded/
    non-degenerate (all 3 axis spans > eps). Rejects false offsets that squish a
    submesh flat (a check without the span test accepts those)."""
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
        if not (is_finite_float(x) and is_finite_float(y) and is_finite_float(z)):
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


def vb_ok_flat(stream, vbo, nv, stride, ib, order="<"):
    """FALLBACK for planar decals (signs/graffiti: legit meshes with one flat
    axis; 56 models in the batch sweep).  Same checks as vb_ok but only
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
        if not (is_finite_float(x) and is_finite_float(y) and is_finite_float(z)):
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
    for strip in itertools.batched(uvs, n):
        mv = sum(uv[1] for uv in strip) / n
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
    for strip in itertools.batched(uvs, n):
        blk = [(float(u), float(v)) for u, v in strip]
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
        for a, b in zip(again, uvs, strict=True)
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


def _strided(stream, off, n, stride, k, dt):
    """(n, k) numpy view of `k` items of dtype `dt` at stream offsets off + i *
    stride (one row per vertex).  struct.error when a row runs past the end of
    the stream (what struct.unpack_from raised there)."""
    dt = np.dtype(dt)
    if n <= 0:
        return np.zeros((0, k), dt)
    if off < 0 or off + (n - 1) * stride + k * dt.itemsize > len(stream):
        raise struct.error("vertex data past the end of the stream")
    return np.ndarray((n, k), dtype=dt, buffer=stream, offset=off, strides=(stride, dt.itemsize))


def _unit_rows(H):
    """Rows of a float64 (n, 3) array divided by their length; a row of length
    <= 1e-9 is (0, 0, 0).  The length is computed as Python's `x ** 0.5` of the
    sum of squares, so the result is bit for bit the per-vertex loop's."""
    sq = H[:, 0] * H[:, 0] + H[:, 1] * H[:, 1] + H[:, 2] * H[:, 2]
    m = np.array([x**0.5 for x in sq.tolist()], np.float64)
    ok = m > 1e-9
    out = H / np.where(ok, m, 1.0)[:, None]
    out[~ok] = 0.0
    return out


def _rows3(A):
    """(n, 3) array -> [(x, y, z)] of Python floats."""
    return list(zip(*A.T.tolist(), strict=True)) if len(A) else []


def decode_mesh_vertices(stream, vbo, nv, stride, be=False, restored=None, notes=None):
    """Vertex fields.  PC (44/56): pos f32x3 @0, normal half3 @12, uv half2 @24.
    Console (32/44): pos f32x3 @0 (BE), normal 11:11:10 u32 @12, color @16,
    uv BE half2 @20 (then packed tangents; skinned: idx u8x4 @32, weight half4 @36).
    The eyelash strips of the generic female heads come back with restored UVs
    (LASH_RESTORE) unless WATCHMEN_NO_SYNTH is set; a list passed as `restored`
    then receives "eyelash_uvs".

    -> (positions, normals, uvs): lists of tuples of Python floats; normals and
    uvs are None when the stride has no room for them or the stream ends first.
    A half float that is infinite or NaN (exponent 31) in the normals or the UVs
    drops that attribute of the submesh (None) and a list passed as `notes`
    receives one line saying so -- as rig_glb.unit_normals refuses a normal set
    with a non-finite value; no shipped model has one (measured).  Read with
    numpy strided views, one row per vertex; the values are the per-vertex
    struct loop's, bit for bit."""
    # a signalling NaN among the floats is quieted as struct.unpack_from quiets it;
    # numpy would also raise a RuntimeWarning for it
    with np.errstate(invalid="ignore"):
        return _decode_sub_np(stream, vbo, nv, stride, be, restored, notes)


def _decode_sub_np(stream, vbo, nv, stride, be, restored, notes):
    """decode_mesh_vertices's numpy body."""
    pdt = ">f4" if be else "<f4"
    verts = _rows3(_strided(stream, vbo, nv, stride, 3, pdt).astype(np.float64))
    norms = None
    if stride >= 20:
        try:
            if be:
                u = _strided(stream, vbo + 12, nv, stride, 1, ">u4")[:, 0].astype(np.int64)
                x, y, z = u & 0x7FF, (u >> 11) & 0x7FF, (u >> 22) & 0x3FF
                H = np.stack(
                    [
                        np.where(x >= 0x400, x - 0x800, x) / 1023.0,
                        np.where(y >= 0x400, y - 0x800, y) / 1023.0,
                        np.where(z >= 0x200, z - 0x400, z) / 511.0,
                    ],
                    1,
                )
            else:
                H = _strided(stream, vbo + 12, nv, stride, 3, "<f2").astype(np.float64)
            bad = int((~np.isfinite(H)).any(1).sum())
            if bad:
                if notes is not None:
                    notes.append(
                        "%d of %d normals hold an infinite or NaN half float: normals not written"
                        % (bad, nv)
                    )
            else:
                norms = _rows3(_unit_rows(H))
        except struct.error:
            norms = None
    uvs = None
    if stride >= 28 or (be and stride >= 24):
        try:
            uo = 20 if be else 24
            U = _strided(stream, vbo + uo, nv, stride, 2, ">f2" if be else "<f2").astype(np.float64)
            bad = int((~np.isfinite(U)).any(1).sum())
            if bad:
                if notes is not None:
                    notes.append(
                        "%d of %d UVs hold an infinite or NaN half float: UVs not written"
                        % (bad, nv)
                    )
            else:
                uvs = list(zip(U[:, 0].tolist(), U[:, 1].tolist(), strict=True))
        except struct.error:
            uvs = None
    if nv == LASH_RESTORE["vertex_count"] and uvs and synth_enabled():
        fixed = lash_restored_uvs(uvs)
        if fixed is not None:
            uvs = fixed
            if restored is not None:
                restored.append("eyelash_uvs")
    return verts, norms, uvs


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
                for e in naz_archive.naz_entries(naz):
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
                if kapow_block.header_order(mh) != ">":
                    if kapow_block.header_order(mh) == "<":
                        return None  # a PC tree
                    continue
                with open(os.path.join(dp, f + ".stream"), "rb") as fh:
                    ms = fh.read()
                M = model_header.parse_model_header(mh, ">")
                if M is None or model_header.model_stream_layout(M, ms, ">") is None:
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
    a0 = a3 = True
    n = 0
    for b in buffers:
        lay = model_header.CONSOLE_VERTEX_FORMATS.get(b["format"], {})
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
    lay = model_header.CONSOLE_VERTEX_FORMATS.get(b["format"], {})
    if "color" not in lay:
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
    lay = model_header.vertex_formats(order).get(buf["format"])
    if lay is None:
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
    degrees off."""
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
      lod, format, stride, vertex_count, index_bytes, primitive_type (0 strip,
      1 list), material (texture stem or None), texture (path or None),
      positions, normals, uvs  (python lists, same values as the OBJ writer gets),
      triangles [(a, b, c)] local indices, vb, ib,
      + decode_vertex_attributes() keys,
      + "restored": ["eyelash_uvs"] on a submesh whose UVs are restored content
        (LASH_RESTORE; not with WATCHMEN_NO_SYNTH)
      + "not_finite": [line] on a submesh whose normals or UVs hold an infinite
        or NaN half float (that attribute is None: decode_mesh_vertices)} ]}.
    A console model with vertex colours that cannot be read
    (console_color_undecoded) has no "color" on those submeshes, the has_color /
    has_alpha flags of ALL its buffers are cleared (the stored ones stay under
    has_color_file / has_alpha_file) and the result carries "not_decoded":
    ["COLOR_0"]."""
    if order is None:
        order = kapow_block.header_order(header) or "<"
    if order == ">" and not model_header.console_header_decode():
        return None
    M = model_header.parse_model_header(header, order)
    if M is None or stream is None or model_header.model_stream_layout(M, stream, order) is None:
        return None
    formats = model_header.vertex_formats(order)
    lay = M.get("layout")
    corder = console_color_order(stream, M["buffers"], None, lay) if order == ">" else None
    not_decoded = []
    if order == ">" and console_color_undecoded(stream, M["buffers"], None, lay):
        not_decoded.append("COLOR_0")
        for b in M["buffers"]:
            b["has_color_file"], b["has_alpha_file"] = b.get("has_color"), b.get("has_alpha")
            b["has_color"] = b["has_alpha"] = 0
    subs = []
    xfs = [None] * len(M["parts"]) if part_space else model_header.model_part_transforms(M)
    for b in model_header.select_model_buffers(M, lod, kinds):
        nv, st = b["vertex_count"], b["stride"]
        _restored, _notes = [], []
        verts, norms, uvs = decode_mesh_vertices(
            stream, b["vb"], nv, st, order == ">", _restored, _notes
        )
        # a skinned buffer is placed by its bone palette: left as stored
        xf = None if "joints" in formats.get(b["format"], {}) else xfs[b["part"]]
        verts = model_header.apply_part_transform(xf, verts)
        norms = model_header.apply_part_transform(xf, norms, point=False)
        if "uv" not in formats.get(b["format"], {}):
            uvs = None
        idx = struct.unpack_from(order + "%dH" % (b["index_bytes"] // 2), stream, b["ib"])
        ti = b["tex_index"][0] if b["tex_index"] else None
        tex = M["textures"][ti] if ti is not None and ti < len(M["textures"]) else None
        d = {
            "name": b["name"],
            "kind": b["kind"],
            "role": model_header.BUFFER_ROLES.get(b["kind"], b["kind"]),
            "part": b["part"],
            "lod": b["lod"],
            "format": b["format"],
            "stride": st,
            "vertex_count": nv,
            "index_bytes": b["index_bytes"],
            "primitive_type": b.get("primitive_type", 1),
            "vb": b["vb"],
            "ib": b["ib"],
            "texture": tex,
            "material": material_refs.texture_ref(tex) if tex else None,
            "positions": verts,
            "normals": norms,
            "uvs": uvs,
            "triangles": model_header.index_triangles(idx, b.get("primitive_type", 1)),
            "primitive": model_header.PRIMITIVE_NAMES.get(b.get("primitive_type", 1)),
        }
        d.update(decode_vertex_attributes(stream, b, order, corder))
        d.pop("normal", None)  # "normals" already holds it, normalised
        d["part_moved"] = xf is not None
        if _restored:
            d["restored"] = _restored
        if _notes:
            d["not_finite"] = _notes
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


def half_to_float(u):
    """IEEE half float (u16 code) -> Python float, as numpy's float16 reads it:
    exponent 31 is +-infinity (mantissa 0) or NaN."""
    s = (u >> 15) & 1
    e = (u >> 10) & 0x1F
    f = u & 0x3FF
    if e == 31:
        val = float("nan") if f else float("inf")
    elif e == 0:
        val = (f / 1024) * 2**-14
    else:
        val = (1 + f / 1024) * 2 ** (e - 15)
    return -val if s else val
