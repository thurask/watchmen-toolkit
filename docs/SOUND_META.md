# sound_meta.json - what the game plays, when, and for how long

`python3 watchmen.py soundmeta EXTRACT_OUT OUT.json [ANIM_META.json]`; `characters` writes the
same table to `OUT_DIR/sound_meta.json`. Format `watchmen-sound-meta/1`. Built from the fragments
and the sound headers of an extract; event times in seconds need the clip durations of
`anim_meta.json` (built on the fly when not given).

Part 2 PC: 1,030 definitions, 9 speak groups, 14 characters, 5 body classes with 3,880 sound
events, 12 footstep rows, 24 music setups.

Evidence levels are in the top-level `evidence` dict, one line per table: *read* = traced in the
executable (address given), *data* = measured on the game files.

## References

`[fragment path under extracted/, node id]`. Node ids repeat across fragments, so an id alone does
not name a node; table keys are `<fragment>#<id>`. In the game data an Entity value is
`{"ref": id}` (same fragment) or `{"xref": [a, ..., id]}`, where a leading element is the id of a
`FragmentNode` (its `assetName` is the next fragment) or the name hash of a fragment's file stem.
References that leave the known fragments are counted in `unresolved_instances`.

## Asset strings

A string that names a file of the export (a `.fragment`, `.model`, `.particle`, `.bmp`, `.wav`,
`.mediastream_s` ... path) is spelled as that file is written, and the string the game stores is
kept in the same record under `stored`, `{field: value as stored}`, where it differs (for a map
whose keys are respelled, `{key written: key stored}` beside the map). `asset_names` at the top
level says so (`spelling: "export"`, `respelled`: how many strings). `--names stored` writes the
stored strings and neither key. See "Asset strings in the JSON files" in the README.
In this table that is the `stream` of a music setup (`/derived_pc/sounds/Music/...` against the
archive entry `files/derived_pc/sounds/music/...`: 24 strings on PC Part 2, 20 on PS3 Part 1).

## `definitions`

One record per top-level `SoundDef`: `name`, `group` (mix group), `start_delay_s` [min, max],
`n_waves`, `duration_s` {min, max, mean}, `play`.

`play` is what one "play" starts (`SoundDef.command_sounddef_play_all` 0x831365):

| `mode` | Meaning |
|---|---|
| `self` | this wave: `wave`, `duration_s`, `loop`, `volume`, `pitch`, `random_pitch_pct`, `random_volume_pct`, `range_m`, `priority` |
| `one_of` | one of `options` per play; the node itself is option 0. `rule`: `random_no_immediate_repeat` (random start index, never the one played last), `random_start_first_free`, `round_robin` |
| `all_of` | every entry of `parts` starts together (layered hits); each part chooses for itself |

Played pitch = `pitch * (1 + r * random_pitch_pct / 100)`, volume likewise (clamped to 0..1),
r uniform in -1..1. `wave` is the asset path; the decoded file is `audio/<path>`.

## `classes`

Per body animation class the states that fire sound events, each with `events` in time order:
`event` (SOUND, SPEAK, LEFT/RIGHT_FOOT_DOWN, FOOT_DOWN_JUMP, FOOT_DOWN_STOP), `trigger`, `raw`
(play position or seconds), `playpos`, `t_s` (seconds since the state was entered at its default
start), `source` (`state` or the `SE_<clip>.fragment` the state includes; the file name as stored:
one list is `se_finished_by_NO_victim02.fragment`, lower case, 9 events on Part 2 and 3 on Part 1, so
count list events by `source != "state"`). `missing_event_lists` (only when there are any): the
asset names of event lists a state includes that the data does not contain, sorted, with repeats
(1 on Part 2: `Enemy04`, `SE_RSH_COM_ATT_counter_EN4_B.fragment`; 5 on Part 1, `Enemy03`); the game
has nothing to include there. Means are rounded to 4 decimals from an exactly rounded sum
(`math.fsum`), so the table does not depend on the Python version.

- SOUND: `definition`, `name`, `n_waves`, `duration_s`, `rule`, `wave` (only when the definition
  always plays one wave), `speak_flag` (the sound is a voice line: the face gets START_SPEAK),
  `position` (`world` = left at the place it started, `follow` = attached to the character).
- SPEAK: `speak_id`, `speak`, `stops_current_speech_first`, `category_by_character`.
- foot events: `footstep` = `step` / `jump` / `stop`; the sound depends on the character type and
  the ground surface, see `footsteps`.

## `characters`

The body class is read from the fragments (`CharacterDef` -> its CharVisual fragment -> the
`AnimationCtrlWM` class id), not from a table: Gimp and GimpGagBall are `EnemyBig` (EN2), like
ThugBig; an earlier research table had them as `Enemy01`.

Per character definition: `character_type`, `body_class` (+ `body_class_basis`),
`face_class_id`, `speak_group`, `n_voices`, `attack_start_effects` (light / heavy / weapon),
`damage_effects` (key into `effects.damage_effect_sets`), `footstep_effect_types`.

## `speak_groups`

Per group the lines by speak id: `category` (0 never plays and never opens the mouth, 1 exclusive line -
opens the mouth after `start_delay_s`, 2 grunt or shout - never opens the mouth), `play_probability`, `quarantine_s`, `start_delay_s`,
`duration_s`, and `voices` in the game's order (a character draws one voice index at its first
line and keeps it): `name`, `definition`, `rule`, `waves` with durations and `subtitle_key`
(the key of the wave's rows in the subtitle table: the wave's file name cut at the first `_uk`,
then the first `_pc` — case-sensitive cuts; the table lookup folds A–Z; the texts are in the
`watchmen textmeta` output, TEXT_ASSETS.md).

## `footsteps`

`effect_type_by_character_type`: which row a foot event uses (Rorschach, Nite Owl, the female
types 28 / 33 / 35, everyone else; step / jump / stop). `rows.<effect type>.by_surface`: the
surfaces that share a definition. The surface comes from the ground (model, else texture, else
`DEFAULT`). A package owns the surfaces it has a `SoundEffectType` child for
(`owned_surface_ids`); every other surface is taken from its `local_default` package (read from
code, 0x83304e, 0x83325a, lookup 0x6e0f13). `effective_by_surface` is the result,
`inherits_from` the package used. A surface is silent when the owning child has no sound or
neither package has it. Measured: on PC Part 2 rows 53, 61, 62, 63, 65, 66 own no surface
(defaults 33, 58, 58, 58, 64, 64); on PC Part 1 rows 53, 54, 61, 62, 63, 65, 66 (defaults 33,
33, 58, 58, 58, 64, 64). Package 58 `CHARACTER_FOOT_WALK_STOP` is written with `role:
local_default`. On Part 1 it has a default of its own (33) and owns all 72 surface ids, so
nothing passes through. Only one level of default is followed; whether a chain of local
defaults resolves in general is not established.

## `effects`

`damage_effect_sets`: per `CharacterEffectDef` the 16 slots (`headfast` ... `block`), each with
its `sounds` (definition + `placement`) and `speaks` (speak id). `damage_rule` and
`attack_start_rule` say which slot a hit or an attack start uses. A weapon hit goes by the
weapon's effect type: wood, steel, sharp = the one `sharpweapon` slot, taser = effect id 1
first, then the steel slot (the sentence said "sharp adds sharpweapon" before 2026-10-04; no
table changed). The same rule as data, with the particle side of each effect, is the `fx` block
of `anim_meta.json` (FX_META.md).

## `face_talk` and the face rule

`fixed_talk_events`: SOUND events with the speak flag; `fixed` = the definition plays one wave, so
the talk has a known length `talk_s` and is baked into the clip's face track. `line_events`: SPEAK
events whose line is category 1 for some character (random voice and wave: not baked). `lines`:
per character the category-1 lines with `talk_s` per voice - the length a talk clip for that line
needs. `closed_mouth_speak_ids`: lines that never open the mouth. The same per-character table is
in `anim_meta.json` under `face.talk_clips`.

## `music`

Per `MusicSetup`: `stream_asset` (the descriptor), `stream`, `tracks`, `duration_s`,
`track_names` (editor labels), `default_state`, `states` (`min_play_s`, `max_play_s`,
`intensity_levels`, per track `volume`, `fade_s`, `change_on_cue`, `change_on_cue_mode`,
`change_on_cue_name`; `one_shots` = every child whose type name contains `SoundSlot` and that
has a sound: `class`, `wave`, `stream` when it names a stream, `volume`, `change_on_cue` with
its mode and name; `groups` = the `MusicGroupCtrl` children that name a group, when there are
any), `cue_names` (the cue names of the setup's stream). Measured on PC: Part 2 has 42
one-shots (41 `MusicStaticSlot` and 1 `SoundDef`; 30 at once, 4 at the next cue, 8 at a named
cue), Part 1 30 (19 / 2 / 9); no `MusicGroupCtrl` and no `MusicOneOffSlot` is shipped.

`music_rules` also says (read from code): `playback` — every track of the setup's stream
starts together at the stream start with volume 0, each on its own controller with the
square-root volume curve, in the first child of the music group node (the menu music group
when the setup has `m_tplayinmenu`) (`MusicPlayer.command_allocate` 0x7cf2a8); a state only
sets volumes; a track the state does not list keeps its volume and any change still waiting for
a cue (`track_switch` 0x7cf77c). `cue_source` — the cue event is registered on the controller
of track 0 only (0x7cf2a8); that this controller reports only track 0's markers is inferred.
`one_shots` — a one-shot plays at once (`change_on_cue` 0), at the next cue (1) or at the named
cue; a slot already waiting is not queued again (`play_one_off_sound` 0x7cf896); the truth
argument of `MusicTrigger.command_trig` (Play Static, `_tforceplaystatic`) is never read
(0x7d1113).

`change_on_cue` (`music_rules.change_on_cue`; read from `MusicPlayer.track_switch` 0x7cf77c and
`cue_point_event` 0x7cfb52): 0 = at once (`change_on_cue_mode` `at_once`); 1 = at the next cue
point of any name (`next_cue`); any other value = at the cue whose name hash equals it
(`named_cue`, with the cue of the setup's stream in `change_on_cue_name`, or `unresolved`). The
hash is 0x423ca1: bit-serial CRC, polynomial 0x04C11DB7, bytes not folded, so `Click` and
`click` are different cues. One pending change per track, a later one overwrites; a cue string
may hold several names separated by `/`. Measured: every value other than 0 and 1 in PC Part 2
and PC Part 1 is the hash of a cue name of that set's music descriptors (`click1` 0x7E6EFDDC,
`click` 0x719A1BFD, `Click` 0x629E6D21, `click_01` 0x73AB579C, `click 01` 0x7355579C, `Perc_01`
0x847FB0DF, `melody 01` 0x9B2EB8AD, `LongMelody` 0xB73D4F2F); in the PC Part 2 table 643 tracks
of 24 setups are 168 `at_once`, 2 `next_cue` and 473 `named_cue`, none unresolved. The cue
`Marker 01` is never referenced. Console sets were not checked.

A PC stream record is a 32-bit `ogg_packet` (read from code, 0x45cbae, 0x8d3b20): the last
packet of a track carries the end flag and the track length as its granule position, and the
decoder shortens the last block to it (0x8d29c0). The exported `.ogg` ends at that position, so
`samples` equals `descriptor_samples` (measured on the 3 PC Part 2 and 4 PC Part 1 one-track
streams: Menu48 10,219,520, GameOver 3,198,976, Complete 3,076,096, Part 1 Intro01 1,206,806).
`--flat-music` files end at the computed block position instead (+704, +832, +704, +106
samples). PS3 `samples` equals the PC descriptor count on the three Part 2 streams; Xbox 360 is
512 higher (padding).

## Engine rules (read from code)

`speak_rules`, `effects.attack_start_rule`, `effects.ragdoll_contact` and `music_rules` of the
table carry the first four; the rest is documentation only.

- **Speak blocking** (`SpeakCtrl.ShouldIgnoreThisSpeaker` 0x83ae84): a category-1 request is
  dropped while any playing line has `ignore_player_events` and `ignore_nonplayer_events`, or
  `ignore_nonplayer_events` and the speaker is not a player, or `ignore_player_events` and the
  speaker is a player. The flags are those of the PLAYING line (`blocks_while_playing` on every
  speak: `all` / `nonplayers` / `players` / `none`; Part 2: 47 / 40 / 1 / 247). Category 2 is
  never dropped, category 0 always. `m_ipriority` is copied into the request and never read.
- **Senders of speak ids**: `speak_triggers` now lists 8 (SPEAK animation events and
  `UnderbossPhase1.command_hit_by`), 9 and 36 (SPEAK events of Part 1 only), 37 (none), the
  `EffectSpeak` ids 26, 27, 29, 30, 31 and the Underboss ids 33, 34.
- **Attack start effect**: fired once per animation state by
  `CharacterRootLogic.command_update_combo_timing` 0x68810a when the state is an attack state
  and max(impact − `_ncleardeadzoneoverride`, impact − 0.2 s) ≤ t < impact.
- **Ragdoll contact**: volume = min(1, (|F| / mass_A / 200 + 0.3) ^ 0.25); body part by bone
  mask (head 0x3, body 0x16c47c, arm 0x3b80, foot 0x90000; first match wins); gates: owners
  differ, force above `m_nragdollimpactforcethresholdforsound`, mean speed above 2.0 m/s, 0.5 s
  per sound group on game time. The ragdoll damage arithmetic runs before the 0.5 s gate, so the
  gate limits sound only.
- **Voice limits**: 1024 live prioritised sounds, 96 playing voices, 128 for playing voices plus
  source voices queued for destruction (slot 3 0x44a868 = fill of the ring at system +0x22c;
  pushed by `Voice_XAudio2` slot 5 0x402a3d, drained by the worker loop 0x446e86 / 0x4468b0;
  that the drained call, vtable +0x40, is `DestroyVoice` is inferred); writer 0x4af2d7, use 0x44a8fa. The stolen voice
  is the first in voice-id order with priority ≠ 0 and ≤ the new one (order inferred).
- **Listener**, single-listener path: distance and reverb send from the player character's
  centre + 0.5 m; direction from the camera position and orientation (0x638969, 0x4470d9,
  0x44882d).
- **Listener**, two-listener path (0x44882d, taken when the listener count is above 1; reads two
  0x50-byte records: +0 distance point, +0x10 orientation, +0x20 panning point). System fields
  (setters 0x4b6773–0x4b67e4): `multiListenerDisableOrientationPanning` +0x80,
  `multiListenerDisableDoppler` +0x81, `multiListenerDistanceAttenuationType` +0x84 (ADDITIVE 0,
  SATURATE 1, CLOSEST 2), `multiListenerSeparationPanning` s +0x88,
  `multiListenerGeneralAttenuation` a +0x8c. Per listener i: g_i = distance gain, r_i = reverb
  gain of |source − record+0|. SATURATE: if g0 + g1 > 1, all four are divided by g0 + g1.
  CLOSEST: if max(g0, g1) > 0, all four are multiplied by max(g0, g1) / (g0 + g1). Weight c_i =
  g_i · volume / (1 + a), volume = voice[+0x88] · [+0x80] · [+0x18]. Panning enabled: the six
  gains (L, R, C, LFE, RL, RR; order inferred) of (source − record+0x20) rotated by the conjugate
  of record+0x10 (0x4460f9); with s = 0 each output += gain · c_i; with s ≠ 0, listener 0 adds
  c·(L + s·(C + R)) to left, c·R·(1 − s) to right, c·(RL + s·RR) to rear left, c·RR·(1 − s) to
  rear right, listener 1 the mirror, and both add c·C·(1 − s) to centre and c·LFE. Panning
  disabled: left += (1 ± s)·c_i·0.5, right += (1 ∓ s)·c_i·0.5 (+ for listener 0 on the left),
  rear the same with 0.4. Reverb send = (r0 + r1) · volume · voice[+0x38] / (1 + a). Doppler =
  sqrt(d0 · d1) (0x44785f), 1 when disabled. (Read from code.)
- **Obstruction** (per voice per frame, 0x44d949; only with exactly one listener): a worker job
  sorts the obstructor boxes into 20 angular sectors (18° each) around the listener in the
  horizontal plane, range 512.0. For a voice at horizontal distance d (d < 1e-5 → 0), each box
  of its sector is tested against the segment listener → source (0x40e4a3); on a hit, c = the
  smallest distance between the sight line and any of 6 box edge lines, and the sum +=
  min(c, 2.0) × 0.5; the sum is clamped to 1 and multiplied by `obstructionFactor`. Which six
  edge lines: not checked.
- **Zones**: weight of a zone at a point = min(1, depth / fadeDepth), depth = distance to the
  nearest of the six faces, 0 outside (1 when fadeDepth ≤ 0 and inside); a zone with weight f
  passes scale × f to its children and keeps (1 − Σ children f) × f × scale; a child is entered
  only inside its x / z half-extents (0x44cf1b, 0x44ff51). `_nfadedepth` is a distance, not a
  time (read by the researcher, not rechecked).
  Blend (0x44ee15): weights are summed per effect type and the type with the largest sum W is
  instantiated (W < 1e-5 → 1). Per parameter over the entries of that type: float = Σ(w·p)/W;
  integer = trunc(Σ(w·p)/W); truth = (number of true entries)/W > 0.5; choice = the value of
  entry 0, replaced by a later entry of that type only when its weight is strictly larger than
  the best so far (entry 0 is not type-tested). 0x44fd75 clamps a weight at 0 and appends the
  entry. (Read from code.)
- **Pitch**: frequency ratio = controller pitch × slot pitch × Doppler × rate ratio, clamped to
  [1/1024, 4.0] (0x40228c). No time-scale term; Doppler only for voices with a Doppler factor
  and it uses game-time velocities; start delays run on the game-scaled event clock. So slow
  motion does not change pitch (a code prediction; no play-session evidence exists).
- **Equalizer** (0x4038d3; sample rate 44100; seven inputs p0..p6; each gain is clamped to
  ≤ 0 dB, so the effect can only cut; a section is active when its gain ≠ 0; V = 10^(g/20)):

  | Section | Inputs | Coefficients |
  |---|---|---|
  | 1, first-order shelf (x − allpass) | f = p0, g = p1 | K = tan(π f / fs); H/2 = (V − 1)/2; a = (V·K − 1)/(V·K + 1) |
  | 2, second-order peak | centre = p2, bandwidth = p3, g = p4 | K = tan(π·p3 / fs); H/2 = (V − 1)/2; a = (K − V)/(K + V); d = −cos(2π·p2 / fs)·(1 − a) |
  | 3, first-order shelf (x + allpass) | f = p5, g = p6 | K = tan(π f / fs); H/2 = (V − 1)/2; a = (K − V)/(K + V) |

  That section 1 is the high shelf and section 3 the low shelf is inferred. The definition node
  of this build offers only `ps3_i3dl2_reverb` and `xaudio2_i3dl2_reverb` (0x4d6c5e); `equalizer`
  and `compressor` have no parameter names: the type registry holds only `xaudio2_i3dl2_reverb`
  (12 parameters) and `ps3_i3dl2_reverb` (constructor 0x44a12c, called only from 0x404442 and
  0x450c53), and the two strings are used only as compare operands at 0x4040db / 0x40411f, on
  effects whose reverb flag (+0x11) is clear (read from code). That no shipped definition can
  select them is inferred.
- **Distance attenuation** (0x447274; evaluated per voice in 0x44882d): a piecewise-linear
  curve. With m = minRange, M = maxRange, r = rollOffScale and G = 1/(r·(M/m − 1) + 1): points
  (0, 1), (m, 1), then for i = 1..3 (m·((1/gᵢ − 1)/r + 1), gᵢ) with gᵢ = G^(i/4), then (M, 0).
  That is 1/(1 + r·(d/m − 1)) sampled three times and forced to 0 at maxRange. With
  `linearDistAtt`: (0, 1), (clamp(m, 0.001, 0.999), 1), (M, 0). The shipped SoundCtrl stores
  `linearDistAtt` false and `rollOffScale` 1.0 (measured, PC Part 2 and Part 1). That the two
  math calls of the curve are log and exp is inferred.
- **Reverb send**: the same curve on reverbMinRange / reverbMaxRange, times reverbMixFactor
  (0x447274, 0x44882d).
- **Volume taper** (0x445b43): g(v) = 0.85·v² + 0.15·v, v clamped to 0..1, on the slot volume
  and on group volumes. A SoundController uses curve 1 (this taper) by default (0x449b8d); music
  controllers are set to 2, square root (0x7cf2a8); 0 = linear, 3 = 1 − f(v·π/2) (0x4463bf; that
  f is the cosine is inferred).
- **Option volumes**: master, effects, voice and music options are linear factors k/10 on the
  group volume, default 1.0 (0x7b84da, 0x82be66, 0x82fd6a). `masterAttenuationPC` and
  `movieAttenuation` are dB: gain = 10^(clamp(dB, −96, 12)/20) (0x445f4d); stored −2.0 and −3.0.
- **Doppler** (0x44785f): ratio = (v_listener·u + c/f) / max(v_source·u + c/f, 1e-6), floored at
  0, c = 346.6 m/s, f = dopplerFactor, u = unit vector listener → source; 1 when f ≤ 0.

## Related files

`wave_durations` (console tables only; absent on a clean PC table): `codecs`, `sources`
(how many lengths came from the `header`, a `frame_count`, a `decoded` file), `without_duration`
(names), `reparsed_fragments`, `note`. A wave's length comes from the sound header in
`extracted/`, else from `audio/sound_info.json`, else from a decoded `.wav`.

`audio/sound_info.json` (per sound: rate, length, loop flag; on console also
`duration_source` = `header` / `frame_count` / `none`, and a `not_decoded` list) and `audio/<stream>.json` (per music
stream: tracks, cue points) are written by `extract`.
