"""The TextBox line breaker and line placement as the engine does them (PC Part 2:
FontBuffer 0x440c1e, 0x4419bc, 0x43ef4d, 0x4418ca), the %N parameter table and the
sender tables of `watchmen textmeta`.  Synthetic advances only."""

import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import text_assets as ta
import test_text_assets as tta

text_extract = tta.text_extract  # the fixture of test_text_assets

ADV = {c: 10.0 for c in "abcdefghijklmnopqrstuvwxyz @-_#ABCDEF0123456789"}

WRAP_CASES = [
    ("aaa bbb ccc", 70, ["aaa bbb", "ccc"]),
    ("aaa bbb ccc", 69, ["aaa", "bbb", "ccc"]),
    ("well-known", 60, ["well-", "known"]),
    ("well-known", 100, ["well-known"]),
    ("aaa_bbb", 100, ["aaa_bbb"]),  # no break: the underscore is kept and drawn
    ("aaa_bbb", 60, ["aaa_bbb"]),  # the width of a kept underscore is not tested (70 wide)
    ("aaa_bbb", 59, ["aaa-", "bbb"]),  # break at '_': a '-' is drawn instead
    ("a\tb\rc", 100, ["abc"]),  # tab and CR vanish without a space
    ("a\n\nb", 100, ["a", "", "b"]),  # blank lines are kept ...
    ("\na", 100, ["a"]),  # ... except an empty first line
    ("aaaaaaaaaaaa b", 50, ["aaaaaaaaaaaa", "b"]),  # an over-long word is not split
    ("#FF0000FFab cd", 40, ["#FF0000FFab", "cd"]),  # colour codes have no width
    ("a  b", 100, ["a  b"]),
    ("zzé", 100, ["zzé"]),  # no glyph: the width of '@'
    # an over-wide word on an empty line pushes an empty line first
    ("a\nbbbbbbbbbbbb", 50, ["a", "", "bbbbbbbbbbbb"]),
    ("aaa ", 100, ["aaa"]),  # a break character at the very end is dropped
]


@pytest.mark.parametrize("text,width,want", WRAP_CASES)
def test_layout_wrap(text, width, want):
    assert ta.layout_wrap(text, width, ADV) == want


def test_layout_place_and_widths():
    assert ta.layout_place(["ab"], 100, 0, 3, ADV) == [(0, 80.0)]  # justify: one gap of 80
    assert ta.layout_place(["abc", "a"], 100, 5, 1, ADV)[0][0] == 75  # right
    assert ta.layout_place(["abcd"], 100, 0, 2, ADV) == [(30.0, 0.0)]  # centre
    assert ta.layout_place(["abcd"], 100, 7, 0, ADV) == [(7, 0.0)]  # left
    assert list(ta.layout_tokens("#FF00ab##c#")) == ["a", "b", "#", "c"]
    assert ta.layout_string_width("ab", ADV, spacing=2.0) == 22.0
    assert ta.layout_string_width("", ADV) == 0.0
    assert ta.layout_char_width("é", ADV, 2.0) == 20.0
    assert ta.layout_box_size(["ab", "abcd"], ADV, 40, line_gap=2.0, scale_y=0.5) == (40.0, 42.0)
    font = {"glyphs": [{"code": 64, "width": 23.0}, {"code": 97, "width": 11.5}]}
    assert ta.layout_advances(font) == {"@": 23.0, "a": 11.5}
    assert "128-unit" in ta.layout_wrap.__doc__


def test_text_params_lists_the_slots_a_row_reads():
    assert ta.text_params("Press %3 or %15; then %3") == [3, 15]
    assert ta.text_params({"en": "%0 of %1", "fr": "%1 sur %0", "de": None}) == [0, 1]
    assert ta.text_params("100%% sure, %%5") == []
    assert ta.text_params(None) == [] and ta.text_params("plain") == []
    rows = [
        {"index": 0, "text": {"en": "Hold %3", "fr": "%3 / %15"}},
        {"index": 1, "text": {"en": "x"}},
    ]
    assert ta.add_row_params(rows) is rows
    assert rows[0]["params"] == [3, 15] and "params" not in rows[1]


def test_textmeta_rows_carry_their_params(text_extract):
    m = ta.build(str(text_extract))
    assert m["layout_rules"] is ta.LAYOUT_RULES or m["layout_rules"] == ta.LAYOUT_RULES
    rows = [r for a in m["assets"].values() for r in a["rows"]]
    assert rows and all(("params" in r) == bool(ta.text_params(r["text"])) for r in rows)


def test_layout_parameter_and_sender_tables():
    r = ta.LAYOUT_RULES
    assert r["break_characters"] == [" ", "-", "_", "\n", "\t", "\r"]
    assert r["line_copy_units"] == 128 and r["slot_string_units"] == 1024
    assert r["horizontal_alignment"]["2"] == "centre" and "0x440c1e" in r["evidence"]
    assert "never read" in r["vertical_alignment"] and "following lines" in r["colour_scope"]
    p = ta.PARAMETERS
    assert p["slots"]["3"] == "PLAYER_USE (24)" and p["slots"]["15"] == "MENU_SELECT (2)"
    assert p["slots"]["gamepad"]["0"] == "PLAYER_ATTACK_0 (21)"
    assert p["slots"]["keyboard_mouse"]["0"] == "Menu row 187"
    assert "0x7597ca" in p["other"]["30"] and "0x7fd097" in p["source"]
    s = ta.SENDERS
    assert (
        s["use_prompt"]["by_use_type"]["3"] == 91 and s["use_prompt"]["by_use_type"]["other"] == 68
    )
    assert s["boss_name"]["by_character_type"] == {"25": 112, "0": 267, "1": 268, "35": 269}
    w = s["warnings"]["by_warning"]
    assert w["4"] == {"platform 3 (PS3)": [None, None, 26], "platform 2 (X360)": [1, 2, 23]}
    assert w["12"] == [1, 2, 39] and s["warnings"]["no_text"] == [0, 2, 8]
    assert s["warning_names"]["2"] == "CHANGE_STORAGE_WITH_NO_PROFILE"
    assert s["platform_ids"] == {"0": "EDITOR", "1": "PC", "2": "X360", "3": "PS3"}
    for key in ("layout", "parameters", "senders"):
        assert key in ta._EV
