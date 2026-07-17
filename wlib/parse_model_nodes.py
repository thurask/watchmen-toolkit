#!/usr/bin/env python3
"""parse_model_nodes.py — ENGINE-EXACT skeleton rest pose from a ModelRes header.

Engine ground truth (FUN_00545927 = Node::Deserialize, KapowMultiDEDRM.exe):
each node record is
    [pos f32x3][quat f32x4 XYZW][u32 namelen][name..\0][u32 f1][u32 parent][aux ...]
The old decode_skeleton_model.py attributed the 28-byte transform to the PREVIOUS
name (off-by-one) and guessed parents from biped names. This parser anchors on the
length-prefixed names and takes the 28 bytes immediately BEFORE each name, plus the
parent index from the record itself.

Node 0 is the unnamed root (empty name, parent -1) == GamePivot slot.
"""

import struct, sys, numpy as np


def _detect_order(mb):
    """'<' PC / '>' X360+PS3.  Pick the order that finds more length-prefixed
    node names (the console header is byte-flipped; namelen only parses small
    in the right order)."""
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


def parse(mb, order=None):
    """-> names(list), pos (N,3), quat (N,4 xyzw), parent (N,) int (node indices, -1 root).
    order '<' PC / '>' console; auto-detected when None (record layout is the
    same on all platforms, only the f32/u32 fields are byte-flipped)."""
    if order is None:
        order = _detect_order(mb)
    f4 = order + "f4"
    occ = [(o, nm) for o, nm in _names(mb, order) if "/" not in nm and nm != "ModelRes"]
    if not occ:
        raise ValueError("no node names")
    # node-0 anchor: count u32 sits 4+12+16+4+1 bytes before first named node?  Instead:
    # first named node's record starts at occ[0][0]-28; node0's record is the 33 bytes
    # before that: [pos 12][quat 16][len=1][\0][u32][u32 -1]... locate by parent -1 check.
    nodes = []
    first = occ[0][0] - 28
    # node0: transform ends at rec0_end; rec0 = [pos][quat][1]["\0"][u32][u32]
    n0 = first - 0x15  # 12+16+4+1+4+4 = 41 = 0x29? conservative: find count field
    # count u32 immediately precedes node0 pos
    # search back for plausible count (20..200)
    cn = None
    for back in range(first - 41 - 8, first - 41 + 9):
        if back < 0:
            continue
        c = struct.unpack_from("<I", mb, back)[0]
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
    for o, nm in occ:
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
            continue
        nl = struct.unpack_from(order + "I", mb, o)[0]
        f1, par = struct.unpack_from(order + "Ii", mb, o + 4 + nl)
        names.append(nm)
        pos.append(p)
        quat.append(q)
        parent.append(par)
    # parent values index the true node array (0 = root)
    n = len(names)
    parent = [pa if -1 <= pa < n else -1 for pa in parent]
    return names, np.array(pos), np.array(quat), np.array(parent)


if __name__ == "__main__":
    mb = open(sys.argv[1], "rb").read()
    names, pos, quat, parent = parse(mb)
    print(len(names), "nodes")
    for i, (nm, p, q, pa) in enumerate(zip(names, pos, quat, parent)):
        print("%2d %-22s par=%3d pos=%s quat=%s" % (i, nm, pa, np.round(p, 4), np.round(q, 4)))


# ---------------------------------------------------------------------------
# 2026-07-09p: node AUX region layout (bytes between a node's name and the
# next node's transform), reversed from Node::Deserialize 0x545927 + corpus
# tiling (exact on all skeleton/prop nodes; 33.4% of ALL node regions incl.
# mesh models):
#   [u32 f1=0][u32 parent]
#   [u32 cnt34]  per outer: [u32 innerCnt] ; innerCnt>0 only on mesh nodes
#                (inner item 0x2c: [str][u32 n][n u32 ids][u8][u8][u32][u8] =
#                 material/palette binding, NOT fully tiled here)
#   [u32 cnt40]  >0 only on mesh nodes: meshbuffer descriptors
#                ([vec3 bboxmin][vec3 bboxmax][u8 hasBuf][meshbuf...], deep)
#   [u8 0]
#   [u32 njoint] per joint (reader 0x545cbe..): 48B + blob:
#       [u32 type(4/5/6/7)][u32 0][f32 pos x3][f32 a][f32 a']
#       [f32 quat x4 xyzw]  (2026-07-12c: a/a' BEFORE quat; unit-norm proof)
#       [u32 blobLen][blob]
#       type7 blobLen=0 (508/508); type6 (UpperArm/Head twist) blobLen=7;
#       types 4/5 blob layout unknown (arm/hand/pelvis special joints).
#   [u32 0][u32 0] terminator
# These joint records are the file-side EmbeddedJointNodes (jiggle/ragdoll
# D6 joints, see 2026-07-09i/j PhysX findings).
def parse_node_aux(mb, start, end):
    """Parse one node aux region [start,end). Returns dict or None if the
    region contains mesh data / unknown joint blobs (not fully tiled)."""
    import struct as _s

    p = start

    def u32():
        nonlocal p
        v = _s.unpack_from("<I", mb, p)[0]
        p += 4
        return v

    try:
        f1, parent, c34 = u32(), u32(), u32()
        if c34 > 64:
            return None
        if any(u32() for _ in range(c34)):
            return None  # mesh node
        if u32():
            return None  # cnt40 mesh node
        p += 1
        nj = u32()
        if nj > 200:
            return None
        joints = []
        for _ in range(nj):
            t, z = u32(), u32()
            import numpy as _np

            pos = _np.frombuffer(mb, "<f4", 3, p)
            p += 12
            # 2026-07-12c FIELD-ORDER FIX: the two scalars precede the quat.
            # True layout: [pos x3][f32 a][f32 a'][quat x4 xyzw] -- verified
            # |q|^2 = 1.0000 on all 24 female-skeleton joints (old order gave
            # non-unit "quats").  a/a' = per-joint scalar pair (limit/offset?).
            a, a2 = _s.unpack_from("<2f", mb, p)
            p += 8
            quat = _np.frombuffer(mb, "<f4", 4, p)
            p += 16
            bl = u32()
            if bl > 4096:
                return None
            blob = mb[p : p + bl]
            p += bl
            joints.append(dict(type=t, pos=pos.copy(), quat=quat.copy(), a=a, a2=a2, blob=blob))
        if u32() or u32() or p != end:
            return None
        return dict(f1=f1, parent=parent, joints=joints)
    except (_s.error, ValueError):
        return None
