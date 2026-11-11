"""characters_export.export: the model index is walked once per run, and a skeleton
without jiggle bones gets no jiggle memo (its palettes equal the raw bakes)."""

import characters_export as ce
import jiggle_d6
import numpy as np


def test_model_index_is_walked_once_per_export(export_env, monkeypatch, tmp_path):
    ex, out, _calls = export_env
    walks = []
    scan = ce._scan_model_index

    def counted(e):
        walks.append(e)
        return scan(e)

    monkeypatch.setattr(ce, "_scan_model_index", counted)
    real_discover = ce.discover
    seen = []

    def discover(e):
        seen.append(ce._model_index(e) is ce._model_index(e))  # one shared index
        return real_discover(e)

    monkeypatch.setattr(ce, "discover", discover)
    ce.export(str(ex), str(out), naz="none.naz", only="Heavy")
    assert seen == [True] and len(walks) == 1
    assert ce._MODEL_INDEX_RUN is None  # released after the run
    # outside a run every call walks the tree (nothing stale is served)
    ce._model_index(str(ex))
    ce._model_index(str(ex))
    assert len(walks) == 3


def test_model_index_cache_is_released_when_the_export_fails(export_env, monkeypatch):
    ex, out, _calls = export_env

    def boom(e, o):
        raise RuntimeError("stop")

    monkeypatch.setattr(ce, "animation_meta", boom)
    try:
        ce.export(str(ex), str(out), naz="none.naz", only="Heavy")
    except RuntimeError:
        pass
    assert ce._MODEL_INDEX_RUN is None


def test_jiggle_bones_lists_the_bones_a_model_moves():
    names = np.array(["Bip01", "BreastL", "BreastR", "JiggleBelly", "Hair_01", "Head"])
    assert jiggle_d6.jiggle_bones(names) == ["BreastL", "BreastR", "JiggleBelly", "Hair_01"]
    assert jiggle_d6.jiggle_bones(np.array(["Bip01", "Spine", "Head"])) == []


def test_no_memo_for_a_skeleton_without_jiggle_bones(export_env, monkeypatch, capsys):
    """The palettes are still passed through apply_jiggle (the GLB gets exactly what it
    got with a memo), but no `<key>_j_*` folder is written and nothing is logged."""
    ex, out, calls = export_env
    monkeypatch.setattr(jiggle_d6, "jiggle_bones", lambda names: [])
    glb = out / "Heavy" / "Heavy.glb"
    ce.export(str(ex), str(out), naz="none.naz", only="Heavy", jiggle_model="solver")
    assert glb.exists()
    assert not [p for p in (out / "_bake").iterdir() if "_j_" in p.name]
    assert len(calls["jiggle_kw"]) == 1
    assert "jiggle_d6:" not in capsys.readouterr().out
    first = glb.read_bytes()
    glb.unlink()
    ce.export(str(ex), str(out), naz="none.naz", only="Heavy", jiggle_model="solver")
    assert len(calls["jiggle_kw"]) == 2  # no memo to read back: solved again
    assert glb.read_bytes() == first
    assert not [p for p in (out / "_bake").iterdir() if "_j_" in p.name]
