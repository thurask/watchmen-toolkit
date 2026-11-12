"""Where the flat wlib modules come from, and the extractor's entry point.

`wlib\\` is appended to sys.path, so an installed top-level module with the same
name as a wlib module would be imported in its place; the first test names
that case.  The extractor lives in the modules below and is run as
`python wlib/extract_driver.py`; the old single-file name no longer imports.
"""

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

WLIB = Path(__file__).resolve().parent.parent / "wlib"

#: the flat modules the extractor is made of
EXTRACTOR_MODULES = {
    "extract_log",
    "byte_reader",
    "extract_paths",
    "naz_archive",
    "kapow_block",
    "texture_header",
    "texture_sheet",
    "texture_decode",
    "texture_carve",
    "material_refs",
    "model_header",
    "model_mesh",
    "obj_mtl",
    "model_export",
    "sound_header",
    "audio_decode",
    "extract_driver",
}


def _wlib_modules():
    return sorted(p.stem for p in WLIB.glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("name", _wlib_modules())
def test_every_wlib_module_is_imported_from_wlib(name):
    mod = importlib.import_module(name)
    assert Path(mod.__file__).resolve().parent == WLIB, (
        "%s is imported from %s, not from wlib: an installed module of that name "
        "shadows it" % (name, mod.__file__)
    )


def test_the_extractor_modules_are_in_wlib():
    assert EXTRACTOR_MODULES <= set(_wlib_modules())


def test_the_old_single_file_module_is_gone():
    assert "watchmen_extract" not in _wlib_modules()
    sys.modules.pop("watchmen_extract", None)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("watchmen_extract")


def test_the_script_entry_point_runs():
    r = subprocess.run(
        [sys.executable, str(WLIB / "extract_driver.py"), "--help"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "Extract Watchmen Part 2" in r.stdout and "--no-textures" in r.stdout
