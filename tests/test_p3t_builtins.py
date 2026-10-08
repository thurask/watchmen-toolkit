"""builtins.json / script_builtins: the builtin script module as registered by
BuiltinModule::RegisterMembers (0x47ff8c).  Pins the counts read from the code and the
internal consistency of the table."""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import script_builtins as sb


def test_counts_read_from_the_registration_routine():
    t = sb.load()
    assert t["format"] == "kapow-builtins/1"
    assert len(t["functions"]) == 123 and len(t["properties"]) == 19
    c = t["counts"]
    assert c["functions"] == 123 and c["properties"] == 19
    assert c["stub_empty_registrations"] == 20 and c["stub_empty_distinct_names"] == 19
    assert c["stub_returns_zero_registrations"] == 3
    assert c["distinct_function_handlers"] == 99
    assert sb.check() == []


def test_stub_marks_follow_the_two_shared_bodies():
    empty = [f for f in sb.functions() if f["stub"] == "empty"]
    zero = [f for f in sb.functions() if f["stub"] == "returns_zero"]
    assert {int(f["handler"]["pc"], 16) for f in empty} == {sb.EMPTY_BODY}
    assert {int(f["handler"]["pc"], 16) for f in zero} == {sb.ZERO_BODY}
    assert sorted(f["name"] for f in zero) == [
        "editor_getselectednode",
        "editor_numselectednodes",
        "geteditoractive",
    ]
    names = [f["name"] for f in empty]
    assert names.count("editor_reloadallassets") == 2  # registered twice
    assert {"drawpoint", "drawline", "profilebegin", "CreateHotkeyBinding"} <= set(names)
    assert not sb.is_stub(sb.functions("CreateNode")[0])
    assert all(sb.is_stub(f) for f in empty + zero)


def test_signatures_types_and_slots():
    f = sb.functions("createnode")[0]
    assert sb.describe(f) == "CreateNode(string,entity):entity"
    assert sb.slot_layout(f) == "[0]=ret:entity [1]:string [2]:entity"
    assert [a["code"] for a in f["args"]] == [4, 12] and f["returns"]["code"] == 12
    f = sb.functions("findrotation")[0]  # quaternion return = 4 slots, vectors 3 each
    assert sb.slot_layout(f) == "[0]=ret:quaternion [4]:vector [7]:vector"
    assert f["arg_slots_total"] == 10
    f = sb.functions("getmessageid")[0]  # biginteger return = 2 slots
    assert f["args"][0]["slot"] == 2
    f = sb.functions("print")[0]  # no return: arguments start at slot 0
    assert f["returns"] is None and f["args"][0]["slot"] == 0
    f = sb.functions("quadtreequery")[0]
    assert [a["code"] for a in f["args"]] == [6, 1, 2, 10]
    assert f["member"] == "BuiltinModule::QuadTreeQueryMSG"
    assert sb.functions("GetGameControllerInfoList")[0]["returns"]["code"] == 10
    assert len(sb.functions("min")) == 2 and len(sb.functions("max")) == 2
    assert {tuple(a["type"] for a in f["args"]) for f in sb.functions("min")} == {
        ("number", "number"),
        ("integer", "integer"),
    }


def test_type_codes():
    assert [sb.type_code(n) for n in ("nothing", "number", "integer", "biginteger")] == [0, 1, 2, 3]
    assert [sb.type_code(n) for n in ("string", "truth", "vector", "quaternion")] == [4, 5, 6, 7]
    assert sb.type_code("list(entity)") == 10 and sb.type_code("dict(Entity)") == 11
    assert sb.type_code("Entity") == 12 and sb.type_code("nosuch") is None
    slots = {r["name"]: r["slots"] for r in sb.load()["type_codes"]}
    assert (slots["vector"], slots["quaternion"], slots["biginteger"], slots["number"]) == (
        3,
        4,
        2,
        1,
    )


def test_properties_and_getters():
    props = sb.properties()
    assert [p["name"] for p in props][:6] == [
        "gametime",
        "realtime",
        "timepassed",
        "realtimepassed",
        "millisecondsSinceFrameStart",
        "pi",
    ]
    by_type = {}
    for p in props:
        by_type[p["type"]] = by_type.get(p["type"], 0) + 1
    assert by_type == {"number": 8, "vector": 7, "integer": 1, "entity": 3}
    assert sb.describe(sb.properties("PLATFORM")[0]) == "platform:entity"
    assert sb.by_handler(0x47B246)[0]["name"] == "platform"
    assert sb.slot_layout(sb.properties("up_vector")[0]) == "getter returns vector"


def test_shared_handlers_resolve_to_all_their_names():
    assert sorted(f["name"] for f in sb.by_handler("0x47ae3b")) == ["NumToInt", "c_int"]
    assert sorted(f["name"] for f in sb.by_handler(0x47BC19)) == [
        "getscreenresolution",
        "getscreensize",
    ]
    assert len(sb.by_handler(sb.EMPTY_BODY)) == 20
    assert sb.by_handler(0x400000) == []
    f = sb.functions("c_int")[0]
    assert f["shares_body_with"] == ["NumToInt"]


def test_enums():
    assert [sb.enum_value("LANGUAGE", n) for n in ("English", "French", "Italian")] == [0, 1, 2]
    assert [sb.enum_value("language", n) for n in ("German", "Spanish", "Danish")] == [3, 4, 5]
    assert sb.enum_value("LANGUAGE", "LANGUAGE___DANISH") == 5
    assert [sb.enum_value("PLATFORM", n) for n in ("EDITOR", "PC", "X360", "PS3")] == [0, 1, 2, 3]
    assert sb.enum_value("PLATFORM", "WII") is None and sb.enum_value("NOPE", "PC") is None
    assert sb.load()["counts"]["enum_members"] == 10


def test_every_entry_has_a_semantics_line_with_its_evidence():
    for e in sb.functions() + sb.properties():
        assert e["semantics"] and e["semantics_evidence"] in ("read", "from name"), e["name"]
        h = e.get("handler") or e.get("getter")
        assert h["pc"].startswith("0x") and h["ps3"]


def test_check_reports_a_broken_table():
    import copy

    t = copy.deepcopy(sb.load())
    t["functions"][0]["stub"] = "empty"
    t["functions"][1]["args"][0]["slot"] = 7
    bad = sb.check(t)
    assert any("stub mark" in b for b in bad) and any("slots of" in b for b in bad)
