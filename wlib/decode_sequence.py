#!/usr/bin/env python3
# Kapow .sequence parser (keyframe tracks driving node properties).
# Integers/floats are in platform byte order: LE on PC, BE on X360/PS3
# (auto-detected from the f32 version=1.0 header, or pass parse(order=...)).
# Layout (byte-packed after header):
#  [f32 version=1.0][u32 4][u32 nobjects][u32 ?]
#  per object:
#   [u8 0][u32 1][u8 0]? [u32 nrefids] [nrefids x u32 id] [u32 namelen][ClassName\0]
#   [u32 ntracks]
#   per track: [u32 namelen][propname\0][u32 ttype][u32 nkeys][key data]
#  scalar keys (ttype 3, prop dim 1): 9 dwords [t][v][u32 m][a][u32][b][c][d][e]
#  vec3 keys: value/tangent vectors prefixed by [u32 3]
# This parser extracts objects, tracks, key times/values; tangents kept raw.
import struct, sys, json


def rdname(b, p, maxl=64, bo="<"):
    if p + 4 > len(b):
        return None
    nl = struct.unpack_from(bo + "I", b, p)[0]
    if 2 <= nl <= maxl and p + 4 + nl <= len(b):
        nm = b[p + 4 : p + 4 + nl]
        if nm.endswith(b"\0") and all(32 <= c < 127 for c in nm[:-1]):
            return nm[:-1].decode(), p + 4 + nl
    return None


def detect_order(b):
    import math

    for bo in ("<", ">"):
        v = struct.unpack_from(bo + "f", b, 0)[0]
        if math.isfinite(v) and 0.01 <= v <= 1000:
            return bo
    return "<"


def parse(b, order=None):
    bo = order or detect_order(b)
    n = len(b)
    out = {"version": struct.unpack_from(bo + "f", b, 0)[0], "objects": []}
    out["h1"], out["nobjects"] = struct.unpack_from(bo + "2I", b, 4)
    p = 12
    while p < n - 8:
        # scan for the next [nrefids][ids...][namelen][Name\0] object header
        found = None
        for q in list(range(p, min(p + 256, n - 8))) + list(range(max(16, p - 24), p)):
            # path-target object: [u32 len]["/...path..."]
            r0 = rdname(b, q, maxl=128, bo=bo)
            if r0 and r0[0].startswith("/"):
                path, pp = r0
                # skip pad dwords then class name
                cn = None
                for s2 in range(0, 17, 1):
                    rr = rdname(b, pp + s2, bo=bo)
                    if rr and (rr[0][:1].isalpha() or rr[0][:1] == "_"):
                        cn = (rr, pp + s2)
                        break
                if cn:
                    found = ("path", path, cn[0])
                    break
            nr = struct.unpack_from(bo + "I", b, q)[0]
            if 1 <= nr <= 8:
                r = rdname(b, q + 4 + 4 * nr, bo=bo)
                if r and (r[0][:1].isalpha() or r[0][:1] == "_"):
                    # validate: [ntracks<=64] then a plausible track name
                    nt_ = struct.unpack_from(bo + "I", b, r[1])[0] if r[1] + 4 <= n else 999
                    if nt_ > 64 or (nt_ > 0 and rdname(b, r[1] + 4, bo=bo) is None):
                        continue
                    ids = ["%08x" % x for x in struct.unpack_from(bo + "%dI" % nr, b, q + 4)]
                    found = ("ids", ids, r)
                    break
        if not found:
            break
        kind, tgt, (cls, p2) = found
        obj = {"class": cls, ("path" if kind == "path" else "ids"): tgt, "tracks": []}
        ntr = struct.unpack_from(bo + "I", b, p2)[0]
        p2 += 4
        ok = True
        for ti in range(min(ntr, 256)):
            r = rdname(b, p2, bo=bo)
            if r is None:
                ok = False
                break
            pname, p2 = r
            ttype, nkeys = struct.unpack_from(bo + "2I", b, p2)
            p2 += 8
            keys = []
            if nkeys > 10000:
                ok = False
                break
            for k in range(nkeys):
                if p2 + 12 > n:
                    ok = False
                    break
                t, mode, dim = struct.unpack_from(bo + "fII", b, p2)
                p2 += 12
                if not 1 <= dim <= 4:
                    ok = False
                    break
                val = [round(x, 5) for x in struct.unpack_from(bo + "%df" % dim, b, p2)]
                p2 += 4 * dim
                kd = {"t": round(t, 5), "mode": mode, "value": val[0] if dim == 1 else val}

                def plaus_key(q):
                    if q + 12 > n:
                        return False
                    tt, mm, dd = struct.unpack_from(bo + "fII", b, q)
                    import math

                    return math.isfinite(tt) and abs(tt) < 1e6 and mm <= 8 and 1 <= dd <= 4

                def plaus_bound(q):
                    if q >= n - 4:
                        return True
                    if rdname(b, q, bo=bo):
                        return True
                    v = struct.unpack_from(bo + "I", b, q)[0]
                    if 1 <= v <= 8 and q + 4 + 4 * v + 4 <= n and rdname(b, q + 4 + 4 * v, bo=bo):
                        return True
                    return False

                last = k == nkeys - 1
                took = False
                if p2 + 4 <= n:
                    hdim = struct.unpack_from(bo + "I", b, p2)[0]
                    if 1 <= hdim <= 4 and p2 + 4 + 16 * hdim <= n:
                        hh = struct.unpack_from(bo + "%df" % (4 * hdim), b, p2 + 4)
                        q = p2 + 4 + 16 * hdim
                        okctx = plaus_bound(q) if last else plaus_key(q)
                        okctx_wo = plaus_bound(p2) if last else plaus_key(p2)
                        if all(abs(x) < 1e9 for x in hh) and (okctx or not okctx_wo):
                            kd["handles"] = [round(x, 5) for x in hh]
                            p2 = q
                            took = True
                keys.append(kd)
            if not ok:
                break
            obj["tracks"].append({"prop": pname, "type": ttype, "nkeys": nkeys, "keys": keys})
        out["objects"].append(obj)
        p = p2
        if not ok:
            out.setdefault("warn", []).append("desync in %s" % cls)
    out["parsed_bytes"] = p
    out["file_bytes"] = n
    return out


if __name__ == "__main__":
    b = open(sys.argv[1], "rb").read()
    d = parse(b)
    j = json.dumps(d, indent=1)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(j)
    else:
        print(j[:3500])
