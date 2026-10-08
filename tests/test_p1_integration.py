"""Seams of the 2026-10-05 pass: the content revision of the cached animation
table, the registered spellings of the property dictionary, and the readers
that must not depend on a letter case the hash does not see.

Revision        characters_export.anim_meta_is_current, anim_meta.REVISION
Spellings       gen_data.apply_registered_spellings / registered_names.json
                (native RegisterMembers functions of the Part 2 PC executable);
                Sprite registers `is3D` (0x4c7801), the sound assets `is3d`
Synthetic data only."""

import json
import pathlib
import os
import pickle
import struct
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import anim_meta as am
import anim_state_machine as asm
import characters_export as ce
import combat_meta as cm
import face_rule
import fx_meta as fx
import gen_data
import kapow_fragment as kf
import kapow_props as kp
import level_meta as lm
import materials as mt
import sound_meta as sm

WLIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib")


# ------------------------------------------------------------ cached table
def _current():
    return {
        "format": am.FORMAT,
        "revision": am.REVISION,
        "face_format": face_rule.FACE_FORMAT,
        "combat_format": cm.COMBAT_FORMAT,
        "fx_format": fx.FORMAT,
    }


@pytest.mark.usefixtures("engine_frame")
def test_a_table_without_the_current_revision_is_rebuilt(tmp_path, monkeypatch):
    """A table written before a rule was added has every format marker of today:
    only the revision tells it apart, and a resumed export must not reuse it."""
    monkeypatch.setattr(face_rule, "find_face_fragments", lambda ex: {"Enemy01Face": "x"})
    cur = _current()
    assert ce.anim_meta_is_current(cur, "x") is True
    older = dict(cur)
    del older["revision"]
    assert ce.anim_meta_is_current(older, "x") is False
    assert ce.anim_meta_is_current(dict(cur, revision=am.REVISION + 1), "x") is False
    assert ce.anim_meta_is_current(dict(cur, revision=str(am.REVISION)), "x") is False

    out = tmp_path / "CHARS"
    out.mkdir()
    (out / "anim_meta.json").write_text(json.dumps(dict(older, marker="cached")))
    built = []

    def build(extract_out, binds=None):
        built.append(extract_out)
        return dict(_current(), marker="new")

    monkeypatch.setattr(am, "build", build)
    monkeypatch.setattr(am, "find_class_fragments", lambda ex: {"Enemy01": "x"})
    monkeypatch.setattr(am, "summary", lambda m: "summary")
    got = ce.animation_meta(str(tmp_path), str(out))
    assert got["marker"] == "new" and len(built) == 1
    assert json.loads((out / "anim_meta.json").read_text())["revision"] == am.REVISION


def test_the_format_markers_name_the_layout_and_are_not_counted_up():
    """Every block added since 1.3.0 keeps its first marker; content is told
    apart by the revision."""
    assert isinstance(am.REVISION, int) and am.REVISION >= 1
    assert am.FORMAT == "watchmen-anim-meta/2"
    assert cm.COMBAT_FORMAT == "watchmen-combat-meta/1"
    assert fx.FORMAT == "watchmen-fx-meta/1"
    assert lm.FORMAT == "watchmen-level-meta/1"
    grades = mt.level_grades(os.path.join(os.path.dirname(__file__), "no_such_dir"), lambda p: {})
    assert grades["format"] == "watchmen-grade-meta/1" and "platform_adjustment" in grades


# -------------------------------------------------------------- spellings
def test_registered_names_table_is_consistent():
    reg = gen_data.load_registered_names()
    assert len(reg["names"]) == 1224
    for h, sp in reg["names"].items():
        for s in sp:
            assert kp.name_hash(s) == h
    assert sorted(reg["keep"].values()) == ["PLATFORM", "Scene", "physicsTimepassed"]
    two = {h for h, sp in reg["names"].items() if len(sp) > 1}
    assert two == set(reg["generic"]) and len(two) == 4
    assert reg["generic"][kp.name_hash("is3d")] == "is3d"
    assert reg["class_overrides"] == {"Sprite": {kp.name_hash("is3D"): "is3D"}}


def test_every_registered_name_is_spelt_as_registered_in_the_dictionary():
    """namedict()[name_hash(n)] == n for every name a native class registers,
    outside the three names the dictionary keeps and the four hashes two classes
    spell differently (there the dictionary has the class-free choice)."""
    reg = gen_data.load_registered_names()
    d = kp.namedict()
    n = 0
    for h, sp in reg["names"].items():
        if h in reg["keep"]:
            assert d[h] == reg["keep"][h]
        elif len(sp) == 1:
            assert d[h] == next(iter(sp))
            n += 1
        else:
            assert d[h] == reg["generic"][h] and d[h] in sp
    assert n == 1224 - 3 - 4
    for name in ("animation", "mass", "movementType", "textRes", "priority", "duration"):
        assert d[kp.name_hash(name)] == name
    for name in ("texture", "position", "speed", "force", "ambient", "factor"):
        assert d[kp.name_hash(name)] == name  # the capitalised variants were editor captions
    assert d[kp.name_hash("platform")] == "PLATFORM" and d[kp.name_hash("scene")] == "Scene"
    assert d[kp.name_hash("physicstimepassed")] == "physicsTimepassed"
    assert d[kp.name_hash("IS3D")] == "is3d"


def test_respelling_the_shipped_dictionary_changes_nothing_and_is_byte_stable():
    path = os.path.join(WLIB, "prop_hash_dict.pkl")
    raw = pathlib.Path(path).read_bytes()
    d = pickle.loads(raw)
    assert len(d) == 23770 and all(kp.name_hash(s) == h for h, s in d.items())
    before = dict(d)
    ch = gen_data.apply_registered_spellings(d)
    assert ch == {"respelled": [], "added": []} and d == before
    assert list(d) == list(before)  # the order is part of the file
    assert pickle.dumps(d, protocol=gen_data.PROP_DICT_PICKLE_PROTOCOL) == raw


def test_apply_registered_spellings_respells_adds_and_keeps():
    h = kp.name_hash
    table = {
        h("Animation"): "Animation",
        h("PLATFORM"): "PLATFORM",
        h("other"): "Other",
        h("deallocate"): "DeAllocate",
    }
    ch = gen_data.apply_registered_spellings(table)
    assert table[h("animation")] == "animation" and table[h("platform")] == "PLATFORM"
    assert table[h("other")] == "Other"  # not a registered name: untouched
    assert table[h("deallocate")] == "deallocate"
    assert (h("animation"), "Animation", "animation") in ch["respelled"]
    assert all(old != new for _h, old, new in ch["respelled"])
    assert [x for x, _s in ch["added"]] == sorted(x for x, _s in ch["added"])
    assert len(table) == 1224 - 3 + 2  # the registered names but the kept three, + PLATFORM, Other
    # with an executable only the spellings found in it are used
    small = {h("Mass"): "Mass", h("Volume"): "Volume"}
    ch = gen_data.apply_registered_spellings(small, exe_bytes=b"\0mass\0Volume\0")
    assert small == {h("mass"): "mass", h("volume"): "Volume"} and ch["added"] == []


def test_build_prop_dict_prefers_the_registered_spelling(tmp_path):
    exe = tmp_path / "fake.exe"
    exe.write_bytes(
        b"\0Animation\0animation\0PLATFORM\0platform\0Scene\0scene\0textres\0textRes\0"
        b"MaxDistance\0maxDistance\0Zebra\0zebra\0"
    )
    d = gen_data.build_prop_dict(str(exe))
    h = kp.name_hash
    assert d[h("animation")] == "animation" and d[h("textres")] == "textRes"
    assert d[h("maxdistance")] == "maxDistance"
    assert d[h("platform")] == "PLATFORM" and d[h("scene")] == "Scene"  # kept
    assert d[h("zebra")] == "zebra"  # no registration: the rank decides, as before
    assert h("mass") not in d  # a registered name the executable does not hold


def _bag(cls, recs):
    name = cls.encode("latin1") + b"\0"
    b = struct.pack("<I", len(name)) + name + struct.pack("<I", 1)
    for key, typ, val in recs:
        b += struct.pack("<4Ii", 7, kp.name_hash(key), kp.name_hash(typ), 1, val)
    return b


def test_generic_walk_uses_the_class_spelling_only_for_sprite():
    recs = [("IS3D", "truth", 1), ("ANIMATION", "integer", 2), ("PLATFORM", "integer", 3)]
    sprite = kp.parse(_bag("Sprite", recs))["blocks"][0]
    sound = kp.parse(_bag("SoundAsset", recs))["blocks"][0]
    assert [r["key"] for r in sprite["props"]] == ["is3D", "animation", "PLATFORM"]
    assert [r["key"] for r in sound["props"]] == ["is3d", "animation", "PLATFORM"]
    assert kp.class_prop_name("Sprite", kp.name_hash("is3d")) == "is3D"
    assert kp.class_prop_name("SoundAsset", kp.name_hash("is3d")) is None
    # a caller's own name table is used as given
    own = kp.parse(_bag("Sprite", recs), keynames={kp.name_hash("is3d"): "X"})["blocks"][0]
    assert own["props"][0]["key"] == "X"


def test_fragment_key_table_has_the_registered_spellings():
    """kapow_fragment.NAMES spells a key the way the executable registers it; the
    readers of fragment nodes still look names up without regard to case, because a
    .fragment.json written by an older toolkit keeps the older spelling."""
    assert kf.NAMES[kp.name_hash("priority")][0] == "priority"
    assert kf.NAMES[kp.name_hash("textres")][0] == "textRes"
    for spelling in ("Priority", "priority", "PRIORITY"):
        n = asm.Node("1", "SoundAsset", "x")
        n.props[spelling] = 5
        assert sm._prop_any_case(n, "priority") == 5
    for spelling in ("textres", "textRes"):
        n = asm.Node("1", "SubtitleSlot", "x")
        n.props[spelling] = "/Localize/A_uk.txt"
        assert lm._prop_any_case(n, "textRes") == "/Localize/A_uk.txt"
    assert sm._prop_any_case(asm.Node("1", "SoundAsset", "x"), "priority") is None
