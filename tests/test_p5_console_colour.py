"""Console vertex colours: the byte order is the console's, and the console comes
from the source path.

Xbox 360 stores the colour of vertex formats 5 / 6 as a D3DCOLOR dword (bytes
A,R,G,B), PS3 as four unsigned bytes R,G,B,A.  A Part 2 model does not name its
console, so the extract passes it on from the block path (derived_x360 /
derived_ps3).  All fixtures are synthetic (test_p3_part1_model.build).
"""

import json

import numpy as np
import pytest

import characters_export as ce
import test_p2_small as ps
import test_p3_part1_model as pm
import variant_glb as vg
import watchmen_extract as we

#: stored bytes of the colour RGBA (255, 20, 255, 255) on each console: first
#: and last byte are 255 on both, so the alpha rule cannot tell the order
OPEN = {"x360": bytes([255, 255, 20, 255]), "ps3": bytes([255, 20, 255, 255])}
SRC = {"x360": bytes([255, 10, 20, 30]), "ps3": bytes([10, 20, 30, 255])}
RGBA = [255, 20, 255, 255]


@pytest.fixture(autouse=True)
def _no_platform(monkeypatch):
    monkeypatch.delenv("WATCHMEN_CONSOLE", raising=False)
    old = we.set_console_platform(None)
    we._PLATFORM_CACHE.clear()
    vg._LAYOUT_CACHE.clear()
    yield
    we.set_console_platform(old)
    we._PLATFORM_CACHE.clear()
    vg._LAYOUT_CACHE.clear()


def open_model(console, layout="part2"):
    """A console model whose colours leave the alpha rule undecided."""
    h, s = pm.build(">", layout, console=console)
    assert s.count(SRC[console]) >= 4
    return h, s.replace(SRC[console], OPEN[console])


def test_colour_orders_and_path_names():
    assert we.CONSOLE_COLOR_ORDERS == {"x360": "argb", "ps3": "rgba"}
    assert (
        we.console_platform_of("derived_x360/levels/game_levels/mainmenu/mainmenu.block") == "x360"
    )
    assert we.console_platform_of("Derived_PS3\\Levels\\a.block_h_z") == "ps3"
    assert we.console_platform_of("E:\\XBLA\\5841096E\\000D0000\\derived_x360") == "x360"
    assert we.console_platform_of("derived_pc/levels/a.block") is None
    assert we.console_platform_of("/art/derived_ps3_notes/x.model") is None
    assert we.console_platform_of(None) is None
    with pytest.raises(ValueError):
        we.set_console_platform("wii")


@pytest.mark.parametrize("console", ["x360", "ps3"])
def test_platform_decides_the_order_the_data_leaves_open(console):
    h, s = open_model(console)
    M = we.parse_model_header(h, ">")
    we.model_stream_layout(M, s, ">")
    assert we.console_color_order(s, M["buffers"]) is None
    assert len(we.console_color_undecoded(s, M["buffers"])) == 3
    want = we.CONSOLE_COLOR_ORDERS[console]
    assert we.console_color_order(s, M["buffers"], console) == want
    assert we.console_color_undecoded(s, M["buffers"], console) == []
    we.set_console_platform(console)
    assert we.console_platform() == console
    mesh = we.decode_model_mesh(h, s, lod="all")
    assert "not_decoded" not in mesh
    assert [b["has_color"] for b in mesh["model"]["buffers"]] == [1, 1, 1, 1]
    for sub in mesh["submeshes"]:
        if sub["format"] == 5:
            assert sub["color"].tolist() == [RGBA] * 4
    # the same colours as the PC copy of the model
    hp, sp = pm.build("<", "part2")
    pc = we.decode_model_mesh(hp, sp.replace(bytes([30, 20, 10, 255]), bytes([255, 20, 255, 255])))
    assert pc["submeshes"][0]["color"].tolist() == [RGBA] * 4


def test_wrong_platform_gives_the_other_reading_so_it_is_never_guessed():
    h, s = open_model("x360")
    M = we.parse_model_header(h, ">")
    b = we.model_stream_layout(M, s, ">")[0]
    right = we.decode_vertex_attributes(s, b, ">", "argb")["color"].tolist()
    wrong = we.decode_vertex_attributes(s, b, ">", "rgba")["color"].tolist()
    assert right == [RGBA] * 4 and wrong == [[255, 255, 20, 255]] * 4
    assert "color" not in we.decode_vertex_attributes(s, b, ">")


def test_environment_overrides_and_names_the_console(monkeypatch):
    h, s = open_model("ps3")
    we.set_console_platform("x360")
    monkeypatch.setenv("WATCHMEN_CONSOLE", "PS3")
    assert we.console_platform() == "ps3"
    assert we.decode_model_mesh(h, s)["submeshes"][0]["color"].tolist() == [RGBA] * 4
    monkeypatch.setenv("WATCHMEN_CONSOLE", "dreamcast")  # not a console we know: ignored
    assert we.console_platform() == "x360"


def test_where_the_data_decides_it_agrees_with_the_platform():
    for console in ("x360", "ps3"):
        h, s = pm.build(">", "part2", console=console)
        M = we.parse_model_header(h, ">")
        we.model_stream_layout(M, s, ">")
        assert we.console_color_order(s, M["buffers"]) == we.CONSOLE_COLOR_ORDERS[console]
        assert we.console_color_order(s, M["buffers"], console) == we.CONSOLE_COLOR_ORDERS[console]


def test_part1_layout_means_xbox_360_when_nothing_else_decides():
    """Big-endian + the stand-alone Part 1 header layout exists on Xbox 360 only."""
    h, s = open_model("x360", "part1")
    M = we.parse_model_header(h, ">")
    we.model_stream_layout(M, s, ">")
    assert M["layout"] == "part1" and we._console_color_order_inferred(s, M["buffers"]) is None
    assert we.console_color_order(s, M["buffers"], None, M["layout"]) == "argb"
    mesh = we.decode_model_mesh(h, s)
    assert "not_decoded" not in mesh and mesh["submeshes"][0]["color"].tolist() == [RGBA] * 4
    # the data, where it decides, and a named console both come first
    hp, sp = pm.build(">", "part1", console="ps3")
    Mp = we.parse_model_header(hp, ">")
    we.model_stream_layout(Mp, sp, ">")
    assert we.console_color_order(sp, Mp["buffers"], None, "part1") == "rgba"
    assert we.console_color_order(s, M["buffers"], "ps3", "part1") == "rgba"


def test_model_sidecar_and_log_carry_no_marker_once_the_console_is_known(tmp_path, monkeypatch):
    monkeypatch.setattr(we, "_write_obj_mtl", lambda *a: None)
    h, s = open_model("ps3")
    logs = []
    assert we.decode_model(h, s, tmp_path / "a.obj", log=lambda *a: logs.append(a[0])) is True
    meta = json.loads((tmp_path / "a.model.json").read_text())
    assert meta["not_decoded"] == ["COLOR_0"] and "WATCHMEN_CONSOLE" in meta["not_decoded_note"]
    assert sum("vertex colours not decoded" in l for l in logs) == 1
    assert we.MODEL_STATUS["color_not_decoded"] is True
    we.set_console_platform("ps3")
    logs = []
    assert we.decode_model(h, s, tmp_path / "b.obj", log=lambda *a: logs.append(a[0])) is True
    meta = json.loads((tmp_path / "b.model.json").read_text())
    assert "not_decoded" not in meta and not any("note:" in l for l in logs)
    assert we.MODEL_STATUS["color_not_decoded"] is False


@pytest.mark.parametrize("console", ["x360", "ps3"])
def test_character_piece_gets_its_colour_with_the_platform(console):
    h, s = open_model(console)
    b = we.model_stream_layout(we.parse_model_header(h, ">"), s, ">")[0]
    at = vg.buffer_vertex_attrs(h, s, ">", b["vb"], b["vertex_count"], b["stride"], console)
    assert at["color"].tolist() == [RGBA] * 4
    assert at["has_color"] is True and at["color_not_decoded"] is False
    pc = pm.build("<", "part2")
    bp = we.model_stream_layout(we.parse_model_header(pc[0], "<"), pc[1], "<")[0]
    ap = vg.buffer_vertex_attrs(pc[0], pc[1], "<", bp["vb"], bp["vertex_count"], bp["stride"])
    assert ap["color_not_decoded"] is False
    for k in ("normal", "tangent", "bitangent"):
        assert np.allclose(at[k], ap[k], atol=2e-3)


def test_character_piece_keeps_normal_and_tangent_when_the_colour_is_not_known():
    h, s = open_model("x360")
    b = we.model_stream_layout(we.parse_model_header(h, ">"), s, ">")[0]
    at = vg.buffer_vertex_attrs(h, s, ">", b["vb"], b["vertex_count"], b["stride"])
    assert at is not None and at["color_not_decoded"] is True
    assert at["has_color"] is False and at["has_alpha"] is False
    assert at["color"].tolist() == [[255] * 4] * 4  # placeholder, never written
    known = vg.buffer_vertex_attrs(h, s, ">", b["vb"], b["vertex_count"], b["stride"], "x360")
    for k in ("normal", "tangent", "bitangent"):
        assert at[k].tolist() == known[k].tolist() and len(at[k]) == 4
    # the cache keeps the two answers apart, also across a platform set later
    we.set_console_platform("x360")
    again = vg.buffer_vertex_attrs(h, s, ">", b["vb"], b["vertex_count"], b["stride"])
    assert again["color"].tolist() == [RGBA] * 4 and again["has_color"] is True


def _part(n, attrs, lost=False):
    p = (np.zeros((n, 3)), None, None, np.zeros((1, 3), int), None, "m")
    if not attrs:
        return p
    z = np.zeros((n, 3), np.float32)
    at = {"normal": z, "tangent": z, "bitangent": z, "color": np.zeros((n, 4), np.uint8)}
    at["color_not_decoded"] = lost
    return vg.with_attrs(p, at)


def test_character_marker_separates_missing_colour_from_missing_attributes():
    assert ce.not_decoded_extras([[_part(3, True), _part(3, True)]]) is None
    nd = ce.not_decoded_extras([[_part(3, True, lost=True), _part(3, True)], [_part(2, False)]])
    nd = nd["not_decoded"]
    assert nd["vertex_attributes"]["pieces_without"] == 1
    assert nd["vertex_attributes"]["reason"] == ce.VERTEX_ATTRS_REASON
    assert "colour" not in ce.VERTEX_ATTRS_REASON
    vc = nd["vertex_colour"]
    assert vc == {
        "missing": ["COLOR_0"],
        "pieces": 3,
        "pieces_without": 1,
        "reason": ce.VERTEX_COLOUR_REASON,
    }
    assert "colour byte order is not known" in vc["reason"] and "WATCHMEN_CONSOLE" in vc["reason"]
    assert "NORMAL and TANGENT are written" in vc["reason"]
    only = ce.not_decoded_extras([[_part(3, True, lost=True)]])["not_decoded"]
    assert list(only) == ["vertex_colour"]
    assert ce.not_decoded_extras([[_part(3, True, lost=True)]], attrs_wanted=False) is None
    json.dumps(nd)


def _write_model(d, name, h, s):
    d.mkdir(parents=True, exist_ok=True)
    (d / (name + ".model")).write_bytes(h)
    (d / (name + ".model.stream")).write_bytes(s)
    return str(d / (name + ".model"))


def test_extract_output_names_its_console_by_the_files_directory(tmp_path):
    (tmp_path / "files" / "Derived_PS3" / "levels").mkdir(parents=True)
    path = _write_model(tmp_path / "extracted" / "art", "A", *open_model("ps3"))
    assert we.detect_console_platform(str(tmp_path)) == "ps3"
    assert we.console_platform_for(path) == "ps3"
    assert we.console_platform_for(str(tmp_path / "loose" / "A.model")) is None
    assert we.console_platform_for(None) is None
    # a named console wins over the tree
    we.set_console_platform("x360")
    assert we.console_platform_for(path) == "x360"


def test_extract_output_without_a_named_console_is_inferred_from_its_models(tmp_path):
    ex = tmp_path / "extracted" / "art"
    a = _write_model(ex / "a", "Open", *open_model("x360"))
    assert we.detect_console_platform(str(tmp_path)) is None  # nothing decides yet
    _write_model(ex / "b", "Plain", *pm.build(">", "part2", console="x360"))
    assert we.detect_console_platform(str(tmp_path)) == "x360"
    assert we.console_platform_for(a) == "x360"
    # models that disagree: not established
    _write_model(ex / "c", "Other", *pm.build(">", "part2", console="ps3"))
    assert we.detect_console_platform(str(tmp_path)) is None
    # a PC tree has no console
    pc = tmp_path / "pc"
    _write_model(pc / "extracted" / "art", "P", *pm.build("<", "part2"))
    assert we.detect_console_platform(str(pc)) is None
    assert we.detect_console_platform(None) is None
    assert we.detect_console_platform(None, naz="X:/game/derived_x360") == "x360"


def test_extract_passes_the_block_path_console_to_every_model(tmp_path, monkeypatch, capsys):
    files = ps._two_block_tree(tmp_path)
    (files / "derived_pc").rename(files / "derived_ps3")
    seen = []

    def decode(header, stream, out_path, tex_index=None, log=None, order=None, lod=0):
        seen.append(we.console_platform())
        return True

    monkeypatch.setattr(we, "carve_texture", lambda *a, **k: True)
    monkeypatch.setattr(we, "decode_model", decode)
    monkeypatch.setattr(we, "HAVE_IMG", True)
    args = [str(files), "-o", str(tmp_path / "o"), "--no-files", "--no-text", "--no-audio"]
    assert we.main(args) == 0
    capsys.readouterr()
    assert seen and set(seen) == {"ps3"}
    assert we.console_platform() is None  # restored after the run
