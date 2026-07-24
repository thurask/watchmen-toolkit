"""glTF 2.0 / GLB structural conformance for the two .glb writers.

Both writers hand-assemble the container: chunk headers, padding, bufferView
offsets, accessor bounds. Blender, three.js and the Khronos validator all
reject files that get any of it wrong, and the failures are opaque ("Unexpected
end of file", silently missing meshes), so the invariants are pinned here
instead.
"""

import json

import numpy as np
import pytest

import rig_glb
import variant_glb as vg
from conftest import COMPONENT, NCOMP, iter_json, parse_glb

# glTF 2.0 schema sets "minItems": 1 on these; an empty array is invalid.
MIN_ITEMS_1 = (
    "animations",
    "skins",
    "images",
    "textures",
    "materials",
    "samplers",
    "accessors",
    "bufferViews",
    "buffers",
    "meshes",
    "nodes",
    "scenes",
)


@pytest.fixture
def variant_file(rig, tmp_path):
    out = tmp_path / "variant.glb"
    vg.write_glb(rig.parts, rig.manifest, out, str(rig.bind_npz))
    return out


@pytest.fixture
def rigged_file(rig, tmp_path):
    out = tmp_path / "rigged.glb"
    F = rig.F
    clip = {
        "name": "clip_test",
        "times": (np.arange(F) / rig.fps).astype(np.float32),
        "locT": np.tile(rig.tb.astype(np.float32), (F, 1, 1)),
        "locQ": np.tile(np.array([0, 0, 0, 1], np.float32), (F, rig.NB, 1)),
        "locS": None,
    }
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
        [clip],
        None,
    )
    return out


@pytest.fixture(params=["variant", "rigged"])
def glb(request, variant_file, rigged_file):
    return parse_glb(variant_file if request.param == "variant" else rigged_file)


# ---------------------------------------------------------------------------
# container
# ---------------------------------------------------------------------------


def test_container_header(glb):
    """Magic, version and the declared total length must describe the real file.

    `length` is the field a loader trusts to know where the file ends; if it
    disagrees with the byte count the file is truncated or over-read.
    """
    assert glb.magic == b"glTF"
    assert glb.version == 2
    assert glb.total_length == len(glb.raw)


def test_chunk_order_and_padding(glb):
    """JSON chunk first, padded with 0x20; BIN chunk second, padded with 0x00.

    The GLB spec fixes both the chunk order and the padding *byte* -- a JSON
    chunk padded with NULs is a parse error in strict loaders, and unpadded
    chunks put every following chunk header on an unaligned offset.
    """
    assert [t for t, _ in glb.chunks] == [b"JSON", b"BIN\x00"]
    jchunk, bchunk = glb.json_chunk, glb.bin_chunk
    assert len(jchunk) % 4 == 0
    assert len(bchunk) % 4 == 0
    jpad = len(jchunk) - len(jchunk.rstrip(b"\x20"))
    assert jpad < 4 and set(jchunk[len(jchunk) - jpad :]) <= {0x20}
    bpad = len(bchunk) - len(bchunk.rstrip(b"\x00"))
    assert set(bchunk[len(bchunk) - bpad :]) <= {0x00}
    # and the JSON really is JSON after the padding is stripped
    assert json.loads(jchunk.decode("utf-8")) == glb.j


def test_buffer_length_matches_bin_chunk(glb):
    """buffers[0].byteLength must cover the data, and fit inside the BIN chunk."""
    (buf,) = glb.j["buffers"]
    assert "uri" not in buf  # self-contained GLB
    assert buf["byteLength"] <= len(glb.bin_chunk)
    assert len(glb.bin_chunk) - buf["byteLength"] < 4  # only the pad


# ---------------------------------------------------------------------------
# bufferViews / accessors
# ---------------------------------------------------------------------------


def test_buffer_views_are_4_aligned_and_in_range(glb):
    """Every bufferView starts 4-aligned and lies inside the buffer.

    glTF requires accessor data to be aligned to its component size (max 4).
    Since these writers never set accessor.byteOffset, the bufferView offset is
    the only alignment lever -- unaligned float data crashes strict readers and
    silently corrupts on some GPU paths.
    """
    total = glb.j["buffers"][0]["byteLength"]
    for i, bv in enumerate(glb.j["bufferViews"]):
        off = bv.get("byteOffset", 0)
        assert off % 4 == 0, "bufferView %d not 4-aligned" % i
        assert bv["byteLength"] > 0
        assert off + bv["byteLength"] <= total, "bufferView %d overruns the buffer" % i
        assert bv["buffer"] == 0


def test_accessors_are_component_aligned_and_in_range(glb):
    """Each accessor's effective offset satisfies its component alignment.

    The spec's rule is (bufferView.byteOffset + accessor.byteOffset) %
    componentSize == 0, and the accessor's span must fit inside its view.
    """
    for i, a in enumerate(glb.j["accessors"]):
        dt, csz = COMPONENT[a["componentType"]]
        nc = NCOMP[a["type"]]
        bv = glb.j["bufferViews"][a["bufferView"]]
        eff = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        assert eff % csz == 0, "accessor %d violates component alignment" % i
        assert a["count"] > 0
        assert a["count"] * nc * csz <= bv["byteLength"], "accessor %d overruns its view" % i


def test_element_array_views_are_indices_only(glb):
    """Index bufferViews must not share a view with vertex attributes.

    Mixing ELEMENT_ARRAY_BUFFER and ARRAY_BUFFER data in one view is a
    validation error; each `av()` call here allocates a fresh view, and this
    pins that.
    """
    used_by = {}
    for pi, prim in enumerate(p for m in glb.j["meshes"] for p in m["primitives"]):
        for a in prim["attributes"].values():
            used_by.setdefault(glb.j["accessors"][a]["bufferView"], set()).add("attr")
        used_by.setdefault(glb.j["accessors"][prim["indices"]]["bufferView"], set()).add("index")
    for bv, kinds in used_by.items():
        assert len(kinds) == 1, "bufferView %d mixes index and attribute data" % bv


def test_position_accessors_carry_correct_min_max(glb):
    """POSITION must declare min/max, and they must be the real bounds.

    glTF makes min/max mandatory on POSITION; viewers use them for framing and
    frustum culling, so a stale or missing bound makes the model invisible or
    unframeable even though the geometry is fine.
    """
    seen = 0
    for mesh in glb.j["meshes"]:
        for prim in mesh["primitives"]:
            a = glb.j["accessors"][prim["attributes"]["POSITION"]]
            assert a["type"] == "VEC3" and a["componentType"] == 5126
            data = glb.accessor(prim["attributes"]["POSITION"])
            assert "min" in a and "max" in a
            assert np.allclose(a["min"], data.min(0), atol=0, rtol=0)
            assert np.allclose(a["max"], data.max(0), atol=0, rtol=0)
            seen += 1
    assert seen


def test_indices_are_in_range(glb):
    """Every triangle index must address a vertex of its own primitive."""
    for mesh in glb.j["meshes"]:
        for prim in mesh["primitives"]:
            nv = glb.j["accessors"][prim["attributes"]["POSITION"]]["count"]
            idx = glb.accessor(prim["indices"])
            assert idx.size % 3 == 0
            assert int(idx.max()) < nv and int(idx.min()) >= 0
            assert prim.get("mode", 4) == 4


# ---------------------------------------------------------------------------
# skinning data
# ---------------------------------------------------------------------------


def test_joints_component_type_can_address_every_joint(glb):
    """JOINTS_0's integer type must span the skin's joint count.

    A ubyte JOINTS_0 silently wraps past 255 joints: the mesh still loads, but
    high-index bones drive the wrong vertices. Pinning the relationship makes a
    future skeleton growing past the type's range a test failure, not a
    mangled character.
    """
    for skin in glb.j["skins"]:
        njoints = len(skin["joints"])
        for mesh, prim in _prims_using_skin(glb, skin):
            acc = glb.j["accessors"][prim["attributes"]["JOINTS_0"]]
            assert acc["type"] == "VEC4"
            assert acc["componentType"] in (5121, 5123), "JOINTS_0 must be ubyte or ushort"
            _dt, csz = COMPONENT[acc["componentType"]]
            assert njoints - 1 <= (1 << (8 * csz)) - 1, "joint index type too narrow"
            data = glb.accessor(prim["attributes"]["JOINTS_0"])
            assert int(data.max()) < njoints, "JOINTS_0 references a joint outside the skin"


def test_weights_rows_sum_to_one(glb):
    """WEIGHTS_0 rows must sum to ~1 so skinning is a convex blend.

    Rows summing to less than 1 shrink the mesh toward the origin; more than 1
    inflates it. Both look like a broken rig rather than a broken exporter.
    """
    for skin in glb.j["skins"]:
        for _mesh, prim in _prims_using_skin(glb, skin):
            w = glb.accessor(prim["attributes"]["WEIGHTS_0"]).astype(np.float64)
            assert glb.j["accessors"][prim["attributes"]["WEIGHTS_0"]]["type"] == "VEC4"
            assert np.all(w >= 0)
            assert np.allclose(w.sum(1), 1.0, atol=1e-5)


def test_inverse_bind_matrices_match_joint_count(glb):
    """skin.inverseBindMatrices must have exactly one MAT4 per joint.

    A count mismatch is undefined behaviour: loaders either error out or read
    past the end of the accessor and pose random bones.
    """
    for skin in glb.j["skins"]:
        acc = glb.j["accessors"][skin["inverseBindMatrices"]]
        assert acc["type"] == "MAT4" and acc["componentType"] == 5126
        assert acc["count"] == len(skin["joints"])
        ibm = glb.mat4_accessor(skin["inverseBindMatrices"])
        assert np.isfinite(ibm).all()
        assert np.allclose(ibm[:, 3, :], [0, 0, 0, 1]), "IBMs must be affine"


def test_skin_joints_and_skeleton_are_real_nodes(glb):
    """Joint and skeleton references must point at existing nodes.

    Also pins that a skinned mesh node actually references its skin -- an
    unreferenced skin means the mesh renders in bind space and never animates.
    """
    nn = len(glb.j["nodes"])
    for skin in glb.j["skins"]:
        assert all(0 <= jn < nn for jn in skin["joints"])
        assert len(set(skin["joints"])) == len(skin["joints"])
        if "skeleton" in skin:
            assert 0 <= skin["skeleton"] < nn
    skins_used = {nd["skin"] for nd in glb.j["nodes"] if "skin" in nd}
    assert skins_used == set(range(len(glb.j["skins"])))


# ---------------------------------------------------------------------------
# animations
# ---------------------------------------------------------------------------


def test_animation_time_accessors_declare_the_real_range(glb):
    """Animation input (time) accessors must carry min/max == the true range.

    glTF makes min/max mandatory on animation inputs; players use them to
    compute clip length, so a wrong maximum truncates or stretches playback of
    an otherwise correct clip.
    """
    assert glb.j.get("animations")
    for anim in glb.j["animations"]:
        assert anim["samplers"] and anim["channels"]
        for s in anim["samplers"]:
            a = glb.j["accessors"][s["input"]]
            t = glb.accessor(s["input"]).astype(np.float64)
            assert a["type"] == "SCALAR" and a["componentType"] == 5126
            assert "min" in a and "max" in a
            assert np.isclose(a["min"][0], t.min(), atol=1e-6)
            assert np.isclose(a["max"][0], t.max(), atol=1e-6)
            assert np.all(np.diff(t) >= 0), "keyframe times must be non-decreasing"
            assert glb.j["accessors"][s["output"]]["count"] == a["count"]


def test_animation_channels_are_well_formed(glb):
    """Every channel targets a real node with a path matching its output type."""
    expect = {"translation": "VEC3", "scale": "VEC3", "rotation": "VEC4", "weights": "SCALAR"}
    for anim in glb.j["animations"]:
        assert "name" in anim
        for ch in anim["channels"]:
            assert 0 <= ch["sampler"] < len(anim["samplers"])
            path = ch["target"]["path"]
            assert 0 <= ch["target"]["node"] < len(glb.j["nodes"])
            out = glb.j["accessors"][anim["samplers"][ch["sampler"]]["output"]]
            assert out["type"] == expect[path]
            if path == "rotation":
                q = glb.accessor(anim["samplers"][ch["sampler"]]["output"]).astype(np.float64)
                assert np.allclose(np.linalg.norm(q, axis=1), 1.0, atol=1e-4)


# ---------------------------------------------------------------------------
# schema hygiene
# ---------------------------------------------------------------------------


def test_no_empty_arrays_survive_in_the_json(glb):
    """glTF 2.0 sets minItems:1 on the top-level arrays -- none may be empty.

    Both writers pre-create every array and prune the unused ones at the end.
    Forgetting one (or adding a new array without adding it to the prune list)
    produces a file the Khronos validator rejects outright, even though it
    happens to load in Blender.
    """
    empties = [p for p, v in iter_json(glb.j) if isinstance(v, list) and not v]
    assert empties == [], "empty arrays in glTF JSON: %s" % empties
    for key in MIN_ITEMS_1:
        assert key not in glb.j or len(glb.j[key]) >= 1


def test_scene_and_node_graph_are_sane(glb):
    """One scene, valid roots, and a node graph that is a forest (no cycles).

    A node reachable from two parents, or a cycle, makes the world-transform
    computation ill-defined -- the exact thing the skinning tests then rely on.
    """
    assert glb.j["scene"] == 0
    assert len(glb.j["scenes"]) == 1
    nodes = glb.j["nodes"]
    assert glb.j["scenes"][0]["nodes"]
    seen_child = {}
    for i, nd in enumerate(nodes):
        for c in nd.get("children", []):
            assert 0 <= c < len(nodes)
            assert c not in seen_child, "node %d has two parents" % c
            seen_child[c] = i
    roots = [i for i in range(len(nodes)) if i not in seen_child]
    assert set(glb.j["scenes"][0]["nodes"]) <= set(roots)
    for i in range(len(nodes)):
        depth, j = 0, i
        while j in seen_child:
            j = seen_child[j]
            depth += 1
            assert depth <= len(nodes), "cycle in the node graph"
    # every mesh is reachable from the scene
    reachable, stack = set(), list(glb.j["scenes"][0]["nodes"])
    while stack:
        i = stack.pop()
        if i in reachable:
            continue
        reachable.add(i)
        stack += nodes[i].get("children", [])
    assert {i for i, nd in enumerate(nodes) if "mesh" in nd} <= reachable


def test_asset_block_is_present(glb):
    """asset.version is the one mandatory member of a glTF document."""
    assert glb.j["asset"]["version"] == "2.0"
    assert glb.j["asset"].get("generator")


def _prims_using_skin(glb, skin):
    si = glb.j["skins"].index(skin)
    out = []
    for nd in glb.j["nodes"]:
        if nd.get("skin") == si and "mesh" in nd:
            for prim in glb.j["meshes"][nd["mesh"]]["primitives"]:
                if "JOINTS_0" in prim["attributes"]:
                    out.append((nd["mesh"], prim))
    return out
