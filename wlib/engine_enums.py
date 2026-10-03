#!/usr/bin/env python3
"""engine_enums -- the engine's own enum tables (id <-> name), read from the exe.

`engine_enums.json` holds the animation-relevant families exactly as the
executable registers them (FUN_005052c9(family, "PREFIX___NAME", value)), the
enum family each ANIMATION_ENUM criteria variable takes its values from, and a
per-event summary of what the engine does with each ANIMATION_EVENT id.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_HERE, "engine_enums.json")
_DATA = None


def data():
    """The whole table (parsed once)."""
    global _DATA
    if _DATA is None:
        with open(_PATH, encoding="utf-8") as fh:
            _DATA = json.load(fh)
    return _DATA


def families():
    """Sorted family names."""
    return sorted(data()["families"])


def family(name):
    """{id (int): item name} of one family; {} when the family is not shipped."""
    f = data()["families"].get(name)
    return {int(k): v for k, v in f["items"].items()} if f else {}


def name(fam, value, default=None):
    """Item name of `value` in family `fam`.  Values stored unsigned in the game
    data (4294967295 for -1) are folded to int32 first."""
    if value is None:
        return default
    return family(fam).get(signed(value), default)


def ident(fam, item_name, default=None):
    """Id of `item_name` in family `fam`."""
    for k, v in family(fam).items():
        if v == item_name:
            return k
    return default


def signed(value):
    """An integer property as the engine's int32 (NONE = -1 is stored as 2**32-1)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return value
    return v - (1 << 32) if v >= (1 << 31) else v


def enum_variable_family(var):
    """The family an ANIMATION_ENUM variable (criteria `m_ianimationenum`) takes
    its values from, or None (TARGET_MODE has no registered value family)."""
    return data()["enum_variable_family"].get(str(var))


def interval_type(value, default=None):
    return data()["interval_types"].get(str(value), default)


def event_semantics():
    """{event id (str): {name, effect, value, moves_character, affects_partner,
    handler, evidence}} for every registered ANIMATION_EVENT."""
    return data()["event_semantics"]
