"""Robustness of the small parsers on truncated / garbage input.

Every one of these runs over thousands of blobs carved out of a shipped
archive, and the carving heuristics are not exact: some of what reaches them is
truncated, misaligned or simply not the format they expect. A parser that
crashes with an opaque struct.error or -- worse -- spins forever takes the
whole extraction run down with it, so each one must fail fast, fail clearly, or
return a partial result.
"""

import random
import struct
import threading

import pytest

import decode_sequence as ds
import parse_model_nodes as pmn
import watchmen_extract as we
from conftest import build_model_header, synthetic_nodes

TIME_GUARD = 10.0  # generous: these parsers finish in milliseconds when sane


def run_bounded(fn, *args, **kwargs):
    """Run fn in a daemon thread; fail (rather than hang) if it does not return.

    A daemon thread lets pytest exit even if the parser really is stuck, so a
    hang shows up as a test failure instead of a wedged CI job.
    """
    box = {}

    def target():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as ex:  # noqa: BLE001 - reported to the caller
            box["error"] = ex

    th = threading.Thread(target=target, daemon=True)
    th.start()
    th.join(TIME_GUARD)
    assert not th.is_alive(), "%s did not terminate within %.0fs" % (fn.__name__, TIME_GUARD)
    return box


# ---------------------------------------------------------------------------
# naz_entries
# ---------------------------------------------------------------------------


def test_naz_entries_rejects_a_non_archive(tmp_path):
    """A file with the right size but the wrong magic must raise ValueError.

    The extractor tries every candidate path it is given; a clear, typed error
    is what lets the caller move on to the next one.
    """
    p = tmp_path / "not.naz"
    p.write_bytes(bytes(random.Random(1).randrange(256) for _ in range(4096)))
    with pytest.raises(ValueError, match="not a NAZ archive"):
        list(we.naz_entries(p))


@pytest.mark.parametrize("size", [0, 1, 8, 15])
def test_naz_entries_on_a_truncated_file(tmp_path, size):
    """A file too short to hold an EOCD must be reported as 'not an archive'.

    An 8-byte file is a perfectly ordinary thing to find in a game directory.
    Reporting it as a negative-seek OSError makes the failure look like a disk
    problem rather than a wrong-file-type problem.
    """
    p = tmp_path / "short.naz"
    p.write_bytes(b"\x00" * size)
    with pytest.raises(ValueError):
        list(we.naz_entries(p))


def test_naz_entries_terminates_on_garbage(tmp_path):
    """Garbage input must not hang the central-directory walk.

    The record count comes straight out of the file, so a hostile or corrupt
    value must not turn into an unbounded loop.
    """
    p = tmp_path / "garbage.naz"
    rnd = random.Random(7)
    for _ in range(20):
        p.write_bytes(bytes(rnd.randrange(256) for _ in range(2048)))
        box = run_bounded(lambda: list(we.naz_entries(p)))
        assert "value" in box or isinstance(box.get("error"), (ValueError, OSError, struct.error))


# ---------------------------------------------------------------------------
# parse_model_nodes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(12))
def test_parse_model_nodes_on_random_bytes(seed):
    """Random bytes must raise a plain ValueError, never a struct/index error.

    This parser is pointed at every block header in the archive, most of which
    are not ModelRes. ValueError is the contract the callers catch; anything
    else escapes and aborts the pass.
    """
    rnd = random.Random(seed)
    blob = bytes(rnd.randrange(256) for _ in range(1024))
    box = run_bounded(pmn.parse, blob)
    if "error" in box:
        assert isinstance(box["error"], ValueError), "unexpected %r" % (box["error"],)
    else:
        names, pos, quat, parent = box["value"]
        assert len(names) == len(pos) == len(quat) == len(parent)


@pytest.mark.parametrize("keep", [0, 1, 3, 17, 64, 200])
def test_parse_model_nodes_on_a_truncated_header(keep):
    """A ModelRes header cut short must fail cleanly, not read past the buffer.

    Truncation is what a mis-sized block carve looks like; the parser must
    notice rather than index into whatever follows in memory.
    """
    header = build_model_header(synthetic_nodes(), "<")[:keep]
    box = run_bounded(pmn.parse, header)
    if "error" in box:
        assert isinstance(box["error"], ValueError), "unexpected %r" % (box["error"],)
    else:
        names, pos, _quat, parent = box["value"]
        assert len(names) == len(pos) == len(parent)
        assert all(-1 <= int(p) < len(names) for p in parent)


def test_parse_model_nodes_on_an_empty_buffer():
    """An empty buffer is a ValueError, not a crash."""
    with pytest.raises(ValueError):
        pmn.parse(b"")


def test_parse_model_nodes_ignores_a_trailing_partial_record():
    """Extra trailing bytes must not invent a bone.

    Block payloads are padded; a decoder that treats padding as another node
    shifts every parent index after it.
    """
    nodes = synthetic_nodes()
    header = build_model_header(nodes, "<") + b"\xab" * 24
    names, _pos, _quat, _parent = pmn.parse(header)
    assert len(names) == len(nodes)


# ---------------------------------------------------------------------------
# decode_sequence
# ---------------------------------------------------------------------------


def _sequence_bytes(nobjects=2, ntracks=1, nkeys=3):
    """A minimal well-formed .sequence: header, objects, one vec3 track each."""
    b = struct.pack("<fII", 1.0, 4, nobjects) + struct.pack("<I", 0)
    for oi in range(nobjects):
        b += struct.pack("<I", 1) + struct.pack("<I", 0x1000 + oi)
        name = b"Node\0"
        b += struct.pack("<I", len(name)) + name
        b += struct.pack("<I", ntracks)
        for _ti in range(ntracks):
            prop = b"Position\0"
            b += struct.pack("<I", len(prop)) + prop
            b += struct.pack("<2I", 3, nkeys)
            for k in range(nkeys):
                b += struct.pack("<fII", k * 0.5, 0, 3)
                b += struct.pack("<3f", float(k), 2.0, 3.0)
    return b


def test_decode_sequence_parses_the_reference_buffer():
    """Baseline: the synthetic buffer really is a parseable .sequence.

    Without this the truncation tests below would be vacuous -- they would pass
    on a parser that rejects everything.
    """
    out = ds.parse(_sequence_bytes())
    assert out["version"] == pytest.approx(1.0)
    assert len(out["objects"]) == 2
    track = out["objects"][0]["tracks"][0]
    assert track["prop"] == "Position"
    assert [k["t"] for k in track["keys"]] == [0.0, 0.5, 1.0]
    assert out["parsed_bytes"] == out["file_bytes"]


@pytest.mark.parametrize("cut", [12, 13, 20, 33, 48, 72, 120, 195])
def test_decode_sequence_terminates_on_truncated_input(cut):
    """Truncated input must TERMINATE -- the scan window must not loop forever.

    parse() hunts for the next object header in a window around the current
    offset, including bytes *behind* it. If the recovered position ever failed
    to advance, the outer `while p < n - 8` would spin. The bounded runner
    turns that into a failure instead of a hung run.
    """
    blob = _sequence_bytes()[:cut]
    box = run_bounded(ds.parse, blob)
    assert "value" in box or "error" in box


@pytest.mark.parametrize("seed", range(8))
def test_decode_sequence_terminates_on_random_bytes(seed):
    """Random bytes must terminate and produce a bounded, self-consistent result."""
    rnd = random.Random(1000 + seed)
    blob = bytes(rnd.randrange(256) for _ in range(768))
    box = run_bounded(ds.parse, blob)
    assert "error" not in box, "unexpected %r" % (box.get("error"),)
    out = box["value"]
    assert out["file_bytes"] == len(blob)
    assert 0 <= out["parsed_bytes"] <= len(blob) + 8


@pytest.mark.parametrize("cut", [0, 4, 8, 50, 98, 195])
def test_decode_sequence_degrades_gracefully_when_truncated(cut):
    """A truncated .sequence should yield a partial parse, not struct.error.

    Sequence blobs are carved heuristically, so short reads are routine. The
    parser already reports desync through out['warn']; a raw struct.error from
    the header or key loop bypasses that and aborts the caller's whole pass.
    """
    out = ds.parse(_sequence_bytes()[:cut])
    assert isinstance(out, dict)
    assert out["file_bytes"] == cut


def test_decode_sequence_key_count_is_bounded():
    """An absurd key count must be refused rather than allocated.

    nkeys comes straight from the file; the parser caps it at 10000 so a
    corrupt dword cannot turn into a multi-gigabyte loop.
    """
    b = struct.pack("<fII", 1.0, 4, 1) + struct.pack("<I", 0)
    b += struct.pack("<I", 1) + struct.pack("<I", 0x1000)
    name = b"Node\0"
    b += struct.pack("<I", len(name)) + name
    b += struct.pack("<I", 1)
    prop = b"Position\0"
    b += struct.pack("<I", len(prop)) + prop
    b += struct.pack("<2I", 3, 0xFFFFFFF0)  # hostile key count
    b += b"\x00" * 64

    box = run_bounded(ds.parse, b)
    assert "error" not in box, "unexpected %r" % (box.get("error"),)
    assert box["value"]["objects"] == [] or not box["value"]["objects"][0]["tracks"]
