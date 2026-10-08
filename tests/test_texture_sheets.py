"""Texture sheets and blend types.

A Texture asset holds one or more named TextureSheets (material settings).  The
first is the one in use unless a model instance names another by its uniqueID
(`textureSheetsDescription`, BaseModel 0x4a56c2 -> 0x524caf, which falls back to
the first sheet).  A sheet can take single layers from another texture
(<layer>MapOverride) -- that is how the outfit colours are stored -- and carries
the blend type (0x582eb6: standard / add / subtract / manual).  Each test fails
on the tree before this change.
"""

import io
import json
import struct

import numpy as np
import pytest

import char_lib
import characters_export as ce
import rig_glb
import variant_glb as vg
import watchmen_extract as we
from conftest import parse_glb

Image = pytest.importorskip("PIL.Image")

WHITE, BLACK_ID, RED_ID = 111 << 32 | 5, 222 << 32 | 6, 333 << 32 | 7


def _rec(salt, name, typ, payload):
    cnt = len(payload) // 4
    return struct.pack("<IIII", salt, we._name_hash(name), we._name_hash(typ), cnt) + payload


def _str(text):
    raw = text.encode("latin-1") + b"\0"
    raw += b"\0" * (-len(raw) % 4)
    return struct.pack("<I", len(text) + 1) + raw


def _sheet(salt, name, uid, **props):
    b = _rec(salt, "name", "string", _str(name))
    b += struct.pack("<IIII", salt, we._name_hash("uniqueID"), we._T_UNIQUE_ID, 2)
    b += struct.pack("<II", uid >> 32, uid & 0xFFFFFFFF)
    base = dict(renderType=0, alphaThreshold=95, twoSided=False, blendType=0, specularSize=15.0)
    base.update(props)
    for k, v in base.items():
        if k.endswith("MapOverride"):
            b += _rec(salt, k, "string", _str(v))
        elif isinstance(v, bool):
            b += _rec(salt, k, "truth", struct.pack("<I", int(v)))
        elif isinstance(v, float):
            b += _rec(salt, k, "number", struct.pack("<f", v))
        else:
            b += _rec(salt, k, "integer", struct.pack("<i", v))
    return b


def _header(*sheets):
    return b"\x08\x00\x00\x00Texture\x00" + b"\xaa" * 37 + b"".join(sheets) + b"\0" * 24


SKIN = "/art/c/dom/textures/Skin_White.bmp"
SKIN_BLACK = "/art/c/dom/textures/Skin_Black.bmp"
SKIN_HDR = _header(
    _sheet(0x1111, "default", WHITE, alphaThreshold=95),
    _sheet(
        0x2222,
        "Black",
        BLACK_ID,
        alphaThreshold=160,
        specularSize=40.0,
        twoSided=True,
        diffuseMapOverride=SKIN_BLACK,
        emptyNote=0,
    ),
    _sheet(0x3333, "Red", RED_ID, renderType=1, blendType=1, uScrollSpeed=0.25),
)


def _png(rgb, alpha=None, size=(4, 4)):
    if alpha is None:
        return Image.new("RGB", size, rgb)
    return Image.new("RGBA", size, tuple(rgb) + (alpha,))


def _texture(root, path, rgb, header=None, normal=None, sheet_json=None, alpha=None):
    """textures/<path>/ with a diffuse (and normal) PNG; extracted/<path> = header."""
    d = root / "textures"
    for p in path.strip("/").split("/"):
        d = d / p
    d.mkdir(parents=True)
    _png(rgb, alpha).save(d / "0_diffuse_4x4_DXT1.png")
    if normal:
        _png(normal).save(d / "1_normal_4x4_ATI2.png")
    if header is not None:
        h = root / "extracted"
        for p in path.strip("/").split("/")[:-1]:
            h = h / p
        h.mkdir(parents=True, exist_ok=True)
        (h / path.split("/")[-1]).write_bytes(header)
        if sheet_json is None:
            we._write_sheet_json(header, d)
    if sheet_json:
        (d / "sheet.json").write_text(json.dumps(sheet_json))
    return d


def _rgb(png):
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel((0, 0))


@pytest.fixture(autouse=True)
def _fresh():
    for c in (char_lib._TEXIDX, char_lib._LAYERCACHE, ce._FRAG_NODES, ce._TEX_SHEETS):
        c.clear()
    yield
    for c in (char_lib._TEXIDX, char_lib._LAYERCACHE, ce._FRAG_NODES, ce._TEX_SHEETS):
        c.clear()


# ---------------------------------------------------------------------------
# 1. the sheet table
# ---------------------------------------------------------------------------


def test_every_sheet_is_read_with_its_properties_and_overrides():
    sheets = we.texture_sheets(SKIN_HDR)
    assert [s["name"] for s in sheets] == ["default", "Black", "Red"]
    assert [s["uniqueID"] for s in sheets] == [WHITE, BLACK_ID, RED_ID]
    assert sheets[0]["overrides"] == {} and sheets[1]["overrides"] == {"diffuse": SKIN_BLACK}
    assert sheets[1]["alphaThreshold"] == 160 and sheets[1]["twoSided"] is True
    assert abs(sheets[1]["specularSize"] - 40.0) < 1e-6
    assert sheets[2]["blendType"] == 1 and abs(sheets[2]["uScrollSpeed"] - 0.25) < 1e-6
    # the first-sheet reader of the earlier tree agrees with sheet 0
    first = we.texture_sheet(SKIN_HDR)
    assert first and all(sheets[0][k] == v for k, v in first.items())
    assert we.texture_sheets(b"\0" * 80) == []


def test_select_sheet_by_id_by_name_and_the_engines_fallback():
    sheets = we.texture_sheets(SKIN_HDR)
    assert we.select_sheet(sheets) is sheets[0]
    assert we.select_sheet(sheets, BLACK_ID) is sheets[1]
    assert we.select_sheet(sheets, "Red") is sheets[2]
    assert we.select_sheet(sheets, 987654321) is sheets[0]  # unknown id: the first sheet
    assert we.select_sheet(sheets, "nope") is sheets[0]
    assert we.select_sheet([]) == {}


def test_sheet_json_lists_every_sheet_and_keeps_the_first_at_top_level(tmp_path):
    we._write_sheet_json(SKIN_HDR, tmp_path)
    d = we.read_sheet_json(tmp_path)
    assert d["alphaThreshold"] == 95 and d["twoSided"] is False  # as before: sheet 0
    assert [s["name"] for s in d["sheets"]] == ["default", "Black", "Red"]
    assert d["sheets"][1]["uniqueID"] == BLACK_ID
    assert d["sheets"][1]["overrides"] == {"diffuse": SKIN_BLACK}
    assert "overrides" not in d  # sheet 0 takes nothing from elsewhere
    hdr = _header(_sheet(0x9, "default", 77, diffuseMapOverride="/art/x/Beige.bmp"))
    we._write_sheet_json(hdr, tmp_path)
    assert we.read_sheet_json(tmp_path)["overrides"] == {"diffuse": "/art/x/Beige.bmp"}


# ---------------------------------------------------------------------------
# 2. blend types
# ---------------------------------------------------------------------------


def test_blend_states_of_every_type():
    b = lambda **k: we.sheet_blend(dict(renderType=1, **k))
    assert b(blendType=0) == dict(
        type="standard",
        src="srcAlpha",
        dst="invSrcAlpha",
        op="add",
        gltf="exact",
        cause="renderType",
    )
    assert b(blendType=1) == dict(
        type="add", src="srcAlpha", dst="one", op="add", gltf="glow", cause="renderType"
    )
    sub = b(blendType=2)
    assert (sub["src"], sub["dst"], sub["op"], sub["gltf"]) == (
        "srcAlpha",
        "one",
        "revSubtract",
        "ink",
    )
    # manual: the sheet's own factors; only some combinations have a glTF form
    man = b(blendType=3, srcBlend=9, dstBlend=6, blendOp=1)
    assert (man["type"], man["src"], man["dst"], man["gltf"]) == (
        "manual",
        "dstColor",
        "invSrcAlpha",
        None,
    )
    assert b(blendType=3, srcBlend=5, dstBlend=6, blendOp=1)["gltf"] == "exact"
    assert b(blendType=3, srcBlend=5, dstBlend=2, blendOp=1)["gltf"] == "glow"
    # the sky box pass uses one/one, and plain subtract there
    sky = we.sheet_blend(dict(renderType=7, blendType=1))
    assert (sky["src"], sky["dst"], sky["op"]) == ("one", "one", "add")
    assert we.sheet_blend(dict(renderType=7, blendType=2))["op"] == "subtract"
    # "Standard with blending", SkyBox and Sprite blend; Standard / FallOff only
    # with an opacity below 0.99 (tests/test_p1_materials.py)
    assert we.sheet_blend(dict(renderType=0, blendType=1)) is None
    assert we.sheet_blend(dict(renderType=10, blendType=2)) is None
    assert we.sheet_blend({}) is None and we.sheet_blend(None) is None


def test_ink_and_glow_images():
    im = Image.new("RGBA", (2, 1), (0, 0, 0, 255))
    im.putpixel((0, 0), (255, 128, 0, 255))
    im.putpixel((1, 0), (100, 100, 100, 128))
    ink = we.blend_layer_image(im, {"gltf": "ink"})
    assert ink.getpixel((0, 0))[:3] == (0, 0, 0) and ink.getpixel((0, 0))[3] > 100
    assert ink.getpixel((1, 0)) == (0, 0, 0, 50)  # brightness 100 * alpha 128 / 255
    glow = we.blend_layer_image(im, {"gltf": "glow"})
    assert glow.getpixel((0, 0)) == (255, 128, 0, 255)  # already at full brightness
    assert glow.getpixel((1, 0)) == (255, 255, 255, 50)  # colour normalised, coverage in alpha
    assert we.blend_layer_image(im, {"gltf": "exact"}) is im
    assert we.blend_layer_image(im, None) is im


def _quad_glb(tmp_path, mats, idx, name="m.glb"):
    V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)] * len(mats)
    U = [(0, 0), (1, 0), (1, 1), (0, 1)] * len(mats)
    T, subs = [], []
    for k in range(len(mats)):
        T += [(4 * k, 4 * k + 2, 4 * k + 1), (4 * k, 4 * k + 3, 4 * k + 2)]
        subs.append((4 * k, 4, 2 * k, 2, 44))
    nrm = np.tile(np.array([0, 0, 1], np.float32), (len(V), 1))
    pal = {"bone_count": 1, "bones": [{"name": "root"}]}
    rig_glb.build_rigged_glb(
        tmp_path / name, np.asarray(V, float), None, U, None, None, T, subs, list(mats), idx, pal,
        None, None, static=True, normals=nrm, engine_materials=True,
    )  # fmt: skip
    return parse_glb(tmp_path / name)


def _image(g, tex_index):
    bv = g.j["bufferViews"][g.j["images"][g.j["textures"][tex_index]["source"]]["bufferView"]]
    o = bv.get("byteOffset", 0)
    return Image.open(io.BytesIO(bytes(g.bin_chunk[o : o + bv["byteLength"]])))


def test_model_glb_writes_add_and_subtract_layers_as_blend_materials(tmp_path):
    root = tmp_path
    _texture(root, "/art/fx/flare.bmp", (200, 100, 0), sheet_json=dict(renderType=1, blendType=1))
    _texture(root, "/art/r/spots.bmp", (255, 255, 255), sheet_json=dict(renderType=1, blendType=2))
    _texture(
        root, "/art/fx/odd.bmp", (9, 9, 9),
        sheet_json=dict(renderType=9, blendType=3, srcBlend=9, dstBlend=6, blendOp=1),
    )  # fmt: skip
    idx = we.build_texture_index(root / "textures")
    mats = [we.texture_ref(p) for p in ("/art/fx/flare.bmp", "/art/r/spots.bmp", "/art/fx/odd.bmp")]
    g = _quad_glb(tmp_path, mats, idx)
    flare, ink, odd = [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]
    # add: light on top -> emissive, coverage in alpha, nothing reflected
    assert flare["alphaMode"] == "BLEND" and flare["emissiveFactor"] == [1.0, 1.0, 1.0]
    assert flare["pbrMetallicRoughness"]["baseColorFactor"] == [0.0, 0.0, 0.0, 1.0]
    ti = flare["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    assert flare["emissiveTexture"]["index"] == ti
    assert _image(g, ti).convert("RGBA").getpixel((0, 0)) == (255, 128, 0, 200)
    assert flare["extras"]["watchmen"]["blend"] == "add"
    assert flare["extras"]["watchmen"]["dst"] == "one"
    # subtract: black ink
    assert ink["alphaMode"] == "BLEND" and ink["extras"]["watchmen"]["blend"] == "subtract"
    ti = ink["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    assert _image(g, ti).convert("RGBA").getpixel((0, 0)) == (0, 0, 0, 255)
    assert "emissiveTexture" not in ink
    # a manual blend without a glTF form: untouched texture, the blend named in extras
    ti = odd["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    assert _image(g, ti).convert("RGB").getpixel((0, 0)) == (9, 9, 9)
    assert odd["extras"]["watchmen"]["src"] == "dstColor" and "alphaMode" not in odd


def test_model_glb_reads_a_manual_blend_from_the_extracted_sheet_table(tmp_path):
    """sheet.json as the extractor writes it: the manual factors are only in
    "sheets" (Sky_SunRay_01: SRCALPHA / ONE, ADD = an additive layer)."""
    root = tmp_path
    hdr = _header(
        _sheet(0x7, "default", 5, renderType=7, blendType=3, srcBlend=5, dstBlend=2, blendOp=1)
    )
    _texture(root, "/art/sky/SunRay.bmp", (200, 100, 0), header=hdr)
    flat = json.loads((root / "textures/art/sky/SunRay.bmp/sheet.json").read_text())
    assert "srcBlend" not in flat and flat["sheets"][0]["dstBlend"] == 2
    idx = we.build_texture_index(root / "textures")
    g = _quad_glb(tmp_path, [we.texture_ref("/art/sky/SunRay.bmp")], idx)
    mat = g.j["materials"][g.j["meshes"][0]["primitives"][0]["material"]]
    assert mat["extras"]["watchmen"] == dict(
        mat["extras"]["watchmen"], blend="manual", src="srcAlpha", dst="one", op="add"
    )
    assert "emissiveTexture" in mat and mat["alphaMode"] == "BLEND"


def test_model_exports_use_the_layers_the_first_sheet_takes_from_elsewhere(tmp_path):
    root = tmp_path
    hdr = _header(_sheet(0x9, "default", 77, diffuseMapOverride="/art/k/TShirtBeige.bmp"))
    _texture(root, "/art/k/TShirt.bmp", (250, 250, 250), header=hdr, normal=(128, 128, 255))
    _texture(root, "/art/k/TShirtBeige.bmp", (200, 180, 140))
    idx = we.build_texture_index(root / "textures")
    shirt = we.texture_ref("/art/k/TShirt.bmp")
    g = _quad_glb(tmp_path, [shirt], idx)
    mat = g.j["materials"][g.j["meshes"][0]["primitives"][0]["material"]]
    ti = mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    assert _image(g, ti).convert("RGB").getpixel((0, 0)) == (200, 180, 140)
    assert "normalTexture" in mat  # its own normal map stays
    # OBJ/MTL: the same diffuse file
    out = tmp_path / "models" / "m.obj"
    v = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    we._write_obj_mtl(out, "m", v, None, None, [(0, 1, 2)], [(0, 3, 0, 1, 44)], [shirt], idx, None)
    mtl = out.with_suffix(".mtl").read_text()
    assert "map_Kd ../textures/art/k/TShirtBeige.bmp/0_diffuse" in mtl
    assert "map_Bump -bm 1.000000 ../textures/art/k/TShirt.bmp/1_normal" in mtl


# ---------------------------------------------------------------------------
# 3. characters: a variant's sheets
# ---------------------------------------------------------------------------


def _skin_tree(root, with_table=True):
    d = _texture(root, SKIN, (240, 200, 180), header=SKIN_HDR, normal=(128, 128, 255), alpha=100)
    _texture(root, SKIN_BLACK, (60, 40, 30), alpha=100)
    Image.new("L", (4, 4), 200).save(d / "roughnessGen.png")
    if not with_table:  # a texture tree carved before sheet.json listed the sheets
        (d / "sheet.json").write_text(json.dumps(we.texture_sheet(SKIN_HDR)))
    return [str(root / "textures")]


@pytest.mark.parametrize("with_table", [True, False])
def test_a_selected_sheet_brings_its_layers_and_switches(tmp_path, with_table, monkeypatch):
    # the roughnessGen.png path is the `legacy` material mode (materials.py)
    monkeypatch.setenv("WATCHMEN_MATERIALS", "legacy")
    roots = _skin_tree(tmp_path, with_table)
    skin = we.texture_ref(SKIN)
    plain = char_lib._find_layers(skin, roots)
    black = char_lib._find_layers(char_lib.sheet_ref(skin, "Black"), roots)
    assert _rgb(plain["diffuse"]) == (240, 200, 180) and _rgb(black["diffuse"]) == (60, 40, 30)
    assert black["normal"] == plain["normal"]  # only the diffuse is overridden
    assert plain["sheet"]["alphaThreshold"] == 95 and black["sheet"]["alphaThreshold"] == 160
    assert "sheet_name" not in plain and black["sheet_name"] == "Black"
    # the flat roughness follows the sheet's specular exponent
    rough = lambda L: Image.open(io.BytesIO(L["mr"])).getpixel((0, 0))[1]
    assert rough(plain) == 200
    assert rough(black) == int(round((1 - (2.0 / 42.0) ** 0.5) * 255))
    # an unknown sheet name is the first sheet, as an unknown id is in the game
    odd = char_lib._find_layers(char_lib.sheet_ref(skin, "Nope"), roots)
    assert _rgb(odd["diffuse"]) == (240, 200, 180) and "sheet_name" not in odd


def test_sheet_ref_is_a_material_of_its_own():
    skin = we.texture_ref(SKIN)
    black = char_lib.sheet_ref(skin, "Black")
    assert black == "Skin_White" and black != skin and black.path == SKIN + "#sheet=Black"
    assert char_lib.sheet_ref(skin, None) is skin
    assert char_lib.sheet_ref(black, "Red").path == SKIN + "#sheet=Red"
    assert char_lib.sheet_ref("plain", "Black") == "plain"  # no path: nothing to select in


def test_character_glb_materials_follow_the_selected_sheet(tmp_path, rig, monkeypatch):
    monkeypatch.delenv("WATCHMEN_VERTEX_ATTRS", raising=False)
    roots = _skin_tree(tmp_path)
    skin = we.texture_ref(SKIN)
    black = char_lib.sheet_ref(skin, "Black")
    base = rig.parts[0]
    parts = [tuple(base[:5]) + (skin,), tuple(base[:5]) + (black,)]
    tex = char_lib.find_textures(parts, roots)
    assert len(tex) == 2
    vg.write_glb(parts, rig.manifest, tmp_path / "c.glb", str(rig.bind_npz), textures=tex)
    g = parse_glb(tmp_path / "c.glb")
    a, b = [g.j["materials"][p["material"]] for p in g.j["meshes"][0]["primitives"]]
    assert a["name"] == "Skin_White" and b["name"] == "Skin_White [Black]"
    assert a["alphaMode"] == b["alphaMode"] == "MASK"
    assert a["alphaCutoff"] == round(95 / 255.0, 6) and b["alphaCutoff"] == round(160 / 255.0, 6)
    assert "sheet" not in a.get("extras", {}).get("watchmen", {})
    assert b["extras"]["watchmen"]["sheet"] == "Black"
    col = lambda m: _image(g, m["pbrMetallicRoughness"]["baseColorTexture"]["index"])
    assert col(a).convert("RGB").getpixel((0, 0)) == (240, 200, 180)
    assert col(b).convert("RGB").getpixel((0, 0)) == (60, 40, 30)


def test_sheet_records_of_both_description_versions():
    v2 = "2,1,0,0,/art/a.bmp,5,1,0,0,/art/b.bmp,6,4,2,1,/art/c.bmp,7,"
    assert ce.sheet_records(v2) == [
        (1, 0, 0, "/art/a.bmp", 5),
        (1, 0, 0, "/art/b.bmp", 6),
        (4, 2, 1, "/art/c.bmp", 7),
    ]
    assert ce.sheet_records("1,3,0,/art/a.bmp,9,") == [(3, 0, 0, "/art/a.bmp", 9)]
    assert ce.sheet_records("") == [] and ce.sheet_records(None) == []
    assert ce.sheet_records("2,1,0,0,/art/a.bmp,notanumber,") == []


def _fragment(root, stem, nodes):
    d = root / "extracted" / "TNT" / "Production" / "Fragments" / "Enemy"
    d.mkdir(parents=True, exist_ok=True)
    full = []
    for k, (name, models, desc) in enumerate(nodes):
        props = [["name", "string", name], ["modelNames", "list", models]]
        if desc is not None:
            props.append(["textureSheetsDescription", "string", desc])
        full.append({"id": "n%d" % k, "props": props})
    full.append({"id": "other", "props": [["name", "string", "not a model node"]]})
    (d / (stem + ".fragment.json")).write_text(json.dumps({"nodes_full": full, "instances": []}))


def test_variant_sheets_come_from_the_fragment_nodes(tmp_path):
    _skin_tree(tmp_path)
    skel, suit, glove, boots = (
        "/art/c/skel/Female_Skeleton.model",
        "/Art/c/dom/model/Suit.model",
        "/art/c/dom/model/Glove.model",
        "/art/c/dom/model/Boots.model",
    )
    rec = lambda slot, sid, path=SKIN: "%d,0,0,%s,%d," % (slot, path, sid)
    _fragment(
        tmp_path,
        "Dom",
        [
            # outfit 0: the suit in Black; a record for a texture the glove does not
            # carry is harmless; an unknown id and the first sheet's id select nothing
            ("Dom_5", [skel, "", suit, glove], "2," + rec(2, BLACK_ID) + rec(3, 424242)),
            # outfit 1 of the same name: Red suit (the last record wins), Black boots
            (
                "Dom_5",
                [skel, boots, suit],
                "2," + rec(2, BLACK_ID) + rec(2, RED_ID) + rec(1, BLACK_ID),
            ),
            ("Dom_6", [skel, suit], "2," + rec(1, WHITE) + rec(7, BLACK_ID)),
            ("Dom_7", [skel, suit], None),
        ],
    )
    ex = str(tmp_path)
    assert [n["name"] for n in ce.variant_nodes(ex, "Dom")] == ["Dom_5", "Dom_5", "Dom_6", "Dom_7"]
    key = we.texture_key(SKIN)
    # one outfit
    assert ce.variant_sheets(ex, "Dom", "Dom_5", node=0) == {"suit": {key: "Black"}}
    assert ce.variant_sheets(ex, "Dom", "Dom_5", node=1) == {
        "suit": {key: "Red"},
        "boots": {key: "Black"},
    }
    # all models of the name in one GLB: each model from the first outfit that lists it
    assert ce.variant_sheets(ex, "Dom", "Dom_5") == {
        "suit": {key: "Black"},
        "boots": {key: "Black"},
    }
    assert ce.variant_sheets(ex, "Dom", "Dom_6") == {}  # first sheet / slot out of range
    assert ce.variant_sheets(ex, "Dom", "Dom_7") == {}
    assert ce.variant_sheets(ex, "Dom", "Missing") == {}
    assert ce.variant_sheets(ex, "NoSuchFragment", "x") == {}


def test_dominatrix_skin_is_no_longer_a_hard_coded_texture_swap():
    assert ce.TEX_OVERRIDES == {}
    sv = ce.SYNTH_VARIANTS[("Dominatrices", "Dominatrix_3")]
    assert list(sv["sheets"].values()) == ["Dominatrix1"]
