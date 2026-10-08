"""particle_meta / `watchmen particlemeta`: every `.particle` of an extract as JSON + index.

Synthetic files only: trees written with particle_asset.build (its grammar is pinned in
test_particle_asset.py against bytes built by hand).
"""

import json

import pytest

import kapow_json as kj
import particle_asset as pa
import particle_meta as pm


def P(name, typ, value):
    return {"name": name, "type": typ, "value": value}


def O(cls, oid, *props):
    return {"class": cls, "id": "%08x" % oid, "props": list(props)}


def ptype(oid, name, texture, extra=(), affectors=(), spawners=(), initializers=()):
    t = O(
        "ParticleType",
        oid,
        P("name", "string", name),
        P("texture", "string", texture),
        *extra,
    )
    t["affectors"] = list(affectors)
    t["spawners"] = list(spawners)
    t["initializers"] = list(initializers)
    return t


def system(order="<", duration=2.5, loop=False, types=(), layout="typed"):
    tree = {
        "byte_order": "little" if order == "<" else "big",
        "record_layout": layout,
        "system": O(
            "ParticleSystemAsset",
            0x10,
            P("duration", "number", duration),
            P("loop", "truth", loop),
        ),
        "types": list(types),
    }
    return pa.build(tree)


def sparks(order="<"):
    return system(
        order,
        types=[
            ptype(
                0x20,
                "Spark",
                "/Art/Effects/Sparks/Spark.bmp",
                extra=[
                    P("blendMode", "integer", 1),
                    P("maxParticles", "integer", 12),
                    P("particleLife", "number", 0.5),
                    P("particleSize", "number", 0.25),
                ],
                affectors=[O("GrowthAffector", 0x21, P("growth", "number", 1.0))],
                spawners=[O("BurstSpawner", 0x22, P("minBurstAmount", "integer", 3))],
                initializers=[
                    O("UVArrayInitializer", 0x23, P("numX", "integer", 4), P("numY", "integer", 2))
                ],
            ),
            ptype(
                0x30,
                "Smoke",
                "/art/effects/smoke/Smoke.bmp",
                extra=[P("particleLife", "number", 3.0), P("renderStyle", "integer", 7)],
                spawners=[O("RegularSpawner", 0x31)],
            ),
        ],
    )


def glow():
    """One type without a texture (null string) that names a model; a looping system."""
    return system(
        loop=True,
        duration=1.0,
        types=[
            ptype(
                0x40,
                "",
                None,
                extra=[
                    P("model", "string", "/Art/Props/Rock.model"),
                    P("renderStyle", "integer", 1),
                ],
            )
        ],
    )


@pytest.fixture
def extract(tmp_path):
    """An `extract` output: extracted/ with three .particle files (one big-endian), a
    carved texture for one of the two textures, the model one type names, and files
    the command must not touch."""
    ex = tmp_path / "EX"
    d = ex / "extracted" / "art" / "Effects"
    d.mkdir(parents=True)
    (d / "Sparks.particle").write_bytes(sparks())
    (d / "sparks_be.PARTICLE").write_bytes(sparks(">"))
    (ex / "extracted" / "particles").mkdir()
    (ex / "extracted" / "particles" / "Glow.particle").write_bytes(glow())
    (d / "Sparks.particle.json").write_text("{}")  # a stale sidecar: not an input
    (d / "notes.txt").write_text("x")
    tex = ex / "textures" / "art" / "effects" / "sparks" / "spark.bmp"  # other case
    tex.mkdir(parents=True)
    (tex / "0_diffuse_64x64_DXT5.png").write_bytes(b"png")
    (tex / "sheet.json").write_text("{}")
    (ex / "extracted" / "art" / "props").mkdir()
    (ex / "extracted" / "art" / "props" / "rock.model").write_bytes(b"m")
    # outside extracted/: never walked
    (ex / "characters").mkdir()
    (ex / "characters" / "Stray.particle").write_bytes(b"junk")
    return ex


def test_find_particles_walks_only_extracted_in_stable_order(extract):
    root, found = pm.find_particles(str(extract))
    assert root == str(extract / "extracted")
    assert [rel for _p, rel in found] == [
        "art/Effects/Sparks.particle",
        "art/Effects/sparks_be.PARTICLE",
        "particles/Glow.particle",
    ]
    # the extracted folder itself, and a single file
    assert [r for _p, r in pm.find_particles(str(extract / "extracted"))[1]] == [
        r for _p, r in found
    ]
    one = extract / "extracted" / "particles" / "Glow.particle"
    assert pm.find_particles(str(one)) == (str(one.parent), [(str(one), "Glow.particle")])


def test_write_per_file_json_is_what_extract_writes(extract, tmp_path):
    out = tmp_path / "OUT"
    index = pm.write(str(extract), str(out), log=None)
    written = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert written == [
        "art/Effects/Sparks.particle.json",
        "art/Effects/sparks_be.PARTICLE.json",
        "index.json",
        "particles/Glow.particle.json",
    ]
    for row in index["files"]:
        src = (extract / "extracted" / row["file"]).read_bytes()
        text = (out / row["json"]).read_text(encoding="utf-8")
        # byte for byte the extractor's sidecar, and the tree of particle_asset.to_json
        assert text == json.dumps(kj.to_json(row["file"].lower(), src), indent=1)
        doc = json.loads(text)
        assert doc == json.loads(json.dumps(pa.to_json(src)))
        assert doc["format"] == pa.FORMAT == "kapow-particle/2"
        assert pa.build(doc) == src
    assert json.loads((out / "index.json").read_text(encoding="utf-8")) == index
    # the extract is left alone
    assert (extract / "extracted" / "art" / "Effects" / "Sparks.particle.json").read_text() == "{}"


def test_index_rows(extract):
    index, docs = pm.build(str(extract))
    assert index["format"] == pm.FORMAT == "watchmen-particle-meta/1"
    assert index["particle_format"] == "kapow-particle/2"
    assert set(index["evidence"]) >= {"files", "values", "textures", "roundtrip"}
    assert set(docs) == {r["file"] for r in index["files"]}
    rows = {r["file"]: r for r in index["files"]}
    s = rows["art/Effects/Sparks.particle"]
    assert s["asset"] == "/art/Effects/Sparks.particle"
    assert s["json"] == "art/Effects/Sparks.particle.json"
    assert s["bytes"] == len(sparks())
    assert (s["parsed"], s["roundtrip"]) == (True, True)
    assert (s["byte_order"], s["record_layout"]) == ("little", "typed")
    assert (s["emit_duration_s"], s["loop"]) == (2.5, False)
    assert (s["types"], s["objects"]) == (2, 7)
    assert s["particle_life_s_max"] == 3.0
    assert s["max_particles_total"] == 12 + 50  # Smoke stores none: constructor default 50
    # a string is spelled as the folder it names is written; the file's own beside it
    assert s["textures"] == ["/art/effects/smoke/Smoke.bmp", "/art/effects/sparks/spark.bmp"]
    assert s["stored"] == {
        "textures": ["/art/effects/smoke/Smoke.bmp", "/Art/Effects/Sparks/Spark.bmp"]
    }
    assert s["models"] == []
    assert s["classes"] == {
        "BurstSpawner": 1,
        "GrowthAffector": 1,
        "ParticleSystemAsset": 1,
        "ParticleType": 2,
        "RegularSpawner": 1,
        "UVArrayInitializer": 1,
    }
    assert (s["unknown_classes"], s["unknown_properties"], s["ignored_records"]) == (0, 0, 0)
    spark, smoke = s["type_list"]
    assert spark == {
        "index": 0,
        "name": "Spark",
        "texture": "/art/effects/sparks/spark.bmp",
        "model": None,
        "render_style": "Billboard",  # absent: constructor default 0
        "blend_mode": "Additive",
        "alignment": "Camera",
        "simulation_mode": "World space",
        "max_particles": 12,
        "particle_life_s": 0.5,
        "particle_size_m": 0.25,
        "start_time_s": 0.0,
        "end_time_s": 1.0,
        "affectors": ["GrowthAffector"],
        "spawners": ["BurstSpawner"],
        "initializers": ["UVArrayInitializer"],
        "uv_grid": {"x": 4, "y": 2, "from": "UVArrayInitializer"},
        "stored": {"texture": "/Art/Effects/Sparks/Spark.bmp"},
    }
    assert "stored" not in smoke  # names nothing in the tree: as the file stores it
    assert smoke["render_style"] == 7  # not a dropdown item: the number is kept
    assert smoke["blend_mode"] == "Normal"
    assert "uv_grid" not in smoke
    assert smoke["spawners"] == ["RegularSpawner"] and smoke["affectors"] == []
    be = rows["art/Effects/sparks_be.PARTICLE"]
    assert be["byte_order"] == "big" and be["roundtrip"] is True
    assert be["type_list"] == s["type_list"]
    g = rows["particles/Glow.particle"]
    assert (g["loop"], g["emit_duration_s"], g["types"]) == (True, 1.0, 1)
    assert g["textures"] == [] and g["models"] == ["/art/props/rock.model"]
    assert g["stored"] == {"models": ["/Art/Props/Rock.model"]}
    assert g["type_list"][0]["texture"] is None
    assert g["type_list"][0]["render_style"] == "Model"
    assert g["particle_life_s_max"] == 1.0  # constructor default
    c = index["counts"]
    assert (c["files"], c["parsed"], c["failed"], c["roundtrip_exact"]) == (3, 3, 0, 3)
    assert (c["types"], c["objects"], c["looping"]) == (5, 16, 1)
    assert c["byte_order"] == {"big": 1, "little": 2}
    assert c["record_layout"] == {"typed": 3}
    assert index["classes"]["ParticleType"] == 5
    assert index["errors"] == []


def test_references_resolved_against_the_extract(extract, tmp_path):
    index, _docs = pm.build(str(extract))
    assert index["texture_tree"] == "textures"
    assert list(index["textures"]) == [
        "/art/effects/smoke/Smoke.bmp",
        "/art/effects/sparks/spark.bmp",
    ]
    spark = index["textures"]["/art/effects/sparks/spark.bmp"]
    assert spark == {
        "found": True,
        "dir": "art/effects/sparks/spark.bmp",  # the key is this path
        "images": ["0_diffuse_64x64_DXT5.png"],
        "used_by": ["art/Effects/Sparks.particle", "art/Effects/sparks_be.PARTICLE"],
        "stored_name": ["/Art/Effects/Sparks/Spark.bmp"],  # found although the case differs
    }
    smoke = index["textures"]["/art/effects/smoke/Smoke.bmp"]
    assert (smoke["found"], smoke["dir"], smoke["images"]) == (False, None, [])
    assert index["models"] == {
        "/art/props/rock.model": {
            "found": True,
            "file": "art/props/rock.model",
            "used_by": ["particles/Glow.particle"],
            "stored_name": ["/Art/Props/Rock.model"],
        }
    }
    c = index["counts"]
    assert (c["textures"], c["textures_found"], c["models"], c["models_found"]) == (2, 1, 1, 1)
    assert "1 of 2 textures found" in pm.summary(index)
    # the same answers from the extracted folder itself (textures/ is its sibling)
    assert pm.build(str(extract / "extracted"))[0]["textures"] == index["textures"]
    # another texture tree, given explicitly
    other = tmp_path / "tex2" / "Art" / "Effects" / "Smoke" / "Smoke.bmp"
    other.mkdir(parents=True)
    (other / "0_diffuse_8x8_DXT1.png").write_bytes(b"p")
    i2 = pm.build(str(extract), textures=str(tmp_path / "tex2"))[0]
    assert i2["texture_tree"] == "tex2"
    # the string follows the tree it is looked up in
    assert i2["textures"]["/Art/Effects/Smoke/Smoke.bmp"] == {
        "found": True,
        "dir": "Art/Effects/Smoke/Smoke.bmp",
        "images": ["0_diffuse_8x8_DXT1.png"],
        "used_by": ["art/Effects/Sparks.particle", "art/Effects/sparks_be.PARTICLE"],
        "stored_name": ["/art/effects/smoke/Smoke.bmp"],
    }
    assert i2["textures"]["/Art/Effects/Sparks/Spark.bmp"]["found"] is False
    # no texture tree at all: named, not found, and the summary says why
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "A.particle").write_bytes(sparks())
    i3 = pm.build(str(bare))[0]
    assert i3["texture_tree"] is None and i3["counts"]["textures_found"] == 0
    assert "no texture tree" in pm.summary(i3)


def test_texture_lookup_never_leaves_the_tree(tmp_path):
    (tmp_path / "secret.bmp").mkdir()
    tree = tmp_path / "textures"
    tree.mkdir()
    assert pm._lookup(str(tree), "/../secret.bmp") is None
    assert pm._lookup(str(tree), "") is None and pm._lookup(str(tree), None) is None
    assert pm._lookup(None, "/a.bmp") is None


def test_untyped_part1_layout_is_indexed(tmp_path):
    (tmp_path / "old.particle").write_bytes(
        system(types=[ptype(0x20, "Dust", "/Art/Dust.bmp")], layout="untyped")
    )
    index = pm.build(str(tmp_path))[0]
    row = index["files"][0]
    assert (row["record_layout"], row["roundtrip"], row["types"]) == ("untyped", True, 1)
    assert index["counts"]["record_layout"] == {"untyped": 1}


def test_broken_file_is_reported_and_still_written(extract, tmp_path):
    bad = extract / "extracted" / "particles" / "Cut.particle"
    bad.write_bytes(sparks()[:-9])
    out = tmp_path / "OUT"
    lines = []
    index = pm.write(str(extract), str(out), log=lines.append)
    c = index["counts"]
    assert (c["files"], c["parsed"], c["failed"], c["roundtrip_exact"]) == (4, 3, 1, 3)
    row = [r for r in index["files"] if r["file"] == "particles/Cut.particle"][0]
    assert row["parsed"] is False and "truncated" in row["error"]
    assert index["errors"] == [{"file": "particles/Cut.particle", "error": row["error"]}]
    assert any("Cut.particle" in ln for ln in lines)
    doc = json.loads((out / "particles" / "Cut.particle.json").read_text())
    assert "format" not in doc and "not a complete .particle tree" in doc["warn"][-1]


def test_no_particles_raises(tmp_path):
    (tmp_path / "extracted").mkdir()
    with pytest.raises(FileNotFoundError):
        pm.build(str(tmp_path))
    assert not (tmp_path / "OUT").exists()


def test_output_is_deterministic(extract, tmp_path):
    a, b = tmp_path / "A", tmp_path / "B"
    pm.write(str(extract), str(a), log=None)
    pm.write(str(extract), str(b), log=None)
    for p in sorted(x for x in a.rglob("*") if x.is_file()):
        assert p.read_bytes() == (b / p.relative_to(a)).read_bytes()
    assert b"\r" not in (a / "index.json").read_bytes()


def test_particlemeta_command(extract, tmp_path, capsys):
    import watchmen

    assert "particlemeta" in watchmen.USAGE and "particlemeta EXTRACT_OUT" in watchmen.__doc__
    out = tmp_path / "OUT"
    assert watchmen.main(["watchmen", "particlemeta", str(extract), str(out)]) == 0
    said = capsys.readouterr().out
    assert "3 particle files (3 parsed, 3 rebuild byte-exact), 5 types" in said
    index = json.loads((out / "index.json").read_text())
    assert index["format"] == "watchmen-particle-meta/1" and index["counts"]["files"] == 3
    assert (out / "art" / "Effects" / "Sparks.particle.json").is_file()
    # explicit texture tree
    tex2 = tmp_path / "tex2"
    tex2.mkdir()
    out2 = tmp_path / "OUT2"
    assert watchmen.main(["watchmen", "particlemeta", str(extract), str(out2), str(tex2)]) == 0
    assert json.loads((out2 / "index.json").read_text())["texture_tree"] == "tex2"
    capsys.readouterr()
    # usage and error paths
    assert watchmen.main(["watchmen", "particlemeta", str(extract)]) == 2
    assert "particlemeta EXTRACT_OUT OUT_DIR [TEXTURES_DIR]" in capsys.readouterr().out
    assert watchmen.main(["watchmen", "particlemeta", "-h"]) == 0
    assert watchmen.main(["watchmen", "particlemeta", str(tmp_path / "nope"), str(out)]) == 2
    assert watchmen.main(["watchmen", "particlemeta", str(extract), str(out), "nodir"]) == 2
    empty = tmp_path / "empty"
    empty.mkdir()
    assert watchmen.main(["watchmen", "particlemeta", str(empty), str(tmp_path / "O3")]) == 1
    assert not (tmp_path / "O3").exists()
    # a broken file: written, reported, exit status 1
    (extract / "extracted" / "particles" / "Cut.particle").write_bytes(b"\x05\x00\x00\x00abc")
    assert watchmen.main(["watchmen", "particlemeta", str(extract), str(tmp_path / "O4")]) == 1
    assert json.loads((tmp_path / "O4" / "index.json").read_text())["counts"]["failed"] == 1
