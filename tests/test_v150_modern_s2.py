"""Python 3.13 idioms in level_meta, combat_meta, fx_meta and anim_meta.

    strict  a zip whose sequences must have one length raises ValueError on a
            mismatch (through the function that zips, not zip itself)
    notes   a parse / read failure carries an exception note naming the file, the
            level or the fragment (and the offset or byte order where known); the
            exception type and message are unchanged
    match   the dispatches rewritten as match statements give the same answers

Synthetic data only: no game files.
"""

import json
import struct

import numpy as np
import pytest

import anim_meta as am
import anim_state_machine as asm
import combat_meta as cm
import fx_meta as fx
import level_meta as lm


def _notes(ex):
    return "\n".join(getattr(ex, "__notes__", []))


# ------------------------------------------------------------------- strict zips
def test_identity_check_rejects_a_world_quat_of_the_wrong_length():
    assert lm._is_identity({"pos": [0, 0, 0], "quat": [0.0, 0.0, 0.0, 1.0]}) is True
    with pytest.raises(ValueError, match="zip"):
        lm._is_identity({"pos": [0, 0, 0], "quat": [0.0, 0.0, 0.0]})
    with pytest.raises(ValueError, match="zip"):
        lm._is_identity({"pos": [0, 0, 0], "quat": [0.0, 0.0, 0.0, 1.0, 0.0]})


def test_root_motion_sample_rejects_keys_of_different_widths():
    assert am._sample([[0.0, 0.0, 0.0], [2.0, 4.0, 6.0]], 0.5) == [1.0, 2.0, 3.0]
    with pytest.raises(ValueError, match="zip"):
        am._sample([[0.0, 0.0, 0.0], [2.0, 4.0]], 0.5)


def test_nearest_cube_keeps_plain_zip_for_stored_positions():
    # a malformed stored position (not 3 values) must not stop the level export
    rec = {"world": {"pos": [0.0, 0.0, 0.0]}, "fragment": "f"}
    cube = {"uid": "u", "world": {"pos": [3.0, 4.0]}, "candidate_at_load": True}
    assert lm._nearest_cube(rec, [cube])["distance"] == 5.0


def test_reaction_rows_compare_only_the_newest_attacks():
    rows = [{"newest_first_ids": [7, 8], "row": 1}]
    assert cm.react(rows, [7, 8, 9, 10]) is rows[0]  # older history is not compared


# --------------------------------------------------------------------- notes
def _kpw(title_chars, payload):
    head = struct.pack("<I4sBII", 5, b"KPWF", 0, 1, title_chars)
    return head + "T".encode("utf-16-le") * title_chars + payload


def test_save_reader_notes_the_offset_of_a_truncated_header():
    data = struct.pack("<I4sBII", 5, b"KPWF", 0, 1, 100) + b"\x00" * 4  # title runs past the file
    with pytest.raises(struct.error) as ei:
        lm.parse_save(data)
    assert "payload size at offset 0xD9" in _notes(ei.value)  # 17 + 2 * 100
    assert "file of 21 bytes" in _notes(ei.value)


def test_save_reader_notes_the_record_that_runs_past_the_payload():
    rec = struct.pack("<4I", 0x11, 0x22, 0x33, 1000)
    data = _kpw(0, struct.pack("<I", len(rec)) + rec)
    with pytest.raises(ValueError, match="record at 21 runs past the payload") as ei:
        lm.parse_save(data)
    n = _notes(ei.value)
    assert n == (
        ".kpw save: record at offset 0x15: entity 00000011, property hash 00000022, type id"
        " 00000033, 1000 words; payload ends at offset 0x25"
    )


def test_save_file_reader_notes_the_path(tmp_path):
    p = tmp_path / "Profile.kpw"
    p.write_bytes(b"not a save file at all")
    with pytest.raises(ValueError, match="no KPWF magic") as ei:
        lm.read_save(str(p))
    assert str(p) in _notes(ei.value)


def test_good_save_reads_without_notes():
    j = lm.parse_save(_kpw(2, struct.pack("<I", 0)))
    assert j["title"] == "TT" and j["records"] == []


def test_scene_reader_notes_the_scene_file(tmp_path):
    missing = str(tmp_path / "Gone.scene")
    with pytest.raises(FileNotFoundError) as ei:
        lm.scene_levels(missing)
    assert "scene file %s" % missing in _notes(ei.value)


def test_level_builder_notes_the_level_and_the_scene(tmp_path):
    scene = tmp_path / "Bare.scene"
    scene.write_bytes(b"\x00" * 8)
    with pytest.raises(ValueError, match="no load block 0000abcd") as ei:
        lm.build_level(str(scene), "Bordello", "0000abcd")
    n = _notes(ei.value)
    assert "level Bordello (load block 0000abcd)" in n and str(scene) in n


def test_reapplyable_scan_notes_the_fragment(tmp_path, monkeypatch):
    import kapow_fragment

    frag = tmp_path / "extracted" / "A" / "Hud.fragment"
    frag.parent.mkdir(parents=True)
    frag.write_bytes(b"\x00" * 64)

    def broken(head, order):
        raise struct.error("bad header")

    monkeypatch.setattr(kapow_fragment, "parse_header", broken)
    monkeypatch.setattr(lm, "_REAPPLY", {})
    with pytest.raises(struct.error, match="bad header") as ei:
        lm.reapplyable_fragments(str(tmp_path))
    assert "header of fragment %s" % frag in _notes(ei.value)


def test_fragment_reads_note_the_fragment_of_an_error_they_let_through(tmp_path, monkeypatch):
    """SoundDB.nodes (the fragment reader of sound_meta, combat_meta and fx_meta) logs
    a damaged fragment and reads it as empty, as before; any other error goes through
    with a note naming the fragment."""
    import kapow_json
    import sound_meta as sm

    rel = "TNT/Combat/Combos.fragment"
    path = str(tmp_path / "Combos.fragment")
    logged = []
    db = sm.SoundDB(str(tmp_path), logged.append)
    db._files, db._stems = {rel.lower(): (path, rel)}, {}

    def damaged(p):
        raise KeyError("x")

    monkeypatch.setattr(kapow_json, "load_fragment", damaged)
    assert db.nodes(rel) == {} and logged == ["  sound_meta: %s: 'x'" % rel]

    def broken(p):
        raise IndexError("chunk 3 of 2")

    db._trees.clear()
    monkeypatch.setattr(kapow_json, "load_fragment", broken)
    with pytest.raises(IndexError, match="chunk 3 of 2") as ei:
        db.nodes(rel)
    assert _notes(ei.value) == "sound_meta: fragment %s (%s)" % (rel, path)
    # combat_meta (and fx_meta) read their fragments through it
    data = object.__new__(cm.CombatData)
    data.db, data.extract_out = db, str(tmp_path)
    monkeypatch.setattr(data, "_fragments", lambda: [rel])
    db._trees.clear()
    with pytest.raises(IndexError) as ei:
        data._load()
    assert _notes(ei.value) == "sound_meta: fragment %s (%s)" % (rel, path)


def test_anim_meta_table_readers_note_the_path(tmp_path):
    bad = tmp_path / "anim_meta.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as ei:
        cm.main(["combat_meta.py", str(bad)])
    assert "anim_meta table %s" % bad in _notes(ei.value)
    with pytest.raises(json.JSONDecodeError) as ei:
        fx.build(str(tmp_path), str(bad))
    assert "fx_meta: anim_meta table %s" % bad in _notes(ei.value)


def test_clip_reader_notes_the_clip_and_its_byte_order(tmp_path):
    clip = tmp_path / "RSH_x.animation"
    clip.write_bytes(b"abcd")
    with pytest.raises(struct.error) as ei:
        am.clip_facts(str(clip))
    n = _notes(ei.value)
    assert str(clip) in n and "4 bytes" in n and "little-endian (PC)" in n


def test_class_reader_notes_the_fragment(tmp_path):
    missing = str(tmp_path / "AnimationClassX.fragment")
    with pytest.raises(FileNotFoundError) as ei:
        am.load_class_tree(missing)
    assert "AnimationClass fragment %s" % missing in _notes(ei.value)


def test_bind_readers_note_the_bind_file(tmp_path):
    bind = tmp_path / "bind_rsh_file_v1.npz"
    bind.write_bytes(b"this is not an npz archive")
    with pytest.raises(Exception) as ei:
        am.skeletons(str(tmp_path))
    assert "bind skeleton %s" % bind in _notes(ei.value)
    with pytest.raises(Exception) as ei:
        am._ContactCheck(str(tmp_path))._load(str(tmp_path / "RSH_a.animation"))
    n = _notes(ei.value)
    assert "bind skeleton %s" % bind in n and "RSH_a.animation" in n


# --------------------------------------------------------------------- match
def test_save_values_by_type():
    f = struct.unpack("<I", struct.pack("<f", 1.5))[0]
    assert lm._save_value("truth", [1], 0) == (True, 1)
    assert lm._save_value("integer", [0xFFFFFFFF], 0) == (-1, 1)
    assert lm._save_value("number", [f], 0) == (1.5, 1)
    assert lm._save_value("vector", [f, f, f, 9], 0) == ([1.5, 1.5, 1.5], 3)
    assert lm._save_value("quaternion", [f] * 4, 0) == ([1.5] * 4, 4)
    assert lm._save_value("Entity", [0xAB], 0) == ("000000ab", 1)
    raw = struct.unpack("<2I", b"abc\x00\x00\x00\x00\x00")
    assert lm._save_value("string", [2, *raw], 0) == ("abc", 3)
    assert lm._save_value("list(list(integer))", [2, 1, 5, 0], 0) == ([[5], []], 4)
    with pytest.raises(ValueError, match="list count"):
        lm._save_value("list(truth)", [99], 0)
    with pytest.raises(ValueError, match="mystery"):
        lm._save_value("mystery", [0], 0)


def test_damage_slots_by_case():
    pose = next(p for p in range(64) if fx.hit_position(p) == 0)
    got = {c: fx.damage_slots(pose, c) for c in ("uber", "kill", "wood", "steel", "sharp")}
    assert got["uber"][0] == "headuber" and got["kill"][0] == "headkill"
    assert got["wood"][0] == "headweaponwood" and got["steel"][0] == "headweaponsteel"
    assert got["sharp"][0] == "sharpweapon"
    taser = fx.damage_slots(pose, "taser")
    assert taser[:2] == ["effect_id:%d" % fx.TASER_EFFECT_ID, "headweaponsteel"]
    assert fx.damage_slots(pose)[0] in ("headfast", "headheavy")


def _crit(kind, **props):
    n = asm.Node("1", asm.CLS_CRIT, "{criteria: SOMETHING}")
    n.props.update(m_ianimationcriteria=kind, **props)
    return n


def test_criterion_text_by_kind():
    v = dict(m_ianimationvalue=0, m_nintervalmin=1.0, m_nintervalmax=2.0)
    assert "in [1;2[" in cm.render_criterion(_crit(asm.CRIT_VALUE, m_iintervaltype=0, **v))
    assert "< 2" in cm.render_criterion(_crit(asm.CRIT_VALUE, m_iintervaltype=1, **v))
    assert ">= 1" in cm.render_criterion(_crit(asm.CRIT_VALUE, m_iintervaltype=2, **v))
    assert "interval type 7" in cm.render_criterion(_crit(asm.CRIT_VALUE, m_iintervaltype=7, **v))
    assert cm.render_criterion(_crit(asm.CRIT_ACTION)).startswith("ACTION ")
    assert cm.render_criterion(_crit(asm.CRIT_ALL_OF)) == "ALL OF()"
    assert cm.render_criterion(_crit(asm.CRIT_ANY_OF, m_tnot=True)) == "NOT ANY OF()"
    assert cm.render_criterion(_crit(asm.CRIT_PLAY_DONE)) == "SOMETHING"
    neg = _crit(asm.CRIT_PLAY_DONE, m_tnot=True)
    neg.name = "{criteria: NOT DONE}"
    assert cm.render_criterion(neg) == "NOT DONE"


def test_volume_shapes_and_child_firing():
    class Lv:
        enabled = {}

        def brief(self, n):
            return {}

        def placement(self, n):
            return {}

    lv = Lv()
    shapes = []
    for nat in ("CollisionBoxNode", "CollisionSphereNode", "CollisionCapsuleNode", "Other"):
        n = asm.Node("1", "X", "v")
        n.type = "X(%s)" % nat
        lv.enabled[id(n)] = True
        shapes.append(lm._volume(lv, n).get("shape"))
    assert shapes == ["box", "sphere", "capsule", None]

    def node(cls, **props):
        n = asm.Node("1", cls, "a")
        n.props.update(props)
        return n

    assert lm._child_when(node("TriggerActionDelay", m_ndelaynumber2=0.5), 2) == ("delay", 0.5)
    assert lm._child_when(node("TriggerActionSound", _tchildrenafter=True), 0)[0] == "after_sound"
    assert lm._child_when(node("TriggerActionSound"), 0)[0] == "immediate"
    assert lm._child_when(node("TriggerActionCamera", _iaction=0), 0)[0] == "tour_refire"
    assert lm._child_when(node("TriggerActionCamera", _iaction=1), 0)[0] == "immediate"


def test_button_code_names_read_the_bundled_table_once():
    first = lm.input_code_name("KEYBOARD_MOUSE", 257)
    assert first is not None and first == lm.input_code_name("KEYBOARD_MOUSE", 257)
    assert lm._input_codes() is lm._input_codes()


def test_bind_npz_round_trip_still_reads(tmp_path):
    np.savez(tmp_path / "bind_rsh_file_v1.npz", names=np.array(["a", "b"]), par=np.array([-1, 0]))
    sk = am.skeletons(str(tmp_path))
    assert sk["rsh"]["joint_count"] == 2
