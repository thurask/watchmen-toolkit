"""Text table additions of the open-items sweep.

routes / unreferenced   which reference properties reach a subtitled sound's SoundDef
languages_missing       a subtitle row that not every language table has
audio_start_delay_s     the definition's start delay delays the audio only (0x44a5fd)
movie length            .bik header: frames x divisor / rate
Synthetic fixtures only (the builders of test_text_assets / test_p1_formats)."""

import os, struct, sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import text_assets as ta
import test_audio_v2 as au
import test_p1_formats as tp
import test_text_assets as tt

text_extract = tt.text_extract  # the fixtures of those modules, used below
movie_extract = tp.movie_extract

V1 = "/sounds/Speaks/V1/Taunt_01_uk.wav"
V2 = "/sounds/Speaks/V2/TAUNT_02_uk.wav"
LX = "/sounds/Speaks/V1/Line_X_uk.wav"
LY = "/sounds/Speaks/V1/Line_X.wav"


def _more(out):
    """Adds a subtitled wave nothing references, one a TriggerActionSound in another
    fragment plays through its parent SoundDef, and a test-sound string property."""
    au.put_wave(out, LX, 1.0)
    au.put_wave(out, LY, 1.0)
    f = au.Frag("TNT/Fragments/Sound/Extra.fragment")
    f.add("SoundDef", "orphan", sound=LX)
    par = f.add("SoundDef", "parent", _nmindelay=0.25, _nmaxdelay=0.75)
    f.add("SoundDef", "leaf", par, sound=LY)
    act = f.add("TriggerActionSound", "play", m_etarget1={"ref": par})
    f.add("LoudSpeaker", "pa", _esoundslot={"ref": par})
    f.add("SoundCtrl", "ctrl", testSound3=LX)  # a path string is not a reference
    f.write(out)
    return act


def test_routes_and_unreferenced(text_extract):
    _more(text_extract)
    s = ta.build(str(text_extract))["subtitles"]
    a, b, x, y = (s["sounds"][k] for k in (V1, V2, LX, LY))
    assert a["routes"] == ["speak_group"] and b["routes"] == ["speak_group"]
    assert a["referrers"] == ["SpeakVoiceDefinition.m_espeaktyperef0"]
    assert "unreferenced" not in a
    assert x["routes"] == ["none"] and x["unreferenced"] is True and x["referrers"] == []
    # reached through the SoundDef above the leaf, by two kinds of referrer
    assert y["routes"] == ["trigger_action", "other"] and "unreferenced" not in y
    assert y["referrers"] == ["LoudSpeaker._esoundslot", "TriggerActionSound.m_etarget1"]
    assert s["routes"] == {"speak_group": 2, "trigger_action": 1, "other": 1, "none": 1}


def test_routes_of_classifies_referrers():
    assert ta.routes_of(set()) == (["none"], True)
    assert ta.routes_of({"SpeakVoiceDefinition.m_espeaktyperef3"}) == (["speak_group"], False)
    assert ta.routes_of({"TriggerActionSound.m_etarget1", "EffectSound._esounddef"}) == (
        ["trigger_action", "other"],
        False,
    )


def test_a_row_missing_in_a_language_is_marked(text_extract):
    s = ta.build(str(text_extract))["subtitles"]
    a, b = s["sounds"][V1], s["sounds"][V2]
    assert "languages_missing" not in a["lines"][0]
    # the second French row of the key: no other language has it, and it is not shown
    assert a["lines"][1]["languages_missing"] == ["en", "it", "de", "es"]
    assert a["lines"][1]["shown"] is False and "shown_in" not in a["lines"][1]
    # French has no row for this key: shown, but not in French
    assert b["lines"][0]["languages_missing"] == ["fr"] and b["lines"][0]["shown"] is True
    assert b["lines"][0]["shown_in"] == ["en", "it", "de", "es"]
    assert s["incomplete_lines"] == 2


def test_audio_start_delay_is_the_definitions_range(text_extract):
    _more(text_extract)
    s = ta.build(str(text_extract))["subtitles"]["sounds"]
    assert s[LY]["audio_start_delay_s"] == [0.25, 0.75]
    assert s[V1]["audio_start_delay_s"] in (None, [0.0, 0.0])
    m = ta.build(str(text_extract))
    assert "0x44a5fd" in m["evidence"]["audio_start_delay_s"]
    assert "0xb67090" in m["evidence"]["mission_speak"]
    assert "0x82949958" in m["evidence"]["subtitle_key"]
    assert "true VA" not in m["evidence"]["subtitle_key"]


def _bik(frames, rate, div):
    b = b"BIKi" + struct.pack("<II", 1000, frames) + bytes(8)
    return b + struct.pack("<4I", 1280, 720, rate, div) + bytes(64)


def test_bik_header_gives_the_movie_length():
    f = ta.bik_header(_bik(794, 10000000, 333667))
    assert f["frames"] == 794 and (f["width"], f["height"]) == (1280, 720)
    assert f["duration_s"] == 26.493 and f["fps"] == 29.97  # Cutscene08, measured
    assert ta.bik_header(_bik(2983, 2997, 100))["duration_s"] == 99.533  # Cutscene10B
    assert ta.bik_header(_bik(240, 24, 1))["duration_s"] == 10.0
    assert ta.bik_header(b"RIFF" + bytes(64)) is None
    assert ta.bik_header(_bik(10, 0, 1)) is None and ta.bik_header(b"BIK") is None


def test_movies_carry_the_length_when_the_file_is_there(movie_extract):
    d = movie_extract / "files" / "Art" / "cutscenes"
    os.makedirs(str(d), exist_ok=True)
    (d / "cutscene08b.BIK").write_bytes(_bik(2646, 10000000, 333667))
    movies = {m["name"]: m for m in ta.build(str(movie_extract))["movies"]}
    m = movies["Cutscene08B"]
    assert (m["frames"], m["fps"], m["duration_s"]) == (2646, 29.97, 88.288)
    assert m["duration_s"] > max(x["to_s"] for x in m["lines"])  # ends after its last row
    logo = movies["DeveloperMovie"]  # no file in the extract: no length keys
    assert "frames" not in logo and "duration_s" not in logo
