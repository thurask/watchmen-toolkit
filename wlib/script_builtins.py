#!/usr/bin/env python3
"""script_builtins -- the engine's builtin script module as a table (`builtins.json`).

`BuiltinModule::RegisterMembers` (0x47ff8c, builtin.cpp) registers 123 functions and 19
properties and the enums LANGUAGE and PLATFORM.  `builtins.json` holds, for each: the
signature as registered, argument and return types with the engine's type codes and slot
positions, the handler address (PC; PS3 and Xbox 360 where a pair table gives it), whether
the handler is a retail stub, and one line on what the handler does.

    t = script_builtins.load()
    script_builtins.functions("clamp")            # entries by name (min / max have two)
    script_builtins.by_handler(0x47bc97)          # entries sharing a PC handler
    script_builtins.describe(entry)               # "CreateNode(string,entity):entity"
    script_builtins.slot_layout(entry)            # "[0]=ret:entity [1]:string [2]:entity"

(The module is not called `builtins`: wlib modules are imported flat and would shadow the
standard library.)
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_HERE, "builtins.json")
_T = None

#: handler of the 20 registrations that do nothing in the retail build (`ret 4`)
EMPTY_BODY = 0x48D55E
#: handler of the three editor queries that return 0
ZERO_BODY = 0x4FA89C


def load(path=None):
    """The table as a dict (cached for the shipped file)."""
    global _T
    if path is not None:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    if _T is None:
        with open(_PATH, encoding="utf-8") as fh:
            _T = json.load(fh)
    return _T


def type_code(name, table=None):
    """Engine type code of a type name ("list(entity)" -> 10); None when unknown."""
    t = table or load()
    low = name.strip().lower()
    for row in t["type_codes"]:
        if row["name"] == low:
            return row["code"]
    if low.startswith("list("):
        return 10
    if low.startswith("dict("):
        return 11
    return None


def functions(name=None, table=None):
    """All function entries, or those registered under `name` (case-insensitive)."""
    t = table or load()
    if name is None:
        return list(t["functions"])
    low = name.lower()
    return [f for f in t["functions"] if f["name"].lower() == low]


def properties(name=None, table=None):
    t = table or load()
    if name is None:
        return list(t["properties"])
    low = name.lower()
    return [p for p in t["properties"] if p["name"].lower() == low]


def _addr(a):
    return int(a, 16) if isinstance(a, str) else int(a)


def by_handler(addr, platform="pc", table=None):
    """Functions and properties whose handler / getter is at `addr` on `platform`."""
    t = table or load()
    addr = _addr(addr)
    out = []
    for f in t["functions"]:
        h = f["handler"].get(platform)
        if h and _addr(h) == addr:
            out.append(f)
    for p in t["properties"]:
        h = p["getter"].get(platform)
        if h and _addr(h) == addr:
            out.append(p)
    return out


def is_stub(entry):
    """True for a function whose retail handler is a stub (empty or returns zero)."""
    return bool(entry.get("stub"))


def describe(entry):
    """The registered text: a signature, or `name:type` for a property."""
    if "signature" in entry:
        return entry["signature"]
    return "%s:%s" % (entry["name"], entry["type"])


def slot_layout(entry):
    """Where the handler finds its values in the slot array it is passed:
    "[0]=ret:entity [1]:string [2]:entity" (a vector takes 3 slots, a quaternion 4,
    a biginteger 2)."""
    if "signature" not in entry:
        return "getter returns %s" % entry["type"]
    parts = []
    r = entry.get("returns")
    if r:
        parts.append("[0]=ret:%s" % r["type"])
    for a in entry["args"]:
        parts.append("[%d]:%s" % (a["slot"], a["type"]))
    return " ".join(parts) if parts else "no slots"


def enum_value(family, member, table=None):
    """Value of an enum member registered by the module ("PLATFORM", "PLATFORM___PC"
    or just "PC"); None when unknown."""
    t = table or load()
    fam = t["enums"].get(family.upper())
    if not fam:
        return None
    want = member.upper()
    for m in fam["members"]:
        if m["name"].upper() == want or m["name"].upper() == "%s___%s" % (family.upper(), want):
            return m["value"]
    return None


def check(table=None):
    """Consistency problems of a table as a list of strings (empty = sound)."""
    t = table or load()
    bad = []
    c = t["counts"]
    if len(t["functions"]) != c["functions"]:
        bad.append("function count")
    if len(t["properties"]) != c["properties"]:
        bad.append("property count")
    slots = {r["code"]: r["slots"] for r in t["type_codes"]}
    for f in t["functions"]:
        pos = f["returns"]["slots"] if f["returns"] else 0
        for a in f["args"]:
            if a["slot"] != pos or slots.get(a["code"]) != a["slots"]:
                bad.append("slots of %s" % f["signature"])
                break
            pos += a["slots"]
        if pos != f["arg_slots_total"]:
            bad.append("slot total of %s" % f["signature"])
        h = _addr(f["handler"]["pc"])
        want = "empty" if h == EMPTY_BODY else ("returns_zero" if h == ZERO_BODY else None)
        if f["stub"] != want:
            bad.append("stub mark of %s" % f["signature"])
    return bad
