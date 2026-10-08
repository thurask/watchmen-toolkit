"""Console texture layer plan from the exact header (pass 2, package E).

Synthetic big-endian fixtures only: X360 streams are built tiled and 16-bit
swapped the way the console stores them, PS3 streams as [36-byte descriptor]
[data] segments.  What is pinned here was measured on the real sets (the
numbers are in the docstrings of wlib/watchmen_extract.py):

* the last u32 of an X360 image descriptor is the layer's stored size;
* format id 8 (DXT3A) is a layer, not the end of the list;
* cube maps: X360 keeps the six faces inside each mip level, PS3 pads every
  face chain to 128 bytes;
* file names follow the PC carve (faceN_ / frameN_);
* what cannot be placed is logged and listed in sheet.json, never dropped.
"""

import json
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "wlib"))
import watchmen_extract as we  # noqa: E402

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------


def _str(s, o):
    b = s.encode("latin1") + b"\0"
    return struct.pack(o + "I", len(b)) + b


def _desc(o, w, h, fmt, mips, typ=1, alpha=0, size=0):
    return struct.pack(o + "5IBII", w, h, fmt, 0, typ, alpha, mips, size)


def _header(frames, o=">", anim=0):
    """frames: [({slot: descriptor bytes}, path)] -> Texture header in order `o`,
    with the nine 20-byte property records of a real Part 2 header."""
    bag = b"".join(
        struct.pack(o + "5I", 0x897CBF7D, 0x1000 + i, 0x36604FF4, 1, 1) for i in range(9)
    )
    b = _str("Texture", o) + struct.pack(o + "I", len(bag) // 4) + bag
    b += struct.pack(o + "IB", len(frames), anim)
    for slots, path in frames:
        b += slots[0]
        for k in range(1, 8):
            b += b"\x01" + slots[k] if k in slots else b"\x00"
        b += _str(path, o)
    return b + b"\0" * 40


def _dxt1(colours, bw, bh):
    """Linear DXT1 data, one flat colour (RGB565) per 4x4 block."""
    return b"".join(struct.pack("<HHI", colours[i], colours[i], 0) for i in range(bw * bh))


def _rgb(c565):
    r, g, b = (c565 >> 11) & 31, (c565 >> 5) & 63, c565 & 31
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _x360_tile(linear, we_, he, unit, xo=0, yo=0):
    """Linear element data -> one tiled, 16-bit swapped X360 surface (the block
    grid padded to 32 x 32 elements), the image placed at element (xo, yo)."""
    tw, th = (we_ + xo + 31) & ~31, (he + yo + 31) & ~31
    out = bytearray(tw * th * unit)
    for y in range(he):
        for x in range(we_):
            d = we._xg2d(x + xo, y + yo, tw, unit) * unit
            s = (y * we_ + x) * unit
            out[d : d + unit] = linear[s : s + unit]
    return we._bswap16(bytes(out))


def _pngs(d):
    return sorted(p.name for p in d.glob("*.png"))


def _px(path):
    return np.asarray(Image.open(path))


def _carve(stream, hdr, out):
    log = []
    ok = we.carve_texture(stream, hdr, out, log.append)
    return ok, [l.strip() for l in log]


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------


def test_big_endian_header_parses_with_the_stored_size_of_each_layer():
    hdr = _header(
        [
            (
                {
                    0: _desc(">", 128, 128, 5, 1, size=8192),
                    1: _desc(">", 128, 128, 10, 1, size=16384),
                    4: _desc(">", 128, 128, 8, 1, size=8192),
                },
                "/data/art/x/Ground.bmp",
            )
        ]
    )
    assert we.parse_texture_frames(hdr) is None  # not a little-endian header
    ex = we.parse_texture_frames(hdr, ">")
    slots = [d for d in ex["frames"][0]["slots"] if d]
    assert [(d["slot"], d["enum"], d["fmt"], d["size"]) for d in slots] == [
        (0, 5, "DXT1", 8192),
        (1, 10, "ATI2", 16384),
        (4, 8, "DXT3A", 8192),
    ]
    assert ex["frames"][0]["path"] == "/data/art/x/Ground.bmp"
    assert [we.texture_layer_label(slots, j, ">") for j in range(3)] == [
        "diffuse",
        "normal",
        "height",  # slot 4 (was "specSize" until the labels followed the file slot)
    ]


def test_format_8_stays_a_console_format():
    """Id 8 exists only in the X360 table: the PC parser must keep rejecting it."""
    assert 8 not in we.TEX_ENUMS
    pc = _header([({0: _desc("<", 8, 8, 8, 1)}, "/data/a.bmp")], o="<")
    assert we.parse_texture_frames(pc) is None
    assert we.parse_texture_frames(_header([({0: _desc("<", 8, 8, 5, 1)}, "/data/a.bmp")], "<"))


def test_dxt3a_is_four_bits_per_texel_low_nibble_first():
    blk = bytes([0x10, 0x32, 0x54, 0x76, 0x98, 0xBA, 0xDC, 0xFE])
    img = we._decode_one_layer(blk + bytes([0xFF] * 8), 8, 8, 4)
    assert img.shape == (4, 8) and img.dtype == np.uint8
    assert (img[:, :4].reshape(-1) == np.arange(16) * 17).all()
    assert (img[:, 4:] == 255).all()
    assert we._decode_one_layer(blk, 8, 8, 4) is None  # short data


# ---------------------------------------------------------------------------
# X360
# ---------------------------------------------------------------------------


def _x360_four_layer():
    """128x128: DXT1 diffuse, BC5 normal, DXT1 specMap, DXT3A slot 4 (the
    Ground_Asphalt_06 shape, one mip each)."""
    cols = [(i * 37) & 0xFFFF for i in range(32 * 32)]
    diff = _dxt1(cols, 32, 32)
    spec = _dxt1(cols[::-1], 32, 32)
    norm = bytes([128, 128, 0, 0, 0, 0, 0, 0] * 2) * (32 * 32)
    size = bytes((i * 7) & 255 for i in range(32 * 32 * 8))
    stream = (
        _x360_tile(diff, 32, 32, 8)
        + _x360_tile(norm, 32, 32, 16)
        + _x360_tile(spec, 32, 32, 8)
        + _x360_tile(size, 32, 32, 8)
    )
    hdr = _header(
        [
            (
                {
                    0: _desc(">", 128, 128, 5, 1, size=8192),
                    1: _desc(">", 128, 128, 10, 1, size=16384),
                    2: _desc(">", 128, 128, 5, 1, size=8192),
                    4: _desc(">", 128, 128, 8, 1, size=8192),
                },
                "/data/art/x/Ground_Asphalt.bmp",
            )
        ]
    )
    return hdr, stream, (diff, spec, size)


def test_x360_fourth_layer_in_format_8_is_written(tmp_path):
    """Was: 'X360 layers=3 x1 (approx stream ...)' and three PNGs."""
    hdr, stream, (diff, spec, size) = _x360_four_layer()
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok
    assert _pngs(tmp_path / "t") == [
        "0_diffuse_128x128_DXT1.png",
        "1_normal_128x128_ATI2.png",
        "2_specMap_128x128_DXT1.png",
        "3_height_128x128_DXT3A.png",
    ]
    assert log == ["Ground_Asphalt: X360 layers=4 x1 (exact stream 40960) -> t/ (4 png)"]
    assert not (tmp_path / "t" / "sheet.json").exists()  # nothing to report
    for name, lin, en in (
        ("0_diffuse_128x128_DXT1.png", diff, 5),
        ("2_specMap_128x128_DXT1.png", spec, 5),
        ("3_height_128x128_DXT3A.png", size, 8),
    ):
        want = we._decode_one_layer(lin, en, 128, 128)
        assert (_px(tmp_path / "t" / name) == want).all(), name


def test_x360_slot_7_dxt1_layer_is_the_spec_size_map(tmp_path):
    """Dominatrix_Glove2: diffuse, normal, slot 7 stored as DXT1 where the PC has
    L8.  It was labelled specMap, so no roughness map was derived from it."""
    d = _dxt1([0x1234] * 1024, 32, 32)
    size = _dxt1([0xC8E3] * 1024, 32, 32)  # red 25/31, green 7/63, blue 3/31
    n = bytes([128, 128, 0, 0, 0, 0, 0, 0] * 2) * 1024
    hdr = _header(
        [
            (
                {
                    0: _desc(">", 128, 128, 5, 1, size=8192),
                    1: _desc(">", 128, 128, 10, 1, size=16384),
                    7: _desc(">", 128, 128, 5, 1, size=8192),
                },
                "/data/art/x/Glove2.bmp",
            )
        ]
    )
    stream = _x360_tile(d, 32, 32, 8) + _x360_tile(n, 32, 32, 16) + _x360_tile(size, 32, 32, 8)
    assert _carve(stream, hdr, tmp_path / "t")[0]
    assert _pngs(tmp_path / "t") == [
        "0_diffuse_128x128_DXT1.png",
        "1_normal_128x128_ATI2.png",
        "2_specSize_128x128_DXT1.png",
    ]
    # written as the grayscale map the PC has: the red channel, not the luma
    px = _px(tmp_path / "t" / "2_specSize_128x128_DXT1.png")
    assert px.shape == (128, 128) and (px == _rgb(0xC8E3)[0]).all()
    assert _px(tmp_path / "t" / "0_diffuse_128x128_DXT1.png").ndim == 3


def test_x360_animation_frames_keep_both_layers_and_pc_names(tmp_path):
    """Caustics01_001: every frame is a 16x16 map in the packed tail plus a
    128x128 map in slot 3.  Was cut into one 'segN_0_diffuse_16x16' per 8 KiB."""
    frames, stream, small, big = [], b"", [], []
    for f in range(3):
        s = _dxt1([0x0841 * (f + 1) + i for i in range(16)], 4, 4)
        b = _dxt1([(0x1111 * (f + 1) + i) & 0xFFFF for i in range(1024)], 32, 32)
        small.append(s)
        big.append(b)
        stream += _x360_tile(s, 4, 4, 8, xo=4) + _x360_tile(b, 32, 32, 8)
        frames.append(
            (
                {
                    0: _desc(">", 16, 16, 5, 5, size=8192),
                    3: _desc(">", 128, 128, 5, 1, size=8192),
                },
                "/data/art/fx/Caustics_%03d.bmp" % f,
            )
        )
    hdr = _header(frames, anim=1)
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok and log[-1].endswith("X360 layers=2 x3 (exact stream 49152) -> t/ (6 png)")
    assert _pngs(tmp_path / "t") == sorted(
        "frame%d_%s" % (f, n)
        for f in range(3)
        for n in ("0_diffuse_16x16_DXT1.png", "1_glow_128x128_DXT1.png")
    )
    for f in range(3):
        got = _px(tmp_path / "t" / ("frame%d_0_diffuse_16x16_DXT1.png" % f))
        assert (got == we._decode_one_layer(small[f], 5, 16, 16)).all()
        got = _px(tmp_path / "t" / ("frame%d_1_glow_128x128_DXT1.png" % f))
        assert (got == we._decode_one_layer(big[f], 5, 128, 128)).all()


_FACE = [0xF800, 0x07E0, 0x001F, 0xFFE0, 0xF81F, 0x07FF]


def _x360_cube(w=64, mips=7):
    """One DXT1 cube layer, level-major: 6 faces of level 0, 6 of level 1, the
    packed tails.  Faces are flat colours; lower levels are filled with a colour
    no face has, so a face read from the wrong place shows."""
    bw = w // 4
    lvl0 = b"".join(_x360_tile(_dxt1([_FACE[k]] * (bw * bw), bw, bw), bw, bw, 8) for k in range(6))
    per_face = we._x360_layer_bytes(5, w, w, mips)
    n = (per_face * 6 - len(lvl0)) // 8
    rest = we._bswap16(_dxt1([0x8410] * n, n, 1))
    stream = lvl0 + rest
    assert len(stream) == per_face * 6
    hdr = _header(
        [({0: _desc(">", w, w, 5, mips, typ=2, size=len(stream))}, "/data/art/c/Hall_cubemap.bmp")]
    )
    return hdr, stream


def test_x360_cube_faces_are_stored_inside_each_mip_level(tmp_path):
    """Was: six 'segN_' images read one whole face chain apart, so faces 1-5
    showed the lower mip levels."""
    hdr, stream = _x360_cube()
    assert len(stream) == 147456  # the real 64x64, 7-mip cube layer size
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok and log == ["Hall_cubemap: X360 layers=1 x1 (exact stream 147456) -> t/ (6 png)"]
    assert _pngs(tmp_path / "t") == ["face%d_0_diffuse_64x64_DXT1.png" % k for k in range(6)]
    for k in range(6):
        px = _px(tmp_path / "t" / ("face%d_0_diffuse_64x64_DXT1.png" % k))
        assert tuple(px[0, 0, :3]) == _rgb(_FACE[k]) and (px[..., :3] == px[0, 0, :3]).all()


def test_x360_cube_below_32_texels_is_marked_not_guessed(tmp_path):
    w, mips = 16, 5
    per_face = we._x360_layer_bytes(5, w, w, mips)
    stream = _x360_tile(_dxt1([_FACE[0]] * 16, 4, 4), 4, 4, 8, xo=4) + bytes(per_face * 5)
    hdr = _header(
        [({0: _desc(">", w, w, 5, mips, typ=2, size=len(stream))}, "/data/art/c/Tiny_cubemap.bmp")]
    )
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok and _pngs(tmp_path / "t") == ["face0_0_diffuse_16x16_DXT1.png"]
    assert len([l for l in log if l.startswith("WARNING: texture Tiny_cubemap:")]) == 1
    marks = json.loads((tmp_path / "t" / "sheet.json").read_text())[we.TEXTURE_DECODE_KEY]
    assert len(marks) == 1 and "only face 0 written" in marks[0]


def test_x360_sizes_that_do_not_fill_the_stream_warn_and_mark(tmp_path):
    """The stride walk still writes what it can; the log line and the sheet.json
    key say that the plan does not cover the stream."""
    hdr, stream, _ = _x360_four_layer()
    stream += bytes(4096)
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok
    warns = [l for l in log if l.startswith("WARNING: texture Ground_Asphalt:")]
    assert len(warns) == 2
    assert "header layer sizes add up to 40960, the stream is 45056 bytes" in warns[0]
    assert "stride-walk plan covers" in warns[1]
    assert "(approx stream 45056)" in log[-1]
    js = json.loads((tmp_path / "t" / "sheet.json").read_text())
    assert len(js[we.TEXTURE_DECODE_KEY]) == 2
    assert we.read_sheet_json(tmp_path / "t")[we.TEXTURE_DECODE_KEY] == js[we.TEXTURE_DECODE_KEY]


def test_x360_layer_size_off_the_layout_rule_is_reported(tmp_path):
    """Sizes add up, but one layer is not what the mip layout rule gives."""
    d = _dxt1([0x1234] * 1024, 32, 32)
    stream = _x360_tile(d, 32, 32, 8) + bytes(4096)
    hdr = _header([({0: _desc(">", 128, 128, 5, 1, size=12288)}, "/data/art/x/Odd.bmp")])
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok and _pngs(tmp_path / "t") == ["0_diffuse_128x128_DXT1.png"]
    assert [l for l in log if l.startswith("WARNING:")] == [
        "WARNING: texture Odd: layer 0 (DXT1 128x128, 1 mips) stores 12288 bytes, the layout rule "
        "gives 8192: top mip decoded from the layer start, not checked"
    ]
    assert we.TEXTURE_DECODE_KEY in json.loads((tmp_path / "t" / "sheet.json").read_text())


# ---------------------------------------------------------------------------
# PS3
# ---------------------------------------------------------------------------


def _ps3_seg(data, fmt, mips, w, h, cube=0):
    hd = struct.pack(">III", 0, 0x80, len(data)) + bytes([fmt, mips, 2, cube])
    hd += struct.pack(">IHHH", 0xAAE4, w, h, 1)
    return hd + bytes(36 - len(hd)) + data


def _ps3_cube(w=8, mips=4, pad=128):
    bw = w // 4
    chain = we._chain_bytes(5, w, w, mips)
    data = b""
    for k in range(6):
        face = _dxt1([_FACE[k]] * (bw * bw), bw, bw)
        face += _dxt1([0x8410] * ((chain - len(face)) // 8), (chain - len(face)) // 8, 1)
        data += face + (bytes(-len(face) % pad) if k < 5 else b"")
    hdr = _header([({0: _desc(">", w, w, 5, mips, typ=2)}, "/data/art/c/Hall_cubemap.bmp")])
    return hdr, _ps3_seg(data, 0x86, mips, w, w, cube=1)


def test_ps3_cube_writes_six_faces_from_128_byte_aligned_chains(tmp_path):
    """Was: one PNG (face 0) and no word about the other five."""
    hdr, stream = _ps3_cube()
    assert we._chain_bytes(5, 8, 8, 4) == 56  # so every face but the last is padded
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok and log == ["Hall_cubemap: PS3 1 segs -> t/ (6 png)"]
    assert _pngs(tmp_path / "t") == ["face%d_0_diffuse_8x8_DXT1.png" % k for k in range(6)]
    for k in range(6):
        px = _px(tmp_path / "t" / ("face%d_0_diffuse_8x8_DXT1.png" % k))
        assert tuple(px[0, 0, :3]) == _rgb(_FACE[k]) and (px[..., :3] == px[0, 0, :3]).all()


def test_ps3_cube_with_an_unexplained_segment_size_writes_face_0_and_says_so(tmp_path):
    hdr, stream = _ps3_cube(pad=64)
    ok, log = _carve(stream, hdr, tmp_path / "t")
    assert ok and _pngs(tmp_path / "t") == ["face0_0_diffuse_8x8_DXT1.png"]
    warns = [l for l in log if l.startswith("WARNING: texture Hall_cubemap:")]
    assert len(warns) == 1 and "only face 0 written" in warns[0]
    marks = json.loads((tmp_path / "t" / "sheet.json").read_text())[we.TEXTURE_DECODE_KEY]
    assert marks == [warns[0].split(": ", 2)[2]]


def test_ps3_animation_frames_are_named_like_the_pc_ones(tmp_path):
    """Was 'seg0_', 'seg1_' where the PC writes 'frame0_', 'frame1_'."""
    frames, stream = [], b""
    for f in range(2):
        stream += _ps3_seg(_dxt1([_FACE[f]] * 4, 2, 2), 0x86, 1, 8, 8)
        frames.append(({0: _desc(">", 8, 8, 5, 1)}, "/data/art/ui/Saving%d.bmp" % f))
    ok, _log = _carve(stream, _header(frames, anim=1), tmp_path / "t")
    assert ok
    assert _pngs(tmp_path / "t") == [
        "frame0_0_diffuse_8x8_DXT1.png",
        "frame1_0_diffuse_8x8_DXT1.png",
    ]
    px = _px(tmp_path / "t" / "frame1_0_diffuse_8x8_DXT1.png")
    assert tuple(px[0, 0, :3]) == _rgb(_FACE[1])


def test_ps3_segment_count_off_the_header_warns_and_marks(tmp_path):
    seg = _ps3_seg(_dxt1([_FACE[0]] * 4, 2, 2), 0x86, 1, 8, 8)
    hdr = _header([({0: _desc(">", 8, 8, 5, 1)}, "/data/art/x/One.bmp")])
    ok, log = _carve(seg + seg, hdr, tmp_path / "t")
    assert ok
    assert [l for l in log if l.startswith("WARNING:")] == [
        "WARNING: texture One: 2 stream segments for 1 header layers: layer plan from the stride walk"
    ]
    assert _pngs(tmp_path / "t") == ["seg0_0_diffuse_8x8_DXT1.png", "seg1_0_diffuse_8x8_DXT1.png"]
    assert we.TEXTURE_DECODE_KEY in json.loads((tmp_path / "t" / "sheet.json").read_text())


# ---------------------------------------------------------------------------
# PC
# ---------------------------------------------------------------------------


def _pc_cube():
    """8x8 DXT1 cube, 2 mips, stored the way the PC streams are: level 0 of the six
    faces, then level 1 of the six faces."""
    lvl0 = b"".join(_dxt1([_FACE[k]] * 4, 2, 2) for k in range(6))
    lvl1 = _dxt1([0x8410] * 6, 6, 1)
    hdr = _header([({0: _desc("<", 8, 8, 5, 2, typ=2)}, "/data/art/c/Hall_cubemap.bmp")], o="<")
    return hdr, lvl0 + lvl1


def _face_colours(d):
    return [
        tuple(_px(d / ("face%d_0_diffuse_8x8_DXT1.png" % k))[4, 4, :3].tolist()) for k in range(6)
    ]


def test_pc_cube_is_read_level_by_level_by_default(tmp_path):
    """A PC cube stores its mip levels in order, six faces per level (as X360)."""
    hdr, stream = _pc_cube()
    assert we.PC_CUBE_LEVEL_MAJOR is True
    assert we.carve_texture(stream, hdr, tmp_path / "t")
    assert _face_colours(tmp_path / "t") == [_rgb(c) for c in _FACE]


def test_pc_cube_switch_off_gives_the_1_3_0_reading(tmp_path, monkeypatch):
    """Six face chains: faces 1-5 start 40 bytes apart here, so they are not the
    stored faces (what 1.3.0 wrote)."""
    hdr, stream = _pc_cube()
    monkeypatch.setattr(we, "PC_CUBE_LEVEL_MAJOR", False)
    assert we.carve_texture(stream, hdr, tmp_path / "t")
    got = _face_colours(tmp_path / "t")
    assert got[0] == _rgb(_FACE[0])
    assert got[1:] != [_rgb(c) for c in _FACE[1:]]
