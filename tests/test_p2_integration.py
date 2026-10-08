"""Seams between the pass-2 fixes (2026-10-05): one byte-order test for a header
read outside its block, the 64-bit record value on console, the older Part 1
record layout behind the ragdoll material, the fragment byte-order test, and one
log line per asset left without stream data.  Synthetic and offline; the
big-endian and older-layout fixtures are built here or in the package tests.
"""

import builtins
import struct

import pytest

import char_lib
import extract_skeletons
import kapow_fragment as kf
import parse_model_nodes as pmn
import ragdoll_rig as rr
import skeleton_records as sr
import watchmen_extract as we

import test_p2_part1 as tp1


def _cls(order, name="ModelRes"):
    raw = name.encode("ascii") + b"\0"
    return struct.pack(order + "I", len(raw)) + raw


# ---------------------------------------------------------------------------
# byte order: one source of truth
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("order", ["<", ">"])
def test_every_standalone_reader_takes_the_order_the_header_states(order):
    hdr = _cls(order) + b"\0" * 64
    assert we.header_order(hdr) == order
    assert char_lib.header_order(hdr) == order  # the same function, not a second rule
    assert rr.byte_order(hdr) == order
    assert pmn._detect_order(hdr) == order
    assert extract_skeletons._header_order(hdr) == order
    # asset_class reads that very field
    assert we.asset_class(hdr, order) == "ModelRes"


def test_readers_keep_their_own_rule_when_the_header_does_not_say():
    blob = struct.pack("<I", 6) + b"\x9a\x99\x19\x3f" * 8
    assert we.header_order(blob) is None and we.header_order(b"") is None
    assert pmn._detect_order(blob) == "<"
    assert extract_skeletons._ordered_names(blob) == []


# ---------------------------------------------------------------------------
# 64-bit record values: two words, low word first, on every platform
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("order", ["<", ">"])
def test_biginteger_record_is_low_word_first_in_both_orders(order):
    data = struct.pack(order + "II", 0x45AF888D, 0x43B830D4)
    assert sr.record_value(0xEDEF427C, data, order) == 0x43B830D4_45AF888D
    # the value the fragment parser gives for the same eight bytes


@pytest.mark.parametrize("order", ["<", ">"])
@pytest.mark.parametrize("typed", [True, False])
def test_ragdoll_material_from_a_pivot_book_of_either_layout(order, typed):
    """Stand-alone Part 1 (PC, Xbox Live) stores the pivot book without type
    hashes: skeleton_records raises on it, kapow_props reads it (the fallback)."""
    book = tp1._pivot_book(order, typed)
    assert rr.byte_order(book, pivot_book=True) == order
    if not typed:
        with pytest.raises((ValueError, struct.error)):
            sr.parse_pivot_book(book, rr.property_names(), order)
    mat = rr.material_from_pivot_book(book)
    assert mat["sheet"] == "Ragdoll" and mat["unique_id"] == "0x43b830d445af888d"
    assert mat["friction"] == pytest.approx(0.6) and mat["collision_mask"] == "0x1"
    assert mat == rr.material_from_pivot_book(tp1._pivot_book("<", True))
    with pytest.raises(KeyError):
        rr.material_from_pivot_book(book, "NoSuchSheet")


def test_a_pivot_book_no_reader_takes_still_raises():
    with pytest.raises((ValueError, struct.error)):
        rr.pivot_sheets(b"\0" * 40, "<")


# ---------------------------------------------------------------------------
# fragment byte order: both chunk walks pass, the schema record decides
# ---------------------------------------------------------------------------
def _trap_fragment():
    """A big-endian chunked fragment whose LITTLE-endian chunk walk also ends on
    the last byte (as SE_Countered_victim02.fragment, 393 bytes, does on console)."""
    name = b"Node(Object)\0\0\0\0"
    schema = b"\xff" * 4 + struct.pack(">II", 0x1234ABCD, len(name) // 4) + name
    tail = b"\0" * 20
    payload = schema + struct.pack("<I", len(tail)) + tail
    return b"\0" * 8 + struct.pack(">I", len(payload)) + payload


def test_fragment_order_prefers_the_walk_whose_payload_has_a_schema_record():
    d = _trap_fragment()
    assert kf.dechunk(d, "<")[0] is not None and kf.dechunk(d, ">")[0] is not None
    assert kf._schema_scan(kf.dechunk(d, "<")[0], "<") is None
    assert kf.detect_order(d) == ">"  # was "<": the first walk that passed
    # a plain little-endian fragment is unaffected
    le = b"\0" * 8 + struct.pack("<I", 8) + b"\x01\x02\x03\x04" * 2
    assert kf.detect_order(le) == "<"


def test_fragment_notes_use_the_warning_wording():
    lines = kf.notes("a/b.fragment", {"lossless": False})
    assert len(lines) == 1 and lines[0].startswith("WARNING: fragment a/b.fragment: NOT decoded")
    assert kf.notes("a/b.fragment", {"lossless": True}) == []


# ---------------------------------------------------------------------------
# extract: an asset without stream data is named once
# ---------------------------------------------------------------------------
def test_extract_names_an_asset_without_stream_once_for_all_blocks(tmp_path):
    h, a, room = tp1._prison()
    for lvl in ("Prison", "Yard"):  # the same header-only model in two blocks
        src = tmp_path / "derived_pc" / "Levels" / lvl
        src.mkdir(parents=True)
        (src / (lvl + ".block_h_z")).write_bytes(h)
        (src / (lvl + ".block_s_z")).write_bytes(a)
    art = tmp_path / "derived_pc" / "Levels" / "Prison" / "Art"
    art.mkdir()
    (art / "PrisonYard.block_s_z").write_bytes(room)
    lines = []
    real = builtins.print
    builtins.print = lambda *x, **k: lines.append(" ".join(str(v) for v in x))
    try:
        rc = we.main(
            [str(tmp_path / "derived_pc"), "-o", str(tmp_path / "out")]
            + ["--no-textures", "--no-models", "--no-audio", "--no-text", "--no-nav"]
        )
    finally:
        builtins.print = real
    log = "\n".join(lines)
    assert rc == 0
    assert "NO STREAM: 1 texture / model asset(s) without stream data" in log
    assert log.count("note: no stream: /art/Skeleton.model (ModelRes): header only") == 1
    assert "no stream: /art/Fence_01.model" not in log


def test_an_empty_stream_model_is_an_expected_absence_not_a_warning(tmp_path):
    lines = []
    hdr = _cls("<") + bytes(64)
    assert we.decode_model(hdr, b"", tmp_path / "X.model.obj", {}, lines.append) is False
    assert lines == [
        "      note: model X.model.obj: not decoded: empty stream: the model has no mesh data"
    ]
