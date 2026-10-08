"""levelmeta: renderer flags of model nodes, the cube-map candidates and the
cube a placement gets from them, culling boxes.

* a cube node is a candidate when it is enabled and visible, on itself and on
  every parent (0x4d5ca9); a reflective object samples the NEAREST candidate
  (0x4d1299).  models[].cube_map applies that to the state of the file;
* models[].opacity / cast_shadow are the node flags of the renderer;
* `culling` lists the CullingBox nodes with their box (0x7111b9).

Synthetic fragments only (the builders of test_p1_level)."""

import pytest

import level_meta as lm

import test_p1_level as tl

ID = tl.ID
SCENE, LVL = 0x10, 0x12
FOLD, HID, C_NEAR, C_FAR, C_OFF, C_HID, C_INV = range(0x30, 0x37)
M_A, M_B, M_C, BOX, BOX2 = range(0x40, 0x45)


@pytest.fixture(scope="module")
def level(tmp_path_factory):
    base = tmp_path_factory.mktemp("p6level") / "extracted"
    n = tl._node
    scene = n(SCENE, "SceneNode", "", None)
    scene += n(LVL, "SceneScope(LoadBlock)", "Lvl", SCENE, 1, assetName="/L/Lvl.fragment")
    tl._write(base / "L" / "Lvl.scene", tl._fragment(scene))
    f = n(FOLD, "Folder", "room", "host", 0)
    # an invisible PVSRootNode hides what is below it (0x48e028); a Folder would not
    f += n(HID, "PVSRootNode", "hidden", "host", 1, Visible=False)
    cube = lambda nid, name, parent, order, pos, **kw: n(
        nid, "CubeMapNode", name, parent, order, localPos=pos, localOrient=ID,
        texture="/L/cubemaps/%s_cubemap.bmp" % name, textureSize=6, **kw,
    )  # fmt: skip
    f += cube(C_NEAR, "near", FOLD, 0, [1.0, 0.0, 0.0])
    f += cube(C_FAR, "far", FOLD, 1, [50.0, 0.0, 0.0])
    f += cube(C_OFF, "off", FOLD, 2, [10.0, 0.0, 0.0], enabled=False)
    f += cube(C_HID, "under_hidden", HID, 0, [10.1, 0.0, 0.0])
    f += cube(C_INV, "invisible", FOLD, 3, [9.9, 0.0, 0.0], Visible=False)
    model = lambda nid, name, order, pos, **kw: n(
        nid, "Model", name, FOLD, order, localPos=pos, localOrient=ID,
        modelNames=["/art/props/%s.model" % name], **kw,
    )  # fmt: skip
    f += model(M_A, "crate", 4, [0.0, 0.0, 0.0])
    f += model(M_B, "glass", 5, [10.0, 0.0, 0.0], opacity=0.64, castShadow=False)
    f += model(M_C, "lamp", 6, [40.0, 0.0, 0.0])
    f += n(
        BOX, "CullingBox(CollisionBoxNode)", "cb", FOLD, 7, localPos=[5.0, 1.0, 0.0],
        localOrient=ID, width=12.5, height=4.0, depth=5.0,
    )  # fmt: skip
    f += n(
        BOX2, "CullingBox(PivotNode)", "flat", FOLD, 8, localPos=[0.0, 0.0, 0.0],
        localOrient=ID, width=2.0, height=3.0,
    )  # fmt: skip
    tl._write(base / "L" / "Lvl.fragment", tl._fragment(f, name="Lvl_Main", singleton=True))
    return lm.build_level(str(base / "L" / "Lvl.scene"), "Lvl", "%08x" % LVL, None)


def _by_name(rows, name):
    return next(r for r in rows if r["name"] == name)


def test_cube_candidates_need_enabled_and_visible_up_the_tree(level):
    cm = level["cube_maps"]
    flags = {c["name"]: (c["enabled_effective"], c["visible"], c["visible_effective"]) for c in cm}
    assert flags == {
        "near": (True, True, True),
        "far": (True, True, True),
        "off": (False, True, True),
        "under_hidden": (True, True, False),  # its own flag is set, its PVS root's is not
        "invisible": (True, False, False),
    }
    assert {c["name"] for c in cm if c["candidate_at_load"]} == {"near", "far"}
    assert level["counts"]["cube_maps"] == 5
    assert level["counts"]["cube_maps_candidate_at_load"] == 2
    assert "0x4d5ca9" in level["cube_map_rule"] and "state of the file" in level["cube_map_rule"]
    ev = level["evidence"]["cube_maps"]
    assert "586" in ev and "659" in ev and "not established" in ev and "0x48e028" in ev
    assert "0x7054b8" in ev and "0x70e0a4" in level["cube_map_rule"]


def test_a_placement_gets_the_nearest_candidate_cube(level):
    models = level["models"]
    near, far = _by_name(level["cube_maps"], "near"), _by_name(level["cube_maps"], "far")
    crate = _by_name(models, "crate")["cube_map"]
    assert crate == {
        "uid": near["uid"],
        "texture": "/L/cubemaps/near_cubemap.bmp",
        "distance": 1.0,
        "same_fragment": True,
    }
    # three nodes are nearer to the glass and none of them is a candidate
    glass = _by_name(models, "glass")["cube_map"]
    assert glass["uid"] == near["uid"] and glass["distance"] == 9.0
    lamp = _by_name(models, "lamp")["cube_map"]
    assert lamp["uid"] == far["uid"] and lamp["distance"] == 10.0


def test_nearest_cube_helper_edge_cases():
    rec = {"world": {"pos": [0.0, 0.0, 0.0]}, "fragment": "/a"}
    assert lm._nearest_cube(rec, []) is None and lm._nearest_cube(rec, None) is None
    c = lambda uid, x, ok=True, frag="/b": {
        "uid": uid,
        "texture": uid + ".bmp",
        "candidate_at_load": ok,
        "fragment": frag,
        "world": {"pos": [x, 0.0, 0.0]},
    }
    assert lm._nearest_cube(rec, [c("n", 1.0, ok=False)]) is None
    # equal distances: the first in file order stays (the engine compares with <)
    got = lm._nearest_cube(rec, [c("a", 2.0), c("b", -2.0), c("c", 3.0, frag="/a")])
    assert got["uid"] == "a" and got["same_fragment"] is False and got["distance"] == 2.0
    assert lm._nearest_cube({"fragment": "/a"}, [c("a", 2.0)]) is None  # no position


def test_model_nodes_carry_the_renderer_flags(level):
    crate, glass = _by_name(level["models"], "crate"), _by_name(level["models"], "glass")
    assert (crate["opacity"], crate["cast_shadow"]) == (1.0, True)
    assert (glass["opacity"], glass["cast_shadow"]) == (0.64, False)
    note = level["conventions"]["model_flags"]
    assert "0x4995c6" in note and "0x5739d0" in note and "shadow_hull" in note


def test_culling_boxes(level):
    cul = level["culling"]
    assert "0x7111b9" in cul["inside_rule"]
    cb, flat = cul["boxes"]
    assert (cb["class"], cb["native"]) == ("CullingBox", "CollisionBoxNode")
    assert (cb["width"], cb["height"], cb["depth"]) == (12.5, 4.0, 5.0)
    assert cb["world"]["pos"] == [5.0, 1.0, 0.0] and cb["enabled"] is True
    # a class without a depth property: unbounded on z, written as null
    assert (flat["width"], flat["height"], flat["depth"]) == (2.0, 3.0, None)
    assert level["counts"]["culling_boxes"] == 2
    assert "0x70e0a4" in level["evidence"]["culling"]


def test_a_level_without_cube_nodes(tmp_path):
    base = tmp_path / "extracted"
    scene = tl._node(SCENE, "SceneNode", "", None)
    scene += tl._node(LVL, "SceneScope(LoadBlock)", "B", SCENE, 1, assetName="/L/B.fragment")
    tl._write(base / "L" / "B.scene", tl._fragment(scene))
    frag = tl._node(
        0x30, "Model", "m", "host", 0, localPos=[0.0, 0.0, 0.0], localOrient=ID,
        modelNames=["/a.model"],
    )  # fmt: skip
    tl._write(base / "L" / "B.fragment", tl._fragment(frag))
    j = lm.build_level(str(base / "L" / "B.scene"), "B", "%08x" % LVL, None)
    assert j["cube_maps"] == [] and j["models"][0]["cube_map"] is None
    assert j["culling"]["boxes"] == []
