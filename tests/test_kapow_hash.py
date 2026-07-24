"""The Kapow property-bag name hash (``kapow_props.kapow_hash``).

Every property key and type name in a .particle/.grass/.sequence/.fragment is
stored only as this 32-bit hash. If the hash convention drifts, every key in
every parsed asset renders as a raw hex number instead of a name -- and the
regenerated ``prop_hash_dict.pkl`` silently stops matching shipped files.
"""

import pytest

import kapow_props as kp

try:  # watchmenlib pulls in kapow_fragment, which needs the bundled data tables
    import watchmenlib as wl
except Exception as _ex:  # pragma: no cover - depends on the checkout
    wl, _WL_ERR = None, _ex
else:
    _WL_ERR = None

POLY = 0x04C11DB7
GEN = (1 << 32) | POLY  # x^32 + poly, as a GF(2) polynomial


def _poly_mod(value, gen):
    """GF(2) polynomial remainder: value mod gen. Independent of any CRC loop."""
    gbits = gen.bit_length()
    while value.bit_length() >= gbits:
        value ^= gen << (value.bit_length() - gbits)
    return value


def reference_hash(s):
    """Independent reimplementation of the documented convention.

    kapow_props uses a shift register (init 0, no reflection of the register,
    no final xor) into which each byte's bits are fed LSB-first. With an
    all-zero initial value that is exactly the remainder of the message
    polynomial modulo x^32 + 0x04C11DB7 -- computed here by long division
    instead of by re-running the shift register, so a bug in the register loop
    cannot hide behind an identical bug in the reference.
    """
    value = 0
    for byte in s.encode("latin1"):
        for bit in range(8):  # LSB-first within each byte
            value = (value << 1) | ((byte >> bit) & 1)
    return _poly_mod(value, GEN)


NAMES = [
    "",
    "A",
    "POSITION",
    "NAME",
    "NUMBER",
    "QUATERNION",
    "VECTORLIST",
    "GRAVITY",
    "$SPECULARDATA",
    "BIP01 L UPPERARM",
    "MODELRES",
    "0123456789",
]


@pytest.mark.parametrize("name", NAMES)
def test_matches_independent_polynomial_reference(name):
    """kapow_hash == message polynomial mod (x^32 + 0x04C11DB7), init 0.

    Pins the exact CRC convention (init value, bit feed order, absence of a
    final xor). Anything else -- a reflected variant, an 0xFFFFFFFF init, the
    standard zlib CRC32 -- produces different numbers and would break every
    hash->name lookup table in the toolkit.
    """
    assert kp.kapow_hash(name) == reference_hash(name)


def test_hash_is_a_32_bit_value_and_deterministic():
    """The hash is a stable, in-range uint32 across repeated calls.

    The dictionaries built from it are keyed on the raw integer, so an
    out-of-range or run-varying value would corrupt every persisted table.
    """
    for name in NAMES:
        vals = {kp.kapow_hash(name) for _ in range(3)}
        assert len(vals) == 1
        (v,) = vals
        assert isinstance(v, int) and 0 <= v <= 0xFFFFFFFF


@pytest.mark.parametrize(
    "name,expected",
    [
        ("POSITION", 0x15DE4806),
        ("NAME", 0x7282B2A2),
        ("NUMBER", 0xBDA17DE4),
        ("$SPECULARDATA", 0xE9CFE5F3),
        ("GRAVITY", 0xC339EBA5),
        ("", 0x00000000),
    ],
)
def test_golden_values(name, expected):
    """Regression anchors captured from the current implementation.

    These are the numbers that actually appear in shipped assets; freezing a
    handful of them catches a silent convention change even if the reference
    above were ever edited to match a new (wrong) implementation.
    """
    assert kp.kapow_hash(name) == expected


@pytest.mark.skipif(wl is None, reason="watchmenlib unavailable: %s" % (_WL_ERR,))
def test_lookup_convention_is_case_insensitive():
    """The public lookup (`watchmenlib.kapow_hash`) folds case; the raw one does not.

    The engine hashes UPPERCASED names, so every call site must uppercase
    first. This pins where that responsibility lives: `watchmenlib.kapow_hash`
    is the case-insensitive entry point, while `kapow_props.kapow_hash` is the
    raw primitive -- feeding it a mixed-case name yields a different, useless
    hash, which is exactly the bug this test exists to catch.
    """
    for name in ("position", "Position", "POSITION", "pOsItIoN"):
        assert wl.kapow_hash(name) == kp.kapow_hash("POSITION")

    assert kp.kapow_hash("position") != kp.kapow_hash("POSITION")


def test_type_table_is_built_from_uppercased_names():
    """kapow_props.TYPES must map hash(UPPER(typename)) -> typename.

    Type dispatch in parse() keys off this table; if it were built from the
    lowercase names every property value would fall into the raw-hex fallback
    branch and no .particle/.sequence would decode.
    """
    assert kp.TYPES  # non-empty
    for h, tname in kp.TYPES.items():
        assert h == kp.kapow_hash(tname.upper())
        assert tname == tname.lower()
    assert set(kp.TYPES.values()) >= {"number", "integer", "truth", "string", "vector"}
