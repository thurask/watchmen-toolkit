"""Golden GLB output: fixed synthetic input through the two GLB writers, over the
switches a `pc_p2` export does not run, checked against a recorded fingerprint.

A change to `variant_glb.write_glb` or `rig_glb.build_rigged_glb` that is meant
to leave the output as it is must leave every case here passing.  A change that
is meant to alter the output re-records the table on purpose (the failure
message prints the new fingerprint) and says why.

Each case records the SHA-256 of the file bytes and a fingerprint.  The float
math (rotations, inverses, quaternions) does not give the same last bits on
every platform: Windows (Python 3.15, numpy 2.5) writes other last bits than
Linux into the float64 node transforms of the JSON, while the binary buffers
are the same.  So an equal SHA-256 passes a case, and otherwise the fingerprint
decides: an exact SHA-256 over everything but the float values (the JSON with
its numbers taken out, every integer and index byte, every image as pixels) and
four weighted sums of all float values (the JSON numbers and every float32
buffer view), which must agree to 1e-9 of their scale (measured between the two
platforms: 2e-17).  GLB_GOLDEN_STRICT=1 in the environment demands the SHA-256;
it holds where the table was recorded, Python 3.13 / numpy 2.5 on Linux x86-64.

Every input is built here or by the conftest / test-module builders with a
fixed seed; no game file is read.  The WATCHMEN_* switches are cleared first,
so the defaults are the code's own and each case sets only what it names.
"""

import hashlib
import io
import json
import os

import numpy as np
import pytest
from PIL import Image

import ragdoll_rig as rr
import rig_glb
import variant_glb as vg
import material_refs
import obj_mtl
from conftest import parse_glb

import test_frame as tfr
import test_face_rule as tface
import test_ragdoll_rig as trag
import test_rig_hierarchy as trh

FLOAT32 = 5126
#: weighted sums per file; the weights are exact small integers, so every
#: platform sums the same weights
SUMS = 4
TOLERANCE = 1e-9
STRICT = os.environ.get("GLB_GOLDEN_STRICT") == "1"


def _float_views(j):
    """Buffer views read only by float32 accessors."""
    kinds = {}
    for acc in j.get("accessors", []):
        if "bufferView" in acc:
            kinds.setdefault(acc["bufferView"], set()).add(acc["componentType"])
    return {k for k, t in kinds.items() if t == {FLOAT32}}


def _take_floats(obj, out):
    """The JSON with every float replaced by a marker; the floats go to `out`."""
    if isinstance(obj, float):
        out.append(obj)
        return "<f>"
    if isinstance(obj, dict):
        return {k: _take_floats(v, out) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_take_floats(v, out) for v in obj]
    return obj


def fingerprint(path):
    """-> (SHA-256 of the file, SHA-256 of everything but the floats,
    the weighted float sums, their scale)."""
    raw = open(path, "rb").read()
    glb = parse_glb(path)
    j = json.loads(json.dumps(glb.j))
    images = {im["bufferView"] for im in j.get("images", []) if "bufferView" in im}
    floats_bv = _float_views(j)
    h = hashlib.sha256()
    floats = []
    for k, bv in enumerate(j.get("bufferViews", [])):
        o, n = bv.pop("byteOffset", 0), bv["byteLength"]
        data = glb.bin_chunk[o : o + n]
        if k in images:
            # images as pixels: a writer that re-encodes with Pillow gets other
            # PNG bytes from another Pillow / zlib build
            del bv["byteLength"]
            im = Image.open(io.BytesIO(data))
            data = ("%s %dx%d " % (im.mode, *im.size)).encode() + im.tobytes()
        elif k in floats_bv and n % 4 == 0:
            floats.append(np.frombuffer(data, "<f4").astype(np.float64))
            data = b"float32 view"
        h.update(len(data).to_bytes(8, "little") + data)
    j.get("buffers", [{}])[0].pop("byteLength", None)
    json_floats = []
    h.update(json.dumps(_take_floats(j, json_floats), sort_keys=True).encode())
    v = np.concatenate(floats + [np.array(json_floats, np.float64)])
    i = np.arange(v.size, dtype=np.int64)
    w = np.stack([((i * (2 * s + 1) * 2654435761 + s) % 2001 - 1000) for s in range(SUMS)])
    w = w.astype(np.float64) / 1000.0
    sums = [float(x) for x in w @ v]
    scale = float(np.abs(w).max(axis=0) @ np.abs(v)) if v.size else 0.0
    return hashlib.sha256(raw).hexdigest(), h.hexdigest(), sums, scale


def _check(path, case):
    sha, content, sums, scale = fingerprint(path)
    new = {"sha256": sha, "content": content, "sums": sums, "scale": scale}
    ref = GOLDEN.get(case)
    msg = "%s: GLB output changed; now %r" % (case, new)
    assert ref is not None, msg
    if sha == ref["sha256"]:
        return
    assert not STRICT, msg
    assert content == ref["content"], msg
    tol = TOLERANCE * max(ref["scale"], 1.0)
    assert all(abs(a - b) <= tol for a, b in zip(sums, ref["sums"])), msg


@pytest.fixture
def clean_env(monkeypatch):
    for k in [k for k in os.environ if k.startswith("WATCHMEN_")]:
        monkeypatch.delenv(k)
    return monkeypatch


# Fixed PNG bytes: the inputs must not depend on how the installed Pillow / zlib
# compress (two builds of the same Pillow version write different IDAT bytes).
#: 4x4 RGBA (200, 150, 100), alpha 255 but 0 at (0, 0)
DIFFUSE_RGBA = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000004000000040806000000a9f19e7e0000001b49444154"
    "78da633c312d85818181e13f031430217360020c780500e05103c8a869156d0000000049454e44ae426082"
)
#: 4x4 RGB (128, 128, 255)
NORMAL_RGB = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000400000004080200000026930929000000144944415478"
    "da636c68f8cf00034c0c480037070064530207281792e30000000049454e44ae426082"
)
#: 2x2 RGB (90, 90, 90) and (128, 128, 255): test_frame.tface_png's two images
TFACE_PNG = {
    (90, 90, 90): bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a7300000016494441"
        "5478da638c8a8a6260606062606060606000000cd20112f8bddc500000000049454e44ae426082"
    ),
    (128, 128, 255): bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a7300000016494441"
        "5478da636c68f8cfc0c0c0c4c0c0c0c0c00000179f0203547ecca40000000049454e44ae426082"
    ),
}


def test_the_fixed_pngs_hold_the_pixels_they_name():
    rgba = np.asarray(Image.open(io.BytesIO(DIFFUSE_RGBA)))
    assert rgba.shape == (4, 4, 4) and (rgba[..., :3] == (200, 150, 100)).all()
    assert rgba[0, 0, 3] == 0 and (rgba[..., 3] == 255).sum() == 15
    assert (np.asarray(Image.open(io.BytesIO(NORMAL_RGB))) == (128, 128, 255)).all()
    for rgb, data in TFACE_PNG.items():
        assert (np.asarray(Image.open(io.BytesIO(data))) == rgb).all()


def _full_character(tmp_path, rig, name, monkeypatch):
    monkeypatch.setattr(tfr, "tface_png", lambda rgb=(90, 90, 90): TFACE_PNG[tuple(rgb)])
    return tfr._full_character(tmp_path, rig, name)


# ------------------------------------------------------------ write_glb inputs
def _blink_face(tmp_path, rig):
    """The face rig of test_face_rule with an EyeLid bone, a neutral pose named
    as the legacy rule looks for it and an eyes-closed pose (the legacy rule then
    writes its synthetic blink keys), plus the Open / Closed / DamageL poses the
    face class of test_face_rule names (the engine rule's track and idle cycle)."""
    names = np.array(["Bip01", "Neck", "Head", "Jaw", "EyeLid"])
    par = np.array([-1, 0, 1, 2, 2])
    Rb = np.tile(np.eye(3), (5, 1, 1))
    tb = np.array([[0, 0, 0], [0, 0.1, 0], [0, 0.2, 0], [0, 0.2, 0.05], [0, 0.25, 0.04]], float)
    bind = tmp_path / "bind_blink_face.npz"
    np.savez(bind, Rb=Rb, tb=tb, names=names, par=par)

    def pal(jaw_drop=0.0, lid=0.0):
        p = np.tile(np.eye(4)[:3], (1, 5, 1, 1)).astype(np.float32)
        p[0, 3, 1, 3] = -jaw_drop
        c, s = np.cos(lid), np.sin(lid)
        p[0, 4, :3, :3] = [[1, 0, 0], [0, c, -s], [0, s, c]]
        return np.repeat(p, 2, axis=0)

    anims = [
        ("FACE EN1/MouthClosed_EyesOpen", pal(), 2.0),
        ("FACE EN1/Open", pal(0.01), 2.0),
        ("FACE EN1/Closed", pal(0.01, 0.6), 2.0),
        ("FACE EN1/DamageL", pal(0.03), 2.0),
    ]
    V = np.array([[0, 0.2, 0], [0.02, 0.2, 0.05], [-0.02, 0.25, 0.05]], np.float32)
    SI = np.array([[2, 0, 0, 0], [3, 0, 0, 0], [4, 0, 0, 0]], np.uint16)
    SW = np.array([[1, 0, 0, 0]] * 3, np.float32)
    part = (V, SI, SW, np.array([[0, 1, 2]], np.uint32), np.zeros((3, 2), np.float32), "head")
    return dict(
        bind=str(bind),
        parts=[part],
        anims=anims,
        attach_idx=rig.NB - 1,
        M=np.eye(3),
        t=np.zeros(3),
        proxy_slots=[],
        proxy_align=None,
        auto_poses={nm.split("/")[-1]: p[0] for nm, p, _f in anims},
        blink_closed=pal(lid=0.6)[0],
        family="EN1",
        head="Test_Head",
    )


def _long_manifest(rig):
    """The rig's clip at 0.4 frames per second: 7.5 s, long enough for blink keys
    and for the idle cycle to change pose."""
    return [("clip_long", rig.palette, 0.4)]


def _face_meta():
    """anim_meta.build's shape for `clip_long`: a hit face from 1 s to 2 s."""
    track = [
        tface.seg(0.0, 1.0, "IDLE"),
        tface.seg(1.0, 2.0, "HitLeft", ["DamageL"]),
        tface.seg(2.0, None, "IDLE"),
    ]
    st = tface.body_state("Hit", "clip_long", track, duration_s=7.5)
    clip = {"used_by": [tface.used("Hit")], "pairs": [], "duration_s": 7.5}
    return tface.meta_with([st], {"clip_long": clip})


# ------------------------------------------------------------- write_glb cases
def test_write_glb_default(tmp_path, rig, clean_env):
    out = tmp_path / "default.glb"
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz))
    _check(out, "write_glb_default")


def test_write_glb_flat_rig(tmp_path, rig, clean_env):
    out = tmp_path / "flat.glb"
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz), rig="flat")
    _check(out, "write_glb_flat")


def test_write_glb_flat_rig_from_the_environment(tmp_path, rig, clean_env):
    clean_env.setenv("WATCHMEN_RIG", "flat")
    out = tmp_path / "flat_env.glb"
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz))
    _check(out, "write_glb_flat")


def test_write_glb_mirrored_frame(tmp_path, rig, clean_env):
    clean_env.setenv("WATCHMEN_FRAME", "mirrored")
    out = tmp_path / "mirrored.glb"
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz))
    _check(out, "write_glb_mirrored")


@pytest.mark.parametrize("rig_mode", ["hierarchy", "flat"])
def test_write_glb_legacy_face_rule_with_blinks(tmp_path, rig, clean_env, rig_mode):
    out = tmp_path / "legacy.glb"
    vg.write_glb(
        rig.parts,
        _long_manifest(rig),
        str(out),
        str(rig.bind_npz),
        face=_blink_face(tmp_path, rig),
        face_rule="legacy",
        rig=rig_mode,
    )
    _check(out, "write_glb_legacy_face_" + rig_mode)


@pytest.mark.parametrize("idle", [None, False])
def test_write_glb_engine_face_rule(tmp_path, rig, clean_env, idle):
    out = tmp_path / "engine_face.glb"
    vg.write_glb(
        rig.parts,
        _long_manifest(rig),
        str(out),
        str(rig.bind_npz),
        face=_blink_face(tmp_path, rig),
        meta=_face_meta(),
        face_idle=idle,
    )
    _check(out, "write_glb_engine_face" + ("_no_idle" if idle is False else ""))


def test_write_glb_engine_face_rule_without_metadata(tmp_path, rig, clean_env):
    out = tmp_path / "engine_face_neutral.glb"
    vg.write_glb(
        rig.parts, _long_manifest(rig), str(out), str(rig.bind_npz), face=_blink_face(tmp_path, rig)
    )
    _check(out, "write_glb_engine_face_neutral")


@pytest.mark.parametrize("attrs", ["1", "0"])
def test_write_glb_vertex_attributes_switch(tmp_path, rig, clean_env, attrs):
    clean_env.setenv("WATCHMEN_VERTEX_ATTRS", attrs)
    out = tmp_path / ("attrs_%s.glb" % attrs)
    parts = [tfr._attr_part(rig, 0.0, "mat_body"), tfr._attr_part(rig, 0.5, "mat_alpha", True)]
    vg.write_glb(parts, rig.manifest, str(out), str(rig.bind_npz))
    _check(out, "write_glb_vertex_attrs_" + attrs)


@pytest.mark.parametrize("normal", [False, True])
def test_write_glb_textures(tmp_path, rig, clean_env, normal):
    tex = {"diffuse": DIFFUSE_RGBA}
    if normal:
        tex["normal"] = NORMAL_RGB
    out = tmp_path / ("tex_%s.glb" % normal)
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz), textures={"mat_body": tex})
    _check(out, "write_glb_textures_normal" if normal else "write_glb_textures_plain")


@pytest.mark.parametrize("frame", ["true", "mirrored"])
def test_write_glb_everything(tmp_path, rig, clean_env, frame):
    """Face, weapon, hidden alternative, two outfits, pair metadata, ragdoll helpers
    and a normal map in one file (test_frame._full_character)."""
    clean_env.setenv("WATCHMEN_FRAME", frame)
    _full_character(tmp_path, rig, "full.glb", clean_env)
    _check(tmp_path / "full.glb", "write_glb_everything_" + frame)


def test_write_glb_everything_flat(tmp_path, rig, clean_env):
    clean_env.setenv("WATCHMEN_RIG", "flat")
    _full_character(tmp_path, rig, "full_flat.glb", clean_env)
    _check(tmp_path / "full_flat.glb", "write_glb_everything_flat")


def test_write_glb_attachments_without_a_parts_record(tmp_path, rig, clean_env):
    out = tmp_path / "attach.glb"
    wpn = [("WPN_Bat", [(rig.V + np.float32(3.0),) + rig.parts[0][1:5] + ("bat",)])]
    vg.write_glb(rig.parts, rig.manifest, str(out), str(rig.bind_npz), attachments=wpn)
    _check(out, "write_glb_attachments")


def test_write_glb_ragdoll_helpers_alone(tmp_path, rig, clean_env):
    model = rr.build(trag.build_model())
    names = list(trag.BIND_NAMES)
    np.savez(rig.bind_npz, Rb=rig.Rb, tb=rig.tb, names=np.array(names), par=rig.par)
    out = tmp_path / "ragdoll.glb"
    vg.write_glb(
        rig.parts,
        rig.manifest,
        str(out),
        str(rig.bind_npz),
        ragdoll=rr.glb_helpers(model, names, rig.Rb, rig.tb),
    )
    _check(out, "write_glb_ragdoll")


# ------------------------------------------------------- build_rigged_glb inputs
def _legacy_clips(rig):
    F = rig.F
    locT = np.zeros((F, rig.NB, 3), np.float32)
    locQ = np.zeros((F, rig.NB, 4), np.float32)
    for f in range(F):
        for k in range(rig.NB):
            locT[f, k] = rig.tb[k] + 0.01 * f
            q = np.array([0.1 * k, 0.2, 0.3 + 0.05 * f, 1.0])
            locQ[f, k] = q / np.linalg.norm(q)
    return [
        {
            "name": "clip_test",
            "times": (np.arange(F) / rig.fps).astype(np.float32),
            "locT": locT,
            "locQ": locQ,
            "locS": None,
        }
    ]


def _texture_index(tmp_path, asset):
    """A texture tree with one diffuse layer and its sheet, as `extract` writes it."""
    root = tmp_path / "textures"
    d = root / asset.strip("/")
    d.mkdir(parents=True)
    (d / "0_diffuse_4x4_DXT5.png").write_bytes(DIFFUSE_RGBA)
    (d / "1_normal_4x4_ATI2.png").write_bytes(NORMAL_RGB)
    sheet = {"renderType": 0, "blendType": 0, "opacity": 1.0, "specularPower": 20.0}
    (d / "sheet.json").write_text(json.dumps(dict(sheet, sheets=[dict(sheet, name="default")])))
    return obj_mtl.TextureIndex(root)


def _rigged(path, rig, clips=None, **kw):
    rig_glb.build_rigged_glb(
        path,
        rig.V,
        None,
        rig.UV,
        rig.SI.astype(np.uint8),
        rig.SW,
        rig.T,
        [(0, rig.NV, 0, len(rig.T), 56)],
        kw.pop("materials", ["mat_body"]),
        kw.pop("tex_index", {}),
        rig.tpl(),
        clips,
        None,
        **kw,
    )


# ------------------------------------------------------- build_rigged_glb cases
@pytest.mark.parametrize("clips", [False, True])
def test_rigged_skinned_without_a_node_table(tmp_path, rig, clean_env, clips):
    out = tmp_path / "rigged.glb"
    _rigged(out, rig, _legacy_clips(rig) if clips else None)
    _check(out, "rigged_skinned_clips" if clips else "rigged_skinned")


@pytest.mark.parametrize("rig_mode", ["hierarchy", "flat"])
def test_rigged_skinned_with_the_header_node_table(tmp_path, clean_env, rig_mode):
    nodes, _hdr = trh._nodes()
    out = tmp_path / ("nodes_%s.glb" % rig_mode)
    trh._skinned_glb(out, nodes, rig=rig_mode)
    _check(out, "rigged_nodes_" + rig_mode)


def test_rigged_skinned_with_the_header_node_table_mirrored(tmp_path, clean_env):
    clean_env.setenv("WATCHMEN_FRAME", "mirrored")
    nodes, _hdr = trh._nodes()
    out = tmp_path / "nodes_mirrored.glb"
    trh._skinned_glb(out, nodes)
    _check(out, "rigged_nodes_mirrored")


@pytest.mark.parametrize("engine", [False, True])
def test_rigged_static_materials(tmp_path, rig, clean_env, engine):
    asset = "/art/props/Crate_01.bmp"
    idx = _texture_index(tmp_path, asset)
    out = tmp_path / ("static_%s.glb" % engine)
    _rigged(
        out,
        rig,
        static=True,
        materials=[material_refs.texture_ref(asset)],
        tex_index=idx,
        normals=np.tile(np.array([[0.0, 0.0, 1.0]], np.float32), (rig.NV, 1)),
        has_color=[False],
        has_alpha=[False],
        engine_materials=engine,
    )
    _check(out, "rigged_static_engine" if engine else "rigged_static_plain")


@pytest.mark.parametrize("engine", [False, True])
def test_rigged_skinned_materials(tmp_path, rig, clean_env, engine):
    asset = "/art/characters/c/Body_01.bmp"
    idx = _texture_index(tmp_path, asset)
    out = tmp_path / ("skinned_%s.glb" % engine)
    _rigged(
        out,
        rig,
        materials=[material_refs.texture_ref(asset)],
        tex_index=idx,
        has_color=[False],
        has_alpha=[False],
        engine_materials=engine,
    )
    _check(out, "rigged_skinned_engine" if engine else "rigged_skinned_plain")


GOLDEN = {
    "rigged_nodes_flat": {
        "sha256": "bc72b1e63abf1581be239d6d2b46b1fdc58934b41d0af45849b200bb384f4951",
        "content": "23c5135faa839cf054a65b04279164a0d01f43fd86fe5495fd8eb753157b402d",
        "sums": [-3.467629666211587, -7.3350981482530395, 3.068107273410224, -3.5146233345717555],
        "scale": 70.36329295055207,
    },
    "rigged_nodes_hierarchy": {
        "sha256": "addefb01db0940548ebbc7dc7407fc5d6916f8b6430584edc2772f920d97882c",
        "content": "ffe74feaf7dbfb2eba4d487f4c525ec7abc747ce4796b05bc38102b3d8928bff",
        "sums": [2.018109359443132, 1.190354400379727, 0.5297329212265331, 0.03844294109634161],
        "scale": 160.04818648116006,
    },
    "rigged_nodes_mirrored": {
        "sha256": "19b14d79924ec31c74930fb588783f58609d763ad5e24e3f3c53430913049bb3",
        "content": "ae659c4de8b48b25b4c018fef9d626a89562b814891ff84e13cb4d64a6bfc019",
        "sums": [-6.430940036698621, -6.158840526936616, 4.976863569388249, 5.8409758092859345],
        "scale": 160.07687301970734,
    },
    "rigged_skinned": {
        "sha256": "edfd3d1021b8443e8374eb2efac13c430a45b770344c81e26760bd584437edf8",
        "content": "fa71fc9a705296711041131445b8660b7a7d411c6c90ca90348975917adf3001",
        "sums": [-6.389887933440357, -10.875962694695144, 0.707118923959434, -4.265435023339689],
        "scale": 39.54755830564111,
    },
    "rigged_skinned_clips": {
        "sha256": "392cdc79346a147edfa02919919ebeaba223735c17c2419f40c02c2027e92b78",
        "content": "a06de12d67c987f077476514ada813854d4ee00f7b280ad879fb47b5b6cf2b27",
        "sums": [-9.624698146281167, -15.85353626810476, 0.1915793060615647, -3.30850385151677],
        "scale": 92.27008153631775,
    },
    "rigged_skinned_engine": {
        "sha256": "b660716b80d48bd7764edcc98817eb3a1c355ab28173ad4fecbd3dd6426ec6d6",
        "content": "3485796fa25eba2ba3e32f7ef2a1f1a060fe796e6af2b9526605a7bcdff22ac6",
        "sums": [-0.5129034334403575, -24.255506694695146, 4.850426923959434, -20.918425023339687],
        "scale": 60.258001305641116,
    },
    "rigged_skinned_plain": {
        "sha256": "61552a7750a19cb878cb43fb093a42464b94da4a9c887fe2aef41083a12cd64d",
        "content": "20abd72c0569c1fd9cfa0d833058e679d27ab396bb183ee8332077de44344ac5",
        "sums": [-6.392677933440357, -10.884332694695146, 0.4330389239594339, -3.104375023339689],
        "scale": 38.12754830564111,
    },
    "rigged_static_engine": {
        "sha256": "2cf70305b9454462f3ec11602433597c7fb20110da3e84a91844bd8a2c1f6bef",
        "content": "755d685333e4307cf3b6dd9af6e7fa3f52f0d9ca285127d75f4423e11bced1da",
        "sums": [2.6989578692203473, 11.779100903577714, -8.421646571538867, -3.51544088925767],
        "scale": 42.64775844361793,
    },
    "rigged_static_plain": {
        "sha256": "c96724c2302eed3812fd9f867a3bd5d97710dc91afb4c0f3e76e6bdd09ed2b48",
        "content": "b757cdf605ccd858c980792d43382f34cb101ff38a9d0c2ea664e0dc8db249e5",
        "sums": [0.8619908692203468, -2.7413025964222846, 7.375002928461133, 0.2981221107423304],
        "scale": 22.03409894361794,
    },
    "write_glb_attachments": {
        "sha256": "2c65953d79822585934f5be59a87e0717f424d4617f9552c16035ba4271e24b2",
        "content": "d93dd689894fe6970a211d00707ec3855e5d26f8ccdef453f68394ffbe58a496",
        "sums": [-2.3474017603311044, 4.368203459906017, 5.545646673367137, -13.533553633171985],
        "scale": 174.91041271770848,
    },
    "write_glb_default": {
        "sha256": "93029fb0cd663b8f2d2f1168d5d7688d28770602a0d3d7fb541c0604b1318d43",
        "content": "9254ac6f94de9a81cb32039de66a1f5470bcae38f3acf633e61fcab0a15c297a",
        "sums": [0.9743112418322676, -2.226383802676568, -8.12738760731173, -5.257583055503086],
        "scale": 90.63025601252009,
    },
    "write_glb_engine_face": {
        "sha256": "719259f393747d56f84f8b46ce1a5319faf8a6a9fe54535a6f24522450bda93f",
        "content": "7b4d4fa1b203c13f2edefe6b75c1cae9a134b21b94423ffa4dbfc4ef1d010b4c",
        "sums": [4.831777129233279, -10.882588405872488, 15.00712375590815, 9.78177639830425],
        "scale": 249.57033059009476,
    },
    "write_glb_engine_face_neutral": {
        "sha256": "e6bf1ce7fecf46bb25f7acab218a2aecdee8214f199d952666e1445eb3ceb4b2",
        "content": "26463e0355a41bcc188079f744d95e9d308264acadef7338f51a0ca3c599f46a",
        "sums": [-0.5104112338690244, -28.31709202851956, -2.801216894969954, -5.013680687736366],
        "scale": 176.18261750909994,
    },
    "write_glb_engine_face_no_idle": {
        "sha256": "72e2baadf37b361c920e8054e8a1638d6df3acfd7fb23c972d181c2882de4de6",
        "content": "c9077e9999fbc4a4fc0ebe57e1d3344a1fc25da565f0dd3edd8eea493bf2e444",
        "sums": [8.885582573559212, -22.54733967145633, 15.436011721250603, -5.787718289496505],
        "scale": 211.4802956424721,
    },
    "write_glb_everything_flat": {
        "sha256": "4133d5556b96c84f0716ed61f054719715186cb279b04058184c2f1e438f09ca",
        "content": "90c26d7d3d26fa72b3977db6656d3d56993d6e25dd2dada2d681a10952705dd5",
        "sums": [1054.7087436559161, 264.406599396647, 155.16838749857683, -756.3746277473322],
        "scale": 3272.5807204169255,
    },
    "write_glb_everything_mirrored": {
        "sha256": "5100659c24ecb293abefe9a69df5a2b5f35d77ec83fed133dfa2ada7cb3890b0",
        "content": "ca2f9c46ba6b39cfa00fafe0606d7de0a68227fac3c2ee47bb066ce50b81cb38",
        "sums": [130.15539448476648, -152.5860815885296, -300.29866686463464, -74.06348997225717],
        "scale": 3790.0608830581764,
    },
    "write_glb_everything_true": {
        "sha256": "39d53b4e78a928f93c817c62a2dfdef69ea5043022fbd5232c33f9d0f0c1a718",
        "content": "280ae38de607f57c5508448640e6f4ef4e82a00cacb532622e8adf0a9777c544",
        "sums": [57.99523228736024, 75.99614716923153, -235.313802209938, -309.8863495690705],
        "scale": 3790.472313701768,
    },
    "write_glb_flat": {
        "sha256": "1a67b7999e90764d56e98c339826a76c0109668069c1c9ede0cccb46c3eb4419",
        "content": "55cb865e0159dc9f22703daed3dda4e39ee93bb0a9d821be4a76774e99394908",
        "sums": [1.1244016118121496, -4.73578010679396, -9.098163232940854, -7.556055842410385],
        "scale": 100.90966916885893,
    },
    "write_glb_legacy_face_flat": {
        "sha256": "7ccdf85897b25c0487a555ea6298c361a4eb2ae86e324b27ec63626356c0ed11",
        "content": "a64a8d41c673db9428bbd368deb6c2d1117bd041fd5111479cedb40a5e4e3a7c",
        "sums": [-5.807558656017723, -8.454431517696074, -31.613055692811393, 19.25867635574887],
        "scale": 235.9253534203024,
    },
    "write_glb_legacy_face_hierarchy": {
        "sha256": "8a3c036de9491863d38a336d8f798d02e37648a4fa922d5bb7d01928ecc1c73d",
        "content": "eb1025fd9c1031e0766c36a801e874a3bc85418550bf456e4dc368eb33c45c92",
        "sums": [-2.603601465047235, -13.328758669011002, -22.822448619318752, -2.0542568464873376],
        "scale": 226.2984945855902,
    },
    "write_glb_mirrored": {
        "sha256": "672ed4086cbeec6cad003a9b923ff922299718683bb5da6cebc914808e05403f",
        "content": "51eaddb83b794a23920ce8a40c811cd12a8fcbe1b212b1d50e209ce6147d5329",
        "sums": [2.916663461828508, -1.1901925491301737, -9.279984042981258, -4.65195308239612],
        "scale": 90.68894234075238,
    },
    "write_glb_ragdoll": {
        "sha256": "4c00487b10f519b3a8b2ca943915eb6d22b7999fe1172712508d65faa127ac98",
        "content": "1ad227b7fd96bce1b033a5a317e6468c4b4357d941d8d4bfacbda2a58a2b1eb5",
        "sums": [-64.6909725109081, 424.0617293581257, -1267.451860866182, 19.668198892311466],
        "scale": 2773.501193713213,
    },
    "write_glb_textures_normal": {
        "sha256": "d3062844ae05cff2cd20c51f658a7a276d990200a0ac0e84e3a4e63281ec7514",
        "content": "8795e6ad4075da346962a7ea9e2f36ff4162c4a0ffecd80b45ef9a07d9251da1",
        "sums": [1.6491212418322676, -1.7627338026765682, -7.914917607311731, -5.296293055503085],
        "scale": 88.5736060125201,
    },
    "write_glb_textures_plain": {
        "sha256": "fa7d20a19922d5bec9cc14c3dd02c4202c897477298d1b8182db1add94417c90",
        "content": "e1428e1317512455ab21ffd862eda78ef3cf2502ee3f33734e04db29d3a18f58",
        "sums": [1.6491212418322676, -1.7627338026765682, -7.914917607311731, -5.296293055503085],
        "scale": 88.5736060125201,
    },
    "write_glb_vertex_attrs_0": {
        "sha256": "f1f72e653ae226b91a4d14f320daabd74a9088a18201f075abe12e4c06b0d217",
        "content": "8b94c1e7fd187c90385c21f0f92f691226291a0bbdc5ca48fcb929936ef50198",
        "sums": [-4.759902077815236, -2.8692965383952505, -1.5143534231923867, -5.40855382798977],
        "scale": 118.63005625141514,
    },
    "write_glb_vertex_attrs_1": {
        "sha256": "c508affd23505609dd5c7a3f79cb4c658cf8b4811fef4035b5d4a3d6bea7ff63",
        "content": "28b11f28c9e391cf13418a40bbeabd044af32523ef88433e630d469ce0cd5626",
        "sums": [4.939648325553859, -6.297665747232289, -12.370444041157526, -8.602257192500682],
        "scale": 169.94366564507345,
    },
}
