"""Audio: multi-track music, sound headers, the sound metadata and the speech
side of the face rule.

Synthetic fixtures only.  They mirror what was read on the shipped files
(2026-10-03): a music stream is a chain of groups (one chunk per track) joined
by link records `[u32 m][u32 size x tracks]`, m = sum + 4 * (tracks + 1); a
sound header stores its own sample rate and, for PCM, the data right after its
byte count; an Entity value names a node of another fragment as
[name hash of the fragment's file stem, node id].
"""

import json
import os
import struct
import sys
import wave

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_meta as am
import anim_state_machine as asm
import face_rule as fr
import kapow_props
import watchmen_extract as wx

try:  # the module is new: every sound_meta test fails (not errors at import) on 1.3.0
    import sound_meta as sm
except ImportError:  # pragma: no cover
    sm = None


def need_sm():
    assert sm is not None, "wlib/sound_meta.py is missing"
    return sm


# ------------------------------------------------------------ stream builders
def vorbis_headers(ch=2, rate=48000, tag=0):
    ident = b"\x01vorbis" + struct.pack("<IBIiiiB", 0, ch, rate, 0, 0, 0, 0xB8) + b"\x01"
    return [ident, b"\x03vorbis" + bytes([tag]) * 9, b"\x05vorbis" + bytes([tag]) * 21]


def rec(packet, granule=0):
    """[32-byte packet header][packet]: dword 1 = length, u64 at +16 = granule."""
    return struct.pack("<IIIIQQ", 0, len(packet), 0, 0, granule, 0) + packet


def link(sizes, bo="<"):
    return struct.pack(bo + "%dI" % (len(sizes) + 1), sum(sizes) + 4 * (len(sizes) + 1), *sizes)


def pc_stream(ntracks, groups=3, per_chunk=3, plen=3000, ends=None):
    """-> (stream bytes, [packets per track]).  ends: per-track end sample
    stored with the track's last packet."""
    packets = []
    for k in range(ntracks):
        audio = [
            bytes([0x10 + 2 * k]) + bytes([(k * 31 + g * 7 + i) & 0xFF]) * (plen + 11 * k + i)
            for g in range(groups)
            for i in range(per_chunk)
        ]
        packets.append(vorbis_headers(tag=k) + audio)
    chunks = []  # [group][track] -> bytes
    for g in range(groups):
        row = []
        for k in range(ntracks):
            pk = packets[k][3 + g * per_chunk : 3 + (g + 1) * per_chunk]
            if g == 0:
                pk = packets[k][:3] + pk
            last = g == groups - 1
            b = b""
            for i, p in enumerate(pk):
                gran = ends[k] if ends and last and i == len(pk) - 1 else 0
                b += rec(p, gran)
            row.append(b)
        chunks.append(row)
    out = b""
    for g in range(groups):
        out += b"".join(chunks[g])
        nxt = chunks[g + 1] if g + 1 < groups else chunks[0]
        out += link([len(c) for c in nxt])
    return out, packets


def ogg_pages(data):
    """[(granule, header type, [packets])] of an Ogg file."""
    out, o = [], 0
    while o < len(data):
        assert data[o : o + 4] == b"OggS"
        htype = data[o + 5]
        gran = struct.unpack_from("<q", data, o + 6)[0]
        nseg = data[o + 26]
        lac = data[o + 27 : o + 27 + nseg]
        body = data[o + 27 + nseg : o + 27 + nseg + sum(lac)]
        pk, cur, p = [], b"", 0
        for n in lac:
            cur += body[p : p + n]
            p += n
            if n < 255:
                pk.append(cur)
                cur = b""
        out.append((gran, htype, pk))
        o += 27 + nseg + sum(lac)
    return out


def ogg_packets(data):
    return [p for _g, _h, pk in ogg_pages(data) for p in pk]


def descriptor(stream, tracks, order="<", trailer=None, sizes=None):
    """A `mediastream` descriptor header.  tracks: [(source, samples, ch, rate,
    [(cue name, sample)])]; trailer: bytes after every track record (console)."""

    def s(x):
        b = x.encode() + b"\x00"
        return struct.pack(order + "I", len(b)) + b

    n = len(tracks)
    h = struct.pack(order + "IiII", 7, -1, 0, n) + s(stream)
    h += link(sizes or [100 + k for k in range(n)], order)
    h += struct.pack(order + "II", 5, 0)
    for src, samples, ch, rate, cues in tracks:
        h += s(src) + struct.pack(order + "IIIIIiI", 0, samples, ch, rate, 0, -1, len(cues))
        for nm, pos in cues:
            h += s(nm) + struct.pack(order + "I", pos)
        h += trailer or b""
    return h


# -------------------------------------------------------- multi-track music
def test_pc_stream_is_split_at_the_link_records():
    raw, packets = pc_stream(3)
    tracks = wx.media_tracks_pc(raw)
    assert [t["packets"] for t in tracks] == packets
    # one byte short / one stray byte: not a clean chain -> the caller falls back
    assert wx.media_tracks_pc(raw[:-1]) is None
    assert wx.media_tracks_pc(raw + b"\x00") is None


def test_per_track_files_hold_only_their_own_packets_and_end_sample(tmp_path):
    probe, packets = pc_stream(2)
    computed = [wx._ogg_from_packets(p, True)[4] for p in packets]
    ends = [c - 7 for c in computed]
    raw, packets = pc_stream(2, ends=ends)
    name = "/derived_pc/sounds/music/a/Song_track0.mediastream_s"
    out = wx.decode_audio_tracks(raw, tmp_path, name)
    assert [t["index"] for t in out] == [0, 1]
    assert [t["file"] for t in out] == [
        "derived_pc/sounds/music/a/Song_track0.mediastream_s.ogg",
        "derived_pc/sounds/music/a/Song_track1.mediastream_s.ogg",
    ]
    for k, t in enumerate(out):
        data = (tmp_path / t["file"]).read_bytes()
        assert ogg_packets(data) == packets[k]
        pages = ogg_pages(data)
        # the stream's own end position is stamped on the last page, so a
        # decoder trims the last block: the track has its real length
        assert pages[-1][0] == ends[k] == t["samples"] and pages[-1][1] == 0x04
        assert t["channels"] == 2 and t["rate"] == 48000
        assert t["duration_s"] == round(ends[k] / 48000.0, 4)
    # the 1.3.0 file: every track's chunks appended in turn, one header set
    flat = tmp_path / "flat.ogg"
    assert wx.decode_audio(raw, flat, True)
    n_flat = len([p for p in ogg_packets(flat.read_bytes()) if p[0] not in (1, 3, 5)])
    assert n_flat >= sum(len(p) - 3 for p in packets)


def test_one_track_stream_keeps_its_name_and_ends_at_the_stored_position(tmp_path):
    _probe, packets = pc_stream(1)
    computed = wx._ogg_from_packets(packets[0], True)[4]
    raw, _packets = pc_stream(1, ends=[computed - 7])
    name = "/derived_pc/sounds/music/Menu_track0.mediastream_s"
    out = wx.decode_audio_tracks(raw, tmp_path / "t", name)
    old = tmp_path / "old.ogg"
    assert wx.decode_audio(raw, old, True)
    assert len(out) == 1 and out[0]["file"].endswith("Menu_track0.mediastream_s.ogg")
    new = (tmp_path / "t" / out[0]["file"]).read_bytes()
    # the stream's stored end position (0x8d29c0 shortens the last block to it), not the
    # computed block position the flat file ends at
    assert out[0]["samples"] == computed - 7
    pages = ogg_pages(new)
    assert pages[-1][0] == computed - 7 and pages[-1][1] == 0x04
    assert ogg_pages(old.read_bytes())[-1][0] == computed
    assert ogg_packets(new) == ogg_packets(old.read_bytes())


def test_track_file_names():
    n = "/a/b/Underground_track0.mediastream_s"
    assert wx.media_track_name(n, 3) == "/a/b/Underground_track3.mediastream_s"
    assert wx.media_track_name(n, 1, "Intro loop!") == (
        "/a/b/Underground_track1_Intro_loop.mediastream_s"
    )
    assert wx.media_track_name(n, 9, "none") == "/a/b/Underground_track9.mediastream_s"
    # a directory named like a track is left alone; no _track0 -> a suffix
    assert wx.media_track_name("/x_track0.d/song.mediastream_s", 2) == (
        "/x_track0.d/song_track2.mediastream_s"
    )


@pytest.mark.parametrize("order,trailer", [("<", None), (">", "ps3"), (">", "x360")])
def test_stream_descriptor_tracks_and_cue_points(order, trailer):
    tr = {
        None: b"",
        "ps3": struct.pack(">IIf", 2304512, 0x3E80, 0.5),
        "x360": struct.pack(">I3II", 3, 0, 1024, 2048, 75),
    }[trailer]
    h = b"\x00" * 24 + descriptor(
        "/derived_pc/sounds/Music/U/Under_track0.mediastream_s",
        [
            ("/sounds/Music/U/Under_track0.wav", 2304001, 2, 48000, [("click1", 9), ("end", 77)]),
            ("/sounds/Music/U/Under_track1.wav", 2304003, 2, 48000, []),
        ],
        order,
        tr,
        sizes=[51158, 43344],
    )
    d = wx.media_desc_from_header(h, order)
    assert d["stream"] == "/derived_pc/sounds/Music/U/Under_track0.mediastream_s"
    assert d["groups"] == 5 and d["first_group_sizes"] == [51158, 43344]
    assert [t["samples"] for t in d["tracks"]] == [2304001, 2304003]
    assert d["tracks"][0]["cue_points"] == [
        {"name": "click1", "sample": 9},
        {"name": "end", "sample": 77},
    ]
    assert d["tracks"][1]["source"].endswith("Under_track1.wav")
    assert d["tracks"][1]["cue_points"] == [] and d["tracks"][1]["rate"] == 48000
    # the 1.3.0 reader still gives the first track's numbers
    assert wx.media_meta_from_header(h, order)[1:] == (2, 48000, 2304001)
    assert wx.media_desc_from_header(b"\x00" * 64, order) is None


def ps3_seg(payload):
    return struct.pack(">I", len(payload)) + b"\x00" * 28 + payload


def test_ps3_stream_tracks(tmp_path):
    pay = [[b"\xff\xfb" + bytes([16 * k + g]) * (700 + 16 * k) for g in range(3)] for k in (0, 1)]
    g0 = [ps3_seg(pay[k][0]) for k in (0, 1)]
    g1 = [ps3_seg(pay[k][1]) + ps3_seg(pay[k][2]) for k in (0, 1)]  # two segments per chunk
    raw = b"".join(g0) + link([len(c) for c in g1], ">") + b"".join(g1)
    raw += link([len(c) for c in g0], ">")
    assert len(raw) >= 0x1000
    codec, tracks = wx.media_tracks_console(raw)
    assert codec == "mp3" and tracks == [b"".join(pay[0]), b"".join(pay[1])]
    # the single-file reader of 1.3.0 sees the same bytes, track after track per group
    assert len(wx._console_media_parse(raw)[1]) == sum(len(t) for t in tracks)
    name = "/derived_ps3/sounds/music/x/Song_track0.mediastream_s"
    out = wx.decode_console_audio(name, raw, tmp_path, None, None, lambda *a: None, tracks=True)
    assert [t["file"].rsplit("/", 1)[1] for t in out] == [
        "Song_track0.mediastream_s.mp3",
        "Song_track1.mediastream_s.mp3",
    ]
    assert (tmp_path / out[1]["file"]).read_bytes() == tracks[1]


def test_x360_stream_tracks_split_group_0_with_the_closing_link():
    def pkts(k, g, n):
        return b"".join(bytes([4 * (k + 1)]) + bytes([0xA0 + 16 * k + g]) * 2047 for _ in range(n))

    g0 = [pkts(0, 0, 2), pkts(1, 0, 1)]
    g1 = [pkts(0, 1, 1), pkts(1, 1, 2)]
    raw = b"".join(g0) + link([len(c) for c in g1], ">") + b"".join(g1)
    raw += link([len(c) for c in g0], ">")
    codec, tracks = wx.media_tracks_console(raw)
    assert codec == "xma" and tracks == [g0[0] + g1[0], g0[1] + g1[1]]
    # a closing link that does not add up to group 0: no split, no guess
    bad = raw[:-12] + link([2048, 2048], ">")
    assert wx.media_tracks_console(bad) is None


def test_extract_writes_one_file_per_track_and_flat_music_the_old_file(tmp_path):
    raw, packets = pc_stream(2, ends=None)
    src = tmp_path / "files" / "derived_pc" / "sounds" / "music"
    src.mkdir(parents=True)
    (src / "Song_track0.mediastream_s").write_bytes(raw)
    one, _p = pc_stream(1)
    (src / "Menu_track0.mediastream_s").write_bytes(one)
    new, flat = tmp_path / "new", tmp_path / "flat"
    assert wx.main([str(tmp_path / "files"), "-o", str(new), "--no-files", "--quiet"]) == 0
    args = [str(tmp_path / "files"), "-o", str(flat), "--no-files", "--quiet", "--flat-music"]
    assert wx.main(args) == 0
    d = "audio/derived_pc/sounds/music/"
    got = sorted(p.name for p in (new / d).iterdir())
    assert got == [
        "Menu_track0.mediastream_s.json",
        "Menu_track0.mediastream_s.ogg",
        "Song_track0.mediastream_s.json",
        "Song_track0.mediastream_s.ogg",
        "Song_track1.mediastream_s.ogg",
    ]
    for k in (0, 1):
        f = new / d / ("Song_track%d.mediastream_s.ogg" % k)
        assert ogg_packets(f.read_bytes()) == packets[k]
    side = json.loads((new / d / "Song_track0.mediastream_s.json").read_text())
    assert side["format"] == "watchmen-music-stream/1"
    assert [t["file"].rsplit("/", 1)[1] for t in side["tracks"]] == got[3:]
    assert side["tracks"][1]["cue_points"] == [] and side["setups"] == []
    # --flat-music: exactly the 1.3.0 output, no sidecars
    assert sorted(p.name for p in (flat / d).iterdir()) == [
        "Menu_track0.mediastream_s.ogg",
        "Song_track0.mediastream_s.ogg",
    ]
    ref = tmp_path / "ref.ogg"
    wx.decode_audio(raw, ref, True)
    assert (flat / d / "Song_track0.mediastream_s.ogg").read_bytes() == ref.read_bytes()
    # a one-track stream holds the same packets either way (its end position may differ)
    m = "Menu_track0.mediastream_s.ogg"
    assert ogg_packets((new / d / m).read_bytes()) == ogg_packets((flat / d / m).read_bytes())


# ------------------------------------------------------------ sound headers
def sound_header(ch=1, rate=44100, fmt=1, data=b"", samples=None, loop=0, is3d=1, orig=None):
    """A `sound` asset header: [type name][class id][one property record], then
    the fields the loader 0x449e40 reads."""
    h = struct.pack("<I", 6) + b"sound\x00" + struct.pack("<I", 0x1234)
    h += struct.pack("<5I", 0xA1B2C3D4, 0x11, 0x22, 0, 7)
    h += bytes([loop, is3d]) + struct.pack("<4I", ch, orig or rate, fmt, rate)
    if fmt == 1:
        n = len(data) // (2 * ch) if samples is None else samples
        return h + struct.pack("<2I", n, len(data)) + data + struct.pack("<I", 0)
    ba = 32
    h += struct.pack("<3I", (ba * rate * 128) & 0xFFFFFFFF, samples or 0, ba) + wx._COEFB
    return h + struct.pack("<I", len(data)) + data + struct.pack("<I", 0)


def ramp(frames, ch):
    return struct.pack("<%dh" % (frames * ch), *range(100, 100 + frames * ch))


def test_stereo_sound_takes_the_rate_of_its_header():
    pcm = ramp(64, 2)
    data, ch, rate = wx.decode_sfx(sound_header(2, 48000, 1, pcm, orig=48000))
    assert (ch, rate) == (2, 48000)
    blocks = b"".join(b"\x00" * 32 for _ in range(4))
    _d, ch, rate = wx.decode_sfx(sound_header(2, 43937, 2, blocks, samples=40))
    assert (ch, rate) == (2, 43937)
    # mono sounds are stored at 44100 whatever their source rate was
    _d, ch, rate = wx.decode_sfx(sound_header(1, 44100, 1, ramp(64, 1), orig=22050))
    assert (ch, rate) == (1, 44100)
    # a rate no sound has: the old constant, not a broken file
    assert wx.decode_sfx(sound_header(1, 3, 1, ramp(64, 1)))[2] == 44100


def test_pcm_data_starts_right_after_its_byte_count():
    pcm = ramp(64, 2)
    data, _ch, _rate = wx.decode_sfx(sound_header(2, 48000, 1, pcm))
    assert data == pcm  # 1.3.0 began 4 bytes (one stereo frame) late and ran into the cue count
    frames = struct.unpack("<128h", data)
    assert frames[0::2] == tuple(range(100, 228, 2)) and frames[1::2] == tuple(range(101, 228, 2))
    mono = ramp(50, 1)
    assert wx.decode_sfx(sound_header(1, 44100, 1, mono))[0] == mono


def test_sound_header_facts():
    i = wx.sfx_info(sound_header(2, 48016, 1, ramp(480, 2), loop=1, is3d=0, orig=48000))
    assert i["looping"] is True and i["is3d"] is False
    assert (i["channels"], i["rate"], i["original_rate"], i["codec"]) == (2, 48016, 48000, "pcm16")
    assert i["samples"] == 480 and i["duration_s"] == round(480 / 48016.0, 4)
    assert i["cue_points"] == []
    a = wx.sfx_info(sound_header(1, 44100, 2, b"\x00" * 64, samples=88200))
    assert a["codec"] == "ms-adpcm" and a["block_align"] == 32 and a["duration_s"] == 2.0
    assert a["looping"] is False and a["data_bytes"] == 64
    assert wx.sfx_info(b"\x00" * 12) is None


def test_loop_flag_as_smpl_chunk_only_on_request(tmp_path):
    pcm = ramp(100, 1)
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    wx.write_wav(pcm, 1, 44100, a)
    wx.write_wav(pcm, 1, 44100, b, loop=True)
    plain = a.read_bytes()
    looped = b.read_bytes()
    assert looped[: len(plain)][8:] == plain[8:] and len(looped) == len(plain) + 68
    assert struct.unpack_from("<I", looped, 4)[0] == len(looped) - 8
    assert looped[len(plain) : len(plain) + 4] == b"smpl"
    f = struct.unpack_from("<15I", looped, len(plain) + 8)
    assert f[2] == round(1e9 / 44100) and f[7] == 1  # sample period, one loop
    assert (f[11], f[12]) == (0, 99)  # forward loop over the whole sample
    w = wave.open(str(b), "rb")  # still a file every reader opens
    assert w.getnframes() == 100 and w.getframerate() == 44100
    w.close()


# ------------------------------------------------------------ sound metadata
class Frag:
    """A fragment JSON in the shape tree_from_json() reads.  Node ids count
    from 1 in every fragment, so they collide across fragments on purpose."""

    def __init__(self, rel):
        self.rel, self.cls, self.nodes, self.n = rel, {}, [], 0

    def add(self, cls, name, parent=None, **props):
        self.n += 1
        nid = "%08x" % self.n
        self.cls["str_" + nid] = [cls + "(Node)"]
        p = [["name", "string", name], ["siblingOrder", "int", self.n]]
        if parent:
            p.append(["logicalParent", "ref", {"ref": parent}])
        p += [[k, "x", v] for k, v in props.items()]
        self.nodes.append({"id": nid, "type": cls, "props": p})
        return nid

    def write(self, root):
        f = root / "extracted" / (self.rel + ".json")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"instances": [self.cls], "nodes_full": self.nodes}))


def stem_ref(stem, nid):
    return {"xref": ["%08x" % kapow_props.name_hash(stem), nid]}


def put_wave(root, path, seconds, loop=0):
    f = root / "extracted" / path.lstrip("/")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(sound_header(1, 44100, 2, b"\x00" * 64, samples=int(seconds * 44100), loop=loop))


SOUNDDB = "TNT/Fragments/SoundDb/SoundDb.fragment"
ENEMIES = "TNT/Fragments/Enemy/AllTypes.fragment"


@pytest.fixture
def sound_extract(tmp_path):
    """A SoundDb with a three-way random definition and a layered one, a
    footstep table, a speak group with a talk line and a grunt, one character,
    and a body class whose state fires SOUND / SPEAK / foot events -- inline
    and through a SoundEvents fragment."""
    for nm, sec in (("a", 0.5), ("b", 0.25), ("c", 1.0), ("line", 2.0), ("t1", 1.5), ("t2", 3.0)):
        put_wave(tmp_path, "/sounds/fx/%s.wav" % nm, sec, loop=nm == "c")
    put_wave(tmp_path, "/sounds/fx/grunt.wav", 0.4)
    db = Frag(SOUNDDB)
    grp = db.add("SoundGrp", "Combat")
    swish = db.add(  # id 2: the node itself is option 0
        "SoundDef",
        "swish",
        sound="/sounds/fx/a.wav",
        _iselectionmethod=1,
        m_esoundgroup={"ref": grp},
        _nmindelay=0.05,
        _nmaxdelay=0.1,
        randomPitchLength=10.0,
        minrange=5.0,
        maxrange=30.0,
    )
    db.add("SoundDef", "", swish, sound="/sounds/fx/b.wav", _iselectionmethod=3)
    db.add("SoundDef", "", swish, sound="/sounds/fx/c.wav", _iselectionmethod=3)
    hit = db.add("SoundDef", "hit", _iselectionmethod=4)  # id 5: all layers at once
    lay = db.add("SoundDef", "", hit, sound="/sounds/fx/a.wav", _iselectionmethod=2)
    db.add("SoundDef", "", lay, sound="/sounds/fx/c.wav", _iselectionmethod=3)
    db.add("SoundDef", "", hit, sound="/sounds/fx/b.wav", _iselectionmethod=3)
    pkg = db.add("SoundPackageCtrl", "CHARACTER_FOOT_FEMALE", m_ieffecttypes=91)
    for nm, surf in (("DEFAULT", 6), ("MATERIAL_CONCRETE_DRY", 34)):
        db.add(
            "SoundEffectType",
            nm,
            pkg,
            m_ieffecttypes=surf,
            m_eeffectsoundreference={"ref": swish},
        )
    db.add("SoundEffectType", "CARPET", pkg, m_ieffecttypes=73)
    db.write(tmp_path)

    en = Frag(ENEMIES)
    # node 1 of THIS fragment is a definition too: the same id as SoundDb's group
    line = en.add("SoundDef", "talk line", sound="/sounds/fx/line.wav", _iselectionmethod=3)
    two = en.add("SoundDef", "taunt", sound="/sounds/fx/t1.wav", _iselectionmethod=1)
    en.add("SoundDef", "", two, sound="/sounds/fx/t2.wav", _iselectionmethod=3)
    grunt = en.add("SoundDef", "grunt", sound="/sounds/fx/grunt.wav", _iselectionmethod=3)
    g = en.add("CharacterSpeakDefinitionUpdate", "DomSpeakDefinition")
    flags = dict(m_nrandom=1.0, m_ndelay=0.0, m_nquarantinetimemin=20.0, m_nquarantinetimemax=40.0)
    talk = en.add(  # category 1: an exclusive line
        "SpeakDefinition",
        "MELEE_ON_TARGET_A",
        g,
        m_ispeak=24,
        m_tallowmultipleevents=False,
        m_tignoreplayerspeakevents=True,
        m_tignorenoneplayerspeakevents=False,
        **flags,
    )
    en.add("SpeakVoiceDefinition", "Dom1", talk, m_espeaktyperef0={"ref": two})
    en.add("SpeakVoiceDefinition", "Dom2", talk, m_espeaktyperef0={"ref": line})
    shout = en.add(  # category 2: a grunt
        "SpeakDefinition",
        "DAMAGED_LIGHT_STUN",
        g,
        m_ispeak=35,
        m_tallowmultipleevents=True,
        m_tignoreplayerspeakevents=False,
        m_tignorenoneplayerspeakevents=False,
        **flags,
    )
    en.add("SpeakVoiceDefinition", "Dom1", shout, m_espeaktyperef0={"ref": grunt})
    never = en.add(  # category 0
        "SpeakDefinition",
        "TAUNT",
        g,
        m_ispeak=1,
        m_tallowmultipleevents=True,
        m_tignoreplayerspeakevents=True,
        m_tignorenoneplayerspeakevents=False,
        **flags,
    )
    en.add("SpeakVoiceDefinition", "Dom1", never, m_espeaktyperef0={"ref": grunt})
    en.write(tmp_path)

    cv = Frag("TNT/Fragments/CharacterVisual.fragment")
    fn = cv.add(
        "FragmentNode", "", assetName="/TNT/Fragments/CharacterVisual/En4CharVisual.fragment"
    )
    cv.write(tmp_path)
    vis = Frag("TNT/Fragments/CharacterVisual/En4CharVisual.fragment")
    v = vis.add("CharacterVisual", "EN4")
    vis.add("AnimationCtrlWM", "AnimCtrl", v, m_ianimationclassid=10)
    head = vis.add("Character", "HeadModel", v)
    vis.add("AnimationCtrlWM", "AnimCtrl", head, m_ianimationclassid=11)
    vis.write(tmp_path)

    ch = Frag("TNT/Fragments/Enemy/Dominatrices.fragment")
    csd = ch.add(
        "CharacterSoundDef",
        "CharacterSoundDef",
        m_espeakref=stem_ref("AllTypes", g),
        _elightattackeffect={"etag": 1},
    )
    ch.add(
        "CharacterDef",
        "{DOMINATRICE}",
        m_icharactertype=33,
        m_emodelfragment=stem_ref("CharacterVisual", fn),
        m_echaractersounddef={"ref": csd},
    )
    ch.write(tmp_path)

    se = Frag("TNT/Fragments/CharacterAnimation/SoundEvents/SE_clip_a.fragment")
    ev = dict(m_ieventtype=0, m_nvalue=0.0)
    se.add(
        "AnimationEventWM",
        "{event SOUND}",
        m_ianimationevent=9,
        m_nplaypos=0.5,
        _etarget00=stem_ref("SoundDb", swish),
        m_ivalue00=1,
        m_ttruth1=False,
        **ev,
    )
    se.add("AnimationEventWM", "{event foot}", m_ianimationevent=40, m_nplaypos=0.25, **ev)
    se.add(
        "AnimationEventWM",
        "{event SPEAK}",
        m_ianimationevent=37,
        m_nplaypos=0.75,
        m_ivalue00=35,
        m_ttruth1=True,
        **ev,
    )
    se.write(tmp_path)

    body = Frag("TNT/Fragments/CharacterAnimation/AnimationClassEnemy04.fragment")
    root = body.add("AnimationClassWM", "Enemy04AnimationClass", m_iclassid=10)
    # an inline definition whose id (2) is also SoundDb's `swish`
    own = body.add("SoundDef", "counter line", root, sound="/sounds/fx/line.wav")
    grp_n = body.add("AnimationStateGroupWM", "Counters", root)

    def state(name, clip, events):
        s = body.add("AnimationStateWM", name, grp_n, m_tislooping=False)
        layers = body.add("Folder", "Layers", s)
        b = body.add("AnimationBlendWM", "{MOTION_LAYER_1}", layers, m_nweight=1.0)
        body.add("AnimationSlotWM", "{%s.animation}" % clip, b, m_nweight=1.0)
        evf = body.add("Folder", "Events", s)
        for props in events:
            if "assetName" in props:
                body.add("FragmentNode", "", evf, **props)
            else:
                body.add("AnimationEventWM", "{event}", evf, **dict(ev, **props))
        return s

    state(
        "Counter_A",
        "clip_a",
        [
            dict(m_ianimationevent=9, m_nplaypos=0.25, _etarget00={"ref": own}, m_ttruth1=True),
            dict(m_ianimationevent=37, m_nplaypos=0.1, m_ivalue00=24, m_ttruth1=False),
            dict(assetName="/TNT/Fragments/CharacterAnimation/SoundEvents/SE_clip_a.fragment"),
        ],
    )
    state(
        "Counter_B",
        "clip_b",
        [
            dict(
                m_ianimationevent=9,
                m_nplaypos=0.25,
                _etarget00=stem_ref("AllTypes", two),
                m_ttruth1=True,
            ),
            dict(m_ianimationevent=37, m_nplaypos=0.5, m_ivalue00=35, m_ttruth1=False),
        ],
    )
    body.write(tmp_path)

    face = Frag("TNT/Fragments/CharacterAnimation/AnimationClassEnemy04Face.fragment")
    froot = face.add("AnimationClassWM", "Enemy04FaceAnimationClass", m_iclassid=11)
    alive = face.add("AnimationStateGroupWM", "Alive", froot)
    active = face.add("AnimationStateGroupWM", "Active", alive, **{asm.RANDOM_STATE: True})
    idles = face.add("AnimationStateGroupWM", "Idles", active, **{asm.RANDOM_STATE: True})
    talkg = face.add("AnimationStateGroupWM", "Talk", alive, **{asm.RANDOM_STATE: True})

    def fstate(name, parent, clip):
        s = face.add("AnimationStateWM", name, parent, m_neaseinduration=0.21)
        b = face.add("AnimationBlendWM", "{MOTION_LAYER_1}", s, m_nweight=1.0)
        face.add(
            "AnimationSlotWM",
            "{%s.animation}" % clip,
            b,
            m_nweight=1.0,
            targetAnimation="Animation/BS2/FACE/%s.animation" % clip,
        )
        return s

    def ftrans(owner, target, **crit):
        t = face.add("AnimationTransitionWM", "{trans}", owner, m_etostate={"ref": target})
        if crit:
            face.add("AnimationCriteriaWM", "{crit}", t, **crit)

    pt = dict(m_ianimationcriteria=asm.CRIT_PLAY_TIME, m_iintervaltype=2)
    ftrans(fstate("IdleA", idles, "MouthClosed_EyesOpen"), idles, m_nintervalmin=3.0, **pt)
    ftrans(fstate("OpenMouth", talkg, "MouthTalk_EyesAnger"), talkg, m_nintervalmin=0.15, **pt)
    ftrans(fstate("ClosedMouth", talkg, "MouthClosed_EyesOpen"), talkg, m_nintervalmin=0.15, **pt)
    act = dict(m_ianimationcriteria=asm.CRIT_ACTION)
    face.add(
        "AnimationCriteriaWM",
        "{crit}",
        talkg,
        m_ianimationaction=fr.A_START_SPEAK,
        m_tentryonly=True,
        **act,
    )
    ftrans(alive, talkg, m_ianimationaction=fr.A_START_SPEAK, **act)
    ftrans(alive, active, m_ianimationaction=fr.A_STOP_SPEAK, **act)
    face.nodes[0]["props"].append(["m_edefaultanimstate", "ref", {"ref": idles}])
    face.write(tmp_path)

    import test_anim_meta as tam

    tam.write_clip(tmp_path, "clip_a", ((0, 1, 0), (0, 1, 0)), duration=8.0)
    tam.write_clip(tmp_path, "clip_b", ((0, 1, 0), (0, 1, 0)), duration=8.0)
    return tmp_path


def test_speak_category_truth_table():
    s = need_sm()
    assert s.speak_category(True, False, False) == 2  # grunt: overlaps, no START_SPEAK
    assert s.speak_category(False, True, False) == 1
    assert s.speak_category(False, False, True) == 1
    assert s.speak_category(False, True, True) == 1
    for flags in ((False, False, False), (True, True, False), (True, False, True)):
        assert s.speak_category(*flags) == 0  # never played


def test_footstep_effect_type_by_character_type():
    s = need_sm()
    assert [s.foot_effect_type(0, k) for k in ("step", "jump", "stop")] == [53, 65, 62]
    assert [s.foot_effect_type(1, k) for k in ("step", "jump", "stop")] == [54, 66, 63]
    for female in (28, 33, 35):
        assert s.foot_effect_type(female, "step") == 91
    assert [s.foot_effect_type(34, k) for k in ("step", "jump", "stop")] == [33, 64, 61]


def test_references_resolve_per_fragment_not_by_node_id(sound_extract):
    s = need_sm()
    db = s.SoundDB(str(sound_extract))
    body = "TNT/Fragments/CharacterAnimation/AnimationClassEnemy04.fragment"
    # id 00000002 exists in SoundDb (swish), AllTypes (taunt) and the class (counter line)
    a = db.resolve({"ref": "00000002"}, body)
    b = db.resolve(stem_ref("SoundDb", "00000002"), body)
    c = db.resolve(stem_ref("AllTypes", "00000002"), body)
    assert (a[0], a[1].name) == (body, "counter line")
    assert (b[0], b[1].name) == (SOUNDDB, "swish")
    assert (c[0], c[1].name) == (ENEMIES, "taunt")
    # through a FragmentNode of the fragment reached so far
    v = db.resolve({"xref": ["%08x" % kapow_props.name_hash("CharacterVisual"), "00000001"]}, body)
    assert v[1].cls == "FragmentNode"
    inner = db.resolve(
        {"xref": ["%08x" % kapow_props.name_hash("CharacterVisual"), "00000001", "00000001"]},
        body,
    )
    assert inner[0].endswith("En4CharVisual.fragment") and inner[1].cls == "CharacterVisual"
    # an instance nobody knows: no guess by bare node id
    assert db.resolve({"xref": ["deadbeef", "00000002"]}, body) is None
    assert db.resolve({"etag": 1}, body) is None and db.unresolved == {"deadbeef": 1}


def test_play_tree_and_durations(sound_extract):
    s = need_sm()
    db = s.SoundDB(str(sound_extract))
    swish = db.definition_of(stem_ref("SoundDb", "00000002"), None)
    assert swish["ref"] == [SOUNDDB, "00000002"] and swish["group"] == "Combat"
    assert swish["play"]["mode"] == "one_of"
    assert swish["play"]["rule"] == "random_no_immediate_repeat"
    assert [o["wave"][-5:] for o in swish["play"]["options"]] == ["a.wav", "b.wav", "c.wav"]
    assert [o["duration_s"] for o in swish["play"]["options"]] == [0.5, 0.25, 1.0]
    assert [o["loop"] for o in swish["play"]["options"]] == [False, False, True]
    assert swish["duration_s"] == {"min": 0.25, "max": 1.0, "mean": round(1.75 / 3, 4)}
    assert swish["start_delay_s"] == [0.05, 0.1] and swish["n_waves"] == 3
    assert swish["play"]["options"][0]["random_pitch_pct"] == 10.0
    assert swish["play"]["options"][0]["range_m"] == [5.0, 30.0]
    hit = db.definition_of(stem_ref("SoundDb", "00000005"), None)
    # all_of: both layers start together; the first layer is a round robin of a / c
    assert hit["play"]["mode"] == "all_of" and len(hit["play"]["parts"]) == 2
    assert hit["play"]["parts"][0]["rule"] == "round_robin"
    assert hit["duration_s"]["min"] == 0.5 and hit["duration_s"]["max"] == 1.0
    assert s.fixed_wave(swish) is None and s.fixed_wave(hit) is None
    line = db.definition_of({"ref": "00000001"}, ENEMIES)
    assert s.fixed_wave(line) == ("/sounds/fx/line.wav", 2.0)


def test_sound_meta_tables(sound_extract):
    s = need_sm()
    meta = s.build(str(sound_extract), anim=am.build(str(sound_extract)))
    assert meta["format"] == "watchmen-sound-meta/1"
    assert set(meta["evidence"]) >= {"definitions", "classes", "speak_groups", "footsteps"}
    c = meta["characters"]["Dominatrices"]
    assert c["character_type"] == 33 and c["body_class"] == "Enemy04"
    assert c["body_class_id"] == 10 and c["face_class_id"] == 11
    assert c["body_class_basis"].startswith("data:")
    assert c["footstep_effect_types"] == {"step": 91, "jump": 92, "stop": 93}
    g = meta["speak_groups"][c["speak_group"]]
    assert {k: v["category"] for k, v in g["speaks"].items()} == {"24": 1, "35": 2, "1": 0}
    assert [v["name"] for v in g["speaks"]["24"]["voices"]] == ["Dom1", "Dom2"]
    assert g["speaks"]["24"]["voices"][0]["duration_s"] == {"min": 1.5, "max": 3.0, "mean": 2.25}
    assert g["speaks"]["24"]["duration_s"] == {"n": 3, "min": 1.5, "max": 3.0, "mean": 2.1667}
    assert g["speaks"]["24"]["start_speak"] and not g["speaks"]["35"]["start_speak"]
    assert not g["speaks"]["1"]["plays"]
    # the state: its own events and those of its SoundEvents fragment, in time order
    cls = meta["classes"]["Enemy04"]
    assert cls["characters"] == ["Dominatrices"]
    st = {x["state"]: x for x in cls["states"]}
    ev = st["Counter_A"]["events"]
    assert [(e["event"], e["t_s"], e["source"]) for e in ev] == [
        ("SPEAK", 0.8, "state"),
        ("SOUND", 2.0, "state"),
        ("RIGHT_FOOT_DOWN", 2.0, "SE_clip_a.fragment"),
        ("SOUND", 4.0, "SE_clip_a.fragment"),
        ("SPEAK", 6.0, "SE_clip_a.fragment"),
    ]
    assert ev[0]["speak"] == "MELEE_ON_TARGET_A"
    assert ev[0]["category_by_character"] == {"Dominatrices": 1}
    body = "TNT/Fragments/CharacterAnimation/AnimationClassEnemy04.fragment"
    assert ev[1]["definition"] == [body, "00000002"] and ev[1]["speak_flag"] is True
    assert ev[1]["wave"] == "/sounds/fx/line.wav" and ev[1]["duration_s"]["max"] == 2.0
    assert ev[2]["footstep"] == "step"
    assert ev[3]["definition"] == [SOUNDDB, "00000002"] and ev[3]["position"] == "follow"
    assert ev[3]["n_waves"] == 3 and "wave" not in ev[3]
    assert ev[4]["stops_current_speech_first"] is True
    assert ev[4]["category_by_character"] == {"Dominatrices": 2}
    # every definition is in the table under '<fragment>#<id>'
    assert meta["definitions"][SOUNDDB + "#00000002"]["name"] == "swish"
    assert meta["definitions"][body + "#00000002"]["name"] == "counter line"
    # footsteps: effect type x surface, rows that share a definition are merged
    row = meta["footsteps"]["rows"]["91"]
    assert row["name"] == "CHARACTER_FOOT_FEMALE" and len(row["by_surface"]) == 1
    assert row["by_surface"][0]["surface_ids"] == [6, 34]
    assert row["by_surface"][0]["definition"] == [SOUNDDB, "00000002"]
    # face: one fixed-wave talk event; the category-1 line with its length per voice
    ft = meta["face_talk"]["Enemy04"]
    assert [(x["state"], x["fixed"], x["talk_s"]) for x in ft["fixed_talk_events"]] == [
        ("Counter_A", True, 2.0),
        ("Counter_B", False, None),
    ]
    assert [x["speak"] for x in ft["line_events"]] == ["MELEE_ON_TARGET_A"]
    assert list(ft["lines"]["Dominatrices"]) == ["24"]
    assert ft["lines"]["Dominatrices"]["24"]["voices"][1]["talk_s"]["max"] == 2.0
    assert ft["closed_mouth_speak_ids"]["Dominatrices"] == [1, 35]
    assert meta["unresolved_instances"] == {}


def test_music_setup_track_names_and_states():
    s = need_sm()
    f = Frag("Levels/L/Sound/MusicSetup_level_L.fragment")
    setup = f.add("MusicSetup", "Underground", m_tstartonsceneactivated=True)
    f.add(
        "MusicStreamSlot",
        "MusicStreamSlot",
        setup,
        streamingSound="/sounds/Music/U/Under_track0.wav",
        volume=0.76,
        track0="Percussion",
        track1="Intro_loop",
        track2="",
    )
    cont = f.add("MusicIntensityContainer", "c", setup)
    trig = f.add("MusicTrigger", "LevelIntensity1", setup, m_nminplaytime=20.0, m_nmaxplaytime=40.0)
    f.add("MusicIntensityDefinition", "A", cont, _emusicintensitylevel01={"ref": trig})
    f.add("MusicTrackCtrl", "", trig, track_index=0, volume=0.48, fade_time=0.41, change_on_cue=0)
    f.add("MusicTrackCtrl", "", trig, track_index=1, volume=0.0, fade_time=0.41, change_on_cue=7)
    nodes = asm.tree_from_json({"instances": [f.cls], "nodes_full": f.nodes})[1]
    (m,) = s.music_setups(nodes, f.rel)
    assert m["setup"] == "Underground" and m["track_names"] == ["Percussion", "Intro_loop"]
    assert m["stream_asset"] == "/sounds/Music/U/Under_track0.wav"
    (st,) = m["states"]
    assert st["name"] == "LevelIntensity1" and st["intensity_levels"] == [1]
    assert (st["min_play_s"], st["max_play_s"]) == (20.0, 40.0)
    assert [(t["track"], t["volume"], t["fade_s"]) for t in st["tracks"]] == [
        (0, 0.48, 0.41),
        (1, 0.0, 0.41),
    ]
    assert s.track_labels([m]) == {"sounds/music/u/under_track0.wav": ["Percussion", "Intro_loop"]}
    assert s.music_setups_from_bytes(b"no slot here") == []


# ---------------------------------------------------------- anim_meta events
def test_anim_meta_events_keep_the_sound_arguments(sound_extract):
    m = am.build(str(sound_extract))
    st = {s["name"]: s for s in m["classes"]["Enemy04"]["states"]}
    ev = {e["name"]: e for e in st["Counter_A"]["events"] if "source" not in e}
    assert ev["SOUND"]["_etarget00"] == {"ref": "00000002"} and ev["SOUND"]["m_ttruth1"] is True
    # the events of the state's SoundEvents fragment are the state's own, marked with it
    se = [e for e in st["Counter_A"]["events"] if e.get("source")]
    assert {e["source"] for e in se} == {"SE_clip_a.fragment"}
    assert sorted(e["name"] for e in se) == ["RIGHT_FOOT_DOWN", "SOUND", "SPEAK"]
    assert ev["SPEAK"]["m_ivalue00"] == 24 and ev["SPEAK"]["m_ttruth1"] is False
    b = {e["name"]: e for e in st["Counter_B"]["events"]}
    assert b["SOUND"]["_etarget00"] == stem_ref("AllTypes", "00000002")
    # the clip table carries the same records
    assert any("_etarget00" in e for e in m["clips"]["clip_a"]["events"])


# ------------------------------------------------------------- the face rule
def test_face_talk_segment_ends_with_a_fixed_wave(sound_extract):
    m = am.build(str(sound_extract))
    assert m["face_format"] == fr.FACE_FORMAT == "watchmen-face/2"
    st = {s["name"]: s for s in m["classes"]["Enemy04"]["states"]}
    a = st["Counter_A"]["face"]
    (start,) = [i for i in a["inputs"] if i["input"] == "START_SPEAK"]
    assert start["t_s"] == 2.0 and start["talk_s"] == 2.0
    assert start["sound"]["wave"] == "/sounds/fx/line.wav"
    assert [(s["from_s"], s["to_s"], s["face_state"]) for s in a["track"]] == [
        (0.0, 2.0, "IDLE"),
        (2.0, 4.0, "TALK"),
        (4.0, None, "IDLE"),
    ]
    talk = a["track"][1]
    assert talk["talk"]["talk_s"] == 2.0 and talk["talk"]["ends_s"] == 4.0
    assert "sound_dependent" not in talk and a["confidence"] == "high"
    # the SPEAK event of a category-1 line: a note, never an input
    note, se_note = a["notes"]  # the state's own SPEAK, then its SoundEvents fragment's
    assert se_note["t_s"] > note["t_s"] and "speak_id" in se_note
    assert note["speak_id"] == 24 and note["opens_mouth_for"] == ["Dominatrices"]
    # Counter_B: the definition draws one of two waves -> the end stays open
    b = st["Counter_B"]["face"]
    (start,) = [i for i in b["inputs"] if i["input"] == "START_SPEAK"]
    assert "talk_s" not in start and start["sound"]["n_waves"] == 2
    assert b["track"][-1]["face_state"] == "TALK" and b["track"][-1]["to_s"] is None
    assert b["track"][-1]["sound_dependent"] and b["confidence"] == "low"
    # its SPEAK event is a grunt (category 2): no START_SPEAK, no talk segment
    assert [i["input"] for i in b["inputs"]] == ["START_SPEAK"]
    assert b["notes"][0]["category_by_character"] == {"Dominatrices": 2}
    assert b["notes"][0]["opens_mouth_for"] == []
    # the AI-requested lines: talk-clip lengths per voice instead of a baked segment
    tc = m["face"]["talk_clips"]["characters"]["Dominatrices"]
    assert tc["face_class"] == "Enemy04Face" and list(tc["lines"]) == ["24"]
    assert [v["talk_s"]["max"] for v in tc["lines"]["24"]["voices"]] == [3.0, 2.0]
    assert tc["closed_mouth_speak_ids"] == [1, 35]


def test_fixed_talk_is_baked_as_a_seeded_talk_cycle(sound_extract):
    m = am.build(str(sound_extract))
    fclass = m["face"]["classes"]["Enemy04Face"]
    c = fr.choose_track(m, "clip_a", fclass["pose_family"])
    sched, skipped = fr.pose_schedule(c, fclass, "clip_a", lambda pp: pp * 8.0, False, 8.0)
    assert skipped == []
    talk = [x for x in sched if 2.0 - 1e-6 <= x[0] < 4.0 - 1e-6]
    assert talk[0][0] == pytest.approx(2.0) and len(talk) >= 5
    assert {p for _t, p, _e in talk} == {"MouthTalk_EyesAnger", "MouthClosed_EyesOpen"}
    gaps = [b[0] - a[0] for a, b in zip(talk, talk[1:])]
    assert min(gaps) >= 0.15 - 1e-6  # a member is held for its min time, then re-rolled
    assert all(e == 0.21 for _t, _p, e in talk)
    # back on the idle pose when the wave has ended, and nothing after it
    assert sched[-1][1] == "MouthClosed_EyesOpen" and sched[-1][0] == pytest.approx(4.0)
    assert sched == fr.pose_schedule(c, fclass, "clip_a", lambda pp: pp * 8.0, False, 8.0)[0]
    # the open-ended talk of Counter_B is still left on the idle pose
    c2 = fr.choose_track(m, "clip_b", fclass["pose_family"])
    s2, skipped2 = fr.pose_schedule(c2, fclass, "clip_b", lambda pp: pp * 8.0, False, 8.0)
    assert {p for _t, p, _e in s2} == {"MouthClosed_EyesOpen"}
    assert [x["face_state"] for x in skipped2] == ["TALK"]


def test_stop_speak_input_ends_the_talk_state(sound_extract):
    path = str(
        sound_extract
        / "extracted/TNT/Fragments/CharacterAnimation/AnimationClassEnemy04Face.fragment"
    )
    root, _nodes = fr.load_face_class(path)
    open_end = fr.simulate(root, 4.0, inputs=[(1.0, "START_SPEAK", 0)])
    assert [(s["from_s"], s["to_s"], s["face_state"]) for s in open_end][-1] == (1.0, None, "TALK")
    segs = fr.simulate(root, 4.0, inputs=[(1.0, "START_SPEAK", 0), (2.5, "STOP_SPEAK", 0)])
    assert [(s["from_s"], s["to_s"], s["face_state"]) for s in segs] == [
        (0.0, 1.0, "IDLE"),
        (1.0, 2.5, "TALK"),
        (2.5, None, "IDLE"),
    ]


# ----------------------------------------------------------------------- CLI
def test_soundmeta_command_and_characters_sidecar(sound_extract, tmp_path, capsys):
    import watchmen

    out = tmp_path / "sm.json"
    assert watchmen.main(["watchmen", "soundmeta", str(sound_extract), str(out)]) == 0
    meta = json.loads(out.read_text())
    assert meta["format"] == "watchmen-sound-meta/1"
    # event times come from the animation table built on the fly
    st = meta["classes"]["Enemy04"]["states"][0]
    assert st["duration_s"] == 8.0 and st["events"][0]["t_s"] is not None
    assert "definitions" in capsys.readouterr().out
    assert watchmen.main(["watchmen", "soundmeta", str(sound_extract)]) == 2
    d = tmp_path / "chars"
    p = watchmen.write_sound_meta(str(sound_extract), str(d))
    assert p == str(d / "sound_meta.json")
    assert json.loads((d / "sound_meta.json").read_text())["format"] == meta["format"]
    # an extract without sounds: nothing written, nothing raised
    empty = tmp_path / "empty"
    (empty / "extracted").mkdir(parents=True)
    assert watchmen.write_sound_meta(str(empty), str(tmp_path / "none")) is None
    assert not (tmp_path / "none" / "sound_meta.json").exists()
