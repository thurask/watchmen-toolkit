#!/usr/bin/env python3
# Universal Kapow "property bag" asset parser (.particle/.grass/.terrain/.detailmesh/
# .pb/.sequence/...). Format (integers in platform byte order: LE on PC, BE on
# X360/PS3 -- auto-detected, or pass parse(order='<'|'>')):
#   block: [u32 pre?]* [u32 namelen][ClassName\0][u32 schemaCount]
#   records (same ownerId dword anchors a block's records):
#     [u32 ownerId][u32 keyHash][u32 typeHash][u32 k][k dwords payload]
#     string payload: [u32 wordcount][wordcount*4 chars]  (k = 1+wordcount)
#   keyHash/typeHash = kapow bit-CRC32(poly 0x04C11DB7) of UPPERCASE name / typename.
import struct, json, pickle


def kapow_hash(s):
    crc = 0
    for byte in s.encode("latin1"):
        for bit in range(8):
            neg = crc & 0x80000000
            crc = ((crc << 1) & 0xFFFFFFFF) | ((byte >> bit) & 1)
            if neg:
                crc ^= 0x04C11DB7
    return crc


TYPES = {
    kapow_hash(t.upper()): t
    for t in (
        "number",
        "integer",
        "truth",
        "string",
        "vector",
        "color",
        "quaternion",
        "enum",
        "vectorlist",
        "list",
    )
}
_D = None


def namedict():
    global _D
    if _D is None:
        import os

        for cand in (
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "prop_hash_dict.pkl"),
            "/tmp/prop_hash_dict.pkl",
        ):
            try:
                _D = pickle.load(open(cand, "rb"))
                break
            except:
                _D = {}
    return _D


def _rdname(b, p, bo="<"):
    n = len(b)
    if p + 4 > n:
        return None
    nl = struct.unpack_from(bo + "I", b, p)[0]
    if 2 <= nl <= 64 and p + 4 + nl <= n:
        nm = b[p + 4 : p + 4 + nl]
        if nm.endswith(b"\0") and all(32 <= c < 127 for c in nm[:-1]):
            return nm[:-1].decode(), p + 4 + nl
    return None


def detect_order(b):
    """Pick byte order by finding the leading [u32 namelen][ClassName\\0] record
    (allowing up to 4 pre-dwords). Small namelen only parses in the right order."""
    for bo in ("<", ">"):
        for nskip in range(5):
            if _rdname(b, 4 * nskip, bo):
                return bo
    return "<"


def parse(b, keynames=None, order=None):
    if keynames is None:
        keynames = namedict()
    bo = order or detect_order(b)
    p = 0
    n = len(b)
    blocks = []
    pre = []
    while p + 8 <= n:
        r = _rdname(b, p, bo)
        nskip = 0
        while r is None and nskip < 4 and p + 4 * (nskip + 1) + 8 <= n:
            nskip += 1
            r = _rdname(b, p + 4 * nskip, bo)
        if r is None:
            break
        if nskip:
            pre = list(struct.unpack_from(bo + "%dI" % nskip, b, p))
        cls, p = r
        schema = struct.unpack_from(bo + "I", b, p)[0]
        p += 4
        recs = []
        owner = None
        while p + 16 <= n:
            o, key, typ, k = struct.unpack_from(bo + "4I", b, p)
            if owner is None:
                owner = o
            if o != owner:
                break
            tn = TYPES.get(typ)
            if tn is None and k > 1024:
                break
            q = p + 16
            val = None
            if tn == "string":
                wc = struct.unpack_from(bo + "I", b, q)[0]
                if wc + 1 != k:
                    pass
                val = b[q + 4 : q + 4 + wc * 4].rstrip(b"\0").decode("latin1")
            elif tn == "number":
                fs = [struct.unpack_from(bo + "f", b, q + 4 * j)[0] for j in range(k)]
                val = fs[0] if k == 1 else fs
            elif tn in ("integer", "truth", "enum"):
                iv = [struct.unpack_from(bo + "i", b, q + 4 * j)[0] for j in range(k)]
                val = iv[0] if k == 1 else iv
            else:
                fs = [struct.unpack_from(bo + "f", b, q + 4 * j)[0] for j in range(k)]
                val = {
                    "raw_type": "%08x" % typ,
                    "floats": [round(x, 6) if abs(x) < 1e9 else None for x in fs],
                    "hex": b[q : q + 4 * k].hex(),
                }
            p = q + 4 * k
            recs.append(
                {"key": keynames.get(key) or "%08x" % key, "type": tn or "%08x" % typ, "value": val}
            )
        blocks.append(
            {
                "class": cls,
                "pre": pre,
                "owner": "%08x" % (owner or 0),
                "schema": schema,
                "props": recs,
            }
        )
        pre = []
    return {"blocks": blocks, "trailing_bytes": n - p}


if __name__ == "__main__":
    import sys

    b = open(sys.argv[1], "rb").read()
    out = parse(b)
    j = json.dumps(out, indent=1)
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(j)
    else:
        print(j[:5000])
