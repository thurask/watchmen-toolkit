"""Level JSON: which path-object nodes the game binds to its path data.

The path data's path object finds its node by id -- the 1-based index into the AI
world's `aiStaticPathObjectNodes` list (KynapseStaticPathObject 0x48c249 -> 0x4837d5) --
stores itself in the node and takes over its impassable flag;
`AIStaticPathObjectNode::SetIsImpassable` (0x48a559) reaches the path data only through
that link.  A node that is not in the list is never found: it is in the level, but the
path finder does not know it.  `path_objects[].bound_at_run_time` says which is which
and `counts.path_objects_unbound` counts them.

That is what the two Part 1 oddities are: ConstructionSite has 4 path nodes and an empty
list (all four unbound, and disabled), Streets has 15 nodes against a list of 14 (one
unbound copy of a template's nodes).

Synthetic levels only (the level of test_p1_level): no game files.
"""

import level_meta as lm
import test_p1_level as t1

level = t1.level  # the module's synthetic level: list [door2, null, door1], door3 unlisted


def test_a_node_outside_the_list_is_unbound(level):
    po = {p["name"]: p for p in level["path_objects"]}
    assert {k: v["bound_at_run_time"] for k, v in po.items()} == {
        "door1": True,
        "door2": True,
        "door3": False,
    }
    assert all(p["bound_at_run_time"] == (p["ai_world_index"] is not None) for p in po.values())
    assert level["counts"]["path_objects_unbound"] == 1
    assert level["counts"]["path_objects"] == 3
    # the record still describes the node: it is in the level
    assert len(po["door3"]["vertices"]) == 2 and po["door3"]["world"]["pos"][0] == 20.0


def test_a_position_join_does_not_make_a_node_bound(level):
    """The table entry of a null list position can be matched to a node by position
    (what the Bordello entry 45 is), but the engine cannot find that node: unbound."""
    lv = {"path_objects": [dict(p) for p in level["path_objects"]], "counts": {}}
    lm.link_nav(lv, t1._table((1, 1, 10.0), (2, 2, 20.0), (3, 3, 0.0)), source="t.hpd")
    door3 = next(p for p in lv["path_objects"] if p["name"] == "door3")
    assert door3["nav"]["method"] == "position" and door3["bound_at_run_time"] is False
    for name in ("door1", "door2"):
        p = next(q for q in lv["path_objects"] if q["name"] == name)
        assert p["nav"]["method"] == "id" and p["bound_at_run_time"] is True


def test_evidence_names_the_code_and_the_measured_levels(level):
    ev = level["evidence"]["path_objects"]
    for word in ("bound_at_run_time", "0x48c249", "0x48a559", "ConstructionSite", "Streets"):
        assert word in ev
    assert "not established" not in ev


def test_a_level_without_an_ai_world_binds_nothing(tmp_path):
    """Path nodes but no AIWorldNode list (and so no id): every node is unbound."""
    base = tmp_path / "extracted"
    scene = t1._node(t1.SCENE, "SceneNode", "", None)
    scene += t1._node(
        t1.LVL, "SceneScope(LoadBlock)", "Bare", t1.SCENE, 1, assetName="/L/Bare.fragment"
    )
    t1._write(base / "L" / "Bare.scene", t1._fragment(scene))
    lvl = t1._path_object(0x40, "gate", 1, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    lvl += t1._path_object(0x50, "", 2, [5.0, 0.0, 0.0], [5.0, 0.0, 1.0])
    t1._write(base / "L" / "Bare.fragment", t1._fragment(lvl))
    j = lm.build_level(str(base / "L" / "Bare.scene"), "Bare", "%08x" % t1.LVL, None)
    assert j["level"]["ai_world"] is None
    assert [p["bound_at_run_time"] for p in j["path_objects"]] == [False, False]
    assert [p["ai_world_index"] for p in j["path_objects"]] == [None, None]
    assert j["counts"]["path_objects"] == 2 and j["counts"]["path_objects_unbound"] == 2


def test_a_level_without_path_objects_counts_none(tmp_path):
    base = tmp_path / "extracted"
    scene = t1._node(t1.SCENE, "SceneNode", "", None)
    scene += t1._node(
        t1.LVL, "SceneScope(LoadBlock)", "Bare", t1.SCENE, 1, assetName="/L/Bare.fragment"
    )
    t1._write(base / "L" / "Bare.scene", t1._fragment(scene))
    t1._write(base / "L" / "Bare.fragment", t1._fragment(t1._node(0x30, "Folder", "x", "host")))
    j = lm.build_level(str(base / "L" / "Bare.scene"), "Bare", "%08x" % t1.LVL, None)
    assert j["path_objects"] == [] and j["counts"]["path_objects_unbound"] == 0
