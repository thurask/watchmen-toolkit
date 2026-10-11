"""f32json -- float32 values as JSON numbers, written exactly.

The game stores its decimals as IEEE float32.  A JSON number that reads back
as the same float32 needs at most 9 significant digits, often far fewer: f32()
returns the shortest decimal ('%.6g' .. '%.9g') whose float32 is the stored
value, bit for bit, so 1.2345e-05 stays 1.2345e-05 where rounding to 6
decimal places wrote 1.2e-05.

`$WATCHMEN_JSON_FLOATS` picks the mode of the JSON writers that use num():
  exact   (default) -- f32(): every stored value written exactly; NaN and
                       infinities (not JSON numbers) become null;
  rounded           -- the 1.4.0 output: each writer's own rounding
                       (round(x, nd)), byte for byte.
`extract`, `fragment` and `all` set it from --json-floats exact|rounded.

The parsers (kapow_fragment, decode_sequence) keep a NaN or an infinity as the
float it is (value()): what they return is also used in memory (level, animation
and effect tables, derived quaternions), where null would be a TypeError.  The
null is written by dumps(), the serialiser of their JSON files.
"""

import json
import math
import os
import struct

MODES = ("exact", "rounded")
_F = struct.Struct("<f")
_INF = float("inf")


def mode():
    """'exact' or 'rounded' ($WATCHMEN_JSON_FLOATS; default 'exact')."""
    v = (os.environ.get("WATCHMEN_JSON_FLOATS") or "exact").strip().lower()
    if v not in MODES:
        raise ValueError("WATCHMEN_JSON_FLOATS must be one of %s, not %r" % ("|".join(MODES), v))
    return v


def f32(x):
    """The shortest decimal ('%.6g' .. '%.9g') that reads back as the same
    float32 as `x`, as a Python float; None for NaN and the infinities.  `x` is
    a float32 value (a double unpacked from '<f'); a double that is not one is
    first rounded to float32, as struct.pack('<f') does."""
    x = float(x)
    if x != x or x == _INF or x == -_INF:
        return None
    try:
        bits = _F.pack(x)
    except OverflowError:  # a double past the float32 range: not a stored value
        return None
    for p in (6, 7, 8, 9):
        s = "%.*g" % (p, x)
        if _F.pack(float(s)) == bits:
            return float(s)
    return float("%.9g" % x)  # unreachable: 9 digits always round-trip a float32


def num(x, nd, exact=None):
    """A stored float32 for JSON: f32(x) in exact mode, round(x, nd) (the 1.4.0
    writing) in rounded mode.  `exact`: True / False, or None for mode()."""
    if exact is None:
        exact = mode() == "exact"
    return f32(x) if exact else round(x, nd)


def value(x):
    """f32(x) for a finite value; a NaN or an infinity stays the float it is (the
    in-memory form of the parsers; dumps() writes it as null)."""
    x = float(x)
    if x != x or x == _INF or x == -_INF:
        return x
    y = f32(x)
    return x if y is None else y


def finite(obj):
    """`obj` with every NaN / infinite float replaced by None (dicts, lists and
    tuples walked; other values as they are).  A new structure only where
    something changed."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        out = {k: finite(v) for k, v in obj.items()}
        return obj if all(out[k] is obj[k] for k in obj) else out
    if isinstance(obj, (list, tuple)):
        out = [finite(v) for v in obj]
        if all(a is b for a, b in zip(out, obj)):
            return obj
        return out if isinstance(obj, list) else tuple(out)
    return obj


def dumps(obj, exact=None, **kw):
    """json.dumps for the decoded JSON files: in exact mode a NaN or an infinity
    (anywhere in `obj`) is written as null; in rounded mode `obj` is written as
    1.4.0 wrote it (json.dumps' own NaN / Infinity tokens).  `exact`: True /
    False, or None for mode()."""
    if exact is None:
        exact = mode() == "exact"
    if not exact:
        return json.dumps(obj, **kw)
    try:
        return json.dumps(obj, allow_nan=False, **kw)
    except ValueError:  # a non-finite float somewhere: walk only then
        return json.dumps(finite(obj), allow_nan=False, **kw)
