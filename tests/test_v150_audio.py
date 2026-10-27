"""1.5.0 audio: MS-ADPCM as the reference decoder computes it (truncating
predictor, the header's coefficients, data_bytes only, a final partial block),
checked against ffmpeg's output stored in tests/data/adpcm_ffmpeg.json; the
Vorbis setup reader raises ValueError (also under `python -O`); Ogg pages hold
about 4 KB of packets."""

import base64
import hashlib
import json
import os
import struct
import subprocess
import sys

import pytest

import test_audio_v2 as ta
import watchmen_extract as wx

FIXTURE = os.path.join(os.path.dirname(__file__), "data", "adpcm_ffmpeg.json")


# ---------------------------------------------------------------------------
# MS-ADPCM
# ---------------------------------------------------------------------------
def test_predictor_truncates_toward_zero():
    assert wx._adpcm_predict(-3, 0, 256, 0) == -3
    assert wx._adpcm_predict(-1, 0, 192, 0) == 0  # -192/256 -> 0, `>> 8` gave -1
    assert wx._adpcm_predict(-1, -1, 460, -208) == 0  # -252/256
    assert wx._adpcm_predict(-300, 7, 460, -208) == -544  # -139456/256 = -544.75
    assert wx._adpcm_predict(300, -7, 460, -208) == 544
    assert (-300 * 460 + 7 * -208) >> 8 == -545  # what `>> 8` gave
    for s1 in range(-600, 600, 37):
        for s2 in range(-600, 600, 41):
            for c1, c2 in wx._COEF_PAIRS:
                t = s1 * c1 + s2 * c2
                assert wx._adpcm_predict(s1, s2, c1, c2) == int(t / 256)


@pytest.mark.parametrize("tag", ["mono_small", "stereo_small"])
def test_decoder_is_bit_exact_with_ffmpeg(tag):
    """The stored stream was encoded for the test (sine + noise, random
    predictors and deltas, the last block partial) and decoded with ffmpeg 6.1.1
    (WAV fmt tag 2, standard coefficients, -f s16le); its PCM sha1 is stored."""
    with open(FIXTURE) as fh:
        fx = json.load(fh)[tag]
    data = base64.b64decode(fx["adpcm"])
    ch, ba = fx["ch"], fx["block_align"]
    assert len(data) % ba >= 7 * ch  # a partial last block is part of the case
    pcm = (wx._adpcm_stereo if ch == 2 else wx._adpcm_mono)(data, ba)
    assert len(pcm) // ch == fx["ffmpeg_samples"]
    assert hashlib.sha1(pcm.tobytes()).hexdigest() == fx["ffmpeg_pcm_sha1"]


def test_the_fixture_is_small():
    assert os.path.getsize(FIXTURE) <= 10 * 1024


def _block(pred, delta, s1, s2, nibbles):
    b = struct.pack("<Bhhh", pred, delta, s1, s2)
    return b + bytes((nibbles[i] << 4) | nibbles[i + 1] for i in range(0, len(nibbles), 2))


def test_a_partial_last_block_is_decoded():
    full = _block(0, 16, 10, 5, [1, 2] * 25)  # 7 + 25 bytes = one 32-byte block
    part = _block(0, 16, 10, 5, [1, 2] * 3)  # 7 + 3 bytes
    pcm = wx._adpcm_mono(full + part, 32)
    assert len(pcm) == (2 + 50) + (2 + 6)  # 1.4.0 dropped the 8 samples of `part`
    assert len(wx._adpcm_mono(full + part[:6], 32)) == 52  # no block header: ends
    st = struct.pack("<BBhhhhhh", 0, 0, 16, 16, 1, 2, 3, 4) + b"\x12" * 2
    assert len(wx._adpcm_stereo(st, 64)) == 4 + 4


def test_custom_coefficients_are_used():
    blk = _block(1, 16, 100, 100, [0, 0])
    std = wx._adpcm_mono(blk, len(blk))
    own = wx._adpcm_mono(blk, len(blk), [(256, 0), (128, 0)])
    assert list(std) == [100, 100, 100, 100]  # pair 1 (512, -256): 2*100 - 100
    assert list(own) == [100, 100, 50, 25]  # pair 1 of the header: 128 / 256
    assert len(wx._adpcm_mono(_block(2, 16, 1, 1, [0, 0]), 9, [(256, 0), (0, 0)])) == 0


def _adpcm_sound(data, samples, ch=1, coefs=None, ba=32, cue=b""):
    """A PC `sound` header in the loader layout (sfx_info) with ADPCM data."""
    h = struct.pack("<I", 6) + b"sound\x00" + struct.pack("<I", 0x1234)
    h += struct.pack("<5I", 0xA1B2C3D4, 0x11, 0x22, 0, 7)
    h += bytes([0, 1]) + struct.pack("<4I", ch, 44100, 2, 44100)
    h += struct.pack("<3I", 0, samples, ba)
    h += struct.pack("<14h", *(coefs or wx._COEF))
    return h + struct.pack("<I", len(data)) + data + (cue or struct.pack("<I", 0))


def test_decode_sfx_reads_the_header_layout():
    blk = _block(0, 16, 10, 5, [1, 2] * 25)
    part = _block(0, 16, 10, 5, [3, 4] * 3)
    cue = struct.pack("<I", 1) + struct.pack("<I", 4) + b"cue\0" + struct.pack("<I", 9)
    h = _adpcm_sound(blk + part, 57, cue=cue)
    info = wx.sfx_info(h)
    assert info["data_bytes"] == len(blk + part) and info["cue_points"][0]["name"] == "cue"
    data, ch, rate = wx.decode_sfx(h)
    pcm = struct.unpack("<%dh" % (len(data) // 2), data)
    assert len(pcm) == 57  # 52 + 8 decoded, trimmed to the stored sample count
    assert list(pcm) == list(wx._adpcm_mono(blk + part, 32))[:57]
    # the header's own table: a non-standard pair 0 changes the decode
    coefs = list(wx._COEF)
    coefs[0] = 128
    other = wx.decode_sfx(_adpcm_sound(blk + part, 57, coefs=coefs))[0]
    assert other != data
    assert (
        other
        == wx._adpcm_mono(blk + part, 32, [(128, 0)] + list(wx._COEF_PAIRS[1:]))[:57].tobytes()
    )


def test_decode_sfx_falls_back_to_the_table_search():
    """Not the loader layout (data_bytes past the end): the 1.4.0 search for the
    standard table, then the data to the end."""
    blk = _block(0, 16, 10, 5, [1, 2] * 25)
    h = bytearray(_adpcm_sound(blk, 52))
    struct.pack_into("<I", h, len(h) - 4 - len(blk) - 4, 10**6)
    data, _ch, _rate = wx.decode_sfx(bytes(h))
    assert len(data) == 2 * 52


# ---------------------------------------------------------------------------
# Vorbis setup header
# ---------------------------------------------------------------------------
class _BW:
    def __init__(self):
        self.bits = []

    def w(self, v, n):
        self.bits += [(v >> i) & 1 for i in range(n)]

    def bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(sum(b[i + k] << k for k in range(8)) for i in range(0, len(b), 8))


def vorbis_setup(blockflags=(0, 1), channels=2):
    """A minimal Vorbis I setup header (one codebook, floor 1, residue 0, one
    mapping) with one mode per block flag."""
    b = _BW()
    b.w(5, 8)
    for c in b"vorbis":
        b.w(c, 8)
    b.w(0, 8)  # 1 codebook
    b.w(0x564342, 24)
    b.w(1, 16)  # dimensions
    b.w(2, 24)  # entries
    b.w(0, 1)  # not ordered
    b.w(0, 1)  # not sparse
    b.w(0, 5)
    b.w(0, 5)  # two lengths of 1
    b.w(0, 4)  # no lookup
    b.w(0, 6)
    b.w(0, 16)  # one time-domain transform, type 0
    b.w(0, 6)
    b.w(1, 16)  # one floor, type 1
    b.w(0, 5)  # no partitions
    b.w(0, 2)
    b.w(4, 4)  # multiplier, range bits
    b.w(0, 6)  # one residue
    b.w(0, 16)
    b.w(0, 24)
    b.w(64, 24)
    b.w(15, 24)
    b.w(0, 6)  # one classification
    b.w(0, 8)  # classbook
    b.w(0, 3)
    b.w(0, 1)  # cascade 0
    b.w(0, 6)  # one mapping
    b.w(0, 16)
    b.w(0, 1)  # one submap
    b.w(0, 1)  # no coupling
    b.w(0, 2)  # reserved
    b.w(0, 8)
    b.w(0, 8)
    b.w(0, 8)
    b.w(len(blockflags) - 1, 6)
    for f in blockflags:
        b.w(f, 1)
        b.w(0, 16)
        b.w(0, 16)
        b.w(0, 8)
    b.w(1, 1)  # framing
    return b.bytes()


def test_vorbis_setup_block_flags():
    assert wx._vorbis_blockflags(vorbis_setup((0, 1)), 2) == [0, 1]
    assert wx._vorbis_blockflags(vorbis_setup((1, 1, 0)), 1) == [1, 1, 0]


@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda s: s[:20], "truncated"),
        (lambda s: b"\x03" + s[1:], "not a setup header"),
        (lambda s: s[:1] + b"VORBIS" + s[7:], "signature"),
        (lambda s: s[:8] + b"\x00\x00\x00" + s[11:], "sync pattern"),
        (lambda s: b"", "truncated"),
    ],
)
def test_a_bad_setup_header_raises_value_error(mutate, why):
    with pytest.raises(ValueError, match="vorbis setup: .*" + why):
        wx._vorbis_blockflags(mutate(vorbis_setup()), 2)


def test_the_setup_checks_survive_python_O():
    """Under -O an assert vanishes: the checks are explicit raises."""
    code = (
        "import sys; sys.path[:0] = [%r, %r]\n"
        "import watchmen_extract as wx, test_v150_audio as t\n"
        "assert False, 'asserts are on'\n"
    ) % (os.path.dirname(wx.__file__), os.path.dirname(__file__))
    code = code.replace("assert False, 'asserts are on'\n", "") + (
        "s = t.vorbis_setup()\n"
        "print(wx._vorbis_blockflags(s, 2))\n"
        "for bad in (s[:1] + b'VORBIS' + s[7:], s[:8] + b'xxx' + s[11:]):\n"
        "    try:\n"
        "        wx._vorbis_blockflags(bad, 2)\n"
        "    except ValueError as e:\n"
        "        print('ValueError', e)\n"
        "print(__debug__)\n"
    )
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(
        [sys.executable, "-O", "-c", code],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "[0, 1]" and lines[-1] == "False"
    assert [ln.split(":")[0] for ln in lines[1:3]] == ["ValueError vorbis setup"] * 2


# ---------------------------------------------------------------------------
# Ogg pages
# ---------------------------------------------------------------------------
def _pages(data):
    """[(header type, granule, seq, [lacing], body)] with the CRC checked."""
    out, o = [], 0
    while o < len(data):
        assert data[o : o + 4] == b"OggS"
        nseg = data[o + 26]
        lac = list(data[o + 27 : o + 27 + nseg])
        end = o + 27 + nseg + sum(lac)
        page = bytearray(data[o:end])
        crc = struct.unpack_from("<I", page, 22)[0]
        page[22:26] = b"\0\0\0\0"
        assert wx._ogg_crc(bytes(page)) == crc
        gran, _serial, seq = struct.unpack_from("<qII", data, o + 6)
        out.append((data[o + 5], gran, seq, lac, data[o + 27 + nseg : end]))
        o = end
    return out


def _audio(n, size=100):
    return [bytes([0x10 + (i & 0x3F) * 2 % 0x7E]) * size for i in range(n)]


def test_audio_packets_share_pages_of_about_4_kb():
    heads = ta.vorbis_headers()
    audio = _audio(300, 97)
    ogg, ch, rate, n, last = wx._ogg_from_packets(heads + audio, True, end=28000)
    pages = _pages(ogg)
    assert [p[0] for p in pages][:2] == [0x02, 0x00] and pages[-1][0] == 0x04
    assert all(p[0] == 0 for p in pages[1:-1])
    assert [p[2] for p in pages] == list(range(len(pages)))
    assert pages[0][4] == heads[0] and pages[0][1] == 0  # identification alone
    assert pages[1][4] == heads[1] + heads[2] and pages[1][1] == 0  # before any audio
    audio_pages = pages[2:]
    assert all(len(p[4]) <= wx.OGG_PAGE_BYTES for p in audio_pages)
    assert len(audio_pages) == 8  # 300 x 97 bytes: 42 packets a page (1.4.0: 300 pages)
    assert ta.ogg_packets(ogg) == heads + audio
    gr = [(i + 1) * 1024 for i in range(300)]  # this setup has no modes: 1024 a packet
    gr[-1] = 28000 if gr[-2] < 28000 <= gr[-1] else gr[-1]
    done = 0
    for p in audio_pages:
        done += sum(1 for x in p[3] if x < 255)
        assert p[1] == gr[done - 1]  # granule of the last packet completed on the page
    assert last == pages[-1][1]
    # the same packets one page each (1.4.0) took 27 + 1 bytes more per packet
    assert len(ogg) < sum(len(p) + 28 for p in audio) - 250 * 28


def test_a_packet_larger_than_a_page_continues():
    heads = ta.vorbis_headers()
    big = b"\x12" * 70000  # 275 lacing values: more than one page can hold
    ogg = wx._ogg_from_packets(heads + [b"\x10" * 50, big, b"\x14" * 50], False)[0]
    pages = _pages(ogg)
    assert ta.ogg_packets(ogg) == heads + [b"\x10" * 50, big, b"\x14" * 50]
    cont = [p for p in pages if p[0] & 0x01]
    assert len(cont) == 1
    first = pages.index(cont[0]) - 1
    assert pages[first][1] == -1  # the big packet starts a page and completes none there
    assert len(pages[first][3]) == 255 and pages[first][3][-1] == 255
    assert pages[first - 1][1] == 1024 and len(pages[first - 1][4]) == 50  # the small one
    assert pages[-1][0] & 0x04 and pages[-1][1] == 3 * 1024


def test_the_writer_marks_a_page_where_no_packet_ends():
    w = wx._OggWriter(1, page_bytes=1000)
    w.packet(b"\x01" * 10, 0)
    w.flush()
    w.packet(b"\x02" * (255 * 300), 77)
    w.flush(eos=True)
    pages = _pages(bytes(w.out))
    assert [p[1] for p in pages] == [0, -1, 77]  # the middle page completes no packet
    assert [p[0] for p in pages] == [0x02, 0x00, 0x05]
