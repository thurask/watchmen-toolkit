"""`watchmen scriptdb`: the script name database reader behind the command line, and the
lookup of a key that could be a hash or a name.  Synthetic database files only."""

import json
import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kapow_props as kp
import script_database as sd
import watchmen

PROPS = ["_tuseteleport:truth", "_nsteplengthinmeters:number", "deadbeef:integer"]
MSGS = ["command_lock_player(entity)", "getspeed():number"]


def _db(tmp_path, extra=b""):
    p = tmp_path / "database.bin"
    p.write_bytes(sd.build(PROPS, MSGS) + extra)
    return p


def test_scriptdb_is_a_command_with_a_usage_line():
    assert watchmen.USAGE["scriptdb"] == (1, "scriptdb DATABASE.bin [OUT.json] [--find KEY ...]")
    assert "scriptdb DATABASE.bin [OUT.json] [--find KEY ...]" in watchmen.__doc__
    assert "kapow-script-database/1" in watchmen.__doc__


def test_scriptdb_prints_counts_and_writes_the_json(tmp_path, capsys):
    src, out = _db(tmp_path), tmp_path / "db.json"
    assert watchmen.main(["watchmen", "scriptdb", str(src), str(out)]) == 0
    log = capsys.readouterr().out
    assert "3 properties, 2 messages, little-endian" in log and "wrote %s" % out in log
    j = json.loads(out.read_text(encoding="utf-8"))
    assert j["format"] == "kapow-script-database/1"
    assert [e["name"] for e in j["properties"]] == [p.split(":")[0] for p in PROPS]
    assert j["messages"][1]["returns"] == "number"


def test_scriptdb_find_reaches_the_reader_untouched(tmp_path, capsys):
    src = _db(tmp_path)
    key = "key_%08x" % kp.name_hash("_tuseteleport")
    args = ["watchmen", "scriptdb", str(src), "--find", key, "--find", "getspeed()", "--find", "x"]
    assert watchmen.main(args) == 0
    log = capsys.readouterr().out
    assert "%s: %08x  _tuseteleport:truth" % (key, kp.name_hash("_tuseteleport")) in log
    assert "getspeed():number" in log and "x: not in the database" in log


def test_scriptdb_argument_errors(tmp_path, capsys):
    assert watchmen.main(["watchmen", "scriptdb"]) == 2
    assert "usage: watchmen.py scriptdb DATABASE.bin" in capsys.readouterr().out
    assert watchmen.main(["watchmen", "scriptdb", "-h"]) == 0
    assert watchmen.main(["watchmen", "scriptdb", str(tmp_path / "nope.bin")]) == 1
    assert watchmen.main(["watchmen", "scriptdb", str(_db(tmp_path)), "--find"]) == 2
    # a file with bytes after the last message is reported and gives status 1
    assert watchmen.main(["watchmen", "scriptdb", str(_db(tmp_path, b"junk"))]) == 1
    assert "NOT consumed exactly" in capsys.readouterr().out


def test_eight_hex_digits_are_a_hash_first_and_a_name_second():
    db = sd.parse(sd.build(PROPS, MSGS))
    h = kp.name_hash("_tuseteleport")
    # a hash that is in the file, bare or prefixed
    assert [e["name"] for e in sd.lookup(db, "%08x" % h)] == ["_tuseteleport"]
    assert [e["name"] for e in sd.lookup(db, "0x%08x" % h)] == ["_tuseteleport"]
    # a NAME of eight hex digits: no entry has the id 0xdeadbeef, so it is hashed
    assert kp.name_hash("deadbeef") != 0xDEADBEEF
    assert [e["name"] for e in sd.lookup(db, "deadbeef")] == ["deadbeef"]
    # with a prefix it stays a hash, and is not found
    assert sd.lookup(db, "0xdeadbeef") == [] and sd.lookup(db, "key_deadbeef") == []


def test_find_takes_several_values_and_help_points_to_its_doc(tmp_path, capsys):
    p = _db(tmp_path)
    before = sorted(os.listdir(tmp_path))
    assert sd.main([str(p), "--find", "_tuseteleport", "getspeed()"]) == 0
    out = capsys.readouterr().out
    assert "_tuseteleport:truth" in out and "getspeed():number" in out
    assert sorted(os.listdir(tmp_path)) == before
    doc = watchmen.__doc__
    i = doc.index("  scriptdb DATABASE.bin")
    j = doc.index("\n  faces ", i)
    assert "SCRIPT_DATABASE.md" in doc[i:j] and "PARTICLE_FORMAT" not in doc[i:j]
    k = doc.index("  particlemeta ")
    assert "PARTICLE_FORMAT.md" in doc[k:i]
