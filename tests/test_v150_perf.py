"""1.5.0 performance changes that must not change a result: the header scans
of texture_sheet / header_dims / submesh_materials (bytes searches and numpy
views instead of a struct.unpack_from at every byte offset) and the texture
plan rescue (meet-in-the-middle sums, a budget on decoded plans).  Each new
function is compared with a frozen copy of its 1.4.0 code."""

import itertools
import random
import struct
import time

import pytest

import watchmen_extract as we
import test_texture_sheets as tts
import test_v120_regressions as tv


# ---------------------------------------------------------------------------
# frozen 1.4.0 copies (reference)
# ---------------------------------------------------------------------------
def old_texture_sheet(header, order="<"):
    H = we._sheet_hashes()
    n = len(header)
    salt = None
    rt = H["renderType"]
    ti = H["integer"]
    for o in range(0, n - 20):
        s0, lo, hi = struct.unpack_from(order + "III", header, o)
        if lo == rt and hi == ti:
            salt = s0
            start = o
            break
    if salt is None:
        for sh in we._untyped_sheets(header, order):
            if "renderType" in sh:
                return {
                    k: (sh[k] & 0xFFFFFFFF) if we.TEXTURE_SHEET_PROPS[k] == "integer" else sh[k]
                    for k in we.TEXTURE_SHEET_PROPS
                    if k in sh
                }
        return {}
    out = {}
    want = {H[k]: k for k in we.TEXTURE_SHEET_PROPS}
    for o in range(start, n - 20):
        s0, lo, hi = struct.unpack_from(order + "III", header, o)
        if s0 != salt or lo not in want:
            continue
        nm = want[lo]
        typ = we.TEXTURE_SHEET_PROPS[nm]
        if hi != H[typ] or nm in out:
            continue
        if typ == "number":
            out[nm] = struct.unpack_from(order + "f", header, o + 16)[0]
        elif typ == "truth":
            out[nm] = bool(struct.unpack_from(order + "I", header, o + 16)[0])
        else:
            out[nm] = struct.unpack_from(order + "I", header, o + 16)[0]
    return out


def old_header_dims(header):
    pows = set()
    for off in range(0, max(0, len(header) - 3)):
        v = struct.unpack_from("<I", header, off)[0]
        if 32 <= v <= 4096 and (v & (v - 1)) == 0:
            pows.add(v)
    pows = sorted(pows, reverse=True)
    dims = [(a, a) for a in pows]
    for a in pows:
        for b in pows:
            if a != b and a // 2 <= b <= a * 2:
                dims.append((a, b))
    seen, out = set(), []
    for d in dims:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out or [(512, 512), (256, 256), (1024, 1024)]


def old_submesh_materials(header, order="<"):
    _u32 = we._u32
    nmats = len(we.extract_materials(header))
    recs = []
    i = 0
    n = len(header)
    while i < n - 8:
        ln = _u32(header, i, order)
        if 2 <= ln <= 48 and i + 4 + ln <= n:
            sb = header[i + 4 : i + 4 + ln]
            if sb[-1] == 0 and all(32 <= c < 127 for c in sb[:-1]) and sb[:1].isalpha():
                for o in range(i + 4 + ln, min(i + 4 + ln + 24, n - 8), 4):
                    a, b = _u32(header, o, order), _u32(header, o + 4, order)
                    if a == 1 and b < max(nmats, 1):
                        recs.append((i, sb[:-1].decode("latin1"), b))
                        break
                i += 4 + ln
                continue
        i += 1
    dpos = []
    last = -100
    for p_ in range(0, n - 24):
        fa = _u32(header, p_, order)
        nv = _u32(header, p_ + 4, order)
        G = _u32(header, p_ + 8, order)
        fb = _u32(header, p_ + 12, order)
        ib = _u32(header, p_ + 16, order)
        one = _u32(header, p_ + 20, order)
        if (
            G in (5, 6)
            and fa == fb
            and fa in (0, 8)
            and one == 1
            and 3 <= nv <= 300000
            and 6 <= ib <= 8000000
            and ib % 2 == 0
        ):
            if p_ - last >= 24:
                dpos.append(p_)
                last = p_
    out = []
    for k, dp in enumerate(dpos):
        prev = [r for r in recs if r[0] < dp]
        out.append((prev[-1][1], prev[-1][2]) if prev else ("sub%d" % k, k if k < nmats else 0))
    return out


# ---------------------------------------------------------------------------
# inputs: synthetic headers, then the same with random bytes spliced in
# ---------------------------------------------------------------------------
def _noise(rng, n):
    """Random bytes rich in the small words the scans look for."""
    pick = [0, 1, 2, 5, 6, 8, 12, 32, 48, 64, 256, 1024, 4096, 0xFF]
    out = bytearray()
    while len(out) < n:
        if rng.random() < 0.5:
            out += struct.pack(rng.choice("<>") + "I", rng.choice(pick))
        else:
            out += bytes(rng.getrandbits(8) for _ in range(rng.randrange(1, 9)))
    return bytes(out[:n])


def _mutants(base, rng, k=12):
    yield base
    for _ in range(k):
        b = bytearray(base)
        for _ in range(rng.randrange(1, 4)):
            at = rng.randrange(len(b) + 1)
            b[at:at] = _noise(rng, rng.randrange(1, 64))
        if rng.random() < 0.3 and len(b) > 40:
            del b[rng.randrange(len(b) - 20) :][:]
        yield bytes(b)


def _sheet_headers():
    yield tts.SKIN_HDR
    yield tts._header(tts._sheet(0x1111, "a", 5, renderType=1, twoSided=True))
    yield tts._header(
        tts._sheet(0x2222, "a", 5, specularSize=3.5), tts._sheet(0x2222, "b", 6, renderType=2)
    )


def test_texture_sheet_equals_the_1_4_0_scan():
    rng = random.Random(11)
    n = 0
    for base in _sheet_headers():
        for h in _mutants(base, rng):
            for order in "<>":
                assert we.texture_sheet(h, order) == old_texture_sheet(h, order)
                n += 1
    for _ in range(150):
        h = _noise(rng, rng.randrange(0, 600))
        assert we.texture_sheet(h) == old_texture_sheet(h)
    assert n >= 70


def test_texture_sheet_finds_overlapping_salt_words():
    """A salt whose bytes repeat (a record right after a matching byte run)."""
    h = tts._header(tts._sheet(0x01010101, "a", 5, renderType=1))
    h = b"\x01\x01\x01" + h
    assert we.texture_sheet(h) == old_texture_sheet(h) != {}


def test_header_dims_equals_the_1_4_0_scan():
    rng = random.Random(5)
    for _ in range(300):
        h = _noise(rng, rng.randrange(0, 400))
        assert we.header_dims(h) == old_header_dims(h)
    for v in (32, 64, 4096, 8192, 31, 33):
        for pad in range(4):
            h = b"\xaa" * pad + struct.pack("<I", v) + b"\xbb" * pad
            assert we.header_dims(h) == old_header_dims(h)
    assert we.header_dims(b"") == old_header_dims(b"") == [(512, 512), (256, 256), (1024, 1024)]


def _model_headers():
    joints = [(0, 0, 0, 0)] * 8
    for order in "<>":
        yield order, tv.skinned_model(order, joints)[0]
        yield (
            order,
            tv.skinned_model(
                order, joints, nsub=3, materials=["a", "b", "c"], piece_mats=[2, 0, 1]
            )[0],
        )


def test_submesh_materials_equals_the_1_4_0_scan():
    rng = random.Random(3)
    n = 0
    for order, base in _model_headers():
        for h in _mutants(base, rng, 10):
            assert we.submesh_materials(h, order) == old_submesh_materials(h, order)
            n += 1
    for _ in range(100):
        h = _noise(rng, rng.randrange(0, 500))
        for order in "<>":
            assert we.submesh_materials(h, order) == old_submesh_materials(h, order)
    assert n >= 40


def test_submesh_materials_without_numpy(monkeypatch):
    order, h = next(_model_headers())
    want = old_submesh_materials(h, order)
    monkeypatch.setattr(we, "HAVE_IMG", False)
    assert we.submesh_materials(h, order) == want


def test_u32_view_of_every_offset():
    rng = random.Random(1)
    for n in range(0, 23):
        b = bytes(rng.getrandbits(8) for _ in range(n))
        for order in "<>":
            W = we._u32_all(b, order)
            assert W.tolist() == [struct.unpack_from(order + "I", b, o)[0] for o in range(n - 3)]


def test_the_scans_are_faster(capsys):
    """Report the speed-up on a 400 KB header (no assertion on the machine)."""
    rng = random.Random(9)
    big = _noise(rng, 400_000)
    for new, old in ((we.header_dims, old_header_dims), (we.texture_sheet, old_texture_sheet)):
        t0 = time.perf_counter()
        a = new(big)
        t1 = time.perf_counter()
        b = old(big)
        t2 = time.perf_counter()
        assert a == b
        print("%s: %.4f s, 1.4.0 %.4f s" % (new.__name__, t1 - t0, t2 - t1))


# ---------------------------------------------------------------------------
# texture plan rescue
# ---------------------------------------------------------------------------
def old_rescue_texture_plan(hdr, stream, order="<"):
    """1.4.0 _rescue_texture_plan (frozen copy)."""
    info = we.parse_texture_header(hdr, order)
    if not info or not info["images"]:
        return None
    p0 = info["images"][0]["rec_off"]
    end = we._tex_path_off(hdr)
    hits = []
    for pos in range(p0, max(p0, end - 27)):
        v = we._valid_rec(hdr, pos, powtwo=True, order=order)
        if v and (not hits or pos - hits[-1][0] >= 28):
            hits.append((pos, v))
    if not (1 <= len(hits) <= 6):
        return None
    cands = [tuple(hits)]
    if len(hits) > 1:
        for k in range(len(hits)):
            cands.append(tuple(hits[:k] + hits[k + 1 :]))
        cands += [(h,) for h in hits]
    best = None
    for cand in cands:
        recs = [(v["enum"], v["aw"], v["ah"]) for _, v in cand]
        if len(recs) > 4:
            continue
        sols = []
        for mips in itertools.product(range(1, 14), repeat=len(recs)):
            if sum(we._chain_bytes(e, w, h, m) for (e, w, h), m in zip(recs, mips)) == len(stream):
                sols.append(mips)
                if len(sols) > 400:
                    sols = []
                    break
        for mips in sols:
            off = 0
            tot = 0.0
            for (e, w, h), m in zip(recs, mips):
                img = we._decode_one_layer(stream[off:], e, w, h)
                if img is None:
                    tot = 1e9
                    break
                tot += we._coherence(img)
                off += we._chain_bytes(e, w, h, m)
            if tot < 1e9 and (best is None or tot < best[0]):
                best = (tot, [(e, w, h, m) for (e, w, h), m in zip(recs, mips)])
    return best[1] if best else None


def _brute(recs, total):
    """The 1.4.0 search: the product of 1..13 mips per layer, in order."""
    sols = []
    for mips in itertools.product(range(1, 14), repeat=len(recs)):
        if sum(we._chain_bytes(e, w, h, m) for (e, w, h), m in zip(recs, mips)) == total:
            sols.append(mips)
    return sols


@pytest.mark.parametrize(
    "recs",
    [
        [(5, 256, 256)],
        [(5, 64, 64), (7, 32, 32)],
        [(7, 128, 128), (5, 64, 64), (3, 16, 16)],
        [(5, 4, 4), (5, 4, 4), (7, 8, 8), (5, 1, 1)],
    ],
)
def test_exact_mip_sums_equal_the_product_search(recs):
    sizes = {
        sum(we._chain_bytes(e, w, h, m) for (e, w, h), m in zip(recs, ms))
        for ms in itertools.product(range(1, 14), repeat=len(recs))
    }
    for total in sorted(sizes)[:: max(1, len(sizes) // 12)] + [1, 12345]:
        assert we._exact_mip_sums(recs, total) == _brute(recs, total)


def _crafted(monkeypatch, recs, stream_len):
    """A texture header whose layer plan fails and whose record scan finds
    `recs` (the drift-scan inputs are stubbed: the search is what is tested)."""
    hits = {i * 28: dict(enum=e, aw=w, ah=h, mip=1) for i, (e, w, h) in enumerate(recs)}
    monkeypatch.setattr(we, "parse_texture_header", lambda h, o="<": {"images": [{"rec_off": 0}]})
    monkeypatch.setattr(we, "_tex_path_off", lambda h: 28 * len(recs) + 27)
    monkeypatch.setattr(we, "_valid_rec", lambda h, pos, powtwo=False, order="<": hits.get(pos))
    decoded = []

    def dec(buf, e, w, h):
        decoded.append((e, w, h))
        import numpy as np

        return np.zeros((max(1, h), max(1, w), 3), np.uint8)

    monkeypatch.setattr(we, "_decode_one_layer", dec)
    monkeypatch.setattr(we, "_coherence", lambda img: 1.0)
    return b"\0" * stream_len, decoded


def test_a_failing_header_returns_fast(monkeypatch):
    """Six large records and a stream no plan fits: 13 candidate record sets, each
    searched exactly; 1.4.0 summed up to 28,561 chains per set (~370k)."""
    recs = [(7, 2048, 2048)] * 4 + [(5, 1024, 1024)] * 2
    stream, decoded = _crafted(monkeypatch, recs, 12345)
    t0 = time.perf_counter()
    assert we._rescue_texture_plan(b"x" * 400, stream) is None
    # nothing decoded is the property; the time bound only catches a hang
    assert decoded == [] and time.perf_counter() - t0 < 30.0


def test_the_rescue_gives_up_after_its_budget(monkeypatch):
    recs = [(5, 4, 4)] * 3  # tiny chains: many plans of one size
    stream, decoded = _crafted(monkeypatch, recs, 48)
    logs = []
    t0 = time.perf_counter()
    assert we._rescue_texture_plan(b"x" * 200, stream, log=logs.append, max_plans=5) is None
    assert time.perf_counter() - t0 < 30.0  # a hang only; the budget is checked below
    assert logs == [
        "      ! texture plan rescue gave up after 5 candidate plans (RESCUE_MAX_PLANS)"
    ]
    assert we.is_warning_line(logs[0])
    # within the budget: the plan of the 1.4.0 search
    plan = we._rescue_texture_plan(b"x" * 200, stream, log=logs.append)
    assert plan == old_rescue_texture_plan(b"x" * 200, stream) and len(logs) == 1


@pytest.mark.parametrize("seed", range(6))
def test_the_rescue_picks_the_1_4_0_plan(monkeypatch, seed):
    """Random record sets and stream sizes, layer scores that differ per plan:
    the same plan (or None) as the 1.4.0 search."""
    rng = random.Random(seed)
    recs = [
        (rng.choice((3, 5, 7)), 1 << rng.randrange(2, 8), 1 << rng.randrange(2, 8))
        for _ in range(rng.randrange(1, 5))
    ]
    stream, _ = _crafted(monkeypatch, recs, 1)
    ms = [rng.randrange(1, 14) for _ in recs]
    size = sum(we._chain_bytes(e, w, h, m) for (e, w, h), m in zip(recs, ms))
    stream = bytes(rng.getrandbits(8) for _ in range(size))
    monkeypatch.setattr(we, "_coherence", lambda img: float(img.shape[0] * 7 % 5 + img.shape[1]))
    assert we._rescue_texture_plan(b"x" * 200, stream) == old_rescue_texture_plan(
        b"x" * 200, stream
    )
