#!/usr/bin/env python3
"""text_assets -- the game's text tables (`textRes` assets) and its subtitles.

A `textRes` asset (`/Localize/Menu_uk_pc.txt`, `/Localize/SubtitlesPrison_uk.txt`
...) is a table of (key, text) rows (loader TextRes 0x5387ae):

    [u32 count]  count x ( [u32 n][n UTF-16 units]  [u32 n][n UTF-16 units] )

n counts the terminating NUL; integers and code units are little-endian on PC,
big-endian on X360 / PS3.  A TextSlot shows row `index`; nothing looks a row
up by key except the subtitle slots.

The 14 text tables of a game are localized block records: the block stores six
copies, one per language slot.  Slot i is language i of the engine's LANGUAGE
enum (0x47ff8c; the slot index is the current language, 0x45c762 / 0x4a3525):
English, French, Italian, German, Spanish, Danish.  Data: slots 0-4 of every
shipped block hold those five languages; slot 5 is a byte copy of slot 0 (no
Danish text was shipped).

Subtitles (SubtitleSlot 0x4da4db, 0x4da273, 0x4d89d0; SubtitleHUD 0x84a20c):
a row key is `name`, `name#start->end` or `start->end` (times `mm:ss:zzz`).
A playing sound looks its rows up by the file name of its wave, cut at the
first `_uk`, then at the first `_pc` (the cuts are case-sensitive); the lookup
lower-cases A-Z and hashes.  Rows without times follow each other, each
`defaultDuration` seconds long, and the line is on screen only while the sound
plays.  Cutscene tables are keyed by movie time; which table a movie uses is
data (MoviePlayerCtrl.subtitleSlot -> SubtitleSlot.textres).

CLI:  python3 text_assets.py extract NAZ_OR_FILES_DIR OUT_DIR
      python3 text_assets.py meta EXTRACT_OUT OUT.json
"""

import csv
import io
import json
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

FORMAT = "watchmen-text/1"
INDEX_FORMAT = "watchmen-text-index/1"
META_FORMAT = "watchmen-text-meta/1"
TEXT_CLASS = "textRes"

# LANGUAGE enum, builtin.cpp 0x47ff8c (explicit values); the block's six
# size / stream slots are indexed by it (0x45c762, 0x4a3525)
LANGUAGES = (
    (0, "English", "en"),
    (1, "French", "fr"),
    (2, "Italian", "it"),
    (3, "German", "de"),
    (4, "Spanish", "es"),
    (5, "Danish", "da"),
)
LANGUAGE_CODES = tuple(c for _i, _n, c in LANGUAGES)
#: the engine's own two-letter codes, slot order (platform constructor 0x45fb96;
#: consumed by the asset path rewriter 0x54e890: "/uk/" -> "/<code>/", "_uk" ->
#: "_<code>", and returned to scripts by GetCurrentCountryCodeMSG 0x47b9ec)
ENGINE_CODES = ("uk", "fr", "it", "de", "es", "dk")

# How each platform picks the slot (read: PC 0x45c7a6 emulated for every id
# 0..0xFFFF, X360 0x82a34a20, PS3 0x154ee0).  Every value not listed is English.
SELECTION = {
    "rule": "the current language (0x45c762) indexes the six size / stream slots of every "
    "block record and the header's language seek table (0x4a36d8: header offset 364 + "
    "4 x language); a system language that is not listed below gives slot 0, English",
    "fallback_slot": 0,
    "pc": {
        "source": "GetLocaleInfoA(0x800, LOCALE_ILANGUAGE): the system default locale, not "
        "the user's display language (the meaning of 0x800 is from the Windows SDK, not "
        "from the game's code)",
        "language_ids": {
            "1": ["0x040c", "0x080c", "0x0c0c", "0x100c", "0x140c", "0x180c"],
            "2": ["0x0410", "0x0810"],
            "3": ["0x0407", "0x0807", "0x0c07", "0x1007", "0x1407"],
            "4": ["0x%04x" % (0x40A + 0x400 * i) for i in range(20)],
        },
        "unreachable_slots": [5],
        "note": "slot 5 (Danish) is unreachable on PC: Danish, 0x0406, falls through to "
        "English.  An override field (platform+0x88, 6 = none) exists; no writer of it was "
        "found, an indirect one is not excluded",
    },
    "x360": {
        "source": "the console language setting (function 0x825b3838), then the locale "
        "(0x825b38c8) for Danish",
        "language_ids": {"0": [1], "1": [4], "2": [6], "3": [3], "4": [5]},
        "danish": "slot 5 when the language is none of 1, 3, 4, 5, 6 and 0x825b38c8 returns "
        "10 (it does for country code 0x19; reading that as Denmark is from the SDK, "
        "not from the game's code)",
    },
    "ps3": {
        "source": "cellSysutilGetSystemParamInt(0x111)",
        "language_ids": {"1": [2], "2": [5], "3": [4], "4": [3], "5": [14]},
        "note": "one field, no override",
    },
}

# When a speech subtitle is requested and which sound owns the line (read from
# the lifted scripts SoundDef / SubtitleHUD and the native SubtitleSlot).
SUBTITLE_RULES = {
    "entry_routes": [
        "speech: SoundDef.command_sounddef_play_speak 0x831bb8 is the only play entry that "
        "passes tSpeak = 1; the definition that actually plays (the chosen leaf) enters "
        "state Active.  Callers: SpeakCtrl.Active 0x83d414, "
        "AnimationEventWM.command_play_event_speak 0x5c1725, a debug tool",
        "activator: SoundDef.command_play_activator 0x831e22 enters Active on the definition "
        "it was sent to.  Callers: TriggerActionSound.TriggerSoundPlay 0x853e88, "
        "SoundCtrl.command_cross_fade 0x830d47",
    ],
    "other_starts": "a subtitled wave started any other way (Play, playfade, PlayPos, "
    "PlayPivot, PlayController ...) never asks for a line; true for every send the lifted "
    "scripts resolve statically, a send by a run-time name string is not established",
    "request": "in Active the HUD is asked once which slot has the key "
    "(HasSubtitleForSoundSlot 0x4d91bf), then every frame command_show_subtitle(slot, "
    "time, owner) until the sound stops; owner = the voice's sound slot when "
    "get_voice_soundslot is non-null, else the SoundDef",
    "priority": [
        "each frame (SubtitleHUD.StateMain 0x849343): last = showing; showing = none; "
        "if last is none: clear the text",
        "command_show_subtitle(slot, time, owner) 0x84a20c:",
        "  same_as_last = last is none or last == owner",
        "  free = showing is none and same_as_last",
        "  showing_mission = mission flag of (showing, else last)",
        "  if free or (owner is mission speak and not showing_mission):",
        "      showing = owner; index = slot.GetIndexFromSoundSlotAndTime(owner, time); "
        "show row index; a mission owner also damps the other sounds",
        "one owner at a time and no queue: the owner of the previous frame keeps the claim "
        "while it keeps asking, even while its index is -1 (blank text); a mission speak "
        "pre-empts a non-mission owner at once, mission against mission does not; a refused "
        "sound is not delayed, it shows from its own current time once the claim is free",
    ],
    "option": "the subtitle option is off by default (SettingsState.command_set_default_"
    "settings 0x82be66 sets m_tsubtitles = 0); SubtitleHUD.command_set_slot 0x84a11c asks "
    "GameStateCtrl.command_get_subtitles on every call and clears the text when it is off",
    "clock": "the line time advances by the real frame time [0xe14300] (QueryPerformance"
    "Counter delta, a frame capped at 0.1 s, 0x496294), not by the scaled game time; it "
    "starts at the play request",
}

MOVIE_RULE = (
    "every movie frame (0x49c557) the player asks its SubtitleSlot for the row of hash 0 "
    "(keys without a name) at movie time and shows that row in its text box.  Movie time "
    "is the Bink frame counter over the frame rate (0x435a65), not wall-clock time.  "
    "The lookup is the in-game one (0x4da273): rows in file order, a row is skipped only "
    "once its end has passed, so a row appears at shown_from_s = max(from_s, the latest "
    "to_s of ALL earlier rows) and an earlier row wins an overlap; shown false = the row "
    "never appears.  defaultDuration applies only to a row without an end time"
)

_EV = {
    "format": "read: TextRes loader 0x5387ae (count 0x435459, wide string 0x4374d1); data: "
    "0 trailing bytes on every text asset of Parts 1 and 2, PC / X360 / PS3, all six slots",
    "languages": "read: LANGUAGE enum 0x47ff8c, current language selects the slot 0x45c762 / "
    "0x4a3525; data: slots 0-4 hold English, French, Italian, German, Spanish text; slot 5 "
    "(Danish) is a byte copy of slot 0 in every shipped block",
    "subtitle_key": "read: SubtitleSlot 0x4d89d0 (the name is the SoundSlot's `sound` asset "
    "name, else its `streamingSound` name; its file name is cut at the first '_uk', then at "
    "the first '_pc', both cuts case-sensitive), 0x4d24aa (A-Z lower-cased, hashed; the "
    "table is keyed by that 32-bit hash alone); same two literals in the same order on "
    "X360 Part 2 0x8298e130 (literals loaded at 0x8298e2b0), X360 Part 1 0x82949958 (literals "
    "loaded at 0x82949ad8); Xbox 360 addresses are 0x82000000 + file offset of default.pe "
    "(the entry point, the .pdata starts and the jump tables agree only with that) and PS3 "
    "Part 2 0x266600 / Part 1 0x2663e8",
    "mission_speak": "data: m_tmissionspeak of the SoundDefs whose play tree holds the wave.  "
    "read, Part 2: the playing leaf is known in the first frame (0x44a8fa inserts the voice "
    "before returning its id), so the flag the HUD reads is the leaf's.  PS3 Part 1 "
    "(0xb67090): SoundDef.Active has no playing-leaf lookup and asks for the subtitle of "
    "the SoundDef that entered Active, so there the flag is that definition's.  X360 Part "
    "1 (0x82b21808): the same - 3 locals, no voice-slot lookup, the request and "
    "command_show_subtitle are given self.  PC Part 1: no executable, not established.  "
    "Whether this changes an exported value on Part 1 was not measured",
    "audio_start_delay_s": "data: _nmindelay.._nmaxdelay of the wave's definitions.  read: "
    "the subtitle clock starts at the play request and the start delay delays the audio "
    "only (0x44a5fd), so a line leads its audio by that delay",
    "routes": "data: every reference property of every fragment of the extract that lands "
    "on a SoundDef above the wave (SpeakVoiceDefinition -> speak_group, TriggerActionSound "
    "-> trigger_action, any other referrer -> other); `unreferenced` = no property "
    "reaches it.  A start by a run-time name string or command hash is not covered",
    "movie_length": "data: the .bik file header (frames at +8, frame rate dividend at +28, "
    "divisor at +32): duration = frames x divisor / rate; on the eight subtitled Part 2 "
    "movies the last subtitle row ends before it (three platform copies identical)",
    "subtitle_timing": "read: key grammar 0x4da4db, time format 'mm:ss:zzz' 0x4d21be, lookup "
    "0x4da273 (a row without times starts where the previous row of its key ended and lasts "
    "defaultDuration); SoundDef.Active 0x82aecf / SubtitleHUD.command_show_subtitle 0x84a20c "
    "(shown only while the sound plays, one sound at a time, mission speak first); data: "
    "defaultDuration of the slots",
    "speech": "data: speak groups and waves (sound_meta) joined to the table by the key rule",
    "subtitle_rules": "read: SoundDef.Active 0x82aecf (one `tSpeak = 1` site, two "
    "CALL_STATE(Active) sites), SubtitleHUD.StateMain 0x849343 / command_show_subtitle "
    "0x84a20c / command_set_slot 0x84a11c, SettingsState 0x82be66, frame clock 0x496294 "
    "(constants 1000.0 and 0.1 from the exe bytes)",
    "movie_subtitles": "read: MoviePlayer frame function 0x49c557 (movie time through "
    "impl vfunc +0x28, lookup under hash 0), lookup 0x4da273, movie time 0x435a65 "
    "(BinkGetRealtime, then field0 x field2 / field1; reading those as frame number, rate "
    "divisor and rate follows the Bink SDK struct and is inferred); data: `subtitleSlot` "
    "of the MoviePlayerCtrl nodes -> `textres` of that SubtitleSlot; isLocalized is false "
    "on every player node of Parts 1 and 2, so movie audio has one track",
    "selection": "read: LANGUAGE enum 0x47ff8c, current language 0x45c762, PC mapping "
    "0x45c7a6 (emulated for every id), X360 0x82a34a20, PS3 0x154ee0, engine codes "
    "registered in 0x45fb96 and consumed by 0x54e890 / 0x47b9ec",
    "markup": "read (substitution 0x4b6fb7, colour codes 0x43dd71 / 0x43d2e0, break table "
    "0x9eaab0): %N reads parameter slot N (decimal, 0-based; one ';' after the digits is "
    "swallowed; %% = %; a slot past the end gives an empty string), # + up to 8 upper-case "
    "hex digits is a colour (fewer digits are left-aligned with alpha FF; ## = #); the two "
    "characters backslash + n are replaced by U+000A (0x4b7007-0x4b700e).  data only: Greek "
    "capitals and Latin-1 symbols as button glyphs of the icon font (glyph flag 1 = icon, "
    "0x43efbb; the character is chosen by ProjectLib.SetTextSlotParams 0x7fd097)",
    "layout": (
        "read from code (PC Part 2: 0x440c1e, 0x4419bc, 0x43ef00, 0x43ef4d, 0x43efbb, "
        "0x4418ca, 0x4bf66d, 0x4b044a; table 0x9eaab0): break characters space - _ LF TAB CR; "
        "'-' stays on the word; '_' is drawn as '_' unless the line breaks there, then '-'; "
        "TAB and CR are dropped; no word splitting; advance = (glyph width + "
        "horizontalSpacing) * scale x, no kerning; alignment 0 left, 1 right, 2 centre, 3 "
        "justify (every line); verticalAlignment has no reader; line step = (glyph height + "
        "font v28[1]) * scale y; 2D scale = textScaling * (width / 1280, height / 720) of the "
        "renderer size; no clipping; missing glyph -> '@'; glyphs with flag 1 are drawn white "
        "with the current alpha; a colour code of all zeros is ignored; a colour stays in "
        "effect on the following lines, and in a 2D box a later line's code multiplies into "
        "the colour the previous line ended with"
    ),
    "parameters": "read: ProjectLib.SetTextSlotParams 0x7fd097 (every (N, logical button) "
    "pair, the gamepad / keyboard split and the keyboard-only branch), SetTextSlotParam "
    "0x7fdb09 (row = device button id + 1), GetMetaDeviceTextSlot 0x7f09b7; data: the "
    "ControllerLayout, KeyboardLayout and Menu tables",
    "senders": "read: PlayerHUD.SetTriggerUseType 0x7f2a38, pickup 0x801cc8, BossHUD "
    "0x625c7b, WarningWindowCtrl 0x8ac18d, warning names 0x7c5274-0x7c531a, PLATFORM enum "
    "0x47ff8c; inferred: that the boss name rows are in the Menu table (from the row texts)",
}

# ------------------------------------------------------------------ TextBox layout
#: the engine's line breaking and placement as data (PC Part 2 executable)
LAYOUT_RULES = {
    "binary": "KapowMultiDEDRM.exe (PC Part 2)",
    "break_characters": [" ", "-", "_", "\n", "\t", "\r"],
    "hyphen": "stays at the end of the word before it; a break may follow",
    "underscore": "break opportunity; drawn as '_' when the line does not break there, as '-' "
    "when it does; its own width is not tested",
    "tab_cr": "break the word and are dropped without a space",
    "newline": "forces a line; blank lines are kept, an empty first line is removed",
    "trailing_break": "a break character at the end of the text is dropped",
    "fit": "max_width >= pending_space_or_hyphen + line_width",
    "long_word": "not split; when the line is empty an empty line is pushed before it",
    "line_buffer_units": 256,
    "line_copy_units": 128,
    "slot_string_units": 1024,
    "advance": "(glyph.width + horizontalSpacing) * scale_x; no kerning",
    "horizontal_alignment": {
        "0": "left",
        "1": "right",
        "2": "centre",
        "3": "justify: spacing = (width - line_width) / (units - 1), every line; units counts "
        "colour-code characters",
    },
    "vertical_alignment": "stored, never read; text starts at the box top",
    "line_step": "(glyph_height + font.v28[1]) * scale_y",
    "scale_2d": "textScaling * (renderer_width / 1280, renderer_height / 720)",
    "wrap_width": "sprite size x (pixels)",
    "clipping": "none",
    "auto_size": "none in the engine",
    "colour_scope": "a colour code stays in effect on the following lines; 2D: a code "
    "multiplies into the colour the line started with, which is the colour the previous line "
    "ended with",
    "evidence": "read from code: 0x440c1e, 0x4419bc, 0x43ef00, 0x43ef4d, 0x43efbb, 0x4418ca, "
    "0x4bf66d, 0x4b044a; table 0x9eaab0",
}
#: what the %N parameter slots of a text hold (ProjectLib.SetTextSlotParams 0x7fd097):
#: a LOGICAL_INPUT_BUTTON name with its id is the layout-table row of the button the
#: device maps to it
PARAMETERS = {
    "source": "ProjectLib.SetTextSlotParams 0x7fd097; row = device button id + 1 (0x7fdb09)",
    "layout_table": {"gamepad": "ControllerLayout", "keyboard_mouse": "KeyboardLayout"},
    "slots": {
        "2": "PLAYER_ATTACK_2 (23)",
        "3": "PLAYER_USE (24)",
        "4": "PLAYER_SPECIAL_ATTACK_1 (25)",
        "5": "PLAYER_SPECIAL_ATTACK_2 (27)",
        "7": "MENU_BACK (3)",
        "8": "MENU_LEFT (5)",
        "9": "MENU_RIGHT (6)",
        "15": "MENU_SELECT (2)",
        "16": "device name (0x7fdbbb)",
        "17": "MENU_ABILITIES (7)",
        "18": "CAMERA_LOOK_AT_WAYPOINT (18)",
        "gamepad": {
            "0": "PLAYER_ATTACK_0 (21)",
            "1": "PLAYER_ATTACK_1 (22)",
            "10": "PLAYER_DEFEND (28)",
            "6": "ControllerLayout row 18",
            "12": "ControllerLayout row 17",
            "empty": [11, 13, 14, 19, 20, 21, 22, 23, 24],
        },
        "keyboard_mouse": {
            "0": "Menu row 187",
            "1": "Menu row 188",
            "10": "Menu row 189",
            "6": "KeyboardLayout row 262, or CAMERA_STICK_UP (36) when keyboard-only",
            "19": "CAMERA_STICK_LEFT (38), keyboard-only",
            "20": "CAMERA_STICK_DOWN (37), keyboard-only",
            "21": "CAMERA_STICK_RIGHT (39), keyboard-only",
            "11": "MOVEMENT_STICK_UP (30)",
            "12": "MOVEMENT_STICK_LEFT (32)",
            "13": "MOVEMENT_STICK_DOWN (31)",
            "14": "MOVEMENT_STICK_RIGHT (33)",
            "22": "PLAYER_ATTACK_0 (21)",
            "23": "PLAYER_ATTACK_1 (22)",
            "24": "PLAYER_DEFEND (28)",
        },
    },
    "other": {
        "25": "WarningWindowCtrl.SetParameterFromString 0x8a9f77",
        "30": "InputCtrl.HandleRemovedGamepads 0x7597ca (call at 0x759d5f)",
    },
}
#: which text row a HUD class shows for which value (row indices of the named table)
SENDERS = {
    "use_prompt": {
        "source": "PlayerHUD.SetTriggerUseType 0x7f2a38",
        "table": "Menu",
        "by_use_type": {
            "0": 87,
            "1": 95,
            "2": 94,
            "3": 91,
            "4": 90,
            "5": 93,
            "6": 88,
            "7": 92,
            "8": 96,
            "9": 97,
            "10": 98,
            "11": 100,
            "12": 202,
            "13": 270,
            "14": 270,
            "15": 271,
            "other": 68,
        },
        "note": "rows 270 and 271 are Part 2 only; use type -1 sets no row",
    },
    "pickup": {
        "source": "0x801cc8",
        "table": "Menu",
        "rorschach": [212, 213],
        "nite_owl": [214, 215],
        "ability": 216,
        "ability_params": "%0 = the ability's Menu row, %1 / %2 = unlocked / unlockable counts",
    },
    "boss_name": {
        "source": "BossHUD 0x625c7b",
        "table": "Menu",
        "by_character_type": {"25": 112, "0": 267, "1": 268, "35": 269},
        "other": "characterlib.DebugCharName, no table row",
        "note": "rows 267-269 are Part 2 only; the Menu table is inferred from the row texts",
    },
    "warnings": {
        "source": "WarningWindowCtrl 0x8ac18d",
        "table": "Warnings",
        "columns": ["accept row", "cancel row", "description row"],
        "by_warning": {
            "1": [1, 2, 17],
            "3": [3, None, 20],
            "4": {"platform 3 (PS3)": [None, None, 26], "platform 2 (X360)": [1, 2, 23]},
            "5": [3, 9, 24],
            "6": [3, 9, 25],
            "7": [5, None, 30],
            "9": [3, None, 27],
            "10": [3, None, 33],
            "11": [3, 10, 34],
            "12": [1, 2, 39],
        },
        "no_text": [0, 2, 8],
        "note": "warning 4 sets no text on any other platform; warning 12 is Part 2 only; "
        "null = the button is hidden",
    },
    "warning_names": {
        "0": "NO_PROFILE",
        "1": "NO_DEVICE",
        "2": "CHANGE_STORAGE_WITH_NO_PROFILE",
        "3": "CHANGED_PROFILE",
        "4": "OUT_OF_MEMORY",
        "5": "CORRUPT_SETTINGS_FILE",
        "6": "CORRUPT_PROGRESS_FILE",
        "7": "STORAGE_DEVICE_DISCONNECTED",
        "8": "STORAGE_DEVICE_RECONNECTED",
        "9": "AUTOSAVE_NOTIFICATION",
        "10": "LOADED_DATA_NOT_CREATED_BY_USER",
        "11": "SAVEDATA_MAY_BE_OVERWRITTEN",
        "12": "RESTORE_DEFAULT",
    },
    "platform_ids": {"0": "EDITOR", "1": "PC", "2": "X360", "3": "PS3"},
}

_LAYOUT_BREAK = " -_\n\t\r"  # table 0x9eaab0: 20 2d 5f 0a 09 0d 00
_PARAM = __import__("re").compile(r"%(\d+)")


def text_params(text):
    """Sorted distinct N of the %N parameter slots a text (a string or {language:
    string}) reads; %% is a literal per cent sign."""
    vals = text.values() if isinstance(text, dict) else [text]
    out = set()
    for s in vals:
        if isinstance(s, str):
            out.update(int(n) for n in _PARAM.findall(s.replace("%%", "")))
    return sorted(out)


def add_row_params(rows):
    """Adds `params` (text_params of the row's texts in every language) to each row of
    an asset that reads a %N parameter slot (PARAMETERS)."""
    for r in rows:
        pr = text_params(r.get("text"))
        if pr:
            r["params"] = pr
    return rows


def layout_tokens(s):
    """The drawn characters of a string (0x43dd71): '#' + up to 8 upper-case hex digits
    is a colour code (no width), '##' is '#'."""
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "#":
            yield c
            i += 1
            continue
        i += 1
        if i >= n:
            return
        if s[i] == "#":
            yield "#"
            i += 1
            continue
        k = 0
        while k < 8 and i + k < n and s[i + k] in "0123456789ABCDEF":
            k += 1
        i += k


def layout_advances(font_doc):
    """{character: advance in pixels} of a kapow-font/1 JSON (font_asset.parse)."""
    return {chr(g["code"]): g["width"] for g in font_doc.get("glyphs", [])}


def layout_char_width(c, adv, scale_x=1.0):
    """Advance of one character (0x43ef00); '@' when the font has no such glyph."""
    return adv.get(c, adv["@"]) * scale_x


def layout_string_width(s, adv, spacing=0.0, scale_x=1.0):
    """Width of a string (0x43ef4d): sum of (advance + spacing) * scale, minus one
    spacing."""
    w, k = 0.0, 0
    for c in layout_tokens(s):
        w += layout_char_width(c, adv, scale_x) + spacing * scale_x
        k += 1
    return w - spacing * scale_x if k else 0.0


def layout_wrap(text, max_width, adv, spacing=0.0, scale_x=1.0):
    """The lines the engine breaks `text` into for a box `max_width` pixels wide
    (FontBuffer line breaker 0x440c1e; LAYOUT_RULES).  adv: layout_advances().
    It does not model the 128-unit line copy."""
    W = lambda c: layout_char_width(c, adv, scale_x)
    SW = lambda s: layout_string_width(s, adv, spacing, scale_x)
    lines, line, linew, prev = [], "", 0.0, ""
    i, n = 0, len(text)
    while n:
        word = ""
        while i < n and not (text[i] in _LAYOUT_BREAK and ord(text[i]) < 0x80):
            word += text[i]
            i += 1
        cur = text[i] if i < n else ""
        if cur == "-":
            word += "-"
        extra = W("-") if cur == "_" else 0.0
        if prev == " ":
            extra += W(" ")
        linew += SW(word)
        if max_width >= extra + linew:  # fits (0x440cf8)
            if prev in (" ", "_") and prev:
                line += prev  # the space, or the underscore itself
                linew += W(prev)
        else:
            if prev == "_":
                line += "-"
            lines.append(line)
            line = ""
            linew = SW(word)
        line += word
        if cur == "\n":
            lines.append(line)
            line, linew = "", 0.0
        prev = cur
        if cur == "":
            break
        i += 1
        if i >= n:
            break
    if line:
        lines.append(line)
    if lines and lines[0] == "":
        del lines[0]
    return lines


def layout_place(lines, width, origin_x, mode, adv, spacing=0.0, scale_x=1.0):
    """Per line (x, letter spacing) (0x4419bc).  mode 0 left, 1 right, 2 centre,
    3 justify; a justified line's spacing stays in effect for the lines after it."""
    out, sp = [], spacing
    for ln in lines:
        lw = layout_string_width(ln, adv, sp, scale_x)
        x = origin_x
        if mode == 1:
            x = origin_x + width - lw
        elif mode == 2:
            x = (width - lw) * 0.5 + origin_x
        elif mode == 3 and len(ln) > 1:
            sp = (width - layout_string_width(ln, adv, 0.0, scale_x)) / (len(ln) - 1)
        out.append((x, sp))
    return out


def layout_box_size(lines, adv, glyph_height, line_gap=0.0, spacing=0.0, scale_x=1.0, scale_y=1.0):
    """(widest line, lines * (glyph_height + line_gap) * scale_y) (0x4418ca)."""
    return (
        max([layout_string_width(ln, adv, spacing, scale_x) for ln in lines] or [0.0]),
        scale_y * len(lines) * (glyph_height + line_gap),
    )


# ------------------------------------------------------------------ format
def detect_order(data):
    """'<' or '>' for a textRes payload: the order in which the row count and
    the first string length are plausible for the size."""
    if len(data) < 4:
        return "<"
    for bo in ("<", ">"):
        n = struct.unpack_from(bo + "I", data, 0)[0]
        if n * 8 + 4 > len(data):
            continue
        if n == 0:
            return bo
        ln = struct.unpack_from(bo + "I", data, 4)[0]
        if 8 + 2 * ln <= len(data):
            return bo
    return "<"


def parse_textres(data, order=None):
    """[(key, text)] of a textRes payload, in file order (the row index is what
    a TextSlot addresses).  Raises ValueError when the table does not end
    exactly at the end of the data."""
    bo = order or detect_order(data)
    enc = "utf-16-le" if bo == "<" else "utf-16-be"
    if len(data) < 4:
        raise ValueError("textRes: %d bytes, no row count" % len(data))
    n = struct.unpack_from(bo + "I", data, 0)[0]
    p, rows = 4, []
    for i in range(n):
        pair = []
        for _j in range(2):
            if p + 4 > len(data):
                raise ValueError("textRes: row %d of %d runs past the end" % (i, n))
            ln = struct.unpack_from(bo + "I", data, p)[0]
            p += 4
            if p + 2 * ln > len(data):
                raise ValueError("textRes: row %d of %d runs past the end" % (i, n))
            s = data[p : p + 2 * ln].decode(enc, "replace")
            p += 2 * ln
            pair.append(s[:-1] if s.endswith("\x00") else s)
        rows.append((pair[0], pair[1]))
    if p != len(data):
        raise ValueError("textRes: %d bytes after the last row" % (len(data) - p))
    return rows


def build_textres(rows, order="<"):
    """Inverse of parse_textres (every string NUL-terminated, as shipped)."""
    enc = "utf-16-le" if order == "<" else "utf-16-be"
    out = [struct.pack(order + "I", len(rows))]
    for pair in rows:
        for s in pair:
            b = (s + "\x00").encode(enc)
            out.append(struct.pack(order + "I", len(b) // 2) + b)
    return b"".join(out)


# --------------------------------------------------------------- subtitles
def subtitle_key(wave):
    """The key a sound's subtitle rows are found under (0x4d89d0): the wave's
    file name without directory and extension, cut at the first '_uk' and then
    at the first '_pc'.  Both cuts are case-sensitive and match anywhere in the
    name, not only at its end; letter case then drops out in the lookup, which
    lower-cases A-Z before hashing (key_hash).  The engine takes the name from
    the SoundSlot's `sound` asset, else from its `streamingSound`."""
    name = (wave or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = name.rsplit(".", 1)[0] if "." in name else name
    for cut in ("_uk", "_pc"):
        i = name.find(cut)
        if i >= 0:
            name = name[:i]
    return name


def key_hash(name):
    """Hash the engine files a subtitle key under (0x4d24aa): the raw Kapow
    hash of the lower-cased (A-Z only) name; 0 for an empty name."""
    import kapow_props

    low = "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in name)
    return kapow_props.kapow_hash(low) if name else 0


def _fold(name):
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in name)


def parse_time(s):
    """Seconds of a 'mm:ss:zzz' time (0x4d21be), or None when it is not one
    (the engine logs "Error parsing subtitle file" and uses -1)."""
    if len(s) != 9 or s[2] != ":" or s[5] != ":":
        return None
    d = s[0:2] + s[3:5] + s[6:9]
    if not all("0" <= c <= "9" for c in d):
        return None
    return int(d[0:2]) * 60.0 + int(d[2:4]) + int(d[4:7]) * 0.001


def parse_subtitle_key(key):
    """(name, start_s, end_s) of a row key as SubtitleSlot reads it (0x4da4db),
    or None for an empty key (the row is skipped).  A key that starts with a
    digit is times only (name ''); otherwise the name runs to the first '#'
    and times may follow (a key that starts with '#' has the name '').  A
    missing or unreadable time is None.  Nothing is truncated: past 127 name
    characters / 20 time characters the engine keeps copying (0x4da5b4,
    0x4da663, 0x4da6dc).  When both times read and 0 <= end < start the engine
    logs "end time is before start time!" and drops the end (0x4da710)."""
    if not key:
        return None
    name, spec = "", key
    if not ("0" <= key[0] <= "9"):
        name, sep, spec = key.partition("#")
        if not sep:
            return name, None, None
    start, sep, end = spec.partition("->")
    a = parse_time(start) if start else None
    b = parse_time(end) if sep and end else None
    if a is not None and b is not None and 0 <= b < a:
        b = None
    return name, a, b


def subtitle_table(rows, default_duration):
    """{folded name: [(start_s, end_s, row index)]} as the slot builds and
    reads it: rows of one name in file order; a row without a start begins
    where the previous one ended (0 for the first), one without an end lasts
    `default_duration` (0x4da273)."""
    raw = {}
    for i, (key, _text) in enumerate(rows):
        k = parse_subtitle_key(key)
        if k is None:
            continue
        raw.setdefault(_fold(k[0]), []).append((k[1], k[2], i))
    out = {}
    for name, lst in raw.items():
        prev, lines = 0.0, []
        for a, b, i in lst:
            start = prev if a is None else a
            end = start + default_duration if b is None else b
            lines.append((round(start, 4), round(end, 4), i))
            prev = end
        out[name] = lines
    return out


def subtitle_index(lines, t):
    """Row index shown at time `t` for one name's line list, or -1 (0x4da273:
    the first line with start <= t < end; a gap before a line returns -1)."""
    for start, end, i in lines or ():
        if end > t:
            if t < start:
                return -1
            return i
    return -1


# -------------------------------------------------------------- extraction
def block_text_assets(h_data):
    """[(asset name, localized, byte order, [payload per language slot])] of
    the textRes assets of one block header file (`*.block_h_z`).  A slot whose
    blob is missing or does not inflate is None."""
    import watchmen_extract as wx

    out, order = {}, None
    for lang in range(wx.BLOCK_LANGUAGES):
        entries, cur = wx.parse_block_toc(h_data, language=lang)
        bo = order = wx.BLOCK_ORDER
        num = struct.unpack_from(bo + "I", h_data, wx.NUM_TABLES_OFFSET)[0]
        lang_off = struct.unpack_from(bo + "6I", h_data, 364)
        for i, e in enumerate(entries):
            if i == num and lang_off[lang]:
                cur = lang_off[lang]
            size = e.data_size
            if e.type_name == TEXT_CLASS:
                rec = out.setdefault(e.name, [e.localized, [None] * wx.BLOCK_LANGUAGES])
                try:
                    rec[1][lang] = wx._maybe_inflate(h_data[cur : cur + size], e.type_name)
                except Exception:
                    rec[1][lang] = None
            cur += size
    return [(name, loc, order, blobs) for name, (loc, blobs) in out.items()]


def rows_json(name, rows, slot, order="<"):
    """The decoded table as written next to the raw asset."""
    _i, lang, code = LANGUAGES[slot]
    return {
        "format": FORMAT,
        "asset": name,
        "language": {
            "slot": slot,
            "name": lang,
            "code": code,
            "engine_code": ENGINE_CODES[slot],
        },
        "byte_order": "little" if order == "<" else "big",
        "rows": len(rows),
        "empty_rows": sum(1 for k, v in rows if not k and not v),
        "entries": [{"index": i, "key": k, "text": v} for i, (k, v) in enumerate(rows) if k or v],
    }


def rows_csv(rows):
    """index,key,text (rows that are empty left out); TextWriter writes it as UTF-8 with a
    byte-order mark."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["index", "key", "text"])
    for i, (k, v) in enumerate(rows):
        if k or v:
            w.writerow([i, k, v])
    return buf.getvalue()


class TextWriter:
    """Writes OUT/text/<language code>/<asset path> (the raw asset), + `.json`
    (decoded, order kept) and + `.csv` (readable), and OUT/text/index.json.

    Every language folder is complete: a text asset that is not localized is
    written into each.  A slot whose every asset is a byte copy of slot 0 (the
    Danish slot of the shipped games; every slot when nothing is localized)
    gets no folder; the index says so."""

    def __init__(self, out_dir, log=None):
        self.root = os.path.join(str(out_dir), "text")
        self.log = log or (lambda *a: None)
        self.assets = {}  # name -> {localized, order, slots: {slot: facts}, blobs}

    def add_block(self, h_data, block_name=None):
        """Collect the text assets of one block header file; returns how many."""
        found = block_text_assets(h_data)
        if block_name:
            # archive spelling: a loose `files` tree names its entries with a leading '/'
            block_name = block_name.replace("\\", "/").lstrip("/")
        for name, loc, order, blobs in found:
            self.assets[name] = {
                "localized": bool(loc),
                "order": order,
                "block": block_name,
                "blobs": blobs,
            }
        return len(found)

    def _safe(self, code, name, suffix=""):
        import watchmen_extract as wx

        return str(wx.safe(wx.Path(self.root) / code, name + suffix))

    def write(self):
        """Write everything collected; returns the index dict (None when no
        block had a text asset: nothing is written then)."""
        if not self.assets:
            return None
        copies = set()
        for slot in range(1, len(LANGUAGES)):
            if all(
                a["blobs"][slot] is None or a["blobs"][slot] == a["blobs"][0]
                for a in self.assets.values()
            ):
                copies.add(slot)
        index = {
            "format": INDEX_FORMAT,
            "evidence": {"format": _EV["format"], "languages": _EV["languages"]},
            "languages": [],
            "assets": {},
        }
        for slot, lang, code in LANGUAGES:
            index["languages"].append(
                {
                    "slot": slot,
                    "name": lang,
                    "code": code,
                    "engine_code": ENGINE_CODES[slot],
                    "folder": None if slot in copies else code,
                    "identical_to_slot": 0 if slot in copies else None,
                }
            )
        for name in sorted(self.assets):
            a = self.assets[name]
            rec = {
                "localized": a["localized"],
                "byte_order": "little" if a["order"] == "<" else "big",
                "block": a["block"],
                "languages": {},
            }
            for slot, _lang, code in LANGUAGES:
                blob = a["blobs"][slot]
                if slot in copies or blob is None:
                    continue
                try:
                    rows = parse_textres(blob, a["order"])
                except ValueError as ex:
                    self.log("      ! text %s [%s]: %s" % (name, code, ex))
                    rows = None
                raw = self._safe(code, name)
                os.makedirs(os.path.dirname(raw), exist_ok=True)
                with open(raw, "wb") as fh:
                    fh.write(blob)
                facts = {"file": os.path.relpath(raw, self.root).replace(os.sep, "/")}
                facts["bytes"] = len(blob)
                if rows is not None:
                    with open(raw + ".json", "w", encoding="utf-8", newline="\n") as fh:
                        json.dump(
                            rows_json(name, rows, slot, a["order"]),
                            fh,
                            indent=1,
                            ensure_ascii=False,
                        )
                    # UTF-8 with a byte-order mark: Excel then reads the accents
                    with open(raw + ".csv", "w", encoding="utf-8-sig", newline="") as fh:
                        fh.write(rows_csv(rows))
                    facts["rows"] = len(rows)
                    facts["strings"] = sum(1 for k, v in rows if k or v)
                rec["languages"][code] = facts
            index["assets"][name] = rec
        os.makedirs(self.root, exist_ok=True)
        with open(os.path.join(self.root, "index.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(index, fh, indent=1)
        n = sum(len(r["languages"]) for r in index["assets"].values())
        self.log(
            "TEXT: %d text assets, %d language files -> %s" % (len(index["assets"]), n, self.root)
        )
        return index


def extract_text(naz, out_dir, log=print):
    """Write only OUT_DIR/text/ from a game.naz (or a loose `files` tree):
    reads the block header files, touches nothing else.  Returns the index."""
    import watchmen_extract as wx

    w = TextWriter(out_dir, log)
    for e in wx.naz_entries(naz):
        if not e.name.lower().endswith(".block_h_z"):
            continue
        try:
            w.add_block(wx.naz_read(naz, e), e.name[: -len("_h_z")])
        except Exception as ex:
            log("  ! %s: %s" % (e.name, ex))
    return w.write()


# ---------------------------------------------------------------- metadata
def load_text(extract_out):
    """(index, {asset: {code: [(key, text)]}}) from EXTRACT_OUT/text (the raw
    assets are re-read; the .json / .csv beside them are for people)."""
    root = os.path.join(extract_out, "text")
    path = os.path.join(root, "index.json")
    if not os.path.exists(path):
        raise ValueError(
            "%s has no text/index.json -- run `watchmen text NAZ %s` (or a fresh `extract`)"
            % (extract_out, extract_out)
        )
    with open(path, encoding="utf-8") as fh:
        index = json.load(fh)
    tables = {}
    for name, a in index["assets"].items():
        order = "<" if a.get("byte_order") != "big" else ">"
        for code, facts in a["languages"].items():
            with open(os.path.join(root, facts["file"]), "rb") as fh:
                tables.setdefault(name, {})[code] = parse_textres(fh.read(), order)
    return index, tables


def _prop(n, key, default=None):
    """Property `key` of a node, whatever letter case the name table spells it
    in (`textRes` as the engine registers it; `textres` in key tables before 1.4.0)."""
    v = n.p(key)
    if v is not None:
        return v
    low = key.lower()
    for k, v in n.props.items():
        if k.lower() == low:
            return v
    return default


def _slots(db):
    """{asset path lower: [{fragment, node, class, name, default_duration_s}]}
    of the TextSlot / SubtitleSlot nodes that name a text asset."""
    out = {}
    for path, rel in sorted(db.files().values(), key=lambda x: x[1]):
        try:
            with open(path if os.path.exists(path) else path + ".json", "rb") as fh:
                b = fh.read()
        except OSError:
            continue
        if b"textres" not in b.lower() and b"TextSlot" not in b and b"SubtitleSlot" not in b:
            continue
        for n in db.nodes(rel).values():
            t = _prop(n, "textRes")
            if not isinstance(t, str) or not t:
                continue
            rec = {"ref": [rel, n.id], "class": n.cls, "name": n.name or None}
            if n.p("defaultDuration") is not None:
                rec["default_duration_s"] = round(float(n.p("defaultDuration")), 4)
            out.setdefault(t.replace("\\", "/").lower(), []).append(rec)
    return out


def shown_from(lines):
    """[(shown_from_s, shown)] for a slot's line list [(start_s, end_s, ...)] in
    file order, as the lookup 0x4da273 walks it: a row is passed over only once
    its end is behind, so row i is on screen from max(start_i, the latest end of
    all earlier rows) to end_i; shown is False when that leaves nothing."""
    out, latest = [], None
    for ln in lines:
        start, end = ln[0], ln[1]
        frm = start if latest is None else max(start, latest)
        out.append((round(frm, 4), frm < end))
        latest = end if latest is None else max(latest, end)
    return out


def bik_header(data):
    """{frames, width, height, fps, duration_s} of a Bink file's first 36 bytes, or None
    (magic 'BIK' + revision letter; u32 frames at +8, width +20, height +24, frame rate
    dividend +28 and divisor +32)."""
    if len(data) < 36 or data[:3] != b"BIK":
        return None
    frames = struct.unpack_from("<I", data, 8)[0]
    width, height, rate, div = struct.unpack_from("<4I", data, 20)
    if not rate or not div:
        return None
    return {
        "frames": frames,
        "width": width,
        "height": height,
        "fps": round(rate / float(div), 4),
        "frame_rate": [rate, div],
        "duration_s": round(frames * div / float(rate), 3),
    }


def _bik_index(extract_out):
    """{file name lower: path} of the .bik files of an extract."""
    out = {}
    for base in (os.path.join(extract_out, "files"), extract_out):
        if not os.path.isdir(base):
            continue
        for d, _dirs, names in os.walk(base):
            for nm in names:
                if nm.lower().endswith(".bik"):
                    out.setdefault(nm.lower(), os.path.join(d, nm))
        if out:
            break
    return out


def movie_file_facts(movie, index):
    """bik_header() of the file a MoviePlayer's `movie` names, or None."""
    if not isinstance(movie, str) or not movie:
        return None
    path = index.get(movie.replace("\\", "/").rsplit("/", 1)[-1].lower())
    if not path:
        return None
    try:
        with open(path, "rb") as fh:
            return bik_header(fh.read(36))
    except OSError:
        return None


def sound_def_referrers(db):
    """{(fragment, SoundDef node id): {"Class.property"}}: every reference property of
    every fragment of the extract that lands on a SoundDef node."""
    out = {}
    for _path, rel in sorted(db.files().values(), key=lambda x: x[1]):
        for n in db.nodes(rel).values():
            for k, v in n.props.items():
                if k == "logicalParent":
                    continue
                for x in v if isinstance(v, list) else (v,):
                    if not isinstance(x, dict) or not (x.get("ref") or x.get("xref")):
                        continue
                    hit = db.resolve(x, rel)
                    if hit and hit[1] is not None and hit[1].cls == "SoundDef":
                        out.setdefault((hit[0], hit[1].id), set()).add("%s.%s" % (n.cls, k))
    return out


def routes_of(referrers):
    """(routes, unreferenced) for the set of "Class.property" referrers of a sound."""
    routes = []
    if any(r.startswith("SpeakVoiceDefinition.") for r in referrers):
        routes.append("speak_group")
    if any(r.startswith("TriggerActionSound.") for r in referrers):
        routes.append("trigger_action")
    if any(not r.startswith(("SpeakVoiceDefinition.", "TriggerActionSound.")) for r in referrers):
        routes.append("other")
    return (routes or ["none"]), not routes


def _is_movie_player(n):
    t = getattr(n, "type", None) or ""
    return n.cls in ("MoviePlayerCtrl", "MoviePlayer") or t.endswith("(MoviePlayer)")


def _movies(db, tables, assets):
    """The `movies` section: every MoviePlayerCtrl node with its movie file and,
    through its `subtitleSlot` reference, the text table and timed lines."""
    by_low = {name.lower(): name for name in tables}
    biks = _bik_index(db.out)

    def brief(home, node):
        return {"ref": [home, node.id], "name": node.name or None}

    out = []
    for path, rel in sorted(db.files().values(), key=lambda x: x[1]):
        try:
            with open(path if os.path.exists(path) else path + ".json", "rb") as fh:
                if b"MoviePlayer" not in fh.read():
                    continue
        except OSError:
            continue
        for n in db.nodes(rel).values():
            if not _is_movie_player(n):
                continue
            rec = brief(rel, n)
            rec["movie"] = _prop(n, "movie") or None
            facts = movie_file_facts(rec["movie"], biks)
            # only when the .bik is in the extract (files/): an archive holds the
            # movies, `extract` copies those of a loose-folder source to files/
            if facts:
                rec["frames"], rec["fps"] = facts["frames"], facts["fps"]
                rec["duration_s"] = facts["duration_s"]
            vol = _prop(n, "volume")
            rec["volume"] = round(float(vol), 4) if isinstance(vol, (int, float)) else None
            loc = _prop(n, "isLocalized")
            rec["localized_audio"] = bool(loc) if loc is not None else None
            nxt = db.resolve(_prop(n, "m_econtinuelink"), rel)
            rec["continue_link"] = (
                dict(brief(*nxt), movie=_prop(nxt[1], "movie") or None) if nxt else None
            )
            skip = _prop(n, "m_tskiplink")
            rec["skip_skips_link"] = bool(skip) if skip is not None else None
            box = db.resolve(_prop(n, "subtitleTextBox"), rel)
            rec["subtitle_text_box"] = brief(*box) if box else None
            slot = db.resolve(_prop(n, "subtitleSlot"), rel)
            rec["subtitle_slot"] = brief(*slot) if slot else None
            rec["table"] = rec["default_duration_s"] = None
            rec["lines"] = []
            if slot:
                t = _prop(slot[1], "textRes")
                dd = _prop(slot[1], "defaultDuration")
                if isinstance(dd, (int, float)):
                    rec["default_duration_s"] = round(float(dd), 4)
                if isinstance(t, str) and t:
                    name = by_low.get(t.replace("\\", "/").lower())
                    rec["table"] = name or t
                    if name:
                        by_lang = tables[name]
                        first = by_lang[next(c for c in LANGUAGE_CODES if c in by_lang)]
                        lines = subtitle_table(first, rec["default_duration_s"] or 0.0).get("", [])
                        for (a, b, i), (frm, shown) in zip(lines, shown_from(lines)):
                            rec["lines"].append(
                                {
                                    "index": i,
                                    "from_s": a,
                                    "to_s": b,
                                    "shown_from_s": frm,
                                    "shown": shown,
                                    "text": {
                                        c: by_lang[c][i][1]
                                        for c in LANGUAGE_CODES
                                        if c in by_lang and i < len(by_lang[c])
                                    },
                                }
                            )
                        assets[name].setdefault("movies", []).append(brief(rel, n))
            out.append(rec)
    return out


def _aligned(by_lang, by_key=False):
    """Rows of one asset across languages.  Tables of one length are aligned by
    row index (what a TextSlot addresses); otherwise, and always with `by_key`
    (a table sounds look their rows up in), by (key, occurrence)."""
    codes = [c for c in LANGUAGE_CODES if c in by_lang]
    if not by_key and len({len(by_lang[c]) for c in codes}) == 1:
        rows = []
        for i in range(len(by_lang[codes[0]])):
            keys = [by_lang[c][i][0] for c in codes]
            text = {c: by_lang[c][i][1] for c in codes}
            if not any(keys) and not any(text.values()):
                continue
            row = {"index": i, "key": keys[0], "text": text}
            if len(set(keys)) > 1:
                row["key_by_language"] = dict(zip(codes, keys))
            rows.append(row)
        return "index", rows
    order, cells = [], {}
    for c in codes:
        seen = {}
        for i, (k, v) in enumerate(by_lang[c]):
            if not k and not v:
                continue
            n = seen.get(k, 0)
            seen[k] = n + 1
            if (k, n) not in cells:
                cells[(k, n)] = {"key": k, "n": n, "index": {}, "text": {}}
                order.append((k, n))
            cells[(k, n)]["index"][c] = i
            cells[(k, n)]["text"][c] = v
    return "key", [cells[k] for k in order]


def build(extract_out, log=None):
    """The text table of an extract (see docs/TEXT_ASSETS.md)."""
    import sound_meta

    log = log or (lambda *a: None)
    index, tables = load_text(extract_out)
    db = sound_meta.SoundDB(extract_out, log)
    slots = _slots(db)
    assets, sub_assets = {}, []
    for name in sorted(tables):
        by_lang = tables[name]
        use = slots.get(name.lower(), [])
        dur = next((s["default_duration_s"] for s in use if "default_duration_s" in s), None)
        first = next(iter(by_lang.values()))
        keys = [parse_subtitle_key(k) for k, _v in first if k]
        if dur is None:
            kind = "text"
        elif keys and all(k[0] == "" for k in keys):
            kind = "timed_subtitles"
        else:
            kind = "sound_subtitles"
        align, rows = _aligned(by_lang, kind == "sound_subtitles")
        if kind == "timed_subtitles":
            for r in rows:
                k = parse_subtitle_key(r["key"]) or ("", None, None)
                r["from_s"], r["to_s"] = k[1], k[2]
        add_row_params(rows)
        rec = {
            "kind": kind,
            "localized": index["assets"][name]["localized"],
            "slots": use,
            "rows_by_language": {c: len(v) for c, v in by_lang.items()},
            "strings_by_language": {c: sum(1 for k, t in v if k or t) for c, v in by_lang.items()},
            "aligned_by": align,
            "rows": rows,
        }
        if dur is not None:
            rec["default_duration_s"] = dur
        assets[name] = rec
        if kind == "sound_subtitles":
            sub_assets.append(name)

    # sound -> subtitle lines
    sounds, speech = {}, {}
    if sub_assets:
        name = sub_assets[0]
        dur = assets[name]["default_duration_s"]
        tabs = {c: subtitle_table(rows, dur) for c, rows in tables[name].items()}
        frags = db.sound_fragments()
        users, leaf_nodes = {}, {}
        for rel in frags:
            for n in db.nodes(rel).values():
                if n.cls == "SoundDef" and (n.parent is None or n.parent.cls != "SoundDef"):
                    d = db.definition(rel, n)
                    for leaf in sound_meta.leaves(d["play"]):
                        users.setdefault(leaf["wave"].lower(), []).append(d)
                        leaf_nodes.setdefault(leaf["wave"].lower(), []).append((rel, leaf["node"]))
        referrers = sound_def_referrers(db)

        def reached_by(wave_low):
            """Referrers of the SoundDefs a play of this wave can come from: the leaf's
            own node and every SoundDef above it."""
            got = set()
            for rel, nid in leaf_nodes.get(wave_low, ()):
                n = db.nodes(rel).get(nid)
                while n is not None and n.cls == "SoundDef":
                    got |= referrers.get((rel, n.id), set())
                    n = n.parent
            return got

        def lines_of(wave, duration):
            key = subtitle_key(wave)
            fk = _fold(key)
            n = max([len(t.get(fk, ())) for t in tabs.values()] or [0])
            out = []
            for i in range(n):
                line = {"n": i, "text": {}}
                for c in LANGUAGE_CODES:
                    lst = tabs.get(c, {}).get(fk, ())
                    if i < len(lst):
                        a, b, row = lst[i]
                        line.setdefault("from_s", a)
                        line.setdefault("to_s", b)
                        line["text"][c] = tables[name][c][row][1]
                if duration is not None and "from_s" in line:
                    line["shown"] = line["from_s"] < duration
                missing = [c for c in LANGUAGE_CODES if c in tabs and c not in line["text"]]
                if missing:  # a language without this row shows nothing for it
                    line["languages_missing"] = missing
                    if line.get("shown"):
                        line["shown_in"] = [c for c in LANGUAGE_CODES if c in line["text"]]
                out.append(line)
            return key, out

        db.wave("/sounds/x.wav")  # fills the wave index
        for (raw, k), path in sorted(db._wavs.items()):
            if not raw:
                continue
            w = db.wave(k) or {}
            if w.get("codec") == "stream":
                continue
            asset = "/" + os.path.relpath(path, db.root).replace(os.sep, "/")
            key, lines = lines_of(asset, w.get("duration_s"))
            if not lines:
                continue
            ds = users.get("/" + k, [])
            refs = reached_by("/" + k)
            routes, unref = routes_of(refs)
            delays = [d["start_delay_s"] for d in ds if d.get("start_delay_s")]
            lo = [x[0] for x in delays if x[0] is not None]
            hi = [x[1] for x in delays if x[1] is not None]
            sounds[asset] = {
                "key": key,
                "duration_s": w.get("duration_s"),
                "definitions": [d["ref"] for d in ds],
                "mission_speak": any(d.get("mission_speak") for d in ds),
                "audio_start_delay_s": [min(lo), max(hi)] if lo and hi else None,
                "routes": routes,
                "referrers": sorted(refs),
                "lines": lines,
            }
            if unref:
                sounds[asset]["unreferenced"] = True
        groups = sound_meta._speak_groups(db, frags)
        chars = sound_meta._characters(db, frags, groups)[0]
        for gk, g in groups.items():
            sp = {}
            for sid, s in g["speaks"].items():
                voices = []
                for v in s["voices"]:
                    ls = []
                    for wv in v.get("waves", ()):
                        key, lines = lines_of(wv["wave"], wv["duration_s"])
                        ls.append(
                            {
                                "wave": wv["wave"],
                                "duration_s": wv["duration_s"],
                                "key": key,
                                "text": lines[0]["text"] if lines else None,
                                "lines": len(lines),
                            }
                        )
                    voices.append(
                        {
                            "index": v["index"],
                            "name": v["name"],
                            "definition": v.get("definition"),
                            "lines": ls,
                        }
                    )
                sp[sid] = {
                    "speak": s["speak"],
                    "category": s["category"],
                    "plays": s["plays"],
                    "voices": voices,
                }
            speech[gk] = {
                "name": g["name"],
                "characters": sorted(k for k, c in chars.items() if c.get("speak_group") == gk),
                "speaks": sp,
            }
    movies = _movies(db, tables, assets)
    nlines = sum(
        1
        for g in speech.values()
        for s in g["speaks"].values()
        for v in s["voices"]
        for x in v["lines"]
    )
    ntext = sum(
        1
        for g in speech.values()
        for s in g["speaks"].values()
        for v in s["voices"]
        for x in v["lines"]
        if x["text"]
    )
    log(
        "  text_meta: %d assets, %d subtitled sounds, %d of %d speech waves have a subtitle, "
        "%d movie players (%d with a subtitle table)"
        % (
            len(assets),
            len(sounds),
            ntext,
            nlines,
            len(movies),
            sum(1 for m in movies if m["table"]),
        )
    )
    nodur = sum(1 for x in sounds.values() if x["duration_s"] is None)
    nodur_sp = sum(
        1
        for g in speech.values()
        for sp in g["speaks"].values()
        for v in sp["voices"]
        for x in v["lines"]
        if x["duration_s"] is None
    )
    if nodur or nodur_sp:
        # never silent: a line without its sound's length has no `shown` key
        log(
            "  text_meta: WARNING: no duration for %d of %d subtitled sounds and %d of %d speech waves "
            "(their sound header was not read; duration_s is null and `shown` is not set)"
            % (nodur, len(sounds), nodur_sp, nlines)
        )
    languages = [
        (
            dict(rec, engine_code=ENGINE_CODES[rec["slot"]])
            if isinstance(rec.get("slot"), int) and 0 <= rec["slot"] < len(ENGINE_CODES)
            else rec
        )
        for rec in index["languages"]
    ]
    meta = {
        "format": META_FORMAT,
        "conventions": {
            "text": "{language code: string} -- en, fr, it, de, es (da only when the Danish "
            "slot differs from English)",
            "rows": "aligned_by index: row i of every language (a TextSlot shows row "
            "`index`); aligned_by key: the n-th row of that key in each language",
            "subtitle": "a sound's rows are found by `key` = its wave's file name cut at "
            "the first '_uk', then at the first '_pc' (the cuts are case-sensitive); the "
            "lookup lower-cases A-Z and hashes.  Line n runs from_s..to_s after the sound "
            "starts and is shown only while the sound still plays (`shown` false: the "
            "sound is over before the line starts); `languages_missing` on a line = the "
            "languages whose table has no such row (nothing is shown in them; `shown_in` then "
            "lists the others); `subtitles.rules` says when a line is requested at all and "
            "which sound owns it; `routes` / `unreferenced` say whether any reference "
            "property of the extract reaches the sound (evidence.routes)",
            "timed_subtitles": "cutscene tables: from_s / to_s are movie time",
            "languages": "`code` names the text/ folder (ISO 639-1); `engine_code` is the "
            "engine's own code for the slot (uk fr it de es dk), the one it writes into "
            "localized asset paths; `selection` says how each platform picks the slot",
            "movies": MOVIE_RULE,
        },
        "evidence": _EV,
        "languages": languages,
        "selection": SELECTION,
        "layout_rules": LAYOUT_RULES,
        "parameters": PARAMETERS,
        "senders": SENDERS,
        "assets": assets,
        "subtitles": {
            "table": sub_assets[0] if sub_assets else None,
            "default_duration_s": (
                assets[sub_assets[0]]["default_duration_s"] if sub_assets else None
            ),
            "rules": SUBTITLE_RULES,
            "incomplete_lines": sum(
                1 for x in sounds.values() for ln in x["lines"] if ln.get("languages_missing")
            ),
            "routes": {
                r: sum(1 for x in sounds.values() if r in x["routes"])
                for r in ("speak_group", "trigger_action", "other", "none")
            },
            "sounds": sounds,
        },
        "movies": movies,
        "speech": speech,
        "not_established": [
            "TextBox layout on the Xbox 360 and PS3 builds (read on PC Part 2 only); the menu "
            "controllers are not read",
            "whether the Part 1 rule (the subtitle of the SoundDef that entered Active; Xbox "
            "360 Part 1 0x82b21808, PS3 Part 1 0xb67090) changes an exported mission_speak "
            "on Part 1 (not measured); SoundDef.Active on PC Part 1 (no executable)",
            "whether the subtitle option hides cutscene subtitles (no test of it was found on "
            "the movie path, script or 0x49c557; not confirmed by a run)",
            "a subtitle request sent by a run-time name string (none is visible in the "
            "lifted scripts)",
        ],
    }
    import canonical_names

    # strings that name a file of the export (the movie files, the text tables, the
    # fragments): spelled as that file is written, the stored string under "stored"
    return canonical_names.respell_export(meta, extract_out)


def write(extract_out, out_json, log=print):
    meta = build(extract_out, log=log)
    with open(out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1, ensure_ascii=False)
    return meta


def summary(meta):
    per = {}
    for a in meta["assets"].values():
        for c, n in a["strings_by_language"].items():
            per[c] = per.get(c, 0) + n
    movies = meta.get("movies") or []
    return (
        "%d text assets; strings %s; %d subtitled sounds; %d speak groups; "
        "%d movie players, %d with subtitles"
        % (
            len(meta["assets"]),
            ", ".join("%s %d" % (c, per[c]) for c in LANGUAGE_CODES if c in per),
            len(meta["subtitles"]["sounds"]),
            len(meta["speech"]),
            len(movies),
            sum(1 for m in movies if m.get("table")),
        )
    )


def main(argv):
    if len(argv) < 4 or argv[1] not in ("extract", "meta"):
        print("usage: text_assets.py extract NAZ_OR_FILES_DIR OUT_DIR")
        print("       text_assets.py meta EXTRACT_OUT OUT.json")
        return 0 if len(argv) > 1 and argv[1] in ("-h", "--help") else 2
    if argv[1] == "extract":
        idx = extract_text(argv[2], argv[3])
        if idx is None:
            print("no text assets found in %s" % argv[2])
            return 1
        return 0
    meta = write(argv[2], argv[3])
    print("wrote %s: %s" % (argv[3], summary(meta)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
