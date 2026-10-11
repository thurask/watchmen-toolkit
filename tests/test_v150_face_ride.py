"""The face rig of a character GLB rides the body skeleton.

Hierarchy rig: f_anchor is a child of the attach joint (Head) and each face
proxy a child of its body joint, with constant local transforms; no channel
drives them.  Between keys a viewer composes the body's local channels down
the chain, so the face follows the head there too (1.4.0 drove the anchor with
its own world channel, interpolated by a different rule than the head: the
face slid off the head between keys).  The flat rig keeps the 1.4.0 layout.
Synthetic bind, clips and face rig.
"""

import numpy as np
import pytest

import variant_glb as vg
from conftest import axis_angle, parse_glb, quat_xyzw_to_mat
from test_rig_hierarchy import Chain

HEAD, PROXY_BONE = 2, 3


def _face(tmp_path, chain):
    rng = np.random.default_rng(7)
    names = np.array(["Bip01", "Neck", "Head", "Jaw"])
    par = np.array([-1, 0, 1, 2])
    Rb = np.array([axis_angle(rng.uniform(-1, 1, 3), 0.3 + 0.2 * k) for k in range(4)])
    tb = np.array([[0.0, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.2, 0.0], [0.0, 0.2, 0.05]])
    bind = tmp_path / "bind_face.npz"
    np.savez(bind, Rb=Rb, tb=tb, names=names, par=par)

    def pal(jaw):
        p = np.tile(np.eye(4)[:3], (1, 4, 1, 1)).astype(np.float32)
        p[0, 3, 1, 3] = -jaw
        return np.repeat(p, 2, axis=0)

    anims = [("FACE EN1/Open", pal(0.0), 2.0), ("FACE EN1/DamageL", pal(0.03), 2.0)]
    V = np.array([[0, 0.2, 0], [0.02, 0.2, 0.05], [-0.02, 0.2, 0.05], [0.0, 0.1, 0.1]], np.float32)
    # joints of the face skin: 4 face bones, 1 proxy (index 4), the anchor (5)
    SI = np.array([[2, 0, 0, 0], [3, 0, 0, 0], [3, 4, 0, 0], [4, 5, 0, 0]], np.uint16)
    SW = np.array([[1, 0, 0, 0], [1, 0, 0, 0], [0.5, 0.5, 0, 0], [0.6, 0.4, 0, 0]], np.float32)
    part = (
        V,
        SI,
        SW,
        np.array([[0, 1, 2], [1, 2, 3]], np.uint32),
        np.zeros((4, 2), np.float32),
        "h",
    )
    M = axis_angle([0.3, 1.0, -0.2], 0.9)
    t = np.array([0.1, 0.4, -0.2])
    Mk = np.eye(4)
    Mk[:3, :3] = axis_angle([1.0, 0.2, 0.5], -0.6)
    Mk[:3, 3] = [-0.3, 0.2, 0.25]
    return dict(
        bind=str(bind),
        parts=[part],
        anims=anims,
        attach_idx=HEAD,
        M=M,
        t=t,
        proxy_slots=[PROXY_BONE],
        proxy_align=[Mk],
        auto_poses={nm.split("/")[-1]: p[0] for nm, p, _f in anims},
        blink_closed=None,
        family="EN1",
        head="Test_Head",
    )


def _m4(R, t):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def _slerp(q0, q1, a):
    q0, q1 = np.asarray(q0, float), np.asarray(q1, float)
    d = float(np.dot(q0, q1))
    if d < 0:
        q1, d = -q1, -d
    if d > 0.9999995:
        q = q0 + a * (q1 - q0)
    else:
        th = np.arccos(min(d, 1.0))
        q = (np.sin((1 - a) * th) * q0 + np.sin(a * th) * q1) / np.sin(th)
    return q / np.linalg.norm(q)


def _sample_lerp(g, anim, t):
    """Animation `anim` at time t as a glTF viewer evaluates LINEAR samplers:
    lerp of translations, slerp of rotations -> {node: TRS dict}."""
    a = g.j["animations"][anim]
    out = {}
    for ch in a["channels"]:
        s = a["samplers"][ch["sampler"]]
        times = np.asarray(g.accessor(s["input"]), float)
        vals = np.asarray(g.accessor(s["output"]), float)
        i = int(np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 2))
        al = float(np.clip((t - times[i]) / (times[i + 1] - times[i]), 0.0, 1.0))
        path = ch["target"]["path"]
        if path == "rotation":
            v = _slerp(vals[i], vals[i + 1], al)
        else:
            v = vals[i] + al * (vals[i + 1] - vals[i])
        out.setdefault(ch["target"]["node"], {})[path] = [float(x) for x in v]
    return out


def _write(chain, face, path, **kw):
    vg.write_glb(chain.parts, chain.manifest, str(path), str(chain.bind_npz), face=face, **kw)
    return parse_glb(path)


def _names(g):
    return [n["name"] for n in g.j["nodes"]]


@pytest.mark.usefixtures("engine_frame")  # engine numbers: compared with the input
def test_face_anchor_and_proxy_ride_their_body_joints(tmp_path):
    chain = Chain(tmp_path)
    face = _face(tmp_path, chain)
    g = _write(chain, face, tmp_path / "h.glb", face_rule="legacy")
    j, nm = g.j, _names(g)
    joints = j["skins"][0]["joints"]
    par = g.parents()
    assert "face_root" not in nm
    anchor = nm.index("f_anchor")
    proxy = nm.index("face_proxy_b%d_0" % PROXY_BONE)
    assert par[anchor] == joints[HEAD] and par[proxy] == joints[PROXY_BONE]
    M4 = _m4(face["M"], face["t"])
    Mk = face["proxy_align"][0]
    # constant local transforms: inv(B4[bone]) @ M
    G0 = g.global_matrices()
    assert np.allclose(G0[anchor], M4, atol=1e-5)  # at rest: where 1.4.0 put it
    assert np.allclose(G0[proxy], Mk, atol=1e-5)
    # the face skin: same joints as before, rooted at the body's root
    assert j["skins"][1]["skeleton"] == nm.index("root")
    assert j["skins"][1]["joints"][-1] == anchor
    tops = [nm[i] for i in j["scenes"][0]["nodes"]]
    assert tops == ["root", "mesh", "face_mesh"]
    for a in range(len(chain.clips)):
        assert not {anchor, proxy} & {c["target"]["node"] for c in j["animations"][a]["channels"]}
        W = chain.world(a)
        F = len(W)
        fps = chain.clips[a][2]
        # on every key: the 1.4.0 world of the anchor, A4[Head] @ M4
        for f in range(F):
            G = g.global_matrices(_sample_lerp(g, a, f / fps))
            A4h = W[f, HEAD] @ np.linalg.inv(chain.B4[HEAD])
            assert np.allclose(G[anchor], A4h @ M4, atol=1e-4)
            A4p = W[f, PROXY_BONE] @ np.linalg.inv(chain.B4[PROXY_BONE])
            assert np.allclose(G[proxy], A4p @ Mk, atol=1e-4)
        # between keys: still Head @ inv(B4[Head]) @ M4 of the interpolated head
        for f in range(F - 1):
            G = g.global_matrices(_sample_lerp(g, a, (f + 0.5) / fps))
            hb = G[joints[HEAD]] @ np.linalg.inv(chain.B4[HEAD]) @ M4
            assert np.allclose(G[anchor], hb, atol=1e-5)
            pb = G[joints[PROXY_BONE]] @ np.linalg.inv(chain.B4[PROXY_BONE]) @ Mk
            assert np.allclose(G[proxy], pb, atol=1e-5)
    sx = j["skins"][1]["extras"]["watchmen"]["face"] if "extras" in j["skins"][1] else None
    assert sx is None  # the legacy rule writes no face extras


@pytest.mark.usefixtures("engine_frame")
def test_flat_rig_keeps_the_world_driven_face_root(tmp_path):
    """--rig flat: the 1.4.0 layout, and the gap the hierarchy closes: the
    world-interpolated anchor leaves the interpolated head between keys."""
    chain = Chain(tmp_path)
    face = _face(tmp_path, chain)
    g = _write(chain, face, tmp_path / "f.glb", face_rule="legacy", rig="flat")
    j, nm = g.j, _names(g)
    par = g.parents()
    frn, anchor = nm.index("face_root"), nm.index("f_anchor")
    proxy = nm.index("face_proxy_b%d_0" % PROXY_BONE)
    assert frn in j["scenes"][0]["nodes"] and par[anchor] == frn and par[proxy] == frn
    assert j["skins"][1]["skeleton"] == frn
    joints = j["skins"][0]["joints"]
    M4 = _m4(face["M"], face["t"])
    gap = 0.0
    for a in range(len(chain.clips)):
        tgt = {c["target"]["node"] for c in j["animations"][a]["channels"]}
        assert {anchor, proxy} <= tgt
        fps = chain.clips[a][2]
        for f in range(len(chain.clips[a][1]) - 1):
            G = g.global_matrices(_sample_lerp(g, a, (f + 0.5) / fps))
            hb = G[joints[HEAD]] @ np.linalg.inv(chain.B4[HEAD]) @ M4
            gap = max(gap, float(np.abs(G[anchor][:3, 3] - hb[:3, 3]).max()))
    assert gap > 1e-3


def test_face_joint_channels_are_the_same_in_both_rigs(tmp_path, monkeypatch):
    """The face bones' local channels under f_anchor do not depend on the rig."""
    chain = Chain(tmp_path)
    face = _face(tmp_path, chain)
    h = _write(chain, face, tmp_path / "h.glb", face_rule="legacy")
    fl = _write(chain, face, tmp_path / "f.glb", face_rule="legacy", rig="flat")

    def chans(g):
        nm = _names(g)
        out = {}
        for a in g.j["animations"]:
            for c in a["channels"]:
                n = nm[c["target"]["node"]]
                if n.startswith("f_") and n != "f_anchor":
                    s = a["samplers"][c["sampler"]]
                    out[(a["name"], n, c["target"]["path"])] = (
                        g.accessor(s["input"]).tobytes(),
                        g.accessor(s["output"]).tobytes(),
                    )
        return out

    ch = chans(h)
    assert ch and ch == chans(fl)
    nh, nf = _names(h), _names(fl)
    for k in range(4):
        n = h.j["nodes"][nh.index("f_%s" % ["Bip01", "Neck", "Head", "Jaw"][k])]
        m = fl.j["nodes"][nf.index("f_%s" % ["Bip01", "Neck", "Head", "Jaw"][k])]
        assert n["rotation"] == m["rotation"] and n["translation"] == m["translation"]


@pytest.mark.parametrize("frame", ["true", "mirrored"])
def test_face_skins_the_same_at_rest_and_on_keys_in_both_rigs(tmp_path, monkeypatch, frame):
    from conftest import skin_vertices

    monkeypatch.setenv("WATCHMEN_FRAME", frame)
    chain = Chain(tmp_path)
    face = _face(tmp_path, chain)
    h = _write(chain, face, tmp_path / "h.glb", face_rule="legacy")
    fl = _write(chain, face, tmp_path / "f.glb", face_rule="legacy", rig="flat")

    def skinned(g, over=None):
        nm = _names(g)
        mnode = nm.index("face_mesh")
        mesh = g.j["nodes"][mnode]["mesh"]
        p = g.j["meshes"][mesh]["primitives"][0]["attributes"]
        V = g.accessor(p["POSITION"]).astype(float)
        J, Wt = g.accessor(p["JOINTS_0"]), g.accessor(p["WEIGHTS_0"]).astype(float)
        return skin_vertices(V, J, Wt, g.skin_matrices(mnode, 1, over))

    assert np.allclose(skinned(h), skinned(fl), atol=1e-5)
    for a in range(len(chain.clips)):
        fps = chain.clips[a][2]
        for f in range(len(chain.clips[a][1])):
            assert np.allclose(
                skinned(h, _sample_lerp(h, a, f / fps)),
                skinned(fl, _sample_lerp(fl, a, f / fps)),
                atol=1e-4,
            )


def test_engine_face_extras_name_the_anchor_and_its_joint(tmp_path):
    chain = Chain(tmp_path)
    face = _face(tmp_path, chain)
    h = _write(chain, face, tmp_path / "h.glb", face_rule="engine", face_idle=False)
    sx = h.j["skins"][1]["extras"]["watchmen"]["face"]
    assert sx["anchor_node"] == "f_anchor" and sx["anchor_parent"] == "Head"
    fl = _write(chain, face, tmp_path / "f.glb", face_rule="engine", face_idle=False, rig="flat")
    sx = fl.j["skins"][1]["extras"]["watchmen"]["face"]
    assert sx["anchor_node"] == "face_root" and "anchor_parent" not in sx


def test_quat_helper_sanity():
    """_slerp is the glTF LINEAR rotation rule (endpoints and midpoint)."""
    q0 = np.array([0.0, 0.0, 0.0, 1.0])
    q1 = np.array([0.0, np.sin(0.5), 0.0, np.cos(0.5)])
    assert np.allclose(_slerp(q0, q1, 0.0), q0) and np.allclose(_slerp(q0, q1, 1.0), q1)
    mid = quat_xyzw_to_mat(_slerp(q0, q1, 0.5))
    assert np.allclose(mid, axis_angle([0, 1, 0], 0.5), atol=1e-12)


def test_joint_names_never_take_a_face_or_ragdoll_node_name(tmp_path):
    names = ["face_mesh", "f_Jaw", "face_proxy_b3_0", "RB.Head.0", "RJ.Head", "Head", "fJaw"]
    assert vg.joint_node_names(names) == [
        "face_mesh #0",
        "f_Jaw #1",
        "face_proxy_b3_0 #2",
        "RB.Head.0 #3",
        "RJ.Head #4",
        "Head",
        "fJaw",
    ]
    # a whole file: a body bone named like a face joint and like the face mesh node
    chain = Chain(tmp_path, names=("Pelvis", "f_Jaw", "Head", "face_mesh"), par=(-1, 0, 1, 1))
    g = _write(chain, _face(tmp_path, chain), tmp_path / "n.glb", face_rule="legacy")
    nm = _names(g)
    assert len(set(nm)) == len(nm), sorted(n for n in nm if nm.count(n) > 1)
    joints = [nm[n] for n in g.j["skins"][0]["joints"]]
    assert joints == ["Pelvis", "f_Jaw #1", "Head", "face_mesh #3"]
    assert {"f_Jaw", "face_mesh"} <= set(nm)  # the face rig's own nodes keep their names
