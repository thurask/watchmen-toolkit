"""tools/blender_import_level.py: the parts that need no Blender.

    paths       the export root from the level file, exact-case joins, the character folder
    frames      the level's and a GLB's coordinate_frame marker; unknown values are refused
    transforms  glTF (x, y, z) / (x, y, z, w) -> Blender (x, -z, y) / (w, x, -z, y)
    plan        what an import creates: groups, names, properties, counts, what is left out
    characters  which variant GLB a placement gets and how that is recorded
    GLB         pruning a character GLB to its scene and one clip; the rewritten container

Synthetic fixtures only; bpy is not imported."""

import json
import math
import os
import struct
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import blender_import_level as bil

TOP = "/Levels/L/Lev/Lev.fragment"


def glb_bytes(doc, blob=b"\x01\x02\x03\x04"):
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(blob), b"BIN\x00")
    body += blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def write_glb(path, frame="right-handed-true", extra=None):
    doc = {
        "asset": {"version": "2.0"},
        "nodes": [{"name": "n", "mesh": 0}],
        "scenes": [{"nodes": [0]}],
    }
    if frame:
        doc["asset"]["extras"] = {"watchmen": {"coordinate_frame": frame}}
    doc.update(extra or {})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(glb_bytes(doc))
    return path


def trs(x, y, z, q=(0.0, 0.0, 0.0, 1.0)):
    return {"gltf": {"translation": [-x, y, z], "rotation": list(q)}, "world": {"pos": [x, y, z]}}


def model(uid, path, x=0.0, y=0.0, z=0.0, **kw):
    m = {"uid": uid, "class": "Model", "name": "", "role": "prop", "models": [path]}
    m.update(
        {"fragment": TOP, "enabled": True, "visible": True, "opacity": 1.0, "cast_shadow": True}
    )
    m.update(trs(x, y, z))
    m.update(kw)
    return m


def character(uid, folder, ctype, status, members, **kw):
    c = {"uid": uid, "id": uid.split(":")[1], "class": "CharacterRoot", "name": "{x}"}
    c.update({"fragment": "/Levels/L/Lev/Gameplay/Enemies.fragment", "enabled": True})
    c["export"] = {"character": folder, "variants": []}
    c["character_type"] = {"value": ctype, "name": "T%d" % ctype}
    c["variant"] = {"status": status, "members": members}
    c["state_of_mind"] = {"value": 1, "name": "AGGRESSIVE"}
    c["weapon_type"] = {"value": -1, "name": "NONE"}
    c["group"] = {"name": "G"}
    c.update(trs(1.0, 2.0, 3.0))
    c.update(kw)
    return c


@pytest.fixture
def export(tmp_path):
    root = tmp_path / "exp"
    for d in ("levels", "models", "textures", "extracted", "nav"):
        (root / d).mkdir(parents=True)
    write_glb(str(root / "models/art/props/Box_01.model.glb"))
    write_glb(str(root / "models/art/props/Lamp.model.glb"))
    write_glb(str(root / "models/art/environments/sky/s/Sky_01.model.glb"))
    write_glb(str(root / "models/art/characters/k/Head.model.glb"))
    write_glb(str(root / "extracted/Levels/L/Lev/Art/T/T.terrain.glb"))
    write_glb(str(root / "nav/Lev.nav.glb"))
    for f, v in (
        ("Thug", "KnotTop_Medium"),
        ("Doms", "Dom_1"),
        ("Doms", "Dom_2"),
        ("Boss", "Boss"),
    ):
        write_glb(str(root / "characters_v1.4.0" / f / (v + ".glb")))
    write_glb(str(root / "characters_v1.4.0/Rorschach/Rorschach.glb"))
    write_glb(str(root / "characters_v1.4.0/Rorschach/Rorschach_Dry.glb"))
    tex = root / "textures/art/environments/common/textures/terrain/Ground_01.bmp"
    tex.mkdir(parents=True)
    (tex / "0_diffuse_4x4_DXT1.png").write_bytes(b"png")
    (tex / "1_normal_4x4_ATI2.png").write_bytes(b"png")
    doc = {
        "format": "watchmen-level-meta/1",
        "coordinate_frame": "right-handed-true",
        "level": {
            "name": "Lev",
            "asset": TOP,
            "hero_models": {
                "rsh": {"model": "/art/characters/rorschach/models/Rorschach_Dry.model"}
            },
        },
        "files": {
            "top_fragment": TOP,
            "terrain": [
                dict(
                    {"uid": "1:aa", "asset": "/Levels/L/Lev/Art/T/T.terrain", "enabled": True},
                    glb="/Levels/L/Lev/Art/T/T.terrain.glb",
                    enabled_effective=True,
                    visible=True,
                    **trs(0.0, 0.0, 0.0),
                )
            ],
        },
        "fragments": [
            {"index": 0, "asset": TOP, "parent": None},
            {"index": 1, "asset": "/Levels/L/Lev/PVS/01_Room.fragment", "parent": 0},
            {"index": 2, "asset": "/art/props/Pile.fragment", "parent": 1},
            {"index": 3, "asset": "/Levels/L/Lev/Gameplay/Mission.fragment", "parent": 0},
            {"index": 4, "asset": "/TNT/Other.fragment", "parent": 0},
        ],
        "models": [
            model("2:00000001", "/art/props/Box_01.model", 1.0, 2.0, 3.0),
            model("1:00000002", "/art/props/Box_01.model", 4.0, 0.0, 0.0),
            model("3:00000003", "/art/props/Lamp.model"),
            model("4:00000004", "/art/props/Gone.model"),
            model("1:00000005", "/art/environments/sky/s/Sky_01.model"),
            model("1:00000006", "/art/props/Lamp.model", enabled=False),
            model("1:00000007", "/art/props/Lamp.model", visible=False),
            model(
                "1:00000008",
                "/art/characters/common/skeletons/Skel.model",
                role="character_model",
                models=[
                    "/art/characters/common/skeletons/Skel.model",
                    "/art/characters/k/Head.model",
                ],
            ),
            model(
                "1:00000009", "/art/characters/k/Head.model", role="character_model", enabled=False
            ),
        ],
        "character_defs": {
            "8": {"export": {"members": [{"index": 0, "name": "KnotTop_Medium"}]}},
            "33": {
                "export": {
                    "members": [
                        {"index": 0, "name": "Dom_1"},
                        {"index": 1, "name": "Dom_2"},
                        {"index": 2, "name": ""},
                    ]
                }
            },
            "35": {"export": {"members": [{"index": 0, "name": ""}]}},
        },
        "characters": [
            character("9:000000c1", "Thug", 8, "fixed", [0]),
            character("9:000000c2", "Doms", 33, "candidates", [0, 1, 2]),
            character("9:000000c3", "Boss", 35, "fixed", [0]),
            character("9:000000c4", "Rorschach", 0, "fixed_scene_model", []),
            character("9:000000c5", "Nobody", 77, "unknown", []),
            character("9:000000c6", "Doms", 33, "candidates", [1, 0], enabled=False),
        ],
    }
    path = root / "levels" / "Lev.level.json"
    path.write_text(json.dumps(doc))
    return str(root), str(path), doc


def by_uid(plan):
    return {i["props"]["watchmen_uid"]: i for i in plan["instances"]}


def test_export_root_and_paths(export, tmp_path):
    root, path, _ = export
    assert bil.find_export_root(path) == root
    with pytest.raises(bil.LevelError, match="models/"):
        bil.find_export_root(str(tmp_path / "elsewhere" / "x.level.json"))
    assert bil.model_glb(root, "/art/props/Box_01.model") == os.path.join(
        root, "models", "art", "props", "Box_01.model.glb"
    )
    with pytest.raises(bil.LevelError):
        bil.join_export(root, "/art/../../x")
    assert bil.characters_dir(root).endswith("characters_v1.4.0")
    os.makedirs(os.path.join(root, "characters_v1.3.0"))
    assert bil.characters_dir(root).endswith("characters_v1.4.0")
    assert bil.nav_glb(root, "Lev") == os.path.join(root, "nav", "Lev.nav.glb")


def test_texture_lookup_ignores_case_of_a_stored_string(export):
    root = export[0]
    png = bil.texture_png(root, "/art/Environments/Common/Textures/Terrain/Ground_01.BMP")
    assert png.endswith("0_diffuse_4x4_DXT1.png")
    assert bil.texture_png(root, "/art/environments/none.bmp") is None
    assert bil.resolve_nocase(root, "../x") is None


def test_frames(export, tmp_path):
    _, path, doc = export
    assert bil.level_frame(doc) == bil.FRAME_TRUE
    mirrored = dict(doc)
    del mirrored["coordinate_frame"]
    assert bil.level_frame(mirrored) == bil.FRAME_MIRRORED
    with pytest.raises(bil.LevelError, match="left-handed"):
        bil.level_frame(dict(doc, coordinate_frame="left-handed"))
    a = write_glb(str(tmp_path / "a.glb"))
    b = write_glb(str(tmp_path / "b.glb"), frame=None)
    assert bil.glb_frame(bil.glb_json(a)) == bil.FRAME_TRUE
    assert bil.glb_frame(bil.glb_json(b)) == bil.FRAME_MIRRORED
    with pytest.raises(bil.LevelError):
        bil.glb_frame({"asset": {"extras": {"watchmen": {"coordinate_frame": "other"}}}})
    bad = tmp_path / "bad.level.json"
    bad.write_text(json.dumps({"format": "something-else"}))
    with pytest.raises(bil.LevelError, match="watchmen-level-meta/1"):
        bil.load_level(str(bad))
    assert bil.load_level(path)["level"]["name"] == "Lev"


def test_gltf_to_blender():
    loc, quat = bil.gltf_to_blender([1.0, 2.0, 3.0], [0.0, 0.0, 0.0, 1.0])
    assert loc == (1.0, -3.0, 2.0) and quat == (1.0, 0.0, 0.0, 0.0)
    # a yaw about glTF +Y is a rotation about Blender +Z by the same angle
    a = math.radians(40.0)
    loc, quat = bil.gltf_to_blender([0, 0, 0], [0.0, math.sin(a / 2), 0.0, math.cos(a / 2)])
    assert quat == pytest.approx((math.cos(a / 2), 0.0, 0.0, math.sin(a / 2)))
    # a rotation about glTF +Z is one about Blender -Y
    loc, quat = bil.gltf_to_blender([0, 0, 0], [0.0, 0.0, math.sin(a / 2), math.cos(a / 2)])
    assert quat == pytest.approx((math.cos(a / 2), 0.0, -math.sin(a / 2), 0.0))
    rec = {"gltf": {"translation": [5.0, 1.0, -2.0], "rotation": [0, 0, 0, 1]}}
    assert bil.placement_trs(rec, 1.0)[0] == (5.0, 2.0, 2.0)


def test_sections(export):
    doc = export[2]
    s = bil.sections(doc)
    assert s == {0: "Lev", 1: "01_Room", 2: "01_Room", 3: "Gameplay/Mission", 4: "Lev"}
    assert bil.instance_index("12:abcd") == 12 and bil.instance_index("x") is None


def test_plan_groups_counts_and_properties(export):
    root, path, doc = export
    plan = bil.build_plan(doc, root, path)
    assert plan["frame"] == bil.FRAME_TRUE and plan["level"] == "Lev"
    u = by_uid(plan)
    a = u["2:00000001"]
    assert a["kind"] == "prop" and a["group"] == ("Props", "01_Room")
    assert a["name"] == "Box_01 2:00000001"
    assert a["glb"] == bil.model_glb(root, "/art/props/Box_01.model")
    assert a["loc"] == (-1.0, -3.0, 2.0) and a["quat"] == (1.0, 0.0, 0.0, 0.0)
    p = a["props"]
    assert p["watchmen_node_id"] == "00000001" and p["watchmen_section"] == "01_Room"
    assert p["watchmen_model"] == "/art/props/Box_01.model" and p["watchmen_fragment"] == TOP
    assert p["watchmen_level"] == "Lev" and p["watchmen_enabled"] is True
    assert u["3:00000003"]["group"] == ("Props", "Gameplay/Mission")
    assert u["1:00000005"]["kind"] == "sky" and u["1:00000005"]["group"] == ("Sky",)
    # a model without a GLB is kept as a placement and reported
    assert u["4:00000004"]["glb"] is None
    assert sorted(plan["missing"]) == sorted(
        [bil.model_glb(root, "/art/props/Gone.model"), "character GLB of Nobody"]
    )
    # a placed Character node: its part models, the skeleton (no mesh, no GLB) left out
    sm = u["1:00000008"]
    assert sm["kind"] == "scene_model" and sm["group"] == ("Characters", "Scene models")
    assert sm["props"]["watchmen_model"] == "/art/characters/k/Head.model"
    assert plan["skipped"] == {
        "props_disabled": 1,
        "props_invisible": 1,
        "scene_model_parts_without_glb": 1,
        "character_models_disabled": 1,
        "characters_disabled": 1,
    }
    c = plan["counts"]
    assert c["model_placements"] == 9 and c["prop_placements"] == 4 and c["sky_placements"] == 1
    assert c["character_placements"] == 6 and c["characters"] == 5
    assert c["instances"] == len(plan["instances"]) == 11
    assert plan["nav"] == bil.nav_glb(root, "Lev")
    assert [t["name"] for t in plan["terrain"]] == ["T"]
    assert plan["terrain"][0]["glb"].endswith(
        os.path.join("extracted", "Levels", "L", "Lev", "Art", "T", "T.terrain.glb")
    )


def test_plan_options(export):
    root, path, doc = export
    plan = bil.build_plan(doc, root, path, characters=False, sky=False, nav=False, disabled=True)
    u = by_uid(plan)
    assert u["1:00000006"]["group"] == ("Disabled",) and u["1:00000007"]["group"] == ("Invisible",)
    assert "1:00000005" not in u and plan["skipped"]["sky"] == 1
    assert plan["skipped"]["characters"] == 6 and plan["nav"] is None
    assert not any(i["kind"] in ("character", "scene_model") for i in plan["instances"])
    few = bil.build_plan(doc, root, path, limit=2)
    assert few["counts"]["prop_placements"] == 2 and few["skipped"]["over_limit"] == 4
    on = by_uid(bil.build_plan(doc, root, path, disabled=True))
    assert on["9:000000c6"]["group"] == ("Disabled",)
    # the second character of definition 33: the second of its candidates [1, 0]
    assert on["9:000000c6"]["props"]["watchmen_variant"] == "Dom_1"


def test_host_offset_copies_go_to_a_collection_of_their_own(export):
    root, path, doc = export
    doc = json.loads(json.dumps(doc))
    by = {m["uid"]: m for m in doc["models"]}
    by["2:00000001"]["host_offset_copy"] = {"twin": "3:00000003"}  # a prop
    by["1:00000008"]["host_offset_copy"] = {"twin": None}  # a placed Character node
    by["1:00000006"]["host_offset_copy"] = {"twin": None}  # disabled
    plan = bil.build_plan(doc, root, path)
    u = by_uid(plan)
    assert bil.HOST_OFFSET_GROUP == ("Host-offset copies",)
    a, sm = u["2:00000001"], u["1:00000008"]
    assert a["group"] == sm["group"] == bil.HOST_OFFSET_GROUP
    assert a["kind"] == "prop" and sm["kind"] == "scene_model"  # what they are stays
    assert a["props"]["watchmen_host_offset_copy"] is True
    assert a["props"]["watchmen_host_offset_twin"] == "3:00000003"
    assert sm["props"]["watchmen_host_offset_copy"] is True
    assert "watchmen_host_offset_twin" not in sm["props"]
    # the placement is the one of the level file, and nothing else moves
    plain = by_uid(bil.build_plan(export[2], root, path))
    assert set(plain) == set(u)
    assert "watchmen_host_offset_copy" not in plain["2:00000001"]["props"]
    for uid, inst in u.items():
        assert (inst["loc"], inst["quat"]) == (plain[uid]["loc"], plain[uid]["quat"])
        if uid not in ("2:00000001", "1:00000008"):
            assert inst["group"] == plain[uid]["group"] != bil.HOST_OFFSET_GROUP
            assert "watchmen_host_offset_copy" not in inst["props"]
    assert plan["counts"]["host_offset_copies"] == 2
    assert plan["counts"]["prop_placements"] == 4 and plan["counts"]["instances"] == 11
    assert "host_offset_copies" not in bil.build_plan(export[2], root, path)["counts"]
    # a disabled record stays with the disabled ones
    assert "1:00000006" not in u and plan["skipped"]["props_disabled"] == 1
    on = by_uid(bil.build_plan(doc, root, path, disabled=True))
    assert on["1:00000006"]["group"] == ("Disabled",)
    assert on["1:00000006"]["props"]["watchmen_host_offset_copy"] is True
    # the collection is switched off after the import, and the text says why
    import inspect

    src = inspect.getsource(bil)
    assert '("Characters", "Scene models"), HOST_OFFSET_GROUP)' in src
    assert "Whether the game draws these nodes is not established" in bil.__doc__
    assert "run by the user on desktop Blender 5.2" in bil.__doc__
    assert "was not inspected in detail" in bil.__doc__


def test_character_variants(export):
    root, path, doc = export
    u = by_uid(bil.build_plan(doc, root, path))
    chars = os.path.join(root, "characters_v1.4.0")
    a = u["9:000000c1"]
    assert a["glb"] == os.path.join(chars, "Thug", "KnotTop_Medium.glb") and a["character"]
    assert a["props"]["watchmen_variant_pick"] == "fixed"
    assert a["group"] == ("Characters", "Thug")
    # 1 m above the placement (glTF y = 2 -> Blender z = 2, + CHARACTER_PIVOT_HEIGHT)
    assert a["loc"] == (-1.0, -3.0, 2.0 + bil.CHARACTER_PIVOT_HEIGHT)
    b = u["9:000000c2"]["props"]
    assert b["watchmen_variant"] == "Dom_1" and b["watchmen_variant_pick"] == "candidate_in_turn"
    assert b["watchmen_variant_candidates"] == "0:Dom_1, 1:Dom_2"
    assert b["watchmen_variant_member"] == 0 and b["watchmen_outfit"] == 1
    c = u["9:000000c3"]["props"]  # the single member has no name: the folder's own GLB
    assert c["watchmen_variant"] == "Boss" and c["watchmen_variant_pick"] == "folder_default"
    d = u["9:000000c4"]  # a hero: the model the level's LevelSceneCtrl names
    assert d["glb"].endswith(os.path.join("Rorschach", "Rorschach_Dry.glb"))
    assert d["props"]["watchmen_variant_pick"] == "scene_model"
    e = u["9:000000c5"]  # no folder in the export: an empty at the placement, not lifted
    assert e["glb"] is None and e["loc"] == (-1.0, -3.0, 2.0)
    plan = bil.build_plan(doc, root, path)
    assert "character GLB of Nobody" in plan["missing"]


def test_candidates_are_handed_out_in_turn_and_outfits_numbered(export):
    root, path, doc = export
    chars = os.path.join(root, "characters_v1.4.0")
    members = [{"index": i, "name": "KnotTop_Medium"} for i in range(3)]
    members.insert(1, {"index": 7, "name": "Other"})  # another name does not count
    doc["character_defs"]["8"] = {"export": {"members": members}}
    doc["characters"] = [
        character("9:%08x" % n, "Thug", 8, "candidates", [0, 1, 2]) for n in range(5)
    ] + [
        character("9:000000d1", "Doms", 33, "candidates", [0, 1, 2]),
        character("9:000000d2", "Doms", 33, "candidates", [0, 1, 2]),
        character("9:000000d3", "Doms", 33, "candidates", [0, 1, 2]),
        character("9:000000d4", "Thug", 8, "fixed", [2]),
    ]
    u = by_uid(bil.build_plan(doc, root, path))
    thugs = [u["9:%08x" % n] for n in range(5)]
    assert {t["glb"] for t in thugs} == {os.path.join(chars, "Thug", "KnotTop_Medium.glb")}
    assert [t["outfit"] for t in thugs] == [1, 2, 3, 1, 2]
    assert [t["props"]["watchmen_variant_member"] for t in thugs] == [0, 1, 2, 0, 1]
    assert [t["props"]["watchmen_outfit"] for t in thugs] == [1, 2, 3, 1, 2]
    assert {t["props"]["watchmen_variant_pick"] for t in thugs} == {"candidate_in_turn"}
    cand = "0:KnotTop_Medium, 1:KnotTop_Medium, 2:KnotTop_Medium"
    assert thugs[0]["props"]["watchmen_variant_candidates"] == cand
    # each definition has its own turn; the member without a name is passed over
    doms = [u["9:000000d%d" % n]["props"]["watchmen_variant"] for n in (1, 2, 3)]
    assert doms == ["Dom_1", "Dom_2", "Dom_1"]
    # a fixed member does not take a turn and keeps its outfit number
    f = u["9:000000d4"]
    assert f["outfit"] == 3 and f["props"]["watchmen_variant_pick"] == "fixed"
    direct = bil.character_choice(doc, doc["characters"][0], chars, turn=7)
    assert (direct["member"], direct["outfit"], direct["pick"]) == (1, 2, "candidate_in_turn")


def test_character_lift_follows_the_placement_up_axis():
    rec = trs(1.0, 2.0, 3.0)
    assert bil.placement_trs(rec) == ((-1.0, -3.0, 2.0), (1.0, 0.0, 0.0, 0.0))
    assert bil.placement_trs(rec, 1.0)[0] == (-1.0, -3.0, 3.0)
    # a turn about the vertical leaves the lift vertical
    h = math.sqrt(0.5)
    loc, _ = bil.placement_trs(trs(1.0, 2.0, 3.0, (0.0, h, 0.0, h)), 1.0)
    assert loc == pytest.approx((-1.0, -3.0, 3.0), abs=1e-12)
    # tilted 90 degrees about glTF x (Blender x): the up axis is Blender -y
    loc, quat = bil.placement_trs(trs(1.0, 2.0, 3.0, (h, 0.0, 0.0, h)), 1.0)
    assert quat == pytest.approx((h, h, 0.0, 0.0))
    assert loc == pytest.approx((-1.0, -4.0, 2.0), abs=1e-12)
    # 7 degrees of tilt move the pivot 12 cm sideways and keep the distance at 1 m
    a = math.radians(7.0) / 2
    loc, _ = bil.placement_trs(trs(0.0, 0.0, 0.0, (math.sin(a), 0.0, 0.0, math.cos(a))), 1.0)
    assert loc == pytest.approx((0.0, -math.sin(2 * a), math.cos(2 * a)), abs=1e-12)
    assert abs(loc[1]) == pytest.approx(0.1219, abs=1e-4)


def test_object_name_and_sky():
    assert bil.object_name("A" * 80, "12:deadbeef") == "A" * 51 + " 12:deadbeef"
    assert len(bil.object_name("A" * 80, "12:deadbeef")) == 63
    assert bil.is_sky("/art/Environments/Sky/x/Sky.model")
    assert not bil.is_sky("/art/props/common/skylights/model/Skylight_07_lit.model")


def test_pick_idle():
    names = [
        "EN1_COM_MOV_idle_stand",
        "EN1_EXP_MOV_idle_fidget_A",
        "EN1_EXP_MOV_idle_stand",
        "GRIP 1H",
    ]
    assert bil.pick_idle(names) == "EN1_EXP_MOV_idle_stand"
    assert bil.pick_idle(["Rsh_EXP_Mov_idle_stand", "x"]) == "Rsh_EXP_Mov_idle_stand"
    assert bil.pick_idle(["EN1_COM_MOV_idle_stand", "run"]) == "EN1_COM_MOV_idle_stand"
    assert bil.pick_idle(["FACE EN1/idle", "run"]) is None


def character_doc():
    return {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [5, 3], "name": "game"}],
        "nodes": [
            {"name": "b0"},  # 0 joint, child of 5
            {"name": "b1"},  # 1 joint, a root outside the scene
            {"name": "OUTFIT 2 x", "mesh": 1, "skin": 1},  # 2 outside the scene
            {"name": "mesh", "mesh": 0, "skin": 0},  # 3
            {"name": "RB.helper", "mesh": 2},  # 4 outside the scene
            {"name": "root", "children": [0]},  # 5
        ],
        "skins": [{"joints": [0, 1]}, {"joints": [0]}],
        "meshes": [{}, {}, {}],
        "animations": [
            {
                "name": "run",
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}],
            },
            {
                "name": "EN1_EXP_MOV_idle_stand",
                "channels": [
                    {"sampler": 0, "target": {"node": 1, "path": "rotation"}},
                    {"sampler": 1, "target": {"node": 4, "path": "translation"}},
                ],
                "samplers": [{}, {}],
            },
        ],
    }


def test_prune_gltf_keeps_the_scene_and_one_clip():
    src = character_doc()
    out = bil.prune_gltf(src, "EN1_EXP_MOV_idle_stand")
    assert src["nodes"][4]["name"] == "RB.helper"  # the input is not changed
    assert [n["name"] for n in out["nodes"]] == ["b0", "b1", "mesh", "root"]
    assert out["nodes"][3]["children"] == [0] and out["nodes"][2]["skin"] == 0
    assert out["skins"] == [{"joints": [0, 1]}]
    # the scene roots, and the joint that had no parent in the scene
    assert out["scenes"] == [{"nodes": [3, 2, 1], "name": "game"}] and out["scene"] == 0
    assert [a["name"] for a in out["animations"]] == ["EN1_EXP_MOV_idle_stand"]
    # the channel on a dropped node is gone, the other follows its node
    assert out["animations"][0]["channels"] == [
        {"sampler": 0, "target": {"node": 1, "path": "rotation"}}
    ]
    assert len(out["meshes"]) == 3
    rest = bil.prune_gltf(src)
    assert "animations" not in rest and len(rest["nodes"]) == 4


def outfit_doc():
    parts = {
        "member_shown": 1,
        "shown_nodes": ["OUTFIT 1 Jacket", "OUTFIT 1 Hair"],
        "members": [
            {"index": 1, "nodes": ["OUTFIT 1 Jacket", "OUTFIT 1 Hair"]},
            {"index": 2, "nodes": ["OUTFIT 2 Jacket"]},
            {"index": 3, "nodes": []},
        ],
    }
    return {
        "asset": {"version": "2.0", "extras": {"watchmen": {"parts": parts}}},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "root", "children": [1, 2, 3, 4]},  # 0
            {"name": "b0"},  # 1
            {"name": "mesh", "mesh": 0, "skin": 0},  # 2
            {"name": "OUTFIT 1 Jacket", "mesh": 1, "skin": 0},  # 3
            {"name": "OUTFIT 1 Hair", "mesh": 2, "skin": 0},  # 4
            {"name": "alternatives", "children": [6, 7]},  # 5 in no scene
            {"name": "WPN_Bat", "mesh": 3, "skin": 0},  # 6
            {"name": "OUTFIT 2 Jacket", "mesh": 4, "skin": 0},  # 7
        ],
        "skins": [{"joints": [1]}],
        "meshes": [{}, {}, {}, {}, {}],
    }


def test_prune_gltf_shows_the_outfit_asked_for():
    src = outfit_doc()
    assert bil.outfit_swap(src, 2) == (["OUTFIT 1 Jacket", "OUTFIT 1 Hair"], ["OUTFIT 2 Jacket"])
    assert bil.outfit_swap(src, 9) is None and bil.outfit_swap(character_doc(), 2) is None
    one = bil.prune_gltf(src, None, 1)
    assert [n["name"] for n in one["nodes"]] == [
        "root",
        "b0",
        "mesh",
        "OUTFIT 1 Jacket",
        "OUTFIT 1 Hair",
    ]
    assert one == bil.prune_gltf(src) == bil.prune_gltf(src, None, 9)
    two = bil.prune_gltf(src, None, 2)
    assert [n["name"] for n in two["nodes"]] == ["root", "b0", "mesh", "OUTFIT 2 Jacket"]
    # the outfit's node hangs where the shown outfit's nodes hung, with its mesh and skin
    assert two["nodes"][0]["children"] == [1, 2, 3] and two["scenes"] == [{"nodes": [0]}]
    assert two["nodes"][3] == {"name": "OUTFIT 2 Jacket", "mesh": 4, "skin": 0}
    three = bil.prune_gltf(src, None, 3)  # an outfit of the common models only
    assert [n["name"] for n in three["nodes"]] == ["root", "b0", "mesh"]
    assert src["nodes"][0]["children"] == [1, 2, 3, 4]  # the input is not changed


def test_write_glb_keeps_the_binary_chunk(tmp_path):
    src = tmp_path / "src.glb"
    blob = bytes(range(256)) * 4
    src.write_bytes(glb_bytes(character_doc(), blob))
    dst = tmp_path / "dst.glb"
    small = bil.prune_gltf(bil.glb_json(str(src)), None)
    bil.write_glb(str(dst), small, str(src))
    raw = dst.read_bytes()
    magic, version, total = struct.unpack_from("<4sII", raw, 0)
    assert (magic, version, total) == (b"glTF", 2, len(raw))
    n, kind = struct.unpack_from("<I4s", raw, 12)
    assert kind == b"JSON" and n % 4 == 0 and json.loads(raw[20 : 20 + n]) == small
    m, kind2 = struct.unpack_from("<I4s", raw, 20 + n)
    assert kind2 == b"BIN\x00" and raw[28 + n : 28 + n + m] == blob
    assert bil.glb_json(str(dst)) == small
    junk = tmp_path / "junk.glb"
    junk.write_bytes(b"x" * 20)
    with pytest.raises(ValueError):
        bil.glb_json(str(junk))


def test_main_without_blender_prints_the_plan(export, capsys):
    assert bil.bpy is None
    assert bil.main([export[1], "--no-characters"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["level"] == "Lev" and out["counts"]["prop_placements"] == 4
    assert out["skipped"]["characters"] == 6
