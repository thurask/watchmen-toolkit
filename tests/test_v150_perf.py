"""1.5.0 performance changes that must not change a result: the header scans
of texture_sheet / submesh_materials (bytes searches and numpy views instead of
a struct.unpack_from at every byte offset).  Each new function is compared with
a frozen copy of its 1.4.0 code."""

import random
import struct
import time


import material_refs
import texture_sheet
import test_texture_sheets as tts
import test_v120_regressions as tv


# ---------------------------------------------------------------------------
# frozen 1.4.0 copies (reference)
# ---------------------------------------------------------------------------
def old_texture_sheet(header, order="<"):
    H = texture_sheet.sheet_hashes()
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
        for sh in texture_sheet._untyped_sheets(header, order):
            if "renderType" in sh:
                return {
                    k: (sh[k] & 0xFFFFFFFF)
                    if texture_sheet.TEXTURE_SHEET_PROPS[k] == "integer"
                    else sh[k]
                    for k in texture_sheet.TEXTURE_SHEET_PROPS
                    if k in sh
                }
        return {}
    out = {}
    want = {H[k]: k for k in texture_sheet.TEXTURE_SHEET_PROPS}
    for o in range(start, n - 20):
        s0, lo, hi = struct.unpack_from(order + "III", header, o)
        if s0 != salt or lo not in want:
            continue
        nm = want[lo]
        typ = texture_sheet.TEXTURE_SHEET_PROPS[nm]
        if hi != H[typ] or nm in out:
            continue
        if typ == "number":
            out[nm] = struct.unpack_from(order + "f", header, o + 16)[0]
        elif typ == "truth":
            out[nm] = bool(struct.unpack_from(order + "I", header, o + 16)[0])
        else:
            out[nm] = struct.unpack_from(order + "I", header, o + 16)[0]
    return out


def old_submesh_materials(header, order="<"):
    _u32 = material_refs.u32_at
    nmats = len(material_refs.extract_materials(header))
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
                assert texture_sheet.texture_sheet(h, order) == old_texture_sheet(h, order)
                n += 1
    for _ in range(150):
        h = _noise(rng, rng.randrange(0, 600))
        assert texture_sheet.texture_sheet(h) == old_texture_sheet(h)
    assert n >= 70


def test_texture_sheet_finds_overlapping_salt_words():
    """A salt whose bytes repeat (a record right after a matching byte run)."""
    h = tts._header(tts._sheet(0x01010101, "a", 5, renderType=1))
    h = b"\x01\x01\x01" + h
    assert texture_sheet.texture_sheet(h) == old_texture_sheet(h) != {}


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
            assert material_refs.submesh_materials(h, order) == old_submesh_materials(h, order)
            n += 1
    for _ in range(100):
        h = _noise(rng, rng.randrange(0, 500))
        for order in "<>":
            assert material_refs.submesh_materials(h, order) == old_submesh_materials(h, order)
    assert n >= 40


def test_u32_view_of_every_offset():
    rng = random.Random(1)
    for n in range(0, 23):
        b = bytes(rng.getrandbits(8) for _ in range(n))
        for order in "<>":
            W = material_refs._u32_all(b, order)
            assert W.tolist() == [struct.unpack_from(order + "I", b, o)[0] for o in range(n - 3)]


def test_the_scans_are_faster(capsys):
    """Report the speed-up on a 400 KB header (no assertion on the machine)."""
    rng = random.Random(9)
    big = _noise(rng, 400_000)
    for new, old in ((texture_sheet.texture_sheet, old_texture_sheet),):
        t0 = time.perf_counter()
        a = new(big)
        t1 = time.perf_counter()
        b = old(big)
        t2 = time.perf_counter()
        assert a == b
        print("%s: %.4f s, 1.4.0 %.4f s" % (new.__name__, t1 - t0, t2 - t1))
