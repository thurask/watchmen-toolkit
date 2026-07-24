"""ModelRes skeleton decoding, little- AND big-endian.

Engine node record (FUN_00545927 = Node::Deserialize):

    [pos f32x3][quat f32x4 XYZW][u32 namelen][name\\0][u32 f1][i32 parent]

The transform PRECEDES the name. The superseded decoder attributed each
28-byte transform to the *previous* name, so every bone was published carrying
its successor's rest pose and the last bone was dropped entirely. These tests
build headers whose every node has a distinct position/quaternion/parent, so an
off-by-one, a dropped record or a byte-order slip cannot pass by coincidence.
"""

import numpy as np
import pytest

import extract_skeletons as es
import parse_model_nodes as pmn
from conftest import build_model_header, synthetic_nodes

ORDERS = ["<", ">"]


@pytest.mark.parametrize("order", ORDERS)
def test_parse_recovers_every_node_exactly(order):
    """parse() returns each node's OWN pos/quat/parent, in file order.

    This is the off-by-one regression test: `nodes[i]` and `parse()[i]` must
    agree element-for-element. Because the synthetic positions and quaternions
    are all distinct, shifting the transform table by one bone in either
    direction fails on the very first comparison.
    """
    nodes = synthetic_nodes()
    header = build_model_header(nodes, order)

    names, pos, quat, parent = pmn.parse(header)

    assert len(names) == len(nodes), "a node was dropped or invented"
    assert names[0] == "(root)" and parent[0] == -1
    for i in range(1, len(nodes)):
        nm, p, q, par = nodes[i]
        assert names[i] == nm
        assert np.allclose(pos[i], p, atol=1e-5), "bone %d (%s) has the wrong position" % (i, nm)
        assert np.allclose(quat[i], q, atol=1e-5), "bone %d (%s) has the wrong rotation" % (i, nm)
        assert int(parent[i]) == par


@pytest.mark.parametrize("order", ORDERS)
def test_byte_order_is_autodetected(order):
    """Auto-detection must pick the header's real byte order.

    PC headers are little-endian, X360/PS3 headers big-endian; the record
    layout is identical, only the f32/u32 fields are flipped. Getting this
    wrong yields either zero parsed nodes or garbage transforms.
    """
    header = build_model_header(synthetic_nodes(), order)
    assert pmn._detect_order(header) == order
    forced = pmn.parse(header, order=order)
    auto = pmn.parse(header)
    assert forced[0] == auto[0]
    assert np.allclose(forced[1], auto[1])
    assert np.allclose(forced[2], auto[2])


def test_both_byte_orders_decode_to_the_same_skeleton():
    """The same skeleton stored LE and BE must decode identically.

    Console and PC builds of the same character share a skeleton; if the two
    paths disagreed, animations baked on one would not apply to the other.
    """
    nodes = synthetic_nodes()
    le = pmn.parse(build_model_header(nodes, "<"))
    be = pmn.parse(build_model_header(nodes, ">"))
    assert le[0] == be[0]
    assert np.allclose(le[1], be[1], atol=1e-6)
    assert np.allclose(le[2], be[2], atol=1e-6)
    assert np.array_equal(le[3], be[3])


@pytest.mark.parametrize("order", ORDERS)
def test_skeleton_from_header_publishes_wxyz_and_own_transforms(order):
    """skeleton_from_header() re-publishes parse() faithfully.

    It converts the file's XYZW quaternion to WXYZ and rounds to 6 places; the
    bone list, parents and bone_count must otherwise be exactly parse()'s. A
    regression here would republish the old decoder's shifted table into every
    skeleton_<family>.json.
    """
    nodes = synthetic_nodes()
    header = build_model_header(nodes, order)

    sk = es.skeleton_from_header(header, "female")

    assert sk["family"] == "female"
    assert sk["bone_count"] == len(nodes), "bone_count must count every node incl. the root"
    assert len(sk["bones"]) == len(nodes)
    assert [b["name"] for b in sk["bones"]][1:] == [n[0] for n in nodes[1:]]
    for i in range(1, len(nodes)):
        _nm, p, q, par = nodes[i]
        b = sk["bones"][i]
        assert np.allclose(b["rest_pos"], p, atol=1e-5)
        # file order XYZW -> published WXYZ
        assert np.allclose(b["rest_quat_wxyz"], [q[3], q[0], q[1], q[2]], atol=1e-5)
        assert b["parent"] == par


def test_last_bone_is_not_dropped():
    """The final node in the header must survive the decode.

    The superseded decoder needed a *following* name record to locate a node's
    tail, so it silently lost the last bone of every skeleton -- shifting every
    engine parent index by one from that point on.
    """
    nodes = synthetic_nodes()
    names, pos, quat, parent = pmn.parse(build_model_header(nodes, "<"))
    assert names[-1] == nodes[-1][0]
    assert np.allclose(pos[-1], nodes[-1][1], atol=1e-5)
    assert np.allclose(quat[-1], nodes[-1][2], atol=1e-5)


def test_parents_form_a_single_rooted_tree():
    """Parent indices must index the returned node list, with exactly one root.

    Parent values come from each record and index the file's node array; a
    dropped or added node makes them point at the wrong bone, producing a
    plausible-looking but wrong hierarchy.
    """
    nodes = synthetic_nodes()
    names, _pos, _quat, parent = pmn.parse(build_model_header(nodes, "<"))
    n = len(names)
    assert sum(1 for p in parent if p < 0) == 1
    for i, p in enumerate(parent):
        assert -1 <= int(p) < n
        assert int(p) != i
        depth, j = 0, i
        while parent[j] >= 0:
            j = int(parent[j])
            depth += 1
            assert depth <= n, "cycle in the bone hierarchy"


@pytest.mark.parametrize("order", ORDERS)
def test_node_count_mismatch_raises(order):
    """A header count that disagrees with the parsed count must fail loudly.

    Parent indices are positional. If a record is silently rejected the whole
    hierarchy below it re-parents to the wrong bone and nothing downstream can
    tell. parse() cross-checks the header's declared node count and raises
    instead of emitting a plausible-but-wrong skeleton.
    """
    nodes = synthetic_nodes()
    # node 5's quaternion is pushed off the unit sphere -> record rejected,
    # while the declared count still says every node is present.
    header = build_model_header(nodes, order, break_quat=5)
    with pytest.raises(ValueError, match="node count mismatch"):
        pmn.parse(header)


def test_rest_by_name_matches_parse():
    """rest_by_name() is a keyed view of parse(), not a second decoder.

    It exists so callers can look bones up by name; it must not reintroduce the
    old transform/name attribution, and it must skip only the synthetic root.
    """
    nodes = synthetic_nodes()
    header = build_model_header(nodes, "<")
    rest = pmn.rest_by_name(header)
    assert set(rest) == {n[0] for n in nodes[1:]}
    for _nm, p, q, _par in nodes[1:]:
        assert np.allclose(rest[_nm]["pos"], p, atol=1e-5)
        assert np.allclose(rest[_nm]["quat_wxyz"], [q[3], q[0], q[1], q[2]], atol=1e-5)


def test_quaternions_stay_unit_length():
    """Decoded quaternions must be unit length.

    A non-unit quaternion here means the 16 bytes were read at the wrong offset
    (or in the wrong byte order) -- it is the cheapest available proof that the
    record layout is being honoured.
    """
    for order in ORDERS:
        _n, _p, quat, _par = pmn.parse(build_model_header(synthetic_nodes(), order))
        norms = np.linalg.norm(quat, axis=1)
        assert np.allclose(norms, 1.0, atol=1e-5)
