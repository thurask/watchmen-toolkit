"""Engine-read file formats (findings/formats.md): every test builds its fixture
from the layout the engine loader reads and fails on the pre-change parsers.

Sections
--------
  1. block header / directory (FUN_004a36d8, FUN_004a3525)
  2. script asset classes: ModelEffects(ModelRes), TextureEffects(Texture)
  3. Texture header: 29-byte descriptors, 8 slots per frame, 4-byte linear rows
  4. ModelRes: header-driven mesh decode (FUN_00547006 -> ... -> FUN_004336ec)
  5. parse_model_nodes: header-driven node table
  6. .sequence: engine grammar, key classes, Hermite evaluation, Euler tracks
"""

import math
import struct

import numpy as np
import pytest

import decode_sequence as ds
import parse_model_nodes as pmn
import watchmen_extract as we


def _str(s):
    b = s.encode("latin1") + b"\0"
    return struct.pack("<I", len(b)) + b


# ---------------------------------------------------------------------------
# 1. block header / directory
# ---------------------------------------------------------------------------


def _record(sizes, type_hash, name, streams=None):
    r = struct.pack("<6I", *sizes) + struct.pack("<I", type_hash) + _str(name)
    if streams is None:
        return r + b"\x00"
    return r + b"\x01" + b"".join(struct.pack("<II", *p) for p in streams)


def _block(main, localized=(), lang_blobs=None):
    """main / localized: [(name, type_hash, [blob per language] | blob, stream|None)].
    Returns (block_h_z bytes, block_s_z bytes)."""
    s_data = b""
    toc = b""
    blobs = b""
    recs = []
    for name, th, blob, stream in list(main) + list(localized):
        per_lang = blob if isinstance(blob, list) else [blob] * 6
        pairs = None
        if stream is not None:
            per_stream = stream if isinstance(stream, list) else [stream] * 6
            pairs = []
            for st in per_stream:
                pairs.append((len(s_data), len(st)))
                s_data += st
        recs.append((name, per_lang))
        toc += _record([len(b) for b in per_lang], th, name, pairs)
    for name, per_lang in recs[: len(main)]:
        blobs += per_lang[0]
    data_start = 400 + len(toc)
    lang_off = [0] * 6
    loc = b""
    if localized:
        for lang in range(6):
            lang_off[lang] = data_start + len(blobs) + len(loc)
            for name, per_lang in recs[len(main) :]:
                loc += per_lang[lang]
    hdr = bytearray(400)
    struct.pack_into("<8f", hdr, 0, -1, -2, -3, 0, 1, 2, 3, 0)
    hdr[0x24:0x48] = b"DB851B2E-F452-47f7-9C7D-0BD4918F6F07"
    fp = bytes.fromhex("46b742a4fa59a6d8d3a88b4e807da5451071a61548997978")
    hdr[0x48 : 0x48 + len(fp)] = fp
    hdr[0x147] = 2
    trailer = data_start + len(blobs) + len(loc)
    struct.pack_into(
        "<9I",
        hdr,
        328,
        0x593F430A,
        len(toc),
        len(recs[0][1][0]),
        max(len(toc), max(len(b) for _n, pl in recs for b in pl)),
        trailer,
        8,
        len(main),
        len(localized),
        sum(1 for r in list(main) + list(localized) if r[3] is not None),
    )
    struct.pack_into("<6I", hdr, 364, *lang_off)
    return bytes(hdr) + toc + blobs + loc + b"\0" * 8, s_data


_TEX = 0x7D8D9A63


def test_block_stream_belongs_to_its_own_record_including_the_last():
    """The (offset, size) pairs are the tail of the record they locate; the old
    reader took them from the NEXT record, so the last entry never had a stream."""
    h, s = _block(
        [
            ("/a.bmp", _TEX, b"HDR-A", b"stream-a"),
            ("/b.fragment", 0xA048CB21, b"HDR-BB", None),
            ("/c.bmp", _TEX, b"HDR-CCC", b"stream-c!"),
        ]
    )
    got = [(e.name, hd, st) for e, hd, st in we.extract_block(h, s)]
    assert got == [
        ("/a.bmp", b"HDR-A", b"stream-a"),
        ("/b.fragment", b"HDR-BB", None),
        ("/c.bmp", b"HDR-CCC", b"stream-c!"),
    ]


def test_block_directory_record_fields_and_legacy_aliases():
    h, _s = _block([("/a.bmp", _TEX, b"HDR-A", b"stream-a"), ("/b.x", 0x41764525, b"B", None)])
    entries, data_start = we.parse_block_toc(h)
    a, b = entries
    assert (a.has_stream, a.type_hash, a.sizes) == (True, _TEX, [5] * 6)
    assert a.streams == [(i * 8, 8) for i in range(6)]
    assert (b.has_stream, b.streams, b.type_name) == (False, None, "ModelEffects(ModelRes)")
    # names used before the engine read keep working
    assert (a.flag, a.unknown, a.variants, a.data_size) == (1, _TEX, [5] * 6, 5)
    assert a.pairs[0] == (0, 8) and b.flag == 0 and b.pairs == []
    assert data_start == 400 + struct.unpack_from("<I", h, 332)[0]


def test_block_header_fields_and_fingerprint():
    h, _s = _block([("/a.bmp", _TEX, b"HDR-A" * 3, b"x"), ("/b.bmp", _TEX, b"B", None)])
    hd = we.parse_block_header(h)
    assert hd["guid"] == "DB851B2E-F452-47f7-9C7D-0BD4918F6F07"
    assert hd["fingerprint"] == "THIS IS THE DEFAULT FING"  # LFSR cipher, FUN_00405b1e
    assert hd["entry0_size"] == 15 and hd["num_entries"] == 2 and hd["num_streams"] == 1
    assert hd["io_buffer_size"] == hd["tables_size"]  # the directory is the largest read
    assert hd["fragment_offset"] == len(h) - 8 and hd["fragment_size"] == 8
    assert hd["num_localized"] == 0 and hd["language_header_offset"] == (0,) * 6
    assert hd["bounds"][:3] == (-1.0, -2.0, -3.0)


def test_block_localized_entries_follow_the_language_slot():
    """Records after num_entries are per-language: blob size, blob position (seek
    table at 364) and stream all come from the language slot."""
    texts = [("TEXT-%d" % i).encode() * (i + 1) for i in range(6)]
    streams = [("S%d" % i).encode() * (i + 2) for i in range(6)]
    h, s = _block(
        [("/main.bmp", _TEX, b"MAIN", b"main-stream")],
        [
            ("/Localize/Cut_uk.txt", 0x7D6D720B, texts, None),
            ("/logo_uk.bmp", _TEX, b"LOGO", streams),
        ],
    )
    for lang in (0, 3, 5):
        got = [(e.name, e.localized, hd, st) for e, hd, st in we.extract_block(h, s, lang)]
        assert got == [
            ("/main.bmp", False, b"MAIN", b"main-stream"),
            ("/Localize/Cut_uk.txt", True, texts[lang], None),
            ("/logo_uk.bmp", True, b"LOGO", streams[lang]),
        ]
    assert len(list(we.extract_block(h, s))) == 3  # default language 0


# ---------------------------------------------------------------------------
# 2. script asset classes
# ---------------------------------------------------------------------------


def test_script_asset_type_hashes_and_base_class():
    assert we.asset_type_name(0x41764525) == "ModelEffects(ModelRes)"
    assert we.asset_type_name(0x96EA413F) == "TextureEffects(Texture)"
    assert we.asset_type_name(_TEX) == "Texture"
    assert we.asset_base_class("ModelEffects(ModelRes)") == "ModelRes"
    assert we.asset_base_class("TextureEffects(Texture)") == "Texture"
    assert we.asset_base_class("sound") == "sound"


# ---------------------------------------------------------------------------
# 3. Texture header
# ---------------------------------------------------------------------------


def _tex_desc(w, h, fmt, mips, typ=1, alpha=0):
    return struct.pack("<5IBII", w, h, fmt, 0, typ, alpha, mips, 0)


def _tex_header(frames, typename="Texture", bag_dwords=45, anim=0):
    """frames: [({slot: desc}, path)]"""
    b = _str(typename) + struct.pack("<I", bag_dwords) + b"\xab" * (4 * bag_dwords)
    b += struct.pack("<IB", len(frames), anim)
    for slots, path in frames:
        b += slots[0]
        for k in range(1, 8):
            b += b"\x01" + slots[k] if k in slots else b"\x00"
        b += _str(path)
    return b + b"\0" * 40


def test_texture_frames_slots_and_linear_row_padding():
    hdr = _tex_header(
        [
            (
                {0: _tex_desc(8, 8, 5, 4), 1: _tex_desc(8, 8, 9, 2), 7: _tex_desc(8, 8, 3, 4)},
                "/data/art/x/Thing.bmp",
            )
        ]
    )
    ex = we.parse_texture_frames(hdr)
    slots = ex["frames"][0]["slots"]
    assert [d["slot"] if d else None for d in slots] == [0, 1, None, None, None, None, None, 7]
    assert ex["frames"][0]["path"] == "/data/art/x/Thing.bmp" and ex["anim"] is False
    assert (slots[1]["fmt"], slots[1]["aw"], slots[1]["mip"]) == ("ATI2", 8, 2)
    # DXT1 8x8 x4 mips = 32+8+8+8 ; ATI2 x2 = 64+16 ; L8 rows padded to 4: 64+16+8+4
    assert [d["chain"] for d in slots if d] == [56, 80, 92]
    assert we._chain_bytes(3, 8, 8, 4) == 85  # the unpadded count is 7 bytes short
    plan = we.plan_texture_layers(hdr, 56 + 80 + 92)
    assert plan["kind"] == "single" and plan.get("exact") and len(plan["layers"]) == 3
    labels = [we.texture_layer_label(plan["layers"], j) for j in range(3)]
    assert labels == ["diffuse", "normal", "specSize"]


def test_texture_exact_plan_cube_and_animation():
    cube = _tex_header([({0: _tex_desc(4, 4, 5, 1, typ=2)}, "/data/c_cubemap.bmp")])
    assert we.plan_texture_layers(cube, 6 * 8)["kind"] == "cube"
    fr = {0: _tex_desc(4, 4, 1, 1, alpha=1)}
    anim = _tex_header([(fr, "/data/f0.bmp"), (fr, "/data/f1.bmp"), (fr, "/data/f2.bmp")], anim=1)
    plan = we.plan_texture_layers(anim, 3 * 64)
    assert (plan["kind"], plan["count"], plan.get("exact")) == ("anim", 3, True)
    # a stream the header does not tile exactly is left to the older planner
    assert not we.plan_texture_layers(anim, 3 * 64 + 1).get("exact")


def test_texture_effects_header_is_a_texture(tmp_path):
    """TextureEffects(Texture) has a longer type name and a 55-dword bag; it is read
    by the Texture loader, so it must carve like one (was skipped entirely)."""
    pytest.importorskip("PIL")
    px = bytes(range(64))  # 4x4 A8R8G8B8
    hdr = _tex_header(
        [({0: _tex_desc(4, 4, 1, 1, alpha=1)}, "/data/art/decals/Burn.bmp")],
        typename="TextureEffects(Texture)",
        bag_dwords=55,
    )
    assert we.asset_class(hdr) == "TextureEffects(Texture)"
    assert we.parse_texture_frames(hdr)["frames"][0]["slots"][0]["alpha"] is True
    assert we.carve_texture(px, hdr, tmp_path / "Burn") is True
    assert [p.name for p in (tmp_path / "Burn").glob("*.png")] == ["0_diffuse_4x4_A8R8G8B8.png"]


def test_texture_layer_after_a_padded_l8_layer_is_read_at_the_right_offset(tmp_path):
    """An L8 chain with 2- and 1-texel mips is 7 bytes longer than w*h sums; the
    layer stored after it used to be decoded 7 bytes early."""
    Image = pytest.importorskip("PIL.Image")
    l8_a = bytes([10] * 64) + bytes([20] * 16) + bytes([30] * 8) + bytes([40] * 4)
    l8_b = bytes(range(100, 164)) + bytes(28)
    hdr = _tex_header(
        [
            (
                {0: _tex_desc(8, 8, 3, 4), 4: _tex_desc(8, 8, 3, 4)},
                "/data/art/x/Gloss.bmp",
            )
        ]
    )
    assert we.carve_texture(l8_a + l8_b, hdr, tmp_path / "g") is True
    out = sorted((tmp_path / "g").glob("1_*.png"))
    assert len(out) == 1
    got = np.asarray(Image.open(out[0]))
    assert got.reshape(-1).tolist() == list(range(100, 164))


# ---------------------------------------------------------------------------
# 4. ModelRes: header-driven mesh decode
# ---------------------------------------------------------------------------


def _half3(v):
    return struct.pack("<3e", *v) + b"\0\0"


def _vertex(fmt, pos, normal=(0, 0, 1), color=(255, 255, 255, 255), uv=(0, 0), joints=None):
    if fmt in (9, 10):
        b = struct.pack("<3f", *pos) + _half3(normal)
        if fmt == 10:
            b += bytes([joints[2], joints[1], joints[0], joints[3]]) + struct.pack(
                "<4e", 1, 0, 0, 0
            )
        return b
    r, g, bl, a = color
    b = struct.pack("<3f", *pos) + _half3(normal) + bytes([bl, g, r, a])
    b += struct.pack("<2e", *uv) + _half3((1, 0, 0)) + _half3((0, -1, 0))
    if fmt == 6:
        b += bytes([joints[2], joints[1], joints[0], joints[3]])
        b += struct.pack("<4e", 0.75, 0.25, 0, 0)
    return b


def _quad(fmt, z, **kw):
    """4 vertices + 2 triangles at height z -> (vertex bytes, index bytes, nv)."""
    pts = [(0, 0, z), (1, 0, z), (1, 1, z), (0, 1, z)]
    v = b"".join(_vertex(fmt, p, uv=(p[0], p[1]), **kw) for p in pts)
    return v, struct.pack("<6H", 0, 1, 2, 0, 2, 3), 4


def _meshbuffer(fmt, nv, index_bytes, ix=1, flags=8, has_color=1):
    b = struct.pack("<6f", 0.5, 0.5, 0, 0.5, 0.5, 0) + bytes([has_color, 0, 0])
    return b + struct.pack("<6I", flags, nv, fmt, flags, index_bytes, ix)


def _bulk(vb, ib):
    return vb + ib + struct.pack("<I", 0) + struct.pack("<I", 0) + b"\0"


def _model(parts, textures, typename="ModelRes", bag_dwords=91):
    """parts: [dict(name, pos, quat, parent, lods=[[(name, tex, fmt, z, ix)]],
    shadow=[z], proxy=z|None)] -> (header, stream)."""
    h = _str(typename) + struct.pack("<I", bag_dwords) + b"\xcd" * (4 * bag_dwords)
    h += struct.pack("<IBIB", 0, 0, 0xFFFFFFFF, 0) + struct.pack("<II", 0, 0)
    h += struct.pack("<6f", 0, 0, 0, 1, 1, 1)
    h += struct.pack("<I", len(textures)) + b"".join(b"\x01" + _str(t) for t in textures)
    h += struct.pack("<I", 1) + _str("/pivotbooks/default.pb")
    h += struct.pack("<I", len(parts))
    s = b""
    for P in parts:
        h += struct.pack("<3f", *P.get("pos", (0, 0, 0)))
        h += struct.pack("<4f", *P.get("quat", (0, 0, 0, 1)))
        h += _str(P.get("name", "")) + struct.pack("<Ii", 0, P.get("parent", -1))
        lods = P.get("lods", [])
        h += struct.pack("<I", len(lods))
        for lod in lods:
            h += struct.pack("<I", len(lod))
            for name, tex, fmt, z, ix in lod:
                vb, ib, nv = _quad(fmt, z, joints=(1, 2, 3, 4), color=(10, 20, 30, 40))
                h += _str(name) + struct.pack("<II", 1, tex) + bytes([0, 0])
                h += struct.pack("<I", 1) + bytes([0, 0])
                h += _meshbuffer(fmt, nv, len(ib), ix) + struct.pack("<I", 0)
                s += _bulk(vb, ib)
        shadow = P.get("shadow", [])
        h += struct.pack("<I", 1 if shadow else 0)
        if shadow:
            h += struct.pack("<I", len(shadow))
            for z in shadow:
                vb, ib, nv = _quad(9, z)
                h += b"\x00" + struct.pack("<I", 0xFFFFFFFF) + _meshbuffer(9, nv, len(ib))
                s += _bulk(vb, ib)
        if P.get("proxy") is not None:
            vb, ib, nv = _quad(5, P["proxy"])
            h += b"\x01" + _meshbuffer(5, nv, len(ib), flags=0)
            s += _bulk(vb, ib)
        else:
            h += b"\x00"
        h += struct.pack("<III", 0, 0, 0)
    return h + b"\0" * 24, s


@pytest.fixture
def obj_capture(monkeypatch):
    cap = {}

    def fake(path, name, v, n, uv, tris, subs, mats, tex_index, log):
        cap.update(v=list(v), n=n, uv=uv, tris=list(tris), subs=list(subs), mats=list(mats))

    monkeypatch.setattr(we, "_write_obj_mtl", fake)
    return cap


_TEXTURES = ["/art/t/Wall_01.bmp", "/art/t/Trim_02.bmp", "/art/t/Leaf_03.bmp"]


def _lod_model():
    return _model(
        [
            {
                "lods": [
                    [("Body", 1, 5, 0.0, 1), ("Leaf", 2, 5, 1.0, 0)],
                    [("BodyLow", 1, 5, 2.0, 1)],
                ],
                "shadow": [5.0],
                "proxy": 9.0,
            }
        ],
        _TEXTURES,
    )


def test_model_header_lists_every_buffer_in_stream_order():
    h, s = _lod_model()
    M = we.parse_model_header(h)
    assert M["textures"] == _TEXTURES and len(M["parts"]) == 1
    bufs = we.model_stream_layout(M, s)
    assert [(b["kind"], b["lod"], b["format"], b["stride"]) for b in bufs] == [
        ("render", 0, 5, 44),
        ("render", 0, 5, 44),
        ("render", 1, 5, 44),
        ("shadow", None, 9, 20),
        ("proxy", None, 5, 44),
    ]
    assert [b["name"] for b in bufs[:3]] == ["Body", "Leaf", "BodyLow"]
    assert [b["vb"] for b in bufs] == [0, 197, 394, 591, 692]
    assert we.model_stream_layout(M, s + b"\0") is None  # must tile the stream exactly
    assert we.parse_model_header(h[: len(h) // 2]) is None


def test_decode_model_writes_lod0_only_with_file_materials(tmp_path, obj_capture):
    """LOD 0 only, no shadow hull, no proxy slab; the ix == 0 submesh is kept; the
    material comes from the submesh record's texture-list index."""
    h, s = _lod_model()
    assert we.decode_model(h, s, tmp_path / "m.obj") is True
    assert obj_capture["mats"] == ["Trim_02", "Leaf_03"]
    assert [sub[:4] for sub in obj_capture["subs"]] == [(0, 4, 0, 2), (4, 4, 2, 2)]
    assert sorted({v[2] for v in obj_capture["v"]}) == [0.0, 1.0]
    assert obj_capture["tris"] == [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    assert obj_capture["uv"][2] == (1.0, 1.0) and obj_capture["n"][0] == (0.0, 0.0, 1.0)


def test_decode_model_lod_selection(tmp_path, obj_capture):
    h, s = _lod_model()
    assert we.decode_model(h, s, tmp_path / "m.obj", lod=1) is True
    assert obj_capture["mats"] == ["Trim_02"] and {v[2] for v in obj_capture["v"]} == {2.0}
    assert we.decode_model(h, s, tmp_path / "m.obj", lod="all") is True
    assert obj_capture["mats"] == ["Trim_02", "Leaf_03", "Trim_02"]
    assert sorted({v[2] for v in obj_capture["v"]}) == [0.0, 1.0, 2.0]  # never 5.0 / 9.0
    # a part with fewer LODs keeps its last one
    assert we.decode_model(h, s, tmp_path / "m.obj", lod=7) is True
    assert {v[2] for v in obj_capture["v"]} == {2.0}


def test_decode_model_finds_a_buffer_far_behind_a_shadow_hull(tmp_path, obj_capture):
    """Offsets are computed, so a render buffer behind >64 KB of other data (the old
    search window) is still found."""
    h, s = _model(
        [
            {"lods": [[("A", 0, 5, 0.0, 1)]], "shadow": [5.0]},
            {"name": "Part2", "parent": 0, "lods": [[("B", 1, 5, 3.0, 1)]]},
        ],
        _TEXTURES,
    )
    M = we.parse_model_header(h)
    pad = 70000  # grow the first part's shadow hull: nv x 20 bytes of vertices
    nv = pad // 20
    big_v = b"".join(_vertex(9, (i, 0, 5.0)) for i in range(nv))
    old_hull = _bulk(*_quad(9, 5.0)[:2])
    new_hull = _bulk(big_v, struct.pack("<6H", 0, 1, 2, 0, 2, 3))
    assert s.count(old_hull) == 1
    s2 = s.replace(old_hull, new_hull)
    h2 = h.replace(_meshbuffer(9, 4, 12), _meshbuffer(9, nv, 12))
    assert h2 != h and we.model_stream_layout(we.parse_model_header(h2), s2) is not None
    assert we.decode_model(h2, s2, tmp_path / "m.obj") is True
    assert obj_capture["mats"] == ["Wall_01", "Trim_02"]
    assert sorted({v[2] for v in obj_capture["v"]}) == [0.0, 3.0]
    assert M["parts"][1]["name"] == "Part2"


def test_decode_model_mesh_exposes_colour_tangents_and_skin():
    h, s = _model([{"lods": [[("Skin", 0, 6, 0.0, 1)]], "shadow": [1.0], "proxy": 2.0}], _TEXTURES)
    mesh = we.decode_model_mesh(h, s)
    assert [m["name"] for m in mesh["submeshes"]] == ["Skin"]
    m = mesh["submeshes"][0]
    assert (m["format"], m["stride"], m["material"], m["texture"]) == (
        6,
        56,
        "Wall_01",
        _TEXTURES[0],
    )
    assert m["color"].tolist() == [[10, 20, 30, 40]] * 4  # RGBA from D3DCOLOR bytes B,G,R,A
    assert m["tangent"].tolist() == [[1.0, 0.0, 0.0]] * 4
    assert m["bitangent"].tolist() == [[0.0, -1.0, 0.0]] * 4
    assert m["joints"].tolist() == [[1, 2, 3, 4]] * 4  # idx0..3 = bytes +46, +45, +44, +47
    assert m["weights"].tolist() == [[0.75, 0.25, 0.0, 0.0]] * 4
    assert m["triangles"] == [(0, 1, 2), (0, 2, 3)]
    t = we.gltf_tangents(m["normals"], m["tangent"], m["bitangent"])
    assert t.tolist() == [[1.0, 0.0, 0.0, -1.0]] * 4  # cross(n, t) = +y, stored bitangent = -y
    kinds = [
        x["kind"]
        for x in we.decode_model_mesh(h, s, kinds=("render", "shadow", "proxy"))["submeshes"]
    ]
    assert kinds == ["render", "shadow", "proxy"]


def test_model_effects_header_is_a_modelres(tmp_path, obj_capture):
    h, s = _model(
        [{"lods": [[("Rubble", 2, 5, 0.0, 1)]]}],
        _TEXTURES,
        typename="ModelEffects(ModelRes)",
        bag_dwords=96,
    )
    assert we.parse_model_header(h)["type"] == "ModelEffects(ModelRes)"
    assert we.decode_model(h, s, tmp_path / "m.obj") is True
    assert obj_capture["mats"] == ["Leaf_03"]


def test_headers_outside_the_engine_layout_fall_back_to_the_scan():
    assert we.parse_model_header(b"") is None
    assert we.parse_model_header(_str("Texture") + b"\0" * 64) is None
    h, s = _lod_model()
    assert we.parse_model_header(h, ">") is None
    assert we.decode_model_mesh(h, s[:-1]) is None


# ---------------------------------------------------------------------------
# 5. parse_model_nodes
# ---------------------------------------------------------------------------


def test_parse_model_nodes_reads_every_part_as_a_node():
    """Names the name-anchored scan rejects ('-', digits first) used to drop the node
    and shift every later parent index."""
    q = (0.0, math.sin(0.25), 0.0, math.cos(0.25))
    h, _s = _model(
        [
            {},
            {"name": "Bip01", "parent": 0, "pos": (0, 1, 0)},
            {"name": "01-Odd Name", "parent": 1, "pos": (0, 2, 0), "quat": q},
            {"name": "Bip01 Head", "parent": 2, "pos": (0, 3, 0)},
        ],
        _TEXTURES,
    )
    names, pos, quat, parent = pmn.parse(h)
    assert names == ["(root)", "Bip01", "01-Odd Name", "Bip01 Head"]
    assert parent.tolist() == [-1, 0, 1, 2]
    assert pos[:, 1].tolist() == [0.0, 1.0, 2.0, 3.0]
    assert quat[2].tolist() == pytest.approx(list(q))
    assert pmn.parse_header_driven(b"\0" * 64) is None


# ---------------------------------------------------------------------------
# 6. .sequence
# ---------------------------------------------------------------------------


def _key(t, value, handles=None, mode=0):
    b = struct.pack("<fII", t, mode, len(value)) + struct.pack("<%df" % len(value), *value)
    if handles is not None:
        b += struct.pack("<I", len(handles))
        for (it, iv), (ot, ov) in handles:
            b += struct.pack("<4f", it, iv, ot, ov)
    return b


def _track(prop, interp, keys):
    return _str(prop) + struct.pack("<II", interp, len(keys)) + b"".join(keys)


def _object(cls, tracks, path="", ids=(0x1AA8AA9B,), flag=0):
    b = _str(path) + struct.pack("<II", flag, len(ids))
    b += struct.pack("<%dI" % len(ids), *ids) + _str(cls)
    return b + struct.pack("<I", len(tracks)) + b"".join(tracks)


def _sequence(objects, duration=2.5, flags=1):
    return struct.pack("<fII", duration, flags, len(objects)) + b"".join(objects)


def _door_sequence():
    hk = lambda t, v: [((t - 0.1, v), (t + 0.1, v))]
    return _sequence(
        [
            _object(
                "AIStaticPathObjectNode",
                [_track("impassable", 1, [_key(0, [0.0]), _key(1, [1.0])])],
            ),
            _object(
                "Model",
                [
                    _track(
                        "localorient",
                        3,
                        [
                            _key(0.0, [0, 0, 0, 1], [((-0.1, 0), (0.1, 0))] * 3),
                            _key(
                                2.0,
                                [0, 90, 0, 0],
                                [
                                    ((1.9, 0), (2.1, 0)),
                                    ((1.5, 90), (2.5, 90)),
                                    ((1.9, 0), (2.1, 0)),
                                ],
                            ),
                        ],
                    ),
                    _track(
                        "opacity",
                        2,
                        [_key(0.0, [0.0], hk(0.0, 0.0)), _key(2.0, [1.0], hk(2.0, 1.0))],
                    ),
                ],
            ),
            _object(
                "Sprite",
                [_track("visible", 1, [_key(0.5, [1.0])])],
                path="/art/ui/x.fragment#a",
                ids=(),
            ),
        ]
    )


def test_sequence_engine_grammar():
    d = ds.parse(_door_sequence())
    assert d["format"] == ds.FORMAT and d["duration"] == pytest.approx(2.5)
    assert d["version"] == d["duration"] and d["parsed_bytes"] == d["file_bytes"]
    assert [o["class"] for o in d["objects"]] == ["AIStaticPathObjectNode", "Model", "Sprite"]
    assert d["objects"][0]["ids"] == ["1aa8aa9b"] and "path" not in d["objects"][0]
    assert d["objects"][2]["path"] == "/art/ui/x.fragment#a" and "ids" not in d["objects"][2]
    imp = d["objects"][0]["tracks"][0]
    assert (imp["interpolation"], imp["spline"], imp["nkeys"]) == ("step", False, 2)
    assert "handles" not in imp["keys"][0]
    orient, opacity = d["objects"][1]["tracks"]
    assert (orient["prop"], orient["interpolation"], orient["spline"]) == (
        "localorient",
        "spline",
        True,
    )
    assert orient["value_type"] == "quaternion" and opacity["value_type"] == "number"
    k = orient["keys"][1]
    assert k["value"] == [0.0, 90.0, 0.0, 0.0] and k["euler_deg"] == [0.0, 90.0, 0.0]
    assert k["in"] == [[1.9, 0.0], [1.5, 90.0], [1.9, 0.0]]
    assert k["out"] == [[2.1, 0.0], [2.5, 90.0], [2.1, 0.0]]
    assert k["handles"][4:8] == [1.5, 90.0, 2.5, 90.0]  # file order kept
    assert k["quat"] == pytest.approx([0, math.sqrt(0.5), 0, math.sqrt(0.5)], abs=1e-6)
    assert opacity["keys"][0]["in"] == [[-0.1, 0.0]]


def test_sequence_exact_parse_rejects_trailing_or_missing_bytes():
    b = _door_sequence()
    assert ds.parse_exact(b) is not None
    assert ds.parse_exact(b + b"\0") is None and ds.parse_exact(b[:-1]) is None
    out = ds.parse(b[:-1])  # falls back to the scanning parser, never raises
    assert isinstance(out, dict) and "format" not in out


def test_sequence_key_class_without_a_type_table_entry():
    """Unknown property names: the key class is the one that parses to the end."""
    hk = lambda t, v: [((t - 0.1, v), (t + 0.1, v))]
    b = _sequence(
        [
            _object(
                "Thing",
                [
                    _track(
                        "zzNotARealProp",
                        3,
                        [_key(0, [1.0], hk(0, 1.0)), _key(1, [2.0], hk(1, 2.0))],
                    ),
                    _track("zzAlsoMadeUp", 1, [_key(0, [1.0]), _key(1, [0.0])]),
                ],
            )
        ]
    )
    t0, t1 = ds.parse(b)["objects"][0]["tracks"]
    assert (t0["spline"], t0["value_type"], t0["value_type_source"]) == (True, "number", "inferred")
    assert (t1["spline"], t1["value_type"]) == (False, None)


def test_sequence_property_type_table():
    assert ds.property_type("localpos") == "vector"
    assert ds.property_type("localorient") == "quaternion"
    assert ds.property_type("enabled") == "truth"
    assert ds.property_type("zzNotARealProp") is None


def test_sequence_evaluate_matches_the_engine_formulas():
    d = ds.parse(_door_sequence())
    imp = d["objects"][0]["tracks"][0]
    orient, opacity = d["objects"][1]["tracks"]
    assert ds.evaluate(imp, 0.5) == [0.0] and ds.evaluate(imp, 5.0) == [1.0]  # step: start key
    assert ds.evaluate(opacity, 0.5) == pytest.approx([0.25])  # linear
    assert ds.evaluate(opacity, -1.0) == [0.0]
    # spline: flat handles at both ends -> smoothstep 3u^2 - 2u^3 (FUN_0040f5a1)
    for t in (0.0, 0.5, 1.0, 1.5, 2.0):
        u = t / 2.0
        got = ds.evaluate(orient, t)
        assert got == pytest.approx([0.0, 90.0 * (3 * u * u - 2 * u * u * u), 0.0], abs=1e-4)
    # a sloped out-handle: m0 = (out.v - v0) / (out.t - t0) scaled by the segment
    tr = {
        "type": 3,
        "keys": [
            {"t": 0.0, "mode": 0, "value": 0.0, "in": [[-1.0, 0.0]], "out": [[1.0, 2.0]]},
            {"t": 2.0, "mode": 0, "value": 4.0, "in": [[1.0, 2.0]], "out": [[3.0, 6.0]]},
        ],
    }
    assert ds.evaluate(tr, 1.0) == pytest.approx([2.0])  # slopes 2 at both ends -> a line
    tr["keys"][0]["mode"] = 1  # the START key's own interpolation overrides the track's
    assert ds.evaluate(tr, 1.0) == [0.0]


def test_sequence_euler_degrees_to_quaternion_order():
    """q = qx * qy * qz (FUN_00499733)."""
    s = math.sqrt(0.5)
    assert ds.euler_deg_to_quat(90, 0, 0) == pytest.approx((s, 0, 0, s))
    assert ds.euler_deg_to_quat(0, 0, 90) == pytest.approx((0, 0, s, s))
    x, y, z, w = ds.euler_deg_to_quat(90, 90, 0)
    assert (x, y, z, w) == pytest.approx((0.5, 0.5, 0.5, 0.5))
    assert ds.euler_deg_to_quat(0, 0, 0) == (0.0, 0.0, 0.0, 1.0)
