"""Jiggle post-pass: driven damped-spring secondary motion for jiggle bones.
Params fit from captured palettes (see jiggle_params.npz; fit at 30fps).
Model: rotvec deviation x rel parent: x[t+1]=a*x[t]+b*x[t-1]+C@drive[t],
drive = [grav+inertial force (parent frame, per-frame^2), parent ang vel, ang accel].
Sim always runs on a 30fps grid (resample in/out) so params stay valid.
Usage as module: apply_jiggle(P, fps, bind_npz_path, bones=None) -> P modified copy.
"""

import numpy as np, os

_PDIR = os.path.dirname(os.path.abspath(__file__))


def _engine_ar2(k, zeta, dt=1 / 30.0):
    """AR(2) coeffs from ENGINE spring constants (GameEssentials.fragment
    PhysicsWorld: m_n{breast,belly,hair}springconstant/damping/distancelimit;
    damping 0.8 acts as a RATIO: d = 2*zeta*sqrt(k) -- capture-fit implies
    d~18-19 vs 20.9 predicted, k within 20%; semi-implicit Euler assumed)."""
    import math

    d = 2.0 * zeta * math.sqrt(k)
    return 2.0 - k * dt * dt - d * dt, -(1.0 - d * dt)


def _params():
    p = os.path.join(_PDIR, "jiggle_params.npz")
    if os.path.exists(p):
        z = np.load(p)
        return {
            "BreastL": (float(z["breastL_a"]), float(z["breastL_b"]), z["breastL_C"]),
            "BreastR": (float(z["breastR_a"]), float(z["breastR_b"]), z["breastR_C"]),
            # no gimp captures: JiggleBelly reuses BreastL dynamics (placeholder)
            "JiggleBelly": (float(z["breastL_a"]), float(z["breastL_b"]), z["breastL_C"]),
        }, float(z["gain"])
    # fresh-install fallback: ENGINE constants (k=200/70 zeta=0.8), isotropic drive
    ab_br = _engine_ar2(200, 0.8)
    ab_be = _engine_ar2(70, 0.8)
    C = np.zeros((3, 9))
    C[:, :3] = np.eye(3) * (1 / 900.0)  # dt^2 * force term only
    return {
        "BreastL": (ab_br[0], ab_br[1], C),
        "BreastR": (ab_br[0], ab_br[1], C),
        "JiggleBelly": (ab_be[0], ab_be[1], C),
    }, 1.0


def _orth(R):
    U, _, Vt = np.linalg.svd(R)
    return U @ Vt


def _rotv2m(v):
    a = np.linalg.norm(v)
    if a < 1e-12:
        return np.eye(3)
    x, y, z = v / a
    K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def apply_jiggle(P, fps, bindpath, bones=None, gain=None):
    if not os.path.exists(os.path.join(_PDIR, "jiggle_params.npz")):
        # fresh install: jiggle_d6 (file-only, capture-parity 2026-07-12e)
        # replaces the old _engine_ar2 approximation entirely.
        from jiggle_d6 import apply_jiggle as _d6

        return _d6(P, fps, bindpath, bones=bones, gain=gain)
    bt = np.load(bindpath, allow_pickle=True)
    Rb = bt["Rb"].astype(np.float64)
    tb = bt["tb"].astype(np.float64)
    names = [str(n) for n in bt["names"]]
    par = bt["par"]
    prm, g0 = _params()
    if gain is None:
        gain = g0
    if bones is None:
        bones = [n for n in names if n in prm]
    F = len(P)
    if F < 4:
        return P
    P = np.array(P, dtype=np.float64, copy=True)
    dur = F / max(fps, 1e-6)
    N = max(4, int(round(dur * 30.0)))
    t_o = np.arange(F) / fps
    t_n = np.arange(N) / 30.0
    t_n = np.clip(t_n, 0, t_o[-1])
    for bone in bones:
        if bone not in names:
            continue
        k = names.index(bone)
        p = par[k]
        if p < 0:
            continue
        a, b, C = prm[bone]
        A_o = np.einsum("fab,bc->fac", P[:, p, :, :3], Rb[p])
        # resample parent rot + anchor to 30fps grid
        A = np.empty((N, 3, 3))
        anch_o = np.einsum("fab,b->fa", P[:, p, :, :3], tb[k]) + P[:, p, :, 3]
        anch = np.empty((N, 3))
        for j, tj in enumerate(t_n):
            i = min(int(tj * fps), F - 2)
            w = tj * fps - i
            A[j] = _orth((1 - w) * A_o[i] + w * A_o[i + 1])
            anch[j] = (1 - w) * anch_o[i] + w * anch_o[i + 1]
        acc = np.zeros_like(anch)
        acc[1:-1] = anch[2:] - 2 * anch[1:-1] + anch[:-2]
        Ff = np.einsum("fba,fb->fa", A, np.array([0, -0.0109, 0.0]) - acc)
        dA = np.zeros_like(A)
        dA[1:-1] = (A[2:] - A[:-2]) / 2
        S = np.einsum("fba,fbc->fac", A, dA)
        W = np.stack([S[:, 2, 1], S[:, 0, 2], S[:, 1, 0]], 1)
        AL = np.zeros_like(W)
        AL[1:-1] = (W[2:] - W[:-2]) / 2
        drv = np.concatenate([Ff, W, AL], 1)
        x = np.zeros((N, 3))
        for i in range(1, N - 1):
            x[i + 1] = a * x[i] + b * x[i - 1] + C @ drv[i]
        x *= gain
        # soft clamp (protects against misclocked clips, e.g. dance_small fps anomaly)
        n = np.linalg.norm(x, axis=1, keepdims=True)
        x = x * np.where(n > 1e-9, 0.35 * np.tanh(n / 0.35) / np.maximum(n, 1e-9), 1.0)
        # back to original grid + apply: B_new = A·R(x)·A^T·B (rotate deviation in parent frame)
        for i, ti in enumerate(t_o):
            j = min(int(ti * 30.0), N - 2)
            w = ti * 30.0 - j
            xi = (1 - w) * x[j] + w * x[j + 1]
            Ai = A_o[i]
            D = Ai @ _rotv2m(xi) @ Ai.T
            P[i, k, :, :3] = D @ P[i, k, :, :3]
            # keep skin anchored at joint: translation adjusted so joint pos invariant
            jw = anch_o[i]
            P[i, k, :, 3] = jw - P[i, k, :, :3] @ tb[k]
    return P.astype(np.float32)


if __name__ == "__main__":
    import sys

    P = np.load(sys.argv[1])
    fps = float(sys.argv[2])
    bp = sys.argv[3]
    out = apply_jiggle(P, fps, bp)
    np.save(sys.argv[4], out)
    print("jiggled", P.shape, "->", sys.argv[4])
