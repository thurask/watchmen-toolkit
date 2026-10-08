"""Ragdoll rig: the articulated-body section of a skeleton .model, the property
record reader it shares with the pivot books, the rig as the engine applies it,
and the helper nodes / sidecar the character export writes.

Engine evidence: reader 0x51e1ad (section), 0x51a435 / 0x510e5f (records),
0x517b34 (joint frames), 0x4f727a / 0x4f6f54 / 0x4f7145 (shape descriptors),
0x69eac6 (10 solver iterations).  Everything here is synthetic and offline.
"""

import json
import pathlib
import math
import os
import pickle
import struct
import subprocess
import sys

import numpy as np
import pytest

import characters_export as ce
import kapow_props
import parse_model_nodes as pmn
import ragdoll_rig as rr
import skeleton_records as sr
import variant_glb as vg
from conftest import parse_glb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T_STR, T_BOOL, T_INT, T_NUM, T_VEC, T_QUAT, T_BIG = (
    0x144B7B5D,
    0xFD034A24,
    0x36604FF4,
    0xBDA17DE4,
    0x71D8181D,
    0xD007189C,
    0xEDEF427C,
)


def _str(s):
    b = s.encode() + b"\0"
    return struct.pack("<I", len(b)) + b


def _rec(oid, name, typ, value):
    if typ == T_STR:
        raw = value.encode() + b"\0"
        raw += b"\0" * (-len(raw) % 4)
        data = struct.pack("<I", len(raw) // 4) + raw
    elif typ == T_BOOL:
        data = struct.pack("<I", int(value))
    elif typ == T_INT:
        data = struct.pack("<i", value)
    elif typ == T_NUM:
        data = struct.pack("<f", value)
    elif typ == T_BIG:
        data = struct.pack("<Q", value)
    else:
        data = struct.pack("<%df" % len(value), *value)
    return struct.pack("<4I", oid, kapow_props.name_hash(name), typ, len(data) // 4) + data


def _body_records(oid, name, mass, lin=0.5, ang=2.0):
    return b"".join(
        [
            _rec(oid, "name", T_STR, name),
            _rec(oid, "movementType", T_INT, 0),
            _rec(oid, "numSolverIterations", T_INT, 4),
            _rec(oid, "mass", T_NUM, mass),
            _rec(oid, "angularDamping", T_NUM, ang),
            _rec(oid, "linearDamping", T_NUM, lin),
            _rec(oid, "maxLinearVelocity", T_NUM, 200.0),
            _rec(oid, "maxAngularVelocity", T_NUM, 200.0),
        ]
    )


def _joint_records(oid, name, s1, s2, tw, spring=200.0, proj=0, twist_type=1):
    num = {
        "maxForceBeforeBreak": 500.0,
        "maxTorqueBeforeBreak": 500.0,
        "jointProjectionDist": 0.02,
        "jointProjectionAngle": 0.0175,
        "swing1MotionLimitValue": s1,
        "swing2MotionLimitValue": s2,
        "lowTwistMotionLimitValue": -tw,
        "highTwistMotionLimitValue": tw,
        "linearMotionLimitValue": 0.0,
        "linearMotionLimitRestitution": 0.0,
        "linearMotionLimitSpring": 0.0,
        "linearMotionLimitDamping": 0.0,
        "xMotorPower": 0.0,
        "yMotorPower": 0.0,
        "zMotorPower": 0.0,
        "twistMotorPower": 0.0,
        "orientMotorPower": 0.0,
    }
    for pre in ("swing1", "swing2", "lowTwist", "highTwist"):
        num[pre + "MotionLimitRestitution"] = 0.0
        num[pre + "MotionLimitSpring"] = spring
        num[pre + "MotionLimitDamping"] = 14.0 if spring else 0.0
    ints = {
        "jointType": 0,
        "swing1LimitType": 1,
        "swing2LimitType": 1,
        "twistLimitType": twist_type,
        "xLimitType": 0,
        "yLimitType": 0,
        "zLimitType": 0,
        "movementMotorType": 0,
        "twistMotorType": 0,
    }
    bools = {
        "enableJointMotors": 0,
        "breakable": 0,
        "actorCollisionEnabled": 0,
        "jointProjection": proj,
    }
    out = [_rec(oid, "name", T_STR, name)]
    out += [_rec(oid, k, T_BOOL, v) for k, v in bools.items()]
    out += [_rec(oid, k, T_NUM, v) for k, v in num.items()]
    out += [_rec(oid, k, T_INT, v) for k, v in ints.items()]
    out.append(_rec(oid, "childSpacePos", T_VEC, (0.0, 0.0, 0.0)))
    out.append(_rec(oid, "childSpaceOrient", T_QUAT, (0.0, 0.0, 1.0, 0.0)))  # Rz(180)
    return b"".join(out)


def _volume(t, data, pos=(0, 0, 0), quat=(0, 0, 0, 1)):
    return (
        struct.pack("<II", t, 0)
        + data
        + struct.pack("<7f", *(tuple(pos) + tuple(quat)))
        + b"\0" * 4
    )


def _capsule(d, h, **kw):
    return _volume(7, struct.pack("<2f", d, h), **kw)


def _box(x, y, z, **kw):
    return _volume(5, struct.pack("<3f", x, y, z), **kw)


def _sphere(r, **kw):
    return _volume(6, struct.pack("<f", r), **kw)


def _node(name, parent, pos, quat=(0, 0, 0, 1), vols0=(), vols1=()):
    b = struct.pack("<3f", *pos) + struct.pack("<4f", *quat) + _str(name)
    b += struct.pack("<Ii", 0, parent)
    b += struct.pack("<I", 0)  # lods
    b += struct.pack("<I", 0)  # shadow lists
    b += b"\0"  # no proxy
    b += struct.pack("<I", len(vols0)) + b"".join(vols0)
    b += struct.pack("<I", len(vols1)) + b"".join(vols1)
    b += struct.pack("<I", 0)  # third list
    return b


_S15 = math.sin(math.radians(7.5))  # elbow bent 15 degrees about Y in the bind
_C15 = math.cos(math.radians(7.5))


def build_model(tuned=True, cloth_body=False):
    """root, Pelvis, Spine, L UpperArm, L Forearm, R UpperArm (the last without a
    body): 4 bodies, 3 joints."""
    nodes = [
        _node("", -1, (0, 0, 0)),
        _node("Pelvis", 0, (0, 1.0, 0), vols0=[_capsule(0.26, 0.38)], vols1=[_box(0.3, 0.2, 0.2)]),
        _node("Spine", 1, (0.1, 0.0, 0.0), vols0=[_box(0.2, 0.3, 0.1), _sphere(0.08)]),
        _node("L UpperArm", 2, (0.3, 0.0, 0.2), vols0=[_capsule(0.14, 0.31, pos=(-0.15, 0, 0))]),
        _node(
            "L Forearm",
            3,
            (-0.29, 0.0, 0.0),
            quat=(0.0, _S15, 0.0, _C15),
            vols0=[_capsule(0.4, 0.3)],  # height <= diameter
        ),
        _node("R UpperArm", 2, (0.3, 0.0, -0.2)),
    ]
    bodies = [1, 2, 3, 4]
    names = ["Pelvis", "Spine", "L UpperArm", "L Forearm"]
    masses = [9.0, 9.0, 2.5, 2.0] if tuned else [100.0] * 4
    blob = b"".join(_body_records(0x1000 + i, n, m) for i, (n, m) in enumerate(zip(names, masses)))
    joints = [(0, 1), (1, 2), (2, 3)]
    lim = [(10.0, 10.0, 5.0), (60.0, 60.0, 15.0), (90.0, 10.0, 20.0)]
    for i, ((pa, ch), (s1, s2, tw)) in enumerate(zip(joints, lim)):
        if not tuned:
            s1 = s2 = tw = 0.0
        blob += _joint_records(
            0x2000 + i,
            "%s->%s" % (names[ch], names[pa]),
            s1,
            s2,
            tw,
            spring=200.0 if tuned else 0.0,
            proj=1 if i == 0 else 0,
        )
    ab = struct.pack("<I", len(blob) // 4) + blob
    ab += struct.pack("<I", len(bodies)) + b"".join(struct.pack("<H", b) for b in bodies)
    cb = [1] if cloth_body else []
    ab += struct.pack("<I", len(cb)) + b"".join(struct.pack("<H", b) for b in cb)
    ab += struct.pack("<I", 0)  # cloths
    ab += struct.pack("<I", len(joints)) + b"".join(struct.pack("<2i", *j) for j in joints)
    h = _str("ModelRes") + struct.pack("<I", 2) + b"\xcd" * 8
    h += struct.pack("<IBIB", 0, 1, 0xFFFFFFFF, 0) + struct.pack("<II", 0, 0)
    h += struct.pack("<6f", 0, 0, 0, 1, 1, 1)
    h += struct.pack("<I", 0)  # textures
    h += struct.pack("<I", 1) + _str("/pivotbooks/default.pb")
    h += struct.pack("<I", len(nodes)) + b"".join(nodes)
    return h + ab + b"\0" * 4


def build_pivot_book(sheets):
    out = struct.pack("<3I", 0x16269EFA, 0x2964, len(sheets))
    for i, (name, fr, re_, mask) in enumerate(sheets):
        oid = 0x35BB0000 + i
        blob = b"".join(
            [
                _rec(oid, "name", T_STR, name),
                _rec(oid, "useRealtime", T_BOOL, 0),
                _rec(oid, "uniqueID", T_BIG, 0x43B830D445AF0000 + i),
                _rec(oid, "friction", T_NUM, fr),
                _rec(oid, "restitution", T_NUM, re_),
                _rec(oid, "collisionMask", T_INT, mask),
            ]
        )
        out += struct.pack("<I", 11) + b"PivotSheet\0" + struct.pack("<I", len(blob) // 4) + blob
    return out + struct.pack("<I", 10) + b"PivotBook\0" + struct.pack("<I", 0)


BIND_NAMES = ["Pelvis", "Spine", "L UpperArm", "L Forearm", "R UpperArm"]


def _bind(rig):
    """Rb, tb in palette order from the rig's own bind poses (the convention of
    build_bind_file: Rb = R(conj(world quat)))."""
    by = {b["bone"]: b for b in rig["bodies"]}
    Rb, tb = [], []
    for nm in BIND_NAMES:
        if nm in by:
            Rb.append(rr.frame_matrix(by[nm]["bind_world_quat_xyzw"]))
            tb.append(by[nm]["bind_world_pos"])
        else:
            Rb.append(np.eye(3))
            tb.append([0.4, 1.0, -0.2])
    return np.array(Rb), np.array(tb, float)


# ---------------------------------------------------------------------------
# record reader, section, pivot book
# ---------------------------------------------------------------------------


def test_property_records_group_into_objects_and_decode_by_type():
    blob = _body_records(7, "Pelvis", 9.107143) + _rec(8, "childSpaceOrient", T_QUAT, (0, 0, 1, 0))
    blob += _rec(8, "uniqueID", T_BIG, 0x43B830D445AF888D) + _rec(8, "breakable", T_BOOL, 1)
    recs = sr.read_property_records(blob, 0, len(blob) // 4)
    objs = sr.record_objects(recs, rr.property_names())
    assert [o["id"] for o in objs] == [7, 8]
    assert objs[0]["props"]["name"] == "Pelvis"
    assert objs[0]["props"]["mass"] == pytest.approx(9.107143)
    assert objs[0]["props"]["numSolverIterations"] == 4
    assert objs[1]["props"]["childSpaceOrient"] == [0.0, 0.0, 1.0, 0.0]
    assert objs[1]["props"]["uniqueID"] == 0x43B830D445AF888D
    assert objs[1]["props"]["breakable"] is True
    # an unnamed key keeps its hash; an unknown type keeps its bytes
    raw = struct.pack("<4I", 9, 0x12345678, 0xDEADBEEF, 1) + b"\x01\x02\x03\x04"
    o = sr.record_objects(sr.read_property_records(raw, 0, 5))[0]["props"]
    assert o == {"key_12345678": {"type_id": "0xdeadbeef", "hex": "01020304"}}


def test_property_records_reject_a_record_that_runs_past_the_blob():
    blob = _rec(1, "mass", T_NUM, 1.0)
    with pytest.raises(ValueError):
        sr.read_property_records(blob, 0, len(blob) // 4 + 1)
    bad = struct.pack("<4I", 1, 2, T_NUM, 9) + b"\0" * 4
    with pytest.raises(ValueError):
        sr.read_property_records(bad, 0, len(bad) // 4)


def test_cloth_attachments_are_six_bytes_each():
    """{u16 vertex, u32 value} is packed (6 bytes): reading it with native
    alignment (8) put the joint count of both player models out of range."""
    ab = struct.pack("<I", 0)  # empty property blob
    ab += struct.pack("<IH", 1, 3)  # one scene-0 body, node 3
    ab += struct.pack("<I", 0)
    ab += struct.pack("<I", 1) + struct.pack("<2HI", 5, 0, 3)
    ab += b"".join(struct.pack("<HI", v, 0x100 + v) for v in (7, 8, 9))
    ab += struct.pack("<I", 2) + struct.pack("<4i", 0, 1, 1, 2)
    got = sr.parse_articulated_body(b"\0" * 5 + ab, 5)
    assert got["cloths"] == [dict(node=5, mesh=0, attachments=[(7, 0x107), (8, 0x108), (9, 0x109)])]
    assert got["joints"] == [(0, 1), (1, 2)]
    assert got["end"] == 5 + len(ab)


def test_articulated_body_section_layout():
    h = build_model(cloth_body=True)
    m = pmn.model_physics(h)
    ab = m["articulated_body"]
    assert ab["bodies"] == [1, 2, 3, 4]
    assert ab["cloth_bodies"] == [1]
    assert ab["joints"] == [(0, 1), (1, 2), (2, 3)]
    assert m["end"] == len(h) - 4
    assert [n["name"] for n in m["nodes"]] == [
        "",
        "Pelvis",
        "Spine",
        "L UpperArm",
        "L Forearm",
        "R UpperArm",
    ]
    assert [len(n["volumes"][0]) for n in m["nodes"]] == [0, 1, 2, 1, 1, 0]
    assert len(m["nodes"][1]["volumes"][1]) == 1  # the cloth-scene list
    assert pmn.model_physics(h[: len(h) - 40]) is None  # truncated: clean failure
    assert pmn.model_physics(b"\x08\0\0\0Texture\0" + b"\0" * 64) is None


def test_pivot_book_gives_the_ragdoll_material_from_the_file():
    pb = build_pivot_book(
        [("Default", 0.9, 0.0, 0xA62F), ("Ragdoll", 0.6, 0.0, 1), ("Trashcan", 0.45, 0.2, 0x242F)]
    )
    sheets = rr.pivot_sheets(pb)
    assert [s["name"] for s in sheets] == ["Default", "Ragdoll", "Trashcan"]
    mat = rr.material_from_pivot_book(pb, "Ragdoll")
    assert mat["friction"] == pytest.approx(0.6) and mat["restitution"] == 0.0
    assert mat["collision_mask"] == "0x1" and mat["unique_id"] == "0x43b830d445af0001"
    assert rr.material_from_pivot_book(pb, "Trashcan")["restitution"] == pytest.approx(0.2)
    with pytest.raises(KeyError):
        rr.material_from_pivot_book(pb, "Ragdoll_All")
    with pytest.raises(ValueError):
        sr.parse_pivot_book(pb[:-20])


# ---------------------------------------------------------------------------
# the rig as the engine applies it
# ---------------------------------------------------------------------------


def test_rig_bodies_shapes_and_engine_inflation():
    rig = rr.build(build_model())
    assert [b["bone"] for b in rig["bodies"]] == ["Pelvis", "Spine", "L UpperArm", "L Forearm"]
    assert rig["total_mass"] == pytest.approx(22.5) and rig["tuned"] is True
    b = rig["bodies"][0]
    assert (b["mass"], b["linear_damping"], b["angular_damping"]) == (9.0, 0.5, 2.0)
    # file says 4, the game sets 10 at activation (0x69eac6): both, labelled
    assert (b["solver_iterations_file"], b["solver_iterations_runtime"]) == (4, 10)
    cap = b["shapes"][0]
    assert cap["type"] == "capsule" and cap["file"] == {"diameter": 0.26, "height_total": 0.38}
    assert cap["physx"]["radius"] == pytest.approx(0.13 + 0.025)  # 0x4f727a
    assert cap["physx"]["height"] == pytest.approx(0.38 - 0.26)
    box, sph = rig["bodies"][1]["shapes"]
    assert box["physx"]["half_extents"] == pytest.approx([0.125, 0.175, 0.075])  # 0x4f6f54
    assert sph["physx"]["radius"] == pytest.approx(0.105)  # 0x4f7145
    # total height <= diameter: the cylinder collapses to 0.001 (0xaad40c)
    assert rig["bodies"][3]["shapes"][0]["physx"]["height"] == pytest.approx(0.001)
    assert rig["bodies"][2]["shapes"][0]["local_pos"] == [-0.15, 0.0, 0.0]
    # contact = the stored size in PhysX terms: what a solver without a skin width needs,
    # and what the GLB proxies are drawn at
    assert cap["contact"] == {"radius": 0.13, "height": pytest.approx(0.12), "axis": "local +Y"}
    assert box["contact"]["half_extents"] == pytest.approx([0.1, 0.15, 0.05])
    assert sph["contact"]["radius"] == pytest.approx(0.08)
    v, _t = rr.proxy_mesh(cap)
    assert np.abs(v).max(0) == pytest.approx([0.13, 0.19, 0.13 * math.sin(math.radians(72))])
    assert np.abs(rr.proxy_mesh(cap, "physx")[0]).max(0)[:2] == pytest.approx([0.155, 0.215])
    # the cloth-scene list is not a ragdoll shape
    rig2 = rr.build(build_model(cloth_body=True))
    assert [len(x["shapes"]) for x in rig2["cloth_scene_bodies"]] == [1]
    assert rig2["cloth_scene_bodies"][0]["shapes"][0]["type"] == "box"
    assert len(rig2["bodies"][0]["shapes"]) == 1


def test_joint_frames_child_origin_axes_and_bind_derived_parent_frame():
    rig = rr.build(build_model())
    j = rig["joints"][2]  # L Forearm -> L UpperArm, elbow bent 15 degrees in the bind
    assert (j["parent_bone"], j["child_bone"], j["type"]) == ("L UpperArm", "L Forearm", "D6")
    ax = j["child_frame"]["axes_in_child_bone"]
    assert ax["twist_x"] == pytest.approx([-1, 0, 0], abs=1e-6)  # -X of the child bone
    assert ax["swing1_y"] == pytest.approx([0, -1, 0], abs=1e-6)  # -Y
    assert ax["swing2_z"] == pytest.approx([0, 0, 1], abs=1e-6)  # +Z
    # anchor = child bone origin = the child's local position in the parent (0x517b34)
    assert j["parent_frame"]["pos"] == pytest.approx([-0.29, 0, 0], abs=1e-6)
    # the parent frame is the child frame at bind pose: rotated by the bind bend
    pa = j["parent_frame"]["axes_in_parent_bone"]
    assert pa["swing1_y"] == pytest.approx([0, -1, 0], abs=1e-6)
    bend = math.degrees(math.acos(-pa["twist_x"][0]))
    assert bend == pytest.approx(15.0, abs=1e-3)
    # limits and flags as stored
    assert (j["swing1"]["limit_deg"], j["swing2"]["limit_deg"]) == (90.0, 10.0)
    assert (j["twist"]["low_deg"], j["twist"]["high_deg"]) == (-20.0, 20.0)
    assert j["swing1"]["spring"] == 200.0 and j["swing1"]["motion"] == "limited"
    assert j["linear"]["x"] == "locked" and j["breakable"] is False
    assert [x["projection"]["enabled"] for x in rig["joints"]] == [True, False, False]
    # world joint frame sits on the child body's bind position
    assert j["frame_world_bind"]["pos"] == pytest.approx(rig["bodies"][3]["bind_world_pos"])


def test_untuned_rig_is_flagged_not_passed_off_as_usable():
    rig = rr.build(build_model(tuned=False))
    assert rig["tuned"] is False and rig["total_mass"] == 400.0
    doc = rr.sidecar(rig, BIND_NAMES)
    assert doc["tuned"] is False and "untuned_note" in doc
    assert "untuned_note" not in rr.sidecar(rr.build(build_model()), BIND_NAMES)
    Rb, tb = _bind(rig)
    assert rr.glb_helpers(rig, BIND_NAMES, Rb, tb)["extras"]["tuned"] is False


def test_model_without_joints_has_no_rig():
    h = _str("ModelRes") + struct.pack("<I", 0) + struct.pack("<IBIB", 0, 0, 0, 0)
    h += struct.pack("<II", 0, 0) + struct.pack("<6f", 0, 0, 0, 1, 1, 1) + struct.pack("<II", 0, 0)
    h += struct.pack("<I", 1) + _node("Box", -1, (0, 0, 0), vols0=[_box(1, 1, 1)])
    blob = _body_records(1, "Box", 5.0)
    h += (
        struct.pack("<I", len(blob) // 4)
        + blob
        + struct.pack("<IH", 1, 0)
        + struct.pack("<III", 0, 0, 0)
    )
    assert pmn.model_physics(h)["articulated_body"]["bodies"] == [0]
    assert rr.build(h) is None
    assert rr.build(b"junk") is None


def test_blender_mapping_and_damping_conversion():
    rig = rr.build(build_model())
    bl = rr.blender_limits(rig["joints"][2])
    assert bl["type"] == "GENERIC" and (bl["object1"], bl["object2"]) == ("L UpperArm", "L Forearm")
    assert bl["limit_ang_x"] == pytest.approx([math.radians(-20), math.radians(20)], abs=1e-6)
    # the importer relabels a node's local (x, y, z) as (x, z, -y): swing1 (90) is the
    # empty's local Z in Blender, swing2 (10) its local Y
    assert bl["limit_ang_z"] == pytest.approx([-math.pi / 2, math.pi / 2], abs=1e-5)
    assert bl["limit_ang_y"] == pytest.approx([math.radians(-10), math.radians(10)], abs=1e-6)
    assert bl["limit_lin_x"] == [0.0, 0.0] and bl["disable_collisions"] is True
    locked = dict(rig["joints"][0], twist=dict(rig["joints"][0]["twist"], motion="locked"))
    assert rr.blender_limits(locked)["limit_ang_x"] == [0.0, 0.0]
    free = dict(rig["joints"][0], swing1=dict(rig["joints"][0]["swing1"], motion="free"))
    assert rr.blender_limits(free)["limit_ang_z"] is None
    assert rr.bullet_damping(0.5) == pytest.approx(1 - math.exp(-0.5), abs=1e-6)
    assert rr.bullet_damping(0.0) == 0.0
    # glTF (x, y, z) -> Blender (x, -z, y), a proper rotation
    M = np.eye(4)
    M[:3, 3] = [1.0, 2.0, 3.0]
    assert rr.to_blender(M)[:3, 3] == pytest.approx([1.0, -3.0, 2.0])
    assert np.linalg.det(rr._C) == pytest.approx(1.0)


def test_sidecar_carries_material_groups_and_joint_node_names():
    rig = rr.build(build_model())
    mat = rr.material_from_pivot_book(build_pivot_book([("Ragdoll", 0.6, 0.0, 1)]))
    doc = rr.sidecar(rig, BIND_NAMES, material=mat, source_model="a/b.model", group=4, glb="V.glb")
    assert doc["format"] == rr.FORMAT and doc["glb"] == "V.glb"
    assert doc["common"]["material"]["friction"] == pytest.approx(0.6)
    assert doc["common"]["solver_iterations"]["file"] == [4]
    assert doc["common"]["solver_iterations"]["runtime"] == 10
    assert doc["joint_nodes"] == {
        "Pelvis": "b0",
        "Spine": "b1",
        "L UpperArm": "b2",
        "L Forearm": "b3",
    }
    g = doc["common"]["collision_groups"]
    assert g["names"]["4"] == "KINEMATIC_RAGDOLL" and g["animated_group"] == 4
    pairs = {(a, b): e for a, b, e in g["pairs_enabled"]}
    assert pairs[(0, 4)] == 1 and pairs[(4, 5)] == 0 and pairs[(0, 10)] == 1 and len(pairs) == 135
    # the run-time groups of an active ragdoll (0x7dffbf loops, 0x7d82f0 / 0x7d837d / 0x7d823f)
    u = g["unique_groups"]
    assert u["ragdoll_dynamic"]["groups"] == [24, 27] and 5 in u["ragdoll_dynamic"]["collides_with"]
    assert u["ragdoll"]["groups"] == [20, 23] and 5 in u["ragdoll"]["not_with"]
    assert u["ragdoll_pair"]["groups"] == [28, 31]
    for pool in ("ragdoll", "ragdoll_dynamic", "ragdoll_pair"):
        assert sorted(u[pool]["collides_with"] + u[pool]["not_with"]) == list(range(12))
    assert "keeps its animated LOCAL transform" in doc["common"]["runtime"]["bones_without_body"]
    assert "no velocity" in doc["common"]["runtime"]["handover"]
    assert doc["joints"][0]["blender"]["type"] == "GENERIC"
    assert "blender" not in rig["joints"][0]  # the rig itself is not mutated
    json.dumps(doc)  # plain JSON all the way down
    assert rr.group_for("rsh") == 8 and rr.group_for("nto") == 9 and rr.group_for("female") == 4
    assert rr.sheet_for("nto") == "Ragdoll_All" and rr.sheet_for("medium") == "Ragdoll"


# ---------------------------------------------------------------------------
# GLB helper nodes
# ---------------------------------------------------------------------------


def _write(rig5, tmp_path, name, ragdoll):
    out = tmp_path / name
    vg.write_glb(rig5.parts, rig5.manifest, out, str(rig5.bind_npz), ragdoll=ragdoll)
    return parse_glb(out)


@pytest.fixture
def helpers_on_rig(rig):
    """The synthetic rig's helpers on the conftest character (5 flat joints)."""
    model = rr.build(build_model())
    names = list(BIND_NAMES)
    np.savez(rig.bind_npz, Rb=rig.Rb, tb=rig.tb, names=np.array(names), par=rig.par)
    return model, rr.glb_helpers(
        model, names, rig.Rb, rig.tb, material={"friction": 0.6, "restitution": 0.0}
    )


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_glb_gets_helper_nodes_outside_the_scene(rig, helpers_on_rig, tmp_path):
    model, helpers = helpers_on_rig
    g = _write(rig, tmp_path, "rag.glb", helpers)
    j = g.j
    names = [n.get("name") for n in j["nodes"]]
    root = j["nodes"][names.index("ragdoll")]
    kids = [j["nodes"][k]["name"] for k in root["children"]]
    assert kids == [
        "RB.Pelvis.0",
        "RB.Spine.0",
        "RB.Spine.1",
        "RB.L UpperArm.0",
        "RB.L Forearm.0",
        "RJ.Spine",
        "RJ.L UpperArm",
        "RJ.L Forearm",
    ]
    # in no scene, like "alternatives"
    in_scene = set()

    def walk(k):
        in_scene.add(k)
        for c in j["nodes"][k].get("children", []):
            walk(c)

    for k in j["scenes"][0]["nodes"]:
        walk(k)
    assert names.index("ragdoll") not in in_scene
    assert not in_scene & set(root["children"])
    # a shape: proxy mesh skinned rigidly to its bone's joint
    nd = j["nodes"][names.index("RB.L UpperArm.0")]
    assert nd["skin"] == 0 and "translation" not in nd
    ex = nd["extras"]["watchmen"]["ragdoll"]
    assert ex["kind"] == "shape" and ex["body"]["joint_node"] == "b2"
    assert ex["body"]["solver_iterations"] == {"file": 4, "runtime": 10}
    assert ex["body"]["friction"] == 0.6 and ex["shape"]["physx"]["radius"] == pytest.approx(0.095)
    prim = j["meshes"][nd["mesh"]]["primitives"][0]
    J = g.accessor(prim["attributes"]["JOINTS_0"])
    W = g.accessor(prim["attributes"]["WEIGHTS_0"])
    assert (np.asarray(J)[:, 0] == 2).all() and (np.asarray(W)[:, 0] == 1).all()
    assert (np.asarray(J)[:, 1:] == 0).all() and (np.asarray(W)[:, 1:] == 0).all()
    # vertices are in bind world space: back in the bone frame they fit the capsule
    V = np.asarray(g.accessor(prim["attributes"]["POSITION"]), float)
    local = (V - rig.tb[2]) @ rig.Rb[2]  # R^T (v - t)
    local -= np.array([-0.15, 0, 0])
    rad, cyl = 0.07, 0.31 - 0.14  # the proxy has the stored (contact) size
    assert ex["shape"]["contact"]["radius"] == pytest.approx(rad)
    assert np.abs(local[:, 1]).max() == pytest.approx(cyl / 2 + rad, abs=1e-5)
    assert np.hypot(local[:, 0], local[:, 2]).max() == pytest.approx(rad, abs=1e-5)
    # triangles wind outward
    T = np.asarray(g.accessor(prim["indices"])).reshape(-1, 3)
    nrm = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    assert (np.einsum("ij,ij->i", nrm, V[T].mean(1) - V.mean(0)) > 0).all()
    assert j["materials"][prim["material"]]["name"] == "RAGDOLL proxy"
    # a joint: empty at the child bone's bind position, D6 frame = Rz(180) of the bone
    jn = j["nodes"][names.index("RJ.L Forearm")]
    assert "mesh" not in jn
    assert jn["translation"] == pytest.approx(rig.tb[3].tolist(), abs=1e-6)
    from conftest import quat_xyzw_to_mat

    R = quat_xyzw_to_mat(jn["rotation"])
    assert R[:, 0] == pytest.approx(-rig.Rb[3][:, 0], abs=1e-6)  # twist = -X of the bone
    assert R[:, 1] == pytest.approx(-rig.Rb[3][:, 1], abs=1e-6)
    assert R[:, 2] == pytest.approx(rig.Rb[3][:, 2], abs=1e-6)
    jx = jn["extras"]["watchmen"]["ragdoll"]
    assert (jx["parent_joint_node"], jx["child_joint_node"]) == ("b2", "b3")
    assert jx["blender"]["limit_ang_z"] == pytest.approx([-math.pi / 2, math.pi / 2], abs=1e-5)
    Mb = np.array(jx["blender"]["bind_world_matrix"]).reshape(3, 4)
    # in Blender the empty's local Z is the node's local +Y (swing1), local Y its -Z
    C = np.array([[1.0, 0, 0], [0, 0, -1], [0, 1, 0]])
    assert Mb[:, 2] == pytest.approx(C @ R[:, 1], abs=1e-6)
    assert Mb[:, 1] == pytest.approx(-(C @ R[:, 2]), abs=1e-6)
    assert Mb[:, 0] == pytest.approx(C @ R[:, 0], abs=1e-6)
    t = rig.tb[3]
    assert Mb[:, 3] == pytest.approx([t[0], -t[2], t[1]], abs=1e-6)  # (x, y, z) -> (x, -z, y)
    a = j["asset"]["extras"]["watchmen"]["ragdoll"]
    assert a["format"] == rr.FORMAT and a["bodies"] == 4 and a["joints"] == 3 and a["tuned"] is True


def test_everything_else_in_the_glb_is_unchanged_by_the_helpers(rig, helpers_on_rig, tmp_path):
    _model, helpers = helpers_on_rig
    a = _write(rig, tmp_path, "with.glb", helpers)
    b = _write(rig, tmp_path, "without.glb", None)
    ja, jb = a.j, b.j
    for key in ("nodes", "meshes", "accessors", "bufferViews", "materials"):
        assert ja[key][: len(jb[key])] == jb[key], key
        assert len(ja[key]) > len(jb[key]) or key == "bufferViews"
    for key in ("scenes", "scene", "skins", "animations"):
        assert ja.get(key) == jb.get(key), key
    assert "ragdoll" not in jb["asset"].get("extras", {}).get("watchmen", {})
    nb = jb["buffers"][0]["byteLength"]
    assert a.bin_chunk[:nb] == b.bin_chunk[:nb]  # helper data is appended
    # and the default (no argument) is byte-identical to ragdoll=None
    out = tmp_path / "default.glb"
    vg.write_glb(rig.parts, rig.manifest, out, str(rig.bind_npz))
    assert out.read_bytes() == (tmp_path / "without.glb").read_bytes()


def test_left_and_right_helpers_follow_their_own_bones(rig, tmp_path):
    """Mirror check: a body's proxy sits on the joint that carries its bone name,
    whichever side that is in the (mirrored) GLB."""
    model = rr.build(build_model())
    names = ["R UpperArm", "Spine", "L UpperArm", "L Forearm", "Pelvis"]  # shuffled palette
    np.savez(rig.bind_npz, Rb=rig.Rb, tb=rig.tb, names=np.array(names), par=rig.par)
    h = rr.glb_helpers(model, names, rig.Rb, rig.tb)
    by = {s["name"]: s for s in h["shapes"]}
    assert by["RB.Pelvis.0"]["slot"] == 4 and by["RB.L UpperArm.0"]["slot"] == 2
    assert by["RB.Pelvis.0"]["verts"].mean(0) == pytest.approx(rig.tb[4], abs=1e-4)
    # a body whose bone the bind does not have is skipped and reported
    h2 = rr.glb_helpers(model, ["Pelvis", "Spine"], rig.Rb[:2], rig.tb[:2])
    assert h2["extras"]["skipped_bodies"] == ["L UpperArm", "L Forearm"]
    assert [x["name"] for x in h2["joints"]] == ["RJ.Spine"]


def test_convex_shape_becomes_a_proxy_from_its_own_triangles():
    tet = np.array([[0, 0, 0], [0.1, 0, 0], [0, 0.1, 0], [0, 0, 0.1]], np.float32)
    idx = [0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3]
    shape = rr.shape_record(
        dict(
            type=4, mode=1, verts=tet, indices=idx, blob=b"x" * 9, pos=(0, 0, 0), quat=(0, 0, 0, 1)
        )
    )
    assert shape["type"] == "convex_mesh" and shape["file"]["cooked_blob_bytes"] == 9
    v, t = rr.proxy_mesh(shape)
    assert v.shape == (4, 3) and t.shape == (4, 3)
    strip = rr.shape_record(
        dict(
            type=4,
            mode=0,
            verts=tet,
            indices=[0, 1, 2, 3],
            blob=b"",
            pos=(0, 0, 0),
            quat=(0, 0, 0, 1),
        )
    )
    assert rr.proxy_mesh(strip)[1].shape == (2, 3)


# ---------------------------------------------------------------------------
# export hook, CLI, key table
# ---------------------------------------------------------------------------


def _extract_tree(tmp_path):
    ex = tmp_path / "ex"
    sk = ex / "extracted" / "art" / "characters" / "common" / "skeletons"
    sk.mkdir(parents=True)
    (sk / "Female_Skeleton.model").write_bytes(build_model())
    pbd = ex / "extracted" / "pivotbooks"
    pbd.mkdir()
    (pbd / "default.pb").write_bytes(
        build_pivot_book([("Ragdoll", 0.6, 0.0, 1), ("Ragdoll_All", 0.6, 0.0, 0x401)])
    )
    return ex


def test_export_hook_writes_the_sidecar_and_returns_helpers(rig, tmp_path, monkeypatch):
    ex = _extract_tree(tmp_path)
    np.savez(rig.bind_npz, Rb=rig.Rb, tb=rig.tb, names=np.array(BIND_NAMES), par=rig.par)
    out = str(tmp_path / "Dominatrix_1.glb")
    monkeypatch.delenv("WATCHMEN_RAGDOLL", raising=False)
    h = ce.ragdoll_helpers(str(ex), "female", [], str(rig.bind_npz), out)
    assert len(h["shapes"]) == 5 and len(h["joints"]) == 3
    assert h["extras"]["sidecar"] == "Dominatrix_1.ragdoll.json"
    doc = json.loads((tmp_path / "Dominatrix_1.ragdoll.json").read_text())
    assert doc["source_model"] == "art/characters/common/skeletons/Female_Skeleton.model"
    assert doc["common"]["material"]["sheet"] == "Ragdoll" and doc["glb"] == "Dominatrix_1.glb"
    assert len(doc["bodies"]) == 4 and doc["joint_nodes"]["Pelvis"] == "b0"
    # switched off: nothing returned, nothing written
    os.remove(str(tmp_path / "Dominatrix_1.ragdoll.json"))
    monkeypatch.setenv("WATCHMEN_RAGDOLL", "0")
    assert ce.ragdoll_helpers(str(ex), "female", [], str(rig.bind_npz), out) is None
    assert not os.path.exists(str(tmp_path / "Dominatrix_1.ragdoll.json"))
    assert ce.ragdoll_helpers(str(ex), "female", [], str(rig.bind_npz), out, True) is not None
    # a skeleton that is not on disk: no rig, no error
    monkeypatch.delenv("WATCHMEN_RAGDOLL")
    assert ce.ragdoll_helpers(str(ex), "gimp", [], str(rig.bind_npz), out) is None
    # the players use their own model (slot 0), not a skeleton model
    base = str(ex / "extracted" / "art" / "characters" / "common" / "skeletons" / "Female_Skeleton")
    assert ce.ragdoll_source_model(str(ex), "rsh", [base]) == base + ".model"


def _cli(*args, **env):
    e = dict(os.environ, **env)
    return subprocess.run(
        [sys.executable, os.path.join(ROOT, "watchmen.py")] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        env=e,
    )


def test_cli_ragdoll_command_and_no_ragdoll_switch(tmp_path):
    ex = _extract_tree(tmp_path)
    model = str(
        ex / "extracted" / "art" / "characters" / "common" / "skeletons" / "Female_Skeleton.model"
    )
    pb = str(ex / "extracted" / "pivotbooks" / "default.pb")
    out = str(tmp_path / "rig.json")
    r = _cli("ragdoll", model, pb, out)
    assert r.returncode == 0, r.stdout
    doc = json.loads(pathlib.Path(out).read_text())
    assert len(doc["bodies"]) == 4 and len(doc["joints"]) == 3
    assert doc["common"]["material"]["friction"] == pytest.approx(0.6)
    r = _cli("ragdoll", pb)
    assert r.returncode == 1 and "no articulated body" in r.stdout
    r = _cli("faces", "a", "b", "--no-ragdoll")
    assert r.returncode == 2 and "--no-ragdoll applies to: all, characters" in r.stdout


def test_d6_swing_keys_resolve_in_the_fragment_key_table():
    """The digit-bearing D6 names hash with the 0xDF fold (digits fold too); a
    key table without them mis-types every D6 joint in a fragment."""
    kd = pickle.loads(pathlib.Path(ROOT, "wlib", "kapow_fragment_keys.pkl").read_bytes())
    want = {
        0xE3BA246D: ("swing1LimitType", "integer"),
        0x6F1C1D46: ("swing1MotionLimitValue", "number"),
        0x96F40D0C: ("swing2LimitType", "integer"),
        0x1C2A4EFB: ("swing2MotionLimitValue", "number"),
        0x0A3F7A6E: ("swing1MotionLimitRestitution", "number"),
        0x1DE40E20: ("swing1MotionLimitSpring", "number"),
        0x09EBF0A2: ("swing1MotionLimitDamping", "number"),
        0x9F5E10AB: ("swing2MotionLimitRestitution", "number"),
        0xC640881E: ("swing2MotionLimitSpring", "number"),
        0x97BD4E2A: ("swing2MotionLimitDamping", "number"),
    }
    for h, (name, typ) in want.items():
        assert kapow_props.name_hash(name) == h
        got = kd["keytable"].get(h) or kd["promoted"].get(h)
        assert tuple(got) == (name, typ), name
    import gen_data

    assert gen_data.keys_import(json.loads(json.dumps(gen_data.keys_export()))) == kd
