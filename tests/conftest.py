"""Shared fixtures and helpers for the wlib test-suite.

No game files, no network: every fixture builds synthetic data that matches the
engine layouts documented in the modules under test.
"""

import json
import os
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

# The wlib modules are FLAT top-level modules that import each other directly
# (``import watchmen_extract as we``), so the package directory must be on
# sys.path before any of them can be imported.
# watchmen.py sits in the toolkit root and the Blender scripts in tools/; the test
# modules import each other's fixtures, so this folder goes on the path as well.
TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
WLIB = ROOT / "wlib"
for _p in (TESTS, ROOT / "tools", ROOT, WLIB):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import kapow_props as kp  # noqa: E402  (wlib is on the path from here on)


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


def pytest_collection_modifyitems(config, items):
    """tests/test_gltf_validator.py runs only when $WATCHMEN_GLTF_VALIDATOR names
    the Khronos validator (see that file); otherwise its tests are deselected --
    reported as "deselected", never as skipped or passed."""
    if os.environ.get("WATCHMEN_GLTF_VALIDATOR"):
        return
    keep, drop = [], []
    for item in items:
        is_validator = Path(str(item.fspath)).name == "test_gltf_validator.py"
        (drop if is_validator else keep).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


@pytest.fixture(autouse=True)
def no_leaked_options():
    """A test leaves the WATCHMEN_* variables as it found them, so no test
    depends on the order the suite runs in (a command that sets one must be
    undone by the test, e.g. through monkeypatch)."""
    before = {k: v for k, v in os.environ.items() if k.startswith("WATCHMEN_")}
    yield
    after = {k: v for k, v in os.environ.items() if k.startswith("WATCHMEN_")}
    assert after == before, "WATCHMEN_* variables changed by the test"


@pytest.fixture
def engine_frame(monkeypatch):
    """Write in the mirrored frame (`--frame mirrored`): the engine's numbers
    verbatim, so a test can compare the file with its synthetic engine input.
    The default (true-handed) frame is tested against it in test_frame.py."""
    monkeypatch.setenv("WATCHMEN_FRAME", "mirrored")


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


# ---------------------------------------------------------------------------
# characters_export.export on a synthetic extract
# ---------------------------------------------------------------------------


@pytest.fixture
def export_env(tmp_path, monkeypatch, rig):
    """A minimal extract: one character with two models on the rig fixture's
    bind, one baked clip; a second character whose bakes are still pending.
    The archive-reading steps (discover, binds, bakes) are replaced; everything
    from the cached bake to the written GLB runs as in a real export."""
    ex = tmp_path / "ex"
    (ex / "extracted").mkdir(parents=True)
    out = tmp_path / "chars"
    calls = {"bake": [], "faces": [], "load_parts": [], "jiggle_kw": []}

    import characters_export as ce

    monkeypatch.setattr(
        ce,
        "discover",
        lambda e: {
            "Heavy": {"Heavy": ("large", ["/m/Heavy_Body", "/m/Heavy_Hair"])},
            "Thug": {"Thug_A": ("small", ["/m/Thug_Body"])},
        },
    )
    monkeypatch.setattr(ce, "bind_mismatches", lambda e: {"large": "other bone list than X.model"})
    monkeypatch.setattr(ce, "ensure_all_binds", lambda keys, e, naz: {"small": "no skeleton"})
    monkeypatch.setattr(ce, "ensure_bind", lambda key, e, naz: str(rig.bind_npz))
    monkeypatch.setattr(ce, "animation_meta", lambda e, o: None)

    def bake_cache(key, bind, e, o, budget=None):
        calls["bake"].append(key)
        if key == "small":
            return 0, 2  # two clips still to bake
        cdir = os.path.join(o, "_bake", key)
        os.makedirs(cdir, exist_ok=True)
        f = os.path.join(cdir, "clip_test.npz")
        if not os.path.exists(f):
            np.savez(f, pal=rig.palette, dur=np.float32(0.2), fps=np.float32(rig.fps))
            open(os.path.join(cdir, "torn.tmp.npz"), "wb").close()  # a killed run's leftover
        return 1, 0

    monkeypatch.setattr(ce, "bake_cache", bake_cache)
    import char_lib
    import jiggle_d6

    def load_parts(models, bn, sheets=None):
        calls["load_parts"].append([os.path.basename(m) for m in models])
        return [
            (rig.V + np.float32(i), rig.SI, rig.SW, rig.T, rig.UV, "mat_" + os.path.basename(m))
            for i, m in enumerate(models)
        ]

    monkeypatch.setattr(char_lib, "load_parts", load_parts)
    jig = []

    def apply_jiggle(pal, fps, bind, model=None, loop=False, props=None):
        jig.append(model)
        calls["jiggle_kw"].append({"fps": fps, "model": model, "loop": loop, "props": props})
        return np.asarray(pal, np.float32) * np.float32(1.0)

    monkeypatch.setattr(jiggle_d6, "apply_jiggle", apply_jiggle)
    calls["jiggle"] = jig
    return ex, out, calls


# ---------------------------------------------------------------------------
# characters_export.face_attach on a synthetic head
# ---------------------------------------------------------------------------


def _bind_npz(path, names, R, t, par):
    np.savez(
        str(path),
        Rb=np.asarray(R, float),
        tb=np.asarray(t, float),
        names=np.array(names),
        par=np.array(par),
    )
    return str(path)


def _rz(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1.0]])


@pytest.fixture
def face_env(tmp_path, monkeypatch):
    """Body bind: Bip, Spine2, Neck, Head.  Face bind of the head model: Head,
    Jaw (below Head), Neck (aligned with the body's Neck) and Bip01 (0.5 m off
    the body's Bip: a misaligned match)."""
    ex = tmp_path / "ex"
    ex.mkdir()
    body_names = ["Bip", "Spine2", "Neck", "Head"]
    Rb = [np.eye(3), np.eye(3), np.eye(3), _rz(30)]
    tb = [[0, 1.0, 0], [0, 1.3, 0], [0, 1.5, 0], [0, 1.6, 0]]
    body = _bind_npz(tmp_path / "body.npz", body_names, Rb, tb, [-1, 0, 1, 2])
    face_names = ["Bip01", "Neck", "Head", "Jaw"]
    # the face model's frame: its Head at the origin, rotated by -10 deg
    Rh = _rz(-10)
    M = np.asarray(Rb[3]) @ Rh.T
    tf = [[0, 0.5, 0], [0, -0.1, 0], [0, 0, 0], [0, -0.05, 0.04]]
    Rf = [np.eye(3), np.eye(3), Rh, Rh]
    # Neck: aligned under the global head transform M,t (t maps face Head -> body Head)
    t = np.asarray(tb[3]) - M @ np.asarray(tf[2])
    Rf[1] = M.T @ np.asarray(Rb[2])
    tf[1] = list(M.T @ (np.asarray(tb[2]) - t))
    import build_bind_file as bbf
    import bake_v4
    import char_lib
    import face_export
    import parse_model_nodes

    def build(model, template, dst):
        _bind_npz(dst, face_names, Rf, tf, [-1, 0, 1, 2])
        return dst

    monkeypatch.setattr(bbf, "build", build)
    import characters_export as ce

    monkeypatch.setattr(ce, "_read_bytes", lambda p: b"")
    monkeypatch.setattr(
        parse_model_nodes,
        "parse",
        lambda b: (["", "x"], np.ones((2, 3)), np.tile([0, 0, 0, 1.0], (2, 1)), np.array([5, 0])),
    )
    V = np.array([[0, 0.02, 0.0], [0, -0.05, 0.04], [0, 0.45, 0], [0, -0.1, 0.01]], np.float32)
    # vertex k: all weight on face joint k (Bip01, Neck, Head, Jaw)
    SI = np.array([[0, 0, 0, 0], [1, 0, 0, 0], [2, 0, 0, 0], [3, 0, 0, 0]][::-1], np.uint16)
    SW = np.array([[1, 0, 0, 0]] * 4, np.float32)
    T = np.array([[0, 1, 2], [1, 2, 3]], np.uint32)
    UV = np.zeros((4, 2), np.float32)
    face_part = (V, SI, SW, T, UV, "face_mat")
    ref_V = (V.astype(float) @ M.T + t).astype(np.float32)
    ref_part = (
        ref_V,
        np.array([[3, 2, 0, 0]] * 4, np.uint16),
        np.array([[0.75, 0.25, 0, 0]] * 4, np.float32),
        T,
        UV,
        "head_mat",
    )

    def load_parts(models, bn, sheets=None):
        return [ref_part] if models == ["/m/StaticHead"] else [face_part]

    monkeypatch.setattr(char_lib, "load_parts", load_parts)
    monkeypatch.setattr(face_export, "head_family", lambda head: "Fam")
    clips = {
        "Fam/MouthClosed_EyesOpen": b"a",
        "Fam/MouthClosed_EyesClosed": b"b",
        "Fam/MouthTalk_EyesAnger": b"c",
        "Other/X": b"d",
    }
    monkeypatch.setattr(face_export, "face_clips", lambda e: clips)
    monkeypatch.setattr(bake_v4, "_load_bind", lambda p: None)
    poses = {
        "Fam/MouthClosed_EyesOpen": 0.0,
        "Fam/MouthClosed_EyesClosed": 1.0,
        "Fam/MouthTalk_EyesAnger": 2.0,
    }

    baked = []

    def bake(nm, up, bank=None, **kw):
        baked.append(kw)
        if nm not in poses:
            raise ValueError("no such clip")
        return np.full((1, 4, 3, 4), poses[nm], np.float32), 1.0

    monkeypatch.setattr(bake_v4, "bake", bake)
    return dict(ex=ex, body=body, bn=body_names, M=M, t=t, baked=baked)


# ---------------------------------------------------------------------------
# face_export.export on one synthetic head
# ---------------------------------------------------------------------------


@pytest.fixture
def faces_env(tmp_path, monkeypatch):
    """An extract with one face-rigged head and the face clips `clips` of its family
    (the test fills them in); the bind, the meshes and the GLB writer are replaced and
    every bake_v4.bake call is recorded as (clip, keyword arguments)."""
    import bake_v4
    import build_bind_file
    import char_lib
    import face_export
    import variant_glb as vg

    ex, out = tmp_path / "face_ex", tmp_path / "faces"
    (ex / "extracted").mkdir(parents=True)
    clips, baked, written = {}, [], []
    monkeypatch.setattr(face_export, "find_heads", lambda e: [str(tmp_path / "Head1")])
    monkeypatch.setattr(face_export, "head_family", lambda head: "EN1")
    monkeypatch.setattr(face_export, "face_clips", lambda e: clips)
    monkeypatch.setattr(
        build_bind_file, "build", lambda m, t, p: np.savez(p, names=np.array(["Jaw"]))
    )
    monkeypatch.setattr(bake_v4, "_load_bind", lambda p=None: None)

    def bake(nm, up, bank=None, **kw):
        baked.append((nm, kw))
        return np.zeros((2, 1, 3, 4), np.float32), 0.1

    monkeypatch.setattr(bake_v4, "bake", bake)
    monkeypatch.setattr(char_lib, "load_parts", lambda models, bn: [])
    monkeypatch.setattr(char_lib, "find_textures", lambda parts, roots: {})

    def write_glb(parts, anims, path, bind, textures=None, asset_extras=None):
        written.append(path)
        Path(path).write_bytes(b"glb")

    monkeypatch.setattr(vg, "write_glb", write_glb)
    return dict(ex=ex, out=out, clips=clips, baked=baked, written=written)


# ---------------------------------------------------------------------------
# Small builders and lookups shared by several test files
# ---------------------------------------------------------------------------


def u32s(*v):
    """Little-endian u32 values."""
    return struct.pack("<%dI" % len(v), *v)


def f32s(*v):
    """Little-endian f32 values."""
    return struct.pack("<%df" % len(v), *v)


def kstr(s):
    """A fragment string value: [u32 words][text NUL-padded to whole words]."""
    b = s.encode("latin1") + b"\0"
    b += b"\0" * (-len(b) % 4)
    return u32s(len(b) // 4) + b


def entity_ref(v):
    """None -> null, "host" -> tag 2, int -> tag 3, ("up", a, ids) -> tag 4,
    ("single", ids) -> tag 5."""
    if v is None:
        return u32s(1)
    if v == "host":
        return u32s(2)
    if isinstance(v, int):
        return u32s(3, v)
    if v[0] == "up":
        return u32s(4, v[1], len(v[2]), *v[2])
    return u32s(5, len(v[1]), *v[1])


def prop_value(v):
    """A fragment property value encoded by its Python type."""
    if isinstance(v, bool):
        return u32s(int(v))
    if isinstance(v, int):
        return u32s(v & 0xFFFFFFFF)
    if isinstance(v, float):
        return f32s(v)
    if isinstance(v, str):
        return kstr(v)
    if isinstance(v, list) and v and isinstance(v[0], str):
        return u32s(len(v)) + b"".join(kstr(s) for s in v)
    if isinstance(v, list):
        return f32s(*v)
    raise TypeError(v)


ENTITY_KEYS = ("logicalParent", "m_etarget1", "_eauxaction", "m_etriggerentity", "_ealldeadaction")


def frag_node(nid, typ, name, parent, order=0, **props):
    """One type record and one instance record.  Entity properties take the entity_ref
    forms, everything else is encoded by its Python type."""
    b = u32s(0xFFFFFFFF, nid) + kstr(typ) + u32s(0xFFFFFFFE, nid)
    b += u32s(kp.name_hash("name")) + kstr(name)
    b += u32s(kp.name_hash("logicalParent")) + entity_ref(parent)
    b += u32s(kp.name_hash("siblingOrder")) + u32s(order)
    for k, v in props.items():
        b += u32s(kp.name_hash(k)) + (entity_ref(v) if k in ENTITY_KEYS else prop_value(v))
    return b


def fragment_bytes(payload, name="", singleton=False, reapplyable=False, version=4):
    """A whole fragment file: header (Fragment::LoadHeader 0x54306d) and one chunk."""
    nm = name.encode("latin1") + b"\0"
    head = u32s(version) + bytes([int(singleton), 0]) + u32s(len(nm)) + nm
    head += bytes([int(reapplyable), 0]) + u32s(1)
    return head + u32s(len(payload)) + payload


def write_bytes(path, data):
    """Write `data` to `path`, making its folder."""
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as fh:
        fh.write(data)


def state_named(meta, cls, name):
    """State `name` of class `cls` in an anim_meta table."""
    return next(s for s in meta["classes"][cls]["states"] if s["name"] == name)


def rot_vector(R):
    """Rotation vector (axis x angle, radians) of a 3x3 rotation matrix."""
    a = float(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)))
    if a < 1e-12:
        return np.zeros(3)
    return a * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(a))


def rig_part(rig, dx, name):
    """The Rig fixture's mesh moved by dx along every axis, as a part with material `name`."""
    return (rig.V + np.float32(dx), rig.SI, rig.SW, rig.T, rig.UV, name)


def class_name_record(order, name="ModelRes"):
    """[u32 length][class name NUL] in byte order `order`."""
    raw = name.encode("ascii") + b"\0"
    return struct.pack(order + "I", len(raw)) + raw


def joint_origin(P, k, tb):
    """World position of joint k over the frames of palette P (bind positions tb)."""
    return np.einsum("fab,b->fa", P[:, k, :, :3].astype(np.float64), tb[k]) + P[:, k, :, 3]


def model_named(level, name):
    """The model record called `name` in a level export."""
    return next(r for r in level["models"] if r["name"] == name)


def rotation_angle_deg(R):
    """Rotation angle of a 3x3 rotation matrix, degrees."""
    return float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1))))


def clear_character_caches():
    """Empty the texture, layer, fragment-node and sheet caches of the character
    export (module state of char_lib and characters_export)."""
    import char_lib
    import characters_export as ce

    for c in (char_lib._TEXIDX, char_lib._LAYERCACHE, ce._FRAG_NODES, ce._TEX_SHEETS):
        c.clear()


@pytest.fixture
def character_caches():
    """The character export's caches empty before and after the test."""
    clear_character_caches()
    yield
    clear_character_caches()


@pytest.fixture
def material_caches(monkeypatch):
    """No WATCHMEN_MATERIALS / WATCHMEN_MATERIAL_OPTS, and the character export's
    caches empty before and after the test."""
    monkeypatch.delenv("WATCHMEN_MATERIALS", raising=False)
    monkeypatch.delenv("WATCHMEN_MATERIAL_OPTS", raising=False)
    clear_character_caches()
    yield
    clear_character_caches()
