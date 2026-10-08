"""Level JSON: where a level puts its `.terrain` (`files.terrain`).

The terrain GLB is written in asset space; the TerrainNode's transform composed with its
parents places it.  Bordello's node has localPos (0, -24, 76) under a fragment host at
(0, 24, -76), so its world placement is the origin: the fixture repeats that shape.
Synthetic binary fixtures only."""

import os, sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import level_meta as lm
import test_level_meta as tl

ASSET = "/Levels/T/Art/Terrain/T_01/T_01.terrain"
HOUSE, FOLDER, TERRAIN, PLAIN = 0x70, 0x71, 0x72, 0x73


def _level(tmp_path, level_pos, level_quat, frame):
    base = tmp_path / "extracted"
    scene = tl._node(tl.SCENE, "SceneNode", "", None)
    scene += tl._node(tl.SCENES, "Folder", "Scenes", tl.SCENE)
    scene += tl._node(
        tl.LVL,
        "SceneScope(LoadBlock)",
        "Lvl",
        tl.SCENES,
        1,
        localPos=level_pos,
        localOrient=level_quat,
        assetName="/Levels/T/Lvl.fragment",
    )
    tl._write(base / "Levels" / "T" / "Test.scene", tl._fragment(scene))
    lvl = tl._node(
        HOUSE, "PivotNode", "house", "host", 0, localPos=[0.0, 24.0, -76.0], localOrient=tl.ID
    )
    lvl += tl._node(FOLDER, "Folder", "Terrain", HOUSE, 0)
    lvl += tl._node(
        TERRAIN,
        "TerrainNode",
        "",
        FOLDER,
        1,
        localPos=[0.0, -24.0, 76.0],
        localOrient=tl.ID,
        terrainAsset=ASSET,
        terrainColoringAsset="",
        metersPerQuad=1.0,
        quadsPerUserSector=64,
        widthInUserSectors=6,
        heightInUserSectors=8,
        textureTiling=2,
    )
    lvl += tl._node(PLAIN, "PivotNode", "no terrain", "host", 1, localPos=[1.0, 0.0, 0.0])
    tl._write(base / "Levels" / "T" / "Lvl.fragment", tl._fragment(lvl))
    os.environ["WATCHMEN_FRAME"] = frame
    (found,) = lm.levels(str(tmp_path))
    return lm.build_level(found[0], found[1], found[2], str(tmp_path))


@pytest.fixture
def frames(monkeypatch):
    monkeypatch.setenv("WATCHMEN_FRAME", "true")  # restored after the test


def test_terrain_placement_is_the_composed_transform_not_local_pos(tmp_path, frames):
    j = _level(tmp_path, [0.0, 0.0, 0.0], tl.ID, "true")
    assert j["files"]["loose"] == [ASSET]  # the old list is unchanged
    (t,) = j["files"]["terrain"]
    assert t["class"] == "TerrainNode" and t["asset"] == ASSET and t["glb"] == ASSET + ".glb"
    assert t["uid"].endswith(":%08x" % TERRAIN) and t["stable_uid"].startswith("%08x@" % TERRAIN)
    assert t["local"] == {"pos": [0.0, -24.0, 76.0], "quat": tl.ID}
    assert t["world"]["pos"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert t["world"]["quat"] == pytest.approx(tl.ID)
    assert t["gltf"]["translation"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-6)
    assert t["scale"] is None and t["coloring_asset"] is None
    assert t["enabled"] and t["enabled_effective"] and t["visible"]
    assert t["node"] == {
        "metersPerQuad": 1.0,
        "quadsPerUserSector": 64,
        "widthInUserSectors": 6,
        "heightInUserSectors": 8,
        "textureTiling": 2,
    }
    assert "composed" in j["files"]["terrain_rule"] and "terrain" in j["evidence"]["files"]


@pytest.mark.parametrize("frame", ["true", "mirrored"])
def test_terrain_gltf_follows_the_frame_of_the_file(tmp_path, frames, frame):
    j = _level(tmp_path, [10.0, 0.0, 3.0], tl.Q90, frame)
    (t,) = j["files"]["terrain"]
    # level (10, 0, 3) turned 90 degrees about +Y; house and terrain offsets cancel
    assert t["world"]["pos"] == pytest.approx([10.0, 0.0, 3.0], abs=1e-4)
    assert t["world"]["quat"] == pytest.approx(tl.Q90, abs=1e-6)
    want = lm.gltf_trs(t["world"]["pos"], t["world"]["quat"], frame)
    assert t["gltf"]["translation"] == pytest.approx(want["translation"], abs=1e-6)
    assert t["gltf"]["rotation"] == pytest.approx(want["rotation"], abs=1e-6)
    x = -10.0 if frame == "true" else 10.0
    assert t["gltf"]["translation"] == pytest.approx([x, 0.0, 3.0], abs=1e-4)
    assert ("coordinate_frame" in j) == (frame == "true")


def test_level_without_a_terrain_has_an_empty_list(tmp_path, frames):
    base = tmp_path / "extracted"
    scene = tl._node(tl.SCENE, "SceneNode", "", None)
    scene += tl._node(tl.SCENES, "Folder", "Scenes", tl.SCENE)
    scene += tl._node(
        tl.LVL, "SceneScope(LoadBlock)", "Lvl", tl.SCENES, 1, assetName="/Levels/T/Lvl.fragment"
    )
    tl._write(base / "Levels" / "T" / "Test.scene", tl._fragment(scene))
    lvl = tl._node(PLAIN, "PivotNode", "p", "host", 0, localPos=[1.0, 0.0, 0.0])
    tl._write(base / "Levels" / "T" / "Lvl.fragment", tl._fragment(lvl))
    (found,) = lm.levels(str(tmp_path))
    j = lm.build_level(found[0], found[1], found[2], str(tmp_path))
    assert j["files"]["terrain"] == [] and j["files"]["loose"] == []
