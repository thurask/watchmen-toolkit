"""The one character mesh loader (wlib/mesh_loader.py), the half-float rule and
the numpy vertex decoder.

    header path   a model whose header parses and whose buffers consume the
                  stream exactly is read from the header (the scan is never
                  called); a buffer the header lists without a geometry
                  descriptor (a triangle strip) is decoded as a strip
    fallback      a model without a usable header is scanned, and every
                  scanned submesh is logged
    failures      a triangle naming a vertex the buffer lacks marks the piece
                  not decoded; degenerate triangles are counted and logged; a
                  palette name without a bind slot is logged and stated in the
                  GLB extras; a skin influence outside the palette is dropped
                  (weight 0, the rest renormalised), never clamped onto
                  another bone; a vertex left with no weight drops its piece
    callers       char_lib.load_parts, variant_glb.load_parts, the weapon
                  attachment and export_female_anims.mesh_arrays all read
                  through it; one unreadable archive block is logged
    half floats   _half equals numpy's float16 on all 65,536 codes; a
                  non-finite normal or UV drops that attribute with a note
                  and never reaches an OBJ
    _decode_sub   the numpy version equals the per-vertex struct loop bit for
                  bit (PC and console layouts, random streams)

Synthetic fixtures only (the builders of test_p3_part1_model,
test_v120_regressions and test_p2_console_chars)."""

import struct

import numpy as np
import pytest

import char_lib
import characters_export as ce
import export_female_anims as efa
import mesh_loader as ml
import variant_glb as vg
import watchmen_extract as we

import test_p2_console_chars as tc
import test_p3_part1_model as tm
import test_v120_regressions as tv

#: the geometry descriptor of each of tm.build()'s three render buffers
#: (Body lod 0, BodyLow lod 1, Spine): [8][4 vertices][format 5][8][12][list]
_DESC = struct.pack("<6I", 8, 4, 5, 8, 12, 1)


def _lines(capsys):
    return capsys.readouterr().out.splitlines()


@pytest.fixture
def no_scan(monkeypatch):
    """The descriptor scan raises: a test using it proves the header path ran."""

    def boom(*a, **k):
        raise AssertionError("the descriptor scan ran")

    monkeypatch.setattr(ml, "_scan_one", boom)


@pytest.fixture(autouse=True)
def _fresh_notes():
    char_lib.dropped_pieces(reset=True)
    char_lib.dropped_palette_names(reset=True)
    yield
    char_lib.dropped_pieces(reset=True)
    char_lib.dropped_palette_names(reset=True)


# ---------------------------------------------------------------------------
# header path / fallback
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bo, console, stride", [("<", None, 44), (">", "x360", 32), (">", "ps3", 32)]
)
def test_the_header_path_is_used_when_the_header_applies(no_scan, capsys, bo, console, stride):
    h, s = tm.build(bo, "part2", console=console)
    subs, rep = ml.load_submeshes(h, s, "M", skin=False, attrs=False)
    assert [sb["path"] for sb in subs] == ["header"] * 3
    assert rep["header"] == rep["submeshes"] == 3 and rep["scanned"] == 0
    assert [sb["stride"] for sb in subs] == [stride] * 3
    # part-local, as stored (Body z 0, BodyLow z 2, Spine z 1)
    assert np.allclose(subs[0]["V"], [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    assert np.allclose(subs[1]["V"][:, 2], 2.0) and np.allclose(subs[2]["V"][:, 2], 1.0)
    assert subs[0]["T"].tolist() == [[0, 1, 2], [0, 2, 3]]
    assert np.allclose(subs[0]["UV"], [(0, 0), (1, 0), (1, 1), (0, 1)])
    assert subs[0]["vb"] == 0 and all(sb["primitive"] == "triangle_list" for sb in subs)
    assert "scanned" not in capsys.readouterr().out


def test_the_header_path_gives_what_the_scan_gives(monkeypatch):
    """Same vertices, UVs, triangles and offsets from both paths."""
    h, s = tm.build("<", "part2")
    by_header, _ = ml.load_submeshes(h, s, "M", skin=False, attrs=False, log=None)
    monkeypatch.setattr(ml, "_header_path", lambda mh, ms, order: (None, "test"))
    by_scan, rep = ml.load_submeshes(h, s, "M", skin=False, attrs=False, log=None)
    assert rep["scanned"] == 3 and [sb["path"] for sb in by_scan] == ["flat"] * 3  # planar quads
    for a, b in zip(by_header, by_scan):
        assert a["vb"] == b["vb"] and a["material"] == b["material"]
        for k in ("V", "UV", "T"):
            assert np.array_equal(a[k], b[k])


def test_a_model_without_a_usable_header_is_scanned_and_logged(capsys):
    hdr, stream = tv.skinned_model("<", [(i % 5, 0, 0, 0) for i in range(8)], names=tv.MESH_NODES)
    subs, rep = ml.load_submeshes(hdr, stream, "Body")
    assert rep["scanned"] == 1 and rep["header"] == 0 and subs[0]["path"] == "scan"
    out = capsys.readouterr().out
    assert (
        "  note: Body sub0: header path not applicable (the header does not parse as a "
        "ModelRes); scanned" in out
    )
    assert rep["scan_reasons"] == ["the header does not parse as a ModelRes"]


def test_the_console_scan_switch_is_named_as_the_reason(monkeypatch, capsys):
    monkeypatch.setenv("WATCHMEN_CONSOLE_MODELS", "scan")
    h, s = tm.build(">", "part2", console="x360")
    subs, rep = ml.load_submeshes(h, s, "M", skin=False, attrs=False)
    assert rep["scanned"] == 3 and len(subs) == 3
    assert "header path not applicable (WATCHMEN_CONSOLE_MODELS=scan); scanned" in (
        capsys.readouterr().out
    )


def test_a_strip_buffer_is_decoded_as_a_strip(no_scan):
    """A strip has no geometry descriptor (the descriptor's last word is the
    primitive type, find_descriptors wants 1): the header alone knows it."""
    h, s = tm.build("<", "part2")
    k = h.rindex(_DESC)  # Spine's buffer
    h = h[:k] + struct.pack("<6I", 8, 4, 5, 8, 12, 0) + h[k + len(_DESC) :]
    assert len(we.find_descriptors(h, "<")) == 2
    subs, rep = ml.load_submeshes(h, s, "M", skin=False, attrs=False)
    assert rep["strips"] == 1 and len(subs) == 3
    spine = subs[2]
    assert spine["primitive"] == "triangle_strip" and spine["path"] == "header"
    # indices 0 1 2 0 2 3 as a strip: (0,1,2), (0,2,1), [2,0,2 repeats], (3,2,0)
    assert spine["T"].tolist() == [[0, 1, 2], [0, 2, 1], [3, 2, 0]]
    # read as a list it would have been (0,1,2), (0,2,3)
    assert np.allclose(spine["V"][:, 2], 1.0)


def test_a_triangle_naming_a_missing_vertex_drops_the_piece(no_scan, capsys):
    h, s = tm.build("<", "part2")
    M = we.parse_model_header(h, "<")
    we.model_stream_layout(M, s, "<")
    ib = M["buffers"][0]["ib"]  # Body: indices 0 1 2 0 2 3 -> 0 1 9 0 2 3
    s = s[: ib + 4] + struct.pack("<H", 9) + s[ib + 6 :]
    subs, rep = ml.load_submeshes(h, s, "Bad", skin=False, attrs=False)
    assert [sb["index"] for sb in subs] == [1, 2] and rep["not_decoded"] == 1
    (d,) = char_lib.dropped_pieces()
    assert d["model"] == "Bad" and d["submesh"] == 0
    assert d["reason"] == "the index buffer names vertex 9 of a 4-vertex buffer"
    assert "WARNING: Bad: submesh 0 (4 vertices, stride 44, 12 index bytes" in (
        capsys.readouterr().out
    )


def test_degenerate_triangles_are_counted_and_logged(no_scan, capsys):
    h, s = tm.build("<", "part2")
    M = we.parse_model_header(h, "<")
    we.model_stream_layout(M, s, "<")
    ib = M["buffers"][0]["ib"]  # Body: 0 1 2 0 2 3 -> 0 1 2 0 2 2
    s = s[: ib + 10] + struct.pack("<H", 2) + s[ib + 12 :]
    subs, rep = ml.load_submeshes(h, s, "Deg", skin=False, attrs=False)
    assert subs[0]["T"].tolist() == [[0, 1, 2]] and rep["degenerate_triangles"] == 1
    assert "  note: Deg sub0: 1 degenerate triangle (an index repeated) left out" in (
        capsys.readouterr().out
    )
    assert char_lib.dropped_pieces() == []


# ---------------------------------------------------------------------------
# palette and skin
# ---------------------------------------------------------------------------
def test_palette_remap_is_the_rotate_by_one_list_of_names_with_a_slot(capsys):
    hdr, _ = tv.skinned_model("<", [(0, 0, 0, 0)] * 8, names=tv.MESH_NODES)
    remap, lost = ml.palette_remap(hdr, "<", tv.PALETTE, "Body")
    assert remap.tolist() == tv.EXPECTED_REMAP
    # 'GamePivot' comes before names with a slot (the list is shortened there);
    # 'Dummy01' after the last one
    assert lost == [
        {"name": "GamePivot", "where": ml.MID_LIST},
        {"name": "Dummy01", "where": ml.AFTER_LAST},
    ]
    out = capsys.readouterr().out
    assert (
        "  ! Body: palette name 'GamePivot' has no bind slot - rotate-by-one list shortened" in out
    )
    assert "  note: Body: palette name 'Dummy01' has no bind slot; it comes after" in out


def test_the_after_list_note_is_logged_once_per_model_and_glb(capsys):
    """A model loaded again (an outfit, an alternative part) does not repeat the
    note; the warning of a name inside the list is repeated every time."""
    hdr, _ = tv.skinned_model("<", [(0, 0, 0, 0)] * 8, names=tv.MESH_NODES)
    for _ in range(2):
        ml.palette_remap(hdr, "<", tv.PALETTE, "Body")
    out = capsys.readouterr().out
    assert out.count("note: Body: palette name 'Dummy01'") == 1
    assert out.count("! Body: palette name 'GamePivot'") == 2
    char_lib.dropped_palette_names(reset=True)  # the next character GLB
    ml.palette_remap(hdr, "<", tv.PALETTE, "Body")
    assert "note: Body: palette name 'Dummy01'" in capsys.readouterr().out


def test_a_palette_name_without_a_slot_reaches_the_glb_extras(tmp_path, capsys):
    # palette indices 1..4 only: index 0 is the one 'Dummy01' (after the list) changes
    joints = [(1 + i % 4, 0, 0, 0) for i in range(8)]
    hdr, stream = tv.skinned_model("<", joints, names=tv.MESH_NODES)
    base = tc._write_model(tmp_path, "Body", hdr, stream)
    parts = char_lib.load_parts([base], tv.PALETTE)
    assert len(parts) == 1
    names = char_lib.dropped_palette_names()
    assert names == [{"model": "Body", "name": "GamePivot", "where": ml.MID_LIST}]
    nd = ce.not_decoded_extras([parts], palette_names=names)["not_decoded"]
    assert nd["palette_names"] == names
    assert "palette_names" not in ce.not_decoded_extras([parts])["not_decoded"]
    assert char_lib.dropped_palette_names(reset=True) == names
    assert char_lib.dropped_palette_names() == []


def test_a_weighted_index_0_is_flagged_when_a_name_after_the_list_has_no_slot(tmp_path, capsys):
    hdr, stream = tv.skinned_model("<", [(0, 0, 0, 0)] * 8, names=tv.MESH_NODES)
    base = tc._write_model(tmp_path, "Body", hdr, stream)
    char_lib.load_parts([base], tv.PALETTE)
    out = capsys.readouterr().out
    assert "  ! Body sub0: 8 weighted influence(s) use palette index 0, which the names" in out
    assert {"model": "Body", "name": "Dummy01", "where": ml.AFTER_LAST} in (
        char_lib.dropped_palette_names()
    )


def test_remap_skin_drops_an_index_outside_the_palette_instead_of_clamping():
    remap = np.array([4, 0, 1, 2, 3])
    I = np.array([[1, 7, 0, 0], [2, 0, 0, 0], [9, 0, 0, 0]], np.uint8)
    W = np.array([[0.5, 0.5, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]], np.float32)
    SI, SW, st = ml.remap_skin(I, W, remap)
    assert SI.dtype == np.uint16 and SW.dtype == np.float32
    assert SI[0].tolist() == [0, 0, 4, 4] and SW[0].tolist() == [1.0, 0.0, 0.0, 0.0]
    assert SI[1].tolist() == [1, 4, 4, 4] and SW[1].tolist() == [1, 0, 0, 0]  # untouched
    # 1.4.0 clamped 7 and 9 onto remap[4] = slot 3 with their full weight
    assert SW[2].tolist() == [0, 0, 0, 0]
    assert st == {
        "oob_influences": 2,
        "oob_zero_weight": 0,
        "vertices_changed": 2,
        "vertices_unweighted": 1,
        "max_index": 9,
    }
    # no index outside: the 1.4.0 arrays, bit for bit
    I2 = np.array([[1, 2, 0, 0]], np.uint8)
    W2 = np.array([[0.25, 0.75, 0, 0]], np.float32)
    SI2, SW2, st2 = ml.remap_skin(I2, W2, remap)
    assert SI2.tolist() == [[0, 1, 4, 4]] and SW2.tobytes() == W2.tobytes()
    assert st2["oob_influences"] == st2["vertices_changed"] == 0


def _skin(stream, vi, joints, weights, stride=56):
    """Rewrite the PC skin of vertex `vi` (joint quad BGRA @44, half4 @48)."""
    b = bytearray(stream)
    o = vi * stride
    j0, j1, j2, j3 = joints
    b[o + 44 : o + 48] = bytes([j2, j1, j0, j3])
    b[o + 48 : o + 56] = struct.pack("<4e", *weights)
    return bytes(b)


def test_an_influence_outside_the_palette_is_logged_and_its_weight_dropped(tmp_path, capsys):
    hdr, stream = tv.skinned_model("<", [(1, 0, 0, 0)] * 8, names=tv.MESH_NODES)
    stream = _skin(stream, 3, (1, 7, 0, 0), (0.5, 0.5, 0, 0))
    base = tc._write_model(tmp_path, "Body", hdr, stream)
    (part,) = char_lib.load_parts([base], tv.PALETTE)
    SI, SW = part[1], part[2]
    assert SI[3, 0] == tv.EXPECTED_REMAP[1] and SW[3].tolist() == [1, 0, 0, 0]
    assert SI[3, 1] == 0  # the dropped influence: joint 0, weight 0
    assert (SW.sum(1) == 1).all()
    assert (
        "  ! Body sub0: 1 skin influence(s) name palette index 7 of a 5-entry palette: weight "
        "dropped (1 vertices renormalised), not clamped onto another bone"
        in capsys.readouterr().out
    )
    assert char_lib.dropped_pieces() == []


def test_a_zero_weight_influence_outside_the_palette_is_a_note_not_a_problem(tmp_path, capsys):
    """Weight 0 already: nothing is dropped, the arrays are what they would be with
    an index inside the palette, and the log has no '!' line for it."""
    import watchmen_extract as wx

    hdr, stream = tv.skinned_model("<", [(1, 0, 0, 0)] * 8, names=tv.MESH_NODES)
    ref = tc._write_model(tmp_path, "Ref", hdr, stream)
    (want,) = char_lib.load_parts([ref], tv.PALETTE)
    capsys.readouterr()
    stream = _skin(stream, 3, (1, 7, 0, 0), (1.0, 0, 0, 0))  # index 7 with weight 0
    base = tc._write_model(tmp_path, "Body", hdr, stream)
    (part,) = char_lib.load_parts([base], tv.PALETTE)
    out = capsys.readouterr().out
    import variant_glb

    # JOINTS_0 as written (a zero-weight slot is joint 0 either way) and WEIGHTS_0
    uj = variant_glb.used_joints
    assert uj(part[1], part[2]).tolist() == uj(want[1], want[2]).tolist()
    assert part[2].tobytes() == want[2].tobytes()
    # (the fixture's own lines aside: byte order, palette names)
    assert not [ln for ln in out.splitlines() if wx.is_warning_line(ln) and "influence" in ln]
    assert "influence" in out
    assert (
        "  note: Body sub0: 1 zero-weight skin influence(s) name an index past the 5-entry "
        "palette: written as joint 0, skinning unchanged" in out
    )
    # both kinds in one piece: the '!' line counts and names the weighted ones only
    stream = _skin(stream, 4, (1, 9, 0, 0), (0.5, 0.5, 0, 0))
    base = tc._write_model(tmp_path, "Body2", hdr, stream)
    char_lib.load_parts([base], tv.PALETTE)
    out = capsys.readouterr().out
    assert (
        "  ! Body2 sub0: 1 skin influence(s) name palette index 9 of a 5-entry palette: weight "
        "dropped (1 vertices renormalised)" in out
    )
    assert "  note: Body2 sub0: 1 zero-weight skin influence(s)" in out


def test_a_vertex_weighted_only_outside_the_palette_drops_its_piece(tmp_path, capsys):
    hdr, stream = tv.skinned_model("<", [(1, 0, 0, 0)] * 8, names=tv.MESH_NODES)
    stream = _skin(stream, 5, (8, 0, 0, 0), (1, 0, 0, 0))
    base = tc._write_model(tmp_path, "Body", hdr, stream)
    assert char_lib.load_parts([base], tv.PALETTE) == []
    (d,) = char_lib.dropped_pieces()
    assert d["reason"] == "1 of 8 vertices are weighted only to joints outside the 5-entry palette"
    assert "NOT exported" in capsys.readouterr().out


def test_a_rigid_piece_in_a_skinned_list_is_stated_not_raised(tmp_path, capsys):
    """1.4.0 raised TypeError on a piece without joints (decode_skin -> None)."""
    hdr, stream = tc.console_rigid_model()
    base = tc._write_model(tmp_path, "Prop", hdr, stream)
    assert char_lib.load_parts([base], tv.PALETTE) == []
    (d,) = char_lib.dropped_pieces()
    assert d["reason"] == char_lib.NO_SKIN


def test_variant_glb_drops_an_outside_index_too(monkeypatch):
    """variant_glb.load_parts clamped twice (to the remap, then to the bind)."""
    hdr, stream = tv.skinned_model("<", [(1, 0, 0, 0)] * 8, names=tv.MESH_NODES)
    stream = _skin(stream, 2, (2, 9, 0, 0), (0.25, 0.75, 0, 0))
    monkeypatch.setattr(
        vg.efa, "iter_blocks", lambda naz, streams=True: iter([("blk", {"h": b"H", "s": b"S"})])
    )
    monkeypatch.setattr(
        we, "extract_block", lambda h, s: iter([(tv._Entry("/x/Body.model"), hdr, stream)])
    )
    (part,) = vg.load_parts(["Body"], tv.PALETTE, naz="does-not-exist.naz")
    assert part[1][2, 0] == tv.EXPECTED_REMAP[2] and part[2][2].tolist() == [1, 0, 0, 0]


# ---------------------------------------------------------------------------
# callers
# ---------------------------------------------------------------------------
def test_the_weapon_attachment_reads_the_header(no_scan, tmp_path):
    h, s = tm.build("<", "part2")
    base = tc._write_model(tmp_path, "Club", h, s)
    bind = str(tmp_path / "bind.npz")
    np.savez(bind, Rb=np.stack([np.eye(3)] * 2), tb=np.array([[0.0, 0, 0], [1.0, 2.0, 3.0]]))
    parts = ce._weapon_attach_parts(base, 1, bind, ["Root", "Attach RHand"])
    assert len(parts) == 3
    assert np.allclose(parts[0][0][0], (1, 2, 3)) and (parts[0][1] == 1).all()


def test_one_unreadable_block_is_logged_and_the_walk_goes_on(monkeypatch, capsys):
    hdr, stream = tv.skinned_model("<", [(i % 5, 0, 0, 0) for i in range(8)], names=tv.MESH_NODES)
    blocks = [("/Levels/A/Bad.block", {"h": b"bad", "s": b""}), ("/L/Good", {"h": b"H", "s": b"S"})]
    monkeypatch.setattr(vg.efa, "iter_blocks", lambda naz, streams=True: iter(blocks))

    def extract_block(h, s):
        if h == b"bad":
            raise ValueError("truncated block")
        return iter([(tv._Entry("/x/Body.model"), hdr, stream)])

    monkeypatch.setattr(we, "extract_block", extract_block)
    assert len(vg.load_parts(["Body"], tv.PALETTE, naz="x.naz")) == 1
    assert "  ! block Bad.block: truncated block" in capsys.readouterr().out


def test_an_interrupt_during_the_walk_is_not_swallowed(monkeypatch):
    """1.4.0 had a bare `except:` there."""
    monkeypatch.setattr(
        vg.efa, "iter_blocks", lambda naz, streams=True: iter([("blk", {"h": b"H", "s": b"S"})])
    )

    def interrupt(h, s):
        raise KeyboardInterrupt

    monkeypatch.setattr(we, "extract_block", interrupt)
    with pytest.raises(KeyboardInterrupt):
        vg.load_parts(["Body"], tv.PALETTE, naz="x.naz")


def test_export_female_anims_reads_its_body_through_the_loader(capsys):
    hdr, stream = tv.skinned_model(
        "<", [(i % 5, 0, 0, 0) for i in range(8)], names=tv.MESH_NODES, nsub=2
    )
    V, SI, SW, T, subs = efa.mesh_arrays(hdr, stream, "Body")
    assert len(V) == 16 and SI.dtype == np.uint8 and SW.dtype == np.float32
    assert SI[:, 0].tolist() == [i % 5 for i in range(8)] * 2  # palette indices, as stored
    assert subs == [(0, 8, 0, 6), (8, 8, 6, 6)] and T[6] == (8, 9, 10)


# ---------------------------------------------------------------------------
# half floats and _decode_sub
# ---------------------------------------------------------------------------
def test_half_equals_numpy_float16_on_every_code():
    codes = np.arange(65536, dtype=np.uint16)
    ref = codes.view("<f2").astype(np.float64)
    got = np.array([we._half(int(c)) for c in codes], np.float64)
    fin = np.isfinite(ref)
    assert np.array_equal(np.isfinite(got), fin)
    assert got[fin].tobytes() == ref[fin].tobytes()  # bit for bit, -0.0 included
    assert np.array_equal(np.isnan(got), np.isnan(ref))
    assert np.array_equal(np.isinf(got) & (got > 0), np.isinf(ref) & (ref > 0))
    assert we._half(0x7C00) == float("inf") and we._half(0xFC00) == float("-inf")


def _random_stream(rng, nv, stride, be, finite=True):
    b = bytearray(rng.integers(0, 256, nv * stride + 7, dtype=np.uint8).tobytes())
    pf, hf = (">f4", ">f2") if be else ("<f4", "<f2")
    for i in range(nv):
        o = i * stride
        b[o : o + 12] = rng.normal(0, 3, 3).astype(pf).tobytes()
        if finite:
            if not be:
                b[o + 12 : o + 18] = rng.normal(0, 1, 3).astype(hf).tobytes()
            uo = o + (20 if be else 24)
            b[uo : uo + 4] = rng.normal(0, 2, 2).astype(hf).tobytes()
    return bytes(b)


def _bits_equal(p, q):
    """The same double bit for bit (-0.0 included); two NaNs count as equal: Python
    3.14's struct keeps a signalling NaN's payload where numpy's float32 -> float64
    conversion quiets it (measured: 35 of 50,513 values of this test differ in
    nothing but that bit on 3.14.6; none on 3.8 or 3.13)."""
    if p != p and q != q:
        return True
    return struct.pack("<d", p) == struct.pack("<d", q)


def _same(a, b):
    if a is None or b is None:
        return a is b
    return (
        type(a) is type(b)
        and len(a) == len(b)
        and all(
            type(x) is type(y)
            and len(x) == len(y)
            and all(type(p) is float and _bits_equal(p, q) for p, q in zip(x, y))
            for x, y in zip(a, b)
        )
    )


@pytest.mark.parametrize(
    "be, stride",
    [
        (False, 44),
        (False, 56),
        (False, 20),
        (False, 12),
        (True, 32),
        (True, 44),
        (True, 24),
        (True, 20),
    ],
)
def test_decode_sub_equals_the_per_vertex_loop(be, stride):
    rng = np.random.default_rng(stride + 100 * be)
    for nv in (0, 1, 7, 300):
        for finite in (True, False):
            s = _random_stream(rng, nv, stride, be, finite)
            for vbo in (0, 3):
                n1, n2 = [], []
                a = we._decode_sub(s, vbo, nv, stride, be, None, n1)
                b = we._decode_sub_loop(s, vbo, nv, stride, be, None, n2)
                assert all(_same(x, y) for x, y in zip(a, b)), (nv, finite, vbo)
                assert n1 == n2


def test_decode_sub_past_the_end_drops_the_attribute_and_keeps_positions():
    s = struct.pack("<3f", 1, 2, 3) + bytes(14)  # room for the normal, not the UV
    v, n, uv = we._decode_sub(s, 0, 1, 44)
    assert v == [(1.0, 2.0, 3.0)] and n == [(0.0, 0.0, 0.0)] and uv is None
    with pytest.raises(struct.error):
        we._decode_sub(s, 0, 2, 44)  # positions past the end raise, as in 1.4.0


def _vertex(normal=(0, 0, 1), uv=(0.5, 0.5)):
    b = struct.pack("<3f", 0.1, 0.2, 0.3) + struct.pack("<3H", *normal) + bytes(6)
    return b + struct.pack("<2H", *uv) + bytes(16)


_H1, _H05, _INF, _NAN = 0x3C00, 0x3800, 0x7C00, 0x7E00


@pytest.mark.parametrize("decode", [we._decode_sub, we._decode_sub_loop])
def test_a_non_finite_normal_or_uv_drops_that_attribute_with_a_note(decode):
    s = _vertex((0, 0, _H1), (_H05, _H05)) + _vertex((_NAN, 0, _H1), (_H05, _INF))
    notes = []
    v, n, uv = decode(s, 0, 2, 44, False, None, notes)
    assert len(v) == 2 and n is None and uv is None
    assert notes == [
        "1 of 2 normals hold an infinite or NaN half float: normals not written",
        "1 of 2 UVs hold an infinite or NaN half float: UVs not written",
    ]
    v, n, uv = decode(_vertex((0, 0, _H1), (_H05, _H05)) * 2, 0, 2, 44)
    assert n == [(0.0, 0.0, 1.0)] * 2 and uv == [(0.5, 0.5)] * 2


def test_no_nan_reaches_an_obj_or_the_mesh(tmp_path, capsys):
    h, s = tm.build("<", "part2")
    M = we.parse_model_header(h, "<")
    we.model_stream_layout(M, s, "<")
    vb = M["buffers"][0]["vb"]  # Body vertex 1: u = +inf
    s = s[: vb + 44 + 24] + struct.pack("<H", _INF) + s[vb + 44 + 26 :]
    mesh = we.decode_model_mesh(h, s)
    body = mesh["submeshes"][0]
    assert body["uvs"] is None
    assert body["not_finite"] == ["1 of 4 UVs hold an infinite or NaN half float: UVs not written"]
    logged = []
    assert we.decode_model(h, s, tmp_path / "m.obj", log=logged.append) is True
    obj = (tmp_path / "m.obj").read_text()
    assert "nan" not in obj.lower() and "inf" not in obj.lower()
    assert any("UVs hold an infinite or NaN half float" in x for x in logged)
    # the character loader: the piece keeps its geometry, the UV rule of a
    # buffer without UVs, and a note
    subs, _ = ml.load_submeshes(h, s, "M", skin=False, attrs=False)
    assert np.isfinite(subs[0]["UV"]).all() and not subs[0]["UV"].any()
    assert "  note: M sub0: 1 of 4 UVs hold an infinite or NaN half float" in (
        capsys.readouterr().out
    )
