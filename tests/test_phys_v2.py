"""Jiggle 'pivot' model and node collision volumes (2026-10 exe re-read).

Jiggle (CharacterAddonCtrl 0x6574cd / 0x648858 / 0x6563a0): the simulated body
swings about the PARENT bone origin on the parent->bone lever, its pose replaces
the bone's local position and rotation, gravity is cancelled, twist about the
parent X axis is locked, the clamp is a bone-origin distance in metres and the
body trails the parent by one frame.  The previous model stays selectable as
model='pinned'.

Node records (Node::Deserialize 0x545927): two lists of collision volumes with
per-type sizes (box 52, sphere 44, capsule 48 bytes, meshes variable) and a
third list, instead of the fixed 48-byte "joint" record.

Everything here is synthetic: no game files.
"""

import math
import struct

import numpy as np
import pytest

import extract_skeletons as es
import jiggle_d6
import jiggle_pass
import parse_model_nodes as pmn
import skeleton_records as sr

# ---------------------------------------------------------------------------
# jiggle helpers
# ---------------------------------------------------------------------------

LEVER = np.array([0.0, 0.1, 0.05])  # parent -> bone, in the parent frame
PARENT_ORIGIN = np.array([0.0, 1.0, 0.0])


def _bind(tmp_path, with_tloc=True, name="BreastL"):
    """Root at the origin, parent bone 1 m up, jiggle bone on LEVER."""
    tb = np.array([[0.0, 0.0, 0.0], PARENT_ORIGIN, PARENT_ORIGIN + LEVER])
    arrays = dict(
        Rb=np.tile(np.eye(3), (3, 1, 1)),
        tb=tb,
        names=np.array(["Root", "Spine2", name]),
        par=np.array([-1, 0, 1]),
    )
    if with_tloc:
        arrays["tloc"] = np.array([[0.0, 0.0, 0.0], PARENT_ORIGIN, LEVER])
    path = tmp_path / ("bind_%s.npz" % ("tloc" if with_tloc else "notloc"))
    np.savez(path, **arrays)
    return str(path), tb


def _rot(axis, ang):
    return jiggle_d6._rotv2m(np.asarray(axis, float) * ang)


def _palettes(angles, axis, pivot=PARENT_ORIGIN, shift=None):
    """Parent (and the rigid jiggle bone) rotate by angles[f] about `axis`
    through `pivot`; optional per-frame world shift of everything."""
    F = len(angles)
    P = np.zeros((F, 3, 3, 4))
    P[:, 0, :, :3] = np.eye(3)
    for f, a in enumerate(angles):
        R = _rot(axis, a)
        t = pivot - R @ pivot + (shift[f] if shift is not None else 0.0)
        for k in (1, 2):
            P[f, k, :, :3] = R
            P[f, k, :, 3] = t
    return P


def _rotvec(R):
    a = float(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)))
    if a < 1e-12:
        return np.zeros(3)
    return a * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(a))


def _origin(P, k, tb):
    return np.einsum("fab,b->fa", P[:, k, :, :3].astype(np.float64), tb[k]) + P[:, k, :, 3]


def _props(**groups):
    props = dict(jiggle_d6._FILE_DEFAULTS)
    for g, kv in groups.items():
        props[g] = dict(props[g], **kv)
    return props


SWING = 0.6 * np.sin(np.arange(90) / 60.0 * 2 * math.pi * 2.0)  # 2 Hz, +-34 deg, 60 fps


# ---------------------------------------------------------------------------
# model selection
# ---------------------------------------------------------------------------


def test_default_model_is_pinned_and_pivot_is_opt_in(tmp_path):
    """Review M2: the default stays the 1.2.0 model; the pivot model's swing
    constants are capture-fitted at an estimated frame rate, so it is opt-in."""
    bind, _tb = _bind(tmp_path)
    P = _palettes(SWING, [0, 0, 1])
    assert jiggle_d6.DEFAULT_MODEL == "pinned"
    assert jiggle_d6.resolve_model() == ("pinned", "engine")
    assert jiggle_d6.resolve_model("pivot") == ("pivot", "capture")
    default = jiggle_d6.apply_jiggle(P, 60.0, bind)
    pivot = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot")
    pinned = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pinned")
    legacy = jiggle_d6.apply_jiggle_legacy(P, 60.0, bind)
    assert np.array_equal(default, pinned)
    assert np.array_equal(pinned, legacy)
    assert not np.allclose(pivot, pinned, atol=1e-4)
    with pytest.raises(ValueError):
        jiggle_d6.apply_jiggle(P, 60.0, bind, model="nope")


def test_pinned_model_keeps_the_old_numbers(tmp_path):
    """model='pinned' is the shipped 1.3.x integrator: gravity sag on a static
    parent, origin pinned, K/D = solver_soften at 1/120 s."""
    bind, tb = _bind(tmp_path)
    P = _palettes(np.zeros(120), [0, 0, 1])
    out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pinned").astype(np.float64)
    sag = np.linalg.norm(_rotvec(out[-1, 2, :, :3] @ P[-1, 2, :, :3].T))
    K, _D = jiggle_d6.swing_constants("engine", "breast", jiggle_d6._FILE_DEFAULTS, "pinned")
    assert K == pytest.approx(166.327, abs=1e-3)
    r = tb[2]
    expect = np.linalg.norm(np.cross(r, [0.0, -14.82, 0.0])) / K  # static balance of r x g
    assert sag == pytest.approx(expect, rel=0.05)
    assert np.allclose(_origin(out, 2, tb), _origin(P, 2, tb), atol=1e-6)  # origin pinned


def test_jiggle_pass_forwards_the_model(tmp_path):
    bind, _tb = _bind(tmp_path)
    P = _palettes(SWING, [0, 0, 1])
    a = jiggle_pass.apply_jiggle(P, 60.0, bind, model="pinned")
    b = jiggle_pass.apply_jiggle(P, 60.0, bind)
    assert np.array_equal(a, jiggle_d6.apply_jiggle(P, 60.0, bind, model="pinned"))
    assert np.array_equal(b, jiggle_d6.apply_jiggle(P, 60.0, bind))


# ---------------------------------------------------------------------------
# the five modelling corrections
# ---------------------------------------------------------------------------


def test_gravity_is_cancelled_static_parent_does_not_sag(tmp_path):
    """0x656fb4: ApplyForce(-mass * gravity) every frame.  A static parent must
    leave the bone exactly where the animation put it (old model: ~1.6 deg sag)."""
    bind, _tb = _bind(tmp_path)
    P = _palettes(np.zeros(60), [0, 0, 1])
    out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot")
    assert np.allclose(out, P, atol=1e-6)


def test_body_swings_about_the_parent_origin_on_the_parent_bone_lever(tmp_path):
    """Pivot = parent bone origin, lever = parent->bone offset: the bone ORIGIN
    moves (old model pinned it) and stays on the sphere |origin - pivot| = |lever|."""
    bind, tb = _bind(tmp_path)
    P = _palettes(SWING, [0, 0, 1])
    out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot", latency=0.0).astype(np.float64)
    org = _origin(out, 2, tb)
    moved = np.linalg.norm(org - _origin(P, 2, tb), axis=1)
    assert moved.max() > 2e-3, "position write-back missing: the bone origin never moved"
    dist = np.linalg.norm(org - PARENT_ORIGIN, axis=1)
    free = moved < 0.079  # frames the metre clamp did not touch
    assert free.sum() > 10
    assert np.allclose(dist[free], np.linalg.norm(LEVER), atol=1e-5)


def test_rotation_and_position_are_written_back_together(tmp_path):
    """The bone palette is the parent palette rotated about the pivot: the
    origin displacement is exactly the deviation rotation applied to the lever."""
    bind, tb = _bind(tmp_path)
    P = _palettes(SWING, [0, 0, 1])
    out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot", latency=0.0).astype(np.float64)
    org = _origin(out, 2, tb)
    for f in (10, 25, 40):
        D = out[f, 2, :, :3] @ P[f, 2, :, :3].T  # world deviation rotation
        if np.linalg.norm(org[f] - _origin(P, 2, tb)[f]) > 0.079:
            continue
        lever_w = P[f, 1, :, :3] @ LEVER
        assert np.allclose(org[f] - PARENT_ORIGIN, D @ lever_w, atol=1e-5)


def test_lever_falls_back_to_tb_difference_when_bind_has_no_tloc(tmp_path):
    with_tloc, _ = _bind(tmp_path, True)
    without, _ = _bind(tmp_path, False)
    P = _palettes(SWING, [0, 0, 1])
    a = jiggle_d6.apply_jiggle(P, 60.0, with_tloc, model="pivot")
    b = jiggle_d6.apply_jiggle(P, 60.0, without, model="pivot")
    assert np.allclose(a, b, atol=1e-6)


def test_clamp_is_a_bone_origin_distance_in_metres(tmp_path):
    """0x6563a0: if |pos - animatedPos| > limit, pos = animated + delta*limit/len
    and quat = slerp(animated, body, limit/len).  The old clamp capped the ANGLE
    at limit/|tb| (4.4 deg here) and never moved the origin."""
    bind, tb = _bind(tmp_path)
    P = _palettes(3.0 * SWING, [0, 0, 1])  # violent: far beyond the limit
    props = _props(breast=dict(limit=0.02))
    out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot", props=props).astype(np.float64)
    disp = np.linalg.norm(_origin(out, 2, tb) - _origin(P, 2, tb), axis=1)
    assert disp.max() == pytest.approx(0.02, abs=1e-5)
    assert disp.max() <= 0.02 + 1e-5
    ang = [np.linalg.norm(_rotvec(out[f, 2, :, :3] @ P[f, 2, :, :3].T)) for f in range(len(P))]
    # a 0.02 m chord on the 0.1118 m lever is ~10.3 deg; the old angle clamp was 1 deg
    assert max(ang) > math.radians(5.0)
    assert max(ang) < math.radians(12.0)


def test_twist_about_the_parent_x_axis_is_locked(tmp_path):
    """TwistMotionType = Locked (0x51795e): spinning the parent about its own X
    axis with angular acceleration excites no deviation; about Z it does."""
    bind, _tb = _bind(tmp_path)
    for axis, moves in (([1, 0, 0], False), ([0, 0, 1], True)):
        P = _palettes(SWING, axis)
        out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot", latency=0.0).astype(np.float64)
        dev = max(np.linalg.norm(_rotvec(out[f, 2, :, :3] @ P[f, 2, :, :3].T)) for f in range(90))
        assert (dev > 1e-3) == moves, (axis, dev)


def test_linear_acceleration_couples_through_the_cube_inertia(tmp_path):
    """Drive = (m / I_pivot) r x (-a): body = 0.8 m cube of mass 0.1 on the lever.
    A constant pivot acceleration gives the static deflection G |r x a| / K."""
    bind, _tb = _bind(tmp_path)
    F, fps, acc = 180, 60.0, np.array([3.0, 0.0, 0.0])
    t = np.arange(F) / fps
    shift = 0.5 * acc[None, :] * t[:, None] ** 2
    P = _palettes(np.zeros(F), [0, 0, 1], shift=shift)
    props = _props(breast=dict(limit=10.0))
    out = jiggle_d6.apply_jiggle(P, fps, bind, model="pivot", latency=0.0, props=props)
    dev = _rotvec(out[F - 10, 2, :, :3].astype(np.float64) @ P[F - 10, 2, :, :3].T)
    K, _D = jiggle_d6.swing_constants("capture", "breast", props)
    icm = jiggle_d6.BODY_MASS * jiggle_d6.BODY_SIZE**2 / 6.0
    G = jiggle_d6.BODY_MASS / (icm + jiggle_d6.BODY_MASS * float(LEVER @ LEVER))
    expect = G * np.cross(LEVER, -acc) / K
    expect[0] = 0.0  # twist component is locked
    assert G == pytest.approx(8.39, abs=0.01)
    assert np.allclose(dev, expect, atol=0.03 * np.linalg.norm(expect))


def test_body_trails_the_parent_by_one_physics_frame(tmp_path):
    """Order of 0x6563a0: anchor box moved to the current parent pose, body pose
    read from the previous step.  At constant angular velocity (no drive) the
    deviation is exactly -omega * latency, about every axis including twist."""
    bind, _tb = _bind(tmp_path)
    w = 2.0  # rad/s
    P = _palettes(w * np.arange(60) / 60.0, [1, 0, 0])
    props = _props(breast=dict(limit=10.0))
    out = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot", props=props).astype(np.float64)
    dev = _rotvec(out[30, 2, :, :3] @ P[30, 2, :, :3].T)
    assert np.allclose(dev, [-w / 60.0, 0, 0], atol=1e-6)
    off = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot", props=props, latency=0.0)
    assert np.allclose(off[30], P[30], atol=1e-6)
    half = jiggle_d6.apply_jiggle(P, 60.0, bind, model="pivot", props=props, latency=1 / 120.0)
    dev = _rotvec(half[30, 2, :, :3].astype(np.float64) @ P[30, 2, :, :3].T)
    assert np.allclose(dev, [-w / 120.0, 0, 0], atol=1e-6)


def test_swing_constants_per_model_and_mode():
    W = jiggle_d6._FILE_DEFAULTS
    k, d = W["breast"]["k"], W["breast"]["d"]
    # pivot/engine: PhysX substep 1/rate_hz (FUN_004f4d20) + angular damping 1.0 (0x4fe311)
    Ke, De = jiggle_d6.solver_soften(k, d, dts=1.0 / 60.0)
    assert jiggle_d6.swing_constants("engine", "breast", W, "pivot") == pytest.approx(
        (Ke, De + 1.0)
    )
    assert jiggle_d6.swing_constants("engine", "breast", W, "pinned") == pytest.approx(
        jiggle_d6.solver_soften(k, d, dts=1.0 / 120.0)
    )
    assert jiggle_d6.swing_constants("capture", "breast", W) == (570.0, 37.5)
    assert jiggle_d6.swing_constants("capture", "belly", W) == (308.0, 19.2)
    # no hair capture: falls back to the file-constant recipe
    assert jiggle_d6.swing_constants("capture", "hair", W) == jiggle_d6.swing_constants(
        "engine", "hair", W
    )
    over = _props(breast=dict(K_eff=123.0, D_eff=4.5))
    assert jiggle_d6.swing_constants("capture", "breast", over) == (123.0, 4.5)
    assert jiggle_d6.DEFAULT_MODE == {"pivot": "capture", "pinned": "engine"}


def test_capture_constants_are_rejected_for_the_pinned_model(tmp_path):
    bind, _tb = _bind(tmp_path)
    P = _palettes(SWING, [0, 0, 1])
    with pytest.raises(ValueError):
        jiggle_d6.apply_jiggle(P, 60.0, bind, model="pinned", mode="capture")


def test_pivot_tail_frames_do_not_extrapolate_on_fast_clips(tmp_path):
    """240 fps clip on the 60 Hz sim grid: frames past the last sim sample hold
    it (same guarantee the pinned model's regression test pins)."""
    bind, tb = _bind(tmp_path)
    F, fps = 80, 240.0
    P = _palettes(0.6 * np.sin(np.arange(F) / fps * 2 * math.pi * 3.0), [0, 0, 1])
    out = jiggle_d6.apply_jiggle(P, fps, bind, model="pivot").astype(np.float64)
    assert np.isfinite(out).all()
    disp = np.linalg.norm(_origin(out, 2, tb) - _origin(P, 2, tb), axis=1)
    assert disp.max() <= jiggle_d6._FILE_DEFAULTS["breast"]["limit"] + 1e-5
    assert disp.max() > 1e-3


def test_two_jiggle_bones_on_one_parent_do_not_feed_each_other(tmp_path):
    """BreastL and BreastR share Spine2: both are simulated from the ANIMATED
    input, so a mirrored lever gives a mirrored result."""
    tb = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.1, 1.1, 0.05], [-0.1, 1.1, 0.05]])
    path = tmp_path / "bind_pair.npz"
    np.savez(
        path,
        Rb=np.tile(np.eye(3), (4, 1, 1)),
        tb=tb,
        tloc=np.array([[0, 0, 0], [0, 1.0, 0], [0.1, 0.1, 0.05], [-0.1, 0.1, 0.05]]),
        names=np.array(["Root", "Spine2", "BreastL", "BreastR"]),
        par=np.array([-1, 0, 1, 1]),
    )
    F = 60
    P = np.zeros((F, 4, 3, 4))
    P[:, :, :, :3] = np.eye(3)
    # pure fore-aft (Z) shake of the whole body: symmetric drive for a mirrored pair
    P[:, :, 2, 3] = (0.05 * np.sin(np.arange(F) / 60.0 * 2 * math.pi * 3.0))[:, None]
    out = jiggle_d6.apply_jiggle(P, 60.0, str(path), model="pivot").astype(np.float64)
    M = np.diag([-1.0, 1.0, 1.0])
    for f in (10, 30, 50):
        assert np.allclose(out[f, 3, :, :3], M @ out[f, 2, :, :3] @ M, atol=1e-5)
    assert np.abs(out[:, 2, :, :3] - P[:, 2, :, :3]).max() > 1e-4


# ---------------------------------------------------------------------------
# node collision volumes
# ---------------------------------------------------------------------------

Q_ID = (0.0, 0.0, 0.0, 1.0)
VERTS = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]
INDICES = [0, 1, 2, 0, 2, 3, 0, 3, 1, 1, 3, 2]
COOKED = b"NXS\x01CVXM" + bytes(range(40))

VOLS0 = [
    dict(type=7, data=(0.1429, 0.2428), pos=(-0.1887, -0.0953, 0.0237), quat=(0.0, 0.6, 0.0, 0.8)),
    dict(type=6, data=(0.07,), pos=(0.1, 0.2, 0.3), quat=Q_ID),
    dict(type=5, data=(0.2, 0.1, 0.05), pos=(0.0, 0.01, 0.02), quat=(0.6, 0.0, 0.0, 0.8)),
    dict(type=4, mesh=(1, VERTS, INDICES), pos=(0.5, 0.5, 0.5), quat=Q_ID, blob=COOKED),
]
VOLS1 = [dict(type=5, data=(1.0, 2.0, 3.0), pos=(0.0, 0.0, 0.0), quat=Q_ID)]


def _volume_bytes(v, order):
    b = struct.pack(order + "2I", v["type"], 0)
    if "mesh" in v:
        mode, verts, idx = v["mesh"]
        b += struct.pack(order + "2I", mode, len(verts))
        for p in verts:
            b += struct.pack(order + "3f", *p)
        b += struct.pack(order + "I", len(idx)) + struct.pack(order + "%dI" % len(idx), *idx)
    else:
        b += struct.pack(order + "%df" % len(v["data"]), *v["data"])
    b += struct.pack(order + "3f", *v["pos"]) + struct.pack(order + "4f", *v["quat"])
    blob = v.get("blob", b"")
    return b + struct.pack(order + "I", len(blob)) + blob


def _lists_bytes(order, l0=(), l1=(), surfaces=()):
    b = b""
    for lst in (l0, l1):
        b += struct.pack(order + "I", len(lst)) + b"".join(_volume_bytes(v, order) for v in lst)
    b += struct.pack(order + "I", len(surfaces))
    for tris, verts, idx in surfaces:
        b += struct.pack(order + "I", len(tris))
        for vec, val, ident in tris:
            b += struct.pack(order + "4fi", vec[0], vec[1], vec[2], val, ident)
        b += struct.pack(order + "I", len(verts))
        for p in verts:
            b += struct.pack(order + "3f", *p)
        b += struct.pack(order + "I", len(idx)) + struct.pack(order + "%dI" % len(idx), *idx)
    return b


def _tail(order, parent, c34=1, **lists):
    """[f1][parent][cnt34][cnt34 x 0][cnt40 = 0][flag 0][volume lists]."""
    b = struct.pack(order + "IiI", 0, parent, c34) + struct.pack(order + "%dI" % c34, *([0] * c34))
    return b + struct.pack(order + "I", 0) + b"\0" + _lists_bytes(order, **lists)


BONES = [
    ("Bip", (0.0, 1.0, 0.0), Q_ID, 0, dict()),
    ("Spine2", (0.0, 0.3, 0.01), (0.0, 0.0, 0.6, 0.8), 1, dict(l0=VOLS0)),
    ("L Hand", (0.4, 0.0, 0.0), (0.6, 0.0, 0.0, 0.8), 2, dict(l0=VOLS0[2:3], l1=VOLS1)),
    ("Head", (0.0, 0.2, 0.0), Q_ID, 2, dict()),
]


def _header(order, with_volumes=True):
    """Node array in the engine layout: count, unnamed root, then BONES."""
    b = struct.pack(order + "I", len(BONES) + 1)
    b += struct.pack(order + "3f", 0, 0, 0) + struct.pack(order + "4f", *Q_ID)
    b += struct.pack(order + "I", 1) + b"\0" + _tail(order, -1)
    for nm, pos, q, par, lists in BONES:
        b += struct.pack(order + "3f", *pos) + struct.pack(order + "4f", *q)
        raw = nm.encode() + b"\0"
        b += struct.pack(order + "I", len(raw)) + raw
        b += _tail(order, par, **(lists if with_volumes else {}))
    return b


def _check_volume(got, want):
    assert got["type"] == want["type"]
    assert got["kind"] == sr.VOLUME_TYPES[want["type"]]
    assert got["base"] == 0
    assert np.allclose(got["pos"], want["pos"], atol=1e-6)
    assert np.allclose(got["quat"], want["quat"], atol=1e-6)
    assert got["blob"] == want.get("blob", b"")
    if want["type"] == 5:
        assert np.allclose(got["size"], want["data"], atol=1e-6)
    elif want["type"] == 6:
        assert got["radius"] == pytest.approx(want["data"][0])
    elif want["type"] == 7:
        assert got["diameter"] == pytest.approx(want["data"][0])
        assert got["height"] == pytest.approx(want["data"][1])
    else:
        mode, verts, idx = want["mesh"]
        assert got["mode"] == mode
        assert np.allclose(got["verts"], verts, atol=1e-6)
        assert list(got["indices"]) == idx


@pytest.mark.parametrize("order", ["<", ">"])
def test_volume_lists_parse_every_type_and_tile_exactly(order):
    """Records are NOT a fixed 48 bytes: sphere 44, capsule 48, box 52, mesh
    variable + cooked blob.  The old parse_node_aux only tiles capsule-only nodes."""
    region = _tail(order, 5, c34=2, l0=VOLS0, l1=VOLS1)
    mb = b"\xaa" * 5 + region + b"\xbb" * 9
    r = sr.parse_node_tail(mb, 5, 5 + len(region), order)
    assert r is not None and r["parent"] == 5 and r["end"] == 5 + len(region)
    assert [len(x) for x in r["volumes"]] == [len(VOLS0), len(VOLS1)]
    for got, want in zip(r["volumes"][0] + r["volumes"][1], VOLS0 + VOLS1):
        _check_volume(got, want)
    assert r["surfaces"] == []
    # parse_node_aux is the same reader since the follow-up (its fixed 48-byte
    # reader returned None here, which is why 331 corpus regions failed)
    aux = pmn.parse_node_aux(mb, 5, 5 + len(region), order)
    assert aux is not None and len(aux["joints"]) == len(VOLS0) + len(VOLS1)
    assert [j["scene"] for j in aux["joints"]] == [0] * len(VOLS0) + [1] * len(VOLS1)
    # an off-by-one end must not be accepted
    assert sr.parse_node_tail(mb, 5, 5 + len(region) - 1, order) is None
    assert sr.parse_node_tail(mb, 5, 5 + len(region) + 1, order) is None


def test_record_sizes_match_the_engine_readers():
    sizes = {v["type"]: len(_volume_bytes(v, "<")) for v in VOLS0}
    assert sizes[6] == 44 and sizes[7] == 48 and sizes[5] == 52
    assert sizes[4] == 8 + 8 + 12 * len(VERTS) + 4 + 4 * len(INDICES) + 28 + 4 + len(COOKED)


@pytest.mark.parametrize("order", ["<", ">"])
def test_third_list_surface_is_parsed(order):
    """node+0x64 list (reader 0x561d1c): per-triangle (vec3, f32, i32) records
    + an indexed mesh.  One node in the PC corpus has it ("splash emitter")."""
    tris = [((0.0, 1.0, 0.0), 1.0, -1), ((0.0, 1.0, 0.0), 1.0, -1)]
    quad = [(0.79, 1.22, 0.33), (0.79, 1.22, 0.95), (-0.79, 1.22, 0.95), (-0.79, 1.22, 0.33)]
    region = _tail(order, 0, surfaces=[(tris, quad, [0, 1, 2, 2, 3, 0])])
    assert len(region) == 157  # the corpus region, byte for byte in size
    r = sr.parse_node_tail(region, 0, len(region), order)
    assert r is not None and r["volumes"] == [[], []]
    (s,) = r["surfaces"]
    assert [t["id"] for t in s["tris"]] == [-1, -1]
    assert np.allclose(s["tris"][0]["vec"], (0, 1, 0)) and s["tris"][0]["value"] == 1.0
    assert np.allclose(s["verts"], quad, atol=1e-6)
    assert list(s["indices"]) == [0, 1, 2, 2, 3, 0]


def test_node_tail_rejects_what_it_cannot_read():
    good = _tail("<", 1, l0=VOLS0[:1])
    assert sr.parse_node_tail(good, 0, len(good)) is not None
    unknown = _tail("<", 1, l0=[dict(type=3, data=(1.0,), pos=(0, 0, 0), quat=Q_ID)])
    assert sr.parse_node_tail(unknown, 0, len(unknown)) is None  # factory 0x524b23 -> null
    mesh_node = bytearray(good)
    struct.pack_into("<I", mesh_node, 12, 1)  # cnt34 inner count != 0: mesh bindings
    assert sr.parse_node_tail(bytes(mesh_node), 0, len(mesh_node)) is None
    flagged = bytearray(good)
    flagged[20] = 1  # node+0x30 object present
    assert sr.parse_node_tail(bytes(flagged), 0, len(flagged)) is None
    assert sr.parse_node_tail(good[:30], 0, 30) is None  # truncated
    assert sr.parse_node_tail(good[:8], 0, None) is None


@pytest.mark.parametrize("order", ["<", ">"])
def test_skeleton_records_expose_volumes_and_keep_existing_fields(order):
    h = _header(order)
    recs = sr.parse(h)
    assert [r["name"] for r in recs] == [nm for nm, *_ in BONES]
    assert [r["parent"] for r in recs] == [par - 1 for _, _, _, par, _ in BONES]
    for r in recs:
        assert set(r) >= {"name", "parent", "body", "entries", "volumes", "offset"}
        assert sr.is_node_record(h, r["offset"], order)
    vols = {r["name"]: r["volumes"] for r in recs}
    assert vols["Bip"] == [[], []] and vols["Head"] == [[], []]  # last node: open end
    assert [v["type"] for v in vols["Spine2"][0]] == [7, 6, 5, 4]
    assert [v["type"] for v in vols["L Hand"][0]] == [5]
    assert [v["type"] for v in vols["L Hand"][1]] == [5]
    for got, want in zip(vols["Spine2"][0], VOLS0):
        _check_volume(got, want)
    assert sr.node_volumes(h, order)[1][0] == "Spine2"


def test_truncated_synthetic_headers_still_decode_without_volumes():
    """Headers that stop after [f1][parent] (the older test fixtures) keep
    decoding; their records simply carry volumes=None."""
    from conftest import build_model_header, synthetic_nodes

    h = build_model_header(synthetic_nodes(), "<")
    recs = sr.parse(h)
    assert recs and all(r["volumes"] is None for r in recs)
    sk = es.skeleton_from_header(h, "x")
    assert all("collision_volumes" not in b for b in sk["bones"])


@pytest.mark.parametrize("order", ["<", ">"])
def test_skeleton_json_gains_optional_volumes_and_nothing_else_changes(order):
    with_v = es.skeleton_from_header(_header(order), "fam")
    without = es.skeleton_from_header(_header(order, with_volumes=False), "fam")
    assert with_v["bone_count"] == without["bone_count"] == len(BONES) + 1
    stripped = [{k: v for k, v in b.items() if k != "collision_volumes"} for b in with_v["bones"]]
    assert stripped == without["bones"], "rest pose / hierarchy / names must be untouched"
    assert {k: v for k, v in with_v.items() if k != "bones"} == {
        k: v for k, v in without.items() if k != "bones"
    }
    by_name = {b["name"]: b for b in with_v["bones"]}
    assert "collision_volumes" not in by_name["Bip"] and "collision_volumes" not in by_name["Head"]
    spine = by_name["Spine2"]["collision_volumes"]
    assert [v["type"] for v in spine] == ["capsule", "sphere", "box", "convex_mesh"]
    assert spine[0]["diameter"] == pytest.approx(0.1429) and spine[0]["height"] == pytest.approx(
        0.2428
    )
    assert spine[0]["quat_xyzw"] == [0.0, 0.6, 0.0, 0.8] and spine[0]["scene"] == 0
    assert spine[1]["radius"] == pytest.approx(0.07)
    assert spine[2]["size"] == [0.2, 0.1, 0.05]
    assert spine[3]["cooked_blob_bytes"] == len(COOKED) and len(spine[3]["verts"]) == 4
    assert spine[3]["indices"] == INDICES
    hand = by_name["L Hand"]["collision_volumes"]
    assert [(v["type"], v["scene"]) for v in hand] == [("box", 0), ("box", 1)]
    import json

    json.dumps(with_v)  # plain JSON types only


def test_bind_is_unaffected_by_volume_data(tmp_path):
    import contextlib
    import io

    import build_bind_file as bbf

    outs = []
    for flag in (True, False):
        src = tmp_path / ("m%d.model" % flag)
        src.write_bytes(_header("<", with_volumes=flag))
        dst = tmp_path / ("b%d.npz" % flag)
        with contextlib.redirect_stdout(io.StringIO()):
            bbf.build(str(src), None, str(dst))
        outs.append(np.load(dst, allow_pickle=True))
    for key in ("Rb", "tb", "tloc", "par", "mask", "names"):
        assert np.array_equal(outs[0][key], outs[1][key]), key
