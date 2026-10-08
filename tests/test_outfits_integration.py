"""Outfits x texture sheets, switchable outfit nodes, and which fragment file is read.

Synthetic fixtures.  Shapes mirror the shipped data (read 2026-10-04): the 18
`Heavy` outfits all list the jacket, but with different sheets of Heavy_Outfit1,
so the jacket is one node per outfit; shoes and hands are the same everywhere and
stay in the main mesh."""

import json
import os
import sys

import numpy as np

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import characters_export as ce
import kapow_json
import parts_rule as pr
import variant_glb as vg

from conftest import parse_glb

MEMBERS = [
    {"index": 1, "models": ["Jacket", "Shoes", "Hair_Side", "Head1"]},
    {"index": 2, "models": ["Jacket", "Shoes", "Afro", "Head1"]},
    {"index": 3, "models": ["Jacket", "Shoes", "Head1"]},
]
UNION = ["Jacket", "Shoes", "Hair_Side", "Afro", "Head1", "Skeleton_Extra"]
SHEETS = {1: {}, 2: {"jacket": {"/art/outfit.bmp": "Outfit3"}}, 3: {}}


def test_models_that_differ_between_outfits_become_one_node_per_outfit():
    common, nodes = pr.outfits(UNION, MEMBERS, SHEETS, skip=["Head1"])
    # same model list AND same sheets in every outfit -> main mesh; a model no
    # outfit lists stays; the head the face rig stands for is left out
    assert common == ["Shoes", "Skeleton_Extra"]
    assert nodes == [
        ("OUTFIT 1 Jacket", 1, "Jacket", True),
        ("OUTFIT 1 Hair_Side", 1, "Hair_Side", True),
        ("OUTFIT 2 Jacket", 2, "Jacket", False),
        ("OUTFIT 2 Afro", 2, "Afro", False),
        ("OUTFIT 3 Jacket", 3, "Jacket", False),
    ]
    # without the sheet difference the jacket is common
    common, nodes = pr.outfits(UNION, MEMBERS, {}, skip=["Head1"])
    assert common == ["Jacket", "Shoes", "Skeleton_Extra"]
    assert [n[0] for n in nodes] == ["OUTFIT 1 Hair_Side", "OUTFIT 2 Afro"]
    # another outfit shown
    assert [n[0] for n in pr.outfits(UNION, MEMBERS, {}, show=2)[1] if n[3]] == ["OUTFIT 2 Afro"]
    # one outfit, or none: nothing is split
    assert pr.outfits(["A", "B"], MEMBERS[:1]) == (["A", "B"], [])
    assert pr.outfits(["A"], []) == (["A"], [])


def test_outfit_record_maps_each_outfit_to_its_nodes_and_sheets():
    common, nodes = pr.outfits(UNION, MEMBERS, SHEETS, skip=["Head1"])
    rec = pr.outfit_record(pr.record(MEMBERS, UNION, [], []), common, nodes, SHEETS)
    assert rec["common_models"] == ["Shoes", "Skeleton_Extra"]
    assert rec["shown_nodes"] == ["OUTFIT 1 Jacket", "OUTFIT 1 Hair_Side"]
    assert [m["nodes"] for m in rec["members"]] == [
        ["OUTFIT 1 Jacket", "OUTFIT 1 Hair_Side"],
        ["OUTFIT 2 Jacket", "OUTFIT 2 Afro"],
        ["OUTFIT 3 Jacket"],
    ]
    assert rec["members"][1]["sheets"] == {"jacket": {"outfit": "Outfit3"}}
    assert rec["members"][0]["sheets"] == {}
    assert {a["node"]: a["members"] for a in rec["alternatives"]} == {
        "OUTFIT 2 Jacket": [2],
        "OUTFIT 2 Afro": [2],
        "OUTFIT 3 Jacket": [3],
    }
    assert "siblingOrder" in rec["order_basis"] and "OUTFIT <k>" in rec["outfit_rule"]


def _part(rig, dx, name):
    return (rig.V + np.float32(dx), rig.SI, rig.SW, rig.T, rig.UV, name)


def test_outfit_nodes_shown_in_scene_hidden_outside_and_sharing_their_vertex_data(tmp_path, rig):
    jacket = lambda mat: [_part(rig, 1.0, mat)]
    outfit = [
        ("OUTFIT 1 Jacket", jacket("outfit"), True),
        ("OUTFIT 2 Jacket", jacket("outfit_3"), False),
        ("OUTFIT 2 Afro", [_part(rig, 2.0, "afro")], False),
    ]
    rec = {
        "mode": "game",
        "alternatives": [{"node": "OUTFIT 2 Jacket"}, {"node": "OUTFIT 2 Afro"}],
        "weapons": {"shown": []},
    }
    out = tmp_path / "o.glb"
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        outfit_parts=outfit,
        parts_record=rec,
    )
    g = parse_glb(out)
    j = g.j
    names = [n["name"] for n in j["nodes"]]
    seen, todo = set(), list(j["scenes"][0]["nodes"])
    while todo:
        i = todo.pop()
        seen.add(names[i])
        todo += j["nodes"][i].get("children", [])
    assert {"mesh", "OUTFIT 1 Jacket"} <= seen
    assert not {"OUTFIT 2 Jacket", "OUTFIT 2 Afro", "alternatives"} & seen
    alt = j["nodes"][names.index("alternatives")]
    assert [names[c] for c in alt["children"]] == ["OUTFIT 2 Jacket", "OUTFIT 2 Afro"]
    node = lambda n: j["nodes"][names.index(n)]
    prim = lambda n: j["meshes"][node(n)["mesh"]]["primitives"][0]
    for n in ("OUTFIT 1 Jacket", "OUTFIT 2 Jacket", "OUTFIT 2 Afro"):
        assert node(n)["skin"] == 0  # follows every animation of the body skeleton
    a, b, c = prim("OUTFIT 1 Jacket"), prim("OUTFIT 2 Jacket"), prim("OUTFIT 2 Afro")
    # the same model in two outfits: the SAME accessors, another material
    assert a["attributes"] == b["attributes"] and a["indices"] == b["indices"]
    assert a["material"] != b["material"]
    assert c["attributes"]["POSITION"] != a["attributes"]["POSITION"]
    # no buffer view is shared by two accessors (that would need a byteStride)
    views = [x["bufferView"] for x in j["accessors"]]
    assert len(views) == len(set(views))
    # the main mesh is written exactly as without the outfit nodes
    plain = tmp_path / "p.glb"
    vg.write_glb(rig.parts, rig.manifest, str(plain), str(rig.bind_npz))
    p = parse_glb(plain)
    for k, i in j["meshes"][0]["primitives"][0]["attributes"].items():
        assert np.array_equal(
            g.accessor(i), p.accessor(p.j["meshes"][0]["primitives"][0]["attributes"][k])
        )
    parts = j["asset"]["extras"]["watchmen"]["parts"]
    assert parts["hidden_nodes"] == ["OUTFIT 2 Jacket", "OUTFIT 2 Afro"]


def _fragment_json(root, stem, nodes):
    d = root / "extracted" / "TNT" / "Production" / "Fragments" / "Enemy"
    d.mkdir(parents=True, exist_ok=True)
    full = []
    for k, (name, models, order) in enumerate(nodes):
        props = [["name", "string", name], ["modelNames", "list", models]]
        if order is not None:
            props.append(["siblingOrder", "integer", order])
        full.append({"id": "n%d" % k, "props": props})
    path = d / (stem + ".fragment.json")
    path.write_text(json.dumps({"nodes_full": full, "instances": []}))
    return path


def test_outfit_order_is_the_engines_child_list_order(tmp_path):
    """Node insert 0x48f556 keeps the child list sorted by siblingOrder; equal
    orders keep the order in which they were added (the file order)."""
    _fragment_json(
        tmp_path,
        "Heavies",
        [
            ("Heavy", ["s", "third"], 7),
            ("Heavy", ["s", "first"], 1),
            ("Heavy", ["s", "second_a"], 3),
            ("Heavy", ["s", "second_b"], 3),
        ],
    )
    ce._FRAG_NODES.clear()
    got = [n["models"][1] for n in ce.variant_nodes(str(tmp_path), "Heavies")]
    assert got == ["first", "second_a", "second_b", "third"]
    ce._FRAG_NODES.clear()


def test_the_binary_fragment_wins_over_a_json_beside_it(tmp_path, monkeypatch):
    """A `.fragment.json` written by an older extractor must never be preferred."""
    stale = _fragment_json(tmp_path, "Dominatrices", [("Stale", ["s", "old"], 1)])
    binary = stale.with_name("Dominatrices.fragment")
    fresh = {"nodes_full": [], "instances": [], "marker": "parsed from the binary"}
    calls = []

    def fake(name_lower, data, order=None):
        calls.append((name_lower, data))
        return fresh

    monkeypatch.setattr(kapow_json, "to_json", fake)
    kapow_json._FRAGMENT_FILES.clear()
    root = str(tmp_path / "extracted")
    # only the JSON is there: found through it, and read
    assert kapow_json.find_fragment(root, "Dominatrices") == str(binary)
    assert kapow_json.load_fragment(str(stale))["nodes_full"][0]["props"][0][2] == "Stale"
    # the binary appears: it is parsed, whichever of the two paths is asked for
    binary.write_bytes(b"BINARY")
    assert kapow_json.load_fragment(str(stale)) is fresh
    assert kapow_json.load_fragment(str(binary)) is fresh
    assert calls == [(str(binary).lower(), b"BINARY")]  # parsed once, then cached
    # the character export goes the same way
    ce._FRAG_NODES.clear()
    assert ce.variant_nodes(str(tmp_path), "Dominatrices") == []
    ce._FRAG_NODES.clear()
    # a binary alone is enough
    stale.unlink()
    assert kapow_json.find_fragment(root, "Dominatrices") == str(binary)
    assert kapow_json.find_fragment(root, "Missing") is None
    kapow_json._FRAGMENT_FILES.clear()


def test_dominatrix_3_is_marked_as_a_reconstruction():
    sv = ce.SYNTH_VARIANTS[("Dominatrices", "Dominatrix_3")]
    assert sv["base"] == "Dominatrix_2" and ce.is_reconstruction("Dominatrices", "Dominatrix_3")
    assert not ce.is_reconstruction("Dominatrices", "Dominatrix_2")


def test_weapon_collections_come_from_the_characters_own_def(tmp_path):
    """CharacterDef.m_emodelcollbash1h / 2h name the two collections set_weapon
    draws from; the built-in table is only the fallback (it had no two-handed
    collection for ThugBig, whose CharacterDef names ThugsWeapons_2H)."""
    d = tmp_path / "extracted" / "TNT" / "Production" / "Fragments" / "Enemy"
    d.mkdir(parents=True)
    weapons = {
        "nodes_full": [
            {"id": "aa", "type": "CharacterModelCollection(Node)", "props": [["name", "string", "ThugsWeaponsBIG_1H"]]},
            {"id": "bb", "type": "CharacterModelCollection(Node)", "props": [["name", "string", "ThugsWeapons_2H"]]},
        ]
    }  # fmt: skip
    (d / "WeaponDB.fragment.json").write_text(json.dumps(weapons))
    big = {
        "nodes_full": [
            {"id": "x", "type": "Folder", "props": [["name", "string", "ThugBig"]]},
            {
                "id": "def",
                "type": "CharacterDef(Node)",
                "props": [
                    ["m_emodelcollbash1h", "Entity", {"xref": ["f3986307", "aa"]}],
                    ["m_emodelcollbash2h", "Entity", {"xref": ["f3986307", "bb"]}],
                ],
            },
        ]
    }
    (d / "ThugBig.fragment.json").write_text(json.dumps(big))
    lady = {"nodes_full": [{"id": "def", "type": "CharacterDef(Node)", "props": [
        ["m_emodelcollbash1h", "Entity", {"etag": 1}], ["m_emodelcollbash2h", "Entity", {"etag": 1}]]}]}  # fmt: skip
    (d / "Lady.fragment.json").write_text(json.dumps(lady))
    old = {"nodes_full": [{"id": "def", "type": "CharacterDef(Node)", "props": [["key_b73828c8", "raw4?", 5]]}]}  # fmt: skip
    (d / "Heavies.fragment.json").write_text(json.dumps(old))
    ex = str(tmp_path)
    ce._WEAPON_COLLS.clear()
    assert ce.CHAR_WEAPON_COLLS["ThugBig"] == ("ThugsWeaponsBIG_1H",)
    assert ce.char_weapon_colls(ex, "ThugBig") == ("ThugsWeaponsBIG_1H", "ThugsWeapons_2H")
    assert ce.char_weapon_colls(ex, "Lady") == ()  # a def that names none: no weapons
    # a fragment that does not carry the named properties, or none at all: the table
    assert ce.char_weapon_colls(ex, "Heavies") == ce.CHAR_WEAPON_COLLS["Heavies"]
    assert ce.char_weapon_colls(ex, "Gimp") == ce.CHAR_WEAPON_COLLS["Gimp"]
    assert ce.char_weapon_colls(ex, "Rorschach") == "*"
    ce._WEAPON_COLLS.clear()
