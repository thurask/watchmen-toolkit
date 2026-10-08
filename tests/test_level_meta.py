"""Runtime core in the toolkit: fragment header, engine reference resolution,
`.scene` files, the level export and the `.kpw` save reader.

Header          Fragment::LoadHeader 0x54306d
References      EntityType reader 0x500b81 / 0x505d84, scope search 0x53a5ff,
                singleton registry 0x4a1d63 / 0x49aadf
Instancing      FragmentNode::SetFragmentAssetByName 0x498db7 (case-folding asset
                lookup 0x54ba59)
Trigger graph   TriggerConditionBase 0x8632fa, TriggerActionBase 0x84afa9,
                TriggerActionDelay 0x852ecd, TriggerActionCheckpoint 0x85d2de
Synthetic binary fixtures only: every file below is built in the test."""

import json, os, struct, sys
import pathlib

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import anim_state_machine as asm
import kapow_fragment as kf
import kapow_json as kj
import kapow_props as kp
import level_meta as lm


def _u(*v):
    return struct.pack("<%dI" % len(v), *v)


def _f(*v):
    return struct.pack("<%df" % len(v), *v)


def _str(s):
    b = s.encode("latin1") + b"\0"
    b += b"\0" * (-len(b) % 4)
    return _u(len(b) // 4) + b


def _ent(v):
    """None -> null, "host" -> tag 2, int -> tag 3, ("up", a, ids) -> tag 4,
    ("single", ids) -> tag 5."""
    if v is None:
        return _u(1)
    if v == "host":
        return _u(2)
    if isinstance(v, int):
        return _u(3, v)
    if v[0] == "up":
        return _u(4, v[1], len(v[2]), *v[2])
    return _u(5, len(v[1]), *v[1])


def _val(v):
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
    if isinstance(v, list):
        return _f(*v)
    raise TypeError(v)


ENTITY = ("logicalParent", "m_etarget1", "_eauxaction", "m_etriggerentity", "_ealldeadaction")


def _node(nid, typ, name, parent, order=0, **props):
    """One type record and one instance record.  Entity properties take the _ent
    forms, everything else is encoded by its Python type."""
    b = _u(0xFFFFFFFF, nid) + _str(typ) + _u(0xFFFFFFFE, nid)
    b += _u(kp.name_hash("name")) + _str(name)
    b += _u(kp.name_hash("logicalParent")) + _ent(parent)
    b += _u(kp.name_hash("siblingOrder")) + _u(order)
    for k, v in props.items():
        b += _u(kp.name_hash(k)) + (_ent(v) if k in ENTITY else _val(v))
    return b


def _fragment(payload, name="", singleton=False, reapplyable=False, version=4):
    nm = name.encode("latin1") + b"\0"
    head = _u(version) + bytes([int(singleton), 0]) + _u(len(nm)) + nm
    head += bytes([int(reapplyable), 0]) + _u(1)
    return head + _u(len(payload)) + payload


def _write(path, data):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as fh:
        fh.write(data)


def _h(name):
    return kp.name_hash(name)


Q90 = [0.0, 0.70710678, 0.0, 0.70710678]  # 90 degrees about +Y as stored
ID = [0.0, 0.0, 0.0, 1.0]

# node ids
SCENE, SCENES, LVL, OTHER, GE = 0x10, 0x11, 0x12, 0x13, 0x14
GRP, ROOT, BOX, CON, DELAY, ACT0, ACT1, ACT2, CP, TELE, TOG, SUB, AUX = range(0x20, 0x2D)
S_ACT, S_UP, S_MODEL, DB, TARGET = 0x40, 0x41, 0x42, 0x50, 0x51


@pytest.fixture
def extract(tmp_path):
    """extracted/Levels/T/Test.scene with two load blocks and a game-essentials
    scope; the level `Lvl` nests Sub.fragment and refers into GE.fragment."""
    base = tmp_path / "extracted"
    scene = _node(SCENE, "SceneNode", "", None)
    scene += _node(SCENES, "Folder", "Scenes", SCENE)
    scene += _node(
        LVL,
        "SceneScope(LoadBlock)",
        "Lvl",
        SCENES,
        1,
        localPos=[10.0, 0.0, 0.0],
        localOrient=Q90,
        assetName="/levels/t/lvl.fragment",  # the file is Levels/T/Lvl.fragment
        m_isceneid=9,
    )
    scene += _node(
        OTHER, "SceneScope(LoadBlock)", "Other", SCENES, 2, assetName="/Levels/T/Other.fragment"
    )
    scene += _node(
        GE, "SceneScope(FragmentNode)", "GameEssentials", SCENE, 5, assetName="/TNT/GE.fragment"
    )
    _write(base / "Levels" / "T" / "Test.scene", _fragment(scene))

    ge = _node(DB, "Folder", "Db", "host") + _node(TARGET, "PivotNode", "Level 005", DB)
    _write(base / "TNT" / "GE.fragment", _fragment(ge, singleton=True))  # named by its file

    lvl = _node(GRP, "CharacterGroup(Folder)", "guards", "host", 0, _ealldeadaction=TOG)
    lvl += _node(
        ROOT,
        "CharacterRoot(PivotNode)",
        "{gimp}",
        GRP,
        0,
        localPos=[0.0, 0.0, 5.0],
        localOrient=ID,
        _icharactertype=34,
        m_istateofmind=1,
        _tstartactivated=False,
    )
    lvl += _node(
        BOX,
        "CollisionBoxNode",
        "Hall_TRIGGER",
        "host",
        1,
        localPos=[1.0, 2.0, 3.0],
        localOrient=ID,
        width=18.0,
        height=4.0,
        depth=6.0,
    )
    lvl += _node(CON, "TriggerConditionCollision(Node)", "con", BOX, 0, m_itrueon=1, m_iactivator=1)
    lvl += _node(
        DELAY, "TriggerActionDelay(Node)", "d", CON, 0, m_ndelaynumber0=0.5, m_ndelaynumber1=1.25
    )
    lvl += _node(
        ACT0, "TriggerActionCharacter(Node)", "a0", DELAY, 0, m_iactiontype=5, m_etarget1=GRP
    )
    lvl += _node(
        ACT1,
        "TriggerActionGeneral(Node)",
        "a1",
        DELAY,
        1,
        m_iactiontype=8,
        m_etarget1=("single", [_h("GE"), TARGET]),
        _eauxaction=AUX,
    )
    lvl += _node(
        ACT2,
        "TriggerActionGeneral(Node)",
        "a2",
        DELAY,
        2,
        m_iactiontype=0,
        m_etarget1=("single", [_h("NotLoaded"), 0x77]),
    )
    lvl += _node(CP, "TriggerActionCheckpoint(Node)", "CheckPoint02", CON, 1, _icheckpointid=910)
    lvl += _node(
        TELE,
        "TriggerActionCharacter(PivotNode)",
        "tele",
        CP,
        0,
        localPos=[0.0, 0.0, 4.0],
        localOrient=ID,
        m_iactiontype=0,
        m_itargettype=2,
    )
    lvl += _node(TOG, "TriggerConditionToggle(Node)", "tog", "host", 2)
    lvl += _node(AUX, "TriggerActionBase(Node)", "shared", "host", 3)
    lvl += _node(
        SUB,
        "FragmentNode",
        "sub",
        "host",
        4,
        localPos=[0.0, 0.0, 2.0],
        localOrient=ID,
        assetName="/Levels/T/Sub.fragment",
    )
    # a node with the id of Sub's model, placed in the level itself
    lvl += _node(S_MODEL, "PivotNode", "level pivot", "host", 5)
    _write(base / "Levels" / "T" / "Lvl.fragment", _fragment(lvl, name="Lvl_Main", singleton=True))

    sub = _node(
        S_MODEL,
        "Model",
        "crate",
        "host",
        0,
        localPos=[1.0, 0.0, 0.0],
        localOrient=ID,
        modelNames=["/art/props/crate.model"],
    )
    # tag 3: the model of this instance; tag 4 a = 2: one host further up, the level
    sub += _node(S_ACT, "TriggerActionGeneral(Node)", "own", "host", 1, m_etarget1=S_MODEL)
    sub += _node(
        S_UP, "TriggerActionGeneral(Node)", "up", "host", 2, m_etarget1=("up", 2, [S_MODEL])
    )
    _write(base / "Levels" / "T" / "Sub.fragment", _fragment(sub, reapplyable=True))

    other = _node(0x60, "CharacterRoot(PivotNode)", "elsewhere", "host", 0, _icharactertype=33)
    _write(base / "Levels" / "T" / "Other.fragment", _fragment(other))
    return tmp_path


def _scene(extract):
    return str(extract / "extracted" / "Levels" / "T" / "Test.scene")


def _by(nodes, nid):
    return [n for n in nodes if n.id == "%08x" % nid]


# ---------------------------------------------------------------- fragment layer


def test_header_fields_are_parsed_and_exported():
    data = _fragment(_node(1, "Folder", "f", "host"), name="Bordello_Enemies", singleton=True)
    h = kf.parse_header(data)
    assert h["version"] == 4 and h["singleton"] is True and h["name"] == "Bordello_Enemies"
    assert h["reapplyable"] is False and h["typed"] is False and h["chunks"] == 1
    assert h["size"] == 17 + len("Bordello_Enemies")
    j = kj.to_json("x.fragment", data)
    assert j["lossless"] and j["header"]["name"] == "Bordello_Enemies"
    assert j["header"]["singleton"] is True and "size" not in j["header"]
    r = kj.to_json("y.fragment", _fragment(_node(1, "Folder", "f", "host"), reapplyable=True))
    assert r["header"]["reapplyable"] is True and r["header"]["name"] == ""


def test_parse_header_rejects_what_is_not_a_header():
    assert kf.parse_header(b"\x00" * 40) is None  # version 0
    assert kf.parse_header(_u(4) + bytes([7, 0]) + _u(1) + b"\0" + bytes(6)) is None  # flag 7
    assert kf.parse_header(b"\x04") is None


def test_leading_native_type_record_is_read_not_skipped():
    """A scene opens with the bare native record "SceneNode": the old scan started
    at the first "Class(Native)" record and lost every node in front of it."""
    data = _fragment(
        _node(SCENE, "SceneNode", "", None) + _node(LVL, "SceneScope(LoadBlock)", "L", SCENE)
    )
    j = kj.to_json("t.scene", data)
    types = {n["id"]: n["type"] for n in j["nodes_full"]}
    assert types["%08x" % SCENE] == "SceneNode"
    assert types["%08x" % LVL] == "SceneScope(LoadBlock)"
    assert j["lossless"]


def test_scene_files_are_fragments(extract):
    assert kj.to_json("a/b.scene", pathlib.Path(_scene(extract)).read_bytes()) is not None
    j = kj.load_fragment(_scene(extract))
    assert any(n["type"] == "SceneScope(LoadBlock)" for n in j["nodes_full"])


def test_default_hosts_keep_the_animation_behaviour(extract):
    """load_tree without `hosts` splices under state groups only, as before."""
    assert asm.HOSTS_GROUPS == "groups"
    roots = asm.load_tree(_scene(extract))
    assert not _by(asm.walk(roots), GRP)
    assert all(n.inst is not None for n in asm.walk(roots))


def test_all_hosts_splice_case_insensitively_and_filter(extract):
    nodes = asm.walk(asm.load_tree(_scene(extract), hosts=asm.HOSTS_ALL))
    assert _by(nodes, GRP) and _by(nodes, 0x60) and _by(nodes, TARGET)
    (root,) = _by(nodes, ROOT)
    assert root.inst.header["name"] == "Lvl_Main"
    assert root.inst.asset == "/levels/t/lvl.fragment"  # found as Levels/T/Lvl.fragment
    only = asm.load_tree(_scene(extract), hosts=lambda n, asset: n.name != "Other")
    assert not _by(asm.walk(only), 0x60) and _by(asm.walk(only), GRP)


def test_singleton_hash_is_the_header_name_or_the_file_stem(extract):
    nodes = asm.walk(asm.load_tree(_scene(extract), hosts="all"))
    ctx = nodes[0].inst.ctx
    assert set(ctx["singletons"]) == {"%08x" % _h("GE"), "%08x" % _h("Lvl_Main")}
    assert _by(nodes, S_ACT)[0].inst.singleton_hash() is None


def test_references_resolve_the_engine_way(extract):
    roots = asm.load_tree(_scene(extract), hosts="all")
    nodes = asm.walk(roots)
    index = asm.node_index(roots, nodes)

    def target(nid):
        (n,) = _by(nodes, nid)
        return asm.resolve_ref(n, n.p("m_etarget1"), index)

    # tag 5: singleton by name hash, then a path below its host
    assert target(ACT1).name == "Level 005"
    assert target(ACT2) is None  # the singleton is not loaded
    # tag 3: the node of the SAME fragment instance although the level has the id too
    assert target(S_ACT).name == "crate"
    # tag 4, a = 2: one host above the nested fragment; the search does not enter
    # nested fragments, so it is the level's node, not the nearer `crate`
    assert target(S_UP).name == "level pivot"
    # tag 2 is the host; a single-id tag-5 path names no node
    (grp,) = _by(nodes, GRP)
    assert asm.resolve_ref(grp, {"etag": 2}, index).name == "Lvl"
    assert asm.resolve_ref(grp, {"xref": ["%08x" % _h("GE")]}, index) is None
    assert (
        asm.resolve_ref(grp, {"xref4": ["%08x" % SCENES, "%08x" % OTHER], "a": 0}, index).name
        == "Other"
    )


def test_find_in_scope_is_depth_first_and_stops_at_hosts(extract):
    roots = asm.load_tree(_scene(extract), hosts="all")
    (lvl,) = _by(asm.walk(roots), LVL)
    assert asm.find_in_scope(lvl.children, "%08x" % S_MODEL).name == "level pivot"
    assert asm.find_in_scope(lvl.children, "%08x" % S_ACT) is None  # inside `sub`
    assert asm.find_in_scope(lvl.children, "%08x" % SUB).name == "sub"
    assert asm.is_fragment_host(lvl) and not asm.is_fragment_host(_by(asm.walk(roots), BOX)[0])


# ---------------------------------------------------------------- level export


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_transform_helpers():
    # the engine rotates with conj(q) v q: +Z under the stored 90-degree yaw is -X
    assert lm.q_rot(Q90, [0.0, 0.0, 1.0]) == pytest.approx([-1.0, 0.0, 0.0], abs=1e-6)
    pos, quat = lm.compose(([10.0, 0.0, 0.0], Q90), [0.0, 0.0, 5.0], ID)
    assert pos == pytest.approx([5.0, 0.0, 0.0], abs=1e-5) and quat == pytest.approx(Q90)
    g = lm.gltf_trs([1.0, 2.0, 3.0], Q90)
    assert g["translation"] == [1.0, 2.0, 3.0]
    assert g["rotation"] == pytest.approx([0.0, -0.707107, 0.0, 0.707107], abs=1e-6)
    assert lm.yaw_deg(Q90) == pytest.approx(-90.0)
    assert lm.enum_name("TRIGGER_ACTION_GENERAL", 18) == "USE_TRIGGER_UNFREEZE"
    assert lm.enum_name("SCENE_ID", 0xFFFFFFFF) == "NONE"


@pytest.fixture
def level(extract):
    (found,) = [x for x in lm.levels(str(extract)) if x[1] == "Lvl"]
    return lm.build_level(found[0], found[1], found[2], str(extract))


def test_levels_are_the_load_blocks(extract):
    assert [(x[1], x[3]) for x in lm.levels(str(extract))] == [
        ("Lvl", "/levels/t/lvl.fragment"),
        ("Other", "/Levels/T/Other.fragment"),
    ]


def test_level_header_and_fragment_tree(level):
    assert level["format"] == "watchmen-level-meta/1"
    assert level["level"]["scene_id"] == {"value": 9, "name": "BORDELLO"}
    assert level["files"]["blocks"] == ["lvl.block_h_z", "lvl.block_s_z"]
    assert set(level["evidence"]) >= {"graph", "world", "references", "characters"}
    frags = {f["asset"]: f for f in level["fragments"]}
    assert set(frags) == {None, "/levels/t/lvl.fragment", "/Levels/T/Sub.fragment"}  # None: scene
    sub = frags["/Levels/T/Sub.fragment"]
    assert sub["header"]["reapplyable"] is True and sub["host"]["name"] == "sub"
    assert sub["parent"] == frags["/levels/t/lvl.fragment"]["index"]
    # host of Sub: level (10, 0, 0) yaw 90, local (0, 0, 2) -> (8, 0, 0)
    assert sub["world"]["pos"] == pytest.approx([8.0, 0.0, 0.0], abs=1e-5)
    assert [r["asset"] for r in level["spawn_recipe"]["reapplyable_fragments"]] == [
        "/Levels/T/Sub.fragment"
    ]


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_character_placement(level):
    (c,) = level["characters"]  # the other level's character is not in this one
    assert c["name"] == "{gimp}" and c["group"]["name"] == "guards"
    assert c["character_type"] == {"value": 34, "name": "GIMP"}
    assert c["state_of_mind"]["name"] == "AGGRESSIVE" and c["start_activated"] is False
    assert c["world"]["pos"] == pytest.approx([5.0, 0.0, 0.0], abs=1e-5)
    assert c["gltf"]["translation"] == c["world"]["pos"]
    q = c["world"]["quat"]
    assert c["gltf"]["rotation"] == pytest.approx([-q[0], -q[1], -q[2], q[3]])
    assert c["forward"] == pytest.approx([-1.0, 0.0, 0.0], abs=1e-4)
    (g,) = level["groups"]
    assert g["members"] == [c["uid"]] and g["all_dead"]["name"] == "tog"


def test_models_and_volumes(level):
    (m,) = level["models"]
    assert m["models"] == ["/art/props/crate.model"]
    assert m["world"]["pos"] == pytest.approx([8.0, 0.0, 1.0], abs=1e-5)
    (v,) = level["volumes"]
    assert v["shape"] == "box" and v["size"] == [18.0, 4.0, 6.0]
    assert len(v["conditions"]) == 1 and v["used_by"] == v["conditions"]


def test_graph_edges(level):
    g = level["graph"]
    n = {x["name"]: x for x in g["nodes"]}
    u = {x["uid"]: x["name"] for x in g["nodes"]}
    edges = set((u[e["from"]], e["kind"], u[e["to"]]) for e in g["edges"])
    assert (
        n["con"]["kind"] == "condition" and n["con"]["label"] == "LEAVE by PLAYER in Hall_TRIGGER"
    )
    assert n["con"]["names"] == {"m_itrueon": "LEAVE", "m_iactivator": "PLAYER"}
    assert n["a0"]["label"] == "ACTIVATE guards" and n["a1"]["label"] == "TRIG Level 005"
    assert n["Level 005"]["kind"] == "object" and n["Level 005"]["external"] is True
    assert ("con", "volume", "Hall_TRIGGER") in edges  # default: the parent
    assert ("con", "action", "d") in edges and ("con", "action", "CheckPoint02") in edges
    assert ("a0", "target", "guards") in edges and ("a1", "target", "Level 005") in edges
    assert ("a1", "aux", "shared") in edges and ("guards", "all_dead", "tog") in edges
    assert ("guards", "member", "{gimp}") in edges
    assert ("up", "target", "level pivot") in edges and ("own", "target", "crate") in edges
    child = {u[e["to"]]: e for e in g["edges"] if e["kind"] == "child"}
    assert (child["a0"]["order"], child["a0"]["when"], child["a0"]["delay"]) == (0, "delay", 0.5)
    assert child["a1"]["delay"] == 1.25 and child["a2"]["delay"] == 0.0
    assert child["tele"]["when"] == "restore"
    order = {u[e["to"]]: e["order"] for e in g["edges"] if e["kind"] == "action"}
    assert order == {"d": 0, "CheckPoint02": 1}


def test_checkpoints(level):
    (cp,) = level["checkpoints"]
    assert cp["checkpoint_id"] == 910 and cp["condition"]["label"].startswith("LEAVE by PLAYER")
    assert cp["trigger_volume"]["name"] == "Hall_TRIGGER"
    # box (1, 2, 3) in the level frame -> world (10 - 3, 2, 1); teleport (0, 0, 4) below it
    assert cp["trigger_volume"]["world"]["pos"] == pytest.approx([7.0, 2.0, 1.0], abs=1e-5)
    (t,) = cp["teleports"]
    assert t["who"] == "RORSCHACH" and t["world"]["pos"] == pytest.approx([3.0, 2.0, 1.0], abs=1e-5)
    assert [(r["depth"], r["label"], r["when"]) for r in cp["replay"]] == [
        (0, "TELEPORT RORSCHACH", "restore")
    ]
    assert cp["fired_by"][0]["kind"] == "action"


def test_unresolved_references_are_listed_and_counted(level):
    (un,) = level["unresolved"]
    assert un["name"] == "a2" and un["property"] == "m_etarget1"
    assert un["reference"] == {"xref": ["%08x" % _h("NotLoaded"), "00000077"]}
    c = level["counts"]
    assert c["references_unresolved"] == 1 and c["characters"] == 1 and c["checkpoints"] == 1
    assert c["conditions"] == 2 and c["actions"] == 9 and c["models"] == 1


def test_levelmeta_command_writes_one_file_per_level(extract, tmp_path, capsys):
    import watchmen

    out = tmp_path / "meta"
    assert watchmen.main(["watchmen", "levelmeta", str(extract), str(out)]) == 0
    assert sorted(os.listdir(str(out))) == ["Lvl.level.json", "Other.level.json"]
    j = json.loads((out / "Other.level.json").read_text())
    assert [c["name"] for c in j["characters"]] == ["elsewhere"]
    assert watchmen.main(["watchmen", "levelmeta", str(tmp_path / "meta"), str(out)]) == 2
    assert "no *.scene" in capsys.readouterr().err


def _named_files(doc, index):
    """[(string, tree, path as written)] of the strings of `doc` that name a file
    of the export; the "stored" / "stored_name" entries are not looked at."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k not in ("stored", "stored_name"):
                    walk(k)
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and index.find(o):
            out.append((o,) + index.find(o))

    walk(doc)
    return out


def test_levelmeta_spells_asset_strings_as_the_files_are_written(extract, tmp_path, monkeypatch):
    """--names canonical (default): every string of a level JSON that names an
    exported file has the letter case of that file; the string the game stores
    stays beside it under "stored"."""
    import canonical_names as cn

    monkeypatch.delenv("WATCHMEN_NAMES", raising=False)
    # the model the level names as /art/props/crate.model, as `extract` wrote it
    mdl = extract / "models" / "art" / "Props"
    mdl.mkdir(parents=True)
    (mdl / "Crate.model.glb").write_bytes(b"glb")
    (mdl / "Crate.model.obj").write_bytes(b"obj")
    stored = {x[1]: lm.build_level(x[0], x[1], x[2], str(extract)) for x in lm.levels(str(extract))}
    index = cn.ExportIndex(str(extract))
    before = _named_files(stored["Lvl"], index)
    assert ("/levels/t/lvl.fragment", "extracted", "Levels/T/Lvl.fragment") in before
    assert ("/art/props/crate.model", "models", "art/Props/Crate.model") in before

    out = tmp_path / "meta"
    lm.write(str(extract), str(out), log=None)
    j = json.loads((out / "Lvl.level.json").read_text())
    after = _named_files(j, index)
    assert len(after) == len(before) > 4
    for text, tree, path in after:  # exact case, every one
        assert text.lstrip("/") == path and os.path.exists(
            str(extract / tree / path) + (".glb" if tree == "models" else "")
        )
    names = j["asset_names"]
    assert names["spelling"] == "export" and "stored" in names["note"]
    assert names["respelled"] == sum(1 for b, a in zip(before, after) if b[0] != a[0]) > 0
    assert j["level"]["asset"] == "/Levels/T/Lvl.fragment"
    assert j["level"]["stored"] == {"asset": "/levels/t/lvl.fragment"}
    (m,) = [r for r in j["models"] if r["models"] == ["/art/Props/Crate.model"]]
    assert m["stored"]["models"] == ["/art/props/crate.model"]
    # nothing but the spelling changed: undo it and the level is what build_level gives
    assert _as_stored(j) == stored["Lvl"]
    # a string that names no file is left as the game stores it
    assert "stored" not in json.dumps(json.loads((out / "Other.level.json").read_text())["level"])

    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    lm.write(str(extract), str(tmp_path / "meta2"), log=None)
    assert json.loads((tmp_path / "meta2" / "Lvl.level.json").read_text()) == json.loads(
        json.dumps(stored["Lvl"])
    )


def _as_stored(doc):
    """A respelled table with every "stored" entry put back and the notes dropped."""
    if isinstance(doc, list):
        return [_as_stored(x) for x in doc]
    if not isinstance(doc, dict):
        return doc
    back = doc.get("stored") if isinstance(doc.get("stored"), dict) else {}
    out = {}
    for k, v in doc.items():
        if k in ("stored", "asset_names"):
            continue
        out[k] = back[k] if k in back and not isinstance(v, dict) else _as_stored(v)
    return json.loads(json.dumps(out))


# ---------------------------------------------------------------- .kpw saves


def _save(title, records):
    t = (title + "\0").encode("utf-16-le")
    body = b""
    for ent, prop, typ, words in records:
        body += _u(ent, kp.name_hash(prop), kp.name_hash(typ), len(words), *words)
    return _u(5) + b"KPWF" + b"\0" + _u(2) + _u(len(title) + 1) + t + _u(len(body)) + body


def test_save_file_records():
    data = _save(
        "Checkpoint Save Data",
        [
            (0x9B677B3B, "m_ilastcheckpoint", "list(integer)", [4, 999, 920, 0, 0]),
            (0x9B677B3B, "m_blevelcompletelist", "list(list(integer))", [2, 2, 7, 8, 0]),
            (0x9B677B3B, "m_ncontrast", "number", [0x3F000000]),
            (0x9B677B3B, "m_tsubtitles", "truth", [1]),
            (0x9B677B3B, "m_ngamma", "vectorlist", [1, 2]),  # a type the reader does not know
        ],
    )
    j = lm.parse_save(data)
    assert j["format"] == "watchmen-save-meta/1" and j["title"] == "Checkpoint Save Data"
    assert j["entities"] == ["9b677b3b"] and j["trailing_bytes"] == 0
    v = {r["property"]: r for r in j["records"]}
    assert v["m_ilastcheckpoint"]["value"] == [999, 920, 0, 0]
    assert v["m_blevelcompletelist"]["value"] == [[7, 8], []]
    assert v["m_ncontrast"]["value"] == 0.5 and v["m_tsubtitles"]["value"] is True
    assert v["m_ngamma"]["raw_words"] == [1, 2] and "value" not in v["m_ngamma"]
    assert j["decoded"]["last_checkpoint"]["NITEOWL"] == 920
    assert j["decoded"]["completed_scenes"]["RORSCHACH"] == [
        {"id": 7, "name": "NIGHTCLUB"},
        {"id": 8, "name": "STREETS_OF_RIOTS"},
    ]
    with pytest.raises(ValueError):
        lm.parse_save(b"\x05\0\0\0NOPE" + bytes(20))


def test_savemeta_command(tmp_path, capsys):
    import watchmen

    src = tmp_path / "PROGRESS.kpw"
    _write(src, _save("User Settings", [(1, "m_tsubtitles", "truth", [0])]))
    assert watchmen.main(["watchmen", "savemeta", str(src)]) == 0
    j = json.loads(pathlib.Path(str(src) + ".json").read_text())
    assert j["title"] == "User Settings" and j["records"][0]["value"] is False
    _write(tmp_path / "bad.kpw", b"not a save")
    assert watchmen.main(["watchmen", "savemeta", str(tmp_path / "bad.kpw")]) == 2
