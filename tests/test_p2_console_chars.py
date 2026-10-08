"""Console (big-endian) characters: byte order taken from the model header, the
ragdoll rig on Xbox 360 / PS3, mesh pieces that a tie in the old descriptor-count
rule dropped, and the gaps that are now stated (log line + asset.extras marker)
instead of silent.

Measured on the six exported sets (2026-10-05): 5,490 of 5,490 model headers open
with [u32 length][class name] in exactly one byte order; the count rule picked the
wrong order on 87 (Part 2) / 156 (Part 1) console models.  Everything here is
synthetic and offline; the big-endian fixtures are built in this file.
"""

import json
import pathlib
import os
import struct

import numpy as np
import pytest

import char_lib
import characters_export as ce
import ragdoll_rig as rr
import variant_glb as vg
import watchmen_extract as we

import test_ragdoll_rig as trr
import test_v120_regressions as tv

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _cls(order, name="ModelRes"):
    raw = name.encode("ascii") + b"\0"
    return struct.pack(order + "I", len(raw)) + raw


def _false_descriptor(order, nv=3000, ib=600):
    """A descriptor that parses in `order` only and needs far more stream than
    any fixture here has (0xFF framing: see test_v120_regressions.skinned_model)."""
    return b"\xff" * 4 + struct.pack(order + "6I", 0, nv, 6, 0, ib, 1) + b"\xff" * 8


def console_skinned_model(with_class=True, false_le=True, nv=8):
    """Big-endian single-submesh skinned model whose header ALSO holds one stray
    little-endian descriptor: the two orders tie 1 : 1, as on the real
    Heavies_Sunglasses / Heavies_Chains1 / Biker_Medium_Sunglass."""
    joints = [(i % 5, 0, 0, 0) for i in range(nv)]
    hdr, stream = tv.skinned_model(">", joints, names=tv.MESH_NODES, nv=nv)
    if false_le:
        hdr += _false_descriptor("<")
    if with_class:
        hdr = _cls(">") + hdr
    return hdr, stream


def console_rigid_model(nv=6):
    """Big-endian rigid prop (G=5, stride 32) with the same tie: WPN_2x4_2H."""
    tris = [(i, i + 1, i + 2) for i in range(nv - 2)]
    ib = len(tris) * 6
    hdr = _cls(">") + b"\xff" * 4 + struct.pack(">6I", 0, nv, 5, 0, ib, 1) + b"\xff" * 8
    hdr += _false_descriptor("<")
    vb = bytearray()
    for i in range(nv):
        rec = bytearray(32)
        struct.pack_into(">3f", rec, 0, 0.1 + 0.05 * i, 0.2 + 0.07 * (i % 3), 0.3 + 0.11 * (i % 5))
        vb += rec
    return hdr, bytes(vb) + b"".join(struct.pack(">3H", *t) for t in tris)


def _write_model(tmp_path, name, hdr, stream):
    base = str(tmp_path / name)
    with open(base + ".model", "wb") as f:
        f.write(hdr)
    with open(base + ".model.stream", "wb") as f:
        f.write(stream)
    return base


class _BigEndianStruct:
    """`struct` for test_ragdoll_rig's little-endian builders, writing the console
    form: every field big-endian, and a 64-bit value as two u32 words with the LOW
    word first (what default.pb holds on Xbox 360 and PS3)."""

    def pack(self, fmt, *a):
        if fmt == "<Q":
            return struct.pack(">II", a[0] & 0xFFFFFFFF, a[0] >> 32)
        return struct.pack(">" + fmt[1:] if fmt[:1] == "<" else fmt, *a)

    def __getattr__(self, k):
        return getattr(struct, k)


@pytest.fixture
def big_endian(monkeypatch):
    """Inside the fixture test_ragdoll_rig.build_model / build_pivot_book write
    big-endian files."""
    monkeypatch.setattr(trr, "struct", _BigEndianStruct())


SHEETS = [("Ragdoll", 0.6, 0.0, 1), ("Ragdoll_All", 0.6, 0.0, 0x401)]


def _tree(tmp_path, model, book, name="Female_Skeleton.model"):
    ex = tmp_path / "ex"
    sk = ex / "extracted" / "art" / "characters" / "common" / "skeletons"
    sk.mkdir(parents=True)
    (sk / name).write_bytes(model)
    (ex / "extracted" / "pivotbooks").mkdir()
    (ex / "extracted" / "pivotbooks" / "default.pb").write_bytes(book)
    return ex


def _bind_file(tmp_path, rig):
    Rb, tb = trr._bind(rig)
    p = str(tmp_path / "bind.npz")
    np.savez(p, Rb=Rb, tb=tb, names=np.array(trr.BIND_NAMES), par=np.array([-1, 0, 1, 2, 1]))
    return p


# ---------------------------------------------------------------------------
# byte order: the header says
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("order", ["<", ">"])
def test_header_order_is_read_from_the_class_name_length(order):
    assert char_lib.header_order(_cls(order) + b"\0" * 64) == order
    assert char_lib.header_order(_cls(order, "ModelEffects(ModelRes)") + b"\0" * 8) == order
    assert rr.byte_order(_cls(order) + b"\0" * 64) == order


def test_header_order_is_none_when_the_header_does_not_say():
    assert char_lib.header_order(b"") is None
    assert char_lib.header_order(struct.pack("<I", 6) + b"\x9a\x99\x19\x3f" * 8) is None


def test_the_fixture_ties_the_old_descriptor_count_rule():
    """The condition of the bug: one descriptor in each order."""
    hdr, stream = console_skinned_model()
    le, be = we.find_descriptors(hdr, "<"), we.find_descriptors(hdr, ">")
    assert len(le) == len(be) == 1
    assert sum(nv * st + ib for nv, st, ib in le) > len(stream)  # the false one overruns
    assert char_lib.model_order(hdr, stream, "X") == ">"


def test_model_order_without_a_class_name_rejects_overrunning_descriptors(capsys):
    hdr, stream = console_skinned_model(with_class=False)
    assert char_lib.header_order(hdr) is None
    assert char_lib.model_order(hdr, stream, "Loose.model") == ">"
    out = capsys.readouterr().out
    assert "Loose.model" in out and "byte order not stated by the header" in out
    assert "big-endian taken" in out and "little 0, big 1" in out
    # nothing to go on: little-endian, and the log says it is an assumption
    assert char_lib.model_order(b"\x9a" * 64, b"", "Blank.model") == "<"
    assert "assumed (tie)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# bug 2: pieces dropped on a tie
# ---------------------------------------------------------------------------


def test_char_lib_load_parts_keeps_a_single_submesh_console_model(tmp_path, capsys):
    hdr, stream = console_skinned_model()
    base = _write_model(tmp_path, "Heavies_Sunglasses", hdr, stream)
    char_lib.dropped_pieces(reset=True)
    parts = char_lib.load_parts([base], tv.PALETTE)
    assert len(parts) == 1
    V, SI, SW, T = parts[0][:4]
    assert V.shape == (8, 3) and len(T) == 6
    assert np.allclose(V[0], [0.1, 0.2, 0.3], atol=1e-6)
    assert SI[:, 0].tolist() == [tv.EXPECTED_REMAP[i % 5] for i in range(8)]
    assert char_lib.dropped_pieces() == []
    assert "NOT exported" not in capsys.readouterr().out


def test_variant_glb_load_parts_keeps_it_too(monkeypatch):
    hdr, stream = console_skinned_model()
    monkeypatch.setattr(vg.efa, "grab_blocks", lambda naz: {"blk": {"h": b"H", "s": b"S"}})
    monkeypatch.setattr(
        we, "extract_block", lambda h, s: iter([(tv._Entry("/x/Body.model"), hdr, stream)])
    )
    parts = vg.load_parts(["Body"], tv.PALETTE, naz="does-not-exist.naz")
    assert len(parts) == 1 and len(parts[0][0]) == 8


def test_weapon_attachment_keeps_a_single_submesh_console_prop(tmp_path):
    hdr, stream = console_rigid_model()
    assert len(we.find_descriptors(hdr, "<")) == len(we.find_descriptors(hdr, ">")) == 1
    base = _write_model(tmp_path, "2x4_2H", hdr, stream)
    bind = str(tmp_path / "bind.npz")
    np.savez(bind, Rb=np.stack([np.eye(3)] * 2), tb=np.array([[0.0, 0, 0], [1.0, 2.0, 3.0]]))
    parts = ce._weapon_attach_parts(base, 1, bind, ["Root", "Attach RHand"])
    assert len(parts) == 1
    V, SI, SW, T = parts[0][:4]
    assert V.shape == (6, 3) and len(T) == 4
    assert np.allclose(V[0], [1.1, 2.2, 3.3], atol=1e-6)  # on the attach bone
    assert (SI == 1).all() and np.allclose(SW[:, 0], 1.0)


def test_a_piece_that_cannot_be_decoded_is_logged_and_listed(tmp_path, capsys):
    hdr, stream = console_skinned_model(false_le=False)
    base = _write_model(tmp_path, "Broken", hdr, b"\xff" * len(stream))  # no valid buffer
    char_lib.dropped_pieces(reset=True)
    assert char_lib.load_parts([base], tv.PALETTE) == []
    assert char_lib.load_parts([base], tv.PALETTE) == []  # an outfit loads it again
    out = capsys.readouterr().out
    assert (
        out.count("WARNING: Broken: submesh 0 (8 vertices, stride 44, 36 index bytes, big-endian)")
        == 2
    )
    assert "NOT exported: " + char_lib.NO_BUFFER in out
    got = char_lib.dropped_pieces(reset=True)
    assert got == [
        {
            "model": "Broken",
            "submesh": 0,
            "vertices": 8,
            "stride": 44,
            "index_bytes": 36,
            "byte_order": "big",
            "reason": char_lib.NO_BUFFER,
        }
    ]
    assert char_lib.dropped_pieces() == []


# ---------------------------------------------------------------------------
# bug 1: the ragdoll rig of a console skeleton
# ---------------------------------------------------------------------------


def test_big_endian_skeleton_gives_the_rig_of_the_pc_file(big_endian, monkeypatch):
    be_model = trr.build_model()
    monkeypatch.undo()
    le_model = trr.build_model()
    assert be_model != le_model and rr.byte_order(be_model) == ">"
    assert rr.byte_order(le_model) == "<"
    assert rr.build(le_model, "<") is not None
    assert rr.build(be_model, "<") is None  # what 1.3.0 .. the first 1.4.0 batch did
    rig = rr.build(be_model)
    assert rig is not None and rr.explain(be_model) is None
    assert len(rig["bodies"]) == 4 and len(rig["joints"]) == 3
    assert rig == rr.build(le_model)


def test_big_endian_pivot_book_gives_the_same_material_and_id(big_endian, monkeypatch):
    be_book = trr.build_pivot_book(SHEETS)
    monkeypatch.undo()
    le_book = trr.build_pivot_book(SHEETS)
    assert rr.byte_order(be_book, pivot_book=True) == ">"
    assert rr.byte_order(le_book, pivot_book=True) == "<"
    for sheet in ("Ragdoll", "Ragdoll_All"):
        mat = rr.material_from_pivot_book(be_book, sheet)
        assert mat == rr.material_from_pivot_book(le_book, sheet)
    # 64-bit ids: low word first on console, not a byte-reversed u64
    assert rr.material_from_pivot_book(be_book)["unique_id"] == "0x43b830d445af0000"
    assert rr.material_from_pivot_book(be_book, "Ragdoll_All")["collision_mask"] == "0x401"


def test_export_hook_writes_the_same_sidecar_for_a_console_extract(
    big_endian, monkeypatch, tmp_path
):
    be = _tree(tmp_path / "be", trr.build_model(), trr.build_pivot_book(SHEETS))
    monkeypatch.undo()
    le = _tree(tmp_path / "le", trr.build_model(), trr.build_pivot_book(SHEETS))
    monkeypatch.delenv("WATCHMEN_RAGDOLL", raising=False)
    bind = _bind_file(tmp_path, rr.build(trr.build_model()))
    docs = []
    for ex in (le, be):
        out = str(tmp_path / ex.parent.name / "Dominatrix_1.glb")
        why = []
        h = ce.ragdoll_helpers(str(ex), "female", [], bind, out, why=why)
        assert h is not None and why == []
        assert len(h["shapes"]) == 5 and len(h["joints"]) == 3
        docs.append(pathlib.Path(out[:-4] + ".ragdoll.json").read_bytes())
    assert docs[0] == docs[1]
    assert json.loads(docs[1])["common"]["material"]["unique_id"] == "0x43b830d445af0000"


def test_no_rig_says_why_in_the_log_and_to_the_caller(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("WATCHMEN_RAGDOLL", raising=False)
    old_layout = _cls("<") + b"\x07" * 400  # a ModelRes header the Part 2 reader cannot walk
    assert rr.build(old_layout) is None and rr.explain(old_layout) == rr.NO_LAYOUT
    assert rr.explain(trr.build_model()) is None
    ex = _tree(tmp_path, old_layout, trr.build_pivot_book(SHEETS))
    bind = _bind_file(tmp_path, rr.build(trr.build_model()))
    out = str(tmp_path / "Biker_1.glb")
    why = []
    assert ce.ragdoll_helpers(str(ex), "female", [], bind, out, why=why) is None
    assert why == ["Female_Skeleton.model: " + rr.NO_LAYOUT]
    line = capsys.readouterr().out
    assert "note: no ragdoll rig for Biker_1.glb: Female_Skeleton.model: " in line
    assert "older record format" in line
    assert not os.path.exists(out[:-4] + ".ragdoll.json")
    # a skeleton that is not in the extract
    why = []
    assert ce.ragdoll_helpers(str(ex), "gimp", [], bind, out, why=why) is None
    assert "not in the extract" in why[0] and "no ragdoll rig for Biker_1.glb" in (
        capsys.readouterr().out
    )
    # switched off: silent, no reason
    why = []
    assert ce.ragdoll_helpers(str(ex), "female", [], bind, out, False, why=why) is None
    assert why == [] and capsys.readouterr().out == ""


def test_model_without_joints_is_explained():
    h = trr._str("ModelRes") + struct.pack("<I", 0) + struct.pack("<IBIB", 0, 0, 0, 0)
    h += struct.pack("<II", 0, 0) + struct.pack("<6f", 0, 0, 0, 1, 1, 1) + struct.pack("<II", 0, 0)
    h += struct.pack("<I", 1) + trr._node("Box", -1, (0, 0, 0), vols0=[trr._box(1, 1, 1)])
    blob = trr._body_records(1, "Box", 5.0)
    h += struct.pack("<I", len(blob) // 4) + blob + struct.pack("<IH", 1, 0)
    h += struct.pack("<III", 0, 0, 0)
    assert rr.build(h) is None and rr.explain(h) == rr.NO_BODY
    assert rr.explain(b"junk") == rr.NO_LAYOUT


# ---------------------------------------------------------------------------
# bug 7: the Part 1 warning tests the binds, not the path
# ---------------------------------------------------------------------------


def _binds_tree(tmp_path, model):
    import build_bind_file

    ex = _tree(tmp_path, model, trr.build_pivot_book(SHEETS), name="Medium_Skeleton.model")
    (ex / "binds").mkdir()
    src = ex / "extracted" / "art" / "characters" / "common" / "skeletons"
    build_bind_file.build(
        str(src / "Medium_Skeleton.model"), None, str(ex / "binds" / "bind_medium_file_v1.npz")
    )
    return ex


def test_binds_built_from_the_extract_raise_no_warning_whatever_the_path(tmp_path, capsys):
    # the PS3 and XBLA Part 1 paths have no "part1" in them: USRDIR/p1, derived_x360
    ex = _binds_tree(tmp_path / "USRDIR" / "p1", trr.build_model())
    capsys.readouterr()
    assert ce.bind_mismatches(str(ex)) == {}
    assert capsys.readouterr().out == ""  # the check itself prints nothing
    assert ce.bind_mismatches(str(tmp_path / "nothing_here")) == {}


def test_a_bind_from_another_skeleton_is_reported_even_under_a_part1_path(tmp_path):
    ex = _binds_tree(tmp_path / "part1_pc", trr.build_model())
    sk = ex / "extracted" / "art" / "characters" / "common" / "skeletons"
    # the extract's skeleton now has another rest pose than the bind on disk
    blob = bytearray(trr.build_model())
    i = bytes(blob).index(struct.pack("<3f", 0.1, 0.0, 0.0))  # Spine local position
    blob[i : i + 12] = struct.pack("<3f", 0.1, 0.25, 0.0)
    (sk / "Medium_Skeleton.model").write_bytes(bytes(blob))
    got = ce.bind_mismatches(str(ex))
    assert list(got) == ["medium"] and "rest pose differs from Medium_Skeleton.model" in (
        got["medium"]
    )
    # a bind whose skeleton the extract does not have at all (a Part 2 bind)
    os.replace(
        str(ex / "binds" / "bind_medium_file_v1.npz"), str(ex / "binds" / "bind_gimp_file_v1.npz")
    )
    assert ce.bind_mismatches(str(ex)) == {"gimp": "the extract has no Large_Gimp_Skeleton.model"}


# ---------------------------------------------------------------------------
# what a GLB does not carry is stated
# ---------------------------------------------------------------------------


def _part(n, attrs):
    p = (np.zeros((n, 3)), None, None, np.zeros((1, 3), int), None, "m")
    if not attrs:
        return p
    z = np.zeros((n, 3), np.float32)
    return vg.with_attrs(
        p, {"normal": z, "tangent": z, "bitangent": z, "color": np.zeros((n, 4), np.uint8)}
    )


def test_not_decoded_marker_is_absent_when_nothing_is_missing():
    assert ce.not_decoded_extras([[_part(3, True)], None, [_part(4, True)]]) is None
    assert ce.not_decoded_extras([]) is None
    # attributes switched off by the user: a choice, not a gap
    assert ce.not_decoded_extras([[_part(3, False)]], attrs_wanted=False) is None


def test_not_decoded_marker_lists_attributes_ragdoll_and_pieces():
    dropped = [{"model": "X", "submesh": 1, "reason": char_lib.NO_BUFFER}]
    nd = ce.not_decoded_extras(
        [[_part(3, False), _part(3, True)], [_part(5, False)]],
        "Medium_Skeleton.model: why",
        dropped,
    )["not_decoded"]
    va = nd["vertex_attributes"]
    assert va["missing"] == ["NORMAL", "TANGENT", "COLOR_0"]
    assert (va["pieces"], va["pieces_without"]) == (3, 2) and "does not locate" in va["reason"]
    assert nd["ragdoll"] == {"reason": "Medium_Skeleton.model: why"}
    assert nd["pieces"] == dropped
    json.dumps(nd)  # plain data: goes into asset.extras.watchmen


def test_console_parts_carry_no_attributes_and_pc_parts_are_untouched(tmp_path):
    """The marker's premise: buffer_vertex_attrs gives nothing for a big-endian
    buffer (documented limit), so a console piece is a plain tuple."""
    hdr, stream = console_skinned_model()
    base = _write_model(tmp_path, "P", hdr, stream)
    parts = char_lib.load_parts([base], tv.PALETTE)
    assert getattr(parts[0], "attrs", None) is None
    assert ce.not_decoded_extras([parts])["not_decoded"]["vertex_attributes"]["pieces_without"] == 1


@pytest.mark.parametrize("order", ["<", ">"])
def test_a_planar_piece_is_found_by_the_flat_fallback(order, tmp_path, capsys):
    """Large_Head_2 submesh 3 (an eye card, flat in x) was dropped on every
    platform: the strict scan wants three non-degenerate axes."""
    nv, stride = 6, tv.STRIDE[order]
    tris = [(i, i + 1, i + 2) for i in range(nv - 2)]
    ib = len(tris) * 6
    hdr = _cls(order) + tv.build_model_header(tv.synthetic_nodes(tv.MESH_NODES), order)
    hdr += b"\xff" * 4 + struct.pack(order + "6I", 0, nv, 6, 0, ib, 1) + b"\xff" * 8
    vb = bytearray()
    for i in range(nv):
        rec = bytearray(stride)
        struct.pack_into(order + "3f", rec, 0, 0.0988, 0.43 + 0.01 * i, 0.02 * (i % 3) - 0.02)
        vb += rec
    stream = bytes(vb) + b"".join(struct.pack(order + "3H", *t) for t in tris)
    assert not we._vb_ok(stream, 0, nv, stride, ib, order)
    assert char_lib.flat_buffer(stream, 0, nv, stride, ib, order) == 0
    base = _write_model(tmp_path, "Large_Head_2", hdr, stream)
    char_lib.dropped_pieces(reset=True)
    parts = char_lib.load_parts([base], tv.PALETTE)
    assert len(parts) == 1 and len(parts[0][0]) == nv and len(parts[0][3]) == len(tris)
    assert np.allclose(np.asarray(parts[0][0])[:, 0], 0.0988)
    assert char_lib.dropped_pieces() == [] and "NOT exported" not in capsys.readouterr().out
    # a line (two flat axes) is still not a mesh
    assert char_lib.flat_buffer(b"\0" * len(stream), 0, nv, stride, ib, order) is None
