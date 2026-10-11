"""1.5.0: `extract` and the block walks read the archive one block at a time,
zlib blobs have an inflate ceiling, and --quiet keeps the warning lines.

Synthetic archives only (test_p1_formats._naz, test_p2_part1._prison)."""

import os
import struct
import time
import tracemalloc
import zlib

import pytest

import watchmen_extract as we
import export_female_anims as efa
import test_p1_formats as tp1
import test_p2_part1 as tpp


def _prison_naz(tmp_path):
    """A .naz with a block pair, a stream-only room file the block's stream set
    names, an orphan stream-only file and a second block pair."""
    h, a, room = tpp._prison()
    h2, a2, _room = tpp._prison()
    ents = [
        ("Levels/Prison/Prison.block_h_z", h, 0),
        ("Levels/Prison/Art/PrisonYard.block_s_z", room, 0),
        ("Levels/Prison/Prison.block_s_z", a, 0),
        ("Levels/Yard/Orphan.block_s_z", b"xx", 0),
        ("Levels/Yard/Yard.block_s_z", a2, 0),
        ("Levels/Yard/Yard.block_h_z", h2, 0),
    ]
    return tp1._naz(tmp_path, ents), ents


# ---------------------------------------------------------------------------
# iter_blocks / grab_blocks
# ---------------------------------------------------------------------------
def test_iter_blocks_yields_what_grab_blocks_returns_in_the_same_order(tmp_path):
    naz, ents = _prison_naz(tmp_path)
    got = list(we.iter_blocks(naz))
    assert [st for st, _hs in got] == [
        "Levels/Prison/Prison.block",
        "Levels/Prison/Art/PrisonYard.block",
        "Levels/Yard/Orphan.block",
        "Levels/Yard/Yard.block",
    ]
    assert dict(got) == efa.grab_blocks(naz)
    byname = {n: d for n, d, _m in ents}
    assert got[0][1] == {
        "h": byname["Levels/Prison/Prison.block_h_z"],
        "s": byname["Levels/Prison/Prison.block_s_z"],
    }
    assert got[1][1] == {"s": byname["Levels/Prison/Art/PrisonYard.block_s_z"]}
    # headers only: no stream half is read, stream-only files are skipped
    heads = list(we.iter_blocks(naz, streams=False))
    assert [st for st, _ in heads] == ["Levels/Prison/Prison.block", "Levels/Yard/Yard.block"]
    assert all(set(hs) == {"h"} for _st, hs in heads)
    assert list(efa.iter_blocks(naz, False)) == heads


def test_iter_blocks_reads_one_block_at_a_time(tmp_path, monkeypatch):
    naz, _ents = _prison_naz(tmp_path)
    reads = []
    real = we.naz_read
    monkeypatch.setattr(we, "naz_read", lambda p, e: reads.append(e.name) or real(p, e))
    it = we.iter_blocks(naz)
    next(it)
    assert reads == ["Levels/Prison/Prison.block_h_z", "Levels/Prison/Prison.block_s_z"]
    reads.clear()
    list(we.iter_blocks(naz, streams=False))
    assert all(n.endswith("_h_z") for n in reads) and len(reads) == 2


def test_a_later_entry_of_the_same_name_replaces_the_earlier_one(tmp_path):
    h, a, _room = tpp._prison()
    naz = tp1._naz(
        tmp_path,
        [("B.block_h_z", b"old", 0), ("B.block_s_z", a, 0), ("B.block_h_z", h, 0)],
    )
    assert efa.grab_blocks(naz) == {"B.block": {"h": h, "s": a}}
    assert list(we.iter_blocks(naz)) == [("B.block", {"h": h, "s": a})]


def test_archive_clip_reads_headers_only(tmp_path, monkeypatch):
    import bake_v4

    naz, _ents = _prison_naz(tmp_path)
    reads = []
    real = we.naz_read
    monkeypatch.setattr(we, "naz_read", lambda p, e: reads.append(e.name) or real(p, e))
    assert bake_v4.archive_clip("Fence_01", str(naz)) is None  # a model, not a clip
    assert reads and all(n.endswith(".block_h_z") for n in reads)


# ---------------------------------------------------------------------------
# extract: the block pass holds one block
# ---------------------------------------------------------------------------
class _Tracked(bytes):
    """bytes that count how many of them are alive (CPython frees on the last
    reference, so the count is exact)."""

    alive = 0

    def __new__(cls, b):
        cls.alive += 1
        return bytes.__new__(cls, b)

    def __del__(self):
        type(self).alive -= 1


def test_extract_keeps_no_archive_entry_in_memory(tmp_path, monkeypatch, capsys):
    naz, _ents = _prison_naz(tmp_path)
    real_read, real_block = we.naz_read, we.extract_block
    seen = []
    monkeypatch.setattr(we, "naz_read", lambda p, e: _Tracked(real_read(p, e)))

    def spy(h, s, *a, **k):
        seen.append(_Tracked.alive)
        return real_block(h, s, *a, **k)

    monkeypatch.setattr(we, "extract_block", spy)
    _Tracked.alive = 0
    out = tmp_path / "out"
    args = [str(naz), "-o", str(out), "--no-textures", "--no-models", "--no-text", "--no-nav"]
    assert we.main(args) == 0
    # each block is parsed once: the check pass keeps its assets for the asset pass
    # (BLOCK_CACHE_BYTES); its two halves, plus the room file once the first set has
    # read it (it stays cached)
    assert seen == [2, 3]
    assert _Tracked.alive == 0
    log = capsys.readouterr().out
    assert "PrisonYard.block_s_z: 4 asset stream(s) read" in log
    assert "Orphan.block_s_z: no stream set of any block names this file" in log
    ex = out / "extracted" / "art"
    assert (ex / "Fence_01.model.stream").read_bytes() == b"fence-mesh"
    assert not [p for p in out.iterdir() if p.name.startswith(".watchmen_models_")]


def test_the_stream_only_files_are_read_once_and_cached(tmp_path, monkeypatch):
    naz, _ents = _prison_naz(tmp_path)
    reads = []
    real = we.naz_read
    monkeypatch.setattr(we, "naz_read", lambda p, e: reads.append(e.name) or real(p, e))
    args = [str(naz), "-o", str(tmp_path / "o"), "--no-textures", "--no-models", "--no-text"]
    assert we.main(args + ["--no-nav", "--no-files", "--quiet"]) == 0
    room = "Levels/Prison/Art/PrisonYard.block_s_z"
    assert reads.count(room) == 1  # once for both blocks (pass 1 plans without reading)
    assert reads.count("Levels/Yard/Orphan.block_s_z") == 0  # never named: never read
    # --no-files: every entry the run reads, it reads once
    assert sorted(set(reads)) == sorted(reads)


def test_extract_with_files_reads_each_entry_for_files_then_each_block_once(tmp_path, monkeypatch):
    naz, ents = _prison_naz(tmp_path)
    reads = []
    real = we.naz_read
    monkeypatch.setattr(we, "naz_read", lambda p, e: reads.append(e.name) or real(p, e))
    args = [str(naz), "-o", str(tmp_path / "o"), "--no-textures", "--no-models", "--no-text"]
    assert we.main(args + ["--no-nav", "--quiet"]) == 0
    # pass 1 writes files/ (every entry), the block pass reads each half it uses again
    assert reads[: len(ents)] == [n for n, _d, _m in ents]
    again = reads[len(ents) :]
    assert sorted(again) == sorted(
        [
            "Levels/Prison/Prison.block_h_z",
            "Levels/Prison/Prison.block_s_z",
            "Levels/Prison/Art/PrisonYard.block_s_z",
            "Levels/Yard/Yard.block_h_z",
            "Levels/Yard/Yard.block_s_z",
        ]
    )


def _tree(root):
    out = {}
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            p = os.path.join(dp, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


def test_a_block_too_big_to_keep_is_parsed_again_with_the_same_output(
    tmp_path, monkeypatch, capsys
):
    naz, _ents = _prison_naz(tmp_path)
    calls = []
    real_block = we.extract_block
    monkeypatch.setattr(we, "extract_block", lambda *a, **k: calls.append(1) or real_block(*a, **k))
    base = [str(naz), "--no-textures", "--no-models", "--no-text", "--no-nav", "--no-files"]
    assert we.main(base + ["-o", str(tmp_path / "kept")]) == 0
    assert len(calls) == 2  # one parse per block
    log_kept = capsys.readouterr().out
    monkeypatch.setattr(we, "BLOCK_CACHE_BYTES", 0)
    calls.clear()
    assert we.main(base + ["-o", str(tmp_path / "again")]) == 0
    assert len(calls) == 4  # check pass + asset pass per block
    log_again = capsys.readouterr().out
    assert _tree(tmp_path / "kept") == _tree(tmp_path / "again") != {}
    assert log_kept.replace("kept", "X") == log_again.replace("again", "X")


def test_model_spool_round_trips_jobs_in_order(tmp_path):
    sp = we.ModelSpool(tmp_path / "out")
    jobs = [
        (b"H1", b"S1" * 1000, tmp_path / "a.obj", "<", None),
        (b"", b"", tmp_path / "b.obj", ">", "x360"),
        (b"H3", None, tmp_path / "c.obj", None, "ps3"),
    ]
    for j in jobs:
        sp.append(j)
    assert len(sp) == 3
    assert list(sp) == jobs
    assert list(sp) == jobs  # iterable again
    sp.close()
    assert [p.name for p in (tmp_path / "out").iterdir()] == []
    assert len(we.ModelSpool(tmp_path / "none")) == 0
    assert not (tmp_path / "none").exists()  # no job, no folder


# ---------------------------------------------------------------------------
# --quiet keeps the warnings
# ---------------------------------------------------------------------------
def test_quiet_sends_the_warning_lines_to_stderr(tmp_path, capsys):
    naz, _ents = _prison_naz(tmp_path)
    base = [str(naz), "--no-textures", "--no-models", "--no-text", "--no-nav", "--no-files"]
    assert we.main(base + ["-o", str(tmp_path / "loud")]) == 0
    loud = capsys.readouterr()
    warn = [ln for ln in loud.out.splitlines() if we.is_warning_line(ln)]
    assert warn and any("Orphan.block_s_z" in ln and "WARNING:" in ln for ln in warn)
    assert loud.err == ""
    assert we.main(base + ["-o", str(tmp_path / "quiet"), "--quiet"]) == 0
    quiet = capsys.readouterr()
    assert quiet.out == ""
    assert quiet.err.splitlines() == warn  # the same lines, in the same order


def test_is_warning_line():
    assert we.is_warning_line("  ! x: boom")
    assert we.is_warning_line("      WARNING: sfx a: sound header not decoded")
    assert we.is_warning_line("\n  WARNING: raw only")
    assert not we.is_warning_line("\nBLOCK a.block")
    assert not we.is_warning_line("  note: no stream: x")


def test_sheet_warning_goes_through_the_running_log(capsys):
    we._sheet_warning("t", "sheet.json not written", OSError("disk"))
    assert "WARNING: texture t" in capsys.readouterr().out
    got = []
    we._RUN_LOG.append(got.append)
    try:
        we._sheet_warning("t", "sheet.json not written", OSError("disk"))
    finally:
        we._RUN_LOG.pop()
    assert len(got) == 1 and capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# inflate ceiling
# ---------------------------------------------------------------------------
def _zeros_bomb(total, chunk=1 << 20):
    """zlib stream of `total` zero bytes, built by streaming (never materialised)."""
    c = zlib.compressobj(9)
    z = bytearray()
    zero = bytes(chunk)
    for _ in range(total // chunk):
        z += c.compress(zero)
    return bytes(z + c.flush())


def test_a_zlib_bomb_is_refused_fast_with_bounded_memory(monkeypatch):
    bomb = _zeros_bomb(1 << 30)  # 1 GiB of zeros in about 1 MB
    assert len(bomb) < 2 << 20
    monkeypatch.setenv("WATCHMEN_MAX_INFLATE", str(4 << 20))
    for f in (
        lambda: we._maybe_inflate(bomb, "Texture"),
        lambda: we._maybe_inflate(bomb),  # sniffed
        lambda: we.inflate_standalone(b"\0" * 8 + bomb),
        lambda: we.inflate(bomb),
    ):
        tracemalloc.start()
        t0 = time.perf_counter()
        with pytest.raises(ValueError, match="inflates past"):
            f()
        dt = time.perf_counter() - t0
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        # the memory bound is the property; the time bound only catches a hang
        # (generous: tracemalloc slows allocation, and a loaded machine is slow)
        assert peak < 16 << 20 and dt < 30.0


def test_the_default_ceiling_and_its_override(monkeypatch):
    assert we.max_inflate() == we.MAX_INFLATE == 256 << 20
    monkeypatch.setenv("WATCHMEN_MAX_INFLATE", "0x1000")
    assert we.max_inflate() == 4096
    for bad in ("0", "-5", "lots"):
        monkeypatch.setenv("WATCHMEN_MAX_INFLATE", bad)
        with pytest.raises(ValueError, match="WATCHMEN_MAX_INFLATE"):
            we.max_inflate()


def test_inflate_equals_zlib_below_the_ceiling():
    data = os.urandom(5000) + bytes(20000)
    z = zlib.compress(data)
    assert we.inflate(z) == zlib.decompress(z) == data
    assert we.inflate(z, limit=len(data)) == data  # exactly at the ceiling
    with pytest.raises(ValueError, match="inflates past 24999"):
        we.inflate(z, limit=len(data) - 1)
    assert we.inflate(z + b"trailing") == zlib.decompress(z + b"trailing")
    raw = zlib.compressobj(6, zlib.DEFLATED, -15)
    rz = raw.compress(data) + raw.flush()
    assert we.inflate(rz, -15) == data
    # truncated / corrupt: the very error zlib.decompress raises
    for broken in (z[:-9], b"\x78\x9c\xff\xff\xff", b"nonsense"):
        with pytest.raises(zlib.error) as mine:
            we.inflate(broken)
        with pytest.raises(zlib.error) as ref:
            zlib.decompress(broken)
        assert str(mine.value) == str(ref.value)
    # _maybe_inflate keeps reporting the zlib text and returning the blob
    msgs = []
    assert we._maybe_inflate(b"\x78\x9cbad", "Texture", msgs.append) == b"\x78\x9cbad"
    assert msgs == [str(pytest.raises(zlib.error, zlib.decompress, b"\x78\x9cbad").value)]


def _deflated_entry_naz(tmp_path, data, usize):
    """A .naz with one method-8 entry whose directory states `usize`."""
    c = zlib.compressobj(6, zlib.DEFLATED, -15)
    z = c.compress(data) + c.flush()
    p = tp1._naz(tmp_path, [("A.bin", z, 8)])
    e = list(we.naz_entries(p))[0]
    return p, we.NazEntry(e.name, e.compr, e.psize, usize, e.data_off)


def test_naz_read_checks_the_inflated_size(tmp_path, monkeypatch):
    data = b"payload-" * 1000
    p, e = _deflated_entry_naz(tmp_path, data, len(data))
    assert we.naz_read(p, e) == data
    for wrong in (len(data) - 1, len(data) + 1, 0):
        p, e = _deflated_entry_naz(tmp_path, data, wrong)
        with pytest.raises(ValueError, match="the archive says %d" % wrong):
            we.naz_read(p, e)
    p, e = _deflated_entry_naz(tmp_path, b"", 0)
    assert we.naz_read(p, e) == b""
    monkeypatch.setenv("WATCHMEN_MAX_INFLATE", "100")
    p, e = _deflated_entry_naz(tmp_path, data, len(data))
    with pytest.raises(ValueError, match="past the inflate ceiling 100"):
        we.naz_read(p, e)


def test_a_bomb_in_a_block_is_named_and_the_run_goes_on(tmp_path, monkeypatch, capsys):
    """A block asset blob past the ceiling: the block's parse fails with the
    reason in the log, the other blocks are extracted."""
    th = struct.unpack("<I", struct.pack("<I", tpp._TEX))[0]
    bomb_block = tpp._block([("/art/Bomb.bmp", th, _zeros_bomb(64 << 20), None)])
    h, a, room = tpp._prison()
    naz = tp1._naz(
        tmp_path,
        [
            ("Levels/A/A.block_h_z", bomb_block, 0),
            ("Levels/Prison/Prison.block_h_z", h, 0),
            ("Levels/Prison/Prison.block_s_z", a, 0),
            ("Levels/Prison/Art/PrisonYard.block_s_z", room, 0),
        ],
    )
    monkeypatch.setenv("WATCHMEN_MAX_INFLATE", str(1 << 20))
    out = tmp_path / "out"
    args = [str(naz), "-o", str(out), "--no-textures", "--no-models", "--no-text", "--no-nav"]
    assert we.main(args + ["--no-files", "--quiet"]) == 0
    err = capsys.readouterr().err
    assert "! parse failed: zlib blob inflates past 1048576 bytes" in err
    assert (out / "extracted" / "art" / "Fence_01.model.stream").read_bytes() == b"fence-mesh"


def test_skeleton_collect_reads_header_halves_one_at_a_time(tmp_path, monkeypatch):
    """extract --glb's skeleton pass (extract_skeletons.collect) held every block
    of the archive in 1.4.0; it reads the header halves only, in sorted order."""
    import extract_skeletons as es

    naz, _ents = _prison_naz(tmp_path)
    reads = []
    real = we.naz_read
    monkeypatch.setattr(we, "naz_read", lambda p, e: reads.append(e.name) or real(p, e))
    assert es.collect(str(naz)) == {}  # the synthetic skeleton has too few bones
    assert reads == ["Levels/Prison/Prison.block_h_z", "Levels/Yard/Yard.block_h_z"]
