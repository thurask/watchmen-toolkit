"""Code the suite did not run before 1.5.0 (review m14), on synthetic data.

    characters_export.export   the orchestration of `watchmen characters`: binds,
                               resumable bakes, jiggle memos, head selection, the
                               GLB and its options record, the resumed run
    characters_export.face_attach       face bind alignment, the name-proxy ride
                               and the weight transfer onto the static head
    characters_export._brown_hair_layers the brown-tinted hair layer of a
                               synthetic variant
    watchmen_extract.rsx_unswizzle      against a reference RSX swizzle
    watchmen_extract._carve_texture_legacy  the coherence-search carve
    watchmen_extract.carve_texture_console  a PS3 L8 and an X360 DXT1 texture with
                               known pixels, the early returns
    mesh_loader.mesh_arrays    the archive walk and mesh_arrays' skipped pieces

No game files.
"""

import io
import json
import os
import struct

import numpy as np
import pytest
from PIL import Image

import characters_export as ce
import watchmen_extract as we
from conftest import parse_glb

# ---------------------------------------------------------------------------
# characters_export.export
# ---------------------------------------------------------------------------


def test_export_writes_the_glb_and_resumes(export_env, capsys):
    ex, out, calls = export_env
    pending = ce.export(str(ex), str(out), naz="none.naz", jiggle_model="pinned")
    log = capsys.readouterr().out
    assert pending == 2  # Thug's bakes
    assert "WARNING: binds/bind_large_file_v1.npz does not match this extract" in log
    assert "bind small: not built before the animation table (no skeleton)" in log
    assert "Thug [small]: 0 baked, 2 remaining -- rerun to continue" in log
    assert "jiggle_d6: 1 clips [large]" in log and calls["jiggle"] == ["pinned"]
    glb = out / "Heavy" / "Heavy.glb"
    assert glb.exists() and not (out / "Thug").exists()
    assert not (out / "_bake" / "large" / "torn.tmp.npz").exists()
    g = parse_glb(glb)
    assert [a["name"] for a in g.j["animations"]] == ["clip_test"]
    assert {m["name"] for m in g.j["materials"]} >= {"mat_Heavy_Body", "mat_Heavy_Hair"}
    opts = json.loads((out / "_glb_options.json").read_text())
    assert list(opts["files"]) == ["Heavy/Heavy.glb"]
    assert opts["files"]["Heavy/Heavy.glb"]["jiggle"].startswith("pinned")
    # the jiggled palette is cached beside the bake
    memo = [p for p in (out / "_bake").iterdir() if p.name.startswith("large_j_")]
    assert len(memo) == 1 and len(list(memo[0].glob("*.npz"))) == 1
    # resumed: the GLB is kept, the memo is read, nothing is solved again
    mtime = glb.stat().st_mtime_ns
    assert ce.export(str(ex), str(out), naz="none.naz", jiggle_model="pinned") == 2
    log = capsys.readouterr().out
    assert "kept 1 existing GLB(s) written with these options" in log
    assert glb.stat().st_mtime_ns == mtime and calls["jiggle"] == ["pinned"]
    # other options: written again (and `only` limits the run to one character)
    assert ce.export(str(ex), str(out), naz="none.naz", only="Heavy", jiggle_model="pivot") == 0
    assert "kept" not in capsys.readouterr().out
    assert calls["jiggle"] == ["pinned", "pivot"] and calls["bake"].count("small") == 2


def test_export_picks_the_head_to_rig(export_env, monkeypatch, capsys):
    """A static head listed in HEAD_SWAPS is replaced by its face-rigged twin; a
    character in EXTRA_HEADS gets its extra head; the face attach is asked for
    each (it returns no face here, so the GLB is the body alone)."""
    ex, out, calls = export_env
    seen = []

    def face_attach(model_base, bone, bind, bn, cname, e, o, align_ref=None):
        seen.append((cname, os.path.basename(model_base), bone, align_ref))
        return None

    monkeypatch.setattr(ce, "face_attach", face_attach)
    monkeypatch.setattr(
        ce, "_model_index", lambda e: {"Heavy_FaceTwin": "/m/Heavy_FaceTwin", "Extra": "/m/Extra"}
    )
    monkeypatch.setitem(ce.HEAD_SWAPS, "Heavy_Hair", "Heavy_FaceTwin")
    monkeypatch.setitem(ce.EXTRA_HEADS, "Heavy", ("Extra", "bone3"))
    ce.export(str(ex), str(out), naz="none.naz", only="Heavy")
    assert seen == [
        ("Heavy", "Heavy_FaceTwin", "Head", "/m/Heavy_Hair"),
        ("Heavy", "Extra", "bone3", None),
    ]
    # the swapped static head left the body mesh
    assert ["Heavy_Body"] in calls["load_parts"] and (out / "Heavy" / "Heavy.glb").exists()


def test_export_outfits_synthetic_hair_and_restored_textures(export_env, monkeypatch, capsys):
    """A variant with two outfits (one node per outfit model), the reconstructed
    Dominatrix_3 (a hair submesh grafted from another model, brown-tinted) and a
    texture override."""
    import char_lib
    import parts_rule

    ex, out, calls = export_env
    monkeypatch.setattr(
        ce,
        "discover",
        lambda e: {"Dominatrices": {"Dominatrix_3": ("large", ["/m/Body", "/m/Hair", "/m/Afro"])}},
    )
    monkeypatch.setattr(
        parts_rule,
        "members",
        lambda e, v: [
            {"index": 1, "models": ["Body", "Hair"]},
            {"index": 2, "models": ["Body", "Afro"]},
        ],
    )
    monkeypatch.setattr(ce, "_model_index", lambda e: {"BS2_WithoutWeapon": "/m/BS2_WithoutWeapon"})
    orig = char_lib.load_parts

    def load_parts(models, bn, sheets=None):
        if models == ["/m/BS2_WithoutWeapon"]:
            return [p[:5] + ("TwilightLadyHair",) for p in orig(models, bn)] + orig(
                ["/m/Other"], bn
            )
        return orig(models, bn, sheets)

    monkeypatch.setattr(char_lib, "load_parts", load_parts)
    png = _png(np.full((4, 4, 3), 90), "RGB")
    monkeypatch.setattr(
        ce, "_brown_hair_layers", lambda roots, hm, tm: {"diffuse": png, "alphaMask": True}
    )
    monkeypatch.setitem(ce.TEX_OVERRIDES, ("Dominatrices", "Dominatrix_3"), {"mat_Body": "Repl"})
    monkeypatch.setattr(
        char_lib,
        "find_textures",
        lambda parts, roots: {str(p[5]): {"alphaMask": False} for p in parts},
    )
    monkeypatch.setattr(
        char_lib, "find_layers", lambda mat, roots: {"diffuse": png} if mat == "Repl" else None
    )
    ce.export(str(ex), str(out), naz="none.naz")
    log = capsys.readouterr().out
    assert (
        "synth: Dominatrices/Dominatrix_3 + TwilightLadyHair hair (1 submesh, brown-tinted)" in log
    )
    assert "restore: Dominatrices/Dominatrix_3 mat_Body -> Repl" in log
    g = parse_glb(out / "Dominatrices" / "Dominatrix_3.glb")
    names = [n["name"] for n in g.j["nodes"]]
    assert "OUTFIT 1 Hair" in names and "OUTFIT 2 Afro" in names
    mats = {m["name"] for m in g.j["materials"]}
    assert {"TwilightLadyHair_Brown", "mat_Body"} <= mats
    parts = g.j["asset"]["extras"]["watchmen"]["parts"]
    assert parts["hidden_nodes"] == ["OUTFIT 2 Afro"] and parts["common_models"] == ["Body"]
    assert g.j["asset"]["extras"]["watchmen"].get("reconstruction")


# ---------------------------------------------------------------------------
# characters_export.face_attach
# ---------------------------------------------------------------------------


def test_face_attach_aligns_and_rides_the_name_proxies(face_env, capsys):
    e = face_env
    face = ce.face_attach("/m/HeadTwin", "Head", e["body"], e["bn"], "Heavy", str(e["ex"]), "out")
    log = capsys.readouterr().out
    assert os.path.exists(face["bind"]) and face["attach_idx"] == 3 and face["family"] == "Fam"
    assert np.allclose(face["M"], e["M"]) and np.allclose(face["t"], e["t"])
    # Neck is aligned: it rides the body's Neck; Bip01 (0.5 m off) rides Spine2
    assert face["proxy_slots"] == [1, 2]
    assert "name-proxy Bip01 -> Spine2 ride" in log and "name-proxy ride: ['Spine2', 'Neck']" in log
    SI = face["parts"][0][1]
    assert SI[:, 0].tolist() == [3, 2, 5, 4]  # Jaw, Head stay; Neck -> proxy 5, Bip01 -> 4
    names = [n for n, _p, _f in face["anims"]]
    assert names == [
        "FACE Fam/MouthClosed_EyesClosed",
        "FACE Fam/MouthClosed_EyesOpen",
        "FACE Fam/MouthTalk_EyesAnger",
        "FACE SYNTH Blink",
        "FACE SYNTH Talk",
    ]
    assert all(len(p) == 2 for n, p, _f in face["anims"][:3])  # one-key poses held
    assert face["blink_closed"] is not None and set(face["auto_poses"]) == {
        "MouthClosed_EyesOpen",
        "MouthClosed_EyesClosed",
        "MouthTalk_EyesAnger",
    }


def test_face_attach_transfers_the_static_heads_weights(face_env, capsys):
    e = face_env
    face = ce.face_attach(
        "/m/HeadTwin",
        "Head",
        e["body"],
        e["bn"],
        "Heavy",
        str(e["ex"]),
        "out",
        align_ref="/m/StaticHead",
    )
    log = capsys.readouterr().out
    assert "ICP residual" in log and "weight transfer: proxy body slots ['Head', 'Neck']" in log
    assert face["proxy_align"] is None and face["proxy_slots"] == [3, 2]
    V, SI, SW = face["parts"][0][:3]
    assert np.allclose(SW.sum(1), 1.0)
    # Jaw (below Head) keeps its face weight; the others take the static head's
    # 75 % Head + 25 % Neck through the proxies 4 (Head) and 5 (Neck)
    assert SI[0, 0] == 3 and SW[0, 0] == 1.0
    for v in (1, 2, 3):
        assert dict(zip(SI[v, :2].tolist(), SW[v, :2].round(4).tolist())) == {4: 0.75, 5: 0.25}


# ---------------------------------------------------------------------------
# characters_export._brown_hair_layers
# ---------------------------------------------------------------------------


def _png(arr, mode):
    b = io.BytesIO()
    Image.fromarray(np.asarray(arr, np.uint8), mode).save(b, "PNG")
    return b.getvalue()


def test_brown_hair_layers(monkeypatch):
    import char_lib

    hair = np.zeros((4, 4, 4), np.uint8)
    hair[..., 0] = hair[..., 1] = hair[..., 2] = np.arange(16).reshape(4, 4) * 10 + 20
    hair[..., 3] = [[0, 255, 255, 0]] * 4
    tint = np.zeros((2, 2, 3), np.uint8)
    tint[:] = (120, 80, 40)  # warm mid-value: brown
    tint[0, 0] = (10, 10, 10)  # too dark, not counted
    layers = {
        "hair_mat": {"diffuse": _png(hair, "RGBA"), "normal": b"N", "specSize": b"S"},
        "tint_mat": {"diffuse": _png(tint, "RGB")},
    }
    monkeypatch.setattr(char_lib, "find_layers", lambda mat, roots: dict(layers.get(mat) or {}))
    out = ce._brown_hair_layers(["t"], "hair_mat", "tint_mat")
    assert out["normal"] == b"N" and out["specSize"] == b"S" and out["alphaMask"] is True
    im = np.asarray(Image.open(io.BytesIO(out["diffuse"])))
    assert im.shape == (4, 4, 4) and (im[..., 3] == hair[..., 3]).all()  # cut-out kept
    rgb = im[..., :3].reshape(-1, 3).astype(float)
    # every texel has the brown's hue; brightness follows the strands
    ratio = rgb / rgb[:, :1]
    assert np.allclose(ratio[:, 1], 80 / 120, atol=0.03) and np.allclose(
        ratio[:, 2], 40 / 120, atol=0.04
    )
    assert rgb[15, 0] > rgb[0, 0]
    # no tint layer: the measured fallback brown (87, 52, 27)
    layers["tint_mat"] = None
    out2 = ce._brown_hair_layers(["t"], "hair_mat", "tint_mat")
    r = np.asarray(Image.open(io.BytesIO(out2["diffuse"])))[..., :3].reshape(-1, 3).astype(float)
    bright = r[:, 0] >= 60  # 8-bit rounding dominates the ratio of the darkest texels
    assert bright.sum() >= 8
    assert np.allclose(r[bright, 1] / r[bright, 0], 52 / 87, atol=0.02)
    assert np.allclose(r[bright, 2] / r[bright, 0], 27 / 87, atol=0.02)
    # a hair material without a diffuse layer: nothing to tint
    assert ce._brown_hair_layers(["t"], "missing", "tint_mat") is None


# ---------------------------------------------------------------------------
# watchmen_extract.rsx_unswizzle
# ---------------------------------------------------------------------------


def _rsx_address(x, y, w, h):
    """Reference RSX swizzle address of texel (x, y): the bits of x and y
    interleaved from bit 0 (x first) while both have bits left, then the
    remaining bits of the larger dimension above them."""
    lw, lh = w.bit_length() - 1, h.bit_length() - 1
    addr, b, bx, by = 0, 0, 0, 0
    while bx < lw or by < lh:
        if bx < lw and (by >= lh or bx <= by):
            addr |= ((x >> bx) & 1) << b
            bx += 1
        else:
            addr |= ((y >> by) & 1) << b
            by += 1
        b += 1
    return addr


def _swizzle(linear, w, h, unit):
    out = bytearray(len(linear))
    for y in range(h):
        for x in range(w):
            d = _rsx_address(x, y, w, h) * unit
            s = (y * w + x) * unit
            out[d : d + unit] = linear[s : s + unit]
    return bytes(out)


@pytest.mark.parametrize(
    "w,h,unit",
    [
        (1, 1, 1),
        (4, 4, 1),
        (8, 2, 1),
        (2, 8, 1),
        (16, 4, 1),
        (4, 16, 1),
        (32, 32, 1),
        (8, 4, 4),
        (2, 16, 4),
    ],
)
def test_rsx_unswizzle_inverts_the_reference_swizzle(w, h, unit):
    rng = np.random.default_rng(w * 100 + h * 10 + unit)
    linear = rng.integers(0, 256, w * h * unit, dtype=np.uint8).tobytes()
    sw = _swizzle(linear, w, h, unit)
    assert we.rsx_unswizzle(sw + b"\xee" * 16, w, h, unit) == linear  # chain bytes ignored


def test_rsx_unswizzle_leaves_what_it_cannot_untile():
    assert we.rsx_unswizzle(b"x" * 12, 3, 4) == b"x" * 12  # not a power of two
    assert we.rsx_unswizzle(b"x" * 8, 4, 4) == b"x" * 8  # too short


# ---------------------------------------------------------------------------
# watchmen_extract.carve_texture_console with known pixels
# ---------------------------------------------------------------------------


def test_ps3_l8_layer_is_unswizzled(tmp_path):
    from test_p2_x360_textures import _desc, _header, _ps3_seg

    w, h = 16, 8
    linear = bytes((y * 16 + x) & 255 for y in range(h) for x in range(w))
    stream = _ps3_seg(_swizzle(linear, w, h, 1), 0x81, 1, w, h)
    hdr = _header([({0: _desc(">", w, h, 3, 1)}, "/data/art/x/Mask.bmp")])
    out = tmp_path / "t"
    assert we.carve_texture_console(stream, hdr, out)  # log=None: no output
    png = sorted(p.name for p in out.glob("*.png"))
    assert png == ["0_diffuse_16x8_L8.png"]
    px = np.asarray(Image.open(out / png[0]))
    assert px.shape == (8, 16) and px.tobytes() == linear


def test_x360_dxt1_layer_with_known_pixels(tmp_path):
    from test_p2_x360_textures import _desc, _dxt1, _header, _rgb, _x360_tile

    cols = [0xF800, 0x07E0, 0x001F, 0xFFFF] * 16  # 8 x 8 blocks of four colours
    lin = _dxt1(cols, 8, 8)
    hdr = _header([({0: _desc(">", 32, 32, 5, 1, size=8192)}, "/data/art/x/Quad.bmp")])
    log = []
    assert we.carve_texture_console(_x360_tile(lin, 8, 8, 8), hdr, tmp_path / "t", log.append)
    px = np.asarray(Image.open(tmp_path / "t" / "0_diffuse_32x32_DXT1.png"))[..., :3]
    for by in range(8):
        for bx in range(8):
            want = _rgb(cols[by * 8 + bx])
            assert (px[by * 4 : by * 4 + 4, bx * 4 : bx * 4 + 4] == want).all()
    assert log and "X360 layers=1 x1 (exact stream 8192)" in log[0]


def test_console_carve_of_something_that_is_not_a_texture(tmp_path):
    assert we.carve_texture_console(b"\0" * 64, b"\0" * 64, tmp_path / "t") is False
    assert not (tmp_path / "t").exists()


# ---------------------------------------------------------------------------
# watchmen_extract._carve_texture_legacy
# ---------------------------------------------------------------------------


def _solid_dxt1_chain(w, h, c565):
    n, _m = we.mip_chain_size(w, h, 8)
    return struct.pack("<HHI", c565, c565, 0) * (n // 8)


def _flat_bc5_chain(w, h):
    n, _m = we.mip_chain_size(w, h, 16)
    return bytes([128, 128, 0, 0, 0, 0, 0, 0] * 2) * (n // 16)


def test_legacy_carve_finds_diffuse_normal_and_spec(tmp_path):
    hdr = b"not a texture class" + struct.pack("<I", 64)  # dims: 64 x 64
    stream = _solid_dxt1_chain(64, 64, 0xF800) + _flat_bc5_chain(64, 64)
    stream += _solid_dxt1_chain(64, 64, 0x07E0)
    log = []
    assert we.carve_texture(stream, hdr, tmp_path / "t", log.append)
    names = sorted(p.name for p in (tmp_path / "t").glob("*.png"))
    assert names == [
        "0_diffuse_64x64_DXT1.png",
        "1_normal_64x64_ATI2.png",
        "2_specMap_64x64_DXT1.png",
    ]
    d = np.asarray(Image.open(tmp_path / "t" / names[0]))
    assert (d[..., :3] == (255, 0, 0)).all()
    n = np.asarray(Image.open(tmp_path / "t" / names[1]))
    assert (n[..., 0] == 128).all() and (n[..., 1] == 128).all()
    s = np.asarray(Image.open(tmp_path / "t" / names[2]))
    assert (s[..., :3] == (0, 255, 0)).all()
    assert log == ["      64x64 diffuse=DXT1 normal=BC5 specular=64x64 -> t/"]


def test_legacy_carve_without_a_normal_map_and_of_noise(tmp_path):
    hdr = b"junk" + struct.pack("<I", 32)
    rng = np.random.default_rng(7)
    stream = (
        _solid_dxt1_chain(32, 32, 0x001F) + rng.integers(0, 256, 6000, dtype=np.uint8).tobytes()
    )
    log = []
    assert we.carve_texture(stream, hdr, tmp_path / "a", log.append)
    assert sorted(p.name for p in (tmp_path / "a").glob("*.png")) == ["0_diffuse_32x32_DXT1.png"]
    assert "normal=NOT-FOUND" in log[0]
    # no size in the header and a stream too short for the default 256..1024 guesses
    noise = rng.integers(0, 256, 8192, dtype=np.uint8).tobytes()
    assert we.carve_texture(noise, b"junk", tmp_path / "b", log.append) is False
    assert we.carve_texture(b"\0" * 1000, hdr, tmp_path / "c") is False  # under 4 KiB


# ---------------------------------------------------------------------------
# watchmenlib's archive walk and mesh_loader.mesh_arrays
# ---------------------------------------------------------------------------


def test_archive_walk_and_mesh_arrays(monkeypatch, capsys):
    import mesh_loader
    import watchmenlib as wl

    blocks = [("a", {"h": b"1", "s": b"2"}), ("b", {"h": b"3", "s": b"4"})]
    monkeypatch.setattr(we, "iter_blocks", lambda naz, streams=True: iter(blocks))
    assert list(wl.iter_blocks("x.naz")) == blocks and wl.grab_blocks("x.naz") == dict(blocks)
    V = np.zeros((3, 3), np.float32)
    pieces = [
        {"index": 0, "skin": (None, None), "V": V, "T": np.array([[0, 1, 2]])},
        {
            "index": 1,
            "skin": (np.zeros((3, 4), np.uint8), np.ones((3, 4), np.float32)),
            "V": V + 1,
            "T": np.array([[0, 1, 2]]),
        },
    ]
    monkeypatch.setattr(
        mesh_loader, "load_submeshes", lambda mh, ms, name, attrs=False: (pieces, {})
    )
    Vs, SI, SW, T, subs = mesh_loader.mesh_arrays(b"", b"", "Body")
    assert "Body sub0: no skin, left out" in capsys.readouterr().out
    assert len(Vs) == 3 and subs == [(0, 3, 0, 1)] and SI.shape == (3, 4)
    monkeypatch.setattr(mesh_loader, "load_submeshes", lambda mh, ms, name, attrs=False: ([], {}))
    Vs, SI, SW, T, subs = mesh_loader.mesh_arrays(b"", b"", "Body")
    assert SI.shape == (0, 4) and SW.dtype == np.float32 and subs == []
