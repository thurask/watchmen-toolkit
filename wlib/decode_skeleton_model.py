#!/usr/bin/env python3
"""SUPERSEDED (2026-07-08) by parse_model_nodes.py + build_bind_file.py.
This module attributed each node's 28-byte [pos][quat] to the WRONG name
(off-by-one: the transform PRECEDES the name in the record, engine
FUN_00545927) and guessed parents from biped names instead of reading the
record's parent field.  Kept for history only.


decode_skeleton_model.py  --  Decode a skeleton/character ModelRes HEADER into a
per-bone rest pose (name, parent, local position + local quaternion), straight from
the file. NO apitrace, NO hand-authored json -- works for every skeleton.

THE FINDING (from Ghidra FUN_00545927 / FUN_00547006, KapowMultiDEDRM.exe):
  The model loader reads an array of NODES. Each node record, in the ModelRes header,
  ENDS with its local rest transform:
        [u32 namelen][name\\0] ... <other fields> ... [pos vec3 12B][quat vec4 16B]
  and the NEXT node's [u32 namelen] follows immediately. The reader is:
        FUN_0043552a -> reads 12 bytes (vec3 position)  -> node+0x10
        FUN_0043553c -> reads 16 bytes (vec4 quaternion)-> node+0x1c
  i.e. the per-bone rest transform is stored as POSITION + QUATERNION (NOT a 3x3
  matrix -- which is why earlier matrix-scans missed it). Quaternion order in the FILE is XYZW
  (verified 2026-07-01 against clip t3/t1 cross-checks; the earlier WXYZ claim was wrong —
  this module now converts to wxyz for its output dict key).

  So the rest skeleton = each bone's [pos, quat] composed up the biped name hierarchy.
  Decodes to a clean T-pose biped (47/47 unit quats; 1.4 m tall, 1.0 m armspan, Z-up).

USAGE:
  python decode_skeleton_model.py Female_Skeleton.model.header [--json out.json]
  # or feed a raw inflated ModelRes header (the *.modelres_h_z inflated, or the
  #  block-extracted header). Reads names + tail pos/quat per node.

This is the generic replacement for skeleton_female_biped.json: run it on each of the
5 skeleton resources in the naz (Female/Medium/Large/Small/Large_Gimp) to get all rest
poses, then FK any of the 2047 .animation clips on the matching skeleton.
"""

import sys, struct, json, argparse, numpy as np


def biped_parent(n, names_set):
    P = {
        "Bip": "GamePivot",
        "Pelvis": "Bip",
        "Spine": "Pelvis",
        "Spine1": "Spine",
        "Spine2": "Spine1",
        "Neck": "Spine2",
        "Head": "Neck",
    }
    if n in P:
        return P[n]
    if n == "GamePivot":
        return None
    if n in ("BreastL", "BreastR"):
        return "Spine2"
    if n == "interact":
        return "Bip"
    for s in ("L", "R"):
        sp = s + " "
        if n == sp + "Clavicle":
            return "Spine2"
        if n == sp + "UpperArm":
            return sp + "Clavicle"
        if n == sp + "Forearm":
            return sp + "UpperArm"
        if n == sp + "Hand":
            return sp + "Forearm"
        if n in (sp + "ForeTwist", sp + "ForeTwist1"):
            return sp + "Forearm"
        if n in (s + "UpArmTwist", s + "UpArmTwist1"):
            return sp + "UpperArm"
        if n.startswith("Attach " + s) or n.startswith("Bip02 Attach " + s):
            return sp + "Hand"
        if n.startswith(sp + "Finger"):
            if n[-1] == "1" and n[-2].isdigit():
                return n[:-1]
            return sp + "Hand"
        if n == sp + "Thigh":
            return "Pelvis"
        if n == sp + "Calf":
            return sp + "Thigh"
        if n == sp + "Foot":
            return sp + "Calf"
        if n == sp + "Toe0":
            return sp + "Foot"
    return "Bip"


def node_records(header):
    """Ordered length-prefixed name records in the header: list of (lenpos, name)."""
    occ = []
    i = 0
    N = len(header)
    while i + 4 <= N:
        n = struct.unpack_from("<I", header, i)[0]
        if 2 <= n <= 40 and i + 4 + n <= N:
            s = header[i + 4 : i + 4 + n]
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


def decode(header):
    """-> dict name -> {'pos':(3,), 'quat_wxyz':(4,)} for every node that carries a
    tail [pos vec3][quat vec4] (unit quaternion) before the next node's name."""
    occ = [(lp, nm) for lp, nm in node_records(header) if "/" not in nm and nm != "ModelRes"]
    out = {}
    order = []
    for k, (lp, nm) in enumerate(occ):
        nxt = occ[k + 1][0] if k + 1 < len(occ) else None
        if nxt is None or nxt - 28 < lp or nxt > len(header):
            continue
        pos = np.array(struct.unpack_from("<3f", header, nxt - 28))
        _q = np.array(
            struct.unpack_from("<4f", header, nxt - 16)
        )  # stored XYZW (verified 2026-07-01)
        quat = _q[[3, 0, 1, 2]]  # expose as wxyz for downstream compatibility
        if not (0.96 < float(np.dot(quat, quat)) < 1.04):
            continue  # tail isn't a unit quat -> not a transform-bearing node
        out[nm] = {"pos": pos, "quat_wxyz": quat}
        order.append(nm)
    return out, order


def qmat_wxyz(q):
    w, x, y, z = q
    n = (w * w + x * x + y * y + z * z) ** 0.5 or 1
    w, x, y, z = w / n, x / n, y / n, z / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def world_positions(nodes, order):
    ns = set(order)
    par = {nm: biped_parent(nm, ns) for nm in order}

    def dep(nm):
        d = 0
        p = par.get(nm)
        while p:
            d += 1
            p = par.get(p)
        return d

    W = {}
    for nm in sorted(order, key=dep):
        L = np.eye(4)
        L[:3, :3] = qmat_wxyz(nodes[nm]["quat_wxyz"])
        L[:3, 3] = nodes[nm]["pos"]
        p = par.get(nm)
        W[nm] = (W[p] @ L) if p in W else L
    return W, par


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "header", help="ModelRes header file (skeleton .model header / inflated modelres_h_z)"
    )
    ap.add_argument("--json", help="write skeleton json here")
    ap.add_argument("--family", default="biped")
    a = ap.parse_args(argv)
    header = open(a.header, "rb").read()
    nodes, order = decode(header)
    W, par = world_positions(nodes, order)
    P = np.array([W[n][:3, 3] for n in order])
    ext = P.max(0) - P.min(0)
    print(
        "decoded %d bones with rest transform; world extent (engine xyz): %s span %.2f m"
        % (len(order), np.round(ext, 3).tolist(), float(np.abs(ext).max()))
    )
    nunit = sum(
        1
        for n in order
        if 0.98 < float(np.dot(nodes[n]["quat_wxyz"], nodes[n]["quat_wxyz"])) < 1.02
    )
    print("unit quaternions: %d/%d" % (nunit, len(order)))
    if a.json:
        bones = []
        idx = {n: i for i, n in enumerate(order)}
        for n in order:
            p = par.get(n)
            bones.append(
                {
                    "name": n,
                    "parent": idx.get(p, -1) if p else -1,
                    "rest_pos": [round(float(x), 6) for x in nodes[n]["pos"]],
                    "rest_quat_wxyz": [round(float(x), 6) for x in nodes[n]["quat_wxyz"]],
                }
            )
        json.dump(
            {
                "family": a.family,
                "bone_count": len(order),
                "note": "rest transform decoded from ModelRes header tail [pos vec3][quat wxyz vec4]",
                "bones": bones,
            },
            open(a.json, "w"),
            indent=1,
        )
        print("wrote", a.json)


if __name__ == "__main__":
    main(sys.argv[1:])
