"""Python 3.13 modernisation of the extractor, the CLI and the Blender tools.

    strict zip   the pairings whose two sides must have one length now fail
                 with ValueError on a mismatch instead of dropping the tail
    add_note     a parse / extract failure carries where it happened (archive,
                 entry, offset, asset, byte order) as an exception note; the
                 message and the exception type are unchanged, and the extract
                 log (str of the exception) does not change either
    CLI          `watchmen.py` prints the notes under its one-line error

Synthetic data only: no game files.
"""

import struct
import zlib

import numpy as np
import pytest

import watchmen
import watchmen_extract as we
from test_formats_v2 import _TEX, _block


def _notes(ei):
    return "\n".join(getattr(ei.value, "__notes__", ()))


# ---------------------------------------------------------------------------
# strict zip: a length mismatch is an error
# ---------------------------------------------------------------------------


def test_rescue_plan_refuses_a_mip_tuple_shorter_than_its_records(monkeypatch):
    """_rescue_texture_plan pairs every candidate record with one mip count; a
    solution of the wrong length used to score a plan with the tail left out."""
    recs = {0: {"enum": 5, "aw": 4, "ah": 4, "mip": 1}, 40: {"enum": 5, "aw": 4, "ah": 4, "mip": 1}}
    monkeypatch.setattr(we, "parse_texture_header", lambda h, o="<": {"images": [{"rec_off": 0}]})
    monkeypatch.setattr(we, "_tex_path_off", lambda h: 80)
    monkeypatch.setattr(we, "_valid_rec", lambda h, pos, powtwo=False, order="<": recs.get(pos))
    monkeypatch.setattr(we, "_decode_one_layer", lambda *a, **k: np.zeros((4, 4), np.uint8))
    monkeypatch.setattr(we, "_exact_mip_sums", lambda r, total: [(1,) * (len(r) - 1 or 1)])
    with pytest.raises(ValueError, match="zip"):
        we._rescue_texture_plan(b"\0" * 80, b"\0" * 64)


def test_rescue_plan_unchanged_when_the_lengths_agree(monkeypatch):
    recs = {0: {"enum": 5, "aw": 4, "ah": 4, "mip": 1}}
    monkeypatch.setattr(we, "parse_texture_header", lambda h, o="<": {"images": [{"rec_off": 0}]})
    monkeypatch.setattr(we, "_tex_path_off", lambda h: 80)
    monkeypatch.setattr(we, "_valid_rec", lambda h, pos, powtwo=False, order="<": recs.get(pos))
    monkeypatch.setattr(we, "_decode_one_layer", lambda *a, **k: np.zeros((4, 4), np.uint8))
    monkeypatch.setattr(we, "_exact_mip_sums", lambda r, total: [(1,) * len(r)])
    assert we._rescue_texture_plan(b"\0" * 80, b"\0" * 64) == [(5, 4, 4, 1)]


def _restored_lashes():
    """72 UV pairs in the restored layout: four strips at the upper strip's mean."""
    _mean, s, (du, dv) = we.LASH_RESTORE["strips"]["upper"]
    stored = [(0.01 + 0.001 * k, 0.4137) for k in range(we.LASH_RESTORE["strip_vertices"])] * 4
    return [(s * u + du, s * v + dv) for u, v in stored]


def test_lash_is_restored_refuses_a_round_trip_of_another_length(monkeypatch):
    uvs = _restored_lashes()
    monkeypatch.setattr(we, "lash_restored_uvs", lambda back: list(uvs[:-1]))
    with pytest.raises(ValueError, match="zip"):
        we.lash_is_restored(uvs)
    monkeypatch.setattr(we, "lash_restored_uvs", lambda back: list(uvs))
    assert we.lash_is_restored(uvs) is True


def test_mtl_writer_refuses_names_that_do_not_pair_with_the_materials(tmp_path, monkeypatch):
    """_write_obj_mtl writes one newmtl per material under its unique name; a name
    list of another length used to leave materials out of the .mtl."""
    v = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    args = (v, None, None, [(0, 1, 2)], [(0, 3, 0, 1, 44)], ["a", "b"], None, None)
    we._write_obj_mtl(tmp_path / "ok.obj", "ok", *args)
    assert (tmp_path / "ok.mtl").read_text().count("newmtl") == 2
    monkeypatch.setattr(we, "unique_material_names", lambda mats: [str(m) for m in mats][:1])
    with pytest.raises(ValueError, match="zip"):
        we._write_obj_mtl(tmp_path / "bad.obj", "bad", *args)


def test_rows3_refuses_ragged_columns():
    class Ragged:
        T = type("T", (), {"tolist": staticmethod(lambda: [[1.0, 2.0], [3.0], [5.0, 6.0]])})

        def __len__(self):
            return 2

    with pytest.raises(ValueError, match="zip"):
        we._rows3(Ragged())
    assert we._rows3(np.arange(6.0).reshape(2, 3)) == [(0.0, 1.0, 2.0), (3.0, 4.0, 5.0)]


# ---------------------------------------------------------------------------
# add_note: where a parse failed
# ---------------------------------------------------------------------------


def _eocd(titem, doffs):
    return struct.pack("<IHHHHIIH", we.NAZ_HEAD, 0, 0, titem, titem, 0, doffs, 0)


def test_naz_entries_notes_the_central_directory_record(tmp_path):
    p = tmp_path / "bad.naz"
    p.write_bytes(b"\0" * 64 + _eocd(3, 0))
    with pytest.raises(ValueError, match="bad central-dir magic at 0x0") as ei:
        list(we.naz_entries(p))
    assert "central-directory record 0 of 3 at 0x0" in _notes(ei)
    assert str(p) in _notes(ei)
    assert str(ei.value) == "bad central-dir magic at 0x0"  # the message is unchanged


def test_naz_entries_notes_the_archive_that_is_not_one(tmp_path):
    p = tmp_path / "plain.zip"
    p.write_bytes(b"PK" + b"\0" * 40)
    with pytest.raises(ValueError, match="not a NAZ archive") as ei:
        list(we.naz_entries(p))
    assert str(p) in _notes(ei) and "EOCD record at 0x14 of 42 bytes" in _notes(ei)


def test_naz_read_notes_the_entry(tmp_path):
    p = tmp_path / "x.naz"
    p.write_bytes(b"\0" * 16 + b"\xff\xfe\xfd\xfc not deflate")
    bad = we.NazEntry("/levels/x.block_h_z", 8, 16, 100, 16)
    with pytest.raises(zlib.error) as ei:
        we.naz_read(p, bad)
    n = _notes(ei)
    assert "entry /levels/x.block_h_z, 16 bytes stored at 0x10, method 8" in n and str(p) in n
    other = we.NazEntry("/levels/y.bin", 9, 4, 4, 0)
    with pytest.raises(ValueError, match="unsupported compression 9") as ei:
        we.naz_read(p, other)
    assert "entry /levels/y.bin, 4 bytes stored at 0x0, method 9" in _notes(ei)
    stored = we.NazEntry("/levels/z.bin", 0, 4, 4, 0)
    assert we.naz_read(p, stored) == b"\0" * 4  # the good paths are untouched


def test_extract_block_notes_a_short_header():
    with pytest.raises(struct.error) as ei:
        list(we.extract_block(b"\0" * 100, None))
    assert "block header: 100 bytes, language slot 0" in _notes(ei)


def test_extract_block_notes_the_asset_whose_blob_fails(monkeypatch):
    blob = zlib.compress(b"\x08\0\0\0Texture\0" + b"\0" * 200)
    h, s = _block([("tex_a", _TEX, blob, None)])
    assert [e.name for e, _h, _s in we.extract_block(h, s)] == ["tex_a"]
    monkeypatch.setenv("WATCHMEN_MAX_INFLATE", "64")
    with pytest.raises(ValueError, match="inflate ceiling") as ei:
        list(we.extract_block(h, s))
    n = _notes(ei)
    assert "block asset tex_a (record 0, type Texture, little-endian (PC))" in n
    assert "header blob at 0x%X, %d bytes" % (400 + 24 + 4 + 4 + 6 + 1, len(blob)) in n


def _trailer_block(blob):
    """A 400-byte block header with one directory record slot and `blob` as its
    trailing stream-set table."""
    h = bytearray(400)
    struct.pack_into("<9I", h, 328, 0, 0, 0, 0, 400, len(blob), 1, 0, 0)
    return bytes(h) + blob


def test_block_trailer_notes_both_layouts_and_keeps_the_report_text():
    h = _trailer_block(struct.pack("<I", 1))  # one automatic set, then the blob ends
    with pytest.raises(ValueError, match="read past its end") as ei:
        we.parse_block_trailer(h)
    assert (
        "block trailer at 0x190, 4 bytes, little-endian (PC): read with 3-float and with "
        "4-float stream-set bounds" in _notes(ei)
    )
    # block_stream_sets reports the message alone (what the extract log shows)
    assert we.block_stream_sets(h) == ([], "block trailer: read past its end")


def test_carve_texture_notes_the_texture(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise struct.error("unpack_from requires a buffer of at least 8 bytes")

    monkeypatch.setattr(we, "_is_texture", boom)
    with pytest.raises(struct.error) as ei:
        we.carve_texture(b"\0" * 32, b"\0" * 6, tmp_path / "Wall.bmp")
    assert "texture Wall.bmp: header 6 bytes, stream 32 bytes, byte order not known" in _notes(ei)


def test_decode_model_notes_the_model_and_the_console(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise ValueError("vertex format 99")

    monkeypatch.setattr(we, "_header_model_plan", boom)
    monkeypatch.setenv("WATCHMEN_CONSOLE", "ps3")
    with pytest.raises(ValueError, match="vertex format 99") as ei:
        we.decode_model(b"\0" * 12, b"\0" * 40, tmp_path / "Crate.obj", order=">")
    assert (
        "model Crate.obj: header 12 bytes, stream 40 bytes, big-endian (Xbox 360 / PS3), "
        "platform ps3" in _notes(ei)
    )


def test_cli_prints_the_notes_under_the_error(monkeypatch, capsys):
    def boom(argv):
        ex = ValueError("bad central-dir magic at 0x0")
        ex.add_note("archive game.naz: central-directory record 0 of 3 at 0x0")
        raise ex

    monkeypatch.delenv("WATCHMEN_DEBUG", raising=False)
    monkeypatch.setattr(watchmen, "main", boom)
    with pytest.raises(SystemExit) as ei:
        watchmen.cli()
    assert ei.value.code == 2
    assert capsys.readouterr().err.splitlines() == [
        "error: bad central-dir magic at 0x0",
        "  archive game.naz: central-directory record 0 of 3 at 0x0",
    ]


# ---------------------------------------------------------------------------
# the rewritten helpers give the values of the code they replace
# ---------------------------------------------------------------------------


def test_batched_pairs_and_cached_tables_match_the_loops():
    v = tuple(range(12))
    assert list(we.itertools.batched(v, 2)) == [(v[2 * k], v[2 * k + 1]) for k in range(6)]
    assert we._COEF_PAIRS == tuple(zip(we._C1, we._C2))
    assert we.asset_type_name(we._name_hash("Texture")) == "Texture"
    assert we.asset_type_name(0) == ""
    assert we._sheet_keys() is we._sheet_keys() and we._sheet_hashes() is we._sheet_hashes()
    assert we._names_mod() is we._names_mod()


def test_move_out_option_strips_the_prefix_only():
    assert watchmen.move_out_option(["game.naz", "--out=--out=x"]) == ["game.naz", "--out=x"]


def test_cached_tables_hold_what_their_sources_give():
    """The tables loaded once with functools.cache (module globals filled on first use
    before): the contents their source gives, and one shared object per table."""
    import json
    import os

    import canonical_names
    import engine_enums
    import engine_schema
    import gen_data
    import kapow_json
    import level_meta

    wlib = os.path.dirname(os.path.abspath(we.__file__))

    def shipped(name):
        with open(os.path.join(wlib, name), encoding="utf-8") as fh:
            return json.load(fh)

    assert we._asset_types() == {we._name_hash(n): n for n in we.ASSET_TYPE_NAMES}
    sheet_names = [*we.TEXTURE_SHEET_PROPS, "integer", "truth", "number"]
    assert we._sheet_hashes() == {n: we._name_hash(n) for n in sheet_names}
    types = ("number", "integer", "truth", "string", "vector", "color")
    assert we._sheet_keys() == (
        {we._name_hash(n): n for n in we.SHEET_PROPERTIES}
        | {("type", we._name_hash(t)): t for t in types}
        | {("type", we._T_UNIQUE_ID): "id"}
    )
    assert we._names_mod() is canonical_names and we._kapow_json() is kapow_json
    assert canonical_names.table() == dict(shipped("canonical_names.json")["names"])
    assert engine_enums.data() == shipped("engine_enums.json")
    assert level_meta._input_codes() == shipped("input_code_enums.json")
    assert engine_schema.prop_names() == gen_data.derive_prop_names(engine_schema.reg())
    for table in (
        we._asset_types,
        we._sheet_hashes,
        we._sheet_keys,
        canonical_names.table,
        engine_enums.data,
        level_meta._input_codes,
        engine_schema.prop_names,
    ):
        assert table() is table(), table.__qualname__


# ---------------------------------------------------------------------------
# the Python version: 3.13 for the toolkit, Blender's own Python for tools/
# ---------------------------------------------------------------------------


def test_python_too_old_names_the_minimum_and_the_running_version():
    assert watchmen.MIN_PYTHON == (3, 13)
    assert watchmen.python_too_old() is None  # the suite runs on 3.13 or later
    assert watchmen.python_too_old((3, 13, 0, "final", 0)) is None
    assert watchmen.python_too_old((3, 14, 6)) is None
    assert watchmen.python_too_old((3, 12, 9, "final", 0)) == (
        "error: watchmen-kapow-toolkit needs Python 3.13 or later (this is 3.12)"
    )
    assert watchmen.python_too_old((3, 10, 0)) == (
        "error: watchmen-kapow-toolkit needs Python 3.13 or later (this is 3.10)"
    )


def test_watchmen_py_on_an_older_python_stops_before_importing_wlib():
    """`python3 watchmen.py` on 3.12 (sys.version_info replaced before the script
    runs): exit code 2 and the one line, before anything from wlib/ is imported."""
    import os
    import subprocess
    import sys

    script = os.path.join(os.path.dirname(os.path.abspath(watchmen.__file__)), "watchmen.py")
    probe = (
        "import runpy, sys\n"
        "sys.version_info = (3, 12, 9, 'final', 0)\n"
        "sys.argv = [%r, '--version']\n"
        "try:\n"
        "    runpy.run_path(%r, run_name='__main__')\n"
        "except SystemExit as ex:\n"
        "    print('exit', ex.code, 'wutil' in sys.modules, 'wlib' in sys.modules)\n"
        % (script, script)
    )
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        env=env,
        stdin=subprocess.DEVNULL,
    )
    assert p.stderr == "error: watchmen-kapow-toolkit needs Python 3.13 or later (this is 3.12)\n"
    assert p.stdout == "exit 2 False False\n"


#: Library names of Python 3.11 and later that Blender 3.6's Python (3.10) lacks.
_NEWER_THAN_310 = {
    "batched",  # itertools, 3.12
    "add_note",  # BaseException, 3.11
    "ExceptionGroup",
    "BaseExceptionGroup",
    "TaskGroup",
    "tomllib",
    "StrEnum",
    "Self",
    "LiteralString",
    "Never",
    "assert_never",
    "reveal_type",
    "override",
    "UTC",
}


def _py310_problems(src):
    """What in `src` Python 3.10 cannot run: grammar of 3.11+ (`except*`, `type`, type
    parameters), the f-strings of 3.12 (a quote of the enclosing string, a backslash or
    a comment inside a replacement field) and the library names of _NEWER_THAN_310."""
    import ast
    import io
    import tokenize

    try:
        tree = ast.parse(src, feature_version=(3, 10))
    except SyntaxError as ex:
        return ["syntax: %s (line %s)" % (ex.msg, ex.lineno)]
    out = []
    for node in ast.walk(tree):
        name = (
            node.id
            if isinstance(node, ast.Name)
            else node.attr
            if isinstance(node, ast.Attribute)
            else None
        )
        if name in _NEWER_THAN_310:
            out.append("%s (line %d)" % (name, node.lineno))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                if a.name in _NEWER_THAN_310 or getattr(node, "module", None) == "tomllib":
                    out.append("import %s (line %d)" % (a.name, node.lineno))
    quotes = []  # enclosing f-string quotes, outermost first
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.FSTRING_START:
            if quotes and quotes[0] in tok.string:
                out.append("f-string quote reused (line %d)" % tok.start[0])
            quotes.append(tok.string.lstrip("rRfFbBuU"))
        elif tok.type == tokenize.FSTRING_END:
            quotes.pop()
        elif quotes and tok.type == tokenize.FSTRING_MIDDLE:
            if len(quotes) > 1 and quotes[0] in tok.string:
                out.append("f-string quote reused (line %d)" % tok.start[0])
        elif quotes:
            if tok.type == tokenize.COMMENT or "\\" in tok.string:
                out.append("backslash or comment in an f-string field (line %d)" % tok.start[0])
            elif tok.type == tokenize.STRING and quotes[0] in tok.string:
                out.append("f-string quote reused (line %d)" % tok.start[0])
    return out


def test_py310_check_finds_what_python_310_cannot_run():
    assert _py310_problems("x = list(zip(a, b, strict=True))\nmatch x:\n    case _: pass\n") == []
    assert _py310_problems("y = f'{x!r:>10}' + f\"{'a'}\" + f'''{\"b\"}'''\n") == []
    assert _py310_problems("import itertools\nitertools.batched(v, 2)\n") == ["batched (line 2)"]
    assert _py310_problems("e.add_note('x')\n") == ["add_note (line 1)"]
    assert _py310_problems("try:\n    pass\nexcept* ValueError:\n    pass\n")[0].startswith(
        "syntax: "
    )
    assert _py310_problems('y = f"{"a"}"\n') == ["f-string quote reused (line 1)"]
    assert _py310_problems("y = f'{chr(10)!r}' + f'{\"\\n\".join(v)}'\n") == [
        "backslash or comment in an f-string field (line 1)"
    ]


def test_blender_scripts_run_on_the_python_of_blender_36():
    """tools/*.py run inside Blender (3.6 bundles Python 3.10); the toolkit's 3.13
    minimum does not apply to them."""
    import os

    tools = os.path.join(os.path.dirname(os.path.abspath(watchmen.__file__)), "tools")
    names = sorted(n for n in os.listdir(tools) if n.endswith(".py"))
    assert names == ["blender_attach_extras.py", "blender_import_level.py"]
    for n in names:
        with open(os.path.join(tools, n), encoding="utf-8") as fh:
            assert _py310_problems(fh.read()) == [], n
