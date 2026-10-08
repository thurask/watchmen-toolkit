"""wlib closes the files it opens.

A file opened as `open(p, "rb").read()` or `json.load(open(p))` is closed only when
the garbage collector gets to it: at once on CPython, later (or never before exit) on
other interpreters, and on Windows an open file cannot be replaced or removed in the
meantime.  Every `open()` in the toolkit's code is the subject of a `with`; a module
that only wants the bytes has a `_read_bytes` helper.

Synthetic data only: no game files.
"""

import ast
import gc
import glob
import io
import os
import struct
import warnings
import wave

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = sorted(
    glob.glob(os.path.join(ROOT, "wlib", "*.py"))
    + glob.glob(os.path.join(ROOT, "tools", "*.py"))
    + [os.path.join(ROOT, "watchmen.py")]
)


def _bare_opens(path):
    """(line, source) of every builtin open() call that is not a `with` item."""
    with io.open(path, encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    managed = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            managed.update(id(item.context_expr) for item in node.items)
    out = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "open"
            and id(node) not in managed
        ):
            out.append((node.lineno, src.splitlines()[node.lineno - 1].strip()))
    return out


def test_the_scan_sees_a_bare_open(tmp_path):
    p = tmp_path / "m.py"
    p.write_text(
        'def f(p):\n    a = open(p, "rb").read()\n    with open(p) as fh:\n        b = fh.read()\n'
        '    import json\n    return a, b, json.load(open(p))\n\n\n"""doc: open(x).read()"""\n'
    )
    assert [n for n, _ in _bare_opens(str(p))] == [2, 6]


def test_every_open_in_the_toolkit_is_a_with_item():
    assert len(SOURCES) > 40
    bad = [
        "%s:%d: %s" % (os.path.relpath(p, ROOT), n, s) for p in SOURCES for n, s in _bare_opens(p)
    ]
    assert bad == []


def test_read_bytes_helpers_are_the_same_function_everywhere():
    """One three-line helper per module that needs it (the modules are flat scripts and
    several run on their own): all copies must stay the same."""
    bodies = {}
    for p in SOURCES:
        with io.open(p, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "_read_bytes":
                bodies[os.path.basename(p)] = ast.dump(node)
    assert len(bodies) >= 10 and len(set(bodies.values())) == 1


@pytest.fixture
def strict():
    """ResourceWarning is an error for the test, and anything left over is collected
    inside it."""
    with warnings.catch_warnings():
        warnings.simplefilter("error", ResourceWarning)
        yield
        gc.collect()


def test_read_bytes_reads_and_closes(tmp_path, strict):
    import characters_export
    import kapow_json
    import watchmenlib

    p = tmp_path / "x.bin"
    p.write_bytes(b"\x00\x01kapow\xff")
    for mod in (characters_export, kapow_json, watchmenlib):
        assert mod._read_bytes(str(p)) == b"\x00\x01kapow\xff"
    with pytest.raises(OSError):
        kapow_json._read_bytes(str(tmp_path / "missing.bin"))
    os.replace(str(p), str(tmp_path / "y.bin"))  # nothing holds the file


def test_write_wav_gives_the_same_file_and_closes(tmp_path, strict):
    import watchmen_extract as wx

    pcm = struct.pack("<8h", 0, 1000, -1000, 32767, -32768, 5, -5, 0)
    out = tmp_path / "sub" / "a.wav"
    wx.write_wav(pcm, 2, 22050, out)
    with wave.open(str(out), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, 22050)
        assert w.readframes(w.getnframes()) == pcm
    ref = tmp_path / "ref.wav"
    w = wave.open(str(ref), "wb")  # the sequence write_wav used before
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(22050)
    w.writeframes(pcm)
    w.close()
    assert out.read_bytes() == ref.read_bytes()
    looped = tmp_path / "loop.wav"
    wx.write_wav(pcm, 2, 22050, looped, loop=True)
    data = looped.read_bytes()
    assert data[:44] != out.read_bytes()[:44] and b"smpl" in data  # RIFF size + loop chunk
    os.remove(str(out))


def test_the_data_tables_load_without_leaving_a_handle(strict, monkeypatch):
    import engine_schema
    import ragdoll_rig

    monkeypatch.setattr(engine_schema, "_reg", None)
    reg = engine_schema.reg()
    assert isinstance(reg, (dict, list)) and len(reg) > 100
    monkeypatch.setattr(ragdoll_rig, "_names_cache", {})
    src = open  # the loader goes through builtins.open: count what it leaves open
    opened = []

    def spy(*a, **k):
        fh = src(*a, **k)
        opened.append(fh)
        return fh

    monkeypatch.setattr("builtins.open", spy)
    names = ragdoll_rig.property_names()
    assert len(names) > 100
    assert opened and all(fh.closed for fh in opened)


def test_fragment_json_of_a_path_closes_the_file(tmp_path, strict, monkeypatch):
    import watchmenlib

    p = tmp_path / "t.fragment"
    p.write_bytes(b"\x00" * 17)
    seen = []
    monkeypatch.setattr(watchmenlib._kj, "to_json", lambda name, data: seen.append((name, data)))
    watchmenlib.fragment_json_file(str(p))
    assert seen == [(str(p).lower(), b"\x00" * 17)]
