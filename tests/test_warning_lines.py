"""Failures that change or drop output are named by a WARNING line (the word the
export batch counts), and the handlers catch only the errors they are meant for.

Synthetic data only.
"""

import json
import struct
import zlib

import pytest

import anim_meta
import combat_meta
import face_export
import fx_meta
import gen_data
import text_assets as ta
import watchmen_extract as wx

import test_formats_v2 as tf

TEXT_HASH = wx._name_hash("textRes")


@pytest.fixture
def run_log():
    """The lines the extract helpers write through the running extract's log."""
    lines = []
    wx._RUN_LOG.append(lines.append)
    yield lines
    wx._RUN_LOG.remove(lines.append)


def _warnings(lines):
    return [x for x in lines if "WARNING:" in x]


# ------------------------------------------------------------ kapow_json import
def test_kapow_json_import_failure_keeps_its_reason(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "kapow_json", None)  # import -> ImportError
    wx._kapow_json.cache_clear()
    try:
        assert wx._kapow_json() is None
        assert wx._KAPOW_JSON_ERROR and "kapow_json" in wx._KAPOW_JSON_ERROR[0]
    finally:
        wx._kapow_json.cache_clear()
        wx._KAPOW_JSON_ERROR.clear()


def test_kapow_json_import_failure_names_each_asset_left_raw(tmp_path, monkeypatch, capsys):
    import test_text_assets as tt

    files = tt.loose_tree(tmp_path)
    h, s = tf._block([("/x/a.sequence", wx._name_hash("Sequence"), b"\x00" * 16, None)])
    lv = files / "derived_pc" / "levels"
    (lv / "seq.block_h_z").write_bytes(h)
    (lv / "seq.block_s_z").write_bytes(s)
    monkeypatch.setitem(__import__("sys").modules, "kapow_json", None)
    wx._kapow_json.cache_clear()
    try:
        wx.main([str(files), "-o", str(tmp_path / "o"), "--no-textures", "--no-models"])
    finally:
        wx._kapow_json.cache_clear()
        wx._KAPOW_JSON_ERROR.clear()
    out = capsys.readouterr()
    assert "WARNING: sequence /x/a.sequence: not decoded: kapow_json not importable" in (
        out.out + out.err
    )


# ------------------------------------------------------- property bag record cap
def _bag(records, rs=20):
    name = b"Sound"
    salt = 0x1234ABCD
    tag_off = 12 if rs == 20 else 8
    out = struct.pack("<I", len(name)) + name + struct.pack("<I", 0x2D)
    for i in range(records):
        rec = bytearray(rs)
        struct.pack_into("<I", rec, 0, salt)
        struct.pack_into("<I", rec, 4, i + 1)
        struct.pack_into("<I", rec, tag_off, 1)
        out += bytes(rec)
    return out + b"\xee" * 8


def test_prop_walk_names_a_bag_longer_than_its_cap(run_log):
    cap = wx._PROP_WALK_CAP
    start = 4 + len(b"Sound") + 4
    # at the cap exactly: nothing to say
    assert wx._prop_walk(_bag(cap)) == (start + cap * 20, 20)
    assert not _warnings(run_log)
    # past it: the same offset as before, and one line per distinct header
    long_bag = _bag(cap + 6)
    assert wx._prop_walk(long_bag) == (start + cap * 20, 20)
    wx._prop_walk(long_bag)
    got = _warnings(run_log)
    assert len(got) == 1 and "Sound header" in got[0] and "more than %d" % cap in got[0]


# ---------------------------------------------------------------- text assets
def _zblock(menus):
    return tf._block(
        [("/main.bmp", tf._TEX, b"MAIN", None)],
        [("/Localize/T_uk.txt", TEXT_HASH, menus, None)],
    )


def test_text_blob_that_does_not_inflate_is_named():
    good = [zlib.compress(ta.build_textres([("K", "v%d" % i)])) for i in range(6)]
    lines = []
    got = ta.block_text_assets(_zblock(good)[0], lines.append)
    assert not lines and ta.parse_textres(got[0][3][2]) == [("K", "v2")]
    bad = list(good)
    bad[3] = b"\x78\x9c" + b"\xff" * 12
    got = ta.block_text_assets(_zblock(bad)[0], lines.append)
    assert got[0][3][3] == bad[3]  # kept as stored, as before
    assert len(lines) == 1 and "WARNING: text /Localize/T_uk.txt (language slot 3)" in lines[0]


def test_text_asset_stored_twice_with_other_bytes_is_named(tmp_path):
    one = [zlib.compress(ta.build_textres([("K", "a")]))] * 6
    two = [zlib.compress(ta.build_textres([("K", "b")]))] * 6
    lines = []
    w = ta.TextWriter(tmp_path, lines.append)
    w.add_block(_zblock(one)[0], "first")
    w.add_block(_zblock(one)[0], "copy")  # the same bytes: nothing to say
    assert not _warnings(lines)
    w.add_block(_zblock(two)[0], "second")
    got = _warnings(lines)
    assert len(got) == 1 and "block second stores other bytes than block copy" in got[0]
    assert ta.parse_textres(w.assets["/Localize/T_uk.txt"]["blobs"][0]) == [("K", "b")]


# --------------------------------------------------------------- face heads
def test_find_heads_names_a_model_it_cannot_parse(tmp_path, capsys):
    d = tmp_path / "extracted" / "art" / "characters" / "x"
    d.mkdir(parents=True)
    (d / "Broken.model").write_bytes(b"\x00" * 40)
    assert face_export.find_heads(str(tmp_path)) == []
    out = capsys.readouterr().out
    assert "WARNING: faces:" in out and "Broken.model not parsed" in out


# ------------------------------------------------------- registered_names.json
def test_registered_names_missing_is_quiet_damaged_is_named(tmp_path, capsys):
    assert gen_data.load_registered_names(str(tmp_path / "none.json"))["names"] == {}
    assert capsys.readouterr().err == ""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert gen_data.load_registered_names(str(bad))["names"] == {}
    assert "WARNING:" in capsys.readouterr().err
    wrong = tmp_path / "wrong.json"
    h = "%08X" % wx._name_hash("m_good")
    wrong.write_text(
        json.dumps({"names": {h: {"m_good": ["A"], "m_bad": ["A"]}}}), encoding="utf-8"
    )
    got = gen_data.load_registered_names(str(wrong))
    assert list(got["names"].values()) == [{"m_good": ["A"]}]
    assert "1 spelling(s)" in capsys.readouterr().err


def test_shipped_registered_names_drops_nothing(capsys):
    assert gen_data.load_registered_names()["names"]
    assert "WARNING" not in capsys.readouterr().err


# ------------------------------------------------- anim_meta decoration steps
def test_skipped_steps_are_warning_lines_and_still_recorded(monkeypatch):
    def broken(*a, **k):
        raise KeyError("m_broken")

    monkeypatch.setattr(combat_meta, "build", broken)
    said = []
    assert combat_meta.build_or_none("/nonexistent", {}, {}, [], anim_meta, said.append) is None
    assert said and said[-1].startswith(combat_meta.SKIPPED_PREFIX)
    for prefix in (
        combat_meta.SKIPPED_PREFIX,
        fx_meta.SKIPPED_PREFIX,
        anim_meta.FACE_SKIPPED_PREFIX,
    ):
        assert "WARNING:" in prefix
    failed = {}
    anim_meta._block_failed(failed, "combat", "f", said, combat_meta.SKIPPED_PREFIX)
    assert failed["combat"]["status"] == "attempted, failed"
    assert failed["combat"]["reason"] == "KeyError: 'm_broken'"


# ------------------------------------------------------------- sheet.json
def test_read_sheet_json_missing_is_quiet_damaged_is_named(tmp_path, run_log):
    assert wx.read_sheet_json(tmp_path) == {}
    assert not run_log
    (tmp_path / "sheet.json").write_text("{", encoding="utf-8")
    assert wx.read_sheet_json(tmp_path) == {}
    assert len(_warnings(run_log)) == 1


def test_texture_alpha_flag_names_a_header_the_reader_refuses(monkeypatch, run_log):
    def refuse(*a, **k):
        raise struct.error("cut")

    monkeypatch.setattr(wx, "parse_texture_frames", refuse)
    assert wx.texture_alpha_flag(b"\x00" * 64, "<", "T.bmp") is None
    got = _warnings(run_log)
    assert len(got) == 1 and "texture T.bmp: alpha flag not read" in got[0]


def test_alpha_flag_lets_a_code_error_through(monkeypatch):
    def bug(*a, **k):
        raise TypeError("a bug, not bad data")

    monkeypatch.setattr(wx, "parse_texture_frames", bug)
    with pytest.raises(TypeError):
        wx.texture_alpha_flag(b"\x00" * 64)


# ------------------------------------------------------------- fx particles
def test_particle_facts_names_a_file_it_cannot_read(tmp_path, capsys):
    assert fx_meta.particle_facts(str(tmp_path / "gone.particle")) is None
    assert "WARNING: fx_meta: particle" in capsys.readouterr().out
