#!/usr/bin/env python3
"""gen_data.py — regenerate wlib's checked-in data tables from a game install.

Provenance of the data files shipped in wlib/ (see docs/INDEX.md):

  prop_hash_dict.pkl       hash -> name dictionary for the Kapow property hash
                           (bit-CRC32/0x04C11DB7 over the UPPERCASE name).
                           Source: string harvest over the game EXE + all naz
                           block payloads.  FULLY regenerable de novo — the
                           string sections (.rdata/.data) are identical even in
                           the DRM-packed retail KapowMulti.exe.
  reg_dump.json            441 engine classes (props/commands/defaults/UI
                           captions), recovered by scanning registration call
                           sites in the executable's CODE.  Regenerable with
                           `gen_data regdump`, but ONLY from a DRM-free exe
                           (retail .text is SecuROM-encrypted in place) and
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
    sys.path.insert(0, _HERE)

from kapow_props import kapow_hash


# ---- PE helpers -------------------------------------------------------------
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


def build_prop_dict(exe_path, sources=()):
    """De novo prop_hash_dict: hash(UPPER(name)) -> name from the exe string
    sections plus (optionally) every block payload of the given naz sources,
    expanded with identifier sub-tokens."""
    strs = harvest_strings(open(exe_path, "rb").read())
    for src in sources:
        strs |= naz_source_strings(src)
    toks = set()
    for s in strs:
        if len(s) <= 64:
            toks |= _tokens(s)
    out = {}
    for s in sorted(strs | toks, key=_name_rank):
        out.setdefault(kapow_hash(s.upper()), s)
    return out


# ---- reg_dump (ported claude/work_E/reg_scan.py, Ghidra-free) ---------------
CREATE, PROP, CMD = 0x47E126, 0x47FDE4, 0x47ECCC  # registration fns (this exe)


def build_reg_dump(exe_path):
    import capstone

    d = open(exe_path, "rb").read()
    if text_is_packed(d):
        raise RuntimeError(
            "%s has a DRM-packed .text section - reg_dump can only be "
            "regenerated from a DRM-free executable (e.g. KapowMultiDEDRM.exe)" % exe_path
        )
    secs = {s[0]: s for s in pe_sections(d)}
    _, tva, _, traw, tsz = secs[".text"]
    strings = exe_string_map(d)
    off2va = lambda o: o - traw + tva if traw <= o < traw + tsz else None
    va2off = lambda v: v - tva + traw
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.skipdata = True

    def call_sites(target):
        out, i, end = [], traw, traw + tsz - 5
        while True:
            i = d.find(b"\xe8", i, end)
            if i == -1:
                break
            rel = struct.unpack_from("<i", d, i + 1)[0]
            va = off2va(i)
            if va and va + 5 + rel == target:
                out.append(va)
            i += 1
        return out

    def pushes_before(site_va, window=120):
        lo = site_va - window
        for start in range(lo, site_va):
            insns, ok = [], False
            for i in md.disasm(d[va2off(start) : va2off(site_va) + 5], start):
                if i.address == site_va and i.mnemonic == "call":
                    ok = True
                    break
                insns.append(i)
            if ok and insns:
                out = []
                for i in insns:
                    if i.mnemonic == "push":
                        t = i.op_str
                        out.append(
                            int(t, 16)
                            if t.startswith("0x")
                            else (int(t) if t.lstrip("-").isdigit() else t)
                        )
                    elif i.mnemonic in ("call", "jmp", "ret"):
                        out = []  # pushes consumed by an earlier call
                return out
        return []

    sites = []
    for kind, tgt in (("create", CREATE), ("prop", PROP), ("cmd", CMD)):
        for va in call_sites(tgt):
            sites.append((va, kind))
    sites.sort()
    classes, cur = [], None
    for va, kind in sites:
        imms = [x for x in pushes_before(va) if isinstance(x, int)]
        sva = strings.get
        if kind == "create":
            name = next((sva(x) for x in reversed(imms) if sva(x)), None)
            others = [sva(x) for x in imms if sva(x)]
            base = others[0] if len(others) > 1 and others[0] != name else None
            cid = next((x for x in imms if 0 < x < 0x1000), None)
            cur = {
                "va": hex(va),
                "name": name,
                "base": base,
                "classId": cid,
                "props": [],
                "commands": [],
            }
            classes.append(cur)
        elif kind == "prop" and cur is not None:
            if len(imms) >= 2:
                h = imms[-1]
                dflt = sva(imms[-2])
                ui = next((sva(x) for x in imms if sva(x) and "caption" in sva(x)), None)
                if ui is None and len(imms) >= 3:
                    ui = sva(imms[-3])
                cur["props"].append({"va": hex(va), "hash": hex(h), "default": dflt, "ui": ui})
        elif kind == "cmd" and cur is not None:
            name = next((sva(x) for x in imms if sva(x)), None)
            handler = hsh = None
            for x in imms:
                if 0x401000 <= x < 0x9E5000 and sva(x) is None:
                    handler = x
                    break
            cands = [x for x in imms if x > 0x1000000 and x != handler and sva(x) is None]
            if cands:
                hsh = cands[0]
            argc = next((x for x in imms if 0 <= x < 16), None)
            cur["commands"].append(
                {
                    "va": hex(va),
                    "name": name,
                    "hash": hex(hsh) if hsh else None,
                    "handler": hex(handler) if handler else None,
                    "argc": argc,
                }
            )
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
                    "ui": p.get("ui"),
                    "default": p.get("default"),
                }
            if p["hash"] not in seen:  # one entry per registering class OBJECT
                seen.add(p["hash"])  # (duplicate class names stay duplicated)
                out[p["hash"]]["classes"].append(c["name"])
    return out


# ---- fragment-keys transparency (pkl <-> readable json) ---------------------
def keys_export(pkl_path=None):
    kd = pickle.load(open(pkl_path or os.path.join(_HERE, "kapow_fragment_keys.pkl"), "rb"))
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
    exe = next(
        (
            os.path.join(eng, n)
            for n in ("KapowMultiDEDRM.exe", "KapowMulti.exe")
            if os.path.exists(os.path.join(eng, n))
        ),
        None,
    )
    naz = os.path.join(game_root, "game.naz")
    print("exe:", exe)
    rc = 0

    shipped = pickle.load(open(os.path.join(_HERE, "prop_hash_dict.pkl"), "rb"))
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
        old = json.load(open(reg_path))

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
        out = args[i + 1]
        args = args[:i] + args[i + 2 :]
    if cmd == "strings":
        d = build_prop_dict(args[0], args[1:])
        out = out or "prop_hash_dict.pkl"
        pickle.dump(d, open(out, "wb"))
        print("wrote %s (%d names)" % (out, len(d)))
    elif cmd == "regdump":
        r = build_reg_dump(args[0])
        out = out or "reg_dump.json"
        json.dump(r, open(out, "w"), indent=1)
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
        p = derive_prop_names(json.load(open(src)))
        out = out or "prop_names_from_reg.json"
        json.dump(p, open(out, "w"), indent=1)
        print("wrote %s (%d hashes)" % (out, len(p)))
    elif cmd == "keys-export":
        j = keys_export(args[0] if args else None)
        out = out or "kapow_fragment_keys.json"
        json.dump(j, open(out, "w"), indent=1)
        print("wrote %s" % out)
    elif cmd == "keys-import":
        kd = keys_import(json.load(open(args[0])))
        out = out or "kapow_fragment_keys.pkl"
        pickle.dump(kd, open(out, "wb"))
        print("wrote %s" % out)
    elif cmd == "check":
        return check(args[0] if args else ".")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
