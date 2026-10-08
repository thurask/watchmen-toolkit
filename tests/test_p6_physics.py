"""Physics facts settled by the open-items sweep.

Material        NxMaterialDesc built at 0x51555a: one friction value for static and
                dynamic, friction combine MULTIPLY, restitution combine AVERAGE
Cloth           NxClothDesc built at 0x50c95f: flag word, constants; attachments
                (0xFFFFFFFF = world fix 0x507dd0, else cloth-scene body node 0x517b06)
Cloth-only rig  a model with cloths but no ragdoll (Curtains_01)
Ragdoll values  CharacterVisual.command_update_ragdoll 0x6bc3e2 (anim_meta conventions)
Synthetic fixtures only (the builders of test_ragdoll_rig)."""

import math, os, struct, sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import ragdoll_rig as rr
import test_ragdoll_rig as tr


def cloth_model(with_ragdoll=False):
    """A model whose articulated body holds one cloth on node 1 (two attachments: a
    world fix and one to node 1) -- alone, or behind the ragdoll of build_model."""
    oid = 0x3000
    cloth = b"".join(
        [
            tr._rec(oid, "name", tr.T_STR, "Plane01"),
            tr._rec(oid, "useGravity", tr.T_BOOL, 1),
            tr._rec(oid, "isSelfColliding", tr.T_BOOL, 0),
            tr._rec(oid, "isPressurized", tr.T_BOOL, 0),
            tr._rec(oid, "useMinAdhereVelocity", tr.T_BOOL, 0),
            tr._rec(oid, "dampingType", tr.T_INT, 2),
            tr._rec(oid, "collisionType", tr.T_INT, 0),
            tr._rec(oid, "bendConstraintType", tr.T_INT, 1),
        ]
    )
    nodes = [
        tr._node("", -1, (0, 0, 0)),
        tr._node("Plane01", 0, (0, 1.0, 0), vols1=[tr._box(0.3, 0.2, 0.2)]),
    ]
    ab = struct.pack("<I", len(cloth) // 4) + cloth
    ab += struct.pack("<I", 0)  # scene-0 bodies
    ab += struct.pack("<I", 1) + struct.pack("<H", 1)  # cloth-scene bodies
    ab += struct.pack("<I", 1) + struct.pack("<2HI", 1, 0, 2)
    ab += struct.pack("<HI", 4, 0xFFFFFFFF) + struct.pack("<HI", 9, 1)
    ab += struct.pack("<I", 0)  # joints
    h = tr._str("ModelRes") + struct.pack("<I", 2) + b"\xcd" * 8
    h += struct.pack("<IBIB", 0, 1, 0xFFFFFFFF, 0) + struct.pack("<II", 0, 0)
    h += struct.pack("<6f", 0, 0, 0, 1, 1, 1)
    h += struct.pack("<I", 0)
    h += struct.pack("<I", 1) + tr._str("/pivotbooks/default.pb")
    h += struct.pack("<I", len(nodes)) + b"".join(nodes)
    return h + ab + b"\0" * 4


def test_cloth_flags_follow_the_descriptor_code():
    f = rr.cloth_flags
    # the five shipped combinations (flag words computed from the read table)
    base = dict(useGravity=True, bendConstraintType=1)
    assert f(dict(base, dampingType=1, collisionType=1)) == 0x160  # Rorschach beltCloth
    assert f(dict(base, dampingType=1, collisionType=1, isSelfColliding=True)) == 0x168
    assert f(dict(base, dampingType=0, collisionType=1)) == 0x60  # no damping flag
    assert f(dict(base, dampingType=2, collisionType=0)) == 0x4164  # Curtains_01
    assert f({}) == 0  # a property that is not stored sets no bit
    assert f(dict(collisionType=2, bendConstraintType=2, useMinAdhereVelocity=True)) == 0x402C0
    assert f(dict(isPressurized=True, collisionType=1)) == 0  # the pressure bit is not set here


def test_cloth_only_model_builds_only_when_asked():
    mb = cloth_model()
    assert rr.build(mb) is None and rr.explain(mb) == rr.NO_BODY  # the character path
    rig = rr.build(mb, cloth_only=True)
    assert rig["bodies"] == [] and rig["joints"] == []
    (c,) = rig["cloths"]
    assert c["node_index"] == 1 and c["mesh_index"] == 0
    assert c["attachments"] == [
        {"vertex": 4, "cloth_body_node_index": None, "world_fixed": True},
        {"vertex": 9, "cloth_body_node_index": 1, "world_fixed": False},
    ]
    px = c["physx"]
    assert px["flags"] == "0x4164" and px["pressure_flag_if_mesh_closed"] is False
    assert px["tear_factor"] == 1.5 and px["attachment_response"] == 0.2
    assert px["wake_up_counter"] == 0.4 and px["sleep_linear_velocity"] == -1.0
    assert px["scene"] == 1 and px["source"] == "0x50c95f"
    assert isinstance(px["friction"], str)  # the sheet's value is not in the model
    assert [b["bone"] for b in rig["cloth_scene_bodies"]] == ["Plane01"]
    doc = rr.sidecar(rig, source_model="Curtains_01.model")
    assert "cloth_only_note" in doc and "untuned_note" not in doc
    assert doc["cloths"][0]["physx"]["flags"] == "0x4164"


def test_ragdoll_models_are_unchanged_by_the_cloth_switch():
    mb = tr.build_model()
    assert rr.build(mb, cloth_only=True) == rr.build(mb)
    assert rr.build(mb)["cloths"] == []


def test_material_says_how_the_engine_combines():
    pb = tr.build_pivot_book([("Ragdoll", 0.6, 0.0, 1), ("Default", 0.9, 0.0, 0xA62F)])
    m = rr.material_from_pivot_book(pb)
    assert m["friction"] == 0.6 and m["static_friction"] == 0.6 and m["dynamic_friction"] == 0.6
    assert m["friction_combine"] == "multiply" and m["restitution_combine"] == "average"
    assert m["source"] == "0x51555a" and m["restitution"] == 0.0
    # two ragdoll bodies rub with 0.36, a ragdoll on a Default surface with 0.54
    d = rr.material_from_pivot_book(pb, "Default")
    assert m["friction"] * m["friction"] == pytest.approx(0.36)
    assert m["friction"] * d["friction"] == pytest.approx(0.54)
    doc = rr.sidecar(rr.build(tr.build_model()), material=m)
    listed = " | ".join(doc["common"]["blender"]["not_representable"])
    assert "friction combine" not in listed and "skin width" in listed


def test_ragdoll_values_are_in_the_conventions_of_both_frames():
    for frame in ("true", "mirrored"):
        vals = am.conventions(frame)["ragdoll_values"]
        assert [v["id"] for v in vals] == [6, 8, 10, 11]
        assert vals[0]["name"] == "CHARACTER_PELVIS_ROTATION" and vals[0]["range"] == [-180, 180]
        assert "0x6bc3e2" in vals[0]["source"] and "0.15 s" in vals[1]["rule"]
        assert vals[3]["source"].endswith("(cast details not rechecked)")


def test_pelvis_rotation_follows_the_engine_formula():
    s = math.sqrt(0.5)
    f = am.pelvis_rotation
    # bone -Y is the body's "front" axis E, bone -X the head axis A
    assert f([0.0, 0.0, 0.0, 1.0]) == pytest.approx(-90.0)  # E straight down, A horizontal
    assert f([1.0, 0.0, 0.0, 0.0]) == pytest.approx(90.0)  # E straight up
    # nY = 0 with nX < 0: the engine's ATan2 takes sign -1 for nY <= 0 -> -180, not +180
    assert f([s, 0.0, 0.0, s]) == pytest.approx(-180.0)
    assert f([-s, 0.0, 0.0, s]) == pytest.approx(-0.0, abs=1e-6)
    # an exactly vertical body (A along Y): B = 0, so nX = 0 and the result is +-90
    assert abs(f([0.0, 0.0, s, s])) == pytest.approx(90.0)
    assert abs(f([0.0, 0.0, -s, s])) == pytest.approx(90.0)
    # scale of the quaternion does not matter; the range is (-180, 180]
    assert f([2.0, 0.0, 0.0, 0.0]) == pytest.approx(90.0)
    import random

    rnd = random.Random(5)
    for _ in range(500):
        q = [rnd.gauss(0, 1) for _ in range(4)]
        assert -180.0 <= f(q) <= 180.0
