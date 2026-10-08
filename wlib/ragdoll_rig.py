#!/usr/bin/env python3
"""ragdoll_rig.py -- the ragdoll / collision rig of a character, read from its
skeleton .model and expressed the way the engine applies it.

The rig is DATA: the articulated-body section of the model the character has in
slot 0 (reader 0x51e1ad; `Character` vtable slot 41, 0x4bee1e, clones it).  17
rigid bodies (one per listed bone, shapes = the bone's scene-0 collision volumes)
and 16 D6 joints.  See docs/RAGDOLL_RIG.md.

    rig = build(open("Female_Skeleton.model", "rb").read())
    side = sidecar(rig, bind_names, material=material_from_pivot_book(pb, "Ragdoll"))
    helpers = glb_helpers(rig, bind_names, Rb, tb)     # variant_glb.write_glb(ragdoll=...)

build() returns the engine's numbers; sidecar() and the extras of glb_helpers()
are written in the output frame (frame.py: true-handed by default, the rig
reflected with reflect_rig; engine numbers with --frame mirrored).

Conventions (engine space, +Y up, metres): quaternions are xyzw AS STORED; the
engine composes world = local (x) parent (Hamilton) and rotates a vector as
conj(q) v q, so the matrix that takes frame coordinates to the parent is
R(conj(q)) -- the same conjugate the skeleton rest pose needs.
"""

import math, os, pickle, struct, sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0)
import frame as _frame
import kapow_props
import parse_model_nodes as _pmn
import skeleton_records as _sr

FORMAT = "watchmen_ragdoll/1"
SKIN_WIDTH = 0.025  # shape inflation and skinWidth: 0xa23760 (double), 0x9e600c
MIN_CAPSULE_HEIGHT = 0.001  # 0xaad40c
MIN_EXTENT = 1e-5  # 0xa23590
RUNTIME_SOLVER_ITERATIONS = 10  # CharacterVisual.command_activate_ragdoll 0x69eac6
HELPER_ROOT = "ragdoll"  # GLB node (in no scene) that holds the helper nodes
PROXY_MATERIAL = "RAGDOLL proxy"

# COLLISION_GROUP_TYPES (script enum) and the pair matrix set once by
# PhysicsSimulation.command_setup_collision_groups 0x7dffbf (constant pairs only;
# pairs not listed keep the scene default "same group only", 0x502fda).
COLLISION_GROUPS = {
    0: "WORLD",
    1: "ACTIVE_CHAR_PHYSICS",
    2: "INACTIVE_CHAR_PHYSICS",
    3: "RAGDOLL_IN_WORLD",
    4: "KINEMATIC_RAGDOLL",
    5: "DYNAMIC_WORLD",
    6: "NOT_USED01",
    7: "EXPAND_VOLUME_PHYSICS",
    8: "KINEMATIC_RAGDOLL_ROR",
    9: "KINEMATIC_RAGDOLL_NO",
    10: "SIMPLE_RAGDOLL",
    11: "AI_SYSTEM_WAYPOINT",
    12: "NITE_OWL_PHYSICS",
    13: "NITE_OWL_PHYSICS_TARGET",
    14: "RORSCHACH_PHYSICS",
    15: "RORSCHACH_PHYSICS_TARGET",
    16: "RAGDOLL_NITE_OWL",
    17: "RAGDOLL_NITE_OWL_TARGET",
    18: "RAGDOLL_RORSCHACH",
    19: "RAGDOLL_RORSCHACH_TARGET",
}
# fmt: off
# Groups 20..31 are handed out at run time (PhysicsSimulation.GetRagdoll*CollisionGroup
# 0x7d82f0 / 0x7d837d / 0x7d823f; bounds = WorldLib.collision_group_types_max_num 20,
# ..._max_num_ragdoll_dynamic 24, ..._max_num_dynamic 28, collision_group_max_num 32).
# Rows from the three loops at the end of command_setup_collision_groups 0x7dffbf; a pair
# the script does not set keeps the scene default "same group only" (0x502fda).
UNIQUE_GROUP_POOLS = {
    "ragdoll": {
        "groups": [20, 23],
        "used_by": "CharacterVisual.command_pre_transfer_to_animation_control 0x69fde4 "
        "(tCollideWithDynamicWorld = 0): the ragdoll while it blends back to animation",
        "collides_with": [0, 3, 4],
        "not_with": [1, 2, 5, 6, 7, 8, 9, 10, 11],
    },
    "ragdoll_dynamic": {
        "groups": [24, 27],
        "used_by": "CharacterVisual.StateRagdollDriven 0x69ed7c (both arguments 1): the "
        "active ragdoll, until the pelvis slows below 1.5 m/s (then SIMPLE_RAGDOLL 10)",
        "collides_with": [0, 3, 4, 5],
        "not_with": [1, 2, 6, 7, 8, 9, 10, 11],
    },
    "ragdoll_pair": {
        "groups": [28, 31],
        "used_by": "PhysicsSimulation.command_set_safe_ragdoll_collision_groups 0x7df74a: "
        "two characters get g and g + 1, which do not collide with each other",
        "collides_with": [0, 3, 4, 5],
        "not_with": [1, 2, 6, 7, 8, 9, 10, 11],
    },
    "rules": "within its own group a ragdoll's bodies collide with each other (scene "
    "default; the two bodies of a joint do not: NX_JF_COLLISION_ENABLED is off); two "
    "ragdolls in different unique groups, and a unique group against the capsule and "
    "player groups 12..19, do not collide.  A pool that is used up hands out its last "
    "group again (pair pool: 30/31), so those ragdolls then share a group and collide",
}

_PAIRS_ON = [(0, 1), (0, 3), (0, 4), (0, 5), (0, 7), (0, 8), (0, 9), (0, 10), (0, 12), (0, 13), (0, 14), (0, 15), (0, 16), (0, 17), (0, 18), (0, 19), (1, 5), (1, 7), (1, 12), (1, 13), (1, 14), (1, 15), (3, 4), (3, 5), (3, 8), (3, 9), (3, 16), (3, 17), (3, 18), (3, 19), (4, 16), (4, 17), (4, 18), (4, 19), (5, 7), (5, 10), (5, 12), (5, 13), (5, 14), (5, 15), (5, 16), (5, 17), (5, 18), (5, 19), (7, 7), (7, 12), (7, 13), (7, 14), (7, 15), (8, 16), (8, 17), (8, 19), (9, 17), (9, 18), (9, 19)]
_PAIRS_OFF = [(0, 2), (0, 11), (1, 2), (1, 10), (1, 16), (1, 17), (1, 18), (1, 19), (2, 5), (2, 7), (2, 10), (2, 12), (2, 13), (2, 14), (2, 15), (2, 16), (2, 17), (2, 18), (2, 19), (3, 7), (3, 10), (3, 12), (3, 13), (3, 14), (3, 15), (4, 5), (4, 7), (4, 10), (4, 12), (4, 13), (4, 14), (4, 15), (5, 8), (5, 9), (5, 11), (6, 12), (6, 13), (6, 14), (6, 15), (6, 16), (6, 17), (6, 18), (6, 19), (7, 8), (7, 9), (7, 10), (7, 11), (7, 16), (7, 17), (7, 18), (7, 19), (8, 10), (8, 12), (8, 13), (8, 14), (8, 15), (8, 18), (9, 10), (9, 12), (9, 13), (9, 14), (9, 15), (9, 16), (10, 11), (10, 16), (10, 17), (10, 18), (10, 19), (11, 12), (11, 13), (11, 14), (11, 15), (11, 16), (11, 17), (11, 18), (11, 19), (12, 13), (14, 15), (16, 17), (18, 19)]
# fmt: on

_MOTION = {0: "locked", 1: "limited", 2: "free"}
_JOINT_TYPE = {0: "D6", 1: "hinge", 2: "fixed"}
_SHAPE = {2: "concave_mesh", 4: "convex_mesh", 5: "box", 6: "sphere", 7: "capsule"}

# property names of the objects in the blob (RigidBody 0x4fe311, Joint 0x51f882,
# D6Joint 0x51ff66, PivotSheet) in the spelling the classes register (`mass`,
# `movementType`); the key is kapow_props.name_hash(name), which folds case
_PROP_NAMES = (
    "name mass linearDamping angularDamping numSolverIterations movementType "
    "maxLinearVelocity maxAngularVelocity linearVelocity angularVelocity "
    "enableJointMotors breakable maxForceBeforeBreak maxTorqueBeforeBreak "
    "actorCollisionEnabled jointProjection jointProjectionDist jointProjectionAngle "
    "childSpacePos childSpaceOrient parentSpacePos parentSpaceOrient jointType "
    "swing1LimitType swing1MotionLimitValue swing2LimitType swing2MotionLimitValue "
    "twistLimitType lowTwistMotionLimitValue highTwistMotionLimitValue "
    "swing1MotionLimitRestitution swing1MotionLimitSpring swing1MotionLimitDamping "
    "swing2MotionLimitRestitution swing2MotionLimitSpring swing2MotionLimitDamping "
    "lowTwistMotionLimitRestitution lowTwistMotionLimitSpring lowTwistMotionLimitDamping "
    "highTwistMotionLimitRestitution highTwistMotionLimitSpring highTwistMotionLimitDamping "
    "xLimitType yLimitType zLimitType linearMotionLimitValue linearMotionLimitRestitution "
    "linearMotionLimitSpring linearMotionLimitDamping movementMotorType "
    "movementMotorTargetPos movementMotorTargetVelocity xMotorPower yMotorPower zMotorPower "
    "twistMotorType twistMotorPower twistMotorTargetSpeed orientMotorPower "
    "orientMotorTargetOrient useRealtime recordInSavepoints runScript "
    "uniqueID friction restitution collisionMask"
).split()
_names_cache = {}


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def property_names():
    """{keyHash: name} for the blob / pivot-book properties; the names this module
    consumes first, then the fragment key tables (cloth properties)."""
    if not _names_cache:
        try:
            with open(os.path.join(_HERE, "kapow_fragment_keys.pkl"), "rb") as fh:
                kd = pickle.load(fh)
            for tab in ("nameable", "promoted"):
                for h, v in kd.get(tab, {}).items():
                    _names_cache[h] = v if isinstance(v, str) else v[0]
        except (OSError, pickle.UnpicklingError, KeyError):
            pass
        for nm in _PROP_NAMES:
            _names_cache[kapow_props.name_hash(nm)] = nm
    return _names_cache


# ---- engine quaternion rule -------------------------------------------------
def qmul(a, b):
    """Hamilton product a (x) b, xyzw."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return [
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    ]


def qconj(q):
    return [-q[0], -q[1], -q[2], q[3]]


def rot(q, v):
    """Engine vector rotation: conj(q) v q."""
    return qmul(qmul(qconj(q), [v[0], v[1], v[2], 0.0]), q)[:3]


def frame_matrix(q):
    """3x3 whose columns are the frame's X, Y, Z axes in the parent: R(conj(q))."""
    return np.array([rot(q, e) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1))], float).T


def _r(x, n=6):
    if isinstance(x, (list, tuple, np.ndarray)):
        return [_r(y, n) for y in x]
    x = float(x)
    return float(("%." + str(n) + "g") % x) if abs(x) > 1e-9 else 0.0


# ---- reading ----------------------------------------------------------------
def shape_record(v):
    """One collision volume as the rig's shape: `file` = stored values, `physx` =
    what the engine hands to PhysX (0x4f727a capsule, 0x4f6f54 box, 0x4f7145 sphere:
    every size grown by the skin width), `contact` = the stored size in the same
    terms -- the surface things rest on, because PhysX lets shapes sink in by the
    skin width the engine added (use this one in a solver without a skin width)."""
    s = {
        "type": _SHAPE.get(v["type"], "type_%d" % v["type"]),
        "local_pos": _r(v["pos"]),
        "local_quat_xyzw": _r(v["quat"]),
    }
    if v["type"] == 7:
        d, h = float(v["diameter"]), float(v["height"])
        s["file"] = {"diameter": _r(d), "height_total": _r(h)}
        cyl = h - d
        s["physx"] = {
            "radius": _r(d * 0.5 + SKIN_WIDTH),
            "height": _r(cyl if cyl > 0 else MIN_CAPSULE_HEIGHT),
            "axis": "local +Y",
        }
        s["contact"] = dict(s["physx"], radius=_r(d * 0.5))
    elif v["type"] == 6:
        rad = float(v["radius"])
        s["file"] = {"radius": _r(rad)}
        s["physx"] = {"radius": _r(max(rad, MIN_EXTENT) + SKIN_WIDTH)}
        s["contact"] = {"radius": _r(max(rad, MIN_EXTENT))}
    elif v["type"] == 5:
        s["file"] = {"size_full": _r(v["size"])}
        s["physx"] = {
            "half_extents": _r(
                [max(abs(float(x)) * 0.5, MIN_EXTENT) + SKIN_WIDTH for x in v["size"]]
            )
        }
        s["contact"] = {
            "half_extents": _r([max(abs(float(x)) * 0.5, MIN_EXTENT) for x in v["size"]])
        }
    else:
        s["file"] = {
            "mode": int(v["mode"]),
            "vertices": [_r(p) for p in np.asarray(v["verts"], float).reshape(-1, 3)],
            "indices": [int(i) for i in v["indices"]],
            "cooked_blob_bytes": len(v["blob"]),
        }
    return s


def _limit(o, pre):
    return {
        "restitution": o[pre + "Restitution"],
        "spring": _r(o[pre + "Spring"], 7),
        "damping": o[pre + "Damping"],
    }


def is_tuned(joints, bodies):
    """False for a rig nobody authored: every angular limit 0 with spring 0 (the
    D6 constructor defaults; bs2 and the go-go dancers ship like that)."""
    for j in joints:
        vals = (
            j["swing1"]["limit_deg"],
            j["swing2"]["limit_deg"],
            j["twist"]["low_deg"],
            j["twist"]["high_deg"],
            j["swing1"]["spring"],
        )
        if any(abs(x) > 0 for x in vals):
            return True
    return not joints and bool(bodies)


def byte_order(blob, pivot_book=False):
    """Byte order of a model header ("<" PC, ">" Xbox 360 / PS3), read from its
    opening [u32 length][class name] (char_lib.header_order: the field
    watchmen_extract.asset_class reads in the archive's order); of a pivot book,
    from the name length of its first object at offset 12.  "<" when the bytes do
    not say."""
    import struct

    if pivot_book:
        if len(blob) < 16:
            return "<"
        le, be = (struct.unpack_from(bo + "I", blob, 12)[0] for bo in ("<", ">"))
        return ">" if be <= 64 < le else "<"
    import char_lib

    return char_lib.header_order(blob) or "<"


#: why build() returned None (explain())
NO_LAYOUT = (
    "the model header follows neither known layout (Part 2, or the older record format "
    "of stand-alone Part 1), so its articulated body is not read"
)
NO_BODY = "the model has no articulated body with joints"
BAD_BODY = "the articulated body does not match the node list or its property records"


def explain(mb, order=None):
    """None when build(mb, order) gives a rig, else the reason it gives none."""
    return _build(mb, order)[1]


def build(mb, order=None, cloth_only=False):
    """Skeleton / character ModelRes header -> rig dict, or None when the model
    has no articulated body with joints (explain() says why).  order: "<" / ">",
    None = byte_order(mb) (console headers are big-endian).  Field names follow
    findings/wp2_ragdoll_rigs.json (`rigs[<key>]`).  cloth_only: see _build."""
    return _build(mb, order, cloth_only)[0]


#: NxClothDesc values the game sets for every cloth (0x50c95f), not stored per model
CLOTH_PHYSX_CONSTANTS = {
    "tear_factor": 1.5,
    "attachment_tear_factor": 1.5,
    "attachment_response": 0.2,
    "to_fluid_response": 1.0,
    "from_fluid_response": 1.0,
    "wake_up_counter": 0.4,
    "sleep_linear_velocity": -1.0,
    "scene": 1,
}


def cloth_flags(props):
    """NxClothFlag word the game builds from a cloth's properties (0x50cd45-0x50cdee),
    without the pressure bit 0x1, which also needs a closed mesh."""
    flags = 0
    if props.get("useGravity"):
        flags |= 0x20
    flags |= {1: 0x100, 2: 0x4100}.get(props.get("dampingType"), 0)
    flags |= {0: 0x4, 2: 0x200}.get(props.get("collisionType"), 0)
    if props.get("isSelfColliding"):
        flags |= 0x8
    flags |= {1: 0x40, 2: 0xC0}.get(props.get("bendConstraintType"), 0)
    if props.get("useMinAdhereVelocity"):
        flags |= 0x40000
    return flags


def cloth_physx(props):
    """The derived `physx` record of a cloth: what the NxClothDesc of 0x50c95f holds
    beyond the stored properties."""
    out = {
        "flags": "0x%x" % cloth_flags(props),
        "pressure_flag_if_mesh_closed": bool(props.get("isPressurized")),
    }
    out.update(CLOTH_PHYSX_CONSTANTS)
    out["friction"] = "pivot sheet of the owning node (0x4f5d6a)"
    out["source"] = "0x50c95f"
    return out


def cloth_attachment(vertex, value):
    """One cloth attachment: 0xFFFFFFFF is a world fix point (0x507dd0), any other
    value the node index of the cloth-scene body the vertex is pinned to (0x517b06 /
    0x507f08)."""
    fixed = value == 0xFFFFFFFF
    return {
        "vertex": vertex,
        "cloth_body_node_index": None if fixed else value,
        "world_fixed": fixed,
    }


#: how the engine decides whether a cloth's world fix points are applied
WORLD_FIXES_RULE = (
    "0x507dd0 / 0x4b96bc / 0x4b6e9f: a world fix is skipped only for a format 6 buffer with"
    " characterClothMode on"
)


def cloth_mesh_format(model, node_index, mesh_index):
    """Stored FORMAT of the vertex buffer a cloth simulates: LOD 0 submesh
    `mesh_index` of part `node_index` in a parsed model header
    (watchmen_extract.parse_model_header), or None when the lookup fails."""
    try:
        fmt = model["parts"][node_index]["lods"][0][mesh_index]["format"]
    except (TypeError, KeyError, IndexError):
        return None
    return fmt if isinstance(fmt, int) and not isinstance(fmt, bool) else None


def world_fixes_applied(mesh_format, props):
    """Whether the engine applies a cloth's world fix points (0x507dd0): it skips
    them only when the cloth's vertex buffer is format 6 (skinned, 0x4b6e9f) and
    characterClothMode is on (0x4b96bc; constructor default true).  None when the
    buffer format is not known."""
    if mesh_format is None:
        return None
    return not (mesh_format == 6 and bool(props.get("characterClothMode", True)))


def _model_header(mb, order):
    """parse_model_header(mb), or None (a blob the mesh reader does not follow)."""
    try:
        import watchmen_extract as _wx

        return _wx.parse_model_header(mb, order)
    except Exception:
        return None


def _cloth_record(c, o, model):
    props = {k: v for k, v in o["props"].items() if not k.startswith("key_")}
    fmt = cloth_mesh_format(model, c["node"], c["mesh"])
    return {
        "node_index": c["node"],
        "mesh_index": c["mesh"],
        "mesh_format": fmt,
        "attachments": [cloth_attachment(a, b) for a, b in c["attachments"]],
        "world_fixes_applied": world_fixes_applied(fmt, props),
        "world_fixes_rule": WORLD_FIXES_RULE,
        "properties": props,
        "physx": cloth_physx(o["props"]),
    }


def _build(mb, order=None, cloth_only=False):
    """(rig, None) or (None, reason).  cloth_only: also build for a model whose
    articulated body has cloths but no body or no joint (a prop such as Curtains_01;
    the command line of this module asks for it, the character export does not)."""
    if order is None:
        order = byte_order(mb)
    m = _pmn.model_physics(mb, order)
    if not m:
        return None, NO_LAYOUT
    nodes = m["nodes"]
    ab = m["articulated_body"]
    if (not ab["bodies"] or not ab["joints"]) and not (cloth_only and ab["cloths"]):
        return None, NO_BODY
    n = len(nodes)
    if any(i >= n for i in ab["bodies"] + ab["cloth_bodies"]):
        return None, BAD_BODY
    par = [nd["parent"] for nd in nodes]
    wq = [None] * n
    wp = [None] * n
    for i, nd in enumerate(nodes):  # parents precede children in the file
        p = par[i]
        if p < 0 or wq[p] is None:
            wq[i], wp[i] = list(nd["quat"]), list(nd["pos"])
        else:
            wq[i] = qmul(nd["quat"], wq[p])
            wp[i] = [a + b for a, b in zip(wp[p], rot(wq[p], nd["pos"]))]
    objs = _sr.record_objects(ab["records"], property_names(), order)
    nb, nc, nj = len(ab["bodies"]), len(ab["cloths"]), len(ab["joints"])
    if len(objs) != nb + nc + nj:
        return None, BAD_BODY
    bobj, cobj, jobj = objs[:nb], objs[nb : nb + nc], objs[nb + nc :]

    bodies = []
    for bi, (ni, ob) in enumerate(zip(ab["bodies"], bobj)):
        o = ob["props"]
        bodies.append(
            {
                "index": bi,
                "bone": nodes[ni]["name"],
                "node_index": ni,
                "name_in_file": o["name"],
                "mass": _r(o["mass"], 7),
                "linear_damping": _r(o["linearDamping"]),
                "angular_damping": _r(o["angularDamping"]),
                "solver_iterations_file": o["numSolverIterations"],
                "solver_iterations_runtime": RUNTIME_SOLVER_ITERATIONS,
                "max_linear_velocity": o["maxLinearVelocity"],
                "max_angular_velocity": o["maxAngularVelocity"],
                "movement_type_file": o["movementType"],
                "bind_world_pos": _r(wp[ni]),
                "bind_world_quat_xyzw": _r(wq[ni]),
                "shapes": [shape_record(v) for v in nodes[ni]["volumes"][0]],
            }
        )

    def axes(q):
        return {
            "twist_x": _r(rot(q, [1, 0, 0])),
            "swing1_y": _r(rot(q, [0, 1, 0])),
            "swing2_z": _r(rot(q, [0, 0, 1])),
        }

    joints = []
    for (pa, ch), ob in zip(ab["joints"], jobj):
        o = ob["props"]
        if not (0 <= pa < nb and 0 <= ch < nb):
            return None
        pn, cn = ab["bodies"][pa], ab["bodies"][ch]
        qcs, pcs = o["childSpaceOrient"], o["childSpacePos"]
        # parent frame = the child frame at bind pose seen from the parent body
        # (loader 0x517b34; the file stores no parent-space property)
        qjw = qmul(qcs, wq[cn])
        pjw = [a + b for a, b in zip(wp[cn], rot(wq[cn], pcs))]
        qps = qmul(qjw, qconj(wq[pn]))
        pps = rot(qconj(wq[pn]), [a - b for a, b in zip(pjw, wp[pn])])
        joints.append(
            {
                "name": o["name"],
                "parent_body": pa,
                "child_body": ch,
                "parent_bone": nodes[pn]["name"],
                "child_bone": nodes[cn]["name"],
                "type": _JOINT_TYPE.get(o["jointType"], "type_%d" % o["jointType"]),
                "child_frame": {
                    "pos": _r(pcs),
                    "quat_xyzw": _r(qcs),
                    "axes_in_child_bone": axes(qcs),
                    "source": "file (childSpacePos/childSpaceOrient)",
                },
                "parent_frame": {
                    "pos": _r(pps),
                    "quat_xyzw": _r(qps),
                    "axes_in_parent_bone": axes(qps),
                    "source": "derived: bind pose, loader 0x517b34 (not stored in the file)",
                },
                "frame_world_bind": {"pos": _r(pjw), "quat_xyzw": _r(qjw)},
                "linear": {
                    "x": _MOTION[o["xLimitType"]],
                    "y": _MOTION[o["yLimitType"]],
                    "z": _MOTION[o["zLimitType"]],
                    "limit": o["linearMotionLimitValue"],
                    "restitution": o["linearMotionLimitRestitution"],
                    "spring": o["linearMotionLimitSpring"],
                    "damping": o["linearMotionLimitDamping"],
                },
                "swing1": dict(
                    motion=_MOTION[o["swing1LimitType"]],
                    limit_deg=o["swing1MotionLimitValue"],
                    **_limit(o, "swing1MotionLimit"),
                ),
                "swing2": dict(
                    motion=_MOTION[o["swing2LimitType"]],
                    limit_deg=o["swing2MotionLimitValue"],
                    **_limit(o, "swing2MotionLimit"),
                ),
                "twist": {
                    "motion": _MOTION[o["twistLimitType"]],
                    "low_deg": o["lowTwistMotionLimitValue"],
                    "high_deg": o["highTwistMotionLimitValue"],
                    "low": _limit(o, "lowTwistMotionLimit"),
                    "high": _limit(o, "highTwistMotionLimit"),
                },
                "breakable": bool(o["breakable"]),
                "max_force": o["maxForceBeforeBreak"],
                "max_torque": o["maxTorqueBeforeBreak"],
                "collision_between_bodies": bool(o["actorCollisionEnabled"]),
                "projection": {
                    "enabled": bool(o["jointProjection"]),
                    "distance": _r(o["jointProjectionDist"]),
                    "angle_rad": _r(o["jointProjectionAngle"]),
                },
                "motors_file": {
                    "enabled": bool(o["enableJointMotors"]),
                    "orient_power": o["orientMotorPower"],
                    "twist_type": o["twistMotorType"],
                    "twist_power": o["twistMotorPower"],
                    "movement_type": o["movementMotorType"],
                    "xyz_power": [o["xMotorPower"], o["yMotorPower"], o["zMotorPower"]],
                },
            }
        )
    cloth_bodies = [
        {
            "bone": nodes[ni]["name"],
            "node_index": ni,
            "shapes": [shape_record(v) for v in nodes[ni]["volumes"][1]],
        }
        for ni in ab["cloth_bodies"]
    ]
    model = _model_header(mb, order) if ab["cloths"] else None
    cloths = [_cloth_record(c, o, model) for c, o in zip(ab["cloths"], cobj)]
    unbound = [
        {"bone": nd["name"], "node_index": i, "scene0": len(nd["volumes"][0])}
        for i, nd in enumerate(nodes)
        if nd["volumes"][0] and i not in ab["bodies"]
    ]
    rig = {
        "total_mass": _r(sum(b["mass"] for b in bodies), 7),
        "tuned": is_tuned(joints, bodies),
        "skeleton": [
            {
                "index": i,
                "name": nd["name"],
                "parent": par[i],
                "local_pos": _r(nd["pos"]),
                "local_quat_xyzw": _r(nd["quat"]),
            }
            for i, nd in enumerate(nodes)
        ],
        "bodies": bodies,
        "joints": joints,
        "cloth_scene_bodies": cloth_bodies,
        "cloths": cloths,
        "volumes_without_body": unbound,
    }
    return rig, None


def pivot_sheets(pb, order=None):
    """.pb bytes -> [sheet dict] with names resolved.  order: None = byte_order()."""
    if order is None:
        order = byte_order(pb, pivot_book=True)
    try:
        return _sr.parse_pivot_book(pb, property_names(), order)
    except (ValueError, struct.error):
        # the older record layout of stand-alone Part 1 (no type hash per record):
        # kapow_props reads both layouts and gives the same keys and the same id
        sheets = kapow_props.pivot_book(pb, order)["sheets"]
        if not sheets:
            raise
        return sheets


def material_from_pivot_book(pb, sheet="Ragdoll", order=None):
    """The physics material of a pivot sheet: {sheet, friction, restitution,
    collision_mask, unique_id}.  Raises KeyError when the book has no such sheet."""
    for s in pivot_sheets(pb, order):
        if s.get("name") == sheet:
            return {
                "sheet": sheet,
                "friction": _r(s["friction"]),
                # the engine uses the one value for both and combines two materials by
                # multiplying; restitution by averaging (NxMaterialDesc built at 0x51555a)
                "static_friction": _r(s["friction"]),
                "dynamic_friction": _r(s["friction"]),
                "friction_combine": "multiply",
                "restitution_combine": "average",
                "source": "0x51555a",
                "restitution": _r(s["restitution"]),
                "collision_mask": "0x%x" % (s["collisionMask"] & 0xFFFFFFFF),
                "unique_id": "0x%016x" % s["uniqueID"],
            }
    raise KeyError(sheet)


# ---- proxy meshes (shape-local) ----------------------------------------------
def _capsule_mesh(radius, height, seg=10, rings=3):
    """Capsule along +Y: cylinder of `height` plus two hemispheres."""
    verts, tris = [], []
    lat = []
    for i in range(1, rings + 1):  # top hemisphere, pole excluded
        a = math.pi / 2 * (1 - i / float(rings))
        lat.append((radius * math.cos(a), height / 2 + radius * math.sin(a)))
    for i in range(0, rings):  # bottom hemisphere
        a = math.pi / 2 * (i / float(rings))
        lat.append((radius * math.cos(a), -height / 2 - radius * math.sin(a)))
    verts.append((0.0, height / 2 + radius, 0.0))
    for rr, y in lat:
        for s in range(seg):
            t = 2 * math.pi * s / seg
            verts.append((rr * math.cos(t), y, rr * math.sin(t)))
    verts.append((0.0, -height / 2 - radius, 0.0))
    last = len(verts) - 1
    for s in range(seg):
        tris.append((0, 1 + (s + 1) % seg, 1 + s))
    for k in range(len(lat) - 1):
        a0, b0 = 1 + k * seg, 1 + (k + 1) * seg
        for s in range(seg):
            s1 = (s + 1) % seg
            tris.append((a0 + s, a0 + s1, b0 + s))
            tris.append((a0 + s1, b0 + s1, b0 + s))
    a0 = 1 + (len(lat) - 1) * seg
    for s in range(seg):
        tris.append((last, a0 + s, a0 + (s + 1) % seg))
    return np.array(verts, float), np.array(tris, np.uint32)


def _box_mesh(half):
    hx, hy, hz = half
    v = [(sx * hx, sy * hy, sz * hz) for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)]
    t = [
        (0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
        (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3),
    ]  # fmt: skip
    return np.array(v, float), np.array(t, np.uint32)


def proxy_mesh(shape, size="contact"):
    """(vertices Nx3, triangles Mx3) of a shape in ITS OWN frame; None for a mesh
    shape without usable triangles.  size: "contact" (the stored size, default) or
    "physx" (grown by the skin width, what the engine creates)."""
    t = shape["type"]
    if t == "capsule":
        return _capsule_mesh(shape[size]["radius"], shape[size]["height"])
    if t == "sphere":
        return _capsule_mesh(shape[size]["radius"], 0.0)
    if t == "box":
        return _box_mesh(shape[size]["half_extents"])
    f = shape.get("file", {})
    v = np.array(f.get("vertices", []), float).reshape(-1, 3)
    idx = [int(i) for i in f.get("indices", [])]
    if f.get("mode") == 1:  # triangle list, else a strip (0x522d17)
        tri = [idx[i : i + 3] for i in range(0, len(idx) - 2, 3)]
    else:
        tri = [
            (idx[i], idx[i + 1], idx[i + 2]) if i % 2 == 0 else (idx[i + 1], idx[i], idx[i + 2])
            for i in range(len(idx) - 2)
        ]
    tri = [t3 for t3 in tri if len(set(t3)) == 3 and max(t3) < len(v)]
    if not len(v) or not tri:
        return None
    return v, np.array(tri, np.uint32)


# glTF (x, y, z) -> Blender (x, -z, y): what the stock importer applies (+Y up to +Z up)
_C = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])


def to_blender(M):
    """4x4 in glTF/engine space -> the same frame in Blender world space."""
    C = np.eye(4)
    C[:3, :3] = _C
    return C @ np.asarray(M, float) @ C.T


def _m4(R, t):
    M = np.eye(4)
    M[:3, :3] = R
    M[:3, 3] = t
    return M


def _m2q(R):
    """3x3 -> xyzw unit quaternion (standard convention, as glTF)."""
    t = R[0, 0] + R[1, 1] + R[2, 2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [(R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s, 0.25 * s]
    elif R[0, 0] > R[1, 1] and R[0, 0] > R[2, 2]:
        s = math.sqrt(1.0 + R[0, 0] - R[1, 1] - R[2, 2]) * 2
        q = [0.25 * s, (R[0, 1] + R[1, 0]) / s, (R[0, 2] + R[2, 0]) / s, (R[2, 1] - R[1, 2]) / s]
    elif R[1, 1] > R[2, 2]:
        s = math.sqrt(1.0 + R[1, 1] - R[0, 0] - R[2, 2]) * 2
        q = [(R[0, 1] + R[1, 0]) / s, 0.25 * s, (R[1, 2] + R[2, 1]) / s, (R[0, 2] - R[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + R[2, 2] - R[0, 0] - R[1, 1]) * 2
        q = [(R[0, 2] + R[2, 0]) / s, (R[1, 2] + R[2, 1]) / s, 0.25 * s, (R[1, 0] - R[0, 1]) / s]
    n = math.sqrt(sum(x * x for x in q))
    return [x / n for x in q]


def bone_slots(rig, bind_names):
    """{bone name: palette slot} for the rig's bodies (None when a body's bone is
    not in the bind)."""
    low = {str(nm).lower(): k for k, nm in enumerate(bind_names)}
    names = [str(x) for x in bind_names]
    out = {}
    for b in rig["bodies"]:
        nm = b["bone"]
        out[nm] = names.index(nm) if nm in names else low.get(nm.lower())
    return out


def blender_limits(j):
    """A joint's limits for a Blender GENERIC rigid-body constraint on the imported
    RJ.<child bone> empty (or any object with blender.bind_world_matrix): radians,
    per constraint-local axis.  The stock importer turns a node's local axes
    (x, y, z) into Blender's (x, z, -y), so the empty's local X is the twist axis,
    its local Z the swing1 axis and its local Y the swing2 axis reversed (all swing
    limits are symmetric, so the reversal does not show)."""

    def sw(s):
        if s["motion"] == "free":
            return None
        a = math.radians(s["limit_deg"]) if s["motion"] == "limited" else 0.0
        return [_r(-a), _r(a)]

    tw = j["twist"]
    if tw["motion"] == "free":
        x = None
    elif tw["motion"] == "limited":
        x = [_r(math.radians(tw["low_deg"])), _r(math.radians(tw["high_deg"]))]
    else:
        x = [0.0, 0.0]
    lin = [None if j["linear"][a] == "free" else [0.0, 0.0] for a in "xyz"]
    return {
        "type": "GENERIC",
        "object1": j["parent_bone"],
        "object2": j["child_bone"],
        "disable_collisions": not j["collision_between_bodies"],
        "axes": "x = twist, y = swing2 (reversed), z = swing1",
        "limit_ang_x": x,
        "limit_ang_y": sw(j["swing2"]),
        "limit_ang_z": sw(j["swing1"]),
        "limit_lin_x": lin[0],
        "limit_lin_y": lin[1],
        "limit_lin_z": lin[2],
    }


def bullet_damping(c):
    """PhysX damping coefficient c (1/s) -> Blender/Bullet damping d (0..1):
    Bullet scales velocity by (1 - d)^dt, PhysX by ~exp(-c dt)."""
    return _r(1.0 - math.exp(-float(c)))


def glb_helpers(rig, bind_names, Rb, tb, material=None, frame=None):
    """What variant_glb.write_glb adds for the rig (`rig`, Rb, tb: engine numbers,
    as build() and the binds give them):
      shapes: [{name "RB.<bone>.<i>", slot, verts (bind world, float32 Nx3), tris,
                extras}]   -- proxy meshes skinned rigidly to joint `slot`
      joints: [{name "RJ.<child bone>", translation, rotation (xyzw, glTF), extras}]
      extras: the asset-level record.
    Bodies whose bone is not in the bind are skipped (and listed).

    verts / translation / rotation are ENGINE numbers in both frames: write_glb
    reflects them with the rest of the document.  The `extras` are what ends up
    in the file unchanged, so they are in the output frame (`frame`, default
    frame.mode()): in the true frame they are those of the reflected rig."""
    out = _glb_helpers(rig, bind_names, Rb, tb, material)
    if not _frame.is_true(frame):
        return out
    Rt = np.array([_frame.mat4(R) for R in np.asarray(Rb, float)])
    tt = np.asarray(tb, float) * np.array([-1.0, 1.0, 1.0])
    true = _glb_helpers(reflect_rig(rig), bind_names, Rt, tt, material)
    for kind in ("shapes", "joints"):
        for a, b in zip(out[kind], true[kind]):
            a["extras"] = b["extras"]
    out["extras"] = true["extras"]
    return out


def _glb_helpers(rig, bind_names, Rb, tb, material=None):
    """glb_helpers for the rig and binds as given, all in one frame."""
    slots = bone_slots(rig, bind_names)
    Rb = np.asarray(Rb, float)
    tb = np.asarray(tb, float)
    shapes, joints, skipped = [], [], []
    for b in rig["bodies"]:
        k = slots.get(b["bone"])
        if k is None:
            skipped.append(b["bone"])
            continue
        Bk = _m4(Rb[k], tb[k])
        body = {
            "bone": b["bone"],
            "joint_node": "b%d" % k,
            "mass": b["mass"],
            "linear_damping": b["linear_damping"],
            "angular_damping": b["angular_damping"],
            "solver_iterations": {
                "file": b["solver_iterations_file"],
                "runtime": b["solver_iterations_runtime"],
            },
        }
        if material:
            body["friction"] = material["friction"]
            body["restitution"] = material["restitution"]
        for i, s in enumerate(b["shapes"]):
            pm = proxy_mesh(s)
            if pm is None:
                continue
            L = _m4(frame_matrix(s["local_quat_xyzw"]), s["local_pos"])
            W = Bk @ L
            v = pm[0] @ W[:3, :3].T + W[:3, 3]
            ex = {
                "kind": "shape",
                "index": i,
                "shape": {k2: s[k2] for k2 in ("type", "file", "contact", "physx") if k2 in s},
                "local_pos": s["local_pos"],
                "local_quat_xyzw": s["local_quat_xyzw"],
                "bind_world_matrix": _r(W[:3].reshape(-1).tolist(), 7),
                "blender_bind_world_matrix": _r(to_blender(W)[:3].reshape(-1).tolist(), 7),
                "body": body,
            }
            if s["type"] in ("convex_mesh", "concave_mesh"):
                ex["shape"] = {"type": s["type"], "vertices": len(s["file"]["vertices"])}
            shapes.append(
                {
                    "name": "RB.%s.%d" % (b["bone"], i),
                    "slot": k,
                    "verts": v.astype(np.float32),
                    "tris": pm[1],
                    "extras": ex,
                }
            )
    for j in rig["joints"]:
        kc, kp = slots.get(j["child_bone"]), slots.get(j["parent_bone"])
        if kc is None or kp is None:
            continue
        cf = j["child_frame"]
        W = _m4(Rb[kc], tb[kc]) @ _m4(frame_matrix(cf["quat_xyzw"]), cf["pos"])
        ex = {
            "kind": "joint",
            "name": j["name"],
            "type": j["type"],
            "parent_bone": j["parent_bone"],
            "child_bone": j["child_bone"],
            "parent_joint_node": "b%d" % kp,
            "child_joint_node": "b%d" % kc,
            "axes": "node +X = twist, +Y = swing1, +Z = swing2 (PhysX D6 frame)",
            "swing1": j["swing1"],
            "swing2": j["swing2"],
            "twist": j["twist"],
            "linear": j["linear"],
            "projection": j["projection"],
            "breakable": j["breakable"],
            "collision_between_bodies": j["collision_between_bodies"],
            "blender": dict(
                blender_limits(j),
                bind_world_matrix=_r(to_blender(W)[:3].reshape(-1).tolist(), 7),
            ),
        }
        joints.append(
            {
                "name": "RJ.%s" % j["child_bone"],
                "translation": [float(x) for x in W[:3, 3]],
                "rotation": [float(x) for x in _m2q(W[:3, :3])],
                "extras": ex,
            }
        )
    extras = {
        "format": FORMAT,
        "tuned": rig["tuned"],
        "total_mass": rig["total_mass"],
        "bodies": len(rig["bodies"]),
        "joints": len(joints),
        "helper_root": HELPER_ROOT,
        "proxy_size": "contact",
        "helper_nodes": (
            "node '%s' (in no scene; Blender: collection 'Orphan Nodes', switched off): "
            "RB.<bone>.<i> = proxy mesh of shape i at its stored (contact) size, skinned rigidly "
            "to the bone's joint; RJ.<child bone> = empty at the joint frame in bind pose"
            % HELPER_ROOT
        ),
        "skipped_bodies": skipped,
    }
    return {"shapes": shapes, "joints": joints, "extras": extras}


# What the engine does with the rig while it runs (read from the code; addresses in
# R/findings/impl_ragdoll.md section 6).
RUNTIME_RULES = {
    "bones_without_body": "the pose is built from the bodies: each body bone takes its "
    "body's transform (times the bind-pose offset between the two, 0x4b96da); every other "
    "bone keeps its animated LOCAL transform and so rides its nearest ancestor that has a "
    "body (0x58edf9 -> 0x5958c3 / 0x595704).  While the ragdoll weight is below 1 the "
    "result is blended with the animation pose",
    "handover": "going limp = the 17 kinematic bodies become dynamic where they are "
    "(clearBodyFlag(NX_BF_KINEMATIC) after wakeUp, RigidBody 0x4fe5ed); the engine writes "
    "no velocity at that moment.  Velocities come afterwards from CharacterVisual."
    "StateRagdollDriven 0x69ed7c (mean velocity / impulse of the hit, x 1.2)",
    "solver_iterations": RUNTIME_SOLVER_ITERATIONS,
}


CONVENTIONS = {
    "units": "metres, kilograms, seconds; limit angles in degrees (engine converts with "
    "0.0174533, 0xc8c574), blender.* limits in radians",
    "axes": "engine space, +Y up, values verbatim from the files -- the same space as the "
    "GLB, which is a mirror image of the real-world pose (docs/ANIMATION_META.md)",
    "quaternions": "xyzw as stored; world = local (x) parent (Hamilton), a vector rotates as "
    "conj(q) v q.  For a standard (q v q*) library use the conjugate",
    "bone_frame": "a body's frame is its bone's frame (actor pose = bone pose, 0x5123d2); "
    "shape local_pos / local_quat_xyzw are in that frame",
    "joint_frames": "D6: X = twist, Y = swing1, Z = swing2; actor[0] = parent body, actor[1] "
    "= child body (0x5141ee).  child_frame is stored; parent_frame is the same frame at "
    "bind pose seen from the parent bone (0x517b34)",
    "limits": "swing limits are symmetric half-angles about the bind pose; twist is "
    "low..high.  'limited' with spring > 0 is a soft limit (spring N*m/rad, damping "
    "N*m*s/rad, unscaled); 'limited' 0 with spring 0 is effectively locked",
    "shapes": "file = stored; physx = what the engine simulates: capsule radius = diameter/2 "
    "+ 0.025, cylinder height = height_total - diameter (0.001 if <= 0), box half extents "
    "= size/2 + 0.025, sphere radius + 0.025, with skinWidth 0.025 (shapes may sink into "
    "each other by that much); contact = the stored size in the same terms = where "
    "surfaces come to rest.  The RB proxies have the contact size: at it no two bodies of "
    "a rig overlap in the bind pose unless a joint connects them.  Capsule axis = local +Y",
    "blender": "stock glTF importer: Blender matrix = C M C^-1 with C: (x, y, z) -> (x, -z, "
    "y), a proper rotation, so angles keep their sign; an object's local axes (x, y, z) "
    "become Blender's (x, z, -y).  blender.bind_world_matrix / blender_bind_world_matrix "
    "are 3x4 row-major in Blender world space at bind (rest) pose and equal what the "
    "importer gives the helper nodes.  In that frame a capsule's axis is local Z and a "
    "box's half extents read (x, z, y); a GENERIC constraint on an RJ empty limits twist "
    "about its local X, swing1 about local Z and swing2 about local Y",
}


def _refl_shape(s):
    s["local_pos"] = _frame.vec(s["local_pos"])
    s["local_quat_xyzw"] = _frame.quat(s["local_quat_xyzw"])
    f = s.get("file")
    if isinstance(f, dict) and "vertices" in f:
        # the triangle indices stay: in the true frame the file order is the
        # outward (counter-clockwise) one
        s["file"] = dict(f, vertices=[_frame.vec(v) for v in f["vertices"]])
    return s


def reflect_rig(rig):
    """The rig of build() (engine numbers = the mirrored frame) in the true frame,
    or back: a deep copy with every position x-negated, every quaternion turned
    into (x, -y, -z, w) and the frame axes re-expressed.

    A frame F becomes S F S (S = diag(-1, 1, 1)), a proper rotation whose axes
    are X' = -S X, Y' = S Y, Z' = S Z.  Limits do not change: a turn by a about
    the twist axis X of the mirrored rig is the turn by +a about X' of the
    reflected one, and the swing limits are symmetric half-angles."""
    import copy

    out = copy.deepcopy(rig)
    for nd in out.get("skeleton", []):
        nd["local_pos"] = _frame.vec(nd["local_pos"])
        nd["local_quat_xyzw"] = _frame.quat(nd["local_quat_xyzw"])
    for b in out.get("bodies", []):
        b["bind_world_pos"] = _frame.vec(b["bind_world_pos"])
        b["bind_world_quat_xyzw"] = _frame.quat(b["bind_world_quat_xyzw"])
    for b in out.get("bodies", []) + out.get("cloth_scene_bodies", []):
        for s in b.get("shapes", []):
            _refl_shape(s)
    for j in out.get("joints", []):
        for key, ax in (
            ("child_frame", "axes_in_child_bone"),
            ("parent_frame", "axes_in_parent_bone"),
            ("frame_world_bind", None),
        ):
            f = j.get(key)
            if not f:
                continue
            f["pos"] = _frame.vec(f["pos"])
            f["quat_xyzw"] = _frame.quat(f["quat_xyzw"])
            a = f.get(ax) if ax else None
            if a:
                x = a["twist_x"]  # X' = -S X
                a["twist_x"] = [x[0], -x[1] + 0.0, -x[2] + 0.0]
                a["swing1_y"] = _frame.vec(a["swing1_y"])  # Y' = S Y
                a["swing2_z"] = _frame.vec(a["swing2_z"])  # Z' = S Z
    return out


# The `axes` / `quaternions` sentences for a rig written in the true frame.
CONVENTIONS_TRUE = dict(CONVENTIONS)
CONVENTIONS_TRUE["axes"] = (
    "the GLB's own space: right-handed, +Y up, x = -engine x (coordinate_frame "
    "'right-handed-true').  Every position, quaternion, axis and matrix here is in "
    "that space, i.e. the file's value reflected: positions and convex-mesh vertices "
    "with x negated, quaternions (x, y, z, w) -> (x, -y, -z, w).  A frame F of the "
    "file is S F S here (S = diag(-1, 1, 1)): its twist axis is -S X, its swing axes "
    "S Y and S Z, and about those axes every limit, twist low..high included, has the "
    "file's value.  A rig file without a coordinate_frame key holds the engine's "
    "numbers verbatim (a mirror image, as its GLB)"
)
CONVENTIONS_TRUE["quaternions"] = (
    "xyzw in the engine's convention: world = local (x) parent (Hamilton), a vector "
    "rotates as conj(q) v q.  For a standard (q v q*) library use the conjugate"
)


def conventions(frame=None):
    """The `conventions` block of a sidecar in `frame` (default frame.mode())."""
    return CONVENTIONS_TRUE if _frame.is_true(frame) else CONVENTIONS


def sidecar(
    rig, bind_names=None, material=None, source_model=None, group=None, glb=None, frame=None
):
    """The <Variant>.ragdoll.json document.  `rig`: build()'s (engine numbers);
    it is written in `frame` (default frame.mode()), the frame of the GLB."""
    slots = bone_slots(rig, bind_names) if bind_names is not None else {}
    true = _frame.is_true(frame)
    if true:
        rig = reflect_rig(rig)
    doc = {
        "format": FORMAT,
        "glb": glb,
        "source_model": source_model,
        "tuned": rig["tuned"],
        "conventions": conventions("true" if true else "mirrored"),
        "common": {
            "material": material,
            "solver_iterations": {
                "file": sorted({b["solver_iterations_file"] for b in rig["bodies"]}),
                "runtime": RUNTIME_SOLVER_ITERATIONS,
                "note": "the game sets 10 on every ragdoll body at activation "
                "(CharacterVisual.command_activate_ragdoll 0x69eac6)",
            },
            "scene": {
                "fixed_timestep": 1.0 / 60.0,
                "max_substeps_per_frame": 8,
                "gravity_default": [0.0, -9.82, 0.0],
                "skin_width": SKIN_WIDTH,
            },
            "collision_groups": {
                "names": {str(k): v for k, v in COLLISION_GROUPS.items()},
                "pairs_enabled": [[a, b, 1] for a, b in _PAIRS_ON]
                + [[a, b, 0] for a, b in _PAIRS_OFF],
                "animated_group": group,
                "unique_groups": UNIQUE_GROUP_POOLS,
                "note": "pairs set by PhysicsSimulation.command_setup_collision_groups "
                "0x7dffbf; an active ragdoll gets a unique group (unique_groups)",
            },
            "runtime": RUNTIME_RULES,
            "blender": {
                "damping": {
                    "rule": "d = 1 - exp(-c)",
                    "linear": sorted({bullet_damping(b["linear_damping"]) for b in rig["bodies"]}),
                    "angular": sorted(
                        {bullet_damping(b["angular_damping"]) for b in rig["bodies"]}
                    ),
                },
                "shape_size": "use shape.contact (the RB proxies as imported), margin 0",
                "not_representable": [
                    "soft limits (PhysX: a limit with a spring gives way beyond the angle; "
                    "Blender's are hard)",
                    "swing cone and twist (PhysX: twist about X, then a cone over swing1 / "
                    "swing2; Blender limits three Euler angles, which agree only near the "
                    "bind pose)",
                    "joint projection",
                    "muscles (drives toward the animation)",
                    "skin width (shapes sinking in by 0.025)",
                    "collision group matrix and per-ragdoll unique groups",
                ],
            },
        },
        "joint_nodes": {nm: ("b%d" % k if k is not None else None) for nm, k in slots.items()},
    }
    if not rig["joints"]:
        doc["cloth_only_note"] = (
            "this model has no ragdoll: its articulated body holds cloths only "
            "(built with cloth_only); `tuned` says nothing here"
        )
    elif not rig["tuned"]:
        doc["untuned_note"] = (
            "this model's joints were never authored: every limit is 'limited 0' with "
            "spring 0 and every mass is the constructor default.  Shapes are valid; the "
            "joint data is exported as stored and is not usable as a ragdoll"
        )
    doc.update(rig)
    doc["joints"] = [dict(j, blender=blender_limits(j)) for j in rig["joints"]]
    return _frame.stamp_json(doc, "true") if true else doc


def group_for(key):
    """Collision group of the ANIMATED (kinematic) bodies by character kind
    (CharacterVisual.command_reset_collision_group 0x69e9a5)."""
    return {"rsh": 8, "nto": 9}.get(key, 4)


def sheet_for(key):
    """Pivot sheet of the Character node (fragment data: *CharVisual.fragment)."""
    return "Ragdoll_All" if key in ("rsh", "nto") else "Ragdoll"


def main(argv):
    """ragdoll_rig.py MODEL [PIVOTBOOK.pb] -> rig JSON on stdout."""
    import json

    if len(argv) < 2:
        print(main.__doc__)
        return 1
    mb = _read_bytes(argv[1])
    rig = build(mb, cloth_only=True)
    if rig is None:
        print("no rig from %s: %s" % (argv[1], explain(mb)), file=sys.stderr)
        return 1
    mat = material_from_pivot_book(_read_bytes(argv[2])) if len(argv) > 2 else None
    json.dump(sidecar(rig, material=mat, source_model=os.path.basename(argv[1])), sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
