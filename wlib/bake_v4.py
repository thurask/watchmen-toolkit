#!/usr/bin/env python3
# Baker v3 (final): engine-verified decode. quat/10000, POSITION/1000 (Ghidra-confirmed),
# t0 = position keys + const quat, file hierarchy, root motion relative to frame 0,
# twist alignment (engine pass 0x5958f5) is applied; bake(twist_align=False) leaves it out.
# usage: python3 bake_v4.py CLIP OUT.npy [upsample] --bind BIND.npz
import sys, struct, numpy as np, watchmen_extract as we, export_female_anims as efa

# 2026-07-24: this module used to read --bind/--conj out of sys.argv AT IMPORT
# TIME, which forced every caller (and watchmenlib, at import) to rewrite the
# host program's sys.argv and then importlib.reload() this module.  bake() now
# takes bind= and conj= directly; argv is parsed only under __main__.
CONJ = True  # engine-exact palette gauge (conjugated FK); see docs/ENGINE_CONSTANTS.md

# Revision of the pose rule; stored in every cached bake (characters_export.bake_cache), so a
# cache written by another rule is baked again.  2 = the engine's rule for the constant
# position of track types 1 / 3 and for roots (docs/ENGINE_CONSTANTS.md, "Clip tracks:
# constant position of type 1 / 3"): the constant is added to the rest local position
# (0x594d38-0x594d49), and the rest pose has every parent-less bone at 0 (0x593685).
# 3 = the twist pass is applied and clip tracks are matched to bones by exact name
# (0x594dde, 0x53c0dc).
POSE_RULE = 3

BIND = None
# import-safe: a missing bind only matters once bake() is called (fresh-install
# bootstrap needs to import this module to BUILD the binds first).
Rb = tb = tloc = par = names = None
NS = 0


def _load_bind(path=None):
    global BIND, Rb, tb, tloc, par, NS, names
    if path:
        BIND = path
    if not BIND:
        raise ValueError("no bind loaded: call bake(clip, bind='.../bind_<skel>_file_v1.npz')")
    bt = np.load(BIND, allow_pickle=True)
    Rb = bt["Rb"]
    tb = bt["tb"]
    tloc = bt["tloc"]
    par = bt["par"]
    NS = len(Rb)
    names = [str(n) for n in bt["names"]]


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


def twist_pairs(names, par):
    """[(T, S)]: the twist bones the engine aligns each frame and their partners, as the
    pair builder 0x545019 finds them: T is a bone whose name contains "Twist" and whose
    parent's name does not; S is the lowest-index bone below T's index with the same
    parent.  A twist bone without such a sibling has no pair."""
    out = []
    for k in range(len(names)):
        p = par[k]
        if "Twist" not in names[k] or p < 0 or "Twist" in names[p]:
            continue
        for j in range(k):
            if par[j] == p:
                out.append((k, j))
                break
    return out


def apply_twist_align(Wr, Wt, names, par):
    """The engine's per-frame twist pass (0x5958f5; read from code; measured against
    captured palettes), in place on world rotations Wr (F, N, 3, 3) and positions Wt (F, N, 3)
    whose column 0 is the bone's X axis: each twist bone T is turned by the shortest arc
    that puts its X axis on its partner's (arc 0x41f896; skipped when |a x b| <= 1e-5),
    its position is kept and its descendants follow.  Returns the pairs."""
    n = len(names)
    pairs = twist_pairs(names, par)
    for k, s in pairs:
        desc = []
        for d in range(n):
            j = par[d]
            while j >= 0 and j != k:
                j = par[j]
            if j == k:
                desc.append(d)
        a, b = Wr[:, k, :, 0], Wr[:, s, :, 0]
        c = np.cross(a, b)
        cn = np.linalg.norm(c, axis=-1)
        for f in np.nonzero(cn > 1e-5)[0]:
            ax = c[f] / cn[f]
            th = np.arctan2(cn[f], float(a[f] @ b[f]))
            K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0.0]])
            A = np.eye(3) + np.sin(th) * K + (1 - np.cos(th)) * (K @ K)
            Wr[f, k] = A @ Wr[f, k]
            for d in desc:
                Wr[f, d] = A @ Wr[f, d]
                Wt[f, d] = A @ (Wt[f, d] - Wt[f, k]) + Wt[f, k]
    return pairs


# First byte the track-name scan looks at.  The clip header is five words and the name list
# starts at byte 29 in every shipped clip (measured, 6,912 files of Parts 1 and 2 on all
# platforms).  A scan from byte 0 read the key count 0x372 of the big-endian
# EN4_EXP_MOV_dance_cage_small_C as the length of a name "r" at byte 11 and baked that
# clip as a still pose.  Stored in every cached bake as `scan`.
NAME_SCAN_START = 20


def _name_scan(h, order, start=NAME_SCAN_START):
    """Offset of the first length-prefixed track name of clip `h` read in byte order
    `order`, looking from byte `start`; None when there is none below byte 300."""
    for i in range(start, 300):
        if i + 4 > len(h):
            break
        L = struct.unpack_from(order + "I", h, i)[0]
        if 2 <= L <= 40 and i + 4 + L <= len(h):
            s = h[i + 4 : i + 4 + L]
            if s[:1].isalpha() and all(32 <= c < 127 or c == 0 for c in s):
                return i
    return None


def _detect_clip_order(h, start=NAME_SCAN_START):
    """'<' PC / '>' X360+PS3.  Console .animation clips are big-endian; pick the
    order whose length-prefixed track-name scan lands on a real name first."""
    for order in ("<", ">"):
        if _name_scan(h, order, start) is not None:
            return order
    return "<"


def scan_start_matters(h):
    """Does clip `h` (its first 400 bytes are enough) read differently when the name scan
    starts at byte 0, as it did before NAME_SCAN_START?  A cached bake without `scan` of
    such a clip is stale (characters_export.bake_is_current)."""
    old = _detect_clip_order(h, 0)
    new = _detect_clip_order(h)
    return (old, _name_scan(h, old, 0)) != (new, _name_scan(h, new))


def walk(h, order=None, types=None):
    """{track name: (quaternion keys, position keys or None)} of one clip.  A zero constant
    position (types 1 and 3) is reported as None.  `types`, when given, is filled with
    {track name: track type 0..3}: a one-key keyed track has the shape of a constant, and
    only the type says whether the engine adds the rest pose to it."""
    if order is None:
        order = _detect_clip_order(h)
    f4 = np.dtype(order + "f4")
    i2 = np.dtype(order + "i2")
    o = _name_scan(h, order)
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
        if types is not None and t in (0, 1, 2, 3):
            types[name] = t
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


def default_naz():
    """The archive `bake` and `char` read when none is named: `01_game.naz` in the
    current directory when it exists, else `game.naz` there."""
    import os

    return "01_game.naz" if os.path.exists("01_game.naz") else "game.naz"


def archive_clip(clipname, naz, marks=None):
    """Bytes of clip `clipname` in archive `naz` (None when no block has it).  `marks`,
    when given, is {lower-case path ending: False}: each one is set True when an entry of
    the archive ends with it (path separators as '/'), and the walk then reads every block
    instead of stopping at the clip."""
    clip = None
    for st, hs in efa.grab_blocks(naz).items():
        if "h" not in hs:
            continue
        try:
            it = list(we.extract_block(hs["h"], hs.get("s")))
        except Exception:
            continue
        for e, h, s in it:
            if marks:
                low = e.name.replace("\\", "/").strip().lower()
                for m in marks:
                    if low.endswith(m):
                        marks[m] = True
            if clip is not None:
                continue
            bn = e.name.rsplit("/", 1)[-1].strip()
            if bn == clipname or bn == clipname + ".animation" or bn[:-10].strip() == clipname:
                clip = h
                if not marks:
                    return clip
        if clip is not None and marks and all(marks.values()):
            break
    return clip


def bake(
    clipname,
    upsample=2,
    bind=None,
    conj=None,
    bank=None,
    root_rest="engine",
    naz=None,
    twist_align=None,
    track_names="exact",
):
    """Clip name -> (palettes (F,NB,3,4), duration_s), engine-exact.

    bind : path to a bind npz (see build_bind_file / watchmenlib.ensure_binds).
           Required the first time; cached on the module afterwards.
    conj : palette gauge; None keeps the current setting (engine default True).
    bank : optional {clipname: header_bytes_or_path} to look clips up in,
           instead of walking the naz.
    naz  : the archive to find the clip in when no bank has it (None: default_naz()).
    root_rest : where a parent-less bone without position keys sits (no track, or a zero
           constant of track type 1 / 3).  "engine" (default): at 0, as in the engine's
           rest pose, which zeroes the position of every parent-less bone (0x593685).
           "bind": at its bind position; for a bind built from a part's own node list (a
           head model), whose roots are not the roots of the character's skeleton.
    twist_align: the engine's per-frame twist pass (0x5958f5, pairs 0x545019).  None
           (default): applied in the engine gauge.  Measured on captured palettes of five
           skeletons: closer on 729 of 729 samples it moves by more than 0.5°, largest
           worsening 0.20°.
    track_names: "exact" (default) matches a track to the bone of the same name,
           case-sensitive, as the engine does (channel table 0x53c0dc / 0x539eaf, map
           0x594dde); a bone without a track keeps its rest local.  "prefix" also accepts a
           name that differs only by a leading 'BipNN '.
    """
    global CONJ
    if root_rest not in ("engine", "bind"):
        raise ValueError("root_rest must be 'engine' or 'bind', not %r" % (root_rest,))
    if conj is not None:
        CONJ = bool(conj)
    if twist_align is None:
        twist_align = CONJ
    if twist_align and not CONJ:
        raise ValueError("twist_align needs the engine gauge (conj=True)")
    if track_names not in ("exact", "prefix"):
        raise ValueError("track_names must be 'exact' or 'prefix', not %r" % (track_names,))
    if bind:
        _load_bind(bind)
    elif Rb is None:
        _load_bind()
    if bank is not None:
        _b = bank.get(clipname)
        if isinstance(_b, str):
            with open(_b, "rb") as _fh:
                _b = _fh.read()
        clip = _b
    else:
        clip = None
    if clip is None:
        _naz = naz or default_naz()
        if not __import__("os").path.exists(_naz):
            raise FileNotFoundError(
                "clip %r is in no clip bank and the archive %r does not exist: name the"
                " archive (`watchmen bake CLIP BIND.npz OUT.npy NAZ`, bake(naz=...))"
                % (clipname, _naz)
            )
        clip = archive_clip(clipname, _naz)
    if clip is None:
        raise KeyError("clip %r not found (not in the bank and not in the naz)" % clipname)
    _ord = _detect_clip_order(clip)
    hdr = np.frombuffer(clip[:8], np.dtype(_ord + "f4"))
    ttype = {}
    tr = walk(clip, _ord, ttype)
    if not tr:
        raise ValueError("no animation tracks decoded from clip %r" % clipname)
    # 2026-08-17: frame count from ALL key tracks, not quats only -- a type-0
    # track (const quat + position keys) contributed 1 before, so a clip whose
    # longest track was positional got its position keys down-sampled (worst
    # case, all-const rotations: collapsed to a single frame).
    nf = max(max(len(q), len(p) if p is not None else 1) for q, p in tr.values())
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
    # Tracks bind to bones by exact, case-sensitive name (0x53c0dc / 0x539eaf, 0x594dde); an
    # unmatched track is skipped (0x594cac).  Part 2 medium: `Bip02 R/LUpArmTwist(1)` have no
    # track in 221 of 222 EN1 clips and are placed by the twist pass (capture: median 0.16° /
    # 0.03° against 34° / 30° with the track and no pass).  track_names='prefix' keeps the
    # 'BipNN '-insensitive lookup for Part 1, where `Attach RHand` has only a
    # `Bip01 Attach RHand` track in 983 clips and no capture exists.
    import re

    _canon = lambda n: re.sub(r"^Bip\d+\s+", "", n)
    _trc = {}
    for _n, _v in tr.items():
        _c = _canon(_n)
        if _c not in tr:
            _trc.setdefault(_c, _v)

    _tyc = {}
    for _n, _v in ttype.items():
        _c = _canon(_n)
        if _c not in tr:
            _tyc.setdefault(_c, _v)

    def _track(bn):
        if bn in tr:
            return tr[bn]
        if track_names != "prefix":
            return None
        _c = _canon(bn)
        return tr.get(_c) or _trc.get(_c)

    def _track_type(bn):
        if bn in tr:
            return ttype.get(bn)
        if track_names != "prefix":
            return None
        _c = _canon(bn)
        return ttype.get(_c) if _c in tr else _tyc.get(_c)

    L = np.empty((F, NS, 3, 3))
    POS = [None] * NS
    ADD = [False] * NS  # position is a type-1/3 constant: the engine adds the rest local to it
    for k in range(NS):
        bn = names[k]
        _tk = _track(bn)
        if _tk is not None:
            q, pos = _tk
            ADD[k] = _track_type(bn) in (1, 3)
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
            # The engine's rest pose has every parent-less bone at position 0 (0x593685), so
            # a root's keys and constants are absolute, and a root with a zero constant
            # (types 1 / 3) or without a track is at 0, not at its bind position tb[k].
            rest0 = 0.0 if root_rest == "engine" else np.tile(tb[k], (F, 1))
            if _track(names[k]) is not None:  # the lookup the bone's keys were read with
                # ABSOLUTE root (engine direct-copy): clip root orientation+position verbatim
                Wr[:, k] = L[:, k]
                Wt[:, k] = POS[k] if POS[k] is not None else rest0
            else:
                Wr[:, k] = np.tile(Rb[k], (F, 1, 1))
                Wt[:, k] = rest0
        else:
            Wr[:, k] = np.einsum("fab,fbc->fac", Wr[:, p], L[:, k])
            if POS[k] is None:
                off = np.tile(tloc[k], (F, 1))
            elif ADD[k]:
                # type-1/3 constant on a non-root bone = rest local + constant (0x594d49).
                # The engine also scales the rest position per bone (0x4c2fcd, default 1);
                # the toolkit does not read that list; whether a shipped character carries one is
                # not established.
                off = tloc[k] + POS[k]
            else:
                off = POS[k]
            Wt[:, k] = np.einsum("fab,fb->fa", Wr[:, p], off) + Wt[:, p]
    if twist_align:
        apply_twist_align(Wr, Wt, names, par)
    Pr = np.einsum("fkab,kcb->fkac", Wr, Rb)
    Pt = Wt - np.einsum("fkab,kb->fka", Pr, tb)
    # HEADER SOLVED (2026-07-09, docs/ENGINE_CONSTANTS.md): clip header
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
    _bind = sys.argv[sys.argv.index("--bind") + 1] if "--bind" in sys.argv else None
    _conj = False if "--no-conj" in sys.argv else True
    up = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 2
    pal, dur = bake(sys.argv[1], up, bind=_bind, conj=_conj)
    np.save(sys.argv[2], pal)
    fps = fps_for(len(pal), dur)
    print("baked %s %s  dur %.2fs  glb fps %.2f" % (sys.argv[1], pal.shape, dur, fps))
