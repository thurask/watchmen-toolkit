"""jiggle_d6: FILE-ONLY jiggle pass -- NxD6 swing-soft-limit pendulum integrator.

Drop-in for jiggle_pass.apply_jiggle (same signature); replaces the capture-fit
AR(2) params (jiggle_params.npz) with pure file-side data:

  spring/damping/limit : GameEssentials.fragment PhysicsWorld node
                         (m_n{breast,belly,hair}springconstant/springdamping/
                          distancelimit) + gravity + physicsIntegrationRateInHz.
  geometry             : bind npz (anchor = parentFrame . tb[bone]; lever r = tb).

Engine model (decomp 2026-07-09c + 2026-07-12 session, ENGINE_CONSTANTS.md):
  - Per jiggle bone a 0.1^3 MockupBox rigid body (RigidBody::SetMass=0x4fe514,
    called with 0.1 in setup FUN_006574cd) hangs off the parent bone via an
    NxD6Joint: translation locked -> angular pendulum about the parent anchor
    at radius |tb|; swing soft-limits carry the spring (Swing1LimitValue=45deg
    is never reached under the distance clamp -- breast asin(0.08/0.346)=13.4
    deg -- so the always-engaged (Swing2LimitValue=0) restoring spring
    dominates and the pendulum is integrated isotropically).
  - Gravity: PhysicsWorld ctor default (0,-9.82,0) @0xa26418, OVERRIDDEN by
    GameEssentials.fragment to (0,-14.82,0).  World -Y.
  - Sim tick: physicsIntegrationRateInHz (60), semi-implicit Euler.
  - Effective dynamics (capture-fit AR(2) cross-check): x'' = -K x - D x' +
    r x f - alpha_parent, K = k_file (fit 166-170 vs 200), D = 2*d_file*
    sqrt(K) (fit 17.9-19.4 vs 22.6).  The r x f (NOT (rhat x f)/|r|) coupling
    is pinned by the fitted C force-block magnitude ~|r|~0.35 and matches the
    engine RigidBody's unit-inertia-tensor space (GetUnitInertiaTensorMSG);
    the fitted C alpha-block diagonal ~ -1 pins the -alpha_parent term.
  - GAME-side clamp (CharacterAddonCtrl update FUN_006563a0, per-record ebx):
    delta = bodyPos-anchor [+0x60], len [+0x6c] vs limit [ebx+4]; if over,
    t = limit/len [+0x70], pos = anchor + delta*t AND quat = slerp(anchorQ,
    bodyQ, t) via FUN_0041fd54 (verified slerp).  In reduced rotvec state
    both collapse to x *= t.  Replaces jiggle_pass's tanh soft clamp.

Damping-domain note: NxJointLimitSoftDesc damping (0.8) is written torque-
domain in the desc, but the capture-fit response shows the solver's emergent
behaviour is k acceleration-domain with damping acting as a ratio zeta ~
d_file.  Both hypotheses are implemented; 'ratio' is the default and the QA
comparison (claude/work_E/validate_jiggle_d6.py) supports it.

Usage: from jiggle_d6 import apply_jiggle;  apply_jiggle(P, fps, bind_npz)
"""

import numpy as np, os, json, math

_PDIR = os.path.dirname(os.path.abspath(__file__))
_FRAG_CANDIDATES = ("extracted/TNT/Production/Fragments/GameEssentials.fragment.json",)

# GameEssentials.fragment file values (every install ships them in game.naz;
# kept here only as a fallback when no extract dir is available).
_FILE_DEFAULTS = {
    "gravity": (0.0, -14.82, 0.0),
    "rate_hz": 60,
    "breast": dict(k=200.0, d=0.8, limit=0.08),
    "belly": dict(k=70.0, d=0.8, limit=0.1),
    "hair": dict(k=100.0, d=0.8, limit=0.3),
}


def load_world_props(extract_root=None):
    """PhysicsWorld jiggle props from the extractor's GameEssentials fragment
    JSON.  extract_root = extractor outdir (e.g. '20260708').  Falls back to
    the recorded file values."""
    roots = [extract_root] if extract_root else []
    roots += [os.path.join(_PDIR, "..", "20260708"), os.path.join(_PDIR, "..")]
    for r in roots:
        if not r:
            continue
        for c in _FRAG_CANDIDATES:
            p = os.path.join(r, c)
            if not os.path.exists(p):
                continue
            try:
                j = json.load(open(p))
            except Exception:
                continue
            for n in j.get("nodes_full", []):
                pr = {q[0]: q[2] for q in n.get("props", [])}
                if pr.get("name") != "PhysicsWorld":
                    continue
                out = dict(_FILE_DEFAULTS)
                out["gravity"] = tuple(pr.get("gravity", out["gravity"]))
                out["rate_hz"] = int(pr.get("physicsIntegrationRateInHz", out["rate_hz"]))
                for g in ("breast", "belly", "hair"):
                    out[g] = dict(
                        k=float(pr.get("m_n%sspringconstant" % g, _FILE_DEFAULTS[g]["k"])),
                        d=float(pr.get("m_n%sspringdamping" % g, _FILE_DEFAULTS[g]["d"])),
                        limit=float(pr.get("m_n%sdistancelimit" % g, _FILE_DEFAULTS[g]["limit"])),
                    )
                return out
    return dict(_FILE_DEFAULTS)


def _group(bone):
    b = bone.lower()
    if "breast" in b:
        return "breast"
    if "belly" in b or "jiggle" in b:
        return "belly"
    if "hair" in b or "ponytail" in b:
        return "hair"
    return None


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


def solver_soften(k, zeta, dts=1.0 / 120.0):
    """PhysX implicit soft-constraint discretization: an implicit spring
    (k, d=2*zeta*sqrt(k)) solved at substep dts responds like an explicit
    spring with k/(1+d*dts+k*dts^2), d/(1+d*dts+k*dts^2).  At dts=1/120
    (60Hz frame, 2 solver substeps) the file constants k=200 zeta=0.8 land
    EXACTLY on the capture-fit AR(2) values (k 166.3 vs fit 166-170,
    d 18.8 vs fit 17.9-19.4) -- this is the decoded engine discretization."""
    d = 2.0 * zeta * math.sqrt(k)
    den = 1.0 + d * dts + k * dts * dts
    return k / den, d / den


def _q2m(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


_SKEL_ASSETS = {
    "female": "Female_Skeleton.model",
    "bs2": "Female_Skeleton.model",
    "gimp": "Large_Gimp_Skeleton.model",
}


def joint_frames(bindpath, naz="game.naz"):
    """FILE-SIDE D6 swing axes per jiggle bone, in the parent-local (x) frame.
    Reads EmbeddedJointNode type-7 records from the skeleton .model in the naz
    (parse_node_aux, 2026-07-12c field-order fix: [pos][a][a'][quat]).  Joint
    quats are model-space (conj-FK); mirrored breast pair verified.  Axes:
    X=twist (outward), Y=swing1 (FREE to 45deg), Z=swing2 (always-sprung).
    Matching: per jiggle bone, the parent-node joint whose model-space twist
    axis best aligns with the bone's bind offset direction.  Cached npz next
    to the bind.  Returns {bone: (y_axis, z_axis)} or {} if unavailable."""
    import re

    m = re.search(r"bind_(\w+?)_file", os.path.basename(bindpath))
    key = m.group(1) if m else None
    asset = _SKEL_ASSETS.get(key)
    if not asset:
        return {}
    cache = os.path.join(os.path.dirname(bindpath), "jointframes_v2_%s.npz" % key)
    if os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        return {str(n): (y, zz) for n, y, zz in zip(z["names"], z["yaxes"], z["zaxes"])}
    try:
        import watchmenlib as W, parse_model_nodes as PMN, struct

        hdr = None
        for bk, b in W.grab_blocks(naz).items():
            if "h" not in b:
                continue
            for e, h, st in W.extract_block(b["h"], b.get("s")):
                if (e.name or "").endswith(asset):
                    hdr = h
                    break
            if hdr:
                break
        if hdr is None:
            return {}
        bt = np.load(bindpath, allow_pickle=True)
        Rb = bt["Rb"].astype(np.float64)
        tb = bt["tb"].astype(np.float64)
        names = [str(n) for n in bt["names"]]
        par = bt["par"]
        occ = [(o, nm) for o, nm in PMN._names(hdr) if "/" not in nm and nm != "ModelRes"]
        aux = {}
        for i, (o, nm) in enumerate(occ):
            nl = struct.unpack_from("<I", hdr, o)[0]
            end = occ[i + 1][0] - 28 if i + 1 < len(occ) else len(hdr)
            r = PMN.parse_node_aux(hdr, o + 4 + nl, end)
            if r and r["joints"]:
                aux.setdefault(nm, []).extend(r["joints"])
        out = {}
        for bone in names:
            if not _group(bone):
                continue
            k = names.index(bone)
            p = par[k]
            if p < 0 or names[p] not in aux:
                continue
            tdir = Rb[p] @ tb[k]
            tdir /= max(np.linalg.norm(tdir), 1e-9)
            best = None
            for j in aux[names[p]]:
                for conj in (False, True):  # mirrored side = conjugate frame
                    q = j["quat"].astype(np.float64).copy()
                    if conj:
                        q[:3] *= -1
                    Rj = _q2m(q)
                    s = float(Rj[:, 0] @ tdir)
                    if best is None or s > best[0]:
                        best = (s, Rj)
            if best is None or best[0] < 0.2:
                continue
            Rl = Rb[p].T @ best[1]  # model -> parent-local
            out[bone] = (Rl[:, 1].copy(), Rl[:, 2].copy())
        np.savez(
            cache,
            names=list(out.keys()),
            yaxes=[v[0] for v in out.values()],
            zaxes=[v[1] for v in out.values()],
        )
        return out
    except Exception as e:
        print("jiggle_d6: joint_frames unavailable (%s)" % e)
        return {}


def apply_jiggle(
    P,
    fps,
    bindpath,
    bones=None,
    gain=None,
    mode="engine",
    props=None,
    extract_root=None,
    frames=None,
    free_damp=0.05,
    naz="game.naz",
):
    """P: (F,nbones,3,4) world palettes; fps: clip rate; bindpath: bind npz.
    mode: 'engine'   -- file k,zeta + solver_soften (capture-exact k,d; default)
          'aniso'    -- EXPERIMENTAL anisotropic wedge -- TESTED AND REJECTED
                        2026-07-12c: a force-free swing1 axis is gravity-
                        unstable (idle drifts to the distance clamp ~10deg vs
                        capture 1.4deg) for BOTH axis assignments.  PhysX's
                        eccentric elliptic cone (swing2max=0) acts as a SINGLE
                        combined near-isotropic swing constraint => 'engine'
                        mode is the correct file-only model.  The capture-fit
                        C weak middle row = the LOCKED TWIST DOF along rhat
                        (parent-local rhat ~ (-0.27,0.94,0.19), Y-dominated),
                        not a free swing.  Kept for reference/experiments.
          'ratio'    -- D = 2*d_file*sqrt(K), no softening
          'absolute' -- D = d_file raw torque-domain reading
    gain kept for interface parity (scales deviation; default 1).
    KNOWN GAP: dynamic amplitude ~1.4-1.5x below capture-fit AR(2)+gain on
    run/dance (statics match exactly; a x2 visual double-cover matches
    dynamics but doubles statics -> rejected).  Needs raw-capture window
    validation; see ENGINE_CONSTANTS.md handoff."""
    bt = np.load(bindpath, allow_pickle=True)
    Rb = bt["Rb"].astype(np.float64)
    tb = bt["tb"].astype(np.float64)
    names = [str(n) for n in bt["names"]]
    par = bt["par"]
    W = props or load_world_props(extract_root)
    g_world = np.array(W["gravity"], np.float64)
    hz = float(W["rate_hz"])
    dt = 1.0 / hz
    if gain is None:
        gain = 1.0
    if bones is None:
        bones = [n for n in names if _group(n)]
    F = len(P)
    if F < 4:
        return P
    if mode == "aniso" and frames is None:
        frames = joint_frames(bindpath, naz)
    P = np.array(P, dtype=np.float64, copy=True)
    dur = F / max(fps, 1e-6)
    N = max(4, int(round(dur * hz)))  # sim on the engine 60Hz grid
    t_o = np.arange(F) / fps
    t_n = np.clip(np.arange(N) / hz, 0, t_o[-1])
    for bone in bones:
        if bone not in names:
            continue
        k = names.index(bone)
        p = par[k]
        if p < 0:
            continue
        grp = _group(bone)
        if not grp:
            continue
        kf, df, lim = W[grp]["k"], W[grp]["d"], W[grp]["limit"]
        if mode in ("engine", "aniso"):
            K, D = solver_soften(kf, df)
        elif mode == "ratio":
            K = kf
            D = 2.0 * df * math.sqrt(K)
        else:
            K, D = kf, df
        r = tb[k]
        rlen = float(np.linalg.norm(r))
        if rlen < 1e-6:
            continue
        rhat = r / rlen
        # parent world rot + anchor
        A_o = np.einsum("fab,bc->fac", P[:, p, :, :3], Rb[p])
        anch_o = np.einsum("fab,b->fa", P[:, p, :, :3], tb[k]) + P[:, p, :, 3]
        # derivatives on the ORIGINAL clip grid (per-second units) -- taking
        # them after upsampling turns linear-interp knots into accel impulses
        acc_o = np.zeros_like(anch_o)
        acc_o[1:-1] = (anch_o[2:] - 2 * anch_o[1:-1] + anch_o[:-2]) * fps * fps
        dA_o = np.zeros_like(A_o)
        dA_o[1:-1] = (A_o[2:] - A_o[:-2]) * (fps / 2.0)
        S = np.einsum("fba,fbc->fac", A_o, dA_o)
        wvel_o = np.stack([S[:, 2, 1], S[:, 0, 2], S[:, 1, 0]], 1)
        walp_o = np.zeros_like(wvel_o)
        walp_o[1:-1] = (wvel_o[2:] - wvel_o[:-2]) * (fps / 2.0)
        # net specific force in parent frame (gravity - anchor accel)
        f_o = np.einsum("fba,fb->fa", A_o, g_world[None, :] - acc_o)
        # drive: unit-inertia torque r x f + inertial rotation term -alpha
        drv_o = np.cross(np.broadcast_to(r, f_o.shape), f_o) - walp_o
        drv_o -= np.einsum("fa,a->f", drv_o, rhat)[:, None] * rhat
        # resample drive to the sim grid
        drv = np.empty((N, 3))
        for j, tj in enumerate(t_n):
            i = min(int(tj * fps), F - 2)
            w = tj * fps - i
            drv[j] = (1 - w) * drv_o[i] + w * drv_o[i + 1]
        # semi-implicit Euler @ engine rate + engine radial clamp
        x = np.zeros((N, 3))
        v = np.zeros(3)
        xi = np.zeros(3)
        max_x = lim / rlen
        ax = frames.get(bone) if (mode == "aniso" and frames) else None
        if ax is not None:
            yh, zh = ax
            yh = yh - (yh @ rhat) * rhat
            yh /= max(np.linalg.norm(yh), 1e-9)
            zh = zh - (zh @ rhat) * rhat
            zh /= max(np.linalg.norm(zh), 1e-9)
            SW1 = math.radians(45.0)
        for i in range(1, N):
            if ax is not None:
                x2 = xi @ zh
                v2 = v @ zh  # swing2: sprung + damped
                x1 = xi @ yh
                v1 = v @ yh  # swing1: free inside 45deg
                s1 = K * (abs(x1) - SW1) * np.sign(x1) + D * v1 if abs(x1) > SW1 else free_damp * v1
                acc = drv[i - 1] - (K * x2 + D * v2) * zh - s1 * yh
                v += dt * acc
            else:
                v += dt * (drv[i - 1] - K * xi - D * v)
            xi = xi + dt * v
            n = np.linalg.norm(xi)
            if n > max_x:  # FUN_006563a0 clamp+slerp
                t = max_x / n
                xi = xi * t
                v = v * t
            x[i] = xi
        x *= gain
        # back to clip grid + apply (same convention as jiggle_pass)
        for i, ti in enumerate(t_o):
            j = min(int(ti * hz), N - 2)
            w = ti * hz - j
            xw = (1 - w) * x[j] + w * x[j + 1]
            Ai = A_o[i]
            Dm = Ai @ _rotv2m(xw) @ Ai.T
            P[i, k, :, :3] = Dm @ P[i, k, :, :3]
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
    print("jiggled(d6)", P.shape, "->", sys.argv[4])
