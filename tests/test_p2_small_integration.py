"""Pass 2, small defects that live in characters_export / anim_meta (applied by the
integrator on top of work package F).

    V11   a table whose combat / fx step failed carries `build_failed` with the
          reason, and a resumed character export reuses it instead of rebuilding
          it on every run
    A41   the jiggle memo of a solver bake is looked up under a name that carries
          the clip's loop flag (jiggle_d6.cache_file)

Synthetic fixtures only (those of the feature tests are reused)."""

import inspect
import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import characters_export as ce
import combat_meta as cm
import face_rule
import fx_meta as fx

import test_combat_meta
import test_feature_seams as fs

combat_extract = test_combat_meta.extract


def _boom(*a, **k):
    raise KeyError("m_broken")


@pytest.mark.parametrize("block", ["combat", "fx"])
def test_a_failed_block_leaves_a_marker_with_the_reason(combat_extract, monkeypatch, block):
    if block == "combat":
        monkeypatch.setattr(cm, "build", _boom)
        fmt = cm.COMBAT_FORMAT
    else:
        monkeypatch.setattr(fx, "_attach", _boom)
        fmt = fx.FORMAT
    said = []
    m = am.build(str(combat_extract), log=said.append)
    assert block + "_format" not in m and block not in m
    assert m[am.BUILD_FAILED_KEY] == {
        block: {"format": fmt, "status": "attempted, failed", "reason": "KeyError: 'm_broken'"}
    }
    other = "fx" if block == "combat" else "combat"
    assert m[other + "_format"]  # the other block is there
    assert any("skipped (KeyError: 'm_broken')" in x for x in said)  # and the reason is printed
    assert ce.anim_meta_failures(m) == ["%s: attempted, failed: KeyError: 'm_broken'" % block]
    json.dumps(m)


def test_a_table_built_without_failures_has_no_marker(combat_extract):
    m = am.build(str(combat_extract))
    assert am.BUILD_FAILED_KEY not in m and ce.anim_meta_failures(m) == []


@pytest.mark.usefixtures("engine_frame")
@pytest.mark.parametrize("block,fmt", [("combat", cm.COMBAT_FORMAT), ("fx", fx.FORMAT)])
def test_a_table_with_a_failed_block_is_reused_and_says_why(
    tmp_path, monkeypatch, capsys, block, fmt
):
    """Before: the table had no `<block>_format`, so every `characters` run rebuilt it
    (and failed the same way again)."""
    table = fs._current()
    del table[block + "_format"]
    table[am.BUILD_FAILED_KEY] = {
        block: {"format": fmt, "status": "attempted, failed", "reason": "KeyError: 'x'"}
    }
    assert fs._resume(tmp_path, monkeypatch, table)[:2] == ("cached", 0)
    out = capsys.readouterr().out
    assert "without the %s block (attempted, failed: KeyError: 'x')" % block in out
    assert "delete the file to try again" in out


@pytest.mark.usefixtures("engine_frame")
def test_a_failure_recorded_for_another_block_format_is_retried(tmp_path, monkeypatch):
    table = fs._current()
    del table["combat_format"]
    table[am.BUILD_FAILED_KEY] = {
        "combat": {"format": "watchmen-combat-meta/0", "status": "attempted, failed", "reason": "x"}
    }
    assert fs._resume(tmp_path, monkeypatch, table)[:2] == ("new", 1)
    monkeypatch.setattr(face_rule, "find_face_fragments", lambda ex: {})
    assert ce.anim_meta_is_current(dict(table, build_failed="junk"), "x") is False


def test_the_jiggle_memo_is_looked_up_with_the_loop_flag():
    src = inspect.getsource(ce.export)
    assert src.count("cache_file(nm, jiggle_model, clip_loops(meta, nm))") == 2  # read and write
    assert 'os.path.join(jdir, nm + ".npz")' not in src
