"""1.5.0: a clip track whose key count is neither 1 nor the clip's is resampled
by time (linear interpolation of its own keys), not by the floor of the key
index; the bake names such tracks in one WARNING line per clip."""

import numpy as np
import pytest

import bake_v4
import test_p6_anim as tpa
import test_s5_code_findings as ts5

ID = (0.0, 0.0, 0.0, 1.0)


def _qy(deg):
    h = np.radians(deg) / 2
    return (0.0, float(np.sin(h)), 0.0, float(np.cos(h)))


def _angle_deg(R):
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def _old_index_rule(x, n):
    """1.4.0: the key at the floor of the position (a step function)."""
    x = np.asarray(x, np.float64)
    return x[np.linspace(0, len(x) - 1, n).astype(int)]


def test_resample_keys_is_a_linear_ramp_not_a_step():
    x = np.array([[0.0, 10.0], [29.0, 39.0]])
    got = bake_v4.resample_keys(x, 30)
    assert np.allclose(got[:, 0], np.arange(30.0)) and np.allclose(got[:, 1], 10 + np.arange(30.0))
    old = _old_index_rule(x, 30)
    assert (old[:29, 0] == 0).all() and old[29, 0] == 29  # what 1.4.0 did
    # end keys are kept exactly; equal counts pass through untouched
    y = np.random.default_rng(1).normal(size=(7, 4))
    r = bake_v4.resample_keys(y, 19)
    assert np.array_equal(r[0], y[0]) and np.array_equal(r[-1], y[-1])
    assert np.allclose(r[3], y[1])  # 3 * 6/18 = key 1 exactly
    assert bake_v4.resample_keys(y, 7) is not None and np.array_equal(bake_v4.resample_keys(y, 7), y)


def _clip(arm_keys):
    """root: 30 keys (type 2), Arm: `arm_keys` rotation keys about y (type 1),
    0 to 58 degrees."""
    root = [((0.0, 0.0, 0.0), ID)] * 30
    arm = [_qy(58.0 * i / (arm_keys - 1)) for i in range(arm_keys)]
    return tpa._clip([("root", 2, root), ("Arm", 1, ((1.0, 0.0, 0.0), arm))], keys=30)


def _arm_angles(tmp_path, clip, capsys):
    bind = ts5._twist_bind(tmp_path)
    pal, _dur = bake_v4.bake("c", 1, bind=bind, bank={"c": clip}, twist_align=False)
    err = capsys.readouterr().err
    return np.array([_angle_deg(pal[f, 1, :, :3]) for f in range(len(pal))]), err


def test_a_two_key_track_in_a_thirty_key_clip_ramps(tmp_path, capsys):
    ang, err = _arm_angles(tmp_path, _clip(2), capsys)
    assert len(ang) == 30
    assert ang[0] == pytest.approx(0.0, abs=0.05) and ang[-1] == pytest.approx(58.0, abs=0.05)
    assert np.all(np.diff(ang) > 0)  # monotonic, no step
    assert ang[15] == pytest.approx(30.0, abs=1.0)  # nlerp of two keys 58 deg apart
    assert err.count("WARNING:") == 1
    assert "WARNING: clip c: 1 track(s) with a key count other than 1 or 30" in err
    assert "Arm" in err and "root" not in err.split("over the clip:")[1]


def test_the_1_4_0_rule_held_the_first_key(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bake_v4, "resample_keys", _old_index_rule)
    ang, _err = _arm_angles(tmp_path, _clip(2), capsys)
    assert np.allclose(ang[:29], 0.0, atol=0.05) and ang[29] == pytest.approx(58.0, abs=0.05)


def test_a_uniform_clip_never_resamples_and_bakes_as_before(tmp_path, capsys, monkeypatch):
    ang, err = _arm_angles(tmp_path, _clip(30), capsys)
    assert "WARNING" not in err

    def boom(*a):
        raise AssertionError("resample_keys called for a uniform clip")

    monkeypatch.setattr(bake_v4, "resample_keys", boom)
    ang2, _ = _arm_angles(tmp_path, _clip(30), capsys)
    assert np.array_equal(ang, ang2)  # the uniform path is the 1.4.0 formula, bit for bit
    assert np.allclose(ang, 58.0 * np.arange(30) / 29, atol=0.05)
