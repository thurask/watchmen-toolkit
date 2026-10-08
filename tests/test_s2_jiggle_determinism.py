"""The solver jiggle bake gives the same bytes on every platform.

A baked jiggle channel is a simulation: each step feeds the next through a one-sided
limit row, and on clips that keep the bone near its limit a difference in the last bit
of one value grows to centimetres.  The solver therefore uses only operations whose
result IEEE 754 fixes (+ - * / sqrt on doubles, one operation at a time) and takes
its trigonometry, its nearest-rotation and its sums from `exact_math`:

* no C-library trigonometry (`math.sin` ... differ between the Windows and the Linux
  C library) and no `float ** 2`;
* no `sum()` of floats (compensated from Python 3.12 on, a plain fold before);
* no LAPACK / BLAS (`numpy.linalg.svd`, `@`, `einsum`, `norm`: they depend on the
  OpenBLAS build numpy ships with).

The digests below were made on Linux (Python 3.13, numpy 2.5) and must come out the
same wherever the suite runs.  Everything here is synthetic: no game files.
"""

import hashlib
import math
import struct

import numpy as np
import pytest

import exact_math as em
import jiggle_d6

CLAMP = 0.004  # metres: a distance limit the "clamp" bake reaches
CLIPS = {"one-shot": (90, False), "loop": (48, True), "gain": (40, False), "clamp": (90, False)}
LEVER = (0.0, 0.05, 0.1225)
ORIGIN = (0.0, 1.0, 0.0)


def _digest(values):
    return hashlib.sha256(b"".join(struct.pack("<d", v) for v in values)).hexdigest()[:16]


def _grid(lo, hi, n):
    """n + 1 doubles from lo to hi made with exact operations only."""
    return [lo + (hi - lo) * (i / float(n)) for i in range(n + 1)]


def _next_up(v):
    """The next double above v (math.nextafter needs Python 3.9)."""
    (n,) = struct.unpack("<q", struct.pack("<d", v))
    if v == 0.0:
        return 5e-324
    return struct.unpack("<d", struct.pack("<q", n + 1 if v > 0 else n - 1))[0]


def _ulps(a, b):
    if b == 0.0:
        return abs(a) / 5e-324
    return abs(a - b) / (_next_up(abs(b)) - abs(b))


# ---------------------------------------------------------------------------
# exact_math
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, lo, hi, tol",
    [
        ("sin", -40.0, 40.0, 1.0),
        ("cos", -40.0, 40.0, 1.0),
        ("tan", -1.5, 1.5, 4.0),
        ("atan", -50.0, 50.0, 1.0),
        ("acos", -1.0, 1.0, 3.0),
    ],
)
def test_functions_agree_with_the_c_library_to_a_few_ulp(name, lo, hi, tol):
    mine, ref = getattr(em, name), getattr(math, name)
    worst = max(_ulps(mine(x), ref(x)) for x in _grid(lo, hi, 20011))
    assert worst <= tol + 1.0  # the C library itself may be 1 ulp off


def test_atan2_covers_every_quadrant_and_the_axes():
    for y in _grid(-2.0, 2.0, 97):
        for x in _grid(-2.0, 2.0, 89):
            assert _ulps(em.atan2(y, x), math.atan2(y, x)) <= 3.0 or (x == 0.0 and y == 0.0)
    assert em.atan2(0.0, 0.0) == 0.0
    assert em.atan2(1.0, 0.0) == em.HALF_PI and em.atan2(-1.0, 0.0) == -em.HALF_PI
    assert em.atan2(0.0, -1.0) == em.PI
    assert em.acos(1.0) == 0.0 and em.acos(-1.0) == em.PI and em.acos(1.5) == 0.0
    assert em.sin(0.0) == 0.0 and em.cos(0.0) == 1.0
    assert em.atan(float("inf")) == em.HALF_PI


def test_function_values_are_pinned_bit_for_bit():
    """The same digests on every platform: this is the cross-platform check."""
    xs = _grid(-12.0, 12.0, 4001)
    us = _grid(-1.0, 1.0, 4001)
    got = {
        "sin": _digest(em.sin(x) for x in xs),
        "cos": _digest(em.cos(x) for x in xs),
        "tan": _digest(em.tan(x) for x in _grid(-1.5, 1.5, 4001)),
        "atan": _digest(em.atan(x) for x in xs),
        "acos": _digest(em.acos(u) for u in us),
        "atan2": _digest(em.atan2(u, x) for u, x in zip(us, xs)),
    }
    assert got == PINNED_FUNCTIONS


def test_fold_is_a_plain_left_fold():
    vals = [1e16, 1.0, -1e16, 1.0]
    assert em.fold(vals) == ((1e16 + 1.0) - 1e16) + 1.0 == 1.0
    assert em.fold([]) == 0.0


def test_nearest_rotation_is_the_polar_factor():
    rs = np.random.RandomState(7)
    for n in range(300):
        A = np.linalg.qr(rs.randn(3, 3))[0]
        if n % 3 == 1:
            A = A.astype(np.float32).astype(np.float64)  # a palette rotation
        elif n % 3 == 2:
            A = A @ np.diag(rs.uniform(0.3, 4.0, 3))  # scaled
        Q = np.array(em.nearest_rotation(A.tolist()))
        U, _, Vt = np.linalg.svd(A)
        assert np.abs(Q - U @ Vt).max() < 1e-12
        assert np.abs(Q @ Q.T - np.eye(3)).max() < 1e-14
    with pytest.raises(ValueError):
        em.nearest_rotation([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 0.0, 1.0]])


def test_matrix_helpers_match_numpy():
    rs = np.random.RandomState(1)
    A, B, v = rs.randn(3, 3), rs.randn(3, 3), rs.randn(3)
    assert np.allclose(em.mat_mul(A.tolist(), B.tolist()), A @ B, atol=1e-14)
    assert np.allclose(em.mat_vec(A.tolist(), v.tolist()), A @ v, atol=1e-14)
    assert np.array_equal(np.array(em.transpose(A.tolist())), A.T)


# ---------------------------------------------------------------------------
# the solver
# ---------------------------------------------------------------------------


def _bind(tmp_path):
    tb = np.array([[0.0, 0.0, 0.0], ORIGIN, np.add(ORIGIN, LEVER)])
    path = tmp_path / "bind_female_file_v1.npz"
    np.savez(
        path,
        Rb=np.tile(np.eye(3), (3, 1, 1)),
        tb=tb,
        tloc=np.array([[0.0, 0.0, 0.0], ORIGIN, LEVER]),
        names=np.array(["Root", "Spine2", "BreastL"]),
        par=np.array([-1, 0, 1]),
    )
    return str(path)


def _rot(rv):
    """Rotation matrix of a rotation vector, exact_math only."""
    a = math.sqrt(rv[0] * rv[0] + rv[1] * rv[1] + rv[2] * rv[2])
    if a < 1e-12:
        return ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    x, y, z = rv[0] / a, rv[1] / a, rv[2] / a
    K = ((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0))
    KK = em.mat_mul(K, K)
    s, c = em.sin(a), 1.0 - em.cos(a)
    return tuple(
        tuple((1.0 if i == j else 0.0) + s * K[i][j] + c * KK[i][j] for j in range(3))
        for i in range(3)
    )


def _clip(frames, closed, amp=0.9, speed=5.0):
    """A hard two-axis swing of the parent about ORIGIN (float32 palettes, like a bake);
    built without the C library so the input is the same everywhere too."""
    n = frames + (1 if closed else 0)
    P = np.zeros((n, 3, 3, 4), np.float32)
    P[:, 0, :, :3] = np.eye(3)
    for f in range(n):
        t = f / float(frames)
        rv = (
            0.3 * amp * em.sin(2 * em.PI * speed * t + 0.4),
            0.5 * amp * em.cos(4 * em.PI * t),
            amp * em.sin(2 * em.PI * t),
        )
        R = _rot(rv)
        back = em.mat_vec(R, ORIGIN)
        for k in (1, 2):
            for i in range(3):
                P[f, k, i, :3] = R[i]
                P[f, k, i, 3] = ORIGIN[i] - back[i]
    return P


def _bake(tmp_path, **kw):
    out = {}
    bind = _bind(tmp_path)
    out["one-shot"] = jiggle_d6.apply_jiggle(_clip(90, False), 30.0, bind, **kw)
    out["loop"] = jiggle_d6.apply_jiggle(_clip(48, True), 24.0, bind, loop=True, **kw)
    out["gain"] = jiggle_d6.apply_jiggle(_clip(40, False), 30.0, bind, gain=0.5, **kw)
    tight = dict(kw.pop("props"))
    tight["breast"] = dict(tight["breast"], limit=CLAMP)
    out["clamp"] = jiggle_d6.apply_jiggle(_clip(90, False), 30.0, bind, props=tight, **kw)
    return out


def test_the_clips_exercise_the_limit_and_the_clamp(tmp_path):
    """The pinned bakes are worth pinning: the bone leaves its parent in each, and the
    "clamp" bake reaches its distance limit (the write-back's clamp and slerp)."""
    props = dict(jiggle_d6._FILE_DEFAULTS)
    out = _bake(tmp_path, props=props)
    tb = np.add(ORIGIN, LEVER)
    moved = {}
    for name, P in out.items():
        src = _clip(*CLIPS[name])
        assert P.dtype == np.float32 and P.shape == src.shape
        assert np.array_equal(P[:, :2], src[:, :2])  # only the jiggle bone is written
        a = P[:, 2].astype(np.float64)
        b = src[:, 2].astype(np.float64)
        d = (a[:, :, :3] @ tb + a[:, :, 3]) - (b[:, :, :3] @ tb + b[:, :, 3])
        moved[name] = float(np.linalg.norm(d, axis=1).max())
        assert moved[name] > 1e-3, name
    assert moved["one-shot"] > 1.5 * CLAMP
    assert abs(moved["clamp"] - CLAMP) < 1e-6


def test_bake_digests_are_pinned(tmp_path):
    """The same bytes on every platform (Windows / Linux, any Python from 3.8, any numpy)."""
    props = dict(jiggle_d6._FILE_DEFAULTS)
    got = {
        k: hashlib.sha256(v.tobytes()).hexdigest()[:16]
        for k, v in _bake(tmp_path, props=props).items()
    }
    assert got == PINNED_BAKES


class _NoLibm:
    """`math` with only the operations IEEE 754 fixes."""

    sqrt, floor, ceil, degrees = math.sqrt, math.floor, math.ceil, math.degrees

    def __getattr__(self, name):
        raise AssertionError("solver called math.%s" % name)


def test_the_solver_calls_nothing_platform_dependent(tmp_path, monkeypatch):
    props = dict(jiggle_d6._FILE_DEFAULTS)
    want = _bake(tmp_path, props=props)

    def banned(name):
        def f(*a, **k):
            raise AssertionError("solver called %s" % name)

        return f

    monkeypatch.setattr(jiggle_d6, "math", _NoLibm())
    monkeypatch.setattr(em, "math", _NoLibm(), raising=False)
    monkeypatch.setattr(jiggle_d6, "sum", banned("sum"), raising=False)
    monkeypatch.setattr(jiggle_d6, "pow", banned("pow"), raising=False)
    for mod, name in (
        (np.linalg, "svd"),
        (np.linalg, "norm"),
        (np.linalg, "inv"),
        (np, "einsum"),
        (np, "dot"),
        (np, "matmul"),
        (np, "trace"),
    ):
        monkeypatch.setattr(mod, name, banned("numpy %s" % name))
    monkeypatch.setattr(jiggle_d6, "_orth", banned("_orth"))
    monkeypatch.setattr(jiggle_d6, "_slerp_m", banned("_slerp_m"))
    monkeypatch.setattr(jiggle_d6, "_rotv2m", banned("_rotv2m"))
    got = _bake(tmp_path, props=props)
    for k in want:
        assert np.array_equal(got[k], want[k]), k


def test_solver_source_has_no_power_operator_or_builtin_sum():
    import inspect

    src = "".join(
        inspect.getsource(o)
        for o in (
            jiggle_d6.SoftLimitJoint,
            jiggle_d6._apply_jiggle_solver,
            jiggle_d6._q_slerp,
            jiggle_d6._q_extrapolate,
            jiggle_d6._loop_frames,
            jiggle_d6._slerp_rot,
            jiggle_d6._m2q,
        )
    )
    code = "\n".join(line.split("#")[0] for line in src.splitlines())
    assert "**" not in code and "sum(" not in code and " @ " not in code
    assert "np.linalg" not in code and "einsum" not in code


def test_the_arithmetic_change_has_its_own_cache_tag():
    """Bakes of the earlier arithmetic (tag 8872e40b) are not served from the cache."""
    assert jiggle_d6.MODEL_REVISION["solver"] == 3
    assert jiggle_d6.cache_signature("solver") != "solver-file-8872e40b"
    assert jiggle_d6.cache_signature("pinned") == "pinned-engine-b1de22ed"
    assert jiggle_d6.cache_signature("pivot") == "pivot-capture-b1de22ed"


def test_last_bit_noise_is_what_the_fix_removes(tmp_path, monkeypatch):
    """Why it matters.  PhysX does not execute an anchor rotation below 0.16 degrees per
    step (SOLVER_KIN_EPS), so on a slow, small motion one bit decides whether the anchor
    turns in a step: move the last bit of one sine in a hundred and the baked bone ends
    up millimetres away.  With the dead band off the same noise changes nothing."""
    props = dict(jiggle_d6._FILE_DEFAULTS)
    bind = _bind(tmp_path)
    clip = _clip(120, True, amp=0.02, speed=3.0)
    a = jiggle_d6.apply_jiggle(clip, 30.0, bind, props=props, loop=True)
    assert np.array_equal(a, jiggle_d6.apply_jiggle(clip, 30.0, bind, props=props, loop=True))
    real, calls = em.sin, [0]

    def noisy(x):
        calls[0] += 1
        v = real(x)
        return _next_up(v) if calls[0] % 100 == 0 else v

    monkeypatch.setattr(em, "sin", noisy)
    c = jiggle_d6.apply_jiggle(clip, 30.0, bind, props=props, loop=True)
    assert calls[0] > 1000
    assert np.abs(a.astype(np.float64) - c).max() > 1e-3
    monkeypatch.setattr(jiggle_d6, "SOLVER_KIN_EPS", 0.0)
    calls[0] = 0
    c0 = jiggle_d6.apply_jiggle(clip, 30.0, bind, props=props, loop=True)
    monkeypatch.setattr(em, "sin", real)
    a0 = jiggle_d6.apply_jiggle(clip, 30.0, bind, props=props, loop=True)
    assert np.array_equal(a0, c0)


PINNED_FUNCTIONS = {
    "sin": "322f8faec6ac433e",
    "cos": "e081c972eaa1d261",
    "tan": "1b6f0d38ded3c5be",
    "atan": "a69f3c1417c93bcd",
    "acos": "6336b63061f515fb",
    "atan2": "8c146389760a3ef3",
}
PINNED_BAKES = {
    "one-shot": "3b3aae24a29dc4a1",
    "loop": "e6fa46ad0e6adf43",
    "gain": "22fbcd9c693c0b65",
    "clamp": "a87b471226294872",
}
