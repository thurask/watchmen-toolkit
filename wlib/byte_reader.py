"""Bounds-checked sequential reader of engine records: little- or big-endian
u32 / u8 / bool / f32 runs, counted arrays and length-prefixed strings.  A read
past the end raises ValueError."""

import struct


class ByteReader:
    """Bounds-checked sequential reader (raises ValueError past the end)."""

    def __init__(s, b, order="<"):
        s.b, s.p, s.o = b, 0, order

    def _need(s, n):
        if n < 0 or s.p + n > len(s.b):
            raise ValueError("read past end")

    def u32(s):
        s._need(4)
        v = struct.unpack_from(s.o + "I", s.b, s.p)[0]
        s.p += 4
        return v

    def u8(s):
        s._need(1)
        v = s.b[s.p]
        s.p += 1
        return v

    def boolean(s):
        v = s.u8()
        if v > 1:
            raise ValueError("bool %d" % v)
        return v

    def floats(s, n):
        s._need(4 * n)
        v = struct.unpack_from(s.o + "%df" % n, s.b, s.p)
        s.p += 4 * n
        return v

    def skip(s, n):
        s._need(n)
        s.p += n

    def count(s, item_bytes=1):
        """u32 element count, rejected when the elements cannot fit."""
        n = s.u32()
        if n * item_bytes > len(s.b) - s.p:
            raise ValueError("count %d" % n)
        return n

    def string(s):
        n = s.count()
        if n > 65536:  # merged-mesh names run to a few KB (TwilightMansion_Attic)
            raise ValueError("string %d" % n)
        v = s.b[s.p : s.p + n]
        s.p += n
        return v.split(b"\0", 1)[0].decode("latin1")
