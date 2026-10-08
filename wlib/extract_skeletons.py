#!/usr/bin/env python3
"""
extract_skeletons.py  --  "skeletons first" pass.

Scans the naz, finds every *_Skeleton.model (ModelRes), decodes each into a rest-pose
table (name + parent + rest local pos + rest local quat, read from the file header per
docs/ENGINE_CONSTANTS.md), and writes skeleton_<family>.json. Run BEFORE rigging so
each character binds to its base skeleton.

Hierarchy (2026-08-17 docstring sync -- the code moved to parse_model_nodes in
v1.1.0): each node record carries its own parent field, read verbatim by
parse_model_nodes.parse(); node 0 is the file's unnamed root (the GamePivot
slot) and every parent is an index into the file's own node list.  Out-of-range
or self-referencing parents publish as -1 (root); there is no biped-name
guessing anywhere in this path.  (_explicit_parent_names below still implements
the older engine-ID name mapping for export_female_anims.)
"""

import sys, os, json, struct, argparse
import watchmen_extract as we
import parse_model_nodes as pmn
import skeleton_records as _sr


def _family(model_name):
    base = model_name.rsplit("/", 1)[-1].replace(".model", "")
    return base.replace("_Skeleton", "").replace("Skeleton", "").strip("_").lower() or base.lower()


def _header_order(header):
    """The order the header states (watchmen_extract.header_order), or None."""
    try:
        import watchmen_extract as _we
    except ImportError:
        return None
    return _we.header_order(header)


def _ordered_names(header, order=None):
    """Length-prefixed node names in file order. Console (X360/PS3) headers are
    big-endian, so the u32 namelen must be read BE; auto-detected when order is
    None (only the right order parses the small lengths)."""
    if order is None:
        order = _header_order(header)
    if order is None:
        order = "<" if len(_ordered_names(header, "<")) >= len(_ordered_names(header, ">")) else ">"
    occ = []
    i = 0
    N = len(header)
    while i + 4 <= N:
        n = struct.unpack_from(order + "I", header, i)[0]
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
    return [(lp, nm) for lp, nm in occ if "/" not in nm and nm != "ModelRes"]


def _explicit_parent_names(header):
    order = "<" if len(_ordered_names(header, "<")) >= len(_ordered_names(header, ">")) else ">"
    recs = _ordered_names(header, order)
    names = [nm for _, nm in recs]
    rest = [nm for nm in names if nm != "GamePivot"]
    engine_ids = ["GamePivot"] + rest  # id 0 = GamePivot (root)
    out = {}
    for lp, nm in recs:
        nlen = struct.unpack_from(order + "I", header, lp)[0]
        if lp + 4 + nlen + 8 > len(header):
            continue
        p = struct.unpack_from(order + "i", header, lp + 4 + nlen + 4)[0]
        if 0 <= p < len(engine_ids):
            pnm = engine_ids[p]
            out[nm] = None if pnm == nm else pnm  # GamePivot(p=0)->GamePivot==self->root
    return out


def _r6(v):
    return [round(float(x), 6) for x in v]


def _volume_json(v, scene):
    """One collision volume (skeleton_records.parse_volume_lists) as plain JSON."""
    out = {
        "type": v["kind"] or "type_%d" % v["type"],
        "scene": scene,  # which of the node's two lists (PhysX scene index)
        "pos": _r6(v["pos"]),  # centre in the bone's frame
        "quat_xyzw": _r6(v["quat"]),  # file order, NOT reordered
    }
    if v["type"] == 5:
        out["size"] = _r6(v["size"])
    elif v["type"] == 6:
        out["radius"] = round(float(v["radius"]), 6)
    elif v["type"] == 7:
        out["diameter"] = round(float(v["diameter"]), 6)
        out["height"] = round(float(v["height"]), 6)
    else:
        out["mode"] = int(v["mode"])
        out["verts"] = [_r6(p) for p in v["verts"]]
        out["indices"] = [int(i) for i in v["indices"]]
        out["cooked_blob_bytes"] = len(v["blob"])
    return out


def collision_volumes(header, names):
    """{node index: [volume json]} for the nodes of pmn.parse() that carry
    collision volumes.  `names` is parse()'s name list; records are aligned on
    the same true-node test parse() applies, and any disagreement yields {}
    (the volumes are optional, the hierarchy is not)."""
    try:
        order = pmn._detect_order(header)
        recs = [
            r
            for r in _sr.parse(header, order=order)
            if _sr.is_node_record(header, r["offset"], order)
        ]
    except Exception:
        return {}
    if [r["name"] for r in recs] != list(names[1:]):
        return {}
    out = {}
    for i, r in enumerate(recs, 1):
        vols = r["volumes"]
        if vols and (vols[0] or vols[1]):
            out[i] = [_volume_json(v, s) for s in (0, 1) for v in vols[s]]
    return out


def skeleton_from_header(header, family):
    """ModelRes header -> rest-pose table, engine-exact.

    2026-07-24: rebuilt on parse_model_nodes.parse().  This used to call
    decode_skeleton_model.decode(), which that module's own docstring marks
    SUPERSEDED for an off-by-one: the 28-byte [pos][quat] transform PRECEDES the
    name in a node record, so every bone was published carrying its SUCCESSOR's
    rest transform, the last bone of every skeleton was dropped entirely (the
    decoder needs a following name record to locate the tail), and `bone_count`
    was short by one.  Parents were also guessed from biped names instead of
    read from the record's own parent field.

    parse() reads the transform before the CURRENT name and takes the parent
    index from the record, so index 0 is the file's unnamed root (the GamePivot
    slot) and every `parent` is the file's own node index.  Byte order is
    auto-detected, so console (X360/PS3) headers work too.
    """
    names, pos, quat, parent = pmn.parse(header)
    vols = collision_volumes(header, names)
    bones = []
    for i, nm in enumerate(names):
        q = quat[i]
        pa = int(parent[i])
        bones.append(
            {
                "name": nm,
                "parent": pa if (0 <= pa < len(names) and pa != i) else -1,
                "rest_pos": [round(float(x), 6) for x in pos[i]],
                # file order is XYZW; published as WXYZ for backwards compatibility
                "rest_quat_wxyz": [
                    round(float(q[3]), 6),
                    round(float(q[0]), 6),
                    round(float(q[1]), 6),
                    round(float(q[2]), 6),
                ],
            }
        )
        if i in vols:
            # optional (2026-10): present only on bones that carry volumes
            bones[-1]["collision_volumes"] = vols[i]
    return {
        "family": family,
        "bone_count": len(names),
        "source": "ModelRes header (file), parse_model_nodes",
        "note": (
            "node 0 is the file's unnamed root (GamePivot slot); rest = the 28 bytes "
            "BEFORE each name ([pos vec3][quat vec4 xyzw], published wxyz); parent = "
            "the record's own parent field, indexing this list"
        ),
        "bones": bones,
    }


def _tree_stats(sk):
    bones = sk["bones"]
    par = [b["parent"] for b in bones]
    roots = sum(1 for p in par if p < 0)

    def depth(i):
        seen = set()
        d = 0
        while 0 <= par[i] < len(par) and i not in seen:
            seen.add(i)
            i = par[i]
            d += 1
            if d > 80:
                return -1
        return d

    return roots, max(depth(i) for i in range(len(bones)))


def collect(naz):
    entries = list(we.naz_entries(naz))
    blocks = {}
    for e in entries:
        low = e.name.lower()
        if low.endswith(".block_h_z") or low.endswith(".block_s_z"):
            stem = e.name[: -len("_h_z")] if low.endswith("_h_z") else e.name[: -len("_s_z")]
            blocks.setdefault(stem, {})["h" if low.endswith("_h_z") else "s"] = we.naz_read(naz, e)
    out = {}
    for stem, hs in sorted(blocks.items()):
        if "h" not in hs:
            continue
        try:
            it = list(we.extract_block(hs["h"], hs.get("s")))
        except Exception:
            continue
        for e, header, stream in it:
            if e.name.lower().endswith("skeleton.model"):
                fam = _family(e.name)
                if fam in out:
                    continue
                try:
                    sk = skeleton_from_header(header, fam)
                    if sk["bone_count"] >= 20:
                        out[fam] = sk
                except Exception as ex:
                    print("  skeleton %s: %s" % (fam, ex), file=sys.stderr)
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("naz")
    ap.add_argument("-o", "--out", default="skeletons")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    sk = collect(a.naz)
    index = {}
    for fam, s in sorted(sk.items()):
        path = os.path.join(a.out, "skeleton_%s.json" % fam)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(s, fh, indent=1)
        roots, depth = _tree_stats(s)
        index[fam] = {
            "file": os.path.basename(path),
            "bones": s["bone_count"],
            "roots": roots,
            "max_depth": depth,
        }
        print(
            "  skeleton_%-12s %3d bones | roots %d depth %d -> %s"
            % (fam, s["bone_count"], roots, depth, path)
        )
    with open(os.path.join(a.out, "index.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(index, fh, indent=1)
    print("wrote %d skeletons + index.json to %s" % (len(sk), a.out))


if __name__ == "__main__":
    main(sys.argv[1:])
