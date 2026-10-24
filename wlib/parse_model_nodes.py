#!/usr/bin/env python3
"""parse_model_nodes.py — ENGINE-EXACT skeleton rest pose from a ModelRes header.

Engine ground truth (FUN_00545927 = Node::Deserialize, game executable):
each node record is
    [pos f32x3][quat f32x4 XYZW][u32 namelen][name..\0][u32 f1][u32 parent][aux ...]
This parser anchors on the length-prefixed names and takes the 28 bytes immediately
BEFORE each name (the transform belongs to the name that follows it, not to the one
before), plus the parent index from the record itself; parents are never guessed from
biped names.

Node 0 is the unnamed root (empty name, parent -1) == GamePivot slot.
"""

import os
import struct
import sys
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))


from wutil import (  # noqa: E402  (one copy, in wlib/wutil.py)
    order_name,
    qmat_xyzw,
    read_bytes as _read_bytes,
)


def _detect_order(mb):
    """'<' PC / '>' X360+PS3: the order the header states (its opening class-name
    length, watchmen_extract.header_order); when it does not say, the order that
    finds more length-prefixed node names."""
    try:  # the header states its order (5,490 of 5,490 models of the six sets)
        import watchmen_extract as _we

        o = _we.header_order(mb)
    except ImportError:
        o = None
    if o is not None:
        return o
    return "<" if len(_names(mb, "<")) >= len(_names(mb, ">")) else ">"


def _names(mb, order="<"):
    occ = []
    i = 0
    N = len(mb)
    while i + 4 <= N:
        n = struct.unpack_from(order + "I", mb, i)[0]
        if 2 <= n <= 40 and i + 4 + n <= N:
            s = mb[i + 4 : i + 4 + n]
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


def parse_header_driven(mb):
    """Node table straight from the engine-exact ModelRes header walk
    (watchmen_extract.parse_model_header: FUN_00547006 -> FUN_00545927), or None
    when the blob is not a little-endian header of either layout (Part 2, or the
    stand-alone Part 1 build).  Same return shape as parse(); every
    part of the file is a node, so parent indices can never be misaligned."""
    try:
        import watchmen_extract as _we
    except ImportError:
        if _HERE not in sys.path:
            sys.path.append(_HERE)  # append, never insert(0)
        import watchmen_extract as _we
    M = _we.parse_model_header(bytes(mb), "<")
    if not M or not M["parts"]:
        return None
    parts = M["parts"]
    n = len(parts)
    names = [P["name"] or ("(root)" if i == 0 else "(node%d)" % i) for i, P in enumerate(parts)]
    pos = np.array([P["pos"] for P in parts], dtype=np.float32).astype(np.float64)
    quat = np.array([P["quat"] for P in parts], dtype=np.float32).astype(np.float64)
    parent = [P["parent"] - (1 << 32) if P["parent"] >= (1 << 31) else P["parent"] for P in parts]
    parent = [pa if -1 <= pa < n else -1 for pa in parent]
    return names, pos, quat, np.array(parent)


def parse(mb, order=None):
    """-> names(list), pos (N,3), quat (N,4 xyzw), parent (N,) int (node indices, -1 root).
    order '<' PC / '>' console; auto-detected when None (record layout is the
    same on all platforms, only the f32/u32 fields are byte-flipped).

    PC headers are read header-driven first (parse_header_driven); the name-anchored
    scan below remains for console and Part 1 blobs."""
    if order in (None, "<"):
        hd = parse_header_driven(mb)
        if hd is not None:
            return hd
    if order is None:
        order = _detect_order(mb)
    f4 = order + "f4"
    occ = [(o, nm) for o, nm in _names(mb, order) if "/" not in nm and nm != "ModelRes"]
    if not occ:
        ex = ValueError("no node names")
        ex.add_note(f"parse_model_nodes: {len(mb)}-byte header read {order_name(order)}")
        raise ex
    # node-0 anchor: count u32 sits 4+12+16+4+1 bytes before first named node?  Instead:
    # first named node's record starts at occ[0][0]-28; node0's record is the 33 bytes
    # before that: [pos 12][quat 16][len=1][\0][u32][u32 -1]... locate by parent -1 check.
    # The header's node COUNT sits just before node 0's transform.  We recover it
    # so a record dropped by the validity filter below can be DETECTED: parent
    # values index the file's node array, so a silently dropped node shifts every
    # later parent by one and corrupts the whole hierarchy without any error.
    first = occ[0][0] - 28
    cn = None
    for back in range(first - 41 - 8, first - 41 + 9):
        if back < 0 or back + 4 > len(mb):
            continue
        c = struct.unpack_from(order + "I", mb, back)[0]
        if 10 <= c <= 500 and len(occ) + 1 in (c, c + 1):
            cn = (back, c)
            break
    # keep only TRUE node records: the 16 bytes before the name must be a unit
    # quaternion (mesh/material/pivot name tables that precede the node array
    # fail this test).  Node 0 is the unnamed root (identity).
    names = ["(root)"]
    pos = [np.zeros(3)]
    quat = [np.array([0, 0, 0, 1.0])]
    parent = [-1]
    dropped = []
    for o, nm in occ:
        if o < 28 or o + 4 > len(mb):
            dropped.append(nm)
            continue
        p = np.frombuffer(mb, dtype=f4, count=3, offset=o - 28).astype(np.float64)
        q = np.frombuffer(mb, dtype=f4, count=4, offset=o - 16).astype(
            np.float64
        )  # f64: garbage f4 candidates overflow on q*q (harmless RuntimeWarning)
        if (
            (not np.isfinite(q).all())
            or abs(float((q * q).sum()) - 1.0) > 1e-3
            or not np.isfinite(p).all()
            or np.abs(p).max() > 100
        ):
            dropped.append(nm)
            continue
        nl = struct.unpack_from(order + "I", mb, o)[0]
        if o + 4 + nl + 8 > len(mb):
            dropped.append(nm)
            continue
        f1, par = struct.unpack_from(order + "Ii", mb, o + 4 + nl)
        names.append(nm)
        pos.append(p)
        quat.append(q)
        parent.append(par)
    # parent values index the true node array (0 = root).  If the file told us how
    # many nodes it has and a different number was kept, the indices below do not
    # line up -- fail loudly rather than emit a plausible but wrong hierarchy.
    n = len(names)
    if cn is not None and n != cn[1] and (n - 1) != cn[1]:
        ex = ValueError(
            "node count mismatch: header says %d, parsed %d (dropped %r) -- "
            "parent indices would be misaligned" % (cn[1], n, dropped[:8])
        )
        ex.add_note(
            f"parse_model_nodes: node count u32 at header offset 0x{cn[0]:X} of {len(mb)} "
            f"bytes, {order_name(order)}"
        )
        raise ex
    parent = [pa if -1 <= pa < n else -1 for pa in parent]
    return names, np.array(pos), np.array(quat), np.array(parent)


def qmat_wxyz(q):
    """WXYZ quaternion -> 3x3 rotation matrix."""
    w, x, y, z = q
    nn = (w * w + x * x + y * y + z * z) ** 0.5 or 1.0
    return qmat_xyzw((x / nn, y / nn, z / nn, w / nn))


def rest_by_name(mb, order=None):
    """-> {name: {'pos': (3,), 'quat_wxyz': (4,)}} for every named node.

    Convenience view over parse() for callers that key by bone name; each
    28-byte transform belongs to the name that FOLLOWS it, and the last node
    is kept."""
    names, pos, quat, _par = parse(mb, order)
    out = {}
    for i, nm in enumerate(names):
        if i == 0:
            continue  # synthetic unnamed root
        q = quat[i]
        out[nm] = {"pos": pos[i], "quat_wxyz": np.array([q[3], q[0], q[1], q[2]])}
    return out


if __name__ == "__main__":
    mb = _read_bytes(sys.argv[1])
    names, pos, quat, parent = parse(mb)
    print(len(names), "nodes")
    for i, (nm, p, q, pa) in enumerate(zip(names, pos, quat, parent)):
        print("%2d %-22s par=%3d pos=%s quat=%s" % (i, nm, pa, np.round(p, 4), np.round(q, 4)))


# ---------------------------------------------------------------------------
# Node AUX region = the bytes between a node's name and the next node's
# transform (Node::Deserialize 0x545927):
#   [u32 f1][u32 parent]
#   [u32 nLod] nLod x [u32 nSub][nSub x submesh]      nSub > 0 only on mesh nodes
#   [u32 nGroup] nGroup x [u32 n][n x shadow hull]    groups may be empty (n = 0)
#   [u8 hasOccluder] (MeshBuffer)
#   [u32 n0] n0 x volume   collision shapes, PhysX scene 0
#   [u32 n1] n1 x volume   collision shapes, PhysX scene 1
#   [u32 n2] n2 x surface  particle emission meshes (MeshParticleData, 0x561d1c):
#                          29 in 19 of the 738 distinct staged PC Part 2 models
# The volume records are read by skeleton_records.parse_node_tail (box 52 B,
# sphere 44 B, capsule 48 B, mesh variable).  They are not fixed 48-byte "joints"
# [type][0][pos][a][a'][quat]: that reading only tiles capsule-only nodes with an
# empty second list and puts the capsule's (diameter, height, x) in `pos`.
def _skeleton_records():
    try:
        import skeleton_records as _sr
    except ImportError:
        if _HERE not in sys.path:
            sys.path.append(_HERE)  # append, never insert(0)
        import skeleton_records as _sr
    return _sr


def parse_node_aux(mb, start, end, order="<", meshes=False):
    """Parse one node aux region [start, end).  Returns None when the node
    carries mesh data (unless meshes=True: skeleton_records.parse_node_tail) or
    the bytes do not tile the region exactly, else
        dict(f1, parent, joints, volumes, surfaces, has_mesh)
    surfaces particle emission meshes: [{class "MeshParticleData", tris
             [{normal, area_weight, material_id}], verts, indices, weight_sum,
             weight_is_area}]
    volumes  [scene 0 list, scene 1 list] as skeleton_records.parse_node_tail
             returns them (type, kind, base, pos, quat, blob + size | radius |
             diameter, height | mode, verts, indices)
    joints   the same volumes flattened in file order under the flat keys
             type, pos (3,) f32, quat (4,) f32 xyzw, blob, scene,
             and a / a2 = a capsule's diameter / height (None for other types)
    order: '<' PC (default) / '>' X360+PS3."""
    tail = _skeleton_records().parse_node_tail(mb, start, end, order, meshes=meshes)
    if tail is None:
        return None
    joints = []
    for scene, vols in enumerate(tail["volumes"]):
        for v in vols:
            j = dict(v)
            j["scene"] = scene
            j["pos"] = np.array(v["pos"], dtype=np.float32)
            j["quat"] = np.array(v["quat"], dtype=np.float32)
            j["a"], j["a2"] = (v["diameter"], v["height"]) if v["type"] == 7 else (None, None)
            joints.append(j)
    return dict(
        f1=tail["f1"],
        parent=tail["parent"] & 0xFFFFFFFF,
        joints=joints,
        volumes=tail["volumes"],
        surfaces=tail["surfaces"],
        has_mesh=tail["has_mesh"],
    )


def model_physics(mb, order="<"):
    """Header-driven read of everything physical in a ModelRes header, in either
    header layout (watchmen_extract.MODEL_LAYOUTS: Part 2 / PS3 Part 1, and the
    stand-alone Part 1 build): every node with its two collision-volume lists
    (Node::Deserialize 0x545927) and the articulated-body section that follows
    the node array (0x51e1ad).  Works on models with meshes too (the
    name-anchored scan of skeleton_records only tiles mesh-free nodes).
    -> dict(nodes=[{name, parent, pos, quat (xyzw as stored), volumes: [scene 0
    list, scene 1 list], surfaces: [particle emission meshes, see
    parse_node_aux]}], articulated_body=
    skeleton_records.parse_articulated_body(...), end, layout) or None when the
    blob follows neither layout."""
    try:
        import watchmen_extract as _we
    except ImportError:
        if _HERE not in sys.path:
            sys.path.append(_HERE)  # append, never insert(0)
        import watchmen_extract as _we
    _sr = _skeleton_records()
    M = _we.parse_model_header(mb, order)
    if M is None:
        return None
    try:
        nodes = []
        end = M["end"]
        for P in M["parts"]:
            par = P["parent"]
            nd = {"pos": P["pos"], "quat": P["quat"], "name": P["name"]}
            nd["parent"] = par - (1 << 32) if par >= (1 << 31) else par
            nd["volumes"], nd["surfaces"], end = _sr.parse_volume_lists(
                mb, P["lists_offset"], order
            )
            nodes.append(nd)
        if end != M["end"]:
            return None
        n = len(nodes)
        for nd in nodes:
            if not -1 <= nd["parent"] < n:
                nd["parent"] = -1
        ab = _sr.parse_articulated_body(mb, M["end"], order)
    except (ValueError, struct.error, IndexError):
        return None
    return dict(nodes=nodes, articulated_body=ab, end=ab["end"], layout=M["layout"])


def model_tail(mb, order="<"):
    """What a ModelRes header holds after its articulated-body section, read as
    ModelRes::Read 0x547006 reads it:
        [string animation path]        only when the header's second bool is set
                                       (has_animation; read by 0x54292c: curtains,
                                       foliage and other unskinned animated models)
        [u32 n] n x {f32, string name, [u32 m] m x {u32 target, f32 key}}
                                       the morph-channel list (ModelRes+0x134,
                                       36-byte elements; writer 0x543e10)
    A channel's weight w > 0 picks the last entry whose key <= w and drives that
    target by (w - previous key) / (key - previous key), the previous key of the
    first entry being 0 (0x4b5b31); `Character.GetMorphChannelIdx` finds a channel by
    the hash of its name (0x4b38b6).  The leading f32 of a channel is not read there.
    -> dict(animation=str | None, morph_channels=[{"f0", "name", "targets":
    [[target, key]]}], end) with end == len(mb), or None when the tail does not
    read to the end of the blob."""
    try:
        import watchmen_extract as _we
    except ImportError:
        if _HERE not in sys.path:
            sys.path.append(_HERE)  # append, never insert(0)
        import watchmen_extract as _we
    M = _we.parse_model_header(mb, order)
    phys = model_physics(mb, order)
    if M is None or phys is None:
        return None
    try:
        r = _we._Rd(mb, order)
        r.p = phys["end"]
        animation = r.string() if M.get("has_animation") else None
        channels = []
        for _ in range(r.count(12)):
            (f0,) = r.floats(1)
            name = r.string()
            m = r.count(8)
            targets = []
            for _ in range(m):
                t = r.u32()
                (k,) = r.floats(1)
                targets.append([t, k])
            channels.append({"f0": f0, "name": name, "targets": targets})
    except (ValueError, struct.error, IndexError):
        return None
    if r.p != len(mb):
        return None
    return dict(animation=animation, morph_channels=channels, end=r.p)
