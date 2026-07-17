# Kapow .fragment.header format (cracked)

The extractor left fragments as "passthrough" (prop_count 0). Reversed the property-bag node tree
from the binary. `decode_fragment.py` parses it.

## Node record
Each scene-graph node is a variable-length record. The fixed, reliable part is:
```
[ TypeName bytes, '\0', padded ]      e.g. "CharacterGroup(Folder)\0"  /  "TriggerActionCharacter(Node)\0"
[ u32  parentHash ]                   0xFFFFFFFF / 0xFFFFFFFE = root-ish/no-parent ; otherwise = parent node's hash
[ u32  selfHash ]                     this node's id (other nodes reference it by this)
[ u32  depth ]                        tree nesting depth  <-- reconstructs the hierarchy
[ optional name '\0' ]               e.g. "{dominatrice}", "{act_FOLLOW_PIVOT_{dominatrice}}", "Cam_01"
[ embedded typed properties ]        [u32 keyHashLo][u32 keyHashHi][u32 typeTag][value...] records,
                                      variable size (floats for pivot transforms, ids for references)
```
`TypeName` is the engine class + node kind, e.g. `CharacterDef(Node)`, `EnemyDef(Node)`,
`CharacterModelCollection(Node)`, `CharacterHeadModel(Character)`, `CharacterGroup(Folder)`,
`CharacterRoot(PivotNode)`, `TriggerCondition*`, `TriggerAction*`, `Collision{Capsule,Sphere,Box}Node`.

## What `decode_fragment.py` recovers (now)
The TypeName + parentHash/selfHash + depth -> the full **node-type hierarchy**. Run:
`python3 decode_fragment.py <file>.fragment.header [maxlines]`
Saved dumps: `tree_Enemies.txt` (825 nodes, 56 CharacterGroups / 164 CharacterRoots) and
`tree_Cameras.txt` (74 camera actions).

## The two file sections (cracked)
A `.fragment.header` is two serializations back to back:

1. **Front schema table (0 .. ~43 KB)** — pure topology. Tightly-packed records
   `[u32 depth][TypeName '\0', padded to 4][u32 parent=0xFFFFFFFF][u32 selfHash]`.
   Gives the node-TYPE tree (`decode_fragment.py`). No values here.

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
   **world translation is a float3 (x,y,z)** sitting in its span; `decode_spawns.py` finds it by a
   byte-granular sane-float-triple scan (skips the `(-5.6, *, -5.6)` default-bounds placeholder).

## Spawn map — RECOVERED (`enemy_spawns.json`)
`python3 decode_spawns.py Enemies.fragment.header enemy_spawns.json`
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
`decode_spawns.py` reads pos+quat directly off these keys (401 transform records in Enemies.fragment).

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
- `decode_spawns.py` — keyed transform decoder (works on any Bordello fragment).

## Still open (lowest value)
The exact TriggerAction->target-group id wiring (u32 hash references in the property stream resolve via
instHash, but per-key types aren't all mapped). The node names already make the wiring legible
(`act_ACTIVATE_Entrance_enemies_02`, `act_FOLLOW_PIVOT_{dominatrice}`), so this is optional.

## Encounter content (from the decoded types + the name table)
Enemies.fragment instantiates, across 56 CharacterGroups / 164 spawn pivots:
  {dominatrice} x92, {gimp} x36, {gimp_with_gagball} x23, {twilight_lady} x14
driven by con_ENTER_PLAYER / con_ENTER_ENEMY gates -> act_DELAY -> act_FOLLOW_PIVOT (scripted run
path) -> act_PLAY_SPECIFIC_ANIMATION (scripted jump) -> act_SET_AI_STATE_*_AGGRESSIVE (combat).
Boss control: act_ACTIVATE_TwillligthLady, act_FORCE_MOVE_{twilight_lady},
act_DAMAGE_MODE_{twilight_lady}_INVULNERABLE, act_DEACTIVATE_{twilight_lady}.
Cameras.fragment: Cam_01/02/03 via PivotController(Camera), TELEPORT/FORCE_MOVE players,
SET_AI_STATE Rorshach/NiteOwl PASSIVE during cutscenes then AGGRESSIVE.
