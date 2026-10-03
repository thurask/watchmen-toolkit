"""rig_glb.py  -- rigged + textured + animated glTF (.glb) export for Watchmen Kapow
character models, designed to be called from watchmen_extract.py.

Given the per-submesh geometry the master script already carves (positions / normals /
UVs / triangles / per-submesh material names) plus the SKIN channel read from the same
stride-56 vertices, this builds a single .glb containing:
  - per-submesh primitives, each with its own PBR material + embedded diffuse texture
  - a flat skinned armature (IBM = identity, bind pose); joint names/order come from
    the MODEL's own embedded skeleton header (file-derived; no capture artifacts)
  - Y-up orientation so it stands in Blender on import
Engine-exact ANIMATED per-character glbs are produced by the `watchmen.py characters`
pipeline (file-only binds + baked clips), not here.

Skin channel (verified): BLENDINDICES = D3DCOLOR ubyte4 @ +44 read BGRA (bytes 2,1,0,3);
BLENDWEIGHT = float16 x4 @ +48. Animation decode (_decode_anim / decode_animation --
LEGACY, caller-less; engine-exact clips come from bake_v4): per-bone local
quaternions ONLY (XYZW in-file, /10000, reordered to WXYZ on read); position keys
are skipped and translations come from the skeleton's rest offsets, so root motion
is not reproduced on that path (2026-08-17: docstring corrected -- it used to
claim translations (/1000) were decoded).
"""

import json, struct, math, io
import numpy as np

# ---------------- skeleton template (LEGACY: retired capture-artifact loader;
# no callers since 2026-07-13 -- the rig now takes its joint table from the
# model's own header via watchmen_extract._model_palette) ----------------
_TPL = None


def load_skeleton(path):
    global _TPL
    if _TPL is None and path and path.exists():
        _TPL = json.loads(path.read_text())
    return _TPL


def _skel_arrays(tpl):
    n = tpl["bone_count"]
    names = [b["name"] for b in tpl["bones"]]
    par = [b["parent"] for b in tpl["bones"]]
    rest_t = np.array([b["rest_t"] for b in tpl["bones"]], float)
    rest_q = np.array([b["rest_q"] for b in tpl["bones"]], float)  # xyzw
    ibm = np.array([b["ibm"] for b in tpl["bones"]], np.float32)  # column-major 16
    return n, names, par, rest_t, rest_q, ibm


# ---------------- skin read ----------------
def decode_skin(stream, vbo, nv, stride, order="<"):
    """Return (idx uint8 Nx4, weight f32 Nx4) from skinned vertices, or (None,None).
    PC (stride 56): BLENDINDICES D3DCOLOR ubyte4 @+44 read BGRA, BLENDWEIGHT
    float16x4 @+48 (LE).  Console (stride 44, X360/PS3 BE): joint idx u8x4 @+32,
    weights BE half4 @+36 (verified against PC skin on the bordello curtain)."""
    if order == ">":
        if stride < 44:
            return None, None
        rec = np.frombuffer(stream[vbo : vbo + nv * stride], np.uint8).reshape(nv, stride)
        # BLENDINDICES: D3DCOLOR u32 @+32 big-endian -> [R,G,B,A] joint quad =
        # bytes [33,34,35,32] (verified 1148/1148 skin sets == PC Rorschach).
        I = np.ascontiguousarray(rec[:, [33, 34, 35, 32]]).astype(np.uint8)
        # BLENDWEIGHT: BE float16 x4 @+36 -> swap each half's 2 bytes to LE.
        wraw = np.ascontiguousarray(rec[:, 36:44]).astype(np.uint8)
        wraw = wraw.reshape(nv, 4, 2)[:, :, ::-1].reshape(nv, 8)
        W = np.frombuffer(wraw.tobytes(), np.float16).reshape(nv, 4).astype(np.float32)
        s = W.sum(1, keepdims=True)
        s[s < 1e-6] = 1.0
        return I, (W / s).astype(np.float32)
    if stride < 56:
        return None, None
    rec = np.frombuffer(stream[vbo : vbo + nv * stride], np.uint8).reshape(nv, stride)
    I = np.ascontiguousarray(rec[:, [46, 45, 44, 47]]).astype(np.uint8)  # D3DCOLOR BGRA
    W = (
        np.frombuffer(np.ascontiguousarray(rec[:, 48:56]).tobytes(), np.float16)
        .reshape(nv, 4)
        .astype(np.float32)
    )
    s = W.sum(1, keepdims=True)
    s[s < 1e-6] = 1.0
    return I, (W / s).astype(np.float32)


# ---------------- coordinate convention (engine <-> glb) ----------------
# 2026-07-24 AXIS: the Kapow engine is already Y-up, so glTF needs no axis
# conversion.  This module used to rotate POSITION (and conjugate the FK world
# matrices) by a Z-up->Y-up matrix.  Unlike variant_glb -- where an exact
# inverse was folded into the skin matrices and cancelled -- nothing here
# cancelled it, so every model this writes came out rotated 90 degrees about X
# (static props/heads flat on their back; rigged bodies likewise).  Measured on
# shipped character output: skinned frame-0 bbox 1.75 m tall along Y, while raw
# POSITION measured 1.80 m along Z.  See variant_glb.py for the full evidence.


def _qmat(q):  # wxyz -> 3x3
    w, x, y, z = q
    nrm = (x * x + y * y + z * z + w * w) ** 0.5
    if nrm < 1e-9:
        return np.eye(3)
    x, y, z, w = x / nrm, y / nrm, z / nrm, w / nrm
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def _decomp(M):
    t = M[:3, 3].astype(float).copy()
    L = M[:3, :3].astype(float).copy()
    s = np.array([np.linalg.norm(L[:, k]) for k in range(3)])
    s[s < 1e-12] = 1e-12
    R = L / s
    if np.linalg.det(R) < 0:
        s[0] *= -1
        R = L / s
    tr = R[0, 0] + R[1, 1] + R[2, 2]
    if tr > 0:
        S = math.sqrt(tr + 1) * 2
        q = [(R[2, 1] - R[1, 2]) / S, (R[0, 2] - R[2, 0]) / S, (R[1, 0] - R[0, 1]) / S, 0.25 * S]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        S = math.sqrt(1 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [0.25 * S, (R[0, 1] + R[1, 0]) / S, (R[0, 2] + R[2, 0]) / S, (R[2, 1] - R[1, 2]) / S]
    elif R[1, 1] > R[2, 2]:
        S = math.sqrt(1 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 1] + R[1, 0]) / S, 0.25 * S, (R[1, 2] + R[2, 1]) / S, (R[0, 2] - R[2, 0]) / S]
    else:
        S = math.sqrt(1 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[0, 2] + R[2, 0]) / S, (R[1, 2] + R[2, 1]) / S, 0.25 * S, (R[1, 0] - R[0, 1]) / S]
    q = np.array(q)
    q /= np.linalg.norm(q) or 1
    return t, q, s  # q xyzw


# ---------------- .animation decode + FK ----------------
def _decode_anim(h):
    gi = h.find(b"GamePivot")
    o = gi - 4
    nm = []
    while o < len(h) - 4:
        L = struct.unpack_from("<I", h, o)[0]
        if L < 1 or L > 40 or o + 4 + L > len(h):
            break
        s = h[o + 4 : o + 4 + L]
        if not all(32 <= c < 127 or c == 0 for c in s):
            break
        nm.append(s.rstrip(b"\x00").decode())
        o += 4 + L
    nf = struct.unpack_from("<I", h, 12)[0]
    p = o
    tr = {}
    for bi in range(len(nm)):
        t = h[p]
        p += 1
        if t == 0:
            kc = struct.unpack_from("<H", h, p)[0]
            p += 2
            bq = struct.unpack_from("<4f", h, p)
            p += 16
            p += kc * 6
            tr[nm[bi]] = np.array([[bq[3], bq[0], bq[1], bq[2]]])  # const rot wxyz
        elif t == 1:
            kc = struct.unpack_from("<H", h, p)[0]
            p += 2
            p += 12
            k = np.frombuffer(h[p : p + kc * 8], np.int16).reshape(kc, 4).astype(float) / 10000.0
            p += kc * 8
            tr[nm[bi]] = k[:, [3, 0, 1, 2]]  # xyzw -> wxyz
        elif t == 2:
            kc = struct.unpack_from("<H", h, p)[0]
            p += 2
            raw = np.frombuffer(h[p : p + kc * 14], np.int16).reshape(kc, 7).astype(float)
            p += kc * 14
            tr[nm[bi]] = (raw[:, 3:7] / 10000.0)[:, [3, 0, 1, 2]]
        elif t == 3:
            p += 12
            p += 4
            q = struct.unpack_from("<4f", h, p)
            p += 16
            tr[nm[bi]] = np.array([[q[3], q[0], q[1], q[2]]])
    return nm, nf, tr


def _resample(k, NF):
    out = np.zeros((NF, 4))
    idx = np.linspace(0, len(k) - 1, NF)
    for i, t in enumerate(idx):
        a = int(t)
        b = min(a + 1, len(k) - 1)
        f = t - a
        qa, qb = k[a], k[b]
        if np.dot(qa, qb) < 0:
            qb = -qb
        q = qa * (1 - f) + qb * f
        out[i] = q / (np.linalg.norm(q) or 1)
    return out


def decode_animation(anim_header_bytes, tpl, fps=24.0, max_frames=120):
    """FK a .animation on the skeleton template -> per-bone local TRS tracks in glb space.
    Returns (name_unused, times, per_bone_T (F,B,3), per_bone_Q (F,B,4 xyzw)) or None."""
    n, names, par, rest_t, rest_q, ibm = _skel_arrays(tpl)
    # engine-space rest world (FK with offsets); offsets come from template rest_t in glb -> engine
    glb_restW = np.zeros((n, 4, 4))
    order = sorted(range(n), key=lambda i: _depth(par, i))
    for i in order:
        L = np.eye(4)
        L[:3, :3] = _qmat([rest_q[i][3], rest_q[i][0], rest_q[i][1], rest_q[i][2]])
        L[:3, 3] = rest_t[i]
        Wp = glb_restW[par[i]] if par[i] >= 0 else np.eye(4)
        glb_restW[i] = Wp @ L
    engRestW = glb_restW  # engine == glb frame (both Y-up); no conversion
    offset = np.zeros((n, 3))
    engRestLocR = np.zeros((n, 3, 3))
    for i in range(n):
        Wp = engRestW[par[i]] if par[i] >= 0 else np.eye(4)
        Lloc = np.linalg.inv(Wp) @ engRestW[i]
        offset[i] = Lloc[:3, 3]
        # engine-convention rest local rotation (consistent frame with clip tracks)
        U, _, Vt = np.linalg.svd(Lloc[:3, :3])
        Rr = U @ Vt
        if np.linalg.det(Rr) < 0:
            U[:, -1] *= -1
            Rr = U @ Vt
        engRestLocR[i] = Rr
    anames, nf, tr = _decode_anim(anim_header_bytes)
    NF = min(max(nf, 2), max_frames)
    rot = {}
    for i in range(n):
        rot[i] = _resample(tr[names[i]], NF) if names[i] in tr else None
    # FK in engine space -> glb node world -> local TRS
    locT = np.zeros((NF, n, 3), np.float32)
    locQ = np.zeros((NF, n, 4), np.float32)
    for f in range(NF):
        eW = [None] * n
        for i in order:
            R = _qmat(rot[i][f]) if rot[i] is not None else engRestLocR[i]
            L = np.eye(4)
            L[:3, :3] = R
            L[:3, 3] = offset[i]
            Wp = eW[par[i]] if par[i] >= 0 else np.eye(4)
            eW[i] = Wp @ L
        gW = eW  # engine == glb frame (both Y-up); no conversion
        for b in range(n):
            Wp = gW[par[b]] if par[b] >= 0 else np.eye(4)
            t, q, s = _decomp(np.linalg.inv(Wp) @ gW[b])
            locT[f, b] = t
            locQ[f, b] = q
    times = np.arange(NF, dtype=np.float32) / fps
    return times, locT, locQ


def _depth(par, i):
    d = 0
    p = par[i]
    while p >= 0:
        d += 1
        p = par[p]
    return d


def load_bundled_clip(npz_path):
    """LEGACY (retired 2026-07-13, no callers): loader for the pre-baked capture
    npz clips (bundled_clip_*.npz). Returns a dict with
    name, times, locT (F,B,3), locQ (F,B,4 xyzw), locS (F,B,3 or None), flat(bool).
    Flat clips bake per-bone WORLD transforms (Y-up baked) for a flat IBM=identity rig."""
    d = np.load(npz_path, allow_pickle=True)
    return {
        "name": str(d["name"]),
        "times": d["times"],
        "locT": d["locT"],
        "locQ": d["locQ"],
        "locS": d["locS"] if "locS" in d else None,
        "flat": bool(d["flat"]) if "flat" in d else False,
    }


# ---------------- optional vertex attributes ----------------
def unit_normals(N, tol=1e-6):
    """(n,3) float32 unit normals, or None when any is non-finite or has no
    length (glTF NORMAL must be unit length; nothing is invented for a bad one)."""
    if N is None:
        return None
    n = np.asarray(N, np.float64).reshape(-1, 3)
    ln = np.linalg.norm(n, axis=1)
    if n.size == 0 or not np.isfinite(n).all() or (ln < tol).any():
        return None
    return np.ascontiguousarray(n / ln[:, None], np.float32)


def well_formed_tangents(T4, tol=1e-3):
    """(n,4) float32 glTF TANGENT (xyz unit, w = +-1), or None when any entry is
    non-finite, not unit length or has another handedness value."""
    if T4 is None:
        return None
    t = np.asarray(T4, np.float32).reshape(-1, 4)
    if t.size == 0 or not np.isfinite(t).all():
        return None
    if (np.abs(np.linalg.norm(t[:, :3].astype(np.float64), axis=1) - 1.0) > tol).any():
        return None
    if not np.isin(t[:, 3], (-1.0, 1.0)).all():
        return None
    return np.ascontiguousarray(t)


def orthogonal_tangents(N, T4, tol=1e-6):
    """Gram-Schmidt of TANGENT xyz against unit normals (w unchanged: the sign of
    cross(n, t) . b does not depend on t's component along n).  None when a
    tangent is parallel to its normal.  The game's tangents are raw dP/du, not
    orthogonalised: |n.t| > 0.1 on 29 % of the skinned corpus's vertices."""
    n = np.asarray(N, np.float64)
    t = np.asarray(T4, np.float64)
    x = t[:, :3] - n * (n * t[:, :3]).sum(1, keepdims=True)
    ln = np.linalg.norm(x, axis=1)
    if (ln < tol).any():
        return None
    return np.concatenate([x / ln[:, None], t[:, 3:4]], 1).astype(np.float32)


def winding_reversed(P, N, tri):
    """Do the triangles wind against their vertex normals?  True when, for most
    triangles, cross(p1 - p0, p2 - p0) points away from the summed vertex normals.
    The engine's triangles do (Direct3D: clockwise is the front face), and glTF's
    front face is the counter-clockwise one, so a primitive that carries NORMAL
    has to be written with its winding flipped or double-sided materials light it
    from the inside (the back face's normal is reversed before lighting)."""
    t = np.asarray(tri, np.int64).reshape(-1, 3)
    if not len(t):
        return False
    p = np.asarray(P, np.float64)
    n = np.asarray(N, np.float64)
    fn = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
    s = (fn * (n[t[:, 0]] + n[t[:, 1]] + n[t[:, 2]])).sum(1)
    return int((s < 0).sum()) > int((s > 0).sum())


def mesh_vertex_attributes(header, stream, subs, lod=0):
    """NORMAL / COLOR_0 / TANGENT source data for build_rigged_glb, in the vertex
    order of decode_model's `subs` [(base, nverts, tstart, ntris, stride)].

    -> {"normals": (N,3) f32, "colors": (N,4) u8 RGBA | None, "tangents": (N,4)
    f32 | None, "has_color": [bool per submesh]} or None when the model is not
    decoded header-driven (console / Part 1 / scan fallback) or its render
    buffers do not line up with `subs`.

    Colour is the vertex's D3DCOLOR (stored B,G,R,A); a submesh whose mesh buffer
    has the has_color flag clear holds the writer's default (opaque white), so
    `colors` is None unless at least one submesh is flagged.  TANGENT xyz is the
    stored tangent (dP/du) normalised, w the sign of the stored bitangent against
    cross(normal, tangent) (watchmen_extract.gltf_tangents); a vertex whose stored
    tangent has no length makes `tangents` None for the whole model."""
    try:
        import watchmen_extract as we
    except ImportError:
        import os, sys

        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.append(here)  # append, never insert(0)
        import watchmen_extract as we

    mesh = we.decode_model_mesh(header, stream, lod)
    if mesh is None:
        return None
    bufs = [b for b in we.select_model_buffers(mesh["model"], lod) if b["format"] in (5, 6)]
    sm = [m for m in mesh["submeshes"] if m["format"] in (5, 6)]
    if len(sm) != len(subs) or len(bufs) != len(sm):
        return None
    if any(len(m["positions"]) != s[1] for m, s in zip(sm, subs)):
        return None
    if not sm or any("tangent" not in m or m["normals"] is None for m in sm):
        return None
    normals = np.concatenate([np.asarray(m["normals"], np.float32).reshape(-1, 3) for m in sm])
    has_color = [bool(b.get("has_color")) for b in bufs]
    colors = np.concatenate([m["color"] for m in sm]) if any(has_color) else None
    raw_t = np.concatenate([m["tangent"] for m in sm])
    raw_b = np.concatenate([m["bitangent"] for m in sm])
    tangents = None
    if np.isfinite(raw_t).all() and (np.linalg.norm(raw_t, axis=1) > 1e-6).all():
        un = unit_normals(normals)
        if un is not None:
            tangents = we.gltf_tangents(un, raw_t, raw_b)
    return {"normals": normals, "colors": colors, "tangents": tangents, "has_color": has_color}


# ---------------- glb assembly ----------------
def build_rigged_glb(
    out_path,
    V,
    N,
    U,
    SKIN_I,
    SKIN_W,
    T,
    subs,
    materials,
    tex_index,
    tpl,
    clips,
    log,
    tex_size=512,
    static=False,
    normals=None,
    colors=None,
    tangents=None,
    write_normals=True,
    write_colors=True,
    write_tangents=True,
    fix_winding=True,
    orthogonalize_tangents=False,
):
    """Carved submeshes -> one rigged + textured + animated .glb (FLAT exact rig:
    48 bones, inverseBind = identity, per-bone WORLD transform from the bundled clip
    with Y-up baked in -- the validated exact path). subs = list of
    (base, nverts, tstart, ntris, stride); materials[i] = texture basename; clips =
    list of dicts from load_bundled_clip. Needs Pillow for textures.

    `N` is accepted and ignored, as in 1.2.0 (callers that passed normals there
    got none written, and still get the same file).

    Optional per-vertex attributes, each written per primitive only when its data
    is present and well-formed (mesh_vertex_attributes supplies all three):
      normals   -> NORMAL   VEC3 float, normalised (skipped if any normal is bad)
      tangents  -> TANGENT  VEC4 float, xyz unit + w = +-1; needs NORMAL (glTF
                   ignores tangents without normals).  Written as stored;
                   orthogonalize_tangents=True makes them perpendicular to the
                   normal first (orthogonal_tangents)
      colors    -> COLOR_0  VEC4 unsigned byte, normalized
    A primitive that gets NORMAL is written with its triangle winding flipped when
    the triangles wind against the normals (winding_reversed; fix_winding=False
    keeps the file order).  Primitives without NORMAL keep their indices.
    write_normals / write_colors / write_tangents = False switch one off; with
    all three off (or no data passed) the file is byte-identical to what this
    function wrote before these attributes existed."""
    from PIL import Image

    n = tpl["bone_count"]
    V = np.asarray(V, np.float64)
    Vg = np.ascontiguousarray(V, np.float32)  # engine frame == glb frame
    j = {
        "asset": {"version": "2.0", "generator": "watchmen_extract"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "skins": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
        "animations": [],
        "images": [],
        "textures": [],
        "materials": [],
        "samplers": [{"wrapS": 10497, "wrapT": 10497}],
    }
    BIN = bytearray()

    def av(x, tgt=None):
        while len(BIN) % 4:
            BIN.append(0)
        o = len(BIN)
        BIN.extend(x)
        bv = {"buffer": 0, "byteOffset": o, "byteLength": len(x)}
        if tgt:
            bv["target"] = tgt
        j["bufferViews"].append(bv)
        return len(j["bufferViews"]) - 1

    def ac(bv, ct, c, t, mn=None, mx=None, normalized=False):
        A = {"bufferView": bv, "componentType": ct, "count": c, "type": t}
        if normalized:
            A["normalized"] = True
        if mn is not None:
            A["min"] = mn
            A["max"] = mx
        j["accessors"].append(A)
        return len(j["accessors"]) - 1

    matmap = {}

    def get_mat(texname):
        key = str(texname).lower()
        if key in matmap:
            return matmap[key]
        mi = None
        td = tex_index.get(key) if tex_index else None
        dif = None
        if td:
            try:
                g = sorted(td.glob("*_diffuse_*.png"))
                dif = g[0] if g else None
            except Exception:
                dif = None
        if dif and dif.exists():
            try:
                img = Image.open(dif).convert("RGB")
                img.thumbnail((tex_size, tex_size))
                buf = io.BytesIO()
                img.save(buf, "PNG")
                data = buf.getvalue()
                bv = av(data)
                j["images"].append(
                    {"bufferView": bv, "mimeType": "image/png", "name": str(texname)}
                )
                j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
                j["materials"].append(
                    {
                        "name": str(texname),
                        "pbrMetallicRoughness": {
                            "baseColorTexture": {"index": len(j["textures"]) - 1},
                            "metallicFactor": 0.0,
                            "roughnessFactor": 0.85,
                        },
                        "doubleSided": True,
                    }
                )
                mi = len(j["materials"]) - 1
            except Exception as ex:
                log and log("        (tex %s failed: %s)" % (texname, ex))
        if mi is None:
            j["materials"].append(
                {
                    "name": str(texname),
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [0.72, 0.72, 0.74, 1],
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.85,
                    },
                    "doubleSided": True,
                }
            )
            mi = len(j["materials"]) - 1
        matmap[key] = mi
        return mi

    # flat skeleton: 48 bones (rest = identity), children of Armature, IBM = identity.
    # static=True (head/accessory models with their own non-body palette): emit mesh +
    # materials only, no skin/armature/anim, so it lands at its authored position.
    bn = []
    if not static:
        for b in range(n):
            bn.append(len(j["nodes"]))
            j["nodes"].append({"name": tpl["bones"][b]["name"]})
    Tn = np.asarray(T, np.uint32)
    have_skin = (SKIN_I is not None) and (not static)
    prims = []
    for si, (base, nverts, tstart, ntris, stride) in enumerate(subs):
        vidx = slice(base, base + nverts)
        Pp = Vg[vidx]
        attrs = {
            "POSITION": ac(
                av(Pp.tobytes(), 34962),
                5126,
                nverts,
                "VEC3",
                Pp.min(0).tolist(),
                Pp.max(0).tolist(),
            )
        }
        Np = None
        if write_normals and normals is not None:
            Np = unit_normals(normals[base : base + nverts])
        if Np is not None and len(Np) == nverts:
            attrs["NORMAL"] = ac(av(Np.tobytes(), 34962), 5126, nverts, "VEC3")
            Tp = None
            if write_tangents and tangents is not None:
                Tp = well_formed_tangents(tangents[base : base + nverts])
                if Tp is not None and orthogonalize_tangents:
                    Tp = well_formed_tangents(orthogonal_tangents(Np, Tp))
            if Tp is not None and len(Tp) == nverts:
                attrs["TANGENT"] = ac(av(Tp.tobytes(), 34962), 5126, nverts, "VEC4")
        if U is not None:
            UVp = np.ascontiguousarray(np.asarray(U[base : base + nverts], np.float32))
            attrs["TEXCOORD_0"] = ac(av(UVp.tobytes(), 34962), 5126, nverts, "VEC2")
        if write_colors and colors is not None:
            Cp = np.ascontiguousarray(np.asarray(colors[base : base + nverts]))
            if Cp.dtype == np.uint8 and Cp.shape == (nverts, 4):
                attrs["COLOR_0"] = ac(
                    av(Cp.tobytes(), 34962), 5121, nverts, "VEC4", normalized=True
                )
        if have_skin:
            Ip = np.ascontiguousarray(SKIN_I[vidx])
            Wp = np.ascontiguousarray(SKIN_W[vidx]).astype(np.float32)
            attrs["JOINTS_0"] = ac(av(Ip.tobytes(), 34962), 5121, nverts, "VEC4")
            attrs["WEIGHTS_0"] = ac(av(Wp.tobytes(), 34962), 5126, nverts, "VEC4")
        tri = Tn[tstart : tstart + ntris] - base
        if fix_winding and "NORMAL" in attrs and winding_reversed(Pp, Np, tri):
            tri = np.asarray(tri).reshape(-1, 3)[:, [0, 2, 1]]
        ia = ac(av(np.ascontiguousarray(tri).tobytes(), 34963), 5125, tri.size, "SCALAR")
        prims.append(
            {
                "attributes": attrs,
                "indices": ia,
                "material": get_mat(materials[si] if si < len(materials) else "submesh_%d" % si),
                "mode": 4,
            }
        )
    j["meshes"].append({"name": out_path.stem, "primitives": prims})
    if static:
        mnode = len(j["nodes"])
        j["nodes"].append({"name": out_path.stem + "_mesh", "mesh": 0})
        j["scenes"][0]["nodes"] = [mnode]
    else:
        ident = np.tile(np.eye(4, dtype=np.float32).reshape(16), (n, 1))
        ibmacc = ac(av(ident.tobytes()), 5126, n, "MAT4")
        mnode = len(j["nodes"])
        mn = {"name": out_path.stem + "_mesh", "mesh": 0}
        if have_skin:
            mn["skin"] = 0
        j["nodes"].append(mn)
        arm = len(j["nodes"])
        j["nodes"].append({"name": "Armature", "children": bn + [mnode]})
        if have_skin:
            j["skins"].append({"joints": bn, "inverseBindMatrices": ibmacc, "skeleton": arm})
        j["scenes"][0]["nodes"] = [arm]
        for clip in clips or []:
            times = np.asarray(clip["times"], np.float32)
            F = len(times)
            ta = ac(
                av(times.tobytes()),
                5126,
                F,
                "SCALAR",
                [float(times.min())],
                [float(times.max())],
            )
            sm = []
            chn = []
            for b in range(n):
                chans = [
                    (np.asarray(clip["locT"][:, b], np.float32), "translation"),
                    (np.asarray(clip["locQ"][:, b], np.float32), "rotation"),
                ]
                if clip.get("locS") is not None:
                    chans.append((np.asarray(clip["locS"][:, b], np.float32), "scale"))
                j["nodes"][bn[b]]["translation"] = [float(x) for x in clip["locT"][0, b]]
                j["nodes"][bn[b]]["rotation"] = [float(x) for x in clip["locQ"][0, b]]
                if clip.get("locS") is not None:
                    j["nodes"][bn[b]]["scale"] = [float(x) for x in clip["locS"][0, b]]
                for arr, path in chans:
                    vo = ac(
                        av(np.ascontiguousarray(arr).tobytes()),
                        5126,
                        F,
                        "VEC3" if path != "rotation" else "VEC4",
                    )
                    sm.append({"input": ta, "output": vo, "interpolation": "LINEAR"})
                    chn.append({"sampler": len(sm) - 1, "target": {"node": bn[b], "path": path}})
            j["animations"].append({"name": clip["name"], "samplers": sm, "channels": chn})
    for _k in ("animations", "skins", "images", "textures", "materials", "samplers"):
        if not j.get(_k):
            j.pop(_k, None)
    j["buffers"].append({"byteLength": len(BIN)})
    jb = json.dumps(j, separators=(",", ":")).encode()
    while len(jb) % 4:
        jb += b" "
    bb = bytes(BIN)
    while len(bb) % 4:
        bb += b"\x00"
    out_path.write_bytes(
        b"glTF"
        + struct.pack("<II", 2, 12 + 8 + len(jb) + 8 + len(bb))
        + struct.pack("<I", len(jb))
        + b"JSON"
        + jb
        + struct.pack("<I", len(bb))
        + b"BIN\x00"
        + bb
    )
    return True
