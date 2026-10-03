#!/usr/bin/env python3
# Kapow .sequence parser (PropertySequenceAsset: keyframe tracks driving node
# properties).  Integers/floats are in platform byte order: LE on PC, BE on
# X360/PS3 (auto-detected from the leading f32, or pass parse(order=...)).
#
# Engine grammar (readers: asset FUN_0054558c, object FUN_00544374/FUN_0054113c,
# track FUN_005415bf, key FUN_00547f4c, spline key FUN_00547fdb) -- byte-packed,
# no padding, no slop:
#   [f32 durationSec][u32 flags][u32 nObjects]
#   object: [str targetPath][u32 flag][u32 nIds][u32 id x nIds][str className][u32 nTracks]
#   track:  [str property][u32 interpolation][u32 nKeys]
#   key:    [f32 time][u32 interpolation][u32 dim][f32 value x dim]
#           spline-capable tracks only: [u32 n][n x (f32 inT, inV, outT, outV)]
#   str = [u32 len][len bytes incl. NUL]; an empty path is [1]["\0"].
# interpolation: 0 inherited (key only: use the track's), 1 step, 2 linear,
# 3 spline (exe string "inherited,step,linear,spline" @0x00a361a0).
# A track is spline-capable -- EVERY key carries the handle block -- iff its
# property's data type is number, vector or quaternion (FUN_00539dd9).  Handles
# are absolute (time, value) points; the segment is a cubic Hermite through the
# start key's out-handle and the end key's in-handle (FUN_0040f5a1).
# Quaternion properties are keyed as EULER DEGREES (x, y, z + one pad float),
# interpolated as a vector, then converted q = qx*qy*qz (FUN_00499733).
import math, os, struct, sys, json, threading


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

    if len(b) < 4:
        return "<"
    for bo in ("<", ">"):
        v = struct.unpack_from(bo + "f", b, 0)[0]
        if math.isfinite(v) and 0.01 <= v <= 1000:
            return bo
    return "<"


FORMAT = "kapow-sequence/2"
INTERPOLATION = ("inherited", "step", "linear", "spline")
#: property data types whose tracks use spline keys (FUN_00539dd9)
SPLINE_TYPES = ("number", "vector", "quaternion")
_HERE = os.path.dirname(os.path.abspath(__file__))
_TYPES = {"loaded": False, "names": None, "hash": None}


def property_type(name):
    """Registered data type of a property name ('number', 'vector', 'truth', ...)
    from the fragment key table (kapow_fragment.NAMES: hash -> (name, type)), or
    None when the name is not in the table."""
    if not _TYPES["loaded"]:
        _TYPES["loaded"] = True
        try:
            if _HERE not in sys.path:
                sys.path.append(_HERE)  # append, never insert(0)
            import kapow_fragment as _kf, kapow_props as _kp

            _TYPES["names"] = _kf.NAMES
            _TYPES["hash"] = getattr(_kp, "name_hash", None) or (
                lambda s: _kp.kapow_hash(s.upper())
            )
        except Exception:
            _TYPES["names"] = None
    if not _TYPES["names"]:
        return None
    ent = _TYPES["names"].get(_TYPES["hash"](name))
    if isinstance(ent, (tuple, list)) and len(ent) >= 2 and str(ent[0]).lower() == name.lower():
        return ent[1]
    return None


def euler_deg_to_quat(x, y, z):
    """Quaternion-track value -> (qx, qy, qz, qw), engine FUN_00499733:
    q = qx(x) * qy(y) * qz(z), angles in degrees."""
    hx, hy, hz = (math.radians(a) * 0.5 for a in (x, y, z))
    c0, s0, c1, s1, c2, s2 = (
        math.cos(hx),
        math.sin(hx),
        math.cos(hy),
        math.sin(hy),
        math.cos(hz),
        math.sin(hz),
    )
    return (
        s2 * (c0 * s1) + c2 * c1 * s0,
        -s2 * s0 * c1 + c2 * (c0 * s1),
        s1 * s0 * c2 + s2 * (c0 * c1),
        -s2 * s0 * s1 + c2 * (c0 * c1),
    )


def _hermite(u, t0, v0, out, inn, t1, v1):
    """FUN_0040f5a1: cubic through (t0,v0) and (t1,v1), end slopes from the start
    key's out-handle and the end key's in-handle (absolute (time, value) points)."""
    d = v1 - v0
    dt = t1 - t0
    m0 = ((out[1] - v0) / (out[0] - t0)) * dt if out[0] != t0 else 0.0
    m1 = ((v1 - inn[1]) / (t1 - inn[0])) * dt if inn[0] != t1 else 0.0
    c = m1 + m0 - 2.0 * d
    return m0 * u + u * u * u * c + (d - m0 - c) * u * u + v0


def evaluate(track, t):
    """Value of a parsed track at time `t`, as the engine evaluates it
    (key search FUN_0053a9b0, dispatch FUN_0053aa43).  Returns a list of floats
    (Euler degrees for quaternion tracks) or None for an empty track."""
    keys = track["keys"]
    if not keys:
        return None
    val = lambda k: list(k["value"]) if isinstance(k["value"], (list, tuple)) else [k["value"]]
    if len(keys) == 1:
        return val(keys[0])
    i = 0
    while i < len(keys) and t > keys[i]["t"]:
        i += 1
    a = max(i - 1, 0)
    b = min(i, len(keys) - 1)
    ka, kb = keys[a], keys[b]
    u = 0.0 if a == b or kb["t"] == ka["t"] else (t - ka["t"]) / (kb["t"] - ka["t"])
    mode = ka.get("mode") or track.get("type")
    va, vb = val(ka), val(kb)
    if mode == 2:
        return [x + (y - x) * u for x, y in zip(va, vb)]
    if mode == 3 and "out" in ka and "in" in kb:
        n = min(len(ka["out"]), len(kb["in"]))
        return [
            _hermite(u, ka["t"], va[c], ka["out"][c], kb["in"][c], kb["t"], vb[c]) for c in range(n)
        ]
    return va  # step (and anything the engine leaves untouched)


class _Bad(Exception):
    pass


class _Budget(threading.local):
    """Track-parse attempts left for the current parse_exact() call: one counter
    per thread, saved and restored around each call, so parses may nest."""

    left = 0


_BUDGET = _Budget()


def _rstr(b, p, bo, maxl=1024):
    if p + 4 > len(b):
        raise _Bad("string")
    n = struct.unpack_from(bo + "I", b, p)[0]
    if n > maxl or p + 4 + n > len(b):
        raise _Bad("string")
    raw = b[p + 4 : p + 4 + n]
    if n and (raw[-1] != 0 or not all(32 <= c < 127 for c in raw[:-1])):
        raise _Bad("string")
    return raw[:-1].decode("latin1") if n else "", p + 4 + n


def _keys(b, p, nk, spline, bo):
    out = []
    n = len(b)
    for _ in range(nk):
        if p + 12 > n:
            raise _Bad("key")
        t, mode, dim = struct.unpack_from(bo + "fII", b, p)
        p += 12
        if mode > 3 or not 1 <= dim <= 4 or p + 4 * dim > n or not math.isfinite(t):
            raise _Bad("key")
        val = [round(x, 5) for x in struct.unpack_from(bo + "%df" % dim, b, p)]
        p += 4 * dim
        kd = {"t": round(t, 5), "mode": mode, "value": val[0] if dim == 1 else val}
        if spline:
            if p + 4 > n:
                raise _Bad("handles")
            hn = struct.unpack_from(bo + "I", b, p)[0]
            p += 4
            if not 1 <= hn <= 4 or p + 16 * hn > n:
                raise _Bad("handles")
            hh = [round(x, 5) for x in struct.unpack_from(bo + "%df" % (4 * hn), b, p)]
            p += 16 * hn
            kd["handles"] = hh  # file order: inT, inV, outT, outV per component
            kd["in"] = [hh[4 * c : 4 * c + 2] for c in range(hn)]
            kd["out"] = [hh[4 * c + 2 : 4 * c + 4] for c in range(hn)]
        out.append(kd)
    return out, p


def _tracks(b, p, nt, bo, rest):
    """Parse `nt` tracks at p, then `rest(p)` (the remaining objects).  The key
    class comes from the property's registered type; without one it is decided
    by which reading lets the WHOLE remainder parse."""
    if nt == 0:
        return [], rest(p)
    _BUDGET.left -= 1
    if _BUDGET.left < 0:
        raise _Bad("budget")
    name, q = _rstr(b, p, bo)
    if not name or q + 8 > len(b):
        raise _Bad("track")
    interp, nk = struct.unpack_from(bo + "2I", b, q)
    q += 8
    if nk > 10000 or not 1 <= interp <= 3:
        raise _Bad("track")
    vt = property_type(name)
    order = [vt in SPLINE_TYPES] if vt else [True, False]
    if vt:
        order.append(not order[0])  # table disagrees with the bytes: still try
    for spline in order:
        try:
            ks, q2 = _keys(b, q, nk, spline, bo)
            more, tail = _tracks(b, q2, nt - 1, bo, rest)
        except _Bad:
            continue
        dim = len(ks[0]["value"]) if ks and isinstance(ks[0]["value"], list) else 1
        if vt is None and spline and ks:
            vt_out, src = {1: "number", 3: "vector", 4: "quaternion"}.get(dim), "inferred"
        else:
            vt_out, src = vt, ("table" if vt else None)
        tr = {
            "prop": name,
            "type": interp,
            "interpolation": INTERPOLATION[interp],
            "value_type": vt_out,
            "value_type_source": src,
            "spline": spline,
            "nkeys": nk,
            "keys": ks,
        }
        if vt_out == "quaternion":
            for k in ks:
                v = k["value"] if isinstance(k["value"], list) else [k["value"]]
                if len(v) >= 3:
                    k["euler_deg"] = v[:3]
                    k["quat"] = [round(x, 6) for x in euler_deg_to_quat(*v[:3])]
        return [tr] + more, tail
    raise _Bad("track")


def _objects(b, p, no, bo):
    if no == 0:
        if p != len(b):
            raise _Bad("trailing bytes")
        return []
    path, p = _rstr(b, p, bo)
    if p + 8 > len(b):
        raise _Bad("object")
    flag, nids = struct.unpack_from(bo + "2I", b, p)
    p += 8
    if nids > 64 or p + 4 * nids > len(b):
        raise _Bad("object")
    ids = ["%08x" % x for x in struct.unpack_from(bo + "%dI" % nids, b, p)]
    p += 4 * nids
    cls, p = _rstr(b, p, bo)
    if p + 4 > len(b):
        raise _Bad("object")
    nt = struct.unpack_from(bo + "I", b, p)[0]
    if nt > 256:
        raise _Bad("object")
    obj = {"class": cls, "flag": flag}
    if path:
        obj["path"] = path
    if ids or not path:
        obj["ids"] = ids
    obj["tracks"], rest = _tracks(b, p + 4, nt, bo, lambda q: _objects(b, q, no - 1, bo))
    return [obj] + rest


def parse_exact(b, order=None):
    """Engine-grammar parse; returns the result dict, or None unless the buffer
    follows the grammar to its last byte."""
    bo = order or detect_order(b)
    if len(b) < 12:
        return None
    dur, flags, no = struct.unpack_from(bo + "fII", b, 0)
    if no > 4096 or not math.isfinite(dur):
        return None
    lim = sys.getrecursionlimit()
    saved = _BUDGET.left
    try:
        sys.setrecursionlimit(max(lim, 8000))
        _BUDGET.left = 100000
        objs = _objects(b, 12, no, bo)
    except (_Bad, RecursionError):
        return None
    finally:
        _BUDGET.left = saved
        sys.setrecursionlimit(lim)
    return {
        "format": FORMAT,
        "duration": dur,
        "version": dur,  # historical name of the same float (it is seconds)
        "h1": flags,
        "nobjects": no,
        "objects": objs,
        "parsed_bytes": len(b),
        "file_bytes": len(b),
    }


def parse(b, order=None):
    """Parse a .sequence.  Engine grammar first (parse_exact); buffers that do
    not follow it to the last byte go through the older scanning parser, whose
    result carries no "format" key."""
    out = parse_exact(b, order)
    if out is not None:
        return out
    return _parse_scan(b, order)


def _parse_scan(b, order=None):
    """Pre-engine-read scanning parser: kept as the fallback for buffers that do
    not follow the engine grammar (truncated / carved blobs)."""
    bo = order or detect_order(b)
    n = len(b)
    # .sequence payloads are carved heuristically, so a short/truncated buffer is
    # routine: report it through the same `warn` channel the desync path uses
    # rather than letting struct.error escape into the caller's whole pass.
    if n < 12:
        return {
            "version": None,
            "h1": None,
            "nobjects": 0,
            "objects": [],
            "parsed_bytes": 0,
            "file_bytes": n,
            "warn": ["truncated: %d bytes, need at least 12" % n],
        }
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
        if p2 + 4 > n:
            out.setdefault("warn", []).append("truncated before track count at %d" % p2)
            break
        ntr = struct.unpack_from(bo + "I", b, p2)[0]
        p2 += 4
        ok = True
        for ti in range(min(ntr, 256)):
            r = rdname(b, p2, bo=bo)
            if r is None:
                ok = False
                break
            pname, p2 = r
            if p2 + 8 > n:
                ok = False
                break
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
                if not 1 <= dim <= 4 or p2 + 4 * dim > n:
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
                    if q + 4 > n:
                        return False
                    v = struct.unpack_from(bo + "I", b, q)[0]
                    if 1 <= v <= 8 and q + 4 + 4 * v + 4 <= n and rdname(b, q + 4 + 4 * v, bo=bo):
                        return True
                    return False

                last = k == nkeys - 1
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
                keys.append(kd)
            if not ok:
                break
            obj["tracks"].append({"prop": pname, "type": ttype, "nkeys": nkeys, "keys": keys})
        out["objects"].append(obj)
        if p2 <= p:
            # the resync window scans 24 bytes BACKWARD, so a match can hand back
            # an earlier offset; without this guard a 2-cycle would spin forever
            # appending to out["objects"].
            out.setdefault("warn", []).append("no forward progress at %d" % p)
            break
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
        with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as _f:
            _f.write(j)
    else:
        print(j[:3500])
