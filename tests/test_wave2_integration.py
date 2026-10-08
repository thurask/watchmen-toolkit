"""Seams between the features of 1.4.0: the cached animation table, and the last
fragment key that had no name."""

import pytest
import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_meta
import characters_export as ce
import face_rule
import kapow_fragment as kf
import kapow_props


def _cached_table(tmp_path, monkeypatch, face_format):
    out = tmp_path / "CHARS"
    out.mkdir()
    # the combat and fx blocks have their own markers (tests/test_feature_seams.py)
    import combat_meta
    import fx_meta

    table = {
        "format": anim_meta.FORMAT,
        "revision": anim_meta.REVISION,
        "marker": "cached",
        "combat_format": combat_meta.COMBAT_FORMAT,
        "fx_format": fx_meta.FORMAT,
    }
    if face_format:
        table["face_format"] = face_format
    (out / "anim_meta.json").write_text(json.dumps(table))
    built = []

    def build(extract_out, binds=None):
        built.append(extract_out)
        return {
            "format": anim_meta.FORMAT,
            "revision": anim_meta.REVISION,
            "face_format": face_rule.FACE_FORMAT,
            "marker": "new",
        }

    monkeypatch.setattr(anim_meta, "build", build)
    monkeypatch.setattr(anim_meta, "find_class_fragments", lambda ex: {"Enemy01": "x"})
    monkeypatch.setattr(anim_meta, "summary", lambda m: "summary")
    monkeypatch.setattr(face_rule, "find_face_fragments", lambda ex: {"Enemy01Face": "x"})
    got = ce.animation_meta(str(tmp_path), str(out))
    return got, built, json.loads((out / "anim_meta.json").read_text())


@pytest.mark.usefixtures("engine_frame")  # pins the engine numbers; true frame: test_frame.py
def test_a_cached_table_with_the_current_face_format_is_reused(tmp_path, monkeypatch):
    got, built, on_disk = _cached_table(tmp_path, monkeypatch, face_rule.FACE_FORMAT)
    assert got["marker"] == "cached" and built == [] and on_disk["marker"] == "cached"


def test_a_cached_table_with_an_older_face_format_is_rebuilt(tmp_path, monkeypatch):
    """An output folder of an earlier build (face format 1: no talk clips, no
    speech categories) must not hand its table to the new GLBs."""
    assert face_rule.FACE_FORMAT == "watchmen-face/2"
    got, built, on_disk = _cached_table(tmp_path, monkeypatch, "watchmen-face/1")
    assert got["marker"] == "new" and len(built) == 1
    assert on_disk["face_format"] == face_rule.FACE_FORMAT


def test_a_cached_table_without_a_face_block_is_rebuilt(tmp_path, monkeypatch):
    got, built, _ = _cached_table(tmp_path, monkeypatch, None)
    assert got["marker"] == "new" and len(built) == 1


def test_zone_trigger_key_has_its_name_and_is_an_entity():
    """0x0991b0d4 was the one standard key without a name ("key_0991b0d4",
    read as an integer).  It is CharacterGroup.m_ezonetrigger, an entity
    reference: [1] = none, [3][node id] = a node of the same fragment.  Read as
    an integer, the id of the 22 set references was taken for an unknown key."""
    h = kapow_props.name_hash("m_ezonetrigger")
    assert h == 0x0991B0D4
    assert kf.NAMES[h] == ("m_ezonetrigger", "Entity")
    assert not [n for n, _t in kf.NAMES.values() if n == "key_0991b0d4"]
    assert kf.NAMES[kapow_props.name_hash("m_emodelcollbash1h")][1] == "Entity"  # same kind
