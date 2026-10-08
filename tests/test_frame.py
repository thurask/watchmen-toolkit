"""The coordinate frame of the output (`--frame true|mirrored`, wlib/frame.py).

The engine is left-handed.  1.3.0 wrote its numbers verbatim into right-handed
glTF, which every viewer shows as a mirror image.  The default is now the true
frame (x = -engine x); `--frame mirrored` gives the 1.3.0 frame back.

Everything here is synthetic.  The central invariant: what a viewer finally
shows in the true frame is the reflection of what it shows in the mirrored
frame -- for the skinned vertices of every mesh node (scene or hidden), in the
bind pose and at every key of every animation.
"""

import copy
import json
import pathlib
import math
import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import characters_export as ce
import face_rule
import frame
import fx_meta
import level_meta as lm
import nav_data as nd
import ragdoll_rig as rr
import rig_glb
import variant_glb as vg
import watchmen
import watchmen_extract as we

import test_face_rule as tface
import test_formats_v2 as tf
import test_level_meta as tl
import test_nav_data as tn
import test_ragdoll_rig as trag
from conftest import axis_angle, parse_glb, quat_xyzw_to_mat, skin_vertices

S3 = np.diag([-1.0, 1.0, 1.0])
S4 = np.diag([-1.0, 1.0, 1.0, 1.0])

# the fixtures of other test modules, under names of this one
extract = tl.extract


def both(monkeypatch, fn):
    """fn() run once per frame -> (mirrored result, true result)."""
    out = []
    for mode in ("mirrored", "true"):
        monkeypatch.setenv("WATCHMEN_FRAME", mode)
        out.append(fn(mode))
    monkeypatch.delenv("WATCHMEN_FRAME")
    return out


def tri_normals(P, T):
    P = np.asarray(P, float)
    T = np.asarray(T).reshape(-1, 3)
    return np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])


# ---------------------------------------------------------------- the switch
def test_default_frame_is_true_and_the_switch_is_validated(monkeypatch):
    monkeypatch.delenv("WATCHMEN_FRAME", raising=False)
    assert frame.mode() == "true" and frame.is_true() and frame.marker() == "right-handed-true"
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    assert frame.mode() == "mirrored" and not frame.is_true()
    assert frame.marker() == "engine-mirrored"
    assert frame.mode("true") == "true"  # an explicit value wins
    monkeypatch.setenv("WATCHMEN_FRAME", "left")
    with pytest.raises(ValueError):
        frame.mode()
    assert frame.frame_of({"coordinate_frame": "right-handed-true"}) == "true"
    assert frame.frame_of({"format": "watchmen-anim-meta/2"}) == "mirrored"  # 1.3.0 files
    assert frame.frame_of(None) == "mirrored"


@pytest.mark.parametrize("cmd", watchmen.FRAME_COMMANDS)
def test_cli_frame_option_reaches_every_command_that_writes_the_frame(cmd, monkeypatch, capsys):
    """--frame is taken off the argument list and put into $WATCHMEN_FRAME before
    the command runs; a bad value or a command without frame data is refused."""
    assert "--frame true|mirrored" in watchmen.USAGE[cmd][1]
    seen = {}

    def stop():
        seen["frame"] = os.environ.get("WATCHMEN_FRAME")
        raise OSError("stop here")

    monkeypatch.setattr(watchmen, "_wl", stop)
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    pos = ["A"] * watchmen.USAGE[cmd][0]
    with pytest.raises(OSError):
        watchmen.main(["w", cmd] + pos + ["--frame", "mirrored"])
    assert seen["frame"] == "mirrored"
    assert watchmen.main(["w", cmd] + pos + ["--frame", "sideways"]) == 2
    assert watchmen.main(["w", cmd] + pos + ["--frame"]) == 2
    assert "--frame takes one of: true, mirrored" in capsys.readouterr().out


def test_cli_frame_option_is_refused_where_it_means_nothing(monkeypatch, capsys):
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    for cmd in ("fragment", "hash", "soundmeta", "particlemeta", "text", "bake", "binds"):
        assert cmd not in watchmen.FRAME_COMMANDS
        assert watchmen.main(["w", cmd, "A", "B", "C", "--frame", "mirrored"]) == 2
    assert "--frame applies to:" in capsys.readouterr().out
    assert os.environ["WATCHMEN_FRAME"] == "true"
    assert set(watchmen.FRAME_MODES) == set(frame.MODES)
    assert "--frame true|mirrored" in watchmen.__doc__


def test_extract_parser_has_the_option_too(monkeypatch, tmp_path, capsys):
    """`watchmen extract` strips --frame itself; the extractor run on its own
    (python wlib/watchmen_extract.py) takes it as well."""
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    with pytest.raises(SystemExit):
        we.main(["--help"])
    assert "--frame {true,mirrored}" in capsys.readouterr().out
    naz = tmp_path / "empty.naz"
    naz.write_bytes(b"")
    try:
        we.main([str(naz), "-o", str(tmp_path / "o"), "--frame", "mirrored", "--quiet"])
    except Exception:
        pass  # not an archive: only the option handling is of interest
    assert os.environ["WATCHMEN_FRAME"] == "mirrored"


# ---------------------------------------------------------------- the maths
def test_quaternion_rule_is_conjugation_by_the_reflection():
    rng = np.random.default_rng(7)
    for _ in range(20):
        q = rng.normal(size=4)
        q /= np.linalg.norm(q)
        R = quat_xyzw_to_mat(q)
        assert np.allclose(quat_xyzw_to_mat(frame.quat(q)), S3 @ R @ S3, atol=1e-12)
        assert frame.quat(frame.quat(q)) == pytest.approx(list(q))
        # the engine's convention (conj(q) v q) obeys the same rule
        e = rr.frame_matrix(list(q))
        assert np.allclose(rr.frame_matrix(frame.quat(list(q))), S3 @ e @ S3, atol=1e-12)
    # an automorphism: products of reflected quaternions are reflected products
    a, b = [0.1, 0.5, -0.3, 0.8], [-0.4, 0.2, 0.7, 0.55]
    assert rr.qmul(frame.quat(a), frame.quat(b)) == pytest.approx(frame.quat(rr.qmul(a, b)))


def test_matrix_rule_keeps_proper_rotations():
    rng = np.random.default_rng(8)
    M = np.eye(4)
    M[:3, :3] = axis_angle(rng.uniform(-1, 1, 3), 0.9)
    M[:3, 3] = [0.3, -1.2, 2.0]
    T = frame.mat4(M)
    assert np.allclose(T, S4 @ M @ S4)
    assert np.linalg.det(T[:3, :3]) == pytest.approx(1.0)  # never a negative scale
    assert np.allclose(frame.mat4(T), M)
    flat = M[:3].reshape(-1).tolist()
    assert np.allclose(np.array(frame.mat34(flat)).reshape(3, 4), (S4 @ M @ S4)[:3])
    v = np.array([0.2, 0.4, -0.7, 1.0])
    assert np.allclose(T @ (S4 @ v), S4 @ (M @ v))  # transform of the reflected point


def test_tangent_handedness_flips_with_the_reflection():
    """glTF's bitangent is cross(N, T) * w.  For the reflected normal, tangent
    and stored bitangent the sign that reproduces the bitangent is the opposite
    one -- which is what frame.tangents (and reflect_gltf) write."""
    rng = np.random.default_rng(9)
    n = rng.normal(size=(50, 3))
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    t = np.cross(n, rng.normal(size=(50, 3)))
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    b = np.cross(n, t) * rng.choice([-1.0, 1.0], size=(50, 1))  # mirrored UV islands too
    eng = we.gltf_tangents(n, t, b)
    refl = we.gltf_tangents(n @ S3, t @ S3, b @ S3)  # computed from scratch in the true frame
    assert np.array_equal(frame.tangents(eng), refl)
    assert (refl[:, 3] == -eng[:, 3]).all() and (refl[:, 0] == -eng[:, 0]).all()
    # and the bitangent glTF rebuilds is the reflected one in both frames
    for T4, N, B in ((eng, n, b), (refl, n @ S3, b @ S3)):
        got = np.cross(N, T4[:, :3]) * T4[:, 3:4]
        assert np.allclose(got, -B, atol=1e-6)  # -B: the embedded normal map has green inverted


def test_yaw_and_scalar_helpers():
    assert frame.vec([1.5, 2.0, 3.0]) == [-1.5, 2.0, 3.0]
    assert frame.xz([0.25, 4.0]) == [-0.25, 4.0]
    assert str(frame.vec([0.0, 1.0, 2.0])[0]) == "0.0"  # no -0.0 in a JSON file
    assert frame.yaw_deg(90.0) == -90.0 and frame.yaw_deg(None) is None
    assert frame.yaw_deg(-180.0) == -180.0  # anim_meta's range is [-180, 180)
    assert frame.yaw_deg(180.0, half_open_low=False) == 180.0  # atan2's is (-180, 180]
    assert frame.yaw_deg(-180.0, half_open_low=False) == 180.0
    # a yaw is 2 * atan2(y, w) of the ENGINE quaternion in both frames (the GLB stores
    # the conjugate, so it is minus the right-handed yaw of the GLB node's rotation)
    q = [0.0, math.sin(math.radians(35) / 2), 0.0, math.cos(math.radians(35) / 2)]
    assert am._yaw_deg(q) == pytest.approx(35.0)
    assert am._yaw_deg(frame.quat(q)) == pytest.approx(frame.yaw_deg(35.0))


# ---------------------------------------------------------------- reflect_gltf
def _doc():
    P = np.arange(12, dtype="<f4").reshape(4, 3) + 1
    Q = np.array([[0.1, 0.2, 0.3, 0.9], [0.5, 0.5, 0.5, 0.5], [0, 1, 0, 0]], "<f4")
    M = np.arange(32, dtype="<f4").reshape(2, 16)
    I = np.array([0, 1, 2, 0, 2, 3], "<u4")
    L = np.array([0, 1, 2, 3], "<u4")
    T4 = np.array([[1, 0, 0, 1], [0, 1, 0, -1], [0, 0, 1, 1], [1, 0, 0, -1]], "<f4")
    binbuf = bytearray()
    views, accs = [], []

    def add(a, typ, ct, **kw):
        views.append({"buffer": 0, "byteOffset": len(binbuf), "byteLength": a.nbytes})
        binbuf.extend(a.tobytes())
        accs.append(dict({"bufferView": len(views) - 1, "componentType": ct, "type": typ}, **kw))
        accs[-1]["count"] = len(a)
        return len(accs) - 1

    p = add(P, "VEC3", 5126, min=P.min(0).tolist(), max=P.max(0).tolist())
    t = add(T4, "VEC4", 5126)
    i = add(I, "SCALAR", 5125)
    line = add(L, "SCALAR", 5125)
    q = add(Q, "VEC4", 5126)
    m = add(M, "MAT4", 5126)
    tr = add(P[:3].copy(), "VEC3", 5126)
    j = {
        "asset": {"version": "2.0"},
        "accessors": accs,
        "bufferViews": views,
        "meshes": [
            {
                "primitives": [
                    {"attributes": {"POSITION": p, "TANGENT": t}, "indices": i},
                    {"attributes": {"POSITION": p}, "indices": line, "mode": 1},
                ]
            }
        ],
        "skins": [{"joints": [0, 1], "inverseBindMatrices": m}],
        "nodes": [
            {"translation": [1.0, 2.0, 3.0], "rotation": [0.1, 0.2, 0.3, 0.9], "scale": [2, 3, 4]},
            {"matrix": [float(x) for x in range(16)]},
        ],
        "animations": [
            {
                "samplers": [{"input": 99, "output": q}, {"input": 99, "output": tr}],
                "channels": [
                    {"sampler": 0, "target": {"node": 0, "path": "rotation"}},
                    {"sampler": 1, "target": {"node": 0, "path": "translation"}},
                ],
            }
        ],
    }
    return (
        j,
        binbuf,
        dict(P=P, Q=Q, M=M, I=I, L=L, T4=T4, p=p, t=t, i=i, line=line, q=q, m=m, tr=tr),
    )


def _acc(j, binbuf, i):
    A = j["accessors"][i]
    k = frame._NCOMP[A["type"]]
    off = j["bufferViews"][A["bufferView"]]["byteOffset"]
    return np.frombuffer(bytes(binbuf), frame._NP[A["componentType"]], A["count"] * k, off).reshape(
        A["count"], k
    )


def test_reflect_gltf_rewrites_every_row_of_every_spatial_accessor():
    j, binbuf, d = _doc()
    before = bytes(binbuf)
    n = frame.reflect_gltf(j, binbuf)
    assert n == 6 and len(binbuf) == len(before)  # the line indices are not rewritten
    assert np.array_equal(_acc(j, binbuf, d["p"]), d["P"] * [-1, 1, 1])
    assert np.array_equal(_acc(j, binbuf, d["tr"]), d["P"][:3] * [-1, 1, 1])
    assert np.array_equal(_acc(j, binbuf, d["t"]), d["T4"] * [-1, 1, 1, -1])
    assert np.array_equal(_acc(j, binbuf, d["q"]), d["Q"] * [1, -1, -1, 1])  # all rows
    got = _acc(j, binbuf, d["m"]).reshape(2, 4, 4).transpose(0, 2, 1)  # column-major on disk
    want = d["M"].reshape(2, 4, 4).transpose(0, 2, 1)
    assert np.array_equal(got, np.einsum("ab,kbc,cd->kad", S4, want, S4))
    assert _acc(j, binbuf, d["i"]).ravel().tolist() == [0, 2, 1, 0, 3, 2]  # winding reversed
    assert _acc(j, binbuf, d["line"]).ravel().tolist() == [0, 1, 2, 3]
    A = j["accessors"][d["p"]]
    P = _acc(j, binbuf, d["p"])
    assert A["min"] == P.min(0).tolist() and A["max"] == P.max(0).tolist()
    nd0, nd1 = j["nodes"]
    assert nd0["translation"] == [-1.0, 2.0, 3.0] and nd0["scale"] == [2, 3, 4]
    assert nd0["rotation"] == [0.1, -0.2, -0.3, 0.9]
    M = np.array(nd1["matrix"]).reshape(4, 4).T
    assert np.array_equal(M, S4 @ np.arange(16.0).reshape(4, 4).T @ S4)
    # an involution: a second pass gives the bytes back
    frame.reflect_gltf(j, binbuf)
    assert bytes(binbuf) == before and j["nodes"][0]["translation"] == [1.0, 2.0, 3.0]


def test_reflect_gltf_refuses_what_it_does_not_cover():
    j, binbuf, d = _doc()
    j["meshes"][0]["primitives"][0]["attributes"]["NORMAL"] = d["t"]  # TANGENT's accessor
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    j, binbuf, d = _doc()
    j["meshes"][0]["primitives"][1]["mode"] = 5  # a triangle strip
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    j, binbuf, d = _doc()
    j["accessors"][d["p"]]["sparse"] = {"count": 1}
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    j, binbuf, d = _doc()
    j["meshes"][0]["primitives"][1]["indices"] = d["i"]  # triangles and lines share indices
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)
    j, binbuf, d = _doc()
    del j["meshes"][0]["primitives"][0]["indices"]
    with pytest.raises(frame.FrameError):
        frame.reflect_gltf(j, binbuf)


def test_stamp_and_markers(tmp_path):
    j = {"asset": {"version": "2.0"}}
    assert frame.stamp_gltf(j, "mirrored") == {"asset": {"version": "2.0"}}  # untouched
    frame.stamp_gltf(j, "true")
    w = j["asset"]["extras"]["watchmen"]
    assert w["coordinate_frame"] == "right-handed-true" and "LEFT hand at +X" in w[frame.NOTE_KEY]
    doc = {"format": "x/1", "data": 1}
    assert frame.stamp_json(doc, "mirrored") is doc and list(doc) == ["format", "data"]
    assert list(frame.stamp_json(doc, "true")) == [
        "format",
        "coordinate_frame",
        "coordinate_frame_note",
        "data",
    ]
    assert list(frame.stamp_json({"a": 1}, "true"))[0] == "coordinate_frame"
    assert frame.glb_frame(str(tmp_path / "missing.glb")) is None
    (tmp_path / "x.glb").write_bytes(b"not a glb at all, just bytes")
    assert frame.glb_frame(str(tmp_path / "x.glb")) is None


# ---------------------------------------------------------------- static model GLB
#: a quad at z = 0 as the ENGINE stores it: the triangles wind clockwise against the
#: stored normal (+Z) in a right-handed reading (docs/ENGINE_CONSTANTS.md)
QUAD_V = [(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)]
QUAD_FILE_TRIS = ((0, 2, 1), (0, 3, 2))


def _static(path, normals=True, tris=QUAD_FILE_TRIS, **kw):
    n = np.tile(np.array([0, 0, 1.0], np.float32), (4, 1))
    # tangent +X, stored bitangent +Y: s = +1, so the engine-number w is -1
    tg = we.gltf_tangents(n, np.tile([1.0, 0, 0], (4, 1)), np.tile([0, 1.0, 0], (4, 1)))
    extra = dict(normals=n, tangents=tg) if normals else {}
    extra.update(kw)
    rig_glb.build_rigged_glb(
        path,
        QUAD_V,
        None,
        [(0, 0), (1, 0), (1, 1), (0, 1)],
        None,
        None,
        list(tris),
        [(0, 4, 0, 2, 56)],
        ["m"],
        {},
        {"bone_count": 0, "bones": []},
        None,
        None,
        static=True,
        **extra,
    )
    return parse_glb(path)


def _prim(g, k=0):
    p = g.j["meshes"][0]["primitives"][k]
    get = lambda name: np.asarray(g.accessor(p["attributes"][name]), float)
    return p, get, np.asarray(g.accessor(p["indices"])).reshape(-1, 3)


def test_model_glb_true_frame_is_the_reflection_with_outward_faces(tmp_path, monkeypatch):
    for m in ("mirrored", "true"):
        (tmp_path / m).mkdir()
    gm, gt = both(monkeypatch, lambda m: _static(tmp_path / m / "quad.glb"))
    (pm, am_, im), (pt, at, it) = _prim(gm), _prim(gt)
    assert np.array_equal(at("POSITION"), am_("POSITION") * [-1, 1, 1])
    assert np.array_equal(am_("POSITION"), np.array(QUAD_V, float))  # mirrored = engine numbers
    assert np.array_equal(at("NORMAL"), am_("NORMAL") * [-1, 1, 1])
    assert np.array_equal(at("TANGENT"), am_("TANGENT") * [-1, 1, 1, -1])
    assert at("TANGENT")[:, 3].tolist() == [1.0] * 4 and am_("TANGENT")[:, 3].tolist() == [-1.0] * 4
    assert np.array_equal(at("TEXCOORD_0"), am_("TEXCOORD_0"))
    # winding: the mirrored file needs the flip, the true file is the FILE order
    assert im.tolist() == [[0, 1, 2], [0, 2, 3]]
    assert it.tolist() == [list(t) for t in QUAD_FILE_TRIS]
    for get, idx in ((am_, im), (at, it)):  # CCW triangle normal agrees with NORMAL in both
        fn = tri_normals(get("POSITION"), idx)
        assert (np.einsum("ij,ij->i", fn, get("NORMAL")[idx[:, 0]]) > 0).all()
    A = gt.j["accessors"][pt["attributes"]["POSITION"]]
    assert A["min"] == [-2.0, 0.0, 0.0] and A["max"] == [0.0, 1.0, 0.0]
    # markers: only the true file has one; nothing else differs in the JSON
    assert "extras" not in gm.j["asset"]
    assert gt.j["asset"]["extras"]["watchmen"]["coordinate_frame"] == "right-handed-true"
    jt = copy.deepcopy(gt.j)
    del jt["asset"]["extras"]
    jt["accessors"][pt["attributes"]["POSITION"]].update(
        gm.j["accessors"][pm["attributes"]["POSITION"]]
    )
    assert jt == gm.j
    assert frame.glb_frame(str(tmp_path / "true" / "quad.glb")) == "true"
    assert frame.glb_frame(str(tmp_path / "mirrored" / "quad.glb")) == "mirrored"
    assert "scale" not in json.dumps(gt.j["nodes"])  # the data is reflected, not a node


def test_model_glb_minority_winding_and_no_normals(tmp_path, monkeypatch):
    """A primitive whose file order already agrees with its normals in engine
    numbers (0.15 % of the game's triangles) is kept there and so reversed in
    the true frame: the normal side is the front in both.  Without normals
    nothing can be tested: both frames keep the file order, which is the front
    face in the true frame only."""
    with_n = ((0, 1, 2), (0, 2, 3))
    gm, gt = both(monkeypatch, lambda m: _static(tmp_path / (m + "a.glb"), tris=with_n))
    assert _prim(gm)[2].tolist() == [list(t) for t in with_n]
    assert _prim(gt)[2].tolist() == [[0, 2, 1], [0, 3, 2]]
    for g in (gm, gt):
        _p, get, idx = _prim(g)
        fn = tri_normals(get("POSITION"), idx)
        assert (np.einsum("ij,ij->i", fn, get("NORMAL")[idx[:, 0]]) > 0).all()
    gm, gt = both(monkeypatch, lambda m: _static(tmp_path / (m + "b.glb"), normals=False))
    assert _prim(gm)[2].tolist() == _prim(gt)[2].tolist() == [list(t) for t in QUAD_FILE_TRIS]
    # true frame: file order = counter-clockwise seen from the engine's normal side (+Z)
    assert (tri_normals(_prim(gt)[1]("POSITION"), _prim(gt)[2])[:, 2] > 0).all()
    assert (tri_normals(_prim(gm)[1]("POSITION"), _prim(gm)[2])[:, 2] < 0).all()
    # fix_winding=False means "the file order" in both frames as well
    gm, gt = both(monkeypatch, lambda m: _static(tmp_path / (m + "c.glb"), fix_winding=False))
    assert _prim(gm)[2].tolist() == _prim(gt)[2].tolist() == [list(t) for t in QUAD_FILE_TRIS]


def test_mirrored_frame_never_enters_the_reflection(tmp_path, monkeypatch, rig):
    """--frame mirrored is the code path of before: no pass over the document."""

    def boom(*a, **k):
        raise AssertionError("reflect_gltf called in the mirrored frame")

    monkeypatch.setattr(frame, "reflect_gltf", boom)
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    _static(tmp_path / "s.glb")
    vg.write_glb(rig.parts, rig.manifest, tmp_path / "v.glb", str(rig.bind_npz))
    nd.build_glb(nd.parse_hpd(tn.demo_hpd()), "Demo")
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    with pytest.raises(AssertionError):
        _static(tmp_path / "t.glb")


# ---------------------------------------------------------------- character GLB
def _attr_part(rig, dx, name, has_alpha=False):
    """A part with the engine's per-vertex frame; triangles wound the engine's way
    for a +Z normal where possible (the majority rule decides either way)."""
    rng = np.random.default_rng(int(abs(dx) * 10) + 3)
    n = rng.normal(size=(rig.NV, 3))
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    t = np.cross(n, rng.normal(size=(rig.NV, 3)))
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    at = {
        "normal": n.astype(np.float32),
        "tangent": t.astype(np.float32),
        "bitangent": np.cross(n, t).astype(np.float32),
        "color": np.tile(np.array([128, 64, 255, 255], np.uint8), (rig.NV, 1)),
        "has_color": True,
        "has_alpha": has_alpha,
    }
    part = (rig.V + np.float32(dx), rig.SI, rig.SW, rig.T, rig.UV, name)
    return vg.with_attrs(part, at)


def _full_character(tmp_path, rig, name):
    """Everything write_glb can put into a file: body with NORMAL / TANGENT, a
    weapon, a hidden alternative, two outfits sharing vertex data, the face skin
    with baked face channels, pair metadata and the ragdoll helpers."""
    model = rr.build(trag.build_model())
    names = list(trag.BIND_NAMES)
    np.savez(rig.bind_npz, Rb=rig.Rb, tb=rig.tb, names=np.array(names), par=rig.par)
    helpers = rr.glb_helpers(model, names, rig.Rb, rig.tb)
    tex = {"mat_body": {"diffuse": tface_png(), "normal": tface_png((128, 128, 255))}}
    jacket = [_attr_part(rig, 0.5, "jacket_a")]
    out = tmp_path / name
    vg.write_glb(
        [_attr_part(rig, 0.0, "mat_body")],
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        textures=tex,
        face=tface.face_rig(tmp_path, rig),
        attachments=[("WPN_Bat", [(rig.V + np.float32(3.0),) + rig.parts[0][1:5] + ("bat",)])],
        alt_parts=[("ALT Afro", [_attr_part(rig, 1.0, "afro")])],
        outfit_parts=[
            ("OUTFIT 1 Jacket", jacket, True),
            (
                "OUTFIT 2 Jacket",
                [vg.with_attrs(jacket[0][:5] + ("jacket_b",), jacket[0].attrs)],
                False,
            ),
        ],
        parts_record={
            "mode": "game",
            "alternatives": [{"node": "ALT Afro"}, {"node": "OUTFIT 2 Jacket"}],
            "weapons": {"shown": []},
        },
        meta=_pair_meta(rig),
        face_rule="engine",
        face_idle=False,
        ragdoll=helpers,
    )
    return parse_glb(out)


def tface_png(rgb=(90, 90, 90)):
    import io
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.full((2, 2, 3), rgb, np.uint8)).save(buf, "PNG")
    return buf.getvalue()


def _pair_meta(rig):
    """A table as anim_meta.build computes it (engine numbers, no marker)."""
    dur = (rig.F - 1) / rig.fps
    track = [tface.seg(0.0, 0.05, "IDLE"), tface.seg(0.05, None, "HitLeft", ["DamageL"])]
    st = tface.body_state("Hit", "clip_test", track, duration_s=dur)
    m = {"game_pivot": {"pos_start": [0.3, 1.0, -0.2], "yaw_start_deg": 30.0}}
    m["interact"] = {"pos_start": [0.25, 0.0, 1.5]}
    v = {"game_pivot": {"pos_start": [-0.1, 1.0, 1.4], "yaw_start_deg": -150.0}}
    clip = {
        "used_by": [tface.used("Hit")],
        "duration_s": dur,
        "game_pivot": {
            "yaw_start_deg": 30.0,
            "yaw_end_deg": -180.0,
            "rotation_keyed": True,
            "pos_start": [0.3, 1.0, -0.2],
            "pos_end": [0.0, 1.0, 0.75],
            "position_keyed": True,
        },
        "interact": {"yaw_start_deg": 0.0, "yaw_end_deg": None, "pos_start": [0.25, 0.0, 1.5]},
        "events": [{"id": 5, "playpos": 0.5, "payload": {"m_vvalue1": [-0.7, 0.3, 0.0]}}],
        "pairs": [{"pair": 0, "role": "master", "other_clip": "other", "other_class": "B"}],
    }
    pair = {
        "master_state": "Body/Hit",
        "partner_state": "B/Got",
        "same_duration": True,
        "primary": True,
        "confidence": "high",
        "placement": am.placement(m, v),
    }
    return tface.meta_with([st], {"clip_test": clip}, [pair])


def _skinned(g, node, overrides=None):
    nd_ = g.j["nodes"][node]
    jm = g.skin_matrices(node, nd_["skin"], overrides=overrides)
    out = []
    for p in g.j["meshes"][nd_["mesh"]]["primitives"]:
        V = np.asarray(g.accessor(p["attributes"]["POSITION"]), float)
        J = np.asarray(g.accessor(p["attributes"]["JOINTS_0"]))
        W = np.asarray(g.accessor(p["attributes"]["WEIGHTS_0"]), float)
        out.append(skin_vertices(V, J, W, jm))
    return out


def test_character_true_frame_shows_the_reflection_of_the_mirrored_one(tmp_path, monkeypatch, rig):
    """THE invariant.  Every mesh node of the file -- body, weapon, the hidden
    alternative and outfit, the face on its own skin, the ragdoll proxies --
    skinned from the file's own nodes, inverse binds and animation channels:
    true == reflection of mirrored, in the bind pose and at every key of every
    animation (body clip with baked face channels, the face-pose clips)."""
    gm, gt = both(monkeypatch, lambda m: _full_character(tmp_path, rig, m + ".glb"))
    names = [n.get("name") for n in gt.j["nodes"]]
    assert names == [n.get("name") for n in gm.j["nodes"]]
    mesh_nodes = [i for i, n in enumerate(gt.j["nodes"]) if "mesh" in n]
    kinds = {names[i].split(".")[0].split(" ")[0] for i in mesh_nodes}
    assert kinds >= {"mesh", "WPN_Bat", "ALT", "OUTFIT", "face_mesh", "RB"}
    in_scene = set()

    def walk(k):
        in_scene.add(k)
        for c in gt.j["nodes"][k].get("children", []):
            walk(c)

    for k in gt.j["scenes"][0]["nodes"]:
        walk(k)
    assert any(i not in in_scene for i in mesh_nodes)  # hidden nodes are covered too

    def compare(over_m=None, over_t=None):
        Gm, Gt = gm.global_matrices(over_m), gt.global_matrices(over_t)
        for i in Gm:  # every node: a proper rotation, conjugated by the reflection
            assert np.allclose(Gt[i], S4 @ Gm[i] @ S4, atol=1e-6), names[i]
            assert np.linalg.det(Gt[i][:3, :3]) > 0
        worst = 0.0
        for i in mesh_nodes:
            for a, b in zip(_skinned(gm, i, over_m), _skinned(gt, i, over_t)):
                assert np.allclose(b, a * [-1, 1, 1], atol=1e-5), names[i]
                worst = max(worst, float(np.abs(b - a * [-1, 1, 1]).max()))
        return worst

    compare()  # bind pose
    assert len(gt.j["animations"]) == len(gm.j["animations"]) >= 3
    samples = 0
    for ai, anim in enumerate(gt.j["animations"]):
        times = set()
        for s in anim["samplers"]:
            times.update(float(x) for x in np.ravel(gt.accessor(s["input"])))
        for t in sorted(times):
            compare(gm.sample_at(ai, t), gt.sample_at(ai, t))
            samples += 1
    assert samples >= rig.F + 2
    # the accessors themselves: exact negation, same layout, same bytes elsewhere
    assert len(gt.bin_chunk) == len(gm.bin_chunk)
    assert [a["count"] for a in gt.j["accessors"]] == [a["count"] for a in gm.j["accessors"]]
    for pm, pt in zip(
        (p for m in gm.j["meshes"] for p in m["primitives"]),
        (p for m in gt.j["meshes"] for p in m["primitives"]),
    ):
        im = np.asarray(gm.accessor(pm["indices"])).reshape(-1, 3)
        it = np.asarray(gt.accessor(pt["indices"])).reshape(-1, 3)
        Pm = np.asarray(gm.accessor(pm["attributes"]["POSITION"]))
        Pt = np.asarray(gt.accessor(pt["attributes"]["POSITION"]))
        assert np.array_equal(Pt, Pm * np.float32([-1, 1, 1]))
        if "NORMAL" in pm["attributes"]:
            assert np.array_equal(it, im[:, [0, 2, 1]])
            Nm = np.asarray(gm.accessor(pm["attributes"]["NORMAL"]), float)
            Nt = np.asarray(gt.accessor(pt["attributes"]["NORMAL"]), float)
            assert np.array_equal(Nt, Nm * [-1, 1, 1])
            # the triangle normal of the CCW winding lies on the vertex normals' side
            for P, N, idx in ((Pm, Nm, im), (Pt, Nt, it)):
                s = np.einsum("ij,ij->i", tri_normals(P, idx), N[idx].sum(1))
                assert (s > 0).sum() >= (s < 0).sum()
        if "TANGENT" in pm["attributes"]:
            Tm = np.asarray(gm.accessor(pm["attributes"]["TANGENT"]))
            Tt = np.asarray(gt.accessor(pt["attributes"]["TANGENT"]))
            assert np.array_equal(Tt, Tm * np.float32([-1, 1, 1, -1]))
        for k in ("TEXCOORD_0", "JOINTS_0", "WEIGHTS_0", "COLOR_0"):
            if k in pm["attributes"]:
                assert np.array_equal(
                    gm.accessor(pm["attributes"][k]), gt.accessor(pt["attributes"][k])
                )
    assert any("TANGENT" in p["attributes"] for m in gt.j["meshes"] for p in m["primitives"])


def test_character_true_frame_against_the_engine_input(tmp_path, monkeypatch, rig):
    """The classic checks of test_glb_skinning.py, in the default frame: the joint
    nodes carry S B S, the inverse binds invert it, and the animated vertices are
    the reflection of palette * vertex -- with left-handed input on the left of
    the character ending up at +X."""
    monkeypatch.delenv("WATCHMEN_FRAME", raising=False)
    out = tmp_path / "t.glb"
    vg.write_glb(rig.parts, rig.manifest, out, str(rig.bind_npz))
    g = parse_glb(out)
    w = g.j["asset"]["extras"]["watchmen"]
    assert w["coordinate_frame"] == "right-handed-true"
    assert "LEFT hand is at +X" in w["conventions"]["handedness"]
    assert "MIRROR" not in w["conventions"]["handedness"]
    G = g.global_matrices()
    joints = g.j["skins"][0]["joints"]
    ibm = g.mat4_accessor(g.j["skins"][0]["inverseBindMatrices"])
    for k, jn in enumerate(joints):
        want = S4 @ rig.B4[k] @ S4
        assert np.allclose(G[jn], want, atol=1e-5)
        assert np.allclose(ibm[k] @ want, np.eye(4), atol=1e-5)
        assert "scale" not in g.j["nodes"][jn]
    mesh = [i for i, n in enumerate(g.j["nodes"]) if n.get("mesh") == 0][0]
    p = g.j["meshes"][0]["primitives"][0]
    V = np.asarray(g.accessor(p["attributes"]["POSITION"]), float)
    J = np.asarray(g.accessor(p["attributes"]["JOINTS_0"]))
    W = np.asarray(g.accessor(p["attributes"]["WEIGHTS_0"]), float)
    assert np.allclose(V, rig.V * [-1, 1, 1])
    for f in range(rig.F):
        jm = g.skin_matrices(mesh, 0, overrides=g.sample_at(0, f / rig.fps))
        pal = np.einsum("kab,kbc->kac", rig.world[f], rig.invB4)
        engine = skin_vertices(rig.V.astype(float), J, W, pal)  # what the game shows, in x-left
        assert np.allclose(skin_vertices(V, J, W, jm), engine * [-1, 1, 1], atol=1e-5)


def test_clip_extras_follow_the_frame_of_the_glb(tmp_path, monkeypatch, rig):
    gm, gt = both(monkeypatch, lambda m: _full_character(tmp_path, rig, m + ".glb"))
    em = [a for a in gm.j["animations"] if a["name"] == "clip_test"][0]["extras"]["watchmen"]
    et = [a for a in gt.j["animations"] if a["name"] == "clip_test"][0]["extras"]["watchmen"]
    assert em["game_pivot"]["pos_start"] == [0.3, 1.0, -0.2]
    assert et["game_pivot"]["pos_start"] == [-0.3, 1.0, -0.2]
    assert et["game_pivot"]["pos_end"] == [0.0, 1.0, 0.75]
    assert (et["game_pivot"]["yaw_start_deg"], et["game_pivot"]["yaw_end_deg"]) == (-30.0, -180.0)
    assert (
        et["interact"]["pos_start"] == [-0.25, 0.0, 1.5] and et["interact"]["yaw_end_deg"] is None
    )
    pm, pt = em["pairs"][0]["placement"], et["pairs"][0]["placement"]
    for k in am._PLACEMENT_XZ_KEYS:
        assert pt[k] == [-pm[k][0] + 0.0, pm[k][1]]
    assert pt["partner_yaw_deg"] == frame.yaw_deg(pm["partner_yaw_deg"])
    assert pt["partner_distance_m"] == pm["partner_distance_m"]
    # raw engine values are copied as they are, and the conventions say so
    assert et["events"][0]["payload"] == em["events"][0]["payload"]
    cv = gt.j["asset"]["extras"]["watchmen"]["conventions"]
    assert "m_vvalue" in cv["engine_values"] and "engine_values" not in am.CONVENTIONS
    assert gm.j["asset"]["extras"]["watchmen"]["conventions"] == am.CONVENTIONS
    assert "coordinate_frame" not in gm.j["asset"]["extras"]["watchmen"]


# ---------------------------------------------------------------- anim_meta
def _clip_facts(pos, yaw, interact=None):
    f = {"game_pivot": {"pos_start": list(pos), "yaw_start_deg": yaw}}
    if interact is not None:
        f["interact"] = {"pos_start": list(interact)}
    return f


@pytest.mark.parametrize("yaw", [0.0, 30.0, -90.0, 135.0])
def test_placement_of_reflected_clips_is_the_reflected_placement(yaw):
    """The rule check for xz pairs and yaw: the engine's placement formula run on
    the reflected clip facts gives what reflect_placement makes of the original."""
    m = _clip_facts([0.3, 1.0, -0.2], yaw, [0.25, 0.0, 1.5])
    v = _clip_facts([-0.1, 1.0, 1.4], -150.0)
    want = am.placement(am_reflect_facts(m), am_reflect_facts(v))
    got = am.reflect_placement(am.placement(m, v))
    for k in am._PLACEMENT_XZ_KEYS:
        assert got[k] == pytest.approx(want[k], abs=2e-4)
    assert got["partner_yaw_deg"] == pytest.approx(want["partner_yaw_deg"])
    assert got["check"]["partner_game_pivot_start_xz"] == pytest.approx(
        want["check"]["partner_game_pivot_start_xz"]
    )
    assert got["check"]["agreement_m"] == pytest.approx(want["check"]["agreement_m"], abs=2e-4)
    assert got["partner_distance_m"] == pytest.approx(want["partner_distance_m"], abs=2e-4)


def am_reflect_facts(f):
    out = copy.deepcopy(f)
    for k in ("game_pivot", "interact"):
        if k in out:
            am.reflect_root(out[k])
    return out


def test_meta_frame_conversion(rig, monkeypatch):
    meta = _pair_meta(rig)
    meta["format"] = am.FORMAT
    meta["conventions"] = am.CONVENTIONS
    meta["fx"] = {"camera": {"cut_placement": dict(fx_meta._CUT_PLACEMENT)}}
    meta["classes"]["Body"]["states"][0]["impact"] = {"position": [0.5, 1.2, 0.3]}
    shared = meta["clips"]["clip_test"]["game_pivot"]
    meta["clips"]["alias"] = {"game_pivot": shared}  # one record under two names: once only
    before = copy.deepcopy(meta)
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    assert am.apply_frame(meta) is meta and meta == before  # mirrored: nothing at all
    assert am.to_frame(meta) is meta
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    t = am.to_frame(meta)
    assert t is not meta and meta == before  # a converted copy
    assert t["coordinate_frame"] == "right-handed-true" and frame.frame_of(t) == "true"
    assert t["clips"]["clip_test"]["game_pivot"]["pos_start"] == [-0.3, 1.0, -0.2]
    assert t["clips"]["alias"]["game_pivot"]["pos_start"] == [-0.3, 1.0, -0.2]
    assert t["classes"]["Body"]["states"][0]["impact"] == {"position": [0.5, 1.2, 0.3]}  # raw
    assert t["clips"]["clip_test"]["events"] == before["clips"]["clip_test"]["events"]
    assert t["conventions"] is am.CONVENTIONS_TRUE
    assert "x = -engine x" in t["fx"]["camera"]["cut_placement"]["coordinates"]
    assert t["fx"]["camera"]["cut_placement"]["angle"] == fx_meta._CUT_PLACEMENT["angle"]
    assert am.to_frame(t) is t
    back = am.to_frame(t, "mirrored")
    assert "coordinate_frame" not in back and back == before
    # apply_frame: build()'s last step, in place, marker right after `format`
    m2 = copy.deepcopy(before)
    assert am.apply_frame(m2) is m2 and m2 == t
    keys = list(am.apply_frame(dict(copy.deepcopy(before), format=am.FORMAT)))
    assert "coordinate_frame" in keys
    ordered = {"format": am.FORMAT, "conventions": {}, "clips": {}, "pairs": []}
    assert list(am.apply_frame(ordered))[:3] == [
        "format",
        "coordinate_frame",
        "coordinate_frame_note",
    ]


def test_conventions_per_frame():
    assert am.conventions("mirrored") is am.CONVENTIONS and "MIRROR" in am.CONVENTIONS["handedness"]
    t = am.conventions("true")
    assert set(t) == set(am.CONVENTIONS) | {"engine_values", "yaw"}
    assert "Nothing has to be mirrored" in t["handedness"] and "truthful" in t["handedness"]
    assert {k for k in am.CONVENTIONS if t[k] != am.CONVENTIONS[k]} == {"handedness"}


def _resume(tmp_path, monkeypatch, table):
    out = tmp_path / "CHARS"
    out.mkdir()
    (out / "anim_meta.json").write_text(json.dumps(dict(table, marker="cached")))
    built = []

    def build(extract_out, binds=None):
        built.append(extract_out)
        return am.apply_frame(dict(tfs_current(), marker="new"))

    monkeypatch.setattr(am, "build", build)
    monkeypatch.setattr(am, "find_class_fragments", lambda ex: {"Enemy01": "x"})
    monkeypatch.setattr(am, "summary", lambda m: "summary")
    monkeypatch.setattr(face_rule, "find_face_fragments", lambda ex: {"Enemy01Face": "x"})
    got = ce.animation_meta(str(tmp_path), str(out))
    return got["marker"], len(built), json.loads((out / "anim_meta.json").read_text())


def tfs_current():
    import combat_meta

    return {
        "format": am.FORMAT,
        "revision": am.REVISION,
        "face_format": face_rule.FACE_FORMAT,
        "combat_format": combat_meta.COMBAT_FORMAT,
        "fx_format": fx_meta.FORMAT,
    }


@pytest.mark.parametrize(
    "mode,stored,want",
    [
        ("true", "true", ("cached", 0)),
        ("true", "mirrored", ("new", 1)),  # a folder written before the default changed
        ("mirrored", "true", ("new", 1)),
        ("mirrored", "mirrored", ("cached", 0)),
    ],
)
def test_resumed_export_does_not_reuse_a_table_in_the_other_frame(
    tmp_path, monkeypatch, mode, stored, want
):
    monkeypatch.setenv("WATCHMEN_FRAME", mode)
    table = tfs_current()
    if stored == "true":
        table["coordinate_frame"] = "right-handed-true"
    marker, builds, on_disk = _resume(tmp_path, monkeypatch, table)
    assert (marker, builds) == want
    assert frame.frame_of(on_disk) == mode  # what is on disk afterwards is in the run's frame


def test_resumed_export_rewrites_a_glb_in_the_other_frame(tmp_path, monkeypatch, rig):
    """characters_export skips an existing GLB only when it is in the run's frame."""
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    old = tmp_path / "old.glb"
    vg.write_glb(rig.parts, rig.manifest, old, str(rig.bind_npz))
    assert frame.glb_frame(str(old)) == "mirrored"
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    new = tmp_path / "new.glb"
    vg.write_glb(rig.parts, rig.manifest, new, str(rig.bind_npz))
    assert frame.glb_frame(str(new)) == "true"
    assert ce.glb_is_current(str(new)) and not ce.glb_is_current(str(old))
    assert not ce.glb_is_current(str(tmp_path / "missing.glb"))
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    assert ce.glb_is_current(str(old)) and not ce.glb_is_current(str(new))


# ---------------------------------------------------------------- fx
def test_cut_camera_in_the_true_frame_is_the_reflected_camera():
    actor, target, cam = [1.0, 0.0, 2.0], [2.5, 0.0, 3.0], [4.0, 1.5, 0.0]
    R = lambda p: [-p[0], p[1], p[2]]
    for cut in (
        {"distance_m": 3.0, "height_m": 1.5, "angle_deg": 40.0},
        {"distance_m": 3.0, "height_m": 1.5, "angle_deg": -75.0, "look_at": "attack_target"},
        {"distance_m": 2.0, "height_m": 1.0, "angle_deg": 0.0},
        {"distance_m": 2.0, "keep_previous_position": True},
    ):
        e = fx_meta.cut_camera(cut, actor, target, previous=[9.0, 1.0, 1.0], camera=cam)
        t = fx_meta.cut_camera(
            cut, R(actor), R(target), previous=R([9.0, 1.0, 1.0]), camera=R(cam), frame="true"
        )
        assert t["position"] == pytest.approx(R(e["position"]))
        assert t["look_at"] == pytest.approx(R(e["look_at"])) and t["side"] == e["side"]
    # the true-frame formulas the conventions quote
    cut = {"distance_m": 3.0, "height_m": 1.5, "angle_deg": 40.0}
    a, tg = R(actor), R(target)
    d = np.array([tg[0] - a[0], tg[2] - a[2]])
    h = math.atan2(d[0], d[1]) - math.radians(40.0)
    want = [a[0] + 3.0 * math.sin(h), 1.5, a[2] + 3.0 * math.cos(h)]
    assert fx_meta.cut_camera(cut, a, tg, frame="true")["position"] == pytest.approx(want, abs=1e-5)
    line = np.array([tg[0] - a[0], 0.0, tg[2] - a[2]])
    v = np.array([line[2], 0.0, -line[0]]) / np.hypot(line[0], line[2])
    side = fx_meta.cut_camera({"distance_m": 2.0, "angle_deg": 0.0}, a, tg, frame="true")
    assert side["position"] == pytest.approx((np.array(a) + line / 2 + 2.0 * v).tolist(), abs=1e-5)
    with pytest.raises(ValueError):
        fx_meta.cut_camera(cut, actor, target, frame="engine")
    assert fx_meta.cut_placement("mirrored") == fx_meta._CUT_PLACEMENT
    assert "frame='true'" in fx_meta.cut_placement("true")["coordinates"]


def test_fx_attachment_space_names_the_engine_frame(monkeypatch):
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    assert fx_meta._attachment_space() == fx_meta._ATTACHMENT_SPACE
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    assert "x = -engine x" in fx_meta._attachment_space()


# ---------------------------------------------------------------- ragdoll
@pytest.fixture
def model():
    return rr.build(trag.build_model())


def test_reflected_rig_frames_axes_and_limits(model):
    t = rr.reflect_rig(model)
    assert rr.reflect_rig(t) == model and t is not model  # an involution, on a copy
    for jm, jt in zip(model["joints"], t["joints"]):
        for key in ("swing1", "swing2", "twist", "linear", "projection", "motors_file"):
            assert jt[key] == jm[key]  # every limit keeps its value
        for key, ax in (
            ("child_frame", "axes_in_child_bone"),
            ("parent_frame", "axes_in_parent_bone"),
        ):
            qm, qt = jm[key]["quat_xyzw"], jt[key]["quat_xyzw"]
            Fm, Ft = rr.frame_matrix(qm), rr.frame_matrix(qt)
            assert np.allclose(Ft, S3 @ Fm @ S3, atol=1e-6) and np.linalg.det(Ft) > 0
            assert jt[key]["pos"] == pytest.approx((S3 @ np.array(jm[key]["pos"])).tolist())
            # the listed axes are those of the reflected frame
            assert jt[key][ax]["twist_x"] == pytest.approx(rr.rot(qt, [1, 0, 0]), abs=2e-6)
            assert jt[key][ax]["swing1_y"] == pytest.approx(rr.rot(qt, [0, 1, 0]), abs=2e-6)
            assert jt[key][ax]["swing2_z"] == pytest.approx(rr.rot(qt, [0, 0, 1]), abs=2e-6)
            # limits: a turn by +a about the twist axis of the mirrored frame is the
            # turn by +a about the twist axis of the reflected frame; swings change sign
            a = 0.37
            for axis, sign in ((0, 1.0), (1, -1.0), (2, -1.0)):
                turn_m = axis_angle(Fm[:, axis], a)
                turn_t = axis_angle(Ft[:, axis], sign * a)
                assert np.allclose(S3 @ turn_m @ S3, turn_t, atol=1e-6)
    for bm, bt in zip(model["bodies"], t["bodies"]):
        assert bt["bind_world_pos"] == pytest.approx((S3 @ np.array(bm["bind_world_pos"])).tolist())
        assert bt["mass"] == bm["mass"]
        for sm, st in zip(bm["shapes"], bt["shapes"]):
            assert st["contact"] == sm.get("contact") or "contact" not in sm
            assert st["local_pos"] == pytest.approx((S3 @ np.array(sm["local_pos"])).tolist())
    for nm, nt in zip(model["skeleton"], t["skeleton"]):
        assert nt["local_quat_xyzw"] == frame.quat(nm["local_quat_xyzw"])


def test_swing_limits_are_symmetric_so_their_sign_change_cannot_show(model):
    """The derivation leans on it: a swing limit is one half-angle (no low / high)."""
    for j in model["joints"]:
        assert set(j["swing1"]) >= {"limit_deg"} and "low_deg" not in j["swing1"]
        assert "low_deg" in j["twist"] and "high_deg" in j["twist"]


def test_reflected_rig_with_reflected_binds_is_the_reflected_geometry(model, rig):
    """The whole chain at once: helpers built from the reflected rig and the
    reflected binds are the reflection of the helpers built from the engine
    numbers -- vertices, joint frames, and the matrices in the extras."""
    names = list(trag.BIND_NAMES)
    eng = rr.glb_helpers(model, names, rig.Rb, rig.tb, frame="mirrored")
    Rt = np.array([S3 @ R @ S3 for R in rig.Rb])
    refl = rr.glb_helpers(rr.reflect_rig(model), names, Rt, rig.tb * [-1, 1, 1], frame="mirrored")
    out = rr.glb_helpers(model, names, rig.Rb, rig.tb, frame="true")
    assert len(eng["shapes"]) == len(refl["shapes"]) == 5
    for a, b, o in zip(eng["shapes"], refl["shapes"], out["shapes"]):
        # the same solid: a capsule / box is its own mirror image, so the two
        # vertex sets coincide (not vertex by vertex: the proxy is re-built in
        # the reflected shape frame)
        want = a["verts"] * np.float32([-1, 1, 1])
        dist = np.linalg.norm(b["verts"][:, None] - want[None], axis=-1)
        assert dist.min(1).max() < 1e-5 and dist.min(0).max() < 1e-5
        assert np.array_equal(o["verts"], a["verts"])  # write_glb reflects the geometry
        assert o["extras"] == b["extras"]  # ... and the extras are final
        Wm = np.array(a["extras"]["bind_world_matrix"]).reshape(3, 4)
        Wt = np.array(o["extras"]["bind_world_matrix"]).reshape(3, 4)
        assert np.allclose(Wt, (S4 @ np.vstack([Wm, [0, 0, 0, 1]]) @ S4)[:3], atol=1e-6)
    for a, b, o in zip(eng["joints"], refl["joints"], out["joints"]):
        assert b["translation"] == pytest.approx(frame.vec(a["translation"]))
        qa, qb = np.array(a["rotation"]), np.array(frame.quat(b["rotation"]))
        assert min(np.abs(qa - qb).max(), np.abs(qa + qb).max()) < 1e-6
        assert o["translation"] == a["translation"] and o["extras"] == b["extras"]
        assert o["extras"]["twist"] == a["extras"]["twist"]
        assert o["extras"]["blender"]["limit_ang_x"] == a["extras"]["blender"]["limit_ang_x"]


def test_ragdoll_nodes_in_the_glb_match_their_extras_in_both_frames(tmp_path, monkeypatch, rig):
    """In the written file an RJ node's transform is the frame its extras state
    (Blender matrix included) and an RB proxy sits where its bind_world_matrix
    says, wound outward -- in the mirrored and in the true frame."""
    gm, gt = both(monkeypatch, lambda m: _full_character(tmp_path, rig, m + ".glb"))
    C = np.array([[1.0, 0, 0], [0, 0, -1], [0, 1, 0]])
    for g in (gm, gt):
        j = g.j
        names = [n.get("name") for n in j["nodes"]]
        jn = j["nodes"][names.index("RJ.L Forearm")]
        R = quat_xyzw_to_mat(jn["rotation"])
        Mb = np.array(jn["extras"]["watchmen"]["ragdoll"]["blender"]["bind_world_matrix"])
        Mb = Mb.reshape(3, 4)
        assert np.allclose(Mb[:, :3], C @ R @ C.T, atol=1e-6)
        t = jn["translation"]
        assert Mb[:, 3] == pytest.approx([t[0], -t[2], t[1]], abs=1e-6)
        for nm in ("RB.L UpperArm.0", "RB.Pelvis.0"):
            node = j["nodes"][names.index(nm)]
            prim = j["meshes"][node["mesh"]]["primitives"][0]
            V = np.asarray(g.accessor(prim["attributes"]["POSITION"]), float)
            W = np.array(node["extras"]["watchmen"]["ragdoll"]["bind_world_matrix"]).reshape(3, 4)
            local = (V - W[:, 3]) @ W[:, :3]  # back in the shape's own frame
            assert np.abs(local.mean(0)).max() < 0.02  # centred on the shape frame
            T = np.asarray(g.accessor(prim["indices"])).reshape(-1, 3)
            out = np.einsum("ij,ij->i", tri_normals(V, T), V[T].mean(1) - V.mean(0))
            assert (out > 0).all()  # outward in both frames
    names = [n.get("name") for n in gt.j["nodes"]]
    a = gm.j["nodes"][names.index("RJ.L Forearm")]
    b = gt.j["nodes"][names.index("RJ.L Forearm")]
    assert b["translation"] == pytest.approx(frame.vec(a["translation"]))
    assert b["rotation"] == pytest.approx(frame.quat(a["rotation"]))
    lim = lambda n: {
        k: n["extras"]["watchmen"]["ragdoll"][k] for k in ("twist", "swing1", "swing2")
    }
    assert lim(a) == lim(b)


def test_ragdoll_sidecar_follows_the_frame(model, monkeypatch):
    dm, dt = both(monkeypatch, lambda m: rr.sidecar(model, list(trag.BIND_NAMES), glb="X.glb"))
    assert "coordinate_frame" not in dm and dm["conventions"] is rr.CONVENTIONS
    assert list(dt)[:2] == ["format", "coordinate_frame"] and dt["format"] == rr.FORMAT
    assert dt["conventions"] is rr.CONVENTIONS_TRUE
    assert "twist low..high included" in dt["conventions"]["axes"]
    assert "mirror image" in dm["conventions"]["axes"]
    assert dt["bodies"] == rr.reflect_rig(model)["bodies"] and dm["bodies"] == model["bodies"]
    for a, b in zip(dm["joints"], dt["joints"]):
        assert b["child_frame"]["pos"] == frame.vec(a["child_frame"]["pos"])
        assert b["blender"] == a["blender"]  # limits: the same numbers
    assert dt["common"] == dm["common"] and dt["joint_nodes"] == dm["joint_nodes"]
    assert rr.sidecar(model, frame="mirrored") == rr.sidecar(model, frame="mirrored")
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")
    assert rr.sidecar(model, frame="true")["coordinate_frame"] == "right-handed-true"


def test_convex_shape_vertices_are_reflected_and_keep_their_triangles():
    s = {
        "type": "convex_mesh",
        "local_pos": [0.1, 0.0, 0.0],
        "local_quat_xyzw": [0.0, 0.0, 0.0, 1.0],
        "file": {
            "mode": 1,
            "vertices": [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]],
            "indices": [0, 1, 2],
        },
    }
    rig_ = {"bodies": [{"bind_world_pos": [0, 0, 0], "bind_world_quat_xyzw": [0, 0, 0, 1]}]}
    rig_["bodies"][0]["shapes"] = [s]
    t = rr.reflect_rig(rig_)["bodies"][0]["shapes"][0]
    assert t["file"]["vertices"][0] == [-1.0, 0, 0] and t["file"]["indices"] == [0, 1, 2]
    assert s["file"]["vertices"][0] == [1.0, 0, 0]  # the input is not touched
    assert t["local_pos"] == [-0.1, 0.0, 0.0]


# ---------------------------------------------------------------- level
Q = [0.18, 0.55, -0.12, 0.8]
Q = [x / math.sqrt(sum(y * y for y in Q)) for x in Q]


def test_level_gltf_transform_places_the_reflected_glb_at_the_reflected_place():
    """A vertex v of a mirrored GLB placed with the mirrored `gltf` lands on the
    engine's world position; the same vertex of the true GLB (x negated) placed
    with the true `gltf` lands on its reflection."""
    pos = [3.0, 1.0, -2.0]
    gm, gt = lm.gltf_trs(pos, Q, "mirrored"), lm.gltf_trs(pos, Q, "true")
    assert gm["translation"] == pos and gt["translation"] == [-3.0, 1.0, -2.0]
    assert gt["rotation"] == pytest.approx(frame.quat(gm["rotation"]))
    assert gt["rotation"] == pytest.approx([-Q[0], Q[1], Q[2], Q[3]], abs=1e-6)
    rng = np.random.default_rng(3)
    for v in rng.uniform(-2, 2, (10, 3)):
        engine = np.array(lm.q_rot(Q, list(v))) + pos  # the engine's own rule
        pm = quat_xyzw_to_mat(gm["rotation"]) @ v + gm["translation"]
        pt = quat_xyzw_to_mat(gt["rotation"]) @ (S3 @ v) + gt["translation"]
        assert np.allclose(pm, engine, atol=1e-5)
        assert np.allclose(pt, S3 @ engine, atol=1e-5)


def test_level_file_keeps_engine_values_and_recomputes_the_gltf_ones(extract, monkeypatch):
    def build(_mode):
        (found,) = [x for x in lm.levels(str(extract)) if x[1] == "Lvl"]
        return lm.build_level(found[0], found[1], found[2], str(extract))

    m, t = both(monkeypatch, build)
    assert "coordinate_frame" not in m and m["conventions"] is lm.CONVENTIONS
    assert list(t)[:3] == ["format", "coordinate_frame", "coordinate_frame_note"]
    assert t["conventions"] is lm.CONVENTIONS_TRUE
    assert "no root scale" in t["conventions"]["handedness"]
    assert "scale (-1, 1, 1)" in m["conventions"]["handedness"]
    (cm,), (ct,) = m["characters"], t["characters"]
    assert ct["world"] == cm["world"]  # engine values stay
    assert cm["world"]["pos"] == pytest.approx([5.0, 0.0, 0.0], abs=1e-5)
    assert ct["gltf"]["translation"] == pytest.approx([-5.0, 0.0, 0.0], abs=1e-5)
    q = ct["world"]["quat"]
    assert ct["gltf"]["rotation"] == pytest.approx([-q[0], q[1], q[2], q[3]])
    assert cm["forward"] == pytest.approx([-1.0, 0.0, 0.0], abs=1e-4)
    assert ct["forward"] == pytest.approx([1.0, 0.0, 0.0], abs=1e-4)
    assert ct["yaw_deg"] == pytest.approx(-cm["yaw_deg"]) and abs(cm["yaw_deg"]) == 90.0
    # forward / yaw_deg describe the placed GLB: its local +Z under `gltf`
    assert quat_xyzw_to_mat(ct["gltf"]["rotation"]) @ [0, 0, 1.0] == pytest.approx(
        ct["forward"], abs=1e-4
    )
    assert quat_xyzw_to_mat(cm["gltf"]["rotation"]) @ [0, 0, 1.0] == pytest.approx(
        cm["forward"], abs=1e-4
    )
    # everything else is the same document
    strip = lambda d: json.loads(
        json.dumps(d), object_hook=lambda o: {k: v for k, v in o.items() if k not in DROP}
    )
    DROP = {
        "gltf",
        "forward",
        "yaw_deg",
        "conventions",
        "coordinate_frame",
        "coordinate_frame_note",
    }
    assert strip(m) == strip(t)
    frags_m = [f for f in m["fragments"] if "gltf" in f]
    frags_t = [f for f in t["fragments"] if "gltf" in f]
    assert frags_m and all(
        b["gltf"]["translation"] == pytest.approx(frame.vec(a["gltf"]["translation"]))
        for a, b in zip(frags_m, frags_t)
    )


# ---------------------------------------------------------------- nav
def test_nav_glb_follows_the_frame_and_the_json_stays_engine(monkeypatch):
    h = nd.parse_hpd(tn.demo_hpd())
    gm, gt = both(monkeypatch, lambda m: tn.parse_glb_bytes(nd.build_glb(h, "Demo")))
    by = lambda g: dict(
        (n["name"], g.j["meshes"][n["mesh"]]["primitives"][0]) for n in g.j["nodes"] if "mesh" in n
    )
    bm, bt = by(gm), by(gt)
    assert set(bm) == set(bt) and len(bt) >= 6
    for name in bm:
        Pm = np.asarray(gm.accessor(bm[name]["attributes"]["POSITION"]))
        Pt = np.asarray(gt.accessor(bt[name]["attributes"]["POSITION"]))
        assert np.array_equal(Pt, Pm * np.float32([-1, 1, 1])), name
        A = gt.j["accessors"][bt[name]["attributes"]["POSITION"]]
        assert A["min"] == [float(x) for x in Pt.min(0)] and A["max"] == [
            float(x) for x in Pt.max(0)
        ]
        if bm[name].get("mode") != 4 and "indices" in bm[name]:
            assert np.array_equal(
                gm.accessor(bm[name]["indices"]), gt.accessor(bt[name]["indices"])
            )
    for g, b in ((gm, bm), (gt, bt)):  # the floor faces up in both frames
        P = np.asarray(g.accessor(b["navmesh"]["attributes"]["POSITION"]), float)
        T = np.asarray(g.accessor(b["navmesh"]["indices"])).reshape(-1, 3)
        assert (tri_normals(P, T)[:, 1] > 0).all()
    Pt = np.asarray(gt.accessor(bt["navmesh"]["attributes"]["POSITION"]))
    assert Pt[:, 0].min() == 0.0 and Pt[:, 0].max() == 6.0  # true x = the file's (Kynapse) x
    assert gm.j["extras"]["space"] == nd.SPACE["note"] and "extras" not in gm.j["asset"]
    assert gt.j["extras"]["space"] == nd.GLB_SPACE_TRUE
    assert gt.j["asset"]["extras"]["watchmen"]["coordinate_frame"] == "right-handed-true"
    dm, dt = both(monkeypatch, lambda m: nd.build_document(h, None, "Demo"))
    assert dm["conventions"] == nd.SPACE
    assert dt["conventions"] == dict(nd.SPACE, note=nd.NOTE_TRUE, glb_frame=nd.GLB_FRAME_NOTE)
    assert "write engine coordinates unchanged" not in nd.NOTE_TRUE
    assert dt["conventions"]["space"] == "engine"
    dt2 = dict(dt, conventions=dm["conventions"])
    assert dt2 == dm  # every number of the JSON is the same: engine space in both


# ---------------------------------------------------------------- OBJ
def _obj(path):
    v, vn, f, head = [], [], [], []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines(True):
        p = line.split()
        if line.startswith("#"):
            head.append(line.strip())
        elif p and p[0] == "v":
            v.append([float(x) for x in p[1:]])
        elif p and p[0] == "vn":
            vn.append([float(x) for x in p[1:]])
        elif p and p[0] == "f":
            f.append([int(x.split("/")[0]) - 1 for x in p[1:]])
    return np.array(v), np.array(vn), f, head


def test_obj_true_frame_negates_x_and_winds_with_its_normals(tmp_path, monkeypatch):
    h, s = tf._model([{"lods": [[("Body", 1, 6, 0.0, 1)]]}], tf._TEXTURES)

    def write(mode):
        out = tmp_path / mode / "m.obj"
        assert we.decode_model(h, s, out) is True
        return _obj(out), out.read_text()

    ((vm, nm, fm, hm), text_m), ((vt, nt, ft, ht), text_t) = both(monkeypatch, write)
    assert np.array_equal(vt, vm * [-1, 1, 1]) and np.array_equal(nt, nm * [-1, 1, 1])
    assert ft == fm  # the faces are the file's in both
    assert len(hm) == 1 and ht[1] == "# coordinate_frame right-handed-true (x = -engine x)"
    assert "-0.000000" not in text_t
    assert text_t.replace(ht[1] + "\n", "").count("\n") == text_m.count("\n")
    # this fixture's triangles wind WITH the stored normal in engine numbers, so in
    # the true frame they wind against it: the face order is never changed
    sm = np.einsum("ij,ij->i", tri_normals(vm, fm), nm[[t[0] for t in fm]])
    st = np.einsum("ij,ij->i", tri_normals(vt, ft), nt[[t[0] for t in ft]])
    assert np.array_equal(np.sign(sm), -np.sign(st)) and (sm != 0).all()
