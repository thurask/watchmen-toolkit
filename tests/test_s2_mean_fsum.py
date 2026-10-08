"""Means in sound_meta / anim_meta do not depend on the Python version.

`sum()` of floats is a plain left fold up to Python 3.11 and a compensated sum from
3.12 on.  The two differ in the last bit now and then, and a mean rounded to 4
decimals then lands on either side: on the six-set export 14 `talk_s.mean` values of
PC Part 2 differed by 0.0001 between a Python 3.10 and a Python 3.14 build of the same
extract.  `math.fsum` is exactly rounded on every version.
"""

import math

import sound_meta


def _fold(values):
    a = 0.0
    for v in values:
        a = a + v
    return a


def test_mean_is_the_exactly_rounded_sum():
    ds = [0.1] * 10  # fold: 0.9999999999999999, exact: 1.0
    assert _fold(ds) != math.fsum(ds)
    assert sound_meta._mean(ds) == 0.1
    assert sound_meta._stats(ds)["mean"] == 0.1


def test_mean_where_the_fold_rounds_the_other_way():
    """Durations whose folded mean rounds to another 4th decimal than the exact one."""
    import random

    rnd = random.Random(4)
    hits = 0
    for _ in range(20000):
        n = rnd.randrange(2, 9)
        base = rnd.randrange(10000, 60000) * 1e-4 + 0.5e-4  # a tie at the 4th decimal
        ds = [base + rnd.uniform(-2.0, 2.0) for _ in range(n - 1)]
        ds.append(base * n - math.fsum(ds))
        want = round(math.fsum(ds) / n, 4)
        assert sound_meta._mean(ds) == want
        if round(_fold(ds) / n, 4) != want:
            hits += 1
    assert hits > 0  # the fold does differ on such data


def test_stats_shape_is_unchanged():
    assert sound_meta._stats([]) == {"n": 0, "min": None, "max": None, "mean": None}
    assert sound_meta._stats([0, None, 1.5, 2.5]) == {"n": 2, "min": 1.5, "max": 2.5, "mean": 2.0}
