"""Text assets and subtitles.

Synthetic fixtures only.  They mirror the shipped data (read 2026-10-04): a
`textRes` asset is [u32 rows] x ([u32 n][UTF-16 key], [u32 n][UTF-16 text])
with n counting the NUL; the text tables are localized block records with one
copy per language slot (slot 5 a byte copy of slot 0); the in-game subtitle
table is keyed by the wave's file name cut at `_uk`, the cutscene tables by
`mm:ss:zzz->mm:ss:zzz`.
"""

import csv
import hashlib
import json
import os
import struct
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
import kapow_props
import watchmen_extract as wx

try:  # the module is new: on 1.3.0 every test fails instead of erroring at import
    import text_assets as ta
except ImportError:  # pragma: no cover
    ta = None

import test_formats_v2 as tf

TEXT_HASH = wx._name_hash("textRes")


def need():
    assert ta is not None, "wlib/text_assets.py is missing"
    return ta


ROWS = [
    ("Menu_Title", "WATCHMEN"),
    ("", ""),
    ("", "Press %1 to continue\\nor wait"),
    ("Menu_Text", "Réglages audio – ΦΥΤ"),
]


# ------------------------------------------------------------------ format
@pytest.mark.parametrize("order,enc", [("<", "utf-16-le"), (">", "utf-16-be")])
def test_textres_rows_in_both_byte_orders(order, enc):
    t = need()
    b = t.build_textres(ROWS, order)
    # the layout the loader reads: count, then length-prefixed NUL-terminated strings
    assert struct.unpack_from(order + "I", b, 0)[0] == 4
    assert struct.unpack_from(order + "I", b, 4)[0] == len("Menu_Title") + 1
    assert b[8 : 8 + 22] == "Menu_Title\x00".encode(enc)
    assert t.parse_textres(b, order) == ROWS
    assert t.parse_textres(b) == ROWS  # the order is found from the data
    assert t.detect_order(b) == order
    assert t.parse_textres(t.build_textres([], order)) == []


def test_textres_must_end_with_its_last_row():
    t = need()
    b = t.build_textres(ROWS)
    with pytest.raises(ValueError):
        t.parse_textres(b + b"\x00\x00", "<")
    with pytest.raises(ValueError):
        t.parse_textres(b[:-3], "<")
    with pytest.raises(ValueError):
        t.parse_textres(b"\x01", "<")


# --------------------------------------------------------------- subtitles
def test_subtitle_key_is_the_wave_name_cut_at_uk_and_pc():
    t = need()
    assert t.subtitle_key("/sounds/Speaks/TWILIGHT/BS2_TWL_Attack_RSH_05_uk.wav") == (
        "BS2_TWL_Attack_RSH_05"
    )
    assert t.subtitle_key("\\sounds\\x\\Line_pc.wav") == "Line"
    assert t.subtitle_key("/sounds/x/Help.wav") == "Help"
    assert t.subtitle_key("/a/Take_uk_alt_02.wav") == "Take"  # everything from the first '_uk'
    assert t.subtitle_key("/a/Line_UK.wav") == "Line_UK"  # the cut is case-sensitive ...
    # ... the lookup is not: the name is lower-cased before it is hashed
    assert t.key_hash("Line_UK") == t.key_hash("line_uk") == kapow_props.kapow_hash("line_uk")
    assert t.key_hash("") == 0


def test_subtitle_times_and_key_grammar():
    t = need()
    assert t.parse_time("00:04:607") == pytest.approx(4.607)
    assert t.parse_time("12:07:050") == pytest.approx(727.05)
    for bad in ("0:04:607", "00:04:60", "00-04-607", "aa:04:607", ""):
        assert t.parse_time(bad) is None
    assert t.parse_subtitle_key("") is None  # an empty key: the row is no subtitle
    assert t.parse_subtitle_key("RSH_Bull_01") == ("RSH_Bull_01", None, None)
    name, a, b = t.parse_subtitle_key("00:04:607->00:07:573")
    assert (name, a, b) == ("", pytest.approx(4.607), pytest.approx(7.573))
    name, a, b = t.parse_subtitle_key("Line#00:01:000->00:02:500")
    assert (name, a, b) == ("Line", 1.0, 2.5)
    assert t.parse_subtitle_key("Line#00:01:000") == ("Line", 1.0, None)


def test_rows_of_one_key_follow_each_other_for_the_default_duration():
    t = need()
    rows = [
        ("Line_A", "first"),
        ("", ""),
        ("LINE_a", "second"),  # the same key: case does not matter
        ("Other#00:01:000->00:02:000", "timed"),
        ("Other", "after it"),
        ("00:10:000->00:12:000", "movie"),
    ]
    tab = t.subtitle_table(rows, 7.0)
    assert tab["line_a"] == [(0.0, 7.0, 0), (7.0, 14.0, 2)]
    assert tab["other"] == [(1.0, 2.0, 3), (2.0, 9.0, 4)]
    assert tab[""] == [(10.0, 12.0, 5)]
    line = tab["line_a"]
    assert [t.subtitle_index(line, x) for x in (0.0, 6.99, 7.0, 13.9, 14.0)] == [0, 0, 2, 2, -1]
    # before the first timed row there is nothing; a gap ends the search
    assert t.subtitle_index(tab["other"], 0.5) == -1
    assert t.subtitle_index(tab[""], 9.0) == -1 and t.subtitle_index(tab[""], 11.0) == 5
    assert t.subtitle_index(None, 1.0) == -1


# -------------------------------------------------------------- extraction
LANG_TEXT = ["Audio", "Réglages audio", "Impostazioni audio", "Audioeinstellungen", "Ajustes"]


def text_block():
    """One block: a common text asset, a localized one (slot 5 = slot 0, as
    shipped) and a localized texture that must stay as it was."""
    t = need()
    menus = [t.build_textres([("Menu_Text", s), ("", "")]) for s in LANG_TEXT]
    menus.append(menus[0])
    subs = [t.build_textres([("Line_A", s.upper())]) for s in LANG_TEXT]
    subs.append(subs[0])
    common = t.build_textres([("PAD_A", "¢")])
    return tf._block(
        [
            ("/Localize/ControllerLayout_pc.txt", TEXT_HASH, common, None),
            ("/main.bmp", tf._TEX, b"MAIN", b"main-stream"),
        ],
        [
            ("/Localize/Menu_uk_pc.txt", TEXT_HASH, menus, None),
            ("/Localize/Subs_uk.txt", TEXT_HASH, subs, None),
            ("/logo_uk.bmp", tf._TEX, b"LOGO", [b"S%d" % i for i in range(6)]),
        ],
    )


def loose_tree(root):
    h, s = text_block()
    d = root / "files" / "derived_pc" / "levels"
    d.mkdir(parents=True)
    (d / "game.block_h_z").write_bytes(h)
    (d / "game.block_s_z").write_bytes(s)
    return root / "files"


def tree_hashes(root):
    out = {}
    for d, _dirs, files in os.walk(str(root)):
        for f in files:
            p = os.path.join(d, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, str(root)).replace(os.sep, "/")] = hashlib.sha1(
                    fh.read()
                ).hexdigest()
    return out


def test_block_text_assets_gives_every_language_slot():
    t = need()
    h, _s = text_block()
    got = {name: (loc, order, blobs) for name, loc, order, blobs in t.block_text_assets(h)}
    assert sorted(got) == [
        "/Localize/ControllerLayout_pc.txt",
        "/Localize/Menu_uk_pc.txt",
        "/Localize/Subs_uk.txt",
    ]
    loc, order, blobs = got["/Localize/Menu_uk_pc.txt"]
    assert loc is True and order == "<" and len(blobs) == 6
    assert [t.parse_textres(b)[0][1] for b in blobs] == LANG_TEXT + ["Audio"]
    loc, _order, blobs = got["/Localize/ControllerLayout_pc.txt"]
    assert loc is False and len(set(blobs)) == 1  # not localized: the same in every slot


def test_extract_writes_text_for_every_language_and_nothing_else_changes(tmp_path):
    t = need()
    files = loose_tree(tmp_path)
    plain, full = tmp_path / "plain", tmp_path / "full"
    args = ["--no-files", "--no-textures", "--no-models", "--quiet"]
    assert wx.main([str(files), "-o", str(plain), "--no-text"] + args) == 0
    assert wx.main([str(files), "-o", str(full)] + args) == 0
    a, b = tree_hashes(plain), tree_hashes(full)
    assert not any(k.startswith("text/") for k in a)
    # additive: every file of the run without text is there, byte for byte
    assert {k: v for k, v in b.items() if not k.startswith("text/")} == a
    # extracted/ still holds the slot chosen by --language (0)
    raw0 = (full / "extracted" / "Localize" / "Menu_uk_pc.txt").read_bytes()
    assert t.parse_textres(raw0)[0][1] == "Audio"
    text = full / "text"
    assert sorted(p.name for p in text.iterdir()) == ["de", "en", "es", "fr", "index.json", "it"]
    for code, want in zip(("en", "fr", "it", "de", "es"), LANG_TEXT):
        d = text / code / "Localize"
        assert sorted(p.name for p in d.iterdir()) == [
            "ControllerLayout_pc.txt",
            "ControllerLayout_pc.txt.csv",
            "ControllerLayout_pc.txt.json",
            "Menu_uk_pc.txt",
            "Menu_uk_pc.txt.csv",
            "Menu_uk_pc.txt.json",
            "Subs_uk.txt",
            "Subs_uk.txt.csv",
            "Subs_uk.txt.json",
        ]
        assert t.parse_textres((d / "Menu_uk_pc.txt").read_bytes())[0][1] == want
        j = json.loads((d / "Menu_uk_pc.txt.json").read_text(encoding="utf-8"))
        assert j["format"] == "watchmen-text/1" and j["asset"] == "/Localize/Menu_uk_pc.txt"
        assert j["language"]["code"] == code and j["rows"] == 2 and j["empty_rows"] == 1
        # the empty row keeps its index but is not listed
        assert j["entries"] == [{"index": 0, "key": "Menu_Text", "text": want}]
        assert (d / "Menu_uk_pc.txt.csv").read_bytes()[:3] == b"\xef\xbb\xbf"  # for Excel
        with open(d / "Menu_uk_pc.txt.csv", encoding="utf-8-sig", newline="") as fh:
            assert list(csv.reader(fh)) == [["index", "key", "text"], ["0", "Menu_Text", want]]
    en = (text / "en" / "Localize" / "Menu_uk_pc.txt").read_bytes()
    assert en == raw0
    idx = json.loads((text / "index.json").read_text())
    assert idx["format"] == "watchmen-text-index/1"
    langs = {x["code"]: x for x in idx["languages"]}
    assert [x["name"] for x in idx["languages"]] == [
        "English",
        "French",
        "Italian",
        "German",
        "Spanish",
        "Danish",
    ]
    # the Danish slot is a copy of the English one: no folder, the index says why
    assert langs["da"]["folder"] is None and langs["da"]["identical_to_slot"] == 0
    assert langs["fr"]["folder"] == "fr" and langs["fr"]["identical_to_slot"] is None
    m = idx["assets"]["/Localize/Menu_uk_pc.txt"]
    assert m["localized"] is True and sorted(m["languages"]) == ["de", "en", "es", "fr", "it"]
    assert m["languages"]["de"] == {
        "file": "de/Localize/Menu_uk_pc.txt",
        "bytes": len(t.build_textres([("Menu_Text", LANG_TEXT[3]), ("", "")])),
        "rows": 2,
        "strings": 1,
    }
    assert idx["assets"]["/Localize/ControllerLayout_pc.txt"]["localized"] is False


def test_text_command_adds_only_the_text_folder(tmp_path, capsys):
    t = need()
    import watchmen

    files = loose_tree(tmp_path)
    full = tmp_path / "full"
    wx.main([str(files), "-o", str(full), "--no-files", "--no-textures", "--no-models", "--quiet"])
    out = tmp_path / "existing"
    (out / "extracted").mkdir(parents=True)
    (out / "extracted" / "keep.bin").write_bytes(b"untouched")
    assert watchmen.main(["watchmen", "text", str(files), str(out)]) == 0
    assert "3 text assets" in capsys.readouterr().out
    assert sorted(p.name for p in out.iterdir()) == ["extracted", "text"]
    assert [p.name for p in (out / "extracted").iterdir()] == ["keep.bin"]
    # the same folder `extract` writes
    assert tree_hashes(out / "text") == tree_hashes(full / "text")
    # no block with a text asset: nothing written, a clear error
    empty = tmp_path / "empty"
    empty.mkdir()
    assert watchmen.main(["watchmen", "text", str(empty), str(tmp_path / "none")]) == 2
    assert not (tmp_path / "none").exists()
    assert t.extract_text(str(empty), str(tmp_path / "none"), log=lambda *a: None) is None


def test_a_differing_danish_slot_gets_its_folder(tmp_path):
    t = need()
    blobs = [t.build_textres([("K", "v%d" % i)]) for i in range(6)]
    h, _s = tf._block(
        [("/main.bmp", tf._TEX, b"MAIN", None)], [("/Localize/T_uk.txt", TEXT_HASH, blobs, None)]
    )
    w = t.TextWriter(tmp_path)
    assert w.add_block(h, "b") == 1
    idx = w.write()
    assert [x["folder"] for x in idx["languages"]] == ["en", "fr", "it", "de", "es", "da"]
    assert t.parse_textres((tmp_path / "text" / "da" / "Localize" / "T_uk.txt").read_bytes()) == [
        ("K", "v5")
    ]


# ---------------------------------------------------------------- metadata
@pytest.fixture
def text_extract(tmp_path):
    """An extract with a menu table, the in-game subtitle table (French has
    one line fewer and a doubled key), a cutscene table, and the sound side: a
    talk line with two voices and a grunt."""
    t = need()
    import test_audio_v2 as au

    def six(per):
        return per + [per[0]]

    menu = six([t.build_textres([("Title", s), ("", ""), ("", "x" + s)]) for s in LANG_TEXT])
    subs_rows = [
        [("Taunt_01", "Come here!"), ("Taunt_02", "You again."), ("Line_X", "Unused")],
        [("Taunt_01", "Viens !"), ("Taunt_01", "Allez !"), ("Line_X", "Inutilisé")],
    ]
    subs = [t.build_textres(subs_rows[0]), t.build_textres(subs_rows[1])]
    subs += [subs[0]] * 3
    cut = six([t.build_textres([("00:01:000->00:02:500", s)]) for s in LANG_TEXT])
    h, s_ = tf._block(
        [("/main.bmp", tf._TEX, b"MAIN", None)],
        [
            ("/Localize/Menu_uk_pc.txt", TEXT_HASH, menu, None),
            ("/Localize/SubtitlesPrison_uk.txt", TEXT_HASH, six(subs), None),
            ("/Localize/Cutscene08a_uk.txt", TEXT_HASH, cut, None),
        ],
    )
    files = tmp_path / "files"
    files.mkdir()
    (files / "g.block_h_z").write_bytes(h)
    (files / "g.block_s_z").write_bytes(s_)
    out = tmp_path / "out"
    t.extract_text(str(files), str(out), log=lambda *a: None)

    au.put_wave(out, "/sounds/Speaks/V1/Taunt_01_uk.wav", 2.0)
    au.put_wave(out, "/sounds/Speaks/V2/TAUNT_02_uk.wav", 9.0)
    au.put_wave(out, "/sounds/Speaks/V1/Grunt_01.wav", 0.4)
    slots = au.Frag("TNT/Fragments/TextSlots.fragment")
    slots.add("TextSlot", "MenuTextSlot", textres="/Localize/Menu_uk_pc.txt", currentIndex=0)
    slots.add(
        "SubtitleSlotRegister",
        "IngameSubtitles",
        textres="/Localize/SubtitlesPrison_uk.txt",
        defaultDuration=7.0,
    )
    slots.add("SubtitleSlot", "Cut08", textres="/Localize/Cutscene08a_uk.txt", defaultDuration=5.0)
    slots.write(out)
    en = au.Frag("TNT/Fragments/Enemy/AllTypes.fragment")
    v1 = en.add("SoundDef", "taunt v1", sound="/sounds/Speaks/V1/Taunt_01_uk.wav")
    v2 = en.add(
        "SoundDef", "taunt v2", sound="/sounds/Speaks/V2/TAUNT_02_uk.wav", m_tmissionspeak=True
    )
    gr = en.add("SoundDef", "grunt", sound="/sounds/Speaks/V1/Grunt_01.wav")
    g = en.add("CharacterSpeakDefinitionUpdate", "DomSpeakDefinition")
    flags = dict(m_nrandom=1.0, m_ndelay=0.0, m_nquarantinetimemin=1.0, m_nquarantinetimemax=2.0)
    talk = en.add(
        "SpeakDefinition",
        "TAUNT",
        g,
        m_ispeak=24,
        m_tallowmultipleevents=False,
        m_tignoreplayerspeakevents=True,
        m_tignorenoneplayerspeakevents=False,
        **flags,
    )
    en.add("SpeakVoiceDefinition", "Dom1", talk, m_espeaktyperef0={"ref": v1})
    en.add("SpeakVoiceDefinition", "Dom2", talk, m_espeaktyperef0={"ref": v2})
    hit = en.add(
        "SpeakDefinition",
        "HIT",
        g,
        m_ispeak=35,
        m_tallowmultipleevents=True,
        m_tignoreplayerspeakevents=False,
        m_tignorenoneplayerspeakevents=False,
        **flags,
    )
    en.add("SpeakVoiceDefinition", "Dom1", hit, m_espeaktyperef0={"ref": gr})
    en.write(out)
    return out


def test_textmeta_strings_per_language(text_extract):
    t = need()
    m = t.build(str(text_extract))
    assert m["format"] == "watchmen-text-meta/1"
    assert set(m["evidence"]) >= {"format", "languages", "subtitle_key", "subtitle_timing"}
    assert [x["code"] for x in m["languages"] if x["folder"]] == ["en", "fr", "it", "de", "es"]
    menu = m["assets"]["/Localize/Menu_uk_pc.txt"]
    assert menu["kind"] == "text" and menu["localized"] and menu["aligned_by"] == "index"
    assert [s["name"] for s in menu["slots"]] == ["MenuTextSlot"]
    assert menu["rows_by_language"]["de"] == 3 and menu["strings_by_language"]["de"] == 2
    # rows of equal-length tables are aligned by index (what a TextSlot addresses)
    assert [r["index"] for r in menu["rows"]] == [0, 2]
    assert menu["rows"][0]["key"] == "Title"
    assert menu["rows"][0]["text"] == dict(zip(("en", "fr", "it", "de", "es"), LANG_TEXT))
    assert menu["rows"][1]["text"]["fr"] == "xRéglages audio"
    cut = m["assets"]["/Localize/Cutscene08a_uk.txt"]
    assert cut["kind"] == "timed_subtitles" and cut["default_duration_s"] == 5.0
    assert (cut["rows"][0]["from_s"], cut["rows"][0]["to_s"]) == (1.0, 2.5)
    # the subtitle table differs in length between languages: aligned by key
    sub = m["assets"]["/Localize/SubtitlesPrison_uk.txt"]
    assert sub["kind"] == "sound_subtitles" and sub["aligned_by"] == "key"
    assert sub["slots"][0]["class"] == "SubtitleSlotRegister"
    rows = {(r["key"], r["n"]): r for r in sub["rows"]}
    assert rows[("Taunt_01", 0)]["text"]["fr"] == "Viens !"
    assert rows[("Taunt_01", 1)]["text"] == {"fr": "Allez !"}
    assert rows[("Taunt_02", 0)]["index"] == {"en": 1, "it": 1, "de": 1, "es": 1}
    assert "fr" not in rows[("Taunt_02", 0)]["text"]


def test_textmeta_links_sounds_and_speech_to_their_subtitles(text_extract):
    t = need()
    m = t.build(str(text_extract))
    s = m["subtitles"]
    assert s["table"] == "/Localize/SubtitlesPrison_uk.txt" and s["default_duration_s"] == 7.0
    # the grunt has no row: it is not in the table at all
    assert sorted(s["sounds"]) == [
        "/sounds/Speaks/V1/Taunt_01_uk.wav",
        "/sounds/Speaks/V2/TAUNT_02_uk.wav",
    ]
    a = s["sounds"]["/sounds/Speaks/V1/Taunt_01_uk.wav"]
    assert a["key"] == "Taunt_01" and a["duration_s"] == 2.0 and a["mission_speak"] is False
    assert a["definitions"] == [["TNT/Fragments/Enemy/AllTypes.fragment", "00000001"]]
    # French has two rows under the key: the second would start after 7 s, but
    # the sound is over after 2 s
    assert [(x["from_s"], x["to_s"], x["shown"]) for x in a["lines"]] == [
        (0.0, 7.0, True),
        (7.0, 14.0, False),
    ]
    assert a["lines"][0]["text"]["en"] == "Come here!" and a["lines"][0]["text"]["fr"] == "Viens !"
    assert a["lines"][1]["text"] == {"fr": "Allez !"}
    b = s["sounds"]["/sounds/Speaks/V2/TAUNT_02_uk.wav"]  # found case-insensitively
    assert b["key"] == "TAUNT_02" and b["mission_speak"] is True
    assert b["lines"][0]["text"] == {c: "You again." for c in ("en", "it", "de", "es")}
    (g,) = m["speech"].values()
    assert g["name"] == "DomSpeakDefinition"
    talk, hit = g["speaks"]["24"], g["speaks"]["35"]
    assert talk["category"] == 1 and hit["category"] == 2
    lines = [v["lines"][0] for v in talk["voices"]]
    assert [(x["key"], x["duration_s"]) for x in lines] == [("Taunt_01", 2.0), ("TAUNT_02", 9.0)]
    assert lines[0]["text"]["fr"] == "Viens !" and lines[0]["lines"] == 2
    assert hit["voices"][0]["lines"][0]["text"] is None  # a grunt has no subtitle


def test_textmeta_command_and_the_key_in_sound_meta(text_extract, tmp_path, capsys):
    need()
    import sound_meta
    import watchmen

    out = tmp_path / "tm.json"
    assert watchmen.main(["watchmen", "textmeta", str(text_extract), str(out)]) == 0
    assert "3 text assets" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8"))["format"] == "watchmen-text-meta/1"
    sm = sound_meta.build(str(text_extract))
    (g,) = sm["speak_groups"].values()
    waves = g["speaks"]["24"]["voices"][1]["waves"]
    assert waves == [
        {"wave": "/sounds/Speaks/V2/TAUNT_02_uk.wav", "duration_s": 9.0, "subtitle_key": "TAUNT_02"}
    ]
    # an extract without text/: a clear error, not a traceback
    with pytest.raises(ValueError, match="watchmen text"):
        ta.build(str(tmp_path / "nothing"))
