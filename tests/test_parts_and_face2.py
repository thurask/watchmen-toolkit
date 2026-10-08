"""Which of a variant's models the game shows, and how the GLB keeps the rest.

Synthetic fixtures.  The shapes mirror the shipped data (read 2026-10-04):
`Heavies.fragment` holds 18 CharacterHeadModel nodes all named "Heavy", each a
complete outfit; the extractor's per-name record is the union of their model
lists, which is what the character GLBs used to show."""

import os
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import face_rule as fr
import parts_rule as pr
import variant_glb as vg

from conftest import parse_glb
from test_face_rule import Frag, model

HEAVY = [  # (models of the member, in slot order; '' = empty slot)
    ["Medium_Skeleton", "", "Jacket", "Chains", "Hands", "Hair_Side", "Sunglasses"],
    ["Medium_Skeleton", "Afro", "Jacket", "Chains", "Hands", "Sunglasses", ""],
    ["Medium_Skeleton", "", "Jacket", "", "Hands", "", ""],
    ["Medium_Skeleton", "Hair_Long", "Jacket", "Chains", "Hands", "", ""],
]
UNION = ["Jacket", "Chains", "Hands", "Hair_Side", "Sunglasses", "Afro", "Hair_Long"]


@pytest.fixture
def heavies(tmp_path):
    f = Frag()
    coll = f.add("CharacterModelCollection", "Model", _eheadmodelcollection={"xref": "Faces"})
    for models in HEAVY:
        f.add(
            "CharacterHeadModel",
            "Heavy",
            coll,
            m_iheadmodeltype=22,
            modelNames=[model(m) if m else "" for m in models],
        )
    f.add("CharacterHeadModel", "Solo", coll, m_iheadmodeltype=3, modelNames=[model("Body")])
    f.write(tmp_path, "Heavies")
    fr._HEADS.clear()
    yield str(tmp_path)
    fr._HEADS.clear()


def test_members_are_the_same_named_collection_nodes_in_list_order(heavies):
    m = pr.members(heavies, "Heavy")
    assert [x["index"] for x in m] == [1, 2, 3, 4]
    assert m[0]["models"] == ["Jacket", "Chains", "Hands", "Hair_Side", "Sunglasses"]
    assert m[2]["models"] == ["Jacket", "Hands"]  # empty slots and the skeleton dropped
    assert m[1]["head_model_type"] == 22 and m[1]["head_model_type_name"] == "HEAVY_1"
    assert pr.members(heavies, "Rorschach") == []


def test_split_shows_the_first_members_models_only(heavies):
    m = pr.members(heavies, "Heavy")
    shown, alt = pr.split(UNION, m)
    assert shown == ["Jacket", "Chains", "Hands", "Hair_Side", "Sunglasses"]
    assert alt == ["Afro", "Hair_Long"]  # the two other hairstyles
    shown, alt = pr.split(UNION, m, show=3)  # the bald member
    assert shown == ["Jacket", "Hands"] and "Chains" in alt and "Hair_Side" in alt
    # a model no member lists (a reconstructed part) is never hidden
    assert pr.split(UNION + ["Grafted_Hair"], m)[0][-1] == "Grafted_Hair"
    # one member, or none: everything is the character
    assert pr.split(["Body"], pr.members(heavies, "Solo")) == (["Body"], [])
    assert pr.split(["Rorschach"], []) == (["Rorschach"], [])


def test_record_lists_members_alternatives_and_the_rule(heavies):
    m = pr.members(heavies, "Heavy")
    shown, alt = pr.split(UNION, m)
    rec = pr.record(m, UNION, shown, alt)
    assert rec["mode"] == "game" and rec["member_shown"] == 1
    assert [x["shown"] for x in rec["members"]] == [True, False, False, False]
    assert rec["alternatives"] == [
        {"node": "ALT Afro", "model": "Afro", "members": [2]},
        {"node": "ALT Hair_Long", "model": "Hair_Long", "members": [4]},
    ]
    assert "0x66ca15" in rec["rule"] and "not random" in rec["rule"]
    # a member's model the export does not carry is named
    rec = pr.record(m, [u for u in UNION if u != "Afro"], shown, ["Hair_Long"])
    assert rec["members"][1]["not_exported"] == ["Afro"]


def test_mode_switch(monkeypatch):
    monkeypatch.delenv("WATCHMEN_PARTS", raising=False)
    assert pr.mode() == "game"
    monkeypatch.setenv("WATCHMEN_PARTS", "all")
    assert pr.mode() == "all" and pr.mode("game") == "game"
    with pytest.raises(ValueError):
        pr.mode("some")


def test_cli_parts_flag(monkeypatch, capsys):
    import watchmen

    monkeypatch.delenv("WATCHMEN_PARTS", raising=False)
    assert watchmen.main(["watchmen", "characters", "x", "y", "--parts", "most"]) == 2
    assert "--parts takes one of: game, all" in capsys.readouterr().out
    assert watchmen.main(["watchmen", "faces", "x", "y", "--parts", "all"]) == 2
    assert "--parts applies to: all, characters" in capsys.readouterr().out
    assert "WATCHMEN_PARTS" not in os.environ
    assert watchmen.main(["watchmen", "characters", "--parts", "all"]) == 2  # too few arguments
    assert os.environ["WATCHMEN_PARTS"] == "all"
    # the command set it: monkeypatch did not record it (it was absent), so drop it here
    os.environ.pop("WATCHMEN_PARTS")
    assert "[--parts game|all]" in watchmen.USAGE["characters"][1]


# ------------------------------------------------------------------ weapons
def test_weapon_record_names_collections_types_and_what_is_shown():
    sets = {
        "HeaviesWeapons_1H": ["/x/Bottle", "/x/Bat"],
        "HeaviesWeapons_2H": ["/x/Wrench"],
        "GimpWeapons_1H": ["/x/Paddle"],
    }
    rec = pr.weapon_record(
        ["WPN_Bottle", "WPN_Bat", "WPN_Wrench"], sets, ("HeaviesWeapons_1H", "HeaviesWeapons_2H")
    )
    assert rec["shown"] == [] and rec["attach_bone"] == "Attach RHand" and not rec["player"]
    assert [(n["model"], n["weapon_types"], n["shown"]) for n in rec["nodes"]] == [
        ("Bottle", ["BASH_1H"], False),
        ("Bat", ["BASH_1H"], False),
        ("Wrench", ["BASH_2H"], False),
    ]
    assert "0x694378" in rec["rule"] and "_iweapontype" in rec["rule"]
    # a player picks up anything; Twilight Lady's whip is part of her
    assert pr.weapon_record(["WPN_Paddle"], sets, "*")["nodes"][0]["collections"] == [
        "GimpWeapons_1H"
    ]
    assert pr.weapon_record(["WPN_Paddle"], sets, "*")["player"] is True
    rec = pr.weapon_record(["WPN_TW_weapon"], sets, None, always=["WPN_TW_weapon"])
    assert rec["shown"] == ["WPN_TW_weapon"] and rec["nodes"][0]["shown"] is True


def test_clip_weapon_use_from_criteria_and_weapon_blends():
    blend2h = "MOTION_LAYER_1, blend on HAS_2H_WEAPON 0-1"
    armed = "MOTION_LAYER_1, blend on HAS_WEAPON 0-1"

    def st(name, main, clips, weapon=()):
        return {"name": name, "main_clip": main, "clips": clips, "weapon": list(weapon)}

    def row(clip, layer, pos):
        return {"clip": clip, "layer": layer, "blend_position": pos}

    meta = {
        "classes": {
            "Enemy01": {
                "states": [
                    st(
                        "Idle", "idle_2h", [row("idle", blend2h, 0.0), row("idle_2h", blend2h, 1.0)]
                    ),
                    st("Run", "run_w", [row("run", armed, 0.0), row("run_w", armed, 1.0)]),
                    st("Swing", "swing_1h", [row("swing_1h", "MOTION_LAYER_1", None)], ["BASH_1H"]),
                    st("Plain", "walk", [row("walk", "MOTION_LAYER_1", None)]),
                    st(
                        "Dir",
                        "left",
                        [
                            row("left", "L, blend on DIRECTION -3-3", -3.0),
                            row("right", "L, blend on DIRECTION -3-3", 3.0),
                        ],
                    ),
                ]
            }
        }
    }
    use = pr.clip_weapon_use(meta)
    assert use["idle"] == {
        "classes": ["UNARMED", "BASH_1H"],
        "basis": ["blend on HAS_2H_WEAPON (low end)"],
    }
    assert use["idle_2h"]["classes"] == ["BASH_2H"]
    assert use["run"]["classes"] == ["UNARMED"] and use["run_w"]["classes"] == [
        "BASH_1H",
        "BASH_2H",
    ]
    assert use["swing_1h"] == {"classes": ["BASH_1H"], "basis": ["criteria WEAPON_ANIMATION_TYPE"]}
    assert "walk" not in use and "left" not in use  # not tied to a weapon by the data


# ---------------------------------------------------------- the GLB writer
def _part(rig, dx, name):
    return (rig.V + np.float32(dx), rig.SI, rig.SW, rig.T, rig.UV, name)


def _write(tmp_path, rig, name, **kw):
    out = tmp_path / name
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz), **kw)
    return parse_glb(out)


def test_alternatives_are_kept_outside_the_scene(tmp_path, rig):
    alt = [
        ("ALT Afro", [_part(rig, 1.0, "hair_afro")]),
        ("ALT Hair_Long", [_part(rig, 2.0, "hair_long")]),
    ]
    wpn = [("WPN_Bat", [_part(rig, 3.0, "bat")])]
    rec = {
        "mode": "game",
        "alternatives": [
            {"node": "ALT Afro", "model": "Afro", "members": [2]},
            {"node": "ALT Gone", "model": "Gone", "members": [3]},
        ],
        "weapons": {"shown": []},
    }
    glb = _write(tmp_path, rig, "g.glb", attachments=wpn, alt_parts=alt, parts_record=rec)
    j = glb.j
    names = [n["name"] for n in j["nodes"]]
    assert len(j["scenes"]) == 1 and j["scenes"][0]["name"] == "game"
    # what the scene reaches: the skeleton and the character's own mesh, nothing else
    seen, todo = set(), list(j["scenes"][0]["nodes"])
    while todo:
        i = todo.pop()
        seen.add(names[i])
        todo += j["nodes"][i].get("children", [])
    assert "mesh" in seen and not {"ALT Afro", "ALT Hair_Long", "WPN_Bat", "alternatives"} & seen
    grp = j["nodes"][names.index("alternatives")]
    assert [names[c] for c in grp["children"]] == ["WPN_Bat", "ALT Afro", "ALT Hair_Long"]
    for c in grp["children"]:  # still skinned to the body's skeleton
        assert j["nodes"][c]["skin"] == 0 and "mesh" in j["nodes"][c]
    parts = j["asset"]["extras"]["watchmen"]["parts"]
    assert parts["hidden_nodes"] == ["WPN_Bat", "ALT Afro", "ALT Hair_Long"]
    assert [a["node"] for a in parts["alternatives"]] == ["ALT Afro"]  # only nodes that exist
    assert "Orphan Nodes" in parts["hidden_under"]
    # the body mesh itself is what it is without the alternatives
    plain = _write(tmp_path, rig, "p.glb")
    assert (
        j["meshes"][0]["primitives"][0]["attributes"].keys()
        == plain.j["meshes"][0]["primitives"][0]["attributes"].keys()
    )
    assert np.array_equal(
        glb.accessor(j["meshes"][0]["primitives"][0]["attributes"]["POSITION"]),
        plain.accessor(plain.j["meshes"][0]["primitives"][0]["attributes"]["POSITION"]),
    )


def test_a_weapon_named_as_shown_stays_in_the_scene(tmp_path, rig):
    wpn = [("WPN_Whip", [_part(rig, 3.0, "whip")]), ("WPN_Bat", [_part(rig, 4.0, "bat")])]
    rec = {"mode": "game", "alternatives": [], "weapons": {"shown": ["WPN_Whip"]}}
    j = _write(tmp_path, rig, "w.glb", attachments=wpn, parts_record=rec).j
    names = [n["name"] for n in j["nodes"]]
    root = j["nodes"][names.index("root")]
    kids = [names[c] for c in root["children"]]
    assert "WPN_Whip" in kids and "WPN_Bat" not in kids
    assert [names[c] for c in j["nodes"][names.index("alternatives")]["children"]] == ["WPN_Bat"]


def test_without_a_parts_record_nothing_is_hidden_and_the_file_is_the_old_one(tmp_path, rig):
    """--parts all: attachments under the root, no `alternatives` node, no parts
    extras -- byte for byte what the writer produced before."""
    wpn = [("WPN_Bat", [_part(rig, 3.0, "bat")])]
    a = tmp_path / "a.glb"
    b = tmp_path / "b.glb"
    vg.write_glb(rig.parts, rig.manifest, str(a), str(rig.bind_npz), attachments=wpn)
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(b),
        str(rig.bind_npz),
        attachments=wpn,
        alt_parts=None,
        parts_record=None,
    )
    assert a.read_bytes() == b.read_bytes()
    j = parse_glb(a).j
    names = [n["name"] for n in j["nodes"]]
    assert "alternatives" not in names and "name" not in j["scenes"][0]
    assert "WPN_Bat" in [names[c] for c in j["nodes"][names.index("root")]["children"]]
    assert "parts" not in ((j["asset"].get("extras") or {}).get("watchmen") or {})


def test_nothing_hidden_means_no_alternatives_node(tmp_path, rig):
    rec = {"mode": "game", "alternatives": [], "weapons": {"shown": []}}
    j = _write(tmp_path, rig, "n.glb", parts_record=rec).j
    assert "alternatives" not in [n["name"] for n in j["nodes"]]
    parts = j["asset"]["extras"]["watchmen"]["parts"]
    assert parts["hidden_nodes"] == [] and parts["hidden_under"] is None


# ------------------------------------------------- face: what the exe settled
import test_face_rule as tf

face_extract = tf.face_extract  # the fixture: a hero finisher and its victim


def test_back_pose_table_is_the_engines():
    # DirectionManipulateDamage 0x802ae8: 1-3 -> 23, 4-6 -> 24, ... 16-18 -> 28, 19 -> 21, 20 -> 22
    assert [fr.back_pose(p) for p in (1, 3, 4, 6, 9, 12, 15, 16, 18)] == [
        23,
        23,
        24,
        24,
        25,
        26,
        27,
        28,
        28,
    ]
    assert fr.back_pose(19) == 21 and fr.back_pose(20) == 22
    assert fr.back_pose(0) == 0 and fr.back_pose(23) == 23  # no pose / already a back pose


def test_direction_manipulate_needs_the_attacker_clearly_behind():
    assert fr.BEHIND_Z == -0.2
    assert fr.direction_manipulate(5, 1.0) == 5
    assert fr.direction_manipulate(5, -0.2) == 5  # strictly below
    assert fr.direction_manipulate(5, -0.21) == 24


def test_character_mode_comes_from_the_criteria_or_is_marked_assumed():
    mode, basis = fr.character_mode(["STUNNED"], False, False)
    assert mode == 3 and basis.startswith("data:")
    mode, basis = fr.character_mode(None, False, True)
    assert mode == fr.MODE_DEAD and basis.startswith("data:")
    mode, basis = fr.character_mode(["NONCOMBAT", "PRONE"], True, False)
    assert mode == fr.MODE_NONCOMBAT and basis.startswith("data:")  # COMBAT excluded
    mode, basis = fr.character_mode(None, True, False)
    assert mode == fr.MODE_COMBAT and basis.startswith("assumed:")
    mode, basis = fr.character_mode(["NONCOMBAT", "COMBAT"], False, False)
    assert mode == fr.MODE_NONCOMBAT and basis.startswith("assumed:")


def test_head_and_neck_copy_space_is_recorded_as_bone_local():
    assert fr.ATTACHMENT["copy_space"].startswith("bone-local")
    assert "0x4ba7ad" in fr.ATTACHMENT["copy_space"]


def test_metadata_says_the_mode_basis_and_what_a_hit_from_behind_would_show(face_extract):
    import anim_meta as am

    tf._face_fragment(face_extract)
    tf._charvisual(face_extract, 3, 7)
    m = am.build(str(face_extract))
    states = {s["name"]: s for s in m["classes"]["Enemy01"]["states"]}
    cm = states["Idle"]["face"]["character_mode"]
    assert cm["name"] == "NONCOMBAT" and cm["basis"].startswith("assumed:")
    assert "blend_position" in states["Idle"]["clips"][0]
    (pair,) = [p for p in m["pairs"] if p.get("primary")]
    victim = pair["face"]["partner"]
    assert "character_mode" in victim
    hit = victim["inputs"][0]
    assert hit["source"].endswith("IMPACT_EFFECTS")
    poses = {v: k for k, v in fr.ee.family("DAMAGE_POSE").items()}
    back = fr.back_pose(hit["damage_pose_id"])
    assert poses[hit["damage_pose_if_behind"]] == back
    assert hit["behind_changes_face"] == (hit["face_state"] != hit["face_state_if_behind"])
    kill = victim["inputs"][1]  # KILL_ANIMATION_PARTNER: not routed through the direction step
    assert "damage_pose_if_behind" not in kill


def test_metadata_gives_the_weapon_class_of_a_clip(face_extract):
    import anim_meta as am
    import test_anim_meta as tam

    e = tam.Frag()
    root = e.add("AnimationClassWM", "Enemy02AnimationClass", m_iclassid=4)
    e.state("Idle", root, "EN2_idle", m_tislooping=True)
    e.write(face_extract, "Enemy02")
    m = am.build(str(face_extract))
    assert all("weapon_use" not in c for c in m["clips"].values())  # nothing tests a weapon here
    m["classes"]["Enemy02"]["states"][0]["weapon"] = ["BASH_2H"]
    use = pr.clip_weapon_use(m)
    assert use == {
        "EN2_idle": {"classes": ["BASH_2H"], "basis": ["criteria WEAPON_ANIMATION_TYPE"]}
    }
