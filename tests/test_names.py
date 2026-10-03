"""Engine name hash, the re-keyed name tables, reg_dump v2 and fragment key typing.

All offline: the shipped tables are checked for internal consistency (every name
must sit under its own engine hash) and the parser is driven with small synthetic
fragments built here.
"""

import json
import pickle
import re
import struct
import subprocess
import sys
from pathlib import Path

import pytest

import engine_schema as es
import gen_data
import kapow_fragment as kf
import kapow_json as kj
import kapow_props as kp
import watchmenlib as wl

ROOT = Path(__file__).resolve().parent.parent
WLIB = ROOT / "wlib"


# ---------------------------------------------------------------------------
# 1. the fold: bytes & 0xDF (FUN_00423ce8), not str.upper()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        # hashes pushed at registration sites in the exe; all contain characters
        # that str.upper() leaves alone but the engine folds
        ("m_nsupersynclocal1", 0xEE2A40A0),
        ("m_nsupersyncremote1", 0x4CADFB2B),
        ("command_set_achievement_earned(integer)", 0x6EED1060),
        ("command_is_achievement_earned(integer)", 0x13A9D763),
        ("command_game_event(integer,entity,integer,number,entity)", 0xEEE497D4),
        ("FilterExposedProperties(list(propertyinstance))", 0x286B9E96),
        # letters only: unchanged by the fix
        ("name", 0x7282B2A2),
        ("m_neaseinduration", 0xC457385C),
    ],
)
def test_name_hash_matches_engine_constants(name, expected):
    """name_hash reproduces hashes that are immediates in the executable."""
    assert kp.name_hash(name) == expected
    assert wl.kapow_hash(name) == expected


def test_fold_is_and_0xdf_not_upper():
    """Digits and punctuation are folded ('1' -> 0x11, '(' -> 0x08): hashing the
    upper-cased string -- what the toolkit did before -- gives a different value."""
    assert kp.name_fold("aZ_") == "AZ_"
    assert kp.name_fold("0129(,):") == "\x10\x11\x12\x19\x08\x0c\x09\x1a"
    for name in ("m_nsupersynclocal1", "command_use(entity)", "color4RGB"):
        assert kp.name_hash(name) != kp.kapow_hash(name.upper())
    # the raw primitive is untouched (FUN_00423ca1 hashes bytes as given)
    assert kp.kapow_hash("POSITION") == 0x15DE4806
    assert kp.name_hash("position") == kp.name_hash("PoSiTiOn") == 0x15DE4806


def test_cli_hash_command_uses_the_engine_fold():
    r = subprocess.run(
        [sys.executable, str(ROOT / "watchmen.py"), "hash", "m_nsupersynclocal1"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert r.returncode == 0 and r.stdout.strip() == "ee2a40a0"


def test_string_harvest_keys_by_name_hash(tmp_path):
    """gen_data.build_prop_dict (the prop_hash_dict generator) must file names
    under the engine hash, digits included."""
    exe = tmp_path / "fake.exe"
    exe.write_bytes(b"\0testSound1\0aspectRatio\0")
    d = gen_data.build_prop_dict(str(exe))
    assert d[kp.name_hash("testSound1")] == "testSound1"
    assert d[kp.name_hash("aspectRatio")] == "aspectRatio"
    assert kp.kapow_hash("TESTSOUND1") not in d


# ---------------------------------------------------------------------------
# 2. shipped tables are keyed by the engine hash
# ---------------------------------------------------------------------------


def _keys():
    with open(WLIB / "kapow_fragment_keys.pkl", "rb") as fh:
        return pickle.load(fh)


@pytest.mark.parametrize("table", ["keytable", "stdkeys", "promoted", "nameable"])
def test_fragment_key_tables_are_keyed_by_name_hash(table):
    """Every name sits under name_hash(name). Before the re-key 480 keytable and
    16,293 nameable entries (anything with a digit, space or punctuation) were
    filed under hash(upper(name)), which never occurs in game data."""
    tab = _keys()[table]
    assert tab
    for h, v in tab.items():
        name = v[0] if isinstance(v, tuple) else v
        assert kp.name_hash(name) == h, (table, name)


def test_prop_hash_dict_is_keyed_by_name_hash():
    with open(WLIB / "prop_hash_dict.pkl", "rb") as fh:
        d = pickle.load(fh)
    assert len(d) > 20000
    assert all(kp.name_hash(n) == h for h, n in d.items())
    assert d[kp.name_hash("testSound1")].lower() == "testsound1"


def test_keys_export_import_round_trip(tmp_path):
    kd = _keys()
    j = json.loads(json.dumps(gen_data.keys_export(str(WLIB / "kapow_fragment_keys.pkl"))))
    assert gen_data.keys_import(j) == kd


def test_digit_names_resolve_in_the_parser_tables():
    """The transition sync markers were key_ee2a40XX/key_4cadfbXX before."""
    assert kf.NAMES[0xEE2A40A0] == ("m_nsupersynclocal1", "number")
    assert kf.NAMES[0x4CADFB2B] == ("m_nsupersyncremote1", "number")
    assert kf.NAMES[kp.name_hash("m_nvalue02")][0] == "m_nvalue02"


def test_builtin_node_properties_are_typed():
    """Built-in (native) node properties get the type of the registration wrapper
    they go through (0x505514 integer, 0x505553 biginteger, 0x505592 number,
    0x5055d1 string, 0x505610 truth, 0x50564f vector, 0x50568e quaternion,
    entity wrappers) instead of being size-guessed."""
    want = {
        "aspectRatio": "number",
        "parentLink": "integer",
        "includeInAO": "truth",
        "spatialTreeStrategy": "integer",
        "pivotSheet_Id": "biginteger",
        "assetName": "string",
        "lightColorRGB": "vector",
        "childSpaceOrient": "quaternion",
        "gfxNode": "Entity",
    }
    for name, typ in want.items():
        assert kf.NAMES[kp.name_hash(name)] == (name, typ)
    # the hand-written STDTYPES agree with the wrapper-derived types
    for name, typ in kf.STDTYPES.items():
        assert kf.NAMES[kp.name_hash(name)] == (name, typ)


# ---------------------------------------------------------------------------
# 3. command signatures + reg_dump v2
# ---------------------------------------------------------------------------

SIG_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\([a-z0-9_(),]+\)$")


def test_command_signature_table_rehashes():
    raw = json.loads((WLIB / "command_signatures.json").read_text(encoding="utf-8"))
    sigs = raw["signatures"]
    assert len(sigs) == 830
    for k, s in sigs.items():
        assert kp.name_hash(s) == int(k, 16), s
        assert SIG_RE.match(s), s
    assert gen_data.load_command_signatures() == {int(k, 16): v for k, v in sigs.items()}


def test_signature_loader_drops_entries_that_do_not_hash(tmp_path):
    p = tmp_path / "sig.json"
    p.write_text(
        json.dumps(
            {"signatures": {"0x6eed1060": "command_set_achievement_earned(integer)", "0x1": "x(y)"}}
        )
    )
    assert gen_data.load_command_signatures(str(p)) == {
        0x6EED1060: "command_set_achievement_earned(integer)"
    }


def test_reg_dump_v2_shape_and_counts():
    reg = es.reg()
    props = [p for c in reg for p in c["props"]]
    cmds = [m for c in reg for m in c["commands"]]
    assert (len(reg), len(props), len(cmds)) == (441, 5090, 6630)
    assert len({p["hash"] for p in props}) == 3695
    for p in props:
        assert set(p) == {"va", "hash", "name", "default", "ui", "flags", "typeidx"}
        assert kp.name_hash(p["name"]) == int(p["hash"], 16)
        assert p["ui"] is None or "=" in p["ui"]  # ui strings are control=...|caption=...
        assert p["default"] is None or "control=" not in p["default"]
    slots = {}
    for m in cmds:
        assert set(m) == {
            "va",
            "name",
            "hash",
            "handler",
            "slot",
            "kind",
            "arg3",
            "typeidx",
            "signature",
        }
        assert m["name"] and m["handler"] and m["kind"] in (1, 3)
        slots[m["slot"]] = slots.get(m["slot"], 0) + 1
        if m["slot"] == "command":
            # hash-addressable: hash == name_hash(signature), signature extends the name
            assert kp.name_hash(m["signature"]) == int(m["hash"], 16)
            assert m["signature"] == m["name"] or m["signature"].startswith(m["name"] + "(")
        else:
            # state functions / script methods carry 0xFFFFFFFF = not addressable
            assert m["hash"] is None and m["signature"] is None and m["arg3"] == -1
    assert slots == {"command": 3939, "state": 841, "method": 1850}
    # short names and zero-top-byte hashes the v1 dumper lost
    names = {m["name"] for m in cmds}
    assert {"Init", "init", "ipow"} <= names
    assert any(m["hash"] == "0xc837a9" for m in cmds)


def test_engine_schema_views():
    by = es.commands_by_hash()
    e = by[0x6EED1060]
    assert e["signature"] == "command_set_achievement_earned(integer)"
    assert "AchievementCtrl" in e["classes"]
    assert len(by) == 1696
    info = es.prop_info("key_ee2a40a0")
    assert info["name"] == "m_nsupersynclocal1"
    assert es.caption(0xEE2A40A0) == "Sync marker 1 (local)"
    # short default strings ("0", "true") were dropped by the v1 dumper
    assert any(isinstance(v, bool) for v in es.defaults("AnimationStateWM").values())


def test_sweep_resolves_register_held_arguments():
    """`push 3; pop ebx`, `or ebp,-1`, `xor esi,esi` feed call arguments as
    constants; the v1 scan saw only immediates and so lost them."""
    capstone = pytest.importorskip("capstone")
    base = 0x401000
    code = (
        b"\x6a\x03\x5b"  # push 3 ; pop ebx
        b"\x83\xcd\xff"  # or ebp,-1
        b"\x33\xf6"  # xor esi,esi
        b"\x56"  # push esi            (arg5)
        b"\x68\x78\x56\x34\x12"  # push 0x12345678     (arg4)
        b"\x55"  # push ebp            (arg3) = -1
        b"\x53"  # push ebx            (arg2) = 3
        b"\x68\x40\x68\x9e\x00"  # push 0x9e6840       (arg1)
        b"\x8b\xcf"  # mov ecx,edi
        b"\xe8\x00\x00\x00\x00"  # call +0
    )
    call_va = base + len(code) - 5
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    out = gen_data.sweep_call_args(md, code, base, base, base + len(code), {call_va})
    assert out == {call_va: [0x9E6840, 3, 0xFFFFFFFF, 0x12345678, 0]}


def test_derive_prop_names_carries_the_name():
    reg = [{"name": "C", "props": [{"hash": "0x1", "name": "n", "ui": None, "default": "0"}]}]
    assert gen_data.derive_prop_names(reg) == {
        "0x1": {"classes": ["C"], "name": "n", "ui": None, "default": "0"}
    }


# ---------------------------------------------------------------------------
# 4. fragment parser: type records, typed built-ins, empty files
# ---------------------------------------------------------------------------


def _str(s):
    b = s.encode("latin1") + b"\0"
    b += b"\0" * (-len(b) % 4)
    return struct.pack("<I", len(b) // 4) + b


def _key(name):
    return struct.pack("<I", kp.name_hash(name))


def _fragment(payload):
    return b"\x04" + b"\0" * 16 + struct.pack("<I", len(payload)) + payload


def _sample_payload():
    u, f = (lambda *v: struct.pack("<%dI" % len(v), *v)), (
        lambda *v: struct.pack("<%df" % len(v), *v)
    )
    p = u(0xFFFFFFFF, 0x11111111) + _str("AnimationEventWM(Node)")  # opening type record
    p += u(0xFFFFFFFE, 0x11111111) + _key("name") + _str("evt")
    p += _key("m_nvalue02") + f(0.35)  # digit-bearing name; 0.35 = 0x3eb33333
    p += _key("m_ttruth1") + u(1)
    p += _key("m_vvalue1") + f(1.0, 2.0, 3.0)
    p += u(0xFFFFFFFF, 0x22222222) + _str("Folder")  # bare native type record, mid-stream
    p += u(0xFFFFFFFE, 0x22222222) + _key("name") + _str("f")
    p += _key("aspectRatio") + f(1.5)
    p += _key("pivotSheet_Id") + u(0x447EF063, 0x071836EC)  # biginteger = 8 bytes
    p += _key("includeInAO") + u(1)
    p += _key("siblingOrder") + u(7)
    return p


def test_fragment_with_typed_extras_and_bare_type_record_parses_clean():
    """An event node with extra number/truth/vector properties and a created
    'Folder' node: before, the digit keys were unknown (float bit patterns such
    as key_3eb33333 followed), 'Folder' was read as property keys, and the
    8-byte pivotSheet_Id shifted everything after it."""
    r = kf.parse(_fragment(_sample_payload()))
    assert r["ok"] and r["parsed_frac"] == 1 and r["unknown"] == {}
    assert r["schema"] == [("11111111", "AnimationEventWM(Node)"), ("22222222", "Folder")]
    nodes = [(i["node"], i.get("created"), i["props"]) for i in r["inst"]]
    assert nodes[0] == (
        "11111111",
        False,
        [
            ("name", "string", "evt"),
            ("m_nvalue02", "number", 0.35),
            ("m_ttruth1", "truth", True),
            ("m_vvalue1", "vector", [1.0, 2.0, 3.0]),
        ],
    )
    assert nodes[1] == ("22222222", True, [])  # the type record itself: no properties
    assert nodes[2] == (
        "22222222",
        False,
        [
            ("name", "string", "f"),
            ("aspectRatio", "number", 1.5),
            ("pivotSheet_Id", "biginteger", 0x071836EC447EF063),
            ("includeInAO", "truth", True),
            ("siblingOrder", "integer", 7),
        ],
    )
    j = kj.to_json("x.fragment", _fragment(_sample_payload()))
    assert j["lossless"] is True
    assert [n["type"] for n in j["nodes_full"]] == ["AnimationEventWM(Node)", "Folder", "Folder"]
    assert not [k for n in j["nodes_full"] for k, _t, _v in n["props"] if k.startswith("key_")]


def test_ffffffff_followed_by_non_type_data_still_opens_a_node():
    """Only a well-formed [wc][name] block is consumed as a type record."""
    u = lambda *v: struct.pack("<%dI" % len(v), *v)
    p = u(0xFFFFFFFF, 0x11111111) + _str("Thing(Node)")
    p += u(0xFFFFFFFF, 0x33333333) + _key("siblingOrder") + u(4)
    r = kf.parse(_fragment(p))
    assert r["ok"]
    assert r["inst"][-1] == {
        "node": "33333333",
        "created": True,
        "props": [("siblingOrder", "integer", 4)],
    }


def test_header_only_fragment_is_empty_not_a_failure():
    """Nine Part 2 fragments are 17-byte headers with no chunk; they used to
    report fail=(0, '00000004')."""
    d = bytes.fromhex("0400000000000100000000000000000000")
    r = kf.parse(d)
    assert r["ok"] and r["inst"] == [] and r["schema"] == [] and r.get("empty") is True
    assert kj.to_json("x.fragment", d)["lossless"] is True
