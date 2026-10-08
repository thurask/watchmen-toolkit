# Level metadata (`watchmen levelmeta`)

    watchmen levelmeta EXTRACT_OUT OUT_DIR [LEVEL ...]

writes `OUT_DIR/<level>.level.json` (format `watchmen-level-meta/1`) for every level of the
extract: a level is a `SceneScope(LoadBlock)` node of the `*.scene` file. The file is built
from the level's top fragment with every nested fragment instanced and every entity
reference resolved the way the engine does it. `evidence` in the file says per section what
is read from the executable, what is data and what is inferred.

## Conventions (`conventions`)

- Metres, +Y up. Quaternions are (x, y, z, w) as stored.
- The engine rotates with v' = conj(q) v q. World transform: `world.quat = local (x) parent`
  (Hamilton product), `world.pos = parent.pos + rotate(parent.quat, local.pos)`; the parent
  is the nearest ancestor that has a transform; `parentLink = 1` composes like any other node;
  it only keeps the node in place when its parent moves during play.
- `world` (and every other position or quaternion in the file) is in **engine coordinates**,
  which are left-handed.
- `gltf` = the node transform that places a toolkit GLB in a glTF scene, in the frame the
  GLBs are written in. No scale in either frame.
  - Default, `coordinate_frame: "right-handed-true"` (top of the file): the GLBs have
    x = −engine x, so `translation = (-world.pos.x, world.pos.y, world.pos.z)` and
    `rotation = (-x, y, z, w)` of `world.quat` (its conjugate, reflected). Place every GLB
    with its `gltf` and the level stands as the game shows it. No root scale is needed.
  - `--frame mirrored` (no `coordinate_frame` key): `translation = world.pos` unchanged,
    `rotation = conj(world.quat) = (-x, -y, -z, w)`. Self-consistent with the GLBs of that
    frame, and like them a mirror image of the game.
- `forward` and `yaw_deg` go with `gltf`: `forward` = the direction of the placed node's local
  +Z in that frame (the engine direction, with x negated in the true frame),
  `yaw_deg = atan2(forward.x, forward.z)`.
- Do not mix frames: true-frame GLBs need a true-frame level file.
- `uid` = `<fragment instance index>:<node id>`. Node ids repeat between fragment instances
  (a door template used 28 times), uids do not. `fragments[index]` is the instance.
- `stable_uid` = `<node id>@<instance id>` (graph nodes; `stable_id` on fragments). The
  instance id is the first 8 hex digits of the SHA-1 of the host chain `scene/<host id>/…`.
  It does not depend on the load order, so it matches across platforms where the node exists
  on both (PC against PS3 Part 2: every node but the 2 + 1 that exist on one side only; `uid`
  matched on 0 to 21 % per level). `stable_ids[N]` gives the instance id of instance index
  N, so any `uid` `N:<id>` maps to `<id>@stable_ids[N]`. A toolkit naming rule, not an
  engine value.
- `nav` is null and `nav_note` says why when a level has path objects but the extract holds
  no path data for it. A level finds its `.hpd` by its own name or through the
  `.aipathdata` it names (Part 1 `Streets2` → `Street2`, `Undergound` → `Underground`).
- Asset strings (`asset_names`). Every string that names a file of the export — the
  `fragment` / `asset` / `assetName` of an instance, `models`, `model`, `sequence`, the
  `texture` of a cube map, a path inside `textureSheetsDescription` — is spelled as that file
  is written: `textures/<path>/` for a `.bmp`, `models/<path>.glb` for a `.model`, else the
  file below `extracted/`, `files/data/` or `files/`. A cutscene `movie` is such a string: the
  game names a loose file of its `data` folder without that folder, so
  `/Art/cutscenes/Cutscene10A.bik` is `files/data/art/cutscenes/cutscene10a.bik` and is written
  `/art/cutscenes/cutscene10a.bik`. A graph `label` of a movie action is text, `MOVIE <path>`;
  the path after `MOVIE ` is respelled the same way and the label as stored is kept under
  `stored` of the graph node. The string the fragment stores is kept in the same
  record under `stored`, only where it differs: `"stored": {"model": "/Art/Characters/..."}`;
  for a list (`models`) the list as stored. `asset_names` = `{spelling: "export", respelled,
  note}`. With `--names stored` (or for an export made with it) the strings are the stored
  ones and there is no `stored` and no `asset_names`. The fragments themselves
  (`extracted/**.fragment.json`) always keep the stored strings;
  `canonical_names.resolve(EXTRACT_OUT, string)` finds the file one names.

## Terrain placement

`<name>.terrain.glb` (written by `extract --glb` beside the `.terrain`) is in world space (the engine
draws the vertices with the identity matrix, below): the vertices are the file's, in the frame of the toolkit's model exports. `files.terrain`
says where the level puts it, one entry per node that names a `.terrain`:

| key | content |
|---|---|
| `uid`, `stable_uid`, `class`, `name`, `fragment` | the `TerrainNode` and the fragment it is in |
| `asset`, `glb`, `coloring_asset` | the `.terrain` path, the GLB name (`asset` + `.glb`), the `.terraincoloringasset` or null |
| `local` | `localPos` / `localOrient` as stored: `{pos, quat}` |
| `world` | the node's transform composed with its parents (conventions `world`), engine numbers |
| `gltf` | `{translation, rotation}` for the GLB, in the frame of the level file (`--frame`), like every other placement; `forward`, `yaw_deg` go with it |
| `scale` | always null: the node has no scale property; the quad size is in the `.terrain` header and already in the vertices |
| `parent_link`, `enabled`, `enabled_effective`, `visible` | as on the node |
| `drawn_with`, `world_is_identity` | `"identity"`: the matrix the engine draws the terrain with (0x49c3be); whether `world` is the identity within 1e-6 (true on all 24 shipped nodes) |
| `node` | `metersPerQuad`, `quadsPerUserSector`, `widthInUserSectors`, `heightInUserSectors`, `textureTiling` (equal to the `.terrain` header) |

Use `world` / `gltf`, not `local`. Bordello's TerrainNode has `localPos` (0, −24, 76), but it
sits in `PVS/08_TWM_GreenHouse_01.fragment`, whose host node is at (0, 24, −76): composed,
the terrain is at the origin, unrotated. Checked on the PC Part 2 export: with the GLB at the
origin 61 of 129 (full level tree) placed models above the terrain's footprint rest within 0.5 m of its
surface (the others are on the floors above); shifted by (0, −24, 76) or by (0, 24, −76) none
does. StreetsOfRiot and NightClub have `localPos` (0, 0, 0) and a world transform at the
origin as well, so all three Part 2 terrains are placed with an identity transform and the
GLBs were already in the right place. All 24 TerrainNodes of the six sets compose to the world
origin, unrotated; only Bordello has a non-zero `localPos`. Placed models rest on the surface
there: a 2 m vertical shift removes the fit on all eight terrains, and a horizontal shift or
mirror removes it on Docks, Prison, StreetsOfRiot and ConstructionSite. NightClub and Streets2
are flat, so the data test is firm only for height there; their horizontal position is the
file's vertices by the rule below.
Read from code: the terrain is drawn with the constant identity matrix, not the node's
transform. 0x49c3be passes 0xc79520 (identity in the exe bytes; no instruction stores to it by
absolute address) as the world matrix to the effect: `REDeferredMain2` 0x5691b7 in the main
frame, `REDeferredTerrain` 0x5682aa in the refraction pre-pass, `RETerrain` 0x576d17 in
Simple3DRA. The ray test 0x49c4ce uses the same matrix. The Xbox 360 images do the same (Part 2
0x829d8750 with a global the static initialiser 0x8303a258 fills with the identity; Part 1
0x829a31d0 and 0x82f53eb0). The node's world translation, never its rotation, reaches only the
height and normal query (0x49f3e4 → asset +0x114 → 0x52a22f / 0x531002), whose grid is centred
on it. All 24 shipped TerrainNodes compose to the origin, so `world` / `gltf` are the identity
and equal the drawn position (`drawn_with`, `world_is_identity`); a TerrainNode moved off the
origin would be drawn unmoved while its height query moved. `files.loose` is unchanged.

## Sections

| key | content |
|---|---|
| `level` | name, scene file, scope uid, `scene_id` {value, name}, top fragment, quad-tree bounds, node count, `ai_world` (the list the path-object ids index, the two collision masks and the generation inputs, see below), `hero_models` (what the `LevelSceneCtrl` names for the two heroes, see "Hero models") |
| `files` | `stream_blocks` (every `StreamBlock` node: `asset`, `scene_start`, `loaded_by` / `unloaded_by` = the uids of the stream trigger volumes that name it; `referenced_by` = the checkpoint actions that name it through `_estreamblock` (what a checkpoint does with it is not established); see "Waypoints, stream blocks, lights"), `blocks` (the two block file names: the base name of `top_fragment`, lower-cased as the archives store them, with `.block_h_z` / `.block_s_z`), `loose` (terrain, AI path data), `terrain` (where each `.terrain` is placed, see "Terrain placement"), `terrain_rule`, `top_fragment` |
| `fragments` | every fragment instance of the level: `asset`, `header`, node count, `host` (the node it is applied to), `parent` instance, the host's `world` / `gltf` |
| `characters` | every `CharacterRoot`: `group`, `character_type`, `state_of_mind` (PASSIVE / AGGRESSIVE), `weapon_type`, `priority_model`, `priority_weapon_model`, `start_activated`, `enabled`, `world`, `gltf`, `forward`, `export` {`character`, `variants`, `rule`}, `variant` and `weapon` (what the file fixes about the model and the weapon it gets; `weapon.no_collection` = it asks for a 1H or 2H weapon its definition has no collection for, so it gets none), `ai_start` |
| `groups` | `CharacterGroup`s: `members` (uids), `all_dead` (what fires when all are dead), `zone` (the `m_ezonetrigger` reference), `zone_trigger` (the zone the engine uses, with `source`), `return_point`, `return_position` (computed as the engine does, with `return_position_source`), `return_position_stored` (the stale value in the file) |
| `character_defs` | by character type: definition fragment, `root_template` and `visual` fragments, health, faction, `playable`, `export` {`character` = folder written by `watchmen characters`, `variants`, `collection_uid`, `head_collection_uid`, `members`, `weapons`, `rule`} |
| `models` | every node with `modelNames`: model files, `role` (`prop`, or `character_model` for definition variants and player models kept in level data and for the placed `CharacterSimple` background characters), `enabled`, `visible`, `visible_effective` (own flag and the `PVSRootNode`s above), `pvs_root` (uid or null), `opacity` and `cast_shadow` (the node's renderer flags, below), `lod_override`, `lod_factor`, `include_in_reflections`, `include_in_ao`, `part_overrides` (below), `motion` on a prop that swings when hit (below), `cube_map` (the cube map the placement gets from the state of the file, below), `cube_map_by_area` (the cube per culling area, below), `world`, `gltf`, `local` (`pos`, `quat` as stored), `parent_chain_without_transform` (the script class of each ancestor between the node and its nearest ancestor with a transform, nearest first; empty when the direct parent has one) and, on the nodes it applies to, `host_offset_copy` (`{twin}`, see "Host-offset copies") |
| `path_objects` | every `AIStaticPathObjectNode` (doors, gates, climb-ups the path finder knows): class, `fragment`, `enabled`, `impassable`, `can_leave`, `can_bypass`, `path_object` (the node its `pathObject` property names), `vertices` (uid and world position of its `AIStaticPathObjectVertexNode` children), `world`, `gltf`, `ai_world_index` (its path-object id, or null), `bound_at_run_time` (below) and `nav`; the constructor default of `impassable`, `can_leave` and `can_bypass` is true (0x48c55d) |
| `nav` | the join with the level's path data, or null when the extract has none: `source` (the `.hpd`), `path_objects`, `linked`, `linked_by_id`, `linked_by_position_only`, `id_position_disagree`, `unlinked` (indices), `max_distance_m`, `tolerance_m`, the rule and the height note |
| `combat_presets` | `start` (the `CombatOrchestrator` node's values: the state at level start), `presets` (every `CombatOrchestratorParameters` node with how many switches name it), `switches` (the level's actions that switch to a preset) |
| `cube_maps` | every `CubeMapNode`: `fragment`, `texture`, `texture_size`, `enabled`, `enabled_effective`, `visible`, `visible_effective`, `candidate_at_load`, `visibility_groups`, `pvs_roots`, `world`, `gltf`; the rule is repeated in `cube_map_rule` |
| `culling` | `inside_rule`, `visibility_rule` and `boxes`: every node whose script class is `CullingBox`, with `native`, `enabled`, `width`, `height`, `depth` (null when the native class has no such property), `group` (uid of the nearest ancestor of script class `CullingGroup`, or null), `world`, `gltf`; `groups` = `[{uid, name, boxes, shows, cube_maps}]` (`shows` = the uids its `m_evisibilitygrouplist` names; `cube_maps` = the cube nodes that are candidates for a camera in the boxes of that group alone), `cube_maps_no_box` (the candidates for a camera in no box) and `visibility_groups` (uids of the `CullingVisibilityGroup` nodes) |
| `volumes` | collision boxes / spheres / capsules: `shape`, `size` (x, y, z) or radius, `world`, `conditions` under it, `used_by`, `ai_sight` (does the AI sight ray report it and does it block, see "AI sight") |
| `graph` | `nodes` (conditions, actions, use triggers, counters, groups, other trigger classes, and every node they point at as `object`; a `REQUEST_FORCED_STATE` action carries `forced_state`, see "Forced states") and `edges` |
| `checkpoints` | id, what fires it, trigger volume, `teleports` (who, where), `replay` = the restore script, depth-first |
| `cameras` | `tours` (sequences with `speed_factor`, flags, end / skip actions; `tours[*].cuts` = the `TriggerActionCamera` children of the tour's sequence node, `timed_actions` = its other action children, both by `at` (sequence position; see `sequence_action`); measured on PC Part 2: 198 `cuts` on 214 tours (42 SET_CAMERA, 156 SET_CHARACTER_CAM_DIR) and 75 `timed_actions`; PC Part 1: 128 (46, 79, 3 END_TOUR) and 113) and `camera_nodes`. `pvp_focus`: the `PlayerVsPlayerFocusPoint` node; the PvP camera sits on the line from the players' midpoint away from this node (FX_META, Gameplay cameras). |
| `auto_sequences` | the `PropertySequenceNode`s with `autoStart` true (66 of the 239 nodes stored in the Part 2 PC fragments; the six Part 2 PC level files list 291 instances, the seven of Part 1 PC 615): `uid`, `name`, `path`, `sequence`, `enabled`, `speed_factor`, `update_culling_distance`, `actions` (how many action-track children it has) — what runs without a trigger (the Rage sheet pulse among them) |
| `waypoints` | null without a `WaypointController`, else `controller`, `max_distance`, `start`, `end`, `nodes` (the start node and its next siblings: `uid`, `id`, `for_all`, `exclusive_to` / `exclusive_to_name`, `active`, `activator_stopper`, `flying`, `height_limits`, `force_next`, `force_use_trigger`, `next_all`, `next_exclusive` [type 0, type 1], `world`, `gltf`) and `activated_by` (the general actions of type ACTIVATE_WAYPOINTS) |
| `lights` | every native `Light` node: `type` / `type_name`, `color`, `brightness`, `range_m`, `attn_start`, cones, fade distances, `never_fade`, `cause_shadows`, `shadow_power`, `textured`, `texture`, `box`, `aspect_ratio`, placement, and `flicker` on a `LightFlicker` (below) |
| `scene_ctrl` | the level's `LevelSceneCtrl` nodes; `override_models` = the Character nodes their references name, keyed `nto`, `nto_flashing`, `rsh`, `rsh_rage`, `nto_head` (`_emodelnto`, `_emodelntoflashing`, `_emodelrsh`, `_emodelrshrage`, `_emodelntohead`), each `uid`, `name`, `model`, `enabled`, `textureSheetsDescription`; null for a null reference, no key when the node does not store the property (Part 1 has no `_emodelrshrage`). These are the per-level hero models (`CharacterDef.command_get_override_model` 0x666d03 → `LevelSceneCtrl` 0x76ef49, read from code); `nto_flashing` is the model whose sheets the block flash (event 84) copies. `rsh_rage` is not read by any script (hash and member scan); inferred unused |
| `movies` | the scope's cutscene movies and every movie action with its `.bik`, `localized`, `subtitle_table` (the timed text table of the movie's subtitle slot, or null; the same table name as `movies[].table` in `text_meta.json`, which has the lines and their times: TEXT_ASSETS.md "Cutscene subtitles") and `continue_link` (the movie played next, or null) |
| `game_events` | events the level data listens to and sends |
| `spawn_recipe` | fragments the game applies at run time (`reapplyable`), placed spawners |
| `unresolved` | every reference that did not resolve: node, property, raw reference. Nothing is dropped silently |
| `counts` | totals of all of the above, with `parent_link_1` (nodes with `parentLink` = 1), `placements_below_transformless_ancestor` (model records with a non-empty `parent_chain_without_transform`), `host_offset_copies`, `culling_groups`, `lights`, `lights_with_flicker`, `waypoints`, `stream_blocks`, `sequence_actions`, `tour_cuts`, `models_hidden_by_pvs_root` and `models_with_part_overrides` |

### Graph

Node: `uid`, `id`, `kind`, `class`, `native`, `name`, `enabled`, `enabled_effective`
(own flag and every ancestor's), `parent`, `fragment`, `external` (outside the load block:
game essentials), `label` (one-line reading), `params` (the node's own properties; a
reference is `{to: uid, class, name}`), `names` (enum names of integer properties).

Edge kinds:

| kind | from -> to | meaning |
|---|---|---|
| `action` | condition -> action | fired when the condition becomes true, in `order`; a `TriggerConditionTrue` that is reactivatable fires again every `m_treactivationdelay` s unless its parent has a property `m_tReactivatable` (0x86f83e) |
| `child` | action -> action | fired by the parent, in `order`; `when` = `immediate`, `delay` (+`delay` seconds, child i of a `TriggerActionDelay`), `restore` (children of a checkpoint run only on restore), `after_movie`, `after_sound` (with `sound_done: false` where no sound will send it, below), `mode` (game-mode filter), `tour_refire` (a direct action child of a camera tour is fired only by the base handler: when the tour is fired again while it runs, outside scene 30 where that re-fire ends and restarts the tour, or when the tour has no sequence child; read from code: 0x84b299, 0x84aea3, 0x84bde2; PC Part 2: 3 such edges, Part 1: 5). A `TriggerActionDelay` reads delays only for children 0..19 (`m_ndelaynumber0..19`); a child with index ≥ 20 fires immediately (0x852f1e). A child with delay exactly 0 also fires immediately, in the same call; any other value is queued and fires in a later frame once the remaining time is ≤ 0. Shipped maximum: 19 children (39 level files, six sets) |
| `aux` | action -> action | `_eauxaction`: fired after the children; how shared action trees are called |
| `input` | condition -> logical condition | child condition counted by the logical condition: ANY = at least one true; ALL = all registered inputs true; SOME = exactly `m_icount` true (0x86de58) |
| `volume` | collision condition -> volume | `default: true` when it is the parent node |
| `target`, `activator`, `move_to`, `camera`, `movie`, `look_at`, `tour_end`, `tour_skipped`, `activated`, `released`, `start`, `stream_block`, `stream_load`, `stream_unload` (on no PC level), `grapple_end`, `force_next`, `force_use` | node -> node | the named reference properties |
| `sequence_action` | sequence -> action | fired with itself as activator when the sequence's play position passes `at` (last <= at < new; rising position only; `at` equal to the duration never fires; a loop wrap skips what lay between the last position and the end) (read from code: 0x4ab230, 0x49d529, 0x4999e7). `at` is a sequence position: seconds of game time = at / speed factor. Only sequence nodes that have such children are graph nodes (kind `object`) |
| `tour_sequence` | tour -> sequence | the tour plays its first PropertySequenceNode child from 0 and ends at relative position 0.99 (read from code: 0x849e59, 0x84bed0) |
| `all_dead`, `zone`, `return_point`, `member` | group -> node | group death action, combat zone, home point, its characters |
| `ref` | node -> node | any other reference property (`property` names it) |

A node of class `TriggerActionGeneral`, `TriggerActionParticle` or `TriggerUseFragment`
also has `applies`: the sorted names of the properties its class's property filter shows for
the node's action type (for a use fragment: the use type of its `TriggerUse`, −1 without one),
from `wlib/filter_exposed.json` (read from code: 0x85e3e8, 0x86038f, 0x873568; this is the
editor's property filter).
General types 10, 11 and 12 do nothing at run time (0x85f77b: two empty handlers and no
branch; they occur in no PC level); their `label` ends "(no effect)".

A `TriggerActionSound` node has `sound_params`: `{caption: value}` of the properties its
filter shows for the action type (0x861606), a reference as the target's name:

| type | properties (caption) |
|---|---|
| 0 SOUND_PLAY | `m_etarget1` Sound slot, `m_etarget2` Attach to, `m_iinteger1` Track no., `m_nnumber4` Fade time, `m_ttruth1` Attach to activator, `m_ttruth2` Stop sounds on attach?, `m_ttruth3` Pause Speak System while playing |
| 1 SOUND_STOP | `m_etarget1` Sound slot, `m_nnumber4` Fade time |
| 2 GROUP_STOP | `m_etarget1` Group node, `m_nnumber4` Fade time |
| 3 ALL_STOP | `m_nnumber4` Fade time |
| 4 CROSS_FADE | `m_etarget1` Fade from sound, `m_etarget2` Fade to sound, `m_etarget3` Attach to, `m_iinteger1` Track no., `m_nnumber4` Fade time, `m_ttruth1` Attach to activator |
| 5 GROUP_PAUSE, 6 GROUP_UNPAUSE | `m_etarget1` Group node |
| 7 GROUP_SET_VOLUME | `m_etarget1` Group node, `m_nnumber4` Volume, `m_nnumber5` Fade time |
| 8 ACTIVATE_MUSIC_SETUP | `m_etarget1` Set music setup |
| 9 ACTIVATE_MUSIC_STATE | `m_etarget1` Music state, `m_nnumber1` Play time, `m_ttruth1` Set As Default, `m_ttruth2` Play Static |
| 10 DEACTIVATE_MUSIC | none |
| 11 ACTIVATE_MUSIC_INTENSITY | `m_etarget1` Music intensity definition |
| 12 NEXT_DEFAULT_MUSIC_STATE | `m_etarget1` Next default music state |
| 13 ADJUST_SOUND | `m_etarget1` SoundDef, `m_nnumber1` Volume, `m_nnumber2` Fade time |

- With `_tchildrenafter` set the children are held for `command_sound_done` for every action
  type (0x86150a); only a SoundDef started by SOUND_PLAY or CROSS_FADE sends it (0x82aecf).
  `sound_done: false` marks held children of other types. Measured: the flag is set on 38
  actions of PC Part 2, all SOUND_PLAY, and on PC Part 1 on 100 SOUND_PLAY and 12 SOUND_STOP
  actions (Streets); the 12 have no child node, so no edge of the 13 PC levels carries the
  mark. The Part 1 executable was not read.
- DEACTIVATE_MUSIC acts only with a non-null `m_etarget1` (0x8524bb).
- ADJUST_SOUND sends `SoundDef.command_adjust_volume` (0x852584).
- "Play Static" of ACTIVATE_MUSIC_STATE has no effect (0x7d1113).

**Use triggers.** Read from code: who may activate is `_iactivatortype` (0x862e84). Pressing
use has no distance or facing test on the trigger (0x87d044): the collision volume is the
range. Use is refused in combat unless `m_tallowincombat`; with `m_tspecialcombathandling` it
is refused only while an enemy is within 2.0 m of the character's height (0x695030). The
trigger's own `_eactivatedaction` fires first, then the fragment's `m_eactivatedaction`
(0x880105). Types 5, 9, 10, 8, 13, 14 and 1 run their own state; type 0 starts the lock-pick
minigame; every other type fires at once. The `label` of a `TriggerUse` is
"USE <use type> by <activator>", a `TriggerUseFragment` takes it from its `TriggerUse`, and a
`TriggerConditionVisibility` reads "LOOK+USE <character> within <n> m".

Enemies are not spawned: a placed `CharacterRoot` is activated (ACTIVATE on it or its group)
and built when near. A group's `all_dead` normally points at a `TriggerConditionToggle`,
which is the input of a logical condition.

Children with equal `siblingOrder` keep file order (`counts.action_order_ties`). The engine's
sibling insert (0x48f556) puts a node behind every sibling whose order is not larger than its own,
so ties keep the order of insertion (read from code); this order is the file order: the loader
attaches nodes as it reads them (0x545e1b, read from code) and every parent record precedes its
children (measured, all PC fragments).

### Which model and weapon a placement gets (`variant`, `weapon`)

The model is not stored on the placement and it is not random. A definition's model collection
(`character_defs[type].export.members`, the collection's children in sibling order, unnamed ones
included) keeps one live count per member. When a character is built
(`CharacterModelCollection.command_get_model`, 0x66ca15; member list 0x66cd2a):

1. A non-zero request (`priority_model` of the placement) selects the **last** member whose own
   `priority_model` equals it. A request of 0 is "no request": a member's priority 0 cannot be asked
   for.
2. Otherwise the member with the lowest live count is taken, the first in member order on a tie.
3. The chosen member's count goes up. It goes down again when the character's visual is deleted
   (0x67909b: on delete, and on deactivation of a dead character).

So for most enemies the outcome depends on the **history of the play session** (who was built and
deleted before), not on the level file alone. The file fixes only this, which is what the export
states:

| `variant.status` | meaning | `members` |
|---|---|---|
| `fixed` | one member, or a request that a member matches (`rule`: `single_member` / `priority_last_match`) | the one member index |
| `candidates` | any member can come up; `rule` = `least_used_first` | every member index |
| `fixed_scene_model` | the definition has no collection (the two heroes): the level's `LevelSceneCtrl` names the model (0x76ef49). Which node that is, is not resolved | empty |
| `none` | no collection for another type, or an empty collection | empty |
| `unknown` | no definition of that character type in the loaded data | empty |

`requested_priority` is the placement's value, `priority_matched` whether a member has it. The
member also decides the head: `head_model_type` selects the first head of that type in the
collection's head collection (`head_collection_uid`; 0x66cbdd).

`weapon` has the same shape for the weapon (`CharacterRoot.command_set_weapon`, 0x694378):
`weapon_type` 0 picks from `export.weapons.bash_1h`, 1 from `bash_2h`, with
`priority_weapon_model` as the request; `status` is `none` for weapon type -1 and for a definition
without that collection. `collection_uid` matters: weapon collections are single nodes shared
by several definitions (`HeaviesWeapons_1H` by three), so "least used" counts across them.

`counts`: `characters_variant_fixed` (fixed + fixed_scene_model), `characters_variant_candidates`,
`weapons_fixed`, `weapons_candidates`, `weapons_none`. Part 2 PC, Bordello / NightClub /
StreetsOfRiot as staged (2026-10-05): variant fixed 16 / 2 / 0, candidates 151 / 168 / 143; weapons
fixed 33 / 41 / 39, candidates 11 / 5 / 18. The full PC extract (all six levels, 488 placements):
variant fixed 26 (12 of them `fixed_scene_model`), candidates 462; weapons fixed 113, candidates
34, none 341. In shipped Part 2 data every body member has priority
0, so no placement's request can match: the 15 NightClub Heavies that ask for 1 are `candidates`.

Around the picker (read from code): an activated enemy registers with the LOD controller, which
admits one waiting character per frame in the order of registration and gives the 16 nearest to a
player the built state (0x66bb68); the rest wait unbuilt. The event `DO_BLOCK_FLASH` asks the
picker again without giving the count back, but only Nite Owl's clips fire it and he has no
collection. `command_set_weapon` asks the 1H collection a second time for character type 0x23
(TWILIGHT_LADY), whose definition has no weapon collection: inert in shipped data.

### AI start state (`ai_start`)

`ai_start.state_of_mind` is `PASSIVE`, `AGGRESSIVE` or `unset` (no value on the placement; what such
a character starts as is not established). A PASSIVE enemy does **not** chase or attack
(`Enemy.Evaluate` 0x72587d, branch at 0x726214): it returns to its combat zone when outside it and
idles otherwise. It turns AGGRESSIVE when it reacts to an attack, takes damage, is the target of
an attack, or when a `SET_AI_STATE` action lists it. `ai_start.set_ai_state` holds those actions:
`{uid, name, to: {value, name}, enabled}`. An action lists the characters under its `m_etarget1`:
that node when it is a `CharacterRoot`, else every `CharacterRoot` below it (0x855ecb, 0x59d5db).
The class is matched exactly: `TriggerActionCharacterForceMove` has its own action enum (1 =
FORCE_MOVE). `counts`: `characters_passive`, `characters_aggressive`, `set_ai_state_actions`.

### Combat presets (`combat_presets`)

`start` = the values of the game's `CombatOrchestrator` node (engagement distance, running
characters clamp, attack cooldown, maximum simultaneous attacks, attack frequency, idle time): what
is in force until the level switches. `switches` = each `TriggerActionGeneral` TRIG whose target is
a `CombatOrchestratorParameters` node, with that preset's values (0x851fba -> 0x6d9128 ->
`command_set_parameters`). `presets` lists all preset nodes; one with `on_initialize` applies
itself at start (0x6d910d; none does in Part 2). Part 2 switches to Level 001 and 002 in
NightClub, 002 to 004 in StreetsOfRiot and 004 to 006 in Bordello: maximum attacks 2 to 4, attack
cooldown 4.0 to 2.0 s, idle time 1.5 to 0.1 s.

### Groups

`zone_trigger` is the zone the engine uses: the `m_ezonetrigger` reference, else the group's
first child with physics type 2 (0x668a0e); `source` says which. Home-turf behaviour exists only
for groups that have one. `return_position` is computed as the engine does at start (0x668a99):
the position of the return point, else of the first member, plus 0.5 in y;
`return_position_source` = `return_point` / `first_member`, or `stored` for a group without members
(the engine leaves the stored vector alone then). The vector in the file
(`return_position_stored`) is overwritten at run time and is stale in the shipped levels (all
zero in Bordello and NightClub, 1.6 to 98 m from the computed position in StreetsOfRiot).

### Cube maps

A reflective surface samples the cube map of the **nearest candidate** `CubeMapNode` (squared
distance from the node to the drawn object's world translation; 0x4d1299, 0x56bd5f), or none when
there is no candidate. Read from code: the candidate list is rebuilt every frame (0x4d5ca9, called
from `MasterRA` 0x561521) from all cube nodes; a node is a candidate when `Node::IsEnabled`
(0x481762: its own `enabled` byte +0x54 and bit 0 of +0x40, the property `globalEnabled`) holds
and `visible` (+0x55) is set on the node and on every `PVSRootNode` above it (0x48e028; the
handle at +0x3c is set to the nearest `PVSRootNode` ancestor by 0x492b67). Read from code: bit 0
of +0x40 is the enabled state of all ancestors (0x48e51d). An invisible `Folder`, `Group` or
fragment host does not hide its children.

Read from code: the visible flag of a `CullingVisibilityGroup` (native `PVSRootNode`) is set
every frame by `CullingCtrl` (0x70e0a4 → 0x7054b8 → `Node::SetVisible` 0x48f69a): shown when a
`CullingGroup` with a box containing the camera lists it, hidden otherwise; with the camera in
boxes of several groups the lists are united. So a cube node below a hidden group is no
candidate. `StateMain` 0x705138 sends `command_viewport_render_begin` once per frame for the
single-player camera (viewport 0 in game modes 1 and 4, viewport 1 in mode 2, not in mode 3;
0x704d7f). Not established: any other switch of the flags at run time.

Measured on three D3D9 captures (Bordello, NightClub), counting the draws whose pixel shader
samples a cube (`dcl_cube s3`): the nearest candidate under that rule is the bound cube in 4,041
of 4,041 draws of 87 frames (file state alone: 3,254 of 4,041) and in 659 of 659 draws of 18
other frames (nearest of **all** cube nodes of the level file: 586 of 659 — Bordello 328 of 328,
NightClub 258 of 331). In the seven frames with the camera in two groups only the union of their
lists fits (312 of 312; intersection 250). A shader without the cube sampler leaves stage 3 as
the last draw set it, so a draw of such a shader is not counted.

Measured on the level files (PC Part 2), per model placement:

| Level | Models | Under a group: single / multiple / single differing from `cube_map` | Under no group: single / multiple |
|---|---|---|---|
| Bordello | 3,043 | 2,135 / 613 / 311 | 22 / 273 |
| NightClub | 3,737 | 2,831 / 695 / 403 | 15 / 196 |
| StreetsOfRiot | 3,564 | 2,551 / 479 / 22 | 8 / 526 |

"Single" = one cube whatever culling group the camera is in; "multiple" = the cube changes with
the area. A placement under no visibility group also changes cube with the area (Bordello 273
of 295). Bordello has 26 `CullingVisibilityGroup` nodes (all native `PVSRootNode`) with 71 of
its 75 cube nodes under one; NightClub 32 with 49 of 53; StreetsOfRiot 14 groups plus 6 plain
`PVSRootNode`s with 18 of 19. Tutorial, PlayerVsPlayer, MainMenu and the seven Part 1 levels
have no such group, no `PVSRootNode` and no culling box.

The export gives the state of the file and the answer per culling area:

- `cube_maps[].visible`, `visible_effective` (the node and every `PVSRootNode` above it) and `candidate_at_load`
  (= `enabled_effective` and `visible_effective`);
- `cube_maps[].visibility_groups` = the uids of the `CullingVisibilityGroup` nodes among the
  `PVSRootNode`s above the node, nearest first (`[]` when none); `pvs_roots` = the uids of all
  `PVSRootNode`s above it, nearest first;
- `culling.groups[].cube_maps` = the cube nodes that are candidates for a camera in the boxes of
  that group alone: `enabled_effective`, the node's own `visible`, every plain `PVSRootNode`
  above stored visible, and every `CullingVisibilityGroup` above in that group's `shows`;
  `culling.cube_maps_no_box` = the same test with an empty `shows` (a camera in no box);
- `models[].cube_map` = `{uid, texture, distance, same_fragment}` of the nearest
  `candidate_at_load` node to the placement's world position, or null when the level has none
  (the FILE state). `same_fragment` says whether that node is in the placement's own fragment.
  A moving object changes its cube as it moves;
- `models[].cube_map_by_area` = `[{cube: {uid, texture, distance} or null, groups: [culling
  group uids]}]`, one row per distinct answer. The groups asked are the culling groups whose
  `shows` holds every `CullingVisibilityGroup` above the placement (all culling groups when it
  has none); the answer of a group is the nearest of its `cube_maps`. `[]` when no group shows
  the placement (and on a level without culling groups);
- `counts.models_cube_by_area_single`, `models_cube_by_area_multiple` (one row, several rows)
  and `models_cube_by_area_single_differs_from_file_rule` (one row whose cube is not
  `cube_map`).

In the six PC Part 2 levels every cube node is a candidate at load (152 of 152; Bordello 75,
NightClub 53). All 10,656 model placements get a `cube_map`; for 3,344 of them it is a node of
their own fragment (measured).

### Renderer flags of a model node (`opacity`, `cast_shadow`)

`models[].cast_shadow` is the node's `castShadow`, the flag the stencil shadow pass tests
(0x4995c6, 0x5748e2); the mesh also needs a shadow hull in its model (`not_exported.shadow_hull`
in the model's `.model.json`). The sheet's own `castShadow` is not read in stencil mode.
`models[].opacity` is `BaseModel.opacity` (clamped 0..1 by the engine): it multiplies the sheet
opacity, and a render-type 0 or 10 part whose product is below 0.99 is drawn blended (0x5739d0).
It is exported here and not multiplied into the model files. Measured on the six PC Part 2
levels: 853 of 10,656 model nodes store an opacity below 1 (Bordello 139, NightClub 661, values
0.28 to 0.95) and 53 have `cast_shadow` false.

`visible_effective` is the node's own flag and that of the `PVSRootNode`s above it (0x48e028),
`pvs_root` the nearest one. StreetsOfRiot stores six `PVSRootNode`s invisible
(`PVSNoCombatSimpleEnemies_*`); their 36 `CharacterSimple` placements have `visible` true and
`visible_effective` false. Whether a script switches those roots on during play is not
established; no Part 1 level has a `PVSRootNode`.

`lod_override` (−1 = none) is the LOD the renderer draws regardless of distance, and
`lod_factor` multiplies the distance used for LOD selection (0x49d00f, 0x53a317; defaults −1
and 1.0 from the constructor 0x4a8f99). `include_in_reflections` (default false) and
`include_in_ao` (default true) are the node flags at +0x12a and +0x129. Measured: StreetsOfRiot
has 51 model nodes forced to LOD 1 and 7 to LOD 0; the importer places LOD 0 for all of them.
What the renderer does with an override above the model's highest LOD is not established.

A `SubPivot` below a `Model` is one part of its ModelRes (`pivotID` = part index). At load the
engine re-creates them by name, overwrites the transform with the part's rest pose unless
`locked` is set (0x4a5907), and draws a part only when its SubPivot is enabled and visible
(0x49faaf). Measured: every unlocked SubPivot stores the rest pose (2,785 of 2,785 in PC Part
2). The only locked one is part 1 `interact` of `SwitchInteractive.model` (10 placements in
Part 2, 17 in Part 1), stored with quaternion (−0.5, −0.5, −0.5, 0.5) where the model has
(0.5, 0.5, −0.5, 0.5). One Bordello model has two disabled SubPivots (`Door_Left01`,
`Door_Right01`), so 11 Part 2 models carry `part_overrides` (measured, PC). `part_overrides`
lists, per model node, the SubPivots (reached through SubPivot nodes only) that are locked,
disabled or invisible: `{part, name, local, locked, enabled, visible}`. The exported GLB keeps the rest pose; the importer does not apply the list.

`motion` is on a model node whose script class is `TriggerOscillateBox` or
`TriggerFireBarrelEffect` (hanging lamps, signs, barrels): `{kind: "hit_swing", rest,
amplitude, frequency_hz, falloff, amplitude_z, frequency_z_hz, falloff_z, quarantine_s,
formula, evidence}` (the `_z` keys null for the barrel). Read from code (0x874b7a, 0x871b96,
0x8718e6; 0x874795, 0x87113c): angle_k = −impact_k · amplitude_k · 2^(−falloff_k·t) ·
sin(2π·frequency_k·t); the impact is min(1, |contact force| / 10000) times the horizontal
direction from the hitting character projected on the node's X and Z axes; the box turns
about local Z, then local X, from its stored orientation while either term is ≥ 0.001.
Measured: 5 OscillateBox and 6 FireBarrel nodes in PC Part 2, 18 and 15 in PC Part 1.

### Culling boxes (`culling`)

Read from code: `CullingCtrl.InsideTest` (0x7111b9) takes a point as inside iff
`abs(local) * 2 <= (width, height, depth)`; the depth comes from MockupBox+0x1a0,
CollisionBoxNode *(+0x198)+0x2c or Light+0x174, and a node of any other class is unbounded on z
(`depth` null). `CullingCtrl.Culling` (0x70e0a4) collects the boxes with a physics overlap sphere
of radius 1.0 and mask 0x10 at the test position. Every registered `CullingVisibilityGroup` is
hidden except those listed by a `CullingGroup` that has a box containing the camera of the
viewport being drawn; a camera in no box hides all of them (0x70e0a4, 0x7052b9, 0x7054b8); a
box's group is the nearest ancestor with script `CullingGroup`, written into `m_ecullinggroup`
at initialisation (0x70d525, 0x704f9b; the property is stored on none of the 233 boxes).
`culling.groups` and `boxes[].group` carry that link. Measured: 233 boxes in the six PC Part 2 levels
(Bordello 104, NightClub 108, StreetsOfRiot 21), all `CollisionBoxNode`.

### Waypoints, stream blocks, lights

**`waypoints`.** The links are the ones `WaypointController.WayPointInit` (0x8b1062) builds at
load, not stored ones (`m_enextall`, `m_enextexclusivecharacterlist`, `m_epreviousall`,
`m_epreviouswaypoint` and `m_iwaypointid` are stored on no waypoint). Read from code: the walk
goes from `m_estart` over its next siblings; `id` is 0 for the start node and 1, 2, … after it;
`next_all` links each for-all node (the start node counts as one) to the next for-all node; an
exclusive node (type 0 or 1) is written into slot [type] of the previous node when that one is
exclusive to the same type, else of the last for-all node (`SetNextExclusiveCharacter`
0x8aa4e5). `m_eforcenext` then replaces the node's own slot; it has no effect on a node that is
not exclusive to type 0 or 1, and is itself replaced when the next sibling is exclusive to the
same type. Following a route (`command_get_follow` 0x8b2f6c): a node answers only when it is
for-all or exclusive to the asking type, with the type's slot when set, else `next_all`.
Measured: `m_eforcenext` is non-null on 28 PC waypoints (4 on for-all nodes).

**`files.stream_blocks`.** Read from code: a `StreamBlockTriggerOneShot` (0x847c78) works
once (`_tisused`), unloads `m_eunloadstreamblock`, loads `m_eloadstreamblock` and waits for
the loaded callback or 20.0 s; a `StreamBlockTrigger` (0x841c78, 0x841d9d) loads its block on
entering with local z > 0 or leaving with z ≤ 0 and unloads it otherwise. Measured: only
Part 1 Prison has stream blocks (4, with 3 one-shot triggers).

**`lights`.** Stored values; a value the node does not store is null (constructor defaults:
type 1, range 25, `attn_start` 0.75, brightness 1, shadow power 1, cones 45 / 55, 0x4a3d8e).
`type`: 1 point, 2 spot, 3 directional, 4 ambient, 6 box, 7 frustum; a stored 5 is written as
`type` 2, `textured` true, `stored_type` 5 (0x4a1c4a). Read from code (0x579fdf, 0x56a4c0): the
axis is local +Z; distance term = sat((range − d) / (range × (1 − min(attn_start, 0.99))));
spot term = sat((cos θ − cos outer) / (cos inner − cos outer)), the cones being half-angles
in degrees; colour × brightness × camera-distance fade (the saturate form is inferred from the
constants). `flicker` (`LightFlicker`, 0x774baf): `brightness_min` / `brightness_max`,
`period_s`, `range_m` (the mean of the two range values) and `active_within_m` 40.
glTF `KHR_lights_punctual`: 1 → point, 2 → spot (cone angles = the stored degrees in
radians), 3 → directional; `intensity` = `brightness`, not photometric; node =
`gltf_trs(world)` with the rotation multiplied on the local side by a half turn about Y
(0, 1, 0, 0), because glTF lights point along −Z; types 4, 6, 7 and `attn_start` go to
extras. The Blender importer does not place lights. Measured on PC Part 2: 2,267 lights, 180
with flicker.

### Path objects and navigation data

`path_objects[].nav` = `{index, id, method, distance_m, edges}`: the entry of the path-object
table of `<Level>.nav.json` (NAV_DATA.md) that is this node, and the `[cell, edge]` pairs of the
graph edges that carry it.

The join is **by id** first, as the engine does it. A table entry's `id` is the 1-based index into
the serialised list property `aiStaticPathObjectNodes` of the level's `AIWorldNode` (lookup PC
0x4837d5, X360 0x829f8260; property registered in 0x484ffb, setter 0x483844). The list was written
when the path data was generated and nothing adds to it at run time. `level.ai_world` =
`{uid, asset, collision_mask, node_collision_mask, use_collision_masks_for_map_builder,
generation, pivot_sheet_source, nodes, list_length, null_entries, unresolved, not_path_objects,
repeated}` (1-based positions). `generation` holds path-data generation inputs
(`groundSlopeMax`, `groundSlopeMin`, `holeMax`, `entityHeight`, `entityRadius`, `pitch`,
`stepMax`, `stepLength`, `graphAccuracy`, `nbSectors`, `distEdgeMax`); this exe cannot
regenerate (the three generation handlers are the stub 0x48d55e). Only `collision_mask` and
`node_collision_mask` are read at run time, by the Kynapse ray callbacks 0x48b44e and 0x48b56c.
Measured on 11 PC levels: `collisionMask` 8192, but 8193 in NightClub and PlayerVsPlayer;
`nodeCollisionMask` 0 everywhere. And `path_objects[].ai_world_index` is the node's position in it, or null.

`path_objects[].bound_at_run_time` is true for a node that is in the list and false for one that is
not; `counts.path_objects_unbound` counts the latter. Read from code: the path data's path object
(`KynapseStaticPathObject`, 0x48c249) looks its node up by id (0x4837d5), stores itself in the node
(+0x138) and takes over the node's impassable flag; `AIStaticPathObjectNode::SetIsImpassable`
(0x48a559) changes the path data only through +0x138. A node outside the list is never found: it is
in the level, a script can still set its flags, and the path finder does not know it. Measured on
the six-set export, the same on PC, PS3 and Xbox 360: every level's path-object table has as many
entries as its list (Part 1: Docks 15, Prison 24, Streets 14, Streets2 9, Undergound 25,
ConstructionSite 0; Part 2: Bordello 62, NightClub 48, StreetsOfRiot 18, Tutorial 2,
PlayerVsPlayer 1). Unbound nodes:

- Part 1 ConstructionSite, 4 of 4: unnamed, disabled, `impassable` false, no `path_object`, in
  `gameplay.fragment`; the list is empty and the `.hpd` has no path object.
- Part 1 Streets, 1 of 15: `StreetsRollerDoor_StaticPathObject` in
  `Gameplay/MissionStructure.fragment` at (-103.36, 0.25, 53.40). It has the node ids of the
  `StreetsRollerDoor.fragment` template (whose two instances are list entries 8 and 10) but is
  placed in the fragment itself, has no `path_object`, and is not in the list of 14. That it was
  pasted after the path data was generated is inferred.
- Part 2 Bordello, 1 of 62: the node of the null list entry 45. Its table entry exists and is
  joined by position (`nav.method` `"position"`), but the engine cannot bind it.
`nav.method` is `"id"` for these.

An entry whose list position is null or does not resolve goes **by position** (`method`
`"position"`): to the still unjoined node whose vertex nodes are nearest to all end points of the
entry's edges (the largest per-point distance counts), within 0.5 m, one entry per node. The same
distance is computed for every id-joined pair as a cross-check (`distance_m`); a pair farther apart
than the tolerance stays joined and is listed in `nav.id_position_disagree`.

Part 2 PC (2026-10-05; staged fragments, and the same on the PC extract, where Tutorial 2 and
PlayerVsPlayer 1 join by id as well): Bordello 61 by id + 1 by position, NightClub 48 by id,
StreetsOfRiot 18 by id, `id_position_disagree` empty, largest distance 0.1558 m (NightClub id 16).
Bordello entry 45 of the list is null (the single word `01 00 00 00` at offset 0x2026 of
`gameplay.fragment`), so the engine cannot bind that path object; the position join gives id 45 to
the node at 0.1196 m. In Bordello the list is in the order of the nodes in the level tree; in
NightClub and StreetsOfRiot it is not. `levelmeta` looks for the path data under
`EXTRACT_OUT/files` and `EXTRACT_OUT/extracted` by level name; without it `nav` is null and every
`path_objects[].nav` too (`ai_world_index` is still set).

The rest of the navigation data (mesh outlines, other graph vertices) lies about 1 m ABOVE the
positions in this file (character pivots, floors). Whether a placement stands on the mesh is
therefore tested in x / z with an altitude window (`nav_data.locate`), not by comparing heights;
the path-object end points alone coincide exactly, because they are the vertex nodes.

### AI sight (`volumes[].ai_sight`)

`{sheet, sheet_book, sheet_collision_mask, sheet_has_ai_bit, physics_type, blocks, sheet_source}` per collision
node. Read from code: the AI sight ray (0x48b44e) reports every shape whose pivot-sheet
`collisionMask` shares a bit with the level's `AIWorldNode.collisionMask`, and sight is blocked
when the first reported hit belongs to a `CollisionNode` with `physicsType` 1 (RIGIDBODY). So
`sheet_has_ai_bit` = the node's sheet (`pivotSheet_Id`) has a bit of `level.ai_world.collision_mask`,
and `blocks` = that and `physics_type == 1`. A stored `pivotSheet_Id` of 0 is no sheet
(`CollisionNode::SetPivotSheetID` 0x4a4c44): `sheet_collision_mask` 0 and `blocks` false. This
is the case for 4 StreetsOfRiot volumes (`physicsType` 1) and 2 Docks volumes (`physicsType` 2)
on all three platforms; that the shape's mask word is then 0 is inferred. A value is `null`
where the node does not store the property or a non-zero id is in no pivot book that was read.
The constructor defaults are `physicsType` 1 and the first sheet of `/pivotbooks/default.pb`
(0x4a8944), but no exported volume lacks either property, so they are not applied.
`sheet_source` says which case holds (`stored id`, `none (stored id 0, 0x4a4c44)`, `not stored`,
`id in no pivot book read`). The sheets come from the extract's own `pivotbooks/*.pb.json` when it has
them (Part 1 books differ: 42 sheets, some other masks), else from the bundled PC Part 2 table
`wlib/pivot_sheets.json` (47 sheets); `level.ai_world.pivot_sheet_source` says which.
`counts.volumes_block_ai_sight` counts the `true` ones (PC Part 2: Bordello 218 of 1,031
volumes, NightClub 409 of 1,093, StreetsOfRiot 157 of 870, Tutorial 10 of 34, PlayerVsPlayer 13
of 20; every one of the 124 placed vision blockers is among them). NightClub's 409 include 5 volumes
on `SolidCollisionAiCanSeeThrough`, because its mask 8193 shares bit 0 with that sheet. "Blocks" is a property of the node
alone: which shape PhysX reports first on a given ray is not established. NAV_DATA.md
("AI sight") has the engine side.

### Host-offset copies (`models[].host_offset_copy`)

`{"twin": uid or null}` on a model record whose stored local position is the one of another
node of the same class and fragment, with every component of the stored quaternion within
1e-5 of the other's (`HOST_OFFSET_QUAT_TOLERANCE`), while the two world positions differ by
exactly the translation of the fragment's host (`twin` = that other node), and on the other
model nodes of the same folder (`twin` null). Measured: StreetsOfRiot block C keeps ten enabled, visible
`CharacterSimple` nodes in plain folders directly under the fragment host, with local
positions in level coordinates, so they compose to 50 m above the street; seven placed ones
hang under a `PVSRootNode` whose local position (−100, −50, 105) cancels the host, and seven
of the ten have a twin at the same stored position among them, one for each placed node (one
pair differs in one quaternion component, 0.894935 against 0.894934). The key is on those 10
records (7 with a twin) and on no other record of the six PC Part 2 and seven PC Part 1
levels (measured). The composition itself is right (the host is applied once). Inferred: an
editor leftover, the source folder of a crowd that was moved under a PVS root.
Not established: whether the game draws them. `tools/blender_import_level.py` therefore keeps
the flagged records, in a switched-off collection of their own (`<Level>` > `Host-offset
copies`), and leaves the choice to the user.
`counts.host_offset_copies` counts them; the rule text is `conventions.host_offset_copy`.

### Forced states (`graph.nodes[].forced_state`)

On a `TriggerActionCharacter` node of action type 28 (`REQUEST_FORCED_STATE`), read from
`ActionExecute` 0x85b858 case 28: the action sends `command_set_forced_state(state, criteria,
time)` with `state` = `m_iinteger2` (`state_name` from the `ENEMY` enum: 9 =
`TWILIGHT_LADY_BACK_FLIP`, 7 = `HANG_BACK` …). When the target's AI type equals `for_ai_type`
(`m_iinteger1`; 1 enemy, 2 partner, 3 player-controlled, from `AILib.CharacterRootToAiType`
0x5974a3) and `m_nnumber1` is above 0, the criteria are `criteria_if_match` = 10 (`TIMER` |
`STATE_NOT_RUNNING`) with `time_s_if_match` = `m_nnumber1`; otherwise `criteria_otherwise` = 8
with time 0. With `m_nnumber1` ≤ 0 only the "otherwise" pair is written.
`counts.forced_state_actions` counts them (PC Part 2: Bordello 17, PlayerVsPlayer 1, none
elsewhere and none in Part 1; the four of Bordello's `Enemies.fragment` ask for state 9 for AI
type 1 with 0.05 s).

### Hero models (`level.hero_models`)

`{ctrl, rsh, nto, nto_head, rsh_rage, nto_flashing}`: the `LevelSceneCtrl` node and, per
reference (`_emodelrsh`, `_emodelnto`, `_emodelntohead`, `_emodelrshrage`,
`_emodelntoflashing`), `{uid, name, enabled, model}` of the node it names, or null. These are the
models the two heroes take (`CharacterDef.command_get_override_model` 0x666d03 →
`LevelSceneCtrl.command_get_override_model` 0x76ef49, character types 0 and 1). Each reference points to a disabled native `Character` node that is a child of the
`LevelSceneCtrl` node. Measured on all six sets (the platforms agree):

| Level | `rsh` | `nto` | `nto_head` |
|---|---|---|---|
| All five Part 2 play levels | `Rorschach_Dry.model` | `NightOwl_No_MaskDry.model` | `NiteOwl_MaskDry2.model` |
| MainMenu (both parts) | `Rorschach.model` | `NightOwl_No_Mask.model` | `NiteOwl_Mask2.model` |
| Part 1 Docks, Streets | `Rorschach.model` | `NightOwl_No_Mask.model` | `NiteOwl_Mask2.model` |
| Part 1 ConstructionSite, Prison, Street2, Underground | `Rorschach_Dry.model` | `NightOwl_No_MaskDry.model` | `NiteOwl_MaskDry2.model` |

`rsh_rage` (node `Rorschach_Rage`) and `nto_flashing` (`NiteOwl_Electric`) point to second nodes
with the same model in the Part 2 play levels and are null in MainMenu. Part 1 has no
`_emodelrshrage` property; its `_emodelntoflashing` nodes are named `NiteOwl_Electric`,
`NiteOwl electric`, `NiteOWl Electric` or `Niteowl-electric` depending on the level.

The weapon reference model (read from code, `CharacterRoot.command_set_weapon` 0x694378): the
`_root` state local `erefmodel` (task stack + state-locals base + 0x118, 0x694456–0x694467;
member +0x118 is `m_ehasjustdodgedme`) is cleared (0x694415) and, when the weapon type is 0 or 1 and the definition's
collection (+0x1c for 1H, +0x20 for 2H) is not null, set to the result of
`CharacterModelCollection.command_get_model` (0x694467); that node is then cloned as the weapon.
The weapon keeps it through `WeaponBase.command_set_ref_model` 0x8b31fb.
`CharacterRoot._eweaponrefmodel` (+0x218) has one reader (0x6791d2) and no writer (measured:
displacement and hash scan), and `WeaponBase` never sends `command_decrease_model_ref`, so a
weapon's count is never given back. Data: every armed placement on Part 2 has a
non-null collection for its type; on Part 1, 12 of 188 armed placements ask for a 2H weapon
from a definition with no 2H collection (`{COP_FAST}` 8, `{COP_LEADER}` 2, `{MERCENARY}` 1,
`{MERCENARY_FAST}` 1) and by the code get no weapon: `weapon.no_collection`,
`counts.weapons_no_collection`.

### Block files, face classes, a simulated curtain (data notes)

- **Block names.** `files.blocks` comes from the top fragment's path, not from the load block's
  name: Part 1 level `Streets2` is `Street2/Street2.block_h_z` and `Undergound` is
  `Underground/underground.block_h_z` (the names were `streets2.block_*` / `undergound.block_*`
  before). Checked against the archive directory and the loose Part 1 trees on all 39 levels.
  Not listed in any level file: the four stream-only Prison blocks
  (`BuildingPrisonShowerRoom`, `GeneratorRoom`, `hallway`, `PrisonYard`, each `.block_s_z`) and
  the common block (`WatchMen.block_*` in Part 1, `watchmenpart2.block_*` in Part 2); the
  extract output does not keep block files, so the level export cannot list them.
- **Which level hosts which face class** (measured on all `.fragment.json` of the six sets; the
  three platforms of a part agree). Every level host is a plain `FragmentNode` under the level's
  `CharacterDB` folder, except in `underground.fragment`, where it is a top-level node.
  `AnimationClassEnemy01Face` (Part 2): `Bordello`, `NightClub`, `StreetsOfRiot`.
  `AnimationClassEnemy04Face` (Part 2): `Bordello` only (the node is named
  `Enemy1AnimationClass`). `AnimationClassNiteOwlFace` (both parts):
  `GameEssentials/CharacterAnimation.fragment`, not a level. `AnimationClassEnemy01Face`
  (Part 1): `ConstructionSite`, `streets`, `docks`, `Prison`, `Street2`, `underground`.
  `AnimationClassUnderbossFace` (Part 1): `ConstructionSite` only. Tutorial, PlayerVsPlayer and
  MainMenu host no enemy face class. The face definition fragments are hosted by the type
  lists (`BordelloFace` ← `AllBodelloTypes`, `NightClubFace` ← `AllNightClubTypes`, `ThugFace` ←
  `AllThugTypes`, `TwilightHeadFace` ← `TwilightLady.fragment`; Part 1: `BikerFace`, `CopFace`,
  `MercenaryFace`, `MinionFace`, `PrisonerFace`, `ThugFace` ← the matching `All*Types.fragment`).
  That these load and initialise with the level is inferred.
- **`/art/props/common/curtains/Curtains_01.model`** (Part 2 only; NightClub `03_THP_MainRoom`
  and `26_THP_PeepingRoom`, 4 references each) carries a simulated NxCloth: 74 world-fixed
  vertices, collision disabled, flags 0x4164. Its world pins are applied (read from code): 0x507dd0
  skips a world fix only when the cloth's vertex buffer is format 6 (skinned; 0x4b96a8 →
  0x4b6e9f) and `characterClothMode` is on (0x4b96bc). The cloth's buffer (`Plane01`, 851
  vertices) stores FORMAT 5 (measured on the PC, Xbox 360 and PS3 files). The Xbox 360 Part 2
  image has the same test (0x8294fc30 → 0x822e33c8). (`python -m wlib.ragdoll_rig Curtains_01.model` prints the
  cloth record; RAGDOLL_RIG.md "Cloth".)

## A level in Blender (`tools/blender_import_level.py`)

    blender -b --python tools/blender_import_level.py -- LEVEL.json [--save OUT.blend]
        [--no-characters] [--no-sky] [--no-nav] [--include-disabled] [--limit N]
        [--keep-duplicate-images] [--compress]

or, inside Blender: Scripting workspace, open the file, Run Script; a file browser asks for the
`*.level.json` and File > Import > "Watchmen level (.level.json)" exists for the rest of the
session. The level file must lie in its export (`levels/` beside `models/`, `textures/`,
`extracted/`, `characters_v<version>/`, `nav/`); every path is one of the level file's own
strings, so the level file must use the naming of its export: `levelmeta` follows the
export's `--names` (default `canonical`) unless the option is given.

| What | How |
|---|---|
| Models | each GLB of `models[].models` is imported once into a collection of `<Level> Library`; a placement is an empty that instances that collection (`instance_type = 'COLLECTION'`) at `gltf`, converted as Blender's importer converts a node: location (x, −z, y), quaternion (w, x, −z, y). A collection instance, not a linked duplicate, because a GLB can hold several objects |
| Collections | `<Level>` > `Terrain`, `Props` > one per section, `Characters` > one per character folder, `Sky`, `Navigation` (off), `Host-offset copies` (off), `Library` (off); `Disabled` and `Invisible` only with `--include-disabled`. A section is the nearest fragment at or above the placement that lies in the level's own folder (a PVS room or city block, `gameplay`, `Gameplay/MissionStructure`) |
| Custom properties | `watchmen_uid`, `watchmen_node_id`, `watchmen_fragment`, `watchmen_section`, `watchmen_model`, `watchmen_node_class`, `watchmen_node_name`, `watchmen_enabled`, `watchmen_visible`, `watchmen_opacity`, `watchmen_cast_shadow`, `watchmen_cube_map`, `watchmen_glb`, `watchmen_level`, `watchmen_kind` (`prop`, `sky`, `character`, `scene_model`); on characters also `watchmen_path`, `watchmen_group`, `watchmen_character`, `watchmen_character_type`, `watchmen_variant`, `watchmen_variant_pick`, `watchmen_variant_status`, `watchmen_variant_member`, `watchmen_outfit`, `watchmen_variant_candidates` (`<member index>:<name>`, ...), `watchmen_state_of_mind`, `watchmen_weapon_type`, `watchmen_pivot_height`. A property without a value is left out (`watchmen_node_name` of an unnamed node, `watchmen_group` of the heroes). The level file has no sheet name on a placement, so none is stored; the import summary is the JSON in the level collection's `watchmen_import`, the level file's path its `watchmen_level_file` |
| Terrain | the GLB of `files.terrain[]` under an empty at its `gltf`; each layer gets a material of its own, the layer's `0_diffuse` PNG (found below `textures/` without regard to case, the GLB keeps the stored spelling) times the vertex tint, or grey times the tint without a PNG. The PNG is packed into the `.blend` |
| Sky | the placements whose model lies below `.../environments/sky/`, at their `gltf`, unscaled (the Bordello dome is 2,957 m across); visible to the camera only, so a dome does not shadow a light outside it |
| Characters | `characters[]`: the GLB `<folder>/<variant>.glb` of a member of `variant.members`. `watchmen_variant_pick` says how it was chosen: `fixed` (the level file fixes the member); `candidate_in_turn` (status `candidates`: the game takes the least-used member, the first in list order on a tie, so the k-th character of a definition gets candidate k mod n, counted in the order of `characters[]`; a member without a name or file is passed over); `scene_model` (a hero: the folder's `_Dry` file when `level.hero_models` names a Dry model); `first_candidate` (any other status: the first member); `folder_default` (no named member: the folder's own GLB). Members of one name share a GLB and are its outfits in member order (`watchmen_outfit`, 1-based: the Heavy has 18, `KnotTop_Medium` and `KnotTop_Large` 11, `KnotTop_Small` 9): the `OUTFIT <k> ...` nodes that `asset.extras.watchmen.parts.members[k].nodes` lists take the place of `shown_nodes`; the face stays that of outfit 1. The order in which the game builds the characters of a level is not established, so the hand-out shows every outfit about equally often but not on the character that wears it in the game. A GLB is imported once per variant and outfit, without the other outfits, weapons and ragdoll helpers and with one clip, the first that matches `_EXP_MOV_idle_stand`, then `_MOV_idle_stand`; the instance sits 1.0 m above the placement along the placement's own up axis (the GLB's origin is `GamePivot`) |
| Host-offset copies | an enabled, visible record with `host_offset_copy` (above: StreetsOfRiot block C, ten `CharacterSimple` nodes 50 m above the street) is placed at its `gltf` like any other, but in `<Level>` > `Host-offset copies`, a collection that is switched off, and not in `Props` or `Characters`. Whether the game draws these nodes is not established, so they are kept and hidden, not dropped; switch the collection on to see them. Each instance has `watchmen_host_offset_copy` and, with a twin, `watchmen_host_offset_twin` (the uid of the placed node); the import summary counts them in `counts.host_offset_copies`. A disabled or invisible one stays with `Disabled` / `Invisible` |
| Scene models | an enabled node of role `character_model` (a placed `Character` / `CharacterSimple`): its part models at the node's `gltf`, bind pose, in `Characters` > `Scene models`, switched off. The skeleton model it lists first has no mesh and no GLB. The 36 placed `CharacterSimple` nodes of StreetsOfRiot (the seven twins of the host-offset copies among them) stay there: the level file gives each `visible_effective` false under an invisible `PVSRootNode` (six, `PVSNoCombatSimpleEnemies_*`, 0x48e028), which trigger actions of the level target (measured, PC) |
| Frames | the level's `coordinate_frame` must be `right-handed-true` or absent (mirrored: imported with a warning); a GLB whose marker differs from the level's is refused. The header of every GLB is read before anything is created |
| Twice, and failures | a level whose file is already in the `.blend` (the level collection's `watchmen_level_file`) is refused. When Blender's glTF importer fails on a file, the import stops with the file's name; what was built stays in the level collection with the Library switched off and has to be deleted before the level is imported again |
| Images | identical embedded PNGs are merged into one datablock after every 25 imported GLBs, compared by the bytes of the packed file, the colour space and the alpha mode |

Left alone: materials (as the importer builds them), lights, the world, the frame range.
Not placed: lights, particles, volumes, cube maps, cameras; `opacity` is stored, not applied.

Measured with Blender 3.6.0 (the `bpy` module on Linux, 2 cores, 3.9 GB of memory), six-set export of
2026-10-07. Library collections: one per GLB, one more for every further outfit of a character GLB.
Blender 5.2.2 on Windows, background mode (measured): PC Part 2 Bordello imports as 3,070 instances
from 264 GLBs in 40 s into a 260 MB file, NightClub as 3,811 instances from 277 GLBs in 42 s into a
257 MB file, both without an error; every prop instance sits within 0.02 mm of the `gltf` placement
of its level record. The table was measured before the
`Host-offset copies` collection existed; the import was not run again with it. Inferred from the
level file: the ten flagged records of StreetsOfRiot are among its 46 scene models, which were
switched off before as well (`Characters` > `Scene models`), so the visible scene is the same.

| Level | placements in the file | instances | library collections | import | `.blend` | peak memory |
|---|---|---|---|---|---|---|
| Bordello (PC Part 2) | 3,043 models, 167 characters | 2,901 props + 1 sky + 167 characters + 1 scene model | 264 | 66 s | 312 MB | 2.6 GB |
| NightClub (PC Part 2) | 3,737 models, 170 characters | 3,640 props + 1 sky + 170 characters | 277 | 71 s | 306 MB | 1.9 GB |
| StreetsOfRiot (PC Part 2) | 3,564 models, 145 characters | 3,430 props + 2 sky + 143 characters + 382 parts of 46 scene models | 271 | 99 s | 377 MB | 2.3 GB |
| Docks (PC Part 1) | 4,554 models, 124 characters | 4,464 props + 1 sky + 124 characters | 247 | 104 s | 362 MB | 2.5 GB |
| Prison (PC Part 1) | 3,117 models, 94 characters | 2,587 props + 1 sky + 91 characters | 268 | 73 s | 306 MB | 2.9 GB |
| Bordello (PS3 Part 2) | as PC | as PC | 264 | 67 s | 313 MB | 2.6 GB |

Left out by default (Bordello / NightClub / StreetsOfRiot / Docks / Prison): disabled props
(18 / 4 / 11 / 28 / 452), invisible props (90 / 52 / 33 / 19 / 24), the disabled definition models
(32 / 40 / 42 / 42 / 53), disabled characters (0 / 0 / 2 / 0 / 3). No model GLB is missing in the
three Part 2 levels; Docks has one, `Docks_waterSurface_aligner.model`, and Prison one,
`GuardRoom_Door_02.model` (2 placements), both models without mesh data (placed as empties marked
`watchmen_missing`). Merging identical embedded images removes 2,358 / 3,021 / 3,390 / 3,430 / 2,956
image datablocks (423 / 413 / 379 / 446 / 500 MB). Every instance's world matrix equals the
converted `gltf` of its record to single precision (largest difference 3e-5 m, in StreetsOfRiot).
Characters by outfit: the 168 Heavies of NightClub are 9 or 10 of each of the 18 outfits; the 92
Dominatrices of Bordello 10 or 11 of each of 9 variants.

The contact figures below were measured with every candidate shown as its first member, outfit 1,
and the character pivot lifted along the world's up axis; the placements and the props are the same.

Contact, measured in the assembled scenes (lowest vertex of an instance minus the first surface
of another object below it; ground-type props: garbage, dumpsters, newspapers, barrels, crates,
furniture, rubble, statues, vases, plants):

| | Bordello | StreetsOfRiot | Docks |
|---|---|---|---|
| ground-type props with a surface below | 902 | 1,645 | 1,749 |
| median | −0.010 m | −0.032 m | −0.005 m |
| within 5 cm / 20 cm | 727 / 847 | 689 / 1,031 | 1,539 / 1,654 |
| lowest vertex minus terrain, ground-type props above the terrain | 13 (the level is indoors) | 1,318: median +0.003 m, 629 / 1,005 | 1,650: median −0.004 m, 1,298 / 1,408 |
| characters: placement minus the floor below it, median | 0.000 m | 0.000 m | 0.000 m |
| characters within 5 cm / 20 cm | 128 / 135 of 167 | 101 / 119 of 143 | 84 / 115 of 124 |
| soles of the posed character above the placement | −0.011 to +0.008 m | −0.090 to +0.002 m | −0.090 to +0.001 m |

The characters farther than 20 cm from the floor stand above it (95th percentile 1.6 m, 1.9 m
and 0.3 m): on what they stand was not looked up. `KnotTop_Large` has its soles 9 cm below the
placement in its idle clip. In StreetsOfRiot 10 of the 46 enabled `CharacterSimple` nodes of
`03_SOR_City_Block_C.fragment` have a `world` position that is higher and farther than their
neighbours by (100, 50, −105), the translation of that fragment's host node, and hang 33 to 80 m
above the nearest surface; their node ids are those of the Thug definition's members. Whether
that is the data or the composition rule for these nodes is not established.

## Library

    import level_meta
    level_meta.levels(extract_out)                 # [(scene, name, scope id, asset)]
    level_meta.build_level(scene, name, scope_id, extract_out)
    level_meta.write(extract_out, out_dir, only=None)
    level_meta.gltf_trs(pos, quat, frame=None); level_meta.compose(parent, pos, quat)
    level_meta.link_nav(level, nav_doc["path_objects"])   # join a watchmen-nav/1 table by hand
    level_meta.read_save(path)                     # .kpw -> dict

## Save files (`watchmen savemeta FILE [OUT.json]`)

    u32 5, "KPWF", u8, u32, u32 titleChars, UTF-16LE title, u32 payloadBytes
    records: [u32 entity id][u32 property name hash][u32 type id][u32 nWords][words]

The type id is the name hash of the type name (`integer`, `list(list(truth))`, ...); values
use the fragment encodings. Output (`watchmen-save-meta/1`): `title`, `records` (entity,
property, type, `value` or `raw_words`), `decoded` (`last_checkpoint` and `completed_scenes`
per save type; `button_map` for `SETTINGS.kpw`). A save holds the progress and settings nodes
only: no object state.

`decoded.button_map` names `SettingsState.m_emetadevicebuttonmap` (type
`list(list(list(list(integer))))`, 675 words in a shipped profile): `shape`, `index_order`
(save device, player, logical button, code) and `devices` = {`SAVE_DEVICES` name: [{`player`,
`buttons`: {`LOGICAL_INPUT_BUTTON` name: [codes]}}]}, only for what holds a code (−1 = none).
Read from code: the type and the first two indices (0x82bc77, 0x74d04e). Inferred from the
content: the button index and "three alternative codes". `code_names` = {device: {code: name}} names the codes: the engine registers
`GamepadButton` 0–15 (0x4d3514), `KeyboardKeys` with 118 names (0x4cc842) and `MouseButtons`
1 / 2 / 4 (0x4db801) (read from code; the three tables are `wlib/input_code_enums.json`).
Inferred from the fit with one shipped profile, in which all 16 pad codes and all 19 keyboard
codes have a name: a pad device's codes are `GamepadButton` values (MENU_UP 0 =
`GAMEPAD_DPAD_UP`, PLAYER_DEFEND 9 = `GAMEPAD_RIGHT_SHOULDER`), a `KEYBOARD_MOUSE` code
below 256 is a `KeyboardKeys` value and 257 / 258 / 260 are 256 + `MouseButtons` (left,
middle, right). The code that fills the map and the 256 offset were not read.

## Not established

- For a placement with `variant.status` or `weapon.status` = `candidates`: which member comes
  up in a given play session (it depends on the build / delete history). Also open: whether a
  the order in which start-activated characters are built. (A restart or checkpoint restore from
  the in-game menu unloads the level block and resets the enemy collections' counts. The eight
  weapon collections of `WeaponDB.fragment` sit under `GameEssentials`, a scene-level
  `SceneScope(FragmentNode)` outside every load block (measured); the class has no game-event
  handler and a weapon's count is never decreased (read from code), so the weapon candidate
  depends on every weapon handed out since the program started (inferred).
  `AllPlayerTypes.fragment` holds no collection in PC Part 2 (measured). ENGINE_CONSTANTS.md "Which outfit a
  character gets".)
- What a character without a stored state of mind starts as (no shipped placement is without
  one: all 488 Part 2 and 519 Part 1 `CharacterRoot` property records carry `m_istateofmind`); whether a PASSIVE enemy keeps a
  target or turns to face the player while idle.
- That the position `CharacterGroup` reads for the return position is the node's world position
  (inferred).
- For `volumes[].ai_sight`: which shape PhysX reports first on a ray; that a property absent
  from a record leaves the constructor value (inferred).
- Equal `siblingOrder` children are inserted in file order (read from code and measured, see
  above). That ties keep insertion order is read from code (0x48f556); they are counted in
  `counts.action_order_ties`.
- Tag-3 references past the own fragment instance fall back to the nearest-instance rule (never
  used by shipped data: FRAGMENT_FORMAT.md).
- Nodes below a node without a transform take the nearest ancestor with one: confirmed on
  StreetsOfRiot in Blender (1,457 placements; ground-type props 188 of 282 within 5 cm of the
  terrain, median height of the lowest vertex +0.010 m against +0.005 m for the 1,160 that are
  not below such a node; 0 of 150 within 1 m if the local transform is taken as the world
  transform). One level; the other levels were not assembled. `parentLink = 1`: read from code
  (0x49325d, 0x48d789) the node composes with its parent; the flag only gates later parent
  moves in play mode. Part 2 has no such node; Part 1 has 3 HUD sprites per game level and 21
  `PivotNode`s in ConstructionSite (flee points and `StartPos`), which lie in the frame of
  their Group at y = 36 (measured). Whether a script moves an ancestor of such a node during
  play is not established. `counts.parent_link_1` and `counts.placements_below_transformless_ancestor` say
  per level how often each rule is used; `models[].parent_chain_without_transform` lists the
  classes passed over.
- Why Bordello's list entry 45 is null (a node replaced after the path data was generated is the
  likely cause) and what the game does at that door.
- Sound setups are only named or left in the graph as plain nodes; trigger classes other than
  conditions / actions / use triggers / visibility conditions / groups have no `label`.
- Whether `WaypointController.StateInitAutoStart` (0x8aa1fb) runs in the shipped game (no
  caller among the script classes).
- When `Node` vfunc 29 runs after a load, so the moment the PVS handle is set; whether a script
  toggles the six invisible StreetsOfRiot PVS roots.
- The pose of the terrain's collision body (0x4a8047 → 0x4f4f3d) was not read; PS3 was not read
  for the terrain draw.

Real data (2026-10-04): Part 2 PC 6 levels and Part 1 PC 7 levels, 0 unresolved references in
each. The six-set export of 2026-10-05 (PC, Xbox 360 and PS3, both parts): 6 and 7 levels per
set, 0 unresolved references in all 39 level files; `nav` is filled in every level but MainMenu,
and the `stable_uid` sets of a level are equal on the three platforms but for the nodes one
platform's data lacks (NightClub 2, StreetsOfRiot 1). The keys added on 2026-10-05 (`variant`, `weapon`, `ai_start`,
`combat_presets`, `cube_maps`, `zone_trigger`, `ai_world`, the id join) were measured on the
staged Part 2 PC fragments of Bordello, NightClub and StreetsOfRiot and then on the full Part 2 PC
extract (six levels, 0 unresolved references); their values were not compared across Part 1 and
the console extracts.
