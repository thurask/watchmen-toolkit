"""Untrusted input: .npz and pickle loading, CSV cells, output path names.

    load_npz        every bind / bake / cache .npz is read with allow_pickle=False;
                    a file that holds Python objects is refused with the recovery
                    command in the message
    restricted_load the shipped .pkl tables (and `variant_glb --bank`, `gendata
                    respell`) load as plain data: a pickle that names a class or a
                    function is refused before anything of it runs
    kapow_fragment  a corrupt key table is an ImportError with the recovery text
    csv_cell        a text CSV cell is never a spreadsheet formula
    safe            trailing dots / spaces, the Windows extended-length form
    exact_math      nearest_rotation of a reflection (documented behaviour)
    child stdin     every subprocess.run reads stdin from DEVNULL (WinError 6 without a
                    console)

Synthetic data only: no game files.
"""

import os
import pickle
import pickletools
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import wutil

REPO = Path(__file__).resolve().parent.parent
WLIB = REPO / "wlib"


# ---------------------------------------------------------------------------
# .npz without pickle
# ---------------------------------------------------------------------------


def _bind(path, names_dtype=None):
    names = ["GamePivot", "Pelvis", "L Hand"]
    np.savez(
        str(path),
        Rb=np.tile(np.eye(3), (3, 1, 1)),
        tb=np.zeros((3, 3)),
        tloc=np.zeros((3, 3)),
        par=np.array([-1, 0, 1]),
        names=np.array(names, dtype=names_dtype) if names_dtype else np.array(names),
    )
    return str(path)


def test_load_npz_reads_a_bind_the_toolkit_writes(tmp_path):
    p = _bind(tmp_path / "bind_x_file_v1.npz")
    z = wutil.load_npz(p)
    assert z["names"].dtype.kind == "U" and list(z["names"]) == ["GamePivot", "Pelvis", "L Hand"]
    assert (
        "par" in z and "mask" not in z and sorted(z.files) == ["Rb", "names", "par", "tb", "tloc"]
    )
    with wutil.load_npz(p) as z2:  # the `with np.load(...) as z` form of the callers
        assert np.array_equal(z2["par"], [-1, 0, 1])
    os.replace(p, str(tmp_path / "moved.npz"))  # nothing holds the file open


def test_load_npz_refuses_python_objects_with_the_recovery_command(tmp_path):
    p = _bind(tmp_path / "bind_x_file_v1.npz", names_dtype=object)
    with pytest.raises(ValueError) as ei:
        wutil.load_npz(p)
    msg = str(ei.value)
    assert msg == "%s holds Python objects; rebuild it with watchmen binds NAZ OUT_DIR" % p
    with pytest.raises(ValueError, match="holds Python objects; delete it"):
        wutil.load_npz(p, hint="delete it (it is written again)")


def test_load_npz_of_a_npy_and_other_errors(tmp_path):
    a = tmp_path / "a.npy"
    np.save(str(a), np.arange(4))
    assert wutil.load_npz(str(a)).tolist() == [0, 1, 2, 3]
    o = tmp_path / "o.npy"
    np.save(str(o), np.array([1, "x"], dtype=object))
    with pytest.raises(ValueError, match="holds Python objects"):
        wutil.load_npz(str(o))
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"not a zip at all")  # numpy would unpickle a file without a header
    with pytest.raises(ValueError, match="is not an .npz / .npy file .*watchmen binds"):
        wutil.load_npz(str(bad))
    with pytest.raises(OSError):
        wutil.load_npz(str(tmp_path / "missing.npz"))


def test_bake_refuses_an_object_bind(tmp_path):
    """The bind loaders go through load_npz: the baker refuses an object array."""
    import bake_v4

    p = _bind(tmp_path / "bind_x_file_v1.npz", names_dtype=object)
    with pytest.raises(ValueError, match="holds Python objects; rebuild it with watchmen binds"):
        bake_v4._load_bind(p)


def test_cli_reports_an_object_bind_as_one_error_line(tmp_path):
    p = _bind(tmp_path / "bind_x_file_v1.npz", names_dtype=object)
    r = subprocess.run(
        [sys.executable, "watchmen.py", "bake", "Clip", p, str(tmp_path / "o.npy"), "nothing.naz"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert r.stderr.strip().splitlines()[-1].startswith("error: ")
    assert "holds Python objects" in r.stderr and "Traceback" not in r.stderr


def test_no_toolkit_module_loads_with_allow_pickle():
    """One loader (wutil.load_npz); no module passes allow_pickle=True."""
    hits = []
    for p in (
        sorted(WLIB.glob("*.py")) + [REPO / "watchmen.py"] + sorted((REPO / "tools").glob("*.py"))
    ):
        if "allow_pickle=True" in p.read_text(encoding="utf-8"):
            hits.append(p.name)
    assert hits == []


# ---------------------------------------------------------------------------
# pickle tables as plain data
# ---------------------------------------------------------------------------


class _Evil:
    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return (os.system, ("echo pwned > %s" % self.marker,))


def test_restricted_load_refuses_a_pickle_that_runs_code(tmp_path):
    marker = tmp_path / "ran.txt"
    data = pickle.dumps({"keytable": _Evil(str(marker))}, protocol=2)
    ops = {op.name for op, _a, _p in pickletools.genops(data)}
    assert "GLOBAL" in ops and "REDUCE" in ops  # the classic os.system pickle
    with pytest.raises(pickle.UnpicklingError, match="plain data only"):
        wutil.restricted_loads(data)
    data4 = pickle.dumps(_Evil(str(marker)), protocol=4)  # STACK_GLOBAL form
    with pytest.raises(pickle.UnpicklingError):
        wutil.restricted_loads(data4)
    assert not marker.exists()


def test_restricted_load_builds_plain_data():
    d = {
        1: ("a", "number"),
        "s": {1, 2},
        "f": frozenset([3]),
        "ba": bytearray(b"xy"),
        "b": b"\x00\xff",
        "n": None,
        "l": [1.5, -2, True],
        "big": 2**70,
    }
    for proto in range(4, pickle.HIGHEST_PROTOCOL + 1):
        assert wutil.restricted_loads(pickle.dumps(d, protocol=proto)) == d
    # protocols 0-3 name builtins.set / frozenset / bytearray: allowed
    assert wutil.restricted_loads(pickle.dumps(d, protocol=3)) == d
    old = {k: v for k, v in d.items() if k not in ("b", "ba")}
    for proto in (0, 1, 2):
        assert wutil.restricted_loads(pickle.dumps(old, protocol=proto)) == old
    # ... but protocol 2 writes bytes as a call of _codecs.encode: refused
    with pytest.raises(pickle.UnpicklingError, match="_codecs.encode"):
        wutil.restricted_loads(pickle.dumps(b"\x00", protocol=2))


def test_restricted_load_refuses_a_persistent_id():
    import io

    class P(pickle.Pickler):
        def persistent_id(self, obj):
            return "x" if obj == "secret" else None

    buf = io.BytesIO()
    P(buf, protocol=4).dump(["secret"])
    with pytest.raises(pickle.UnpicklingError, match="persistent id"):
        wutil.restricted_loads(buf.getvalue())


@pytest.mark.parametrize("name", ["kapow_fragment_keys.pkl", "prop_hash_dict.pkl"])
def test_shipped_tables_hold_plain_data_only(name):
    data = (WLIB / name).read_bytes()
    ops = {op.name for op, _a, _p in pickletools.genops(data)}
    code = {
        "GLOBAL",
        "STACK_GLOBAL",
        "REDUCE",
        "BUILD",
        "INST",
        "OBJ",
        "NEWOBJ",
        "NEWOBJ_EX",
        "EXT1",
        "EXT2",
        "EXT4",
        "PERSID",
        "BINPERSID",
    }
    assert not (ops & code), sorted(ops & code)
    assert wutil.restricted_loads(data) == pickle.loads(data)


def _checkout(tmp_path, table_bytes):
    """A copy of watchmen.py + wlib/ whose fragment key table holds `table_bytes`."""
    root = tmp_path / "co"
    (root / "wlib").mkdir(parents=True)
    shutil.copy(str(REPO / "watchmen.py"), str(root / "watchmen.py"))
    for p in WLIB.iterdir():
        if p.suffix in (".py", ".json", ".pkl"):
            shutil.copy(str(p), str(root / "wlib" / p.name))
    (root / "wlib" / "kapow_fragment_keys.pkl").write_bytes(table_bytes)
    return root


_IMPORT = (
    "import sys; sys.path.insert(0, 'wlib')\n"
    "try:\n"
    "    import kapow_fragment\n"
    "except BaseException as ex:\n"
    "    print(type(ex).__name__); print(str(ex))\n"
    "else:\n"
    "    print('NO-ERROR')\n"
)


@pytest.mark.parametrize("kind", ["truncated", "not a pickle", "wrong layout", "runs code"])
def test_a_bad_key_table_is_an_import_error_with_the_recovery(tmp_path, kind):
    marker = tmp_path / "ran.txt"
    good = (WLIB / "kapow_fragment_keys.pkl").read_bytes()
    table = {
        "truncated": good[: len(good) // 2],
        "not a pickle": b"this is not a pickle",
        "wrong layout": pickle.dumps({"other": 1}, protocol=4),
        "runs code": pickle.dumps(_Evil(str(marker)), protocol=2),
    }[kind]
    root = _checkout(tmp_path, table)
    r = subprocess.run(
        [sys.executable, "-c", _IMPORT],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    lines = r.stdout.splitlines()
    assert r.returncode == 0, r.stderr
    assert lines[0] == "ImportError", r.stdout
    assert "unreadable data table" in r.stdout and "gendata keys-import" in r.stdout
    assert not marker.exists()
    # the CLI reports it as one error line, exit code 2
    r = subprocess.run(
        [sys.executable, "watchmen.py", "fragment", "x.fragment"],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 2 and r.stderr.startswith("error: watchmen: unreadable data table")


def test_variant_glb_bank_refuses_a_code_pickle(tmp_path):
    marker = tmp_path / "ran.txt"
    bank = tmp_path / "bank.pkl"
    bank.write_bytes(pickle.dumps({"Clip": _Evil(str(marker))}, protocol=2))
    r = subprocess.run(
        [
            sys.executable,
            str(WLIB / "variant_glb.py"),
            "f.json",
            "V",
            str(tmp_path / "o.glb"),
            "--bank",
            str(bank),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode != 0 and "UnpicklingError" in r.stderr and "plain data only" in r.stderr
    assert not marker.exists() and not (tmp_path / "o.glb").exists()


def test_gendata_respell_refuses_a_code_pickle(tmp_path):
    import gen_data

    marker = tmp_path / "ran.txt"
    src = tmp_path / "dict.pkl"
    src.write_bytes(pickle.dumps(_Evil(str(marker)), protocol=4))
    with pytest.raises(pickle.UnpicklingError):
        gen_data.main(["gen_data", "respell", str(src), "-o", str(tmp_path / "o.pkl")])
    assert not marker.exists() and not (tmp_path / "o.pkl").exists()


# ---------------------------------------------------------------------------
# CSV cells
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cell, out",
    [
        ("=SUM(A1:A2)", "'=SUM(A1:A2)"),
        ("+cmd", "'+cmd"),
        ("--Huh?", "'--Huh?"),  # in the Part 1 text assets (measured: 6 cells)
        ("@user", "'@user"),
        ("\tTab", "'\tTab"),
        ("\rCR", "'\rCR"),
        ("-5", "-5"),
        ("+1.25", "+1.25"),
        ("-0.5", "-0.5"),
        ("-", "'-"),
        ("- item", "'- item"),
        ("Hello", "Hello"),
        ("a=b", "a=b"),
        ("", ""),
        (7, 7),
        (None, None),
    ],
)
def test_csv_cell(cell, out):
    import text_assets as ta

    assert ta.csv_cell(cell) == out


def test_rows_csv_guards_keys_and_texts_and_the_json_stays_verbatim():
    import csv
    import io

    import text_assets as ta

    rows = [("KEY_A", "=1+1"), ("", ""), ("@KEY", "-3"), ("K", "--Huh?")]
    text = ta.rows_csv(rows)
    got = list(csv.reader(io.StringIO(text)))
    assert got == [
        ["index", "key", "text"],
        ["0", "KEY_A", "'=1+1"],
        ["2", "'@KEY", "-3"],
        ["3", "K", "'--Huh?"],
    ]
    j = ta.rows_json("x", rows, 0)
    assert [(e["key"], e["text"]) for e in j["entries"]] == [
        ("KEY_A", "=1+1"),
        ("@KEY", "-3"),
        ("K", "--Huh?"),
    ]


# ---------------------------------------------------------------------------
# output path names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "part, out",
    [
        ("Foo. ", "Foo__"),
        ("Foo.", "Foo_"),
        ("a b", "a b"),
        ("...", "___"),
        (" ", "_"),
        ("x.png", "x.png"),
        ("CON.", "CON_"),
    ],
)
def test_no_trailing_dots(part, out):
    import watchmen_extract as we

    assert we._no_trailing_dots(part) == out


def test_safe_replaces_trailing_dots_and_spaces_on_every_system(tmp_path):
    import watchmen_extract as we

    assert we.safe(tmp_path, "Art/Foo. /x.png") == tmp_path / "Art" / "Foo__" / "x.png"
    assert we.safe(tmp_path, "Art/Foo/x.png") == tmp_path / "Art" / "Foo" / "x.png"
    # two names Windows would put in one folder stay apart
    assert we.safe(tmp_path, "a/Foo./b") != we.safe(tmp_path, "a/Foo/b")
    assert we.safe(tmp_path, "CON. /x") == tmp_path / "CON__" / "x"
    assert we.out_rel(tmp_path, "Art/Foo. /x.png") == "Art/Foo__/x.png"


def test_long_path_only_on_windows_and_only_when_long():
    short = "C:\\out\\textures\\a.png"
    long_ = "C:\\" + "\\".join(["d%02d_xxxxxxxxxxxxxxxxx" % i for i in range(12)]) + "\\x.png"
    assert len(long_) >= wutil.LONG_PATH_LIMIT
    assert wutil.long_path(long_, nt=False) == long_  # Linux / macOS: unchanged
    assert wutil.long_path(short, nt=True) == short
    assert wutil.long_path(long_, nt=True) == "\\\\?\\" + long_
    assert wutil.long_path("\\\\?\\" + long_, nt=True) == "\\\\?\\" + long_  # once
    unc = "\\\\server\\share\\" + long_[3:]
    assert wutil.long_path(unc, nt=True) == "\\\\?\\UNC\\server\\share\\" + long_[3:]
    edge = "C:\\" + "x" * (wutil.LONG_PATH_LIMIT - 3)
    assert len(edge) == wutil.LONG_PATH_LIMIT and wutil.long_path(edge, nt=True).startswith(
        "\\\\?\\"
    )
    assert wutil.long_path(edge[:-1], nt=True) == edge[:-1]


def test_plain_path_and_rel_path():
    assert wutil.plain_path("\\\\?\\C:\\a\\b") == "C:\\a\\b"
    assert wutil.plain_path("\\\\?\\UNC\\srv\\s\\a") == "\\\\srv\\s\\a"
    assert wutil.plain_path(Path("/tmp/a")) == str(Path("/tmp/a"))
    assert wutil.rel_path("/o/models/a/b.obj", "/o/models") == os.path.join("a", "b.obj")


def test_safe_is_unchanged_here(tmp_path):
    """On this system (not Windows) safe() gives the plain path even when it is long."""
    import watchmen_extract as we

    name = "/".join(["folder_%02d_xxxxxxxxxxxxxxxxxxxxxxxx" % i for i in range(10)]) + "/x.png"
    out = we.safe(tmp_path, name)
    if os.name != "nt":
        assert out == tmp_path.joinpath(*name.split("/"))
        assert len(str(out)) >= wutil.LONG_PATH_LIMIT


# ---------------------------------------------------------------------------
# exact_math.nearest_rotation of a reflection
# ---------------------------------------------------------------------------


def test_nearest_rotation_keeps_a_reflection():
    """The polar factor keeps det < 0: a mirrored input gives a reflection back
    (documented; the callers feed near-rotations)."""
    import exact_math as em

    near = ((1.0, 1e-9, 0.0), (-1e-9, 1.0, 0.0), (0.0, 0.0, 1.0 + 1e-9))
    R = np.array(em.nearest_rotation(near))
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-12) and np.linalg.det(R) > 0
    mirrored = ((-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    M = np.array(em.nearest_rotation(mirrored))
    assert np.allclose(M, np.array(mirrored)) and np.linalg.det(M) == pytest.approx(-1.0)
    skewed = ((-1.1, 0.05, 0.0), (0.02, 0.9, 0.01), (0.0, 0.03, 1.2))
    S = np.array(em.nearest_rotation(skewed))
    U, _s, Vt = np.linalg.svd(np.array(skewed))
    assert np.allclose(S, U @ Vt, atol=1e-12) and np.linalg.det(S) == pytest.approx(-1.0)


def test_every_child_process_reads_its_input_from_devnull():
    """A child process inherits the parent's stdin unless told otherwise; a run started without
    a console (a scheduler, another program) hands on an invalid handle and subprocess fails in
    DuplicateHandle with WinError 6. Every subprocess.run in the toolkit and its tests passes
    stdin (or input)."""
    import ast

    missing = []
    files = [REPO / "watchmen.py", *sorted((REPO / "wlib").glob("*.py"))]
    files += sorted((REPO / "tests").glob("*.py")) + sorted((REPO / "tools").glob("*.py"))
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            f = node.func if isinstance(node, ast.Call) else None
            if (
                isinstance(f, ast.Attribute)
                and f.attr in ("run", "Popen", "call", "check_call", "check_output")
                and isinstance(f.value, ast.Name)
                and f.value.id == "subprocess"
                and not {k.arg for k in node.keywords} & {"stdin", "input"}
            ):
                missing.append("%s:%d" % (path.relative_to(REPO), node.lineno))
    assert missing == []
