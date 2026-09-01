"""Regression tests for the 1.2.0 correctness pass (CHANGELOG.md, 2026-08-17).

Every test here pins one fix from that release and was verified to FAIL on the
1.1.0 baseline (b4b869c). No game files, no network, no refactoring seams: each
test drives the real code path with synthetic data built from the layouts the
modules document, monkeypatching only the archive readers (grab_blocks /
extract_block) and the optional rig module where a naz would otherwise be
required.

Sections
--------
  1. extractor: decode_model threads the byte order into decode_skin
  2. watchmenlib.decode_skin forwards `order`
  3. variant_glb.load_parts: BipNN-prefix slot fallback + byte-order autodetect
  4. watchmen_extract.decode_model: engine-exact submesh -> material pairing
  5. kapow_fragment: ImportError (not SystemExit) for a missing key table
  6. watchmen.py: `hash` / `gendata` dispatch before the facade import
  7. kapow_props.parse: truncated propbags degrade, wordcount mismatch warns
  8. skeleton_records: big-endian autodetection
  9. parse_model_nodes.parse_node_aux: honours order='>'
 10. bake_v4: frame count from ALL tracks, not quaternion tracks only
 11. jiggle_d6: resample weight clamped at 1.0 past the sim grid
 12. variant_glb.build: tolerant clip-bank lookup
"""

import pickle
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import bake_v4
import jiggle_d6
import kapow_props as kp
import parse_model_nodes as pmn
import rig_glb
import skeleton_records as sr
import variant_glb as vg
import watchmen_extract as we
from conftest import build_clip_header, build_model_header, synthetic_nodes

try:  # pulls in kapow_fragment, which needs the bundled data tables
    import watchmenlib as wl
except Exception as _ex:  # pragma: no cover - depends on the checkout
    wl, _WL_ERR = None, _ex
else:
    _WL_ERR = None

REPO = Path(__file__).resolve().parent.parent
WLIB = REPO / "wlib"

# ---------------------------------------------------------------------------
# Synthetic skinned ModelRes (header + stream) in either byte order
# ---------------------------------------------------------------------------

#: Console (BE) skinned vertex stride is 44 and PC (LE) is 56 -- find_descriptors
#: maps the same G=6 descriptor to a different stride per byte order, and
#: rig_glb.decode_skin reads the skin channel at a different offset for each.
STRIDE = {"<": 56, ">": 44}


def skinned_model(order, joints, names=None, nv=8, nsub=1, materials=None, piece_mats=None):
    """-> (header, stream) for a skinned model with `nsub` identical submeshes.

    header : synthetic node table (conftest layout) [+ texture path strings
             + per-piece [name][u32 1][u32 matIndex] records] + one geometry
             descriptor per submesh [0][nv][6][0][idxBytes][1].
    stream : per submesh, nv vertices of the platform stride followed by the
             u16 index buffer.  Vertex i is bound 100% to joints[i][0].

    Each descriptor is framed with 0xFF bytes: a lone all-small descriptor
    surrounded by zeros also parses in the OTHER byte order three bytes away
    (`00 00 00 08` reads as LE 8 at p+3), which would make the count-based
    autodetect a coin toss.  Real headers are not zero-padded like that.
    """
    be = order == ">"
    stride = STRIDE[order]
    tris = [(i, i + 1, i + 2) for i in range(nv - 2)]
    ib = len(tris) * 6
    hdr = bytearray(build_model_header(synthetic_nodes(names), order))
    if materials:
        for m in materials:
            raw = ("/textures/%s.dds" % m).encode("ascii") + b"\0"
            hdr += struct.pack(order + "I", len(raw)) + raw
    for k in range(nsub):
        if piece_mats is not None:
            raw = ("Piece%d" % k).encode("ascii") + b"\0"
            hdr += struct.pack(order + "I", len(raw)) + raw
            hdr += struct.pack(order + "2I", 1, piece_mats[k])
        hdr += b"\xff" * 4 + struct.pack(order + "6I", 0, nv, 6, 0, ib, 1) + b"\xff" * 8
    vb = bytearray()
    for i in range(nv):
        rec = bytearray(stride)
        x, y, z = 0.1 + 0.05 * i, 0.2 + 0.07 * (i % 3), 0.3 + 0.11 * (i % 5)
        struct.pack_into(order + "3f", rec, 0, x, y, z)
        j0, j1, j2, j3 = joints[i]
        if be:  # BLENDINDICES D3DCOLOR u32 BE @+32 -> quad = bytes [33,34,35,32]
            rec[32], rec[33], rec[34], rec[35] = j3, j0, j1, j2
            rec[36:44] = struct.pack(">4e", 1.0, 0.0, 0.0, 0.0)
        else:  # PC: D3DCOLOR ubyte4 @+44 read BGRA -> quad = bytes [46,45,44,47]
            rec[44], rec[45], rec[46], rec[47] = j2, j1, j0, j3
            rec[48:56] = struct.pack("<4e", 1.0, 0.0, 0.0, 0.0)
        vb += rec
    ibuf = b"".join(struct.pack(order + "3H", *t) for t in tris)
    return bytes(hdr), (bytes(vb) + ibuf) * nsub


@pytest.mark.parametrize("order", ["<", ">"])
def test_synthetic_model_is_unambiguous_and_carvable(order):
    """Baseline for this file: the synthetic model parses the way a real one does.

    Without this the tests below could pass vacuously (a model that yields no
    descriptors produces no skin calls to inspect).
    """
    joints = [(i % 5, 0, 0, 0) for i in range(8)]
    hdr, stream = skinned_model(order, joints)
    other = ">" if order == "<" else "<"
    assert we.find_descriptors(hdr, order) == [(8, STRIDE[order], 36)]
    assert we.find_descriptors(hdr, other) == []
    assert we._vb_ok(stream, 0, 8, STRIDE[order], 36, order)
    assert we._ib_ok(stream, 0, 8, STRIDE[order], 36, order)
    si, sw = rig_glb.decode_skin(stream, 0, 8, STRIDE[order], order)
    assert si[:, 0].tolist() == [j[0] for j in joints]
    assert np.allclose(sw[:, 0], 1.0)


# ---------------------------------------------------------------------------
# 1. decode_model -> decode_skin(order)
# ---------------------------------------------------------------------------


class _RigStub:
    """Stand-in for rig_glb that records what decode_model hands it.

    decode_skin delegates to the REAL decoder with whatever order it received,
    so a missing/None order reproduces the 1.1.0 behaviour exactly (PC layout,
    stride >= 56 gate).  build_rigged_glb just records its skin arrays.
    """

    def __init__(self):
        self.skin_calls = []
        self.glb_calls = []

    def decode_skin(self, stream, vbo, nv, stride, order=None):
        self.skin_calls.append({"vbo": vbo, "nv": nv, "stride": stride, "order": order})
        return rig_glb.decode_skin(stream, vbo, nv, stride, order or "<")

    def build_rigged_glb(self, glb_path, V, N, U, SI, SW, T, subs, mats, tex, pal, *a, **k):
        self.glb_calls.append({"SI": np.asarray(SI), "SW": np.asarray(SW), "pal": pal})


@pytest.fixture
def rig_stub(monkeypatch):
    stub = _RigStub()
    monkeypatch.setitem(we._RIG, "on", True)
    monkeypatch.setitem(we._RIG, "mod", stub)
    monkeypatch.setitem(we._RIG, "loaded", True)
    return stub


@pytest.mark.parametrize("order", ["<", ">"])
def test_decode_model_passes_detected_byte_order_to_decode_skin(tmp_path, rig_stub, order):
    """decode_skin must receive the byte order decode_model auto-detected.

    1.1.0 called `decode_skin(stream, vbo, nv, stride)` -- no order -- so the
    console (stride-44) skinned submesh hit the PC `stride >= 56` gate and
    `--glb` on an X360/PS3 naz silently produced no skinned GLB at all.
    """
    joints = [(i % 5, 0, 0, 0) for i in range(8)]
    hdr, stream = skinned_model(order, joints)
    assert we.decode_model(hdr, stream, tmp_path / "m.obj") is True
    assert len(rig_stub.skin_calls) == 1, "one skinned submesh -> one decode_skin call"
    call = rig_stub.skin_calls[0]
    assert call["order"] == order
    assert call["stride"] == STRIDE[order]


def test_console_model_yields_a_skinned_glb(tmp_path, rig_stub):
    """End-to-end: a big-endian skinned model reaches build_rigged_glb with its skin.

    This is the user-visible symptom: with the order dropped, decode_skin
    returns (None, None) for stride 44, `have_skin` flips off and no glb is
    ever built.  The joint indices must also be the ones written into the
    vertex records (BE D3DCOLOR quad), not a byte-swapped reading.
    """
    joints = [((i * 3) % 5, 0, 0, 0) for i in range(8)]
    hdr, stream = skinned_model(">", joints)
    assert we.decode_model(hdr, stream, tmp_path / "m.obj") is True
    assert len(rig_stub.glb_calls) == 1, "console skinned model must produce a glb"
    SI = rig_stub.glb_calls[0]["SI"]
    assert SI.shape == (8, 4)
    assert SI[:, 0].tolist() == [j[0] for j in joints]
    assert np.allclose(rig_stub.glb_calls[0]["SW"][:, 0], 1.0)


# ---------------------------------------------------------------------------
# 2. watchmenlib.decode_skin forwards `order`
# ---------------------------------------------------------------------------


@pytest.mark.skipif(wl is None, reason="watchmenlib unavailable: %s" % (_WL_ERR,))
def test_facade_decode_skin_forwards_order():
    """wl.decode_skin(stream, vbo, nv, stride, order) must reach rig_glb intact.

    The 1.1.0 wrapper had no `order` parameter, so facade callers could not
    decode a console skin at all (TypeError on the fifth argument).
    """
    joints = [(i % 5, 1, 2, 3) for i in range(8)]
    _hdr, stream = skinned_model(">", joints)
    si, sw = wl.decode_skin(stream, 0, 8, 44, ">")
    assert si is not None, "BE stride-44 skin must decode through the facade"
    assert si[:, 0].tolist() == [j[0] for j in joints]
    assert np.allclose(sw[:, 0], 1.0)


@pytest.mark.skipif(wl is None, reason="watchmenlib unavailable: %s" % (_WL_ERR,))
def test_facade_decode_skin_passes_order_through_verbatim(monkeypatch):
    """The wrapper passes `order` on unchanged -- and defaults to PC ('<')."""
    seen = []

    def fake(stream, vbo, nv, stride, order="<"):
        seen.append(order)
        return None, None

    monkeypatch.setattr(wl._rig, "decode_skin", fake)
    wl.decode_skin(b"", 0, 0, 44, ">")
    wl.decode_skin(b"", 0, 0, 56)
    assert seen == [">", "<"]


# ---------------------------------------------------------------------------
# 3. variant_glb.load_parts -- BipNN-prefix slot fallback + byte order
# ---------------------------------------------------------------------------

#: bind palette (what the skeleton/bind calls the bones)
PALETTE = ["Bip01", "Bip01 Pelvis", "Bip02 RUpArmTwist", "Bip01 Head", "Neck"]
#: mesh node table (what the part mesh calls them): exact matches, a bare name
#: for a prefixed palette bone, a prefixed name for a bare palette bone, and
#: two bones the palette does not have at all.
MESH_NODES = [
    "GamePivot",
    "Bip01",
    "Bip01 Pelvis",
    "RUpArmTwist",  # palette: 'Bip02 RUpArmTwist'
    "Bip01 Head",
    "Bip01 Neck",  # palette: 'Neck'
    "Dummy01",
]
#: engine palette after rotate-by-one over the RESOLVABLE mesh bones
#: pf   = [Bip01, Pelvis, RUpArmTwist, Head, Bip01 Neck]
#: ppal = [Bip01 Neck, Bip01, Pelvis, RUpArmTwist, Head] -> slots [4,0,1,2,3]
EXPECTED_REMAP = [4, 0, 1, 2, 3]


class _Entry:
    def __init__(self, name):
        self.name = name


def _run_load_parts(monkeypatch, order, joints):
    hdr, stream = skinned_model(order, joints, names=MESH_NODES)
    monkeypatch.setattr(vg.efa, "grab_blocks", lambda naz: {"blk": {"h": b"H", "s": b"S"}})
    monkeypatch.setattr(
        we, "extract_block", lambda h, s: iter([(_Entry("/x/Body.model"), hdr, stream)])
    )
    return vg.load_parts(["Body"], PALETTE, naz="does-not-exist.naz")


def test_load_parts_resolves_bip_prefix_mismatches_in_both_directions(monkeypatch):
    """A mesh bone that differs from its palette bone only by a 'BipNN ' prefix
    must land in that palette slot -- bare->prefixed AND prefixed->bare.

    1.1.0 used an exact-name set, so 'RUpArmTwist' (mesh) never matched
    'Bip02 RUpArmTwist' (bind) and was silently dropped from the mid-list;
    every bone after it shifted one slot in the rotate-by-one palette and the
    skin pointed at the wrong joints (mis-skinned arms/head on Thug/Heavies).
    """
    joints = [(i % 5, 0, 0, 0) for i in range(8)]
    parts = _run_load_parts(monkeypatch, "<", joints)
    assert len(parts) == 1
    SI = parts[0][1]
    assert SI[:, 0].tolist() == [EXPECTED_REMAP[i % 5] for i in range(8)]
    # vertex bound to mesh index 3 must skin to 'Bip02 RUpArmTwist' (slot 2),
    # and mesh index 0 to 'Neck' via 'Bip01 Neck' (slot 4)
    assert PALETTE[SI[3, 0]] == "Bip02 RUpArmTwist"
    assert PALETTE[SI[0, 0]] == "Neck"


def test_load_parts_drops_only_truly_unknown_bones(monkeypatch):
    """Bones the palette really lacks ('GamePivot', 'Dummy01') take no slot.

    The fallback must not become a free-for-all: an unknown name resolves to
    None and is excluded from the rotate-by-one list, so the five resolvable
    mesh bones (of seven) fill exactly the five palette slots -- every slot
    reached, none reached from an unknown name.
    """
    joints = [(i % 5, 0, 0, 0) for i in range(8)]
    hdr, _ = skinned_model("<", joints, names=MESH_NODES)
    assert len(pmn.parse(hdr)[0]) - 1 == len(MESH_NODES), "mesh table really has 7 named nodes"
    parts = _run_load_parts(monkeypatch, "<", joints)
    SI = parts[0][1]
    assert set(SI[:, 0].tolist()) == set(range(len(PALETTE)))
    assert SI.max() < len(PALETTE)


def test_load_parts_autodetects_big_endian_models(monkeypatch):
    """A console (BE) part must decode to the same skin as its PC twin.

    load_parts was hardcoded little-endian in 1.1.0: on a BE header
    find_descriptors('<') finds nothing, so the part silently vanished.
    """
    joints = [(i % 5, 0, 0, 0) for i in range(8)]
    le = _run_load_parts(monkeypatch, "<", joints)
    be = _run_load_parts(monkeypatch, ">", joints)
    assert len(be) == 1, "big-endian part was dropped"
    assert be[0][1].tolist() == le[0][1].tolist()
    assert np.allclose(be[0][0], le[0][0], atol=1e-6), "positions differ between byte orders"
    assert be[0][3].tolist() == le[0][3].tolist(), "triangles differ between byte orders"


# ---------------------------------------------------------------------------
# 4. decode_model: submesh -> material pairing from the header records
# ---------------------------------------------------------------------------


def test_decode_model_pairs_materials_by_record_not_position(tmp_path):
    """Two submeshes whose piece records BOTH point at material 1 must both use it.

    Positional pairing (1.1.0) handed submesh k the k-th texture, which is
    wrong whenever one material covers several submeshes (Rorschach's
    trenchcoat); the extractor's OBJ path now reads each piece's own
    materialIndex like char_lib does.
    """
    joints = [(0, 0, 0, 0)] * 8
    hdr, stream = skinned_model(
        "<", joints, nsub=2, materials=["coat_a", "coat_b"], piece_mats=[1, 1]
    )
    assert we.extract_materials(hdr) == ["coat_a", "coat_b"]
    assert we.submesh_materials(hdr, "<") == [("Piece0", 1), ("Piece1", 1)]
    out = tmp_path / "m.obj"
    assert we.decode_model(hdr, stream, out) is True
    usemtl = [ln.split()[1] for ln in out.read_text().splitlines() if ln.startswith("usemtl ")]
    assert usemtl == ["coat_b", "coat_b"]


# ---------------------------------------------------------------------------
# 5. kapow_fragment: ImportError, not SystemExit
# ---------------------------------------------------------------------------


def _checkout_without_key_table(tmp_path):
    """A copy of watchmen.py + wlib/*.py with NO data tables (no .pkl/.json)."""
    root = tmp_path / "nopkl"
    (root / "wlib").mkdir(parents=True)
    shutil.copy(REPO / "watchmen.py", root / "watchmen.py")
    for p in WLIB.glob("*.py"):
        shutil.copy(p, root / "wlib" / p.name)
    assert not (root / "wlib" / "kapow_fragment_keys.pkl").exists()
    return root


def _run(args, cwd, code=None):
    cmd = [sys.executable] + (["-c", code] if code else args)
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=120)


def test_missing_key_table_raises_import_error_not_system_exit(tmp_path):
    """`import kapow_fragment` without its .pkl must raise ImportError.

    1.1.0 raised SystemExit at import time.  SystemExit is a BaseException, so
    it escaped every `except Exception` guard: pytest collection died with zero
    tests run and `import watchmenlib` could kill a host process outright.
    The message must still name the documented recovery command.
    """
    root = _checkout_without_key_table(tmp_path)
    code = (
        "import sys; sys.path.insert(0, 'wlib')\n"
        "try:\n"
        "    import kapow_fragment\n"
        "except BaseException as ex:\n"
        "    print(type(ex).__name__); print(isinstance(ex, Exception)); print(str(ex))\n"
        "else:\n"
        "    print('NO-ERROR')\n"
    )
    r = _run(None, root, code)
    lines = r.stdout.splitlines()
    assert r.returncode == 0, r.stderr
    assert lines[0] == "ImportError", "got %s" % lines[0]
    assert lines[1] == "True", "must be catchable by `except Exception`"
    assert "gendata keys-import" in r.stdout


def test_cli_reports_a_missing_key_table_as_an_error_line(tmp_path):
    """A facade-using command on a checkout without the table exits 2 with `error:`.

    cli() catches ImportError since 1.2.0 (exit code 2, one actionable line);
    before, the SystemExit propagated with exit code 1 and no `error:` prefix.
    """
    root = _checkout_without_key_table(tmp_path)
    r = _run(["watchmen.py", "fragment", "nothing.fragment"], root)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert r.stderr.lstrip().startswith("error:"), r.stderr
    assert "gendata keys-import" in r.stderr


# ---------------------------------------------------------------------------
# 6. watchmen.py: hash / gendata dispatch before the facade import
# ---------------------------------------------------------------------------


def test_hash_command_does_not_import_the_facade():
    """`watchmen hash NAME` must not import numpy / Pillow / watchmenlib.

    Checked in a subprocess by inspecting sys.modules after main() returns.
    In 1.1.0 `hash` was dispatched after `_wl()`, paying the full facade import
    (and failing when any data table was missing).
    """
    code = (
        "import sys, importlib.util\n"
        "spec = importlib.util.spec_from_file_location('watchmen_cli', 'watchmen.py')\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "rc = m.main(['watchmen.py', 'hash', 'POSITION'])\n"
        "heavy = sorted(x for x in sys.modules if x.split('.')[0] in "
        "('numpy', 'PIL', 'watchmenlib', 'kapow_fragment', 'watchmen_extract'))\n"
        "print('RC', rc); print('HEAVY', ' '.join(heavy))\n"
    )
    r = _run(None, REPO, code)
    assert r.returncode == 0, r.stderr
    out = dict(ln.split(" ", 1) if " " in ln else (ln, "") for ln in r.stdout.splitlines())
    assert out["RC"] == "0"
    assert out["HEAVY"] == "", "facade modules were imported: %s" % out["HEAVY"]


@pytest.mark.parametrize("name", ["POSITION", "position", "Position"])
def test_hash_command_prints_the_uppercase_kapow_hash(name):
    """Output == '%08x' % kapow_hash(NAME.upper()), whatever the input case.

    The engine hashes UPPERCASE names; the old path went through
    wl.kapow_hash (which uppercases) and the new direct path must keep that.
    """
    r = _run(["watchmen.py", "hash", name], REPO)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "%08x" % kp.kapow_hash("POSITION")
    assert r.stdout.strip() == "15de4806"


def test_hash_and_gendata_work_without_the_key_table(tmp_path):
    """`gendata keys-import` -- the documented recovery for a missing
    kapow_fragment_keys.pkl -- must run when that very file is absent.

    In 1.1.0 both `hash` and `gendata` were dispatched after the facade
    import, so the recovery command died on the exact error it exists to fix.
    """
    root = _checkout_without_key_table(tmp_path)
    r = _run(["watchmen.py", "hash", "position"], root)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "15de4806"

    keys = tmp_path / "keys.json"
    keys.write_text(
        '{"keytable": {"0000000a": ["foo", "number"]}, "stdkeys": {"0000000b": "bar"},'
        ' "promoted": {}, "nameable": {}}'
    )
    out = tmp_path / "rebuilt.pkl"
    r = _run(["watchmen.py", "gendata", "keys-import", str(keys), "-o", str(out)], root)
    assert r.returncode == 0, (r.stdout, r.stderr)
    with open(out, "rb") as fh:
        kd = pickle.load(fh)
    assert kd["keytable"] == {10: ("foo", "number")}
    assert kd["stdkeys"] == {11: "bar"}


# ---------------------------------------------------------------------------
# 7. kapow_props.parse: truncation and wordcount warnings
# ---------------------------------------------------------------------------

PROP_KEYS = ("GRAVITY", "NAME", "POSITION", "COUNT")
KEYNAMES = {kp.kapow_hash(k): k for k in PROP_KEYS}


def _propbag(string_words=2, string_k=None):
    """A minimal LE property bag (kapow_props module docstring layout).

    [u32 namelen][ClassName\\0][u32 schemaCount] then records
    [u32 owner][u32 keyHash][u32 typeHash][u32 k][k dwords].
    Returns (bytes, {key: payload offset}).
    """
    H = kp.kapow_hash
    b = bytearray()
    cls = b"Particle\0"
    b += struct.pack("<I", len(cls)) + cls + struct.pack("<I", 3)
    owner = 0x1234
    offs = {}

    def rec(key, typ, payload, k=None):
        if k is not None:  # a k that overstates the payload: pad so later records stay aligned
            payload = payload + [b"\0\0\0\0"] * (k - len(payload))
        offs[key] = len(b) + 16
        b.extend(struct.pack("<4I", owner, H(key), H(typ.upper()), len(payload)))
        for dw in payload:
            b.extend(dw)

    rec("GRAVITY", "number", [struct.pack("<f", 9.5)])
    s = b"hello".ljust(4 * string_words, b"\0")
    rec(
        "NAME",
        "string",
        [struct.pack("<I", string_words)] + [s[i : i + 4] for i in range(0, len(s), 4)],
        k=string_k,
    )
    rec("POSITION", "vector", [struct.pack("<f", v) for v in (1.0, 2.0, 3.0)])
    rec("COUNT", "integer", [struct.pack("<i", 7)])
    return bytes(b), offs


def test_propbag_reference_parses_completely():
    """Baseline: the synthetic bag decodes every record with no warning."""
    b, _ = _propbag()
    out = kp.parse(b, keynames=KEYNAMES)
    assert "warn" not in out
    (blk,) = out["blocks"]
    assert blk["class"] == "Particle" and blk["schema"] == 3
    assert [(p["key"], p["type"]) for p in blk["props"]] == [
        ("GRAVITY", "number"),
        ("NAME", "string"),
        ("POSITION", "vector"),
        ("COUNT", "integer"),
    ]
    assert blk["props"][0]["value"] == pytest.approx(9.5)
    assert blk["props"][1]["value"] == "hello"
    assert blk["props"][2]["value"]["floats"] == [1.0, 2.0, 3.0]
    assert blk["props"][3]["value"] == 7
    assert out["trailing_bytes"] == 0


@pytest.mark.parametrize(
    "where,delta,kept",
    [
        ("schema", 0, 0),  # cut right after the class name, before schemaCount
        ("GRAVITY", 2, 0),  # inside the number payload
        ("NAME", 2, 1),  # inside the string wordcount dword
        ("NAME", 6, 1),  # inside the string characters
        ("POSITION", 5, 2),  # inside the vector payload
        ("COUNT", 1, 3),  # inside the integer payload
    ],
)
def test_truncated_propbag_returns_partial_output_with_a_warning(where, delta, kept):
    """A payload running past the buffer yields the records before it plus
    out['warn'] -- never struct.error.

    Property bags are carved heuristically, so short reads are routine; in
    1.1.0 the struct.error escaped into the caller's whole extraction pass.
    """
    b, offs = _propbag()
    cut = (13 if where == "schema" else offs[where]) + delta
    out = kp.parse(b[:cut], keynames=KEYNAMES)
    assert isinstance(out, dict)
    assert any("truncated" in w for w in out.get("warn", [])), out
    props = out["blocks"][0]["props"] if out["blocks"] else []
    assert [p["key"] for p in props] == list(PROP_KEYS[:kept])
    for p in props:  # what survived is intact, not garbage
        assert p["value"] is not None


def test_string_wordcount_mismatch_is_reported():
    """A string record whose wordcount disagrees with k must surface in out['warn'].

    The check existed in 1.1.0 but its body was `pass`; the value still parses
    (it always did) and now the disagreement is counted and reported.
    """
    b, _ = _propbag(string_words=2, string_k=4)  # k should be 3 (= 1 + wordcount)
    out = kp.parse(b, keynames=KEYNAMES)
    assert any("wordcount" in w for w in out.get("warn", [])), out
    assert not any("truncated" in w for w in out["warn"]), "nothing was cut short"
    props = out["blocks"][0]["props"]
    assert [p["key"] for p in props] == list(PROP_KEYS), "records after the string stay aligned"
    assert props[1]["value"] == "hello"


# ---------------------------------------------------------------------------
# 8. skeleton_records: big-endian autodetection
# ---------------------------------------------------------------------------


def _records_view(recs):
    return [
        (r["name"], r["parent"], [(p.tolist(), q.tolist()) for _o, p, q in r["entries"]])
        for r in recs
    ]


def test_skeleton_records_autodetects_big_endian():
    """The same skeleton stored BE must parse identically to its LE twin.

    skeleton_records was LE-only in 1.1.0, so a console header yielded no
    (or garbage) records for every facade caller of wl.skeleton_records.
    """
    nodes = synthetic_nodes()
    le_h = build_model_header(nodes, "<")
    be_h = build_model_header(nodes, ">")
    le = sr.parse(le_h)
    be = sr.parse(be_h)
    assert [r["name"] for r in le] == [n[0] for n in nodes[1:]], "LE reference must decode"
    assert [r["name"] for r in be] == [r["name"] for r in le], "BE header did not decode"
    assert [r["parent"] for r in be] == [r["parent"] for r in le]
    lv, bv = _records_view(le), _records_view(be)
    assert sum(len(e) for _n, _p, e in lv) > 0, "LE reference must find transform entries"
    for (ln, lp, le_ents), (bn, bp, be_ents) in zip(lv, bv):
        assert len(le_ents) == len(be_ents), "entry count differs on %s" % ln
        for (lpos, lq), (bpos, bq) in zip(le_ents, be_ents):
            assert np.allclose(lpos, bpos, atol=1e-6)
            assert np.allclose(lq, bq, atol=1e-6)
    # and the detector itself picks the right order for each
    assert sr._detect_order(le_h) == "<"
    assert sr._detect_order(be_h) == ">"


def test_skeleton_records_explicit_order_matches_autodetect():
    """parse(h, order='>') and parse(h) agree on a BE header."""
    be_h = build_model_header(synthetic_nodes(), ">")
    assert _records_view(sr.parse(be_h, order=">")) == _records_view(sr.parse(be_h))


# ---------------------------------------------------------------------------
# 9. parse_node_aux honours order
# ---------------------------------------------------------------------------

AUX_JOINTS = [
    (7, (0.1, 0.2, 0.3), (1.5, 2.5), (0.0, 0.0, 0.0, 1.0), b""),
    (6, (0.4, 0.5, 0.6), (0.25, 0.75), (0.0, 0.6, 0.0, 0.8), b"abcdefg"),
]


def _aux_region(order, parent=3, c34=2, joints=AUX_JOINTS):
    """One node aux region, per the layout documented above parse_node_aux:
    [f1][parent][cnt34][cnt34 x u32 0][cnt40=0][u8 0][njoint]
    per joint [type][0][pos x3][a][a'][quat x4][blobLen][blob]  [0][0]."""
    b = bytearray()
    b += struct.pack(order + "3I", 0, parent, c34)
    b += struct.pack(order + "%dI" % c34, *([0] * c34))
    b += struct.pack(order + "I", 0) + b"\0"
    b += struct.pack(order + "I", len(joints))
    for t, pos, (a, a2), q, blob in joints:
        b += struct.pack(order + "2I", t, 0)
        b += struct.pack(order + "3f", *pos) + struct.pack(order + "2f", a, a2)
        b += struct.pack(order + "4f", *q) + struct.pack(order + "I", len(blob)) + blob
    b += struct.pack(order + "2I", 0, 0)
    return bytes(b)


def _check_aux(r):
    assert r is not None
    assert r["parent"] == 3
    assert len(r["joints"]) == len(AUX_JOINTS)
    for j, (t, pos, (a, a2), q, blob) in zip(r["joints"], AUX_JOINTS):
        assert j["type"] == t
        assert np.allclose(j["pos"], pos, atol=1e-6)
        assert j["a"] == pytest.approx(a) and j["a2"] == pytest.approx(a2)
        assert np.allclose(j["quat"], q, atol=1e-6)
        assert j["blob"] == blob


@pytest.mark.parametrize("order", ["<", ">"])
def test_parse_node_aux_honours_byte_order(order):
    """parse_node_aux(mb, start, end, order) decodes a region in either byte order.

    The reads were hardcoded '<' in 1.1.0 (no `order` parameter at all), so
    console EmbeddedJointNode records could not be decoded.
    """
    region = _aux_region(order)
    mb = b"\xaa" * 7 + region + b"\xbb" * 5
    _check_aux(pmn.parse_node_aux(mb, 7, 7 + len(region), order))


def test_parse_node_aux_default_order_is_still_little_endian():
    """The default (no `order`) keeps the previous PC behaviour and does not
    misread a BE region as valid joints."""
    le = _aux_region("<")
    _check_aux(pmn.parse_node_aux(le, 0, len(le)))
    be = _aux_region(">")
    assert pmn.parse_node_aux(be, 0, len(be)) is None
    assert pmn.parse_node_aux(be, 0, len(be), "<") is None


# ---------------------------------------------------------------------------
# 10. bake_v4: frame count from all tracks
# ---------------------------------------------------------------------------


def _clip_bytes(pos_keys, quat_keys):
    """A minimal .animation clip bake_v4.walk() decodes:
    [hdr 20][u32 nexp=2]['Root\\0']['Child\\0']
    Root  : type 0 = const quat (f32 x4) + pos keys (3 x i16 / 1000)
    Child : type 1 = const pos (f32 x3) + quat keys (4 x i16 / 10000)"""
    b = bytearray(build_clip_header(max(len(pos_keys), len(quat_keys)), 1.0))
    b += struct.pack("<I", 2)
    for nm in (b"Root\0", b"Child\0"):
        b += struct.pack("<I", len(nm)) + nm
    b += bytes([0]) + struct.pack("<H", len(pos_keys)) + struct.pack("<4f", 0, 0, 0, 1)
    for p in pos_keys:
        b += struct.pack("<3h", *[int(round(v * 1000)) for v in p])
    b += bytes([1]) + struct.pack("<H", len(quat_keys)) + struct.pack("<3f", 0, 1, 0)
    for q in quat_keys:
        b += struct.pack("<4h", *[int(round(v * 10000)) for v in q])
    return bytes(b)


@pytest.fixture
def two_bone_bind(tmp_path):
    p = tmp_path / "bind_two_file_v1.npz"
    np.savez(
        p,
        Rb=np.tile(np.eye(3), (2, 1, 1)),
        tb=np.array([[0, 0, 0], [0, 1, 0]], float),
        tloc=np.array([[0, 0, 0], [0, 1, 0]], float),
        par=np.array([-1, 0]),
        names=np.array(["Root", "Child"]),
    )
    return p


def test_bake_frame_count_comes_from_the_longest_track_of_any_kind(two_bone_bind):
    """A clip whose longest track is POSITIONAL keeps every position key.

    1.1.0 took `nf = max(len(quat_track))`: a type-0 root track (constant
    quaternion, 5 position keys) contributed 1, so nf came from the 2-key
    child rotation and the 5 root position keys were down-sampled to 2 --
    worst case (all-constant rotations) a clip collapsed to a single frame.
    """
    pos_keys = [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)]
    clip = _clip_bytes(pos_keys, [(0, 0, 0, 1), (0, 0, 0, 1)])
    tr = bake_v4.walk(clip)
    assert len(tr["Root"][0]) == 1 and len(tr["Root"][1]) == 5, "reference clip decodes as intended"
    assert len(tr["Child"][0]) == 2

    pal, dur = bake_v4.bake(
        "synthetic", upsample=2, bind=str(two_bone_bind), bank={"synthetic": clip}
    )
    assert dur == pytest.approx(1.0)
    assert pal.shape[0] == (5 - 1) * 2 + 1, "5 position keys x upsample 2 -> 9 frames"
    # root translation column: the 5 keys, linearly upsampled, none skipped
    assert np.allclose(pal[:, 0, 0, 3], np.linspace(0.0, 4.0, 9), atol=1e-6)
    assert np.allclose(pal[:, 0, 1:, 3], 0.0, atol=1e-6)


# ---------------------------------------------------------------------------
# 11. jiggle_d6: resample weight clamp
# ---------------------------------------------------------------------------


def _rotvec(R):
    a = float(np.arccos(np.clip((np.trace(R) - 1.0) / 2.0, -1.0, 1.0)))
    if a < 1e-12:
        return np.zeros(3)
    return a * np.array([R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1]]) / (2 * np.sin(a))


def test_jiggle_resample_never_extrapolates_past_the_last_sim_sample(tmp_path):
    """Frames beyond the last sim sample all carry x[N-1] -- weight clamped at 1.

    A 240 fps clip on the 60 Hz sim grid has 4 clip frames per sim step; the
    last four land at sim time >= N-1, where the index is clamped to N-2 but
    the 1.1.0 weight was not (w = 1.0, 1.25, 1.5, 1.75), so those frames
    extrapolated past the final sample and could overshoot the engine
    distance clamp.  With the clamp the four tail frames are identical.
    """
    bind = tmp_path / "bind_female_file_v1.npz"
    np.savez(
        bind,
        Rb=np.tile(np.eye(3), (2, 1, 1)),
        tb=np.array([[0.0, 0.0, 0.0], [0.1, 0.0, 0.05]]),  # lever arm not parallel to gravity
        names=np.array(["Root", "BreastL"]),
        par=np.array([-1, 0]),
    )
    F, fps, hz = 40, 240.0, 60
    props = dict(jiggle_d6._FILE_DEFAULTS)
    props["rate_hz"] = hz
    P = np.zeros((F, 2, 3, 4), np.float32)
    P[:, :, :, :3] = np.eye(3)  # static parent -> constant gravity torque drives the sim
    out = jiggle_d6.apply_jiggle(P, fps, str(bind), props=props)
    assert out.shape == P.shape
    dev = [_rotvec(out[i, 1, :, :3].astype(np.float64) @ P[i, 1, :, :3].T) for i in range(F)]
    N = int(round(F / fps * hz))
    tail = [i for i in range(F) if (i / fps) * hz >= N - 1 - 1e-9]
    assert len(tail) == 4, tail
    # the sim really moved (the tail assertion is not satisfied by a zero deviation)
    assert np.linalg.norm(dev[tail[0]]) > 1e-4
    assert (
        np.linalg.norm(dev[tail[0]] - dev[tail[0] - 4]) > 1e-5
    ), "deviation must vary frame to frame"
    for i in tail[1:]:
        assert np.allclose(dev[i], dev[tail[0]], atol=1e-6), "frame %d extrapolated past x[N-1]" % i


# ---------------------------------------------------------------------------
# 12. variant_glb.build: tolerant clip-bank lookup
# ---------------------------------------------------------------------------


def test_build_finds_clip_headers_under_bare_suffixed_and_path_keys(tmp_path, monkeypatch):
    """bank keys '<clip>.animation', '<clip>' and stripped '<clip>' all resolve,
    and a str value is read as a header path -- every clip gets header-exact fps.

    bake_v4 banks key by BARE clip name; build()'s 1.1.0 lookup only tried
    '<clip>.animation', so a bare-keyed bank missed every clip and silently
    fell back to 30 fps (2x slow on FULL-rate clips).
    """
    frag = tmp_path / "X.fragment.json"
    frag.write_text(
        '{"instances": [{"name": "V", "model_ref": ["/a/Skel_Skeleton.model", "/a/Body.model"]}]}'
    )
    bind = tmp_path / "bind_skel_file_v1.npz"
    np.savez(
        bind, Rb=np.tile(np.eye(3), (2, 1, 1)), tb=np.zeros((2, 3)), names=np.array(["A", "B"])
    )
    bakedir = tmp_path / "bake"
    bakedir.mkdir()
    A = np.zeros((31, 2, 3, 4), np.float32)
    A[:, :, :, :3] = np.eye(3)
    for nm in ("EN4_suffixed", "EN4_bare", "EN4_stripped ", "EN4_path", "EN4_absent"):
        np.save(bakedir / (nm + ".npy"), A)
    hdr = build_clip_header(31, 2.0)  # 30 keys over 2 s -> 15 fps
    hdr_path = tmp_path / "EN4_path.hdr"
    hdr_path.write_bytes(hdr)
    bank = {
        "EN4_suffixed.animation": hdr,
        "EN4_bare": hdr,
        "EN4_stripped": hdr,
        "EN4_path": str(hdr_path),
    }
    captured = {}
    monkeypatch.setattr(vg, "load_parts", lambda meshes, pal, naz="01_game.naz": [])
    monkeypatch.setattr(
        vg, "write_glb", lambda parts, manifest, out, bindp, **k: captured.update(manifest=manifest)
    )
    vg.build(
        str(frag), "V", str(tmp_path / "o.glb"), bakedir=str(bakedir), bank=bank, bind=str(bind)
    )
    fps = {nm: f for nm, _a, f in captured["manifest"]}
    assert set(fps) == {"EN4_suffixed", "EN4_bare", "EN4_stripped ", "EN4_path", "EN4_absent"}
    for nm in ("EN4_suffixed", "EN4_bare", "EN4_stripped ", "EN4_path"):
        assert fps[nm] == pytest.approx(15.0), "%r fell back to the 30 fps default" % nm
    assert fps["EN4_absent"] == pytest.approx(30.0), "a clip the bank lacks keeps the fallback"
