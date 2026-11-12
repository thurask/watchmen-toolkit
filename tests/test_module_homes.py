"""Where the flat wlib modules come from, and the forwarding of the names that
moved out of watchmen_extract.

`wlib\\` is appended to sys.path, so an installed top-level module with the same
name as a wlib module would be imported in its place; the first test names
that case.  The rest hold the forwarding of watchmen_extract's `_HOMES`: a name
read, patched, deleted or mutated through watchmen_extract is the one in its
home module, and the script entry point still runs.
"""

import importlib
import subprocess
import sys
import types
from pathlib import Path

import pytest

import extract_log
import watchmen_extract as we

WLIB = Path(__file__).resolve().parent.parent / "wlib"

#: modules split out of watchmen_extract, each with what it holds
HOMES = {
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


def test_the_split_modules_are_listed():
    assert {home for home, _ in we._HOMES.values()} == HOMES
    assert HOMES <= set(_wlib_modules())


@pytest.mark.parametrize("name", sorted(we._HOMES))
def test_a_moved_name_is_read_from_its_home(name):
    home, there = we._HOMES[name]
    assert name not in vars(we), "a moved name must not stay in watchmen_extract"
    assert getattr(we, name) is getattr(importlib.import_module(home), there)


@pytest.mark.parametrize("name", sorted(we._HOMES))
def test_a_patch_through_watchmen_extract_lands_in_the_home_and_is_undone(name):
    home, there = we._HOMES[name]
    mod = importlib.import_module(home)
    before = getattr(mod, there)
    marker = object()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(we, name, marker)
        assert getattr(mod, there) is marker and getattr(we, name) is marker
    assert getattr(mod, there) is before
    assert name not in vars(we)


@pytest.mark.parametrize("name", sorted(we._HOMES))
def test_a_delete_through_watchmen_extract_is_undone(name):
    home, there = we._HOMES[name]
    mod = importlib.import_module(home)
    before = getattr(mod, there)
    with pytest.MonkeyPatch.context() as mp:
        mp.delattr(we, name)
        assert not hasattr(mod, there) and not hasattr(we, name)
    assert getattr(mod, there) is before


def test_a_patch_on_the_old_spelling_reaches_callers_in_other_modules(tmp_path):
    """texture_sheet.sheet_warning (old spelling `_sheet_warning`) calls
    extract_log.warn; a patch on the old private spelling `_run_warning`
    reaches it."""
    got = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(we, "_run_warning", got.append)
        we._sheet_warning(tmp_path / "Tex", "not written", OSError("disk full"))
    assert got == ["      WARNING: texture Tex: not written (OSError: disk full)"]


def test_module_state_mutated_through_watchmen_extract_is_the_homes():
    """`we._RUN_LOG.append(...)` and a subscript write change the home's list,
    which extract_log.warn reads."""
    got = []
    we._RUN_LOG.append(got.append)
    try:
        assert extract_log._RUN_LOG[-1] == got.append
        we._RUN_LOG[-1] = got.append
        extract_log.warn("WARNING: one")
    finally:
        we._RUN_LOG.pop()
    assert got == ["WARNING: one"] and extract_log._RUN_LOG == []


def test_a_subscript_write_into_a_forwarded_dict_lands_in_the_home(monkeypatch):
    """The forwarding for a dict of module state (the shape of `_RIG`), on a
    stand-in module of the same type: `mod.<name>["key"] = v` changes the
    home's dict."""
    home = types.ModuleType("_test_home")
    home.STATE = {"on": False}
    monkeypatch.setitem(sys.modules, "_test_home", home)
    mod = types.ModuleType("_test_shim")
    mod.__class__ = we._forwarding_type({"_STATE": ("_test_home", "STATE")})
    mod._STATE["on"] = True
    assert home.STATE == {"on": True} and mod._STATE is home.STATE
    assert "_STATE" not in vars(mod)


@pytest.mark.parametrize("name", sorted(we._HOMES))
def test_a_moved_name_is_a_data_descriptor_of_the_module_type(name):
    """What makes monkeypatch restore the home's value: pytest 9.2 takes a
    module attribute's old value from the module namespace unless the module
    type serves the name through a data descriptor."""
    descr = vars(type(we))[name]
    assert hasattr(type(descr), "__set__") and hasattr(type(descr), "__delete__")


def test_a_name_neither_here_nor_forwarded_is_an_attribute_error():
    assert not hasattr(we, "_no_such_name")
    with pytest.raises(AttributeError, match="_no_such_name"):
        _ = we._no_such_name
    with pytest.raises(AttributeError):
        del we._no_such_name


def test_a_name_defined_here_is_set_here(monkeypatch):
    monkeypatch.setattr(we, "main", "patched")
    assert vars(we)["main"] == "patched"


def test_the_script_entry_point_runs():
    r = subprocess.run(
        [sys.executable, str(WLIB / "watchmen_extract.py"), "--help"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=120,
    )
    assert r.returncode == 0, r.stderr
    assert "Extract Watchmen Part 2" in r.stdout and "--no-textures" in r.stdout
