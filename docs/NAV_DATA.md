# Navigation data

Kynapse (Kynogon's AI middleware, namespace `Kaim`, statically linked) reads two files per level.
The game asks it for a velocity per agent; the bridge and what the script does with it are in
`re/wp4_ai.md`.

| file | where | what |
|---|---|---|
| `<Level>.aipathdata` | block-archive asset, `OUT/extracted/Levels/.../Gameplay/` | world definition: a tree of strings |
| `<level>.hpd` | plain NAZ entry, `OUT/files/data/levels/.../gameplay/` (Part 1 PC: loose in the game's `data/`) | path data: graph + AI mesh |

    watchmen extract game.naz OUT            # writes OUT/nav/ among the rest (--no-nav: not)
    watchmen navmeta FILE_OR_DIR OUT_DIR     # the same export from an extract output, a
                                             # game data folder or a single file

Both write `<Level>.nav.json` (`watchmen-nav/1`) and `<Level>.nav.glb` per level (module
`wlib/nav_data.py`). In an extract output only `files/` and `extracted/` are searched
(`nav_data.extract_trees`), and a definition is paired with the `.hpd` its database `Path` names.
`extract` needs the `.hpd` under `files/`, so with `--no-files` it only finds those an earlier
run wrote; an extract without path data gets no `nav/` folder. Part 1 on PC and Xbox Live ships
its `.hpd` loose, beside the `derived_pc` / `derived_x360` folder: `extract` of a loose folder
copies the sibling `data/**/*.hpd` and `data_baked/**/database.bin` into `files/` (7 files) and
reads them there; with `--no-files` it reads them in place. Levels left without path data are
named (`WARNING: nav: no path data (.hpd) found for …`). Part 1 `ConstructionSite` has an `.hpd`
without a path-object table (0 of 4 path objects linked).

Evidence words: **code** = read from the loader (address given), **data** = holds on all 11
shipped files (5 Part 2, 6 Part 1; byte-identical on PC, X360 and PS3), **inferred**, **unknown**.
Every shipped `.hpd` is consumed to the last byte (0 undecoded bytes in 11 of 11), and all 17
`.aipathdata` files parse with no trailing byte.

## Coordinates

Files are in Kynapse space = engine space with **x negated** (bridge 0x48110f); y up; metres.

- `<Level>.nav.json` is in ENGINE space (x already negated), the space of fragment node
  positions and of `watchmen levelmeta` (`world.pos`), in both output frames.
- `<Level>.nav.glb` is in the frame of the toolkit's model exports, so it overlays extracted
  level models placed by the level export's `gltf` transforms. In the default true frame
  (`asset.extras.watchmen.coordinate_frame = "right-handed-true"`) that is x = −engine x,
  i.e. the file's own Kynapse x; the JSON then says so in `conventions.glb_frame`, and its
  positions need x negated to lie on the GLB. With `--frame mirrored` the GLB is in engine
  space like the JSON (and like the GLBs of that frame, a mirror image).

That the middleware's space is the engine's with x negated is consistent with the engine
being left-handed and Kynapse right-handed (inferred; only the negation itself is read).

**Heights.** Mesh outlines and graph vertices lie about 1 m above the walking surface: median
1.025 m above the character placements (`CharacterRoot` pivots; Bordello and NightClub 1.025,
StreetsOfRiot 0.99) and 1.05 m above the floor of the room models measured (Bordello main
stairs; 1.015 in the master bedroom). This is how the data was generated, not an export offset. The game reports each agent to Kynapse at the world position of its physics-volume node
(0x48a6a4). For the 0.8 × 2.0 m movement capsule the controller is radius 0.425 and height 1.2,
whose centre is 1.025 m above its bottom, which equals the measured offset (read: the
controller is created at the node's world position, 0x4fe1ed, and its entity position is set to
the value the controller returns, 0x5027b5, with no offset; not established here: that this
value is the capsule centre, `NxCharacter.dll` not read). The generator is not in this build
(`CreatePathData`, `CreateLocalPathData`, `UpdateAIDefinition` all point at the stub 0x48d55e),
so the generation rule itself is unread.
Compare a placement with the mesh in x / z and an altitude window, not by height:
`nav_data.locate(hpd, point)` does that (file space, default window 3 m down / 3 m up). With it,
165 of 167 Bordello, 165 of 168 NightClub and 141 of 143 StreetsOfRiot character placements are
on the mesh; the others are 0.03 to 1.7 m outside its edge. Path-object end points are the
exception: they are the level's vertex nodes, exactly (next section).

## Path objects and the level export

A path object is a link the game can close, cost or take over (a door, a gate, a climb-up): an
`AIStaticPathObjectNode` of the level with two `AIStaticPathObjectVertexNode` children, and in
the path data an entry of the path-object table that some graph edges carry.
`watchmen levelmeta` lists the nodes in `path_objects` and joins the two **by id**, with the
position as cross-check and fallback (LEVEL_META.md).

The entry's `id` is the 1-based index into the serialised property `aiStaticPathObjectNodes` of
the level's `AIWorldNode`: a list of entity references stored in the level's `gameplay.fragment`,
written when the path data was generated. The bridge returns `list[id - 1]` (PC 0x4837d5, X360
0x829f8260; a missing entry logs "StaticPathObject with ID %d was not found"); the property is
registered in 0x484ffb with the plain list setter 0x483844, and nothing adds to the list at run
time. In Bordello the list is in the order of the nodes in the level tree; in NightClub and
StreetsOfRiot it is not (the nodes of the level's own `Collision.fragment` come last instead of
first).

Part 2 PC (2026-10-05, staged fragments of Bordello / NightClub / StreetsOfRiot): 62 + 48 + 18
path objects; 127 join by id, each within 0.16 m of its node's vertex nodes (126 within
0.00002 m; NightClub id 16, a door of `Door_HoneyPot_Right_UseTrigger.fragment`, is 0.1558 m off,
its node probably moved after generation). The one
left over is Bordello id 45 (on the PC extract Tutorial's 2 and PlayerVsPlayer's 1 join by id too:
130 by id in all): its list entry is null (the single word `01 00 00 00`, tag 1, at
offset 0x2026 of Bordello's `gameplay.fragment`; the list starts at 0x1cb6 with the property hash
`88 cd 01 5b` and the count 0x3e). The engine cannot bind that path object ("Could not match a
Kynapse static path object ... please generate new PathData"); the position rule gives it to the
path-object node of `Door_TwillightMansion_DoubleDoor_UseTriggerB.fragment` at 0.1196 m. The position join alone (end points of a path object's
edges against the vertex nodes, the next-nearest node at least 3.9 m away) gave the same 128
pairs on 2026-10-04, and 131 of 131 with Tutorial (2) and PlayerVsPlayer (1) on the full PC data.
The id join, measured on all 39 `level.json` of the six sets (2026-10-06): Part 2, identical on PC,
PS3 and Xbox 360: Bordello list 62 with entry 45 null, 61 joined by id and 1 by position (worst
distance 0.1196 m); NightClub 48 of 48 by id; StreetsOfRiot 18 of 18; Tutorial 2 of 2;
PlayerVsPlayer 1 of 1; no id / position disagreement, nothing unlinked. Part 1, identical on the
three platforms: Docks 15, Prison 24, Streets 14, Streets2 9, Underground 25, all by id.
ConstructionSite has 4 path-object nodes in the level but an empty list and 0 path objects in the
`.hpd`; Streets has 15 level nodes against a list of 14.

## `.aipathdata` — "KS BIG FILE" (code 0x48b3c0, 0x489e00, 0x488dab, 0x488e6e)

    u32  payload size            (the asset's own field; big-endian in console builds)
    char[11] "KS BIG FILE"
    u32  version = 1             (anything else is refused)
    node
    node := u32 kind
      0 group:     string label, string name, u32 child count, children
      1 raw data:  u32 size, bytes
      2 attribute: string name, string value
    string := u32 length, characters (no terminator)

Root group `Level` (OneMeter, MaxEntity, Tpf) with groups `GlobalServices`, `TimeMgt` (13 aperiodic
tasks with priority / time budget / call budget), `Entities` (7), `Brains` (NPCBrain, VehicleBrain),
`Agents` (wander, follow, flee, goto, hide), `Services` (two path finders with their modifier lists,
PointLockManager, GapManager, HierarchicalPathObjectManager with its pools, HierarchicalGraphManager
with the database and three traversals, EntityInfoManager with filters, infos and profiles).
Attribute order and duplicates are data. Per level only these differ: `MaxEntity`, the database
`Path`, slot sizes (`ConcreteSlotSize` in kB, or `RunTimeMemory` in Part 1), `MaxAIMeshSize`, and one
`MaxDist`.

### Values the engine overrides at run time (read from code)

- `FlatDataModeSearchRadius` (100.0) is replaced on the first `CharacterPathfinder` by
  `AIBrainNode.pathSearchRadius` every entity update (0x4898f6, called at 0x48afad).
- `subgoaldistance2d5/MaxDist` (1.0) is replaced on the first path finder by `subGoalMinDist`
  (0x489c1b).
- `FollowAgent` `DistFromEntity` / `AngleFromEntity` are replaced by `followDist` / `followAngle`
  every think while `agentType` is 2 (0x934630, 0x934650).
- The second `CharacterPathfinder` and second `GotoAgent` serve `IsPosReachable` only and keep the
  file values; both doubled lines are required (0x48b11e).
- 34 `AICharacter` entities are created up front (0x483894); `AIVehicle`, `VehicleBrain`,
  `VehiclePathfinder` are never instantiated (0x483a55).
- `ValidTime`, `UnsafeTime` and `Tpf` are milliseconds (0x935ab4, 0x935b11, 0x925260, 0x92a8f2).

The four overrides are listed in the JSON as `config_runtime_overrides`; the file values stay in
`config_tree`. The `AIBrainNode` defaults and what an entity sends to Kynapse are in
ENGINE_CONSTANTS.md ("AIBrainNode / Kynapse bridge").

### AI sight (read from code; counts measured)

Sight = range and cone (0x955970), then visibility. Visibility is a per-pair result held in a
time-stamped cache (0x48b785 → 0x489135, 0x48a2c1, 0x48a1b7); a stale entry is recomputed,
time-sliced, by `Kaim::CVisibilityEntityInfo` 0x943be0, which calls the engine ray cast 0x48b44e
between the two eye points (periods read from code: an entry younger than `ValidTime` 0.3 s is used;
up to `UnsafeTime` 1 s the cached value is returned; older or never computed, the game's own
query 0x48b8f3 / 0x48b891 recomputes at once. The Sight computation 0x9460a0 asks the
visibility cache without recomputing (0x946349): with a visibility entry older than 1 s it
fails, the Sight entry is not updated (0x944090) and the query returns not seen, until the
background pass 0x944530 has refreshed visibility. Without the keys the periods are 0.2 s and
1 s, 0x935710; `ImmediateMode` bypasses the cache, 0x48b785. All ten definitions store 300 /
1000 in all 33 nav files of the six sets, measured). The ray reports every shape whose
pivot-sheet `collisionMask` shares a bit with `AIWorldNode.collisionMask` (8192 `KYNAPSE` in
three and 8193 in two of the five PC Part 2 `AIWorld` nodes that store one; `nodeCollisionMask`
0). Sight is blocked when the first reported hit belongs to a `CollisionNode` with `physicsType`
1 (RIGIDBODY). Sheets that share no bit with the level's mask are transparent to AI: `Character_Enemy` (258) and `Trigger` (16) everywhere, and `SolidCollisionAiCanSeeThrough*` (4095 / 4079 / 4075) where the mask is 8192. Where the mask is 8193 (NightClub, PlayerVsPlayer) those three sheets share bit 0 and are reported: 5 NightClub volumes on `SolidCollisionAiCanSeeThrough` with `physicsType` 1 export `blocks: true` (measured); Bordello's 8 export `false`. The 28 `visionblocker` boxes of PC Part 2 all store `physicsType` 1 and
the `collisionprimitives` `default` sheet (mask 9771) and so block at run time (measured on the
906 fragments: 47 `visionblocker` records in `nodes_full`, of which 19 are creation records
without properties of nodes whose property record is in the same file; in the six level trees
they are instanced 124 times, every one `blocks: true`). `includeInAIVisibilityCache`
(`CollisionNode`+0x189) only feeds the `Get*AIObjects` natives, which no script calls. There is
no hearing: `Kaim::CEntityHearingAcuteness` is never instantiated (class object 0xe4c698 has no
reference outside its own registration).

The ray loads the node of hit record 0 once and repeats the same test for every hit
(0x48b4ee–0x48b512), so only the first reported hit decides; the hits are unsorted.

The level export applies the data side of this per collision node (`volumes[].ai_sight`,
LEVEL_META.md), with the pivot sheets of the extract (47 on PC Part 2: 26 + 12 + 9 in
`collisionprimitives`, `default`, `mockupbox`, 18 of them with the 8192 bit; the same table is
bundled as `wlib/pivot_sheets.json`).

## `.hpd` — path data (little-endian on every platform)

### Header, 0x84 bytes (code 0x90b310 reads it to manager+0x17c)

| off | type | field | evidence |
|---|---|---|---|
| 0x00 | f32 | version, 1.3 in every file. 1.0 has 0x28-byte cell entries; below 1.3 there is no path-object table (constant 0x9e60c0 = 1.3) | code 0x90b310, 0x90b660 |
| 0x04 | u32 | cell count | code |
| 0x08 | u32 | cell addressing: 1 = each cell carries a float box; 0 = integer lattice coordinates | code 0x916040, 0x90a3a0 |
| 0x0c | 3 f32 + f32 | lattice origin and lattice cell size (unused with boxes; zero) | code 0x916040 |
| 0x1c | 4 x 3 u32 | vertex extension descriptors {kind, offset, bytes}; first is (2, 0, 6) | inferred (0x90c980 looks for kind 2) + data |
| 0x4c | 4 x 3 u32 | second descriptor block, all zero | unknown |
| 0x7c | u32 | vertex record size (36) | code 0x9172c0 |
| 0x80 | u32 | edge record size (12) | code 0x9172c0 |

### Cell table at 0x84, 0x30 bytes per cell

| off | type | field | evidence |
|---|---|---|---|
| 0x00 | u32 | cell id (1000, 1001, ...) | code |
| 0x04 | 6 f32 | box: x_min, x_max, y_min, y_max, z_min, z_max = bounding box of the cell's graph vertices | code 0x916040; data |
| 0x1c | u32 | hierarchy level, 0 = concrete. No file has another | code 0x916040 |
| 0x20 | u32 | size of the cell's data | code 0x90d9c0 |
| 0x24 | u32 | offset of the cell's data from the end of the tables | code 0x90d9c0 |
| 0x28 | u32 | generation date as decimal YYMMDD (90127 = 2009-01-27) | data (120 cells of the 11 distinct shipped files) + code: the field was added after 1.0, the loader writes `0xBAFFE000` for a 1.0 file (0x90b310, 0x90b660); no reader found |
| 0x2c | u32 | generation time as decimal HHMMSScc; cc is 00 in every cell | same |

All cells of a file carry one stamp, from 2008-09-28 09:32:07 (`streets2.hpd`, Part 1) to
2009-02-05 14:09:54 (`nightclubaipath.hpd`); four of the eleven files have a single cell. The
nav document repeats it as `summary.generated` (null when the cells disagree or have no stamp).
No code that reads the two words was found, and no fragment of Bordello, NightClub or
StreetsOfRiot holds the time word, so "when the path data was generated" is the reading of the
data, not of code.

### Path-object table (version >= 1.3), after the cell table

    f32 1.0, u32 count, count x { u32 id, u16 flags, u16 pool type }

`id` is the 1-based index into the `aiStaticPathObjectNodes` list of the level's `AIWorldNode` (code
0x4837d5: the bridge looks the node up by `id - 1`; see "Path objects and the level export"); `pool type` 1 = the `AIStaticPathObject` pool of the definition
(code 0x92dfa0); `flags`: bit 0 = entry created at run time (dynamic path objects, ids from 2000);
bits 1–2 equal to 2 (value 4) = per-entity pass bits; bit 3 = starts passable (state byte 1). 8 in
every shipped entry: static, simple, starts passable; the node's `isImpassable` then decides (code
0x92d380, 0x92dfa0, 0x48a559); exported as `flags_decoded`. Entry k (1-based) is what an edge refers to.
The engine keeps a reserved entry 0 in memory, so the file's first entry is index 1 (code 0x92d280).

### Cell data (CConcreteSlot 0x9172c0)

    u32 vertex count, u32 edge count
    vertices, edges
    AI mesh blob
    u32 mesh size, u32 0          (the mesh is located from the end: 0x90c980)

Vertex, 36 bytes:

| off | type | field | evidence |
|---|---|---|---|
| 0x00 | u32 | id (bits 0..30); bit 31 = border vertex, present in other cells under the same id; cells are joined on it when they load | code 0x909ea0 |
| 0x04 | 3 f32 | position | code 0x92dfa0 |
| 0x10 | u32 | abstract (hierarchy) vertex, 0x80000000 = none; always none | code 0x909ea0 |
| 0x14 | f32 | in the FIRST record only: longest edge of the cell; else 0 | data (the slot takes it at 0x9172c0) |
| 0x18 | u32 | index + 1 of the first edge leaving the vertex, 0 = none (edges are sorted by start vertex) | data |
| 0x1c | 3 u16 | record k holds the k-th vertex index by ascending x, by y, by z (three sort orders spread over the records) | data |
| 0x22 | u16 | 0 | - |

Edge, 12 bytes (directed):

| off | type | field | evidence |
|---|---|---|---|
| 0x00 | u32 | bits 0..15 = floor(16 x length in metres); bits 16..30 = path-object index, 0 = none; bit 31 set in every file, cleared when the path object is bound | data (length); code 0x909dc0, 0x92dfa0 |
| 0x04 | u32 | start vertex index | code 0x92dfa0 |
| 0x08 | u32 | end vertex index | code 0x92dfa0 |

### AI mesh blob (CAiMesh 0x918940)

    char[12] "Kynogon Mesh", u32 version (1..5 accepted; 5 in every file)
    u32  sector word           (v5)  an equality key at run time (0x91060d, 0x9106a0); in the data, signed byte 1 = z index
                                     and signed byte 3 = x index of the 99.6 m lattice (18 of 18 PC Part 2 meshes)
    f32  cell size             20.0 (Bordello 20.1)                     code 0x91b0d0
    f32  x_min, x_max, z_min, z_max                                     code 0x91b0d0
    u32  nx, nz                6 x 6                                    code
    f32  margin                (v4+) = AIWorldNode.pitch in the data     code 0x91b0d0
    f32  unk_30                (v2+) generation value the runtime does not read (loader 0x918b13; no reader in
                                     the mesh code 0x917000–0x91d800); −0.707106 in every file
    f32  radius                (v3+) 0.4 = entityRadius                  code 0x91c1d0
    for i in nx, for j in nz:  u32 floor count, floors
    then for every floor in the same order: the link targets (3 u32 each)

A point is in grid square `i = floor((x + margin - x_min) / cell size)`, likewise j from z.

Floor:

| field | layout | meaning | evidence |
|---|---|---|---|
| alt_min, alt_max | 2 f32 | altitude range; = outline heights -1.0 / +0.6 | code 0x91c300; data |
| level links | u32 n, n x 2 points | never present | code |
| links | u32 n, n x 2 points; targets {i, j, floor} in the trailing pass | boundary segments shared with a floor of a neighbouring (or the same) square | code 0x918940, 0x91b470 |
| mesh links (v5) | u32 n, n x {2 points, u32 sector word, u32 i, u32 j, u32 floor, 3 f32} | boundary segments on the mesh edge and the floor of another mesh behind them; 0xffffffff = none. The 3 floats are a gate (below) | data (every target exists); code 0x9104d8 |
| inner walls | u32 n, n x {u32 m, m points} | blocking polylines inside the floor; not part of the outline | code 0x91b970 |
| outline | u32 n, n x {u32 m, m points} | wall segments (m is 2, rarely 1) | code 0x91b470 |
| directional | u32 n, n x {u32 m, direction, m points} | closed polygon that blocks moves with a non-negative component along `direction` | code 0x91b5f0 |

Inside test (code 0x91b470 with 0x91c300): altitude in range and odd crossing parity of
outline + links + mesh links.

**Mesh-link gate.** The three floats are a gate: a trace crosses the link only when
dir.x·dir_x + dir.z·dir_z > min_dot, with dir the normalised move direction
(0x9104d8–0x910506; default record (1, 0, 0)). A zero direction with min_dot 1 never passes.
In the JSON a mesh link carries `gate: {dir_x, min_dot, dir_z}` (`dir_x` = −f0, engine space;
`min_dot` = f1; `dir_z` = f2) and `crossable` (false for a zero direction with min_dot ≥ 1);
`summary.mesh.mesh_links_never_crossable` counts those. Measured on the five PC Part 2 files:
593 mesh links, 542 with a unit direction (444 of them within 0.5° of a 22.5° step, 98 not),
51 with a zero vector and min_dot 1.0 (never crossable). After the gate the trace still checks
progress and visited meshes before the hop (0x91050c–0x9106b5); whether path following applies
the same gate was not checked.

## `watchmen-nav/1`

`conventions`, `evidence`, `header`, `path_objects` (index, id, flags, flags_decoded, pool_type, the edges that use
it with engine positions), `cells` (id, box, `generated` = the generation stamp, `vertices`, `edges`, `sorted`, `mesh`
with every floor's outline, links, mesh links, inner walls, directional zones, area and triangle
count), `summary` (counts, `generated` = the stamp all cells share, graph components, edge-length statistics), `coverage` (regions, undecoded
regions with offset and size, fields of unknown meaning), `config` and `config_tree` (the definition),
`config_runtime_overrides` (the definition values the engine writes over at run time, next to
`config_tree`: `{definition_path, overridden_by, when, code}`; see "Values the engine overrides").
`config` and `config_tree` are the definition file, value for value: a path in them
(`databases[].Path`, `/data/Levels/.../BordelloAIPath.hpd`) is the string the file stores, while
the `.hpd` lies under `files/data/levels/...` in the archive's lower case.
`canonical_names.resolve(EXTRACT_OUT, path)` gives that file; `source.hpd` names it as written.

## `<Level>.nav.glb`

Nodes `navmesh` (triangles), `navmesh_walls`, `navmesh_links`, `navmesh_inner_walls`, `graph_edges`,
`graph_path_object_edges` (lines), `graph_vertices` (points) under `nav <Level>`. The triangles are
the toolkit's: the outline region cut into trapezoids, heights interpolated along the boundary (the
file has no height inside a floor). Adjacent meshes overlap at their edges, so summed area counts
those strips twice. The triangles face up (+Y) in both frames.

## Library

    import nav_data
    nav_data.parse_aipathdata(data); nav_data.config_summary(cfg)
    hpd = nav_data.parse_hpd(data)                 # file space (x not yet negated)
    nav_data.locate(hpd, (x, y, z))                # on which floor a FILE-space point is
    nav_data.build_document(hpd, cfg, level)       # the watchmen-nav/1 dict (engine space)
    nav_data.build_glb(hpd, level)                 # frame.mode(): true-handed unless --frame mirrored
    nav_data.find_inputs(path_or_list)             # [{level, hpd, aipathdata}]
    nav_data.extract_trees(extract_out)            # files/ + extracted/ of an extract output
    nav_data.export(src, out_dir, log)

## Not established

| item | note |
|---|---|
| Why Bordello's path-object list entry 45 is null, and what the game does at that door | a node replaced after generation is the likely cause |
| A reader of the cell stamp (0x28 / 0x2c) | none in the game; the generation tool is not available |
| Second header descriptor block; cell tail word | all zero in the files |
| Abstract (hierarchy) cells, lattice addressing, version 1.0 | read from code only, no file; abstract cells are reported as undecoded regions, never guessed |
| Why the data is 1 m above the ground | inferred: agents are reported at the centre of the movement capsule, 1.025 m above its bottom ("Heights"); read: the controller is created at the node's world position, 0x4fe1ed, and its entity position is set to the value the controller returns, 0x5027b5, with no offset; not established here: that this value is the capsule centre, `NxCharacter.dll` not read; the generator is not in this build |
| Mesh-link gate on path following | read for the trace 0x9101a0 only |
| Refresh periods of the sight visibility cache; default `physicsType` and sheet of a collision node | read: 0.3 s / 1 s (0x48a1b7, 0x935a60); constructor defaults `physicsType` 1 and the first sheet of `/pivotbooks/default.pb` (0x4a8944); a stored sheet id 0 is no sheet (0x4a4c44). The meaning of the clamp `owner+0x98 − owner+0x94` (0x935c90) is not established |
| Whether the many graph components are intended (Bordello 20, NightClub 15, StreetsOfRiot 18) | small components are separate areas reached by scripted moves; leftovers not ruled out |
| Height inside a floor | not in the file; the triangles interpolate the boundary |
