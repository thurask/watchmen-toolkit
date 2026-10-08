"""Level JSON additions of the open-items sweep.

forced_state     TriggerActionCharacter.ActionExecute 0x85b858 case 28
ai_sight         AI sight ray cast 0x48b44e (sheet mask against AIWorldNode.collisionMask,
                 physicsType 1 blocks)
ai_world         AIWorldNode masks and generation inputs
hero_models      LevelSceneCtrl references
blocks           block file names come from the top fragment's path
no_collection    command_set_weapon 0x694440
Synthetic binary fixtures only."""

import json, os, struct, sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import kapow_props as kp
import level_meta as lm
import test_level_meta as tl

DEFAULT_SHEET = int.from_bytes(bytes.fromhex("63f07e442f0f1807"), "little")
SEE_THROUGH = int.from_bytes(bytes.fromhex("12ea38493bc52366"), "little")
WORLD, CTRL, RSH, NTO, ACT, ACT0, BLOCK, GLASS, BARE, DEF, ROOT = range(0x60, 0x6B)


def _big(name, v):
    return tl._u(kp.name_hash(name)) + struct.pack("<Q", v)


def _build(tmp_path, monkeypatch, asset="/Levels/T/Street2.fragment", books=None):
    monkeypatch.setenv("WATCHMEN_FRAME", "true")
    monkeypatch.setattr(
        tl,
        "ENTITY",
        tl.ENTITY + ("_emodelrsh", "_emodelnto", "_emodelntohead", "m_emodelcollbash1h"),
    )
    lm._SHEETS.clear()
    base = tmp_path / "extracted"
    scene = tl._node(tl.SCENE, "SceneNode", "", None)
    scene += tl._node(tl.SCENES, "Folder", "Scenes", tl.SCENE)
    scene += tl._node(tl.LVL, "SceneScope(LoadBlock)", "Streets2", tl.SCENES, 1, assetName=asset)
    tl._write(base / "Levels" / "T" / "Test.scene", tl._fragment(scene))
    lvl = tl._node(
        WORLD,
        "AIWorld(AIWorldNode)",
        "",
        "host",
        0,
        aiWorldAsset="/Levels/T/T.aipathdata",
        collisionMask=8192,
        nodeCollisionMask=0,
        useCollisionMasksForMapBuilder=False,
        entityHeight=2.0,
        entityRadius=0.4,
        nbSectors=25,
    )
    lvl += tl._u(kp.name_hash("aiStaticPathObjectNodes")) + tl._u(0)  # an empty list
    lvl += tl._node(CTRL, "LevelSceneCtrl(Node)", "ctrl", "host", 1, _emodelrsh=RSH, _emodelnto=NTO)
    lvl += tl._node(
        RSH,
        "Character",
        "Rorschach",
        CTRL,
        0,
        enabled=False,
        localPos=[0.0, 0.0, 0.0],
        localOrient=tl.ID,
        modelNames=["/art/Rorschach_Dry.model"],
    )
    lvl += tl._node(NTO, "Character", "NiteOwl", CTRL, 1, localPos=[0.0] * 3, localOrient=tl.ID)
    lvl += tl._node(
        ACT,
        "TriggerActionCharacter(Node)",
        "flip",
        "host",
        2,
        m_iactiontype=28,
        m_iinteger1=1,
        m_iinteger2=9,
        m_nnumber1=0.05,
    )
    lvl += tl._node(
        ACT0, "TriggerActionCharacter(Node)", "hold", "host", 3, m_iactiontype=28, m_iinteger2=7
    )
    box = dict(localPos=[0.0] * 3, localOrient=tl.ID, width=1.0, height=1.0, depth=1.0)
    lvl += tl._node(BLOCK, "visionblocker(CollisionBoxNode)", "b", "host", 4, physicsType=1, **box)
    lvl += _big("pivotSheet_Id", DEFAULT_SHEET)
    lvl += tl._node(GLASS, "CollisionBoxNode", "g", "host", 5, physicsType=1, **box)
    lvl += _big("pivotSheet_Id", SEE_THROUGH)
    lvl += tl._node(BARE, "visionblocker(CollisionBoxNode)", "n", "host", 6, **box)
    lvl += tl._node(
        DEF, "CharacterDef(Node)", "{COP}", "host", 7, m_icharactertype=5, m_emodelcollbash1h=None
    )
    lvl += tl._node(
        ROOT,
        "CharacterRoot(PivotNode)",
        "cop",
        "host",
        8,
        localPos=[0.0] * 3,
        localOrient=tl.ID,
        _icharactertype=5,
        _iweapontype=1,
    )
    tl._write(base / "Levels" / "T" / "Street2.fragment", tl._fragment(lvl))
    if books is not None:
        tl._write(base / "pivotbooks" / "default.pb.json", json.dumps(books).encode())
    (found,) = lm.levels(str(tmp_path))
    return lm.build_level(found[0], found[1], found[2], str(tmp_path))


def _node(j, nid):
    (r,) = [n for n in j["graph"]["nodes"] if n["id"] == "%08x" % nid]
    return r


def _vol(j, nid):
    (r,) = [v for v in j["volumes"] if v["uid"].endswith(":%08x" % nid)]
    return r["ai_sight"]


def test_enemy_and_stop_criteria_tables_are_the_registered_values():
    assert lm.ENEMY_STATES[9] == "TWILIGHT_LADY_BACK_FLIP" and lm.ENEMY_STATES[7] == "HANG_BACK"
    assert len(lm.ENEMY_STATES) == 11 and sorted(lm.STOP_CRITERIA) == [1, 2, 4, 8]
    assert lm.AI_BRAIN_ENUMS["agentType"][2] == "FOLLOWAGENT"
    assert lm.AI_BRAIN_ENUMS["pathFindingConstraint"] == {0: "SHORTESTPATH", 1: "STEALTH"}


def test_forced_state_of_action_28(tmp_path, monkeypatch):
    j = _build(tmp_path, monkeypatch)
    fs = _node(j, ACT)["forced_state"]
    assert fs["state"] == 9 and fs["state_name"] == "TWILIGHT_LADY_BACK_FLIP"
    assert fs["for_ai_type"] == 1 and fs["for_ai_type_name"] == "enemy"
    assert fs["criteria_if_match"] == 10
    assert fs["criteria_names_if_match"] == ["TIMER", "STATE_NOT_RUNNING"]
    assert fs["time_s_if_match"] == pytest.approx(0.05)
    assert fs["criteria_otherwise"] == 8 and fs["time_s_otherwise"] == 0.0
    # no positive time: only the "otherwise" pair
    fs0 = _node(j, ACT0)["forced_state"]
    assert fs0["state_name"] == "HANG_BACK" and "criteria_if_match" not in fs0
    assert fs0["criteria_otherwise"] == 8
    assert j["counts"]["forced_state_actions"] == 2
    assert "0x85b858" in j["evidence"]["forced_state"]


def test_ai_world_masks_and_generation(tmp_path, monkeypatch):
    j = _build(tmp_path, monkeypatch)
    w = j["level"]["ai_world"]
    assert w["asset"] == "/Levels/T/T.aipathdata"
    assert w["collision_mask"] == 8192 and w["node_collision_mask"] == 0
    assert w["use_collision_masks_for_map_builder"] is False
    assert list(w["generation"]) == list(lm.AI_WORLD_GENERATION)
    assert w["generation"]["entityHeight"] == 2.0 and w["generation"]["nbSectors"] == 25
    assert w["generation"]["pitch"] is None  # not stored on this node
    assert w["pivot_sheet_source"].startswith("bundled")


def test_ai_sight_needs_the_sheet_bit_and_a_rigid_body(tmp_path, monkeypatch):
    j = _build(tmp_path, monkeypatch)
    b = _vol(j, BLOCK)
    assert b["sheet"] == "default" and b["sheet_collision_mask"] == 9771
    assert b["sheet_has_ai_bit"] is True and b["physics_type"] == 1 and b["blocks"] is True
    g = _vol(j, GLASS)  # rigid body on a sheet the AI ray does not report
    assert g["sheet"] == "SolidCollisionAiCanSeeThrough"
    assert g["sheet_has_ai_bit"] is False and g["blocks"] is False
    n = _vol(j, BARE)  # stores neither property: no default is assumed
    assert n == {
        "sheet": None,
        "sheet_book": None,
        "sheet_collision_mask": None,
        "sheet_has_ai_bit": None,
        "physics_type": None,
        "blocks": None,
        "sheet_source": "not stored",
    }
    assert b["sheet_source"] == g["sheet_source"] == "stored id"
    assert j["counts"]["volumes_block_ai_sight"] == 1


def test_pivot_books_of_the_extract_win_over_the_bundled_table(tmp_path, monkeypatch):
    book = {
        "blocks": [
            {"class": "PivotBook", "props": []},
            {
                "class": "PivotSheet",
                "props": [
                    {"key": "name", "value": "default"},
                    {"key": "uniqueID", "value": {"hex": "63f07e442f0f1807"}},
                    {"key": "collisionMask", "value": 16},
                ],
            },
        ]
    }
    j = _build(tmp_path, monkeypatch, books=book)
    assert j["level"]["ai_world"]["pivot_sheet_source"] == "pivot books of the extract"
    b = _vol(j, BLOCK)
    assert b["sheet_book"] == "/pivotbooks/default.pb" and b["sheet_collision_mask"] == 16
    assert b["sheet_has_ai_bit"] is False and b["blocks"] is False
    assert _vol(j, GLASS)["sheet"] is None  # not in the book that was read


def test_console_pivot_book_ids_are_two_big_endian_words(tmp_path, monkeypatch):
    """A console book stores the id as two big-endian words, low word first
    (447ef063 07180f2f for the id PC stores as 63f07e44 2f0f1807); the node's
    pivotSheet_Id is the same number on every platform."""
    book = {
        "blocks": [
            {
                "class": "PivotSheet",
                "props": [
                    {"key": "name", "value": "default"},
                    {"key": "uniqueID", "value": {"hex": "447ef06307180f2f"}},
                    {"key": "collisionMask", "value": 9771},
                ],
            },
            {"class": "PivotSheet", "props": [{"key": "uniqueID", "value": {"hex": "0102"}}]},
        ]
    }
    j = _build(tmp_path, monkeypatch, books=book)
    b = _vol(j, BLOCK)
    assert b["sheet"] == "default" and b["sheet_has_ai_bit"] is True and b["blocks"] is True


def test_bundled_pivot_sheet_table():
    lm._SHEETS.clear()
    table, source = lm.pivot_sheets(None)
    rows = {id(r): r for r in table.values()}.values()
    assert len(rows) == 47 and source.startswith("bundled")
    by = {}
    for r in rows:
        by[r["book"]] = by.get(r["book"], 0) + 1
    assert by == {
        "/pivotbooks/collisionprimitives.pb": 26,
        "/pivotbooks/default.pb": 12,
        "/pivotbooks/mockupbox.pb": 9,
    }
    assert table[511175253393600611]["name"] == "default"  # the id a vision blocker stores
    assert sum(1 for r in rows if r["collision_mask"] & 8192) == 18


def test_hero_models_are_the_level_scene_ctrl_references(tmp_path, monkeypatch):
    h = _build(tmp_path, monkeypatch)["level"]["hero_models"]
    assert h["ctrl"].endswith(":%08x" % CTRL)
    assert h["rsh"]["model"] == "/art/Rorschach_Dry.model" and h["rsh"]["enabled"] is False
    assert h["rsh"]["name"] == "Rorschach" and h["rsh"]["uid"].endswith(":%08x" % RSH)
    assert h["nto"]["model"] is None and h["nto"]["name"] == "NiteOwl"
    assert h["nto_head"] is None and h["rsh_rage"] is None and h["nto_flashing"] is None


def test_block_names_come_from_the_top_fragment(tmp_path, monkeypatch):
    j = _build(tmp_path, monkeypatch)
    assert j["level"]["name"] == "Streets2"
    assert j["files"]["blocks"] == ["street2.block_h_z", "street2.block_s_z"]
    assert j["files"]["top_fragment"] == "/Levels/T/Street2.fragment"


def test_weapon_asked_for_without_a_collection(tmp_path, monkeypatch):
    j = _build(tmp_path, monkeypatch)
    (c,) = j["characters"]
    assert c["weapon_type"]["value"] == 1
    assert c["weapon"]["status"] == "none" and c["weapon"]["no_collection"] is True
    assert c["weapon"]["collection"] == "bash_2h"
    assert j["counts"]["weapons_no_collection"] == 1
    # no weapon asked for: no flag
    assert "no_collection" not in lm._weapon({"export": {"weapons": {}}}, -1, 0)
    assert "no_collection" not in lm._weapon(None, 1, 0)


# ----------------------------------------------------------- save file button map
def _button_words(filled, put=(), dev=6, players=2, buttons=41, codes=3):
    """The words of a list(list(list(list(integer)))) value as a profile stores it:
    every device has `players` entries, a (device, player) of `filled` has all its
    buttons (code -1 except `put` = [(device, player, button, slot, code)]), any other
    player has none."""
    w = [dev]
    for d in range(dev):
        w.append(players)
        for p in range(players):
            if (d, p) not in filled:
                w.append(0)
                continue
            w.append(buttons)
            for b in range(buttons):
                cs = [-1] * codes
                for d2, p2, b2, k, c in put:
                    if (d2, p2, b2) == (d, p, b):
                        cs[k] = c
                w.append(codes)
                w.extend(c & 0xFFFFFFFF for c in cs)
    return w


def test_save_button_map_is_named_by_device_player_and_button():
    # the shipped profile: device 0 both players, devices 1 and 2 player 0 only
    words = _button_words(
        [(0, 0), (0, 1), (1, 0), (2, 0)],
        put=[(1, 0, 0, 0, 200), (1, 0, 1, 0, 208), (1, 0, 21, 0, 33), (1, 0, 21, 1, 257)]
        + [(0, 1, 40, 2, 5), (2, 0, 9, 0, 3)],
    )
    assert len(words) == 675  # the size of the shipped record
    data = tl._save(
        "Settings",
        [(0x11, "m_emetadevicebuttonmap", "list(list(list(list(integer))))", words)],
    )
    j = lm.parse_save(data)
    (rec,) = j["records"]
    assert rec["type"] == "list(list(list(list(integer))))" and "raw_words" not in rec
    bm = j["decoded"]["button_map"]
    assert bm["shape"] == [6, 2, 41, 3]
    assert bm["index_order"] == ["save_device", "player", "logical_button", "code"]
    assert list(bm["devices"]) == ["X360_PS3", "KEYBOARD_MOUSE", "GENERIC_PC_GAMEPAD"]
    (kb,) = bm["devices"]["KEYBOARD_MOUSE"]
    assert kb == {
        "player": 0,
        "buttons": {"MENU_UP": [200], "MENU_DOWN": [208], "PLAYER_ATTACK_0": [33, 257]},
    }
    assert bm["devices"]["X360_PS3"] == [{"player": 1, "buttons": {"40": [5]}}]
    assert bm["devices"]["GENERIC_PC_GAMEPAD"][0]["buttons"] == {"9": [3]}  # 9 is not registered
    assert "inferred from the content" in bm["evidence"] and "0x82bc77" in bm["evidence"]


def test_button_map_of_another_shape_is_left_alone():
    assert lm.button_map(None) is None and lm.button_map([]) is None
    assert lm.button_map([[1, 2], [3]]) is None and lm.button_map([[[1, 2]]]) is None
    assert lm.button_map([[[], []]]) == dict(
        lm.button_map([[[], []]]), shape=[1, 2, 0, 0], devices={}
    )
    assert lm.SAVE_DEVICES[1] == "KEYBOARD_MOUSE" and len(lm.SAVE_DEVICES) == 6
    assert lm.LOGICAL_INPUT_BUTTONS[0] == "MENU_UP" and 40 not in lm.LOGICAL_INPUT_BUTTONS
