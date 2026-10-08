# The builtin script module (`wlib/builtins.json`)

Scripts call a fixed set of engine functions and read a fixed set of engine globals that
belong to no node class: the builtin module. `BuiltinModule::RegisterMembers` (0x47ff8c,
`builtin.cpp`) registers all of them. `wlib/builtins.json` is that registration as a table;
`wlib/script_builtins.py` loads it.

## Counts (read from the code)

Every call in the routine was walked in the disassembly:

| What | Count |
|---|---|
| Functions (calls of 0x47f650: signature, handler, member name) | 123 |
| Distinct function names (`min`, `max` have a number and an integer form; `editor_reloadallassets` is registered twice) | 120 |
| Distinct handler bodies | 99 |
| Properties (calls of 0x47fe93: type object, name, getter, member name) | 19 |
| Registrations at the shared empty body 0x48d55e (`ret 4`) | 20 (19 names) |
| Registrations at the "return 0" body 0x4fa89c | 3 |
| Enum members (calls of 0x50574a) | 10 |

The empty body: `drawpoint drawline drawline2d drawsphere profilebegin profileend
startcleanupdashboard setscreenresolution editor_reloadallassets (twice) editor_selectnode
printnodeproperties create_newtabpanel create_newtabpanelbyname close_tabpanel
exists_tabpanel editorhelper_registertype RefreshSceneTree CreateEditorAction
CreateHotkeyBinding`. Two of these declare a return value (`exists_tabpanel`,
`CreateHotkeyBinding`); the body does not write the slot.

The "return 0" body: `geteditoractive`, `editor_numselectednodes`, `editor_getselectednode`.

Other shared bodies: `c_int` / `NumToInt` (0x47ae3b), `c_num` / `IntToNum` (0x47ae2f),
`getscreensize` / `getscreenresolution` (0x47bc19). `print` and `forceprint` are not stubs
by address, but both end in the logger 0x48d561, which is a single `ret` in this build.

## Other builds

The table is the PC Part 2 registration. The 139 `BuiltinModule::` member-name strings (123
functions, 19 properties, 3 names shared) are identical in X360 Part 2, PS3 Part 2 and PS3
Part 1. The X360 Part 1 image (retail and the devkit-signed build) has 133: it lacks indices 68
`SortPivotNodes`, 69 `getrenderpreferences`, 98 `create_newtabpanelbyname`, 99 `close_tabpanel`,
100 `exists_tabpanel`, 119 `InitPerformanceMeasurement`, 120
`RegisterPerformanceMeasurementCallback`, 121 `UnRegisterPerformanceMeasurementCallback` (member
and signature strings both absent), and adds `set_disc_error_message(entity,integer)`
(`SetDiscErrorMessageMSG`) and `disablecurrentloadscreen` (`DisableCurrentLoadScreenMSG`).
Measured on strings; the X360 Part 1 registration order and handlers were not read, so a
builtin index from this table is not valid for X360 Part 1 from index 68 on. PC Part 1 was not
examined. `builtins.json` carries this as `other_builds`.

## Calling convention

- A function handler is `thiscall(module, slot *args)`. `args` is one array of 4-byte
  slots: the return value first, then the arguments. A vector takes 3 slots, a quaternion
  4, a biginteger 2, everything else 1 (a string, entity, list or struct is a pointer).
  `findrotation(vector,vector):quaternion` reads its vectors at slots 4 and 7 and writes
  slots 0..3; `print(string)` has no return and reads slot 0.
- A property getter takes no slot array: number and integer getters return the value,
  entity getters return the pointer, vector getters write through an out pointer. The
  seven direction getters copy four words into that three-slot value.

## Type codes

| Code | Type | Slots |
|---|---|---|
| 0 | nothing | 0 |
| 1 | number | 1 |
| 2 | integer | 1 |
| 3 | biginteger | 2 |
| 4 | string | 1 |
| 5 | truth | 1 |
| 6 | vector | 3 |
| 7 | quaternion | 4 |
| 8 | color | 1 |
| 9 | netparticipant | 1 |
| 10 | list | 1 |
| 11 | dict | 1 |
| 12 | entity | 1 |
| 13 | struct | 1 |
| 14 | asset family | 1 |

## Enums and the struct

- `LANGUAGE`: `LANGUAGE___ENGLISH` 0, `FRENCH` 1, `ITALIAN` 2, `GERMAN` 3, `SPANISH` 4,
  `DANISH` 5. The member name is built as `"LANGUAGE___%s"` from the language name
  upper-cased by 0x410312.
- `PLATFORM`: `PLATFORM___EDITOR` 0, `PLATFORM___PC` 1, `PLATFORM___X360` 2,
  `PLATFORM___PS3` 3.
- No other enum is registered here.
- Struct `GameControllerInfo(productName:string,present:truth,type:integer)` and
  `list(GameControllerInfo)` (0x47cab9), the return type of `GetGameControllerInfoList`.

## The properties

`gametime realtime timepassed realtimepassed millisecondsSinceFrameStart pi
physicsTimePassed physicsRemainingTime` (number), `physicsNumTimesteps` (integer),
`in_vector out_vector right_vector left_vector up_vector down_vector zero_vector` (vector),
`scene annotate platform` (entity).

## The table

`format` `kapow-builtins/1`. Per function: `name`, `signature` (as registered), `args`
(`type`, `code`, `slot`, `slots`), `returns`, `arg_slots_total`, `member` (the
`BuiltinModule::...` string of the registration), `handler` (`pc`; `ps3` and `x360` where
known), `registration_site`, `stub` (`null`, `"empty"`, `"returns_zero"`),
`shares_body_with`, `semantics` and `semantics_evidence`. Per property: `name`, `type`,
`code`, `slots`, `type_object`, `member`, `getter`, `semantics`.

- `semantics` is one line on what the handler does. `semantics_evidence` is `read` when the
  line was read from the handler's decompilation or disassembly, here or in the two
  runtime passes before (141 entries) and
  `from name` otherwise (1: `dumptable_createfromfile`, read only in part). Where a `read`
  line also says what an argument means, that part is marked "from name" in the text.
- `handler.ps3` is the Part 2 PS3 address of the same registration, matched by the member
  name string (all 142). `handler.x360` is filled for 14 entries from the call-sequence
  pair table of the Xbox 360 Part 2 image; its confidence is copied, not re-verified.

## Which builtins the game's scripts call

Counted in the lifted script corpus (441 classes, shared bodies printed once per class; the
corpus is research output outside the toolkit, kept on the project PC under
`ghidra_kapow_out\engine\script_lifted_v2`):
1,340 call sites of 40 handler bodies, every one resolving to an entry. Most used:
`platform` 295, `CreateNode` 213, the empty stub 156, `rand_number` 125, `getplatformid`
125, `GetEnumMemberNameFromValueFormatted` 114, `DeleteNode` 66, `rand_integer` 29, the
"return 0" stub 29, `getframenumber` 21.

A call of the empty stub cannot be attributed to one builtin: the compiler emits a call to
the body, and 19 builtins and other natives share it. No handler of a math function is
called from a script handler (0 call sites); the runtime research found their bodies
inlined at the call.

## Use

```python
import script_builtins as sb
sb.functions("clamp")[0]["semantics"]     # 'clamp(x, lo, hi) = min(max(x, lo), hi)'
sb.slot_layout(sb.functions("CreateNode")[0])   # '[0]=ret:entity [1]:string [2]:entity'
sb.by_handler(0x47ae3b)                   # c_int and NumToInt
sb.enum_value("PLATFORM", "PS3")          # 3
sb.check()                                # [] when the table is consistent
```
