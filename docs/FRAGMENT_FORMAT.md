# Kapow .fragment format

A `.fragment` (and a `.scene`) is a property-bag node tree: a stream of type records and
instances whose properties are `[keyHash][value]` pairs. `wlib/kapow_fragment.py` parses it
losslessly: to the end of the stream, every stored value written exactly (see
[Lossless](#lossless-and-float_values)).

    watchmen fragment <file>.fragment [OUT.json]     # lossless JSON (--json-floats rounded: 6-place values)

## Stream grammar

Engine readers `FUN_005473ee` / `FUN_00545e1b`; implemented in `wlib/kapow_fragment.py`.

```
file    = [header: 17 bytes, or extended with a name when a flag bit is set] + chunks
chunk   = [u32 size <= 0x2800][payload]        payloads concatenate into ONE stream
stream  = ( type record | instance )*

type record = [FFFFFFFF][nodeId][wc][TypeName, NUL-padded to wc words]
instance    = [FFFFFFFE][nodeId] ( [keyHash][value] )*
```

- `0xFFFFFFFF` and `0xFFFFFFFE` are record markers (type record / instance), not parent ids.
  The u32 in front of a type name is the name's length in 32-bit words, not a depth.
- A property in a fragment is `[keyHash][value]`: there is no second hash word and no type
  tag; the type comes from the key. A value's size follows from its key's type (below).
- An instance is opened by `0xFFFFFFFE` only; `0xFFFFFFFF` opens a type record and is never
  followed by properties. Type records open the stream **and recur between instances**.
  Reading a later type record's word count and name bytes as property keys produces keys such
  as `key_00000006` or `key_63697461` ("atic"); the parser does not do this.
- The stream may open with type records that carry a bare native name (`SceneNode`, `Folder`);
  they are read like any other type record, so those nodes have a `type` (111 of the 907 Part 2
  files gain typed nodes; instance records and properties are identical in all 907, in the same
  order).
- `TypeName` is `Class(Native)` for a script class (`CharacterRoot(PivotNode)`) or a bare
  native class (`Folder`, `Model`, `Sprite`, …). Examples: `CharacterDef(Node)`,
  `EnemyDef(Node)`, `CharacterModelCollection(Node)`, `CharacterHeadModel(Character)`,
  `CharacterGroup(Folder)`, `CharacterRoot(PivotNode)`, `TriggerCondition*`, `TriggerAction*`,
  `Collision{Capsule,Sphere,Box}Node`, `TriggerActionCharacter(Node)`.
- A 17-byte file is a header with no chunk: an empty fragment, not a failure (9 of the 906
  Part 2 files).
- **A `.scene` file is a fragment** whose first node is the `SceneNode`; `to_json` /
  `load_fragment` accept it.
- Byte order: `detect_order` takes the order whose chunk walk ends on the last byte; when both
  do (one 393-byte console fragment, `SE_Countered_victim02`), the one whose payload holds a
  schema record.

### Header

Engine `Fragment::LoadHeader` 0x54306d: `u32 version` (4 in every shipped file), `u8 singleton`,
`u8 smartSelectable`, `u32 nameLen` (NUL included), `name`, `u8 reapplyable`, `u8 typed`,
`u32 chunkCount`; 17 bytes with the empty name. `kapow_fragment.parse_header`; exported as
`header` in the fragment JSON. Part 2 PC (906 fragments + 1 scene): 129 singletons, 63 with a
name, 11 reapplyable, none typed.

### Typed streams

With the header byte `typed` set, a property is `[keyHash][typeHash][wordCount][value]`; the
engine skips the value on an unknown key, a type-hash mismatch, a property the class lacks or
one with store-flag bit 0 (0x545e1b, 0x53c5c3). No shipped fragment is typed (0 on PC, PS3 and
Xbox 360, both parts). 0x53c5c3 is the stream transcoder (byte swap and the `.debug_info` log
written by 0x5409da), not a reference fix-up. `kapow_fragment.parse` reads a typed stream with
this framing (the value of an unknown key is kept as its `wordCount` words, type `words?`); it
does not compare the type hash.

### Key hash

`keyHash = name_hash(name)`: bit-CRC32, poly 0x04C11DB7, over the name's bytes `& 0xDF`
(engine `FUN_00423ce8`; `kapow_props.name_hash`). Digits fold too, so this is not
`hash(name.upper())` and not a CRC over the upper-cased name: `m_nsupersynclocal1` is
`0xee2a40a0`.

Key names and types come from `kapow_fragment_keys.pkl`. Built-in node properties are typed
from the engine's typed registration wrappers (862 names, e.g. `aspectRatio` number,
`includeInAO` truth, `pivotSheet_Id` biginteger). A registration site's `typeIdx` is the
declaring class, not a value type.

### Value sizes by type

number / integer / truth / color 4 bytes; biginteger 8; vector 12; quaternion 16; string
`[wc][wc × 4 bytes]`; `list(T)` `[count][T × count]`; entity references are tagged (`[tag]`,
tag 0 / 1 / 2 = 4 bytes, tag 3 = `[3][nodeId]`, tag 4 = `[4][a][n][n words]`, tag 5 =
`[5][n][n words]`). `netparticipant` is one slot (4 bytes, default 0xFFFFFFFF; 0x500343,
0x4f35b0); it is absent from the corpus.

Values are variable length (strings, lists, references), so the stream is not 4-byte aligned
beyond the key words.

### Entity references as the engine resolves them

Readers 0x500b81 / 0x505d84, scope search 0x53a5ff: tag 1 null; tag 2 the node the fragment
is applied to; tag 3 `[id]` a node of the same instance; tag 4 `[a][n][ids]` a path from the
scene (`a = 0`) or from the fragment host enclosing the referrer, `a - 1` hosts further up;
tag 5 `[n][ids]` where `ids[0]` is the name hash of a SINGLETON fragment (header name, or the
file's base name when the name is empty; the first registered instance wins) and the rest a
path below the node it is applied to. Each id is searched depth-first in child order without
entering nested fragments. `anim_state_machine.resolve_ref` implements this when fragment
headers are known and keeps a nearest-instance rule otherwise (JSON without headers; a tag-5
singleton outside the loaded tree; the tag-3 fallback past the own instance, which is not
established). That fallback is never used by shipped data: 0 of 69,104 (Part 2) and 0 of
96,411 (Part 1) tag-3 references name an id outside their own fragment file, on all three
platforms. All references of every Part 2 PC level (6) and Part 1 PC level (7) resolve.

Asset paths in `assetName` are matched case-insensitively (engine 0x54ba59): the scene says
`/Levels/.../tutorial.fragment`, the file is `Tutorial.fragment`.

`anim_state_machine.load_tree(hosts="all" | callable)` splices a fragment under every node
whose `assetName` names a `.fragment` / `.scene`; the default (`"groups"`: state groups only)
is all an animation class needs. What a level is built from: LEVEL_META.md.

### Which properties a fragment stores

Decided at registration: property record +0x38: bit 0 = never written; bit 1 = deprecated
alias, read but never written; bit 3 is set on 16 properties (`bit3` in
`property_store_flags.json`) and nothing in the executable reads it: the record's flags have two getters, bit 0
(0x4f93ec) and bit 1 (0x4f9420), and no instruction tests bit 3 of +0x38 (instruction scan). The 16 are owner /
sub-object links (`owner`, `ownerAsset`, `texturePtr`, `sheetVec`, `actor`, the particle lists), so an editor-side
flag is likely (inferred). It does not change what is stored. `wlib/property_store_flags.json`
lists the 61 + 56 properties that carry bit 0 / bit 1 (class, property, registration site). The
writer (Entity vfunc 7, 0x5016d8) also skips `script`, a property without a setter and
`assetName` on an entity whose native class is SceneNode.

### Standard keys of a node

The name property has the constant key `0x7282b2a2` (`[u32 0x7282b2a2][u32 wordCount][name
bytes, wordCount*4, null-padded]`, e.g. `{dominatrice}`, `{act_FOLLOW_PIVOT_{dominatrice}}`,
`Cam_01`). The standard property keys recur in every node, in order:
`9b9b2ff5 2bb48300 7829e877 f20aa272 2708acba 9227257f fd368732 53eb3733 260cadd3 3235f542 0991b0d4`.

`key_0991b0d4` is `CharacterGroup.m_ezonetrigger` (the name hashes to 0x0991b0d4; registered
as an entity reference, "Combat Zone"), an Entity: `[1]` = none (119 times), `[3][node id]` =
a node of the same fragment (22 times). Read as an integer, the id looks like an unknown key of
the form `[X][float][0][0][0]` directly after `key_0991b0d4 = 3`; read as an Entity no unknown
key remains in the 906 Part 2 fragments nor in the 758 of Part 1 (see "Part 1 keys").

### Corpus

Part 2 PC (906 `.fragment` files): all 906 parse to the end of the file with no unknown key
(580,286 unknown-key occurrences result without the hash fold, the built-in types and the
type-record handling).

In the JSON, `schema` lists every type record, created nodes carry their `type` in
`nodes_full`, and a type record produces a `{"node", "created": true, "props": []}` entry
(53,799 + 1,492 = 55,291 of them in the 906 Part 2 PC fragments). The exception: type records
in front of the first `Class(Native)` record at the head of the stream go to `schema` alone.

## Transform record

The placed-node transform is a keyed TRS without scale. Three consecutive property keys:

```
0x2f0823c4  -> position   vec3  (x, y, z)        [12 bytes]
0x51172879  -> rotation   quat  (qx, qy, qz, qw) [16 bytes]
0xd2e8577f  -> pivot/offset vec3 (always 0,0,0)  [12 bytes]   (not scale)
```

A placed node is `[0x2f0823c4][x y z][0x51172879][qx qy qz qw][0xd2e8577f][0 0 0]`. The
transform decoder reads pos and quat off these keys (401 transform records in
`Enemies.fragment`). yaw = `2*atan2(qy, qw)` in degrees.

## Example: the Bordello level fragments

### Spawn map (`enemy_spawns.json`)

`watchmen fragment Enemies.fragment enemy_spawns.json` gives **164 enemy spawns with world
positions** — equal to the 164 `CharacterRoot` pivots in the schema table, with per-type
counts matching the name table: `dominatrice 92, gimp 36, gimp_with_gagball 23,
twilight_lady 13`. Saved dumps: `tree_Enemies.txt` (825 nodes, 56 CharacterGroups / 164
CharacterRoots) and `tree_Cameras.txt` (74 camera actions).

The Y coordinate is the floor height and lays out the vertical progression of the Twilight
mansion (ground gimps -> upstairs dominatrices -> roof):

```
 Y    enemies on that floor
 4    gimp x2                                  (ground-floor gimp fight)
 8    dominatrice 11, gimp 4, gagball 6, lady 1
 9-10 dominatrice 7                            (first dominatrix wave, z -103..-109)
 16   dominatrice 14, gimp 7, gagball 4, lady 3
 21   dominatrice 7
 24   dominatrice 13, gimp 15, gagball 3, lady 4
 26   dominatrice 12, gagball 1
 30   dominatrice 4, gimp 1, gagball 2
 34   dominatrice 8, gimp 7, gagball 7, lady 1
 35-36 dominatrice 6
 40   dominatrice 2
 42   dominatrice 5, lady 1
 46   dominatrice 1, lady 2
 82   dominatrice 1, lady 1                     (off-stage holding spot 0.4,82,0.6)
```

`{twilight_lady}` appears as a positioned marker on many floors because the boss is
FORCE_MOVEd / teleported between phases (act_FORCE_MOVE / act_REQUEST_FORCED_STATE), not
because 13 bosses spawn. The `(0.4, 82.06, 0.6)` slot is a shared parked/disabled position.

Rotation: all **164/164 enemy spawns have a pure-Y quaternion** (qx≈qz≈0) — every enemy is
placed standing upright, each with its own facing yaw. `enemy_spawns.json` carries `quat` and
`yaw_deg` per spawn. Yaws cluster on cardinal/diagonal facings (0, ±90, ±180, ±45); the first
dominatrix wave at z≈-103..-109 faces inward (±96°, ±179°) toward the room.

### Cameras (`camera_transforms.json`)

`Cameras.fragment` yields 207 transform records, 89 named cameras with pos+yaw: cutscene cams
`Cam_Bordello_START[_01..03]`, `Cam_EntranceHall_START[_01/02]`, `Cam_MainHall_DoorOpen`, plus
`SetCamDir` aim markers and an `editorcamera`. These are the cinematic camera placements (the
`Camera: Cam_0N` markers apitrace records), so the cutscene camera paths are recoverable.

### Encounter content

`Enemies.fragment` instantiates, across 56 CharacterGroups / 164 spawn pivots:
`{dominatrice} x92, {gimp} x36, {gimp_with_gagball} x23, {twilight_lady} x14`, driven by
con_ENTER_PLAYER / con_ENTER_ENEMY gates -> act_DELAY -> act_FOLLOW_PIVOT (scripted run path)
-> act_PLAY_SPECIFIC_ANIMATION (scripted jump) -> act_SET_AI_STATE_*_AGGRESSIVE (combat).
Boss control: act_ACTIVATE_TwillligthLady, act_FORCE_MOVE_{twilight_lady},
act_DAMAGE_MODE_{twilight_lady}_INVULNERABLE, act_DEACTIVATE_{twilight_lady}.
`Cameras.fragment`: Cam_01/02/03 via PivotController(Camera), TELEPORT/FORCE_MOVE players,
SET_AI_STATE Rorshach/NiteOwl PASSIVE during cutscenes then AGGRESSIVE.

The TriggerAction -> target-group wiring is u32 hash references in the property stream that
resolve via the instance id; the node names make it legible (`act_ACTIVATE_Entrance_enemies_02`,
`act_FOLLOW_PIVOT_{dominatrice}`).

### Outputs

- `enemy_spawns.json`  — 164 enemy spawns: name, world pos, quat, yaw (+ all 401 transforms).
- `camera_transforms.json` — 89 cameras + 207 transforms with pos/quat/yaw.
- keyed transform decoder (works on any fragment) — `wlib/kapow_fragment.py`.

## JSON sections (`.fragment.json`)

`nodes`, `named_instances`, `instances` and `transforms` are built from the exact parse
(`kapow_fragment.sections`), not from a byte sweep of the raw file (a sweep reads integers as
text, loses strings at chunk boundaries and pairs types with the wrong id: 553 of 906 Part 2
files and 486 of 758 Part 1 files disagree with their own `nodes_full` when swept).

- `schema`, `nodes_full`: the exact parse. `nodes`: the same type records as `{type, hash}`.
  `nodes_full` has two records for a node the fragment creates: a creation record
  (`created: true`, no properties) and a property record. Count nodes by property records, not
  by `created: true` records: Part 2 has 467 `CharacterRoot` creation records and 488 property
  records (the 21 extra are overrides of nodes created in another fragment), Part 1 504 and 519;
  the 47 `visionblocker` records of Part 2 are 28 nodes.
- **Key names** are spelled as the executable registers them (`visible`, `open`, `useRealtime`,
  `locked`, `userType`, `textRes`, `minRange` …), the same spelling `.particle.json` and the
  other property-bag files use. 99 names have a lower-case-only variant that differs in letter
  case alone (`Visible`, `Open`, `UseRealTime`, `Locked`, `UserType`, `textres`, `minrange` …);
  48 of them occur in PC Part 2 fragments (285,211 keys in 897 of the 906 fragments and the
  scene file) and 49 in PC Part 1 (436,865 keys in 746 of 758). The key hash folds letter case,
  so hashes, types and values do not depend on the spelling: only the spelling of the key in the
  JSON does. None of the 99 is an entry of a script database (`Database.bin`), whose
  3,693 / 3,410 names agree; the spelling is the one of the registration string
  (`wlib/registered_names.json`). The toolkit's own readers take either spelling. Four keys
  have the type their native registration gives: `alphaThreshold` and `density` integer,
  `materialColorAlpha` number, `model` string; no fragment carries any of the four.
- `named_instances`: every `name` in file order.
- `instances`: one entry per instance name, in order of first appearance. Nodes sharing a
  name share the entry; a node without `name` adds to the entry before it; `(preamble)`
  holds the opening type table and anything before the first name.
  - `<property>`: the distinct text values of that `string` / `list(string)` property;
  - `str_<id>`: the node's type record;
  - `model_ref`, `texture_ref`, `fragment_ref`, `sound_ref`, `script_ref`, `animation_ref`,
    `asset_ref`: resource paths among list elements, by extension;
  - `_transforms`: one per `localPos`.
- `transforms`: every finite `localPos`; `quat` and `yaw_deg` when a unit `localOrient`
  follows directly.
- `instances_source`: `"exact"`, or `"sweep"` when the property stream does not parse to
  its end (then `lossless` is false and the four sections come from the byte sweep, which is
  approximate: its `pos` / `quat` stay rounded to 3 / 4 places in both float modes; 0 files in
  six sets). `unknown_keys`: `[{key, count, type_guess}]`, only when a key is in no table (0
  files). `extract` prints a `WARNING: fragment …` line for either.

### Lossless and `float_values`

`lossless: true` means two things: the property stream was parsed to its last byte, and every
stored value is in the JSON exactly. The game stores its decimals as IEEE float32; the JSON
writes each as the shortest decimal (6 to 9 significant digits) that reads back as the same
float32, bit for bit (`wlib/f32json.py`), so `1.2345e-05` stays `1.2345e-05` and `-8448.72`
is the float32 the file holds. A NaN or infinity is `null` (JSON has no such numbers); in what
`kapow_fragment.parse` and `decode_sequence.parse` return it stays the float it is, so the tables
that compute with those values do not meet a `None` (`f32json.dumps` writes the `null`). A
sequence quaternion key whose Euler angles are not all finite has `quat: null`.

`float_values` says how the file was written: `"exact"` (the default) or `"rounded"`.
`--json-floats rounded` / `WATCHMEN_JSON_FLOATS=rounded` write the values of releases before
1.5.0: `number`, `vector` and `quaternion` values rounded to 6 decimal places, the transform
`pos` to 3 and `quat` to 4 (so a value like 1.2345e-05 comes out as 1.2e-05, and `lossless`
then means "parsed to the end" only). Derived numbers are rounded in both modes: `yaw_deg` to
0.1 degree. The same rule applies to `.sequence` keys (`t`, `value`, `handles`: rounded mode
5 places; the `quat` derived from Euler angles stays rounded to 6) and to the raw float records
of a property bag (`floats`; rounded mode 6 places, `null` from 1e9 up).

Measured on the 263 fragments, 6 sequences and 1 scene of a PC Part 2 extract: 1,115,730
numbers, of which 145,391 differ between the two modes; on 140,007 of them the rounded value is
a different float32 than the stored one (most are transform `pos` / `quat`), the other 5,384
are the same float32 written with other digits; all 648,996 converted values read back as the
stored float32, and no value is NaN or infinite. The tables built from the fragments differ by
rounding only (PC Part 2 extract): `levelmeta` 21,926 of 729,488 numbers (by at most 0.001, a
derived distance rounded to 3 places), `animmeta` 157 of 312,356 and `fxmeta` 3 of 3,403 (by
at most 1e-6), `soundmeta` 1 of 81,900; `textmeta` is byte-identical; no string, key or list
changes.

A vector or quaternion guess for an unknown key is refused when a component is a marker, a
known key hash, or not an ordinary float (zero, or magnitude between 1e-6 and 1e7); the
parser then falls through to its other guesses and re-syncs on the next key.

### Part 1 keys

Seven keys occur only in Part 1 (95 properties per set) and are named in
`kapow_fragment.PART1_KEYS`:

| Key | Name | Type | Class | Count | Evidence |
|---|---|---|---|---|---|
| 57a8be19 | `_idebugrunthroughmode` | integer | WaypointController | 6 | Part 1 `database.bin` entry `_idebugrunthroughmode:integer`; also a string in the PS3 Part 1 executable and both XBLA images; caption "Runthrough Special Mode" |
| 40cb4063 | `_tdebugtmp01` | truth | WaypointController | 6 | Part 1 `database.bin` entry `_tdebugtmp01:truth`; also a string in the same executables; "Tjeck Waypoint Path" button |
| 56eec9bf | `_nsteplengthinmeters` | number | WaypointController | 6 | Part 1 `database.bin` entry `_nsteplengthinmeters:number`; caption "Step Length(m)", values 2.0 and 0.5 |
| f89f0453 | `_ntimeprstepinsec` | number | WaypointController | 6 | Part 1 `database.bin` entry `_ntimeprstepinsec:number`; caption "Step Time(m/sec)", values 0.5 and 0.01 |
| ceacaed4 | `_tuseteleport` | truth | WaypointController | 6 | Part 1 `database.bin` entry `_tuseteleport:truth`; "tUseTeleport" is a string beside `waypointcontroller_tnt.cpp`; caption "Use Teleport" |
| 0cdb31bf | `_nobstructionfactor` | number | SoundEnvironment | 50 | Part 1 `database.bin` entry `_nobstructionfactor:number`; caption "Obstruction factor", between `_nocclusionfactor` and `_tobstructor` |
| b29cf82f | `_tstartenabled` | truth | visionblocker | 21 | Part 1 `database.bin` entry `_tstartenabled:truth`; caption "Start Enabled" |

All seven names and types are entries of the Part 1 script database
(`data_baked/tnt/production/database.bin`; PC, the Xbox 360 devkit build and PS3 agree), so
no spelling is inferred. See [SCRIPT_DATABASE.md](SCRIPT_DATABASE.md). The pairing of key and
caption is by file order and was not read from the registration code.

`kapow_fragment.PART1_INFERRED` is empty, so no fragment JSON carries an `inferred_names`
list. The mechanism exists for a name added later with an exact hash but no string list or
database entry behind it; such a file would say:

```json
"inferred_names": [
 {"name": "<name>", "key": "<8 hex digits>", "count": 1,
  "confidence": "inferred", "caption": "<UI caption>"}
],
"inferred_names_note": "the spelling of these property names is inferred: ..."
```

One entry per inferred name the file uses, with the stored key, the number of properties
and the caption it was matched to (`inferred_names()`). The key, the type and the value in
`nodes_full` are as stored and the file stays `lossless`; only the name would be a guess.

Fragment JSON differences between platforms are typed values of the source: 4 Part 2 files
(Bordello `Enemies` and `Sound`, NightClub `Collision`, StreetsOfRiot `Cameras`) and 12 files
of the PS3 build of Part 1.

## Not the case

- A node record does not carry a parent hash and a depth; `0xFFFFFFFF` / `0xFFFFFFFE` are
  record markers, the hierarchy comes from the type records and the entity references.
- A property is not `[keyHashLo][keyHashHi][typeTag][value]`; the type comes from the key.
- The file is not a front "schema table" followed by a back "instance stream"; type records
  recur between instances throughout.
- A node's world translation is not found by scanning for a sane float triple; it is read from
  key `0x2f0823c4`.
