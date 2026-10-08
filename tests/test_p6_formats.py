"""Format facts settled by the open-items sweep.

Block header      @327 fingerprint display mode (0x49dd59), @328 raw CRC of the 255-byte
                  plaintext fingerprint field
Fragment keys     four corrected value types, the list / netparticipant properties the
                  executable registers (0x50570c, 0x500343), key names in the registered
                  spelling
Native messages   registration-string normaliser 0x4f9504, hash 0x423d30
PS3 sounds        segment dword 4 = byte length of two MP3 frames
Synthetic fixtures only."""

import json, os, struct, sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib"))
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import kapow_fragment as kf
import kapow_json as kj
import kapow_props as kp
import watchmen_extract as we
import test_formats_v2 as tf
import test_level_meta as tl
import test_p2_audio as ta

WLIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "wlib")
DEFAULT = "THIS IS THE DEFAULT FINGERPRINT KEY, PLEASE CHANGE IT!"


def _with_fingerprint(h, text, crc):
    b = bytearray(h)
    b[0x48:0x147] = bytes(255)
    ct = we.fingerprint_decrypt(text.encode("latin1"))  # the cipher is its own inverse
    b[0x48 : 0x48 + len(ct)] = ct
    b[327] = 2
    b[328:332] = struct.pack("<I", crc)
    return bytes(b)


def test_fingerprint_crc_is_the_raw_crc_of_the_padded_field():
    assert len(DEFAULT) == 54
    assert we.fingerprint_field_crc(DEFAULT) == 0x593F880A
    # the field is 255 bytes: one byte less or more gives another value
    for n in (254, 256):
        assert kp.kapow_hash(DEFAULT + "\0" * (n - len(DEFAULT))) != 0x593F880A
    assert kp.name_hash(DEFAULT + "\0" * 201) != 0x593F880A  # not the folded name hash


def test_block_header_names_the_fingerprint_fields():
    h, _s = tf._block([("/a.bmp", tf._TEX, b"HDR-A", None)])
    hd = we.parse_block_header(_with_fingerprint(h, DEFAULT, 0x593F880A))
    assert hd["fingerprint"] == DEFAULT
    assert hd["fingerprint_display"] == 2 and hd["unknown_327"] == 2
    assert hd["fingerprint_crc"] == 0x593F880A and hd["fingerprint_crc_ok"] is True
    assert hd["unknown_328"] == bytes.fromhex("0a883f59")  # the older fields stay
    bad = we.parse_block_header(_with_fingerprint(h, DEFAULT, 0x593F880B))
    assert bad["fingerprint_crc_ok"] is False
    other = we.parse_block_header(_with_fingerprint(h, "ANOTHER KEY", 0x593F880A))
    assert other["fingerprint"] == "ANOTHER KEY" and other["fingerprint_crc_ok"] is False


def test_fingerprint_crc_is_little_endian_on_a_big_endian_block():
    h, _s = tf._block([("/a.bmp", tf._TEX, b"HDR-A", None)])
    b = bytearray(_with_fingerprint(h, DEFAULT, 0x593F880A))
    struct.pack_into(">I", b, 32, 0x79D3E0DA)
    hd = we.parse_block_header(bytes(b), order=">")
    assert hd["fingerprint_crc"] == 0x593F880A and hd["fingerprint_crc_ok"] is True


# ----------------------------------------------------------- native messages
def test_native_message_signature_erases_argument_names():
    f = kp.native_message_signature
    assert f("IsLowViolence:truth") == "IsLowViolence:truth"
    assert (
        f("ApplyForceAtPos(position:vector,radius:number,force:vector)")
        == "ApplyForceAtPos(vector,number,vector)"
    )
    assert f("GetNearbyAIObjects(number):list(AIObjectInfo)") == (
        "GetNearbyAIObjects(number):list(AIObjectInfo)"
    )
    assert f("GetVibration(motor:integer):number") == "GetVibration(integer):number"
    assert f("Allocate") == "Allocate" and f("Odd(") == "Odd("
    # the engine's quirk: an unnamed argument in front of a named one goes with it
    assert f("GetNearbyAIAgents(number,agents:list(AIAgentInfo))") == (
        "GetNearbyAIAgents(list(AIAgentInfo))"
    )


def test_native_message_hash_stops_at_the_first_colon():
    assert kp.native_message_hash("IsLowViolence:truth") == 0xC8C0D741
    assert kp.native_message_hash(
        "ApplyForceAtPos(position:vector,radius:number,force:vector)"
    ) == (0x400325F2)
    assert kp.native_message_hash("GetVibration(motor:integer):number") == kp.name_hash(
        "getvibration(integer)"
    )


def test_registered_names_lists_the_native_messages():
    with open(os.path.join(WLIB, "registered_names.json"), encoding="utf-8") as fh:
        j = json.load(fh)
    nm = j["native_messages"]
    assert "not validated against a sender" in nm["note"]
    msgs = nm["messages"]
    assert nm["count"] == 589 == sum(len(v) for v in msgs.values())
    assert nm["hashes"] == len(msgs) == 577
    for h, sigs in msgs.items():
        assert all(kp.native_message_hash(s) == int(h, 16) for s in sigs)
    assert msgs["400325f2"] == ["ApplyForceAtPos(position:vector,radius:number,force:vector)"]
    assert len(j["names"]) == 1224  # the property / command table is untouched


# ----------------------------------------------------------- fragment keys
def test_four_key_types_follow_the_native_registration():
    want = {
        "alphaThreshold": "integer",  # 0x526ab6
        "materialColorAlpha": "number",  # 0x52712c
        "density": "integer",  # 0x533c49
        "model": "string",  # 0x5365a2 DetailMeshAsset, 0x55c691 ParticleType
    }
    for name, typ in want.items():
        assert kf.NAMES[kp.name_hash(name)] == (name, typ)


def test_registered_list_properties_have_their_types():
    for name in ("typeAffectors", "subPivots", "cloths", "particleTypes", "sheetVec"):
        assert kf.NAMES[kp.name_hash(name)] == (name, "list(Entity)")
    assert kf.NAMES[kp.name_hash("boneScaleFactors")][1] == "list(vector)"
    assert kf.NAMES[kp.name_hash("alignNode_originalOrientations")][1] == "list(quaternion)"
    assert kf.NAMES[kp.name_hash("generalEngineOptions_logChannels")][1] == "list(string)"
    assert kf.NAMES[kp.name_hash("remoteParticipants")][1] == "list(netparticipant)"
    assert kp.name_hash("localParticipant") == 0x0BB2CD35
    assert kf.NAMES[0x0BB2CD35] == ("localParticipant", "netparticipant")
    assert kp.TYPES[kp.name_hash("netparticipant")] == "netparticipant"


def test_netparticipant_is_one_slot_in_a_fragment():
    node = tl._node(0x21, "NetworkManager", "", None)
    node += tl._u(kp.name_hash("localParticipant"), 0xFFFFFFFF)
    node += tl._u(kp.name_hash("remoteParticipants"), 2, 7, 0xFFFFFFFF)
    node += tl._u(kp.name_hash("siblingOrder"), 5)  # the walk goes on behind them
    j = kj.to_json("x.fragment", tl._fragment(node))
    (rec,) = [n for n in j["nodes_full"] if not n.get("created")]
    props = {k: (t, v) for k, t, v in rec["props"]}
    assert props["localParticipant"] == ("netparticipant", 0xFFFFFFFF)
    assert props["remoteParticipants"] == ("list(netparticipant)", [7, 0xFFFFFFFF])
    assert props["siblingOrder"][1] == 5


def test_key_names_are_spelled_as_the_executable_registers_them():
    """M13: no key name differs from the registered spelling in letter case only."""
    with open(os.path.join(WLIB, "registered_names.json"), encoding="utf-8") as fh:
        rn = json.load(fh)
    generic = {int(h, 16): v for h, v in rn["generic"].items()}
    differ = []
    for h, spellings in rn["names"].items():
        hi = int(h, 16)
        if hi not in kf.NAMES:
            continue
        name = kf.NAMES[hi][0]
        if name in spellings or name in rn["keep"] or generic.get(hi) == name:
            continue
        if name.lower() in [s.lower() for s in spellings]:
            differ.append((h, name))
    assert differ == []
    for old, new in (
        ("Visible", "visible"),
        ("Open", "open"),
        ("UseRealTime", "useRealtime"),
        ("Locked", "locked"),
        ("UserType", "userType"),
        ("textres", "textRes"),
        ("minrange", "minRange"),
        ("Brightness", "brightness"),
    ):
        assert kp.name_hash(old) == kp.name_hash(new)  # the hash folds case: keys unchanged
        assert kf.NAMES[kp.name_hash(old)][0] == new
    assert kf.STDTYPES["open"] == "truth" and kf.STDTYPES["visible"] == "truth"
    assert kf.NAMES[kp.name_hash("visible")] == ("visible", "truth")


def test_readers_take_both_spellings_of_a_respelled_key():
    import anim_state_machine as asm
    import level_meta as lm

    for key in ("Visible", "visible"):
        n = asm.Node("1", "PivotNode", "x")
        n.props[key] = False
        assert lm._visible(n) is False
    assert lm._visible(asm.Node("1", "PivotNode", "x")) is True
    for key in ("Open", "open", "UseRealTime", "useRealtime", "Locked", "userType"):
        assert key in lm._STD  # neither spelling leaks into a node's `params`


# ----------------------------------------------------------- PS3 loop word
def test_ps3_loop_word_is_two_mp3_frames_in_bytes():
    for rate, ch in ((48000, 1), (44100, 1), (48000, 2)):
        bps = 64 * ch * 125
        word = int(2 * 1152 * bps / rate)
        h, _d = ta.ps3_sound(frames=12, rate=rate, ch=ch, loop=1, is3d=0, word4=word)
        i = we.sfx_info(h, ">")
        assert i["segment_word4"] == word == int(2 * 1152 * i["bytes_per_second"] / i["rate"])
        assert i["segment_word4_rule"] == "2 mp3 frames in bytes" and i["loop_skip_frames"] == 2
        assert i["samples"] == (i["mp3_frames"] - i["loop_skip_frames"]) * 1152
    assert [int(2 * 1152 * b / r) for r, b in ((48000, 8000), (44100, 8000), (48000, 16000))] == [
        384,
        417,
        768,
    ]
    h, _d = ta.ps3_sound(frames=10)
    i = we.sfx_info(h, ">")
    assert "loop_skip_frames" not in i and "segment_word4_rule" not in i
