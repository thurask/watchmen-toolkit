#!/usr/bin/env python3
"""`.terrain`, `.terraincoloringasset` and the buffer tail of `.detailmesh`.

Everything here follows the engine's loaders (addresses are in the PC Part 2
executable); what is a reading of the values and not of the code is listed in the
JSON under `inferred`, what has no meaning yet under `not_established`.

.terrain header  (TerrainAsset header reader 0x5397d0; integers and floats in the
block's byte order)

    f32   quad_size              asset +0x98 (1 / quad_size is kept at +0x9c)
    u32   sector_quads           +0xa0   edge of a sector in quads
    u32   sectors_x, sectors_z   +0xa4, +0xa8   sector index = x * sectors_z + z
    u32 n, n x (string, u64 id)  texture layers            (0x536198)
    u32 n, n x string            grass assets              (0x531590, list +0xdc)
    u32 n, n x string            detail mesh assets        (0x5315da, list +0xe8)
    u32 n, n x (string, u64 id)  second texture list       (0x53623a, list +0xf4)
    u32 n, n x record            rectangles drawn after the terrain (0x539930..)
        i32 x4  quad rectangle x0, z0, x1, z1 (0x530e01)
        u8      texture            index into the second texture list (0x53886b); alias b10
        f32     uv_rotation_deg    measured on the vertex buffers; alias f14
        u8 x3   b18, wrap_u, wrap_v   sampler address, 1 = wrap, 0 = clamp (0x4aebdb,
                                   0x4aec0e, 0x458794); aliases b19, b1a
        f32 x4  uv_scale, uv_offset   alias f1c
        u32 x4  place              sector, cell, vertex in sector, vertex in cell
        f32 x3, f32 x3, f32 x4     box min, box max, sphere
        u32 x3  vertex buffer      flags, vertex count, vertex format id (0x429e11)
    sectors_x * sectors_z times:  u8 present, then a sector (0x52e011)
        u8      enabled            sector +0x14, 0 = not drawn (0x536321); alias flag
        f32 x3 x4   drawn box min / max, box min / max
        f32 x3      origin
        (sector_quads / 32)^2 cells (0x539577), each a render sector (0x529a1a)
            f32 x3 x4   drawn box min / max, box min / max
            u32 x2      quads_x, quads_z
            f32 x3      origin
            f32         quad_size
            u32 x3      vertex buffer   flags, count, format id
            u8          has_index_buffer, then u32 x3: flags, byte count, primitive
                        type (table 0xc7f398, 1 = triangle list; alias x) (0x429f21)
            u32 x2      grass_mask, detail_mask   bit (id + 1) per asset used

.terrain.stream  (stream reader 0x535e15 -> 0x5345b1 -> 0x532a6a)

    the vertex buffer of every rectangle record, in header order
    per present sector, per cell:
        vertex buffer   count * stride        (48 bytes on PC = vertex format 8;
                                               36 bytes on Xbox 360 / PS3)
        index buffer    byte count, u16       (when the cell has one)
        u32 x2          the draw range of the whole cell (first index, end index)
        u32 n, n x (u32 first, u32 end)   pass 1 ranges    (drawn by 0x5370f7)
        u32 n, n x u32  the texture layer of each pass 1 range
        u32 n, n x (u32 first, u32 end)   pass 2 ranges    (drawn by 0x5371ef)
        u32 n, n x u32  the texture layer of each pass 2 range
        u8 x (quads_x+1)*(quads_z+1)   grass id + 1 per vertex, 0 = none (0x52e3ab)
        u8 x (quads_x+1)*(quads_z+1)   detail mesh id + 1 per vertex      (0x53260b)

The height field is not stored: the engine fills a 16-bit height texture from the
mesh when the stream is loaded (0x535e15).  `height_field` rebuilds the grid of
vertex heights from the vertex buffers.

.terraincoloringasset  (TerrainColoringAsset header reader 0x52da01): eight values,
three flags (COLORING_ALIASES names them) and one texture descriptor (0x429e77); the
stream is that texture.

.detailmesh  (DetailMeshAsset header reader 0x52de50): the property bag, then
`u8 has_mesh` and the two buffer descriptors.  The standalone Part 1 (PC, Xbox 360)
has no `has_mesh` byte: its reader (0x828dae50 in the Xbox 360 Part 1 image) reads the
two descriptors right after the bag.
"""

import os
import struct
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)

FORMAT = "kapow-terrain/2"
COLORING_FORMAT = "kapow-terraincoloring/1"
EVIDENCE = (
    "TerrainAsset header 0x5397d0, sector 0x52e011, render sector 0x529a1a; "
    "stream 0x535e15 / 0x532a6a"
)
#: vertex bytes per platform order (PC = vertex format 8 of the stride table 0xC791B0;
#: the console stride is read off the stream sizes: they tile exactly with 36)
VERTEX_STRIDE = {"<": 48, ">": 36}
CELL_QUADS = 32  # 0x539577: cells per sector edge = sector_quads * (1 / 32)

INFERRED = {
    "sectors[].drawn_bounds / cells[].drawn_bounds": (
        "box of the vertices the index buffer uses (an empty box, +FLT_MAX / -FLT_MAX, "
        "in a cell without index buffer); inferred from the values"
    ),
    "sectors[].bounds / cells[].bounds": "box of all vertices; inferred from the values",
    "decal_textures / decals": (
        "the name 'decal'; the code draws these rectangles after the terrain passes, each "
        "with texture `texture` of the second list (0x53886b, 0x52d310)"
    ),
    "decals[].uv_rotation_deg": (
        "measured on the decal vertex buffers: uv - 0.5 = R(angle) * (st - 0.5), st = "
        "position over the rectangle (131 decals, residual <= 6.1e-4); no run-time reader "
        "found"
    ),
    "decals[].uv_scale / uv_offset": (
        "measured: v = t / uv_scale[1] on 16 decals; the offset on one configuration only; "
        "the constructor default is (1, 1, 0, 0) (0x543d29)"
    ),
    "decals[].place": (
        "four u32 the PC loader reads as 16 raw bytes; sector / cell / vertex indices by "
        "agreement with quad_rect (see checks.decal_place_agree)"
    ),
    "decals[].bounds / sphere": "box and bounding sphere of the rectangle; from the values",
    "stream.cells[].pass2": (
        "the blend overlay: its triangles repeat pass 1 triangles under another texture "
        "layer (checks.pass2_in_pass1); pass 1 alone covers the surface once and is what "
        "`range` spans.  Read from the data, the draw calls are 0x5370f7 / 0x5371ef"
    ),
    "stream.vertex layout on consoles": (
        "36-byte vertex = position, packed normal, colour, half4 uv, packed tangent and "
        "bitangent; matched against the PC values, not read from console code"
    ),
}
NOT_ESTABLISHED = ["decals[].b18", "decals[].uv_offset (how it enters the UV)"]
#: (name read from the loader, offset-style key kept as an alias) of the terrain header.
#: parse() writes both; build() takes the name when the dict has it, else the alias.
DECAL_ALIASES = (
    ("texture", "b10"),  # u8 index into decal_textures (0x53886b); out of range: not drawn
    ("uv_rotation_deg", "f14"),
    ("wrap_u", "b19"),  # sampler address U: 1 = wrap, 0 = clamp (0x4aebdb, 0x458794)
    ("wrap_v", "b1a"),  # sampler address V (0x4aec0e)
)
SECTOR_ALIASES = (("enabled", "flag"),)  # sector +0x14; 0 = not drawn (0x536321)


def _named(d, name, alias):
    """d[name] when the dict has it, else d[alias] (a JSON written before the names)."""
    return d[name] if name in d else d[alias]


def _read_bytes(path):
    """The file's bytes; the handle is closed before returning."""
    with open(path, "rb") as fh:
        return fh.read()


class TerrainError(ValueError):
    pass


# ---------------------------------------------------------------------------
# reader / writer
# ---------------------------------------------------------------------------
def _fl(x):
    """A float32 as a JSON-safe value: the float, or {"f32": "hexbits"} when not finite."""
    if x != x or x in (float("inf"), float("-inf")):
        return {"f32": struct.pack(">f", x).hex()}
    return x


def _unfl(v):
    if isinstance(v, dict):
        return struct.unpack(">f", bytes.fromhex(v["f32"]))[0]
    return v


class _Rd:
    def __init__(self, b, order):
        self.b, self.p, self.o = b, 0, order

    def _need(self, n):
        if self.p + n > len(self.b):
            raise TerrainError("read of %d bytes at %d passes the end" % (n, self.p))

    def u32(self):
        self._need(4)
        (v,) = struct.unpack_from(self.o + "I", self.b, self.p)
        self.p += 4
        return v

    def i32(self):
        self._need(4)
        (v,) = struct.unpack_from(self.o + "i", self.b, self.p)
        self.p += 4
        return v

    def f32(self):
        self._need(4)
        (v,) = struct.unpack_from(self.o + "f", self.b, self.p)
        self.p += 4
        return _fl(v)

    def vec(self, n):
        return [self.f32() for _ in range(n)]

    def u8(self):
        self._need(1)
        v = self.b[self.p]
        self.p += 1
        return v

    def flag(self):
        v = self.u8()
        if v > 1:
            raise TerrainError("flag byte %d at %d" % (v, self.p - 1))
        return bool(v)

    def count(self, limit):
        v = self.u32()
        if v > limit:
            raise TerrainError("count %d at %d" % (v, self.p - 4))
        return v

    def string(self):
        n = self.count(1024)
        self._need(n)
        raw = self.b[self.p : self.p + n]
        self.p += n
        if not raw.endswith(b"\0"):
            raise TerrainError("string at %d is not terminated" % (self.p - n))
        return raw[:-1].decode("latin1")

    def ident(self):
        """u64 id: raw bytes as hex (as the JSON always had it) and the value, which
        is stored as two u32, low word first."""
        self._need(8)
        raw = self.b[self.p : self.p + 8]
        lo, hi = struct.unpack_from(self.o + "II", raw, 0)
        self.p += 8
        return raw.hex(), "0x%016x" % ((hi << 32) | lo)

    def vbuf(self):
        return {"flags": self.u32(), "count": self.u32(), "format": self.u32()}

    def ibuf(self):
        d = {"flags": self.u32(), "bytes": self.u32(), "x": self.u32()}
        d["primitive_type"] = d["x"]  # IndexBuffer +0xc; table 0xc7f398, 1 = triangle list
        return d


class _Wr:
    def __init__(self, order):
        self.o, self.out = order, []

    def u32(self, *v):
        self.out.append(struct.pack(self.o + "%dI" % len(v), *v))

    def i32(self, *v):
        self.out.append(struct.pack(self.o + "%di" % len(v), *v))

    def f32(self, *v):
        self.out.append(struct.pack(self.o + "%df" % len(v), *[_unfl(x) for x in v]))

    def u8(self, v):
        self.out.append(bytes([int(v)]))

    def string(self, s):
        raw = s.encode("latin1") + b"\0"
        self.u32(len(raw))
        self.out.append(raw)

    def raw(self, b):
        self.out.append(bytes(b))

    def bytes(self):
        return b"".join(self.out)


def detect_order(data):
    """'<' or '>' for a .terrain header: sector_quads is a small multiple of 32."""
    for bo in "<>":
        try:
            q, sq, sx, sz = struct.unpack_from(bo + "f3I", data, 0)
        except struct.error:
            break
        if 0 < sq <= 4096 and 0 < sx <= 4096 and 0 < sz <= 4096 and 1e-3 < q < 1e3:
            return bo
    raise TerrainError("not a .terrain header")


def _box(r):
    return [r.vec(3), r.vec(3)]


def parse(data, order=None):
    """.terrain header -> JSON dict (format kapow-terrain/2); raises TerrainError when
    the file does not follow the loader's grammar to its last byte."""
    bo = order or detect_order(data)
    r = _Rd(data, bo)
    doc = {"format": FORMAT, "evidence": EVIDENCE, "order": bo}
    doc["quad_size"] = r.f32()
    doc["sector_quads"] = r.u32()
    doc["sectors_x"] = r.u32()
    doc["sectors_z"] = r.u32()
    sq = doc["sector_quads"]
    if not 0 < sq <= 4096 or sq % CELL_QUADS or doc["sectors_x"] > 4096 or doc["sectors_z"] > 4096:
        raise TerrainError(
            "sector_quads %d / grid %d x %d" % (sq, doc["sectors_x"], doc["sectors_z"])
        )

    def with_ids():
        out = []
        for _ in range(r.count(4096)):
            path = r.string()
            raw, val = r.ident()
            out.append({"path": path, "id": raw, "unique_id": val})
        return out

    doc["texture_layers"] = with_ids()
    doc["grass"] = [r.string() for _ in range(r.count(4096))]
    doc["detailmeshes"] = [r.string() for _ in range(r.count(4096))]
    doc["decal_textures"] = with_ids()
    decals = []
    for _ in range(r.count(1 << 20)):
        d = {"quad_rect": [r.i32(), r.i32(), r.i32(), r.i32()]}
        d["b10"] = r.u8()
        d["f14"] = r.f32()
        d["b18"], d["b19"], d["b1a"] = r.u8(), r.u8(), r.u8()
        d["f1c"] = r.vec(4)
        for name, alias in DECAL_ALIASES:
            d[name] = d[alias]
        d["uv_scale"], d["uv_offset"] = d["f1c"][0:2], d["f1c"][2:4]
        sec, cell, sv, cv = r.u32(), r.u32(), r.u32(), r.u32()
        d["place"] = {"sector": sec, "cell": cell, "sector_vertex": sv, "cell_vertex": cv}
        d["bounds"] = _box(r)
        d["sphere"] = r.vec(4)
        d["vertex_buffer"] = r.vbuf()
        decals.append(d)
    doc["decals"] = decals
    side = sq // CELL_QUADS
    doc["cells_per_sector"] = side * side
    sectors = []
    for i in range(doc["sectors_x"] * doc["sectors_z"]):
        if not r.flag():
            continue
        s = {"index": i, "x": i // doc["sectors_z"], "z": i % doc["sectors_z"]}
        s["flag"] = r.u8()
        s["enabled"] = s["flag"]
        s["drawn_bounds"] = _box(r)
        s["bounds"] = _box(r)
        s["origin"] = r.vec(3)
        cells = []
        for _ in range(side * side):
            c = {"drawn_bounds": _box(r), "bounds": _box(r)}
            c["quads_x"], c["quads_z"] = r.u32(), r.u32()
            c["origin"] = r.vec(3)
            c["quad_size"] = r.f32()
            c["vertex_buffer"] = r.vbuf()
            c["index_buffer"] = r.ibuf() if r.flag() else None
            c["grass_mask"], c["detail_mask"] = r.u32(), r.u32()
            if c["quads_x"] > 4096 or c["quads_z"] > 4096:
                raise TerrainError("cell of %d x %d quads" % (c["quads_x"], c["quads_z"]))
            cells.append(c)
        s["cells"] = cells
        sectors.append(s)
    doc["sectors_present"] = len(sectors)
    doc["sectors"] = sectors
    if r.p != len(data):
        raise TerrainError("header ends at %d, the file at %d" % (r.p, len(data)))
    doc["tail_bytes"] = 0
    doc["inferred"] = dict(INFERRED)
    doc["not_established"] = list(NOT_ESTABLISHED)
    return doc


def build(doc):
    """The header bytes of a parse() result (byte-exact)."""
    w = _Wr(doc["order"])
    w.f32(doc["quad_size"])
    w.u32(doc["sector_quads"], doc["sectors_x"], doc["sectors_z"])

    def with_ids(lst):
        w.u32(len(lst))
        for e in lst:
            w.string(e["path"])
            w.raw(bytes.fromhex(e["id"]))

    def strings(lst):
        w.u32(len(lst))
        for s in lst:
            w.string(s)

    def box(b):
        w.f32(*b[0])
        w.f32(*b[1])

    def vbuf(v):
        w.u32(v["flags"], v["count"], v["format"])

    with_ids(doc["texture_layers"])
    strings(doc["grass"])
    strings(doc["detailmeshes"])
    with_ids(doc["decal_textures"])
    w.u32(len(doc["decals"]))
    for d in doc["decals"]:
        w.i32(*d["quad_rect"])
        w.u8(_named(d, "texture", "b10"))
        w.f32(_named(d, "uv_rotation_deg", "f14"))
        w.u8(d["b18"])
        w.u8(_named(d, "wrap_u", "b19"))
        w.u8(_named(d, "wrap_v", "b1a"))
        if "uv_scale" in d and "uv_offset" in d:
            w.f32(*(list(d["uv_scale"]) + list(d["uv_offset"])))
        else:
            w.f32(*d["f1c"])
        p = d["place"]
        w.u32(p["sector"], p["cell"], p["sector_vertex"], p["cell_vertex"])
        box(d["bounds"])
        w.f32(*d["sphere"])
        vbuf(d["vertex_buffer"])
    by_index = {s["index"]: s for s in doc["sectors"]}
    for i in range(doc["sectors_x"] * doc["sectors_z"]):
        s = by_index.get(i)
        w.u8(1 if s else 0)
        if not s:
            continue
        w.u8(_named(s, "enabled", "flag"))
        box(s["drawn_bounds"])
        box(s["bounds"])
        w.f32(*s["origin"])
        for c in s["cells"]:
            box(c["drawn_bounds"])
            box(c["bounds"])
            w.u32(c["quads_x"], c["quads_z"])
            w.f32(*c["origin"])
            w.f32(c["quad_size"])
            vbuf(c["vertex_buffer"])
            ib = c["index_buffer"]
            w.u8(1 if ib else 0)
            if ib:
                w.u32(ib["flags"], ib["bytes"], _named(ib, "primitive_type", "x"))
            w.u32(c["grass_mask"], c["detail_mask"])
    return w.bytes()


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------
def stream_layout(doc, stream):
    """Walk `.terrain.stream` as the loader does.  Returns
    {stride, bytes, decoded_bytes, leftover_bytes, decals: [{offset, count}],
     cells: [{sector, cell, vertex_offset, vertex_count, index_offset, index_count,
              range, pass1: [{layer, first, end}], pass2: [...],
              grass_offset, detail_offset, map_bytes}]}.
    Raises TerrainError when a read passes the end of the stream."""
    bo = doc["order"]
    stride = VERTEX_STRIDE[bo]
    n = len(stream)
    p = 0

    def need(k):
        if p + k > n:
            raise TerrainError("stream: %d bytes at %d pass the end (%d)" % (k, p, n))

    def u32s(k):
        nonlocal p
        need(4 * k)
        v = struct.unpack_from(bo + "%dI" % k, stream, p)
        p += 4 * k
        return v

    out = {"stride": stride, "bytes": n, "decals": [], "cells": []}
    for d in doc["decals"]:
        cnt = d["vertex_buffer"]["count"]
        need(cnt * stride)
        out["decals"].append({"offset": p, "count": cnt})
        p += cnt * stride
    for s in doc["sectors"]:
        for ci, c in enumerate(s["cells"]):
            e = {"sector": s["index"], "cell": ci, "vertex_offset": p}
            e["vertex_count"] = c["vertex_buffer"]["count"]
            need(e["vertex_count"] * stride)
            p += e["vertex_count"] * stride
            ib = c["index_buffer"]
            e["index_offset"] = p if ib else None
            e["index_count"] = ib["bytes"] // 2 if ib else 0
            if ib:
                need(ib["bytes"])
                p += ib["bytes"]
            e["range"] = list(u32s(2))
            for key in ("pass1", "pass2"):
                (k,) = u32s(1)
                if k > 4096:
                    raise TerrainError("stream: %d ranges at %d" % (k, p - 4))
                rng = u32s(2 * k)
                (k2,) = u32s(1)
                if k2 != k:
                    raise TerrainError("stream: %d ranges but %d layer ids at %d" % (k, k2, p))
                ids = u32s(k)
                e[key] = [
                    {"layer": ids[i], "first": rng[2 * i], "end": rng[2 * i + 1]} for i in range(k)
                ]
            m = (c["quads_x"] + 1) * (c["quads_z"] + 1)
            need(2 * m)
            e["grass_offset"], e["detail_offset"], e["map_bytes"] = p, p + m, m
            p += 2 * m
            out["cells"].append(e)
    out["decoded_bytes"] = p
    out["leftover_bytes"] = n - p
    return out


def _np():
    import numpy as np

    return np


def _dec1110(u):
    """Console packed normal (x:11 y:11 z:10 signed, LSB first) as float arrays; the
    rule watchmen_extract._dec1110 solved for model vertices."""
    np = _np()
    x = (u & 0x7FF).astype(np.int32)
    y = ((u >> 11) & 0x7FF).astype(np.int32)
    z = ((u >> 22) & 0x3FF).astype(np.int32)
    x = np.where(x >= 0x400, x - 0x800, x)
    y = np.where(y >= 0x400, y - 0x800, y)
    z = np.where(z >= 0x200, z - 0x400, z)
    return np.stack([x / 1023.0, y / 1023.0, z / 511.0], -1).astype(np.float32)


def decode_vertices(stream, offset, count, order, ps3=None):
    """One vertex buffer -> {position (n,3) f4, normal (n,3) f4, color (n,4) u1 RGBA,
    uv (n,2) f4}.  The colour's alpha is the terrain texture layer of the vertex.
    `ps3`: True / False picks the console colour byte order (PS3 R,G,B,A; Xbox 360
    A,R,G,B); None = guess from the alpha values (a layer id is a small number)."""
    np = _np()
    stride = VERTEX_STRIDE[order]
    a = np.frombuffer(stream, np.uint8, count * stride, offset).reshape(count, stride)
    col = lambda lo, hi: np.ascontiguousarray(a[:, lo:hi])
    if order == "<":
        pos = col(0, 12).view("<f4")
        nrm = col(12, 18).view("<f2").astype(np.float32)
        bgra = col(20, 24)
        rgba = bgra[:, [2, 1, 0, 3]]
        uv = col(24, 28).view("<f2").astype(np.float32)
    else:
        pos = col(0, 12).view(">f4").astype("<f4")
        nrm = _dec1110(col(12, 16).view(">u4")[:, 0])
        c = col(16, 20)
        if ps3 is None:
            ps3 = bool(count) and int(c[:, 0].max()) > int(c[:, 3].max())
        rgba = c if ps3 else c[:, [1, 2, 3, 0]]
        uv = col(20, 24).view(">f2").astype(np.float32)
    return {"position": pos, "normal": nrm, "color": np.ascontiguousarray(rgba), "uv": uv}


def decode_indices(stream, offset, count, order):
    np = _np()
    return np.frombuffer(stream, order + "u2", count, offset).astype(np.uint32)


def _console_is_ps3(doc, stream, lay):
    """Colour byte order of a console stream: over all cells, the byte that holds the
    layer id stays below the layer count.  None when the stream cannot tell."""
    np = _np()
    stride = VERTEX_STRIDE[">"]
    nl = max(1, len(doc["texture_layers"]))
    first = last = 0
    for e in lay["cells"]:
        a = np.frombuffer(stream, np.uint8, e["vertex_count"] * stride, e["vertex_offset"])
        a = a.reshape(-1, stride)
        first = max(first, int(a[:, 16].max()) if len(a) else 0)
        last = max(last, int(a[:, 19].max()) if len(a) else 0)
    if first < nl <= last:
        return False  # Xbox 360: A,R,G,B
    if last < nl <= first:
        return True  # PS3: R,G,B,A
    return None


def decode_stream(doc, stream):
    """stream_layout() plus numpy arrays per cell: `vertices` (decode_vertices), `indices`,
    `grass` and `detail` byte maps (quads_z+1, quads_x+1)."""
    np = _np()
    lay = stream_layout(doc, stream)
    bo = doc["order"]
    ps3 = _console_is_ps3(doc, stream, lay) if bo == ">" else None
    lay["console_color_order"] = (
        None if bo == "<" else {True: "RGBA", False: "ARGB", None: "not established"}[ps3]
    )
    cells = {(s["index"], i): c for s in doc["sectors"] for i, c in enumerate(s["cells"])}
    for e in lay["cells"]:
        c = cells[(e["sector"], e["cell"])]
        e["vertices"] = decode_vertices(stream, e["vertex_offset"], e["vertex_count"], bo, ps3)
        e["indices"] = (
            decode_indices(stream, e["index_offset"], e["index_count"], bo)
            if e["index_offset"] is not None
            else np.zeros(0, np.uint32)
        )
        shape = (c["quads_z"] + 1, c["quads_x"] + 1)
        m = e["map_bytes"]
        e["grass"] = np.frombuffer(stream, np.uint8, m, e["grass_offset"]).reshape(shape)
        e["detail"] = np.frombuffer(stream, np.uint8, m, e["detail_offset"]).reshape(shape)
    for d, e in zip(doc["decals"], lay["decals"]):
        e["vertices"] = decode_vertices(stream, e["offset"], e["count"], bo, ps3)
    return lay


def grid_origin(doc):
    """(x0, z0) of the terrain grid: the terrain is centred on the asset origin
    (checked against every sector origin by `checks`)."""
    q = _unfl(doc["quad_size"])
    sq = doc["sector_quads"]
    return (-0.5 * doc["sectors_x"] * sq * q, -0.5 * doc["sectors_z"] * sq * q)


def height_field(doc, lay):
    """Vertex grids of the whole terrain from a decode_stream() result:
    {width, depth (vertices), height (depth, width) f4 with NaN where no sector is
     stored, layer (u1, 255 = no data), tint (depth, width, 3) u1, grass, detail (u1),
     drawn (depth-1, width-1) bool per quad: at least one triangle uses the quad,
     mismatched: vertices whose x / z is not on the grid}.  Row = z, column = x,
    both ascending, engine axes."""
    np = _np()
    q = _unfl(doc["quad_size"])
    sq = doc["sector_quads"]
    W = doc["sectors_x"] * sq + 1
    D = doc["sectors_z"] * sq + 1
    x0, z0 = grid_origin(doc)
    H = np.full((D, W), np.nan, np.float32)
    L = np.full((D, W), 255, np.uint8)
    T = np.zeros((D, W, 3), np.uint8)
    G = np.zeros((D, W), np.uint8)
    DM = np.zeros((D, W), np.uint8)
    drawn = np.zeros((D - 1, W - 1), bool)
    bad = 0
    cells = {(s["index"], i): c for s in doc["sectors"] for i, c in enumerate(s["cells"])}
    for e in lay["cells"]:
        c = cells[(e["sector"], e["cell"])]
        v = e["vertices"]
        pos = v["position"]
        fx = (pos[:, 0] - x0) / q
        fz = (pos[:, 2] - z0) / q
        ix = np.rint(fx).astype(np.int64)
        iz = np.rint(fz).astype(np.int64)
        ok = (
            (np.abs(fx - ix) < 1e-3)
            & (np.abs(fz - iz) < 1e-3)
            & (ix >= 0)
            & (ix < W)
            & (iz >= 0)
            & (iz < D)
        )
        bad += int((~ok).sum())
        H[iz[ok], ix[ok]] = pos[ok, 1]
        L[iz[ok], ix[ok]] = v["color"][ok, 3]
        T[iz[ok], ix[ok]] = v["color"][ok, :3]
        n = (c["quads_x"] + 1) * (c["quads_z"] + 1)
        if len(pos) == n and ok.all():
            G[iz, ix] = e["grass"].reshape(-1)
            DM[iz, ix] = e["detail"].reshape(-1)
        tri = e["indices"][e["range"][0] : e["range"][1]] if e["index_count"] else e["indices"]
        tri = tri[: len(tri) // 3 * 3].reshape(-1, 3)
        if len(tri):
            tri = tri[(tri < len(pos)).all(axis=1)]
            qx = ix[tri].min(axis=1)
            qz = iz[tri].min(axis=1)
            keep = (qx >= 0) & (qx < W - 1) & (qz >= 0) & (qz < D - 1)
            drawn[qz[keep], qx[keep]] = True
    return {
        "width": W,
        "depth": D,
        "height": H,
        "layer": L,
        "tint": T,
        "grass": G,
        "detail": DM,
        "drawn": drawn,
        "mismatched": bad,
    }


def checks(doc, lay=None):
    """Agreement counts that test the inferred fields (JSON-safe):
    decal_place_agree / decals, sector_origin_agree / sectors and, with a decoded
    stream, cell_bounds_agree / cells, drawn_bounds_agree / cells_with_indices,
    range_end_is_index_count, pass_ranges_tile, masks_cover_ids (every grass /
    detail id of the byte maps has its bit in the cell's mask), pass1_triangles_unique
    and pass2_in_pass1 (every pass 2 triangle is also a pass 1 triangle)."""
    np = None
    q = _unfl(doc["quad_size"])
    sq = doc["sector_quads"]
    side = sq // CELL_QUADS
    x0, z0 = grid_origin(doc)
    out = {"decals": len(doc["decals"]), "sectors": len(doc["sectors"])}
    agree = 0
    for d in doc["decals"]:
        # the place names a grid vertex twice: inside its sector and inside its cell
        # (a vertex on a sector / cell edge is filed under the lower neighbour)
        p = d["place"]
        sx, sz = divmod(p["sector"], max(1, doc["sectors_z"]))
        vz, vx = divmod(p["sector_vertex"], sq + 1)
        cz, cx = divmod(p["cell"], max(1, side))
        wz, wx = divmod(p["cell_vertex"], CELL_QUADS + 1)
        g1 = (sx * sq + vx, sz * sq + vz)
        g2 = (sx * sq + cx * CELL_QUADS + wx, sz * sq + cz * CELL_QUADS + wz)
        if g1 == g2 == (d["quad_rect"][0], d["quad_rect"][1]):
            agree += 1
    out["decal_place_agree"] = agree
    agree = 0
    for s in doc["sectors"]:
        o = [_unfl(v) for v in s["origin"]]
        if abs(o[0] - (x0 + s["x"] * sq * q)) < 1e-3 and abs(o[2] - (z0 + s["z"] * sq * q)) < 1e-3:
            agree += 1
    out["sector_origin_agree"] = agree
    if lay is None or not lay["cells"] or "vertices" not in lay["cells"][0]:
        return out
    np = _np()
    cells = {(s["index"], i): c for s in doc["sectors"] for i, c in enumerate(s["cells"])}
    nb = nd = ni = ne = nt = nm = n1 = n2 = 0
    for e in lay["cells"]:
        c = cells[(e["sector"], e["cell"])]
        pos = e["vertices"]["position"]
        box = lambda b: np.array([[_unfl(x) for x in b[0]], [_unfl(x) for x in b[1]]], np.float64)
        if len(pos):
            got = np.array([pos.min(axis=0), pos.max(axis=0)], np.float64)
            # y is stored with a margin (the boxes are 0.1 above / below flat ground)
            b = box(c["bounds"])
            if np.abs(got[:, [0, 2]] - b[:, [0, 2]]).max() < 1e-2 and (
                b[0, 1] <= got[0, 1] + 1e-3 and b[1, 1] >= got[1, 1] - 1e-3
            ):
                nb += 1
        idx = e["indices"]
        if len(idx):
            ni += 1
            used = pos[idx[idx < len(pos)]]
            got = np.array([used.min(axis=0), used.max(axis=0)], np.float64)
            if np.abs(got - box(c["drawn_bounds"])).max() < 1e-2:
                nd += 1
        spans = [(r["first"], r["end"]) for r in e["pass1"]] + [
            (r["first"], r["end"]) for r in e["pass2"]
        ]
        if (spans[-1][1] if spans else 0) == e["index_count"]:
            ne += 1
        if all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1)) and (
            not spans or spans[0][0] == 0
        ):
            nt += 1
        gm = sum(1 << int(v) for v in np.unique(e["grass"]) if v)
        dm = sum(1 << int(v) for v in np.unique(e["detail"]) if v)
        if not gm & ~c["grass_mask"] and not dm & ~c["detail_mask"]:
            nm += 1
        if len(idx) and e["range"][1] <= len(idx):
            tri = lambda a, b: set(
                map(tuple, np.sort(idx[a : a + (b - a) // 3 * 3].reshape(-1, 3), axis=1).tolist())
            )
            t1 = tri(e["range"][0], e["range"][1])
            t2 = tri(e["range"][1], len(idx))
            if len(t1) == (e["range"][1] - e["range"][0]) // 3:
                n1 += 1
            if t2 <= t1:
                n2 += 1
        elif not len(idx):
            n1 += 1
            n2 += 1
    out.update(
        cells=len(lay["cells"]),
        cells_with_indices=ni,
        cell_bounds_agree=nb,
        drawn_bounds_agree=nd,
        range_end_is_index_count=ne,
        pass_ranges_tile=nt,
        masks_cover_ids=nm,
        pass1_triangles_unique=n1,
        pass2_in_pass1=n2,
    )
    return out


def stream_summary(lay):
    """The JSON part of a stream_layout() / decode_stream() result."""
    cells = []
    for e in lay["cells"]:
        cells.append(
            {
                k: e[k]
                for k in (
                    "sector",
                    "cell",
                    "vertex_offset",
                    "vertex_count",
                    "index_offset",
                    "index_count",
                    "range",
                    "pass1",
                    "pass2",
                    "grass_offset",
                    "detail_offset",
                    "map_bytes",
                )
            }
        )
    out = {
        "vertex_stride": lay["stride"],
        "bytes": lay["bytes"],
        "decoded_bytes": lay["decoded_bytes"],
        "leftover_bytes": lay["leftover_bytes"],
        "decal_vertex_buffers": [
            {"offset": d["offset"], "count": d["count"]} for d in lay["decals"]
        ],
        "cells": cells,
    }
    if lay.get("console_color_order"):
        out["console_color_order"] = lay["console_color_order"]
    return out


def to_json(data, order=None, stream=None):
    """.terrain -> JSON dict.  With `stream` the dict gets the `stream` section, the
    `height_field` description and `checks`.  A file the grammar does not fit gives a
    marked stub (`not_decoded`, `tail_bytes` = the file size) instead of raising."""
    try:
        doc = parse(data, order)
    except (TerrainError, struct.error) as ex:
        return {
            "format": FORMAT,
            "not_decoded": "terrain header: %s" % ex,
            "tail_bytes": len(data),
        }
    lay = None
    if stream:
        try:
            lay = decode_stream(doc, stream)
            doc["stream"] = stream_summary(lay)
        except ImportError:
            try:
                doc["stream"] = stream_summary(stream_layout(doc, stream))
            except TerrainError as ex:
                doc["stream"] = {"not_decoded": str(ex), "leftover_bytes": len(stream)}
        except (TerrainError, ValueError) as ex:
            lay = None
            doc["stream"] = {"not_decoded": str(ex), "leftover_bytes": len(stream)}
    doc["checks"] = checks(doc, lay)
    doc["_lay"] = lay  # for write_outputs; removed by it / by strip()
    return doc


def strip(doc):
    """Drop the in-memory stream arrays from a to_json() result (-> JSON-safe)."""
    doc.pop("_lay", None)
    return doc


# ---------------------------------------------------------------------------
# outputs: height / layer maps and a surface GLB
# ---------------------------------------------------------------------------
def _layer_name(doc, k):
    lst = doc["texture_layers"]
    if 0 <= k < len(lst):
        return os.path.splitext(lst[k]["path"].replace("\\", "/").rsplit("/", 1)[-1])[0]
    return "layer_%d" % k


def build_glb(doc, lay):
    """The terrain surface as GLB bytes: one node per texture layer, triangles from
    the pass 1 index ranges of every cell (each triangle once), POSITION / NORMAL / TEXCOORD_0 /
    COLOR_0 (the vertex tint; the layer id that sits in the colour's alpha is in the
    node name and `extras`).  Written in the frame of the toolkit's model exports
    (frame.finish_gltf: x negated and file winding by default).  None without numpy
    or without triangles."""
    import json

    import frame as _frame

    np = _np()
    per_layer = {}
    for e in lay["cells"]:
        idx = e["indices"]
        nv = e["vertex_count"]
        for r in e["pass1"]:  # pass 2 repeats pass 1 triangles (the blend overlay)
            tri = idx[r["first"] : r["end"]]
            tri = tri[: len(tri) // 3 * 3].reshape(-1, 3)
            tri = tri[(tri < nv).all(axis=1)]
            if len(tri):
                per_layer.setdefault(r["layer"], []).append((e, tri))
    if not per_layer:
        return None
    binbuf = bytearray()
    views, accessors, meshes, nodes, materials = [], [], [], [], []

    def view(raw, target):
        while len(binbuf) % 4:
            binbuf.append(0)
        views.append(
            {"buffer": 0, "byteOffset": len(binbuf), "byteLength": len(raw), "target": target}
        )
        binbuf.extend(raw)
        return len(views) - 1

    def acc(arr, typ, comp, target=34962, normalized=False, bounds=False):
        a = {
            "bufferView": view(arr.tobytes(), target),
            "componentType": comp,
            "count": int(len(arr)),
            "type": typ,
        }
        if normalized:
            a["normalized"] = True
        if bounds:
            a["min"] = [float(x) for x in arr.min(axis=0)]
            a["max"] = [float(x) for x in arr.max(axis=0)]
        accessors.append(a)
        return len(accessors) - 1

    for layer in sorted(per_layer):
        P, N, UV, C, I = [], [], [], [], []
        base = 0
        for e, tri in per_layer[layer]:
            used, inv = np.unique(tri.reshape(-1), return_inverse=True)
            v = e["vertices"]
            P.append(v["position"][used])
            n = v["normal"][used].astype(np.float32)
            ln = np.linalg.norm(n, axis=1, keepdims=True)
            N.append(np.where(ln > 1e-6, n / np.maximum(ln, 1e-6), [[0.0, 1.0, 0.0]]))
            UV.append(v["uv"][used])
            C.append(v["color"][used])
            # mirrored-frame documents wind against the file (as 1.3.0 wrote them);
            # frame.finish_gltf turns the true frame back to file order
            I.append((inv.reshape(-1, 3)[:, [0, 2, 1]] + base).astype(np.uint32))
            base += len(used)
        pos = np.concatenate(P).astype("<f4")
        col = np.concatenate(C).copy()
        col[:, 3] = 255
        prim = {
            "attributes": {
                "POSITION": acc(pos, "VEC3", 5126, bounds=True),
                "NORMAL": acc(np.concatenate(N).astype("<f4"), "VEC3", 5126),
                "TEXCOORD_0": acc(np.concatenate(UV).astype("<f4"), "VEC2", 5126),
                "COLOR_0": acc(col, "VEC4", 5121, normalized=True),
            },
            "indices": acc(np.concatenate(I).reshape(-1), "SCALAR", 5125, target=34963),
            "material": len(materials),
            "mode": 4,
        }
        name = _layer_name(doc, layer)
        tex = doc["texture_layers"][layer]["path"] if layer < len(doc["texture_layers"]) else None
        materials.append(
            {
                "name": name,
                "pbrMetallicRoughness": {"metallicFactor": 0.0, "roughnessFactor": 1.0},
                "extras": {"terrain_layer": int(layer), "texture": tex},
            }
        )
        meshes.append({"name": "layer_%d_%s" % (layer, name), "primitives": [prim]})
        nodes.append({"name": "layer_%d_%s" % (layer, name), "mesh": len(meshes) - 1})
    nodes.append({"name": "terrain", "children": list(range(len(nodes)))})
    while len(binbuf) % 4:
        binbuf.append(0)
    gltf = {
        "asset": {"version": "2.0", "generator": "watchmen-kapow-toolkit terrain_asset"},
        "scene": 0,
        "scenes": [{"nodes": [len(nodes) - 1]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(binbuf)}],
        "extras": {
            "format": FORMAT,
            "note": "terrain surface in asset space (the TerrainNode's transform is not "
            "applied); COLOR_0 is the vertex tint, the texture layer is per node",
        },
    }
    _frame.finish_gltf(gltf, binbuf)
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    out = bytearray(b"glTF" + struct.pack("<II", 2, 0))
    out += struct.pack("<I4s", len(js), b"JSON") + js
    out += struct.pack("<I4s", len(binbuf), b"BIN\0") + bytes(binbuf)
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


def write_outputs(doc, base, glb=True):
    """Write what a to_json(..., stream=...) result can give beside the asset:
        <base>.height.png   16-bit grey, 0 = no data, 1..65535 = min..max height
        <base>.layers.png   8-bit, the texture layer of every vertex (255 = no data)
        <base>.glb          the surface (build_glb), when `glb`
    and add the `height_field` section to the dict.  `base` = the asset path as a
    string.  Returns the list of files written; strips the stream arrays."""
    lay = doc.pop("_lay", None)
    written = []
    if lay is None:
        return written
    try:
        from PIL import Image
    except Exception:
        Image = None
    np = _np()
    hf = height_field(doc, lay)
    H = hf["height"]
    have = ~np.isnan(H)
    lo = float(H[have].min()) if have.any() else 0.0
    hi = float(H[have].max()) if have.any() else 0.0
    x0, z0 = grid_origin(doc)
    section = {
        "width": hf["width"],
        "depth": hf["depth"],
        "origin_xz": [x0, z0],
        "quad_size": doc["quad_size"],
        "axes": "row = z ascending, column = x ascending, engine axes (not reflected)",
        "min_height": lo,
        "max_height": hi,
        "vertices_with_data": int(have.sum()),
        "vertices_off_grid": hf["mismatched"],
        "quads_drawn": int(hf["drawn"].sum()),
        "quads_not_drawn": int((~hf["drawn"]).sum()),
        "source": "vertex positions of the stream (the file stores no height map; the "
        "engine fills its 16-bit height texture from the mesh at load, 0x535e15)",
    }
    if Image is not None and have.any():
        span = hi - lo
        px = np.zeros(H.shape, np.uint16)
        if span > 0:
            px[have] = (1 + np.rint((H[have] - lo) / span * 65534.0)).astype(np.uint16)
        else:
            px[have] = 1
        Image.fromarray(px).save(base + ".height.png")
        written.append(base + ".height.png")
        section["png"] = os.path.basename(base) + ".height.png"
        section["png_encoding"] = (
            "16-bit: 0 = no data; height = min_height + (value - 1) / 65534 * "
            "(max_height - min_height)"
        )
        Image.fromarray(hf["layer"]).save(base + ".layers.png")
        written.append(base + ".layers.png")
        section["layers_png"] = os.path.basename(base) + ".layers.png"
        section["layers_png_encoding"] = (
            "8-bit: index into texture_layers per vertex (the alpha of the vertex colour), "
            "255 = no data"
        )
    doc["height_field"] = section
    if glb:
        try:
            g = build_glb(doc, lay)
        except Exception as ex:  # frame.FrameError etc.: say so, keep the JSON
            doc["glb_not_written"] = str(ex)
            g = None
        if g:
            with open(base + ".glb", "wb") as f:
                f.write(g)
            written.append(base + ".glb")
            doc["glb"] = os.path.basename(base) + ".glb"
    return written


def notes(name, doc):
    """Log lines for one .terrain (never silent about what was not decoded)."""
    if doc.get("not_decoded"):
        return ["WARNING: terrain %s not decoded: %s" % (name, doc["not_decoded"])]
    out = []
    st = doc.get("stream")
    if st is None:
        out.append("note: terrain %s: no stream, header only" % name)
    elif st.get("not_decoded"):
        out.append("WARNING: terrain %s stream not decoded: %s" % (name, st["not_decoded"]))
    elif st["leftover_bytes"]:
        out.append(
            "WARNING: terrain %s: %d stream bytes not decoded" % (name, st["leftover_bytes"])
        )
    if doc.get("glb_not_written"):
        out.append("note: terrain %s: no GLB (%s)" % (name, doc["glb_not_written"]))
    return out


# ---------------------------------------------------------------------------
# .terraincoloringasset
# ---------------------------------------------------------------------------
_TCA = "4I2fIf3B"  # 35 bytes
_DESC = "5IBII"  # 29 bytes


def coloring_parse(data, order=None):
    """.terraincoloringasset header -> JSON dict (reader 0x52da01)."""
    if len(data) != struct.calcsize("<" + _TCA) + struct.calcsize("<" + _DESC):
        raise TerrainError("a terrain colouring header is 64 bytes, not %d" % len(data))
    bo = order
    if bo is None:
        for bo in "<>":
            w, h = struct.unpack_from(bo + "2I", data, 35)
            if 0 < w <= 16384 and 0 < h <= 16384:
                break
        else:
            raise TerrainError("no texture descriptor at 35")
    a0, a4, s98, s9c, fa8, fac, ub0, fb8, bbd, bbc, bbe = struct.unpack_from(bo + _TCA, data, 0)
    w, h, en, x, typ, alpha, mips, size = struct.unpack_from(bo + _DESC, data, 35)
    if max(bbd, bbc, bbe, alpha) > 1:
        raise TerrainError("flag byte above 1")
    doc = {
        "format": COLORING_FORMAT,
        "evidence": (
            "TerrainColoringAsset header 0x52da01; property getters 0x52cb15, 0x512aa3, "
            "0x52a213, 0x555e84, 0x52a21a, 0x5230b3, 0x53a5f8, 0x52a221, 0x52a228; bake "
            "0x52d646; texture descriptor 0x429e77"
        ),
        "order": bo,
        # asset offsets of the eleven values, in file order (aliases of the names below)
        "ua0": a0,
        "ua4": a4,
        "u98": s98,
        "u9c": s9c,
        "fa8": fa8,
        "fac": fac,
        "ub0": ub0,
        "fb8": fb8,
        "bbd": bbd,
        "bbc": bbc,
        "bbe": bbe,
        "texture": {
            "width": w,
            "height": h,
            "enum": en,
            "x": x,
            "usage": x,  # TextureBuffer +0x10 (0x456d46)
            "type": typ,
            "alpha": bool(alpha),
            "mips": mips,
            "size": size,
        },
        "inferred": {
            "texture as an ambient map": (
                "one 8-bit channel; the editor command that writes this asset is "
                "captioned 'Generate Terrain Ambient'"
            ),
        },
        "not_established": [],
        "leftover_bytes": 0,
    }
    for name, alias in COLORING_ALIASES:
        doc[name] = doc[alias]
    return doc


#: (name, offset-style alias) of the colouring header, in file order: the map size the
#: bake uses (0x52d646) and the asset's registered properties (getters in the evidence
#: string; numberOfBlurPasses, +0xb4, is not stored)
COLORING_ALIASES = (
    ("map_width", "ua0"),
    ("map_height", "ua4"),
    ("ambientTextureWidth", "u98"),
    ("ambientTextureHeight", "u9c"),
    ("ambientOcclusionBrightness", "fa8"),
    ("ambientOcclusionContrast", "fac"),
    ("numberOfRays", "ub0"),
    ("raycastLength", "fb8"),
    ("useTerrainAO", "bbd"),
    ("randomDistribution", "bbc"),
    ("blurTexture", "bbe"),
)


def coloring_build(doc):
    bo = doc["order"]
    t = doc["texture"]
    return struct.pack(
        bo + _TCA, *[_named(doc, name, alias) for name, alias in COLORING_ALIASES]
    ) + struct.pack(
        bo + _DESC,
        t["width"],
        t["height"],
        t["enum"],
        _named(t, "usage", "x"),
        t["type"],
        int(t["alpha"]),
        t["mips"],
        t["size"],
    )


def coloring_image(doc, stream):
    """The texture of a colouring asset as a numpy array, or None when the platform
    layout / format is not decoded.  Sets doc['stream'] = {bytes, expected_bytes,
    leftover_bytes}."""
    import watchmen_extract as wx

    t = doc["texture"]
    en, w, h = t["enum"], t["width"], t["height"]
    info = {"bytes": len(stream)}
    doc["stream"] = info
    if en not in wx.TEX_FMT or t["type"] != 1:
        info["not_decoded"] = "texture format id %d / type %d" % (en, t["type"])
        info["leftover_bytes"] = len(stream)
        return None
    t["fmt"] = wx.TEX_FMT[en][0]
    if doc["order"] == "<":
        want = wx._chain_bytes_exact(en, w, h, t["mips"])
        kind, unit = wx.TEX_FMT[en][1]
        if kind == "lin":  # rows are padded to 4 bytes: take them apart
            np = _np()
            pitch = (w * unit + 3) & ~3
            if len(stream) < pitch * h:
                info["not_decoded"] = "stream shorter than %d rows of %d bytes" % (h, pitch)
                info["leftover_bytes"] = len(stream)
                return None
            rows = np.frombuffer(stream, np.uint8, pitch * h).reshape(h, pitch)
            img = wx._decode_one_layer(
                np.ascontiguousarray(rows[:, : w * unit]).tobytes(), en, w, h
            )
        else:
            img = wx._decode_one_layer(stream, en, w, h)
    elif t["size"]:
        want = t["size"]
        img = wx._x360_base_level(stream, en, w, h) if len(stream) >= want else None
        if img is not None and min(w, h) < 4 and wx.TEX_FMT[en][1][0] == "blk":
            # measured: the 1 x 1 map of Part 1 reads 204 here and 255 on PC / PS3
            info["unverified"] = (
                "Xbox 360 map smaller than one 4x4 block: where its texels sit in the "
                "stored block is not established, the image may be wrong"
            )
    else:
        want = len(stream)
        if len(stream) >= 36:
            (n,) = struct.unpack_from(">I", stream, 8)
            want = 36 + n
        img = wx._ps3_layer_image(stream[36:], {"enum": en, "aw": w, "ah": h}, False)
    info["expected_bytes"] = want
    info["leftover_bytes"] = len(stream) - want
    if img is None:
        info["not_decoded"] = "%s %dx%d image not decoded" % (t["fmt"], w, h)
    return img


def coloring_to_json(data, order=None):
    try:
        return coloring_parse(data, order)
    except (TerrainError, struct.error) as ex:
        return {
            "format": COLORING_FORMAT,
            "not_decoded": "terrain colouring header: %s" % ex,
            "leftover_bytes": len(data),
        }


def coloring_write(doc, stream, base):
    """Write `<base>.png` from the stream; returns the files written."""
    if doc.get("not_decoded") or not stream:
        if not stream and not doc.get("not_decoded"):
            doc["stream"] = {"bytes": 0, "not_decoded": "no stream"}
        return []
    try:
        from PIL import Image

        img = coloring_image(doc, stream)
    except ImportError:
        doc["stream"] = {"bytes": len(stream), "not_decoded": "numpy / Pillow not installed"}
        return []
    if img is None:
        return []
    Image.fromarray(img).save(base + ".png")
    doc["png"] = os.path.basename(base) + ".png"
    return [base + ".png"]


def coloring_notes(name, doc):
    if doc.get("not_decoded"):
        return ["WARNING: terrain colouring %s not decoded: %s" % (name, doc["not_decoded"])]
    st = doc.get("stream") or {}
    if st.get("not_decoded"):
        return ["WARNING: terrain colouring %s: image not written: %s" % (name, st["not_decoded"])]
    if st.get("leftover_bytes"):
        return [
            "WARNING: terrain colouring %s: %d stream bytes not decoded"
            % (name, st["leftover_bytes"])
        ]
    if st.get("unverified"):
        return ["note: terrain colouring %s: %s" % (name, st["unverified"])]
    return []


# ---------------------------------------------------------------------------
# .detailmesh: the bytes after the property bag
# ---------------------------------------------------------------------------
DETAIL_VERTEX_FORMAT = 7  # 60 bytes: pos, FLOAT3 normal, colour, FLOAT2 uv, 2 x FLOAT3
#: vertex bytes of the format ids a .detailmesh uses (PC stride table 0xC791B0, entry 7)
DETAIL_FORMAT_STRIDE = {7: 60}
DETAIL_INFERRED = {
    "stream.vertex_stride": (
        "derived from the stream size: (stream bytes - the three lists - index bytes) / "
        "vertex count.  It is not read from the file, so leftover_bytes = 0 only says that "
        "the vertex count divides what is left; stream.format_stride is the stride the PC "
        "table 0xC791B0 gives for the vertex format id and stream.stride_matches_format "
        "says whether the two agree"
    ),
    "stream.format_stride on consoles": (
        "the table is the PC executable's; the Xbox 360 table (0x8308b6e0, "
        "watchmen_extract.CONSOLE_VERTEX_STRIDES) gives 60 for format 7 as well and the "
        "console files tile with it; the PS3 table was not read"
    ),
}
DETAIL_NOT_ESTABLISHED = []
#: what the entries of the three u32 lists of a .detailmesh.stream are, in file order
DETAIL_LIST_NAMES = ["first_index_a", "first_index_b", "triangle_count"]


def detail_tail(tail, order="<"):
    """The bytes a .detailmesh has after its property bag (reader 0x52de50):
    [u8 has_mesh] and, when set, the vertex buffer (flags, count, format id; 0x429e11)
    and index buffer (flags, byte count, primitive type -- JSON keys primitive_type and
    x; 0x429f21) descriptors.  The standalone
    Part 1 layout (PC / Xbox 360) has the two descriptors without the flag byte.
    Returns (mesh dict, leftover byte count); mesh is None when the bytes fit neither."""
    n = len(tail)
    if n == 1 and tail[0] == 0:
        return {"has_mesh": False, "has_mesh_byte": True}, 0
    if n == 25 and tail[0] == 1:
        w = struct.unpack_from(order + "6I", tail, 1)
        flag = True
    elif n == 24:
        w = struct.unpack_from(order + "6I", tail, 0)
        flag = False
    else:
        return None, n
    mesh = {
        "has_mesh": True,
        "has_mesh_byte": flag,
        "vertex_buffer": {"flags": w[0], "count": w[1], "format": w[2]},
        "index_buffer": {"flags": w[3], "bytes": w[4], "x": w[5], "primitive_type": w[5]},
    }
    if not flag:
        mesh["layout_note"] = (
            "standalone Part 1 layout: no has_mesh byte (the Xbox 360 Part 1 reader "
            "0x828dae50 goes from the property bag straight to the two descriptors)"
        )
    return mesh, 0


def detail_tail_build(mesh, order="<"):
    if not mesh["has_mesh"]:
        return b"\0" if mesh.get("has_mesh_byte", True) else b""
    v, i = mesh["vertex_buffer"], mesh["index_buffer"]
    body = struct.pack(
        order + "6I",
        v["flags"],
        v["count"],
        v["format"],
        i["flags"],
        i["bytes"],
        _named(i, "primitive_type", "x"),
    )
    return (b"\1" if mesh.get("has_mesh_byte", True) else b"") + body


def detail_stream_layout(mesh, stream, order="<"):
    """`.detailmesh.stream` (reader 0x5322c6): three u32 lists, the vertex buffer, the
    index buffer.  The lists hold one entry per source mesh: start of its first index
    copy, start of the second (first + index count), index count / 3 (builder 0x5369e7;
    file order from the writer 0x5321e5).  -> {lists: [n, n, n], list_names,
    vertex_offset, vertex_stride,
    vertex_stride_source, format_stride, stride_matches_format, index_offset,
    decoded_bytes, leftover_bytes} or {not_decoded}.  The stride is DERIVED from the
    stream size (DETAIL_INFERRED), so `leftover_bytes` alone proves little: compare
    `stride_matches_format`."""
    p = 0
    lists = []
    try:
        for _ in range(3):
            (k,) = struct.unpack_from(order + "I", stream, p)
            if k > len(stream):
                raise struct.error
            p += 4 + 4 * k
            lists.append(k)
    except struct.error:
        return {"not_decoded": "list header at %d" % p, "leftover_bytes": len(stream)}
    out = {"lists": lists}
    out["list_names"] = list(DETAIL_LIST_NAMES)
    if mesh and mesh.get("has_mesh"):
        vb, ib = mesh["vertex_buffer"], mesh["index_buffer"]
        rest = len(stream) - p - ib["bytes"]
        stride = rest // vb["count"] if vb["count"] else 0
        out["vertex_offset"] = p
        out["vertex_stride"] = stride
        out["vertex_stride_source"] = "stream size"
        want = DETAIL_FORMAT_STRIDE.get(vb["format"])
        out["format_stride"] = want
        out["stride_matches_format"] = (stride == want) if want is not None else None
        p += stride * vb["count"]
        out["index_offset"] = p
        p += ib["bytes"]
    out["decoded_bytes"] = p
    out["leftover_bytes"] = len(stream) - p
    return out


if __name__ == "__main__":
    import json

    path = sys.argv[1]
    blob = _read_bytes(path)
    st = _read_bytes(path + ".stream") if os.path.exists(path + ".stream") else None
    low = path.lower()
    if low.endswith(".terraincoloringasset"):
        d = coloring_to_json(blob)
        if len(sys.argv) > 2:
            print(coloring_write(d, st, sys.argv[2]))
    else:
        d = to_json(blob, stream=st)
        if len(sys.argv) > 2:
            print(write_outputs(d, sys.argv[2]))
        strip(d)
        d["sectors"] = "%d sectors" % len(d.get("sectors", []))
        if "stream" in d and "cells" in d["stream"]:
            d["stream"]["cells"] = "%d cells" % len(d["stream"]["cells"])
    print(json.dumps(d, indent=1)[:6000])
