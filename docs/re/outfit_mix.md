# Outfit copy at spawn and a per-part mix (static, PC exe)

How a spawning character gets its outfit from a `CharacterModelCollection` member, and what an add-on needs to give it a
mix of parts from several members instead (a per-part randomiser). Static reading of `KapowMultiDEDRM.exe` only; nothing
here has run in the game. Tags: **[code]** read from code (addresses), **[docs]** from another doc, **[inferred]**,
**[not established]**. Checked byte for byte: the 0x69CEF8 signature, the 0x4B28D1 / 0x4B5FF7 bodies, the physicsType registration (0x4AC9E6),
0x69E386 and the slot 0 read at the head of 0x4C2BBF.

## Summary

- The engine copies an outfit **by names and by one string**, not by resource pointers: `CopyModelResSettingsFromCharacter`
  0x4B28D1 sets the visual's `modelNames` from the member's list, its texture-sheet description from the member's
  string, copies +0x150, then rebuilds [code].
- `SetModelNames` 0x4A52B0 resolves **each slot on its own** through the AssetManager (one ref-counted handle per slot)
  [code]. A mix is therefore the same setters with different inputs: a name list whose element k comes from member X_k,
  and a version-2 description holding X_k's records for slot k.
- The head is a separate character chosen by HeadCtrl `_imodelindex` (members +0xE8), read later by `command_activate`
  [code].
- A name already resident is reused; nothing loads [code]. Every member's parts are in the loaded level block [inferred].
- One hook: retarget the rel32 of `call 0x4B5FF7` at 0x69CF11 (no stolen instructions), before the render objects exist.
- Parts bind to the skeleton **by bone index, through slot 0 only** (one shared palette, no name lookup) [code]. Parts the
  game already renders on the same slot 0 skeleton (Female_Skeleton.model for every Dominatrix) can be combined; mix only
  between members with the same slot 0 name.

## 1. Spawn path

`CharacterRoot::InstantiateSubSystems` 0x67884E (esi = the root's members) [code]:

```
678cad mov eax,[esi+0x18]        ; m_iprioritymodel
678cb0 mov ecx,[esi+0x14]        ; definition entity
678cba push 0x8e4768bc           ; command_get_override_model (registration 0x66f1f9 -> 0x666d03)
678cc5 call 0x4f99a4             ; result -> [esi+0x214]
678ce4..678d0e A = B = (member != 0); A forced 1 for type 1 / 0x19
678d16 args = {member, A, B, root}
678d1c mov ecx,[esi+0x24]        ; CharacterVisual
678d38 push 0x0fde4b8c           ; command_set_override_model (registration 0x6d40e6 -> 0x69c8e3)
678d3f call 0x596d91
```

0x666D03 forwards to the collection (members +0x10) with `command_get_model` (0x8EF730FA -> 0x66CA15), else asks
`LevelSceneCtrl`. Hash 0x0FDE4B8C appears only at 0x678D39 and its registration: the only sender [code].
`command_activate_model` later sends HeadCtrl `command_activate` (0x5C5D4DD5) at 0x69E82C [code].

## 2. `command_set_override_model` 0x69C8E3 and `CopyModelResSettingsFromCharacter` 0x4B28D1

0x69C8E3 [code]:
1. Finds child "HeadCtrl", stores it at the visual's members +0x0C (0x69C92F).
2. With B != 0 (0x69C963..0x69CBDD): walks the **member's own** `modelNames` (+0x19C) and sets every name containing
   "Head", "Eye", "head", "eye", "gimpmask" or "GimpMask" to "" through the list(string) type info [0xE1693C] vfunc +0x60
   op 0xB (op 0xB = set element: [inferred] from its operands {index, "", &list}). This **changes the collection member
   for good**: a member already dealt out has blanked head names, one never used has not. Why [inferred]: the head is
   drawn by the separate head character; leaving head / eye meshes in the body list would draw them twice.
3. Reads the member's `m_iHeadModelType`; non-zero -> sends 0xF89876C0 `command_set_character_model_id` 0x662728 to
   HeadCtrl, which stores it at members +0xE8.
4. With B != 0, at 0x69CF11: `0x4B5FF7(ecx = visual, &member)`, which casts to Character (0x4AF5C6) and calls 0x4B28D1.

0x4B28D1 (this = visual, arg = member) [code]:

```
4b28d9 save byte [[0xe15124]+0x31]; 0x4ebe09(1)        ; defer the rebuild
4b28f8 0x4980f0(dst, &src+0x19c)                        ; SetModelNames
4b28ff src.0x49f95e() -> 4b2907 dst.0x49d26c(str)       ; Get / SetTextureSheetsDescription
4b2914 dst.0x49cbc4([src+0x150])
4b2922 restore the flag (0 -> flush 0x545fd9); 4b2929 0x47a9fd(dst)   ; invalidate -> vfunc +0x74 Rebuild 0x4c30c9
```

For Character, 0x4980F0 = vtable 0xA0A91C slot +0xB0 = 0x4C64F2 -> 0x4A52B0, then 0x4C2F3E (per-bone array at +0x360).
0x4A52B0, per name: handle {res, owner = this} (0x49ED32), resolve (0x49B380), strdup 0x4059F3; then assigns +0x190
(0x49ACAA releases the old handles) and +0x19C (0x4E63F5). The input list is read, not kept: `[list] -> storage`,
`[storage+4] -> char*[]`, count `[list+4] & 0xFFFFFF` [code].

Character layout [code]: +0x190 handle array (8 B per slot: ModelRes*, owner), +0x194 slot count & 0xFFFFFF;
+0x19C / +0x1A0 names list; +0x1A8 / +0x1B0 / +0x1B4 sheet table (count / keys / TextureSheet*); +0x1DC / +0x1E0 stored
description {len, char*}; +0x150 an int copied from the source (meaning not established).

0x4B28D1 takes one source, but the setters under it take any list or string and resolve per slot, so a list built from
several members is accepted by the code [code]; that the result renders right is [inferred].

## 3. Head

- HeadCtrl +0xE8: written only at 0x662736, read only at 0x669616 (`command_activate`), in a scan of 0x660000..0x674000
  [code]; other ranges not scanned.
- `command_activate` 0x669496: the definition's collection -> its head collection (0x6ED452D4) -> `get_model_by_id(+0xE8)`
  (0x8FFD39D) -> copies that head member into the head character (+0x64) with 0x4B5FF7 at 0x6696E5 [code]. Head mesh and
  head sheets come from the head collection node.
- `m_iHeadModelType` string used only at 0x66CC11 and 0x69CBEC [code]. Face animation class: the HeadModel's own
  controller in the CharVisual fragment [docs: face.md].
- Head from member B: write B's head type (member members +0) to HeadCtrl +0xE8 after 0x69C8E3, before
  `command_activate_model`. Hair and skin pairing is a data rule (afro hair with head type 23).

## 4. Texture sheets

- Per spawn: 0x49F95E returns the member's stored +0x1E0 string when +0x1DC != 0; otherwise it serialises the member's
  table as "2," + "%d,%d,%d,%s,%s," records **and stores it on the member**. 0x49D26C copies the string into the visual
  and clears the visual's table (0x49AA4E) [code].
- Rebuild 0x4C30C9 -> 0x4A9304 -> 0x4A913E: every slot / part / LOD / mesh gets the first sheet of its texture, then the
  stored description is applied by 0x4A6ED7 (version 2 -> 0x4A56C2), then the render objects are built (0x4C31C3 ->
  0x48D35D -> vfunc +0x94 = 0x4CA09F) [code].
- The visual owns its table, keyed by its own slot numbers; only TextureSheet pointers are shared [code].
- 0x4A56C2 bounds-checks each record against the visual's slot count, part count and max LOD (0x4A5773) and applies it
  only to meshes of that slot whose texture path matches (0x42536E) [code]. So B's part in slot k plus B's slot-k records
  makes that part wear B's sheets (e.g. the black-skin body sheet) [inferred].

## 5. Residency

0x49B380 -> AssetManager 0x55243F -> lookup 0x54BA59 returns an existing resource with data size > 0 as is (counter +0x64
+1); nothing loads [code]. With asset blocks in use (`[0xE14605]`), a path no loaded block lists cannot load on its own
(log line at 0x5524F5, asset stays empty) [code; KAPOW_NAZ_FORMAT §2.4]. The game renders every member's kit as members
are dealt out, so all members' parts are resident while the level block is loaded [inferred].

## 5b. Skeleton binding, physicsType, the defer flag

- **Skeleton [code].** 0x4C2BBF builds the inverse binds (+0x264) from slot 0's ModelRes (+0x190[0], its +0x130) only;
  the palette (+0x270) is sized from slot 0 and 0x4B9CFE fills it each frame in skeleton bone order (palette[0] identity,
  palette[i+1] = bone i). The per-slot render setup (0x4CA09F -> 0x4C6509 / 0x4BEA65) gives every mesh that one palette:
  no bone-name lookup, no per-model skeleton, no remap. A part made for another skeleton would bind to the wrong bones
  with no detection path [inferred]. Software skinning switches at max(ModelRes +0xE4) > 70; mixing hardware-skinned
  members cannot cross it [inferred].
- **+0x150 is `physicsType`** (registered at 0x4AC9E6: STATIC 0 / KINEMATIC 1 / DYNAMIC 2; setter 0x49CBC4 =
  CollisionNode::SetMovementType -> 0x519E6F) [code]. `command_activate_model` sets it to 1 at 0x69E386, so copying the base
  member's value is harmless [code].
- **List op 0xB = set element** (dispatcher 0x504E0D, case 0x505153: frees the old string 0x500140, stores a strdup
  0x4EBBCF) [code]. The head-name blanking frees the member's original name strings: never cache those pointers.
- **Defer flag [[0xE15124]+0x31]:** 0 from the constructor (0x4EDE0D); only 0x4EBE09 writes it, always in save / set /
  restore pairs; back to 0 runs the flush 0x545FD9. While 1, 0x47A9FD only marks the object dirty and 0x4CA09F returns at
  once [code]. No set-1 scope encloses the script dispatch that runs InstantiateSubSystems, so at a spawn 0x4B28D1 ends
  with one immediate rebuild [inferred]; the thunk below reproduces that.
- **Head type readers:** of the 27 HeadCtrl methods only 0x662728 writes +0xE8 and only `command_activate` reads it; a
  whole-.text pattern scan found no other reader (not exhaustive through calls / spills); the index has no property name;
  the face-driving handlers do not read it [code]. The head type selects the head mesh and its sheets only, as far as read.

## 6. Hook

**Site** 0x0069CF11 `E8 E1 90 E1 FF` (retarget rel32). Signature at 0x69CEF8:
`8B 03 FF 75 FC 89 45 0C E8 C1 26 E1 FF 85 C0 59 74 0C 8B 4D FC 8D 45 0C 50 E8 E1 90 E1 FF 5F 5E 5B C9 C3` [code].

**Contract:** thiscall, ecx = visual, [esp+4] = pointer to the chosen member; `ret 4`; keep ebx / esi / edi / ebp.
ebx = the args pointer ([ebx+0xC] = the root entity); [ebp+0xC] of 0x69C8E3 already holds args[0] (0x69CEFD) [code].

**Thunk:**
1. Off, or not a collection to mix: jump to 0x4B5FF7.
2. The collection: root members +0x14 -> definition +0x10 -> member list (the skin-check path), or from the get_model hook.
3. A source member per slot, seeded by the root (the same character keeps its mix); only members whose slot 0 name equals
   the base member's.
4. Name list: element k = X_k's name k, with the six-substring blanking done by the add-on (unused members still hold head
   names); the base member's slot count, "" padding.
5. Description from each member's stored +0x1DC / +0x1E0, read only: "2," + the records whose slot field is k. Never call
   0x49F95E on other members (it writes to them).
6. The 0x4B28D1 sequence with those inputs (the engine copies them; static buffers are fine): 0x4EBE09(mgr, 1);
   0x4980F0(visual, &list); 0x49D26C(visual, desc); 0x49CBC4(visual, [base+0x150]); 0x4EBE09(mgr, saved);
   0x47A9FD(visual).
7. Head: [[[[visual+0x10]+0x0C]+0x10]+0xE8] = the chosen head type.
8. `ret 4`.

Timing: the stock copy point, before visual init, `command_activate_model` and the head activation; the rebuild builds
the sheet table before the render objects [code].

**Alternative B:** point the base member's +0x19C / +0x1A0 and +0x1DC / +0x1E0 at the add-on's list and string for the
stock call, then restore (0x4B28D1 reads the source string as stored when +0x1DC != 0). No setter calls, but it writes
into a shared member during the call.

**Risks:** reference counts are the engine's handles [code]; skeleton binding by index from slot 0 (same slot 0 only);
blanking (above); head
type 0 is skipped by 0x69C8E3, a direct +0xE8 write avoids that; model LOD covered by the table builder [code];
character LOD re-instantiation [not established] (a root-seeded mix repeats).

## Not established

1. Who fills the deferred-message queue (0xC8CCD4).
2. Whether any face clip set varies by head model.
3. The defer flag's value at a spawn, at run time.
4. Character LOD re-instantiation of a live character.
5. Everything above at run time.
