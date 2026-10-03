# Name tables: command hashes, property names, fragment keys

Tables: `names_commands.json` (hash -> name/hashed string/classes/handlers/sites),
`names_commands_sites.json` (all 6,630 registrations re-decoded), `names_props.json`
(every registered property hash -> name), `names_fragment_keys.json` (fragment keys
newly named + the 480 keytable corrections). Scratch + scripts: `work/names/`.

Every name in the tables was checked: `kapow_hash_df(hashed_string) == stored hash`
(asserted in `work/names/emit.py`). The hashed string is given per entry.

## 0. The root cause of most gaps: our `kapow_hash` folds case wrongly

**Read from code.** The engine's string hashers do not uppercase; they AND every
byte with 0xDF:

- `FUN_00423ce8` (hash a NUL-terminated string): `and cl,0xdf` @0x423cf7 and
  @0x423d23, poly `xor esi,0x4c11db7` @0x423d12.
- `FUN_00423d30` (same, but stops at NUL **or ':'**): `and cl,0xdf` @0x423d3f /
  @0x423d6a, `cmp dl,0x3a` @0x423d71.
- `FUN_00423d7c` / `FUN_00423ca1` hash raw bytes with a length and no fold
  (block-version checksum 0x49db60, MusicPlayer cue points 0x7cfccb) - not used
  for names.

`b & 0xDF` equals `upper()` only for letters and `_`. It differs for every other
character: digits `'0'..'9'` -> 0x10..0x19, `'('` -> 0x08, `')'` -> 0x09,
`','` -> 0x0C, `':'` -> 0x1A, space -> 0x00. `kh.py` and
`wlib/kapow_props.kapow_hash(s.upper())` are therefore wrong for any name that
contains a digit or punctuation. Correct reference implementation:

```python
def kapow_hash(s):
    crc = 0
    for byte in s.encode("latin1"):
        byte &= 0xDF
        for bit in range(8):
            neg = crc & 0x80000000
            crc = ((crc << 1) & 0xFFFFFFFF) | ((byte >> bit) & 1)
            if neg: crc ^= 0x04C11DB7
    return crc
```

Confirmation on data (not only code):
- 480 `kapow_fragment_keys.pkl` keytable entries have digit-bearing names filed
  under the `upper()` hash. None of those 480 stored hashes occurs anywhere in the
  exe's property registrations; re-hashed with &0xDF, 391 of them hit registered
  property hashes exactly.
- In the 906 extracted `.fragment` files, none of the 480 names was ever parsed
  under its stored hash; after re-hashing, 321 of them parse, 227,441 occurrences
  (section 3).
- This also closes the open item in ENGINE_CONSTANTS.md ("hash pairs
  0xee2a40XX/0x4cadfbXX differ per digit; keep key_XXXX"): they are
  `m_nsupersynclocal1..8` / `m_nsupersyncremote1..7`.

## 1. Commands

### 1.1 What 0x47eccc stores (read from code)

`FUN_0047eccc(name, kind, arg3, hash, cmdHandler, stateHandler, methodHandler, typeIdx)`
(thiscall, ecx = class; source file string "kernel/script/interface/scriptbaked.cpp").
It allocates a 0x38-byte record and writes: name string at +0, `kind` +0x10,
`arg3` +0x14, **hash +0x18**, args 5/6/7 at +0x1c/+0x20/+0x24, and
`DAT_00c89ebc[typeIdx]` at +0x28. The record ctor `FUN_0047ddc3` defaults +0x10=3,
+0x14=-1, +0x18=`DAT_00a22e34` (bytes at 0xa22e34 = FF FF FF FF), handlers 0.

The reg_dump field `argc` is not an argument count - it is `kind` (only values 1
and 3 occur; `command_set_achievement_earned(integer)` has 3, so does `_root`).
What `kind` and `arg3` mean is **not established** (arg3 is 0 for 3,053 commands,
a small integer for 886, -1 for all non-commands).

Re-decoding all 6,630 call sites with register tracking (`push 3; pop ebx`,
`or ebp,-1`, `xor esi,esi` etc. resolved) gives exactly three shapes:

| handler in | hash | count | names |
|---|---|---|---|
| arg5 (+0x1c) | real hash | 3,939 | `command_*`, `initialize_local`, `FilterExposedProperties`, ... |
| arg6 (+0x20) | -1 | 841 | `_root` (441), `StateActive`, `StateMain`, `Main`, ... |
| arg7 (+0x24) | -1 | 1,850 | `Init`, `PrepAttack`, `GetDef`, ... (script-local methods) |

### 1.2 Is a null hash a gap? No (read from code)

- All 2,691 null-hash sites push a literal/register -1 for both arg3 and arg4,
  i.e. the same 0xFFFFFFFF the ctor uses as "none".
- The by-hash senders refuse that value: `FUN_004f99a4` @0x4f99a8
  `cmp eax,[0xa22e34]; je ret`; `FUN_004ee0e7`/`FUN_004ee289` return -1 when a
  name's hash is not registered. `FUN_0047c9fd` (behind `FUN_00596d91`)
  dispatches only if `record[index]+0x18 == hash` (@0x47ca23-0x47ca26).
- Null hash coincides 1:1 with the handler sitting in the state or method slot.

So state functions and script methods are not addressable by hash and are not
gaps. reg_dump has 2,696 nulls; 5 of those are dumper misses (section 4).

### 1.3 How command hashes are formed

**Rule (established by exact reproduction of all 1,696 distinct hashes; hasher read
from code):**

1. Command with no parameters: `hash = kapow_hash("<cpp name as registered>")`,
   including the `command_` prefix. 866 distinct hashes / 2,305 registrations.
   (The "name without `command_`" variant in the task description never occurs.)
2. Command with parameters: `hash = kapow_hash("<name>(<type>,<type>,...)")` -
   parentheses, comma-separated, no spaces, no return type, &0xDF fold.
   830 distinct hashes / 1,634 registrations. Overloads get distinct hashes
   (`command_init` has 5, `command_update` 4).

The three examples:
- 0x6eed1060 = `command_set_achievement_earned(integer)`
- 0x13a9d763 = `command_is_achievement_earned(integer)`
- 0xeee497d4 = `command_game_event(integer,entity,integer,number,entity)`
- (most common) 0x286b9e96 = `FilterExposedProperties(list(propertyinstance))`

Why the earlier brute force failed: it hashed with `upper()`, which keeps
`( ) ,` as 0x28/0x29/0x2C instead of 0x08/0x09/0x0C.

Code evidence for the format (**read from code** for the hasher and the
signature syntax, **inferred** that the offline script compiler used the same
routine, since no run-time code builds a command signature - the hashes are
compile-time constants in baked script code, e.g. `FUN_004f99a4(0x6eed1060,&arg)`
in part_0006.c):
- `FUN_00423d30` hashes up to ':' - exactly "signature without return type".
  Callers `FUN_004ee0e7`/`FUN_004ee289` look the result up in the global message
  table `[0xe15130]` (`FUN_004ec992`); literals passed include
  `"minrange:number"`, `"enableobstructionandocclusion:truth"`, `"editor_play"`.
- Native script functions are registered by `0x47f650(sig, handler, doc)` with
  strings in the same syntax: `"GetAsset(string,string):entity"` (0x9f5de4),
  `"crc32(string):integer"` (0x9f6144), `"getmessageid(string):biginteger"`;
  0x47f650 splits off the part after ':' (`push 0x3a` @0x47f6a8).
- All struct type names found in signatures exist as lowercase strings in the
  exe's type-name area (`sounddefinstance` 0xa8d720, `cameracharacterstate`
  0xa8da50, `comboitemstruct` 0xa8dc30, `list(comboitemstruct)` 0xa8dc40).

Type vocabulary seen (uses): entity 508, integer 322, number 196, truth 100,
vector 67, string 29, quaternion 13, `list(T)` 18, and structs
physicscontactinfo, bankstruct, comboitemstruct, takeahitstruct,
characterdamagestruct, cameracharacterstate, combatcutdata, effectinstance,
audiosettingssoundstruct, chunkstruct, propertyinstance, forcedstatedata,
enemystruct, aipathobjectinfo, gfxnodeproperties, forceinfo, sounddefinstance,
speakdefstruct. Type-name case cannot be recovered (the fold erases it); tables
show lowercase.

Handler argument layout follows the signature: one 4-byte slot per argument
except vector = 3 slots, quaternion = 4 (checked on
`SoundDef.command_sounddef_play_all` 0x831365: 9 arguments, 11 slots).

### 1.4 Counts

| | before (reg_dump + kh.py) | after |
|---|---|---|
| registrations | 6,630 | 6,630 |
| null hash | 2,696 | 2,691 legitimately hashless + 0 missed |
| hashed registrations | 3,934 | 3,939 |
| ... hash explained | 2,274 | 3,939 |
| distinct hashes | 1,691 | 1,696 |
| ... distinct explained | ~848 unexplained | 1,696 / 1,696 |
| registrations without a name | 88 (task text says 83) | 0 |

Unresolved command hashes: none.

Confidence note. The search space is small relative to 2^32 for almost all
hits (1-4 arguments from ~30 types). Three signatures were found with larger
searches and rest on the handler's slot usage as well as the hash:
`command_sounddef_play_all(entity,entity,entity,vector,number,number,number,sounddefinstance,truth)`
(search of ~3.6e9 candidates, so a chance hit was possible; accepted because the
one hit is slot-exact and names the semantically right struct),
`command_update(number,cameracharacterstate,cameracharacterstate,truth)`
(CameraCharacterTransition; two same-type struct pointers at slots 1 and 2 in
0x62ee5f), and the 6-7 argument effect/sound signatures (a 9-argument search for
0x057197f3 produced two obvious chance collisions, discarded in favour of the
6-argument form that matches `command_fire_effect`).

## 2. Properties

Registration: `FUN_0047fde4(hash, defaultStringVA|0, uiStringVA, flags, typeIdx)`
(args re-decoded at all sites; flags in {0,1,3}; e.g. 0x5a0fbd:
`push ebx; push esi; push 0xa423b8 (ui "control=autodropdown|..."); push 0xa423b0
(default "20"); push hash`). **No name string is pushed at or near the site** -
the name exists only as the hash. This agrees with ENGINE_CONSTANTS.md. `typeIdx`
indexes `DAT_00c89ebc` and is the declaring CLASS (equal to the class's own id at
4,262 of 5,090 sites), not the value type; the value type comes from the global
property descriptor looked up by hash (`FUN_004ee10d` @0x47fe03).
(An earlier revision of this report had ui/default swapped - corrected.)

| | before | after |
|---|---|---|
| registration sites | 4,976 | 5,090 (114 missed by the dumper) |
| distinct hashes | 3,602 | 3,695 |
| distinct named via keytable/prop_hash_dict | 3,215 of 3,602 (3,304 of 3,695) | 3,695 / 3,695 |
| reg_dump sites with `ui` null | 2,816 | all named |

Sources of the 3,695 names: 3,303 already correct in the keytable; 391 keytable
names re-hashed with &0xDF (digit-bearing: `m_idrs01attack01`,
`m_nsupersyncremote1`, `_ienum1`, `m_njointmusclepowerscale10`, ...); 1 from
prop_hash_dict (`interval`, 0x06331c10). The caption/`m_` generator (b) was not
needed: once the fold is fixed the existing keytable (3,693 database names)
covers every registered hash. Unresolved registered properties: none.

Five registered hashes are tiny because the names are one or two characters
(0x92 = `i`, 0x52 = `j`, 0xfa2a, 0xaccaad); they are correct, not decode errors.

## 3. Fragment keys (real data, read-only pass on the device)

One aggregated pass with the shipped `kapow_fragment.parse` over all 906
extracted `.fragment` files (18 s; 897 parse ok, 9 SoundEvents/ForceTrigger
files fail at offset 0 with `00000004` - pre-existing, unrelated).

| | before | after fold fix |
|---|---|---|
| distinct "unknown key" values | 10,769 | 8,936 |
| occurrences | 580,286 | 354,606 |
| ... of which nameable but untyped (prop_hash_dict/NAMEABLE) | - | 344 values / 247,305 occ |
| ... unnamed | - | 8,592 values / 107,301 occ |

Newly named: 309 distinct keys / 201,701 occurrences, all digit-bearing names
(259 from the keytable with types, 50 from prop_hash_dict such as `color1RGB`,
`xaudio2I3dl2Reverb_*`, `ps3I3dl2Reverb_*`, `testSound1..5`,
`swing1MotionLimit*`, `FadeCameraAngle1`). Listed in `names_fragment_keys.json`
together with all 480 keytable corrections (new hash, name, type, old wrong hash).

What remains (8,592 values) is mostly not keys at all: 862 are small integers,
ASCII fragments (`6f697461` = "atio", `41726567` = "gerA") or floats
(`3f800000`) - the parser reading values or schema text as keys after an
untyped key. Of all 8,592 residual values, 7,366 occur exactly once. A generator
pass (keytable stems + numeric suffixes, Hungarian prefixes x 24k string tokens;
1.75M candidates) produced 1 hit against ~3 expected by chance, so nothing was
recorded. **Not established** whether the residue contains real keys; typing the
344 nameable-but-untyped keys (aspectRatio, parentLink, includeInAO, ...) is
what would shrink it, since each one currently forces a size guess.

## 4. Errors in reg_dump.json / gen_data.py (for the dumper fix)

1. **Hash function** (`kapow_props.kapow_hash` + callers upper-casing): use
   `byte & 0xDF`. Affects 480 keytable entries, ~1,089 identifier-like
   prop_hash_dict entries, and `kh.py`.
2. **114 property registrations missed** (93 distinct hashes absent from
   reg_dump). The sites pass 0/"" through registers so fewer than 2 immediates
   are seen (`len(imms) >= 2` filter). Examples: 0x6595b9 CameraTool 0x0adc56bd,
   0x6794b1 CharacterSimple 0xd1f1c7c1, 0x6c444d.. CharacterRootLogic. Full list:
   `names_props.json` -> `missed_sites`.
3. **5 command hashes missed** by the `x > 0x1000000` filter (hash has a zero top
   byte): 0x6caf1d CharacterRoot `command_ignore_input_timed(number)` 0x00c837a9;
   0x746e5a/0x746eae Behavior `command_get_follow_pivot` 0x002d4cb5; 0x7c99d0
   MenuWidgetButtonMap `command_get_meta_device` 0x00e0cd00; 0x8075b9
   PlayerManager `command_enable_HUDs(entity)` 0x002eb2af.
4. **88 command names missed** because `exe_string_map` drops strings shorter
   than 5 characters: `Init`, `init`, `ipow`, ... (the VA is pushed normally).
5. **`argc` is not argc**: it is arg2 (`kind`, 1 or 3). 1,351 entries hold
   something else (None, or 0 picked from another argument).
6. **Handler slot is lost**: the dumper takes the first code-range immediate, so
   the address is right, but whether it is a command (arg5), state function
   (arg6) or script method (arg7) is not recorded. No wrong handler addresses
   were found. `names_commands_sites.json` has slot, kind, arg3 and arg8 per site.
7. Register-held arguments are ignored (`push 3; pop ebx; push ebx`,
   `or ebp,-1`). A forward sweep from the SEH prologue
   (`mov eax,imm; call 0x991850`) with constant tracking recovers all 12,161
   sites (441 create, 5,090 prop, 6,630 cmd) with full argument lists -
   `work/names/rescan2.py`.
8. Doc: ENGINE_CONSTANTS.md "Prop hash = kapow_hash(UPPER(m_name))" and the
   0x47eccc argument list ("argc") should be corrected; the 0x47fde4 order is right.
9. Class records: `classId` was wrong for most classes (v1 picked the first small
   immediate) and `base` mixed the native base with the script parent;
   0x47e126 is (name, classId, nativeBase, scriptParent|0, flag, flag).
10. Short default strings ("0", "1", "true", "-1") were dropped (strings < 5 chars).

## 5. Not established

- Meaning of `kind` (+0x10), `arg3` (+0x14) and the `DAT_00c89ebc[typeIdx]`
  value at +0x28 in command records; meaning of `flags`/`typeIdx` for properties.
- That the offline compiler literally calls the &0xDF hasher on
  `name(types)` - inferred from 1,696/1,696 exact reproductions.
- Original letter case of type names in signatures.
- Whether any of the 7,730 residual hash-like fragment values are real keys.
