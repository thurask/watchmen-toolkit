#!/usr/bin/env python3
# ONE GLB PER CHARACTER VARIANT with ALL of its animations.
#   python3 variant_glb.py FRAGMENT.json VARIANT_NAME OUT.glb [--clips PREFIX] \
#       [--bind BIND.npz] [--bank CLIPBANK.pkl]
# Uses: engine-exact bind (bind_v14b/gimp...), bake_v4 math (conjugate convention,
# absolute root), real IBMs + joint-space TRS (interpolation-safe), real-time rates.
import os
import sys
import json
import struct
import zlib
import numpy as np
from wutil import load_npz, order_name, platform_name, restricted_load

_D = os.path.dirname(os.path.abspath(__file__))
if _D not in sys.path:
    sys.path.append(_D)  # append, never insert(0): flat module names must not shadow the stdlib
import kapow_block  # noqa: E402
import model_header  # noqa: E402
import model_mesh  # noqa: E402
import naz_archive  # noqa: E402
import texture_sheet  # noqa: E402
import rig_glb  # noqa: E402
import gltf_build  # noqa: E402

# AXIS: the Kapow engine is ALREADY Y-up, so no axis conversion is needed for
# glTF.  This module applies no Z-up->Y-up rotation C to POSITION and no inverse
# Ry to the joint world matrices: such a pair (Ry @ C4 == I) cancels in the
# *animated* result but leaves the raw POSITION accessor -- and therefore the
# bind pose -- rotated 90 degrees about X.  Without it the bind pose is upright.
#
# Evidence: on CHAR_Rorschach_v10_walk_cycle.glb the skinned frame-0 bbox is
# (0.519, 1.751, 0.662) -- 1.75 m tall along Y, feet down; a rotated POSITION
# measures (1.276, 0.426, 1.802), i.e. lying on its back.  A Z-up reading with
# an off-by-one node/name attribution reports a 1.4 m character.  Independent
# confirmation: GameEssentials.fragment gravity is (0, -14.82, 0) == World -Y
# (jiggle_d6.py).


# Clip timing: every clip is written at its header-exact rate (bake_v4.fps_for).  The engine
# plays a page at ctrl.speed x slot speedFactor x weight / duration (SetAllSlotBlends
# 0x5b5175, GetGameSpecificSpeedFactor 0x5ab837; docs/ENGINE_CONSTANTS.md "Rate"): no
# velocity term (read from code).  No walk / run multiplier is applied; each clip's
# slot speed factors are in its extras (`speeds`).


def batch_m2q(M):
    """(N,3,3) -> (N,4) xyzw, vectorized Shepperd."""
    N = len(M)
    q = np.empty((N, 4))
    t = M[:, 0, 0] + M[:, 1, 1] + M[:, 2, 2]
    c0 = t > 0
    s = np.sqrt(np.clip(t[c0] + 1, 1e-12, None)) * 2
    q[c0, 3] = 0.25 * s
    q[c0, 0] = (M[c0, 2, 1] - M[c0, 1, 2]) / s
    q[c0, 1] = (M[c0, 0, 2] - M[c0, 2, 0]) / s
    q[c0, 2] = (M[c0, 1, 0] - M[c0, 0, 1]) / s
    r = ~c0
    if r.any():
        Mr = M[r]
        qr = np.empty((r.sum(), 4))
        i = np.argmax(np.stack([Mr[:, 0, 0], Mr[:, 1, 1], Mr[:, 2, 2]], 1), axis=1)
        for ax in range(3):
            m = i == ax
            if not m.any():
                continue
            A = Mr[m]
            b, c_, d = (ax + 1) % 3, (ax + 2) % 3, ax
            s = np.sqrt(np.clip(1 + A[:, d, d] - A[:, b, b] - A[:, c_, c_], 1e-12, None)) * 2
            qq = np.empty((m.sum(), 4))
            qq[:, 3] = (A[:, c_, b] - A[:, b, c_]) / s
            qq[:, d] = 0.25 * s
            qq[:, b] = (A[:, b, d] + A[:, d, b]) / s
            qq[:, c_] = (A[:, d, c_] + A[:, c_, d]) / s
            qr[m] = qq
        q[r] = qr
    return q / np.linalg.norm(q, axis=1, keepdims=True)


#: The character GLB's skeleton (--rig, $WATCHMEN_RIG):
#:   "hierarchy" (default) -- joint node k is named after its bone and is a child of
#:       the joint of the bone's parent (roots: children of `root`); its rest TRS and
#:       every animation channel are LOCAL to that parent; the skinned mesh nodes are
#:       scene roots.  Requires the bind's names and parents (else "flat").
#:   "flat" -- the layout of the 1.4.0 files: nodes `b<k>`, all children of `root`, each carrying
#:       the joint's world transform, the mesh nodes under `root`.
#: The skinning (IBMs, JOINTS_0, WEIGHTS_0) and every world pose are the same in both.
RIG_MODES = ("hierarchy", "flat")
DEFAULT_RIG = "hierarchy"
#: node names a character GLB uses besides the joints; a joint never takes one
FIXED_NODE_NAMES = (
    "root",
    "mesh",
    "face_root",
    "f_anchor",
    "face_mesh",
    "alternatives",
    "ragdoll",
)
#: the forms of the other helper node names write_glb gives: the face joints
#: 'f_<face bone>', the face proxies 'face_proxy_b<k>_<i>', the ragdoll shapes
#: 'RB.<bone>.<i>' and frames 'RJ.<bone>'; a joint name of such a form is taken too
#: (whether or not the file has a face rig or a ragdoll, so the joint names depend
#: on the bind and the attachment / outfit names only)
RESERVED_NODE_PREFIXES = ("f_", "face_proxy_", "RB.", "RJ.")


def rig_mode(value=None):
    """The rig mode in force: `value`, else $WATCHMEN_RIG, else DEFAULT_RIG."""
    v = value or os.environ.get("WATCHMEN_RIG") or DEFAULT_RIG
    if v not in RIG_MODES:
        raise ValueError("rig mode %r (one of %s)" % (v, ", ".join(RIG_MODES)))
    return v


def joint_node_names(names, reserved=()):
    """Node names for the joints of a hierarchical rig: the bone names with control
    characters removed and surrounding blanks stripped; an empty name becomes
    'b<k>'; a name that is already taken -- by an earlier joint, by one of
    FIXED_NODE_NAMES, by a name in `reserved` (the attachment and outfit nodes), or
    that has the form of a face or ragdoll helper node (RESERVED_NODE_PREFIXES) --
    gets ' #<k>' appended (k = the joint's palette index).  So no joint shares a
    name with another node write_glb writes (the attachment, outfit, face and
    ragdoll nodes keep the names they are given), and the palette index stays
    readable."""
    taken = set(FIXED_NODE_NAMES) | {str(r) for r in reserved}
    out = []
    for k, n in enumerate(names):
        nm = "".join(c for c in str(n) if c.isprintable()).strip() or "b%d" % k
        if nm in taken or nm.startswith(RESERVED_NODE_PREFIXES):
            nm = "%s #%d" % (nm, k)
            i = 2
            while nm in taken:  # pathological: '<name> #k' itself is a bone name
                nm = "%s #%d.%d" % (nm.rsplit(" #", 1)[0], k, i)
                i += 1
        taken.add(nm)
        out.append(nm)
    return out


def parent_table_ok(par, n=None):
    """True when `par` is a forest over range(n): every entry -1 or another index,
    no joint its own ancestor."""
    par = [int(p) for p in par]
    n = len(par) if n is None else n
    if len(par) != n or any(p < -1 or p >= n or p == k for k, p in enumerate(par)):
        return False
    state = [0] * n  # 0 unseen, 1 on the current path, 2 done
    for k in range(n):
        path = []
        j = k
        while j >= 0 and state[j] == 0:
            state[j] = 1
            path.append(j)
            j = par[j]
        if j >= 0 and state[j] == 1:
            return False  # came back to a joint of this path: a cycle
        for x in path:
            state[x] = 2
    return True


def glb_joint_names(bind_names, bind_par, reserved=(), rig=None):
    """The joint node names write_glb gives a bind with names `bind_names` and
    parents `bind_par`: joint_node_names() in the "hierarchy" rig, None when the
    rig is (or falls back to) "flat" -- the 'b<k>' names."""
    if rig_mode(rig) != "hierarchy" or bind_names is None or bind_par is None:
        return None
    if len(bind_names) != len(bind_par) or not parent_table_ok(bind_par):
        return None
    return joint_node_names(bind_names, reserved)


def local_from_world(W, par):
    """Rigid world transforms W (..., NB, 4, 4) -> transforms local to the parent
    joint: R_p^T R_k and R_p^T (t_k - t_p) (the rigid inverse of the parent; the
    joint matrices are rotations, so no general inverse is needed).  Roots
    (par < 0) keep W.  Vectorised over the leading axes (frames)."""
    W = np.asarray(W, np.float64)
    L = W.copy()
    par = np.asarray(par, int)
    k = np.nonzero(par >= 0)[0]
    if k.size:
        p = par[k]
        # index the joint axis on its own (mixing an index array with the scalar
        # column index would move the joint axis to the front)
        R = W[..., :3, :3]
        t = W[..., :3, 3]
        RpT = np.swapaxes(np.take(R, p, axis=-3), -1, -2)
        Rl = L[..., :3, :3]
        tl = L[..., :3, 3]
        Rl[..., k, :, :] = RpT @ np.take(R, k, axis=-3)
        d = np.take(t, k, axis=-2) - np.take(t, p, axis=-2)
        tl[..., k, :] = np.einsum("...ij,...j->...i", RpT, d)
        L[..., :3, :3] = Rl
        L[..., :3, 3] = tl
    return L


def used_joints(SI, SW):
    """JOINTS_0 with the index of every zero-weight influence set to 0 (glTF 2.0,
    3.7.3.3: unused joint slots should be 0; the weight decides alone, so the
    skinning is unchanged)."""
    SI = np.array(SI, copy=True)
    SI[np.asarray(SW) == 0] = 0
    return np.ascontiguousarray(SI)


#: per-vertex attributes (NORMAL / TANGENT / COLOR_0, winding, vertex-alpha
#: blend) in the character GLBs; False (or WATCHMEN_VERTEX_ATTRS=0) writes the
#: attribute set of releases before 1.4.0 (--no-vertex-attrs).
VERTEX_ATTRS = True


def vertex_attrs_enabled():
    return bool(VERTEX_ATTRS) and os.environ.get("WATCHMEN_VERTEX_ATTRS", "1") != "0"


class Part(tuple):
    """A mesh part (V, SI, SW, T, UV, material) that also carries `.attrs`: the
    per-vertex data of its mesh buffer, in the same vertex order --
    {"normal", "tangent", "bitangent": (n,3) f32 as stored, "color": (n,4) u8
    RGBA, "has_color", "has_alpha": the MeshBuffer flags}.  Unpacks like the
    plain 6-tuple every consumer expects."""

    attrs = None


def with_attrs(part, attrs, rot=None):
    """`part` as a Part carrying `attrs` (or the plain tuple when attrs is None).
    rot: 3x3 rotation already applied to the part's positions -- the normal,
    tangent and bitangent are rotated with it."""
    if attrs is None:
        return part
    if rot is not None:
        Rm = np.asarray(rot, np.float64)
        attrs = dict(attrs)
        for k in ("normal", "tangent", "bitangent"):
            attrs[k] = (np.asarray(attrs[k], np.float64) @ Rm.T).astype(np.float32)
    p = Part(part)
    p.attrs = attrs
    return p


def keep_attrs(old, new, rot=None):
    """Carry `old`'s attributes over to the re-built tuple `new` (same vertices,
    same order).  rot: 3x3 rotation that was applied to the positions -- the
    normal, tangent and bitangent are rotated with it."""
    at = getattr(old, "attrs", None)
    if at is None or len(new[0]) != len(at["normal"]):
        return new
    return with_attrs(new, at, rot)


_LAYOUT_CACHE = {}


def buffer_vertex_attrs(mh, ms, order, vbo, nv, stride, platform=None):
    """Per-vertex attributes for the vertex buffer the descriptor scan located at
    stream offset `vbo` -- taken from the header-driven decode
    (model_header.parse_model_header + model_stream_layout), so nothing is
    guessed: the buffer must be a format 5/6 render buffer whose computed
    offset, vertex count and stride equal the scan's.  None otherwise (a buffer
    the header does not account for).

    platform: the console of a big-endian model ("x360" / "ps3"; None = what
    model_mesh.console_platform gives).  It decides the colour byte order
    (model_mesh.console_color_order).  A console model whose colour order stays unknown
    (model_mesh.console_color_undecoded) still gets its normal and tangent
    frame: the result then has "color_not_decoded": True, a white `color` and
    has_color / has_alpha False for every buffer of the model, like the static
    model path."""
    if order not in ("<", ">") or ms is None:
        return None
    if order == ">" and not model_header.console_header_decode():
        return None
    # the stream is part of the key: the Xbox 360 and PS3 copies of a model share
    # the header and the stream length and differ in the colour bytes
    key = (
        zlib.crc32(mh),
        len(mh),
        len(ms),
        zlib.crc32(ms),
        order,
        platform,
        model_mesh.console_platform(),
    )
    bufs = _LAYOUT_CACHE.get(key)
    if bufs is None:
        bufs = {}
        try:
            M = model_header.parse_model_header(mh, order)
            if M is not None and model_header.model_stream_layout(M, ms, order) is not None:
                cargs = (ms, M["buffers"], platform, M.get("layout"))
                corder = model_mesh.console_color_order(*cargs) if order == ">" else None
                lost = order == ">" and bool(model_mesh.console_color_undecoded(*cargs))
                for b in M["buffers"]:
                    if b["format"] in (5, 6) and b.get("kind") == "render":
                        bufs[b["vb"]] = (b, corder, lost)
        except Exception:
            bufs = {}
        if len(_LAYOUT_CACHE) > 16:
            _LAYOUT_CACHE.clear()
        _LAYOUT_CACHE[key] = bufs
    b, corder, lost = bufs.get(vbo) or (None, None, False)
    if b is None or b["vertex_count"] != nv or b["stride"] != stride:
        return None
    a = model_mesh.decode_vertex_attributes(ms, b, order, corder)
    if "tangent" not in a:
        return None
    if lost or "color" not in a:
        # colour order not known: no colour is written for ANY buffer of the model
        # (decode_model_mesh does the same), the tangent frame is kept
        lost = True
        a["color"] = np.full((nv, 4), 255, np.uint8)
    if order == ">":
        nrm = np.asarray(a["normal"], np.float32)
    else:
        st = b["stride"]
        raw = np.frombuffer(ms, np.uint8, nv * st, vbo).reshape(nv, st)
        nrm = np.ascontiguousarray(raw[:, 12:18]).view("<f2").astype(np.float32)
    return {
        "normal": nrm,
        "tangent": np.asarray(a["tangent"], np.float32),
        "bitangent": np.asarray(a["bitangent"], np.float32),
        "color": np.asarray(a["color"], np.uint8),
        "has_color": bool(b.get("has_color")) and not lost,
        "has_alpha": bool(b.get("has_alpha")) and not lost,
        "color_not_decoded": bool(lost),
    }


def load_parts(mesh_names, palette_names, naz=None):
    """Mesh parts of `mesh_names` read from the archive `naz` (None: `01_game.naz`,
    else `game.naz`, in the current directory -- bake_v4.default_naz).  The
    pieces and their skin come from mesh_loader, as in char_lib.load_parts."""
    if naz is None:
        import bake_v4

        naz = bake_v4.default_naz()
    import char_lib as _cl
    import mesh_loader as ml

    found = {}
    for st, hs in naz_archive.iter_blocks(naz):
        if "h" not in hs:
            continue
        try:
            it = list(kapow_block.extract_block(hs["h"], hs.get("s")))
        except Exception as ex:  # one unreadable block is logged, the walk goes on
            print("  ! block %s: %s" % (st.rsplit("/", 1)[-1], ex))
            continue
        for e, h, s in it:
            nm = e.name.rsplit("/", 1)[-1].replace(".model", "")
            if nm in mesh_names:
                # the block path names the console (derived_x360 / derived_ps3)
                found.setdefault(nm, []).append((h, s, model_mesh.console_platform_of(st)))
    parts = []
    for nm in mesh_names:
        if nm not in found:
            print("  ! mesh missing:", nm)
            continue
        cands = sorted(found[nm], key=lambda t: -(len(t[1]) if t[1] else 0))
        mh, ms, plat = cands[0]
        if ms is None:
            continue
        # per-part skin-index remap (each part mesh has its OWN bone list); the
        # header states the byte order (char_lib.model_order)
        order = _cl.model_order(mh, ms, nm)
        remap, lost = ml.palette_remap(mh, order, palette_names, nm)
        _cl.note_palette_names(nm, [d for d in lost if d["where"] == ml.MID_LIST])
        try:
            subs, _rep = ml.load_submeshes(
                mh, ms, nm, order=order, platform=plat, fallback_name="%s_sub%d"
            )
        except (ValueError, KeyError, IndexError, struct.error) as ex:
            ex.add_note(
                "model %s in %s (%d header bytes, %d stream bytes, %s, platform %s)"
                % (
                    nm,
                    naz,
                    len(mh),
                    len(ms),
                    order_name(order),
                    platform_name(plat, order),
                )
            )
            raise
        for sb in subs:
            sk = _cl.skinned_part(nm, sb, remap, order, lost)
            if sk is None:
                continue
            SI, SW = sk
            mat = sb["material"]
            parts.append(with_attrs((sb["V"], SI, SW, sb["T"], sb["UV"], mat), sb["attrs"]))
            print(
                "  loaded %-24s sub%d verts=%d tris=%d mat=%s"
                % (nm, sb["index"], len(sb["V"]), len(sb["T"]), mat)
            )
    return parts


def _sanitize_uv_tangents(part, eps=1.5 / 512.0):
    """Split faces with a collapsed (zero-area) UV triangle so viewer-generated
    tangents stay finite.  A normal-mapped material + a degenerate UV triangle
    (all 3 verts on ONE texel -- common on flat-shaded 'solid colour cap' faces,
    e.g. hair caps, and present in ~85 shipped submeshes) yields a NaN/zero
    tangent, and the fragment renders pure BLACK.  For each bad face we duplicate
    its 3 verts (position/skin unchanged) and spread their UVs into a ~1.5-texel
    triangle around the shared point -- visually identical sample, valid tangent
    basis.  Non-degenerate faces (and their shared verts) are untouched.  No-op
    when the part has no collapsed-UV faces."""
    v, si, sw, T, uv, mat = part
    v = np.asarray(v, float)
    uv = np.asarray(uv, float)
    si = np.asarray(si)
    sw = np.asarray(sw)
    T = np.asarray(T).copy()
    if len(T) == 0 or len(uv) < len(v):
        return part
    area = (
        np.abs(
            (uv[T[:, 1], 0] - uv[T[:, 0], 0]) * (uv[T[:, 2], 1] - uv[T[:, 0], 1])
            - (uv[T[:, 2], 0] - uv[T[:, 0], 0]) * (uv[T[:, 1], 1] - uv[T[:, 0], 1])
        )
        / 2
    )
    bad = np.where(area < 1e-6)[0]
    if not len(bad):
        return part
    V = [v]
    SI = [si]
    SW = [sw]
    UV = [uv]
    n = len(v)
    at = getattr(part, "attrs", None)
    dup = []  # source vertex of every appended one (attributes are copied)
    off = np.array([[0, -eps], [eps, eps], [-eps, eps]])  # fixed 2*eps^2 UV triangle
    for t in bad:
        idx = T[t]
        dup.extend(int(i) for i in idx)
        # rebuild around the face's UV centroid -> guaranteed non-degenerate
        # even for sliver faces (distinct-but-collinear UVs), not just fully
        # collapsed ones.
        V.append(v[idx])
        SI.append(si[idx])
        SW.append(sw[idx])
        UV.append(uv[idx].mean(0) + off)
        T[t] = [n, n + 1, n + 2]
        n += 3
    out = (
        np.concatenate(V),
        np.concatenate(SI).astype(np.uint16),
        np.concatenate(SW).astype(np.float32),
        T,
        np.concatenate(UV).astype(np.float32),
        mat,
    )
    if at is not None and len(at["normal"]) == len(v):
        at = dict(at)
        for k in ("normal", "tangent", "bitangent", "color"):
            at[k] = np.concatenate([at[k], at[k][dup]])
        out = with_attrs(out, at)
    return out


class VariantGlb:
    """One variant GLB as write_glb writes it: the inputs, the body bind and the
    rig layout read from them, the glTF document (gltf_build.GltfDoc) and the
    material caches.  write_glb's docstring describes the arguments and the file."""

    def __init__(
        self,
        parts,
        manifest,
        bindnpz,
        textures=None,
        face=None,
        attachments=None,
        meta=None,
        face_rule=None,
        face_idle=None,
        alt_parts=None,
        parts_record=None,
        outfit_parts=None,
        asset_extras=None,
        ragdoll=None,
        rig=None,
    ):
        import anim_meta as _am
        import face_rule as _fr
        import frame as _frame

        self.engine = _fr.rule(face_rule) == "engine"
        self.idle = _fr.idle_enabled(face_idle)
        # Guard against the degenerate-UV -> black-tangent artifact on any part whose
        # material has a normal map (see _sanitize_uv_tangents).  Gated on normal-
        # mapped materials so UV-less / untextured parts aren't needlessly split.
        _norm_mats = {
            nm for nm, l in (textures or {}).items() if isinstance(l, dict) and l.get("normal")
        }
        if _norm_mats:
            _san = lambda pl: [_sanitize_uv_tangents(p) if p[5] in _norm_mats else p for p in pl]
            parts = _san(parts)
            if attachments:
                attachments = [(an, _san(ap)) for an, ap in attachments]
            if alt_parts:
                alt_parts = [(an, _san(ap)) for an, ap in alt_parts]
            if outfit_parts:
                outfit_parts = [(an, _san(ap), sh) for an, ap, sh in outfit_parts]
            if face is not None and face.get("parts"):
                face = dict(face)
                face["parts"] = _san(face["parts"])
        self.parts = parts
        self.manifest = manifest
        self.textures = textures
        self.face = face
        self.attachments = attachments
        self.alt_parts = alt_parts
        self.parts_record = parts_record
        self.outfit_parts = outfit_parts
        self.asset_extras = asset_extras
        self.ragdoll = ragdoll
        # the clip extras copy GLB-frame numbers out of `meta`: it has to be in the
        # frame this file is written in (a table without the marker is mirrored)
        self.meta = _am.to_frame(meta)
        bt = load_npz(bindnpz)
        Rb = bt["Rb"]
        tb = bt["tb"]
        NB = self.NB = len(Rb)
        # real bone names + parents (palette order) -- written to `extras` so an
        # importer needs no per-skeleton table to rebuild the hierarchy.
        bnames = self.bnames = [str(x) for x in bt["names"]] if "names" in bt else None
        bpar = self.bpar = [int(x) for x in bt["par"]] if "par" in bt else None
        skel = (
            _am.skeleton_extras(bnames, bpar)
            if bnames and bpar and len(bnames) == NB and len(bpar) == NB
            else None
        )
        B4 = self.B4 = np.tile(np.eye(4), (NB, 1, 1))
        B4[:, :3, :3] = Rb
        B4[:, :3, 3] = tb
        self.IBM = np.array([np.linalg.inv(B4[k]) for k in range(NB)])
        # the skeleton layout (RIG_MODES): joint node names, parents, local TRS
        rigrec = {"mode": rig_mode(rig)}
        jnames = None
        if rigrec["mode"] == "hierarchy":
            _reserved = [a for a, _p in attachments or []] + [a for a, _p in alt_parts or []]
            _reserved += [a for a, _p, _s in outfit_parts or []]
            jnames = glb_joint_names(bnames, bpar, _reserved) if skel else None
            if jnames is None:
                rigrec = {
                    "mode": "flat",
                    "reason": (
                        "the bind has no bone names and parents"
                        if not skel
                        else "the bind's parent table is not a tree"
                    ),
                }
        self.jnames = jnames
        self.hier = jnames is not None
        if self.hier:
            skel = _am.skeleton_extras(bnames, bpar, rig="hierarchy", joint_nodes=jnames)
        self.skel = skel
        self.doc = gltf_build.GltfDoc(
            {
                "version": "2.0",
                "generator": "watchmen_extract variant_glb",
                "extras": {
                    "watchmen": {
                        "format": _am.FORMAT,
                        "conventions": _am.conventions(),
                        "rig": rigrec,
                    }
                },
            },
            (
                "nodes",
                "meshes",
                "skins",
                "accessors",
                "bufferViews",
                "buffers",
                "materials",
                "animations",
                "images",
                "textures",
            ),
            {"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497},
        )
        self.j = self.doc.j
        self.va = vertex_attrs_enabled()
        # everything below is built from engine numbers (binds, bakes, meshes);
        # _frame.finish_gltf reflects the finished document for the "true" frame
        self.true_frame = _frame.is_true()
        self.texdone = {}  # material name -> index of its textured material
        self.blendmat = {}  # material index -> its alphaMode BLEND twin
        self.sheetalpha = {}  # id(material) -> (sheet, header alpha, pixel alpha): engine materials
        self.vamat = {}  # material index -> the material a part with vertex alpha uses

    # ------------------------------------------------------------ materials
    def vertex_prep(self, part, Vg, T):
        """Per-vertex attributes of one part -> (index array to write, pending
        attribute arrays or None, vertex-alpha blend flag).  NORMAL is the stored
        normal; TANGENT the stored tangent with w for the green-inverted normal
        texture (we.gltf_tangents), written when the part's material has a normal
        map; COLOR_0 only when the buffer has colours.
        A part that gets NORMAL has its winding turned to glTF's (the engine's
        triangles wind clockwise against their normals)."""
        T = np.asarray(T)
        at = getattr(part, "attrs", None) if self.va else None
        Np = None
        if at is not None and len(at["normal"]) == len(Vg):
            Np = rig_glb.unit_normals(at["normal"])
        if Np is None:
            if self.true_frame and T.size:
                # no normals: the file order is the front face in the true frame,
                # so cancel the reversal frame.finish_gltf applies
                T = T.reshape(-1, 3)[:, [0, 2, 1]]
            return T, None, False
        pend = {"NORMAL": (Np, "VEC3")}
        tg = np.asarray(at["tangent"], np.float32)
        lay = (self.textures or {}).get(part[5])
        has_nmap = isinstance(lay, dict) and bool(lay.get("normal"))  # else TANGENT is unused
        if has_nmap and np.isfinite(tg).all() and (np.linalg.norm(tg, axis=1) > 1e-6).all():
            Tp = rig_glb.well_formed_tangents(
                model_mesh.gltf_tangents(
                    Np,
                    tg,
                    at["bitangent"],
                    green_up=os.environ.get("WATCHMEN_NORMALS", "gl") != "dx",
                )
            )
            if Tp is not None:
                pend["TANGENT"] = (Tp, "VEC4")
        if at.get("has_color"):
            pend["COLOR_0"] = (
                np.ascontiguousarray(rig_glb.linear_vertex_colors(at["color"])),
                "VEC4",
            )
        if T.size and rig_glb.winding_reversed(Vg, Np, T):
            T = T.reshape(-1, 3)[:, [0, 2, 1]]
        return T, pend, bool(at.get("has_color") and at.get("has_alpha"))

    def blend(self, mi, blend):
        """material index `mi`, or its alphaMode BLEND twin for a part whose
        vertex alpha varies (it multiplies the texture alpha in the engine).
        A material written from its sheet (materials.py, engine mode) gets no
        twin unless the sheet blends: the engine picks the render list from
        renderType and opacity alone (0x5739d0), and the opaque lists are drawn
        with blending off, so vertex alpha only reaches the alpha test there.
        It is recorded as extras.watchmen.vertex_alpha instead.  The legacy mode
        and a material without a known sheet keep the twin."""
        j = self.j
        if not blend or j["materials"][mi].get("alphaMode") == "BLEND":
            return mi
        m = j["materials"][mi]
        if id(m) in self.sheetalpha:
            import materials as _mt

            if mi not in self.vamat:
                sheet, has_a, pix_a = self.sheetalpha[id(m)]
                amode, cutoff, _afac = _mt.alpha(sheet, has_a, True, pix_a)
                if amode == m.get("alphaMode") and cutoff == m.get("alphaCutoff"):
                    m.setdefault("extras", {}).setdefault("watchmen", {})["vertex_alpha"] = True
                    self.vamat[mi] = mi
                else:  # the vertex alpha changes the mode (a flagged texture without
                    # alpha pixels is alpha-tested on it; a type 1 sheet blends it)
                    m2 = json.loads(json.dumps(m))
                    m2.pop("alphaMode", None)
                    m2.pop("alphaCutoff", None)
                    if amode:
                        m2["alphaMode"] = amode
                    if cutoff is not None:
                        m2["alphaCutoff"] = cutoff
                    if sheet.get("renderType") is not None:
                        m2.setdefault("extras", {}).setdefault("watchmen", {})["vertex_alpha"] = (
                            True
                        )
                    j["materials"].append(m2)
                    self.vamat[mi] = len(j["materials"]) - 1
            return self.vamat[mi]
        if mi not in self.blendmat:
            m2 = json.loads(json.dumps(j["materials"][mi]))
            m2["alphaMode"] = "BLEND"
            m2.pop("alphaCutoff", None)
            j["materials"].append(m2)
            self.blendmat[mi] = len(j["materials"]) - 1
        return self.blendmat[mi]

    def sheet_material(self, mat, layers):
        """Engine values from the texture's sheet.json (char_lib.find_layers):
        the alpha-test reference, the normal-map power and the subtractive blend."""
        if layers.get("blend_info"):
            # the texture is ink / light with its coverage in alpha (char_lib._blend_layer)
            bct = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture", {})
            texture_sheet.blend_material(
                mat,
                layers["blend_info"],
                bct.get("index"),
                (layers.get("sheet") or {}).get("opacity"),
            )
        if layers.get("sheet_name"):  # a sheet other than the texture's first
            mat.setdefault("extras", {}).setdefault("watchmen", {})["sheet"] = layers["sheet_name"]
            # its own name: two materials of one texture would otherwise share one
            # (Blender renames the second "<name>.001")
            mat["name"] = "%s [%s]" % (mat.get("name"), layers["sheet_name"])
        if layers.get("materials") == "engine":
            self.engine_material(mat, layers)
        sheet = layers.get("sheet") if self.va else None
        if not sheet:
            return
        thr = sheet.get("alphaThreshold")
        if mat.get("alphaMode") == "MASK" and thr:
            mat["alphaCutoff"] = round(min(int(thr), 255) / 255.0, 6)
        power = sheet.get("normalMapPower")
        if "normalTexture" in mat and power is not None and abs(float(power) - 1.0) > 1e-6:
            mat["normalTexture"]["scale"] = round(float(power), 6)

    def image_texture(self, data, name):
        """Index of a new texture (sampler 0) of a new PNG image `name` whose bytes
        go into the buffer now."""
        j = self.j
        j["images"].append(
            {"bufferView": self.doc.view(data), "mimeType": "image/png", "name": name}
        )
        j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
        return len(j["textures"]) - 1

    def engine_material(self, mat, layers):
        """materials.py: roughness / specular / emission / alpha mode / culling from
        the sheet (layers["materials"] == "engine", set by char_lib.find_layers)."""
        import materials as _mt

        sheet = layers.get("sheet") or {}
        P = _mt.engine_material(
            sheet,
            layers.get("diffuse"),
            layers.get("spec"),
            layers.get("specsize"),
            layers.get("glow"),
        )
        _mt.apply(
            self.j, mat, P, lambda data, label: self.image_texture(data, mat["name"] + "_" + label)
        )
        if "twoSided" in sheet:
            mat["doubleSided"] = bool(sheet["twoSided"])
        if not layers.get("blend_info"):
            pix_a = bool(layers.get("texAlpha") or layers.get("alphaMask"))
            # the engine's alpha test follows the texture header's alpha flag
            # (0x429e77 -> 0x571d5d): layers["texAlphaFlag"] when the extract has
            # it (sheet.json "textureHasAlpha"), else the pixels
            has_a = layers.get("texAlphaFlag")
            has_a = pix_a if has_a is None else bool(has_a)
            self.sheetalpha[id(mat)] = (sheet, has_a, pix_a)
            amode, cutoff, afac = _mt.alpha(sheet, has_a, False, pix_a)
            mat.pop("alphaMode", None)
            mat.pop("alphaCutoff", None)
            if amode:
                mat["alphaMode"] = amode
            if cutoff is not None:
                mat["alphaCutoff"] = cutoff
            if afac is not None:
                mat["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, afac]

    def material(self, nm):
        """Material index for nm: the textured material of `textures[nm]` (made once per
        name, for the body, attachment and face primitives alike), else a new grey one."""
        j = self.j
        png = (self.textures or {}).get(nm)
        if png is not None and nm in self.texdone:
            return self.texdone[nm]
        if png is not None:
            layers = png if isinstance(png, dict) else {"diffuse": png}

            mat = {
                "name": nm,
                "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 0.85},
                "doubleSided": True,
            }
            if "diffuse" in layers:
                mat["pbrMetallicRoughness"]["baseColorTexture"] = {
                    "index": self.image_texture(layers["diffuse"], nm + "_diffuse")
                }
            if "mr" in layers:
                mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {
                    "index": self.image_texture(layers["mr"], nm + "_mr")
                }
                mat["pbrMetallicRoughness"]["roughnessFactor"] = 1.0
            if "normal" in layers:
                mat["normalTexture"] = {
                    "index": self.image_texture(layers["normal"], nm + "_normal")
                }
            if layers.get("alphaMask"):
                mat["alphaMode"] = "MASK"
                mat["alphaCutoff"] = 0.5
            self.sheet_material(mat, layers)
            if "spec" in layers and layers.get("materials") != "engine":
                mat.setdefault("extensions", {})["KHR_materials_specular"] = {
                    "specularColorTexture": {
                        "index": self.image_texture(layers["spec"], nm + "_spec")
                    }
                }
                j.setdefault("extensionsUsed", [])
                if "KHR_materials_specular" not in j["extensionsUsed"]:
                    j["extensionsUsed"].append("KHR_materials_specular")
            j["materials"].append(mat)
            self.texdone[nm] = len(j["materials"]) - 1
            return self.texdone[nm]
        j["materials"].append(
            {
                "name": nm,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.8, 0.8, 0.82, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.8,
                },
                "doubleSided": True,
            }
        )
        return len(j["materials"]) - 1

    # ---------------------------------------------------------------- meshes
    @staticmethod
    def node_trs(L):
        """4x4 -> glTF node TRS dict (rotation is XYZW, same as glTF)."""
        q = batch_m2q(np.ascontiguousarray(L[:3, :3])[None])[0]
        return {"rotation": [float(x) for x in q], "translation": [float(x) for x in L[:3, 3]]}

    def joint_nodes(self):
        """The body joint nodes (`bnode`, joint k -> node index) and the
        inverse-bind-matrix accessor (`ibmacc`).

        Joint nodes carry the BIND pose, not identity (identity joints with real
        IBMs render the mesh in bind-LOCAL space in every viewer that shows the
        scene before an animation is picked: measured 0.72 m mean vertex
        displacement).  Flat rig: children of an identity `root`, so node-local ==
        node-global and B4[k] goes straight in.  Hierarchy: B4[k] relative to the
        parent joint (local_from_world); the product down the chain gives B4[k]
        back, so the IBMs are the same in both."""
        j, NB, hier = self.j, self.NB, self.hier
        bnames, bpar, jnames = self.bnames, self.bpar, self.jnames
        bnode = self.bnode = [len(j["nodes"]) + k for k in range(NB)]
        B4n = local_from_world(self.B4, bpar) if hier else self.B4
        for k in range(NB):
            nd = {"name": jnames[k] if hier else "b%d" % k}
            nd.update(self.node_trs(B4n[k]))
            if self.skel:
                nd["extras"] = {"bone": bnames[k], "parent": bpar[k]}
                if hier:
                    nd["extras"]["index"] = k
            j["nodes"].append(nd)
        if hier:
            for k in range(NB):
                if bpar[k] >= 0:
                    j["nodes"][bnode[bpar[k]]].setdefault("children", []).append(bnode[k])
        doc = self.doc
        self.ibmacc = doc.accessor(
            doc.view(np.array([m.T.reshape(16) for m in self.IBM], np.float32).tobytes()),
            5126,
            NB,
            "MAT4",
        )

    def primitive(self, part, material_first):
        """The skinned primitive of one part (V, SI, SW, T, UV, material name).
        material_first: the part's material is made before its NORMAL / TANGENT /
        COLOR_0 views (body and face parts) or after them (attachment, alternative
        and outfit parts); a material's images land in the buffer where it is made
        first."""
        V, SI, SW, T, UV, nm = part
        Vg = np.ascontiguousarray(V, np.float32)
        T, pend, vblend = self.vertex_prep(part, Vg, T)
        return self.doc.add_skinned_primitive(
            Vg,
            used_joints(SI, SW),
            SW,
            T,
            UV,
            pend,
            lambda: self.blend(self.material(nm), vblend),
            material_first,
        )

    def body_mesh(self):
        """Mesh 0 ("variant") of the body parts, its node (`mnode`) and skin 0."""
        j = self.j
        prims = []
        for part in self.parts:
            prims.append(self.primitive(part, True))
        j["meshes"].append({"name": "variant", "primitives": prims})
        self.mnode = len(j["nodes"])
        j["nodes"].append({"name": "mesh", "mesh": 0, "skin": 0})
        j["skins"].append({"joints": self.bnode, "inverseBindMatrices": self.ibmacc})
        if self.skel:
            j["skins"][0]["extras"] = {"watchmen": self.skel}

    def extra_meshes(self):
        """One mesh node on skin 0 per attachment, alternative and outfit model
        (`attnodes`); `hidden`: the node indices that go under "alternatives".

        Outfit nodes of the same model: identical data is written once and the
        ACCESSOR is shared (GlbPacker.share; a buffer view shared by two accessors
        would need a byteStride; a shared accessor needs nothing)."""
        j, pk = self.j, self.doc.packer
        parts_record = self.parts_record
        self.attnodes = []
        self.hidden = set()  # node indices that go to the "alternatives" scene only
        _wshown = set(((parts_record or {}).get("weapons") or {}).get("shown") or [])
        _extra = [
            (a, p, parts_record is not None and a not in _wshown, False)
            for a, p in self.attachments or []
        ]
        _extra += [(a, p, True, False) for a, p in self.alt_parts or []]
        _extra += [(a, p, not sh, True) for a, p, sh in self.outfit_parts or []]
        for aname, aparts, _hide, _shared in _extra:
            pk.share = _shared
            # each attachment = its OWN mesh node sharing skin 0 (verts already in
            # body bind space, weighted to the attach bone slot) -> imports as a
            # separate object, individually hideable.
            aprims = []
            for part in aparts:
                # the material after the pending attributes, as this site always wrote it
                aprims.append(self.primitive(part, False))
            if not aprims:
                continue
            mi_ = len(j["meshes"])
            j["meshes"].append({"name": aname, "primitives": aprims})
            if _hide:
                self.hidden.add(len(j["nodes"]))
            self.attnodes.append(len(j["nodes"]))
            j["nodes"].append({"name": aname, "mesh": mi_, "skin": 0})
        pk.share = False

    # ----------------------------------------------------------------- skins
    def face_rig(self):
        """SECOND SKIN: the face rig parented under the body's Head joint -- rides
        every body animation via hierarchy; face poses = local channels on the
        face joints only.  face = dict(bind, parts, anims, attach_idx, M (3,3),
        t (3)) with M,t mapping face-model space -> body bind space.  Sets
        `facenodes`, `proxynodes`, `anchor`, `frn` (face_root, flat rig only),
        `fmnode` (the face mesh node) and, from the face bind (read once here),
        `fb`, `NF`, `B4f`, `M4`.

        Flat rig: `face_root` is a scene root; f_anchor and the proxies under it
        carry WORLD channels, A4[Head]·M4 and A4[bs]·Mk, on every body clip.
        Hierarchy: no face_root; f_anchor is a child of the attach joint (Head)
        and each proxy a child of its body joint bs, with the CONSTANT local
        transforms inv(B4[Head])·M4 and inv(B4[bs])·Mk -- their world transform is
        the same product on every key, and between keys they follow the joint
        they ride instead of being interpolated in world space on their own
        (which let the face drift off the head mid-key).  No channels are written
        for them."""
        self.facenodes = []
        self.proxynodes = []
        self.anchor = self.frn = self.fmnode = None
        face = self.face
        if face is None:
            return
        j, hier, B4, bnode, doc = self.j, self.hier, self.B4, self.bnode, self.doc
        fb = self.fb = load_npz(face["bind"])
        fRb, ftb = fb["Rb"], fb["tb"]
        NF = self.NF = len(fRb)
        B4f = self.B4f = np.tile(np.eye(4), (NF, 1, 1))
        B4f[:, :3, :3] = fRb
        B4f[:, :3, 3] = ftb
        M4 = self.M4 = np.eye(4)
        M4[:3, :3] = face["M"]
        M4[:3, 3] = face["t"]
        ai = face["attach_idx"]
        if not hier:
            self.frn = len(j["nodes"])
            j["nodes"].append({"name": "face_root"})
        anchor = self.anchor = len(j["nodes"])
        nd = {"name": "f_anchor"}
        nd.update(self.node_trs(np.linalg.inv(B4[ai]) @ M4 if hier else M4))
        j["nodes"].append(nd)
        if hier:
            j["nodes"][bnode[ai]].setdefault("children", []).append(anchor)
        proxynodes = self.proxynodes
        _palign = face.get("proxy_align") or None  # per-proxy 4x4 alignment
        for pi, bs in enumerate(face.get("proxy_slots", [])):
            _Mk = _palign[pi] if _palign is not None else M4
            Lp = np.linalg.inv(B4[bs]) @ _Mk if hier else _Mk
            nd = {"name": "face_proxy_b%d_%d" % (bs, pi)}
            nd.update(self.node_trs(Lp))
            pn = len(j["nodes"])
            j["nodes"].append(nd)
            proxynodes.append(pn)
            if hier:
                j["nodes"][bnode[bs]].setdefault("children", []).append(pn)
        facenodes = self.facenodes
        for k in range(NF):
            L = B4f[k]  # LOCAL under f_anchor
            nd = {"name": "f_%s" % str(fb["names"][k])}
            nd.update(self.node_trs(L))
            facenodes.append(len(j["nodes"]))
            j["nodes"].append(nd)
        j["nodes"][anchor]["children"] = facenodes[:]
        if self.frn is not None:
            j["nodes"][self.frn]["children"] = [anchor] + proxynodes
        _fj_ibms = (
            [np.linalg.inv(B4f[k]) for k in range(NF)]
            + [np.eye(4) for _ in proxynodes]
            + [np.linalg.inv(M4)]
        )
        fibm = doc.accessor(
            doc.view(np.array([m.T.reshape(16) for m in _fj_ibms], np.float32).tobytes()),
            5126,
            len(_fj_ibms),
            "MAT4",
        )
        fprims = []
        for part in face["parts"]:
            fprims.append(self.primitive(part, True))
        fmi = len(j["meshes"])
        j["meshes"].append({"name": "face", "primitives": fprims})
        self.fmnode = len(j["nodes"])
        j["nodes"].append({"name": "face_mesh", "mesh": fmi, "skin": 1})
        j["skins"].append(
            {"joints": facenodes + proxynodes + [anchor], "inverseBindMatrices": fibm}
        )

    def scene_roots(self):
        """The node "root" (`root`), the scene's root nodes and the skins'
        skeletons; the face skin's extras under the engine face rule."""
        import face_rule as _fr

        j, hier, bnode, face = self.j, self.hier, self.bnode, self.face
        root = self.root = len(j["nodes"])
        _shown = [a for a in self.attnodes if a not in self.hidden]
        if hier:
            # skinned meshes at the scene root (glTF ignores a skinned mesh node's
            # transform; the validator flags one with a parent): the joints alone
            # hang under `root`
            j["nodes"].append(
                {"name": "root", "children": [bnode[k] for k in range(self.NB) if self.bpar[k] < 0]}
            )
            j["scenes"][0]["nodes"] = [root, self.mnode] + _shown
        else:
            j["nodes"].append({"name": "root", "children": bnode + [self.mnode] + _shown})
            j["scenes"][0]["nodes"] = [root]
        j["skins"][0]["skeleton"] = root
        if face is None:
            return
        if hier:
            # the face joints hang under body joints: the body root is their
            # common root
            j["scenes"][0]["nodes"].append(self.fmnode)
            j["skins"][1]["skeleton"] = root
        else:
            j["scenes"][0]["nodes"].append(self.frn)
            j["nodes"][self.frn].setdefault("children", []).append(self.fmnode)
            j["skins"][1]["skeleton"] = self.frn
        if self.engine:
            _fm = (self.meta or {}).get("face") or {}
            _sx = {
                "head_model": face.get("head"),
                "pose_family": face.get("family"),
                "face_classes": sorted(
                    n
                    for n, r in (_fm.get("classes") or {}).items()
                    if r.get("pose_family") == face.get("family")
                ),
                "anchor_node": "f_anchor" if hier else "face_root",
                "rule": "engine",
                "track_choice": _fr.TRACK_CHOICE,
                "idle_cycle_baked": bool(self.idle),
            }
            if hier:
                _sx["anchor_parent"] = self.jnames[face["attach_idx"]]
            if face.get("game_head"):
                _sx["game_head"] = face["game_head"]
            j["skins"][1]["extras"] = {"watchmen": {"face": _sx}}

    def below_head(self, k):
        """True when face joint k hangs below the face bind's "Head"."""
        fn, fp = self._fn, self.fb["par"]
        p = fp[k]
        while p >= 0:
            if fn[p] == "Head":
                return True
            p = fp[p]
        return False

    def face_locals(self, A):
        """pose palettes frame (NF,3,4) -> (quat,(NF,3)) LOCALS under anchor."""
        B4f = self.B4f
        _A4 = np.concatenate(
            [
                A.astype(np.float64),
                np.tile(np.array([0, 0, 0, 1.0]).reshape(1, 1, 4), (self.NF, 1, 1)),
            ],
            axis=1,
        )
        _W = np.einsum("kab,kbc->kac", _A4, B4f)
        _fx = B4f[self.fhead] @ np.linalg.inv(_W[self.fhead])
        _L = np.einsum("ab,kbc->kac", _fx, _W)
        return batch_m2q(_L[:, :3, :3]), _L[:, :3, 3]

    def face_poses(self):
        """`facemask` (the face joints below Head; the only ones animated),
        `fhead`, and `faceride`: (attach_idx, proxy slots, proxy alignment,
        neutral locals, per-pose locals, blink data, face_synth) when the face
        has poses, else None."""
        self.facemask = None
        self.faceride = None
        face = self.face
        if face is None:
            return
        fb, NF = self.fb, self.NF
        self._fn = [str(x) for x in fb["names"]]
        self.facemask = [k for k in range(len(self._fn)) if self.below_head(k)]
        self.fhead = self._fn.index("Head")
        if not face.get("anims"):
            return
        _cand = [a for a in face["anims"] if "MouthClosed_EyesOpen" in a[0]] or list(face["anims"])
        _fneut = self.face_locals(_cand[0][1][0])
        # per-category pose locals (AUTO-PAIRING: ATT face on attack clips etc.)
        # guard ONLY the import: a blanket except would also swallow
        # face_locals errors and silently disable ALL auto-pairing (and blink
        # categorization) on the first bad pose.
        _fpose = {}
        try:
            import face_synth as _fs
        except Exception:
            _fs = None
        if _fs is not None:
            for _pn, _pp in (face.get("auto_poses") or {}).items():
                try:
                    _fpose[_pn] = self.face_locals(_pp)
                except Exception as _pe:
                    print("  ! auto-pose %s failed: %s" % (_pn, _pe))
        # blink data: EyeLid bone locals for neutral vs eyes-closed
        _fblink = None
        _fn2 = [str(x) for x in fb["names"]]
        if face.get("blink_closed") is not None and "EyeLid" in _fn2:
            _lidk = [
                k for k in range(NF) if "eyelid" in _fn2[k].lower() or _fn2[k] in ("Leye", "Reye")
            ]
            _fblink = (_lidk, self.face_locals(face["blink_closed"]))
        self.faceride = (
            face["attach_idx"],
            face.get("proxy_slots", []),
            face.get("proxy_align") or None,
            _fneut,
            _fpose,
            _fblink,
            _fs,
        )

    # ------------------------------------------------------------- animation
    def time_accessor(self, times):
        """The float32 SCALAR key-time accessor of `times` (float32, from 0)."""
        doc = self.doc
        return doc.accessor(
            doc.view(times.tobytes()), 5126, len(times), "SCALAR", [0.0], [float(times[-1])]
        )

    def anim_record(self, animname, sm, chn, frames, fps, finfo=None):
        """The glTF animation of one body clip, with its clip extras."""
        import anim_meta as _am

        a = {"name": animname, "samplers": sm, "channels": chn}
        ex = None
        if self.meta is not None:
            ex = _am.clip_extras(self.meta, animname, fps=fps, frames=frames)
        if finfo is not None:  # what the face channels of this clip show
            ex = dict(ex or {}, face=finfo)
        if ex is not None:
            a["extras"] = {"watchmen": ex}
        return a

    def face_track_channels(self, animname, F, fps, sm, chn):
        """Engine rule: face-bone channels of one body clip from the face track
        of the state(s) that play it.  Returns the `face` extras record."""
        import face_rule as _fr

        face, meta, idle = self.face, self.meta, self.idle
        _fs = self.faceride[6]
        _fpose_all = self.faceride[4]
        dur = max((F - 1) / fps, 1e-3)
        fam = face.get("family")
        fmeta = (meta or {}).get("face") or {}
        chosen = _fr.choose_track(meta, animname, fam) if fmeta else None
        info = {"rule": "engine", "pose_family": fam}
        sched = []
        if chosen is not None:
            fclass = fmeta["classes"][chosen["source"]["class_face"]]
            sched, skipped = _fr.pose_schedule(
                chosen, fclass, animname, lambda pp: None if pp is None else pp * dur, idle, dur
            )
            sched = [x for x in sched if x[1] in _fpose_all and x[0] <= dur + 1e-6]
            info.update(
                face_class=chosen["source"]["class_face"],
                baked_from={k: v for k, v in chosen["source"].items() if k != "class_face"},
                candidates=chosen["candidates"],
                distinct_tracks=chosen["distinct_tracks"],
                confidence=chosen["confidence"],
                track=chosen["track"],
                not_baked=skipped,
                idle_cycle_baked=bool(idle),
            )
        else:
            info["note"] = "no face track for this clip in the metadata: neutral pose"
        if not sched:
            neutral = [k for k in _fpose_all if "MouthClosed_EyesOpen" in k] or sorted(_fpose_all)
            sched = [
                (
                    0.0,
                    (
                        neutral[0]
                        if "NiteOwl_MouthClosed" not in _fpose_all
                        else "NiteOwl_MouthClosed"
                    ),
                    0.0,
                )
            ]
        info["poses"] = [
            {"written_time_s": round(t, 4), "pose": p, "ease_in_s": e} for t, p, e in sched
        ]
        kt = _fr.key_times(sched, dur) if len(sched) > 1 else [0.0, dur]
        ktf = np.array(kt, np.float32)
        ta3 = self.time_accessor(ktf)
        QT = [_fs.blend_locals(_fpose_all, _fr.pose_weights(sched, t)) for t in kt]
        Qk = np.stack([q for q, _t in QT])  # (K, NF, 4)
        Tk = np.stack([t for _q, t in QT])
        for f in range(1, len(kt)):
            flip = np.einsum("kc,kc->k", Qk[f], Qk[f - 1]) < 0
            Qk[f, flip] *= -1
        for k in self.facemask:
            self.doc.add_trs(sm, chn, self.facenodes[k], ta3, Qk[:, k], Tk[:, k])
        return info

    def blink_channels(self, animname, times, sm, chn):
        """Legacy rule: sparse blink keys on the lid bones, neutral -> closed ->
        neutral every ~3 s (deterministic per clip), 0.24 s per blink."""
        _fneut, _fblink = self.faceride[3], self.faceride[5]
        _dur = max(float(times[-1]), 0.5)
        _per = 2.7 + ((zlib.crc32(animname.encode()) % 100) / 100.0) * 0.9  # hash() is per-process
        _keys = [0.0]
        _t = _per * 0.6
        while _t + 0.3 < _dur:
            _keys += [_t, _t + 0.07, _t + 0.14, _t + 0.24]
            _t += _per
        _keys.append(_dur)
        _kt = np.array(_keys, np.float32)
        # weights per blink group [start, closed, closed, open] ->
        # w=[0,1,1,0]
        _wts = np.zeros(len(_kt))
        for _i in range(1, len(_kt) - 4, 4):
            _wts[_i + 1] = 1.0
            _wts[_i + 2] = 1.0
        _ta3 = self.time_accessor(_kt)
        _lidk, _fcl = _fblink
        for k in _lidk:
            _qn, _tn = _fneut[0][k], _fneut[1][k]
            _qc, _tc = _fcl[0][k], _fcl[1][k]
            if float(np.dot(_qn, _qc)) < 0:
                _qc = -_qc
            _Q = np.array([(_qn * (1 - w) + _qc * w) for w in _wts], np.float32)
            _Q /= np.linalg.norm(_Q, axis=1, keepdims=True)
            _T = np.array([(_tn * (1 - w) + _tc * w) for w in _wts], np.float32)
            self.doc.add_trs(sm, chn, self.facenodes[k], _ta3, _Q, _T)

    def face_ride_channels(self, animname, A4, F, fps, times, ta, sm, chn):
        """The face channels of one full body clip; returns the `face` extras
        record under the engine rule, else None.

        The face armature rides via ONE anchor joint (face bones are its children
        with LOCAL channels -> expressions follow the head, and a FACE action
        layered/posed on top keeps riding).  Hierarchy rig: the anchor and the
        proxies ride their body joints with constant local transforms -- no
        channels of their own."""
        doc, hier, M4 = self.doc, self.hier, self.M4
        _ai, _pslots, _palign, _fneut, _fpose, _fblink, _fs = self.faceride
        _pslots = () if hier else _pslots
        _finfo = None
        if not hier:
            FH = A4[:, _ai]  # (F,4,4)
            La = np.einsum("fab,bc->fac", FH, M4)
            Qf = batch_m2q(La[:, :3, :3])
            for f in range(1, F):
                if (Qf[f] * Qf[f - 1]).sum() < 0:
                    Qf[f] *= -1
            doc.add_trs(sm, chn, self.anchor, ta, Qf, La[:, :3, 3])
        # ENGINE RULE: the face track of the state(s) that play this clip
        _eng = self.engine and _fpose and _fs is not None
        if _eng:
            _finfo = self.face_track_channels(animname, F, fps, sm, chn)
        # LEGACY AUTO-PAIRED face: category pose for combat/damage/dance
        # clips, neutral otherwise
        _base = _fneut
        if not _eng and _fs is not None and _fpose:
            _pn = _fs.category_pose(animname, _fpose)
            if _pn:
                _base = _fpose[_pn]
        t2 = np.array([0.0, max(float(times[-1]), 1e-3)], np.float32)
        ta2 = None if _eng else self.time_accessor(t2)
        _blinkset = set(_fblink[0]) if (_fblink is not None and _base is _fneut) else set()
        if _eng:
            _blinkset = set()
        for k in () if _eng else self.facemask:
            if k in _blinkset:
                continue  # blink channel written below
            doc.add_trs(
                sm,
                chn,
                self.facenodes[k],
                ta2,
                np.tile(_base[0][k].astype(np.float32), (2, 1)),
                np.tile(_base[1][k].astype(np.float32), (2, 1)),
            )
        if _blinkset:
            self.blink_channels(animname, times, sm, chn)
        for pi, bs in enumerate(_pslots):
            _MkCi = _palign[pi] if _palign is not None else M4
            Lp = np.einsum("fab,bc->fac", A4[:, bs], _MkCi)
            Qf = batch_m2q(Lp[:, :3, :3])
            for f in range(1, F):
                if (Qf[f] * Qf[f - 1]).sum() < 0:
                    Qf[f] *= -1
            doc.add_trs(sm, chn, self.proxynodes[pi], ta, Qf, Lp[:, :3, 3])
        return _finfo

    def body_clip(self, entry):
        """The animation of one manifest entry: (name, pal, fps) or (name, pal,
        fps, bone_indices) -- the 4-tuple form writes channels ONLY for the
        listed bones (partial overlay anims, e.g. GRIP hand poses layered over
        body clips in NLA); the full form also writes the face channels."""
        NB = self.NB
        if len(entry) == 4:
            animname, A, fps, bmask = entry
        else:
            animname, A, fps = entry
            bmask = None
        _finfo = None
        F = len(A)
        times = (np.arange(F) / fps).astype(np.float32)
        ta = self.time_accessor(times)
        sm = []
        chn = []
        A4 = np.concatenate(
            [
                A.astype(np.float64),
                np.tile(np.array([0, 0, 0, 1.0]).reshape(1, 1, 1, 4), (F, NB, 1, 1)),
            ],
            axis=2,
        )  # (F,NB,4,4)
        W = np.einsum("fkab,kbc->fkac", A4, self.B4)  # (F,NB,4,4) joint world
        if self.hier:
            # local to the parent joint, from this entry's own palette (a masked
            # overlay's bones are posed relative to whatever drives their parents)
            W = local_from_world(W, self.bpar)
        Q = batch_m2q(W[:, :, :3, :3].reshape(-1, 3, 3)).reshape(F, NB, 4)
        # sign continuity along time per bone
        for f in range(1, F):
            flip = np.einsum("kc,kc->k", Q[f], Q[f - 1]) < 0
            Q[f, flip] *= -1
        Tt = W[:, :, :3, 3]
        for k in range(NB) if bmask is None else bmask:
            self.doc.add_trs(sm, chn, self.bnode[k], ta, Q[:, k], Tt[:, k])
        if self.faceride is not None and bmask is None:
            _finfo = self.face_ride_channels(animname, A4, F, fps, times, ta, sm, chn)
        self.j["animations"].append(self.anim_record(animname, sm, chn, F, fps, _finfo))

    def face_clips(self):
        """One animation per face clip of the face rig: LOCAL channels of the
        face joints below Head."""
        import face_rule as _fr

        NF, B4f, fhead = self.NF, self.B4f, self.fhead
        for animname, A, fps in self.face["anims"]:
            F = len(A)
            times = (np.arange(F) / fps).astype(np.float32)
            ta = self.time_accessor(times)
            A4 = np.concatenate(
                [
                    A.astype(np.float64),
                    np.tile(np.array([0, 0, 0, 1.0]).reshape(1, 1, 1, 4), (F, NF, 1, 1)),
                ],
                axis=2,
            )
            Wp = np.einsum("fkab,kbc->fkac", A4, B4f)
            fix = np.einsum("ab,fbc->fac", B4f[fhead], np.linalg.inv(Wp[:, fhead]))
            L = np.einsum("fab,fkbc->fkac", fix, Wp)  # LOCAL under anchor
            Q = batch_m2q(L[:, :, :3, :3].reshape(-1, 3, 3)).reshape(F, NF, 4)
            for f in range(1, F):
                flip = np.einsum("kc,kc->k", Q[f], Q[f - 1]) < 0
                Q[f, flip] *= -1
            Tt = L[:, :, :3, 3]
            sm = []
            chn = []
            for k in self.facemask:  # only bones BELOW Head: the rig's own
                # Bip01/Neck/Head tracks carry the cutscene neck posture and
                # would double-rotate the head that already rides the body.
                self.doc.add_trs(sm, chn, self.facenodes[k], ta, Q[:, k], Tt[:, k])
            _fa = {"name": animname, "samplers": sm, "channels": chn}
            if self.engine:
                _fa["extras"] = {"watchmen": {"face_pose": _fr.pose_extras(self.meta, animname)}}
            self.j["animations"].append(_fa)

    # ------------------------------------------------------------------ file
    def asset_records(self):
        """The parts record (scene "game", node "alternatives"), asset_extras and
        the restored-content note in asset.extras.watchmen.

        The one scene holds the character as the game shows it.  The hidden
        parts hang under a node "alternatives" that is in NO scene: viewers
        draw scenes, so they never show it, and Blender's importer puts such
        nodes in a switched-off collection ("Orphan Nodes"), still bound to the
        armature.  (Ruled out: a second scene sharing the skeleton root is valid,
        but three.js clones a node used by two scenes and the animations then
        drive the copy that is not displayed.)"""
        j, attnodes, hidden = self.j, self.attnodes, self.hidden
        if self.parts_record is not None:
            j["scenes"][0]["name"] = "game"
            _alt = [a for a in attnodes if a in hidden]
            if _alt:
                j["nodes"].append({"name": "alternatives", "children": _alt})
            _names = {j["nodes"][a]["name"] for a in attnodes}
            _rec = dict(self.parts_record)
            _rec["hidden_nodes"] = [j["nodes"][a]["name"] for a in attnodes if a in hidden]
            _rec["alternatives"] = [x for x in _rec.get("alternatives", []) if x["node"] in _names]
            _rec["hidden_under"] = (
                "node 'alternatives', which is in no scene; skinned to the same skeleton "
                "(skin 0).  Blender: collection 'Orphan Nodes', switched off after import"
                if _alt
                else None
            )
            j["asset"].setdefault("extras", {}).setdefault("watchmen", {})["parts"] = _rec
        if self.asset_extras:  # e.g. {"reconstruction": {...}} for a variant the game does not ship
            j["asset"].setdefault("extras", {}).setdefault("watchmen", {}).update(self.asset_extras)
        # restored content among the mesh pieces is named in the same record
        _pieces = [self.parts, (self.face or {}).get("parts")]
        _pieces += [p for _a, p in self.attachments or []]
        _pieces += [p for _a, p in self.alt_parts or []]
        _pieces += [p for _a, p, _s in self.outfit_parts or []]
        if any(model_mesh.lash_is_restored(pt[4]) for _pl in _pieces for pt in _pl or ()):
            _w = j["asset"].setdefault("extras", {}).setdefault("watchmen", {})
            _w["reconstruction"] = (
                _w.get("reconstruction") or {}
            ) | model_mesh.lash_reconstruction_note()

    def ragdoll_helpers(self):
        """The ragdoll rig (ragdoll_rig.glb_helpers) as helper nodes under a node
        "ragdoll" that is in no scene: `RB.<bone>.<i>` proxy meshes skinned rigidly
        to their joint, `RJ.<child bone>` empties.  Appended last, nothing above
        refers to them."""
        ragdoll = self.ragdoll
        if not (ragdoll and (ragdoll.get("shapes") or ragdoll.get("joints"))):
            return
        import ragdoll_rig as _rr

        j, av, ac = self.j, self.doc.view, self.doc.accessor
        # the joint node names in the helpers' extras are this file's
        ragdoll = _rr.relabel_joint_nodes(
            ragdoll, self.jnames if self.hier else ["b%d" % k for k in range(self.NB)]
        )
        _rk = []
        _rmat = None
        for _sh in ragdoll.get("shapes", []):
            if _rmat is None:
                _rmat = len(j["materials"])
                j["materials"].append(
                    {
                        "name": "RAGDOLL proxy",
                        "pbrMetallicRoughness": {
                            "baseColorFactor": [1.0, 0.55, 0.1, 0.35],
                            "metallicFactor": 0.0,
                            "roughnessFactor": 1.0,
                        },
                        "alphaMode": "BLEND",
                        "doubleSided": True,
                    }
                )
            _V = np.ascontiguousarray(_sh["verts"], np.float32)
            _T = np.asarray(_sh["tris"], np.uint32).reshape(-1, 3)
            _c = _V.mean(0)  # shapes are convex: wind every triangle outward
            _n = np.cross(_V[_T[:, 1]] - _V[_T[:, 0]], _V[_T[:, 2]] - _V[_T[:, 0]])
            _fl = np.einsum("ij,ij->i", _n, _V[_T].mean(1) - _c) < 0
            _T[_fl] = _T[_fl][:, [0, 2, 1]]
            _SI = np.zeros((len(_V), 4), np.uint16)
            _SI[:, 0] = _sh["slot"]
            _SW = np.zeros((len(_V), 4), np.float32)
            _SW[:, 0] = 1.0
            _prim = {
                "attributes": {
                    "POSITION": ac(
                        av(_V.tobytes(), 34962),
                        5126,
                        len(_V),
                        "VEC3",
                        _V.min(0).tolist(),
                        _V.max(0).tolist(),
                    ),
                    "JOINTS_0": ac(av(_SI.tobytes(), 34962), 5123, len(_V), "VEC4"),
                    "WEIGHTS_0": ac(av(_SW.tobytes(), 34962), 5126, len(_V), "VEC4"),
                },
                "indices": ac(
                    av(np.ascontiguousarray(_T).tobytes(), 34963), 5125, _T.size, "SCALAR"
                ),
                "material": _rmat,
                "mode": 4,
            }
            j["meshes"].append({"name": _sh["name"], "primitives": [_prim]})
            _rk.append(len(j["nodes"]))
            j["nodes"].append(
                {
                    "name": _sh["name"],
                    "mesh": len(j["meshes"]) - 1,
                    "skin": 0,
                    "extras": {"watchmen": {"ragdoll": _sh["extras"]}},
                }
            )
        for _jn in ragdoll.get("joints", []):
            _rk.append(len(j["nodes"]))
            j["nodes"].append(
                {
                    "name": _jn["name"],
                    "translation": _jn["translation"],
                    "rotation": _jn["rotation"],
                    "extras": {"watchmen": {"ragdoll": _jn["extras"]}},
                }
            )
        j["nodes"].append({"name": "ragdoll", "children": _rk})
        j["asset"].setdefault("extras", {}).setdefault("watchmen", {})["ragdoll"] = ragdoll.get(
            "extras", {}
        )

    def build(self):
        """The whole document, in file order."""
        self.joint_nodes()
        self.body_mesh()
        self.extra_meshes()
        self.face_rig()
        self.scene_roots()
        self.face_poses()
        for entry in self.manifest:
            self.body_clip(entry)
        if self.face is not None:
            self.face_clips()
        self.asset_records()
        self.ragdoll_helpers()
        return self

    def glb(self):
        """The .glb bytes of the built document (empty lists dropped, the
        sampler only with textures, frame.finish_gltf applied)."""
        j = self.j
        for kk in ("animations", "skins", "images", "textures", "materials"):
            if not j.get(kk):
                j.pop(kk, None)
        if "textures" not in j:
            del j["samplers"]
        return self.doc.finish()


def write_glb(
    parts,
    manifest,
    out,
    bindnpz,
    textures=None,
    face=None,
    attachments=None,
    meta=None,
    face_rule=None,
    face_idle=None,
    alt_parts=None,
    parts_record=None,
    outfit_parts=None,
    asset_extras=None,
    ragdoll=None,
    rig=None,
):
    """meta: optional anim_meta.build() table -> per-animation `extras` (events,
    loop, pair partner + placement).  Bone names/parents and the coordinate
    conventions are written to `extras` whether or not meta is given.

    textures: optional {material_name: png_bytes | dict} -> embedded maps.
    dict form: {'diffuse':png, 'normal':png, 'mr':png, 'spec':png} (all optional).
    normal = glTF convention (green up); mr = occlusion/roughness/metallic in R/G/B;
    spec -> KHR_materials_specular specularColorTexture.

    face_rule: "engine" (default; $WATCHMEN_FACE_RULE) bakes into every body
    clip the face track the game plays with it (face_rule.choose_track, from
    meta["face"]); "legacy" = the rule of releases before 1.4.0: a pose picked from the clip NAME
    plus synthetic blink keys.  face_idle: also bake the seeded idle cycle (default
    on; $WATCHMEN_FACE_IDLE=0 turns it off).

    alt_parts: [(node name, parts)] -- models the game does NOT show for this
    variant (other collection members' hair, jackets ...).  Each becomes a mesh
    node of its own on skin 0, like an attachment.  parts_record: the `parts`
    extras (parts_rule.record, with `weapons`).  When it is given, the scene
    ("game") holds what the game shows; the alt_parts nodes and the attachments
    not named in parts_record["weapons"]["shown"] hang under a node
    "alternatives" that is in no scene.  Viewers draw scenes and never show it;
    Blender imports it into a switched-off collection ("Orphan Nodes").
    Without parts_record nothing is hidden.
    outfit_parts: [(node name, parts, shown)] -- the models that differ between the
    variant's outfits (parts_rule.outfits), one node `OUTFIT <k> <model>` per outfit
    and model on skin 0: the shown outfit's nodes are in the scene (scene roots in the
    hierarchical rig, children of the root in the flat one), the others hang under
    "alternatives".  Nodes of the same model share their vertex
    data (identical data is written once and the accessor shared), only the
    materials differ.  asset_extras: merged into asset.extras.watchmen.  A piece with restored
    eyelash UVs (model_mesh.LASH_RESTORE) adds reconstruction.eyelash_uvs there.
    ragdoll: ragdoll_rig.glb_helpers(...) -- the character's ragdoll rig as helper
    nodes under a node "ragdoll" that is in no scene (hidden like "alternatives"):
    `RB.<bone>.<i>` proxy meshes skinned rigidly to the bone's joint, `RJ.<child
    bone>` empties at the joint frames; parameters in the nodes' extras.  Appended
    after everything else, so the rest of the file is the same with or without it.

    rig: "hierarchy" / "flat" (None = rig_mode(): $WATCHMEN_RIG, default "hierarchy").
    The hierarchy names joint node k after its bone (joint_node_names), parents it to
    the joint of the bone's parent, writes rest and animation TRS local to that
    parent, hangs the face rig on the body joints (f_anchor under the attach joint,
    each face proxy under its joint, constant local transforms, no channels; no
    face_root) and puts the skinned mesh nodes the scene shows at the scene root; a bind
    without names and parents, or with a parent table that is not a tree, is
    written flat.  "flat" is the flat layout (see RIG_MODES).  The mode written,
    and why a requested hierarchy was not, is in asset.extras.watchmen.rig."""
    _glb = (
        VariantGlb(
            parts,
            manifest,
            bindnpz,
            textures=textures,
            face=face,
            attachments=attachments,
            meta=meta,
            face_rule=face_rule,
            face_idle=face_idle,
            alt_parts=alt_parts,
            parts_record=parts_record,
            outfit_parts=outfit_parts,
            asset_extras=asset_extras,
            ragdoll=ragdoll,
            rig=rig,
        )
        .build()
        .glb()
    )
    _tmp = str(out) + ".tmp"
    with open(_tmp, "wb") as fh:
        fh.write(_glb)
    os.replace(_tmp, out)
    # 12-byte header + the two chunks' data (their 8-byte headers not counted, as before)
    print("wrote %s  (%d anims, %.1f MB)" % (out, len(manifest), (len(_glb) - 16) / 1e6))


# Skeleton asset name -> the bind npz built for it.  Populated from a binds
# directory (watchmenlib.ensure_binds / `watchmen binds`); no path is hardcoded.
_BIND_KEY = {
    "Female_Skeleton": "female",
    "Large_Gimp_Skeleton": "gimp",
    "Medium_Skeleton": "medium",
    "Large_Skeleton": "large",
    "Small_Skeleton": "small",
    "Rorschach": "rsh",
    "NiteOwl": "nto",
}


def binds_from_dir(binddir):
    """-> {skeleton asset name: bind npz path} for the binds present in binddir."""
    import os as _os

    out = {}
    for skel, key in _BIND_KEY.items():
        p = _os.path.join(binddir, "bind_%s_file_v1.npz" % key)
        if _os.path.exists(p):
            out[skel] = p
    return out


CLIP_PREFIX = {"Female_Skeleton": ("EN4", "BS2"), "Large_Gimp_Skeleton": ("EN2",)}


def clip_families(skel, fragjson=None):
    """Clip name prefixes of skeleton `skel`, as `characters` bakes them
    (characters_export.CLIP_PREFIX; a fragment under a Part 1 extract takes
    CLIP_PREFIX_P1, which adds a family to the big and the fast enemies)."""
    import characters_export as _ce

    key = _BIND_KEY.get(skel)
    prefix = _ce.CLIP_PREFIX.get(key, ("EN4",))
    ex = os.path.abspath(fragjson) if fragjson else ""
    while ex and os.path.basename(ex).lower() != "extracted" and os.path.dirname(ex) != ex:
        ex = os.path.dirname(ex)
    if os.path.basename(ex).lower() == "extracted" and _ce._is_part1(os.path.dirname(ex)):
        prefix = _ce.CLIP_PREFIX_P1.get(key, prefix)
    return (prefix,) if isinstance(prefix, str) else tuple(prefix)


def no_bake_note(bakedir, prefix):
    """The line `build` prints when BAKEDIR holds no bake of the skeleton's clip families."""
    return "  note: no bake in %s for the clip families %s (%s*.npy): the GLB gets no clip" % (
        bakedir,
        "/".join(prefix),
        prefix[0],
    )


def variant_from_fragment(fragjson, variant):
    import kapow_json

    try:
        d = kapow_json.load_fragment(fragjson)  # the binary .fragment beside it wins
    except (OSError, ValueError, KeyError, IndexError) as ex:
        ex.add_note("fragment %s (variant %s)" % (fragjson, variant))
        raise
    inst = [i for i in d["instances"] if i.get("name") == variant and i.get("model_ref")]
    if not inst:
        raise SystemExit(
            "variant %r not found (have: %s)"
            % (variant, [i["name"] for i in d["instances"] if i.get("model_ref")])
        )
    refs = [r.rsplit("/", 1)[-1].replace(".model", "") for r in inst[0]["model_ref"]]
    skel = [r for r in refs if "Skeleton" in r]
    meshes = [r for r in refs if "Skeleton" not in r]
    heads = [m for m in meshes if "head" in m.lower()]
    if heads:
        noskl = [m for m in heads if "noskl" in m.lower()]
        keep = noskl[0] if noskl else heads[0]
        for m in heads:
            if m != keep:
                meshes.remove(m)
    return (skel[0] if skel else None), meshes


def build(
    fragjson,
    variant,
    out,
    bakedir="bake",
    bank=None,
    prefix=None,
    bind=None,
    binddir=None,
    jiggle=False,
    jiggle_model=None,
    meta=None,
    naz=None,
    extract_root=None,
):
    """One fragment variant -> one GLB carrying every baked clip in `bakedir`.
    The GLB has the skinned meshes with flat materials and the clips; it has no
    textures, no tangents, no face rig, no weapons and no ragdoll helpers (the
    `characters` export writes the full character).
    jiggle: bake the jiggle bones; jiggle_model: 'solver' / 'pivot' / 'pinned' (None =
    jiggle_d6.DEFAULT_MODEL, 'solver').
    meta: the animation metadata table (anim_meta.build / `watchmen animmeta`).  With
    it the clips get the same `extras` as in the `characters` export and the solver
    bakes looping clips as closed laps; without it (None) there
    are no clip extras and every clip is baked as non-looping.  No head is attached
    here, so there are no face channels in either case.

    bind    : path to the bind npz for this variant's skeleton, or
    binddir : a directory of binds (see `watchmen binds`) to pick it from.
    bank    : {clip name: .animation path or header bytes}.  A bake in `bakedir` holds
              the palettes only; the clip's duration comes from here.  A clip that is
              not in the bank is written at 30 fps and named in a note.
    naz     : the archive the meshes are read from (None: `01_game.naz`, else
              `game.naz`, in the current directory).
    extract_root : the extract output the fragment belongs to; the jiggle bake takes the
              PhysicsWorld values of its GameEssentials fragment (None: the shipped values).
    """
    skel, meshes = variant_from_fragment(fragjson, variant)
    if not bind and binddir:
        bind = binds_from_dir(binddir).get(skel)
    if not bind:
        raise ValueError(
            "no bind for skeleton %r -- pass bind=<npz> or binddir=<dir built by "
            "`watchmen binds NAZ OUT/binds`)" % skel
        )
    if prefix is None:
        prefix = clip_families(skel, fragjson)
    if isinstance(prefix, str):
        prefix = (prefix,)
    print(
        "variant %s: skeleton=%s meshes=%s bind=%s clips=%s" % (variant, skel, meshes, bind, prefix)
    )
    bt = load_npz(bind)
    pal_names = [str(x) for x in bt["names"]]
    parts = load_parts(meshes, pal_names, naz=naz)
    manifest = []
    import glob as _g

    # jiggle_d6 'engine' is the bake default: it is at capture parity (dance
    # capture 3.1-3.8deg vs d6 2.65 / AR2+gain 4.4; ENGINE_CONSTANTS.md) and
    # file-only.
    from jiggle_d6 import apply_jiggle, load_world_props

    world = load_world_props(extract_root) if jiggle else None
    _files = []
    for pf in prefix:
        _files += _g.glob(os.path.join(bakedir, pf + "*.npy"))
    if not _files:
        print(no_bake_note(bakedir, prefix))
    for f in sorted(set(_files)):
        A = np.load(f)
        nm = os.path.basename(f)[:-4]
        fps = 30.0
        timed = False
        if bank:
            # tolerant lookup: bake_v4 banks key by BARE clip name
            # ({clipname: header_bytes_or_path}, bake_v4.py:155); an
            # nm+".animation"-only lookup would miss on those and leave
            # every clip at the 30fps fallback (2x slow on FULL-rate clips).
            h = bank.get(nm + ".animation")
            if h is None:
                h = bank.get(nm)
            if h is None:
                h = bank.get(nm.strip())
            if isinstance(h, str):
                with open(h, "rb") as _fh:
                    h = _fh.read()
            if h is not None:
                # header = [f32 keyRate Hz][f32 duration s] ... -- hdr[0] is the
                # RATE, not the duration (bake_v4.py:265).  fps must match
                # bake_v4.fps_for(): (keys-1)/duration.
                import bake_v4

                try:
                    dur = struct.unpack_from(bake_v4.detect_clip_order(h) + "f", h, 4)[0]
                except (struct.error, ValueError) as ex:
                    ex.add_note("clip %s: header of %d bytes in the bank" % (nm, len(h)))
                    raise
                if dur > 0 and len(A) > 1:
                    fps = (len(A) - 1) / dur
                    timed = True
        if not timed and len(A) > 1:
            print("  note: clip %s written at 30 fps (its duration is not known)" % nm)
        if jiggle:
            try:
                A = apply_jiggle(
                    A, fps, bind, model=jiggle_model, loop=clip_loops(meta, nm), props=world
                )
            except Exception as e:
                print("  jiggle skip %s: %s" % (nm, e))
        manifest.append((nm, A, fps))
    write_glb(parts, manifest, out, bind, meta=meta)


def clip_loops(meta, name):
    """The game's loop flag of clip `name` in an anim_meta table (False when unknown)."""
    if not meta:
        return False
    import anim_meta

    return bool((anim_meta._find_clip(meta, name)[1] or {}).get("loop"))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("frag")
    ap.add_argument("variant")
    ap.add_argument("out")
    ap.add_argument(
        "--bank",
        default=None,
        help="a pickled {clip name: header bytes or path} (plain data only: a pickle that"
        " names a class or function is refused)",
    )
    ap.add_argument("--jiggle", action="store_true")
    from jiggle_d6 import MODELS as _jiggle_models

    ap.add_argument("--jiggle-model", choices=tuple(sorted(_jiggle_models)), default=None)
    ap.add_argument("--bakedir", default="bake")
    a = ap.parse_args()
    bank = None
    if a.bank:
        with open(a.bank, "rb") as _fh:
            bank = restricted_load(_fh)
    build(
        a.frag,
        a.variant,
        a.out,
        bakedir=a.bakedir,
        bank=bank,
        jiggle=a.jiggle or a.jiggle_model is not None,
        jiggle_model=a.jiggle_model,
    )
