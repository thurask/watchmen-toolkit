"""jiggle_d6: FILE-ONLY jiggle pass -- NxD6 swing-soft-limit pendulum integrator.

Drop-in for jiggle_pass.apply_jiggle (same signature); replaces the capture-fit
AR(2) params (jiggle_params.npz) with pure file-side data:

  spring/damping/limit : GameEssentials.fragment PhysicsWorld node
                         (m_n{breast,belly,hair}springconstant/springdamping/
                          distancelimit) + gravity + physicsIntegrationRateInHz.
  geometry             : bind npz (pivot = parent bone origin; lever = tloc[bone]).

Three models, selected with apply_jiggle(..., model=):

'solver' (DEFAULT_MODEL; PhysXCore.dll 2.8.1.1 read, findings/physx_d6.md):
  - the joint has no drive (game 0x5146ec: every driveType 0); spring and damping
    are the soft SWING LIMITS (45 deg / 0 deg), which PhysX turns into one cone
    limit of radius 0: a unilateral soft row on tan(swing/4) (0x10227db0);
  - SoftLimitJoint steps the body exactly as the DLL's row arithmetic does (soft
    row 0x102068b0, 4 iterations 0x1022ce80, conclude pass 0x1022d500, pose from
    the pre-conclude velocity 0x102008a0), with the FILE's k and d and nothing
    fitted; geometry, write-back, metre clamp and one-frame delay as 'pivot';
  - a clip the game loops (loop=True) is baked as a closed lap of its settled
    motion; any other clip starts with the parent already moving at its
    frame-0 velocity (see _apply_jiggle_solver).

'pivot' (opt-in, 2026-10; exe re-read + capture re-measurement):
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
    K, D here are a linear fit, not the game's law (the joint is a PhysX soft
    swing limit -- see the 'solver' model); mode='capture' uses the values
    measured on the capture palettes, mode='engine' the file k, d
    through solver_soften at 1/60 s.

'pinned' (opt-in; the default up to 1.3.0, output unchanged since 1.2.0):
  - joint pinned at the bone origin, lever r = tb (bone position from the model
    origin), drive r x (g - a) - alpha with gravity (0,-14.82,0), K/D from
    solver_soften at 1/120 s (166.3 / 18.8), angle clamp limit/|tb|.  The 1/120
    "capture-exact" match came from reading the capture at 30 fps; the
    'pivot' capture fit (K ~ 570, D ~ 37.5, breast) assumed 55 fps; the capture
    actually averaged about 64-65 fps with frames that ran no physics step.

Usage: from jiggle_d6 import apply_jiggle;  apply_jiggle(P, fps, bind_npz)
"""

import numpy as np, os, math
import exact_math as _em

_FRAG_CANDIDATES = ("extracted/TNT/Production/Fragments/GameEssentials.fragment.json",)

# GameEssentials.fragment PhysicsWorld values (equal in the six shipped sets, measured);
# used when no extract is named or its fragment has no PhysicsWorld node.
_FILE_DEFAULTS = {
    "gravity": (0.0, -14.82, 0.0),
    "rate_hz": 60,
    "breast": dict(k=200.0, d=0.8, limit=0.08),
    "belly": dict(k=70.0, d=0.8, limit=0.1),
    "hair": dict(k=100.0, d=0.8, limit=0.3),
}


def load_world_props(extract_root=None):
    """PhysicsWorld jiggle props from the GameEssentials fragment of the extract output
    `extract_root`; the shipped values (_FILE_DEFAULTS) when it is None or has no such
    node.  No other folder is looked in."""
    roots = [extract_root] if extract_root else []
    for r in roots:
        if not r:
            continue
        for c in _FRAG_CANDIDATES:
            p = os.path.join(r, c)
            if not (os.path.exists(p) or os.path.exists(p[:-5])):
                continue
            try:
                import kapow_json

                j = kapow_json.load_fragment(p)  # the binary first, never a stale JSON
            except Exception as e:
                print(
                    "WARNING: GameEssentials.fragment not read (%s): shipped PhysicsWorld"
                    " values used" % e
                )
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

MODELS = ("pivot", "pinned", "solver")
# "solver" steps the PhysX soft-limit row itself with the file constants: the DEFAULT.
# "pinned" = the model of 1.2.0 (joint pinned at the bone origin, lever |tb|,
# gravity drive, angle clamp), the default up to 1.3.0; its output is bit-identical
# to those releases: apply_jiggle(model="pinned"), `--jiggle-model pinned`.
# "pivot" follows the engine geometry read from the exe with a linear spring whose
# constants (mode 'capture') are fitted to captures at an estimated frame rate.
DEFAULT_MODEL = "solver"
DEFAULT_MODE = {"pivot": "capture", "pinned": "engine"}
SOLVER_MODE = "file"  # the one mode of "solver": file constants, nothing to choose


# bump when a model's arithmetic changes in a way its constants do not show
MODEL_REVISION = {"pinned": 1, "pivot": 1, "solver": 3}


def resolve_model(model=None, mode=None):
    """(model, mode) with the defaults filled in; ValueError on an unknown model."""
    if model is None:
        model = DEFAULT_MODEL
    if model not in MODELS:
        raise ValueError(
            "unknown jiggle model %r (expected one of %s)" % (model, ", ".join(MODELS))
        )
    return model, (DEFAULT_MODE.get(model, SOLVER_MODE) if mode is None else mode)


#: version of the on-disk jiggle cache KEY of the solver model (directory tag +
#: cache_file name).  2 = the clip's loop flag is part of the file name; the
#: directories of key 1 (`<clip>.npz` baked with whatever loop flag the first run
#: had) get another tag and are never read again.  The older models do not use the
#: loop flag, so their 1.3.0 tags stay.
CACHE_KEY_VERSION = 2


def cache_file(clip, model=None, loop=False):
    """File name of clip `clip`'s jiggled palette inside a cache directory
    (cache_signature): `<clip>.npz`, or `<clip>.loop.npz` for a solver bake of a
    clip the game loops.  The solver bakes a looping clip as a closed lap and any
    other clip from a lead-in (apply_jiggle `loop`), so the two results must not
    share a cache entry: the flag comes from the animation table, which can be
    missing on one run and present on the next."""
    model, _mode = resolve_model(model, None)
    return "%s%s.npz" % (clip, ".loop" if model == "solver" and loop else "")


def cache_signature(model=None, mode=None, props=None):
    """Short tag naming everything a baked jiggle depends on besides the clip and
    the bind: model, constants mode and the constants themselves.  Used in the
    name of on-disk jiggle caches (characters_export), so palettes baked with one
    model or one set of constants are never served for another.  props: the
    PhysicsWorld values the bake uses (load_world_props); they enter the tag when
    they differ from the shipped values (_FILE_DEFAULTS), so the tag of the shipped
    values is the one without them."""
    import hashlib

    model, mode = resolve_model(model, mode)
    world = _world_key(props)
    consts = (
        sorted((g, sorted(v.items())) for g, v in _CAPTURE_FIT.items()),
        BODY_MASS,
        BODY_SIZE,
        BODY_ANGULAR_DAMPING,
        MODEL_REVISION[model],
    )
    if model == "solver":  # its own constants; the tuples of the older models stay as 1.3.0
        consts = consts[1:] + (
            SOLVER_BIAS,
            SOLVER_ITERATIONS,
            SOLVER_LIMIT_TOL,
            SOLVER_Q_ZERO,
            SOLVER_LIN_DIRECT_SQ,
            SOLVER_MIN_DAMPING,
            SOLVER_LAMBDA_EPS,
            SOLVER_KIN_EPS,
            SOLVER_SWING1_DEG,
            SOLVER_SWING2_DEG,
            SOLVER_MAX_ANGULAR_VELOCITY,
            SOLVER_LEAD_IN,
            SOLVER_LOOP_TOL,
            SOLVER_LOOP_SETTLE,
            SOLVER_LOOP_MAX_LAPS,
            ("cache key", CACHE_KEY_VERSION),
        )
    if world is not None:
        consts = consts + (("world", world),)
    consts = repr(consts)
    return "%s-%s-%s" % (model, mode, hashlib.md5(consts.encode()).hexdigest()[:8])


def _world_key(props):
    """A canonical tuple of the PhysicsWorld values in `props`, None when they are the
    shipped ones (or `props` is None)."""
    if props is None:
        return None

    def canon(W):
        return (
            tuple(float(x) for x in W["gravity"]),
            int(W["rate_hz"]),
            tuple(
                (g, float(W[g]["k"]), float(W[g]["d"]), float(W[g]["limit"]))
                for g in ("breast", "belly", "hair")
            ),
        )

    key = canon(props)
    return None if key == canon(_FILE_DEFAULTS) else key


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


# --- 'solver' model (2026-10: PhysXCore.dll 2.8.1.1 read, findings/physx_d6.md) ---
# The jiggle joint has NO drive (game 0x5146ec: every driveType 0).  The file's spring
# and damping are the SOFT SWING LIMITS (swing1 45 deg, swing2 0 deg, both LIMITED); two
# limited swing axes form one cone limit of radius 0, i.e. one unilateral soft row.
# Constants below are read from PhysXCore.dll bytes; nothing here is fitted to captures.
SOLVER_BIAS = 0.7  # f32 @0x1029e1b8: row bias coefficient = m_eff * 0.7 (0x10227cba)
SOLVER_ITERATIONS = 4  # body solverIterationCount (game 0x4fe329; island max 0x10201412)
SOLVER_LIMIT_TOL = 0.025004999712109566  # f32 @0x102a0f84, in tan(angle/4) units
SOLVER_Q_ZERO = 9.999999747378752e-05  # f32 @0x1028089c: small q components -> 0
SOLVER_LIN_DIRECT_SQ = 1.1920928955078125e-07  # f32 @0x1028058c
SOLVER_MIN_DAMPING = 9.999999747378752e-06  # f32 @0x102808b4
SOLVER_LAMBDA_EPS = 1.000000013351432e-10  # f32 @0x102a10dc (conclude pass)
SOLVER_KIN_EPS = 9.999999974752427e-07  # f32 @0x102a1990 (kinematic angular deadband)
SOLVER_SWING1_DEG = 45.0  # game 0x648858: Swing1LimitValue (f32 @0x9fffa8)
SOLVER_SWING2_DEG = 0.0  # game 0x648858: Swing2LimitValue
SOLVER_MAX_ANGULAR_VELOCITY = 200.0  # game 0x4fe353 -> setMaxAngularVelocity (0x5072a4)
_FLT_MAX = 3.4028234663852886e38  # maxForce / maxTorque (game f32 @0xa2367c)
# Bake policy (not engine constants): how a clip is started, see _apply_jiggle_solver.
SOLVER_LEAD_IN = 0.25  # s of lead-in before frame 0 of a clip that does not loop
SOLVER_LOOP_TOL = 2e-5  # lap-to-lap change of the body state that counts as periodic
SOLVER_LOOP_SETTLE = 12.0  # s of laps after which a loop that keeps changing is recorded
SOLVER_LOOP_MAX_LAPS = 40


_MAX_W2 = SOLVER_MAX_ANGULAR_VELOCITY * SOLVER_MAX_ANGULAR_VELOCITY


def _q_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def _v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _q_mul(a, b):
    """Hamilton product, (x, y, z, w)."""
    return (
        a[3] * b[0] + a[0] * b[3] + a[1] * b[2] - a[2] * b[1],
        a[3] * b[1] - a[0] * b[2] + a[1] * b[3] + a[2] * b[0],
        a[3] * b[2] + a[0] * b[1] - a[1] * b[0] + a[2] * b[3],
        a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
    )


def _q_rot(q, v):
    x, y, z, w = q
    t = (2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0]))
    return (
        v[0] + w * t[0] + y * t[2] - z * t[1],
        v[1] + w * t[1] + z * t[0] - x * t[2],
        v[2] + w * t[2] + x * t[1] - y * t[0],
    )


def _q_axes(q):
    """Columns (X, Y, Z axes) of the rotation matrix of q."""
    x, y, z, w = q
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)),
        (2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)),
        (2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)),
    )


def _m2q(M):
    """Rotation matrix -> unit quaternion (x, y, z, w)."""
    t = M[0][0] + M[1][1] + M[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = ((M[2][1] - M[1][2]) / s, (M[0][2] - M[2][0]) / s, (M[1][0] - M[0][1]) / s, 0.25 * s)
    elif M[0][0] > M[1][1] and M[0][0] > M[2][2]:
        s = math.sqrt(1.0 + M[0][0] - M[1][1] - M[2][2]) * 2
        q = (0.25 * s, (M[0][1] + M[1][0]) / s, (M[0][2] + M[2][0]) / s, (M[2][1] - M[1][2]) / s)
    elif M[1][1] > M[2][2]:
        s = math.sqrt(1.0 + M[1][1] - M[0][0] - M[2][2]) * 2
        q = ((M[0][1] + M[1][0]) / s, 0.25 * s, (M[1][2] + M[2][1]) / s, (M[0][2] - M[2][0]) / s)
    else:
        s = math.sqrt(1.0 + M[2][2] - M[0][0] - M[1][1]) * 2
        q = ((M[0][2] + M[2][0]) / s, (M[1][2] + M[2][1]) / s, 0.25 * s, (M[1][0] - M[0][1]) / s)
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def _q_slerp(q0, q1, t):
    d = _q_dot(q0, q1)
    if d < 0:
        q1, d = (-q1[0], -q1[1], -q1[2], -q1[3]), -d
    a = _em.acos(min(1.0, d))
    if a < 1e-9:
        w0, w1 = 1.0 - t, t
    else:
        w0, w1 = _em.sin((1.0 - t) * a) / _em.sin(a), _em.sin(t * a) / _em.sin(a)
    q = tuple(w0 * q0[i] + w1 * q1[i] for i in range(4))
    n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


class SoftLimitJoint:
    """One jiggle addon as PhysX 2.8.1.1 steps it: a dynamic cube (body B) on a D6 joint
    to a kinematic anchor (body A, the parent bone).  x/y/z and twist locked, swing on a
    zero-radius soft cone limit with the file's spring k and damping d.

    The joint frame is the anchor frame (X twist, Y swing1, Z swing2; game 0x4a8dd5);
    B is given A's orientation at rest (its cube inertia is isotropic, so its own rest
    orientation does not enter).  Vectors are 3-tuples, quaternions (x, y, z, w) tuples."""

    def __init__(self, k, d, lever, dt=1.0 / 60.0, iterations=SOLVER_ITERATIONS):
        self.k, self.d, self.dt, self.iterations = float(k), float(d), float(dt), int(iterations)
        self.lever = tuple(float(c) for c in lever)
        self.inv_m = 1.0 / BODY_MASS
        # NxActor::updateMassFromShapes(0, mass) (game 0x50724a): solid cube about its centre
        self.inv_i = 6.0 / (BODY_MASS * BODY_SIZE * BODY_SIZE)
        # PxsD6Joint cache 0x10226580: limits kept as tan(angle / 4)
        self.l1 = _em.tan(_em.radians(SOLVER_SWING1_DEG) * 0.25)
        self.l2 = _em.tan(_em.radians(SOLVER_SWING2_DEG) * 0.25)
        self.reset((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))

    def reset(self, xa, qa):
        """Anchor at (xa, qa), body at rest on the lever."""
        self.xa, self.qa = tuple(xa), tuple(qa)
        r = _q_rot(self.qa, self.lever)
        self.xb = (self.xa[0] + r[0], self.xa[1] + r[1], self.xa[2] + r[2])
        self.qb = self.qa
        self.vb = (0.0, 0.0, 0.0)
        self.wb = (0.0, 0.0, 0.0)

    def _kinematic_velocity(self, xt, qt, nsub):
        """moveGlobalPose target -> velocity held for the nsub substeps (0x10034c10)."""
        h = nsub * self.dt
        va = tuple((xt[i] - self.xa[i]) / h for i in range(3))
        q = _q_mul(qt, (-self.qa[0], -self.qa[1], -self.qa[2], self.qa[3]))
        if q[3] < 0:
            q = (-q[0], -q[1], -q[2], -q[3])
        n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
        w = q[3] / n
        if abs(w - 1.0) > SOLVER_KIN_EPS and w < 1.0:
            f = (_em.acos(w) * 2.0 / h) / math.sqrt(1.0 - w * w) / n
            return va, (q[0] * f, q[1] * f, q[2] * f)
        return va, (0.0, 0.0, 0.0)  # below 0.16 deg the anchor rotation is not executed

    def _rows(self):
        """PxsD6Joint constraint setup 0x10227db0 for this configuration.  Each row is a
        list [lin, n, a, m, B, c, rhs, lo, hi, lam, lamv, limit]; blocks in buffer order."""
        dt, inv_i, inv_m = self.dt, self.inv_i, self.inv_m
        qb, qa = self.qb, self.qa
        x0, y0, z0 = _q_axes(qb)
        r0 = _q_rot(qb, (-self.lever[0], -self.lever[1], -self.lever[2]))
        dw = tuple(self.xa[i] - (self.xb[i] + r0[i]) for i in range(3))  # anchor separation
        d0 = (_v_dot(x0, dw), _v_dot(y0, dw), _v_dot(z0, dw))
        q = _q_mul((-qb[0], -qb[1], -qb[2], qb[3]), qa)  # frame 1 relative to frame 0
        q = tuple(0.0 if abs(c) < SOLVER_Q_ZERO else c for c in q)
        neg = q[3] < 0
        if neg:
            q = (-q[0], -q[1], -q[2], -q[3])
        n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
        q = (q[0] / n, q[1] / n, q[2] / n, q[3] / n)
        rows = []
        # twist LOCKED: axis 0x10226e60, rhs = -2 qx / dt, bilateral (0x1022b754)
        q1 = (-qa[0], -qa[1], -qa[2], -qa[3]) if neg else qa
        xx = qb[0] * q1[0]
        ax = (
            xx + xx + (q1[3] * qb[3] - (qb[2] * q1[2] + qb[1] * q1[1] + xx)),
            q1[1] * qb[0] + qb[1] * q1[0] + qb[3] * q1[2] + qb[2] * q1[3],
            (qb[0] * q1[2] + qb[2] * q1[0]) - q1[1] * qb[3] - q1[3] * qb[1],
        )
        resp = inv_i * _v_dot(ax, ax)  # 0x10227a70: 1 / (a . I^-1 . a), anchor has no response
        # (read: Body::setKinematic 0x10037f30 zeroes inverse mass, inverse inertia and damping;
        # body 0 = dynamic box = actor[0])
        m = 1.0 / resp if resp != 0.0 else 0.0
        rows.append(
            [False, None, ax, m, m * SOLVER_BIAS, 0.0, q[0] / dt * -2.0, -_FLT_MAX, _FLT_MAX]
        )
        # swing / twist split 0x10226ed0
        s = math.sqrt(q[0] * q[0] + q[3] * q[3])
        if s != 0.0:
            sy, sz, sw = (q[3] * q[1] - q[2] * q[0]) / s, (q[0] * q[1] + q[2] * q[3]) / s, s
        else:
            sy, sz, sw = q[1], q[2], q[3]
        # cone limit, swing1 and swing2 both LIMITED (0x1022bcf1 - 0x1022be9b)
        n2 = sz * sz + sy * sy
        if n2 != 0.0:
            fy, fz = (1.0 / n2) * sy * sy, (1.0 / n2) * sz * sz
            den = self.l1 * fz + fy * self.l2
            # limit radius; 0/0 is NaN in the DLL and a NaN limit emits no row (jp 0x1022bd7a)
            lim = (self.l1 * self.l2) / den if den != 0.0 else float("nan")
            e = math.sqrt(n2) / (sw + 1.0)  # tan(swing / 4)
            if lim - SOLVER_LIMIT_TOL < e:
                a = tuple(y0[i] * sy + z0[i] * sz for i in range(3))
                an = math.sqrt(_v_dot(a, a))
                a = (a[0] / an, a[1] / an, a[2] / an) if an > 0 else (0.0, 0.0, 0.0)
                resp = inv_i * _v_dot(a, a)
                m = 1.0 / resp if resp != 0.0 else 0.0
                b, c = m * SOLVER_BIAS, 0.0
                if self.k != 0.0:  # soft row 0x10227cde / 0x102068b0, force spring
                    dd = max(self.d, SOLVER_MIN_DAMPING)
                    kdt = self.k * dt
                    gamma = 1.0 / ((kdt + dd) * dt)  # 1 / (dt (d + k dt))
                    erp = kdt / (kdt + dd)
                    f = 1.0 / (m * gamma + 1.0)
                    c = m / (1.0 / gamma + m)  # NX_IMPROVED_SPRING_SOLVER (default 1)
                    b = b * erp * f
                    m = m * f
                rows.append([False, None, a, m, b, c, (lim - e) / dt, 0.0, _FLT_MAX])
        # x, y, z LOCKED (0x1022c5ef..): along the separation and two perpendiculars
        # (0x10227010) once |d|^2 > 1.19e-7, else along the joint axes
        if _v_dot(d0, d0) > SOLVER_LIN_DIRECT_SQ:
            dn = math.sqrt(_v_dot(dw, dw))
            n0 = (dw[0] / dn, dw[1] / dn, dw[2] / dn)
            if abs(n0[2]) <= 0.7071067690849304:
                f = math.sqrt(n0[0] * n0[0] + n0[1] * n0[1])
                b1 = (-n0[1] / f, n0[0] / f, 0.0)
                b2 = (-b1[1] * n0[2], b1[0] * n0[2], f)
            else:
                f = math.sqrt(n0[1] * n0[1] + n0[2] * n0[2])
                b1 = (0.0, -n0[2] / f, n0[1] / f)
                b2 = (f, -b1[2] * n0[0], n0[0] * b1[1])
            axes = []
            for v in (n0, b1, b2):
                vn = math.sqrt(_v_dot(v, v))
                axes.append((v[0] / vn, v[1] / vn, v[2] / vn))
        else:
            axes = [x0, y0, z0]
        for nv in axes:  # 0x10227640: J = [n, r0 x n]; anchor arm r1 = 0
            a = _v_cross(r0, nv)
            resp = _v_dot(nv, nv) * inv_m + inv_i * _v_dot(a, a)
            m = 1.0 / resp if resp != 0.0 else 0.0
            rows.append(
                [True, nv, a, m, m * SOLVER_BIAS, 0.0, -_v_dot(nv, dw) / dt, -_FLT_MAX, _FLT_MAX]
            )
        for r in rows:
            r += [0.0, 0.0, r[7] == 0.0]  # lambda, lambda_v, limit flag
        return rows

    def _solve(self, rows, va, wa):
        """One pass of the row iteration 0x1022ccb0 (linear) / 0x1022ce80 (angular) over
        `rows`, in order (plain floats: this is the inner loop of every bake)."""
        vx, vy, vz = self.vb
        wx, wy, wz = self.wb
        vax, vay, vaz = va
        wax, way, waz = wa
        inv_m, inv_i = self.inv_m, self.inv_i
        for r in rows:
            a0, a1, a2 = r[2]
            if r[0]:
                n0, n1, n2 = r[1]
                jv = a0 * wx
                jv += a1 * wy + a2 * wz
                jv += n0 * (vx - vax) + n1 * (vy - vay) + n2 * (vz - vaz)
            else:
                jv = a0 * (wx - wax)
                jv += a1 * (wy - way) + a2 * (wz - waz)
            t = -jv * r[3]
            c = r[5]
            lam = r[9]
            r[10] = (t - c * r[10]) + r[10]  # lambda_v (solverExtrapolationFactor 1)
            dl = (t - r[4] * r[6]) - lam * c
            nl = lam + dl
            if nl > r[8]:
                dl, nl = r[8] - lam, r[8]
            elif nl < r[7]:
                dl, nl = r[7] - lam, r[7]
            r[9] = nl
            if dl != 0.0:
                if r[0]:
                    g = inv_m * dl
                    vx, vy, vz = vx + n0 * g, vy + n1 * g, vz + n2 * g
                g = inv_i * dl
                wx, wy, wz = wx + a0 * g, wy + a1 * g, wz + a2 * g
        self.vb = (vx, vy, vz)
        self.wb = (wx, wy, wz)

    def _integrate_q(self, q, w):
        n = math.sqrt(w[0] * w[0] + w[1] * w[1] + w[2] * w[2])
        if n == 0.0:
            return q
        half = n * self.dt * 0.5
        s = _em.sin(half) / n
        return _q_mul((w[0] * s, w[1] * s, w[2] * s, _em.cos(half)), q)

    def substep(self, va, wa):
        dt = self.dt
        # 0x101ffb50: v += a dt (a = 0: gravity cancelled by the game's -m g force,
        # 0x656fb4), w *= 1 - angularDamping dt, |w| <= maxAngularVelocity
        f = 1.0 - BODY_ANGULAR_DAMPING * dt
        wb = (self.wb[0] * f, self.wb[1] * f, self.wb[2] * f) if f > 0.0 else (0.0, 0.0, 0.0)
        w2 = _v_dot(wb, wb)
        if w2 > _MAX_W2:
            f = math.sqrt(_MAX_W2 / w2)
            wb = (wb[0] * f, wb[1] * f, wb[2] * f)
        self.wb = wb
        rows = self._rows()
        for _ in range(self.iterations):  # PxsSolverCoreGeneral 0x1022c8d0
            self._solve(rows, va, wa)
        vm, wm = self.vb, self.wb  # 0x10206570: motion velocities, saved before conclude
        # conclude 0x1022d450 / 0x1022d500: drop the position bias (limit rows keep rhs > 0),
        # scale the decay coefficient by lambda_v / lambda, solve each block once more
        blocks = [rows[:1], rows[1:-3], rows[-3:]]
        for blk in blocks:
            for r in blk:
                r[6] = max(r[6], 0.0) if r[11] else 0.0
                if abs(r[9]) > SOLVER_LAMBDA_EPS:
                    r[5] = r[10] / r[9] * r[5]
            self._solve(blk, va, wa)
        # pose integration 0x102008a0 with the motion (pre-conclude) velocities
        self.xb = (self.xb[0] + vm[0] * dt, self.xb[1] + vm[1] * dt, self.xb[2] + vm[2] * dt)
        self.qb = self._integrate_q(self.qb, wm)
        self.xa = (self.xa[0] + va[0] * dt, self.xa[1] + va[1] * dt, self.xa[2] + va[2] * dt)
        self.qa = self._integrate_q(self.qa, wa)

    def step(self, xt, qt, nsub=1):
        """One simulate(): the anchor is driven to (xt, qt) over nsub fixed substeps."""
        if nsub <= 0:
            return
        va, wa = self._kinematic_velocity(xt, qt, nsub)
        for _ in range(nsub):
            self.substep(va, wa)
        for name in ("qa", "qb"):
            q = getattr(self, name)
            n = math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3])
            setattr(self, name, (q[0] / n, q[1] / n, q[2] / n, q[3] / n))


def _slerp_rot(Ra, Rb_, t):
    """Rotation-matrix slerp Ra -> Rb_ (shortest path) on 3x3 tuples: _slerp_m in plain
    float arithmetic."""
    M = _em.mat_mul(_em.transpose(Ra), Rb_)
    v = (M[2][1] - M[1][2], M[0][2] - M[2][0], M[1][0] - M[0][1])
    c = min(1.0, max(-1.0, (M[0][0] + M[1][1] + M[2][2] - 1.0) / 2.0))
    a = _em.acos(c)
    s = math.sqrt(_v_dot(v, v))
    if a < 1e-9 or s < 1e-12:
        return Rb_ if t >= 0.5 else Ra
    x, y, z = v[0] / s, v[1] / s, v[2] / s
    K = ((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0))
    KK = _em.mat_mul(K, K)
    sn, cs = _em.sin(a * t), 1.0 - _em.cos(a * t)
    rot = tuple(
        tuple((1.0 if i == j else 0.0) + sn * K[i][j] + cs * KK[i][j] for j in range(3))
        for i in range(3)
    )
    return _em.mat_mul(Ra, rot)


def _q_extrapolate(q0, q1, u):
    """Rotation at frame coordinate u on the constant-rate motion through q0 (u = 0) and
    q1 (u = 1)."""
    d = _q_mul(q1, (-q0[0], -q0[1], -q0[2], q0[3]))
    if d[3] < 0:
        d = (-d[0], -d[1], -d[2], -d[3])
    s = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2])
    if s < 1e-12:
        return q0
    half = _em.atan2(s, d[3]) * u
    f = _em.sin(half) / s
    q = _q_mul((d[0] * f, d[1] * f, d[2] * f, _em.cos(half)), q0)
    return q if _q_dot(q, q0) >= 0 else (-q[0], -q[1], -q[2], -q[3])


def _loop_frames(c_o, qA):
    """Unique frames of one lap of a looping clip.  Baked loops usually repeat frame 0 as
    their last frame (lap = F - 1 frames); a clip whose last frame is one step short of
    frame 0 laps in F frames.  Decided on the parent pose: the last frame counts as a
    repeat when it is within half a typical frame step of frame 0."""
    F = len(c_o)

    def dist(i, j):
        dq = abs(_q_dot(qA[i], qA[j]))
        dx = (c_o[i][0] - c_o[j][0], c_o[i][1] - c_o[j][1], c_o[i][2] - c_o[j][2])
        return math.sqrt(_v_dot(dx, dx)) + 2.0 * _em.acos(min(1.0, dq)) * 0.1

    steps = sorted(dist(i, i + 1) for i in range(F - 1))
    return F - 1 if dist(F - 1, 0) <= 0.5 * steps[len(steps) // 2] + 1e-9 else F


def _apply_jiggle_solver(
    P, fps, bindpath, bones, gain, props, extract_root, latency, warmup, loop, lead_in, stats
):
    """PhysX soft-limit model, file constants only (see SoftLimitJoint).

    Time base.  The engine steps at 1/physicsIntegrationRateInHz (game 0x4f4d20) and a
    baked clip has its own rate, so the clip is played at exactly one physics step per
    1/hz s: step j drives the anchor to the parent pose at t = j/hz (Catmull-Rom through
    the clip frames, exact on a frame, so a 60 fps clip is used as it is).  The game
    reads the body before it steps (0x6563a0), so the state after step j is what a frame
    at t = j/hz + latency shows (latency = 1/hz, the one-frame read-back delay).  Each
    clip frame takes the body pose interpolated between the two physics states around it
    and expresses it in ITS OWN parent frame, then applies the game's metre clamp.
    In the game a frame may also take 0, 2 or 3 steps (0x4f4ddc); that depends on the
    machine's frame times and is not modelled.

    Start of a clip that does not loop.  In the game the body keeps simulating across
    state changes, so no clip really starts at rest; what came before is not in the clip.
    The bake assumes the parent was already moving at the velocity of the clip's first
    frame interval for lead_in seconds (default SOLVER_LEAD_IN): a clip that starts
    still starts at rest, a clip cut out of ongoing motion starts with the lag that
    motion had built up.  On capture windows that start in mid-motion this lowers the
    frame-0 error by 13-28 % against starting at rest.  lead_in=0 starts at rest.

    Looping clip (loop=True; the caller passes the game's loop flag).  One lap is F - 1
    frames when the last frame repeats frame 0 (the usual bake) and F frames otherwise
    (_loop_frames); it is played as round(lap * hz) steps per lap from rest until the
    state at the lap boundary repeats (SOLVER_LOOP_TOL) or SOLVER_LOOP_SETTLE seconds
    have gone by -- the motion is not always periodic, lap-to-lap changes of a few
    tenths of a degree can persist -- and then one more lap is recorded.  Whatever
    mismatch is left between that lap's end and its start is spread over the lap, so
    the body's last frame hands over to its first exactly.
    warmup = n replaces the automatic stop by exactly n laps before the recorded one
    (and treats the clip as a loop); warmup = 0 forces the non-looping start.
    stats: optional dict, filled per bone with what was done (laps, seam, steps)."""
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
    looped = bool(loop) or bool(warmup)
    if warmup is not None and not warmup:
        looped = False  # warmup=0: explicitly not a loop
    if lead_in is None:
        lead_in = SOLVER_LEAD_IN
    P = np.array(P, dtype=np.float64, copy=True)
    P0 = P.copy()  # animated input (several jiggle bones may share a parent)
    t_end = (F - 1) / max(fps, 1e-6)
    # states S[0] (rest) .. S[n_steps]; S[j + 1] = after step j, shown at j/hz + latency
    n_steps = int(math.ceil(max(t_end - latency, 0.0) * hz - 1e-9)) + 1
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
        Rb_p, tb_p, tb_k = Rb[p].tolist(), tuple(tb[p].tolist()), tuple(tb[k].tolist())
        Rb_pT = _em.transpose(Rb_p)
        if tloc is not None:
            r = tuple(tloc[k].tolist())
        else:
            r = _em.mat_vec(Rb_pT, (tb_k[0] - tb_p[0], tb_k[1] - tb_p[1], tb_k[2] - tb_p[2]))
        if math.sqrt(_v_dot(r, r)) < 1e-6:
            continue
        # Plain float arithmetic from here to the write-back (exact_math): no LAPACK, BLAS
        # or C-library call, so the bake is the same bit for bit on every platform.
        Pp = P0[:, p].tolist()  # [frame][row][col], parent palette
        Pk = P0[:, k].tolist()
        A_o, c_o = [], []
        for i in range(F):
            rot = [row[:3] for row in Pp[i]]
            A_o.append(_em.mat_mul(rot, Rb_p))  # parent bone frame
            x = _em.mat_vec(rot, tb_p)
            c_o.append((x[0] + Pp[i][0][3], x[1] + Pp[i][1][3], x[2] + Pp[i][2][3]))  # pivot
        qA = [_m2q(_em.nearest_rotation(A_o[i])) for i in range(F)]

        for i in range(1, F):  # one quaternion sheet, so components can be interpolated
            if _q_dot(qA[i], qA[i - 1]) < 0:
                qA[i] = tuple(-v for v in qA[i])
        U = _loop_frames(c_o, qA) if looped else 0  # unique frames of one lap (0: no loop)
        M = int(round(U / fps * hz)) if U else 0  # physics steps of one lap
        if M < 2:
            U = M = 0
        # ghost frames for the spline ends of a clip that does not loop: the motion
        # continues at the velocity of the first / last frame interval
        g_lo = (
            tuple(2 * c_o[0][n] - c_o[1][n] for n in range(3)),
            _q_extrapolate(qA[0], qA[1], -1.0),
        )
        g_hi = (
            tuple(2 * c_o[F - 1][n] - c_o[F - 2][n] for n in range(3)),
            _q_extrapolate(qA[F - 1], qA[F - 2], -1.0),
        )

        def knot(i):
            if U:
                return c_o[i % U], qA[i % U]
            if i < 0:
                return g_lo
            return (c_o[i], qA[i]) if i < F else g_hi

        def target(u):
            """Parent pose at clip-frame coordinate u: Catmull-Rom through the frames (C1,
            so frame knots do not become velocity jumps), exact on a frame; before frame 0
            of a non-looping clip the first interval's velocity, extrapolated."""
            if not U:
                if u < 0.0:
                    x = tuple(c_o[0][n] + u * (c_o[1][n] - c_o[0][n]) for n in range(3))
                    return x, _q_extrapolate(qA[0], qA[1], u)
                u = min(u, F - 1.0)
            i = int(math.floor(u + 1e-12))
            w = u - i
            if w <= 1e-12:
                x, q = knot(i)
                return tuple(x), q
            w2, w3 = w * w, w * w * w
            cf = (
                -0.5 * w3 + w2 - 0.5 * w,
                1.5 * w3 - 2.5 * w2 + 1.0,
                -1.5 * w3 + 2.0 * w2 + 0.5 * w,
                0.5 * w3 - 0.5 * w2,
            )
            kn = [knot(i + n) for n in (-1, 0, 1, 2)]
            x = [0.0, 0.0, 0.0]
            q = [0.0, 0.0, 0.0, 0.0]
            for n in range(4):
                xn_, qn_ = kn[n]
                for m in range(3):
                    x[m] += cf[n] * xn_[m]
                sg = cf[n] if _q_dot(qn_, kn[1][1]) >= 0 else -cf[n]
                for m in range(4):
                    q[m] += sg * qn_[m]
            qn = math.sqrt(_q_dot(q, q))
            return tuple(x), (q[0] / qn, q[1] / qn, q[2] / qn, q[3] / qn)

        sim = SoftLimitJoint(W[grp]["k"], W[grp]["d"], r, dt=dt)
        if U:
            # Looping clip: laps of M steps from rest until the lap-boundary state repeats or
            # the start is forgotten (the motion is not always periodic: lap-to-lap changes
            # of a few tenths of a degree can persist), then one recorded lap whose
            # remaining end/start mismatch is spread over the lap so that it closes exactly.
            sim.reset(*target(0.0))
            prev, laps, resid = None, 0, float("inf")
            while True:
                start = (sim.xa, sim.qa, sim.xb, sim.qb)
                xs, qs, rec = [sim.xb], [sim.qb], [(sim.xa, sim.qa)]
                for j in range(M):
                    sim.step(*target(j * U / float(M)))
                    xs.append(sim.xb)
                    qs.append(sim.qb)
                    rec.append((sim.xa, sim.qa))
                laps += 1
                cur = sim.xb + sim.qb + tuple(v * dt for v in sim.vb + sim.wb)
                if prev is not None:
                    resid = max(abs(cur[n] - prev[n]) for n in range(len(cur)))
                prev = cur
                if warmup:
                    if laps > int(warmup):
                        break
                elif laps >= 2 and (
                    resid < SOLVER_LOOP_TOL
                    or laps >= SOLVER_LOOP_MAX_LAPS
                    or (laps - 1) * M * dt >= SOLVER_LOOP_SETTLE
                ):
                    break
            # seam: body pose relative to the anchor at the lap's end vs its start
            ca = (-start[1][0], -start[1][1], -start[1][2], start[1][3])
            cb = (-rec[M][1][0], -rec[M][1][1], -rec[M][1][2], rec[M][1][3])
            r0 = _q_mul(ca, start[3])
            rm = _q_mul(cb, qs[M])
            dq = _q_mul(r0, (-rm[0], -rm[1], -rm[2], rm[3]))  # end -> start, anchor frame
            if dq[3] < 0:
                dq = (-dq[0], -dq[1], -dq[2], -dq[3])
            seam = 2.0 * _em.atan2(math.sqrt(dq[0] * dq[0] + dq[1] * dq[1] + dq[2] * dq[2]), dq[3])
            p0 = _q_rot(ca, tuple(start[2][n] - start[0][n] for n in range(3)))
            for j in range(1, M + 1):
                w = j / float(M)
                xa_j, qa_j = rec[j]
                cj = (-qa_j[0], -qa_j[1], -qa_j[2], qa_j[3])
                dj = _q_slerp((0.0, 0.0, 0.0, 1.0), dq, w)
                pj = _q_rot(cj, tuple(xs[j][n] - xa_j[n] for n in range(3)))
                pj = _q_rot(dj, pj)
                if j == M:
                    pj = p0
                pw = _q_rot(qa_j, pj)
                xs[j] = (xa_j[0] + pw[0], xa_j[1] + pw[1], xa_j[2] + pw[2])
                qs[j] = _q_mul(qa_j, _q_mul(dj, _q_mul(cj, qs[j])))
            n_steps = M
            if stats is not None:
                stats[bone] = dict(
                    loop=True,
                    frames=U,
                    steps=M,
                    laps=laps,
                    residual=resid,
                    seam_deg=math.degrees(seam),
                )
        else:
            lead = int(round(lead_in * hz))
            sim.reset(*target(-lead * dt * fps))
            for j in range(-lead, 0):  # the parent already moving at its frame-0 velocity
                sim.step(*target(j * dt * fps))
            xs = [sim.xb]
            qs = [sim.qb]
            for j in range(n_steps):
                sim.step(*target(j * dt * fps))
                xs.append(sim.xb)
                qs.append(sim.qb)
            if stats is not None:
                stats[bone] = dict(loop=False, frames=F, steps=n_steps, lead_in_steps=lead)
        for i in range(F):
            if U:  # clip time -> lap phase -> state index (one lap = M steps exactly)
                u = ((i % U) / float(U) * M - latency * hz + 1.0) % M
            else:
                u = (i / fps - latency) * hz + 1.0
                u = min(max(u, 0.0), float(n_steps))
            j = min(int(u), n_steps - 1)
            w = u - j
            w0 = 1.0 - w
            xb = tuple(xs[j][n] * w0 + xs[j + 1][n] * w for n in range(3))
            qb = qs[j] if w <= 0.0 else (qs[j + 1] if w >= 1.0 else _q_slerp(qs[j], qs[j + 1], w))
            # body orientation is "anchor-like": palette rotation = R(qb) Rb_p^T
            Rbody = _em.mat_mul(_em.transpose(_q_axes(qb)), Rb_pT)
            org_body = xb
            Ra = [row[:3] for row in Pk[i]]
            x = _em.mat_vec(Ra, tb_k)
            org_anim = (x[0] + Pk[i][0][3], x[1] + Pk[i][1][3], x[2] + Pk[i][2][3])
            if gain != 1.0:
                Rp = _em.nearest_rotation([row[:3] for row in Pp[i]])
                Rbody = _slerp_rot(Rp, Rbody, gain)
                x = _em.mat_vec(Rp, tb_k)
                rest = (x[0] + Pp[i][0][3], x[1] + Pp[i][1][3], x[2] + Pp[i][2][3])
                org_body = tuple(rest[n] + (org_body[n] - rest[n]) * gain for n in range(3))
            delta = (
                org_body[0] - org_anim[0],
                org_body[1] - org_anim[1],
                org_body[2] - org_anim[2],
            )
            ln = math.sqrt(_v_dot(delta, delta))
            if ln > lim:  # 0x6563a0: pos = p0 + delta*t, quat = slerp(q0, q, t)
                t = lim / ln
                org_body = tuple(org_anim[n] + delta[n] * t for n in range(3))
                Rbody = _slerp_rot(_em.nearest_rotation(Ra), Rbody, t)
            x = _em.mat_vec(Rbody, tb_k)
            for n in range(3):
                P[i, k, n, 0] = Rbody[n][0]
                P[i, k, n, 1] = Rbody[n][1]
                P[i, k, n, 2] = Rbody[n][2]
                P[i, k, n, 3] = org_body[n] - x[n]
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
    warmup=None,
    loop=False,
    lead_in=None,
    stats=None,
):
    """P: (F,nbones,3,4) world palettes; fps: clip rate; bindpath: bind npz.
    model: 'solver' -- the PhysX 2.8.1 soft swing-limit row stepped as the DLL does,
                       file spring/damping only; see _apply_jiggle_solver
           'pivot'  -- engine geometry (parent-origin pivot, parent->bone lever,
                       position+rotation write-back, metre clamp, no gravity,
                       twist locked, one-frame latency); see _apply_jiggle_pivot
           'pinned' -- the default of 1.2.0 - 1.3.0 (see _apply_jiggle_pinned)
           None     -- DEFAULT_MODEL ('solver')
    mode:  spring constants, see swing_constants ('aniso' is pinned-only);
           None = DEFAULT_MODE[model].  'solver' has one mode, 'file'.
    latency: pivot / solver, seconds the body trails the parent (None = 1/rate_hz,
             0 disables).
    loop: solver only, True for a clip the game loops: baked as a closed lap of its
          settled motion (last frame hands over to the first).
    lead_in: solver only, seconds of lead-in at the frame-0 velocity before a clip
             that does not loop (None = SOLVER_LEAD_IN, 0 = start at rest).
    warmup: solver only, exact number of laps before the recorded one (implies loop;
            0 forces the non-looping start).
    stats: solver only, optional dict that receives per-bone bake details.
    gain scales the deviation (default 1)."""
    model, mode = resolve_model(model, mode)
    if mode == "capture" and model == "pinned":
        raise ValueError("mode='capture' constants belong to model='pivot'")
    if model == "solver":
        if mode != SOLVER_MODE:
            raise ValueError("model='solver' uses the file constants only (mode='file')")
        return _apply_jiggle_solver(
            P,
            fps,
            bindpath,
            bones,
            gain,
            props,
            extract_root,
            latency,
            warmup,
            loop,
            lead_in,
            stats,
        )
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
