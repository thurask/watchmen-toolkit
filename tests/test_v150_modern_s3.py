"""Python 3.13 modernisation of the character, face, sound and navigation modules
(characters_export, variant_glb, anim_state_machine, face_rule, sound_meta,
nav_data).

    strict zip   the pairings whose two sides must have one length now fail
                 with ValueError on a mismatch instead of dropping the tail
    add_note     a parse / extract failure carries where it happened (fragment,
                 host node, model, clip, cell offset, byte order, platform) as an
                 exception note; the message and the exception type are unchanged
    match        the record-kind dispatches give the results of the old chains

Synthetic data only: no game files.
"""

import json
import struct
import types

import numpy as np
import pytest

import anim_state_machine as asm
import characters_export as ce
import face_rule as fr
import nav_data as nd
import sound_meta as sm
import variant_glb as vg
from test_nav_data import demo_hpd, make_aipathdata


def _notes(ei):
    return "\n".join(getattr(ei.value, "__notes__", ()))


# ---------------------------------------------------------------------------
# strict zip: a length mismatch is an error
# ---------------------------------------------------------------------------


def _floor_with_links(h):
    for c in h["cells"]:
        for fl in (c.get("mesh") or {}).get("floors", ()):
            if fl["links"]:
                return fl
    raise AssertionError("the demo file has a floor with a cell link")


def test_nav_document_refuses_link_targets_of_another_length():
    """build_document pairs every cell link with the target the loader's second
    pass read for it; a target list of another length used to drop links."""
    h = nd.parse_hpd(demo_hpd())
    fl = _floor_with_links(h)
    assert len(fl["links"]) == len(fl["link_targets"]) == 1
    nd.build_document(h)  # equal lengths: unchanged
    fl["link_targets"] = []
    with pytest.raises(ValueError, match="zip"):
        nd.build_document(h)
    fl["link_targets"] = [(0, 0, 1), (0, 0, 2)]
    with pytest.raises(ValueError, match="zip"):
        nd.build_document(h)


def test_nav_document_refuses_level_link_targets_of_another_length():
    h = nd.parse_hpd(demo_hpd())
    fl = _floor_with_links(h)
    a, b = fl["links"][0]
    fl["level_links"] = [(a, b)]
    fl["level_link_targets"] = [(0, 0, 0)]
    doc = nd.build_document(h)
    floors = [f for c in doc["cells"] if c["mesh"] for f in c["mesh"]["floors"]]
    assert [f["level_links"][0]["to"] for f in floors if "level_links" in f] == [[0, 0, 0]]
    fl["level_link_targets"] = []
    with pytest.raises(ValueError, match="zip"):
        nd.build_document(h)


def test_by_construction_pairings_still_give_the_old_results():
    """The strict zips over lists built from the same source in the line before
    (_page_rate: durations per slot; _stack_weights: one share per page;
    characters_export.discover: one base name per model reference) cannot
    mismatch; they keep their results."""
    root = asm.Node(1, asm.CLS_CLASS, "class")
    st = asm.Node(2, asm.CLS_STATE, "S")
    st.parent, root.children = root, [st]
    bl = asm.Node(3, asm.CLS_BLEND, "B")
    bl.parent, st.children = st, [bl]
    for i, (dur, sp) in enumerate(((0.0, 3.0), (2.0, 1.5))):
        s = asm.Node(10 + i, asm.CLS_SLOT, "{C%d.animation}" % i)
        s.props = {"m_sduration": "%g s" % dur, "speedFactor": sp, "targetAnimation": "C%d" % i}
        s.parent = bl
        bl.children.append(s)
    it = asm.Interpreter(root)
    it.transit(st)
    pg = it.page
    assert it._page_rate(pg) == pytest.approx(1.5 / 2.0)  # the first slot WITH a duration
    pg.raw = pg.shown = 1.0
    assert it.slot_weights() == {"C0": 1.0}


# ---------------------------------------------------------------------------
# add_note: where a parse failed
# ---------------------------------------------------------------------------


def test_hpd_mesh_failure_names_the_cell():
    data = bytearray(demo_hpd())
    tag = data.index(b"Kynogon Mesh")
    struct.pack_into("<I", data, tag + 12, 9)  # AI mesh version 9: the loader takes 1..5
    with pytest.raises(nd.NavError) as ei:
        nd.parse_hpd(bytes(data))
    assert str(ei.value) == "AI mesh version 9 at 0x%x (the engine accepts 1..5)" % (tag + 12)
    assert "cell 1000 (cell table entry at 0x84): AI mesh of" in _notes(ei)
    assert "at 0x%x.." % tag in _notes(ei)


def test_hpd_header_attribute_tables_are_the_file_triples():
    h = nd.parse_hpd(demo_hpd())["header"]
    words = struct.unpack_from("<33I", demo_hpd(), 0)
    assert h["vertex_attributes"] == [words[7 + 3 * i : 10 + 3 * i] for i in range(4)]
    assert h["edge_attributes"] == [words[19 + 3 * i : 22 + 3 * i] for i in range(4)]
    assert h["vertex_attributes"][0] == (2, 0, 6)


def test_aipathdata_node_kinds():
    tree = nd.parse_aipathdata(make_aipathdata())
    assert tree["root"]["children"] and tree["trailing"] == 0
    bad = bytearray(make_aipathdata())
    struct.pack_into("<I", bad, 19, 7)  # root node kind 7
    with pytest.raises(nd.NavError, match="node kind 7 at 0x13"):
        nd.parse_aipathdata(bytes(bad))


def _write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path)


BROKEN = {"instances": [{}], "nodes_full": [{"id": 1, "props": [["name", "x"]]}]}


def test_load_tree_failure_names_the_fragment(tmp_path):
    p = _write_json(tmp_path / "extracted" / "TNT" / "Bad.fragment.json", BROKEN)
    with pytest.raises(ValueError) as ei:
        asm.load_tree(p)
    assert "not enough values to unpack" in str(ei.value)
    assert _notes(ei) == "fragment %s" % p


def test_spliced_fragment_failure_names_its_host(tmp_path):
    _write_json(tmp_path / "extracted" / "Sub" / "Bad.fragment.json", BROKEN)
    top = {
        "instances": [{}],
        "nodes_full": [
            {
                "id": 7,
                "type": "AnimationStateGroupWM(Node)",
                "props": [["name", "s", "Group"], ["assetName", "s", "/Sub/Bad.fragment"]],
            }
        ],
    }
    p = _write_json(tmp_path / "extracted" / "TNT" / "Top.fragment.json", top)
    with pytest.raises(ValueError) as ei:
        asm.load_tree(p)
    notes = _notes(ei)
    assert "Bad.fragment (spliced under AnimationStateGroupWM 'Group', node id 7)" in notes
    assert "Top.fragment" not in notes  # the host's own file read fine


def test_face_class_failure_names_the_class(tmp_path):
    p = _write_json(tmp_path / "extracted" / "AnimationClassEnemy01Face.fragment.json", BROKEN)
    with pytest.raises(ValueError) as ei:
        fr.face_class_record("Enemy01Face", p, str(tmp_path), None)
    assert _notes(ei).splitlines() == ["fragment %s" % p, "face class Enemy01Face"]


def test_music_fragment_failure_names_file_and_byte_order(monkeypatch):
    import kapow_json

    def boom(name, data, order=None):
        raise ValueError("chunk walk ends past the data")

    monkeypatch.setattr(kapow_json, "to_json", boom)
    data = b"\0" * 8 + b"MusicStreamSlot" + b"\0" * 9
    with pytest.raises(ValueError, match="chunk walk") as ei:
        sm.music_setups_from_bytes(data, "TNT/Music.fragment", ">")
    assert _notes(ei) == (
        "music fragment TNT/Music.fragment: 32 bytes, big-endian (Xbox 360 / PS3)"
    )
    assert sm.music_setups_from_bytes(b"no music here", "x.fragment") == []


def test_sound_meta_names_an_unreadable_animation_table(tmp_path):
    bad = tmp_path / "anim_meta.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError) as ei:
        sm.build(str(tmp_path), anim=str(bad))
    assert _notes(ei) == "animation table %s (anim_meta.json)" % bad


def test_character_fragment_failure_names_fragment_and_stem(monkeypatch, tmp_path):
    def bad(path):
        raise ValueError("node table runs past the data")

    monkeypatch.setattr(ce, "_find_fragment", lambda root, stem: "/x/%s.fragment" % stem)
    monkeypatch.setattr(ce, "_load_fragment", bad)
    with pytest.raises(ValueError, match="node table") as ei:
        ce.discover(str(tmp_path))
    first = ce.ENEMY_FRAGS[0]
    assert _notes(ei) == "character fragment /x/%s.fragment (%s)" % (first, first)


def test_weapon_fragment_failure_names_the_fragment(monkeypatch, tmp_path):
    monkeypatch.setattr(ce, "_find_fragment", lambda root, stem: "/x/WeaponDB.fragment")
    monkeypatch.setattr(
        ce, "_load_fragment", lambda p: {"nodes_full": [{"id": 1, "props": [["name", "x"]]}]}
    )
    with pytest.raises(ValueError) as ei:
        ce.weapon_sets(str(tmp_path))
    assert _notes(ei) == "weapon fragment /x/WeaponDB.fragment"


def test_rigid_model_failure_names_model_order_and_platform(monkeypatch, tmp_path):
    import char_lib
    import mesh_loader

    base = tmp_path / "WPN_Bat"
    (tmp_path / "WPN_Bat.model").write_bytes(b"\0" * 12)
    (tmp_path / "WPN_Bat.model.stream").write_bytes(b"\0" * 40)

    def bad(*a, **k):
        raise struct.error("unpack_from requires a buffer of at least 64 bytes")

    monkeypatch.setattr(char_lib, "model_order", lambda mh, ms=None, name=None, log=print: ">")
    monkeypatch.setattr(mesh_loader, "load_submeshes", bad)
    monkeypatch.delenv("WATCHMEN_CONSOLE", raising=False)
    with pytest.raises(struct.error) as ei:
        ce._rigid_parts(str(base), np.eye(3), np.zeros(3), 0, "%s_sub%d", positional=True)
    assert _notes(ei) == (
        "model %s.model (12 header bytes, 40 stream bytes, big-endian (Xbox 360 / PS3), "
        "platform console not known)" % base
    )


def test_variant_mesh_failure_names_model_archive_and_platform(monkeypatch):
    import char_lib
    import mesh_loader

    entry = types.SimpleNamespace(name="art/characters/Body.model")
    monkeypatch.setattr(
        vg.efa,
        "iter_blocks",
        lambda naz, streams=True: iter([("derived_ps3/levels/x", {"h": b"h", "s": b"s"})]),
    )
    monkeypatch.setattr(vg.we, "extract_block", lambda h, s: [(entry, b"\0" * 20, b"\0" * 64)])
    monkeypatch.setattr(char_lib, "model_order", lambda mh, ms=None, name=None, log=print: ">")
    monkeypatch.setattr(mesh_loader, "palette_remap", lambda *a, **k: ({}, []))

    def bad(*a, **k):
        raise IndexError("descriptor 3 of 2")

    monkeypatch.setattr(mesh_loader, "load_submeshes", bad)
    with pytest.raises(IndexError, match="descriptor 3 of 2") as ei:
        vg.load_parts(["Body"], ["Bip01"], naz="game.naz")
    assert _notes(ei) == (
        "model Body in game.naz (20 header bytes, 64 stream bytes, big-endian (Xbox 360 / PS3), "
        "platform ps3)"
    )


def test_variant_fragment_failure_names_fragment_and_variant(monkeypatch):
    import kapow_json

    def bad(path):
        raise OSError(2, "No such file or directory")

    monkeypatch.setattr(kapow_json, "load_fragment", bad)
    with pytest.raises(OSError) as ei:
        vg.variant_from_fragment("Dominatrices.fragment.json", "Dominatrix_1")
    assert _notes(ei) == "fragment Dominatrices.fragment.json (variant Dominatrix_1)"


def test_variant_clip_header_failure_names_the_clip(monkeypatch, tmp_path):
    bind = tmp_path / "bind.npz"
    np.savez(bind, names=np.array(["Bip01"]))
    bake = tmp_path / "bake"
    bake.mkdir()
    np.save(bake / "EN4_walk.npy", np.zeros((2, 1, 3, 4), np.float32))
    monkeypatch.setattr(vg, "variant_from_fragment", lambda f, v: ("Female_Skeleton", []))
    monkeypatch.setattr(vg, "load_parts", lambda *a, **k: [])
    with pytest.raises(struct.error) as ei:
        vg.build(
            "x.fragment",
            "V",
            str(tmp_path / "out.glb"),
            bakedir=str(bake),
            bank={"EN4_walk": b"\0\0\0"},
            bind=str(bind),
            prefix=("EN4",),
        )
    assert _notes(ei) == "clip EN4_walk: header of 3 bytes in the bank"


# ---------------------------------------------------------------------------
# match: the dispatches give what the if / elif chains gave
# ---------------------------------------------------------------------------


def test_interval_types():
    assert [asm.interval_met(0.5, t, 0.5, 1.0) for t in (0, 1, 2, 3)] == [True, True, True, False]
    assert [asm.interval_met(1.0, t, 0.5, 1.0) for t in (0, 1, 2)] == [False, False, True]
    assert asm.interval_met(0.7, 0.0, 0.5, 1.0) is True  # a float type id compares equal


def test_shared_clock_by_trigger():
    x = {"raw": 0.5, "t_s": 0.3}
    assert fr._shared(dict(x, trigger="TOTAL_PLAY_TIME"), 0.0, 2.0, False) == 0.5
    assert fr._shared(dict(x, trigger="ENTER_STATE"), 0.0, 2.0, False) == 0.0
    assert fr._shared(dict(x, trigger="LEAVE_STATE"), 0.0, 2.0, False) is None
    assert fr._shared(dict(x, trigger="PLAY_POS"), 0.0, 2.0, True) == 0.25
    assert fr._shared(dict(x, trigger="PLAY_POS"), 0.0, 2.0, False) == 0.3  # not slaved
    assert fr._shared(dict(x, trigger="PLAY_POS"), 0.0, 0.0, True) is None
    assert fr._shared(dict(x, trigger=None), 0.0, 2.0, True) == 0.3


def test_face_script_by_input():
    ins = [
        {"t_s": 0.1, "input": "HITTAKEN", "damage_pose_id": 4},
        {"t_s": 0.2, "input": "HITTAKEN", "pose_established": False},
        {"t_s": 0.3, "input": "START_SPEAK", "talk_s": 1.0},
        {"t_s": 0.4, "input": "DEAD"},
        {"t_s": 0.5, "input": "NORMAL_ATTACK"},
        {"t_s": None, "input": "DEAD"},
    ]
    assert fr._script(ins) == (
        (0.1, "HIT", 4),
        (0.3, "START_SPEAK", 0),
        (1.3, "STOP_SPEAK", 0),
        (0.4, "DEAD", 0),
    )
    assert ins[1]["in_track"] is False and ins[5]["not_in_track_because"] == "no defined time"


def test_cue_change_modes():
    names = ["Click", "Drop"]
    assert sm.cue_change(0, names) == ("at_once", None)
    assert sm.cue_change(None, names) == ("at_once", None)
    assert sm.cue_change(1, names) == ("next_cue", None)
    assert sm.cue_change(sm.cue_hash("Drop"), names) == ("named_cue", "Drop")
    assert sm.cue_change(2, names) == ("named_cue", "unresolved")
