"""Archive-entry path sanitization (``watchmen_extract.safe``).

Entry names inside a .naz are attacker-controlled (rot-2 obfuscated, not
authenticated), so every one of them has to be clamped under the output
directory before anything is written.
"""

from pathlib import Path

import pytest

import watchmen_extract as we


def _under(base, p):
    """True iff `p` resolves strictly inside `base`."""
    base, p = Path(base).resolve(), Path(p).resolve()
    return base in p.parents


@pytest.mark.parametrize(
    "name,expected",
    [
        ("tex/skin.png", ("tex", "skin.png")),
        ("a/b/c/d.dds", ("a", "b", "c", "d.dds")),
        ("mixed\\windows\\sep.bin", ("mixed", "windows", "sep.bin")),
        ("./leading/dot.txt", ("leading", "dot.txt")),
        ("dots..in..name.txt", ("dots..in..name.txt",)),
    ],
)
def test_safe_keeps_ordinary_names(tmp_path, name, expected):
    """Ordinary entry names must survive verbatim.

    Sanitization that mangles legitimate names would silently rename half the
    extracted asset tree, so the filter has to be surgical: only the dangerous
    components go, and '..' embedded in a filename is not one of them.
    """
    out = we.safe(tmp_path, name)
    assert out == tmp_path.joinpath(*expected)
    assert _under(tmp_path, out)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.txt",
        "../../../../etc/passwd",
        "a/../../b.txt",
        "/absolute/rooted.txt",
        "//double/slash.txt",
        "\\\\server\\share\\evil.txt",
        "a/./../../b/../../c.txt",
        "..",
        "../",
        "sub/../../../out.bin",
    ],
)
def test_safe_never_escapes_base(tmp_path, name):
    """Traversal and absolute anchors must never resolve outside `base`.

    This is the security property of the whole extractor: one escaping entry
    means an archive can overwrite arbitrary files on the extracting machine.
    """
    base = tmp_path / "out"
    base.mkdir()
    out = we.safe(base, name)
    assert _under(base, out) or Path(out).resolve() == base.resolve()
    assert ".." not in Path(out).parts


@pytest.mark.parametrize(
    "name,expected",
    [
        ("C:/x", ("C_", "x")),
        ("D:evil.txt", ("D_evil.txt",)),
        (
            "C:\\Windows\\System32\\drivers\\etc\\hosts",
            ("C_", "Windows", "System32", "drivers", "etc", "hosts"),
        ),
        ("../C:/x", ("C_", "x")),
    ],
)
def test_safe_neutralizes_windows_drive_letters(tmp_path, name, expected):
    """':' must be neutralized, not merely stripped of '..'.

    pathlib treats 'C:/x' as a fresh anchor on Windows, so joining it onto the
    base would discard the base entirely -- a traversal escape that no amount
    of '..' filtering catches. Replacing ':' with '_' keeps the name readable
    while making it an ordinary path component everywhere.
    """
    out = we.safe(tmp_path, name)
    assert out == tmp_path.joinpath(*expected)
    assert ":" not in str(out.relative_to(tmp_path))
    assert _under(tmp_path, out)


@pytest.mark.parametrize("name", ["", "/", "//", ".", "./", "..", "../..", "\\"])
def test_safe_maps_degenerate_names_to_a_file(tmp_path, name):
    """A name that sanitizes to nothing must become a FILE, not `base` itself.

    Returning `base` would make the caller open the output directory for
    writing (IsADirectoryError at best, clobbering at worst). '_unnamed' keeps
    the result a writable leaf under the base.
    """
    out = we.safe(tmp_path, name)
    assert out == tmp_path / "_unnamed"
    assert out != tmp_path
    assert out.parent == tmp_path


def test_safe_result_is_writable_and_stays_put(tmp_path):
    """End-to-end: the sanitized path can actually be created under `base`."""
    base = tmp_path / "extract"
    base.mkdir()
    victim = tmp_path / "victim.txt"
    victim.write_text("original")

    for hostile in ("../victim.txt", "../../victim.txt", "C:/victim.txt", ""):
        out = we.safe(base, hostile)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"payload")

    assert victim.read_text() == "original"
    written = sorted(p.relative_to(base).as_posix() for p in base.rglob("*") if p.is_file())
    assert written == ["C_/victim.txt", "_unnamed", "victim.txt"]
