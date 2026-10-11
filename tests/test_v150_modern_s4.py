"""Python 3.13 idioms in the parsers, loaders and helpers of wlib (slice S4).

    strict   a zip whose sequences must have one length raises ValueError on a
             mismatch (through the function that zips, not zip itself)
    notes    a parse / read failure carries an exception note naming the file, the
             asset or model and the byte order or offset where known; the exception
             type and message are unchanged
    idioms   the dispatches rewritten as match statements and the chunking rewritten
             with itertools.batched / pairwise give the same answers

Synthetic data only: no game files.
"""

import json
import math
import struct

import numpy as np
import pytest

import bake_v4
import build_bind_file
import char_lib
import decode_sequence as ds
import exact_math as em
import extract_skeletons
import jiggle_d6
import kapow_fragment as kf
import kapow_props as kp
import mesh_loader
import parse_model_nodes as pmn
import particle_asset as pa
import ragdoll_rig as rr
import script_database as sdb
import skeleton_records as sr
import terrain_asset as ta
import text_assets as txt


def _notes(ex):
    return "\n".join(getattr(ex, "__notes__", []))


# ------------------------------------------------------------------- strict zips
def test_jiggle_joint_frame_cache_with_arrays_of_different_lengths_is_refused(tmp_path):
    bind = tmp_path / "bind_female_file_v1.npz"  # only its name is read: the cache wins
    cache = tmp_path / "jointframes_v2_female.npz"
    np.savez(cache, names=["BreastL", "BreastR"], yaxes=[[0, 1, 0]] * 2, zaxes=[[0, 0, 1]] * 2)
    got = jiggle_d6.joint_frames(str(bind))
    assert sorted(got) == ["BreastL", "BreastR"]
    np.savez(cache, names=["BreastL", "BreastR"], yaxes=[[0, 1, 0]], zaxes=[[0, 0, 1]] * 2)
    with pytest.raises(ValueError, match="zip") as ei:
        jiggle_d6.joint_frames(str(bind))
    assert _notes(ei.value) == (
        "jiggle joint-frame cache %s: its arrays differ in length; "
        "delete it (it is written again)" % cache
    )


def _fragment_result(at):
    return {
        "order": "<",
        "schema": [],
        "schema_lead": 0,
        "inst": [{"node": "00000001", "created": False, "props": []}],
        "at": at,
    }


def test_fragment_sections_need_one_offset_list_per_instance_record():
    out = kf.sections(b"", _fragment_result([[]]))
    assert out["instances"] == [{"name": "(preamble)"}]
    with pytest.raises(ValueError, match="zip"):
        kf.sections(b"", _fragment_result([]))


def _body_props(name):
    return {
        "name": name,
        "mass": 1.0,
        "linearDamping": 0.0,
        "angularDamping": 0.0,
        "numSolverIterations": 4,
        "maxLinearVelocity": 0.0,
        "maxAngularVelocity": 0.0,
        "movementType": 0,
    }


def _fake_model(monkeypatch, positions, parents, joint):
    nodes = [
        {"name": "n%d" % i, "pos": pos, "quat": [0.0, 0.0, 0.0, 1.0], "parent": par}
        | {"volumes": [[], []]}
        for i, (pos, par) in enumerate(zip(positions, parents, strict=True))
    ]
    ab = {
        "bodies": [0, 1],
        "cloth_bodies": [],
        "cloths": [],
        "joints": [joint],
        "records": [],
    }
    monkeypatch.setattr(
        rr._pmn, "model_physics", lambda mb, order: {"nodes": nodes, "articulated_body": ab}
    )
    joint_props = {"childSpaceOrient": [0.0, 0.0, 0.0, 1.0], "childSpacePos": [0.0, 0.0, 0.0]}
    objs = [{"props": _body_props("a")}, {"props": _body_props("b")}, {"props": joint_props}]
    monkeypatch.setattr(sr, "record_objects", lambda records, names, order: objs)


@pytest.mark.parametrize(
    "positions, parents, joint",
    [
        # a child placed from a parent world position of 4 values (bind world positions)
        ([[0.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [-1, 0], (0, 1)),
        # the joint frame in the world from a child body position of 4 values
        ([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], [-1, -1], (0, 1)),
        # the joint frame seen from a parent body position of 4 values
        ([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]], [-1, -1], (1, 0)),
    ],
)
def test_ragdoll_rig_vectors_must_have_three_components(monkeypatch, positions, parents, joint):
    _fake_model(monkeypatch, positions, parents, joint)
    with pytest.raises(ValueError, match="zip"):
        rr.build(b"", order="<")


def test_ragdoll_helpers_of_the_reflected_rig_must_pair_one_to_one(monkeypatch):
    calls = []

    def fake(rig, bind_names, Rb, tb, material=None, joint_names=None):
        calls.append(1)
        n = 2 if len(calls) == 1 else 1  # the reflected rig gives one helper less
        return {"shapes": [{"extras": {"k": i}} for i in range(n)], "joints": [], "extras": {}}

    monkeypatch.setattr(rr, "_glb_helpers", fake)
    Rb, tb = np.zeros((0, 3, 3)), np.zeros((0, 3))
    with pytest.raises(ValueError, match="zip"):
        rr.glb_helpers({}, [], Rb, tb, frame="true")
    calls.clear()
    monkeypatch.setattr(
        rr,
        "_glb_helpers",
        lambda *a, **k: {"shapes": [{"extras": {"k": 1}}], "joints": [], "extras": {"e": 1}},
    )
    out = rr.glb_helpers({}, [], Rb, tb, frame="true")
    assert out["shapes"] == [{"extras": {"k": 1}}] and out["extras"] == {"e": 1}


def test_terrain_stream_needs_one_vertex_buffer_per_decal(monkeypatch):
    doc = {"order": "<", "texture_layers": [], "sectors": [], "decals": [{"vertex_buffer": {}}]}
    lay = {"stride": 48, "bytes": 0, "decals": [], "cells": [], "decoded_bytes": 0}
    monkeypatch.setattr(ta, "stream_layout", lambda d, s: dict(lay))
    with pytest.raises(ValueError, match="zip"):
        ta.decode_stream(doc, b"")
    assert ta.decode_stream(doc | {"decals": []}, b"")["decals"] == []


class _Node:
    def __init__(self, nid, cls, props, name=None):
        self.id, self.cls, self.props, self.name = nid, cls, props, name

    def p(self, key):
        return self.props.get(key)


class _MovieDB:
    """The parts of sound_meta.SoundDB that text_assets._movies reads."""

    def __init__(self, root):
        self.out = str(root)
        frag = root / "movie.fragment"
        frag.write_bytes(b"MoviePlayer")
        self.path = str(frag)
        self.slot = _Node(
            2, "SubtitleSlot", {"textRes": "/Localize/Sub_uk.txt", "defaultDuration": 2.0}
        )
        self.player = _Node(1, "MoviePlayerCtrl", {"subtitleSlot": "SLOT"}, "Player")

    def files(self):
        return {"movie": (self.path, "movie.fragment")}

    def nodes(self, rel):
        return {1: self.player, 2: self.slot}

    def resolve(self, ref, rel):
        return (rel, self.slot) if ref == "SLOT" else None


def test_movie_lines_need_one_shown_from_entry_per_line(tmp_path, monkeypatch):
    name = "/Localize/Sub_uk.txt"
    tables = {name: {"en": [("00:00:000->00:01:500", "hello")]}}
    movies = txt._movies(_MovieDB(tmp_path), tables, {name: {}})
    assert [ln["text"] for ln in movies[0]["lines"]] == [{"en": "hello"}]
    monkeypatch.setattr(txt, "shown_from", lambda lines: [])
    with pytest.raises(ValueError, match="zip"):
        txt._movies(_MovieDB(tmp_path), tables, {name: {}})


def test_decode_sequence_keeps_plain_zip_for_keys_of_different_dimension():
    # every key stores its own dimension: the components both keys have are blended
    track = {
        "type": 2,
        "value_type": "vector",
        "keys": [{"t": 0.0, "value": [0.0, 0.0, 0.0]}, {"t": 1.0, "value": [2.0, 4.0]}],
    }
    assert ds.evaluate(track, 0.5) == [1.0, 2.0]


# --------------------------------------------------------------------- notes
def test_model_node_parse_failure_names_the_byte_order():
    with pytest.raises(ValueError, match="no node names") as ei:
        pmn.parse(b"\x00" * 64, order=">")
    assert _notes(ei.value) == "parse_model_nodes: 64-byte header read big-endian (Xbox 360 / PS3)"


def test_bind_build_failure_names_the_header_file(tmp_path):
    hdr = tmp_path / "Broken_Skeleton.model"
    hdr.write_bytes(b"\x00" * 64)
    with pytest.raises(ValueError, match="no node names") as ei:
        build_bind_file.build(str(hdr), None, str(tmp_path / "bind.npz"))
    assert str(hdr) in _notes(ei.value)


def test_skeleton_table_failure_names_the_family():
    with pytest.raises(ValueError) as ei:
        extract_skeletons.skeleton_from_header(b"\x00" * 64, "female")
    assert "family 'female'" in _notes(ei.value)


def test_script_database_failure_names_the_file(tmp_path):
    p = tmp_path / "Database.bin"
    p.write_bytes(b"\xff\xff\xff\x7f")
    with pytest.raises(sdb.DatabaseError, match="not a script database") as ei:
        sdb.load(str(p))
    assert str(p) in _notes(ei.value) and "4 bytes" in _notes(ei.value)


def test_particle_failure_says_the_untyped_layout_fails_too():
    data = struct.pack("<I", 5) + b"Abcd\0" + struct.pack("<I", 100)
    with pytest.raises(pa.ParticleError, match="payload of Abcd") as ei:
        pa.parse(data, order="<")
    assert "untyped record layout fails too" in _notes(ei.value)


def test_bake_failure_names_the_clip(tmp_path, monkeypatch):
    for k in ("BIND", "Rb", "tb", "tloc", "par", "NS", "names", "CONJ"):
        monkeypatch.setattr(bake_v4, k, getattr(bake_v4, k))  # restored after the test
    bind = tmp_path / "bind.npz"
    np.savez(
        bind,
        Rb=np.eye(3)[None],
        tb=np.zeros((1, 3)),
        tloc=np.zeros((1, 3)),
        par=np.array([-1]),
        names=np.array(["root"]),
    )
    with pytest.raises(ValueError, match="multiple of element size") as ei:
        bake_v4.bake("short_clip", bind=str(bind), bank={"short_clip": b"\x01\x02\x03\x04\x05"})
    assert "clip 'short_clip' (5 bytes, little-endian (PC))" in _notes(ei.value)


def test_mesh_loader_failure_names_the_model_and_submesh(monkeypatch):
    import watchmen_extract as we

    monkeypatch.setattr(we, "find_descriptors", lambda mh, order: [(3, 56, 6)])
    monkeypatch.setattr(we, "extract_materials", lambda mh: [])
    monkeypatch.setattr(we, "submesh_materials", lambda mh, order: [])
    monkeypatch.setattr(mesh_loader, "_header_path", lambda mh, ms, order: (None, "test"))

    def broken(*a):
        raise struct.error("unpack requires a buffer of 4 bytes")

    monkeypatch.setattr(mesh_loader, "_scan_one", broken)
    with pytest.raises(struct.error, match="unpack requires") as ei:
        mesh_loader.load_submeshes(b"", b"", "Body", order=">", platform="x360", log=None)
    note = _notes(ei.value)
    assert note == (
        "mesh_loader: model 'Body' submesh 0 of 1 (big-endian (Xbox 360 / PS3), platform x360)"
    )


def test_character_part_failure_names_the_model_file(tmp_path):
    base = str(tmp_path / "Missing_Body")
    with pytest.raises(FileNotFoundError) as ei:
        char_lib.load_parts([base], ["root"])
    assert base + ".model" in _notes(ei.value)


def test_text_table_failure_names_the_asset_and_language(tmp_path):
    root = tmp_path / "text"
    (root / "fr").mkdir(parents=True)
    (root / "fr" / "Menu.txt").write_bytes(struct.pack("<I", 3))  # 3 rows, none stored
    index = {
        "assets": {
            "/Localize/Menu.txt": {
                "byte_order": "little",
                "languages": {"fr": {"file": "fr/Menu.txt"}},
            }
        },
        "languages": [],
    }
    (root / "index.json").write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(ValueError, match="runs past the end") as ei:
        txt.load_text(str(tmp_path))
    assert "/Localize/Menu.txt [fr]" in _notes(ei.value)


def test_pivot_book_failure_says_neither_record_layout_has_a_sheet():
    pb = b"\x00" * 12 + b"\xff\xff\xff\xff"
    with pytest.raises(ValueError, match="bad pivot book object header") as ei:
        rr.pivot_sheets(pb, order="<")
    assert "no sheet in either record layout" in _notes(ei.value)


# --------------------------------------------------------------------- idioms
def test_quadrant_dispatch_of_exact_sin_and_cos():
    for x in (0.1, 2.0, 3.5, 5.0, -2.0, 100.0):
        assert abs(em.sin(x) - math.sin(x)) < 1e-15
        assert abs(em.cos(x) - math.cos(x)) < 1e-15


def test_sequence_play_position_per_loop_mode():
    seq = {"duration": 2.0}
    got = [ds.play_position(seq, 3.0, mode) for mode in range(5)]
    assert got == [1.0, 2.0, 0.0, 1.0, 1.0]


def test_spline_key_handles_are_split_per_component():
    hh = [float(x) for x in range(8)]
    b = struct.pack("<fII2f", 0.0, 3, 2, 1.0, 2.0) + struct.pack("<I8f", 2, *hh)
    keys, p = ds._keys(b, 0, 1, True, "<")
    assert p == len(b)
    assert keys[0]["in"] == [[0.0, 1.0], [4.0, 5.0]] and keys[0]["out"] == [[2.0, 3.0], [6.0, 7.0]]


def test_record_values_by_type():
    b = struct.pack("<i", -5)
    assert kp.record_value("integer", b, 0, 1) == -5 == kp.record_value("enum", b, 0, 1)
    assert kp.record_value("integer", b, 0, 2) is None
    assert sr.record_value(0x36604FF4, b) == -5
    assert sr.record_value(0xEDEF427C, struct.pack("<II", 1, 2)) == (2 << 32) | 1
    assert sr.record_value(0x12345678, b) == {"type_id": "0x12345678", "hex": b.hex()}


def test_particle_vector_values_round_trip():
    payload = struct.pack("<3f", 1.5, -2.25, 0.1)
    v, canonical = pa._decode_value("vector", payload, "<")
    assert canonical and v == [1.5, -2.25, 0.1]
    assert pa._encode_value("vector", v, "<") == payload


def test_proxy_mesh_triangle_list_ignores_a_short_tail():
    shape = {
        "type": "convex_mesh",
        "file": {"mode": 1, "vertices": [[0, 0, 0], [1, 0, 0], [0, 1, 0]], "indices": [0, 1, 2, 0]},
    }
    v, tri = rr.proxy_mesh(shape)
    assert tri.tolist() == [[0, 1, 2]]


def test_terrain_pass_ranges_pair_first_and_end():
    doc = {
        "order": "<",
        "decals": [],
        "sectors": [
            {
                "index": 0,
                "cells": [
                    {
                        "vertex_buffer": {"count": 0},
                        "index_buffer": None,
                        "quads_x": 0,
                        "quads_z": 0,
                    }
                ],
            }
        ],
    }
    stream = (
        struct.pack("<2I", 0, 6) + struct.pack("<I4I", 2, 0, 3, 3, 6) + struct.pack("<I2I", 2, 7, 9)
    )
    stream += struct.pack("<I", 0) + struct.pack("<I", 0) + b"\x00\x00"
    lay = ta.stream_layout(doc, stream)
    assert lay["cells"][0]["pass1"] == [
        {"layer": 7, "first": 0, "end": 3},
        {"layer": 9, "first": 3, "end": 6},
    ]
    assert lay["leftover_bytes"] == 0
