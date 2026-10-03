# Ghidra scripts for the Kapow executable

Three Ghidra scripts and one table. They repair two things Ghidra's
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
| `DumpDecomp.java` | writes the decompilation as shard files plus an index |
| `handlers.tsv` | handler table read by `DefineKapowHandlers.java` (4,516 rows) |

## The two problems

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
2. `DefineKapowHandlers.java`
3. `FixEHProlog.java`
4. Let auto-analysis finish again. The re-bodied functions expose calls and
   references that analysis has not seen before; this is where most of the new
   functions come from.
5. Optionally `DumpDecomp.java`.

`DefineKapowHandlers` goes first so that the handlers exist as functions when
`FixEHProlog` looks for the function containing each `__EH_prolog` call.

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

analyzeHeadless PROJ_DIR PROJ -process KapowMultiDEDRM.exe -noanalysis -readOnly \
    -scriptPath tools/ghidra \
    -postScript DumpDecomp.java /path/OUTDIR
```

Without `-noanalysis`, headless mode analyses the changes a post-script made
before it saves, which covers step 4. The dump is run with `-noanalysis
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

Examples of what the repair recovers: `Node::Deserialize` 0x545927 goes from
10 to 1,220 bytes, the block loader 0x4a36d8 from 10 to 1,718, the property
registration function 0x47fde4 from 10 to 175.

The analysis pass after `FixEHProlog` is slow: in the run above the
"Non-Returning Functions - Discovered" analyzer alone took about 25 minutes on
two cores.

## Re-running

All three are safe to re-run.

- `DefineKapowHandlers` finds the functions it created, keeps every name that
  is no longer a default name (its own from the first run included), and does
  not add the comment twice.
- `FixEHProlog` finds the helper already named and fixed up, the
  fall-throughs already disassembled and the bodies already complete.
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
