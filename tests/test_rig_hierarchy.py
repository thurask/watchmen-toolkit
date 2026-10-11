"""The hierarchical skeleton of the rigged GLBs (1.5.0), the full-size embedded
textures of `extract --glb`, and the pixel decoders.

Character GLBs (variant_glb.write_glb): one joint node per bone, named after it,
parented as the bind's parent table says, rest and animation TRS local to the
parent; the skinned mesh nodes are scene roots.  `--rig flat` ($WATCHMEN_RIG=flat)
writes the 1.4.0 layout.  Every check that matters is made on the written file
the way a viewer reads it: world = product of the local TRS down the chain,
joint matrix = world @ IBM.

`extract --glb` (rig_glb.build_rigged_glb): the joints get the model header's
rest pose (build_bind_file's conventions) and real inverse binds.
"""

import io
import json

import numpy as np
import pytest
from PIL import Image

import bake_v4
import build_bind_file as bbf
import ragdoll_rig as rr
import rig_glb
import variant_glb as vg
import watchmen_extract as we
from conftest import (
    axis_angle,
    build_model_header,
    parse_glb,
    quat_xyzw_to_mat,
    skin_vertices,
    synthetic_nodes,
)


# ---------------------------------------------------------------- fixtures
class Chain:
    """A 4-bone bind with a branch (0 <- 1 <- 2, 1 <- 3) and two random clips."""

    def __init__(self, tmp_path, names=("Pelvis", "Spine", "Head", "L Arm"), par=(-1, 0, 1, 1)):
        rng = np.random.default_rng(151)
        self.NB = len(names)
        self.names = np.array(names)
        self.par = np.array(par)
        self.B4 = np.tile(np.eye(4), (self.NB, 1, 1))
        for k in range(self.NB):
            self.B4[k, :3, :3] = axis_angle(rng.uniform(-1, 1, 3), rng.uniform(0.2, 2.9))
            self.B4[k, :3, 3] = rng.uniform(-1, 1, 3)
        self.bind_npz = tmp_path / "bind_chain.npz"
        np.savez(
            self.bind_npz,
            Rb=self.B4[:, :3, :3],
            tb=self.B4[:, :3, 3],
            names=self.names,
            par=self.par,
        )
        nv = 12
        self.V = rng.uniform(-0.5, 0.5, (nv, 3)).astype(np.float32)
        self.SI = np.array([[i % self.NB, (i + 1) % self.NB, 0, 0] for i in range(nv)], np.uint16)
        self.SW = np.zeros((nv, 4), np.float32)
        self.SW[:, 0] = 0.7
        self.SW[:, 1] = 0.3
        self.T = np.array([[i, (i + 1) % nv, (i + 2) % nv] for i in range(nv - 2)], np.uint32)
        self.UV = rng.uniform(0, 1, (nv, 2)).astype(np.float32)
        self.clips = []
        for c, F in enumerate((5, 9)):
            W = np.tile(np.eye(4), (F, self.NB, 1, 1))
            for f in range(F):
                for k in range(self.NB):
                    W[f, k, :3, :3] = axis_angle(rng.uniform(-1, 1, 3), rng.uniform(0, 3.1))
                    W[f, k, :3, 3] = rng.uniform(-2, 2, 3)
            pal = np.einsum("fkab,kbc->fkac", W, np.linalg.inv(self.B4))[:, :, :3, :]
            self.clips.append(("clip%d" % c, pal.astype(np.float32), 10.0 + c, W))

    @property
    def parts(self):
        return [(self.V, self.SI, self.SW, self.T, self.UV, "mat")]

    @property
    def manifest(self):
        return [(n, A, fps) for n, A, fps, _W in self.clips]

    def world(self, clip):
        """The file's own world: palette (as float32, as written) @ B4."""
        A = self.clips[clip][1].astype(np.float64)
        A4 = np.concatenate([A, np.tile([[[[0, 0, 0, 1.0]]]], A.shape[:2] + (1, 1))], 2)
        return np.einsum("fkab,kbc->fkac", A4, self.B4)


@pytest.fixture
def chain(tmp_path):
    return Chain(tmp_path)


def _trs(nd):
    M = np.eye(4)
    M[:3, :3] = quat_xyzw_to_mat(nd.get("rotation", [0, 0, 0, 1]))
    M[:3, 3] = nd.get("translation", [0, 0, 0])
    return M


def _sample(g, anim, f):
    """{node: {path: value}} of animation `anim` at key f (keys are per frame)."""
    a = g.j["animations"][anim]
    out = {}
    for ch in a["channels"]:
        s = a["samplers"][ch["sampler"]]
        out.setdefault(ch["target"]["node"], {})[ch["target"]["path"]] = [
            float(x) for x in np.atleast_1d(g.accessor(s["output"])[f])
        ]
    return out


def _write(chain, path, **kw):
    vg.write_glb(chain.parts, chain.manifest, str(path), str(chain.bind_npz), **kw)
    return parse_glb(path)


# ---------------------------------------------------------------- rig mode
def test_rig_mode_reads_the_option_then_the_environment(monkeypatch):
    monkeypatch.delenv("WATCHMEN_RIG", raising=False)
    assert vg.rig_mode() == "hierarchy" == vg.DEFAULT_RIG
    monkeypatch.setenv("WATCHMEN_RIG", "flat")
    assert vg.rig_mode() == "flat" and vg.rig_mode("hierarchy") == "hierarchy"
    monkeypatch.setenv("WATCHMEN_RIG", "tree")
    with pytest.raises(ValueError, match="rig mode 'tree'"):
        vg.rig_mode()


def test_joint_node_names_are_clean_and_unique():
    names = ["Head", "", "L\x01Hand\n", "root", "Head", "WPN_Bat", "  ", "Head #4"]
    got = vg.joint_node_names(names, reserved=["WPN_Bat"])
    assert got == [
        "Head",
        "b1",  # empty -> the palette index
        "LHand",  # control characters removed, blanks stripped
        "root #3",  # a fixed node name of the file
        "Head #4",  # a duplicate keeps its palette index
        "WPN_Bat #5",  # an attachment node's name
        "b6",
        "Head #4 #7",  # its own name was taken by the duplicate above
    ]
    assert len(set(got)) == len(got)


def test_parent_table_check():
    assert vg.parent_table_ok([-1, 0, 1, 1])
    assert vg.parent_table_ok([-1, -1])
    assert not vg.parent_table_ok([1, 0])  # a cycle
    assert not vg.parent_table_ok([-1, 1])  # its own parent
    assert not vg.parent_table_ok([-1, 5])  # out of range
    assert not vg.parent_table_ok([-1, 0, 3, 2])


def test_local_from_world_recomposes_over_frames():
    rng = np.random.default_rng(3)
    par = [-1, 0, 1, 0, 3]
    W = np.tile(
        np.eye(4), (6, 5, 1, 1)
    )  # 6 frames: as many as joints minus one would hide a transposition
    for f in range(6):
        for k in range(5):
            W[f, k, :3, :3] = axis_angle(rng.uniform(-1, 1, 3), rng.uniform(0, 3))
            W[f, k, :3, 3] = rng.uniform(-1, 1, 3)
    for F in (6, 4):  # 4 frames == 4 non-root joints
        L = vg.local_from_world(W[:F], par)
        for f in range(F):
            assert np.allclose(L[f], vg.local_from_world(W[f], par))
            G = np.zeros((5, 4, 4))
            for k in range(5):
                G[k] = L[f, k] if par[k] < 0 else G[par[k]] @ L[f, k]
            assert np.allclose(G, W[f], atol=1e-12)


# ---------------------------------------------------------------- the file
@pytest.mark.usefixtures("engine_frame")  # engine numbers: world compares with the input
def test_hierarchy_recomposes_the_bind_and_every_frame_of_two_clips(chain, tmp_path):
    g = _write(chain, tmp_path / "h.glb")
    j = g.j
    joints = j["skins"][0]["joints"]
    assert [j["nodes"][n]["name"] for n in joints] == list(chain.names)
    assert [j["nodes"][n]["extras"]["index"] for n in joints] == [0, 1, 2, 3]
    parent = {c: i for i, n in enumerate(j["nodes"]) for c in n.get("children", [])}
    root = [n["name"] for n in j["nodes"]].index("root")
    for k, n in enumerate(joints):
        assert parent[n] == (root if chain.par[k] < 0 else joints[chain.par[k]])
    # rest: the product of the local TRS down the chain is the bind
    G = g.global_matrices()
    for k, n in enumerate(joints):
        assert np.allclose(G[n], chain.B4[k], atol=1e-5)
    ibm = g.mat4_accessor(j["skins"][0]["inverseBindMatrices"])
    assert np.allclose(ibm, np.linalg.inv(chain.B4), atol=1e-5)  # unchanged by the rig
    # animation: every joint of every frame of both clips, world == palette @ B4
    for a in range(2):
        W = chain.world(a)
        assert {c["target"]["node"] for c in j["animations"][a]["channels"]} == set(joints)
        for f in range(len(W)):
            G = g.global_matrices(_sample(g, a, f))
            for k, n in enumerate(joints):
                assert np.allclose(G[n][:3, :3], W[f, k, :3, :3], atol=1e-5)
                assert np.allclose(G[n][:3, 3], W[f, k, :3, 3], atol=1e-5)


@pytest.mark.parametrize("frame", ["true", "mirrored"])
def test_hierarchy_and_flat_skin_the_same_in_both_frames(chain, tmp_path, monkeypatch, frame):
    """Rest pose and every animated frame give the same skinned vertices with
    either rig (the rig changes the node layout, not the pose)."""
    monkeypatch.setenv("WATCHMEN_FRAME", frame)
    h = _write(chain, tmp_path / "h.glb")
    fl = _write(chain, tmp_path / "f.glb", rig="flat")

    def skinned(g, over=None):
        mesh = next(i for i, n in enumerate(g.j["nodes"]) if n.get("skin") == 0)
        p = g.j["meshes"][0]["primitives"][0]["attributes"]
        V = g.accessor(p["POSITION"]).astype(float)
        J, Wt = g.accessor(p["JOINTS_0"]), g.accessor(p["WEIGHTS_0"]).astype(float)
        return skin_vertices(V, J, Wt, g.skin_matrices(mesh, 0, over))

    assert np.allclose(skinned(h), skinned(fl), atol=1e-5)
    assert np.allclose(
        skinned(h),
        h.accessor(h.j["meshes"][0]["primitives"][0]["attributes"]["POSITION"]),
        atol=1e-5,
    )
    for a in range(2):
        for f in range(len(chain.clips[a][1])):
            assert np.allclose(
                skinned(h, _sample(h, a, f)), skinned(fl, _sample(fl, a, f)), atol=1e-5
            )


def test_skinned_mesh_nodes_are_scene_roots(rig, tmp_path):
    """The validator's NODE_SKINNED_MESH_NON_ROOT: the shown mesh nodes (body,
    shown attachment) are scene roots; a hidden one stays under `alternatives`."""
    wpn = [("WPN_Whip", [rig.parts[0]]), ("WPN_Bat", [rig.parts[0]])]
    rec = {"mode": "game", "alternatives": [], "weapons": {"shown": ["WPN_Whip"]}}
    out = tmp_path / "s.glb"
    vg.write_glb(
        rig.parts, rig.manifest, str(out), str(rig.bind_npz), attachments=wpn, parts_record=rec
    )
    j = parse_glb(out).j
    names = [n["name"] for n in j["nodes"]]
    parent = {c: i for i, n in enumerate(j["nodes"]) for c in n.get("children", [])}
    tops = j["scenes"][0]["nodes"]
    assert [names[i] for i in tops] == ["root", "mesh", "WPN_Whip"]
    for i, n in enumerate(j["nodes"]):
        if "skin" in n and "mesh" in n:
            assert i not in parent or names[parent[i]] == "alternatives", names[i]
    assert names[parent[names.index("WPN_Bat")]] == "alternatives"
    # flat: the 1.4.0 layout, everything under root
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        attachments=wpn,
        parts_record=rec,
        rig="flat",
    )
    j = parse_glb(out).j
    names = [n["name"] for n in j["nodes"]]
    assert [names[i] for i in j["scenes"][0]["nodes"]] == ["root"]
    kids = [names[c] for c in j["nodes"][names.index("root")]["children"]]
    assert kids == ["b%d" % k for k in range(rig.NB)] + ["mesh", "WPN_Whip"]
    assert j["asset"]["extras"]["watchmen"]["rig"] == {"mode": "flat"}


@pytest.mark.usefixtures("engine_frame")  # engine numbers: compared with the input
def test_masked_overlay_writes_local_channels_of_its_bones_only(chain, tmp_path):
    """A 4-tuple entry (GRIP overlay): channels for the listed bones only, local
    to their parents and computed from that entry's own palette."""
    pal = chain.clips[1][1][:1]
    man = chain.manifest + [("GRIP", np.repeat(pal, 2, axis=0), 2.0, [2, 3])]
    out = tmp_path / "g.glb"
    vg.write_glb(chain.parts, man, str(out), str(chain.bind_npz))
    g = parse_glb(out)
    joints = g.j["skins"][0]["joints"]
    a = g.j["animations"][-1]
    assert a["name"] == "GRIP"
    assert sorted({c["target"]["node"] for c in a["channels"]}) == sorted(joints[k] for k in (2, 3))
    W = chain.world(1)[0]
    L = vg.local_from_world(W, chain.par)
    s = _sample(g, len(g.j["animations"]) - 1, 0)
    for k in (2, 3):
        M = _trs(s[joints[k]])
        Lk = L[k]
        if chain.par[k] >= 0:
            assert np.allclose(M, Lk, atol=1e-5)  # parent-relative, not the world pose
            assert not np.allclose(M[:3, 3], W[k, :3, 3], atol=1e-3)


def test_bind_without_a_tree_is_written_flat_and_says_why(chain, tmp_path):
    np.savez(
        chain.bind_npz,
        Rb=chain.B4[:, :3, :3],
        tb=chain.B4[:, :3, 3],
        names=chain.names,
        par=np.array([1, 0, 1, 1]),  # a cycle
    )
    g = _write(chain, tmp_path / "c.glb")
    assert g.j["asset"]["extras"]["watchmen"]["rig"] == {
        "mode": "flat",
        "reason": "the bind's parent table is not a tree",
    }
    assert g.j["nodes"][g.j["skins"][0]["joints"][0]]["name"] == "b0"
    np.savez(chain.bind_npz, Rb=chain.B4[:, :3, :3], tb=chain.B4[:, :3, 3])
    g = _write(chain, tmp_path / "n.glb")
    assert (
        g.j["asset"]["extras"]["watchmen"]["rig"]["reason"]
        == "the bind has no bone names and parents"
    )


def test_bone_named_like_an_attachment_gets_its_index(tmp_path):
    ch = Chain(tmp_path, names=("Pelvis", "WPN_Bat", "Head", "mesh"))
    out = tmp_path / "a.glb"
    vg.write_glb(
        ch.parts, ch.manifest, str(out), str(ch.bind_npz), attachments=[("WPN_Bat", ch.parts)]
    )
    j = parse_glb(out).j
    names = [n["name"] for n in j["nodes"]]
    assert [names[n] for n in j["skins"][0]["joints"]] == [
        "Pelvis",
        "WPN_Bat #1",
        "Head",
        "mesh #3",
    ]
    assert (
        names.count("WPN_Bat") == 1
        and j["skins"][0]["extras"]["watchmen"]["joint_nodes"][1] == "WPN_Bat #1"
    )
    assert vg.glb_joint_names(list(ch.names), list(ch.par), ["WPN_Bat"]) == [
        names[n] for n in j["skins"][0]["joints"]
    ]
    assert vg.glb_joint_names(list(ch.names), list(ch.par), rig="flat") is None


# ---------------------------------------------------------------- ragdoll names
def test_ragdoll_helpers_name_the_files_joint_nodes(tmp_path):
    import test_ragdoll_rig as trr

    rig = rr.build(trr.build_model())
    names = trr.BIND_NAMES
    Rb = np.tile(np.eye(3), (len(names), 1, 1))
    tb = np.zeros((len(names), 3))
    jn = vg.joint_node_names(names)
    flat = rr.glb_helpers(rig, names, Rb, tb)
    hier = rr.glb_helpers(rig, names, Rb, tb, joint_names=jn)
    for a, b in zip(flat["shapes"], hier["shapes"]):
        k = a["slot"]
        assert a["extras"]["body"]["joint_node"] == "b%d" % k
        assert "joint_index" not in a["extras"]["body"]
        assert (
            b["extras"]["body"]["joint_node"] == jn[k] and b["extras"]["body"]["joint_index"] == k
        )
    for a, b in zip(flat["joints"], hier["joints"]):
        assert (
            a["extras"]["child_joint_node"].startswith("b")
            and "child_joint_index" not in a["extras"]
        )
        kc, kp = b["extras"]["child_joint_index"], b["extras"]["parent_joint_index"]
        assert (b["extras"]["child_joint_node"], b["extras"]["parent_joint_node"]) == (
            jn[kc],
            jn[kp],
        )
        assert list(a["extras"])[-1] == "blender"  # the 1.4.0 key order is kept
    side = rr.sidecar(rig, names, joint_names=jn)
    assert set(side["joint_nodes"].values()) <= set(jn) | {None}
    assert all(
        side["joint_nodes"][b] == jn[k] for b, k in side["joint_indices"].items() if k is not None
    )
    assert "joint_indices" not in rr.sidecar(rig, names)
    # write_glb relabels to the names of the file it writes
    other = ["X%d" % k for k in range(len(names))]
    rel = rr.relabel_joint_nodes(hier, other)
    assert rel["shapes"][0]["extras"]["body"]["joint_node"] == other[rel["shapes"][0]["slot"]]
    assert (
        hier["shapes"][0]["extras"]["body"]["joint_node"] == jn[hier["shapes"][0]["slot"]]
    )  # a copy
    same = rr.relabel_joint_nodes(flat, other)  # no indices: the names stay
    assert [x["extras"]["body"]["joint_node"] for x in same["shapes"]] == [
        x["extras"]["body"]["joint_node"] for x in flat["shapes"]
    ]


# ---------------------------------------------------------------- prune_gltf
def test_prune_gltf_on_the_hierarchical_layout(chain, tmp_path):
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "bil", os.path.join(os.path.dirname(__file__), "..", "tools", "blender_import_level.py")
    )
    bil = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bil)
    outfits = [("OUTFIT 1 Jacket", chain.parts, True), ("OUTFIT 2 Jacket", chain.parts, False)]
    rec = {
        "mode": "game",
        "alternatives": [],
        "weapons": {"shown": []},
        "member_shown": 1,
        "shown_nodes": ["OUTFIT 1 Jacket"],
        "members": [
            {"index": 1, "nodes": ["OUTFIT 1 Jacket"]},
            {"index": 2, "nodes": ["OUTFIT 2 Jacket"]},
        ],
    }
    for mode in ("hierarchy", "flat"):
        out = tmp_path / (mode + ".glb")
        vg.write_glb(
            chain.parts,
            chain.manifest,
            str(out),
            str(chain.bind_npz),
            outfit_parts=outfits,
            parts_record=rec,
            rig=mode,
        )
        doc = parse_glb(out).j
        for outfit, want, gone in (
            (None, "OUTFIT 1 Jacket", "OUTFIT 2 Jacket"),
            (2, "OUTFIT 2 Jacket", "OUTFIT 1 Jacket"),
        ):
            p = bil.prune_gltf(doc, "clip1", outfit)
            names = [n["name"] for n in p["nodes"]]
            assert want in names and gone not in names, (mode, outfit)
            par = {c: i for i, n in enumerate(p["nodes"]) for c in n.get("children", [])}
            reach, stack = set(), list(p["scenes"][0]["nodes"])
            while stack:
                i = stack.pop()
                reach.add(i)
                stack.extend(p["nodes"][i].get("children", []))
            w = names.index(want)
            assert w in reach  # the swapped-in outfit is in the scene
            if mode == "hierarchy":
                assert w in p["scenes"][0]["nodes"] and w not in par  # at the scene root
            else:
                assert names[par[w]] == "root"
            # every joint is kept with all its ancestors, in the scene
            for jn in p["skins"][0]["joints"]:
                assert jn in reach
            assert [a["name"] for a in p["animations"]] == ["clip1"]
            assert len(p["animations"][0]["channels"]) == 2 * chain.NB


# ---------------------------------------------------------------- extract --glb rig
def _nodes():
    """A header node table (parse_model_nodes.parse shape) and its header bytes."""
    raw = synthetic_nodes()
    hdr = build_model_header(raw, "<")
    import parse_model_nodes as pmn

    return pmn.parse(hdr), hdr


def test_header_rig_is_build_bind_files_bind(tmp_path):
    (names, pos, quat, parent), hdr = _nodes()
    (tmp_path / "s.model").write_bytes(hdr)
    Rb, tb, _tloc, _par, tn = bbf.build(str(tmp_path / "s.model"), None, str(tmp_path / "b.npz"))
    tpl = {"bone_count": len(names), "bones": [{"name": n} for n in names]}
    rec, W, par = rig_glb.header_rig(tpl, (names, pos, quat, parent), "hierarchy")
    assert rec == {"mode": "hierarchy", "source": "the model header's node table"}
    for k, nm in enumerate(tn):  # every bind slot equals the header node of that name
        h = list(names).index(nm)
        assert np.allclose(W[h, :3, :3], Rb[k], atol=1e-12) and np.allclose(
            W[h, :3, 3], tb[k], atol=1e-12
        )
    assert np.allclose(W[0], np.eye(4))  # node 0, the unnamed root, at the origin
    assert rig_glb.header_rig(tpl, (names, pos, quat, parent), "flat") == (None, None, None)
    short = {
        "bone_count": len(names) + 1,
        "bones": tpl["bones"] + [{"name": "bone_%d" % len(names)}],
    }
    assert rig_glb.header_rig(short, (names, pos, quat, parent), "hierarchy")[0]["mode"] == "flat"
    assert (
        rig_glb.header_rig(tpl, None, "hierarchy")[0]["reason"]
        == "no node table for the model's skeleton"
    )
    bad = list(parent)
    bad[2] = 3
    bad[3] = 2
    assert (
        "not a tree" in rig_glb.header_rig(tpl, (names, pos, quat, bad), "hierarchy")[0]["reason"]
    )


def _skinned_glb(path, nodes, rig=None, tex_size=None, tex=None, **kw):
    names = nodes[0]
    n = len(names)
    rng = np.random.default_rng(5)
    V = rng.uniform(-1, 1, (8, 3))
    SI = np.array([[i % n, (i + 3) % n, 0, 0] for i in range(8)], np.uint8)
    SW = np.zeros((8, 4), np.float32)
    SW[:, 0], SW[:, 1] = 0.6, 0.4
    T = [(i, i + 1, i + 2) for i in range(6)]
    rig_glb.build_rigged_glb(
        path,
        V,
        None,
        rng.uniform(0, 1, (8, 2)),
        SI,
        SW,
        T,
        [(0, 8, 0, 6, 56)],
        ["m"],
        tex or {},
        {"bone_count": n, "bones": [{"name": x} for x in names]},
        None,
        None,
        tex_size=tex_size,
        nodes=nodes,
        rig=rig,
        **kw,
    )
    return parse_glb(path)


@pytest.mark.parametrize("frame", ["true", "mirrored"])
def test_extract_glb_joints_stand_at_the_header_rest_pose(tmp_path, monkeypatch, frame):
    monkeypatch.setenv("WATCHMEN_FRAME", frame)
    nodes, _hdr = _nodes()
    g = _skinned_glb(tmp_path / "h.glb", nodes)
    j = g.j
    sk = j["skins"][0]
    names = [n["name"] for n in j["nodes"]]
    mesh = names.index("h_mesh")
    assert mesh in j["scenes"][0]["nodes"]  # a scene root
    assert j["asset"]["extras"]["watchmen"]["rig"]["mode"] == "hierarchy"
    parent = {c: i for i, n in enumerate(j["nodes"]) for c in n.get("children", [])}
    for k, jn in enumerate(sk["joints"]):
        p = int(nodes[3][k]) if k else -1
        assert j["nodes"][jn]["extras"] == {"bone": str(nodes[0][k]), "parent": p, "index": k}
        assert names[parent[jn]] == ("Armature" if p < 0 else names[sk["joints"][p]])
    # rest: every joint matrix is the identity -> the mesh renders as stored
    for M in g.skin_matrices(mesh, 0):
        assert np.allclose(M, np.eye(4), atol=1e-5)
    _r, W, _p = rig_glb.header_rig(
        {"bone_count": len(nodes[0]), "bones": [{"name": x} for x in nodes[0]]}, nodes, "hierarchy"
    )
    G = g.global_matrices()
    S = np.diag([-1.0, 1, 1, 1]) if frame == "true" else np.eye(4)
    for k, jn in enumerate(sk["joints"]):
        assert np.allclose(G[jn], S @ W[k] @ S, atol=1e-5)
    # zero-weight influences carry joint 0 (validator: ACCESSOR_JOINTS_USED_ZERO_WEIGHT)
    p = j["meshes"][0]["primitives"][0]["attributes"]
    J, Wt = g.accessor(p["JOINTS_0"]), g.accessor(p["WEIGHTS_0"])
    assert (J[Wt == 0] == 0).all() and (J[:, 1] != 0).any()


def test_extract_glb_flat_rig_is_the_140_armature(tmp_path):
    nodes, _hdr = _nodes()
    g = _skinned_glb(tmp_path / "f.glb", nodes, rig="flat")
    j = g.j
    names = [n["name"] for n in j["nodes"]]
    assert "extras" not in j["asset"] or "rig" not in j["asset"]["extras"].get("watchmen", {})
    arm = j["nodes"][names.index("Armature")]
    assert [names[c] for c in arm["children"]] == list(nodes[0]) + ["f_mesh"]
    assert j["scenes"][0]["nodes"] == [names.index("Armature")]
    for jn in j["skins"][0]["joints"]:
        assert set(j["nodes"][jn]) == {"name"}
    assert np.allclose(g.mat4_accessor(j["skins"][0]["inverseBindMatrices"]), np.eye(4))
    # a table that does not cover the joints (names padded 'bone_<k>'): flat, with the reason
    names2 = list(nodes[0]) + ["bone_%d" % len(nodes[0])]
    rec = rig_glb.header_rig(
        {"bone_count": len(names2), "bones": [{"name": x} for x in names2]}, nodes
    )[0]
    assert rec["mode"] == "flat" and "skin uses" in rec["reason"]


def _big_textures(tmp_path, size=1024):
    d = tmp_path / ("big%d.bmp" % size)
    d.mkdir()
    rng = np.random.default_rng(1)
    Image.fromarray(rng.integers(0, 255, (size, size, 3), dtype=np.uint8)).save(
        d / ("0_diffuse_%dx%d_DXT1.png" % (size, size))
    )
    Image.fromarray(rng.integers(0, 255, (size, size, 3), dtype=np.uint8)).save(
        d / ("1_normal_%dx%d_ATI2.png" % (size, size))
    )
    Image.fromarray(rng.integers(0, 255, (size, size, 3), dtype=np.uint8)).save(
        d / ("2_specMap_%dx%d_DXT1.png" % (size, size))
    )
    Image.fromarray(rng.integers(0, 255, (size, size), dtype=np.uint8)).save(
        d / ("3_specSize_%dx%d_L8.png" % (size, size))
    )
    (d / "sheet.json").write_text(
        json.dumps({"renderType": 0, "specularPower": 0.8, "specularSize": 30.0}), encoding="utf-8"
    )
    return {"m": d}


def _image_sizes(g):
    out = []
    for im in g.j.get("images", []):
        bv = g.j["bufferViews"][im["bufferView"]]
        png = g.bin_chunk[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]]
        out.append((im["name"], Image.open(io.BytesIO(png)).size))
    return out


def test_extract_glb_embeds_textures_at_full_size_unless_asked(tmp_path):
    nodes, _hdr = _nodes()
    n = np.tile([0, 0, 1.0], (8, 1)).astype(np.float32)
    t = np.tile([1.0, 0, 0, 1.0], (8, 1)).astype(np.float32)
    kw = dict(normals=n, tangents=t, engine_materials=True)
    tex = _big_textures(tmp_path)
    full = _image_sizes(_skinned_glb(tmp_path / "a.glb", nodes, tex=tex, **kw))
    names = [x for x, _ in full]
    assert "m" in names and "m_normal" in names and len(full) >= 3
    assert all(s == (1024, 1024) for _, s in full), full
    small = _image_sizes(_skinned_glb(tmp_path / "b.glb", nodes, tex=tex, tex_size=512, **kw))
    assert [x for x, _ in small] == names
    assert all(max(s) <= 512 for _, s in small), small
    # the primitive's material has a normal map, so TANGENT is written for it
    g = _skinned_glb(tmp_path / "c.glb", nodes, tex=tex, tex_size=64, **kw)
    assert "TANGENT" in g.j["meshes"][0]["primitives"][0]["attributes"]


def test_glb_texture_size_option():
    assert we._texture_size_arg("512") == 512
    import argparse

    for bad in ("0", "-3", "big"):
        with pytest.raises(argparse.ArgumentTypeError):
            we._texture_size_arg(bad)


def test_extract_options_set_the_rig_and_texture_size(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WATCHMEN_RIG", "hierarchy")
    monkeypatch.setitem(we._RIG, "tex_size", None)
    missing = str(tmp_path / "missing.naz")
    assert (
        we.main(
            [
                missing,
                "-o",
                str(tmp_path / "o"),
                "--glb",
                "--rig",
                "flat",
                "--glb-texture-size",
                "256",
            ]
        )
        == 2
    )
    # the archive is looked for before the options are applied; parse them alone
    with pytest.raises(SystemExit):
        we.main([missing, "-o", str(tmp_path / "o"), "--glb-texture-size", "0"])
    assert "must be at least 1" in capsys.readouterr().err


def test_cli_rig_option(monkeypatch, capsys):
    import os
    import watchmen

    monkeypatch.setenv("WATCHMEN_RIG", "hierarchy")
    assert watchmen.main(["w", "binds", "a", "b", "--rig", "flat"]) == 2
    assert "--rig applies to" in capsys.readouterr().out
    assert watchmen.main(["w", "characters", "a", "b", "--rig", "tree"]) == 2
    assert "--rig takes one of: hierarchy, flat" in capsys.readouterr().out
    assert os.environ["WATCHMEN_RIG"] == "hierarchy"
    assert (
        watchmen.main(["w", "char", "x", "--rig", "flat"]) == 2
    )  # too few arguments, option applied
    assert os.environ["WATCHMEN_RIG"] == "flat"
    for cmd in watchmen.RIG_COMMANDS:
        assert "--rig hierarchy|flat" in watchmen.USAGE[cmd][1]
    assert watchmen.RIG_MODES == vg.RIG_MODES


def test_writer_options_name_the_rig(monkeypatch):
    import characters_export as ce

    monkeypatch.delenv("WATCHMEN_RIG", raising=False)
    a = ce.writer_options()
    monkeypatch.setenv("WATCHMEN_RIG", "flat")
    b = ce.writer_options()
    assert (a["rig"], b["rig"]) == ("hierarchy", "flat") and a[
        "glb_revision"
    ] == ce.GLB_REVISION == 3


# ---------------------------------------------------------------- zero weights
def test_used_joints_zeroes_unweighted_slots_only():
    SI = np.array([[3, 4, 5, 6]], np.uint8)
    SW = np.array([[0.5, 0.5, 0.0, 0.0]], np.float32)
    out = vg.used_joints(SI, SW)
    assert (
        out.tolist() == [[3, 4, 0, 0]] and out.dtype == np.uint8 and SI.tolist() == [[3, 4, 5, 6]]
    )


# ---------------------------------------------------------------- pixel decoders
def _dxt1_colour_block(c0, c1, idx):
    bits = 0
    for i, v in enumerate(idx):
        bits |= v << (2 * i)
    return (
        int(c0).to_bytes(2, "little") + int(c1).to_bytes(2, "little") + bits.to_bytes(4, "little")
    )


def test_dxt3_block_decodes_its_explicit_alpha():
    alpha = 0
    for i in range(16):
        alpha |= i << (4 * i)  # texel i: alpha nibble i
    blk = alpha.to_bytes(8, "little") + _dxt1_colour_block(
        0xFFFF, 0x0000, [i % 4 for i in range(16)]
    )
    rgba = we.decode_dxt_base(blk, 4, 4, "DXT3")
    grey = [255, 0, 170, 85]  # c0, c1, 2/3 c0 + 1/3 c1, 1/3 c0 + 2/3 c1
    for i in range(16):
        y, x = divmod(i, 4)
        assert rgba[y, x].tolist() == [grey[i % 4]] * 3 + [17 * i], i
    # a layer of enum 6 goes through it (1.4.0 decoded it as DXT5)
    assert np.array_equal(we._decode_one_layer(blk, 6, 4, 4), rgba)
    assert we.FOURCC["DXT3"] == b"DXT3"


def test_dxt5_block_decodes_its_interpolated_alpha():
    idx = [[0, 1, 6, 7][i % 4] for i in range(16)]  # e0 <= e1: 6 -> 0, 7 -> 255
    bits = 0
    for i, v in enumerate(idx):
        bits |= v << (3 * i)
    blk = bytes([40, 200]) + bits.to_bytes(6, "little") + _dxt1_colour_block(0xFFFF, 0, [0] * 16)
    rgba = we.decode_dxt_base(blk, 4, 4, "DXT5")
    want = {0: 40, 1: 200, 6: 0, 7: 255}
    for i in range(16):
        y, x = divmod(i, 4)
        assert rgba[y, x].tolist() == [255, 255, 255, want[idx[i]]]


def _bc4(e0, e1, idx):
    bits = 0
    for i, v in enumerate(idx):
        bits |= v << (3 * i)
    return bytes([e0, e1]) + bits.to_bytes(6, "little")


def _d3d_bc4(e0, e1):
    """The D3D reference palette (float, then rounded to the nearest UNORM8)."""
    if e0 > e1:
        pal = [e0, e1] + [((7 - i) * e0 + i * e1) / 7.0 for i in range(1, 7)]
    else:
        pal = [e0, e1] + [((5 - i) * e0 + i * e1) / 5.0 for i in range(1, 5)] + [0, 255]
    return [int(np.floor(v + 0.5)) for v in pal]


@pytest.mark.parametrize("e0,e1", [(200, 10), (11, 200), (255, 0), (0, 255), (90, 90), (3, 1)])
def test_bc4_palette_is_rounded_like_d3d(e0, e1):
    idx = [i % 8 for i in range(16)]
    blk = np.frombuffer(_bc4(e0, e1, idx), np.uint8).reshape(1, 8)
    got = we._bc4_channel(blk, 4, 4).reshape(-1).tolist()
    pal = _d3d_bc4(e0, e1)
    assert got == [pal[i % 8] for i in range(16)]
    if (e0, e1) == (200, 10):
        assert pal[2:5] == [173, 146, 119]  # 1.4.0 truncated these to 172, 145, 118


def test_bc5_blocks_and_the_pc_channel_order():
    first = _bc4(200, 10, [0] * 16)  # every texel 200
    second = _bc4(30, 60, [0] * 16)  # every texel 30
    a, b = we.decode_bc5_base(first + second, 4, 4)
    assert (a == 200).all() and (b == 30).all()
    X, Y = we.ati2_xy((a, b))  # PC ATI2 keeps Y first
    assert (X == 30).all() and (Y == 200).all()
    rgb = we._decode_one_layer(first + second, 9, 4, 4)  # PC enum 9: swapped
    assert rgb[0, 0, :2].tolist() == [30, 200]
    rgb = we._decode_one_layer(first + second, 10, 4, 4)  # X360 enum 10: file order
    assert rgb[0, 0, :2].tolist() == [200, 30]
    assert we.decode_bc5_base(first, 4, 4) is None  # too short


# ---------------------------------------------------------------- batch_m2q
def test_batch_m2q_trace_le_zero_branch():
    rots = []
    for axis in np.eye(3):
        rots.append(axis_angle(axis, np.pi))  # 180 degrees: trace -1
    rng = np.random.default_rng(42)
    while len(rots) < 1003:
        R = axis_angle(rng.normal(size=3), rng.uniform(2.1, np.pi))
        if np.trace(R) <= 0:
            rots.append(R)
    M = np.array(rots)
    assert (np.trace(M, axis1=1, axis2=2) <= 0).all()
    q = vg.batch_m2q(M)
    assert np.allclose(np.linalg.norm(q, axis=1), 1.0)
    err = np.abs(bake_v4.Rstd(q) - M).max()
    assert err <= 1e-12, err


# ------------------------------------------------- anim_meta.json `skeletons`
@pytest.mark.parametrize("rig", ["hierarchy", "flat"])
def test_anim_meta_skeletons_table_matches_the_skin_extras(chain, tmp_path, monkeypatch, rig):
    """The `skeletons` table written beside the GLBs describes the layout the GLBs
    of the run have: the record of a bind is the skin extras of a GLB of it."""
    import shutil

    import anim_meta

    monkeypatch.setenv("WATCHMEN_RIG", rig)
    binds = tmp_path / "binds"
    binds.mkdir()
    shutil.copy(chain.bind_npz, binds / "bind_chain_file_v1.npz")
    table = anim_meta.skeletons(str(binds))
    rec = dict(table["chain"])
    assert rec.pop("joint_count") == chain.NB
    g = _write(chain, tmp_path / "s.glb")
    sk = g.j["skins"][0]["extras"]["watchmen"]
    assert rec == sk
    names = [g.j["nodes"][n]["name"] for n in g.j["skins"][0]["joints"]]
    if rig == "hierarchy":
        assert rec["joint_nodes"] == names == list(chain.names)
        assert rec["joint_space"].startswith("hierarchy:")
    else:
        assert "joint_nodes" not in rec and names == ["b%d" % k for k in range(chain.NB)]
        assert rec["joint_space"].startswith("flat:")
    assert anim_meta.skeletons(str(binds), rig="flat")["chain"]["joint_space"].startswith("flat:")
