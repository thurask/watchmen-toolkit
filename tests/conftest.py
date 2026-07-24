"""Shared fixtures and helpers for the wlib test-suite.

No game files, no network: every fixture builds synthetic data that matches the
engine layouts documented in the modules under test.
"""

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

# The wlib modules are FLAT top-level modules that import each other directly
# (``import watchmen_extract as we``), so the package directory must be on
# sys.path before any of them can be imported.
WLIB = Path(__file__).resolve().parent.parent / "wlib"
if str(WLIB) not in sys.path:
    sys.path.insert(0, str(WLIB))


# ---------------------------------------------------------------------------
# GLB container parsing
# ---------------------------------------------------------------------------

GLB_MAGIC = b"glTF"
CHUNK_JSON = b"JSON"
CHUNK_BIN = b"BIN\x00"

#: glTF componentType -> (numpy dtype, size in bytes)
COMPONENT = {
    5120: (np.int8, 1),
    5121: (np.uint8, 1),
    5122: (np.int16, 2),
    5123: (np.uint16, 2),
    5125: (np.uint32, 4),
    5126: (np.float32, 4),
}

#: glTF accessor type -> number of components
NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


class Glb:
    """A parsed .glb: JSON chunk, BIN chunk and the raw container fields.

    Deliberately hand-rolled (rather than a glTF library) so the tests pin the
    on-disk bytes -- chunk padding, chunk order, declared lengths -- and not
    some library's tolerant reinterpretation of them.
    """

    def __init__(self, raw):
        self.raw = raw
        self.magic = raw[0:4]
        self.version, self.total_length = struct.unpack_from("<II", raw, 4)
        self.chunks = []  # [(type, padded_payload)]
        p = 12
        while p + 8 <= len(raw):
            clen, ctype = struct.unpack_from("<I4s", raw, p)
            self.chunks.append((ctype, raw[p + 8 : p + 8 + clen]))
            p += 8 + clen
        self.json_chunk = next(c for t, c in self.chunks if t == CHUNK_JSON)
        self.bin_chunk = next((c for t, c in self.chunks if t == CHUNK_BIN), b"")
        self.j = json.loads(self.json_chunk.decode("utf-8"))

    # -- accessor access ---------------------------------------------------
    def accessor(self, i):
        """Accessor i -> numpy array shaped (count, ncomp) (or (count,) SCALAR)."""
        a = self.j["accessors"][i]
        dt, csz = COMPONENT[a["componentType"]]
        nc = NCOMP[a["type"]]
        bv = self.j["bufferViews"][a["bufferView"]]
        base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
        stride = bv.get("byteStride")
        if stride and stride != csz * nc:  # not produced by these writers
            raise AssertionError("interleaved bufferView not supported by this helper")
        n = a["count"]
        flat = np.frombuffer(self.bin_chunk, dt, count=n * nc, offset=base)
        return flat.reshape(n, nc) if nc > 1 else flat.reshape(n)

    def mat4_accessor(self, i):
        """Accessor i (MAT4) -> (count, 4, 4) row-major matrices.

        glTF stores matrices COLUMN-major, so each 16-float run is transposed
        back into the row-major convention the tests do their algebra in.
        """
        flat = self.accessor(i)
        return np.array([m.reshape(4, 4).T for m in flat], dtype=np.float64)

    # -- scene graph -------------------------------------------------------
    def parents(self):
        par = {}
        for i, nd in enumerate(self.j["nodes"]):
            for c in nd.get("children", []):
                par[c] = i
        return par

    def global_matrices(self, overrides=None):
        """Every node's global (world) 4x4.

        `overrides` maps node index -> partial TRS dict, so a test can evaluate
        the scene with animation channels applied without mutating the file.
        """
        par = self.parents()
        nodes = self.j["nodes"]
        cache = {}

        def local(i):
            nd = dict(nodes[i])
            if overrides and i in overrides:
                nd.update(overrides[i])
            if "matrix" in nd:
                return np.array(nd["matrix"], float).reshape(4, 4).T
            M = np.eye(4)
            M[:3, :3] = quat_xyzw_to_mat(nd.get("rotation", [0, 0, 0, 1]))
            M[:3, :3] *= np.asarray(nd.get("scale", [1, 1, 1]), float)  # columns
            M[:3, 3] = nd.get("translation", [0, 0, 0])
            return M

        def glob(i):
            if i not in cache:
                p = par.get(i)
                cache[i] = local(i) if p is None else glob(p) @ local(i)
            return cache[i]

        return {i: glob(i) for i in range(len(nodes))}

    def skin_matrices(self, mesh_node, skin_index, overrides=None):
        """glTF joint matrices for `skin_index` as seen from `mesh_node`.

        jointMatrix[j] = inverse(globalTransform(meshNode))
                         * globalTransform(joint[j]) * inverseBindMatrix[j]
        """
        sk = self.j["skins"][skin_index]
        G = self.global_matrices(overrides)
        ibm = self.mat4_accessor(sk["inverseBindMatrices"])
        inv_mesh = np.linalg.inv(G[mesh_node])
        return np.array([inv_mesh @ G[jn] @ ibm[k] for k, jn in enumerate(sk["joints"])])

    def sample_at(self, anim_index, t):
        """Animation `anim_index` evaluated at time `t` -> {node: TRS dict}.

        Only exact keyframe times are needed by the tests, so this picks the
        nearest key rather than interpolating.
        """
        anim = self.j["animations"][anim_index]
        out = {}
        for ch in anim["channels"]:
            s = anim["samplers"][ch["sampler"]]
            times = self.accessor(s["input"])
            vals = self.accessor(s["output"])
            k = int(np.argmin(np.abs(np.asarray(times, float) - t)))
            out.setdefault(ch["target"]["node"], {})[ch["target"]["path"]] = [
                float(x) for x in np.atleast_1d(vals[k])
            ]
        return out


def parse_glb(path):
    return Glb(Path(path).read_bytes())


def quat_xyzw_to_mat(q):
    """glTF XYZW quaternion -> 3x3 rotation matrix."""
    x, y, z, w = [float(v) for v in q]
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def skin_vertices(V, joints, weights, jm):
    """Linear-blend skinning: (NV,3) positions -> (NV,3) skinned positions."""
    V = np.asarray(V, float)
    out = np.zeros_like(V)
    for i in range(len(V)):
        M = np.zeros((4, 4))
        for c in range(4):
            M += float(weights[i][c]) * jm[int(joints[i][c])]
        out[i] = (M @ np.append(V[i], 1.0))[:3]
    return out


def axis_angle(axis, ang):
    """Rotation matrix from an axis/angle pair (right-handed)."""
    a = np.asarray(axis, float)
    a = a / np.linalg.norm(a)
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(ang) * K + (1 - np.cos(ang)) * (K @ K)


def iter_json(obj, path=""):
    """Yield (json-pointer-ish path, value) for every node of a JSON tree."""
    yield path, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_json(v, "%s/%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_json(v, "%s/%d" % (path, i))


# ---------------------------------------------------------------------------
# Synthetic rig / mesh / animation fixtures
# ---------------------------------------------------------------------------


class Rig:
    """A tiny synthetic character: bind pose, skinned mesh and one clip."""

    def __init__(self, tmp_path, nb=5, nv=8, frames=4, fps=15.0):
        rng = np.random.default_rng(20260724)
        self.NB, self.NV, self.F, self.fps = nb, nv, frames, fps
        # bind pose: a chain of joints, each a genuine rotation (no scale/shear)
        self.Rb = np.array([axis_angle(rng.uniform(-1, 1, 3), 0.25 + 0.17 * k) for k in range(nb)])
        self.tb = np.array([[0.05 * k, 0.40 * k, -0.03 * k] for k in range(nb)], float)
        self.names = np.array(["bone%d" % k for k in range(nb)])
        self.par = np.array([-1] + [k - 1 for k in range(1, nb)])
        self.B4 = np.tile(np.eye(4), (nb, 1, 1))
        self.B4[:, :3, :3] = self.Rb
        self.B4[:, :3, 3] = self.tb

        self.bind_npz = Path(tmp_path) / "bind.npz"
        np.savez(self.bind_npz, Rb=self.Rb, tb=self.tb, names=self.names, par=self.par)

        # mesh
        self.V = rng.uniform(-0.6, 0.6, (nv, 3)).astype(np.float32)
        self.SI = np.zeros((nv, 4), np.uint16)
        self.SW = np.zeros((nv, 4), np.float32)
        for i in range(nv):
            self.SI[i] = [(i + c) % nb for c in range(4)]
            w = rng.uniform(0.1, 1.0, 4)
            self.SW[i] = (w / w.sum()).astype(np.float32)
        # renormalise in float32 so the file bytes really sum to 1
        self.SW /= self.SW.sum(1, keepdims=True)
        self.T = np.array([[i, (i + 1) % nv, (i + 2) % nv] for i in range(nv - 2)], np.uint32)
        self.UV = rng.uniform(0, 1, (nv, 2)).astype(np.float32)

        # animation: an arbitrary per-frame WORLD pose per joint ...
        self.world = np.zeros((frames, nb, 4, 4))
        for f in range(frames):
            for k in range(nb):
                M = np.eye(4)
                M[:3, :3] = axis_angle([0.2, 1.0, 0.3], 0.11 * f + 0.07 * k) @ self.Rb[k]
                M[:3, 3] = self.tb[k] + np.array([0.013 * f, 0.021 * f, 0.007 * f])
                self.world[f, k] = M
        # ... turned into a skinning palette exactly as the engine defines it:
        # palette = worldAnim @ inverse(bind)
        self.invB4 = np.linalg.inv(self.B4)
        full = np.einsum("fkab,kbc->fkac", self.world, self.invB4)
        self.palette = full[:, :, :3, :].astype(np.float32)  # (F, NB, 3, 4)

    @property
    def parts(self):
        return [(self.V, self.SI, self.SW, self.T, self.UV, "mat_body")]

    @property
    def manifest(self):
        return [("clip_test", self.palette, self.fps)]

    def tpl(self):
        """rig_glb-style skeleton template (flat, identity inverse binds)."""
        return {
            "bone_count": self.NB,
            "bones": [
                {"name": str(self.names[k]), "parent": int(self.par[k])} for k in range(self.NB)
            ],
        }


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


# ---------------------------------------------------------------------------
# Synthetic ModelRes skeleton header
# ---------------------------------------------------------------------------

#: Engine node record: [pos f32x3][quat f32x4 XYZW][u32 namelen][name\0][u32 f1][i32 parent]
NODE_NAMES = [
    "GamePivot",
    "Bip01",
    "Bip01 Pelvis",
    "Bip01 Spine",
    "Bip01 Spine1",
    "Bip01 Neck",
    "Bip01 Head",
    "Bip01 L Thigh",
    "Bip01 L Calf",
    "Bip01 R Thigh",
    "Bip01 R Calf",
]


def synthetic_nodes(names=None):
    """-> [(name, pos(3), quat xyzw(4), parent)] with node 0 the unnamed root.

    Every node gets a DIFFERENT position and quaternion so an off-by-one in the
    transform/name pairing cannot pass by coincidence.
    """
    names = NODE_NAMES if names is None else names
    rng = np.random.default_rng(1917)
    nodes = [("", np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0]), -1)]
    for i, nm in enumerate(names):
        pos = np.round(rng.uniform(-2.0, 2.0, 3), 4)
        q = rng.uniform(-1, 1, 4)
        q = q / np.linalg.norm(q)
        nodes.append((nm, pos, q, i))  # parent = the preceding node
    return nodes


def build_model_header(nodes, order="<", count=None, break_quat=None):
    """Serialise `nodes` into a ModelRes-style header.

    count       : override the declared node count (defaults to len(nodes))
    break_quat  : index of a node whose quaternion is scaled off the unit
                  sphere, so parse() drops the record
    """
    b = bytearray()
    b += struct.pack(order + "I", len(nodes) if count is None else count)
    for i, (nm, pos, q, par) in enumerate(nodes):
        qq = np.asarray(q, float) * (2.0 if break_quat == i else 1.0)
        b += struct.pack(order + "3f", *[float(x) for x in pos])
        b += struct.pack(order + "4f", *[float(x) for x in qq])
        raw = nm.encode("ascii") + b"\0"
        b += struct.pack(order + "I", len(raw)) + raw
        b += struct.pack(order + "I", 0) + struct.pack(order + "i", int(par))
    return bytes(b)


def build_clip_header(key_count, duration, frame_rate_scale=1):
    """[f32 keyRate][f32 duration][u32 0][u32 keyCount][u32 frameRateScale]."""
    key_rate = (key_count - 1) / duration
    return struct.pack("<ffIII", key_rate, duration, 0, key_count, frame_rate_scale)
