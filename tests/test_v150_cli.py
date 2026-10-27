"""The command line: the option table, per-command help, unknown options, exit
codes, WATCHMEN_DEBUG, the archive default, the version and the packaging.

    n7   one table of options (watchmen.OPTIONS) parses every command line; `CMD -h`
         prints CMD's usage, description and options; an unknown --option of a
         command without a parser of its own is an error, exit code 2
    n9   `fragment` exits 3 when the JSON is not lossless (documented in -h)
    m10  every command and library default reads 01_game.naz, else game.naz
    m11  WATCHMEN_DEBUG prints the traceback before the one-line error
    m12  one version: pyproject, wlib.__version__, watchmen.VERSION, CHANGELOG
    m13  the facade imports (a broken table is an error, never a skip)
    m16  classifiers, the console scripts, the package data

Synthetic data only: no game files.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import watchmen

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# m13: the facade imports
# ---------------------------------------------------------------------------


def test_facade_import():
    """`import watchmenlib` works in a checkout: the data tables are there and
    readable.  Tests that need the facade import it without a guard, so a broken
    facade fails them instead of skipping them."""
    import watchmenlib as wl

    assert wl.kapow_hash("position") == 0x15DE4806
    assert callable(wl.extract_all) and callable(wl.ensure_binds)


# ---------------------------------------------------------------------------
# n7: the option table
# ---------------------------------------------------------------------------


def test_every_option_names_real_commands():
    for o in watchmen.OPTIONS:
        assert o.flag.startswith("--") and o.commands
        assert set(o.commands) <= set(watchmen.USAGE), o.flag
        assert set(o.env_commands) <= set(o.commands) and set(o.keep) <= set(o.commands)
    flags = [o.flag for o in watchmen.OPTIONS]
    assert len(flags) == len(set(flags))


def test_each_usage_line_lists_the_options_of_its_command():
    """The usage line of a command names every option of the table it takes."""
    missing = []
    for o in watchmen.OPTIONS:
        for cmd in o.commands:
            if o.flag not in watchmen.USAGE[cmd][1] and not (
                cmd == "extract" and o.flag == "--glb-texture-size"
            ):
                missing.append((cmd, o.flag))
    assert missing == []


@pytest.mark.parametrize("cmd", sorted(watchmen.USAGE))
def test_help_of_every_command(cmd, capsys):
    if cmd == "extract":
        with pytest.raises(SystemExit):  # the extractor's own argparse help
            watchmen.main(["w", cmd, "-h"])
        assert "--vgmstream-cli" in capsys.readouterr().out
        return
    assert watchmen.main(["w", cmd, "--help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: watchmen.py %s" % watchmen.USAGE[cmd][1].split(" ")[0])
    for o in watchmen.OPTIONS:
        assert (o.flag in out) == (cmd in o.commands), (cmd, o.flag)


def test_help_shows_the_description_and_the_choices(capsys):
    assert watchmen.main(["w", "characters", "-h"]) == 0
    out = capsys.readouterr().out
    assert "Folder per character, one glb per fragment" in out
    assert "--jiggle-model {solver,pivot,pinned}" in out and "--rig {hierarchy,flat}" in out
    assert "[--face-rule engine|legacy]" not in out.split("\n\n", 1)[1].split("options:")[0]
    assert watchmen.main(["w", "fragment", "-h"]) == 0
    out = capsys.readouterr().out
    assert "3: written, but the" in out and "--json-floats {exact,rounded}" in out
    assert watchmen.main(["w", "all", "-h"]) == 0
    out = capsys.readouterr().out
    assert "--glb-texture-size N" in out and "Every option of `extract`" in out


@pytest.mark.parametrize(
    "argv",
    [
        ["binds", "a", "b", "--glb"],
        ["characters", "a", "b", "--quiet"],
        ["levelmeta", "a", "b", "--frmae", "true"],
        ["hash", "--upper"],
        ["fragment", "x", "--json-float", "exact"],
    ],
)
def test_unknown_option_is_an_error(argv, capsys):
    assert watchmen.main(["w"] + argv) == 2
    out = capsys.readouterr().out
    bad = next(a for a in argv if a.startswith("--"))
    assert "error: unknown option %s for %s" % (bad, argv[0]) in out
    assert "usage: watchmen.py %s" % argv[0] in out


def test_option_of_another_command_keeps_its_message(capsys):
    assert watchmen.main(["w", "binds", "a", "b", "--glb-texture-size", "512"]) == 2
    assert "error: --glb-texture-size applies to: all, extract" in capsys.readouterr().out
    assert watchmen.main(["w", "faces", "a", "b", "--no-face-idle"]) == 2
    assert (
        "error: --face-rule / --no-face-idle apply to: all, characters" in capsys.readouterr().out
    )


def test_extract_and_all_pass_other_options_on_in_order():
    env = {}
    rest, opts = watchmen.parse_options(
        "extract",
        [
            "N",
            "O",
            "--vgmstream-cli",
            "C:/v.exe",
            "--rig",
            "flat",
            "--glb",
            "--glb-texture-size",
            "512",
            "--no-vertex-attrs",
            "--frame",
            "mirrored",
        ],
        env,
    )
    assert rest == [
        "N",
        "O",
        "--vgmstream-cli",
        "C:/v.exe",
        "--glb",
        "--glb-texture-size",
        "512",
        "--no-vertex-attrs",
    ]
    assert env == {"WATCHMEN_RIG": "flat", "WATCHMEN_FRAME": "mirrored"}
    assert opts["--glb-texture-size"] == "512" and opts["--no-vertex-attrs"] is True
    env = {}
    rest, opts = watchmen.parse_options(
        "all", ["N", "O", "--jiggle-model", "pinned", "--no-vertex-attrs", "--keep-xma"], env
    )
    assert (
        rest == ["N", "O", "--no-vertex-attrs", "--keep-xma"] and opts["--jiggle-model"] == "pinned"
    )
    assert env == {"WATCHMEN_VERTEX_ATTRS": "0"}


def test_scriptdb_and_gendata_keep_their_own_options():
    rest, _ = watchmen.parse_options("scriptdb", ["db.bin", "--find", "x"], {})
    assert rest == ["db.bin", "--find", "x"]
    rest, _ = watchmen.parse_options("gendata", ["strings", "exe", "-o", "o.pkl", "--anything"], {})
    assert rest == ["strings", "exe", "-o", "o.pkl", "--anything"]


def test_a_rejected_line_sets_no_environment():
    env = {}
    with pytest.raises(watchmen.OptionError, match="--frame takes one of"):
        watchmen.parse_options("characters", ["a", "--rig", "flat", "--frame", "sideways"], env)
    assert env == {}
    with pytest.raises(watchmen.OptionError, match="--rig takes one of"):
        watchmen.parse_options("characters", ["a", "--rig"], env)  # value missing


def test_no_face_idle_alone_leaves_the_face_rule(monkeypatch):
    """1.4.0 set WATCHMEN_FACE_RULE=engine when --no-face-idle came without
    --face-rule, overriding a WATCHMEN_FACE_RULE=legacy of the environment."""
    env = {"WATCHMEN_FACE_RULE": "legacy"}
    watchmen.parse_options("characters", ["a", "b", "--no-face-idle"], env)
    assert env == {"WATCHMEN_FACE_RULE": "legacy", "WATCHMEN_FACE_IDLE": "0"}


def test_the_last_of_a_repeated_option_wins():
    env = {}
    watchmen.parse_options("char", ["--frame", "true", "f", "--frame", "mirrored"], env)
    assert env == {"WATCHMEN_FRAME": "mirrored"}


# ---------------------------------------------------------------------------
# n9: fragment exit codes
# ---------------------------------------------------------------------------


def test_fragment_exit_code_3_for_a_parse_that_stops_early(tmp_path, capsys):
    from test_p2_fragment import B, H

    b = B("<")
    p = b.type_record(0x10, "Root(Node)") + b.instance(0x10, [("name", "Root")])
    p += b.u(H("m_smainbehavior"), 5000) + b"Enemy\0\0\0"  # a string past the end
    bad = tmp_path / "x.fragment"
    bad.write_bytes(b.fragment(p))
    assert watchmen.main(["w", "fragment", str(bad), str(tmp_path / "x.json")]) == 3
    io_ = capsys.readouterr()
    assert "(lossless: False )" in io_.out and "not lossless" in io_.err
    good = tmp_path / "g.fragment"
    good.write_bytes(
        b.fragment(b.type_record(0x10, "Root(Node)") + b.instance(0x10, [("name", "R")]))
    )
    assert watchmen.main(["w", "fragment", str(good), str(tmp_path / "g.json")]) == 0
    other = tmp_path / "x.bin"
    other.write_bytes(b"\x00" * 8)
    assert watchmen.main(["w", "fragment", str(other)]) == 2
    assert "Exit codes" in watchmen.__doc__ and "3 `fragment` wrote a JSON" in watchmen.__doc__


# ---------------------------------------------------------------------------
# m10: one default archive
# ---------------------------------------------------------------------------


def test_charlibs_reads_the_same_default_archive_as_characters(tmp_path, monkeypatch):
    import extract_out
    import watchmenlib as wl
    import char_lib

    seen = []
    monkeypatch.chdir(tmp_path)
    (tmp_path / "01_game.naz").write_bytes(b"")
    monkeypatch.setattr(extract_out, "require", lambda d: None)
    monkeypatch.setattr(
        wl, "ensure_binds", lambda naz, out, extract_dir=None: seen.append(naz) or {}
    )
    monkeypatch.setattr(char_lib, "build_all", lambda *a: None)
    assert watchmen.main(["w", "charlibs", "EX", "OUT"]) == 0
    os.remove("01_game.naz")
    assert watchmen.main(["w", "charlibs", "EX", "OUT"]) == 0
    assert watchmen.main(["w", "charlibs", "EX", "OUT", "mine.naz"]) == 0
    assert seen == ["01_game.naz", "game.naz", "mine.naz"]


def test_library_defaults_use_default_naz(tmp_path, monkeypatch):
    import inspect

    import bake_v4
    import characters_export as ce
    import jiggle_d6
    import watchmenlib as wl
    import wutil

    assert bake_v4.default_naz is wutil.default_naz
    for fn in (
        wl.ensure_binds,
        wl.grab_blocks,
        wl.iter_blocks,
        wl.block_order,
        ce.ensure_bind,
        ce.ensure_all_binds,
        ce.export,
        jiggle_d6.joint_frames,
        jiggle_d6.apply_jiggle,
    ):
        assert inspect.signature(fn).parameters["naz"].default is None, fn.__name__
    seen = []
    monkeypatch.setattr(
        wl._efa, "iter_blocks", lambda naz, streams=True: seen.append(naz) or iter(())
    )
    monkeypatch.chdir(tmp_path)
    list(wl.iter_blocks())
    (tmp_path / "01_game.naz").write_bytes(b"")
    list(wl.iter_blocks())
    assert seen == ["game.naz", "01_game.naz"]
    src = (REPO / "watchmen.py").read_text(encoding="utf-8")
    assert '"game.naz"' not in src.split('"""', 2)[2]  # no literal default in the code


# ---------------------------------------------------------------------------
# m11: WATCHMEN_DEBUG
# ---------------------------------------------------------------------------


def _cli(monkeypatch, capsys, exc):
    def boom(argv):
        raise exc

    monkeypatch.setattr(watchmen, "main", boom)
    with pytest.raises(SystemExit) as ei:
        watchmen.cli()
    return ei.value.code, capsys.readouterr().err


@pytest.mark.parametrize(
    "value, traceback", [(None, False), ("", False), ("0", False), ("1", True), ("yes", True)]
)
def test_watchmen_debug(monkeypatch, capsys, value, traceback):
    if value is None:
        monkeypatch.delenv("WATCHMEN_DEBUG", raising=False)
    else:
        monkeypatch.setenv("WATCHMEN_DEBUG", value)
    code, err = _cli(monkeypatch, capsys, OSError(28, "No space left on device"))
    assert code == 2
    assert err.rstrip().splitlines()[-1] == "error: [Errno 28] No space left on device"
    assert ("Traceback (most recent call last)" in err) == traceback
    if traceback:
        assert "in boom" in err  # where it happened


def test_debug_enabled():
    assert not watchmen.debug_enabled({})
    assert not watchmen.debug_enabled({"WATCHMEN_DEBUG": " 0 "})
    assert watchmen.debug_enabled({"WATCHMEN_DEBUG": "2"})


def test_interrupt_and_other_errors(monkeypatch, capsys):
    assert _cli(monkeypatch, capsys, KeyboardInterrupt())[0] == 130
    monkeypatch.setattr(watchmen, "main", lambda argv: 0)
    with pytest.raises(SystemExit) as ei:
        watchmen.cli()
    assert ei.value.code == 0


# ---------------------------------------------------------------------------
# m12: one version
# ---------------------------------------------------------------------------


def _pyproject_version():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def test_the_versions_agree():
    import wlib

    head = re.search(r"^## (\S+) ", (REPO / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert _pyproject_version() == wlib.__version__ == watchmen.VERSION == head.group(1)


def test_version_falls_back_to_the_text_of_wlib_init(monkeypatch):
    import wlib

    monkeypatch.setitem(sys.modules, "wlib", None)  # `from wlib import ...` fails
    assert watchmen._version() == wlib.__version__


def test_version_command():
    r = subprocess.run(
        [sys.executable, "watchmen.py", "--version"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=60,
        stdin=subprocess.DEVNULL,
    )
    assert (
        r.returncode == 0 and r.stdout.strip() == "watchmen-kapow-toolkit %s" % _pyproject_version()
    )


# ---------------------------------------------------------------------------
# m16: packaging
# ---------------------------------------------------------------------------


def test_pyproject_classifiers_scripts_and_data():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    req = re.search(r'requires-python = ">=3\.(\d+)"', text).group(1)
    assert req == "13"  # 1.5.0: Python 3.13+, with the dependency minimums for it
    assert '"numpy>=2.1"' in text and '"Pillow>=11"' in text
    for minor in range(int(req), 15):
        assert '"Programming Language :: Python :: 3.%d"' % minor in text
    assert re.findall(r'"Programming Language :: Python :: 3\.(\d+)"', text) == ["13", "14"]
    assert '"Programming Language :: Python :: 3 :: Only"' in text
    assert 'watchmen = "watchmen:cli"' in text and 'watchmen-kapow = "watchmen:cli"' in text
    data = re.search(r"wlib = \[([^\]]*)\]", text).group(1)
    pats = [p.strip().strip('"') for p in data.split(",")]
    wlib = REPO / "wlib"
    for pat in pats:  # every pattern matches a file that ships
        assert list(wlib.glob(pat)), pat
    shipped = {p.suffix for p in wlib.iterdir() if p.is_file() and p.suffix != ".py"}
    assert shipped <= {pat[1:] for pat in pats}


# ---------------------------------------------------------------------------
# extract / all: OUT as -o / --out, the spelling `extract -h` shows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args, want",
    [
        (["N", "O", "--glb"], ["N", "O", "--glb"]),
        (["N", "-o", "O", "--glb"], ["N", "O", "--glb"]),
        (["N", "--glb", "--out", "O", "--limit", "5"], ["N", "O", "--glb", "--limit", "5"]),
        (["-o", "O", "N"], ["N", "O"]),
        (["N", "--out=O"], ["N", "O"]),
    ],
)
def test_out_option_becomes_the_second_argument(args, want):
    assert watchmen.move_out_option(args) == want


@pytest.mark.parametrize(
    "args, msg",
    [
        (["N", "O", "-o", "P"], "given twice (O and P)"),
        (["N", "-o", "O", "--out", "P"], "given twice"),
        (["N", "-o"], "-o needs the output folder"),
        (["N", "--out", "--glb"], "--out needs the output folder"),
    ],
)
def test_out_option_errors(args, msg, capsys):
    with pytest.raises(watchmen.OptionError) as e:
        watchmen.move_out_option(args)
    assert msg in str(e.value)
    assert watchmen.main(["w", "extract"] + args) == 2
    out = capsys.readouterr().out
    assert msg in out and "usage: watchmen.py extract NAZ OUT" in out


def test_extract_runs_with_out_option(tmp_path, monkeypatch):
    seen = []
    wl = watchmen._wl()
    monkeypatch.setattr(
        wl, "extract_all", lambda naz, out, *extra: seen.append((naz, out, extra)) or 0
    )
    assert watchmen.main(["w", "extract", "N", "-o", str(tmp_path), "--glb", "--limit", "3"]) == 0
    assert seen == [("N", str(tmp_path), ("--glb", "--limit", "3"))]


def test_extract_help_names_out_as_the_second_argument(capsys):
    with pytest.raises(SystemExit):
        watchmen.main(["w", "extract", "-h"])
    out = capsys.readouterr().out
    assert out.startswith("usage: watchmen.py extract NAZ OUT")
    assert "OUT is the second argument (or -o / --out OUT)" in out and "--vgmstream-cli" in out
