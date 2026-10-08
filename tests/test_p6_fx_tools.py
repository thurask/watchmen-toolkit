"""Final sweep, effects / cameras and tools.

    F10   the gameplay cameras as data, with reference functions
    F02 / F05 / F07 / F12   the settled points of the fx tables
    V10   character GLBs: unused joint slots are 0 and attribute / index buffer views
          carry their target
    A38   `watchmen char`: clip lengths from the extract, the archive as an argument,
          a stored animation table is reused
    V03   tools/blender_attach_extras.py

Synthetic fixtures only."""

import json
import math
import os
import struct
import sys

import numpy as np
import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import bake_v4
import characters_export as ce
import fx_meta as fx
import level_meta
import variant_glb as vg

import blender_attach_extras as bae
import test_combat_meta
import test_level_meta as tl
from conftest import build_clip_header, parse_glb

combat_extract = test_combat_meta.extract


# ------------------------------------------------------------ camera helpers
def test_power_smooth_and_symmetric_halfbell():
    assert fx.power_smooth(0.5, 1.5, 1) == 0.5
    assert fx.power_smooth(0.25, 1.5, 1) == pytest.approx(0.5 * 0.5**1.5)
    assert fx.power_smooth(0.75, 1.5, 1) == pytest.approx(1 - 0.5 * 0.5**1.5)
    assert fx.power_smooth(-3, 2.0) == 0.0 and fx.power_smooth(7, 2.0) == 1.0
    assert fx.power_smooth(0.5, 2.0, 2.0) == pytest.approx(0.5 * (2 * 0.25) ** 2.0)
    assert fx.symmetric_halfbell(0.5) == pytest.approx(0.5)
    assert fx.symmetric_halfbell(0.0) == 0.0 and fx.symmetric_halfbell(2.0) == pytest.approx(1.0)
    assert fx.symmetric_halfbell(0.25) == pytest.approx(0.5 * (1 - math.cos(math.pi / 4)))


def test_pvp_camera_of_the_reference_case():
    r = fx.pvp_camera([-1, 0, 0], [1, 0, 0], [0, 0, 5], [0, 0, -9], 40, 1.0, 0.0, 16 / 9)
    hfov = math.radians(40) * 16 / 9
    assert (
        r["distance"] == pytest.approx(3.0 / math.tan(hfov / 2)) == pytest.approx(4.197, abs=2e-3)
    )
    assert r["look_at"] == pytest.approx([0.0, 1.0, 0.0])
    assert r["position"] == pytest.approx([0.0, 1.0, -r["distance"]])
    # the pitch lifts the camera by D tan(pitch); the distance along the line is the same
    p = fx.pvp_camera([-1, 0, 0], [1, 0, 0], [0, 0, 5], [0, 0, -9], 40, 1.0, 0.45, 16 / 9)
    assert p["distance"] == pytest.approx(r["distance"])
    assert p["position"][1] == pytest.approx(1.0 + r["distance"] * math.tan(0.45))
    # the hero closest to the camera sets the distance: its offset from the centre -> pivot line
    far = fx.pvp_camera([-1, 0, 0], [5, 0, 0], [2, 0, 5], [5, 0, -9], 40, 1.0, 0.0, 16 / 9)
    assert far["distance"] == pytest.approx((3.0 + 2.0) / math.tan(hfov / 2))
    # the clamps
    assert (
        fx.pvp_camera([0, 0, 0], [0, 0, 0], [0, 0, 1], [0, 0, -1], 170, 0, 0, 2)["distance"] == 2.0
    )
    # the true frame is the x-negated one
    t = fx.pvp_camera([1, 0, 0], [-5, 0, 0], [-2, 0, 5], [-5, 0, -9], 40, 1.0, 0.0, 16 / 9, "true")
    assert t["position"] == pytest.approx(
        [-far["position"][0], far["position"][1], far["position"][2]]
    )
    with pytest.raises(ValueError):
        fx.pvp_camera([0, 0, 0], [1, 0, 0], [0, 0, 1], [0, 0, -1], 40, 1, 0, 1, frame="x")


def test_exploration_camera_pose():
    r = fx.exploration_camera([0, 0, 0], 0.0, 0.0, 3.0, 0.0, 1.2, 3.0)
    assert r["look_at"] == pytest.approx([0, 1.2, 0]) and r["position"] == pytest.approx(
        [0, 1.2, -3]
    )
    # positive pitch puts the camera above the look-at
    up = fx.exploration_camera([0, 0, 0], 0.0, 0.5, 3.0, 0.0, 1.2, 3.0)
    assert up["position"][1] > 1.2 and np.linalg.norm(up["look_dir"]) == pytest.approx(1.0)
    assert np.linalg.norm(np.subtract(up["position"], up["look_at"])) == pytest.approx(3.0)
    # the side offset scales with the actual distance and is clamped at the state distance
    off = fx.exploration_camera([0, 0, 0], 0.0, 0.0, 1.5, -0.6, 1.2, 3.0)
    assert off["look_at"] == pytest.approx([0.3, 1.2, 0.0])  # -right * 1.5 * (-0.6 / 3)
    wide = fx.exploration_camera([0, 0, 0], 0.0, 0.0, 1.5, -9.0, 1.2, 3.0)
    assert wide["look_at"] == pytest.approx([1.5, 1.2, 0.0])
    t = fx.exploration_camera([0, 0, 0], 0.0, 0.0, 1.5, -0.6, 1.2, 3.0, frame="true")
    assert t["look_at"] == pytest.approx([-0.3, 1.2, 0.0])


# ------------------------------------------------------------------ fx tables
def test_gameplay_cameras_are_in_the_table(tmp_path):
    t = fx.tables(str(tmp_path))
    g = t["camera"]["gameplay"]
    assert set(g) == {"combat", "exploration", "pvp", "helpers", "evidence"}
    assert "0x64cee1" in g["evidence"] and "not checked in game" in g["evidence"]
    c = g["combat"]
    assert c["update"] == "0x64cee1" and c["output_lowpass_s"] == 0.2
    assert c["rate_factor"]["target_front"] == "when the rate already has the sign of the push"
    assert "x <= 0.1" in c["quarantine_note"] and "nfovtimer = 0" in c["reset_entry"]
    assert len(c["formulas"]) == 22 and c["formulas"][0].startswith("entry:")
    assert any(f.startswith("7b target bias") and "f = 2 when rate > 0" in f for f in c["formulas"])
    e = g["exploration"]
    assert (
        e["stick_states"]["WALK"] == "0.1 < move < 0.6 (exactly 0.1: no change)"
        and e["fall_in"]["speed_gate_mps"] == 1.0
    )
    assert e["buttons"] == {"0x22": 16, "0x23": 17, "0x12": 26}
    assert g["pvp"]["focus_class"] == "PlayerVsPlayerFocusPoint" and len(g["pvp"]["formula"]) == 7
    json.dumps(t)


def test_settled_points_of_the_fx_tables(tmp_path):
    t = fx.tables(str(tmp_path))
    text = " | ".join(t["not_established"])
    for gone in (
        "useRealtime",
        "truth1 call",
        "sine argument",
        "effect ids fired by",
        "fake weapon",
    ):
        assert gone not in text, gone
    assert "GLB-space transform of a character attachment" not in text
    cp = t["camera"]["cut_placement"]
    assert "0xe14304" in cp["transition"] and "useRealtime is set" not in cp["transition"]
    assert "sphere of radius 0.1" in cp["validity"] and "25 m" in cp["validity"]
    assert "DoContinue(3) 0x6269bc" in cp["hard_cut_push_in"]
    assert cp["return_in_vector"]["pitch_y"] == -0.3 and cp["return_in_vector"]["yaw_rad"] == -0.8
    shake = t["camera"]["modifiers"]["cut_shake"]["rule"]
    assert "sin(time_factor * t)" in shake and "0x643d95" in shake and "inferred" not in shake
    by = t["event_effects"]["by_event"]
    assert {k: v["effect_ids"] for k, v in by.items()} == {
        "29": [8],
        "30": [],
        "31": [],
        "60": [12, 13],
        "69": [1, 10],
    }
    assert by["29"]["name"] == "FLASH_GRENADE" and "fires id 0" in by["30"]["note"]
    senders = t["rumble"]["senders"]
    assert len(senders) == 8 and not any("event 56" in s["source"] for s in senders)
    assert senders[0] == {
        "source": "command_force_counter_attack 0x6867b7",
        "to": "partner's PlayerCtrl",
        "duration_s": 1.0,
        "power": 0.4,
        "fade": True,
    }
    assert "null in shipped data" in t["fake_twilight_lady_weapon"]
    f = t["event_fields"]["56"]["fields"]
    assert f["m_nvalue"]["arg"] == "override_damage"
    assert "SetCloseCombatDamageToTarget" in f["m_ttruth1"]["meaning"]
    assert (
        "looking from the actor toward the partner"
        in t["event_fields"]["61"]["fields"]["m_ttruth1"]["meaning"]
    )
    assert "translation (-p.x, p.y, p.z)" in fx._ATTACHMENT_SPACE


def test_an_impact_effects_event_that_deals_damage_says_so():
    e = {"playpos": 0.5, "time_s": 1.0, "play_time_s": 1.0}
    a = {"damage_pose": 8, "truth1": True, "override_damage": 35.0}
    out = fx._impact(e, a)
    assert out["deals_damage"] is True and out["override_damage"] == 35.0
    assert out["truth1"] is True and out["value"] == 35.0  # the first names, kept
    plain = fx._impact(e, {"damage_pose": 8})
    assert "deals_damage" not in plain and "truth1" not in plain


def test_camera_states_say_what_selects_them():
    assert fx.CAMERA_CHARACTER_DB_USE[16] == "button 0x22: centre behind"
    assert {fx.CAMERA_CHARACTER_DB[k] for k in fx.CAMERA_CHARACTER_DB_USE} == {
        "FORCE_BEHIND",
        "LOOK_AT_PARTNER",
        "HELPER",
        "RUN",
        "WALK",
        "IDLE",
    }
    import inspect

    src = inspect.getsource(fx.FxDB.camera_rig)
    assert 'it["use"] = CAMERA_CHARACTER_DB_USE[cid]' in src and "_RIG_PROPERTY_USE" in src
    assert "CameraPlayerVsPlayer._nsmoothing" in fx._RIG_PROPERTY_USE


def test_property_store_flags_table():
    here = os.path.dirname(os.path.abspath(__file__))
    with open(
        os.path.join(here, "..", "wlib", "property_store_flags.json"), encoding="utf-8"
    ) as fh:
        j = json.load(fh)
    assert len(j["bit0_not_stored"]) == 61 and len(j["bit1_deprecated_alias"]) == 56
    assert len(j["bit3"]) == 16 and len({r["site"] for r in j["bit3"]}) == 16
    assert {(r["class"], r["property"]) for r in j["bit3"]} >= {
        ("CollisionNode", "pivotBookAssetRef"),
        ("ParticleType", "initializers"),
        ("Sheet", "isVolatile"),
    }
    assert {"class", "property", "site"} <= set(j["bit0_not_stored"][0])
    names = {(r["class"], r["property"]) for r in j["bit1_deprecated_alias"]}
    assert ("ParticleType", "localMode") in names


# ----------------------------------------------------------------- level export
def test_level_cameras_name_the_pvp_focus_point_and_auto_sequences_are_listed():
    import inspect

    src = inspect.getsource(level_meta._section_cameras)
    assert 'n.cls == "PlayerVsPlayerFocusPoint"' in src and '"pvp_focus": focus' in src
    src = inspect.getsource(level_meta._section_auto_sequences)
    assert 'n.p("autoStart")' in src and '"PropertySequenceNode"' in src

    class N:
        def __init__(self, cls, name, **p):
            self.cls, self.name, self.props, self.type = cls, name, p, cls

        def p(self, k, d=None):
            return self.props.get(k, d)

    class Lv:
        def __init__(self, nodes):
            self.level = nodes
            self.uid = {id(n): "u%d" % i for i, n in enumerate(nodes)}
            self.enabled = {id(n): True for n in nodes}

        def brief(self, n):
            return {"uid": self.uid[id(n)], "name": n.name}

        def path(self, n):
            return "Camera/" + n.name

        def placement(self, n):
            return {"world": {"pos": n.p("localPos")}}

    nodes = [
        N("PlayerVsPlayerFocusPoint", "Focus", localPos=[0.5, 46.7, -21.3]),
        N(
            "PropertySequenceNode",
            "Pulse",
            autoStart=True,
            sequence="/a/RageMaterialPulse.sequence",
        ),
        N("PropertySequenceNode", "Door", autoStart=False, sequence="/a/Door.sequence"),
    ]
    lv = Lv(nodes)
    cams = level_meta._section_cameras(lv)
    assert cams["tours"] == [] and cams["camera_nodes"] == []
    assert cams["pvp_focus"] == [
        {"uid": "u0", "name": "Focus", "path": "Camera/Focus", "world": {"pos": [0.5, 46.7, -21.3]}}
    ]
    assert level_meta._section_auto_sequences(lv) == [
        {
            "uid": "u1",
            "name": "Pulse",
            "path": "Camera/Pulse",
            "sequence": "/a/RageMaterialPulse.sequence",
            "enabled": True,
            "speed_factor": 1.0,
            "update_culling_distance": 0.0,
            "actions": 0,
        }
    ]
    assert tl is not None  # the level feature's own tests cover the full export


def test_scene_ctrl_names_the_override_models():
    class N:
        def __init__(self, cls, name, **p):
            self.cls, self.name, self.props = cls, name, p

        def p(self, k, d=None):
            return self.props.get(k, d)

    dry = N(
        "Character",
        "",
        modelNames=["/Art/Characters/rorschach/models/Rorschach_Dry.model", ""],
        textureSheetsDescription="2,0,0,0,/a/RorschachHat.bmp,1,",
    )
    rage = N("Character", "Rorschach_Rage", modelNames=["/a/Rorschach_Dry.model"])
    ctrl = N(
        "LevelSceneCtrl",
        "",
        _emodelrsh={"ref": "1"},
        _emodelrshrage={"ref": "2"},
        _emodelntoflashing={"etag": 0},
    )

    class Lv:
        level = [ctrl, dry, rage, N("Folder", "x")]
        uid = {id(ctrl): "c", id(dry): "d", id(rage): "r"}
        enabled = {id(dry): False, id(rage): False}

        def brief(self, n):
            return {"uid": self.uid[id(n)], "class": n.cls, "name": n.name}

        def resolve(self, n, prop):
            return {"_emodelrsh": dry, "_emodelrshrage": rage}.get(prop)

    (rec,) = level_meta._section_scene_ctrl(Lv())
    m = rec["override_models"]
    assert rec["uid"] == "c" and sorted(m) == ["nto_flashing", "rsh", "rsh_rage"]
    assert m["nto_flashing"] is None  # a null reference; `nto` is not stored at all
    assert m["rsh"] == {
        "uid": "d",
        "name": "",
        "model": "/Art/Characters/rorschach/models/Rorschach_Dry.model",
        "enabled": False,
        "textureSheetsDescription": "2,0,0,0,/a/RorschachHat.bmp,1,",
    }
    assert m["rsh_rage"]["note"] == level_meta.RSH_RAGE_NOTE and "inferred" in m["rsh_rage"]["note"]


# ----------------------------------------------------------- GLB validator items
def test_unused_joint_slots_are_zero_and_buffer_views_carry_their_target(rig, tmp_path):
    V, SI, SW, T, UV, nm = rig.parts[0]
    SW = SW.copy()
    SI = SI.copy()
    SW[0] = [1, 0, 0, 0]  # a rigid one-bone vertex: all four slots name the bone
    SI[0] = [3, 3, 3, 3]
    SW[1] = [0.5, 0.5, 0, 0]
    SI[1] = [2, 4, 1, 1]
    out = tmp_path / "v.glb"
    vg.write_glb([(V, SI, SW, T, UV, nm)], rig.manifest, str(out), str(rig.bind_npz))
    g = parse_glb(out)
    prim = g.j["meshes"][0]["primitives"][0]
    J = g.accessor(prim["attributes"]["JOINTS_0"])
    W = g.accessor(prim["attributes"]["WEIGHTS_0"])
    assert (J[W == 0] == 0).all()
    assert J[0].tolist() == [3, 0, 0, 0] and J[1].tolist() == [2, 4, 0, 0]
    assert (J[W > 0] == SI[SW > 0]).all()  # nothing with weight moves
    assert (SI[0] == 3).all()  # the caller's array is not modified

    def target(acc):
        return g.j["bufferViews"][g.j["accessors"][acc]["bufferView"]].get("target")

    for key in ("POSITION", "JOINTS_0", "WEIGHTS_0", "TEXCOORD_0"):
        assert target(prim["attributes"][key]) == 34962, key
    assert target(prim["indices"]) == 34963
    # animation, inverse-bind and image views have none (the validator asks for none)
    skin = g.j["skins"][0]
    assert target(skin["inverseBindMatrices"]) is None
    for s in g.j["animations"][0]["samplers"]:
        assert target(s["input"]) is None and target(s["output"]) is None


# --------------------------------------------------------------- `watchmen char`
def test_char_takes_each_clips_length_from_the_extract(tmp_path, monkeypatch, capsys):
    import watchmen

    ex = tmp_path / "OUT"
    frag = ex / "extracted" / "TNT" / "Fragments" / "Enemy" / "X.fragment.json"
    frag.parent.mkdir(parents=True)
    frag.write_text(
        '{"instances": [{"name": "V", "model_ref": ["/a/Skel_Skeleton.model", "/a/Body.model"]}]}'
    )
    d = ex / "extracted" / "Animation" / "EN4" / "COM"
    d.mkdir(parents=True)
    (d / "EN4_COM_ATT_light_A.animation").write_bytes(build_clip_header(59, 2.9))
    (d / "EN4_COM_ATT_spaced .animation").write_bytes(build_clip_header(59, 2.9))
    bank = watchmen.char_clip_bank(str(frag))
    assert set(bank) == {"EN4_COM_ATT_light_A", "EN4_COM_ATT_spaced"}
    assert watchmen.char_clip_bank(str(tmp_path / "elsewhere" / "X.fragment.json")) == {}

    bind = tmp_path / "bind_skel_file_v1.npz"
    np.savez(
        bind, Rb=np.tile(np.eye(3), (2, 1, 1)), tb=np.zeros((2, 3)), names=np.array(["A", "B"])
    )
    bakedir = tmp_path / "bake"
    bakedir.mkdir()
    A = np.zeros((59, 2, 3, 4), np.float32)
    A[:, :, :, :3] = np.eye(3)
    np.save(bakedir / "EN4_COM_ATT_light_A.npy", A)
    np.save(bakedir / "EN4_COM_ATT_unknown.npy", A)
    seen = {}
    monkeypatch.setattr(vg, "load_parts", lambda meshes, pal, naz=None: seen.update(naz=naz) or [])
    monkeypatch.setattr(
        vg, "write_glb", lambda parts, manifest, out, bindp, **k: seen.update(m=manifest)
    )
    vg.build(
        str(frag),
        "V",
        str(tmp_path / "o.glb"),
        bakedir=str(bakedir),
        bank=bank,
        bind=str(bind),
        naz="my.naz",
    )
    fps = {nm: f for nm, _a, f in seen["m"]}
    # a 59-frame bake of a 2.9 s clip is written at 20 fps, not at 30
    assert fps["EN4_COM_ATT_light_A"] == pytest.approx(58 / 2.9) == pytest.approx(20.0)
    assert fps["EN4_COM_ATT_unknown"] == pytest.approx(30.0)
    said = capsys.readouterr().out
    assert "note: clip EN4_COM_ATT_unknown written at 30 fps" in said
    assert "EN4_COM_ATT_light_A written at 30 fps" not in said
    assert seen["naz"] == "my.naz"  # the archive named by the caller reaches the mesh reader


def test_a_big_endian_clip_header_gives_the_same_length(tmp_path, monkeypatch):
    frag = tmp_path / "X.fragment.json"
    frag.write_text(
        '{"instances": [{"name": "V", "model_ref": ["/a/Skel_Skeleton.model", "/a/Body.model"]}]}'
    )
    bind = tmp_path / "bind_skel_file_v1.npz"
    np.savez(bind, Rb=np.tile(np.eye(3), (1, 1, 1)), tb=np.zeros((1, 3)), names=np.array(["A"]))
    bakedir = tmp_path / "bake"
    bakedir.mkdir()
    A = np.zeros((30, 1, 3, 4), np.float32)
    np.save(bakedir / "EN4_be.npy", A)
    # a console clip: big-endian header, then the track count and one name
    be = struct.pack(">ffIII", 29 / 2.0, 2.0, 0, 30, 1) + struct.pack(">I", 1)
    be += struct.pack(">I", 4) + b"Bip\0"
    assert bake_v4._detect_clip_order(be) == ">"
    seen = {}
    monkeypatch.setattr(vg, "load_parts", lambda meshes, pal, naz=None: [])
    monkeypatch.setattr(
        vg, "write_glb", lambda parts, manifest, out, bindp, **k: seen.update(m=manifest)
    )
    vg.build(
        str(frag),
        "V",
        str(tmp_path / "o.glb"),
        bakedir=str(bakedir),
        bank={"EN4_be": be},
        bind=str(bind),
    )
    assert seen["m"][0][2] == pytest.approx(29 / 2.0)


def test_char_and_bake_name_the_archive(tmp_path, monkeypatch, capsys):
    import watchmen
    import watchmenlib as wl

    assert "[BINDDIR [BAKEDIR [NAZ]]]" in watchmen.USAGE["char"][1]
    assert watchmen.USAGE["bake"][1] == "bake CLIPNAME BIND.npz OUT.npy [NAZ]"
    assert "01_game.naz" in watchmen.__doc__ and "no textures" in watchmen.__doc__
    monkeypatch.chdir(tmp_path)
    assert bake_v4.default_naz() == "game.naz"
    (tmp_path / "01_game.naz").write_bytes(b"")
    assert bake_v4.default_naz() == "01_game.naz"

    # bake: the fourth argument is the archive
    got = {}

    def fake_bake(clip, bind=None, upsample=2, bank=None, naz=None):
        got.update(clip=clip, bind=bind, naz=naz)
        return np.zeros((2, 1, 3, 4), np.float32), 1.0

    monkeypatch.setattr(wl, "bake", fake_bake)
    out = tmp_path / "o.npy"
    assert watchmen.main(["watchmen", "bake", "CLIP", "b.npz", str(out), "arch.naz"]) == 0
    assert got == {"clip": "CLIP", "bind": "b.npz", "naz": "arch.naz"}
    assert (
        watchmen.main(["watchmen", "bake", "CLIP", "b.npz", str(out)]) == 0 and got["naz"] is None
    )

    # a clip that is in no bank and an archive that is not there: said, not a traceback
    bind = tmp_path / "bind_one.npz"
    np.savez(
        bind,
        Rb=np.eye(3)[None],
        tb=np.zeros((1, 3)),
        tloc=np.zeros((1, 3)),
        par=np.array([-1]),
        names=np.array(["Bip"]),
    )
    with pytest.raises(FileNotFoundError, match="missing.naz.*does not exist"):
        bake_v4.bake("NOPE", 1, bind=str(bind), bank={}, naz="missing.naz")

    # char: the sixth argument is the archive; a missing one is an error with the usage
    frag = tmp_path / "X.fragment.json"
    frag.write_text("{}")
    rc = watchmen.main(
        ["watchmen", "char", str(frag), "V", "o.glb", "binds", "bake", "nope.naz", "--no-meta"]
    )
    assert rc == 2 and "'nope.naz', which does not exist" in capsys.readouterr().out
    called = {}
    monkeypatch.setattr(wl, "build_variant_glb", lambda f, v, o, **kw: called.update(kw))
    (tmp_path / "there.naz").write_bytes(b"")
    rc = watchmen.main(
        ["watchmen", "char", str(frag), "V", "o.glb", "binds", "bake", "there.naz", "--no-meta"]
    )
    assert rc == 0 and called["naz"] == "there.naz" and called["bakedir"] == "bake"
    assert "bank" not in called  # the fragment is outside an extract: no lengths, and it says so
    assert "every clip is written at 30 fps" in capsys.readouterr().out


def test_char_reuses_the_animation_table_of_a_characters_export(
    combat_extract, monkeypatch, capsys
):
    import watchmen

    f = combat_extract / "extracted" / "TNT" / "Fragments" / "Enemy" / "Thug.fragment.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{}")
    assert watchmen.stored_char_meta(str(combat_extract)) == (None, None)
    m = am.build(str(combat_extract))
    d = combat_extract / "characters_v1"
    d.mkdir()
    (d / "anim_meta.json").write_text(json.dumps(m))
    stale = combat_extract / "another"
    stale.mkdir()
    (stale / "anim_meta.json").write_text(json.dumps(dict(m, revision=0)))
    got, path = watchmen.stored_char_meta(str(combat_extract))
    assert path == str(d / "anim_meta.json") and got["revision"] == am.REVISION
    assert ce.anim_meta_is_current(got, str(combat_extract))
    monkeypatch.setattr(am, "build", lambda *a, **k: pytest.fail("the stored table was not used"))
    assert watchmen.char_meta(str(f))["format"] == am.FORMAT
    assert "clip metadata from %s" % (d / "anim_meta.json") in capsys.readouterr().out


# ----------------------------------------------------- Blender: action metadata
def _glb(path, gltf):
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)


def test_blender_attach_extras_reads_the_clip_metadata_and_drops_nulls(tmp_path):
    f = tmp_path / "c.glb"
    _glb(
        f,
        {
            "asset": {"version": "2.0"},
            "animations": [
                {
                    "name": "RSH_run",
                    "extras": {
                        "watchmen": {
                            "clip": "RSH_run",
                            "loop": True,
                            "written_duration_s": None,
                            "events": [{"name": "IMPACT", "time_s": None, "at": [0.5, None]}],
                        }
                    },
                },
                {"name": "GRIP 1H"},
                {"name": "other", "extras": {"else": 1}},
            ],
        },
    )
    assert bae.glb_json(str(f))["asset"]["version"] == "2.0"
    ex = bae.clip_extras(str(f))
    assert list(ex) == ["RSH_run"]
    assert ex["RSH_run"] == {
        "clip": "RSH_run",
        "loop": True,
        "events": [{"name": "IMPACT", "at": [0.5, ""]}],  # null member dropped, null element ""
    }

    class Action(dict):
        pass

    actions = {"RSH_run": Action(), "unrelated": Action()}
    done, missing = bae.attach(str(f), actions=actions)
    assert (done, missing) == (1, []) and actions["RSH_run"]["watchmen"]["loop"] is True
    assert "watchmen" not in actions["unrelated"]
    assert bae.attach(str(f), actions={}) == (0, ["RSH_run"])
    assert bae.main(["x", str(f)]) == 0  # outside Blender it only reads
    (tmp_path / "bad.glb").write_bytes(b"nope")
    with pytest.raises(ValueError, match="not a GLB"):
        bae.glb_json(str(tmp_path / "bad.glb"))
