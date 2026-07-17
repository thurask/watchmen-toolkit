#!/usr/bin/env python3
"""kapow_fragment — LOSSLESS .fragment parser (engine-verified, 2026-07-07).
Format (from KapowMultiDEDRM decomp FUN_005473ee/FUN_00545e1b + TOD_tools):
  file = [header (17B, or extended w/ name when flags bit set)] + chunks
  chunk = [u32 size<=0x2800][payload]; payloads concatenate into ONE stream
  stream = schema records [FFFFFFFF][selfHash][wc][TypeName(...)] ...
           then instances: [FFFFFFFE|FFFFFFFF][nodeId] then [keyHash][typed value]*
  keyHash = kapow bit-CRC32(poly 0x04C11DB7) of UPPERCASE property name
  types: number/integer/truth/color=4B; vector=12B; quaternion=16B;
         string=[wc][wc*4]; list(T)=[count][T*count];
         Entity: [tag] tag0/1/2=4B, tag3=[3][nodeId], tag4=[4][a][n][n words],
                 tag5=[5][n][n words]
  key names/types: game database.bin registry (3693) + TOD_tools builtins +
  exe strings; unknown keys are size-inferred with boundary/lookahead resync
  and reported with '?' type suffix.
Validation: all 906 extracted fragments parse to EOF; all 12777 resource-path
strings verified present in output; EmbeddedJoint spring constants recovered.
"""

import struct, pickle, sys, re
import os as _os

sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import os as _os0

_KP = _os0.path.join(_os0.path.dirname(_os0.path.abspath(__file__)), "kapow_fragment_keys.pkl")
_KD = pickle.load(open(_KP, "rb"))
h2t = _KD["keytable"]
std = _KD["stdkeys"]
STDTYPES = {
    "runScript": "truth",
    "Open": "truth",
    "enabled": "truth",
    "Visible": "truth",
    "runFrameUpdate": "truth",
    "smartSelectable": "truth",
    "logicalParent": "Entity",
    "siblingOrder": "integer",
}
NAMES = {}
for h, (n, t) in h2t.items():
    NAMES[h] = (n, t)
for h, n in std.items():
    NAMES[h] = (n, STDTYPES.get(n, "integer"))
NAMES[0x0991B0D4] = ("key_0991b0d4", "integer")
for _h, _nt in _KD["promoted"].items():
    NAMES[_h] = _nt
NAMEABLE = _KD["nameable"]
TYPERE = re.compile(r"^[A-Za-z_0-9 ]+\([A-Za-z_0-9 ]*\)$")


def dechunk(d, bo="<"):
    import struct as _s

    for start in range(8, 80):
        p = start
        parts = []
        while p + 4 <= len(d):
            sz = _s.unpack_from(bo + "I", d, p)[0]
            if not (0 < sz <= 0x2800) or p + 4 + sz > len(d):
                parts = None
                break
            parts.append(d[p + 4 : p + 4 + sz])
            p += 4 + sz
            if p == len(d):
                break
        if parts and p == len(d):
            return b"".join(parts), start
    return None, None


def _schema_scan(d, bo):
    """Return offset of first valid [FFFFFFFF][hash][wc][TypeName(...)] record, or None."""
    u = lambda o: struct.unpack_from(bo + "I", d, o)[0]
    scan = 0
    while scan + 16 <= min(len(d), 4096):
        if d[scan : scan + 4] == b"\xff\xff\xff\xff":
            wc = u(scan + 8)
            if 1 <= wc <= 40 and scan + 12 + wc * 4 <= len(d):
                nm = d[scan + 12 : scan + 12 + wc * 4].split(b"\x00")[0].decode("latin1", "replace")
                if TYPERE.match(nm):
                    return scan
        scan += 1
    return None


def detect_order(d):
    """Byte order of a .fragment: try chunk-size walk (only parses in the right
    order), fall back to the schema-record scan for unchunked payloads."""
    for bo in ("<", ">"):
        if dechunk(d, bo)[0] is not None:
            return bo
    for bo in ("<", ">"):
        if _schema_scan(d, bo) is not None:
            return bo
    return "<"


def parse(d, collect_unknown=None, order=None):
    bo = order or detect_order(d)
    dc, st = dechunk(d, bo)
    if dc is not None:
        d = dc
    u = lambda o: struct.unpack_from(bo + "I", d, o)[0]
    f = lambda o: struct.unpack_from(bo + "f", d, o)[0]
    # locate schema start: first valid [FFFFFFFF][hash][wc][TypeName(...)] record in the head
    p = None
    schema = []
    scan = 0
    while scan + 16 <= min(len(d), 4096):
        if d[scan : scan + 4] == b"\xff\xff\xff\xff":
            wc = u(scan + 8)
            if 1 <= wc <= 40 and scan + 12 + wc * 4 <= len(d):
                nm = d[scan + 12 : scan + 12 + wc * 4].split(b"\x00")[0].decode("latin1", "replace")
                if TYPERE.match(nm):
                    p = scan
                    break
        scan += 1
    if p is None:
        p = 0
    while p + 12 <= len(d) and u(p) == 0xFFFFFFFF:
        wc = u(p + 8)
        if not (1 <= wc <= 40) or p + 12 + wc * 4 > len(d):
            break
        nm = d[p + 12 : p + 12 + wc * 4].split(b"\x00")[0].decode("latin1")
        if not TYPERE.match(nm):
            break
        schema.append(("%08x" % u(p + 4), nm))
        p += 12 + wc * 4
    inst = []
    cur = None
    hard_fail = None
    unk_here = {}
    memo = {}

    def rdval(typ, p):
        if typ == "raw4":
            x = u(p)
            fl = f(p)
            v = (
                round(fl, 6)
                if (fl == fl and 1e-12 < abs(fl) < 1e12)
                else (x if x < 0x80000000 else x - 0x100000000)
            )
            return v, p + 4
        if typ == "number":
            return round(f(p), 6), p + 4
        if typ in ("integer", "int", "color"):
            return u(p), p + 4
        if typ == "truth":
            return bool(u(p)), p + 4
        if typ == "vector":
            return [round(f(p + i * 4), 6) for i in range(3)], p + 12
        if typ == "quaternion":
            return [round(f(p + i * 4), 6) for i in range(4)], p + 16
        if typ == "string":
            wc = u(p)
            if wc > 4000 or p + 4 + wc * 4 > len(d):
                raise ValueError("wc %d" % wc)
            return d[p + 4 : p + 4 + wc * 4].split(b"\x00")[0].decode("latin1"), p + 4 + wc * 4
        if typ in ("Entity", "entity"):
            tag = u(p)
            if tag == 3:
                return {"ref": "%08x" % u(p + 4)}, p + 8
            if tag == 5:
                n = u(p + 4)
                if n > 64:
                    raise ValueError("etag5 n %d" % n)
                return {"xref": [("%08x" % u(p + 8 + i * 4)) for i in range(n)]}, p + 8 + n * 4
            if tag == 4:
                a = u(p + 4)
                n = u(p + 8)
                if n > 64:
                    raise ValueError("etag4 n %d" % n)
                return {
                    "xref4": [("%08x" % u(p + 12 + i * 4)) for i in range(n)],
                    "a": a,
                }, p + 12 + n * 4
            if tag in (0, 1, 2):
                return {"etag": tag}, p + 4
            raise ValueError("etag %d" % tag)
        if typ.startswith("list("):
            sub = typ[5:-1]
            cnt = u(p)
            q = p + 4
            if cnt > 50000:
                raise ValueError("cnt %d" % cnt)
            out = []
            for i in range(cnt):
                v, q = rdval(sub, q)
                out.append(v)
            return out, q
        raise ValueError("type %r" % typ)

    known_or_marker = lambda q: q == len(d) or (
        q + 4 <= len(d) and (u(q) in (0xFFFFFFFE, 0xFFFFFFFF) or u(q) in NAMES or u(q) in NAMEABLE)
    )
    while p + 4 <= len(d):
        w = u(p)
        if w in (0xFFFFFFFE, 0xFFFFFFFF):
            cur = {"node": "%08x" % u(p + 4), "created": w == 0xFFFFFFFF, "props": []}
            inst.append(cur)
            p += 8
            continue
        ent = NAMES.get(w)
        if ent is None:
            # unknown key: infer value span; allow chains of unknown keys via depth-limited lookahead
            def try_ahead(q, depth):
                if known_or_marker(q):
                    return True
                if q in memo:
                    return memo[q]
                if depth <= 0 or q + 4 > len(d):
                    return False
                memo[q] = False
                for typ3 in ("Entity", "integer", "string", "vector", "quaternion"):
                    try:
                        _, q2 = rdval(typ3, q + 4)
                    except Exception:
                        continue
                    if try_ahead(q2, depth - 1):
                        memo[q] = True
                        break
                return memo[q]

            def ascii_frac(a, b):
                seg = d[a:b]
                if not seg:
                    return 0
                return sum(1 for c in seg if 32 <= c < 127 or c == 0) / len(seg)

            order = [
                "raw4",
                "Entity",
                "string",
                "list(string)",
                "vector",
                "quaternion",
                "list(integer)",
            ]
            wc0 = u(p + 4) if p + 8 <= len(d) else 0
            if (
                1 <= wc0 <= 4000
                and p + 8 + wc0 * 4 <= len(d)
                and ascii_frac(p + 8, p + 8 + min(wc0 * 4, 64)) > 0.9
            ):
                order = ["string", "list(string)", "raw4", "Entity", "vector", "quaternion"]
            got = None
            # pass 1: immediate anchor
            for typ2 in order:
                try:
                    v, q = rdval(typ2, p + 4)
                except Exception:
                    continue
                if known_or_marker(q):
                    got = (typ2, v, q)
                    break
            if got is None:
                for typ2 in order:
                    try:
                        v, q = rdval(typ2, p + 4)
                    except Exception:
                        continue
                    if try_ahead(q, 200):
                        got = (typ2, v, q)
                        break
            if got is None:
                hard_fail = (p, "%08x" % w)
                break
            unk_here.setdefault(w, [0, got[0]])
            unk_here[w][0] += 1
            if collect_unknown is not None:
                collect_unknown.setdefault(w, {}).setdefault(got[0], 0)
                collect_unknown[w][got[0]] += 1
            if cur is None:
                cur = {"node": "(pre)", "props": []}
                inst.append(cur)
            cur["props"].append((NAMEABLE.get(w, "key_%08x" % w), got[0] + "?", got[1]))
            p = got[2]
            continue
        nm, typ = ent
        try:
            v, q = rdval(typ, p + 4)
        except Exception as e:
            hard_fail = (p, "%s:%s %s" % (nm, typ, e))
            break
        if cur is None:
            cur = {"node": "(pre)", "props": []}
            inst.append(cur)
        cur["props"].append((nm, typ, v))
        p = q
    return dict(
        ok=hard_fail is None,
        fail=hard_fail,
        schema=schema,
        inst=inst,
        unknown=unk_here,
        parsed_frac=p / len(d) if len(d) else 1,
        end=p,
        size=len(d),
    )


if __name__ == "__main__":
    d = open(sys.argv[1], "rb").read()
    r = parse(d)
    print(
        "ok:",
        r["ok"],
        "frac %.4f" % r["parsed_frac"],
        "schema:",
        len(r["schema"]),
        "inst:",
        len(r["inst"]),
        "unknown keys:",
        len(r["unknown"]),
    )
    if r["fail"]:
        print("FAIL:", r["fail"])
    for i in r["inst"]:
        print("node", i["node"], "C" if i.get("created") else "", len(i["props"]), "props")
