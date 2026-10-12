"""rig_glb.py  -- rigged + textured + animated glTF (.glb) export for Watchmen Kapow
character models, designed to be called from watchmen_extract.py.

Given the per-submesh geometry the master script already carves (positions / normals /
UVs / triangles / per-submesh material names) plus the SKIN channel read from the same
stride-56 vertices, this builds a single .glb containing:
  - per-submesh primitives, each with its own PBR material + embedded textures (full
    size; `tex_size` / extract --glb-texture-size shrinks them)
  - bind-pose geometry, skin weights and the skeleton: one joint node per node of
    the MODEL's own embedded skeleton header (names, parents, rest transforms built
    as build_bind_file builds a bind), real inverse bind matrices -- no animation.
    rig "flat" (--rig flat, or a header whose node table does not cover the joints)
    writes the flat armature instead: joints without a transform, all children of
    `Armature`, identity inverse binds.  The mesh renders the same in both.
  - Y-up orientation so it stands in Blender on import
Engine-exact ANIMATED per-character glbs are produced by the `watchmen.py characters`
pipeline (file-only binds + baked clips), not here.

Skin channel (verified): BLENDINDICES = D3DCOLOR ubyte4 @ +44 read BGRA (bytes 2,1,0,3);
BLENDWEIGHT = float16 x4 @ +48.  Clips are not decoded here: engine-exact clips come
from bake_v4; this module has no clip decoder.
"""

import io
import numpy as np

from wutil import GlbPacker, glb_bytes


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
        W = np.frombuffer(wraw.tobytes(), "<f2").reshape(nv, 4).astype(np.float32)
        s = W.sum(1, keepdims=True)
        s[s < 1e-6] = 1.0
        return I, (W / s).astype(np.float32)
    if stride < 56:
        return None, None
    rec = np.frombuffer(stream[vbo : vbo + nv * stride], np.uint8).reshape(nv, stride)
    I = np.ascontiguousarray(rec[:, [46, 45, 44, 47]]).astype(np.uint8)  # D3DCOLOR BGRA
    W = (
        np.frombuffer(np.ascontiguousarray(rec[:, 48:56]).tobytes(), "<f2")
        .reshape(nv, 4)
        .astype(np.float32)
    )
    s = W.sum(1, keepdims=True)
    s[s < 1e-6] = 1.0
    return I, (W / s).astype(np.float32)


# ---------------- coordinate convention (engine <-> glb) ----------------
# AXIS: the Kapow engine is already Y-up, so glTF needs no axis conversion.
# This module applies no Z-up->Y-up rotation to POSITION or to the FK world
# matrices; such a rotation would turn every model 90 degrees about X (static
# props/heads flat on their back; rigged bodies likewise).  Measured on shipped
# character output: skinned frame-0 bbox 1.75 m tall along Y.  See variant_glb.py
# for the full evidence.


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


def srgb_to_linear(c):
    """sRGB-encoded 0..1 -> linear (IEC 61966-2-1)."""
    c = np.asarray(c, np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_vertex_colors(rgba_u8):
    """(n,4) uint8 RGBA vertex colours -> (n,4) float32 glTF COLOR_0.

    The engine multiplies the lit, display-encoded colour by rgb and the texture
    alpha by a (DeferredMain2PS: `mul r1.xyz, r0, v0` / `mul oC0.w, r2.w, v0.w`;
    no sRGB read or write state in the D3D9 capture).  glTF multiplies the LINEAR
    base colour, so rgb is converted sRGB -> linear to give the same displayed
    factor; alpha is linear in both."""
    c = np.asarray(rgba_u8, np.float64) / 255.0
    out = np.empty(c.shape, np.float32)
    out[:, :3] = srgb_to_linear(c[:, :3])
    out[:, 3] = c[:, 3]
    return out


def gltf_normal_png(png_bytes):
    """Extracted normal-map PNG (R = X along +u, G = Y along +v, the engine's
    stored bitangent) -> glTF normal texture bytes (G inverted: glTF's +Y is the
    -v direction).  None if Pillow cannot read it."""
    try:
        from PIL import Image, ImageChops

        im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
        r, g, b = im.split()
        buf = io.BytesIO()
        Image.merge("RGB", (r, ImageChops.invert(g), b)).save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None


def material_alpha(sheet, tex_has_alpha, vertex_alpha, legacy=False):
    """glTF alpha mode of a material -> (alphaMode or None, alphaCutoff or None).

    The engine picks the render list from the sheet alone (0x5739d0): BLEND iff
    the sheet is "Standard with blending" (renderType 1) or its opacity is below
    0.99; otherwise MASK when the diffuse layer has alpha, at the sheet's
    alpha-test reference (alphaThreshold / 255; the capture shows D3DRS_ALPHAREF
    95) or 0.5 when the sheet is unknown; otherwise opaque.  Vertex alpha
    multiplies the texture alpha but does not choose the list, so on its own it
    never gives BLEND (materials.alpha is the same rule, with the opacity factor)
    -- except for SkyBox / Sprite sheets and where no sheet is known, which use
    the `legacy` rule below.

    legacy=True is the rule of the `legacy` materials mode: BLEND when
    the vertex alpha varies, or for renderType 1 with a diffuse that has alpha."""
    sheet = sheet or {}
    if legacy:
        if vertex_alpha or (sheet.get("renderType") == 1 and tex_has_alpha):
            return "BLEND", None
    else:
        op = sheet.get("opacity")
        fade = op is not None and float(op) < 0.99
        if vertex_alpha and sheet.get("renderType") in (None, 7, 9):
            # SkyBox / Sprite: passes of their own, which blend; None: sheet not known
            return "BLEND", None
        if sheet.get("renderType") == 1 or fade:
            return ("BLEND", None) if (tex_has_alpha or vertex_alpha or fade) else (None, None)
    if tex_has_alpha:
        thr = sheet.get("alphaThreshold")
        if thr is None:
            return "MASK", 0.5
        if thr > 0:
            return "MASK", round(min(int(thr), 255) / 255.0, 6)
    return None, None


def mesh_vertex_attributes(header, stream, subs, lod=0):
    """NORMAL / COLOR_0 / TANGENT source data for build_rigged_glb, in the vertex
    order of decode_model's `subs` [(base, nverts, tstart, ntris, stride)].

    -> {"normals": (N,3) f32, "colors": (N,4) u8 RGBA | None, "tangents": (N,4)
    f32 | None, "has_color": [bool per submesh]} or None when the model is not
    decoded header-driven (the scan fallback: a header of neither layout, or a
    stream its buffers do not tile) or its render buffers do not line up with
    `subs`.

    Colour is the vertex's D3DCOLOR (stored B,G,R,A); a submesh whose mesh buffer
    has the has_color flag clear holds the writer's default (opaque white), so
    `colors` is None unless at least one submesh is flagged.  TANGENT xyz is the
    stored tangent (dP/du) normalised, w = -sign(dot(cross(normal, tangent),
    stored bitangent)): the handedness for the green-inverted glTF normal texture
    (watchmen_extract.gltf_tangents); a vertex whose stored tangent has no length
    makes `tangents` None for the whole model."""
    try:
        import watchmen_extract as we
    except ImportError:
        import os
        import sys

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
    has_alpha = [bool(b.get("has_alpha")) for b in bufs]
    colors = np.concatenate([m["color"] for m in sm]) if any(has_color) else None
    raw_t = np.concatenate([m["tangent"] for m in sm])
    raw_b = np.concatenate([m["bitangent"] for m in sm])
    tangents = None
    if np.isfinite(raw_t).all() and (np.linalg.norm(raw_t, axis=1) > 1e-6).all():
        un = unit_normals(normals)
        if un is not None:
            tangents = we.gltf_tangents(un, raw_t, raw_b)
    return {
        "normals": normals,
        "colors": colors,
        "tangents": tangents,
        "has_color": has_color,
        "has_alpha": has_alpha,
    }


# ---------------- glb assembly ----------------
def header_rig(tpl, nodes, rig=None):
    """The skeleton build_rigged_glb writes for the joint table `tpl` -> (record,
    W, parents): W (n, 4, 4) the joints' rest world transforms and parents their
    parent joint indices for the hierarchy; (None, None, None) for the flat rig
    asked for; ({"mode": "flat", "reason": ...}, None, None) when the hierarchy
    cannot be built from `nodes` (parse_model_nodes.parse's names, pos, quat xyzw,
    parent; joint k = node k).

    W follows build_bind_file exactly: node 0 (the unnamed root) at the origin,
    rotations by fk_conj (conjugated locals, parent then child), positions
    t_k = t_p + R_p pos_k -- the conventions the binds of `watchmen binds` use, so
    a model whose header carries a bind's skeleton gets that bind's Rb / tb."""
    import variant_glb as _vg
    import build_bind_file as _bbf

    if _vg.rig_mode(rig) == "flat":
        return None, None, None
    n = int(tpl["bone_count"])

    def flat(reason):
        return {"mode": "flat", "reason": reason}, None, None

    if nodes is None:
        return flat("no node table for the model's skeleton")
    names, pos, quat, parent = nodes
    if len(names) < n:
        return flat(
            "the header's node table has %d nodes, the skin uses %d joints" % (len(names), n)
        )
    if [str(b["name"]) for b in tpl["bones"][:n]] != [str(x) for x in names[:n]]:
        return flat("the joint names are not the header's node names")
    par = [int(p) for p in parent[:n]]
    par[0] = -1
    if not _vg.parent_table_ok(par):
        return flat("the header's parent table is not a tree over the joints")
    pos = np.array(pos[:n], np.float64).reshape(n, 3)
    quat = np.array(quat[:n], np.float64).reshape(n, 4)
    pos[0] = 0.0
    quat[0] = [0.0, 0.0, 0.0, 1.0]
    if (
        not (np.isfinite(pos).all() and np.isfinite(quat).all())
        or (np.linalg.norm(quat, axis=1) < 1e-6).any()
    ):
        return flat("the header's rest transforms are not valid")
    Wq = _bbf.fk_conj(names[:n], pos, quat, par)
    W = np.tile(np.eye(4), (n, 1, 1))
    for k in range(n):
        W[k, :3, :3] = _bbf.q2m(Wq[k])
    done = [False] * n

    def place(k):
        if done[k]:
            return
        p = par[k]
        if p >= 0:
            place(p)
            W[k, :3, 3] = W[p, :3, 3] + W[p, :3, :3] @ pos[k]
        else:
            W[k, :3, 3] = pos[k]
        done[k] = True

    for k in range(n):
        place(k)
    return {"mode": "hierarchy", "source": "the model header's node table"}, W, par


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
    tex_size=None,
    static=False,
    normals=None,
    colors=None,
    tangents=None,
    write_normals=True,
    write_colors=True,
    write_tangents=True,
    fix_winding=True,
    orthogonalize_tangents=False,
    has_color=None,
    has_alpha=None,
    engine_materials=False,
    nodes=None,
    rig=None,
):
    """Carved submeshes -> one rigged + textured .glb in bind pose. subs = list of
    (base, nverts, tstart, ntris, stride); materials[i] = texture basename; tpl =
    {'bone_count', 'bones': [{'name'}]} in joint (palette) order; clips = list of
    dicts with times / locT / locQ (LEGACY, the extractor passes None). Needs Pillow
    for textures.

    tex_size: None (default) embeds every texture at the size of its PNG; N
    shrinks each to fit N x N (aspect kept; 512 = the size of the 1.4.0 files).

    nodes: the model header's node table, (names, pos, quat xyzw, parent) as
    parse_model_nodes.parse gives it, joint k = node k.  rig: "hierarchy" / "flat"
    (None = variant_glb.rig_mode(), $WATCHMEN_RIG).  In the hierarchy the joints
    get the header's rest pose -- world W_k built as build_bind_file builds a bind
    (rotation: fk_conj, position: t_k = t_p + R_p pos_k; node 0 at the origin) --
    as TRS local to the parent joint, and IBM_k = inverse(W_k), so the skinned
    rest pose is the mesh as stored.  Without `nodes`, when the table has fewer
    nodes than the joints the skin uses, or when its parents are not a tree, the
    file gets the flat rig and asset.extras.watchmen.rig says why; "flat" asked
    for writes the flat armature with no record.

    `N` is accepted and ignored (callers that pass normals there get none
    written).

    Optional per-vertex attributes, each written per primitive only when its data
    is present and well-formed (mesh_vertex_attributes supplies all three):
      normals   -> NORMAL   VEC3 float, normalised (skipped if any normal is bad)
      tangents  -> TANGENT  VEC4 float, xyz unit + w = +-1; needs NORMAL (glTF
                   ignores tangents without normals) and, with engine_materials,
                   a material that has a normal map.  Written as stored;
                   orthogonalize_tangents=True makes them perpendicular to the
                   normal first (orthogonal_tangents)
      colors    -> COLOR_0  VEC4 float, rgb sRGB -> linear, alpha as stored
                   (linear_vertex_colors); only for the submeshes flagged in
                   `has_color` (all of them when it is None)
    `has_alpha` (per submesh: the buffer's vertex alpha varies) is recorded in
    that submesh's material (extras.watchmen.vertex_alpha) and makes it alphaMode
    BLEND only where the sheet blends (renderType 1 / opacity < 0.99), or in the
    `legacy` materials mode.  engine_materials=True also takes the
    material switches from the texture's sheet.json (doubleSided = twoSided,
    alpha test / blend, see material_alpha) and adds the normal map when the
    primitive carries NORMAL; without it every material is the `legacy` one
    (diffuse only, opaque, doubleSided).
    A primitive that gets NORMAL is written with its triangle winding flipped when
    the triangles wind against the normals (winding_reversed; fix_winding=False
    keeps the file order).  Primitives without NORMAL keep their indices.
    Frame (frame.mode(), --frame): the above describes the engine numbers, which
    is the file in the "mirrored" frame; in the "true" frame (default) the
    finished document is reflected (x -> -x, winding reversed, TANGENT w
    negated), so there the file order is the front face and a primitive without
    NORMAL is written in file order as well.
    write_normals / write_colors / write_tangents = False switch one off; with
    all three off (or no data passed) the file is byte-identical to what this
    function wrote before these attributes existed."""
    from PIL import Image
    import frame as _frame

    # the arrays below are engine numbers; _frame.finish_gltf reflects the finished
    # document when the output frame is "true" (default)
    true_frame = _frame.is_true()
    n = tpl["bone_count"]
    rig_rec, rig_W, rig_par = None, None, None
    if not static and n:
        rig_rec, rig_W, rig_par = header_rig(tpl, nodes, rig)
    V = np.asarray(V, np.float64)
    Vg = np.ascontiguousarray(V, np.float32)
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
    _pk = GlbPacker(j["bufferViews"], j["accessors"])
    BIN = _pk.bin
    av = _pk.view  # (data, target=None) -> bufferView index
    ac = _pk.accessor  # (bv, ct, count, type, mn=None, mx=None, normalized=False)

    matmap = {}

    def _sheet(td):
        # the first sheet in full, as the MTL writer reads it
        if not (engine_materials and td):
            return {}
        import watchmen_extract as _we

        return _we.first_sheet(td)

    import materials as _mt

    engine_pbr = bool(engine_materials) and _mt.mode() == "engine"

    _base_mode = {}  # material key -> (alphaMode, alphaCutoff) the texture has without vertex alpha

    def _mark_va(mat, sheet):
        if sheet and sheet.get("renderType") is not None:  # a sheet the rule was read from
            mat.setdefault("extras", {}).setdefault("watchmen", {})["vertex_alpha"] = True

    def get_mat(texname, blend=False, with_normal=False):
        # the model's own texture path tells same-named textures apart
        tpath = getattr(texname, "path", None)
        key = (str(texname).lower(), tpath.replace("\\", "/").lower() if tpath else None)
        if engine_materials:
            key = (key, bool(blend), bool(with_normal))
        if key in matmap:
            return matmap[key]
        mi = None
        if hasattr(tex_index, "resolve"):  # watchmen_extract.TextureIndex: by path, then name
            td = tex_index.resolve(texname, log if callable(log) else None)
        else:
            td = tex_index.get(str(texname).lower()) if tex_index else None
        dif = None
        sheet = _sheet(td)
        # the sheet may take single layers from another texture, and may not be
        # a plain alpha blend (watchmen_extract.sheet_blend)
        over, sblend = {}, None
        if engine_materials and sheet:
            import watchmen_extract as _we

            over = _we.sheet_layer_dirs(tex_index, sheet, log if callable(log) else None)
            sblend = _we.sheet_blend(sheet)
        # a type 0 / 10 sheet that is drawn blended only for its opacity is written
        # by materials.alpha (BLEND + opacity factor) with its engine material; only
        # an additive / subtractive one needs the rewritten layer (engine mode)
        if sblend and sblend.get("cause") == "opacity":
            if not (engine_pbr and sblend.get("gltf") in ("ink", "glow")):
                sblend = None
        if td:
            try:
                g = sorted(over.get("diffuse", td).glob("*_diffuse_*.png"))
                dif = g[0] if g else None
            except Exception:
                dif = None
        two_sided = bool(sheet["twoSided"]) if "twoSided" in sheet else True
        if dif and dif.exists():
            try:
                src = Image.open(dif)
                tex_alpha = False
                if sblend and sblend.get("gltf") in ("ink", "glow"):
                    src = _we.blend_layer_image(src, sblend)
                if engine_materials and src.mode in ("RGBA", "LA", "PA"):
                    rgba = src.convert("RGBA")
                    tex_alpha = rgba.getextrema()[3][0] < 255
                pix_alpha = tex_alpha
                if engine_pbr and sheet and not (sblend and sblend.get("gltf") in ("ink", "glow")):
                    # the engine's alpha test follows the texture header's alpha
                    # flag (0x429e77 -> 0x571d5d), not the pixels
                    tex_alpha, _hdr = _mt.texture_has_alpha(
                        _we.read_sheet_json(over.get("diffuse", td)), pix_alpha
                    )

                def _amode(va):
                    if not engine_materials:
                        return None, None, None
                    if engine_pbr and sheet:
                        return _mt.alpha(sheet, tex_alpha, va, pix_alpha)
                    return material_alpha(
                        sheet if sheet else None, tex_alpha, va, legacy=not engine_pbr
                    ) + (None,)

                mode, cutoff, afac = _amode(blend)
                if engine_pbr and blend:
                    # vertex alpha that does not change the alpha mode: one material
                    # for the texture, marked extras.watchmen.vertex_alpha
                    # blend_material makes these BLEND whatever the vertex alpha
                    forced = bool(sblend and sblend["type"] != "standard" and sblend.get("gltf"))
                    _base_mode[key] = ("BLEND", None) if forced else _amode(False)[:2]
                    if forced or _base_mode[key] == (mode, cutoff):
                        shared = (key[0], False, key[2])
                        if shared in matmap:
                            _mark_va(j["materials"][matmap[shared]], sheet)
                            matmap[key] = matmap[shared]
                            return matmap[shared]
                # the alpha channel is kept where it is used (always in legacy mode)
                keep_a = pix_alpha and (bool(mode) or bool(sblend) or not engine_pbr)
                img = rgba if keep_a else src.convert("RGB")
                if tex_size:
                    img.thumbnail((tex_size, tex_size))
                buf = io.BytesIO()
                img.save(buf, "PNG")
                data = buf.getvalue()
                bv = av(data)
                j["images"].append(
                    {"bufferView": bv, "mimeType": "image/png", "name": str(texname)}
                )
                j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
                mat = {
                    "name": str(texname),
                    "pbrMetallicRoughness": {
                        "baseColorTexture": {"index": len(j["textures"]) - 1},
                        "metallicFactor": 0.0,
                        "roughnessFactor": 0.85,
                    },
                    "doubleSided": two_sided,
                }
                if engine_materials:
                    if blend and engine_pbr:
                        _mark_va(mat, sheet)
                    if mode:
                        mat["alphaMode"] = mode
                    if cutoff is not None:
                        mat["alphaCutoff"] = cutoff
                    if afac is not None:
                        mat["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, afac]
                    if sblend:
                        _we.blend_material(
                            mat, sblend, len(j["textures"]) - 1, sheet.get("opacity")
                        )
                    nrm = None
                    if with_normal and sheet.get("enableNormalMapping", True):
                        g = sorted(over.get("normal", td).glob("*_normal_*.png"))
                        if g:
                            nimg = Image.open(g[0]).convert("RGB")
                            if tex_size:
                                nimg.thumbnail((tex_size, tex_size))
                            nb = io.BytesIO()
                            nimg.save(nb, "PNG")
                            nrm = gltf_normal_png(nb.getvalue())
                    if nrm is not None:
                        j["images"].append(
                            {
                                "bufferView": av(nrm),
                                "mimeType": "image/png",
                                "name": str(texname) + "_normal",
                            }
                        )
                        j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
                        mat["normalTexture"] = {"index": len(j["textures"]) - 1}
                        power = sheet.get("normalMapPower")
                        if power is not None and abs(float(power) - 1.0) > 1e-6:
                            mat["normalTexture"]["scale"] = round(float(power), 6)
                    if engine_pbr and sheet and not sblend:
                        # roughness / specular / emission from the sheet (materials.py)
                        def _layer(label):
                            g = sorted(over.get(label, td).glob("*_%s_*.png" % label))
                            if not g:
                                return None
                            im = Image.open(g[0])
                            im.load()  # read now: the file is closed, not left to the collector
                            if tex_size:
                                im.thumbnail((tex_size, tex_size))
                            return im

                        def _add(data, label):
                            j["images"].append(
                                {
                                    "bufferView": av(data),
                                    "mimeType": "image/png",
                                    "name": "%s_%s" % (texname, label),
                                }
                            )
                            j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
                            return len(j["textures"]) - 1

                        _mt.apply(
                            j,
                            mat,
                            _mt.engine_material(
                                sheet, img, _layer("specMap"), _layer("specSize"), _layer("glow")
                            ),
                            _add,
                        )
                j["materials"].append(mat)
                mi = len(j["materials"]) - 1
            except Exception as ex:
                log and log("        (tex %s failed: %s)" % (texname, ex))
        if mi is None:
            mat = {
                "name": str(texname),
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.72, 0.72, 0.74, 1],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.85,
                },
                "doubleSided": two_sided,
            }
            if engine_materials and blend:
                if engine_pbr:  # vertex alpha alone does not blend (material_alpha)
                    shared = (key[0], False, key[2])
                    amode = material_alpha(sheet if sheet else None, False, True)[0]
                    _base_mode[key] = (
                        material_alpha(sheet if sheet else None, False, False)[0],
                        None,
                    )
                    if not amode and shared in matmap:
                        _mark_va(j["materials"][matmap[shared]], sheet)
                        matmap[key] = matmap[shared]
                        return matmap[shared]
                    _mark_va(mat, sheet)
                    if amode:
                        mat["alphaMode"] = "BLEND"
                else:
                    mat["alphaMode"] = "BLEND"
            j["materials"].append(mat)
            mi = len(j["materials"]) - 1
        matmap[key] = mi
        if engine_pbr and blend:
            # the same material serves the texture's submeshes without vertex alpha
            # when their alpha mode would be the same
            m = j["materials"][mi]
            base_mode = _base_mode.get(key)
            if base_mode is not None and base_mode == (m.get("alphaMode"), m.get("alphaCutoff")):
                matmap.setdefault((key[0], False, key[2]), mi)
        return mi

    # flat skeleton (rig "flat"): bones with rest = identity, children of Armature,
    # IBM = identity.  Hierarchy: the header's skeleton (header_rig).
    # static=True (head/accessory models with their own non-body palette): emit mesh +
    # materials only, no skin/armature/anim, so it lands at its authored position.
    bn = []
    if not static:
        hier = rig_W is not None
        names = [tpl["bones"][b]["name"] for b in range(n)]
        if hier:
            import variant_glb as _vg

            names = _vg.joint_node_names(names, ("Armature", out_path.stem + "_mesh"))
            L = _vg.local_from_world(rig_W, rig_par)
        for b in range(n):
            bn.append(len(j["nodes"]))
            nd = {"name": names[b]}
            if hier:
                q = _vg.batch_m2q(np.ascontiguousarray(L[b, :3, :3])[None])[0]
                nd["rotation"] = [float(x) for x in q]
                nd["translation"] = [float(x) for x in L[b, :3, 3]]
                nd["extras"] = {
                    "bone": str(tpl["bones"][b]["name"]),
                    "parent": int(rig_par[b]),
                    "index": b,
                }
            j["nodes"].append(nd)
        if hier:
            for b in range(n):
                if rig_par[b] >= 0:
                    j["nodes"][bn[rig_par[b]]].setdefault("children", []).append(bn[b])
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
        blend = bool(
            write_colors
            and colors is not None
            and has_alpha is not None
            and si < len(has_alpha)
            and has_alpha[si]
            and (has_color is None or (si < len(has_color) and bool(has_color[si])))
        )
        mat_name = materials[si] if si < len(materials) else "submesh_%d" % si
        mat_index = None
        if engine_materials:  # resolved first: TANGENT is only written for a normal map
            mat_index = get_mat(mat_name, blend, Np is not None and len(Np) == nverts)
        if Np is not None and len(Np) == nverts:
            attrs["NORMAL"] = ac(av(Np.tobytes(), 34962), 5126, nverts, "VEC3")
            Tp = None
            # TANGENT only serves a normal map: only engine materials get one (a
            # material resolved without engine_materials never has normalTexture)
            want_t = mat_index is not None and "normalTexture" in j["materials"][mat_index]
            if write_tangents and tangents is not None and want_t:
                Tp = well_formed_tangents(tangents[base : base + nverts])
                if Tp is not None and orthogonalize_tangents:
                    Tp = well_formed_tangents(orthogonal_tangents(Np, Tp))
            if Tp is not None and len(Tp) == nverts:
                attrs["TANGENT"] = ac(av(Tp.tobytes(), 34962), 5126, nverts, "VEC4")
        if U is not None:
            UVp = np.ascontiguousarray(np.asarray(U[base : base + nverts], np.float32))
            attrs["TEXCOORD_0"] = ac(av(UVp.tobytes(), 34962), 5126, nverts, "VEC2")
        sub_color = has_color is None or (si < len(has_color) and bool(has_color[si]))
        if write_colors and colors is not None and sub_color:
            Cp = np.ascontiguousarray(np.asarray(colors[base : base + nverts]))
            if Cp.dtype == np.uint8 and Cp.shape == (nverts, 4):
                Cf = np.ascontiguousarray(linear_vertex_colors(Cp))
                attrs["COLOR_0"] = ac(av(Cf.tobytes(), 34962), 5126, nverts, "VEC4")
        if have_skin:
            import variant_glb as _vg

            Wp = np.ascontiguousarray(SKIN_W[vidx]).astype(np.float32)
            # JOINTS_0 of a zero-weight influence is 0 (glTF 3.7.3.3; skinning unchanged)
            Ip = _vg.used_joints(SKIN_I[vidx], Wp)
            attrs["JOINTS_0"] = ac(av(Ip.tobytes(), 34962), 5121, nverts, "VEC4")
            attrs["WEIGHTS_0"] = ac(av(Wp.tobytes(), 34962), 5126, nverts, "VEC4")
        tri = Tn[tstart : tstart + ntris] - base
        if fix_winding and "NORMAL" in attrs and winding_reversed(Pp, Np, tri):
            tri = np.asarray(tri).reshape(-1, 3)[:, [0, 2, 1]]
        elif true_frame and ("NORMAL" not in attrs or not fix_winding):
            # nothing decided against the normals: the file order is the front face
            # in the true frame, so cancel the reversal finish_gltf applies
            tri = np.asarray(tri).reshape(-1, 3)[:, [0, 2, 1]]
        ia = ac(av(np.ascontiguousarray(tri).tobytes(), 34963), 5125, tri.size, "SCALAR")
        prims.append(
            {
                "attributes": attrs,
                "indices": ia,
                "material": get_mat(mat_name) if mat_index is None else mat_index,
                "mode": 4,
            }
        )
    j["meshes"].append({"name": out_path.stem, "primitives": prims})
    if static:
        mnode = len(j["nodes"])
        j["nodes"].append({"name": out_path.stem + "_mesh", "mesh": 0})
        j["scenes"][0]["nodes"] = [mnode]
    else:
        if rig_W is not None:
            ibm = np.array([np.linalg.inv(m).T.reshape(16) for m in rig_W], np.float32)
        else:
            ibm = np.tile(np.eye(4, dtype=np.float32).reshape(16), (n, 1))
        ibmacc = ac(av(ibm.tobytes()), 5126, n, "MAT4")
        mnode = len(j["nodes"])
        mn = {"name": out_path.stem + "_mesh", "mesh": 0}
        if have_skin:
            mn["skin"] = 0
        j["nodes"].append(mn)
        arm = len(j["nodes"])
        if rig_W is not None:
            # the skinned mesh at the scene root; the joints alone under Armature
            j["nodes"].append(
                {"name": "Armature", "children": [bn[b] for b in range(n) if rig_par[b] < 0]}
            )
            j["scenes"][0]["nodes"] = [arm, mnode]
        else:
            j["nodes"].append({"name": "Armature", "children": bn + [mnode]})
            j["scenes"][0]["nodes"] = [arm]
        if have_skin:
            j["skins"].append({"joints": bn, "inverseBindMatrices": ibmacc, "skeleton": arm})
        if rig_rec is not None:
            j["asset"].setdefault("extras", {}).setdefault("watchmen", {})["rig"] = rig_rec
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
    _frame.finish_gltf(j, BIN)
    j["buffers"].append({"byteLength": len(BIN)})
    out_path.write_bytes(glb_bytes(j, BIN))
    return True
