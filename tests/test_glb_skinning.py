"""Skinning correctness: the rest pose and animation frame 0 must be right.

These evaluate the written .glb the way a glTF viewer does --

    jointMatrix[j] = inverse(global(meshNode)) * global(joint[j]) * IBM[j]
    v' = sum_i weight_i * jointMatrix[JOINTS_i] * v

-- so they test the file, not the code that wrote it.

Regression context: the joint nodes in variant_glb used to be emitted at
identity while the inverse bind matrices were real. Animated playback still
looked right (the animation overwrote the joint TRS), but ANY viewer state
before a clip is picked -- Blender's rest pose, the default glTF viewer, a
thumbnailer -- rendered the mesh in bind-LOCAL space: measured 0.72 m mean
vertex displacement and a mesh collapsed to about a fifth of its animated size.
"""

import numpy as np
import pytest

import rig_glb
import variant_glb as vg
from conftest import parse_glb, skin_vertices


@pytest.fixture
def variant(rig, tmp_path):
    out = tmp_path / "variant.glb"
    vg.write_glb(rig.parts, rig.manifest, out, str(rig.bind_npz))
    return parse_glb(out)


def _mesh_node(glb, skin=0):
    return next(i for i, nd in enumerate(glb.j["nodes"]) if nd.get("skin") == skin)


def _positions(glb, mesh=0, prim=0):
    p = glb.j["meshes"][mesh]["primitives"][prim]
    return (
        glb.accessor(p["attributes"]["POSITION"]).astype(np.float64),
        glb.accessor(p["attributes"]["JOINTS_0"]),
        glb.accessor(p["attributes"]["WEIGHTS_0"]).astype(np.float64),
    )


# ---------------------------------------------------------------------------
# rest pose
# ---------------------------------------------------------------------------


def test_rest_pose_skins_to_the_identity(variant):
    """With no animation applied, every skinned vertex == its POSITION.

    That is only true when the joint nodes' TRS and the inverse bind matrices
    are mutual inverses, i.e. the joints really carry the BIND pose. This is
    the direct regression test for joints emitted at identity: with those, the
    skin matrices become bind^-1 and the whole mesh collapses into bind-local
    space.
    """
    V, J, W = _positions(variant)
    jm = variant.skin_matrices(_mesh_node(variant), 0)
    skinned = skin_vertices(V, J, W, jm)
    assert np.allclose(skinned, V, atol=1e-5), "rest pose displaces the mesh by %.4f m" % float(
        np.abs(skinned - V).max()
    )


def test_rest_pose_joint_matrices_are_identity(variant):
    """Each individual rest-pose joint matrix is the identity, not just the blend.

    Checking the blended result alone could be satisfied by errors that cancel
    across joints; per-joint identity pins that global(joint[k]) == inverse(IBM[k])
    for every k independently.
    """
    jm = variant.skin_matrices(_mesh_node(variant), 0)
    for k, M in enumerate(jm):
        assert np.allclose(M, np.eye(4), atol=1e-5), "joint %d rest matrix is not identity" % k


def test_joint_nodes_carry_the_bind_pose(rig, variant):
    """The joint node TRS must reproduce the bind world matrix from the npz.

    Ties the file back to its input: node k's global transform is B4[k] =
    [Rb[k] | tb[k]]. Also pins that the joints are flat children of an identity
    root, so node-local == node-global.
    """
    G = variant.global_matrices()
    joints = variant.j["skins"][0]["joints"]
    assert len(joints) == rig.NB
    for k, jn in enumerate(joints):
        assert np.allclose(G[jn], rig.B4[k], atol=1e-5), "joint %d is not at its bind pose" % k
        assert "rotation" in variant.j["nodes"][jn] or "translation" in variant.j["nodes"][jn]


def test_inverse_bind_matrices_invert_the_bind_pose(rig, variant):
    """IBM[k] @ B4[k] == I, using the matrices actually stored in the file.

    Catches a column-major/row-major transposition on write, which is invisible
    for rotation-free rigs and catastrophic for real ones.
    """
    ibm = variant.mat4_accessor(variant.j["skins"][0]["inverseBindMatrices"])
    for k in range(rig.NB):
        assert np.allclose(ibm[k] @ rig.B4[k], np.eye(4), atol=1e-5)


# ---------------------------------------------------------------------------
# animated pose
# ---------------------------------------------------------------------------


def test_frame_zero_matches_world_anim_times_inverse_bind(rig, variant):
    """At animation frame 0, v' == worldAnim @ inverse(bind) @ v.

    The palette handed to write_glb IS worldAnim @ inverse(bind); this checks
    the whole round trip -- palette -> joint TRS -> quaternion -> file ->
    glTF skinning -- reproduces it. A transposed rotation, a wrong quaternion
    convention or a bind matrix applied on the wrong side all fail here.
    """
    V, J, W = _positions(variant)
    over = variant.sample_at(0, 0.0)
    jm = variant.skin_matrices(_mesh_node(variant), 0, overrides=over)

    expected_jm = np.einsum("kab,kbc->kac", rig.world[0], rig.invB4)
    assert np.allclose(jm, expected_jm, atol=1e-5)

    got = skin_vertices(V, J, W, jm)
    want = skin_vertices(V, J, W, expected_jm)
    assert np.allclose(got, want, atol=1e-5)


@pytest.mark.parametrize("frame", [0, 1, 3])
def test_every_frame_reproduces_its_palette(rig, variant, frame):
    """Each keyframe's joint matrices equal that frame's palette entry.

    Frame 0 alone would not catch a one-frame shift or a sampler wired to the
    wrong output accessor.
    """
    t = frame / rig.fps
    jm = variant.skin_matrices(_mesh_node(variant), 0, overrides=variant.sample_at(0, t))
    expected = np.einsum("kab,kbc->kac", rig.world[frame], rig.invB4)
    assert np.allclose(jm[:, :3, :], expected[:, :3, :], atol=1e-5)


def test_animation_actually_moves_the_mesh(rig, variant):
    """Sanity floor: the animated pose must differ from the rest pose.

    Without this, a writer that emitted a constant identity animation would
    pass every other test in this module.
    """
    V, J, W = _positions(variant)
    rest = skin_vertices(V, J, W, variant.skin_matrices(_mesh_node(variant), 0))
    last = (rig.F - 1) / rig.fps
    moved = skin_vertices(
        V, J, W, variant.skin_matrices(_mesh_node(variant), 0, overrides=variant.sample_at(0, last))
    )
    assert np.abs(moved - rest).max() > 1e-3


def test_animation_times_span_the_requested_fps(rig, variant):
    """Sampler times must be frame/fps, so the clip plays at the authored rate."""
    sampler = variant.j["animations"][0]["samplers"][0]
    t = variant.accessor(sampler["input"]).astype(np.float64)
    assert len(t) == rig.F
    assert np.allclose(t, np.arange(rig.F) / rig.fps, atol=1e-6)


# ---------------------------------------------------------------------------
# rig_glb: flat rig, identity inverse binds
# ---------------------------------------------------------------------------


@pytest.fixture
def rigged(rig, tmp_path):
    """rig_glb's flat rig: IBM = identity, joint nodes carry the clip's frame 0."""
    F = rig.F
    locT = np.zeros((F, rig.NB, 3), np.float32)
    locQ = np.zeros((F, rig.NB, 4), np.float32)
    for f in range(F):
        for k in range(rig.NB):
            locT[f, k] = rig.tb[k] + 0.01 * f
            q = np.array([0.1 * k, 0.2, 0.3 + 0.05 * f, 1.0])
            locQ[f, k] = q / np.linalg.norm(q)
    out = tmp_path / "rigged.glb"
    rig_glb.build_rigged_glb(
        out,
        rig.V,
        None,
        rig.UV,
        rig.SI.astype(np.uint8),
        rig.SW,
        rig.T,
        [(0, rig.NV, 0, len(rig.T), 56)],
        ["mat_body"],
        {},
        rig.tpl(),
        [
            {
                "name": "clip_test",
                "times": (np.arange(F) / rig.fps).astype(np.float32),
                "locT": locT,
                "locQ": locQ,
                "locS": None,
            }
        ],
        None,
    )
    return parse_glb(out), locT, locQ


def test_rigged_rest_pose_equals_animation_frame_zero(rigged):
    """rig_glb's joint nodes must be authored at the clip's first keyframe.

    The flat rig uses identity inverse binds, so the joint node TRS *is* the
    skin matrix. If the nodes were left at identity the file would snap into a
    different pose the instant the animation was enabled -- the same class of
    bug as the variant_glb identity-joints regression.
    """
    glb, locT, locQ = rigged
    mesh_node = next(i for i, nd in enumerate(glb.j["nodes"]) if nd.get("skin") == 0)
    rest = glb.skin_matrices(mesh_node, 0)
    frame0 = glb.skin_matrices(mesh_node, 0, overrides=glb.sample_at(0, 0.0))
    assert np.allclose(rest, frame0, atol=1e-5)

    for k, jn in enumerate(glb.j["skins"][0]["joints"]):
        nd = glb.j["nodes"][jn]
        assert np.allclose(nd["translation"], locT[0, k], atol=1e-6)
        assert np.allclose(np.abs(nd["rotation"]), np.abs(locQ[0, k]), atol=1e-6)


def test_rigged_inverse_binds_are_identity(rigged):
    """rig_glb documents a FLAT rig: every inverse bind matrix is the identity.

    The joint world transforms therefore have to carry the full pose. Pinning
    the identity IBM keeps the two halves of that contract from drifting apart.
    """
    glb, _locT, _locQ = rigged
    ibm = glb.mat4_accessor(glb.j["skins"][0]["inverseBindMatrices"])
    assert np.allclose(ibm, np.eye(4), atol=0)


def test_rigged_static_mode_emits_no_rig(rig, tmp_path):
    """static=True must emit mesh + materials only -- no skin, no armature.

    Head/accessory models carry their own non-body palette; giving them a rig
    would re-pose them onto the body skeleton and move them off their authored
    position.
    """
    out = tmp_path / "static.glb"
    rig_glb.build_rigged_glb(
        out,
        rig.V,
        None,
        rig.UV,
        rig.SI.astype(np.uint8),
        rig.SW,
        rig.T,
        [(0, rig.NV, 0, len(rig.T), 56)],
        ["mat_body"],
        {},
        rig.tpl(),
        [],
        None,
        static=True,
    )
    glb = parse_glb(out)
    assert "skins" not in glb.j and "animations" not in glb.j
    prim = glb.j["meshes"][0]["primitives"][0]
    assert "JOINTS_0" not in prim["attributes"] and "WEIGHTS_0" not in prim["attributes"]
    assert [nd.get("name") for nd in glb.j["nodes"]] == ["static_mesh"]
    V = glb.accessor(prim["attributes"]["POSITION"]).astype(np.float64)
    assert np.allclose(V, rig.V, atol=1e-6), "static export must not move the vertices"
