"""The node-type scan of `kapow_json.fragment_json` is linear in the file size.

The scan looks for type names: a printable string of 3+ bytes that ends with ")" or
starts with "{", closed by a NUL and followed by a 12-byte node header.  It used to
test every start offset on its own, reading the rest of the NUL-free run each time,
which is quadratic in the length of a run (packed floats, strings).  The run is now
judged once.  The result must be exactly what the per-offset scan gives.

Synthetic data only: no game files.
"""

import random
import struct
import time

import pytest

import kapow_json


def _reference_scan(d, bo="<"):
    """The per-offset scan as it was (step 1 of fragment_json)."""
    nodes = []
    p = 0
    while p < len(d):
        e = d.find(b"\x00", p)
        if e < 0:
            break
        s = d[p:e]
        if (
            len(s) >= 3
            and all(32 <= c < 127 for c in s)
            and (s.endswith(b")") or s.startswith(b"{"))
        ):
            q = e + 1
            while q < len(d) and d[q] == 0 and q - (e + 1) < 8:
                q += 1
            if q + 12 <= len(d):
                mark, h, depth = struct.unpack_from(bo + "III", d, q)
                if depth < 40 and (mark >= 0xFFFFFFF0 or 0x10000 < mark < 0xFFFFFF00):
                    nodes.append({"depth": depth, "type": s.decode("latin1"), "hash": "%08x" % h})
                    p = q + 12
                    continue
        p += 1
    return nodes


def _header(rnd, bo, good=True):
    mark = rnd.choice([0xFFFFFFF0, 0xFFFFFFFF, 0x10001, 0x00ABCDEF, 0xFFFFFEFF])
    depth = rnd.randrange(0, 40)
    if not good:
        mark, depth = rnd.choice([(0, 3), (0x10000, 3), (0xFFFFFF00, 3), (0xFFFFFFF5, 40)])
    return struct.pack(bo + "III", mark, rnd.getrandbits(32), depth)


def _buffer(rnd, bo):
    names = [
        b"Node(Base)",
        b"{guid-1234}",
        b"A()",
        b"x)",
        b"{}",
        b"ab{cd",
        b"{a",
        b"FragmentNode(Node)",
    ]
    out = []
    for _ in range(rnd.randrange(5, 60)):
        kind = rnd.randrange(9)
        if kind == 0:  # a well-formed type record
            out.append(rnd.choice(names) + b"\x00" * rnd.randrange(1, 11) + _header(rnd, bo))
        elif kind == 1:  # a name whose record is not a node header
            out.append(rnd.choice(names) + b"\x00" * rnd.randrange(1, 4) + _header(rnd, bo, False))
        elif kind == 2:  # junk in front of a name, no NUL between
            junk = bytes(rnd.randrange(1, 256) for _ in range(rnd.randrange(1, 30)))
            out.append(junk + rnd.choice(names) + b"\x00" + _header(rnd, bo))
        elif kind == 3:  # printable text in front: the name is a tail of the run
            text = bytes(rnd.randrange(32, 127) for _ in range(rnd.randrange(1, 30)))
            out.append(text + rnd.choice(names) + b"\x00\x00" + _header(rnd, bo))
        elif kind == 4:  # several "{" in one run
            out.append(b"q{r{s{tu" + rnd.choice([b")", b"", b"}"]) + b"\x00" + _header(rnd, bo))
        elif kind == 5:  # a name at the very end, record cut short
            out.append(rnd.choice(names) + b"\x00" + _header(rnd, bo)[: rnd.randrange(0, 12)])
        elif kind == 6:
            out.append(bytes(rnd.randrange(0, 256) for _ in range(rnd.randrange(0, 80))))
        elif kind == 7:
            out.append(b"\x00" * rnd.randrange(1, 20))
        else:  # a long NUL-free run of float-like bytes
            out.append(bytes(rnd.randrange(1, 256) for _ in range(rnd.randrange(50, 400))))
    return b"".join(out)


@pytest.mark.parametrize("bo", ["<", ">"])
def test_scan_equals_the_per_offset_scan(bo):
    rnd = random.Random(20261004 + (bo == ">"))
    found = 0
    for _ in range(1500):
        d = _buffer(rnd, bo)
        want = _reference_scan(d, bo)
        assert kapow_json.fragment_json(d, bo)["nodes"] == want
        found += len(want)
    assert found > 3000  # the buffers do contain type records


def test_schema_name_rules():
    f = kapow_json._schema_name

    def name(run):
        d = run + b"\x00"
        return f(d, 0, len(run))

    assert name(b"Node(Base)") == b"Node(Base)"
    assert name(b"\x01\x02Node(Base)") == b"Node(Base)"  # the printable tail
    assert name(b"ab{cd") == b"{cd"  # from the first "{" on
    assert name(b"a{b{c") == b"{b{c"
    assert name(b"x)") is None and name(b"{a") is None  # shorter than 3
    assert name(b"abc") is None and name(b"") is None
    assert name(b"{ab\x7f") is None  # tail after the last non-printable byte is empty
    assert name(b"{\x05abc)") == b"abc)"
    assert name(b"ab{") is None and name(b"a{b") is None
    assert name(b"{bc") == b"{bc"
    # a start offset inside the run
    d = b"Node(Base)\x00"
    assert f(d, 4, 10) == b"(Base)" and f(d, 8, 10) is None


def test_long_runs_are_scanned_in_linear_time():
    """2 MB without a NUL, then a real record: seconds before, milliseconds now."""
    rnd = random.Random(1)
    blob = bytes(rnd.randrange(32, 127) for _ in range(1 << 16)) * 32
    d = blob.replace(b")", b"(") + b"\x05Tail(Node)\x00" + struct.pack("<III", 0xFFFFFFF0, 7, 2)
    t = time.time()
    nodes = kapow_json.fragment_json(d)["nodes"]
    assert time.time() - t < 5.0
    assert nodes == [{"depth": 2, "type": "Tail(Node)", "hash": "00000007"}]
