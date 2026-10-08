"""Rules read from the executable and measured on captures after the pass-8 export, as the
toolkit applies them.

animation   layers of a state (SetupNewPage 0x5b7788): layer_index, additive,
            force_playpos_1, layer_weight on a state's clip rows; layer_use on clips
combat      rules.partner_ai.waypoint_move (0x6289b4) and the kill-target defect; the
            Underboss's movement (0x887a07), flee and flamethrower volumes
formats     field names read from the loaders, with the offset-style keys as aliases:
            terrain decals and sectors, index buffers, terrain colouring, detail mesh
            lists, fonts, the pivot-book header, texture usage, the model header's
            skinned bone count, a submesh's hidden flag, a shadow hull's cloth link
Synthetic fixtures only."""

import json
import struct

import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import anim_state_machine as asm
import combat_meta as cm
import font_asset as fa
import kapow_json as kj
import kapow_props as kp
import skeleton_records as sr
import terrain_asset as ta
import watchmen_extract as we
from test_interp_v2 import node


# ------------------------------------------------------------------ animation layers
def _layered_state(root, name="Idle"):
    s = node(asm.CLS_STATE, name, root)
    base = node(asm.CLS_BLEND, "{MOTION_LAYER_1}", s, m_ilayerindex=0)
    inner = node(asm.CLS_BLEND, "{inner}", base)  # a blend tree: its slots are the base's
    node(asm.CLS_SLOT, "walk.animation", inner, targetAnimation="walk.animation")
    arm = node(
        asm.CLS_BLEND,
        "{ACTION_LAYER_1}",
        s,
        m_ilayerindex=10,
        m_ilayerweightctrlparam=3,
        m_nlayerweightintervalstart=0.0,
        m_nlayerweightintervalend=1.0,
    )
    node(asm.CLS_SLOT, "arm_layer.animation", arm, targetAnimation="arm_layer.animation")
    look = node(
        asm.CLS_BLEND,
        "{ACTION_LAYER_2}",
        s,
        m_ilayerindex=11,
        m_tlayeradditive=True,
        m_tforcedpos=1,
    )
    node(asm.CLS_SLOT, "look_up.animation", look, targetAnimation="look_up.animation")
    return s


def test_a_state_clip_row_names_its_layer():
    root = node(asm.CLS_CLASS, "C")
    rows = {r["clip"]: r for r in am.state_record(_layered_state(root))["clips"]}
    walk, arm, look = rows["walk"], rows["arm_layer"], rows["look_up"]
    # the slot of a nested blend reports the blend directly under the state
    assert (walk["layer_index"], walk["additive"], walk["force_playpos_1"]) == (0, False, False)
    assert "layer_weight" not in walk and walk["layer"] == "inner"
    assert arm["layer_index"] == 10 and arm["additive"] is False
    assert arm["layer_weight"]["start"] == 0.0 and arm["layer_weight"]["end"] == 1.0
    assert isinstance(arm["layer_weight"]["value"], str)
    assert (look["layer_index"], look["additive"], look["force_playpos_1"]) == (11, True, True)
    assert am.layer_use(list(rows.values())) == {
        "walk": ["base"],
        "arm_layer": ["upper"],
        "look_up": ["additive"],
    }


def test_layer_use_is_base_only_in_a_non_additive_blend_of_the_lowest_layer():
    row = lambda c, i, a=False: {"clip": c, "layer_index": i, "additive": a}
    # a HeadTurn state: every layer additive, so nothing is a base
    assert am.layer_use([row("a", 0, True), row("b", 10, True)]) == {
        "a": ["additive"],
        "b": ["additive"],
    }
    # the lowest index of the state is the base, whatever its number
    assert am.layer_use([row("a", 10), row("b", 11), row("a", 11), row("", 11)]) == {
        "a": ["base", "upper"],
        "b": ["upper"],
    }
    assert "layer_use" in am.CONVENTIONS["layers"] and "0x5b7788" in am.CONVENTIONS["layers"]
    assert am.CONVENTIONS_TRUE["layers"] == am.CONVENTIONS["layers"]


# ------------------------------------------------------------------ combat rules
def test_partner_waypoint_move_and_the_kill_target_defect():
    p = cm.rules()["partner_ai"]
    w = p["waypoint_move"]
    assert "0x6289b4" in w["handlers"] and "0x629b68" in w["handlers"]
    assert (w["arrive_m"], w["stand_before_use_s"], w["walk_within_m"]) == (1.0, 1.0, 3.0)
    assert (w["stuck_move_m"], w["stuck_s"], w["first_replan_s"], w["replan_s"]) == (
        0.1,
        5.0,
        0.5,
        5.0,
    )
    assert w["flying_waypoint_range_m"] == 50.0 and w["force_move_s"] == 2.0
    assert "0x629c52" in w["use_trigger"] and "inferred" in w["use_trigger"]
    defect = p["known_defects"][1]
    assert "0x6e6495" in defect and "0x6e388e" in defect and "0x691013" in defect
    assert "not established" not in defect


def test_underboss_movement_flee_and_flamer_volumes():
    u = cm.rules(None, [{"name": "UB"}])["underboss"]
    mv, fl, fv = u["movement"], u["flee"], u["flamer_volumes"]
    assert "0x887a07" in mv["evidence"] and mv["full_speed_from_m"] == 5.0
    assert (mv["step_back_turn_first_rad"], mv["step_back_stop_after_s"]) == (1.5, 0.5)
    assert mv["step_back_stop_below_speed"] == 0.6 and mv["turn_in_place_error_rad"] == 0.3
    assert fl["candidate_index_steps"] == [1, 3] and fl["candidate_max_dot"] == 0.9
    assert fl["arrive_m"] == 2.0 and "0x886913" in fl["evidence"]
    assert (fv["length_m"], fv["speed_m_per_s"], fv["capsules"]) == (12.0, 10.0, 5)
    # the start ages spread length / speed over the capsules
    n = fv["capsules"]
    ages = [round(fv["length_m"] / fv["speed_m_per_s"] * i / (n - 1), 6) for i in range(n)]
    assert fv["start_ages_s"] == ages
    assert "flee geometry" not in u["not_established"]


# ------------------------------------------------------------------ cameras, sound
def test_exploration_camera_collision_is_exported_as_read():
    import fx_meta

    src = open(fx_meta.__file__, encoding="utf-8").read()
    assert '"not_traced"' not in src and "were not traced" not in src
    cam = fx_meta._GAMEPLAY_CAMERAS["exploration"]
    assert cam["collision"] == {
        "order": ["LineChecks", "CapsuleCheck", "OffsetXCheck"],
        "min_distance_m": 0.1,
        "capsule_lead_m": 0.5,
        "offset_x_factor": 1.1,
        "handlers": "0x65436e, 0x654196, 0x653883, 0x653b26, 0x644cc6",
    }
    assert cam["collision"]["offset_x_factor"] == cam["offset_x_check_factor"]
    assert "gameplay cameras: nothing was checked in the running game" in fx_meta._NOT_ESTABLISHED


# ------------------------------------------------------------------ format field names
def test_terrain_names_follow_the_loader_and_the_old_keys_still_build():
    import test_p3_raw_formats as t3

    old = t3._terrain_doc("<")  # offset-style keys only, as a JSON written before the names
    data = ta.build(old)
    doc = ta.parse(data)
    d, s = doc["decals"][0], doc["sectors"][0]
    assert (d["texture"], d["uv_rotation_deg"], d["wrap_u"], d["wrap_v"]) == (0, -90.0, 1, 1)
    assert (d["b10"], d["f14"], d["b19"], d["b1a"]) == (0, -90.0, 1, 1)  # the aliases
    assert d["uv_scale"] == pytest.approx([1.0, 0.86]) and d["uv_offset"] == [0.0, 0.0]
    assert d["f1c"] == d["uv_scale"] + d["uv_offset"]
    assert s["enabled"] == s["flag"] == 1
    assert s["cells"][0]["index_buffer"]["primitive_type"] == 1
    assert doc["not_established"] == ["decals[].b18", "decals[].uv_offset (how it enters the UV)"]
    assert "0x53886b" in doc["inferred"]["decal_textures / decals"]
    assert "131 decals" in doc["inferred"]["decals[].uv_rotation_deg"]
    assert ta.build(json.loads(json.dumps(doc))) == data
    # a name wins over its alias; a dict with only the names builds too
    new = json.loads(json.dumps(doc))
    nd, ns = new["decals"][0], new["sectors"][0]
    nd.update(texture=3, uv_rotation_deg=30.0, wrap_u=0, uv_offset=[0.52, 0.54])
    ns["enabled"] = 0
    ns["cells"][0]["index_buffer"]["primitive_type"] = 2
    for k in ("b10", "f14", "b19", "b1a", "f1c"):
        del nd[k]
    del ns["flag"], ns["cells"][0]["index_buffer"]["x"]
    again = ta.parse(ta.build(new))
    a = again["decals"][0]
    assert (a["b10"], a["f14"], a["b19"], a["b1a"]) == (3, 30.0, 0, 1)
    assert a["f1c"] == pytest.approx([1.0, 0.86, 0.52, 0.54])
    assert again["sectors"][0]["flag"] == 0
    assert again["sectors"][0]["cells"][0]["index_buffer"]["x"] == 2


def test_coloring_names_are_the_registered_properties():
    import test_p3_raw_formats as t3

    data = t3._coloring("<")
    doc = ta.coloring_parse(data)
    for name, alias in ta.COLORING_ALIASES:
        assert doc[name] == doc[alias], name
    assert [n for n, _a in ta.COLORING_ALIASES][:2] == ["map_width", "map_height"]
    assert (doc["map_width"], doc["map_height"], doc["numberOfRays"]) == (3, 2, 128)
    assert doc["raycastLength"] == 3.5 and doc["texture"]["usage"] == doc["texture"]["x"]
    assert doc["not_established"] == [] and "ua0 / ua4" not in doc["inferred"]
    assert "0x52d646" in doc["evidence"] and "0x52cb15" in doc["evidence"]
    new = json.loads(json.dumps(doc))
    new["numberOfRays"] = 64
    new["texture"]["usage"] = 1
    for _n, alias in ta.COLORING_ALIASES:
        del new[alias]
    del new["texture"]["x"]
    again = ta.coloring_parse(ta.coloring_build(new))
    assert again["ub0"] == 64 and again["texture"]["x"] == 1 and again["ua0"] == 3
    old = {k: v for k, v in doc.items() if k not in dict(ta.COLORING_ALIASES)}
    old["texture"] = {k: v for k, v in doc["texture"].items() if k != "usage"}
    assert ta.coloring_build(old) == data


def test_detail_mesh_lists_are_named_and_the_primitive_type_builds():
    import test_p3_raw_formats as t3

    doc = kj.to_json("a.detailmesh", t3._detail("<"), order="<", stream=t3._detail_stream("<"))
    assert doc["stream"]["list_names"] == ta.DETAIL_LIST_NAMES
    assert ta.DETAIL_LIST_NAMES == ["first_index_a", "first_index_b", "triangle_count"]
    m = doc["mesh"]
    assert m["index_buffer"]["primitive_type"] == m["index_buffer"]["x"] == 1
    assert doc["not_established"] == []
    tail = ta.detail_tail_build(m, "<")
    only_name = json.loads(json.dumps(m))
    del only_name["index_buffer"]["x"]
    only_alias = json.loads(json.dumps(m))
    del only_alias["index_buffer"]["primitive_type"]
    assert ta.detail_tail_build(only_name, "<") == tail == ta.detail_tail_build(only_alias, "<")


def test_font_names_and_aliases():
    import test_p3_raw_formats as t3

    old = t3._font_doc("<")  # offset-style keys only
    old.update(b04=4, b38=1, b3c=2, v28=[0.5, 1.5], v30=[2.0, 3.0], f24=7.0)
    data = fa.build(old, t3._PIX)
    doc = fa.parse(data)
    for name, alias in fa.ALIASES:
        assert doc[name] == doc[alias], name
    assert (doc["flags"], doc["h_align"], doc["v_align"]) == (4, 1, 2)
    assert (doc["spacing"], doc["scale"], doc["fixed_advance"]) == ([0.5, 1.5], [2.0, 3.0], 7.0)
    assert doc["texture"]["usage"] == doc["texture"]["x"] == 0 and doc["not_established"] == []
    assert fa.build(json.loads(json.dumps(doc)), t3._PIX) == data
    new = json.loads(json.dumps(doc))
    new.update(flags=0, fixed_advance=0.0)
    new["texture"]["usage"] = 1
    for _n, alias in fa.ALIASES:
        del new[alias]
    del new["texture"]["x"]
    again = fa.parse(fa.build(new, t3._PIX))
    assert (again["b04"], again["f24"], again["b38"], again["texture"]["x"]) == (0, 0.0, 1, 1)


@pytest.mark.parametrize("bo", ["<", ">"])
def test_pivot_book_header_is_the_book_id_and_the_sheet_count(bo):
    import test_p2_part1 as p1

    for typed in (True, False):
        raw = p1._pivot_book(bo, typed)
        assert sr.pivot_book_id(raw, bo) == 0x0000296416269EFA
        assert kp.pivot_book(raw, bo)["book_id"] == "0x0000296416269efa"
        doc = kj.to_json("default.pb", raw, order=bo)
        assert doc["book_id"] == "0x0000296416269efa" and doc["sheet_count"] == 2
        # the words stay, in file order: the high word is first in a console file
        words = [0x16269EFA, 0x2964] if bo == "<" else [0x2964, 0x16269EFA]
        assert doc["blocks"][0]["pre"] == words + [2]
        assert raw[:8] == bytes.fromhex("fa9e261664290000" if bo == "<" else "0000296416269efa")
        assert kj.to_json("default.pb", raw)["book_id"] == "0x0000296416269efa"  # order found
        assert kp.pivot_book(raw)["book_id"] == "0x0000296416269efa"
    with pytest.raises(ValueError):
        sr.pivot_book_id(b"\0" * 8, bo)
    # no three-word header in front of the first object: no book id
    assert "book_id" not in kp.pivot_book(raw[12:], bo)
    assert "book_id" not in kj.to_json("x.pb", raw[12:], order=bo)


def test_model_header_names_the_bone_count_the_hidden_flag_and_the_cloth_link():
    import test_p3_part1_model as tm

    h, _s = tm.build("<", "part2")
    M = we.parse_model_header(h)
    assert M["has_skeleton"] == 1 and M["skinned_bone_count"] is None  # stored 0xFFFFFFFF
    sm = M["parts"][1]["lods"][0][0]
    assert sm["hidden"] == sm["b24"] and not sm["hidden"]
    (hull,) = [b for b in M["buffers"] if b["kind"] == "shadow"]
    assert hull["from_cloth"] is False and hull["cloth_submesh"] is None  # (0, -1): merged
    head = struct.pack("<IBIB", 0, 1, 0xFFFFFFFF, 0)
    rec = struct.pack("<I", 1) + b"\0" + struct.pack("<I", 0xFFFFFFFF)
    assert h.count(head) == 1 and h.count(rec) == 1
    h2 = h.replace(head, struct.pack("<IBIB", 0, 1, 37, 0))
    h2 = h2.replace(rec, struct.pack("<I", 1) + b"\1" + struct.pack("<I", 0))
    M2 = we.parse_model_header(h2)
    assert M2["skinned_bone_count"] == 37
    (hull,) = [b for b in M2["buffers"] if b["kind"] == "shadow"]
    assert hull["from_cloth"] is True and hull["cloth_submesh"] == 0  # hull of cloth submesh 0


def test_texture_slot_carries_the_usage_word():
    import test_formats_v2 as f2

    desc = f2._tex_desc(8, 8, 5, 4)
    hdr = f2._tex_header([({0: desc}, "/data/art/x/Thing.bmp")])
    assert we.parse_texture_frames(hdr)["frames"][0]["slots"][0]["usage"] == 0
    w, h, en, _usage = struct.unpack_from("<4I", desc, 0)
    patched = struct.pack("<4I", w, h, en, 1) + desc[16:]
    hdr = f2._tex_header([({0: patched}, "/data/art/x/Thing.bmp")])
    assert we.parse_texture_frames(hdr)["frames"][0]["slots"][0]["usage"] == 1
