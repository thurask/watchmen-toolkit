"""The Khronos glTF validator over the GLBs the toolkit writes (opt-in).

Runs only when $WATCHMEN_GLTF_VALIDATOR names the validator: a folder whose
node_modules holds the npm package `gltf-validator` (`npm install
gltf-validator` there), or that package's own folder; `node` must be on PATH.
Without the variable conftest.py deselects these tests (they are not counted as
skipped).  tests/data/gltf_validate.js runs the validator.

Writes one GLB of every writer: character GLBs (hierarchy and flat rig, the
mirrored frame, a face rig, outfit nodes), `extract --glb` (a skinned body and a
static model with vertex attributes), the navigation mesh and a terrain
surface.  Every file must have 0 errors and no warning outside ALLOWED.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "data" / "gltf_validate.js"

#: warnings a correct file of these writers can carry, and why
ALLOWED = {
    # a normal-mapped material on a primitive without TANGENT: the viewer derives
    # the tangent frame (glTF 2.0 3.7.2.1); written so by --no-vertex-attrs and by
    # pieces whose header does not locate the tangent buffer
    "MESH_PRIMITIVE_GENERATED_TANGENT_SPACE",
}


def _validator():
    v = os.environ.get("WATCHMEN_GLTF_VALIDATOR")
    node = shutil.which("node")
    assert node, "WATCHMEN_GLTF_VALIDATOR is set but `node` is not on PATH"
    assert v and os.path.exists(v), "WATCHMEN_GLTF_VALIDATOR=%r does not exist" % v
    return node, v


def _validate(files, tmp_path):
    node, pkg = _validator()
    lst = tmp_path / "glbs.txt"
    lst.write_text("\n".join(str(f) for f in files) + "\n")
    out = tmp_path / "report.json"
    r = subprocess.run(
        [node, str(RUNNER), pkg, str(lst), str(out)], capture_output=True, text=True, timeout=600
    )
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def _write_all(tmp_path, monkeypatch, rig):
    import nav_data as nd
    import terrain_asset as ta
    import variant_glb as vg
    import watchmen

    import test_face_rule as tfr
    import test_nav_data as tn
    import test_outfits_integration as toi
    import test_p3_raw_formats as trf
    import test_v150_e2e as te

    out = tmp_path / "glb"
    out.mkdir()
    files = []

    def char(name, **kw):
        p = out / name
        vg.write_glb(rig.parts, rig.manifest, str(p), str(rig.bind_npz), **kw)
        files.append(p)

    char("char_hierarchy.glb")
    char("char_face.glb", face=tfr.face_rig(tmp_path, rig))
    char(
        "char_outfits.glb",
        outfit_parts=[
            ("OUTFIT 1 Jacket", [toi._part(rig, 1.0, "outfit")], True),
            ("OUTFIT 2 Jacket", [toi._part(rig, 1.0, "outfit_3")], False),
        ],
        parts_record={
            "mode": "game",
            "alternatives": [{"node": "OUTFIT 2 Jacket"}],
            "weapons": {"shown": []},
        },
    )
    with monkeypatch.context() as m:
        m.setenv("WATCHMEN_RIG", "flat")
        char("char_flat.glb")
    with monkeypatch.context() as m:
        m.setenv("WATCHMEN_FRAME", "mirrored")
        char("char_mirrored.glb")
    # extract --glb: a skinned body and a static model with vertex attributes
    naz, _pcm, _pk = te._archive(tmp_path)
    ex = tmp_path / "ex"
    assert watchmen.main(["w", "extract", str(naz), str(ex), "--glb", "--quiet"]) == 0
    files += sorted((ex / "models").rglob("*.glb"))
    # navigation mesh
    p = out / "nav.glb"
    p.write_bytes(nd.build_glb(nd.parse_hpd(tn.demo_hpd()), "Demo"))
    files.append(p)
    # terrain surface
    doc = ta.to_json(ta.build(trf._terrain_doc()), stream=trf._terrain_stream())
    ta.write_outputs(doc, str(out / "terrain.terrain"), glb=True)
    files += sorted(out.glob("terrain*.glb"))
    return files


def _outside_the_scene(path, pointer):
    """Is node `pointer` ("/nodes/<k>") outside every scene (under `alternatives`
    or `ragdoll`: the hidden outfit and weapon nodes)?"""
    from conftest import parse_glb

    j = parse_glb(path).j
    k = int(pointer.rsplit("/", 1)[1])
    seen, todo = set(), [n for sc in j.get("scenes", []) for n in sc.get("nodes", [])]
    while todo:
        n = todo.pop()
        seen.add(n)
        todo += j["nodes"][n].get("children", [])
    return k not in seen


def _flat(path):
    from conftest import parse_glb

    w = parse_glb(path).j["asset"].get("extras", {}).get("watchmen", {})
    return (w.get("rig") or {}).get("mode") == "flat"


def test_every_writer_validates(tmp_path, monkeypatch, rig):
    files = _write_all(tmp_path, monkeypatch, rig)
    names = sorted(Path(f).name for f in files)
    assert len(names) == 9, names
    report = _validate(files, tmp_path)
    bad, hidden, flat = [], [], []
    for rec in report:
        name = Path(rec["file"]).name
        if "crash" in rec:
            bad.append((name, "validator crash", rec["crash"]))
            continue
        for sev, code, ptr, msg in rec["issues"]:
            if (
                sev == 1
                and code == "NODE_SKINNED_MESH_NON_ROOT"
                and _outside_the_scene(rec["file"], ptr)
            ):
                # a hidden alternative (outfit / weapon) kept under `alternatives`, outside
                # the scene: no viewer draws it, Blender imports it switched off
                hidden.append((name, ptr))
            elif sev == 1 and code == "NODE_SKINNED_MESH_NON_ROOT" and _flat(rec["file"]):
                # --rig flat writes the 1.4.0 layout on purpose: the mesh under `root`
                flat.append((name, ptr))
            elif sev == 0 or (sev == 1 and code not in ALLOWED):
                bad.append((name, code, ptr, msg))
    assert bad == [], "\n".join(map(str, bad))
    assert hidden == [("char_outfits.glb", "/nodes/7")]
    assert [n for n, _p in flat] == ["char_flat.glb"]


def test_the_runner_reports_an_error(tmp_path):
    """The check can fail: a GLB whose accessor points past its buffer view."""
    import variant_glb as vg  # noqa: F401  (wlib on sys.path)
    import wutil

    doc = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": 4}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 4}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    p = tmp_path / "broken.glb"
    p.write_bytes(wutil.glb_bytes(doc, np.zeros(1, np.float32).tobytes()))
    (rec,) = _validate([p], tmp_path)
    assert any(sev == 0 for sev, _c, _p, _m in rec["issues"])
