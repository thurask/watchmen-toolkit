#!/usr/bin/env python3
# ONE GLB PER CHARACTER VARIANT with ALL of its animations.
#   python3 variant_glb.py FRAGMENT.json VARIANT_NAME OUT.glb [--clips PREFIX] \
#       [--bind BIND.npz] [--bank CLIPBANK.pkl]
# Uses: engine-exact bind (bind_v14b/gimp...), bake_v4 math (conjugate convention,
# absolute root), real IBMs + joint-space TRS (interpolation-safe), real-time rates.
import os, sys, json, struct, pickle
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


# Engine playback-speed overrides -- MOSTLY RETIRED (2026-07-09,
# docs/ENGINE_CONSTANTS.md): the clip header was misread (hdr[0]=keyRate Hz
# was taken as duration; hdr[1] is the true duration).  With header-exact fps
# the old turn/settle/step/run_start/stop multipliers (2.7-3.2 needed vs 3.0
# empirical etc.) are reproduced NATIVELY and are gone.  What remains is
# genuine RUNTIME movement sync (AnimSlot.SetSpeed scales locomotion cycles to
# actual velocity -- capture strut 1.43-1.63s vs authored 3.4s):
SPEED_MULT = [
    ("walk_cycle", 2.3),  # capture strut match / header-exact base
    ("run_cycle", 2.6),  # capture-era estimate rebased to header fps
]


def speed_mult(nm):
    for k, m in SPEED_MULT:
        if k in nm:
            return m
    return 1.0


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


def load_parts(mesh_names, palette_names, naz="01_game.naz"):
    NB = len(palette_names)
    skelset = set(palette_names)
    uslot = {n: i for i, n in enumerate(palette_names)}
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
                found.setdefault(nm, []).append((h, s))
    parts = []
    for nm in mesh_names:
        if nm not in found:
            print("  ! mesh missing:", nm)
            continue
        cands = sorted(found[nm], key=lambda t: -(len(t[1]) if t[1] else 0))
        mh, ms = cands[0]
        if ms is None:
            continue
        # per-part skin-index remap (each part mesh has its OWN bone list)
        plist = [x for _, x in es._ordered_names(mh)]
        pf = [x for x in plist if x in skelset]
        ppal = [pf[(k - 1) % len(pf)] for k in range(len(pf))]
        remap = np.array([uslot.get(n, 0) for n in ppal], dtype=np.int64)
        descs = we.find_descriptors(mh)
        mats = we.extract_materials(mh)
        off = 0
        for si, (nv, stride, ib) in enumerate(descs):
            hi = len(ms) - nv * stride - ib
            c = off
            vbo = None
            while c <= min(off + 65536, hi):
                if we._sane(struct.unpack_from("<f", ms, c)[0]) and we._vb_ok(
                    ms, c, nv, stride, ib
                ):
                    vbo = c
                    break
                c += 1
            if vbo is None:
                continue
            v, _, uv = we._decode_sub(ms, vbo, nv, stride)
            skidx, skw = rig_glb.decode_skin(ms, vbo, nv, stride)
            ibo = vbo + nv * stride
            T = []
            for t in range(ib // 6):
                x, y, z = struct.unpack_from("<3H", ms, ibo + t * 6)
                if x < nv and y < nv and z < nv and len({x, y, z}) == 3:
                    T.append((x, y, z))
            off = ibo + ib
            if not v or not T:
                continue
            SI = remap[np.clip(np.asarray(skidx, int), 0, len(remap) - 1)]
            SI = np.clip(SI, 0, NB - 1)
            mat = mats[si] if si < len(mats) else "%s_sub%d" % (nm, si)
            parts.append(
                (
                    np.array(v, float),
                    SI.astype(np.uint16),
                    np.asarray(skw, np.float32),
                    np.array(T),
                    np.array(uv if uv else [(0.0, 0.0)] * len(v), np.float32),
                    mat,
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
    off = np.array([[0, -eps], [eps, eps], [-eps, eps]])  # fixed 2*eps^2 UV triangle
    for t in bad:
        idx = T[t]
        # rebuild around the face's UV centroid -> guaranteed non-degenerate
        # even for sliver faces (distinct-but-collinear UVs), not just fully
        # collapsed ones.
        V.append(v[idx])
        SI.append(si[idx])
        SW.append(sw[idx])
        UV.append(uv[idx].mean(0) + off)
        T[t] = [n, n + 1, n + 2]
        n += 3
    return (
        np.concatenate(V),
        np.concatenate(SI).astype(np.uint16),
        np.concatenate(SW).astype(np.float32),
        T,
        np.concatenate(UV).astype(np.float32),
        mat,
    )


def write_glb(parts, manifest, out, bindnpz, textures=None, face=None, attachments=None):
    """textures: optional {material_name: png_bytes | dict} -> embedded maps.
    dict form: {'diffuse':png, 'normal':png, 'mr':png, 'spec':png} (all optional).
    normal = glTF convention (green up); mr = occlusion/roughness/metallic in R/G/B;
    spec -> KHR_materials_specular specularColorTexture."""
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
        if face is not None and face.get("parts"):
            face = dict(face)
            face["parts"] = _san(face["parts"])
    bt = np.load(bindnpz, allow_pickle=True)
    Rb = bt["Rb"]
    tb = bt["tb"]
    NB = len(Rb)
    B4 = np.tile(np.eye(4), (NB, 1, 1))
    B4[:, :3, :3] = Rb
    B4[:, :3, 3] = tb
    IBM = np.array([np.linalg.inv(B4[k]) for k in range(NB)])
    j = {
        "asset": {"version": "2.0", "generator": "watchmen_extract variant_glb"},
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

    def av(x):
        while len(BIN) % 4:
            BIN.append(0)
        ofs = len(BIN)
        BIN.extend(x)
        j["bufferViews"].append({"buffer": 0, "byteOffset": ofs, "byteLength": len(x)})
        return len(j["bufferViews"]) - 1

    def ac(bv, ct, c, t, mn=None, mx=None):
        A = {"bufferView": bv, "componentType": ct, "count": c, "type": t}
        if mn is not None:
            A["min"] = mn
            A["max"] = mx
        j["accessors"].append(A)
        return len(j["accessors"]) - 1

    _texdone = {}

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
        j["nodes"].append(nd)
    ibmacc = ac(
        av(np.array([m.T.reshape(16) for m in IBM], np.float32).tobytes()), 5126, NB, "MAT4"
    )
    prims = []
    for V, SI, SW, T, UV, nm in parts:
        Vg = np.ascontiguousarray(V, np.float32)
        ap = ac(av(Vg.tobytes()), 5126, len(Vg), "VEC3", Vg.min(0).tolist(), Vg.max(0).tolist())
        aj = ac(av(np.ascontiguousarray(SI).tobytes()), 5123, len(Vg), "VEC4")
        aw = ac(av(np.ascontiguousarray(SW).tobytes()), 5126, len(Vg), "VEC4")
        auv = ac(av(np.ascontiguousarray(UV).tobytes()), 5126, len(Vg), "VEC2")
        ai = ac(av(np.ascontiguousarray(T.astype(np.uint32)).tobytes()), 5125, T.size, "SCALAR")
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
            if "spec" in layers:
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
                "attributes": {"POSITION": ap, "JOINTS_0": aj, "WEIGHTS_0": aw, "TEXCOORD_0": auv},
                "indices": ai,
                "material": mi,
                "mode": 4,
            }
        )
    j["meshes"].append({"name": "variant", "primitives": prims})
    mnode = len(j["nodes"])
    j["nodes"].append({"name": "mesh", "mesh": 0, "skin": 0})
    j["skins"].append({"joints": bnode, "inverseBindMatrices": ibmacc})

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
            if "spec" in layers:
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
    for aname, aparts in attachments or []:
        # each attachment = its OWN mesh node sharing skin 0 (verts already in
        # body bind space, weighted to the attach bone slot) -> imports as a
        # separate object, individually hideable.
        aprims = []
        for V, SI, SW, T, UV, nm in aparts:
            Vg = np.ascontiguousarray(V, np.float32)
            ap = ac(av(Vg.tobytes()), 5126, len(Vg), "VEC3", Vg.min(0).tolist(), Vg.max(0).tolist())
            aj = ac(av(np.ascontiguousarray(SI).tobytes()), 5123, len(Vg), "VEC4")
            aw = ac(av(np.ascontiguousarray(SW).tobytes()), 5126, len(Vg), "VEC4")
            auv = ac(av(np.ascontiguousarray(UV).tobytes()), 5126, len(Vg), "VEC2")
            ai_ = ac(
                av(np.ascontiguousarray(T.astype(np.uint32)).tobytes()), 5125, T.size, "SCALAR"
            )
            aprims.append(
                {
                    "attributes": {
                        "POSITION": ap,
                        "JOINTS_0": aj,
                        "WEIGHTS_0": aw,
                        "TEXCOORD_0": auv,
                    },
                    "indices": ai_,
                    "material": _mkmat(nm),
                    "mode": 4,
                }
            )
        if not aprims:
            continue
        mi_ = len(j["meshes"])
        j["meshes"].append({"name": aname, "primitives": aprims})
        attnodes.append(len(j["nodes"]))
        j["nodes"].append({"name": aname, "mesh": mi_, "skin": 0})
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
        for V, SI, SW, T, UV, nm in face["parts"]:
            Vg = np.ascontiguousarray(V, np.float32)
            ap = ac(av(Vg.tobytes()), 5126, len(Vg), "VEC3", Vg.min(0).tolist(), Vg.max(0).tolist())
            aj = ac(av(np.ascontiguousarray(SI).tobytes()), 5123, len(Vg), "VEC4")
            aw = ac(av(np.ascontiguousarray(SW).tobytes()), 5126, len(Vg), "VEC4")
            auv = ac(av(np.ascontiguousarray(UV).tobytes()), 5126, len(Vg), "VEC2")
            ai_ = ac(
                av(np.ascontiguousarray(T.astype(np.uint32)).tobytes()), 5125, T.size, "SCALAR"
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
                    "attributes": {
                        "POSITION": ap,
                        "JOINTS_0": aj,
                        "WEIGHTS_0": aw,
                        "TEXCOORD_0": auv,
                    },
                    "indices": ai_,
                    "material": mi,
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
    rootkids = bnode + [mnode] + attnodes
    j["nodes"].append({"name": "root", "children": rootkids})
    j["skins"][0]["skeleton"] = root
    j["scenes"][0]["nodes"] = [root]
    if face is not None:
        j["scenes"][0]["nodes"].append(frn)
        j["nodes"][frn].setdefault("children", []).append(fmnode)
        j["skins"][1]["skeleton"] = frn
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
        _fpose = {}
        try:
            import face_synth as _fs

            for _pn, _pp in (face.get("auto_poses") or {}).items():
                _fpose[_pn] = _locals_for(_pp)
        except Exception:
            _fs = None
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
    for entry in manifest:
        # (name, pal, fps) or (name, pal, fps, bone_indices) -- the 4-tuple
        # form writes channels ONLY for the listed bones (partial overlay
        # anims, e.g. GRIP hand poses layered over body clips in NLA).
        if len(entry) == 4:
            animname, A, fps, bmask = entry
        else:
            animname, A, fps = entry
            bmask = None
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
            # AUTO-PAIRED face: category pose for combat/damage/dance clips,
            # neutral otherwise (engine pairs these procedurally at runtime)
            _base = _fneut
            if _fs is not None and _fpose:
                _pn = _fs.category_pose(animname, _fpose)
                if _pn:
                    _base = _fpose[_pn]
            t2 = np.array([0.0, max(float(times[-1]), 1e-3)], np.float32)
            ta2 = ac(av(t2.tobytes()), 5126, 2, "SCALAR", [0.0], [float(t2[-1])])
            _blinkset = set(_fblink[0]) if (_fblink is not None and _base is _fneut) else set()
            for k in _facemask:
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
                _wts = np.zeros(len(_kt))
                for _i in range(1, len(_kt) - 1, 4):
                    if _i + 2 < len(_kt):
                        _wts[_i + 1] = 1.0
                        _wts[_i + 2] = 1.0 if _i + 3 < len(_kt) - 1 else 0.0
                # weights pattern per blink: t0=0, t1(close start)=0? keys are
                # [start, closed, closed, open] -> w=[0,1,1,0]
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
        j["animations"].append({"name": animname, "samplers": sm, "channels": chn})
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
            j["animations"].append({"name": animname, "samplers": sm, "channels": chn})
    for kk in ("animations", "skins", "images", "textures", "materials"):
        if not j.get(kk):
            j.pop(kk, None)
    if "textures" not in j:
        del j["samplers"]
    j["buffers"].append({"byteLength": len(BIN)})
    jb = json.dumps(j, separators=(",", ":")).encode()
    while len(jb) % 4:
        jb += b" "
    bb = bytes(BIN)
    while len(bb) % 4:
        bb += b"\x00"
    _tmp = str(out) + ".tmp"
    open(_tmp, "wb").write(
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


def variant_from_fragment(fragjson, variant):
    d = json.load(open(fragjson))
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
):
    """One fragment variant -> one GLB carrying every baked clip in `bakedir`.

    bind    : path to the bind npz for this variant's skeleton, or
    binddir : a directory of binds (see `watchmen binds`) to pick it from.
    """
    skel, meshes = variant_from_fragment(fragjson, variant)
    if not bind and binddir:
        bind = binds_from_dir(binddir).get(skel)
    if not bind:
        raise ValueError(
            "no bind for skeleton %r -- pass bind=<npz> or binddir=<dir built by "
            "`watchmen binds NAZ OUT/binds`)" % skel
        )
    prefix = prefix or CLIP_PREFIX.get(skel, ("EN4",))
    if isinstance(prefix, str):
        prefix = (prefix,)
    print(
        "variant %s: skeleton=%s meshes=%s bind=%s clips=%s" % (variant, skel, meshes, bind, prefix)
    )
    bt = np.load(bind, allow_pickle=True)
    pal_names = [str(x) for x in bt["names"]]
    parts = load_parts(meshes, pal_names)
    manifest = []
    import glob as _g

    # 2026-07-12e capture verdict (ENGINE_CONSTANTS.md): jiggle_d6 'engine' is at
    # capture parity (dance capture 3.1-3.8deg vs d6 2.65 / AR2+gain 4.4) and is
    # file-only -> promoted to the bake default.  AR2: from jiggle_pass import apply_jiggle
    from jiggle_d6 import apply_jiggle

    _files = []
    for pf in prefix:
        _files += _g.glob(os.path.join(bakedir, pf + "*.npy"))
    for f in sorted(set(_files)):
        A = np.load(f)
        nm = os.path.basename(f)[:-4]
        fps = 30.0
        if bank:
            h = bank.get(nm + ".animation")
            if h is not None:
                # header = [f32 keyRate Hz][f32 duration s] ... -- hdr[0] is the
                # RATE, not the duration (bake_v4.py:265).  fps must match
                # bake_v4.fps_for(): (keys-1)/duration.
                dur = struct.unpack_from("<f", h, 4)[0]
                if dur > 0 and len(A) > 1:
                    fps = (len(A) - 1) / dur
        fps *= speed_mult(nm)
        if jiggle:
            try:
                A = apply_jiggle(A, fps, bind)
            except Exception as e:
                print("  jiggle skip %s: %s" % (nm, e))
        manifest.append((nm, A, fps))
    write_glb(parts, manifest, out, bind)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("frag")
    ap.add_argument("variant")
    ap.add_argument("out")
    ap.add_argument("--bank", default="/tmp/clipbank_en4.pkl")
    ap.add_argument("--jiggle", action="store_true")
    ap.add_argument("--bakedir", default="/tmp/allbake")
    a = ap.parse_args()
    bank = pickle.load(open(a.bank, "rb")) if os.path.exists(a.bank) else None
    build(a.frag, a.variant, a.out, bakedir=a.bakedir, bank=bank, jiggle=a.jiggle)
