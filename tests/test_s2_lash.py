"""Restored content: the eyelash strips of the generic female heads
(watchmen_extract.LASH_RESTORE).

    layout        the small stored layout is recognised by its own numbers; any
                  other set of 72 UVs is left alone
    transform     each strip is scaled and moved: uv' = scale * uv + shift
    decoders      _decode_sub (PC and console vertex layout), decode_model_mesh
    files         OBJ `vt`, the .model.json note, asset.extras of a character GLB
    switch        WATCHMEN_NO_SYNTH=1 writes the stored UVs and no note

Synthetic fixtures only: four blocks of 18 UVs inside the stored box."""

import json
import os
import struct
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import variant_glb as vg
import watchmen_extract as we

import test_formats_v2 as tf
from conftest import parse_glb

#: the corners of the stored layout, as the half floats of the files
U_MIN, U_MAX = (float(np.array([b], "<u2").view("<f2")[0]) for b in (0x1AC7, 0x2BEE))
V_MIN, V_MAX = (float(np.array([b], "<u2").view("<f2")[0]) for b in (0x3643, 0x3760))
NV, STRIP = 72, 18


def _block(upper):
    """18 UVs of one strip: mean v 0.4137 (upper) or 0.4494 (lower)."""
    if upper:
        vs = [V_MIN] + [0.415] * 16 + [0.4405]
        us = [0.0072 + 0.0024 * i for i in range(STRIP)]
    else:
        vs = [0.4373] + [0.4493] * 16 + [V_MAX]
        us = [U_MIN] + [0.006 + 0.003 * i for i in range(16)] + [U_MAX]
    return list(zip(us, vs))


def _stored():
    return _block(True) + _block(False) + _block(True) + _block(False)


def _half(uv):
    """UVs as the file's half floats give them back."""
    return [tuple(float(x) for x in np.array(p, "<f2")) for p in uv]


@pytest.fixture(autouse=True)
def synth_on(monkeypatch):
    monkeypatch.delenv("WATCHMEN_NO_SYNTH", raising=False)


def test_the_fixture_is_the_stored_box():
    uv = np.array(_half(_stored()))
    assert np.allclose(uv.min(0), we.LASH_RESTORE["stored_uv_min"], atol=1e-5)
    assert np.allclose(uv.max(0), we.LASH_RESTORE["stored_uv_max"], atol=1e-5)
    assert (U_MIN, V_MIN) < (0.0034, 0.3915)


def test_the_layout_is_recognised_by_its_own_numbers():
    uv = _half(_stored())
    assert we.lash_strips(uv) == ["upper", "lower", "upper", "lower"]
    assert we.lash_strips(uv[:-1]) is None  # 71 vertices
    assert we.lash_strips(None) is None
    assert we.lash_strips([(u + 0.01, v) for u, v in uv]) is None  # another box
    assert we.lash_strips([(u, v + 0.001) for u, v in uv]) is None
    assert we.lash_strips([(u * 11.0, v) for u, v in uv]) is None  # a full-size layout
    # the same box with blocks that are neither strip
    mixed = uv[:9] + uv[18:27] + uv[9:18] + uv[27:]
    assert we.lash_strips(mixed) is None


def test_each_strip_is_scaled_and_moved():
    uv = _half(_stored())
    out = we.lash_restored_uvs(uv)
    assert len(out) == NV
    up, lo = we.LASH_RESTORE["strips"]["upper"], we.LASH_RESTORE["strips"]["lower"]
    assert (up[1], up[2]) == (11.7691, (0.4736, -4.4107))
    assert (lo[1], lo[2]) == (11.5133, (-0.0358, -4.5707))
    for i, ((u, v), (u2, v2)) in enumerate(zip(uv, out)):
        _, s, (du, dv) = up if (i // STRIP) % 2 == 0 else lo
        assert u2 == pytest.approx(s * u + du) and v2 == pytest.approx(s * v + dv)
    a = np.array(out)
    # on the painted lashes: the range Twilight Lady's strips have (-0.002..1.045, 0.196..0.779)
    assert -0.01 < a[:, 0].min() < 0.02 and 1.0 < a[:, 0].max() < 1.06
    assert 0.18 < a[:, 1].min() < 0.21 and 0.76 < a[:, 1].max() < 0.80
    assert we.lash_restored_uvs(out) is None  # a second pass changes nothing
    assert we.lash_restored_uvs([(0.5, 0.5)] * NV) is None


def test_the_restored_layout_is_told_from_the_stored_one():
    uv = _half(_stored())
    out = we.lash_restored_uvs(uv)
    assert we.lash_is_restored(out) and we.lash_is_restored(np.array(out, np.float32))
    assert not we.lash_is_restored(uv) and not we.lash_is_restored(out[:-1])
    assert not we.lash_is_restored(None)
    assert not we.lash_is_restored(np.zeros((NV, 4)))  # not a UV array
    assert not we.lash_is_restored([(0.5, 0.5)] * NV)


def _pc_buffer(uv):
    return b"".join(
        tf._vertex(6, (0.01 * i, 0.3, 0.0), uv=p, joints=(1, 2, 3, 4)) for i, p in enumerate(uv)
    )


def _console_buffer(uv):
    out = b""
    for i, p in enumerate(uv):
        out += struct.pack(">3f", 0.01 * i, 0.3, 0.0) + struct.pack(">I", 511 << 22)
        out += (
            b"\xff" * 4
            + struct.pack(">2e", *p)
            + bytes(8)
            + bytes(4)
            + struct.pack(">4e", 1, 0, 0, 0)
        )
    return out


@pytest.mark.parametrize("be", [False, True])
def test_decode_sub_restores_on_both_vertex_layouts(be, monkeypatch):
    uv = _stored()
    buf, stride = (_console_buffer(uv), 44) if be else (_pc_buffer(uv), 56)
    assert len(buf) == NV * stride
    noted = []
    _v, _n, got = we._decode_sub(buf, 0, NV, stride, be, noted)
    assert noted == ["eyelash_uvs"]
    assert got == we.lash_restored_uvs(_half(uv))
    assert we._decode_sub(buf, 0, NV, stride, be)[2] == got  # the list is optional
    monkeypatch.setenv("WATCHMEN_NO_SYNTH", "1")
    noted = []
    assert we._decode_sub(buf, 0, NV, stride, be, noted)[2] == _half(uv) and noted == []


def test_decode_sub_leaves_every_other_buffer_alone():
    uv = [(0.01 * i, 0.5) for i in range(NV)]
    noted = []
    assert we._decode_sub(_pc_buffer(uv), 0, NV, 56, False, noted)[2] == _half(uv)
    assert noted == []
    short = _stored()[:40]
    assert we._decode_sub(_pc_buffer(short), 0, 40, 56)[2] == _half(short)


@pytest.fixture
def lash_model(monkeypatch):
    """A head model whose second submesh is the eyelash buffer (z = 7 marks it)."""
    quad = tf._quad

    def geometry(fmt, z, **kw):
        if z != 7.0:
            return quad(fmt, z, **kw)
        kw.pop("color", None)
        vb = b"".join(
            tf._vertex(fmt, (0.01 * i, 0.3, 0.001 * (i % 7)), uv=p, **kw)
            for i, p in enumerate(_stored())
        )
        tris = [(b + i, b + i + 1, b + i + 2) for b in range(0, NV, STRIP) for i in range(16)]
        return vb, b"".join(struct.pack("<3H", *t) for t in tris), NV

    monkeypatch.setattr(tf, "_quad", geometry)
    textures = ["/art/h/Head.bmp", "/art/characters/common/textures/head/female/EyeBlow.bmp"]
    return tf._model([{"lods": [[("Head", 0, 6, 0.0, 1), ("EyeBlow01", 1, 6, 7.0, 1)]]}], textures)


def _vt(path):
    return [tuple(float(x) for x in l.split()[1:3]) for l in open(path) if l.startswith("vt ")]


def test_decode_model_mesh_marks_the_submesh(lash_model, monkeypatch):
    h, s = lash_model
    head, lash = we.decode_model_mesh(h, s)["submeshes"]
    assert "restored" not in head and lash["restored"] == ["eyelash_uvs"]
    assert we.lash_is_restored(lash["uvs"])
    monkeypatch.setenv("WATCHMEN_NO_SYNTH", "1")
    lash = we.decode_model_mesh(h, s)["submeshes"][1]
    assert "restored" not in lash and lash["uvs"] == _half(_stored())


def test_decode_model_writes_the_restored_uvs_and_says_so(lash_model, tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    h, s = lash_model
    assert we.decode_model(h, s, tmp_path / "on" / "m.obj") is True
    vt = _vt(tmp_path / "on" / "m.obj")
    want = we.lash_restored_uvs(_half(_stored()))
    assert len(vt) == 4 + NV
    for (u, v), (u2, v2) in zip(vt[4:], want):  # an OBJ has v counted from the bottom
        assert u == pytest.approx(u2, abs=1e-5) and v == pytest.approx(1.0 - v2, abs=1e-5)
    note = json.loads((tmp_path / "on" / "m.model.json").read_text())["reconstruction"]
    lash = note["eyelash_uvs"]
    assert lash["shipped"] is False and "WATCHMEN_NO_SYNTH=1" in lash["note"]
    assert lash["stored_uv_range"] == {"u": [0.00331, 0.06195], "v": [0.39136, 0.46094]}
    assert lash["transform"] == {
        "lower": {"scale": 11.5133, "shift": [-0.0358, -4.5707]},
        "upper": {"scale": 11.7691, "shift": [0.4736, -4.4107]},
    }
    # the switch of the reconstructed Dominatrix_3: the stored UVs, no note
    monkeypatch.setenv("WATCHMEN_NO_SYNTH", "1")
    assert we.decode_model(h, s, tmp_path / "off" / "m.obj") is True
    off = _vt(tmp_path / "off" / "m.obj")
    for (u, v), (u2, v2) in zip(off[4:], _half(_stored())):
        assert u == pytest.approx(u2, abs=1e-5) and v == pytest.approx(1.0 - v2, abs=1e-5)
    meta = json.loads((tmp_path / "off" / "m.model.json").read_text())
    assert "reconstruction" not in meta
    on = json.loads((tmp_path / "on" / "m.model.json").read_text())
    on.pop("reconstruction")
    assert on == meta  # nothing else differs
    lines = lambda d: [l for l in open(tmp_path / d / "m.obj") if not l.startswith("vt ")]
    assert lines("on") == lines("off")


def test_a_model_without_the_layout_has_no_note(tmp_path):
    pytest.importorskip("PIL")
    h, s = tf._lod_model()
    assert we.decode_model(h, s, tmp_path / "m.obj") is True
    assert "reconstruction" not in json.loads((tmp_path / "m.model.json").read_text())


def _lash_part(rig, uv):
    rng = np.random.default_rng(7)
    V = rng.uniform(-0.1, 0.1, (NV, 3)).astype(np.float32)
    SI = np.zeros((NV, 4), np.uint16)
    SW = np.tile(np.array([1, 0, 0, 0], np.float32), (NV, 1))
    T = np.array([[i, i + 1, i + 2] for i in range(NV - 2)], np.uint32)
    return (V, SI, SW, T, np.array(uv, np.float32), "EyeBlow")


def test_a_character_glb_names_the_restored_piece(tmp_path, rig):
    restored = we.lash_restored_uvs(_half(_stored()))
    out = tmp_path / "c.glb"
    vg.write_glb(rig.parts + [_lash_part(rig, restored)], rig.manifest, str(out), str(rig.bind_npz))
    rec = parse_glb(out).j["asset"]["extras"]["watchmen"]["reconstruction"]
    assert rec == we.lash_reconstruction_note()
    # beside the record of a variant the game does not ship, which stays
    base = {"reconstruction": {"shipped": False, "base": "Dominatrix_2", "note": "x"}}
    vg.write_glb(
        rig.parts + [_lash_part(rig, restored)],
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        asset_extras=base,
    )
    rec = parse_glb(out).j["asset"]["extras"]["watchmen"]["reconstruction"]
    assert rec["base"] == "Dominatrix_2" and rec["eyelash_uvs"]["shipped"] is False
    assert base == {"reconstruction": {"shipped": False, "base": "Dominatrix_2", "note": "x"}}
    # as an alternative piece outside the scene
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        alt_parts=[("ALT Head", [_lash_part(rig, restored)])],
    )
    assert "eyelash_uvs" in parse_glb(out).j["asset"]["extras"]["watchmen"]["reconstruction"]


def test_a_character_glb_with_stored_uvs_has_no_record(tmp_path, rig):
    out = tmp_path / "c.glb"
    vg.write_glb(
        rig.parts + [_lash_part(rig, _half(_stored()))], rig.manifest, str(out), str(rig.bind_npz)
    )
    assert "reconstruction" not in parse_glb(out).j["asset"].get("extras", {}).get("watchmen", {})
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz))
    assert "reconstruction" not in parse_glb(out).j["asset"].get("extras", {}).get("watchmen", {})


def test_synth_enabled_follows_the_variable(monkeypatch):
    assert we.synth_enabled() is True
    monkeypatch.setenv("WATCHMEN_NO_SYNTH", "1")
    assert we.synth_enabled() is False
