"""Asset strings of the tables, the loose-file cases (wlib/canonical_names.py).

    files/data    a string that names a loose file of the game folder (a movie)
                  is looked up below files/data/ and respelled like any other
    graph label   the movie path after "MOVIE " in a label is respelled too
    levelmeta     both are counted in asset_names.respelled of the level file
    particle index  has asset_names like the other tables; `respelled` counts the
                  strings written in another spelling than the files store

Synthetic fixtures only."""

import json
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import canonical_names as cn
import level_meta as lm
import particle_meta as pm

import test_p8_canonical_names as p8

STORED = "/Art/cutscenes/Cutscene10A.bik"
WRITTEN = "/art/cutscenes/cutscene10a.bik"


@pytest.fixture(autouse=True)
def names_mode(monkeypatch):
    monkeypatch.delenv("WATCHMEN_NAMES", raising=False)
    cn.end()
    yield
    cn.end()


def _export(root):
    ex = p8._export(root)
    for rel in (
        "files/data/art/cutscenes/cutscene10a.bik",
        "files/data/art/cutscenes/cutscene10b.bik",
        "files/derived_pc/art/cutscenes/Other.bik",
    ):
        (ex / rel).parent.mkdir(parents=True, exist_ok=True)
        (ex / rel).write_bytes(b"x")
    return ex


def test_a_movie_string_finds_its_file_below_files_data(tmp_path):
    ix = cn.ExportIndex(str(_export(tmp_path)))
    assert cn.REF_TREES.index("files/data") < cn.REF_TREES.index("files")
    assert ix.find(STORED) == ("files/data", "art/cutscenes/cutscene10a.bik")
    assert ix.spell(STORED) == WRITTEN
    assert ix.spell(WRITTEN) is WRITTEN
    assert cn.resolve(str(tmp_path), STORED) == "files/data/art/cutscenes/cutscene10a.bik"
    assert os.path.isfile(os.path.join(str(tmp_path), cn.resolve(str(tmp_path), STORED, ix)))
    # a string that spells the data/ folder itself still names the file below files/
    assert ix.find("/Data/Art/Cutscenes/CUTSCENE10A.bik") == (
        "files",
        "data/art/cutscenes/cutscene10a.bik",
    )
    assert ix.find("/data/Levels/T/Gameplay/T.hpd") == ("files", "data/levels/t/gameplay/t.hpd")
    # a file of another folder below files/ is not named without that folder
    assert ix.find("/art/cutscenes/other.bik") is None
    assert ix.spell("/Art/cutscenes/Missing.bik") == "/Art/cutscenes/Missing.bik"


def test_respell_keeps_the_stored_movie_string(tmp_path):
    ix = cn.ExportIndex(str(_export(tmp_path)))
    doc = {"movies": {"scope": {"m": {"movie": STORED, "continue_link": {"movie": STORED}}}}}
    assert cn.respell(doc, ix) == 2
    rec = doc["movies"]["scope"]["m"]
    assert rec["movie"] == WRITTEN and rec["stored"] == {"movie": STORED}
    assert rec["continue_link"] == {"movie": WRITTEN, "stored": {"movie": STORED}}
    assert cn.respell(doc, ix) == 0


def test_the_path_after_a_prefix_is_respelled(tmp_path):
    ix = cn.ExportIndex(str(_export(tmp_path)))
    doc = {
        "graph": {
            "nodes": [
                {"uid": 1, "label": "MOVIE /Art/cutscenes/Cutscene10B.bik"},
                {"uid": 2, "label": "MOVIE /art/cutscenes/cutscene10b.bik"},  # as written
                {"uid": 3, "label": "MOVIE None"},
                {"uid": 4, "label": "CHECKPOINT /Art/cutscenes/Cutscene10B.bik"},
                {"uid": 5, "label": "MOVIE /Art/cutscenes/Nowhere.bik"},
                {"uid": 6, "label": 7},
                {"uid": 7, "label": "MOVIE /Art/cutscenes/Cutscene10A.bik", "stored": "own"},
            ]
        },
        "stored": {"label": "MOVIE /Art/cutscenes/Cutscene10B.bik"},
        "asset_names": {"label": "MOVIE /Art/cutscenes/Cutscene10B.bik"},
    }
    before = json.loads(json.dumps(doc))
    assert cn.respell_after(doc, ix, "label", "MOVIE ") == 1
    n = doc["graph"]["nodes"]
    assert n[0] == {
        "uid": 1,
        "label": "MOVIE /art/cutscenes/cutscene10b.bik",
        "stored": {"label": "MOVIE /Art/cutscenes/Cutscene10B.bik"},
    }
    assert n[1:] == before["graph"]["nodes"][1:]
    assert doc["stored"] == before["stored"] and doc["asset_names"] == before["asset_names"]
    assert cn.respell_after(doc, ix, "label", "MOVIE ") == 0  # a second pass changes nothing
    # beside a field respell() already noted in the same record
    rec = {"label": "MOVIE " + STORED, "movie": STORED}
    assert cn.respell(rec, ix) == 1 and cn.respell_after(rec, ix, "label", "MOVIE ") == 1
    assert rec["stored"] == {"movie": STORED, "label": "MOVIE " + STORED}


def _level(_scene, name, _nid, _extract_out):
    return {
        "level": name,
        "movies": {"scope": {"m_ecutscenemovie": {"movie": STORED}}, "actions": []},
        "graph": {"nodes": [{"uid": 9, "label": "MOVIE " + STORED}, {"uid": 10, "label": "DELAY"}]},
        "models": [{"models": ["/ART/props/crate.model"]}],
        "counts": {
            k: 0
            for k in (
                "nodes",
                "characters",
                "models",
                "conditions",
                "actions",
                "checkpoints",
                "unresolved",
            )
        },
    }


def test_levelmeta_respells_movies_and_counts_them(tmp_path, monkeypatch):
    ex = _export(tmp_path / "ex")
    monkeypatch.setattr(lm, "levels", lambda e: [("s.scene", "T", 1, "/levels/t")])
    monkeypatch.setattr(lm, "build_level", _level)
    lm.write(str(ex), str(tmp_path / "out"), log=None)
    j = json.loads((tmp_path / "out" / "T.level.json").read_text(encoding="utf-8"))
    rec = j["movies"]["scope"]["m_ecutscenemovie"]
    assert rec == {"movie": WRITTEN, "stored": {"movie": STORED}}
    assert j["graph"]["nodes"][0] == {
        "uid": 9,
        "label": "MOVIE " + WRITTEN,
        "stored": {"label": "MOVIE " + STORED},
    }
    assert j["graph"]["nodes"][1] == {"uid": 10, "label": "DELAY"}
    assert j["models"][0]["models"] == ["/art/props/Crate.model"]
    # the model, the movie and the label
    assert j["asset_names"]["respelled"] == 3 and j["asset_names"]["spelling"] == "export"
    assert "files/data/" in j["asset_names"]["note"]
    # every respelled string names a file of the export, in its own letter case
    for ref in (rec["movie"], j["graph"]["nodes"][0]["label"][len("MOVIE ") :]):
        assert os.path.isfile(os.path.join(str(ex), "files", "data", *ref.strip("/").split("/")))


def test_levelmeta_names_stored_keeps_every_string(tmp_path, monkeypatch):
    ex = _export(tmp_path / "ex")
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    monkeypatch.setattr(lm, "levels", lambda e: [("s.scene", "T", 1, "/levels/t")])
    monkeypatch.setattr(lm, "build_level", _level)
    lm.write(str(ex), str(tmp_path / "out"), log=None)
    j = json.loads((tmp_path / "out" / "T.level.json").read_text(encoding="utf-8"))
    assert j == _level(None, "T", None, None)


# ------------------------------------------------------------------ particle index
def test_the_particle_index_has_asset_names(tmp_path):
    x360 = p8.FIRE % "Fire_01.bmp"
    canon = p8.FIRE % "Fire_01.BMP"
    index, _docs = pm.build(str(p8._particle_extract(tmp_path / "x", x360)))
    names = index["asset_names"]
    assert list(index)[-1] == "asset_names"
    assert names == {"spelling": "export", "respelled": 3, "note": pm.NAMES_NOTE}
    # the three: the type row, the file row's list, the key of `textures`
    row = index["files"][0]
    assert row["type_list"][0]["stored"] == {"texture": x360}
    assert row["stored"] == {"textures": [x360]} and row["textures"] == [canon]
    assert index["textures"][canon]["stored_name"] == [x360]
    assert pm.respelled(index) == 3
    # nothing respelled: the entry is there and says 0
    pc, _ = pm.build(str(p8._particle_extract(tmp_path / "p", canon)))
    assert pc["asset_names"]["respelled"] == 0 and pc["asset_names"]["spelling"] == "export"


def test_the_particle_index_with_names_stored_has_no_asset_names(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    x360 = p8.FIRE % "Fire_01.bmp"
    index, _docs = pm.build(str(p8._particle_extract(tmp_path, x360)))
    assert "asset_names" not in index and list(index["textures"]) == [x360]
    assert pm.respelled(index) == 0


def test_respelled_counts_strings_not_rows():
    index = {
        "files": [
            {
                "textures": ["/a/B.bmp", "/a/C.bmp", "/a/d.bmp"],
                "models": [],
                "stored": {"textures": ["/a/b.bmp", "/a/c.bmp", "/a/d.bmp"]},
                "type_list": [
                    {"texture": "/a/B.bmp", "model": None, "stored": {"texture": "/a/b.bmp"}},
                    {"texture": "/a/C.bmp", "model": None, "stored": {"texture": "/a/c.bmp"}},
                    {"texture": "/a/d.bmp", "model": None},
                ],
            },
            {"file": "broken.particle", "parsed": False},
        ],
        "textures": {"/a/B.bmp": {"stored_name": ["/a/b.bmp"]}, "/a/d.bmp": {}},
        "models": {"/m/X.model": {"stored_name": ["/m/x.model", "/M/x.model"]}},
    }
    # 2 strings of the file row's list, 2 type rows, 2 keys
    assert pm.respelled(index) == 6
