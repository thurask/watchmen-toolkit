"""Name tables touched by the open-items sweep.

builtins.json    which builtins the X360 Part 1 image lacks / adds (member-name strings)
names2.tsv       the Kynapse bridge functions, named from their role
fx_meta          the Twilight Lady's fake weapon is null in shipped data (0x6943b8)
No game files."""

import json, os, sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import fx_meta
import kapow_props as kp

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def test_builtins_table_says_what_x360_part1_differs_in():
    with open(os.path.join(ROOT, "wlib", "builtins.json"), encoding="utf-8") as fh:
        j = json.load(fh)
    ob = j["other_builds"]
    assert ob["same_as_pc_p2"] == ["x360_p2", "ps3_p2", "ps3_p1"]
    x = ob["x360_p1"]
    assert x["missing_indices"] == [68, 69, 98, 99, 100, 119, 120, 121]
    names = [j["functions"][i]["name"] for i in x["missing_indices"]]
    assert names[0] == "SortPivotNodes" and names[-1] == "UnRegisterPerformanceMeasurementCallback"
    assert [e["name"] for e in x["extra"]] == ["set_disc_error_message", "disablecurrentloadscreen"]
    assert x["extra"][0]["signature"] == "set_disc_error_message(entity,integer)"
    assert x["evidence"].endswith("registration not read")
    assert len(j["functions"]) == 123  # the PC Part 2 table itself is unchanged


def test_kynapse_bridge_functions_are_named():
    rows = {}
    with open(os.path.join(ROOT, "tools", "ghidra", "names2.tsv"), encoding="utf-8") as fh:
        for line in fh:
            cols = line.rstrip("\n").split("\t")
            assert len(cols) == 4 and cols[0] not in rows
            assert cols[3].startswith(("high: ", "medium: "))
            rows[cols[0]] = cols
    assert len(rows) == 5036
    assert rows["48b44e"][1] == "KynapseSkel_RayBlocked"
    assert rows["48a6a4"][1] == "KynapseBaseEntity__Update"
    assert "was KynapseBaseEntity__vfunc_05" in rows["48a6a4"][3]
    assert rows["48c2fa"][3].startswith("medium: ") and "inferred" in rows["48c2fa"][3]
    assert "Node::GetVisible" in rows["48e01b"][3]
    assert "GetFlatDataModeSearchRadius" in rows["514581"][3]
    addrs = [int(a, 16) for a in rows]
    assert addrs == sorted(addrs)
    assert len({r[1] for r in rows.values()}) == len(rows)  # no name twice


def test_fx_table_no_longer_lists_the_fake_weapon_as_open():
    assert not any("fake weapon" in s for s in fx_meta._NOT_ESTABLISHED)
    note = fx_meta.damage_rule()["twilight_lady_fake_weapon"]
    assert "0x6943b8" in note and "null in shipped data" in note
    assert "inferred" in note  # the never-taken TASER branch stays an inference
    assert kp.name_hash("g_efaketwilightladyweapon") == kp.name_hash("G_EFAKETWILIGHTLADYWEAPON")
