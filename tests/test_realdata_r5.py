"""Found on the real-data run of export r5 (case-sensitive file system)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "wlib"))

import characters_export as ce  # noqa: E402


def test_tw_weapon_found_when_reference_case_differs(tmp_path, monkeypatch):
    """Bs2CharVisual names '/Art/Characters/.../TW_weapon.model'; the extract has
    'art/characters/...'.  On a case-sensitive file system the whip was dropped."""
    mdir = tmp_path / "extracted" / "art" / "characters" / "twilightlady" / "models"
    mdir.mkdir(parents=True)
    (mdir / "TW_weapon.model").write_bytes(b"")
    doc = {
        "nodes_full": [
            {"id": 1, "props": [("attachedBone", "integer", 7)]},
            {
                "id": 2,
                "props": [
                    (
                        "modelNames",
                        "strings",
                        ["/Art/Characters/twilightlady/models/TW_weapon.model"],
                    ),
                    ("logicalParent", "ref", {"ref": 1}),
                    ("localPos", "vector", [0.1, 0.2, 0.3]),
                ],
            },
        ]
    }
    monkeypatch.setattr(ce, "_find_fragment", lambda root, stem: "Bs2CharVisual.fragment")
    monkeypatch.setattr(ce, "_load_fragment", lambda path: doc)
    spec = ce._tw_weapon_spec(str(tmp_path), ["Root"])
    assert spec is not None
    base, slot, (pos, quat) = spec
    assert os.path.samefile(base + ".model", str(mdir / "TW_weapon.model"))
    assert slot == 7 and pos == [0.1, 0.2, 0.3] and quat == [0, 0, 0, 1]


def test_tw_weapon_none_when_model_absent(tmp_path, monkeypatch):
    (tmp_path / "extracted").mkdir()
    doc = {
        "nodes_full": [{"id": 2, "props": [("modelNames", "strings", ["/Art/x/TW_weapon.model"])]}]
    }
    monkeypatch.setattr(ce, "_find_fragment", lambda root, stem: "Bs2CharVisual.fragment")
    monkeypatch.setattr(ce, "_load_fragment", lambda path: doc)
    assert ce._tw_weapon_spec(str(tmp_path), ["Attach RHand"]) is None
