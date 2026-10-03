"""jiggle_d6: FILE-ONLY jiggle pass -- NxD6 swing-soft-limit pendulum integrator.

Drop-in for jiggle_pass.apply_jiggle (same signature); replaces the capture-fit
AR(2) params (jiggle_params.npz) with pure file-side data:

  spring/damping/limit : GameEssentials.fragment PhysicsWorld node
                         (m_n{breast,belly,hair}springconstant/springdamping/
                          distancelimit) + gravity + physicsIntegrationRateInHz.
  geometry             : bind npz (pivot = parent bone origin; lever = tloc[bone]).

Two models, selected with apply_jiggle(..., model=):

'pivot' (opt-in, 2026-10; exe re-read + capture re-measurement; the default is
'pinned', described further down):
  - Setup 0x6574cd: per addon (Spine2->BreastL/R, Spine->JiggleBelly, Head->Hair)
    a kinematic 0.1 m anchor box on the PARENT bone and a dynamic 0.8 m box of
    mass 0.1 on the jiggle bone; RigidBody ctor 0x4fe311 leaves angular damping
    1.0 and 4 solver iterations.  The D6 joint (0x648858) lives in the anchor
    box's frame = parent bone frame: X/Y/Z translation and twist (about X)
    locked, swing about Y/Z on soft limits (spring k, damping d verbatim).
  - Update 0x6563a0: the body pose relative to the anchor box REPLACES the
    bone's local position and rotation (no gain); clamp on the bone-origin
    displacement in metres (pos lerp + quat slerp by limit/len); gravity is
    cancelled by ApplyForce(-m*g) each frame; the body pose read at a frame is
    the previous physics result -> one frame of latency.
  - PhysX step 1/physicsIntegrationRateInHz (FUN_004f4d20), up to 3 per frame.
  - Swing dynamics x'' = -K x - D x' + (m/I) r x f - alpha_parent, r = the
    parent->bone offset, I = cube inertia about the pivot, f = -pivot accel.
    K, D are NOT derivable from the exe (PhysXCore); mode='capture' uses the
    values measured on the capture palettes, mode='engine' the file k, d
    through solver_soften at 1/60 s.

'pinned' (the model shipped up to 1.3.x, kept for comparison):
  - joint pinned at the bone origin, lever r = tb (bone position from the model
    origin), drive r x (g - a) - alpha with gravity (0,-14.82,0), K/D from
    solver_soften at 1/120 s (166.3 / 18.8), angle clamp limit/|tb|.  The 1/120
    "capture-exact" match came from reading the capture at 30 fps; at the
    clip-matched 55 fps the capture fit is K ~ 570, D ~ 37.5 (breast).

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
    """LEGACY input of the rejected mode='aniso' only.  The "type-7 joint
    records" read here are the node's collision CAPSULES (skeleton_records
    module docstring), not D6 joint frames; the real jiggle joint frame is the
    parent bone frame (0x648858).  Kept so mode='aniso' still runs.
    Original description: D6 swing axes per jiggle bone, in the parent-local frame.
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


def _apply_jiggle_pinned(
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
            K, D = solver_soften(kf, df, dts=0.5 / hz)  # PhysX: 2 substeps per step
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
            # 2026-08-17: clamp w -- on clips faster than the sim grid (4x
            # dense bakes, fps > hz) the tail frames extrapolated past x[N-1]
            # and could overshoot the engine distance clamp.
            w = min(ti * hz - j, 1.0)
            xw = (1 - w) * x[j] + w * x[j + 1]
            Ai = A_o[i]
            Dm = Ai @ _rotv2m(xw) @ Ai.T
            P[i, k, :, :3] = Dm @ P[i, k, :, :3]
            jw = anch_o[i]
            P[i, k, :, 3] = jw - P[i, k, :, :3] @ tb[k]
    return P.astype(np.float32)


# --- engine "pivot" model (2026-10: exe re-read, findings/jiggle.md) ---------
# Simulated body: the 0.8 m MockupBox of mass 0.1 (setup 0x6574cd: size props
# f32 @0xa06d84, RigidBody::SetMass 0x4fe514 with f32 @0x9e664c); the 0.1 m box
# is the kinematic anchor that follows the parent bone.
BODY_MASS = 0.1
BODY_SIZE = 0.8
# RigidBody ctor 0x4fe311: angularDamping [+0xa8] = 1.0 (fld1), solver iterations 4.
BODY_ANGULAR_DAMPING = 1.0

# Effective swing stiffness / damping (s^-2, s^-1) measured on the capture
# palettes with the pivot model's own state definition (see jiggle_capture_fit
# notes in docs): NOT derivable from the exe (PhysXCore soft-limit solver).
# Time base: capture frame = 1/55 s (clip-matched playback rate).
_CAPTURE_FIT = {
    "breast": dict(K=570.0, D=37.5),
    "belly": dict(K=308.0, D=19.2),
}

MODELS = ("pivot", "pinned")
# "pinned" = the model of 1.2.0 (joint pinned at the bone origin, lever |tb|,
# gravity drive, angle clamp) and the DEFAULT: its output is bit-identical to
# 1.2.0.  "pivot" follows the engine geometry read from the exe, but its swing
# constants (mode 'capture') are fitted to captures at an estimated frame rate,
# so it is opt-in: apply_jiggle(model="pivot"), `--jiggle-model pivot`.
DEFAULT_MODEL = "pinned"
DEFAULT_MODE = {"pivot": "capture", "pinned": "engine"}


# bump when a model's arithmetic changes in a way its constants do not show
MODEL_REVISION = {"pinned": 1, "pivot": 1}


def resolve_model(model=None, mode=None):
    """(model, mode) with the defaults filled in; ValueError on an unknown model."""
    if model is None:
        model = DEFAULT_MODEL
    if model not in MODELS:
        raise ValueError(
            "unknown jiggle model %r (expected one of %s)" % (model, ", ".join(MODELS))
        )
    return model, (DEFAULT_MODE[model] if mode is None else mode)


def cache_signature(model=None, mode=None):
    """Short tag naming everything a baked jiggle depends on besides the clip and
    the bind: model, constants mode and the constants themselves.  Used in the
    name of on-disk jiggle caches (characters_export), so palettes baked with one
    model or one set of constants are never served for another."""
    import hashlib

    model, mode = resolve_model(model, mode)
    consts = repr(
        (
            sorted((g, sorted(v.items())) for g, v in _CAPTURE_FIT.items()),
            BODY_MASS,
            BODY_SIZE,
            BODY_ANGULAR_DAMPING,
            MODEL_REVISION[model],
        )
    )
    return "%s-%s-%s" % (model, mode, hashlib.md5(consts.encode()).hexdigest()[:8])


def _slerp_m(Ra, Rb_, t):
    """Rotation-matrix slerp Ra -> Rb_ (shortest path)."""
    M = Ra.T @ Rb_
    v = np.array([M[2, 1] - M[1, 2], M[0, 2] - M[2, 0], M[1, 0] - M[0, 1]])
    c = min(1.0, max(-1.0, (np.trace(M) - 1.0) / 2.0))
    a = math.acos(c)
    s = np.linalg.norm(v)
    if a < 1e-9 or s < 1e-12:
        return Rb_.copy() if t >= 0.5 else Ra.copy()
    return Ra @ _rotv2m(v / s * (a * t))


def swing_constants(mode, grp, W, model="pivot"):
    """(K, D) of the swing spring for one addon group.
    'engine'   -- file k, zeta through solver_soften at the PhysX substep
                  (pivot: 1/rate_hz, FUN_004f4d20; pinned: historical 0.5/rate_hz)
    'capture'  -- pivot only: capture-measured effective constants (_CAPTURE_FIT)
    'ratio'    -- D = 2*d_file*sqrt(K), no softening
    'absolute' -- D = d_file
    props[grp] may carry explicit 'K_eff' / 'D_eff' overrides (fitting harness)."""
    g = W[grp]
    kf, df = g["k"], g["d"]
    hz = float(W["rate_hz"])
    if mode in ("engine", "aniso", "capture"):
        if model == "pinned":
            K, D = solver_soften(kf, df, dts=0.5 / hz)
        elif mode == "capture" and grp in _CAPTURE_FIT:
            K, D = _CAPTURE_FIT[grp]["K"], _CAPTURE_FIT[grp]["D"]
        else:
            K, D = solver_soften(kf, df, dts=1.0 / hz)
            D += BODY_ANGULAR_DAMPING
    elif mode == "ratio":
        K = kf
        D = 2.0 * df * math.sqrt(K)
    else:
        K, D = kf, df
    return float(g.get("K_eff", K)), float(g.get("D_eff", D))


def _lerp_rows(arr, tq, fps):
    """Linear resample of a per-clip-frame array at times tq (seconds)."""
    F = len(arr)
    u = np.clip(np.asarray(tq, np.float64) * fps, 0.0, F - 1.0)
    i = np.minimum(u.astype(int), F - 2)
    w = (u - i).reshape((-1,) + (1,) * (arr.ndim - 1))
    return (1.0 - w) * arr[i] + w * arr[i + 1]


def _apply_jiggle_pivot(P, fps, bindpath, bones, gain, mode, props, extract_root, latency):
    """Engine-geometry model.  Per addon (CharacterAddonCtrl 0x6574cd / 0x648858 /
    0x6563a0):
      * the body swings about the PARENT bone origin (joint frame = anchor box =
        parent bone; X twist locked, Y/Z swing), lever = parent->bone offset;
      * its pose replaces the bone's local position AND rotation (0x6563a0 ->
        FUN_004ba7ad), i.e. the palette is rotated about the parent origin;
      * gravity is cancelled every frame by ApplyForce(-m*g) (0x656fb4-0x65707c);
      * the clamp is on the bone-ORIGIN displacement in metres, pos lerp +
        quat slerp by limit/len (0x6563a0, FUN_0041fd54); the body itself is
        not clamped;
      * the body pose read at a frame is the previous physics result while the
        anchor is already at the current parent pose -> one frame of latency
        (order of 0x6563a0; capture: twist-axis deviation = 1.05 x one-frame
        parent rotation, R2 0.93)."""
    bt = np.load(bindpath, allow_pickle=True)
    Rb = bt["Rb"].astype(np.float64)
    tb = bt["tb"].astype(np.float64)
    names = [str(n) for n in bt["names"]]
    par = bt["par"]
    tloc = bt["tloc"].astype(np.float64) if "tloc" in bt.files else None
    W = props or load_world_props(extract_root)
    hz = float(W["rate_hz"])
    dt = 1.0 / hz
    if gain is None:
        gain = 1.0
    if latency is None:
        latency = dt
    if bones is None:
        bones = [n for n in names if _group(n)]
    F = len(P)
    if F < 4:
        return P
    P = np.array(P, dtype=np.float64, copy=True)
    P0 = P.copy()  # animated input (several jiggle bones may share a parent)
    dur = F / max(fps, 1e-6)
    N = max(4, int(round(dur * hz)))
    t_o = np.arange(F) / fps
    t_n = np.clip(np.arange(N) / hz, 0, t_o[-1])
    icm = BODY_MASS * BODY_SIZE * BODY_SIZE / 6.0  # solid cube about its centre
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
        lim = W[grp]["limit"]
        K, D = swing_constants(mode, grp, W, "pivot")
        # lever in the parent bone frame (bind npz tloc; == Rb_p^T (tb_k - tb_p))
        r = tloc[k] if tloc is not None else Rb[p].T @ (tb[k] - tb[p])
        rlen = float(np.linalg.norm(r))
        if rlen < 1e-6:
            continue
        acc_gain = BODY_MASS / (icm + BODY_MASS * rlen * rlen)  # m / I about the pivot
        A_o = np.einsum("fab,bc->fac", P0[:, p, :, :3], Rb[p])  # parent bone frame
        c_o = np.einsum("fab,b->fa", P0[:, p, :, :3], tb[p]) + P0[:, p, :, 3]  # pivot
        # derivatives on the ORIGINAL clip grid (see the pinned model's note)
        acc_o = np.zeros_like(c_o)
        acc_o[1:-1] = (c_o[2:] - 2 * c_o[1:-1] + c_o[:-2]) * fps * fps
        dA_o = np.zeros_like(A_o)
        dA_o[1:-1] = (A_o[2:] - A_o[:-2]) * (fps / 2.0)
        S = np.einsum("fba,fbc->fac", A_o, dA_o)
        wvel_o = np.stack([S[:, 2, 1], S[:, 0, 2], S[:, 1, 0]], 1)
        walp_o = np.zeros_like(wvel_o)
        walp_o[1:-1] = (wvel_o[2:] - wvel_o[:-2]) * (fps / 2.0)
        # no gravity term: cancelled by the per-frame -m*g force
        f_o = np.einsum("fba,fb->fa", A_o, -acc_o)
        drv_o = acc_gain * np.cross(np.broadcast_to(r, f_o.shape), f_o) - walp_o
        drv_o[:, 0] = 0.0  # TwistMotionType = Locked about joint X (0x51795e)
        drv = _lerp_rows(drv_o, t_n, fps)
        x = np.zeros((N, 3))
        v = np.zeros(3)
        xi = np.zeros(3)
        for i in range(1, N):
            v = v + dt * (drv[i - 1] - K * xi - D * v)
            xi = xi + dt * v
            n = np.linalg.norm(xi)
            if not np.isfinite(n) or n > math.pi:  # numerical guard, not an engine limit
                xi = np.zeros(3) if not np.isfinite(n) else xi * (math.pi / n)
                v = np.zeros(3)
            x[i] = xi
        x *= gain
        # write-back: body = lagged anchor swung about the lagged pivot
        t_l = np.clip(t_o - latency, 0.0, None)
        xs = _lerp_rows(x, t_l, hz)
        Pp_l = _lerp_rows(P0[:, p], t_l, fps)
        for i in range(F):
            Rp = _orth(Pp_l[i, :, :3])
            Al = Rp @ Rb[p]
            cl = Rp @ tb[p] + Pp_l[i, :, 3]
            Dm = Al @ _rotv2m(xs[i]) @ Al.T
            Rbody = Dm @ Rp
            org_body = cl + Dm @ (Rp @ tb[k] + Pp_l[i, :, 3] - cl)
            Ra = P0[i, k, :, :3]
            org_anim = Ra @ tb[k] + P0[i, k, :, 3]
            delta = org_body - org_anim
            ln = float(np.linalg.norm(delta))
            if ln > lim:  # 0x6563a0: pos = p0 + delta*t, quat = slerp(q0, q, t)
                t = lim / ln
                org_body = org_anim + delta * t
                Rbody = _slerp_m(_orth(Ra), Rbody, t)
            P[i, k, :, :3] = Rbody
            P[i, k, :, 3] = org_body - Rbody @ tb[k]
    return P.astype(np.float32)


def apply_jiggle_legacy(P, fps, bindpath, **kw):
    """The pre-2026-10 'pinned' model (apply_jiggle(..., model='pinned'))."""
    kw.pop("model", None)
    return apply_jiggle(P, fps, bindpath, model="pinned", **kw)


def apply_jiggle(
    P,
    fps,
    bindpath,
    bones=None,
    gain=None,
    mode=None,
    props=None,
    extract_root=None,
    frames=None,
    free_damp=0.05,
    naz="game.naz",
    model=None,
    latency=None,
):
    """P: (F,nbones,3,4) world palettes; fps: clip rate; bindpath: bind npz.
    model: 'pivot'  -- engine geometry (parent-origin pivot, parent->bone lever,
                       position+rotation write-back, metre clamp, no gravity,
                       twist locked, one-frame latency); see _apply_jiggle_pivot
           'pinned' -- previous model (see _apply_jiggle_pinned)
           None     -- DEFAULT_MODEL
    mode:  spring constants, see swing_constants ('aniso' is pinned-only);
           None = DEFAULT_MODE[model].
    latency: pivot only, seconds the body trails the parent (None = 1/rate_hz,
             0 disables).
    gain scales the deviation (default 1)."""
    model, mode = resolve_model(model, mode)
    if mode == "capture" and model == "pinned":
        raise ValueError("mode='capture' constants belong to model='pivot'")
    if model == "pinned" or mode == "aniso":
        return _apply_jiggle_pinned(
            P, fps, bindpath, bones, gain, mode, props, extract_root, frames, free_damp, naz
        )
    return _apply_jiggle_pivot(P, fps, bindpath, bones, gain, mode, props, extract_root, latency)


if __name__ == "__main__":
    import sys

    P = np.load(sys.argv[1])
    fps = float(sys.argv[2])
    bp = sys.argv[3]
    out = apply_jiggle(P, fps, bp)
    np.save(sys.argv[4], out)
    print("jiggled(d6)", P.shape, "->", sys.argv[4])
