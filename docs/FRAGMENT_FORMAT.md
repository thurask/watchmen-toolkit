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
- Key names and types come from `kapow_fragment_keys.pkl`. Built-in node
  properties are typed from the engine's typed registration wrappers (862
  names, e.g. `aspectRatio` number, `includeInAO` truth, `pivotSheet_Id`
  biginteger). A registration site's `typeIdx` is the declaring class, not a
  value type.

In the JSON, `schema` lists every type record, created nodes carry their
`type` in `nodes_full`, and a type record still produces a
`{"node", "created": true, "props": []}` entry.

Part 2 PC corpus (906 `.fragment` files): all 906 parse to the end of the
file; 22 unknown-key occurrences remain (580,286 before the hash fold, the
built-in types and type-record handling). The residue: 22 different values,
each directly after `key_0991b0d4 = 3`, of the form `[X][float][0][0][0]`.
`key_0991b0d4` is the one standard key without a name; its name and type are
not established.

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
under "Stream grammar". Not established: the name and type of `key_0991b0d4`;
the serialized size of `netparticipant` (one property, absent from the
corpus).]*

## Encounter content (from the decoded types + the name table)
Enemies.fragment instantiates, across 56 CharacterGroups / 164 spawn pivots:
  {dominatrice} x92, {gimp} x36, {gimp_with_gagball} x23, {twilight_lady} x14
driven by con_ENTER_PLAYER / con_ENTER_ENEMY gates -> act_DELAY -> act_FOLLOW_PIVOT (scripted run
path) -> act_PLAY_SPECIFIC_ANIMATION (scripted jump) -> act_SET_AI_STATE_*_AGGRESSIVE (combat).
Boss control: act_ACTIVATE_TwillligthLady, act_FORCE_MOVE_{twilight_lady},
act_DAMAGE_MODE_{twilight_lady}_INVULNERABLE, act_DEACTIVATE_{twilight_lady}.
Cameras.fragment: Cam_01/02/03 via PivotController(Camera), TELEPORT/FORCE_MOVE players,
SET_AI_STATE Rorshach/NiteOwl PASSIVE during cutscenes then AGGRESSIVE.
