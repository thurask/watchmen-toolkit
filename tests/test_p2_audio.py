"""Console sound headers: durations, audio/sound_info.json and the containers.

Synthetic fixtures only.  They mirror what was read on the six exported sets
(2026-10-05), all big-endian:

* PS3 `sound` header after the property bag (pe): +0 looping, +1 is3d, +2 a
  byte that is 1, +3 rate, +7 channels, +11 samples (whole MP3 frames x 1152;
  a looping sound holds two frames more than its count), +15 bytes per second,
  +19 size (32 + MP3 bytes + padding), +23 a 32-byte segment header whose first
  dword is the MP3 byte count, +55 the MP3 frames, padding, a u32 cue count.
* X360: the PC PCM layout with format 3; the 2048-byte XMA2 packets start at
  pe+26, right after their byte count, and `samples` = packet frame counts x 512.
"""

import json
import os
import struct
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import sound_meta as sm
import test_audio_v2 as au
import test_text_assets as tt
import text_assets as ta
import watchmen_extract as wx

text_extract = tt.text_extract  # the fixture of test_text_assets, used below


# ------------------------------------------------------------------ builders
def bag(order=">"):
    """[type name][class id][one property record] of a `sound` asset."""
    h = struct.pack(order + "I", 6) + b"sound\x00" + struct.pack(order + "I", 0x1234)
    return h + struct.pack(order + "5I", 0xA1B2C3D4, 0x11, 0x22, 0, 7)


def mp3_frames(n, rate=48000, kbps=64, mono=True, fill=0x55):
    """n MPEG-1 layer III frames (header + filler), no padding bit."""
    bi = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320).index(kbps)
    si = (44100, 48000, 32000).index(rate)
    head = bytes([0xFF, 0xFB, (bi << 4) | (si << 2), 0xC4 if mono else 0x64])
    size = 144 * kbps * 1000 // rate
    return b"".join(head + bytes([(fill + k) & 0xFF]) * (size - 4) for k in range(n))


def ps3_sound(frames=10, rate=48000, ch=1, loop=0, is3d=1, samples=None, pad=0, word4=0, cues=0):
    """A PS3 `sound` header.  samples: the stored count (default: frames x 1152,
    or two frames less on a looping sound, as shipped)."""
    kbps = 64 * ch
    data = mp3_frames(frames, rate, kbps, mono=ch == 1)
    if samples is None:
        samples = (frames - (2 if loop else 0)) * 1152
    seg = struct.pack(">I", len(data)) + b"\x00" * 12 + struct.pack(">I", word4) + b"\x00" * 12
    h = bag() + bytes([loop, is3d, 1])
    h += struct.pack(">5I", rate, ch, samples, kbps * 125, 32 + len(data) + pad)
    return h + seg + data + b"\x00" * pad + struct.pack(">I", cues), data


def xma_packets(counts):
    """One 2048-byte XMA2 packet per entry; the top six bits = its frame count."""
    return b"".join(
        bytes([c << 2, 0, 1, 0]) + bytes([0x30 + k]) * 2044 for k, c in enumerate(counts)
    )


def x360_sound(counts=(17, 15), rate=48000, ch=1, loop=0, is3d=1, samples=None):
    data = xma_packets(counts)
    if samples is None:
        samples = sum(counts) * 512
    h = bag() + bytes([loop, is3d]) + struct.pack(">4I", ch, rate, 3, rate)
    return h + struct.pack(">2I", samples, len(data)) + data + struct.pack(">I", 0), data


def be_block(assets):
    """A big-endian block_h_z holding `assets` = [(name, header blob)]."""
    toc = blobs = b""
    for name, blob in assets:
        nm = name.encode("latin1") + b"\0"
        toc += struct.pack(">6I", *([len(blob)] * 6)) + struct.pack(">I", 0x1111)
        toc += struct.pack(">I", len(nm)) + nm + b"\x00"
        blobs += blob
    hdr = bytearray(400)
    hdr[0x24:0x48] = b"DB851B2E-F452-47f7-9C7D-0BD4918F6F07"
    hdr[0x147] = 2
    big = max(len(toc), max(len(b) for _n, b in assets))
    trailer = 400 + len(toc) + len(blobs)
    struct.pack_into(
        ">9I", hdr, 328, 0x593F430A, len(toc), len(assets[0][1]), big, trailer, 8, len(assets), 0, 0
    )
    return bytes(hdr) + toc + blobs + b"\0" * 8


def run_extract(tmp_path, capsys, assets, block=None):
    src = tmp_path / "files" / "levels"
    src.mkdir(parents=True, exist_ok=True)
    (src / "x.block_h_z").write_bytes(block if block is not None else be_block(assets))
    (src / "x.block_s_z").write_bytes(b"")
    out = tmp_path / "out"
    capsys.readouterr()
    assert wx.main([str(tmp_path / "files"), "-o", str(out), "--no-files", "--no-text"]) == 0
    return out, capsys.readouterr().out


# -------------------------------------------------------------- MP3 frames
def test_mp3_frame_walk_counts_whole_frames():
    d = mp3_frames(7)
    assert len(d) == 7 * 192
    fs = wx.mp3_frame_stats(d)
    assert (fs["frames"], fs["samples"], fs["rate"], fs["channels"]) == (7, 7 * 1152, 48000, 1)
    assert fs["bytes"] == len(d) and fs["clean"] is True
    # bytes after the last whole frame are counted out, not guessed into a frame
    fs = wx.mp3_frame_stats(d + b"\xff\xfb\x54")
    assert fs["frames"] == 7 and fs["clean"] is False and fs["bytes"] == len(d)
    # stereo 128 kbit/s at 44100: 417-byte frames, 418 with the padding bit
    st = bytes([0xFF, 0xFB, 0x90, 0x64]) + b"\x00" * 413
    pad = bytes([0xFF, 0xFB, 0x92, 0x64]) + b"\x00" * 414
    fs = wx.mp3_frame_stats(st + pad + st)
    assert (fs["frames"], fs["channels"], fs["rate"], fs["clean"]) == (3, 2, 44100, True)
    # MPEG-2 layer III: 576 samples a frame
    m2 = bytes([0xFF, 0xF3, 0x80, 0xC4]) + b"\x00" * (72 * 64000 // 22050 - 4)
    assert wx.mp3_frame_stats(m2 * 2)["samples"] == 2 * 576
    assert wx.mp3_frame_stats(b"\x00" * 64)["frames"] == 0
    assert wx.mp3_frame_stats(b"\xff\xe0\x00\x00" * 8)["frames"] == 0  # a sync is not a frame


# ----------------------------------------------------------- sound headers
def test_ps3_sound_header_gives_the_stored_sample_count():
    h, data = ps3_sound(frames=10, rate=48000, pad=7)
    assert wx.sfx_info(h, "<") is None  # the PC reader does not take it
    i = wx.sfx_info(h, ">")
    assert i["codec"] == "mp3" and (i["channels"], i["rate"]) == (1, 48000)
    assert (i["looping"], i["is3d"]) == (False, True)
    assert i["samples"] == 10 * 1152 and i["duration_s"] == 0.24
    assert i["duration_source"] == "header"
    assert (i["mp3_frames"], i["mp3_frame_samples"], i["mp3_clean"]) == (10, 11520, True)
    assert i["bytes_per_second"] == 8000 and i["original_rate"] is None
    assert h[i["data_offset"] : i["data_offset"] + i["data_bytes"]] == data
    assert i["cue_points"] == [] and "segment_word4" not in i


def test_ps3_looping_sound_keeps_its_count_and_the_unread_word():
    h, _d = ps3_sound(frames=12, rate=44100, ch=2, loop=1, is3d=0, word4=384)
    i = wx.sfx_info(h, ">")
    assert (i["looping"], i["is3d"], i["channels"]) == (True, False, 2)
    # the header count, not frames x 1152: a looping sound holds two frames more
    assert i["samples"] == 10 * 1152 and i["mp3_frames"] == 12
    assert i["duration_s"] == round(11520 / 44100.0, 4) and i["duration_source"] == "header"
    assert i["segment_word4"] == 384


def test_ps3_header_without_a_count_falls_back_to_the_frames_and_says_so():
    h, _d = ps3_sound(frames=5, samples=0)
    i = wx.sfx_info(h, ">")
    assert i["samples"] == 5 * 1152 and i["duration_source"] == "frame_count"
    assert i["duration_s"] == 0.12


def test_ps3_layout_is_not_guessed_from_other_bytes():
    h, _d = ps3_sound(frames=4)
    pe = wx._propbag_end(h, ">")
    assert wx.sfx_info(h[: pe + 55 + 100], ">") is None  # MP3 bytes cut short
    bad = bytearray(h)
    bad[pe + 55] = 0x00  # no frame where the MP3 has to start
    assert wx.sfx_info(bytes(bad), ">") is None
    bad = bytearray(h)
    struct.pack_into(">I", bad, pe + 7, 9)  # nine channels
    assert wx.sfx_info(bytes(bad), ">") is None


def test_x360_sound_header_count_is_whole_xma_frames():
    h, data = x360_sound(counts=(17, 15))
    i = wx.sfx_info(h, ">")
    assert i["codec"] == "xma2" and i["samples"] == 32 * 512
    assert i["xma_frames"] == 32 and i["duration_source"] == "header"
    assert i["duration_s"] == round(32 * 512 / 48000.0, 4)
    assert h[i["data_offset"] : i["data_offset"] + i["data_bytes"]] == data
    # no stored count: the packets' frame counts
    h, _d = x360_sound(counts=(3, 4), samples=0)
    i = wx.sfx_info(h, ">")
    assert i["samples"] == 7 * 512 and i["duration_source"] == "frame_count"


def test_pc_sound_record_has_no_console_keys():
    i = wx.sfx_info(au.sound_header(2, 48000, 1, au.ramp(480, 2), loop=1, is3d=0))
    assert "duration_source" not in i and "xma_frames" not in i and "mp3_frames" not in i


# ------------------------------------------------------------- containers
def test_x360_xma_starts_at_the_first_packet(tmp_path):
    """1.3.0 cut the packets from pe+30: four bytes into the first packet and
    four bytes (the cue count) past the last.  No decoder read the result."""
    h, data = x360_sound(counts=(17, 15), ch=2)
    logs = []
    rec = wx.decode_sfx_console(h, ">", "sounds/fx/a.wav", tmp_path, None, logs.append)
    riff = (tmp_path / "sounds/fx/a.wav.xma").read_bytes()
    j = riff.index(b"data")
    assert struct.unpack_from("<I", riff, j + 4)[0] == len(data)
    assert riff[j + 8 :] == data
    assert riff[j + 8] >> 2 == 17  # the first packet's frame count
    # XMA2WAVEFORMATEX: channels, rate and the header's sample count
    assert struct.unpack_from("<HHI", riff, 20) == (0x166, 2, 48000)
    assert rec["file"] == "sounds/fx/a.wav.xma" and rec["duration_source"] == "header"
    assert "_pe" not in rec and not [x for x in logs if "!" in x]


def test_ps3_mp3_is_the_whole_segment(tmp_path):
    """The 1.3.0 size scan took the first big-endian u32 within 512 bytes of the
    data length -- the bytes-per-second field (8000) of a sound 8064 bytes long
    -- and cut the MP3 short."""
    h, data = ps3_sound(frames=42, pad=9)  # 42 x 192 = 8064 bytes at 8000 bytes/s
    assert len(data) == 8064
    rec = wx.decode_sfx_console(h, ">", "sounds/fx/b.wav", tmp_path, None, lambda *a: None)
    assert (tmp_path / "sounds/fx/b.wav.mp3").read_bytes() == data
    assert rec["file"] == "sounds/fx/b.wav.mp3"
    assert rec["samples"] == 42 * 1152 and rec["duration_s"] == 1.008


def test_unknown_console_header_writes_nothing_and_is_not_scanned_into_audio(tmp_path):
    # a stream descriptor-like blob with bytes that look like a frame sync
    h = bag() + b"\x00\x01" + b"\x00" * 20 + b"\xff\xe3/sounds/x.mediastream_s\x00" + b"\x07" * 400
    logs = []
    assert wx.decode_sfx_console(h, ">", "sounds/x.wav", tmp_path, None, logs.append) is False
    assert not list(tmp_path.rglob("*.mp3")) and not list(tmp_path.rglob("*.xma"))
    # an MP3 the header reader does not take is still written, with a log line
    data = mp3_frames(6)
    odd = bag() + b"\x00\x01\x09" + b"\x00" * 30 + data
    rec = wx.decode_sfx_console(odd, ">", "sounds/y.wav", tmp_path, None, logs.append)
    assert (tmp_path / "sounds/y.wav.mp3").read_bytes() == data
    assert rec["header"] == "not recognised" and rec["duration_source"] == "frame_count"
    assert rec["duration_s"] == 0.144
    assert any("sounds/y.wav: sound header not recognised" in x for x in logs)


# ------------------------------------------------------- the extract (main)
@pytest.mark.parametrize("platform", ["ps3", "x360"])
def test_console_extract_writes_sound_info_and_says_what_it_did(tmp_path, capsys, platform):
    if platform == "ps3":
        a, da = ps3_sound(frames=10)
        b, _db = ps3_sound(frames=12, loop=1, word4=384)
        ext, codec = ".mp3", "mp3"
    else:
        a, da = x360_sound(counts=(17, 15))
        b, _db = x360_sound(counts=(4,), loop=1)
        ext, codec = ".xma", "xma2"
    odd = bag() + b"\x00\x01\x09" + b"\x00" * 60
    assets = [("sounds/fx/A.wav", a), ("sounds/fx/b.wav", b), ("sounds/fx/odd.wav", odd)]
    out, log = run_extract(tmp_path, capsys, assets)
    doc = json.loads((out / "audio" / "sound_info.json").read_text(encoding="utf-8"))
    assert doc["format"] == "watchmen-sound-info/1"
    assert sorted(doc["sounds"]) == ["sounds/fx/A.wav", "sounds/fx/b.wav"]
    ra, rb = doc["sounds"]["sounds/fx/A.wav"], doc["sounds"]["sounds/fx/b.wav"]
    # the PC keys, plus where the duration is from
    for k in ("looping", "is3d", "channels", "original_rate", "codec", "rate", "samples"):
        assert k in ra
    for k in ("data_bytes", "data_offset", "cue_points", "duration_s", "file"):
        assert k in ra
    assert ra["codec"] == codec and ra["duration_source"] == "header" and ra["duration_s"] > 0
    assert ra["file"] == "sounds/fx/A.wav" + ext and rb["looping"] is True
    assert (out / "audio" / ra["file"]).is_file()
    if platform == "ps3":
        assert (out / "audio" / ra["file"]).read_bytes() == da
    # the header nothing reads: marked in the file and in the log, not dropped
    assert doc["not_decoded"] == ["sounds/fx/odd.wav"]
    assert "WARNING: sfx sounds/fx/odd.wav: sound header not decoded; no audio written" in log
    assert "SOUND INFO: 2 sounds -> audio/sound_info.json (duration from: header 2; " in log
    assert (
        "CONSOLE SFX: 2 of 2 sounds written as .mp3 / .xma containers (vgmstream: not set)" in log
    )


def test_pc_sound_info_is_unchanged(tmp_path, capsys):
    """The PC file keeps its 1.4.0 keys: no duration_source, no console line."""
    le = struct.pack("<I", 6) + b"sound\x00"
    h = au.sound_header(2, 48000, 1, au.ramp(480, 2), loop=1, is3d=0)
    assert h.startswith(le)
    toc = struct.pack("<6I", *([len(h)] * 6)) + struct.pack("<I", 0x1111)
    toc += struct.pack("<I", 17) + b"sounds/fx/pc.wav\0" + b"\x00"
    hdr = bytearray(400)
    hdr[0x147] = 2
    struct.pack_into(
        "<9I", hdr, 328, 0x593F430A, len(toc), len(h), len(h), 400 + len(toc) + len(h), 8, 1, 0, 0
    )
    out, log = run_extract(tmp_path, capsys, None, block=bytes(hdr) + toc + h + b"\0" * 8)
    doc = json.loads((out / "audio" / "sound_info.json").read_text(encoding="utf-8"))
    assert sorted(doc) == ["format", "sounds"]
    rec = doc["sounds"]["sounds/fx/pc.wav"]
    assert sorted(rec) == sorted(
        [
            "looping",
            "is3d",
            "channels",
            "original_rate",
            "codec",
            "rate",
            "samples",
            "data_bytes",
            "data_offset",
            "cue_points",
            "duration_s",
            "file",
        ]
    )
    assert rec["duration_s"] == 0.01 and (out / "audio" / "sounds/fx/pc.wav").is_file()
    assert "SOUND INFO" not in log and "CONSOLE SFX" not in log


def test_one_track_console_stream_takes_its_facts_from_the_descriptor(tmp_path):
    """A loose tree names the stream below `derived_<platform>/`, so the facts
    kept by stream path miss it: 4 X360 Part-1 tracks had no rate / duration."""
    raw = xma_packets((8,) * 4)
    desc = {"tracks": [{"samples": 16384, "channels": 2, "rate": 44100}]}
    name = "sounds/Music/GameOver_track0.mediastream_s"
    quiet = lambda *a: None
    out = wx.decode_console_audio(name, raw, tmp_path, None, None, quiet, tracks=True, desc=desc)
    assert len(out) == 1
    t = out[0]
    assert (t["channels"], t["rate"], t["samples"]) == (2, 44100, 16384)
    assert t["duration_s"] == round(16384 / 44100.0, 4)
    riff = (tmp_path / (name + ".xma")).read_bytes()
    assert struct.unpack_from("<HHI", riff, 20) == (0x166, 2, 44100)
    # facts by path still win
    out = wx.decode_console_audio(
        name, raw, tmp_path, (2, 48000, 16384), None, quiet, tracks=True, desc=desc
    )
    assert out[0]["rate"] == 48000


# ----------------------------------------------------------------- consumers
def put_raw(root, path, blob):
    f = root / "extracted" / path.lstrip("/")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(blob)


def test_sounddb_reads_console_durations(tmp_path):
    put_raw(tmp_path, "/sounds/fx/short.wav", ps3_sound(frames=10)[0])
    # longer than the 64 KiB the PC / X360 facts need: the MP3 frames are checked
    big = ps3_sound(frames=400, loop=1, word4=384)[0]
    assert len(big) > (1 << 16)
    put_raw(tmp_path, "/sounds/fx/long.wav", big)
    put_raw(tmp_path, "/sounds/fx/x.wav", x360_sound(counts=(17, 15))[0])
    db = sm.SoundDB(str(tmp_path))
    w = db.wave("/sounds/fx/short.wav")
    assert w["duration_s"] == 0.24 and w["codec"] == "mp3" and w["duration_source"] == "header"
    assert w["basis"] == "sound header" and w["loop"] is False
    w = db.wave("/sounds/fx/long.wav")
    assert w["duration_s"] == round(398 * 1152 / 48000.0, 4) and w["loop"] is True
    w = db.wave("/sounds/fx/x.wav")
    assert w["codec"] == "xma2" and w["duration_source"] == "header"
    rep = db.duration_report()
    assert rep["codecs"] == {"mp3": 2, "xma2": 1} and rep["sources"] == {"header": 3}
    assert rep["without_duration"] == []


def test_sounddb_uses_sound_info_json_then_the_decoded_file(tmp_path):
    """No raw header under extracted/: audio/sound_info.json has the same
    facts; a decoded .wav is the last source and is marked as such."""
    (tmp_path / "extracted").mkdir()
    audio = tmp_path / "audio" / "sounds" / "fx"
    audio.mkdir(parents=True)
    rec = {
        "looping": True,
        "channels": 1,
        "rate": 48000,
        "codec": "mp3",
        "duration_s": 1.5,
        "duration_source": "header",
        "file": "sounds/fx/A.wav.mp3",
    }
    doc = {"format": "watchmen-sound-info/1", "sounds": {"sounds/fx/A.wav": rec}}
    (tmp_path / "audio" / "sound_info.json").write_text(json.dumps(doc))
    wx.write_wav(au.ramp(4800, 1), 1, 48000, audio / "dec.wav")
    db = sm.SoundDB(str(tmp_path))
    w = db.wave("/sounds/fx/a.wav")  # asset paths compare without case
    assert w["duration_s"] == 1.5 and w["loop"] is True
    assert w["basis"] == "audio/sound_info.json" and w["duration_source"] == "header"
    w = db.wave("/sounds/fx/dec.wav")
    assert w["duration_s"] == 0.1 and w["duration_source"] == "decoded"
    assert db.wave("/sounds/fx/none.wav") is None


def console_extract(root, header_of):
    for nm in ("a", "b"):
        put_raw(root, "/sounds/fx/%s.wav" % nm, header_of(nm))
    db = au.Frag(au.SOUNDDB)
    one = db.add("SoundDef", "one", sound="/sounds/fx/a.wav", _iselectionmethod=1)
    db.add("SoundDef", "", one, sound="/sounds/fx/b.wav", _iselectionmethod=3)
    db.write(root)
    return str(root)


def test_sound_meta_marks_console_durations_and_leaves_a_pc_table_alone(tmp_path):
    ps3 = console_extract(
        tmp_path / "ps3", lambda nm: ps3_sound(frames=10 if nm == "a" else 20, samples=0)[0]
    )
    logs = []
    meta = sm.build(ps3, log=logs.append)
    d = next(iter(meta["definitions"].values()))
    assert d["duration_s"]["max"] == 0.48 and d["missing_waves"] == 0
    wd = meta["wave_durations"]
    assert wd["codecs"] == {"mp3": 2} and wd["sources"] == {"frame_count": 2}
    assert wd["without_duration"] == [] and wd["reparsed_fragments"] == {}
    assert any("mp3 durations: frame_count 2" in x for x in logs)
    pc = tmp_path / "pc"
    for nm, sec in (("a", 0.25), ("b", 0.5)):
        au.put_wave(pc, "/sounds/fx/%s.wav" % nm, sec)
    frag = au.Frag(au.SOUNDDB)
    one = frag.add("SoundDef", "one", sound="/sounds/fx/a.wav", _iselectionmethod=1)
    frag.add("SoundDef", "", one, sound="/sounds/fx/b.wav", _iselectionmethod=3)
    frag.write(pc)
    logs = []
    meta = sm.build(str(pc), log=logs.append)
    assert "wave_durations" not in meta
    assert not [x for x in logs if "durations" in x or "no duration" in x]


def test_sound_meta_names_the_sounds_it_has_no_duration_for(tmp_path):
    odd = bag() + b"\x00\x01\x09" + b"\x00" * 60
    root = console_extract(tmp_path, lambda nm: odd if nm == "b" else ps3_sound(frames=10)[0])
    logs = []
    meta = sm.build(root, log=logs.append)
    assert meta["wave_durations"]["without_duration"] == ["sounds/fx/b.wav"]
    assert next(iter(meta["definitions"].values()))["missing_waves"] == 1
    assert any("1 sound assets have no duration" in x and "sounds/fx/b.wav" in x for x in logs)


def test_empty_looking_fragment_is_read_again_in_each_byte_order(tmp_path, monkeypatch):
    """SE_Countered_victim02.fragment (393 bytes, big-endian) passes the
    little-endian chunk walk by accident, so the automatic test read it as an
    empty little-endian fragment: 3 sound events were missing on console."""
    import kapow_json as kj

    rel = "TNT/Fragments/SoundEvents/SE_x.fragment"
    f = tmp_path / "extracted" / rel
    f.parent.mkdir(parents=True)
    f.write_bytes(b"\x00" * 64)
    good = au.Frag(rel)
    good.add("AnimationEventWM", "{event SOUND at pos 0.29}")
    good_doc = {"instances": [good.cls], "nodes_full": good.nodes, "lossless": True}
    empty = {"instances": [], "nodes_full": [], "lossless": False}
    calls = []

    def to_json(name, data, order=None):
        calls.append(order)
        return good_doc if order == ">" else empty

    monkeypatch.setattr(kj, "load_fragment", lambda path: empty)
    monkeypatch.setattr(kj, "to_json", to_json)
    logs = []
    db = sm.SoundDB(str(tmp_path), logs.append)
    nodes = db.nodes(rel)
    assert [n.cls for n in nodes.values()] == ["AnimationEventWM"]
    assert db.reparsed == {rel: ">"} and calls == [">"]
    assert any("SE_x.fragment: read as big-endian" in x for x in logs)
    # a fragment that is empty in both orders stays empty, and that is logged
    monkeypatch.setattr(kj, "to_json", lambda name, data, order=None: empty)
    db = sm.SoundDB(str(tmp_path), logs.append)
    assert db.nodes(rel) == {} and db.reparsed == {}
    assert any("no node read in either byte order" in x for x in logs)
    # a fragment that reads cleanly as empty (lossless) is not second-guessed
    monkeypatch.setattr(kj, "load_fragment", lambda path: dict(empty, lossless=True))
    monkeypatch.setattr(kj, "to_json", lambda *a, **k: pytest.fail("must not be re-read"))
    assert sm.SoundDB(str(tmp_path)).nodes(rel) == {}


def test_textmeta_durations_on_ps3_sounds(text_extract):
    """text_meta.json had no duration on any PS3 sound (5,704 of 5,704 in Part 2)."""
    root = text_extract
    waves = {
        "/sounds/Speaks/V1/Taunt_01_uk.wav": 100,
        "/sounds/Speaks/V2/TAUNT_02_uk.wav": 400,
        "/sounds/Speaks/V1/Grunt_01.wav": 20,
    }
    for path, frames in waves.items():
        put_raw(root, path, ps3_sound(frames=frames)[0])
    logs = []
    meta = ta.build(str(root), log=logs.append)
    sounds = meta["subtitles"]["sounds"]
    a = sounds["/sounds/Speaks/V1/Taunt_01_uk.wav"]
    assert a["duration_s"] == 2.4 and all("shown" in ln for ln in a["lines"])
    assert all(s["duration_s"] is not None for s in sounds.values())
    assert not [x for x in logs if "no duration" in x]
    # a header nothing reads: null, no `shown`, and one line in the log
    put_raw(root, "/sounds/Speaks/V1/Taunt_01_uk.wav", bag() + b"\x00\x01\x09" + b"\x00" * 60)
    logs = []
    meta = ta.build(str(root), log=logs.append)
    a = meta["subtitles"]["sounds"]["/sounds/Speaks/V1/Taunt_01_uk.wav"]
    assert a["duration_s"] is None and not any("shown" in ln for ln in a["lines"])
    assert any("text_meta: WARNING: no duration for 1 of" in x for x in logs)
