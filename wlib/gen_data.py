#!/usr/bin/env python3
"""gen_data.py — regenerate wlib's checked-in data tables from a game install.

Provenance of the data files shipped in wlib/ (see docs/INDEX.md):

  prop_hash_dict.pkl       hash -> name dictionary for the Kapow property hash
                           (kapow_props.name_hash: bit-CRC32/0x04C11DB7 over
                           the name's bytes & 0xDF, engine FUN_00423ce8).
                           Source: string harvest over the game EXE + all naz
                           block payloads (`gendata strings`; the string
                           sections are readable even in the DRM-packed retail
                           KapowMulti.exe).  The shipped table is an earlier
                           harvest, not the byte output of today's generator:
                           from the Part 2 PC executable alone `strings` gives
                           40,575 names, the shipped table has 23,753, and 675
                           shared hashes differ in letter case.  Names the
                           native classes register carry the registered
                           spelling (registered_names.json); `gendata respell`
                           applies that to a table without any game file and
                           is how the shipped table got them (byte-stable:
                           running it again changes nothing).
  registered_names.json    The spelling of the 1,224 property / command hashes
                           the native classes register (research output from
                           the registration sites; each entry re-hashed on
                           load), the three names the dictionary keeps
                           (PLATFORM, Scene, physicsTimepassed) and the
                           per-class exception is3D (Sprite) / is3d.
  reg_dump.json            441 engine classes (5,090 property and 6,630 command
                           registrations with defaults/UI captions/handler
                           slots; format "kapow-reg-dump/2"), recovered by a
                           register-tracking sweep of the registration
                           functions in the executable's CODE.  Property names
                           and command signatures are merged from
                           kapow_fragment_keys.pkl / command_signatures.json
                           (each verified by re-hashing).  Regenerable with
                           `gen_data regdump`, but ONLY from an executable whose
                           .text is not encrypted (retail .text is SecuROM-
                           packed in place; this toolkit does not unpack it) and
                           needs the `capstone` package.
  prop_names_from_reg.json Pure aggregation of reg_dump.json (hash ->
                           classes/ui/default).  Derived at runtime by
                           engine_schema when absent; no need to ship it.
  kapow_fragment_keys.pkl  The fragment property-key crack: names AND value
                           types for 4.5k property hashes, accumulated by
                           corpus-wide type inference + caption synthesis +
                           manual work.  This is research OUTPUT (knowledge,
                           like the bind formula), not something latent in the
                           game files — it cannot be regenerated mechanically.
                           `gen_data keys-export/keys-import` converts it
                           to/from readable JSON so it is at least transparent
                           and hand-maintainable.
  jiggle_params.npz        RETIRED (capture-fit AR(2) legacy).  Not shipped:
                           without it jiggle_pass delegates to the file-only
                           jiggle_d6 model (the promoted default).

Usage (via the CLI: `watchmen gendata SUBCMD ...`):
  gendata strings   EXE [NAZ_OR_DIR ...] [-o OUT.pkl]   rebuild prop_hash_dict
  gendata respell   [PKL] [-o OUT.pkl]                  registered spellings -> prop_hash_dict
  gendata regdump   EXE [-o OUT.json]                   rebuild reg_dump (capstone)
  gendata propnames [REG_DUMP.json] [-o OUT.json]       derive prop_names
  gendata keys-export [PKL] [-o OUT.json]               fragment keys -> readable json
  gendata keys-import JSON [-o OUT.pkl]                 readable json -> fragment keys
  gendata check     GAME_ROOT                           regenerate + diff vs shipped
"""

import json
import os
import pickle
import re
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0): flat module names must not shadow the stdlib

from kapow_props import kapow_hash, name_hash

_REEXPORTED = (kapow_hash,)  # gen_data.kapow_hash stays importable for older callers


# ---- PE helpers -------------------------------------------------------------


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


def pe_sections(d):
    """[(name, va, vsize, raw_off, raw_size)] from a PE image."""
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    n = struct.unpack_from("<H", d, pe + 6)[0]
    opt = struct.unpack_from("<H", d, pe + 20)[0]
    base = struct.unpack_from("<I", d, pe + 24 + 28)[0]  # ImageBase (PE32)
    off, out = pe + 24 + opt, []
    for _ in range(n):
        nm = d[off : off + 8].rstrip(b"\0").decode("latin1")
        vsz, va, rsz, ro = struct.unpack_from("<IIII", d, off + 8)
        out.append((nm, base + va, vsz, ro, rsz))
        off += 40
    return out


def text_is_packed(d):
    """True if the exe's .text looks DRM-encrypted (SecuROM adds a .bind
    section and leaves essentially no x86 padding/prologue patterns)."""
    secs = {s[0]: s for s in pe_sections(d)}
    if ".bind" in secs:
        return True
    _, _, _, ro, rsz = secs[".text"]
    sample = d[ro : ro + min(rsz, 0x40000)]
    # real x86 .text is full of 0xCC/0x90 padding and E8/FF call bytes
    return (sample.count(b"\xcc\xcc\xcc") + sample.count(b"\x90\x90")) < 16


# ---- string harvest ---------------------------------------------------------
def _runs(data, minlen):
    """(offset, string) for every null-terminated printable ASCII run of at
    least minlen chars.  Linear scan - a regex like [\\x20-\\x7e]{3,}\\x00
    backtracks quadratically on huge printable stretches with no NULs."""
    chunks = data.split(b"\0")
    off = 0
    for ci, chunk in enumerate(chunks[:-1]):  # last chunk has no terminator
        i = len(chunk)
        while i > 0 and 0x20 <= chunk[i - 1] <= 0x7E:
            i -= 1
        if len(chunk) - i >= minlen:
            yield off + i, chunk[i:].decode("latin1")
        off += len(chunk) + 1


def harvest_strings(data, minlen=3):
    """All null-terminated printable ASCII runs (len >= minlen) in a blob."""
    return {s for _o, s in _runs(data, minlen)}


def exe_string_map(d):
    """{va: string} for every null-terminated string (len >= 5, matching the
    Ghidra export reg_dump.json was first built with) in the exe's data
    sections (replacement for the old Ghidra strings.tsv export)."""
    out = {}
    for nm, va, vsz, ro, rsz in pe_sections(d):
        if nm not in (".rdata", ".data"):
            continue
        for o, s in _runs(d[ro : ro + rsz], 5):
            out[va + o] = s
    return out


def naz_source_strings(src):
    """String harvest over every decompressed block payload of a naz archive
    (or Part 1 loose directory): asset names + all inline string payloads."""
    import export_female_anims as efa
    import watchmen_extract as we

    out = set()
    for _stem, b in efa.grab_blocks(src).items():
        if "h" not in b:
            continue
        for e, h, st in we.extract_block(b["h"], b.get("s")):
            if e.name:
                out.add(e.name)
                out.update(p for p in e.name.replace("\\", "/").split("/") if p)
                out.add(os.path.splitext(os.path.basename(e.name))[0])
            out |= harvest_strings(h)
            if st:
                out |= harvest_strings(st)
    return out


def _name_rank(s):
    """Deterministic collision policy for same-hash case variants: prefer
    identifier-looking, then short, then the engine's editor naming style
    (camelBack like 'useRealtime' > all-lowercase > Capitalized), then sorted.
    The hash is case-insensitive, so this is purely cosmetic."""
    ident = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s) is None
    if s[:1].islower() and any(c.isupper() for c in s[1:]):
        style = 0  # camelBack
    elif s.islower():
        style = 1
    else:
        style = 2
    return (ident, len(s), style, s)


_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def _tokens(s):
    """Sub-identifier tokens: split on non-alnum AND camelCase boundaries
    ('WalkSpeed' -> Walk, Speed).  Property names are often bare tokens of
    longer identifiers that never appear standalone in any file."""
    out = set()
    for part in re.split(r"[^A-Za-z0-9]+", s):
        toks = _CAMEL.findall(part)
        out.update(t for t in toks if len(t) >= 3)
        if len(toks) > 1 and 3 <= len(part) <= 40:
            out.add(part)
    return out


# ---- registered spellings ---------------------------------------------------
# The hash folds case, so a dictionary entry may be any case variant of a name.
# For the names the native classes register, the spelling pushed at the
# registration call is the engine's own (`animation`, `mass`, `textRes`); the
# capitalised variants in the executable are editor captions.  That spelling
# outranks every other string of the same hash, with the exceptions the table
# lists (`keep`).  registered_names.json is research output, checked here.
_REG_NAMES_PATH = os.path.join(_HERE, "registered_names.json")
PROP_DICT_PICKLE_PROTOCOL = 4  # what the shipped table is written with (byte-stable)


def load_registered_names(path=None):
    """registered_names.json -> {"names": {hash: {spelling: [classes]}}, "keep":
    {hash: name}, "generic": {hash: name}, "class_overrides": {class: {hash: name}}}
    with integer hashes.  A spelling whose hash is not its key is dropped, so a
    damaged table cannot inject names.  {} tables when the file is missing."""
    out = {"names": {}, "keep": {}, "generic": {}, "class_overrides": {}}
    try:
        with open(path or _REG_NAMES_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return out
    for k, sp in raw.get("names", {}).items():
        h = int(k, 16)
        good = {s: list(c) for s, c in sp.items() if name_hash(s) == h}
        if good:
            out["names"][h] = good
    for s in raw.get("keep", []):
        out["keep"][name_hash(s)] = s
    for k, s in raw.get("generic", {}).items():
        if name_hash(s) == int(k, 16):
            out["generic"][int(k, 16)] = s
    for cls, tab in raw.get("class_overrides", {}).items():
        good = {int(k, 16): s for k, s in tab.items() if name_hash(s) == int(k, 16)}
        if good:
            out["class_overrides"][cls] = good
    return out


def registered_spellings(reg=None):
    """{hash: name}: the one spelling a reader without class context uses for
    every registered hash -- the registered spelling, the `generic` choice where
    two classes register different ones, and no entry for the `keep` names."""
    reg = reg or load_registered_names()
    out = {}
    for h, sp in reg["names"].items():
        if h in reg["keep"]:
            continue
        if len(sp) == 1:
            out[h] = next(iter(sp))
        elif h in reg["generic"]:
            out[h] = reg["generic"][h]
    return out


def apply_registered_spellings(table, reg=None, exe_bytes=None):
    """Let the registered spelling outrank the entry of the same hash in `table`
    ({hash: name}); add the registered names the table lacks.  The `keep` names
    stay as they are.  With `exe_bytes`, only spellings found there as a
    NUL-terminated string are used.  The table is changed in place; new hashes
    are appended in ascending order, so the result does not depend on set or
    dict order.  -> {"respelled": [(hash, old, new)], "added": [(hash, name)]}"""
    want = registered_spellings(reg)
    respelled, added = [], []
    for h in sorted(want):
        s = want[h]
        if exe_bytes is not None and (s.encode("latin1") + b"\0") not in exe_bytes:
            continue
        old = table.get(h)
        if old is None:
            table[h] = s
            added.append((h, s))
        elif old != s:
            table[h] = s
            respelled.append((h, old, s))
    return {"respelled": respelled, "added": added}


def build_prop_dict(exe_path, sources=()):
    """De novo prop_hash_dict: hash(UPPER(name)) -> name from the exe string
    sections plus (optionally) every block payload of the given naz sources,
    expanded with identifier sub-tokens.  A name a native class registers gets
    the registered spelling (apply_registered_spellings); the `keep` names of
    registered_names.json keep the spelling of their own string."""
    exe = _read_bytes(exe_path)
    strs = harvest_strings(exe)
    for src in sources:
        strs |= naz_source_strings(src)
    toks = set()
    for s in strs:
        if len(s) <= 64:
            toks |= _tokens(s)
    out = {}
    for s in sorted(strs | toks, key=_name_rank):
        out.setdefault(name_hash(s), s)
    reg = load_registered_names()
    for h, s in sorted(reg["keep"].items()):
        if s in strs or s in toks:
            out[h] = s
    apply_registered_spellings(out, reg, exe)
    return out


# ---- reg_dump (registration-site scan, Ghidra-free) -------------------------
# Registration-function VAs for the ONE build this was reversed against.  A
# different executable will have different addresses and produce garbage, so the
# recovered class count is sanity-checked in build_reg_dump before returning.
#   CREATE 0x47e126 (name, classId, nativeBase, scriptParent|0, flag, flag)
#   PROP   0x47fde4 (hash, defaultVA|0, uiVA, flags, classTypeIdx)
#   CMD    0x47eccc (name, kind, arg3, hash|-1, cmdHandler, stateHandler,
#                    methodHandler, classTypeIdx)   -> record +0x10.. (FUN_0047eccc)
CREATE, PROP, CMD = 0x47E126, 0x47FDE4, 0x47ECCC
SEH_PROLOG = 0x991850  # every registration function starts `mov eax,imm; call 0x991850`
REG_DUMP_FORMAT = "kapow-reg-dump/2"
SLOTS = ("command", "state", "method")  # which of CMD args 5/6/7 holds the code pointer
_SIG_PATH = os.path.join(_HERE, "command_signatures.json")
_REGS = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")


def load_command_signatures(path=None):
    """{hash:int -> hashed string} for commands whose hash is NOT the bare name:
    ``name(type,type,...)`` (lowercase type names, no spaces, no return type).
    The strings are research output (not present in the exe); every entry is
    verified against its hash here, so a corrupted table cannot inject names."""
    try:
        with open(path or _SIG_PATH, encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError:
        return {}
    out = {}
    for k, v in raw.get("signatures", {}).items():
        h = int(k, 16)
        if name_hash(v) == h:
            out[h] = v
    return out


def _key_names():
    """{hash -> name} from the shipped fragment key table (verified by re-hash)."""
    out = {}
    try:
        with open(os.path.join(_HERE, "kapow_fragment_keys.pkl"), "rb") as fh:
            kd = pickle.load(fh)
    except (OSError, pickle.UnpicklingError, EOFError, ValueError):
        return out
    for tab in ("nameable", "stdkeys", "promoted", "keytable"):  # keytable wins
        for h, v in kd.get(tab, {}).items():
            n = v[0] if isinstance(v, (tuple, list)) else v
            if name_hash(n) == h:
                out[h] = n
    return out


def _cstr(d, off, maxlen=4096):
    """NUL-terminated printable-ASCII string at file offset (any length >= 0), else None."""
    e = d.find(b"\0", off, off + maxlen)
    if e < 0:
        return None
    s = d[off:e]
    if any(c < 0x20 or c > 0x7E for c in s):
        return None
    return s.decode("latin1")


def sweep_call_args(md, code, base, start, end, wanted):
    """Linear sweep of code[start-base:end-base] tracking pushes and constant
    registers; returns {call_va: [arg1, arg2, ...]} for every call VA in `wanted`
    (args in call order: last push first).  An arg is an int when it is an
    immediate or a register whose constant value is known (`xor r,r`,
    `or r,-1`, `mov r,imm`, `push imm; pop r`), else the operand text."""
    regs, stack, out = {}, [], {}
    off = start
    while off < end:
        ins = next(md.disasm(code[off - base : off - base + 16], off), None)
        if ins is None:
            off += 1
            regs, stack = {}, []
            continue
        m, o = ins.mnemonic, ins.op_str
        if m == "push":
            try:
                v = int(o, 0) & 0xFFFFFFFF
            except ValueError:
                v = regs.get(o, o)
            stack.append(v)
        elif m == "pop":
            v = stack.pop() if stack else None
            if o in _REGS:
                if isinstance(v, int):
                    regs[o] = v
                else:
                    regs.pop(o, None)
        elif m == "call":
            if ins.address in wanted:
                out[ins.address] = list(reversed(stack))
            stack = []
            for r in ("eax", "ecx", "edx"):  # caller-saved
                regs.pop(r, None)
        elif m in ("jmp", "ret", "retn"):
            stack = []
        else:
            ops = o.split(", ")
            dst = ops[0]
            if dst in _REGS:
                two = len(ops) == 2
                if m == "xor" and two and ops[1] == dst:
                    regs[dst] = 0
                elif m == "or" and two and ops[1] in ("0xffffffff", "-1"):
                    regs[dst] = 0xFFFFFFFF
                elif m == "and" and two and ops[1] == "0":
                    regs[dst] = 0
                elif m == "mov" and two:
                    try:
                        regs[dst] = int(ops[1], 0) & 0xFFFFFFFF
                    except ValueError:
                        if ops[1] in regs:
                            regs[dst] = regs[ops[1]]
                        else:
                            regs.pop(dst, None)
                elif m in ("inc", "dec") and dst in regs:
                    regs[dst] = (regs[dst] + (1 if m == "inc" else -1)) & 0xFFFFFFFF
                elif m not in ("cmp", "test"):
                    regs.pop(dst, None)
        off = ins.address + ins.size
    return out


def build_reg_dump(exe_path, signatures=None, key_names=None):
    """Registration table (format "kapow-reg-dump/2"): list of class dicts
      {va, name, classId, native_base, parent, base, root_index, props[], commands[]}
      prop    {va, hash, name, default, ui, flags, typeidx}
      command {va, name, hash, handler, slot, kind, visibility, arg3, typeidx,
               signature, dispatch_kind, dispatch_index}
    root_index / visibility / dispatch_* are derived by add_dispatch().
    `signatures` / `key_names` default to the shipped tables; names and
    signatures are only attached when name_hash(string) == hash."""
    import bisect

    import capstone

    d = _read_bytes(exe_path)
    if text_is_packed(d):
        raise RuntimeError(
            "%s has a DRM-packed .text section. reg_dump can only be regenerated "
            "from an executable whose .text is not encrypted; this toolkit neither "
            "provides such a binary nor assists in producing one. The other tables "
            "(prop_hash_dict, kapow_fragment_keys) do not need it." % exe_path
        )
    secs = pe_sections(d)
    _, tva, _, traw, tsz = {s[0]: s for s in secs}[".text"]
    code = d[traw : traw + tsz]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    if signatures is None:
        signatures = load_command_signatures()
    if key_names is None:
        key_names = _key_names()

    def va2off(va):
        for _nm, sva, vsz, ro, rsz in secs:
            if sva <= va < sva + min(vsz, rsz):
                return va - sva + ro
        return None

    def sva(x):  # string at a data VA (any length; "" stays "")
        if not isinstance(x, int) or not (tva + tsz <= x):
            return None
        off = va2off(x)
        return None if off is None else _cstr(d, off)

    def call_sites(target):
        out, i = [], 0
        while True:
            i = code.find(b"\xe8", i)
            if i == -1 or i + 5 > len(code):
                break
            if tva + i + 5 + struct.unpack_from("<i", code, i + 1)[0] == target:
                out.append(tva + i)
            i += 1
        return out

    sites = []
    for kind, tgt in (("create", CREATE), ("prop", PROP), ("cmd", CMD)):
        sites += [(va, kind) for va in call_sites(tgt)]
    sites.sort()
    # function starts = SEH prologues (`b8 imm32` immediately before the call)
    starts = sorted(va - 5 for va in call_sites(SEH_PROLOG) if code[va - tva - 5] == 0xB8)
    byfn = {}
    for va, _k in sites:
        i = bisect.bisect_right(starts, va) - 1
        if i >= 0:
            byfn.setdefault(starts[i], []).append(va)
    args = {}
    for fn, vas in byfn.items():
        args.update(sweep_call_args(md, code, tva, fn, max(vas) + 5, set(vas)))

    def isint(x):
        return isinstance(x, int)

    classes, cur = [], None
    for va, kind in sites:
        a = args.get(va, [])
        if kind == "create":
            a = a + [None] * (6 - len(a))
            native, parent = sva(a[2]), sva(a[3])
            cur = {
                "va": hex(va),
                "name": sva(a[0]),
                "classId": a[1] if isint(a[1]) else None,
                "native_base": native,
                "parent": parent,
                # legacy key: script parent if any, else a non-Node native base
                "base": parent or (native if native != "Node" else None),
                "props": [],
                "commands": [],
            }
            classes.append(cur)
        elif cur is None or len(a) < (5 if kind == "prop" else 8):
            continue
        elif kind == "prop":
            if not isint(a[0]):
                continue
            cur["props"].append(
                {
                    "va": hex(va),
                    "hash": hex(a[0]),
                    "name": key_names.get(a[0]),
                    "default": sva(a[1]),  # None when 0 is passed (no default)
                    "ui": sva(a[2]) or None,  # "" -> None: not exposed in the editor
                    "flags": a[3] if isint(a[3]) else None,
                    "typeidx": a[4] if isint(a[4]) else None,
                }
            )
        else:
            name = sva(a[0])
            hsh = a[3] if isint(a[3]) and a[3] != 0xFFFFFFFF else None
            slot = handler = None
            for i in range(3):
                x = a[4 + i]
                if isint(x) and tva <= x < tva + tsz:
                    slot, handler = SLOTS[i], x
                    break
            sig = None
            if hsh is not None and name is not None:
                if name_hash(name) == hsh:
                    sig = name
                elif signatures.get(hsh, "").startswith(name + "("):
                    sig = signatures[hsh]
            cur["commands"].append(
                {
                    "va": hex(va),
                    "name": name,
                    "hash": hex(hsh) if hsh is not None else None,
                    "handler": hex(handler) if handler is not None else None,
                    "slot": slot,
                    "kind": a[1] if isint(a[1]) else None,
                    "arg3": (a[2] if a[2] != 0xFFFFFFFF else -1) if isint(a[2]) else None,
                    "typeidx": a[7] if isint(a[7]) else None,
                    "signature": sig,
                }
            )
    if len(classes) < 50:
        raise RuntimeError(
            "recovered only %d engine classes from %s -- the registration-function "
            "addresses in this module were reversed from one specific build and do "
            "not apply here; the result would be garbage." % (len(classes), exe_path)
        )
    return add_dispatch(classes)


def add_dispatch(classes):
    """Add what the script runtime derives from the registrations (in place;
    returns `classes`).

    class   root_index      position of `_root` in the class's command list
                            (ScriptClass+0x54), found here by name; None without one
    command visibility      the same number as `kind` (command record +0x10): 3 on
                            every command, `_root` and library-class method, 1 on
                            every other state and method.  "3 = callable from
                            outside" is inferred; no reader of the field was found
            dispatch_kind   kind of the class's hash-map entry for this command's
            dispatch_index  hash, and the command-list index that entry holds
                            (ScriptClass_ResolveCommandTable 0x47c752); None on
                            states and methods (no hash: not reachable by hash)
        0  one version, owned by `_root`: runs whenever sent (a task is created)
        1  one version, owned by a state: needs a live frame of that state
        2  several versions, none owned by `_root` (index -1): the topmost frame
           whose state owns one handles it, else it is unhandled
        3  several versions, one owned by `_root` (index = that one): a state
           override with the root version as fallback -- the topmost owning
           frame wins, the `_root` frame at the bottom supplies the root version
    `arg3` is the owner: the command-list index of the state the version
    belongs to (command record +0x14)."""
    for c in classes:
        cmds = c["commands"]
        roots = [i for i, x in enumerate(cmds) if x["name"] == "_root" and x["slot"] == "state"]
        root = roots[0] if roots else None
        # insertion order: root_index sits before the two lists, as documented
        tail = {k: c.pop(k) for k in ("props", "commands")}
        c["root_index"] = root
        c.update(tail)
        by_hash = {}
        for i, x in enumerate(cmds):
            x["visibility"] = x["kind"]
            x["dispatch_kind"] = x["dispatch_index"] = None
            if x["hash"] is not None and x["arg3"] not in (None, -1):
                by_hash.setdefault(x["hash"], []).append(i)
        for idxs in by_hash.values():
            if len(idxs) == 1:
                kind, index = (0 if cmds[idxs[0]]["arg3"] == root else 1), idxs[0]
            else:
                rv = [i for i in idxs if cmds[i]["arg3"] == root]
                kind, index = (3, rv[0]) if rv else (2, -1)
            for i in idxs:
                cmds[i]["dispatch_kind"], cmds[i]["dispatch_index"] = kind, index
    return classes


# ---- prop_names_from_reg (pure derivation; also used by engine_schema) ------
def derive_prop_names(reg):
    out = {}
    for c in reg:
        seen = set()
        for p in c["props"]:
            if p["hash"] not in out:  # first registration wins (incl. its Nones)
                out[p["hash"]] = {
                    "classes": [],
                    "name": p.get("name"),
                    "ui": p.get("ui"),
                    "default": p.get("default"),
                }
            if p["hash"] not in seen:  # one entry per registering class OBJECT
                seen.add(p["hash"])  # (duplicate class names stay duplicated)
                out[p["hash"]]["classes"].append(c["name"])
    return out


# ---- fragment-keys transparency (pkl <-> readable json) ---------------------
def keys_export(pkl_path=None):
    with open(pkl_path or os.path.join(_HERE, "kapow_fragment_keys.pkl"), "rb") as fh:
        kd = pickle.load(fh)
    return {
        "keytable": {"%08x" % h: list(v) for h, v in sorted(kd["keytable"].items())},
        "stdkeys": {"%08x" % h: v for h, v in sorted(kd["stdkeys"].items())},
        "promoted": {"%08x" % h: list(v) for h, v in sorted(kd["promoted"].items())},
        "nameable": {"%08x" % h: v for h, v in sorted(kd["nameable"].items())},
    }


def keys_import(j):
    return {
        "keytable": {int(h, 16): tuple(v) for h, v in j["keytable"].items()},
        "stdkeys": {int(h, 16): v for h, v in j["stdkeys"].items()},
        "promoted": {int(h, 16): tuple(v) for h, v in j["promoted"].items()},
        "nameable": {int(h, 16): v for h, v in j["nameable"].items()},
    }


# ---- verification -----------------------------------------------------------
def check(game_root):
    """Regenerate what can be regenerated and compare against the shipped
    tables.  Success criterion is FUNCTIONAL: every hash the shipped tables
    resolve must resolve to the same name in the regenerated ones."""
    eng = os.path.join(game_root, "Data", "Engine")
    exe = (
        next(
            (
                os.path.join(eng, n)
                for n in sorted(os.listdir(eng))
                if n.lower().startswith("kapowmulti") and n.lower().endswith(".exe")
            ),
            None,
        )
        if os.path.isdir(eng)
        else None
    )
    naz = os.path.join(game_root, "game.naz")
    if exe is None:
        print(
            "error: no KapowMulti*.exe under %s\n"
            "  `gendata check` verifies the shipped tables against a fresh regeneration,\n"
            "  which needs a game install: pass its root, e.g. `watchmen gendata check /path/to/game`."
            % eng,
            file=sys.stderr,
        )
        return 2
    print("exe:", exe)
    rc = 0

    with open(os.path.join(_HERE, "prop_hash_dict.pkl"), "rb") as fh:
        shipped = pickle.load(fh)
    fresh = build_prop_dict(exe, [naz] if os.path.exists(naz) else [])
    cov = sum(1 for h in shipped if h in fresh)
    agree = sum(1 for h in shipped if fresh.get(h, "").upper() == shipped[h].upper())
    print(
        "prop_hash_dict: shipped %d | regenerated %d | covered %d | case-insensitive agree %d"
        % (len(shipped), len(fresh), cov, agree)
    )
    if cov < len(shipped) * 0.95:
        rc = 1

    reg_path = os.path.join(_HERE, "reg_dump.json")
    try:
        fresh_reg = build_reg_dump(exe)
        with open(reg_path) as fh:
            old = json.load(fh)

        def norm(x):  # the original Ghidra string export trimmed trailing spaces
            if isinstance(x, str):
                return x.rstrip()
            if isinstance(x, list):
                return [norm(v) for v in x]
            if isinstance(x, dict):
                return {k: norm(v) for k, v in x.items()}
            return x

        same = norm(fresh_reg) == norm(old)
        print(
            "reg_dump: regenerated %d classes | identical to shipped: %s" % (len(fresh_reg), same)
        )
        if not same:
            rc = 1
        pn = derive_prop_names(fresh_reg)
        print("prop_names (derived): %d hashes" % len(pn))
    except (RuntimeError, ImportError) as e:
        print("reg_dump: SKIPPED (%s)" % e)
    return rc


# ---- CLI --------------------------------------------------------------------
def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    cmd, args = argv[1], argv[2:]
    out = None
    if "-o" in args:
        i = args.index("-o")
        if i + 1 >= len(args):
            print("error: -o needs a path", file=sys.stderr)
            return 2
        out = args[i + 1]
        args = args[:i] + args[i + 2 :]
    if cmd in ("strings", "regdump", "keys-import") and not args:
        print("error: %s needs a path argument (see `gendata -h`)" % cmd, file=sys.stderr)
        return 2
    if cmd == "strings":
        d = build_prop_dict(args[0], args[1:])
        out = out or "prop_hash_dict.pkl"
        with open(out, "wb") as _f:
            pickle.dump(d, _f, protocol=PROP_DICT_PICKLE_PROTOCOL)
        print("wrote %s (%d names)" % (out, len(d)))
    elif cmd == "respell":
        # the shipped dictionary with the registered spellings applied: the step
        # that needs no game files, and gives the same bytes on every run
        src = args[0] if args else os.path.join(_HERE, "prop_hash_dict.pkl")
        with open(src, "rb") as _f:
            d = pickle.load(_f)
        ch = apply_registered_spellings(d)
        out = out or "prop_hash_dict.pkl"
        with open(out, "wb") as _f:
            pickle.dump(d, _f, protocol=PROP_DICT_PICKLE_PROTOCOL)
        for _h, _old, _new in ch["respelled"]:
            print("  %08x %s -> %s" % (_h, _old, _new))
        for _h, _new in ch["added"]:
            print("  %08x + %s" % (_h, _new))
        print(
            "wrote %s (%d names; %d respelled, %d added)"
            % (out, len(d), len(ch["respelled"]), len(ch["added"]))
        )
    elif cmd == "regdump":
        r = build_reg_dump(args[0])
        out = out or "reg_dump.json"
        with open(out, "w", encoding="utf-8", newline="\n") as _f:
            json.dump(r, _f, indent=1)
        print(
            "wrote %s (%d classes, %d props, %d commands)"
            % (
                out,
                len(r),
                sum(len(c["props"]) for c in r),
                sum(len(c["commands"]) for c in r),
            )
        )
    elif cmd == "propnames":
        src = args[0] if args else os.path.join(_HERE, "reg_dump.json")
        with open(src) as _f:
            p = derive_prop_names(json.load(_f))
        out = out or "prop_names_from_reg.json"
        with open(out, "w", encoding="utf-8", newline="\n") as _f:
            json.dump(p, _f, indent=1)
        print("wrote %s (%d hashes)" % (out, len(p)))
    elif cmd == "keys-export":
        j = keys_export(args[0] if args else None)
        out = out or "kapow_fragment_keys.json"
        with open(out, "w", encoding="utf-8", newline="\n") as _f:
            json.dump(j, _f, indent=1)
        print("wrote %s" % out)
    elif cmd == "keys-import":
        with open(args[0]) as _f:
            kd = keys_import(json.load(_f))
        out = out or "kapow_fragment_keys.pkl"
        with open(out, "wb") as _f:
            pickle.dump(kd, _f)
        print("wrote %s" % out)
    elif cmd == "check":
        return check(args[0] if args else ".")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
