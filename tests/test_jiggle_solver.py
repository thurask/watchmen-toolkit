"""Jiggle 'solver' model: the PhysX 2.8.1.1 soft swing-limit row, file constants only.

The jiggle joint has no drive (game 0x5146ec); spring and damping are the soft swing
limits (45 deg / 0 deg), which PhysXCore turns into one zero-radius cone limit: a
unilateral soft row on tan(swing/4) (0x10227db0), solved in 4 iterations plus a conclude
pass (0x1022ce80 / 0x1022d500).  `jiggle_d6.SoftLimitJoint` steps that arithmetic;
`FrozenReference` below is an independent numpy transcription of the same DLL reading
(the reference integrator of findings/physx_d6.md) that the toolkit code must match.

Everything here is synthetic: no game files.
"""

import hashlib
import importlib.util
import math
import os

import numpy as np
import pytest

import characters_export as ce
import jiggle_d6
import jiggle_pass

LEVER = np.array([0.0, 0.05, 0.1225])  # parent -> bone, in the parent frame (|r| = 0.1323)
PARENT_ORIGIN = np.array([0.0, 1.0, 0.0])
PROPS = dict(jiggle_d6._FILE_DEFAULTS)


def _bind(tmp_path, name="BreastL", lever=LEVER):
    tb = np.array([[0.0, 0.0, 0.0], PARENT_ORIGIN, PARENT_ORIGIN + lever])
    path = tmp_path / ("bind_%s.npz" % name)
    np.savez(
        path,
        Rb=np.tile(np.eye(3), (3, 1, 1)),
        tb=tb,
        tloc=np.array([[0.0, 0.0, 0.0], PARENT_ORIGIN, lever]),
        names=np.array(["Root", "Spine2", name]),
        par=np.array([-1, 0, 1]),
    )
    return str(path), tb


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


def _origin(P, k, tb):
    return np.einsum("fab,b->fa", P[:, k, :, :3].astype(np.float64), tb[k]) + P[:, k, :, 3]


def _solver(P, fps, bind, **kw):
    kw.setdefault("props", PROPS)
    return jiggle_d6.apply_jiggle(P, fps, bind, model="solver", **kw)


def _step_clip(axis, deg=5.0, frames=90, at=10):
    rv = np.zeros((frames, 3))
    rv[at:, axis] = math.radians(deg)
    return rv


# ---------------------------------------------------------------------------
# frozen reference: numpy transcription of the PhysXCore reading (findings/physx_d6.md)
# ---------------------------------------------------------------------------


def _qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array(
        [
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz,
        ]
    )


def _q2m(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


class FrozenReference:
    """Body B (cube 0.8 m, mass 0.1) on a D6 joint to kinematic anchor A; do not edit to
    make a test pass -- it pins the reading of PhysXCore.dll 2.8.1.1."""

    BIAS = 0.7  # 0x1029e1b8
    TOL = 0.025004999712109566  # 0x102a0f84
    QZ = 9.999999747378752e-05  # 0x1028089c
    LIN2 = 1.1920928955078125e-07  # 0x1028058c
    DMIN = 9.999999747378752e-06  # 0x102808b4
    LEPS = 1.000000013351432e-10  # 0x102a10dc
    KEPS = 9.999999974752427e-07  # 0x102a1990
    BIG = 3.4028234663852886e38

    def __init__(self, k, d, lever, dt=1.0 / 60.0, iters=4):
        self.k, self.d, self.dt, self.iters = k, d, dt, iters
        self.lever = np.asarray(lever, float)
        self.invM = 10.0
        self.invI = 1.0 / (0.1 * 0.8 * 0.8 / 6.0)
        self.L1 = math.tan(math.radians(45.0) * 0.25)
        self.L2 = 0.0
        self.xA = np.zeros(3)
        self.qA = np.array([0.0, 0.0, 0.0, 1.0])
        self.qB = self.qA.copy()
        self.xB = self.lever.copy()
        self.vB = np.zeros(3)
        self.wB = np.zeros(3)

    def _row(self, lin, n, a, rhs, limit, soft):
        resp = self.invI * float(a @ a) + (float(n @ n) * self.invM if lin else 0.0)
        m = 1.0 / resp if resp else 0.0
        r = dict(lin=lin, n=n, a=a, m=m, B=m * self.BIAS, c=0.0, rhs=rhs, lam=0.0, lamv=0.0)
        r["lo"], r["hi"], r["limit"] = (0.0 if limit else -self.BIG), self.BIG, limit
        if soft and self.k:
            s = self.k * self.dt + max(self.d, self.DMIN)
            gamma, erp = 1.0 / (s * self.dt), self.k * self.dt / s
            f = 1.0 / (r["m"] * gamma + 1.0)
            r["c"] = r["m"] / (1.0 / gamma + r["m"])
            r["B"] *= erp * f
            r["m"] *= f
        return r

    def _rows(self):
        dt = self.dt
        R0 = _q2m(self.qB)
        r0 = R0 @ (-self.lever)
        dw = self.xA - (self.xB + r0)
        q = _qmul(np.array([-self.qB[0], -self.qB[1], -self.qB[2], self.qB[3]]), self.qA)
        q = np.where(np.abs(q) < self.QZ, 0.0, q)
        neg = q[3] < 0
        q = -q if neg else q
        q = q / np.linalg.norm(q)
        q0, q1 = self.qB, (-self.qA if neg else self.qA)
        xx = q0[0] * q1[0]
        ax = np.array(
            [
                xx + xx + (q1[3] * q0[3] - (q0[2] * q1[2] + q0[1] * q1[1] + xx)),
                q1[1] * q0[0] + q0[1] * q1[0] + q0[3] * q1[2] + q0[2] * q1[3],
                (q0[0] * q1[2] + q0[2] * q1[0]) - q1[1] * q0[3] - q1[3] * q0[1],
            ]
        )
        blocks = [[self._row(False, None, ax, q[0] / dt * -2.0, False, False)]]
        s = math.sqrt(q[0] ** 2 + q[3] ** 2)
        sy, sz, sw = (q[3] * q[1] - q[2] * q[0]) / s, (q[0] * q[1] + q[2] * q[3]) / s, s
        n2 = sz * sz + sy * sy
        if n2 != 0.0:
            fy, fz = sy * sy / n2, sz * sz / n2
            den = self.L1 * fz + fy * self.L2
            lim = (self.L1 * self.L2) / den if den != 0.0 else float("nan")
            e = math.sqrt(n2) / (sw + 1.0)
            if lim - self.TOL < e:
                a = R0[:, 1] * sy + R0[:, 2] * sz
                a = a / np.linalg.norm(a)
                blocks.append([self._row(False, None, a, (lim - e) / dt, True, True)])
        d0 = R0.T @ dw
        if float(d0 @ d0) > self.LIN2:
            n0 = dw / np.linalg.norm(dw)
            if abs(n0[2]) <= 0.7071067690849304:
                f = math.hypot(n0[0], n0[1])
                b = np.array([-n0[1], n0[0], 0.0]) / f
                c = np.array([-b[1] * n0[2], b[0] * n0[2], f])
            else:
                f = math.hypot(n0[1], n0[2])
                b = np.array([0.0, -n0[2], n0[1]]) / f
                c = np.array([f, -b[2] * n0[0], n0[0] * b[1]])
            axes = [n0, b / np.linalg.norm(b), c / np.linalg.norm(c)]
        else:
            axes = [R0[:, 0], R0[:, 1], R0[:, 2]]
        blocks.append(
            [self._row(True, n, np.cross(r0, n), -float(n @ dw) / dt, False, False) for n in axes]
        )
        return blocks

    def _solve(self, r, vA, wA):
        if r["lin"]:
            jv = r["n"] @ (self.vB - vA) + r["a"] @ self.wB
        else:
            jv = r["a"] @ (self.wB - wA)
        t = -jv * r["m"]
        r["lamv"] += t - r["c"] * r["lamv"]
        dl = t - r["B"] * r["rhs"] - r["lam"] * r["c"]
        nl = min(max(r["lam"] + dl, r["lo"]), r["hi"])
        dl, r["lam"] = nl - r["lam"], nl
        if r["lin"]:
            self.vB = self.vB + r["n"] * (self.invM * dl)
        self.wB = self.wB + r["a"] * (self.invI * dl)

    def _integ(self, q, w):
        n = np.linalg.norm(w)
        if n == 0.0:
            return q
        h = n * self.dt * 0.5
        return _qmul(np.concatenate([w * (math.sin(h) / n), [math.cos(h)]]), q)

    def step(self, xT, qT, nsub=1):
        h = nsub * self.dt
        vA = (np.asarray(xT, float) - self.xA) / h
        q = _qmul(
            np.asarray(qT, float), np.array([-self.qA[0], -self.qA[1], -self.qA[2], self.qA[3]])
        )
        q = -q if q[3] < 0 else q
        q = q / np.linalg.norm(q)
        wA = np.zeros(3)
        if abs(q[3] - 1.0) > self.KEPS and q[3] < 1.0:
            wA = q[:3] * (math.acos(q[3]) * 2.0 / h) / math.sqrt(1.0 - q[3] ** 2)
        for _ in range(nsub):
            self.wB = self.wB * (1.0 - 1.0 * self.dt)
            blocks = self._rows()
            for _i in range(self.iters):
                for blk in blocks:
                    for r in blk:
                        self._solve(r, vA, wA)
            vm, wm = self.vB.copy(), self.wB.copy()
            for blk in blocks:
                for r in blk:
                    r["rhs"] = max(r["rhs"], 0.0) if r["limit"] else 0.0
                    if abs(r["lam"]) > self.LEPS:
                        r["c"] = r["lamv"] / r["lam"] * r["c"]
                for r in blk:
                    self._solve(r, vA, wA)
            self.xB = self.xB + vm * self.dt
            self.qB = self._integ(self.qB, wm)
            self.xA = self.xA + vA * self.dt
            self.qA = self._integ(self.qA, wA)
        self.qA = self.qA / np.linalg.norm(self.qA)
        self.qB = self.qB / np.linalg.norm(self.qB)


def _anchor_path(n):
    """Smooth 3-axis rotation plus translation of the anchor, with a hard kick and a still
    stretch (kinematic deadband, cone row on and off, direct and frame-axis linear rows)."""
    t = np.arange(n) / 60.0
    rv = np.stack(
        [
            0.20 * np.sin(2 * np.pi * 1.3 * t),
            0.25 * np.sin(2 * np.pi * 2.1 * t + 0.4),
            0.30 * np.sin(2 * np.pi * 1.7 * t + 1.1),
        ],
        1,
    )
    x = np.stack([0.05 * np.sin(2 * np.pi * 1.1 * t), 0.03 * np.sin(2 * np.pi * 2.9 * t), 0 * t], 1)
    rv[n // 2 :] += [0.0, 0.3, -0.4]
    rv[-n // 5 :] = rv[-n // 5]
    x[-n // 5 :] = x[-n // 5]
    return x, [jiggle_d6._m2q(jiggle_d6._rotv2m(r).tolist()) for r in rv]


@pytest.mark.parametrize("k,d,lever", [(200.0, 0.8, LEVER), (70.0, 0.8, [-0.1008, 0.0, 0.0123])])
def test_soft_limit_joint_matches_the_frozen_reference(k, d, lever):
    xs, qs = _anchor_path(240)
    sim = jiggle_d6.SoftLimitJoint(k, d, lever)
    ref = FrozenReference(k, d, lever)
    sim.reset(tuple(xs[0]), qs[0])
    ref.xA, ref.qA = xs[0].copy(), np.array(qs[0])
    ref.qB = ref.qA.copy()
    ref.xB = ref.xA + _q2m(ref.qA) @ ref.lever
    moved = 0.0
    for j in range(1, len(xs)):
        nsub = 2 if j % 37 == 0 else 1  # a frame that takes two fixed substeps
        sim.step(tuple(xs[j]), qs[j], nsub)
        ref.step(xs[j], qs[j], nsub)
        assert np.allclose(sim.xb, ref.xB, atol=1e-9, rtol=0)
        assert np.allclose(sim.qb, ref.qB, atol=1e-9, rtol=0)
        assert np.allclose(sim.wb, ref.wB, atol=1e-7, rtol=0)
        assert np.allclose(sim.xa, ref.xA, atol=1e-12, rtol=0)
        rel = _q2m(ref.qA).T @ _q2m(ref.qB)
        moved = max(moved, float(np.linalg.norm(_rotvec(rel))))
    assert moved > math.radians(5.0)  # the path really exercises the joint


def test_soft_row_coefficients_are_the_dll_formulas():
    """0x10227cde / 0x102068b0: gamma = 1/(dt (d + k dt)), erp = k dt/(d + k dt), softness
    scaled by the cube's inertia about its CENTRE (0.1 * 0.8^2 / 6), bias 0.7."""
    sim = jiggle_d6.SoftLimitJoint(200.0, 0.8, LEVER)
    sim.qb = jiggle_d6._m2q(jiggle_d6._rotv2m(np.array([0.0, 0.0, 0.08])).tolist())
    cone = [r for r in sim._rows() if r[11]]
    assert len(cone) == 1
    m_eff = 0.1 * 0.8 * 0.8 / 6.0
    dt = 1.0 / 60.0
    gamma = 1.0 / (dt * (0.8 + 200.0 * dt))
    erp = 200.0 * dt / (0.8 + 200.0 * dt)
    f = 1.0 / (1.0 + m_eff * gamma)
    _lin, _n, _a, m, b, c, rhs, lo, hi = cone[0][:9]
    assert m == pytest.approx(m_eff * f, rel=1e-12)
    assert b == pytest.approx(0.7 * erp * m_eff * f, rel=1e-12)
    assert c == pytest.approx(m_eff * gamma / (1.0 + m_eff * gamma), rel=1e-12)
    assert (lo, hi) == (0.0, jiggle_d6._FLT_MAX)  # unilateral: pushes toward the centre only
    # the error is tan(swing / 4) against a zero-radius cone (swing2 limit 0 deg)
    assert rhs == pytest.approx(-math.tan(0.08 / 4.0) / dt, rel=1e-9)
    assert jiggle_d6.SOLVER_BIAS == 0.7 and jiggle_d6.SOLVER_ITERATIONS == 4


# ---------------------------------------------------------------------------
# model selection, cache signature, CLI
# ---------------------------------------------------------------------------


def test_solver_is_the_third_model_and_the_default():
    assert jiggle_d6.MODELS == ("pivot", "pinned", "solver")
    assert jiggle_d6.DEFAULT_MODEL == "solver"
    assert jiggle_d6.resolve_model() == ("solver", "file")
    assert jiggle_d6.resolve_model("pinned") == ("pinned", "engine")
    assert jiggle_d6.resolve_model("solver") == ("solver", "file")


def test_solver_uses_file_constants_only(tmp_path, monkeypatch):
    bind, _tb = _bind(tmp_path)
    P = _palettes(_step_clip(2))
    base = _solver(P, 60.0, bind)
    for mode in ("capture", "engine", "ratio", "absolute", "aniso"):
        with pytest.raises(ValueError):
            _solver(P, 60.0, bind, mode=mode)
    assert np.array_equal(_solver(P, 60.0, bind, mode="file"), base)
    # capture-fitted numbers and K_eff / D_eff overrides do not reach this model
    monkeypatch.setitem(jiggle_d6._CAPTURE_FIT, "breast", dict(K=5.0, D=1.0))
    over = dict(PROPS, breast=dict(PROPS["breast"], K_eff=5.0, D_eff=1.0))
    assert np.array_equal(_solver(P, 60.0, bind, props=over), base)
    # the file's spring and damping do
    soft = dict(PROPS, breast=dict(PROPS["breast"], k=70.0))
    assert not np.allclose(_solver(P, 60.0, bind, props=soft), base, atol=1e-4)
    damp = dict(PROPS, breast=dict(PROPS["breast"], d=3.0))
    assert not np.allclose(_solver(P, 60.0, bind, props=damp), base, atol=1e-4)


def test_cache_signature_separates_the_solver_and_keeps_the_old_tags(monkeypatch):
    sigs = {m: jiggle_d6.cache_signature(m) for m in jiggle_d6.MODELS}
    assert len(set(sigs.values())) == 3
    assert sigs["solver"].startswith("solver-file-")
    # 1.3.0 tags: caches baked by the release stay valid
    assert sigs["pinned"] == "pinned-engine-b1de22ed"
    assert sigs["pivot"] == "pivot-capture-b1de22ed"
    assert jiggle_d6.cache_signature("pivot", "engine") == "pivot-engine-b1de22ed"
    dirs = {m: ce.jiggle_cache_dir("/out/_bake/female", m) for m in jiggle_d6.MODELS}
    assert len(set(dirs.values())) == 3
    monkeypatch.setattr(jiggle_d6, "SOLVER_BIAS", 1.0)
    assert jiggle_d6.cache_signature("solver") != sigs["solver"]
    assert jiggle_d6.cache_signature("pinned") == sigs["pinned"]
    monkeypatch.undo()
    monkeypatch.setitem(jiggle_d6.MODEL_REVISION, "solver", jiggle_d6.MODEL_REVISION["solver"] + 1)
    assert jiggle_d6.cache_signature("solver") != sigs["solver"]
    # capture-fit constants are not part of the solver's signature
    monkeypatch.undo()
    monkeypatch.setitem(jiggle_d6._CAPTURE_FIT, "breast", dict(K=600.0, D=37.5))
    assert jiggle_d6.cache_signature("solver") == sigs["solver"]
    assert jiggle_d6.cache_signature("pivot") != sigs["pivot"]


def test_cli_and_wrappers_accept_the_solver_model(tmp_path, monkeypatch, capsys):
    import watchmen

    assert set(watchmen.JIGGLE_MODELS) == set(jiggle_d6.MODELS)
    assert watchmen.JIGGLE_MODELS[0] == jiggle_d6.DEFAULT_MODEL
    calls = {}

    class FakeExport:
        @staticmethod
        def export(exout, outdir, naz, jiggle_model=None):
            calls["characters"] = jiggle_model
            return 0

    monkeypatch.setitem(__import__("sys").modules, "characters_export", FakeExport)
    assert watchmen.main(["w", "characters", "EX", "OUT", "--jiggle-model", "solver"]) == 0
    assert calls["characters"] == "solver"
    assert watchmen.main(["w", "characters", "-h"]) == 0
    assert "solver|pivot|pinned" in capsys.readouterr().out
    bind, _tb = _bind(tmp_path)
    P = _palettes(_step_clip(2))
    a = jiggle_pass.apply_jiggle(P, 60.0, bind, model="solver")
    assert np.array_equal(a, jiggle_d6.apply_jiggle(P, 60.0, bind, model="solver"))


# ---------------------------------------------------------------------------
# pinned / pivot unchanged
# ---------------------------------------------------------------------------


def _old_inputs(tmp_path):
    bind, _tb = _bind(tmp_path)
    t = np.arange(150) / 30.0
    rv = np.stack([0.1 * np.sin(5 * t), 0.3 * np.sin(9 * t + 1), 0.4 * np.sin(13 * t)], 1)
    shift = np.stack([0.05 * np.sin(7 * t), 0.02 * np.sin(11 * t), 0.0 * t], 1)
    return bind, _palettes(rv, shift)


def test_pinned_and_pivot_are_bit_identical_to_1_3_0(tmp_path):
    """Against a 1.3.0 tree (WATCHMEN_TK130 or ../tk130 next to this checkout)."""
    root = os.environ.get("WATCHMEN_TK130") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tk130"
    )
    src = os.path.join(root, "wlib", "jiggle_d6.py")
    if not os.path.exists(src):
        pytest.skip("no 1.3.0 tree to compare against")
    spec = importlib.util.spec_from_file_location("jiggle_d6_130", src)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    assert "solver" not in old.MODELS
    bind, P = _old_inputs(tmp_path)
    for fps in (30.0, 60.0, 20.0):
        for kw in (
            dict(model="pinned"),
            dict(model="pivot"),
            dict(model="pivot", mode="engine"),
            dict(model="pivot", latency=0.0),
            dict(model="pinned", mode="ratio"),
            dict(model="pivot", gain=1.5),
        ):
            new = jiggle_d6.apply_jiggle(P, fps, bind, props=PROPS, **kw)
            ref = old.apply_jiggle(P, fps, bind, props=PROPS, **kw)
            assert new.dtype == ref.dtype and new.tobytes() == ref.tobytes(), (fps, kw)
        # the 1.3.0 default was the pinned model
        new = jiggle_d6.apply_jiggle(P, fps, bind, props=PROPS, model="pinned")
        assert new.tobytes() == old.apply_jiggle(P, fps, bind, props=PROPS).tobytes(), fps
    for m in ("pinned", "pivot"):
        assert jiggle_d6.cache_signature(m) == old.cache_signature(m)


def test_default_output_is_the_solver_model(tmp_path):
    bind, P = _old_inputs(tmp_path)
    default = jiggle_d6.apply_jiggle(P, 30.0, bind, props=PROPS)
    assert np.array_equal(default, _solver(P, 30.0, bind))
    pinned = jiggle_d6.apply_jiggle(P, 30.0, bind, props=PROPS, model="pinned")
    assert not np.allclose(default, pinned, atol=1e-4)
    # same input twice -> same bytes (no hidden state in the stepper)
    a = hashlib.sha256(_solver(P, 30.0, bind).tobytes()).hexdigest()
    assert a == hashlib.sha256(_solver(P, 30.0, bind).tobytes()).hexdigest()


# ---------------------------------------------------------------------------
# behaviour of the solver model
# ---------------------------------------------------------------------------


def test_static_parent_gives_no_deviation(tmp_path):
    """Gravity is cancelled by the game's per-frame -m g force (0x656fb4): no sag."""
    bind, _tb = _bind(tmp_path)
    P = _palettes(np.tile([0.3, -0.2, 0.5], (40, 1)))
    out = _solver(P, 60.0, bind)
    assert np.allclose(out[:, 2], P[:, 2], atol=1e-6)
    assert np.array_equal(out[:, :2], P[:, :2].astype(np.float32))


def test_step_relaxes_first_order_with_one_frame_of_delay(tmp_path):
    """A swing step is read back one frame late (0x6563a0 reads before the step) and
    then relaxes at about 0.175 k / (d + k dt) per second (tan(swing/4), bias 0.7)."""
    bind, _tb = _bind(tmp_path)
    at = 10
    out = _solver(_palettes(_step_clip(2, at=at)), 60.0, bind)
    z = np.array([_dev(out, f)[2] for f in range(len(out))])
    assert np.allclose(z[:at], 0.0, atol=1e-5)
    assert z[at] == pytest.approx(-5.0, abs=1e-3)  # body still where the parent was
    assert z[at + 1] == pytest.approx(-5.0, abs=1e-3)  # result of the step read a frame later
    ratios = z[at + 3 : at + 10] / z[at + 2 : at + 9]
    assert np.all((ratios > 0.82) & (ratios < 0.92))
    rate = -math.log(float(np.mean(ratios))) * 60.0
    assert rate == pytest.approx(0.175 * 200.0 / (0.8 + 200.0 / 60.0), rel=0.2)
    assert abs(z[at + 14]) < 0.5 and np.all(np.abs(z[at + 20 :]) < 0.5)
    # softer file spring (belly): slower
    slow = _solver(
        _palettes(_step_clip(2, at=at)), 60.0, bind, props=dict(PROPS, breast=PROPS["belly"])
    )
    assert abs(_dev(slow, at + 8)[2]) > abs(z[at + 8]) + 0.3


def test_twist_is_locked_and_the_lever_is_rigid(tmp_path):
    bind, tb = _bind(tmp_path)
    at = 10
    out = _solver(_palettes(_step_clip(0, at=at)), 60.0, bind).astype(np.float64)
    x = np.array([_dev(out, f)[0] for f in range(len(out))])
    assert x[at] == pytest.approx(-5.0, abs=1e-3) and abs(x[at + 1]) < 1e-2
    assert np.all(np.abs(x[at + 2 :]) < 1e-2)
    # bone origin stays on the lever about the parent origin of the frame it was read in
    P = _palettes(_step_clip(2, at=at))
    out = _solver(P, 60.0, bind).astype(np.float64)
    pivot = _origin(P, 1, tb)
    dist = np.linalg.norm(_origin(out, 2, tb) - pivot, axis=1)
    assert np.allclose(dist, np.linalg.norm(LEVER), atol=2e-4)


def test_zero_radius_cone_needs_a_swing2_component(tmp_path):
    """0x1022bd2d: limit = L1 L2 / (L1 fz + L2 fy) with L2 = tan(0) is 0 when the swing has
    a swing-2 (Z) component and 0/0 (no row) when it has none: a pure swing-1 deviation is
    not pulled back, any mixed one is pulled back as a whole."""
    bind, _tb = _bind(tmp_path)
    at = 5
    pure = _solver(_palettes(_step_clip(1, at=at, frames=60)), 60.0, bind)
    assert _dev(pure, 55)[1] == pytest.approx(-5.0, abs=1e-3)
    rv = np.zeros((60, 3))
    rv[at:] = np.radians([0.0, 5.0, 0.5])
    mixed = _solver(_palettes(rv), 60.0, bind)
    assert np.linalg.norm(_dev(mixed, 55)) < 0.3


def test_metre_clamp_on_the_bone_origin(tmp_path):
    """Game 0x6563a0: |pos - animated pos| > limit -> pos lerp + quat slerp by limit/len."""
    bind, tb = _bind(tmp_path)
    rv = np.zeros((30, 3))
    rv[5:] = np.radians([0.0, 80.0, 8.0])  # the lever is 0.1225 m off this axis
    P = _palettes(rv)
    out = _solver(P, 60.0, bind).astype(np.float64)
    off = np.linalg.norm(_origin(out, 2, tb) - _origin(P, 2, tb), axis=1)
    assert off.max() == pytest.approx(PROPS["breast"]["limit"], abs=1e-5)
    assert off[5] == pytest.approx(0.08, abs=1e-5) and off[4] < 1e-6
    # the rotation is slerped by the same ratio: well short of the 80 deg the body lags
    lag = np.linalg.norm(_dev(out, 5))
    assert 20.0 < lag < 60.0
    tight = dict(PROPS, breast=dict(PROPS["breast"], limit=0.01))
    out = _solver(P, 60.0, bind, props=tight).astype(np.float64)
    off = np.linalg.norm(_origin(out, 2, tb) - _origin(P, 2, tb), axis=1)
    assert off.max() == pytest.approx(0.01, abs=1e-5)
    assert np.linalg.norm(_dev(out, 5)) < lag / 4


def test_clip_rate_is_resampled_to_the_60_hz_step(tmp_path):
    """The physics step is 1/60 s whatever the clip rate: a 20 / 30 fps clip of the same
    motion gives the 60 fps result at the shared instants up to the interpolation of the
    parent between clip frames (Catmull-Rom; within 20 % rms here), and a 120 fps clip is
    the 60 fps result read between steps (within 1 %: the lead-in before frame 0 and the
    end tangents come from the clip's own first / last frame spacing)."""
    bind, _tb = _bind(tmp_path)
    dur = 2.0

    def clip(fps):
        t = np.arange(int(dur * fps) + 1) / fps
        rv = np.zeros((len(t), 3))
        rv[:, 2] = 0.15 * np.sin(2 * np.pi * 1.0 * t)
        rv[:, 1] = 0.10 * np.sin(2 * np.pi * 1.5 * t)
        return _palettes(rv)

    full = _solver(clip(60.0), 60.0, bind)
    d60 = np.array([_dev(full, f) for f in range(len(full))])
    assert np.abs(d60).max() > 0.5
    rms60 = float(np.sqrt((d60**2).sum(1).mean()))
    for fps, tol in ((30.0, 0.2), (20.0, 0.2), (24.0, 0.2), (120.0, 1e-2)):
        out = _solver(clip(fps), fps, bind)
        step = 60.0 / fps
        idx = [f for f in range(len(out)) if abs(f * step - round(f * step)) < 1e-9]
        d = np.array([_dev(out, f) for f in idx])
        ref = d60[[int(round(f * step)) for f in idx]]
        err = float(np.sqrt(((d - ref) ** 2).sum(1).mean()))
        assert err < tol * rms60, (fps, err, rms60)
        assert np.all(np.isfinite(out))
    # at the engine rate the parent is not interpolated: the 60 fps clip IS the step grid
    sim = jiggle_d6.SoftLimitJoint(200.0, 0.8, LEVER)
    P = clip(60.0)
    q = [jiggle_d6._m2q(P[f, 1, :, :3].tolist()) for f in range(len(P))]
    sim.reset(tuple(PARENT_ORIGIN), q[0])
    for f in range(5):
        sim.step(tuple(PARENT_ORIGIN), q[f])
    Rk = np.array(jiggle_d6._q_axes(sim.qb)).T
    at_rest = _solver(P, 60.0, bind, lead_in=0.0)
    assert np.allclose(at_rest[5, 2, :, :3], Rk, atol=1e-6)


def test_latency_and_gain_options(tmp_path):
    bind, _tb = _bind(tmp_path)
    at = 10
    P = _palettes(_step_clip(2, at=at))
    lat = _solver(P, 60.0, bind)
    now = _solver(P, 60.0, bind, latency=0.0)
    for f in range(at, 40):
        assert _dev(now, f)[2] == pytest.approx(_dev(lat, f + 1)[2], abs=2e-3)
    half = _solver(P, 60.0, bind, gain=0.5)
    assert _dev(half, at + 4)[2] == pytest.approx(0.5 * _dev(lat, at + 4)[2], abs=1e-3)


def test_start_at_rest_and_optional_warmup_for_loops(tmp_path):
    """lead_in=0: the body starts at rest on frame 0 (as the other models).  warmup=1 plays
    the clip once before the recorded pass, so a looping clip starts in its cycle.  The
    default bake policy (lead-in, loop flag) is covered by tests/test_jiggle_default.py."""
    bind, _tb = _bind(tmp_path)
    n = 60  # one period of a 1 Hz swing, frame n would equal frame 0
    t = np.arange(n) / 60.0
    rv = np.zeros((n, 3))
    rv[:, 2] = 0.2 * np.sin(2 * np.pi * t)
    rv[:, 1] = 0.1 * np.cos(2 * np.pi * t)
    P = _palettes(rv)
    cold = _solver(P, 60.0, bind, lead_in=0.0)
    warm = _solver(P, 60.0, bind, warmup=1)
    assert np.allclose(_dev(cold, 0), 0.0, atol=1e-5)
    assert np.linalg.norm(_dev(warm, 0)) > 0.2
    two = _solver(np.concatenate([P, P]), 60.0, bind)  # the second lap of a longer take
    assert np.allclose(_dev(warm, 0), _dev(two, n), atol=0.05)
    assert np.allclose(_dev(warm, 30), _dev(two, n + 30), atol=0.05)
    # warmup=0 is the plain non-looping bake, whatever the loop flag says
    assert np.array_equal(_solver(P, 60.0, bind, warmup=0, loop=True), _solver(P, 60.0, bind))


def test_groups_take_their_own_file_constants(tmp_path):
    """Hair and belly addons are configured by the same code as the breasts (game
    0x648858 loop); only spring, damping and distance limit differ."""
    P = _palettes(_step_clip(2, at=10))
    devs = {}
    for name in ("BreastL", "JiggleBelly", "Hair"):
        bind, _tb = _bind(tmp_path, name=name)
        out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="solver", props=PROPS)
        devs[name] = abs(_dev(out, 18)[2])
    # k = 200 / 70 / 100 -> relaxation 8.5 / 6.2 / 7.1 per second
    assert devs["BreastL"] < devs["Hair"] < devs["JiggleBelly"]
    bind, _tb = _bind(tmp_path, name="Hair")
    as_hair = jiggle_d6.apply_jiggle(P, 60.0, bind, model="solver", props=PROPS)
    swapped = dict(PROPS, hair=PROPS["breast"])
    as_breast = jiggle_d6.apply_jiggle(P, 60.0, bind, model="solver", props=swapped)
    assert not np.allclose(as_hair, as_breast, atol=1e-4)
