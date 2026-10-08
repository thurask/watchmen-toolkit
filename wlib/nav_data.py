"""Navigation data of a level: the Kynapse path data (`.hpd`) and the Kynapse
world definition (`.aipathdata`).

The game links the Kynapse AI middleware (namespace `Kaim`) statically.  Per level
it loads two files:

* `<Level>.aipathdata` (a block-archive asset): a "KS BIG FILE" tree of strings,
  the world definition (services, agents, path finder settings, the path of the
  path-data file).  Reader: KynapseSkel::CBigFileDataReader 0x48b3c0 / 0x489e00.
* `<level>.hpd` (a plain NAZ entry, written by `extract` to OUT/files/...): the
  path data of the database "Characters" -- a table of streaming cells, each with
  a graph (vertices, directed edges) and an "AI mesh" (walkable floors as outlines
  on a 2D grid).  Readers: CHierarchicalGraphManager 0x90b310 / 0x90b660 /
  0x90b930 / 0x90d9c0 (header, cell table, path-object table, cell data),
  CConcreteSlot 0x9172c0 (graph of a cell), CAiMesh 0x918940 (mesh).

Everything is little-endian on every platform (the PC, Xbox 360 and PS3 files are
byte-identical; the definition carries `EndiannessSwap = True` and the engine swaps
on big-endian machines, 0x90b190 / 0x90b240 / 0x9172c0).

Coordinates: the files are in Kynapse space, which is the engine's space with x
negated (bridge 0x48110f negates x at every crossing).  y is up, units are metres.
`parse_hpd` returns file values unchanged; `build_document` is in ENGINE space (x
negated).  `build_glb` is in the frame of the toolkit's model exports (frame.py):
true-handed by default, which is the file's own x again; engine space with
`--frame mirrored`.

Evidence per field is in docs (NAV_DATA.md) and in the `evidence` table of the
exported document: "code" = read from the loader, "data" = verified on all shipped
files, "inferred", "unknown".
"""

import json
import math
import os
import struct
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.append(_HERE)  # append, never insert(0)
import frame as _frame  # noqa: E402

FORMAT = "watchmen-nav/1"

HEADER_SIZE = 0x84  # 0x90b310: cell table is read from file offset 0x84
MESH_TAG = b"Kynogon Mesh"
KS_TAG = b"KS BIG FILE"
NO_LINK = 0x80000000  # vertex +0x10: no abstract vertex (0x909ea0)
NO_MESH = 0xFFFFFFFF  # mesh-link target sector: none


class NavError(ValueError):
    """The data is not a path-data / world-definition file this module understands."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _f(x):
    """float32 value -> the shortest decimal that round-trips it (for JSON)."""
    return float(str(np.float32(x)))


def _v(p):
    return [_f(p[0]), _f(p[1]), _f(p[2])]


def to_engine(p):
    """Kynapse position / direction -> engine space (x negated, 0x48110f)."""
    return (-p[0], p[1], p[2])


def _ev(p):
    return [_f(-p[0]) + 0.0, _f(p[1]), _f(p[2])]


class _Reader(object):
    def __init__(self, data, pos, end):
        self.d = data
        self.o = pos
        self.end = end

    def _need(self, n):
        if self.o + n > self.end:
            raise NavError("truncated at 0x%x (need %d bytes, limit 0x%x)" % (self.o, n, self.end))

    def u32(self):
        self._need(4)
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def f32(self):
        self._need(4)
        v = struct.unpack_from("<f", self.d, self.o)[0]
        self.o += 4
        return v

    def vec(self):
        self._need(12)
        v = struct.unpack_from("<3f", self.d, self.o)
        self.o += 12
        return v

    def count(self, unit):
        """A u32 element count; refuses counts the remaining bytes cannot hold."""
        n = self.u32()
        if n * unit > self.end - self.o:
            raise NavError("count %d at 0x%x exceeds the data" % (n, self.o - 4))
        return n


# ---------------------------------------------------------------------------
# .aipathdata -- "KS BIG FILE"
# ---------------------------------------------------------------------------


def parse_aipathdata(data):
    """`.aipathdata` asset -> {"version", "root", "size_field", "bytes", "trailing"}.

    Layout (reader 0x48b3c0, 0x489e00, 0x488dab, 0x488e6e):
      u32 payload size (the asset's own length field; big-endian in console builds)
      char[11] "KS BIG FILE", u32 version (must be 1), then one node.
      node := u32 kind;
        kind 0 (group):     string label, string name, u32 child count, children
        kind 1 (raw data):  u32 size, bytes (named "RawData" by the reader)
        kind 2 (attribute): string name, string value
      string := u32 length, characters (no terminator).
    A node is returned as {"name", "label", "children"}, {"attr", "value"} or
    {"raw": hex}.  Attribute order and duplicates are kept (they matter: a brain
    lists `Agent = GotoAgent` twice).
    """
    if len(data) < 23 or data[4:15] != KS_TAG:
        raise NavError("not a KS BIG FILE (.aipathdata) asset")
    le = struct.unpack_from("<I", data, 0)[0]
    be = struct.unpack_from(">I", data, 0)[0]
    version = struct.unpack_from("<I", data, 15)[0]
    if version != 1:
        raise NavError("KS BIG FILE version %d (the engine accepts 1 only)" % version)
    r = _Reader(data, 19, len(data))

    def string():
        n = r.count(1)
        s = data[r.o : r.o + n].decode("latin-1")
        r.o += n
        return s

    def node(depth):
        if depth > 64:
            raise NavError("KS BIG FILE nesting too deep")
        kind = r.u32()
        if kind == 0:
            label = string()
            name = string()
            n = r.count(4)
            return {"name": name, "label": label, "children": [node(depth + 1) for _ in range(n)]}
        if kind == 1:
            n = r.count(1)
            raw = data[r.o : r.o + n]
            r.o += n
            return {"raw": raw.hex()}
        if kind == 2:
            name = string()
            return {"attr": name, "value": string()}
        raise NavError("KS BIG FILE node kind %d at 0x%x" % (kind, r.o - 4))

    root = node(0)
    expect = len(data) - 4
    return {
        "version": version,
        "root": root,
        "size_field": le if le == expect else be,
        "size_field_endian": "little" if le == expect else ("big" if be == expect else "?"),
        "bytes": len(data),
        "trailing": len(data) - r.o,
    }


def tree_find(node, name, label=None):
    """First child group of `node` called `name` (and labelled `label`), or None."""
    for c in node.get("children", ()):
        if c.get("name") == name and (label is None or c.get("label") == label):
            return c
    return None


def tree_attrs(node):
    """The attributes of a group as a list of (name, value) in file order."""
    return [(c["attr"], c["value"]) for c in node.get("children", ()) if "attr" in c]


def tree_attr(node, name, default=None):
    for k, v in tree_attrs(node):
        if k == name:
            return v
    return default


def _num(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        try:
            return float(s)
        except (TypeError, ValueError):
            return s


def config_summary(tree):
    """The parts of a world definition that say how the path data is used.

    Values are the file's strings converted to numbers where they are numbers;
    nothing is defaulted.  Key names are the file's own.
    """
    root = tree["root"]
    out = {
        "level": dict((k, _num(v)) for k, v in tree_attrs(root)),
        "global_services": [],
        "time_management": [],
        "entities": [],
        "brains": [],
        "agents": [],
        "path_finders": [],
        "path_object_pools": [],
        "databases": [],
        "traversals": [],
    }
    g = tree_find(root, "GlobalServices")
    if g:
        out["global_services"] = [v for k, v in tree_attrs(g) if k == "Service"]
    g = tree_find(root, "TimeMgt")
    if g:
        for c in g["children"]:
            if "children" in c:
                e = {"task": c["label"], "kind": c["name"]}
                e.update((k, _num(v)) for k, v in tree_attrs(c))
                out["time_management"].append(e)
    for key, group in (("entities", "Entities"), ("agents", "Agents")):
        g = tree_find(root, group)
        for c in g["children"] if g else ():
            if "children" in c:
                e = {"name": c["label"]}
                e.update((k, _num(v)) for k, v in tree_attrs(c))
                out[key].append(e)
    g = tree_find(root, "Brains")
    for c in g["children"] if g else ():
        if "children" in c:
            a = tree_attrs(c)
            out["brains"].append(
                {
                    "name": c["label"],
                    "class": tree_attr(c, "Class"),
                    "services": [v for k, v in a if k == "Service"],
                    "agents": [v for k, v in a if k == "Agent"],
                }
            )
    g = tree_find(root, "Services")
    for c in g["children"] if g else ():
        if "children" not in c:
            continue
        cls = tree_attr(c, "Class")
        if cls == "CHierarchicalPathFinder":
            e = {"name": c["label"]}
            e.update((k, _num(v)) for k, v in tree_attrs(c))
            mods = {}
            for m in c["children"]:
                if "children" in m and m["name"].startswith("Modifiers_"):
                    items = []
                    for it in m["children"]:
                        if "children" in it:
                            d = {"name": it["label"]}
                            d.update((k, _num(v)) for k, v in tree_attrs(it))
                            items.append(d)
                    mods[m["name"][len("Modifiers_") :]] = {
                        "default": tree_attr(m, "default"),
                        "items": items,
                    }
            e["modifiers"] = mods
            out["path_finders"].append(e)
        elif cls == "CHierarchicalPathObjectManager":
            for p in c["children"]:
                if p.get("name") == "PathObjectsPool":
                    out["path_object_pools"].append(dict((k, _num(v)) for k, v in tree_attrs(p)))
        elif cls == "CHierarchicalGraphManager":
            dbs = tree_find(c, "Databases")
            for d in dbs["children"] if dbs else ():
                if "children" in d:
                    e = {"name": d["label"]}
                    e.update((k, _num(v)) for k, v in tree_attrs(d))
                    out["databases"].append(e)
            for t in c["children"]:
                if t.get("name") == "Traversal":
                    e = {"name": t["label"]}
                    e.update((k, _num(v)) for k, v in tree_attrs(t))
                    out["traversals"].append(e)
    return out


def database_path(tree):
    """The `.hpd` path the definition names (first database with a Path), or None."""
    for d in config_summary(tree)["databases"]:
        if isinstance(d.get("Path"), str):
            return d["Path"]
    return None


# ---------------------------------------------------------------------------
# .hpd
# ---------------------------------------------------------------------------


def _parse_mesh(data, pos, end):
    """One AI mesh blob (CAiMesh loader 0x918940).  Returns (mesh, end offset)."""
    r = _Reader(data, pos, end)
    r._need(16)
    if data[pos : pos + 12] != MESH_TAG:
        raise NavError("no 'Kynogon Mesh' tag at 0x%x" % pos)
    r.o += 12
    ver = r.u32()
    if not 1 <= ver <= 5:
        raise NavError("AI mesh version %d at 0x%x (the engine accepts 1..5)" % (ver, pos + 12))
    m = {"offset": pos, "version": ver}
    m["sector_word"] = r.u32() if ver >= 5 else 0  # mesh+0x04
    m["cell_size"] = r.f32()  # +0x08
    m["x_min"] = r.f32()  # +0x10
    m["x_max"] = r.f32()  # +0x14
    m["z_min"] = r.f32()  # +0x18
    m["z_max"] = r.f32()  # +0x1c
    nx = m["nx"] = r.u32()  # +0x20
    nz = m["nz"] = r.u32()  # +0x24
    m["margin"] = r.f32() if ver >= 4 else 0.0  # +0x0c
    m["unk_30"] = r.f32() if ver >= 2 else 0.0  # +0x30
    m["radius"] = r.f32() if ver >= 3 else 0.0  # +0x34
    if nx * nz * 4 > end - r.o:
        raise NavError("AI mesh grid %dx%d at 0x%x exceeds the data" % (nx, nz, pos))
    floors = []
    for i in range(nx):
        for j in range(nz):
            for k in range(r.count(24)):
                fl = {"cell": (i, j), "index": k, "offset": r.o}
                fl["alt_min"] = r.f32()  # floor+0x14
                fl["alt_max"] = r.f32()  # floor+0x10
                fl["level_links"] = [(r.vec(), r.vec()) for _ in range(r.count(24))]  # +0x18
                fl["links"] = [(r.vec(), r.vec()) for _ in range(r.count(24))]  # +0x24
                ml = []
                if ver >= 5:  # +0x30: 2 points, then a 0x1c target record
                    for _ in range(r.count(52)):
                        a, b = r.vec(), r.vec()
                        t = (r.u32(), r.u32(), r.u32(), r.u32())
                        ml.append((a, b, t, r.vec()))
                fl["mesh_links"] = ml
                fl["inner_walls"] = [  # +0x3c
                    [r.vec() for _ in range(r.count(12))] for _ in range(r.count(4))
                ]
                fl["outline"] = [  # +0x48
                    [r.vec() for _ in range(r.count(12))] for _ in range(r.count(4))
                ]
                dz = []
                for _ in range(r.count(16)):  # +0x54: count, direction, points
                    n = r.count(12)
                    d = r.vec()
                    dz.append((d, [r.vec() for _ in range(n)]))
                fl["directional"] = dz
                if ver == 1:
                    r.u32()  # read and dropped by the loader
                floors.append(fl)
    for fl in floors:  # second pass of the loader: link targets (cell i, cell j, floor)
        fl["level_link_targets"] = [(r.u32(), r.u32(), r.u32()) for _ in fl["level_links"]]
        fl["link_targets"] = [(r.u32(), r.u32(), r.u32()) for _ in fl["links"]]
    m["floors"] = floors
    return m, r.o


def parse_hpd(data):
    """`.hpd` path data -> dict in FILE (Kynapse) space.

    Layout (all little-endian; offsets in the file):
      0x00 f32 version (1.3 in every shipped file; the loader also takes 1.0, whose
           cell entries are 0x28 bytes, and treats < 1.3 as "no path-object table")
      0x04 u32 cell count
      0x08 u32 cell addressing: 1 = each cell entry carries a float box, 0 = cells
           sit on a lattice (integer coordinates, origin 0x0c..0x14, size 0x18)
      0x1c 4 x {u32 kind, u32, u32 bytes}: vertex extension descriptors
      0x4c 4 x {u32, u32, u32}: second descriptor block
      0x7c u32 vertex record size, 0x80 u32 edge record size
      0x84 cell table, 0x30 bytes each: u32 id, f32 x_min, x_max, y_min, y_max,
           z_min, z_max, u32 hierarchy level, u32 size, u32 offset (from the end of
           the tables), u32 date (decimal YYMMDD), u32 time (decimal HHMMSScc)
      then (version >= 1.3) f32 1.0, u32 count, count x {u32 id, u16 flags, u16 pool
           type}: the static path objects
      then the cells: u32 vertex count, u32 edge count, vertices, edges, AI mesh,
           u32 mesh size, u32 0.
    """
    n = len(data)
    if n < HEADER_SIZE:
        raise NavError("file too short for a path-data header (%d bytes)" % n)
    words = struct.unpack_from("<33I", data, 0)
    version = struct.unpack_from("<f", data, 0)[0]
    if not 0.99 < version < 2.0:
        raise NavError("not a path-data file (version field %r)" % version)
    ncell = words[1]
    one = abs(version - 1.0) < 1e-6
    entry = 0x28 if one else 0x30  # 0x90b310
    has_po = version >= struct.unpack("<f", struct.pack("<f", 1.3))[0]  # 0x9e60c0
    if HEADER_SIZE + ncell * entry > n:
        raise NavError("cell table (%d cells) exceeds the file" % ncell)
    vstride, estride = words[31], words[32]
    if vstride < 28 or estride < 12 or vstride > 4096 or estride > 4096:
        raise NavError("record sizes %d / %d are not plausible" % (vstride, estride))
    hdr = {
        "version": version,
        "cell_count": ncell,
        "cell_mode": words[2],
        "lattice_origin": struct.unpack_from("<3f", data, 0x0C),
        "lattice_cell_size": struct.unpack_from("<f", data, 0x18)[0],
        "vertex_attributes": [words[7 + 3 * i : 10 + 3 * i] for i in range(4)],
        "edge_attributes": [words[19 + 3 * i : 22 + 3 * i] for i in range(4)],
        "vertex_stride": vstride,
        "edge_stride": estride,
    }
    regions = [("header", 0, HEADER_SIZE), ("cell table", HEADER_SIZE, ncell * entry)]
    undecoded = []
    cells = []
    for i in range(ncell):
        o = HEADER_SIZE + i * entry
        c = {"id": struct.unpack_from("<I", data, o)[0], "table_offset": o}
        if words[2] == 1:
            b = struct.unpack_from("<6f", data, o + 4)
            c["box"] = (b[0], b[1], b[2], b[3], b[4], b[5])
        else:
            c["lattice"] = struct.unpack_from("<3i", data, o + 4)
            c["raw_10"] = struct.unpack_from("<3I", data, o + 0x10)
        c["level"], c["size"], c["offset"] = struct.unpack_from("<3I", data, o + 0x1C)
        if not one:
            c["date"], c["time"] = struct.unpack_from("<2I", data, o + 0x28)
        cells.append(c)
    o = HEADER_SIZE + ncell * entry
    po = []
    po_version = None
    if has_po:
        if o + 8 > n:
            raise NavError("path-object table header exceeds the file")
        po_version, npo = struct.unpack_from("<fI", data, o)
        if o + 8 + npo * 8 > n:
            raise NavError("path-object table (%d entries) exceeds the file" % npo)
        for i in range(npo):
            pid, flags, typ = struct.unpack_from("<IHH", data, o + 8 + 8 * i)
            po.append({"index": i + 1, "id": pid, "flags": flags, "pool_type": typ})
        regions.append(("path-object table", o, 8 + 8 * npo))
        o += 8 + 8 * npo
    base = o
    covered = []
    for c in cells:
        start = base + c["offset"]
        end = start + c["size"]
        c["file_offset"] = start
        if end > n or c["size"] < 16:
            raise NavError(
                "cell %d (offset 0x%x, size %d) exceeds the file" % (c["id"], start, c["size"])
            )
        covered.append((start, end))
        if c["level"] != 0:
            # an abstract (hierarchy) cell: CAbstractSlot 0x9173e0, 0x20-byte vertices
            # and 0x10-byte edges.  No shipped file has one; kept as an undecoded region.
            c["vertices"], c["edges"], c["mesh"] = [], [], None
            undecoded.append(
                {"what": "abstract cell %d" % c["id"], "offset": start, "size": c["size"]}
            )
            continue
        nv, ne = struct.unpack_from("<II", data, start)
        g_end = start + 8 + nv * vstride + ne * estride
        if g_end + 8 > end:
            raise NavError(
                "cell %d: graph (%d vertices, %d edges) exceeds the cell" % (c["id"], nv, ne)
            )
        verts = []
        for i in range(nv):
            p = start + 8 + i * vstride
            vid, x, y, z, link, f14, first = struct.unpack_from("<IfffIfI", data, p)
            verts.append(
                {
                    "id": vid & 0x7FFFFFFF,
                    "border": bool(vid >> 31),
                    "pos": (x, y, z),
                    "abstract": None if link == NO_LINK else link,
                    "raw_14": f14,
                    "first_edge": first - 1 if first else None,
                    "ext": bytes(data[p + 28 : p + vstride]),
                }
            )
        edges = []
        eo = start + 8 + nv * vstride
        for i in range(ne):
            w, a, b = struct.unpack_from("<III", data, eo + i * estride)
            if a >= nv or b >= nv:
                raise NavError("cell %d edge %d: vertex index out of range" % (c["id"], i))
            edges.append(
                {
                    "from": a,
                    "to": b,
                    "length_q": w & 0xFFFF,
                    "path_object": (w >> 16) & 0x7FFF,
                    "unbound": bool(w >> 31),
                    "ext": bytes(data[eo + i * estride + 12 : eo + (i + 1) * estride]),
                }
            )
        c["vertices"], c["edges"] = verts, edges
        c["max_edge_length"] = verts[0]["raw_14"] if verts else None
        # sort orders: the 6-byte kind-2 vertex extension holds, in record k, the index
        # of the k-th vertex by ascending x, y and z.
        order = None
        kinds = [a for a in hdr["vertex_attributes"] if a[0] == 2 and a[2] == 6]
        if kinds and vstride >= 28 + kinds[0][1] + 6:
            off = kinds[0][1]
            order = [struct.unpack_from("<3H", v["ext"], off) for v in verts]
            order = [[t[a] for t in order] for a in range(3)]
        c["sorted"] = order
        # the mesh is found from the END of the cell (0x90c980): size at end-8
        msize, tail = struct.unpack_from("<II", data, end - 8)
        c["mesh_size"], c["tail_word"] = msize, tail
        c["mesh"] = None
        if msize == 0 or msize == 0x80000000:
            if g_end != end - 8:
                undecoded.append(
                    {
                        "what": "cell %d after the graph" % c["id"],
                        "offset": g_end,
                        "size": end - 8 - g_end,
                    }
                )
            continue
        m_start = end - 8 - msize
        if m_start < g_end:
            raise NavError("cell %d: AI mesh (%d bytes) overlaps the graph" % (c["id"], msize))
        if m_start != g_end:
            undecoded.append(
                {
                    "what": "cell %d between graph and mesh" % c["id"],
                    "offset": g_end,
                    "size": m_start - g_end,
                }
            )
        mesh, m_end = _parse_mesh(data, m_start, end - 8)
        if m_end != end - 8:
            undecoded.append(
                {
                    "what": "cell %d after the AI mesh" % c["id"],
                    "offset": m_end,
                    "size": end - 8 - m_end,
                }
            )
        c["mesh"] = mesh
    # anything between / after the cells
    covered.sort()
    p = base
    for s, e in covered:
        if s > p:
            undecoded.append({"what": "between cells", "offset": p, "size": s - p})
        p = max(p, e)
    if p < n:
        undecoded.append({"what": "after the last cell", "offset": p, "size": n - p})
    if covered:
        regions.append(("cells", base, p - base))
    return {
        "bytes": n,
        "header": hdr,
        "cells": cells,
        "path_objects": po,
        "path_object_table_version": po_version,
        "data_offset": base,
        "regions": regions,
        "undecoded": undecoded,
    }


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def floor_segments(fl):
    """The segments that bound a floor, as the engine's inside test uses them
    (0x91b470: outline polylines, cell links and mesh links; not the inner walls).
    -> list of (a, b, kind) with kind "wall" | "link" | "mesh_link"."""
    out = []
    for pl in fl["outline"]:
        for a, b in zip(pl, pl[1:]):
            out.append((a, b, "wall"))
    for a, b in fl["links"]:
        out.append((a, b, "link"))
    for s in fl["mesh_links"]:
        out.append((s[0], s[1], "mesh_link"))
    return out


def triangulate(segments):
    """Even-odd region bounded by 3D segments (y up) -> (points, triangles, open).

    The file stores a floor as an unordered set of boundary segments; the engine
    decides "inside" by crossing parity (0x91b470).  This cuts the same region
    into trapezoids between consecutive z values of the segment ends, two
    triangles each, so holes and touching loops need no special case.  Heights are
    interpolated along the boundary segments (the file has no height inside a
    floor).  `open` counts slabs with an odd number of crossings (an outline that
    does not close); the unpaired crossing is dropped.
    Triangles are wound so their normal points up (+y) in the space given.
    """
    segs = []
    for a, b in segments:
        if a[2] == b[2]:
            continue  # parallel to the sweep: bounds no slab
        segs.append((a, b) if a[2] < b[2] else (b, a))
    zs = sorted(set([s[0][2] for s in segs] + [s[1][2] for s in segs]))
    pts, index, tris = [], {}, []
    open_slabs = 0

    def vid(p):
        k = (round(p[0], 5), round(p[1], 5), round(p[2], 5))
        i = index.get(k)
        if i is None:
            i = index[k] = len(pts)
            pts.append(p)
        return i

    def at(s, z):
        a, b = s
        if z == a[2]:
            return a
        if z == b[2]:
            return b
        t = (z - a[2]) / (b[2] - a[2])
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, z)

    for z0, z1 in zip(zs, zs[1:]):
        zm = 0.5 * (z0 + z1)
        act = [s for s in segs if s[0][2] <= z0 and s[1][2] >= z1]
        act.sort(key=lambda s: at(s, zm)[0])
        if len(act) % 2:
            open_slabs += 1
        for k in range(0, len(act) - 1, 2):
            l0, l1 = at(act[k], z0), at(act[k], z1)
            r0, r1 = at(act[k + 1], z0), at(act[k + 1], z1)
            q = [vid(l0), vid(l1), vid(r1), vid(r0)]  # normal +y for x left -> right
            for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3])):
                if t[0] != t[1] and t[1] != t[2] and t[0] != t[2]:
                    tris.append(t)
    return pts, tris, open_slabs


def _tri_area(pts, t):
    a, b, c = pts[t[0]], pts[t[1]], pts[t[2]]
    return 0.5 * abs((b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2]))


def point_in_floor(fl, p):
    """The engine's inside test (0x91b470 / 0x91c300) for a FILE-space point:
    altitude within the floor's range and odd crossing parity of its boundary."""
    if not fl["alt_min"] <= p[1] <= fl["alt_max"]:
        return False
    inside = False
    x, z = p[0], p[2]
    for a, b, _k in floor_segments(fl):
        if (a[2] > z) != (b[2] > z):
            if x < a[0] + (z - a[2]) * (b[0] - a[0]) / (b[2] - a[2]):
                inside = not inside
    return inside


def _seg_dist2(px, pz, a, b):
    ax, az, bx, bz = a[0], a[2], b[0], b[2]
    dx, dz = bx - ax, bz - az
    L = dx * dx + dz * dz
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / L))
    ex, ez = ax + dx * t - px, az + dz * t - pz
    return ex * ex + ez * ez


def locate(hpd, p, up=3.0, down=3.0):
    """Where a FILE-space point lies on the AI mesh.

    -> {"on_mesh", "distance", "cell", "floor", "alt_min", "alt_max"}: `distance`
    is 0 on a floor whose altitude range, widened by `down` below and `up` above
    (placement pivots are not exactly at foot height), holds the point; otherwise
    the horizontal distance to the nearest boundary segment of such a floor (None
    when no floor is in altitude range)."""
    best = None
    for c in hpd["cells"]:
        m = c.get("mesh")
        if not m:
            continue
        for fl in m["floors"]:
            if not fl["alt_min"] - down <= p[1] <= fl["alt_max"] + up:
                continue
            q = (p[0], 0.5 * (fl["alt_min"] + fl["alt_max"]), p[2])
            if point_in_floor(fl, q):
                return {
                    "on_mesh": True,
                    "distance": 0.0,
                    "cell": c["id"],
                    "floor": [fl["cell"][0], fl["cell"][1], fl["index"]],
                    "alt_min": fl["alt_min"],
                    "alt_max": fl["alt_max"],
                }
            for a, b, _k in floor_segments(fl):
                d2 = _seg_dist2(p[0], p[2], a, b)
                if best is None or d2 < best[0]:
                    best = (d2, c, fl)
    if best is None:
        return {"on_mesh": False, "distance": None, "cell": None, "floor": None}
    fl = best[2]
    return {
        "on_mesh": False,
        "distance": math.sqrt(best[0]),
        "cell": best[1]["id"],
        "floor": [fl["cell"][0], fl["cell"][1], fl["index"]],
        "alt_min": fl["alt_min"],
        "alt_max": fl["alt_max"],
    }


def graph_summary(hpd):
    """Counts and connectivity of the whole graph.  Border vertices with the same
    id in different cells are one node (0x909ea0 joins them when a cell loads)."""
    parent = {}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    nv = ne = npo = 0
    lens = []
    worst = 0.0
    for c in hpd["cells"]:
        vs = c["vertices"]
        nv += len(vs)
        for v in vs:
            parent.setdefault(v["id"], v["id"])
        for e in c["edges"]:
            ne += 1
            npo += 1 if e["path_object"] else 0
            a, b = vs[e["from"]], vs[e["to"]]
            ra, rb = find(a["id"]), find(b["id"])
            if ra != rb:
                parent[ra] = rb
            d = math.sqrt(sum((a["pos"][k] - b["pos"][k]) ** 2 for k in range(3)))
            lens.append(d)
            worst = max(worst, abs(d - (e["length_q"] + 0.5) / 16.0))
    sizes = {}
    for k in parent:
        r = find(k)
        sizes[r] = sizes.get(r, 0) + 1
    comp = sorted(sizes.values(), reverse=True)
    pairs = set()
    one_way = 0
    for c in hpd["cells"]:
        vs = c["vertices"]
        for e in c["edges"]:
            pairs.add((vs[e["from"]]["id"], vs[e["to"]]["id"]))
    for a, b in pairs:
        if (b, a) not in pairs:
            one_way += 1
    return {
        "vertex_records": nv,
        "nodes": len(parent),
        "edges": ne,
        "path_object_edges": npo,
        "one_way_edges": one_way,
        "components": len(comp),
        "component_sizes": comp[:8],
        "edge_length_min": _f(min(lens)) if lens else None,
        "edge_length_max": _f(max(lens)) if lens else None,
        "edge_length_mean": round(sum(lens) / len(lens), 4) if lens else None,
        "stored_length_max_error": round(worst, 5),
    }


# ---------------------------------------------------------------------------
# export document (engine space)
# ---------------------------------------------------------------------------

SPACE = {
    "space": "engine",
    "note": (
        "Every position and direction is in the game's ENGINE space: metres, y up, "
        "the same numbers as node positions in the level fragments and as the "
        "toolkit's model exports (which write engine coordinates unchanged).  The "
        "files store Kynapse space, which is engine space with x negated (bridge "
        "0x48110f); the negation is already applied here.  Mesh cell indices and "
        "the per-axis sort orders are the file's: they follow ascending Kynapse x, "
        "that is descending engine x."
    ),
    "x_negated_from_file": True,
}

#: the `note` of a .nav.json written with the true frame in force: the same facts
#: without the sentence that the model exports hold engine coordinates
NOTE_TRUE = (
    "Every position and direction is in the game's ENGINE space (left-handed): "
    "metres, y up, the same numbers as node positions in the level fragments and "
    "as `world.pos` of the level export.  The files store Kynapse space, which is "
    "engine space with x negated (bridge 0x48110f); the negation is already applied "
    "here.  Mesh cell indices and the per-axis sort orders are the file's: they "
    "follow ascending Kynapse x, that is descending engine x."
)
#: added to the conventions of a .nav.json whose .nav.glb is in the true frame
GLB_FRAME_NOTE = (
    "the .nav.glb written with this file is in the frame of the toolkit's GLBs, "
    "coordinate_frame 'right-handed-true': x = -engine x, which is the file's own "
    "(Kynapse) x.  This JSON stays in engine space: negate x to overlay it on those GLBs"
)
#: asset-level note of a .nav.glb in the true frame
GLB_SPACE_TRUE = (
    "Positions are in the frame of the toolkit's model exports (coordinate_frame "
    "'right-handed-true'): metres, y up, x = -engine x.  That is the x the navigation "
    "files store (Kynapse space is engine space with x negated, bridge 0x48110f)."
)

EVIDENCE = {
    "header.version / cell_count / cell_mode / strides": "code 0x90b310, 0x90d9c0, 0x916040",
    "header.vertex_attributes": "inferred: kind 2 = the 6-byte sort-order extension "
    "(0x90c980 searches for kind 2); verified on data",
    "cell.box / level / size / offset": "code 0x916040, 0x90a3a0, 0x90d9c0",
    "cell.date / time": "data: decimal YYMMDD and HHMMSScc -- every cell of the 11 distinct "
    "shipped files (120 cells) decodes to a valid date and time, cc is 00 everywhere and all "
    "cells of a file carry one stamp (summary.generated).  code: the two words were added "
    "after version 1.0; the loader writes 0xbaffe000 into both for a 1.0 file (0x90b310, "
    "0x90b660).  No reader was found in the game: the meaning 'when the path data was "
    "generated' is inferred from the data",
    "vertex.id / border": "code 0x909ea0 (bit 31 marks a vertex shared with other cells)",
    "vertex.first_edge": "data: index + 1 of the first edge leaving the vertex, 0 = none",
    "vertex.abstract": "code 0x909ea0 (0x80000000 = none; no shipped file has one)",
    "cell.max_edge_length": "data: stored in the first vertex record at +0x14 "
    "(moved to the slot by 0x9172c0)",
    "cell.sorted": "data: vertex indices by ascending file x, y, z",
    "edge.from / to": "code 0x92dfa0",
    "edge.length": "data: low 16 bits = floor(16 x Euclidean length)",
    "edge.path_object": "code 0x909dc0, 0x92dfa0 (bits 16..30, 1-based table index)",
    "edge.unbound": "code 0x92dfa0 (bit 31, cleared when the path object is bound; "
    "set on every edge in the files)",
    "path_object.id": "code 0x4837d5 (X360 0x829f8260): 1-based index into the serialised "
    "list property aiStaticPathObjectNodes of the level's AIWorldNode (registered in 0x484ffb, "
    "setter 0x483844), written when the path data was generated; `watchmen levelmeta` joins "
    "the table to the level's nodes with it",
    "path_object.pool_type": "code 0x92dfa0 (compared with the pool Type of the definition)",
    "path_object.flags": "code 0x92d380, 0x92dfa0, 0x48a559: bit 0 = entry created at run "
    "time (dynamic path objects), bits 1-2 equal to 2 (value 4) = per-entity pass bits, "
    "bit 3 = starts passable; 8 in every shipped entry (flags_decoded)",
    "mesh header": "code 0x918940, 0x91b0d0 (cell size, bounds, grid, margin), "
    "0x91c1d0 (radius)",
    "mesh.sector": "measured on data; equality use read in code: signed bytes 1 and 3 of "
    "the word are the z and x index of the mesh in the level-wide lattice; mesh links name "
    "their target by this word, which the runtime only compares for equality (0x91060d, "
    "0x9106a0)",
    "mesh.unk_30": "code: a generation value the runtime does not read (loader 0x918b13; no "
    "reader in the mesh code 0x917000-0x91d800); -0.707106 in every file",
    "floor.alt_min / alt_max": "code 0x91c300",
    "floor.outline / links / mesh_links": "code 0x91b470 (the region is where their "
    "crossing parity is odd)",
    "floor.links[].to": "code 0x918940 second pass (cell i, cell j, floor index)",
    "floor.mesh_links[].to": "data: target sector word, cell i, cell j, floor index "
    "(every target exists)",
    "floor.mesh_links[].gate": "code 0x9104d8-0x910506: the three trailing floats (f0, f1, "
    "f2) are a gate -- a trace crosses the link only when dir.x * f0 + dir.z * f2 > f1, dir "
    "= the normalised move direction; exported as dir_x = -f0 (engine space), min_dot = "
    "f1, dir_z = f2.  `crossable` is false for a zero direction with min_dot >= 1, which "
    "never passes",
    "config_runtime_overrides": "code: AIBrainNode values the bridge writes over the "
    "definition's (0x4898f6, 0x489c1b: first path finder only; 0x934630, 0x934650: the "
    "follow agent)",
    "floor.inner_walls": "code 0x91b970 (blocking polylines inside the floor)",
    "floor.directional": "code 0x91b5f0 (polygon that blocks moves whose direction has a "
    "non-negative component along `dir`)",
    "floor.level_links": "code 0x918940; never present in a shipped file",
    "triangles (GLB)": "derived: trapezoid cut of the outline, heights interpolated",
}


#: values of the definition (.aipathdata) the engine writes over at run time
CONFIG_RUNTIME_OVERRIDES = [
    {
        "definition_path": "Services/CharacterPathfinder/FlatDataModeSearchRadius",
        "overridden_by": "AIBrainNode.pathSearchRadius",
        "when": "every entity update, first path finder only",
        "code": "0x4898f6",
    },
    {
        "definition_path": "Services/CharacterPathfinder/Modifiers_IDetectPathNodeReached/"
        "subgoaldistance2d5/MaxDist",
        "overridden_by": "AIBrainNode.subGoalMinDist",
        "when": "every entity update, first path finder only",
        "code": "0x489c1b",
    },
    {
        "definition_path": "Agents/FollowAgent/DistFromEntity",
        "overridden_by": "AIBrainNode.followDist",
        "when": "every think while agentType == 2",
        "code": "0x934630",
    },
    {
        "definition_path": "Agents/FollowAgent/AngleFromEntity",
        "overridden_by": "AIBrainNode.followAngle",
        "when": "every think while agentType == 2",
        "code": "0x934650",
    },
]


def path_object_flags(flags):
    """The bits of a path-object table entry's `flags` (0x92d380, 0x92dfa0)."""
    return {
        "dynamic": bool(flags & 1),
        "per_entity_bits": (flags & 6) == 4,
        "initially_passable": bool(flags & 8),
    }


def mesh_link_gate(f):
    """(gate, crossable) of a mesh link's three trailing floats (0x9104d8)."""
    gate = {"dir_x": _f(-f[0]) + 0.0, "min_dot": _f(f[1]), "dir_z": _f(f[2])}
    return gate, not (f[0] == 0 and f[2] == 0 and f[1] >= 1.0)


def _mesh_link(s):
    gate, ok = mesh_link_gate(s[3])
    return {
        "a": _ev(s[0]),
        "b": _ev(s[1]),
        "to_sector": None if s[2][0] == NO_MESH else _sector(s[2][0]),
        "to": [s[2][1], s[2][2], s[2][3]],
        "gate": gate,
        "crossable": ok,
    }


def _sector(word):
    b = struct.pack("<I", word)
    s = struct.unpack("<4b", b)
    return {"word": word, "x": s[3], "z": s[1]}


def _stamp(date, time):
    if date is None or date == 0xBAFFE000:
        return None
    yy, mm, dd = date // 10000, date // 100 % 100, date % 100
    hh, mi, ss = time // 1000000, time // 10000 % 100, time // 100 % 100
    if not (1 <= mm <= 12 and 1 <= dd <= 31 and hh < 24 and mi < 60 and ss < 60):
        return None
    return "20%02d-%02d-%02d %02d:%02d:%02d" % (yy % 100, mm, dd, hh, mi, ss)


def build_document(hpd, config=None, level=None, source=None):
    """parse_hpd() result (+ parse_aipathdata() result) -> the `watchmen-nav/1` document."""
    h = hpd["header"]
    doc = {
        "format": FORMAT,
        "level": level,
        "source": source or {},
        "conventions": (
            dict(SPACE, note=NOTE_TRUE, glb_frame=GLB_FRAME_NOTE)
            if _frame.is_true()
            else dict(SPACE)
        ),
        "evidence": EVIDENCE,
        "header": {
            "version": _f(h["version"]),
            "cell_count": h["cell_count"],
            "cell_mode": "box" if h["cell_mode"] == 1 else "lattice",
            "lattice_origin_file": _v(h["lattice_origin"]),
            "lattice_cell_size": _f(h["lattice_cell_size"]),
            "vertex_attributes": [list(a) for a in h["vertex_attributes"]],
            "edge_attributes": [list(a) for a in h["edge_attributes"]],
            "vertex_stride": h["vertex_stride"],
            "edge_stride": h["edge_stride"],
        },
    }
    po_edges = {}
    cells = []
    tot = {"floors": 0, "triangles": 0, "area": 0.0, "open_outlines": 0}
    kinds = {
        "wall": 0,
        "link": 0,
        "mesh_link": 0,
        "mesh_link_closed": 0,
        "inner_wall": 0,
        "directional": 0,
    }
    for c in hpd["cells"]:
        oc = {
            "id": c["id"],
            "level": c["level"],
            "file_offset": c["file_offset"],
            "size": c["size"],
            "generated": _stamp(c.get("date"), c.get("time")),
        }
        if "box" in c:
            b = c["box"]
            oc["box_min"] = [_f(-b[1]) + 0.0, _f(b[2]), _f(b[4])]
            oc["box_max"] = [_f(-b[0]) + 0.0, _f(b[3]), _f(b[5])]
        else:
            oc["lattice"] = list(c["lattice"])
        oc["max_edge_length"] = (
            None if c.get("max_edge_length") is None else _f(c["max_edge_length"])
        )
        oc["vertices"] = [
            {
                "id": v["id"],
                "border": v["border"],
                "pos": _ev(v["pos"]),
                "first_edge": v["first_edge"],
                "abstract": v["abstract"],
            }
            for v in c["vertices"]
        ]
        oe = []
        for i, e in enumerate(c["edges"]):
            oe.append(
                {
                    "from": e["from"],
                    "to": e["to"],
                    "length": e["length_q"] / 16.0,
                    "path_object": e["path_object"] or None,
                    "unbound": e["unbound"],
                }
            )
            if e["path_object"]:
                po_edges.setdefault(e["path_object"], []).append((c, i, e))
        oc["edges"] = oe
        if c.get("sorted"):
            oc["sorted"] = {"x": c["sorted"][0], "y": c["sorted"][1], "z": c["sorted"][2]}
        m = c.get("mesh")
        if m:
            om = {
                "version": m["version"],
                "sector": _sector(m["sector_word"]),
                "cell_size": _f(m["cell_size"]),
                "grid": [m["nx"], m["nz"]],
                "bounds_min": [_f(-m["x_max"]) + 0.0, _f(m["z_min"])],
                "bounds_max": [_f(-m["x_min"]) + 0.0, _f(m["z_max"])],
                "file_x_min": _f(m["x_min"]),
                "margin": _f(m["margin"]),
                "radius": _f(m["radius"]),
                "unk_30": _f(m["unk_30"]),
                "floors": [],
            }
            for fl in m["floors"]:
                segs = [(to_engine(a), to_engine(b)) for a, b, _k in floor_segments(fl)]
                pts, tris, opn = triangulate(segs)
                area = sum(_tri_area(pts, t) for t in tris)
                of = {
                    "cell": list(fl["cell"]),
                    "index": fl["index"],
                    "alt_min": _f(fl["alt_min"]),
                    "alt_max": _f(fl["alt_max"]),
                    "area": round(area, 4),
                    "triangles": len(tris),
                    "outline": [[_ev(p) for p in pl] for pl in fl["outline"]],
                    "links": [
                        {"a": _ev(a), "b": _ev(b), "to": list(t)}
                        for (a, b), t in zip(fl["links"], fl["link_targets"])
                    ],
                    "mesh_links": [_mesh_link(s) for s in fl["mesh_links"]],
                    "inner_walls": [[_ev(p) for p in pl] for pl in fl["inner_walls"]],
                    "directional": [
                        {"dir": _ev(d), "polygon": [_ev(p) for p in pl]}
                        for d, pl in fl["directional"]
                    ],
                }
                if fl["level_links"]:
                    of["level_links"] = [
                        {"a": _ev(a), "b": _ev(b), "to": list(t)}
                        for (a, b), t in zip(fl["level_links"], fl["level_link_targets"])
                    ]
                if opn:
                    of["open_outline"] = True
                    tot["open_outlines"] += 1
                om["floors"].append(of)
                tot["floors"] += 1
                tot["triangles"] += len(tris)
                tot["area"] += area
                kinds["wall"] += sum(max(0, len(pl) - 1) for pl in fl["outline"])
                kinds["link"] += len(fl["links"])
                kinds["mesh_link"] += len(fl["mesh_links"])
                kinds["mesh_link_closed"] += sum(1 for x in of["mesh_links"] if not x["crossable"])
                kinds["inner_wall"] += len(fl["inner_walls"])
                kinds["directional"] += len(fl["directional"])
            oc["mesh"] = om
        else:
            oc["mesh"] = None
        cells.append(oc)
    doc["path_objects"] = []
    for p in hpd["path_objects"]:
        ends = []
        for c, i, e in po_edges.get(p["index"], ()):
            ends.append(
                {
                    "cell": c["id"],
                    "edge": i,
                    "from": _ev(c["vertices"][e["from"]]["pos"]),
                    "to": _ev(c["vertices"][e["to"]]["pos"]),
                }
            )
        doc["path_objects"].append(
            {
                "index": p["index"],
                "id": p["id"],
                "flags": p["flags"],
                "flags_decoded": path_object_flags(p["flags"]),
                "pool_type": p["pool_type"],
                "edges": ends,
            }
        )
    doc["cells"] = cells
    g = graph_summary(hpd)
    stamps = set(c["generated"] for c in cells)
    doc["summary"] = {
        "cells": len(cells),
        # the one stamp every cell carries; None when the cells disagree or have none
        "generated": stamps.pop() if len(stamps) == 1 else None,
        "graph": g,
        "mesh": {
            "floors": tot["floors"],
            "area": round(tot["area"], 2),
            "triangles": tot["triangles"],
            "open_outlines": tot["open_outlines"],
            "wall_segments": kinds["wall"],
            "links": kinds["link"],
            "mesh_links": kinds["mesh_link"],
            "mesh_links_never_crossable": kinds["mesh_link_closed"],
            "inner_walls": kinds["inner_wall"],
            "directional_zones": kinds["directional"],
        },
        "path_objects": len(hpd["path_objects"]),
    }
    und = list(hpd["undecoded"])
    doc["coverage"] = {
        "bytes": hpd["bytes"],
        "regions": [{"what": w, "offset": o, "size": s} for w, o, s in hpd["regions"]],
        "undecoded_regions": und,
        "undecoded_bytes": sum(u["size"] for u in und),
        "fields_of_unknown_meaning": [
            "header 0x4c..0x7b (second descriptor block, all zero)",
            "mesh +0x30 (a generation value the runtime does not read)",
            "cell tail word (0)",
        ],
    }
    if config is not None:
        doc["config"] = config_summary(config)
        doc["config_tree"] = config["root"]
        doc["config_runtime_overrides"] = CONFIG_RUNTIME_OVERRIDES
    return doc


def dumps(obj, indent=1):
    """JSON with one line per record: containers of plain numbers / strings, and
    dicts whose values are such, stay on one line."""

    def flat(o, depth=0):
        if isinstance(o, (list, tuple)):
            return depth < 3 and all(flat(x, depth + 1) for x in o)
        if isinstance(o, dict):
            return depth < 1 and len(o) <= 12 and all(flat(x, depth + 1) for x in o.values())
        return True

    def enc(o, lvl):
        if flat(o):
            return json.dumps(o)
        pad = " " * (indent * (lvl + 1))
        end = " " * (indent * lvl)
        if isinstance(o, dict):
            items = ["%s%s: %s" % (pad, json.dumps(str(k)), enc(v, lvl + 1)) for k, v in o.items()]
            return "{\n" + ",\n".join(items) + "\n" + end + "}"
        items = [pad + enc(v, lvl + 1) for v in o]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"

    return enc(obj, 0) + "\n"


# ---------------------------------------------------------------------------
# GLB
# ---------------------------------------------------------------------------

_MATERIALS = (
    ("nav_floor", (0.20, 0.65, 0.35, 1.0)),
    ("nav_wall", (0.90, 0.25, 0.20, 1.0)),
    ("nav_link", (0.20, 0.45, 0.95, 1.0)),
    ("nav_inner", (0.95, 0.60, 0.10, 1.0)),
    ("nav_graph", (0.95, 0.90, 0.20, 1.0)),
    ("nav_path_object", (0.85, 0.20, 0.85, 1.0)),
)


def nav_geometry(hpd):
    """Engine-space render geometry of a parsed file.

    -> dict name -> {"mode": 4 | 1 | 0, "points": [(x, y, z)], "indices": [...],
    "material": index}.  `navmesh` is triangles; the others are lines or points.
    """
    out = {}
    pts, idx = [], []
    lines = dict((k, ([], [])) for k in ("wall", "link", "inner", "edge", "po_edge"))

    def line(kind, a, b):
        p, i = lines[kind]
        i.extend((len(p), len(p) + 1))
        p.append(to_engine(a))
        p.append(to_engine(b))

    gv = []
    for c in hpd["cells"]:
        for v in c["vertices"]:
            gv.append(to_engine(v["pos"]))
        for e in c["edges"]:
            a, b = c["vertices"][e["from"]], c["vertices"][e["to"]]
            if a["id"] < b["id"] or not any(
                x["from"] == e["to"] and x["to"] == e["from"] for x in c["edges"]
            ):
                line("po_edge" if e["path_object"] else "edge", a["pos"], b["pos"])
        m = c.get("mesh")
        if not m:
            continue
        for fl in m["floors"]:
            segs = floor_segments(fl)
            p, t, _o = triangulate([(to_engine(a), to_engine(b)) for a, b, _k in segs])
            base = len(pts)
            pts.extend(p)
            for tri in t:
                idx.extend((base + tri[0], base + tri[1], base + tri[2]))
            for a, b, k in segs:
                line("wall" if k == "wall" else "link", a, b)
            for pl in fl["inner_walls"]:
                for a, b in zip(pl, pl[1:]):
                    line("inner", a, b)
            for _d, pl in fl["directional"]:
                for a, b in zip(pl, pl[1:]):
                    line("inner", a, b)
    out["navmesh"] = {"mode": 4, "points": pts, "indices": idx, "material": 0}
    for name, kind, mat in (
        ("navmesh_walls", "wall", 1),
        ("navmesh_links", "link", 2),
        ("navmesh_inner_walls", "inner", 3),
        ("graph_edges", "edge", 4),
        ("graph_path_object_edges", "po_edge", 5),
    ):
        out[name] = {
            "mode": 1,
            "points": lines[kind][0],
            "indices": lines[kind][1],
            "material": mat,
        }
    out["graph_vertices"] = {"mode": 0, "points": gv, "indices": None, "material": 4}
    return out


def build_glb(hpd, level=None):
    """Parsed file -> GLB bytes: the AI mesh as triangles, its boundary kinds and the
    graph as line primitives, graph vertices as points.  The file is in the frame
    of the toolkit's model exports (frame.mode(): true-handed by default, engine
    numbers with --frame mirrored), so it overlays the level geometry.  Nodes: navmesh, navmesh_walls, navmesh_links,
    navmesh_inner_walls, graph_edges, graph_path_object_edges, graph_vertices."""
    geo = nav_geometry(hpd)
    binbuf = bytearray()
    views, accessors, meshes, nodes = [], [], [], []

    def view(raw, target):
        while len(binbuf) % 4:
            binbuf.append(0)
        views.append(
            {"buffer": 0, "byteOffset": len(binbuf), "byteLength": len(raw), "target": target}
        )
        binbuf.extend(raw)
        return len(views) - 1

    for name, g in geo.items():
        if not g["points"]:
            continue
        p = np.asarray(g["points"], dtype="<f4").reshape(-1, 3)
        accessors.append(
            {
                "bufferView": view(p.tobytes(), 34962),
                "componentType": 5126,
                "count": int(len(p)),
                "type": "VEC3",
                "min": [float(x) for x in p.min(axis=0)],
                "max": [float(x) for x in p.max(axis=0)],
            }
        )
        prim = {
            "attributes": {"POSITION": len(accessors) - 1},
            "mode": g["mode"],
            "material": g["material"],
        }
        if g["indices"] is not None:
            i = np.asarray(g["indices"], dtype="<u4")
            accessors.append(
                {
                    "bufferView": view(i.tobytes(), 34963),
                    "componentType": 5125,
                    "count": int(len(i)),
                    "type": "SCALAR",
                }
            )
            prim["indices"] = len(accessors) - 1
        meshes.append({"name": name, "primitives": [prim]})
        nodes.append({"name": name, "mesh": len(meshes) - 1})
    root = {"name": "nav %s" % level if level else "nav", "children": list(range(len(nodes)))}
    nodes.append(root)
    while len(binbuf) % 4:
        binbuf.append(0)
    gltf = {
        "asset": {"version": "2.0", "generator": "watchmen-kapow-toolkit nav_data"},
        "scene": 0,
        "scenes": [{"nodes": [len(nodes) - 1]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [
            {
                "name": n,
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": list(c),
                    "metallicFactor": 0.0,
                    "roughnessFactor": 1.0,
                },
            }
            for n, c in _MATERIALS
        ],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(binbuf)}],
        "extras": {
            "format": FORMAT,
            "level": level,
            "space": GLB_SPACE_TRUE if _frame.is_true() else SPACE["note"],
        },
    }
    if not binbuf:
        del gltf["buffers"], gltf["bufferViews"], gltf["accessors"], gltf["meshes"]
    _frame.finish_gltf(gltf, binbuf)  # geo above is engine space; --frame true reflects it
    js = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    out = bytearray(b"glTF" + struct.pack("<II", 2, 0))
    out += struct.pack("<I4s", len(js), b"JSON") + js
    if binbuf:
        out += struct.pack("<I4s", len(binbuf), b"BIN\0") + bytes(binbuf)
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


# ---------------------------------------------------------------------------
# files
# ---------------------------------------------------------------------------


def _level_of(path):
    """.../<Level>/Gameplay/<file> -> <Level>; otherwise the file's stem."""
    parts = os.path.normpath(path).replace("\\", "/").split("/")
    if len(parts) >= 3 and parts[-2].lower() == "gameplay":
        return parts[-3]
    return os.path.splitext(parts[-1])[0]


def find_inputs(path):
    """A file, a directory tree or a list of trees -> [{"level", "hpd", "aipathdata"}]
    sorted by level.

    In a tree (an `extract` output, or a game data directory) every `.aipathdata`
    is paired with the `.hpd` its database Path names (compared case-insensitively
    by the trailing path components); an `.hpd` no definition names stands alone.
    """
    if isinstance(path, (list, tuple)):  # several trees searched as one
        trees = [str(p) for p in path]
    elif os.path.isfile(path):
        if path.lower().endswith(".aipathdata"):
            return [{"level": _level_of(path), "hpd": None, "aipathdata": path}]
        return [{"level": _level_of(path), "hpd": path, "aipathdata": None}]
    else:
        trees = [path]
    hpds, defs = [], []
    for tree in trees:
        if os.path.isfile(tree):  # a single file among the trees (a loose source's .hpd)
            if tree.lower().endswith(".hpd"):
                hpds.append(tree)
            elif tree.lower().endswith(".aipathdata"):
                defs.append(tree)
            continue
        for root, dirs, files in os.walk(tree):
            dirs.sort()
            for f in sorted(files):
                low = f.lower()
                if low.endswith(".hpd"):
                    hpds.append(os.path.join(root, f))
                elif low.endswith(".aipathdata"):
                    defs.append(os.path.join(root, f))
    used = set()
    out = []

    def key(p):
        return [x.lower() for x in p.replace("\\", "/").split("/") if x]

    for d in defs:
        want = None
        try:
            with open(d, "rb") as fh:
                want = database_path(parse_aipathdata(fh.read()))
        except (NavError, OSError):
            pass
        best, score = None, 0
        if want:
            w = key(want)
            for h in hpds:
                k = key(h)
                n = 0
                while n < min(len(w), len(k)) and w[-1 - n] == k[-1 - n]:
                    n += 1
                if n > score and h not in used:
                    best, score = h, n
        if best:
            used.add(best)
        out.append({"level": _level_of(want or d), "hpd": best, "aipathdata": d})
    for h in hpds:
        if h not in used:
            out.append({"level": _level_of(h), "hpd": h, "aipathdata": None})
    # one entry per level name: prefer the pair that has both files
    seen = {}
    for e in out:
        k = e["level"].lower()
        cur = seen.get(k)
        if cur is None or (e["hpd"] and e["aipathdata"] and not (cur["hpd"] and cur["aipathdata"])):
            seen[k] = e
    return sorted(seen.values(), key=lambda e: e["level"].lower())


#: what a loose-folder source keeps OUTSIDE the folder `extract` is given: the
#: sibling folder and the file names (lower case) the toolkit reads from it.  The
#: archives (.naz) hold the same files as data/... and data_baked/... entries.
#: The .bik movies (data/Art/cutscenes) are fetched for `textmeta`, which reads
#: their frame count and rate.
LOOSE_SIBLINGS = (("data", (".hpd", ".bik")), ("data_baked", ("database.bin",)))


def loose_source_files(source):
    """The files of a loose-folder game source that lie beside it and that the
    toolkit reads: navigation data, the game database and the movies.

    `extract` is given `.../derived_pc` (Part 1 PC) or `.../derived_x360` (Part 1
    Xbox Live); the path data sits in the sibling `data/` folder
    (data/Levels/Game_Levels/<Level>/Gameplay/<name>.hpd), the Bink movies in
    data/Art/cutscenes/<name>.bik and the game database in
    `data_baked/` (data_baked/tnt/production/database.bin).  -> [(name, path)]
    sorted by name, `name` as an archive would spell it ('data/Levels/.../x.hpd');
    [] for an archive, or a folder that has no such siblings (a folder that itself
    holds `data/` is searched too)."""
    source = os.path.abspath(str(source))
    if not os.path.isdir(source):
        return []
    out = {}
    for base in (os.path.dirname(source), source):
        for sub, ends in LOOSE_SIBLINGS:
            top = os.path.join(base, sub)
            if not os.path.isdir(top) or os.path.normcase(top) == os.path.normcase(source):
                continue
            for root, dirs, files in os.walk(top):
                dirs.sort()
                for f in sorted(files):
                    if f.lower().endswith(ends):
                        full = os.path.join(root, f)
                        name = sub + "/" + os.path.relpath(full, top).replace(os.sep, "/")
                        out.setdefault(name, full)
    return sorted(out.items())


def stage_loose_source(source, extract_out, log=None, names=None):
    """Copy loose_source_files(source) to <extract_out>/files/<name>, where the
    archive sets have them, so `navmeta` / `levelmeta` find the path data of a
    loose-folder extract like any other and `textmeta` the movies.  Existing files
    are replaced.  -> the copied names.

    Unless --names stored is in force the names are lower case, as every archive
    spells its entries (`data/Levels/Game_Levels/<Level>/Gameplay` of the folder
    becomes `data/levels/game_levels/<level>/gameplay`); `names` (a
    canonical_names.Run) records the folder's spelling."""
    import shutil

    import canonical_names

    done = []
    for name, path in loose_source_files(source):
        if names is not None:
            name = names.archive_name(name)
        else:
            name = canonical_names.archive_name(name)
        dst = os.path.join(str(extract_out), "files", *name.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(path, dst)
        done.append(name)
    if done and log:
        hp = sum(1 for n in done if n.lower().endswith(".hpd"))
        bk = sum(1 for n in done if n.lower().endswith(".bik"))
        log(
            "LOOSE SOURCE: %d file(s) from beside %s -> files/ "
            "(%d .hpd path data, %d .bik movie(s), %d other)"
            % (len(done), source, hp, bk, len(done) - hp - bk)
        )
    return done


def extract_trees(extract_out):
    """The two folders of an `extract` output that hold navigation files (`files/`:
    the .hpd, `extracted/`: the .aipathdata), or the folder itself when it has
    neither -- so an output folder full of exports is not walked as a whole."""
    extract_out = str(extract_out)
    sub = [os.path.join(extract_out, d) for d in ("files", "extracted")]
    sub = [d for d in sub if os.path.isdir(d)]
    return sub or [extract_out]


def export(src, out_dir, log=None):
    """Write <level>.nav.json (+ <level>.nav.glb when there is path data) for every
    level found under `src` (a file, a tree, or a list of trees).  The output folder
    is only created when there is something to write.  -> list of per-level result
    dicts."""
    found = find_inputs(src)
    if not found:
        return []
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for e in found:
        res = {"level": e["level"], "hpd": e["hpd"], "aipathdata": e["aipathdata"]}
        cfg = hpd = None
        try:
            if e["aipathdata"]:
                with open(e["aipathdata"], "rb") as fh:
                    cfg = parse_aipathdata(fh.read())
            if e["hpd"]:
                with open(e["hpd"], "rb") as fh:
                    hpd = parse_hpd(fh.read())
        except NavError as ex:
            res["error"] = str(ex)
            results.append(res)
            if log:
                log("  %-18s ERROR %s" % (e["level"], ex))
            continue
        source = {
            "hpd": os.path.basename(e["hpd"]) if e["hpd"] else None,
            "aipathdata": os.path.basename(e["aipathdata"]) if e["aipathdata"] else None,
        }
        base = os.path.join(out_dir, e["level"])
        if hpd is not None:
            doc = build_document(hpd, cfg, e["level"], source)
            with open(base + ".nav.glb", "wb") as fh:
                fh.write(build_glb(hpd, e["level"]))
            res["glb"] = base + ".nav.glb"
            res["summary"] = doc["summary"]
            res["undecoded_bytes"] = doc["coverage"]["undecoded_bytes"]
        else:
            doc = {
                "format": FORMAT,
                "level": e["level"],
                "source": source,
                "note": "no path data (.hpd) found for this definition",
                "config": config_summary(cfg),
                "config_tree": cfg["root"],
                "config_runtime_overrides": CONFIG_RUNTIME_OVERRIDES,
            }
        with open(base + ".nav.json", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(dumps(doc))
        res["json"] = base + ".nav.json"
        results.append(res)
        if log:
            if hpd is not None:
                s = doc["summary"]
                log(
                    "  %-18s %d cells, %d vertices, %d edges, %d floors (%d triangles, %.0f m2),"
                    " %d path objects, %d graph component(s), %d undecoded bytes"
                    % (
                        e["level"],
                        s["cells"],
                        s["graph"]["vertex_records"],
                        s["graph"]["edges"],
                        s["mesh"]["floors"],
                        s["mesh"]["triangles"],
                        s["mesh"]["area"],
                        s["path_objects"],
                        s["graph"]["components"],
                        res["undecoded_bytes"],
                    )
                )
            else:
                log("  %-18s definition only (no .hpd found)" % e["level"])
    return results


def main(argv):
    if len(argv) != 2:
        print("usage: nav_data.py FILE_OR_DIR OUT_DIR", file=sys.stderr)
        return 2
    if not os.path.exists(argv[0]):
        print("error: %s does not exist" % argv[0], file=sys.stderr)
        return 2
    src = extract_trees(argv[0]) if os.path.isdir(argv[0]) else argv[0]
    res = export(src, argv[1], log=print)
    if not res:
        print("error: no .hpd or .aipathdata under %s" % argv[0], file=sys.stderr)
        return 1
    bad = [r for r in res if "error" in r]
    print(
        "wrote %d level(s) to %s%s"
        % (len(res) - len(bad), argv[1], ", %d failed" % len(bad) if bad else "")
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
