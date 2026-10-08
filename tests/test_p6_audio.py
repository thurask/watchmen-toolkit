"""Sound metadata rules settled by the open-items sweep.

Speak blocking     SpeakCtrl.ShouldIgnoreThisSpeaker 0x83ae84
Speak senders      ids 8 / 9 / 36 / 37 and the EffectSpeak ids
Attack start       CharacterRootLogic.command_update_combo_timing 0x68810a
Ragdoll contact    0x69d00a, masks 0x69e5e6-0x69e64e, volume 0x8a9cd3
Music cues         change_on_cue = raw CRC of a cue name (0x423ca1), 0 = at once,
                   1 = next cue of any name
Synthetic fixtures only (the builders of test_audio_v2)."""

import os, sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import anim_meta as am
import sound_meta as sm
import watchmen_extract as wx
import test_audio_v2 as ta

sound_extract = ta.sound_extract  # the fixture of test_audio_v2, used below


def test_blocks_while_playing_follows_the_playing_lines_flags():
    f = sm.blocks_while_playing
    assert f(True, True) == "all" and f(False, True) == "nonplayers"
    assert f(True, False) == "players" and f(False, False) == "none"


def test_cue_hash_is_the_unfolded_crc():
    # measured values of the shipped cue names
    assert sm.cue_hash("click1") == 0x7E6EFDDC and sm.cue_hash("click") == 0x719A1BFD
    assert sm.cue_hash("Click") == 0x629E6D21  # case matters: no 0xDF fold
    assert sm.cue_hash("click_01") == 0x73AB579C and sm.cue_hash("click 01") == 0x7355579C
    assert sm.cue_hash("Perc_01") == 0x847FB0DF and sm.cue_hash("melody 01") == 0x9B2EB8AD
    assert sm.cue_hash("LongMelody") == 0xB73D4F2F


def test_cue_change_names_the_cue():
    names = ["Click", "click", "Marker 01"]
    assert sm.cue_change(0, names) == ("at_once", None)
    assert sm.cue_change(None, names) == ("at_once", None)
    assert sm.cue_change(1, names) == ("next_cue", None)
    assert sm.cue_change(0x629E6D21, names) == ("named_cue", "Click")
    assert sm.cue_change(0x719A1BFD, names) == ("named_cue", "click")
    assert sm.cue_change(0x629E6D21 - (1 << 32), names) == ("named_cue", "Click")  # signed
    assert sm.cue_change(0x7E6EFDDC, names) == ("named_cue", "unresolved")
    assert sm.cue_change(0x7E6EFDDC, None) == ("named_cue", "unresolved")


def test_setup_tracks_get_the_cue_mode_and_name():
    setup = {
        "states": [
            {
                "tracks": [
                    {"track": 0, "change_on_cue": 0},
                    {"track": 1, "change_on_cue": 1},
                    {"track": 2, "change_on_cue": 0x629E6D21},
                    {"track": 3, "change_on_cue": 0xB73D4F2F},
                ]
            }
        ]
    }
    sm.name_cue_changes(setup, ["Click", "click1"])
    assert setup["cue_names"] == ["Click", "click1"]
    got = [(t["change_on_cue_mode"], t["change_on_cue_name"]) for t in setup["states"][0]["tracks"]]
    assert got == [
        ("at_once", None),
        ("next_cue", None),
        ("named_cue", "Click"),
        ("named_cue", "unresolved"),
    ]
    assert setup["states"][0]["tracks"][2]["change_on_cue"] == 0x629E6D21  # the value stays


def test_stream_descriptor_facts_carry_the_cue_names():
    h = b"\x00" * 24 + ta.descriptor(
        "/derived_pc/sounds/Music/U/Under_track0.mediastream_s",
        [
            ("/sounds/Music/U/Under_track0.wav", 4800, 2, 48000, [("click1", 9), ("end", 77)]),
            ("/sounds/Music/U/Under_track1.wav", 4800, 2, 48000, [("click1", 9), ("Perc", 5)]),
        ],
    )
    facts = sm.SoundDB._header_facts(wx, h)
    assert facts["codec"] == "stream" and facts["tracks"] == 2
    assert facts["cue_names"] == ["Perc", "click1", "end"]


def test_table_rules(sound_extract):
    meta = sm.build(str(sound_extract), anim=am.build(str(sound_extract)))
    assert meta["not_established"] == [
        "listener: the 2D path",
        "SoundDef.Active on PC Part 1 (no executable; Xbox 360 Part 1 0x82b21808 and PS3 "
        "Part 1 0xb67090 read: no playing-leaf lookup)",
    ]
    music = meta["music_rules"]
    assert "0x7cf2a8" in music["playback"] and "square-root" in music["playback"]
    assert "inferred" in music["cue_source"] and "0x7d1113" in music["one_shots"]
    assert "0x83325a" in meta["conventions"]["footstep"]
    assert "0x83304e" in meta["evidence"]["footsteps"]
    rules = meta["speak_rules"]
    assert "0x83ae84" in rules["blocking"] and "PLAYING line" in rules["blocking"]
    assert rules["priority"].endswith("never read.")
    assert "0x83ae84" in meta["evidence"]["speak_rules"]
    trig = {tuple(t["speak_ids"]): t for t in meta["speak_triggers"]}
    assert "0x888e62" in trig[(8,)]["sender"] and trig[(37,)]["sender"] == "none"
    assert trig[(8,)]["evidence"].startswith("read (code sites); data:")
    assert trig[(26, 27, 29, 30, 31)]["evidence"].startswith("read (code sites); data:")
    assert trig[(33, 34)]["evidence"] == "read (constants at the sites)"
    assert trig[(37,)]["evidence"].startswith("read: no code site passes the id")
    assert trig[(20, 21)]["evidence"] == "read (constants at the sites)"
    fx = meta["effects"]
    assert "0x68810a" in fx["attack_start_rule"] and "impact - 0.2 s" in fx["attack_start_rule"]
    rc = fx["ragdoll_contact"]
    assert rc["bone_masks"] == {
        "RAGDOLL_HEAD": 0x3,
        "RAGDOLL_BODY": 0x16C47C,
        "RAGDOLL_ARM": 0x3B80,
        "RAGDOLL_FOOT": 0x90000,
    }
    assert rc["gates"]["mean_speed_above_m_s"] == 2.0
    assert rc["gates"]["min_interval_s_per_group"] == 0.5 and rc["first_match_wins"] is True
    assert "0x423ca1" in meta["music_rules"]["change_on_cue"]
    for g in meta["speak_groups"].values():
        for sp in g["speaks"].values():
            assert sp["blocks_while_playing"] == sm.blocks_while_playing(
                sp["ignore_player_events"], sp["ignore_nonplayer_events"]
            )


def test_ragdoll_contact_volume_formula():
    def vol(force, mass):
        return min(1.0, (abs(force) / mass / 200.0 + 0.3) ** 0.25)

    assert round(vol(0.0, 10.0), 4) == round(0.3**0.25, 4)  # the floor: about 0.74
    assert vol(1400.0, 10.0) == 1.0  # (0.7 + 0.3) ** 0.25
    assert vol(1e9, 1.0) == 1.0  # clamped
