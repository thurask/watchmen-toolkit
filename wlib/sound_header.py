"""Sound and music-stream headers: the tracks and link records of a
`.mediastream` header on PC (`media_tracks_pc`, `media_track_name`) and on the
consoles (`media_tracks_console`, `console_media_parse`, `xma_frame_count`),
its cue points and track states (`media_meta_from_header`,
`media_desc_from_header`), and a `sound` asset's format, rate, length and loop
flag (`sfx_info`, `adpcm_layout`, `mp3_frame_stats`).
"""

import itertools
import os
import re
import struct
import sys

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
import byte_reader  # noqa: E402
import kapow_block  # noqa: E402


class SoundHeaderError(byte_reader.ReadError):
    """A sound or music-stream header record that does not read."""


# ---------------------------------------------------------------------------
# Multi-track streams.  A mediastream_s holds N synchronous tracks (music
# stems).  It is a sequence of groups; a group is one chunk per track, back to
# back, and is followed by a link record
#     [u32 m][u32 size x N],  m = sum(sizes) + 4 * (N + 1)
# giving the chunk sizes of the NEXT group; the link after the last group
# repeats group 0's sizes (the loop).  Read on all 13 Part-2 music streams of
# each platform; engine side: MusicStreamSlot track0..9 / SoundSlot
# numStreamTracks (0x4da99c), MusicTrackCtrl.track_index.
# PC: a chunk is [32-byte packet header][Vorbis packet] records, and each
# track's first chunk starts with its own three Vorbis header packets.
# ---------------------------------------------------------------------------
def _media_link(raw, o, n, bo="<"):
    """Chunk sizes of the link record at `o` for `n` tracks, or None."""
    if n < 1 or o + 4 * (n + 1) > len(raw):
        return None
    v = struct.unpack_from(bo + "%dI" % (n + 1), raw, o)
    return list(v[1:]) if v[0] == sum(v[1:]) + 4 * (n + 1) else None


def media_tracks_pc(raw):
    """Tracks of a PC mediastream_s: [{"packets": [...], "end_sample": n}, ...]
    (headers first).  end_sample is the granule position the stream stores with
    the track's last packet (packet header dwords 4-5; equal to the block-size
    sum on every other packet, and the exact track length on the last).  None
    when the stream does not walk cleanly to its end (callers then fall back to
    the flat packet scan)."""
    N = len(raw)

    def packets(o, end, into):
        while o < end:
            if o + 32 > end:
                return None
            plen = struct.unpack_from("<I", raw, o + 4)[0]
            if not (1 <= plen and o + 32 + plen <= end):
                return None
            into["packets"].append(raw[o + 32 : o + 32 + plen])
            into["end_sample"] = struct.unpack_from("<Q", raw, o + 16)[0]
            o += 32 + plen
        return o

    # group 0: a new track starts at every Vorbis identification header
    tracks, o = [], 0
    while o + 32 <= N:
        if tracks and _media_link(raw, o, len(tracks)) is not None:
            break
        plen = struct.unpack_from("<I", raw, o + 4)[0]
        if not (1 <= plen <= 65536 and o + 32 + plen <= N):
            return None
        p = raw[o + 32 : o + 32 + plen]
        if p[:7] == b"\x01vorbis":
            tracks.append({"packets": [], "end_sample": 0})
        if not tracks:
            return None
        tracks[-1]["packets"].append(p)
        tracks[-1]["end_sample"] = struct.unpack_from("<Q", raw, o + 16)[0]
        o += 32 + plen
    n = len(tracks)
    while o + 4 * (n + 1) <= N:
        sizes = _media_link(raw, o, n)
        if sizes is None:
            return None
        o += 4 * (n + 1)
        if o + sum(sizes) > N:
            break  # the closing link: group 0's sizes again
        for k in range(n):
            o = packets(o, o + sizes[k], tracks[k])
            if o is None:
                return None
    return tracks if tracks and o == N else None


_TRACK0 = re.compile(r"_track0(?=\.[^/]*$|$)", re.I)


def media_track_name(name, k, label=None):
    """Output name of track `k` of the stream `name` (`..._track0.mediastream_s`):
    the same name with the track number replaced and, when the MusicStreamSlot
    gives one, its track label: `underground_track1_Intro_loop.mediastream_s`."""
    lab = re.sub(r"[^A-Za-z0-9_-]+", "_", (label or "").strip()).strip("_")
    if lab.lower() in ("", "none"):
        lab = ""
    tag = "_track%d%s" % (k, "_" + lab if lab else "")
    if _TRACK0.search(name):
        return _TRACK0.sub(lambda m: tag, name, count=1)
    base, dot, ext = name.rpartition(".")
    return (base + tag + dot + ext) if dot and "/" not in ext else name + tag


# ---------------------------------------------------------------------------
# Console (X360/PS3) streamed audio.  Console `mediastream_s` files are NOT the
# PC Vorbis packet container; they are the engine's segment-chained stream:
#     [seg0][link][seg1][link]...[EOF loop-link]
# link = [u32be m][u32be size...]:  m = sum(sizes) + 4*(n+1); the FIRST size is
# the next segment's byte length (multi-entry links = streaming prefetch info).
#   X360 segments: raw XMA2 2048-byte packets (seg0 found by bootstrap scan).
#   PS3  segments: [32-byte header][MP3 frames]; header dword0 = payload size;
#                  MP3 frame sync sits at +0x20.  Link records are NOT emitted
#                  after every segment: most Part-2 music packs several headered
#                  segments back-to-back with a multi-entry link only between
#                  groups, and one file (str_p2) pads each segment up to a
#                  16-byte boundary.  _ps3_media_walk handles all observed
#                  layouts record-by-record (link OR segment at each offset,
#                  exact-offset first, align-16 fallback); verified lossless on
#                  all 13 Part-2 music streams (0 junk bytes, durations == PC).
# Channels/rate/total-samples come from the block 'mediastream' asset header
# (media_meta_from_header).
# ---------------------------------------------------------------------------
def _media_walk_segments(raw, seg0):
    u = lambda o: struct.unpack_from(">I", raw, o)[0]
    if not (0 < seg0 <= len(raw)):
        return None
    segs = [(0, seg0)]
    o = seg0
    while o + 8 <= len(raw):
        m = u(o)
        ents = []
        q = o + 4
        hit = False
        while q + 4 <= len(raw) and len(ents) < 32:
            e = u(q)
            ents.append(e)
            q += 4
            if m == sum(ents) + 4 * (len(ents) + 1):
                hit = True
                break
            if sum(ents) >= m:
                return None
        if not hit:
            return None
        nxt = ents[0]
        if q + nxt > len(raw):
            return segs  # EOF loop-back link
        segs.append((q, nxt))
        o = q + nxt
    return segs


def _ps3_media_link(raw, o):
    """Try to parse a link record at o: [u32be m][u32be sizes...] with
    m = sum(sizes) + 4*(n+1).  Returns end-of-link offset or None."""
    u = lambda x: struct.unpack_from(">I", raw, x)[0]
    if o + 8 > len(raw):
        return None
    m = u(o)
    ents = []
    q = o + 4
    while q + 4 <= len(raw) and len(ents) < 32:
        ents.append(u(q))
        q += 4
        if m == sum(ents) + 4 * (len(ents) + 1):
            return q
        if sum(ents) >= m:
            return None
    return None


def _ps3_media_seg(raw, o):
    """True if a [32B header][MP3 frames] segment starts at o (header dword0 =
    payload size, MP3 frame sync at +0x20)."""
    if o + 0x24 > len(raw):
        return False
    sz = struct.unpack_from(">I", raw, o)[0]
    return (
        raw[o + 0x20] == 0xFF
        and (raw[o + 0x21] & 0xE0) == 0xE0
        and 0 < sz
        and o + 0x20 + sz <= len(raw)
    )


def _ps3_media_walk(raw):
    """De-chain a PS3 mediastream_s: at each offset either a link record (skip)
    or a headered MP3 segment (collect payload).  After a segment the next
    record sits at the exact end offset OR padded to a 16-byte boundary
    (str_p2).  Returns the joined MP3 stream, or None."""
    u = lambda x: struct.unpack_from(">I", raw, x)[0]
    o = 0
    out = []
    while o + 0x24 <= len(raw):
        q = _ps3_media_link(raw, o)
        if q is not None:
            if q + 0x24 > len(raw):
                break  # EOF loop-back link
            o = q
            continue
        if not _ps3_media_seg(raw, o):
            return None
        sz = u(o)
        out.append(raw[o + 0x20 : o + 0x20 + sz])
        nxt = o + 0x20 + sz
        a = (nxt + 15) & ~15
        if nxt + 8 > len(raw):
            break
        if _ps3_media_link(raw, nxt) is not None or _ps3_media_seg(raw, nxt):
            o = nxt
        elif a != nxt and (
            a + 8 > len(raw) or _ps3_media_link(raw, a) is not None or _ps3_media_seg(raw, a)
        ):
            o = a  # 16-byte aligned next record
        else:
            return None
    return b"".join(out) if out else None


def console_media_parse(raw):
    """Detect + de-chain a console mediastream_s. Returns (codec, data) with the
    engine framing stripped ('mp3' PS3 / 'xma' X360), or None."""
    if len(raw) < 0x1000 or len(raw) < 0x24:
        return None
    # PS3: MP3 sync right after the 32-byte segment header
    if raw[0x20] == 0xFF and (raw[0x21] & 0xE0) == 0xE0:
        out = _ps3_media_walk(raw)
        if out:
            return ("mp3", out)
    # X360: XMA2 packets; segment sizes are 2048-aligned -> bootstrap seg0
    for s0 in range(0x800, min(len(raw), 0x200000), 0x800):
        segs = _media_walk_segments(raw, s0)
        if segs and len(segs) >= 2 and sum(sz for _, sz in segs) >= len(raw) * 0.9:
            return ("xma", b"".join(raw[o : o + sz] for o, sz in segs))
    # X360 fallback: single segment, engine trailer only at EOF
    if (
        len(raw) >= 2048
        and (raw[0] >> 2)
        and struct.unpack_from(">I", raw, 0)[0] & 0xFFFF == 0x0100
    ):
        return ("xma", raw[: len(raw) - (len(raw) % 2048)])
    return None


def _ps3_media_tracks(raw):
    """Per-track MP3 byte strings of a PS3 mediastream_s (see the multi-track
    note above decode_audio_tracks): group 0 is one headered segment per track,
    then [link][one chunk per track]...  A chunk is [32-byte header][MP3 frames]
    segments, each optionally padded to a 16-byte boundary.  None if it does not
    walk to the end of the file."""
    N = len(raw)

    def seg(o, end):
        for q in (o, (o + 15) & ~15):
            if q + 0x24 <= end and _ps3_media_seg(raw, q):
                sz = struct.unpack_from(">I", raw, q)[0]
                if q + 0x20 + sz <= end:
                    return q, sz
        return None

    tracks, o = [], 0
    while True:
        if tracks:
            for q in (o, (o + 15) & ~15):
                if _media_link(raw, q, len(tracks), ">") is not None:
                    o = q
                    break
            else:
                q = None
            if q is not None:
                break
        r = seg(o, N)
        if r is None or len(tracks) >= 32:
            return None
        tracks.append([raw[r[0] + 0x20 : r[0] + 0x20 + r[1]]])
        o = r[0] + 0x20 + r[1]
    n = len(tracks)
    while o + 4 * (n + 1) <= N:
        sizes = _media_link(raw, o, n, ">")
        if sizes is None:
            q = (o + 15) & ~15
            sizes = _media_link(raw, q, n, ">")
            if sizes is None:
                return None
            o = q
        o += 4 * (n + 1)
        if o + sum(sizes) > N:
            break  # closing link
        for k in range(n):
            end = o + sizes[k]
            while o < end:
                r = seg(o, end)
                if r is None:
                    if end - o < 16:  # trailing pad of the chunk
                        break
                    return None
                tracks[k].append(raw[r[0] + 0x20 : r[0] + 0x20 + r[1]])
                o = r[0] + 0x20 + r[1]
            o = end
    return [b"".join(t) for t in tracks]


def _x360_media_tracks(raw):
    """Per-track XMA2 packet strings of an X360 mediastream_s.  Chunks are whole
    2048-byte packets; group 0 has no sizes in front of it, so it is split with
    the closing link (which repeats group 0's sizes).  None if the links do not
    chain to the end of the file or the closing link does not add up."""
    N = len(raw)
    first = None
    for o in range(0x800, min(N, 0x400000), 0x800):
        for n in range(1, 17):
            sizes = _media_link(raw, o, n, ">")
            if sizes and all(x and x % 2048 == 0 for x in sizes):
                first = (o, n)
                break
        if first:
            break
    if not first:
        return None
    g0, n = first
    o = g0
    spans = []  # (offset, sizes) of groups 1..
    sizes = None
    while o + 4 * (n + 1) <= N:
        sizes = _media_link(raw, o, n, ">")
        if sizes is None:
            return None
        o += 4 * (n + 1)
        if o + sum(sizes) > N:
            break
        spans.append((o, sizes))
        o += sum(sizes)
    if sizes is None or sum(sizes) != g0 or o + sum(sizes) <= N:
        return None  # the last link read must be the closing one, equal to group 0
    tracks = [[] for _ in range(n)]
    for off, sz in [(0, sizes)] + spans:
        for k in range(n):
            tracks[k].append(raw[off : off + sz[k]])
            off += sz[k]
    return [b"".join(t) for t in tracks]


def media_tracks_console(raw):
    """(codec, [track bytes, ...]) of a console mediastream_s, one entry per
    track with the engine framing stripped ('mp3' PS3 / 'xma' X360), or None."""
    if len(raw) < 0x1000:
        return None
    if raw[0x20] == 0xFF and (raw[0x21] & 0xE0) == 0xE0:
        t = _ps3_media_tracks(raw)
        return ("mp3", t) if t else None
    t = _x360_media_tracks(raw)
    return ("xma", t) if t else None


def xma_frame_count(data):
    return sum(data[o] >> 2 for o in range(0, len(data) - 2047, 2048))


def media_meta_from_header(header, order="<"):
    """From a block 'mediastream' asset header: (mediastream_path, channels,
    rate, total_samples) -- channels/rate/samples may be None if not found
    (the u32 before channels = XMA frame-count*512 exactly, i.e. total samples)."""
    m = re.search(rb"/[ -~]{4,220}?\.mediastream_s\x00", header, re.I)
    if not m:
        return None
    path = m.group()[:-1].decode("latin1")
    ch = rate = samples = None
    w = re.search(rb"\.wav\x00", header, re.I)
    if w:
        tail = header[w.end() : w.end() + 48]
        for off in range(0, 25):
            if off + 12 <= len(tail):
                a, b2, c = struct.unpack_from(order + "III", tail, off)
                if 1 <= b2 <= 8 and 8000 <= c <= 96000:
                    samples, ch, rate = a, b2, c
                    break
    return (path, ch, rate, samples)


def media_desc_from_header(header, order="<"):
    """The whole block 'mediastream' descriptor (the `<x>_track0.wav` asset):
    {"stream", "groups", "first_group_sizes", "tracks": [{"source", "samples",
    "channels", "rate", "cue_points": [{"name", "sample"}]}]}, or None.

    After the stream path: [u32 m][u32 chunk size x tracks] (group 0's link,
    see media_tracks_pc), [u32 groups][u32 0], then per track
    [str source wav][u32 0][u32 samples][u32 channels][u32 rate][u32 0][i32 -1]
    [u32 cues] cues x ([str name][u32 sample]); str = [u32 len][bytes, NUL
    included].  The u32 before the path's length is the track count.  Console
    track records carry codec fields after the cues (skipped).  Layout read on
    the 13 Part-2 descriptors of PC, X360 and PS3 and the 13 of Part 1 PC."""
    m = re.search(rb"/[ -~]{4,220}?\.mediastream_s\x00", header, re.I)
    if not m or m.start() < 8:
        return None
    u = lambda o: struct.unpack_from(order + "I", header, o)[0]

    def string(o):
        if o + 4 > len(header):
            raise SoundHeaderError("descriptor ends inside a string")
        n = u(o)
        if not (1 <= n <= 512) or o + 4 + n > len(header):
            raise SoundHeaderError("bad string length")
        return header[o + 4 : o + 4 + n].split(b"\x00")[0].decode("latin1"), o + 4 + n

    try:
        n = u(m.start() - 8)
        if not (1 <= n <= 32) or u(m.start() - 4) != len(m.group()):
            return None
        o = m.end()
        sizes = _media_link(header, o, n, order)
        if sizes is None:
            return None
        o += 4 * (n + 1)
        groups = u(o)
        o += 8
        tracks = []
        for _ in range(n):
            src, o = string(o)
            _z, samples, ch, rate, _z2, _m1, ncue = struct.unpack_from(order + "7I", header, o)
            o += 28
            if not (1 <= ch <= 8 and 8000 <= rate <= 96000 and ncue <= 4096):
                return None
            cues = []
            for _c in range(ncue):
                nm, o = string(o)
                cues.append({"name": nm, "sample": u(o)})
                o += 4
            tracks.append(
                {
                    "source": src,
                    "samples": samples,
                    "channels": ch,
                    "rate": rate,
                    "cue_points": cues,
                }
            )
            if len(tracks) < n:
                # console records end with codec fields before the next source
                # path: PS3 12 bytes (padded samples, bytes/s, MP3 ratio),
                # X360 [u32 k][k x u32 seek sample][u32 XMA quality]; PC none
                k = u(o) if o + 4 <= len(header) else 0
                for q in (o, o + 12, o + 8 + 4 * k):
                    if q + 5 <= len(header) and 1 <= u(q) <= 512 and header[q + 4 : q + 5] == b"/":
                        o = q
                        break
                else:
                    return None
    except (struct.error, ValueError):
        return None
    return {
        "stream": m.group()[:-1].decode("latin1"),
        "groups": groups,
        "first_group_sizes": sizes,
        "tracks": tracks,
    }


def adpcm_layout(header, pe, ch):
    """The MS-ADPCM fields of a PC 'sound' header (sfx_info): (samples, block
    align, [(c1, c2)] * 7, data bytes) or None when they do not fit -- block
    align 16..4096, the data inside the header."""
    if pe + 62 > len(header):
        return None
    nsamp, ba = struct.unpack_from("<2I", header, pe + 22)
    c = struct.unpack_from("<14h", header, pe + 30)
    dbytes = struct.unpack_from("<I", header, pe + 58)[0]
    if not (16 <= ba <= 4096) or dbytes < 7 * ch or pe + 62 + dbytes > len(header):
        return None
    pairs = list(itertools.batched(c, 2))  # seven (c1, c2)
    return nsamp, ba, pairs, header[pe + 62 : pe + 62 + dbytes]


def sfx_info(header, order="<"):
    """Fields of a 'sound' asset header (loader 0x449e40), or None.

    pe = property-bag end:  +0 u8 looping, +1 u8 is3d, +2 u32 channels,
    +6 u32 original rate, +10 u32 format (1 PCM16, 2 MS-ADPCM, 3 XMA2),
    +14 u32 sample rate.  PCM: +18 samples, +22 data bytes, +26 data.
    ADPCM: +22 samples, +26 block align, +30 seven coefficient pairs, +58 data
    bytes, +62 data.  A cue list (u32 count, then [str name][u32 time]) follows
    the data; no shipped PC sound has cues.  The rate at +14 is 44100 on every
    mono PC sound and the file's own rate on the stereo ones.

    Console (order ">", layouts read on the data of all four console sets):
    X360 is the PCM layout with format 3: +18 samples (= XMA2 frames x 512),
    +22 data bytes, +26 the 2048-byte XMA2 packets.  PS3 has its own layout
    (codec "mp3", see _ps3_sound_info).  Console records carry
    `duration_source`: "header" (the stored sample count), "frame_count"
    (stored count is 0: frames x frame size) or "none" (no duration)."""
    pe = kapow_block.propbag_end(header, order)
    if pe + 30 > len(header):
        return None
    loop, is3d = header[pe], header[pe + 1]
    ch, orig, fmt, rate = struct.unpack_from(order + "4I", header, pe + 2)
    if not (1 <= ch <= 2) or fmt not in (1, 2, 3):
        return _ps3_sound_info(header, pe) if order == ">" else None
    out = dict(
        looping=bool(loop),
        is3d=bool(is3d),
        channels=ch,
        original_rate=orig,
        codec={1: "pcm16", 2: "ms-adpcm", 3: "xma2"}[fmt],
        rate=rate,
        _pe=pe,
    )
    if fmt == 2:
        if pe + 62 > len(header):
            return None
        out["samples"], out["block_align"] = struct.unpack_from(order + "2I", header, pe + 22)
        out["data_bytes"] = struct.unpack_from(order + "I", header, pe + 58)[0]
        out["data_offset"] = pe + 62
    else:
        out["samples"], out["data_bytes"] = struct.unpack_from(order + "2I", header, pe + 18)
        out["data_offset"] = pe + 26
    end = out["data_offset"] + out["data_bytes"]
    cues = []
    if fmt != 3 and end + 4 <= len(header):
        try:
            n = struct.unpack_from(order + "I", header, end)[0]
            o = end + 4
            for _ in range(n if n <= 4096 else 0):
                ln = struct.unpack_from(order + "I", header, o)[0]
                nm = header[o + 4 : o + 4 + ln].split(b"\x00")[0].decode("latin1")
                cues.append(
                    {"name": nm, "sample": struct.unpack_from(order + "I", header, o + 4 + ln)[0]}
                )
                o += 8 + ln
        except struct.error:
            cues = []
    out["cue_points"] = cues
    if fmt == 3:  # X360: the stored count is whole XMA2 frames (512 samples each)
        data = header[out["data_offset"] : end]
        out["xma_frames"] = xma_frame_count(data) if len(data) == out["data_bytes"] else None
        out["duration_source"] = "header"
        if not out["samples"] and out["xma_frames"]:
            out["samples"] = out["xma_frames"] * 512
            out["duration_source"] = "frame_count"
    if out["samples"] and 8000 <= rate <= 96000:
        out["duration_s"] = round(out["samples"] / rate, 4)
    elif fmt == 3:
        out["duration_s"], out["duration_source"] = None, "none"
    return out


_MP3_KBPS = {
    3: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),  # MPEG-1 layer III
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),  # MPEG-2 layer III
    0: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),  # MPEG-2.5
}
_MP3_RATE = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


def mp3_frame_stats(data):
    """Walk the layer III frames of `data` from offset 0:
    {"frames", "samples" (frames x 1152, or x 576 for MPEG-2 / 2.5), "rate",
    "channels", "bytes" (length of the whole frames), "clean" (the walk used
    every byte)}.  frames = 0 when `data` does not start with a frame."""
    o = n = samples = 0
    rate = ch = None
    N = len(data)
    while o + 4 <= N:
        b1, b2 = data[o + 1], data[o + 2]
        ver, bi, si = (b1 >> 3) & 3, b2 >> 4, (b2 >> 2) & 3
        if data[o] != 0xFF or (b1 & 0xE0) != 0xE0 or ver == 1 or ((b1 >> 1) & 3) != 1:
            break
        if not (0 < bi < 15) or si == 3:
            break
        spf = 1152 if ver == 3 else 576
        size = spf // 8 * _MP3_KBPS[ver][bi] * 1000 // _MP3_RATE[ver][si] + ((b2 >> 1) & 1)
        if o + size > N:
            break
        if not n:
            rate, ch = _MP3_RATE[ver][si], 1 if (data[o + 3] >> 6) == 3 else 2
        n += 1
        samples += spf
        o += size
    return {
        "frames": n,
        "samples": samples,
        "rate": rate,
        "channels": ch,
        "bytes": o,
        "clean": o == N,
    }


def _ps3_sound_info(header, pe):
    """Fields of a PS3 'sound' asset header (big-endian; the 2,921 Part-2 and
    3,953 Part-1 sounds of the PS3 disc all fit, and the field order is the PS3
    Part 2 loader's, 0x140f10 in sounddataps3.cpp).  pe = property-bag end:
    +0 u8 looping, +1 u8 is3d, +2 u8 compressed (1 on every sound: the
    bytes-per-second field is stored; 0 would mean PCM16 with that field absent
    and taken as rate x 2 x channels, a layout no shipped sound uses and this
    reader does not handle), +3 u32 sample rate, +7 u32 channels, +11 u32 samples,
    +15 u32 bytes per second, +19 u32 size (32 + MP3 bytes + 0..15 padding),
    +23 the 32-byte segment header of the streams (dword 0 = MP3 bytes; dword 4,
    on looping sounds only, is the byte length of two MP3 frames, floor(2 x 1152 x
    bytes per second / rate): 384 / 417 / 768, measured on 145 of 145 looping
    sounds of both PS3 sets; inferred: the byte offset of the looped region, which
    matches the sample count of frames - 2), +55 the MP3
    frames, then the padding and a u32 cue count (0 on every shipped sound).

    `samples` counts whole MP3 frames (frames x 1152: the encoder delay and
    the padding of the last frame are inside it), so the duration runs 0.03 -
    0.06 s over the PC sound's.  A looping sound holds two frames more than
    its count.  None when the bytes do not fit this layout."""
    if pe + 59 > len(header):
        return None
    loop, is3d = header[pe], header[pe + 1]
    rate, ch, samples, bps, size, seg0 = struct.unpack_from(">6I", header, pe + 3)
    d0 = pe + 55
    if not (1 <= ch <= 2 and 8000 <= rate <= 96000 and 0 < seg0 <= len(header) - d0):
        return None
    if not (seg0 + 32 <= size <= len(header) - pe - 23):
        return None
    fs = mp3_frame_stats(header[d0 : d0 + seg0])
    if not fs["frames"]:
        return None
    out = dict(
        looping=bool(loop),
        is3d=bool(is3d),
        channels=ch,
        original_rate=None,  # the PS3 header stores one rate only
        codec="mp3",
        rate=rate,
        _pe=pe,
        samples=samples,
        data_bytes=seg0,
        data_offset=d0,
        bytes_per_second=bps,
        mp3_frames=fs["frames"],
        mp3_frame_samples=fs["samples"],
        mp3_clean=fs["clean"],
    )
    w4 = struct.unpack_from(">I", header, pe + 23 + 16)[0]
    if w4:
        out["segment_word4"] = w4
        out["segment_word4_rule"] = "2 mp3 frames in bytes"
        out["loop_skip_frames"] = 2
    cues, o = [], pe + 23 + size
    try:  # the PC cue list layout; no shipped console sound has a cue
        n = struct.unpack_from(">I", header, o)[0] if o + 4 <= len(header) else 0
        o += 4
        for _ in range(n if n <= 4096 else 0):
            ln = struct.unpack_from(">I", header, o)[0]
            nm = header[o + 4 : o + 4 + ln].split(b"\x00")[0].decode("latin1")
            cues.append({"name": nm, "sample": struct.unpack_from(">I", header, o + 4 + ln)[0]})
            o += 8 + ln
    except struct.error:
        cues = []
    out["cue_points"] = cues
    out["duration_source"] = "header"
    if not samples:
        out["samples"], out["duration_source"] = fs["samples"], "frame_count"
    out["duration_s"] = round(out["samples"] / rate, 4)
    return out
