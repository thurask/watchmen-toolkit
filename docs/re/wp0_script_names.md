# WP0 - names for the baked scripts: mechanism, extraction, lifter

Target `KapowMultiDEDRM.exe`. Evidence marks: **read** = traced in code (addresses given),
**data** = verified on the extracted tables (numbers given), **inferred**, **not established**.
Slots are 4 bytes everywhere. Files are listed in section 9.

## 0. Result in one page

- The tail of every `Class__register` holds, per handler, the handler's **variable table**: optional
  `<return>`, the arguments, then the locals, each as `(name, type object)`. All 13,205 records of all
  441 classes are extracted (0 unparsed) and every one of the 108 type objects is named.
- Three frame models exist, decided by the registration slot of the handler (section 2). Together
  with the member rule (properties in registration order) this names every script-visible storage
  location a handler touches.
- Independent checks on data: 3,939/3,939 command signatures (recovered earlier from hashes) equal
  the record types; 503 state frames have `Task_PushLocals(N)` equal to the summed local sizes; 362
  compiler-generated polymorphic member accesses resolve to the same member name in every branch
  class, 0 contradict; 231 of 233 entity members/arguments whose name implies a class receive only
  commands of that class.
- Applied in Ghidra (copy of the project) and as a text lifter. Corpus `findings/script_lifted/`:
  441 files, 454 k lines, every one of the 6,630 registrations present. Reference resolution over
  the 4,514 distinct bodies: own members 99.95 %, frame slots and arguments 98.9 %, command and
  property hashes 100 %, runtime calls 99.4 %, type operations 97 %, members of *other* objects 77 %.

## 1. The registration tail

### 1.1 Record and container (read)

- Command record: `ScriptClass_RegisterCommand` 0x47eccc allocates 0x38 bytes: name string +0,
  kind +0x10, **owning state index +0x14**, hash +0x18, command/state/method handler
  +0x1c/+0x20/+0x24, class +0x28, and at **+0x2c a vector of 20-byte elements** (ptr, count, cap).
- Element: 16-byte engine string + type pointer at +0x10. Built on the stack either by 0x598d0e
  `(tmp, name, type)` (calls `Str_AssignCStr_b` 0x4f7ae9, stores type at +0x10) or by the same two
  steps inlined, then appended with `Vec20_PushBack` 0x5a0dfd; `this` of the push is
  `class->commands[i] + 0x2c`, loaded as `mov r,[cls+0x1c]; mov r,[r+4*i]; lea ecx,[r+0x2c]`
  (e.g. 0x6d1ebc..0x6d1ecc and 0x6d2461..0x6d2490 in `CharacterSpawner__register`).
- **Boundary between handlers** = the reload of that `this` pointer: the group index `i` is the index
  in the class command list, i.e. the order of the 0x47eccc calls, which is the order of
  `reg_dump.json` `commands`. Groups appear in increasing `i`; handlers without variables have no
  group. All command registrations precede the first record.
- What the vector means is read from `FUN_00479e91` (0x479e91): the task debug dump computes the
  "theoretical size" of the data stack by summing `type->sizeSlots (+0x24)` over the +0x2c vector of
  the command record of every active frame. So the vector is the frame content of that handler.

Extractor: `work/wp0/extract_tail.py` - a symbolic linear sweep from each function entry (register
and stack-slot tracking, ebp- and esp-based frames, both record idioms) to the `ret` after
`ScriptClass_FinalizeLayout` 0x47ed4b. **13,205 push-back call sites exist in the exe, all inside
the 441 register functions; 13,205 records extracted, 0 failed.** (The dump's sizes for 9 register
functions are wrong, e.g. `CharacterRoot__register`; the sweep does not use them.)

### 1.2 Type pointer -> type name (read; 108/108 resolved)

- Basic types are created in 0x501f6a with `DataType` ctor 0x4fa12f `(id, name, slots, flag)`:
  0xe15190 number (1 slot), 0xe1518c integer (1), 0xe15194 truth (1), 0xe15184 vector (3),
  0xe15174 quaternion (4), 0xe1517c string (1), 0xe15188 biginteger (2), 0xe15178 color (1),
  0xe15170 nothing (0); 0xe151a0 = `EntityType("Entity")` (0x50b1d6, id 0xc, 1 slot).
  `slots` is stored at type+0x24 - this is where "vector 3, quaternion 4" comes from.
- Script structs: 0x81c5f5 (scriptresource.cpp; the dump has no decompilation, read from bytes)
  builds 72 struct types: field list ctor 0x5023a2, `0x50b807(list, fieldName, 0x50211a(typeName))`
  per field, `StructType` ctor 0x4f06e5 (id 0xd, 1 slot: an instance pointer). Field names and types
  are in `wp0_script_layout.json` `structs`. A further 83 native structs are declared by strings
  such as `PhysicsCastHitInfo(vpoint:vector,vnormal:vector,t:number,...)` (parsed by 0x4f08c7).
- The type globals used by the records are filled right after (0x820e58..): `mov [esp],nameVA;
  call 0x50211a; mov [glob],eax` - 139 globals, e.g. 0xe1696c `list(entity)`, 0xe16c70
  `list(propertyinstance)`, 0xe16aec `characterdamagestruct`. All 101 non-basic globals that occur
  in records are in this table. `extract_types.py`.
- Same region: 335 class objects `mov [glob], ScriptClass_GetByIndex(id)` (0x47c4e7), 28 class
  indices by name (0x47c5b4), and in 0x813000.. 30 library singletons
  `mov [glob], 0x47c56d("WorldLib(Node)")` (0xe17194..0xe17208). `extract_globals.py`.

Type use over the 13,205 records: entity 3,511, integer 2,887, number 2,162, truth 1,700, vector
1,210, string 455, quaternion 262, list(entity) 206, list(propertyinstance) 163, other 649.

### 1.3 Which entries are return, arguments, locals (read + data)

Record order is always `[<return>] [arguments...] [locals...]`.

| handler slot | count | frame model | how the split is known |
|---|---|---|---|
| command (handler at +0x1c, has hash) | 3,939 | record = `<return>` + arguments only; they are the slots of the `args*` parameter. The command's locals are stored in the record of its **owning state** | signature; **data**: record types == signature types for 3,939/3,939 |
| state (+0x20) incl. `_root` | 841 | task frame: arguments at `stack[frame->argsBase]`, locals at `stack[frame->localsBase]` | `Task_PushLocals(N)` in the function = slots of the trailing locals: 503 exact, 320 empty, 18 by the case rule |
| method (+0x24) | 1,850 | `<return>` + arguments are the slots of `args*`; locals are ordinary C locals (not addressable) | case rule (inferred), see below |

- Owning state: record +0x14 (`arg3` of 0x47eccc). 0 = `_root`; otherwise the command-list index of
  a state. **data**: all 3,939 commands point at a state-slot handler (3,300 `_root`, 639 nested);
  the same command name registered twice with different owners is the per-state override
  (`CharacterSpawner.command_is_running`: owner 0 and owner 8 = `StateActive`).
- Case rule: the compiler lower-cases locals and keeps the source spelling of arguments. Measured
  where the truth is known: 3,811 of 3,813 state locals are all lower case; 2,323 of 2,563 arguments
  contain an upper-case letter. For methods the split is therefore **inferred** and can be wrong for
  an argument written in lower case (the mapping of `args[k]` to names does not depend on the split).
- `_forinlistvarindexN_` are compiler-made loop counters of `for x in list`.

## 2. Frames, arguments, return values (read)

Objects: `Task` (the `ctx` parameter), `TaskFrame` (0x1c bytes), globals `g_self` 0xe12d9c,
`g_stateLocalsBase` 0xe12da0, `g_stateArgsBase` 0xe12da4.

- Handlers are `void __cdecl h(Task* ctx, slot* args)`. `ScriptBaked_InvokeHandler` 0x479874 and the
  dispatcher tail 0x479c56 store the receiving entity in `g_self` before the call.
- `Task`: +0x10 data stack (`->+4` = slot array), +0x1c frame array, +0x20 frame count, +0x28 sleep
  time, +0x2c wake frame, +0x30 low 16 bits stack pointer (slots) and flags 0x10000 sleeping /
  0x20000 real time, +0x3c pending call record, +0x40 current frame, +0x44 blocking flag.
- `TaskFrame` (pushed by 0x47a447): +0 self, +8 handler index, +0xc **resume label**, +0x10 `argsBase`
  = sp - nargs, +0x12 `localsBase` = sp at entry, +0x14 marker 0xfffe, +0x18 count popped on leave.
- State function: reads `frame = ctx->frame`, `self = frame->self`, members `self+0x10`, locals
  `ctx->stack->data + frame->localsBase*4`, arguments `... + frame->argsBase*4`; first entry
  (resume 0) calls `Task_PushLocals(n)` 0x47a3fa (sp += n, zero-filled) and constructs struct/list
  locals; on unwind it destroys them, pops and calls `Task_LeaveFrame` 0x47a165.
- Command in a state: locals of the enclosing state are reached through
  `ctx->stack->data + g_stateLocalsBase*4`, its arguments through `g_stateArgsBase`. The values come
  from the dispatcher: `Entity_SendCommand` 0x596d91 -> 0x47c9fd passes 0,0 (the `_root` frame is at
  the bottom of the object's task stack); the by-hash path 0x47decf searches the frame array for the
  innermost active frame of the owning state (0x479d9f / 0x479e01) and passes that frame's +0x12 and
  +0x10. Read on `CharacterSpawner.command_remove_enemies` 0x697992 (`etemplist` slot 1, `i` slot 2
  of `_root`).
- Sizes: a variable occupies `type->sizeSlots`; vector 3 slots inline (x,y,z), quaternion 4,
  biginteger 2, everything else 1 (string = `char*`, entity = pointer, list/dict = pointer to a list
  object `{buf, nslots}` with `buf->+4` = element slots, struct = pointer to an instance whose `+4`
  points at the field slots, fields laid out by the same size rule).
- Arguments: caller builds a slot array `[return slots][arg0][arg1]...` on its C stack and passes its
  address; a vector argument takes 3 slots, a quaternion 4. **Return value** = written by the callee to
  `args[0..]` (`CharacterRoot.IsAIPartner` 0x678254 `*args = ...`; the shared body 0x7f09ac is just
  `args[0] = 1`). Commands without return and without arguments get `args = 0`.
- State arguments are pushed on the task stack: `Task_PushLocals(n)`, store to the top n slots,
  then a call/goto request; popped by the caller afterwards (`sp -= n`).

### Coroutines

- After **every** call that can run script, a handler tests `ctx->pendingCall != 0 && !ctx->blocking`.
  Commands and methods then simply return (the request is honoured further up). State functions call
  `Task_SetResumeLabelAndCall(ctx, n)` 0x47a66f (better name: check pending call): stores n at
  frame+0xc and runs 0x47a572: **0** continue, **1** a callee frame was pushed - return to the
  scheduler, the function is re-entered later through `switch(frame->resume)` at case n, **-1** this
  frame is being unwound - jump to the cleanup block.
- The pending record is written by `Task_SetupCall` 0x47a4b0 through two wrappers:
  0x47a513 (mode -1) `(fromState, calleeFn|0, calleeIndex, self, class, nargs)`: unwind up to and
  including the frame of `fromState`, then push the callee if there is one - seen as
  `(S,0,-1,0,0,0)` "leave state S" and with a callee "go to state"; 0x47a533 (mode 0): push the
  callee on top of `fromState` (latent call). The goto/call naming is **inferred** from 0x47a572.
- Real waits: `frame->resume = n; Task_WaitNextFrame(ctx)` 0x4797e9 (wake frame = now+1) or
  `Task_WaitSeconds(ctx, t, realTime)` 0x479a1d, then `return`.
- 836 of the 841 state functions contain resume logic (820 with checkpoint labels); no command or
  method does - they only test the pending flag and return. Labels per handler: `resume_labels` /
  `wait_labels` in the JSON.

## 3. Member (property) offsets (read + data)

- `ScriptClass_FinalizeLayout` 0x47ed4b: property records are 0x18 bytes at class+0x10; record +0xc
  receives the running slot offset, which advances by `descriptor->type->sizeSlots`. Offsets start
  at 0; the block is addressed as `*(entity + 0x10)`.
- Order = order of the `ScriptClass_RegisterProperty` 0x47fde4 calls = `reg_dump.json` `props`.
- **Inheritance**: a derived class's register function registers the parent's properties first
  (their `typeidx` is the declaring class) and then its own, and likewise the parent's commands
  first. **data**: 93 classes have a script parent; in 93/93 the member list starts with the parent's
  list at identical offsets and the command list starts with the parent's commands at identical
  indices. That is why `(index, hash)` dispatch and member offsets work on derived objects.
- Native base members are not in the block: they are native properties, reached through direct
  accessor calls or `Entity_Set/GetPropertyByHash` (section 4).
- **Property value types are not in the exe** (the registration passes only the hash; the descriptor
  is looked up by hash, 0x4ee10d). Types and names come from the game database key table
  (`kapow_fragment_keys.pkl` `keytable`, re-hashed with the &0xDF fold): 5,089 of 5,090 registered
  properties are typed; `interval` (1) is not and is assumed 1 slot. Evidence level for sizes: **data**
  (database types) confirmed by code use - see the checks in section 6.

## 4. Runtime calls (read; table `findings/wp0_builtins.json`)

4,488 handler bodies make 38,943 direct calls to 637 targets; the top 200 cover 96.2 %. All top-200
entries are named with evidence: 69 read in this pass, 50 from the native message registry, 40 from
the native property registry, 37 type casts recognised by pattern, 4 from the subsystem map.

- `Entity_SendCommand(target, cmdIndex, hash, args)` 0x596d91 -> 0x47c9fd: runs
  `class->commands[cmdIndex]` if its hash matches; no-op for non-script entities. The index is a
  compile-time constant of the *static* receiver class, so `(index, hash)` identifies the class
  family of the receiver.
- 0x4f99a4 (dump name `Entity_GetPropertyByHash` is **wrong**): send message by hash, state-aware
  script lookup 0x47decf, else native message table. All 1,146 constant hashes passed are command
  hashes except one (0xca2af20a), the native message `Stop` (hash of the bare name).
- 0x510737 (thunk 0x5107b2) set property by hash; 0x4ff93b (thunks 0x5037ea, 0x506074) get property
  by hash; 0x4f99c3 / 0x4f99dc get/set script property by index.
- Own methods: `InvokeHandler(ctx, *(class->commands[i]) + 0x24, self, args)`; parent's
  implementation through `scriptClass->parent (+0x58)`; library functions by direct function address
  with the library singleton as self.
- Polymorphic member access: when the static type of an entity expression is a set of classes, the
  compiler emits `ScriptClass_IsDerivedFrom(obj->type->scriptClass, CLS_x)` chains (0x596d7b, walks
  +0x58) and reads the member at each class's own offset.
- Entity cast: 35-byte functions that walk `entity->type->parent (+0x30)` to a native type object;
  58 are called from handlers; named from the 145 `EntityType` ctor calls (0x50b1d6).
- Native functions: 762 registered messages with signature strings (620 through
  `EntityType::RegisterMessage` 0x50ed51 `(sig, memfn, 0, doc)`, 142 builtins through 0x47f650 /
  0x47fe93) and 2,017 property accessor entries (0x505514 family). Called directly as
  `fn(this = entity, args*)` with the same `[return][args]` slot layout.
- **Builtin-by-id idiom** (3,718 calls): `(*typeObject->vtbl[0x60/4])(id, args)` = `DataType` virtual
  slot 24. Ids are assigned by slot 23 (name -> id resolver), which compares against literal
  strings, so the names are the engine's own: list `+ == != clear erase(integer) size count(T)
  index(T) rindex(T) push_back(T) [](integer) [](integer,T) insert(integer,T) resize(integer)` =
  0..13; string `+ == != > < >= <= size tolower toupper substring find []` = 0..12; dict 0..8;
  struct `== != serialize deserialize` then 4+2k get / 5+2k set field k; vector 0..22; quaternion
  0..26. Other vtable slots used: +0xc construct, +0x10 destroy, +0x14 copy, +0x54/+0x58 equality.
  Only list, string, dict and struct ids occur in handlers; arithmetic is inlined.
- Math: `sin/cos/acos/pow/floor/sqrt` wrappers identified through the registered builtin handlers
  that call them (0x47aa9e..).

## 5. Tools

### 5.1 Ghidra (`work/wp0/ApplyScriptLayout.java`, data `work/wp0/script_layout.tsv`)

Run headless on a copy (`work/wp0/proj`), in this order, from a directory that does not itself
contain the scripts, with `-scriptPath work/wp0`:

1. `FixProtos.java protos.lst 2` - commits the decompiler-inferred prototype of 2,262 runtime
   targets. In the lead's project these functions are `undefined f(void)` with unknown convention,
   so the receiver in ECX is dropped at every call site; after the commit `Entity_SendCommand(...)`
   shows its target. (4,522 commits, 22 s.)
2. `ApplyScriptLayout.java script_layout.tsv retype` - 532 labels (globals, type objects `T_*`, class
   objects `CLS_*`, libraries `g_*Lib`), 4,825 structures in `/KapowScript` (`Task`, `TaskFrame`,
   `Entity`, one `<Class>_members` per class, `<Struct>_data/_inst` per script struct, `_args` and
   `_locals` per handler), prototype `void h(Task *ctx, <h>_args *args)` and a plate comment for
   4,488 handlers, and **3,194 local variables retyped/renamed** (`m` members, `L` locals, `SL`/`SA`
   enclosing state, `self`, `frame`) by matching the defining p-code expression. ~6 minutes.
3. `DumpDecomp.java OUT handlers.lst` - re-dump (4,540 functions, 1 decompile failure).

Tested on all classes (so including CharacterRoot, CharacterRootLogic, AnimationCtrlWM, Enemy).
Limits: variable retyping only where one variable holds one base pointer for its whole life; C
locals of methods are not named (no stable mapping from the record to the decompiler's variables -
only the plate comment lists them); 28 handler entry points are not function starts in the project.

Before / after (decompiler output only, no lifter):

```c
/* before */ void CharacterRoot__DecreaseHealth(int param_1,uint *param_2)
  iVar2 = DAT_00e12d9c[4];
  local_94 = (int *)(*(float *)(iVar2 + 0x1c8) * (float)param_2[1]);
  fVar1 = *(float *)(iVar2 + 100);
  if (param_2[2] != 0) {
/* after  */ void __cdecl CharacterRoot__DecreaseHealth(Task *ctx,CharacterRoot__DecreaseHealth_152_args *args)
  m = g_self->members;
  local_94 = (Entity *)(m->m_nincomingdamagefactor * args->nMyDamage);
  fVar1 = m->m_nhealth;
  if (args->eInflictor != (Entity *)0x0) {

/* before */ void Enemy__command_force_step_back(void)
  piVar1 = *(int **)(DAT_00e12d9c + 0x10);
  iVar2 = *(int *)(*(int *)(*piVar1 + 0x10) + 0x7c);
  if (iVar2 != 0) {
    *(int *)(*(int *)(piVar1[0x15] + 0x10) + 0x10) = iVar2;
    piVar1[0x1e] = (int)(*(float *)(*(int *)(DAT_00e171f8 + 0x10) + 0x20) + (float)_DAT_00c3cc48);
/* after  */ void __cdecl Enemy__command_force_step_back(Task *ctx,void *args)
  m = g_self->members;
  iVar1 = *(int *)((int)m->m_echaracterroot->members + 0x7c);
  if (iVar1 != 0) {
    *(int *)((int)m->_ebehaviorstepback->members + 0x10) = iVar1;
    m->_nstepbacktimer = g_WorldLib->members->g_ngametimesincestart + (float)_DAT_00c3cc48;

/* before */ void AnimationCtrlWM__IsImportantActionPending(undefined4 param_1,int *param_2)
  if (*(int *)(iVar1 + 0xf8) == 0) {
    ScriptBaked_InvokeHandler(AnimationLib__IsAnimationActionPending,DAT_00e171e8,&local_10);
    if ((local_10 != 0) || (*(int *)(*(int *)(*(int *)(iVar1 + 0x10) + 0x10) + 8) != 0)) {
/* after  */
  if (m->_tishead == 0) {
    ScriptBaked_InvokeHandler(ctx,AnimationLib__IsAnimationActionPending,g_AnimationLib,&local_10);
    if ((local_10.ret != 0) || (*(int *)((int)m->m_eanimationdata->members + 8) != 0)) {

/* before */ void CharacterRootLogic__command_blocked(undefined4 param_1,undefined4 *param_2)
  local_c = *param_2;
  local_8 = *(undefined4 *)(*(int *)(DAT_00e12d9c + 0x10) + 0xa4);
/* after  */ local_c = args->eBlockedEntity;
  local_8 = *(undefined4 *)((int)g_self->members + 0xa4);   /* lifter: self._edodgecharlist */
```

### 5.2 Lifter (`work/wp0/lift.py`)

`lift.py Class.handler | 0xADDR`, `--class Class`, `--all OUTDIR` (`--old`: lift the text of `R/dump`; receivers of sends are missing there). Works on the decompiler text
(`work/wp0/dump2` preferred, `R/dump` as fallback; 28 entries without text are printed as
disassembly). Passes: unwrap lines; fold the coroutine boilerplate (`CHECKPOINT(n)`,
`STATE_CHANGE_PENDING`, `WAIT_FRAME/WAIT_SECONDS ... resume at case n`, `LEAVE_STATE/GOTO_STATE/
CALL_STATE`, `STACKTOP[-k]`, `POP(n)`); member, local and argument names (`self.`, `loc.`, `arg.`,
`st.` = enclosing state's locals, `starg.`), including raw offsets through an approximate flow
tracking of which C variable holds which base pointer; polymorphic `IsDerivedFrom` chains; members of
other objects with a class guess; struct fields and list elements (`list[i].field`, `COUNT(list)`);
sends as `send(target, Class.command(sig), args)`, by-hash sends, `setprop/getprop(target,"name")`,
own/parent/library method calls; type operations as `OP<list_entity>."push_back(T)"(/*value,list*/
&tmp)`; runtime helper names; enum names on member comparisons where the property UI string names
an enum (`engine_enums.json` family or an inline `A:0,B:1` list); string addresses; float literals.
Unrecognised text is left unchanged; unresolved hashes are tagged `/*?hash*/`, guessed classes carry
`/*Class?*/`, classes proven by sends / `HasScript` / polymorphic chains carry `/*Class*/`.

Class of another object's member access is decided, in this order, by: the `(index, hash)` of a
command sent to the same expression (919 uses), a preceding `HasScript("X")` test, an `IsDerivedFrom`
chain (655), the variable or member name matching a class name (1,048; `m_echaracterphysics` ->
`CharacterPhysics`), a unique long common prefix (38), a property-name string literal in the
function (20); 344 more are the object's own block reached through a copy of `self`. The name
rule is a heuristic: where it could be cross-checked it agreed in 231 of 233 cases (section 6).

Corpus-wide resolution (4,514 distinct bodies, `findings/wp0_lift_stats.json`):

| reference kind | resolved | unresolved | share |
|---|---|---|---|
| own members | 16,666 by Ghidra types + 2,668 from raw offsets | 9 | 99.95 % |
| frame locals / state locals | 5,902 + 7,975 | 296 leftover expressions | 97.9 % |
| arguments | 12,146 + 105 | 6 | 99.95 % |
| members of other objects | 5,885 | 1,751 | 77.1 % |
| struct fields | 942 | 19 | 98.0 % |
| command / property hashes | 6,289 | 0 | 100 % |
| own-class / library method calls | 3,971 | 52 | 98.7 % |
| type operations (builtin-by-id) | 3,609 | 110 | 97.0 % |
| runtime helper calls with a name | 25,396 | 157 | 99.4 % |
| coroutine checkpoints | 1,776 folded | 1,237 left as annotated calls (tail-merged form) | - |
| enum constants annotated | 98 | not measured (only members with an enum UI) | - |

## 6. Verification

Automatic, on all data:

1. Command records vs signatures: 3,939 / 3,939 equal in count and types.
2. State frames: `Task_PushLocals(N)` equals the slot sum of the trailing locals in 503 state
   functions; the 18 others have no immediate operand or no matching push (split by the case rule).
3. Polymorphic chains: 362 blocks; in 276 the branches read different offsets and all of them map
   to the **same member name** in their respective classes (e.g. `m_nmaxhealth`: AiDef +0x2c,
   CharacterDef +0x30; `m_echaracterdef`: CharacterRoot +0x14, AiDef +0x18); 86 read one offset;
   0 blocks without a common name. This tests member offsets of two or more classes against each
   other with no input from us.
4. Name-implied class vs send-implied class for entity members/arguments/locals: 231 agree, 2
   conflict (`FollowPartner._epartner` holds a CharacterRoot, not a `Partner`;
   `BehaviorMovementTest.m_echaracterroot` receives a CharacterRootLogic command).
5. Raw `float` dereferences land on a number/vector/quaternion name in 686 of 709 cases; the 23
   others read back as 4-byte copies through a float temporary (checked on
   `CharacterPhysics.command_update_world_data`: `igamepivotindex` passed as the integer argument of
   `GetTrackPosAtGivenTime`), not as wrong names.
6. Struct layouts: `PendingActionStruct` fields `eAction, eActivator, nDurationLeft` are written from
   arguments `eAction, eActivator, nDelay` (TriggerActionDelay.command_add_pending_action).

By reading: 48 handlers in 14 classes (CharacterRoot 6, CharacterSpawner 5, Enemy 5,
CharacterRootLogic 4, AnimationCtrlWM 4, PlayerHUD 4, CameraCinematic 4, SoundDef 4,
CharacterPhysics 4, HudBar 3, TriggerActionDelay 2, DamageBox 1, BehaviorChase 1, BossHUD 1). In all
48 every own member, local and argument name fits its use (`m_nhealth` compared and decremented in
`DecreaseHealth`; `nendtimer` accumulating frame time before `command_deactivate`; `_nstepbacktimer
= game time + c`; `nTravelTime`, `nFov` pushed as the two arguments of `StateMoveToPos`;
`m_nquarantinetimemin/max` driving a `rand_number` interpolation; `_iweapontype` at +0x190 as in the
audit). Hit rate for own names: 48/48 handlers, no wrong name found.

Mismatch patterns found, and what was done:

| # | pattern | effect | status |
|---|---|---|---|
| 1 | polymorphic access resolved with the class guessed from the variable name | wrong member name in the non-matching branch (`m_iprioritymodel` for AiDef +0x18) | fixed: chains are resolved first, by name agreement |
| 2 | class learnt from a send applied to a reused C temporary (`pEStack_c`) | wrong class for later uses | fixed: only named slots and single-assignment variables |
| 3 | one C variable holds different base pointers over time | raw offsets not named, or named wrongly if resolved globally | fixed: nearest-assignment rule, dropped at labels and loop back edges; costs coverage |
| 4 | decompiler lines wrapped inside an expression | patterns missed | fixed: unwrap |
| 5 | `ctx` copied to `this`/`pTVar` | coroutine boilerplate not folded | fixed for the block form; 1,237 tail-merged checkpoints remain as calls |
| 6 | parameter / stack slots reused by the compiler | Ghidra propagates the struct type: `args = (X_args *)value`, floats shown as `Entity *` | not fixed (cosmetic, common in large handlers) |
| 7 | dump function sizes wrong for register functions | records missed (548) | fixed: sweep to the real end |
| 8 | 4-byte copies typed `float` | false alarm of the type check | none needed |
| 9 | members of objects whose class is not derivable (results of `command_get_target`, list elements of generic entity lists) | 1,751 raw `expr->members + off` remain | open |

## 7. Coverage

- Classes 441 / 441. Members 5,090 (5,089 typed). Structs 155 (72 script, 83 native).
- Registrations 6,630 = 3,939 commands + 841 states + 1,850 methods, 4,516 distinct addresses.
- Registrations with a variable record: 4,391 (2,226 commands, 521 states, 1,644 methods).
- Records: 13,205 of 13,205 (1,676 return, 4,671 argument, 6,858 local). Unparsed: 0.
- Handlers not lifted from decompiler text: 28 addresses (156 registrations), entry points inside
  another function of the dump (shared tails); emitted as disassembly.

## 8. Acceptance test: three handlers explained from the lifted text alone

**`CharacterRoot.command_give_damage(characterdamagestruct):truth`** (0x691b10; damage handling
lives in CharacterRoot, not CharacterRootLogic) with `CharacterRoot.DecreaseHealth`.
The dodge bookkeeping lists `m_eenemytododgelist` / `m_nenemytododgetime` are cleared. Nothing else
happens unless `m_nhealth > 0` and the character is not a placeholder. `st.tisinflictoracharacterroot`
= the inflictor has script `CharacterRoot`; if so it is told `command_you_hit_me(self)`. If the logic
object has `m_treversedirection` and the animation play position is inside a constant window,
`damStruct.iDamagePos` is cleared. Unless `m_idamagestate == 1`: `_nfastrotatetime` = game time, the
logic gets `command_kill_combo`; damage is scaled by a constant when the victim's character type is
0x19 and the inflictor is an AI character; then, if the animation controller is not in slave mode or
the animation partner is the inflictor or the inflictor is the victim, `DecreaseHealth(nDamage,
eInflictor, iUniqueAttackId, iDamagePos != 0)` runs and its result is `st.tisdead`. Achievement
messages follow when the inflictor is the signed-in player. Rage: if `tRageDamage` and damage > 0 the
inflictor receives `command_add_rage(k * nDamage)` with one of two factors from the character special
data (the larger path, clamped from below, when its `m_ninrageuberdamagefactor > 1`), and the victim
receives rage with a third factor. A player hit by another player-controlled character gets
`m_nextraclearzonetime = now + _thitinvsmodedefenddeadzonetime`. If the def has a sound def and damage
> 0: speech is stopped (not for type 0x19), the damage effect is prepared - uber-damage flag, weapon
(the inflictor's `m_eweapon`, the fake Twilight Lady weapon when its def type is 0x23, none when
`tIgnoreWeapon`), an impact offset from `CalcImpactOffset(inflictor, vImpactWorldPos, body or head
attack distance)` - and `CharacterEffectDef.command_play_damage_effect(self, iDamagePos, pos+offset,
vImpactWorldDir, uber, ?, weapon)` is sent; the logic gets `command_set_ragdoll_modifier_direction`.
Survivor branch: a player inflictor gets `command_do_recoil(iDamagePos)` and for damage positions
13-18, 27, 28 slow motion starts (`WorldLib.SetTimeMultiplier(_nslomotimemultiplier)`, `_tslomo`,
`_nslomotime` = real time); `command_set_stun_time` if the new stun is longer than `_nstuntimeleft`;
`command_set_push_back_data(vPushBackSpeed, nPushBackTime)` if a push-back time is given. Death
branch: prone victims get a constant ragdoll direction; slow motion is ended or, for a list of
finishing damage positions by a player, a camera FOV effect, a shake and slow motion are started;
`command_enemy_killed_by_signed_in_player`, `command_you_killed_me(self)` to the inflictor; a ragdoll
velocity from the impact direction and a push-back are set. Finally the head controller and the
body animation controller get `SetAnimationEnum(ctrl, 4, iDamagePos)` (enum variable 4 is
DAMAGE_POSE in `engine_enums.json`) and `FireAnimationAction` 0xe / 2, the player controller or the
behaviour handler gets `command_hit_by`, and under a state flag the combat orchestrator is told
`command_force_lock_target(self, inflictor)` and the victim `command_set_aggressive`. Returns true.
`DecreaseHealth`: damage = `m_nincomingdamagefactor * nMyDamage`, divided by the inflictor's uber-rage
factor (floor constant) when the victim is a playable character; returns false if `m_tinvulnerable`
or damage state 1; type-0x19 characters cannot drop below `max(1, m_nhealthlowerbound * def
m_nmaxhealth)`; playable characters are immune under `characterlib.g_tplayablecharactersinvulnerable`;
otherwise `m_nhealth -= damage`, AI partners are held at 1, `m_nlasthittime` is stamped, and crossing
the def's `m_ncriticalhealth` starts the critical phase (`m_nstartcriticaltime`).
*Unclear in the lifted text:* the numeric constants are unnamed globals; three accesses to
`characterlib.g_echaracterspecialdata` and two `st+0x84/0x88` slots stay raw (variable reuse); damage
positions and action ids are bare numbers; the argument packs (`&local_90`) must be matched to the
signature by order.

**`Enemy.Evaluate`:integer** (0x72587d, 5.8 kB coroutine, 34 checkpoints, 2 timed waits).
Returns 1 at once if the character root's health is <= 0. A watchdog: when the root's breadcrumb
timer is set, older than a constant and the state of mind is 1, a forced state 5 fetches the
follow pivot from the follow-pivot behaviour, a kill timer `nbreadcrumbmovekilltimer` is armed, and
when it later expires the enemy is removed with `CharacterRoot.command_uberkill`. Without a
breadcrumb timer the heading from the AI brain (`MathLib.ToHeading`) is sent as
`command_set_movement(n, n, 0)`. The wanted state defaults to 3. While the step-back behaviour's
timer runs the function returns 10. Outside the home turf (or while the return behaviour is
current) `ReturnToCombatZone.command_force_return` is issued unless it is running and its
preconditions hold. With a target from `Perception.command_get_target`, reachability is asked
through `Perception.command_force_is_pos_reachable(self, targetPos)` with a short timed wait, and,
failing that, by `AIWorldNode.TraceLine` towards the target's physics position compared with a
radius; an unreachable target returns 3. The definition object (polymorphic EnemyDef /
UnderbossDef / AiDef / CharacterDef member reads) decides hanging back (`thangback`, the hang-back
behaviour and `command_get_hang_back_time`). Otherwise the distance to the target is compared with
the def's `command_get_max_melee_distance`; moving in is allowed when the combat orchestrator's
`m_imovingcharacterslastframe` is under a def limit or the character already moves
(`command_get_move_speed > 0`); wanted state becomes 4 or 2, and `SetState` is called when it
differs. *Honestly:* single statements read well, but the order of decisions is hard to follow -
the function is a 35-case resume switch with gotos between cases; members of the perceived target
(`loc.etarget->members + 0x88/0x1a0/0x28`) are unnamed because nothing in the function fixes the
target's class; several float temporaries are shown as `Entity *`/`Task *`. I would not trust my
reading of the exact branch conditions without the disassembly; the list of commands and members
involved is reliable.

**`BossHUD.StateActive(eCharacterRoot)`** (0x625c7b). Enables `_erootsprite`; picks the name text slot
from the boss's character type (def member 0 through a CharacterRoot/AiDef polymorphic read of
`m_echaracterdef`): 0x19 -> slot 0x70, 0 -> 0x10b, 1 -> 0x10c, 0x23 -> 0x10d, anything else shows
`characterlib.DebugCharName` as raw text. Lays the bar out from measured sizes: text background
width = name width + c + `_ninitialhealthbarx`; health bar x = name width + health sprite width + c
(`SpriteBar.command_set_pos`); the empty-bar, gradient and health sprites get pixel offsets built
from the same widths. Then every frame: fraction = boss `m_nhealth` / def `m_nmaxhealth` (AiDef or
CharacterDef offset) sent as `command_set_bar`; while the boss's health is <= 0 `nendtimer`
accumulates frame time, and when it exceeds 1 s the HUD sends itself `command_deactivate`;
otherwise it waits one frame. *Unclear:* which component of the size/offset vectors each
`extraout_EAX` read is (getter results returned by pointer), and the constants.

## 9. Not established

- Method argument/local split where the case rule is the only evidence (1,850 methods).
- Value type of property `interval`; property types rest on the database key table, not on the exe.
- `kind` (+0x10): 3 for all commands and `_root`, 1 for other states and 1,501 methods, 3 for 349
  methods - meaning unknown. Frame field +4 and pending-record field 5 (class pointer?) unused here.
- Goto-vs-call semantics of 0x47a513 / 0x47a533 are read from 0x47a572 but not confirmed by a trace.
- Native message hashing: one observed case (bare name `Stop`); the rule for natives with
  arguments is not established.
- Names marked `?` in `wp0_builtins.json` (7 of the top 200) describe behaviour only.
- 1,751 member reads of objects with unknown class; 296 frame expressions; 110 type operations
  through a non-constant type object; C locals of methods.
- Whether `CLS_*`/class ids in `reg_dump.json` are right for all 335 class objects was checked only
  through the polymorphic chains that use them (71 distinct classes).

## 10. Proposed toolkit changes (not made)

- `gen_data.py` / `reg_dump.json`: add per command `owner_state` (rename of `arg3`), `vars`
  `[{name,type,role,slot}]` (extract_tail.py), per class `member_offsets` (needs the key table
  types), top-level `types`, `structs`, `libs`, `class_objects`.
- Dump naming: 0x4f99a4 is send-by-hash, not a property getter; 0x47a66f returns int.
- `fn.py`/dump: register function sizes are wrong for 9 classes; 28 handler entries are not
  functions.

## 11. Files

- `findings/wp0_script_names.md` (this), `findings/wp0_script_layout.json`,
  `findings/wp0_builtins.json`, `findings/wp0_lift_stats.json`, `findings/script_lifted/<Class>.c`.
- `work/wp0/`: `extract_tail.py`, `extract_types.py`, `extract_globals.py`, `natives2.py`,
  `natives3.py`, `calls.py`, `build_layout.py`, `build_builtins.py`, `gen_ghidra_data.py`, `lift.py`,
  `verify_sends.py`, `wp0lib.py`; Ghidra: `ApplyScriptLayout.java`, `FixProtos.java`,
  `DumpDecomp.java`, `script_layout.tsv`, `protos.lst`, `handlers.lst`; `proj/` (modified copy of
  the project), `dump2/` (re-decompiled handlers).
