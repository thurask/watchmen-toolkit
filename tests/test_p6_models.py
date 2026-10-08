"""Multi-part rigid models, model sidecar additions, standalone files.

* vertices are stored in the space of their part: decode_model (OBJ and GLB) and
  decode_model_mesh take them through the part chain, v' = conj(q)·v·q + pos, the
  part first and then every parent; skinned buffers are left as stored;
* <name>.model.json lists the parts (transform, pivot-book index, shadow-hull
  group of each submesh) and says whether the transforms were applied;
* particle surfaces: `weight_is_unit`, and the area test tolerates the console
  rounding;
* standalone `_h_z` preamble; two standalone pairs with one base name no longer
  overwrite each other.

Synthetic fixtures only (the builders of test_p3_part1_model / test_formats_v2)."""

import json
import math
import struct

import numpy as np
import pytest

import skeleton_records as sr
import watchmen_extract as we
from conftest import parse_glb

import test_p1_formats as tp1
import test_p3_part1_model as tm

S = math.sqrt(0.5)
#: the Pelvis node of tm.build(): pos (0, 1, 0), identity rotation
_PELVIS = struct.pack("<7f", 0, 1, 0, 0, 0, 0, 1)


def _capture(monkeypatch):
    cap = {}

    def fake(path, name, v, n, uv, tris, subs, mats, tex_index, log):
        cap.update(v=[tuple(p) for p in v], n=[tuple(p) for p in n])

    monkeypatch.setattr(we, "_write_obj_mtl", fake)
    return cap


# ---------------------------------------------------------------------------
# the transform itself
# ---------------------------------------------------------------------------
def _part(pos=(0, 0, 0), quat=(0, 0, 0, 1), parent=0xFFFFFFFF):
    return {"pos": tuple(map(float, pos)), "quat": tuple(map(float, quat)), "parent": parent}


def test_identity_chain_is_none_and_returns_the_input():
    M = {"parts": [_part(), _part(parent=0), _part(quat=(0, 0, 0, -1), parent=1)]}
    assert we.model_part_transforms(M) == [None, None, None]
    pts = [(1.0, 2.0, 3.0)]
    assert we.apply_part_transform(None, pts) is pts


def test_rotation_is_conj_q_v_q():
    # q = 90 degrees about +Y as stored: conj(q)·v·q turns +X into +Z, +Z into -X
    (xf,) = we.model_part_transforms({"parts": [_part(quat=(0, S, 0, S))]})
    got = we.apply_part_transform(xf, [(1, 0, 0), (0, 0, 1), (0, 1, 0)])
    assert np.allclose(got, [(0, 0, 1), (-1, 0, 0), (0, 1, 0)], atol=1e-6)
    # a direction is rotated, not moved
    (xf,) = we.model_part_transforms({"parts": [_part(pos=(5, 6, 7), quat=(0, S, 0, S))]})
    assert np.allclose(we.apply_part_transform(xf, [(1, 0, 0)]), [(5, 6, 8)], atol=1e-6)
    assert np.allclose(we.apply_part_transform(xf, [(1, 0, 0)], point=False), [(0, 0, 1)])


def test_chain_applies_the_part_first_then_its_parents():
    parts = [
        _part(pos=(10, 0, 0), quat=(0, S, 0, S)),  # root: turn, then move
        _part(pos=(0, 0, 2), parent=0),  # child: 2 along the root's local z
    ]
    root, child = we.model_part_transforms({"parts": parts})
    # child-local (1, 0, 0) -> root-local (1, 0, 2) -> turned (-2, 0, 1) -> (8, 0, 1)
    assert np.allclose(we.apply_part_transform(child, [(1, 0, 0)]), [(8, 0, 1)], atol=1e-6)
    assert np.allclose(we.apply_part_transform(root, [(1, 0, 0)]), [(10, 0, 1)], atol=1e-6)


def test_a_parent_loop_or_a_bad_index_ends_the_chain():
    parts = [_part(pos=(1, 0, 0), parent=1), _part(pos=(0, 1, 0), parent=0), _part(parent=77)]
    a, b, c = we.model_part_transforms({"parts": parts})
    assert np.allclose(we.apply_part_transform(a, [(0, 0, 0)]), [(1, 1, 0)])
    assert np.allclose(we.apply_part_transform(b, [(0, 0, 0)]), [(1, 1, 0)])
    assert c is None


# ---------------------------------------------------------------------------
# OBJ / mesh / GLB of a model whose parts are away from the origin
# ---------------------------------------------------------------------------
def test_obj_vertices_are_in_model_space(tmp_path, monkeypatch):
    """tm.build(): Body in Pelvis (0, 1, 0); Spine in a child of Pelvis at
    (0.1, 0, 0).  1.3.0 and the first 1.4.0 exports wrote both at the origin."""
    cap = _capture(monkeypatch)
    h, s = tm.build("<", "part2")
    assert we.decode_model(h, s, tmp_path / "m.obj") is True
    body, spine = cap["v"][:4], cap["v"][4:]
    assert np.allclose(body, [(0, 1, 0), (1, 1, 0), (1, 2, 0), (0, 2, 0)])
    assert np.allclose(spine, [(0.1, 1, 1), (1.1, 1, 1), (1.1, 2, 1), (0.1, 2, 1)])
    meta = json.loads((tmp_path / "m.model.json").read_text())
    assert meta["part_transforms_applied"] is True


def test_rotated_part_turns_positions_normals_and_tangents(tmp_path, monkeypatch):
    h, s = tm.build("<", "part2")
    assert h.count(_PELVIS) == 1
    h = h.replace(_PELVIS, struct.pack("<7f", 0, 1, 0, 0, S, 0, S))
    mesh = we.decode_model_mesh(h, s)
    body = mesh["submeshes"][0]
    assert body["part_moved"] is True
    # stored corner (1, 0, 0) -> (0, 0, 1) + (0, 1, 0); normal +Z -> -X; tangent +X -> +Z
    assert np.allclose(body["positions"][1], (0, 1, 1), atol=1e-6)
    assert np.allclose(body["normals"][0], (-1, 0, 0), atol=1e-3)
    assert np.allclose(body["tangent"][0], (0, 0, 1), atol=1e-3)
    assert np.allclose(body["bitangent"][0], (0, 1, 0), atol=1e-3)
    # as stored on request
    raw = we.decode_model_mesh(h, s, part_space=True)["submeshes"][0]
    assert raw["part_moved"] is False
    assert np.allclose(raw["positions"][1], (1, 0, 0)) and np.allclose(raw["normals"][0], (0, 0, 1))
    # the OBJ path gives the same vertices as the mesh path
    cap = _capture(monkeypatch)
    assert we.decode_model(h, s, tmp_path / "m.obj") is True
    assert np.allclose(cap["v"][:4], body["positions"], atol=1e-6)
    assert np.allclose(cap["n"][0], (-1, 0, 0), atol=1e-3)


def test_shadow_hull_follows_its_part():
    h, s = tm.build("<", "part2")
    mesh = we.decode_model_mesh(h, s, lod="all", kinds=("shadow",))
    (hull,) = mesh["submeshes"]
    assert np.allclose(hull["positions"], [(x, 1, 5) for x in range(4)])


@pytest.mark.usefixtures("engine_frame")
def test_glb_positions_are_in_model_space(tmp_path, monkeypatch):
    monkeypatch.setitem(we._RIG, "on", True)
    monkeypatch.setitem(we._RIG, "loaded", False)
    monkeypatch.setitem(we._RIG, "attrs", True)
    h, s = tm.build("<", "part2")
    assert we.decode_model(h, s, tmp_path / "m.obj", {}, None)
    g = parse_glb(tmp_path / "m.glb")
    lo, hi = np.full(3, 1e9), np.full(3, -1e9)
    for m in g.j["meshes"]:
        for pr in m["primitives"]:
            P = np.asarray(g.accessor(pr["attributes"]["POSITION"]))
            lo, hi = np.minimum(lo, P.min(0)), np.maximum(hi, P.max(0))
    assert np.allclose(lo, (0, 1, 0)) and np.allclose(hi, (1.1, 2, 1))


def test_skinned_buffer_is_not_moved(monkeypatch):
    """A buffer with joints is placed by its bone palette."""
    h, s = tm.build("<", "part2")
    fm = {k: dict(v) for k, v in we.vertex_formats("<").items()}
    fm[5]["joints"] = ("u8x4", 0)
    monkeypatch.setattr(we, "vertex_formats", lambda order="<": fm)
    monkeypatch.setattr(we, "decode_vertex_attributes", lambda *a, **k: {})
    sub = we.decode_model_mesh(h, s)["submeshes"][0]
    assert sub["part_moved"] is False and np.allclose(sub["positions"][0], (0, 0, 0))


# ---------------------------------------------------------------------------
# sidecar
# ---------------------------------------------------------------------------
def test_model_json_lists_the_parts():
    h, s = tm.build("<", "part2")
    meta = we.model_meta(h)
    root, pelvis, spine = meta["parts"]
    assert (root["name"], root["parent"], root["moved"]) == ("", -1, False)
    assert pelvis["pos"] == [0.0, 1.0, 0.0] and pelvis["quat"] == [0.0, 0.0, 0.0, 1.0]
    assert pelvis["moved"] is True and pelvis["parent"] == 0 and pelvis["shadow_hulls"] == 1
    assert spine["parent"] == 1 and spine["moved"] is True
    assert [(m["lod"], m["name"]) for m in pelvis["submeshes"]] == [(0, "Body"), (1, "BodyLow")]
    # the builder writes u28 = 1 and b24 clear: in shadow-hull group 1
    assert pelvis["submeshes"][0]["shadow_id"] == 1
    assert pelvis["submeshes"][0]["in_shadow_hull"] is True
    assert pelvis["pivotbook_index"] == 0
    assert "0x544ae4" in meta["parts_note"] and "0x53e987" in meta["parts_note"]
    json.dumps(meta)


def test_parse_model_header_names_the_two_fields_and_keeps_the_old_keys():
    M = we.parse_model_header(tm.build("<", "part2")[0])
    P = M["parts"][1]
    assert P["pivotbook_index"] == P["f1"] == 0
    sm = P["lods"][0][0]
    assert sm["shadow_id"] == sm["u28"] == 1


def test_scan_decoded_sidecar_says_the_transforms_were_not_applied():
    h, _s = tm.build(">", "part1")
    meta = we.model_meta_scanned(h, ">")
    assert meta["mesh_source"] == "descriptor scan"
    assert meta["part_transforms_applied"] is False and meta["parts"][1]["moved"] is True


# ---------------------------------------------------------------------------
# particle surfaces
# ---------------------------------------------------------------------------
def test_weight_is_unit_marks_constant_one_weights():
    meta = we.model_meta(tp1._model_with_surface(weights=(1.0, 1.0))[0])
    assert meta["particle_surfaces"][0]["weight_is_unit"] is True
    assert "weight_is_unit" in meta["particle_surface_note"]
    meta = we.model_meta(tp1._model_with_surface(weights=(1.0, 0.5))[0])
    assert "weight_is_unit" not in meta["particle_surfaces"][0]


def test_area_test_tolerates_the_console_rounding():
    verts = np.array([(0, 0, 0), (2, 0, 0), (0, 1, 0)], np.float32)
    idx = np.array([0, 1, 2], np.uint16)
    for w, want in ((1.0, True), (1.0016, True), (0.9984, True), (1.006, False), (0.5, False)):
        assert sr._weight_is_area([{"area_weight": w}], verts, idx) is want, w


# ---------------------------------------------------------------------------
# standalone files
# ---------------------------------------------------------------------------
def test_standalone_preamble():
    import zlib

    z = zlib.compress(b"ModelRes" * 4)
    pc = struct.pack("<II", 0xEFD1E8BB, 0x12345678) + z
    assert we.standalone_preamble(pc) == {
        "version_signature": 0xEFD1E8BB,
        "second_word": 0x12345678,
        "order": "<",
        "build": "part2",
    }
    be = struct.pack(">II", 0x520D5FD8, 7) + z
    got = we.standalone_preamble(be)
    assert (got["order"], got["build"], got["second_word"]) == (">", "part1", 7)
    # an unknown first word is read little-endian and names no build
    got = we.standalone_preamble(struct.pack("<II", 0x11223344, 1) + z)
    assert got["build"] is None and got["version_signature"] == 0x11223344
    # `_s_z`: the zlib stream starts the file
    assert we.standalone_preamble(z) is None
    assert we.inflate_standalone(pc) == b"ModelRes" * 4
    assert set(we.STANDALONE_SIGNATURES) == {".modelres", ".texture", ".pivotbook"}
    for tab in we.STANDALONE_SIGNATURES.values():
        assert sorted(tab.values()) == ["part1", "part2"]


def test_two_standalone_pairs_with_one_name_do_not_overwrite_each_other():
    log = []
    names = we.OutputNames(log.append)
    a = we.standalone_output_name(names, "a/unit_box.modelres", b"H", b"S1")
    b = we.standalone_output_name(names, "b/unit_box.modelres", b"H", b"S2")
    c = we.standalone_output_name(names, "c\\unit_box.modelres", b"H", b"S1")
    assert a == ("unit_box.modelres", "new")
    assert b == ("unit_box~b.modelres", "variant")
    assert c[1] == "repeat"
    assert len(names.variants) == 1 and any("unit_box" in str(x) for x in log)
    # a file at the archive root
    assert we.standalone_output_name(we.OutputNames(), "unit_cone.modelres", b"H", b"S") == (
        "unit_cone.modelres",
        "new",
    )
