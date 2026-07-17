#!/usr/bin/env python3
# Human-readable JSON emitters for Kapow property/sequence/fragment assets.
# Used by watchmen_extract.py (extracted/*.json) and standalone:
#   python3 kapow_json.py FILE            (prints JSON)
import json, struct, re, math, bisect
import kapow_props, decode_sequence

PROPBAG_EXTS = (".particle", ".grass", ".detailmesh", ".pb", ".terrain")
POSK = 0x2F0823C4
ROTK = 0x51172879

NAMEK = 0x7282B2A2  # kapow keyHash of NAME (stored in platform byte order)


def fragment_json(d, bo="<"):
    # 1) node-type tree (schema table)
    nodes = []
    p = 0
    while p < len(d):
        e = d.find(b"\x00", p)
        if e < 0:
            break
        s = d[p:e]
        if (
            len(s) >= 3
            and all(32 <= c < 127 for c in s)
            and (s.endswith(b")") or s.startswith(b"{"))
        ):
            q = e + 1
            while q < len(d) and d[q] == 0 and q - (e + 1) < 8:
                q += 1
            if q + 12 <= len(d):
                mark, h, depth = struct.unpack_from(bo + "III", d, q)
                if depth < 40 and (mark >= 0xFFFFFFF0 or 0x10000 < mark < 0xFFFFFF00):
                    nodes.append({"depth": depth, "type": s.decode("latin1"), "hash": "%08x" % h})
                    p = q + 12
                    continue
        p += 1

    # 2) named instances + transforms (instance stream)
    def f(o):
        return struct.unpack_from(bo + "f", d, o)[0]

    def u(o):
        return struct.unpack_from(bo + "I", d, o)[0]

    heads = []
    for m in re.finditer(re.escape(struct.pack(bo + "I", NAMEK)), d):
        o = m.start()
        if o < 12:
            continue
        wc = u(o + 4)
        if 1 <= wc <= 30:
            nm = d[o + 8 : o + 8 + wc * 4].split(b"\x00")[0].decode("latin1", "replace")
            heads.append((o - 8, nm))
    heads.sort()
    starts = [h[0] for h in heads]

    def owner(off):
        i = bisect.bisect_right(starts, off) - 1
        return heads[i][1] if i >= 0 else None

    tr = []
    for m in re.finditer(re.escape(struct.pack(bo + "I", POSK)), d):
        o = m.start() + 4
        x, y, z = f(o), f(o + 4), f(o + 8)
        if not all(math.isfinite(v) and abs(v) < 5000 for v in (x, y, z)):
            continue
        rec = {"name": owner(m.start()), "pos": [round(x, 3), round(y, 3), round(z, 3)]}
        if o + 16 <= len(d) and u(o + 12) == ROTK:
            qq = [f(o + 16), f(o + 20), f(o + 24), f(o + 28)]
            if 0.98 < sum(c * c for c in qq) < 1.02:
                rec["quat"] = [round(c, 4) for c in qq]
                rec["yaw_deg"] = round(math.degrees(2 * math.atan2(qq[1], qq[3])), 1)
        tr.append(rec)
    # 3) ALL string properties ([u32 keyHash][u32 wordcount][wc*4 chars]) -> resource refs etc.
    keynames = kapow_props.namedict()
    strs = []
    p2 = 0
    while p2 + 12 <= len(d):
        wc = u(p2 + 4)
        if 1 <= wc <= 200 and p2 + 8 + wc * 4 <= len(d):
            raw = d[p2 + 8 : p2 + 8 + wc * 4]
            txt = raw.split(b"\x00")[0]
            # must fill most of the field and be printable
            if (
                len(txt) >= 3
                and len(txt) >= (wc - 1) * 4 - 3
                and all(32 <= c < 127 for c in txt)
                and raw[len(txt) :].strip(b"\x00") == b""
            ):
                key = u(p2)
                kn = keynames.get(key)
                if kn is None:
                    t = txt.decode("latin1").lower()
                    if t.endswith(".model"):
                        kn = "model_ref"
                    elif t.endswith(".bmp") or t.endswith(".tga"):
                        kn = "texture_ref"
                    elif ".bmp," in t or ".tga," in t:
                        kn = "texture_table"
                    elif t.endswith(".fragment"):
                        kn = "fragment_ref"
                    elif t.endswith((".wav", ".ogg")):
                        kn = "sound_ref"
                    elif t.endswith((".tnt", ".script")):
                        kn = "script_ref"
                    elif t.endswith((".animation", ".animationgraph")):
                        kn = "animation_ref"
                    elif t.endswith((".particle", ".sequence", ".pb")):
                        kn = "asset_ref"
                    else:
                        kn = "str_%08x" % key
                strs.append((p2, kn, txt.decode("latin1")))
                p2 += 8 + wc * 4
                continue
        p2 += 1
    # robust resource-ref sweep (regex, immune to stream-walk desync)
    seen_off = {st[0] for st in strs}
    for m in re.finditer(
        rb"/[ -~]{4,150}?\.(?:model|bmp|tga|fragment|wav|ogg|tnt|script|animation|animationgraph|sequence|particle|pb|terrain|grass|detailmesh)\x00",
        d,
        re.I,
    ):
        off = m.start()
        # avoid duplicating records the walk already captured (same string start)
        if any(abs(off - (so + 8)) < 3 for so in seen_off):
            pass
        txt = m.group()[:-1].decode("latin1")
        t = txt.lower()
        if t.endswith(".model"):
            kn = "model_ref"
        elif t.endswith((".bmp", ".tga")):
            kn = "texture_ref"
        elif t.endswith(".fragment"):
            kn = "fragment_ref"
        elif t.endswith((".wav", ".ogg")):
            kn = "sound_ref"
        elif t.endswith((".tnt", ".script")):
            kn = "script_ref"
        elif t.endswith((".animation", ".animationgraph")):
            kn = "animation_ref"
        else:
            kn = "asset_ref"
        strs.append((off, kn, txt))
    # dedupe (offset,value)
    strs = sorted({(o, k, v) for o, k, v in strs})
    # group per owning named instance
    inst = {}
    order = []
    for off, keyn, val in strs:
        own = owner(off) or "(preamble)"
        if own not in inst:
            inst[own] = {}
            order.append(own)
        if keyn == "name" and val == own:
            continue
        lst = inst[own].setdefault(keyn, [])
        if val not in lst:
            lst.append(val)
    for rec in tr:
        own = rec.get("name") or "(preamble)"
        if own not in inst:
            inst[own] = {}
            order.append(own)
        inst[own].setdefault("_transforms", []).append(
            {k: v for k, v in rec.items() if k != "name"}
        )
    instances = [{"name": k, **inst[k]} for k in order]
    return {
        "nodes": nodes,
        "named_instances": [n for _, n in heads],
        "instances": instances,
        "transforms": tr,
    }


def terrain_json(b, bo="<"):
    (ver,) = struct.unpack_from(bo + "f", b, 0)
    h = struct.unpack_from(bo + "4I", b, 4)
    out = {"version": ver, "header": list(h), "texture_layers": [], "grass": [], "detailmeshes": []}
    p = 20

    def rdpath(p):
        if p + 4 > len(b):
            return None
        nl = struct.unpack_from(bo + "I", b, p)[0]
        if not 4 <= nl <= 128 or p + 4 + nl > len(b):
            return None
        s = b[p + 4 : p + 4 + nl]
        if not s.endswith(b"\0") or not s.startswith(b"/"):
            return None
        return s[:-1].decode("latin1"), p + 4 + nl

    for i in range(h[3]):
        r = rdpath(p)
        if not r:
            break
        path, p = r
        tid = b[p : p + 8].hex()
        p += 8
        out["texture_layers"].append({"path": path, "id": tid})
    for lst in ("grass", "detailmeshes"):
        if p + 4 > len(b):
            break
        cnt = struct.unpack_from(bo + "I", b, p)[0]
        if cnt > 32:
            break
        p += 4
        for i in range(cnt):
            r = rdpath(p)
            if not r:
                break
            path, p = r
            out[lst].append(path)
    out["tail_bytes"] = len(b) - p
    return out


def to_json(name_lower, data, order=None):
    """Return (json_dict or None) for a raw asset payload.
    order: '<' (PC) / '>' (X360/PS3) / None = auto-detect per asset."""
    if name_lower.endswith(".fragment"):
        import sys as _sys

        _sys.setrecursionlimit(100000)
        import kapow_fragment as _kf

        bo = order or _kf.detect_order(data)
        out = fragment_json(data, bo)
        try:
            r = _kf.parse(data, order=bo)
            sch = {h: t for h, t in r["schema"]}
            out["schema"] = [{"id": h, "type": t} for h, t in r["schema"]]
            out["nodes_full"] = [
                {
                    "id": i["node"],
                    "type": sch.get(i["node"]),
                    "created": bool(i.get("created")),
                    "props": [[nm, t, v] for nm, t, v in i["props"]],
                }
                for i in r["inst"]
            ]
            out["lossless"] = bool(r["ok"])
        except Exception as e:
            out["lossless"] = False
            out["parse_error"] = str(e)[:200]
        return out
    if name_lower.endswith(".sequence"):
        return decode_sequence.parse(data, order=order)
    if name_lower.endswith(".terrain"):
        return terrain_json(data, order or decode_sequence.detect_order(data))
    if name_lower.endswith(PROPBAG_EXTS):
        return kapow_props.parse(data, order=order)
    return None


if __name__ == "__main__":
    import sys

    b = open(sys.argv[1], "rb").read()
    d = to_json(sys.argv[1].lower(), b)
    out = json.dumps(d, indent=1)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(out)
    else:
        print(out[:4000])
