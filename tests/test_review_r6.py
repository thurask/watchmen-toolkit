"""Corrections from the independent review of the true-handed frame (1.4.0).

- the SENSE of the yaw numbers of anim_meta (they are the engine's heading
  angle, the opposite of the right-handed yaw of the GLB node), and the turn of
  the pair offset for a master that starts turned;
- two rules of the true frame that no test pinned: character parts without
  normals keep the file's triangle order, and the OBJ's `vn` lines are reflected;
- frame.reflect_gltf: bounds of rotation / matrix accessors, and overlapping
  accessors.
"""

import math
import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import frame
import variant_glb as vg
import watchmen_extract as we

import test_frame as tfr
from conftest import parse_glb, quat_xyzw_to_mat


# ---------------------------------------------------------------- yaw sense
def _engine_yaw_quat(deg):
    """Engine root quaternion (x, y, z, w) whose anim_meta yaw is `deg`."""
    h = math.radians(deg) / 2.0
    return [0.0, math.sin(h), 0.0, math.cos(h)]


def _engine_rotate(q, v):
    """The engine turns a vector as conj(q) v q: the matrix of the conjugate,
    which is the rotation the GLB node (it stores the conjugate) applies."""
    x, y, z, w = q
    return quat_xyzw_to_mat([-x, -y, -z, w]) @ np.asarray(v, float)


@pytest.mark.parametrize("deg", [90.0, -90.0, 35.0, -120.0])
def test_a_yaw_is_minus_the_right_handed_yaw_of_the_glb_rotation(deg):
    q = _engine_yaw_quat(deg)
    assert am._yaw_deg(q) == pytest.approx(deg)
    glb_rotation = [-q[0], -q[1], -q[2], q[3]]  # what the GLB node holds
    f = quat_xyzw_to_mat(glb_rotation) @ np.array([0.0, 0.0, 1.0])
    right_handed = math.degrees(math.atan2(f[0], f[2]))  # +Z towards +X is positive
    assert right_handed == pytest.approx(-deg)
    # the same in the true frame: both numbers change sign together
    ft = quat_xyzw_to_mat(frame.quat(glb_rotation)) @ np.array([0.0, 0.0, 1.0])
    assert math.degrees(math.atan2(ft[0], ft[2])) == pytest.approx(-frame.yaw_deg(deg))
    # true frame, positive yaw: facing turns from +Z towards -X (the character's right)
    if frame.yaw_deg(deg) > 0:
        assert ft[0] < 0


@pytest.mark.parametrize("deg", [90.0, -90.0, 35.0, -120.0])
def test_pair_offset_of_a_turned_master_turns_the_engines_way(deg):
    """placement(): `master node * interact(0)`.  With the master's GamePivot
    turned at t = 0 the offset is turned as the engine turns a vector, which is
    what the GLB hierarchy GamePivot -> interact shows (real clips: 0.1 mm).
    The opposite sense (the code before the review) fails this for every angle."""
    gp, it = (0.3, 1.0, -0.2), (0.25, 0.0, 1.5)
    m = {
        "game_pivot": {"pos_start": list(gp), "yaw_start_deg": deg},
        "interact": {"pos_start": list(it)},
    }
    v = {"game_pivot": {"pos_start": [-0.1, 1.0, 1.4], "yaw_start_deg": 0.0}}
    pl = am.placement(m, v)
    want = np.array(gp) + _engine_rotate(_engine_yaw_quat(deg), it)
    assert pl["partner_start_xz"] == pytest.approx([want[0], want[2]], abs=2e-4)
    assert pl["partner_distance_m"] == pytest.approx(math.hypot(it[0], it[2]), abs=2e-4)
    assert pl["partner_yaw_deg"] == pytest.approx((180.0 + deg + 180.0) % 360.0 - 180.0)
    wrong = am._yaw_rot(deg, it[0], it[2])
    assert math.hypot(gp[0] + wrong[0] - want[0], gp[2] + wrong[1] - want[2]) > 0.1


def test_unturned_master_is_untouched_by_the_sense():
    m = {
        "game_pivot": {"pos_start": [0.3, 1.0, -0.2], "yaw_start_deg": 0.0},
        "interact": {"pos_start": [0.25, 0.0, 1.5]},
    }
    v = {"game_pivot": {"pos_start": [-0.1, 1.0, 1.4], "yaw_start_deg": 0.0}}
    pl = am.placement(m, v)
    assert pl["partner_start_xz"] == [0.55, 1.3] and pl["partner_yaw_deg"] == -180.0


def test_conventions_state_the_yaw_sense_in_the_true_frame_only():
    t = am.conventions("true")["yaw"]
    assert "MINUS" in t and "towards -X" in t and "character's right" in t
    assert "yaw" not in am.CONVENTIONS  # a mirrored file is the 1.3.0 text, byte for byte
    for text in am.CONVENTIONS_TRUE.values():
        assert "counter-clockwise" not in text


# ---------------------------------------------------------------- winding, vn
def _indices(g, k=0):
    p = g.j["meshes"][k]["primitives"][0]
    return p, np.asarray(g.accessor(p["indices"])).reshape(-1, 3)


def test_character_part_without_normals_keeps_the_file_order_in_both_frames(
    tmp_path, monkeypatch, rig
):
    """A part without per-vertex normals cannot be tested for its winding, so
    the file's order is written in both frames: the front face in the true
    frame (the engine culls clockwise in its left-handed space), the back face
    in the mirrored one as in 1.3.0.  Without variant_glb's pre-reversal the
    reflection pass would turn the true file's triangles round."""

    def write(mode):
        vg.write_glb(rig.parts, rig.manifest, tmp_path / (mode + ".glb"), str(rig.bind_npz))
        return parse_glb(tmp_path / (mode + ".glb"))

    gm, gt = tfr.both(monkeypatch, write)
    (pm, im), (pt, it) = _indices(gm), _indices(gt)
    assert "NORMAL" not in pm["attributes"] and "NORMAL" not in pt["attributes"]
    assert im.tolist() == rig.T.tolist()
    assert it.tolist() == rig.T.tolist()
    Pm = np.asarray(gm.accessor(pm["attributes"]["POSITION"]), float)
    Pt = np.asarray(gt.accessor(pt["attributes"]["POSITION"]), float)
    assert np.array_equal(Pt, Pm * [-1, 1, 1])
    # same order on reflected points: every geometric normal is the reflected one, reversed
    nm, nt = tfr.tri_normals(Pm, im), tfr.tri_normals(Pt, it)
    assert np.allclose(nt, -nm * [-1, 1, 1], atol=1e-6)


def test_character_part_with_normals_is_reversed_against_the_mirrored_file(
    tmp_path, monkeypatch, rig
):
    """The counterpart: with normals the majority rule decides in engine numbers
    and the true file is the reversed mirrored one, so both show the normal side."""

    def write(mode):
        parts = [tfr._attr_part(rig, 0.0, "mat_body")]
        vg.write_glb(parts, rig.manifest, tmp_path / (mode + "n.glb"), str(rig.bind_npz))
        return parse_glb(tmp_path / (mode + "n.glb"))

    gm, gt = tfr.both(monkeypatch, write)
    (pm, im), (pt, it) = _indices(gm), _indices(gt)
    assert "NORMAL" in pm["attributes"] and "NORMAL" in pt["attributes"]
    assert it.tolist() == im[:, [0, 2, 1]].tolist()


def test_obj_normals_are_reflected_in_the_true_frame(tmp_path, monkeypatch):
    """`vn` follows `v`: x negated.  (The fixture of test_frame's OBJ test has
    normals along +Z only, so it could not see a missing negation.)"""
    v = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.5), (0.0, 1.0, 0.5)]
    n = [(0.6, 0.0, 0.8), (-0.6, 0.0, 0.8), (0.0, 0.6, 0.8), (1.0, 0.0, 0.0)]
    uv = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    tris = [(0, 2, 1), (0, 3, 2)]

    def write(mode):
        out = tmp_path / mode / "q.obj"
        we._write_obj_mtl(out, "q", v, n, uv, tris, [(0, 4, 0, 2, 56)], ["m"], {}, lambda *a: None)
        return tfr._obj(out)

    (vm, nm, fm, _hm), (vt, nt, ft, _ht) = tfr.both(monkeypatch, write)
    assert np.array_equal(nm, np.array(n)) and np.array_equal(vm, np.array(v))
    assert np.array_equal(nt, np.array(n) * [-1, 1, 1])
    assert np.array_equal(vt, np.array(v) * [-1, 1, 1])
    assert (nt[:, 0] != nm[:, 0]).sum() == 3 and ft == fm


# ---------------------------------------------------------------- reflect_gltf
def test_bounds_of_rotation_and_matrix_accessors_are_swapped_too():
    j, binbuf, d = tfr._doc()
    Aq, Am_ = j["accessors"][d["q"]], j["accessors"][d["m"]]
    Aq["min"], Aq["max"] = d["Q"].min(0).tolist(), d["Q"].max(0).tolist()
    Am_["min"], Am_["max"] = d["M"].min(0).tolist(), d["M"].max(0).tolist()
    frame.reflect_gltf(j, binbuf)
    for key in ("q", "m", "p"):
        A, data = j["accessors"][d[key]], tfr._acc(j, binbuf, d[key])
        assert A["min"] == data.min(0).tolist() and A["max"] == data.max(0).tolist(), key
    assert Aq["min"][1] == pytest.approx(-1.0) and Aq["max"][1] == pytest.approx(-0.2)
    # tangent bounds as before (x and w)
    j, binbuf, d = tfr._doc()
    At = j["accessors"][d["t"]]
    At["min"], At["max"] = d["T4"].min(0).tolist(), d["T4"].max(0).tolist()
    frame.reflect_gltf(j, binbuf)
    data = tfr._acc(j, binbuf, d["t"])
    assert At["min"] == data.min(0).tolist() and At["max"] == data.max(0).tolist()


def test_bounds_that_cannot_be_reflected_are_refused():
    j, binbuf, d = tfr._doc()
    del j["accessors"][d["p"]]["max"]  # a min without a max
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    j, binbuf, d = tfr._doc()
    j["accessors"][d["q"]]["min"] = [0.0, 0.0, 0.0]  # wrong length for a VEC4
    j["accessors"][d["q"]]["max"] = [1.0, 1.0, 1.0]
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)


def _add_accessor(j, like, **over):
    A = dict(j["accessors"][like])
    A.pop("min", None)
    A.pop("max", None)
    A.update(over)
    j["accessors"].append(A)
    return len(j["accessors"]) - 1


def test_two_accessors_on_the_same_bytes_are_reflected_once():
    j, binbuf, d = tfr._doc()
    twin = _add_accessor(j, d["tr"])
    sm = j["animations"][0]["samplers"]
    sm.append({"input": 99, "output": twin})
    j["animations"][0]["channels"].append(
        {"sampler": len(sm) - 1, "target": {"node": 1, "path": "translation"}}
    )
    n = frame.reflect_gltf(j, binbuf)
    assert n == 7
    assert np.array_equal(tfr._acc(j, binbuf, d["tr"]), d["P"][:3] * [-1, 1, 1])


def test_overlapping_accessors_at_different_offsets_are_refused():
    """Two reflected accessors sharing bytes without being the same range would
    be negated twice where they overlap; the guard used to compare start offsets
    only."""
    j, binbuf, d = tfr._doc()
    # a second translation accessor starting one row into POSITION's bytes
    inner = _add_accessor(j, d["p"], byteOffset=12, count=2)
    sm = j["animations"][0]["samplers"]
    sm.append({"input": 99, "output": inner})
    j["animations"][0]["channels"].append(
        {"sampler": len(sm) - 1, "target": {"node": 1, "path": "translation"}}
    )
    before = bytes(binbuf)
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    # same start, shorter range: not the same data either
    j, binbuf, d = tfr._doc()
    short = _add_accessor(j, d["p"], count=2)
    j["animations"][0]["samplers"].append({"input": 99, "output": short})
    j["animations"][0]["channels"].append(
        {"sampler": 2, "target": {"node": 1, "path": "translation"}}
    )
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    assert len(before) == len(binbuf)


def test_an_unreflected_accessor_on_reflected_bytes_is_refused():
    """Data that is not reflected (times, UVs, weights) must not share bytes with
    data that is: one of the two would be wrong afterwards."""
    j, binbuf, d = tfr._doc()
    j["accessors"][d["line"]] = dict(j["accessors"][d["i"]])  # the line list on the triangles
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    j, binbuf, d = tfr._doc()
    # an accessor nothing spatial refers to (a time track, say) inside POSITION's bytes
    _add_accessor(j, d["p"], type="SCALAR", count=3, byteOffset=4)
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    # unreflected accessors may share bytes among themselves
    j, binbuf, d = tfr._doc()
    _add_accessor(j, d["line"])
    assert frame.reflect_gltf(j, binbuf) == 6


def test_vec_returns_a_float_x_and_leaves_the_rest():
    out = frame.vec([1, 2, 3])
    assert out == [-1.0, 2, 3] and isinstance(out[0], float)
    assert isinstance(out[1], int) and isinstance(out[2], int)
    assert "ints stay ints" not in frame.vec.__doc__
