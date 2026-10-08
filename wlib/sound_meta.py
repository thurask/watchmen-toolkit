#!/usr/bin/env python3
"""sound_meta -- what the game plays, when, and for how long (sound_meta.json).

Joins the sound side of the fragments to the wave files of an EXTRACT_OUT:

  definitions     every SoundDef with its play tree (which wave(s) one "play"
                  starts) and the variation rule
  classes         per body animation class, per state: the SOUND / SPEAK /
                  foot-down events (the state's own and those of its
                  SoundEvents/SE_<clip>.fragment list) resolved to definitions,
                  waves and durations
  characters      the character definitions: type, body class, speak group,
                  attack-start effects, damage effect set, footstep rows
  speak_groups    per group the lines (speak id), their category and per voice
                  the definition / waves / durations
  footsteps       effect type x surface -> definition
  effects         attack-start and damage effects (EffectSound / EffectSpeak)
  face_talk       what the face rule needs: fixed-wave talk segments and, for
                  lines requested by the AI, the talk-clip length per voice
  music           MusicSetup: stream, track names, track states, cue points

References are [fragment, node id]: node ids repeat across fragments, so an id
alone does not name a node.  An Entity value is {'ref': id} (same fragment) or
{'xref': [a, ..., id]}: each leading element is either the id of a FragmentNode
of the fragment reached so far (its assetName is the next fragment) or the
name hash of a fragment's file stem (name_hash("SoundDb") = 68447a02).  Data:
all 7,215 sound references of the Part 2 PC fragments resolve this way (1,763
same-fragment, 5,448 [stem hash, id], 4 with three elements).

Every table carries an `evidence` line: "read" = traced in the executable
(address given), "data" = measured on the game files, "inferred" = neither.

CLI:  python3 sound_meta.py EXTRACT_OUT OUT.json [ANIM_META.json]
"""

import json
import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

import anim_state_machine as asm  # noqa: E402
import engine_enums as ee  # noqa: E402
import kapow_props  # noqa: E402

FORMAT = "watchmen-sound-meta/1"

# ANIMATION_EVENT ids handled by CharacterRootLogic.command_animation_event_received
# 0x6a525e: SOUND 0x6aba76, SPEAK 0x6a9f30, foot events 0x6a533a
EV_SOUND, EV_SPEAK = 9, 37
EV_FOOT = {6: "step", 40: "step", 76: "jump", 77: "stop"}
EV_NAMES = {
    9: "SOUND",
    37: "SPEAK",
    6: "LEFT_FOOT_DOWN",
    40: "RIGHT_FOOT_DOWN",
    76: "FOOT_DOWN_JUMP",
    77: "FOOT_DOWN_STOP",
}

# exe enum family SPEAK_ID (registered names, prefix stripped)
SPEAK_ID = dict(
    enumerate(
        (
            "NOTHING TAUNT TAUNT_TARGET_KILLED TARGET_SPOTTED TARGET_SPOTTED_COMMUNICATE_TO_GROUP "
            "ENGAGEMENT MELEE NOT_USED_03 TAUNT_COUNTER_ATTACK_A TAUNT_COUNTER_ATTACK_B "
            "TAUNT_SPECIAL_MOVE_A TAUNT_SPECIAL_MOVE_B TAUNT_FINISHING_MOVE NOT_USED_02 "
            "TAUNT_TARGET_STUNNED TAUNT_TARGET_THROWN NOT_USED_01 HELP_COMMUNICATE_TO_GROUP "
            "TARGET_A_SPOTTED_COMMUNICATE_TO_GROUP TARGET_B_SPOTTED_COMMUNICATE_TO_GROUP "
            "TAUNT_TARGET_A_SPOTTED TAUNT_TARGET_B_SPOTTED TAUNT_GET_UP_TO_TARGET_A "
            "TAUNT_GET_UP_TO_TARGET_B MELEE_ON_TARGET_A MELEE_ON_TARGET_B DAMAGED_HEAVY_FACE "
            "DAMAGED_HEAVY_MIDDLE DAMAGED_HEAVY_KNOCKDOWN DAMAGED_LIGHT_FACE DAMAGED_LIGHT_MIDDLE "
            "DAMAGED_LIGHT_KNOCKDOWN DEATH MELEE_START_LIGHT MELEE_START_HEAVY DAMAGED_LIGHT_STUN "
            "DAMAGED_GRENADE DAMAGED_ELECTRIFY"
        ).split()
        + ["SPECIAL_GROUP_%d" % i for i in range(1, 13)]
    )
)

# SoundDef._iselectionmethod, SoundDef.command_sounddef_play_all 0x831365
SELECTION = {
    0: "random_start_first_free",
    1: "random_no_immediate_repeat",
    2: "round_robin",
    3: "self",
    4: "all",
}

# footstep effect type by character type and event (0x6a533a):
# {kind: (Rorschach, Nite Owl, female, everyone else)}; COLLISION_EFFECT_TYPES ids
FOOT_EFFECT = {"step": (53, 54, 91, 33), "jump": (65, 66, 92, 64), "stop": (62, 63, 93, 61)}
FOOT_FEMALE_TYPES = (28, 33, 35)  # go-go dancer, Dominatrix, Twilight Lady
FOOT_DEFAULT_SURFACE = 6  # DEFAULT, when neither model nor texture names a package

_TOKENS = (
    b"SoundDef",
    b"SpeakDefinition",
    b"EffectSound",
    b"EffectSpeak",
    b"SoundPackageCtrl",
    b"MusicStreamSlot",
    b"CharacterDef",
    b"CharacterEffectDef",
)

_EV = {
    "definitions": "data: SoundDef nodes; play tree and variation rule read: "
    "SoundDef.command_sounddef_play_all 0x831365, jitter 0x4d094c",
    "waves": "data: sound asset header (loader 0x449e40): samples / rate, loop flag",
    "classes": "data: AnimationEventWM nodes of the state and of its SoundEvents fragments; "
    "handlers read: SOUND 0x6aba76, SPEAK 0x6a9f30, foot events 0x6a533a",
    "characters": "data: CharacterDef -> m_emodelfragment (CharVisual: m_ianimationclassid), "
    "m_echaractersounddef, m_echaractereffectdef",
    "speak_groups": "data: SpeakDefinition / SpeakVoiceDefinition; category read: "
    "SpeakLib.DetermineSoundCategoryStruct 0x83baa1, SpeakCtrl.Active 0x83d936 (START_SPEAK "
    "only for category 1), voice choice 0x83afd6",
    "speak_rules": "read: SpeakCtrl.ShouldIgnoreThisSpeaker 0x83ae84, "
    "SpeakDefinition.command_fill_speak_def_struct 0x83e397",
    "music_rules": "read: MusicPlayer track_switch / cue_point_event (0x7cf77c, 0x7cfb52), cue "
    "hash 0x423ca1; data: every change_on_cue other than 0 and 1 is the hash of a cue name of "
    "that set's music streams (PC Part 2 and PC Part 1); playback read: "
    "MusicPlayer.command_allocate 0x7cf2a8, MusicTrigger.command_trig 0x7d1113, "
    "play_one_off_sound 0x7cf896",
    "footsteps": "data: CollisionSoundDB SoundPackageCtrl rows; lookup read: "
    "CollisionEffectCtrl 0x6e0f13; effect type by character type read: 0x6a533a; table build "
    "read: SoundPackageCtrl.initialize_local 0x83304e, initialize_external 0x83325a",
    "effects": "data: EffectBase children; read: EffectSound.Fire 0x714d1f, EffectSpeak.Fire "
    "0x714d94, attack start 0x679525, damage effect choice 0x6673d0",
    "face_talk": "read: START_SPEAK senders 0x6aba76 / 0x83d94d, STOP_SPEAK 0x83dbe4 / 0x69c7d7; "
    "data: durations",
    "music": "data: MusicSetup / MusicStreamSlot / MusicTrigger / MusicTrackCtrl nodes and the "
    "mediastream descriptors; state selection read: SoundCtrl.StateActive 0x829f70",
}


def speak_category(allow_multiple, ignore_player, ignore_nonplayer):
    """SpeakLib.DetermineSoundCategoryStruct 0x83baa1: 2 = grunt (may overlap,
    never sends START_SPEAK), 1 = exclusive line (START_SPEAK at its start,
    SpeakCtrl.Active 0x83d936), 0 = never played."""
    if allow_multiple and not ignore_player and not ignore_nonplayer:
        return 2
    if not allow_multiple and (ignore_player or ignore_nonplayer):
        return 1
    return 0


def effective_category(speak):
    """Category of a speak-group line as it behaves: None = the group has no
    such line, 0 = it never plays (category 0, or no voice has a sound), else
    its category (1 opens the mouth, 2 does not)."""
    if speak is None:
        return None
    return speak["category"] if speak["plays"] else 0


def foot_effect_type(character_type, kind):
    """COLLISION_EFFECT_TYPES row a foot event of `kind` ("step" / "jump" /
    "stop") looks up for a character type (0x6a533a)."""
    row = FOOT_EFFECT[kind]
    if character_type == 0:
        return row[0]
    if character_type == 1:
        return row[1]
    return row[2] if character_type in FOOT_FEMALE_TYPES else row[3]


def _key(rel, nid):
    return "%s#%s" % (rel, nid)


def _round(v, n=4):
    return None if v is None else round(float(v), n)


def _prop_any_case(n, key):
    """Property `key` of a fragment node whatever letter case the key table
    spells it in (the hash folds case: `Priority` in the table, `priority` as
    SoundAsset registers it)."""
    v = n.p(key)
    if v is not None:
        return v
    low = key.lower()
    for k, v in n.props.items():
        if k.lower() == low:
            return v
    return None


def _mean(ds):
    """Mean to 4 decimals.  math.fsum, not sum(): sum() of floats is a plain fold up to
    Python 3.11 and compensated from 3.12 on, and the last bit decides a rounding now
    and then, so the same extract gave 3.0259 on one Python and 3.0258 on another."""
    import math

    return round(math.fsum(ds) / len(ds), 4)


def _stats(ds):
    ds = [d for d in ds if d]
    if not ds:
        return {"n": 0, "min": None, "max": None, "mean": None}
    return {
        "n": len(ds),
        "min": round(min(ds), 4),
        "max": round(max(ds), 4),
        "mean": _mean(ds),
    }


class SoundDB:
    """The fragments and wave headers of one EXTRACT_OUT, with reference
    resolution across fragments."""

    def __init__(self, extract_out, log=None):
        self.out = extract_out
        root = os.path.join(extract_out, "extracted")
        self.root = root if os.path.isdir(root) else extract_out
        self.log = log or (lambda *a: None)
        self._files = None  # rel lower -> (abs path of the .fragment, rel)
        self._stems = None  # stem hash -> [rel]
        self._trees = {}  # rel -> (roots, {id: node})
        self._home = {}  # id(node) -> rel
        self._wavs = None  # asset path lower -> abs path
        self._wave = {}
        self._defs = {}
        self._info = None  # audio/sound_info.json: asset path lower -> record
        self.unresolved = {}
        self.reparsed = {}  # fragment -> byte order it was re-read in

    # ------------------------------------------------------------ fragments
    def files(self):
        if self._files is None:
            self._files, self._stems = {}, {}
            for d, _dirs, names in os.walk(self.root):
                for nm in sorted(names):
                    low = nm.lower()
                    if low.endswith(".fragment.json"):
                        nm, low = nm[:-5], low[:-5]
                    elif not low.endswith(".fragment"):
                        continue
                    rel = os.path.relpath(os.path.join(d, nm), self.root).replace(os.sep, "/")
                    if rel.lower() in self._files:
                        continue
                    self._files[rel.lower()] = (os.path.join(d, nm), rel)
                    h = "%08x" % kapow_props.name_hash(nm[: -len(".fragment")])
                    self._stems.setdefault(h, []).append(rel)
            for v in self._stems.values():
                v.sort()
        return self._files

    def rel(self, asset):
        """Fragment key of an asset path ('/TNT/.../x.fragment') or None."""
        if not isinstance(asset, str):
            return None
        hit = self.files().get(asset.replace("\\", "/").lstrip("/").lower())
        return hit[1] if hit else None

    def nodes(self, rel):
        """{node id: node} of one fragment ({} when it does not parse)."""
        if rel not in self._trees:
            import kapow_json as kj

            hit = self.files().get((rel or "").lower())
            roots, nodes = [], {}
            if hit:
                try:
                    doc = kj.load_fragment(hit[0])
                    roots, nodes = asm.tree_from_json(doc)
                    if not nodes and not doc.get("lossless"):
                        roots, nodes = self._reparse(hit[0], rel, roots, nodes)
                except (OSError, ValueError, KeyError, struct.error) as ex:
                    self.log("  sound_meta: %s: %s" % (rel, ex))
            for n in nodes.values():
                self._home[id(n)] = rel
            self._trees[rel] = (roots, nodes)
        return self._trees[rel][1]

    def _reparse(self, path, rel, roots, nodes):
        """A fragment the automatic byte-order test read as empty and not
        lossless (a small big-endian fragment whose little-endian chunk walk
        happens to end on the last byte): parse it in each order and keep the
        one that reads the whole file.  Says so in the log."""
        import kapow_json as kj

        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return roots, nodes
        if len(data) <= 17:
            return roots, nodes
        for order in (">", "<"):
            try:
                doc = kj.to_json(path.lower(), data, order=order)
                r2, n2 = asm.tree_from_json(doc) if doc else ([], {})
            except (ValueError, KeyError, IndexError, struct.error):
                continue
            if n2 and doc.get("lossless"):
                self.log(
                    "  sound_meta: %s: read as %s-endian (the automatic byte-order test "
                    "found no node)" % (rel, "big" if order == ">" else "little")
                )
                self.reparsed[rel] = order
                return r2, n2
        self.log("  sound_meta: %s: no node read in either byte order" % rel)
        return roots, nodes

    def home(self, node):
        """Fragment a node of this DB was read from."""
        return self._home.get(id(node))

    def sound_fragments(self):
        """Fragments that hold sound data (a byte test on the class names)."""
        out = []
        for path, rel in sorted(self.files().values(), key=lambda x: x[1]):
            try:
                with open(path if os.path.exists(path) else path + ".json", "rb") as fh:
                    b = fh.read()
            except OSError:
                continue
            if any(t in b for t in _TOKENS):
                out.append(rel)
        return out

    def resolve(self, ref, home=None):
        """(fragment, node) an Entity value points at, or None.  home: the
        fragment the value was read from."""
        if not isinstance(ref, dict):
            return None
        if ref.get("ref") is not None:
            n = self.nodes(home).get(ref["ref"]) if home else None
            return (home, n) if n is not None else None
        x = ref.get("xref")
        if not x:
            return None
        cur = home
        for a in x[:-1]:
            nxt = None
            n = self.nodes(cur).get(a) if cur else None
            if n is not None and str(n.p("assetName") or "").lower().endswith(".fragment"):
                nxt = self.rel(n.p("assetName"))
            if nxt is None:
                self.files()
                cands = self._stems.get(a, [])
                if len(cands) > 1:  # several files of one name: the one that has the node
                    cands = [r for r in cands if x[-1] in self.nodes(r)] or cands
                    cands.sort(key=lambda r: -len(os.path.commonprefix([r, home or ""])))
                nxt = cands[0] if cands else None
            if nxt is None:
                self.unresolved[a] = self.unresolved.get(a, 0) + 1
                return None
            cur = nxt
        n = self.nodes(cur).get(x[-1]) if cur else None
        return (cur, n) if n is not None else None

    # ---------------------------------------------------------------- waves
    def wave(self, path):
        """Facts of a wave asset ('/sounds/.../x.wav'): duration_s, loop,
        channels, rate, codec -- from the raw sound header in extracted/, else
        from audio/sound_info.json (the same header facts, written by the
        extract on every platform), else from the decoded file in audio/.  A
        stream descriptor gives its track count and the first track's length.
        `duration_source` says where the length is from: "header" (the stored
        sample count: exact on PC, whole XMA2 / MP3 frames on console),
        "frame_count" (frames x frame size), "decoded" (the file in audio/).
        None when none of them is there."""
        if not path or not isinstance(path, str):
            return None
        k = path.replace("\\", "/").lstrip("/").lower()
        if k not in self._wave:
            self._wave[k] = self._wave_info(k)
        return self._wave[k]

    def _wave_info(self, k):
        import watchmen_extract as wx

        if self._wavs is None:
            self._wavs = {}
            for base in (self.root, os.path.join(self.out, "audio")):
                for d, _dirs, names in os.walk(base):
                    for nm in names:
                        if nm.lower().endswith(".wav"):
                            p = os.path.join(d, nm)
                            r = os.path.relpath(p, base).replace(os.sep, "/").lower()
                            self._wavs.setdefault((base == self.root, r), p)
        raw = self._wavs.get((True, k))
        # the first 64 KiB hold every PC and X360 header fact; a PS3 header is
        # checked against its MP3 frames, so a longer file is then read whole
        for limit in (1 << 16, None) if raw else ():
            try:
                with open(raw, "rb") as fh:
                    head = fh.read() if limit is None else fh.read(limit + 1)
            except OSError:
                break
            more = limit is not None and len(head) > limit
            got = self._header_facts(wx, head[:limit] if more else head)
            if got or not more:
                if got:
                    return got
                break
        i = self._sound_info().get(k)
        if i and i.get("duration_s"):
            return {
                "duration_s": i["duration_s"],
                "loop": i.get("looping"),
                "channels": i.get("channels"),
                "rate": i.get("rate"),
                "codec": i.get("codec"),
                "basis": "audio/sound_info.json",
                "duration_source": i.get("duration_source", "header"),
            }
        dec = self._wavs.get((False, k))
        if dec:
            import wave as _wave

            try:
                w = _wave.open(dec, "rb")
                try:
                    return {
                        "duration_s": round(w.getnframes() / float(w.getframerate()), 4),
                        "loop": None,
                        "channels": w.getnchannels(),
                        "rate": w.getframerate(),
                        "codec": None,
                        "basis": "decoded file",
                        "duration_source": "decoded",
                    }
                finally:
                    w.close()
            except Exception:  # not a RIFF the wave module reads
                return None
        return None

    @staticmethod
    def _header_facts(wx, head):
        """Wave facts from the bytes of a raw 'sound' / stream descriptor asset."""
        for order in ("<", ">"):
            try:
                i = wx.sfx_info(head, order)
            except (struct.error, IndexError, ValueError):
                i = None
            if i and i.get("duration_s"):
                return {
                    "duration_s": i["duration_s"],
                    "loop": i["looping"],
                    "channels": i["channels"],
                    "rate": i["rate"],
                    "codec": i["codec"],
                    "basis": "sound header",
                    "duration_source": i.get("duration_source", "header"),
                }
            try:
                d = wx.media_desc_from_header(head, order)
            except (struct.error, IndexError, ValueError):
                d = None
            if d and d["tracks"]:
                t = d["tracks"][0]
                return {
                    "duration_s": round(t["samples"] / float(t["rate"]), 4),
                    "loop": None,
                    "channels": t["channels"],
                    "rate": t["rate"],
                    "codec": "stream",
                    "tracks": len(d["tracks"]),
                    "cue_names": sorted(
                        {
                            c["name"]
                            for x in d["tracks"]
                            for c in x.get("cue_points") or ()
                            if c.get("name")
                        }
                    ),
                    "stream": d["stream"],
                    "basis": "stream descriptor",
                }
        return None

    def _sound_info(self):
        """audio/sound_info.json of the extract by lower-case asset path ({}
        when it is not there or does not parse)."""
        if self._info is None:
            self._info = {}
            try:
                with open(
                    os.path.join(self.out, "audio", "sound_info.json"), encoding="utf-8"
                ) as fh:
                    doc = json.load(fh)
                for name, rec in (doc.get("sounds") or {}).items():
                    if isinstance(rec, dict):
                        self._info[name.replace("\\", "/").lstrip("/").lower()] = rec
            except (OSError, ValueError):
                pass
        return self._info

    def duration_report(self):
        """Where the lengths of the waves looked up so far come from:
        {"codecs": {codec: n}, "sources": {source: n}, "without_duration":
        [asset path, ...]} -- stream descriptors and paths that are not a wave
        asset of the extract are left out of the last list."""
        codecs, sources, missing = {}, {}, []
        for k, w in sorted(self._wave.items()):
            if w is None:
                if (True, k) in (self._wavs or {}):
                    missing.append(k)
                continue
            if w.get("codec") == "stream":
                continue
            c = w.get("codec") or "decoded"
            codecs[c] = codecs.get(c, 0) + 1
            src = w.get("duration_source") or "none"
            sources[src] = sources.get(src, 0) + 1
        return {"codecs": codecs, "sources": sources, "without_duration": missing}

    # ---------------------------------------------------------- definitions
    def _leaf(self, n):
        s = n.p("sound") or n.p("streamingSound") or None
        w = self.wave(s) or {}
        return {
            "node": n.id,
            "wave": s,
            "duration_s": w.get("duration_s"),
            "loop": w.get("loop"),
            "volume": _round(n.p("volume")),
            "pitch": _round(n.p("pitch")),
            "random_pitch_pct": _round(n.p("randomPitchLength")),
            "random_volume_pct": _round(n.p("randomVolumeLength")),
            "range_m": [
                _round(_prop_any_case(n, "minRange")),
                _round(_prop_any_case(n, "maxRange")),
            ],
            "priority": _prop_any_case(n, "priority"),
        }

    def play_tree(self, n):
        """What one play of SoundDef `n` starts (0x831365): the engine's child
        list is the node itself followed by its SoundDef children."""
        kids = [c for c in n.children if c.cls == "SoundDef"]
        m = n.p("_iselectionmethod", 1)
        me = self._leaf(n)
        if m == 3 or not kids:
            t = dict(mode="self", **me)
        elif m == 4:
            parts = [self.play_tree(k) for k in kids]
            if me["wave"]:
                parts.append(dict(mode="self", **me))
            t = {"mode": "all_of", "node": n.id, "parts": parts}
        else:
            t = {
                "mode": "one_of",
                "node": n.id,
                "rule": SELECTION.get(m, m),
                "options": [dict(mode="self", **me)] + [self.play_tree(k) for k in kids],
            }
        return t

    def definition(self, rel, n):
        """Record of the SoundDef `n` of fragment `rel` (cached)."""
        k = _key(rel, n.id)
        if k not in self._defs:
            t = self.play_tree(n)
            lv = leaves(t)
            lo, hi = span(t)
            ds = [x["duration_s"] for x in lv if x["duration_s"]]
            g = self.resolve(n.p("m_esoundgroup"), rel)
            self._defs[k] = {
                "ref": [rel, n.id],
                "name": n.name or None,
                "group": (g[1].name or None) if g else None,
                "selection_method": n.p("_iselectionmethod"),
                "start_delay_s": [_round(n.p("_nmindelay")), _round(n.p("_nmaxdelay"))],
                "mission_speak": n.p("m_tmissionspeak"),
                "obstruction": _prop_any_case(n, "enableObstructionAndOcclusion"),
                "reverb_mix": _round(_prop_any_case(n, "reverbMixFactor")),
                "doppler": _round(_prop_any_case(n, "dopplerFactor")),
                "n_waves": len(lv),
                "missing_waves": sum(1 for x in lv if x["duration_s"] is None),
                "duration_s": {
                    "min": lo,
                    "max": hi,
                    "mean": _mean(ds) if ds else None,
                },
                "play": t,
            }
        return self._defs[k]

    def definition_of(self, ref, home):
        """Definition record an Entity value names, or None."""
        r = self.resolve(ref, home)
        if r is None or r[1].cls != "SoundDef":
            return None
        return self.definition(r[0], r[1])


def span(t):
    """(shortest, longest) seconds one play of a tree lasts: one_of = any
    option, all_of = the longest part (they start together)."""
    if t["mode"] == "self":
        return t.get("duration_s"), t.get("duration_s")
    sub = [span(x) for x in t.get("parts") or t.get("options")]
    sub = [s for s in sub if s[0] is not None]
    if not sub:
        return None, None
    if t["mode"] == "all_of":
        return round(max(s[0] for s in sub), 4), round(max(s[1] for s in sub), 4)
    return round(min(s[0] for s in sub), 4), round(max(s[1] for s in sub), 4)


def leaves(t):
    """The wave entries of a play tree."""
    if t["mode"] == "self":
        return [t] if t.get("wave") else []
    out = []
    for x in t.get("parts") or t.get("options"):
        out += leaves(x)
    return out


def fixed_wave(d):
    """(wave, seconds) when a definition always plays one known wave at its
    own pitch, else None: one leaf, no pitch jitter, no start-delay range."""
    if not d:
        return None
    lv = leaves(d["play"])
    if d["play"]["mode"] != "self" or len(lv) != 1 or not lv[0].get("duration_s"):
        return None
    lo, hi = d["start_delay_s"]
    if (lv[0].get("random_pitch_pct") or 0.0) != 0.0 or (lo or 0.0) != (hi or 0.0):
        return None
    pitch = lv[0].get("pitch") or 1.0
    return lv[0]["wave"], round((lo or 0.0) + lv[0]["duration_s"] / pitch, 4)


def blocks_while_playing(ignore_player, ignore_nonplayer):
    """Whose category-1 requests a PLAYING line with these two flags drops
    (SpeakCtrl.ShouldIgnoreThisSpeaker 0x83ae84): "all", "nonplayers", "players", "none"."""
    if ignore_player and ignore_nonplayer:
        return "all"
    if ignore_nonplayer:
        return "nonplayers"
    return "players" if ignore_player else "none"


def cue_hash(name):
    """Hash a MusicTrackCtrl.change_on_cue holds for the cue `name` (0x423ca1): the
    raw bit-CRC of the name's bytes, NOT folded -- `Click` and `click` differ."""
    return kapow_props.kapow_hash(name)


def cue_change(value, cue_names):
    """(mode, name) of a change_on_cue value: 0 = ("at_once", None); 1 = ("next_cue",
    None), the next cue point of any name; else ("named_cue", the cue of `cue_names`
    whose hash it is, or "unresolved")."""
    v = (value or 0) & 0xFFFFFFFF
    if v == 0:
        return "at_once", None
    if v == 1:
        return "next_cue", None
    for nm in cue_names or ():
        if cue_hash(nm) == v:
            return "named_cue", nm
    return "named_cue", "unresolved"


def name_cue_changes(setup, cue_names):
    """Adds `cue_names` (the cue names of the setup's stream; None when the descriptor
    was not read) to a music_setups() record and change_on_cue_mode / change_on_cue_name
    to every track, one-shot and group of its states."""
    setup["cue_names"] = cue_names
    for st in setup["states"]:
        for t in st["tracks"] + st.get("one_shots", []) + st.get("groups", []):
            t["change_on_cue_mode"], t["change_on_cue_name"] = cue_change(
                t["change_on_cue"], cue_names
            )
    return setup


def _brief(d):
    """A definition as other tables name it."""
    if d is None:
        return None
    return {
        "definition": d["ref"],
        "name": d["name"],
        "n_waves": d["n_waves"],
        "duration_s": d["duration_s"],
        "rule": d["play"].get("rule", d["play"]["mode"]),
    }


# ------------------------------------------------------------------- music
def music_setups(nodes, rel=None):
    """[{setup, stream, track_names, states, ...}] of the MusicSetup nodes in
    one fragment's {id: node}: the MusicStreamSlot it plays (`streamingSound` =
    the stream descriptor asset, track0..9 = the track names) and its
    MusicTrigger track states (per track target volume, fade, cue switch)."""
    out = []
    for n in nodes.values():
        if n.cls != "MusicStreamSlot":
            continue
        names = []
        for i in range(10):
            v = n.p("track%d" % i)
            names.append(v if isinstance(v, str) and v.strip() else None)
        while names and names[-1] is None:
            names.pop()
        setup = n.parent if n.parent is not None and n.parent.cls == "MusicSetup" else None
        rec = {
            "setup": setup.name if setup is not None else None,
            "ref": [rel, (setup or n).id],
            "stream_asset": n.p("streamingSound") or None,
            "track_names": names,
            "volume": _round(n.p("volume")),
            "states": [],
        }
        if setup is not None:
            d = setup.p("m_edefaultmusictrackstate")
            rec["default_state"] = d.get("ref") if isinstance(d, dict) else None
            rec["start_on_scene_activated"] = setup.p("m_tstartonsceneactivated")
            levels = {}
            for c in setup.descend("MusicIntensityDefinition"):
                for i in range(1, 6):
                    v = c.p("_emusicintensitylevel%02d" % i)
                    if isinstance(v, dict) and v.get("ref"):
                        levels.setdefault(v["ref"], []).append(i)
            for t in setup.kids("MusicTrigger"):
                tracks = [
                    {
                        "track": c.p("track_index"),
                        "volume": _round(c.p("volume")),
                        "fade_s": _round(c.p("fade_time")),
                        "change_on_cue": c.p("change_on_cue") or 0,
                    }
                    for c in t.kids("MusicTrackCtrl")
                ]
                st = {
                    "node": t.id,
                    "name": t.name,
                    "min_play_s": _round(t.p("m_nminplaytime")),
                    "max_play_s": _round(t.p("m_nmaxplaytime")),
                    "intensity_levels": sorted(levels.get(t.id, [])),
                    "tracks": tracks,
                }
                # every child whose type name contains SoundSlot and that has a sound is
                # played as a one-shot (MusicPlayer.play_one_off_sound 0x7cf896)
                one = []
                for c in t.children:
                    if "SoundSlot" not in (c.type or "") or c.cls == "MusicTrackCtrl":
                        continue
                    wave, stream = c.p("sound") or None, c.p("streamingSound") or None
                    if not (wave or stream):
                        continue
                    o = {"class": c.cls, "wave": wave}
                    if stream:
                        o["stream"] = stream
                    o["volume"] = _round(c.p("volume"))
                    o["change_on_cue"] = (
                        (c.p("change_on_cue") or 0)
                        if c.cls in ("MusicStaticSlot", "MusicOneOffSlot")
                        else 0
                    )
                    one.append(o)
                if one:
                    st["one_shots"] = one
                groups = [
                    {
                        "group": c.p("group"),
                        "volume": _round(c.p("volume")),
                        "fade_s": _round(c.p("fade_time")),
                        "change_on_cue": c.p("change_on_cue") or 0,
                    }
                    for c in t.children
                    if c.cls == "MusicGroupCtrl" and c.p("group")
                ]
                if groups:
                    st["groups"] = groups
                rec["states"].append(st)
        out.append(rec)
    out.sort(key=lambda r: (r["setup"] or "", r["ref"][1]))
    return out


def music_setups_from_bytes(data, name="x.fragment", order=None):
    """music_setups() of a raw .fragment payload ([] when it holds none)."""
    if b"MusicStreamSlot" not in data:
        return []
    import kapow_json as kj

    j = kj.to_json(name.lower(), data, order=order)
    if not j:
        return []
    return music_setups(asm.tree_from_json(j)[1], name.replace("\\", "/").lstrip("/"))


def track_labels(setups):
    """{stream descriptor asset (lower, no leading '/'): [track names]} -- the
    first setup that names a stream wins (the setups of one stream agree in
    the shipped data)."""
    out = {}
    for s in setups:
        a = (s.get("stream_asset") or "").replace("\\", "/").lstrip("/").lower()
        if a and s.get("track_names"):
            out.setdefault(a, s["track_names"])
    return out


# ------------------------------------------------------------------ tables
def _effect(db, rel, n):
    if n is None:
        return None
    o = {"ref": [rel, n.id], "name": n.name or None, "sounds": [], "speaks": []}
    for c in n.children:
        if c.cls == "EffectSound":
            pl = c.p("_iplacement")
            o["sounds"].append(
                dict(
                    _brief(db.definition_of(c.p("_esounddef"), rel)) or {"definition": None},
                    placement={0: "ENTITY", 1: "POS_AND_ORIENT"}.get(pl, pl),
                )
            )
        elif c.cls == "EffectSpeak":
            sid = c.p("_ispeakid")
            o["speaks"].append({"speak_id": sid, "speak": SPEAK_ID.get(sid)})
    return o


def _effect_of(db, ref, home):
    r = db.resolve(ref, home)
    return _effect(db, r[0], r[1]) if r and r[1].cls == "EffectBase" else None


def _subtitle_key(wave):
    """Key of the wave's rows in the subtitle table (text_assets.subtitle_key,
    SubtitleSlot 0x4d89d0); the texts are in `watchmen textmeta` output."""
    import text_assets

    return text_assets.subtitle_key(wave)


def _speak_groups(db, frags):
    out = {}
    for rel in frags:
        for n in db.nodes(rel).values():
            kids = [c for c in n.children if c.cls == "SpeakDefinition"]
            if not kids:
                continue
            g = {"ref": [rel, n.id], "name": n.name or None, "speaks": {}}
            for d in kids:
                M = bool(d.p("m_tallowmultipleevents"))
                P = bool(d.p("m_tignoreplayerspeakevents"))
                N = bool(d.p("m_tignorenoneplayerspeakevents"))
                cat = speak_category(M, P, N)
                voices, durs = [], []
                for v in d.kids("SpeakVoiceDefinition"):
                    sd = db.definition_of(v.p("m_espeaktyperef0"), rel)
                    vo = {"index": len(voices), "name": v.name or None}
                    if sd:
                        lv = leaves(sd["play"])
                        br = _brief(sd)
                        br["definition_name"] = br.pop("name")
                        vo.update(br)
                        vo["start_delay_s"] = sd["start_delay_s"]
                        vo["waves"] = [
                            {
                                "wave": x["wave"],
                                "duration_s": x["duration_s"],
                                "subtitle_key": _subtitle_key(x["wave"]),
                            }
                            for x in lv
                        ]
                        durs += [x["duration_s"] for x in lv]
                    else:
                        vo["definition"] = None
                    voices.append(vo)
                sid = d.p("m_ispeak")
                g["speaks"][str(sid)] = {
                    "speak_id": sid,
                    "speak": SPEAK_ID.get(sid),
                    "category": cat,
                    "start_speak": cat == 1,
                    "plays": cat != 0 and any(v.get("definition") for v in voices),
                    "play_probability": _round(d.p("m_nrandom")),
                    "quarantine_s": [
                        _round(d.p("m_nquarantinetimemin")),
                        _round(d.p("m_nquarantinetimemax")),
                    ],
                    "start_delay_s": _round(d.p("m_ndelay")),
                    "allow_multiple": M,
                    "ignore_player_events": P,
                    "ignore_nonplayer_events": N,
                    "blocks_while_playing": blocks_while_playing(P, N),
                    "duration_s": _stats(durs),
                    "voices": voices,
                }
            out[_key(rel, n.id)] = g
    return out


_DAMAGE_SLOTS = (
    "headfast headheavy headuber headweaponwood headweaponsteel headkill bodyfast bodyheavy "
    "bodyuber bodyweaponwood bodyweaponsteel bodykill sharpweapon stun knockdown block"
).split()


def _body_classes(db):
    """({class id: body class name}, {CharVisual fragment rel: row})."""
    import anim_meta
    import face_rule

    ids = {}
    for cn, path in anim_meta.find_class_fragments(db.out).items():
        try:
            root = asm.find_class_root(asm.load_tree(path, False))
        except (OSError, ValueError, KeyError):
            root = None
        cid = root.p("m_iclassid") if root is not None else None
        if cid is None:
            cid = face_rule._class_id_by_name(cn)
        if cid is not None:
            ids[cid] = cn
    rows = {}
    for r in face_rule.charvisual_table(db.out):
        rel = r["fragment"].replace("\\", "/")
        rel = rel[len("extracted/") :] if rel.startswith("extracted/") else rel
        rows[rel.lower()] = r
    return ids, rows


def _characters(db, frags, groups):
    try:
        class_ids, visuals = _body_classes(db)
    except Exception as ex:  # no class fragments in this extract
        db.log("  sound_meta: body classes: %s" % ex)
        class_ids, visuals = {}, {}
    fam = ee.family("CHARACTER_TYPES")
    anim = ee.family("CHARACTER_ANIMATIONS")
    chars, damage = {}, {}
    for rel in frags:
        for n in db.nodes(rel).values():
            if n.cls != "CharacterDef" or n.p("m_icharactertype") is None:
                continue
            ct = asm.s32(n.p("m_icharactertype"))
            rec = {
                "ref": [rel, n.id],
                "name": n.name or None,
                "character_type": ct,
                "character_type_name": fam.get(ct),
                "body_class": None,
                "body_class_id": None,
                "body_class_basis": "not resolved",
                "face_class_id": None,
                "footstep_effect_types": {k: foot_effect_type(ct, k) for k in FOOT_EFFECT},
            }
            mf = db.resolve(n.p("m_emodelfragment"), rel)
            vis = db.rel(mf[1].p("assetName")) if mf else None
            row = visuals.get((vis or "").lower())
            if row:
                rec.update(
                    visual_fragment=vis,
                    body_class_id=row["body_class_id"],
                    body_class_id_name=anim.get(row["body_class_id"]),
                    body_class=class_ids.get(row["body_class_id"]),
                    face_class_id=row["face_class_id"],
                    body_class_basis="data: CharacterDef.m_emodelfragment -> %s -> "
                    "AnimationCtrlWM.m_ianimationclassid" % os.path.basename(vis),
                )
            sd = db.resolve(n.p("m_echaractersounddef"), rel)
            if sd:
                s_rel, s = sd
                g = db.resolve(s.p("m_espeakref"), s_rel)
                gk = _key(g[0], g[1].id) if g else None
                rec["speak_group"] = gk if gk in groups else None
                rec["speak_group_name"] = g[1].name if g else None
                sp = groups.get(gk, {}).get("speaks", {})
                rec["n_voices"] = max([len(x["voices"]) for x in sp.values()] or [0])
                rec["attack_start_effects"] = {
                    k: _effect_of(db, s.p("_e%sattackeffect" % k), s_rel)
                    for k in ("light", "heavy", "weapon")
                }
            ed = db.resolve(n.p("m_echaractereffectdef"), rel)
            if ed and ed[1].cls == "CharacterEffectDef":
                k = _key(ed[0], ed[1].id)
                rec["damage_effects"] = k
                if k not in damage:
                    damage[k] = {
                        "ref": [ed[0], ed[1].id],
                        "name": ed[1].name or None,
                        "slots": {
                            sl: _effect_of(db, ed[1].p("_e" + sl), ed[0]) for sl in _DAMAGE_SLOTS
                        },
                    }
            chars[os.path.basename(rel)[: -len(".fragment")]] = rec
    return chars, damage


def _package_rows(db, rel, n, skip_ids=()):
    """(by_surface rows, owned surface ids) of one SoundPackageCtrl.  A package owns the
    surface of every SoundEffectType child, with or without a sound (initialize_local
    0x83304e); rows are only made for children that name a sound or an advanced effect.
    skip_ids: surface ids to leave out of the rows."""
    rows, owned = {}, []
    for e in n.kids("SoundEffectType"):
        sid = e.p("m_ieffecttypes")
        owned.append(sid)
        if sid in skip_ids:
            continue
        d = db.definition_of(e.p("m_eeffectsoundreference"), rel)
        a = db.resolve(e.p("m_eadvancedeffectreference"), rel)
        if d is None and a is None:
            continue
        k = (_key(*d["ref"]) if d else None, a[1].name if a else None)
        row = rows.setdefault(
            k,
            dict(
                _brief(d) or {"definition": None},
                advanced_effect=a[1].name if a else None,
                surfaces=[],
                surface_ids=[],
            ),
        )
        row["surfaces"].append(e.name or None)
        row["surface_ids"].append(sid)
    return list(rows.values()), sorted(x for x in set(owned) if isinstance(x, int))


def _footsteps(db, frags):
    foot_types = {v for row in FOOT_EFFECT.values() for v in row}
    out, defaults = {}, []
    for rel in frags:
        for n in db.nodes(rel).values():
            if n.cls != "SoundPackageCtrl" or n.p("m_ieffecttypes") not in foot_types:
                continue
            rows, owned = _package_rows(db, rel, n)
            ld = db.resolve(n.p("m_elocaldefault"), rel)
            rec = {
                "ref": [rel, n.id],
                "effect_type": n.p("m_ieffecttypes"),
                "name": n.name or None,
                "local_default": ld[1].name if ld else None,
                "by_surface": rows,
                "owned_surface_ids": owned,
            }
            effective = list(rows)
            if ld and ld[1].cls == "SoundPackageCtrl":
                # every surface the package has no child for comes from its local default
                # package (initialize_external 0x83325a)
                rec["inherits_from"] = {
                    "ref": [ld[0], ld[1].id],
                    "effect_type": ld[1].p("m_ieffecttypes"),
                    "name": ld[1].name or None,
                }
                effective = effective + _package_rows(db, ld[0], ld[1], skip_ids=set(owned))[0]
                defaults.append(ld)
            rec["effective_by_surface"] = effective
            out[str(n.p("m_ieffecttypes"))] = rec
    for drel, dn in defaults:  # a default package that is not a foot type itself
        key = str(dn.p("m_ieffecttypes"))
        if key in out:
            continue
        rows, owned = _package_rows(db, drel, dn)
        ld = db.resolve(dn.p("m_elocaldefault"), drel)
        out[key] = {
            "ref": [drel, dn.id],
            "effect_type": dn.p("m_ieffecttypes"),
            "name": dn.name or None,
            "role": "local_default",
            "local_default": ld[1].name if ld else None,
            "by_surface": rows,
            "owned_surface_ids": owned,
        }
    return out


def _fragment_events(db, state):
    """[(event node, fragment it was read from or None, source label)] of a
    body state: its own events (asm.state_events) and the events of the
    fragments its `Events` folders include (SoundEvents/SE_<clip>.fragment)."""
    # a class tree loaded by anim_meta has the event lists spliced in already: the state's
    # own events first, then each list in the order of its FragmentNode, as before
    out = [(e, None, "state") for e in asm.state_events(state) if not _spliced_from(e)]
    stack = list(state.children)
    while stack:
        n = stack.pop(0)
        if n.cls == "FragmentNode":
            rel = db.rel(n.p("assetName"))
            spliced = [c for c in n.children if c.frag is not None]
            if rel and spliced:
                for e in asm.walk(spliced):
                    if e.cls == asm.CLS_EVENT:
                        out.append((e, rel, os.path.basename(rel)))
            elif rel:
                for e in db.nodes(rel).values():
                    if e.cls == asm.CLS_EVENT:
                        out.append((e, rel, os.path.basename(rel)))
        elif n.cls not in (asm.CLS_STATE, asm.CLS_TRANS, asm.CLS_GROUP):
            stack[0:0] = n.children
    return out


def _spliced_from(e):
    """Asset path of the event-list fragment spliced under a FragmentNode that the
    event node `e` belongs to, or None (an event of the class tree itself)."""
    n = e
    while n is not None and n.cls not in (asm.CLS_STATE, asm.CLS_GROUP, asm.CLS_CLASS):
        if n.frag is not None and n.parent is not None and n.parent.cls == "FragmentNode":
            return n.frag
        n = n.parent
    return None


def tree_home(db, node, class_rel):
    """Fragment key of a node of a spliced class tree."""
    n = node
    while n is not None:
        if n.frag is not None:
            return db.rel(n.frag)
        n = n.parent
    return class_rel


def event_sound(db, ev, home):
    """Definition record of a SOUND event's `_etarget00`, or None.  home: the
    fragment the event node was read from (tree_home for a spliced class tree)."""
    return db.definition_of(ev.p("_etarget00"), home)


def _class_states(db, chars, groups, anim=None):
    import anim_meta

    out = {}
    try:
        classes = anim_meta.load_classes(db.out)
    except Exception as ex:
        db.log("  sound_meta: classes: %s" % ex)
        return out
    for cn, c in sorted(classes.items()):
        class_rel = os.path.relpath(c["fragment"], db.root).replace(os.sep, "/")
        recs = {}
        for s in ((anim or {}).get("classes", {}).get(cn) or {}).get("states", []):
            recs.setdefault((s["path"], s["name"]), s)
        mine = {
            k: v for k, v in chars.items() if v.get("body_class") == cn and "speak_group" in v
        }  # a definition without a CharacterSoundDef is a head (BIKER_HEAD), not a character
        states = []
        for s in c["nodes"]:
            if s.cls != asm.CLS_STATE:
                continue
            path = anim_meta._path(s)
            m = recs.get((path, s.name))
            evs = []
            for e, rel, src in _fragment_events(db, s):
                eid = e.p("m_ianimationevent")
                if eid not in EV_NAMES:
                    continue
                trig = asm.event_trigger(e)
                raw = round(asm.event_at(e), 4)
                o = {
                    "event": EV_NAMES[eid],
                    "event_id": eid,
                    "trigger": ee.name("ANIMATION_EVENT_TYPES", trig, "TRIGGER_%s" % trig),
                    "raw": raw,
                    "source": src,
                }
                if m is not None:
                    pp, _ts, pt = asm.event_timing(
                        trig,
                        raw,
                        m.get("duration_s"),
                        m.get("speed") or 1.0,
                        float(m.get("start_playpos") or 0.0),
                        bool(m.get("loop")),
                    )
                    o["playpos"] = _round(pp)
                    o["t_s"] = _round(pt)
                if eid == EV_SOUND:
                    home = rel or tree_home(db, e, class_rel)
                    d = event_sound(db, e, home)
                    o["speak_flag"] = bool(e.p("m_ttruth1"))
                    o["position"] = {0: "world", 1: "follow"}.get(
                        e.p("m_ivalue00"), e.p("m_ivalue00")
                    )
                    o.update(_brief(d) or {"definition": None})
                    fw = fixed_wave(d)
                    if fw:
                        o["wave"] = fw[0]
                elif eid == EV_SPEAK:
                    sid = e.p("m_ivalue00")
                    o["speak_id"] = sid
                    o["speak"] = SPEAK_ID.get(sid)
                    o["stops_current_speech_first"] = bool(e.p("m_ttruth1"))
                    o["category_by_character"] = {
                        k: effective_category(
                            groups.get(v.get("speak_group"), {}).get("speaks", {}).get(str(sid))
                        )
                        for k, v in sorted(mine.items())
                    }
                else:
                    o["footstep"] = EV_FOOT[eid]
                evs.append(o)
            if not evs:
                continue
            evs.sort(key=lambda o: (o.get("t_s") is None, o.get("t_s") or 0.0, o["raw"]))
            row = {"state": s.name, "path": path, "events": evs}
            if m is not None:
                row.update(
                    main_clip=m.get("main_clip"),
                    duration_s=m.get("duration_s"),
                    speed=m.get("speed"),
                )
            states.append(row)
        out[cn] = {"fragment": class_rel, "characters": sorted(mine), "states": states}
        gone = anim_meta.missing_event_lists(c["nodes"])
        if gone:  # a state names an event-list fragment the data does not contain
            out[cn]["missing_event_lists"] = gone
    return out


def _face_talk(classes, chars, groups):
    out = {}
    for cn, c in classes.items():
        baked, lines_ev = [], []
        for st in c["states"]:
            for e in st["events"]:
                base = {
                    "state": st["state"],
                    "path": st["path"],
                    "main_clip": st.get("main_clip"),
                    "t_s": e.get("t_s"),
                    "playpos": e.get("playpos"),
                }
                if e["event_id"] == EV_SOUND and e.get("speak_flag"):
                    d = e.get("duration_s") or {}
                    fixed = bool(e.get("wave"))
                    baked.append(
                        dict(
                            base,
                            definition=e.get("definition"),
                            wave=e.get("wave"),
                            talk_s=d.get("max") if fixed else None,
                            fixed=fixed,
                            duration_s=d,
                        )
                    )
                elif e["event_id"] == EV_SPEAK and 1 in e["category_by_character"].values():
                    lines_ev.append(
                        dict(
                            base,
                            speak_id=e["speak_id"],
                            speak=e["speak"],
                            characters=sorted(
                                k for k, v in e["category_by_character"].items() if v == 1
                            ),
                        )
                    )
        lines, silent = {}, {}
        for ch in c["characters"]:
            sp = groups.get(chars[ch].get("speak_group"), {}).get("speaks", {})
            lines[ch] = {
                sid: {
                    "speak": s["speak"],
                    "play_probability": s["play_probability"],
                    "quarantine_s": s["quarantine_s"],
                    "start_delay_s": s["start_delay_s"],
                    "talk_s": s["duration_s"],
                    "voices": [
                        {
                            "index": v["index"],
                            "name": v["name"],
                            "definition": v.get("definition"),
                            "talk_s": (
                                dict(v["duration_s"], n=v["n_waves"])
                                if v.get("definition")
                                else None
                            ),
                        }
                        for v in s["voices"]
                    ],
                }
                for sid, s in sp.items()
                if s["category"] == 1 and s["plays"]
            }
            silent[ch] = sorted(int(sid) for sid, s in sp.items() if s["category"] != 1)
        out[cn] = {
            "characters": c["characters"],
            "fixed_talk_events": baked,
            "line_events": lines_ev,
            "lines": lines,
            "closed_mouth_speak_ids": silent,
        }
    return out


class Speech:
    """What the face rule needs from the sound data of one EXTRACT_OUT: the
    sound of a speak-flag SOUND event, the category of a line per character,
    and the talk-clip lengths of the lines the AI requests."""

    def __init__(self, extract_out, log=None):
        self.db = SoundDB(extract_out, log)
        frags = self.db.sound_fragments()
        self.groups = _speak_groups(self.db, frags)
        self.chars = _characters(self.db, frags, self.groups)[0]

    def _speaks(self, ch):
        return self.groups.get(self.chars[ch].get("speak_group"), {}).get("speaks", {})

    def characters(self, body_class):
        return sorted(
            k
            for k, v in self.chars.items()
            if v.get("body_class") == body_class and "speak_group" in v
        )

    def event_sound(self, ev, class_fragment):
        """{definition, name, n_waves, duration_s, rule, wave?, talk_s?} of a
        SOUND event node of a class tree (talk_s only for one fixed wave)."""
        class_rel = os.path.relpath(class_fragment, self.db.root).replace(os.sep, "/")
        d = event_sound(self.db, ev, tree_home(self.db, ev, class_rel))
        if d is None:
            return None
        out = _brief(d)
        fw = fixed_wave(d)
        if fw:
            out["wave"], out["talk_s"] = fw
        return out

    def categories(self, body_class, speak_id):
        """{character: category or None (the group has no such line)}."""
        return {
            ch: effective_category(self._speaks(ch).get(str(speak_id)))
            for ch in self.characters(body_class)
        }

    def talk_clips(self):
        """Per character the category-1 lines with the talk time per voice, and
        the speak ids that never open the mouth."""
        out = {}
        for ch, c in sorted(self.chars.items()):
            if "speak_group" not in c:
                continue
            sp = self._speaks(ch)
            out[ch] = {
                "body_class": c.get("body_class"),
                "face_class_id": c.get("face_class_id"),
                "speak_group": c.get("speak_group_name"),
                "lines": {
                    sid: {
                        "speak": x["speak"],
                        "play_probability": x["play_probability"],
                        "quarantine_s": x["quarantine_s"],
                        "talk_s": x["duration_s"],
                        "voices": [
                            {
                                "index": v["index"],
                                "name": v["name"],
                                "definition": v.get("definition"),
                                "talk_s": (
                                    dict(v["duration_s"], n=v["n_waves"])
                                    if v.get("definition")
                                    else None
                                ),
                            }
                            for v in x["voices"]
                        ],
                    }
                    for sid, x in sorted(sp.items(), key=lambda kv: int(kv[0]))
                    if x["category"] == 1 and x["plays"]
                },
                "closed_mouth_speak_ids": sorted(
                    int(sid) for sid, x in sp.items() if x["category"] != 1
                ),
            }
        return out


SPEAK_TRIGGERS = [
    (
        [20, 21],
        "Enemy.StateActive 0x725392 / 0x7254a1; ReturnToCombatZone.StopAndTaunt 0x7ff775",
        "a target is spotted (A = Rorschach, B = Nite Owl); taunt at the combat-zone border",
    ),
    ([18, 19], "Enemy.StateActive 0x725235", "target spotted, told to the group"),
    ([3], "Enemy.StateActive 0x725535", "generic TARGET_SPOTTED"),
    ([5], "Enemy.SetState 0x715404; CombatPartner.StateActive 0x6ed2ac", "entering combat"),
    ([22, 23], "Enemy.command_got_up 0x722f8b; Partner 0x7d9a66", "after getting up"),
    ([24, 25], "AttackEnemy.command_may_attack 0x600658", "the orchestrator grants an attack"),
    ([6], "AttackEnemy.StateActive 0x5ffab0", "generic MELEE"),
    ([1], "AttackEnemy.command_taunt 0x6006d8; 0x7ff895; 0x8164de", "generic TAUNT"),
    ([17], "hangback.StateActive 0x75e9af; Partner.StateActive 0x7db33e", "asks for help"),
    ([2], "CharacterRoot.command_you_killed_me 0x690077", "sent to the killer"),
    ([32], "CharacterRoot.StateDead 0x6bb1c1", "death, unless m_tnodeathscream"),
    ([10, 11, 15], "partner AI 0x6e1e40, 0x602d6d, 0x6f1c9b", "special / throw taunts"),
    (
        [8],
        "SPEAK animation events; UnderbossPhase1.command_hit_by 0x888e62",
        "counter-attack taunt: Part 2 Enemy01 state 31, EnemyBig 25 / 27; Part 1 also Enemy03 "
        "and Underboss",
    ),
    ([9], "SPEAK animation events only (Part 1 Enemy03)", "no sender in Part 2"),
    ([36], "SPEAK animation event only (Part 1 Underboss state 17)", "no sender in Part 2"),
    ([37], "none", "no code constant, SPEAK event or EffectSpeak in either part"),
    ([26, 27, 29, 30, 31], "EffectSpeak.Fire 0x714e00 (_ispeakid)", "damage effect sets"),
    (
        [33, 34],
        "UnderbossPhase1.command_flamer_done 0x88e8c1; StateActive 0x895319 / 0x895421",
        "Underboss lines",
    ),
]


def _trigger_evidence(sender):
    """Evidence of a SPEAK_TRIGGERS row: the rows whose sender is data-driven say so."""
    if sender == "none":
        return (
            "read: no code site passes the id; data: no SPEAK event or effect set of the "
            "six sets carries it"
        )
    if "SPEAK" in sender or "EffectSpeak" in sender:
        return "read (code sites); data: SPEAK events and effect sets of the export"
    return "read (constants at the sites)"


def build(extract_out, anim=None, log=None):
    """The whole table.  anim: an anim_meta dict (or its path): gives the
    events their play time in seconds (clip durations are not in the
    fragments); without it events carry the raw trigger value only."""
    import kapow_json as _kj

    with _kj.tree_cache(os.path.join(extract_out, "extracted")):  # the extract is only read
        return _build(extract_out, anim, log)


def _build(extract_out, anim, log):
    log = log or (lambda *a: None)
    if isinstance(anim, str):
        with open(anim, encoding="utf-8") as fh:
            anim = json.load(fh)
    db = SoundDB(extract_out, log)
    frags = db.sound_fragments()
    groups = _speak_groups(db, frags)
    chars, damage = _characters(db, frags, groups)
    classes = _class_states(db, chars, groups, anim)
    foot = _footsteps(db, frags)
    music = []
    for rel in frags:
        for s in music_setups(db.nodes(rel), rel):
            w = db.wave(s["stream_asset"]) or {}
            s["stream"] = w.get("stream")
            s["tracks"] = w.get("tracks")
            s["duration_s"] = w.get("duration_s")
            name_cue_changes(s, w.get("cue_names"))
            music.append(s)
    for rel in frags:  # every top-level definition, referenced or not
        for n in db.nodes(rel).values():
            if n.cls == "SoundDef" and (n.parent is None or n.parent.cls != "SoundDef"):
                db.definition(rel, n)
    nwav = len({x["wave"].lower() for d in db._defs.values() for x in leaves(d["play"])})
    log(
        "  sound_meta: %d fragments, %d definitions (%d waves), %d speak groups, %d characters"
        % (len(frags), len(db._defs), nwav, len(groups), len(chars))
    )
    rep = db.duration_report()
    if rep["without_duration"]:
        log(
            "  sound_meta: note: %d sound assets have no duration (header not read, no decoded file): %s"
            % (
                len(rep["without_duration"]),
                ", ".join(rep["without_duration"][:5])
                + (" ..." if len(rep["without_duration"]) > 5 else ""),
            )
        )
    console = sorted(c for c in rep["codecs"] if c in ("mp3", "xma2"))
    if console:
        log(
            "  sound_meta: %s durations: %s"
            % (
                " / ".join(console),
                ", ".join("%s %d" % kv for kv in sorted(rep["sources"].items())),
            )
        )
    out = _table(db, groups, chars, damage, classes, foot, music)
    if console or rep["without_duration"] or db.reparsed:
        # console extracts only (a PC table is unchanged): what the lengths are
        out["wave_durations"] = dict(
            rep,
            reparsed_fragments=dict(sorted(db.reparsed.items())),
            note="console sound headers store the sample count in whole codec frames: "
            "X360 XMA2 frames x 512 (0 - 0.02 s over the PC length), PS3 MP3 frames x 1152 "
            "with the encoder delay inside (0.03 - 0.06 s over the PC length; measured on "
            "the 2,921 Part-2 and 3,953 Part-1 sounds).  sources: header = that count, "
            "frame_count = counted frames x frame size (the header count was 0), decoded = "
            "the length of the decoded file in audio/.  without_duration: sound assets "
            "whose header no reader took and that have no decoded file (their duration_s "
            "is null everywhere)",
        )
    import canonical_names

    # strings that name a file of the export: spelled as that file is written
    return canonical_names.respell_export(out, extract_out)


def _table(db, groups, chars, damage, classes, foot, music):
    return {
        "format": FORMAT,
        "conventions": {
            "reference": "[fragment path under extracted/, node id]; table keys are "
            "'<fragment>#<node id>'",
            "wave": "asset path as the definition names it; the decoded file is "
            "audio/<path> of the same extract",
            "duration_s": "samples / sample rate of the sound header; a play tree's min / max "
            "is over its options (one_of) or the longest part (all_of)",
            "play": "mode self = this wave; one_of = one option per play (the node itself is "
            "option 0): random_no_immediate_repeat = random start index, never the index "
            "played last, first not quarantined; random_start_first_free; round_robin; "
            "all_of = every part starts together",
            "jitter": "played pitch = pitch * (1 + r * random_pitch_pct / 100), volume "
            "likewise, clamped to 0..1; r uniform in -1..1",
            "speech_category": "0 never plays and never opens the mouth (no START_SPEAK is "
            "sent); 1 exclusive line, opens the mouth (START_SPEAK at its start, after the "
            "line's start_delay_s); 2 grunt / shout, never opens the mouth.  "
            "category_by_character on a SPEAK event: null = the character's group has no "
            "such line, 0 also when the line has no sound.  The mouth closes when no voice "
            "has the character root as pivot (STOP_SPEAK), so a talk segment is as long as "
            "the wave that was drawn: a bake of it has to add start_delay_s and is one "
            "instance per (character, voice, wave)",
            "voice": "a character draws one voice index at its first line and keeps it",
            "subtitle_key": "on the waves of a speak voice: the key its subtitle rows have "
            "in the in-game subtitle table (wave file name cut at the first '_uk', then the "
            "first '_pc'; the cuts are case-sensitive, the table lookup folds A-Z, 0x4d89d0 "
            "/ 0x4d24aa); the table and the texts per language are in the `textmeta` output",
            "t_s": "seconds of play time since the state was entered at its default start "
            "(needs anim_meta); raw = the trigger's own value (play position or seconds)",
            "footstep": "effect type from the character type and the event (step / jump / "
            "stop), surface from the ground probe (model, else texture, else DEFAULT); a "
            "surface the package has no SoundEffectType child for is taken from its local "
            "default package (0x83325a); a child without a sound, or no entry in either "
            "package, is silent.  The footstep's voice has the character root as "
            "pivot (CharacterRootLogic passes _echaracterroot; 0x830fe5 -> 0x4c3602), so "
            "while it sounds the face is not sent STOP_SPEAK",
        },
        "evidence": _EV,
        "selection_methods": {str(k): v for k, v in SELECTION.items()},
        "speak_ids": {str(k): v for k, v in SPEAK_ID.items()},
        "characters": chars,
        "classes": classes,
        "speak_groups": groups,
        "speak_triggers": [
            {"speak_ids": a, "sender": b, "when": c, "evidence": _trigger_evidence(b)}
            for a, b, c in SPEAK_TRIGGERS
        ],
        "speak_rules": {
            "blocking": "read 0x83ae84: a category-1 request is dropped while any playing line has "
            "ignore_player_events and ignore_nonplayer_events, or ignore_nonplayer_events and the "
            "speaker is not a player, or ignore_player_events and the speaker is a player "
            "(CharacterDef.m_iplayablecharacter != -1).  The flags are those of the PLAYING line.  "
            "Category 2 is never dropped; category 0 always; a CharacterRoot speaker without "
            "m_echaractervisual always.  Checked when the request is made (0x8419b3) and every "
            "frame while it waits (0x83d414).",
            "priority": "m_ipriority is copied into the request (0x83e397) and never read.",
        },
        "face_talk": _face_talk(classes, chars, groups),
        "footsteps": {
            "effect_type_by_character_type": {
                "0": {k: v[0] for k, v in FOOT_EFFECT.items()},
                "1": {k: v[1] for k, v in FOOT_EFFECT.items()},
                ",".join(str(t) for t in FOOT_FEMALE_TYPES): {
                    k: v[2] for k, v in FOOT_EFFECT.items()
                },
                "other": {k: v[3] for k, v in FOOT_EFFECT.items()},
            },
            "default_surface": FOOT_DEFAULT_SURFACE,
            "rows": foot,
        },
        "effects": {
            "damage_rule": "rage hit -> uber; killing hit -> kill; weapon hit -> by the "
            "weapon's effect type (wood / steel; sharp = the one sharpweapon slot; taser = effect id 1, "
            "then steel); else damage poses "
            "1, 2, 5, 6, 23, 24 -> fast, others -> heavy; upper-body pose -> head*, else "
            "body*; knockdown poses 17, 18, 27, 28 add knockdown; stun poses 19-22 add stun",
            "attack_start_rule": "fired once per animation state by "
            "CharacterRootLogic.command_update_combo_timing 0x68810a (sent every frame from "
            "CharacterRoot.StateActive) when the state has m_tisattackstate and "
            "max(impact - _ncleardeadzoneoverride, impact - 0.2 s) <= t < impact (t = main "
            "blend-source time); holding a weapon -> weapon effect; else list index = "
            "m_issuedattacks[m_icurrentattackindex] (1 when out of range), 0 = heavy, 1 = light; "
            "fired at the character's centre",
            "ragdoll_contact": {
                "volume": "min(1, (|F| / mass_A / 200 + 0.3) ** 0.25)",
                "bone_masks": {
                    "RAGDOLL_HEAD": 3,
                    "RAGDOLL_BODY": 1492092,
                    "RAGDOLL_ARM": 15232,
                    "RAGDOLL_FOOT": 589824,
                },
                "bone_mask_bits": "ANIMATIION_BONE_TYPES",
                "first_match_wins": True,
                "lookup": "get_sound_in_package_based_on_enum(body part type, surface type from "
                "the model, else the texture, else 6 DEFAULT); against another ragdoll the "
                "second key is its body part type",
                "gates": {
                    "force_above": "CharacterVisualDef.m_nragdollimpactforcethresholdforsound",
                    "mean_speed_above_m_s": 2.0,
                    "min_interval_s_per_group": 0.5,
                    "interval_clock": "game time",
                },
                "evidence": "read 0x69d00a, 0x67a2ba, 0x69e5e6-0x69e64e, 0x8b468e, 0x8a9cd3",
            },
            "damage_effect_sets": damage,
        },
        "music": music,
        "music_rules": {
            "change_on_cue": "0 = at once; 1 = at the next cue point of any name; other "
            "= at the cue whose name hash equals it (0x423ca1: bit-serial CRC, low bit of each "
            "byte first, start 0, polynomial 0x04C11DB7, bytes not folded).  One pending change "
            "per track, a later one overwrites (0x7cf77c, 0x7cfb52).  A cue string may hold "
            "several names separated by '/'.  change_on_cue_mode / change_on_cue_name of a "
            "track say which case it is and name the cue of the setup's stream "
            "(`unresolved` when no cue of that stream has the hash).",
            "playback": "every track of the setup's stream starts together at the stream start "
            "with volume 0, each on its own controller with the square-root volume curve, in "
            "the first child of the music group node (the menu music group when the setup has "
            "m_tplayinmenu) (MusicPlayer.command_allocate 0x7cf2a8); a state only sets volumes; "
            "a track the state does not list keeps its volume and any change still waiting for "
            "a cue (track_switch 0x7cf77c)",
            "cue_source": "the cue event is registered on the controller of track 0 only "
            "(0x7cf2a8); that this controller reports only track 0's markers is inferred",
            "one_shots": "a child whose type name contains SoundSlot and that has a sound plays "
            "at once (change_on_cue 0), at the next cue (1) or at the named cue; a slot already "
            "waiting is not queued again (play_one_off_sound 0x7cf896); the truth argument of "
            "MusicTrigger.command_trig (Play Static, _tforceplaystatic) is never read "
            "(0x7d1113)",
        },
        "definitions": dict(sorted(db._defs.items())),
        "unresolved_instances": dict(sorted(db.unresolved.items())),
        "not_established": [
            "listener: the 2D path",
            "SoundDef.Active on PC Part 1 (no executable; Xbox 360 Part 1 0x82b21808 and PS3 "
            "Part 1 0xb67090 read: no playing-leaf lookup)",
        ],
    }


def write(extract_out, out_json, anim=None, log=print):
    import extract_out as _xo

    _xo.require(extract_out)  # a mistyped folder is an error, not an empty table
    meta = build(extract_out, anim=anim, log=log)
    with open(out_json, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(meta, fh, indent=1)
    return meta


def summary(meta):
    ev = sum(len(s["events"]) for c in meta["classes"].values() for s in c["states"])
    return "%d definitions, %d speak groups, %d characters, %d classes (%d sound events), " % (
        len(meta["definitions"]),
        len(meta["speak_groups"]),
        len(meta["characters"]),
        len(meta["classes"]),
        ev,
    ) + "%d footstep rows, %d music setups" % (len(meta["footsteps"]["rows"]), len(meta["music"]))


def main(argv):
    if len(argv) < 3 or argv[1] in ("-h", "--help"):
        print("usage: sound_meta.py EXTRACT_OUT OUT.json [ANIM_META.json]")
        return 0 if len(argv) > 1 else 2
    meta = write(argv[1], argv[2], anim=argv[3] if len(argv) > 3 else None)
    print("wrote %s: %s" % (argv[2], summary(meta)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
