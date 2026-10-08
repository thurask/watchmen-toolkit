# WP5 - runtime core and level flow: from files on disk to a running level

Target `KapowMultiDEDRM.exe`. Machine-readable tables: `findings/wp5_runtime_tables.json`.
Scratch and helper scripts: `work/wp5/`.

Evidence marks used on every item:

- **read** - traced in the decompilation or disassembly; address given.
- **data** - measured on the user's extracted game files (906 `.fragment` files, the `.scene`
  file, `SaveData/Profile1`), parsed from the binary files with the toolkit's parser.
- **inferred** - plausible, reason given.
- **not established** - collected in section 8.

Script handlers are cited as `Class.handler` with the address from the lifted corpus
(`findings/script_lifted/`). "Slot" means a 4-byte cell.

## 0. The life cycle in one page

1. `game.naz` holds one common block (`watchmenpart2.block_h_z/_s_z`), one block pair per level
   and loose movie, music and AI-path files (**data**). A block is a directory of asset headers
   plus one trailing fragment, the "loadblock fragment".
2. The scene file `WatchMenPart2.scene` is itself a fragment. Its root is the `SceneNode` (the
   common load block); it contains one `SceneScope(LoadBlock)` node per level and a
   `SceneScope(FragmentNode)` for `GameEssentials.fragment`, the game-wide controllers (**data**).
3. `MasterSceneCtrl` activates a level scope. The scope calls `LoadBlock.Load` with a callback; a
   time-sliced state machine reads the 400-byte header, the directory, every asset header (assets
   are created or re-used by path hash), the localized headers and the fragment blob
   (0x4a36d8, **read**). A worker thread reads stream data (mips, vertex buffers) later
   (0x4e0e5d, **read**).
4. `ApplyLoaded` instantiates the loadblock fragment into the `LoadBlock` node (0x4addf6 ->
   0x5473ee, **read**). The stream reader creates one node per type record, sets properties in
   file order, and instantiates a nested fragment at the moment a `FragmentNode`'s `assetName`
   property is applied. References that cannot be resolved yet are queued and retried when the
   outermost load ends. Each created scripted node then gets `script_construct`.
5. The scope calls `ProjectLib.InitializeHierarchy`: `initialize_local` over the whole subtree
   (pre-order), then `initialize_external` over the whole subtree (0x7fe7e9 / 0x7fe85c, **read**).
   Most classes enter their main state from `initialize_external`.
6. `MasterSceneCtrl` broadcasts game events SCENE_ACTIVATED, then SCENE_RESTARTED or
   SCENE_RESTORED_FROM_CP, then SCENE_STARTING (0x7a63b2, **read**). Level data reacts through
   `TriggerConditionGameEvent` nodes.
7. Every frame (`SceneNode` update 0x496294): input; native `FrameUpdate` of two node lists with
   animation and physics between them; then the script update, which resumes every scripted
   entity's coroutine task once, in entity-table order, bracketed by `preScriptUpdate` /
   `postScriptUpdate` sent to `ScriptUpdateCtrl` (**read**).
8. Level logic is data: trigger volumes and conditions fire trees of actions; actions activate
   placed `CharacterRoot` nodes, which build their sub-systems by instancing two fragments at run
   time; `CharacterGroup` fires an "all dead" action; checkpoints store an id only.

---

## 1. Object model

### 1.1 Entity, type object, native class hierarchy

- Everything is an `Entity` (vtable 0xa26428, 12 virtual slots). `Node` (0x9fd31c, 30 slots) adds
  the tree; `PivotNode` (0x9fd4d4, 38 slots) adds a transform. **read** (RTTI, `work/submap/rtti.pkl`).
- 163 classes derive from `Entity` (RTTI, **read**). The node branch, with the classes that occur
  in level data:

```
Entity
  Asset (16 asset classes, section 4)          Sheet (PivotSheet, TextureSheet)
  BlockMemorySetup                             Physics::Actor / RigidBody / Trigger / Cloth / CharacterController
  Preferences (editor option classes)          Physics::Joint / D6Joint, Physics::ArticulatedBody
  ParticleModule (affectors, spawners, ...)    NetworkManager, NetworkSession
  Node
    Folder  TextSlot(SubtitleSlot)  AnimSlot  AnimLayer  AnimBlendSource  PhysicsWorld  MoviePlayer
    AIBrainNode  AIWorldNode  DecalManager  GFXEffect  LensFlare  Control  ControlSetup
    SoundSlot  SoundGroup  SoundController  SoundStreamPlayer  SoundSystemNode  SoundEffect*Node
    GamepadNode  KeyboardNode  MouseNode  PlatformNode
    PivotNode
      Group  SubPivot  Light  Wind  Track  TrackPoint  Annotator  SnapGrid  CubeMapNode
      BoneAttacher  BoneController  EmitterNode  ParticleSystemSlot  PropertySequenceNode
      StreamingProbe  PVSRootNode  LensFlareManager  GrassCollisionNode  EmbeddedJointNode
      AI path nodes (seed point, static/dynamic path object, fake target)
      Camera (EditorCamera)     Sprite (TextBox)
      CollisionNode
        BaseModel (Model, Character, GeometryEffect)   TerrainNode
        EmbeddedActorNode
          MockupBox (AI zone nodes)
          CollisionVolumeNode > ConvexCollisionVolumeNode > CollisionBoxNode / CapsuleNode / SphereNode
      FragmentNode
        StreamBlockNode
        LoadBlock
          SceneNode
```

  Full parent table: `wp5_runtime_tables.json` `native_node_classes`.
- Entity fields (**read**; each from the accessor named in `Entity__RegisterMembers` 0x511603 or
  `Node` registration 0x494142, or from the function cited):

| offset | meaning | evidence |
|---|---|---|
| +0x04 | type object (`EntityType*`) | 0x4f934b, 0x48e575 |
| +0x08 | handle; `handle+4` is a 16-bit reference count | 0x4a4971 |
| +0x0c | flags: bit 0 "being destroyed" (messages refused, 0x47c9fd), bit 2 "has an unresolved reference" (0x545e1b @0x545f4a) | read |
| +0x10 | script member block | 0x47dfed |
| +0x14 | task handle (`handle+4` = `Task`) | 0x4799f1, 0x4f996d |
| +0x20 | name string | 0x4f9bf0 |
| +0x24 | index in the entity table = `sessionID` | 0x4edf25, 0x4f9bf0 |
| +0x28 | `fragmentID` (the node id stored in fragments) | 0x53c4fa @0x53c584 |
| +0x2c | `useRealtime` | 0x4f98ed |
| +0x34 | `runScript` ("Auto-resume script") | 0x4f9b96 |
| +0x40 | bit 0: all ancestors enabled; bit 2: post-load call pending | 0x48e51d, 0x47a9fd |
| +0x44 | `runFrameUpdate` ("Auto-run FrameUpdate") | 0x491395 |
| +0x48 / +0x4c / +0x50 | `logicalParent` / `firstLogicalChild` / `nextLogicalSibling` | 0x7fe7e9, 0x53a5ff |
| +0x54 | `enabled` (this node only) | 0x48f65c |

- Type object `EntityType` (vtable 0xa24dcc, ctor 0x50b1d6): name +0x10, **type id +0x1c = hash of
  the type name**, slot size +0x24, parent type +0x30, script class +0x34, native property records
  +0x7c. Type-id rule is **data**: the save files carry type ids and `0xfd034a24` = hash("truth"),
  `0xbda17de4` = hash("number"), `0x36604ff4` = hash("integer"), `0x5520b06f` =
  hash("list(integer)"), `0xca625776` = hash("list(list(integer))"), `0x7848543d` =
  hash("list(list(truth))") (section 5.5).
- The entity manager (`DAT_00e15124`, ctor 0x4edd94) keeps a table of all entities (+0x14) and a
  parallel flag byte per entity (+0x20): bit 2 (4) "has a task", bit 3 (8) "script may run". The
  first free index is tracked at +0x2c (0x4edf59). **read.** That new entities take the lowest free
  index is **inferred** from that hint; the allocating function was not read.

### 1.2 Enable, visible, runScript, runFrameUpdate

- `enabled` is per node; `globalEnabled` is `enabled` and all ancestors enabled. Setting `enabled`
  (0x48f65c -> 0x48f613) propagates the ancestor bit to the subtree (0x48e51d), calls virtual slot
  26, and sends the script message `on_enabled` or `on_disabled` to the node. **read.**
- A node's script runs only if `enabled`, ancestors enabled, `runScript` set and the type has a
  script class (`Node` virtual slot 2, 0x48e575). The result is cached in flag bit 3 of the entity
  table (0x4f324e -> 0x48f473 / 0x48f488). **read.** Consequence: disabling a folder freezes every
  script below it without unwinding its coroutine.
- `runScript` false means "do not resume automatically": the task still exists and commands still
  run, but only an explicit `ResumeScript` (native message, 0x500419 -> 0x4f9baa) advances the
  state function. This is the "manual script resume" used by `ScriptUpdateCtrl` (section 3.5).
- `runFrameUpdate` registers the node in the scene's native update set (0x48f6ae -> 0x48f430) if
  enabled, ancestors enabled and virtual slot 18 says the class wants updates (0x48e05f). **read.**
- `visible` only affects drawing (registered next to `enabled` in 0x494142); not traced further.

### 1.3 Properties: three storages, one lookup by hash

- Global property registry: a hash map from **name hash** to a 0x1c-byte record
  (`propertytype.cpp`, 0x4ee06a / 0x4edfa4). A property is declared as `"name:type"`; the hash
  covers the name up to the colon (0x423d30) and the type object is stored at record+0x18.
  Registering the same name with a different type returns -1. So a property name has **one type
  engine-wide**, which is why a fragment can store `[hash][value]` without a type tag. **read.**
- Native properties: each native class registers accessor pairs by name (`*__RegisterMembers`).
  They live in the type's record array (+0x7c) and are found through a per-type hash map
  (0x4f7a02). Get calls the getter through the data type's virtual +0x4c (0x4ff93b). **read.**
- Script members: the script class's properties in registration order, laid out by
  `ScriptClass_FinalizeLayout` 0x47ed4b in the block at entity+0x10 (see `wp0_script_names.md`).
  The block is allocated when a node of a scripted type is created (0x47dfed: class+0x4c slots,
  each member default-constructed). Get by hash tries the script class first (0x47c42d), then the
  native table (0x4ff93b). **read.**
- A per-entity dynamic property bag was looked for and **not found**: set (0x510737 -> 0x50e94c)
  and get (0x4ff93b) only consult the script class and the native type table, and the fragment
  reader skips a key the node's type does not have (0x545e1b, typed mode). **read** for those
  three paths; a bag elsewhere is not excluded.
- A property record flag (record+0x38 bit 0) marks properties that are not serialised
  (`autoName`, 0x511603). **read.**

### 1.4 Script classes on native classes: `Class(Native)`

- A fragment type name is either a native class (`Folder`) or `Script(Native)`. On load the name
  is looked up as registered (0x5022f6); if absent it is split at the parenthesis (0x4fd89d) and
  the native part is looked up (0x4fd96f); if that fails the default type `DAT_00e1433c` (`Node`)
  is used (0x53a699). **read.**
- The same script class can sit on different natives: `TriggerCharacter` is registered with base
  `Node` but level data uses it on collision nodes, and `TriggerActionCharacter(PivotNode)` occurs
  beside `TriggerActionCharacter(Node)` (**data**, Bordello `Enemies.fragment`). The pivot variant
  is how an action carries a position (teleport target, follow-pivot target).
- Script inheritance is separate from native inheritance: a derived script class repeats its
  parent's members and commands first (`wp0_script_names.md` section 3).

### 1.5 Messages and commands

- Three kinds of callable (**read**):
  - script command of a class: record with name hash at +0x18; dispatched by `(index, hash)`
    (`Entity_SendCommand` 0x596d91 -> 0x47c9fd) or by hash (0x4f99a4 -> 0x4f92a2 -> 0x47decf);
  - native message of a type: registered with a signature string by `EntityType::RegisterMessage`
    0x50ed51; found through the type's hash map and called through the global handler table
    `DAT_00c8be20` (stride 0x28) (0x4f92a2);
  - engine-defined script messages registered by name with 0x5004bb / 0x4ef657 (global message
    table, `message.cpp`): `script_construct`, `script_destruct` (0x47c477), `preScriptUpdate`,
    `postScriptUpdate`, `preEngineUpdate`, `postEngineUpdate`, `viewportRenderBegin(integer)`
    (0x4942f7 region, part_0004 line 17931), `on_enabled`, `on_disabled`, `StopmodeUpdate`, `start`.
- By-hash dispatch (0x47decf) looks the hash up in the class's map and gets `(kind, index)`:
  kind 0 = plain command; kind 1 = command owned by one state, valid only while that state has a
  frame on the task (0x479d9f searches the frame array from the top); kind 2 = several
  state-owned overloads, the innermost active state wins (0x479e01); kind 3 = both a root version
  and state versions. If no state matches, the message is not handled by script and falls through
  to the native table. **read.** This is the mechanism behind "the same command registered in
  `_root` and in `StateActive`".
- **Delivery is immediate.** 0x47c9af calls the handler synchronously through 0x479c56 (which
  sets `g_self` and the state frame bases). There is no message queue in the engine. The only
  deferral is what a command itself requests: a state change is written to the task's pending-call
  record and executed when the command returns to nesting depth 0 (0x47b8ba -> 0x47a836), or at
  the receiving state's next checkpoint. **read.**
- A script entity gets its task lazily: the first command sent to it creates the task, pushes the
  `_root` state frame and runs it once (0x47c95b). **read.**
- Broadcast: 0x48d44d walks the whole entity table and sends the hash to every entity. Used for
  `start` when the scene enters play mode (0x495d11). **read.** Gameplay "broadcasts" are not this:
  they go through `GameEventCtrl` listener lists (section 5.4).

### 1.6 Tree order

- Children are a singly linked list (first child, next sibling). Position among siblings is the
  property `siblingOrder`; the parent is the property `logicalParent`. Both are ordinary serialised
  properties (0x494142), so a fragment builds its tree by setting them. **read** (registration);
  the insertion routine was not read.
- Script code walks trees directly through +0x4c / +0x50 (e.g. 0x7fe7e9). Order of children is
  therefore the order every recursive initialisation, activation and "find child" uses.

---

## 2. Fragment instancing

### 2.1 File header (read 0x54306d; **data**: all 906 files)

```
u32  version               4 in every file
u8   singletonFragment     Fragment+0xbc
u8   smartSelectable       Fragment+0xbd   (0x53ca5c)
u32  nameLen (incl. NUL), char name[nameLen]   fragmentName, Fragment+0xac
u8   reapplyable           Fragment+0xbe   (0x53ca69)
u8   typed                 Fragment+0xa8   0 in every file
u32  chunkCount
chunks: [u32 size <= 0x2800][payload]       payloads concatenate into one stream
```

The toolkit documents "17 bytes, or extended with a name when a flag bit is set". The engine
reads it as above: 16 + nameLen bytes, 17 with the empty name. Counts: 527 plain, 239
`smartSelectable`, 129 singleton, 11 `reapplyable` (**data**).

- `reapplyable` selects the allocator of the stream buffer (0x54306d) and is the condition for
  applying a fragment at run time: `FragmentNode` virtual slot 38 (0x4ac7e9) refuses with
  "Fragment '%s' could not be applied run-time since the reapplyable flag is not set" unless the
  flag is set, a load block is being applied (`DAT_00e14604`), or the scene is in stop mode. A
  non-reapplyable fragment's buffer is freed after the block is applied (0x5473ee prints "Tried to
  apply free'd fragment"). **read.** The 11 reapplyable files are exactly the three
  `CharacterRootTemplate_*` and the eight `CharacterVisual/*CharVisual` fragments (**data**): the
  ones instanced when a character is built.
- `typed` mode adds `[typeId][wordCount]` after each key and lets the reader skip unknown or
  mismatching properties (0x545e1b @0x545edd). Shipped fragments do not use it; **save files do**
  (section 5.5).

### 2.2 The stream reader (0x545e1b, read from disassembly)

`Fragment::Apply(target)` is 0x5473ee; the loop is 0x545e1b. Per record:

| first word | action |
|---|---|
| `0xFFFFFFFF` | type record: read id, read the type name with the string type's reader, resolve the type (1.4), **create the node** (`type->vtbl+0x6c`), store it in the fragment's load map `id -> node` (Fragment+0x94). If the type is the scene type (`DAT_00e142ec`), no node is made: the existing `SceneNode` is used (0x53c4fa). |
| `0xFFFFFFFE` | instance: read id, make that node the current node |
| anything else | property key: look up the descriptor (0x4ee10d), call the type's reader (`vtbl+0x38`) with (stream, value, current node, key, apply target, fragment), set the property on the current node (0x5107b2), destroy the temporary |

- Node ids: with header version >= 2 the node's `fragmentID` is the id from the file. Older
  versions re-rolled colliding ids at random (0x53c4fa @0x53c578). **read.**
- So nodes are created in type-record order, and **all properties are applied in file order**,
  parent links included (`logicalParent` is just a property). Type records also occur between
  instances (toolkit doc), so a reference may name a node that does not exist yet.
- Nested fragments: `assetName` is a property of `FragmentNode` whose setter is virtual slot 38
  (0x498db7 jumps to `vtbl+0x98`). It fetches the `Fragment` asset and applies it **at that moment**,
  inside the outer loop (0x4ac7e9 -> 0x4ab7e5 -> 0x49e1ad -> 0x5473ee). Nesting is therefore
  depth-first, and a nested fragment's nodes exist before the host's remaining properties (its
  script members) are read. **read.**
- Before applying, 0x4ab7e5 deletes the host's existing children (0x48d63e) and saves entity
  references that point into the old subtree as raw serialised references, to replay them
  afterwards (0x4ab4b3, 0x49e211). **read** (outline).

### 2.3 Entity references (`EntityType` reader 0x500b81, re-resolver 0x505d84; read)

| tag | layout | meaning |
|---|---|---|
| 1 | `[1]` | null |
| 2 | `[2]` | the entity the fragment is being applied to: the host `FragmentNode` (the load block for a level's top fragment) |
| 3 | `[3][id]` | local. Looked up, in order: the load map of the fragment being read (0x53cb0d); the nodes under the host found by walking children without entering nested `FragmentNode`s (0x4a4205 / 0x4a4029, compare `fragmentID`); the scene-wide id map (0x4f9206) |
| 4 | `[4][a][n][n ids]` | relative path. Start node: the scene if `a == 0`, otherwise the referring node. From the start, take the nearest `FragmentNode` at or above it (0x48e4fe), go up `a - 1` further enclosing `FragmentNode`s (0x48e4e2), then for each id find the descendant with that `fragmentID`, depth-first in child order, not descending into nested `FragmentNode`s although such a node can itself match (0x53a5ff) (0x53c224) |
| 5 | `[5][n][n ids]` | singleton path. `ids[0]` is looked up in the global singleton map (0x51511f); the rest descends as for tag 4 (0x53c1cc) |
| 0 | `[0]` | not handled by the reader; one word consumed, value stays null |

- Singleton map: a `FragmentNode` whose fragment has `singletonFragment` set registers itself
  under **hash(effective name)** (0x4a1d63, log "[FragmentNode] Installing %s (Effective name: %s)
  with CRC %u"). The effective name is the header `fragmentName`, or the asset file's base name
  when the header name is empty (0x540afd). **read**, and **data**: every tag-5 head in Bordello
  resolves this way - `8a35d53f` "Bordello", `7677f316` "Bordello_Gameplay", `ac1b759c`
  "Bordello_Enemies", `4ed4262d` "Bordello_Cameras", `288468f1` "Bordello_PartnerAI", `cf8fdaf3`
  "GameEssentials", `70d1e469` "AllBodelloTypes" (empty header name, file base name).
- Unresolved references: if a lookup fails and the node's type has the property, the reader sets
  flag bit 2 on the node and the loop stores a pending record (node, key, a copy of the raw words)
  (0x545340). `FUN_00545fd9` retries every pending record through the type's `vtbl+0x48` and drops
  those that resolve. It runs only when the "loading" flag `DAT_00e15124+0x31` is clear, and
  0x5473ee saves and restores that flag around the load (0x4ebe09), so the retry happens once the
  **outermost** fragment has finished. Records that still fail stay in the list for later loads.
  **read.**
- Tag statistics over the 906 files (**data**): tag 1: 44,386; tag 2: 4,637 (4,537 of them on
  `logicalParent`); tag 3: 69,082; tag 5: 9,554; tag 4: 17, all with `a = 1` and two ids
  (`MainMenu.fragment`, `WallLadder4m/6m.fragment`).
- In the reader the "levels up" field of a tag-4 path is not written explicitly (only the
  re-resolver passes `a - 1`, 0x505d84). With `a = 1` both give 0, the only case in the data.
  The behaviour for `a > 1` at first load is **not established**.

### 2.4 After the stream: construction and initialisation order

1. `script_construct`: 0x5473ee clears `DAT_00c89e04` during the load so that node creation does
   not send it (0x47dfed); after the pending-reference pass it iterates the load map and sends
   `script_construct` (hash global `DAT_00e12e14`) to every created node whose type has a script
   class. The iteration is the hash map's bucket order, **not file order**. **read.**
2. Post-load virtual: the caller (0x49e1ad) walks the applied subtree in pre-order and calls
   virtual slot 29 on each node (0x48d612 -> 0x47a9fd), unless a load is still in progress, in
   which case the node is flagged and handled later. For `PivotNode` this recomputes the world
   transform (0x495bbe). **read.**
3. Singleton registration of the host (0x4a1d63). **read.**
4. When a load block is applied while the scene is playing, 0x4addf6 additionally calls virtual
   slot 20 on every node of the block (0x4981db); `Character` overrides it (0x498055). Meaning
   **inferred**: native "start".
5. Script initialisation is done by script, not by the engine. No native code sends
   `initialize_local` (0x7cdedb82), `initialize_external` (0x2ae98f9b), `deinitialize`
   (0x196ec739) or `deinitalize` (0x6b932724): the constants occur only in registrations and in
   `ProjectLib` (**read**: search of the whole dump). `ProjectLib.InitializeHierarchy(root)`
   0x7fe750 runs `RecursiveInitializeLocal` (0x7fe7e9: send to the node, then to each child in
   sibling order) over the whole subtree and then `RecursiveInitializeExternal` (0x7fe85c) the same
   way. Callers: `SceneScope.StateActivate` (level and game-essentials load), `CharacterRoot`
   (sub-system build, six sites), `WeaponSpawner`, `CharacterSpawner` (**read**: grep of the lifted
   corpus).
6. `start` is broadcast to all entities once, when the scene enters play mode (0x495d11). Few
   classes handle it; `SceneScope.start` (0x813b0b) is the one that matters: the root scope starts
   activating, sub scopes register with their parent and wait.
7. Tear-down mirrors it: `ProjectLib.DeinitializeHierarchy` sends `deinitialize` in pre-order
   (0x7fe7b8 -> 0x7fe8cf); `script_destruct` is sent by the engine when the member block is freed (0x47e0a1).
   Note the two spellings: 221 classes register `initialize_local`, 71 `deinitialize`; a handful
   register the misspelt `deinitalize`, which `RecursiveDeinitialize` never sends (**read**: the
   send uses 0x196ec739). Those handlers are dead unless called directly.

What the two initialisation passes are for (**read** on the trigger classes): `initialize_local`
may only touch the node's own subtree and its parent (register with the parent, collect child
actions); `initialize_external` may use other objects, because every object has had its local pass,
and is where a class enters its main state (`CALL_STATE(StateActive)`).

### 2.5 Creating, cloning and destroying at run time (builtin module 0x47ff8c; read)

- `CreateNode(typeName, parent)`, `CreateNodeAtSiblingPos(typeName, parent, sibling)`,
  `CloneNode(node, parent)`, `DeleteNode(node)`, `ReparentNode(node, parent)`.
- `CloneNode` (0x47d558) is serialise-and-instantiate: it makes a temporary `Fragment`, saves the
  source subtree into it (0x542f27), creates a temporary `FragmentNode`, applies the fragment
  (0x5473ee), moves the first child under the requested parent and runs the pending-reference
  pass. A clone therefore gets fresh nodes with the same property values and internal references
  remapped by the normal tag-3 rule.
- Spawning a character = instancing two fragments (`CharacterRoot.InstantiateSubSystems` 0x67884e,
  **read**): `CreateNode(type name of def.m_echaracterfragment, self)`, then the new node's virtual
  slot 38 is called with that def node's fragment name (applies `CharacterRootTemplate_<kind>`),
  then `InitializeHierarchy`; the same for `def.m_emodelfragment` (`<kind>CharVisual`). The rest of
  the build is in `dominatrix_audit.md` a11. `DeleteSubSystems` deinitialises and deletes them.
- A placed `CharacterRoot` is thus a light placeholder until activation; only the 16 nearest
  activated enemies own sub-systems (audit a12).

### 2.6 Toolkit `anim_state_machine.load_tree` / `resolve_ref` against the engine

| # | toolkit | engine | effect |
|---|---|---|---|
| 1 | `{'xref': ids}` (tag 5) is treated as a path whose first id is "looked up next to the referring node" | `ids[0]` is the name hash of a singleton fragment, looked up in a global map | The toolkit cannot resolve a tag-5 reference into another file except by accident; with the name-hash rule all of them resolve (checked on Bordello). |
| 2 | `{'xref4': ids, 'a': a}` (tag 4) is not handled by `resolve_ref` (only `xref` and `ref`) | relative path from the referrer's enclosing fragment instance, `a - 1` instances up | 17 references in the corpus are dropped. |
| 3 | candidates with one id are disambiguated by "nearest common ancestor", then "shallowest inside the current node" | deterministic: depth-first in sibling order inside one fragment instance, never entering a nested instance | Same answer when ids are unique inside an instance (true for version-4 files); the toolkit's fallback "last id that exists anywhere" can return a node the engine would not. |
| 4 | `{'ref': id}` is a node of the same fragment instance | also falls back to the host's scope and to the scene-wide id map | Differences only for references that leave the instance. |
| 5 | nested fragments are spliced only under `AnimationStateGroup` nodes with `assetName` | any `FragmentNode`-derived node; existing children are deleted first | Fine for animation classes; a general level loader must splice every `FragmentNode`, `TriggerUseFragment`, `SaveFragment`, `CharacterRootFragment`, ... |
| 6 | children sorted by `siblingOrder`; top-level nodes are those whose `logicalParent` is not in the file | same data; a top-level node's `logicalParent` is tag 2 = the host | Agrees. |
| 7 | `{'etag': 2}` = the instancing state group (`fragment_host`) | the apply target | Agrees. |
| 8 | key `key_0991b0d4` typed as an integer | it is `CharacterGroup.m_ezonetrigger`, an entity reference (hash of the name is 0x0991b0d4; **data**: the key occurs only on `CharacterGroup`, 119 times as tag 1 and 22 times as tag 3) | This is the source of the 22 "unknown key" residues in `FRAGMENT_FORMAT.md`: `[3][id]` read as integer 3, then the id read as a key. Fix: type the key as entity. |
| 9 | `.scene` files are not accepted by `kapow_json.load_fragment` (extension check) | a scene is a fragment | Parses with the same code once the extension test is relaxed (**data**: `WatchMenPart2.scene`, 39 nodes). |

---

## 3. Scheduler

### 3.1 Frame order (`SceneNode` virtual slot 39, 0x496294; read)

1. Real frame time from the millisecond clock, clamped to 0.1 s (constants 0x9e9628 / 0x9e664c
   confirmed from bytes). Game time step = real step x `timeMultiplier` (scene+0x2dc) x
   `editorTimeMultiplier` (+0x2e0).
2. Input (0x4b5644, 0x4c87c3).
3. Native update 0x495fec:
   - message `preEngineUpdate` to the engine-update handler (scene+0x27c);
   - the registered nodes are split by virtual slot 12 into a first and a second list;
   - first list `FrameUpdate` (virtual slot 17);
   - 0x5427a6, 0x529f71, 0x50305c (animation, sheet and physics-side ticks; identities
     **inferred** from the address ranges they call into);
   - second list `FrameUpdate`;
   - message `postEngineUpdate`.
4. Particle manager.
5. Script update 0x495e41 (3.2), only in play mode, or in pause mode when the single-step flag
   (+0x2e4) is set.
6. Clean-up, camera selection.

`playMode` (scene+0x2d4): 0 play, 1 stop, 2 pause. Correction to `dominatrix_audit.md` b1 ("in
pause mode only the script update runs"): that sentence describes the branch taken when the flag
at scene+0x2d8 is set, which is not the pause mode. In pause mode (2) the game time step is forced
to 0 and neither the script update nor (unless a node's virtual slot 19 says so) the native update
runs. The game's own pause does not use this mode at all (3.6).

Which classes are in which native list (**read** from the vtables; table in the JSON
`frame_update_classes`): a node is updated only if its class's virtual slot 18 returns true.

- First list (slot 12 returns false): `AIBrainNode`, `Camera`, `DecalManager`, `EmitterNode`,
  `ParticleSystemSlot`, `SoundController`, `SoundGroup`, `SoundStreamPlayer`, `SoundSystemNode`,
  `GamepadNode`, `KeyboardNode`, `MouseNode`, `TerrainNode`.
- Second list: `Character`, `AIWorldNode`, `PhysicsWorld`, `PropertySequenceNode`,
  `EmbeddedJointNode`, `Wind`, `PlatformNode`, `SceneNode`, `GrassCollisionNode`; and the collision
  family (`CollisionNode`, `Model`, box / capsule / sphere, `MockupBox`, ...) under a per-node
  condition (slot 18 = 0x48181e, not read).
- Each node uses the real time step instead of the game step if its `useRealtime` is set
  (0x495fec). So the native side of a frame runs **before** the scripts of that frame: a property a
  script sets on a `Character` is consumed by that node's `FrameUpdate` in the next frame, unless
  the script calls the native function directly (as `CharacterRoot.StateActive` does with
  `UpdateAnimPoseAndCloth`).

### 3.2 Script update (0x495e41; read from disassembly)

1. `preScriptUpdate` to the script-update handler (scene+0x278; `ScriptUpdateCtrl` installs itself
   with `SceneNode.SetScriptUpdateHandler`, 0x823be4).
2. The scene's own task is resumed.
3. The run list (`DAT_00e14438`) is rebuilt from the entity table: every entity whose flag byte
   has bit 2 and bit 3 set (has a task, script may run), in table index order.
4. Each listed entity is resumed once (0x4f9baa) if the game time step is > 0 **or** the entity
   has `useRealtime`.
5. `postScriptUpdate` to the handler.

Order between scripted objects is therefore the entity-table order, which is creation order with
freed indices re-used (1.1). Objects that need a defined order opt out of this list (3.5).

### 3.3 Tasks, frames, states

Layouts are in `wp0_script_names.md` section 2; additions from this pass (**read**):

- One `Task` per scripted entity, created by the first command (1.5). The task's frame array is a
  stack of **state** frames; `_root` is at the bottom. A state is a coroutine function; commands
  and methods are plain calls that run on the C stack and never own a frame.
- Resume (0x4f9baa): requires virtual slot 3 (`enabled`, ancestors enabled, not being destroyed;
  0x481773) and a task; then 0x479a8f decides readiness; then 0x47a0f6 runs the top frame's
  function and keeps calling the (possibly new) top frame while a frame exists and the task is
  neither sleeping nor waiting for a frame. So when a state calls another state, the callee starts
  in the same frame; when a callee leaves, its caller continues in the same frame.
- States nest: `CALL_STATE` (0x47a533, mode 0) pushes the callee above the caller, and the caller
  resumes at its checkpoint when the callee leaves. `GOTO_STATE` / `LEAVE_STATE` (0x47a513,
  mode -1) unwinds frames down to and including the named state and then pushes the target if
  there is one (0x47a572). Only the top frame executes; a command owned by a lower state is still
  reachable while that state is on the stack (1.5). Typical stack: `_root` > `StateActive`.
- A state change requested from inside a command is stored in the pending-call record (0x47a4b0)
  and takes effect when the command returns to depth 0 (0x47b8ba -> 0x47a836 runs the task until
  the request is consumed). If the request comes from deeper inside (a command called while a
  state function is on the C stack), the state function sees it at its next checkpoint
  (0x47a66f). **read.**
- When only `_root` remains and nothing is pending, 0x47a836 releases the task back to a
  10-entry pool (0x47a728) and clears the entity's "has a task" bit (0x4f996d): such an object
  costs nothing per frame until the next command. `_root` of most classes is just
  `WAIT_SECONDS(-1)` (wake time 0xffffffff = never). **read** in outline: the arguments of the
  release calls are not visible in the decompilation.

### 3.4 Waits and clocks (read; constants confirmed from bytes)

- `Task_WaitNextFrame` 0x4797e9: wake frame = frame counter + 1. Two counters: the game frame
  counter `DAT_00e1431c` (0x493976) and the real one `DAT_00e14320`; an entity with `useRealtime`
  (task flag 0x80000, 0x4f98ed) uses the real one.
- `Task_WaitSeconds(t, realTime)` 0x479a1d: sets the sleeping flag and a wake time in
  milliseconds on one of two clocks: accumulated game time `DAT_00e14314` (scaled by the time
  multiplier) or accumulated real time `DAT_00e1430c` (0x479801; factor 1000.0 at 0x9e5a60).
  Real time is used if the argument asks for it or the entity has `useRealtime`. A negative `t`
  sleeps for ever.
- Ready test 0x479a8f: sleeping tasks compare the clock with the wake time; then the wake frame
  is compared with the frame counter.
- Nothing else wakes a task: there is no "wake" primitive. A sleeping state is woken by a command
  that requests a state change (the pending call is processed regardless of sleep) or by
  `ResumeScript`.
- `BuiltinModule.EnableBlockingMode(truth)` sets task+0x44: while set, pending calls are not
  honoured at checkpoints, so a long initialisation (`SceneScope.StateActivate`) cannot be
  pre-empted by a state change. **read** (use), exact flag handling skimmed.

### 3.5 `ScriptUpdateCtrl`: ordered updates and manual resume

Read in the audit (b3) and re-checked here: `preScriptUpdate` 0x815030 resets `characterlib`'s
update list and runs `Update(order)` for orders 0..`m_idefaultscriptordering` (5);
`postScriptUpdate` 0x8150d9 runs the higher orders. `Update` 0x812ab5 resumes the entities
registered with `command_register_manual_resume(order, entity)` (0x8148cb) and sends
`command_update` to the listeners of `command_register_update_event_listener` (0x814a0b).
Registering calls `Entity::SetRunScript(e, false)` (0x8148cb, **read**), so the flat list skips the
entity; unregistering sets it back.

Resulting order inside one script update: manual-resume buckets 0..5 (players at 5,
`MasterSceneCtrl` registers itself too, 0x78e1dd), the scene task, every auto-resumed entity in
table order (enemies, triggers, controllers), then buckets above 5.

### 3.6 Time scaling: pause and slow motion (read)

- Pause is not the engine pause mode. `MasterSceneCtrl.command_request_pause(requester)`
  (0x78daed) keeps a requester list; on the first request (outside the main menu) it stores the
  current multiplier and sets the scene's `timeMultiplier` to 0; `command_unrequest_pause`
  (0x78dbba) restores it when the list empties. While paused, `command_set_time_multiplier` only
  updates the stored value (0x78dc96).
- With multiplier 0: the game time step is 0, game-time waits never expire, and the run list
  skips every entity without `useRealtime` (3.2). Menus, HUD, fades and `MasterSceneCtrl` itself
  are `useRealtime` objects (**data**: `UseRealTime=true` on `LevelSceneCtrl`). Native nodes with
  `useRealtime` keep animating.
- Slow motion: `WorldLib.SetTimeMultiplier(m)` (0x8a9d27) forwards to `MasterSceneCtrl` and
  rescales the physics integration rate (`PhysicsWorld.SetIntegrationRateInHz(c1 / m + c2)`).
  **It does nothing in co-op**: the call is ignored when the game mode is 3 unless `m == 1`.
  Slow motion scales every game-time object equally; objects that must keep real speed use the
  real clock (`CharacterRoot` keeps `_nslomotime` in real time, audit section 7).
- Per-object time scaling does not exist in the engine; `useRealtime` is the only distinction.

---

## 4. Streaming and assets

### 4.1 Blocks of the shipped game (data: `game.naz`, 57 entries)

| entry | role |
|---|---|
| `derived_pc/levels/game_levels_part2/watchmenpart2.block_h_z` (20.4 MB) + `.block_s_z` (5.6 MB) | common block: the scene, `GameEssentials` and everything it references |
| `.../mainmenu/mainmenu.block_h_z/_s_z` | main menu level |
| `.../nightclub/`, `.../streetsofriot/`, `.../bordello/`, `.../tutorial/`, `.../playervsplayer/` `*.block_h_z/_s_z` | one pair per level |
| `data/levels/.../gameplay/*aipath.hpd` | Kynapse path data, loose |
| `data/art/cutscenes/*.bik` | movies, loose |
| `derived_pc/sounds/music/**/*.mediastream_s` | streamed music, loose |
| `data_baked/tnt/production/database.bin`, `derived_pc/precompiled_shaders/shader.archive`, engine helper assets | loose |

`_h_z` holds the headers and the loadblock fragment, `_s_z` the stream data (toolkit doc).

### 4.2 `LoadBlock` (native, `loadblock.cpp`)

- Properties (0x4ae441): `isCommonBlock`, `isLoaded`, quad-tree bounds, `workingPlatform`,
  `sceneReservedAssetBudget`, four embedded `BlockMemorySetup` (editor, PC, X360, PS3).
  Messages: `Load:truth`, `Load(callbackEntity, callbackMessage):truth`, `ApplyLoaded:truth`,
  `Unload`. **read.**
- Rules enforced by `Load` (0x4ae0fd, **read**): a loaded block is not loaded twice; in play mode
  only one non-common block may be loaded at a time; all common blocks must be loaded first;
  common blocks cannot be unloaded in play mode.
- With a callback, loading is asynchronous: a per-frame hook (0x4a4b2f) pumps the state machine
  0x4a36d8 with a time budget. Without one, the machine runs to completion and the fragment is
  applied at once.
- State machine (read in outline, states at `loader+4`): 1 read the 400-byte header; 2-3 read the
  directory, allocate two ping-pong buffers of the largest header-blob size ("Allocating 2
  buffers for asset block loading"); 4-5 read header blobs one after the other, each processed by
  0x4a3525 while the next is being read; at the first localized record seek to
  `languageHeaderOffset[language]` ("Loading localized header assets (language: %s)"); 6 wait for
  the asset stream manager; then read the fragment blob; 7 loaded, "the loadblock fragment should
  be applied".
- Per directory record (0x4a3525, **read**): six sizes (one per language, the current language's
  is used), type id, path; `AssetManager` lookup by path hash and type (0x54ba59: the hash folds
  case, the full path is compared, the type must match); an existing asset is re-used (reference
  count at asset+0x64), otherwise `type->vtbl+0x6c` creates it; then a stream flag and three
  (offset, size) pairs.
- `ApplyLoaded` (0x4addf6): sets `DAT_00e14604`, applies the fragment into the load block node
  (section 2), marks the block loaded, and in play mode calls virtual slot 20 on its nodes.

### 4.3 Stream blocks: present in the engine, unused by the shipped game

- Engine: `StreamBlockNode` (`Load`, `Unload`, `AddLoadedCallback`), auto stream blocks driven by
  a `StreamingProbe` on the camera (sector radii, FOV) and a spatial tree, manual stream blocks
  with slot limits, budgets in `BlockMemorySetup` (`maxNumLoadedAutoStreamBlocks`,
  `maxMemPer...StreamBlockMB`, ...). `StreamBlockNode::Load` refuses when no manual slot is free
  (0x4a04b2). **read** (registrations and that one function).
- Script: `StreamBlock(StreamBlockNode)`, `StreamBlockManager`, `StreamBlockTrigger` (a collision
  box that loads or unloads its target block when a playable character crosses it),
  `StreamBlockTriggerOneShot` (unload one, load another, once), `TriggerActionCheckpoint._estreamblock`
  and `StreamBlockManager.command_get_streamblock_for_loading` (pick the block of the checkpoint to
  restore). **read** (handler lists).
- **Data**: no `StreamBlock`, `StreamBlockNode` or `StreamBlockTrigger*` node exists in any of the
  906 fragments (only the `StreamBlockManager`), every checkpoint's `_estreamblock` is null, and
  every `BlockMemorySetup` in `WatchMenPart2.scene` has all stream-block budgets at 0. A Part 2
  level is one load block, resident as a whole. The streaming path is dead code for this title.

### 4.4 Asset stream manager (0x4e0e5d; read in outline)

A worker thread loop: wait on a signal (1 s timeout), take a request, open the asset's stream file,
seek to the request's per-language offset, read the per-language size into the asset's buffer, and
move the request to a "done" list consumed on the main thread ("[AssetManager] Loaded stream
data: %s"). What decides which assets request stream data and when it is dropped was not read.

### 4.5 Asset types (RTTI + vtables, read; type names from the toolkit's block table)

`Asset` virtual slot 24 reads a header blob, slot 23 writes one. The 16 classes:

| class | type name in blocks | header reader | file | toolkit |
|---|---|---|---|---|
| `Fragment` | `fragment` | 0x54306d | `.fragment`, `.scene` | parsed (`kapow_fragment.py`) |
| `ModelRes` | `modelRes` | 0x547006 | `.model` | decoded |
| `Texture` | `Texture` | 0x5382aa | `.bmp`/`.tga` | decoded |
| `Animation` | `animation` | 0x5434af | `.animation` | decoded |
| `PropertySequenceAsset` | `PropertySequenceAsset` | 0x54558c | `.sequence` | decoded |
| `SoundAsset` | `sound` | 0x5516fa | `.wav` | decoded |
| `MediaStreamAsset` | `mediastream` | 0x555288 | `.mediastream` | decoded |
| `TextRes` | `textRes` | 0x5387ae | `.txt` | localized text; see toolkit docs |
| `Font` | - | 0x540c6e | `.ttf`/`.font` | `font_asset.py` |
| `ParticleSystemAsset` | `ParticleSystemAsset` | 0x55d3ed | `.particle` | property bag |
| `PivotBook` | `pivotbook` | 0x5229d7 | `.pb` | property bag |
| `GrassAsset` | `grass` | 0x52af1a | `.grass` | property bag |
| `DetailMeshAsset` | `DetailMeshAsset` | 0x52de50 | `.detailmesh` | property bag |
| `TerrainAsset` | `terrain` | 0x5397d0 | `.terrain` | `terrain_json` |
| `TerrainColoringAsset` | - | 0x52da01 | `.terrainColoringAsset` | 5 files per Part 1 set, decoded (`terrain_asset.py`) |
| `AIAsset` | `aipathdata` | 0x52945d | `.aipathdata` / `.hpd` | **not decoded** (Kynapse path data) |

`ModelEffects(ModelRes)` and `TextureEffects(Texture)` are script classes on asset classes, the
same `Class(Native)` mechanism as for nodes. Whether the toolkit's extraction of each type is
complete was taken from the toolkit docs, not re-tested here.

### 4.6 Language slots

The six per-language slots are indexed by the current language id (0x45c762: the platform
object's override at +0x88, or the detected language at +0x84 when the override is 6). The id is
the `LANGUAGE` enum registered in `builtin.cpp` 0x47ff8c with explicit values: **0 English,
1 French, 2 Italian, 3 German, 4 Spanish, 5 Danish**. **read** for the enum and the index;
**inferred** that the block slots use the same numbering (the loader prints the slot through the
language-name function 0x437c91). This fills the gap "which language each slot number means" in
`KAPOW_NAZ_FORMAT.md`.

---

## 5. Level flow

### 5.1 The condition / action system

Structure (**read**: `TriggerConditionBase` 0x8632fa, `TriggerActionBase` 0x84afa9; **data**):

- A **condition** node registers with its parent (`command_register_condition`; the parent may
  be a `TriggerConditionLogical` / `Toggle` / `Tutorial` / `TriggerCharacter`) and collects its
  **child nodes that have the property `_tIsAction`** as its action list, in child order.
- `FireAction(activator)` (0x85411f) sends `command_fire_action(activator)` to each action in
  order, sets `_tistriggered`, and arms `_nreactivationcountdown = m_treactivationdelay` if
  `m_treactivatable`. `UpdateReactivation` (0x8525b4) counts down with the frame time and clears
  `_tistriggered`. A condition that is not reactivatable fires once.
- An **action** registers with its parent action (`command_register_child_action`).
  `command_fire_action` runs only if the action node is enabled (and its ancestors); it executes
  its own effect and then `command_fire_child_actions` (0x84aed2): every child action in order,
  then `_eauxaction` (an entity reference to an action anywhere, used to call shared action
  trees). `TriggerActionBase` itself has no effect: it is the grouping node (`{act_BASE}`).
- Everything is synchronous (1.5): a whole action tree runs inside the frame of the event that
  fired it, except children of `TriggerActionDelay`, camera tours and movies.
- Disabling a trigger volume or an action node (`TriggerActionGeneral` DISABLE) is how level data
  turns logic off; `RESET_CONDITION` re-arms a fired condition.

Conditions (properties are the inherited `m_treactivatable`, `m_treactivationdelay` plus):

| class | properties | when it fires (read; handler) |
|---|---|---|
| `TriggerConditionCollision` | `m_itrueon` ENTER / LEAVE / INSIDE, `m_etriggerentity` (collision node; default = parent), `m_iactivator` ANY_CHARACTER / PLAYER / RORSCHACH / NITE_OWL / SPECIFIC / ENEMY, `m_eactivatorentity`, `m_tignoreduringcombat` | subscribes to the collision node's contact callbacks (0x863c8a); maps the contact actor to a `CharacterRoot` and filters by activator (0x863875); ENTER fires on entry, LEAVE when the character leaves (`RemoveIntruder` 0x8643c2), INSIDE every frame while someone is inside and the condition is re-armed (`StateActive` 0x864063). With `m_tignoreduringcombat` it waits until the combat orchestrator knows no enemies. Also listens to one game event to drop dead characters (0x863c0f). |
| `TriggerConditionGameEvent` | `m_itrueon` (GAME_EVENTS id), `m_iconditiontype`, `m_iamount`, `m_iactivator`, `m_eactivatorentity` | registers as listener of the event (0x86448a); on the event goes to `StateConditionTrue`, fires its actions, and returns to false after the reactivation delay or stays true (0x86481c). `command_reset_trigger` re-arms. Does not derive from the base class. |
| `TriggerConditionLogical` | `m_iconditiontype` ANY / ALL / SOME, `m_icount` | counts child conditions answering `command_condition_true` (0x86de58): ANY >= 1, ALL = all, SOME = exactly `m_icount`. Re-evaluated when a child reports `command_child_condition_changed` and every frame; fires on the transition to true (0x86ef55). |
| `TriggerConditionToggle` | `_tstartstate`, `_tfireon` | **is itself an action target**: `command_fire_action` flips it between `StateFalse` and `StateTrue` (0x86f436 / 0x86f5b3); fires its own actions when entering the state equal to `_tfireon`; answers `command_condition_true` in `StateTrue`. This is the latch that turns "group dead" events into inputs of a logical condition. |
| `TriggerConditionCharacter` | `_echaracter`, `_iconditiontype` HEALTH_PERCENT_BELOW / ABOVE, `_nvalue1` (percent) | each frame compares `100 * m_nhealth / def.m_nmaxhealth` with the percent; false while the character is a placeholder (0x8525fd). |
| `TriggerConditionGameMode` | `_igamemodetype` (flags RORSCHACH 1, NITEOWL 2, COOP 4) | fires once in `initialize_external` if the current game mode is in the mask (0x864b3d). |
| `TriggerConditionTrue` | - | fires its actions once when initialised (`StateMain` 0x86f7d3); used for "on load" action lists. |
| `TriggerConditionTutorial` | `_iwho`, `_icondition` (TUTORIAL_EVENT), `_isubcondition`, `_icount`, `_etextbox`, `_eprogressaction` | counts tutorial events reported by `MenuTutorialCtrl` (0x86ff57). |
| `TriggerConditionVisibility` | distance, viewport position, combat flags, glow / passive models | the "use" prompt: true when the player can see and reach the node; fired by a use command (0x870baf). |
| `TriggerCharacter` | `_iactivatortype` (TRIGGER_ACTIVATOR) | collision volume that forwards enter / leave of matching characters to registered listeners (`TriggerUse`) (0x862e84). |
| `TriggerCounterScript` + `TriggerThreshold` | `m_istartvalue`; `m_itrigvalue` | counter changed by AMOUNT_* actions; broadcasts TRIGGER_THRESHOLD_* game events (0x86e4e6). |

Actions:

| class | properties | effect (read; handler) |
|---|---|---|
| `TriggerActionCharacter` | `m_iactiontype` (35 values), `m_itargettype` ENTITYREF / RORSCHACH / NITE_OWL, `m_etarget1..3`, `m_iinteger1..2`, `m_nnumber1..2`, `m_ttruth1..2` | `ActionExecute` 0x85b858, table below |
| `TriggerActionCharacterForceMove` | `m_iactiontype` FORCE_MOVE / SKIP_FORCE_MOVE, `m_eactivatorgroup`, `m_emovetotargetgroup1`, `m_eskiplink` | `RunningState` 0x854a1e: locks the player controller or pauses the AI, walks the characters along the pivots under the target group with `command_follow_pivot`, ends when all arrived, when a camera tour is skipped, or on `command_terminate`. |
| `TriggerActionGeneral` | `m_iactiontype` (25 values), `m_etarget1..2`, `m_iinteger1..2`, `m_nnumber1`, `m_ttruth1`, `m_sstring1` | `ActionExecute` 0x85f77b: ENABLE / DISABLE / FLIP_ENABLED set `enabled` on the target (and notify a `TriggerSendEnableDisable` child); SET_VISIBLE / INVISIBLE / FLIP; RESET_CONDITION (re-enable and `command_reset_trigger`, recursively); START / STOP_SEQUENCER on a `PropertySequenceNode`; TRIG (`command_trig`, 9 receiving classes); CHANGE_MOVEMENT_TYPE; AMOUNT_RESET / INCREMENT / DECREMENT on a counter; USE_TRIGGER_FREEZE / UNFREEZE; SET_IMPASSABLE; ACTIVATE_WAYPOINTS; SET_TIME_MULTIPLIER (`WorldLib.SetTimeMultiplier`); depth of field on / off; SET_SEARCHLIGHT_TARGET. |
| `TriggerActionDelay` | `m_ndelaynumber0..19` | `ActionExecute` 0x852ecd: child action i (i < 20) is fired at once if its delay is 0, otherwise queued as (action, activator, time left); `StateMain` 0x852d2a decrements with the frame time and fires at <= 0. The child's own `_ndelay` is an editor mirror of the parent's number (0x852ff8). |
| `TriggerActionCheckpoint` | `_icheckpointid`, `_estreamblock` | fire = `GameStateCtrl.command_game_checkpoint_reached(id)` and nothing else (0x85d2a3); its **children run only on restore** (`command_restore_checkpoint` 0x85d2de). |
| `TriggerActionGameEvent` | `m_iactioneventtype` | broadcasts the game event with the activator as sender (0x85df54). |
| `TriggerActionGameMode` | `_igamemodetype` flags | fires its children only if the current game mode is in the mask (0x85e286): a filter node. |
| `TriggerActionCamera` | `_iaction` CAMERA_TOUR / SET_CAMERA / END_TOUR / SET_CHARACTER_CAM_DIR, `_ecamera`, `m_iviewport`, `_tdisableplayerctrl`, `_tpauseenemyattack`, `_tskipable`, `_tunskippabletime`, transitions, `_eontourskipped`, `_eontourend`, `_elookatnode` | a tour (`StateTour` 0x84bed0) plays the child `PropertySequenceNode`, fires child camera cuts at their `_ndelay`, locks players, and at the end or on skip fires `_eontourend` / `_eontourskipped`. |
| `TriggerActionMovie` | `m_emovie`, transitions | `StatePlayMovie` 0x85fdae: request pause, full-screen viewport, `MoviePlayerCtrl.command_play`, wait, release pause, **then** fire children. |
| `TriggerActionSound` | `m_iactiontype` (14 values), targets, numbers, `_tchildrenafter` | play / stop / cross-fade / group pause / volume / music setup, music state, intensity (0x862b6c). With `_tchildrenafter` the children fire from `command_sound_done`. |
| `TriggerActionParticle` | `m_iactiontype` DO_PARTICLE_EFFECT / START / STOP | creates an emitter on a `ParticleSystemSlot` or starts / stops an `EmitterNode` (0x861445). |

`TriggerActionCharacter.m_iactiontype` (**read** 0x85b858; the JSON has the full table):

| id | name | effect |
|---|---|---|
| 0 | TELEPORT | `TeleportCharacter(target)` to this action node's transform (the action is a `PivotNode`); delayed a frame while grappling (0x855fb9) |
| 1 | SET_AI_STATE | `m_istateofmind = m_iinteger1` (0 PASSIVE, 1 AGGRESSIVE) on every `CharacterRoot` found under `m_etarget1` at initialisation |
| 2 | PLAY_SPECIFIC_ANIMATION | `command_play_specific_anim` (stops a forced state first) |
| 3 | FOLLOW_PIVOT | `CharacterRoot.command_follow_pivot(m_etarget2, m_nnumber1, ...)`: run to the pivot |
| 4 | KILL | `command_give_damage` with the full health |
| 5 / 8 | ACTIVATE / DEACTIVATE | `RecursiveSetCharActivationState(m_etarget1, true/false)` 0x85cd2d (5.2) |
| 9 / 10 | LOOK_AT_PIVOT / CANCEL_LOOKAT | head look-at |
| 11 / 12 | LEAVING / ENTERING_COMBAT_ZONE | `CharacterGroup.command_leaving_zone / entering_zone(activator)` |
| 13 | USE | makes the target use a use-trigger |
| 14, 15, 28 | FORCE_MOVEMENT_TYPE, STOP_FORCED_STATE, REQUEST_FORCED_STATE | forced AI states |
| 16, 17 | GIVE_HEALTH, GIVE_POWER | health += number; rage or electrify power by character type |
| 18, 19 | SET_AI_DEF, SET_AI_DEF_PHASE | switch the AI parameter sheet; select the def phase `m_iinteger1` for one root or every root of a group |
| 20, 21 | TUTORIAL_AI_PASSIVE / AGGRESSIVE | switch root behaviour |
| 22, 23, 24, 32 | SET_INCOMING_DAMAGE_FACTOR, SET_MIN_HEALTH, INVULNERABLE, DAMAGE_MODE | damage tuning members of the root |
| 25, 33 | RUMBLE_CHARACTERS_CONTROLLER, CAMERA_SHAKE | feedback on the target player |
| 26, 27 | SHOW_BOSS_HUD, HIDE_BOSS_HUD | |
| 29, 30, 31, 34 | SET_TWI_LADY_COMBAT_PARAMS, RESET_SPECIAL_MODE, DROP_WEAPON, FREEZE_ACTIVE_RAGDOLLS | |
| 6, 7 | SET / REMOVE_PRIORITY_LOOKAT_TARGET | no code (falls through) |

Other trigger classes, briefly (**read**: handler lists): `TriggerUse` / `TriggerUseFragment`
(doors, switches, ladders, lock picks: a nested fragment with activate / release actions, a
"frozen" flag and pin heights), `TriggerKill` (kill volume), `TriggerUniqueEffect` (collision
effect volume), `TriggerSendEnableDisable`, `TriggerStaticPathObj` (AI door edge cost),
`TriggerTutorial`, `TriggerFireBarrelEffect`, `TriggerOscillateBox`, `TriggerStopmodeWM` (editor).

### 5.2 How enemies are placed and activated (no spawner in Bordello)

- Placement: `CharacterRoot(PivotNode)` nodes under `CharacterGroup(Folder)` folders in
  `Enemies.fragment` (**data**: 56 groups, 165 roots: 92 DOMINATRICE, 36 GIMP, 23
  GIMP_WITH_GAGBALL, 14 TWILIGHT_LADY; `_tstartactivated` false on all). The node's transform is
  the spawn transform; `_icharactertype`, `m_istateofmind`, `_iweapontype`,
  `m_ipriorityweaponmodel` are per-placement.
- `CharacterGroup.initialize_external` (0x668a99) collects the roots below it
  (`m_einitialcharacterrootlist`) and enters `StateActive`.
- ACTIVATE on a target (`RecursiveSetCharActivationState` 0x85cd2d, **read**): a `CharacterRoot`
  gets `command_character_activate`; a `CharacterGroup` gets it for every root of its initial
  list; a `CharacterSpawner` gets it itself and the recursion continues into its children; any
  other node has `enabled` set (unless it is a `Folder`) and the recursion continues. DEACTIVATE
  sends `command_character_deactivate` the same way.
- Activation only registers the root with `CharacterLodCtrl`; the 16 nearest activated enemies are
  built (audit a12). The same placed enemy can be deactivated and re-activated by data.
- Group death: `CharacterGroup.StateActive` (0x668ded) calls `FireDeadActions` (0x66267e) once
  when no member is alive: `command_fire_action` on `_ealldeadaction`. In level data that reference
  points at a `TriggerConditionToggle` (5.1), so "group dead" becomes a latched condition.
- Combat zones: `m_ezonetrigger` (the property behind `key_0991b0d4`) is a collision box with two
  reactivatable conditions, LEAVE and ENTER by ANY_CHARACTER, whose actions send
  LEAVING / ENTERING_COMBAT_ZONE to the group; the group forwards to the character
  (`command_leaving_combat_zone`, 0x66873d), which makes it return to `_ereturntohometurfpoint` /
  `m_vreturnposition` (**data** on `mainHall_Bonus_door_04`; forwarding **read**).
- `CharacterSpawner` (respawning folder) exists and is read in the audit (a13); **data**: unused
  in Bordello.

### 5.3 Scene scopes, level load and transitions

- Data: `WatchMenPart2.scene` contains `GameEssentials` = `SceneScope(FragmentNode)` (scene id 20,
  root scope) with sub scope `MovieDbPart2`, and under folder `Scenes` six
  `SceneScope(LoadBlock)`: NightClub (7), StreetsOfRiot (8), Bordello (9), Tutorial (30),
  PlayerVsPlayer (40), MainMenu. Each has `assetName` = the level's top fragment, quad-tree
  bounds and movie references (`m_ecutscenemovie`, `m_eendcutscenemovie`, `m_eendcutscenemovie2`,
  `m_efinalcutscenemovie`, `m_ecreditsmovie`).
- `SceneScope.start` (0x813b0b): a scope without parent becomes `SceneCtrlLib.g_erootscenescope`
  and enters `StateActivate`; a sub scope registers with its parent and enters `StateDeactivated`.
- `SceneScope.StateActivate` (0x813bf5, **read**): if the node is a `LoadBlock` and none is
  loaded, `LoadBlock.Load(self, "callback_load_done")`; wait frame by frame until the callback;
  wait for `command_finalize`; `ApplyLoaded`; blocking mode on; `ProjectLib.InitializeHierarchy(self)`;
  blocking mode off; go to `StateActivated`. `StateDeactivate` (0x813f5d): `command_deactivate` to
  sub scopes, `DeinitializeHierarchy`, `MasterSceneCtrl.command_scope_unloading`, unload.
- `MasterSceneCtrl` (in `SceneControl.fragment`) sequences a level change
  (`StateActivateScene` 0x7a63b2, **read**: order of calls; branch conditions skimmed): show the
  load screen with a hint, `command_activate` the scope, optionally play the start cutscene
  (`StatePlayMovie`, not when restoring a checkpoint), wait for loading (`StateWaitForLoad`
  0x78f8dc), ask `StreamBlockManager` for a start stream block (none in this title),
  `SceneScope.command_finalize`, wait until `CharacterLodCtrl` has no incoming characters, then:
  - not restoring: `GameStateCtrl.command_reset_checkpoints`; restoring:
    `GameStateCtrl.restore_checkpoint`;
  - broadcast SCENE_ACTIVATED (1) with the scope as data;
  - broadcast SCENE_RESTARTED (4), or SCENE_RESTORED_FROM_CP (5) when restoring;
  - mute, wait, broadcast SCENE_STARTING (6), fade out the load screen, restore volume.
- Leaving a level: `MasterSceneCtrl.StateActive` broadcasts SCENE_DEACTIVATING (2) and
  SCENE_DEACTIVATED (3) around the scope's deactivation (0x78e3c1, call list).
- Level end: `LevelSceneCtrl` (one per level, in the level's top fragment) listens for LEVEL_END,
  GAMEOVER, GAME_COMPLETE_*, CHARACTER_DEAD (0x773c22). `StateEndMovie` 0x7743bb marks the scene
  complete (`GameStateCtrl.command_scene_complete(saveType, sceneId, save)`), plays the end movie
  under a pause request; `StateLevelEnd` 0x774993 shows the level-end menu and, on the last level,
  `command_game_completed`; `MasterSceneCtrl.command_load_next_level` 0x78dd5d loads the next
  scope. `StateGameOver` shows the game-over menu; "retry" is
  `MasterSceneCtrl.command_load_current_level(true)` = reload with checkpoint restore.

### 5.4 Game events

- `GameEventCtrl` (0x752a74): `command_register_gameevent_listener(id, entity)`,
  `command_register_gameevents_listener(entity)` (all events), `command_broadcast_gameevent(id,
  sender, iData, nData, eData)`. `BroadcastGameEvent` 0x74c677 flushes pending registrations, finds
  the listener list of the id and sends `command_game_event(id, sender, iData, nData, eData)` to
  each listener in registration order, synchronously. Registrations and removals made during a
  broadcast are queued and applied by `command_flush` (0x74c027). **read.**
- The enum has 56 values (JSON `game_events.enum`). Senders and listeners recovered from the
  lifted text (**data**, heuristic: constant found within 40 lines before the send; incomplete):

| id | name | sent by | listened to by (excerpt) |
|---|---|---|---|
| 1 | SCENE_ACTIVATED | `MasterSceneCtrl.StateActivateScene` | cameras, `CharacterLodCtrl`, `CharacterRoot`, `PlayerManager`, `SoundCtrl`, `SpeakCtrl`, `MusicIntensityCtrl`, `PhysicsSimulation`, level data |
| 2, 3 | SCENE_DEACTIVATING, SCENE_DEACTIVATED | `MasterSceneCtrl.StateActive` | achievements, HUD, menus, `GroupManager`, `CombatOrchestrator`, `StreamBlockManager` |
| 4, 5 | SCENE_RESTARTED, SCENE_RESTORED_FROM_CP | `MasterSceneCtrl.StateActivateScene` | `AchievementCtrl`, level data |
| 6 | SCENE_STARTING | same | - |
| 101, 102 | LEVEL_END, GAMEOVER | level data (`TriggerActionGameEvent`), `LevelSceneCtrl` | `LevelSceneCtrl` |
| 105 | GAME_COMPLETE_NITE_OWL_WON | `CharacterRoot.DecreaseHealth` | `LevelSceneCtrl` |
| 201 | CHARACTER_DEAD | character death (audit j2) | `LevelSceneCtrl`, `PlayerCtrl` |
| 203 | CHARACTER_DAMAGE_RECEIVED | `CharacterRoot.DecreaseHealth` | `PlayerCtrl` |
| 204-207 | CHARACTER_PLACEHOLDED_IN/OUT, SUBSYSTEMS_CREATED / DELETING | `CharacterRoot` | `CharacterRoot` |
| 300, 301 | PLAYER_CTRL_ACTIVATED / DEACTIVATED | `PlayerCtrl` | `CharacterLodCtrl`, `SpeakCtrl`, rain FX |
| 400 | CHARACTER_CAMERA_ACTIVATED | `CharacterCamera` | `FXLighting` |
| 500-502 | TRIGGER_THRESHOLD_* | `TriggerCounterScript` | level data |
| 600 | CUTSCENE_DONE | `MoviePlayerCtrl` | level data |
| 610-615 | settings / menu events | menus, `InputCtrl` | `CharacterCamera`, `GameStateCtrl` |
| 106-112 | PLAYER_VS_PLAYER_* | combat code | `PlayerManager` |
| 700-715 | UNDERBOSS_* | underboss scripts | level data |

### 5.5 Checkpoints and saves

- Registration: `TriggerActionCheckpoint.initialize_local` (0x85d2fd) registers `(id, self)` with
  `GameStateCtrl` (`_icheckpointidlist`, `_echeckpointlist`).
- Reaching (0x74f382, **read**): unless in trial mode, `_ilastsessioncheckpointid = max(itself,
  id)`; if the current scene is the last playable scene of the save type,
  `LevelProgressState.m_ilastcheckpoint[saveType] = max(itself, id)`; then `command_save(1)`
  (LEVELPROGRESS). Ids therefore must increase along the level; Bordello uses 901 ... 999.
- Restoring (0x74f5f1): find the registered checkpoint whose id is the session checkpoint id and
  send it `command_restore_checkpoint`, which fires **its child actions**. The level has just been
  loaded from scratch (5.3), so the children are a hand-written script that re-creates the state:
  teleport both players, disable the checkpoint's own trigger and earlier triggers, deactivate
  earlier groups, activate the groups of the next encounter, set music, set the combat
  orchestrator level (**data**, section 6). No object state is saved.
- Save type index: 0 Rorschach, 1 Nite Owl, 2 co-op with player 1 as Rorschach, 3 co-op with
  player 1 as Nite Owl (`ProjectLib.GetSaveGameType` 0x7fe24c).
- Save file format (**data**, both files decoded completely; `SaveData/Profile1`):

```
u32 5, "KPWF", u8 0, u32 2, u32 titleChars, UTF-16LE title (NUL included), u32 payloadBytes
records: [u32 entity fragmentID][u32 property name hash][u32 type id][u32 nWords][nWords x u32]
```

  The record is the fragment reader's typed mode with the entity id in front; the type id is the
  hash of the type name; values use the fragment encodings (`list` = count then elements).
  `PROGRESS.kpw` ("Checkpoint Save Data", 992 payload bytes) holds the ten properties of the
  `LevelProgressState` node (fragment id 0x9b677b3b in `GameState.fragment`):
  `m_blevelcompletelist` = `[[7,8,9],[7,8,9],[7,8,9],[]]` (completed scene ids per save type),
  `m_ilastcheckpoint` = `[999,999,999,0]`, four statistics counters,
  `m_itutorialsseenlistlist`, and two ability lists (2 x 42 truths).
  `SETTINGS.kpw` ("User Settings") holds the 22 properties of `SettingsState` (0x163975ae):
  brightness, contrast, gamma, saturation, volumes, subtitles, sensitivities, controller names,
  the button map (675 words: `list(list(list(list(integer))))` = [6 save devices][2 players][41 logical buttons][3 codes], −1 = no code, a player without a map has no buttons; `savemeta` names it as `decoded.button_map`) and two camera-inversion lists.
- So a checkpoint restores: which level, which checkpoint id, and the global progress (abilities,
  tutorials seen, counters). Health, rage, weapons, dead enemies and door states are not stored;
  they come back as whatever the checkpoint's child actions and a fresh level produce.
- `Entity.recordInSavepoints` (0x511603) and `SceneNode.flushrewind` / `rewindResumeTime` exist
  natively: an engine-level savepoint / rewind facility. It is not what the game's checkpoints
  use (**read**: the script path above); whether anything uses it is not established.

### 5.6 Cutscenes, movies, sequences

- Movies: `TriggerActionMovie` (level data) and the scope's movie references; both play a
  `MoviePlayerCtrl` under a pause request and continue afterwards. CUTSCENE_DONE is broadcast by
  `MoviePlayerCtrl.StateActive`.
- In-engine cutscenes are camera tours: `TriggerActionCamera` with a `PropertySequenceNode`
  (a `.sequence` asset animating camera nodes) and child camera cuts timed by `_ndelay`; scripted
  character motion during a tour is `TriggerActionCharacterForceMove` and FOLLOW_PIVOT; players
  are locked and set PASSIVE, then released by the tour-end action.
- Doors and props: `PropertySequenceNode` started by `TriggerActionGeneral` START_SEQUENCER.

### 5.7 Game modes and co-op

- `ProjectLib.GetGameMode` (0x7f09db): `g_igamemode` if set, else `g_ioverridegamemode`, else 1.
  Values: 1 RORSCHACH, 2 NITEOWL, 3 COOP, 4 MAINMENU. `OverrideGameMode` nodes set the override
  for editor runs. The mode is chosen in the menu before a level is loaded.
- `PlayerManager.command_game_event` (0x7f9d1b) reacts to SCENE_ACTIVATED: resets HUDs, sets the
  number of sound listeners, activates one or two `PlayerCtrl`s on the playable characters
  according to the mode, and changes the faction of the character that is not player-controlled
  (it becomes the AI partner). **read** (call list only).
- Level data branches on the mode with `TriggerConditionGameMode` / `TriggerActionGameMode`
  (flags) and `GameModeSelector`.
- No drop-in join was found: nothing switches a running level from single player to co-op
  (**inferred** from the above; the menu scripts were not read).
- Slow motion is suppressed in co-op (3.6).

---

## 6. Worked trace: Bordello, the main hall

All **data** unless marked; node ids are fragment ids. Full tables in the JSON (`bordello`).

### 6.1 Blocks and fragments

- Blocks: the common block and `bordello.block_h_z` (55.1 MB) / `bordello.block_s_z` (84.9 MB);
  loose `bordelloaipath.hpd`; movies `cutscene10a/10b/11/12a/12b.bik` (that these five belong to
  this level is **inferred** from the action named `Cutscene10B`).
- Scope: `Bordello` `SceneScope(LoadBlock)` #b98b9e6f, scene id 9, bounds x -56..51, z -173..32.
- Fragment tree (header name; singleton; nodes):

```
Bordello.fragment                ("Bordello", singleton, 19 nodes)
  SceneSettings, LevelSceneCtrl (+5 disabled Character nodes: player models), KillNode
  Art.fragment                   (singleton, 51)  -> sky, 25 PVS/*.fragment (rooms, culling), use-trigger resources
  gameplay.fragment              ("Bordello_Gameplay", singleton, 185)
    AIWorld + 19 seed points, Doors (41 TriggerUseFragment, 28 door FragmentNodes)
    Gameplay/Enemies.fragment        ("Bordello_Enemies", singleton, 1156)
    Gameplay/MissionStructure.fragment   (460)   checkpoints, area logic, ladders
    Gameplay/Cameras.fragment        ("Bordello_Cameras", singleton, 503)  cutscene cameras and their action trees
    Gameplay/PartnerAI.fragment      ("Bordello_PartnerAI", singleton, 535)
    Gameplay/Collision.fragment      ("Bordello_Collision", singleton, 226)
    Gameplay/Players.fragment        ("Bordello_Player", singleton, 3)   the two player CharacterRoots
    Gameplay/RORvsNO_EndBattle.fragment  (114)
  Sound.fragment                 (312) -> Sound/MusicSetup_level_Bordello.fragment (252)
  CharacterDB folder: AllBodelloTypes.fragment (singleton, 1200: Dominatrices, Gimp, GimpGagBall, BordelloFace),
    AnimationClassEnemy04 / Enemy04Face / EnemyBig / Enemy01Face, TwilightLady.fragment
```

- The level has 14 checkpoints: 901 (after the intro tour, in `Cameras.fragment`), then 910, 920,
  930, 940, 960, 970, 980, 990, 995, 996, 997 on player-enter trigger boxes in
  `MissionStructure.fragment`, and 998, 999 fired by actions before the boss fight and before the
  final player-versus-player fight.

### 6.2 The encounter

Five groups in `Enemies.fragment` under `Area_D_MainHall` (#e63b3f7d), floor height y = 8:

| group | id | members (type, x, z) | start state |
|---|---|---|---|
| `mainHall_guards` | e63b55f4 | GIMP (-2.5, -12.3), GIMP (2.0, -11.9) | PASSIVE |
| `mainHall_Rightside_01` | a4bf8de2 | GAGBALL (22.9, -14.4), GAGBALL (25.2, -14.3) | AGGRESSIVE |
| `mainHall_Rightside_02` | c50bb1e4 | GAGBALL (23.3, -20.4), DOMINATRICE (25.1, -20.0) | AGGRESSIVE |
| `mainHall_LeftSide` | 851c6a4d | DOMINATRICE (-23.0, -26.3), GAGBALL (-24.7, -14.7), DOMINATRICE (-23.1, -14.5) | AGGRESSIVE |
| `mainHall_rushers` | a6421889 | DOMINATRICE (-27.3, -20.7), GAGBALL (-23.8, -20.7), DOMINATRICE (-25.5, -20.8) | AGGRESSIVE |

Trigger graph, in play order:

1. **Checkpoint 920.** `CheckPoint03_Collision` box at (-0.1, 9.9, -34.0), condition ENTER by
   PLAYER, action `CheckPoint03` (id 920). Reaching it only saves.
2. **Start.** `MainHall_TRIGGER` #847bbdc9 in `Cameras.fragment`, box 18.0 x 6.6 x 4.7 at
   (-0.5, 8.4, -33.1), condition **LEAVE** by PLAYER. Actions: ACTIVATE the `TwillligthLady`
   group and make her invulnerable; a delay node that after 0.5 s plays the movie `Cutscene10B`
   and then (aux action) runs `Cam_MainHall`, and after 1.2 s opens door `MainHall08`.
3. **`Cam_MainHall`** #d73d8987: a skippable camera tour (five cameras, players locked, enemy
   attacks paused) and a delay node with 16 timed children: force-move the Twilight Lady (0.4 s)
   and both players (1.0 s); ACTIVATE `mainHall_guards` (3 s); ACTIVATE `mainHall_Rightside_01`
   and `_02` (9 s); ACTIVATE the Twilight Lady group and invulnerable (10 s); close the entrance
   door (10 s); open doors `MainHall06` / `07` (11.3 / 11.7 s); FOLLOW_PIVOT run-in targets for the
   four right-side enemies (11.7 / 12 s). The tour-end action sets both players AGGRESSIVE.
4. **Mid.** Each group's `_ealldeadaction` is a `TriggerConditionToggle`. The toggles of guards,
   Rightside_01 and Rightside_02 sit under `SomeDeadRightSide` #a68c96c5
   (`TriggerConditionLogical`, SOME, count 2). When two of those three groups are dead it fires:
   ACTIVATE `mainHall_rushers` at once, and a delay node: ACTIVATE `mainHall_LeftSide` (0 s),
   camera `Cam_MainHall_rushers` (0.3 s), doors `MainHall01/02/03` (0.7 / 1.0 / 5.0 s),
   FOLLOW_PIVOT run-ins for the five new enemies (0.9 - 5.2 s), attack shouts.
5. **End.** Each of the five group toggles has a child `{act_BASE}` whose aux action is a second
   toggle under `AllDead` #892cd64b (`TriggerConditionLogical`, ALL). When all five are set it
   fires: USE_TRIGGER_UNFREEZE on the double door #61789cbe at (0.0, 8.0, 0.7), which lets the
   players leave the hall, and camera `Cam_MainHall_ShowGate`, whose tree enables the two bonus
   door triggers (`mainHall_Bonus_door_04/05_TRIGGER`, disabled until then, each activating a
   bonus group with a combat zone) and sends the Twilight Lady on with a taunt.
6. **Clean-up.** `DeactivateEnemies` #c8a7feb7 (called from a door's activate action) and a
   logical condition on both players' positions DEACTIVATE the hall groups and freeze active
   ragdolls once the players are upstairs.
7. **Checkpoint 930.** Box at (-0.1, 17.9, 3.3) on the upper floor.

What a restore at 920 does (children of `CheckPoint03`, fired after a fresh load): close two
doors, disable the checkpoint box and `MainHall_TRIGGER` (so the cutscene does not replay),
teleport Nite Owl to (0.6, 8.0, -19.9) and Rorschach to (1.9, 8.0, -19.8), deactivate the entrance
group, set both players AGGRESSIVE, set the music setup, TRIG a node inside the game-essentials
"Combat Orchestrator Parameters" fragment (named "Level 005": the orchestrator parameter set of
this area), run the tour-end action, and a delay node that repeats the encounter's opening without
the tour: doors, the four run-ins, ACTIVATE guards, Rightside_01, Rightside_02 and the Twilight
Lady. The ACTIVATE actions under the checkpoint have the **same node ids** as the ones under
`Cam_MainHall` (e.g. #f73f756e in both files): the designers copied the subtree.

---

## 7. Extractor consequences

1. **Fix key `0x0991b0d4`**: name `m_ezonetrigger`, type entity. Removes the last 22 unknown-key
   occurrences in the corpus and makes combat zones visible (2.6 row 8).
2. **Fragment header fields**: expose `singleton`, `smartSelectable`, `fragmentName`,
   `reapplyable`, `chunkCount` (2.1) instead of an opaque header.
3. **Reference resolution** (2.3, 2.6): implement tag 5 through a singleton index
   `hash(fragmentName or file base name) -> file`, tag 4 with `a`, and the engine's search rule.
   This makes every cross-file reference in a level resolvable; today they print as raw id paths.
4. **Accept `.scene`** in `kapow_json.load_fragment`.
5. **`levelmeta` export**, one JSON per level, built from the scope's top fragment by splicing
   every `FragmentNode`:
   - `level`: scene id, scope node, quad-tree bounds, block files, movies;
   - `fragments`: path, header name, singleton, node count, host node and its world transform;
   - `placements`: every `CharacterRoot` (id, group, character type name, world position, yaw,
     state of mind, weapon type, priority models) and every prop / door / use-trigger host with
     world transform and fragment path;
   - `groups`: id, name, area folder, members, all-dead target, zone trigger box, return point;
   - `volumes`: every collision box / sphere / capsule used by a condition, with size and world
     transform;
   - `conditions`: id, class, parameters with enum names, parent condition, ordered action list;
   - `actions`: id, class, action type name, resolved targets, delay (from the parent delay node's
     slot), children, aux action;
   - `checkpoints`: id, trigger volume, player teleport positions, restore action list;
   - `cameras`: camera tours with their `.sequence`, cut times and cameras.
   World transforms need the parent chain including the host transforms (a nested fragment's nodes
   are children of the host). A derived `encounters` view (start trigger, groups, waves, end
   condition) can be computed from groups + toggles + logical conditions as in section 6.
6. **Enum names** for `m_iactiontype`, `m_itrueon`, `m_iactivator`, GAME_EVENTS, SCENE_ID in
   fragment JSON (the enums are already in `engine_enums.json`).
7. **Save files**: a `watchmen save` reader for `*.kpw` (5.5) is 30 lines and uses the fragment
   value decoders.
8. **Language slots**: document slot 0..5 = English, French, Italian, German, Spanish, Danish
   (4.6) and name the `--language` values.
9. **Not extracted**: `AIAsset` path data (`.hpd` / `.aipathdata`). The AI world's source
   parameters and seed points are in `gameplay.fragment` (`AIWorld(AIWorldNode)`), so a nav-mesh
   could be rebuilt from collision instead of decoding the Kynapse format.
10. **Character spawn recipe** for the character exporter: a character is
    `CharacterRootTemplate_<kind>.fragment` + `<kind>CharVisual.fragment` selected through the
    `CharacterDef` (`m_echaracterfragment`, `m_emodelfragment`); the 11 `reapplyable` files are the
    complete list of run-time-instanced fragments.

---

## 8. Not established

| item | what it would take |
|---|---|
| Allocation of entity-table indices (lowest free first?) and hence the exact script order after deletions | read the entity constructor path that writes manager+0x14 (search for stores to `[DAT_00e15124+0x14]`) |
| `Node::SetLogicalParent` / `SetSiblingOrder` insertion rule (ties, missing orders) | read the two setters named in 0x494142 |
| Tag-4 references with `a > 1` at first load | read where the path object's level field is initialised (0x4f91c9) |
| Virtual slots 20, 26 and 29 of `Node` beyond `PivotNode` / `Character` | read the overrides (0x498055, 0x4c30c9, 0x49413d is not in the dump) |
| Identity of the three calls between the native lists (0x5427a6, 0x529f71, 0x50305c) | read 0x53fee6, 0x5231de, 0x4fecc6 |
| Condition under which collision-family nodes take `FrameUpdate` (0x48181e) | read it |
| Native savepoint / rewind facility (`recordInSavepoints`, `flushrewind`) | find callers of the two accessors |
| Asset reference counting on unload, and which assets stream | read `LoadBlock::Unload`, 0x548abe and the request producers of 0x4e0e5d |
| Block header fields beyond those the toolkit documents (the loader object's +0x15c..+0x1c0) | map the 400-byte header reader 0x49dd0e against the loader fields |
| `kind` of a command record (+0x10: 1 or 3) | read 0x47c752 (table resolution) |
| Branch conditions inside `MasterSceneCtrl.StateActivateScene` and `StateActive`; `PlayerManager.command_game_event`; whether co-op can be joined mid-level | line-by-line reading of 0x7a63b2, 0x78e3c1, 0x7f9d1b and the menu scripts |
| Game-event table completeness (senders found by a 40-line heuristic; CHARACTER_DEAD sender missing) | argument tracking in `lift.py` for `command_broadcast_gameevent` |
| `TriggerActionDelay` children beyond the 20th (fire immediately, **inferred** from the shape of 0x852ecd) | disassemble the loop |
| `TriggerUse` (100 handlers) and `TriggerActionCharacterForceMove.RunningState` details | read them; not needed for the export |
| The numbering of the codes in `m_emetadevicebuttonmap` | the shape is settled (type id 0x2bf20fb4 = `list(list(list(list(integer))))`: save device `SAVE_DEVICES` 0–5, resized in `SettingsState.initialize_local` 0x82bc77; player, `GameStateCtrl.command_has_any_input_map` 0x74d04e; logical button 0–40 and three alternative codes inferred from the content of one profile). Keyboard codes look like DirectInput scan codes (MENU_UP 200, MENU_DOWN 208, MENU_SELECT 28, MENU_BACK 1; not read from the game's code); pad buttons 0–15 and the 257+ codes are not established |
| Which movies belong to which level | read `MovieDbPart2.fragment` and resolve the scope's movie references |
| Everything about Part 1 levels (extracted `Game_Levels` folder) | same analysis; the scripts are shared |

## 9. Files

- `findings/wp5_runtime.md` (this), `findings/wp5_runtime_tables.json`.
- `work/wp5/`: `cond.py` (condensed view of a lifted class), `summ.py` (per-handler send list),
  `hn.py` (hash annotator), `khd.py` (name hash), `game_events.json`, `node_rtti.json`,
  `frameupdate_classes.json`, `lb_sm.c` (load block state machine text), `msc_activate.c`.
- The data scripts ran on the user's PC in a scratch directory outside the mounted folder and
  were removed afterwards; they only used `kapow_json.load_fragment` plus the header layout of
  section 2.1 and the save layout of section 5.5.
