"""The one reader of the 29-byte texture descriptor and of the Texture header
(`texture_header.read_descriptor`, `descriptor_ok`, `layer_bytes`,
`read_texture_header`) and the one top-mip decode by platform
(`texture_decode.layer_image`), on synthetic inputs: a PC mip chain, an
Xbox 360 layer with its stored size, a PS3 layer behind its RSX descriptor."""

import struct

import numpy as np
import pytest

import texture_decode
import texture_header as th


def _desc(order, w, h, en, mips, typ=1, alpha=0, size=0, usage=0):
    return struct.pack(order + "5IBII", w, h, en, usage, typ, alpha, mips, size)


def _str(s, order="<"):
    b = s.encode("latin1") + b"\0"
    return struct.pack(order + "I", len(b)) + b


def _header(order, slots, path="/data/art/x/Thing.bmp", nf=1, anim=0):
    b = _str("Texture", order) + struct.pack(order + "I", 2) + bytes(8)
    b += struct.pack(order + "I", nf) + bytes([anim])
    for _ in range(nf):
        b += slots[0]
        for k in range(1, 8):
            b += b"\x01" + slots[k] if k in slots else b"\x00"
        b += _str(path, order)
    return b


@pytest.mark.parametrize("order", ["<", ">"])
def test_read_descriptor_fields(order):
    data = b"\x01" + _desc(order, 64, 32, 5, 7, typ=2, alpha=1, size=4096, usage=3)
    d = th.read_descriptor(data, 1, order)
    assert d == {
        "width": 64,
        "height": 32,
        "enum": 5,
        "usage": 3,
        "type": 2,
        "alpha": 1,
        "mips": 7,
        "size": 4096,
    }
    assert th.descriptor_ok(d)
    assert th.pack_descriptor(d, order) == data[1:]
    assert th.pack_descriptor(dict(d, alpha=True), order) == data[1:]
    with pytest.raises(th.TextureHeaderError):
        th.read_descriptor(data, 2, order)


@pytest.mark.parametrize(
    "field, value",
    [("width", 0), ("height", 8193), ("type", 3), ("alpha", 2), ("mips", 0), ("mips", 15)],
)
def test_descriptor_ok_refuses(field, value):
    d = th.read_descriptor(_desc("<", 8, 8, 5, 4), 0, "<")
    d[field] = value
    assert not th.descriptor_ok(d)


@pytest.mark.parametrize("order", ["<", ">"])
def test_read_texture_header_matches_the_wrapper(order):
    hdr = _header(order, {0: _desc(order, 8, 8, 5, 4), 3: _desc(order, 4, 4, 5, 3, alpha=1)})
    got = th.read_texture_header(hdr, order)
    assert got == th.parse_texture_frames(hdr, order)
    slots = got["frames"][0]["slots"]
    assert [d["slot"] if d else None for d in slots] == [0, None, None, 3, None, None, None, None]
    assert slots[3]["alpha"] is True and slots[3]["chain"] == th.chain_bytes_exact(5, 4, 4, 3)
    assert got["frames"][0]["path"] == "/data/art/x/Thing.bmp"
    assert got["end"] == len(hdr)


def test_read_texture_header_raises_where_the_wrapper_gives_none():
    good = _header("<", {0: _desc("<", 8, 8, 5, 4)})
    for bad in (
        good[:-3],  # source path cut short
        _header("<", {0: _desc("<", 8, 8, 11, 4)}),  # format enum the PC does not use
        _header("<", {0: _desc("<", 8, 8, 5, 4)}, nf=0),  # no frames
        _str("Model") + bytes(64),  # another class
    ):
        with pytest.raises(th.TextureHeaderError):
            th.read_texture_header(bad, "<")
        assert th.parse_texture_frames(bad, "<") is None


def test_layer_bytes_pc_chain_padded_rows():
    d = th.read_descriptor(_desc("<", 3, 2, 3, 2), 0, "<")  # L8 3x2, 2 mips
    # rows padded to 4 bytes: 4*2 + 4*1
    assert th.layer_bytes(d, "<", b"") == 12 == th.chain_bytes_exact(3, 3, 2, 2)
    d["enum"] = 11
    with pytest.raises(th.TextureHeaderError, match="texture format id 11"):
        th.layer_bytes(d, "<", b"")


def test_layer_bytes_x360_descriptor_size():
    d = th.read_descriptor(_desc(">", 32, 32, 5, 1, size=8192), 0, ">")
    assert th.layer_bytes(d, ">", b"") == 8192


def test_layer_bytes_ps3_rsx_descriptor():
    d = th.read_descriptor(_desc(">", 4, 4, 5, 1), 0, ">")
    rsx = struct.pack(">3I", 0, 0, 8) + bytes(24)
    assert th.layer_bytes(d, ">", b"\xee" + rsx + bytes(8), 1) == 44
    with pytest.raises(th.TextureHeaderError, match="truncated RSX descriptor"):
        th.layer_bytes(d, ">", rsx[:20])


def test_layer_image_pc_linear_rows_unpadded():
    d = th.read_descriptor(_desc("<", 3, 2, 3, 1), 0, "<")  # L8 3x2, pitch 4
    data = bytes([1, 2, 3, 0xFF, 4, 5, 6, 0xFF])
    img = texture_decode.layer_image(d, data, "<")
    assert img.tolist() == [[1, 2, 3], [4, 5, 6]]


def test_layer_image_pc_argb():
    d = th.read_descriptor(_desc("<", 2, 1, 1, 1), 0, "<")  # A8R8G8B8, BGRA in memory
    img = texture_decode.layer_image(d, bytes([10, 20, 30, 40, 50, 60, 70, 80]), "<")
    assert img.tolist() == [[[30, 20, 10, 40], [70, 60, 50, 80]]]


def test_layer_image_x360_is_the_tiled_base_level():
    d = th.read_descriptor(_desc(">", 16, 24, 5, 1, size=8 * 32 * 32), 0, ">")
    raw = np.random.default_rng(7).integers(0, 256, 8 * 32 * 32, np.uint8).tobytes()
    got = texture_decode.layer_image(d, raw, ">")
    want = texture_decode.x360_base_level(raw, 5, 16, 24)
    assert got.shape == (24, 16, 4) and np.array_equal(got, want)


def test_layer_image_ps3_skips_the_rsx_descriptor():
    d = th.read_descriptor(_desc(">", 8, 8, 5, 1), 0, ">")
    chain = np.random.default_rng(3).integers(0, 256, 32, np.uint8).tobytes()
    data = struct.pack(">3I", 0, 0, len(chain)) + bytes(24) + chain
    got = texture_decode.layer_image(d, data, ">")
    want = texture_decode.ps3_layer_image(chain, {"enum": 5, "aw": 8, "ah": 8}, False)
    assert got.shape == (8, 8, 4) and np.array_equal(got, want)
    assert np.array_equal(got, texture_decode.decode_one_layer(chain, 5, 8, 8))


def test_layer_image_none_for_cube_or_unknown_format():
    d = th.read_descriptor(_desc("<", 4, 4, 5, 1, typ=2), 0, "<")
    assert texture_decode.layer_image(d, bytes(64), "<") is None
    d = th.read_descriptor(_desc("<", 4, 4, 11, 1), 0, "<")
    assert texture_decode.layer_image(d, bytes(64), "<") is None


# ---------------------------------------------------------------------------
# A struct-based reading of the same layout, the reference: on cut and mutated
# headers it and the ByteReader reader give the same result.
# ---------------------------------------------------------------------------
def _reference_anim_tail(hdr, p, order="<"):
    """Reference reading (struct.unpack_from)."""

    def u32():
        nonlocal p
        (v,) = struct.unpack_from(order + "I", hdr, p)
        p += 4
        return v

    def count(item):
        n = u32()
        if n * item > len(hdr) - p:
            raise ValueError("count %d" % n)
        return n

    def cycle(depth):
        if depth > 8:
            raise ValueError("cycle depth")
        c = {"head": [u32(), u32(), u32()]}
        c["steps"] = [{"sub_cycle": bool(u32()), "index": u32()} for _ in range(count(8))]
        c["items"] = [
            dict(
                zip(
                    ("frame_min", "frame_max", "time_min_ms", "time_max_ms", "id"),
                    vals,
                    strict=True,
                )
            )
            for vals in ([u32() for _ in range(5)] for _ in range(count(20)))
        ]
        c["sub_cycles"] = [cycle(depth + 1) for _ in range(count(20))]
        return c

    serial = u32()
    return {"serial": serial, "cycle": cycle(0)}, p


def _reference_frames(hdr, order="<"):
    """Reference reading (struct.unpack_from)."""
    if not th.is_texture_header(hdr, order):
        return None
    enums = th.TEX_ENUMS if order == "<" else th.TEX_FMT
    try:
        (tlen,) = struct.unpack_from(order + "I", hdr, 0)
        (nd,) = struct.unpack_from(order + "I", hdr, 4 + tlen)
        p = 4 + tlen + 4 + 4 * nd  # FUN_00511f96: bag = nd dwords
        (nf,) = struct.unpack_from(order + "I", hdr, p)
        anim = hdr[p + 4]
        p += 5
        if not 1 <= nf <= 1024 or anim > 1:
            return None
        frames = []
        for _ in range(nf):
            slots = []
            for k in range(th.TEXTURE_SLOTS):
                if k:
                    present = hdr[p]
                    p += 1
                    if present > 1:
                        return None
                    if not present:
                        slots.append(None)
                        continue
                w, h, en, usage, typ, alpha, mip, size = struct.unpack_from(order + "5IBII", hdr, p)
                p += th._TEX_DESC
                if en not in enums or typ not in (1, 2) or alpha > 1:
                    return None
                if not (0 < w <= 8192 and 0 < h <= 8192 and 1 <= mip <= 14):
                    return None
                slots.append(
                    {
                        "slot": k,
                        "enum": en,
                        "fmt": th.TEX_FMT[en][0],
                        "aw": w,
                        "ah": h,
                        "mip": mip,
                        "type": typ,
                        "alpha": bool(alpha),
                        "usage": usage,
                        # slot 7 is the record the stride walk reaches through
                        # a 4-byte "drift" (four absent-slot bytes): the specSize map
                        "drift": k == 7,
                        "chain": th.chain_bytes_exact(en, w, h, mip),
                        "size": size,
                    }
                )
            (sl,) = struct.unpack_from(order + "I", hdr, p)
            if sl > 1024 or p + 4 + sl > len(hdr):
                return None
            path = hdr[p + 4 : p + 4 + sl].split(b"\0", 1)[0].decode("latin1")
            p += 4 + sl
            frames.append({"slots": slots, "path": path})
    except (struct.error, IndexError):
        return None
    tail = None
    if anim:
        try:
            tail, p = _reference_anim_tail(hdr, p, order)
        except (struct.error, ValueError, RecursionError):
            tail = None  # the frames stand; the block is reported as not read
    return {"frames": frames, "anim": bool(anim), "anim_tail": tail, "end": p}


@pytest.mark.parametrize("order", ["<", ">"])
def test_reader_equals_the_reference_on_mutated_headers(order):
    rng = np.random.default_rng(11)
    slots = {0: _desc(order, 8, 8, 5, 4), 1: _desc(order, 8, 8, 9, 2), 7: _desc(order, 8, 8, 3, 4)}
    tail = struct.pack(order + "6I", 5, 1, 2, 3, 0, 1) + struct.pack(order + "5I", 0, 3, 40, 40, 9)
    tail += struct.pack(order + "I", 0)
    base = [
        _header(order, slots),
        _header(order, slots, nf=3),
        _header(order, slots, anim=1) + tail,
        _header(order, {0: _desc(order, 16, 16, 7, 5, typ=2)}),
    ]
    n = 0
    for b in base:
        assert th.parse_texture_frames(b, order) == _reference_frames(b, order) is not None
        for cut in range(len(b)):
            assert th.parse_texture_frames(b[:cut], order) == _reference_frames(b[:cut], order)
            n += 1
        for _ in range(400):
            m = bytearray(b)
            for i in rng.integers(0, len(b), int(rng.integers(1, 4))):
                m[i] = int(rng.integers(0, 256))
            m = bytes(m)
            assert th.parse_texture_frames(m, order) == _reference_frames(m, order)
            n += 1
    assert n > 1000
