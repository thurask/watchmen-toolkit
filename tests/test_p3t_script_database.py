"""script_database: the baked script name database (`database.bin`).

Layout read from the loader 0x47c5f5: two sections of [u32 len][text], each led by a
count; an entry longer than 0x3fe aborts the load.  Synthetic databases only."""

import json
import os
import struct
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import kapow_fragment as kf
import kapow_props as kp
import script_database as sd

PROPS = ["_ecamera:Entity", "m_ntargetrangemax:number", "_tdebugtmp01:truth", "llist:list(Entity)"]
MSGS = [
    "command_lock_player(entity)",
    "command_allow_fall_behind:truth",
    "command_get_list(truth,list(list(integer)),vector):list(Entity)",
    "command_pre_transfer",
]


@pytest.mark.parametrize("order", ["<", ">"])
def test_roundtrip_both_byte_orders(order):
    raw = sd.build(PROPS, MSGS, order)
    assert sd.detect_order(raw) == order
    db = sd.parse(raw)
    assert db["format"] == "kapow-script-database/1"
    assert db["byte_order"] == ("little" if order == "<" else "big")
    assert db["exact"] and db["consumed"] == db["size"] == len(raw)
    assert (db["property_count"], db["message_count"]) == (4, 4)
    assert db["unterminated_entries"] == 0
    assert [p["name"] + ":" + p["type"] for p in db["properties"]] == PROPS
    assert [m["text"] for m in db["messages"]] == MSGS


def test_ids_are_the_name_hash_of_the_text_before_the_colon():
    db = sd.parse(sd.build(PROPS, MSGS))
    p = db["properties"][2]
    assert p == {"index": 2, "name": "_tdebugtmp01", "type": "truth", "hash": "40cb4063"}
    assert int(p["hash"], 16) == kp.name_hash("_tdebugtmp01")
    m = db["messages"][1]
    assert m["name"] == "command_allow_fall_behind" and m["returns"] == "truth"
    assert m["args"] is None
    assert int(m["hash"], 16) == kp.name_hash("command_allow_fall_behind")
    m = db["messages"][0]
    assert m["args"] == ["entity"] and m["returns"] is None
    assert int(m["hash"], 16) == kp.name_hash("command_lock_player(entity)")
    m = db["messages"][2]
    assert m["args"] == ["truth", "list(list(integer))", "vector"]
    assert m["returns"] == "list(Entity)"


def test_trailing_bytes_are_reported_not_hidden():
    raw = sd.build(PROPS, MSGS) + b"\x00\x00"
    db = sd.parse(raw)
    assert not db["exact"] and db["size"] - db["consumed"] == 2


def test_length_limit_is_the_engines():
    ok = "a" * (sd.MAX_LEN - 3) + ":x"  # with the NUL: exactly 0x3fe
    db = sd.parse(sd.build([ok], []))
    assert db["exact"] and len(db["properties"][0]["name"]) == sd.MAX_LEN - 3
    raw = struct.pack("<II", 1, sd.MAX_LEN + 1) + b"a" * (sd.MAX_LEN + 1) + struct.pack("<I", 0)
    with pytest.raises(sd.DatabaseError):
        sd.parse(raw, "<")
    with pytest.raises(sd.DatabaseError):
        sd.build(["b" * sd.MAX_LEN], [])


@pytest.mark.parametrize("raw", [b"", b"\x01\x00", struct.pack("<I", 5), b"\xff" * 64])
def test_garbage_is_refused(raw):
    with pytest.raises(sd.DatabaseError):
        sd.parse(raw)


def test_truncated_file_is_refused():
    raw = sd.build(PROPS, MSGS)
    with pytest.raises(sd.DatabaseError):
        sd.parse(raw[:-3])


def test_lookup_by_hash_key_and_name():
    db = sd.parse(sd.build(PROPS, MSGS))
    for key in (
        0x40CB4063,
        "40cb4063",
        "0x40CB4063",
        "key_40cb4063",
        "_tdebugtmp01",
        "_TDEBUGTMP01",
    ):
        hit = sd.lookup(db, key)
        assert [h["name"] for h in hit] == ["_tdebugtmp01"], key
    assert sd.lookup(db, "nosuchname") == []
    assert sd.lookup(db, "command_lock_player(entity)", "messages")[0]["index"] == 0


def test_type_histogram_and_compare():
    db = sd.parse(sd.build(PROPS + ["_efoo:Entity"], []))
    hist = sd.type_histogram(db)
    assert list(hist.items())[0] == ("Entity", 2) and hist["truth"] == 1
    table = {
        kp.name_hash("_ecamera"): "_ecamera",  # agrees
        kp.name_hash("llist"): "lList",  # case only
        kp.name_hash("_efoo"): "_egoo_wrong",  # another spelling under the hash
        0x12345678: "onlyInTable",
    }
    c = sd.compare_names(db, table)
    assert c["counts"] == {
        "agree": 1,
        "case_only": 1,
        "different": 1,
        "missing_in_table": 2,
        "table_only": 1,
    }
    assert c["case_only"][0]["table"] == "lList" and c["case_only"][0]["database"] == ["llist"]
    assert c["table_only"] == [{"hash": "12345678", "table": "onlyInTable"}]


def test_the_seven_part1_keys_hash_to_the_names_the_part1_database_stores():
    """Spellings and types as stored in the Part 1 `database.bin` (PC, the Xbox 360
    devkit build and PS3 agree); the test pins that the fragment table carries exactly
    these, each under its own hash."""
    part1 = {
        0x0CDB31BF: ("_nobstructionfactor", "number"),
        0x57A8BE19: ("_idebugrunthroughmode", "integer"),
        0x40CB4063: ("_tdebugtmp01", "truth"),
        0x56EEC9BF: ("_nsteplengthinmeters", "number"),
        0xF89F0453: ("_ntimeprstepinsec", "number"),
        0xB29CF82F: ("_tstartenabled", "truth"),
        0xCEACAED4: ("_tuseteleport", "truth"),
    }
    db = sd.parse(sd.build(["%s:%s" % nt for nt in part1.values()], []))
    for h, nt in part1.items():
        assert [(e["name"], e["type"]) for e in sd.lookup(db, h)] == [nt]
        assert kf.PART1_KEYS[h] == nt and kf.NAMES[h] == nt


def test_cli_dump_and_find(tmp_path, capsys):
    src = tmp_path / "database.bin"
    src.write_bytes(sd.build(PROPS, MSGS))
    out = tmp_path / "db.json"
    assert sd.main([str(src), str(out), "--find", "key_40cb4063", "--find", "nothere"]) == 0
    text = capsys.readouterr().out
    assert "4 properties, 4 messages, little-endian" in text
    assert "_tdebugtmp01:truth" in text and "nothere: not in the database" in text
    j = json.loads(out.read_text(encoding="utf-8"))
    assert j["exact"] and j["properties"][0]["name"] == "_ecamera"
    src.write_bytes(sd.build(PROPS, MSGS) + b"junk")
    assert sd.main([str(src)]) == 1
    assert "NOT consumed exactly" in capsys.readouterr().out
    assert sd.main([str(tmp_path / "missing.bin")]) == 1
