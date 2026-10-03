# Topic B — "joint blob types 4 and 5" in .model node records

Evidence tags: **[code]** read from the exe (capstone; the functions are SEH stubs in the Ghidra dump), **[data]** verified on the
extracted game files (read-only, device tool), **[inferred]**. Table: `findings/skeleton_blobs_layout.json`. Scratch: `work/skel/`.

## Result in one paragraph

The records our docs call "EmbeddedJointNode joints, types 4/5/6/7" are not joints. They are the node's **collision volumes**
(`kernel/collision/volumes/*.cpp`): type 2 concave mesh, 4 convex mesh, 5 box, 6 sphere, 7 capsule. A node carries **two** volume lists
(one per PhysX scene) followed by a third, always-empty list — the "[u32 0][u32 0] terminator" in our layout is the second list's count
and the third list's count. The "blob" is a cooked PhysX mesh and exists only for mesh types (type 4 → `NXS\x01CVXM…`). Records are
not a fixed 48 bytes: only the capsule happens to be 48. With the engine layout, 2003 of 2004 mesh-free node regions in all 1475
`.model` files tile exactly **[data]** (old `parse_node_aux`: 1743).

## Reader

`Node::Deserialize` 0x545927 (entry `mov eax,0x9c3e49; call 0x991850`). After the mesh-binding lists and the one-byte flag
(0x545bd9, node+0x30 object if 1) **[code]**:

    0x545c7f  for list in (node+0x4c, node+0x58):              ; loop counter [ebp-0x10] = 2, stride 0xc
    0x545c8f    count = u32                                    ; 0x435459
    0x545c98    resize(list, count)                            ; 0x54175c, element size 0x24
    0x545cbe    vol   = CreateVolume(stream)                   ; 0x524b23  -> element+0x00
    0x545cd3    pos   = read 12 bytes                          ; 0x4354a8  -> element+0x04
    0x545ce8    quat  = read 16 bytes                          ; 0x4354d1  -> element+0x14
    0x545cfc    blobLen = u32
    0x545d05    if blobLen: buf = alloc; read(buf, blobLen); 0x519392(vol, MemStream(buf)); free(buf)
    0x545d9a  count3 = u32; resize(node+0x64); each element (0x28 bytes): vtable+8 deserialize

`CreateVolume` 0x524b23: reads `u32 type` and switches (`dec eax` chain): 2 → 0x5242f6, 4 → 0x52435f, 5 → 0x522d36,
6 → 0x522e49, 7 → 0x522f16; any other value returns null. Each constructor calls the base constructor 0x522b91 (stores the type at
object+0x1c) and then the class's stream reader (vtable slot 2).

## Record layout (all types)

| field | size | notes |
|---|---|---|
| type | u32 | 2, 4, 5, 6 or 7 |
| base field | u32 | `CollisionVolume::Read` 0x521243 → object+0x18. 0 in all 934 records **[data]**; meaning not established |
| type-specific data | see below | |
| local position | f32 × 3 | volume centre in the node's (bone's) frame → element+0x04 |
| local orientation | f32 × 4 xyzw | → element+0x14; unit length in all records **[data]** |
| blobLen | u32 | |
| blob | blobLen bytes | consumed only for types 2 and 4 (0x519392 switches on object+0x1c) |

Type-specific data **[code]**:

| type | class (vtable) | reader | data | notes |
|---|---|---|---|---|
| 2 | ConcaveCollisionMesh (0xa2f3d0) | 0x5212e1 → mesh sub-object (vtable 0xa2f4cc) 0x521341 → 0x40b7df | `u32 mode`, `u32 nVerts`, `nVerts × f32[3]`, `u32 nIdx`, `nIdx × u32` | `mode == 1` → triangle list (`nIdx/3`), else `nIdx − 2` triangles (0x522d17). Blob → 0x515a04 → `NxPhysicsSDK` vtbl+0x20 (create triangle mesh, **[inferred]** from the slot), cached by id |
| 4 | ConvexCollisionMesh (0xa2f450) | same as type 2 | same as type 2 | Blob → 0x515ca9 → `NxPhysicsSDK` vtbl+0x48 (create convex mesh). Blob starts `4E 58 53 01 43 56 58 4D` = "NXS\x01CVXM" **[data]** |
| 5 | CollisionBox (0xa2f380) | 0x521396 | `f32 x, y, z` → +0x24, +0x28, +0x2c | **full** extents: AABB method 0x5213c7 returns ±0.5 × size (0x9e5dc8 = 0.5) |
| 6 | CollisionSphere (0xa2f3a8) | 0x521c3f | `f32 radius` → +0x24 | AABB 0x521c5b = ±radius |
| 7 | CollisionCapsule (0x9fbd88) | 0x52213d | `f32 a` → +0x24, `f32 b` → +0x28 | `a` = diameter (X and Z extents ±0.5a), `b` = total height along local Y (±0.5b), from AABB method 0x522164; debug mesh scale 0x5221cc = (a/1.0, b/3.0, a/1.0) with the unit capsule constants at 0xc8c814 / 0xc8c818 |

Record sizes without blob: sphere 44, capsule 48, box 52, mesh 8 + 4 + 4 + 12·nVerts + 4 + 4·nIdx + 28 + 4.

What our field names really are (capsule case): `[type][0][pos.x][pos.y][pos.z][a][a'][quat]` = `[type][base][diameter][height][pos.x][pos.y][pos.z][quat]`.
So for the female "breast pair on Spine2" our "anchor (0.143, 0.243, −0.189), a = ∓0.095, a' = 0.024" is a capsule of diameter 0.1429,
height 0.2428 at local position (−0.1887, ∓0.0953, 0.0237).

## The two lists

Accessors `FUN_004f922b` / `FUN_004f9252` / `FUN_004f927a` (volume / position / orientation) index
`model.nodes[node] (stride 0x74) + 0x4c + list × 0xc` **[code]**. The consumer at 0x5073eb (rigid-body shape building in
`physx_rigidbody.cpp`) uses `list = [body+0x8c]`, and the same field indexes the scene array in the actor-creation code
(0x507205: `[0xe1528c] + idx×4 + 0x30`) **[code]** — so list 0 holds the shapes for PhysX scene 0 and list 1 those for scene 1.
What each scene is used for in game terms (main world vs. a character/ragdoll scene) is **[not established]**.

Corpus **[data]**: list 0 — 17 convex meshes, 82 boxes, 51 spheres, 543 capsules; list 1 — 41 boxes, 200 capsules; third list always 0.
`Female_Skeleton.model`: 30 volumes on 16 bones, all in list 0 (capsules on spine/limbs/head, a sphere on each upper arm, boxes on hands and feet).
`Small_Skeleton.model`: 17 convex meshes (10–32 vertices, cooked blobs 1.3–7.7 kB). `Fimale_Gimp_Hair.model`: both lists populated.

## Relevance

- **Bind pose / hierarchy / export: none.** The node transform and parent index precede this data; `parse_model_nodes.parse()` does not read it.
- **Skinning: none.** These are physics shapes (hit and ragdoll collision), useful only if collision geometry is ever exported.
- **Jiggle: the records are not jiggle joints.** `jiggle_d6.joint_frames()` reads the capsule orientations as "D6 swing axes"; that
  interpretation is wrong. The real jiggle joint is created at run time with the parent bone's frame (see `findings/jiggle.md`).
  It only feeds the rejected `mode='aniso'`, so no shipped output depends on it.

## Proposed toolkit change

1. `wlib/parse_model_nodes.py: parse_node_aux` — replace the fixed 48-byte joint loop with the engine layout: two volume lists,
   per-type data as in the table, then the third count; return `{'f1','parent','volumes': [list0, list1]}` with entries
   `{type, base, params, pos, quat, blob}`. Reference implementation (validated on the corpus): `work/skel/vol_parse.py`.
   Keep a `joints` alias only if a caller still needs it.
2. `wlib/jiggle_d6.py: joint_frames` — remove, or rename and document as "collision capsule frames"; delete the `jointframes_v2_*`
   cache use. Not needed by `mode='engine'`.
3. Docs: replace "EmbeddedJointNode joint records" by "node collision volumes"; types 4/5 are closed.
4. The existing unit test `test_v120_regressions.py` case 9 builds a synthetic region in the old layout and must be regenerated with it.
