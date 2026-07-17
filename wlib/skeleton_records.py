"""File-only skeleton record parser (v14-era knowledge).
Each bone record: [u32 namelen][name\0][body]; body starts [u8][u32 parent+1][u32 1]
then flags/zeros, then a byte-packed list of CHILD-ATTACHMENT transforms
[f32x3 pos][f32x4 quat XYZW] (one per child, hypothesis: in child order).
Rest local of bone B = the entry in B's PARENT's record that corresponds to B.
Engine quats = conjugate of naive xyzw convention.
"""

import struct, numpy as np


def node_records(h):
    occ = []
    i = 0
    N = len(h)
    while i + 4 <= N:
        n = struct.unpack_from("<I", h, i)[0]
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


def parse(h, maxpos=5.0):
    occ = [(i, n) for i, n in node_records(h) if "/" not in n and n != "ModelRes"]
    recs = []
    for k, (lp, nm) in enumerate(occ):
        namelen = struct.unpack_from("<I", h, lp)[0]
        b0 = lp + 4 + namelen
        b1 = occ[k + 1][0] if k + 1 < len(occ) else len(h)
        body = h[b0:b1]
        par = (
            struct.unpack_from("<i", body, 4)[0] - 1 if len(body) >= 8 else -2
        )  # u32@4 = parent+1 (1-based, 0=root)
        # scan body for 28B [pos f32x3][quat f32x4 unit] entries, byte-granular
        ents = []
        j = 0
        while j + 28 <= len(body):
            v = struct.unpack_from("<7f", body, j)
            p = np.array(v[:3])
            q = np.array(v[3:])
            n2 = float(q @ q)
            if 0.98 < n2 < 1.02 and np.all(np.isfinite(p)) and np.linalg.norm(p) < maxpos:
                ents.append((j, p, q))
                j += 28
            else:
                j += 1
        recs.append(dict(name=nm, parent=par, body=body, entries=ents))
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
