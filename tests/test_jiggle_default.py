"""The jiggle default is the 'solver' model; how it bakes looping and non-looping clips.

* `solver` is what `watchmen characters` / `apply_jiggle` use when no model is named;
  `pinned` (the default of 1.2.0 - 1.3.0) and `pivot` stay selectable and unchanged.
* A clip the game loops (anim_meta `loop`) is baked as a closed lap of its settled motion:
  the last frame hands over to the first.
* A clip that does not loop gets a short lead-in at its frame-0 velocity.
* Clips of fewer than four frames are returned as they are.

Everything here is synthetic: no game files.
"""

import importlib.util
import math
import os

import numpy as np
import pytest

import characters_export as ce
import jiggle_d6
import jiggle_pass

LEVER = np.array([0.0, 0.05, 0.1225])
PARENT_ORIGIN = np.array([0.0, 1.0, 0.0])
PROPS = dict(jiggle_d6._FILE_DEFAULTS)


def _bind(tmp_path, name="BreastL"):
    tb = np.array([[0.0, 0.0, 0.0], PARENT_ORIGIN, PARENT_ORIGIN + LEVER])
    path = tmp_path / ("bind_%s.npz" % name)
    np.savez(
        path,
        Rb=np.tile(np.eye(3), (3, 1, 1)),
        tb=tb,
        tloc=np.array([[0.0, 0.0, 0.0], PARENT_ORIGIN, LEVER]),
        names=np.array(["Root", "Spine2", name]),
        par=np.array([-1, 0, 1]),
    )
    return str(path)


def _palettes(rotvecs, shift=None):
    """Parent (and the rigid jiggle bone) rotated by rotvecs[f] about PARENT_ORIGIN."""
    F = len(rotvecs)
    P = np.zeros((F, 3, 3, 4))
    P[:, 0, :, :3] = np.eye(3)
    for f in range(F):
        R = jiggle_d6._rotv2m(np.asarray(rotvecs[f], float))
        t = PARENT_ORIGIN - R @ PARENT_ORIGIN + (shift[f] if shift is not None else 0.0)
        for k in (1, 2):
            P[f, k, :, :3] = R
            P[f, k, :, 3] = t
    return P


def _rotvec(R):
    a = float(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)))
    if a < 1e-12:
        return np.zeros(3)
    return a * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(a))


def _dev(out, f):
    """Deviation of the jiggle bone from its parent at frame f, parent frame, degrees."""
    Rp = out[f, 1, :, :3].astype(np.float64)
    Rk = out[f, 2, :, :3].astype(np.float64)
    return np.degrees(_rotvec(Rp.T @ Rk))


def _solver(P, fps, bind, **kw):
    kw.setdefault("props", PROPS)
    return jiggle_d6.apply_jiggle(P, fps, bind, model="solver", **kw)


def _cycle(n, fps=30.0, closed=True, amp=0.25):
    """One period of a two-axis swing: n unique frames, plus the repeat of frame 0."""
    t = np.arange(n + (1 if closed else 0)) / float(n)
    rv = np.zeros((len(t), 3))
    rv[:, 2] = amp * np.sin(2 * np.pi * t)
    rv[:, 1] = 0.5 * amp * np.cos(4 * np.pi * t)
    return _palettes(rv)


def _old_inputs():
    t = np.arange(150) / 30.0
    rv = np.stack([0.1 * np.sin(5 * t), 0.3 * np.sin(9 * t + 1), 0.4 * np.sin(13 * t)], 1)
    shift = np.stack([0.05 * np.sin(7 * t), 0.02 * np.sin(11 * t), 0.0 * t], 1)
    return _palettes(rv, shift)


# ---------------------------------------------------------------------------
# the default
# ---------------------------------------------------------------------------


def test_solver_is_the_default_everywhere(tmp_path):
    import watchmen

    bind = _bind(tmp_path)
    P = _old_inputs()
    assert jiggle_d6.DEFAULT_MODEL == "solver"
    assert jiggle_d6.resolve_model() == ("solver", "file")
    assert watchmen.JIGGLE_MODELS[0] == "solver"
    assert set(watchmen.JIGGLE_MODELS) == set(jiggle_d6.MODELS)
    want = _solver(P, 30.0, bind)
    assert np.array_equal(jiggle_d6.apply_jiggle(P, 30.0, bind, props=PROPS), want)
    assert ce.jiggle_cache_dir("/o/_bake/female") == ce.jiggle_cache_dir(
        "/o/_bake/female", "solver"
    )
    for m in ("pinned", "pivot"):
        assert ce.jiggle_cache_dir("/o/_bake/female") != ce.jiggle_cache_dir("/o/_bake/female", m)
        other = jiggle_d6.apply_jiggle(P, 30.0, bind, props=PROPS, model=m)
        assert not np.allclose(other, want, atol=1e-4)


def test_cli_default_and_explicit_models(monkeypatch, capsys):
    """`characters` without the flag passes None (-> DEFAULT_MODEL); `--jiggle-model pinned`
    is how the 1.3.0 jiggle is asked for."""
    import watchmen

    calls = []

    class FakeExport:
        @staticmethod
        def export(exout, outdir, naz, jiggle_model=None):
            calls.append(jiggle_model)
            return 0

    monkeypatch.setitem(__import__("sys").modules, "characters_export", FakeExport)
    assert watchmen.main(["w", "characters", "EX", "OUT"]) == 0
    assert watchmen.main(["w", "characters", "EX", "OUT", "--jiggle-model", "pinned"]) == 0
    assert watchmen.main(["w", "characters", "EX", "OUT", "--jiggle-model", "pivot"]) == 0
    assert calls == [None, "pinned", "pivot"]
    assert jiggle_d6.resolve_model(calls[0])[0] == "solver"
    capsys.readouterr()
    assert watchmen.main(["w", "characters", "-h"]) == 0
    assert "--jiggle-model solver|pivot|pinned" in capsys.readouterr().out
    assert "`solver` model (default" in watchmen.__doc__


# ---------------------------------------------------------------------------
# pinned / pivot are unchanged: they are the models of 1.3.0
# ---------------------------------------------------------------------------


def _load_140():
    root = os.environ.get("WATCHMEN_TK140") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tk140"
    )
    src = os.path.join(root, "wlib", "jiggle_d6.py")
    if not os.path.exists(src):
        pytest.skip("no pre-switch development tree to compare against (WATCHMEN_TK140)")
    spec = importlib.util.spec_from_file_location("jiggle_d6_140", src)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    assert old.DEFAULT_MODEL == "pinned"
    return old


def test_model_pinned_reproduces_the_previous_default_bit_for_bit(tmp_path):
    """Against a development tree from before the default moved to `solver` -- one in
    which `pinned` is the default and `solver` already exists (WATCHMEN_TK140 or
    ../tk140 next to this checkout; never released, so the test is skipped elsewhere):
    what `--jiggle-model pinned` bakes now is byte for byte what that tree baked by
    default, with or without the loop flag the exporter now passes; pivot is unchanged
    as well.  That default is in turn the 1.3.0 one: test_jiggle_solver compares `pinned`
    and `pivot` with a 1.3.0 tree."""
    old = _load_140()
    bind = _bind(tmp_path)
    P = _old_inputs()
    loop_clip = _cycle(40)
    for fps in (30.0, 60.0, 20.0):
        ref = old.apply_jiggle(P, fps, bind, props=PROPS)  # the old default (pinned)
        for kw in (dict(), dict(loop=True), dict(loop=False)):
            new = jiggle_d6.apply_jiggle(P, fps, bind, props=PROPS, model="pinned", **kw)
            assert new.dtype == ref.dtype and new.tobytes() == ref.tobytes(), (fps, kw)
        via_pass = jiggle_pass.apply_jiggle(P, fps, bind, model="pinned", loop=True)
        assert via_pass.tobytes() == old.apply_jiggle(P, fps, bind).tobytes()
        ref = old.apply_jiggle(loop_clip, fps, bind, props=PROPS)
        new = jiggle_d6.apply_jiggle(loop_clip, fps, bind, props=PROPS, model="pinned", loop=True)
        assert new.tobytes() == ref.tobytes()
        for kw in (dict(), dict(mode="engine"), dict(latency=0.0), dict(gain=1.5)):
            ref = old.apply_jiggle(P, fps, bind, props=PROPS, model="pivot", **kw)
            new = jiggle_d6.apply_jiggle(P, fps, bind, props=PROPS, model="pivot", loop=True, **kw)
            assert new.tobytes() == ref.tobytes(), (fps, kw)
    for m in ("pinned", "pivot"):
        assert jiggle_d6.cache_signature(m) == old.cache_signature(m)
    assert jiggle_d6.cache_signature("solver") != old.cache_signature("solver")


# Bone-2 rotation rows of apply_jiggle(_old_inputs(), 30 fps) as 1.3.0 baked them by default
# (float32 output of the pinned model; frames 0, 37, 149).  Frozen so that the check also
# runs where no older tree is at hand.
_PINNED_140 = {
    0: [
        0.9683055281639099,
        0.0,
        0.24976861476898193,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        -0.24976861476898193,
        0.0,
        0.9683055281639099,
        0.0,
    ],
    37: [
        0.9883456230163574,
        0.05376854166388512,
        -0.14241445064544678,
        -0.01338574942201376,
        -0.05205407366156578,
        0.9985201954841614,
        0.01573967933654785,
        0.0185166597366333,
        0.14305001497268677,
        -0.008142990060150623,
        0.9896819591522217,
        0.008546564728021622,
    ],
    149: [
        0.8517801761627197,
        -0.4498453438282013,
        0.26853254437446594,
        0.44410109519958496,
        0.44315460324287415,
        0.8920481204986572,
        0.08867984265089035,
        0.09032142907381058,
        -0.2794361710548401,
        0.04346570000052452,
        0.9591799378395081,
        -0.04452274367213249,
    ],
}


def test_model_pinned_matches_frozen_1_3_0_values(tmp_path):
    bind = _bind(tmp_path)
    out = jiggle_d6.apply_jiggle(_old_inputs(), 30.0, bind, props=PROPS, model="pinned")
    for f, row in _PINNED_140.items():
        assert np.allclose(out[f, 2].ravel(), row, rtol=0, atol=1e-6), f
    # 1.3.0 cache tags: `<key>_j_pinned-engine-...` directories stay valid
    assert jiggle_d6.cache_signature("pinned") == "pinned-engine-b1de22ed"
    assert jiggle_d6.cache_signature("pivot") == "pivot-capture-b1de22ed"
    assert jiggle_d6.MODEL_REVISION["pinned"] == 1 and jiggle_d6.MODEL_REVISION["pivot"] == 1


# ---------------------------------------------------------------------------
# looping clips
# ---------------------------------------------------------------------------


def test_closed_loop_is_seamless_and_starts_inside_its_cycle(tmp_path):
    """Last frame == first frame in the source: the baked lap closes exactly, where the
    non-looping bake of the same clip jumps at the wrap."""
    bind = _bind(tmp_path)
    n, fps = 40, 30.0
    P = _cycle(n, fps)
    st = {}
    loop = _solver(P, fps, bind, loop=True, stats=st)
    once = _solver(P, fps, bind)
    rest = _solver(P, fps, bind, lead_in=0.0)
    s = st["BreastL"]
    assert s["loop"] is True and s["frames"] == n and s["steps"] == 80
    assert 2 <= s["laps"] <= jiggle_d6.SOLVER_LOOP_MAX_LAPS
    assert s["seam_deg"] < 0.5
    assert np.allclose(loop[n], loop[0], atol=1e-12)  # frame F-1 is frame 0 again
    # degrees: the wrap jump of the non-looping bake, with the lead-in and from rest
    assert np.linalg.norm(_dev(once, n) - _dev(once, 0)) > 0.1
    assert np.linalg.norm(_dev(rest, n) - _dev(rest, 0)) > 1.0
    assert np.linalg.norm(_dev(loop, 0)) > 0.5  # inside the cycle, not at rest
    # continuity through the wrap: the step n-1 -> 0 is no larger than the steps around it
    d = np.array([_dev(loop, f) for f in range(n)])
    steps = np.linalg.norm(np.diff(np.concatenate([d, d[:2]]), axis=0), axis=1)
    assert steps[n - 1] < 1.5 * max(steps[n - 2], steps[n])
    assert np.abs(np.diff(steps[n - 3 :])).max() < 0.5 * steps.max()
    # the parent is untouched and the result is deterministic
    assert np.allclose(loop[:, :2], P[:, :2], atol=1e-6)
    assert np.array_equal(loop, _solver(P, fps, bind, loop=True))


def test_loop_matches_a_long_take_of_the_same_cycle(tmp_path):
    """The baked lap is a late lap of a long non-looping take of the same cycle, up to the
    lap-to-lap drift such a take keeps (the motion does not become exactly periodic) and
    the seam correction that closes the lap."""
    bind = _bind(tmp_path)
    n, fps = 40, 30.0
    P = _cycle(n, fps)
    loop = _solver(P, fps, bind, loop=True)
    many = np.concatenate([P[:n]] * 12 + [P[:1]])
    long_take = _solver(many, fps, bind)
    for f in (0, 7, 20, 39):
        assert np.linalg.norm(_dev(loop, f)) > 0.5
        assert np.allclose(_dev(loop, f), _dev(long_take, 10 * n + f), atol=0.15), f


def test_open_loop_last_frame_is_one_step_short_of_frame_0(tmp_path):
    bind = _bind(tmp_path)
    n, fps = 40, 30.0
    P = _cycle(n, fps, closed=False)
    assert len(P) == n
    st = {}
    loop = _solver(P, fps, bind, loop=True, stats=st)
    assert st["BreastL"]["frames"] == n  # every frame is part of the lap
    closed = _solver(_cycle(n, fps), fps, bind, loop=True)
    assert np.allclose(loop, closed[:n], atol=1e-9)
    d = np.array([_dev(loop, f) for f in range(n)])
    steps = np.linalg.norm(np.diff(np.concatenate([d, d[:1]]), axis=0), axis=1)
    assert steps[-1] < 1.5 * max(steps[-2], steps[0])


def test_loop_frames_detects_the_repeated_last_frame():
    def frames(P):
        c = np.einsum("fab,b->fa", P[:, 1, :, :3], PARENT_ORIGIN) + P[:, 1, :, 3]
        q = [jiggle_d6._m2q(P[f, 1, :, :3].tolist()) for f in range(len(P))]
        return jiggle_d6._loop_frames(c, q)

    assert frames(_cycle(40)) == 40  # 41 frames, the last repeats frame 0
    assert frames(_cycle(40, closed=False)) == 40
    static = _palettes(np.zeros((12, 3)))
    assert frames(static) == 11


def test_loop_that_does_not_settle_is_still_closed(tmp_path, monkeypatch):
    """With the automatic stop cut short the lap has not converged; the seam correction
    still closes it, and reports how much it had to spread."""
    bind = _bind(tmp_path)
    n, fps = 40, 30.0
    P = _cycle(n, fps, amp=0.5)
    st1, st2 = {}, {}
    one = _solver(P, fps, bind, warmup=1, stats=st1)
    auto = _solver(P, fps, bind, loop=True, stats=st2)
    assert st1["BreastL"]["laps"] == 2 and st1["BreastL"]["seam_deg"] > st2["BreastL"]["seam_deg"]
    assert np.allclose(one[n], one[0], atol=1e-12)
    assert np.allclose(auto[n], auto[0], atol=1e-12)
    assert st2["BreastL"]["laps"] > 2 and st2["BreastL"]["seam_deg"] < 0.2
    # the lap cap and the settle time bound the work
    monkeypatch.setattr(jiggle_d6, "SOLVER_LOOP_TOL", 0.0)
    monkeypatch.setattr(jiggle_d6, "SOLVER_LOOP_SETTLE", 3.0)
    st3 = {}
    _solver(P, fps, bind, loop=True, stats=st3)
    assert st3["BreastL"]["laps"] == 1 + int(math.ceil(3.0 / (n / fps) - 1e-9))
    monkeypatch.setattr(jiggle_d6, "SOLVER_LOOP_SETTLE", 1e9)
    monkeypatch.setattr(jiggle_d6, "SOLVER_LOOP_MAX_LAPS", 5)
    _solver(P, fps, bind, loop=True, stats=st3)
    assert st3["BreastL"]["laps"] == 5


def test_static_loop_stays_at_rest(tmp_path):
    bind = _bind(tmp_path)
    P = _palettes(np.tile([0.0, 0.2, 0.1], (30, 1)))
    st = {}
    out = _solver(P, 30.0, bind, loop=True, stats=st)
    assert st["BreastL"]["laps"] == 2 and st["BreastL"]["seam_deg"] < 1e-9
    assert np.allclose(out, P, atol=1e-9)


# ---------------------------------------------------------------------------
# clips that do not loop
# ---------------------------------------------------------------------------


def test_clip_that_starts_still_starts_at_rest(tmp_path):
    bind = _bind(tmp_path)
    rv = np.zeros((60, 3))
    rv[10:, 2] = math.radians(5.0)
    P = _palettes(rv)
    st = {}
    out = _solver(P, 60.0, bind, stats=st)
    assert st["BreastL"] == dict(loop=False, frames=60, steps=59, lead_in_steps=15)
    assert jiggle_d6.SOLVER_LEAD_IN == 0.25
    assert np.array_equal(out, _solver(P, 60.0, bind, lead_in=0.0))
    assert np.allclose(_dev(out, 0), 0.0, atol=1e-9)
    assert np.allclose(_dev(out, 9), 0.0, atol=1e-9)
    assert abs(_dev(out, 12)[2]) > 1.0


def test_clip_cut_out_of_motion_starts_with_the_lag_of_that_motion(tmp_path):
    """A clip that begins in mid-swing: with the lead-in frame 0 is close to what a take
    that started earlier shows there; starting at rest it is not."""
    bind = _bind(tmp_path)
    fps = 60.0
    t = (np.arange(150) - 30) / fps  # the long take starts half a second earlier
    rv = np.zeros((len(t), 3))
    rv[:, 2] = 1.5 * t  # constant-rate turn ...
    rv[:, 1] = 0.1 * np.sin(2 * np.pi * 0.5 * t)  # ... plus a slow sway
    long_take = _solver(_palettes(rv), fps, bind, lead_in=0.0)
    cut = _palettes(rv[30:])
    lead = _solver(cut, fps, bind)
    rest = _solver(cut, fps, bind, lead_in=0.0)
    want = _dev(long_take, 30)
    assert np.linalg.norm(want) > 1.0
    assert np.allclose(_dev(rest, 0), 0.0, atol=1e-9)
    assert np.linalg.norm(_dev(lead, 0) - want) < 0.2 * np.linalg.norm(want)
    for f in (0, 3, 8):
        e_lead = np.linalg.norm(_dev(lead, f) - _dev(long_take, 30 + f))
        e_rest = np.linalg.norm(_dev(rest, f) - _dev(long_take, 30 + f))
        assert e_lead < 0.25 * e_rest, f
    # later the start is forgotten either way
    assert np.allclose(_dev(lead, 100), _dev(rest, 100), atol=0.02)
    # loop=False / warmup=0 are this same bake
    assert np.array_equal(lead, _solver(cut, fps, bind, loop=False))
    assert np.array_equal(lead, _solver(cut, fps, bind, loop=True, warmup=0))


# ---------------------------------------------------------------------------
# short clips
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("frames", [1, 2, 3])
def test_short_clips_are_returned_unchanged_looping_or_not(tmp_path, frames):
    """Fewer than four frames: a held pose (the game's 2-frame pose clips) or a 3-key
    cycle with at most two distinct frames -- nothing to simulate; the bone stays rigid."""
    bind = _bind(tmp_path)
    rv = np.zeros((frames, 3))
    rv[:, 2] = np.linspace(0.0, 0.3, frames)
    P = _palettes(rv)
    for kw in (dict(), dict(loop=True), dict(warmup=2), dict(lead_in=0.0)):
        st = {}
        out = _solver(P, 30.0, bind, stats=st, **kw)
        assert out is P and st == {}, kw
    assert jiggle_pass.apply_jiggle(P, 30.0, bind, loop=True) is P


def test_four_frame_loop_is_baked_and_closed(tmp_path):
    bind = _bind(tmp_path)
    rv = np.zeros((4, 3))
    rv[:, 2] = [0.0, 0.2, -0.2, 0.0]
    P = _palettes(rv)
    st = {}
    out = _solver(P, 10.0, bind, loop=True, stats=st)
    assert st["BreastL"]["frames"] == 3 and st["BreastL"]["steps"] == 18
    assert np.all(np.isfinite(out))
    assert np.allclose(out[3], out[0], atol=1e-12)
    assert np.linalg.norm(_dev(out, 1)) > 0.1


# ---------------------------------------------------------------------------
# plumbing: the loop flag from anim_meta to the bake
# ---------------------------------------------------------------------------


def test_clip_loops_reads_the_game_loop_flag():
    meta = {
        "clips": {
            "EN4_EXP_MOV_walk_cycle": {"loop": True},
            "EN4_COM_ATT_light_A": {"loop": False},
            "EN4_COM_MOV_run_cycle": {},
        }
    }
    assert ce.clip_loops(meta, "EN4_EXP_MOV_walk_cycle") is True
    assert ce.clip_loops(meta, "en4_exp_mov_walk_cycle") is True  # as anim_meta finds clips
    assert ce.clip_loops(meta, "EN4_COM_ATT_light_A") is False
    assert ce.clip_loops(meta, "EN4_COM_MOV_run_cycle") is False  # flag absent
    assert ce.clip_loops(meta, "GRIP_pose") is False  # not a game clip
    assert ce.clip_loops(None, "EN4_EXP_MOV_walk_cycle") is False  # extract without metadata
    assert ce.clip_loops({}, "EN4_EXP_MOV_walk_cycle") is False


def test_jiggle_pass_forwards_the_loop_flag(tmp_path):
    bind = _bind(tmp_path)
    P = _cycle(40)
    a = jiggle_pass.apply_jiggle(P, 30.0, bind, loop=True)
    assert np.array_equal(a, jiggle_d6.apply_jiggle(P, 30.0, bind, loop=True))
    b = jiggle_pass.apply_jiggle(P, 30.0, bind)
    assert np.array_equal(b, jiggle_d6.apply_jiggle(P, 30.0, bind))
    assert not np.allclose(a, b, atol=1e-4)


def test_export_passes_each_clip_its_loop_flag():
    """characters_export.export bakes with loop=clip_loops(meta, clip name)."""
    import inspect

    src = inspect.getsource(ce.export)
    assert "loop=clip_loops(meta, nm)" in src
    assert "model=jiggle_model" in src


def test_bake_policy_is_part_of_the_solver_cache_signature(monkeypatch):
    """The bake policy (lead-in, loop settling) is in the tag, so a solver cache baked
    under another policy, e.g. at rest with no loop handling, is not reused."""
    base = jiggle_d6.cache_signature("solver")
    assert base == jiggle_d6.cache_signature()
    assert jiggle_d6.MODEL_REVISION["solver"] == 3
    for name, value in (
        ("SOLVER_LEAD_IN", 0.0),
        ("SOLVER_LOOP_TOL", 1e-3),
        ("SOLVER_LOOP_SETTLE", 2.0),
        ("SOLVER_LOOP_MAX_LAPS", 3),
    ):
        monkeypatch.setattr(jiggle_d6, name, value)
        assert jiggle_d6.cache_signature("solver") != base, name
        assert jiggle_d6.cache_signature("pinned") == "pinned-engine-b1de22ed"
        monkeypatch.undo()
    assert jiggle_d6.cache_signature("solver") == base
