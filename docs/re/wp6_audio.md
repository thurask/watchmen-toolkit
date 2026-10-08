# WP6 - Audio: from game event to speaker

Target: `KapowMultiDEDRM.exe` (Watchmen: The End Is Nigh Part 2, PC). Companion table:
`findings/wp6_sound_tables.json` (3.5 MB). Scratch: `work/wp6/` (parsers `lib.py`, `build_json.py`,
`final_json.py`; raw header scan `rawhdr.tsv`; decoded lengths `durations.tsv`).

Evidence marks: **[R]** read from code or bytes (address given), **[D]** read from game data (fragment or
sound header; path given), **[I]** inferred (reason given), **[N]** not established. Fragment paths are
relative to `E:\Claude\HeyClaude_WatchmenPart2\20260708\extracted\`; they were parsed with
`tk150/wlib/kapow_fragment.py` (all 28 sound-relevant fragments plus the 302 `SoundEvents` files parse
to EOF). Script-object member offsets follow the registration order in `reg_dump.json`, 4 bytes each.

## 0. Summary

1. **Path.** Animation event / AI decision / trigger -> `SoundDef` (script class on the native
   `SoundSlot`) -> variation choice in `SoundDef.command_sounddef_play_all` 0x831365 -> native
   `SoundSlot::play` 0x4d2758 (random pitch and volume) -> `SoundSystem` 0x44a8fa (distance cull,
   priority steal, voice object) -> `Voice_XAudio2` 0x40271b (one XAudio2 source voice per sound,
   MS-ADPCM or PCM16 decoded by XAudio2 itself, a custom low-pass XAPO on 3D voices) -> per frame
   0x40228c: 6-channel output matrix, reverb send level and frequency ratio computed by the engine's own
   3D code 0x44882d (X3DAudio is only initialised) -> effect-node submix (equalizer + compressor XAPOs)
   and reverb submix (XAudio2 `AudioReverb`, I3DL2 presets per zone) -> mastering voice (6 channels,
   master down-mix XAPO + volume meter).
2. **Speech** is a separate queue, `SpeakCtrl` (0x83d414). A speak event is (speak id, character type,
   character). Each character type has a group of `SpeakDefinition`s; each definition has one
   `SoundDef` per voice; a character draws its voice index once at random. Three categories follow from
   three flags: 0 never plays, 1 exclusive lines (taunts) - the only ones that send `START_SPEAK` to
   the face - and 2 grunts.
3. **Dominatrix.** 26 of her 35 speak definitions play, on 3 voices (300 wave files). Taunt lines last
   1.2 - 7.1 s (mean 3.8 s), attack shouts 0.2 - 1.6 s, hit grunts 0.3 - 3.3 s, death 0.45 - 1.15 s.
   Her animation states carry 166 `SOUND` events on 16 sound definitions (65 states use `swish_08`), 30
   `SPEAK` events and 1179 foot events; 4 `SOUND` events have the speak flag and all 4 are Twilight Lady
   lines (the two share the animation class).
4. **Extractor.** Three defects were found in today's audio export: (a) 10 of the 13 PC music `.ogg`
   files are multi-track streams whose tracks were appended chunk by chunk into one stream (length =
   tracks x real length); (b) all 35 stereo sounds are written at 44100 Hz although their header says
   about 48000 Hz; (c) PCM sounds are read 4 bytes late. Loop flags (55 sounds), cue points (music
   only), track names and the 14 localised `_uk` text assets are not exported.

## 1. Data model

### 1.1 Classes and where they live

| Class (native base) | Role | Instances / fragment [D] | Registration |
|---|---|---|---|
| `SoundDef` (`SoundSlot`) | one playable sound; children of the same class are its variations | 1013 in `TNT/Production/Fragments/GameEssentials/SoundDb/SoundDb.fragment`; character voices in `TNT/Production/Fragments/Enemy/All*Types.fragment`, `Rorchach.fragment`, `NightOwl.fragment`; level sounds in `Levels/Game_Levels_Part2/<level>/Sound.fragment` | 0x8378d1 |
| `SoundGrp` (`SoundGroup`) | mix group tree: volume, pause, `isMusic`, `m_tstopgroupinmenu`, `m_esoundeffectprocessor` | 27, `SoundDb.fragment` folder `SoundGroups` | 0x839809 |
| `SoundCtrl` (`SoundSystemNode`) | global controller: master / effects / music / voice volumes, damping, 20 pooled `SoundController`s, music state | `GameEssentials/Sound.fragment` | 0x835a62 |
| `SoundEffectNode`, `SoundEffectDefinitionNode` | effect submix ("EnvironmentEffect") and 18 reverb definitions (`xaudio2I3dl2Reverb_*`, `ps3I3dl2Reverb_*`, presets) | `Sound.fragment`; `SoundDb.fragment` folder `EffectDefinitions` | native 0x4d5175, 0x4d6c5e |
| `SoundEnvironment` (`CollisionBoxNode`) | reverb / occlusion zone box: `_eeffectdefinition`, `_nfadedepth`, `_nocclusionfactor`, `_tobstructor` | 27 Bordello, 22 NightClub, 19 StreetsOfRiot, 5 PvP, 2 Tutorial (`<level>/Sound.fragment`) | 0x832a2b |
| `LoudSpeaker` (`PivotNode`) | placed emitter (ambience): `_tplayonstart`, `_esoundslot` | 187 in the level `Sound.fragment`s | 0x788f30 |
| `TriggerActionSound` | level scripting: 14 actions (`TRIGGER_ACTION_CATEGORY_SOUND`: SOUND_PLAY ... ADJUST_SOUND) | 336 in level fragments | 0x86aa43 |
| `SpeakCtrl` | speech queue | `SoundDb/SpeakDB.fragment` (+ `SpeakCtrl.fragment`: 4 empty group nodes) | 0x8420d4 |
| `SpeakDefinition` / `SpeakVoiceDefinition` | one line type / one voice of it (`m_espeaktyperef0..2`) | 335 / 201+ in the five character fragments, under a `CharacterSpeakDefinitionUpdate` folder | 0x8446be / 0x8452f4 |
| `SpeakBuilder` | runtime node (speaker type, speak id, definition) built per registered definition | created by `SpeakCtrl.searchCharacterSpeakDef` 0x83b223 | 0x83a2aa |
| `CharacterSoundDef` | per character type: `m_espeakref` (its speak group) and the three attack-start effects | `Enemy/<type>.fragment` | 0x6d19f6 |
| `EffectSound` / `EffectSpeak` | children of an `EffectBase`: a `SoundDef` with a placement / a speak id | 72 / 57 in `GameEssentials/EffectDb.fragment` | 0x72efa3 / 0x72fe97 |
| `SoundPackageCtrl` / `SoundEffectType` | collision-sound matrix: effect type x surface -> `SoundDef` or advanced effect | 96 / 2752 in `GameEssentials/CollisionEffectDB/CollisionSoundDB.fragment` | 0x839ac0 / 0x839471 |
| `MusicSetup`, `MusicStreamSlot`, `MusicIntensityContainer` / `Definition`, `MusicTrigger`, `MusicTrackCtrl`, `MusicStaticSlot`, `MusicPlayer` (`SoundStreamPlayer`) | music (section 5.8) | `<level>/Sound/MusicSetup_level_*.fragment`, NightClub `Sound.fragment`, `SoundDb.fragment` (game over, mission complete) | 0x7d4714 ... |
| `SubtitleSlot`, `SubtitleSlotRegister`, `SubtitleHUD` | subtitles keyed by sound slot | `GameEssentials/MovieDbPart2.fragment` | 0x8488b8, 0x84f6f7 |
| `AmbienceGroup`, `MasterMusicCtrl`, `MusicGroupCtrl`, `MusicOneOffSlot`, `SoundAudioSettingsRef` (1, MainMenu), `FXLightningPlaySound`, `sound_test_play` | registered; no (or one) instance in the Part 2 fragments [D] | - | - |

Nine `SoundEvents` / `ForceTrigger` fragments are header-only (17 bytes): they are empty event lists,
nothing is lost there [D].

### 1.2 `SoundDef` / `SoundSlot` properties

Native `SoundSlot` (registration 0x4da99c, object offsets from the parameter copy 0x4d094c [R]):

| Property | Offset | Meaning (code) |
|---|---|---|
| `sound` / `streamingSound` | asset refs +0x58 / +0x60 | wave asset (`*.wav`, class `sound`) or stream descriptor (`*_track0.wav`, class `mediastream`) |
| `volume` 0..1 | +0x68 | multiplied by the play call's volume; then the volume law (5.4) |
| `pitch` 0..5 | +0x6c | frequency ratio factor |
| `minRange`, `maxRange` | +0x70, +0x74 | distance curve of the direct path (5.3) |
| `reverbMinRange`, `reverbMaxRange`, `reverbMixFactor` | +0x78, +0x7c, +0x80 | distance curve and gain of the reverb send |
| `priority` | +0x84 | voice priority; 0 = not counted and never stolen (3.4) |
| `dopplerFactor` 0..1 | +0x88 | 0 = no Doppler; forced to 0 on non-3D voices (0x44a48d) |
| `enableObstructionAndOcclusion` | +0x8c | enables the per-frame occlusion / obstruction queries (0x447546) |
| `lfeChannelLevel`, `useCenterChannelOnly` | +0x90, +0x94 | LFE gain; 2D mono to centre instead of L+R x 0.707 (0x44623c) |
| `randomPitchLength`, `randomVolumeLength` (0..100) | +0x98, +0x9c | jitter in percent (3.2) |
| `assetIsLooping`, `numStreamTracks`, `get_cue_points` | read-only | come from the asset (5.1, 5.8) |

Script `SoundDef` members (reg 0x8378d1; block offsets): `m_esoundgroup` +0x00 (its `SoundGrp`),
`m_tmissionspeak` +0x04, `m_nquarantinetimemin/max` +0x08/+0x0c (not present in any shipped fragment,
so 0 [D]), `m_nquarantinetimeleft` +0x10, `_nmindelay` / `_nmaxdelay` +0x14/+0x18 (start delay),
`_tstreaming` +0x1c, `_echildlist` +0x20, `_esoundcontroller` +0x24, `_isoundid` +0x28,
`_iselectionmethod` +0x2c, `_ilastindex` +0x30 [R: `SoundDef.GetDelay` 0x828e0a reads +0x14/+0x18,
`ChooseChild` 0x82b53d reads +0x20/+0x2c/+0x30].

There is no "bank" or "package" property: a sound is loaded with the block that holds its asset
(1.4) [D].

### 1.3 From a name to a definition to a wave

There is no event-name hash table for sounds. References are entity references stored in the
fragments [D]: an animation event's `_etarget00`, an `EffectSound._esounddef`, a
`SoundEffectType.m_eeffectsoundreference`, a `SpeakVoiceDefinition.m_espeaktyperef0`, a
`LoudSpeaker._esoundslot`, a `TriggerActionSound.m_etarget1`. A cross-fragment reference is a pair
`[instance id of the included fragment, node id]`, for example `["68447a02", "3549a074"]` = SoundDb
instance, node `swish_08`. **Node ids are not unique across fragments** (the three speak-definition
folders of `Rorchach.fragment`, `NightOwl.fragment` and `AllThugTypes.fragment` all have id `21172c62`),
so the first element must be used to pick the fragment [D; `work/wp6/lib.py res()`].

The wave is the `sound` string of the `SoundDef` (`/sounds/...wav`); the asset of that name is found
by the block directory (name hash of the path, `KAPOW_NAZ_FORMAT.md` 2.2). Speech is the only
enum-indexed lookup: `SPEAK_ID` (50 names) x `CHARACTER_TYPES` -> `SpeakBuilder` -> `SpeakDefinition`
-> voice -> `SoundDef` (2.3).

### 1.4 Loading

`sound` assets are block assets with the samples inline in the header blob (no stream part); they are
resident while their block is loaded. Bordello's block lists 843 `sound` assets
(`KAPOW_NAZ_FORMAT.md` line 254) [D]. `SoundPackageCtrl` is **not** a bank loader: it is one row of
the collision-sound matrix (its `initialize_local` 0x83304e builds a lookup list of its
`SoundEffectType` children) [R]. Music is streamed from loose `derived_pc/sounds/music/**.mediastream_s`
files (13) [D]. Which block holds which character's voice files was not tabulated [N].

### 1.5 Mix groups and global values [D]

```
MasterSoundGroup 1.0                       MenuMasterSoundGroup 1.0 (not stopped in menu)
  EffectsGroup 1.0                           EffectsGroup -> MenuEffectsGroup
    Effect_no_reverb_08 0.8                  VoiceGroup   -> MenuVoiceGroup
    Effect_no_reverb_1  1.0                  MusicGroup   -> MenuMusicGroup
  VoiceGroup 1.0
    VoiceOverRorschach 1.0
  MusicGroup 1.0 (isMusic)
    InGameMusic 1.0
  ProcessorGroup 1.0   m_esoundeffectprocessor = SoundEffectNode "EnvironmentEffect"
    ProcessorVoiceGroup 1.0: VoiceEnemies 1.0, VoiceRorschach 0.9, VoiceNiteOwl 0.96, MissionSpeaks 1.0
    ProcessorEffectsGroup 1.0: rain_default 0.63, rain_on_materials 0.63, Effect 0.95,
                               EnemiesCombatSounds 1.0, PlayerCombatSounds 1.0
```

`SoundCtrl` (`GameEssentials/Sound.fragment`): `linearDistAtt` false, `rollOffScale` 1.0,
`obstructionFactor` 0.5, `masterAttenuationPC` -2 dB, `lfeDownMixLevelPC` 0, `movieAttenuation` -3 dB,
`multiListenerDistanceAttenuationType` 2 (CLOSEST), separation panning 0, general attenuation 0,
`_ndampfactor` 0.65, `_ndamptime` 0.1 s, `_nundamptime` 0.2 s, 20 pooled `SoundController`s. All
Dominatrix voice definitions are in `VoiceEnemies`; her combat sounds in `PlayerCombatSounds` or
`Effect`.

## 2. What starts a sound for a character

### 2.1 Animation events (`CharacterRootLogic.command_animation_event_received` 0x6a525e)

| Event | Case | What plays [R] |
|---|---|---|
| `SOUND` (9) | 0x6aba76 | `_etarget00` = a `SoundDef`. `m_ttruth1` set ("speak flag"): `SoundCtrl.command_stop_entity(root)` (stops every voice attached to the character), `SoundDef.command_sounddef_play_speak(root)` via `AnimationEvent.command_play_event_speak` 0x5c1725, then `CharacterVisual.command_start_speak` (face `START_SPEAK`). Otherwise `command_get_sound_position` (= `m_ivalue00`): 0 -> `SoundDef.command_sounddef_PlayPos(world position of the character)` 0x5c1689; 1 -> `command_sounddef_PlayPivot(capsule, root+0x28)` 0x5c16bf (follows the character) |
| `SPEAK` (37) | 0x6a9f30 | `m_ttruth1`: `SpeakCtrl.command_stop_speak_and_quarantine(root)` first. Then `SpeakCtrl.command_add_speak_event_based_on_enum(m_ivalue00 = speak id, character type, root)` |
| `LEFT/RIGHT_FOOT_DOWN` (6, 40), `FOOT_DOWN_JUMP` (76), `FOOT_DOWN_STOP` (77) | 0x6a533a | footstep, 2.2 |
| `IMPACT_EFFECTS` (56) and `give_damage` | 0x6aae6f; `CharacterEffectDef.command_play_damage_effect` 0x6673d0 | damage effect of the **victim's** effect definition: its `EffectSound` and `EffectSpeak` children, 2.4 |

Sound events come from two places [D]: `AnimationEventWM` nodes inside the state, and the
`SoundEvents/SE_<clip>.fragment` list that the state includes (a `FragmentNode` under the state's
`Events` folder; all 302 `SE_*` files are referenced by at least one state). The exporter's
`anim_meta` already lists both with times but drops `_etarget00`, `m_ivalue00` and `m_ttruth1`;
`wp6_sound_tables.json` `state_sound_events` adds them for all five body classes.

### 2.2 Footsteps (0x6a533a; decompile of 0x6a525e lines 1545-1775) [R]

1. Ground probe result -> surface id: `EffectsLib.GetEffectPackageBasedOnModel(hit)`; if -1,
   `GetEffectPackageBasedOnTexture(hit)`; if still -1, 6 `DEFAULT`. A second branch (probe list
   `logic+0x130`, used when the float at `+0x12c` is non-zero) defaults to 71
   `MATERIAL_DEEP_WATER_10CM` (what sets that float: [N]).
2. Effect type by character type (`root._icharactertype`) and event:

   | Character type | step (6 / 40) | jump (76) | stop (77) |
   |---|---|---|---|
   | 0 Rorschach | 53 `CHARACTER_FOOT_ROR` | 65 | 62 |
   | 1 Nite Owl | 54 `CHARACTER_FOOT_NO` | 66 | 63 |
   | 28 go-go dancer, 33 Dominatrix, 35 Twilight Lady | 91 `CHARACTER_FOOT_FEMALE` | 92 | 93 |
   | all others | 33 `CHARACTER_FOOT` | 64 | 61 |

3. `CollisionEffectCtrl.command_get_sound_in_package_based_on_enum(effect type, surface)` 0x6e0f13:
   row = fast lookup by effect type, then the surface id is searched in the row's list; no entry ->
   no sound.
4. The entry's `m_eadvancedeffectreference` (water) fires an effect; otherwise
   `SoundEffectType.command_apply_effect(hit info, root)` 0x8328b4 -> `ApplySubEffect` 0x82b7a7 plays
   the `SoundDef` (pivot = the entity passed, else at the hit position; which of the two the footstep
   call takes is [I] "pivot = character root", from the argument order).

Dominatrix rows [D: `CollisionSoundDB.fragment`, table `footsteps` in the JSON]:

| Effect type | Surfaces | SoundDef | Waves, duration | Rule |
|---|---|---|---|---|
| 91 step | DEFAULT, concrete dry / wet, generic concrete | `1362d891` | 16 x `Female_Concrete_*`, 0.067 - 0.229 s | one of 16, no immediate repeat |
| | wood board / fence / plate / heavy, generic wood | `065958c6` | 8 x `Female_wood_*`, 0.119 - 0.261 s | one of 8 |
| | all metal materials, trashcans, dumpster, AC unit, jail door, metal stair | `ca5d8b1f` | 8 x `Female_metal_*`, 0.226 - 0.363 s | one of 8 |
| | paper dry | `20baac63` | 4 x `paper_*`, 0.55 - 0.84 s | one of 4 |
| | deep water | advanced effect `WaterWalk10CM` | - | - |
| | every other surface (carpet, sofa, dirt, glass, grass ...) | no entry -> silent | - | - |
| 92 jump | default for all surfaces | `5fa5355c` | `Jump_Concrete.wav` 0.221 s | single |
| | wood | `327d9c9a` "Jump_wood" | 3 x `Medium_stepswood_L_*`, 0.30 - 0.39 s | all three at once (method 4) |
| | metal | `57a9606f` | 2 x `Jump_on_metal_*`, 0.30 s | round robin |
| 93 stop | default for all surfaces | `6913089d` | 3 x `Concrete_dry_stop_*`, 0.11 - 0.19 s | one of 3 |
| | carpet | `5168270e` | `footstep_carpet_stop.wav` 0.98 s | single |

### 2.3 Speech

**Queueing** - `SpeakCtrl.command_add_speak_event_based_on_enum` 0x84171e [R]:
refused while `_ipaused` > 0 (+0x70; `TriggerActionSound.PauseSpeakSystem` 0x853d2b). Then
`command_is_speak_event_ready` 0x83c8ee: (1) `isEventInSpeakGroup(id, character type)` 0x83aa92 finds
the `SpeakBuilder` (ids that the character's group does not define end here); (2) `isEventIgnored`
0x8419b3; (3) the same (id, speaker) must not already be requested (0x83ab80), in quarantine (0x83abee),
or playing (0x83ad39; plus the two `...OnNonePlayers` variants). If ready:
`assignSpeakVoiceToSpeaker` 0x83afd6 - if `CharacterRoot.command_get_speak_voice` is -1 the character
gets `rand_integer(number of voices)` for the rest of its life - and an event record is appended to
`_requestedspeakeventstructlist` (+0x58) with a quarantine time drawn uniformly in
`[m_nquarantinetimemin, m_nquarantinetimemax]`.

**Category** - `SpeakLib.DetermineSoundCategoryStruct` 0x83baa1 (disassembly) [R], from
M = `m_tallowmultipleevents`, P = `m_tignoreplayerspeakevents`, N = `m_tignorenoneplayerspeakevents`:

| Flags | Category | Behaviour (`ShouldIgnoreThisSpeaker` 0x83ae84, `Active` 0x83d414) |
|---|---|---|
| M and not P and not N | 2 | never ignored: grunts overlap freely. No `START_SPEAK` |
| not M and (P or N) | 1 | ignored (dropped) while a conflicting line is playing - the test walks the playing list and compares the playing line's P / N flags with whether its speaker is a player (the exact truth table is [N]: the decompile of the loop is flattened). `START_SPEAK` is sent when it starts |
| anything else | 0 | always ignored. All 99 such definitions in the data have no voices (the unused `SPECIAL_GROUP_n`) [D] |

**Per frame** - `SpeakCtrl.Active` 0x83d414 [R]:

1. For each requested event: ignored -> removed. `rand_number > m_nrandom` -> moved to quarantine with
   time 0 (`m_nrandom` is the play probability; 1.0 on all Dominatrix lines). If its speaker already has
   a line in the playing list the event waits. Voice = the character's voice index; the speak group
   type is always 0 (`determineSpeakGroupType` 0x83b08d returns 0), so only `m_espeaktyperef0` is used
   and `m_espeaktyperef1/2` ("SHOUT") never are.
2. Start condition: not started, `m_ndelay` < waited time, speaker free ->
   `SoundDef.command_sounddef_play_speak(speaker)` (0x83d8c2); the returned voice id is stored; if
   category = 1, `CharacterVisual.command_start_speak` to `root.m_echaractervisual` (0x83d936 -
   0x83d94d); the event moves to the playing list. The waited time starts at 0 and advances at the end of each pass, so a
   line starts one frame (two if it was queued after that frame's pass) after the request [R]. Not started within `m_ndelay` + 2.0 s
   (`_nspeakeventtimeout`) -> dropped.
3. For each playing event: when `SoundSystemNode.IsPlaying(voice id)` is false,
   `CharacterVisual.command_stop_speak` (0x83dbe4; every category) and the event moves to quarantine.
4. Quarantine entries leave when their time has elapsed; until then the same (id, speaker) cannot be
   queued again. Dominatrix: taunt lines 20 - 40 s, hit grunts 2 - 8 s, shouts, stun, death 0 [D].

So **one exclusive line at a time per conflict class, one line of any kind per speaker, and grunts
from different speakers in parallel** - not a single global speaker. Priorities (`m_ipriority`,
`SPEAK_PRIORITY` A..E) are copied into the record but no comparison on them was found in `Active` [R
for the copy, N for any use elsewhere].

**Interruptions** [R]: `command_stop_speak_and_quarantine(character)` 0x83ca38 stops the voice and
quarantines the line. Callers: `CharacterRoot.command_give_damage` 0x691b10 (the victim),
`CharacterRootLogic.FireAttackBasedOnAttackID` 0x68d870 (applied to the **target**, `root+0x70`, when an
attack is fired at it), `command_you_killed_me` 0x69004c, the `SPEAK` event with `m_ttruth1`.

**Who asks for which id** (constants read at the call sites; `work/wp6/speaksites.py`). A = the target
is Rorschach (type 0), B = Nite Owl (type 1) [R: `AttackEnemy.command_may_attack` 0x600246].

| Speak id | Sender (site) | When |
|---|---|---|
| 20 / 21 `TAUNT_TARGET_A/B_SPOTTED` | `Enemy.StateActive` 0x725392 / 0x7254a1; `ReturnToCombatZone.StopAndTaunt` 0x7ff775 / 0x7ff820 | target spotted; taunt at the combat-zone border |
| 18 / 19 `TARGET_A/B_SPOTTED_COMMUNICATE_TO_GROUP` | `Enemy.StateActive` 0x725235 | target spotted, said to the group |
| 22 / 23 `TAUNT_GET_UP_TO_TARGET_A/B` | `Enemy.command_got_up` 0x722f8b; `Partner.command_got_up` 0x7d9a66 | after getting up (event `GOT_UP` 39) |
| 24 / 25 `MELEE_ON_TARGET_A/B` | `AttackEnemy.command_may_attack` 0x600658 | the orchestrator grants her an attack |
| 17 `HELP_COMMUNICATE_TO_GROUP` | `hangback.StateActive` 0x75e9af; `Partner.StateActive` 0x7db33e | hanging back |
| 33 / 34 `MELEE_START_LIGHT/HEAVY` | `EffectSpeak` of `Attack_start_light/heavy/weapon` (2.4); three `SPEAK` events | attack start |
| 26 - 31 `DAMAGED_*` | `EffectSpeak` of the damage effects (2.4) | hit |
| 35 `DAMAGED_LIGHT_STUN` | `SPEAK` events of the 11 stun states | stun state entry |
| 32 `DEATH` | `CharacterRoot.StateDead` 0x6bb1c1 | death, unless `m_tnodeathscream` |
| 2 `TAUNT_TARGET_KILLED` | `CharacterRoot.command_you_killed_me` 0x690077 | sent to the killer |
| 40, 43, 44 `SPECIAL_GROUP_3 / 6 / 7` | `SPEAK` events: jump and get-up states (40), thrown (43), one more (44) | animation |
| 8 / 9 `TAUNT_COUNTER_ATTACK_A/B` | only `UnderbossPhase1.command_hit_by` 0x888e62 sends 8 | no sender for the Dominatrix was found: [N] |
| 1 `TAUNT`, 3 `TARGET_SPOTTED`, 5 `ENGAGEMENT`, 6 `MELEE`, 10 / 11 / 15 | `AttackEnemy.command_taunt` 0x6006d8, `AttackEnemy.StateActive` 0x5ffab0, `Enemy.SetState` 0x715404, `Enemy.StateActive` 0x725535, partner classes | **not defined for the Dominatrix, Gimp, Knot-Top or Twilight Lady groups** (their definitions start at id 8); these requests end at step (1). Only the Rorschach and Heavies groups define ids 0 - 7 [D] |

`36 DAMAGED_GRENADE` and `37 DAMAGED_ELECTRIFY` have definitions and waves but no sender was located
(the flash-grenade / electrify cases of the event handler were not searched) [N].

### 2.4 Combat: attack start and hits

**Attack start** [R]: `CharacterRootLogic.PlayAttackStartEffects` 0x677b58 ->
`CharacterSoundDef.command_play_attack_start_pos(root, index)` 0x679525: if the character holds a
weapon (`root+0xd4`) the weapon effect, else list[index] (list built in `initialize_local` 0x6764ff:
0 = heavy, 1 = light) -> `EffectCtrl.command_fire_effect` at the character's centre. The caller of
`PlayAttackStartEffects` (it is invoked through the class method table) was not located [N].
Dominatrix [D: `EffectDb.fragment` folder `EnemyCombatEffects`]:

| Effect | Sound | Speak |
|---|---|---|
| `Attack_start_light` `8dafe4d5` | none | 33 `MELEE_START_LIGHT` |
| `Attack_start_heavy` `126cca69` | none | 34 `MELEE_START_HEAVY` |
| `Attack_start_weapon` `0684b3ea` | `Heavy_Attack_start` (3 waves 0.17 - 0.28 s, at world position) | 34 |

The whoosh itself is an animation `SOUND` event (`swish_08` etc., table 2.6), not this effect.

**Hits** - `CharacterEffectDef.command_play_damage_effect` 0x6673d0 (rule read in
`dominatrix_audit.md` section i: rage hit -> uber list; killing hit -> kill list; weapon hit -> list by
the weapon's effect type (wood, steel; sharp adds its own effect); else light poses 1, 2, 5, 6, 23, 24
-> fast list, other poses -> heavy list; upper-body pose -> head list, else body list; knockdown poses
17, 18, 27, 28 add `Knockdown`; stun poses 19 - 22 add `Stun`). Each effect fires its children:
`EffectSound.Fire` 0x714d1f (placement 1 `POS_AND_ORIENT` -> `PlayPos`, 0 `ENTITY` -> `PlayPivot`) and
`EffectSpeak.Fire` 0x714d94 (`add_speak_event(_ispeakid, character type, character)`) [R].
For every enemy type (all use `EnemyCombatEffects`) [D]:

| Effect | SoundDef (all placed at world position) | Layers, duration | Speak |
|---|---|---|---|
| `EN_dam_body_light` | `Damage_light_middle` | 5 waves, 0.24 - 0.53 s | 30 `DAMAGED_LIGHT_MIDDLE` |
| `EN_dam_body_heavy`, `EN_dam_body_kill`, `Block`, `Stun` | `Damage_Heavy_middle` | 10 waves, 0.43 - 0.93 s | 27 `DAMAGED_HEAVY_MIDDLE` (`Stun`: none) |
| `EN_dam_head_light` | `Damage_light_upper` | 11 waves, 0.84 - 1.28 s | 29 `DAMAGED_LIGHT_FACE` |
| `EN_dam_head_heavy`, `EN_dam_head_kill` | `Damage_heavy_upper` | 17 waves, 0.84 - 1.28 s | 26 `DAMAGED_HEAVY_FACE` |
| `EN_dam_body_uber`, `EN_dam_head_uber` | `Damage_Uber` | 24 waves, 2.9 - 3.1 s | 27 / 26 |
| `EN_dam_*_weapon_wood`, `..._steel` | `Damage_weapon_wood` / `_steel` | 23 waves, 0.84 - 1.28 s | 27 (body) / 26 (head) |
| `EN_dam_weapon_sharp` | `Damage_sharp_weapon` | 5 waves | 26 |
| `Knockdown` | `Damage_knockdown_middle` | 18 waves, 0.43 - 0.93 s | 31 `DAMAGED_LIGHT_KNOCKDOWN` |

These definitions are method 4 ("play all"): every child layer (impact, cloth, bone ...) starts at once
and each layer picks one of its own variations. The damage type therefore selects the **definition**;
inside it the variation is random. Because the hit sounds are placed at a world position they are not
attached to the character and do not count as "the character is playing a sound" (2.5).

`CharacterRootLogic.SetCloseCombatDamageToTarget` 0x6ae57f plays one extra sound only for target type
25 (`UNDERBOSS`) hit from behind (collision sound 24 / 24, metal) [R]; not relevant to Part 2 enemies.

**Ragdoll contacts** - `CharacterVisual.ModelCollisionContactAdded` 0x69d00a [R, skimmed]: surface from
model or texture as for footsteps, `get_sound_in_package_based_on_enum`, volume from
`WorldLib.GetVolumeBasedOnContactForce`, then `apply_effect`. The effect-type constants per body part
(`RAGDOLL_HEAD/BODY/ARM/FOOT`, 2 - 5, which all default to row `GENERIC_RAGDOLL`) were not read out [N].

**Other sources** [R, callers of the play commands]: `LoudSpeaker.PlaySound` 0x779ded (ambience
emitters), `TriggerActionSound.TriggerSoundPlay` 0x853e88 (level script; on an entity with
`m_eCharacterVisual` it also sends `START_SPEAK`; `m_ttruth2` stops the entity's sounds first,
`m_ttruth3` pauses the speak system), `DynamicObjectsEffectCtrl.StateActive` 0x7185e3 (props),
`ComboBuildupHud` 0x6ed9d5 / 0x6ee53a and `PlayerHUD.HandleSounds` 0x7f0310 (HUD, heart-beat loops),
menu widgets 0x7afca9 ... (`MenuSoundInit`: silence / click / change selection), `LockpickCtrl`,
`FlameThrower`, `GrapplingGun`, `FXLightningPlaySound`.

### 2.5 "Is the character playing a sound" (the face's `STOP_SPEAK` condition)

`SoundCtrl.command_is_entity_playing_sound(root)` 0x830fe5 = `SoundSystemNode.GetAllVoicesOnPivot(root)`
is non-empty [R]. Only voices whose **pivot is the character root** count: `play_speak(root)` (speech),
`TriggerActionSound` plays on the character, and collision sounds applied with the root as entity
(footsteps, [I] above). `SOUND` events without the speak flag attach to the capsule or to a position,
and damage sounds to a position, so they do not hold the face in its talk state.

### 2.6 The Dominatrix table

Complete per-state list: `wp6_sound_tables.json` -> `state_sound_events.Enemy04` (167 states with sound,
speak or foot events; 122 with `SOUND` / `SPEAK`; each event with `playpos`, `t_s` = (playpos -
start_playpos) x clip duration / speed, the definition id and its duration range). The class
`Enemy04` is shared with the Twilight Lady, whose states (`BS2_*` clips) are in the same list.
Condensed by sound definition (ids are node ids in `SoundDb.fragment` unless they are voice lines):

| sound definition (SoundDb id) | group | used by (states) | example state @ playpos (t s) | waves | duration s min / mean / max | variation rule | jitter | range m |
|---|---|---|---|---|---|---|---|---|
| `3549a074` swish_08 | PlayerCombatSounds | 65 | Area_A @ 0.44 (0.6818) | Swish_01.wav, Swish_03.wav, Swish_04.wav ... (8) | 0.119 / 0.222 / 0.3338 | one of 8, random no immediate repeat | pitch +-9.86 %, vol +-0.0 % | 5.0 - 30.0 |
| `b43db010`  | Effect | 20 | ThrownByRorschach @ 0.69 (2.185) | concrete_body_hard_01.wav, concrete_body_hard_02.wav, concrete_body_soft_02.wav | 0.209 / 0.4286 / 0.5776 | one of 3, random no immediate repeat | pitch +-1.24 %, vol +-0.0 % | 5.0 - 150.0 |
| `4d7ae5b5` Heavy_Attack_start | PlayerCombatSounds | 20 | BullmoveImpactTarget @ 0.04 (0.0813) | Clothes_hard_01.wav, Clothes_hard_02.wav, Clothes_hard_03.wav ... (13) | 0.3657 / 0.2909 / 0.4615 | all of: one of 8, random no immediate repeat + one of 5, random no immediate repeat | pitch +-8.92 %, vol +-0.0 % | 5.0 - 30.0 |
| `480a3ebb` swish_06 | PlayerCombatSounds | 2 | Events @ 0.55 (None) | Swish_01.wav, Swish_03.wav, Swish_04.wav ... (8) | 0.119 / 0.222 / 0.3338 | one of 8, random no immediate repeat | pitch +-8.92 %, vol +-0.0 % | 5.0 - 30.0 |
| `480a3534` whoosh | PlayerCombatSounds | 6 | GetupFaceUpEnd @ 0.58 (1.1117) | Clothes_hard_01.wav, Clothes_hard_02.wav, Clothes_hard_03.wav ... (13) | 0.3657 / 0.2909 / 0.4615 | all of: one of 8, random no immediate repeat + one of 5, random no immediate repeat | pitch +-8.92 %, vol +-0.0 % | 5.0 - 30.0 |
| `6086f2b9`  | Effect | 5 | BullmoveImpactTarget @ 0.42 (0.854) | Rors_Rollwav.wav | 1.2713 / 1.2713 / 1.2713 | one wave | pitch +-0.0 %, vol +-0.0 % | 20.0 - 200.0 |
| `a5750fc9`  | Effect | 3 | Countered_by_Rorshack_B @ 0.29 (1.2303) | bones_break_long_04.wav, bones_break_long_05.wav, bones_break_long_06.wav ... (5) | 0.2061 / 0.2943 / 0.3686 | one of 5, random no immediate repeat | pitch +-0.0 %, vol +-0.0 % | 5.0 - 100.0 |
| `4d6fe050` Ligth_Attack_start | PlayerCombatSounds | 2 | JumpDown @ 0.26 (0.5633) | Clothes_hard_01.wav, Clothes_hard_02.wav, Clothes_hard_03.wav ... (13) | 0.3657 / 0.2909 / 0.4615 | all of: one of 8, random no immediate repeat + one of 5, random no immediate repeat | pitch +-8.92 %, vol +-0.0 % | 5.0 - 30.0 |
| `ebd7e5e0`  | Effect | 2 | SE_Finished_by_Rorshack_A @ 0.81 (None) | concrete_feet_hard_01.wav, concrete_feet_hard_02.wav, concrete_feet_hard_03.wav ... (4) | 0.1364 / 0.1792 / 0.2235 | one of 4, random no immediate repeat | pitch +-1.24 %, vol +-0.0 % | 10.0 - 150.0 |
| `331a0727` Ragdoll_Ragdoll | Effect | 2 | Finished_by_Rorshack_1H @ 0.64 (2.0945) | Character_character_05.wav, concrete_body_hard_02.wav | 0.5776 / 0.5999 / 0.6444 | one of 3, random no immediate repeat | pitch +-9.04 %, vol +-0.0 % | 5.0 - 50.0 |
| `6a69fd08`  **[speak flag]** | VoiceEnemies | 1 | Events @ 0.24 (None) | BS2_TWL_React_NTO_03_uk.wav | 2.4497 / 2.4497 / 2.4497 | one wave | pitch +-0.0 %, vol +-0.0 % | 12.0 - 150.0 |
| `72914323`  **[speak flag]** | VoiceEnemies | 1 | Events @ 0.25 (None) | BS2_TWL_Attack_RSH_04_uk.wav | 2.8096 / 2.8096 / 2.8096 | one wave | pitch +-0.0 %, vol +-0.0 % | 12.0 - 150.0 |
| `8a82a948`  **[speak flag]** | VoiceEnemies | 1 | Events @ 0.13 (None) | BS2_TWL_React_NTO_02_uk.wav | 5.2274 / 5.2274 / 5.2274 | one wave | pitch +-0.0 %, vol +-0.0 % | 12.0 - 150.0 |
| `aa7c4811`  **[speak flag]** | VoiceEnemies | 1 | Events @ 0.23 (None) | BS2_TWL_Attack_RSH_05_uk.wav | 2.023 / 2.023 / 2.023 | one wave | pitch +-0.0 %, vol +-0.0 % | 12.0 - 150.0 |
| `f131c37c` finishing_fast | Effect | 1 | Finished_by_NiteOwl_A @ 0.69 (3.5545) | Rors_finshing_fast_01.wav | 2.6848 / 2.6848 / 2.6848 | one wave | pitch +-0.0 %, vol +-0.0 % | 10.0 - 200.0 |
| `4f252fe6`  | PlayerCombatSounds | 1 | Finished_by_NiteOwl_G @ 0.73 (2.6324) | whoosh_01.wav | 0.4702 / 0.4702 / 0.4702 | one wave | pitch +-8.92 %, vol +-0.0 % | 1.0 - 30.0 |

| SPEAK event (id) | states (clip @ playpos) | stop current line first |
|---|---|---|
| DAMAGED_LIGHT_FACE (29) | ThrownByRorschach (EN4_COM_DMG_throw_RSH @ 0.00) | no |
| MELEE_START_HEAVY (34) | ThrownByRorschachRagdolled (RSH_COM_ATT_dash_cycle @ 0.32); Events (None @ 0.60); Events (None @ 0.37) | no |
| DAMAGED_LIGHT_STUN (35) | Enemy Stunned (Non Combat) (EN4_COM_DMG_stun_head_front @ 0.00); StunnedHeadBack (EN4_COM_DMG_stun_head_back @ 0.00); StunnedHeadFront (EN4_COM_DMG_stun_head_front @ 0.00); StunnedHeadFront_rorshach (RSH_COM_DMG_stun_head_front @ 0.00); StunnedMiddleBack_NiteOwl (NTO_COM_DMG_stun_body_back @ 0.00); SE_StunnedSpeak (None @ 0.00); SE_StunnedSpeak (None @ 0.00); SE_StunnedSpeak (None @ 0.00); SE_StunnedSpeak (None @ 0.00); SE_StunnedSpeak (None @ 0.00); SE_StunnedSpeak (None @ 0.00) | no |
| SPECIAL_GROUP_3 (40) | GetupFaceDownEnd (EN4_COM_DMG_prone_front_end @ 0.58); GetupFaceUpEnd (EN4_COM_DMG_prone_back_end @ 0.58); GetupLeftEnd (EN4_COM_DMG_prone_left_end @ 0.58); GetupRightEnd (EN4_COM_DMG_prone_right_end @ 0.46); JumpDown (RSH_EXP_JMP_down4m @ 0.23); DodgeBack (EN4_COM_ATT_dodge_back @ 0.46); DodgeLeft (EN4_COM_ATT_dodge_left @ 0.46); DodgeRight (EN4_COM_ATT_dodge_right @ 0.46); SE_ (None @ 0.28); SE_Jump (None @ 0.23); Events (None @ 0.34); BackFlip (BS2_COM_MOV_cartwheel_back_cycle @ 0.94) | no |
| SPECIAL_GROUP_6 (43) | ThrownByRorschach (EN4_COM_DMG_throw_RSH @ 0.43); Finished_by_Rorshack_F (EN4_COM_DMG_finish_RSH_F @ 0.46) | no |
| SPECIAL_GROUP_7 (44) | Finished_by_Rorshack_2H (EN4_COM_DMG_finish_RSH_2H_B @ 0.27) | no |
Other event-independent Dominatrix sounds: footsteps (2.2), attack-start effects and hit effects (2.4),
AI lines (2.3), death line 32 (voices: all three use the Dom1 heavy-damage definition `f9af3729`, 8
waves 0.45 - 1.15 s [D]).

## 3. Variation and randomisation (read from code)

### 3.1 Choice of the variation - `SoundDef.command_sounddef_play_all` 0x831365

The child list is **the node itself followed by its direct `SoundDef` children**
(`command_get_child_sounds` 0x828e3a) [R]. `_iselectionmethod`:

| Value | Behaviour | Count of top-level definitions [D] |
|---|---|---|
| 0 | `ChooseChild` 0x82b53d: random start index, then the first entry that is not quarantined | 6 |
| 1 (default) | random start index; an entry equal to `_ilastindex` is skipped; first not quarantined. So never the same twice in a row, and the entry after the last one is twice as likely as the others (2/N) | 442 |
| 2 | round robin from `_ilastindex` + 1, skipping quarantined entries | 33 |
| 3 | the node's own wave only | 394 |
| 4 | every child is told to play (each child then applies its own method to its own children), then the node's own wave | 45 |

When the chosen entry is a child, the parent sends it `command_quarantine` (0x832287: time left =
uniform in `[m_nquarantinetimemin, max]`, both 0 in the shipped data, so no effect) and forwards the
play; if nothing is chosen the first entry (the node itself) plays. There are **no weights**. The
start delay is uniform in `[_nmindelay, _nmaxdelay]` (`GetDelay` 0x828e0a) and is handed to the voice
as a delayed start.

### 3.2 Pitch and volume jitter - 0x4d094c [R]

`r` = 2 x rand - 1 (0x4cc1c3). `volume = clamp(volume x (1 + r x randomVolumeLength x 0.01), 0, 1)`;
`pitch = pitch x (1 + r' x randomPitchLength x 0.01)` (constant 0.01 at 0x9e8460). Both are then
multiplied by the play call's volume and pitch (0x4d2758). Example: `swish_08` +-9.86 % pitch; voice
lines 0 % [D]. That the random source 0x576418 is uniform in 0..1 is [I].

### 3.3 Distance culling - 0x44a8fa, 0x44700c [R]

A 3D asset (`is3d`) whose position is farther than `maxRange` from **every** listener is not started,
unless the asset is looping; a looping 3D sound out of range is kept as a silent "virtual" voice and
started when a listener comes into range (the per-frame pass 0x44984c also stops a looping 3D voice
that left the range and restarts it later). Non-looping sounds are never resumed.

### 3.4 Voice limits and priority stealing - 0x44a8fa, 0x44853d, 0x44857d [R]

Three counters / limits in the sound system (`+0x0c`, `+0x10`, `+0x14`; counts at `+0x50`, `+0x54`):
when the number of prioritised sounds (priority > 0) has reached `+0x0c`, `FUN_0044853d(priority)`
stops the **first** playing voice in the list whose priority is non-zero and <= the new sound's
priority; then the voice object is created. A hardware voice is started only while playing + waiting voices are below `+0x14`, and then if the
playing count is below `+0x10`, or else if `FUN_0044857d` finds a playing voice with priority <= the new one to stop (a looping
3D victim is only made virtual); if neither, a looping 3D sound stays virtual and anything else is
discarded. Priority 0 sounds are never victims. All 3845 shipped definitions have `Priority` 1 [D], so any
playing sound can be the victim: the first one in the voice list (whether that list is oldest-first was not checked [N]). The numeric limits are not set in the constructors
(0x44a22d, 0x44a7d7) and the `maxVoices` property setter is an empty stub; their run-time values are
[N]. There is no per-definition "max instances" property.

## 4. Speech for the face system

### 4.1 Timing rule

| | When | Evidence |
|---|---|---|
| `START_SPEAK` (action 31) | (a) own `SOUND` event with `m_ttruth1`: at the event, same call as the sound start; (b) `SpeakCtrl.Active`: in the frame a **category 1** line starts, which is 1 - 2 frames after it was queued (and up to `m_ndelay` + 2.0 s later if the speaker was busy); (c) `TriggerActionSound` `SOUND_PLAY` on the character | 0x6aba76; 0x83d936-0x83d94d; 0x853e88 [R] |
| `STOP_SPEAK` (action 32) | (a) `SpeakCtrl.Active`: first frame the line's voice id is no longer playing (any category); (b) `CharacterVisual.command_update_animation`: every frame in which no voice has the character root as pivot | 0x83dbcf-0x83dbeb; 0x69c7d7 [R] |
| Talk duration | wave duration (pitch jitter is 0 on all voice definitions; `_nmindelay/_nmaxdelay` are 0 on all of them [D]) plus at most one frame at the end; cut short by `stop_speak_and_quarantine` when the speaker is hit, is attacked or kills | 2.3 |

Consequences for the exporter:

- **Category 2 lines never open the mouth**: attack shouts (33, 34), hit grunts (26 - 31), stun (35),
  death (32), grenade / electrify (36, 37), special groups. Only category 1 lines and `SOUND` events
  with the speak flag do.
- For the Dominatrix the category 1 lines are 8, 9, 17 - 25 and all of them are requested by the AI
  (2.3), not by animation events; no Dominatrix state has a `SOUND` event with the speak flag. A talk
  segment therefore cannot be placed on any of her animation clips from data. What can be exported is a
  parameterised "FACE Talk" of the right length per line.
- The four speak-flag `SOUND` events of class `Enemy04` are Twilight Lady counters
  (`Counter_A/B NTO/RSH_CattleProd`, waves `BS2_TWL_React_NTO_03/02`, `BS2_TWL_Attack_RSH_04/05`, 2.45 /
  5.23 / 2.81 / 2.02 s, playpos 0.24 / 0.13 / 0.25 / 0.23): these are fixed, single-wave and can be
  baked.
- Choice is random twice: the voice (uniform over the group's voices, fixed per character instance)
  and the wave (method 1 inside the voice's definition).

### 4.2 Lines and durations per character type

Durations are sample count / sample rate from the sound asset headers; all speech is mono 44100 Hz.
"Waves" counts distinct files over all voices of the group. Per-voice and per-wave values:
`speak_groups` and `face_speech.<body class>.lines_by_character` in the JSON.

**Dominatrices** - type 33 `DOMINATRICE`, body class Enemy04, group `DominatricesSpeakDefinition`, 3 voice(s) (Dom1, Dom2, Dom3)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25 | 132 | 1.21 | 3.81 | 7.13 |
| attack shout light (33) | 33 | 11 | 0.26 | 0.59 | 1.65 |
| attack shout heavy (34) | 34 | 29 | 0.19 | 0.74 | 1.55 |
| hit grunt light (29-31) | 29, 30, 31 | 24 | 0.32 | 1.12 | 3.33 |
| hit grunt heavy (26-28) | 26, 27, 28 | 21 | 0.33 | 1.34 | 3.33 |
| stun (35) | 35 | 14 | 1.26 | 2.28 | 5.37 |
| death (32) | 32 | 8 | 0.45 | 0.66 | 1.15 |
| grenade / electrify (36, 37) | 36, 37 | 18 | 0.51 | 1.56 | 2.93 |
| special groups (38-49) | 40, 43, 44 | 33 | 0.25 | 1.05 | 2.91 |

**TwilightLady** - type 35 `TWILIGHT_LADY`, body class Enemy04, group `TwillightSpeakDefinition`, 1 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 24, 25 | 20 | 1.97 | 3.44 | 5.96 |
| attack shout light (33) | 33 | 7 | 0.28 | 0.45 | 0.66 |
| attack shout heavy (34) | 34 | 15 | 0.30 | 0.94 | 1.55 |
| hit grunt light (29-31) | 29, 30, 31 | 16 | 0.32 | 1.43 | 3.33 |
| hit grunt heavy (26-28) | 26, 27, 28 | 13 | 0.33 | 1.76 | 3.33 |
| stun (35) | 35 | 9 | 1.26 | 1.65 | 2.15 |
| death (32) | 32 | 5 | 0.33 | 0.71 | 1.27 |
| grenade / electrify (36, 37) | 36, 37 | 6 | 1.12 | 1.62 | 2.20 |
| special groups (38-49) | 40, 43, 44 | 16 | 0.25 | 1.10 | 2.35 |

**Heavies** - type 29 `HEAVIES`, body class Enemy01, group `HeaviesSpeakDefinition`, 6 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25 | 296 | 1.22 | 2.89 | 5.39 |
| attack shout light (33) | 33 | 43 | 0.29 | 0.39 | 0.70 |
| attack shout heavy (34) | 34 | 48 | 0.35 | 0.78 | 1.27 |
| hit grunt light (29-31) | 29, 30, 31 | 72 | 0.22 | 0.74 | 3.31 |
| hit grunt heavy (26-28) | 26, 27, 28 | 83 | 0.34 | 1.16 | 3.31 |
| stun (35) | 35 | 40 | 0.67 | 1.87 | 3.82 |
| death (32) | 32 | 53 | 0.22 | 0.40 | 0.60 |
| grenade / electrify (36, 37) | 36, 37 | 64 | 0.58 | 1.52 | 3.63 |
| special groups (38-49) | 40, 43, 44 | 99 | 0.29 | 1.03 | 5.33 |

**Thug** - type 8 `THUG`, body class Enemy01, group `KnopTopSpeakDefinition`, 6 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25 | 275 | 1.44 | 3.05 | 7.08 |
| attack shout light (33) | 33 | 35 | 0.21 | 0.38 | 0.60 |
| attack shout heavy (34) | 34 | 38 | 0.44 | 0.78 | 1.36 |
| hit grunt light (29-31) | 29, 30, 31 | 72 | 0.26 | 0.89 | 3.70 |
| hit grunt heavy (26-28) | 26, 27, 28 | 74 | 0.34 | 1.06 | 3.70 |
| stun (35) | 35 | 35 | 0.44 | 1.13 | 3.25 |
| death (32) | 32 | 42 | 0.34 | 0.69 | 1.28 |
| grenade / electrify (36, 37) | 36, 37 | 47 | 0.58 | 1.38 | 3.20 |
| special groups (38-49) | 43, 44 | 36 | 0.46 | 1.38 | 3.18 |

**ThugFast** - type 10 `THUG_FAST`, body class Enemy01, group `KnopTopSpeakDefinition`, 6 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25 | 275 | 1.44 | 3.05 | 7.08 |
| attack shout light (33) | 33 | 35 | 0.21 | 0.38 | 0.60 |
| attack shout heavy (34) | 34 | 38 | 0.44 | 0.78 | 1.36 |
| hit grunt light (29-31) | 29, 30, 31 | 72 | 0.26 | 0.89 | 3.70 |
| hit grunt heavy (26-28) | 26, 27, 28 | 74 | 0.34 | 1.06 | 3.70 |
| stun (35) | 35 | 35 | 0.44 | 1.13 | 3.25 |
| death (32) | 32 | 42 | 0.34 | 0.69 | 1.28 |
| grenade / electrify (36, 37) | 36, 37 | 47 | 0.58 | 1.38 | 3.20 |
| special groups (38-49) | 43, 44 | 36 | 0.46 | 1.38 | 3.18 |

**ThugBig** - type 9 `THUG_BIG`, body class EnemyBig, group `KnopLeaderSpeakDefinition`, 6 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25 | 294 | 1.44 | 3.15 | 7.08 |
| attack shout light (33) | 33 | 28 | 0.21 | 0.39 | 0.60 |
| attack shout heavy (34) | 34 | 31 | 0.44 | 0.81 | 1.36 |
| hit grunt light (29-31) | 29, 30, 31 | 56 | 0.26 | 0.81 | 2.59 |
| hit grunt heavy (26-28) | 26, 27, 28 | 58 | 0.39 | 0.97 | 2.59 |
| stun (35) | 35 | 27 | 1.15 | 2.09 | 3.55 |
| death (32) | 32 | 20 | 0.58 | 1.10 | 3.18 |
| grenade / electrify (36, 37) | 36, 37 | 38 | 0.58 | 1.45 | 3.20 |
| special groups (38-49) | 43, 44 | 39 | 0.46 | 1.38 | 2.67 |

**Gimp** - type 34 `GIMP`, body class Enemy01, group `GimpSpeakDefinition`, 2 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25 | 205 | 1.16 | 3.46 | 6.49 |
| attack shout light (33) | 33 | 26 | 0.28 | 0.56 | 1.21 |
| attack shout heavy (34) | 34 | 18 | 0.45 | 1.06 | 1.86 |
| hit grunt light (29-31) | 29, 30, 31 | 21 | 0.26 | 0.99 | 2.47 |
| hit grunt heavy (26-28) | 26, 27, 28 | 22 | 0.34 | 1.16 | 2.47 |
| stun (35) | 35 | 14 | 0.98 | 2.77 | 4.78 |
| death (32) | 32 | 15 | 0.34 | 0.80 | 1.24 |
| grenade / electrify (36, 37) | 36, 37 | 26 | 0.76 | 1.43 | 2.81 |
| special groups (38-49) | 40, 43, 44 | 29 | 0.44 | 1.02 | 2.18 |

**GimpGagBall** - type 36 `GIMP_WITH_GAGBALL`, body class Enemy01, group `GagballGimpSpeakDefinition`, 2 voice(s) (Gimp1, Gimp2, Gimp3, Gimp4)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 8, 9, 17, 18, 19, 20, 21, 22, 23, 24, 25 | 33 | 1.71 | 3.20 | 6.57 |
| attack shout light (33) | 33 | 26 | 0.28 | 0.56 | 1.21 |
| attack shout heavy (34) | 34 | 18 | 0.45 | 1.06 | 1.86 |
| hit grunt light (29-31) | 29, 30, 31 | 21 | 0.26 | 0.99 | 2.47 |
| hit grunt heavy (26-28) | 26, 27, 28 | 22 | 0.34 | 1.16 | 2.47 |
| stun (35) | 35 | 14 | 0.98 | 2.77 | 4.78 |
| death (32) | 32 | 15 | 0.34 | 0.80 | 1.24 |
| grenade / electrify (36, 37) | 36, 37 | 26 | 0.76 | 1.43 | 2.81 |
| special groups (38-49) | 40, 43, 44 | 29 | 0.44 | 1.02 | 2.18 |

**Rorchach** - type 0 `RORSCHACH`, body class Rorschach, group `RorchachSpeakDefinition`, 1 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 3, 4, 17 | 12 | 1.45 | 2.35 | 3.97 |
| attack shout light (33) | 33 | 12 | 0.18 | 0.48 | 0.73 |
| attack shout heavy (34) | 34 | 8 | 0.40 | 0.57 | 0.75 |
| hit grunt light (29-31) | 29, 30, 31 | 10 | 0.33 | 0.61 | 1.32 |
| hit grunt heavy (26-28) | 26, 27, 28 | 8 | 0.49 | 0.70 | 0.88 |
| stun (35) | 35 | 10 | 0.33 | 0.61 | 1.32 |
| death (32) | 32 | 8 | 0.49 | 0.70 | 0.88 |
| special groups (38-49) | 38, 39, 40, 41, 42, 43, 44, 45 | 40 | 0.40 | 0.86 | 1.85 |
| other ids | 10, 11 | 12 | 0.40 | 1.15 | 2.76 |

**NightOwl** - type 1 `NITE_OWL`, body class NiteOwl, group `NightowlSpeakDefinition`, 1 voice(s)

| trigger family | speak ids that play | waves | min s | mean s | max s |
|---|---|---|---|---|---|
| taunt / spotted / get-up / melee-on-target (category 1: START_SPEAK) | 3, 4, 17 | 14 | 0.57 | 1.89 | 3.37 |
| attack shout light (33) | 33 | 10 | 0.29 | 0.59 | 0.74 |
| attack shout heavy (34) | 34 | 10 | 0.33 | 0.85 | 1.06 |
| hit grunt light (29-31) | 29, 30, 31 | 9 | 0.40 | 0.55 | 0.82 |
| hit grunt heavy (26-28) | 26, 27, 28 | 7 | 0.66 | 0.97 | 1.46 |
| stun (35) | 35 | 9 | 0.40 | 0.55 | 0.82 |
| death (32) | 32 | 7 | 0.66 | 0.97 | 1.46 |
| special groups (38-49) | 39, 40, 41, 42, 43, 44, 45, 46 | 16 | 0.50 | 1.26 | 3.28 |
Body classes of Gimp, Thug, ThugFast, Heavies (`Enemy01`) and ThugBig (`EnemyBig`) are [I] (not checked
against the character fragments here); Dominatrix / Twilight Lady = `Enemy04` is [D]
(`dominatrix_audit.md`, `face_map.json`).

### 4.3 What the JSON gives the face rule

`face_speech.<body class>`: `face_class`, `characters`, `state_events` (per body state: `SOUND` with
speak flag -> definition, duration range, rule; `SPEAK` event -> per character: category,
`start_speak`, probability, quarantine, per-voice n / min / mean / max), and `lines_by_character`
(every playable speak id with the same fields, for AI-triggered lines). `face_speech_rule` repeats
4.1. Recommended use: bake nothing for category 2; for a state event with `start_speak` true emit a
talk segment from `t_s` of length `duration_s.mean` flagged sound dependent, or one variant per wave;
offer AI lines as standalone talk clips of the listed lengths.

## 5. Playback path

### 5.1 The PC sound asset and its decode

Header blob of a `sound` asset after the property bag (`pe` = property-bag end, 134 in every file
checked). Layout read from the loader 0x449e40 and confirmed on 2727 headers
(`work/wp6/rawhdr.tsv`) [R + D]:

```
pe+0   u8   looping            -> SoundSlot.assetIsLooping; voice loops the whole sample
pe+1   u8   is3d
pe+2   u32  channels           1 (2692 files) or 2 (35)
pe+6   u32  original rate      48000 (2487) / 44100 (240); kept only as rate / original ratio
pe+10  u32  format             1 = PCM16, 2 = MS-ADPCM (3 = XMA2, console)
pe+14  u32  sample rate        44100 for every mono file; 43937 ... 48016 for the 35 stereo files
PCM:   pe+18 u32 samples, pe+22 u32 data bytes (= samples x 2 x channels), pe+26 data
ADPCM: pe+18 u32 blockAlign x rate x 128 (the engine uses blockAlign x rate / 128 as nAvgBytesPerSec),
       pe+22 u32 samples, pe+26 u32 blockAlign (70 mono, 140 stereo), pe+30 14 x i16 coefficients,
       pe+58 u32 data bytes, pe+62 data
then   u32 cue count, cue x { string name, u32 time }      (0 in all 2727 sound assets)
```

Property bag of the asset class (`SoundAsset` registration 0x552716): `looping`, `is3d`, `xmaQuality`,
`mp3CompressionRatio`, `useAdpcm`, `pcSampleRate` (0 = original, 22050 ... 48000).

Counts [D]: 2687 MS-ADPCM, 40 PCM16; 55 looping (ambience loops, heart beats, trash-can roll, menu
music, four `PornoMusic` loops); 47 non-3D. 192 speech headers (Rorschach, Twilight Lady, some Nite
Owl) could not be read in the scan (the PC folder walk skipped them) and are covered only by the
decoded lengths.

**Decode** [R, 0x40271b]: the engine does not decode. It fills a `WAVEFORMATEX` - tag 1, 16 bit, or
tag 2 (`WAVE_FORMAT_ADPCM`) with `wBitsPerSample` 4, `cbSize` 32, 7 coefficient pairs copied from the
asset and block align from the asset - and creates an XAudio2 source voice on it; XAudio2 2.0 decodes
MS-ADPCM itself. One `SubmitSourceBuffer` per sound with `XAUDIO2_END_OF_STREAM`, `AudioBytes` and
`pAudioData` straight from the asset (0x40228c): sounds are fully **in memory**. Looping = `LoopCount`
infinite over `LoopLength` = the asset's sample count, from sample 0: there are no loop points.
`PlayBegin` = start offset (the play call's `offsetSec`).

Voices flagged at `+0x10c` are created at the device rate with a frequency ratio of asset rate /
device rate (`+0x110`), and taken from a pool of pre-created voices when one is available
(0x4026dc); others are created at the asset rate. Which sounds get the flag was not traced [N]; the
data pattern (every mono sound resampled to 44100 at bake time, stereo ones left at their own rate)
suggests the pooled path is the mono one [I].

### 5.2 Voice graph [R]

| Voice | Created | Channels | Effect chain |
|---|---|---|---|
| Mastering | 0x403b9d (root node) `CreateMasteringVoice(6, device rate)` | 6 | `MasterDownMixEffectXAudio2` + a second effect from 0x402bcc ([I] the `AudioVolumeMeter`: 0x445db8 reads 6 peak levels from effect index 1) |
| Effect-node submix (`SoundEffectNode` "EnvironmentEffect") | 0x403b9d `CreateSubmixVoice(6)` -> parent | 6 | `EqualizerEffectXAudio2`, `CompressorEffectXAudio2` (both created disabled; enabled when a definition named `equalizer` / `compressor` is applied, 0x403fd3) |
| Reverb submix (same node class, reverb flag) | 0x403b9d `CreateSubmixVoice(1)` | 1 in | XAudio2 `AudioReverb` (0x402bf2, CLSID_AudioReverb); output matrix 1 -> 6 = {1, 1, 0, 0, 0, 0} (front left / right only); volume starts at 0 |
| Source voice | 0x40271b `CreateSourceVoice(format, flags, maxFrequencyRatio 4.0, callback, effect chain)` | 1 or 2 | 3D voices: `EnvironmentFilterEffectXAudio2` (1 in, 2 out). Flag 0x10 (`XAUDIO2_VOICE_MUSIC`) when the voice's group test 0x446611 is true ([I]: the `isMusic` groups) |

Sends of a source voice (`SetOutputVoices`, 0x402996): the group's effect-node voice (`+0x4c`: the
group's `m_esoundeffectprocessor` chain, else the mastering node) and, for 3D voices in a group that
has one, the reverb voice (`+0x50`). `SoundGrp` nodes themselves are not voices: group volume and
pause are folded into each voice's volume (`+0x80`) and pause flags. So in the shipped data only
`ProcessorGroup`'s descendants (all character voices and combat effects) pass the equalizer /
compressor and can feed the reverb; `Effect_no_reverb_*`, `VoiceOverRorschach`, music and the menu
groups go straight to the master [D + R].

### 5.3 3D maths - the engine's own (0x44882d, 0x4460f9, 0x447274, 0x44785f) [R]

`X3DAudioInitialize(0x3f, 346.6, ...)` is called (0x448336) but nothing else of X3DAudio is used.

- **Base gain** g0 = controller volume (`+0x88`) x group volume (`+0x80`) x law(slot volume) (`+0x18`).
- **Volume law** 0x445b43: law(v) = 0.15 v + 0.85 v^2, v clamped to 0..1 (constants 0x9eb188,
  0x9eb190). `SoundController.volumeCurve` 0x4463bf: 1 = that law, 2 = sqrt(v), 3 = 1 - cos(v pi/2),
  other = linear.
- **Distance curve** 0x447274, evaluated by linear interpolation 0x415ddb. With `linearDistAtt`:
  points (0, 1), (min, 1), (max, 0). Otherwise (shipped setting), with R = `rollOffScale`:
  g(d) = 1 / (1 + R (d / min - 1)); the curve is (0, 1), (min, 1), three points at gains
  g_k = g(max)^(k/4), k = 1..3, at the distances where the inverse law has those gains, and (max, 0).
  The same construction with `reverbMinRange` / `reverbMaxRange` gives the reverb curve.
- **Panning** 0x4460f9: the source offset is rotated into listener space (listener quaternion);
  theta = acos(z / sqrt(x^2 + z^2)) - height is ignored. Amplitude (not power) panning over FL, FR, C,
  LFE, SL, SR:
  - theta < 30 deg: side front = theta / 30 deg, centre = 1 - that;
  - 30 .. 110 deg: side surround = (theta - 30) / 80, side front = 1 - that;
  - > 110 deg: r = (theta - 110) / 140; same-side surround = 1 - r, other surround = r (0.5 / 0.5
    straight behind);
  - LFE = `lfeChannelLevel`; side = right when x > 0.
  (constants 0.5236, 1.9199, 1.3963, 2.4435 rad at 0x9e97f0, 0x9eb208, 0x9eb200, 0x9eb1f8.)
  Output matrix = pan x curve(distance) x g0, on source channel 0 of the filter's two outputs.
- **Reverb send** = reverbCurve(distance) x g0 x `reverbMixFactor`, routed from filter channel 1 to
  the reverb voice, and only while the reverb effect is active.
- **Doppler** 0x44785f: c = 346.6 / `dopplerFactor`; ratio = (v_listener . u + c) / max(v_source . u
  + c, 1e-6), u = unit vector listener -> source, velocities = position difference / frame time
  (0x447546); 1 when `dopplerFactor` <= 0 (the value on every definition examined).
- **Frequency ratio** 0x40228c: clamp(controller pitch x slot pitch x doppler x rate ratio, 1/1024,
  4.0).
- **2D voices** 0x44623c: mono -> L = R = 0.707 g0 (or centre only), LFE = `lfeChannelLevel` x g0;
  stereo -> L, R = g0, LFE from each channel x 0.5; 6-channel -> identity.

**Listeners in co-op** (0x44882d first half, listener count at `+0x68`, 0x50 bytes each) [R]: with two
listeners each gets its own curve value a_i. `multiListenerDistanceAttenuationType`: 0 ADDITIVE as is;
1 SATURATE divide by (a_0 + a_1) when the sum exceeds 1; 2 CLOSEST (shipped) scale both by
max(a) / (a_0 + a_1). Each listener's pan x a_i x g0 / (1 + `multiListenerGeneralAttenuation`) is
**summed** into the one matrix; `multiListenerSeparationPanning` s cross-mixes listener 0 towards the
left and listener 1 towards the right; with `multiListenerDisableOrientationPanning` the pan is
replaced by L / R = 0.5 (1 +- s), surrounds 0.4 (1 +- s). Doppler = sqrt of the product of both ratios
unless `multiListenerDisableDoppler`. So there is no "chosen" listener: both players hear a mix. Who
places the listeners (camera or character) was not read [N].

### 5.4 The four XAPO effects (Process = vtable slot 10)

| Effect | Process | What it does [R] |
|---|---|---|
| `EnvironmentFilterEffectXAudio2` | 0x402e59; parameters 0x402f0e | Per 3D source voice, mono in, 2 out. Two one-pole low-passes y += (1 - a)(x - y): out[1] = LP1(in) (to the reverb), out[0] = LP2(LP1(in)) (direct). Coefficient from a parameter p clamped to 1e-5 .. 0.99999: g = 1 - p, cw = cos(2 pi 500 / fs) (constant 3141.59 at 0x9e5c40), a = (1 - g cw - sqrt(2 g (1 - cw) - g^2 (1 - cw^2))) / (1 - g): the standard "gain g at the reference frequency" design, reference 500 Hz. p for LP1 = zone **occlusion** (voice `+0xd4`), p for LP2 = **obstruction** (`+0xd8`) |
| `EqualizerEffectXAudio2` | 0x403106 | 6 channels, three switchable all-pass-based sections in series: first-order shelf using x - allpass (high shelf), second-order peak, first-order shelf using x + allpass (low shelf). 16 parameter words (0x4032ce); coefficient conversion 0x4038d3 not read. The shelf / peak naming is [I] from the filter structure |
| `CompressorEffectXAudio2` | 0x4032e8 | Per channel feed-forward compressor: env = (env x k1 + |x|) / k2; above the threshold gain = 10^(-(20 log10 env - T) x slope / 20) with slope = 1 - 1 / ratio (0x403fd3); gain smoothed with an attack coefficient when falling and a release coefficient when rising; output x make-up gain |
| `MasterDownMixEffectXAudio2` | 0x40353d | On the mastering voice, 6 channels: every sample x master gain (`masterAttenuationPC`, set through 0x445ef2 / 0x4035e0); when the speaker mode is below 3 (stereo / mono, flag set in `LockForProcess` 0x40350b) channel 3 (LFE) is additionally x `lfeDownMixLevelPC` (0 in the data: LFE dropped on stereo) |

There is no limiter other than the compressor and no pitch effect; Doppler is the source frequency
ratio.

### 5.5 Occlusion, obstruction, reverb zones

Per frame per 3D voice with `enableObstructionAndOcclusion` (0x447546) [R]:

- **Occlusion** `+0xd4` = 1 - T, `FUN_0044e586`: listener and source each lie in a weighted set of
  `SoundEnvironment` zones (a tree: parent `+0x30`, depth `+0x34`, `_nocclusionfactor` `+0x48`). For each
  pair the path through the tree to the common ancestor multiplies (1 - occlusion factor) of every
  zone left or entered; T = sum of weight_L x weight_S x product. Recomputed when the voice moved or
  the listener set changed.
- **Obstruction** `+0xd8` = `obstructionFactor` (0.5) x `FUN_0044d949`: the segment listener ->
  source is tested against the obstructor boxes (`_tobstructor`), only when there is exactly one
  listener; accumulation details and the worker job were not read [N beyond that].
- **Reverb**: each zone names a `SoundEffectDefinitionNode`; applying a definition of type
  `xaudio2_i3dl2_reverb` converts the 12 I3DL2 values to the native reverb parameters (0x402c18),
  `SetEffectParameters`, enables the effect and sets the reverb voice volume to the definition's
  `Level` (0x403fd3) [R]. How the listener's zone is chosen and cross-faded over `_nfadedepth` is [N]
  (the script side is `SoundCtrl.command_get_environment_effect` 0x82fd34; not read).

### 5.6 Mix states

- **User volumes**: `SoundCtrl.command_set_master/effects/music/voice_volume` (0x82fd6a ...), read from
  `GameStateCtrl` at start-up; applied as group volumes.
- **Damping during subtitled speech**: `SubtitleHUD.command_show_subtitle` 0x84a20c ->
  `SoundCtrl.command_damp` 0x83104a: effects groups and music groups are faded to their volume x
  `_ndampfactor` (0.65) in `_ndamptime` (0.1 s), the enemy voice group to 0.65; restored in
  `_nundamptime` (0.2 s) by `SoundCtrl.StateActive` 0x829f70 [R; the un-damp branch skimmed].
- **Menu pause**: `command_toggle_menu_pause` 0x830c91 sets `pause` on every `SoundGrp` with
  `m_tstopgroupinmenu` (all in-game groups; the `Menu*` groups keep playing) [R].
- **Group control from level script**: `TriggerActionSound` -> `command_group_pause/unpause`,
  `command_set_group_volume`, `command_cross_fade`, `command_stop_all` [R, call map].
- **Slow motion**: `WorldLib.SetTimeMultiplier` 0x8a9d27 only sets the scene time multiplier and the
  physics rate; nothing in it or in the voice update multiplies pitch by the time scale, and
  `SoundCtrl` runs on real time (`UseRealTime` true [D]). Sounds are therefore not pitched down in slow
  motion [I: absence of code on the paths read].
- **Pause of speech**: `TriggerActionSound.PauseSpeakSystem` 0x853d2b -> `SpeakCtrl.command_pause` /
  `unpause` (counter `_ipaused`; new requests refused while > 0) [R].

### 5.7 Bink

Movies use Bink's own DirectSound output, not XAudio2: `BinkSetSoundSystem(BinkOpenDirectSound,
device)` (part_0002.c line 6865; `DirectSoundCreate8` caller 0x4359ca, `submap.md`), four sound tracks
(`BinkSetSoundTrack(4, ids)`), and per-track mix-bin volumes: tracks to bins {0, 1} (front pair), {2}
(centre), {3} (LFE, muted unless a sound-system query returns true), {4, 5} (surround), all scaled by
min(1, movie volume x system volume) (`BinkSetMixBinVolumes` / `BinkSetVolume`, part_0002.c lines
11020-11060) [R]. `movieAttenuation` (-3 dB) is the property behind the movie volume [I].

### 5.8 Music

**Data** [D]: a `MusicSetup` holds a `MusicStreamSlot` (`streamingSound` = `<name>_track0.wav`, a
`mediastream` descriptor; `track0..track9` = human-readable track names such as "Percussion",
"Strings", "Terror"), a `MusicIntensityContainer` with `MusicIntensityDefinition`s (levels 01..05 ->
`MusicTrigger`), and `MusicTrigger`s ("track states": `m_nminplaytime`, `m_nmaxplaytime`, children
`MusicTrackCtrl` {`track_index`, `volume`, `fade_time`, `change_on_cue`}). A music stream is one
**multi-track** file: all tracks play in sync and a track state is a set of target volumes per track.
Bordello's "UndergroundmusicIntro": 5 stereo tracks of 48.0 s at 48 kHz, 17 cue points named `click1`
on track 0 (about every 3 s); states MusicIntro, NoAction1/2, LevelIntensity1/2; times 20 / 40 s.
`MusicStaticSlot` / one-off sounds are ordinary `SoundDef` stingers (`Music/*fx*.wav`).

**Intensity** - `MusicIntensityCtrl.StateActive` 0x7ce905 [R; nesting of the level tests from a
flattened decompile]: for every member of the watched faction (`m_iwatchedfaction`, 0;
`CombatOrchestrator.command_get_faction`) that has known enemies, its attackers
(`command_get_attackers`) are counted in three distance classes (near < the attacker definition's
value at `+0x44`; middle < an `AILib` global; far otherwise, within a maximum). Level: at least 1;
far > 0 -> 2; middle >= 1 or far >= 2 -> 3; near >= 2 or middle >= 2 -> 4; near >= 4 -> 5; never below
the previous level while attackers remain, except that with fewer than 4 attackers a level above 3 is
capped at max(previous, 3). No attackers -> 0.

**State selection** - `SoundCtrl.StateActive` 0x829f70 [R, same caveat]: playing level p, game level
L. While a forced play time runs, nothing changes. If L > p and the current state has played longer
than its `m_nminplaytime`, p increases by one (one step at a time). If L <= p and the state has played
longer than `m_nmaxplaytime`, p restarts at 1. If L = 0, p = 0 at once. p = 0 plays the setup's
default state (or the "next default" set by a trigger, once); p > 0 plays the definition's level p
via `command_set_music_track_state_from_reference` 0x830810 -> `MusicPlayer.track_switch` 0x7cf77c,
which fades each track to its volume over `fade_time`, at once or at the next cue point when
`change_on_cue` is set (`cue_point_event` 0x7cfb52; the queueing code was not read [N]).
Level script can override with `TriggerActionSound` actions 8 - 12.

**Stream decode** [I]: `MediaStream*` / `PcmStreamTrack` / `SoundStreamSink` classes
(0x44bb26 - 0x450bc7) and the embedded Vorbis decoder feed stream voices; a stream voice (no asset)
allocates a 0x12000-byte PCM buffer (0x40271b) [R for the buffer]. The packet path was not read.

## 6. Extractor consequences

### 6.1 Defects in today's audio export

| # | Finding | Evidence | Fix |
|---|---|---|---|
| E1 | **Multi-track music is flattened.** A PC `.mediastream_s` is a sequence of groups; each group holds one chunk per track, and every track's first chunk starts with its own three Vorbis header packets. `_audio_packets()` (`watchmen_extract.py` 3199) walks all packets in file order, keeps the first header triplet and appends every other packet, so the `.ogg` contains chunk 0 of track 0, chunk 0 of track 1, ... then chunk 1 of track 0 ... 10 of the 13 streams have 2 - 7 tracks | [D] `files/derived_pc/sounds/music/04_underground/underground_part1/underground_track0.mediastream_s`: header triplets (first bytes 1, 3, 5) at offsets 0, 51158, 94502, 145159, 192100 = cumulative chunk sizes 51158, 43344, 50657, 46941, 51002 listed in the descriptor `extracted/sounds/Music/04_Underground/underground_part1/Underground_track0.wav` (class `mediastream`: track count 5, per track source name, 2304001 samples, 2 ch, 48000 Hz). Decoded lengths: Underground 239.8 s = 5 x 48.0; `l4_a` 74.7 s = 7 x 10.67; `str_p2` 153.7 s = 7 x 21.94 | De-interleave: the descriptor gives, after the stream path, [u32 m][u32 chunk size x tracks] for group 0; each group is followed by a link record of the same shape for the next group, m = sum(sizes) + 4 x (tracks + 1) - seen at offset 243102: m = 227488, sizes 47960, 39138, 47359, 42291, 50716. This is the link format `WATCHMEN_EXTRACTION_MASTER.md` already documents for the console streams. Write one `.ogg` per track, named from `MusicStreamSlot.track0..9`, with a sidecar of cue points |
| E2 | **Stereo sounds have the wrong rate.** `decode_sfx()` (line 3873) writes 44100 Hz for every sound. The real rate is the u32 at `pe+14`; `pe+6` is the original rate. All 2692 mono sounds are 44100, but all 35 stereo sounds are 43937 ... 48016 (25 of them about 48000): music stingers (`Music/*fx*`, `SpecialMoves/ComboEffect_*`, `main_volumen_music`), `ExplosionCar_0n_st`, `ExplosionAndFire` | [R] loader 0x449e40 field order; voice creation 0x40271b uses asset `+0x18` as rate. [D] `work/wp6/rawhdr.tsv` | read the rate at `pe+14` |
| E3 | **PCM data is read 4 bytes late.** PCM layout is samples `pe+18`, byte count `pe+22`, data `pe+26`; the extractor slices from `pe+30`, losing the first two samples and running 4 bytes into the cue count (40 PCM files) | [R] 0x449e40; [D] `Character/Footstep/Medium_stepsdirt_L_01.wav`: `pe+22` = 0x8220 = 2 x samples 0x4110, data follows at once | slice `pe+26 .. pe+26+bytes` |
| E4 | The comment "the engine resamples every PC sound to 44100" is true for mono sounds only (bake-time `pcSampleRate`), see E2 | same | reword |

Speech durations are not affected by E1 - E3 (all speech is mono ADPCM at 44100; the decoded frame
counts equal the header sample counts for all 2727 headers compared).

### 6.2 Present in the data, not exported

- **Loop flag** (`pe+0`): 55 sounds. Loops are whole-sample; no loop points exist. Export as
  `"loop": true` in a sidecar or a `smpl` chunk covering the file.
- **3D flag** (`pe+1`), original rate (`pe+6`), codec (`pe+10`).
- **Cue points**: 0 in all sound assets; present in the music descriptors (per track: name + sample
  position, e.g. 17 x `click1` in Underground track 0, `Perc_01` / `LongMelody` in `str_p2`). They are
  what `MusicTrackCtrl.change_on_cue` refers to.
- **Track names and track states** of the music (`MusicStreamSlot.track0..9`, `MusicTrigger`,
  `MusicTrackCtrl`): in the fragments, not attached to the audio output.
- **Sound definitions**: everything in section 1.2 is in the fragments (already parsed to
  `.fragment.json`), but nothing joins a wave to its definitions, group, variations or events.
- **Language variants**: audio is not switched by the six language slots. 2125 of 2934 waves end in
  `_uk.wav` and no other language suffix exists in the PC data [D]; the slots matter only for the 14
  localised `_uk` text assets of the main block (`KAPOW_NAZ_FORMAT.md` 2.1). Those text assets -
  among them the subtitle resources referenced by the `SubtitleSlot`s in `MovieDbPart2.fragment`
  (`/Localize/SubtitlesPrison_uk.txt` on `IngameSubtitles`, `Cutscene08a_uk.txt` ...) and the menu texts
  in `TextSlots.fragment` - are **not in** `20260708/extracted/Localize/` (only `ControllerLayout_pc.txt`
  is) [D]. Subtitles are keyed by sound slot: `SoundDef.Active` 0x82aecf asks
  `SubtitleHUD.command_get_subtitle_slot_for_sound_slot` 0x8492fa (native
  `SubtitleSlot::HasSubtitleForSoundSlot` 0x4d91bf, `GetIndexFromSoundSlotAndTime` 0x4da3e7) and shows it,
  which also triggers the damping of 5.6 [R]. The text-resource format and the key that links a line to
  a sound were not read [N].
- **Naming**: wave names are the asset paths and are correct. The music files are named
  `<x>_track0.mediastream_s.ogg` although they hold all tracks (E1). Three voice folders are shared
  across characters by the definitions (the Dominatrix voices Dom2 and Dom3 point at the same
  `EN4_DOM2_*` damage waves; her death line uses Dom1 files for all voices) - that is data, not a
  labelling error.

### 6.3 Proposed `sounds` section of the character metadata

```json
"sounds": {
  "format": "watchmen-sounds/1",
  "character_type": 33, "speak_group": "DominatricesSpeakDefinition", "voices": ["Dom1","Dom2","Dom3"],
  "definitions": { "<id>": { "name": "swish_08", "group": "PlayerCombatSounds", "start_delay_s": [0.05, 0.1],
      "range_m": [5, 30], "duration_s": {"min": 0.119, "mean": 0.222, "max": 0.334},
      "play": { "mode": "one_of", "rule": "random_no_immediate_repeat",
                "options": [ {"wave": "audio/sounds/Effects/Combat/Swish/Swish_01.wav", "duration_s": 0.119,
                              "random_pitch_pct": 9.86, "random_volume_pct": 0} ] } } },
  "states": { "<state path>": [ {"event": "SOUND", "t_s": 0.68, "playpos": 0.44, "definition": "<id>",
                                 "speak_flag": false, "position": "world|follow"},
                                {"event": "SPEAK", "t_s": 0.0, "speak": "DAMAGED_LIGHT_STUN"},
                                {"event": "RIGHT_FOOT_DOWN", "t_s": 0.31} ] },
  "speech": { "<speak id>": { "speak": "MELEE_ON_TARGET_A", "category": 1, "start_speak": true,
              "quarantine_s": [20, 40], "probability": 1.0,
              "voices": [ {"name": "Dom1", "definition": "<id>"} ] } },
  "footsteps": { "step|jump|stop": [ {"surfaces": ["MATERIAL_CONCRETE_DRY"], "definition": "<id>"} ] },
  "effects": { "attack_start": {"light": {"speak": 33}, "heavy": {"speak": 34}, "weapon": {"definition": "<id>", "speak": 34}},
               "damage": { "EN_dam_head_light": {"definition": "<id>", "speak": 29} } }
}
```

All of it can be produced from the fragments alone with the rules of sections 1 - 3
(`work/wp6/lib.py` `tree()` / `res()` are a reference implementation; durations need the wave headers).
`wp6_sound_tables.json` already holds these tables for the ten character definitions. Glue needed in
the toolkit: resolve `[instance id, node id]` references per fragment (1.3), keep the event fields
`_etarget00`, `m_ivalue00`, `m_ttruth1` in `anim_meta`, and add the speak category to the face rule so
that only category 1 lines and speak-flag `SOUND` events create talk segments.

## 7. Not established

| Item | What it would take |
|---|---|
| Exact truth table of `ShouldIgnoreThisSpeaker` 0x83ae84 for category 1 (which playing lines block which, player vs non-player) | disassemble the loop 0x83ae84 - 0x83afd5 with the record offsets +0x20 / +0x24 and the definition field +0x4c; 338 bytes |
| Any use of `m_ipriority` (`SPEAK_PRIORITY`) | search readers of record field +0x18 / definition field +0x14 outside `fill_speak_def_struct` |
| Senders of speak ids 8 / 9 (counter-attack taunts), 36, 37 for the enemies | follow `CharacterRootLogic` counter states and the cases 29 - 31 of the event handler |
| Caller and index argument of `PlayAttackStartEffects` 0x677b58 | resolve its slot in the `CharacterRootLogic` method table and grep the invoke offset |
| Footstep: whether the sound is attached to the root or placed (affects `STOP_SPEAK` while walking); what sets the water probe value | read `ApplySubEffect` 0x82b7a7 in disassembly and the block 0x6a533a - 0x6a5c87 before the lookup |
| Ragdoll contact effect types and the force -> volume curve | read 0x69d00a lines 480 - 730 and `WorldLib.GetVolumeBasedOnContactForce` |
| Numeric voice limits (sound system +0x0c / +0x10 / +0x14) and which voices are pooled (`+0x10c`) | find the writers (not in the constructors; probably the platform init or `SoundSystemNode` start-up) |
| Listener placement (camera or character) and update | read `SoundSystemNode` listener setters and their script callers |
| Obstruction geometry and its worker job; zone weights and reverb cross-fade (`_nfadedepth`) | `FUN_0044d949` (3.1 kB), the "sound obstruction" job, `SoundCtrl.command_get_environment_effect` 0x82fd34 and its caller |
| Equalizer coefficient formulas and the parameters of the shipped `equalizer` / `compressor` definitions (none found in `EffectDefinitions`: only reverbs) | 0x4038d3 (714 bytes); search fragments for definitions named `equalizer` / `compressor` |
| Slow-motion and pause effect on pitch (stated as "none" by absence) | check `SceneNode.SetTimeMultiplier` consumers in the sound nodes |
| Music cue queueing (`MusicPlayer.cue_point_event` 0x7cfb52, `track_switch` 0x7cf77c), exact nesting of the intensity thresholds | read both handlers and re-read 0x7ce905 in disassembly |
| PC stream decode path (Vorbis packets -> PCM -> stream voice), link-record format of `.mediastream_s` | `MediaStreamTrack` / `PcmStreamSink` (0x44bd20 ...), and parse two more streams against their descriptors |
| Subtitle text-resource format and its sound key; extraction of the 14 localised text assets | parse a `textRes` header blob from the block's localized directory |
| `m_tmissionspeak` (97 definitions) and `SoundDef.command_play_activator` 0x831e22 (sound controller request, fades) | read 0x831e22 (737 bytes) and `SoundDef.Active` subtitle branch |
| 192 speech headers not scanned (Rorschach, Twilight Lady, part of Nite Owl) | rerun `rawhdr` scan on those folders; their durations currently come from the decoded files (mono, so correct) |
| Body class of Gimp / Thug / Heavies entries in the JSON | read `m_eanimationdata` of the ten character fragments |
