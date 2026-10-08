#!/usr/bin/env python3
# ONE GLB PER CHARACTER VARIANT with ALL of its animations.
#   python3 variant_glb.py FRAGMENT.json VARIANT_NAME OUT.glb [--clips PREFIX] \
#       [--bind BIND.npz] [--bank CLIPBANK.pkl]
# Uses: engine-exact bind (bind_v14b/gimp...), bake_v4 math (conjugate convention,
# absolute root), real IBMs + joint-space TRS (interpolation-safe), real-time rates.
import os, sys, json, struct, pickle, zlib, hashlib
import numpy as np

_D = os.path.dirname(os.path.abspath(__file__))
if _D not in sys.path:
    sys.path.append(_D)  # append, never insert(0): flat module names must not shadow the stdlib
import watchmen_extract as we, export_female_anims as efa, rig_glb, extract_skeletons as es

# 2026-07-24 AXIS: the Kapow engine is ALREADY Y-up, so no axis conversion is
# needed for glTF.  This module used to carry a Z-up->Y-up rotation C (applied
# to POSITION) together with its exact inverse Ry (folded into the joint world
# matrices), i.e. Ry @ C4 == I.  The pair cancelled in the *animated* result but
# left the raw POSITION accessor -- and therefore the bind pose -- rotated 90
# degrees about X.  Both are gone; animated output is bit-identical, the bind
# pose is now upright.
#
# Evidence: on CHAR_Rorschach_v10_walk_cycle.glb the skinned frame-0 bbox is
# (0.519, 1.751, 0.662) -- 1.75 m tall along Y, feet down -- while POSITION
# alone measured (1.276, 0.426, 1.802), i.e. lying on its back.  The old Z-up
# reading came from decode_skeleton_model.py, which is superseded for an
# off-by-one node/name attribution bug (it also reported a 1.4 m character).
# Independent confirmation: GameEssentials.fragment gravity is (0, -14.82, 0)
# == World -Y (jiggle_d6.py).


# Clip timing: every clip is written at its header-exact rate (bake_v4.fps_for).  The engine
# plays a page at ctrl.speed x slot speedFactor x weight / duration (SetAllSlotBlends
# 0x5b5175, GetGameSpecificSpeedFactor 0x5ab837; docs/ENGINE_CONSTANTS.md "Rate"): no
# velocity term (read from code).  The walk / run multipliers 2.3 / 2.6 of 1.3.0 are
# retired; each clip's slot speed factors are in its extras (`speeds`).


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


#: per-vertex attributes (NORMAL / TANGENT / COLOR_0, winding, vertex-alpha
#: blend) in the character GLBs; False (or WATCHMEN_VERTEX_ATTRS=0) writes the
#: 1.3.0 attribute set.
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
    """Per-vertex attributes for the vertex buffer the legacy scan located at
    stream offset `vbo` -- taken from the header-driven decode
    (watchmen_extract.parse_model_header + model_stream_layout), so nothing is
    guessed: the buffer must be a format 5/6 render buffer whose computed
    offset, vertex count and stride equal the scan's.  None otherwise (a buffer
    the header does not account for).

    platform: the console of a big-endian model ("x360" / "ps3"; None = what
    watchmen_extract.console_platform gives).  It decides the colour byte order
    (watchmen_extract.console_color_order).  A console model whose colour order stays unknown
    (watchmen_extract.console_color_undecoded) still gets its normal and tangent
    frame: the result then has "color_not_decoded": True, a white `color` and
    has_color / has_alpha False for every buffer of the model, like the static
    model path."""
    if order not in ("<", ">") or ms is None:
        return None
    if order == ">" and not we.console_header_decode():
        return None
    # the stream is part of the key: the Xbox 360 and PS3 copies of a model share
    # the header and the stream length and differ in the colour bytes
    key = (zlib.crc32(mh), len(mh), len(ms), zlib.crc32(ms), order, platform, we.console_platform())
    bufs = _LAYOUT_CACHE.get(key)
    if bufs is None:
        bufs = {}
        try:
            M = we.parse_model_header(mh, order)
            if M is not None and we.model_stream_layout(M, ms, order) is not None:
                cargs = (ms, M["buffers"], platform, M.get("layout"))
                corder = we.console_color_order(*cargs) if order == ">" else None
                lost = order == ">" and bool(we.console_color_undecoded(*cargs))
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
    a = we.decode_vertex_attributes(ms, b, order, corder)
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
    else `game.naz`, in the current directory -- bake_v4.default_naz)."""
    if naz is None:
        import bake_v4

        naz = bake_v4.default_naz()
    NB = len(palette_names)
    uslot = {n: i for i, n in enumerate(palette_names)}
    # 2026-08-17: ported char_lib.load_parts' 2026-07-13 'BipNN '-prefix-
    # insensitive slot fallback (exact matches always win).  Thug/Heavies
    # models say 'RUpArmTwist' where the medium bind says 'Bip02 RUpArmTwist';
    # a silently dropped MID-LIST name shifts the rotate-by-one palette and
    # mis-skins everything after it.  char_lib had the fix; this path didn't.
    import re

    _canon = lambda n: re.sub(r"^Bip\d+\s+", "", n)
    ucanon = {}
    for i, n in enumerate(palette_names):
        c = _canon(n)
        if c not in uslot:
            ucanon.setdefault(c, i)

    def _slot(x):
        if x in uslot:
            return uslot[x]
        if x in ucanon:
            return ucanon[x]
        c = _canon(x)
        if c in uslot:
            return uslot[c]
        return ucanon.get(c)

    found = {}
    for st, hs in efa.grab_blocks(naz).items():
        if "h" not in hs:
            continue
        try:
            it = list(we.extract_block(hs["h"], hs.get("s")))
        except:
            continue
        for e, h, s in it:
            nm = e.name.rsplit("/", 1)[-1].replace(".model", "")
            if nm in mesh_names:
                # the block path names the console (derived_x360 / derived_ps3)
                found.setdefault(nm, []).append((h, s, we.console_platform_of(st)))
    parts = []
    for nm in mesh_names:
        if nm not in found:
            print("  ! mesh missing:", nm)
            continue
        cands = sorted(found[nm], key=lambda t: -(len(t[1]) if t[1] else 0))
        mh, ms, plat = cands[0]
        if ms is None:
            continue
        # per-part skin-index remap (each part mesh has its OWN bone list).
        # 2026-08-17: byte order threaded through like char_lib.load_parts --
        # console (X360/PS3) models are big-endian; compare descriptor COUNTS
        # (a BE model can throw a stray LE false positive).  This path was
        # hardcoded LE.
        # 2026-10-05: the header states the order (char_lib.model_order); the
        # count rule tied on single-submesh console models and lost them.
        import char_lib as _cl

        order = _cl.model_order(mh, ms, nm)
        be = order == ">"
        plist = [x for _, x in es._ordered_names(mh, order)]
        pf = [x for x in plist if _slot(x) is not None]
        ppal = [pf[(k - 1) % len(pf)] for k in range(len(pf))]  # engine rotate-by-one
        remap = np.array([_slot(n) for n in ppal], dtype=np.int64)
        descs = we.find_descriptors(mh, order)
        mats = we.extract_materials(mh)
        # 2026-08-17: engine-exact submesh->material pairing (char_lib.py had
        # the 2026-07-08g fix); positional mats[si] stays as the fallback.
        smat = we.submesh_materials(mh, order)
        off = 0
        for si, (nv, stride, ib) in enumerate(descs):
            hi = len(ms) - nv * stride - ib
            c = off
            vbo = None
            while c <= min(off + 65536, hi):
                # require a CLEAN index buffer too: a false-positive VB sits
                # ~4 bytes before the real one, passes _vb_ok, but has a ~50%
                # repeated-index IB (char_lib 2026-07-15d).
                if (
                    we._sane(struct.unpack_from(order + "f", ms, c)[0])
                    and we._vb_ok(ms, c, nv, stride, ib, order)
                    and we._ib_ok(ms, c, nv, stride, ib, order)
                ):
                    vbo = c
                    break
                c += 1
            if vbo is None:
                vbo = _cl.flat_buffer(ms, off, nv, stride, ib, order)
            if vbo is None:
                _cl.note_dropped(nm, si, nv, stride, ib, order, _cl.NO_BUFFER)
                continue
            v, _, uv = we._decode_sub(ms, vbo, nv, stride, be)
            skidx, skw = rig_glb.decode_skin(ms, vbo, nv, stride, order)
            ibo = vbo + nv * stride
            T = []
            for t in range(ib // 6):
                x, y, z = struct.unpack_from(order + "3H", ms, ibo + t * 6)
                if x < nv and y < nv and z < nv and len({x, y, z}) == 3:
                    T.append((x, y, z))
            off = ibo + ib
            if not v or not T:
                _cl.note_dropped(nm, si, nv, stride, ib, order, _cl.NO_TRIANGLES)
                continue
            SI = remap[np.clip(np.asarray(skidx, int), 0, len(remap) - 1)]
            SI = np.clip(SI, 0, NB - 1)
            mat = (
                mats[smat[si][1]]
                if si < len(smat) and smat[si][1] < len(mats)
                else (mats[si] if si < len(mats) else "%s_sub%d" % (nm, si))
            )
            parts.append(
                with_attrs(
                    (
                        np.array(v, float),
                        SI.astype(np.uint16),
                        np.asarray(skw, np.float32),
                        np.array(T),
                        np.array(uv if uv else [(0.0, 0.0)] * len(v), np.float32),
                        mat,
                    ),
                    buffer_vertex_attrs(mh, ms, order, vbo, nv, stride, plat),
                )
            )
            print("  loaded %-24s sub%d verts=%d tris=%d mat=%s" % (nm, si, len(v), len(T), mat))
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
    meta["face"]); "legacy" = the rule of 1.3.0: a pose picked from the clip NAME
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
    and model on skin 0: the shown outfit's nodes are children of the root, the
    others hang under "alternatives".  Nodes of the same model share their vertex
    data (identical data is written once and the accessor shared), only the
    materials differ.  asset_extras: merged into asset.extras.watchmen.  A piece with restored
    eyelash UVs (watchmen_extract.LASH_RESTORE) adds reconstruction.eyelash_uvs there.
    ragdoll: ragdoll_rig.glb_helpers(...) -- the character's ragdoll rig as helper
    nodes under a node "ragdoll" that is in no scene (hidden like "alternatives"):
    `RB.<bone>.<i>` proxy meshes skinned rigidly to the bone's joint, `RJ.<child
    bone>` empties at the joint frames; parameters in the nodes' extras.  Appended
    after everything else, so the rest of the file is the same with or without it."""
    import face_rule as _fr

    _engine = _fr.rule(face_rule) == "engine"
    _idle = _fr.idle_enabled(face_idle)
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
    import anim_meta as _am

    # the clip extras copy GLB-frame numbers out of `meta`: it has to be in the
    # frame this file is written in (a table without the marker is mirrored)
    meta = _am.to_frame(meta)
    bt = np.load(bindnpz, allow_pickle=True)
    Rb = bt["Rb"]
    tb = bt["tb"]
    NB = len(Rb)
    # real bone names + parents (palette order) -- written to `extras` so an
    # importer needs no per-skeleton table to rebuild the hierarchy.
    _bnames = [str(x) for x in bt["names"]] if "names" in bt else None
    _bpar = [int(x) for x in bt["par"]] if "par" in bt else None
    _skel = (
        _am.skeleton_extras(_bnames, _bpar)
        if _bnames and _bpar and len(_bnames) == NB and len(_bpar) == NB
        else None
    )
    B4 = np.tile(np.eye(4), (NB, 1, 1))
    B4[:, :3, :3] = Rb
    B4[:, :3, 3] = tb
    IBM = np.array([np.linalg.inv(B4[k]) for k in range(NB)])
    j = {
        "asset": {
            "version": "2.0",
            "generator": "watchmen_extract variant_glb",
            "extras": {"watchmen": {"format": _am.FORMAT, "conventions": _am.conventions()}},
        },
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "skins": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [],
        "materials": [],
        "animations": [],
        "images": [],
        "textures": [],
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}],
    }
    BIN = bytearray()

    # outfit nodes of the same model: identical data is written once and the
    # ACCESSOR is shared (a buffer view shared by two accessors would need a
    # byteStride; a shared accessor needs nothing)
    _share = {"on": False, "view": {}, "acc": {}}

    def _used_joints(SI, SW):
        """JOINTS_0 with the index of every zero-weight influence set to 0 (glTF
        2.0, 3.7.3.3: unused joint slots should be 0; the weight decides alone,
        so the skinning is unchanged)."""
        SI = np.array(SI, copy=True)
        SI[np.asarray(SW) == 0] = 0
        return np.ascontiguousarray(SI)

    def av(x, target=None):
        if _share["on"]:
            _k = (hashlib.sha1(bytes(x)).digest(), target)
            if _k in _share["view"]:
                return _share["view"][_k]
        while len(BIN) % 4:
            BIN.append(0)
        ofs = len(BIN)
        BIN.extend(x)
        j["bufferViews"].append({"buffer": 0, "byteOffset": ofs, "byteLength": len(x)})
        if target is not None:
            j["bufferViews"][-1]["target"] = target
        if _share["on"]:
            _share["view"][_k] = len(j["bufferViews"]) - 1
        return len(j["bufferViews"]) - 1

    def ac(bv, ct, c, t, mn=None, mx=None):
        if _share["on"] and (bv, ct, c, t) in _share["acc"]:
            return _share["acc"][(bv, ct, c, t)]
        A = {"bufferView": bv, "componentType": ct, "count": c, "type": t}
        if mn is not None:
            A["min"] = mn
            A["max"] = mx
        j["accessors"].append(A)
        if _share["on"]:
            _share["acc"][(bv, ct, c, t)] = len(j["accessors"]) - 1
        return len(j["accessors"]) - 1

    _texdone = {}
    _va = vertex_attrs_enabled()
    import frame as _frame

    # everything below is built from engine numbers (binds, bakes, meshes);
    # _frame.finish_gltf reflects the finished document for the "true" frame
    _true_frame = _frame.is_true()
    _blendmat = {}
    _sheetalpha = {}  # id(material) -> (sheet, header alpha, pixel alpha): engine materials
    _vamat = {}

    def _vprep(part, Vg, T):
        """Per-vertex attributes of one part -> (index array to write, pending
        attribute arrays or None, vertex-alpha blend flag).  NORMAL is the stored
        normal; TANGENT the stored tangent with w for the green-inverted normal
        texture (we.gltf_tangents), written when the part's material has a normal
        map; COLOR_0 only when the buffer has colours.
        A part that gets NORMAL has its winding turned to glTF's (the engine's
        triangles wind clockwise against their normals)."""
        T = np.asarray(T)
        at = getattr(part, "attrs", None) if _va else None
        Np = None
        if at is not None and len(at["normal"]) == len(Vg):
            Np = rig_glb.unit_normals(at["normal"])
        if Np is None:
            if _true_frame and T.size:
                # no normals: the file order is the front face in the true frame,
                # so cancel the reversal frame.finish_gltf applies
                T = T.reshape(-1, 3)[:, [0, 2, 1]]
            return T, None, False
        pend = {"NORMAL": (Np, "VEC3")}
        tg = np.asarray(at["tangent"], np.float32)
        lay = (textures or {}).get(part[5])
        has_nmap = isinstance(lay, dict) and bool(lay.get("normal"))  # else TANGENT is unused
        if has_nmap and np.isfinite(tg).all() and (np.linalg.norm(tg, axis=1) > 1e-6).all():
            Tp = rig_glb.well_formed_tangents(
                we.gltf_tangents(
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

    def _vwrite(pend, attributes):
        for name, (arr, typ) in (pend or {}).items():
            attributes[name] = ac(
                av(np.ascontiguousarray(arr).tobytes(), 34962), 5126, len(arr), typ
            )
        return attributes

    def _blend(mi, blend):
        """material index `mi`, or its alphaMode BLEND twin for a part whose
        vertex alpha varies (it multiplies the texture alpha in the engine).
        A material written from its sheet (materials.py, engine mode) gets no
        twin unless the sheet blends: the engine picks the render list from
        renderType and opacity alone (0x5739d0), and the opaque lists are drawn
        with blending off, so vertex alpha only reaches the alpha test there.
        It is recorded as extras.watchmen.vertex_alpha instead.  The legacy mode
        and a material without a known sheet keep the twin."""
        if not blend or j["materials"][mi].get("alphaMode") == "BLEND":
            return mi
        m = j["materials"][mi]
        if id(m) in _sheetalpha:
            import materials as _mt

            if mi not in _vamat:
                sheet, has_a, pix_a = _sheetalpha[id(m)]
                amode, cutoff, _afac = _mt.alpha(sheet, has_a, True, pix_a)
                if amode == m.get("alphaMode") and cutoff == m.get("alphaCutoff"):
                    m.setdefault("extras", {}).setdefault("watchmen", {})["vertex_alpha"] = True
                    _vamat[mi] = mi
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
                        m2.setdefault("extras", {}).setdefault("watchmen", {})[
                            "vertex_alpha"
                        ] = True
                    j["materials"].append(m2)
                    _vamat[mi] = len(j["materials"]) - 1
            return _vamat[mi]
        if mi not in _blendmat:
            m2 = json.loads(json.dumps(j["materials"][mi]))
            m2["alphaMode"] = "BLEND"
            m2.pop("alphaCutoff", None)
            j["materials"].append(m2)
            _blendmat[mi] = len(j["materials"]) - 1
        return _blendmat[mi]

    def _sheet_material(mat, layers):
        """Engine values from the texture's sheet.json (char_lib._find_layers):
        the alpha-test reference, the normal-map power and the subtractive blend."""
        if layers.get("blend_info"):
            # the texture is ink / light with its coverage in alpha (char_lib._blend_layer)
            bct = mat.get("pbrMetallicRoughness", {}).get("baseColorTexture", {})
            we.blend_material(
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
            _engine_material(mat, layers)
        sheet = layers.get("sheet") if _va else None
        if not sheet:
            return
        thr = sheet.get("alphaThreshold")
        if mat.get("alphaMode") == "MASK" and thr:
            mat["alphaCutoff"] = round(min(int(thr), 255) / 255.0, 6)
        power = sheet.get("normalMapPower")
        if "normalTexture" in mat and power is not None and abs(float(power) - 1.0) > 1e-6:
            mat["normalTexture"]["scale"] = round(float(power), 6)

    def _engine_material(mat, layers):
        """materials.py: roughness / specular / emission / alpha mode / culling from
        the sheet (layers["materials"] == "engine", set by char_lib._find_layers)."""
        import materials as _mt

        sheet = layers.get("sheet") or {}

        def _add(data, label):
            j["images"].append(
                {"bufferView": av(data), "mimeType": "image/png", "name": mat["name"] + "_" + label}
            )
            j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
            return len(j["textures"]) - 1

        P = _mt.engine_material(
            sheet,
            layers.get("diffuse"),
            layers.get("spec"),
            layers.get("specsize"),
            layers.get("glow"),
        )
        _mt.apply(j, mat, P, _add)
        if "twoSided" in sheet:
            mat["doubleSided"] = bool(sheet["twoSided"])
        if not layers.get("blend_info"):
            pix_a = bool(layers.get("texAlpha") or layers.get("alphaMask"))
            # the engine's alpha test follows the texture header's alpha flag
            # (0x429e77 -> 0x571d5d): layers["texAlphaFlag"] when the extract has
            # it (sheet.json "textureHasAlpha"), else the pixels
            has_a = layers.get("texAlphaFlag")
            has_a = pix_a if has_a is None else bool(has_a)
            _sheetalpha[id(mat)] = (sheet, has_a, pix_a)
            amode, cutoff, afac = _mt.alpha(sheet, has_a, False, pix_a)
            mat.pop("alphaMode", None)
            mat.pop("alphaCutoff", None)
            if amode:
                mat["alphaMode"] = amode
            if cutoff is not None:
                mat["alphaCutoff"] = cutoff
            if afac is not None:
                mat["pbrMetallicRoughness"]["baseColorFactor"] = [1.0, 1.0, 1.0, afac]

    def _node_trs(L):
        """4x4 -> glTF node TRS dict (rotation is XYZW, same as glTF)."""
        q = batch_m2q(np.ascontiguousarray(L[:3, :3])[None])[0]
        return {"rotation": [float(x) for x in q], "translation": [float(x) for x in L[:3, 3]]}

    # Joint nodes carry the BIND pose, not identity.  They are flat children of
    # an identity `root`, so node-local == node-global and the bind world matrix
    # B4[k] goes straight in.  Previously these were identity while the IBMs
    # were real, so any viewer showing the scene before an animation is picked
    # (Blender's rest pose, default glTF viewer state, thumbnailers) rendered
    # the mesh in bind-LOCAL space -- measured 0.72 m mean vertex displacement
    # and a mesh collapsed to ~1/5 of its animated size.
    bnode = [len(j["nodes"]) + k for k in range(NB)]
    for k in range(NB):
        nd = {"name": "b%d" % k}
        nd.update(_node_trs(B4[k]))
        if _skel:
            nd["extras"] = {"bone": _bnames[k], "parent": _bpar[k]}
        j["nodes"].append(nd)
    ibmacc = ac(
        av(np.array([m.T.reshape(16) for m in IBM], np.float32).tobytes()), 5126, NB, "MAT4"
    )
    prims = []
    for _part in parts:
        V, SI, SW, T, UV, nm = _part
        Vg = np.ascontiguousarray(V, np.float32)
        T, _pend, _vblend = _vprep(_part, Vg, T)
        ap = ac(
            av(Vg.tobytes(), 34962), 5126, len(Vg), "VEC3", Vg.min(0).tolist(), Vg.max(0).tolist()
        )
        aj = ac(av(_used_joints(SI, SW).tobytes(), 34962), 5123, len(Vg), "VEC4")
        aw = ac(av(np.ascontiguousarray(SW).tobytes(), 34962), 5126, len(Vg), "VEC4")
        auv = ac(av(np.ascontiguousarray(UV).tobytes(), 34962), 5126, len(Vg), "VEC2")
        ai = ac(
            av(np.ascontiguousarray(T.astype(np.uint32)).tobytes(), 34963), 5125, T.size, "SCALAR"
        )
        png = (textures or {}).get(nm)
        if png is not None and nm in _texdone:
            mi = _texdone[nm]
        elif png is not None:
            layers = png if isinstance(png, dict) else {"diffuse": png}

            def _tex(data, label):
                bvi = av(data)
                j["images"].append(
                    {"bufferView": bvi, "mimeType": "image/png", "name": nm + "_" + label}
                )
                j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
                return len(j["textures"]) - 1

            mat = {
                "name": nm,
                "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 0.85},
                "doubleSided": True,
            }
            if "diffuse" in layers:
                mat["pbrMetallicRoughness"]["baseColorTexture"] = {
                    "index": _tex(layers["diffuse"], "diffuse")
                }
            if "mr" in layers:
                mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {
                    "index": _tex(layers["mr"], "mr")
                }
                mat["pbrMetallicRoughness"]["roughnessFactor"] = 1.0
            if "normal" in layers:
                mat["normalTexture"] = {"index": _tex(layers["normal"], "normal")}
            if layers.get("alphaMask"):
                mat["alphaMode"] = "MASK"
                mat["alphaCutoff"] = 0.5
            _sheet_material(mat, layers)
            if "spec" in layers and layers.get("materials") != "engine":
                mat.setdefault("extensions", {})["KHR_materials_specular"] = {
                    "specularColorTexture": {"index": _tex(layers["spec"], "spec")}
                }
                j.setdefault("extensionsUsed", [])
                if "KHR_materials_specular" not in j["extensionsUsed"]:
                    j["extensionsUsed"].append("KHR_materials_specular")
            j["materials"].append(mat)
            mi = _texdone[nm] = len(j["materials"]) - 1
        else:
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
            mi = len(j["materials"]) - 1
        prims.append(
            {
                "attributes": _vwrite(
                    _pend, {"POSITION": ap, "JOINTS_0": aj, "WEIGHTS_0": aw, "TEXCOORD_0": auv}
                ),
                "indices": ai,
                "material": _blend(mi, _vblend),
                "mode": 4,
            }
        )
    j["meshes"].append({"name": "variant", "primitives": prims})
    mnode = len(j["nodes"])
    j["nodes"].append({"name": "mesh", "mesh": 0, "skin": 0})
    j["skins"].append({"joints": bnode, "inverseBindMatrices": ibmacc})
    if _skel:
        j["skins"][0]["extras"] = {"watchmen": _skel}

    def _anim(animname, sm, chn, frames, fps, finfo=None):
        a = {"name": animname, "samplers": sm, "channels": chn}
        ex = None
        if meta is not None:
            ex = _am.clip_extras(meta, animname, fps=fps, frames=frames)
        if finfo is not None:  # what the face channels of this clip show
            ex = dict(ex or {}, face=finfo)
        if ex is not None:
            a["extras"] = {"watchmen": ex}
        return a

    def _mkmat(nm):
        """material index for nm using `textures` (same rules as body prims)."""
        png = (textures or {}).get(nm)
        if png is not None and nm in _texdone:
            return _texdone[nm]
        if png is not None:
            layers = png if isinstance(png, dict) else {"diffuse": png}

            def _tex(data, label):
                bvi = av(data)
                j["images"].append(
                    {"bufferView": bvi, "mimeType": "image/png", "name": nm + "_" + label}
                )
                j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
                return len(j["textures"]) - 1

            mat = {
                "name": nm,
                "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 0.85},
                "doubleSided": True,
            }
            if "diffuse" in layers:
                mat["pbrMetallicRoughness"]["baseColorTexture"] = {
                    "index": _tex(layers["diffuse"], "diffuse")
                }
            if "mr" in layers:
                mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {
                    "index": _tex(layers["mr"], "mr")
                }
                mat["pbrMetallicRoughness"]["roughnessFactor"] = 1.0
            if "normal" in layers:
                mat["normalTexture"] = {"index": _tex(layers["normal"], "normal")}
            if layers.get("alphaMask"):
                mat["alphaMode"] = "MASK"
                mat["alphaCutoff"] = 0.5
            _sheet_material(mat, layers)
            if "spec" in layers and layers.get("materials") != "engine":
                mat.setdefault("extensions", {})["KHR_materials_specular"] = {
                    "specularColorTexture": {"index": _tex(layers["spec"], "spec")}
                }
                j.setdefault("extensionsUsed", [])
                if "KHR_materials_specular" not in j["extensionsUsed"]:
                    j["extensionsUsed"].append("KHR_materials_specular")
            j["materials"].append(mat)
            _texdone[nm] = len(j["materials"]) - 1
            return _texdone[nm]
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

    attnodes = []
    _hidden = set()  # node indices that go to the "alternatives" scene only
    _wshown = set(((parts_record or {}).get("weapons") or {}).get("shown") or [])
    _extra = [
        (a, p, parts_record is not None and a not in _wshown, False) for a, p in attachments or []
    ]
    _extra += [(a, p, True, False) for a, p in alt_parts or []]
    _extra += [(a, p, not sh, True) for a, p, sh in outfit_parts or []]
    for aname, aparts, _hide, _shared in _extra:
        _share["on"] = _shared
        # each attachment = its OWN mesh node sharing skin 0 (verts already in
        # body bind space, weighted to the attach bone slot) -> imports as a
        # separate object, individually hideable.
        aprims = []
        for _part in aparts:
            V, SI, SW, T, UV, nm = _part
            Vg = np.ascontiguousarray(V, np.float32)
            T, _pend, _vblend = _vprep(_part, Vg, T)
            ap = ac(
                av(Vg.tobytes(), 34962),
                5126,
                len(Vg),
                "VEC3",
                Vg.min(0).tolist(),
                Vg.max(0).tolist(),
            )
            aj = ac(av(_used_joints(SI, SW).tobytes(), 34962), 5123, len(Vg), "VEC4")
            aw = ac(av(np.ascontiguousarray(SW).tobytes(), 34962), 5126, len(Vg), "VEC4")
            auv = ac(av(np.ascontiguousarray(UV).tobytes(), 34962), 5126, len(Vg), "VEC2")
            ai_ = ac(
                av(np.ascontiguousarray(T.astype(np.uint32)).tobytes(), 34963),
                5125,
                T.size,
                "SCALAR",
            )
            aprims.append(
                {
                    "attributes": _vwrite(
                        _pend,
                        {
                            "POSITION": ap,
                            "JOINTS_0": aj,
                            "WEIGHTS_0": aw,
                            "TEXCOORD_0": auv,
                        },
                    ),
                    "indices": ai_,
                    "material": _blend(_mkmat(nm), _vblend),
                    "mode": 4,
                }
            )
        if not aprims:
            continue
        mi_ = len(j["meshes"])
        j["meshes"].append({"name": aname, "primitives": aprims})
        if _hide:
            _hidden.add(len(j["nodes"]))
        attnodes.append(len(j["nodes"]))
        j["nodes"].append({"name": aname, "mesh": mi_, "skin": 0})
    _share["on"] = False
    facenodes = []
    if face is not None:
        # SECOND SKIN: face rig parented under the body's Head joint -- rides
        # every body animation via hierarchy; face poses = local channels on
        # the face joints only.  face = dict(bind, parts, anims, attach_idx,
        # M (3,3), t (3)) with M,t mapping face-model space -> body bind space.
        fb = np.load(face["bind"], allow_pickle=True)
        fRb, ftb = fb["Rb"], fb["tb"]
        NF = len(fRb)
        B4f = np.tile(np.eye(4), (NF, 1, 1))
        B4f[:, :3, :3] = fRb
        B4f[:, :3, 3] = ftb
        M4 = np.eye(4)
        M4[:3, :3] = face["M"]
        M4[:3, 3] = face["t"]
        ai = face["attach_idx"]

        def _trs(L):
            q = batch_m2q(L[:3, :3][None])[0]
            return {"rotation": [float(x) for x in q], "translation": [float(x) for x in L[:3, 3]]}

        frn = len(j["nodes"])
        j["nodes"].append({"name": "face_root"})
        anchor = len(j["nodes"])
        nd = {"name": "f_anchor"}
        nd.update(_trs(M4))
        j["nodes"].append(nd)
        proxynodes = []
        _palign = face.get("proxy_align") or None  # per-proxy 4x4 (giraffe fix)
        for pi, bs in enumerate(face.get("proxy_slots", [])):
            _Mk = _palign[pi] if _palign is not None else M4
            Lp = _Mk
            nd = {"name": "face_proxy_b%d_%d" % (bs, pi)}
            nd.update(_trs(Lp))
            pn = len(j["nodes"])
            j["nodes"].append(nd)
            proxynodes.append(pn)
        for k in range(NF):
            L = B4f[k]  # LOCAL under f_anchor
            nd = {"name": "f_%s" % str(fb["names"][k])}
            nd.update(_trs(L))
            facenodes.append(len(j["nodes"]))
            j["nodes"].append(nd)
        j["nodes"][anchor]["children"] = facenodes[:]
        j["nodes"][frn]["children"] = [anchor] + proxynodes
        _fj_ibms = (
            [np.linalg.inv(B4f[k]) for k in range(NF)]
            + [np.eye(4) for _ in proxynodes]
            + [np.linalg.inv(M4)]
        )
        fibm = ac(
            av(np.array([m.T.reshape(16) for m in _fj_ibms], np.float32).tobytes()),
            5126,
            len(_fj_ibms),
            "MAT4",
        )
        fprims = []
        for _part in face["parts"]:
            V, SI, SW, T, UV, nm = _part
            Vg = np.ascontiguousarray(V, np.float32)
            T, _pend, _vblend = _vprep(_part, Vg, T)
            ap = ac(
                av(Vg.tobytes(), 34962),
                5126,
                len(Vg),
                "VEC3",
                Vg.min(0).tolist(),
                Vg.max(0).tolist(),
            )
            aj = ac(av(_used_joints(SI, SW).tobytes(), 34962), 5123, len(Vg), "VEC4")
            aw = ac(av(np.ascontiguousarray(SW).tobytes(), 34962), 5126, len(Vg), "VEC4")
            auv = ac(av(np.ascontiguousarray(UV).tobytes(), 34962), 5126, len(Vg), "VEC2")
            ai_ = ac(
                av(np.ascontiguousarray(T.astype(np.uint32)).tobytes(), 34963),
                5125,
                T.size,
                "SCALAR",
            )
            png = (textures or {}).get(nm)
            if png is not None and nm in _texdone:
                mi = _texdone[nm]
            elif png is not None:
                layers = png if isinstance(png, dict) else {"diffuse": png}

                def _tex2(data, label):
                    bvi = av(data)
                    j["images"].append(
                        {"bufferView": bvi, "mimeType": "image/png", "name": nm + "_" + label}
                    )
                    j["textures"].append({"source": len(j["images"]) - 1, "sampler": 0})
                    return len(j["textures"]) - 1

                mat = {
                    "name": nm,
                    "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 0.85},
                    "doubleSided": True,
                }
                if "diffuse" in layers:
                    mat["pbrMetallicRoughness"]["baseColorTexture"] = {
                        "index": _tex2(layers["diffuse"], "diffuse")
                    }
                if "mr" in layers:
                    mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {
                        "index": _tex2(layers["mr"], "mr")
                    }
                    mat["pbrMetallicRoughness"]["roughnessFactor"] = 1.0
                if "normal" in layers:
                    mat["normalTexture"] = {"index": _tex2(layers["normal"], "normal")}
                if layers.get("alphaMask"):
                    mat["alphaMode"] = "MASK"
                    mat["alphaCutoff"] = 0.5
                _sheet_material(mat, layers)
                # 2026-08-17: spec layer was silently dropped on face-first
                # materials -- mirror the body-prim block above.
                if "spec" in layers and layers.get("materials") != "engine":
                    mat.setdefault("extensions", {})["KHR_materials_specular"] = {
                        "specularColorTexture": {"index": _tex2(layers["spec"], "spec")}
                    }
                    j.setdefault("extensionsUsed", [])
                    if "KHR_materials_specular" not in j["extensionsUsed"]:
                        j["extensionsUsed"].append("KHR_materials_specular")
                j["materials"].append(mat)
                mi = _texdone[nm] = len(j["materials"]) - 1
            else:
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
                mi = len(j["materials"]) - 1
            fprims.append(
                {
                    "attributes": _vwrite(
                        _pend,
                        {
                            "POSITION": ap,
                            "JOINTS_0": aj,
                            "WEIGHTS_0": aw,
                            "TEXCOORD_0": auv,
                        },
                    ),
                    "indices": ai_,
                    "material": _blend(mi, _vblend),
                    "mode": 4,
                }
            )
        fmi = len(j["meshes"])
        j["meshes"].append({"name": "face", "primitives": fprims})
        fmnode = len(j["nodes"])
        j["nodes"].append({"name": "face_mesh", "mesh": fmi, "skin": 1})
        j["skins"].append(
            {"joints": facenodes + proxynodes + [anchor], "inverseBindMatrices": fibm}
        )
    root = len(j["nodes"])
    rootkids = bnode + [mnode] + [a for a in attnodes if a not in _hidden]
    j["nodes"].append({"name": "root", "children": rootkids})
    j["skins"][0]["skeleton"] = root
    j["scenes"][0]["nodes"] = [root]
    if face is not None:
        j["scenes"][0]["nodes"].append(frn)
        j["nodes"][frn].setdefault("children", []).append(fmnode)
        j["skins"][1]["skeleton"] = frn
        if _engine:
            _fm = (meta or {}).get("face") or {}
            _sx = {
                "head_model": face.get("head"),
                "pose_family": face.get("family"),
                "face_classes": sorted(
                    n
                    for n, r in (_fm.get("classes") or {}).items()
                    if r.get("pose_family") == face.get("family")
                ),
                "anchor_node": "face_root",
                "rule": "engine",
                "track_choice": _fr.TRACK_CHOICE,
                "idle_cycle_baked": bool(_idle),
            }
            if face.get("game_head"):
                _sx["game_head"] = face["game_head"]
            j["skins"][1]["extras"] = {"watchmen": {"face": _sx}}
    _facemask = None
    if face is not None:
        _fb0 = np.load(face["bind"], allow_pickle=True)
        _fn = [str(x) for x in _fb0["names"]]
        _fp = _fb0["par"]

        def _below_head(k):
            p = _fp[k]
            while p >= 0:
                if _fn[p] == "Head":
                    return True
                p = _fp[p]
            return False

        _facemask = [k for k in range(len(_fn)) if _below_head(k)]
        _fhead = _fn.index("Head")
    _faceride = None
    if face is not None and face.get("anims"):
        _fb = np.load(face["bind"], allow_pickle=True)
        _NF = len(_fb["Rb"])
        _B4f = np.tile(np.eye(4), (_NF, 1, 1))
        _B4f[:, :3, :3] = _fb["Rb"]
        _B4f[:, :3, 3] = _fb["tb"]
        _M4 = np.eye(4)
        _M4[:3, :3] = face["M"]
        _M4[:3, 3] = face["t"]
        _M4Ci = _M4

        def _locals_for(_A):
            """pose palettes frame (NF,3,4) -> (quat,(NF,3)) LOCALS under anchor."""
            _A4 = np.concatenate(
                [
                    _A.astype(np.float64),
                    np.tile(np.array([0, 0, 0, 1.0]).reshape(1, 1, 4), (_NF, 1, 1)),
                ],
                axis=1,
            )
            _W = np.einsum("kab,kbc->kac", _A4, _B4f)
            _fx = _B4f[_fhead] @ np.linalg.inv(_W[_fhead])
            _L = np.einsum("ab,kbc->kac", _fx, _W)
            return batch_m2q(_L[:, :3, :3]), _L[:, :3, 3]

        _cand = [a for a in face["anims"] if "MouthClosed_EyesOpen" in a[0]] or list(face["anims"])
        _fneut = _locals_for(_cand[0][1][0])
        # per-category pose locals (AUTO-PAIRING: ATT face on attack clips etc.)
        # 2026-08-17: guard ONLY the import -- the old blanket except also
        # swallowed _locals_for errors and silently disabled ALL auto-pairing
        # (and blink categorization) on the first bad pose.
        _fpose = {}
        try:
            import face_synth as _fs
        except Exception:
            _fs = None
        if _fs is not None:
            for _pn, _pp in (face.get("auto_poses") or {}).items():
                try:
                    _fpose[_pn] = _locals_for(_pp)
                except Exception as _pe:
                    print("  ! auto-pose %s failed: %s" % (_pn, _pe))
        # blink data: EyeLid bone locals for neutral vs eyes-closed
        _fblink = None
        _fn2 = [str(x) for x in _fb["names"]]
        if face.get("blink_closed") is not None and "EyeLid" in _fn2:
            _lidk = [
                k for k in range(_NF) if "eyelid" in _fn2[k].lower() or _fn2[k] in ("Leye", "Reye")
            ]
            _fblink = (_lidk, _locals_for(face["blink_closed"]))
        _faceride = (
            face["attach_idx"],
            face.get("proxy_slots", []),
            face.get("proxy_align") or None,
            _fneut,
            _fpose,
            _fblink,
            _fs,
        )

    def _face_track_channels(animname, F, fps, sm, chn):
        """Engine rule: face-bone channels of one body clip from the face track
        of the state(s) that play it.  Returns the `face` extras record."""
        _fpose_all = _faceride[4]
        dur = max((F - 1) / fps, 1e-3)
        fam = face.get("family")
        fmeta = (meta or {}).get("face") or {}
        chosen = _fr.choose_track(meta, animname, fam) if fmeta else None
        info = {"rule": "engine", "pose_family": fam}
        sched = []
        if chosen is not None:
            fclass = fmeta["classes"][chosen["source"]["class_face"]]
            sched, skipped = _fr.pose_schedule(
                chosen, fclass, animname, lambda pp: None if pp is None else pp * dur, _idle, dur
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
                idle_cycle_baked=bool(_idle),
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
        ta3 = ac(av(ktf.tobytes()), 5126, len(ktf), "SCALAR", [0.0], [float(ktf[-1])])
        QT = [_fs.blend_locals(_fpose_all, _fr.pose_weights(sched, t)) for t in kt]
        Qk = np.stack([q for q, _t in QT])  # (K, NF, 4)
        Tk = np.stack([t for _q, t in QT])
        for f in range(1, len(kt)):
            flip = np.einsum("kc,kc->k", Qk[f], Qk[f - 1]) < 0
            Qk[f, flip] *= -1
        for k in _facemask:
            vo = ac(
                av(np.ascontiguousarray(Qk[:, k].astype(np.float32)).tobytes()),
                5126,
                len(kt),
                "VEC4",
            )
            to = ac(
                av(np.ascontiguousarray(Tk[:, k].astype(np.float32)).tobytes()),
                5126,
                len(kt),
                "VEC3",
            )
            sm.append({"input": ta3, "output": vo, "interpolation": "LINEAR"})
            chn.append(
                {"sampler": len(sm) - 1, "target": {"node": facenodes[k], "path": "rotation"}}
            )
            sm.append({"input": ta3, "output": to, "interpolation": "LINEAR"})
            chn.append(
                {"sampler": len(sm) - 1, "target": {"node": facenodes[k], "path": "translation"}}
            )
        return info

    for entry in manifest:
        # (name, pal, fps) or (name, pal, fps, bone_indices) -- the 4-tuple
        # form writes channels ONLY for the listed bones (partial overlay
        # anims, e.g. GRIP hand poses layered over body clips in NLA).
        if len(entry) == 4:
            animname, A, fps, bmask = entry
        else:
            animname, A, fps = entry
            bmask = None
        _finfo = None
        F = len(A)
        times = (np.arange(F) / fps).astype(np.float32)
        ta = ac(av(times.tobytes()), 5126, F, "SCALAR", [0.0], [float(times[-1])])
        sm = []
        chn = []
        A4 = np.concatenate(
            [
                A.astype(np.float64),
                np.tile(np.array([0, 0, 0, 1.0]).reshape(1, 1, 1, 4), (F, NB, 1, 1)),
            ],
            axis=2,
        )  # (F,NB,4,4)
        W = np.einsum("fkab,kbc->fkac", A4, B4)
        Q = batch_m2q(W[:, :, :3, :3].reshape(-1, 3, 3)).reshape(F, NB, 4)
        # sign continuity along time per bone
        for f in range(1, F):
            flip = np.einsum("kc,kc->k", Q[f], Q[f - 1]) < 0
            Q[f, flip] *= -1
        Tt = W[:, :, :3, 3]
        for k in (range(NB) if bmask is None else bmask):
            vo = ac(av(np.ascontiguousarray(Q[:, k].astype(np.float32)).tobytes()), 5126, F, "VEC4")
            to = ac(
                av(np.ascontiguousarray(Tt[:, k].astype(np.float32)).tobytes()), 5126, F, "VEC3"
            )
            sm.append({"input": ta, "output": vo, "interpolation": "LINEAR"})
            chn.append({"sampler": len(sm) - 1, "target": {"node": bnode[k], "path": "rotation"}})
            sm.append({"input": ta, "output": to, "interpolation": "LINEAR"})
            chn.append(
                {"sampler": len(sm) - 1, "target": {"node": bnode[k], "path": "translation"}}
            )
        if _faceride is not None and bmask is None:
            # face armature rides via ONE anchor joint (face bones are its
            # children with LOCAL channels -> expressions follow the head, and
            # a FACE action layered/posed on top keeps riding).
            _ai, _pslots, _palign, _fneut, _fpose, _fblink, _fs = _faceride
            FH = A4[:, _ai]  # (F,4,4)
            La = np.einsum("fab,bc->fac", FH, _M4Ci)
            Qf = batch_m2q(La[:, :3, :3])
            for f in range(1, F):
                if (Qf[f] * Qf[f - 1]).sum() < 0:
                    Qf[f] *= -1
            vo = ac(av(np.ascontiguousarray(Qf.astype(np.float32)).tobytes()), 5126, F, "VEC4")
            to = ac(
                av(np.ascontiguousarray(La[:, :3, 3].astype(np.float32)).tobytes()), 5126, F, "VEC3"
            )
            sm.append({"input": ta, "output": vo, "interpolation": "LINEAR"})
            chn.append({"sampler": len(sm) - 1, "target": {"node": anchor, "path": "rotation"}})
            sm.append({"input": ta, "output": to, "interpolation": "LINEAR"})
            chn.append({"sampler": len(sm) - 1, "target": {"node": anchor, "path": "translation"}})
            # ENGINE RULE: the face track of the state(s) that play this clip
            _eng = _engine and _fpose and _fs is not None
            if _eng:
                _finfo = _face_track_channels(animname, F, fps, sm, chn)
            # LEGACY (up to 1.3.0) AUTO-PAIRED face: category pose for combat/damage/dance
            # clips, neutral otherwise
            _base = _fneut
            if not _eng and _fs is not None and _fpose:
                _pn = _fs.category_pose(animname, _fpose)
                if _pn:
                    _base = _fpose[_pn]
            t2 = np.array([0.0, max(float(times[-1]), 1e-3)], np.float32)
            ta2 = None if _eng else ac(av(t2.tobytes()), 5126, 2, "SCALAR", [0.0], [float(t2[-1])])
            _blinkset = set(_fblink[0]) if (_fblink is not None and _base is _fneut) else set()
            if _eng:
                _blinkset = set()
            for k in () if _eng else _facemask:
                if k in _blinkset:
                    continue  # blink channel written below
                vo = ac(
                    av(np.tile(_base[0][k].astype(np.float32), (2, 1)).tobytes()), 5126, 2, "VEC4"
                )
                to = ac(
                    av(np.tile(_base[1][k].astype(np.float32), (2, 1)).tobytes()), 5126, 2, "VEC3"
                )
                sm.append({"input": ta2, "output": vo, "interpolation": "LINEAR"})
                chn.append(
                    {"sampler": len(sm) - 1, "target": {"node": facenodes[k], "path": "rotation"}}
                )
                sm.append({"input": ta2, "output": to, "interpolation": "LINEAR"})
                chn.append(
                    {
                        "sampler": len(sm) - 1,
                        "target": {"node": facenodes[k], "path": "translation"},
                    }
                )
            if _blinkset:
                # sparse blink keys on the lid bones: neutral->closed->neutral
                # every ~3s (deterministic per clip), 0.24s per blink
                _dur = max(float(times[-1]), 0.5)
                import zlib as _z  # 2026-07-13: hash() is per-process random

                _per = 2.7 + ((_z.crc32(animname.encode()) % 100) / 100.0) * 0.9
                _keys = [0.0]
                _t = _per * 0.6
                while _t + 0.3 < _dur:
                    _keys += [_t, _t + 0.07, _t + 0.14, _t + 0.24]
                    _t += _per
                _keys.append(_dur)
                _kt = np.array(_keys, np.float32)
                # weights per blink group [start, closed, closed, open] ->
                # w=[0,1,1,0]  (2026-08-17: removed a dead first computation
                # this one immediately overwrote)
                _wts = np.zeros(len(_kt))
                for _i in range(1, len(_kt) - 4, 4):
                    _wts[_i + 1] = 1.0
                    _wts[_i + 2] = 1.0
                _ta3 = ac(av(_kt.tobytes()), 5126, len(_kt), "SCALAR", [0.0], [float(_kt[-1])])
                _lidk, _fcl = _fblink
                for k in _lidk:
                    _qn, _tn = _fneut[0][k], _fneut[1][k]
                    _qc, _tc = _fcl[0][k], _fcl[1][k]
                    if float(np.dot(_qn, _qc)) < 0:
                        _qc = -_qc
                    _Q = np.array([(_qn * (1 - w) + _qc * w) for w in _wts], np.float32)
                    _Q /= np.linalg.norm(_Q, axis=1, keepdims=True)
                    _T = np.array([(_tn * (1 - w) + _tc * w) for w in _wts], np.float32)
                    vo = ac(av(_Q.tobytes()), 5126, len(_kt), "VEC4")
                    to = ac(av(_T.tobytes()), 5126, len(_kt), "VEC3")
                    sm.append({"input": _ta3, "output": vo, "interpolation": "LINEAR"})
                    chn.append(
                        {
                            "sampler": len(sm) - 1,
                            "target": {"node": facenodes[k], "path": "rotation"},
                        }
                    )
                    sm.append({"input": _ta3, "output": to, "interpolation": "LINEAR"})
                    chn.append(
                        {
                            "sampler": len(sm) - 1,
                            "target": {"node": facenodes[k], "path": "translation"},
                        }
                    )
            for pi, bs in enumerate(_pslots):
                _MkCi = _palign[pi] if _palign is not None else _M4Ci
                Lp = np.einsum("fab,bc->fac", A4[:, bs], _MkCi)
                Qf = batch_m2q(Lp[:, :3, :3])
                for f in range(1, F):
                    if (Qf[f] * Qf[f - 1]).sum() < 0:
                        Qf[f] *= -1
                vo = ac(av(np.ascontiguousarray(Qf.astype(np.float32)).tobytes()), 5126, F, "VEC4")
                to = ac(
                    av(np.ascontiguousarray(Lp[:, :3, 3].astype(np.float32)).tobytes()),
                    5126,
                    F,
                    "VEC3",
                )
                sm.append({"input": ta, "output": vo, "interpolation": "LINEAR"})
                chn.append(
                    {"sampler": len(sm) - 1, "target": {"node": proxynodes[pi], "path": "rotation"}}
                )
                sm.append({"input": ta, "output": to, "interpolation": "LINEAR"})
                chn.append(
                    {
                        "sampler": len(sm) - 1,
                        "target": {"node": proxynodes[pi], "path": "translation"},
                    }
                )
        j["animations"].append(_anim(animname, sm, chn, F, fps, _finfo))
    if face is not None:
        fb = np.load(face["bind"], allow_pickle=True)
        fRb, ftb = fb["Rb"], fb["tb"]
        NF = len(fRb)
        B4f = np.tile(np.eye(4), (NF, 1, 1))
        B4f[:, :3, :3] = fRb
        B4f[:, :3, 3] = ftb
        for animname, A, fps in face["anims"]:
            F = len(A)
            times = (np.arange(F) / fps).astype(np.float32)
            ta = ac(av(times.tobytes()), 5126, F, "SCALAR", [0.0], [float(times[-1])])
            A4 = np.concatenate(
                [
                    A.astype(np.float64),
                    np.tile(np.array([0, 0, 0, 1.0]).reshape(1, 1, 1, 4), (F, NF, 1, 1)),
                ],
                axis=2,
            )
            Wp = np.einsum("fkab,kbc->fkac", A4, B4f)
            fix = np.einsum("ab,fbc->fac", B4f[_fhead], np.linalg.inv(Wp[:, _fhead]))
            L = np.einsum("fab,fkbc->fkac", fix, Wp)  # LOCAL under anchor
            Q = batch_m2q(L[:, :, :3, :3].reshape(-1, 3, 3)).reshape(F, NF, 4)
            for f in range(1, F):
                flip = np.einsum("kc,kc->k", Q[f], Q[f - 1]) < 0
                Q[f, flip] *= -1
            Tt = L[:, :, :3, 3]
            sm = []
            chn = []
            for k in _facemask:  # only bones BELOW Head: the rig's own
                # Bip01/Neck/Head tracks carry the cutscene neck posture and
                # would double-rotate the head that already rides the body.
                vo = ac(
                    av(np.ascontiguousarray(Q[:, k].astype(np.float32)).tobytes()), 5126, F, "VEC4"
                )
                to = ac(
                    av(np.ascontiguousarray(Tt[:, k].astype(np.float32)).tobytes()), 5126, F, "VEC3"
                )
                sm.append({"input": ta, "output": vo, "interpolation": "LINEAR"})
                chn.append(
                    {"sampler": len(sm) - 1, "target": {"node": facenodes[k], "path": "rotation"}}
                )
                sm.append({"input": ta, "output": to, "interpolation": "LINEAR"})
                chn.append(
                    {
                        "sampler": len(sm) - 1,
                        "target": {"node": facenodes[k], "path": "translation"},
                    }
                )
            _fa = {"name": animname, "samplers": sm, "channels": chn}
            if _engine:
                _fa["extras"] = {"watchmen": {"face_pose": _fr.pose_extras(meta, animname)}}
            j["animations"].append(_fa)
    if parts_record is not None:
        # The one scene holds the character as the game shows it.  The hidden
        # parts hang under a node "alternatives" that is in NO scene: viewers
        # draw scenes, so they never show it, and Blender's importer puts such
        # nodes in a switched-off collection ("Orphan Nodes"), still bound to the
        # armature.  (A second scene sharing the skeleton root was tried: valid,
        # but three.js clones a node used by two scenes and the animations then
        # drive the copy that is not displayed.)
        j["scenes"][0]["name"] = "game"
        _alt = [a for a in attnodes if a in _hidden]
        if _alt:
            j["nodes"].append({"name": "alternatives", "children": _alt})
        _names = {j["nodes"][a]["name"] for a in attnodes}
        _rec = dict(parts_record)
        _rec["hidden_nodes"] = [j["nodes"][a]["name"] for a in attnodes if a in _hidden]
        _rec["alternatives"] = [x for x in _rec.get("alternatives", []) if x["node"] in _names]
        _rec["hidden_under"] = (
            "node 'alternatives', which is in no scene; skinned to the same skeleton "
            "(skin 0).  Blender: collection 'Orphan Nodes', switched off after import"
            if _alt
            else None
        )
        j["asset"].setdefault("extras", {}).setdefault("watchmen", {})["parts"] = _rec
    if asset_extras:  # e.g. {"reconstruction": {...}} for a variant the game does not ship
        j["asset"].setdefault("extras", {}).setdefault("watchmen", {}).update(asset_extras)
    # restored content among the mesh pieces is named in the same record
    _pieces = [parts, (face or {}).get("parts")]
    _pieces += [p for _a, p in attachments or []] + [p for _a, p in alt_parts or []]
    _pieces += [p for _a, p, _s in outfit_parts or []]
    if any(we.lash_is_restored(pt[4]) for _pl in _pieces for pt in _pl or ()):
        _w = j["asset"].setdefault("extras", {}).setdefault("watchmen", {})
        _w["reconstruction"] = dict(_w.get("reconstruction") or {}, **we.lash_reconstruction_note())
    if ragdoll and (ragdoll.get("shapes") or ragdoll.get("joints")):
        # helper nodes only: appended last, nothing above refers to them
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
    for kk in ("animations", "skins", "images", "textures", "materials"):
        if not j.get(kk):
            j.pop(kk, None)
    if "textures" not in j:
        del j["samplers"]
    _frame.finish_gltf(j, BIN)
    j["buffers"].append({"byteLength": len(BIN)})
    jb = json.dumps(j, separators=(",", ":")).encode()
    while len(jb) % 4:
        jb += b" "
    bb = bytes(BIN)
    while len(bb) % 4:
        bb += b"\x00"
    _tmp = str(out) + ".tmp"
    with open(_tmp, "wb") as fh:
        fh.write(
            b"glTF"
            + struct.pack("<II", 2, 12 + 8 + len(jb) + 8 + len(bb))
            + struct.pack("<I", len(jb))
            + b"JSON"
            + jb
            + struct.pack("<I", len(bb))
            + b"BIN\x00"
            + bb
        )
    os.replace(_tmp, out)
    print("wrote %s  (%d anims, %.1f MB)" % (out, len(manifest), (12 + len(jb) + len(bb)) / 1e6))


# Skeleton asset name -> the bind npz built for it.  Populated from a binds
# directory (watchmenlib.ensure_binds / `watchmen binds`); the old hardcoded
# table pointed at a developer-machine directory that never shipped.
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
    CLIP_PREFIX_P1, which adds a family to the big and the fast enemies).  1.3.0 looked
    for EN4 clips on every skeleton but the female and the gimp one and wrote the other
    GLBs without a clip."""
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

    d = kapow_json.load_fragment(fragjson)  # the binary .fragment beside it wins
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
    bakes looping clips as closed laps; without it (None, the 1.3.0 behaviour) there
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
    bt = np.load(bind, allow_pickle=True)
    pal_names = [str(x) for x in bt["names"]]
    parts = load_parts(meshes, pal_names, naz=naz)
    manifest = []
    import glob as _g

    # 2026-07-12e capture verdict (ENGINE_CONSTANTS.md): jiggle_d6 'engine' is at
    # capture parity (dance capture 3.1-3.8deg vs d6 2.65 / AR2+gain 4.4) and is
    # file-only -> promoted to the bake default.  AR2: from jiggle_pass import apply_jiggle
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
            # 2026-08-17: tolerant lookup -- bake_v4 banks key by BARE clip
            # name ({clipname: header_bytes_or_path}, bake_v4.py:155); the old
            # nm+".animation"-only lookup silently missed on those and left
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

                dur = struct.unpack_from(bake_v4._detect_clip_order(h) + "f", h, 4)[0]
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
    ap.add_argument("--bank", default=None, help="a pickled {clip name: header bytes or path}")
    ap.add_argument("--jiggle", action="store_true")
    from jiggle_d6 import MODELS as _jiggle_models

    ap.add_argument("--jiggle-model", choices=tuple(sorted(_jiggle_models)), default=None)
    ap.add_argument("--bakedir", default="bake")
    a = ap.parse_args()
    bank = None
    if a.bank:
        with open(a.bank, "rb") as _fh:
            bank = pickle.load(_fh)
    build(
        a.frag,
        a.variant,
        a.out,
        bakedir=a.bakedir,
        bank=bank,
        jiggle=a.jiggle or a.jiggle_model is not None,
        jiggle_model=a.jiggle_model,
    )
