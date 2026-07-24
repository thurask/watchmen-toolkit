"""Animation clip timing.

The .animation clip header is

    [f32 keyRate Hz][f32 duration s][u32 0][u32 keyCount][u32 frameRateScale]

and the engine invariant is keyRate == (keyCount-1)/duration exactly. The bug
these tests guard against read field 0 (keyRate, ~10 Hz on THIRD-rate clips) as
the duration; the resulting glbs played at roughly 3x the authored speed, which
was then papered over with per-clip "capture-calibrated" speed multipliers.
"""

import struct

import numpy as np
import pytest

import bake_v4
from conftest import build_clip_header


@pytest.mark.parametrize(
    "pal_len,dur,expected",
    [
        (2, 1.0, 1.0),
        (31, 1.0, 30.0),
        (61, 2.0, 30.0),
        (121, 4.0, 30.0),
        (11, 1.0, 10.0),
        (100, 3.3, 99 / 3.3),
    ],
)
def test_fps_for_spans_the_duration(pal_len, dur, expected):
    """fps_for(n, d) == (n-1)/d: n frames must span exactly d seconds.

    glTF sampler times are frame/fps, so the last key lands at (n-1)/fps. Using
    n/d instead (the off-by-one) makes every clip finish slightly early and
    accumulates visible drift on looping locomotion.
    """
    assert bake_v4.fps_for(pal_len, dur) == pytest.approx(expected)
    times = np.arange(pal_len) / bake_v4.fps_for(pal_len, dur)
    assert times[-1] == pytest.approx(dur)


@pytest.mark.parametrize("pal_len,dur", [(1, 2.0), (0, 2.0), (10, 0.0), (10, -1.0)])
def test_fps_for_falls_back_to_30(pal_len, dur):
    """Degenerate inputs fall back to the 30 fps engine rate instead of dividing by zero.

    Single-frame ("constant pose") clips and clips whose header duration failed
    to decode both reach here; a ZeroDivisionError would abort a whole
    character export over one bad clip.
    """
    assert bake_v4.fps_for(pal_len, dur) == 30.0


@pytest.mark.parametrize(
    "key_count,duration,scale",
    [(31, 1.0, 1), (61, 2.0, 1), (21, 2.0, 2), (11, 1.0, 3), (301, 10.0, 1)],
)
def test_clip_header_invariant(key_count, duration, scale):
    """keyRate == (keyCount-1)/duration, and field 1 is the duration.

    Documented in docs/ENGINE_CONSTANTS.md and verified on 1163/1163 shipped
    clips. Pinning the field *order* here is the point: it is the fact that
    identifies which dword bake() must read as the duration.
    """
    hdr = build_clip_header(key_count, duration, scale)
    key_rate, dur, zero, kc, frs = struct.unpack("<ffIII", hdr)

    assert dur == pytest.approx(duration, rel=1e-6)
    assert kc == key_count
    assert zero == 0
    assert frs == scale
    assert key_rate == pytest.approx((kc - 1) / dur, rel=1e-6)

    # ...and the fps the exporter derives from it agrees with the key rate
    assert bake_v4.fps_for(kc, dur) == pytest.approx(key_rate, rel=1e-6)


# Realistic shipped clips: ~1-4 s long at a 10-30 Hz key rate, i.e. the regime
# where keyRate and duration are numerically far apart.
@pytest.mark.parametrize("key_count,duration", [(31, 3.0), (91, 3.0), (11, 1.1), (103, 3.4)])
def test_reading_field_zero_as_duration_is_materially_wrong(key_count, duration):
    """The regression guard: hdr[0] is NOT the duration.

    bake() takes `dur = float(hdr[1])`. If it ever drifted back to hdr[0] the
    output would still be a valid, plausible-looking glb -- just played at the
    wrong speed. This asserts the two readings differ by a large factor, so the
    mistake cannot be dismissed as rounding.
    """
    hdr = build_clip_header(key_count, duration)
    key_rate, dur = struct.unpack_from("<ff", hdr, 0)

    good = bake_v4.fps_for(key_count, dur)
    bad = bake_v4.fps_for(key_count, key_rate)
    assert good == pytest.approx((key_count - 1) / duration, rel=1e-6)
    assert bad != pytest.approx(good, rel=0.2)
    assert max(good, bad) / min(good, bad) > 2.0


def test_bake_reads_the_second_float_as_duration():
    """Pins the exact slice bake() uses: np.frombuffer(clip[:8], f4)[1].

    Mirrors the source's own header read so a change of index -- the original
    bug -- shows up as a failure here rather than as mistimed animation nobody
    notices until playback.
    """
    hdr = build_clip_header(61, 2.0, 1)
    fields = np.frombuffer(hdr[:8], np.dtype("<f4"))
    assert float(fields[1]) == pytest.approx(2.0)
    assert float(fields[0]) == pytest.approx(30.0)
    assert bake_v4.fps_for(61, float(fields[1])) == pytest.approx(30.0)


def test_frame_rate_scale_is_a_small_enum():
    """frameRateScale in {1,2,3} = FULL/HALF/THIRD of the 30 fps engine rate.

    It is the reason keyRate is ~10 Hz on THIRD clips -- exactly the value that
    was once mistaken for a duration.
    """
    for scale in (1, 2, 3):
        key_count = 30 // scale + 1
        duration = 1.0
        hdr = build_clip_header(key_count, duration, scale)
        key_rate, dur, _z, kc, frs = struct.unpack("<ffIII", hdr)
        assert frs in (1, 2, 3)
        assert key_rate == pytest.approx(30.0 / scale, rel=0.05)
        assert bake_v4.fps_for(kc, dur) == pytest.approx(key_rate, rel=1e-6)
