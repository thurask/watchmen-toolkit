"""Audio assets to files: music streams as Ogg Vorbis, one file per track
(`decode_audio`, `decode_audio_tracks`, `audio_packets`, `ogg_from_packets`,
`vorbis_blockflags`, `OGG_PAGE_BYTES`), console streams as XMA2 / MP3
(`decode_console_audio`, `decode_sfx_console`), and sounds as WAV from
MS-ADPCM or PCM (`decode_sfx`, `adpcm_mono`, `adpcm_predict`,
`ADPCM_COEF_PAIRS`, `write_wav`).

  AUDIO    raw Vorbis packets (no Ogg framing) in [32-byte block][packet] framing,
           in ~40 KB chunks, one chunk per track per group, groups chained by
           link records; rebuilt into one real Ogg Vorbis file per track.
"""

import array
import os
import struct
import sys
import wave

# the flat wlib modules import each other by name (`import kapow_props`); one path
# setup for this module, also when it is run as a script or loaded by file path.
# Append, never insert(0): flat module names must not shadow the stdlib.
_WLIB = os.path.dirname(os.path.abspath(__file__))
if _WLIB not in sys.path:
    sys.path.append(_WLIB)
import extract_log  # noqa: E402
import extract_paths  # noqa: E402
import kapow_block  # noqa: E402
import sound_header  # noqa: E402


# MS-ADPCM tables (SFX 'sound' assets are MS-ADPCM/PCM -> WAV; music stays Ogg)
_COEF = (256, 0, 512, -256, 0, 0, 192, 64, 240, 0, 460, -208, 392, -232)
_COEFB = struct.pack("<14h", *_COEF)
_ADAPT = (230, 230, 230, 230, 307, 409, 512, 614, 768, 614, 512, 409, 307, 230, 230, 230)
_C1 = (256, 512, 0, 192, 240, 460, 392)
_C2 = (0, -256, 0, 64, 0, -208, -232)


def audio_packets(d):
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


def decode_audio(raw, out_path, exact, log=None):
    """The single-file output (--flat-music): every packet of the stream in file order.
    Correct for a one-track stream; a multi-track stream comes out as its tracks'
    chunks appended in turn (use decode_audio_tracks)."""
    if not callable(log):
        log = lambda *a, **k: None
    r = ogg_from_packets(audio_packets(raw), exact)
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


def _clamp16(x):
    return -32768 if x < -32768 else (32767 if x > 32767 else x)


#: the standard MS-ADPCM coefficient pairs (c1, c2), predictor index 0..6
ADPCM_COEF_PAIRS = tuple(zip(_C1, _C2, strict=True))


def adpcm_predict(s1, s2, c1, c2):
    """(s1*c1 + s2*c2) / 256 truncated toward zero, as the Microsoft reference
    decoder, the Windows ACM codec and ffmpeg compute it (C integer division);
    a plain `>> 8` floors (differs by 1 on negative odd sums)."""
    t = s1 * c1 + s2 * c2
    return t >> 8 if t >= 0 else -((-t) >> 8)


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
