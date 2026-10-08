"""One spelling for paths whose letter case differs between the archives
(`--names canonical|stored`, wlib/canonical_names.py, wlib/canonical_names.json).

    table         41 asset paths, keyed by the folded path of one component
    canonical()   a path in the table's spelling; anything else unchanged
    OutputNames   an asset is placed under its canonical name, the stored one is
                  recorded; a reference in another letter case follows the asset
    safe()        output components in the table's spelling, one spelling per folder
    extract       two archives that store the same assets in different letter case
                  give the same path list; _canonical_names.json, stored_name in
                  sheet.json and .model.json; --names stored keeps the archive's
    loose folder  the files from beside it are named in lower case, as in an archive
    particlemeta  texture strings of the index in the canonical spelling
    CLI           --names on the commands that write names

Synthetic fixtures only."""

import json
import pathlib
import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import canonical_names as cn
import nav_data as nd
import particle_meta as pm
import watchmen
import watchmen_extract as wx

import test_formats_v2 as tf
import test_p2_small as ps
import test_particlemeta as tp

GARBAGE = "/art/props/common/garbage/textures/%s"
CABLES = "/art/props/common/junction_boxes/textures/%s"
FIRE = "/art/Effects/Particles/Textures/%s"
#: the three Part 2 textures: (PC, PS3, Xbox 360) spelling and the canonical one
MEASURED = [
    (FIRE, ("Fire_01.BMP", "Fire_01.BMP", "Fire_01.bmp"), "Fire_01.BMP"),
    (
        GARBAGE,
        ("garbagepile_01.bmp", "GarbagePile_01.bmp", "garbagepile_01.bmp"),
        "GarbagePile_01.bmp",
    ),
    (CABLES, ("WallCables_03.bmp", "wallcables_03.bmp", "wallcables_03.bmp"), "WallCables_03.bmp"),
]


@pytest.fixture(autouse=True)
def names_mode(monkeypatch):
    """Every test starts in the default mode and leaves no run behind."""
    monkeypatch.delenv("WATCHMEN_NAMES", raising=False)
    cn.end()
    yield
    cn.end()


# ------------------------------------------------------------------ mode, table
def test_mode_is_canonical_unless_the_environment_says_stored(monkeypatch):
    assert cn.mode() == "canonical" and cn.is_canonical()
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    assert cn.mode() == "stored" and not cn.is_canonical()
    assert cn.mode("canonical") == "canonical"  # an explicit value wins
    monkeypatch.setenv("WATCHMEN_NAMES", "lower")
    with pytest.raises(ValueError, match="canonical, stored"):
        cn.mode()


def test_table_is_keyed_by_the_folded_path_of_one_component():
    with open(os.path.join(os.path.dirname(cn.__file__), "canonical_names.json")) as fh:
        doc = json.load(fh)
    assert doc["format"] == cn.FORMAT == "watchmen-canonical-names/1"
    names = cn.table()
    assert names == doc["names"] and len(names) == 41
    for key, spelling in names.items():
        assert key == cn.fold(key) and not key.startswith("/") and "\\" not in key
        # the value respells the key's last component and nothing else
        assert cn.fold(spelling) == key.rsplit("/", 1)[-1] and "/" not in spelling
    folders = sorted(k for k in names if "." not in k.rsplit("/", 1)[-1])
    assert [(k, names[k]) for k in folders] == [
        ("art/environments/common/decals", "Decals"),
        ("art/environments/constructionsite/textures", "Textures"),
        ("art/props/common/chains", "chains"),
        ("art/props/common/streetlines", "streetlines"),
    ]
    assert sum(1 for k in names if k.endswith(".bmp")) == 35
    assert sum(1 for k in names if k.endswith(".model")) == 2


def test_fold_touches_ascii_letters_only():
    assert cn.fold("/Art/Fire_01.BMP") == "/art/fire_01.bmp"
    assert cn.fold("\u00c4RGER_\u00dc 01") == "\u00c4rger_\u00dc 01"  # ASCII letters only
    assert cn.key("\\Art\\\\Props/X.bmp") == "art/props/x.bmp"


# ------------------------------------------------------------------ canonical()
@pytest.mark.parametrize("folder,stored,canon", MEASURED)
def test_the_three_part2_textures_get_the_part1_spelling(folder, stored, canon):
    for spelling in stored:
        assert cn.canonical(folder % spelling) == folder % canon
        assert cn.canonical((folder % spelling).upper()) == folder.upper().replace("%S", canon)
        # the material is named like the texture, whatever case the model stores
        assert str(wx.texture_ref(folder % spelling)) == canon.rsplit(".", 1)[0]
        assert wx.texture_ref(folder % spelling).path == folder % canon


def test_canonical_respells_folders_and_leaves_everything_else_alone():
    assert cn.canonical("/art/props/common/Chains/Chain_01.model") == (
        "/art/props/common/chains/Chain_01.model"
    )
    assert cn.canonical("art\\Environments\\Common\\decals\\x.bmp") == (
        "art/Environments/Common/Decals/x.bmp"
    )
    same = "/art/props/common/garbage/textures/Other_01.bmp"
    assert cn.canonical(same) is same  # not listed: the very string comes back
    back = "art\\T\\Wall.bmp"
    assert cn.canonical(back) is back  # separators are not rewritten either
    assert cn.canonical("") == "" and cn.canonical(None) is None
    # a longer path below a listed file name is not that file
    assert cn.canonical(GARBAGE % "garbagepile_01.bmp.stream") == (
        GARBAGE % "garbagepile_01.bmp.stream"
    )


def test_stored_mode_changes_nothing(monkeypatch):
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    name = GARBAGE % "garbagepile_01.bmp"
    assert cn.canonical(name) is name
    assert str(wx.texture_ref(name)) == "garbagepile_01" and wx.texture_ref(name).path == name
    assert cn.output_parts("/o/textures", ["art", "Decals", "x.bmp"]) == ["art", "Decals", "x.bmp"]
    assert cn.archive_name("data/Levels/Docks.hpd") == "data/Levels/Docks.hpd"
    assert cn.canonical(name, "canonical") == GARBAGE % "GarbagePile_01.bmp"


# ------------------------------------------------------------------ OutputNames
def test_output_names_place_an_asset_under_its_canonical_name():
    run = cn.begin()
    n = wx.OutputNames(run=run)
    stored = GARBAGE % "garbagepile_01.bmp"
    canon = GARBAGE % "GarbagePile_01.bmp"
    assert n.place(stored, "/l/streetsofriot.block", b"H", b"S") == (canon, "new")
    assert run.renamed == {canon: [stored]} and run.stored_of(canon) == stored
    # a later copy in the canonical spelling is the same asset, and no "twin"
    assert n.place(canon, "/l/tutorial.block", b"H", b"S") == (canon, "repeat")
    assert n.case_twins == [] and run.twins == {}
    # a third spelling is one
    third = GARBAGE % "GARBAGEPILE_01.bmp"
    assert n.place(third, "/l/x.block", b"H", b"S") == (canon, "repeat")
    assert n.case_twins == [(third, canon)] and run.twins == {canon: [third]}
    assert run.renamed == {canon: [stored]}  # only the copy that was written is "renamed"
    # other content still gets its own name, built on the canonical one
    variant = GARBAGE % "GarbagePile_01~y.bmp"
    assert n.place(stored, "/l/y.block", b"H2", b"S") == (variant, "variant")
    assert run.renamed == {canon: [stored], variant: [stored]}
    assert run.written == {cn.key(canon): canon}  # references follow the first copy
    assert run.stored_of("/art/x/Unlisted.bmp") is None


def test_a_later_copy_in_another_case_is_a_twin_not_a_rename():
    """Part 1 stores the canonical spelling first; a later block's copy in the Part 2
    spelling is the old "twin" and nothing was renamed."""
    run = cn.begin()
    n = wx.OutputNames(run=run)
    canon = "/art/props/common/rubble/Rubble_RoofTop_02.model"
    other = "/art/props/common/rubble/Rubble_Rooftop_02.model"
    assert n.place(canon, "/l/docks.block", b"H", b"S") == (canon, "new")
    assert n.place(other, "/l/streets.block", b"H", b"S") == (canon, "repeat")
    assert run.renamed == {} and run.twins == {canon: [other]}
    assert n.case_twins == [(other, canon)]


def test_output_names_without_a_run_keep_the_stored_name():
    n = wx.OutputNames()
    stored = GARBAGE % "garbagepile_01.bmp"
    assert n.place(stored, "/l/a.block", b"H", b"S") == (stored, "new")


def test_a_reference_in_another_case_follows_the_asset_that_was_written():
    """PC Part 2: TrashCan_03 names GarbagePile_01.bmp, the archive stores
    garbagepile_01.bmp; and for a name no table lists, the spelling written."""
    run = cn.begin()
    n = wx.OutputNames(run=run)
    n.place("/art/T/Wall_Cables.bmp", "/l/a.block", b"H", b"S")
    n.place(GARBAGE % "garbagepile_01.bmp", "/l/a.block", b"H", b"S")
    assert run.written["art/t/wall_cables.bmp"] == "/art/T/Wall_Cables.bmp"
    for ref in ("/art/t/wall_cables.bmp", "/ART/T/WALL_CABLES.BMP", "/art/T/Wall_Cables.bmp"):
        assert str(wx.texture_ref(ref)) == "Wall_Cables"
        assert wx.texture_ref(ref).path == "/art/T/Wall_Cables.bmp"
    assert str(wx.texture_ref(GARBAGE % "GARBAGEPILE_01.BMP")) == "GarbagePile_01"
    cn.end()  # outside an extract only the table applies
    assert str(wx.texture_ref("/art/t/wall_cables.bmp")) == "wall_cables"
    assert str(wx.texture_ref(GARBAGE % "garbagepile_01.bmp")) == "GarbagePile_01"


def test_texture_index_finds_the_folder_whatever_the_reference_spells(tmp_path):
    """The lookup itself never depended on letter case; the name now agrees too."""
    d = tmp_path / "textures" / "art" / "props" / "common" / "garbage" / "textures"
    (d / "GarbagePile_01.bmp").mkdir(parents=True)
    (d / "GarbagePile_01.bmp" / "0_diffuse_4x4_DXT1.png").write_bytes(b"x")
    idx = wx.build_texture_index(tmp_path / "textures")
    for spelling in ("garbagepile_01.bmp", "GarbagePile_01.bmp"):
        ref = wx.texture_ref(GARBAGE % spelling)
        assert idx.resolve(ref).name == "GarbagePile_01.bmp" == str(ref) + ".bmp"


# ------------------------------------------------------------------ safe()
def test_safe_uses_the_table_and_one_spelling_per_folder(tmp_path):
    base = tmp_path / "textures"
    rel = lambda p: p.relative_to(base).as_posix()
    assert rel(wx.safe(base, "/art/props/common/Chains/a.bmp")) == "art/props/common/chains/a.bmp"
    assert rel(wx.safe(base, GARBAGE % "garbagepile_01.bmp")).endswith("/GarbagePile_01.bmp")
    # folders: the first spelling written is kept, as on a case-insensitive file system
    assert rel(wx.safe(base, "/art/Walls/Brick/a.bmp")) == "art/Walls/Brick/a.bmp"
    assert rel(wx.safe(base, "/Art/walls/brick/B.bmp")) == "art/Walls/Brick/B.bmp"
    assert rel(wx.safe(base, "/art/WALLS/New/c.bmp")) == "art/Walls/New/c.bmp"
    # the file name itself is never respelled by that rule
    assert rel(wx.safe(base, "/art/Walls/Brick/A.BMP")) == "art/Walls/Brick/A.BMP"
    # every output tree has its own first spelling
    other = tmp_path / "models"
    assert wx.safe(other, "/ART/walls/x.obj").relative_to(other).as_posix() == "ART/walls/x.obj"
    assert cn.folder_spellings(tmp_path) == {
        "textures/art": ["Art"],
        "textures/art/Walls": ["WALLS", "walls"],
        "textures/art/Walls/Brick": ["brick"],
    }
    # still never leaves the base
    assert rel(wx.safe(base, "../../x/../Art/y")) == "x/Art/y"


def test_a_file_value_names_the_path_that_was_written(tmp_path, monkeypatch):
    """sound_info.json and the music sidecars: "file" follows the folder spelling
    of the tree, so it opens on a case-sensitive file system."""
    base = tmp_path / "audio"
    wx.safe(base, "/sounds/SFX/a.wav")
    assert wx.out_rel(base, "/sounds/sfx/b.wav") == "sounds/SFX/b.wav"
    assert wx.out_rel(str(base), "\\sounds\\Sfx\\c.wav") == "sounds/SFX/c.wav"
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    assert wx.out_rel(base, "/sounds/sfx/b.wav") == "sounds/sfx/b.wav"
    assert wx.out_rel(base, "\\sounds\\Sfx\\c.wav") == "sounds/Sfx/c.wav"


def test_safe_in_stored_mode_is_the_old_function(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    base = tmp_path / "t"
    assert wx.safe(base, "/art/Walls/a.bmp") == base / "art" / "Walls" / "a.bmp"
    assert wx.safe(base, "/ART/walls/b.bmp") == base / "ART" / "walls" / "b.bmp"
    assert wx.safe(base, "/art/props/common/Chains/a.bmp").parent.name == "Chains"
    assert cn.folder_spellings(tmp_path) == {}


# ------------------------------------------------------------------ extract
def _platform_tree(root, platform):
    """One level block that stores the three measured textures, a rubble model and
    a chain model in the letter case of `platform` (0 PC, 1 PS3, 2 Xbox 360), plus a
    second block that repeats the garbage pile as the fragments spell it."""
    tex, mdl = ps._cls("Texture", b"tex-hdr"), ps._cls("ModelRes", b"mdl-hdr")
    rows = [(f % s[platform], tf._TEX, tex, b"stream-of-" + c.encode()) for f, s, c in MEASURED]
    rows += [
        ("/art/props/common/rubble/Rubble_Rooftop_02.model", 1, mdl, b"rubble-stream"),
        (
            "/art/props/common/%s/Chain_01.model" % ("Chains", "chains", "CHAINS")[platform],
            1,
            mdl,
            b"chain-stream",
        ),
        ("/art/T/%s/Plain.bmp" % ("Walls", "walls", "WALLS")[platform], tf._TEX, tex, b"plain"),
    ]
    again = [(GARBAGE % "GarbagePile_01.bmp", tf._TEX, tex, b"stream-of-GarbagePile_01.bmp")]
    d = root / "files" / ("derived_pc", "derived_ps3", "derived_x360")[platform] / "levels"
    d.mkdir(parents=True)
    for nm, rws in (("a", rows), ("b", again)):
        h, s = tf._block(rws)
        (d / (nm + ".block_h_z")).write_bytes(h)
        (d / (nm + ".block_s_z")).write_bytes(s)
    return root / "files"


@pytest.fixture
def writers(monkeypatch):
    """main() with the two decoders replaced by ones that write one small file
    (and, for a model, the .model.json the real one writes)."""
    seen = {"mdl": {}}

    def carve(stream, header, out_dir, log=None):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "0_diffuse_4x4_DXT1.png").write_bytes(stream)
        if stream != b"plain":  # every texture but one has a sheet
            (out_dir / "sheet.json").write_text('{"twoSided": true}')
        return True

    def decode(header, stream, out_path, tex_index=None, log=None, order=None, lod=0, **kw):
        seen["mdl"][out_path.name] = kw
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(stream)
        return True

    monkeypatch.setattr(wx, "carve_texture", carve)
    monkeypatch.setattr(wx, "decode_model", decode)
    monkeypatch.setattr(wx, "HAVE_IMG", True)
    return seen


def _paths(out, skip=("files",)):
    got = []
    for dp, _dns, fns in os.walk(out):
        for f in fns:
            rel = os.path.relpath(os.path.join(dp, f), out).replace(os.sep, "/")
            if rel.split("/")[0] not in skip:
                got.append(rel)
    return sorted(got)


def _extract(tmp_path, platform, *more):
    files = _platform_tree(tmp_path / ("src%d" % platform), platform)
    out = tmp_path / ("out%d" % platform)
    assert wx.main([str(files), "-o", str(out), "--no-text", "--no-audio", "--no-nav", *more]) == 0
    return out


def test_extract_gives_three_archives_the_same_paths(tmp_path, writers, capsys):
    outs = [_extract(tmp_path, k) for k in range(3)]
    log = capsys.readouterr().out
    lists = [_paths(o) for o in outs]
    # the folder outside the table is spelled as each archive stores it; all else agrees
    assert [os.listdir(o / "textures" / "art" / "T") for o in outs] == [
        ["Walls"],
        ["walls"],
        ["WALLS"],
    ]
    assert [[p for p in lst if "/T/" not in p] for lst in lists] == [
        [p for p in lists[0] if "/T/" not in p]
    ] * 3
    base = lists[0]
    for want in (
        "_canonical_names.json",
        "extracted/art/Effects/Particles/Textures/Fire_01.BMP",
        "extracted/art/Effects/Particles/Textures/Fire_01.BMP.stream",
        "extracted/art/props/common/garbage/textures/GarbagePile_01.bmp",
        "extracted/art/props/common/junction_boxes/textures/WallCables_03.bmp.stream",
        "extracted/art/props/common/chains/Chain_01.model",
        "extracted/art/props/common/rubble/Rubble_RoofTop_02.model",
        "models/art/props/common/chains/Chain_01.model.obj",
        "models/art/props/common/rubble/Rubble_RoofTop_02.model.obj",
        "textures/art/props/common/garbage/textures/GarbagePile_01.bmp/0_diffuse_4x4_DXT1.png",
        "textures/art/Effects/Particles/Textures/Fire_01.BMP/0_diffuse_4x4_DXT1.png",
        "textures/art/props/common/junction_boxes/textures/WallCables_03.bmp/sheet.json",
    ):
        assert want in base, want
    assert not [p for p in base if "garbagepile" in p or "wallcables" in p or "Fire_01.bmp" in p]
    # what each archive stores is on record: the per-export file ...
    docs = [json.loads((o / cn.RUN_FILE).read_text(encoding="utf-8")) for o in outs]
    assert all(d["format"] == "watchmen-export-names/1" and d["names"] == "canonical" for d in docs)
    rubble = "/art/props/common/rubble/Rubble_RoofTop_02.model"
    assert docs[0]["renamed"] == {
        "/art/props/common/chains/Chain_01.model": ["/art/props/common/Chains/Chain_01.model"],
        GARBAGE % "GarbagePile_01.bmp": [GARBAGE % "garbagepile_01.bmp"],
        rubble: ["/art/props/common/rubble/Rubble_Rooftop_02.model"],
    }
    assert docs[1]["renamed"] == {
        CABLES % "WallCables_03.bmp": [CABLES % "wallcables_03.bmp"],
        rubble: ["/art/props/common/rubble/Rubble_Rooftop_02.model"],
    }
    assert sorted(docs[2]["renamed"]) == sorted(
        [
            FIRE % "Fire_01.BMP",
            "/art/props/common/chains/Chain_01.model",
            GARBAGE % "GarbagePile_01.bmp",
            CABLES % "WallCables_03.bmp",
            rubble,
        ]
    )
    assert docs[2]["renamed"][FIRE % "Fire_01.BMP"] == [FIRE % "Fire_01.bmp"]
    assert all(d["twins"] == {} and d["folders"] == {} for d in docs)
    # ... the texture's sidecar ...
    side = outs[0] / "textures/art/props/common/garbage/textures/GarbagePile_01.bmp/sheet.json"
    assert json.loads(side.read_text())["stored_name"] == GARBAGE % "garbagepile_01.bmp"
    fire = "textures/art/Effects/Particles/Textures/Fire_01.BMP/sheet.json"
    # PC stores the canonical spelling: no note
    assert json.loads((outs[0] / fire).read_text()) == {"twoSided": True}
    assert json.loads((outs[2] / fire).read_text()) == {
        "stored_name": FIRE % "Fire_01.bmp",
        "twoSided": True,
    }
    # ... and the model's
    assert writers["mdl"]["Rubble_RoofTop_02.model.obj"] == {
        "stored_name": "/art/props/common/rubble/Rubble_Rooftop_02.model"
    }
    assert "names       : 3 written under their canonical spelling" in log
    assert "names       : 5 written under their canonical spelling" in log
    assert "canonical -> stored in _canonical_names.json" in log
    assert "stored under a second spelling" not in log  # the second block's copy is no twin


def test_extract_names_stored_keeps_each_archives_spelling(tmp_path, writers, monkeypatch, capsys):
    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")  # --names overrides, and is restored
    outs = [_extract(tmp_path, k, "--names", "stored") for k in range(3)]
    assert os.environ["WATCHMEN_NAMES"] == "stored"
    log = capsys.readouterr().out
    pc, ps3, x360 = [_paths(o) for o in outs]
    assert "extracted/art/props/common/garbage/textures/garbagepile_01.bmp" in pc
    assert "extracted/art/props/common/garbage/textures/GarbagePile_01.bmp" in ps3
    assert "extracted/art/Effects/Particles/Textures/Fire_01.bmp" in x360
    assert "extracted/art/props/common/Chains/Chain_01.model" in pc
    assert "models/art/props/common/rubble/Rubble_Rooftop_02.model.obj" in pc
    assert len({tuple(pc), tuple(ps3), tuple(x360)}) == 3
    for o in outs:
        for dp, _dns, fns in os.walk(o / "textures"):
            if "sheet.json" in fns:
                assert json.loads(pathlib.Path(dp, "sheet.json").read_text()) == {"twoSided": True}
    assert all(kw == {} for kw in writers["mdl"].values())
    for o in outs:
        doc = json.loads((o / cn.RUN_FILE).read_text(encoding="utf-8"))
        assert doc["names"] == "stored" and doc["renamed"] == {} and doc["folders"] == {}
    # the second block's copy in the other case is the old "twin", written once
    doc = json.loads((outs[0] / cn.RUN_FILE).read_text(encoding="utf-8"))
    assert doc["twins"] == {GARBAGE % "garbagepile_01.bmp": [GARBAGE % "GarbagePile_01.bmp"]}
    assert "names       : 1 stored under a second spelling" in log
    assert "canonical spelling" not in log


def test_extract_writes_one_folder_where_assets_spell_it_two_ways(tmp_path, writers, capsys):
    tex = ps._cls("Texture", b"tex-hdr")
    rows = [
        ("/art/Walls/Brick.bmp", tf._TEX, tex, b"brick-stream"),
        ("/art/walls/Plaster.bmp", tf._TEX, tex, b"plaster-stream"),
        ("/Art/WALLS/Stone.bmp", tf._TEX, tex, b"stone-stream"),
    ]
    d = tmp_path / "files" / "derived_pc" / "levels"
    d.mkdir(parents=True)
    h, s = tf._block(rows)
    (d / "a.block_h_z").write_bytes(h)
    (d / "a.block_s_z").write_bytes(s)
    out = tmp_path / "out"
    args = [str(tmp_path / "files"), "-o", str(out), "--no-text", "--no-audio", "--no-nav"]
    assert wx.main(args + ["--no-files"]) == 0
    assert os.listdir(out / "textures") == ["art"] and os.listdir(out / "extracted") == ["art"]
    assert os.listdir(out / "textures" / "art") == ["Walls"]
    assert sorted(os.listdir(out / "textures" / "art" / "Walls")) == [
        "Brick.bmp",
        "Plaster.bmp",
        "Stone.bmp",
    ]
    doc = json.loads((out / cn.RUN_FILE).read_text(encoding="utf-8"))
    assert doc["renamed"] == {} and doc["folders"] == {
        "extracted/art": ["Art"],
        "extracted/art/Walls": ["WALLS", "walls"],
        "textures/art": ["Art"],
        "textures/art/Walls": ["WALLS", "walls"],
    }
    # the texture index of that tree resolves every spelling to the one folder
    idx = wx.build_texture_index(out / "textures")
    assert idx.resolve(wx.texture_ref("/ART/walls/STONE.bmp")).name == "Stone.bmp"
    assert "canonical spelling" not in capsys.readouterr().out


def test_decode_model_puts_the_stored_name_into_the_model_json(tmp_path):
    h, s = tf._lod_model()
    stored = "/art/props/common/rubble/Rubble_Rooftop_02.model"
    assert wx.decode_model(h, s, tmp_path / "m.obj", stored_name=stored) is True
    assert json.loads((tmp_path / "m.model.json").read_text())["stored_name"] == stored
    assert wx.decode_model(h, s, tmp_path / "n.obj") is True
    assert "stored_name" not in json.loads((tmp_path / "n.model.json").read_text())


def test_mark_stored_name_keeps_the_sheet(tmp_path):
    (tmp_path / "sheet.json").write_text('{"twoSided": true}')
    wx._mark_stored_name(tmp_path, "/art/x/wall.bmp")
    assert wx.read_sheet_json(tmp_path) == {"twoSided": True, "stored_name": "/art/x/wall.bmp"}
    # no sheet, no sidecar: two archives must not differ in the files of a folder
    other = tmp_path / "t"
    other.mkdir()
    wx._mark_stored_name(other, "/art/x/wall.bmp")
    wx._mark_stored_name(tmp_path, None)
    assert not (other / "sheet.json").exists()
    assert wx.read_sheet_json(tmp_path)["stored_name"] == "/art/x/wall.bmp"


# ------------------------------------------------------------------ loose folder
def test_files_from_beside_a_loose_folder_are_named_like_an_archive_names_them(tmp_path):
    src = ps._loose_game(tmp_path)
    run = cn.Run()
    done = nd.stage_loose_source(str(src), str(tmp_path / "out"), None, run)
    assert done == [
        ps.BIK_NAME.lower(),
        ps.HPD_NAME.lower(),
        "data_baked/tnt/production/database.bin",
    ]
    assert ps.HPD_NAME != ps.HPD_NAME.lower()  # the fixture spells it like the Part 1 folders
    assert (tmp_path / "out" / "files" / ps.HPD_NAME.lower()).is_file()
    assert sorted(os.listdir(tmp_path / "out" / "files" / "data")) == sorted(
        {ps.BIK_NAME.split("/")[1].lower(), ps.HPD_NAME.split("/")[1].lower()}
    )
    assert run.renamed == {
        ps.BIK_NAME.lower(): [ps.BIK_NAME],
        ps.HPD_NAME.lower(): [ps.HPD_NAME],
    }
    # without a run the rule is the same
    assert nd.stage_loose_source(str(src), str(tmp_path / "o2")) == done


def test_loose_folder_files_keep_their_spelling_with_names_stored(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")
    src = ps._loose_game(tmp_path)
    out = tmp_path / "out"
    ps._seed_definition(out)
    args = ["--no-textures", "--no-models", "--no-text", "--no-audio", "--names", "stored"]
    assert wx.main([str(src), "-o", str(out)] + args) == 0
    assert (out / "files").joinpath(*ps.HPD_NAME.split("/")).is_file()
    doc = json.loads((out / "nav" / "Demo.nav.json").read_text(encoding="utf-8"))
    assert doc["source"]["hpd"] == ps.HPD_NAME.split("/")[-1]
    assert json.loads((out / cn.RUN_FILE).read_text())["renamed"] == {}
    capsys.readouterr()


def test_extract_records_the_loose_folder_spelling(tmp_path, capsys):
    src = ps._loose_game(tmp_path)
    out = tmp_path / "out"
    ps._seed_definition(out)
    args = ["--no-textures", "--no-models", "--no-text", "--no-audio"]
    assert wx.main([str(src), "-o", str(out)] + args) == 0
    doc = json.loads((out / cn.RUN_FILE).read_text(encoding="utf-8"))
    assert doc["renamed"][ps.HPD_NAME.lower()] == [ps.HPD_NAME]
    assert "names       : 2 written under their canonical spelling" in capsys.readouterr().out


# ------------------------------------------------------------------ particle index
def _particle_extract(tmp_path, texture):
    ex = tmp_path / "EX"
    d = ex / "extracted" / "particles"
    d.mkdir(parents=True)
    (d / "MatressFire_03.particle").write_bytes(tp.system(types=[tp.ptype(0x20, "Fire", texture)]))
    tex = ex / "textures" / "art" / "Effects" / "Particles" / "Textures" / "Fire_01.BMP"
    tex.mkdir(parents=True)
    (tex / "0_diffuse_64x64_DXT5.png").write_bytes(b"png")
    return ex


def test_particle_index_names_a_texture_in_its_canonical_spelling(tmp_path):
    """Xbox 360 Part 2: MatressFire_03 names Fire_01.bmp; PC and PS3 Fire_01.BMP."""
    x360 = FIRE % "Fire_01.bmp"
    canon = FIRE % "Fire_01.BMP"
    index, docs = pm.build(str(_particle_extract(tmp_path / "x", x360)))
    assert list(index["textures"]) == [canon]
    entry = index["textures"][canon]
    assert entry["found"] and entry["dir"] == "art/Effects/Particles/Textures/Fire_01.BMP"
    assert entry["stored_name"] == [x360]
    row = index["files"][0]
    assert row["textures"] == [canon] and row["type_list"][0]["texture"] == canon
    # the per-file JSON is the file: it keeps the stored string
    assert x360 in json.dumps(docs["particles/MatressFire_03.particle"])
    assert canon not in json.dumps(docs["particles/MatressFire_03.particle"])
    assert "names" in index["evidence"]
    # PC: already canonical, no note
    pc, _ = pm.build(str(_particle_extract(tmp_path / "p", canon)))
    assert "stored_name" not in pc["textures"][canon]
    assert pc["textures"][canon] == {k: v for k, v in entry.items() if k != "stored_name"}


def test_particle_index_with_names_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    x360 = FIRE % "Fire_01.bmp"
    index, _docs = pm.build(str(_particle_extract(tmp_path, x360)))
    assert list(index["textures"]) == [x360] and "stored_name" not in index["textures"][x360]
    assert index["textures"][x360]["found"]  # the lookup never depended on the case


# ------------------------------------------------------------------ CLI
@pytest.mark.parametrize("cmd", watchmen.NAMES_COMMANDS)
def test_cli_names_option(cmd, monkeypatch, capsys):
    assert "--names canonical|stored" in watchmen.USAGE[cmd][1]
    seen = {}

    def stop(*a, **k):
        seen["names"] = os.environ.get("WATCHMEN_NAMES")
        raise OSError("stop here")

    monkeypatch.setattr(watchmen, "_wl", stop)
    monkeypatch.setattr(pm, "write", stop)
    import anim_meta, fx_meta, level_meta, materials, sound_meta

    for mod, fn in (
        (anim_meta, "write"),
        (anim_meta, "build"),
        (anim_meta, "find_class_fragments"),
        (fx_meta, "write"),
        (level_meta, "write"),
        (materials, "level_grades"),
        (sound_meta, "write"),
    ):
        monkeypatch.setattr(mod, fn, stop)
    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")
    pos = ["A"] * watchmen.USAGE[cmd][0]
    with pytest.raises(OSError):
        watchmen.main(["w", cmd] + pos + ["--names", "stored"])
    assert seen["names"] == "stored"
    assert watchmen.main(["w", cmd] + pos + ["--names", "lower"]) == 2
    assert watchmen.main(["w", cmd] + pos + ["--names"]) == 2
    assert "--names takes one of: canonical, stored" in capsys.readouterr().out


def test_cli_names_option_is_refused_where_no_name_is_written(monkeypatch, capsys):
    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")
    for cmd in ("fragment", "hash", "navmeta", "textmeta", "text", "binds"):
        assert watchmen.main(["w", cmd, "A", "B", "C", "--names", "stored"]) == 2
    assert "--names applies to: all, extract, characters, char, charlibs, faces, particlemeta" in (
        capsys.readouterr().out
    )
    assert os.environ["WATCHMEN_NAMES"] == "canonical"
    assert set(watchmen.NAMES_MODES) == set(cn.MODES)
    assert "--names canonical|stored" in watchmen.__doc__ and "$WATCHMEN_NAMES" in watchmen.__doc__


def test_extract_parser_has_the_option(monkeypatch, capsys):
    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")
    with pytest.raises(SystemExit):
        wx.main(["--help"])
    assert "--names {canonical,stored}" in capsys.readouterr().out
    assert cn.CURRENT is None  # the run is closed however main() ends


# ------------------------------------------------------------------ one folder spelling per export
def test_the_output_trees_of_an_export_share_one_folder_spelling(
    tmp_path, writers, monkeypatch, capsys
):
    """A model in Art/Environments and its texture in art/environments: models/,
    textures/ and extracted/ spell every folder as the first asset written into it
    does (extracted/ sees every asset first), and the table's spelling wins."""
    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")  # --names sets it: restored after
    tex, mdl = ps._cls("Texture", b"tex-hdr"), ps._cls("ModelRes", b"mdl-hdr")
    rows = [
        ("/art/environments/common/House.fragment", 1, ps._cls("Fragment", b"frag"), b""),
        ("/art/Environments/Common/textures/Wall.bmp", tf._TEX, tex, b"wall-stream"),
        ("/Art/Environments/Common/House.model", 1, mdl, b"house-stream"),
        ("/art/props/common/Streetlines/Line_01.model", 1, mdl, b"line-stream"),
        ("/art/props/common/streetlines/textures/Line.bmp", tf._TEX, tex, b"line-tex"),
    ]
    d = tmp_path / "files" / "derived_pc" / "levels"
    d.mkdir(parents=True)
    h, s = tf._block(rows)
    (d / "a.block_h_z").write_bytes(h)
    (d / "a.block_s_z").write_bytes(s)
    out = tmp_path / "out"
    args = [str(tmp_path / "files"), "-o", str(out), "--no-text", "--no-audio", "--no-nav"]
    assert wx.main(args + ["--no-files"]) == 0
    got = _paths(out)
    for want in (
        "extracted/art/environments/common/House.fragment",
        "extracted/art/environments/common/House.model",
        "models/art/environments/common/House.model.obj",
        "textures/art/environments/common/textures/Wall.bmp/sheet.json",
        "extracted/art/props/common/streetlines/Line_01.model",
        "models/art/props/common/streetlines/Line_01.model.obj",
        "textures/art/props/common/streetlines/textures/Line.bmp/sheet.json",
    ):
        assert want in got, want
    # folder for folder: no tree spells a folder its own way
    spelled = {}
    for path in got:
        parts = path.split("/")
        for i in range(2, len(parts)):
            spelled.setdefault(cn.key("/".join(parts[1:i])), set()).add("/".join(parts[1:i]))
    assert [v for v in spelled.values() if len(v) > 1] == []
    doc = json.loads((out / cn.RUN_FILE).read_text(encoding="utf-8"))
    assert doc["folders"]["models/art/environments"] == ["Environments"]
    assert doc["folders"]["textures/art/environments/common"] == ["Common"]
    assert doc["folders"]["extracted/art"] == ["Art"]
    assert "models/art/props/common/streetlines" not in doc["folders"]  # the table's, not a first
    # the record names an asset as its path is written
    assert doc["renamed"] == {
        "/art/props/common/streetlines/Line_01.model": [
            "/art/props/common/Streetlines/Line_01.model"
        ]
    }
    assert writers["mdl"]["Line_01.model.obj"] == {
        "stored_name": "/art/props/common/Streetlines/Line_01.model"
    }
    # --names stored: every tree as the archive stores its own paths
    out2 = tmp_path / "out2"
    assert wx.main(args[:2] + [str(out2)] + args[3:] + ["--no-files", "--names", "stored"]) == 0
    got2 = _paths(out2)
    # a case-insensitive file system merges folders that differ only in case
    # into the spelling written first
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    fold = (tmp_path / "caseprobe").exists()
    seen = [p.lower() for p in got2] if fold else got2
    for want in (
        "models/Art/Environments/Common/House.model.obj",
        "models/art/props/common/Streetlines/Line_01.model.obj",
        "textures/art/Environments/Common/textures/Wall.bmp/sheet.json",
    ):
        assert (want.lower() if fold else want) in seen, want


def test_trees_that_share_no_folders_keep_their_own_first_spelling(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    assert cn.output_parts(a, ["Art", "x.bmp"]) == ["Art", "x.bmp"]
    assert cn.output_parts(b, ["art", "x.bmp"]) == ["art", "x.bmp"]
    cn.share_folders(tmp_path / "ex")
    assert cn.output_parts(tmp_path / "ex" / "extracted", ["art", "P", "x.model"])[:2] == [
        "art",
        "P",
    ]
    assert cn.output_parts(tmp_path / "ex" / "models", ["Art", "p", "x.model.obj"]) == [
        "art",
        "P",
        "x.model.obj",
    ]
    assert cn.output_parts(tmp_path / "ex" / "files", ["Art", "x"]) == ["Art", "x"]  # not shared
    assert cn.written_parts(tmp_path / "ex" / "textures", ["ART", "p", "X.bmp"]) == [
        "art",
        "P",
        "X.bmp",
    ]
    assert cn.folder_spellings(tmp_path / "ex") == {
        "extracted/art": ["Art"],
        "extracted/art/P": ["p"],
        "models/art": ["Art"],
        "models/art/P": ["p"],
    }


# ------------------------------------------------------------------ references in tables
def _export(root):
    """A small export folder: a texture, a model, a fragment, a movie, a sound."""
    for rel in (
        "textures/art/Effects/Particles/Textures/Fire_01.BMP/0_diffuse_4x4_DXT1.png",
        "extracted/art/Effects/Particles/Textures/Fire_01.BMP",
        "extracted/art/props/Crate.model",
        "models/art/props/Crate.model.obj",
        "models/art/props/Crate.model.glb",
        "models/art/props/Crate.model.model.json",
        "extracted/TNT/Production/Cam.sequence",
        "extracted/Levels/T/Lvl.fragment",
        "extracted/Levels/T/Lvl.fragment.json",
        "files/data/levels/t/gameplay/t.hpd",
        "files/derived_pc/sounds/music/menu_track0.mediastream_s",
        "audio/sounds/Hit_01.wav.ogg",
    ):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return root


def test_export_index_finds_a_file_whatever_the_string_spells(tmp_path):
    ix = cn.ExportIndex(str(_export(tmp_path)))
    assert ix.find("/Art/Effects/particles/textures/fire_01.bmp") == (
        "textures",
        "art/Effects/Particles/Textures/Fire_01.BMP",
    )
    assert ix.find("\\ART\\PROPS\\crate.MODEL") == ("models", "art/props/Crate.model")
    assert ix.find("/tnt/production/cam.sequence") == ("extracted", "TNT/Production/Cam.sequence")
    assert ix.find("/data/Levels/T/Gameplay/T.hpd") == ("files", "data/levels/t/gameplay/t.hpd")
    assert ix.find("/Sounds/hit_01.wav") == ("audio", "sounds/Hit_01.wav")
    assert ix.spell("/art/effects/PARTICLES/textures/fire_01.bmp") == (
        "/art/Effects/Particles/Textures/Fire_01.BMP"
    )
    assert ix.spell("ART/props/CRATE.model") == "art/props/Crate.model"  # no slash, none added
    same = "/art/props/Crate.model"
    assert ix.spell(same) is same
    # several paths in one string, each on its own
    assert ix.spell("2,0,/ART/props/crate.model, /levels/t/LVL.fragment") == (
        "2,0,/art/props/Crate.model, /Levels/T/Lvl.fragment"
    )
    # what names no file stays: a folder, a bare name, a word, a path of another game
    for text in ("/art/props", "Art", "Crate.model", "art/Effects", "/art/props/Barrel.model", ""):
        assert ix.find(text) is None and ix.spell(text) == text
    assert cn.resolve(str(tmp_path), "/ART/PROPS/CRATE.MODEL") == "models/art/props/Crate.model"
    assert cn.resolve(str(tmp_path), "/art/effects/particles/textures/FIRE_01.bmp", ix) == (
        "textures/art/Effects/Particles/Textures/Fire_01.BMP"
    )
    assert cn.resolve(str(tmp_path), "/art/nothing.bmp") is None


def test_an_export_whose_trees_differ_follows_the_tree_of_the_kind(tmp_path):
    """An export made before the trees shared their folder spelling."""
    for rel in (
        "extracted/art/environments/House.model",
        "models/art/Environments/House.model.glb",
        "extracted/art/Walls/Brick.bmp",
        "textures/art/walls/Brick.bmp/0.png",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    ix = cn.ExportIndex(str(tmp_path))
    assert ix.spell("/ART/ENVIRONMENTS/house.model") == "/art/Environments/House.model"
    assert ix.spell("/ART/WALLS/brick.bmp") == "/art/walls/Brick.bmp"


def test_respell_keeps_the_stored_string_beside_the_field(tmp_path):
    ix = cn.ExportIndex(str(_export(tmp_path)))
    doc = {
        "name": "Art",
        "model": "/ART/props/crate.model",
        "exact": "/art/props/Crate.model",
        "models": ["/art/PROPS/Crate.model", "/art/props/Crate.model", "/art/props/None.model"],
        "mixed": ["/levels/t/lvl.fragment", {"sequence": "/tnt/production/cam.sequence"}],
        "particles": {
            "/ART/effects/particles/textures/FIRE_01.bmp": {"used": 2},
            "/art/props/Crate.model": {"texture": "/art/effects/particles/textures/fire_01.bmp"},
        },
        "sheets": "1,0,/Art/Props/Crate.model;x",
        "stored_name": "/ART/PROPS/CRATE.MODEL",
        "rows": [["/LEVELS/t/lvl.fragment", 3]],
    }
    before = json.loads(json.dumps(doc))
    assert cn.respell(doc, ix) == 8
    assert doc == {
        "name": "Art",
        "model": "/art/props/Crate.model",
        "exact": "/art/props/Crate.model",
        "models": ["/art/props/Crate.model", "/art/props/Crate.model", "/art/props/None.model"],
        "mixed": [
            "/Levels/T/Lvl.fragment",
            {
                "sequence": "/TNT/Production/Cam.sequence",
                "stored": {"sequence": "/tnt/production/cam.sequence"},
            },
        ],
        "particles": {
            "/art/Effects/Particles/Textures/Fire_01.BMP": {"used": 2},
            "/art/props/Crate.model": {
                "texture": "/art/Effects/Particles/Textures/Fire_01.BMP",
                "stored": {"texture": "/art/effects/particles/textures/fire_01.bmp"},
            },
        },
        "sheets": "1,0,/art/props/Crate.model;x",
        "stored_name": "/ART/PROPS/CRATE.MODEL",  # an asset's own archive spelling: untouched
        "rows": [["/Levels/T/Lvl.fragment", 3]],
        "stored": {
            "model": before["model"],
            "models": before["models"],
            "mixed": {"0": "/levels/t/lvl.fragment"},
            "particles": {
                "/art/Effects/Particles/Textures/Fire_01.BMP": (
                    "/ART/effects/particles/textures/FIRE_01.bmp"
                )
            },
            "sheets": before["sheets"],
            "rows": before["rows"],
        },
    }
    after = json.loads(json.dumps(doc))
    assert cn.respell(doc, ix) == 0 and doc == after  # a second pass changes nothing
    # every string outside "stored" that names a file now has its letter case
    for text in (doc["model"], doc["models"][0], doc["mixed"][0], doc["rows"][0][0]):
        tree, path = ix.find(text)
        assert text.lstrip("/") == path
    # a record with a "stored" value of its own is not touched; the records in it are
    own = {"stored": 3, "model": "/ART/props/crate.model", "sub": [{"m": "/ART/props/crate.model"}]}
    assert cn.respell(own, ix) == 1
    assert own == {
        "stored": 3,
        "model": "/ART/props/crate.model",
        "sub": [{"m": "/art/props/Crate.model", "stored": {"m": "/ART/props/crate.model"}}],
    }
    # two stored spellings of one key: the first takes the file's spelling, the other stays
    twice = {"m": {"/ART/props/crate.model": 1, "/art/PROPS/crate.model": 2}}
    assert cn.respell(twice, ix) == 1
    assert list(twice["m"]) == ["/art/props/Crate.model", "/art/PROPS/crate.model"]


def test_tables_follow_the_naming_of_their_export(tmp_path, monkeypatch):
    ex = _export(tmp_path / "ex")
    assert cn.export_mode(str(ex)) == "canonical"  # no record: the default
    (ex / cn.RUN_FILE).write_text('{"names": "stored"}')
    assert cn.export_mode(str(ex)) == "stored"  # made with --names stored
    doc = {"model": "/ART/props/crate.model"}
    assert cn.respell_export(doc, str(ex)) == {"model": "/ART/props/crate.model"}  # untouched
    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")  # the option of the command wins
    assert cn.export_mode(str(ex)) == "canonical"
    out = cn.respell_export(doc, str(ex))
    assert out is doc and doc["model"] == "/art/props/Crate.model"
    assert doc["stored"] == {"model": "/ART/props/crate.model"}
    assert doc["asset_names"]["spelling"] == "export" and doc["asset_names"]["respelled"] == 1
    cn.respell_export(doc, str(ex))  # again (a table built from another table)
    assert doc["asset_names"]["respelled"] == 1 and doc["stored"] == {
        "model": "/ART/props/crate.model"
    }
    monkeypatch.setenv("WATCHMEN_NAMES", "stored")
    assert cn.export_mode(str(ex)) == "stored"
    (ex / cn.RUN_FILE).write_text("not json")
    monkeypatch.delenv("WATCHMEN_NAMES")
    assert cn.export_mode(str(ex)) == "canonical"


def test_the_table_writers_respell_what_they_build(tmp_path, monkeypatch):
    """fxmeta, soundmeta, animmeta and grademeta hand their table to
    respell_export with the export they read."""
    import anim_meta
    import fx_meta
    import sound_meta

    monkeypatch.setenv("WATCHMEN_NAMES", "canonical")  # --names sets it: restored after
    ex = _export(tmp_path / "ex")
    monkeypatch.setattr(fx_meta, "tables", lambda e, log=None: {"p": "/ART/props/crate.model"})
    fx = fx_meta.build(str(ex))
    assert fx["p"] == "/art/props/Crate.model" and fx["stored"] == {"p": "/ART/props/crate.model"}
    assert fx["asset_names"]["respelled"] == 1
    assert anim_meta._asset_names({"m": "/levels/T/LVL.fragment"}, str(ex)) == {
        "m": "/Levels/T/Lvl.fragment",
        "stored": {"m": "/levels/T/LVL.fragment"},
        "asset_names": {
            "spelling": "export",
            "respelled": 1,
            "note": cn._NAMES_NOTE,
        },
    }
    src = pathlib.Path(sound_meta.__file__).read_text(encoding="utf-8")
    assert "canonical_names.respell_export(out, extract_out)" in src
    grade = {"fragments": {"a": [{"noisetexture": "/ART/effects/particles/textures/fire_01.BMP"}]}}
    import materials

    monkeypatch.setattr(materials, "level_grades", lambda e, r: json.loads(json.dumps(grade)))
    out = tmp_path / "grade.json"
    assert watchmen.main(["w", "grademeta", str(ex), str(out)]) == 0
    row = json.loads(out.read_text(encoding="utf-8"))["fragments"]["a"][0]
    assert row["noisetexture"] == "/art/Effects/Particles/Textures/Fire_01.BMP"
    assert row["stored"] == {"noisetexture": "/ART/effects/particles/textures/fire_01.BMP"}
    assert watchmen.main(["w", "grademeta", str(ex), str(out), "--names", "stored"]) == 0
    row = json.loads(out.read_text(encoding="utf-8"))["fragments"]["a"][0]
    assert row == {"noisetexture": "/ART/effects/particles/textures/fire_01.BMP"}
