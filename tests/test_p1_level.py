"""Level export, second pass: what the level file fixes about spawned models, the
path-object join by id, AI start state, orchestrator presets, groups, cube maps,
movie subtitle tables, and the nav file's generation stamp.

Model picker    CharacterModelCollection.command_get_model 0x66ca15 (member list
                0x66cd2a), CharacterDef.command_get_override_model 0x666d03,
                CharacterRoot.command_set_weapon 0x694378
Path-object id  AIWorldNode aiStaticPathObjectNodes, lookup 0x4837d5
State of mind   Enemy.Evaluate 0x72587d (PASSIVE branch 0x726214), SET_AI_STATE
                TriggerActionCharacter.SetAIState 0x852a28 / initialize_local 0x855ecb
Presets         TriggerActionGeneral.TriggerTrig 0x851fba,
                CombatOrchestratorParameters.command_trig 0x6d9128
Groups          CharacterGroup.initialize_local 0x668a0e / initialize_external 0x668a99
Cube maps       nearest CubeMapNode 0x4d1299
Synthetic binary fixtures only: every file below is built in the test."""

import os, struct, sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import kapow_fragment as kf
import kapow_props as kp
import level_meta as lm
import nav_data as nd


def _u(*v):
    return struct.pack("<%dI" % len(v), *v)


def _f(*v):
    return struct.pack("<%df" % len(v), *v)


def _str(s):
    b = s.encode("latin1") + b"\0"
    b += b"\0" * (-len(b) % 4)
    return _u(len(b) // 4) + b


def _ent(v):
    """None -> null, "host" -> tag 2, int -> tag 3, ("single", ids) -> tag 5."""
    if v is None:
        return _u(1)
    if v == "host":
        return _u(2)
    if isinstance(v, int):
        return _u(3, v)
    return _u(5, len(v[1]), *v[1])


def _val(key, v):
    typ = (kf.NAMES.get(kp.name_hash(key)) or (key, None))[1]
    if typ == "Entity":
        return _ent(v)
    if typ == "list(Entity)":
        return _u(len(v)) + b"".join(_ent(x) for x in v)
    if isinstance(v, bool):
        return _u(int(v))
    if isinstance(v, int):
        return _u(v & 0xFFFFFFFF)
    if isinstance(v, float):
        return _f(v)
    if isinstance(v, str):
        return _str(v)
    if isinstance(v, list) and v and isinstance(v[0], str):
        return _u(len(v)) + b"".join(_str(s) for s in v)
    return _f(*v)


def _node(nid, typ, name, parent, order=0, **props):
    b = _u(0xFFFFFFFF, nid) + _str(typ) + _u(0xFFFFFFFE, nid)
    b += _u(kp.name_hash("name")) + _str(name)
    b += _u(kp.name_hash("logicalParent")) + _ent(parent)
    b += _u(kp.name_hash("siblingOrder")) + _u(order)
    for k, v in props.items():
        b += _u(kp.name_hash(k)) + _val(k, v)
    return b


def _fragment(payload, name="", singleton=False):
    nm = name.encode("latin1") + b"\0"
    head = _u(4) + bytes([int(singleton), 0]) + _u(len(nm)) + nm + bytes([0, 0]) + _u(1)
    return head + _u(len(payload)) + payload


def _write(path, data):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as fh:
        fh.write(data)


ID = [0.0, 0.0, 0.0, 1.0]
GEH = kp.name_hash("GE")

SCENE, SCENES, LVL, GE = 0x10, 0x11, 0x12, 0x14
# game essentials
DB, ORCH, P1, P2, HERO_DEF, SLOT, MOV1, MOV2 = range(0x50, 0x58)
# level
DEFS, DEF_G, COLL_G, M_A, M_B, M_C, DEF_T, COLL_T, M_T, W1, W_A, W_B, HEADS = range(0x100, 0x10D)
GRP, ZONE, R0, R1, R2, GRP2, RP, R3, GRP3, R4, R5, INNER = range(0x120, 0x12C)
SET, FM, TRIG, TRIG2, CUBE1, CUBE2, MOVACT, AIW = range(0x140, 0x148)
PO1, PO1A, PO1B, PO2, PO2A, PO2B, PO3, PO3A, PO3B = range(0x160, 0x169)


def _root(nid, name, parent, order, pos, **props):
    return _node(
        nid, "CharacterRoot(PivotNode)", name, parent, order, localPos=pos, localOrient=ID, **props
    )


def _path_object(nid, name, order, a, b):
    out = _node(nid, "AIStaticPathObjectNode", name, "host", order, localPos=a, localOrient=ID)
    out += _node(
        nid + 1,
        "AIStaticPathObjectVertexNode",
        "",
        nid,
        0,
        localPos=[0.0, 0.0, 0.0],
        localOrient=ID,
    )
    d = [b[i] - a[i] for i in range(3)]
    out += _node(nid + 2, "AIStaticPathObjectVertexNode", "", nid, 1, localPos=d, localOrient=ID)
    return out


@pytest.fixture(scope="module")
def level(tmp_path_factory):
    base = tmp_path_factory.mktemp("p1level") / "extracted"
    scene = _node(SCENE, "SceneNode", "", None)
    scene += _node(SCENES, "Folder", "Scenes", SCENE)
    scene += _node(
        LVL,
        "SceneScope(LoadBlock)",
        "Lvl",
        SCENES,
        1,
        assetName="/Levels/T/Lvl.fragment",
        m_ecutscenemovie=("single", [GEH, MOV1]),
        m_ecreditsmovie=("single", [GEH, MOV2]),
    )
    scene += _node(
        GE, "SceneScope(FragmentNode)", "GameEssentials", SCENE, 5, assetName="/TNT/GE.fragment"
    )
    _write(base / "Levels" / "T" / "Test.scene", _fragment(scene))

    ge = _node(DB, "Folder", "Db", "host")
    ge += _node(
        ORCH,
        "CombatOrchestrator(Node)",
        "",
        DB,
        0,
        m_nengagementdist=8.0,
        m_irunningcharactersclamp=5,
        _nattackcooldown=2.0,
        _imaxnumberofattacks=3,
        _nattackfrequency=0.25,
        _nidletime=0.5,
    )
    for nid, name, order, cool, mx in ((P1, "Level 001", 1, 4.0, 2), (P2, "Level 002", 2, 3.0, 4)):
        ge += _node(
            nid,
            "CombatOrchestratorParameters(Node)",
            name,
            DB,
            order,
            m_toninitialize=False,
            m_nengagementdist=12.0,
            m_nattackcooldown=cool,
            m_imaxnumberofattacks=mx,
            m_nattackfrequency=0.5,
            m_nidletime=1.5,
        )
    ge += _node(
        HERO_DEF,
        "CharacterDef(Node)",
        "{RORSCHACH}",
        DB,
        3,
        m_icharactertype=0,
        m_eoverridemodelcollection=None,
        m_emodelcollbash1h=None,
        m_emodelcollbash2h=None,
    )
    ge += _node(SLOT, "SubtitleSlot", "CutSlot", DB, 4, textres="/Localize/Cut_uk.txt")
    ge += _node(
        MOV1,
        "MoviePlayerCtrl(MoviePlayer)",
        "Cut",
        DB,
        5,
        movie="/Art/cutscenes/Cut.bik",
        isLocalized=False,
        subtitleSlot=SLOT,
        m_econtinuelink=MOV2,
    )
    ge += _node(
        MOV2,
        "MoviePlayerCtrl(MoviePlayer)",
        "Credits",
        DB,
        6,
        movie="/Art/cutscenes/Credits.bik",
        isLocalized=False,
        subtitleSlot=None,
        m_econtinuelink=None,
    )
    _write(base / "TNT" / "GE.fragment", _fragment(ge, singleton=True))

    lvl = _node(DEFS, "Folder", "Defs", "host", 0)
    lvl += _node(
        DEF_G,
        "CharacterDef(Node)",
        "{GIMP}",
        DEFS,
        0,
        m_icharactertype=34,
        m_eoverridemodelcollection=COLL_G,
        m_emodelcollbash1h=W1,
        m_emodelcollbash2h=None,
    )
    lvl += _node(
        COLL_G, "CharacterModelCollection(Node)", "Model", DEFS, 1, _eheadmodelcollection=HEADS
    )
    # file order B, A, C; sibling order A, B, C.  B and C share priority 2; C has no name
    for nid, name, order, prio, head in (
        (M_B, "B", 2, 2, 20),
        (M_A, "A", 1, 0, 19),
        (M_C, "", 3, 2, 21),
    ):
        lvl += _node(
            nid,
            "CharacterHeadModel(Character)",
            name,
            COLL_G,
            order,
            m_iprioritymodel=prio,
            m_iheadmodeltype=head,
            modelNames=["/art/gimp/%s.model" % (name or "c")],
        )
    lvl += _node(
        DEF_T,
        "CharacterDef(Node)",
        "{TWILIGHT_LADY}",
        DEFS,
        2,
        m_icharactertype=35,
        m_eoverridemodelcollection=COLL_T,
        m_emodelcollbash1h=None,
        m_emodelcollbash2h=None,
    )
    lvl += _node(COLL_T, "CharacterModelCollection(Node)", "Model", DEFS, 3)
    lvl += _node(
        M_T,
        "CharacterHeadModel(Character)",
        "",
        COLL_T,
        1,
        m_iprioritymodel=0,
        m_iheadmodeltype=30,
        modelNames=["/art/lady/lady.model"],
    )
    lvl += _node(W1, "CharacterModelCollection(Node)", "Weapons_1H", DEFS, 4)
    lvl += _node(
        W_A, "WeaponBase(Model)", "", W1, 1, m_iprioritymodel=1, modelNames=["/art/w/bat.model"]
    )
    lvl += _node(
        W_B, "WeaponBase(Model)", "", W1, 2, m_iprioritymodel=2, modelNames=["/art/w/knife.model"]
    )
    lvl += _node(HEADS, "CharacterModelCollection(Node)", "Heads", DEFS, 5)

    # a group without a zone reference: its first physics-type-2 child is the zone
    lvl += _node(
        GRP, "CharacterGroup(Folder)", "guards", "host", 1, m_vreturnposition=[9.0, 9.0, 9.0]
    )
    lvl += _node(
        ZONE, "CollisionBoxNode", "zone", GRP, 0, localPos=[0.0, 0.0, 0.0], localOrient=ID,
        physicsType=2, width=4.0, height=2.0, depth=4.0,
    )  # fmt: skip
    lvl += _root(
        R0, "r0", GRP, 1, [1.0, 2.0, 3.0],
        _icharactertype=34, m_iprioritymodel=0, _iweapontype=0, m_ipriorityweaponmodel=2,
        m_istateofmind=0,
    )  # fmt: skip
    lvl += _root(
        R1, "r1", GRP, 2, [2.0, 0.0, 0.0],
        _icharactertype=34, m_iprioritymodel=2, _iweapontype=0, m_ipriorityweaponmodel=0,
        m_istateofmind=1,
    )  # fmt: skip
    lvl += _node(INNER, "Folder", "inner", GRP, 3)
    lvl += _root(
        R2, "r2", INNER, 0, [3.0, 0.0, 0.0],
        _icharactertype=34, m_iprioritymodel=5, _iweapontype=1, m_ipriorityweaponmodel=1,
    )  # fmt: skip
    # a group with a return point and an explicit zone
    lvl += _node(
        GRP2, "CharacterGroup(Folder)", "boss", "host", 2,
        _ereturntohometurfpoint=RP, m_ezonetrigger=ZONE, m_vreturnposition=[0.0, 0.0, 0.0],
    )  # fmt: skip
    lvl += _node(RP, "PivotNode", "home", GRP2, 0, localPos=[10.0, 1.0, -4.0], localOrient=ID)
    lvl += _root(
        R3, "lady", GRP2, 1, [5.0, 0.0, 5.0],
        _icharactertype=35, m_iprioritymodel=3, _iweapontype=0xFFFFFFFF, m_istateofmind=1,
    )  # fmt: skip
    # a group without members keeps its stored vector
    lvl += _node(
        GRP3, "CharacterGroup(Folder)", "empty", "host", 3, m_vreturnposition=[7.0, 8.0, 9.0]
    )
    lvl += _root(R4, "hero", "host", 4, [0.0, 0.0, 0.0], _icharactertype=0, _iweapontype=0)
    lvl += _root(R5, "nodef", "host", 5, [0.0, 0.0, 0.0], _icharactertype=99)

    lvl += _node(
        SET, "TriggerActionCharacter(Node)", "wake", "host", 6,
        m_iactiontype=1, m_itargettype=1, m_etarget1=GRP, m_iinteger1=1,
    )  # fmt: skip
    # action type 1 of the force-move class is FORCE_MOVE, not SET_AI_STATE
    lvl += _node(
        FM, "TriggerActionCharacterForceMove(Node)", "move", "host", 7,
        m_iactiontype=1, m_etarget1=GRP,
    )  # fmt: skip
    lvl += _node(
        TRIG, "TriggerActionGeneral(Node)", "harder", "host", 8,
        m_iactiontype=8, m_etarget1=("single", [GEH, P2]),
    )  # fmt: skip
    lvl += _node(
        TRIG2, "TriggerActionGeneral(Node)", "other", "host", 9, m_iactiontype=8, m_etarget1=RP
    )
    lvl += _node(
        CUBE1, "CubeMapNode", "", "host", 10, localPos=[1.0, 2.0, 3.0], localOrient=ID,
        texture="/Levels/T/cubemaps/hall_cubemap.bmp", textureSize=6,
    )  # fmt: skip
    lvl += _node(
        CUBE2, "CubeMapNode", "off", "host", 11, localPos=[4.0, 5.0, 6.0], localOrient=ID,
        texture="/Levels/T/cubemaps/roof_cubemap.bmp", textureSize=5, enabled=False,
    )  # fmt: skip
    lvl += _node(
        MOVACT, "TriggerActionMovie(Node)", "play", "host", 12, m_emovie=("single", [GEH, MOV1])
    )
    # list order differs from tree order; entry 2 is null (tag 1)
    lvl += _node(
        AIW, "AIWorld(AIWorldNode)", "", "host", 13, aiStaticPathObjectNodes=[PO2, None, PO1]
    )
    lvl += _path_object(PO1, "door1", 14, [0.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    lvl += _path_object(PO2, "door2", 15, [10.0, 0.0, 0.0], [10.0, 0.0, 1.0])
    lvl += _path_object(PO3, "door3", 16, [20.0, 0.0, 0.0], [20.0, 0.0, 1.0])
    _write(base / "Levels" / "T" / "Lvl.fragment", _fragment(lvl, name="Lvl_Main", singleton=True))

    sc = str(base / "Levels" / "T" / "Test.scene")
    return lm.build_level(sc, "Lvl", "%08x" % LVL, None)


def _char(level, name):
    return next(c for c in level["characters"] if c["name"] == name)


# ---------------------------------------------------------------- the picker


def test_pick_model_priority_zero_gives_every_member():
    ms = [{"index": i, "priority_model": p} for i, p in enumerate((0, 2, 2))]
    r = lm.pick_model(ms, 0)
    assert r == {
        "status": "candidates",
        "members": [0, 1, 2],
        "requested_priority": 0,
        "priority_matched": False,
        "rule": "least_used_first",
    }


def test_pick_model_takes_the_last_member_with_the_requested_priority():
    ms = [{"index": i, "priority_model": p} for i, p in enumerate((0, 2, 2, 1))]
    r = lm.pick_model(ms, 2)  # the loop at 0x66ca15 has no break
    assert (r["status"], r["members"], r["priority_matched"]) == ("fixed", [2], True)
    assert r["rule"] == "priority_last_match"
    assert lm.pick_model(ms, 1)["members"] == [3]


def test_pick_model_unmatched_priority_falls_back_to_least_used():
    ms = [{"index": i, "priority_model": p} for i, p in enumerate((0, 0, 0))]
    r = lm.pick_model(ms, 1)
    assert (r["status"], r["members"]) == ("candidates", [0, 1, 2])
    assert r["requested_priority"] == 1 and r["priority_matched"] is False
    # a member's priority 0 can never be requested: request 0 means "no request"
    assert lm.pick_model(ms, 0)["priority_matched"] is False


def test_pick_model_single_member_and_empty_collection():
    one = [{"index": 0, "priority_model": 0}]
    assert lm.pick_model(one, 0)["status"] == "fixed"
    r = lm.pick_model(one, 7)
    assert (r["status"], r["members"], r["priority_matched"], r["rule"]) == (
        "fixed",
        [0],
        False,
        "single_member",
    )
    assert lm.pick_model([], 3) == {
        "status": "none",
        "members": [],
        "requested_priority": 3,
        "priority_matched": False,
        "rule": None,
    }
    assert lm.pick_model(one, 0xFFFFFFFF)["requested_priority"] == -1  # stored unsigned


# ---------------------------------------------------------------- definitions


def test_definition_members_are_in_sibling_order_and_keep_unnamed_ones(level):
    ex = level["character_defs"]["34"]["export"]
    assert [(m["index"], m["name"], m["sibling_order"]) for m in ex["members"]] == [
        (0, "A", 1),
        (1, "B", 2),
        (2, "", 3),
    ]
    assert [m["priority_model"] for m in ex["members"]] == [0, 2, 2]
    assert [m["head_model_type"] for m in ex["members"]] == [19, 20, 21]
    assert ex["variants"] == ["A", "B"]  # the named ones, as before
    assert ex["collection_uid"].endswith(":%08x" % COLL_G)
    assert ex["head_collection_uid"].endswith(":%08x" % HEADS)
    assert "0x66ca15" in ex["rule"] and "not established" not in ex["rule"]
    lady = level["character_defs"]["35"]["export"]
    assert lady["variants"] == [] and len(lady["members"]) == 1
    assert lady["members"][0]["name"] == ""


def test_definition_weapon_collections(level):
    w = level["character_defs"]["34"]["export"]["weapons"]
    assert w["bash_2h"] is None
    assert w["bash_1h"]["collection_uid"].endswith(":%08x" % W1)
    assert w["bash_1h"]["name"] == "Weapons_1H"
    assert [(m["index"], m["priority_model"], m["models"]) for m in w["bash_1h"]["members"]] == [
        (0, 1, ["/art/w/bat.model"]),
        (1, 2, ["/art/w/knife.model"]),
    ]
    hero = level["character_defs"]["0"]["export"]
    assert hero["collection_uid"] is None and hero["members"] == []
    assert hero["weapons"] == {"bash_1h": None, "bash_2h": None}


# ---------------------------------------------------------------- placements


def test_placement_variant(level):
    v = _char(level, "r0")["variant"]
    assert (v["status"], v["members"], v["rule"]) == ("candidates", [0, 1, 2], "least_used_first")
    v = _char(level, "r1")["variant"]  # asks for 2: members B and C have it, C is last
    assert (v["status"], v["members"], v["requested_priority"]) == ("fixed", [2], 2)
    assert v["priority_matched"] is True
    v = _char(level, "r2")["variant"]  # asks for 5: nobody has it
    assert (v["status"], v["members"], v["priority_matched"]) == ("candidates", [0, 1, 2], False)
    assert v["requested_priority"] == 5
    v = _char(level, "lady")["variant"]  # one unnamed member
    assert (v["status"], v["members"], v["rule"]) == ("fixed", [0], "single_member")
    assert v["requested_priority"] == 3 and v["priority_matched"] is False
    v = _char(level, "hero")["variant"]  # no collection: the level's scene control names it
    assert (v["status"], v["members"], v["rule"]) == ("fixed_scene_model", [], "scene_model")
    assert _char(level, "nodef")["variant"]["status"] == "unknown"


def test_placement_weapon(level):
    w = _char(level, "r0")["weapon"]  # 1H, asks for 2
    assert (w["status"], w["members"], w["collection"]) == ("fixed", [1], "bash_1h")
    assert w["collection_uid"].endswith(":%08x" % W1) and w["priority_matched"] is True
    w = _char(level, "r1")["weapon"]  # 1H, no request
    assert (w["status"], w["members"], w["rule"]) == ("candidates", [0, 1], "least_used_first")
    w = _char(level, "r2")["weapon"]  # 2H, the definition has no 2H collection
    assert (w["status"], w["collection"], w["collection_uid"]) == ("none", "bash_2h", None)
    assert w["requested_priority"] == 1
    w = _char(level, "lady")["weapon"]  # weapon type -1
    assert (w["status"], w["collection"], w["members"]) == ("none", None, [])
    assert _char(level, "hero")["weapon"]["status"] == "none"  # null collection
    assert _char(level, "nodef")["weapon"]["status"] == "none"


def test_placement_keeps_the_old_keys_and_a_compact_export(level):
    c = _char(level, "r1")
    assert c["priority_model"] == 2 and c["priority_weapon_model"] == 0
    assert c["state_of_mind"] == {"value": 1, "name": "AGGRESSIVE"}
    assert sorted(c["export"]) == ["character", "rule", "variants"]


def test_counts_of_variants_and_weapons(level):
    c = level["counts"]
    assert c["characters"] == 6
    assert c["characters_variant_fixed"] == 3  # r1, lady, hero
    assert c["characters_variant_candidates"] == 2  # r0, r2
    assert (c["weapons_fixed"], c["weapons_candidates"], c["weapons_none"]) == (1, 1, 4)
    assert "variants" in level["evidence"] and "0x66ca15" in level["evidence"]["variants"]


# ---------------------------------------------------------------- AI start


def test_ai_start_state_of_mind_and_set_ai_state_links(level):
    a = _char(level, "r0")["ai_start"]
    assert a["state_of_mind"] == "PASSIVE"
    assert [(s["name"], s["to"], s["enabled"]) for s in a["set_ai_state"]] == [
        ("wake", {"value": 1, "name": "AGGRESSIVE"}, True)
    ]
    assert a["set_ai_state"][0]["uid"].endswith(":%08x" % SET)
    assert _char(level, "r1")["ai_start"]["state_of_mind"] == "AGGRESSIVE"
    deep = _char(level, "r2")["ai_start"]  # below a folder of the group, no value stored
    assert deep["state_of_mind"] == "unset" and len(deep["set_ai_state"]) == 1
    assert _char(level, "lady")["ai_start"]["set_ai_state"] == []
    c = level["counts"]
    assert (c["characters_passive"], c["characters_aggressive"]) == (1, 2)
    assert c["set_ai_state_actions"] == 1
    assert "0x726214" in level["evidence"]["ai_start"]


def test_trigger_class_is_matched_exactly_not_by_prefix(level):
    nodes = {n["name"]: n for n in level["graph"]["nodes"]}
    assert nodes["wake"]["label"].startswith("SET_AI_STATE ")
    assert nodes["wake"]["names"]["m_iactiontype"] == "SET_AI_STATE"
    assert nodes["move"]["class"] == "TriggerActionCharacterForceMove"
    assert nodes["move"]["names"]["m_iactiontype"] == "FORCE_MOVE"
    assert nodes["move"]["label"].startswith("FORCE_MOVE ")
    assert level["counts"]["set_ai_state_actions"] == 1  # the force move is not counted


# ---------------------------------------------------------------- presets, groups


def test_combat_presets(level):
    cp = level["combat_presets"]
    assert cp["start"]["class"] == "CombatOrchestrator"
    assert {k: cp["start"][k] for k in cp["start"] if k not in ("uid", "class", "name")} == {
        "engagement_dist": 8.0,
        "running_characters_clamp": 5,
        "attack_cooldown": 2.0,
        "max_attacks": 3,
        "attack_frequency": 0.25,
        "idle_time": 0.5,
    }
    assert [(p["name"], p["max_attacks"], p["switches"]) for p in cp["presets"]] == [
        ("Level 001", 2, 0),
        ("Level 002", 4, 1),
    ]
    assert cp["presets"][0]["on_initialize"] is False
    (s,) = cp["switches"]  # the TRIG on a plain pivot is not a preset switch
    assert s["trigger"]["name"] == "harder" and s["preset"]["name"] == "Level 002"
    assert (s["attack_cooldown"], s["max_attacks"], s["engagement_dist"]) == (3.0, 4, 12.0)
    assert (s["attack_frequency"], s["idle_time"], s["enabled"]) == (0.5, 1.5, True)
    assert level["counts"]["combat_preset_switches"] == 1


def test_group_zone_trigger_and_return_position(level):
    g = {x["name"]: x for x in level["groups"]}
    a = g["guards"]
    assert a["zone"] is None  # the reference property, as before
    assert a["zone_trigger"]["name"] == "zone"
    assert a["zone_trigger"]["source"] == "first_child_physics_type_2"
    assert len(a["members"]) == 3  # r2 sits below a folder of the group
    assert a["return_position"] == [1.0, 2.5, 3.0]  # first member, +0.5 in y
    assert a["return_position_source"] == "first_member"
    assert a["return_position_stored"] == [9.0, 9.0, 9.0]
    b = g["boss"]
    assert b["zone"]["name"] == "zone" and b["zone_trigger"]["source"] == "m_ezonetrigger"
    assert b["return_position"] == [10.0, 1.5, -4.0]  # the return point, +0.5 in y
    assert b["return_position_source"] == "return_point"
    e = g["empty"]  # 0x668a99 returns before it writes the vector
    assert e["zone_trigger"] is None and e["members"] == []
    assert e["return_position"] == [7.0, 8.0, 9.0] and e["return_position_source"] == "stored"
    assert level["counts"]["groups"] == 3 and level["counts"]["groups_with_zone_trigger"] == 2


# ---------------------------------------------------------------- cube maps, movies


def test_cube_maps(level):
    a, b = level["cube_maps"]
    assert a["class"] is None or a["class"] == "CubeMapNode"
    assert a["texture"] == "/Levels/T/cubemaps/hall_cubemap.bmp" and a["texture_size"] == 6
    assert a["world"]["pos"] == [1.0, 2.0, 3.0] and "gltf" in a
    assert (a["enabled"], a["enabled_effective"]) == (True, True)
    assert (b["name"], b["enabled"], b["enabled_effective"]) == ("off", False, False)
    assert level["counts"]["cube_maps"] == 2
    assert "0x4d1299" in level["evidence"]["cube_maps"]


def test_movies_name_the_subtitle_table_and_the_next_movie(level):
    m = level["movies"]
    cut = m["scope"]["m_ecutscenemovie"]
    assert cut["movie"] == "/Art/cutscenes/Cut.bik" and cut["localized"] is False
    assert cut["subtitle_table"] == "/Localize/Cut_uk.txt"
    assert cut["continue_link"]["name"] == "Credits"
    assert cut["continue_link"]["movie"] == "/Art/cutscenes/Credits.bik"
    credits = m["scope"]["m_ecreditsmovie"]
    assert credits["subtitle_table"] is None and credits["continue_link"] is None
    (act,) = m["actions"]
    assert act["movie"]["subtitle_table"] == "/Localize/Cut_uk.txt"


# ---------------------------------------------------------------- path objects by id


def _table(*rows):
    """rows: (index, id, x) -> nav path objects with one edge along z at x."""
    return [
        {
            "index": i,
            "id": pid,
            "edges": [{"cell": 1000, "edge": i, "from": [x, 0.0, 0.0], "to": [x, 0.0, 1.0]}],
        }
        for i, pid, x in rows
    ]


def test_ai_world_list_gives_each_path_object_its_id(level):
    aw = level["level"]["ai_world"]
    assert aw["uid"].endswith(":%08x" % AIW) and aw["nodes"] == 1
    assert aw["list_length"] == 3 and aw["null_entries"] == [2]
    assert aw["unresolved"] == [] and aw["not_path_objects"] == [] and aw["repeated"] == []
    po = {p["name"]: p["ai_world_index"] for p in level["path_objects"]}
    assert po == {"door1": 3, "door2": 1, "door3": None}  # list order, not tree order
    assert "aiStaticPathObjectNodes" in level["evidence"]["path_objects"]
    assert "not established" not in level["evidence"]["path_objects"]


def test_link_nav_joins_by_id_and_a_null_entry_by_position(level):
    lv = {"path_objects": [dict(p) for p in level["path_objects"]], "counts": {}}
    # entry 1 lies at door2, entry 2 (null in the list) at door3, entry 3 at door1
    s = lm.link_nav(lv, _table((1, 1, 10.0), (2, 2, 20.0), (3, 3, 0.0)), source="t.hpd")
    nav = {p["name"]: p["nav"] for p in lv["path_objects"]}
    assert (nav["door2"]["index"], nav["door2"]["method"]) == (1, "id")
    assert (nav["door1"]["index"], nav["door1"]["method"]) == (3, "id")
    assert (nav["door3"]["index"], nav["door3"]["method"]) == (2, "position")
    assert nav["door1"]["distance_m"] == 0.0 and nav["door1"]["edges"] == [[1000, 3]]
    assert (s["linked"], s["linked_by_id"], s["linked_by_position_only"]) == (3, 2, 1)
    assert s["id_position_disagree"] == [] and s["unlinked"] == []
    assert s["source"] == "t.hpd" and "0x4837d5" in s["rule"]
    assert lv["counts"]["path_objects_linked"] == 3


def test_link_nav_keeps_an_id_join_that_position_contradicts(level):
    lv = {"path_objects": [dict(p) for p in level["path_objects"]], "counts": {}}
    # id 1 is door2 (x = 10) but the entry's edge lies at door1 (x = 0): the engine
    # binds by id, so the join stays and the pair is reported
    s = lm.link_nav(lv, _table((1, 1, 0.0)))
    nav = {p["name"]: p["nav"] for p in lv["path_objects"]}
    assert nav["door2"]["method"] == "id" and nav["door2"]["distance_m"] == 10.0
    assert nav["door1"] is None
    (d,) = s["id_position_disagree"]
    assert (d["index"], d["id"], d["distance_m"]) == (1, 1, 10.0)
    assert d["node"] == next(p["uid"] for p in lv["path_objects"] if p["name"] == "door2")
    assert s["linked_by_id"] == 1 and s["max_distance_m"] == 10.0


def test_link_nav_without_ids_is_the_position_join(level):
    nodes = [dict(p, ai_world_index=None) for p in level["path_objects"]]
    lv = {"path_objects": nodes, "counts": {}}
    s = lm.link_nav(lv, _table((1, 1, 10.0), (2, 2, 20.0), (3, 3, 0.3), (4, 4, 55.0)))
    assert [p["nav"]["method"] for p in nodes] == ["position"] * 3
    assert (s["linked_by_id"], s["linked_by_position_only"], s["unlinked"]) == (0, 3, [4])
    assert s["max_distance_m"] == 0.3
    ends = [{"pos": [0.0, 0.0, 0.0]}, {"pos": [0.0, 0.0, 1.0]}]
    old = {"path_objects": [{"uid": "0:1", "vertices": ends}]}
    lm.link_nav(old, _table((1, 9, 0.0)))  # a level dict written before ai_world_index
    assert old["path_objects"][0]["nav"]["method"] == "position"


def test_a_level_without_an_ai_world(tmp_path):
    base = tmp_path / "extracted"
    scene = _node(SCENE, "SceneNode", "", None)
    scene += _node(LVL, "SceneScope(LoadBlock)", "Bare", SCENE, 1, assetName="/L/Bare.fragment")
    _write(base / "L" / "Bare.scene", _fragment(scene))
    _write(base / "L" / "Bare.fragment", _fragment(_node(0x30, "Folder", "x", "host")))
    j = lm.build_level(str(base / "L" / "Bare.scene"), "Bare", "%08x" % LVL, None)
    assert j["level"]["ai_world"] is None and j["path_objects"] == []
    assert j["combat_presets"] == {"start": None, "presets": [], "switches": []}
    assert j["cube_maps"] == [] and j["groups"] == []
    assert j["counts"]["weapons_none"] == 0 and j["counts"]["characters_variant_fixed"] == 0


def test_order_note_says_what_is_read_and_what_is_inferred(level):
    note = level["conventions"]["order"]
    assert "0x48f556" in note and "inferred" in note and "not established" not in note


# ---------------------------------------------------------------- nav stamp


def test_nav_summary_generated_is_the_stamp_all_cells_share():
    import test_nav_data as tn

    hpd = nd.parse_hpd(tn.demo_hpd())
    doc = nd.build_document(hpd, None, "Demo", {})
    assert [c["generated"] for c in doc["cells"]] == ["2009-01-27 11:48:38"] * 2
    assert doc["summary"]["generated"] == "2009-01-27 11:48:38"
    hpd["cells"][1]["time"] = 12000000  # one cell from another run
    assert nd.build_document(hpd, None, "Demo", {})["summary"]["generated"] is None
    for c in hpd["cells"]:  # the loader's filler for a 1.0 file (0x90b310)
        c["date"] = c["time"] = 0xBAFFE000
    doc = nd.build_document(hpd, None, "Demo", {})
    assert doc["summary"]["generated"] is None
    assert [c["generated"] for c in doc["cells"]] == [None, None]
    assert "0x90b660" in nd.EVIDENCE["cell.date / time"]
    assert "aiStaticPathObjectNodes" in nd.EVIDENCE["path_object.id"]
