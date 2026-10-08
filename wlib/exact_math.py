"""Functions whose results are the same bit for bit on every platform.

IEEE 754 fixes the result of + - * / and sqrt on doubles, and CPython evaluates
one operation per bytecode (no fused multiply-add), so plain float arithmetic
gives the same bits on every machine.  That does not hold for what a baked
simulation otherwise leans on:

* `math.sin` / `cos` / `tan` / `acos` / `atan2` and `float ** 2` come from the
  platform's C library, and the libraries round differently;
* `sum()` of floats is compensated from Python 3.12 on and a plain left fold
  before;
* `numpy.linalg.svd` (LAPACK) depends on the OpenBLAS build numpy ships with, and
  `@` / `einsum` / `norm` on its kernels.

A difference in the last bit is harmless in a single value, but the jiggle
solver (jiggle_d6, model "solver") feeds each step into the next through a
one-sided limit row, and on a clip that keeps the bone near its limit the last
bit grows to centimetres.  The solver therefore takes everything of that kind
from here: the trigonometry is the fdlibm kernels (Sun Microsystems, freely
distributable) written with float operations only, the nearest rotation is a
Newton iteration instead of an SVD, sums are left folds.

Accuracy: sin / cos / atan within 1 ulp of the correctly rounded value on the
ranges the solver uses (|x| < 1e5 for sin / cos); acos and atan2 within a few
ulp.  The point of the module is that the value is the same everywhere, not that
it is the best one.
"""

import math

_sqrt = math.sqrt  # correctly rounded by IEEE 754: the one libm call allowed here
_floor = math.floor  # exact

PI = 3.141592653589793
HALF_PI = 1.5707963267948966

# fdlibm e_rem_pio2.c: pi/2 in two pieces (33 bits + tail), 2/pi
_INV_PIO2 = 6.36619772367581382433e-01
_PIO2_1 = 1.57079632673412561417e00
_PIO2_1T = 6.07710050650619224932e-11

# fdlibm k_sin.c / k_cos.c
_S1 = -1.66666666666666324348e-01
_S2 = 8.33333333332248946124e-03
_S3 = -1.98412698298579493134e-04
_S4 = 2.75573137070700676789e-06
_S5 = -2.50507602534068634195e-08
_S6 = 1.58969099521155010221e-10
_C1 = 4.16666666666666019037e-02
_C2 = -1.38888888888741095749e-03
_C3 = 2.48015872894767294178e-05
_C4 = -2.75573143513906633035e-07
_C5 = 2.08757232129817482790e-09
_C6 = -1.13596475577881948265e-11

# fdlibm s_atan.c
_ATAN_HI = (
    4.63647609000806093515e-01,
    7.85398163397448278999e-01,
    9.82793723247329054082e-01,
    1.57079632679489655800e00,
)
_ATAN_LO = (
    2.26987774529616870924e-17,
    3.06161699786838301793e-17,
    1.39033110312309984516e-17,
    6.12323399573676603587e-17,
)
_AT = (
    3.33333333333329318027e-01,
    -1.99999999998764832476e-01,
    1.42857142725034663711e-01,
    -1.11111104054623557880e-01,
    9.09088713343650656196e-02,
    -7.69187620504482999495e-02,
    6.66107313738753120669e-02,
    -5.83357013379057348645e-02,
    4.97687799461593236017e-02,
    -3.65315727442169155270e-02,
    1.62858201153657823623e-02,
)


def _k_sin(x):
    z = x * x
    r = _S2 + z * (_S3 + z * (_S4 + z * (_S5 + z * _S6)))
    return x + (z * x) * (_S1 + z * r)


def _k_cos(x):
    z = x * x
    r = z * (_C1 + z * (_C2 + z * (_C3 + z * (_C4 + z * (_C5 + z * _C6)))))
    return 1.0 - (0.5 * z - z * r)


def _reduce(x):
    """(n mod 4, r) with x = n * pi/2 + r and |r| <= pi/4 (to rounding)."""
    if -0.7853981633974483 <= x <= 0.7853981633974483:
        return 0, x
    n = _floor(x * _INV_PIO2 + 0.5)
    r = (x - n * _PIO2_1) - n * _PIO2_1T
    return int(n) & 3, r


def sin(x):
    n, r = _reduce(x)
    if n == 0:
        return _k_sin(r)
    if n == 1:
        return _k_cos(r)
    if n == 2:
        return -_k_sin(r)
    return -_k_cos(r)


def cos(x):
    n, r = _reduce(x)
    if n == 0:
        return _k_cos(r)
    if n == 1:
        return -_k_sin(r)
    if n == 2:
        return -_k_cos(r)
    return _k_sin(r)


def tan(x):
    return sin(x) / cos(x)


def atan(x):
    neg = x < 0.0
    if neg:
        x = -x
    if x < 0.4375:
        i = -1
    elif x < 1.1875:
        if x < 0.6875:
            i, x = 0, (2.0 * x - 1.0) / (2.0 + x)
        else:
            i, x = 1, (x - 1.0) / (x + 1.0)
    elif x < 2.4375:
        i, x = 2, (x - 1.5) / (1.0 + 1.5 * x)
    elif x == float("inf"):
        return -HALF_PI if neg else HALF_PI
    else:
        i, x = 3, -1.0 / x
    z = x * x
    w = z * z
    s1 = z * (_AT[0] + w * (_AT[2] + w * (_AT[4] + w * (_AT[6] + w * (_AT[8] + w * _AT[10])))))
    s2 = w * (_AT[1] + w * (_AT[3] + w * (_AT[5] + w * (_AT[7] + w * _AT[9]))))
    if i < 0:
        r = x - x * (s1 + s2)
    else:
        r = _ATAN_HI[i] - ((x * (s1 + s2) - _ATAN_LO[i]) - x)
    return -r if neg else r


def atan2(y, x):
    if x > 0.0:
        return atan(y / x)
    if x < 0.0:
        return atan(y / x) + PI if y >= 0.0 else atan(y / x) - PI
    if y > 0.0:
        return HALF_PI
    if y < 0.0:
        return -HALF_PI
    return 0.0


def acos(x):
    if x >= 1.0:
        return 0.0
    if x <= -1.0:
        return PI
    return atan2(_sqrt((1.0 - x) * (1.0 + x)), x)


def radians(deg):
    return deg * (PI / 180.0)


def fold(values):
    """Left-fold sum of floats (what sum() did before Python 3.12)."""
    it = iter(values)
    a = 0.0
    for v in it:
        a = a + v
    return a


def mat_vec(m, v):
    """3x3 (rows) times 3-vector, as tuples."""
    return (
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    )


def mat_mul(a, b):
    """3x3 times 3x3 (rows), as tuples."""
    return tuple(
        tuple(a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j] for j in range(3))
        for i in range(3)
    )


def transpose(m):
    return (
        (m[0][0], m[1][0], m[2][0]),
        (m[0][1], m[1][1], m[2][1]),
        (m[0][2], m[1][2], m[2][2]),
    )


def _cofactors(m):
    (a, b, c), (d, e, f), (g, h, i) = m
    return (
        (e * i - f * h, f * g - d * i, d * h - e * g),
        (c * h - b * i, a * i - c * g, b * g - a * h),
        (b * f - c * e, c * d - a * f, a * e - b * d),
    )


POLAR_MAX_ITERATIONS = 100
POLAR_TOL = 1e-15


def nearest_rotation(m):
    """Orthogonal polar factor of the 3x3 `m` (rows of floats): the orthogonal matrix
    nearest to it, what U @ Vt of its SVD is.  Newton's iteration X <- (X + X^-T) / 2;
    a singular matrix raises ValueError."""
    x = tuple(tuple(float(v) for v in row) for row in m)
    for _ in range(POLAR_MAX_ITERATIONS):
        c = _cofactors(x)
        det = x[0][0] * c[0][0] + x[0][1] * c[0][1] + x[0][2] * c[0][2]
        if det == 0.0:
            raise ValueError("nearest_rotation: singular matrix")
        y = tuple(tuple(0.5 * (x[i][j] + c[i][j] / det) for j in range(3)) for i in range(3))
        d = 0.0
        for i in range(3):
            for j in range(3):
                e = abs(y[i][j] - x[i][j])
                if e > d:
                    d = e
        x = y
        if d <= POLAR_TOL:
            break
    return x
