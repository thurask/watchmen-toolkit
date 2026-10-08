"""Pass 3, the reporting fixes: nothing that is not decoded stays silent, and nothing
inferred is shown like a fact.

    misc kinds        every asset `extract` writes JSON for is counted per kind; one
                      that is not decoded completely has a marker in its JSON
                      (kapow_json.undecoded reads it) and a WARNING line; the summary
                      has one line with the count per kind; a kind without any decoder
                      is counted as raw only
    models            with --glb, a decoded model that gets no .glb says why in its
                      .model.json ("glb": {"written": false, "reason"}) and the run
                      summary counts them per reason; a scan decode that found fewer
                      submeshes than the header lists has "submeshes" under not_decoded
    inferred names    the five Part 1 property names whose spelling is inferred are
                      listed in the fragment JSON that uses them
    output names      the blocks are taken in case-insensitive order, so the spelling a
                      twin is written under does not depend on the letter case an
                      archive stores its block paths in

Synthetic fixtures only (those of the earlier passes are reused)."""

import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import kapow_fragment as kf
import kapow_json as kj
import watchmen_extract as wx

import test_formats_v2 as tf
import test_p2_fragment as pf
import test_p2_small as ps
import test_p3_part1_model as pm
import test_p3_raw_formats as pr


# ------------------------------------------------------------ misc kinds
def test_undecoded_reads_every_marker_and_nothing_else():
    assert kj.undecoded(None) == "no decoder output"
    clean = {
        "lossless": True,
        "tail_bytes": 0,
        "trailing_bytes": 0,
        "leftover_bytes": 0,
        "stream": {"leftover_bytes": 0, "unverified": "1x1 map"},
        "inferred": ["uv"],
        "not_established": ["flag"],
        "inferred_names": [{"name": "_tuseteleport"}],
    }
    assert kj.undecoded(clean) is None
    assert kj.undecoded({"not_decoded": "font: 3 glyph records", "leftover_bytes": 9}) == (
        "font: 3 glyph records"
    )
    assert kj.undecoded({"trailing_bytes": 24}) == "24 trailing bytes"
    assert kj.undecoded({"tail_bytes": 1836}) == "1836 tail bytes"
    assert "stream: no stream" in kj.undecoded({"stream": {"not_decoded": "no stream"}})
    assert kj.undecoded({"stream": {"leftover_bytes": 4}}) == "4 stream bytes left"
    assert "does not end" in kj.undecoded({"lossless": False})
    assert kj.undecoded({"lossless": False, "parse_error": "bad"}) == "parse error: bad"
    assert "1 unknown key" in kj.undecoded({"lossless": True, "unknown_keys": [{"key": "k"}]})
    assert "atlas not written" in kj.undecoded({"atlas_not_written": "format 77"})
    assert kj.undecoded({"warn": ["desync in X"]}) == "desync in X"


def _extract_log(tmp_path, extra_entries=()):
    entries, stream = pr._block_parts()
    return pr._run_extract(tmp_path, entries + list(extra_entries), stream)


def test_extract_counts_every_kind_and_names_what_is_not_decoded(tmp_path):
    z = pr.zlib.compress
    extra = [
        # a .grass whose bytes are no property bag, and a kind nothing decodes
        ("/art/g/Bad.grass", wx._name_hash("grass"), z(b"\x07" * 37), None),
        ("/art/x/Thing.newkind", 0x12345678, z(b"\x01\x02\x03\x04" * 5), None),
    ]
    ex, log = _extract_log(tmp_path, extra)
    assert (
        "  misc JSON   : .detailmesh 1, .font 2, .grass 1, .scene 1, .terrain 1, "
        ".terraincoloringasset 1"
    ) in log
    assert "  not decoded completely: .font 1 of 2, .grass 1 of 1  (a WARNING: line" in log
    # the broken font keeps its own line and gets no second one
    assert log.count("Broken.font") == 1
    assert "WARNING: grass /art/g/Bad.grass: not decoded" in log
    bad = ex / "art" / "g" / "Bad.grass.json"
    assert not bad.exists() or kj.undecoded(json.loads(bad.read_text()))
    assert "WARNING: raw only (no decoder for this kind; kept under extracted/): " in log
    assert ".newkind 1" in log.split("raw only")[1].splitlines()[0]
    assert (ex / "art" / "x" / "Thing.newkind").exists()


def test_misc_summary_counts_an_asset_stored_in_two_blocks_once(tmp_path, capsys):
    frag = pf._waypoint(pf.B("<"), b"")
    d = tmp_path / "files" / "derived_pc" / "levels"
    d.mkdir(parents=True)
    for nm, spelling in (("a", "/L/Way.fragment"), ("b", "/L/way.fragment")):
        h, s = tf._block([(spelling, wx._name_hash("fragment"), frag, None)])
        (d / (nm + ".block_h_z")).write_bytes(h)
        (d / (nm + ".block_s_z")).write_bytes(s)
    args = [str(tmp_path / "files"), "-o", str(tmp_path / "out"), "--no-files", "--no-text"]
    assert wx.main(args + ["--no-audio", "--no-textures", "--no-models"]) == 0
    log = capsys.readouterr().out
    assert "  misc JSON   : .fragment 1\n" in log and "not decoded completely: none" in log


def test_extract_says_none_when_every_misc_asset_is_decoded(tmp_path):
    entries, stream = pr._block_parts()
    ex, log = pr._run_extract(tmp_path, entries[:-1], stream)  # without the broken font
    assert "  misc JSON   : .detailmesh 1, .font 1, .scene 1, .terrain 1, " in log
    assert "  not decoded completely: none" in log
    assert "WARNING:" not in log and "raw only" not in log


# ------------------------------------------------------------ models
@pytest.fixture
def glb_on(monkeypatch):
    """decode_model with --glb in force (the rig writer loaded), default attributes."""
    monkeypatch.setitem(wx._RIG, "on", True)
    monkeypatch.setitem(wx._RIG, "attrs", True)
    assert wx._rig_load()
    monkeypatch.setattr(wx, "_write_obj_mtl", lambda *a: None)


def _decode(tmp_path, h, s, **kw):
    logs = []
    st = {}
    ok = wx.decode_model(h, s, tmp_path / "m.obj", log=lambda *a: logs.append(a[0]), status=st)
    assert ok is True
    return json.loads((tmp_path / "m.model.json").read_text()), st, logs


def test_model_with_a_glb_has_no_glb_marker(tmp_path, glb_on):
    meta, st, logs = _decode(tmp_path, *pm.build("<", "part2"))
    assert (tmp_path / "m.glb").exists()
    assert "glb" not in meta and "not_decoded" not in meta
    assert st["glb"] is True and st["glb_reason"] is None and st["partial"] is None


def test_model_without_glb_says_why_in_its_sidecar(tmp_path, glb_on, monkeypatch):
    monkeypatch.setitem(wx._RIG, "attrs", False)  # --no-vertex-attrs: static models get none
    meta, st, logs = _decode(tmp_path, *pm.build("<", "part2"))
    assert not (tmp_path / "m.glb").exists()
    assert meta["glb"]["written"] is False and "--no-vertex-attrs" in meta["glb"]["reason"]
    assert st["glb"] is False and st["glb_reason"] == meta["glb"]["reason"]


def test_without_glb_option_the_sidecar_has_no_marker(tmp_path, monkeypatch):
    monkeypatch.setitem(wx._RIG, "on", False)
    monkeypatch.setattr(wx, "_write_obj_mtl", lambda *a: None)
    meta, st, logs = _decode(tmp_path, *pm.build("<", "part2"))
    assert "glb" not in meta and st["glb"] is None
    # a caller that passes no dict finds the same facts in MODEL_STATUS
    assert wx.decode_model(*pm.build("<", "part2"), tmp_path / "n.obj") is True
    assert wx.MODEL_STATUS["glb"] is None and wx.MODEL_STATUS["partial"] is None


def test_scan_decode_that_misses_submeshes_is_marked(tmp_path, glb_on, monkeypatch):
    """Console Palm_Banana_01 before the header decode: one of three submeshes."""
    monkeypatch.setenv("WATCHMEN_CONSOLE_MODELS", "scan")
    h, s = pm.build(">", "part2", console="x360")
    full = wx.find_descriptors(h, ">")
    monkeypatch.setattr(wx, "find_descriptors", lambda hd, o: full[:1] if o == ">" else [])
    meta, st, logs = _decode(tmp_path, h, s)
    assert meta["mesh_source"] == "descriptor scan" and meta["not_decoded"] == ["submeshes"]
    assert (
        meta["submeshes"]["decoded"] == 1 and meta["submeshes"]["header_render_buffers_lod0"] == 2
    )
    assert st["partial"] and "2 full-detail render buffer(s)" in st["partial"]
    assert sum("WARNING: model m.obj: incomplete" in l for l in logs) == 1
    # a scan-decoded model without a skin gets no GLB, and says so
    assert meta["glb"]["written"] is False and "descriptor scan" in meta["glb"]["reason"]


def test_complete_scan_decode_is_not_marked_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_CONSOLE_MODELS", "scan")
    monkeypatch.setattr(wx, "_write_obj_mtl", lambda *a: None)
    meta, st, logs = _decode(tmp_path, *pm.build(">", "part2", console="x360"))
    assert meta["mesh_source"] == "descriptor scan"
    assert "not_decoded" not in meta and "submeshes" not in meta and st["partial"] is None


def test_extract_summary_counts_models_without_glb(tmp_path, monkeypatch, capsys):
    files = ps._two_block_tree(tmp_path)
    real = wx.decode_model

    def decode(header, stream, out_path, tex_index=None, log=None, order=None, lod=0):
        if not stream:
            return real(header, stream, out_path, tex_index, log, order=order, lod=lod)
        rock = out_path.name.startswith("Rock")
        wx.MODEL_STATUS.update(
            glb=not rock,
            glb_reason="the mesh came from the descriptor scan" if rock else None,
            color_not_decoded=out_path.name == "Rock.model.obj",
            partial="1 of 3" if out_path.name == "Rock~b.model.obj" else None,
        )
        return True

    monkeypatch.setattr(wx, "carve_texture", lambda *a, **k: True)
    monkeypatch.setattr(wx, "decode_model", decode)
    monkeypatch.setattr(wx, "HAVE_IMG", True)
    out = tmp_path / "out"
    args = [str(files), "-o", str(out), "--no-files", "--no-text", "--no-audio", "--glb"]
    try:
        assert wx.main(args) == 0
    finally:
        wx._RIG["on"] = False
    log = capsys.readouterr().out
    assert '  model GLBs  : 1  (2 decoded model(s) WITHOUT a .glb; "glb" in their' in log
    assert (
        "  note: no GLB for 2 model(s): the mesh came from the descriptor scan: "
        "Rock.model, Rock~b.model"
    ) in log
    assert "  WARNING: 1 model(s) decoded incompletely" in log and "Rock~b.model" in log
    assert "  note: vertex colours not decoded for 1 model(s)" in log


def test_extract_summary_without_glb_option_has_no_glb_line(tmp_path, monkeypatch, capsys):
    files = ps._two_block_tree(tmp_path)
    monkeypatch.setattr(wx, "carve_texture", lambda *a, **k: True)
    monkeypatch.setattr(wx, "HAVE_IMG", True)
    assert wx.main([str(files), "-o", str(tmp_path / "o"), "--no-files", "--no-text"]) == 0
    log = capsys.readouterr().out
    assert "model GLBs" not in log and "no GLB for" not in log


# ------------------------------------------------------------ inferred names
def _part1_fragment(order=">"):
    b = pf.B(order)
    tail = b.u(0x57A8BE19, 0xFFFFFFFF, 0x40CB4063, 0) + b.u(0x56EEC9BF) + b.f(0.5)
    tail += b.u(0xF89F0453) + b.f(0.01) + b.u(0xCEACAED4, 1)
    return pf._waypoint(b, tail)


def test_confirmed_part1_names_carry_no_inferred_marker():
    """All seven Part 1 names are entries of the Part 1 database.bin, so none is marked."""
    j = kj.to_json("x.fragment", _part1_fragment(), order=">")
    assert j["lossless"] and "unknown_keys" not in j
    assert "inferred_names" not in j and "inferred_names_note" not in j
    names = [p[0] for p in j["nodes_full"][0]["props"]]
    for n in ("_idebugrunthroughmode", "_nsteplengthinmeters", "_ntimeprstepinsec"):
        assert n in names
    assert "_tuseteleport" in names and "_tdebugtmp01" in names
    assert kj.undecoded(j) is None and kf.notes("x.fragment", j) == []


def test_a_still_inferred_spelling_is_listed_in_the_fragment_json(monkeypatch):
    """The mechanism for a name that no string list or database confirms: three of the
    seven are put back into the table to show what the JSON then says."""
    monkeypatch.setattr(
        kf,
        "INFERRED_NAMES",
        {
            "_nsteplengthinmeters": (0x56EEC9BF, "Step Length(m)"),
            "_ntimeprstepinsec": (0xF89F0453, "Step Time(m/sec)"),
            "_tuseteleport": (0xCEACAED4, "Use Teleport"),
        },
    )
    j = kj.to_json("x.fragment", _part1_fragment(), order=">")
    assert j["lossless"] and "unknown_keys" not in j
    assert [(e["name"], e["key"], e["count"]) for e in j["inferred_names"]] == [
        ("_nsteplengthinmeters", "56eec9bf", 1),
        ("_ntimeprstepinsec", "f89f0453", 1),
        ("_tuseteleport", "ceacaed4", 1),
    ]
    assert all(e["confidence"] == "inferred" for e in j["inferred_names"])
    assert j["inferred_names"][0]["caption"] == "Step Length(m)"
    assert "spelling" in j["inferred_names_note"]
    # names outside the table are not in the list, the values stay as stored, and a
    # marked fragment is not reported as undecoded
    names = [p[0] for p in j["nodes_full"][0]["props"]]
    assert "_idebugrunthroughmode" in names and "_tdebugtmp01" in names
    assert kj.undecoded(j) is None and kf.notes("x.fragment", j) == []


def test_fragment_without_an_inferred_name_has_no_marker():
    b = pf.B("<")
    j = kj.to_json("x.fragment", pf._waypoint(b, b""), order="<")
    assert j["lossless"] and "inferred_names" not in j and "inferred_names_note" not in j


def test_no_part1_key_is_an_inferred_spelling_any_more():
    assert len(kf.PART1_KEYS) == 7
    assert kf.PART1_INFERRED == {} and kf.INFERRED_NAMES == {}
    assert set(kf.PART1_INFERRED) <= set(kf.PART1_KEYS)
    for h, (name, _typ) in kf.PART1_KEYS.items():
        assert pf.H(name) == h


# ------------------------------------------------------------ output names
def test_block_order_does_not_depend_on_the_letter_case_of_the_block_path(tmp_path, capsys):
    """Blocks `a` and `B` hold the same texture under two spellings.  A byte-wise sort
    takes `B` first (PS3 stores its block paths in lower case, PC Part 1 does not);
    the case-insensitive order takes `a` first in both."""
    tex = ps._cls("Texture", b"tex-hdr")
    d = tmp_path / "files" / "derived_pc" / "levels"
    d.mkdir(parents=True)
    for nm, spelling in (("a", "/art/T/Wall.bmp"), ("B", "/art/T/wall.bmp")):
        h, s = tf._block([(spelling, tf._TEX, tex, b"wall-stream-0123456789")])
        (d / (nm + ".block_h_z")).write_bytes(h)
        (d / (nm + ".block_s_z")).write_bytes(s)
    out = tmp_path / "out"
    args = [str(tmp_path / "files"), "-o", str(out), "--no-files", "--no-text", "--no-audio"]
    assert wx.main(args + ["--no-textures", "--no-models"]) == 0
    log = capsys.readouterr().out
    assert log.index("a.block") < log.index("B.block")
    assert "/art/T/wall.bmp (= /art/T/Wall.bmp)" in log
    assert "under the spelling of the first block in case-insensitive block order" in log
    assert (out / "extracted" / "art" / "T" / "Wall.bmp").exists()
