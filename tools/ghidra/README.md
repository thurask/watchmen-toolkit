# Ghidra scripts for the Kapow executable

Four Ghidra scripts and two tables. They repair three things Ghidra's
auto-analysis gets wrong on `KapowMultiDEDRM.exe` (32-bit x86 PE, image base
0x400000) and write the decompilation out as text. The research reports in
[`docs/re/`](../../docs/re/README.md) were produced from the result.

They need an executable whose `.text` section is not encrypted. The retail
build's is SecuROM-packed in place; this toolkit neither provides an unpacked
binary nor helps produce one. Nothing in `wlib/` needs these scripts: they are
for reading the engine, not for extracting assets.

| File | What it is |
|---|---|
| `DefineKapowHandlers.java` | creates and names the registered command handlers |
| `FixEHProlog.java` | repairs the functions truncated at the `__EH_prolog` call |
| `FixNoReturn.java` | clears wrongly inferred "does not return" flags and re-bodies the callers |
| `DumpDecomp.java` | writes the decompilation as shard files plus an index |
| `handlers.tsv` | handler table read by `DefineKapowHandlers.java` (4,516 rows) |
| `names2.tsv` | 5,036 further function names, same format, applied with `DefineKapowHandlers.java` |

Tooling built later and kept outside the toolkit (a gap sweep of the PC
executable, a Cell VMX addition for the PS3 executable, an Xbox 360 language)
is described at the end, under "Further tooling, 2026-10-06".

## The three problems

**Handlers that are not functions.** The engine registers script commands,
state functions and script methods by pushing a code pointer into a
registration call (`0x47eccc`, see `docs/ENGINE_CONSTANTS.md`). A handler that
nothing calls directly is reached only through that table, and Ghidra's
auto-analysis does not always turn it into a function: 1,191 of the 4,516
distinct handler addresses were not defined. Among them are functions the
notes used to
describe as "not in Ghidra": `AnimationCtrlWM.SetupNewPage` (0x5b7788),
`UpdatePagePlayPos` (0x5b56a9), `CharacterRoot.StateActive` (0x6b367a) and the
`CharacterAddonCtrl` setup and update (0x6574cd, 0x6563a0).

**Functions truncated to a stub.** MSVC's `__EH_prolog` helper (0x991850 in
this build) ends in `push eax; ret`. Ghidra reads that as "does not return to
the caller", so every function that opens with
`mov eax, handler; call __EH_prolog` stops at the call and decompiles to a
10-byte stub, `{ FUN_00991850(); }`. 2,000 functions were affected, among them
every file loader (`Node::Deserialize` 0x545927, the block loader 0x4a36d8) and
the registration functions themselves (0x47e126, 0x47fde4).

**Functions cut off at a call that "never returns".** Ghidra's "Non-Returning
Functions - Discovered" analyzer flagged eight functions of this build as
no-return although each of them contains a `ret`. Two matter: 0x47eccc, the
command-registration function every class's registration code calls once per
command, and 0x5a0dfd. A caller stops at its first call to a flagged function,
so each per-class registration function ended after its first command and the
rest of it was never disassembled.

## What each script does

### `DefineKapowHandlers.java`

Reads `handlers.tsv`. For each row it makes sure a function exists at the
address, names it, and adds a plate comment listing the registrations that
point at it.

- No function at the address: it disassembles there if needed (clearing a
  mistyped data run first, and as a second attempt the range from 8 bytes
  before to 32 bytes after the address), then creates the function.
- The address lies inside another function's body: it adds a label, reports
  the row, and leaves the outer function alone.
- Naming: only functions that still have a default name (`FUN_…`) are renamed.
  A name you chose yourself is kept. On a duplicate name the address is
  appended.
- The comment `Kapow handler: …` is added once; a function that already has
  it is not touched again.

It prints one summary line (`created`, `named`, `kept existing name`,
`inside another function`, `failed`) followed by one line per problem row.

### `FixEHProlog.java`

Optional argument: the helper's address in hex (default `991850`).

1. Checks that the bytes at the address are `6a ff 50 64 a1 00 00 00 00 50`.
   If not, it prints a message and changes nothing, so it is harmless on a
   different build.
2. Names the helper `__EH_prolog`, clears its no-return flag and attaches
   Ghidra's built-in `EH_prolog` call-fixup.
3. For every call to the helper: clears a flow override on the call
   instruction and disassembles the fall-through if it is not code yet.
4. For every function containing such a call: removes a function that
   analysis started directly after the truncated body, if that function has a
   default name and nothing references it; then rebuilds the body
   (`CreateFunctionCmd.fixupFunctionBody`).

It prints the number of calls, fall-throughs disassembled, functions
re-bodied, how many of those grew, and how many spurious starts were absorbed.

### `FixNoReturn.java`

Arguments: none or `auto`, or hex addresses.

1. `auto` collects every internal, non-thunk function that carries the
   no-return flag and has a `RET` instruction in its own body: flagged by
   inference, not by fact. With addresses it takes exactly those.
2. Switches the "Non-Returning Functions - Discovered" analysis option off for
   the program; left on, the analyzer sets the flags again during the analysis
   that follows.
3. For each target: clears the flag; for every call to it clears a flow
   override on the call instruction and disassembles the fall-through if it is
   not code yet (clearing a data run there first); then rebuilds the body of
   every calling function.

It prints one line per target: calls, fall-throughs disassembled, callers
re-bodied and how many of those grew.

### `DumpDecomp.java`

Arguments: `OUTDIR [ADDRLIST_FILE]`. Without a list it decompiles every
function that is neither external nor a thunk; with one (a file with an address
in hex at the start of each line) only those.

Output:

- `OUTDIR/decomp/part_NNNN.c` — shards of about 1.5 MB. Each function is
  preceded by a header with its name, entry address, size, up to 40 callers,
  up to 60 callees, and its plate comment (so the `Kapow handler:` line of
  `DefineKapowHandlers` appears there).
- `OUTDIR/index.tsv` — `address, name, size, n_callers, n_callees, part`.

Decompilation has a 120-second limit per function; a failure is written as a
`/* DECOMPILE FAILED: … */` comment in place of the code. Unlike the other two
scripts it needs its first argument, so run it headless or pass script
arguments explicitly.

## Order

1. Import the executable and let auto-analysis finish.
2. `DefineKapowHandlers.java` with `handlers.tsv`
3. `FixEHProlog.java`
4. `FixNoReturn.java`
5. Let auto-analysis finish again. The re-bodied functions expose calls and
   references that analysis has not seen before; this is where most of the new
   functions come from.
6. `DefineKapowHandlers.java` with `names2.tsv`
7. Optionally `DumpDecomp.java`.

`DefineKapowHandlers` goes first so that the handlers exist as functions when
`FixEHProlog` looks for the function containing each `__EH_prolog` call.
`FixNoReturn` comes after `FixEHProlog` because the registration functions it
repairs are themselves `__EH_prolog` functions, and `names2.tsv` comes last
because many of its addresses only become functions in steps 3 to 5.

## Running

**Script Manager.** Add this directory to the script directories (Script
Manager → *Manage Script Directories*), then run the scripts from the `Kapow`
category. `DefineKapowHandlers` asks for `handlers.tsv`. Wait for the analysis
indicator to go idle after `FixEHProlog`.

**Headless.**

```
analyzeHeadless PROJ_DIR PROJ -process KapowMultiDEDRM.exe \
    -scriptPath tools/ghidra \
    -postScript DefineKapowHandlers.java /path/handlers.tsv

analyzeHeadless PROJ_DIR PROJ -process KapowMultiDEDRM.exe \
    -scriptPath tools/ghidra \
    -postScript FixEHProlog.java

analyzeHeadless PROJ_DIR PROJ -process KapowMultiDEDRM.exe \
    -scriptPath tools/ghidra \
    -postScript FixNoReturn.java

analyzeHeadless PROJ_DIR PROJ -process KapowMultiDEDRM.exe \
    -scriptPath tools/ghidra \
    -postScript DefineKapowHandlers.java /path/names2.tsv

analyzeHeadless PROJ_DIR PROJ -process KapowMultiDEDRM.exe -noanalysis -readOnly \
    -scriptPath tools/ghidra \
    -postScript DumpDecomp.java /path/OUTDIR
```

Without `-noanalysis`, headless mode analyses the changes a post-script made
before it saves, which covers step 5. The dump is run with `-noanalysis
-readOnly` because it changes nothing. For a first import use `-import
KapowMultiDEDRM.exe` in place of `-process …`.

## Measured results

Ghidra 12.1.4, `KapowMultiDEDRM.exe`, 2026-10-02.

| Step | Result |
|---|---|
| `DefineKapowHandlers` | 1,191 functions created, 4,516 named, 0 inside another function. The first run created 1,190 and reported that 0x7bfffe did not disassemble; the wider clear-and-retry was added for that address and a second run created it (and kept the 4,515 existing names) |
| `FixEHProlog` | 2,040 calls to the helper, 2,038 fall-throughs disassembled, 2,000 functions re-bodied (all 2,000 grew), 2 spurious function starts absorbed |
| Functions in the program | 16,369 after `DefineKapowHandlers` → 17,225 after `FixEHProlog` and the analysis that follows it |
| Functions of 12 bytes or less | 2,473 → 622 |
| `DumpDecomp` | 17,225 functions in 21 shard files |

Added 2026-10-03, same Ghidra and executable, continuing from the state above:

| Step | Result |
|---|---|
| `FixNoReturn` | 0x47eccc, given by address in a first run: 443 calls, 443 fall-throughs disassembled, 441 callers re-bodied, all 441 grew. `auto` then found 7 more flagged functions that return. 0x5a0dfd: 762 calls, 373 fall-throughs disassembled, 390 callers re-bodied, all 390 grew. The other six (0x993e8e, 0x993fae, 0x99631f, 0x996330, 0x999275, 0x9a5f3f) have 30 calls together; 12 of their callers grew |
| Functions in the program | 17,225 → 19,233 |
| Bytes inside function bodies | 4.62 MB → 5.77 MB: about 1.1 MB of code, most of it the per-class registration functions, was outside any function before |
| `DefineKapowHandlers` with `names2.tsv` | 5,036 names |
| `DumpDecomp` | 19,233 functions in 26 shard files |

Examples of what the repair recovers: `Node::Deserialize` 0x545927 goes from
10 to 1,220 bytes, the block loader 0x4a36d8 from 10 to 1,718, the property
registration function 0x47fde4 from 10 to 175.

The analysis pass after `FixEHProlog` is slow: in the run above the
"Non-Returning Functions - Discovered" analyzer alone took about 25 minutes on
two cores.

## Re-running

All four are safe to re-run.

- `DefineKapowHandlers` finds the functions it created, keeps every name that
  is no longer a default name (its own from the first run included), and does
  not add the comment twice.
- `FixEHProlog` finds the helper already named and fixed up, the
  fall-throughs already disassembled and the bodies already complete.
- `FixNoReturn` finds no flagged function left (`auto`), or finds the flag
  already clear and the fall-throughs already disassembled.
- `DumpDecomp` overwrites its output.

## `handlers.tsv`

Tab-separated, no header, one row per distinct handler address:

```
address (hex, no 0x)   name   defined-before flag   registrations
```

- **name** — `Class__command` when one class registers the address,
  `shared__command` when several classes register the same command name on it,
  `shared_handler_<addr>` when several different commands share one body
  (0x48d561, an empty stub, has 477 registrations).
- **third column** — 1 if Ghidra already had a function at the address when
  the table was made (3,325 rows), 0 if not (1,191 rows). The script ignores
  it.
- **registrations** — `Class.command; Class.command; …`, cut off after twelve
  with a `(+N more)` count.

The table derives from `wlib/reg_dump.json`: the 4,516 addresses are exactly
the distinct `handler` values of its 6,630 command records (slots `command`,
`state` and `method`). `reg_dump.json` is regenerated with
`watchmen gendata regdump EXE`; the addresses belong to this one build.

## `names2.tsv`

Same four columns as `handlers.tsv`, 5,036 rows, for functions that are not
registered command handlers: virtual methods placed by RTTI
(`Voice_XAudio2__vfunc_02`), and functions named from the subsystem map of the
engine, and the 28 functions of the Kynapse bridge named from their role
(`KynapseSkel_RayBlocked`, `AIBrainNode__CreateAIEntity`). The fourth column starts with a confidence and says where the name
comes from: `high` (2,278 rows) or `medium` (2,758 rows; for example "class
membership read from RTTI, method meaning not established").
`DefineKapowHandlers.java` writes that text into the plate comment, so it
appears in the header `DumpDecomp` puts above each function. As with
`handlers.tsv`, only functions that still have a default name are renamed.

## Further tooling, 2026-10-06 (kept outside the toolkit)

Three pieces of research tooling were built after the scripts above. They are
not in this folder: they hold compiled Ghidra language files for one Ghidra
version, packed programs of 50 to 114 MB and decompiled text. They are kept on
the project PC under `E:\Claude\HeyClaude_WatchmenPart2\ghidra_kapow_out\`;
each folder has a `README.txt` (the console ones also a `README_PC.txt`), and
the packed programs are split into `.partNN` files with a `*_JOIN.txt` that
gives the join command, the size and the SHA-256. Nothing in `wlib/` needs any
of it.

| Folder under `ghidra_kapow_out\` | What it is |
|---|---|
| `engine\gap_sweep\` | sweep of the bytes between the dumped functions of the PC executable; the recovered functions, decompiled |
| `ps3_p2\lang_cell\` | the three Cell VMX instructions Ghidra's PowerPC language lacks, for the PS3 executable |
| `x360_p2\lang_vmx128\` | a Ghidra language for the Xbox 360 CPU (VMX128), and the functions re-decompiled with it |

### `engine\gap_sweep\` — what lies between the 19,233 functions

Measured on `KapowMultiDEDRM.exe` (`.text` 0x401000–0x9e440b, 6,173,707 bytes;
function bodies after the repairs above 5,766,025):

| Gap component | Bytes |
|---|---|
| Real code | 324,616 |
| – tails of 21 existing functions (18 substantive) | 93,444 |
| – 16,318 functions the dump never had | 229,983 |
| – 41 fragments of existing functions (SEH blocks, CRT internals) | 411 |
| – 79 alignment-nop runs, 20 dead tails after no-return calls | 778 |
| Jump tables (dword) | 39,248 |
| Switch index tables (byte) | 5,069 |
| Padding | 32,144 |
| Not classed by the sweep | 6,605 |
| Total | 407,682 |

- Of the 16,318 new functions 13,576 are C++ unwind funclets, 1,219
  frame-handler stubs and 1 a catch block; 422 are virtual functions named
  from RTTI; 28 are registered command handlers (156 registrations). An unwind
  funclet decompiles against its parent's EBP frame: read it only as "which
  destructor runs on which local".
- The 28 handlers are 0x598a5a, 0x59d825, 0x614c00, 0x614c9c, 0x614d38,
  0x61bba2, 0x676574, 0x69ed29, 0x6a1b09, 0x6d910d, 0x704e77, 0x738a6c,
  0x73b943, 0x73b97c, 0x75b9a9, 0x770cfc, 0x77c09d, 0x788e97, 0x788ec0,
  0x7bfcda, 0x7f0655, 0x7f0690, 0x7f06a2, 0x8127b5, 0x83c526, 0x83ffea,
  0x84a3b2 and 0x87b96e. All 28 are rows of `handlers.tsv` and `handler`
  values of `wlib/reg_dump.json` (156 command records; counted): those tables
  are read from the registration calls, so they never depended on the
  function list. Only the functions were missing. They were present in the
  first dump and in none after it.
- Why they were lost: once 0x47eccc carried the no-return flag, Ghidra's
  no-return repair (`ClearFlowAndRepairCmd` with clearData, labels kept)
  cleared the code after the first registration call in 49 register functions
  that were whole, and with it every handler whose only references came from
  cleared code (62 handlers; measured: 42 have a registration site in those
  functions, the sites of the other 20 were in no function body). Later runs
  applied `names2.tsv`, which has no handler rows. 34 handlers whose entry is
  `55 8B EC` (32) or `56 8B 74 24` after a `ret` (2) were found again; the 28
  others were not (inferred: function-start search). Remedy: re-run
  `DefineKapowHandlers.java` with `handlers.tsv` after any run that changes
  no-return flags.
- 0x87b96e, behind 86 registrations (35 of them
  `*.command_is_behavior_running`, 11 `command_condition_true`; counted in
  `wlib/reg_dump.json`), is `*out = 0; ret`. 0x69ed29 (5 registrations, among them
  `CharacterVisual.command_is_in_ragdoll_mode`) returns self-data
  `[+0x10]->[+0x14]`. Both read from code.
- The 21 functions with a short body (9 `*__register` functions and 12
  others, among them `CharacterRootLogic__command_animation_event_received`
  0x6a525e, +2,951 bytes) are not cut by a no-return flag. In 15 of them a
  bogus instruction, disassembled from a "pointer" that is really a 4-byte
  string tail or a table entry, blocks the real one; one is blocked by a
  bogus string over code; two have a switch that was not recovered. The
  decompiled C of 19 of the 21 is the same as in the dump but for 0 to 13
  lines (the decompiler follows the bytes itself); the size, the callee lists
  and the callers of everything called from the tails were wrong. 1,172
  dumped functions gain at least one caller from recovered code, so their
  caller counts in the dump are too low.
- `ApplySweep.java` applies the fix to a copy of the program: functions
  19,291 → 35,601 (thunks included), body bytes 5,766,025 → 6,089,447, no
  overlap, no other existing body changed. `DumpDecomp3.java` raises the
  decompiler payload limit, which is what makes `FUN_0081c5f5` decompile.
- In the folder: `decomp_new\` (16,309 functions in the dump format; one
  CRT fragment failed), `decomp_fixed\` (the 21), `sweep_index.tsv` (one row
  per new function: address, name, kind, size, subsystem, parent, reachable
  from handlers), `sweep_tables.tsv` (417 jump tables), `fn_new.py` (prints a
  function, like the dump reader), `swp.py` (says what any `.text` address
  is), `ghidra_scripts\`, `apply_inputs\`, and the fixed program as
  `KapowMultiDEDRM_v4_sweep.gzf.part01..03` (an x86 program; it needs no
  extra language).
- Not established: "reachable from handlers" is a lower bound (indirect
  calls are not followed); the 82 unreferenced and 170 table-referenced
  functions were accepted on decode plausibility only; 4,800 bytes at
  0x97d420 / 0x97d6f0 (inferred: DirectInput data formats) and 1,735 bytes at
  0x9a247a (inferred: CRT assembly) are not code the sweep could class;
  `FUN_00908ac0` still decompiles with "could not recover jumptable".

### `ps3_p2\lang_cell\` — PS3 (Cell) executables

Import with `PowerPC:BE:64:A2ALT-32addr`. Stock Ghidra 12.1.4 lacks the Cell
VMX instructions `lvlx` (31/519), `stvlx` (31/647) and `stvrx` (31/679); each
stops disassembly. The folder holds `cell_vmx.sinc`, the `.slaspec` that
includes it (and its diff against the stock file), the compiled `.sla`, and
`P5opsRepair.java`. Install the three language files into a copy of Ghidra,
then run `P5opsRepair.java` once on an existing project. On the PS3 Part 2
program (measured): 283 → 1 bad-instruction bookmarks, 207 functions
completed (none created or removed), `.text` decoded 97.73 % → 98.64 %. A
repaired project must not be opened with the stock language.

- Raw word scan of the executable sections: `lvlx` 239 / 226, `stvlx` 116 /
  116, `stvrx` 116 / 116 (Part 2 / Part 1); `lvrx` and the `l` forms 0.
- None of the 207 is a model, texture or sound loader: of 326 functions
  selected by class name or by a loader-type string, two overlap (both debug
  camera tools) and the other 324 decompile identically. A loader with
  neither a class name nor such a string would not be in that set.
- The encodings and semantics are written from memory of the Cell VMX
  documentation, not looked up. `lvlx`, `stvlx` and `stvrx` are corroborated
  by coherent disassembly at all 469 decoded sites; `lvrx`, `stvlxl` and
  `stvrxl` are test-decoded only. `lvlxl` and `lvrxl` are not defined (their
  patterns clash with two embedded-PowerPC instructions of the stock file).
- Only 531 functions were re-decompiled; a full re-dump was not made, and
  the Part 1 executable was word-scanned only. The repaired program is
  `kapowmulti_ps3_p2_cellvmx.gzf.part01..06`.

### `x360_p2\lang_vmx128\` — Xbox 360 image: the Xenon language

Language id `PowerPC:BE:64:Xenon`, built for Ghidra 12.1.4
(`PowerPCXenon\`, also as `PowerPCXenon_ghidra_12.1.4.zip`), with its
generator (`build\`), self-tests (`tests\`) and scripts (`ghidra_scripts\`).

- Switching an existing program, in this order: `ExportState` → `SwitchLang`
  → `FixBad` → `XenonMillicode` → `ExportState`. **Set Language deletes the
  "Bad Instruction" bookmarks**, so export the sites first. For a new import
  give `-processor PowerPC:BE:64:Xenon -cspec default` from the start and run
  `XenonMillicode.java` after the naming step.
- Measured on the Xbox 360 Part 2 image: bad-instruction sites 3,553 → 180
  (none left on a VMX128 opcode; 171 are XEX import records, 9 zero words
  after a no-return call); `.text` covered by instructions 86.4 % → 98.0 %;
  all 6,576 names and 7,088 plate comments kept. Of the 2,049 functions that
  stopped at bad data, 1,865 decompile clean in the batch and one more with
  a 900 s limit; 182 still stop on import records or padding;
  `CharacterRoot__StateActive` (0x82e62d30) did not finish.
- Evidence. Encodings: all 114,762 VMX128 words inside the 40,286 `.pdata`
  functions decode with an independent table, and Ghidra agrees with that
  table on 48,334 test words (measured). P-code: 1,942 single-instruction
  emulator cases match Python models (measured). The opcode table and the
  operand roles are recalled from assembler and emulator sources, not from a
  document; the emulator test proves that the p-code matches that model, not
  that hardware does. Not established: `vmaddcfp128` roles, `vsel128` mask
  direction beyond plausibility, `vcmpbfp128`, the cr6 bits, the D3D pack
  type names.
- **Read before trusting the C: stale stack reads.** When a stack slot is
  accessed through a register holding its address, a read can be linked to
  the slot's value at function entry; it shows as a stack variable copied at
  the top of the function before it is ever assigned. It reproduces with
  stock scalar instructions and is a Ghidra limit, not fixed. The tell-tale
  pattern occurs in 331 of the 2,049 re-decompiled functions (a text
  heuristic, `tests\hoist.py`; three checked by hand). In those, trust the
  listing for values that travel through stack temporaries.
- One result for the toolkit (measured on the image): engine code has no
  CPU-side packed-vertex decode. The platform range 0x82a30000–0x82a38800
  (texture, vertex, index and shader buffer code) contains no `vupkd3d128` /
  `vpkd3d128`; in the whole image 10 functions use a real D3D element type
  (the two large ones called only from library code, inferred: D3DX). Vertex
  and texture payloads go to the GPU unconverted, as read before.
- In the folder: `decomp\halted_2049\` (the 2,049, with `status.tsv`),
  `decomp\twins_named\` (38 Xbox 360 twins of PC functions these documents
  cite, the model loader `ModelRes__vfunc_17` 0x82902400 among them),
  `decomp\platform_x360\` (162 functions), and the switched program
  `KapowMulti_x360_p2_xenon.gzf.part01..04`, which opens only where the
  language is installed. The older Xbox 360 dump beside it was not redone
  with the language; only the Part 2 retail image was processed, headless.

### What still needs the running game

- Dead code. Neither the decompilation nor a Direct3D capture can prove a
  function dead; that needs a coverage trace of the running game, which was
  not made. What the gameplay captures give at render level (measured on
  two traces, 23,530 frames): 33 distinct pass names ran; no `Refractions`
  and no `Shadowmap` pass ran.
- Two debugger reads are open: the float at 0xd91bf8 (0.0 by inference, see
  `docs/ENGINE_CONSTANTS.md`) and whether anything writes the language
  override (`docs/TEXT_ASSETS.md`).
