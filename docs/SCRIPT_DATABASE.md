# The script name database (`database.bin`)

`wlib/script_database.py` reads the file the engine loads as its "script database for use
in baked scripts": the list of every script property (`name:type`) and every script message
(command signature) of the game. It is where the names behind the 32-bit keys of
`.fragment` files come from.

## Where it is

| Set | Path | Bytes | Properties | Messages |
|---|---|---|---|---|
| Part 2, PC (identical on Xbox 360 and PS3) | `data_baked/tnt/production/database.bin` | 174,824 | 3,693 | 1,672 |
| Part 1, PC (identical in the Xbox 360 retail set) | same | 161,482 | 3,410 | 1,551 |
| Part 1, PS3 | same | 161,548 | 3,410 | 1,552 |
| Part 1, Xbox 360 devkit build (`XBLA_DEBUG`) | same | 161,452 | 3,409 | 1,551 |

All four parse to the last byte. The three Part 1 files hold the same properties except
`_iglowforplayable:integer` (absent from the devkit build); PS3 Part 1 has one message more,
`particlesystemeventex(integer,integer,integer,vector,integer)`.

The engine asks for `/data/tnt/production/Database.bin`; 0x4ef41c remaps the path under
`/data_baked` (call at 0x820e5b).

## Layout

Read from the loader 0x47c5f5:

```
u32 nProperties
nProperties x { u32 len; char text[len] }     "name:type"
u32 nMessages
nMessages   x { u32 len; char text[len] }     "signature" or "signature:returntype"
```

- `len` counts the terminating NUL (data: every entry of the four files ends in one).
- The loader refuses an entry with `len + 1 > 0x3ff` (unsigned), so the largest length is
  0x3fe. The reader applies the same limit to both sections.
- The words are little-endian in all four files, the two console files included. The
  reader still detects the order (the one that walks the file to its exact end).
- Nothing follows the last message.

The id of an entry is the engine name hash of the text before the first `:` (0x423d30,
used by the property constructor 0x4edfa4 and the message constructor 0x4ef571):
`kapow_props.name_hash`. For a message that is the signature before the `:`, argument list
included and return type excluded: `name_hash("command_lock_player(entity)")`. No two entries of a file share an id.

### Run-time property record

Property record, 0x18 bytes (`ScriptClass_RegisterProperty` 0x47fde4): +0 flags, +4 type-table
entry, +8 name descriptor (its +0x18 is the type object), +0xc slot index (byte offset = index
× 4), +0x10 default string, +0x14 UI string. Instance creation 0x47dfed parses the default into
the slot (type virtual +0x24, via 0x47a9de) or, with no default, default-constructs it (virtual
+0xc).

## What the names look like

- Property names are stored in lower case. Of the 3,693 Part 2 names none has an upper-case
  letter, so the database cannot settle the letter case of a name: 54 names of
  `prop_hash_dict.pkl` differ from it in case only (`m_iPriority` against `m_ipriority`);
  all 54 mixed-case spellings are strings of the executable.
- Message signatures are lower case too. Only a return type keeps a capital (`:Entity`,
  `:list(Entity)`); 504 of the 1,672 Part 2 messages carry a return type.
- Types (Part 2): number 1,028, Entity 842, truth 653, integer 521, list(Entity) 173,
  vector 166, list(integer) 58, string 58, then 68 rarer ones (lists of lists, script
  structs such as `MicroPage`, `list(RagdollMuscleStruct)`).

## Against the toolkit's tables

| Table | Result (Part 2 database) |
|---|---|
| Fragment key table (`kapow_fragment.NAMES`) | all 3,693 ids present, same spelling and same type; the table has 1,750 more ids (native properties) |
| `reg_dump.json` script properties | 5,087 of 5,090 rows equal; `volume` (2 rows) and `interval` are not in the database |
| `reg_dump.json` command signatures | 3,721 of 3,939 rows found; 100 rows (78 signatures) differ in letter case only; the 218 others are native callbacks (`FilterExposedProperties`, `script_construct`, `StopModeUpdate`, ...) |
| `prop_hash_dict.pkl` | 422 equal, 54 case-only, 0 different; 3,217 database names are not in it |
| `registered_names.json` (native names) | no id in common: the database holds script names only |

Part 1: 19 of its 3,410 properties are not in the Part 2 table apart from the seven below
(`_nnextvisualupdate`, `_nforceblocktime`, `_tforceblock`, `_ebrainlessautotargetbehavior`,
`_ehudnode`, `ilastmove`, `_tissteppingaside`, `_etestbox`, `_ngamma_adjustment`,
`_tunderbosshud`, `m_currentsettings`, `_etempfolder`, `_issuedattacksweetspot`,
`_thackmovepivotifnotreachabletried`, `m_tinrageuberdamagefactor`,
`_nsecondsbetweenvisualupdates`, `_eunderbosshud`, `m_etest`, `_esoundctrl`). No unknown key is left in
the Part 1 exports, so none of them occurs in a fragment.

### The seven Part 1 fragment keys

All seven are in the three Part 1 databases with exactly the spelling and type the toolkit
uses, so none is an inferred spelling any more:

| Key | Name | Type |
|---|---|---|
| 0x0cdb31bf | `_nobstructionfactor` | number |
| 0x57a8be19 | `_idebugrunthroughmode` | integer |
| 0x40cb4063 | `_tdebugtmp01` | truth |
| 0x56eec9bf | `_nsteplengthinmeters` | number |
| 0xf89f0453 | `_ntimeprstepinsec` | number |
| 0xb29cf82f | `_tstartenabled` | truth |
| 0xceacaed4 | `_tuseteleport` | truth |

## Use

```
watchmen scriptdb database.bin [OUT.json] [--find KEY_OR_NAME ...]
python3 wlib/script_database.py database.bin [OUT.json] [--find KEY_OR_NAME ...]
```

prints the counts, the byte order, the type histogram and whether the file was consumed
exactly (exit status 1 if not), looks up hashes (`0x40cb4063`, `key_40cb4063`) or names in
both sections, and writes the whole database as JSON (`format`
`kapow-script-database/1`: `properties[{index, name, type, hash}]`,
`messages[{index, text, name, args, returns, hash}]`).

In Python: `script_database.load(path)`, `parse(bytes)`, `lookup(db, key)`,
`type_histogram(db)`, `compare_names(db)` (against `kapow_props.namedict()` or any
`{hash: spelling}` table), `build(props, messages)` for test data.

Eight bare hex digits given to `--find` / `lookup` are read as a hash first and, when no
entry has that id, hashed as a name.

## Related, outside the toolkit

- `TOD_tools/database.bin` on the project PC (193,479 bytes) is not a Watchmen file: it
  belongs to a third-party tool repository for another Kapow game. It parses to its last
  byte with the same layout (5,283 properties, 1,410 messages), which supports the layout.
- The lifted script corpus that uses these names and the builtins table
  ([BUILTINS.md](BUILTINS.md)) is research output and not part of the toolkit. Its second
  version is on the project PC under `ghidra_kapow_out\engine\script_lifted_v2` (441 `.c`
  files, `_README_v2.txt`, `_rules_v2_stats.json`); the lifter and its rule files are beside
  it under `ghidra_kapow_out\engine\engine_notes\tooling_2026-10-05`.
