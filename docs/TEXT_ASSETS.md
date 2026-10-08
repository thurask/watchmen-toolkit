# Text assets and subtitles

    python3 watchmen.py extract game.naz OUT            # writes OUT/text/ among the rest
    python3 watchmen.py text game.naz OUT               # only OUT/text/
    python3 watchmen.py textmeta OUT OUT/text_meta.json # strings + subtitle linkage

## `text/`

    text/index.json
    text/<en|fr|it|de|es>/Localize/Menu_uk_pc.txt        the raw asset (UTF-16 table)
    text/<..>/Localize/Menu_uk_pc.txt.json               decoded, rows in file order
    text/<..>/Localize/Menu_uk_pc.txt.csv                index,key,text (UTF-8 with BOM)

Languages are the block's slots 0 - 4: English, French, Italian, German, Spanish. Slot 5 (Danish)
is a copy of the English slot in the shipped games and is not written; `index.json` says so
(`identical_to_slot`). A table that is not localized is written into every folder.

### Language slots and how the game picks one
*Added 2026-10-05.*

| Slot | `LANGUAGE` enum (0x47ff8c) | Folder (`code`) | Engine code (`engine_code`) |
|---|---|---|---|
| 0 | `LANGUAGE___ENGLISH` | `en` | `uk` |
| 1 | `LANGUAGE___FRENCH` | `fr` | `fr` |
| 2 | `LANGUAGE___ITALIAN` | `it` | `it` |
| 3 | `LANGUAGE___GERMAN` | `de` | `de` |
| 4 | `LANGUAGE___SPANISH` | `es` | `es` |
| 5 | `LANGUAGE___DANISH` | (`da`, not written) | `dk` |

The engine codes are registered by the platform constructor (0x45fb96). The asset path rewriter
(0x54e890) uses them: with its localize argument it looks for `/uk/` and `_uk` and builds
`/<code>/` and `_<code>`; `GetCurrentCountryCodeMSG` (0x47b9ec) returns the code to scripts.
`extract --language` takes a slot number or any of these names and codes (`german`, `de`, `3`).

The current language (0x45c762) indexes the six slots of every block record and the header's
language seek table. Any system language not listed gives **English**:

| Platform | Source | French 1 | Italian 2 | German 3 | Spanish 4 | Danish 5 |
|---|---|---|---|---|---|---|
| PC (0x45c7a6) | `GetLocaleInfoA(0x800, LOCALE_ILANGUAGE)`: the system default locale, not the display language | 0x40c, 0x80c, 0xc0c, 0x100c, 0x140c, 0x180c | 0x410, 0x810 | 0x407, 0x807, 0xc07, 0x1007, 0x1407 | 0x40a, 0x80a … 0x500a (20 ids) | never: 0x406 gives English |
| X360 (0x82a34a20) | console language (1 gives English) | 4 | 6 | 3 | 5 | any other language when the locale function 0x825b38c8 returns 10 |
| PS3 (0x154ee0) | `cellSysutilGetSystemParamInt(0x111)` | 2 | 5 | 4 | 3 | 14 |

The PC table was checked by emulating the branch code for every id 0..0xFFFF. The meaning of
0x800 and of the console ids is from the platform SDKs, not from the game's code. On PC an
override field exists (platform+0x88, 6 = none); nothing was found that writes it. `textmeta`
carries all of this as `selection`.

| Asset | Content |
|---|---|
| `Menu_uk_pc.txt` | menus, HUD, context prompts |
| `TutorialRS_uk_pc.txt`, `TutorialNO_uk_pc.txt` | tutorial texts of the two heroes |
| `Warnings_uk_pc.txt` | system messages |
| `KeyboardLayout_uk.txt`, `ControllerLayout_pc.txt` | key and button names / glyphs |
| `SubtitlesPrison_uk.txt` | all in-game speech subtitles |
| `Cutscene*_uk.txt` | cutscene subtitles, keyed by movie time |

The `.json` (`watchmen-text/1`): `asset`, `language` {slot, name, code, engine_code}, `byte_order`, `rows`,
`empty_rows`, `entries` [{`index`, `key`, `text`}] - rows with neither key nor text are left out,
`index` is the row number the game uses.

Texts contain markup the game interprets: `%N` (N decimal; reads parameter slot N as set by SetParameterFromString(N, …), slot 0 exists; one `;` after the digits is swallowed; `%%` = `%`; a slot past the end gives an empty string; `%` without digits gives `<Illegal Format Marker>`), the two characters `\n`
(line break), `#RRGGBBAA` (colour) and single characters that the icon font draws as buttons
(glyph flag 1 = icon, 0x43efbb; the character is chosen by `ProjectLib.SetTextSlotParams` 0x7fd097).

## Subtitles

A playing sound finds its subtitle by the **file name of its wave**, cut at the first `_uk`, then
at the first `_pc` (the cuts are case-sensitive and match anywhere in the name); the lookup
lower-cases A–Z and hashes (0x4d89d0, 0x4d24aa):
`/sounds/Speaks/TWILIGHT/BS2_TWL_Attack_RSH_05_uk.wav` -> key `BS2_TWL_Attack_RSH_05`.
The name is the SoundSlot's `sound` asset name, else its `streamingSound` name. There is no
language code and no other platform suffix in the key; X360 Part 2 (0x8298e130), X360 Part 1 (0x82949958) and PS3 Part 2
(0x266600) use the same two literals in the same order. The table is keyed by the 32-bit hash
alone. On Part 2 PC no shipped wave has a case variant of `_uk` / `_pc` or `_uk` away from the
end of its name, so none of this changes a key.

A key may carry times, `name#mm:ss:zzz->mm:ss:zzz`; no shipped in-game row does. Rows of one key
follow each other; a row without times lasts the slot's `defaultDuration` (7 s in game). The line
is on screen only while its sound plays, one sound at a time; mission speech has priority.
Key grammar details (0x4da4db): a key that starts with a digit or with `#` has no name (hash 0);
a time is exactly nine characters `mm:ss:zzz`, anything else is "no time"; when both times read
and `0 <= end < start` the end is dropped; nothing is truncated.

Only exclusive voice lines (speak category 1) have subtitles; grunts and shouts have none.

### When a line is asked for, and who owns it
*Added 2026-10-05 (lifted scripts `SoundDef`, `SubtitleHUD`; `textmeta` carries this as
`subtitles.rules`).*

- Only a `SoundDef` in state `Active` asks the HUD, and two routes lead there: **speech**
  (`command_sounddef_play_speak` 0x831bb8, the only play entry with `tSpeak = 1`; callers
  `SpeakCtrl.Active`, `AnimationEventWM.command_play_event_speak`, a debug tool) and the
  **activator** (`command_play_activator` 0x831e22; callers `TriggerActionSound.TriggerSoundPlay`,
  `SoundCtrl.command_cross_fade`). A subtitled wave started any other way never shows a line
  (true for every send the scripts resolve statically).
- Priority (`command_show_subtitle` 0x84a20c, `StateMain` 0x849343): one owner at a time, no
  queue. The owner of the previous frame keeps the claim while it keeps asking, even while its
  row index is −1 (blank text). A mission speak pre-empts a non-mission owner at once; mission
  against mission does not. A refused sound is not delayed: once the claim is free it shows from
  its own current time.
- The subtitle option is **off by default** (`SettingsState` 0x82be66); `command_set_slot`
  0x84a11c checks it on every call.
- The line clock is real frame time, a frame capped at 0.1 s (0x496294), not scaled game time.
  The clock starts when the sound is requested; a definition's start delay
  (`_nmindelay`..`_nmaxdelay`) delays the audio only, so the line leads its audio by that delay
  (`audio_start_delay_s` on a sound). Part 2: the playing leaf is known in the first frame
  (0x44a8fa inserts the voice before returning its id), so `m_tmissionspeak` is the leaf's. PS3
  Part 1 (0xb67090): `SoundDef.Active` has no leaf lookup and asks for the subtitle of the
  SoundDef that entered `Active`. Xbox 360 Part 1 (0x82b21808) does the same (read from code): 3
  locals against 6 in Part 2 (0x82ba8748, voice-slot lookup 0x82a42c60 at 0x82ba8894), no call
  between the local reservation and the request. Xbox 360 Part 1 `SubtitleHUD` (registration
  0x82af7ff0, hash and handler pairs stored as immediates): `StateMain` 0x82aeb170 equals Part 2
  0x82b6f100 (134 / 134 instructions; only addresses and one task-flag bit differ);
  `command_show_subtitle` 0x82aee1d8 equals 0x82b70030 (109 / 106; addresses and an inline
  task-counter decrement); `command_set_slot` 0x82af72a0 against 0x82b7acb8 (155 / 154) sends
  `GameStateCtrl.command_get_subtitles` through the by-hash helper 0x82917100, which tests the
  target for null itself, where Part 2 tests inline and sends by dispatch index 0x2f (read from
  code). SoundDef's native base is SoundSlot, so the
  definition is a valid argument. PC Part 1 is not established: there is no PC Part 1
  executable.
- 56 of the 1,205 subtitled Part 2 waves are reachable by no reference in the 906 fragments: 54
  are leaves of SoundDefs nothing points at, and 2 are the `SoundCtrl.testSound3` /
  `testSound4` values. `EN2_THGSpotRSH_GMP1_11` has rows in the German and Spanish tables only,
  on all platforms, so it plays without a subtitle in English, French and Italian. `textmeta`
  marks both: `routes` / `unreferenced` on a sound (which reference properties of the extract
  reach a SoundDef above the wave: `speak_group`, `trigger_action`, `other`, or `none`), and
  `languages_missing` on a line (with `shown_in`), counted in `subtitles.incomplete_lines` (21
  in Part 2, 19 in Part 1). Measured on PC: Part 2 1,037 speak group / 115 trigger action (3 of
  them also in a speak group) / 4 other / 56 none; Part 1 1,537 / 105 / 6 / 174 of 1,807.
  Whether a script starts one of the unreferenced waves by name is not established.
- Data, Part 2 PC: 25 subtitled sounds have two or more rows in some language (22 real splits on
  sounds over 7 s, 3 duplicates never shown); 28 sounds are longer than 7 s (21 mission speak),
  their line goes blank at 7 s. *(Counts from the wave B subtitle check, not
  re-measured for this pass.)*

### Cutscene subtitles
*Added 2026-10-05 (`textmeta` section `movies`).*

Which table a movie uses is **data**: each `MoviePlayerCtrl` node of the movie database fragment
(`MovieDbPart2.fragment`; Part 1 `MovieDb.fragment`) has `movie` (the `.bik`), `subtitleSlot`
(a `SubtitleSlot` node whose `textres` is the table) and `subtitleTextBox`. Movie and table
names do not match textually (`Cutscene08.bik` ↔ `Cutscene08a_uk.txt`, `Cutscene01.bik` ↔
`Cutscene1_uk.txt`): take the pairing from the reference.

Every movie frame (0x49c557) the player looks up the row of hash 0 at **movie time** and shows it.
Movie time is the Bink frame counter over the frame rate (0x435a65), not wall-clock time. The
lookup is the in-game one (0x4da273): rows in file order, a row is passed over only once its end
is behind. So a row appears at `shown_from_s = max(from_s, latest to_s of all earlier rows)` —
an earlier row wins an overlap — and `defaultDuration` (5.0 on every cutscene slot) matters only
for a row without an end time (none in the data).

| Part 2 player | `.bik` | Table | Rows | First–last (s) | Delayed rows |
|---|---|---|---|---|---|
| Cutscene08, AttractCutscene08 | `Cutscene08.bik` | `Cutscene08a_uk.txt` | 5 | 0.000–22.077 | 0 |
| Cutscene08B | `Cutscene08B.bik` | `Cutscene08b_uk.txt` | 20 | 5.275–80.651 | 1 (row 6: 25.530 → 26.528) |
| Cutscene09 | `Cutscene09.bik` | `Cutscene09_uk.txt` | 15 | 7.281–70.233 | 0 |
| Cutscene10A | `Cutscene10A.bik` | `Cutscene10a_uk.txt` | 3 | 6.455–18.131 | 0 |
| Cutscene10B | `Cutscene10B.bik` | `Cutscene10b_uk.txt` | 20 | 19.196–98.708 | 0 |
| Cutscene11 | `Cutscene11.bik` | `Cutscene11_uk.txt` | 8 | 6.450–29.382 | 0 |
| Cutscene12A | `Cutscene12A.bik` | `Cutscene12a_uk.txt` | 10 | 13.646–71.188 | 0 |
| Cutscene12B | `Cutscene12B.bik` | `Cutscene12b_uk.txt` | 13 | 17.123–65.606 | 0 |
| Credits, the three logo players and their three Attract copies | `Credits`, `WBGames_logo`, `DC_logo`, `DeadlineGames_logo` | none | – | – | – |

16 players, 9 with a table, 94 distinct rows.

| Part 1 player | `.bik` | Table | Rows | Delayed rows |
|---|---|---|---|---|
| Intro, AttractIntro | `Cutscene00.bik` | `Cutscene00_uk.txt` | 20 | 0 |
| Cutscene01 | `Cutscene01.bik` | `Cutscene1_uk.txt` | 14 | 3 |
| Cutscene02 | `Cutscene02.bik` | `Cutscene2_uk.txt` | 40 | 6 |
| Cutscene03 | `Cutscene03.bik` | `Cutscene3_uk.txt` | 30 | 2 |
| Cutscene04 | `Cutscene04.bik` | `Cutscene4_uk.txt` | 23 | 2 |
| Cutscene05 | `Cutscene05.bik` | `Cutscene5_uk.txt` | 25 | 1 |
| Cutscene06 | `Cutscene06.bik` | `Cutscene6_uk.txt` | 11 | 1 |
| Cutscene07 | `Cutscene07.bik` | `Cutscene7_uk.txt` | 20 | 0 |
| Credits and logos | – | none | – | – |

16 players, 9 with a table, 183 distinct rows. No row of either part is hidden entirely.

- Credits and the logo movies have no table (Credits has the text box but no slot).
- Movie **audio is not localized**: `isLocalized` (it would select Bink sound track 3 + language,
  0x438520) is false on every player node of both parts; only the subtitles differ by language.
- The X360 build (platform id 2) moves the movie text box's top anchor from 0.925 to 0.80 while
  an achievement toast is up (`MoviePlayerCtrl.StateActive` 0x7c2a40).
- The movie text box (`MovieSubtitles`, node `cb416c6c`) is a sibling of the in-game
  `SubtitleHUD`, not its child, and no test of the subtitle option was found on the movie path.
  Whether the option hides cutscene subtitles is **not established**.

## `textmeta` output (`watchmen-text-meta/1`)

- `languages`: the slots (`slot`, `name`, `code`, `engine_code`, `folder`, `identical_to_slot`).
- `selection`: how each platform maps the system language to a slot (`pc`, `x360`, `ps3`:
  `source`, `language_ids` {slot: [ids]}), `fallback_slot` 0, and for PC `unreachable_slots` [5].
- `assets.<path>`: `kind` (`text` / `sound_subtitles` / `timed_subtitles`), `slots` (the scene
  nodes using it), `default_duration_s`, `rows_by_language`, `strings_by_language`, `aligned_by`
  and `rows`. `rows[].text` is `{language code: string}`; a row that reads a parameter slot has
  `params`, the sorted distinct N of its `%N` in any language. Tables of equal length are aligned by
  `index`; the in-game subtitle table by `key` and occurrence `n`, with the row `index` per
  language. Cutscene rows have `from_s` / `to_s`.
- `subtitles`: `table`, `default_duration_s`, `rules` (`entry_routes`, `other_starts`, `request`,
  `priority`, `option`, `clock`), `incomplete_lines`, `routes` (counts), `sounds.<wave>`: `key`,
  `duration_s`, `definitions`, `mission_speak`, `audio_start_delay_s`, `routes`, `referrers`,
  `unreferenced` (only when true), `lines` [{`n`, `from_s`, `to_s`, `shown`, `text`, and
  `languages_missing` / `shown_in` when a language has no such row}].
- `movies` [per `MoviePlayerCtrl` node]: `ref` [fragment, node id], `name`, `movie`, `frames`,
  `fps`, `duration_s` (from the `.bik` header, only when the file is in the extract: under
  `files/`, where an archive's movies are written and where `extract` copies those of a
  loose-folder source from the sibling `data/Art/cutscenes`), `volume`,
  `localized_audio`, `continue_link` {ref, name, movie} (the player started when this one ends),
  `skip_skips_link`, `subtitle_text_box`, `subtitle_slot` {ref, name}, `table` (text asset, null
  without a slot), `default_duration_s`, `lines` [{`index`, `from_s`, `to_s`, `shown_from_s`,
  `shown`, `text`}]. A table used by a player lists it under `assets.<table>.movies`.
- `speech.<speak group>`: `name`, `characters`, `speaks.<speak id>`: `speak`, `category`,
  `voices` [{`index`, `name`, `definition`, `lines` [{`wave`, `duration_s`, `key`, `text`}]}] -
  what a character can say for each line, per voice, in every language, with the length of the
  recording. `sound_meta.json` carries the same `subtitle_key` on its speak waves.
- `layout_rules`, `parameters`, `senders`: the TextBox layout rules, the `%N` table and the
  sender tables of "TextBox layout" below, as data.
- `evidence`: per topic "read" (traced in the executable, address given) or "data".

## The same key in `sound_meta.json` and `anim_meta.json`

- `sound_meta.json`: every wave of a speak voice has `subtitle_key`, computed by the same
  function (`text_assets.subtitle_key`); the texts stay in the `textmeta` output, so `soundmeta`
  does not need `text/`. The key keeps the wave's spelling; the subtitle table is looked up
  case-insensitively (A-Z folded), so compare folded.
- `anim_meta.json` `fx.effects[*].sounds` and the SOUND / SPEAK events of `sound_meta.json` lead
  to sound definitions and from there to waves; a wave's subtitle is then
  `subtitles.sounds[wave]` here.

## Adding the text to an existing extract

    python3 watchmen.py text <game.naz or the extract's files/ folder> OUT
    python3 watchmen.py textmeta OUT OUT/text_meta.json

Only `OUT/text/` (and the one JSON) is created. An extract made by 1.3.0 has a single text
table under `extracted/Localize/` (`ControllerLayout_pc.txt`): 1.3.0 did not read the localized
block records.

## Real data (2026-10-04)

All six sets (Parts 1 and 2; PC, X360, PS3): 15 text assets each, every table of every slot
parses with 0 bytes left; Part 2 has 5,284 / 5,300 / 5,289 / 5,273 / 5,277 strings (en / fr / it
/ de / es), Part 1 4,481 / 4,510 / 4,501 / 4,487 / 4,497. Slot 5 is a byte copy of slot 0 in
all six. Part 2 PC linkage: 1,205 waves have subtitle rows; all 1,664 speak lines of category 1
have a subtitle and none of the 2,835 of category 2.

Six-set export of 2026-10-05 (measured, the six `textmeta` logs). Part 1 (PC, Xbox 360 and PS3
alike): 1,807 subtitled sounds, 4,618 of 12,972 speech waves have a subtitle, 16 movie players, 9
with a table. Part 2 (all three alike): 1,205 subtitled sounds, 1,664 of 4,499.

## TextBox layout (PC Part 2, read from code)

`text_meta.json` carries these as `layout_rules`; `text_assets.layout_wrap(text, width, adv)`
and `layout_place` reproduce the breaking and the line placement (`layout_advances(font)`
gives the advances of a `kapow-font/1` JSON). Functions: line breaker 0x440c1e, placement
0x4419bc, widths 0x43ef00 / 0x43ef4d / 0x43d390, glyph draw 0x43efbb, box size 0x4418ca,
0x4bf66d, 0x4b044a; break table 0x9eaab0.

- Break characters: space, `-`, `_`, LF, TAB, CR (codes above 0x7f never match, 0x405c72).
- `-` stays at the end of the word before it; a break may follow.
- `_` is a break opportunity: drawn as `_` when the line does not break there, as `-` when it
  does; its own width is not tested.
- TAB and CR break the word and are dropped without a space.
- LF forces a line; blank lines are kept, an empty first line is removed.
- A break character at the very end of the text is dropped.
- Fit test: `max_width >= pending_space_or_hyphen + line_width`. A word is never split; when
  the line is empty an empty line is pushed before an over-wide word, so one right after LF
  gets a blank line before it.
- Line buffer 256 units, slot string 1,024 units. A full line is handed on through a copy of
  128 units (`push 0x40; rep movsd` at 0x440d23, then 0x80 dwords in 0x4407d9); the upper half
  of the temporary is never written. `layout_wrap` does not model this copy.
- Advance = (glyph width + `horizontalSpacing`) × scale x; no kerning. With font flag bit 2
  every glyph advances by the font's `f24`.
- Horizontal alignment: 0 left, 1 right, 2 centre, 3 justify — spacing = (width − line width)
  / (units − 1) on every line; the unit count includes colour-code characters, and the draw
  multiplies the spacing by scale x again.
- Vertical alignment is stored and never read (the only users of +0x29b are getter 0x4afb58,
  setter 0x4b3a86, constructor 0x4c71bf and the draw 0x4bf791): text starts at the box top.
- Line step = (glyph height + font `v28[1]`) × scale y (0x441b9f).
- 2D scale = `textScaling` × (renderer width / 1280, renderer height / 720) (0xa06998,
  0xa06990; that renderer +0x40c / +0x410 are the screen size is inferred). Wrap width =
  sprite size x in pixels. No clipping; the engine has no auto-size.
- A code without a glyph is drawn as `@` (0x43ef1f). A glyph with flag 1 (an icon) is drawn
  white (0x9e814c) with the current alpha: box alpha × the last colour code's alpha.
- A colour code of all zeros is ignored. A colour stays in effect on the following lines: the
  box colour is written once before the line loop, each line's draw starts from the fields the
  previous line left (0x441b87) and writes base × code back (0x43efbb). So in a 2D box a code
  on a later line multiplies into the colour the previous line ended with, and within one line
  each code multiplies into that line's starting colour. In the 3D path (0x441be1 → 0x43f3ae)
  the colour also carries over, but codes multiply into the original box colour; there the
  justify count is taken over the whole text and the line step is (`v28[1]` + 1.0) × scale y.
- `Sprite.SetSize` 0x4b719e also writes `spriteSize3D` (+0x170).

**`%N` parameters** (`parameters`; `ProjectLib.SetTextSlotParams` 0x7fd097; a button slot holds
the layout-table row of device button id + 1, 0x7fdb09; table ControllerLayout for a gamepad,
KeyboardLayout for keyboard and mouse, 0x7f09b7):

| N | all devices |
|---|---|
| 2, 3, 4, 5 | PLAYER_ATTACK_2 (23), PLAYER_USE (24), PLAYER_SPECIAL_ATTACK_1 (25), PLAYER_SPECIAL_ATTACK_2 (27) |
| 7, 8, 9 | MENU_BACK (3), MENU_LEFT (5), MENU_RIGHT (6) |
| 15, 16, 17, 18 | MENU_SELECT (2), device name (0x7fdbbb), MENU_ABILITIES (7), CAMERA_LOOK_AT_WAYPOINT (18) |

| N | gamepad | keyboard and mouse |
|---|---|---|
| 0, 1, 10 | PLAYER_ATTACK_0 (21), PLAYER_ATTACK_1 (22), PLAYER_DEFEND (28) | Menu rows 187, 188, 189 |
| 6 | ControllerLayout row 18 | KeyboardLayout row 262, or CAMERA_STICK_UP (36) when keyboard-only |
| 12 | ControllerLayout row 17 | MOVEMENT_STICK_LEFT (32) |
| 11, 13, 14 | empty | MOVEMENT_STICK_UP (30), DOWN (31), RIGHT (33) |
| 19, 20, 21 | empty | keyboard-only: CAMERA_STICK_LEFT (38), DOWN (37), RIGHT (39) |
| 22, 23, 24 | empty | PLAYER_ATTACK_0 (21), PLAYER_ATTACK_1 (22), PLAYER_DEFEND (28) |

`%25` is set by `WarningWindowCtrl.SetParameterFromString` 0x8a9f77 and `%30` by
`InputCtrl.HandleRemovedGamepads` 0x7597ca (call at 0x759d5f; the only row using it is Warnings
28, "Please reconnect controller %30."; what the string holds was not traced). Keyboard-only is
`GameStateCtrl.command_get_keyboard_only`. The enum values are in
`wlib/input_code_enums.json` (`LogicalInputButtons`, `MetaInputDevices`). Measured on Part 2
PC: 125 of the 5,329 aligned rows of `text_meta.json` carry `params` (`%0` on 44, `%1` on 51,
`%3` on 34, `%15` on 8, `%25` on 3, `%30` on 1); counted per language over the five languages
that is 620 rows (`%0` / `%1` / `%3` / `%15`: 220 / 254 / 166 / 40).

**Senders** (`senders`; row indices):

- Use prompt (`PlayerHUD.SetTriggerUseType` 0x7f2a38, Menu table): use type 0..15 → rows 87,
  95, 94, 91, 90, 93, 88, 92, 96, 97, 98, 100, 202, 270, 270, 271; any other 68; type −1 sets
  no row. Rows 270 and 271 are Part 2 only. The `key` column of these rows is a category label
  (`Context_Ingame`), not a unique key.
- Pickup (0x801cc8, Menu table): Rorschach 212 / 213, Nite Owl 214 / 215, ability 216 with `%0`
  = the ability's Menu row and `%1` / `%2` = unlocked / unlockable counts (`"%i"`).
- Boss name (`BossHUD` 0x625c7b, 0x625d86–0x625f04): character type 25 → 112, 0 → 267, 1 → 268,
  35 → 269; any other type `characterlib.DebugCharName`, no table row. Rows 267–269 are Part 2
  only; that they are in the Menu table is inferred from the row texts.
- Warnings (`WarningWindowCtrl` 0x8ac18d, Warnings table; accept row, cancel row, description
  row; — = hidden): 1 (1, 2, 17); 3 (3, —, 20); 4 on platform 3 PS3 (—, —, 26), on platform 2
  X360 (1, 2, 23), no text on any other platform; 5 (3, 9, 24); 6 (3, 9, 25); 7 (5, —, 30); 9
  (3, —, 27); 10 (3, —, 33); 11 (3, 10, 34); 12 (1, 2, 39), Part 2 only; 0, 2, 8 no text.
  Names 0x7c5274–0x7c531a: 0 NO_PROFILE, 1 NO_DEVICE, 2 CHANGE_STORAGE_WITH_NO_PROFILE, 3
  CHANGED_PROFILE, 4 OUT_OF_MEMORY, 5 CORRUPT_SETTINGS_FILE, 6 CORRUPT_PROGRESS_FILE, 7
  STORAGE_DEVICE_DISCONNECTED, 8 STORAGE_DEVICE_RECONNECTED, 9 AUTOSAVE_NOTIFICATION, 10
  LOADED_DATA_NOT_CREATED_BY_USER, 11 SAVEDATA_MAY_BE_OVERWRITTEN, 12 RESTORE_DEFAULT. Platform
  ids (0x47ff8c): 0 EDITOR, 1 PC, 2 X360, 3 PS3.
- `TrialTimer` 0x84a860 counts down only while the byte at script data +0x55 is non-zero
  (60.0 at 0xa5efe8, 0.1 at 0x9e664c). `StatePlayerDead` 0x7f97f3: += [0xe14304] × 0.5, cap 0.8.

Measured on Part 2 PC: 25 rows contain `_`, none contains TAB or CR, the longest string is 355
units; `_` is 23 px wide in DaveGibbons40 and 30 px in TwCentMTCondExtra60; both game fonts
have 211 glyphs, 58 of them icons, and `@`. Part 1 PC: the Menu table has no rows 267–271 and
the Warnings table no row 39.

## Not established

- Read from code (substitution 0x4b6fb7, colour codes 0x43dd71 / 0x43d2e0): `%` + decimal digits
  reads parameter `atol(digits)` (0-based, at most 1000; set with `SetParameterFromString(index,
  string)`); one `;` directly after the digits is swallowed; `%%` is `%`; an index past the end
  gives an empty string, no digits gives `<Illegal Format Marker>`. A colour code is `#` + up to
  8 hex digits, `0-9` and upper-case `A-F` only; fewer than 8 digits are left-aligned with alpha
  FF, so `#RRGGBB` is opaque; `##` is a literal `#`; `#` followed by a non-hex character consumes
  no digits and yields opaque black. The `text` property of a TextBox (ASCII) is drawn without
  parameter substitution. Line-break characters (table 0x9eaab0): space, `-`, `_`, `\n`, `\t`,
  `\r`. The two characters backslash + `n` are replaced by U+000A in the same function
  (`cmp word [eax+esi*2], 0x6e` at 0x4b7007, `push 0xa` at 0x4b700e, appended at 0x4b70e2); a
  backslash before any other character is appended as it is (`push 0x5c` at 0x4b7015).
- `SpriteBar.command_update_chunks` 0x83f3d7 (read from code), per chunk and frame with dt =
  0xe14304: t += dt; b = t / duration; colour and alpha of the four corners and the width are
  linear in b; velocity += accel × dt, then offset += velocity × dt; angular speed += angular
  accel × dt; at the end the value snaps to the target and the sprite is deleted.
  `ScreenFadeCtrl.StateActive` 0x8128de: linear at 1 / `m_nfadeduration` per second of 0xe14300,
  visible iff the value is not 0, hidden while the global fade pause is set and the node
  acknowledges it.
- Not established: the TextBox layout code on Xbox 360 and PS3; the menu controllers. The HUD
  motion classes (`HudBar`, `ComboButtonHud`, `ComboTextShaker`,
  `SpriteWobbler`, `PlayerTutotialHUD`, `SpriteUVRotate`, `TextBoxContentSizer`,
  `MenuTutorialCtrl`, `Menu3DSprite`): their motion rules are not established; only their
  constants were confirmed from exe bytes. Whether any shipped row has a colour code before a wrap point
  was not measured; the colour carry-over is read from code only.
- Danish: the slot exists and holds English. It is reachable only on a console set to Danish
  (see the selection table); whether anything writes the PC language override is not established.
  A Direct3D capture cannot answer it (it records no process memory); it needs a write watch on
  the override field (platform object +0x88) in a debugger on the running game.
- Whether the Part 1 rule (the subtitle of the SoundDef that entered `Active`, read from code on
  Xbox 360 Part 1 0x82b21808 and PS3 Part 1 0xb67090) changes an exported `mission_speak` on
  Part 1 was not measured. PC Part 1: not established (no executable).
- Whether the subtitle option hides cutscene subtitles. *(Replaces "which movie uses which
  slot": that is data, above.)*
- A subtitle request sent by a run-time name string (none is visible in the lifted scripts).
- The Bink field order in memory behind "movie time = frame ÷ rate" (0x435a65) stays inferred.
  The file header is measured (all 12 `.bik` of each Part 2 set; the three platform copies are
  identical): `BIKi`, u32 size − 8 at +4, frames at +8, 1280 × 720, rate at +28, divisor at
  +32; rates 10,000,000 / 333,667 on eight files, 2,997 / 100 on three, 24 / 1 on one. With
  time = frame × divisor ÷ rate every subtitled movie ends after its last row:

  | Movie | Frames | Duration (s) | Rows | Last row ends (s) |
  |---|---|---|---|---|
  | Cutscene08 | 794 | 26.493 | 5 | 22.077 |
  | Cutscene08B | 2,646 | 88.288 | 20 | 80.651 |
  | Cutscene09 | 2,258 | 75.342 | 15 | 70.233 |
  | Cutscene10A | 741 | 24.725 | 3 | 18.131 |
  | Cutscene10B | 2,983 | 99.533 | 20 | 98.708 |
  | Cutscene11 | 923 | 30.797 | 8 | 29.382 |
  | Cutscene12A | 2,425 | 80.914 | 10 | 71.188 |
  | Cutscene12B | 2,281 | 76.109 | 13 | 65.606 |

  Part 1 (the 12 `.bik` are identical on PC and Xbox Live, and give the same frame counts as
  the PS3 copies; rate 29.97 on all but `DC_logo`, 24): `Cutscene00` 2,777 frames, 92.659 s,
  last row ends at 90.306 s; `Cutscene01` 1,238 / 41.308 / 38.597; `Cutscene02` 3,935 /
  131.298 / 129.859; `Cutscene03` 3,055 / 101.935 / 98.479; `Cutscene04` 2,818 / 94.027 /
  90.210; `Cutscene05` 3,837 / 128.028 / 123.843; `Cutscene06` 1,351 / 45.078 / 40.565;
  `Cutscene07` 2,554 / 85.219 / 81.367. Every subtitled Part 1 movie ends after its last row.
