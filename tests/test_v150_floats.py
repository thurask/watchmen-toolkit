"""1.5.0: the decoded JSON writes every stored float32 exactly (the shortest
decimal that reads back as the same float32); $WATCHMEN_JSON_FLOATS=rounded
(--json-floats rounded) writes the 1.4.0 values."""

import json
import math
import random
import struct

import pytest

import decode_sequence
import f32json
import kapow_fragment as kf
import kapow_json
import kapow_props as kp

F = struct.Struct("<f")


def f32(x):
    return F.unpack(F.pack(x))[0]


def bits(x):
    return F.pack(x)


def test_f32_is_the_shortest_round_trip():
    x = f32(1.2345e-5)
    assert x != 1.2345e-5  # the float32 is not the decimal ...
    assert f32json.f32(x) == 1.2345e-05  # ... but this decimal reads back as it
    assert json.dumps(f32json.f32(x)) == "1.2345e-05"
    assert bits(json.loads(json.dumps(f32json.f32(x)))) == bits(x)
    assert round(x, 6) == 1.2e-05 and bits(round(x, 6)) != bits(x)  # 1.4.0 lost it
    for v, s in ((0.1, "0.1"), (-8448.72, "-8448.72"), (1.0, "1.0"), (0.0, "0.0"), (3e38, "3e+38")):
        assert json.dumps(f32json.f32(f32(v))) == s
    assert math.copysign(1, f32json.f32(-0.0)) == -1
    for bad in (float("nan"), float("inf"), -float("inf"), 1e39):
        assert f32json.f32(bad) is None


def test_f32_round_trips_random_float32s():
    rng = random.Random(7)
    for _ in range(20000):
        raw = struct.pack("<I", rng.getrandbits(32))
        x = F.unpack(raw)[0]
        y = f32json.f32(x)
        if x != x or math.isinf(x):
            assert y is None
            continue
        assert F.pack(json.loads(json.dumps(y))) == raw
        s = repr(y)
        digits = len(s.split("e")[0].replace("-", "").replace(".", "").lstrip("0").rstrip("0"))
        assert digits <= 9


def test_mode(monkeypatch):
    monkeypatch.delenv("WATCHMEN_JSON_FLOATS", raising=False)
    assert f32json.mode() == "exact"
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", "Rounded")
    assert f32json.mode() == "rounded"
    assert f32json.num(f32(1.2345e-5), 6) == 1.2e-05
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", "approximate")
    with pytest.raises(ValueError, match="WATCHMEN_JSON_FLOATS"):
        f32json.mode()


# ---------------------------------------------------------------------------
# fragment values: number, vector, quaternion, raw4, transforms
# ---------------------------------------------------------------------------
def _parse_doc(monkeypatch, data, mode):
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", mode)
    return kapow_json.to_json("x.fragment", data)


def _props_fragment(pos, orient):
    """A typed fragment (test_level_meta's builders): one node with localPos /
    localOrient."""
    import test_level_meta as tlm

    return tlm._fragment(tlm._node(0x20, "Folder", "Thing", None, localPos=pos, localOrient=orient))


def _leaves(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _leaves(v)
    elif isinstance(o, list):
        for v in o:
            yield from _leaves(v)
    elif isinstance(o, float):
        yield o


def test_fragment_values_are_exact_and_rounded_on_request(monkeypatch):
    tiny = f32(1.2345e-5)
    big = f32(-8448.72)
    data = _props_fragment([0.1234567, -8448.72, 1.2345e-5], [0.0, 0.38268343, 0.0, 0.9238795])
    assert kf.parse(data)["ok"]
    doc = _parse_doc(monkeypatch, data, "exact")
    assert doc["lossless"] is True and doc["float_values"] == "exact"
    stored = {bits(x) for x in (0.1234567, -8448.72, 1.2345e-5, 0.38268343, 0.9238795)}
    got = {bits(x) for x in _leaves(doc["nodes_full"]) if x}
    assert stored <= got  # every stored value comes back bit for bit
    tr = doc["transforms"][0]
    assert tr["pos"] == [0.1234567, -8448.72, 1.2345e-05]
    assert tr["quat"] == [0.0, 0.38268343, 0.0, 0.9238795]
    assert tr["yaw_deg"] == 45.0  # derived: rounded to 0.1 degree in both modes
    old = _parse_doc(monkeypatch, data, "rounded")
    assert old["float_values"] == "rounded"
    assert old["transforms"][0]["pos"] == [0.123, -8448.72, 0.0]
    assert old["transforms"][0]["quat"] == [0.0, 0.3827, 0.0, 0.9239]
    vec = [v for nd in old["nodes_full"] for n, t, v in nd["props"] if n == "localPos"][0]
    assert vec == [round(f32(0.1234567), 6), round(big, 6), round(tiny, 6)]  # 1.4.0


def test_rdval_number_and_raw_values(monkeypatch):
    for mode, want in (("exact", 1.2345e-05), ("rounded", 1.2e-05)):
        monkeypatch.setenv("WATCHMEN_JSON_FLOATS", mode)
        w = kf._f32_writer(6)
        assert w(f32(1.2345e-5)) == want


# ---------------------------------------------------------------------------
# sequence keys and property-bag raw floats
# ---------------------------------------------------------------------------
def test_sequence_keys(monkeypatch):
    t, v = f32(0.0333333), [f32(1.2345e-5), f32(1234.5678)]
    blob = struct.pack("<fII", t, 0, 2) + struct.pack("<2f", *v)
    for mode, want_t, want_v in (
        ("exact", 0.0333333, [1.2345e-05, 1234.5677]),
        ("rounded", 0.03333, [1e-05, 1234.56775]),
    ):
        monkeypatch.setenv("WATCHMEN_JSON_FLOATS", mode)
        keys, p = decode_sequence._keys(blob, 0, 1, False, "<")
        assert p == len(blob)
        assert keys[0]["t"] == want_t and keys[0]["value"] == want_v
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", "exact")
    keys, _ = decode_sequence._keys(blob, 0, 1, False, "<")
    assert [bits(x) for x in keys[0]["value"]] == [bits(x) for x in v]


def test_property_bag_raw_floats(monkeypatch):
    vals = [f32(1.2345e-5), f32(3e9), float("nan"), float("inf")]
    b = struct.pack("<4f", *vals)
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", "exact")
    got = kp._value(None, 0xABCDEF01, b, 0, 4, "<")["floats"]
    assert got[:2] == [1.2345e-05, 3e9] and got[2:] == [None, None]  # |x| >= 1e9 kept
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", "rounded")
    got = kp._value(None, 0xABCDEF01, b, 0, 4, "<")["floats"]
    assert got == [1.2e-05, None, None, None]  # 1.4.0


def test_cli_option(monkeypatch, capsys):
    import watchmen

    monkeypatch.delenv("WATCHMEN_JSON_FLOATS", raising=False)
    assert watchmen.main(["watchmen", "fragment", "x.fragment", "--json-floats", "nope"]) == 2
    assert "--json-floats takes one of: exact, rounded" in capsys.readouterr().out
    assert watchmen.main(["watchmen", "binds", "a", "b", "--json-floats", "exact"]) == 2
    assert "--json-floats applies to: all, extract, fragment" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# NaN and infinities: floats in memory, null in the exact JSON
# ---------------------------------------------------------------------------
NAN, INF = float("nan"), float("inf")


def _strict(text):
    """json.loads that refuses NaN / Infinity tokens (they are not JSON)."""

    def bad(tok):
        raise ValueError("not JSON: %s" % tok)

    return json.loads(text, parse_constant=bad)


def test_value_finite_and_dumps(monkeypatch):
    assert f32json.value(f32(1.2345e-5)) == 1.2345e-05
    assert math.isnan(f32json.value(NAN)) and f32json.value(-INF) == -INF
    doc = {"a": [1.5, NAN, (INF, 2.0)], "b": {"c": -INF}, "d": "x", "e": 3}
    assert f32json.finite(doc) == {
        "a": [1.5, None, (None, 2.0)],
        "b": {"c": None},
        "d": "x",
        "e": 3,
    }
    clean = {"a": [1.0, (2.0,)], "b": {"c": "x"}}
    assert f32json.finite(clean) is clean  # nothing to replace: the same object
    assert _strict(f32json.dumps(doc, exact=True)) == {
        "a": [1.5, None, [None, 2.0]],
        "b": {"c": None},
        "d": "x",
        "e": 3,
    }
    assert f32json.dumps(doc, exact=False) == json.dumps(doc)  # rounded: as 1.4.0 wrote it
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", "exact")
    assert f32json.dumps([NAN]) == "[null]"
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", "rounded")
    assert f32json.dumps([NAN]) == "[NaN]"


def _nonfinite_sequence():
    import test_formats_v2 as tf

    return tf._sequence(
        [
            tf._object(
                "Model",
                [
                    tf._track(
                        "localorient",
                        3,
                        [
                            tf._key(0.0, [0, 90, 0, 0], [((-0.1, 0), (0.1, 0))] * 3),
                            tf._key(1.0, [NAN, 0, 0, 0], [((0.9, 0), (1.1, 0))] * 3),
                            tf._key(2.0, [0, INF, 0, 0], [((1.9, 0), (2.1, 0))] * 3),
                        ],
                    )
                ],
            )
        ]
    )


@pytest.mark.parametrize("mode", ["exact", "rounded"])
def test_sequence_quaternion_key_with_nan_or_infinity(monkeypatch, mode):
    monkeypatch.setenv("WATCHMEN_JSON_FLOATS", mode)
    d = decode_sequence.parse(_nonfinite_sequence())
    assert d["parsed_bytes"] == d["file_bytes"]
    keys = d["objects"][0]["tracks"][0]["keys"]
    assert keys[0]["quat"] == pytest.approx([0, math.sqrt(0.5), 0, math.sqrt(0.5)], abs=1e-6)
    # no rotation from a NaN or infinite angle; the stored angles stay in memory
    assert keys[1]["quat"] is None and math.isnan(keys[1]["euler_deg"][0])
    assert keys[2]["quat"] is None and keys[2]["euler_deg"][1] == INF
    text = f32json.dumps(d, indent=1)
    if mode == "exact":
        k = _strict(text)["objects"][0]["tracks"][0]["keys"]
        assert k[1]["value"][0] is None and k[2]["euler_deg"][1] is None
        assert k[1]["quat"] is None and k[0]["quat"] is not None


def _nonfinite_fragment():
    return _props_fragment([NAN, 1.0, INF], [0.0, NAN, 0.0, 1.0])


@pytest.mark.parametrize("mode", ["exact", "rounded"])
def test_fragment_number_and_vector_with_nan_or_infinity(monkeypatch, mode):
    doc = _parse_doc(monkeypatch, _nonfinite_fragment(), mode)
    assert doc["lossless"] is True and "parse_error" not in doc
    vec = [v for nd in doc["nodes_full"] for n, t, v in nd["props"] if n == "localPos"][0]
    assert math.isnan(vec[0]) and vec[1] == 1.0 and vec[2] == INF  # floats in memory
    v = kf._f32_writer(6)(NAN)
    assert isinstance(v, float) and math.isnan(v)
    if mode == "exact":
        out = _strict(f32json.dumps(doc, indent=1))
        vec = [v for nd in out["nodes_full"] for n, t, v in nd["props"] if n == "localPos"][0]
        assert vec == [None, 1.0, None]


@pytest.mark.parametrize("mode", ["exact", "rounded"])
@pytest.mark.parametrize("kind", ["sequence", "fragment"])
def test_cli_fragment_writes_nan_and_infinity_without_a_traceback(tmp_path, mode, kind):
    import os
    import subprocess
    import sys

    src = tmp_path / ("x." + kind)
    src.write_bytes(_nonfinite_sequence() if kind == "sequence" else _nonfinite_fragment())
    out = tmp_path / "x.json"
    here = os.path.dirname(os.path.abspath(__file__))
    env = dict(os.environ, WATCHMEN_JSON_FLOATS=mode, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(
        [sys.executable, os.path.join(here, "..", "watchmen.py"), "fragment", str(src), str(out)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    if mode == "exact":
        _strict(text)  # valid JSON: null where the value is not a number
    else:
        assert "NaN" in text  # the 1.4.0 writing
