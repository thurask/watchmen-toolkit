"""Path data (.hpd) fields settled by the open-items sweep.

Path-object flags   0x92d380, 0x92dfa0, SetIsImpassable 0x48a559
Mesh-link gate      trace 0x9104d8-0x910506: crossed when dir.x*f0 + dir.z*f2 > f1
Run-time overrides  AIBrainNode values written over the definition (0x4898f6, 0x489c1b,
                    0x934630, 0x934650)
Synthetic fixtures only (the builders of test_nav_data)."""

import os, sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import nav_data as nd
import test_nav_data as tn


def _doc():
    h = nd.parse_hpd(tn.demo_hpd())
    return nd.build_document(h, nd.parse_aipathdata(tn.make_aipathdata()), "Demo", {"hpd": "d"})


def test_path_object_flags_are_decoded():
    assert nd.path_object_flags(8) == {
        "dynamic": False,
        "per_entity_bits": False,
        "initially_passable": True,
    }
    assert nd.path_object_flags(1)["dynamic"] is True
    assert nd.path_object_flags(4)["per_entity_bits"] is True
    assert nd.path_object_flags(2)["per_entity_bits"] is False  # bits 1-2 must equal 2
    assert nd.path_object_flags(6)["per_entity_bits"] is False
    po = _doc()["path_objects"][0]
    assert po["flags"] == 8 and po["flags_decoded"]["initially_passable"] is True
    assert "0x92d380" in nd.EVIDENCE["path_object.flags"]
    assert "unknown" not in nd.EVIDENCE["path_object.flags"]


def test_mesh_link_gate_and_crossable():
    gate, ok = nd.mesh_link_gate((0.5, 0.25, -0.5))
    assert gate == {"dir_x": -0.5, "min_dot": 0.25, "dir_z": -0.5} and ok is True
    assert nd.mesh_link_gate((0.0, 1.0, 0.0))[1] is False  # zero direction, min_dot 1
    assert nd.mesh_link_gate((0.0, 0.5, 0.0))[1] is True  # not the closed record
    assert nd.mesh_link_gate((1.0, 0.0, 0.0))[0]["dir_x"] == -1.0  # the default record
    doc = _doc()
    link = doc["cells"][0]["mesh"]["floors"][0]["mesh_links"][0]
    assert "unk" not in link
    assert link["gate"] == {"dir_x": 0.0, "min_dot": 1.0, "dir_z": 0.0}
    assert link["crossable"] is False
    assert doc["summary"]["mesh"]["mesh_links"] == 1
    assert doc["summary"]["mesh"]["mesh_links_never_crossable"] == 1
    assert "0x9104d8" in nd.EVIDENCE["floor.mesh_links[].gate"]


def test_unknown_field_list_and_evidence_follow_the_code():
    doc = _doc()
    unk = doc["coverage"]["fields_of_unknown_meaning"]
    assert not any("path-object flags" in u or "trailing floats" in u for u in unk)
    assert any(u.startswith("mesh +0x30") for u in unk)
    assert doc["cells"][0]["mesh"]["unk_30"] == pytest.approx(-0.707106)  # name kept
    assert nd.EVIDENCE["mesh.sector"].startswith("measured on data; equality use read in code")
    assert "0x918b13" in nd.EVIDENCE["mesh.unk_30"]


def test_runtime_overrides_are_listed_beside_the_definition():
    doc = _doc()
    ov = doc["config_runtime_overrides"]
    assert [o["code"] for o in ov] == ["0x4898f6", "0x489c1b", "0x934630", "0x934650"]
    assert ov[0]["definition_path"] == "Services/CharacterPathfinder/FlatDataModeSearchRadius"
    assert ov[0]["overridden_by"] == "AIBrainNode.pathSearchRadius"
    assert all("value_in_file" not in o for o in ov)
    assert "runtime_overrides" not in doc["config"]  # config stays the summary
    h = nd.parse_hpd(tn.demo_hpd())
    assert "config_runtime_overrides" not in nd.build_document(h, None, "Demo", {})
