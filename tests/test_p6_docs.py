"""Documentation audit of 1.4.0: the statements a later read or the six-set export
overtook, where they live in code.

1. `.detailmesh.json`, `inferred["stream.format_stride on consoles"]`: the Xbox 360
   stride table IS read (watchmen_extract.CONSOLE_VERTEX_STRIDES, exe table
   0x8308b6e0) and gives the 60 bytes of the PC table for format 7; only the PS3
   table was not read.  The exported text said "the console tables were not read".
2. `anim_state_machine.members`: the docstring said how a class picks its first
   state "is not read"; it is (m_edefaultanimstate, command_get_valid_state).
3. The 28 command handlers that the function dump lacks are all in reg_dump.json
   (the table comes from the registration calls, not from the function list).
4. One 1.4.0 heading in the CHANGELOG, written against 1.3.0.
"""

import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "wlib"))

import anim_state_machine as asm  # noqa: E402
import kapow_json as kj  # noqa: E402
import terrain_asset as ta  # noqa: E402
import test_p3_raw_formats as p3  # noqa: E402
import watchmen_extract as we  # noqa: E402

KEY = "stream.format_stride on consoles"

# gap sweep of the PC executable, 2026-10-06: registered handlers without a function
# in the 19,233-function dump -> number of registrations
SWEPT_HANDLERS = {
    0x598A5A: 1,
    0x59D825: 1,
    0x614C00: 1,
    0x614C9C: 1,
    0x614D38: 1,
    0x61BBA2: 3,
    0x676574: 1,
    0x69ED29: 5,
    0x6A1B09: 1,
    0x6D910D: 1,
    0x704E77: 1,
    0x738A6C: 3,
    0x73B943: 1,
    0x73B97C: 1,
    0x75B9A9: 3,
    0x770CFC: 13,
    0x77C09D: 1,
    0x788E97: 1,
    0x788EC0: 1,
    0x7BFCDA: 6,
    0x7F0655: 10,
    0x7F0690: 1,
    0x7F06A2: 1,
    0x8127B5: 1,
    0x83C526: 1,
    0x83FFEA: 1,
    0x84A3B2: 8,
    0x87B96E: 86,
}


def test_console_stride_note_says_which_table_was_read():
    text = ta.DETAIL_INFERRED[KEY]
    # what the note claims is what the tables hold
    assert ta.DETAIL_FORMAT_STRIDE[ta.DETAIL_VERTEX_FORMAT] == 60
    assert we.CONSOLE_VERTEX_STRIDES[ta.DETAIL_VERTEX_FORMAT] == 60
    assert "Xbox 360 table (0x8308b6e0" in text and "CONSOLE_VERTEX_STRIDES" in text
    assert "the PS3 table was not read" in text
    assert "console tables were not read" not in text


@pytest.mark.parametrize("bo", ["<", ">"])
def test_detailmesh_json_carries_the_note(bo):
    doc = kj.to_json("a.detailmesh", p3._detail(bo), order=bo, stream=p3._detail_stream(bo))
    assert doc["inferred"] == ta.DETAIL_INFERRED
    assert doc["inferred"][KEY].endswith("the PS3 table was not read")
    # nothing but that text differs from what the stream layout says
    assert doc["stream"]["vertex_stride"] == doc["stream"]["format_stride"] == 60
    # without a stream there is no derived stride and no note
    assert "inferred" not in kj.to_json("a.detailmesh", p3._detail(bo), order=bo)


def test_members_docstring_no_longer_calls_the_first_state_unread():
    doc = " ".join(asm.members.__doc__.split())
    assert "is not read" not in doc
    assert "m_edefaultanimstate" in doc and "0x5f076f" in doc


def test_handlers_the_function_dump_lacks_are_in_reg_dump():
    with open(os.path.join(HERE, "..", "wlib", "reg_dump.json"), encoding="utf-8") as f:
        classes = json.load(f)
    seen = {}
    for c in classes:
        for cmd in c["commands"]:
            if cmd["handler"]:
                va = int(cmd["handler"], 16)
                if va in SWEPT_HANDLERS:
                    seen[va] = seen.get(va, 0) + 1
    assert seen == SWEPT_HANDLERS
    assert len(seen) == 28 and sum(seen.values()) == 156
    # the Ghidra handler table, made from reg_dump, has a row for each of them
    with open(os.path.join(HERE, "..", "tools", "ghidra", "handlers.tsv"), encoding="utf-8") as f:
        rows = {int(line.split("\t")[0], 16) for line in f if line.strip()}
    assert set(SWEPT_HANDLERS) <= rows
    running = [
        c["name"]
        for c in classes
        for cmd in c["commands"]
        if cmd["handler"] == "0x87b96e" and cmd["name"] == "command_is_behavior_running"
    ]
    assert len(running) == 35  # the largest group of the 86, not most of them


def test_changelog_has_one_1_4_0_entry_and_the_docs_do_not_date_it_backwards():
    root = os.path.join(HERE, "..")
    with open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8") as f:
        log = f.read()
    heads = re.findall(r"^## .*$", log, re.M)
    assert heads[0] == "## 1.4.0 — 2026-10-08" and heads[1].startswith("## 1.3.0")
    assert sum(h.startswith("## 1.4.0") for h in heads) == 1
    assert not any("unreleased" in h.lower() for h in heads)
    # "until 1.4.0" read as if 1.4.0 were already behind us
    for rel in (
        "README.md",
        "docs/KAPOW_NAZ_FORMAT.md",
        "docs/ENGINE_CONSTANTS.md",
        "docs/WATCHMEN_EXTRACTION_MASTER.md",
        "wlib/watchmen_extract.py",
    ):
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            text = " ".join(f.read().split()).lower()
        assert "until 1.4.0" not in text and "until toolkit 1.4.0" not in text, rel
