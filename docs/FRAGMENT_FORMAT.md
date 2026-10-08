# Kapow .fragment.header format (cracked)

The extractor left fragments as "passthrough" (prop_count 0). Reversed the property-bag node tree
from the binary. `wlib/kapow_fragment.py` parses it (losslessly).

> **Corrected 2026-10-02.** The record framing described in the first two
> sections below was partly wrong, and the parser built on it lost alignment
> after the opening block. The engine-verified grammar is in
> [Stream grammar](#stream-grammar-corrected-2026-10-02); statements it
> replaces are marked where they stand. The key hash is not "CRC over the
> UPPERCASE name": every byte is ANDed with 0xDF (`kapow_props.name_hash`).

## Node record
Each scene-graph node is a variable-length record. The fixed, reliable part is:
```
[ TypeName bytes, '\0', padded ]      e.g. "CharacterGroup(Folder)\0"  /  "TriggerActionCharacter(Node)\0"
[ u32  parentHash ]                   0xFFFFFFFF / 0xFFFFFFFE = root-ish/no-parent ; otherwise = parent node's hash
[ u32  selfHash ]                     this node's id (other nodes reference it by this)
[ u32  depth ]                        tree nesting depth  <-- reconstructs the hierarchy
                                      [corrected 2026-10-02: 0xFFFFFFFF / 0xFFFFFFFE are record
                                      markers (type record / instance), not parents, and the u32
                                      in front of a type name is the name's length in 32-bit
                                      words, not a depth -- see "Stream grammar"]
[ optional name '\0' ]               e.g. "{dominatrice}", "{act_FOLLOW_PIVOT_{dominatrice}}", "Cam_01"
[ embedded typed properties ]        [u32 keyHashLo][u32 keyHashHi][u32 typeTag][value...] records,
                                      variable size (floats for pivot transforms, ids for references)
                                      [corrected 2026-10-02: in a fragment a property is
                                      [u32 keyHash][value]; there is no second hash word and no
                                      type tag -- the type comes from the key]
```
`TypeName` is the engine class + node kind, e.g. `CharacterDef(Node)`, `EnemyDef(Node)`,
`CharacterModelCollection(Node)`, `CharacterHeadModel(Character)`, `CharacterGroup(Folder)`,
`CharacterRoot(PivotNode)`, `TriggerCondition*`, `TriggerAction*`, `Collision{Capsule,Sphere,Box}Node`.

## What the parser recovers
The TypeName + parentHash/selfHash + depth -> the full **node-type hierarchy**. Run:
`watchmen fragment <file>.fragment` -> lossless JSON
Saved dumps: `tree_Enemies.txt` (825 nodes, 56 CharacterGroups / 164 CharacterRoots) and
`tree_Cameras.txt` (74 camera actions).

## The two file sections (cracked)
A `.fragment.header` is two serializations back to back:

1. **Front schema table (0 .. ~43 KB)** — pure topology. Tightly-packed records
   `[u32 depth][TypeName '\0', padded to 4][u32 parent=0xFFFFFFFF][u32 selfHash]`.
   Gives the node-TYPE tree. No values here.
   *[corrected 2026-10-02: the same bytes, framed correctly, are type records
   `[FFFFFFFF][nodeId][wc][TypeName]`. "depth" is `wc`, the word count of the
   name; "parent = 0xFFFFFFFF" is the marker of the next record. Type records
   are not confined to the front: they recur between instances.]*

2. **Back instance stream (~43 KB .. EOF)** — the named nodes + their property values.
   Per node:
   ```
   [u32 parent  0xFFFFFFFE / 0xFFFFFFFF]
   [u32 instHash]                      <- matches a selfHash in the front table
   [u32 0x7282b2a2]                    <- the "name" property key (constant)
   [u32 wordCount][name bytes, wordCount*4, null-padded]   e.g. {dominatrice}
   ( [u32 keyHash][value] )*           <- typed property stream, runs to next node
   ```
   The standard property keys recur in every node (in order):
   `9b9b2ff5 2bb48300 7829e877 f20aa272 2708acba 9227257f fd368732 53eb3733 260cadd3 3235f542 0991b0d4`.
   Values are typed and **variable length** (u32 flags, strings, and float vectors), so the
   stream is NOT 4-byte aligned — a string/vector value shifts everything after it. The node's
   **world translation is a float3 (x,y,z)** sitting in its span; the transform decoder finds it by a
   byte-granular sane-float-triple scan (skips the `(-5.6, *, -5.6)` default-bounds placeholder).
   *[corrected 2026-10-02: a value's size follows from its key's type — see the
   sizes under "Stream grammar"; the position is read from its key (see
   "Transform record" below), not found by a scan. An instance is opened by
   `0xFFFFFFFE` only; `0xFFFFFFFF` opens a type record and is never followed
   by properties.]*

## Stream grammar (corrected 2026-10-02)

Engine readers `FUN_005473ee` / `FUN_00545e1b`; implemented in
`wlib/kapow_fragment.py`.

```
file    = [header: 17 bytes, or extended with a name when a flag bit is set] + chunks
chunk   = [u32 size <= 0x2800][payload]        payloads concatenate into ONE stream
stream  = ( type record | instance )*

type record = [FFFFFFFF][nodeId][wc][TypeName, NUL-padded to wc words]
instance    = [FFFFFFFE][nodeId] ( [keyHash][value] )*
```

- **Header** *[2026-10-04, engine `Fragment::LoadHeader` 0x54306d]*: `u32 version` (4 in every
  shipped file), `u8 singleton`, `u8 smartSelectable`, `u32 nameLen` (NUL included), `name`,
  `u8 reapplyable`, `u8 typed`, `u32 chunkCount`; 17 bytes with the empty name.
  `kapow_fragment.parse_header`; exported as `header` in the fragment JSON. Part 2 PC (906
  fragments + 1 scene): 129 singletons, 63 with a name, 11 reapplyable, none typed.
- Typed streams (header byte `typed`): a property is `[keyHash][typeHash][wordCount][value]`;
  the engine skips the value on an unknown key, a type-hash mismatch, a property the class
  lacks or one with store-flag bit 0 (0x545e1b, 0x53c5c3). No shipped fragment is typed (0 on
  PC, PS3 and Xbox 360, both parts). 0x53c5c3 is the stream transcoder (byte swap and the
  `.debug_info` log written by 0x5409da), not a reference fix-up. `kapow_fragment.parse` reads
  a typed stream with this framing (the value of an unknown key is kept as its `wordCount`
  words, type `words?`); it does not compare the type hash.
- **A `.scene` file is a fragment** whose first node is the `SceneNode`; `to_json` /
  `load_fragment` accept it.
- The stream may open with type records that carry a bare native name (`SceneNode`, `Folder`);
  they are read like any other type record, so those nodes have a `type` (111 of the 907 Part 2
  files gain typed nodes; instance records and properties are identical in all 907, in the same
  order).
- `TypeName` is `Class(Native)` for a script class (`CharacterRoot(PivotNode)`)
  or a bare native class (`Folder`, `Model`, `Sprite`, …).
- Type records open the stream **and recur between instances**. `0xFFFFFFFF`
  is never followed by properties. The parser used to accept only the
  parenthesised form in the opening block and read every later record's word
  count and name bytes as property keys — the source of keys such as
  `key_00000006` or `key_63697461` ("atic").
- A 17-byte file is a header with no chunk: an empty fragment, not a failure
  (9 of the 906 Part 2 files).
- `keyHash = name_hash(name)`: bit-CRC32, poly 0x04C11DB7, over the name's
  bytes `& 0xDF` (engine `FUN_00423ce8`). Digits fold too, so this is not
  `hash(name.upper())`: `m_nsupersynclocal1` is `0xee2a40a0`.
- Value sizes by type: number / integer / truth / color 4 bytes; biginteger 8;
  vector 12; quaternion 16; string `[wc][wc × 4 bytes]`; `list(T)`
  `[count][T × count]`; entity references are tagged (`[tag]`, tag 0 / 1 / 2 =
  4 bytes, tag 3 = `[3][nodeId]`, tag 4 = `[4][a][n][n words]`, tag 5 =
  `[5][n][n words]`).
- **Entity references as the engine resolves them** *[2026-10-04, readers 0x500b81 / 0x505d84,
  scope search 0x53a5ff]*: tag 1 null; tag 2 the node the fragment is applied to; tag 3 `[id]` a
  node of the same instance; tag 4 `[a][n][ids]` a path from the scene (`a = 0`) or from the
  fragment host enclosing the referrer, `a - 1` hosts further up; tag 5 `[n][ids]` where
  `ids[0]` is the name hash of a SINGLETON fragment (header name, or the file's base name when
  the name is empty; the first registered instance wins) and the rest a path below the node it
  is applied to. Each id is searched depth-first in child order without entering nested
  fragments. `anim_state_machine.resolve_ref` implements this when fragment headers are known
  and keeps the older nearest-instance rule otherwise (JSON without headers; a tag-5 singleton
  outside the loaded tree; the tag-3 fallback past the own instance, which is not established).
  It is never used by shipped data: 0 of 69,104 (Part 2) and 0 of 96,411 (Part 1) tag-3 references
  name an id outside their own fragment file, on all three platforms.
  Which registered properties a fragment stores at all is decided at registration: property
  record +0x38: bit 0 = never written; bit 1 = deprecated alias, read but never written; bit 3
  is set on 16 properties (`bit3` in `property_store_flags.json`); its meaning is not
  established. `wlib/property_store_flags.json` lists the 61 + 56 properties
  that carry bit 0 / bit 1 (class, property, registration site). The writer (Entity vfunc 7,
  0x5016d8) also skips `script`, a property without a setter and `assetName` on an entity whose
  native class is SceneNode.
  All references of every Part 2 PC level (6) and Part 1 PC level (7) resolve.
- Asset paths in `assetName` are matched case-insensitively (engine 0x54ba59): the scene says
  `/Levels/.../tutorial.fragment`, the file is `Tutorial.fragment`.
- `anim_state_machine.load_tree(hosts="all" | callable)` splices a fragment under every node
  whose `assetName` names a `.fragment` / `.scene`; the default (`"groups"`: state groups only)
  is unchanged and is all an animation class needs. What a level is built from: LEVEL_META.md.
- Key names and types come from `kapow_fragment_keys.pkl`. Built-in node
  properties are typed from the engine's typed registration wrappers (862
  names, e.g. `aspectRatio` number, `includeInAO` truth, `pivotSheet_Id`
  biginteger). A registration site's `typeIdx` is the declaring class, not a
  value type.

In the JSON, `schema` lists every type record, created nodes carry their
`type` in `nodes_full`, and a type record still produces a
`{"node", "created": true, "props": []}` entry (53,799 + 1,492 = 55,291 of
them in the 906 Part 2 PC fragments). The exception: type records in front of
the first `Class(Native)` record at the head of the stream go to `schema`
alone, as that first run of `Class(Native)` records always did.

Part 2 PC corpus (906 `.fragment` files): all 906 parse to the end of the
file; 22 unknown-key occurrences remain (580,286 before the hash fold, the
built-in types and type-record handling). The residue: 22 different values,
each directly after `key_0991b0d4 = 3`, of the form `[X][float][0][0][0]`.
`key_0991b0d4` is the one standard key without a name; its name and type are
not established. *[corrected 2026-10-04: it is `CharacterGroup.m_ezonetrigger`
(the name hashes to 0x0991b0d4; registered as an entity reference, "Combat
Zone"), an Entity: `[1]` = none (119 times), `[3][node id]` = a node of the
same fragment (22 times). Read as an integer, the id was taken for a key.
With the type corrected no unknown key remains in the 906 fragments (nor, since 2026-10-05,
in the 758 of Part 1, see "Part 1 keys" below). The "22 unknown-key
occurrences" above are those 22 references and are obsolete.]*

## Spawn map — RECOVERED (`enemy_spawns.json`)
`watchmen fragment Enemies.fragment enemy_spawns.json`
Pulled **164 enemy spawns with world positions** — which exactly equals the 164 `CharacterRoot`
pivots in the schema table, and the per-type counts match the name table:
`dominatrice 92, gimp 36, gimp_with_gagball 23, twilight_lady 13` (double cross-validation).
The Y coordinate is the **floor height**, and it lays out the whole vertical progression of the
Twilight mansion (ground gimps -> upstairs dominatrices -> roof):

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
`{twilight_lady}` appears as a positioned marker on many floors because the boss is FORCE_MOVEd /
teleported between phases (act_FORCE_MOVE / act_REQUEST_FORCED_STATE), not because 13 bosses spawn.
The `(0.4, 82.06, 0.6)` slot is a shared parked/disabled position.

## Transform record — fully cracked (keys)
The placed-node transform is a clean keyed TRS (no scale). Three consecutive property keys:
```
0x2f0823c4  -> position   vec3  (x, y, z)        [12 bytes]
0x51172879  -> rotation   quat  (qx, qy, qz, qw) [16 bytes]   <-- ROTATION
0xd2e8577f  -> pivot/offset vec3 (always 0,0,0)  [12 bytes]   (not scale)
```
So a placed node is literally `[0x2f0823c4][x y z][0x51172879][qx qy qz qw][0xd2e8577f][0 0 0]`.
the transform decoder reads pos+quat directly off these keys (401 transform records in Enemies.fragment).

### Rotation validation
All **164/164 enemy spawns have a pure-Y quaternion** (qx≈qz≈0) — every enemy is placed standing
upright, each with its own facing yaw. `enemy_spawns.json` now carries `quat` and `yaw_deg` per spawn.
Yaws cluster on cardinal/diagonal facings (0, ±90, ±180, ±45); e.g. the first dominatrix wave at
z≈-103..-109 faces inward (±96°, ±179°) toward the room. yaw = `2*atan2(qy, qw)` in degrees.

## Cameras.fragment transforms (`camera_transforms.json`)
Same decoder on Cameras.fragment yields 207 transform records, 89 named cameras with pos+yaw:
cutscene cams `Cam_Bordello_START[_01..03]`, `Cam_EntranceHall_START[_01/02]`, `Cam_MainHall_DoorOpen`,
plus `SetCamDir` aim markers and an `editorcamera`. These are the literal cinematic camera placements
(the `Camera: Cam_0N` markers apitrace recorded), so the cutscene camera paths are now recoverable.

## Outputs
- `enemy_spawns.json`  — 164 enemy spawns: name, world pos, quat, yaw (+ all 401 transforms).
- `camera_transforms.json` — 89 cameras + 207 transforms with pos/quat/yaw.
- keyed transform decoder (works on any fragment) — `wlib/kapow_fragment.py`.

## Still open (lowest value)
The exact TriggerAction->target-group id wiring (u32 hash references in the property stream resolve via
instHash, but per-key types aren't all mapped). The node names already make the wiring legible
(`act_ACTIVATE_Entrance_enemies_02`, `act_FOLLOW_PIVOT_{dominatrice}`), so this is optional.
*[2026-10-02: key typing is no longer the obstacle — see the corpus figures
under "Stream grammar". Not established: the name and type of `key_0991b0d4`
*[established 2026-10-04: `m_ezonetrigger`, Entity; see "Stream grammar"]*;
`netparticipant` is one slot (4 bytes, default 0xFFFFFFFF; 0x500343, 0x4f35b0); it is still
absent from the corpus.]*

## Encounter content (from the decoded types + the name table)
Enemies.fragment instantiates, across 56 CharacterGroups / 164 spawn pivots:
  {dominatrice} x92, {gimp} x36, {gimp_with_gagball} x23, {twilight_lady} x14
driven by con_ENTER_PLAYER / con_ENTER_ENEMY gates -> act_DELAY -> act_FOLLOW_PIVOT (scripted run
path) -> act_PLAY_SPECIFIC_ANIMATION (scripted jump) -> act_SET_AI_STATE_*_AGGRESSIVE (combat).
Boss control: act_ACTIVATE_TwillligthLady, act_FORCE_MOVE_{twilight_lady},
act_DAMAGE_MODE_{twilight_lady}_INVULNERABLE, act_DEACTIVATE_{twilight_lady}.
Cameras.fragment: Cam_01/02/03 via PivotController(Camera), TELEPORT/FORCE_MOVE players,
SET_AI_STATE Rorshach/NiteOwl PASSIVE during cutscenes then AGGRESSIVE.

## JSON sections (`.fragment.json`)

*Rewritten 2026-10-05.* Up to then `nodes`, `named_instances`, `instances` and `transforms`
came from a byte sweep of the raw file, which read integers as text, lost strings at chunk
boundaries and paired types with the wrong id (553 of 906 Part 2 files and 486 of 758 Part 1
files disagreed with their own `nodes_full`). They are now built from the exact parse
(`kapow_fragment.sections`).

- `schema`, `nodes_full`: the exact parse. `nodes`: the same type records as `{type, hash}`.
  `nodes_full` has two records for a node the fragment creates: a creation record
  (`created: true`, no properties) and a property record. Count nodes by property records, not
  by `created: true` records: Part 2 has 467 `CharacterRoot` creation records and 488 property
  records (the 21 extra are overrides of nodes created in another fragment), Part 1 504 and 519;
  the 47 `visionblocker` records of Part 2 are 28 nodes.
- **Key names** are spelled as the executable registers them (`visible`, `open`, `useRealtime`,
  `locked`, `userType`, `textRes`, `minRange` …), the same spelling `.particle.json` and the
  other property-bag files use. Up to 1.3.0 99 names differed from the registered spelling in
  letter case only (`Visible`, `Open`, `UseRealTime`, `Locked`, `UserType`, `textres`,
  `minrange` …); 48 of them occur in PC Part 2 fragments (285,211 keys in 897 of the 906
  fragments and the scene file) and 49 in PC Part 1 (436,865 keys in 746 of 758). The key hash
  folds letter case, so hashes, types and values are unchanged: only the spelling of the key in
  the JSON differs. None of the 99 is an entry of a script database (`Database.bin`), whose
  3,693 / 3,410 names already agreed; the spelling is the one of the registration string
  (`wlib/registered_names.json`). The toolkit's own readers take either spelling, so a
  `.fragment.json` written by an older version still works. Four keys also changed type to the
  one their native registration gives, `alphaThreshold` and `density` integer,
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
  its end (then `lossless` is false and the four sections are the old sweep; 0 files in six
  sets). `unknown_keys`: `[{key, count, type_guess}]`, only when a key is in no table (0
  files). `extract` prints a `WARNING: fragment …` line for either.

A vector or quaternion guess for an unknown key is refused when a component is a marker, a
known key hash, or not an ordinary float (zero, or magnitude between 1e-6 and 1e7); the
parser then falls through to its other guesses and re-syncs on the next key.

Byte order: `detect_order` takes the order whose chunk walk ends on the last byte; when
both do (one 393-byte console fragment, `SE_Countered_victim02`), the one whose payload
holds a schema record.

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
no spelling is inferred any more. See [SCRIPT_DATABASE.md](SCRIPT_DATABASE.md). The pairing
of key and caption is by file order and was not read from the registration code.

Until the database was read, five of the seven spellings were inferred and a fragment JSON
that used one carried an `inferred_names` list. `kapow_fragment.PART1_INFERRED` is empty
now, so no fragment JSON has that list. The mechanism is kept for a name that is added
later with an exact hash but no string list or database entry behind it; such a file would
then say:

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

Fragment JSON differences between platforms that remain are typed values of the source:
4 Part 2 files (Bordello `Enemies` and `Sound`, NightClub `Collision`, StreetsOfRiot
`Cameras`) and 12 files of the PS3 build of Part 1.