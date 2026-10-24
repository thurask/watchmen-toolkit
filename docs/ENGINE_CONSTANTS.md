# Engine constants from the decompilation

What the Kapow engine of *Watchmen: The End Is Nigh* does, read from the executables and the
PhysX DLLs, measured on the shipped files and on captures, and what the toolkit does with it.
Each constant is listed once, with its value, where it lives and its evidence.

Addresses are in `KapowMultiDEDRM.exe` (Part 2 PC, image base 0x400000) unless a line names
another image: `PhysXCore.dll` (PhysX 2.8.1.1, image base 0x10000000, addresses `0x10……`),
`NxCharacter.dll` 2.8.1.6, the Xbox 360 Part 2 image (`0x82……`), the PS3 Part 2 ELF, the
Xbox 360 Part 1 image `default.pe` (`0x828…`; it resolves only when read as a memory image,
file offset = RVA, address − image base 0x82000000; mapping it through its section table gives
other bytes).

Evidence tags: **read** / [code] = read from the decompiled or disassembled code; **data** /
[measured] = measured on the shipped files, on captured palettes or on a D3D9 trace;
**bytecode** = read from shader instructions; **inferred** = fits the evidence but was not
read; **not established** = unknown. "impl" marks a fact found while implementing the toolkit
and not in a research report. Where a count was taken, the corpus is named.

The research reports with the full evidence trail are in `docs/re/` (index and corrections:
`docs/re/README.md`): `re/names.md`, `re/enums.md`, `re/pages.md`, `re/sync.md`,
`re/events.md`, `re/placement.md`, `re/skeleton_blobs.md`, `re/jiggle.md`,
`docs/re/physx_d6.md` (+ `.json`), `docs/re/vcolor.md` (+ `vcolor_shaders.json`),
`re/formats.md`, the `wp0` / `wp1` / `wp2` / `wp3` / `wp4` / `wp5` / `wp6` / `wp7` reports
(`wp1_renderer.md`, `wp2_physics.md`, `wp3_combat.md`, `wp4_ai.md`, `wp6_audio.md`,
`wp7_fx_camera_hud.md`, `wp2_ragdoll_rigs.json`; `wp0`, `wp3`, `wp4`, `wp5` and `wp7` cover the
script layer, combat, AI, runtime and effects), `re/events_table.json`.
Consumer-facing rules are in `ANIMATION_META.md`, `COMBAT_META.md`, `FX_META.md`,
`LEVEL_META.md`, `TEXT_ASSETS.md`, `PARTICLE_FORMAT.md`, `NAV_DATA.md`, `SOUND_META.md`,
`RAGDOLL_RIG.md`, `KAPOW_NAZ_FORMAT.md`, `FORMATS_MISC.md`, `FRAGMENT_FORMAT.md`,
`SCRIPT_DATABASE.md`. The shipped product is `watchmen-toolkit/` (PEP 517, `pip install .`,
console script `watchmen`, docs/ + provenance README). Counts marked Part 2 PC were reproduced
on the full extract and on `game.naz` (all six levels, seven blocks, the 26-character export).

## 1. Decompilation sources and tooling

### The Ghidra dump (`tools/ghidra/`)

- `ghidra_kapow_out` covers the whole executable: 38 shards, 0x401000–0x9e4400, plus four
  deep re-passes (`deep2`, `deep3`). The raw dump had 14,910 functions and was not complete.
- `__EH_prolog` is at 0x991850 (the property registration FUN_0047fde4 = 0x47fde4, the
  PhysicsWorld ctor 0x7eba0e and the CharacterAddonCtrl code 0x6563a0-0x657d54 were among
  the casualties) and ends in `push eax; ret`; Ghidra took it as no-return and cut
  every caller at the call (`mov eax,imm32; call 0x991850`), leaving 10-byte stubs.
  `tools/ghidra/FixEHProlog.java` re-bodies 2,000 functions (0x47fde4 decompiles to 175 bytes,
  0x7eba0e to 694).
- 1,191 of the 4,516 registered handler addresses were not functions at all (reached only
  through the registration table). `tools/ghidra/DefineKapowHandlers.java` creates and names
  them. SetupNewPage 0x5b7788 (9479 bytes), UpdatePagePlayPos 0x5b56a9 (8415 bytes),
  CharacterRoot.StateActive 0x6b367a and the CharacterAddonCtrl setup / update are of this
  kind.
- Functions 16,369 → 17,225 after the two scripts; functions of 12 bytes or less 2,473 → 622.
  After the later repair run the dump has 19,233 functions (`tools/ghidra/README.md`).
- A sweep of the 407,682 bytes of `.text` between those functions (measured) found
  324,616 bytes of code: tails of 21 existing functions (93,444 bytes) and 16,318 functions the dump
  never had (229,983 bytes), of which 13,576 are C++ unwind funclets, 1,219 frame-handler
  stubs and 28 registered command handlers (156 registrations). Those 28 have no function in
  the dump; they are in `wlib/reg_dump.json` and `tools/ghidra/handlers.tsv` all the same,
  because both tables are read from the registration calls. Where the recovered text lives and
  what it does not establish: `tools/ghidra/README.md`, "Further tooling".
- 0x5a0dfd (`Vec20_PushBack`) has 13,205 call sites in 392 functions, all `*__register`; 441
  is the number of `*__register` functions, the callers of 0x47eccc (measured). The functions
  still cut short in the dump (9 registration functions and 12 others) are not cut by a
  no-return flag: a 4-byte string tail or table entry was taken for a code pointer and a bogus
  instruction blocks the real one (read from the Ghidra bookmarks). For 19 of the 21 the
  decompiled C is the same as in the dump but for 0 to 13 lines (measured; the two largest
  were not compared); what was wrong is the size, the callee list and the callers of
  everything called from the tails. The nine register-function tails hold 548 handler variable
  records (225, 116, 68, 40, 34, 21, 20, 12, 12) and 9 command registrations (7
  `GFXPackageCtrl`, 2 `CharacterDef`); all are in the layout extraction and in
  `reg_dump.json` (measured).
- Shard references used below: `part_0019.c` (animation.cpp), `part_0021.c` (TransitToState
  at line 11791, EvaluateTransitions at 19256/19263), `part_0029.c` (enum registration).

### Byte-scan workflow

Caption strings and property hashes are pushed as code immediates (`PUSH imm32`). Scanning
`.text` for string VAs or hash immediates with Python + capstone finds them; a grep of the
decompiled `.c` files misses them. `wlib/gen_data.py` (CLI `watchmen gendata regdump EXE`) is
the registration scanner that regenerates `wlib/reg_dump.json` (format 2: a register-tracking
sweep, 5,090 props, the real classId, a handler slot per command); it is Ghidra-free (the
`.rdata` string map replaces a strings export), uses capstone and refuses a packed `.text`.

Retail DRM: Steam's SteamStub wrapper encrypts `.text` in place (extra `.bind` section holding
the stub; no SecuROM in either exe) but `.rdata` / `.data`
of the retail `KapowMulti.exe` are byte-identical to the unpacked exe, so the string harvest
works on a retail install.

### PS3 PPU vector idioms (the PS3 Part 2 executable)

`lvlx vN,0,p ; vspltw vN,vN,0` = splat of one float (217 of 239 sites load a TOC constant;
inferred from the addressing pattern, values read from the ELF bytes);
`stvlx v,0,p ; stvrx v,p,16` = unaligned 16-byte vector store (116 pairs, measured); `lvrx`
is never used. Ghidra prints a folded 16-byte constant as `auRam00000000` — read the float
from the `lvlx` operand address instead. A hash with the top bit set and a low half below
0x8000 is built as `li lo; oris hi`.

### Ruled out

- The raw dump is not the full executable: 2,000 SEH-prologue callers were 10-byte stubs and
  1,191 handlers undefined. "Not found" in the raw dump does not mean vtable dispatch or an
  external DLL.
- The CharacterAddonCtrl setup / update, SetupNewPage and UpdatePagePlayPos were never SEH
  stubs; they were undefined handlers.

## 2. Name hash, registration and enums

### Name hash (`re/names.md`)

- FUN_00423ce8: bit-CRC32, poly 0x04C11DB7, over every byte `& 0xDF` (`and cl,0xdf`
  @0x423cf7). FUN_00423d30 is the same, stopped at ':'. The fold is not upper(): '0'..'9' ->
  0x10..0x19, '(' -> 0x08, ')' -> 0x09, ',' -> 0x0C, ':' -> 0x1A, space -> 0x00. Letters and
  '_' fold as upper-casing does, so a letters-only name (`m_nbreastspringconstant`,
  `m_neaseinduration` = 0xc457385c, `m_nstartplaypos` = 0x125d3ff7) hashes like
  kapow_hash(UPPER(name)); a name with a digit or punctuation does not.
- FUN_00423d7c / FUN_00423ca1 hash raw bytes with a length and no fold (block-version
  checksum, music cue points, the subtitle key hash), not names.
- `FUN_00423c5b` (X360 `0x82a75de8`) is a different function, a rotate-by-9 XOR hash over
  (buffer, length) with two callers. On the consoles `slw` yields 0 for a shift count of 32 or
  more where x86 masks the count, so its value differs from PC for any string of four or more
  bytes (inferred from the instructions, not run).
- Console twins (X360 Part 2 / PS3 Part 2, read from the images): name hash `0x82a75d08` /
  `0xaaf50`; stopped at `:` `0x82a75c88` / `0xaafc8`; raw buffer `0x82a75d80` / `0xaaec0`;
  stateful update `0x82a75bf0` / `0xab070`; state reset `0x82a75c68` / `0xab048` (PC
  `0x423def`; PC finisher `0x423dd5`).
- Property hashes: every registered hash appears exactly once in the exe, at its registration
  (the `m_nbreast*` hashes among them); run-time reads go by slot, never by hash.
- Asset names use the folding hash too: FUN_005511b8 stores it at asset+0x50, FUN_0054ba59
  looks an asset up by it (impl). Bone names do not: FUN_0042c126 is `h*2+c` over bytes
  (see "Bone name lookup" in §4).
- Property type hashes in headers and the type id of `.kpw` records are the name hash of the
  type name.

### Command and native message signatures

- Command hash = name_hash(cpp name incl. `command_`) for a parameterless command (866
  distinct), else name_hash("name(type,type,...)") — no spaces, no return type (830 distinct).
  0x6eed1060 = command_set_achievement_earned(integer). All 1,696 distinct hashes reproduce.
  Type vocabulary: entity, integer, number, truth, vector, string, quaternion, list(T) and
  struct names; case is not recoverable. Inferred: the offline script compiler used this
  hasher on the signature string (no run-time code builds one).
- A handler takes one 4-byte slot per parameter, except vector = 3 and quaternion = 4.
- Native message hash (registration 0x50ed51, normaliser 0x4f9504, read from code;
  `kapow_props.native_message_signature` / `native_message_hash`). The registration string
  loses its argument names first:
  1. Let `p` be the first `(`. If there is none, the string is unchanged.
  2. Let `end` be the `)` just before the last `:` if that colon directly follows a `)`;
     otherwise the last `)`. If there is none, the string is unchanged.
  3. Let `c` be the first `:` at or after `p`. While `c < end`: erase the characters from
     `p+1` through `c` inclusive; set `p` to the next `,` after `p`, and stop if there is
     none; set `c` to the next `:` at or after `p`.
  4. `end` is not adjusted after an erase.

  Then hash = name hash of the result up to the first `:` (0x423d30). The hash is the message
  id: 0x4ef657 returns it, or −1 when the same hash is already registered with another
  signature, and 0x50ed51 registers it against the handler table 0xc8be20.
  `ApplyForceAtPos(position:vector,radius:number,force:vector)` →
  `ApplyForceAtPos(vector,number,vector)` → 0x400325F2; `IsLowViolence:truth` → 0xC8C0D741.
  In a mixed list an unnamed argument before a named one is erased with it:
  `GetNearbyAIAgents(number,agents:list(AIAgentInfo))` →
  `GetNearbyAIAgents(list(AIAgentInfo))` (the one shipped case). The 589 registration strings
  and their hashes are in `registered_names.json` (`native_messages`); the hash is not
  validated against a sender.

### Registration functions (`re/names.md`; `watchmen gendata regdump`)

    0x47e126 create class      (name, classId, nativeBase, scriptParent|0, flag, flag)
    0x47fde4 register property (hash, defaultVA|0, uiVA, flags, typeIdx)     flags in {0,1,3}
    0x47eccc register command  (name, kind, arg3, hash|-1, cmdHandler, stateHandler,
                                methodHandler, typeIdx)  -> 0x38-byte record, hash at +0x18
    0x47f650 native script function (signature "Name(type,..):ret", handler, doc)

441 classes, 5,090 property registrations (3,695 distinct hashes, all named), 6,630 command
registrations. typeIdx indexes DAT_00c89ebc = the DECLARING CLASS (equal to the class's own
id at 4,262 / 5,090 property sites), not a value type. No property name is pushed at a
registration site; it exists only as the hash. `kind` (+0x10) is 1 or 3 — 3 on commands,
`_root` and library methods, 1 elsewhere; no reader was found; its meaning ("callable from
outside") is inferred. `arg3` is the owning state's command-list index. Record +0x28 is the
declaring class (`DAT_00c89ebc[typeIdx]`, 0x47eccc). A class may be registered twice
(AnimationStateWM at 0x605ce3 and ~0x60b1xx); all four code refs to hash 0xc457385c are
registrations. Run-time reads of a property go through the native record at [node+0x10] at
fixed offsets assigned at registration (4 × registration index), never by hash.

Commands: the handler sits in one of three slots. cmdHandler (3,939, real hash) /
stateHandler (841: _root, StateActive, StateMain ...) / methodHandler (1,850: Init, ...).
State functions and script methods carry hash 0xFFFFFFFF and cannot be sent by hash
(FUN_004f99a4 refuses that value).

Property record (0x47fde4; 0x18 bytes):

| Offset | Content |
|---|---|
| +0x00 | flags |
| +0x04 | declaring class |
| +0x08 | global property descriptor from 0x4ee10d(hash) |
| +0x0c | 0 |
| +0x10 | default string or 0 |
| +0x14 | UI string |

A registered default is parsed into the slot at instance creation; fragments omit
default-valued properties, so `engine_schema.defaults(class)` is needed to read a fragment.

Handlers shared by many registrations (read from code; counted in `wlib/reg_dump.json`):

- 0x87b96e is the handler behind 86 registrations: 35 `*.command_is_behavior_running`, 11
  `command_condition_true`, the other 40 (most of them `is_…` queries) registered three times
  or fewer each. It writes 0 to the result and returns, so the default
  `command_is_behavior_running` answers false.
- 0x69ed29 returns self-data `[+0x10]->[+0x14]` for 5 registrations, among them
  `CharacterVisual.command_is_in_ragdoll_mode` and `Perception.command_get_target`.
- 0x73b97c (`FollowPivotBehavior.command_fill_debug_view`, hash 0xc5b7befb) builds AI debug
  text and writes nothing but a loop counter in its own locals (read from the recovered
  decompilation).
- 0x8127b5 (`SaveFragment.command_save_fragment`) casts self (0x48dc5f, class global
  0xe14674) and calls 0x48d55e, which is a bare `ret 4`: the command does nothing in this
  build.
- 0x770cfc (13 registrations) and 0x6a1b09 enter the class's handler-table entry 2 through
  0x47a533; 0x59d825 and 0x83ffea enter entry 0. 0x75b9a9, 0x84a3b2 and 0x7bfcda invoke
  handler-table entries 4, 3 and 11 through 0x479874. 0x7f0655 (10 registrations) calls
  0x48f65c(self, 0). 0x738a6c stores its argument in a state local and clears the wait
  (+0x2c = -1, bit 0x10000 of +0x30).
- `is_attack_successful` returns 1 through the shared body 0x7f09ac in 33 of its 37
  registrations; `BehaviorHandler` 0x618da2, `Underboss` 0x891084 and `UnderbossCombat`
  0x8832a4 forward it to their current behaviour (1 when none); the only body returning 0 is
  `UnderbossPhase1` in state `StateFleeToJumpPoint` (0x87b96e, Part 1 only).

Built-in node properties go through one typed wrapper per data type: 0x505514 integer,
0x505553 biginteger, 0x505592 number, 0x5055d1 string, 0x505610 truth, 0x50564f vector,
0x50568e quaternion, 0x5056cd netparticipant, entity wrappers via 0xe151a0; type objects are
created in FUN_00501f6a. That is what types a built-in property (impl: 862 names typed this
way); biginteger is 8 bytes in a fragment.

Property names: a native class registers each name with one literal; the capitalised variants
in the executable are editor captions (written to the caption slot +0x2c in
`TriggerActionCharacter__FilterExposedProperties`). 1,371 registrations, 1,224 hashes; the
dictionary had another case on 61 of them. `PLATFORM`, `Scene` and `physicsTimepassed` are
names of their own (BuiltinModule globals). `is3D` (Sprite 0x4c7801) and `is3d` (SoundAsset
0x55284f, MediaStreamAsset 0x554b67) are the one per-class difference.

`Node` property `visible`: getter `0x48e01b`, setter `0x48f69a`, byte at node +0x55. The
getter body is shared with `ToolbarOptions::GetUseSystemColors`, which is the name the dump
shows.

### Enum registration (`re/enums.md`)

FUN_005052c9(family, "PREFIX___NAME", value) is the only writer of the enum table
(0xc8bd78); FUN_0050574a is a thin wrapper. 1,813 registrations in 65 functions, 186
families, 1,801 names. The family is the first argument, not the text before `___`
(CHARACTER_TYPE___X goes into CHARACTER_TYPES). Nothing is loaded from game files. LANGUAGE
names are built at run time (0x47ffdd-0x48017d). The 34 families the toolkit uses are in
`wlib/engine_enums.json`; `re/enums.md` lists the animation ones in full. Animation families
are registered in 0x809e94 and 0x5e50f7; ANIMATION_HEAD_MODEL at 0x80b33e-0x80b4a0
(`part_0029.c` @0x0080b31c).

| Family | Values |
|---|---|
| ANIMATION_CRITERIA | VALUE 0, ACTION 1, ENUM 2, EVENT 3, PLAY_TIME 4, PLAY_POS 5, REVERSE_PLAY_POS 6, OVERLAY_PLAY_POS 7, REVERSE_OVERLAY_PLAY_POS 8, ANIM_PLAY_DONE 9, FORCE_ANIM 10, ANY_OF 11, ALL_OF 12 |
| ANIMATION_ENUM (criteria enum variables) | 0 ATTACK_DIR, 1 CHARACTER_MODE, 2 ATTACK_TYPE, 3 ATTACK_POSE, 4 DAMAGE_POSE, 5 WEAPON_ANIMATION_TYPE, 6 MODEL_ANIMATION_TYPE, 7 TARGET_MODE, 8 OVERRIDE_ATTACK_COMBO, 9 STATE_CHANGE_OVERRIDE, 10 TARGET_LOCK, 11 OPPONENT_MODEL_TYPE, 12 OPPONENT_WEAPON_TYPE, 13 KNEE, 14 SPECIFIC_MODEL, 15 SCENE_ID |
| OPPONENT_MODEL_TYPE | NONE 0, RORSCHACH 1, NITE_OWL 2, ENEMY_01 3, ENEMY_02_BIG_GUY 4, UNDERBOSS 5, ENEMY_03 6, ENEMY_04 7 |
| WEAPON_ANIMATION_TYPE (variable 5) | UNARMED 0, BASH_1H 1, BASH_2H 2 |
| OPPONENT_WEAPON_TYPE (variable 12) | NONE −1, BASH_1H 0, BASH_2H 1 |
| WEAPON_TYPES (registered in 0x6726d6; prefix WEAPON_TYPE___) | NONE −1, BASH_1H 0, BASH_2H 1 |
| WEAPON_TYPE (0x8bb4aa; same prefix) | MELEE_ONE_HAND 0, MELEE_TWO_HAND 1 |
| ANIMATION_EVENT_TYPES | PLAY_POS 0, ENTER_STATE 1, LEAVE_STATE 2, TOTAL_PLAY_TIME 3 |
| ANIMATION_SYSTEM_NODE_TYPE (`m_iAnimationSystemType`) | BLEND 0, CRITERIA 1, SLOT 2, STATE 3, TRANSITION 4, CLASS 5, EVENT 6, STATE_GROUP 7, PLAY_POS 8 |
| ANIMATION_LAYER | the AnimLayer enum (kernel/animation/animlayer.cpp) |
| LANGUAGE (0..5; 0x47ff8c) | English, French, Italian, German, Spanish, Danish; engine codes uk fr it de es dk (0x45fb96; consumers 0x54e890, 0x47b9ec) |
| PLATFORM (0..3) | EDITOR, PC, X360, PS3 |
| VolumeCurve (0x4d9436) | 0 linear, 1 VOLUME_CURVE_LOGARITHMIC, 2 square root, 3 = 1 − f(x·π/2) |
| frameRateScale (editor dropdown) | FULL 1, HALF 2, THIRD 3 |
| blendType (editor string) | standard 0, add 1, subtract 2, manual 3 |
| renderType (editor string) | Standard 0, Standard with blending 1, Glass 2, Water 3, Hair 6, SkyBox 7, Sprite 9, Falloff 10, Wet surface 11 |
| multiListenerDistanceAttenuationType | ADDITIVE 0, SATURATE 1, CLOSEST 2 |

ANIMATION_HEAD_MODEL (`m_iHeadModelType`; PUSH pairs): LARGE_HEAD_1=0 _2=1 _3=2
MEDIUM_HEAD_1=3 _2=4 _3=5 LARGE_3KT=6 SMALL_HEAD_1=7 SMALL_1KT=8 MEDIUM_HEAD_MERC_1=9 _2=10
SMALL_HEAD_MERC_1=11 _2=12 LARGE_GOATEE=13 MED_GOATEE=14 UNDERBOSS=15 NITE_OWL=16
TWILIGHT_LADY=17 DOMINATRIX_1=18 GIMP_1=19 GIMP_2=20 DOMINATRIX_2=21 HEAVY_1=22
DOMINATRIX_3=23 DOMINATRIX_4=24 DOMINATRIX_5=25 GIMP_3=26.

CHARACTER_TYPES (prefix CHARACTER_TYPE___; 32 names): INVALID=-1 RORSCHACH=0 NITE_OWL=1
BIKER=2 BIKER_BIG=3 PRISONER=4 PRISONER_FAST=6 THUG=8 THUG_BIG=9 THUG_FAST=10 THUG_LEADER=11
MERCENARY=12 MERCENARY_FAST=14 MERCENARY_LEADER=15 MINION=16 MINION_FAST=18 MINION_LEADER=19
COP=22 COP_LEADER=23 COP_FAST=24 UNDERBOSS=25 BIKER_HEAD=26 PRISONER_ELITE=27 GO_GO_DANCER=28
HEAVIES=29 KNOT_TOP_NORMAL=30 _FAST=31 _BIG=32 DOMINATRICE=33 GIMP=34 TWILIGHT_LADY=35
GIMP_WITH_GAGBALL=36. It is not what the animation criteria test as the opponent's model
type; that is OPPONENT_MODEL_TYPE.

CHARACTER_BONE_TYPES (`CharacterVisual.SetupBoneMap` 0x67a31e, 23 `FindBoneIndex` calls): 0
Head, 1 Neck, 2 Spine2, 3 Spine1, 4 Spine, 5 Pelvis, 6 L UpperArm, 7 L Forearm, 8 L Hand, 9
L Thigh, 10 L Calf, 11 L Foot, 12 R UpperArm, 13 R Forearm, 14 R Hand, 15 R Thigh, 16 R
Calf, 17 R Foot, 18 GamePivot, 19 L Clavicle, 20 LUpArmTwist, 21 R Clavicle, 22 RUpArmTwist
(same 23 strings in the same order on X360 Part 2, `0x82e21590`, and PS3 Part 2
`CharacterVisual.SetupBoneMap` 0x76ae68); command_get_boneID 0x69b54a returns entry 18 for a
type out of range.

TARGET_MODE is not an exe enum; its values are written by script code
(`CharacterVisual.command_update_animation` 0x69b988), table in `combat_meta.TARGET_MODE`;
the editor lists the CHARACTER_MODE names for it (`AnimationEnumEnumName` 0x7f0934).

Ruled out: a merged "WEAPON_TYPE enum BASH_1H/MELEE_ONE_HAND=0, BASH_2H/MELEE_TWO_HAND=1" —
those are two families sharing a prefix, and the animation criteria test neither.

### Fragment property keys

- `kapow_fragment_keys.pkl` (4564 keytable entries) is the crack result: names plus inferred
  value types (types drive parsing: `NAMES[hash]` selects the decode path). It is not
  regenerable; `gendata keys-export` / `-import` round-trips it to readable JSON. 480 keytable
  entries with digits in their names were filed under the wrong hash before the `& 0xDF` fold
  was known.
- `prop_hash_dict.pkl`: exe + naz string harvest with identifier tokenization
  (camelCase / underscore sub-tokens — names like 'Speed' only occur as substrings). Fully
  de novo from a retail install. Functional check against the canonical pb-family JSONs (297
  files): 202 byte-identical, 3 case-only, 92 strictly better (more hashes named), 0
  regressions. A null-terminated-string regex (`[\x20-\x7e]{3,}\x00`) backtracks O(n^2) on
  NUL-free printable stretches; `gen_data._runs` is the linear split-scan replacement.
  Naz-wide string harvest ~21 s.
- `prop_names_from_reg.json` is a pure aggregation of reg_dump (first registration wins incl.
  Nones; one `classes[]` entry per registering class object — duplicate class names stay
  duplicated); `engine_schema` derives it at run time and it is not shipped.
- `wlib/engine_schema.py`: `defaults(class)`, `prop_info` / caption, `BASE_FPS`. The
  interpreter's fallback defaults match the registered defaults.
- Type records in a fragment stream are `FFFFFFFF + nodeId + word count + TypeName`; they are
  not properties. Sync-marker names are m_nsupersynclocal1..8 / m_nsupersyncremote1..8 (hash
  pairs 0xee2a40XX / 0x4cadfbXX, default -1.0). The last unknown key, `0x0991b0d4`, is
  `CharacterGroup.m_ezonetrigger` (member +4, registered as an entity reference, caption
  "Combat Zone"; `name_hash` of the name gives the key; 141 occurrences, 22 of them set). No
  unknown key remains in the 906 Part 2 PC fragments.

## 3. Script runtime, frame and clocks

### Command dispatch

- **Command by index** (0x596d91 → 0x47c9fd): refused if the type has no script class, the
  entity flag bit 0 is set, the index is out of range, or the stored hash differs. Otherwise
  a task is created if absent (`_root` pushed and run once), the command function is called
  synchronously, and the after-call runs at depth 0. There is no "enabled" test.
- **Send by hash** (0x47decf), by dispatch kind (`ScriptClass_ResolveCommandTable` 0x47c752;
  `reg_dump.json` `dispatch_kind`, 3,166 / 295 / 61 / 134): kind 0, one version owned by
  `_root` — the root command, creating a task if none; kind 1, one version owned by a state —
  needs a live frame of that state, else unhandled; kind 2, several versions and none owned
  by `_root` — needs a task, the topmost frame whose state owns the hash wins, else
  unhandled; kind 3, several versions with a root one — with no task the root version runs,
  with a task the topmost owning frame wins and the `_root` frame at the bottom supplies the
  root version as fallback (0x47c95b pushes `_root` as a normal frame). Unhandled sends go to
  the native message table in 0x4f92a2.
- A class method is invoked by its class-record slot through the thunk 0x479874(handlerVA,
  ctx, args), which sets the script context global 0xe12d9c; an AnimationStateGroupWM
  command is dispatched by command-table index (0x596d91: idx 6 is
  `command_get_valid_state`, hash 0x499d201a at [class+0x1c][6]+0x18).
- **State changes** are one pending record per task; a second request overwrites the fields
  and appends saved arguments. `CALL_STATE` pushes above the named state; `GOTO_STATE` /
  `LEAVE_STATE` unwind through it, then push the callee (0x47a572).
- **Task lifetime**: the stack is `_root` at the bottom plus states; a task is released to a
  pool of 10 when fewer than 2 frames remain after a call or resume (0x47b8ba, 0x47a836). The
  shared `_root` sleeps with `WAIT_SECONDS(-1.0)` and never leaves by itself. A kill (entity
  deleted, task reset) skips state exit blocks. No instruction in any indexed function sets
  the "marked for suspend" task flag 0x40000, so suspend never happens on PC (inferred from
  the absence of a writer).
- `_root` is never absent from a live stack. All 106 `_root` functions (441 classes) only
  declare locals and sleep with `WAIT_SECONDS(-1.0)`. Root leaves only on a kill or on a
  request it cannot satisfy; `Task_LeaveFrame` 0x47a165 then frees the pending record and
  0x47a836 releases the task. State changes are compiled three ways: 359 goto/leave requests
  (0x47a513), 207 call requests (0x47a533) and 48 direct pushes from a state body (0x47a447).
  Every request targets the owner state of the requesting code; no direct push names `_root`
  (all 48 carry an immediate index; 0x7e53eb passes 4, `State_CheckDeviceX360`). Five
  root-owned commands compile a bare `LEAVE_STATE` = 'unwind all states and release the
  task': `AnimationCtrlWM.command_terminate`, `CharacterHeadCtrl.command_terminate`,
  `CharacterVisual.command_terminate`, `CircleTargetEnemy02.command_react_to_attack`,
  `SpeakCtrl.command_initialization`. A request whose target state is not on the stack
  unwinds everything, root included, and drops the callee.
- **Type operations** take `[ret][right][left]`. List `+` (0x504e0d case 0) returns the left
  list's slots followed by the right's, as raw slot copies. One compiled use:
  `AnimationCtrlWM.command_get_list_of_top_level_anims` (0x5b112c).
- **Type ids**: 0 nothing, 1 number, 2 integer, 3 biginteger (2 slots), 4 string, 5 truth, 6
  vector (3), 7 quaternion (4), 8 color, 9 netparticipant, 10 list, 0xb dict, 0xc entity, 0xd
  struct, 0xe asset family. Heap-owning: 4, 10, 0xb, 0xd.
- **Builtins** (0x47ff8c): 123 functions and 19 properties (`wlib/builtins.json`). Float to
  integer truncates toward zero (`c_int` / `NumToInt`, 0x990ba0 = `cvttsd2si`). Direction
  vectors (bytes): in (0, 0, 1) 0x9e808c, out (0, 0, −1) 0x9e80cc, right (1, 0, 0) 0x9e806c,
  left (−1, 0, 0) 0x9e80ac, up (0, 1, 0) 0x9e807c; `pi` = 3.14159274 (0x9f52a8).
- **Entity index**: a new entity takes the lowest free, non-reserved index (0x4f01a9).
- **Property by hash** (0x4ff93b, 0x50e94c): get tries the script member, then the native
  property; set tries native, then the script member. A native property with no setter
  swallows the write. The set-by-hash wrapper 0x510737 queues the property for network
  replication; set by slot has no such hook. It acts only if the entity has an entry for that
  property in its table at `entity+0x38`, `NetworkPlatformManagerWinsock` (0xd91cc8) is
  started, and `NetworkManager+0x7c` is non-zero. The dirty list is in the `NetworkManager`
  (`+0x64`, keyed by listener, then entity). The platform manager is started only by the
  native message `NetworkManager.StartNetwork`; its hash 0x64a4ab78 occurs nowhere in the exe
  and the builtin `GetNetworkManager` has no caller, so no compiled script starts it.
- **Node enable**: `Node+0x54` = own `enabled`; `Node+0x40` bit 0 = all ancestors enabled
  (pushed down by 0x48e51d, which stops at a node whose own flag is clear); `globalEnabled`
  (0x481762) = both; `Node::IsThisEnabled` = +0x54 alone; virtual slot 3 (0x481773) =
  `globalEnabled` and not suspended (`+0xc` bit 0). Virtual +0x68 is called on each node
  whose `globalEnabled` changed. `on_enabled` / `on_disabled` are sent by the script setter
  0x48f65c, only to the node whose own flag changed.
- **`DeleteNode` is immediate** (scalar deleting destructor, virtual +0x2c). Deleting the
  running handler's own entity frees the task stacks and the entity data under the handler.
  From a command handler the runtime itself then does one stale byte write (`task+0x46`); any
  handler code after the call runs on freed memory. From a state body the kill re-enters the
  state function, and the after-call then uses the freed entity (inferred crash at
  0x47a741). No shipped `DeleteNode` site (60) passes its own entity.
- **Savepoint / rewind is residue on PC**: `flushrewind` sets `scene+0x2e9`, never read;
  `rewindResumeTime` (`scene+0x2cc`) is always -1.0; play mode 3 is tested but never set;
  `rewind_or_retry_finished(integer)` is never sent; `recordInSavepoints` (`entity+0x2d`) has
  only its getter and setter.
- **Game mode**: `ProjectLib.g_igamemode` (+0xac) is written only by `MainMenuSceneCtrl` (7
  sites; 4 = MAINMENU in `initialize_external`). `GetGameMode` (0x7f09db) returns it if
  non-zero, else `g_ioverridegamemode` if non-zero, else 1. `PlayerManager.command_game_event`
  (0x7f9d1b) sets players up on event 1 and handles only 1, 2, 0x6a and 0x6b; player
  controllers are activated only there: the hash of `PlayerCtrl.command_activate_player_ctrl`
  (0x22213c24) occurs at 0x7fa57a and 0x7fa773 (both in the event-1 branch), at 0x7fb557
  (`command_character_take_control` 0x7fb48b, whose loop needs the editor-selection builtin
  0x4fa89c, which returns 0) and in the registration 0x803a60; the handler address 0x7f4929
  occurs only in the registration (0x803a5b). Events 0x6a / 0x6b are PLAYER_VS_PLAYER_BEGIN /
  END. There is no mid-level join (read from code; a send with a hash computed at run time is
  not excluded).
- `nanimspeed` (strings.tsv 0x00a5f3f0) is registered once (0x6c1259) as a script-VM local
  of an AI / character script class (alongside nsign, etargetlist...); no value anywhere in
  extracted data; nothing reads it for playback.

### RNG

One script generator, MT19937 seeded with 5489 in the module constructor (0x47fbd3); no
handler in the lifted scripts calls `rand_seed`. `rand_integer(n)` (0x47aa2e, also
FUN_0047aa2e): rejection sampling with limit = (0xffffffff / (n + 1)) × (n + 1), then `r % n`
— range 0..n−1, slightly non-uniform, and a division by zero for n = 0. `rand_number`
(0x576418): r × 2^-32 (double 0x9f5300) stored as a float32, so the range is [0, 1] with
probability 2^-25 of exactly 1.0. 1.0 is returned for draws ≥ 0xFFFFFF80. No handler that
calls `rand_number` (116 sites, 67 functions) converts a value to an integer in the same
handler; `rand_integer` has 27 sites. Every float-to-int conversion in the 4,516 registered
script handlers is a call to 0x990ba0 (77 sites in 39 handler bodies; no inline conversion
instruction; the 28 handlers outside the function index have none). None takes a random
value: 38 convert pow(2.0, x) and one an integer power (0x5aa626), 14 viewport sizes, 8 menu
values × 10.0, 8 clock values, 6 text or fixed arithmetic. The two value × size + 0.5 sites
use a clamped input × (count − 1) (`LockpickCtrl.StateActive` 0x794bca) and a product of two
animation values (`AnimationStateWM.AnalyzeFootsteps` 0x5f2db5) (read from code). Not
scanned: conversions inside native commands that take a `number`. The particle RNG is
separate (§12).

### Frame, clocks and the native update

- **Frame**: clocks, then the native update 0x495fec, then ScriptUpdate 0x495e41
  (pre-message, the scene, a snapshot of entities in table-index order — resumed if
  `useRealtime` or the game step is > 0 — post-message), then both frame counters increment
  (they are always equal). `WAIT_FRAME` wakes at counter + 1. `WAIT_SECONDS(t)` wakes at
  `now_ms + trunc(t × 1000)` (1000.0 at 0x9e5a60); `t < 0` means never. The native update runs
  the first node list (0xe14454, virtual +0x30 false), then three calls, then the second list
  (0xe14448).
- **Between the native lists**: 0x5427a6 ticks every model-animation instance (playhead +=
  speed × `timepassed`, joints written, skin matrices and software skin jobs when model flag
  bit 18 is set); 0x529f71 ticks every animated `TextureSheet`; 0x50305c fetches PhysX
  results for scenes 0 (rigid) and 1 (cloth) if they are simulating, sends `SimulateDone`
  when scene 0 was fetched, and calls virtual +0x9c once per frame on the owner of each moved
  actor. Both scenes are started at the end of render prepare (0x567c04, cloth first), so the
  rigid scene simulates during the render of frame N and is normally fetched in frame N+1;
  physics-node virtuals can force an earlier blocking fetch. Cloth is fetched in the same
  frame, at the start of the draw stage (0x5632f6) or already in 0x567c04 if its job has
  finished. All software skin jobs are waited by 0x42f352 at the start of the draw stage. The
  animation tick 0x53fee6 runs only here, so a pose changed by script later in the frame is
  not in that frame's software-skinned mesh. The three calls read `timepassed` as the last
  first-list node left it.
- **Clocks** (writer 0x496294; dt = ms / 1000): the real step is capped at 0.1 s (double
  0x9e9628, float 0x9e664c); game step = real step × scene+0x2dc × scene+0x2e0; pause zeroes
  it. The writes of game time and `timepassed`, and the pause zeroing, sit in the
  `scene+0x2d8 == 0` branch: when that byte is set, only ScriptUpdate runs and neither is
  updated. `Node::FrameUpdateMSG` 0x48e3a9 sets 0xe14304 to 0xe14308 (game step) or 0xe14300
  (real step) when node +0x2c is set. During the script update 0xe14304 holds the step chosen
  for the last natively updated node (0x495fec does not restore it). No node of a second-list
  class has UseRealTime set in the Part 2 PC data (906 fragments + scene, 137 true).

| Global | Meaning |
|---|---|
| 0xe14300 | real frame dt, capped at 0.1 s (f32 0x9e664c) |
| 0xe1430c | real time |
| 0xe14308 | real dt × scene +0x2dc × +0x2e0 (game dt; 0 in pause mode 2) |
| 0xe14314 | game time |
| 0xe14304 / 0xe14310 | "current" dt / time (`timepassed`): the game values, or the real ones for nodes on real time |

- **Scene play mode**: `SceneNode` singleton `[0xe14324]`+0x2d4: 0 PLAY, 1 STOP (set by the
  constructor at 0x4934cc; Play 0x495d11 sets 0 and runs at scene open, 0x8bef31, unless the
  command-line switch `stopmode` is given), 2 PAUSE (0x495d93; cleared to 0 at 0x495e2b), 3
  rewinding (tested in 0x495d93, never written). In STOP, `AILib.CharacterRootToAiType`
  0x5974a3 returns 0 for every character. `LoadBlock::Unload` 0x4a02f0 unloads a common base
  block only when the mode is not 0.

### Script database

`Database.bin` under `/data/tnt/production/` (path built by 0x4ef41c; loader 0x47c5f5, called
from 0x820e5b). Layout: `u32 n; n × [u32 len ≤ 0x3fe; char[len] "name:type"]; u32 m; m ×
[u32 len; char[len] message]`. `wlib/script_database.py` (`watchmen scriptdb`) reads it: the
Part 2 PC file has 3,693 properties and 1,672 messages and is consumed exactly, 174,824 of
174,824 bytes (SCRIPT_DATABASE.md).

### `MasterSceneCtrl.StateActivateScene` (0x7a63b2)

```
_tisactivatingscene = true
eloadtext = _eloadscreen.findnode("LoadingText")
if eloadtext: SetTextResMode(1); SetTextSlotIndex(ProjectLib.TextslotIndexFromSceneId(eScene.m_isceneid))
eScene.command_activate()
both tutorial load screens: SetRunScript(false); SetupLoadscreenHint(); ResumeScript; RecursiveSetOpacity(1.0)

if eScene.m_ecutscenemovie and tPlayCutscene and !_trestorecheckpoint:
    if eScene == _emainmenuscene: _efadectrl.command_set_value(1.0)
    else: _eloadscreen.enabled = true; _efadectrl.command_set_value(0.0)
    if !getconfigtruth("skipcutscenes"): CALL StatePlayMovie(eScene.m_ecutscenemovie, eScene)

SceneCtrlLib.LockMenuInput(true)
SoundCtrl.command_set_master_volume(0.0)
if eloadtext: MenuLib.g_ebuttonpulsatectrl.command_start_pulsate(eloadtext)

if _trestorecheckpoint:
    _eloadscreen.enabled = true; _efadectrl.command_fade_out()
    do WAIT_FRAME while !_efadectrl.command_is_faded_out()

if eScene.m_tisloadblock:
    if SceneNode.GetLoadedLoadBlock() == 0:
        CALL StateWaitForLoad(eScene); eScene.command_finalize(); WAIT_FRAME
    estreamblock = StreamBlockManager.command_get_streamblock_for_loading(_trestorecheckpoint)
    if estreamblock:
        estreamblock.AddLoadedCallback(self, "callback_streamblock_load_done(truth)")
        tresult = <start load>
        GameStateCtrl.command_set_current_streamblock(estreamblock)
        ntimer = realtime
        while !tisstreamblockloadingdone: WAIT_FRAME

if eloadtext: command_stop_pulsate(eloadtext)
while MenuLib.g_tisconsoleuivisible: WAIT_FRAME
WAIT_FRAME
if tFade: _efadectrl.command_fade_in(); do WAIT_FRAME while !command_is_faded_in()
_eloadscreen.enabled = false
while CharacterLodCtrl.command_get_num_incoming() > 0: WAIT_FRAME

if _trestorecheckpoint: GameStateCtrl.restore_checkpoint()
else:                   GameStateCtrl.command_reset_checkpoints()
broadcast_gameevent(1, self, 0.0, eScene)                         # SCENE_ACTIVATED
broadcast_gameevent(_trestorecheckpoint ? 5 : 4, self, 0.0, eScene)
nmastervol = SoundCtrl.command_get_master_volume(); set_master_volume(0.0)
while MenuLib.g_tisconsoleuivisible: WAIT_FRAME
WAIT_SECONDS(0.5)                                                 # 0x9e6174 = 0.5
broadcast_gameevent(6, self, 0.0, eScene)                         # SCENE_STARTING

if tFade:
    _efadectrl.command_fade_out()
    while !command_is_faded_out(): set_master_volume((1 - _efadectrl.opacity) * nmastervol); WAIT_FRAME
else: _efadectrl.command_set_value(0.0)

set_master_volume(nmastervol)
SceneCtrlLib.LockMenuInput(false)
_ndebugscenecountdown = _ndebugscenesoakduration
ProjectLib.SetRichPresenceData()
exit block (skipped on kill): _tisactivatingscene = false
```

`command_finalize` is sent only when no load block was loaded yet. The start cutscene needs a
movie on the scope, `tPlayCutscene`, no checkpoint restore and config `skipcutscenes` false.
The closing volume ramp is (1 − fade `opacity`) × the saved master volume. Events: 1, then 5
(restore) or 4, then 6 after 0.5 s. The statement order between these points was lifted once
and not independently re-read.

## 4. Animation clips

### `.animation` header [measured: 1185/1185 files, zero mismatches]

    [f32 keyRate][f32 duration][u32 0][u32 keyCount][u32 frameRateScale]
    [u32 0][u8 1][u32 nameCount][names][tracks t in {0,1,2,3}][u8 0 terminator]

| Offset | Field | Meaning |
|---|---|---|
| 0 | f32 keyRate | keys per second == (keyCount−1)/duration exactly, 1185/1185 |
| 4 | f32 duration | true clip duration in seconds |
| 8 | u32 | 0 on all files |
| 12 | u32 keyCount | keys per track (t1/t2 tracks) |
| 16 | u32 frameRateScale | 1 = FULL, 2 = HALF, 3 = THIRD of the 30fps engine rate |

Decomp anchor: `Animation::SetFrameRateScaling` / property `frameRateScale`, editor dropdown
`items=FULL:1,HALF:2,THIRD:3` (`part_0019.c`, kernel/assets/animation/animation.cpp). Scale
histogram over the 1185-file corpus: FULL 71, HALF 354, THIRD 760 (49 FULL over the 1163 clips
of the character set). keyRate = 30/scale nominally (THIRD ≈ 10Hz, HALF ≈ 15Hz, FULL = 30Hz); the
stored keyRate varies slightly per clip because it is (nk−1)/dur. The name list starts at
byte 29 in all 6,912 clip files of Parts 1 and 2 on all platforms; `bake_v4.NAME_SCAN_START`
= 20 (the scan starts behind the five-word header). Leftover: 1 byte (the morph-block flag, 0; see "Reader" below) on every
file. Type-3 tracks: pos is f32x3 + 4 PAD bytes (0 in 10705/11125; 17 junk values repeated
across files = baker uninitialised memory, not data).

Reader [code]: `Animation` vfunc 24 0x5434af reads keyRate → +0x9c, duration → +0xa0, @8 → +0xa4, keyCount → +0xa8,
frameRateScale → +0x98; then 0x540fba reads @20 as an **event count** followed by 12-byte records `[u32][f32][u32]`
(0 in every file). A `u8` flag then creates `CompactSkeletalAnimData` (0x592d62; vtable 0xa406e0), whose reader 0x593fc3
reads the name list (`AnimData` base) and per track a `u8` type; factory 0x592e87:

| Type | Class | Reader | Payload |
|---|---|---|---|
| 0 | `AnimTrackTransFP` | 0x591698 | `u16 n`, constant rotation f32×4, `n` × int16×3 positions |
| 1 | `AnimTrackRotFP` | 0x591534 | `u16 n`, constant position f32×3, `n` × int16×4 rotations |
| 2 | `AnimTrackRotTransFP` | 0x591839 | `u16 n`, `n` × int16×7 |
| 3 | `AnimTrackConstPose` | 0x5918ce | 32 raw bytes, copied whole by its sampler 0x591899 |

The type-3 pad bytes are the fourth component of the pose's 16-byte position vector: read and copied with the pose,
not interpreted by the track. The last `u8` (the "terminator") is a second flag: 1 would create a `MorphAnimData`
block (0x58fac4; reader 0x58f3e9: name list, then f32 × channels × keyCount); every shipped clip has 0.

Console copies are big-endian; the PS3 and X360 copies of `EN4_EXP_MOV_dance_cage_small_C`
bake bit-identical to the PC cache (measured).

### Sampler [code]

Clip time → key (0x591975): t = clamp(time, 0, duration); f = (keyCount−1) × t / duration;
floor / ceil; lerp for positions, sign-corrected nlerp for quaternions. One index pair for all
tracks. keyRate and frameRateScale are not read by the sampler.

### Playback rate [code]

The page rate (SetAllSlotBlends 0x5b4ef7, 0x5b5175-0x5b51d0), over the slots of the page's
first populated layer:

    page.rate += ctrl.speed x slot.speed x slot.weight / clip.duration
    ctrl.speed = class m_nspeedfactor x GetGameSpecificSpeedFactor() x ctrl m_nspeedfactor

GetGameSpecificSpeedFactor 0x5ab837 = the controller's +0x10c slider times a game-mode
factor. No term depends on the character's velocity; no lifted script writes
`m_nspeedfactor` at run time. slot.speed is the slot's `speedFactor` property: +0x64 on an
AnimSlot (getter 0x4b30b1), +0x84 on an AnimBlendSource (impl), +0x134 on a
`PropertySequenceNode`. 707 of 1,290 states run at a speed other than 1; 214 of the 240
primary pair masters at 1.1. The slot `speedFactor` of the walk / run slots is 0.93 – 1.25
(anim_meta `speeds`, measured on Part 2 PC / Xbox 360 and Part 1 PC). A layer has two
parallel lists: the speed is read from `eAnimSlotList[i]`; weight (+0x80) and duration come
from `eBlendSourceList[i]`. A source's own `speedFactor` (+0x84) is 1.0 from its constructor
(0x594ba7) and is not copied from the slot (`SetAnimSlot` 0x593ac3 copies only the clip
name); the source's own update forms `slot × source` at 0x596346. Not read: who fills
`eAnimSlotList`.

Measured: at the header rate the `game_pivot` root speeds are walk 1.07–1.47 m/s, run
3.63–5.21 m/s (Part 2 PC / Xbox 360, Part 1 PC). `RSH_COM_MOV_run_cycle` is 1.333 s long.
Inferred: a captured "strut" of 1.43-1.63 s is a VELOCITY-blend page of the walk and run
clips (rate = Σ speed × weight / duration), not one clip sped up. On a capture window locked
to a single clip (`special_stomp`) the play position advances 0.3696 clip-frames per capture
frame with a sub-frame, linear residual: no hidden speed multiplier at the palette level.

Dance clips play at the header rate: `dance_cage_small_C` is 882 keys / 88s authored.

### Toolkit: baking

- `fps = (frames-1)/duration` (== keyRate × upsample); `bake_v4.fps_for()` is the one formula
  everywhere; bake_v4 returns true seconds. The `_bake` npz stores an explicit `fps` field;
  every clip is written at its header rate. `BASE_FPS` is in `engine_schema`.
- FACE clips (static poses, nk=2, header dur 30s) are exported at fps=2 (1 s hold)
  instead of 30 s strips — a deliberate deviation for Blender ergonomics.
- Derivatives for physics are taken on the original clip grid and then resampled; upsampling
  first turns linear-interpolation knots into acceleration impulses (20 m/s^2 spikes at idle).
- `_lerp_err` applied to stored palettes measures halving the stored rate again; only
  bake-time numbers are valid (36-51deg on a stored 1x cache is not a failure).

Ruled out:

- hdr[0] (keyRate) is not the duration. A pipeline that read it as the duration and divided
  by 3 was close only for THIRD clips (760 of 1163) and wrong by 1.5× for HALF and 3× for
  FULL clips.
- There are no per-clip speed multipliers (turn_180 / turn_90 / turn_settle / step_forward /
  step_back / run_start / run_stop, walk_cycle 2.3, run_cycle 2.6, dance 9.15 / 9.33): the
  rate formula has no velocity term and the captures match the header rate. With such
  multipliers `RSH_COM_MOV_run_cycle` was written 0.513 s long with 12 m/s of root motion.
- `nanimspeed` and `.sequence`-driven playback do not set the dance rate.

### Track types and constant positions [code]

`anim vtable+0x18` (0x593034) is true only for track types 0 and 2. For types 1 and 3,
FUN_00594cac (0x594d38-0x594d49) adds `pose.local[bone].pos` to the track's constant
position. The pose added there is a pooled rest pose (0x4bef74), reset each evaluation by
0x593685: the skeleton's reference locals (`char+0x36c`) with the position of every
parent-less bone zeroed. It is passed down unchanged and never written (results go to another
object, 0x596636). The reference comes from the model node records with node 0 dropped
(0x545019), so `Bip`, `GamePivot` and `interact` are roots; non-root reference positions are
multiplied by scale entry (parent − 1) of the character list at +0x360, default 1 (0x4c2fcd,
0x4bf188). Hence: root, type 1/3 → the constant; non-root, type 1/3 → constant + rest local
position; bone without a track → rest pose, so an untracked root is at 0 (0x5951c2).

Data: the constant `Bip` y of a prone pose clip equals the first keyed `Bip` y of its
continuation clip to 1 mm on twelve pairs checked (EN2 prone_back_pose -0.843 /
prone_back_start -0.843; RSH prone_back_Pose -0.867 / prone_back -0.866; ...), so a root's
constant is absolute, as the code says (its rest position is zeroed; the bind offset rsh
-0.073, nto +0.060, large +0.094 is not added).

Scope: 577 of 64,567 type-1/3 tracks have a non-zero constant; 435 are GamePivot / interact
(rest local 0, no effect); 23 `Bip`, 2 `Attach RHand`, the rest prop bones.
`EN1_COM_DMG_WPN_1H_disarm_RSH .animation` (file name contains a space) is one of the two
`Attach RHand` tracks (type 3, constant (−0.0744, −0.0625, −0.0032)),
`RSH_COM_WPN_2H_heavy_EN2` the other (type 3, (−0.0723, 0.0057, −0.0244)); by the code the
engine places the bone at rest + constant. In 308 Bordello clips the only zero-constant
type-3 `Bip` tracks are the 24 face clips. No capture covers either case: what the game shows
on these tracks is not established.

Toolkit: `bake_v4.py` follows the engine rule (pose rule 2; `bake_v4.POSE_RULE` is 3, which
adds the twist pass and exact track names): a type-1/3 constant on a non-root bone is added
to the rest local position, and a root with a zero constant or without a track is at 0.
Measured on the six sets of the six-set export (every clip baked on every body bind it is
exported with, 1,773 bakes per Part 2 set and 1,469 per Part 1 set; old rule against new,
largest joint displacement):

| Clip | Binds | What moves | By |
|---|---|---|---|
| `EN1_COM_DMG_WPN_1H_disarm_RSH` | medium, small, large | `Attach RHand` alone | 6.9–11.0 cm (Part 2), 7.7 cm (Part 1) |
| `RSH_COM_WPN_2H_heavy_EN2` | rsh | `Attach RHand` alone | 7.8 cm |
| `EN1_` / `EN2_` / `EN4_` / `RSH_COM_WPN_1H_right_arm_layer`, `RSH_COM_WPN_1H_idle_drop` (no `Bip` track) | large, rsh, bs2, female | the whole body, to `Bip` at 0 | 9.4 / 7.3 / 2.2 cm (the bind's `Bip` offset) |

9 of 1,773 bakes change on PC Part 2, 11 on PS3 and X360 Part 2, 8 of 1,469 on each Part 1
set. The two extra console bakes are `EN4_EXP_MOV_dance_cage_small_C` on `bs2` and `female`
(2.2 cm): a track-name scan that started before the header misread the big-endian copy as one
unknown track (a still pose of 768 frames; PC has 1,763 moving frames), which
`NAME_SCAN_START` = 20 prevents. On `medium`, `small`, `gimp` and `nto` nothing but the two
`Attach RHand` tracks can change (their `Bip` binds at 0, or every clip tracks it). The
arm-layer clips are overlays the game never plays alone. Face clips are baked on a head
model's own node list, whose roots are not the character's (`bake(root_rest="bind")`): 172 /
138 face bakes per set, none changes. The per-bone scale list (+0x360) is not read by the
toolkit; whether a shipped character carries one is not established. Cached bakes carry the
rule number and a cache of another rule is baked again.

### Bone name lookup and track binding [code + measured]

Character bone lookup chain: GetBoneIndex MSG handler 0x4bca76 -> FUN_004ba320 (char+0x190
skeleton container) -> FUN_004b6eb7 -> hash table at container+0xc0 (hash FUN_0042c126 =
h*2+c over bytes, compare FUN_00443545 = exact strcmp, case-sensitive, no prefix stripping).
The engine cannot match 'Bip01'->'Bip' or 'Interact'->'interact'. Clip tracks bind by name
through a global channel table (0xe157e0; search 0x53c0dc, exact compare 0x539eaf,
find-or-add 0x5429e4; skeleton map 0x53e3df; source map 0x594dde; an unmatched track is
skipped, 0x594cac). FUN_005936e2's short table at [*obj]+0x10 = 16-bit parent indices
(rest-world composer), not a name remap.

Consequences: Part 2 medium's `Bip02 *UpArmTwist` bones get no track (measured on 2,714
matched capture frames: rest local plus twist pass, median 0.16° / 0.03°, max 0.87°), and the
gimp's `Attach RHand` stays at rest in `EN2_COM_MOV_run_start_right_foot`, whose track is
`Bip01 Attach RHand` (2 matched frames: 0.26° against 91.28°). Part 1 binds the same way
(read from code, PC Part 1: GetBoneIndex 0x4b9754 → hash 0x42783a, exact compare 0x427a18;
channel table search 0x5339d3, compare 0x531a35, find-or-add 0x539506, skeleton map 0x5356dc
equal to Part 2; source map 0x58abd0 equal but for field offsets; the Animation reader 0x539fd1
renames no track), so in its 983 clips that name the track `Bip01 Attach RHand` an
`Attach RHand` bone gets no track there either (inferred from the code; no Part 1 capture). Medium models name palettes 'RUpArmTwist...'
against the bind's 'Bip02 RUpArmTwist...'; large models 'Bip01 Attach RHand' against 'Attach
RHand'.

Toolkit: `bake` matches track names exactly and places the twist bones with the twist pass;
the character export and `watchmen bake` use exact matching in both parts. The
prefix-insensitive lookup (`'BipNN '`-prefix-insensitive, exact match wins) is kept as
`track_names="prefix"` for the head-model bakes, whose bind is the head model's own. Mesh palette matching (`char_lib.load_parts`) is
prefix-insensitive with exact match winning; a dropped mid-list palette name shifts every
later skin index and is a red flag — only leading mesh-object names (before 'Bip') and a
trailing 'Interact' may drop. On medium with prefix matching the twist locals span 71.45deg /
16.06deg, equal to large / small (71deg range; 0.03deg when the tracks do not bind).

### Twist bones: per-frame alignment (0x5958f5, pairs 0x545019) [code + measured]

Measured on captured palettes (five skeletons; Bordello and NightClub traces): the X axes of
the four pairs agree within 1.1° in every captured palette (p99 at most 0.30°). The baker
with the pass is closer on 729 of 729 matched samples that the pass moves by more than 0.5°
(female 321, gimp 14, rsh 300, nto 94), and on 5,436 of 5,436 on medium with exact track
names; largest worsening 0.20°. `bake_v4.bake` applies it by default.

- **Call site.** The model pose update 0x4beeef calls the pass unconditionally at 0x4bf138,
  after the layer mix and 0x4b9c83 and before the vfunc at +0xb4.
- **Pairs** (0x545019, 0x545140–0x5451fd): T is a bone whose name contains "Twist" (string
  0xa3689c) and whose parent's name does not; S is the first k from 0 with `parent[k] == parent[T]`
  and k ≠ T. The parent table is filled in the same loop, so only entries k < T are defined: the
  partner is a lower-index sibling (measured: true in all 24 exported skeleton files of the six
  sets). Pairs: `ForeTwist` → `Forearm` and `UpArmTwist` → `UpperArm`, four per skeleton; each T has
  one child (`…Twist1`), which follows it.
- **Operands.** 0x594392 returns the model-space transform (quaternion at +0x10). a = row 0
  of R(q_T), b = row 0 of R(q_S): the two X axes.
- **Arc** (0x41f896): axis a×b normalised; θ = asin(|a×b| / (|a||b|)), replaced by π − θ
  when a·b < 0 (π at 0x9e5dd0); quaternion (n·sin(−θ/2), cos(−θ/2)) with 0.5 at 0x9e5dc8;
  the identity when |a×b| ≤ 1e-5 (0x9e802c).
- **Composition.** new = q_T ⊗ arc as a Hamilton product (0x595a85 onward): in the engine's
  convention T first, then the arc in model space, so T's X axis lands on S's X axis. The
  position is kept (0x595891 stores the result) and 0x595704 marks T's descendants for
  recomputation from their locals.
- **Gate.** 0x41fb55 converts each quaternion to Euler angles; the pass is skipped only when
  the two first components are exactly equal as floats. `apply_twist_align` does not model
  this gate (it skips on |a×b| ≤ 1e-5 only).

### Layers and the layer mix [code]

- `SetupNewPage` 0x5b7788 creates one `AnimLayer` per page (kernel/animation/animlayer.cpp:
  additive flag, ease in/out, weight, ANIMATION_LAYER enum). For each inner list of the
  state's layer list (the list index is blend +4, `m_ilayerindex`) it picks one blend node at
  random and makes a child `AnimLayer` with one `AnimBlendSource` per slot.
- A blend whose +0x20 is set gets `AnimLayer::SetIsAdditive(1)` (0x4e3663); blend +0x20 =
  `m_tlayeradditive` (9th registered property, 0x5a6f87; inferred from the registration
  order). When no blend of the page had it clear, the page layer is marked additive and the
  children are unmarked.
- The model pose update 0x4beeef starts from the rest pose (0x593685) and walks the layers
  (0x59668e, recursive; `+0x7c || +0x7d` is passed down to the child's +0x7d).
- A source under an additive layer subtracts the clip's first key: each track pose is
  composed with the inverse of the pose sampled at time 0 (0x594cac, inverse 0x591b74,
  compose 0x591e91).
- Mix 0x596636: a layer with +0x7c set and +0x7d clear adds a weighted delta. The delta
  rotation goes to axis-angle, an angle above π is reduced by the value at 0xc8e03c, the
  angle and the delta position are multiplied by the bone weight, then composed onto the
  pose (0x592a2f; π at 0x9e5dd0, 0.5 at 0x9e5dc8). The value at 0xc8e03c is 2π (bytes
  `db 0f c9 40`).
- Otherwise the layer blends per bone by weight (0x592c8d, a per-bone call of 0x4b26ef). The
  bone weight is the sum of the weights of the sources that have a track for that bone
  (0x594cac), so a partial-body clip leaves untracked bones to the layers below.
- An additive blend with "Force Playpos=1.0" always samples the last key (`UpdatePagePlayPos`
  0x5b61b9).
- The twist pass runs after all layers (0x4bf138).
- Measured (PC, raw class nodes): 256 Part 2 and 250 Part 1 states have two or more layer
  indices; 9 clips per part are never in a base layer. The table is in ANIMATION_META.md,
  "Layers". The baker bakes single clips; layer and additive mixing is not baked.
- Toolkit `GRIP 1H` / `GRIP 2H`: 2-frame partial animations per character GLB (channels only
  on the R-Hand subtree, +L for 2H; source = frame 0 of the family's WPN_xH_idle_stand,
  fallback idle_fidget / any WPN clip), NLA-layered over a body clip like FACE poses;
  `variant_glb.write_glb` accepts 4-tuple manifest entries (name, pal, fps, bone_indices)
  for partial animations.

## 5. Animation state machine (AnimationCtrlWM / AnimationStateGroupWM)

The graph is data in `AnimationClass*.fragment` (AnimationStateGroupWM nodes with
m_ianimationcriteria / value / action, m_neaseinduration, m_nweight, m_etostate ...); the
executable interprets it. Fragment JSON `nodes_full` props carry the m_* names and values
(`kapow_fragment` resolves them); schemas, defaults and UI captions of
AnimationState / StateGroup / Slot / Transition are in `reg_dump.json`. The interpreter needs
no exe access.

### Classes, method table and handlers [code]

Animation-system script class id 0x15; method table registered @0x5e58a2+:

    AnimationCriteriaMet=0x5c5781  TransitionMet=0x5c5ea4  StateGroupCriteriaMet=0x5c6002
    GetValidStateGroupTransition=0x5c6140  StateCriteriaMet=0x5c647c
    GetAnimationValue=0x5ae18f  GetHeldAnimationValue=0x5ae1c5  SetAnimationValue=0x5aa701
    FireAnimationAction=0x5aa83f  UnfireAnimationAction=0x5aa86b  IsAnimationActionPending=0x5aa7f7
    GetAnimationPlayPos=0x5ae294  SetAnimationPlayPos=0x5ae2e1

Class registrations: AnimationStateGroupWM ctor 0x605148 (handlers: command_get_valid_state
0x5f076f = group cmd #6, hash 0x499d201a; command_add_criteria 0x5f9c49;
command_add_transition 0x5f0741), AnimationCriteria(WM) ctor 0x5d2b00s, AnimationTransitionWM
ctor 0x60d4a0s, AnimationStateWM registered at 0x605ce3 and ~0x60b1xx, blend-node classes
0x5a6f00s / 0x5a7900s. Transition property registrations: m_neaseinduration at 0x60b325 /
0x60d5b6 / 0x60dd42, m_etostate at 0x60d56e / 0x60dcfa; the five hidden transition props
(0x381c10c0, 0x1d3171a6, 0x52340773, 0x5234171b, 0xdfc5d866) register at 0x60d759-0x60d7bd
with empty default, null caption, type 3.

AnimationCtrlWM script methods (all in `reg_dump.json`): StateMain 0x5b417b, Update 0x5b4613,
EvaluateTransitions 0x5cbbc2 (2577-byte body, `part_0021.c`:19256/19263), TransitToState
0x5b4a31 (`part_0021.c`:11791), SetupNewPage 0x5b7788, UpdatePageBlendsFaster 0x5b4bd6,
SetAllSlotBlends 0x5b4ef7, UpdatePagePlayPos 0x5b56a9, TransitionPlayPos 0x5ac1aa,
SynchronizePages 0x5ac387, CheckPlayPosEvents 0x5b51f3, DeleteOldPages 0x5b9e4c,
DeleteOneOldPage 0x5ac8a6, ClearAnimationPosEvents, CalculateVelocity, AllowOverlayTransitions
0x5aa33d. Command hashes: cmd6 0x499d201a = command_get_valid_state, cmd9 0x7c02ebf4 =
command_get_valid_transition, cmd8 0x4fdde9d3 = command_Group_criteria_met (0x5f781a), cmd11
0x3c01572e = command_get_fallback_state. Related: command_add_state 0x5a03a8 (class),
command_add_layer 0x5f773f, AnimationTransition.initialize_external 0x5f9b13, UpdateSuperSync
0x5fa582 (from Init 0x5fa96c), command_evaluate_blends 0x59e905, blend Init 0x59f8b0, mixer
0x596532, ForceToState 0x5b4933, goto_slave_mode 0x5b32a2, command_get_list_of_top_level_anims
0x5b112c.

### Record offsets (`re/pages.md`, `re/sync.md`) [code]

Record offsets are 4 x registration index.

    AnimationState   +0x04 m_ecriterialist      +0x08 m_eanimstategroup (owner)
                     +0x14 m_toverridestate (overlay stack)
                     +0x18 m_tiswalkcycle ("Sync Playpos")   +0x1c absolute
                     +0x20 / +0x24 defines movement / rotation
                     +0x28 m_tdisallowoverridelayers  +0x2c m_tallowmultipleinstances
                     +0x30 m_imasterof          +0x34 m_tislooping
                     +0x38 m_nstartplaypos      +0x3c m_neaseinduration
                     +0x40 m_tusesoftblend      +0x44 / +0x48 curve hardness / offset
                     +0x4c m_efallbackstate     +0x50 m_nforcestaytime
                     +0x54 m_tholdblendvalues   +0x58 m_tnotransitiontests
                     +0x5c m_tforcemovementcalc +0x6c m_etransitionlist
                     +0x70 m_elayerlistlist (indexed by layer)  +0x74 m_eeventlist
                     +0x78 m_estoredtransitstate  +0x80 m_eplayposmapper
                     +0x8c _etestedstates       +0x9c m_ispecialhandling   +0x15c animation type
    Transition       +0x04 m_ecriterialist  +0x08 m_etostate  +0x0c m_tfallback
                     +0x10 m_toverrideeasein  +0x14 m_neaseinduration
                     +0x18 m_toverrideplaypos +0x1c m_nplaypos  +0x20 m_tsupersyncpos
                     +0x24.. 8 x (local, remote) markers, default -1.0
                     +0x64 / +0x68 sorted local / remote lists (built at init)
                     +0x6c / +0x70 m_nsupersyncmin / max   +0x74 m_eeventlist
    Event            +0x00 m_ieventtype  +0x04 m_nplaypos  +0x08 m_ianimationevent
                     +0x0c m_tforceupdateblends  +0x24 m_nvalue
    Criterion        +0x08 m_ttestonentryonly  +0x14 m_ianimationvalue
                     +0x28 m_ianimationenum  +0x2c m_ianimationenumvalue
                     [crit+0x10]+0x18 testtype, +0x1c min, +0x20 max (strings in the fragment)
    Page             +0x08 blend (linear)  +0x0c ease  +0x10 playpos
                     +0x14 rate (playpos / s)  +0x18 sync  +0x1c state
                     +0x30 looping  +0x34 time played  +0x38 playpos at last event check
    Page list        +0x14 force-stay timer  +0x18 end-of-animation flag
    Controller       +0x2c m_tforceupdate  +0x60 _eslaveof  +0x74 dt  +0x10c speed slider
                     +0xf8 / +0x158 / +0x15c overlay gate flags

State +0x9c and +0x15c are inferred by counting properties in registration order; the rest are
read against their uses.

**Forcing a state** [code]: `command_force_anim_always(integer, blend, startPlayPos)` (0x1fb9a3bd, 0x5b31ef) looks the id
up with `AnimationClass.command_get_state_entity(integer)` and calls `ForceToState`, so it can only reach the one state
an id resolves to (most shipped states have id 0). `command_force_animstate_always(entity, blend, startPlayPos)`
(0x64c3f1c7, 0x5b3259) calls `ForceToState` with the state entity itself; both need `m_eanimationclass` set. A state
entity is found by name (Entity +0x20) in the controller's animation class tree.

**From the controller to the playing clip's name** [code: `command_get_main_state_main_blendsource` 0x5b0bc8,
`AnimBlendSource::GetAnimSlot` 0x514e59, `AnimSlot::GetTargetAnimName` 0x4b5585]: AnimationCtrlWM members +0x0c bank
list → element 0 → its data +0 = page list → last page (element n−1, n = count / slots of `list(pagestruct)`) → page data
+0 = layer list → element 0 → layer data +4 = blend-source list → element 0 = the main `AnimBlendSource`; +0x68 =
its `AnimSlot`; slot +0x58 = the `Animation` asset; asset +0x40 = the clip name (char*). Each "element" is list
object → +0 storage → +4 data → slot; struct elements are instance pointers whose +4 is the field block.

**The animation type (+0x15c) is recomputed at load** [code + data]: `AnimationStateWM.initialize_external`
0x5f0e63 writes it (with +0x144 / +0x148) from the state's criteria, and every shipped state receives
`initialize_external`: `SceneScope.StateActivate` 0x813bf5 calls `ProjectLib.InitializeHierarchy(self)`, whose
`RecursiveInitializeExternal` 0x7fe85c sends it to the node and every descendant (Node +0x4c / +0x50, no
condition). The enemy classes sit under their level's `SceneScope(LoadBlock)` (9 of 9 level-placed
AnimationClass fragments, measured on the level files); the player classes are in
`GameEssentials/CharacterAnimation.fragment` under `GameEssentials`, the root `SceneScope(FragmentNode)` of
`WatchMenPart2.scene`, which `SceneScope.start` 0x813b0b sends to `StateActivate` (`docs/re/wp5_runtime.md` §5.3).
The stored file values are stale editor output; the toolkit's recomputation is what the game uses. Group record: +0x0c "Choose Random State", +0x14 transitions, +0x18
default state. 0x761caa4e is m_estoredtransitstate (+0x78); "Fallback state" prop 0x377d69a
(UI). The +0x54 / +0x40-bit0 tests in TransitionMet and command_get_valid_state are entity
fields (enabled), not record offsets.

The transition's hidden props 0x381c10c0 / 0x1d3171a6 / 0x52340773 / 0x5234171b are
m_nsupersynclocal / m_nsupersyncremote (the sorted marker lists) and m_nsupersyncmin /
m_nsupersyncmax, rebuilt at init by UpdateSuperSync 0x5fa582 and therefore never stored;
0xdfc5d866 is m_eeventlist. Across all 2459 shipped {trans to *} nodes none of the five is
present (all default).

### Owners and criteria [impl]

Owner searches walk up the logical parents and look only at nodes that have
m_iAnimationSystemType; folders and plain nodes have none.

    state      -> first STATE_GROUP (m_eanimstategroup) and the CLASS   AddToClass 0x5ed37a
    group      -> first typed ancestor if it is a group                 AddToParentGroup
    transition -> first typed ancestor if it is a state or group        AddToClosestState
    criterion  -> the first typed ancestor; an owner transition (+0x34) or state
                  (+0x38) ends the walk, state groups are collected in +0x3c
                                                    FindClosestRelevantParent 0x5aaf49

Class command_add_state 0x5a03a8: override states (or their outermost group) form the overlay
candidate list; states with m_istateid form the slave-state table. The class root owns no
transitions.

StateGroupCriteriaMet 0x5c6002 = owner chain AND own list; StateCriteriaMet 0x5c647c = own
list only; command_Group_criteria_met 0x5f781a = owner chain. Each criterion is evaluated by
its class method [criteria class rec + 0xc]+0x24 through the thunk 0x479874.

### AnimationCriteriaMet (0x5c5781) [code]

- Numeric compare via MathLib.InsideInterval 0x77aa25 (x, min, max, type): 0 = min <= x <
  max (INTERVAL), 1 = x < max (LESS_THAN; min is not read), 2 = x >= min
  (GREATER_THAN_OR_EQUAL). min / max are strings in the fragment (they may be ANIMATION_VALUE
  refs, not just literals).
- Entry-only (criterion +0x08, m_ttestonentryonly): met without testing (the early-return
  path @0x5c58a3) when the top page's state is the owner state or inside the owner group,
  unless the state's +0x68 is set (set only around the normal-pass get_valid_transition in
  EvaluateTransitions).
- PLAY_TIME (4): value = current slot record +0x34 (seconds played).
- PLAY_POS (5) / OVERLAY_PLAY_POS (7): value = slot record +0x10 (normalized 0..1);
  REVERSE_* (6/8): 1.0 − playpos. Overlay variants read the overlay slot (record picked via
  [state+0x10]+0xc chain with slot index from the 0xe16fd8 global). Criteria 7 / 8 occur
  nowhere in the shipped fragments (all-data scan).
- EVENT (3): resolves the event id, checks the fired-event list (>= 0 index -> met).
- ENUM (2): reads only m_ianimationenum (rec+0x28) and m_ianimationenumvalue (rec+0x2c);
  m_ianimationvalue (rec+0x14) is read only by a VALUE criterion.
- ANY_OF (11) / ALL_OF (12): recurse over child criteria (OR / AND).
- The NOT property inverts the result.

### State selection and transitions [code]

- **command_get_valid_state 0x5f076f**: a cyclic scan over the group's children that starts
  at index 0 (0x5f0792), or at a uniformly random index (`rand_integer` 0x47b025) when the
  group has "Choose Random State" (group +0x0c; 0x5f07bb-0x5f07d7); nothing is remembered
  between calls. Members already in the tested list of the running transition evaluation
  (`_etestedstates`, state +0x8c) are skipped, and each member examined is appended to it.
  Child count = (hdr & 0xffffff) / stride. Per child: classid via 0x4f99c3(node, 0, &out); 7 =
  state group, else state. A state child must be enabled (entity fields) and pass
  StateGroupCriteriaMet 0x5c6002; a group child passes StateGroupCriteriaMet and then recurses
  through its own command #6. Returns 0 if a full cycle finds nothing. A self-pick is rejected
  in EvaluateTransitions (0x5cbbc2).
- **GetValidStateGroupTransition 0x5c6140** (method-table entry): transitions list: state
  IsKindOf([0xe16844] = AnimationState) -> [rec+0x6c]; group IsKindOf([0xe16f28] =
  AnimationStateGroup) -> [rec+0x14] (typed index checks vtbl+0x60 types 7/9). For each T:
  (1) T rec+0xc (m_tfallback) is compared with the pass flag: the normal pass takes only
  non-fallback transitions, the fallback pass (0x5f7873) only fallback ones; each target is
  tried once per evaluation. (2) TransitionMet (method idx 8 = 0x5c5ea4) with (args+8,
  args+0xc, T). (3) target = [T rec+8]; a group target needs StateGroupCriteriaMet +
  command_get_valid_state on it to yield a state; a state target is gated by the transition's
  criteria, the target state's own criteria (appended to the transition's list by
  AnimationTransition.initialize_external 0x5f9b13) and StateGroupCriteriaMet of its owner
  chain. The winner is stored in m_estoredtransitstate (hash 0x761caa4e, via prop-set
  0x5107b2) and T is returned. The fallback pass runs when the state's or its owners' criteria
  fail; then m_efallbackstate (+0x4c), the class's m_edefaultanimstate, the class's
  m_esafetyfallbackanimstate.
- **TransitionMet FUN_005c5ea4**: gates on the target state being enabled (entity fields),
  then, with "Sync PlayPos?" set, the transition is met only while m_nsupersyncmin <= top
  page playpos <= m_nsupersyncmax ([edi+0x6c] / [edi+0x70] against [state+0x10]), then
  evaluates the criteria list; returns 1 only if all pass.
- **Sync markers** (`re/sync.md`): UpdateSuperSync 0x5fa582: with "Sync PlayPos?" set,
  markers are taken in order until the first local < 0 (remote is not tested), bubble-sorted
  by local (0x5ed5a2); m_nsupersyncmin / max = first / last local. Start position,
  TransitionPlayPos 0x5ac1aa: override -> m_nplaypos; no sync -> -1 (no opinion); else i =
  first index with local >= p: i == 0 -> remote 0; i == n -> remote n-1; else
  MapIntervalToInterval 0x77a579 (p, local i-1, local i, remote i-1, remote i). No implicit
  (0,0) / (1,1). It is a one-shot start position, not a time warp; the curve belongs to the
  target state; a transition can only override the duration. Transition editor props:
  to-state (entityref), fallback, Override Ease In? + Ease In Duration (0..2s, default 0),
  Override Start PlayPos? + Start PlayPos, Sync PlayPos?, 8 marker pairs (default -1).
- **Priority of the start position**: transition override > sync markers > walk-cycle
  carry-over > the state's m_nstartplaypos; then, if the target is already on the stack and
  is a walk cycle, that page's position.
- **TransitToState 0x5b4a31** (FUN_005b4a31) args = {state, ease, playpos}: ease < 0 = the
  state's own m_neaseinduration (+0x3c), playpos < 0 = the state's m_nstartplaypos (+0x38). If the
  outgoing and the target state are both walk cycles and no position was passed, the
  outgoing play position is kept and the page is flagged sync. It passes {state, playpos,
  sync, ease, pagelist} to SetupNewPage (via the class method [class rec+0xfc]+0x24).

### Pages (`re/pages.md`) [code]

SetupNewPage 0x5b7788 args = {state, playpos, sync, ease, pagelist}:

- nothing happens if the top page already plays the state and "Allow more than once" is off
  (0x5b780a);
- an override state goes on the overlay list, and is not created if the body top state
  disallows override layers;
- page list +0x14 = the state's m_nforcestaytime (0x5b7d49);
- re-entry (0x5b7da0-0x5b82dd): a page lower in the stack that plays the same state is
  removed, the pages above are renormalised, the new page starts at the old page's share
  and, for a walk cycle, at its play position;
- ease rule (0x5b83f8-0x5b8593): instant if the state's own ease-in <= 0 (a transition's
  override is then ignored), if it is the first page of the body list, or if the passed ease
  is exactly 0; else the passed value if > 0, else the state's;
- one blend node per inner list of m_elayerlistlist, picked with a Mersenne-Twister rand % n
  (FUN_0047aa2e); command_add_layer 0x5f773f files each blend node under its m_ilayerindex
  (impl);
- allocates and zeroes the page struct (rep stosd), pushes it (0x50030f); ENTER_STATE /
  LEAVE_STATE events are sent here;
- a new state with a non-zero `Master of` and a partner triggers the dual-animation handshake
  (§6);
- no page-count cap (no count test in `DeleteOldPages` 0x5b9e4c or `DeleteOneOldPage`
  0x5ac8a6). `DeleteOldPages` always deletes index 0: once per page below the highest page
  with blend ≥ 1; and a page with blend < 0 at index k removes pages 0..k−1 and then itself.

StateMain 0x5b417b calls Update(0, pagelist[0]) then Update(1, pagelist[ovidx]) — body pass
and overlay pass run the same code. Update 0x5b4613 order, per stack: speed ->
EvaluateTransitions (on the last frame's playpos) -> force-stay timer -> UpdatePageBlendsFaster
per page (FUN_0059397a(slot, w); slots > #9 maskable by the [rec+0x18] bitmask when
[rec+0x14] is set) ->
DeleteOldPages -> SynchronizePages -> ClearAnimationPosEvents -> UpdatePagePlayPos per page ->
CalculateVelocity.

Advance (UpdatePagePlayPos 0x5b56a9): page +0x14 is a rate, rebuilt every frame from the
first layer's slots (§4 "Playback rate"); playpos += min(rate, 6.6) x dt (double at
0xa45e90); when playpos > 1.0 (strict) a non-looping page clamps to 1.0, a looping one
subtracts 1.0 until <= 1.0. blend += dt / ease AFTER the frame's weights were applied, so a
new page has weight b(0) in its first frame. Overlay pages fade out by dt / ease when finished
or disallowed and are removed below 0 (floor -0.01). SynchronizePages 0x5ac387: a run of pages
with the sync flag shares one rate, 1 / sum(w / rate). UpdatePagePlayPos also stores
GamePivot-local velocity and minus the twist rate, and implements the slave lock (§6).

Blend curve (UpdatePageBlendsFaster 0x5b4bd6; `MathLib.PowerSmooth` FUN_0077ab7b + powf
0x423c2b), applied only if the state has m_tusesoftblend and AnimationData "Force Linear
Transitions" is off; otherwise linear:

    t = clamp(t, 0, 1)
    v = powf(t, curve_offset)            # m_ncurveoffset (default 1.0)
    if v <= 0.5:  b = powf(2*v,   hardness) * 0.5
    else:         b = 1 - powf(2 - 2*v, hardness) * 0.5
    # hardness = m_ncurvehardness (default 1.0); defaults => identity (linear)

powf = CRT pow with float32 truncation (fstp dword). Normalized page time via FUN_0077a4d8 =
clamped inverse-lerp (x-a)/(b-a). Checks: identity at defaults; hardness=2, t=.25 -> .125.

"No Transition Tests" (0x5cbbc2): evaluated only when play position >= 1 or
ctrl.m_tforceupdate (+0x2c) is set; the engine sets that flag when a page is added or
blending, and it can be set from outside (impl); `FireAnimationAction` 0x5aa83f sets it, so a
silent face gets it every frame.

Force-stay (0x5cbbc2, Update): a wanted transition is deferred while page list +0x14 > 0; the
timer is loaded by SetupNewPage from the entered state's m_nforcestaytime and counted down
only on ticks where a transition is wanted. m_nforcestaytime is 0.0 in every shipped state,
so the engine never defers.

A class starts in its `m_edefaultanimstate`; when that is a group the controller asks the
group for a valid state (`AnimationCtrlWM` start -> `command_get_valid_state` 0x5f076f, a
random member).

### EvaluateTransitions 0x5cbbc2 and overlay pages [code]

Signature (ctx, args{out, flag, pagelist}); called from Update 0x5b4613 (table offset 0xac).

- pagelist EMPTY + flag=1: overlay entry. Gate AllowOverlayTransitions (0x5aa33d: !ctrl[0xf8]
  && ctrl[0x158] && (ctrl[0x15c] || classrec[0x70])), then scan the class's override list
  (command_add_state 0x5a03a8: each override state, or the outermost state group that owns
  it; the folder name plays no part): classid 7 (group) -> StateGroupCriteriaMet +
  command_get_valid_state -> SetupNewPage (scan continues); state -> StateCriteriaMet
  0x5c647c -> SetupNewPage (scan breaks).
- pagelist non-empty: top-page transition evaluation. Wait-for-anim-end gate ([top rec+0x58]
  && playpos < 1 -> out = 0), get_valid_transition; defer (out = 1) while the force-stay
  timer [listrec+0x14] > 0; execute = TransitionPlayPos [0xa8] + TransitToState [0xb0] +
  per-slot SendAnimationEvent [0xe0]; no-T path: Group_criteria_met / StateCriteriaMet ->
  stay, else retry with arg 1 (the fallback pass), else command_get_fallback_state.

Overlay data: only EN1 / EN4 ship an override state (HeadTurn: additive look-at,
MOTION_LAYER_1 3-slot vertical blend on value 18 over [-0.785, 0.785]; ACTION_LAYER_1/2
left / right on value 17 over 0..±1.575 via m_ilayerweightctrlparam). Ctrl-param 0 = NONE (UI
'blend on NONE'). Override states are additive overlays carried by the AnimLayer machinery.

### Blend nodes [code + data]

Blend-tree props (0x5a6f00s / 0x5a7900s registrations): Force Playpos=1.0, Parent blend pos,
Child value (ANIMATION_VALUE), Polar compensation?, mode MANUAL:0 / VELOCITY:1 / DIRECTION:2,
Blend interval start / end (strings), Weight (m_nweight hash 0xc058b077, default 1.0),
m_npriority (0x0b3a7ea0), m_tlayeradditive.

- Controlled blend: blend-position split (m_iblendctrlparam over the blend interval, slots at
  m_nparentblendposition, linear between neighbours); layer weight drive
  (m_ilayerweightctrlparam -> inv_lerp_clamped 0..intervalend).
- **Uncontrolled blend = first child only.** `command_evaluate_blends` 0x59e905 with
  `m_iblendctrlparam == 0` writes the blend properties on `m_echildlist[0]` only; the list is
  in sibling order (`Init` 0x59f8b0, insert 0x48f556); `SetAllSlotBlends` 0x5b4ef7 sets other
  slots to 0; a new source starts at 0 (0x594b36); the mixer 0x596532 skips a source below
  1e-5 (0xa40400). `m_nweight` (0xc058b077) and `m_npriority` (0x0b3a7ea0) have no reader.
  Data: 1,660 blends and 1,899 slots, every `m_nweight` 1.0. The Attack state of a face
  class plays its first slot alone.

### Events (`re/events.md`) [code]

- Sender CheckPlayPosEvents 0x5b51f3. PLAY_POS: fires once per pass when m_nplaypos <= play
  position and not yet fired (0x5b55c4, `test ah,0x41 / jp`) — a latch; an event skipped by
  a wrap is marked pending and fires on the next check. The (previous, current] window is
  used only under the AnimationData debug play-position override (0x5b5399).
  TOTAL_PLAY_TIME: m_nplaypos is SECONDS, fires once when <= time played on the page
  (0x5b52c1). ENTER_STATE is sent by SetupNewPage, LEAVE_STATE by SetupNewPage /
  UpdatePagePlayPos.
- A PLAY_POS event with m_nplaypos <= the page's start position is created already fired
  (0x5b8f16).
- Delivery SendAnimationEvent 0x5ac4ef -> hash 0xf7c3b75f command_animation_event_received.
  Receivers: CharacterRootLogic 0x6a525e (37,665 bytes, four compare chains),
  CharacterCameraStateManager 0x64b304 (id 18 only), TriggerCharacter 0x87d421 / 0x87e574
  (ids 78, 79, 8).
- Ids with no receiver in the exe: 0, 1, 2, 3, 14, 43, 44, 50, 51, 90. Case map for every
  id: `re/events.md`, `re/events_table.json`, `wlib/engine_enums.json` (event_semantics).
  The character-side cases (19, 20, 23, 28, 38, 45, 70, footsteps, IMPACT, DIE, CHARGE ...)
  are listed with their topics in §6, §7 and §11.

### Toolkit: `wlib/anim_state_machine.py`

Engine-faithful interpreter over extractor fragment JSONs. `load_tree()` rebuilds the node
tree from `nodes_full` (logicalParent / siblingOrder; class from the preamble instance
strings — `j['nodes']` type list is misaligned, use `instances[0] str_<id>`), splices nested
StateGroup fragments via assetName. `get_valid_state` (0x5f076f: from index 0, or a random
index), `get_valid_transition` (0x5c6140 order incl. group-target recursion + fallback),
`transit` (0x5b4a31 ease-in / playpos overrides + supersync marker remap), `tick` (two stacks
`pages` / `opages`, body pass then overlay pass, evaluate before playpos advance,
advance / loop, ancestor-chain transition tests, one-frame event clear, overlay entry per
0x5cbbc2, DeleteOldPages occlusion), `slot_weights` (page cross-fade stack, engine-exact
blend curve, blend-position split and layer-weight drive), `overlay_weights()`. CLI: `--list`,
simulation trace, `--value idx=float`. Validated on Enemy01 + Rorschach classes end to end;
HeadTurn deadzone gating, look up / down interpolation and left / right additive weights
(|v| / 1.575) verified. Transitions belong to their owning state (that is the "from"). No
page cap, no from-filter, sync-marker gate implemented.

Caveats: `anim_meta._main_clip` names the LAST non-arm-layer slot of a multi-slot blend as a
state's main clip, while the engine plays the first child of an uncontrolled blend (EnemyBig
`HeavyMiddleBack`, the two `AnimsToAdd` states); a state's `clips[].weight` is the stored
`m_nweight`. `clips[].loop` is set by any looping state that plays the clip on a non-arm
layer (`EN4_COM_MOV_run_cycle` and `EN2_COM_MOV_strafe_left` are blend members of looping
states: Enemy04 `Run`; EnemyBig `StrafeLeft` / `StrafeRight`).

Capture validation (bounded): nightclub dancers are CharacterSimple entities with raw
AnimSlots — they do not run the state machine; the player (rsh) capture is the vehicle. rsh
clip identification (parent-relative rotation NN against all 293 baked clips, bind-bone order
offset 0): blended frames dominate (median d~2: multi-page + layers without the input
stream); clean single-clip windows lock in tight (special_stomp d=0.05, kick 0.16, walk 0.26).
A full environment-driven replay needs the input stream, which is not derivable from a
capture; graph consistency of observed clip sequences is the remaining cheap check.

### Ruled out

- There is no transition from-filter: transition record +0x0c is m_tfallback, and the five
  hidden props are the run-time marker cache / event list.
- command_get_valid_state is not a round robin that remembers an index between calls.
- State record +0x38 is m_nstartplaypos, not the ease-in; the ease-in is +0x3c; +0x4c is the
  fallback state, +0x78 the stored transit state.
- Slot weight is not m_nweight × page blend: m_nweight has no reader.
- The page-list timer +0x14 is a force-stay timer, not a top-page ease window; the engine
  never defers a transition in shipped data.
- Not every state entry pushes a page (same-state and re-entry rules above); the page stack
  has no cap of 8.
- "member2" of a state group record (+0x08) is the owning group, not a single criterion.
- Playpos advance is not `m_nspeed × dt + offset` per slot; the page rate is rebuilt every
  frame from the first layer.

## 6. Paired animations: master and slave (`re/placement.md`, `re/events.md`)

Consumer-facing rule: `docs/ANIMATION_META.md`. Engine quaternion convention in this code:
products are "child * parent" (Hamilton), vector rotation is conj(q)·v·q.

### Handshake [code]

- Trigger: `AnimationCtrlWM.SetupNewPage` 0x5b9afb–0x5b9b54. A new state with a non-zero
  `Master of` (+0x30) and a partner sends `request_me_as_dual_animation_partner` (0xb47fc836)
  and `goto_slave_mode` (0xa3a6f711, args MasterOf id) to the partner's CharacterRoot.
  `CharacterRoot.command_goto_slave_mode` 0x693b2e picks the slave state with
  `AnimationStateGroupWM.command_get_valid_state` (0x499d201a) and sends
  `command_goto_slave_mode_state` (0x4b150a3d).
- Slave lock (impl): goto_slave_mode 0x5b32a2 -> ForceToState 0x5b4933 with ease -1 ->
  SetupNewPage, whose tail passes page +0x0c to the absolute-mode message. goto_slave_mode
  stores the master's first animation source in the partner controller's _eslaveof (+0x60).
  UpdatePagePlayPos 0x5b5756-0x5b57d0: body stack, top page, _eslaveof set -> page.playpos =
  the source's position (time / duration, 0x591920); cleared when that is >= 1. The pair is
  locked in play position and runs at the master's rate. On 145 of 240 primary pairs the two
  states have different slot speeds (master 1.1, partner 1.0).

### Placement [code]

- The placement block (`CharacterRoot.StateActive` 0x6b367a, block 0x6b9035–0x6b94e9) runs
  EVERY tick, behind three tests: own capsule is_absolute_mode, own controller
  is_in_slave_mode (controller +0x60 != 0), partner (controller +4) != 0.
- `start_pos = M · (I0 − Δ)`, `start_orient = r * Q_M`: M / Q_M are the world transform of
  the master's CharacterVisual node (CharacterRoot data +0x24; +0x28 is the capsule); I0 =
  `get_interact_initial_pos` (0xa591eb43), Δ = `get_slave_pos_offset` (0x90349206, 0x5af879,
  uses track index 0 literally at 0x5af938) = track0(t) − track0(0); r = (0, sin c, 0, cos c),
  c = −π/2 from the float at 0x9e8440; the product is r (x) Q_M in Hamilton terms. I0 == 0 →
  (0.11, 0.04, 1.12) from 0xa5f02c / 0x9e616c / 0xa5f028. Written to capsule +0x10
  `m_vWorldStartPos` and +0x28 `m_qWorldStartOrient`.
- anchor_pos(t) = M(t) · (I0 − (GP_m(t) − GP_m(0))): the subtraction cancels the master's own
  translation, not a turn of its node.
- Capsule property offsets (hash-matched): +0x10 m_vWorldStartPos, +0x1c m_vWorldEndPos,
  +0x28 m_qWorldStartOrient, +0x38 m_qWorldEndOrient, +0x4c m_vAbsInteractPos, +0x58
  m_qAbsInteractOrient. Clip data: +0x48 = GamePivot track index, +0x4c = interact track
  index. Capsule +0x7c..+0x84 = the partner's target; +0xb8 = the mode flag.
- The start frame the capsule uses is a PivotNode "worldstartnode" created at state init
  (`StateAbsoluteAnimation` 0x6a1e1d, which also stores −GP(0)). It is refreshed from the
  properties +0x10 / +0x28 only by command_update_world_data 0x6b201d, which runs only while
  capsule +0xb8 != 0.
- Writers of capsule +0xb8: `command_goto_animation_mode` 0x67bd36 (= args 4, which
  command_goto_phys_absolute_mode 0x68a79f sets to 1 iff the state's special handling is 0;
  in the flag-1 branch with capsule +0x48 == 0 the stored start is kept);
  StateAbsoluteAnimation one tick after init (= 0 if the state has Master of); the
  ABSOLUTE_GOTO_TARGET_POS event (28, 0x6a9dca: capsule data +0xb8 = 1, nothing else).
- The master: no shipped master state is an absolute animation (data), so SetupNewPage sends
  it to normal physics mode. It gets no start frame and is never snapped.
- The partner: enters absolute mode at its own current pose (flag 0); the block's output is
  ignored until the event sets the flag; then `CollisionCapsuleNode.command_absolute_update`
  0x67f7b0 blends from the ENTRY pose (captured at state init) to the anchored track: pos =
  start + R(start_orient)·(GP(t) + loopOffset − GP(0)); orient = q_GP(t) * start_orient;
  timer -= clamp(dt, 0, 0.1); w = timer / blend. The blend time is the partner state's own
  ease-in. A slave's visible node holds its entry pose until +0xb8 is set (0x67f727, `DccUpdate`
  0x680654).
- Once the flag is set the master's capsule drives the partner: DccUpdate 0x680654 ->
  DccJoint 0x6a3d71 sends absolute_update(apply = 0) to the partner's capsule, sweeps to its
  predicted position, and drives an EmbeddedJointNode ("DualAnimationJoint") there; level
  geometry moves both.
- m_vAbsInteractPos / Orient are written by scripted interactions (command_play_specific_anim
  0x6af969, TriggerCharacter.StatePullSwitch 0x896bb0), not by combat.
- `command_get_slave_alignment` 0x5b0ddf is a stub (identity quaternion);
  `get_slave_pos_at_time` 0x5b0698 is called by hash 0xe873fd55 from the auto-align step of
  StateActive.
- The pair ends by the partner's LEAVE_ABSOLUTE_MODE event (19, 0x6ac8de: goto_phys_normal_mode
  (capsule -> StateOnGround, position kept), leave_slave_mode on both sides, break_joint), by
  the partner's watchdog in StateActive (partner null or dead, or the master has left the
  paired state), or by the master changing state (SetupNewPage, DualAnimBroken 0x675f4f).
  Position is kept; there is no snap. KILL_ANIMATION_PARTNER (20, 0x6ac5f6): give_damage of
  100000 to the victim and the partner link cleared; no transform is written. No event case
  writes a partner's position or orientation. LOOK_AT_TARGET (45, 0x6a86ae) is a camera event
  (command_lookat_target_timed); no character field is written.
- No mirroring and no per-character scale anywhere in these functions. Pairs do not loop
  (data).
- **Master node = GamePivot frame.** `UpdateAnimPoseAndCloth` 0x6b015d sets the node
  orientation to (0, sin(−h/2), 0, cos(−h/2)), h = `m_nfaceheading` (0.5 at 0x9e5dc8);
  `UpdatePagePlayPos` 0x5b56a9 stores GamePivot-local velocity and minus the twist rate. The
  anchored partner is rigid in that frame and swings with a turning master: the anchor swings
  on 39 of 240 primary pairs (14 master clips; over all 413 candidates 60 pairs and 22 master
  clips). Not established: whether the visual node and the capsule share an origin.
- **Body = GamePivot(t) + R(q_GamePivot(t)) · joint.** Data: `interact` is world-fixed to 1
  cm on 67 of 72 turning clips with conj(q)·v·q, on 0 without.
- The quaternion tolerance at 0xd91bf8 = 0.0 (inferred: byte scan: 11 references, all `fld`
  (`d9 05`); the four neighbouring globals are addressed absolute-only; the image has no
  relocation directory; the address lies in the zero-filled tail of `.data` (the file-backed
  part ends at 0xd90000), and no instruction stores to it directly; no instruction hands out an
  address within 0x10 below it either (immediate scan of 0xd91a00–0xd91e00: the nearest is 0xd91be8,
  the 8-byte QueryPerformanceFrequency result of 0x425885, then 0xd91c1c); not read in a debugger).

### DCC joint [code; constants from exe bytes]

`DccJoint` 0x6a3d71 rewrites the partner's target (capsule +0x7c..+0x84) while the partner's
capsule is in absolute mode: it sends `absolute_update(dt, apply = 0)` and reads the predicted
position; a closest-hit capsule sweep (partner's `width`, mask 0x20) from the master to that
target gives `target = master + (target − master) × fraction`; with no sweep hit a sorted ray
(mask 0x20) over `distance + width × 0.5` gives `target = master + dir × (|hit − master| −
width × 0.5)`; `delta = new − old`, its component into the hit normal removed when
`delta · n < 0`, and `(delta.x, 0, delta.z)` is added to the master's `_vdccmove`.

| Object | Settings |
|---|---|
| "DCC joint" (`EmbeddedJointNode`, D6), created once | collision off, not breakable, motors off, projection off; swing1, X, Y, Z = 0; swing2, twist = 2 (0 locked / 1 limited / 2 free, `re/physx_d6.md`) |
| "DCC joint slope" | breakable, max force 15.0 (0x9f8090); X, Z = 0; Y, swing1, swing2, twist = 2 |
| On binding a partner | partner capsule body mass 5.0 (0x9e97fc), own 50.0 (0x9e602c); child = own capsule, parent = partner capsule (child / parent assignment inferred from lifter names) |
| Partner absolute, each tick | joint disabled; child-space position = partner target in the master's frame; orientations set; swing1/X/Y/Z = 0; enabled |
| Partner not absolute | swing1/X/Y/Z = 2 |

**When the joint binds and what releases it** (read from code unless tagged).

- Every capsule state (`StateOnGround` 31, `StateCharge` 40, `StateGrapplingHook` 44,
  `StateAbsoluteAnimation` 48, `StateRagdoll` 63, `StateInitFreeFall` 69; the class has no
  others) calls `DccUpdate` 0x680654 each frame. It returns early when `DccTest` 0x676da0 fails
  (capsule `physicsType` +0x14c == 4, CHARACTER_CONTROLLER; enum string 0xa29f14).
- `DccUpdate` calls `DccJoint(partner capsule)` when all hold: the character's current
  animation state has `m_imasterof` != 0; its `m_eanimationpartner` is set, is not a
  placeholder (`m_tisplaceholder` +0x198) and is not itself; the partner capsule's
  `m_icharacterphysicstate` (+0x04) == 3 (written only by `StateAbsoluteAnimation`); the
  partner's `CharacterVisual.m_tisragdollinworld` (+0x14) == 0; the partner capsule's
  `m_tallowchangeworldpos` (+0xb8) != 0. Otherwise it calls `DccJoint(null)`, which runs
  `CleanUp_eDccJoint` 0x676db9 when a partner is bound. The joint lives on the master's capsule.
- Release paths: (1) the master's own `DccUpdate` once the condition fails; (2) the partner's
  LEAVE_ABSOLUTE_MODE event (19; the case at 0x6ac8de in
  `CharacterRootLogic.command_animation_event_received` 0x6a525e) sends `break_joint`
  (CharacterPhysics command #9, hash 0xc40d9345) to the master's capsule, but only while the
  partner's `m_eanimationpartner` is set; (3) `CharacterRoot.command_ragdoll_driven` 0x6937d1
  sends `break_joint` to its own partner's capsule, so it reaches the joint only when the
  character that ragdolls is the slave; (4) `CharacterPhysics.command_character_placeholding_out`
  0x67cbce compares `_edccother` (a capsule) with the root that sent game event 0xcf, so it
  never matches (inferred: `_edccother` is only ever assigned a partner's
  `m_echaracterphysics`). `DualAnimBroken` 0x675f4f sends only `leave_slave_mode`, which
  clears the partner's `_eslaveof` (0x5b3310).
- `CleanUp_eDccJoint` 0x676db9: if the joined capsule is still absolute (state 3) it gets
  `goto_phys_normal_mode`; child and parent are cleared, the joint disabled, both capsule masses reset to 50.0
  (0x9e602c); if the master's own body is a ragdoll in the world (`m_tisragdollinworld`), its ragdoll mean velocity
  is set to the partner's animation velocity in world space. So while a joint is not released the partner capsule
  keeps mass 5.0 against the master's 50.0.
- Offsets for a live check (member block = entity +0x10): `CharacterPhysics` `m_icharacterphysicstate` +0x04,
  `_edccjoint` +0x190, `_edccother` +0x198 (a capsule entity); joint and capsule enabled = Node +0x54;
  `CharacterRoot` `m_nhealth` +0x64, `m_echaracterphysics` +0x28. A master that died bound shows as a capsule
  with `_edccother` set, its own Node +0x54 at 0 and its root's health ≤ 0; the joint node keeps its own
  +0x54 at 1 but has no PhysX joint (next bullet).
- `StateRagdoll` 0x68012e disables its own capsule (`Node.enabled` = 0, `Node__SetEnabledScript`
  0x48f65c) when the root's `m_nhealth` (+0x64) <= 0, before its first `DccUpdate`. What that does
  in PhysX (read from code):
  - The capsule (`CollisionNode` slot 26 0x49cb58 → 0x519f9b) disables every body of its physics
    object (`node+0x154`, list +0x3c, the list `DccJoint` sets the mass on). For the
    `Physics::CharacterController` that is slot 26 0x4f3b08: the controller manager's virtual +0xc
    (`releaseController`, by header order; +0x8 is the `createController` call of 0x4fdfb3) frees the
    `NxController` and its actor, and +0x9c is cleared. A disabled capsule has no PhysX actor.
    Re-enabling (slot 25 0x4f3af9) creates a new controller at the node's position through slot 18
    0x4fdfb3; `DccTeleportMode` uses this disable/enable pair to drop the speed (`tKillSpeed`).
  - The "DCC joint" `EmbeddedJointNode` is created with `CreateNode(type, capsule)` (0x47bc97 → Node
    slot 14 0x4945fd sets the logical parent), so the enable push-down 0x48f613 → 0x48e51d reaches
    it. Its slot 26 0x4aab56 (while the physics system runs) → 0x4a8dd5 sets the D6Joint's +0x55 to 0
    and rebuilds it (0x5146ec → 0x5141ee), which releases the `NxJoint` (scene virtual +0x28) and
    creates none while +0x55 is 0. The joint therefore does not hold the slave in PhysX.
  - What stays stuck is script state: `CleanUp_eDccJoint` never runs for the dead master (path 1 is
    lost; inferred: a disabled node's state task does not run, as with the AI pause), so the slave
    capsule keeps mass 5.0, `_edccother` stays set, and the slave stays in `StateAbsoluteAnimation`
    (state 3) until its own event 19. Not established: whether that is the void launch (mod TODO 4).
- Data (measured, pc_p2 `anim_meta.json`, 240 primary pairs): 158 hero → NPC, 64 hero → hero,
  18 NPC → hero. All 18 NPC masters are COUNTERATTACK states (Enemy01 4, Enemy04 10,
  EnemyBig 4); each hero victim state has a LEAVE_ABSOLUTE_MODE release at play position
  0.45–0.79 (1.6–6.7 s). The risky case is an enemy that counters a hero and is killed during
  the counter.

### Heading constants of `StateActive` [code; constants from exe bytes]

Speed cap 13.0 (0xa5f048) for 0.2 s after `_nfastrotatetime`; 20.0 (0x9e66ac) on reverse
direction or STEP_AROUND; factor by state type — DODGE: NPC with lock 2.0 until play position
0.7, player 0 then 0.4 after 0.4; BULL_MOVE player 1.5 then 0 after 0.25 s; BLOCK NPC 1.0;
NPC ramp rate 5.0, floor 0.2, threshold 0.5 rad. The ignore flag is set when the state's
`m_tignorefaceheading` is set and |move heading − saved face heading| is at or above state
+0xa8, or by `m_tforceignorefaceheading`. `LinearDampSignedAngle` (0x791500): d = pref − cur
wrapped to ±π (0x77a414); `cur` when pref equals cur, `pref` when |d| < step, else cur ± step
by the sign of d. NPC (`m_eplayerctrl` null): the preferred heading is smoothed as
heading(lerp(dir(last), dir(pref), min(1, 10·dt))), 20·dt while attacking (0x9e5c60,
0x9e5c68). If |pref − face| > 0.5 the ramp rises by 5·dt to 1 and the face heading takes the
linear damp with step max speed × dt × factor × ramp; otherwise the ramp falls by 5·dt to 0.2
and face = heading(lerp(dir(face), dir(pref), min(1, 5·dt))), 15·dt while attacking (0x9e70a0,
0x9e5bb0). The ramp rate is state +0x54, loaded with 5.0 (0x9e97fc). A player has ramp 1 and
always takes the linear damp. Not read: the rotation-window block.

### Event cases 23, 38, 70 and the footstep block [code; constants from exe bytes]

- 23 CLEAR_DEADZONE (0x6ae002): in an attack state with an effect attacher and a valid
  `m_iboneid`, the attacher is moved to that bone, enabled, and its child emitter started.
  `_nissuedattackdeadzonetime` = game time − 0.8 (0x9ea130) when the state is an attack state
  and the root has no attack target, otherwise −2.0 (0x9e60cc). The combo list is trimmed
  (`command_trim_combo_list(list, player control == null)`), the AI combo manager is told,
  `_thascleanedcombolist` = 1, `_ecurrentcombostring` =
  `command_get_longest_valid_combo(...)`, and `SessionLogCtrl.command_log_combo_updated` is
  sent.
- 38 THROW_BRANCH_POINT (0x6a91c0): returns if `m_neletrifiedchargespower` ≠ 0. With an
  animation partner whose state has special handling BLOCK (8):
  `FireAnimationAction(own controller, 0x1e)`, `root.command_hit_soon(partner, 2, zero)`,
  `partner.command_hit_soon(root, 3, zero)`. Then always `ClearAttackData`.
- 70 THROW_MODE_STORE_TARGET (0x6a9349): exclusion list = [logic +0x18, the animation
  partner]. Player: h = player control +0x1c; when both `UnderbossLib` platform globals are
  set, the dot of the throw direction with the direction to the platform exceeds 0.5 and the
  distance is under 12.0, the platform is the target; otherwise
  `CharacterAIBrain.command_get_target(wrap(h + π), degtorad × 60, 10.0, 0, exclusions)`. NPC:
  the same call with the heading of the visual's −in vector. A target becomes
  `root.m_eoverrideheadingentity`; without one the entity is 0 and `m_voverrideheadingpos` is
  a point 10 m out (root + direction(wrap(h + π)) × 10 for a player, the visual's −in vector ×
  10 for an NPC). The platform direction is horizontal; for a player without a target the
  fall-back point uses the camera's forward vector when `PlayerCtrl.m_nmoveintensity` < 0.1
  (0x9e9628).
- Footsteps, events 6 / 40 / 76 / 77: bone id `command_get_boneID(0x11)` for event 40, else
  `(0xb)`; no ragdoll actor on the foot, no sound. A ray from root + up × 0.5 to root − up ×
  0.5 (masks 0x1020 and −1); a hit whose owner's collision mask has bit 0x1000 goes to list
  A; otherwise a hit whose shape +0x14c is not 2 goes to list B and ends the walk; a hit with
  neither is skipped (the mask is not reset when the owner is not a rigid body, AI world
  node, geometry affector or pivot sheet). Effect package: from B[0] by model, else by
  texture, else 6; when A is non-empty and the A–B depth is non-zero, from A[0] by model, else
  0x47. The sound comes from `CollisionEffectCtrl.command_get_sound_in_package_based_on_enum`
  and is played by `SoundEffectType.command_apply_effect` or `EffectCtrl.command_fire_effect`.
  Sound enum by `_icharactertype` and event:

  | Character type | 76 | 77 | 6 / 40 |
  |---|---|---|---|
  | 0 | 0x41 | 0x3e | 0x35 |
  | 1 | 0x42 | 0x3f | 0x36 |
  | 0x1c, 0x21, 0x23 | 0x5c | 0x5d | 0x5b |
  | other | 0x40 | 0x3d | 0x21 |

## 7. The face system

Research notes: the face mechanism and the map of all body states are in `face.md` /
`face_map.json`; the numbers the toolkit uses are in `wlib/face_rule.py`.

### The head is a second character [code + data]

- A character with a face has, in its CharVisual fragment, a `Character` node named
  `HeadModel` with its own `AnimationCtrlWM`. `CharacterHeadCtrl` (class 193, registration
  0x671099) owns the body and the head; `Init` 0x664a11 finds both controllers by name
  (read). Rorschach's CharVisual has no HeadModel: no face controller (data).
- Animation classes of the heads (data, `m_ianimationclassid` of the two controllers):
  `EN1_FACE` 7 (Enemy01Face) for body classes Enemy01 (3) and EnemyBig (5); `EN4_FACE` 11
  (Enemy04Face) for Enemy04 (10); `NTO_FACE` 8 (NiteOwlFace) for NiteOwl (1).
- **Which head model** (read): `command_activate` 0x669496 reads the variant's head model
  type (`m_iHeadModelType`, enum ANIMATION_HEAD_MODEL, §2), asks the body collection's
  `_eheadmodelcollection` (property 0x6ed452d4) for the model of that type —
  `CharacterModelCollection.command_get_model_by_id` 0x66cbdd, hash 0x8ffd39d: the first
  member whose `m_iHeadModelType` equals the id — and copies that node's model settings to
  the head character (`Character::CopyModelResSettingsFromCharacter`). So the head collection
  node (ThugFace, BordelloFace, NightClubFace, TwilightHeadFace) decides both the model and
  its texture sheets. This is the only head the head controller instantiates; nothing in
  0x669496 selects by distance or LOD. Runtime classes: CharacterHeadModel
  (characterheadmodel_tnt.cpp, autodropdown over the enum) + HeadCtrl script (FUN_0069c8e3
  reads m_iHeadModelType and picks the model from the level's head
  CharacterModelCollection — BordelloFace.fragment holds GimpHead1-3 + the 5 female cutscene
  heads; gimpmask special-cased). Not established: what the body character does with the
  static head (`KnotTop_Large_Head1`, `GimpHead3_NoSKL`, …) that its own model list names —
  the list of a Gimp variant even names two heads.
- Data: KnotTop_Medium type 3 → `Medium_Head_1`; KnotTop_Small type 8 → `Small_Head_1KT`;
  KnotTop_Large type 13 (LARGE_HEAD_GOATEE) → `Large_Head_1`; Gimp1/2 type 26 → `GimpHead3`.
  The gag-ball Gimps' types are crossed against their static heads (Gimp7 lists
  `GimpHead1_NoSKL` and `GimpHead1`, type 20 = HEAD_GIMP_2); the export takes the rigged twin
  named in the variant's own list there and records both. Dominatrix variants map: 1→21 (D2),
  2→18 (D1), 4→24 (D4), 5/7/10→23 (D3 = afro / dark head), 6→25 (D5), 8→24, 9→21.
- Body skin (data): no code or data path selects a dark body texture.
  FemaleSkinBody_{Dominatrix1,Black} both ship with zero references; every suit model and
  every variant sheet says FemaleSkinBody_White. The dark trio differs only by head (enum 23).
  The toolkit's `_Black` TEX_OVERRIDES is a deliberate restoration, not game-exact.
- **Attachment** (read, 0x669496): the head model is placed at the body's world transform
  turned 90° about +Y (half-angle constant π/4 at 0xa0f240) and attached at the body's
  `Spine2`. Every frame `HeadCharacterUpdate` 0x66a2a5 / `UpdateHeadBone` 0x663ea5 overwrite
  the head's `Head` and `Neck` bones with the body's (bone map entries 0..2 = Head, Neck,
  Bip01; with head type 1, Nite Owl, also the clavicles and upper-arm twists). Bones below
  `Head` keep the face controller's pose.

### What drives the face class [code]

All nine sites that fetch the head's animation controller (command hash 0x31908a4d) were
read. Four inputs, nothing else:

| input | when | where |
|---|---|---|
| enum CHARACTER_MODE (1) | every frame | `CharacterVisual.command_update_animation` 0x69b988, at 0x69c728 |
| action NORMAL_ATTACK (1) | every frame while the body state has "Attack state" | 0x69c764 |
| action HITTAKEN (2) + enum DAMAGE_POSE (4) | a hit | `command_hit_soon` 0x6903ea (0x6906be), `command_give_damage` 0x691b10 (0x6929e9), event IMPACT_EFFECTS 0x6ab6a6 (pose = the event's `m_ivalue00`, through DirectionManipulateDamage 0x802ae8), event DO_CHOKE_EFFECT 0x6a7512 (pose 16) |
| actions START_SPEAK (31) / STOP_SPEAK (32) | a voice line or grunt starts; every frame no voice has the character root as pivot | 0x69b7a1, 0x69b806, 0x69c7d7 |

- An IMPACT event in a state that is not an attack state builds a damage record with pose 0
  (0x6ac9dd); DIE (0x6ac4e1) and KILL_ANIMATION_PARTNER (0x6ac5f6) use pose 0 and damage
  100000; `is_attack_successful` returns 1 in 33 of 37 registrations (§2), so a pair's IMPACT
  is delivered. `give_damage` reaches the head when the victim's health is above 0, it is
  not dead and its +0x16c is not 1; a PRE_IMPACT hit uses the state's `m_idamagepose` after
  ComboManipulateDamage 0x675ce6, DirectionManipulateDamage and the size / height modifiers
  (`SetCloseCombatDamageToTarget` 0x6ae57f) — run-time values, not in the animation data.
- **CHARACTER_MODE.** 1 when (in combat, or weapon held, or `m_tforcecombat`) and (playable,
  or player-controlled, or `m_istateofmind != 0`); also for non-playable types 8–11 without a
  player controller; 3 while the stun timer runs; 2 in StateDead. The head gets it when the
  body controller updated, the character moves, or it is being pushed.
- **Face evaluation.** Every frame while the head is in a camera frustum within 9.0 m
  (0xa45bec). STOP_SPEAK fires every frame no voice has the character root as pivot (a
  footstep's voice has it). Category 0 lines send no START_SPEAK; category 1 lines are the
  only ones that send it; category 2 are grunts (§14). DAMAGE_POSE on the head is never
  cleared (39 `SetAnimationEnum` sites). Not traced: whether `EvaluateTransitions` runs on
  every update of a face whose character is making a sound.

### The face classes [data]

Every face clip is a one-frame pose; states ease in over 0.21 s (0.37 s on Enemy04
`KnockDownMiddleLeft(ClosedEyes)`). Groups: Alive { Active { Idles (random), HitResponse
(ACTION HITTAKEN), Combat }, Talk (random) }, Dead.

- Idles: IdleA for at least 3 s, IdleB for at least 0.5 s, each left by a PLAY_TIME
  transition back into the random group, which may pick the same state again (then nothing
  happens): with two members a 1/2 chance per frame. EN1: IdleB = `Provocatively`. EN4: IdleB
  = `MouthClosed_EyesClosed` — the blink. NTO: one idle state. Idle group entry is random
  (`command_get_valid_state` 0x5f076f).
- HitResponse: members test DAMAGE_POSE; the group returns to Idles at PLAY_TIME ≥ 0.75 s
  (EN1, EN4) unless the class leaves earlier (`STUN_MIDDLE` (20) → `Retreat` after one
  update on a silent character). NTO has no timed exit: it leaves on STOP_SPEAK, i.e. when
  the grunt ends.
- Talk: members re-rolled after 0.2 s (0.15 s); no visemes, no amplitude.
- Dead: not random; DeadA.
- The Alive group's transition to Active fires on STOP_SPEAK, i.e. on every silent frame. It
  does not re-roll the idle state each frame because of the tested-list rule of
  `command_get_valid_state`.
- The Attack state plays its first slot alone (uncontrolled blend); when the mode is COMBAT.

`anim_meta.json` `face` holds the classes, the inputs per body state and pair and the
simulated tracks; docs/ANIMATION_META.md describes the block. Not established: which voice
and wave plays (the length of a line is that of its wave); the pose a hit ends with after the
run-time conversions (their rules are read: `combat.rules.damage_pose`).

### Toolkit: face tracks

The default export bakes the face track the game's face classes produce. `--face-rule legacy`
writes the older synthesis instead: `wlib/face_synth.py` `blend_pal` (per-bone slerp between
static pose palettes), `blink_anim` (open->0.07s close->0.07s hold->0.10s open, loopable
4s), `talk_anim` (4Hz syllable bursts × phrase envelope, seeded, loop-clean),
`category_pose` (body-clip name -> shipped pose name); `_face_attach` appends 'FACE SYNTH
Blink' / 'FACE SYNTH Talk' (shipped poses only: blink = BS2 family only, males / NTO ship no
eyes-closed pose); every body animation's face channels = category pose (ATT / WPN / counter
-> Attack1 | Shout | Biting, DMG -> DamageL/R/Stomach, dead -> Dead1/2, dance / flirt ->
Provocatively | Smile) or neutral + sparse BLINK keys on the EyeLid bone (~3s cadence,
deterministic per clip name through zlib.crc32, so rebuilds are byte-reproducible). The legacy
blink cadence is an invention.

### Ruled out

- There is no procedural blink timer: zero blink / eyelid / facectrl strings in the exe. The
  blink is data (Enemy04Face IdleB after at least 3 s of IdleA, held at least 0.5 s).
- Blink / talk timing is not audio-driven in the face class; talk is a random pose re-roll.

## 8. Characters: outfits, weapons, LOD

### Which outfit a character gets [code + data]

- A `CharacterModelCollection` owns `CharacterHeadModel` children, each a complete outfit:
  `modelNames` (slot 0 the skeleton, empty string = empty slot), `m_iheadmodeltype`,
  `m_iprioritymodel`, `textureSheetsDescription`. `initialize_local` 0x66cd2a walks the child
  list (first child at node+0x4c, next sibling at +0x50) and gives every member an instance
  count of 0.
- The child list is kept sorted by `siblingOrder` (int16 at node+0x46): the insert 0x48f556
  puts a node before the first sibling with a larger order, after those with an equal one
  (ties keep insertion order); `Node::SetSiblingOrder` 0x48f5e9 unlinks (0x48f5b9) and
  re-inserts. Data: in the four collections with several same-named members the orders ascend
  in file order (Heavy 1…18).
- `command_get_model` 0x66ca15 (PS3 0x71a980): with a non-zero request the LAST member whose
  `m_iprioritymodel` equals it (the loop has no break; a request of 0 never selects), else
  the member with the LOWEST instance count (`imincount` starts at 1000, strict `<`), the
  first of them in list order; its count is incremented. No random number is drawn. Asked by
  `CharacterDef.command_get_override_model` 0x666d03 from
  `CharacterRoot::InstantiateSubSystems` 0x67884e; a placement asks through its
  `m_iprioritymodel` (the level export says per placement whether a member matches,
  `characters[].variant`). `command_decrease_model_ref` 0x66ccad gives a model back (sent
  only for the body model, 0x6791b9; never for a weapon); counts fall in
  `DeleteCharacterVisualFragment` 0x67909b (on delete, and on deactivation of a dead
  character). Weapon collections are shared between definitions, so their counts are too.
- Data: Heavy 18 members, KnotTop_Medium 11, KnotTop_Large 11, KnotTop_Small 9, all under
  one name; the Dominatrices collection has 9 members with 9 names (1, 2, 4–10; there is no
  `Dominatrix_3` in the game), Gimp 2, GimpGagBall 5. The least-used pick runs over the whole
  collection, so a level's first Dominatrix is `Dominatrix_1`, its second `Dominatrix_2`, and
  so on.
- The enemy collections are instanced by the level's root fragment, inside the level block.
  A restart or checkpoint restore from the in-game menu (`MenuIngameCtrl` →
  `MasterSceneCtrl.command_load_current_level` 0x78de32) deactivates that block;
  `SceneScope.StateDeactivate` 0x813f5d unloads it (`LoadBlock::Unload` 0x4a02f0) and the
  reload runs `initialize_local` 0x66cd2a again, so instance counts restart at 0 and the
  variants repeat per attempt. Weapon and player collections under `GameEssentials`: not
  established. Which member a "candidates" placement gets in a given session is history
  dependent.
- Per-level override models run: `CharacterDef.command_get_override_model` 0x666d03 →
  `LevelSceneCtrl` 0x76ef49.

### Which weapon [code + data]

- `InstantiateSubSystems` 0x67884e creates the weapon attach node on bone `Attach RHand` and
  sends `command_set_weapon` (hash 0xdb10269e) with the root's `_iweapontype` (root+400;
  WEAPON_TYPES −1 NONE, 0 BASH_1H, 1 BASH_2H; default −1).
- `CharacterRoot.command_set_weapon` 0x694378: −1 removes the weapon; 0 / 1 take ONE model
  from the CharacterDef's `m_emodelcollbash1h` / `m_emodelcollbash2h` collection through the
  same get_model rule, clone and attach it. At most one weapon. The selection also goes
  through the script blackboard vars thas1h / 2hweapon. The second call for character type
  0x23 (Twilight Lady) is inert in shipped data: `command_set_weapon` 0x6943b8 sets
  `g_efaketwilightladyweapon` only when the type-0x23 definition has `m_emodelcollbash1h`,
  which is null on PC, PS3 and X360.
- Data (the CharacterDef cross-references, resolved in `WeaponDB.fragment`): Thug and
  ThugFast `ThugsWeapons_1H` + `ThugsWeapons_2H`; ThugBig `ThugsWeaponsBIG_1H` +
  `ThugsWeapons_2H`; Heavies `HeaviesWeapons_1H` + `HeaviesWeapons_2H`; Gimp and GimpGagBall
  `GimpWeapons_1H` + `GimpWeapons_2H`; Dominatrices `DominitrixWeapons_1H` only (police baton,
  paddle); Twilight Lady none (her whip is a model of her own visual). There is no exe table
  for the class -> weapon binding. Hit-effect entityrefs (Sharp / Body / Head weapon wood /
  steel ...) belong to the CharacterEffectDef class @0x66f652. Players get all 15 weapons in
  the export (a choice).
- Not established: which weapon model a character holds in a pair.

### Character LOD [code]

One incoming character per frame, in registration order; the nearest 16 get level 2, the
rest 1, deleted ones 0 (`CharacterLodCtrl.StateActive` 0x66bb68).

### Skeleton binds and head rigs (toolkit)

- Bind FK: tb == Rb[par] @ tloc + tb[par] exactly (0 error) on all skeletons; Rb orthonormal
  to 1e-15; world bone lengths constant (rel-std 0.0000) across clips. Shared EN1 clips give
  identical world motion across medium / large / small (same lerp metric values). Caches:
  222 / 222 / 222 / 190 / 235 clips for medium / large / small / bs2 / nto. nto against its
  raw capture (`nto_captured_palettes_t1.npy`, 63-bone, bind order offset 0) locks tight
  windows down to d = 0.01 (`NTO_COM_ATT_combo_super_B`); medium / large / small / bs2 have
  no captures.
- Capture palettes are in BIND-BONE ORDER (rotate-by-one gives garbage); worn-cowl rigs
  (`NiteOwl_Mask2`, 17 slots, vc51) use ordered names filtered + rotate-by-one.
- Worn-cowl palettes (`KapowMulti.1.trace`, v7 parser with vc >= 40; vc48 = 16-bone rigs,
  vc51 = 17-bone, beside the known 138 / 144 / 189; 159k live palettes across 5.8k frames;
  446-frame sample, all orthonormal; identified by the rigid bone-length fingerprint, Neck-Head
  0.055): the 'Bip01' and 'Interact' slots are exactly constant (identity in the draw's
  instance space) — the engine never drives a mini-rig root; its verts ride the model
  instance. 'L/R Clavicle' + 'LUpArmTwist' are rigid to Head (relD rot_sd 0.014), not driven
  from the body clavicles; Neck is independently driven (sd 0.18 vs Head 0.30); Jaw / face
  bones carry pose locals (Jaw rot_sd 0.04 = talking). Engine truth: entity-ride skirt base +
  head-rigid clavicles. The body 'interact' palette is the entity transform (0 rotation in
  all clips; a walk carries 4.9m of translation). vc48 palettes (54k; weapons / other heads)
  are unmined. Trace record format: `[u32 frame][u32 vc][vc*4 floats]`; gate real palettes on
  orthonormal rotation blocks first (rank-1 arrays pass naive fingerprints).
- The cowl's `Bip01` is a zeroed mini-rig root (Head's grandparent, bind at origin); M4 =
  90deg + 0.40m (the cowl is authored in model space, not body space), 0.34m/122deg off the body
  root; Twilight Lady's Bip01 0.29m/123deg, weightless. 273 skirt-base verts carry
  Bip01 weight.
- Toolkit choice (deliberate fidelity improvement over the engine): in `_face_attach`, face-rig
  slots not under Head whose names exist in the body bind (NAME_MAP Bip01 -> Bip) are
  re-slotted to per-body-slot proxy joints (the weight-transfer mechanism; `proxy_slots`
  returned unconditionally), gated by alignment — only bones whose bind agrees with the body
  bind under M4 (2 cm / 5deg) are proxied, with per-bone `proxy_align` (B_body @ inv(B_face))
  threaded through `write_glb`; misaligned bones (the mini-rig root) proxy to Spine2 (fallback
  Spine1 / Spine) with align = M4 (S = P_spine2 @ M4: exact at rest, follows the chest). NTO
  rides Bip / Neck / 2×Clavicle / 2×UpArmTwist; TwilightLady rides Bip / Neck. A Head-anchor
  ride pitches the skirt base 22.5deg with the head in idles; an entity ride leaves it at
  rest height while the torso moves. HEAD_SWAPS heads' body weights (Bip01 / Neck) go through
  the weight-transfer path; EXTRA_HEADS masks proxy Neck / clavicles / twists; Heavies_Head_1
  is wired in EXTRA_HEADS (the Heavy variant is a headless wardrobe set; `Heavy.glb` carries
  the face attach). Head-twin ICP /
  weight transfer is accurate to 0.7 mm. gimp `JiggleBelly` receives no clip track by design
  (physics bone).
- `characters_export.py` applies jiggle per skeleton to the loaded animations (per-clip try;
  skeletons without jiggle bones detected on the first failure); GLB and bake npz writes are
  atomic (tmp + os.replace); jiggled palettes are memoized under `_bake/<key>_j...`; npz
  members are read lazily. RSH / NTO palette-set mixing residual 0.03-0.06 (data analysis,
  not decomp). Profiled (stdlib + numpy): bake 29ms/clip, jiggle 21ms/clip, write_glb
  0.15s/30 anims, face attach 0.85s, `_icp_refine` 0.45s, load_parts vertex decode 0.5s,
  weight-transfer python loop ~1s on the worst head; the wall clock is file I/O and repeated
  per-variant work (`char_lib._texdir` is an os.walk index, 2.2s -> ~0.2s per process;
  `char_lib._find_layers` is memoized per (mat, roots, flip), so the normal-map green-flip
  re-encode is paid once, find_textures repeat 0.00s).

## 9. Jiggle (CharacterAddonCtrl + PhysX NxD6Joint)

Reports: `re/jiggle.md`, `re/physx_d6.md` (+ `.json`). The simulation is PhysX 2.8.1
(PhysXLoader.dll, virtual dispatch — hence no import-level evidence); the game only configures
an NxD6Joint and clamps the result. Game addresses: setup 0x6574cd, joint 0x648858 (spring
consumption 0x648b27-0x648cd1), update 0x6563a0; the game wraps PhysX in
kernel/collision/physx/physx_{physicssystem,rigidbody}.cpp (PhysXBlockCloth allocators), and
ships the PhysX 2.8.1 installer under prerequisites/.

### File constants [code + data]

PhysicsWorld (script class "PhysicsSimulation" / "PhysicsWorld", id 0xfb): the ctor 0x7eba0e
registers 16 float props in order (defaults at 0x7ebb10..); values live in a block at
[[[0xe171f8]+0x10]]+0x10 + slot*4 (0xe171f8 = script-class instance global). Consumption is by
direct slot read; each hash appears exactly once in the exe (its registration).

| Slot | Property | Hash | Registered default | `GameEssentials.fragment` value |
|---|---|---|---|---|
| 7 | m_nbreastspringconstant (k) | 0x868ac175 | 1000 | 200 |
| 8 | m_nbreastspringdamping (d) | 0x35ae65e1 | 0.5 | 0.8 |
| 9 | m_nbreastdistancelimit | 0x0daaedf3 | 0.08 | 0.08 |
| 10 / 11 / 12 | belly k / d / limit | 0x05da2a7e / 0x92c25d0c / 0xaac6d51e | 1000 / 0.5 / 0.1 | 70 / 0.8 / 0.1 |
| 13 / 14 / 15 | hair k / d / limit | 0xd0d08f4d / 0xbfbeb999 / 0x87ba318b | 1000 / 0.5 / 0.3 | 100 / 0.8 / 0.3 |

The same node sets gravity = (0, -14.82, 0) (the PhysicsWorld ctor FUN_0050d1e1 initialises
(0, -9.82, 0), f32 @0xa26418, only code ref 0x50d214), physicsIntegrationRateInHz = 60,
maxPhysicsIntegrationTimesteps = 3. All file-side.

### Addon setup (FUN_006574cd = 0x6574cd) [code]

- Addons, bound by name string: Spine2 -> BreastL, Spine2 -> BreastR, Spine -> JiggleBelly,
  Head -> Hair. An addon is built only for a bone the skeleton has.
- Per addon two `MockupBox`es: the ANCHOR, 0.1 m (three size props set to f32 0.1 @0x9e664c),
  kinematic, moved to the PARENT bone every frame; the BODY, 0.8 m (f32 @0xa06d84), mass 0.1
  (RigidBody::SetMass = FUN_004fe514 = 0x4fe514, stores [body+0xa0], virtual +0xb4: the argument if
  above a threshold, else 0.1), dynamic, placed on the child bone. movementtype = 1, enabled,
  collision-grouped. The `EmbeddedJointNode` is a child of the anchor box. Box prop hashes
  0x33aba79c / 0x7801dabd / 0xdaec7a56 (sizes), 0x61f13948 / 0x2708acba (generic node bools, set 1
  after config); the MockupBox class is not in reg_dump (kernel registration path), created by name
  via 0x47bc97.
- RigidBody ctor 0x4fe311: 4 solver iterations, linear damping 0, angular damping 1.0. The
  game calls `setMaxAngularVelocity(200)` on its bodies (0x5072a4).
- The per-type distance limit (slots 9 / 12 / 15) is copied to [joint+0xc] at 0x657c93: addon
  idx 0/1 -> slot 9 (breast), 2 -> slot 12 (belly), 3 -> slot 15 (hair).
- Joint (0x648858, 0x648b27-0x648cd1): k / d are selected per addon type (breast slots
  0x1c / 0x20 = 7 / 8, belly 0x28 / 0x2c, hair 0x34 / 0x38 in the ×4 block) and applied to
  the D6Joint at [body+0x138]:

      SetYMotionType(0=Locked) 0x517982, SetZMotionType(0=Locked) 0x517994
      Swing1LimitSpring  = k    (0x5194ed -> [d6+0x100])
      Swing2LimitSpring  = k    (0x5195b0 -> [d6+0x120])
      Swing1LimitDamping = d    (0x519516 -> [d6+0x108])
      Swing2LimitDamping = d    (0x5195d9 -> [d6+0x128])
      Swing1LimitValue   = 45.0 (0x51947c <- const @0x9fffa8)
      Swing2LimitValue   = 0.0  (0x51953f)

  Setter -> name proof: D6Joint property registration records at 0x520xxx pair "D6Joint::Set<Prop>"
  debug strings with the setter functions (c7 45 e0 imm32). Motion enum Locked 0, Limited 1, Free 2
  (== NxD6JointMotion). X / Y / Z translation and twist (X) are locked; Swing1 (Y) and Swing2 (Z)
  are Limited with spring k and damping d verbatim, restitution 0, limit values 45deg / 0 deg
  (Swing1 45 deg, Swing2 0deg). Nothing on the path scales k or d; only the limit angles are
  converted (× 0.0174533). The joint frame is the anchor box's frame = the parent bone frame; the
  pivot is the parent bone origin, the lever the parent -> bone offset (0.132 m for the breasts).
- The joint has no drive: the descriptor fill 0x5146ec writes `driveType` 0 for x, y, z,
  swing, twist and slerp (0x51478e–0x5147c7) and skips the motor block when joint+0x3c = 0
  (0x514b4e). `useAccelerationSpring` 0, `solverExtrapolationFactor` 1.0, `maxForce` /
  `maxTorque` FLT_MAX (0x5148bc–0x5148dc). Hair (Head → Hair) is configured by the same calls
  with its own constants.
- `NxJointDesc.actor[0]` is the dynamic 0.8 m box (addon record[1]) and stays body 0 down to
  `PxsD6Joint` +4; the anchor (record[0]) is body 1 (game 0x648944 / 0x648968,
  0x4a8e1a–0x4a8edc, 0x5141ee; DLL 0x10146e20, 0x100a19c0, 0x10081ad0, 0x102271e0,
  0x10227db0). The anchor's atom has inverse mass 0, inverse inertia 0, damping 0 / 0 and no
  velocity limit: `Body::setKinematic` 0x10037f30, called from `loadFromDesc` 0x10037900.
  `setMass`, `setLinearDamping` and `setAngularDamping` (0x10032f00, 0x10033150, 0x100331b0)
  do not reach the atom while the body is kinematic. Atom +0xa1 is the sleep flag (property
  7), not a kinematic flag. (That record[1] is the dynamic box and record[0] the anchor is the
  record table of `re/jiggle.md`, not re-read at the creation site.)

### Update per frame (FUN_006563a0 = 0x6563a0) [code]

Three phases: 0x6563a0-0x6567bc show / hide (walks the child boxes, sets visibility by node
type — typechecks 0x4985f1 / 0x4cda0a / 0x4f51d0, setters 0x51ac25 setVisible / 0x512aaa /
0x51544f; boxes hidden unless [world+0x6c] in {0, 2}); 0x6567c0-0x656865 fetch the character
root / fallback bone (0x493a64, [0xe14324]+0x2a4); 0x65686a-0x6574ae per-box dynamics
writeback (per record ebx: limit [ebx+4], delta [ebx+0x60], length [+0x6c], t [+0x70],
current quaternion [ebx+0x18], anchor quaternion [ebx+0x50]; box world pos [box+0xa4], quat
[box+0xb8]; the "Invalid Sqrt argument" guards normalise the delta):

- anchor box -> parent bone world pose; p, q = body pose in the anchor's frame;
- ApplyForce(−m × gravity) (0x656fb4-0x65707c): the game cancels gravity on the jiggle body
  every frame;
- p0, q0 = the bone's animated local pose; d = p − p0; if |d| > limit: t = limit / |d|, p =
  p0 + d t, q = slerp(q0, q, t) (FUN_0041fd54: dot, shortest-path flip, sin weights);
  SetBoneLocal(bone, p, q). Local position AND rotation are replaced, with no gain. The clamp
  is on the bone-origin displacement in metres: 0.08 / 0.10 / 0.30 m (breast / belly / hair).
- The body pose read in a frame is the previous physics result: one frame of latency (order
  in 0x6563a0; measured on the captures). The latency is the game's, not PhysX's: the game
  moves the anchor and reads the body in the same update, before the step.

Step: h = 1 / physicsIntegrationRateInHz, up to maxPhysicsIntegrationTimesteps per frame
(file values: 60 Hz, 3)
(`setTiming(1/rate, maxSteps, NX_TIMESTEP_FIXED)`, FUN_004f4d20 = 0x4f4d20); the game calls simulate
only when `floor(accumulated / h) > 0` (0x4f4ddc). Above 60 fps some frames therefore take no
physics step, and the step that follows carries two anti-gravity forces. The SDK defaults are
maxTimestep 1/60, maxIter 8 (PhysXDocumentation.pdf, 554 pp.); the game sets rate 60 and
maxIter 3.

### What PhysX does with the joint (`re/physx_d6.md`) [code, `PhysXCore.dll`]

Path: `NpD6Joint::loadFromDesc` 0x10135430 → `D6Joint` prepare 0x100804c0 (a limited axis
becomes locked only when limit value AND spring are 0, so swing2 stays limited) → low-level
descriptor 0x10081ad0 → `PxsD6Joint`, whose constraint setup 0x10227db0 the island solve
0x10201330 calls once per substep.

Rows for this configuration, in buffer order:

- twist locked: axis from 0x10226e60, rhs = −2·qx / dt, bilateral.
- cone limit (0x1022bcf1–0x1022be9b). Two limited swing axes are one elliptic cone. With y,
  z, w the swing quaternion: `fy = y²/(y²+z²)`, `fz = z²/(y²+z²)`, `limit = L1·L2 / (L1·fz +
  L2·fy)` with `L = tan(limit angle / 4)`, error `e = sqrt(y²+z²)/(w + 1) = tan(swing/4)`.
  The row is emitted when `limit − 0.025005 < e` (f32 @0x102a0f84), rhs = (limit − e)/dt,
  impulse ≥ 0 only. With L2 = 0 the limit is 0 whenever z ≠ 0 and 0/0 = NaN (no row) when z
  = 0, and quaternion components below 1e-4 (f32 @0x1028089c) are set to 0 first. So the one
  row pulls the whole swing, both axes, toward zero whenever the swing-2 component is at
  least 1e-4 (0.0115°), and a pure swing-1 deviation gets no row.
- three locked linear rows on the parent→bone lever (0x10227640): along the anchor
  separation and two perpendiculars (0x10227010) once |d|² > 1.19e-7 (f32 @0x1028058c), else
  along the joint axes; rhs = −(n·d)/dt.

Row coefficients (0x10227a70 angular, 0x102068b0 soft):

    m     = 1 / (a · I⁻¹ · a)        the body's world inverse inertia about its centre
    B     = m · 0.7                  f32 @0x1029e1b8
    soft, spring ≠ 0:  dd = max(d, 1e-5)
    gamma = 1 / (dt · (dd + k·dt))   erp = k·dt / (dd + k·dt)
    f     = 1 / (m·gamma + 1)        c = m / (1/gamma + m)
    B    *= erp · f                  m *= f

`c` is the decay coefficient of the improved spring solver (`NX_IMPROVED_SPRING_SOLVER`, SDK
parameter 98, default 1.0 at 0x100ac8d0; the game's physics module sets only `NX_SKIN_WIDTH`,
0x50d51f). Spring and damping are force quantities: the softness is scaled by the row's
effective mass, which is the cube's inertia about its centre, 0.1 · 0.8² / 6 = 0.010667
kg·m². At dt = 1/60: breast gamma 14.52, erp 0.806; belly gamma 30.51, erp 0.593. Joint
springs are implicitly integrated within the solver (PhysX doc, Solver Accuracy Tips).

Solver: 4 iterations over all rows in buffer order (0x1022c8d0 core, 0x1022ce80 angular,
0x1022ccb0 linear; the count is the body's `solverIterationCount`, set to 4 by the game). The
velocities are then saved as the "motion velocity" (0x10206570), and a conclude pass
(0x1022d500 / 0x1022d450) sets rhs = 0 on bilateral rows and max(rhs, 0) on limit rows,
scales `c` by lambda_v / lambda, and solves each block once more. The pose is integrated with
the motion velocity, i.e. the pre-conclude one (0x102008a0); the body keeps the post-conclude
velocity.

Body and scene:

- per substep: `v += a·dt`, angular damping `ω *= 1 − c·dt` with c = 1.0, clamp |ω| ≤ 200
  rad/s (0x101ffb50; the SDK default NX_MAX_ANGULAR_VELOCITY 7 rad/s does not apply).
- kinematic anchor: `moveGlobalPose` stores a target (0x10033430); on the first substep it
  becomes a constant velocity held for all n substeps of the simulate (0x10034c10). If |w −
  1| ≤ 1e-6 (f32 @0x102a1990) the angular velocity is 0: an anchor rotation below 0.16° per
  frame is not executed until it accumulates. That the anchor enters the solver with zero
  inverse mass is inferred.
- forces: the accumulator is used as acceleration in every substep and cleared on the last
  one of a simulate (0x10035330), so the per-frame anti-gravity force cancels gravity in
  every substep.
- The game-side wrapper FUN_0095abb0 / 0x95ac50 reads [d6+0x100] / [+0x120] / [+0x108] /
  [+0x128] and the dt at [slot+0x58] into the accumulators [+0x19c] / [+0x1a0] / [+0x1a4]
  with a 1.5 constant @0x9e8320; what that 1.5 belongs to is not established (the row
  arithmetic above is the DLL's).

Net effect: the swing relaxes toward zero at about `0.175·k / (d + k·dt)` — 8.47 s⁻¹ breasts
(k 200), 6.23 s⁻¹ belly (k 70), 7.09 s⁻¹ hair (k 100), all with d 0.8 — while the swing
direction can orbit, damped only by the body's angular damping. It is close to a first-order
relaxation, not a second-order oscillator with the file's k and d. No (K, D) pair of a linear
model reproduces it: the row is one-sided and acts at position level, so a fitted pair
depends on the excitation. Fitting the linear pivot model to the reference integrator's own
output gives a flat valley around K 900, D 25–30 for the breasts. `K = k/I` (about 16,000) is
wrong by the factor tan(θ/4) ≈ θ/4, the 0.7 and the implicit softening.

### Capture facts [measured]

Captures: `dominatrix_capture/ALL_deduped_palettes.npy` (14587×48×3×4) is the fight capture
(dominatrix tracks, 5,730 frames); `gimp_captured_palettes_t2.npy` (gimp, 1,621 frames,
single-track, slot order = bind order, zero offset; its two streams are two characters, each
sampled every frame). The fight tracks are interleaved (lag-6 anchor autocorrelation); a
greedy nearest-neighbour anchor tracker (<0.06m/frame, gap<=12) gives 26 tracks of >= 150
samples and 46 uniform segments (stream gap 3..9). The baked clips have zero authored breast
animation, so the captured deviation (bind cancels: dev = angle(P_breast · P_parent^T)) is
pure engine jiggle.

- 5.9 % of the breast frames and 7.7 % of the belly frames have a bit-identical jiggle
  palette while the parent moves: frames without a physics step. The capture therefore
  averaged about 64–65 fps with uneven frame times; on the other 92–94 % of frames there was
  one physics step per captured frame.
- read-back lag, scanned in captured frames: minimum at 1.00 frame for both groups (twist
  residual 0.46 deg breasts / 0.22 deg belly; lever rigid to 3.3 mm / 0.83 mm against the
  parent origin of the previous frame). Taken relative to the previous frame's parent pose, X
  is the locked twist axis (twist 0.45 deg rms) and the two swing axes respond alike.
- no gravity term in the captured response (the per-frame anti-gravity force); capture
  maxima of the bone-origin displacement: 0.0800 m (breast).
- one-step map on non-frozen frames, `φ⁺ = c1·φ + c2·δ + c3·w + c4·a`, c1 / c2 / c3: belly
  captured 0.899 / −0.778 / 0.798, solver with the file's k = 70: 0.890 / −0.775 / 0.800 (k =
  200 would give c1 = 0.817); BreastL captured 0.809 / −0.673 / 0.680, solver 0.805 / −0.702
  / 0.721. Radial relaxation per step on quiet frames: belly −0.055 captured, −0.060 solver;
  breast −0.129 both. The file constants are confirmed for both groups.
- scanning k in the reference integrator (BreastL, one step per frame): 20 → 9.0° rms, 70 →
  4.7°, 120 → 3.4°, 200 → 3.02°, 400 → 3.11°. The file value is the optimum.
- belly: with the capture's own step pattern the reference integrator reaches 1.34° rms on
  frames 60 onward (fitted pivot model 1.30°); started from the captured state, 2.05° on
  frames 8 onward with a mean-magnitude ratio of 1.00. The same two corrections take the
  breasts to 2.26° / 2.21° rms and a ratio of 1.01 / 1.00 (fitted pivot 3.15° / 2.73°, 1.34 /
  1.23). Segments of 100–272 frames begin in mid-motion.
- nightclub dancers do not jiggle (breast palette == Spine2 palette); they are
  CharacterSimple entities. Captured belly deviation: 0.88deg overall, 0.31 low-motion, 1.18
  high-motion; idle breast deviation about 1.4deg.

### Which characters get the addon controller [measured]

PC, PS3 and X360 Part 2; no Part 1 PC fragment has one (`grep -c CharacterAddonCtrl` on every
`CharacterVisual/*.fragment`):

| Fragment | pc_p2 | ps3_p2 | x360_p2 | pc_p1 |
|---|---|---|---|---|
| `Bs2CharVisual` | yes | yes | yes | (absent) |
| `En4CharVisual` | yes | yes | yes | (absent) |
| `GoonCharVisual` | yes | yes | yes | no |
| `PrisonerBigCharVisual` | yes | yes | yes | no |
| `En3`, `NiteOwn`, `PrisonerFast`, `Rorschach` | no | no | no | no |
| `UnderbossCharVisual` | (absent) | (absent) | (absent) | no |

The controller is a node authored in the data; an addon is built only for a bone the
skeleton has (`BreastL`, `BreastR`, `JiggleBelly`, `Hair`; read from code). Not checked:
ps3_p1, x360_p1.

### Toolkit: `wlib/jiggle_d6.py`

`jiggle_d6.apply_jiggle(P, fps, bind, model='solver'|'pivot'|'pinned', mode=..., props=,
extract_root=, latency=None, warmup=None)` — the interface of `jiggle_pass`. It reads the
PhysicsWorld props from `GameEssentials.fragment.json` and the geometry from the bind npz.
`jiggle_d6.DEFAULT_MODEL` = `'solver'`; `pinned` and `pivot` are opt-in (`--jiggle-model pivot`,
`--jiggle-model pinned`).
`jiggle_pass.py` without a `jiggle_params.npz` delegates to jiggle_d6 (the npz is not shipped
in the toolkit; the capture-fit path stays for comparison). `variant_glb.py --jiggle` uses
jiggle_d6.

- **solver** (`jiggle_d6.SoftLimitJoint`): steps the PhysX soft-limit row with the file
  constants only (`k`, `d`, `limit` per group, `rate_hz`); its one mode is `'file'`
  (`SOLVER_MODE`), any other raises `ValueError`. The clip is played at one physics step per
  1/rate_hz s: step j drives the anchor to the parent pose at t = j/rate_hz, interpolated
  between clip frames with Catmull-Rom and exact on a frame; the state after step j is shown
  at j/rate_hz + latency (default one step); each clip frame takes the body pose interpolated
  between the two physics states around it, in its own parent frame, then the metre clamp.
  `warmup=n` plays the clip n times as a loop first. The model runs in float64 with the DLL's
  thresholds as constants. Cache tag `solver-file-<hash>`; `MODEL_REVISION["solver"]` is 2
  and the four bake constants are in the cache tag. Not modelled: frames with 0, 2 or 3
  physics steps and the doubled anti-gravity force after a zero-step frame, which belong to a
  play session, not to a clip.
- **pivot** (mode `'capture'`): the engine geometry (pivot = parent bone origin, lever =
  parent -> bone offset, clamp on the bone-origin displacement in metres) with linear swing
  constants fitted on the captures under a 55 fps time base — breast K about 570 s^-2, D
  about 37.5 s^-1; belly K about 308, D about 19.2; parent angular-acceleration coupling
  0.84-0.92; linear coupling consistent with m / I of the 0.8 m cube; no gravity term. These
  are the model's built-in constants, not engine facts.
- **pinned** (modes `'engine'` | `'ratio'` | `'absolute'`): the older model — x'' = −K x − D x'
  + r × f − alpha_parent (rotation vector in the parent frame) with r = tb, the bone's
  position from the model origin (0.346 m for the breasts), simulated at 60Hz, engine radial
  clamp. Its r × f coupling is a serviceable proxy on isolated clips; on gimp clips it
  overshoots the captured belly deviation about 2.5-3x (absolute error ~1.5-2.7deg).
- Jiggled palettes are cached per model in `_bake/<key>_j_<model>-<mode>-<hash>/`; inside
  that folder a solver bake of a clip the game loops is `<clip>.loop.npz`, any other bake
  `<clip>.npz` (`jiggle_d6.cache_file`, cache key version 2); a memo older than its raw bake
  is baked again.

How `_apply_jiggle_solver` bakes a clip (toolkit rules, chosen and measured; none of this is
read from the game):

- Looping clip (the game's `loop` flag, `clips[name]["loop"]` of the animation metadata; 156
  of 1,159 clips): laps are played from rest until the body state at the lap boundary
  repeats (`SOLVER_LOOP_TOL` 2e-5 on position, quaternion and per-step velocity) or 12 s of
  laps have gone by (`SOLVER_LOOP_SETTLE`), at least 2 laps, at most 40. One more lap is
  recorded and whatever end / start mismatch is left is spread over it, so the lap closes
  exactly. A fixed lap count does not work: walks and idles repeat after 1–2 laps,
  `EN4_COM_ATT_dash_cycle` needs about 20 (13 s), and `EN2_COM_MOV_run_cycle` never becomes
  exactly periodic. Laps used on 18 staged looping clips: 2–14; correction spread over the
  lap: 0.000–0.37°. A lap is F − 1 frames when the last frame repeats frame 0 in the parent
  pose (nearly every looping clip), else F frames.
- Clip that does not loop: the parent is taken to have moved at the velocity of the clip's
  first frame interval for 0.25 s (`SOLVER_LEAD_IN`) before frame 0. A clip that starts
  still therefore still starts at rest. On windows cut out of the two captures the frame-0
  error falls from 4.38° / 4.00° / 2.12° (BreastL / BreastR / JiggleBelly, at rest) to 3.44°
  / 2.90° / 1.83°; frames 1–30 are within ±4 %. Whole-capture error, frames 60 onward,
  against the at-rest solver: 2.31° → 2.24°, 2.36° → 2.40°, 1.64° → 1.63°.
- Fewer than 4 frames: returned unchanged.

Measured wrap discontinuity (jiggle bone relative to its parent, last frame against frame 0),
18 staged looping clips: `pinned` 1.42–4.85°; `solver` 0.00–0.03° on the 14 clips whose
parent pose closes and 0.18–0.75° on the 4 where it does not (the animation's own mismatch).
On the full export (all looping jiggle channels): Gimp skeleton, 35 channels, median 2.61° →
0.03°, maximum 7.02° → 0.50°; female skeletons, 94 channels, median 1.71° → 0.03°, maximum
5.63° → 3.72°, where the 3.72° is `EN4_COM_MOV_strafe_right_long`, whose `Spine2` itself
differs by 3.72° between its last and first frame.

Scoreboard (at-rest start, one physics step per captured frame, rotation error rms, BreastL /
BreastR / JiggleBelly; breast tracks 23 and 39 excluded):

    frames 8..     pinned 5.38 / 4.93 / 4.25°   pivot (capture) 3.15 / 2.73 / 1.99°   solver 3.02 / 2.70 / 2.35°
    frames 60..    pinned 4.75 / 4.61 / 3.63°   pivot (capture) 2.32 / 2.38 / 1.30°   solver 2.31 / 2.36 / 1.64°

Bone-origin error rms, frames 8..: pinned 15.8 / 15.1 / 5.6 mm, pivot 6.2 / 5.6 / 3.6 mm,
solver 6.0 / 5.6 / 4.2 mm. On the breasts the file-only solver equals the capture-fitted pivot
model; on the belly it is behind it in this like-for-like run and level with it once the
capture's step pattern is used (1.34° against 1.30°). Under the 55 fps time base and all
tracks, pinned -> pivot (BreastL / BreastR / JiggleBelly): rotation error rms 5.90 / 5.64 /
4.09 deg -> 4.29 / 4.13 / 1.96; origin error 16.4 / 15.8 / 5.6 mm -> 8.0 / 7.7 / 3.5; fitted
gain 0.34 / 0.35 / 0.16 -> 0.98 / 0.96 / 0.87; mean-magnitude ratio 1.05 / 1.02 / 0.52 -> 1.57
/ 1.47 / 1.58 (the ratio of about 1.5 is the effect of the zero-step frames and of segments
that start in mid-motion, see "Capture facts").

### Not established

- Whether the 0.8 m jiggle box collides with anything (the script sets no collision group on
  the boxes; `MockupBox` is a `CollisionNode` and does not go through the per-instance group
  counter 0x51d5ad; the resulting group is not established; the captures do not need it).
- Hair: no capture, and no staged bind has a `Hair` bone (synthetic test only).
- Why the swing orbit dies somewhat faster than the model's on a few violent capture events.
- That the high-level `D6Joint` functions (0x10082550, 0x100868c0) do not also act
  (inferred, supported by the agreement above).
- What the game played before a clip (the body never resets between states, so every start
  is an assumption); the game's own steady state on a looping clip (no capture of one in
  isolation exists); the large swing on dash cycles (`EN4_COM_ATT_dash_cycle` 10.7–11.9° mean
  against 5.6–5.9° with `pinned`; the parent turns at 200–390 °/s; no capture to check it
  against).

### Ruled out

- m_n*springdamping 0.8 is not a damping ratio (d = 2ζ√k ≈ 20.9) and not an absolute
  torque-domain NxSpringDesc damper; the values go into the NxJointLimitSoftDesc of the two
  swing limits, where they are force quantities scaled by the row's effective mass.
- The solver does not apply force = −k·x − d·v, nor a torque law
  `tau = spring*err + damping*vel`, nor the softening `solver_soften` k_eff = k / (1 + d·dts +
  k·dts²), d_eff = d / (same) at any dts (1/120 or 1/60).
- There is no planar wedge with one free swing axis (swing1 free to 45°, swing2 spring-
  restored): with a 0° semi-axis the elliptic cone has radius 0 and its one soft row restores
  the whole swing. An anisotropic mode with a free axis is an inverted pendulum that drifts to
  the clamp (~10deg) under gravity in a model that drives it with gravity.
- Gravity does not drive the pendulum (the game cancels it every frame); there is no static
  gravity sag (an idle sag of 1.6-1.7deg is a model artefact); the captured mean deviation is
  zero.
- The capture did not run at 30fps or at 55 fps (55Hz); the K / D pairs derived with those rates —
  k 166-170 / d 17.9-19.4 (30 fps), K 570 / D 37.5 and belly 308 / 19.2 (55 fps), per-axis
  K~6 / D~40 (parent X) and K~146.5 / D~10.7 (parent Z) — are not engine facts.
- The simulated body is not the 0.1 m box (that is the kinematic anchor); the lever is not
  tb (0.346 m) and the clamp is not on the angle.
- The physics step is 1/60 s, not the frame tick, and not two substeps of 1/120 s.
- The `.model` node aux records are collision volumes (§15), not jiggle joint frames; the
  joint is created at run time in the parent bone's frame; the swing axes are the parent
  bone's Y and Z, not the capsule quaternions.
- The "x1.7 dynamic amplitude gap" of the pinned model against a capture-fit AR(2) with gain
  1.4 was a comparison against the fit, not against the capture; the game-side writeback has
  no gain.

## 10. Ragdoll, character controller, PhysX scenes

### PhysX scenes [code]

Two PhysX scenes (`PhysicsSystem` ctor 0x50d1e1): scene 0 holds the world, the character
capsules, ragdolls, triggers and jiggle boxes; scene 1 the cloth and its kinematic collision
bodies, without contact reports. A node's two collision-volume lists (§15) are the ragdoll
shapes (scene 0) and the cloth-collision shapes (scene 1). Scene start / fetch order per
frame: §3. The physics module sets only `NX_SKIN_WIDTH` (0x50d51f).

### Ragdoll [code + data]

The rig is data in the model file (`ModelRes::Read` 0x547006 → 0x51e1ad), not code:
`CharacterRagdollSetup` is an editor tool whose tables are the authoring defaults. A
`Character` instantiates the articulated body of model slot 0 only (vtable slot 41, 0x4bee1e →
0x51d5ad). 17 bodies, 16 PhysX 2.8.1 D6 joints, linear motion locked, swing / twist limits
mostly soft. Shapes are created 0.025 larger with a skin width of 0.025. While animated the
bodies are kinematic in collision group 4 (enemies), 8 (Rorschach) or 9 (Nite Owl); going
limp they become dynamic in place, solver iterations are raised from 4 to 10, and the script
sets velocities from the hit; a bone with a body takes the body's transform, every other bone
rides its nearest ancestor with a body. The gameplay capsule is a separate `NxController`.
Ragdoll is run-time PhysX and not part of clip playback. Toolkit: `wlib/ragdoll_rig.py`,
`docs/RAGDOLL_RIG.md`; rigs of all 13 models in `docs/re/wp2_ragdoll_rigs.json`.

Get-up (`CharacterVisual.command_update_ragdoll` 0x6bc3e2):

- **Animation value 6** (`CHARACTER_PELVIS_ROTATION`): `qpelvisbasis` = quaternion of rows
  (down, left, out); Q = basis ⊗ pelvis world orientation; A = rot(up, Q); B = horizontal A
  normalised (zero if vertical); D = B × up; E = rot(right, Q); value = 57.29578 × ATan2(E·up,
  E·D), where ATan2 0x5aa394 uses sign = −1 for nY ≤ 0. Edge cases: nY = 0 with nX < 0 gives
  −180; a vertical body with nY ≤ 0 gives −90. (`anim_meta.pelvis_rotation`; the four ragdoll
  values are described in `conventions.ragdoll_values` of `anim_meta.json`.)
- **Expand volume**: start when pelvis speed < 0.85; grow over 0.35 s (÷ timescale); overlap
  time accumulates and above 0.1 s restarts growth with timescale × 4 and counter + 1; free
  when fully grown for more than 0.15 s; the free flag is cleared every frame.
- **Enemy veto**: no get-up within 1.5 m horizontal of either playable character.
- **Kill rule**: counter ≥ 3, or death timer > 3.0, or fail-safe timer > 15.0 →
  `command_give_ragdoll_damage_increment(100000)`.
- Constant addresses: 0xa3d8b8, 0x9f8148, 0x9e664c, 0x9e5a40, 0xa11984, 0x9e5ff0, 0x9e6910,
  0x9eba80.
- Data: `m_tuseexpandvolumeforgetup` is never overridden (906 pc_p2, 758 pc_p1, 906 x360_p2
  fragments).

Ragdoll release and contact damage: §11 "Damage".

Velocities at the start of ragdoll control (`CharacterVisual.StateRagdollDriven` 0x69ed7c entry, in order;
read from code):

- The bodies keep the velocity they already have; the entry reads it (`characterlib.GetRagdollMeanVelocity`)
  and does not reset it. It is the velocity PhysX gave the body for the last move it executed while kinematic
  (`v = Δx/(n·h)`, 0x10034c10; zero after a simulate with no target); neither `setKinematic(false)` nor the
  awake-body path of the readback writes it (`docs/RAGDOLL_RIG.md` "While the game runs"). Which game update's
  move that is: not established.
- `m_nnormragdollspeed` (CharacterVisual +0x58) > 0 and mean speed > 0.5 (f32 0x9e6174): every bone velocity is
  scaled so the mean speed equals it (`ScaleRagdollBoneVelocities`). `command_give_damage` 0x691b10 sets it to 3.5
  (f32 0xa554f0) in its killing branch; the entry resets it to −1.0 (f32 0x9e6a8c) at the end.
- `m_vragdollvelincrease` (+0x4c) is added to every bone (`AddRagdollBoneVelocities` 0x67a035), then zeroed; no
  script writer found.
- `m_vragdollcolliderimpulsevelocity` (+0x28) × `m_nragdollimpactforcefromcollider` → `SetRagdollMeanImpuls`; no
  script writer of +0x28 found.
- `m_vragdollcollidervelocity` (+0x34) × `m_nragdollimpactforcefromcollider` → `SetRagdollMeanVelocity`. Written
  by `ModelCollisionContactAdded` when a body's accumulated impact force passes `m_nragdollimpactragdolltrigger`:
  the colliding ragdoll's mean velocity. `m_nragdollimpactforcefromcollider` (CharacterVisualDef +0x10, caption
  "Transfer Force Scale") has registered default 1.2 (0x676a41); the shipped `CharacterVisual.fragment` stores
  1.2 as well (measured, pc_p2 extract).
- `m_vragdollcolliderangularvelocity` (+0x40) → `SetRagdollAngularVelocity` on ragdoll bone enum 32; only ever
  zeroed in script.
- The pelvis body's velocity with y = 0 is kept as `vinitragdollpelvisvelocity`.

### Character controller [code; `NxCharacter.dll` 2.8.1.6]

- Controller descriptor (0x4fdfb3): up Y; slope limit 45° always (constructor 0x4f60f1;
  `SetSlopeLimit` 0x4fe288 has no caller, no fragment property in 906 + 758 + 906 files),
  descriptor slope = cos 45° = 0.7071; skin width 0.025 (0x4fe1a4); step offset 0.5 at
  construction, then `m_ninitsteplimit` at `command_activate_collision` (call at 0x67cdfb):
  class default 0.1, 0.3 in the three `CharacterRootTemplate_*` fragments (all six sets; PC
  Part 1, PC Part 2 and Xbox 360 Part 2 checked); radius width/2 + 0.025 = 0.425, height 1.2,
  constrained climbing, interaction flag 2. Wall-stop and wall-slide angle 46°
  (`m_nangleforwallcontrol`, no override).
- **What the capsule's move collides with** [code]: `CharacterPhysics.command_attempt_move` passes
  `m_icollisionmask` (members +0x08, the pivot-sheet mask from the collision node, `command_activate_collision`
  0x67cc00) and `m_icharactercollisiongroupmask` (+0x0c) to `CharacterController.move`. `StateOnGround` 0x67d2a5 sets
  +0x0c on every entry to 2^0 + 2^1 + 2^2 + 2^5 = 39 (WORLD, ACTIVE_ / INACTIVE_CHAR_PHYSICS, DYNAMIC_WORLD; exponents
  from `fldz`, `fld1`, 2.0, 5.0 @0x9e97fc); `StateCharge` 0x67d89e sets its own. `command_activate_collision` also
  fixes +0x15c world group 1, +0x160 dynamic world 32, +0x164 ragdoll feedback 8, +0x168 object feedback 32 (2^0,
  2^5, 2^3, 2^5). A dead body is in a unique dynamic ragdoll group 24–27 (`StateRagdollDriven`), outside 39, so the
  capsule passes through it. Adding bits 24–27 (0x0F000000) to +0x0c after each `StateOnGround` entry is the
  narrowest switch: camera and AI casts use their own masks (inferred that `NxController::move` filters shapes by
  this mask alone, as in the PhysX 2.8 SDK).
- NxCharacter 2.8.1.6: proxy capsule 0.8 × size, kinematic; 10 sweep iterations; step offset
  only with sideways motion; sharpness < 0 = test move, sharpness 1 = no smoothing;
  `getPosition` is the exposed position, which the game refreshes itself at 0x502977. The
  game overwrites the proxy's 'CCTS' tag (0x4fe256); a controller still never hits its own
  proxy because the capsule sweep (PhysXCore 0x100ec7f0) reports nothing when it starts
  inside the other capsule.
- Environment cloth: radius 1.5, multiplier 2.0 (Part 2 `GameEssentials`), impulse = (1 −
  d/r) · multiplier · capsule linear velocity (0x667aca).
- Cloth world fixes: 0x507dd0 calls cloth vtable +0x74 with the vertex and then 0x4b96bc
  (0x507e42, 0x507e47) for an attachment value of −1; 0x4b96a8 loads `*(*(cloth+0xa4))` and
  jumps to 0x4b6e9f = `cmp dword [(x+0x24 & ~3) + 0x28], 6`; 0x4b96bc also needs byte cloth
  +0x118. `Physics::Cloth` vfunc 30 0x4f7572 stores the mesh item's +0x34 object at +0xa4;
  creation gate 0x50c95f. Xbox 360 Part 2: 0x8294fc30, test 0x822e33c8.

## 11. Combat, damage and AI

Reports: `re/wp3_combat.md`, `re/wp4_ai.md`. Consumer docs: COMBAT_META.md
(`wlib/combat_meta.py`), LEVEL_META.md (`wlib/level_meta.py`). Read from code unless noted;
constants from the executable's bytes.

### Combat

- **Where a counter happens** [code]: the button reaches `CharacterRootLogic.command_counter_attack` 0x68664c, which
  calls `TestForCounterAttack` 0x68d36a; that method returns 1 only after it has fired COUNTER_ATTACK (12) into the
  animation controller, so its true return is the one point every performed counter passes (players and AI alike;
  `_echaracterroot.m_eplayerctrl` tells them apart). `AchievementCtrl` / `AchievementPart2Ctrl.
  command_counter_attack_by_signed_in_player` (hash 0x11b982ae) is never sent: the hash occurs only at its two
  registrations (0x5a10ed, 0x5a1caf).

- **Combo speed-up is by animation type**, not by button: LIGHTATTACK 0.15 s, HEAVYATTACK
  0.2 s, any other type none, so Enemy01 / EnemyBig attacks (NOTSET) never speed up. It needs
  more than one item in the combo list and, for an AI, a running combo or `_tforcespeedup`.
  The lead is divided by the clip's own duration (`start_animation_state` 0x688961, 0x689834
  / 0x689883).
- `INITIAL_ATTACK` is fired by `ExecuteAttack` 0x68b351 when a fresh string starts and the
  current state is not an attack state.
- A kick's damage is the button's base damage: `AddAttackToCombo` 0x68bca8 sets the base
  damage first and only then turns the item into KICK for a prone target.
- Damage modifier inputs: EnemyDef reads `_ndamagemodifier` (0 = the CharacterDef default);
  PartnerDef / AiDef read `m_ndamagemodifier`; without a behaviour handler the modifier is
  1.0 (`CharacterRoot.command_get_damage_modifier` 0x6931a4). All three getters (0x71f0cf,
  0x597273, 0x8841f3) return their own member when it is not 0 and the CharacterDef default
  otherwise. `UnderbossDef` +0x148 is `_ndamagemodifier` (+0x144 `_tmodifydamagemodifier`);
  0x8841f3 returns it when non-zero, else `CharacterDef.command_get_default_damage_modifier`
  0x666cf1. Shipped Underboss: own 0.0.
- Underboss floor: `UnderbossPhase1.StateActive` sends `set_lower_bound` (0x8932d1) with the
  phase threshold on every entry; max health is the `CharacterDef` value, because only
  `CharacterDef` registers into `g_echaracterdeflist` (0x666db8).
- "Big" = animation class model type 4 or 5 (`command_is_big` 0x68f192): EnemyBig only in
  Part 2, whiff distance 2.2 m.
- The counter margin is clip time: `(p1 - p) * D` with D the clip duration; a state with slot
  speed s leaves 0.13 / s seconds of real time.
- Derived: the engine takes the longest string equal to the tail of the presses, so
  sub-strings fire inside longer ones.
- Data: the `phase_2` / `phase_3` Twilight Lady definitions name no override database
  although their combo lists point into "Twilight Lady Combos". Part 2 PC: 336 attack states
  (Enemy01 52, Enemy04 49, EnemyBig 58, NiteOwl 83, Rorschach 94); 413 pair triggers (counter
  257, finisher 118, enemy counter 22, throw 10, bull rush 6). 12 combo databases,
  `throw_damage` 10 in "Enemy Combos", 15 elsewhere.
- `ElectricArmor.AreaDamage` 0x72769f: `t = max(0, (10.0 − d) / 10.0)`, d between the two
  `m_echaractervisual` positions, 10.0 a code constant (f32 0x9eb1d8; `m_nelectrifyrange` is
  not read here; its only reader, 0x6a71b6 in
  `CharacterRootLogic.command_animation_event_received` (event ELECTRIFY_ARMOR), stores it in
  a local that is not read afterwards, so the property — 4.0 in all six sets — has no
  effect); no further factor (it is the constant 1.0); a pose by distance and side: d >
  `m_nelectryfypushbackrange` → LIGHT (front 5 / 2, behind 24 / 23); d >
  `m_nelectryfyfallrange` → HEAVY (front 8 / 11, behind 26 / 25); else KNOCKDOWN (front 17 /
  14, behind 28 / 27); the first id is drawn when rand < 0.5; behind = the attacker's position
  has z < 0 in the victim root's frame; victims: other faction only, a playable victim not
  while its state is DODGE, a non-playable one only within ± 2.2 m of height; push 13.0 × t
  along the direction for 0.3 s.
- `command_electric_armor_hit` 0x71ea63 (PS3 twin 0x8ea0f8): true only in `StateActive` with
  charge power (+0x128) > 0 and takes 1 / `m_nelectrifycharges` off (charge += −1.0 /
  charges, floor 0, effect id 1).
- Sweep check point (`StateActivePlayPos` 0x698fe1): P = visual world position + (visual
  position − last recorded model position, refreshed after the check when it moved > 0.01 m)
  + conj(Q)·(sin r, 0, cos r)·Q × dist; Q = the visual's world orientation; r = angle[i−1] +
  pct × right slice (clockwise) or angle[i−1] − pct × (2π − right slice)
  (counter-clockwise); right slice(a, b) = a − b, plus 2π if negative, taken as (angle[i],
  angle[i−1]); dist = (1 − pct) × len[i−1] + pct × len[i]; pct = (counter − playpos[i−1]) /
  (playpos[i] − playpos[i−1]). Counter-clockwise when rightSlice(impact, begin) >
  rightSlice(end, begin) (`DetermindTravDir` 0x69b2be); the property `m_tcounterclockwise` is
  not read. One check per 0.05 play position (f32 0x9ebc04, `begin_sweep_attack` 0x698a43);
  hit within 0.8 m (f64 0x9ea130) of the travelled segment
  (`DoEnemyCheckAgainstTravelLine` 0x69a57d); `m_nchecksprsec` is never read.
- Bull rush (animation and state data measured on PC Part 2): animation event 15 CHARGE sends
  `CharacterPhysics.command_state_charge`; the state ends in free fall as soon as the current
  state's special handling is not BULL_MOVE. Animation value 9 DISTANCE_TO_END_POS = 3D
  distance root to lock target, 0 without a target, 10.0 while the target blocks or is
  electrified (`SendBullRushDataToAnimationCtrl` 0x696d2d); Rorschach starts the impact pair
  on [0.05, 1.0); EnemyBig 'Freight Train' leaves to CombatGroup below 2.0 or at animation
  end. Secondary victims: every target-list entry that is not a placeholder, the lock target
  or the animation partner, within capsule radius + 1.0 (3D), in front (dot(face heading,
  horizontal direction) > 0), with victim state `m_tstunlockstate` == 0 (set on the
  hit-reaction, Ragdoll-Hit, AttackBlocked and ThrownInAir states: 100 states on PC Part 2);
  damage `m_nbullrushsecondarydamage` with no global / uber / modifier factor, stun
  `m_nbullrushsecondarystun`; pose 11 or 8 (rand < 0.5 first) when |local x| ≥ 0.2 or the
  victim is big, else 17 or 14, then DirectionManipulateDamage; push, when animation speed >
  2.0: 0.3 s at 4.0 m/s along normalise(sign(local x), local y, local z) in the attacker's
  frame (diagonal to sideways, on the victim's side); in low violence a prone victim is
  skipped. A blocking or electrified playable lock target nearer than 1.1 m gets
  `hit_soon`(pose 2) and `give_block_damage`; the attacker is forced to animation 9 and fires
  actions 14 and 30.
- Faction filter: target lists come from `AIBrainNode.GetVisibleAIEnemies` 0x484235 (sweeps:
  Perception's known-enemy list, fed by `GetSeenAIEnemies` 0x48460d): another active agent
  whose faction is not NEUTRALFACTION (2) and differs from the caller's, and that passes the
  sight test; a character set as `Perception.m_forceperceptedcharacter` is added without a
  faction test; that member is written only by `Enemy.StateActive` 0x724071 (store at
  0x725078): on acquiring a target, each other living member of the enemy's group whose
  known-enemy list is empty receives the enemy's own target if the enemy can see it;
  `Perception.AddNewKnownEnemies` 0x7dcc88 uses it once and clears it.
- Not established: ragdoll contact force magnitudes and contact counts (so the health a
  throw really removes). Twilight Lady's punish and back-flip routines are read (COMBAT_META.md,
  `rules.twilight_lady_punish`, `rules.twilight_lady_back_flip`). Underboss: whether
  the registered defaults 3 / 2 are live (the shipped fragment stores neither property); its
  movement, flee and flamethrower volume rules are in COMBAT_META.md and `rules.underboss`.

### Damage

- **Throw.** `m_ndefaultdamagethrow` (hash 0xba104039) has no reader. Throw states carry no
  IMPACT or KILL_ANIMATION_PARTNER. Release (`CharacterTransferToRagdollControl` 0x5b16ed):
  9.0 m/s (f32 0xa45bec), 5.0 m/s for a big victim (f32 0x9e97fc). Data: 10 throw pairs (8 at
  9.0 m/s, 2 at 5.0 m/s).
- **Ragdoll contact damage** (`ModelCollisionContactAdded` 0x69d00a, 0x69d37c–0x69d4e8): x
  and z of the force × 0.2 (f64 0x9e97e8), length capped at 4000 (f32 0xa5ee58, f64
  0xa5ee60), damage = body mass × length × 7e-5 (f64 0xa5ee50); 100000 when the body is more
  than 3.0 m (f64 0x9e8670) below its partner's visual. Gates: force above
  `m_nragdollimpactforcethresholdforsound` (300), mean speed above 2.0 (f32 0x9e663c), not
  the own body, not a placeholder's (0x69d18c). Delivered when the sum exceeds 1.0
  (`StateRagdollDriven` 0x69ed7c → `give_ragdoll_damage_increment` 0x6914f2), × 0.3 (f32
  0x9e650c) for a player-controlled victim. Cap per contact = mass × 0.28.
- **Bystanders** (`DetermineDamageReaction` 0x6a18d1): damage × 0.0 (f64 0xc3cc18, `fmul` at
  0x6a193d), stun 3.0 s (f32 0x9e6910), pose one of 5 / 2 / 11 / 8. Above
  `m_nragdollimpactragdolltrigger` (6000) the bystander is ragdolled.
  `m_nragdollimpactignoretrigger` has no reader in script; `m_nragdollimpactforcefromcollider` is read only by
  `StateRagdollDriven` (velocity transfer, §10 "Velocities at the start of ragdoll control"). `_naddeddamage` decays by 20/s (f64 0x9e5c68; PS3 0x794a08–0x794a3c, PC 0x69f728)
  and is never read.
- **Hit formula** (`SetCloseCombatDamageToTarget` 0x6ae57f): the × 0.2 for electric armour
  applies to the base term only and not for an Underboss attacker; the charge bonus carries
  no modifier; the base is set in `InitializeNextAttack` 0x68bf6f; the size pose rule tests
  the attacker's main target; a blocked hit still costs weapon durability. The IMPACT_EFFECTS
  `m_ttruth1` call is `CharacterRootLogic.SetCloseCombatDamageToTarget(victim,
  m_ecuranimstate, m_nvalue)`.
- **Receiving** (`give_damage` 0x691b10, `DecreaseHealth` 0x695632): × 0.2 for an Underboss
  victim from a non-player character; paired-move filter; `max(1/uber, 0.7)` (threshold f64
  0xa3aff8, value f32 0x9e60d4) on a playable victim; floors (Underboss, AI partner 1.0,
  `m_nminhealth`). Death branch 0x695e83–0x696132: game event 201 for everyone; two
  versus-only outcomes keyed on `AIBrainNode.agentFaction` == 1.
- **Area attacks**: FLASH_GRENADE radius 3.0, (11.0 − distance) (f64 0xa5e9b0; PS3 store
  0x7aea90–0x7aea9c, PC 0x6a6c27) × modifier × global × uber for a playable target, else 0,
  stun 3.0 s. DISCHARGE_ARMOR base = attacker health + 10.0 (f64 0x9e5c60), or 0.4 (f64
  0x9eb790) × victim max health when playable. ELECTRIFY_ARMOR deals no damage itself;
  `ElectricArmor.AreaDamage` 0x72769f does.
- **Twilight Lady reaction** (0x7220c7): 0.22 (f64 0xa69770), 5.0 s (f64 0x9e70a0), 0.25 (f32
  0x9e6914), 1.5 (f32 0x9e5ff0).
- **`g_nglobaldamagefactor`**: default "1.000000" at 0x7f1ce6; no writer in script or native
  code; absent from the extracted fragments.
- Data: 9 of 31 AI definitions store a damage modifier of 0 and resolve to 1.0 or 1.5.

### Enemy AI, spawning, groups

- **AI pause** (`BehaviorHandler.command_set_pause(truth)` 0x618f33) [code]: first
  `BuildBehaviorMessageList` 0x615451 refills `_behaviorentitylist` (members +0x20) unless its
  first entry is already `_eactiverootbehavior` (members +0x0C): it is that root behaviour followed
  by every `Node` below it, depth first (`AILib.RecursivePushBackOfType(root, "Node", list, 0)`).
  Then every entry gets the property `enabled` (hash 0x2708acba) = `!tPause`. There is no separate
  pause flag: an enemy is paused when its active root behaviour has `enabled` = 0 (Node +0x54).
  Among the `Behavior*` classes nothing else writes `enabled` (lifted scripts; native writers not
  excluded). Senders of `set_pause`: `TriggerActionCharacterForceMove`,
  `KynapseStaticPathObjSceneClimbUp`, `WaypointCompleteAutoTest`, and `BehaviorHandler` itself
  (`StateBrainLessAutoTarget` pauses on entry and un-pauses in its exit block).

- **`Enemy.Evaluate` 0x72587d, order**: health <= 0 → INACTIVE; breadcrumb mode (AGGRESSIVE
  only, timer set and older than 2.0 s); forced state; target and step-back timer or
  behaviour running → STEP_BACK; **PASSIVE: outside its turf → RETURN_TO_COMBAT_ZONE,
  otherwise IDLING, and evaluation ends there** (0x726214 → 0x7264a2 → 0x726fc3) — no chase,
  no attack; AGGRESSIVE: the chase / attack / hang-back rules; any other state-of-mind value →
  IDLING.
- **PASSIVE → AGGRESSIVE** only by `Enemy.command_react_to_attack`,
  `CharacterRoot.command_give_damage` when the inflictor path runs (0x691b10),
  `command_give_ragdoll_damage_increment` (0x6914f2), being the attack target in
  `FireAttackBasedOnAttackID` 0x68d870, or the trigger action SET_AI_STATE.
  `command_set_aggressive` 0x693236 only sets a flag; `CharacterRoot.SetAggressive` 0x677f3f
  then sets the whole group. SET_AI_STATE counts: 105 / 79 / 43 (Bordello / NightClub /
  StreetsOfRiot). The action lists the CharacterRoots under `m_etarget1` (0x855ecb, 0x59d5db)
  and writes `m_iinteger1` (0x852a28).
- **Orchestrator grant**: per hero and frame one waiting attacker when the hero has fewer
  than the allowed current attacks and the last attack and grant are older than the attack
  frequency; no grant while the hero's animation is immune (current attacks are then broken
  off); dead waiting entries are erased. Base values in the staged levels: engagement 8.0,
  clamp 5, cooldown 2.0, max 3, frequency 0.2, idle 0.1. Presets: TRIG 0x851fba →
  `CombatOrchestratorParameters.command_trig` 0x6d9128 → `command_set_parameters`;
  `m_toninitialize` self-triggers at 0x6d910d.
- **Constants**: evaluation interval 0.0625 + rand × 0.1 s; melee max 4.5; remember time
  1.0 s (default; that it is live is inferred); step-back times 0.5 at init, 1.0 after first
  use or `command_force_step_back`; target scoring perpendicular factor 3.0, co-op factor
  1.2, near threshold 1.2 m (it serves attack-target selection in the animation-event
  handler). `FindClosestTargetWithTacticalOptions` 0x59d1ad is partner AI only (callers:
  `AttackKillTargetPartner`, `CrowdControlPartner`); it compares a squared distance with
  `m_nvisualrange`, so with the PartnerDef value 50 (all 13 PC Part 2 definitions; measured)
  it reaches √50 = 7.07 m. Part 1 has two PartnerDefs, 50 and 80 (√80 = 8.94 m; measured on
  the PC Part 1 export; the rule itself is read on the Part 2 exe only).
- **Weapons**: §8. `DO_BLOCK_FLASH` (event 84) is fired by Nite Owl's block clips only; no
  enemy counter is touched.
- **CharacterGroup**: zone = `m_ezonetrigger`, else first child with physics type 2
  (0x668a0e); return position = return point or first member, +0.5 y (double at 0x9e5dc8),
  only with members (0x668a99).
- No `CharacterSpawner` is placed in any Part 2 level.

### Partner AI (COMBAT_META.md, `combat.rules.partner_ai`)

- **`Partner.Evaluate` 0x7dba9f**: forced state; step back (timer or child running) →
  STEP_BACK; then only when the state of mind is AGGRESSIVE: in combat and `CombatPartner`
  preconditions → COMBAT, else human alive → FOLLOW_PARTNER; everything else (including
  PASSIVE) → IDELING. States 2, 5, 6, 7 only by forced state.
- **Run-time overrides of the definition** (`Partner.StateActive` 0x7daa2e): MEGA_KILL when,
  in combat, the human is beyond the brain's visibility distance (`m_nvisualrange`) and the
  trace between the two crosses the AI mesh: attack interval max 0.5 / min 0, damage modifier
  10. LOW_HEALTH when own health is below the low-health point outside PvP: the low-health
  attack interval, react probability 1.0. Restored when the condition ends or combat ends.
- **`CombatPartner.BehaviorSwitch` 0x6ed5d1**: `m_nkillvscrowdcontrol` 1 → crowd control, 0 →
  attack-kill, else p = that value ± 0.1 per rule (own attackers > 3 +, human's > 3 −, more
  than half of the human's known enemies attacking and stunned or prone −, human health < 50
  +, human unattacked +, self unattacked −, total > 10 +, total < 4 −); crowd control when
  rand <= p; re-drawn every `m_ncombatanalyzerbehaviorchangetime`. `CombatHelpPartner`
  replaces both while the human is below his low-health point, unless
  `m_tdisallowhelppartnerstate`.
- **Reaction to an attack** (0x6ebac7): p = `m_ncrowdcontrolprobofreactatt` × 1.2 (attacker's
  state is a paired-move master) × 0.4 (Twilight Lady) × 1.3 or 0.7 (own stun-lock state; 0.7
  when the attack is unblockable); then one draw r against counter (attacker in front, not
  low health), dodge, block, with r reduced by each rejected probability and floored at 0.01;
  a block of a paired attack only half the time; the chosen action is re-issued every frame
  for 0.3 s.
- **Partner's-target rule** (0x6eb7c7): the AI hero leaves the human's own target alone while
  the human is within 2.5 m of it, unless that enemy is outside the human's melee range or in
  melee behind him; Twilight Lady is exempt.
- **Specials**: Rorschach step-around window 5.0 s, bull rush when 1 −
  `m_nprobablityrorschachcharge` < own attackers × `m_ncrowdcontrolnumofenemymodifier` + rand;
  Nite Owl electrify when the third-nearest known enemy is within 3.0 m (attack-kill) or the
  second-nearest within 4.0 m (crowd control), stun grenade likewise at 4.0 m; Nite Owl throws
  a target with health > 80 while the armour charge is > 0.05. Combo timeout passed to
  `command_perform_combo`: items × 5.0 (crowd control), items × 0.5 (help).
- **Follow** (`FollowPartner.StateActive` 0x73e357): side point at
  `m_nfollowpartnermovedistancebetweentargetandpartner` (2.0 in data) on the side the AI hero
  is on, ahead by max(1.5, human speed); a wall hit pulls it to half the human capsule width
  + 0.01 short of the hit; in a corridor (both sides blocked at 2.0, tested every 3.0 s) the
  point goes 2.0 in front of the human if the AI hero is in front, else 2.0 behind. Stop
  inside 1.0; match speed inside 3.0 with 0.6 + 0.4 × (v − vmin)/(vmax − vmin), vmax/vmin
  4.83/3.32 (Rorschach human) or 4.77/2.67 (Nite Owl human), 0.4 when the human walks; forced
  stop when the human stands (speed < 0.1) within 4.0 m. Only while stuck (goal unreachable or
  no AI velocity): re-plan kick every 5.0 s, and if the human stays more than 20 m away for
  5.0 s, waypoint following until his breadcrumb is reachable (re-tested every 2.0 s).
- **`UberRageBehavior`** 0x879d9b: while `m_ninrageuberdamagefactor` <= 1.0 it raises
  `m_nrage` to at least 1.0 and sends `command_attack_uber_rage` every frame.
- **Defects in the shipped code**: `CrowdControlPartner.TakeCareOfOwnCrowd` passes a null
  target to `ThrowTarget` (0x6f2428), so its 'throw my stunned target' branch never fires
  (throws still come from `AnalyseSituation`). `AttackKillTargetPartner` passes its target,
  not itself, as the behaviour argument of `command_issue_normal_attack` (0x603129): the
  attack is registered with the target's `CharacterRoot` as the behaviour (0x603129 →
  0x6eb1c2 → 0x6252e3 → 0x6e620c). `CombatOrchestrator.command_attack_animation_stated`
  0x6e6495 sends `command_attack_animation_stated` to that root, which has no such command,
  so the behaviour's handler 0x601088 does not run; `command_release_attackers` 0x6e388e sends
  `command_break_off_attack` to the target's own root (0x691013: animation 9 with 0.3 s when
  the state is an attack state, its special handling is not 13 and, for type 25, the state id
  is not 13–18) instead of the partner's behaviour.
- **AI partner test** (`CharacterRoot.IsAIPartner` 0x678254): `CharacterDef.m_iplayablecharacter`
  != −1, `m_eplayerctrl` == null, and the brain's `AIBrainNode.agentFaction` (entity +0x8c)
  != 1 (ENEMYFACTION). `DecreaseHealth` 0x695632 uses it: an AI partner whose health would
  reach 0 is set to 1.0 (0x695875). `command_deactivate_player_ctrl` 0x7f51f3 (sent by
  `PlayerManager.command_reset` 0x7f9c64 on SCENE_DEACTIVATING) does not clear the root's
  `m_eplayerctrl`.
- **`BehaviorWaypointMove.StateActive`** 0x6289b4, per frame (not observed in game): (1)
  `m_tpauseleaderorder` set: if the breadcrumb timer is −1 or the breadcrumb is 0.5 m or
  more away, clear the flag; otherwise call `StateUseTrigger(root, breadcrumb position)`.
  (2) Current animation absolute: wait 1.0 s. (3) Breadcrumb timer −1 or not older than
  2.0 s: ask `WaypointController.command_get_next_waypoint_advanced(root, false)`; otherwise
  nothing this frame; no waypoint: stop. (4) Flying waypoint: Nite Owl (type 1) within 50 m
  calls `StateUseTrigger`; if that returns false, or for anyone else, the target becomes the
  waypoint's previous one (`m_epreviouswaypoint`, else `m_epreviousall`). (5) Agent type 1,
  go to the waypoint; moved less than 0.1 m for 5.0 s sets `_tforcewanderagent`. (6) AI
  velocity below 0.1 or that flag: stop; if the kick timer ran out (first 0.5 s after entry,
  then every 5.0 s), switch to agent type 3 for one frame and re-plan; otherwise, only when
  the root's `m_nmovespeed` (+0x54) is not above 0 and it stands within 1.0 m of the waypoint:
  with a `PlayerCtrl`, `StateUseTrigger` and on false `StateForceMove` 0x62aef5 (walk straight
  for 2.0 s); without a `PlayerCtrl` the branch only sets `_nfailtimer` = now + 5.0. (7)
  Moving: within 1.0 m, stop, and after standing 1.0 s call `StateUseTrigger` (the timer
  counts only while `m_nmovespeed` is 0 and is reset to −1 otherwise); otherwise run, walk
  inside 3.0 m. `StateUseTrigger` 0x629b68 calls `AILib.StopMove` first, then returns false
  when the root's `m_eplayerctrl` (+0x88) is null (0x629c52); an AI partner has none, so it
  never uses a trigger from here (inferred from two read facts).
  `combat.rules.partner_ai.waypoint_move` holds the constants.

### AIBrainNode and the Kynapse bridge

`AIBrainNode` constructor 0x486099 (constants from exe bytes) against the three
`CharacterRootTemplate_*` fragments (measured, PC Part 2 and PC Part 1, identical in both
parts):

| Property (offset) | Constructor | Templates |
|---|---|---|
| `agentType` (0x88) | 0 | 0 |
| `agentFaction` (0x8c) | 1 | 1 in all three |
| `maxSpeed` (0x90) | 5.0 | 5.0 |
| `followDist` (0x98) | 2.5 | 2.5 |
| `followAngle` (0xa0) | 180.0 | 180.0 |
| `subGoalMinDist` (0xcc) | 0.5 | 0.5 |
| `endGoalMinDist` / `endGoalMaxDist` (0xd0 / 0xd4) | 0.5 / 2.5 | same |
| `pathSearchRadius` (0xd8) | 50.0 | 50.0 |
| `dynamicAvoidanceType` (0xe0) | 0 | 0 |
| biped look-ahead distance / width (0xe4 / 0xe8) | 8.0 / 4.0 | same |
| biped passing distance (0xec) | **0.5** | **0.1** |
| biped max degrees per second / update period (0xf0 / 0xf4) | 360.0 / 0.1 | same |
| vehicle five (0xf8..0x108) | 10.0, 0.4, 0.5, −1.0, 10.0 | same (dead) |
| `eyePos` (0x10c) | (0,0,0) | **(0,1,0)** |
| `headDir` (0x11c) | (0,0,1) | **(0,0,0)** |
| `maxVisibilityHalfAngleDeg` (0x12c) | **70.0** | **90.0** |
| `maxVisibilityDistance` (0x130) | **50.0** | **30.0** |
| `isReferencePoint` (0x134) | **true** | Enemy **false**; both heroes true |
| `referenceRadius` (0x138) | 40.0 | 40.0 |

`subGoalSlowDownDist`, `endGoalSlowDownDist` and `maxDeltaAnglePerFrame` are dummies (getter
0x481155 returns 1.0, setter is the stub 0x48d55e) and are not serialised.
`pathFindingConstraint` is stored at +0xdc but a loaded value is discarded (0x48272c,
0x484cba).

What each entity sends to Kynapse every world update (`KynapseBaseEntity` 0x48a6a4,
`KynapseNPCEntity` 0x48ae80):

| Kynapse target | Source | Rule |
|---|---|---|
| position (entity +0x34) | `physicsVolume` world position (+0x88..) | x negated |
| speed (+0x58) | position delta / frame dt | values below 1e-5 are stored as 0 |
| orientation (+0x40 / +0x4c) | volume orientation applied to (0,0,1) | only updated when speed ≥ 1e-5 |
| `CEntityWidth` (+0x70) | volume +0xe8 − +0xd8 | x extent; only values ≥ 0 are written (0x489306) |
| `CEntityLength` (+0x74) | volume +0xf0 − +0xe0 | z extent |
| `CEntityMaxSpeed` (+0x9c) | `maxSpeed` | |
| `CEntityEyePosition` (+0xa0) | `eyePos` | x negated |
| `CEntityHeadDirection` (+0xa4) | `headDir` | x negated |
| `CEntityVisualAcuteness` (+0xa8) | `maxVisibilityHalfAngleDeg`, `maxVisibilityDistance` | angle clamped to 0..180 |
| `CEntityTeamSide` (+0xac) | `agentFaction` | 0 → 0, 1 → 1, 2 → −1 |
| path finder goal distances (0x94b7b0) | `endGoalMinDist`, `endGoalMaxDist` | min defaults to 0.5 m if negative; max to min + 0.5 m if below min |
| `CDetectPathNodeReached_Distance2D5` distance | `subGoalMinDist` | overrides definition `MaxDist = 1.0` (0x489c1b) |
| path finder +0x30 | `pathSearchRadius` (the call at 0x48af9e reads brain +0xd8) | overrides definition `FlatDataModeSearchRadius = 100.0` (0x4898f6) |
| `CGoto_GapDynamicAvoidance_v2` | biped look-ahead distance and width × 0.5, passing distance, max degrees per second, update period | 0x489a37–0x489af7 |

The overrides go to path finder 1 only (entity +0xd0); path finder 2, used for
`IsPosReachable`, keeps the definition values (0x48c491, 0x48af5b–0x48afad). No height
attribute is written for characters.

- **Occlusion** (callback 0x48b44e): an unsorted PhysX ray-all (0x503244) from A to B,
  filtered by `AIWorldNode.collisionMask` (+0x70) and `nodeCollisionMask` (+0x78). Only hit
  record 0 is tested: blocked when its node is a `CollisionNode` with `physicsType == 1`; a
  first record whose node is not a `CollisionNode` is "not blocked". Kynapse reads true as
  "blocked" (read from code): `Kaim::CVisibilityEntityInfo` slot 13, 0x943be0, loads the
  callback from `[0xd88e5c]` (0x943dd1), calls it (0x943df4) and stores
  `visible = (result == 0)` (`cmp al,bl; sete dl; mov [eax],dl`, 0x943e00–0x943e0c); a null
  callback gives visible.
  `[0xd88e5c]` is the bridge's slot +0x30: 0x9255e0 copies it to slot +0x24 of the block that
  0x923890 copies to 0xd88e38 (the +0x30 → +0x24 mapping is from the decompiler's local
  layout of 0x9255e0, not from disassembly).
- **First hit** (callback 0x48b56c): the nearest hit of any physics type (0x50a384), returned
  with x negated.
- **Faction filter** (0x484235 / 0x48460d enemies, 0x484421 / 0x4847e9 allies): enemy = the
  target's faction is not 2 and differs from mine; ally = not 2 and equal to mine.
- **Freshness** of a perception value: fresher than 300 ms: used; 300 ms to 1 s: cached
  value returned; older or never computed: recomputed synchronously (0x48a1b7, 0x935ab4).
  `ValidTime`, `UnsafeTime` and `Tpf` of the definition are milliseconds (0x935ab4, 0x935b11,
  0x925260, 0x92a8f2). Defaults without the keys: 0.2 s / 1.0 s (0x935710, f32 at 0x9ebc18).
  A background pass (0x944530, task `CEntityInfoManager::Update`, `Tpf` 1.0 ms, `MaxCall` 1
  in all 33 nav files) recomputes entries older than `ValidTime`. `CSightEntityInfo` 0x9460a0
  queries Visibility with compute mode 0 (0x946349): with a visibility entry older than
  `UnsafeTime` the Sight computation fails and the Sight entry keeps its value and stamp
  (0x944090). Sight cache internals: parser 0x935a60 (`ValidTime` × 0.001 → +0x3c,
  `UnsafeTime` × 0.001 → +0x40, `ImmediateMode` → byte +0x44; 0x9e76c8 = 0.001), clamp
  0x935c90 (`owner+0x98 − owner+0x94`, meaning not established), callers 0x48b8f3 / 0x48b891
  (1, 2) and 0x9460a0 (1, 0) at 0x946349–0x94635f.
- `includeInAIVisibilityCache` filters `CollisionNode` `Get*AIObjects` (0x4a2b9f); in
  0x49ca65 the entity type is always `DynamicObstacle` and only kinematic or dynamic nodes
  get one.
- Bridge init numbers 500 / 8 / 10 (0x48ee9f): the Kynapse capacities for entities (0x48eea5 →
  0x9239c0), worlds (0x48eeac → 0x923b70) and allocators (0x48eedd → 0x947380 → 0x946eb0);
  library defaults 1000 and 1 (0x92548a, 0x925491).

### Navigation data (NAV_DATA.md, `wlib/nav_data.py`)

- `.aipathdata` "KS BIG FILE" 0x48b3c0, 0x489e00, 0x488dab, 0x488e6e. `.hpd` header 0x90b310
  (version constant 1.3 @0x9e60c0), cell addressing 0x916040 / 0x90a3a0, cell data
  `CConcreteSlot` 0x9172c0, border vertices 0x909ea0, path objects 0x92dfa0 / 0x92d280, AI
  mesh `CAiMesh` 0x918940 with the grid 0x91b0d0, the inside test 0x91b470 (crossing parity)
  with 0x91c300 (altitude), inner walls 0x91b970, one-way zones 0x91b5f0.
- Kynapse space is engine space with x negated (bridge 0x48110f). The `.hpd` is
  little-endian on every platform; the swap routines 0x90b190, 0x90b240, 0x9172c0 are
  identities in the PC build and the files of PC, X360 and PS3 are byte-identical.
- The `.hpd` files are plain NAZ entries (`files/data/levels/.../gameplay/`), not outside the
  archive; only Part 1 PC ships them loose.
- The mesh is a 6 x 6 grid of 20 m squares per streaming cell; a square holds floors (an
  altitude range plus boundary segments), not triangles and not a height field. Data sits
  about 1 m above the ground (median 1.025 m above character pivots).
- **Path objects match level nodes by id**: the id is the 1-based index into the serialised
  `aiStaticPathObjectNodes` list of the level's `AIWorldNode` (lookup 0x4837d5, X360
  0x829f8260; registered 0x484ffb, setter 0x483844), written when the path data was
  generated. Bordello / NightClub / StreetsOfRiot: 127 of 128 by id (126 within 0.00002 m,
  NightClub id 16 at 0.1558 m); Bordello entry 45 is null (tag 1 at 0x2026 of
  `gameplay.fragment`) and is unbound in the game; the position join gives it a node at
  0.1196 m. By position 128 of 128 (131 of 131 with Tutorial and PlayerVsPlayer). The list is
  in tree order in Bordello only.
- Path-object `flags`: bit 0 run-time entry, bits 1–2 = 2 per-entity pass bits, bit 3 starts
  passable (0x92d380, 0x92dfa0); the mesh-link floats are a direction gate (0x9104d8); mesh
  +0x30 is a generation value the runtime does not read.
- Nav cell stamp 0x28 / 0x2c: one stamp per file in all 11 distinct files (120 cells); the
  loader writes 0xBAFFE000 for 1.0 files (0x90b310, 0x90b660); no reader found.
- Not established: abstract cells, lattice addressing and version 1.0 (code only, no file),
  why the graphs have many components.

## 12. Cameras, effects and particles

Report: `re/wp7_fx_camera_hud.md`. Consumer docs: FX_META.md (`wlib/fx_meta.py`),
PARTICLE_FORMAT.md (`wlib/particle_asset.py`). Read from code; constants from the
executable's bytes at the stated width; not checked in the running game.

### Finisher camera cuts

- **Cut placement** (`CameraCombatSpecialCuts.SetValidStartPos` 0x6341f7): angle term
  `((A + 180) / 360) * 2 pi - pi` (doubles 180 @0x9eaaf8, 360 @0xa00180, pi @0x9e5dd0) = A in
  radians, added to `MathLib.ToHeading(d)` 0x7800c0 = atan2(x, z); `ToDirection` 0x780210 =
  (sin h, 0, cos h). `angle != 0`: d = normalize_xz(target - actor), base = actor root; with
  `tLookAtAttackTarget` d is negated (-1 @0x9e8468) and base = target root; position = base +
  dir * distance + (0, 1, 0) * height. `angle = 0`: the perpendicular of the pair line at its
  midpoint (0.5 @0x9e5dc8), on the side of the current camera, the other side if the sweep
  (width = height = 0.2 @0x9ebc18) fails. `tKeepPreviousPosition`: the previous cut's target
  position, or the character camera's when there is none.
- **Where a cut's slow motion comes from** [code]: `CharacterRootLogic.command_animation_event_received`
  0x6a525e, branch event 59 (CAMERA_CUT), builds the `combatcutdata` from the event node's members and sends it with
  `CameraCtrl.command_set_combat_cut_data` (0xbd64ac28) → `CameraCombatSpecialCuts.command_set_cut_data` 0x6325c5.
  Mapping (cut field ← `AnimationEventWM` member): +0x00 ← `m_nvalue`, +0x04 ← `m_ttruth1`, +0x08 ← `m_ivalue00`,
  +0x0c ← `m_nvalue09`, +0x10 ← `m_nvalue02`, +0x14 ← `m_nvalue05`, +0x18 ← `m_nvalue10`, +0x1c ← `m_nvalue03`,
  **+0x20 `nTimeMultiplier` ← `m_nvalue04`** (members +0x30), +0x24 ← `m_ttruth2`, +0x28..+0x30 ← `m_nvalue06..08`. The cut
  state calls `WorldLib.SetTimeMultiplier(nTimeMultiplier)` (`StateTransition` 0x63312e; transitions 2 / 3 blend toward it); leaving the
  cut camera sets 1.0. So writing `m_nvalue04` = 1.0 on the CAMERA_CUT event nodes before a cut removes its slow
  motion and keeps the shot; the kill slow motion of `give_damage` (`_nslomotimemultiplier`) is separate.
- Look-at: `GetLookAtPosition` 0x634125; bone 18 = root + (0, look-at height, 0), else the
  bone's controlled world position. Bone type -> joint name: `CharacterVisual.SetupBoneMap`
  0x67a31e (§2). Hold update 0x633011: position fixed, aim recomputed; `UpdateWorldPos`
  0x633f28 has no caller (PC, X360, PS3), so the position is fixed for the shot; up = +Y
  (0x626a15). `WorldLib.SetTimeMultiplier` in `StateTransition` 0x63312e and at the end of
  the transition; `Reset` 0x62695d restores it.
- Blend 0x63312e / 0x6337aa: n += dt / T, HalfBell 0x779d40 = 0.5·(1 − cos πn)·sin(πn/2). The
  clock is the script `timepassed` global 0xe14304 (the game step; §3). The camera entity's
  own flag only decides whether its script runs while the game step is 0. Dropped when the
  horizontal view directions differ by more than 90° (0x634f62); 0.3 push-in sweep
  (0x9e650c). Return 0.9 s (0x9e5ecc) when the state is left without event 61. Co-op fov
  `ncoopfov` 75.
- Event cases: 61 0x6aa036 (`m_nvalue` blend back, `m_ttruth1`), 59 0x6aa7e4 (13 slots), 56
  0x6aae6f (also `m_ttruth3` + `_etarget01`: fire that effect at the point). The shake is
  `sin(time_factor × t) × (T − t)/T` in real seconds; events 29 / 30 / 31 / 60 / 69 fire
  effect ids 8 / none (the armour fires 0) / none / 12, 13 / 1, 10 (`fx.event_effects`).
- Data: 259 CAMERA_CUT events; cuts on 122 of 413 pairs (789 cuts, counting the 16 on four
  slave states `Countered_by_BS2_cattleprod_A|B`; at most 10 per pair); 175 side shots, 55
  kept positions, 29 angled; `look_at_height` is 0 on every shipped cut. 650 events carry
  stale slots of the node they were copied from. The table's `play_time_s` accounts for start
  position, slot speed and trigger kind.
- Not established: that a character's root is at floor level (inferred).

### Damage effects

- **TASER, not SHARP, fires the extra effect** (id 1 `ELECTRIC_ARMOR_DISCHARGE`, then the
  STEEL slot); SHARP selects the single `sharpweapon` slot
  (`CharacterEffectDef.command_play_damage_effect` 0x6673d0). No Part 2 weapon node has
  effect type TASER (15 WOOD, 4 STEEL, 2 SHARP). `g_efaketwilightladyweapon` is null in
  shipped data (§8).
- `FXGfxEffectCtrl`: `initialize_external` 0x73ccb6 hands the node to the PlayerCtrl of
  playable character `_iplayerctrl` (data: 0 on "RS GFX", 1 on "NO GFX"; 2 = both).
  `grademeta` exports `_iplayerctrl` and `m_tinitialgfxnode` as stored.
- Target highlight is dead code (`EffectsLib.Highlight` 0x714cc1 has no caller; both defs have
  bloom 0 and self-illumination 0).

### Gameplay cameras (FX_META.md "Gameplay cameras", `fx.camera.gameplay`)

- **Fight-camera (pad) distance** [code]: `CharacterCamera.InitializeCameraProperties` 0x655e27 (called only from
  `initialize_local` 0x64bead and the editor's `FilterExposedProperties`) fills `_cameraproperties` (members +0xfc,
  `list(cameramodeproperties)`): element 0 = exploration (uses `_ninitialblendintimeexploration`), element 1 = combat.
  `StateActiveCombat` 0x64c330 copies element 1 into its frame locals on entry (`StructType_Copy`), so the combat
  distances are that copy's `nMaxDist` +0x10, `nMinDist` +0x14, `nCollisionMinDist` +0x18 (struct field slots, 4 B
  each, at instance+4); a write to element 1 applies from the next combat entry. Exploration distance comes from the
  state manager's database items instead.
- **Movement basis** [code]: `PlayerCtrl.GetMoveStickWorld` 0x7f22e7 turns the stick into world space with the z axis
  of `PlayerCtrl._ecameractrl` (members +0x38, the CameraCtrl camera node) via `ConvertDirectionToWorldSpace`,
  flattened to the ground plane, stored in `_voldcamdirplane` (+0x90). While `_tcamchanged` (+0x8c, set by
  `command_activate_set_pos_camera` 0x7f420a) is set and the stick is held, the stored direction is reused; releasing
  the stick clears it. So movement follows whatever orientation that camera node has when the player update runs.
- **Frame order of input, character and camera** [code]: `PlayerCtrl` registers its task for manual resume at
  order 4 (`initialize_external` 0x7f4795), characters at 5 (0x6b3164), and `CameraCtrl.StateActive` 0x637f66 turns
  its own auto-resume off (`SetRunScript(false)`). The camera task is resumed only by the character it belongs to:
  `CharacterVisual.UpdateCameraCtrl` 0x67a127 resumes `PlayerCtrl.command_get_camera` (= `_ecameractrl`), called at
  the end of `UpdateAnimPoseAndCloth` 0x6b015d (sent from `CharacterRoot.StateActive` 0x6b367a after the animation
  update and after it resumes the capsule task, 0x6b9000) and from `StateRagdollDriven` 0x69ed7c. So one frame runs
  `PlayerCtrl.StateActiveDefault` 0x7f5365 (`GetMoveStickWorld`) → character update (animation, capsule, pose) →
  camera update. The stick is turned into world space with the camera orientation of the previous frame (one frame of
  lag); the camera of a frame is placed after the character has moved in it.

- `MathLib.PowerSmooth(v, power, initPower)` 0x77ab7b: `v = clamp(v, 0, 1); m = v^initPower;
  m > 0.5 ? 1 − 0.5·(2 − 2m)^power : 0.5·(2m)^power` (`fx_meta.power_smooth`; the same
  function is the page blend curve, §5). `SymmetricHalfBell` 0x597620: `0.5·(1 − cos(π·
  clamp(n, 0, 1)))` (`fx_meta.symmetric_halfbell`).
- Combat camera (`StateActiveCombat` 0x64c330, update 0x64cee1):

  | Value | Address | Type |
  |---|---|---|
  | 0.01 | 0x9e5fac | float |
  | −0.01 | 0x9fd4cc | float |
  | 0.1 / −0.1 | 0x9e9628 / 0xa22e58 | double |
  | 1.2 | 0xa46b8c | float |
  | 0.3 | 0xa00178 | double |
  | 1e-5 | 0xa54aa8 (float), 0x9fff88 (double) | — |
  | 1.5 | 0x9e5ff0 | float |
  | 0.5 | 0x9e5dc8 | double |
  | 0.8 | 0x9ea130 | double |
  | 0.3 / −0.3 | 0x9e650c / 0xa403f0 | float |
  | 0.2 | 0x9e97e8 (double), 0x9ebc18 (float) | — |
  | 0.25 | 0x9eb370 | double |
  | 1.5 | 0x9e8320 | double |
  | 1.9 | 0xa55538 | float |
  | 8.0 | 0xa06f18 | double |
  | 0.7 | 0x9e60d4 | float |
  | 0.02 | 0xa403d8 (double), 0x9e6170 (float) | — |
  | 7.0 | 0xa55530 | double |
  | 0.1 | 0x9e664c | float |
  | 3.0 | 0x9e8670 | double |
  | 5.0 | 0x9e97fc | float |
  | 2.0 | 0x9e663c | float |
  | −1.0 | 0x9e6a8c | float |
  | 0.033333 | 0xa55528 | float |
  | −0.0 | 0xa3eba4 | float |
  | −0.999 (`ProjectVector`) | 0xa75788 | double |

- Exploration camera (update 0x651b3d): fall-in speed gate 1.0 (`fld1` at 0x644609), step
  0.01 s (0x9e8460, double), stick thresholds 0.1 and 0.6 (0x9ea12c), convolution snap 0.001
  (0xaad40c), offset-X check factor 1.1 (0xa3f068).
- PvP camera (`CameraPlayerVsPlayer.UpdateCamera` 0x64748c): 0.5 (0x9e5dc8, double), margin
  and lower clamp 2.0 (0xc3cc78 double, 0x9e663c float), upper clamp 999.0 (0xa55430 double,
  0xa55428 float), −1.0 (0x9e8468, double); `hfov = radians(_nfov) · w / h` (0x643ec9);
  registered defaults fov 50, look-at height 1.4, pitch 0.45, smoothing 0.08 (0x658bce);
  `_nsmoothing` has no reader.
- Camera node (0x4a796c, 0x4a1eeb, 0x49e49c, 0x49e500): fov default 70.0 (0x9e6e50), clamp
  1..179 (0xc3cc48, 0xa00a98); near 0.05 with floor 0.05; far 1000, kept ≥ near + 1; viewport
  640 × 480. Only `fovVertical` is registered (string 0xa030a0).
- **Which FOV is on screen** [code, lifted scripts]: the node default 70 holds only until the first
  `CameraCtrl.StateActive` frame, which copies the active camera's `cameradata.nFov` through
  `SetFOVVertical` (clamp 1..179). `CharacterCamera` exploration (update 0x651b3d, the only mode with
  mouse look) blends to the state manager's `nVerticalFOV` (DEFAULT 45, COMBAT 60, ...); combat
  (0x64cee1, pad only) uses `_ndefaultfov` (55 single, 70 / 65 co-op) × the recoil / look-at FOV
  factor. The 45° vertical FOV of the apitrace frames is the DEFAULT exploration state.
- Camera tour: `TriggerActionCamera.initialize_local` 0x84b30f — action 0 needs a sequence
  child (first match, 0x849e59), actions 1 and 2 need an ancestor tour (0x84e905), action 3
  enters StateIdle directly. StateIdle 0x84bde2 starts the tour with a goto request
  (0x47a513), so the stack is `_root` > StateTour; a re-fire during the tour reaches the root
  handler 0x84b299, which in scene 30 (Tutorial) ends and restarts the tour and otherwise
  runs the base handler 0x84aea3, which fires the direct children. StateTour 0x84bed0: enable
  the sequence children, `SetRelPlayPos(0)`, Play, `command_set_camera`; the end test is
  relative position ≥ 0.99 (double at 0xa000b0); at the end the children are disabled, Stop,
  `SetRelPlayPos(1.0)`. Inferred: an action whose `_ndelay` is at or above about 0.99 ×
  duration gets its fire call only after it was disabled.

### Particles (PARTICLE_FORMAT.md, `wlib/particle_asset.py`)

- Loader `ParticleSystemAsset::vfunc_24` 0x55d3ed, writer 0x558a29, object readers 0x511f96 /
  0x511eb5, record application 0x510e5f (stops at the first record whose object id differs),
  record writer 0x5015d7.
- The emission axis is **+Y** (0x5560c1, constant 0x9e807c); `startTime` / `endTime` are
  compared with `fmod(clock, duration)` in **seconds** (0x55a722); the record's first dword is
  interpreted (object id); `particleOrientation` is at type +0xb0; `ProximityNoise` derives
  from `ParticleAffector`; `simulationMode` 2 is offered by the editor but rejected by the
  setter (0x55733e).
- `VarianceInitializer` 0x54964e; `GeometryCollisionAffector` 0x54bfab; the alignment ->
  vertex-shader mapping 0x583a62 (3 = RESTRAINCAM with 0.01 x stretchFactor, 4 =
  RESTRAINVELOCITY); the ring pool (0x55e17b / 0x55e07b: a full pool drops, capacity - 1
  usable); emitter auto-delete (emitter +0x14 = 4th argument of `CreateEmitter` 0x55d059,
  sweep 0x55c16c). RNG 0x54833c: `s = s * 0x19660d + 0x3c6ef35f`.
- Blend states by `blendMode` (0x5892c1): Normal srcAlpha / invSrcAlpha, Additive srcAlpha /
  one, Subtract srcAlpha / one subtract, Multiply dstColor / zero, Custom = `srcBlend` /
  `dstBlend` / `blendOp`. No shipped type is Custom, so the 9 non-default factor pairs are
  never applied.
- Mesh particle surfaces (`MeshParticleData`): §15 "Node collision volumes and the third list".
- Data: Part 1 uses `SurfaceSpawner`, `TerrainSurfaceSpawner` and `EventGeneratorAffector`;
  Part 2 does not. The Part 1 PC / X360 files have records without a type hash (read from
  data only).

## 13. Renderer, materials and texture sheets

Reports: `re/wp1_renderer.md`, `re/vcolor.md` (+ `vcolor_shaders.json`). Toolkit:
`wlib/materials.py`, `wlib/rig_glb.py`, `watchmen_extract`.

### Device and frame [code + measured]

- **Clears** [code]: the only `IDirect3DDevice9::Clear` call is `GfxDx9` virtual slot 19 (0x455263:
  `Clear(0, NULL, flags & 7, colour)`); Gfx singleton `[0xd91c70]`, called as `[vtbl+0x4c](colour*, flags)`. Call
  sites (all 16 found by a scan for `call [reg+0x4c]` / `[reg+0x50]` after a load of 0xd91c70):
  - Frame entry 0x563ca4: target only (1) on the target `GfxDx9` slot 23 (`[vtbl+0x5c]`) returns (0x563d34); then flags −1, i.e. target + Z +
    stencil on the default state, colour 0xc917d0 before the camera loop (0x563f11) or 0x9e80dc on the other branch
    (0x563da4).
  - Target only (1): `REBloom` 0x57bb5d, `REShadowVolume` 0x584afc (colour 1,1,1,1), `REDeferredLightLayer`
    0x5853e6 (colour 0; RT0 and RT1 bound), 0x5615db, 0x8bf4b2 (in 0x8bef92), the reflection passes 0x56d037 /
    0x56d87f (before their sky boxes).
  - Z + stencil (6): `REShadowMap` 0x5838ee (its own map), `REScaleZBuffer` 0x586cd6 (after binding its own target
    and depth surface), the ends of both reflection passes (0x56d24e, 0x56da46, after re-binding the main target),
    and slot 20.
  - Slot 20 0x455140 (`[vtbl+0x50](value)`): draws a full-screen quad that fills the bound colour target with
    `value`, then Clear(6). Called only by `REDepth` begin 0x57bbb7 (state reset to the camera default, RT0 = the
    R32F depth target, value FLT_MAX) and by the refraction pass (0x56d621).
  - State cache (flushed by `GfxDx9` slot 11 0x458794): +0x38 vertex shader, +0x3c pixel shader (0x453da3 sets this
    one), +0x4c RT0 (null → the swap-chain target at +0x518), +0x50 RT1, +0x54 depth-stencil, +0x58 viewport.
  - Order inside one camera (`DeferredRA` draw 0x56f9fb): reflection passes → stencil shadow volumes (mode 0) →
    depth pre-pass (Z + stencil clear) → lights → scaled Z → shadow volumes (mode 1) → sky boxes, terrain, wet
    surfaces, water, hard alpha, fall-off, grass, detail, soft alpha, particles, `Aux3DRA`, refractive particles,
    lens flares. After the depth pre-pass nothing in the draw clears the camera's default depth surface, and every
    other clear outside it is target only or on another surface, so the main depth is not cleared again before Present. Inferred: the default
    depth-stencil of the state stack is the main depth surface (the slot is not traced to its creation).

- **Device**: HAL with hardware vertex processing and pure device (0x50); X8R8G8B8, no MSAA;
  the ATI2 texture format is mandatory.
- **Render algorithm**: Deferred when pixel and vertex shader major ≥ 3, else Simple3D.
  Deferred always uses REDeferredMain2 (slot 2) for the model lists.
- One deferred renderer (`DeferredRA`, collect 0x575da5, draw 0x56f9fb) per camera, each pass
  wrapped in a named PERF event: depth pre-pass (R32F), scaled Z, stencil shadow volumes in
  four layers written to the four colour channels of a half-size target and blurred, material
  bloom, deferred lights into two light-layer targets, then the colour passes on the scene
  target — sky boxes, terrain, wet surfaces, water, "main hard alpha" (render list 0: opaque
  and alpha-tested), "main fall-off" (list 10), grass / detail, "main soft alpha" (list 1:
  blended, sorted), particles — and post-processing (down-scale, bloom filter,
  `PostProcessPS`: brightness, saturation, contrast, tint, gamma), HUD. Checked (measured) on
  the main menu capture and on gameplay captures of Bordello (`KapowMulti.1.trace`,
  7,643 frames) and NightClub (`KapowMulti.3.trace`, 15,887 frames). Gameplay frames add the planar
  reflection passes (`Reflection`, ` Reflection - depth`, ` - render lights`, ` - Sky boxes`,
  ` - Main`, ` - Particles`). No `Refractions` or `Shadowmap` pass ran in either.
- **Frame calls**: 0x567e25 is the depth pre-pass begin (REDepth vfunc +8, 0x57bbb7): it
  binds the R32F depth target and fills it with FLT_MAX (0xa3f114). 0x581f81 zeroes
  REParticles' nine per-frame counters (+0x78..+0x98: particles per shader set, mesh
  particles, systems drawn).
- **REDeferredTerrain** (effect slot 0x11) is drawn only in the refraction pre-pass
  (0x56d299); the main frame draws terrain with REDeferredMain2.
- **Render list 9** (Sprite) is filled and never drawn by the deferred frame. Type-9 sheets
  are drawn by Sprite nodes (vfunc +0x98, 0x4c85e8) from Aux3DRA (gated by `sprites3D`),
  Graphics2DRA and the lens-flare path, with blendType 0 → dst 6 op 1, 1 → dst 2 op 1, 2 →
  dst 2 op 3, 3 → the sheet's own triple. In PC Part 2, 21 textures have a type-9 sheet; the
  only one a model references (`Sky_SunFlare_01`, three sky models) has a type-7 first sheet
  (measured).
- **Config keys beside the `renderOption_*` keys** (read by 0x8be7e4 through the same config
  singleton 0x41ca72): `shadowmode` — `stencil` (mode 1, the default), `shadowmaps` (0),
  `none` (2); `usescaledbuffers` — half-resolution buffers, default on (key absent → 1). The
  shipped PC configuration sets neither key: the three baked configs (0xc8f178, 0xc8e328,
  0xc8e2e0; loader 0x40d7e9) and the installed `local_config.txt` hold neither, and the
  launcher holds only `screensize`, `fullscreen` and seven `renderOption_*` names (measured).
- **Shadows**: in stencil mode only Point and Spot lights draw volumes, in 4 layers (passes
  0x11–0x14), then a blur. A mesh casts iff its node's `castShadow` (PivotNode+0x12b) is set
  and its model instance has a non-empty shadow item list (0x4995c6 → tree entry bit 0 →
  0x4764d1; re-tested in 0x5748e2; that this list is the shadow hulls is inferred from its
  use); the sheet's `castShadow` (+0xa2) is not read. A light gets the shadowed light-layer
  shader when `renderShadows`, the effect's own flag, `causeShadows` (+0x135) and
  `shadowPower` (+0x154) > 0 all hold, and never for Box or Frustum (0x582db0). In shadow-map
  mode the node flag is not read: a render item of the chosen LOD (sheet type ≠ 7) joins the
  caster list when its sheet's `castShadow` is on, and the node's box widens the fitted
  bounds when any item has `castShadow` or `receiveShadow` (0x565f39); `shadowSlopeBias` /
  `shadowDepthBias` (GFXEffect+0xf8/+0xfc) feed REShadowMap (0x58380a). Sheet `shadowPower ×
  globalShadowPower` (0 when `receiveShadow` is off) is sent as PS c16.y by 0x58acbd and
  0x58a836, but no DeferredMainPS or DeferredMain2PS path reads it: only the forward MainPS
  does, which the deferred frame reaches for mesh particles (REParticles 0x58d5f3 →
  0x58c8ee). `isLit` and the material-LOD choice (0x58ab34) are reachable only from
  REAdvTerrain and REForwardGrass, which neither render algorithm draws.
- **Occlusion culling** (`renderOptions_occlusionCulling`, 0x574048): software depth buffer of
  side 128 with coarser levels 64, 32, 16; at most 128 occluders per frame (0x443292); test
  0x40e0e4: a box whose nearest view z ≤ 0 is visible; a box whose screen rectangle is off
  screen is not visible; otherwise it is hidden iff its nearest depth is not in front of the
  stored depth over its whole rectangle, walking the levels from coarsest to finest;
  undecided at the finest level means visible. The per-part proxy buffer of a model is an
  occluder mesh.
- **Post chain** (0x57e066, 0x57bae4): the global node is the first enabled, in-scene
  GFXEffect (0x4b500c); the camera's own node overrides it for the post pass only; fog, LOD,
  light fade and shadow values always use the global node. `enableFilters` gates the bloom
  filter, the grade, gamma and noise; noise also needs a noise texture and intensity > 0; DOF
  and AA are independent of it. GFXEffect defaults: edgeDetectGradient 2, edgeDetectCutoff 3,
  focalDist 2, near 15, far 70, maxFocalBlur 0.75, gamma 1, shadowMaxRange 25.
  `noiseIntensity` is registered twice on the same getter and setter (0x4c0af2:
  "noiseIntensity" and a misspelt "noiseIntensisty"); the level nodes store both keys with
  the same value. `watchmen grademeta` lists the post-process settings of a level's GFXEffect
  nodes; the script blends several at run time.
- **Grade adjustment** (FXGfxEffectCtrl: MapValueCenter 0x73504c, InitializePlatform 0x735084,
  contrast 0x73c139, brightness 0x73c1e5, gamma 0x73c28f, saturation 0x73c33a):

      m(v, c)    = v > 0.5 ? c + 2(1 − c)(v − 0.5) : 2·c·v     v = option 0..1
      contrast   = node + (m − 0.5) · 1.1     (0xa3f068)
      brightness = node + (m − 0.5) · 0.5     (0x9e5dc8)
      gamma      = node + (m − 0.5) · 1.2     (0x9ecf08)
      saturation = max(node + (m − 0.5) · 1.5, −1)   (0x9e8320, 0x9e8468)
      centres (gamma, brightness, contrast, saturation):
        PC 0.6 0.6 0.6 0.5 · X360 0.5 0.7 0.6 0.5 · PS3 0.4 0.4 0.2 0.5 · other 0.5 each

  On PC at v = 0.5: +0.12 gamma, +0.05 brightness, +0.11 contrast. The four options start at
  0.5 (`SettingsState` properties `m_nbrigtness` [sic], `m_ncontrast`, `m_ngamma`,
  `m_nsaturation`, default "0.500000"; `command_set_default_settings` 0x82be66 stores the
  float at 0x9e6174), so a fresh PC profile adds exactly these offsets. With the same default
  the console centres give X360 +0 / +0.10 / +0.11 and PS3 −0.12 / −0.05 / −0.33 (gamma /
  brightness / contrast); the console executables were not read. A saved profile replaces
  the values. `materials.PLATFORM_ADJUSTMENT` carries them as `option_default` and
  `default_offsets` (`grademeta`).

### Lighting equation [bytecode + code]

`DeferredMain2PS` lights every opaque and alpha-tested surface (REHair, REMain and REGlass
are not reached). The sheet chooses the render list by `renderType` and the "extra" shader
variant when it has a real glow or specSize layer, `selfIlluminance` ≠ 0 or `twoSided`
(0x571d5d, 0x56bcb8). Per light, on display-encoded values with no sRGB conversion:

    n        = specularSize                       (× (specSize.g² · 256 + 1) in the extra variant)
    specular = specularPower · NH / (n − n·NH + NH) · NL
    glow     = selfIlluminanceColor · selfIlluminance · glow layer
    colour   = albedo · (ambient + lights + glow) + specular layer · (specular lights + glow)

Cube reflection (`reflectionType` 2) is a lerp toward the cube by specular layer ·
`reflectionLightFactor`, not saturated. `renderType` 10 adds gradient(sat(N·V)) ·
`fallOffPower` · (ambient + directional + positional diffuse + positional specular +
`fallOffColor`), after the vertex-colour multiply and before fog. In the extra variant the
glow term is inside both light sums, and the fall-off factor is 0 where `vFace` ≥ 0 (the back
side of a two-sided sheet; which sign is the front is inferred). The directional light gives
no highlight in any of the eight main-pass variants. (Read from the shader text of
`CreatePixelShader` calls 1036 and 1029 in `KapowMulti.1.trace`.) The gradient is the sheet's
`depthFadeGradient` string `pos,r,g,b,a|…` baked to a texture at load (0x525650, 0x524565;
parser 0x413360, keys at int(pos · 1000), clamped ends, linear between, white when empty).
Missing layers: specular white, glow white, specSize black; the specSize channel read is G.
Hair is alpha-tested (reference 95 / 255), not blended. Sheet offsets: `specularPower` +0x8c,
`specularSize` +0x90, `writeDepthBuffer` +0xa1, `twoSided` +0xa4. The constants z = 250 and
w = 2 pushed with every material are read only by the low-quality variant, as a scale and
bias; they are not rim or Fresnel terms. The hashes 0xf4142d28 / 0xb3ab3306 (`$specularData`)
are the sheet properties `specularSize` / `specularPower` of the selected sheet, not per
texture.

- **Gradient texture**: 128×1 A8R8G8B8, bytes B,G,R,A, each channel int(value · 255)
  truncated, alpha stored inverted (key alpha 1.0 → 0); only for type 10 or water with depth
  fade. Created white with alpha 0 and rewritten when the sheet's gradient is set. Of three
  texel mappings tested, position = i / 127 fits the capture best (measured: 48 draws, max
  difference 2.2 of 255). **UV scroll** uses scaled scene time.
- **Pixel shader constants**: c2 = (specularSize, specularPower, 250, 2); c11 =
  (normalMapPower or 0, selfIlluminanceColor · selfIlluminance); c12 = (reflectionLightFactor,
  reflectionBumpPower); c14 = (fallOffColor, fallOffPower). c16 `$factors` = (normalMapPower
  when `enableNormalMapping`, else 0; sheet shadowPower × globalShadowPower); c17/c18
  `$effectAttenuation` from sheet+0x218 (only .y read: a scale and bias fading the normal-map
  power); c28/c29 `$uvChannelSelector` from sheet+0x238 (UV_CHANNEL_SELECTION variants); c13
  `$wetSurfaceConstants` = (1/waterTileScale, waterMaxDisplacement [read by no shader],
  fresnelPower, maxReflection), with s4 = the sheet's height layer and s5 = the
  water-simulation normal map (0x56debe). Confirmed on gameplay captures (measured): 63
  skinned draws of a Dominatrix (3 frames) and a Heavy (3 frames) equal `sheet.json` to
  float32 on every register the bound shader reads. Registers a variant does not read keep
  stale values (c12 on non-cube variants, c14 on non-falloff ones). The full fall-off cube
  variant reads c12.x only; `reflectionBumpPower` (c12.y) is not read by it.
- **Reflection**: effective type per 0x529e14; the cube is the nearest of the CubeMapNodes
  that are candidates in that frame. `FUN_004d5ca9` (from `MasterRA::vfunc_01` 0x561521)
  rebuilds the candidate list every frame from all cube nodes, keeping a node only if byte
  +0x54 ≠ 0, bit 0 of +0x40 is set and byte +0x55 ≠ 0 on the node and on all its parents
  (0x48e028); position = node+0x88. `FUN_004d1299` takes the smallest squared distance to the
  object's world translation, or null when there is no candidate. +0x55 is the node property
  `visible`; +0x54 and bit 0 of +0x40 together are `Node::IsEnabled` (0x481762), the getter
  of `globalEnabled`; that bit 0 of +0x40 is the enabled state of the parents is inferred.
  The run-time switch is `CullingCtrl`: `Culling` 0x70e0a4 runs a sphere overlap (radius 1.0,
  mask 0x10) at the camera position, `InsideFilter` 0x70dfa8 / `InsideTest` 0x7111b9,
  `GetCullingGroups` 0x705410, `CullUncullSplit` 0x7052b9 and `ApplyCulling` 0x70e06e →
  0x7054b8, which calls `Node::SetVisible` 0x48f69a with 0 on the culled and 1 on the shown
  `CullingVisibilityGroup` nodes (native `PVSRootNode`), so a cube node below a hidden group
  is no candidate. `StateMain` 0x705138 sends `command_viewport_render_begin` once per frame:
  viewport 0 in game modes 1 and 4, viewport 1 in mode 2, not in mode 3; the position is that
  of `CameraLib.GetCamera(0)` in every mode but 3 (0x704d7f). The controller is also a
  viewport-render listener (0x70db16); whether that listener fires in modes 1 and 2 is not
  established. `Culling` returns at once when the controller's own +0x54 is 0 or bit 0 of
  +0x40 is clear. Any other switch of the flags at run time is not established. A sheet whose
  reflection type is not cube gets a NULL cube and c12.x = 0 even when its shader variant has
  the cube sampler; a shader without the cube sampler leaves stage 3 as the last draw set it.
  Measured on three D3D9 captures (Bordello, NightClub), counting the draws whose pixel
  shader declares `dcl_cube s3`: the nearest candidate under the culling rule is the bound
  cube in 4,041 of 4,041 draws of 87 frames (file state alone: 3,254) and in 659 of 659 draws
  of 18 other frames (nearest of all nodes of the level file: 586 — Bordello 328 of 328,
  NightClub 258 of 331); in the seven frames with the camera in two groups only the union of
  their lists fits (312 of 312; intersection 250). The terrain looks up its cube only while
  its own weak handle is empty and then keeps it (0x537194, 0x537296, 0x538a8e; when the
  handle is emptied was not read). `levelmeta` applies the rule to the state of the file
  (`cube_maps[].candidate_at_load`, `models[].cube_map`) and per culling group
  (`culling.groups[].cube_maps`, `models[].cube_map_by_area`; LEVEL_META.md).
- **CullingBox** (`CullingCtrl.InsideTest` 0x7111b9): inside iff |local|·2 ≤ (width, height,
  depth); depth from MockupBox+0x1a0, CollisionBoxNode *(+0x198)+0x2c or Light+0x174, and
  unbounded for any other class. `CullingCtrl.Culling` 0x70e0a4 collects boxes with a physics
  overlap sphere of radius 1.0 and mask 0x10 at the test position. `levelmeta` lists the boxes
  under `culling`.

Toolkit (`wlib/materials.py`, `--materials engine`): roughness (2 / (n + 2))^0.25, F0 = 4 · (2
/ (n + 2)) · peak through `KHR_materials_specular` / `KHR_materials_ior`, a display-space
correction of both (the 0.6 lit level in it is the test scene's, not an engine value),
emission, alpha mode from the render list. Where F0 is 0 (no highlight in the game) the
roughness written is 1.0 without a texture: the lobe's width has no meaning there, and a
viewer that ignores `KHR_materials_specular` would otherwise show a highlight the game does
not have. Measured against a reference implementation of the equation: 3 to 17 % lower mean
error than the legacy materials on skin, clothing, latex and hair in three.js and Blender;
not on every light direction; lace and ring of the Dominatrix suit slightly worse. The rim
term and display-space lighting dominate what is left and cannot be expressed in glTF.
Specular and glow are tinted by the vertex colour in the game but not in glTF. The legacy
bake `roughnessGen.png` took the specSize layer for a matte map (roughness rising with
specSize) and used sqrt(2 / (n + 2)), which is the GGX alpha, not glTF roughness; a larger
specSize is a larger exponent, a narrower and — the lobe is not normalised — smaller
highlight: lower roughness together with lower specular strength.

### Render lists, alpha and blend states [code + data]

- `0x582eb6` (callers 0x58a836, 0x58acbd, 0x571d5d) sets the blend state from the sheet
  (blendType +0x154, srcBlend +0x158, dstBlend +0x15c, blendOp +0x160), then the cull mode
  from `twoSided`. The editor shows `blendType` only for render types 1, 7 and 9 (mask 0x282
  in 0x525d0e), and no sheet in the corpus sets it on another one; the draw path also applies
  it to a type 0 / 10 sheet with opacity < 0.99 (one Part 2 sheet is of that kind,
  `Sewer_Dirt_02`, blendType 0).

  | blendType | SRCBLEND / DESTBLEND, BLENDOP | result |
  |---|---|---|
  | 0 standard | SRCALPHA / INVSRCALPHA, ADD | alpha blend |
  | 1 add | SRCALPHA / ONE, ADD | dst + src·a |
  | 2 subtract | SRCALPHA / ONE, REVSUBTRACT | dst − src·a |
  | 3 manual | the sheet's three values | D3DBLEND 1…11, D3DBLENDOP add 1, subtract 2, revSubtract 3, max 4, min 5 |

  The sky box path (0x589dd9) uses ONE / ONE ADD for `add` and ONE / ONE SUBTRACT for
  `subtract`. Data: first sheets with a non-standard blend are used by 11 models — add: 4 sky /
  flare models, Disco_Ball_01, PickupTruck_OnFire, Sedan_BurnedOut; manual: `Sky_stars_01`
  (SRCALPHA / DESTALPHA) and `Sky_SunRay_01` (SRCALPHA / ONE) on sky boxes; subtract:
  Rorschach and Rorschach_Dry (two inkblot textures with `blendType` 2 and `renderType` 1:
  white blots on black, subtracted from the mask under them).
- **Render list and alpha** (0x5739d0, 0x57552b, 0x571d5d, 0x429e77). The list is the
  sheet's renderType; a type 0 or 10 item whose alpha (sheet opacity × item opacity × LOD
  weight) is below 0.99 (double at 0xa000b0) goes to list 1 and is drawn with the sheet's own
  blendType. Lists 2, 6 and 9 are not drawn by 0x56f9fb. The opaque lists are drawn with
  blending off (blending is enabled only by passes 3, 4, 7 and 0x1a). The alpha test is
  enabled from bit 0 of the layer-0 texture buffer's flags, which the loader copies from the
  header's `u8 hasAlpha`; pixels are not inspected; the capture shows `D3DRS_ALPHAREF 95`.
  Cull is none when twoSided; blend triple by blendType 0–3 (≥ 4 leaves the state
  unchanged); depth mode 0 or 2 by writeDepthBuffer.
- **Culling** (code + capture): the render-state cache keeps the cull mode in bits 4–7 of
  state+0xB8 (`FUN_0042aa66`); `FUN_00571d5d` sets `D3DCULL_NONE` when the texture sheet's
  two-sided byte (sheet+0xA4) is set, otherwise the value on the state stack. Model draws in
  the capture use `D3DCULL_CW` or `D3DCULL_NONE`; `D3DCULL_CCW` occurs only for light volumes.
  So the front face is the side the stored normal is on (inferred from the cull state and the
  measured winding, not from a traced projection matrix).
- **Sky pass and opacity**: the deferred frame draws render list 7 in the pass `Sky boxes`
  (0x56f9fb: effect slot 0x5c, the list at +0xd0) through RESkyBox vfunc 4 (0x58bc85), one
  call of 0x589dd9 per item. 0x589dd9 sets pixel-shader constant 0 to (0, 0, 0, sheet+0x98)
  with 0x42ab39 (0x589e5e `fld [esi+0x98]`, call at 0x589e6a; device vtable +0x1b4,
  SetPixelShaderConstantF); sheet+0x98 is the opacity 0x5739d0 multiplies into the item alpha
  (0x573db2). The item alpha itself (node opacity × LOD fade) is not read by this pass.
  `SkyBoxPS` (4 instructions, bytecode): `texld r0, v1, s0`; `mul r0, r0, v0`; `mul oC0.w,
  r0.w, c0.w`; `mov oC0.xyz, r0` — alpha = texture alpha × vertex alpha × opacity. Blend
  factors by blendType: 0 → SRCALPHA / INVSRCALPHA (0x42aa07(5, 6)), 1 and 2 → ONE / ONE, 3 →
  the sheet's triple. The pass begin (0x58469d) sets bit 8 of the render-state word next to
  the blend factors (0x42a9d0(1)); that this bit is the blend enable is inferred from its
  place, not traced to SetRenderState. Alpha test is on only when the material flag bit 0 is
  set (reference sheet+0xa0). So a type-7 sheet with the standard blend type and opacity 0
  adds nothing to the frame: `skyflash` and `moon_01` of Part 1 (opacity 0.0, blendType 0,
  no texture alpha). Not established: whether a script or effect (`FXLightningLightUpSky`, UI
  string "Sky Flash Model" at 0xa6fc10) changes the sheet or swaps the model at run time. The
  node's own `opacity` (BaseModel node+0x1b8, clamped 0..1, copied to item+0x18 by 0x5835f8)
  multiplies the sheet's; it is exported per placement (`levelmeta` `models[].opacity`) and
  not multiplied into the model files.
- **Header flag against pixel alpha**: Part 2 PC 931 of 937 agree (6 flagged but fully
  opaque); Part 2 X360 905 of 908 (one unflagged DXT1 with alpha pixels, `ArrowMore.bmp`);
  Part 1 PC 1,144 of 1,152 (8 flagged but opaque). The byte is at the same place in the X360
  header: equal on all 908 shared textures. PS3: not checked. The 20 `hasAlpha` buffers on
  `renderType` 0 sheets (`Sewer_Dirt_02`, two terrain textures) blend only through the
  opacity rule above.
- **Toolkit rule** (engine materials): BLEND iff renderType == 1, or opacity < 0.99 on a type
  0 / 10 sheet (the only types 0x5739d0 moves to list 1 for their alpha) or on a sky-box (7)
  sheet (exported as base-colour alpha); else MASK when the header flag is set; else opaque.
  The MTL writes that opacity as `d`. Vertex alpha gives BLEND on sky box (7) and sprite (9)
  sheets and on materials without a known sheet; with engine materials vertex alpha does not
  select BLEND. `rig_glb.material_alpha` for `extract --glb`: `doubleSided` = `twoSided`
  (true without a `sheet.json`); cutoff `alphaThreshold` / 255 (95 → 0.372549), 0.5 when the
  sheet has no threshold, and no alpha mode at all when the threshold is 0; normal texture
  `scale` = `normalMapPower` when it is not 1, and no normal texture when
  `enableNormalMapping` is false. The legacy character writer (`variant_glb.buffer_vertex_attrs`:
  PC format 5 / 6 render buffer with the same offset, vertex count and stride, else nothing)
  keeps `doubleSided` true, does not make a character material BLEND on `renderType` 1, and
  gives a part whose vertex alpha varies a BLEND copy of its material.
- No per-material rule sends a model to `REDeferredMain2`: the `DeferredRA` constructor 0x574f74 sets +0x3c4
  to 1 and calls the toggle 0x567dce once (0x575041), which flips it to 0 and stores {2, 2, 2, 2}; the toggle
  has no other caller and no data reference, so the main, wet, terrain and fall-off model lists always use
  REDeferredMain2 (read from code). Not established: console shader microcode (FORMATS_MISC.md).

### Vertex colour (`re/vcolor.md`)

Shader archive: 243 shaders (95 vertex shaders, 73 of which declare `COLOR0`), all
disassembled; 240 of the 242 shaders the game creates in the capture match an archive entry
by opcode sequence. The integer in a shader's file name is the hash of its compile key
(`FUN_0042a25c`: name, profile, each `#define` in alphabetical order, through the engine CRC
`FUN_00423d7c`); reproducing it names the define set of 224 of 243; 19 define sets are not
established. Three of the unnamed entries (`MainVS-1480351135`, `MainVS901430857`,
`SimpleLightVS1431484195`) are requested by no PC compile site (every "MainVS" and
"SimpleLightVS" call site read); they are the TERRAIN variants with the vertex colour
replaced by (1, 1 − v.w, 1 − v.w) of a texcoord.

- What it is (bytecode). `DeferredMain2VS` with `VERTEX_COLORS` passes TEXCOORD0 = (r, g, b,
  a · `$alphaFactor`) (`mul o1.w, c11.x, COL.w` / `mov o1.xyz, COL`); without the define the
  shader does not declare `COLOR0` and passes (1, 1, 1, `$alphaFactor`). `DeferredMain2PS`
  ends with `mul oC0.w, r2.w, v0.w` (output alpha = diffuse alpha × vertex alpha) and `mul
  r1.xyz, r0, v0` (the complete lit colour — diffuse lighting, specular, glow, reflections —
  × vertex rgb), fog after. All 16 `DeferredMain2PS` variants and the lit `MainPS` /
  `DeferredMainPS`, `MainVertexLightPS`, `SimpleLightPS` and `HairPS` have this structure.
  No shader uses a model's `COLOR0` as ambient occlusion on ambient only, as a layer weight,
  as a sway weight or as a specular mask. The depth and shadow passes do not declare it, so
  vertex alpha does not affect depth or shadows.
- When it is used (code + capture). Per draw item `FUN_0056bc16` calls
  `FUN_00569734(skinned, hasColor)` with `hasColor = *(u8*)(MeshBuffer + 0x31)`, the first of the
  two flag bytes of the file's MeshBuffer header (`FUN_004336ec`); +0x32 is `hasAlpha`.
  `REDeferredMain2` (`FUN_00570d06`, vtable 0xA3E81C) holds 12 vertex shaders, { –, `SKIN`,
  `TERRAIN` } × { –, `VERTEX_COLORS` } × { –, `TANGENTSPACE` }. In the capture every model
  colour-pass draw uses `DeferredMain2VS`: 5,524 format-5 and 1,620 format-6 draws with
  `VERTEX_COLORS`, 8,120 and 2,916 without. No reader of `hasAlpha` was found in the render path (by
  search, not exhaustive).
- The flags (code + data). The mesh builder (0x434341–0x43469d) clears `hasColor` when the
  minimum of all colour components is 1.0 and `hasAlpha` when the minimum alpha is 1.0;
  `hasAlpha` forces `hasColor`. On the files, `hasColor` equals "has a non-white vertex" on
  2,657 of 2,657 format 5 / 6 buffers: 1,204 with neither flag (every byte 255), 1,400 with
  colour only, 53 with varying alpha (21 of those with rgb all white).
- Census (data): 387 of 735 models, 1,453 buffers, 1,289,427 vertices; 39 models under
  `art/characters` and `Animation`. No palm, fern or tree buffer has colours. Mean factor
  0.84 (mean R, G, B 214 / 215 / 216); 51 % of coloured vertices exactly white, 85 % grey (r
  = g = b); 99.7 % have alpha 255. The 53 alpha buffers are decals, puddles, wine stains, sky
  layers, disco-ball glints, garbage piles and Rorschach's `layer03` / `layer04`; their alpha
  fades to zero at the border. What produced the values (bake or paint) is not established.
- Colour space (capture): the trace contains no `SRGBTEXTURE` or `SRGBWRITEENABLE` call, so
  the multiply acts on display-encoded values.
- Toolkit: COLOR_0 only for buffers with `hasColor`; VEC4 float, rgb sRGB → linear (the
  engine multiplies display-encoded colour, glTF linear base colour), alpha as stored
  (`rig_glb.linear_vertex_colors`).

### Tangent frame, culling and winding (`re/vcolor.md`)

- Vertex shader (bytecode): rigid `TANGENTSPACE` passes normal, tangent (TEXCOORD1) and
  bitangent (TEXCOORD2) raw; skinned transforms each by the blended bone matrix and
  normalises it on its own. No cross product.
- Pixel shader (bytecode): `x, y = 2·tex − 254/255`, both × `$effectFactors.x` (the sheet's
  `normalMapPower`), `z = sqrt(1 − x² − y²)`, `N′ = normalize(x·T + y·B + z·N)` with the
  STORED tangent and bitangent (`mul r1.xyz, r0.y, v5` / `mad r1.xyz, r0.x, v4, r1`). No
  handedness sign, no orthogonalisation. `TWO_SIDED` variants negate the normal by `vFace`.
- Stored data (1.80 M format 5 / 6 vertices, 1.40 M triangles of Part 2 PC): tangent and
  bitangent are unit length; the tangent agrees with the geometric ∂P/∂u and the bitangent
  with +∂P/∂v on 97.5 % of triangles; `s = sign(dot(cross(N, T), B))` is + on 66.5 % and − on
  33.0 % of vertices (mirrored UV islands); |N·T| > 0.1 on 9.5 % (a 244,791-triangle sample
  gave 29 %; the two figures have not been reconciled; median |n.t| 0.035), |T·B| > 0.1 on
  13.9 %, B more than 10° from ±cross(N, T) on 15.5 %; 99.85 % of triangles wind clockwise
  against their normals (the counter-clockwise face normal agrees with the vertex normals on
  0.16 % of the sample).
- What this means for the export (impl): the engine's space is left-handed. "Clockwise
  against the normal" is a statement about the numbers read right-handed, i.e. about the
  mirrored frame (`--frame mirrored`, the layout of releases before 1.4.0), where the writers
  reverse the winding of a primitive that carries normals. In the default true frame (x =
  −engine x) the reflection reverses the sense of every triangle, so the FILE order is
  counter-clockwise seen from the normal side — glTF's front face — and is written as it is.
  TANGENT there has x negated and w negated: glTF's bitangent is cross(N, T)·w, and cross(S n,
  S t) = −S cross(n, t) for the reflection S, while the stored bitangent reflects as a vector.
  Checked on three real sign models and two full character exports: the counter-clockwise
  triangle normal lies on the side of the vertex normals in the same number of triangles in
  both frames (56 of 56, 184 of 184, 13,476 of 13,484, 11,398 of 11,410), and the true-frame
  indices of the signs equal the file's. That Kynapse's navigation space is the engine's with
  x negated (bridge 0x48110f, NAV_DATA.md) fits the same picture.
- Toolkit: NORMAL as stored; a primitive that gets NORMAL has its triangles reversed when they
  wind against it. TANGENT = stored tangent, `w = −s` (`watchmen_extract.gltf_tangents`,
  `green_up=False` gives +s), written only for a material with a normal map; the embedded
  normal texture has green inverted. A GLB without NORMAL is shaded flat by glTF consumers;
  no model GLB of the six-set export lacks NORMAL (§15).

### PC `ATI2` normal maps store Y first [data + bytecode + render test]

Direct3D 9 `ATI2` keeps the Y block first and the X block second. `watchmen_extract.ati2_xy`:
PC enum 9 decodes X from the second block, Y from the first, on the exact carve and on the
legacy carve. The per-platform format table at 0x009E8F78 gives the format (normal maps PC 9
-> X360 10 -> PS3 7), not the channel order: the X360 (enum 10) and PS3 (DXT5) layers are
X-first. Evidence:

- bytecode: sampler `.x` goes with the tangent, `.y` with the bitangent (instructions above).
- mixed partials on the art: a tangent-space normal of a height field satisfies ∂x/∂v =
  ∂y/∂u. On 59 PC character normal PNGs decoded first-block-to-red the pair correlates 0.17 in
  the median and the swapped pair 0.57 (57 of 59 files favour "swapped"); on 57 Part 1 PC
  files 0.13 against 0.85 (57 of 57); on the X360 and PS3 copies of the same maps 0.78 against
  0.15 (59 of 59 the other way). The sign is positive in 230 of 234 files: Y points along +v,
  the stored bitangent. One texture (`Generator_01`, correlation −0.92) has the opposite
  green sign; it is left as authored.
- renders against a numpy rasteriser with the pixel shader's math, in three.js r160 and
  Blender 5.0.1 (Cycles), median angle between the consumer's shading normal and the
  reference, three.js / Blender, swapped decode against the correct one:

      model                  swapped PNG, no NORMAL   character GLB   extract --glb
      Fimale_GimpSuit_01     14.4° / 17.0°            1.1° / 1.4°     1.1° / 1.4°
      NightOwl_No_Mask       12.2° / 13.9°            1.1° / 1.0°     1.4° / 1.2°
      Generator_HoneyPot     (no GLB)                 —               0.9° / 0.4°

  With the correct PNG and green inverted for glTF, TANGENT `w = −s` gives 1.1° / 1.1° / 0.9°
  in three.js and `w = +s` 17.0° / 8.2° / 2.2°. With the swapped PNG no choice of `w` or of
  the green flip comes below 10° on the two characters. Blender's importer ignores TANGENT
  and builds its own from the UVs, so there only the texture decides. The remaining degree is
  texture filtering and the non-orthogonal stored bitangent, which glTF cannot carry. No real
  game frame was used as reference.

### How a model's textures are resolved [code + data]

- `ModelRes::Read` 0x547006: the header holds `u32 nTex { bool flag; string path }`; the
  string is a full asset path (`/art/characters/bikers/textures/head.bmp`). Each goes through
  0x49ebc2 → 0x49b2b2 → the AssetManager lookup 0x55243f by that path. The submesh record
  0x542541 indexes this list. No bare-name lookup exists; a texture is never looked up by
  material name.
- Data: 120 character model headers, 247 references, all full paths; 245 exist in the
  texture tree (the two missing are `…/baseballbat/texture/Nail.bmp`). Twelve bare names
  occur in more than one folder of Part 2 (`head`, `head02`, `EnemyEye`, `skinarms`,
  `Biker_DenimVest1`, `Head_Beard`, `KnotTop_LargeHeadF`, `Teeth`, `EyeBlow`, `WomanMouth`,
  `white`, and `gray`, which only the full extract shows and only helper models use); 30
  texture folders end in upper-case `.BMP`; two have a blank before the dot
  (`rorschachspots01 .bmp`, `RorschachSpots02 .bmp`). Letter case: §15 "Asset names".

### Texture sheets [code + data]

- A Texture asset holds one or more `TextureSheet` objects. Each has a `name`, a 64-bit
  `uniqueID` and, besides the material switches, eight path properties: `diffuseMapOverride`,
  `normalMapOverride`, `specularMapOverride`, `specSizeMapOverride`, `glowMapOverride`,
  `heightMapOverride`, `fallOffMapOverride`, `ambOccMapOverride` (names from the executable's
  strings; hashes matched in the headers). In the header a property record is `[salt
  u32][key hash u32][type hash u32][payload dwords u32][payload]` (20-byte records; both
  hashes the engine name hash of the strings), the salt the same for all records of one
  sheet; a string payload is `[dwords u32][bytes]`, a `uniqueID` payload is the id's high
  dword then its low dword (data).
- Material switches, from the registration strings of texturesheet.cpp (0xA2F7A7 onward):
  `renderType` (integer), `isLit`, `writeDepthBuffer`, `twoSided`, `enableNormalMapping`
  (truth), `alphaThreshold`, `blendType` (integer), `opacity`, `normalMapPower` (number).
  `renderType` values: 0 Standard, 1 Standard with blending, 2 glass, 3 water, 6 hair, 7
  skybox, 9 sprite, 10 falloff, 11 wet (editor string `items=Standard:0,Standard with
  blending:1,Glass:2,Water:3,Hair:6,SkyBox:7,Sprite:9,Falloff:10,Wet surface:11`);
  `blendType` from `items=standard:0,add:1,subtract:2,manual:3|caption=blend type`.
  `twoSided` is the byte at sheet+0xA4. `alphaThreshold` is the alpha-test reference, 0..255.
  `watchmen_extract.texture_sheet` reads the first sheet of a header; the further sheets are
  named alternatives, not defaults; texture extraction writes the result as `sheet.json`
  beside the PNGs (with `stored_name` and `overrides`).
- Animated sheets [code]: constructor 0x525964 (`enableAnim` +0xa7 = 0, `animDelayInMs` +0xa8 with +0xac =
  ms / 1000, frame +0x6c = 0, frame player +0x68 = null). The per-frame sheet update 0x5231de first counts +0xac
  down by the script clock (0xe14304); once it is ≤ 0 and a frame player exists, +0x6c = the player's current frame
  (0x52fb0d: time accumulates, and while it exceeds the frame's duration the player steps on, 0x52c75e, reading the
  next frame index 0x52929b and duration 0x5292bb). The same update scrolls four UV offsets (+0x128..+0x134). Every
  layer getter (0x49c838 → 0x49be2d) uses +0x6c as the index into the texture's frame table, so an override
  texture is drawn at the same frame as its sheet.
- Sheet lookup: a collection node selects sheets through `textureSheetsDescription`
  (`BaseModel::Get/SetTextureSheetsDescription` 0x49f95e / 0x49d26c; setter dispatcher
  0x4a6ed7; the getter writes `%d,%d,%d,%s,%s,`): the first token is a version. Version 1 →
  0x4a544a, records `slot,pivot,<texture path>,<sheet id>`; version 2 → 0x4a56c2, records
  `slot,pivot,lod,<texture path>,<sheet id>` (the stored string is `2,` followed by records
  `modelSlot,pivot,lod,<texture path>,<sheet id>,`). Per record: slot, pivot and LOD are
  bounds-checked; every mesh of that slot / pivot / LOD whose own texture path equals the
  record's (0x53bc74, string compare; the branch returns the mesh's Texture object) gets
  `0x524caf(texture, id64)`: a linear search of the texture's sheet array for the 64-bit
  uniqueID (+0x48 / +0x4c). Not found → the FIRST sheet. A later matching record overwrites an
  earlier one. No record → first sheet. There is no default flag and no name hash. Data: 2,996
  records in 390 fragments; 2,411 name the first sheet, 330 another one, 147 an id the texture
  does not have (→ first), 108 a texture not in the corpus. All enemy records are pivot 0,
  LOD 0. Sheets per texture (936 textures): 1: 769, 2: 123, 3: 24, 4: 14, 5: 2, 6: 1, 8: 3.
  The deprecated property `textureSheets` (the fragment JSON's `texture_table`) is registered
  beside it with the message "Texture sheet string has been updated, use
  texturesheetsdescription instead". The sheet a submesh uses is the one the placing
  fragment's `textureSheetsDescription` names per model slot, else the first; the export gives
  every part the sheet its outfit node selects.
- Data, end to end: `bikers/textures/head.bmp` has the sheets `default` (uniqueID
  0x47b2ba3e66d9986d) and `Goatee` (0x47bed84ecd7a1a32); Goatee's `diffuseMapOverride` is
  `/art/characters/bikers/textures/head02.bmp`. In `ThugFace` the node of type 13
  (LARGE_HEAD_GOATEE) names `…/bikers/textures/head.bmp,5169807255234288178` = the Goatee id,
  the node of type 0 (LARGE_HEAD_1) names the default id, both for `Large_Head_1.model`. So
  the large thug's rigged head is `Large_Head_1` wearing `head02`'s diffuse on `head`'s other
  layers. `knottops/textures/head02.bmp` has the sheets `default` and `NoBear`, without
  overrides. Diffuse-only texture folders such as `Heavy_Outfit2..4`, `Biker_DenimVest2/3`
  and `Heavy_ButtonBlue` are override targets of other textures' sheets.
- How a sheet's layers reach the renderer: a sheet holds a resource handle per layer
  override: +0x190 diffuse, +0x19c normal, +0x1a8 specular, +0x1b4 glow, +0x1c0 height,
  +0x1cc fallOff, +0x1d8 ambOcc, +0x1e4 specSize (setters 0x524749, 0x52479d, 0x5247f1,
  0x524845, 0x524899, 0x5248ed, 0x524941, 0x524995; a sheet may not name its own texture,
  0x5243d3). Its own texture is at +0x64. `0x4991f0(sheet, layer)` returns the override handle
  of that layer when it is set, else the sheet's own texture (layer index 0 and 1 diffuse, 2
  normal, 3 height, 4 specular, 5 glow, 6 fallOff, 7 ambOcc, 8 specSize). `0x49c838(sheet, layer)`
  calls it and then asks THAT texture for the same layer (0x49be2d). The material
  binds call 0x49c838 per sampler: 0x58a849 … 0x58a923, 0x58acd0 …, REDeferredMain2 0x571da8
  …, the sky box 0x589d35 …. So an override replaces one layer with the same layer of another
  texture, on whichever sheet the mesh wears — the first included. Data: 43 textures have
  overrides; 3 on their first sheet (`KnotTop_TShirt` → `KnotTop_TShirtBeige`, `SkinTorso` →
  `KnotTop_SmallTorsoSkin`, `denim` → `DenimB2`).
- Engine layer → file slot: 0, 1 → 0; 2 → 1; 3 → 4; 4 → 2; 5 → 3; 6 → 5; 7 → 6; 8 → 7
  (0x49be2d, getters 0x49bcbe…0x49bdff; loader 0x5382aa stores the slots in file order). So
  the shader's "extra" input is slot 3 (glow) or slot 7 (specSize), and file slot 4 is the
  height map (KAPOW_NAZ_FORMAT.md §4.2).
- Animated sheets (0x5231de): scroll offset i grows by `fmod(speed_i × game step, 1.0)` per
  frame and is not wrapped (speeds at sheet +0x114..+0x120, offsets at +0x128..+0x134). A
  start delay at +0xac counts down by `timepassed`; once it is ≤ 0 the flipbook timer
  (0x52fb0d) adds `timepassed` and steps a frame each time it exceeds the frame duration.
- Run-time sheet changes (block flash and the override-model path at call-site level only):
  MaterialSheet registry: dead. Runs: block flash, event 84 (`SetTextureSheetData` 0x677be0
  copies the sheets of `_emodelntoflashing`; copied back at the next state start). Runs:
  `WeaponBase.SetSheetFromModel` 0x8b38c3 from `StateDetach` 0x8b4780 (durability 0 → ref;
  game mode 1 → glowing; mode 2 → ref), `StateAttach` 0x8b53e0 (ref) and
  `command_viewport_render_begin` 0x8b3578 (owned → ref; not owned in game mode 3 → viewport 0
  glowing, viewport 1 ref). Runs: sequence tracks on sheet properties. The Rage sheets are
  animated by an auto-started sequence but only the disabled Rorschach_Rage model uses them
  (never shown: `LevelSceneCtrl._emodelrshrage` is returned only by `command_get_rage_model`
  0x69ed29, whose hash 0x0599741a occurs once in the image, at its registration (measured);
  the node is disabled in the five Part 2 play levels (measured)). Not traced:
  `AiSheetChanger`, `CloneSheet_Prototype`, the bodies of `SetTextureSheetData` and
  `SetSheetFromModel`, whether weapons receive `viewport_render_begin`. Wet / dry
  (NiteOwl_Dry, Rorschach_Dry) are separate models, not sheets. Nothing was found that swaps
  sheets by damage.

### Light node [code; constants from exe bytes]

- Constructor 0x4a3d8e: type 1; range 25.0 (0x9f8094); `attnStart` 0.75 (0xa01020);
  brightness 1.0; shadow power 1.0; cones 45 / 55 (0x9fffa8 / 0xa0101c); texture offsets
  −0.5, scales 0.5.
- Type 5 is stored as 2 with `textured` set (0x4a1c4a). Range floor 0.2 (0x9ebc18). The outer
  cone setter 0x49e119 keeps inner ≤ outer. `distFadeEnd` is zeroed for types 0, 3, 4
  (0x499bb3 via 0x4a3f99). The axis is local +Z (0x9e808c = (0, 0, 1)).
- Attenuation constants 0x579fdf: a = `attnStart`, replaced by 0.99 when above 0.99; distance
  scale = −1 / (R(1 − a)), bias = R / (R(1 − a)); cones are cos(angle × π/180) on the stored
  angle (0xc8d968 = 0.0174533), so the stored angles are half-angles; spot scale = 1 / (cos
  inner × (1 − r)) with r = cos outer / cos inner, capped at 0.99. Colour = RGB × brightness ×
  distance fade (0x56a4c0). The shadow weight is `shadowPower` only with `causeShadows` and
  slot +0x1a0 ≠ −1. The saturate form of the two terms is the shader's (inferred from the
  constants).
- `LightFlicker` 0x774baf, 0x7703c9, 0x774c92: 1600.0 at 0xa743b8 is the squared 40 m;
  `_nrangerandomizetime` has no reader in the class.
- Measured (level instances): PC Part 2 2,267 native `Light` nodes (types 1, 2, 4, 7): 2,087
  of class `Light`, 180 `LightFlicker`; PC Part 1 4,240 (types 1–7, 11 stored as type 5):
  3,755 `Light`, 460 `LightFlicker`, 21 `LightViewportSelector`, 4 `FXLightningShowLight`.
  `SearchLight` is on no native `Light` node of the PC levels (measured): its nodes are
  `PivotNode`s, 3 in StreetsOfRiot and 4 each in Prison and Streets2. LightFlash,
  SearchLight, LightViewportSelector and FXLightningShowLight: not established.

## 14. Audio

Report: `re/wp6_audio.md`. Consumer doc: `docs/SOUND_META.md` (`wlib/sound_meta.py`). Read
from code unless marked.

### Audio path

Animation event, AI decision or trigger → `SoundDef` (script class on the native `SoundSlot`)
→ variation choice in `command_sounddef_play_all` 0x831365 → `SoundSlot::play` 0x4d2758
(random pitch and volume) → `SoundSystem` 0x44a8fa (distance cull, priority steal) → one
XAudio2 source voice per sound (0x40271b; MS-ADPCM or PCM16) → the engine's own 3D code
0x44882d → effect and reverb submixes → mastering voice. Speech is a separate queue
(`SpeakCtrl` 0x83d414): a speak event is (speak id, character type, character); each type has
a group of definitions with one `SoundDef` per voice; a character draws its voice once.
Category 1 lines are the only ones that send `START_SPEAK` to the face; category 2 are
grunts; category 0 sends none either. A looping sound loops its whole buffer (0x40228c).
Music streams hold up to seven synchronous tracks (KAPOW_NAZ_FORMAT.md §8). Body classes per
character, from the fragments: Heavies, Thug, ThugFast `Enemy01`; ThugBig, Gimp, GimpGagBall
`EnemyBig`; Dominatrices and Twilight Lady `Enemy04`.

Sound system limits (writer 0x4af2d7, use 0x44a8fa): 1024 live prioritised sounds, 96 playing
voices, 128 for playing voices plus source voices queued for destruction (slot 3 0x44a868 =
fill of the ring at system +0x22c; pushed by `Voice_XAudio2` slot 5 0x402a3d, drained by the
worker loop 0x446e86 / 0x4468b0; that the drained call, vtable +0x40, is `DestroyVoice` is
inferred). The rules that use them are in SOUND_META.md ("Engine rules").

### SoundSlot (registration 0x4da99c, constructor 0x4d08af, property filter 0x4d654e)

| property | control / range | note |
|---|---|---|
| `sound`, `streamingSound` | resource `*.wav` | `streaming_sound` is the deprecated alias |
| `volume` | slider 0..1 | tapered, see below |
| `pitch` | slider 0..5 | |
| `minRange`, `maxRange` | slider 1..5000 (3D properties) | constructor default of `maxRange` 100.0 (f32 0x9e5bd8) |
| `reverbMinRange`, `reverbMaxRange` | slider 1..5000 (3D properties) | constructor default of `reverbMaxRange` 100.0 |
| `reverbMixFactor` | slider 0..1 (3D properties) | |
| `dopplerFactor` | slider 0..1 (3D properties) | `doppler_factor` deprecated |
| `enableObstructionAndOcclusion` | truth (3D properties) | |
| `lfeChannelLevel` | slider 0..1 (Routing) | `lfe_level` deprecated |
| `useCenterChannelOnly` | truth (Routing) | `center_channel_only` deprecated |
| `useBackChannels` | — | deprecated 23/9-08 |
| `randomPitchLength`, `randomVolumeLength` | slider 0..100 | jitter 0x4d094c (constants 0.01 f64 0x9e8460, 1.0 f64 0xc3cc48) |
| `priority` | string | |
| `assetIsLooping`, `numStreamTracks` | read-only getters | |

- The property filter takes the channel count only from the static `sound` asset (0x4350ac);
  for a `streamingSound` the count stays 0, so only the 3D flag (asset +0x95) hides
  `useCenterChannelOnly`.
- Volume taper 0x445b43: g(v) = 0.85·v² + 0.15·v, v clamped 0..1 (f64 0x9eb190, 0x9eb188).
- Distance attenuation 0x447274: the curve of SOUND_META.md "Engine rules"; step 0.25 (f64
  0x9eb370), clamp 0.001 / 0.999 (f64 0x9e76c8 / 0x9eb380). That 0x993980 is `log` and
  0x990e3c `exp` is inferred.
- Doppler 0x44785f: c = 346.6 (f64 0x9eb388), denominator floor 1e-6 (f32 0x9e6da4).
- Pan 0x4460f9 was not read in full; its four angle constants are 30°, 110°, 80°, 140° (exe
  bytes). The channel order stays inferred.
- The other constructor defaults of SoundSlot are not listed here.

### SoundSystemNode (registration 0x4caea5, constructor 0x44a22d)

Stored = node `9f587bcc` `SoundCtrl(SoundSystemNode)` of `GameEssentials/Sound.fragment`, the
same on PC Part 2 and Part 1 unless noted (measured):

| property | control / range | constructor | stored |
|---|---|---|---|
| `maxVoices` | — | not established | |
| `linearDistAtt` | truth | false (+0x1d = 0) | false |
| `obstructionFactor` | slider 0..1 | 0.5 (f32 0x9e6174) | 0.5 (Part 2 only) |
| `rollOffScale` | slider 0..10 | | 1.0 |
| `masterAttenuationPC` | slider −12..0 dB | | −2.0 |
| `masterAttenuationX360` | slider −12..0 dB | | −2.0 |
| `masterAttenuationPS3` | slider −12..0 dB | | 0.0 |
| `movieAttenuation` | slider −12..0 dB | | −3.0 |
| `lfeDownMixLevelPC` | slider 0..1 | | 0.0 |
| `multiListenerDistanceAttenuationType` | ADDITIVE 0, SATURATE 1, CLOSEST 2 | 2 | 2 |
| `multiListenerDisableOrientationPanning`, `multiListenerDisableDoppler` | truth | | |
| `multiListenerSeparationPanning`, `multiListenerGeneralAttenuation` | slider 0..1 | | |
| `testSound1..3` | resource `*.wav` | | |

- `_inumberofsoundcontrollers` of the script class is 20 on Part 2 and 0 on Part 1 (measured).
- dB law 0x445f4d: gain = 10^(clamp(dB, −96, 12) / 20) (constants 0x9eb1f0, 0x9eb1e0,
  0x9eb1d8, 0x9e5c68).
- VolumeCurve enum 0x4d9436, evaluator 0x4463bf: 0 linear, 1 `VOLUME_CURVE_LOGARITHMIC` (the
  0.85 / 0.15 taper), 2 square root, 3 = 1 − f(x·π/2) with π/2 at f32 0xc7e3d4 (that f,
  0x402b11 → 0x990d10, is the cosine is inferred). The buffer constructor 0x449b8d sets curve
  1 and 0x4d8c22 copies it to the controller: the default SoundController curve is 1.

### SoundEffectDefinitionNode (registration 0x4d6c5e)

Two parameter blocks, `effect_type_ps3` (item `ps3_i3dl2_reverb:0`) and `effect_type_xaudio2`
(item `xaudio2_i3dl2_reverb:1`), each with twelve I3DL2 parameters, plus
`editorTest1..5_<platform>`:

| parameter | range | type default (0x404407, exe bytes) |
|---|---|---|
| Level | 0..1 | 0 |
| Room | −10000..0 | −10000 |
| RoomHF | −10000..0 | −10000 (0x9e6730) |
| DecayTime | 0.1..20 | 1.49 |
| DecayHFRatio | 0.1..2 | 0.83 |
| Reflections | −10000..1000 | −10000 |
| ReflectionsDelay | 0..0.3 | 0.007 |
| Reverb | −10000..2000 | −10000 |
| ReverbDelay | 0..0.1 | 0.011 |
| Diffusion | 0..100 | 100 |
| Density | 0..100 | 100 |
| HFReference | 20..20000 | 5000 |

The description strings in the exe quote the I3DL2 defaults ("-1000 mB"), not these. The
preset table built on the stack of 0x404407 has 30 presets (index: name): 0 `default`, 1
`generic`, 2 `paddedcell`, 3 `room`, 4 `bathroom`, 5 `livingroom`, 6 `stoneroom`, 7
`auditorium`, 8 `concerthall`, 9 `cave`, 10 `arena`, 11 `hangar`, 12 `carpetedhallway`, 13
`hallway`, 14 `stonecorridor`, 15 `alley`, 16 `forest`, 17 `city`, 18 `mountains`, 19
`quarry`, 20 `plain`, 21 `parkinglot`, 22 `sewerpipe`, 23 `underwater`, 24 `smallroom`, 25
`mediumroom`, 26 `largeroom`, 27 `mediumhall`, 28 `largehall`, 29 `plate`. A preset is
applied by copying its value vector (0x4d0eca → 0x4495d0); the values were re-derived from
the exe bytes and are not listed here.

### Streams, music, packages, triggers, options

- **Stream assets**: a PC stream record is a 32-bit `ogg_packet` — 0x45cbae copies eight
  dwords to decoder +0x120 and replaces dword 0 by the data pointer; 0x8d3b20 reads dword 3
  into the block's end flag, dwords 4–5 into the granule position and 6–7 into the sequence
  number; 0x8d29c0 reduces the output count when the running position exceeds the packet's
  granule position and the end flag is set; 0x45db71 hands on whatever the decoder returns.
  `MediaStreamAsset` defaults 0x5548df: +0x94 = 0, +0x95 = 1, +0x96 = 0, +0x98 = 60 (the
  names follow the folded getters, inferred). `mediastream` is the only asset type whose
  compressible flag is cleared (0x554a2e).
- **Music**: `MusicPlayer.command_allocate` 0x7cf2a8 makes one SoundController per track
  (curve 2), plays each with volume 0 in the first child of the node
  `command_get_music_group` returns, and registers the cue event on controller 0;
  `MusicTrigger.command_trig` 0x7d1113..0x7d14ff has no `[ebp+0xc]` access, so its truth
  argument is never read; a one-shot slot already queued is not queued again and keeps its
  first cue id (0x7cf896).
- **SoundPackageCtrl**: `initialize_local` 0x83304e stores, for each enum value i, the last
  child whose `command_get_sound_effect_type` returns i with owner flag 1;
  `initialize_external` 0x83325a gives every index whose owner flag is 0 the entity, name and
  id of `m_elocaldefault`; lookup 0x6e0f13 by the position of the surface id in the
  package's id list.
- **TriggerActionSound**: `command_fire_action` 0x86150a withholds the children whenever
  `_tchildrenafter` is set, for every action type; `command_sound_done` 0x861583 fires them;
  its only sender is `SoundDef.Active` on exit (0x82aecf), to the callback given by
  `command_play_activator`, which only types 0 and 4 pass.
- **Option volumes**: `MenuSettingsCtrl.StateAudioSettingsMenu` 0x7b84da — the option is the
  selector's value × 0.1 (f64 0x9e9628), the selector is set with option × 10 (f64 0x9e5c60);
  default 1.0 for master, effects, voice and music (`command_set_default_settings` 0x82be66);
  the group volume is nVol × option (0x82fd6a).
- **Which option scales which group** [code + data]: the group tree is `GameEssentials/SoundDb/SoundDb.fragment`
  (`SoundGroups` → `MasterSoundGroup` → `EffectsGroup`, `VoiceGroup`, `MusicGroup`, `ProcessorGroup`;
  `ProcessorGroup` → `ProcessorVoiceGroup` → `VoiceEnemies`, `VoiceRorschach` 0.9, `VoiceNiteOwl` 0.96,
  `MissionSpeaks`, and `ProcessorEffectsGroup` → `Effect` 0.95, `EnemiesCombatSounds`, `PlayerCombatSounds`).
  `command_set_voice_volume` 0x8300e0 sets `_evoicesoundgroup`, `_emenuvoicegroup` and `_eprocessedvoicegroup`
  (members +0x44 = `ProcessorVoiceGroup` in `Sound.fragment`), so enemy voices follow the Voice option.
  `VoiceEnemies` itself (found by name under the master group) is only set to 1.0 or the damp factor
  (`StateActive` 0x829f70, `command_damp` 0x83104a).
- Subtitles: §15 "Text and subtitles".

## 15. File formats

Report: `re/formats.md`, `re/skeleton_blobs.md`. Layouts: KAPOW_NAZ_FORMAT.md, FORMATS_MISC.md,
FRAGMENT_FORMAT.md, TEXT_ASSETS.md.

### Archives and loading (KAPOW_NAZ_FORMAT.md §1.1, §2.4) [code + data]

- `.naz` mount 0x4428fb: a modified ZIP that round-trips. The engine indexes entries by the
  raw CRC of the lower-cased, '/'-normalised name (`naz_key(name)`; measured on three
  archives: 57 entries, 57 unique keys, every key = `naz_key(name)`); it uses the size at naz
  +16, never inflates an entry, accepts a plain zip, and the lowest archive slot wins. A
  capacity of five archives is inferred from the handle array (0xd91d24 to 0xd91d38), which
  the mount does not bounds-check.
- A blob is zlib-compressed if and only if `useCompressedAssets` (config key, default 1, read
  in 0x8be5ed) and the type's compressible flag (0x5480fe); only `mediastream` clears it
  (0x554a2e).
- The directory record keeps only `size[currentLanguage]`; the stream worker seeks
  `offset[language]` and reads `size[language]` (0x4e0e5d). A path already known is rebuilt
  (0x551f10) and re-read from this block's header.
- Load is a state machine (1 → 3 → 4 → 5 → 6 → 7) driven from frame end (0x42af4f) with the
  spare milliseconds of the frame, keeping a 5 ms margin (0x9e617c); header blob i+1 is read
  while blob i is deserialised. All stream entries of a load block are requested (at most 10
  queued) and must be delivered before state 7; the fragment is applied only then.
- With asset blocks (`useassetblocks`, default true, read in 0x8be426), an asset no loaded
  block lists is created empty and a notice is logged; it is marked "missing" only when
  single-file loading is forced on and the derived file fails (0x552532). A standalone
  derived header starts with [u32 version + 0x80000][u32 source CRC]. Measured on the 36
  standalone `_h_z` files of the six sets: the zlib stream starts at offset 8 on 36 of 36,
  and the first word is one value per type and build (KAPOW_NAZ_FORMAT.md §2.4); that the
  second word is the source CRC is from the code only.
- Stream manager defaults `prestreamtime` 2, `poststreamtime` 1 (0x4e155a, decompile only).
  Memory budget table: KAPOW_NAZ_FORMAT.md §2.4 (config text at 0xc8f178, every value read
  from the bytes).
- Script (TNT) classes are read by their native base class's loader (FUN_0047e126 stores the
  base at desc+0x5c; FUN_00511f96 re-types the entity).

### Block header and directory (`block_h_z`) [code + data]

Loader FUN_004a36d8 (loadblock.cpp), directory walker FUN_004a3525, header consumer
FUN_0049dd0e. The fixed header is exactly 400 bytes, read in one call (`push 0x190`
@0x4ae315).

    @0    f32 x8   bounds (two vec4)                -> LoadBlock+0x180
    @32   u32      block version signature (0x49db60: CRC over "8" and each asset type's
                   version + 0x80000; computed and discarded by the loader, 0x4a3b5e);
                   0x79D3E0DA in Part 2 and PS3 Part 1, 0xEE1FB0A3 in PC / X360 Part 1
    @36   char[36] GUID text: no reader. The header lands at load state +0x10; all 64
                   `[reg+0x1e8]` load-state accesses in the exe touch none of +0x34..+0x57,
                   and the only two hand-offs of the header pointer are the bounds copy
                   0x42af16 (bytes 0-31) and the fingerprint reader 0x49dd0e (@72, @327)
                   [instruction scan]
    @72   char[255] fingerprint: C string, 3-LFSR stream cipher, key
                   "1E564E3B-D243-4ec5-AFB7"; shipped blocks decrypt to
                   "THIS IS THE DEFAULT FINGERPRINT KEY, PLEASE CHANGE IT!"
    @327  u8       fingerprint display mode -> LoadBlock+0x1e4 (0 = overlay page 2 until
                   20 s after its first draw, 1 = always, 2 = never; 2 in every block)
    @328  u32 LE   fingerprint CRC: kapow_hash (no fold) of the 255-byte plaintext field;
                   bytes 0a 88 3f 59 = 0x593F880A on every platform; no reader
    @332  u32      tablesSize        directory bytes, starting at 400
    @336  u32      entry0Size        header-blob size of entry 0
    @340  u32      ioBufferSize      max(tablesSize, largest header blob)
    @344  u32      fragmentOffset    = 400 + tablesSize + sum of blob sizes (= fileSize − 8)
    @348  u32      fragmentSize      8
    @352  u32      numEntries
    @356  u32      numLocalized      records behind the per-language seek
    @360  u32      numStreams        records with hasStream = 1 (bordello 581)
    @364  u32 x6   languageHeaderOffset
    @388  u8       low-violence flag (0x435c0b); 389-399 zero

Directory record, from 400:

    6 x u32 headerBlobSize   one per LANGUAGE slot (FUN_0045c762), not per platform
    u32 typeHash             name_hash(asset type name)
    u32 nameLen; name
    u8 hasStream             the LAST field of a record (0 = header-only, 1 = has 6 stream chunks)
    if hasStream: 6 x { u32 offset, u32 size }   the record's OWN stream

A walk started at 399 (a zero pad byte that parses as flag = 0) gives a "+1 shift". The
localized records (numLocalized: watchmenpart2 has 14 `_uk` textRes entries, mainmenu 1 logo
bmp) sit behind the per-language seek. The header file tail is 8 zero bytes. `block_s_z` is a
pure stream pool with zero head / tail (6 of 7 exact; mainmenu has 109KB past the last
reference = other-language logo streams, zlib blobs of identical 174800B decompressed).
Corpus: 35 `.block_h_z` files = 7 levels × 5.

Trailing blob ("loadblock fragment"): [u32 nAuto] sets, [u32 nManual] {n, pathId[n], set}
(0x4ab461, 0x4a01d7, 0x4e1a59); both 0 in nine staged blocks, which end with eight zero bytes
(`fragmentOffset == fileSize − 8`); the stream-set lists are empty in every shipped block
except Part 1's `Prison.block_h_z`. The bounds of a stream set in the trailing blob are two
12-byte vectors, not two vec4 (StreamBuffer 0x4354a8 reads 12 bytes; the 16-byte readers are
0x4354d1 and 0x43553c; 0x4353e9 is ReadBool, 0x435403 ReadU8). Order in 0x4addf6: auto sets,
fragment apply (0x49e1ad), fragment buffer free (0x499b02), manual sets.

Asset-type hashes (name_hash of the type name): sound 0x80aa346d, Texture 0x7d8d9a63,
animation 0x45870ad6, fragment 0xa048cb21, modelRes 0xf2e47acb, PropertySequenceAsset
0x5cf8a3cf, ParticleSystemAsset 0x46b6f587, grass 0x86a9d7dd, mediastream 0xe1faf50f,
DetailMeshAsset 0xdeb3f74e, textRes 0x7d6d720b, ModelEffects(ModelRes) 0x41764525 (doors /
rubble / carpets / leaves), TextureEffects(Texture) 0x96ea413f (terrain detail / decals),
terrain 0x6532e9b4, pivotbook 0xd8c06967, aipathdata 0x48d86c33, font 0x62f2722a (0x5431f5),
terrainColoringAsset 0xf1fdbe49 (0x531981; 5 records in Part 1 data, none in Part 2). The
hashes are computed at run time; the names are not in the exe strings. The asset type
`fragment` is registered with the source extensions `scene` and `fragment` (0x542c1a) and
has one header reader (0x54306d): a `.scene` is a Fragment (8 `SceneScope` nodes in Part 2, 9
in Part 1, identical on the three platforms of a part).

Ruled out: the four bytes at 328 are not a magic 0x593F430A and not the version stamp; the
version signature is the u32 at 32.

### Asset header blob [code + data]

`[u32 typeNameLen][typeName][u32 bagDwords][bag]`, body at 4 + typeNameLen + 4 + 4 ×
bagDwords. The u32 is the property bag's length in dwords (FUN_00511f96), not a class id: 45
Texture, 91 ModelRes, 55 TextureEffects, 96 ModelEffects. An asset header's opening name
length states the byte order of the header (`watchmen_extract.header_order`). A 64-bit
property value is two u32 words, low word first, each byte-swapped on console. The standalone
Part 1 (PC, Xbox 360) stores property records without the type hash (KAPOW_NAZ_FORMAT.md §3).

### Texture header [code]

FUN_005382aa (descriptor FUN_00429e77): `u32 nFrames, u8 hasAnim`, then per frame 8 slots —
slot 0 always, slots 1-7 each behind a presence byte — and the source path. Descriptor
29 bytes: width, height, format enum, 0, type (1 = 2D, 2 = cube), u8 hasAlpha, mipCount, 0.
Linear formats store every mip row padded to 4 bytes. Per-platform format table at 0x009E8F78
(normal maps PC 9 -> X360 10 -> PS3 7; channel order §13). File slots: 0 diffuse, 1 normal,
2 specular, 3 glow, 4 height, 5 fallOff, 6 ambOcc, 7 specSize (KAPOW_NAZ_FORMAT.md §4.2). Not
answerable from the PC executable: the PS3 cube-map framing and the X360 2D mip-tail offsets
(the tiling code is in XBox360LibraryWrapper.dll; the 2D bake path is compiled out).

### ModelRes: vertex declarations, header, stream [code + data]

Stride table 0x00C791B0 (u32 x 11): 28, 24, 68, 16, 56, 44, 56, 60, 48, 20, 32. Declarations
are created in FUN_0045544e. The format id is stored in the file: it is the third u32 of the
vertex-buffer descriptor (not an element count).

    5  rigid         44  pos f32x3 @0, normal half3 @12, colour D3DCOLOR @20 (bytes B,G,R,A),
                         uv half2 @24, tangent half3 @28, bitangent half3 @36
    6  skinned       56  format 5 + bone indices @44 (idx0..3 = bytes 46, 45, 44, 47),
                         weights half4 @48
    9  shadow hull   20  pos f32x3 @0, normal half3 @12
    10 skinned hull  32  format 9 + bone indices @20, weights half4 @24
    8  terrain       48  pos, half4 normal, colour, 3 x half4 texcoord
    3                16  FLOAT2 pos + FLOAT2 uv (2D / UI)

Positions are raw floats: no quantisation, scale or bias in any format, and no declaration
has a SHORT element. Indices are always u16 triangle lists; the descriptor stores a byte
count. Part 2 PC census (740 models, 3,118 buffers): format 5 x2370, 6 x287, 9 x357, 10
x104, nothing else.

Header after the property bag: ModelRes::Read FUN_00547006 -> Part FUN_00545927 -> Submesh
FUN_00542541 -> MeshBuffer FUN_004336ec; layout in `KAPOW_NAZ_FORMAT.md` §6b. Stream: for
each MeshBuffer in header order, vertices, indices, `[u32 n][n x 40 B]` cluster table, `[u32
n]` lists, `[u8 has][vertexCount x 8 B]` (order of FUN_00433ef4). Reproduces the stream
length exactly on 740 / 740 models. Vertices are part-local: model space = conj(q)·v·q + pos
up the parent chain (KAPOW_NAZ_FORMAT.md §6b). The per-part proxy buffer is an occluder mesh.

- Submesh bool +0x24: set = skipped by the callers of 0x4b3886; 0 in all 2,575 staged
  submeshes. Submesh u32 +0x28: 0..10 = the shadow-hull group id (builder 0x544ae4: same id
  above 0 and +0x24 clear → one hull; no run-time reader). Part u32 (node +0x2c): index into
  the model's pivot-book list (0x53e987; consumer 0x4a5961 reads part 0's); 0 on all 6,220
  parts.
- Writers: ModelRes header writer 0x543e10; submesh writer 0x53f736 (fourth bool
  `submesh+0x14 != 0`, fifth `MeshBuffer+0x34 != 0`, then the cooked cloth); MeshBuffer
  0x42f110, 0x428d3d, 0x4291e0; part chain 0x53b605; primitive table 0xc7f398 = {5, 4, 6, 1,
  2, 3}; count rule 0x417bf2 (n / 3 for type 1, else n − 2); strip rule 0x431206; morph
  targets 0x430abd (stride 0x44); stride table 0xc791b0 = 28, 24, 68, 16, 56, 44, 56, 60, 48,
  20, 32; joint shifts 0x9e8c48 = 16, 8, 0, 24; box pad 0x9ebc04 =
  0.05.
- Mesh node inner items (cnt34 / cnt40 > 0 only on mesh nodes): inner item 0x2c =
  `[str][u32 n][n ids][u8][u8][u32][u8]` (material / palette binding); cnt40 items =
  meshbuffer descriptors (`[vec3 bbox x2][u8 hasBuf][deep]`).
- Part 2 PC model counts, one basis (the six-set export, extract log; measured): 743 model
  names = 740 `.model` headers + the three engine unit primitives (`unit_box`, `unit_cone`,
  `unitsphere`, `.modelres`); the 5 skeleton models have no stream, so 735 models have mesh
  data and 738 outputs are written (735 + 3). 984 / 978 are records over all blocks before a
  name is written once. Model GLBs (JSON chunk of every GLB of the six-set export, 782 per
  Part 2 set, 1,182 per Part 1 set): 738 model GLBs / 2,388 primitives per Part 2 set (NORMAL
  2,388, TANGENT 2,223), 1,088 / 3,568 per Part 1 set (NORMAL 3,568, TANGENT 3,331); COLOR_0
  on 1,367 primitives on PC Part 2 against 1,349 on both consoles, and 1,942 on PC Part 1
  against 1,907 (PS3) and 1,909 (Xbox 360); 13 model GLBs per Part 2 console set, 23 on PS3
  Part 1 and 22 on Xbox 360 Part 1 have fewer COLOR_0 primitives than PC. Characters: 4 mesh
  primitives per console set are without NORMAL (two body primitives each in `Rorschach.glb`
  and `Rorschach_Dry.glb`, which carry the `not_decoded` marker); faces: all primitives have
  NORMAL on all platforms. Attribute values were counted, not compared with PC.
- The name-anchored node reader (`skeleton_records.parse`) refuses a mesh-free bone that has
  one empty shadow group: reading those by default would add 345 nodes (1,078 volumes) to
  the skeleton JSON and the jiggle candidates. The header-driven readers see all nodes.
  `skeleton_records.py` holds the volume parser (`parse_node_tail`); its older transform
  parser is off by one (the transform belongs to the FOLLOWING name) and is kept for
  reference only.

### Node collision volumes and the third list (`re/skeleton_blobs.md`) [code + data]

Node::Deserialize 0x545927, lists at 0x545c7f-0x545d94, factory 0x524b23. After a node's
name: `[u32 f1][i32 parent][u32 cnt34][cnt34 x u32][u32 cnt40][u8 flag]`, then:

    [u32 n0] n0 x volume     shapes for PhysX scene 0   (node+0x4c)
    [u32 n1] n1 x volume     shapes for PhysX scene 1   (node+0x58)
    [u32 n2] n2 x surface    (node+0x64)

    volume  = [u32 type][u32 base][type data][f32x3 pos][f32x4 quat xyzw][u32 blobLen][blob]
    surface = [u32 nT][nT x (f32x3, f32, i32)][u32 nV][nV x f32x3][u32 nI][nI x u32]

    type 2 concave mesh   u32 mode, u32 nV, verts, u32 nI, u32 indices   + cooked blob
    type 4 convex mesh    same; blob starts "NXS\x01CVXM"
    type 5 box            f32x3 FULL extents                (52 bytes)   reader 0x521396
    type 6 sphere         f32 radius                        (44 bytes)   reader 0x521c3f
    type 7 capsule        f32 diameter, f32 height along local Y (48 bytes)  reader 0x52213d

The blob is a cooked PhysX mesh and exists only for types 2 and 4. PC corpus (740 models):
934 volumes in 23 models — 743 capsules, 123 boxes, 51 spheres, 17 convex meshes; all 2,069
mesh-free node regions tile (5217 node regions in all, 7/7 character skeletons 100 %; the
female skeleton has 24 capsules). The breast capsule on Spine2 has diameter 0.1429, height
0.2428 at local position (-0.1887, -/+0.0953, 0.0237); its quaternion is the capsule's
orientation. These are collision volumes (ragdoll shapes in scene 0, cloth-collision shapes
in scene 1), not joints. `wlib/parse_model_nodes.py:parse_node_aux()` and
`skeleton_records.parse_node_tail` read them.

The third list is non-empty on 29 nodes of 19 models; it is a particle-emission surface,
`MeshParticleData` (ctor 0x560601, vtable 0xa3d538, reader 0x561d1c), consumed by
SurfaceSpawner 0x54fc6b / 0x54decc; budget trunc(particleAmount × sum of weights) 0x553c41;
weight = triangle area in m2 on 27 of 29 staged surfaces; 1.0 per triangle, whatever the
area, on 2 Part 2 and 17 Part 1 surfaces (2–292 triangles; 8 on nodes named like splash
emitter / surface — `ACUnit_Wall_02` "splash emitter" among them — 2 on other named nodes, 7
on the unnamed root); why is not established, and the constant weight is not tied to a node
name. Stored normals are unit length and opposite to the index winding; on Rorschach's arm
surfaces they are 21–36° off the face normal (measured). Centroid factor 1/3 at 0xa37828, used for a
horizontal (x, z) distance test against `radius` (0x54decc with a material test, 0x54e23e without); the
collector stops at 1,500 triangles. On a character the surfaces are collected per ragdoll
body from that body's node (0x54fba7), culled by `faceCullLimit` and material id, with no
radius test.

### The ModelRes header of the stand-alone Part 1 [code + data]

- It is the Part 2 record stream with two differences: one flag byte fewer per submesh record
  — the Part 1 readers (PC 0x539078, Xbox 360 0x828bccc0) read 1, 1, 4, 1 bytes before the
  MeshBuffer, the Part 2 readers (PC 0x542541, Xbox 360 0x828fea68) read 1, 1, 4, 1, 1; the
  kept byte is the dynamic-copy flag — and untyped property records in the bag and in the articulated-body
  blob.
- Version chain: the submesh term is 10 in the Part 1 builds (PC 0x5320a4, Xbox 360 0x828b4ff0)
  against 11 in Part 2 (0x53a563, 0x828f54c0); the model (46), node (10) and mesh-buffer (15,
  8, 2, 3) terms are equal. Of the PC asset terms only `DetailMeshAsset` differs as well (PC
  Part 1 0x522a4e: 3, Part 2 0x52af3f: 4). The header stores no version and no loader branches on one.
- An untyped record's type comes from its key (data: 86 keys, each with one type on all 918
  typed blobs of PS3 Part 1 and PC Part 2).
- Data: 1,090 of 1,090 headers of PC and Xbox 360 Part 1 read in this layout, 1,085 in
  exactly one of the two layouts (the 5 without a submesh read in both and take the bag's
  answer); the stream is consumed exactly on 1,085 of 1,085.
- Code (PC Part 1 against PC Part 2, instruction by instruction with addresses and source line
  numbers masked): the model root reader 0x53d563 (Part 2 0x547006) and the 201 functions it
  reaches within three calls are equal but for the submesh byte (0x539078), the untyped record
  reader 0x50513c (Part 2 0x510e5f), and three checks or flags that read the same bytes
  (KAPOW_NAZ_FORMAT.md, "The stand-alone Part 1 header").

### Console model streams [data]

- Same header as PC; in the stream the vertex strides are `[28, 24, 68, 16, 56, 32, 44, 60,
  36, 16, 28]` by format, the cluster record is 48 bytes (PC 40) and a list item 0x50 bytes
  (PC 0x44). Exact tiling on 735 of 735 models of each Part 2 console set and 1,085 of 1,085
  of each Part 1 console set; against the PC copy, vertex for vertex, on all 3,640 console
  models: same buffers and triangles, UVs, joints and weights equal, normal, tangent and
  bitangent within 0.00195. Not read from console code.
- Console positions are coarser in the files (power-of-two steps, up to 0.5 m on the Part 2
  sky domes, 1.0 m in Part 1).
- Vertex colour is stored A,R,G,B on Xbox 360 (`D3DCOLOR`) and R,G,B,A on PS3. A model does
  not name its console; the exporter takes the order from the console the source path names
  (KAPOW_NAZ_FORMAT.md §6b) and checks it with the rule "a buffer without `hasAlpha` has
  alpha 255 on every vertex" (6,419 of 6,419 such PC buffers); all 13,378 console buffers
  decoded this way equal PC. Where the rule does not decide, the colour is not written.
- Inferred, not compared: the joint offsets of the skinned shadow hull (format 10).

### `.sequence` [code + data]

Asset FUN_0054558c, track FUN_005415bf, keys FUN_00547f4c / FUN_00547fdb, evaluation
FUN_0053aa43; deserialisation is a constructor chain (0x543729 -> 0x550905 -> ...); grammar
in `FORMATS_MISC.md`. Header: `[f32 duration seconds (0.3..60.0)][u32
loop mode][u32 nobjects]`. Loop mode (asset+0x94, describe 0x53cfce): 0 loop, 1 oneshot, 2
oneshot_reverse, 3 loop_reverse, 4 pingpong (shipped values 0, 1, 4). Start 0x49d705, update
0x49d7fe (a loop resets the position to 0.0, it is not a modulo); time base `speedFactor` ×
[0xe14304]. Object header: path, then `u32 flag` = the number of fragment hosts to climb
above the playing node's own host before the id path is resolved (0x5411dc -> 0x53c224;
equals a tag-4 reference's `a - 1`), `u32 id count` (an object can have a path and ids), then
the class name. A track uses spline keys iff its property type is number, vector or
quaternion (FUN_00539dd9): per-key spline handles (inT, inV, outT, outV per component).
Quaternion properties are keyed as Euler degrees and converted q = qx.qy.qz (FUN_00499733).
Linear keys: number 0x4fa5bb, vector 0x4fbf8d, quaternion tracks 0x53aa43 (vector rule on
Euler keys), integer 0x4fac1c `a + trunc((b - a) t)` (0x990ba0 = cvttsd2si), all other types
0x47fc01 = key A. Action track of a PropertySequenceNode: 0x4ab2fe → 0x4ab2e3 → 0x4ab230,
0x4a5d5e, 0x49d529, 0x4999e7, 0x498192. Events: 0xe146ec `OnSequenceStart`, 0xe146e8
`OnSequenceStop` (registered at 0x4ad6c1 / 0x4ad6d1). Corpus: 194 files; the parser reads
every object (`decode_sequence.py`).

### `.pb` (kapow_props) [data]

File prefix (the nskip dwords) = [u32 bankId (sequential 0x16269ef8..fa)][u32 0x2964
version][u32 nblocks-1]. Zero trailing bytes on all 3 files. Pivot books: `CollisionNode`
book `/pivotbooks/default.pb` (0xa2f164).

### `.fragment`, levels, saves (FRAGMENT_FORMAT.md, LEVEL_META.md) [code + data]

- Fragment header 0x54306d; reference readers 0x500b81 / 0x505d84; scope search 0x53a5ff
  (depth-first, child order, nested hosts not entered); singleton registry 0x4a1d63 /
  0x49aadf; `FragmentNode::SetFragmentAssetByName` 0x498db7 with case-folding lookup
  0x54ba59.
- Fragment streams: 0x545e1b creates entities at `0xFFFFFFFF` records and applies each
  property as it is read; the typed branch reads `[typeHash][wordCount]` (0x545e1b, 0x53c5c3);
  0x53c5c3 is the transcoder (log strings `Offset: %d: Entity ID: %u Signature: %s`); 0x5409da
  writes the header in the order +0xa4, +0xbc, +0xbd, name +0xac, +0xbe, `typed`. Measured on the
  stream bytes: a node's block stores `logicalParent`, `siblingOrder`, `parentLink`, then
  `localPos`, `localOrient` (44,281 of 44,281 nodes with a transform in PC Part 1, 20,577 of 20,577
  in PC Part 2), and every in-file `logicalParent` names an earlier record (78,064 / 56,391).
- Trigger graph: `TriggerConditionBase` 0x8632fa, `TriggerActionBase` 0x84afa9 (child order,
  aux action), `TriggerActionDelay` 0x852ecd (delay of child i = `m_ndelaynumber<i>`),
  `TriggerActionCheckpoint` 0x85d2de (children run on restore; `_estreamblock` is its
  property at +0x18), `CharacterGroup` 0x66267e, checkpoints `GameStateCtrl` 0x74f382 (reach)
  / 0x74f5f1 (restore).
- World transform: `world.quat = local (x) parent`, vectors rotate as conj(q) v q; a toolkit
  GLB is placed with translation = world position and rotation = conj(world quaternion);
  verified by assembling the Bordello main hall (73 model instances at 0 / 90 / 180 / 270
  degrees close into a ring; ten enemies stand 0.000 m above their rooms' floor triangles).
- Save file `.kpw`: `u32 5, "KPWF", u8, u32, u32 titleChars, UTF-16LE title, u32
  payloadBytes`, then records `[entity id][property hash][type id][nWords][words]`; the type
  id is the name hash of the type name. Both files of a real profile decode completely.
- Part 2 PC: 6 levels, Part 1 PC: 7 levels, 0 unresolved references. 11 fragments are
  reapplyable. Block file names are derived from the load block's name.

### Text and subtitles (TEXT_ASSETS.md, `wlib/text_assets.py`) [code + data]

- `textRes` loader 0x5387ae: `[u32 rows]` then per row two counted UTF-16 strings (0x4374d1),
  key and text; big-endian on consoles.
- Language slots = the `LANGUAGE` enum (0x47ff8c), current language 0x45c762 in the block
  directory reader 0x4a3525: English, French, Italian, German, Spanish, Danish. Slot 5 is a
  byte copy of slot 0 in all six shipped sets. PC mapping 0x45c7a6 from GetLocaleInfoA(0x800,
  LOCALE_ILANGUAGE), English fallback, Danish unreachable on PC; X360 0x82a34a20; PS3
  0x154ee0. Table: TEXT_ASSETS.md.
- `SubtitleSlot` builds a map key hash -> (start, end, row) when its text resource is set
  (0x4da4db); key hash 0x4d24aa (lower-cased A-Z, raw Kapow hash 0x423ca1); times `mm:ss:zzz`
  (0x4d21be); lookup at time t 0x4da273; cutscene tables by `GetIndexFromTime` 0x4da37f.
  Time constants 60.0 (0x9e6120), 0.001 (0xaad40c), 10.0 (0x9e5c60), error -1.0 (0x9e6a8c).
  `0 <= end < start` drops the end (0x4da710). Line clock = real frame time, capped at 0.1 s
  (0x496294). Movie subtitles: 0x49c557, movie time 0x435a65.
- A sound's key (0x4d89d0): the wave's file name without directory and extension, cut at the
  first `_uk`, then at the first `_pc`, both case-sensitive (bytes at 0xa1435c
  "_pc\0_uk\0"). Driven by `SoundDef.Active` 0x82aecf through `SubtitleHUD` (0x8492fa,
  0x84a20c); mission speech replaces non-mission speech.
- Data: no shipped in-game key has times (0 of 4,477); `defaultDuration` 6.999999 s in game,
  5.0 s for the eight cutscene slots. Part 2 PC: 1,205 waves with subtitle rows; all 1,664
  category-1 speak lines have one, none of the 2,835 category-2 entries.
- HUD text: TEXT_ASSETS.md "TextBox layout" has the rules. Constants (exe bytes): break table
  0x9eaab0 = `20 2d 5f 0a 09 0d 00`; 0xa06998 = 1280.0, 0xa06990 = 720.0; 0x9e814c = (1, 1,
  1, 1); Sprite constructor 0x4c3765: 0.05 (0x9ebc04), 0.0888889 (0xa0aac4), 4.0, 10.0,
  25.0, cull mode 1, axis 4. `StringLib.FormatNum` 0x848ba8 prints `"%f"` and cuts trailing
  zeros; its 28 call sites are editor filters and debug views, none a HUD class.
- TextBox markup (`%N`, `\n`, `#RRGGBBAA`) is read from code in TEXT_ASSETS.md. Not established:
  which movie uses which cutscene slot.

### Small asset formats (FORMATS_MISC.md) [code + data]

- **`.font`** (read: `Font` reader 0x540c6e, `FontBuffer` reader 0x44245e, texture descriptor
  0x429e77): a flag byte, the 29-byte descriptor, the atlas inline, eight fields, then
  27-byte glyph records. Atlas block: PC the full mip chain; Xbox 360 the size the descriptor
  states; PS3 behind a 36-byte RSX descriptor. Data: 18 of 18 files rebuild byte for byte,
  the decoded atlas is the same image on the three platforms; 211 / 211 / 202 glyphs in Part
  2, 209 / 209 / 200 in Part 1. Inferred (holds on every glyph of the 18 files): `uv` is the
  top-left corner in atlas units and `u_width = width / atlas width`. The descriptor's `x` is
  the texture usage (0x456d46); `b04`, `b38`, `b3c`, `v28`, `v30`, `f24`, the glyph `flag` and
  `offset` are read from code. The format holds no kerning data.
- **`.terrain`** (read: header 0x5397d0, sector 0x52e011, cell 0x529a1a; stream 0x535e15 →
  0x532a6a; per-layer ranges 0x5370f7 and 0x5371ef; grass map 0x52e3ab, detail map
  0x53260b): quad size, sector grid, texture layers, grass and detail lists, a second texture
  list with rectangles drawn after the terrain, then per sector and cell the boxes, the
  vertex and index buffer descriptors and two masks. Stream per cell: vertices, u16 indices,
  a whole-cell draw range, per-layer index ranges for two passes, two per-vertex byte maps
  (grass id + 1, detail mesh id + 1). **The file stores no height field**: the engine fills a
  16-bit height texture from the mesh at load (read: 0x535e15). The stand-alone Part 1 uses
  the same grammar (data: 24 of 24 files of the six sets parse to the last byte). PC vertex
  48 bytes, console 36 (data, matched against the PC values: positions, colours, UVs,
  indices and both byte maps identical on 16 of 16 console streams, normals within 0.002;
  not read from console code). Inferred (agree on 24 of 24, counted in each JSON's `checks`):
  the two boxes are all vertices / the vertices the indices use; the four `place` words of a
  rectangle; pass 2 is the blend overlay (every pass 2 triangle repeats a pass 1 triangle);
  the name "decal" for the rectangles. Sector `flag`, `b10`, `b19` / `b1a`, the index
  buffer's `x` and the buffer `flags` are read from code, `f14` and `f1c` measured
  (FORMATS_MISC.md, `.terrain`: `enabled`, `texture`, `wrap_u` / `wrap_v`, `primitive_type`,
  `uv_rotation_deg`, `uv_scale` / `uv_offset`). `b18` is read only by the terrain writer and is 0 on every PC decal; rotation, `uv_scale` and `uv_offset`
  are read only by the loader and the writer, so the decal vertex buffers carry the final UVs (FORMATS_MISC.md). No collision data and no LOD table exist in the file; a hole is a quad
  without triangles. Terrain draw 0x49c3be: 0xc79520 (the identity; 53 absolute references
  to it and 208 to 0xc79520..0xc7955f, none a store — measured) to 0x42c8fa with slot 0x28
  (0x49c3ef) and to effect vtable +0x24 (0x49c41b); the node to vtable +0x2c (0x49c423); then
  0x53886b. Ray test 0x49c4fb. `TerrainNode` vfunc 36 0x49f3e4 copies node +0x88..+0x94 to
  asset +0x114..+0x120; queries 0x52a22f, 0x531002.
- **`.terraincoloringasset`** (read: 0x52da01): eight values, three flags, one 64-byte
  texture descriptor; the stream is that texture, one 8-bit channel. Data: 5 files per Part 1
  set, none in Part 2; PS3 equals PC pixel for pixel, Xbox 360 (DXT3A, 4 bits) within 16. The
  eight values and three flags are the map size and nine registered properties
  (FORMATS_MISC.md; getters 0x52cb15 … 0x53a5f8, bake 0x52d646). Not established: the texel
  position of the one 1×1 Xbox 360 map. That it is an ambient map is inferred from the editor
  caption "Generate Terrain Ambient".
- **`.detailmesh`** (read: 0x52de50; stream 0x5322c6): after the property bag `u8 hasMesh`
  and the vertex and index buffer descriptors, 25 bytes. The stand-alone Part 1 has no flag
  byte, 24 bytes (read: the Part 1 readers, PC 0x525b7e and Xbox 360 0x828dae50, go from the
  bag straight to the two descriptors; the PC Part 1 version term is 3 against 4). Data: the stream tiles with a 60-byte vertex on 30 of 30 files.

### Asset names and letter case [data + code]

- Each archive stores an asset path in the letter case of its own build: three Part 2
  textures differ between the platforms, and the source path inside the texture header
  differs the same way. Within one archive 30 / 29 / 29 names (PC / Xbox 360 / PS3 Part 2)
  and 187 names (Part 1, each of the three platforms) occur under two spellings in different
  blocks, as the extract logs print them with `--names stored` (the default naming prints 23
  on each Part 2 set: a later copy under the canonical spelling is not a second one); the
  first in block order is the same spelling on the three platforms for all of them.
- Each of the three paths is stored once, in one block header per archive (bordello,
  streetsofriot, tutorial). Model and particle headers use their archive's spelling;
  fragments use one spelling on all platforms, and on PC `TrashCan_03.fragment` names
  `GarbagePile_01.bmp` while the archive stores `garbagepile_01.bmp`, so resolution cannot
  depend on letter case. `name_hash` is equal for both spellings; the string compare
  `0x42536e` accepts bytes that differ only in bit 0x20.

  | Texture | Block | PC (both archives) | PS3 | Xbox 360 |
  |---|---|---|---|---|
  | `/art/Effects/Particles/Textures/…` | bordello | `Fire_01.BMP` | `Fire_01.BMP` | `Fire_01.bmp` |
  | `/art/props/common/garbage/textures/…` | streetsofriot | `garbagepile_01.bmp` | `GarbagePile_01.bmp` | `garbagepile_01.bmp` |
  | `/art/props/common/junction_boxes/textures/…` | tutorial | `WallCables_03.bmp` | `wallcables_03.bmp` | `wallcables_03.bmp` |

  Part 1 does not differ: `WallCables_03.bmp`, `GarbagePile_01.bmp` and `Fire_01.BMP` on all
  three Part 1 sets. Referrers (2,687 raw files per Part 2 set): `.model` → garbage pile
  `garbagepile_01` ×4 on PC and Xbox 360, `GarbagePile_01` ×3 on PS3; `.model` → wall cables
  (`Sewer_Cable_Hanging_04`) `WallCables_03` on PC, `wallcables_03` on both consoles;
  `.particle` → fire (`MatressFire_03`) `Fire_01.BMP` on PC and PS3, `Fire_01.bmp` on Xbox
  360; `.fragment` → garbage pile `garbagepile_01` ×4 and `GarbagePile_01` ×1, wall cables
  `WallCables_03` ×4, the same on the three platforms. Not established: which of the two
  (hash or the compare) the texture lookup uses; inferred: the stored spelling comes from the
  build of each platform's model or particle (the packer was not read).
- **The toolkit writes one spelling** (`--names canonical`, the default;
  `wlib/canonical_names.py`, table `wlib/canonical_names.json`, format
  `watchmen-canonical-names/1`). 40 asset paths have two spellings among the six sets: the
  three textures above, and 37 that are spelled one way on the three Part 2 sets and another
  on the three Part 1 sets (32 textures, the models `Rubble_RoofTop_02` and
  `Rubble_Rooftop_03`, and the folders `art/environments/common/Decals`,
  `art/environments/constructionsite/Textures`, `art/props/common/chains`). All 40 exist in
  Part 1, where the three platforms agree, and the table gives each its Part 1 spelling,
  keyed by the folded path up to and including the component it respells (folding: ASCII
  letters only, the letters `name_hash` and `0x42536e` do not tell apart). A 41st entry names
  a folder that has two spellings inside one set: `art/props/common/streetlines` (two Part 1
  models are stored under `Streetlines`; every fragment and texture of the six sets says
  `streetlines`). Case-only path differences with the stored spelling: 14 / 13 / 12 between
  PC and PS3, PC and Xbox 360, PS3 and Xbox 360 Part 2; 6 between PS3 Part 1 and each
  loose-folder set (`files/data/Levels/Game_Levels/<Level>/Gameplay/<name>.hpd` against the
  archive's lower case); 304 / 307 / 317 between the parts of PC / PS3 / Xbox 360. In the
  six-set export: 0 file paths and 0 folders in the nine comparisons.
  - An asset is written under the table's spelling in `extracted/`, `textures/` and `models/`;
    a path the table does not list keeps the archive's. A later copy of the asset under
    another spelling is the "twin" of the item above.
  - A folder takes the table's spelling, else the spelling of the first path written into it,
    once for `extracted/`, `textures/`, `models/` and `audio/` together (`share_folders`; a
    case-insensitive file system does the first-path part by itself, per tree). `extract`
    writes each asset to `extracted/` first, so the other trees follow that one. As stored
    (the same on the three platforms), 5 folders of Part 2 and 21 of Part 1 are spelled
    otherwise by their first model or texture than by their first asset: `Environments`,
    `Common`, `Archie`, `Doors`, `Doors_Slidedown` in Part 2; in Part 1 those five, ten
    `Building_*` folders, `Level02`, `Models`, `AutoBody`, `Shop_Signs`, `Streetlines` (models)
    and `prison_lamp` (textures, beside `Prison_Lamp`). `extract` on the six sources with
    stubbed decoders, 10,386 / 13,237 paths per Part 2 / Part 1 set: no folder of `models/`
    (232 / 330) or `textures/` (1,316 / 1,660) differs from `extracted/`, and the nine set
    comparisons give 0 case-only files and 0 folders. The six-set export has 231 / 329
    folders below `models/` and 1,316 / 1,660 below `textures/`; why `models/` has one fewer
    than the stub run is not established.
  - Files brought from beside a loose-folder source are named in lower case: none of the 235
    entry paths of the four archives (57 per Part 2 archive, 64 in PS3 Part 1) holds an
    upper-case letter.
  - A texture reference is resolved without regard to letter case and named like the texture
    written: during `extract` by the spelling the asset got, elsewhere by the table. Of the
    material references of a set, 48 / 48 / 46 (Part 2: PC / PS3 / Xbox 360, of 2,186 / 2,185
    / 2,187) and 188 / 187 / 187 (Part 1, of 3,525) name their texture in another letter case
    than its folder has (raw model headers of the six sources); 173 texture paths have such a
    reference in a `.model` or `.fragment` of at least one set.
  - The tables written from an export spell a string that names an exported file as the file
    is written (`ExportIndex`, `respell_export`: level JSON, particle index, `fx_meta.json`,
    `grade_meta.json`, `anim_meta.json`, `sound_meta.json`), with the stored string under
    `"stored"` in the same record. The lookup is by folded path: a `.bmp` / `.tga` is the
    folder `textures/<path>`, a `.model` the files `models/<path>.obj` / `.glb`, anything else
    the file below `extracted/`, `audio/`, `files/data/` or `files/` (the game names a loose
    file of its `data` folder without that folder: the 15 movie strings of a Part 2 set's
    level files and the 17 of a Part 1 set's name `.bik` files below
    `files/data/art/cutscenes/`). The strings of the level fragments as stored, against the
    paths `extract` writes: in the 6 level files of PC Part 2, 3,432 `.fragment`, 3,090
    `.model` and 153 `.sequence` strings differ from their file in letter case only; in the 7
    of PS3 Part 1, 15,355 `.bmp`, 4,159 `.fragment`, 12,151 `.model` and 341 `.sequence`
    strings. Respelled, none does. The particle index: 49 of 56 texture strings on PC Part 2,
    56 of 66 on PS3 Part 1. Decoded asset data (every JSON under `extracted/`, the per-file
    particle JSON, `config` / `config_tree` of a nav JSON, the `overrides` of `sheet.json`)
    keeps the stored strings; `canonical_names.resolve(export_dir, string)` gives the file
    one names.
  - The stored spelling stays on record: `_canonical_names.json` of the export (`renamed`,
    `twins`, `folders`), `stored_name` in the texture's `sheet.json` (only where the texture
    has one: all 939 Part 2 and 1,208 Part 1 texture folders do), the model's `.model.json`
    and the particle index. Names respelled per set: 42 / 42 / 44 (Part 2), 29 / 11 / 29 (Part
    1; 18 of the 29 are the loose-folder files, 2 the `Streetlines` models).
  - `--names stored` (`$WATCHMEN_NAMES`): the spelling of each set's archive everywhere, and
    the stored strings in the tables.

## 16. Scene graph, levels and triggers

Read from code unless marked; constants from exe bytes.

### Scene graph

- World transform 0x48d789: local quaternion (0x422a16), local position in row 3, times the
  parent matrix when the pointer at pivot +0x40 is non-null; no scale term and no
  `parentLink` test. `parentLink` is tested at 0x4932b6–0x4932e1 (`cmp [scene+0x2d4],0; sete`
  makes the flag 1 in PLAY; a child with `[child+0xcc] != 0` is skipped only then); setter
  vfunc 35 0x48f3cb stores 0 for a value above 1. Attach 0x495bf6 walks +0x48 until the cast
  to `PivotNode` succeeds; 0x48f31f leaves the pivot parent null when the parent is the scene
  singleton. Sibling insert 0x48f556.
- Enabled 0x48e51d (bit 0 of +0x40, recursive); visible 0x48e028 (byte +0x55 AND the node
  behind the handle at +0x3c); 0x492b67 sets the handle to the nearest ancestor of class
  `PVSRootNode`; `Node::SetVisible` 0x48f69a only stores the byte and calls vfunc 27 (a bare
  `ret`, 0x48d561, for `Node` and `PivotNode`; `SubPivot` overrides it, 0x4996f1). During
  fragment instancing the load flag `[0xe15124]+0x31` is 1 (0x5473ee) and vfunc 14 skips the
  handle update; vfunc 29 sets it instead (0x49413d, 0x495bbe); when that runs after a load
  was not traced.
- SubPivot 0x4a5907 (find or create one per part i ≥ 1 by name, `pivotID` = i, rest pose
  unless byte +0x128; skipped when the ModelRes has `hasAnimation`, +0xe8: a model with an `.animation` of its own); `Model` vfunc 37
  0x49faaf draws a part only when its SubPivot passes 0x48dffd and 0x48e028.
- BaseModel constructor 0x4a8f99: `opacity` 1.0, `terrainAOGradient` 1.0, `geometryLodFactor`
  1.0, `geometryLodOverride` −1, `useConstantAO` false. LOD 0x49d00f (called from 0x573625,
  0x573d5d, 0x57435f): the override when +0x1c8 is not −1, else `geometryLodFactor` ×
  (distance − radius term) × scale into the threshold search 0x53a317. `Character` vfunc 37
  0x4ca09f needs `hasSkeleton` on the first ModelRes and waits until every listed ModelRes
  is loaded (0x4bea65).
- `CollisionNode` constructor 0x4a8944 (+0x14c = 1, +0x148 = 0, +0x189 = 0; book 0xa2f164
  `/pivotbooks/default.pb`); `SetPivotSheetID` 0x4a4c44; mask getter 0x48e154.
- Culling: `CullingBox.initialize_local` 0x70d525 writes `m_ecullinggroup` (hash 0x5f62b696,
  0x704f9b); `Culling` 0x70e0a4 runs only when the controller is enabled, from
  `command_viewport_render_begin` 0x70dba6, sent by `StateMain` 0x705138 each frame in game
  modes 1 and 4 (viewport 0) and 2 (viewport 1); hide / show 0x7052b9, 0x7054b8 (§13).
  Measured: 233 boxes on PC Part 2, every one a direct child of a `CullingGroup`.

### Track / TrackPoint, GeometryEffect, Wind, DecalManager (no instance in the level data)

- Track constructor 0x4b2ad4: `frameRate` (+0x198) 1.0; seven flags at +0x18c..+0x192 = 1,
  0, 1, 1, 1, 1, 0; the byte at +0x192 gives direction +1 when it is 0. Which property name
  has which offset is not established; neither are the segment formulas. No `Track` /
  `TrackPoint` in level scope (measured).
- GeometryEffect constructor 0x4be7f2: life 2.0 (0x9e663c), radius 5.0 (0x9e97fc), threshold
  0.02 (0x9e6170); flags 0, 0, 0, then 1 at +0x204, then 0. Update, matrix and draw: not
  established. No instance in level scope (measured).
- Wind constructor 0x49a53d: 1.0, 0.5, 0.5, 180.0 (0x9eb980), 0.5. The address of the
  singleton 0xe146bc occurs three times in the image, once in the constructor (0x49a5c3) and
  twice at 0x498461 / 0x498469 (measured by byte scan; that function was not opened). A
  reader that reaches a Wind node by reference or type query is not excluded. The update
  formulas are not established. No instance in the data.
- DecalManager constructor 0x4be917: 5 at +0x60, 2 at +0x64. No `DecalManager` or
  `GFXDecalEffectType` in level scope of either game; `GfxBlender` has 34 instances in Part
  1 (measured). Their function bodies are not established.

### Trigger, use-trigger, waypoint and level-flow classes

- Default exposure rule 0x5aa639: true iff the property name is `name`, `id`, `typename`,
  `script` or `enabled`. `TriggerActionGeneral` 0x85e3e8 and `TriggerActionParticle`
  0x86038f apply it to every property except `m_iactiontype` and `_bfireaction`;
  `TriggerUseFragment` 0x873568 sets enabled = (propertyinstance +0x10 != 0) instead (what
  +0x10 holds is not established). The per-type tables are `wlib/filter_exposed.json`.
- General run time 0x85f77b: types 10 and 11 dispatch to handler slots +0x64 and +0x68, both
  the empty 0x48d561; 12 jumps to the return; 17 and 18 write member +0x20 of the target,
  `TriggerUseFragment.m_tisfrozen`.
- Activator test 0x862e84 (types 0..6; 2 and 3 read the faction from the CharacterDef or the
  OnOffEnemies member; 6 compares the character type with 0x19). Volume entry 0x87b77a: the
  node "floor" is found on the trigger's parent; test floor y < character y − 0.2 (double
  0x9e97e8). Use 0x87d044: no distance, facing or button test; state 37 PullLever (types 5,
  9), 65 PullSwitch (10), 51 Lift (8), 44 SlideDoor (13, 14), 62 SqueezeUnder (1); type 0
  sends `command_fire_start_action` and `LockpickCtrl.command_activate_lockpick` and enters
  StateTrigger (68). Combat rule 0x695030: |enemy y − own y| < 2.0 (0x9e663c). Firing order
  0x880105, 0x879c07. Measured: 277 use triggers in PC Part 2 (types 3 ×91, 15 ×78, 13 ×31,
  14 ×31, 2 ×15, 10 ×10, 12 ×6, 0 ×3, 1 ×4, 8 ×4, 9 ×4); `m_tautoactivateplayer` false on
  all.
- Waypoints: `WayPointInit` 0x8b1062, `SetNextExclusiveCharacter` 0x8aa4e5,
  `command_delete_self` 0x8b2f41, `command_get_follow` 0x8b2f6c, selection 0x8b012b (nearest
  15, first 5 visible, 5 forward steps), `CanSee` 0x8b0988 (mask 0x200, offset (0, 1, 0) at
  0x9e807c), `IterateForward` 0x8b0da1, activation 0x8b3091 (a node already active stops the
  walk; a stopper node is set active and stops the propagation). Whether
  `StateInitAutoStart` 0x8aa1fb (state 17) runs is not established: no lifted class refers
  to it.
- `TriggerOscillateBox` 0x874b7a (disassembly 0x874cc7–0x874e0d): pow(2.0, −falloff·t) with
  base 2.0 at 0x9e663c; 2π as the double at 0xa0f220; gate 0.001 (0xaad40c); half angle
  +angle·0.5 (0x9e5dc8); first product with (0, 0, s, c) about Z using the X parameter set,
  second with (s, 0, 0, c) about X using the Z set, on the orientation read back from entity
  +0xb8. Impact 0x871b96: s = min(1, |contact force| / 10000) (double 0x9eb358); d = unit
  horizontal direction from the hitting actor to the node; `_nimpactforce` = −s·(d · node X
  axis), `_nimpactforcez` = −s·(d · node Z axis) (axes 0x9e806c, 0x9e808c); only an actor
  with a character root counts and one in the quarantine list is ignored.
  `command_reset_oscillation` 0x8718e6. `TriggerFireBarrelEffect` 0x874795: about X, then
  about Z with half angle −(`_vdirection.x`·angle)/2 (0x874a87); that the first factor is
  `_vdirection.z` is inferred. `PivotController` 0x7e70f8: type 1 adds
  `_vorientationoffset` and uses the up vector at 0x9e807c; the rest is not established.
- Conditions: Logical 0x86de58 (ANY count ≥ 1, ALL count = list length, SOME count =
  `m_icount` exactly; SOME occurs 17 times on PC); True 0x86f83e (repeats only when
  reactivatable and the parent has no property "m_tReactivatable"; with a delay ≤ 0 it sends
  `command_reset_trigger` without waiting); Visibility 0x873e94 (tests 1, 2, 6; 1.0 at
  0xc3cc48, 2.0 at 0xc3cc78, ray mask 4, 5.0 at 0x9e70a0); Character 0x8525fd (× 100, double
  0x9e5bd0).
- Stream blocks: `StreamBlockTrigger` 0x841c78 / 0x841d9d; `StreamBlockTriggerOneShot`
  0x847c78 (`cmp [edi+8],0; jne exit; mov [edi+8],1` at 0x847cb8: once; 20.0 s limit at
  0x9e66ac); `IsPlayableCharacter` 0x83a88c.
