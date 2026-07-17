#!/usr/bin/env python3
# Baker v3 (final): engine-verified decode. quat/10000, POSITION/1000 (Ghidra-confirmed),
# t0 = position keys + const quat, file hierarchy, root motion relative to frame 0,
# no slaving (twists are ordinary bones under the true hierarchy).
# usage: python3 bake_v3.py CLIP OUT.npy [upsample] [--bind /tmp/bind_v7.npz]
import sys, struct, numpy as np, watchmen_extract as we, export_female_anims as efa

CONJ = "--conj" in sys.argv

BIND = sys.argv[sys.argv.index("--bind") + 1] if "--bind" in sys.argv else "/tmp/bind_v7.npz"
# import-safe: a missing bind only matters once bake() is called (fresh-install
# bootstrap needs to import this module to BUILD the binds first).
Rb = tb = tloc = par = names = None
NS = 0


def _load_bind(path=None):
    global BIND, Rb, tb, tloc, par, NS, names
    if path:
        BIND = path
    bt = np.load(BIND, allow_pickle=True)
    Rb = bt["Rb"]
    tb = bt["tb"]
    tloc = bt["tloc"]
    par = bt["par"]
    NS = len(Rb)
    names = [str(n) for n in bt["names"]]


try:
    _load_bind()
except FileNotFoundError:
    pass


def Rstd(q):
    q = np.asarray(q, np.float64)
    q = q / np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-12)
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    M = np.empty(q.shape[:-1] + (3, 3))
    M[..., 0, 0] = 1 - 2 * (y * y + z * z)
    M[..., 0, 1] = 2 * (x * y - z * w)
    M[..., 0, 2] = 2 * (x * z + y * w)
    M[..., 1, 0] = 2 * (x * y + z * w)
    M[..., 1, 1] = 1 - 2 * (x * x + z * z)
    M[..., 1, 2] = 2 * (y * z - x * w)
    M[..., 2, 0] = 2 * (x * z - y * w)
    M[..., 2, 1] = 2 * (y * z + x * w)
    M[..., 2, 2] = 1 - 2 * (x * x + y * y)
    return M


def _detect_clip_order(h):
    """'<' PC / '>' X360+PS3.  Console .animation clips are big-endian; pick the
    order whose length-prefixed track-name scan lands on a real name first."""
    for order in ("<", ">"):
        for i in range(0, 300):
            if i + 4 > len(h):
                break
            L = struct.unpack_from(order + "I", h, i)[0]
            if 2 <= L <= 40 and i + 4 + L <= len(h):
                s = h[i + 4 : i + 4 + L]
                if s[:1].isalpha() and all(32 <= c < 127 or c == 0 for c in s):
                    return order
    return "<"


def walk(h, order=None):
    if order is None:
        order = _detect_clip_order(h)
    f4 = np.dtype(order + "f4")
    i2 = np.dtype(order + "i2")
    o = None
    for i in range(0, 300):
        L = struct.unpack_from(order + "I", h, i)[0] if i + 4 <= len(h) else 0
        if 2 <= L <= 40 and i + 4 + L <= len(h):
            s = h[i + 4 : i + 4 + L]
            if s[:1].isalpha() and all(32 <= c < 127 or c == 0 for c in s):
                o = i
                break
    nexp = struct.unpack_from(order + "I", h, o - 4)[0] if (o is not None and o >= 4) else 0
    if not (1 <= nexp <= 128):
        nexp = 128
    nm = []
    if o is None:
        return {}
    while o < len(h) - 4 and len(nm) < nexp:
        L = struct.unpack_from(order + "I", h, o)[0]
        if L < 1 or L > 40 or o + 4 + L > len(h):
            break
        s = h[o + 4 : o + 4 + L]
        if not all(32 <= c < 127 or c == 0 for c in s):
            break
        nm.append(s.rstrip(b"\x00").decode())
        o += 4 + L
    p = o
    out = {}
    for name in nm:
        if p >= len(h):
            break
        t = h[p]
        p += 1
        if t == 1:  # const pos (float3 hdr) + quat keys int16/10000
            kc = struct.unpack_from(order + "H", h, p)[0]
            p += 2
            cp = np.frombuffer(h[p : p + 12], f4).astype(np.float64)
            p += 12
            q = np.frombuffer(h[p : p + kc * 8], i2).reshape(kc, 4) / 10000.0
            p += kc * 8
            out[name] = (q.copy(), cp[None, :] if np.linalg.norm(cp) > 1e-6 else None)
        elif t == 2:  # pos keys int16/1000 + quat keys int16/10000
            kc = struct.unpack_from(order + "H", h, p)[0]
            p += 2
            raw = np.frombuffer(h[p : p + kc * 14], i2).reshape(kc, 7).astype(np.float64)
            p += kc * 14
            out[name] = (raw[:, 3:7] / 10000.0, raw[:, :3] / 1000.0)
        elif t == 0:  # const quat (float4) + pos keys 3xint16/1000
            kc = struct.unpack_from(order + "H", h, p)[0]
            p += 2
            b4 = np.array(struct.unpack_from(order + "4f", h, p))
            p += 16
            pk = np.frombuffer(h[p : p + kc * 6], i2).reshape(kc, 3) / 1000.0
            p += kc * 6
            out[name] = (b4[None, :].copy(), pk.copy())
        elif t == 3:  # const pos (float3) + const quat (float4)
            pos = np.frombuffer(h[p : p + 12], f4).astype(np.float64)
            p += 16
            q = np.array(struct.unpack_from(order + "4f", h, p))
            p += 16
            out[name] = (
                q[None, :].copy(),
                pos[None, :].copy() if np.linalg.norm(pos) > 1e-6 else None,
            )
        else:
            break
    return out


def _bank_lookup(clipname):
    import os as _os, pickle as _pk

    for _bk in (
        "/tmp/clipbank_en4.pkl",
        "/tmp/clipbank_en2.pkl",
        "/tmp/clipbank_bs2.pkl",
        "/tmp/clipbank_face.pkl",
    ):
        if _os.path.exists(_bk):
            c = _pk.load(open(_bk, "rb")).get(clipname)
            if c is not None:
                return c
    return None


def bake(clipname, upsample=2):
    if Rb is None:
        _load_bind()
    clip = _bank_lookup(clipname)
    if clip is None:
        _naz = "01_game.naz" if __import__("os").path.exists("01_game.naz") else "game.naz"
        for st, hs in efa.grab_blocks(_naz).items():
            if "h" not in hs:
                continue
            try:
                it = list(we.extract_block(hs["h"], hs.get("s")))
            except:
                continue
            for e, h, s in it:
                bn = e.name.rsplit("/", 1)[-1].strip()
                if bn == clipname or bn == clipname + ".animation" or bn[:-10].strip() == clipname:
                    clip = h
                    break
            if clip is not None:
                break
    _ord = _detect_clip_order(clip)
    hdr = np.frombuffer(clip[:8], np.dtype(_ord + "f4"))
    tr = walk(clip, _ord)
    nf = max(len(v[0]) for v in tr.values())
    F = (nf - 1) * upsample + 1
    t = np.linspace(0, nf - 1, F)
    i0 = np.floor(t).astype(int)
    i1 = np.minimum(i0 + 1, nf - 1)
    a = t - i0

    def series(x):
        x = np.asarray(x, np.float64)
        if len(x) == 1:
            return np.tile(x, (F, 1))
        if len(x) != nf:
            x = x[np.linspace(0, len(x) - 1, nf).astype(int)]
        return (1 - a)[:, None] * x[i0] + a[:, None] * x[i1]

    bindloc = np.array([Rb[k] if par[k] < 0 else Rb[par[k]].T @ Rb[k] for k in range(NS)])
    # 2026-07-13: 'BipNN '-prefix-insensitive track lookup (exact wins).
    # medium bind says 'Bip02 RUpArmTwist' but EN1 clip tracks say
    # 'RUpArmTwist' -> twist bones froze at bindloc (user QA: elbow twisting).
    import re

    _canon = lambda n: re.sub(r"^Bip\d+\s+", "", n)
    _trc = {}
    for _n, _v in tr.items():
        _c = _canon(_n)
        if _c not in tr:
            _trc.setdefault(_c, _v)

    def _track(bn):
        if bn in tr:
            return tr[bn]
        _c = _canon(bn)
        return tr.get(_c) or _trc.get(_c)

    L = np.empty((F, NS, 3, 3))
    POS = [None] * NS
    for k in range(NS):
        bn = names[k]
        _tk = _track(bn)
        if _tk is not None:
            q, pos = _tk
            q = np.asarray(q, np.float64).copy()
            for i in range(1, len(q)):
                if (q[i] * q[i - 1]).sum() < 0:
                    q[i] = -q[i]
            qs = series(q)
            qs /= np.maximum(np.linalg.norm(qs, axis=-1, keepdims=True), 1e-12)
            if CONJ:
                qs = qs * np.array([-1, -1, -1, 1.0])
            L[:, k] = Rstd(qs)
            if pos is not None:
                POS[k] = series(pos)
        else:
            L[:, k] = bindloc[k]

    def depth(k):
        d = 0
        j = k
        while par[j] >= 0:
            d += 1
            j = par[j]
        return d

    topo = sorted(range(NS), key=depth)
    Wr = np.empty((F, NS, 3, 3))
    Wt = np.empty((F, NS, 3))
    for k in topo:
        p = par[k]
        if p < 0:
            if names[k] in tr:
                # ABSOLUTE root (engine direct-copy): clip root orientation+position verbatim
                Wr[:, k] = L[:, k]
                Wt[:, k] = POS[k] if POS[k] is not None else np.tile(tb[k], (F, 1))
            else:
                Wr[:, k] = np.tile(Rb[k], (F, 1, 1))
                Wt[:, k] = np.tile(tb[k], (F, 1))
        else:
            Wr[:, k] = np.einsum("fab,fbc->fac", Wr[:, p], L[:, k])
            off = POS[k] if POS[k] is not None else np.tile(tloc[k], (F, 1))
            Wt[:, k] = np.einsum("fab,fb->fa", Wr[:, p], off) + Wt[:, p]
    Pr = np.einsum("fkab,kcb->fkac", Wr, Rb)
    Pt = Wt - np.einsum("fkab,kb->fka", Pr, tb)
    if "--gfix" in sys.argv:
        G = np.load("/tmp/Gfix.npy")
        gt = np.load("/tmp/Gfix_t.npy")
        Pr = np.einsum("ab,fkbc->fkac", G, Pr)
        Pt = np.einsum("ab,fkb->fka", G, Pt) + gt
    # HEADER SOLVED (2026-07-09, claude/work_E/ENGINE_CONSTANTS.md): clip header
    # = [f32 keyRate Hz][f32 duration s][u32 0][u32 keyCount][u32 frameRateScale]
    # keyRate == (keyCount-1)/duration EXACTLY (1163/1163 clips); frameRateScale
    # in {1,2,3} = FULL/HALF/THIRD of the 30fps engine rate (Animation::
    # SetFrameRateScaling dropdown, deep3/part_0019.c).  The old "x3 capture-
    # calibrated" constant was this, misread: hdr[0] (keyRate ~10 for THIRD
    # clips) was taken as the duration.  dur returned = true SECONDS now.
    dur = float(hdr[1])
    return np.concatenate([Pr, Pt[..., None]], axis=-1).astype(np.float32), dur


def fps_for(pal_len, dur):
    """glb fps so pal_len frames span dur seconds (header-exact timing)."""
    return (pal_len - 1) / dur if dur > 0 and pal_len > 1 else 30.0


if __name__ == "__main__":
    up = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 2
    pal, dur = bake(sys.argv[1], up)
    np.save(sys.argv[2], pal)
    fps = fps_for(len(pal), dur)
    print("baked %s %s  dur %.2fs  glb fps %.2f" % (sys.argv[1], pal.shape, dur, fps))
