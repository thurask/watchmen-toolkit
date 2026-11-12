#!/usr/bin/env python3
"""
watchmen_extract.py  --  master asset extractor for
*Watchmen: The End Is Nigh, Part 2* (Kapow engine, PC).

Feed it game.naz and it walks the whole reverse-engineered chain and writes:

    OUT/files/      every NAZ entry, decrypted & inflated (the raw asset tree)
    OUT/textures/   <asset>/<j>_<label>_<WxH>_<FMT>.png      (diffuse/normal/
                                                              specular/glossiness)
    OUT/models/     <asset>.obj (+ .mtl)                     (Model/ModelRes:
                    per-submesh objects, each material named by its texture and
                    linking diffuse->map_Kd normal->norm specular->map_Ks
                    glossiness->map_Ns from the textures/ dump above)
    OUT/audio/      <asset>.wav (SFX/voice, MS-ADPCM/PCM at the header's rate:
                    44100 mono, the file's own rate stereo); sound_info.json
                    (rate, length, loop flag, cue points of every sound)
    OUT/audio/      <name>_track<k>.mediastream_s.ogg        (.mediastream_s =
                    Vorbis; one file per track of a music stream) + <name>.json
                    (tracks, cue points, MusicSetup track states)
    OUT/extracted/  <asset> (+ .stream, + .json)             (every raw block asset)

Pipeline (see docs/WATCHMEN_EXTRACTION_MASTER.md for the detail):
  AUDIO    raw Vorbis packets (no Ogg framing) in [32-byte block][packet] framing,
           in ~40 KB chunks, one chunk per track per group, groups chained by
           link records; rebuilt into one real Ogg Vorbis file per track.

Usage:
    python watchmen_extract.py game.naz -o OUT
        [--no-files] [--no-textures] [--no-models] [--no-audio]
        [--exact-audio]   sample-perfect Ogg granulepos (parses Vorbis modes)
        [--flat-music]    music streams as ONE file each (the output of releases before 1.4.0)
        [--music-track-labels]  MusicStreamSlot track names in the file names
        [--smpl-loops]    RIFF smpl loop chunk on sounds with the loop flag
        [--no-text]       no text/ (every text asset, every language)
        [--no-nav]        no nav/ (per level navigation mesh + graph)
        [--limit N]       stop after N block assets (debug)
        [--quiet]

Requires numpy and Pillow. Python 3.13+.
"""

import argparse
import functools
import importlib
import os
import struct
import sys
import types
import array
import wave
from pathlib import Path


# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)

import extract_log  # noqa: E402
import extract_paths  # noqa: E402
import naz_archive  # noqa: E402
import kapow_block  # noqa: E402

# under another name: `watchmen_extract.texture_sheet` is the forwarded function, and
# Python 3.15 reads a module's own namespace before a property of its type
import texture_sheet as texture_sheet_mod  # noqa: E402
import texture_carve  # noqa: E402
import model_header  # noqa: E402
import model_mesh  # noqa: E402
import obj_mtl  # noqa: E402
import model_export  # noqa: E402
import sound_header  # noqa: E402

# MS-ADPCM tables (SFX 'sound' assets are MS-ADPCM/PCM -> WAV; music stays Ogg)
_COEF = (256, 0, 512, -256, 0, 0, 192, 64, 240, 0, 460, -208, 392, -232)
_COEFB = struct.pack("<14h", *_COEF)
_ADAPT = (230, 230, 230, 230, 307, 409, 512, 614, 768, 614, 512, 409, 307, 230, 230, 230)
_C1 = (256, 512, 0, 192, 240, 460, 392)
_C2 = (0, -256, 0, 64, 0, -208, -232)


# ===========================================================================
# (5) Audio  (.mediastream_s  ->  Ogg Vorbis)
# ===========================================================================
def _audio_packets(d):
    N = len(d)

    def ok(o):
        if o + 32 > N:
            return False
        _a, plen, _b = struct.unpack_from("<III", d, o)
        return 1 <= plen <= 8192 and o + 32 + plen <= N

    o, pk = 0, []
    while o + 32 <= N:
        _a, plen, _b = struct.unpack_from("<III", d, o)
        if 1 <= plen <= 8192 and o + 32 + plen <= N:
            pk.append(d[o + 32 : o + 32 + plen])
            o += 32 + plen
        else:  # chunk boundary -> resync
            scan, found = o, None
            while scan < min(N - 64, o + 200000):
                if ok(scan):
                    _x, nlen, _y = struct.unpack_from("<III", d, scan)
                    if ok(scan + 32 + nlen):
                        found = scan
                        break
                scan += 1
            if found is None:
                break
            o = found
    return pk


def _ogg_crc_table():
    t = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if (r & 0x80000000) else (r << 1) & 0xFFFFFFFF
        t.append(r)
    return t


_OGGCRC = _ogg_crc_table()


def _ogg_crc(data):
    c = 0
    for b in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ _OGGCRC[((c >> 24) & 0xFF) ^ b]
    return c


def _lacing(L):
    return [255] * (L // 255) + ([0] if L % 255 == 0 else [L % 255])


#: target body size of an Ogg page written by ogg_from_packets (libvorbis
#: aims at about 4 KB too); a page also ends at 255 lacing values
OGG_PAGE_BYTES = 4096


class _OggWriter:
    """Packets -> Ogg pages of one logical stream.  Packets are added to the
    current page while it stays within OGG_PAGE_BYTES of body and 255 lacing
    values; a packet that would not fit starts the next page, and only a packet
    larger than a whole page is split (continued on the next page, header type
    0x01).  A page's granule position is that of the last packet completed on
    it, -1 when none completes (Ogg framing, RFC 3533)."""

    def __init__(s, serial=1, page_bytes=OGG_PAGE_BYTES):
        s.serial, s.page_bytes = serial, page_bytes
        s.seq, s.out = 0, bytearray()
        s.seg, s.body = [], bytearray()
        s.granule, s.cont, s.bos = -1, False, True

    def flush(s, eos=False, split=False):
        """End the current page (if it holds anything); `eos` marks the last,
        `split`: a packet goes on on the next page."""
        if not s.seg:
            return
        htype = (0x01 if s.cont else 0) | (0x02 if s.bos else 0) | (0x04 if eos else 0)
        h = (
            b"OggS"
            + bytes([0, htype])
            + struct.pack("<q", s.granule)
            + struct.pack("<I", s.serial)
            + struct.pack("<I", s.seq)
            + b"\x00\x00\x00\x00"
            + bytes([len(s.seg)])
            + bytes(s.seg)
        )
        pg = h + bytes(s.body)
        s.out += pg[:22] + struct.pack("<I", _ogg_crc(pg)) + pg[26:]
        s.seq += 1
        s.seg, s.body, s.granule, s.bos, s.cont = [], bytearray(), -1, False, split

    def packet(s, p, granule):
        """Add packet `p`, whose last sample is at `granule`.  A full page is
        written when the next lacing value would not fit, so the last packet
        always waits for the final flush(eos=True)."""
        lac = _lacing(len(p))
        if s.seg and (len(s.seg) + len(lac) > 255 or len(s.body) + len(p) > s.page_bytes):
            s.flush()  # the packet starts the next page
        pos = 0
        for L in lac:
            if len(s.seg) == 255:
                s.flush(split=pos > 0)
            s.seg.append(L)
            s.body += p[pos : pos + L]
            pos += L
        s.granule = granule


class _BR:
    """LSB-first bit reader over bytes (the Vorbis packing); reading past the
    end raises ValueError."""

    def __init__(s, d):
        s.d, s.p = d, 0

    def read(s, n):
        if s.p + n > len(s.d) * 8:
            raise ValueError("vorbis setup: truncated (bit %d + %d of %d)" % (s.p, n, len(s.d) * 8))
        v = 0
        for i in range(n):
            v |= ((s.d[s.p >> 3] >> (s.p & 7)) & 1) << i
            s.p += 1
        return v


def _expect(cond, what):
    """Input validation that survives `python -O` (an assert would vanish)."""
    if not cond:
        raise ValueError("vorbis setup: " + what)


def _ilog(x):
    n = 0
    while x > 0:
        n += 1
        x >>= 1
    return n


def _lk1(entries, dim):
    v = 0
    while (v + 1) ** dim <= entries:
        v += 1
    return v


def vorbis_blockflags(setup, channels):
    """The block flag (0 short, 1 long) of every mode of a Vorbis setup header
    (packet type 5), read by walking the codebooks, time-domain transforms,
    floors, residues and mappings in the Vorbis I order.  ValueError for a
    header that does not follow it (also under `python -O`)."""
    b = _BR(setup)
    _expect(b.read(8) == 5, "not a setup header (packet type)")
    for c in b"vorbis":
        _expect(b.read(8) == c, "no 'vorbis' signature")
    for _ in range(b.read(8) + 1):  # codebooks
        _expect(b.read(24) == 0x564342, "codebook sync pattern missing")
        dim = b.read(16)
        ent = b.read(24)
        if not b.read(1):
            sp = b.read(1)
            for _e in range(ent):
                if sp:
                    if b.read(1):
                        b.read(5)
                else:
                    b.read(5)
        else:
            cur = 0
            b.read(5)
            while cur < ent:
                cur += b.read(_ilog(ent - cur))
        lut = b.read(4)
        if lut in (1, 2):
            b.read(32)
            b.read(32)
            vb = b.read(4) + 1
            b.read(1)
            for _v in range(_lk1(ent, dim) if lut == 1 else ent * dim):
                b.read(vb)
    for _ in range(b.read(6) + 1):
        _expect(b.read(16) == 0, "time-domain transform type not 0")
    for _ in range(b.read(6) + 1):  # floors
        ft = b.read(16)
        match ft:
            case 0:
                b.read(8)
                b.read(16)
                b.read(16)
                b.read(6)
                b.read(8)
                for _ in range(b.read(4) + 1):
                    b.read(8)
            case 1:
                plist = [b.read(4) for _ in range(b.read(5))]
                mx = max(plist) if plist else -1
                cd = [0] * (mx + 1)
                for j in range(mx + 1):
                    cd[j] = b.read(3) + 1
                    cs = b.read(2)
                    if cs > 0:
                        b.read(8)
                    for _ in range(1 << cs):
                        b.read(8)
                b.read(2)
                rb = b.read(4)
                for j in plist:
                    for _ in range(cd[j]):
                        b.read(rb)
            case _:
                raise ValueError("vorbis setup: floor type %d" % ft)
    for _ in range(b.read(6) + 1):  # residues
        b.read(16)
        b.read(24)
        b.read(24)
        b.read(24)
        cl = b.read(6) + 1
        b.read(8)
        casc = []
        for _ in range(cl):
            lo = b.read(3)
            casc.append(lo + 8 * (b.read(5) if b.read(1) else 0))
        for c in casc:
            for k in range(8):
                if c & (1 << k):
                    b.read(8)
    for _ in range(b.read(6) + 1):  # mappings
        _expect(b.read(16) == 0, "mapping type not 0")
        sm = (b.read(4) + 1) if b.read(1) else 1
        if b.read(1):
            for _ in range(b.read(8) + 1):
                b.read(_ilog(channels - 1))
                b.read(_ilog(channels - 1))
        _expect(b.read(2) == 0, "mapping reserved bits not 0")
        if sm > 1:
            for _ in range(channels):
                b.read(4)
        for _ in range(sm):
            b.read(8)
            b.read(8)
            b.read(8)
    flags = []
    for _ in range(b.read(6) + 1):  # modes
        flags.append(b.read(1))
        _expect(b.read(16) == 0 and b.read(16) == 0, "mode window / transform type not 0")
        b.read(8)
    return flags


_vorbis_blockflags = vorbis_blockflags  # the private spelling, kept for existing callers


def ogg_from_packets(pk, exact, end=None):
    """One Ogg Vorbis file from a Vorbis packet list (3 header packets + audio).
    end: the stream's own end sample position (stamped on the last page so a
    decoder trims the final block, as Vorbis intends); None = computed position.
    Returns (ogg bytes, channels, rate, audio packet count, last granulepos) or None."""
    headers = [p for p in pk if p and p[0] in (1, 3, 5)][:3]
    audio = [p for p in pk if p and p[0] not in (1, 3, 5)]
    if len(headers) < 3 or not audio:
        return None
    if headers[0][:7] != b"\x01vorbis":
        return None
    ch = headers[0][11]
    rate = struct.unpack_from("<I", headers[0], 12)[0]
    gr = None
    if exact:
        # Sample-perfect granulepos from the per-packet Vorbis block sizes. The
        # approximate 1024/packet path OVERSHOOTS (stamps more samples than the page
        # holds), and players that sync to granulepos then insert gaps -> choppy.
        try:
            bsb = headers[0][28]
            bs0, bs1 = 1 << (bsb & 0xF), 1 << (bsb >> 4)
            fl = vorbis_blockflags(headers[2], ch)
            mb = _ilog(len(fl) - 1)
            bss = [
                (bs1 if fl[((p[0] >> 1) & ((1 << mb) - 1)) if mb else 0] else bs0) for p in audio
            ]
            gr, g = [0], 0
            for n in range(1, len(bss)):
                g += (bss[n - 1] + bss[n]) // 4
                gr.append(g)
        except (struct.error, ValueError, IndexError) as e:  # setup header not walked
            extract_log.warn(
                "      WARNING: Ogg granule positions estimated at 1024 samples per packet, "
                "playback may stutter (%s: %s)" % (type(e).__name__, e)
            )
            gr = None
    if gr is None:
        gr = [(i + 1) * 1024 for i in range(len(audio))]
    if end is not None and (len(gr) < 2 or gr[-2] < end) and end <= gr[-1]:
        gr[-1] = end
    # Vorbis I in Ogg: the identification header alone on the first page, the
    # comment and setup headers finishing on the page(s) before the first audio
    # page (granule 0); audio packets fill pages of about OGG_PAGE_BYTES (not
    # one page per audio packet: 27+ bytes of page header per ~100-byte
    # packet); the last page carries the end position (trims the final block)
    # and the EOS flag
    w = _OggWriter(1)
    w.packet(headers[0], 0)
    w.flush()
    w.packet(headers[1], 0)
    w.packet(headers[2], 0)
    w.flush()
    for i, p in enumerate(audio):
        w.packet(p, gr[i])
    w.flush(eos=True)
    return bytes(w.out), ch, rate, len(audio), gr[-1]


_ogg_from_packets = ogg_from_packets  # the private spelling, kept for existing callers


def decode_audio(raw, out_path, exact, log=None):
    """The single-file output (--flat-music): every packet of the stream in file order.
    Correct for a one-track stream; a multi-track stream comes out as its tracks'
    chunks appended in turn (use decode_audio_tracks)."""
    if not callable(log):
        log = lambda *a, **k: None
    r = ogg_from_packets(_audio_packets(raw), exact)
    if r is None:
        return False
    out, ch, rate, npk, last = r
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(out)
    log(
        "      Vorbis %dch %dHz %d pkts -> %s (%.1fs)" % (ch, rate, npk, out_path.name, last / rate)
    )
    return True


def decode_audio_tracks(raw, out_dir, name, exact=True, log=None, labels=None):
    """Write a PC stream as one Ogg Vorbis file per track under `out_dir`.

    A one-track stream keeps the name decode_audio gives it; like every track it
    ends at the stream's stored end position.  Returns [{index, file, label, channels, rate, samples, duration_s}]
    or None when the stream is not a clean multi-track stream (nothing written)."""
    if not callable(log):
        log = lambda *a, **k: None
    tracks = sound_header.media_tracks_pc(raw)
    if not tracks:
        return None
    out = []
    for k, trk in enumerate(tracks):
        lab = labels[k] if labels and k < len(labels) else None
        tname = (name if len(tracks) == 1 else sound_header.media_track_name(name, k, lab)) + ".ogg"
        r = ogg_from_packets(trk["packets"], exact, trk["end_sample"])
        if r is None:
            return None
        data, ch, rate, npk, last = r
        outp = extract_paths.safe(out_dir, tname)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(data)
        log(
            "      Vorbis %dch %dHz %d pkts -> %s (%.1fs)%s"
            % (ch, rate, npk, outp.name, last / rate, "" if len(tracks) == 1 else " [track %d]" % k)
        )
        out.append(
            dict(
                index=k,
                file=extract_paths.out_rel(out_dir, tname),
                label=lab,
                channels=ch,
                rate=rate,
                samples=last,
                duration_s=round(last / rate, 4),
            )
        )
    return out


def _xma2_riff(data, ch, rate, nsamp):
    """Wrap raw XMA2 packet data in a Microsoft XMA RIFF (XMA2WAVEFORMATEX)."""
    fmt = struct.pack("<HHIIHHH", 0x166, ch, rate, rate * ch * 2, 4, 16, 34)
    fmt += struct.pack(
        "<HIIIIIIIBBH",
        (ch + 1) // 2,
        3 if ch == 2 else 4,
        nsamp,
        0x10000,
        0,
        nsamp,
        0,
        0,
        0,
        4,
        (len(data) + 0xFFFF) // 0x10000,
    )
    return (
        b"RIFF"
        + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


def _emit_audio(container, ext, name, out_dir, vgmstream_cli, log, tag, keep_container=False):
    """Write an audio container; convert to .wav via vgmstream-cli if provided.
    keep_container=True also writes the raw container (.xma/.mp3) alongside the
    .wav -- valid XMA2/MP3 that any working decoder can re-convert (see MASTER
    §14: short X360 XMA2 fails in current vgmstream/ffmpeg but the data is good).

    X360 XMA is ALWAYS kept (keep default-on for `.xma`): the raw container is
    the reliable artifact and a .wav is only produced when --vgmstream-cli is
    given.  --keep-xma still forces keeping PS3 .mp3 containers too."""
    keep_container = keep_container or ext == ".xma"
    base = extract_paths.safe(out_dir, name)

    def _keep():
        outp = base.with_suffix(base.suffix + ext)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(container)
        return outp

    if vgmstream_cli:
        import subprocess
        import tempfile
        import os as _os

        wav = base.with_suffix(base.suffix + ".wav")
        wav.parent.mkdir(parents=True, exist_ok=True)
        tf = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        try:
            try:
                tf.write(container)
            finally:
                tf.close()  # also when the write fails: an open file cannot be unlinked on Windows
            pr = subprocess.run(
                [str(vgmstream_cli), "-o", str(wav), tf.name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            if pr.returncode == 0 and wav.exists():
                kept = " +%s" % _keep().name if keep_container else ""
                log("      %s %s -> %s%s" % (tag, name.split("/")[-1], wav.name, kept))
                return True
            log("      ! vgmstream failed on %s (rc=%s); writing %s" % (name, pr.returncode, ext))
        finally:
            try:
                _os.unlink(tf.name)
            except OSError:
                pass
    outp = _keep()
    log("      %s %s -> %s" % (tag, name.split("/")[-1], outp.name))
    return True


def decode_sfx_console(header, order, name, out_dir, vgmstream_cli, log, keep_container=False):
    """Console inline 'sound' assets (PC uses decode_sfx): the header's audio
    is written as a container (.xma X360 / .mp3 PS3; .wav with vgmstream-cli).
    Returns the sfx_info record of the sound ("file" = the file written,
    relative to out_dir) or False when nothing was written.

    X360: the XMA2 packets start at pe+26, right after their byte count (the
    packet frame counts add up to samples / 512 there on every shipped sound;
    a cut from pe+30 lands four bytes into the first packet, and no decoder
    reads that).  PS3: the MP3 bytes of the header's one segment.  A
    header sfx_info does not read falls back to a byte scan, and says so."""
    try:
        info = sound_header.sfx_info(header, order)
    except (struct.error, IndexError, ValueError):
        info = None

    def done(ok, ext, rec):
        if not ok:
            return False
        wav = vgmstream_cli and extract_paths.safe(out_dir, name + ".wav").exists()
        rec.pop("_pe", None)
        rec["file"] = extract_paths.out_rel(out_dir, name + (".wav" if wav else ext))
        if wav:
            try:
                with wave.open(str(extract_paths.safe(out_dir, name + ".wav")), "rb") as w:
                    rec["decoded_samples"] = w.getnframes()
                    rec["decoded_duration_s"] = round(w.getnframes() / float(w.getframerate()), 4)
            except (wave.Error, OSError, EOFError, ZeroDivisionError):
                pass
        if not rec.get("duration_s"):
            rec["duration_s"], rec["duration_source"] = None, "none"
            log(
                "      WARNING: sfx %s: no sample count in the header and no frames: no duration"
                % name
            )
        return rec

    if info and info["codec"] in ("xma2", "mp3"):
        o, n = info["data_offset"], info["data_bytes"]
        data = header[o : o + n]
        if info["codec"] == "xma2" and n and n % 2048 == 0 and len(data) == n:
            rate = info["rate"] if 8000 <= info["rate"] <= 96000 else 44100
            ns = info["samples"] or sound_header.xma_frame_count(data) * 512
            ok = _emit_audio(
                _xma2_riff(data, info["channels"], rate, ns),
                ".xma",
                name,
                out_dir,
                vgmstream_cli,
                log,
                "XMA-SFX",
                keep_container,
            )
            return done(ok, ".xma", info)
        if info["codec"] == "mp3" and len(data) == n:
            if not info["mp3_clean"]:
                log(
                    "      WARNING: sfx %s: MP3 data is not whole frames (%d frames walked); written as stored"
                    % (name, info["mp3_frames"])
                )
            ok = _emit_audio(
                data, ".mp3", name, out_dir, vgmstream_cli, log, "MP3-SFX", keep_container
            )
            return done(ok, ".mp3", info)
    # not a layout sfx_info reads: the fallback scan (no header facts are known)
    pe = kapow_block.propbag_end(header, order)
    if pe + 30 > len(header):
        return False
    unknown = dict(codec=None, duration_s=None, duration_source="none", header="not recognised")
    ch = struct.unpack_from(order + "H", header, pe + 4)[0]
    codec = struct.unpack_from(order + "I", header, pe + 10)[0]
    rate = struct.unpack_from(order + "I", header, pe + 14)[0]
    nsamp = struct.unpack_from(order + "I", header, pe + 18)[0]
    dsz = struct.unpack_from(order + "I", header, pe + 22)[0]
    if codec == 3 and 1 <= ch <= 2 and dsz and dsz % 2048 == 0 and pe + 26 + dsz <= len(header):
        data = header[pe + 26 : pe + 26 + dsz]
        if not (8000 <= rate <= 96000):
            rate = 44100
        ns = min(nsamp, 0xFFFFFFFF) or sound_header.xma_frame_count(data) * 512
        log(
            "      WARNING: sfx %s: sound header not recognised; XMA2 packets cut by the fallback scan"
            % name
        )
        ok = _emit_audio(
            _xma2_riff(data, ch, rate, ns),
            ".xma",
            name,
            out_dir,
            vgmstream_cli,
            log,
            "XMA-SFX",
            keep_container,
        )
        return done(ok, ".xma", dict(unknown, codec="xma2"))
    for i in range(pe, min(len(header) - 4, pe + 256)):
        if header[i] == 0xFF and (header[i + 1] & 0xE0) == 0xE0:
            best = None
            for o in range(pe, min(pe + 64, len(header) - 4)):
                v = struct.unpack_from(">I", header, o)[0]
                if 0 < v <= len(header) - i and (len(header) - i) - v < 512:
                    best = v
                    break
            data = header[i : i + best] if best else header[i:]
            fs = sound_header.mp3_frame_stats(data)
            if not fs["frames"]:
                continue  # two bytes that look like a sync, not an MP3 frame
            log(
                "      WARNING: sfx %s: sound header not recognised; MP3 cut by the fallback scan"
                % name
            )
            rec = dict(
                unknown,
                codec="mp3",
                channels=fs["channels"],
                rate=fs["rate"],
                samples=fs["samples"],
                mp3_frames=fs["frames"],
                duration_s=round(fs["samples"] / float(fs["rate"]), 4),
                duration_source="frame_count",
            )
            ok = _emit_audio(
                data, ".mp3", name, out_dir, vgmstream_cli, log, "MP3-SFX", keep_container
            )
            return done(ok, ".mp3", rec)
    return False


def decode_console_audio(
    name,
    raw,
    out_dir,
    meta,
    vgmstream_cli,
    log,
    keep_container=False,
    tracks=False,
    labels=None,
    desc=None,
):
    """Decode one console mediastream_s. meta = (ch, rate, samples) or None.
    Writes .wav via vgmstream-cli when available; else .mp3 (PS3) / .xma (X360).

    tracks=True: a multi-track stream is written as one file per track
    (media_track_name; `labels` = the MusicStreamSlot track names, `desc` =
    media_desc_from_header for per-track sample counts) and the list of track
    records is returned.  A one-track stream, or one that does not split
    cleanly, is written by the single-file path below and
    returned as a one-record list.  tracks=False returns True / False."""
    split = sound_header.media_tracks_console(raw) if tracks else None
    if split and len(split[1]) > 1:
        codec, parts = split
        ch, rate, samples = meta if meta else (None, None, None)
        out = []
        for k, data in enumerate(parts):
            lab = labels[k] if labels and k < len(labels) else None
            tname = sound_header.media_track_name(name, k, lab)
            dt = desc["tracks"][k] if desc and k < len(desc.get("tracks", [])) else {}
            tch, trate = dt.get("channels") or ch or 2, dt.get("rate") or rate or 48000
            if codec == "mp3":
                container, ext = data, ".mp3"
                ns = dt.get("samples") or samples
            else:
                ns = min(
                    dt.get("samples") or (sound_header.xma_frame_count(data) * 512), 0xFFFFFFFF
                )
                container, ext = _xma2_riff(data, tch, trate, ns), ".xma"
            _emit_audio(
                container, ext, tname, out_dir, vgmstream_cli, log, codec.upper(), keep_container
            )
            out.append(
                dict(
                    index=k,
                    file=extract_paths.out_rel(
                        out_dir,
                        tname
                        + (
                            ".wav"
                            if vgmstream_cli
                            and extract_paths.safe(out_dir, tname + ".wav").exists()
                            else ext
                        ),
                    ),
                    label=lab,
                    channels=tch,
                    rate=trate,
                    samples=ns,
                    duration_s=round(ns / trate, 4) if ns else None,
                )
            )
        return out
    r = sound_header.console_media_parse(raw)
    if r is None:
        return False
    codec, data = r
    ch, rate, samples = meta if meta else (None, None, None)
    if desc and len(desc.get("tracks") or ()) == 1:
        # no stream facts by path (a loose tree): the one-track descriptor has them
        d0 = desc["tracks"][0]
        ch, rate = ch or d0.get("channels"), rate or d0.get("rate")
        samples = samples or d0.get("samples")
    if codec == "mp3":
        container, ext = data, ".mp3"
    else:
        nsamp = min(samples or (sound_header.xma_frame_count(data) * 512), 0xFFFFFFFF)
        container, ext = _xma2_riff(data, ch or 2, rate or 48000, nsamp), ".xma"
    ok = _emit_audio(
        container, ext, name, out_dir, vgmstream_cli, log, codec.upper(), keep_container
    )
    if not (ok and tracks):
        return ok
    ns = samples or (None if codec == "mp3" else nsamp)
    return [
        dict(
            index=0,
            file=extract_paths.out_rel(
                out_dir,
                name
                + (
                    ".wav"
                    if vgmstream_cli and extract_paths.safe(out_dir, name + ".wav").exists()
                    else ext
                ),
            ),
            label=None,
            channels=ch,
            rate=rate,
            samples=ns,
            duration_s=round(ns / rate, 4) if ns and rate else None,
        )
    ]


# ===========================================================================
# Driver
# ===========================================================================


def _clamp16(x):
    return -32768 if x < -32768 else (32767 if x > 32767 else x)


#: the standard MS-ADPCM coefficient pairs (c1, c2), predictor index 0..6
ADPCM_COEF_PAIRS = tuple(zip(_C1, _C2, strict=True))
_COEF_PAIRS = ADPCM_COEF_PAIRS  # the private spelling, kept for existing callers


def adpcm_predict(s1, s2, c1, c2):
    """(s1*c1 + s2*c2) / 256 truncated toward zero, as the Microsoft reference
    decoder, the Windows ACM codec and ffmpeg compute it (C integer division);
    a plain `>> 8` floors (differs by 1 on negative odd sums)."""
    t = s1 * c1 + s2 * c2
    return t >> 8 if t >= 0 else -((-t) >> 8)


_adpcm_predict = adpcm_predict  # the private spelling, kept for existing callers


def adpcm_mono(d, ba, coefs=None):
    """Mono MS-ADPCM blocks of `ba` bytes -> int16 samples.  `coefs`: the
    (c1, c2) pairs the predictor byte indexes (the header's table; default the
    standard seven).  A final partial block (7 header bytes and up) is decoded
    as far as it goes; a predictor index past the table ends the data."""
    C = coefs or ADPCM_COEF_PAIRS
    out = array.array("h")
    o = 0
    N = len(d)
    while o + 7 <= N:
        b = d[o : o + ba]
        o += ba
        pred = b[0]
        if pred >= len(C):
            break
        dl = struct.unpack_from("<h", b, 1)[0]
        s1 = struct.unpack_from("<h", b, 3)[0]
        s2 = struct.unpack_from("<h", b, 5)[0]
        c1, c2 = C[pred]
        out.append(s2)
        out.append(s1)
        for k in range(7, len(b)):
            for nib in ((b[k] >> 4) & 0xF, b[k] & 0xF):
                t = s1 * c1 + s2 * c2
                p = t >> 8 if t >= 0 else -((-t) >> 8)
                n = nib - 16 if nib >= 8 else nib
                v = _clamp16(p + n * dl)
                out.append(v)
                s2 = s1
                s1 = v
                dl = (_ADAPT[nib] * dl) >> 8
                if dl < 16:
                    dl = 16
    return out


_adpcm_mono = adpcm_mono  # the private spelling, kept for existing callers


def _adpcm_stereo(d, ba, coefs=None):
    """Stereo MS-ADPCM blocks (interleaved L/R output); see adpcm_mono.  A
    final partial block needs its 14 header bytes."""
    C = coefs or ADPCM_COEF_PAIRS
    out = array.array("h")
    o = 0
    N = len(d)
    while o + 14 <= N:
        b = d[o : o + ba]
        o += ba
        pL, pR = b[0], b[1]
        if pL >= len(C) or pR >= len(C):
            break
        dL = struct.unpack_from("<h", b, 2)[0]
        dR = struct.unpack_from("<h", b, 4)[0]
        s1L = struct.unpack_from("<h", b, 6)[0]
        s1R = struct.unpack_from("<h", b, 8)[0]
        s2L = struct.unpack_from("<h", b, 10)[0]
        s2R = struct.unpack_from("<h", b, 12)[0]
        c1L, c2L = C[pL]
        c1R, c2R = C[pR]
        out.append(s2L)
        out.append(s2R)
        out.append(s1L)
        out.append(s1R)
        for k in range(14, len(b)):
            hi = (b[k] >> 4) & 0xF
            lo = b[k] & 0xF
            t = s1L * c1L + s2L * c2L
            p = t >> 8 if t >= 0 else -((-t) >> 8)
            n = hi - 16 if hi >= 8 else hi
            v = _clamp16(p + n * dL)
            out.append(v)
            s2L = s1L
            s1L = v
            dL = (_ADAPT[hi] * dL) >> 8
            dL = 16 if dL < 16 else dL
            t = s1R * c1R + s2R * c2R
            p = t >> 8 if t >= 0 else -((-t) >> 8)
            n = lo - 16 if lo >= 8 else lo
            v = _clamp16(p + n * dR)
            out.append(v)
            s2R = s1R
            s1R = v
            dR = (_ADAPT[lo] * dR) >> 8
            dR = 16 if dR < 16 else dR
    return out


def decode_sfx(header):
    """SFX/voice 'sound' assets -> (pcm16_bytes, channels, rate). Codec tag at
    propbagEnd+10: 1 = 16-bit PCM, 2 = MS-ADPCM. The rate is the header's own
    (pe+14; the voice is created with it, 0x40271b): 44100 on every mono sound
    (resampled at bake time), the file's rate on stereo ones. pe+6 is the
    *source* rate, not playback."""
    pe = kapow_block.propbag_end(header)
    if pe + 30 > len(header):
        return None
    tag = struct.unpack_from("<H", header, pe + 10)[0]
    ch = struct.unpack_from("<H", header, pe + 2)[0]
    rate = struct.unpack_from("<I", header, pe + 14)[0]
    if not (8000 <= rate <= 96000):
        rate = 44100
    if not (1 <= ch <= 2):
        return None
    if tag == 1:
        nsamp, dsz = struct.unpack_from("<II", header, pe + 18)
        if dsz == nsamp * 2 * ch and pe + 26 + dsz <= len(header):
            data = header[pe + 26 : pe + 26 + dsz]  # loader 0x449e40: data follows its size
        else:  # not that layout: the pe+30 slice
            data = header[pe + 30 : pe + 30 + nsamp * 2 * ch]
        return (data, ch, rate) if len(data) >= 16 else None
    if tag == 2:
        lay = sound_header.adpcm_layout(header, pe, ch)
        if lay is not None:
            # the loader's layout (sfx_info): the header's own coefficient table, the
            # data_bytes after it (not the cue list behind them), trimmed to the
            # sample count (the last block is usually partly padding)
            nsamp, ba, coefs, adata = lay
            pcm = _adpcm_stereo(adata, ba, coefs) if ch == 2 else adpcm_mono(adata, ba, coefs)
            if nsamp and len(pcm) > nsamp * ch:
                del pcm[nsamp * ch :]
        else:  # not that layout: find the standard table and read to the end
            j = header.find(_COEFB, pe)
            if j < 0:
                return None
            ba = struct.unpack_from("<H", header, j - 4)[0]
            if not (16 <= ba <= 4096):
                return None
            adata = header[j + 32 :]
            pcm = _adpcm_stereo(adata, ba) if ch == 2 else adpcm_mono(adata, ba)
        return (pcm.tobytes(), ch, rate) if len(pcm) >= 16 else None
    return None


def _smpl_chunk(rate, frames):
    """A RIFF 'smpl' chunk with one forward loop over the whole sample (the
    engine loops the whole buffer: LoopLength = sample count, 0x40228c)."""
    body = struct.pack("<9I", 0, 0, int(round(1e9 / rate)), 60, 0, 0, 0, 1, 0)
    body += struct.pack("<6I", 0, 0, 0, max(frames - 1, 0), 0, 0)
    return b"smpl" + struct.pack("<I", len(body)) + body


def write_wav(pcm_bytes, ch, rate, path, loop=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:  # closed also when a write fails
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm_bytes)
    if loop:  # append the loop chunk and fix the RIFF size
        chunk = _smpl_chunk(rate, len(pcm_bytes) // (2 * ch))
        with open(str(path), "r+b") as fh:
            fh.seek(0, 2)
            fh.write(chunk)
            size = fh.tell() - 8
            fh.seek(4)
            fh.write(struct.pack("<I", size))


#: asset classes / name suffixes that some step of the toolkit decodes (extract itself,
#: binds / characters for animations, the nav and text exports).  Anything else that
#: `extract` meets is kept raw under extracted/ and counted in its summary ("raw only").
_DECODED_CLASSES = frozenset(("Texture", "Model", "ModelRes", "sound", "mediastream"))
_DECODED_SUFFIXES = (".animation", ".aipathdata", ".txt", ".wav", ".bmp", ".tga", ".model")


#: why kapow_json did not import (the asset loop names it on each asset it leaves raw)
_KAPOW_JSON_ERROR = []


@functools.cache
def _kapow_json():
    """Lazy import of kapow_json (fragment/pb/sequence/particle/... -> JSON); None
    (kept) when it does not import, the reason in _KAPOW_JSON_ERROR."""
    try:
        import kapow_json as _kj
    except ImportError as e:
        _KAPOW_JSON_ERROR[:] = ["%s: %s" % (type(e).__name__, e)]
        return None
    return _kj


#: stream-only block files (Part 1 Prison) kept in memory at once by `extract`
_STREAM_CACHE = 4
#: extract: a block whose inflated assets (headers + streams) take at most this many
#: bytes keeps them from the check pass for the asset pass; a larger one is parsed
#: and inflated again, so the memory stays bounded (0 = never keep)
BLOCK_CACHE_BYTES = 64 << 20


class ModelSpool:
    """The model jobs of an `extract` run: (header, stream, out_path, order,
    platform) tuples in the order they were added, the header and stream bytes
    kept in an anonymous temporary file in `folder` (removed when closed, or by
    the system if the process dies) instead of in memory.  Iterating reads one
    job back at a time."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self._f = None
        self._jobs = []

    def append(self, job):
        header, stream, out_path, order, platform = job
        if self._f is None:
            import tempfile

            self.folder.mkdir(parents=True, exist_ok=True)
            self._f = tempfile.TemporaryFile(
                prefix=".watchmen_models_", suffix=".spool", dir=str(self.folder)
            )
        f = self._f
        f.seek(0, os.SEEK_END)
        off = f.tell()
        hl = -1 if header is None else len(header)
        sl = -1 if stream is None else len(stream)
        if hl > 0:
            f.write(header)
        if sl > 0:
            f.write(stream)
        self._jobs.append((off, hl, sl, out_path, order, platform))

    def __len__(self):
        return len(self._jobs)

    def __iter__(self):
        for off, hl, sl, out_path, order, platform in self._jobs:
            self._f.seek(off)
            header = None if hl < 0 else self._f.read(hl)
            stream = None if sl < 0 else self._f.read(sl)
            yield header, stream, out_path, order, platform

    def close(self):
        if self._f is not None:
            self._f.close()
            self._f = None


def main(argv):
    """`extract`: see --help.  The run's name record (canonical_names.Run) is
    closed however the extraction ends."""
    try:
        return _extract_main(argv)
    finally:
        extract_paths.names_module().end()


def _extract_main(argv):
    ap = argparse.ArgumentParser(description="Extract Watchmen Part 2 (Kapow) assets from game.naz")
    ap.add_argument("naz", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("watchmen_out"))
    ap.add_argument(
        "--no-files", action="store_true", help="don't write the raw decrypted asset tree"
    )
    ap.add_argument("--no-textures", action="store_true")
    ap.add_argument("--no-models", action="store_true")
    ap.add_argument("--no-audio", action="store_true")
    ap.add_argument(
        "--no-extract-all",
        action="store_true",
        help="don't dump every raw asset (fragment/sequence/particle/etc.) to extracted/",
    )
    ap.add_argument(
        "--glb",
        action="store_true",
        help="also emit rigged+textured .glb (bind pose) for skinned character models; the skin rig's joint names/order come from each model's own embedded skeleton header, so no capture artifacts are needed (just numpy+Pillow). For engine-exact ANIMATED per-character glbs use `watchmen.py characters` (file-only binds + baked clips).",
    )
    ap.add_argument(
        "--no-vertex-attrs",
        action="store_true",
        help="with --glb: write the 1.3.0 .glb files (skinned models only; no NORMAL / TANGENT / COLOR_0, diffuse-only double-sided materials, file winding). Default: per-vertex attributes from the mesh buffers, sheet-driven materials (alpha blend / cut-out, two-sided, normal map) and a static .glb for rigid models too.",
    )
    ap.add_argument(
        "--rig",
        choices=("hierarchy", "flat"),
        default=None,
        help="with --glb: the skeleton of a rigged model's .glb. hierarchy (default) = one joint node per header node, named after it and parented as the header says, rest transform local to the parent and real inverse bind matrices (the bones stand where the model's skeleton puts them; the mesh node is a scene root); flat = the 1.4.0 file: joints without a transform, all children of 'Armature', identity inverse bind matrices. The mesh renders the same in both. Also $WATCHMEN_RIG.",
    )
    ap.add_argument(
        "--glb-texture-size",
        type=model_export._texture_size_arg,
        default=None,
        metavar="N",
        help="with --glb: shrink every texture embedded in a model .glb to at most N x N pixels (aspect kept). Default: the full size of the extracted PNG; 512 gives the 1.4.0 files.",
    )
    ap.add_argument(
        "--frame",
        choices=("true", "mirrored"),
        default=None,
        help="coordinate frame of the models (.obj / .glb) and the nav .glb: true (default) = right-handed, x = -engine x, the game as it looks; mirrored = the engine's left-handed numbers verbatim, a mirror image, byte-identical to what 1.3.0 wrote. Also $WATCHMEN_FRAME.",
    )
    ap.add_argument(
        "--exact-audio",
        action="store_true",
        help="(default now; kept for compatibility) sample-perfect Ogg granulepos",
    )
    ap.add_argument(
        "--vgmstream-cli",
        type=Path,
        default=None,
        metavar="PATH",
        help="path to a vgmstream-cli executable (any platform); used to decode console (X360 XMA2 / PS3 MP3) music streams to .wav. Without it, console music is written as .xma/.mp3 containers instead.",
    )
    ap.add_argument(
        "--keep-xma",
        action="store_true",
        help="X360 XMA is ALWAYS kept (default), and .wav is only written when --vgmstream-cli is given. This flag additionally keeps PS3 .mp3 containers alongside their .wav. Valid XMA2/MP3 a working decoder can re-convert (some short X360 XMA2 fail in current vgmstream/ffmpeg but the data is good -- see MASTER §14).",
    )
    ap.add_argument(
        "--flat-music",
        action="store_true",
        help="write each music stream as ONE file, the 1.3.0 output: a multi-track stream then holds all its tracks' chunks appended in turn (N times the real length) and no sidecar is written. Default: one file per track (<name>_track<k>...), plus <name>.json with the tracks, their cue points and the MusicSetup track states.",
    )
    ap.add_argument(
        "--music-track-labels",
        action="store_true",
        help="append the MusicStreamSlot track name to each per-track music file name (..._track1_Intro_loop...). Off by default: every shipped setup but one carries the same ten editor names, so they do not describe the stems; the names are in the sidecar either way.",
    )
    ap.add_argument(
        "--smpl-loops",
        action="store_true",
        help="add a RIFF 'smpl' chunk (one forward loop over the whole file) to the .wav of sounds whose header has the loop flag. Default: the flag is only listed in audio/sound_info.json.",
    )
    ap.add_argument(
        "--no-text",
        action="store_true",
        help="don't write text/ (every text asset in every language: raw, .json, .csv; see docs/TEXT_ASSETS.md). --language does not apply to it.",
    )
    ap.add_argument(
        "--no-nav",
        action="store_true",
        help="don't write nav/ (per level <Level>.nav.json + .nav.glb from the .hpd under files/ and the .aipathdata under extracted/; see docs/NAV_DATA.md)",
    )
    ap.add_argument(
        "--limit", type=int, default=None, metavar="N", help="stop after N block assets (debug)"
    )
    ap.add_argument(
        "--model-lod",
        type=model_header.model_lod_arg,
        default=0,
        metavar="N|all",
        help="which level of detail of each model to write: 0 (default) = full detail, N = that LOD (clamped per part), 'all' = every LOD in one file",
    )
    ap.add_argument(
        "--language",
        type=kapow_block.language_arg,
        default=0,
        metavar="0..5|NAME",
        help="language slot used for localized block assets (per-language header blobs and streams); default 0. A number 0..5 or a name / code: english|uk|en, french|fr, italian|it, german|de, spanish|es, danish|dk|da (the Danish slot of the shipped games is a copy of English)",
    )
    ap.add_argument(
        "--names",
        choices=("canonical", "stored"),
        default=None,
        help="spelling of output paths whose letter case differs between the archives: canonical (default) = the one spelling wlib/canonical_names.json lists for them, on every platform and both parts, one spelling per folder, and lower-case names for the files brought from beside a loose folder; the stored spelling goes into _canonical_names.json, the texture's sheet.json and the model's .model.json (stored_name). stored = every path as its archive stores it. Also $WATCHMEN_NAMES.",
    )
    ap.add_argument(
        "--json-floats",
        choices=("exact", "rounded"),
        default=None,
        help="how the decoded JSON writes float32 values: exact (default) = the shortest decimal that reads back as the same float32 (NaN / infinity as null); rounded = the 1.4.0 output (6 places, 5 for sequence keys). Also $WATCHMEN_JSON_FLOATS.",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="no progress log; the warning lines ('!' and 'WARNING:') still go to stderr",
    )
    a = ap.parse_args(argv)
    if not a.naz.exists():
        print("error: %s not found" % a.naz, file=sys.stderr)
        return 2
    model_export._RIG["on"] = bool(getattr(a, "glb", False))
    model_export._RIG["attrs"] = not bool(getattr(a, "no_vertex_attrs", False))
    model_export._RIG["tex_size"] = getattr(a, "glb_texture_size", None)
    if getattr(a, "rig", None):
        os.environ["WATCHMEN_RIG"] = a.rig  # the --glb rig and variant_glb.rig_mode() read it
    if getattr(a, "frame", None):
        os.environ["WATCHMEN_FRAME"] = a.frame  # frame.mode() reads it
    if getattr(a, "names", None):
        os.environ["WATCHMEN_NAMES"] = a.names  # canonical_names.mode() reads it
    if getattr(a, "json_floats", None):
        os.environ["WATCHMEN_JSON_FLOATS"] = a.json_floats  # f32json.mode() reads it
    if model_export._RIG["on"] and a.no_models:
        print("note: --glb requires model decoding; overriding --no-models", file=sys.stderr)
        a.no_models = False
    if model_export._RIG["on"] and not model_export._rig_load():
        print(
            "WARNING: --glb requested but rig_glb.py (or numpy) not importable (%s); "
            "skipping rig export" % model_export._RIG.get("error"),
            file=sys.stderr,
        )
        model_export._RIG["on"] = False
    log = extract_log.extract_logger(a.quiet)
    do_tex = not a.no_textures
    do_mdl = not a.no_models
    do_extract_all = not a.no_extract_all

    entries = list(naz_archive.naz_entries(a.naz, warn=lambda m: log("  ! " + m)))
    log("NAZ %s : %d entries -> %s" % (a.naz, len(entries), a.out))
    # the console of a big-endian source, named by its derived root (the path of
    # a loose tree, or the block paths inside the .naz); None on PC
    run_platform = model_mesh.console_platform_of(a.naz)
    for e in entries:
        if run_platform:
            break
        run_platform = model_mesh.console_platform_of(e.name)
    # the block plan: stem -> {"h": NazEntry, "s": NazEntry[, "standalone": True]}
    # -- archive entries only; each half is read again (and inflated) when its
    # block is processed and dropped after it, so the run never holds the archive
    blocks = {}
    console_audio = []  # (name, NazEntry) console mediastream_s, decoded post-blocks
    pc_audio = []  # (name, NazEntry) PC mediastream_s, split per track post-blocks
    media_meta = {}  # mediastream path (lower, no leading /) -> (ch, rate, samples)
    media_desc = {}  # same key -> (descriptor asset name, media_desc_from_header)
    music_frags = []  # (name, header, order) of fragments holding a MusicStreamSlot
    sound_info = {}  # sound asset name -> header facts (audio/sound_info.json)
    sfx_failed = []  # console sound assets no audio could be written for
    stats = dict(files=0, tex=0, mdl=0, aud=0)
    # --names: the canonical spelling of every output path, and what was respelled
    name_run = extract_paths.names_module().begin()
    # extracted/, textures/, models/ and audio/ spell every folder alike
    extract_paths.names_module().share_folders(a.out)
    names = extract_paths.OutputNames(
        log, name_run
    )  # one output per asset name (repeats, twins, variants)
    model_stored = {}  # model output path -> the archive's spelling of a respelled name
    text_writer = None
    if not a.no_text:
        try:
            import text_assets as _ta

            text_writer = _ta.TextWriter(a.out, log)
        except Exception as ex:
            log("note: text_assets not importable (%s) -> no text/" % ex)
    no_stream = {}  # Texture / ModelRes name -> (class, why) left without stream data
    misc = {}  # JSON kind (".font", ...) -> [assets, not fully decoded]
    raw_only = {}  # class / suffix of assets no decoder of this command reads -> count
    from_sets = {}  # stream-set file -> assets whose stream came from it

    # pass 1, archive order: files/, the standalone audio streams, and the plan.
    # An entry is read here only when its bytes are used here: for files/, or a
    # standalone audio stream.  With --no-files the block halves and the standalone
    # texture / model halves are planned from the directory alone (the block pass
    # reads them), so the archive is read once, not twice.
    for e in entries:
        low = e.name.lower()
        _audio = not a.no_audio and low.endswith(".mediastream_s")
        if a.no_files and not _audio:
            data = None  # planned from the directory; read when its block is processed
        else:
            try:
                data = naz_archive.naz_read(a.naz, e)
            except Exception as ex:
                log("  ! %s: %s" % (e.name, ex))
                continue
        if data is not None and not a.no_files:
            p = extract_paths.safe(a.out / "files", name_run.name(e.name))
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            stats["files"] += 1
        # pair block halves; defer processing until both are known
        if low.endswith(".block_h_z") or low.endswith(".block_s_z"):
            stem = e.name[: -len("_h_z")] if low.endswith("_h_z") else e.name[: -len("_s_z")]
            blocks.setdefault(stem, {})["h" if low.endswith("_h_z") else "s"] = e
            continue
        # standalone audio (PC = Vorbis packet container; console handled after
        # the block pass so channel/rate metadata is available)
        if not a.no_audio and low.endswith(".mediastream_s"):
            try:
                if not a.flat_music and _audio_packets(data):
                    pc_audio.append((e.name, e))  # needs the descriptors
                elif decode_audio(
                    data, extract_paths.safe(a.out / "audio", e.name + ".ogg"), True, log
                ):
                    stats["aud"] += 1
                else:
                    console_audio.append((e.name, e))
            except Exception as ex:
                log("      ! audio %s: %s" % (e.name, ex))
            continue
        # standalone texture / model (paired _h_z + _s_z handled via the block dict
        # path above only for *.block_*; helper textures use *.texture_h_z etc.)
        if low.endswith(".texture_h_z") or low.endswith(".modelres_h_z"):
            blocks.setdefault(e.name[: -len("_h_z")], {})["h"] = e
            blocks[e.name[: -len("_h_z")]]["standalone"] = True
            continue
        if low.endswith(".texture_s_z") or low.endswith(".modelres_s_z"):
            blocks.setdefault(e.name[: -len("_s_z")], {})["s"] = e
            blocks[e.name[: -len("_s_z")]]["standalone"] = True
            continue
    data = None  # pass 1 keeps no entry's bytes

    def _half(hs, k):
        """Bytes of half `k` ("h" / "s") of a planned block, read now: the
        archive entry, inflated for a standalone file; None without that half."""
        ent = hs.get(k)
        if ent is None:
            return None
        raw = naz_archive.naz_read(a.naz, ent)
        return kapow_block.inflate_standalone(raw) if hs.get("standalone") else raw

    def _entry_bytes(ent):
        """An audio entry of pass 1, read again for its post-block pass."""
        return naz_archive.naz_read(a.naz, ent)

    # process collected blocks + standalone pairs
    # stream-only `.block_s_z` files (no header half): the stream sets of another
    # block's header name them (Part 1 Prison: four rooms).  Read when a set
    # first names them; the last few stay cached.
    _stream_only = {k + "_s_z": v for k, v in blocks.items() if "h" not in v and "s" in v}
    _stream_used = {}
    _stream_cache = {}  # stream-only file -> bytes, at most _STREAM_CACHE of them

    def _stream_file(path, _find=kapow_block.stream_file_lookup({k: k for k in _stream_only})):  # noqa: B008
        key = _find(path)
        if key is None:
            return None
        blob = _stream_cache.pop(key, None)
        if blob is None:
            try:
                blob = _half(_stream_only[key], "s")
            except Exception as ex:
                log("  ! %s: %s" % (key, ex))
                return None
        _stream_cache[key] = blob  # most recently used last
        while len(_stream_cache) > _STREAM_CACHE:
            _stream_cache.pop(next(iter(_stream_cache)))
        _stream_used[path] = _stream_used.get(path, 0) + 1
        return blob

    # (header, stream, out_path, order, platform) -- deferred until all textures
    # are dumped; header and stream wait in a spool file under the output folder
    model_jobs = ModelSpool(a.out)
    extract_log.push(log)
    try:
        return _extract_blocks_and_rest(
            a,
            log,
            blocks,
            _half,
            _entry_bytes,
            _stream_only,
            _stream_used,
            _stream_file,
            model_jobs,
            run_platform,
            console_audio,
            pc_audio,
            media_meta,
            media_desc,
            music_frags,
            sound_info,
            sfx_failed,
            stats,
            name_run,
            names,
            model_stored,
            text_writer,
            no_stream,
            misc,
            raw_only,
            from_sets,
            do_tex,
            do_mdl,
            do_extract_all,
        )
    finally:
        extract_log.pop()
        model_jobs.close()


def _extract_blocks_and_rest(
    a,
    log,
    blocks,
    _half,
    _entry_bytes,
    _stream_only,
    _stream_used,
    _stream_file,
    model_jobs,
    run_platform,
    console_audio,
    pc_audio,
    media_meta,
    media_desc,
    music_frags,
    sound_info,
    sfx_failed,
    stats,
    name_run,
    names,
    model_stored,
    text_writer,
    no_stream,
    misc,
    raw_only,
    from_sets,
    do_tex,
    do_mdl,
    do_extract_all,
):
    """The block pass and everything after it (`extract`, see _extract_main).  Returns
    1 when a block could not be read or parsed (its assets are missing), else 0."""
    n_assets = 0
    failed_blocks = []  # blocks whose halves did not read or whose parse failed
    tex_repeats = mdl_repeats = 0
    # blocks in a fixed order that does not depend on the letter case an archive
    # stores their paths in (OutputNames: the first copy names the output)
    for stem, hs in sorted(blocks.items(), key=lambda kv: (kv[0].lower(), kv[0])):
        if "h" not in hs:
            continue
        if hs.get("standalone"):
            low = stem.lower()
            if hs.get("s") is None:
                continue
            try:
                header, stream = _half(hs, "h"), _half(hs, "s")
            except Exception as ex:
                log("  ! %s: %s" % (stem, ex))
                failed_blocks.append(stem)
                continue
            # same registry as the block assets; the folder names a differing copy
            name, placed = extract_paths.standalone_output_name(names, stem, header, stream)
            if placed == "repeat":
                continue
            if do_tex and ".texture" in low:
                try:
                    if texture_carve.carve_texture(
                        stream, header, extract_paths.safe(a.out / "textures", name), log
                    ):
                        stats["tex"] += 1
                        texture_sheet_mod.mark_stored_name(
                            extract_paths.safe(a.out / "textures", name), name_run.stored_of(name)
                        )
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and ".modelres" in low:
                model_jobs.append(
                    (
                        header,
                        stream,
                        extract_paths.safe(a.out / "models", name + ".obj"),
                        None,
                        model_mesh.console_platform_of(stem) or run_platform,
                    )
                )
            continue
        # real block pair
        if a.limit is not None and n_assets >= a.limit:
            break  # --limit N: stop after N block assets
        log("\nBLOCK %s" % stem)
        try:
            h_data, s_data = _half(hs, "h"), _half(hs, "s")
        except Exception as ex:
            log("  ! %s: %s" % (stem, ex))
            failed_blocks.append(stem)
            continue
        if text_writer is not None:  # text assets, all six language slots
            try:
                text_writer.add_block(h_data, stem)
            except Exception as ex:
                log("  ! text assets: %s" % ex)
        _args = (h_data, s_data, a.language) if a.language else (h_data, s_data)
        try:
            # check pass: the whole block parses and inflates (what does not inflate is
            # reported here, before any asset of the block is written).  The
            # assets are kept for the asset pass while they fit in BLOCK_CACHE_BYTES;
            # a larger block is parsed again below -- holding a whole level's assets
            # is what the memory would go on
            _rep = lambda m: log("  ! " + m)
            _kept, _size, _cap = [], 0, BLOCK_CACHE_BYTES
            for _item in kapow_block.extract_block(*_args, report=_rep, stream_files=_stream_file):
                if _kept is not None:
                    _size += len(_item[1] or b"") + len(_item[2] or b"")
                    if _size <= _cap:
                        _kept.append(_item)
                    else:
                        _kept = None  # too big: the asset pass parses it again
            _item = None
        except Exception as ex:
            log("  ! parse failed: %s" % ex)
            failed_blocks.append(stem)
            continue
        # the assets one at a time (the same parse; its reports were logged above)
        if _kept is not None:
            it = iter(_kept)
        else:
            it = kapow_block.extract_block(*_args, report=None, stream_files=_stream_file)
        _kept = None
        h_data = s_data = _args = None  # the generator holds the block's bytes until done
        for e, header, stream in it:
            if a.limit is not None and n_assets >= a.limit:
                break
            n_assets += 1
            # script classes ("ModelEffects(ModelRes)", "TextureEffects(Texture)")
            # are read by their base class loader -> dispatch on the base name
            cls = kapow_block.asset_base_class(
                kapow_block.asset_class(header, kapow_block.BLOCK_ORDER)
            )
            # the name this copy is written under, and whether an earlier block
            # already wrote the same bytes (OutputNames: "repeat")
            name, placed = names.place(e.name, stem, header, stream)
            low = name.lower()
            # class-name compare is case-insensitive: the typename is spelled both
            # "mediastream" and "MediaStream"; a case-sensitive miss here would leave
            # media_meta empty (console XMA then wrapped with default 2ch/48000
            # instead of the real channel/rate/sample values).
            if not a.no_audio and cls.lower() == "mediastream":
                try:
                    mm = sound_header.media_meta_from_header(header, kapow_block.BLOCK_ORDER)
                    if mm:
                        media_meta[mm[0].lower().lstrip("/")] = mm[1:]
                    md = sound_header.media_desc_from_header(header, kapow_block.BLOCK_ORDER)
                    if md:
                        media_desc[md["stream"].lower().lstrip("/")] = (name, md)
                except (struct.error, ValueError, IndexError, KeyError) as ex:
                    log(
                        "      WARNING: music %s: stream description not read, channels and "
                        "rate left to the stream (%s: %s)" % (name, type(ex).__name__, ex)
                    )
            if not a.no_audio and low.endswith(".fragment") and b"MusicStreamSlot" in header:
                music_frags.append((name, header, kapow_block.BLOCK_ORDER))
            # dump EVERY asset raw (header + optional stream) to extracted/ for offline
            # analysis; a later copy with the same header and stream wrote the same files
            # under the same name already (raw, JSON, the files beside it), so it is skipped
            if do_extract_all and not (placed == "repeat" and names.same_bytes):
                _ep = extract_paths.safe(a.out / "extracted", name)
                _ep.parent.mkdir(parents=True, exist_ok=True)
                _ep.write_bytes(header if header else b"")
                if stream:
                    (_ep.parent / (_ep.name + ".stream")).write_bytes(stream)
                # human-readable JSON for property-bag / sequence / fragment assets
                # (.fragment.json, .pb.json, .sequence.json, .particle.json, ...)
                if header and low.endswith(
                    (
                        ".fragment",
                        ".sequence",
                        ".pb",
                        ".particle",
                        ".grass",
                        ".detailmesh",
                        ".terrain",
                        ".scene",
                        ".font",
                        ".terraincoloringasset",
                    )
                ):
                    _kind = "." + low.rsplit(".", 1)[-1]
                    # counted once per output name (a later copy without the stream the
                    # first one had is written again but is the same asset)
                    _one = 1 if placed != "repeat" else 0
                    _cnt = misc.setdefault(_kind, [0, 0])
                    _cnt[0] += _one
                    try:
                        kj = _kapow_json()
                        d = None
                        if kj:
                            _lines = []
                            if low.endswith(kj.EXPORT_EXTS):
                                # font / scene / terrain / terrain colouring / detail mesh:
                                # JSON plus the atlas, maps and terrain GLB beside the asset;
                                # what is not decoded comes back as log lines
                                d, _lines = kj.export(
                                    name,
                                    header,
                                    stream,
                                    str(_ep),
                                    kapow_block.BLOCK_ORDER,
                                    glb=bool(a.glb),
                                )
                            else:
                                d = kj.to_json(low, header, order=kapow_block.BLOCK_ORDER)
                            if d and low.endswith(".fragment"):
                                # never silent: a fragment not decoded exactly, or
                                # with values typed by guess, is named in the log
                                import kapow_fragment as _kfr

                                _lines = _kfr.notes(name, d)
                            _why = kj.undecoded(d)
                            if _why:
                                # one line per asset that is not decoded completely; the
                                # same fact is a marker in its JSON (kapow_json.undecoded)
                                _cnt[1] += _one
                                if not any(_l.startswith("WARNING:") for _l in _lines):
                                    _lines = list(_lines) + [
                                        "WARNING: %s %s: not decoded completely: %s"
                                        % (_kind[1:], name, _why)
                                    ]
                            for _ln in _lines:
                                log("      " + _ln)
                            if d:
                                import f32json as _f32j

                                with open(
                                    _ep.parent / (_ep.name + ".json"),
                                    "w",
                                    encoding="utf-8",
                                    newline="\n",
                                ) as _f:
                                    # exact mode: a NaN or an infinity is null
                                    _f.write(_f32j.dumps(d, indent=1))
                        else:
                            _cnt[1] += _one
                            log(
                                "      WARNING: %s %s: not decoded: kapow_json not importable (%s)"
                                % (_kind[1:], name, "; ".join(_KAPOW_JSON_ERROR))
                            )
                    except Exception as ex:
                        _cnt[1] += _one
                        log("      WARNING: %s %s: not decoded: %s" % (_kind[1:], name, ex))
                elif header and not (
                    cls in _DECODED_CLASSES
                    or cls.lower() in _DECODED_CLASSES
                    or low.endswith(_DECODED_SUFFIXES)
                ):
                    # a kind no step of the toolkit reads: kept raw, and counted
                    _k = cls if cls and cls != "unknown" else "." + low.rsplit(".", 1)[-1]
                    raw_only[_k] = raw_only.get(_k, 0) + (placed != "repeat")
            # SFX / voice 'sound' assets keep their PCM INLINE in the header
            # (stream is None) -> handle these before the stream-None skip below.
            if not a.no_audio and cls == "sound":
                try:
                    if kapow_block.BLOCK_ORDER == "<":
                        r = decode_sfx(header)
                        if r:
                            wn = name if name.lower().endswith(".wav") else name + ".wav"
                            si = sound_header.sfx_info(header) or {}
                            loop = bool(si.get("looping"))
                            write_wav(
                                r[0],
                                r[1],
                                r[2],
                                extract_paths.safe(a.out / "audio", wn),
                                a.smpl_loops and loop,
                            )
                            stats["aud"] += 1
                            if si:
                                si.pop("_pe", None)
                                si["file"] = extract_paths.out_rel(a.out / "audio", wn)
                                sound_info[name.replace("\\", "/").lstrip("/")] = si
                        else:
                            sfx_failed.append(name)
                            log(
                                "      WARNING: sfx %s: sound header not decoded; no audio written"
                                % name
                            )
                    else:
                        si = decode_sfx_console(
                            header,
                            kapow_block.BLOCK_ORDER,
                            name,
                            a.out / "audio",
                            a.vgmstream_cli,
                            log,
                            a.keep_xma,
                        )
                        if si:
                            stats["aud"] += 1
                            if isinstance(si, dict):
                                sound_info[name.replace("\\", "/").lstrip("/")] = si
                        else:
                            sfx_failed.append(name)
                            log(
                                "      WARNING: sfx %s: sound header not decoded; no audio written"
                                % name
                            )
                except Exception as ex:
                    log("      ! sfx %s: %s" % (name, ex))
                continue
            if cls in ("Texture", "Model", "ModelRes"):
                # a texture / model without stream data gets no PNG / OBJ: say so,
                # once per output name, unless a later block's copy brings the
                # stream (OutputNames: "fill")
                if stream:
                    no_stream.pop(name, None)
                elif stream is not None and do_mdl and cls != "Texture":
                    pass  # an empty stream record: decode_model names it with the reason
                elif placed != "repeat":
                    if stream is None:
                        why = "header only" + ("" if e.stream_note else ", not in any stream set")
                    else:
                        why = "its stream record is empty (0 bytes)"
                    no_stream[name] = (cls, why)
            if stream is None:
                continue
            if e.stream_file:
                from_sets[e.stream_file] = from_sets.get(e.stream_file, 0) + 1
            if do_tex and cls == "Texture":
                if placed == "repeat":  # same bytes as an earlier block's copy
                    tex_repeats += 1
                    continue
                try:
                    if texture_carve.carve_texture(
                        stream, header, extract_paths.safe(a.out / "textures", name), log
                    ):
                        stats["tex"] += 1
                        texture_sheet_mod.mark_stored_name(
                            extract_paths.safe(a.out / "textures", name), name_run.stored_of(name)
                        )
                except Exception as ex:
                    log("      ! texture %s: %s" % (name, ex))
            elif do_mdl and (cls in ("Model", "ModelRes") or ".modelres" in low):
                if placed == "repeat":
                    mdl_repeats += 1
                    continue
                if name_run.stored_of(name):
                    model_stored[extract_paths.safe(a.out / "models", name + ".obj")] = (
                        name_run.stored_of(name)
                    )
                model_jobs.append(
                    (
                        header,
                        stream,
                        extract_paths.safe(a.out / "models", name + ".obj"),
                        kapow_block.BLOCK_ORDER,
                        model_mesh.console_platform_of(stem) or run_platform,
                    )
                )
            elif not a.no_audio and (cls.lower() == "mediastream" or ".mediastream" in low):
                try:
                    if decode_audio(
                        stream, extract_paths.safe(a.out / "audio", name + ".ogg"), True, log
                    ):
                        stats["aud"] += 1
                except Exception as ex:
                    log("      ! audio %s: %s" % (name, ex))

    if from_sets or _stream_only:
        log("\nSTREAM SETS: %d stream-only block file(s)" % len(_stream_only))
        for sfile, cnt in sorted(from_sets.items()):
            log("  %s: %d asset stream(s) read" % (sfile, cnt))
        _find = kapow_block.stream_file_lookup({k: k for k in _stream_only})
        _hit = {_find(sfile) for sfile in _stream_used}
        for k in sorted(_stream_only):
            if k not in _hit:
                log("  WARNING: %s: no stream set of any block names this file; not read" % k)
    if no_stream:
        log("\nNO STREAM: %d texture / model asset(s) without stream data" % len(no_stream))
        for _nm, (_cls, _why) in sorted(no_stream.items()):
            log("  note: no stream: %s (%s): %s" % (_nm, _cls, _why))

    # music: block pass done -> descriptors (tracks, cue points) and the
    # MusicSetup fragments (track names, track states) are known
    setups = []
    for fname, fhead, forder in music_frags:
        try:
            import sound_meta as _sm

            setups += _sm.music_setups_from_bytes(fhead, fname, forder)
        except Exception as ex:
            log("      ! music setup %s: %s" % (fname, ex))

    def _desc_of(name):
        """(descriptor asset name, descriptor) of a stream entry: by its path,
        else by the one descriptor whose stream path ends with it (a loose tree
        rooted below `derived_<platform>/`)."""
        key = name.lower().lstrip("/")
        if key in media_desc:
            return media_desc[key]
        hits = [v for k, v in media_desc.items() if k.endswith("/" + key)]
        return hits[0] if len(hits) == 1 else (None, None)

    def _music_sidecar(name, tracks, layout):
        dname, desc = _desc_of(name)
        mine = [
            s
            for s in setups
            if dname
            and (s.get("stream_asset") or "").replace("\\", "/").lstrip("/").lower()
            == dname.replace("\\", "/").lstrip("/").lower()
        ]
        slot = mine[0]["track_names"] if mine else []
        for k, t in enumerate(tracks):
            dt = desc["tracks"][k] if desc and k < len(desc["tracks"]) else {}
            t["slot_track_name"] = slot[k] if k < len(slot) else None
            t["source"] = dt.get("source")
            if dt.get("samples"):
                t["descriptor_samples"] = dt["samples"]
            rate = t.get("rate") or dt.get("rate")
            t["cue_points"] = [
                dict(c, time_s=round(c["sample"] / float(rate), 4) if rate else None)
                for c in dt.get("cue_points", [])
            ]
        doc = {
            "format": "watchmen-music-stream/1",
            "stream": name.replace("\\", "/").lstrip("/"),
            "descriptor": dname,
            "layout": layout,
            "tracks": tracks,
            "setups": mine,
        }
        import json as _json

        jp = extract_paths.safe(a.out / "audio", name + ".json")
        jp.parent.mkdir(parents=True, exist_ok=True)
        with open(jp, "w", encoding="utf-8", newline="\n") as _f:
            _f.write(_json.dumps(doc, indent=1))

    def _slot_labels(name):
        if not a.music_track_labels:
            return None
        dname = _desc_of(name)[0]
        for s in setups:
            if (
                dname
                and (s.get("stream_asset") or "").lstrip("/").lower() == dname.lstrip("/").lower()
            ):
                return s["track_names"]
        return None

    for name, ent in pc_audio:
        try:
            raw = _entry_bytes(ent)
            tr = decode_audio_tracks(raw, a.out / "audio", name, True, log, _slot_labels(name))
            if tr:
                stats["aud"] += len(tr)
                _music_sidecar(name, tr, "one file per track")
            elif decode_audio(raw, extract_paths.safe(a.out / "audio", name + ".ogg"), True, log):
                stats["aud"] += 1
                log("      ! %s does not split into tracks: written as one file" % name)
            else:
                console_audio.append((name, ent))
        except Exception as ex:
            log("      ! audio %s: %s" % (name, ex))
        raw = None

    if sound_info or sfx_failed:
        import json as _json

        doc = {"format": "watchmen-sound-info/1", "sounds": dict(sorted(sound_info.items()))}
        if sfx_failed:  # marker: sound assets whose header no reader took
            doc["not_decoded"] = sorted(n.replace("\\", "/").lstrip("/") for n in sfx_failed)
        (a.out / "audio").mkdir(parents=True, exist_ok=True)
        with open(
            extract_paths.safe(a.out / "audio", "sound_info.json"),
            "w",
            encoding="utf-8",
            newline="\n",
        ) as _f:
            _f.write(_json.dumps(doc, indent=1))
        src = {}
        for si in sound_info.values():
            if "duration_source" in si:  # console records only
                src[si["duration_source"]] = src.get(si["duration_source"], 0) + 1
        if src or sfx_failed:
            kept = sum(1 for si in sound_info.values() if not si["file"].lower().endswith(".wav"))
            log(
                "\nSOUND INFO: %d sounds -> audio/sound_info.json (duration from: %s; "
                "%d not decoded)"
                % (
                    len(sound_info),
                    ", ".join("%s %d" % kv for kv in sorted(src.items())) or "the PC header",
                    len(sfx_failed),
                )
            )
            if src:
                log(
                    "CONSOLE SFX: %d of %d sounds written as .mp3 / .xma containers (vgmstream: %s)"
                    % (kept, len(sound_info), a.vgmstream_cli or "not set")
                )

    # console music: per-stream channel/rate metadata known
    if console_audio:
        log(
            "\nCONSOLE AUDIO: %d streams (vgmstream: %s)"
            % (len(console_audio), a.vgmstream_cli or "not set")
        )
        for name, ent in console_audio:
            try:
                raw = _entry_bytes(ent)
                meta = media_meta.get(name.lower().lstrip("/"))
                r = decode_console_audio(
                    name,
                    raw,
                    a.out / "audio",
                    meta,
                    a.vgmstream_cli,
                    log,
                    a.keep_xma,
                    tracks=not a.flat_music,
                    labels=_slot_labels(name),
                    desc=_desc_of(name)[1],
                )
                if isinstance(r, list):
                    stats["aud"] += len(r)
                    _music_sidecar(name, r, "one file per track")
                elif r:
                    stats["aud"] += 1
                else:
                    log("      ! unrecognized mediastream %s" % name)
            except Exception as ex:
                log("      ! console audio %s: %s" % (name, ex))
            raw = None

    # all blocks parsed -> textures are now on disk; decode models last with the
    # full texture index so per-submesh materials resolve correctly.
    tex_index = obj_mtl.build_texture_index(a.out / "textures")
    # SKELETON REFERENCE DUMP: decode the base *_Skeleton.model rest poses to
    # OUT/skeletons/*.json (file-decoded; see docs/ENGINE_CONSTANTS.md).  This is
    # reference output only -- the glb rig takes its joint names/order from each
    # model's OWN embedded palette in decode_model (skeleton assets have a 0-byte
    # stream, so they never enter model_jobs; collect them straight from the naz).
    if model_export._RIG["on"]:
        try:
            import extract_skeletons as _es
            import json as _json

            _sk = _es.collect(str(a.naz))
            skdir = a.out / "skeletons"
            skdir.mkdir(parents=True, exist_ok=True)
            for _fam, _s in _sk.items():
                with open(
                    skdir / ("skeleton_%s.json" % _fam), "w", encoding="utf-8", newline="\n"
                ) as _f:
                    _json.dump(_s, _f, indent=1)
            log("\nSKELETONS: %d base skeletons decoded from file -> %s" % (len(_sk), skdir))
            for _fam, _s in sorted(_sk.items()):
                log("  skeleton_%-12s %3d bones" % (_fam, _s["bone_count"]))
            import skeleton_records as _skr

            _note = _skr.scan_note()
            if _note:
                log("  note: " + _note)
        except Exception as _ex:
            log("  ! skeleton pass: %s" % _ex)
    model_lod = a.model_lod
    log(
        "\nMODELS: %d  (textures indexed: %d)%s"
        % (
            len(model_jobs),
            len(tex_index),
            (
                "  [%d entries: %d identical copies in other blocks not decoded again]"
                % (len(model_jobs) + mdl_repeats, mdl_repeats)
                if mdl_repeats
                else ""
            ),
        )
    )
    mdl_none = []  # models that gave no output: decode_model logged the reason
    glb_yes = 0
    glb_none = {}  # reason -> [model names]: decoded models that got no .glb (--glb)
    col_none = []  # models whose vertex colours are not decoded
    mdl_partial = []  # models decoded incompletely (fewer submeshes than the header lists)
    _platform_before = model_mesh.CONSOLE_PLATFORM
    for header, stream, out_path, mo, mplat in model_jobs:
        try:
            _st = model_export.MODEL_STATUS
            _st.clear()
            model_mesh.set_console_platform(mplat)
            # stored_name only for a respelled model (--names canonical)
            _kw = {"stored_name": model_stored[out_path]} if out_path in model_stored else {}
            if model_export.decode_model(
                header, stream, out_path, tex_index, log, order=mo, lod=model_lod, **_kw
            ):
                stats["mdl"] += 1
                _mn = out_path.name[: -len(".obj")]
                if _st.get("glb"):
                    glb_yes += 1
                elif _st.get("glb") is False:
                    glb_none.setdefault(_st.get("glb_reason") or "not written", []).append(_mn)
                if _st.get("color_not_decoded"):
                    col_none.append(_mn)
                if _st.get("partial"):
                    mdl_partial.append(_mn)
            else:
                mdl_none.append(out_path.name[: -len(".obj")])
        except Exception as ex:
            mdl_none.append(out_path.name[: -len(".obj")])
            log("      ! model %s: %s" % (out_path.name, ex))
    model_mesh.set_console_platform(_platform_before)

    if text_writer is not None:
        try:
            text_writer.write()
        except Exception as ex:
            log("  ! text assets: %s" % ex)

    if not a.no_nav:  # navigation data of the levels this run (or an earlier one) wrote
        try:
            import nav_data as _nav

            trees = _nav.extract_trees(a.out)
            if a.naz.is_dir():
                # a loose-folder source (Part 1 PC / Xbox Live) keeps the .hpd path
                # data and the .bik movies beside the folder it was given: bring
                # them to files/data/, where the archive sets have them (--no-files:
                # the path data is read in place, the movies are not fetched)
                if a.no_files:
                    trees = trees + [
                        p
                        for _n, p in _nav.loose_source_files(a.naz)
                        if not p.lower().endswith(".bik")
                    ]
                else:
                    stats["files"] += len(_nav.stage_loose_source(a.naz, a.out, log, name_run))
                    trees = _nav.extract_trees(a.out)
            res = _nav.export(trees, str(a.out / "nav"))
            if res:
                bad = sum(1 for r in res if "error" in r)
                log(
                    "NAV: %d level(s) -> %s%s"
                    % (len(res) - bad, a.out / "nav", ", %d failed" % bad if bad else "")
                )
                nohpd = [r["level"] for r in res if "error" not in r and not r.get("hpd")]
                if nohpd:
                    log(
                        "  WARNING: nav: no path data (.hpd) found for %s: definition only, no .nav.glb"
                        % ", ".join(nohpd)
                    )
        except Exception as ex:
            log("  ! navigation data: %s" % ex)

    log("\nDONE  (%d assets across %d blocks)" % (n_assets, len(blocks)))
    log("  files       : %d" % stats["files"])
    log(
        "  textures    : %d%s"
        % (
            stats["tex"],
            (
                "  (+ %d identical copies in other blocks, not written again)" % tex_repeats
                if tex_repeats
                else ""
            ),
        )
    )
    log(
        "  models      : %d%s"
        % (
            stats["mdl"],
            (
                "  of %d  (%d without output, reason logged above: %s)"
                % (len(model_jobs), len(mdl_none), ", ".join(sorted(mdl_none)))
                if mdl_none
                else ""
            ),
        )
    )
    if model_export._RIG["on"]:
        _ng = sum(len(v) for v in glb_none.values())
        log(
            "  model GLBs  : %d%s"
            % (
                glb_yes,
                (
                    '  (%d decoded model(s) WITHOUT a .glb; "glb" in their .model.json'
                    " says why)" % _ng
                    if _ng
                    else ""
                ),
            )
        )
        for _why, _nms in sorted(glb_none.items()):
            log(
                "  note: no GLB for %d model(s): %s: %s"
                % (
                    len(_nms),
                    _why,
                    ", ".join(sorted(_nms)[:12]) + (" ..." if len(_nms) > 12 else ""),
                )
            )
    if mdl_partial:
        log(
            '  WARNING: %d model(s) decoded incompletely ("submeshes" under not_decoded in'
            " their .model.json): %s" % (len(mdl_partial), ", ".join(sorted(mdl_partial)))
        )
    if col_none:
        log(
            "  note: vertex colours not decoded for %d model(s) (not_decoded: COLOR_0 in"
            " their .model.json; the console is not known and their data does not show"
            " the colour byte order: set WATCHMEN_CONSOLE=x360 or ps3)" % len(col_none)
        )
    if misc:
        _bad = ["%s %d of %d" % (k, v[1], v[0]) for k, v in sorted(misc.items()) if v[1]]
        log("  misc JSON   : %s" % ", ".join("%s %d" % (k, v[0]) for k, v in sorted(misc.items())))
        log(
            "  not decoded completely: %s"
            % (", ".join(_bad) + "  (a WARNING: line above names each)" if _bad else "none")
        )
    if raw_only:
        log(
            "  WARNING: raw only (no decoder for this kind; kept under extracted/): %s"
            % ", ".join("%s %d" % kv for kv in sorted(raw_only.items()))
        )
    if names.case_twins:
        log(
            "  names       : %d stored under a second spelling that differs only in letter case;"
            " written once, under the spelling of the first block in case-insensitive block"
            " order: %s"
            % (len(names.case_twins), ", ".join("%s (= %s)" % t for t in names.case_twins))
        )
    if names.variants:
        log(
            "  names       : %d stored with different content in different blocks; each kept"
            " under its own name: %s"
            % (len(names.variants), ", ".join(v[1] for v in names.variants))
        )
    try:
        name_run.write(a.out)
    except OSError as ex:
        log("  ! %s: %s" % (extract_paths.names_module().RUN_FILE, ex))
    if name_run.renamed:
        log(
            "  names       : %d written under their canonical spelling (--names stored keeps"
            " the archive's); canonical -> stored in %s"
            % (len(name_run.renamed), extract_paths.names_module().RUN_FILE)
        )
    log("  audio       : %d" % stats["aud"])
    log("  output      : %s" % a.out)
    if failed_blocks:
        log(
            "  ! blocks    : %d not extracted (reason logged above; exit code 1): %s"
            % (len(failed_blocks), ", ".join(failed_blocks))
        )
        return 1
    return 0


# ===========================================================================
# Names that live in other modules
# ===========================================================================
#: name here -> (home module, name there).  Reading `watchmen_extract.<name>`
#: gives the home's object; setting or deleting it (monkeypatch included) sets or
#: deletes it in the home, so every caller that looks it up there sees the change.
#: Code here calls such a name as `home.name`.
_HOMES = {
    "_RUN_LOG": ("extract_log", "_RUN_LOG"),
    "_run_warning": ("extract_log", "warn"),
    "is_warning_line": ("extract_log", "is_warning_line"),
    "extract_logger": ("extract_log", "extract_logger"),
    "ByteReader": ("byte_reader", "ByteReader"),
    "_Rd": ("byte_reader", "ByteReader"),
    "OutputNames": ("extract_paths", "OutputNames"),
    "standalone_output_name": ("extract_paths", "standalone_output_name"),
    "_WIN_DEVICES": ("extract_paths", "_WIN_DEVICES"),
    "_not_a_device": ("extract_paths", "_not_a_device"),
    "_no_trailing_dots": ("extract_paths", "_no_trailing_dots"),
    "_safe_path": ("extract_paths", "_safe_path"),
    "safe": ("extract_paths", "safe"),
    "out_rel": ("extract_paths", "out_rel"),
    "_names_mod": ("extract_paths", "names_module"),
    "NAZ_HEAD": ("naz_archive", "NAZ_HEAD"),
    "NAZ_LIST": ("naz_archive", "NAZ_LIST"),
    "_EOCD_FMT": ("naz_archive", "_EOCD_FMT"),
    "_EOCD": ("naz_archive", "_EOCD"),
    "_CD_FMT": ("naz_archive", "_CD_FMT"),
    "_CD": ("naz_archive", "_CD"),
    "_LFH": ("naz_archive", "_LFH"),
    "_rotl8": ("naz_archive", "_rotl8"),
    "_decrypt_name": ("naz_archive", "_decrypt_name"),
    "naz_key": ("naz_archive", "naz_key"),
    "NazEntry": ("naz_archive", "NazEntry"),
    "LOOSE_SUFFIXES": ("naz_archive", "LOOSE_SUFFIXES"),
    "loose_entries": ("naz_archive", "loose_entries"),
    "naz_entries": ("naz_archive", "naz_entries"),
    "MAX_INFLATE": ("naz_archive", "MAX_INFLATE"),
    "max_inflate": ("naz_archive", "max_inflate"),
    "inflate": ("naz_archive", "inflate"),
    "naz_read": ("naz_archive", "naz_read"),
    "_naz_inflate": ("naz_archive", "_naz_inflate"),
    "block_plan": ("naz_archive", "block_plan"),
    "iter_blocks": ("naz_archive", "iter_blocks"),
    "BLOCK_HEADER_SIZE": ("kapow_block", "BLOCK_HEADER_SIZE"),
    "BLOCK_TABLES_START": ("kapow_block", "BLOCK_TABLES_START"),
    "TABLES_SIZE_OFFSET": ("kapow_block", "TABLES_SIZE_OFFSET"),
    "NUM_TABLES_OFFSET": ("kapow_block", "NUM_TABLES_OFFSET"),
    "BLOCK_LANGUAGES": ("kapow_block", "BLOCK_LANGUAGES"),
    "STREAM_PAIRS": ("kapow_block", "STREAM_PAIRS"),
    "SIZE_VARIANTS": ("kapow_block", "SIZE_VARIANTS"),
    "BLOCK_LANGUAGE_NAMES": ("kapow_block", "BLOCK_LANGUAGE_NAMES"),
    "_FINGERPRINT_KEY": ("kapow_block", "_FINGERPRINT_KEY"),
    "_name_hash": ("kapow_block", "_name_hash"),
    "_kprops": ("kapow_block", "props_module"),
    "ASSET_TYPE_NAMES": ("kapow_block", "ASSET_TYPE_NAMES"),
    "_asset_types": ("kapow_block", "_asset_types"),
    "asset_type_name": ("kapow_block", "asset_type_name"),
    "asset_base_class": ("kapow_block", "asset_base_class"),
    "fingerprint_decrypt": ("kapow_block", "fingerprint_decrypt"),
    "Toc": ("kapow_block", "Toc"),
    "BLOCK_ORDER": ("kapow_block", "BLOCK_ORDER"),
    "detect_block_order": ("kapow_block", "detect_block_order"),
    "fingerprint_field_crc": ("kapow_block", "fingerprint_field_crc"),
    "parse_block_header": ("kapow_block", "parse_block_header"),
    "parse_block_toc": ("kapow_block", "parse_block_toc"),
    "parse_block_trailer": ("kapow_block", "parse_block_trailer"),
    "block_stream_sets": ("kapow_block", "block_stream_sets"),
    "stream_file_lookup": ("kapow_block", "stream_file_lookup"),
    "asset_compressed": ("kapow_block", "asset_compressed"),
    "maybe_inflate": ("kapow_block", "maybe_inflate"),
    "asset_class": ("kapow_block", "asset_class"),
    "header_order": ("kapow_block", "header_order"),
    "extract_block": ("kapow_block", "extract_block"),
    "STANDALONE_SIGNATURES": ("kapow_block", "STANDALONE_SIGNATURES"),
    "standalone_preamble": ("kapow_block", "standalone_preamble"),
    "inflate_standalone": ("kapow_block", "inflate_standalone"),
    "_header_order_or_none": ("kapow_block", "header_order_or_none"),
    "language_slot": ("kapow_block", "language_slot"),
    "language_arg": ("kapow_block", "language_arg"),
    "prop_walk": ("kapow_block", "prop_walk"),
    "_PROP_WALK_CAP": ("kapow_block", "_PROP_WALK_CAP"),
    "_PROP_WALK_WARNED": ("kapow_block", "_PROP_WALK_WARNED"),
    "_propbag_end": ("kapow_block", "propbag_end"),
    "_maybe_inflate": ("kapow_block", "maybe_inflate"),
    "_language_arg": ("kapow_block", "language_arg"),
    "_prop_walk": ("kapow_block", "prop_walk"),
    "texture_alpha_flag": ("texture_header", "texture_alpha_flag"),
    "TEX_ENUMS": ("texture_header", "TEX_ENUMS"),
    "TEX_FMT": ("texture_header", "TEX_FMT"),
    "_is_texture": ("texture_header", "is_texture_header"),
    "TEXTURE_SLOTS": ("texture_header", "TEXTURE_SLOTS"),
    "TEXTURE_SLOT_LABELS": ("texture_header", "TEXTURE_SLOT_LABELS"),
    "TEXTURE_LAYER_SLOTS": ("texture_header", "TEXTURE_LAYER_SLOTS"),
    "CUBE_FACE_ORDER": ("texture_header", "CUBE_FACE_ORDER"),
    "_parse_texture_anim_tail": ("texture_header", "_parse_texture_anim_tail"),
    "texture_frame_ms": ("texture_header", "texture_frame_ms"),
    "_TEX_DESC": ("texture_header", "_TEX_DESC"),
    "chain_bytes_exact": ("texture_header", "chain_bytes_exact"),
    "parse_texture_frames": ("texture_header", "parse_texture_frames"),
    "_exact_texture_plan": ("texture_header", "_exact_texture_plan"),
    "parse_texture_header": ("texture_header", "parse_texture_header"),
    "_is_normal_layer": ("texture_header", "is_normal_layer"),
    "texture_layer_label": ("texture_header", "texture_layer_label"),
    "chain_bytes": ("texture_header", "chain_bytes"),
    "_tex_path_off": ("texture_header", "_tex_path_off"),
    "_valid_rec": ("texture_header", "_valid_rec"),
    "_stride_layers": ("texture_header", "_stride_layers"),
    "plan_texture_layers": ("texture_header", "plan_texture_layers"),
    "header_dims": ("texture_header", "header_dims"),
    "_chain_bytes_exact": ("texture_header", "chain_bytes_exact"),
    "_chain_bytes": ("texture_header", "chain_bytes"),
    "_SPEC_HI": ("texture_sheet", "_SPEC_HI"),
    "_SPEC_EXP": ("texture_sheet", "_SPEC_EXP"),
    "_SPEC_INT": ("texture_sheet", "_SPEC_INT"),
    "TEXTURE_SHEET_PROPS": ("texture_sheet", "TEXTURE_SHEET_PROPS"),
    "SHEET_RENDER_TYPES": ("texture_sheet", "SHEET_RENDER_TYPES"),
    "sheet_hashes": ("texture_sheet", "sheet_hashes"),
    "texture_sheet": ("texture_sheet", "texture_sheet"),
    "SHEET_PROPERTIES": ("texture_sheet", "SHEET_PROPERTIES"),
    "SHEET_LAYER_OVERRIDES": ("texture_sheet", "SHEET_LAYER_OVERRIDES"),
    "SHEET_BLEND_TYPES": ("texture_sheet", "SHEET_BLEND_TYPES"),
    "SHEET_BLEND_FACTORS": ("texture_sheet", "SHEET_BLEND_FACTORS"),
    "SHEET_BLEND_OPS": ("texture_sheet", "SHEET_BLEND_OPS"),
    "_T_UNIQUE_ID": ("texture_sheet", "_T_UNIQUE_ID"),
    "sheet_keys": ("texture_sheet", "sheet_keys"),
    "_untyped_sheets": ("texture_sheet", "_untyped_sheets"),
    "texture_sheets": ("texture_sheet", "texture_sheets"),
    "select_sheet": ("texture_sheet", "select_sheet"),
    "sheet_blend": ("texture_sheet", "sheet_blend"),
    "blend_layer_image": ("texture_sheet", "blend_layer_image"),
    "blend_material": ("texture_sheet", "blend_material"),
    "write_sheet_json": ("texture_sheet", "write_sheet_json"),
    "_sheet_warning": ("texture_sheet", "sheet_warning"),
    "read_sheet_json": ("texture_sheet", "read_sheet_json"),
    "extract_specular": ("texture_sheet", "extract_specular"),
    "TEXTURE_DECODE_KEY": ("texture_sheet", "TEXTURE_DECODE_KEY"),
    "_mark_texture_decode": ("texture_sheet", "mark_texture_decode"),
    "mark_stored_name": ("texture_sheet", "mark_stored_name"),
    "first_sheet": ("texture_sheet", "first_sheet"),
    "_sheet_hashes": ("texture_sheet", "sheet_hashes"),
    "_sheet_keys": ("texture_sheet", "sheet_keys"),
    "_write_sheet_json": ("texture_sheet", "write_sheet_json"),
    "_mark_stored_name": ("texture_sheet", "mark_stored_name"),
    "DDS_MAGIC": ("texture_decode", "DDS_MAGIC"),
    "FOURCC": ("texture_decode", "FOURCC"),
    "mip_chain_size": ("texture_decode", "mip_chain_size"),
    "base_mip_bytes": ("texture_decode", "base_mip_bytes"),
    "make_dds": ("texture_decode", "make_dds"),
    "decode_dxt_base": ("texture_decode", "decode_dxt_base"),
    "_bc4_channel": ("texture_decode", "_bc4_channel"),
    "decode_bc5_base": ("texture_decode", "decode_bc5_base"),
    "ati2_xy": ("texture_decode", "ati2_xy"),
    "normal_to_png": ("texture_decode", "normal_to_png"),
    "_coherence": ("texture_decode", "image_coherence"),
    "_looks_like_normal": ("texture_decode", "looks_like_normal"),
    "_unpad_linear": ("texture_decode", "unpad_linear"),
    "decode_one_layer": ("texture_decode", "decode_one_layer"),
    "_decode_dxt3a": ("texture_decode", "_decode_dxt3a"),
    "bswap16": ("texture_decode", "bswap16"),
    "xg2d_offset": ("texture_decode", "xg2d_offset"),
    "_xg_untile": ("texture_decode", "_xg_untile"),
    "_x360_packed_offset": ("texture_decode", "_x360_packed_offset"),
    "_thin_mip_yoff": ("texture_decode", "_thin_mip_yoff"),
    "_x360_layer_bytes": ("texture_decode", "x360_layer_bytes"),
    "_ps3_segments": ("texture_decode", "ps3_segments"),
    "_console_recover_layers": ("texture_decode", "console_recover_layers"),
    "rsx_unswizzle": ("texture_decode", "rsx_unswizzle"),
    "_texel32_to_pc": ("texture_decode", "_texel32_to_pc"),
    "_x360_level0_bytes": ("texture_decode", "x360_level0_bytes"),
    "x360_base_level": ("texture_decode", "x360_base_level"),
    "ps3_layer_image": ("texture_decode", "ps3_layer_image"),
    "_decode_one_layer": ("texture_decode", "decode_one_layer"),
    "_bswap16": ("texture_decode", "bswap16"),
    "_xg2d": ("texture_decode", "xg2d_offset"),
    "_rsx_unswizzle": ("texture_decode", "rsx_unswizzle"),
    "_x360_base_level": ("texture_decode", "x360_base_level"),
    "_ps3_layer_image": ("texture_decode", "ps3_layer_image"),
    "_console_prefix": ("texture_carve", "_console_prefix"),
    "_save_layer_png": ("texture_carve", "_save_layer_png"),
    "_carve_x360_exact": ("texture_carve", "_carve_x360_exact"),
    "_carve_ps3_exact": ("texture_carve", "_carve_ps3_exact"),
    "carve_texture_console": ("texture_carve", "carve_texture_console"),
    "_write_spec_txt": ("texture_carve", "_write_spec_txt"),
    "RESCUE_MAX_PLANS": ("texture_carve", "RESCUE_MAX_PLANS"),
    "_exact_mip_sums": ("texture_carve", "_exact_mip_sums"),
    "rescue_texture_plan": ("texture_carve", "rescue_texture_plan"),
    "PC_CUBE_LEVEL_MAJOR": ("texture_carve", "PC_CUBE_LEVEL_MAJOR"),
    "carve_texture": ("texture_carve", "carve_texture"),
    "_carve_texture": ("texture_carve", "_carve_texture"),
    "_carve_texture_legacy": ("texture_carve", "_carve_texture_legacy"),
    "_rescue_texture_plan": ("texture_carve", "rescue_texture_plan"),
    "_u32le": ("material_refs", "_u32le"),
    "_u32": ("material_refs", "u32_at"),
    "_TEX_RE": ("material_refs", "_TEX_RE"),
    "texture_key": ("material_refs", "texture_key"),
    "TexRef": ("material_refs", "TexRef"),
    "texture_ref": ("material_refs", "texture_ref"),
    "extract_materials": ("material_refs", "extract_materials"),
    "_u32_all": ("material_refs", "_u32_all"),
    "_descriptor_candidates": ("material_refs", "_descriptor_candidates"),
    "submesh_materials": ("material_refs", "submesh_materials"),
    "_material_stem": ("material_refs", "material_stem"),
    "VERTEX_STRIDES": ("model_header", "VERTEX_STRIDES"),
    "VERTEX_FORMATS": ("model_header", "VERTEX_FORMATS"),
    "CONSOLE_VERTEX_STRIDES": ("model_header", "CONSOLE_VERTEX_STRIDES"),
    "CONSOLE_VERTEX_FORMATS": ("model_header", "CONSOLE_VERTEX_FORMATS"),
    "_STREAM_RECORDS": ("model_header", "_STREAM_RECORDS"),
    "_VOLUME_FLOATS": ("model_header", "_VOLUME_FLOATS"),
    "console_header_decode": ("model_header", "console_header_decode"),
    "vertex_strides": ("model_header", "vertex_strides"),
    "vertex_formats": ("model_header", "vertex_formats"),
    "read_meshbuffer": ("model_header", "read_meshbuffer"),
    "PRIMITIVE_NAMES": ("model_header", "PRIMITIVE_NAMES"),
    "index_triangles": ("model_header", "index_triangles"),
    "_mr_part": ("model_header", "_mr_part"),
    "MODEL_LAYOUTS": ("model_header", "MODEL_LAYOUTS"),
    "model_header_layout_hint": ("model_header", "model_header_layout_hint"),
    "_parse_model_header_as": ("model_header", "_parse_model_header_as"),
    "parse_model_header": ("model_header", "parse_model_header"),
    "model_stream_layout": ("model_header", "model_stream_layout"),
    "check_lod": ("model_header", "check_lod"),
    "model_lod_arg": ("model_header", "model_lod_arg"),
    "BUFFER_KINDS": ("model_header", "BUFFER_KINDS"),
    "BUFFER_KIND_ALIASES": ("model_header", "BUFFER_KIND_ALIASES"),
    "BUFFER_ROLES": ("model_header", "BUFFER_ROLES"),
    "_LOD_PAIRS": ("model_header", "_LOD_PAIRS"),
    "model_property_bag": ("model_header", "model_property_bag"),
    "model_lod_info": ("model_header", "model_lod_info"),
    "model_surfaces": ("model_header", "model_surfaces"),
    "select_model_buffers": ("model_header", "select_model_buffers"),
    "_part_local_matrix": ("model_header", "_part_local_matrix"),
    "_part_is_identity": ("model_header", "_part_is_identity"),
    "model_part_transforms": ("model_header", "model_part_transforms"),
    "apply_part_transform": ("model_header", "apply_part_transform"),
    "_mr_meshbuffer": ("model_header", "read_meshbuffer"),
    "_model_lod_arg": ("model_header", "model_lod_arg"),
    "is_finite_float": ("model_mesh", "is_finite_float"),
    "_vb_run": ("model_mesh", "_vb_run"),
    "_read_ib": ("model_mesh", "_read_ib"),
    "_pick_vb": ("model_mesh", "pick_vertex_buffer"),
    "find_descriptors": ("model_mesh", "find_descriptors"),
    "ib_ok": ("model_mesh", "ib_ok"),
    "vb_ok": ("model_mesh", "vb_ok"),
    "vb_ok_flat": ("model_mesh", "vb_ok_flat"),
    "_dec1110": ("model_mesh", "_dec1110"),
    "LASH_RESTORE": ("model_mesh", "LASH_RESTORE"),
    "synth_enabled": ("model_mesh", "synth_enabled"),
    "lash_strips": ("model_mesh", "lash_strips"),
    "lash_restored_uvs": ("model_mesh", "lash_restored_uvs"),
    "lash_is_restored": ("model_mesh", "lash_is_restored"),
    "lash_reconstruction_note": ("model_mesh", "lash_reconstruction_note"),
    "_strided": ("model_mesh", "_strided"),
    "_unit_rows": ("model_mesh", "_unit_rows"),
    "_rows3": ("model_mesh", "_rows3"),
    "decode_mesh_vertices": ("model_mesh", "decode_mesh_vertices"),
    "_decode_sub_np": ("model_mesh", "_decode_sub_np"),
    "_dec1110_array": ("model_mesh", "_dec1110_array"),
    "CONSOLE_COLOR_ORDERS": ("model_mesh", "CONSOLE_COLOR_ORDERS"),
    "CONSOLE_PLATFORM": ("model_mesh", "CONSOLE_PLATFORM"),
    "_PLATFORM_DIRS": ("model_mesh", "_PLATFORM_DIRS"),
    "_PLATFORM_CACHE": ("model_mesh", "_PLATFORM_CACHE"),
    "console_platform_of": ("model_mesh", "console_platform_of"),
    "set_console_platform": ("model_mesh", "set_console_platform"),
    "console_platform": ("model_mesh", "console_platform"),
    "detect_console_platform": ("model_mesh", "detect_console_platform"),
    "console_platform_for": ("model_mesh", "console_platform_for"),
    "_console_color_order_inferred": ("model_mesh", "_console_color_order_inferred"),
    "console_color_order": ("model_mesh", "console_color_order"),
    "_console_color_white": ("model_mesh", "_console_color_white"),
    "console_color_undecoded": ("model_mesh", "console_color_undecoded"),
    "decode_vertex_attributes": ("model_mesh", "decode_vertex_attributes"),
    "gltf_tangents": ("model_mesh", "gltf_tangents"),
    "decode_model_mesh": ("model_mesh", "decode_model_mesh"),
    "half_to_float": ("model_mesh", "half_to_float"),
    "_sane": ("model_mesh", "is_finite_float"),
    "_ib_ok": ("model_mesh", "ib_ok"),
    "_vb_ok": ("model_mesh", "vb_ok"),
    "_vb_ok_flat": ("model_mesh", "vb_ok_flat"),
    "_decode_sub": ("model_mesh", "decode_mesh_vertices"),
    "_half": ("model_mesh", "half_to_float"),
    "sheet_layer_dirs": ("obj_mtl", "sheet_layer_dirs"),
    "TEXTURE_DIR_EXTS": ("obj_mtl", "TEXTURE_DIR_EXTS"),
    "TextureIndex": ("obj_mtl", "TextureIndex"),
    "build_texture_index": ("obj_mtl", "build_texture_index"),
    "resolve_texture": ("obj_mtl", "resolve_texture"),
    "unique_material_names": ("obj_mtl", "unique_material_names"),
    "find_layer": ("obj_mtl", "find_layer"),
    "_make_roughness": ("obj_mtl", "_make_roughness"),
    "_materials_mode": ("obj_mtl", "materials_mode"),
    "mtl_no_highlight": ("obj_mtl", "mtl_no_highlight"),
    "_mtl_opacity": ("obj_mtl", "_mtl_opacity"),
    "_mtl_emission": ("obj_mtl", "_mtl_emission"),
    "mtl_const_roughness": ("obj_mtl", "mtl_const_roughness"),
    "mtl_ns_of_roughness": ("obj_mtl", "mtl_ns_of_roughness"),
    "_make_roughness_engine": ("obj_mtl", "_make_roughness_engine"),
    "write_obj_mtl": ("obj_mtl", "write_obj_mtl"),
    "_find_layer": ("obj_mtl", "find_layer"),
    "_mtl_no_highlight": ("obj_mtl", "mtl_no_highlight"),
    "_mtl_const_roughness": ("obj_mtl", "mtl_const_roughness"),
    "_mtl_ns_of_roughness": ("obj_mtl", "mtl_ns_of_roughness"),
    "_write_obj_mtl": ("obj_mtl", "write_obj_mtl"),
    "_RIG": ("model_export", "_RIG"),
    "_texture_size_arg": ("model_export", "_texture_size_arg"),
    "_rig_load": ("model_export", "_rig_load"),
    "_model_palette": ("model_export", "_model_palette"),
    "_model_is_body": ("model_export", "_model_is_body"),
    "_surface_summary": ("model_export", "_surface_summary"),
    "_parts_summary": ("model_export", "_parts_summary"),
    "PARTS_NOTE": ("model_export", "PARTS_NOTE"),
    "_model_tail_meta": ("model_export", "_model_tail_meta"),
    "MORPH_CHANNEL_NOTE": ("model_export", "MORPH_CHANNEL_NOTE"),
    "model_meta": ("model_export", "model_meta"),
    "model_meta_reduced": ("model_export", "model_meta_reduced"),
    "model_meta_scanned": ("model_export", "model_meta_scanned"),
    "_header_model_plan": ("model_export", "_header_model_plan"),
    "_model_skipped": ("model_export", "_model_skipped"),
    "MODEL_STATUS": ("model_export", "MODEL_STATUS"),
    "decode_model": ("model_export", "decode_model"),
    "_decode_model": ("model_export", "_decode_model"),
    "_media_link": ("sound_header", "_media_link"),
    "media_tracks_pc": ("sound_header", "media_tracks_pc"),
    "_TRACK0": ("sound_header", "_TRACK0"),
    "media_track_name": ("sound_header", "media_track_name"),
    "_media_walk_segments": ("sound_header", "_media_walk_segments"),
    "_ps3_media_link": ("sound_header", "_ps3_media_link"),
    "_ps3_media_seg": ("sound_header", "_ps3_media_seg"),
    "_ps3_media_walk": ("sound_header", "_ps3_media_walk"),
    "_console_media_parse": ("sound_header", "console_media_parse"),
    "_ps3_media_tracks": ("sound_header", "_ps3_media_tracks"),
    "_x360_media_tracks": ("sound_header", "_x360_media_tracks"),
    "media_tracks_console": ("sound_header", "media_tracks_console"),
    "_xma_frame_count": ("sound_header", "xma_frame_count"),
    "media_meta_from_header": ("sound_header", "media_meta_from_header"),
    "media_desc_from_header": ("sound_header", "media_desc_from_header"),
    "adpcm_layout": ("sound_header", "adpcm_layout"),
    "sfx_info": ("sound_header", "sfx_info"),
    "_MP3_KBPS": ("sound_header", "_MP3_KBPS"),
    "_MP3_RATE": ("sound_header", "_MP3_RATE"),
    "mp3_frame_stats": ("sound_header", "mp3_frame_stats"),
    "_ps3_sound_info": ("sound_header", "_ps3_sound_info"),
}


def _forwarding_type(homes):
    """A module type with one property per name in `homes` that reads, sets and
    deletes the name in its home module.  A property is a data descriptor, so
    attribute access goes through it before the module's own namespace, and
    monkeypatch (pytest 9.2 restores a module attribute from the module's
    namespace unless a data descriptor serves it) records and restores the
    home's value."""

    def forward(home, there):
        def get(_mod):
            return getattr(importlib.import_module(home), there)

        def put(_mod, value):
            setattr(importlib.import_module(home), there, value)

        def drop(_mod):
            delattr(importlib.import_module(home), there)

        return property(get, put, drop, "%s.%s" % (home, there))

    names = {name: forward(*home) for name, home in homes.items()}
    return type("_Forwarding", (types.ModuleType,), names)


sys.modules[__name__].__class__ = _forwarding_type(_HOMES)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
