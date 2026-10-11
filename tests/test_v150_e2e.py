"""End to end: `watchmen extract --glb --quiet` on a tiny synthetic .naz that holds
every kind of asset the extractor decodes.

    block pair       textures (DXT1 + BC5 normal, DXT3 with alpha), a skinned
                     body model (scan path) and a rigid one (exact header), a
                     PCM and an MS-ADPCM sound, a fragment, a clip
    loose entry      a Vorbis music stream (.mediastream_s)

The archive is read one block at a time (1.5.0), --quiet leaves stdout empty
and every output kind is checked against what was put in.  Builders are those
of test_p1_formats, test_p2_part1, test_formats_v2, test_v120_regressions,
test_p2_console_chars, test_p3_part1_model, test_audio_v2, test_v150_audio and
test_fullextract.
"""

import json
import struct
import zlib

import numpy as np
from PIL import Image

import watchmen
import watchmen_extract as we
import test_audio_v2 as ta
import test_formats_v2 as tf
import test_fullextract as tfe
import test_p1_formats as tp1
import test_p2_console_chars as tc
import test_p2_part1 as tpp
import test_p3_part1_model as tm
import test_v120_regressions as tv
import test_v150_audio as tva
from conftest import build_clip_header, parse_glb

RED, GREEN, BLUE = 0xF800, 0x07E0, 0x001F


def _dxt1(c565, blocks):
    return struct.pack("<HHI", c565, c565, 0) * blocks


def _dxt3(alpha_nibble, c565, blocks):
    a = bytes([alpha_nibble | (alpha_nibble << 4)]) * 8
    return (a + struct.pack("<HHI", c565, c565, 0)) * blocks


def _bc5(x, y, blocks):
    return (bytes([y, y, 0, 0, 0, 0, 0, 0]) + bytes([x, x, 0, 0, 0, 0, 0, 0])) * blocks


class _Block:
    """Entries of one block: header blobs and streams zlib-compressed as the
    engine stores them (every type but mediastream)."""

    def __init__(self):
        self.entries, self.own = [], b""

    def add(self, name, tname, header, stream=None):
        pair = None
        if stream is not None:
            sb = zlib.compress(stream)
            pair = (len(self.own), len(sb))
            self.own += sb
        self.entries.append((name, we._name_hash(tname), zlib.compress(header), pair))

    def halves(self):
        return tpp._block(self.entries), self.own


def _archive(tmp_path):
    b = _Block()
    # textures: DXT1 diffuse + BC5 normal, and a DXT3 layer with explicit alpha
    tex1 = tf._tex_header(
        [({0: tf._tex_desc(8, 8, 5, 1), 1: tf._tex_desc(8, 8, 9, 1)}, "/data/art/x/Crate.bmp")]
    )
    b.add("/art/x/Crate.bmp", "Texture", tex1, _dxt1(RED, 4) + _bc5(200, 60, 4))
    tex3 = tf._tex_header([({0: tf._tex_desc(8, 8, 6, 1, alpha=1)}, "/data/art/x/Glass.bmp")])
    b.add("/art/x/Glass.bmp", "Texture", tex3, _dxt3(0x8, BLUE, 4))
    # a skinned body model (leg bones in its node table; scan path: no exact layout)
    joints = [(i % 5, 0, 0, 0) for i in range(8)]
    mh, ms = tv.skinned_model("<", joints)
    b.add("/art/chars/Body.model", "modelRes", tc._cls("<") + mh, ms)
    # a rigid model in the exact Part 2 header layout (static GLB with its vertex attributes)
    sh, ss = tm.build("<", "part2")
    b.add("/art/props/Crate.model", "modelRes", sh, ss)
    # sounds: PCM inline in the header, and MS-ADPCM
    pcm = ta.ramp(64, 1)
    b.add("/sounds/sfx/Beep.wav", "sound", ta.sound_header(ch=1, rate=22050, data=pcm))
    blk = tva._block(0, 16, 10, 5, [1, 2] * 25)
    b.add("/sounds/sfx/Hit.wav", "sound", tva._adpcm_sound(blk, 52))
    # a fragment and a clip
    frag = tfe._fragment(tfe._inst(0x10, "Crate_01"))
    b.add("/fragments/Crate.fragment", "fragment", frag)
    b.add("/Animation/EN4/EN4_Idle.animation", "animation", build_clip_header(4, 0.1))
    h, s = b.halves()
    music, packets = ta.pc_stream(1)
    naz = tp1._naz(
        tmp_path,
        [
            ("Levels/Test/Test.block_h_z", h, 0),
            ("Levels/Test/Test.block_s_z", s, 0),
            ("sounds/music/Song_track0.mediastream_s", music, 0),
        ],
    )
    return naz, pcm, packets


def test_extract_every_asset_kind(tmp_path, capsys):
    naz, pcm, packets = _archive(tmp_path)
    out = tmp_path / "out"
    rc = watchmen.main(["watchmen.py", "extract", str(naz), str(out), "--glb", "--quiet"])
    io_ = capsys.readouterr()
    assert rc == 0, io_.err
    assert io_.out == ""  # --quiet
    assert "Traceback" not in io_.err

    # textures, pixel for pixel
    t = out / "textures" / "art" / "x"
    crate = sorted(p.name for p in (t / "Crate.bmp").glob("*.png"))
    assert crate == ["0_diffuse_8x8_DXT1.png", "1_normal_8x8_ATI2.png"]
    d = np.asarray(Image.open(t / "Crate.bmp" / crate[0]))
    assert (d[..., :3] == (255, 0, 0)).all()
    n = np.asarray(Image.open(t / "Crate.bmp" / crate[1]))
    assert (n[..., 0] == 200).all() and (n[..., 1] == 60).all()  # X first (ATI2 blocks swapped)
    glass = sorted(p.name for p in (t / "Glass.bmp").glob("*.png"))
    assert glass == ["0_diffuse_8x8_DXT3.png"]
    g = np.asarray(Image.open(t / "Glass.bmp" / glass[0]))
    assert g.shape == (8, 8, 4) and (g[..., 3] == 0x88).all() and (g[..., :3] == (0, 0, 255)).all()

    # the skinned model: OBJ and a rigged GLB
    m = out / "models" / "art" / "chars"
    assert (m / "Body.model.obj").exists()
    glb = parse_glb(m / "Body.model.glb")
    prim = glb.j["meshes"][0]["primitives"][0]
    assert len(glb.accessor(prim["attributes"]["POSITION"])) == 8
    (skin,) = glb.j["skins"]
    J = glb.accessor(prim["attributes"]["JOINTS_0"])
    W = glb.accessor(prim["attributes"]["WEIGHTS_0"])
    assert np.allclose(W[:, 0], 1.0)
    # each vertex on the joint its skin names (the joints are named after the header's nodes)
    names = [glb.j["nodes"][skin["joints"][j]]["name"] for j in J[:, 0]]
    assert len(set(names)) == 5 and glb.j["asset"]["extras"]["watchmen"]["rig"]["mode"]

    static = parse_glb(out / "models" / "art" / "props" / "Crate.model.glb")
    assert "skins" not in static.j and static.j["meshes"]
    attrs = static.j["meshes"][0]["primitives"][0]["attributes"]
    assert {"POSITION", "NORMAL", "TEXCOORD_0"} <= set(attrs)
    meta = json.loads((out / "models" / "art" / "props" / "Crate.model.model.json").read_text())
    assert meta.get("header_layout", "part2") == "part2" and meta["lod_count"] == 2

    # sounds
    import wave

    with wave.open(str(out / "audio" / "sounds" / "sfx" / "Beep.wav"), "rb") as w:
        assert (w.getframerate(), w.getnchannels()) == (22050, 1)
        assert w.readframes(w.getnframes()) == pcm
    with wave.open(str(out / "audio" / "sounds" / "sfx" / "Hit.wav"), "rb") as w:
        assert w.getnframes() == 52
        got = w.readframes(52)
    assert got == we._adpcm_mono(tva._block(0, 16, 10, 5, [1, 2] * 25), 32)[:52].tobytes()
    info = json.loads((out / "audio" / "sound_info.json").read_text())
    assert {"sounds/sfx/Beep.wav", "sounds/sfx/Hit.wav"} <= set(info["sounds"])

    # the music stream: one Ogg with the stored packets
    ogg = out / "audio" / "sounds" / "music" / "Song_track0.mediastream_s.ogg"
    assert ta.ogg_packets(ogg.read_bytes()) == packets[0]

    # the fragment JSON and the raw clip
    fj = json.loads((out / "extracted" / "fragments" / "Crate.fragment.json").read_text())
    assert fj["lossless"] is True and fj["named_instances"] == ["Crate_01"]
    clip = out / "extracted" / "Animation" / "EN4" / "EN4_Idle.animation"
    assert clip.read_bytes() == build_clip_header(4, 0.1)


def test_extract_reads_the_synthetic_archive_one_block_at_a_time(tmp_path, monkeypatch):
    """The streaming path: no archive entry is kept once its block is done."""
    from test_v150_streaming import _Tracked

    naz, _pcm, _packets = _archive(tmp_path)
    real_read = we.naz_read
    monkeypatch.setattr(we, "naz_read", lambda p, e: _Tracked(real_read(p, e)))
    _Tracked.alive = 0
    assert we.main([str(naz), "-o", str(tmp_path / "o"), "--quiet", "--no-models"]) == 0
    assert _Tracked.alive == 0
