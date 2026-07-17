#!/usr/bin/env python3
"""
export_female_anims.py -- export the Dominatrix body mesh rigged to the file-decoded
female skeleton, with MANY female .animation clips baked as glTF animations (Blender
Actions). FK in local bone space: each bone node animates translation=restPos (const) +
rotation=clip-local-rotation; the engine->glTF Y-up rotation lives only on the Armature
root (it cancels in local space), so adding clips is just per-bone rotation tracks.

  python export_female_anims.py game.naz out.glb [--prefix EN4] [--max 60] [--fps 30]
"""

import struct, json, argparse, numpy as np
import watchmen_extract as we, rig_glb, extract_skeletons as es
import decode_skeleton_model as dsm

C = np.array([[1, 0, 0], [0, 0, 1], [0, -1.0, 0]])


def grab_blocks(naz):
    ents = list(we.naz_entries(naz))
    blocks = {}
    for e in ents:
        low = e.name.lower()
        if low.endswith(".block_h_z") or low.endswith(".block_s_z"):
            st = e.name[: -len("_h_z")] if low.endswith("_h_z") else e.name[: -len("_s_z")]
            blocks.setdefault(st, {})["h" if low.endswith("_h_z") else "s"] = we.naz_read(naz, e)
    return blocks


def decode_clip(h):
    """-> {boneName: keys (K,4 xyzw)}, nframes. Local rotation tracks."""
    gi = h.find(b"GamePivot")
    if gi < 0:
        return None, 0
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
    for name in nm:
        if p >= len(h):
            break
        t = h[p]
        p += 1
        if t == 1:
            kc = struct.unpack_from("<H", h, p)[0]
            p += 2
            p += 12
            k = np.frombuffer(h[p : p + kc * 8], np.int16).reshape(kc, 4).astype(float) / 10000.0
            p += kc * 8
            tr[name] = k  # xyzw
        elif t == 2:
            kc = struct.unpack_from("<H", h, p)[0]
            p += 2
            raw = np.frombuffer(h[p : p + kc * 14], np.int16).reshape(kc, 7).astype(float)
            p += kc * 14
            tr[name] = raw[:, 3:7] / 10000.0
        elif t == 0:
            kc = struct.unpack_from("<H", h, p)[0]
            p += 2
            b4 = struct.unpack_from("<4f", h, p)
            p += 16
            p += kc * 6
            tr[name] = np.array([[b4[0], b4[1], b4[2], b4[3]]])  # stored xyzw (fixed 2026-07-01)
        elif t == 3:
            p += 12
            p += 4
            q = struct.unpack_from("<4f", h, p)
            p += 16
            tr[name] = np.array([[q[0], q[1], q[2], q[3]]])  # stored xyzw (fixed 2026-07-01)
        else:
            break
    return tr, max(nf, 2)


def resamp(k, NF):
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


def mat2q(M):
    t = np.trace(M)
    if t > 0:
        s = (t + 1) ** 0.5 * 2
        w = 0.25 * s
        x = (M[2, 1] - M[1, 2]) / s
        y = (M[0, 2] - M[2, 0]) / s
        z = (M[1, 0] - M[0, 1]) / s
    else:
        i = int(np.argmax([M[0, 0], M[1, 1], M[2, 2]]))
        if i == 0:
            s = (1 + M[0, 0] - M[1, 1] - M[2, 2]) ** 0.5 * 2
            w = (M[2, 1] - M[1, 2]) / s
            x = 0.25 * s
            y = (M[0, 1] + M[1, 0]) / s
            z = (M[0, 2] + M[2, 0]) / s
        elif i == 1:
            s = (1 - M[0, 0] + M[1, 1] - M[2, 2]) ** 0.5 * 2
            w = (M[0, 2] - M[2, 0]) / s
            x = (M[0, 1] + M[1, 0]) / s
            y = 0.25 * s
            z = (M[1, 2] + M[2, 1]) / s
        else:
            s = (1 - M[0, 0] - M[1, 1] + M[2, 2]) ** 0.5 * 2
            w = (M[1, 0] - M[0, 1]) / s
            x = (M[0, 2] + M[2, 0]) / s
            y = (M[1, 2] + M[2, 1]) / s
            z = 0.25 * s
    q = np.array([x, y, z, w])
    return q / (np.linalg.norm(q) or 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("naz")
    ap.add_argument("out")
    ap.add_argument("--prefix", default="EN4,BS2")
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--fps", type=float, default=30.0)
    ap.add_argument("--body", default="Dominatrix_Suits2")
    a = ap.parse_args()
    blocks = grab_blocks(a.naz)
    # gather: female skeleton header, body mesh, female clips
    skelhdr = None
    mesh = None
    clips = []
    prefixes = tuple(p.strip().upper() for p in a.prefix.split(","))
    for st, hs in blocks.items():
        if "h" not in hs:
            continue
        try:
            it = list(we.extract_block(hs["h"], hs.get("s")))
        except:
            continue
        for e, h, s in it:
            n = e.name
            if n.endswith("Female_Skeleton.model"):
                skelhdr = h
            if n.endswith(a.body + ".model"):
                mesh = (h, s)
            if n.lower().endswith(".animation"):
                import re

                m = re.search(r"/Animation/([A-Za-z0-9]+)/", n)
                if m and m.group(1).upper() in prefixes and len(clips) < a.max:
                    clips.append((n.rsplit("/", 1)[-1].replace(".animation", ""), h))
    print(
        "skeleton:", skelhdr is not None, "| body:", mesh is not None, "| female clips:", len(clips)
    )
    # file skeleton, engine-ID order (48 bones)
    recs = es._ordered_names(skelhdr)
    hdr_names = [nm for _, nm in recs]
    eng = ["GamePivot"] + [nm for nm in hdr_names if nm != "GamePivot"]
    NB = len(eng)
    nodes, _ = dsm.decode(skelhdr)
    fpar = es._explicit_parent_names(skelhdr)
    n2i = {nm: i for i, nm in enumerate(eng)}
    par = [-1] * NB
    for i, nm in enumerate(eng):
        if nm != "GamePivot":
            par[i] = n2i.get(fpar.get(nm), 0)
    rpos = [np.array(nodes[nm]["pos"]) if nm in nodes else np.zeros(3) for nm in eng]
    rq_wxyz = [
        np.array(nodes[nm]["quat_wxyz"]) if nm in nodes else np.array([1, 0, 0, 0.0]) for nm in eng
    ]
    # mesh + skin
    mh, ms = mesh
    _mesh_names = [nm for _, nm in es._ordered_names(mh)]
    palette_names = [nm for nm in _mesh_names if nm in n2i]
    skin2eng = [n2i[nm] for nm in palette_names]  # skin index -> eng bone index (VERIFIED)
    descs = we.find_descriptors(mh)
    V = []
    SI = []
    SW = []
    T = []
    subs = []
    off = 0
    for nv, stride, ib in descs:
        hi = len(ms) - nv * stride - ib
        c = off
        vbo = None
        while c <= min(off + 65536, hi):
            if we._sane(struct.unpack_from("<f", ms, c)[0]) and we._vb_ok(ms, c, nv, stride, ib):
                vbo = c
                break
            c += 1
        if vbo is None:
            continue
        v, _, _ = we._decode_sub(ms, vbo, nv, stride)
        si, sw = rig_glb.decode_skin(ms, vbo, nv, stride)
        base = len(V)
        ibo = vbo + nv * stride
        ts = len(T)
        for t in range(ib // 6):
            x, y, z = struct.unpack_from("<3H", ms, ibo + t * 6)
            if x < nv and y < nv and z < nv and len({x, y, z}) == 3:
                T.append((base + x, base + y, base + z))
        V.extend(v)
        SI.append(si)
        SW.append(sw)
        subs.append((base, len(v), ts, len(T) - ts))
        off = ibo + ib
    Vg = (C @ np.array(V, float).T).T.astype(np.float32)
    SI = np.concatenate(SI).astype(np.uint8)
    SW = np.concatenate(SW).astype(np.float32)
    # glb
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
        "materials": [],
        "animations": [],
    }
    BIN = bytearray()

    def av(x):
        while len(BIN) % 4:
            BIN.append(0)
        o = len(BIN)
        BIN.extend(x)
        j["bufferViews"].append({"buffer": 0, "byteOffset": o, "byteLength": len(x)})
        return len(j["bufferViews"]) - 1

    def ac(bv, ct, c, t, mn=None, mx=None):
        A = {"bufferView": bv, "componentType": ct, "count": c, "type": t}
        if mn is not None:
            A["min"] = mn
            A["max"] = mx
        j["accessors"].append(A)
        return len(j["accessors"]) - 1

    # bone nodes (rest pose), glb-space local via C4 only at root
    children = {i: [] for i in range(NB)}
    for i in range(NB):
        if par[i] >= 0:
            children[par[i]].append(i)
    bnode = []
    for i, nm in enumerate(eng):
        q = rq_wxyz[i]
        bnode.append(len(j["nodes"]))
        j["nodes"].append(
            {
                "name": nm,
                "translation": [float(x) for x in rpos[i]],
                "rotation": [float(q[1]), float(q[2]), float(q[3]), float(q[0])],
            }
        )
    for i in range(NB):
        if children[i]:
            j["nodes"][bnode[i]]["children"] = [bnode[c] for c in children[i]]

    # IBM = inverse(engine rest world)
    def depth(i):
        d = 0
        while par[i] >= 0:
            d += 1
            i = par[i]
        return d

    order = sorted(range(NB), key=depth)
    Weng = [None] * NB
    for i in order:
        L = np.eye(4)
        L[:3, :3] = dsm.qmat_wxyz(rq_wxyz[i])
        L[:3, 3] = rpos[i]
        Weng[i] = (Weng[par[i]] @ L) if par[i] >= 0 else L
    ibm = np.array([np.linalg.inv(Weng[i]) for i in range(NB)]).astype(np.float32)
    ibmacc = ac(
        av(np.array([m.T.reshape(16) for m in ibm]).astype(np.float32).tobytes()), 5126, NB, "MAT4"
    )
    # mesh primitives
    prims = []
    for base, nv, ts, ntr in subs:
        P = Vg[base : base + nv]
        ap_ = ac(av(P.tobytes()), 5126, nv, "VEC3", P.min(0).tolist(), P.max(0).tolist())
        Ip = np.ascontiguousarray(SI[base : base + nv])
        Wp = np.ascontiguousarray(SW[base : base + nv])
        aj = ac(av(Ip.tobytes()), 5121, nv, "VEC4")
        aw = ac(av(Wp.tobytes()), 5126, nv, "VEC4")
        tri = np.array(T[ts : ts + ntr], np.uint32) - base
        ai = ac(av(np.ascontiguousarray(tri).tobytes()), 5125, tri.size, "SCALAR")
        j["materials"].append(
            {
                "name": "m%d" % len(prims),
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.8, 0.8, 0.82, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.8,
                },
                "doubleSided": True,
            }
        )
        prims.append(
            {
                "attributes": {"POSITION": ap_, "JOINTS_0": aj, "WEIGHTS_0": aw},
                "indices": ai,
                "material": len(j["materials"]) - 1,
                "mode": 4,
            }
        )
    j["meshes"].append({"name": a.body, "primitives": prims})
    mnode = len(j["nodes"])
    j["nodes"].append({"name": a.body + "_mesh", "mesh": 0, "skin": 0})
    rq = [-0.7071068, 0, 0, 0.7071068]  # Rx(-90) Y-up at root
    arm = len(j["nodes"])
    j["nodes"].append(
        {
            "name": "Armature",
            "rotation": rq,
            "children": [bnode[i] for i in range(NB) if par[i] < 0] + [mnode],
        }
    )
    # joints + IBM in SKIN (mesh palette) order so JOINTS_0 indices map to the right bone
    joints_skin = [bnode[skin2eng[k]] for k in range(len(palette_names))]
    ibm_skin = np.array([ibm[skin2eng[k]] for k in range(len(palette_names))]).astype(np.float32)
    ibmacc = ac(
        av(np.array([mm.T.reshape(16) for mm in ibm_skin]).astype(np.float32).tobytes()),
        5126,
        len(joints_skin),
        "MAT4",
    )
    j["skins"].append({"joints": joints_skin, "inverseBindMatrices": ibmacc, "skeleton": arm})
    j["scenes"][0]["nodes"] = [arm]
    # animations: per clip, per bone rotation track (translation stays rest)
    nok = 0
    for cname, ch in clips:
        tr, nf = decode_clip(ch)
        if not tr:
            continue
        NF = max(2, min(nf, 120))
        times = (np.arange(NF) / a.fps).astype(np.float32)
        ta = ac(av(times.tobytes()), 5126, NF, "SCALAR", [0.0], [float(times[-1])])
        sm = []
        chn = []
        for i, nm in enumerate(eng):
            if nm not in tr:
                continue
            R = resamp(np.array(tr[nm]), NF).astype(np.float32)  # xyzw per frame (local rotation)
            vo = ac(av(np.ascontiguousarray(R).tobytes()), 5126, NF, "VEC4")
            sm.append({"input": ta, "output": vo, "interpolation": "LINEAR"})
            chn.append({"sampler": len(sm) - 1, "target": {"node": bnode[i], "path": "rotation"}})
        if chn:
            j["animations"].append({"name": cname, "samplers": sm, "channels": chn})
            nok += 1
    if not j["animations"]:
        del j["animations"]
    j["buffers"].append({"byteLength": len(BIN)})
    jb = json.dumps(j, separators=(",", ":")).encode()
    while len(jb) % 4:
        jb += b" "
    bb = bytes(BIN)
    while len(bb) % 4:
        bb += b"\x00"
    open(a.out, "wb").write(
        b"glTF"
        + struct.pack("<II", 2, 12 + 8 + len(jb) + 8 + len(bb))
        + struct.pack("<I", len(jb))
        + b"JSON"
        + jb
        + struct.pack("<I", len(bb))
        + b"BIN\x00"
        + bb
    )
    print("wrote %s | bones %d | %d animations | %d verts" % (a.out, NB, nok, len(V)))


if __name__ == "__main__":
    main()
