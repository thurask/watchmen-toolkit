"""File-only skeleton record parser (v14-era knowledge) + node collision volumes.

Each bone record: [u32 namelen][name\0][body]; body starts [u32 f1][u32 parent]
then the mesh-binding counts, one flag byte and the node's COLLISION VOLUMES
(Node::Deserialize 0x545927, volume lists at 0x545c7f..0x545d94):

    [u32 n0] n0 x volume      -> node+0x4c, shapes for PhysX scene 0
    [u32 n1] n1 x volume      -> node+0x58, shapes for PhysX scene 1
    [u32 n2] n2 x surface     -> node+0x64; non-empty on ONE node of the PC
                                 corpus (ACUnit_Wall_02 "splash emitter")
    surface = [u32 nT][nT x (f32x3, f32, i32)][u32 nV][nV x f32x3][u32 nI][nI x u32]
              (reader 0x561d1c; vtable 0xa3d538 sits beside the
               particleemitternode.cpp tag -> emitter surface, inferred)

    volume = [u32 type][u32 base][type data][f32x3 pos][f32x4 quat xyzw]
             [u32 blobLen][blob]                     (factory 0x524b23)
      type 2 concave mesh / 4 convex mesh : [u32 mode][u32 nV][nV x f32x3]
                                            [u32 nI][nI x u32]; blob = cooked
                                            PhysX mesh ("NXS\x01CVXM" for 4)
      type 5 box     : [f32x3 full extents]            (reader 0x521396)
      type 6 sphere  : [f32 radius]                    (reader 0x521c3f)
      type 7 capsule : [f32 diameter][f32 height along local Y]  (0x52213d)

These are what earlier notes called "EmbeddedJointNode joints, types 4/5/6/7";
they are collision shapes, not joints.  `entries` (below) is the older
byte-granular scan for [pos][quat] pairs and is kept unchanged: it finds the
volume placements plus the NEXT node's rest transform at the body tail.
Engine quats = conjugate of naive xyzw convention.
"""

import struct, numpy as np

VOLUME_TYPES = {2: "concave_mesh", 4: "convex_mesh", 5: "box", 6: "sphere", 7: "capsule"}
_MAX_VOLUMES = 4096  # sanity bound on a count field, not an engine limit


def parse_volume_lists(mb, p, order="<", limit=None):
    """Engine-layout read of the two volume lists + the third list, starting at
    `p` (just after the node's flag byte).  -> (lists, surfaces, end_offset).
    Raises ValueError / struct.error when the bytes are not volume lists."""
    limit = len(mb) if limit is None else limit

    def take(fmt):
        nonlocal p
        n = struct.calcsize(fmt)
        if p + n > limit:
            raise ValueError("volume record runs past the node region")
        v = struct.unpack_from(order + fmt, mb, p)
        p += n
        return v

    lists = []
    for _scene in range(2):
        (n,) = take("I")
        if n > _MAX_VOLUMES:
            raise ValueError("implausible volume count %d" % n)
        vols = []
        for _ in range(n):
            t, base = take("2I")
            v = dict(type=t, kind=VOLUME_TYPES.get(t), base=base)
            if t == 5:
                v["size"] = take("3f")  # full extents (AABB method 0x5213c7 = +-0.5*size)
            elif t == 6:
                (v["radius"],) = take("f")
            elif t == 7:
                v["diameter"], v["height"] = take("2f")  # height = total, local Y (0x522164)
            elif t in (2, 4):
                v["mode"], nv = take("2I")  # mode 1 = triangle list, else strip (0x522d17)
                if p + 12 * nv > limit:
                    raise ValueError("mesh vertices run past the node region")
                v["verts"] = np.frombuffer(mb, order + "f4", 3 * nv, p).reshape(nv, 3).copy()
                p += 12 * nv
                (ni,) = take("I")
                if p + 4 * ni > limit:
                    raise ValueError("mesh indices run past the node region")
                v["indices"] = np.frombuffer(mb, order + "u4", ni, p).copy()
                p += 4 * ni
            else:
                raise ValueError("unknown collision volume type %d" % t)  # 0x524b23 returns null
            v["pos"] = take("3f")
            v["quat"] = take("4f")
            (bl,) = take("I")
            if p + bl > limit:
                raise ValueError("volume blob runs past the node region")
            v["blob"] = bytes(mb[p : p + bl])
            p += bl
            vols.append(v)
        lists.append(vols)
    # third list (node+0x64, 0x28-byte elements, reader 0x561d1c): non-empty on
    # one node of the PC corpus ("splash emitter"): per-triangle records + a mesh
    (n3,) = take("I")
    if n3 > _MAX_VOLUMES:
        raise ValueError("implausible third-list count %d" % n3)
    surfaces = []
    for _ in range(n3):
        (nt,) = take("I")
        if nt > 1 << 20:
            raise ValueError("implausible surface record count %d" % nt)
        tris = []
        for _ in range(nt):
            vx, vy, vz, w, ident = take("4fi")  # vec3 -> +0x00, f32 -> +0x10, u32 -> +0x14
            tris.append(dict(vec=(vx, vy, vz), value=w, id=ident))
        (nv,) = take("I")  # mesh sub-object 0x40b7df
        if p + 12 * nv > limit:
            raise ValueError("surface vertices run past the node region")
        verts = np.frombuffer(mb, order + "f4", 3 * nv, p).reshape(nv, 3).copy()
        p += 12 * nv
        (ni,) = take("I")
        if p + 4 * ni > limit:
            raise ValueError("surface indices run past the node region")
        indices = np.frombuffer(mb, order + "u4", ni, p).copy()
        p += 4 * ni
        surfaces.append(dict(tris=tris, verts=verts, indices=indices))
    return lists, surfaces, p


def parse_node_tail(mb, start, end=None, order="<"):
    """One node's bytes after its name: [f1][parent][cnt34][cnt34 x u32][cnt40]
    [u8 flag][volume lists].  -> dict(f1, parent, volumes=[scene0, scene1],
    surfaces=[third-list elements], end)
    or None when the node carries mesh bindings / a node+0x30 object (not read
    here) or the bytes do not tile [start, end) exactly.  end=None accepts
    wherever the record ends (last node of a file)."""
    try:
        f1, parent, c34 = struct.unpack_from(order + "IiI", mb, start)
        p = start + 12
        if c34 > 64:
            return None
        for _ in range(c34):
            if struct.unpack_from(order + "I", mb, p)[0]:
                return None  # mesh node
            p += 4
        if struct.unpack_from(order + "I", mb, p)[0]:
            return None  # mesh buffers
        p += 4
        if p >= len(mb) or mb[p]:
            return None  # node+0x30 object present (0x545bd9)
        p += 1
        lists, surfaces, p = parse_volume_lists(mb, p, order, end)
    except (struct.error, ValueError):
        return None
    if end is not None and p != end:
        return None
    return dict(f1=f1, parent=parent, volumes=lists, surfaces=surfaces, end=p)


def node_volumes(h, order=None):
    """-> [(name, [scene0 volumes, scene1 volumes] or None)] for every named
    node record, in file order (None: mesh node or bytes that do not tile)."""
    return [(r["name"], r["volumes"]) for r in parse(h, order=order)]


def is_node_record(h, lp, order="<"):
    """parse_model_nodes.parse()'s test for a TRUE node record at name offset
    `lp`: the 28 bytes before the name are [finite pos][unit quat] and the
    [f1][parent] pair fits.  (Name tables that precede the node array fail.)"""
    if lp < 28 or lp + 4 > len(h):
        return False
    p = np.frombuffer(h, dtype=order + "f4", count=3, offset=lp - 28).astype(np.float64)
    q = np.frombuffer(h, dtype=order + "f4", count=4, offset=lp - 16).astype(np.float64)
    if not np.isfinite(q).all() or abs(float((q * q).sum()) - 1.0) > 1e-3:
        return False
    if not np.isfinite(p).all() or np.abs(p).max() > 100:
        return False
    nl = struct.unpack_from(order + "I", h, lp)[0]
    return lp + 4 + nl + 8 <= len(h)


def node_records(h, order="<"):
    occ = []
    i = 0
    N = len(h)
    while i + 4 <= N:
        n = struct.unpack_from(order + "I", h, i)[0]
        if 2 <= n <= 40 and i + 4 + n <= N:
            s = h[i + 4 : i + 4 + n]
            if (
                s[-1] == 0
                and all(32 <= b < 127 for b in s[:-1])
                and s[:1].isalpha()
                and all(chr(b).isalnum() or chr(b) in " _" for b in s[:-1])
            ):
                occ.append((i, s[:-1].decode()))
                i += 4 + n
                continue
        i += 1
    return occ


def _detect_order(h):
    """'<' PC / '>' X360+PS3, same idiom as parse_model_nodes: the u32 namelen
    only parses small in the header's real byte order (2026-08-17; this module
    was LE-only, so console models yielded empty/garbage records)."""
    return "<" if len(node_records(h, "<")) >= len(node_records(h, ">")) else ">"


def parse(h, maxpos=5.0, order=None):
    if order is None:
        order = _detect_order(h)
    occ = [(i, n) for i, n in node_records(h, order) if "/" not in n and n != "ModelRes"]
    recs = []
    for k, (lp, nm) in enumerate(occ):
        namelen = struct.unpack_from(order + "I", h, lp)[0]
        b0 = lp + 4 + namelen
        b1 = occ[k + 1][0] if k + 1 < len(occ) else len(h)
        body = h[b0:b1]
        par = (
            struct.unpack_from(order + "i", body, 4)[0] - 1 if len(body) >= 8 else -2
        )  # u32@4 = parent+1 (1-based, 0=root)
        # scan body for 28B [pos f32x3][quat f32x4 unit] entries, byte-granular
        ents = []
        j = 0
        while j + 28 <= len(body):
            v = struct.unpack_from(order + "7f", body, j)
            p = np.array(v[:3])
            q = np.array(v[3:])
            n2 = float(q @ q)
            if 0.98 < n2 < 1.02 and np.all(np.isfinite(p)) and np.linalg.norm(p) < maxpos:
                ents.append((j, p, q))
                j += 28
            else:
                j += 1
        # volumes: the tail ends 28 bytes before the next name (that node's own
        # transform); the last node has no successor, so only its start is fixed
        tail = parse_node_tail(h, b0, b1 - 28 if k + 1 < len(occ) else None, order)
        recs.append(
            dict(
                name=nm,
                offset=lp,
                parent=par,
                body=body,
                entries=ents,
                volumes=tail["volumes"] if tail else None,
            )
        )
    return recs


if __name__ == "__main__":
    import sys

    h = open(sys.argv[1], "rb").read()
    rs = parse(h)
    print(len(rs), "records")
    for r in rs[:60]:
        print(
            "%-16s par=%3d body=%4dB entries=%d"
            % (r["name"], r["parent"], len(r["body"]), len(r["entries"]))
        )
